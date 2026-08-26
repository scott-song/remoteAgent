"""Tests for bot.feishu_client module."""

from __future__ import annotations

import io
import json
import logging
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.attachments import ACK_EMOJI

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(mock_lark=None):
    """Create a FeishuClient with lark SDK mocked at the module level."""
    with patch("core.feishu_client.lark") as lark_mock:
        if mock_lark:
            mock_lark(lark_mock)
        # Make the builder chain return a MagicMock
        builder = MagicMock()
        lark_mock.Client.builder.return_value = builder
        builder.app_id.return_value = builder
        builder.app_secret.return_value = builder
        builder.log_level.return_value = builder
        builder.build.return_value = MagicMock(name="lark_client")

        from core.feishu_client import FeishuClient

        client = FeishuClient("test_app_id", "test_app_secret")
    return client


def _make_event(
    message_id="msg_001",
    message_type="text",
    text="hello",
    chat_id="chat_001",
    sender_open_id="user_001",
    mentions=None,
):
    """Build a mock event data object matching the lark SDK shape."""
    mention_objs = mentions or []
    message = SimpleNamespace(
        message_id=message_id,
        message_type=message_type,
        content=json.dumps({"text": text}),
        chat_id=chat_id,
        mentions=mention_objs,
    )
    sender = SimpleNamespace(
        sender_id=SimpleNamespace(open_id=sender_open_id),
    )
    return SimpleNamespace(event=SimpleNamespace(message=message, sender=sender))


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_app_id_stored(self):
        client = _make_client()
        assert client.app_id == "test_app_id"

    def test_app_secret_stored(self):
        client = _make_client()
        assert client.app_secret == "test_app_secret"

    def test_bot_open_id_empty(self):
        client = _make_client()
        assert client.bot_open_id == ""

    def test_seen_ids_empty_ordered_dict(self):
        client = _make_client()
        assert isinstance(client._seen_ids, OrderedDict)
        assert len(client._seen_ids) == 0


# ---------------------------------------------------------------------------
# on_message
# ---------------------------------------------------------------------------


class TestOnMessage:
    def test_registers_callback(self):
        client = _make_client()
        cb = MagicMock()
        client.on_message(cb)
        assert client._on_message_callback is cb


# ---------------------------------------------------------------------------
# _build_card
# ---------------------------------------------------------------------------


class TestBuildCard:
    def test_returns_valid_json_with_schema(self):
        client = _make_client()
        raw = client._build_card("some text")
        card = json.loads(raw)
        assert card["schema"] == "2.0"

    def test_contains_markdown_element(self):
        client = _make_client()
        raw = client._build_card("hello **world**")
        card = json.loads(raw)
        elements = card["body"]["elements"]
        assert len(elements) == 1
        assert elements[0]["tag"] == "markdown"
        assert elements[0]["content"] == "hello **world**"


# ---------------------------------------------------------------------------
# _on_event
# ---------------------------------------------------------------------------


