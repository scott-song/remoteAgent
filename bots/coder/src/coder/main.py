"""
Feishu bot service — routes messages to Claude sessions, streams responses.

Command handlers live in `commands.CommandsMixin`; this module owns startup,
message dispatch, and the Claude session-execution / streaming path.
"""

from __future__ import annotations

import asyncio
import threading
import time

from core.config import core_settings
from core.feishu_client import FeishuClient, build_action_buttons
from core.logging_config import get_logger, setup_logging
from core.session_manager import Session, SessionManager
from core.stream_handler import StreamHandler

from .commands import _GREETINGS, HELP_TEXT, MODE_DISPLAY, CommandsMixin
from .config import coder_settings
from .git_sync import commit_and_push, sync_repo
from .project_registry import ProjectRegistry
from .sdk_client import create_claude_client

logger = get_logger(__name__)


class ClaudeWorkspaceBot(CommandsMixin):
    def __init__(self):
        self.registry = ProjectRegistry(projects_dir=coder_settings.projects_dir)
        self.sessions = SessionManager()
        self.feishu = FeishuClient(
            app_id=core_settings.feishu_app_id, app_secret=core_settings.feishu_app_secret
        )
        self.feishu.on_message(self._on_message)
        self._user_projects: dict[str, str] = {}
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def _schedule(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def start(self):
        projects = self.registry.list_projects()
        if not projects:
            logger.warning("No projects configured. Add YAML files to projects/")
            return
        logger.info("Claude Workspace Bot")
        logger.info(f"  Feishu app: {core_settings.feishu_app_id[:8]}...")
        logger.info(f"  Projects: {', '.join(p.name for p in projects)}")
        logger.info(f"  Default: {projects[0].name} → {projects[0].project_dir}")
        self.feishu.start(self.loop)
        logger.info("Listening for messages. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            for s in self.sessions.all_sessions():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.sessions.close(s.user_id, s.bot_name), self.loop
                    ).result(timeout=5)
                except Exception as e:
                    logger.warning(f"[Shutdown] Error closing {s.key}: {e}")

    # ── Message routing ──────────────────────────────────

    def _on_message(
        self, chat_id: str, sender_id: str, _sender_name: str, text: str, message_id: str
    ):
        logger.info(f"[Message] {sender_id[:8]}...: {text}")

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
            # Quick action commands (shown as tappable buttons on response cards)
            "/commit": lambda: self._schedule(self._cmd_commit(sender_id, chat_id, message_id)),
            "/test": lambda: self._quick_action(
                "Run the test suite and report the results.", chat_id, sender_id, message_id
            ),
            "/diff": lambda: self._quick_action(
                "Show a git diff of all uncommitted changes.", chat_id, sender_id, message_id
            ),
            "/undo": lambda: self._quick_action(
                "Undo the last file change you made. Use git checkout or restore to revert it.",
                chat_id,
                sender_id,
                message_id,
            ),
            "/continue": lambda: self._quick_action(
                "Continue with the next step.", chat_id, sender_id, message_id
            ),
        }

        handler = commands.get(cmd)
        if handler:
            handler()
        else:
            self.feishu.reply(
                message_id, f"Unknown command: `{cmd}`\nType /help for available commands."
            )

    async def _cmd_commit(self, sender_id: str, chat_id: str, message_id: str):
        """Commit & push via git directly (fast, no Claude needed)."""
        project_name = self._resolve_project(sender_id, chat_id)
        project = self.registry.get(project_name)
        if not project:
            self.feishu.send_message(chat_id, "No project configured.")
            return

        session = self.sessions.get(sender_id, project_name)
        summary = (session.first_prompt or "Update") if session else "Update"

        try:
            result = commit_and_push(project.project_dir, f"[claude] {summary[:72]}")
            self.feishu.send_message(chat_id, f"**Git:** {result}")
        except Exception as e:
            self.feishu.send_message(chat_id, f"**Git failed:** {e}")

    # ── Claude session handling ──────────────────────────

    async def _do_resume(self, sender_id: str, project_name: str, session_id: str, chat_id: str):
        project = self.registry.get(project_name)
        if not project:
            self.feishu.send_message(chat_id, f"Project `{project_name}` not found.")
            return

        await self.sessions.close(sender_id, project_name)

        if project.github_url:
            try:
                status = sync_repo(project.project_dir, project.github_url)
                logger.info(f"[Git] {project_name}: {status}")
            except Exception as e:
                logger.error(f"[Git] {project_name}: sync failed: {e}")

        try:
            client = create_claude_client(project, resume=session_id)
            session = Session(
                user_id=sender_id,
                bot_name=project_name,
                project_dir=project.project_dir,
                client=client,
                permission_mode=project.permission_mode,
                session_id=session_id,
            )
            await client.connect()
            session.connected = True
            self.sessions.store(session)
            self.feishu.send_message(
                chat_id,
                f"**Session resumed** (`{session_id[:8]}...`)\n"
                f"Project: `{project_name}`\n\nYou can continue the conversation.",
            )
        except Exception as e:
            logger.error(f"[Resume] Failed: {e}", exc_info=True)
            self.feishu.send_message(chat_id, f"Failed to resume: {e}")

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
                    logger.info(f"[Git] {project_name}: {status}")
                except Exception as e:
                    logger.error(f"[Git] {project_name}: sync failed: {e}")

            # Auto-resume: pick up the last session for this user+project
            last_sid = self.sessions.get_last_session_id(sender_id, project_name)

            try:
                if last_sid:
                    logger.info(
                        f"[Session] Auto-resuming {last_sid[:8]}... "
                        f"for {sender_id[:8]}:{project_name}"
                    )
                    client = create_claude_client(project, resume=last_sid)
                else:
                    client = create_claude_client(project)

                session = Session(
                    user_id=sender_id,
                    bot_name=project_name,
                    project_dir=project.project_dir,
                    client=client,
                    permission_mode=project.permission_mode,
                    session_id=last_sid,
                )
                await client.connect()
                session.connected = True
                self.sessions.store(session)
                if last_sid:
                    logger.info(f"[Session] Auto-resumed {session.key}")
                else:
                    logger.info(f"[Session] Created {session.key}")
            except Exception as e:
                # If auto-resume fails, fall back to a fresh session
                if last_sid:
                    logger.warning(f"[Session] Auto-resume failed, starting fresh: {e}")
                    try:
                        client = create_claude_client(project)
                        session = Session(
                            user_id=sender_id,
                            bot_name=project_name,
                            project_dir=project.project_dir,
                            client=client,
                            permission_mode=project.permission_mode,
                        )
                        await client.connect()
                        session.connected = True
                        self.sessions.store(session)
                        logger.info(f"[Session] Created fresh {session.key}")
                    except Exception as e2:
                        self.feishu.send_message(chat_id, f"Failed to create session: {e2}")
                        return
                else:
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
            logger.warning("[Feishu] Placeholder message failed, retrying...")
            msg_id = self.feishu.send_message(chat_id, "⏳ Thinking...")
            if not msg_id:
                logger.error("[Feishu] Placeholder failed twice — cannot stream response")
                self.feishu.send_message(chat_id, "❌ Failed to start response. Please try again.")
                return

        streamer = StreamHandler(
            self.feishu, chat_id, msg_id, session.bot_name, core_settings.stream_update_interval
        )

        try:
            await session.client.query(text)

            async for msg in session.client.receive_response():
                msg_type = type(msg).__name__

                if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                    for block in msg.content:
                        bt = type(block).__name__
                        if bt == "TextBlock" and hasattr(block, "text"):
                            streamer.on_text(block.text)
                            logger.debug(block.text)
                        elif bt == "ToolUseBlock" and hasattr(block, "name"):
                            streamer.on_tool_start(block.name, getattr(block, "input", {}) or {})
                            logger.debug(f"[Tool: {block.name}]")

                elif msg_type == "UserMessage" and hasattr(msg, "content"):
                    for block in msg.content:
                        if type(block).__name__ == "ToolResultBlock":
                            streamer.on_tool_result(
                                str(getattr(block, "content", "")),
                                getattr(block, "is_error", False),
                            )

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
            buttons_text = build_action_buttons(has_code_changes=streamer.has_code_changes())
            streamer.finalize(
                duration,
                MODE_DISPLAY.get(session.permission_mode, session.permission_mode),
                buttons_text=buttons_text,
            )
            logger.info(f"[Done] {duration}")

            # Auto git commit & push if enabled
            project = self.registry.get(session.bot_name)
            if project and project.auto_git and streamer.has_code_changes():
                try:
                    summary = session.first_prompt or "Auto-commit"
                    result = commit_and_push(project.project_dir, f"[claude] {summary[:72]}")
                    if "No changes" not in result:
                        self.feishu.send_message(chat_id, f"**Auto-git:** {result}")
                    logger.info(f"[Auto-git] {result}")
                except Exception as e:
                    logger.error(f"[Auto-git] Failed: {e}")
                    self.feishu.send_message(chat_id, f"**Auto-git failed:** {e}")

        except Exception as e:
            logger.error(f"[Error] {session.key}: {e}", exc_info=True)
            error_msg = f"❌ Error: {e}"
            partial = getattr(streamer, "response_text", "") or ""
            if isinstance(partial, str) and partial.strip():
                if len(partial) > 3000:
                    partial = partial[:3000] + "\n*(truncated)*"
                error_msg += f"\n---\n**Partial response before error:**\n{partial}"
            self.feishu.update_message(msg_id, error_msg)
            await self.sessions.close(session.user_id, session.bot_name)


def main():
    setup_logging()
    logger.info("Claude Workspace Bot (Feishu) starting")
    ClaudeWorkspaceBot().start()


if __name__ == "__main__":
    main()
