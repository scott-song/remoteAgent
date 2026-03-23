"""Tests for bot.git_sync module — clone / pull logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.git_sync import _clone, _pull, sync_repo


# ---------------------------------------------------------------------------
# sync_repo
# ---------------------------------------------------------------------------


class TestSyncRepo:
    """Route to _pull when .git exists, _clone otherwise."""

    @patch("bot.git_sync._pull", return_value="Pulled latest: abc123")
    def test_calls_pull_when_git_dir_exists(self, mock_pull, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        result = sync_repo(tmp_path, "https://github.com/org/repo.git")
        mock_pull.assert_called_once_with(tmp_path)
        assert result == "Pulled latest: abc123"

    @patch("bot.git_sync._clone", return_value="Cloned https://github.com/org/repo.git")
    def test_calls_clone_when_git_dir_missing(self, mock_clone, tmp_path: Path):
        result = sync_repo(tmp_path, "https://github.com/org/repo.git")
        mock_clone.assert_called_once_with("https://github.com/org/repo.git", tmp_path)
        assert result == "Cloned https://github.com/org/repo.git"

    @patch("bot.git_sync._clone", return_value="Cloned url")
    def test_project_dir_converted_to_path(self, mock_clone):
        """Passing a string should still work — sync_repo wraps it in Path."""
        sync_repo("/tmp/nonexistent_project_xyz", "https://example.com/r.git")
        called_target = mock_clone.call_args[0][1]
        assert isinstance(called_target, Path)


# ---------------------------------------------------------------------------
# _clone
# ---------------------------------------------------------------------------


class TestClone:
    url = "https://github.com/org/repo.git"

    @patch("bot.git_sync.subprocess.run")
    def test_success_returns_cloned_message(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        target = tmp_path / "project"
        result = _clone(self.url, target)
        assert result == f"Cloned {self.url}"
        mock_run.assert_called_once_with(
            ["git", "clone", self.url, str(target)],
            capture_output=True,
            text=True,
            timeout=300,
        )

    @patch("bot.git_sync.subprocess.run")
    def test_failure_raises_runtime_error(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="fatal: repository not found"
        )
        target = tmp_path / "project"
        with pytest.raises(RuntimeError, match="git clone failed: fatal: repository not found"):
            _clone(self.url, target)

    @patch("bot.git_sync.subprocess.run")
    def test_failure_with_empty_stderr(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        with pytest.raises(RuntimeError, match="git clone failed:"):
            _clone(self.url, tmp_path / "project")

    @patch("bot.git_sync.subprocess.run")
    def test_creates_parent_directory(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        target = tmp_path / "deep" / "nested" / "project"
        _clone(self.url, target)
        assert target.parent.exists()

    @patch("bot.git_sync.subprocess.run")
    def test_parent_already_exists(self, mock_run, tmp_path: Path):
        """mkdir(exist_ok=True) should not fail if parent already exists."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        target = tmp_path / "project"
        target.parent.mkdir(parents=True, exist_ok=True)
        result = _clone(self.url, target)
        assert result == f"Cloned {self.url}"


# ---------------------------------------------------------------------------
# _pull
# ---------------------------------------------------------------------------


class TestPull:

    @patch("bot.git_sync.subprocess.run")
    def test_success_with_new_changes(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Updating abc1234..def5678\nFast-forward\n file.py | 2 +-\n",
            stderr="",
        )
        result = _pull(tmp_path)
        assert result == "Pulled latest: Updating abc1234..def5678"
        mock_run.assert_called_once_with(
            ["git", "pull", "--ff-only"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=120,
        )

    @patch("bot.git_sync.subprocess.run")
    def test_already_up_to_date(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Already up to date.\n", stderr=""
        )
        result = _pull(tmp_path)
        assert result == "Already up to date"

    @patch("bot.git_sync.subprocess.run")
    def test_failure_returns_non_fatal_message(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="fatal: Not possible to fast-forward, aborting.",
        )
        result = _pull(tmp_path)
        assert "Pull failed (non-fatal):" in result
        assert "Not possible to fast-forward" in result

    @patch("bot.git_sync.subprocess.run")
    def test_failure_does_not_raise(self, mock_run, tmp_path: Path):
        """Pull failures are non-fatal — they should never raise."""
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: something went wrong"
        )
        # Should not raise
        result = _pull(tmp_path)
        assert isinstance(result, str)

    @patch("bot.git_sync.subprocess.run")
    def test_failure_with_empty_stderr(self, mock_run, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        result = _pull(tmp_path)
        assert "Pull failed (non-fatal):" in result

    @patch("bot.git_sync.subprocess.run")
    def test_success_with_empty_stdout(self, mock_run, tmp_path: Path):
        """When stdout is empty after success, fallback to 'ok'."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = _pull(tmp_path)
        assert result == "Pulled latest: ok"

    @patch("bot.git_sync.subprocess.run")
    def test_success_stdout_only_whitespace(self, mock_run, tmp_path: Path):
        """Whitespace-only stdout should also trigger the 'ok' fallback."""
        mock_run.return_value = MagicMock(returncode=0, stdout="   \n  \n", stderr="")
        result = _pull(tmp_path)
        assert result == "Pulled latest: ok"
