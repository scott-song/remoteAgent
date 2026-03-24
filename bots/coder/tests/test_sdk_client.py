"""Tests for the sdk_client module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coder.project_registry import ProjectConfig
from coder.security import BASE_ALLOWED_COMMANDS
from coder.sdk_client import _load_project_mcp_servers, create_claude_client


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_project(tmp_path: Path, **overrides) -> ProjectConfig:
    """Build a ProjectConfig with sensible defaults, overridable via kwargs."""
    defaults = dict(
        name="test-agent",
        project_dir=tmp_path / "project",
        display_name="Test Agent",
        description="A test agent",
        model="claude-opus-4-6",
        permission_mode="acceptEdits",
        system_prompt=None,
        setting_sources=["user", "project"],
        restricted=True,
        allowed_commands=[],
        mcp_servers={},
        feishu_chat_ids=[],
    )
    defaults.update(overrides)
    return ProjectConfig(**defaults)


# ── _load_project_mcp_servers tests ─────────────────────────────────────────


class TestLoadProjectMcpServers:
    def test_no_config_file_returns_empty(self, tmp_path):
        """When the config file does not exist, return {}."""
        with patch("coder.sdk_client.CLAUDE_CONFIG_FILE", tmp_path / "missing.json"):
            result = _load_project_mcp_servers(tmp_path)
        assert result == {}

    def test_global_mcp_servers_returned(self, tmp_path):
        """Global mcpServers in config are returned."""
        config_file = tmp_path / ".claude.json"
        config_file.write_text(json.dumps({
            "mcpServers": {"server-a": {"command": "a"}},
        }))
        with patch("coder.sdk_client.CLAUDE_CONFIG_FILE", config_file):
            result = _load_project_mcp_servers(tmp_path / "proj")
        assert result == {"server-a": {"command": "a"}}

    def test_project_servers_override_global(self, tmp_path):
        """Project-specific servers merge over global; project wins on conflict."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        config_file = tmp_path / ".claude.json"
        config_file.write_text(json.dumps({
            "mcpServers": {
                "shared": {"command": "global-cmd"},
                "global-only": {"command": "g"},
            },
            "projects": {
                str(project_dir.resolve()): {
                    "mcpServers": {
                        "shared": {"command": "project-cmd"},
                        "proj-only": {"command": "p"},
                    },
                },
            },
        }))
        with patch("coder.sdk_client.CLAUDE_CONFIG_FILE", config_file):
            result = _load_project_mcp_servers(project_dir)
        assert result["shared"] == {"command": "project-cmd"}
        assert result["global-only"] == {"command": "g"}
        assert result["proj-only"] == {"command": "p"}

    def test_invalid_json_returns_empty(self, tmp_path):
        """Malformed JSON falls back to {}."""
        config_file = tmp_path / ".claude.json"
        config_file.write_text("{bad json!!!")
        with patch("coder.sdk_client.CLAUDE_CONFIG_FILE", config_file):
            result = _load_project_mcp_servers(tmp_path)
        assert result == {}

    def test_valid_json_no_mcp_key_returns_empty(self, tmp_path):
        """Config with no mcpServers key returns {} (no global, no project)."""
        config_file = tmp_path / ".claude.json"
        config_file.write_text(json.dumps({"someOtherKey": True}))
        with patch("coder.sdk_client.CLAUDE_CONFIG_FILE", config_file):
            result = _load_project_mcp_servers(tmp_path)
        assert result == {}


# ── create_claude_client tests ──────────────────────────────────────────────


