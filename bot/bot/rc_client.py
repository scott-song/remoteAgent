"""
Rocket.Chat Client
==================
Handles DDP WebSocket connection (receive messages) and REST API (send/update messages).
Each bot user gets its own RCClient instance.
"""

import json
import threading
import time
from collections import OrderedDict
from typing import Callable, Optional

import requests
import websocket


class RCClient:
    """
    Rocket.Chat client for a single bot user.

    Connects via DDP WebSocket to receive messages.
    Uses REST API to send and update messages.
    """

    def __init__(self, server_url: str, username: str, password: str):
        self.server_url = server_url.rstrip("/")
        self.ws_url = self.server_url.replace("http", "ws") + "/websocket"
        self.username = username
        self.password = password

        self.user_id: str = ""
        self.auth_token: str = ""
        self.ws: Optional[websocket.WebSocketApp] = None

        # Message dedup
        self._seen_ids: OrderedDict[str, float] = OrderedDict()
        self._seen_max = 500

        # Callbacks
        self._on_message_callback: Optional[Callable] = None

        # DDP state
        self._ddp_connected = False
        self._sub_id = 0

    def login(self):
        """Authenticate via REST API and get auth token."""
        resp = requests.post(
            f"{self.server_url}/api/v1/login",
            data={"user": self.username, "password": self.password},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            raise RuntimeError(f"Login failed: {data}")

        self.user_id = data["data"]["userId"]
        self.auth_token = data["data"]["authToken"]
        print(f"  [RC] Logged in as {self.username} (id: {self.user_id[:8]}...)")

    def on_message(self, callback: Callable):
        """Register callback for incoming messages: callback(room_id, sender_id, sender_username, text)"""
        self._on_message_callback = callback

    def connect_ws(self):
        """Connect DDP WebSocket in a background thread."""
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        thread = threading.Thread(
            target=lambda: self.ws.run_forever(reconnect=5),
            daemon=True,
        )
        thread.start()
        print(f"  [RC] WebSocket connecting to {self.ws_url}")

    def _next_sub_id(self) -> str:
        self._sub_id += 1
        return f"sub-{self._sub_id}"

    def _on_ws_open(self, ws):
        # DDP connect
        ws.send(json.dumps({"msg": "connect", "version": "1", "support": ["1"]}))

        # DDP login
        ws.send(json.dumps({
            "msg": "method",
            "method": "login",
            "id": "login-1",
            "params": [{"resume": self.auth_token}],
        }))

        # Subscribe to messages visible to this bot user
        ws.send(json.dumps({
            "msg": "sub",
            "id": self._next_sub_id(),
            "name": "stream-room-messages",
            "params": ["__my_messages__", False],
        }))

        self._ddp_connected = True
        print(f"  [RC] WebSocket connected, subscribed to messages")

    def _on_ws_message(self, ws, raw):
        data = json.loads(raw)

        # Keepalive
        if data.get("msg") == "ping":
            ws.send(json.dumps({"msg": "pong"}))
            return

        # Only handle room message events
        if data.get("collection") != "stream-room-messages":
            return

        for msg in data.get("fields", {}).get("args", []):
            self._handle_incoming_message(msg)

    def _handle_incoming_message(self, msg: dict):
        # Skip own messages
        sender_id = msg.get("u", {}).get("_id", "")
        if sender_id == self.user_id:
            return

        # Skip system messages
        if msg.get("t"):
            return

        # Dedup
        msg_id = msg.get("_id", "")
        if msg_id in self._seen_ids:
            return
        self._seen_ids[msg_id] = time.time()
        while len(self._seen_ids) > self._seen_max:
            self._seen_ids.popitem(last=False)

        # Extract text
        text = msg.get("msg", "").strip()
        if not text:
            return

        # Remove @mention of this bot
        text = text.replace(f"@{self.username}", "").strip()
        if not text:
            return

        room_id = msg.get("rid", "")
        sender_username = msg.get("u", {}).get("username", "?")

        if self._on_message_callback:
            self._on_message_callback(room_id, sender_id, sender_username, text)

    def _on_ws_error(self, ws, error):
        print(f"  [RC] WebSocket error: {error}")

    def _on_ws_close(self, ws, code, reason):
        self._ddp_connected = False
        print(f"  [RC] WebSocket closed: {code} {reason}")

    # ── REST API: Send & Update Messages ──────────────────

    def _auth_headers(self) -> dict:
        return {
            "X-Auth-Token": self.auth_token,
            "X-User-Id": self.user_id,
            "Content-Type": "application/json",
        }

    def send_message(self, room_id: str, text: str, metadata: Optional[dict] = None) -> str:
        """Send a new message. Returns the message _id."""
        payload = {"channel": room_id, "text": text}
        if metadata:
            payload["customFields"] = metadata

        resp = requests.post(
            f"{self.server_url}/api/v1/chat.sendMessage",
            headers=self._auth_headers(),
            json={"message": {"rid": room_id, "msg": text, **({"customFields": metadata} if metadata else {})}},
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("_id", "")

    def update_message(self, room_id: str, msg_id: str, text: str, metadata: Optional[dict] = None):
        """Update an existing message (for streaming)."""
        payload = {"roomId": room_id, "msgId": msg_id, "text": text}
        if metadata:
            payload["customFields"] = metadata

        resp = requests.post(
            f"{self.server_url}/api/v1/chat.update",
            headers=self._auth_headers(),
            json={"roomId": room_id, "msgId": msg_id, "text": text},
        )
        resp.raise_for_status()
