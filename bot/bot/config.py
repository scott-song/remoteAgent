"""
Configuration
=============
Loads settings from environment variables.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")


@dataclass
class Settings:
    # Rocket.Chat connection
    rc_url: str = os.getenv("RC_URL", "http://localhost:3000")
    rc_bot_password: str = os.getenv("RC_BOT_PASSWORD", "")

    # Paths
    agents_dir: Path = Path(__file__).parent.parent / "agents"

    # Session management
    session_timeout_hours: int = int(os.getenv("SESSION_TIMEOUT_HOURS", "50"))

    # Streaming
    stream_update_interval: float = float(os.getenv("STREAM_UPDATE_INTERVAL", "1.5"))

    @property
    def rc_ws_url(self) -> str:
        return self.rc_url.replace("http", "ws") + "/websocket"


settings = Settings()
