"""
Security Hooks
==============
Pre-tool-use hooks that validate bash commands.
Allowlist approach — only explicitly permitted commands can run.
"""

from __future__ import annotations

import os
import shlex
from typing import Optional

# Base allowed commands (always available)
BASE_ALLOWED_COMMANDS = {
    # File inspection
    "ls", "cat", "head", "tail", "wc", "grep", "echo", "printf",
    # File operations
    "cp", "mv", "rm", "mkdir", "touch", "chmod",
    # Directory
    "pwd", "cd",
    # Node.js
    "npm", "pnpm", "npx", "node",
    # Python
    "python", "python3",
    # Version control
    "git", "gh",
    # Process
    "ps", "lsof", "sleep", "find", "pkill", "kill",
    # Shell utilities
    "true", "false", "test", "[", "which", "export", "env",
    "readlink", "basename", "dirname",
    # Text processing
    "sed", "awk", "sort", "uniq", "tr", "cut", "tee",
    # Network
    "curl",
    # Other
    "xargs", "date",
}


def extract_commands(command_string: str) -> list[str]:
    """Extract command names from a shell command string."""
    import re

    commands = []
    segments = re.split(r'(?<!\\)(?<!["\'])\s*;\s*(?!["\'])', command_string)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return []

        if not tokens:
            continue

        expect_command = True
        in_find_exec = False

        for token in tokens:
            if in_find_exec:
                if token in (";", "\\;", "+"):
                    in_find_exec = False
                continue

            if token in ("|", "||", "&&", "&"):
                expect_command = True
                continue

            if token in ("if", "then", "else", "elif", "fi", "for", "while",
                         "until", "do", "done", "case", "esac", "in", "!", "{", "}"):
                continue

            if token.startswith("-"):
                if token in ("-exec", "-execdir"):
                    in_find_exec = True
                continue

            if "=" in token and not token.startswith("="):
                continue

            if expect_command:
                cmd = os.path.basename(token)
                commands.append(cmd)
                expect_command = False

    return commands


def make_bash_security_hook(
    allowed_commands: set[str],
    restricted_project_dir: Optional[str] = None,
):
    """
    Factory for bash security hooks.

    Args:
        allowed_commands: Set of allowed command names (BASE + agent-specific)
        restricted_project_dir: If set, all path args must stay within this dir
    """

    async def _hook(input_data, tool_use_id=None, context=None):
        if input_data.get("tool_name") != "Bash":
            return {}

        command = input_data.get("tool_input", {}).get("command", "")
        if not command:
            return {}

        commands = extract_commands(command)
        if not commands:
            return {
                "decision": "block",
                "reason": f"Could not parse command: {command}",
            }

        for cmd in commands:
            if cmd not in allowed_commands:
                return {
                    "decision": "block",
                    "reason": f"Command '{cmd}' is not allowed",
                }

        if restricted_project_dir:
            ok, reason = _validate_paths(command, restricted_project_dir)
            if not ok:
                return {"decision": "block", "reason": reason}

        return {}

    return _hook


def _validate_paths(command_string: str, project_dir: str) -> tuple[bool, str]:
    """Validate that path-like arguments stay within project_dir."""
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse command for path validation"

    project_dir_normalized = os.path.realpath(project_dir)
    if not project_dir_normalized.endswith("/"):
        project_dir_normalized += "/"

    allowed_prefixes = ("/tmp/", "/var/tmp/", "/private/tmp/", "/dev/")

    for token in tokens:
        if token.startswith("-") or ("=" in token and not token.startswith("=")):
            continue

        is_path = (
            token.startswith("/")
            or token.startswith("./")
            or token.startswith("../")
            or ".." in token
        )
        if not is_path:
            continue

        # Allow /tmp, /dev, etc.
        if any(token.startswith(p) for p in allowed_prefixes):
            continue

        # Resolve and check
        if os.path.isabs(token):
            resolved = os.path.realpath(token)
        else:
            resolved = os.path.realpath(os.path.join(project_dir, token))

        if resolved == project_dir_normalized.rstrip("/"):
            continue
        if resolved.startswith(project_dir_normalized):
            continue

        return False, f"Path '{token}' resolves outside project directory"

    return True, ""
