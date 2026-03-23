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
        client = MagicMock(spec=["update_message", "send_message", "_chunk_text"])
        # By default, _chunk_text returns text as single chunk
        client._chunk_text.side_effect = lambda text: [text]
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

    def test_on_tool_result_truncates_to_2000_with_indicator(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Bash", {"command": "ls"})
        h.on_tool_result("x" * 5000, is_error=False)
        output = h.tools[-1]["output"]
        # First 2000 chars preserved, then truncation indicator appended
        self.assertTrue(output.startswith("x" * 2000))
        self.assertIn("truncated", output)
        self.assertIn("5000 chars total", output)

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

    def test_render_streaming_truncates_long_response(self):
        """Mid-stream text > 3000 chars is trimmed to tail with indicator."""
        h, _ = self._make_handler()
        h.response_text = "A" * 5000
        result = h._render_streaming()
        self.assertIn("response truncated", result)
        # Should contain the tail portion
        self.assertIn("A" * 3000, result)

    def test_render_streaming_collapses_finished_tools(self):
        """After first render, completed tools are summarized as a count."""
        h, _ = self._make_handler()
        h.tools.append({"name": "Read", "status": "success", "duration_ms": 5, "input": {}})
        # First render — shows tool details
        result1 = h._render_streaming()
        self.assertIn("Read", result1)
        # Second render — prior tools collapsed
        h.tools.append({"name": "Bash", "status": "running", "input": {"command": "ls"}})
        result2 = h._render_streaming()
        self.assertIn("1 tool calls completed", result2)
        self.assertIn("Bash", result2)

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


    # -- finalize with chunking --

    def test_finalize_sends_overflow_chunks(self):
        """When finalize text is split into multiple chunks, overflow goes via send_message."""
        h, client = self._make_handler()
        h.response_text = "big response"
        client._chunk_text.side_effect = lambda text: ["chunk1", "chunk2", "chunk3"]
        h.finalize(duration_str="1s", mode="one-shot")
        # First chunk goes to update_message
        client.update_message.assert_called_once_with("msg_1", "chunk1")
        # Overflow chunks go to send_message
        assert client.send_message.call_count == 2
        client.send_message.assert_any_call("chat_1", "chunk2")
        client.send_message.assert_any_call("chat_1", "chunk3")

    def test_finalize_single_chunk_no_send(self):
        """Single chunk should only call update_message, not send_message."""
        h, client = self._make_handler()
        h.response_text = "small"
        h.finalize(duration_str="1s", mode="one-shot")
        client.update_message.assert_called_once()
        client.send_message.assert_not_called()

    # -- on_tool_result truncation details --

    def test_on_tool_result_short_content_not_truncated(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Bash", {"command": "ls"})
        h.on_tool_result("short output", is_error=False)
        self.assertEqual(h.tools[-1]["output"], "short output")
        self.assertNotIn("truncated", h.tools[-1]["output"])

    def test_on_tool_result_exactly_2000_not_truncated(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Bash", {"command": "ls"})
        h.on_tool_result("x" * 2000, is_error=False)
        self.assertEqual(h.tools[-1]["output"], "x" * 2000)

    def test_on_tool_result_2001_truncated(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Bash", {"command": "ls"})
        h.on_tool_result("x" * 2001, is_error=False)
        self.assertIn("truncated", h.tools[-1]["output"])
        self.assertIn("2001 chars total", h.tools[-1]["output"])

    def test_on_tool_result_records_duration_ms(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Bash", {"command": "ls"})
        h.on_tool_result("ok", is_error=False)
        self.assertIn("duration_ms", h.tools[-1])
        self.assertIsInstance(h.tools[-1]["duration_ms"], int)

    def test_on_tool_result_error_status(self):
        h, _ = self._make_handler()
        h._last_update = float("inf")
        h.on_tool_start("Bash", {"command": "bad"})
        h.on_tool_result("error msg", is_error=True)
        self.assertEqual(h.tools[-1]["status"], "error")


# ---------------------------------------------------------------------------
# _render_tool — error output display
# ---------------------------------------------------------------------------

class TestRenderToolErrorOutput(unittest.TestCase):
    def test_error_tool_shows_output(self):
        tool = {"name": "Bash", "status": "error", "duration_ms": 50,
                "input": {"command": "exit 1"}, "output": "command failed"}
        result = _render_tool(tool)
        self.assertIn("command failed", result)

    def test_success_tool_hides_output(self):
        tool = {"name": "Bash", "status": "success", "duration_ms": 50,
                "input": {"command": "ls"}, "output": "file1\nfile2"}
        result = _render_tool(tool)
        self.assertNotIn("file1", result)

    def test_error_output_truncated_at_500(self):
        tool = {"name": "Bash", "status": "error", "duration_ms": 50,
                "input": {}, "output": "E" * 1000}
        result = _render_tool(tool)
        # Error output shown but capped at 500 chars
        self.assertIn("E" * 500, result)
        # The 501st char should not appear in the output quote
        lines_with_output = [l for l in result.split("\n") if l.startswith(">")]
        combined = "".join(lines_with_output)
        self.assertLessEqual(len(combined), 510)  # "> " prefix + 500 chars


# ---------------------------------------------------------------------------
# _summarize_input — edit preview limit
# ---------------------------------------------------------------------------

class TestEditPreviewLimit(unittest.TestCase):
    def test_edit_old_string_truncated_at_200(self):
        result = _summarize_input("Edit", {
            "file_path": "/a.py",
            "old_string": "O" * 500,
            "new_string": "N" * 500,
        })
        # old_string should be truncated to 200 chars
        self.assertIn("O" * 200, result)
        self.assertNotIn("O" * 201, result)

    def test_edit_new_string_truncated_at_200(self):
        result = _summarize_input("Edit", {
            "file_path": "/a.py",
            "old_string": "old",
            "new_string": "N" * 500,
        })
        self.assertIn("N" * 200, result)
        self.assertNotIn("N" * 201, result)


if __name__ == "__main__":
    unittest.main()
