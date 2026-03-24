"""Tests for core.config module."""
from __future__ import annotations


def test_core_settings_defaults():
    """Module-level core_settings singleton should carry expected type defaults."""
    from core.config import core_settings

    assert isinstance(core_settings.feishu_app_id, str)
    assert isinstance(core_settings.feishu_app_secret, str)
    assert isinstance(core_settings.session_timeout_hours, int)
    assert isinstance(core_settings.stream_update_interval, float)


def test_core_settings_type_coercion():
    """session_timeout_hours should be int, stream_update_interval should be float."""
    from core.config import core_settings

    assert isinstance(core_settings.session_timeout_hours, int)
    assert isinstance(core_settings.stream_update_interval, float)
    assert core_settings.session_timeout_hours > 0
    assert core_settings.stream_update_interval > 0
