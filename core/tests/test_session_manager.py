"""Tests for core.session_manager — Session dataclass & SessionManager."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import core.session_manager as session_manager
import pytest
from core.session_manager import (
    _MAX_HISTORY_PER_PROJECT,
    Session,
    SessionManager,
)

# ── Helpers ──────────────────────────────────────────────


def _make_session(
    user_id: str = "user1",
    bot_name: str = "test-bot",
    chat_id: str = "chatA",
    connected: bool = True,
    session_id: str | None = "sess-123",
    first_prompt: str | None = None,
) -> Session:
    client = MagicMock()
    client.disconnect = AsyncMock()
    return Session(
        user_id=user_id,
        bot_name=bot_name,
        chat_id=chat_id,
        project_dir=Path("/tmp/project"),
        client=client,
        connected=connected,
        session_id=session_id,
        first_prompt=first_prompt,
    )


# ── Session dataclass ───────────────────────────────────


class TestSession:
    def test_key_property(self):
        s = _make_session(user_id="alice", bot_name="mybot", chat_id="oc_1")
        assert s.key == "alice:mybot:oc_1"

    def test_is_stale_false_for_fresh(self):
        s = _make_session()
        assert s.is_stale() is False

    def test_is_stale_true_for_old(self, monkeypatch):
        s = _make_session()
        monkeypatch.setattr(session_manager, "SESSION_TIMEOUT", 10)
        with patch.object(time, "time", return_value=s.last_active + 11):
            assert s.is_stale() is True

    def test_touch_updates_last_active(self):
        s = _make_session()
        old = s.last_active
        time.sleep(0.01)
        s.touch()
        assert s.last_active >= old


# ── SessionManager ───────────────────────────────────────


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    """SessionManager that writes history to tmp_path."""
    hist_file = tmp_path / "sessions.json"
    monkeypatch.setattr(session_manager, "HISTORY_FILE", hist_file)
    return SessionManager()


class TestGet:
    def test_returns_connected_session(self, sm):
        s = _make_session()
        sm.store(s)
        assert sm.get("user1", "test-bot", "chatA") is s

    def test_returns_none_if_not_connected(self, sm):
        s = _make_session(connected=False)
        sm.store(s)
        assert sm.get("user1", "test-bot", "chatA") is None

    def test_returns_none_if_missing(self, sm):
        assert sm.get("nobody", "nobot", "chatA") is None

    def test_calls_touch(self, sm):
        s = _make_session()
        sm.store(s)
        old = s.last_active
        time.sleep(0.01)
        sm.get("user1", "test-bot", "chatA")
        assert s.last_active > old


class TestStore:
    def test_stores_session(self, sm):
        s = _make_session()
        sm.store(s)
        assert sm.get(s.user_id, s.bot_name, s.chat_id) is s


class TestClose:
    @pytest.mark.asyncio
    async def test_disconnects_and_removes(self, sm):
        s = _make_session()
        sm.store(s)
        await sm.close("user1", "test-bot", "chatA")
        s.client.disconnect.assert_awaited_once()
        assert sm.get("user1", "test-bot", "chatA") is None

    @pytest.mark.asyncio
    async def test_nonexistent_key_no_crash(self, sm):
        await sm.close("ghost", "nope", "chatA")  # should not raise

    @pytest.mark.asyncio
    async def test_handles_disconnect_error(self, sm):
        s = _make_session()
        s.client.disconnect = AsyncMock(side_effect=RuntimeError("boom"))
        sm.store(s)
        await sm.close("user1", "test-bot", "chatA")  # should not raise
        assert s.connected is False


class TestPerChatIsolation:
    """AC-1/AC-2/AC-3: sessions are keyed by (user, project, chat)."""

    def test_distinct_chats_distinct_sessions(self, sm):
        a = _make_session(user_id="u", bot_name="proj", chat_id="chatA")
        b = _make_session(user_id="u", bot_name="proj", chat_id="chatB")
        sm.store(a)
        sm.store(b)
        assert sm.get("u", "proj", "chatA") is a
        assert sm.get("u", "proj", "chatB") is b
        assert a.key != b.key  # AC-3

    def test_same_chat_reuses_session(self, sm):
        a = _make_session(user_id="u", bot_name="proj", chat_id="chatA")
        sm.store(a)
        assert sm.get("u", "proj", "chatA") is a  # AC-2

    @pytest.mark.asyncio
    async def test_cleanup_is_per_chat(self, sm, monkeypatch):
        """AC-5: a stale chat session is closed; an active one in another chat survives."""
        monkeypatch.setattr(session_manager, "SESSION_TIMEOUT", 10)
        stale = _make_session(user_id="u", bot_name="proj", chat_id="chatA")
        fresh = _make_session(user_id="u", bot_name="proj", chat_id="chatB")
        sm.store(stale)
        sm.store(fresh)
        base = stale.last_active
        stale.last_active = base - 1000
        fresh.last_active = base
        with patch.object(time, "time", return_value=base + 5):
            await sm.cleanup_stale()
        assert sm.get("u", "proj", "chatA") is None
        assert sm.get("u", "proj", "chatB") is fresh


class TestCleanupStale:
    @pytest.mark.asyncio
    async def test_removes_old_sessions(self, sm, monkeypatch):
        monkeypatch.setattr(session_manager, "SESSION_TIMEOUT", 10)
        s = _make_session()
        sm.store(s)

        fake_now = s.last_active + 500
        with patch.object(time, "time", return_value=fake_now):
            await sm.cleanup_stale()

        assert sm.get("user1", "test-bot", "chatA") is None

    @pytest.mark.asyncio
    async def test_skips_if_within_interval(self, sm, monkeypatch):
        monkeypatch.setattr(session_manager, "SESSION_TIMEOUT", 1)
        s = _make_session()
        sm.store(s)

        now = time.time()
        sm._last_cleanup = now - 1  # recently cleaned
        with patch.object(time, "time", return_value=now):
            await sm.cleanup_stale()

        assert "user1:test-bot:chatA" in sm._sessions


class TestAllSessions:
    def test_returns_list(self, sm):
        s1 = _make_session(user_id="a", bot_name="b1")
        s2 = _make_session(user_id="a", bot_name="b2")
        sm.store(s1)
        sm.store(s2)
        result = sm.all_sessions()
        assert len(result) == 2
        assert set(s.key for s in result) == {"a:b1:chatA", "a:b2:chatA"}


# ── History persistence ──────────────────────────────────


class TestSaveToHistory:
    def test_adds_new_entry(self, sm):
        s = _make_session(session_id="s1", first_prompt="hello world")
        sm.save_to_history(s)
        key = sm._history_key("user1", "test-bot", "chatA")
        entries = sm._history.get(key, [])
        assert len(entries) == 1
        assert entries[0]["session_id"] == "s1"
        assert entries[0]["summary"] == "hello world"

    def test_updates_existing_entry(self, sm):
        s = _make_session(session_id="s1", first_prompt=None)
        sm.save_to_history(s)
        s.first_prompt = "updated prompt"
        sm.save_to_history(s)
        key = sm._history_key("user1", "test-bot", "chatA")
        entries = sm._history[key]
        assert len(entries) == 1
        assert entries[0]["summary"] == "updated prompt"

    def test_noop_when_session_id_none(self, sm):
        s = _make_session(session_id=None)
        sm.save_to_history(s)
        key = sm._history_key("user1", "test-bot", "chatA")
        assert sm._history.get(key) is None

    def test_caps_at_max_history(self, sm):
        for i in range(_MAX_HISTORY_PER_PROJECT + 5):
            s = _make_session(session_id=f"s{i}")
            sm.save_to_history(s)
        key = sm._history_key("user1", "test-bot", "chatA")
        assert len(sm._history[key]) == _MAX_HISTORY_PER_PROJECT


class TestGetHistory:
    def test_returns_sorted_desc(self, sm):
        key = sm._history_key("alice", "bot", "chatA")
        sm._history[key] = [
            {"session_id": "a", "last_active": "2025-01-01T00:00:00"},
            {"session_id": "b", "last_active": "2025-06-01T00:00:00"},
            {"session_id": "c", "last_active": "2025-03-01T00:00:00"},
        ]
        result = sm.get_history("alice", "bot", "chatA")
        ids = [e["session_id"] for e in result]
        assert ids == ["b", "c", "a"]

    def test_returns_empty_for_unknown(self, sm):
        assert sm.get_history("nobody", "unknown-project", "chatA") == []

    def test_history_is_per_chat(self, sm):
        """AC-6 / OQ-1: history for one chat is not returned for another."""
        key = sm._history_key("u", "proj", "chatA")
        sm._history[key] = [{"session_id": "only-A", "last_active": "2025-01-01T00:00:00"}]
        assert len(sm.get_history("u", "proj", "chatA")) == 1
        assert sm.get_history("u", "proj", "chatB") == []


class TestGetLastSessionId:
    def test_returns_latest(self, sm):
        key = sm._history_key("user1", "bot", "chatA")
        sm._history[key] = [
            {"session_id": "a", "last_active": "2025-06-01T00:00:00"},
            {"session_id": "b", "last_active": "2025-01-01T00:00:00"},
        ]
        assert sm.get_last_session_id("user1", "bot", "chatA") == "a"

    def test_returns_none_if_empty(self, sm):
        assert sm.get_last_session_id("user1", "nobot", "chatA") is None


class TestLoadHistory:
    def test_loads_from_file(self, tmp_path, monkeypatch):
        hist_file = tmp_path / "sessions.json"
        data = {"mybot": [{"session_id": "x", "last_active": "2025-01-01"}]}
        hist_file.write_text(json.dumps(data))
        monkeypatch.setattr(session_manager, "HISTORY_FILE", hist_file)
        mgr = SessionManager()
        assert mgr._history == data

    def test_returns_empty_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_manager, "HISTORY_FILE", tmp_path / "nope.json")
        mgr = SessionManager()
        assert mgr._history == {}

    def test_returns_empty_if_invalid_json(self, tmp_path, monkeypatch):
        hist_file = tmp_path / "sessions.json"
        hist_file.write_text("{bad json!!")
        monkeypatch.setattr(session_manager, "HISTORY_FILE", hist_file)
        mgr = SessionManager()
        assert mgr._history == {}
