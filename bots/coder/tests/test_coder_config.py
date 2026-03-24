"""Tests for coder.config module."""
from pathlib import Path


def test_coder_settings_projects_dir():
    """projects_dir should point to a 'projects' directory."""
    from coder.config import coder_settings

    assert coder_settings.projects_dir.name == "projects"
    assert isinstance(coder_settings.projects_dir, Path)


def test_coder_settings_projects_dir_relative_to_package():
    """projects_dir should be under the coder bot directory."""
    from coder.config import coder_settings

    # bots/coder/src/coder/config.py → parents[2] = bots/coder/
    # so projects_dir = bots/coder/projects
    assert coder_settings.projects_dir.parent.name == "coder"
