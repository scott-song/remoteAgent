"""Tests for core.logging_config."""

from __future__ import annotations

import logging

from core.logging_config import get_logger, setup_logging


def test_default_level_is_info(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    setup_logging()
    assert logging.getLogger().level == logging.INFO


def test_explicit_level_applied(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    setup_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_lowercase_level_applied(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    setup_logging()
    assert logging.getLogger().level == logging.WARNING


def test_invalid_level_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")
    setup_logging()
    assert logging.getLogger().level == logging.INFO


def test_get_logger_returns_named_logger():
    logger = get_logger("my.module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "my.module"
