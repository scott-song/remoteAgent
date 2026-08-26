"""End-to-end acceptance tests for messaging/image-input — no Feishu, no model.

A level above `test_coder_main.py`: this wires the **real** `FeishuClient`
transport to the **real** `ClaudeWorkspaceBot`, real `ProjectRegistry`, real
`SessionManager` and the real `AttachmentStore`. Only two things are faked —
the lark SDK client (so no network) and the Claude SDK client (so no model) —
which is the same seam `bots/coder/tools/harness.py` uses.

What that buys over the integration tests: a synthetic Feishu *event* goes in
one end and the **prompt the agent would receive** comes out the other, through
every real seam in between. That is the acceptance question for 13 of the 14 ACs.

What it still cannot answer: whether the model *reads* a path-referenced image
(AC-1's real observable — see the harness's image phase, which runs real Claude)
and whether Feishu's live wire format matches these synthetic payloads.
"""

from __future__ import annotations

import json
import struct
import textwrap
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

CHAT = "oc_chat_e2e"
USER = "ou_user_e2e"
OTHER = "ou_user_other"


# ── a real PNG, no third-party encoder ──────────────────────────────────────


def solid_png(width: int = 8, height: int = 8, rgb: tuple[int, int, int] = (220, 20, 60)) -> bytes:
    """Encode a solid-colour RGB PNG with the standard library only."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# ── synthetic Feishu events ─────────────────────────────────────────────────


def _event(message_type: str, content: dict, message_id: str, sender: str = USER):
    message = SimpleNamespace(
        message_id=message_id,
        message_type=message_type,
        content=json.dumps(content),
        chat_id=CHAT,
        mentions=[],
    )
    return SimpleNamespace(
        event=SimpleNamespace(
            message=message,
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id=sender)),
        )
    )


def image_event(message_id="m_img", key="img_v2_abc", sender=USER):
    return _event("image", {"image_key": key}, message_id, sender)


def text_event(text, message_id="m_txt", sender=USER):
    return _event("text", {"text": text}, message_id, sender)


def post_event(text, keys=("img_v2_abc",), message_id="m_post", sender=USER):
    elements = [{"tag": "text", "text": text}]
    elements += [{"tag": "img", "image_key": k} for k in keys]
    return _event("post", {"title": "", "content": [elements]}, message_id, sender)


def file_event(message_id="m_file"):
    return _event("file", {"file_key": "file_v2_xyz", "file_name": "trace.pdf"}, message_id)


# ── the stack under test ────────────────────────────────────────────────────


class FakeClaude:
    """Records the prompt it was given; emits a minimal valid stream."""

    last_query = ""

    def __init__(self, project, resume=None):
        self.session_id = "e2e-session"

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def set_permission_mode(self, mode):
        pass

    async def query(self, text):
        type(self).last_query = text

    async def receive_messages(self):
        yield SimpleNamespace(data={"session_id": self.session_id})
        yield SimpleNamespace(session_id=self.session_id)

    async def receive_response(self):
        yield SimpleNamespace(session_id=self.session_id)


class Stack:
    """The wired-together system, plus the two drivers that keep it ordered."""

    def __init__(self, feishu, bot, store):
        self.feishu = feishu
        self.bot = bot
        self.store = store
        self.replies: list[str] = []
        self.reactions: list[str] = []

    async def deliver(self, event):
        """Push one Feishu event through the real transport, inline."""
        offloaded: list = []

        def capture(coro, _loop):
            offloaded.append(coro)
            return MagicMock()

        scheduled: list = []
        with (
            patch("core.feishu_client.asyncio.run_coroutine_threadsafe", capture),
            patch.object(self.bot, "_schedule", scheduled.append),
        ):
            self.feishu._on_event(event)
            for coro in offloaded:
                await coro
        for coro in scheduled:
            await coro


@pytest.fixture
def stack(tmp_path, monkeypatch):
    from core.attachments import AttachmentStore

    projects_dir = tmp_path / "projects"
    project_dir = tmp_path / "demo"
    projects_dir.mkdir()
    project_dir.mkdir()
    (projects_dir / "demo.yaml").write_text(
        textwrap.dedent(f"""\
        name: demo
        project_dir: {project_dir}
        model: sonnet
        permission_mode: acceptEdits
        chat_ids: ["{CHAT}"]
        """)
    )

    import core.session_manager as sm

    monkeypatch.setattr(sm, "HISTORY_FILE", tmp_path / "sessions.json")

    store = AttachmentStore(root=tmp_path / "attachments")
    # The store is a module-level singleton; both consumers must see the same one.
    monkeypatch.setattr("core.session_manager.attachment_store", store)
    monkeypatch.setattr("coder.main.attachment_store", store)

    fake_core = SimpleNamespace(
        feishu_app_id="e2e", feishu_app_secret="e2e", stream_update_interval=99.0
    )
    fake_coder = SimpleNamespace(projects_dir=str(projects_dir))

    with (
        patch("coder.main.core_settings", fake_core),
        patch("coder.main.coder_settings", fake_coder),
        patch("coder.main.create_claude_client", FakeClaude),
        patch("coder.main.threading"),
        patch("core.feishu_client.lark") as lark,
    ):
        builder = lark.Client.builder.return_value
        builder.app_id.return_value = builder
        builder.app_secret.return_value = builder
        builder.log_level.return_value = builder
        builder.build.return_value = MagicMock()

        from coder.main import ClaudeWorkspaceBot
        from core.feishu_client import FeishuClient

        bot = ClaudeWorkspaceBot()
        feishu = FeishuClient("e2e", "e2e", accept_attachments=True)
        feishu.attachments = store
        feishu._loop = bot.loop
        bot.feishu = feishu
        feishu.on_message(bot._on_message)

        s = Stack(feishu, bot, store)
        # Capture what the user would see, without asserting through lark's builder.
        feishu.reply = MagicMock(side_effect=lambda mid, text, **kw: s.replies.append(text))
        feishu.send_message = MagicMock(side_effect=lambda cid, text: s.sent_id(text))
        feishu.update_message = MagicMock()
        feishu._chunk_text = lambda t: [t]
        feishu.react = MagicMock(side_effect=lambda mid, **kw: s.reactions.append(mid) or True)
        s.sent: list[str] = []
        s.sent_id = lambda text: (s.sent.append(text), "srv1")[1]
        feishu.download_resource = MagicMock(return_value=(solid_png(), None, len(solid_png())))
        FakeClaude.last_query = ""
        yield s
        bot.loop.call_soon_threadsafe(bot.loop.stop)


# ── the acceptance tests ────────────────────────────────────────────────────


class TestPasteThenAsk:
    async def test_e2e_AC_1_a_pasted_image_is_carried_by_the_next_message(self, stack):
        """Given a user in a chat bound to a project who has pasted one image and
        received the receipt acknowledgement, when they send a text message, then
        the agent's turn for that message includes the image."""
        await stack.deliver(image_event())
        await stack.deliver(text_event("why is this misaligned?"))

        assert "why is this misaligned?" in FakeClaude.last_query
        assert "Attached image:" in FakeClaude.last_query
        assert ".png" in FakeClaude.last_query
        referenced = [
            line.split("Attached image:")[1].strip()
            for line in FakeClaude.last_query.splitlines()
            if "Attached image:" in line
        ]
        assert len(referenced) == 1
        assert Path(referenced[0]).is_file(), "the referenced path must exist on disk"

    async def test_e2e_AC_3_a_bare_image_is_acknowledged_by_reaction_only(self, stack):
        """Given a user in a chat bound to a project, when they send a message
        containing only an image, then the bot adds an emoji reaction, posts no
        reply, and no agent turn starts."""
        await stack.deliver(image_event())

        assert stack.reactions == ["m_img"]
        assert stack.replies == []
        assert FakeClaude.last_query == ""

    async def test_e2e_AC_11_a_held_image_is_used_once(self, stack):
        """Given a held image already attached to a previous prompt, when the user
        sends another text message, then that turn includes no image."""
        await stack.deliver(image_event())
        await stack.deliver(text_event("first", message_id="m1"))
        first = FakeClaude.last_query
        await stack.deliver(text_event("second", message_id="m2"))

        assert "Attached image:" in first
        assert "Attached image:" not in FakeClaude.last_query
        assert "second" in FakeClaude.last_query