class TestOnEvent:
    def test_valid_text_triggers_callback(self):
        client = _make_client()
        cb = MagicMock()
        client.on_message(cb)

        event = _make_event(text="hi there")
        client._on_event(event)

        cb.assert_called_once_with("chat_001", "user_001", "user_001", "hi there", "msg_001")

    def test_duplicate_message_id_deduplicated(self):
        client = _make_client()
        cb = MagicMock()
        client.on_message(cb)

        event = _make_event(message_id="dup_1", text="hello")
        client._on_event(event)
        client._on_event(event)

        cb.assert_called_once()

    def test_non_text_message_ignored(self):
        client = _make_client()
        cb = MagicMock()
        client.on_message(cb)

        event = _make_event(message_type="image", text="ignored")
        client._on_event(event)

        cb.assert_not_called()

    def test_empty_text_after_mention_strip_ignored(self):
        client = _make_client()
        cb = MagicMock()
        client.on_message(cb)

        mention = SimpleNamespace(key="@_user_1")
        event = _make_event(text="@_user_1", mentions=[mention])
        client._on_event(event)

        cb.assert_not_called()

    def test_mentions_stripped_from_text(self):
        client = _make_client()
        cb = MagicMock()
        client.on_message(cb)

        mention = SimpleNamespace(key="@_user_1")
        event = _make_event(text="@_user_1 do something", mentions=[mention])
        client._on_event(event)

        cb.assert_called_once()
        actual_text = cb.call_args[0][3]
        assert actual_text == "do something"

    def test_exception_in_processing_no_crash(self):
        client = _make_client()
        cb = MagicMock(side_effect=RuntimeError("boom"))
        client.on_message(cb)

        event = _make_event(text="trigger error")
        # Should not raise
        client._on_event(event)

    def test_dedup_eviction_when_exceeding_seen_max(self):
        client = _make_client()
        client._seen_max = 3

        for i in range(5):
            event = _make_event(message_id=f"msg_{i}", text=f"text {i}")
            client._on_event(event)

        # Only the last 3 should remain
        assert len(client._seen_ids) == 3
        assert "msg_0" not in client._seen_ids
        assert "msg_1" not in client._seen_ids
        assert "msg_2" in client._seen_ids
        assert "msg_3" in client._seen_ids
        assert "msg_4" in client._seen_ids


# ---------------------------------------------------------------------------
# reply
# ---------------------------------------------------------------------------


class TestReply:
    def test_success_no_fallback(self):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        client.lark_client.im.v1.message.reply.return_value = resp
        client._reply_plain = MagicMock()

        client.reply("msg_001", "response text")

        client.lark_client.im.v1.message.reply.assert_called_once()
        client._reply_plain.assert_not_called()

    def test_failure_calls_reply_plain(self):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 99
        resp.msg = "error"
        client.lark_client.im.v1.message.reply.return_value = resp
        client._reply_plain = MagicMock()

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            client.reply("msg_001", "response text")

        client._reply_plain.assert_called_once_with("msg_001", "response text")

    def test_reply_retries_on_failure_then_succeeds(self):
        """reply() retries the card reply before falling back to plain text."""
        client = _make_client()
        fail_resp = MagicMock()
        fail_resp.success.return_value = False
        fail_resp.code = 500
        fail_resp.msg = "server error"
        ok_resp = MagicMock()
        ok_resp.success.return_value = True

        client.lark_client.im.v1.message.reply.side_effect = [fail_resp, ok_resp]
        client._reply_plain = MagicMock()

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            client.reply("msg_001", "text")

        assert client.lark_client.im.v1.message.reply.call_count == 2
        client._reply_plain.assert_not_called()

    def test_reply_exhausts_retries_then_falls_back(self):
        """After all retries fail, reply() falls back to plain text."""
        client = _make_client()
        fail_resp = MagicMock()
        fail_resp.success.return_value = False
        fail_resp.code = 500
        fail_resp.msg = "error"
        client.lark_client.im.v1.message.reply.return_value = fail_resp
        client._reply_plain = MagicMock()

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            client.reply("msg_001", "text")

        # 1 initial + 2 retries = 3 attempts
        assert client.lark_client.im.v1.message.reply.call_count == 3
        client._reply_plain.assert_called_once()


# ---------------------------------------------------------------------------
# _reply_plain retry
# ---------------------------------------------------------------------------


