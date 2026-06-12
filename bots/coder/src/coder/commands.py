"""
Chat command handlers for the coder bot.

`CommandsMixin` holds the slash-command handlers and project-resolution
helpers. It is mixed into `ClaudeWorkspaceBot` (see `main.py`), which provides
the instance attributes these methods use (`self.feishu`, `self.registry`,
`self.sessions`, `self._user_projects`) and the session-execution methods
(`self._handle_prompt`, `self._do_resume`).
"""

from __future__ import annotations

import re
from typing import Any

MODE_ALIASES = {"plan": "plan", "ask": "default", "auto": "acceptEdits"}
MODE_DISPLAY = {v: k for k, v in MODE_ALIASES.items()}
NO_PROJECT_MSG = "No project selected.\nUse `/bind <name>` or `/project <name>` first."
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
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


def _read_first_line(path) -> str:
    try:
        return path.read_text().strip().split("\n")[0].lstrip("# ").strip()
    except Exception:
        return ""


class CommandsMixin:
    # Attributes and methods provided by the host class (ClaudeWorkspaceBot) at runtime.
    feishu: Any
    registry: Any
    sessions: Any
    _user_projects: dict[str, str]
    _schedule: Any
    _handle_prompt: Any
    _do_resume: Any

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

    # ── Quick actions (tappable from response cards) ─────

    def _quick_action(self, prompt: str, chat_id: str, sender_id: str, message_id: str):
        """Send a predefined prompt to the active session."""
        self.feishu.reply(message_id, "⏳ Processing...")
        self._schedule(self._handle_prompt(prompt, chat_id, sender_id, message_id))

    # ── Chat commands ────────────────────────────────────

    def _cmd_projects(self, sender_id: str, chat_id: str, message_id: str):
        projects = self.registry.list_projects()
        if not projects:
            self.feishu.reply(
                message_id, "No projects.\nUse `/addproject <name> <path>` to add one."
            )
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
        session = self.sessions.get(sender_id, project_name, chat_id)
        if not session:
            self.feishu.reply(message_id, "No active session. Send a message first.")
            return
        self._schedule(self._switch_mode(session, MODE_ALIASES[mode], mode, chat_id))

    async def _switch_mode(self, session, sdk_mode: str, display: str, chat_id: str):
        try:
            await session.client.set_permission_mode(sdk_mode)
            session.permission_mode = sdk_mode
            self.feishu.send_message(chat_id, f"Mode switched to **{display}**")
        except Exception as e:
            self.feishu.send_message(chat_id, f"Failed to switch mode: {e}")

    async def _cmd_new(self, sender_id: str, chat_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        await self.sessions.close(sender_id, project_name, chat_id)
        self.registry.reload()
        self.feishu.reply(message_id, "Session reset. (project configs reloaded)")

    async def _cmd_stop(self, sender_id: str, chat_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        session = self.sessions.get(sender_id, project_name, chat_id)
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
        session = self.sessions.get(sender_id, project_name, chat_id)
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
            self.feishu.reply(
                message_id,
                f"**{project_name}** has no skills.\nAdd: `{skills_dir}/<name>/SKILL.md`",
            )
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
        self._schedule(
            self._handle_prompt(f"Invoke the skill: {name}", chat_id, sender_id, message_id)
        )

    # ── Resume ───────────────────────────────────────────

    def _cmd_resume(self, arg: str | None, sender_id: str, chat_id: str, message_id: str):
        project_name = self._resolve_project(sender_id, chat_id)
        if not project_name:
            self.feishu.reply(message_id, NO_PROJECT_MSG)
            return

        if arg is None:
            history = self.sessions.get_history(sender_id, project_name, chat_id)
            if not history:
                self.feishu.reply(
                    message_id,
                    f"No recent sessions for `{project_name}`.\n"
                    "Paste a session ID: `/resume <uuid>`",
                )
                return
            lines = [f"**Recent sessions for {project_name}:**\n"]
            for i, entry in enumerate(history, 1):
                ts = entry.get("last_active", "?")[:16].replace("T", " ")
                summary = entry.get("summary", "?")
                lines.append(f"`{i}.` [{ts}] {summary}")
            lines.append("\nResume: `/resume <number>` or `/resume <uuid>`")
            self.feishu.reply(message_id, "\n".join(lines))
            return

        session_id = None
        if arg.isdigit():
            idx = int(arg) - 1
            history = self.sessions.get_history(sender_id, project_name, chat_id)
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

    # ── Project management ───────────────────────────────

    def _cmd_add_project(self, text: str, chat_id: str, message_id: str):
        parts = text.split()
        if len(parts) < 3:
            self.feishu.reply(
                message_id,
                "Usage: `/addproject <name> <path>`\n"
                "Options: `--bind` `--github <url>`\n"
                "Example: `/addproject my-app /home/dev/my-app "
                "--github https://github.com/user/repo --bind`",
            )
            return
        name, path = parts[1], parts[2]
        bind = "--bind" in parts
        github_url = None
        if "--github" in parts:
            idx = parts.index("--github")
            if idx + 1 < len(parts):
                github_url = parts[idx + 1]

        try:
            self.registry.add(
                name=name,
                project_dir=path,
                chat_id=chat_id if bind else None,
                github_url=github_url,
            )
            msg = f"**Added:** `{name}` → `{path}`"
            if github_url:
                msg += f"\nGit: `{github_url}`"
            if bind:
                msg += "\nBound ✅"
            self.feishu.reply(message_id, msg)
        except Exception as e:
            self.feishu.reply(message_id, f"Error: {e}")

    def _cmd_remove_project(self, name: str | None, message_id: str):
        if not name:
            self.feishu.reply(message_id, "Usage: `/removeproject <name>`")
            return
        self.feishu.reply(
            message_id,
            f"Removed `{name}`." if self.registry.remove(name) else f"Not found: `{name}`",
        )

    def _cmd_bind(self, name: str | None, chat_id: str, message_id: str):
        if not name:
            project = self.registry.get_by_chat_id(chat_id)
            if project:
                self.feishu.reply(
                    message_id, f"Bound to `{project.name}` (`{project.project_dir}`)"
                )
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
