"""
Feishu Bot Client
=================
Receives messages via WebSocket (lark-oapi SDK) and sends replies via REST API.
Uses interactive cards (schema 2.0) for rich message rendering.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
    Emoji,
    GetMessageResourceRequest,
    PatchMessageRequest,
    PatchMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from .attachments import (
    ACCEPTED_MSG_TYPES,
    ACK_EMOJI,
    IMAGE_MAX_BYTES,
    MAX_ATTACHMENTS,
    Attachment,
    attachment_store,
)
from .logging_config import get_logger

logger = get_logger(__name__)

# Feishu interactive card limit is ~28KB; leave margin for JSON overhead
CARD_MAX_BYTES = 25_000
UPDATE_MAX_RETRIES = 2
UPDATE_RETRY_DELAY = 0.5  # seconds


def build_action_buttons(has_code_changes: bool = True) -> str:
    """Build markdown action buttons for the end of a response card.

    Returns a markdown string with tap-friendly button labels that
    the user can copy-paste or that the bot recognizes as quick actions.

    Args:
        has_code_changes: If True, include code-related buttons (commit, diff, undo).
    """
    buttons = []
    if has_code_changes:
        buttons.extend(
            [
                "✅ `/commit`",
                "🧪 `/test`",
                "📋 `/diff`",
                "↩️ `/undo`",
            ]
        )
    buttons.append("📝 `/continue`")
    return "  ".join(buttons)


# Feishu message-content shapes: an `image` message carries one key; a `post`
# carries rich-text rows mixing text and `img` elements.
_ATTACHMENT_ERRORS = {
    "too_large": "⚠️ That image is over the 10 MB limit and was not attached.",
    "failed": "⚠️ Could not download that image from Feishu. Try sending it again.",
}


def _extract_text(msg_type: str, content: dict) -> str:
    """Pull the user's words out of a message body."""
    if msg_type == "post":
        parts = [
            element.get("text", "")
            for row in content.get("content", [])
            for element in row
            if element.get("tag") == "text"
        ]
        return " ".join(p for p in parts if p).strip()
    return str(content.get("text", "")).strip()


def _extract_image_keys(msg_type: str, content: dict) -> list[str]:
    """Every image key in the message, in document order."""
    if msg_type == "image":
        key = content.get("image_key")
        return [key] if key else []
    if msg_type == "post":
        return [
            element["image_key"]
            for row in content.get("content", [])
            for element in row
            if element.get("tag") == "img" and element.get("image_key")
        ]
    return []


