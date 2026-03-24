"""Tests for bot.session_manager — Session dataclass & SessionManager."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.project_registry import ProjectConfig
from bot.session_manager import Session, SessionManager, _CLEANUP_INTERVAL, _MAX_HISTORY_PER_PROJECT
import bot.session_manager as session_manager


# ── Helpers ──────────────────────────────────────────────


def _make_config(name: str = "test-bot") -> ProjectConfig:
    return ProjectConfig(name=name, project_dir=Path("/tmp/project"))


def _make_session(
    user_id: str = "user1",
    bot_name: str = "test-bot",
    connected: bool = True,
    session_id: str | None = "sess-123",
    first_prompt: str | None = None,
) -> Session:
    client = MagicMock()
    client.disconnect = AsyncMock()
    return Session(
        user_id=user_id,
        bot_name=bot_name,
        project_config=_make_config(bot_name),
        client=client,
        connected=connected,
        session_id=session_id,
        first_prompt=first_prompt,
    )


# ── Session dataclass ───────────────────────────────────


class TestSession:
    def test_key_property(self):
        s = _make_session(user_id="alice", bot_name="mybot")
        assert s.key == "alice:mybot"

    def test_is_stale_false_for_fresh(self):
        s = _make_session()
        assert s.is_stale() is False

    def test_is_stale_true_for_old(self, monkeypatch):
        s = _make_session()
        # Make SESSION_TIMEOUT very small so session appears stale
        monkeypatch.setattr(session_manager, "SESSION_TIMEOUT", 10)
        with patch.object(time, "time", return_value=s.last_active + 11):
            assert s.is_stale() is True

    def test_touch_updates_last_active(self):
        s = _make_session()
        old = s.last_active
        # Ensure at least a tiny time delta
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
        assert sm.get("user1", "test-bot") is s

    def test_returns_none_if_not_connected(self, sm):
        s = _make_session(connected=False)
        sm.store(s)
        assert sm.get("user1", "test-bot") is None

    def test_returns_none_if_missing(self, sm):
        assert sm.get("nobody", "nobot") is None

    def test_calls_touch(self, sm):
        s = _make_session()
        sm.store(s)
        old = s.last_active
        time.sleep(0.01)
        sm.get("user1", "test-bot")
        assert s.last_active > old


class TestStore:
    def test_stores_session(self, sm):
        s = _make_session()
        sm.store(s)
        assert sm.get(s.user_id, s.bot_name) is s


class TestClose:
    @pytest.mark.asyncio
    async def test_disconnects_and_removes(self, sm):
        s = _make_session()
        sm.store(s)
        await sm.close("user1", "test-bot")
        s.client.disconnect.assert_awaited_once()
        assert sm.get("user1", "test-bot") is None

    @pytest.mark.asyncio
    async def test_nonexistent_key_no_crash(self, sm):
        await sm.close("ghost", "nope")  # should not raise

    @pytest.mark.asyncio
    async def test_handles_disconnect_error(self, sm):
        s = _make_session()
        s.client.disconnect = AsyncMock(side_effect=RuntimeError("boom"))
        sm.store(s)
        await sm.close("user1", "test-bot")  # should not raise
        assert s.connected is False


class TestCleanupStale:
    @pytest.mark.asyncio
    async def test_removes_old_sessions(self, sm, monkeypatch):
        monkeypatch.setattr(session_manager, "SESSION_TIMEOUT", 10)
        s = _make_session()
        sm.store(s)

        # Advance time so session is stale and cleanup interval is met
        fake_now = s.last_active + 500
        with patch.object(time, "time", return_value=fake_now):
            await sm.cleanup_stale()

        assert sm.get("user1", "test-bot") is None

    @pytest.mark.asyncio
    async def test_skips_if_within_interval(self, sm, monkeypatch):
        monkeypatch.setattr(session_manager, "SESSION_TIMEOUT", 1)
        s = _make_session()
        sm.store(s)

        now = time.time()
        sm._last_cleanup = now - 1  # recently cleaned
        with patch.object(time, "time", return_value=now):
            await sm.cleanup_stale()

        # Session should still be there because cleanup was skipped
        assert "user1:test-bot" in sm._sessions


class TestAllSessions:
    def test_returns_list(self, sm):
        s1 = _make_session(user_id="a", bot_name="b1")
        s2 = _make_session(user_id="a", bot_name="b2")
        sm.store(s1)
        sm.store(s2)
        result = sm.all_sessions()
        assert len(result) == 2
        assert set(s.key for s in result) == {"a:b1", "a:b2"}


# ── History persistence ──────────────────────────────────


class TestSaveToHistory:
    def test_adds_new_entry(self, sm):
        s = _make_session(session_id="s1", first_prompt="hello world")
        sm.save_to_history(s)
        entries = sm._history.get("test-bot", [])
        assert len(entries) == 1
        assert entries[0]["session_id"] == "s1"
        assert entries[0]["summary"] == "hello world"

    def test_updates_existing_entry(self, sm):
        s = _make_session(session_id="s1", first_prompt=None)
        sm.save_to_history(s)
        # Now update with a prompt
        s.first_prompt = "updated prompt"
        sm.save_to_history(s)
        entries = sm._history["test-bot"]
        assert len(entries) == 1
        assert entries[0]["summary"] == "updated prompt"

    def test_noop_when_session_id_none(self, sm):
        s = _make_session(session_id=None)
        sm.save_to_history(s)
        assert sm._history.get("test-bot") is None

    def test_caps_at_max_history(self, sm):
        for i in range(_MAX_HISTORY_PER_PROJECT + 5):
            s = _make_session(session_id=f"s{i}")
            sm.save_to_history(s)
        assert len(sm._history["test-bot"]) == _MAX_HISTORY_PER_PROJECT


class TestGetHistory:
    def test_returns_sorted_desc(self, sm):
        sm._history["bot"] = [
            {"session_id": "a", "last_active": "2025-01-01T00:00:00"},
            {"session_id": "b", "last_active": "2025-06-01T00:00:00"},
            {"session_id": "c", "last_active": "2025-03-01T00:00:00"},
        ]
        result = sm.get_history("bot")
        ids = [e["session_id"] for e in result]
        assert ids == ["b", "c", "a"]

    def test_returns_empty_for_unknown(self, sm):
        assert sm.get_history("unknown-agent") == []


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
