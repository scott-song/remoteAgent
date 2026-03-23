"""
Claude SDK Client Factory
=========================
Creates configured ClaudeSDKClient instances from agent configs.
"""

import json
from pathlib import Path
from typing import Optional

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import HookMatcher

from .agent_registry import AgentConfig
from .security import BASE_ALLOWED_COMMANDS, make_bash_security_hook


# Built-in tools to enable
BUILTIN_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "Bash",
    "Skill", "WebSearch", "WebFetch", "Task",
]

# Claude Code CLI config (for MCP server discovery)
CLAUDE_CONFIG_FILE = Path.home() / ".claude.json"


def _load_project_mcp_servers(project_dir: Path) -> dict:
    """Load MCP servers from ~/.claude.json (global + project-level, merged)."""
    if not CLAUDE_CONFIG_FILE.is_file():
        return {}
    try:
        with open(CLAUDE_CONFIG_FILE) as f:
            config = json.load(f)
        global_servers = config.get("mcpServers", {})
        project_key = str(project_dir.resolve())
        project_servers = (
            config.get("projects", {}).get(project_key, {}).get("mcpServers", {})
        )
        return {**global_servers, **project_servers}
    except (json.JSONDecodeError, IOError):
        return {}


def create_claude_client(
    agent: AgentConfig,
    resume: Optional[str] = None,
) -> ClaudeSDKClient:
    """
    Create a Claude SDK client configured from an agent config.

    Args:
        agent: Agent configuration
        resume: Session ID to resume a previous conversation
    """
    project_dir = agent.project_dir.resolve()

    # Build allowed commands set
    allowed_cmds = BASE_ALLOWED_COMMANDS | set(agent.allowed_commands)

    # Build security hook
    restricted_dir = str(project_dir) if agent.restricted else None
    security_hook = make_bash_security_hook(allowed_cmds, restricted_dir)

    # Load MCP servers: agent-configured + project-level from ~/.claude.json
    project_mcp = _load_project_mcp_servers(project_dir)
    all_mcp = {**project_mcp, **agent.mcp_servers}
    mcp_tool_wildcards = [f"mcp__{name}__*" for name in all_mcp]

    # Build options
    options_kwargs = dict(
        model=agent.model,
        allowed_tools=[*BUILTIN_TOOLS, *mcp_tool_wildcards],
        mcp_servers=all_mcp if all_mcp else None,
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher="Bash",
                    hooks=[security_hook],
                ),
            ],
        },
        max_turns=1000,
        cwd=str(project_dir),
        setting_sources=agent.setting_sources,
    )

    if agent.system_prompt:
        options_kwargs["system_prompt"] = agent.system_prompt
    if agent.permission_mode:
        options_kwargs["permission_mode"] = agent.permission_mode
    if resume:
        options_kwargs["resume"] = resume

    # Write permission settings file
    project_dir.mkdir(parents=True, exist_ok=True)
    settings_file = project_dir / ".claude_settings.json"
    settings_data = {
        "permissions": {
            "defaultMode": agent.permission_mode or "acceptEdits",
            "allow": [
                "Read(./**)", "Write(./**)", "Edit(./**)",
                "Glob(./**)", "Grep(./**)", "Bash(*)",
                *mcp_tool_wildcards,
            ],
        },
    }
    with open(settings_file, "w") as f:
        json.dump(settings_data, f, indent=2)
    options_kwargs["settings"] = str(settings_file)

    return ClaudeSDKClient(options=ClaudeAgentOptions(**options_kwargs))
