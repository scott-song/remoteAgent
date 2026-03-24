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
from typing import Callable, Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    PatchMessageRequest,
    PatchMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)


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
        buttons.extend([
            "✅ `/commit`",
            "🧪 `/test`",
            "📋 `/diff`",
            "↩️ `/undo`",
        ])
    buttons.append("📝 `/continue`")
    return "  ".join(buttons)


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

    def on_message(self, callback: Callable):
        """Register callback: callback(chat_id, sender_id, sender_name, text, message_id)"""
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

        print(f"  [Feishu] WebSocket connecting (app: {self.app_id[:8]}...)")
        return thread

    def _on_event(self, data) -> None:
        """Handle incoming message event from Feishu."""
        try:
            message = data.event.message
            sender = data.event.sender

            # Dedup
            message_id = message.message_id
            if message_id in self._seen_ids:
                return
            self._seen_ids[message_id] = time.time()
            while len(self._seen_ids) > self._seen_max:
                self._seen_ids.popitem(last=False)

            # Only text messages
            if message.message_type != "text":
                return

            # Extract sender info
            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"

            # Parse text and remove @mention
            content = json.loads(message.content)
            text = content.get("text", "").strip()
            if hasattr(message, "mentions") and message.mentions:
                for mention in message.mentions:
                    text = text.replace(mention.key, "").strip()

            if not text:
                return

            chat_id = message.chat_id
            sender_name = sender_id  # Feishu doesn't give username in the event easily

            print(f"\n[Feishu] {sender_id[:8]}... in {chat_id[:8]}...: {text}")

            if self._on_message_callback:
                self._on_message_callback(chat_id, sender_id, sender_name, text, message_id)

        except Exception as e:
            print(f"[Feishu] Error handling message: {e}")
            import traceback
            traceback.print_exc()

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
            print(f"  [Feishu] Reply failed (attempt {attempt + 1}): {response.code} - {response.msg}")
            if attempt < UPDATE_MAX_RETRIES:
                time.sleep(UPDATE_RETRY_DELAY)

        if not response.success():
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
            print(f"  [Feishu] Plain reply failed (attempt {attempt + 1}): {response.code} - {response.msg}")
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
                print(f"  [Feishu] Send failed (attempt {attempt + 1}): {response.code} - {response.msg}")
                if attempt < UPDATE_MAX_RETRIES:
                    time.sleep(UPDATE_RETRY_DELAY)
            if not response.success():
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
                .request_body(
                    PatchMessageRequestBody.builder()
                    .content(card_content)
                    .build()
                )
                .build()
            )
            response = self.lark_client.im.v1.message.patch(request)
            if response.success():
                return
            print(f"  [Feishu] Update failed (attempt {attempt + 1}): {response.code} - {response.msg}")
            if attempt < UPDATE_MAX_RETRIES:
                time.sleep(UPDATE_RETRY_DELAY)