@patch("coder.sdk_client._load_project_mcp_servers", return_value={})
@patch("coder.sdk_client.ClaudeSDKClient")
@patch("coder.sdk_client.ClaudeAgentOptions")
class TestCreateClaudeClient:
    def test_creates_client_with_correct_model_and_cwd(
        self, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path)
        create_claude_client(project)

        kwargs = MockOptions.call_args[1]
        assert kwargs["model"] == "claude-opus-4-6"
        assert kwargs["cwd"] == str(project.project_dir.resolve())
        MockClient.assert_called_once()

    def test_system_prompt_passed_when_set(
        self, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path, system_prompt="Be helpful.")
        create_claude_client(project)

        kwargs = MockOptions.call_args[1]
        assert kwargs["system_prompt"] == "Be helpful."

    def test_system_prompt_absent_when_none(
        self, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path, system_prompt=None)
        create_claude_client(project)

        kwargs = MockOptions.call_args[1]
        assert "system_prompt" not in kwargs

    def test_resume_session_id_passed(
        self, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path)
        create_claude_client(project, resume="sess-123")

        kwargs = MockOptions.call_args[1]
        assert kwargs["resume"] == "sess-123"

    def test_resume_absent_when_none(
        self, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path)
        create_claude_client(project, resume=None)

        kwargs = MockOptions.call_args[1]
        assert "resume" not in kwargs

    @patch("coder.sdk_client.make_bash_security_hook")
    def test_security_hook_configured_for_bash(
        self, mock_make_hook, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        sentinel_hook = MagicMock(name="security_hook")
        mock_make_hook.return_value = sentinel_hook

        project = make_project(tmp_path)
        create_claude_client(project)

        kwargs = MockOptions.call_args[1]
        hooks = kwargs["hooks"]["PreToolUse"]
        assert len(hooks) == 1
        assert hooks[0].matcher == "Bash"
        assert hooks[0].hooks == [sentinel_hook]

    @patch("coder.sdk_client.make_bash_security_hook")
    def test_allowed_commands_merged(
        self, mock_make_hook, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path, allowed_commands=["docker", "make"])
        create_claude_client(project)

        called_cmds = mock_make_hook.call_args[0][0]
        expected = BASE_ALLOWED_COMMANDS | {"docker", "make"}
        assert called_cmds == expected

    def test_mcp_servers_from_agent_config_included(
        self, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        agent_mcp = {"my-server": {"command": "run-it"}}
        project = make_project(tmp_path, mcp_servers=agent_mcp)
        create_claude_client(project)

        kwargs = MockOptions.call_args[1]
        assert kwargs["mcp_servers"] == {"my-server": {"command": "run-it"}}
        assert "mcp__my-server__*" in kwargs["allowed_tools"]

    def test_mcp_servers_merged_with_project_servers(
        self, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        mock_mcp.return_value = {"proj-srv": {"command": "p"}}
        project = make_project(tmp_path, mcp_servers={"agent-srv": {"command": "a"}})
        create_claude_client(project)

        kwargs = MockOptions.call_args[1]
        assert kwargs["mcp_servers"]["proj-srv"] == {"command": "p"}
        assert kwargs["mcp_servers"]["agent-srv"] == {"command": "a"}

    def test_writes_claude_settings_json(
        self, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path)
        create_claude_client(project)

        settings_file = project.project_dir.resolve() / ".claude_settings.json"
        assert settings_file.exists()

        data = json.loads(settings_file.read_text())
        assert "permissions" in data
        assert "allow" in data["permissions"]
        assert "Bash(*)" in data["permissions"]["allow"]

    @patch("coder.sdk_client.make_bash_security_hook")
    def test_unrestricted_agent_has_no_restricted_dir(
        self, mock_make_hook, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path, restricted=False)
        create_claude_client(project)

        # restricted_dir should be None
        mock_make_hook.assert_called_once()
        called_restricted_dir = mock_make_hook.call_args[0][1]
        assert called_restricted_dir is None

    @patch("coder.sdk_client.make_bash_security_hook")
    def test_restricted_agent_passes_project_dir(
        self, mock_make_hook, MockOptions, MockClient, mock_mcp, tmp_path
    ):
        project = make_project(tmp_path, restricted=True)
        create_claude_client(project)

        called_restricted_dir = mock_make_hook.call_args[0][1]
        assert called_restricted_dir == str(project.project_dir.resolve())
