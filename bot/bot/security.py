"""
Security hooks — bash command allowlist and path restriction.
"""

from __future__ import annotations

import os
import re
import shlex
from typing import Optional

BASE_ALLOWED_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "grep", "echo", "printf",
    "cp", "mv", "rm", "mkdir", "touch", "chmod",
    "pwd", "cd",
    "npm", "pnpm", "npx", "node",
    "python", "python3",
    "git", "gh",
    "ps", "lsof", "sleep", "find", "pkill", "kill",
    "true", "false", "test", "[", "which", "export", "env",
    "readlink", "basename", "dirname",
    "sed", "awk", "sort", "uniq", "tr", "cut", "tee",
    "curl", "xargs", "date",
}

_SEMICOLON_RE = re.compile(r'(?<!\\)(?<!["\'])\s*;\s*(?!["\'])')

_SHELL_KEYWORDS = frozenset({
    "if", "then", "else", "elif", "fi", "for", "while",
    "until", "do", "done", "case", "esac", "in", "!", "{", "}",
})


def extract_commands(command_string: str) -> list[str]:
    """Extract command names from a shell command string."""
    commands = []
    for segment in _SEMICOLON_RE.split(command_string):
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
            if token in _SHELL_KEYWORDS:
                continue
            if token.startswith("-"):
                if token in ("-exec", "-execdir"):
                    in_find_exec = True
                continue
            if "=" in token and not token.startswith("="):
                continue
            if expect_command:
                commands.append(os.path.basename(token))
                expect_command = False

    return commands


def make_bash_security_hook(
    allowed_commands: set[str],
    restricted_project_dir: Optional[str] = None,
):
    """Create a PreToolUse hook that validates bash commands against an allowlist."""

    async def _hook(input_data, tool_use_id=None, context=None):
        if input_data.get("tool_name") != "Bash":
            return {}

        command = input_data.get("tool_input", {}).get("command", "")
        if not command:
            return {}

        commands = extract_commands(command)
        if not commands:
            return {"decision": "block", "reason": f"Could not parse command: {command}"}

        for cmd in commands:
            if cmd not in allowed_commands:
                return {"decision": "block", "reason": f"Command '{cmd}' is not allowed"}

        if restricted_project_dir:
            ok, reason = _validate_paths(command, restricted_project_dir)
            if not ok:
                return {"decision": "block", "reason": reason}

        return {}

    return _hook


_ALLOWED_PATH_PREFIXES = ("/tmp/", "/var/tmp/", "/private/tmp/", "/dev/")


def _validate_paths(command_string: str, project_dir: str) -> tuple[bool, str]:
    """Validate that path-like arguments stay within project_dir."""
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse command for path validation"

    project_dir_normalized = os.path.realpath(project_dir).rstrip("/") + "/"

    for token in tokens:
        if token.startswith("-") or ("=" in token and not token.startswith("=")):
            continue

        is_path = token.startswith("/") or token.startswith("./") or token.startswith("../") or ".." in token
        if not is_path:
            continue
        if any(token.startswith(p) for p in _ALLOWED_PATH_PREFIXES):
            continue

        resolved = os.path.realpath(token if os.path.isabs(token) else os.path.join(project_dir, token))
        if resolved == project_dir_normalized.rstrip("/") or resolved.startswith(project_dir_normalized):
            continue

        return False, f"Path '{token}' resolves outside project directory"

    return True, ""