class TestCaptionedImage:
    async def test_e2e_AC_2_an_image_and_its_caption_are_used_together(self, stack):
        """Given a user in a chat bound to a project, when they send one rich-text
        message containing both an image and text, then the agent's turn includes
        the image and the text, with no hold and no second message required."""
        await stack.deliver(post_event("what is wrong with this button?"))

        assert "what is wrong with this button?" in FakeClaude.last_query
        assert "Attached image:" in FakeClaude.last_query
        assert stack.reactions == []


class TestPlainTextUntouched:
    async def test_e2e_AC_4_plain_text_is_unaffected_when_nothing_is_held(self, stack):
        """Given a user with no held image, when they send a text message, then it
        is processed exactly as it is today, with no attachment count."""
        await stack.deliver(text_event("run the tests"))

        assert FakeClaude.last_query == "run the tests"
        assert stack.replies == ["⏳ Processing..."]

    async def test_e2e_AC_12_a_non_image_attachment_changes_nothing(self, stack):
        """Given a user in a chat bound to a project, when they send a file
        message, then the bot holds nothing, starts no agent turn, and posts no
        reply."""
        await stack.deliver(file_event())

        assert stack.replies == []
        assert stack.reactions == []
        assert FakeClaude.last_query == ""
        assert stack.store.take(USER, CHAT) == ([], [])


