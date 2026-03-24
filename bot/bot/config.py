"""
Configuration — loads settings from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")


@dataclass
class Settings:
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    projects_dir: Path = Path(__file__).parent.parent / "projects"
    session_timeout_hours: int = int(os.getenv("SESSION_TIMEOUT_HOURS", "50"))
    stream_update_interval: float = float(os.getenv("STREAM_UPDATE_INTERVAL", "1.5"))


settings = Settings()
