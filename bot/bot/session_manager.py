"""
Session manager — Claude SDK sessions keyed by (user_id, project_name).
Includes persistent history for session resume across bot restarts.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .agent_registry import AgentConfig
from .config import settings

SESSION_TIMEOUT = settings.session_timeout_hours * 60 * 60
_CLEANUP_INTERVAL = 300
_MAX_HISTORY_PER_AGENT = 10
HISTORY_FILE = Path.home() / ".claude-workspace" / "sessions.json"


@dataclass
class Session:
    user_id: str
    bot_name: str
    agent_config: AgentConfig
    client: object  # ClaudeSDKClient
    connected: bool = False
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    session_id: Optional[str] = None
    permission_mode: str = "acceptEdits"
    first_prompt: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.user_id}:{self.bot_name}"

    def is_stale(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TIMEOUT

    def touch(self):
        self.last_active = time.time()


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._last_cleanup: float = 0.0
        self._history: dict = self._load_history()

    def get(self, user_id: str, bot_name: str) -> Optional[Session]:
        key = f"{user_id}:{bot_name}"
        session = self._sessions.get(key)
        if session and session.connected:
            session.touch()
            return session
        return None

    def store(self, session: Session):
        self._sessions[session.key] = session

    async def close(self, user_id: str, bot_name: str):
        key = f"{user_id}:{bot_name}"
        session = self._sessions.pop(key, None)
        if session and session.connected:
            try:
                await session.client.disconnect()
            except Exception as e:
                print(f"  [Session] Disconnect error: {e}")
            session.connected = False

    async def cleanup_stale(self):
        now = time.time()
        if now - self._last_cleanup < _CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        stale = [s for s in self._sessions.values() if s.is_stale()]
        for s in stale:
            print(f"  [Session] Cleaning stale: {s.key}")
            await self.close(s.user_id, s.bot_name)

    def all_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    # ── Session history (persisted to disk) ──────────────

    def save_to_history(self, session: Session):
        """Save or update a session entry in persistent history."""
        if not session.session_id:
            return

        agent_name = session.bot_name
        entries = self._history.get(agent_name, [])

        # Update existing or add new
        found = False
        for entry in entries:
            if entry["session_id"] == session.session_id:
                entry["last_active"] = datetime.now().isoformat()
                if session.first_prompt and entry.get("summary") == "(new session)":
                    entry["summary"] = session.first_prompt[:50]
                found = True
                break

        if not found:
            entries.insert(0, {
                "session_id": session.session_id,
                "summary": (session.first_prompt or "(new session)")[:50],
                "last_active": datetime.now().isoformat(),
                "project_dir": str(session.agent_config.project_dir),
            })

        # Cap history
        self._history[agent_name] = entries[:_MAX_HISTORY_PER_AGENT]
        self._save_history()

    def get_history(self, agent_name: str) -> list[dict]:
        """Get recent session history for an agent, sorted by last_active desc."""
        entries = self._history.get(agent_name, [])
        return sorted(entries, key=lambda e: e.get("last_active", ""), reverse=True)

    def _load_history(self) -> dict:
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_history(self):
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "w") as f:
            json.dump(self._history, f, indent=2, ensure_ascii=False)
