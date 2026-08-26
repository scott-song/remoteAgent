"""
Claude SDK Client Factory
=========================
Creates configured ClaudeSDKClient instances from agent configs.
"""

import json
from pathlib import Path
from typing import Any, Optional

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import HookMatcher

from .project_registry import ProjectConfig
from .security import BASE_ALLOWED_COMMANDS, make_bash_security_hook

# Built-in tools to enable
BUILTIN_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Bash",
    "Skill",
    "WebSearch",
    "WebFetch",
    "Task",
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
        project_servers = config.get("projects", {}).get(project_key, {}).get("mcpServers", {})
        return {**global_servers, **project_servers}
    except (json.JSONDecodeError, IOError):
        return {}


def create_claude_client(
    project: ProjectConfig,
    resume: Optional[str] = None,
) -> ClaudeSDKClient:
    """
    Create a Claude SDK client configured from a project config.

    Args:
        project: Project configuration
        resume: Session ID to resume a previous conversation
    """
    project_dir = project.project_dir.resolve()

    # Build allowed commands set — None disables the allowlist check, leaving the
    # project's own .claude/settings.json permissions as the sole gate.
    allowed_cmds = (
        BASE_ALLOWED_COMMANDS | set(project.allowed_commands) if project.bash_allowlist else None
    )

    # Build security hook — skipped entirely when neither gate is active, so the
    # bot adds no PreToolUse veto on top of the project's settings.json.
    restricted_dir = str(project_dir) if project.restricted else None
    bash_hooks = None
    if allowed_cmds is not None or restricted_dir:
        bash_hooks = {
            "PreToolUse": [
                HookMatcher(
                    matcher="Bash",
                    hooks=[make_bash_security_hook(allowed_cmds, restricted_dir)],
                ),
            ],
        }

    # Load MCP servers: project-configured + project-level from ~/.claude.json
    project_mcp = _load_project_mcp_servers(project_dir)
    all_mcp = {**project_mcp, **project.mcp_servers}
    mcp_tool_wildcards = [f"mcp__{name}__*" for name in all_mcp]

    # Build options
    options_kwargs: dict[str, Any] = dict(
        model=project.model,
        allowed_tools=[*BUILTIN_TOOLS, *mcp_tool_wildcards],
        mcp_servers=all_mcp if all_mcp else None,
        hooks=bash_hooks,
        max_turns=1000,
        cwd=str(project_dir),
        setting_sources=project.setting_sources,
        env={"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"},
    )

    if project.system_prompt:
        options_kwargs["system_prompt"] = project.system_prompt
    if project.permission_mode:
        options_kwargs["permission_mode"] = project.permission_mode
    if resume:
        options_kwargs["resume"] = resume

    # Ensure cwd exists — the CLI subprocess fails on a missing working directory,
    # and a project without a github_url is never cloned by git_sync.
    project_dir.mkdir(parents=True, exist_ok=True)

    # No generated settings file: permissions come from the project's own
    # .claude/settings.json (loaded via setting_sources). See ADR-0006.
    return ClaudeSDKClient(options=ClaudeAgentOptions(**options_kwargs))
