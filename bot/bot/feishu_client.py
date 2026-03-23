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

    def reply(self, message_id: str, text: str):
        """Reply to a specific message with an interactive card."""
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("interactive")
                .content(self._build_card(text))
                .build()
            )
            .build()
        )
        response = self.lark_client.im.v1.message.reply(request)
        if not response.success():
            print(f"  [Feishu] Reply failed: {response.code} - {response.msg}")
            self._reply_plain(message_id, text)

    def _reply_plain(self, message_id: str, text: str):
        """Fallback: reply as plain text."""
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )
        self.lark_client.im.v1.message.reply(request)

    def send_message(self, chat_id: str, text: str) -> str:
        """Send a new message to a chat. Returns message_id."""
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(self._build_card(text))
                .build()
            )
            .build()
        )
        response = self.lark_client.im.v1.message.create(request)
        if not response.success():
            print(f"  [Feishu] Send failed: {response.code} - {response.msg}")
            return ""
        return response.data.message_id if response.data else ""

    def update_message(self, message_id: str, text: str):
        """Update an existing message (for streaming)."""
        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                PatchMessageRequestBody.builder()
                .content(self._build_card(text))
                .build()
            )
            .build()
        )
        response = self.lark_client.im.v1.message.patch(request)
        if not response.success():
            print(f"  [Feishu] Update failed: {response.code} - {response.msg}")
