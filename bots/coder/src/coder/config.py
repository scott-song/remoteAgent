"""
Coder bot configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CoderSettings:
    # bots/coder/src/coder/config.py → parents[2] = bots/coder/
    projects_dir: Path = Path(__file__).parents[2] / "projects"


coder_settings = CoderSettings()
