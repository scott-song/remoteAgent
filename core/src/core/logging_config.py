"""
Logging configuration — stdlib logging with a configurable level.

Call ``setup_logging()`` once at process startup (each bot entrypoint does).
The level is read from the ``LOG_LEVEL`` environment variable (default ``INFO``);
an unrecognized value falls back to ``INFO`` rather than raising.
"""

from __future__ import annotations

import logging
import os

_DEFAULT_LEVEL = logging.INFO
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_configured = False


def setup_logging() -> None:
    """Configure root logging once. Idempotent.

    Level comes from ``LOG_LEVEL`` (e.g. ``DEBUG``, ``INFO``, ``WARNING``).
    Unrecognized values fall back to ``INFO``.
    """
    global _configured

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = _DEFAULT_LEVEL

    logging.basicConfig(level=level, format=_LOG_FORMAT)
    logging.getLogger().setLevel(level)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger. Use ``get_logger(__name__)`` at module scope."""
    return logging.getLogger(name)
