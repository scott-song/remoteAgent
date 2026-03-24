"""Tests for coder.main module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coder.main import (
    ClaudeWorkspaceBot,
    HELP_TEXT,
    MODE_ALIASES,
    MODE_DISPLAY,
    NO_PROJECT_MSG,
    _read_first_line,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(name="proj1", project_dir="/tmp/proj1", model="sonnet",
                permission_mode="acceptEdits", github_url=None,
                feishu_chat_ids=None):
    """Create a lightweight project-like object."""
    return SimpleNamespace(
        name=name,
        project_dir=Path(project_dir),
        display_name=name,
        model=model,
        permission_mode=permission_mode,
        github_url=github_url,
        feishu_chat_ids=feishu_chat_ids or [],
    )


class AsyncIterHelper:
    """Async iterator wrapper for a list."""
    def __init__(self, items):
        self._items = items
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


def _make_async_receive(items):
    """Create an async function that returns an async iterator."""
    async def _receive():
        return AsyncIterHelper(items)
    # We need receive_response to directly return the async iterable (not a coroutine)
    # The source code does: async for msg in session.client.receive_response()
    # So receive_response() must return an async iterable
    return MagicMock(return_value=AsyncIterHelper(items))


def _make_session(user_id="user1", bot_name="proj1", locked=False,
                  permission_mode="acceptEdits", session_id=None,
                  first_prompt=None, connected=True):
    """Create a mock Session with an asyncio lock."""
    session = MagicMock()
    session.user_id = user_id
    session.bot_name = bot_name
    session.permission_mode = permission_mode
    session.session_id = session_id
    session.first_prompt = first_prompt
    session.connected = connected
    session.key = f"{user_id}:{bot_name}"
    # Use a real asyncio.Lock so `async with session.lock` works
    lock = asyncio.Lock()
    if locked:
        lock._locked = True
    session.lock = lock
    session.client = MagicMock()
    session.client.query = AsyncMock()
    session.client.receive_response = _make_async_receive([])
    session.client.interrupt = MagicMock()
    session.client.set_permission_mode = AsyncMock()
    session.client.disconnect = AsyncMock()
    return session


# Message-like classes that mimic SDK types (type(msg).__name__ dispatch)
class TextBlock:
    def __init__(self, text):
        self.text = text

class ToolUseBlock:
    def __init__(self, name, input=None):
        self.name = name
        self.input = input or {}

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


# ---------------------------------------------------------------------------
# Bot fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def bot():
    with patch('coder.main.ProjectRegistry') as mock_registry_cls, \
         patch('coder.main.SessionManager') as mock_sessions_cls, \
         patch('coder.main.FeishuClient') as mock_feishu_cls, \
         patch('coder.main.core_settings') as mock_core_settings, \
         patch('coder.main.coder_settings') as mock_coder_settings, \
         patch('coder.main.threading'):
        mock_coder_settings.projects_dir = '/tmp/projects'
        mock_core_settings.feishu_app_id = 'test_id'
        mock_core_settings.feishu_app_secret = 'test_secret'
        mock_core_settings.stream_update_interval = 1.5
        b = ClaudeWorkspaceBot()
        b.registry = mock_registry_cls.return_value
        b.sessions = mock_sessions_cls.return_value
        b.feishu = mock_feishu_cls.return_value
        b.loop = asyncio.new_event_loop()
        yield b
        b.loop.close()


# ---------------------------------------------------------------------------
# _read_first_line
# ---------------------------------------------------------------------------

class TestReadFirstLine:
    def test_normal_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# My Title\nSecond line")
        assert _read_first_line(f) == "My Title"

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        assert _read_first_line(f) == ""

    def test_nonexistent_path(self, tmp_path):
        f = tmp_path / "does_not_exist.md"
        assert _read_first_line(f) == ""

    def test_no_hash_prefix(self, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("Just a plain line\nAnother line")
        assert _read_first_line(f) == "Just a plain line"


# ---------------------------------------------------------------------------
# _on_message routing
# ---------------------------------------------------------------------------

class TestOnMessage:
    def test_command_routes_to_handle_command(self, bot):
        with patch.object(bot, '_handle_command') as mock_cmd:
            bot._on_message("chat1", "user1", "User", "/help", "msg1")
            mock_cmd.assert_called_once_with("/help", "chat1", "user1", "msg1")

    def test_greeting_replies_with_help(self, bot):
        bot._on_message("chat1", "user1", "User", "hello", "msg1")
        bot.feishu.reply.assert_called_once_with("msg1", HELP_TEXT)

    def test_greeting_case_insensitive(self, bot):
        bot._on_message("chat1", "user1", "User", "Hello", "msg1")
        bot.feishu.reply.assert_called_once_with("msg1", HELP_TEXT)

    def test_greeting_hi(self, bot):
        bot._on_message("chat1", "user1", "User", "hi", "msg1")
        bot.feishu.reply.assert_called_once_with("msg1", HELP_TEXT)

    def test_regular_text_sends_processing(self, bot):
        with patch.object(bot, '_schedule'):
            bot._on_message("chat1", "user1", "User", "do something", "msg1")
            bot.feishu.reply.assert_called_once_with("msg1", "\u23f3 Processing...")

    def test_regular_text_schedules_prompt(self, bot):
        with patch.object(bot, '_schedule') as mock_sched:
            bot._on_message("chat1", "user1", "User", "do something", "msg1")
            mock_sched.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_command dispatch
# ---------------------------------------------------------------------------

class TestHandleCommand:
    def test_help(self, bot):
        bot._handle_command("/help", "chat1", "user1", "msg1")
        bot.feishu.reply.assert_called_once_with("msg1", HELP_TEXT)

    def test_unknown_command(self, bot):
        bot._handle_command("/foobar", "chat1", "user1", "msg1")
        bot.feishu.reply.assert_called_once()
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Unknown command" in reply_text
        assert "/foobar" in reply_text

    def test_projects_lists_all(self, bot):
        projects = [_make_project("p1"), _make_project("p2")]
        bot.registry.list_projects.return_value = projects
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {}
        bot._handle_command("/projects", "chat1", "user1", "msg1")
        bot.feishu.reply.assert_called_once()
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "p1" in reply_text
        assert "p2" in reply_text

    def test_project_with_valid_name(self, bot):
        project = _make_project("proj1")
        bot.registry.get.return_value = project
        bot._handle_command("/project proj1", "chat1", "user1", "msg1")
        bot.feishu.reply.assert_called_once()
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "proj1" in reply_text
        assert bot._user_projects["user1"] == "proj1"

    def test_project_with_invalid_name(self, bot):
        bot.registry.get.return_value = None
        bot.registry.list_projects.return_value = [_make_project("p1")]
        bot._handle_command("/project badname", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Unknown project" in reply_text

    def test_project_no_name_shows_list(self, bot):
        projects = [_make_project("p1")]
        bot.registry.list_projects.return_value = projects
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {}
        bot._handle_command("/project", "chat1", "user1", "msg1")
        bot.feishu.reply.assert_called_once()
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "p1" in reply_text

    def test_mode_valid(self, bot):
        session = _make_session()
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get.return_value = session
        with patch.object(bot, '_schedule') as mock_sched:
            bot._handle_command("/mode plan", "chat1", "user1", "msg1")
            mock_sched.assert_called_once()

    def test_mode_invalid(self, bot):
        bot._handle_command("/mode badmode", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Usage" in reply_text

    def test_mode_no_arg(self, bot):
        bot._handle_command("/mode", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Usage" in reply_text

    def test_mode_no_active_session(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get.return_value = None
        bot._handle_command("/mode plan", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "No active session" in reply_text

    def test_new_resets_session(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        with patch.object(bot, '_schedule') as mock_sched:
            bot._handle_command("/new", "chat1", "user1", "msg1")
            mock_sched.assert_called_once()

    def test_stop_with_running_session(self, bot):
        session = _make_session(locked=True)
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get.return_value = session
        with patch.object(bot, '_schedule') as mock_sched:
            bot._handle_command("/stop", "chat1", "user1", "msg1")
            mock_sched.assert_called_once()

    def test_status_with_session(self, bot):
        session = _make_session(permission_mode="plan")
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get.return_value = session
        bot._handle_command("/status", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "plan" in reply_text

    def test_status_without_session(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get.return_value = None
        bot._handle_command("/status", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "No active session" in reply_text


# ---------------------------------------------------------------------------
# _resolve_project
# ---------------------------------------------------------------------------

class TestResolveProject:
    def test_returns_project_from_chat_binding(self, bot):
        project = _make_project("bound-proj")
        bot.registry.get_by_chat_id.return_value = project
        assert bot._resolve_project("user1", "chat1") == "bound-proj"

    def test_falls_back_to_user_last_selected(self, bot):
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {"user1": "user-proj"}
        bot.registry.get.return_value = _make_project("user-proj")
        assert bot._resolve_project("user1", "chat1") == "user-proj"

    def test_falls_back_to_first_project(self, bot):
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {}
        bot.registry.get.return_value = None
        bot.registry.list_projects.return_value = [_make_project("first")]
        assert bot._resolve_project("user1", "chat1") == "first"

    def test_returns_empty_when_no_projects(self, bot):
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {}
        bot.registry.get.return_value = None
        bot.registry.list_projects.return_value = []
        assert bot._resolve_project("user1", "chat1") == ""


# ---------------------------------------------------------------------------
# Project management commands
# ---------------------------------------------------------------------------

class TestProjectManagement:
    def test_addproject_valid(self, bot):
        bot.registry.add.return_value = _make_project("newproj", "/tmp/newproj")
        bot._handle_command("/addproject newproj /tmp/newproj", "chat1", "user1", "msg1")
        bot.registry.add.assert_called_once_with(
            name="newproj", project_dir="/tmp/newproj",
            chat_id=None, github_url=None,
        )
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "newproj" in reply_text

    def test_addproject_with_bind_and_github(self, bot):
        bot.registry.add.return_value = _make_project("proj", "/tmp/proj", github_url="https://github.com/u/r")
        bot._handle_command(
            "/addproject proj /tmp/proj --github https://github.com/u/r --bind",
            "chat1", "user1", "msg1",
        )
        bot.registry.add.assert_called_once_with(
            name="proj", project_dir="/tmp/proj",
            chat_id="chat1", github_url="https://github.com/u/r",
        )
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Bound" in reply_text
        assert "github.com" in reply_text

    def test_addproject_too_few_args(self, bot):
        bot._handle_command("/addproject onlyname", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Usage" in reply_text

    def test_addproject_duplicate(self, bot):
        bot.registry.add.side_effect = ValueError("duplicate")
        bot._handle_command("/addproject dup /tmp/dup", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Error" in reply_text

    def test_removeproject_valid(self, bot):
        bot.registry.remove.return_value = True
        bot._handle_command("/removeproject proj1", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Removed" in reply_text

    def test_removeproject_not_found(self, bot):
        bot.registry.remove.return_value = False
        bot._handle_command("/removeproject nope", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Not found" in reply_text

    def test_removeproject_no_name(self, bot):
        bot._handle_command("/removeproject", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Usage" in reply_text

    def test_bind_with_name(self, bot):
        bot.registry.bind_chat.return_value = None
        bot.registry.get.return_value = _make_project("proj1")
        bot._handle_command("/bind proj1", "chat1", "user1", "msg1")
        bot.registry.bind_chat.assert_called_once_with("proj1", "chat1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Bound" in reply_text

    def test_bind_without_name_shows_current(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot._handle_command("/bind", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "proj1" in reply_text

    def test_bind_without_name_not_bound(self, bot):
        bot.registry.get_by_chat_id.return_value = None
        bot.registry.list_projects.return_value = [_make_project("p1")]
        bot._handle_command("/bind", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Not bound" in reply_text

    def test_unbind(self, bot):
        bot.registry.unbind_chat.return_value = "proj1"
        bot._handle_command("/unbind", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Unbound" in reply_text
        assert "proj1" in reply_text

    def test_unbind_not_bound(self, bot):
        bot.registry.unbind_chat.return_value = None
        bot._handle_command("/unbind", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Not bound" in reply_text


# ---------------------------------------------------------------------------
# Resume commands
# ---------------------------------------------------------------------------

class TestResume:
    def test_resume_no_arg_lists_history(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get_history.return_value = [
            {"session_id": "abc-123", "last_active": "2025-01-01T12:00:00", "summary": "Fix bug"},
        ]
        bot._handle_command("/resume", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Fix bug" in reply_text
        assert "Recent sessions" in reply_text

    def test_resume_with_number(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get_history.return_value = [
            {"session_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "last_active": "2025-01-01T12:00:00", "summary": "task"},
        ]
        with patch.object(bot, '_schedule') as mock_sched:
            bot._handle_command("/resume 1", "chat1", "user1", "msg1")
            # Should reply with resuming message
            bot.feishu.reply.assert_called_once()
            reply_text = bot.feishu.reply.call_args[0][1]
            assert "Resuming" in reply_text
            mock_sched.assert_called_once()

    def test_resume_with_uuid(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        uuid = "12345678-1234-1234-1234-123456789abc"
        with patch.object(bot, '_schedule') as mock_sched:
            bot._handle_command(f"/resume {uuid}", "chat1", "user1", "msg1")
            bot.feishu.reply.assert_called_once()
            reply_text = bot.feishu.reply.call_args[0][1]
            assert "Resuming" in reply_text
            mock_sched.assert_called_once()

    def test_resume_invalid_number(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get_history.return_value = [
            {"session_id": "abc", "last_active": "2025-01-01T12:00:00", "summary": "task"},
        ]
        bot._handle_command("/resume 5", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Invalid number" in reply_text

    def test_resume_no_history(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get_history.return_value = []
        bot._handle_command("/resume", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "No recent sessions" in reply_text

    def test_resume_no_project(self, bot):
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {}
        bot.registry.get.return_value = None
        bot.registry.list_projects.return_value = []
        bot._handle_command("/resume", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "No project" in reply_text


# ---------------------------------------------------------------------------
# _handle_prompt (async)
# ---------------------------------------------------------------------------

class TestHandlePrompt:
    @pytest.mark.asyncio
    async def test_no_project_sends_error(self, bot):
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {}
        bot.registry.get.return_value = None
        bot.registry.list_projects.return_value = []

        await bot._handle_prompt("test", "chat1", "user1", "msg1")
        # _resolve_project returns "" and registry.get("") returns None
        bot.feishu.send_message.assert_called_once()
        reply_text = bot.feishu.send_message.call_args[0][1]
        assert "No project configured" in reply_text

    @pytest.mark.asyncio
    async def test_creates_new_session(self, bot):
        project = _make_project("proj1")
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        bot.sessions.get.return_value = None
        bot.sessions.cleanup_stale = AsyncMock()
        bot.sessions.save_to_history = MagicMock()

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.receive_response = _make_async_receive([])

        with patch('coder.main.create_claude_client', return_value=mock_client), \
             patch('coder.main.StreamHandler') as mock_sh_cls, \
             patch('coder.main.Session') as mock_session_cls:
            mock_session = _make_session()
            mock_session.first_prompt = None
            mock_session.client = mock_client
            mock_session_cls.return_value = mock_session
            bot.feishu.send_message.return_value = "sent_msg_id"

            await bot._handle_prompt("test prompt", "chat1", "user1", "msg1")

            mock_client.connect.assert_called_once()
            bot.sessions.store.assert_called_once()

    @pytest.mark.asyncio
    async def test_reuses_existing_session(self, bot):
        project = _make_project("proj1")
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        session = _make_session()
        session.first_prompt = "existing"
        bot.sessions.get.return_value = session
        bot.sessions.cleanup_stale = AsyncMock()
        bot.sessions.save_to_history = MagicMock()
        bot.feishu.send_message.return_value = "sent_msg_id"

        with patch('coder.main.StreamHandler'):
            await bot._handle_prompt("test", "chat1", "user1", "msg1")

        # Should NOT call create_claude_client since session exists
        bot.sessions.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_creation_failure(self, bot):
        project = _make_project("proj1")
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        bot.sessions.get.return_value = None
        bot.sessions.cleanup_stale = AsyncMock()

        with patch('coder.main.create_claude_client', side_effect=Exception("connect failed")):
            await bot._handle_prompt("test", "chat1", "user1", "msg1")

        bot.feishu.send_message.assert_called()
        reply_text = bot.feishu.send_message.call_args[0][1]
        assert "Failed to create session" in reply_text

    @pytest.mark.asyncio
    async def test_git_sync_called_when_github_url_set(self, bot):
        project = _make_project("proj1", github_url="https://github.com/u/r")
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        bot.sessions.get.return_value = None
        bot.sessions.cleanup_stale = AsyncMock()
        bot.sessions.save_to_history = MagicMock()

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.receive_response = _make_async_receive([])

        with patch('coder.main.create_claude_client', return_value=mock_client), \
             patch('coder.main.sync_repo') as mock_sync, \
             patch('coder.main.StreamHandler'), \
             patch('coder.main.Session') as mock_session_cls:
            mock_session = _make_session()
            mock_session.first_prompt = None
            mock_session.client = mock_client
            mock_session_cls.return_value = mock_session
            bot.feishu.send_message.return_value = "sent_msg_id"

            await bot._handle_prompt("test", "chat1", "user1", "msg1")

            mock_sync.assert_called_once_with(project.project_dir, "https://github.com/u/r")


# ---------------------------------------------------------------------------
# _stream_response (async)
# ---------------------------------------------------------------------------

class TestStreamResponse:
    @pytest.mark.asyncio
    async def test_text_blocks_forwarded(self, bot):
        session = _make_session()
        msg = AssistantMessage([TextBlock("Hello world")])

        session.client.query = AsyncMock()
        session.client.receive_response = _make_async_receive([msg])
        bot.feishu.send_message.return_value = "msg_id"

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            mock_streamer = MagicMock()
            mock_sh_cls.return_value = mock_streamer
            await bot._stream_response("chat1", session, "test")
            mock_streamer.on_text.assert_called_once_with("Hello world")

    @pytest.mark.asyncio
    async def test_tool_use_blocks_forwarded(self, bot):
        session = _make_session()
        msg = AssistantMessage([ToolUseBlock("bash", {"cmd": "ls"})])

        session.client.query = AsyncMock()
        session.client.receive_response = _make_async_receive([msg])
        bot.feishu.send_message.return_value = "msg_id"

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            mock_streamer = MagicMock()
            mock_sh_cls.return_value = mock_streamer
            await bot._stream_response("chat1", session, "test")
            mock_streamer.on_tool_start.assert_called_once_with("bash", {"cmd": "ls"})

    @pytest.mark.asyncio
    async def test_tool_result_blocks_forwarded(self, bot):
        session = _make_session()
        msg = UserMessage([ToolResultBlock("output text", is_error=False)])

        session.client.query = AsyncMock()
        session.client.receive_response = _make_async_receive([msg])
        bot.feishu.send_message.return_value = "msg_id"

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            mock_streamer = MagicMock()
            mock_sh_cls.return_value = mock_streamer
            await bot._stream_response("chat1", session, "test")
            mock_streamer.on_tool_result.assert_called_once_with("output text", False)

    @pytest.mark.asyncio
    async def test_system_message_sets_session_id(self, bot):
        session = _make_session()
        msg = SystemMessage({"session_id": "new-session-id"})

        session.client.query = AsyncMock()
        session.client.receive_response = _make_async_receive([msg])
        bot.feishu.send_message.return_value = "msg_id"

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            mock_sh_cls.return_value = MagicMock()
            await bot._stream_response("chat1", session, "test")
            assert session.session_id == "new-session-id"

    @pytest.mark.asyncio
    async def test_result_message_breaks_loop(self, bot):
        session = _make_session()
        assist_msg = AssistantMessage([TextBlock("partial")])
        result_msg = ResultMessage(session_id="final-id")
        extra_msg = AssistantMessage([TextBlock("should not see")])

        session.client.query = AsyncMock()
        session.client.receive_response = _make_async_receive(
            [assist_msg, result_msg, extra_msg]
        )
        bot.feishu.send_message.return_value = "msg_id"

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            mock_streamer = MagicMock()
            mock_sh_cls.return_value = mock_streamer
            await bot._stream_response("chat1", session, "test")
            mock_streamer.on_text.assert_called_once_with("partial")
            assert session.session_id == "final-id"

    @pytest.mark.asyncio
    async def test_error_during_streaming_closes_session(self, bot):
        session = _make_session()
        session.client.query = AsyncMock(side_effect=Exception("query failed"))
        bot.feishu.send_message.return_value = "msg_id"
        bot.sessions.close = AsyncMock()

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            mock_sh_cls.return_value = MagicMock()
            await bot._stream_response("chat1", session, "test")

        bot.feishu.update_message.assert_called_once()
        error_text = bot.feishu.update_message.call_args[0][1]
        assert "Error" in error_text
        bot.sessions.close.assert_called_once_with(session.user_id, session.bot_name)

    @pytest.mark.asyncio
    async def test_returns_early_when_no_msg_id(self, bot):
        """When placeholder fails even after retry, response is aborted with error message."""
        session = _make_session()
        bot.feishu.send_message.return_value = ""

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            await bot._stream_response("chat1", session, "test")
            mock_sh_cls.assert_not_called()
            session.client.query.assert_not_called()
        # Should have tried send_message multiple times (retry) + error message
        assert bot.feishu.send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_error_shows_partial_response(self, bot):
        """When streaming errors out after partial text, error includes partial content."""
        session = _make_session()
        session.client.query = AsyncMock(side_effect=Exception("boom"))
        bot.feishu.send_message.return_value = "msg_id"
        bot.sessions.close = AsyncMock()

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            mock_streamer = MagicMock()
            mock_streamer.response_text = "Here is the partial answer"
            mock_sh_cls.return_value = mock_streamer
            await bot._stream_response("chat1", session, "test")

        error_text = bot.feishu.update_message.call_args[0][1]
        assert "boom" in error_text
        assert "Partial response" in error_text
        assert "Here is the partial answer" in error_text

    @pytest.mark.asyncio
    async def test_error_without_partial_shows_only_error(self, bot):
        """When streaming errors before any text, only error is shown."""
        session = _make_session()
        session.client.query = AsyncMock(side_effect=Exception("boom"))
        bot.feishu.send_message.return_value = "msg_id"
        bot.sessions.close = AsyncMock()

        with patch('coder.main.StreamHandler') as mock_sh_cls:
            mock_streamer = MagicMock()
            mock_streamer.response_text = ""
            mock_sh_cls.return_value = mock_streamer
            await bot._stream_response("chat1", session, "test")

        error_text = bot.feishu.update_message.call_args[0][1]
        assert "boom" in error_text
        assert "Partial response" not in error_text


# ---------------------------------------------------------------------------
# _cmd_stop (async)
# ---------------------------------------------------------------------------

class TestCmdStop:
    @pytest.mark.asyncio
    async def test_stop_no_session(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get.return_value = None
        await bot._cmd_stop("user1", "chat1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "No active session" in reply_text

    @pytest.mark.asyncio
    async def test_stop_nothing_running(self, bot):
        session = _make_session(locked=False)
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get.return_value = session
        await bot._cmd_stop("user1", "chat1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Nothing running" in reply_text

    @pytest.mark.asyncio
    async def test_stop_interrupts_running(self, bot):
        session = _make_session(locked=True)
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.get.return_value = session
        await bot._cmd_stop("user1", "chat1", "msg1")
        session.client.interrupt.assert_called_once()
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "Interrupted" in reply_text


# ---------------------------------------------------------------------------
# _cmd_new (async)
# ---------------------------------------------------------------------------

class TestCmdNew:
    @pytest.mark.asyncio
    async def test_new_resets(self, bot):
        bot.registry.get_by_chat_id.return_value = _make_project("proj1")
        bot.sessions.close = AsyncMock()
        await bot._cmd_new("user1", "chat1", "msg1")
        bot.sessions.close.assert_called_once()
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "reset" in reply_text.lower()


# ---------------------------------------------------------------------------
# _switch_mode (async)
# ---------------------------------------------------------------------------

class TestSwitchMode:
    @pytest.mark.asyncio
    async def test_switch_mode_success(self, bot):
        session = _make_session()
        await bot._switch_mode(session, "plan", "plan", "chat1")
        session.client.set_permission_mode.assert_called_once_with("plan")
        assert session.permission_mode == "plan"
        bot.feishu.send_message.assert_called_once()
        reply_text = bot.feishu.send_message.call_args[0][1]
        assert "plan" in reply_text

    @pytest.mark.asyncio
    async def test_switch_mode_failure(self, bot):
        session = _make_session()
        session.client.set_permission_mode = AsyncMock(side_effect=Exception("fail"))
        await bot._switch_mode(session, "plan", "plan", "chat1")
        reply_text = bot.feishu.send_message.call_args[0][1]
        assert "Failed" in reply_text


# ---------------------------------------------------------------------------
# Skills commands
# ---------------------------------------------------------------------------

class TestSkills:
    def test_skills_no_project(self, bot):
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {}
        bot.registry.get.return_value = None
        bot.registry.list_projects.return_value = []
        bot._handle_command("/skills", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "No project" in reply_text

    def test_skills_no_skills_dir(self, bot, tmp_path):
        project = _make_project("proj1", project_dir=str(tmp_path))
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        bot._handle_command("/skills", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "has no skills" in reply_text

    def test_skills_with_skill_folder(self, bot, tmp_path):
        # Create .claude/skills/deploy/SKILL.md
        skills_dir = tmp_path / ".claude" / "skills" / "deploy"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# Deploy to production\nDeploy steps here.")
        project = _make_project("proj1", project_dir=str(tmp_path))
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        bot._handle_command("/skills", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "deploy" in reply_text
        assert "Deploy to production" in reply_text

    def test_skills_with_standalone_md(self, bot, tmp_path):
        # Create .claude/skills/review.md
        skills_dir = tmp_path / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "review.md").write_text("# Code review\nReview checklist.")
        project = _make_project("proj1", project_dir=str(tmp_path))
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        bot._handle_command("/skills", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "review" in reply_text
        assert "Code review" in reply_text

    def test_skills_empty_skills_dir(self, bot, tmp_path):
        # Create .claude/skills/ but no files
        skills_dir = tmp_path / ".claude" / "skills"
        skills_dir.mkdir(parents=True)
        project = _make_project("proj1", project_dir=str(tmp_path))
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        bot._handle_command("/skills", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "has no skills" in reply_text

    def test_skill_no_name_shows_skills(self, bot, tmp_path):
        project = _make_project("proj1", project_dir=str(tmp_path))
        bot.registry.get_by_chat_id.return_value = project
        bot.registry.get.return_value = project
        bot._handle_command("/skill", "chat1", "user1", "msg1")
        # Should delegate to _cmd_skills → "has no skills" (no skills dir)
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "has no skills" in reply_text

    def test_skill_no_project(self, bot):
        bot.registry.get_by_chat_id.return_value = None
        bot._user_projects = {}
        bot.registry.get.return_value = None
        bot.registry.list_projects.return_value = []
        bot._handle_command("/skill deploy", "chat1", "user1", "msg1")
        reply_text = bot.feishu.reply.call_args[0][1]
        assert "No project" in reply_text

    def test_skill_valid_schedules_prompt(self, bot):
        project = _make_project("proj1")
        bot.registry.get_by_chat_id.return_value = project
        with patch.object(bot, '_schedule') as mock_sched:
            bot._handle_command("/skill deploy", "chat1", "user1", "msg1")
            bot.feishu.reply.assert_called_once_with("msg1", "⏳ Processing...")
            mock_sched.assert_called_once()


# ---------------------------------------------------------------------------
# main() function
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_calls_start(self):
        with patch('coder.main.ClaudeWorkspaceBot') as mock_cls:
            mock_bot = MagicMock()
            mock_cls.return_value = mock_bot
            main()
            mock_bot.start.assert_called_once()
