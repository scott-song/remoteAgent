"""
Feishu bot service — routes messages to Claude sessions, streams responses.
"""

from __future__ import annotations

import asyncio
import re
import traceback
import threading
import time

from core.config import core_settings
from core.feishu_client import FeishuClient
from core.session_manager import Session, SessionManager
from core.stream_handler import StreamHandler

from .config import coder_settings
from .project_registry import ProjectRegistry
from .git_sync import sync_repo
from .sdk_client import create_claude_client

MODE_ALIASES = {"plan": "plan", "ask": "default", "auto": "acceptEdits"}
MODE_DISPLAY = {v: k for k, v in MODE_ALIASES.items()}
NO_PROJECT_MSG = "No project selected.\nUse `/bind <name>` or `/project <name>` first."
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
_GREETINGS = {"hello", "hi", "hey", "help", "start", "你好"}

HELP_TEXT = (
    "**Commands:**\n\n"
    "`/project <name>` — switch project\n"
    "`/projects` — list all projects\n"
    "`/mode [plan|auto|ask]` — switch mode\n"
    "`/skills` — list skills\n"
    "`/skill <name>` — invoke a skill\n"
    "`/resume [id|number]` — resume a session\n"
    "`/new` — fresh conversation\n"
    "`/stop` — interrupt request\n"
    "`/status` — check status\n"
    "`/addproject <name> <path>` — add project\n"
    "`/removeproject <name>` — remove project\n"
    "`/bind <name>` — bind chat to project\n"
    "`/unbind` — unbind chat\n"
    "`/help` — this message\n\n"
    "Or just send a message to chat with Claude."
)


