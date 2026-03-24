"""Tests for bot.config module."""
from __future__ import annotations

from pathlib import Path


def test_settings_defaults():
    """Module-level settings singleton should carry expected type defaults."""
    from bot.config import settings

    assert isinstance(settings.feishu_app_id, str)
    assert isinstance(settings.feishu_app_secret, str)
    assert isinstance(settings.session_timeout_hours, int)
    assert isinstance(settings.stream_update_interval, float)


def test_settings_projects_dir():
    """projects_dir should point to a 'projects' directory."""
    from bot.config import settings

    assert settings.projects_dir.name == "projects"
    assert isinstance(settings.projects_dir, Path)


def test_settings_projects_dir_relative_to_package():
    """projects_dir should be a sibling of the bot package directory."""
    from bot.config import settings

    # projects_dir = Path(__file__).parent.parent / "projects"
    # i.e., it is <bot_pkg>/../projects
    assert settings.projects_dir.parent.name == "bot"


def test_settings_type_coercion():
    """session_timeout_hours should be int, stream_update_interval should be float."""
    from bot.config import settings

    assert isinstance(settings.session_timeout_hours, int)
    assert isinstance(settings.stream_update_interval, float)
    # Verify reasonable defaults (unless overridden by .env)
    assert settings.session_timeout_hours > 0
    assert settings.stream_update_interval > 0
