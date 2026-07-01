"""
Single-instance startup guard.

Feishu's long-connection push is *cluster mode* — an event is delivered to only
one randomly-chosen client among all connections for the same app. Running two
bot processes therefore doesn't duplicate messages; it silently sprays a
conversation across processes whose live sessions live in separate memory, and
races them on the shared ``sessions.json`` (see ADR-0005). This guard makes a
second start fail fast instead.

Uses ``flock`` (advisory, whole-open-file). The lock is held for the life of the
process and released automatically by the OS if the process dies, so a crash
never leaves a stale lock behind.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

DEFAULT_LOCK_PATH = Path.home() / ".claude-workspace" / "coder.lock"


class AlreadyRunningError(RuntimeError):
    """Raised when another process already holds the instance lock."""

    def __init__(self, pid: str, path: Path):
        self.pid = pid
        self.path = path
        super().__init__(
            f"Another coder bot instance is already running (PID {pid}, lock: {path}). "
            "Feishu delivers each event to only one client, so a second instance would "
            "fragment conversations — refusing to start."
        )


def acquire_instance_lock(lock_path: Path = DEFAULT_LOCK_PATH) -> int:
    """Acquire the exclusive single-instance lock.

    Returns the open file descriptor (keep it for the process lifetime; closing
    it releases the lock). Raises :class:`AlreadyRunningError` if another process
    holds it.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            holder = os.pread(fd, 32, 0).decode(errors="replace").strip() or "unknown"
        except OSError:
            holder = "unknown"
        os.close(fd)
        raise AlreadyRunningError(holder, lock_path) from None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    os.fsync(fd)
    return fd


def release_instance_lock(fd: int) -> None:
    """Release the lock and close its file descriptor."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