class ClaudeWorkspaceBot:
    def __init__(self):
        self.registry = ProjectRegistry(projects_dir=coder_settings.projects_dir)
        self.sessions = SessionManager()
        self.feishu = FeishuClient(app_id=core_settings.feishu_app_id, app_secret=core_settings.feishu_app_secret)
        self.feishu.on_message(self._on_message)
        self._user_projects: dict[str, str] = {}
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def _schedule(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def start(self):
        projects = self.registry.list_projects()
        if not projects:
            print("\nNo projects configured. Add YAML files to projects/")
            return
        print(f"\nClaude Workspace Bot")
        print(f"  Feishu app: {core_settings.feishu_app_id[:8]}...")
        print(f"  Projects: {', '.join(p.name for p in projects)}")
        print(f"  Default: {projects[0].name} → {projects[0].project_dir}\n")
        self.feishu.start(self.loop)
        print("Listening for messages. Press Ctrl+C to stop.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            for s in self.sessions.all_sessions():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.sessions.close(s.user_id, s.bot_name), self.loop
                    ).result(timeout=5)
                except Exception:
                    pass

    # ── Message routing ──────────────────────────────────

    def _on_message(self, chat_id: str, sender_id: str, _sender_name: str, text: str, message_id: str):
        print(f"\n[Message] {sender_id[:8]}...: {text}")

        if text.startswith("/"):
            self._handle_command(text, chat_id, sender_id, message_id)
        elif text.lower().strip() in _GREETINGS:
            self.feishu.reply(message_id, HELP_TEXT)
        else:
            self.feishu.reply(message_id, "⏳ Processing...")
            self._schedule(self._handle_prompt(text, chat_id, sender_id, message_id))

    def _handle_command(self, text: str, chat_id: str, sender_id: str, message_id: str):
        parts = text.split(None, 2)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) >= 2 else None

        commands = {
            "/help": lambda: self.feishu.reply(message_id, HELP_TEXT),
            "/projects": lambda: self._cmd_projects(sender_id, chat_id, message_id),
            "/project": lambda: self._cmd_project(arg, sender_id, chat_id, message_id),
            "/mode": lambda: self._cmd_mode(arg, sender_id, chat_id, message_id),
            "/new": lambda: self._schedule(self._cmd_new(sender_id, chat_id, message_id)),
            "/stop": lambda: self._schedule(self._cmd_stop(sender_id, chat_id, message_id)),
            "/status": lambda: self._cmd_status(sender_id, chat_id, message_id),
            "/skills": lambda: self._cmd_skills(sender_id, chat_id, message_id),
            "/skill": lambda: self._cmd_skill(arg, sender_id, chat_id, message_id),
            "/resume": lambda: self._cmd_resume(arg, sender_id, chat_id, message_id),
            "/addproject": lambda: self._cmd_add_project(text, chat_id, message_id),
            "/removeproject": lambda: self._cmd_remove_project(arg, message_id),
            "/bind": lambda: self._cmd_bind(arg, chat_id, message_id),
            "/unbind": lambda: self._cmd_unbind(chat_id, message_id),
        }

        handler = commands.get(cmd)
        if handler:
            handler()
        else:
            self.feishu.reply(message_id, f"Unknown command: `{cmd}`\nType /help for available commands.")

    # ── Project resolution ────────────────────────────────

    def _resolve_project(self, sender_id: str, chat_id: str) -> str:
        project = self.registry.get_by_chat_id(chat_id)
        if project:
            return project.name
        name = self._user_projects.get(sender_id)
        if name and self.registry.get(name):
            return name
        projects = self.registry.list_projects()
        return projects[0].name if projects else ""

    # ── Chat commands ────────────────────────────────────

    def _cmd_projects(self, sender_id: str, chat_id: str, message_id: str):
        projects = self.registry.list_projects()
        if not projects:
            self.feishu.reply(message_id, "No projects.\nUse `/addproject <name> <path>` to add one.")
            return
        current = self._resolve_project(sender_id, chat_id)
        lines = ["**Projects:**\n"]
        for p in projects:
            marker = " ◀" if p.name == current else ""
            lines.append(f"`{p.name}` — `{p.project_dir}` ({p.model}){marker}")
        self.feishu.reply(message_id, "\n".join(lines))

    def _cmd_project(self, name: str | None, sender_id: str, chat_id: str, message_id: str):
        if name is None:
            self._cmd_projects(sender_id, chat_id, message_id)
            return
        project = self.registry.get(name)
        if not project:
            names = ", ".join(p.name for p in self.registry.list_projects())
            self.feishu.reply(message_id, f"Unknown project: `{name}`\nAvailable: {names}")
            return
        self._user_projects[sender_id] = name
        self.feishu.reply(message_id, f"Switched to **{name}** (`{project.project_dir}`)")

    def _cmd_mode(self, mode: str | None, sender_id: str, chat_id: str, message_id: str):
        if mode is None or mode not in MODE_ALIASES:
            self.feishu.reply(message_id, "Usage: `/mode [plan|auto|ask]`")
            return
        project_name = self._resolve_project(sender_id, chat_id)
        session = self.sessions.get(sender_id, project_name)
        if not session:
            self.feishu.reply(message_id, "No active session. Send a message first.")
            return
        self._schedule(self._switch_mode(session, MODE_ALIASES[mode], mode, chat_id))

    async def _switch_mode(self, session: Session, sdk_mode: str, display: str, chat_id: str):
        try:
            await session.client.set_permission_mode(sdk_mode)
            session.permission_mode = sdk_mode
            self.feishu.send_message(chat_id, f"Mode switched to **{display}**")
        except Exception as e:
            self.feishu.send_message(chat_id, f"Failed to switch mode: {e}")

    async def _cmd_new(self, sender_id: str, chat_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        await self.sessions.close(sender_id, project_name)
        self.feishu.reply(message_id, "Session reset.")

    async def _cmd_stop(self, sender_id: str, chat_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        session = self.sessions.get(sender_id, project_name)
        if not session:
            self.feishu.reply(message_id, "No active session.")
            return
        if not session.lock.locked():
            self.feishu.reply(message_id, "Nothing running.")
            return
        try:
            session.client.interrupt()
            self.feishu.reply(message_id, "Interrupted.")
        except Exception as e:
            self.feishu.reply(message_id, f"Interrupt failed: {e}")

    def _cmd_status(self, sender_id: str, chat_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        session = self.sessions.get(sender_id, project_name)
        if not session:
            self.feishu.reply(message_id, "No active session.")
            return
        mode = MODE_DISPLAY.get(session.permission_mode, session.permission_mode)
        status = "⏳ Working..." if session.lock.locked() else "Idle."
        self.feishu.reply(message_id, f"{status} ({mode} mode)")

    def _cmd_skills(self, sender_id: str, chat_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        if not project_name:
            self.feishu.reply(message_id, NO_PROJECT_MSG)
            return
        project = self.registry.get(project_name)
        skills_dir = project.project_dir / ".claude" / "skills"
        skills = []
        if skills_dir.exists():
            for f in sorted(skills_dir.glob("*/SKILL.md")):
                skills.append((f.parent.name, _read_first_line(f)))
            for f in sorted(skills_dir.glob("*.md")):
                if f.name != "SKILL.md":
                    skills.append((f.stem, _read_first_line(f)))
        if not skills:
            self.feishu.reply(message_id, f"**{project_name}** has no skills.\nAdd: `{skills_dir}/<name>/SKILL.md`")
            return
        lines = [f"**Skills for {project_name}:**\n"]
        for name, desc in skills:
            lines.append(f"`{name}` — {desc}" if desc else f"`{name}`")
        lines.append("\nInvoke: `/skill <name>`")
        self.feishu.reply(message_id, "\n".join(lines))

    def _cmd_skill(self, name: str | None, sender_id: str, chat_id: str, message_id: str):
        if not name:
            self._cmd_skills(sender_id, chat_id, message_id)
            return
        if not self._resolve_project(sender_id, chat_id):
            self.feishu.reply(message_id, NO_PROJECT_MSG)
            return
        self.feishu.reply(message_id, "⏳ Processing...")
        self._schedule(self._handle_prompt(f"Invoke the skill: {name}", chat_id, sender_id, message_id))

    # ── Resume ───────────────────────────────────────────

    def _cmd_resume(self, arg: str | None, sender_id: str, chat_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        if not project_name:
            self.feishu.reply(message_id, NO_PROJECT_MSG)
            return

        if arg is None:
            history = self.sessions.get_history(project_name)
            if not history:
                self.feishu.reply(message_id, f"No recent sessions for `{project_name}`.\nPaste a session ID: `/resume <uuid>`")
                return
            lines = [f"**Recent sessions for {project_name}:**\n"]
            for i, entry in enumerate(history, 1):
                ts = entry.get("last_active", "?")[:16].replace("T", " ")
                summary = entry.get("summary", "?")
                lines.append(f"`{i}.` [{ts}] {summary}")
            lines.append(f"\nResume: `/resume <number>` or `/resume <uuid>`")
            self.feishu.reply(message_id, "\n".join(lines))
            return

        session_id = None
        if arg.isdigit():
            idx = int(arg) - 1
            history = self.sessions.get_history(project_name)
            if 0 <= idx < len(history):
                session_id = history[idx]["session_id"]
            else:
                self.feishu.reply(message_id, f"Invalid number. Use 1-{len(history)}.")
                return
        elif _UUID_RE.match(arg):
            session_id = arg
        else:
            self.feishu.reply(message_id, "Usage: `/resume <number>` or `/resume <session-uuid>`")
            return

        self.feishu.reply(message_id, f"⏳ Resuming session `{session_id[:8]}...`")
        self._schedule(self._do_resume(sender_id, project_name, session_id, chat_id))

    async def _do_resume(self, sender_id: str, project_name: str, session_id: str, chat_id: str):
        project = self.registry.get(project_name)
        if not project:
            self.feishu.send_message(chat_id, f"Project `{project_name}` not found.")
            return

        await self.sessions.close(sender_id, project_name)

        if project.github_url:
            try:
                status = sync_repo(project.project_dir, project.github_url)
                print(f"  [Git] {project_name}: {status}")
            except Exception as e:
                print(f"  [Git] {project_name}: sync failed: {e}")

        try:
            client = create_claude_client(project, resume=session_id)
            session = Session(
                user_id=sender_id, bot_name=project_name, project_dir=project.project_dir,
                client=client, permission_mode=project.permission_mode,
                session_id=session_id,
            )
            await client.connect()
            session.connected = True
            self.sessions.store(session)
            self.feishu.send_message(chat_id, f"**Session resumed** (`{session_id[:8]}...`)\nProject: `{project_name}`\n\nYou can continue the conversation.")
        except Exception as e:
            print(f"  [Resume] Failed: {e}")
            traceback.print_exc()
            self.feishu.send_message(chat_id, f"Failed to resume: {e}")

    # ── Project management ───────────────────────────────

    def _cmd_add_project(self, text: str, chat_id: str, message_id: str):
        parts = text.split()
        if len(parts) < 3:
            self.feishu.reply(message_id,
                "Usage: `/addproject <name> <path>`\n"
                "Options: `--bind` `--github <url>`\n"
                "Example: `/addproject my-app /home/dev/my-app --github https://github.com/user/repo --bind`")
            return
        name, path = parts[1], parts[2]
        bind = "--bind" in parts
        github_url = None
        if "--github" in parts:
            idx = parts.index("--github")
            if idx + 1 < len(parts):
                github_url = parts[idx + 1]

        try:
            project = self.registry.add(name=name, project_dir=path, chat_id=chat_id if bind else None, github_url=github_url)
            msg = f"**Added:** `{name}` → `{path}`"
            if github_url:
                msg += f"\nGit: `{github_url}`"
            if bind:
                msg += "\nBound ✅"
            self.feishu.reply(message_id, msg)
        except (ValueError, Exception) as e:
            self.feishu.reply(message_id, f"Error: {e}")

    def _cmd_remove_project(self, name: str | None, message_id: str):
        if not name:
            self.feishu.reply(message_id, "Usage: `/removeproject <name>`")
            return
        self.feishu.reply(message_id, f"Removed `{name}`." if self.registry.remove(name) else f"Not found: `{name}`")

    def _cmd_bind(self, name: str | None, chat_id: str, message_id: str):
        if not name:
            project = self.registry.get_by_chat_id(chat_id)
            if project:
                self.feishu.reply(message_id, f"Bound to `{project.name}` (`{project.project_dir}`)")
            else:
                names = ", ".join(f"`{p.name}`" for p in self.registry.list_projects())
                self.feishu.reply(message_id, f"Not bound.\n`/bind <name>`\nAvailable: {names}")
            return
        try:
            self.registry.bind_chat(name, chat_id)
            project = self.registry.get(name)
            self.feishu.reply(message_id, f"Bound to **{name}** (`{project.project_dir}`)")
        except ValueError as e:
            self.feishu.reply(message_id, f"Error: {e}")

    def _cmd_unbind(self, chat_id: str, message_id: str):
        name = self.registry.unbind_chat(chat_id)
        self.feishu.reply(message_id, f"Unbound from `{name}`." if name else "Not bound.")

    # ── Claude session handling ──────────────────────────

    async def _handle_prompt(self, text: str, chat_id: str, sender_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        project = self.registry.get(project_name)
        if not project:
            self.feishu.send_message(chat_id, "No project configured. Use `/projects`.")
            return

        await self.sessions.cleanup_stale()

        session = self.sessions.get(sender_id, project_name)
        if not session:
            if project.github_url:
                try:
                    status = sync_repo(project.project_dir, project.github_url)
                    print(f"  [Git] {project_name}: {status}")
                except Exception as e:
                    print(f"  [Git] {project_name}: sync failed: {e}")

            try:
                client = create_claude_client(project)
                session = Session(user_id=sender_id, bot_name=project_name, project_dir=project.project_dir,
                                  client=client, permission_mode=project.permission_mode)
                await client.connect()
                session.connected = True
                self.sessions.store(session)
                print(f"  [Session] Created {session.key}")
            except Exception as e:
                self.feishu.send_message(chat_id, f"Failed to create session: {e}")
                return

        if not session.first_prompt:
            session.first_prompt = text[:50]

        async with session.lock:
            await self._stream_response(chat_id, session, text)

    async def _stream_response(self, chat_id: str, session: Session, text: str):
        start = time.time()
        msg_id = self.feishu.send_message(chat_id, "⏳ Thinking...")
        if not msg_id:
            print("  [Feishu] Placeholder message failed, retrying...")
            msg_id = self.feishu.send_message(chat_id, "⏳ Thinking...")
            if not msg_id:
                print("  [Feishu] Placeholder failed twice — cannot stream response")
                self.feishu.send_message(chat_id, "❌ Failed to start response. Please try again.")
                return

        streamer = StreamHandler(self.feishu, chat_id, msg_id, session.bot_name, core_settings.stream_update_interval)

        try:
            await session.client.query(text)

            async for msg in session.client.receive_response():
                msg_type = type(msg).__name__

                if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                    for block in msg.content:
                        bt = type(block).__name__
                        if bt == "TextBlock" and hasattr(block, "text"):
                            streamer.on_text(block.text)
                            print(block.text, end="", flush=True)
                        elif bt == "ToolUseBlock" and hasattr(block, "name"):
                            streamer.on_tool_start(block.name, getattr(block, "input", {}) or {})
                            print(f"\n[Tool: {block.name}]", flush=True)

                elif msg_type == "UserMessage" and hasattr(msg, "content"):
                    for block in msg.content:
                        if type(block).__name__ == "ToolResultBlock":
                            streamer.on_tool_result(str(getattr(block, "content", "")), getattr(block, "is_error", False))

                elif msg_type == "SystemMessage":
                    if hasattr(msg, "data") and isinstance(msg.data, dict):
                        if sid := msg.data.get("session_id"):
                            session.session_id = sid
                        if mode := msg.data.get("permission_mode"):
                            session.permission_mode = mode

                elif msg_type == "ResultMessage":
                    if sid := getattr(msg, "session_id", None):
                        session.session_id = sid
                    break

            self.sessions.save_to_history(session)

            duration = f"{time.time() - start:.0f}s"
            streamer.finalize(duration, MODE_DISPLAY.get(session.permission_mode, session.permission_mode))
            print(f"\n  [Done] {duration}")

        except Exception as e:
            print(f"  [Error] {session.key}: {e}")
            traceback.print_exc()
            error_msg = f"❌ Error: {e}"
            partial = getattr(streamer, "response_text", "") or ""
            if isinstance(partial, str) and partial.strip():
                if len(partial) > 3000:
                    partial = partial[:3000] + "\n*(truncated)*"
                error_msg += f"\n---\n**Partial response before error:**\n{partial}"
            self.feishu.update_message(msg_id, error_msg)
            await self.sessions.close(session.user_id, session.bot_name)


def _read_first_line(path) -> str:
    try:
        return path.read_text().strip().split("\n")[0].lstrip("# ").strip()
    except Exception:
        return ""


def main():
    print("=" * 50)
    print("  Claude Workspace Bot (Feishu)")
    print("=" * 50)
    ClaudeWorkspaceBot().start()


if __name__ == "__main__":
    main()
