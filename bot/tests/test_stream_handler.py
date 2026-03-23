"""Tests for bot.stream_handler — _summarize_input, _render_tool, and StreamHandler."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub out lark_oapi so we can import stream_handler without the real SDK.
_lark = types.ModuleType("lark_oapi")
_lark_api = types.ModuleType("lark_oapi.api")
_lark_im = types.ModuleType("lark_oapi.api.im")
_lark_im_v1 = types.ModuleType("lark_oapi.api.im.v1")
for _attr in (
    "CreateMessageRequest", "CreateMessageRequestBody",
    "PatchMessageRequest", "PatchMessageRequestBody",
    "ReplyMessageRequest", "ReplyMessageRequestBody",
):
    setattr(_lark_im_v1, _attr, MagicMock())
sys.modules.setdefault("lark_oapi", _lark)
sys.modules.setdefault("lark_oapi.api", _lark_api)
sys.modules.setdefault("lark_oapi.api.im", _lark_im)
sys.modules.setdefault("lark_oapi.api.im.v1", _lark_im_v1)

from bot.stream_handler import StreamHandler, _render_tool, _summarize_input


# ---------------------------------------------------------------------------
# _summarize_input
# ---------------------------------------------------------------------------

class TestSummarizeInput(unittest.TestCase):
    def test_empty_input_returns_empty(self):
        self.assertEqual(_summarize_input("Read", {}), "")
        self.assertEqual(_summarize_input("Read", None), "")

    def test_read_tool_returns_file_path(self):
        self.assertEqual(
            _summarize_input("Read", {"file_path": "/tmp/foo.py"}),
            "/tmp/foo.py",
        )

    def test_write_tool_returns_file_path(self):
        self.assertEqual(
            _summarize_input("Write", {"file_path": "/tmp/bar.py"}),
            "/tmp/bar.py",
        )

    def test_glob_tool_returns_pattern(self):
        self.assertEqual(
            _summarize_input("Glob", {"pattern": "**/*.ts"}),
            "**/*.ts",
        )

    def test_edit_with_old_new_returns_diff(self):
        result = _summarize_input("Edit", {
            "file_path": "/a/b.py",
            "old_string": "foo",
            "new_string": "bar",
        })
        self.assertIn("/a/b.py", result)
        self.assertIn("- foo", result)
        self.assertIn("+ bar", result)

    def test_edit_without_old_new_returns_path(self):
        result = _summarize_input("Edit", {"file_path": "/a/b.py"})
        self.assertEqual(result, "/a/b.py")

    def test_bash_returns_command(self):
        self.assertEqual(
            _summarize_input("Bash", {"command": "ls -la"}),
            "ls -la",
        )

    def test_grep_with_path(self):
        self.assertEqual(
            _summarize_input("Grep", {"pattern": "TODO", "path": "/src"}),
            "TODO in /src",
        )

    def test_grep_without_path(self):
        self.assertEqual(
            _summarize_input("Grep", {"pattern": "TODO"}),
            "TODO",
        )

    def test_unknown_tool_returns_str_truncated(self):
        inp = {"key": "x" * 300}
        result = _summarize_input("UnknownTool", inp)
        self.assertLessEqual(len(result), 204)  # 200 + len("...")

    def test_unknown_tool_long_input_appends_ellipsis(self):
        inp = {"key": "x" * 300}
        result = _summarize_input("UnknownTool", inp)
        self.assertTrue(result.endswith("..."))

    def test_unknown_tool_short_input_no_ellipsis(self):
        inp = {"k": "v"}
        result = _summarize_input("UnknownTool", inp)
        self.assertFalse(result.endswith("..."))


# ---------------------------------------------------------------------------
# _render_tool
# ---------------------------------------------------------------------------

class TestRenderTool(unittest.TestCase):
    def test_success_shows_check_and_duration(self):
        tool = {"name": "Read", "status": "success", "duration_ms": 42, "input": {}}
        result = _render_tool(tool)
        self.assertIn("\u2705", result)  # check mark
        self.assertIn("42ms", result)

    def test_error_shows_x_icon(self):
        tool = {"name": "Bash", "status": "error", "duration_ms": 10, "input": {}}
        result = _render_tool(tool)
        self.assertIn("\u274c", result)

    def test_running_shows_wrench_no_duration(self):
        tool = {"name": "Grep", "status": "running", "input": {}}
        result = _render_tool(tool)
        self.assertIn("\U0001f527", result)  # wrench
        self.assertNotIn("ms", result)

    def test_tool_with_summary_has_code_block(self):
        tool = {"name": "Read", "status": "success", "duration_ms": 5,
                "input": {"file_path": "/tmp/a.py"}}
        result = _render_tool(tool)
        self.assertIn("```", result)
        self.assertIn("/tmp/a.py", result)

    def test_tool_without_summary_no_code_block(self):
        tool = {"name": "Read", "status": "success", "duration_ms": 5, "input": {}}
        result = _render_tool(tool)
        self.assertNotIn("```", result)


# ---------------------------------------------------------------------------
# StreamHandler
# ---------------------------------------------------------------------------

class TestStreamHandler(unittest.TestCase):
    def _make_handler(self, interval=1.5):
        client = MagicMock(spec=["update_message"])
        handler = StreamHandler(
            client=client,
            chat_id="chat_1",
            msg_id="msg_1",
            agent_name="test-agent",
            interval=interval,
        )
        return handler, client

    # -- on_text --

    def test_on_text_accumulates(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")  # suppress update calls
        h.on_text("hello ")
        h.on_text("world")
        self.assertEqual(h.response_text, "hello world")

    # -- on_tool_start --

    def test_on_tool_start_appends_running(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Read", {"file_path": "/f"})
        self.assertEqual(len(h.tools), 1)
        self.assertEqual(h.tools[0]["status"], "running")
        self.assertEqual(h.tools[0]["name"], "Read")

    # -- on_tool_result --

    def test_on_tool_result_updates_last_tool(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Bash", {"command": "ls"})
        h.on_tool_result("output text", is_error=False)
        self.assertEqual(h.tools[-1]["status"], "success")
        self.assertEqual(h.tools[-1]["output"], "output text")

    def test_on_tool_result_truncates_to_2000(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Bash", {"command": "ls"})
        h.on_tool_result("x" * 5000, is_error=False)
        self.assertEqual(len(h.tools[-1]["output"]), 2000)

    def test_on_tool_result_empty_tools_no_crash(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        # should not raise
        h.on_tool_result("data", is_error=False)

    # -- _maybe_update throttling --

    @patch("bot.stream_handler.time")
    def test_maybe_update_throttled(self, mock_time):
        mock_time.time.return_value = 100.0
        h, client = self._make_handler(interval=1.5)
        h._last_update = 99.5  # only 0.5s ago
        h._maybe_update()
        client.update_message.assert_not_called()

    @patch("bot.stream_handler.time")
    def test_maybe_update_fires_after_interval(self, mock_time):
        mock_time.time.return_value = 102.0
        h, client = self._make_handler(interval=1.5)
        h._last_update = 100.0  # 2s ago, > 1.5 interval
        h._maybe_update()
        client.update_message.assert_called_once()

    # -- finalize --

    def test_finalize_calls_update_message(self):
        h, client = self._make_handler()
        h.response_text = "done"
        h.finalize(duration_str="1.2s", mode="one-shot")
        client.update_message.assert_called_once()
        call_args = client.update_message.call_args
        self.assertEqual(call_args[0][0], "msg_1")
        self.assertIn("done", call_args[0][1])

    # -- _render_streaming --

    def test_render_streaming_includes_working(self):
        h, _ = self._make_handler()
        result = h._render_streaming()
        self.assertIn("Working...", result)

    # -- _render_final --

    def test_render_final_with_tools_has_separator(self):
        h, _ = self._make_handler()
        h.tools.append({"name": "Read", "status": "success", "duration_ms": 5, "input": {}})
        result = h._render_final("1s", "one-shot")
        self.assertIn("---", result)

    def test_render_final_without_tools_no_separator(self):
        h, _ = self._make_handler()
        h.response_text = "hello"
        result = h._render_final("1s", "one-shot")
        self.assertNotIn("---", result)

    def test_render_final_no_response_shows_placeholder(self):
        h, _ = self._make_handler()
        result = h._render_final("1s", "one-shot")
        self.assertIn("(no response)", result)


if __name__ == "__main__":
    unittest.main()
