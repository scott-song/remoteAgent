"""Tests for the attachment store — the hold rules behind AC-5, 6, 9, 10, 11, 13."""

import stat

import pytest
from core.attachments import (
    ACCEPTED_MSG_TYPES,
    ATTACHMENTS_ROOT,
    HOLD_TTL_SECONDS,
    IMAGE_MAX_BYTES,
    MAX_ATTACHMENTS,
    AttachmentStore,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32

SENDER = "ou_sender_1"
CHAT = "oc_chat_1"


class _Clock:
    """Injectable clock so TTL behaviour is testable without touching internals."""

    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def store(tmp_path, clock):
    return AttachmentStore(root=tmp_path, time_fn=clock)


class TestConstants:
    def test_constants_match_the_business_rules(self):
        assert IMAGE_MAX_BYTES == 10 * 1024 * 1024  # BR-4
        assert MAX_ATTACHMENTS == 5  # BR-3
        assert HOLD_TTL_SECONDS == 10 * 60  # BR-2
        assert ACCEPTED_MSG_TYPES == frozenset({"image", "post"})


class TestPut:
    def test_accepts_each_supported_signature(self, store):
        for data in (PNG, JPEG, GIF, WEBP):
            assert store.put(SENDER, CHAT, data) is not None

    def test_rejects_an_unrecognised_signature(self, store):
        """A declared image whose bytes are not an image is rejected, not stored
        under a guessed name (design § Security → Tampering)."""
        assert store.put(SENDER, CHAT, b"%PDF-1.7 not an image") is None

    def test_rejects_empty_payload(self, store):
        assert store.put(SENDER, CHAT, b"") is None

    def test_stored_name_is_generated_not_caller_supplied(self, store):
        att = store.put(SENDER, CHAT, PNG)
        assert att is not None
        assert att.path.suffix == ".png"
        assert att.path.stem not in ("", "image")
        assert len(att.path.stem) >= 16  # a uuid4 hex, not a predictable name

    def test_file_is_owner_only(self, store):
        att = store.put(SENDER, CHAT, PNG)
        assert att is not None
        assert stat.S_IMODE(att.path.stat().st_mode) == 0o600

    def test_records_size_and_media_type(self, store):
        att = store.put(SENDER, CHAT, JPEG)
        assert att is not None
        assert att.size == len(JPEG)
        assert att.media_type == "image/jpeg"


class TestTakeSingleUse:
    def test_int_AC_11_held_image_is_attached_once(self, store):
        """Given a held image already attached to a previous prompt, when the user
        sends another text message, then that turn includes no image."""
        store.put(SENDER, CHAT, PNG)

        first, _ = store.take(SENDER, CHAT)
        second, warnings = store.take(SENDER, CHAT)

        assert len(first) == 1
        assert second == []
        assert warnings == []

    def test_take_with_nothing_held_is_quiet(self, store):
        """AC-4's precondition: nothing held means nothing to say."""
        assert store.take(SENDER, CHAT) == ([], [])


class TestTakeExpiry:
    def test_int_AC_5_expired_hold_is_dropped_and_reported(self, store, clock):
        """Given a held image received more than 10 minutes ago, when the user sends
        a text message, then the turn excludes it and the user is told."""
        store.put(SENDER, CHAT, PNG)
        clock.advance(HOLD_TTL_SECONDS + 1)

        attachments, warnings = store.take(SENDER, CHAT)

        assert attachments == []
        assert warnings == [
            "⚠️ Your earlier image expired after 10 minutes and was not included. "
            "Paste it again if you still need it."
        ]

    def test_hold_just_inside_the_window_survives(self, store, clock):
        store.put(SENDER, CHAT, PNG)
        clock.advance(HOLD_TTL_SECONDS - 1)

        attachments, warnings = store.take(SENDER, CHAT)

        assert len(attachments) == 1
        assert warnings == []

    def test_expired_file_is_deleted_from_disk(self, store, clock):
        att = store.put(SENDER, CHAT, PNG)
        assert att is not None
        clock.advance(HOLD_TTL_SECONDS + 1)

        store.take(SENDER, CHAT)

        assert not att.path.exists()


class TestTakeCap:
    def test_int_AC_6_beyond_the_cap_the_newest_win_and_the_drop_is_reported(self, store):
        """Given a user holding 6 images, when they send a text message, then the 5
        most recent are attached and the drop is named."""
        for _ in range(6):
            store.put(SENDER, CHAT, PNG)

        attachments, warnings = store.take(SENDER, CHAT)

        assert len(attachments) == MAX_ATTACHMENTS
        assert warnings == [
            "⚠️ Only the 5 most recent images were attached; 1 older image was dropped."
        ]

    def test_cap_warning_pluralises(self, store):
        for _ in range(8):
            store.put(SENDER, CHAT, PNG)

        _, warnings = store.take(SENDER, CHAT)

        assert warnings == [
            "⚠️ Only the 5 most recent images were attached; 3 older images were dropped."
        ]

    def test_exactly_at_the_cap_warns_nothing(self, store):
        for _ in range(MAX_ATTACHMENTS):
            store.put(SENDER, CHAT, PNG)

        attachments, warnings = store.take(SENDER, CHAT)

        assert len(attachments) == MAX_ATTACHMENTS
        assert warnings == []

    def test_dropped_file_is_deleted_not_orphaned(self, store):
        first = store.put(SENDER, CHAT, PNG)
        assert first is not None
        for _ in range(MAX_ATTACHMENTS):
            store.put(SENDER, CHAT, PNG)

        assert not first.path.exists()

    def test_oldest_is_the_one_dropped(self, store, clock):
        oldest = store.put(SENDER, CHAT, PNG)
        assert oldest is not None
        kept = []
        for _ in range(MAX_ATTACHMENTS):
            clock.advance(1)
            att = store.put(SENDER, CHAT, PNG)
            assert att is not None
            kept.append(att.path)

        attachments, _ = store.take(SENDER, CHAT)

        assert [a.path for a in attachments] == kept


class TestSenderIsolation:
    def test_int_AC_9_one_members_image_never_reaches_another(self, store):
        """Given two users in the same chat where the first has pasted an image,
        when the second sends a text message, then their turn includes no image and
        the first user's image remains held."""
        store.put(SENDER, CHAT, PNG)

        other, warnings = store.take("ou_sender_2", CHAT)

        assert other == []
        assert warnings == []
        still_held, _ = store.take(SENDER, CHAT)
        assert len(still_held) == 1

    def test_same_sender_different_chat_is_a_separate_hold(self, store):
        store.put(SENDER, CHAT, PNG)

        elsewhere, _ = store.take(SENDER, "oc_chat_2")

        assert elsewhere == []

    def test_holds_are_stored_under_distinct_directories(self, store):
        a = store.put(SENDER, CHAT, PNG)
        b = store.put("ou_sender_2", CHAT, PNG)
        assert a is not None and b is not None

        assert a.path.parent != b.path.parent

    def test_directory_name_does_not_leak_the_raw_ids(self, store):
        att = store.put(SENDER, CHAT, PNG)
        assert att is not None

        assert SENDER not in str(att.path)
        assert CHAT not in str(att.path)


class TestRepoIsolation:
    def test_int_AC_10_default_root_is_outside_any_project_tree(self):
        """The storage root must not sit inside a project directory, because
        git_sync runs `git add -A` and would otherwise commit user images."""
        assert ATTACHMENTS_ROOT.is_absolute()
        assert ATTACHMENTS_ROOT.parts[-2:] == (".claude-workspace", "attachments")

    def test_stored_paths_stay_within_the_root(self, store, tmp_path):
        att = store.put(SENDER, CHAT, PNG)
        assert att is not None

        assert att.path.resolve().is_relative_to(tmp_path.resolve())

    def test_directory_is_owner_only(self, store):
        att = store.put(SENDER, CHAT, PNG)
        assert att is not None

        assert stat.S_IMODE(att.path.parent.stat().st_mode) == 0o700


class TestPurge:
    def test_int_AC_13_purge_deletes_every_held_file(self, store):
        """Given a session that used received images, when it ends, then every
        image received for it is deleted from the host."""
        paths = []
        for _ in range(3):
            att = store.put(SENDER, CHAT, PNG)
            assert att is not None
            paths.append(att.path)

        removed = store.purge(SENDER, CHAT)

        assert removed == 3
        assert not any(p.exists() for p in paths)

    def test_purge_clears_the_hold_so_nothing_survives_to_a_later_prompt(self, store):
        store.put(SENDER, CHAT, PNG)

        store.purge(SENDER, CHAT)

        assert store.take(SENDER, CHAT) == ([], [])

    def test_purge_is_idempotent_and_quiet_when_nothing_is_held(self, store):
        assert store.purge(SENDER, CHAT) == 0

    def test_purge_leaves_other_senders_untouched(self, store):
        store.put(SENDER, CHAT, PNG)
        other = store.put("ou_sender_2", CHAT, PNG)
        assert other is not None

        store.purge(SENDER, CHAT)

        assert other.path.exists()

    def test_purge_after_take_removes_the_consumed_file(self, store):
        """Retention is session-lifetime, so take releases the hold but the file
        stays readable until the session is purged (AC-13)."""
        att = store.put(SENDER, CHAT, PNG)
        assert att is not None
        store.take(SENDER, CHAT)

        assert att.path.exists()
        assert store.purge(SENDER, CHAT) == 1
        assert not att.path.exists()
