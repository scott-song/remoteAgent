"""
Session Manager
===============
Manages Claude SDK sessions keyed by (user_id, bot_id).
Each user gets a separate Claude conversation per bot.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from .agent_registry import AgentConfig
from .config import settings


SESSION_TIMEOUT = settings.session_timeout_hours * 60 * 60


@dataclass
class Session:
    """A single user's Claude session with a specific bot."""

    user_id: str
    bot_name: str
    agent_config: AgentConfig
    client: object  # ClaudeSDKClient — typed as object to avoid import at module level
    connected: bool = False
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    session_id: Optional[str] = None
    permission_mode: str = "acceptEdits"

    @property
    def key(self) -> str:
        return f"{self.user_id}:{self.bot_name}"

    def is_stale(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TIMEOUT

    def touch(self):
        self.last_active = time.time()


class SessionManager:
    """Manages sessions keyed by (user_id, bot_name)."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def _key(self, user_id: str, bot_name: str) -> str:
        return f"{user_id}:{bot_name}"

    def get(self, user_id: str, bot_name: str) -> Optional[Session]:
        """Get an existing session if it exists and is connected."""
        key = self._key(user_id, bot_name)
        session = self._sessions.get(key)
        if session and session.connected:
            session.touch()
            return session
        return None

    def store(self, session: Session):
        """Store a session."""
        self._sessions[session.key] = session

    async def close(self, user_id: str, bot_name: str):
        """Close and remove a session."""
        key = self._key(user_id, bot_name)
        session = self._sessions.pop(key, None)
        if session and session.connected:
            try:
                await session.client.disconnect()
            except Exception as e:
                print(f"  [Session] Disconnect error: {e}")
            session.connected = False
            print(f"  [Session] Closed {key}")

    async def cleanup_stale(self):
        """Remove sessions that have been inactive beyond the timeout."""
        stale = [k for k, s in self._sessions.items() if s.is_stale()]
        for key in stale:
            parts = key.split(":", 1)
            if len(parts) == 2:
                print(f"  [Session] Cleaning stale: {key}")
                await self.close(parts[0], parts[1])

    def list_sessions(self, user_id: str) -> list[Session]:
        """List all active sessions for a user."""
        return [
            s for s in self._sessions.values()
            if s.user_id == user_id and s.connected
        ]
