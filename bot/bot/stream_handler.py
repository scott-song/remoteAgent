"""
Stream Handler
==============
Streams Claude Agent SDK responses to Rocket.Chat
by progressively updating a message with structured metadata.
"""

import time
from typing import Optional

from .rc_client import RCClient


class StreamHandler:
    """
    Accumulates Claude response and pushes throttled updates to Rocket.Chat.

    Builds a structured metadata payload alongside the text so the
    RC frontend can render tool calls, diffs, and terminal output richly.
    """

    def __init__(
        self,
        rc: RCClient,
        room_id: str,
        msg_id: str,
        agent_name: str,
        interval: float = 1.5,
    ):
        self.rc = rc
        self.room_id = room_id
        self.msg_id = msg_id
        self.agent_name = agent_name
        self.interval = interval

        self.response_text = ""
        self.tools: list[dict] = []
        self._last_update = 0.0

    def on_text(self, text: str):
        """Append text from a TextBlock."""
        self.response_text += text
        self._maybe_update()

    def on_tool_start(self, name: str, tool_input: dict):
        """Record start of a tool call."""
        self.tools.append({
            "name": name,
            "input": tool_input,
            "status": "running",
            "started_at": time.time(),
        })
        self._maybe_update()

    def on_tool_result(self, content: str, is_error: bool):
        """Record tool result — updates the last tool entry."""
        if self.tools:
            tool = self.tools[-1]
            tool["status"] = "error" if is_error else "success"
            tool["output"] = content[:2000]  # truncate large outputs
            tool["duration_ms"] = int((time.time() - tool.get("started_at", time.time())) * 1000)
        self._maybe_update()

    def finalize(self, duration_str: str, mode: str, session_id: Optional[str] = None):
        """Send final update with complete response."""
        metadata = self._build_metadata(streaming=False, mode=mode, session_id=session_id)
        metadata["duration"] = duration_str

        text = self.response_text or "(no response)"
        self.rc.update_message(self.room_id, self.msg_id, text, metadata)

    def _maybe_update(self):
        """Send an update if enough time has passed since the last one."""
        now = time.time()
        if now - self._last_update < self.interval:
            return

        text = self.response_text or "..."
        metadata = self._build_metadata(streaming=True)
        self.rc.update_message(self.room_id, self.msg_id, text, metadata)
        self._last_update = now

    def _build_metadata(
        self,
        streaming: bool = True,
        mode: str = "",
        session_id: Optional[str] = None,
    ) -> dict:
        """Build the structured metadata payload for the RC message."""
        meta = {
            "claude": True,
            "agent": self.agent_name,
            "streaming": streaming,
            "tools": [
                {
                    "name": t["name"],
                    "input": _summarize_input(t["input"]),
                    "status": t["status"],
                    "output": t.get("output", ""),
                    "duration_ms": t.get("duration_ms", 0),
                }
                for t in self.tools
            ],
        }
        if mode:
            meta["mode"] = mode
        if session_id:
            meta["session_id"] = session_id
        return meta


def _summarize_input(tool_input: dict) -> dict:
    """Truncate large input values for metadata."""
    result = {}
    for k, v in tool_input.items():
        s = str(v)
        result[k] = s[:200] + "..." if len(s) > 200 else s
    return result
