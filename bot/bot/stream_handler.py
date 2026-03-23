"""
Stream handler — streams Claude responses to Feishu via progressive message updates.
"""

from __future__ import annotations

import time
from typing import Optional

from .feishu_client import FeishuClient


class StreamHandler:
    def __init__(self, client: FeishuClient, chat_id: str, msg_id: str, agent_name: str, interval: float = 1.5):
        self.client = client
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.agent_name = agent_name
        self.interval = interval
        self.response_text = ""
        self.tools: list[dict] = []
        self._last_update = 0.0
        self._tools_rendered_count = 0  # tracks how many tools have been rendered as final

    def on_text(self, text: str):
        self.response_text += text
        self._maybe_update()

    def on_tool_start(self, name: str, tool_input: dict):
        self.tools.append({"name": name, "input": tool_input, "status": "running", "started_at": time.time()})
        self._maybe_update()

    def on_tool_result(self, content: str, is_error: bool):
        if self.tools:
            tool = self.tools[-1]
            tool["status"] = "error" if is_error else "success"
            tool["output"] = content[:2000]
            tool["duration_ms"] = int((time.time() - tool.get("started_at", time.time())) * 1000)
        self._maybe_update()

    def finalize(self, duration_str: str, mode: str, session_id: Optional[str] = None):
        self.client.update_message(self.msg_id, self._render_final(duration_str, mode))

    def _maybe_update(self):
        now = time.time()
        if now - self._last_update < self.interval:
            return
        self.client.update_message(self.msg_id, self._render_streaming())
        self._last_update = now

    def _render_streaming(self) -> str:
        parts = [_render_tool(t) for t in self.tools]
        if self.response_text:
            parts.append(self.response_text)
        parts.append("\n⏳ Working...")
        return "\n".join(parts)

    def _render_final(self, duration_str: str, mode: str) -> str:
        parts = []
        if self.tools:
            parts.extend(_render_tool(t) for t in self.tools)
            parts.append("---")
        parts.append(self.response_text or "(no response)")
        parts.append(f"\n*{duration_str} | {mode}*")
        return "\n".join(parts)


def _render_tool(tool: dict) -> str:
    name = tool["name"]
    status = tool["status"]
    duration = tool.get("duration_ms", 0)
    icon = "✅" if status == "success" else ("❌" if status == "error" else "🔧")
    dur = f" {duration}ms" if duration else ""
    line = f"{icon} **{name}**{dur}"
    summary = _summarize_input(name, tool.get("input", {}))
    if summary:
        line += f"\n```\n{summary}\n```"
    return line


def _summarize_input(tool_name: str, tool_input: dict) -> str:
    if not tool_input:
        return ""
    if tool_name in ("Read", "Write", "Glob"):
        return tool_input.get("file_path", tool_input.get("pattern", str(tool_input)))
    if tool_name == "Edit":
        path = tool_input.get("file_path", "")
        old = str(tool_input.get("old_string", ""))[:60]
        new = str(tool_input.get("new_string", ""))[:60]
        return f"{path}\n- {old}\n+ {new}" if old and new else path
    if tool_name == "Bash":
        return tool_input.get("command", str(tool_input))
    if tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"{pattern} in {path}" if path else pattern
    s = str(tool_input)
    return s[:200] + "..." if len(s) > 200 else s
