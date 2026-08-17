#!/usr/bin/env python
"""
Local integration / end-to-end harness for the coder bot — NO Feishu connection.

This is a *level above* the unit tests in ``tests/``. Those mock every
collaborator and assert on one function at a time. This harness stands up the
**real** bot wired together — ProjectRegistry, SessionManager, StreamHandler,
git, and (by default) the real Claude Agent SDK — and only fakes the Feishu
transport. Synthetic inbound messages are pushed through the real
``_on_message`` router and every outbound reply is printed, so you can watch the
whole pipeline behave as it would in a live chat.

Two modes
---------
* **real Claude (default)** — true end-to-end. Prompts hit the live SDK, which
  actually reads/writes files and runs bash in the project dir. Slow, costs
  tokens, non-deterministic. Proves the SDK integration works.
* **``--mock-claude``** — deterministic. A canned SDK stand-in replaces the real
  client, so all internal wiring is still real but no external service is hit.
  Fast, free, repeatable — safe to run in CI.

Safety: runs against a throwaway scratch project dir (never your repo) and
redirects session history to a temp file, so ``~/.claude-workspace/sessions.json``
is left untouched.

Usage
-----
    .venv/bin/python bots/coder/tools/harness.py               # real Claude
    .venv/bin/python bots/coder/tools/harness.py --mock-claude # deterministic
    .venv/bin/python bots/coder/tools/harness.py --keep        # keep scratch dir
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

CHAT_A, CHAT_B, USER = "chatA", "chatB", "userA"


# ── fake Feishu transport (the only mock that is always on) ─────────────────
def _short(t: str, n: int = 700) -> str:
    t = str(t).replace("\n", "\n      ")
    return t if len(t) <= n else t[:n] + f" …(+{len(t) - n} chars)"


class FakeFeishu:
    """Stand-in for FeishuClient. Captures/prints everything the bot sends.

    Must implement every method the bot *and* StreamHandler call on the client:
    ``reply``, ``send_message``, ``update_message``, and ``_chunk_text`` (which
    ``StreamHandler.finalize`` invokes on the client).
    """

    def __init__(self, app_id=None, app_secret=None):
        self._n = 0
        self.sent: list[str] = []
        self.replied: list[str] = []
        self.updated: list[str] = []

    def _chunk_text(self, text):
        return [text]

    def on_message(self, cb):
        self._cb = cb

    def start(self, loop):
        pass

    def _id(self):
        self._n += 1
        return f"srv{self._n}"

    def reply(self, message_id, text, chat_id=""):
        self.replied.append(text)
        print(f"   ↩️  reply→{message_id}: {_short(text)}")

    def send_message(self, chat_id, text):
        self.sent.append(text)
        mid = self._id()
        print(f"   📤 send→{chat_id} [{mid}]: {_short(text)}")
        return mid

    def update_message(self, message_id, text):
        self.updated.append(text)
        print(f"   ✏️  update {message_id}: {_short(text)}")


# ── canned Claude SDK stand-in (only used with --mock-claude) ───────────────
# NOTE: _stream_response dispatches on type(block).__name__, so these class
# names must match the real SDK block names EXACTLY (no underscore prefix).
class TextBlock:
    def __init__(self, text):
        self.text = text


class ToolUseBlock:
    def __init__(self, name, tool_input=None):
        self.name = name
        self.input = tool_input or {}


class ToolResultBlock:
    def __init__(self, content, is_error=False):
        self.content = content
        self.is_error = is_error


class AssistantMessage:
    def __init__(self, content):
        self.content = content


class UserMessage:
    def __init__(self, content):
        self.content = content


class SystemMessage:
    def __init__(self, data):
        self.data = data


class ResultMessage:
    def __init__(self, session_id=None):
        self.session_id = session_id


_MOCK_SEQ = {"n": 0}


class FakeClaudeClient:
    """Deterministic ClaudeSDKClient stand-in.

    Emits a canned stream that exercises the streaming-parse path: a session id,
    a Write tool call + result (so ``has_code_changes`` is True), and a final
    text block. Each connect() gets a fresh session id so per-chat history and
    isolation are distinguishable.
    """

    def __init__(self, project, resume=None):
        _MOCK_SEQ["n"] += 1
        self.session_id = resume or f"mock-sess-{_MOCK_SEQ['n']:04d}"
        self._last_query = ""

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    def interrupt(self):
        pass

    async def set_permission_mode(self, mode):
        pass

    async def query(self, text):
        self._last_query = text

    async def receive_response(self):
        yield SystemMessage({"session_id": self.session_id})
        yield AssistantMessage([ToolUseBlock("Write", {"file_path": "hello.txt"})])
        yield UserMessage([ToolResultBlock("wrote hello.txt")])
        yield AssistantMessage([TextBlock(f"(mock) handled: {self._last_query[:60]}")])
        yield ResultMessage(session_id=self.session_id)


# ── scratch workspace ───────────────────────────────────────────────────────
def make_workspace() -> tuple[Path, Path, Path, Path]:
    # A clean, short, underscore-free path: real Claude reproduces it reliably.
    # (mkdtemp's random suffix can contain '_', which the model may mis-transcribe
    # as a path separator when it writes files by absolute path.)
    base = Path(tempfile.gettempdir()) / f"coder-harness-{os.getpid()}"
    shutil.rmtree(base, ignore_errors=True)
    projects_dir = base / "projects"
    project_dir = base / "demo-project"
    history_file = base / "sessions.json"
    projects_dir.mkdir(parents=True)
    project_dir.mkdir(parents=True)

    # a real git repo so /commit actually commits (push fails gracefully — no remote)
    (project_dir / "README.md").write_text("# Demo project\nUsed by the coder-bot harness.\n")
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=h@x", "-c", "user.name=h", "commit", "-qm", "seed"],
    ):
        subprocess.run(["git", *args], cwd=project_dir, check=True, capture_output=True)

    # a skill so /skills lists something
    skill = project_dir / ".claude" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo skill\nA sample skill for the harness.\n")

    # seed project YAML (unbound; we bind at runtime to exercise /bind)
    (projects_dir / "demo.yaml").write_text(
        textwrap.dedent(f"""\
        name: demo
        project_dir: {project_dir}
        model: sonnet
        permission_mode: acceptEdits
        restricted: true
        """)
    )
    return base, projects_dir, project_dir, history_file


def banner(t: str):
    print(f"\n{'=' * 70}\n{t}\n{'=' * 70}")


def run(mock_claude: bool, keep: bool) -> int:
    base, projects_dir, project_dir, history_file = make_workspace()

    import core.session_manager as sm

    sm.HISTORY_FILE = history_file  # keep the real home file untouched

    fake_core = SimpleNamespace(
        feishu_app_id="harness", feishu_app_secret="harness", stream_update_interval=2.0
    )
    fake_coder = SimpleNamespace(projects_dir=str(projects_dir))

    patches: list[Any] = [
        patch("coder.main.FeishuClient", FakeFeishu),
        patch("coder.main.core_settings", fake_core),
        patch("coder.main.coder_settings", fake_coder),
    ]
    if mock_claude:
        # NOTE: create_claude_client is called later on the background loop, not
        # at construction — so the patch must stay open for the WHOLE run, not
        # just while the bot is built. Hence the ExitStack around everything.
        patches.append(patch("coder.main.create_claude_client", FakeClaudeClient))

    # Keep every patch active for the entire driver (construction + all turns).
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        from coder.main import ClaudeWorkspaceBot

        bot = ClaudeWorkspaceBot()
        feishu: FakeFeishu = bot.feishu

        # make scheduled coroutines block so output stays ordered & deterministic
        def _blocking_schedule(coro: Any) -> Any:
            return asyncio.run_coroutine_threadsafe(coro, bot.loop).result(timeout=600)

        setattr(bot, "_schedule", _blocking_schedule)

        def say(chat_id: str, user_id: str, text: str):
            print(f"\n\033[1m👤 [{user_id}@{chat_id}] {text}\033[0m")
            bot._on_message(chat_id, user_id, user_id, text, feishu._id())

        mode = "MOCK Claude (deterministic)" if mock_claude else "REAL Claude (true E2E)"
        banner(f"coder-bot harness — Feishu faked, {mode}")

        # ── Phase 1: command surface (no Claude turns) ──────────────────────
        banner("PHASE 1 — command surface (routing, registry, session state)")
        say(CHAT_A, USER, "hello")  # greeting → HELP_TEXT
        say(CHAT_A, USER, "/help")
        say(CHAT_A, USER, "/status")  # no active session
        say(CHAT_A, USER, "/projects")
        say(CHAT_A, USER, "/project demo")  # switch (valid)
        say(CHAT_A, USER, "/project nope")  # switch (invalid)
        say(CHAT_A, USER, "/bind demo")  # bind chat → project
        say(CHAT_A, USER, "/bind")  # show current binding
        say(CHAT_A, USER, "/skills")  # lists the demo skill
        say(CHAT_A, USER, "/mode plan")  # no session yet
        say(CHAT_A, USER, "/resume")  # no history yet
        say(CHAT_A, USER, f"/addproject demo2 {project_dir}")
        say(CHAT_A, USER, "/removeproject demo2")
        say(CHAT_A, USER, "/stop")  # no active session
        say(CHAT_A, USER, "/frobnicate")  # unknown command

        # ── Phase 2: a real (or mocked) Claude session ──────────────────────
        banner("PHASE 2 — Claude session (plain prompt → Write tool)")
        say(
            CHAT_A,
            USER,
            "Create a file named hello.txt containing exactly: Hello from the "
            "harness. Then reply with just the word DONE.",
        )

        banner("PHASE 2b — commands that now have a live session")
        say(CHAT_A, USER, "/status")  # active session now
        say(CHAT_A, USER, "/mode plan")  # set_permission_mode on live client
        say(CHAT_A, USER, "/resume")  # history now has an entry
        say(CHAT_A, USER, "/diff")  # quick action (repr. of /test /undo /continue)
        say(CHAT_A, USER, "/commit")  # git-only, no Claude

        # ── Phase 3: per-chat isolation (ADR-0009) ──────────────────────────
        banner("PHASE 3 — per-chat isolation: same user+project, different chat")
        say(CHAT_B, USER, "Reply with just the word: pong")
        print("\nLive session keys (user:project:chat):")
        for s in bot.sessions.all_sessions():
            print(f"   • {s.key}")

        banner("SUMMARY")
        print(
            f"replies={len(feishu.replied)}  sends={len(feishu.sent)}  "
            f"updates={len(feishu.updated)}"
        )
        if mock_claude:
            print("hello.txt on disk: n/a (mock emits a Write event, no real file I/O)")
        else:
            # Real Claude sometimes writes by absolute path and mis-transcribes the
            # throwaway temp path (e.g. '/' → '-'), landing the file in a sibling
            # dir. Both share the coder-harness-<pid> prefix, so glob for it.
            hits = [
                p
                for d in Path(tempfile.gettempdir()).glob(f"coder-harness-{os.getpid()}*")
                for p in d.rglob("hello.txt")
            ]
            print(f"hello.txt written to disk: {bool(hits)}" + (f"  → {hits[0]}" if hits else ""))
        print(f"scratch workspace → {base}")

        # disconnect live sessions (while patches — incl. mock client — still active)
        for s in list(bot.sessions.all_sessions()):
            try:
                asyncio.run_coroutine_threadsafe(
                    bot.sessions.close(s.user_id, s.bot_name, s.chat_id), bot.loop
                ).result(timeout=30)
            except Exception as e:
                print("close error:", e)

    if keep:
        print(f"(kept scratch workspace at {base})")
    else:
        # Remove the base plus any sibling dirs a mangled write path created.
        for d in Path(tempfile.gettempdir()).glob(f"coder-harness-{os.getpid()}*"):
            shutil.rmtree(d, ignore_errors=True)
    print("done.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Local E2E harness for the coder bot (no Feishu).")
    ap.add_argument(
        "--mock-claude",
        action="store_true",
        help="use a canned SDK stand-in instead of the real Claude (fast, deterministic, CI-safe)",
    )
    ap.add_argument(
        "--keep", action="store_true", help="keep the scratch workspace instead of deleting it"
    )
    args = ap.parse_args()
    sys.exit(run(mock_claude=args.mock_claude, keep=args.keep))


if __name__ == "__main__":
    main()