class TestFailurePaths:
    async def test_e2e_AC_7_an_oversized_image_is_rejected_on_receipt(self, stack):
        """Given a user in a chat bound to a project, when they send an image
        larger than 10 MB, then nothing is held and no agent turn starts."""
        stack.feishu.download_resource = MagicMock(return_value=(None, "too_large", 11534336))

        await stack.deliver(image_event())

        assert stack.replies == ["⚠️ That image is over the 10 MB limit and was not attached."]
        assert FakeClaude.last_query == ""
        assert stack.store.take(USER, CHAT) == ([], [])

    async def test_e2e_AC_8_a_failed_download_is_reported_not_swallowed(self, stack):
        """Given Feishu returning an error for the image's content, when the bot
        tries to receive the image, then nothing is held and the user is told."""
        stack.feishu.download_resource = MagicMock(return_value=(None, "failed", 0))

        await stack.deliver(image_event())

        assert stack.replies == [
            "⚠️ Could not download that image from Feishu. Try sending it again."
        ]
        assert FakeClaude.last_query == ""


class TestSenderIsolation:
    async def test_e2e_AC_9_one_members_image_never_reaches_another(self, stack):
        """Given two users in the same chat where the first has pasted an image,
        when the second sends a text message, then that turn includes no image and
        the first user's image remains held."""
        await stack.deliver(image_event(sender=USER))
        await stack.deliver(text_event("status?", message_id="m_other", sender=OTHER))

        assert "Attached image:" not in FakeClaude.last_query
        await stack.deliver(text_event("and mine?", message_id="m_mine", sender=USER))
        assert "Attached image:" in FakeClaude.last_query


class TestCapAndExpiry:
    async def test_e2e_AC_6_beyond_the_cap_the_newest_win_and_the_drop_is_visible(self, stack):
        """Given a user holding 6 images, when they send a text message, then the 5
        most recent are attached and the drop is named."""
        for i in range(6):
            await stack.deliver(image_event(message_id=f"m_img_{i}"))
        await stack.deliver(text_event("compare these"))

        assert FakeClaude.last_query.count("Attached image:") == 5
        assert any("older image was dropped" in r for r in stack.replies)

    async def test_e2e_AC_5_an_expired_image_is_not_attached_and_the_user_is_told(
        self, stack, monkeypatch
    ):
        """Given a user whose held image was received more than 10 minutes ago,
        when they send a text message, then the turn excludes it and the user is
        told it expired."""
        await stack.deliver(image_event())

        import core.attachments as attachments_module

        real_now = attachments_module.time.time
        monkeypatch.setattr(
            stack.store, "_now", lambda: real_now() + attachments_module.HOLD_TTL_SECONDS + 1
        )

        await stack.deliver(text_event("what about it?"))

        assert "Attached image:" not in FakeClaude.last_query
        assert any("expired after 10 minutes" in r for r in stack.replies)