class FeishuClient:
    """
    Feishu bot client.

    Connects via WebSocket (outbound — no public URL needed).
    Sends/updates messages via REST API with interactive cards.
    """

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret

        # Lark API client (for sending messages)
        self.lark_client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        # Bot's own user ID (set after first message received)
        self.bot_open_id: str = ""

        # Message dedup
        self._seen_ids: OrderedDict[str, float] = OrderedDict()
        self._seen_max = 500

        # Callback
        self._on_message_callback: Optional[Callable] = None

        # Event loop for async work
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Attachment holds; swappable for tests
        self.attachments = attachment_store

    def on_message(self, callback: Callable):
        """Register callback.

        callback(chat_id, sender_id, sender_name, text, message_id, attachments)
        where attachments is a list[Attachment] — empty for a plain text message.
        """
        self._on_message_callback = callback

    def start(self, loop: asyncio.AbstractEventLoop):
        """Start WebSocket connection in a background thread."""
        self._loop = loop

        # Build event handler
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_event)
            .build()
        )

        # Build WebSocket client
        ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        def _run_ws():
            import lark_oapi.ws.client as ws_module

            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            ws_module.loop = new_loop

            # Bypass proxy issues
            import os

            os.environ.setdefault("no_proxy", "*")

            import requests as _req

            _no_proxy_session = _req.Session()
            _no_proxy_session.trust_env = False
            ws_module.requests = _no_proxy_session

            ws_client.start()

        thread = threading.Thread(target=_run_ws, daemon=True)
        thread.start()

        logger.info(f"[Feishu] WebSocket connecting (app: {self.app_id[:8]}...)")
        return thread

    def _on_event(self, data: Any) -> None:
        """Handle incoming message event from Feishu.

        Runs on the lark WebSocket callback thread, which delivers events for
        every chat — so anything slow (a resource download) is offloaded to the
        bot's loop and this returns immediately.
        """
        try:
            message = data.event.message
            sender = data.event.sender

            # Dedup — upstream of any download, so a redelivered event neither
            # re-downloads nor re-reacts.
            message_id = message.message_id
            if message_id in self._seen_ids:
                return
            self._seen_ids[message_id] = time.time()
            while len(self._seen_ids) > self._seen_max:
                self._seen_ids.popitem(last=False)

            msg_type = message.message_type
            if msg_type != "text" and msg_type not in ACCEPTED_MSG_TYPES:
                return

            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            sender_name = sender_id  # Feishu doesn't give username in the event easily

            content = json.loads(message.content)
            text = _extract_text(msg_type, content)
            if hasattr(message, "mentions") and message.mentions:
                for mention in message.mentions:
                    text = text.replace(mention.key, "").strip()

            image_keys = _extract_image_keys(msg_type, content)
            if image_keys:
                if self._loop is None:
                    logger.error("[Feishu] No loop available — cannot fetch attachment")
                    self.reply(message_id, _ATTACHMENT_ERRORS["failed"])
                    return
                logger.info(
                    f"[Feishu] {sender_id[:8]}... in {chat_id[:8]}...: "
                    f"{len(image_keys)} image(s) + {len(text)} chars"
                )
                asyncio.run_coroutine_threadsafe(
                    self._handle_attachments(data, chat_id, sender_id, sender_name, text),
                    self._loop,
                )
                return

            if not text:
                return

            logger.info(f"[Feishu] {sender_id[:8]}... in {chat_id[:8]}...: {text}")

            if self._on_message_callback:
                self._on_message_callback(chat_id, sender_id, sender_name, text, message_id, [])

        except Exception as e:
            logger.error(f"[Feishu] Error handling message: {e}", exc_info=True)

    async def _handle_attachments(
        self, data: Any, chat_id: str, sender_id: str, sender_name: str, text: str
    ) -> None:
        """Download, hold and acknowledge a message's images.

        Runs on the bot's loop; each blocking download goes to a worker thread so
        neither the WebSocket thread nor the loop stalls (NFR-1).
        """
        message = data.event.message
        message_id = message.message_id
        content = json.loads(message.content)

        # Cap downloads per message, not just per prompt: a post can embed
        # arbitrarily many images, and the cap must bound transfer.
        keys = _extract_image_keys(message.message_type, content)[:MAX_ATTACHMENTS]

        loop = asyncio.get_running_loop()
        attachments: list[Attachment] = []
        failures: list[str] = []

        for key in keys:
            try:
                payload, reason = await loop.run_in_executor(
                    None, self.download_resource, message_id, key
                )
            except Exception as e:
                logger.error(f"[Feishu] Attachment fetch raised for {key[:8]}...: {e}")
                failures.append("failed")
                continue

            if payload is None:
                failures.append(reason or "failed")
                continue

            attachment = self.attachments.put(sender_id, chat_id, payload)
            if attachment is None:
                failures.append("failed")
                continue
            attachments.append(attachment)

        # One reply per distinct cause, so five bad images are not five replies.
        for reason in dict.fromkeys(failures):
            self.reply(message_id, _ATTACHMENT_ERRORS.get(reason, _ATTACHMENT_ERRORS["failed"]))

        if not attachments and not text:
            return

        if not text:
            # A bare image is acknowledged with a reaction and starts no turn.
            self.react(message_id)
            return

        if self._on_message_callback:
            self._on_message_callback(
                chat_id, sender_id, sender_name, text, message_id, attachments
            )

    # ── Send / Update Messages ────────────────────────────

    def _build_card(self, text: str) -> str:
        """Build a Feishu interactive card (schema 2.0 with markdown)."""
        card = {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "body": {
                "elements": [
                    {"tag": "markdown", "content": text},
                ],
            },
        }
        return json.dumps(card)

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks that fit within Feishu card size limits."""
        overhead = len(self._build_card("").encode("utf-8"))
        max_content = CARD_MAX_BYTES - overhead
        if len(text.encode("utf-8")) <= max_content:
            return [text]

        chunks: list[str] = []
        remaining = text
        while remaining:
            encoded = remaining.encode("utf-8")
            if len(encoded) <= max_content:
                chunks.append(remaining)
                break
            # Find cut point at last newline before limit
            cut = encoded[:max_content].rfind(b"\n")
            if cut <= 0:
                # No newline found — cut at byte boundary
                cut = max_content
            chunk_text = encoded[:cut].decode("utf-8", errors="ignore")
            chunks.append(chunk_text)
            remaining = encoded[cut:].decode("utf-8", errors="ignore").lstrip("\n")
        return chunks

    def reply(self, message_id: str, text: str, chat_id: str = ""):
        """Reply to a specific message with an interactive card.

        If text exceeds Feishu card limits, overflow chunks are sent as
        separate messages (requires chat_id). Without chat_id, content
        is truncated.
        """
        chunks = self._chunk_text(text)
        if len(chunks) > 1 and not chat_id:
            # No chat_id for overflow — truncate with indicator
            chunks = [chunks[0] + "\n\n*(message truncated)*"]

        card_content = self._build_card(chunks[0])
        response = None
        for attempt in range(1 + UPDATE_MAX_RETRIES):
            request = (
                ReplyMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .msg_type("interactive")
                    .content(card_content)
                    .build()
                )
                .build()
            )
            response = self.lark_client.im.v1.message.reply(request)
            if response.success():
                break
            logger.warning(
                f"[Feishu] Reply failed (attempt {attempt + 1}): {response.code} - {response.msg}"
            )
            if attempt < UPDATE_MAX_RETRIES:
                time.sleep(UPDATE_RETRY_DELAY)

        if not (response and response.success()):
            self._reply_plain(message_id, text[:4000])
            return

        # Send overflow chunks as new messages
        for chunk in chunks[1:]:
            self.send_message(chat_id, chunk)

    def _reply_plain(self, message_id: str, text: str):
        """Fallback: reply as plain text with retry (truncated to 4000 chars)."""
        for attempt in range(1 + UPDATE_MAX_RETRIES):
            request = (
                ReplyMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .msg_type("text")
                    .content(json.dumps({"text": text[:4000]}))
                    .build()
                )
                .build()
            )
            response = self.lark_client.im.v1.message.reply(request)
            if response.success():
                return
            logger.warning(
                f"[Feishu] Plain reply failed (attempt {attempt + 1}): "
                f"{response.code} - {response.msg}"
            )
            if attempt < UPDATE_MAX_RETRIES:
                time.sleep(UPDATE_RETRY_DELAY)

    def send_message(self, chat_id: str, text: str) -> str:
        """Send a new message to a chat. Returns first message_id.

        If text exceeds Feishu card limits, it is split into multiple
        messages. The first message's ID is returned.
        """
        chunks = self._chunk_text(text)
        first_msg_id = ""
        for i, chunk in enumerate(chunks):
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("interactive")
                    .content(self._build_card(chunk))
                    .build()
                )
                .build()
            )
            response = None
            for attempt in range(1 + UPDATE_MAX_RETRIES):
                response = self.lark_client.im.v1.message.create(request)
                if response.success():
                    break
                logger.warning(
                    f"[Feishu] Send failed (attempt {attempt + 1}): "
                    f"{response.code} - {response.msg}"
                )
                if attempt < UPDATE_MAX_RETRIES:
                    time.sleep(UPDATE_RETRY_DELAY)
            if not (response and response.success()):
                if i == 0:
                    return ""
                continue
            msg_id = response.data.message_id if response.data else ""
            if i == 0:
                first_msg_id = msg_id
        return first_msg_id

    def update_message(self, message_id: str, text: str):
        """Update an existing message (for streaming) with retry logic.

        Since we can only update a single message, content is truncated
        to fit within Feishu card limits.
        """
        # Truncate for update (can't split into multiple messages mid-stream)
        chunks = self._chunk_text(text)
        content_text = chunks[0]
        if len(chunks) > 1:
            content_text = chunks[0] + "\n\n*(content truncated — full response will follow)*"

        card_content = self._build_card(content_text)
        self._patch_message(message_id, card_content)

    def _patch_message(self, message_id: str, card_content: str):
        """Low-level message patch with retry logic."""
        for attempt in range(1 + UPDATE_MAX_RETRIES):
            request = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(PatchMessageRequestBody.builder().content(card_content).build())
                .build()
            )
            response = self.lark_client.im.v1.message.patch(request)
            if response.success():
                return
            logger.warning(
                f"[Feishu] Update failed (attempt {attempt + 1}): {response.code} - {response.msg}"
            )
            if attempt < UPDATE_MAX_RETRIES:
                time.sleep(UPDATE_RETRY_DELAY)

    # ── Attachments ───────────────────────────────────────

    def download_resource(
        self, message_id: str, file_key: str, *, max_bytes: int = IMAGE_MAX_BYTES
    ) -> tuple[bytes | None, str | None]:
        """Fetch a message resource's bytes.

        Returns ``(data, None)`` on success, else ``(None, reason)`` where reason
        is ``"too_large"`` (AC-7) or ``"failed"`` (AC-8) — the two cases carry
        different user-facing replies, so they must stay distinguishable.

        Reads at most ``max_bytes + 1`` so an oversized resource is rejected
        without ever being fully buffered.
        """
        request = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type("image")
            .build()
        )
        response = None
        for attempt in range(1 + UPDATE_MAX_RETRIES):
            response = self.lark_client.im.v1.message_resource.get(request)
            if response.success():
                break
            logger.warning(
                f"[Feishu] Resource fetch failed (attempt {attempt + 1}): "
                f"{response.code} - {response.msg}"
            )
            if attempt < UPDATE_MAX_RETRIES:
                time.sleep(UPDATE_RETRY_DELAY)

        if not (response and response.success()):
            return None, "failed"

        stream = getattr(response, "file", None)
        if stream is None:
            logger.warning(f"[Feishu] Resource {file_key[:8]}... returned no stream")
            return None, "failed"

        data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            logger.warning(
                f"[Feishu] Resource {file_key[:8]}... exceeds {max_bytes} bytes — rejected"
            )
            return None, "too_large"
        return data, None

    def react(self, message_id: str, emoji_type: str = ACK_EMOJI) -> bool:
        """Add one emoji reaction to a message.

        Returns False on failure and **never** falls back to a reply: AC-3
        acknowledges receipt without adding a chat message, so a failed
        acknowledgement stays in the log.
        """
        request = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                .build()
            )
            .build()
        )
        response = self.lark_client.im.v1.message_reaction.create(request)
        if response.success():
            return True
        logger.warning(f"[Feishu] Reaction failed: {response.code} - {response.msg}")
        return False
