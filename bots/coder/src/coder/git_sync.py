"""
Git sync — clone or pull a project before starting work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def commit_and_push(project_dir: Path, message: str = "Auto-commit by Claude") -> str:
    """
    Stage all changes, commit with the given message, and push.
    Returns a status string.
    """
    project_dir = Path(project_dir)

    if not (project_dir / ".git").exists():
        return "Not a git repo — skipped"

    # Stage all changes
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=30,
    )

    # Check if there are staged changes
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        return "No changes to commit"

    # Commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(project_dir), capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git commit failed: {result.stderr.strip()}")

    # Push
    result = subprocess.run(
        ["git", "push"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        # Commit succeeded but push failed — not fatal
        return f"Committed but push failed: {result.stderr.strip()}"

    return "Committed and pushed"


def sync_repo(project_dir: Path, github_url: str) -> str:
    """
    Ensure project_dir has the latest code from github_url.
    Clones if not exist, pulls if already cloned.

    Returns a status message.
    """
    project_dir = Path(project_dir)

    if (project_dir / ".git").exists():
        return _pull(project_dir)
    else:
        return _clone(github_url, project_dir)


def _clone(url: str, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", url, str(target)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr.strip()}")
    return f"Cloned {url}"


def _pull(project_dir: Path) -> str:
    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=str(project_dir),
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        # Pull failed (e.g., diverged) — not fatal, just warn
        return f"Pull failed (non-fatal): {result.stderr.strip()}"
    output = result.stdout.strip()
    if "Already up to date" in output:
        return "Already up to date"
    return f"Pulled latest: {output.splitlines()[0] if output else 'ok'}"