class TestCleanup:
    async def test_e2e_AC_13_resetting_the_session_deletes_received_images(self, stack):
        """Given a session that has used received images, when it is reset by the
        user, then every image received for that session is deleted from the
        host."""
        await stack.deliver(image_event())
        await stack.deliver(text_event("look at this"))
        referenced = Path(
            next(
                line.split("Attached image:")[1].strip()
                for line in FakeClaude.last_query.splitlines()
                if "Attached image:" in line
            )
        )
        assert referenced.is_file()

        await stack.deliver(text_event("/new", message_id="m_new"))

        assert not referenced.exists()


class TestAuditTrail:
    async def test_e2e_AC_14_a_receipt_is_recorded_without_its_content(self, stack, caplog):
        """Given operational logging at its default level, when the bot accepts a
        received image, then the log records the disposition, the sender, the chat
        and the size — and never the bytes."""
        import logging

        payload = solid_png()
        stack.feishu.download_resource = MagicMock(return_value=(payload, None, len(payload)))

        with caplog.at_level(logging.INFO):
            await stack.deliver(image_event())

        assert "attachment accepted" in caplog.text
        assert str(len(payload)) in caplog.text
        assert "ack_ms=" in caplog.text
        # The payload is binary; assert no long raw run of it leaked into the log.
        assert payload[:16].hex() not in caplog.text


class TestRepoIsolation:
    async def test_e2e_AC_10_a_received_image_never_enters_the_project_repository(self, stack):
        """Given a project configured with automatic git commit and push and a user
        who has pasted an image, when the agent completes a turn that used it and
        the automatic commit runs, then the commit contains no received image and
        the working tree is unchanged by the image's presence.

        Runs a real `git add -A` — the same staging `git_sync.commit_and_push`
        uses — in the real project dir after a real image turn.
        """
        import subprocess

        project_dir = stack.bot.registry.get("demo").project_dir
        for args in (
            ["init", "-q"],
            ["-c", "user.email=e@x", "-c", "user.name=e", "commit", "-qm", "seed", "--allow-empty"],
        ):
            subprocess.run(["git", *args], cwd=project_dir, check=True, capture_output=True)

        await stack.deliver(image_event())
        await stack.deliver(text_event("what is in this image?"))
        referenced = Path(
            next(
                line.split("Attached image:")[1].strip()
                for line in FakeClaude.last_query.splitlines()
                if "Attached image:" in line
            )
        )
        assert referenced.is_file(), "the turn must really have had an image"

        subprocess.run(["git", "add", "-A"], cwd=project_dir, check=True, capture_output=True)
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        ).stdout

        assert staged.strip() == "", f"nothing should be staged, got: {staged!r}"
        assert referenced.name not in staged
        assert not str(referenced).startswith(str(Path(project_dir).resolve()))


class TestNoDoubleAttach:
    async def test_e2e_AC_2_a_captioned_post_attaches_its_image_exactly_once(self, stack):
        """Regression: the image was both held in the store and passed inline to
        the callback, so `held + inline` attached it twice — double vision-token
        cost, and two of the five cap slots for one image. Found by the round-2
        F-13 test, missed by every earlier layer because they counted the
        callback's argument rather than the prompt."""
        await stack.deliver(post_event("look at this"))

        assert FakeClaude.last_query.count("Attached image:") == 1

    async def test_e2e_AC_6_a_post_and_a_paste_together_stay_within_the_cap(self, stack):
        """Six real images across a paste and a captioned post must attach five,
        not ten."""
        for i in range(6):
            await stack.deliver(image_event(message_id=f"m_pre_{i}"))
        await stack.deliver(post_event("and these", message_id="m_post"))

        assert FakeClaude.last_query.count("Attached image:") == 5
