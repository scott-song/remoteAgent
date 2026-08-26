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

# How long a text message waits for this sender's in-flight image receives
# before being delivered anyway (review F-14). A stuck Feishu call can burn
# ~90s (30s timeout x 3 attempts); waiting that long leaves the user with no
# reply at all, which is worse than the missing-image answer the wait exists to
# prevent. Bounded here, so the failure degrades to "visible and wrong" rather
# than "silent".
DELIVERY_GRACE_SECONDS = 3.0


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

    def __init__(self, app_id: str, app_secret: str, accept_attachments: bool = False):
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

        # Attachment holds; swappable for tests. Opt-in per bot: a consumer with
        # no drain path (no take/purge) would accumulate images forever, so the
        # default is off and the coder bot turns it on explicitly (F-5).
        self.attachments = attachment_store
        self.accept_attachments = accept_attachments

        # In-flight receives per (sender, chat). A text message arriving while a
        # download is still running must wait for it, or it drains an empty hold
        # and the image lands on the *next*, unrelated message (F-1).
        self._inflight: dict[str, list[Any]] = {}
        self._inflight_lock = threading.Lock()

        # Serializes attachment handling per (sender, chat) on the bot loop, so
        # two receives from one sender cannot settle out of order and deliver a
        # callback that sees only its own image (review F-13). Loop-only, so an
        # asyncio lock is the right primitive and needs no thread lock.
        self._key_locks: dict[str, asyncio.Lock] = {}

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

            image_keys = _extract_image_keys(msg_type, content) if self.accept_attachments else []
            if image_keys:
                if self._loop is None:
                    logger.error("[Feishu] No loop available — cannot fetch attachment")
                    self.reply(message_id, _ATTACHMENT_ERRORS["failed"])
                    return
                logger.info(
                    f"[Feishu] {sender_id[:8]}... in {chat_id[:8]}...: "
                    f"{len(image_keys)} image(s) + {len(text)} chars"
                )
                job = asyncio.run_coroutine_threadsafe(
                    self._handle_attachments(data, chat_id, sender_id, sender_name, text),
                    self._loop,
                )
                self._track_inflight(sender_id, chat_id, job)
                return

            if not text:
                return

            # A text message from a sender whose download is still running must
            # not drain the hold yet — deliver it behind that receive (F-1).
            waiting = self._inflight_for(sender_id, chat_id)
            if waiting and self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._deliver_after(waiting, chat_id, sender_id, sender_name, text, message_id),
                    self._loop,
                )
                return

            logger.info(f"[Feishu] {sender_id[:8]}... in {chat_id[:8]}...: {text}")

            if self._on_message_callback:
                self._on_message_callback(chat_id, sender_id, sender_name, text, message_id, [])

        except Exception as e:
            logger.error(f"[Feishu] Error handling message: {e}", exc_info=True)

    def _track_inflight(self, sender_id: str, chat_id: str, job: Any) -> None:
        key = f"{sender_id}:{chat_id}"
        with self._inflight_lock:
            self._inflight.setdefault(key, []).append(job)

        def _done(_f: Any, k: str = key) -> None:
            with self._inflight_lock:
                jobs = [j for j in self._inflight.get(k, []) if not j.done()]
                if jobs:
                    self._inflight[k] = jobs
                else:
                    self._inflight.pop(k, None)

        job.add_done_callback(_done)

    def _inflight_for(self, sender_id: str, chat_id: str) -> list[Any]:
        with self._inflight_lock:
            return [j for j in self._inflight.get(f"{sender_id}:{chat_id}", []) if not j.done()]

    async def _deliver_after(
        self,
        jobs: list[Any],
        chat_id: str,
        sender_id: str,
        sender_name: str,
        text: str,
        message_id: str,
    ) -> None:
        """Invoke the callback once this sender's in-flight receives have settled.

        A failed receive must not swallow the user's message, so each wait is
        independent and its error is logged, never raised.
        """
        try:
            await asyncio.wait_for(
                asyncio.gather(*(asyncio.wrap_future(job) for job in jobs), return_exceptions=True),
                timeout=DELIVERY_GRACE_SECONDS,
            )
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning(
                f"[Feishu] Delivering {message_id} after {DELIVERY_GRACE_SECONDS}s without its "
                "in-flight image(s) — a pending receive is slow; the text goes through rather "
                "than leaving the sender with no reply"
            )
        if self._on_message_callback:
            self._on_message_callback(chat_id, sender_id, sender_name, text, message_id, [])

    async def _handle_attachments(
        self, data: Any, chat_id: str, sender_id: str, sender_name: str, text: str
    ) -> None:
        """Download, hold and acknowledge a message's images.

        Runs on the bot's loop; each blocking download goes to a worker thread so
        neither the WebSocket thread nor the loop stalls (NFR-1).
        """
        started = time.time()
        message = data.event.message
        message_id = message.message_id
        content = json.loads(message.content)

        # One receive at a time per sender+chat: a captioned post that finished
        # first would otherwise hand the callback only its own image, leaving an
        # earlier paste to ride the next, unrelated message (F-13).
        key = f"{sender_id}:{chat_id}"
        lock = self._key_locks.setdefault(key, asyncio.Lock())
        async with lock:
            await self._receive_attachments(
                data, message_id, content, chat_id, sender_id, sender_name, text, started
            )
        if not lock.locked():
            self._key_locks.pop(key, None)

    async def _receive_attachments(
        self,
        data: Any,
        message_id: str,
        content: dict,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        text: str,
        started: float,
    ) -> None:
        """Download, hold and acknowledge — serialized per sender by the caller."""
        message = data.event.message

        # Cap downloads per message, not just per prompt: a post can embed
        # arbitrarily many images, and the cap must bound transfer.
        keys = _extract_image_keys(message.message_type, content)[:MAX_ATTACHMENTS]

        loop = asyncio.get_running_loop()
        attachments: list[Attachment] = []
        failures: list[str] = []

        for key in keys:
            try:
                payload, reason, observed = await loop.run_in_executor(
                    None, self.download_resource, message_id, key
                )
            except Exception as e:
                logger.error(f"[Feishu] Attachment fetch raised for {key[:8]}...: {e}")
                self._log_receipt("rejected:error", sender_id, chat_id, 0, message_id)
                failures.append("failed")
                continue

            if payload is None:
                self._log_receipt(
                    f"rejected:{reason or 'failed'}",
                    sender_id,
                    chat_id,
                    observed,
                    message_id,
                    size_is_floor=(reason == "too_large"),
                )
                failures.append(reason or "failed")
                continue

            attachment = self.attachments.put(sender_id, chat_id, payload)
            if attachment is None:
                self._log_receipt(
                    "rejected:unstorable", sender_id, chat_id, len(payload), message_id
                )
                failures.append("failed")
                continue

            self._log_receipt("accepted", sender_id, chat_id, attachment.size, message_id)
            attachments.append(attachment)

        # One reply per distinct cause, so five bad images are not five replies.
        for reason in dict.fromkeys(failures):
            self.reply(message_id, _ATTACHMENT_ERRORS.get(reason, _ATTACHMENT_ERRORS["failed"]))

        if not attachments and not text:
            return

        if not text:
            # A bare image is acknowledged with a reaction and starts no turn.
            if self.react(message_id):
                elapsed_ms = int((time.time() - started) * 1000)
                logger.info(
                    f"[Feishu] attachment ack sent ack_ms={elapsed_ms} msg={message_id} "
                    "(budget 5000ms)"
                )
            return

        # Everything received is already held, so the callback carries NOTHING
        # inline and the consumer's single `take()` is the only drain. Passing
        # them inline as well double-attached a captioned post's own image —
        # once from the store, once from the callback — costing double vision
        # tokens and two of the five cap slots.
        if self._on_message_callback:
            self._on_message_callback(chat_id, sender_id, sender_name, text, message_id, [])

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
    ) -> tuple[bytes | None, str | None, int]:
        """Fetch a message resource's bytes.

        Returns ``(data, None, size)`` on success, else ``(None, reason, size)``
        where reason is ``"too_large"`` (AC-7) or ``"failed"`` (AC-8) — the two
        carry different user-facing replies, so they must stay distinguishable.

        ``size`` is the byte count actually observed, which AC-14 needs on the
        rejection path too: for ``"too_large"`` the size *is* the reason.

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
            return None, "failed", 0

        stream = getattr(response, "file", None)
        if stream is None:
            logger.warning(f"[Feishu] Resource {file_key[:8]}... returned no stream")
            return None, "failed", 0

        data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            logger.warning(
                f"[Feishu] Resource {file_key[:8]}... exceeds {max_bytes} bytes — rejected"
            )
            return None, "too_large", len(data)
        return data, None, len(data)

    @staticmethod
    def _log_receipt(
        disposition: str,
        sender_id: str,
        chat_id: str,
        size: int,
        message_id: str,
        size_is_floor: bool = False,
    ) -> None:
        """One line per accepted or rejected attachment (AC-14).

        Carries the disposition, sender, chat and size — never the bytes, and
        never a path to a copy kept only for logging (BR-7).

        ``size_is_floor`` renders ``size>=N``: an oversized read stops at
        ``max_bytes + 1``, so the true size is unknown and reporting that bound
        as an exact figure would be a lie (review F-15).
        """
        rendered = f"size>={size}" if size_is_floor else f"size={size}"
        logger.info(
            f"[Feishu] attachment {disposition} sender={sender_id[:8]} "
            f"chat={chat_id[:8]} {rendered} msg={message_id}"
        )

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
        for attempt in range(1 + UPDATE_MAX_RETRIES):
            response = self.lark_client.im.v1.message_reaction.create(request)
            if response.success():
                return True
            logger.warning(
                f"[Feishu] Reaction failed (attempt {attempt + 1}): "
                f"{response.code} - {response.msg}"
            )
            if attempt < UPDATE_MAX_RETRIES:
                time.sleep(UPDATE_RETRY_DELAY)
        return False
