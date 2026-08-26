"""
Attachment store
================
Holds images received from chat against a ``(sender, chat)`` pair until the
sender's next prompt drains them.

Storage lives under ``~/.claude-workspace/`` and **never** inside a project
directory: ``git_sync.commit_and_push`` runs ``git add -A``, so an attachment
written into a project tree would be committed and pushed to that project's
remote. Keeping it out of the tree is what makes that safe.
"""

from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .logging_config import get_logger

logger = get_logger(__name__)

# Hold rules — the single source for every caller (BR-2, BR-3, BR-4).
IMAGE_MAX_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = 5
HOLD_TTL_SECONDS = 10 * 60

# Feishu message types this feature accepts; everything else keeps the
# pre-existing silent drop.
ACCEPTED_MSG_TYPES = frozenset({"image", "post"})

# Feishu ``emoji_type`` used to acknowledge receipt without posting a message.
ACK_EMOJI = "EYES"

ATTACHMENTS_ROOT = Path.home() / ".claude-workspace" / "attachments"

# Magic-byte signatures, checked in order. The declared filename from Feishu is
# never trusted — the extension comes from the bytes.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
)

_EXPIRED_WARNING = (
    f"⚠️ Your earlier image expired after {HOLD_TTL_SECONDS // 60} minutes and was not "
    "included. Paste it again if you still need it."
)


def _sniff(data: bytes) -> tuple[str, str] | None:
    """Return ``(media_type, extension)`` for recognised image bytes, else None."""
    for magic, media_type, extension in _SIGNATURES:
        if data.startswith(magic):
            return media_type, extension
    # WebP carries its marker after a 4-byte length: RIFF<size>WEBP
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


@dataclass(frozen=True)
class Attachment:
    """One image on disk, held for or already handed to a prompt."""

    path: Path
    media_type: str
    size: int
    received_at: float


class AttachmentStore:
    """Per-``(sender, chat)`` holds with a TTL, a cap, and single-use semantics.

    Not thread-safe by itself; callers mutate it from the bot's single event
    loop, which is the only writer.
    """

    def __init__(
        self,
        root: Path | None = None,
        time_fn: Callable[[], float] = time.time,
        ttl_seconds: float = HOLD_TTL_SECONDS,
        max_attachments: int = MAX_ATTACHMENTS,
    ) -> None:
        self._root = Path(root) if root is not None else ATTACHMENTS_ROOT
        self._now = time_fn
        self._ttl = ttl_seconds
        self._max = max_attachments
        self._pending: dict[str, list[Attachment]] = {}
        self._dropped: dict[str, int] = {}

    # ── Keys and paths ────────────────────────────────────

    @staticmethod
    def _key(sender_id: str, chat_id: str) -> str:
        """Opaque directory name — the raw ids never appear on the filesystem."""
        return hashlib.sha256(f"{sender_id}:{chat_id}".encode()).hexdigest()[:16]

    def _dir_for(self, sender_id: str, chat_id: str) -> Path:
        return self._root / self._key(sender_id, chat_id)

    # ── Hold lifecycle ────────────────────────────────────

    def put(self, sender_id: str, chat_id: str, data: bytes) -> Attachment | None:
        """Store bytes and hold them. None when unrecognised or unwritable.

        Holds beyond ``max_attachments`` evict the oldest, remembered so the
        next ``take`` can report the drop (AC-6).
        """
        sniffed = _sniff(data)
        if sniffed is None:
            logger.warning(
                f"[Attachments] Rejected unrecognised signature "
                f"({len(data)} bytes) from {sender_id[:8]}..."
            )
            return None
        media_type, extension = sniffed

        directory = self._dir_for(sender_id, chat_id)
        path = directory / f"{uuid.uuid4().hex}{extension}"
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(data)
            path.chmod(0o600)
        except OSError as e:
            logger.error(f"[Attachments] Write failed at {directory}: {e}")
            return None

        attachment = Attachment(
            path=path, media_type=media_type, size=len(data), received_at=self._now()
        )
        key = self._key(sender_id, chat_id)
        held = self._pending.setdefault(key, [])
        held.append(attachment)
        self._evict_over_cap(key, held)
        return attachment

    def _evict_over_cap(self, key: str, held: list[Attachment]) -> None:
        while len(held) > self._max:
            self._unlink(held.pop(0))
            self._dropped[key] = self._dropped.get(key, 0) + 1

    def take(self, sender_id: str, chat_id: str) -> tuple[list[Attachment], list[str]]:
        """Drain this sender's holds, returning them with any user-facing warnings.

        Releases the hold, so a second call returns nothing (BR-6 → AC-11). The
        files themselves survive until ``purge`` — retention is session-lifetime.
        """
        key = self._key(sender_id, chat_id)
        held = self._pending.pop(key, [])
        dropped = self._dropped.pop(key, 0)

        cutoff = self._now() - self._ttl
        live = [a for a in held if a.received_at > cutoff]
        expired = [a for a in held if a.received_at <= cutoff]
        for attachment in expired:
            self._unlink(attachment)

        warnings: list[str] = []
        if expired:
            warnings.append(_EXPIRED_WARNING)
        if dropped:
            noun = "image was" if dropped == 1 else "images were"
            warnings.append(
                f"⚠️ Only the {self._max} most recent images were attached; "
                f"{dropped} older {noun} dropped."
            )
        return live, warnings

    def purge(self, sender_id: str, chat_id: str) -> int:
        """Delete every file held or already handed out for this pair (AC-13)."""
        key = self._key(sender_id, chat_id)
        self._pending.pop(key, None)
        self._dropped.pop(key, None)

        directory = self._dir_for(sender_id, chat_id)
        if not directory.is_dir():
            return 0
        removed = sum(1 for entry in directory.iterdir() if entry.is_file())
        try:
            shutil.rmtree(directory)
        except OSError as e:
            logger.warning(f"[Attachments] Purge failed at {directory}: {e}")
            return 0
        return removed

    @staticmethod
    def _unlink(attachment: Attachment) -> None:
        try:
            attachment.path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"[Attachments] Could not delete {attachment.path}: {e}")


# Default instance — imported by the session manager so cleanup needs no
# constructor injection through SessionManager.
attachment_store = AttachmentStore()
