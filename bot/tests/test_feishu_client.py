"""Tests for bot.feishu_client module."""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(mock_lark=None):
    """Create a FeishuClient with lark SDK mocked at the module level."""
    with patch("bot.feishu_client.lark") as lark_mock:
        if mock_lark:
            mock_lark(lark_mock)
        # Make the builder chain return a MagicMock
        builder = MagicMock()
        lark_mock.Client.builder.return_value = builder
        builder.app_id.return_value = builder
        builder.app_secret.return_value = builder
        builder.log_level.return_value = builder
        builder.build.return_value = MagicMock(name="lark_client")

        from bot.feishu_client import FeishuClient

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

        client.reply("msg_001", "response text")

        client._reply_plain.assert_called_once_with("msg_001", "response text")


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
    def test_success_no_error(self, capsys):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = True
        client.lark_client.im.v1.message.patch.return_value = resp

        client.update_message("msg_001", "updated text")

        client.lark_client.im.v1.message.patch.assert_called_once()
        captured = capsys.readouterr()
        assert "Update failed" not in captured.out

    def test_failure_prints_error(self, capsys):
        client = _make_client()
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 99
        resp.msg = "patch error"
        client.lark_client.im.v1.message.patch.return_value = resp

        client.update_message("msg_001", "updated text")

        captured = capsys.readouterr()
        assert "Update failed" in captured.out