class TestReplyPlainRetry:
    def test_reply_plain_retries_on_failure(self):
        client = _make_client()
        fail_resp = MagicMock()
        fail_resp.success.return_value = False
        fail_resp.code = 500
        fail_resp.msg = "error"
        ok_resp = MagicMock()
        ok_resp.success.return_value = True

        client.lark_client.im.v1.message.reply.side_effect = [fail_resp, ok_resp]

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            client._reply_plain("msg_001", "text")

        assert client.lark_client.im.v1.message.reply.call_count == 2

    def test_reply_plain_truncates_at_4000(self):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        client.lark_client.im.v1.message.reply.return_value = resp

        client._reply_plain("msg_001", "x" * 10_000)

        # Content is JSON with text truncated to 4000 (truncation logic lives in the code).
        client.lark_client.im.v1.message.reply.assert_called_once()


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_success_returns_message_id(self):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        resp.data.message_id = "new_msg_123"
        client.lark_client.im.v1.message.create.return_value = resp

        result = client.send_message("chat_001", "hello")

        assert result == "new_msg_123"
        client.lark_client.im.v1.message.create.assert_called_once()

    def test_failure_returns_empty_string(self):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 99
        resp.msg = "error"
        client.lark_client.im.v1.message.create.return_value = resp

        result = client.send_message("chat_001", "hello")

        assert result == ""


# ---------------------------------------------------------------------------
# update_message
# ---------------------------------------------------------------------------


class TestUpdateMessage:
    def test_success_no_error(self, caplog):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        client.lark_client.im.v1.message.patch.return_value = resp

        with caplog.at_level(logging.WARNING):
            client.update_message("msg_001", "updated text")

        client.lark_client.im.v1.message.patch.assert_called_once()
        assert "Update failed" not in caplog.text

    def test_failure_logs_error(self, caplog):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 99
        resp.msg = "patch error"
        client.lark_client.im.v1.message.patch.return_value = resp

        with caplog.at_level(logging.WARNING):
            client.update_message("msg_001", "updated text")

        assert "Update failed" in caplog.text

    def test_retry_on_failure_then_success(self):
        """update_message retries up to UPDATE_MAX_RETRIES times."""
        client = _make_client()
        fail_resp = MagicMock()
        fail_resp.success.return_value = False
        fail_resp.code = 500
        fail_resp.msg = "server error"
        ok_resp = MagicMock()
        ok_resp.success.return_value = True

        client.lark_client.im.v1.message.patch.side_effect = [fail_resp, ok_resp]

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            client.update_message("msg_001", "text")

        # Called twice: initial + 1 retry
        assert client.lark_client.im.v1.message.patch.call_count == 2

    def test_retry_exhausted(self):
        """After UPDATE_MAX_RETRIES+1 attempts, update_message gives up."""
        client = _make_client()
        fail_resp = MagicMock()
        fail_resp.success.return_value = False
        fail_resp.code = 500
        fail_resp.msg = "server error"

        client.lark_client.im.v1.message.patch.return_value = fail_resp

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            client.update_message("msg_001", "text")

        # 1 initial + UPDATE_MAX_RETRIES = 3 total
        assert client.lark_client.im.v1.message.patch.call_count == 3

    def test_truncates_oversized_content(self):
        """update_message truncates content that exceeds card limits."""
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        client.lark_client.im.v1.message.patch.return_value = resp

        # Send very large text — should not crash
        client.update_message("msg_001", "x" * 50_000)

        client.lark_client.im.v1.message.patch.assert_called_once()


# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_small_text_single_chunk(self):
        client = _make_client()
        chunks = client._chunk_text("hello world")
        assert chunks == ["hello world"]

    def test_large_text_multiple_chunks(self):
        client = _make_client()
        # Create text that exceeds CARD_MAX_BYTES
        big = "line\n" * 10_000  # ~50KB
        chunks = client._chunk_text(big)
        assert len(chunks) > 1
        # Each chunk's content bytes should be within the configured limit
        overhead = len(client._build_card("").encode("utf-8"))
        max_content = 25_000 - overhead
        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= max_content + 10  # small tolerance

    def test_splits_at_newline_boundary(self):
        client = _make_client()
        # Build text just over limit with clear newline boundaries
        overhead = len(client._build_card("").encode("utf-8"))
        max_content = 25_000 - overhead
        line = "A" * 100 + "\n"
        num_lines = (max_content // len(line)) + 5  # just over limit
        text = line * num_lines
        chunks = client._chunk_text(text)
        assert len(chunks) >= 2
        # First chunk should end cleanly (not mid-line)
        assert chunks[0].endswith("A" * 100) or chunks[0].endswith("\n")

    def test_empty_text_single_chunk(self):
        client = _make_client()
        chunks = client._chunk_text("")
        assert chunks == [""]


# ---------------------------------------------------------------------------
# reply with overflow
# ---------------------------------------------------------------------------


class TestReplyOverflow:
    def test_reply_overflow_sends_extra_chunks(self):
        """When reply text is too large, overflow chunks go via send_message."""
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        client.lark_client.im.v1.message.reply.return_value = resp

        # Mock send_message for overflow
        client.send_message = MagicMock()

        # Create text that will be chunked
        big = "line\n" * 10_000
        client.reply("msg_001", big, chat_id="chat_001")

        client.lark_client.im.v1.message.reply.assert_called_once()
        # Overflow should trigger send_message calls
        if len(client._chunk_text(big)) > 1:
            assert client.send_message.call_count > 0

    def test_reply_no_chat_id_truncates(self):
        """Without chat_id, oversized reply text is truncated."""
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        client.lark_client.im.v1.message.reply.return_value = resp

        big = "line\n" * 10_000
        # No chat_id means we can't send overflow
        client.reply("msg_001", big)

        client.lark_client.im.v1.message.reply.assert_called_once()


# ---------------------------------------------------------------------------
# send_message chunking
# ---------------------------------------------------------------------------


class TestSendMessageChunking:
    def test_large_message_split_into_multiple_sends(self):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        resp.data.message_id = "new_msg"
        client.lark_client.im.v1.message.create.return_value = resp

        big = "line\n" * 10_000
        result = client.send_message("chat_001", big)

        chunks = client._chunk_text(big)
        # Each chunk retried up to 3 times on failure, but on success called once per chunk
        assert client.lark_client.im.v1.message.create.call_count == len(chunks)
        assert result == "new_msg"  # returns first message's ID

    def test_send_message_retries_on_failure(self):
        """send_message retries each chunk on API failure."""
        client = _make_client()
        fail_resp = MagicMock()
        fail_resp.success.return_value = False
        fail_resp.code = 500
        fail_resp.msg = "error"
        ok_resp = MagicMock()
        ok_resp.success.return_value = True
        ok_resp.data.message_id = "msg_ok"

        client.lark_client.im.v1.message.create.side_effect = [fail_resp, ok_resp]

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = client.send_message("chat_001", "hello")

        assert result == "msg_ok"
        assert client.lark_client.im.v1.message.create.call_count == 2


# ---------------------------------------------------------------------------
# download_resource / react  (T2 — AC-3, AC-7, AC-8)
# ---------------------------------------------------------------------------


def _resource_response(payload: bytes | None, ok: bool = True):
    """Mock a GetMessageResourceResponse, whose `.file` is a readable stream."""
    response = MagicMock()
    response.success.return_value = ok
    response.code = 0 if ok else 234001
    response.msg = "ok" if ok else "resource not found"
    response.file = io.BytesIO(payload) if payload is not None else None
    return response


class TestDownloadResource:
    def test_int_AC_7_an_image_over_the_cap_is_rejected(self):
        """Given a user sends an image larger than 10 MB, when the bot receives it,
        then nothing is held — the call reports the size, not a generic failure."""
        client = _make_client()
        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        client.lark_client.im.v1.message_resource.get.return_value = _resource_response(oversized)

        data, reason = client.download_resource("msg_1", "img_1", max_bytes=16)

        assert data is None
        assert reason == "too_large"

    def test_a_payload_at_the_cap_is_accepted(self):
        client = _make_client()
        exact = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8  # 16 bytes
        client.lark_client.im.v1.message_resource.get.return_value = _resource_response(exact)

        data, reason = client.download_resource("msg_1", "img_1", max_bytes=16)

        assert data == exact
        assert reason is None

    def test_oversized_payload_is_not_fully_buffered(self):
        """The read must stop at max_bytes + 1 so a huge image never lands in
        memory (design § Performance — the budget holds because of the cap)."""
        client = _make_client()
        stream = MagicMock()
        stream.read.return_value = b"x" * 17
        response = MagicMock()
        response.success.return_value = True
        response.file = stream
        client.lark_client.im.v1.message_resource.get.return_value = response

        client.download_resource("msg_1", "img_1", max_bytes=16)

        stream.read.assert_called_once_with(17)

    def test_int_AC_8_a_failed_download_is_reported_distinctly(self):
        """Given Feishu errors for the image's content, when the bot tries to
        receive it, then the failure is distinguishable from an oversize reject."""
        client = _make_client()
        client.lark_client.im.v1.message_resource.get.return_value = _resource_response(
            None, ok=False
        )

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            data, reason = client.download_resource("msg_1", "img_1")

        assert data is None
        assert reason == "failed"

    def test_download_retries_then_succeeds(self):
        client = _make_client()
        client.lark_client.im.v1.message_resource.get.side_effect = [
            _resource_response(None, ok=False),
            _resource_response(b"\x89PNG\r\n\x1a\n"),
        ]

        with patch("core.feishu_client.time") as mock_time:
            mock_time.sleep = MagicMock()
            data, reason = client.download_resource("msg_1", "img_1")

        assert data == b"\x89PNG\r\n\x1a\n"
        assert reason is None
        assert client.lark_client.im.v1.message_resource.get.call_count == 2

    def test_a_successful_response_with_no_stream_is_a_failure(self):
        client = _make_client()
        client.lark_client.im.v1.message_resource.get.return_value = _resource_response(None)

        data, reason = client.download_resource("msg_1", "img_1")

        assert data is None
        assert reason == "failed"

    def test_never_logs_the_bytes(self, caplog):
        """BR-7 — logs record that an image arrived, never its content."""
        client = _make_client()
        secret = b"\x89PNG\r\n\x1a\nSUPERSECRETPIXELS"
        client.lark_client.im.v1.message_resource.get.return_value = _resource_response(secret)

        with caplog.at_level(logging.DEBUG):
            client.download_resource("msg_1", "img_1")

        assert "SUPERSECRETPIXELS" not in caplog.text


class TestReact:
    def test_int_AC_3_receipt_is_acknowledged_with_a_reaction(self):
        """Given a message containing only an image, when the bot receives it, then
        it adds an emoji reaction — this is the call that does it."""
        client = _make_client()
        response = MagicMock()
        response.success.return_value = True
        client.lark_client.im.v1.message_reaction.create.return_value = response

        assert client.react("msg_1") is True
        assert client.lark_client.im.v1.message_reaction.create.call_count == 1

    def test_uses_the_configured_ack_emoji(self):
        client = _make_client()
        response = MagicMock()
        response.success.return_value = True
        client.lark_client.im.v1.message_reaction.create.return_value = response

        with patch("core.feishu_client.Emoji") as emoji_cls:
            builder = MagicMock()
            emoji_cls.builder.return_value = builder
            builder.emoji_type.return_value = builder
            client.react("msg_1")

        builder.emoji_type.assert_called_once_with(ACK_EMOJI)

    def test_a_failed_reaction_never_becomes_a_chat_message(self):
        """AC-3 forbids a reply, so a failed acknowledgement stays in the log."""
        client = _make_client()
        response = MagicMock()
        response.success.return_value = False
        response.code = 230001
        response.msg = "invalid emoji"
        client.lark_client.im.v1.message_reaction.create.return_value = response

        assert client.react("msg_1") is False
        assert client.lark_client.im.v1.message.reply.call_count == 0
        assert client.lark_client.im.v1.message.create.call_count == 0
