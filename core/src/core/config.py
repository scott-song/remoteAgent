"""
Configuration — loads shared settings from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# core/src/core/config.py → parents[3] = repo root
load_dotenv(Path(__file__).parents[3] / ".env")


@dataclass
class CoreSettings:
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    session_timeout_hours: int = int(os.getenv("SESSION_TIMEOUT_HOURS", "50"))
    stream_update_interval: float = float(os.getenv("STREAM_UPDATE_INTERVAL", "1.5"))


core_settings = CoreSettings()
