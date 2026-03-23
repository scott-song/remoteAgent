"""
Agent Registry
==============
Loads agent configs from YAML files.
Each agent maps to one Rocket.Chat bot user and one project directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class AgentConfig:
    """Configuration for a single bot-project binding."""

    name: str
    display_name: str
    description: str

    # Claude SDK config
    project_dir: Path
    model: str = "claude-sonnet-4-5-20250929"
    permission_mode: str = "acceptEdits"
    system_prompt: Optional[str] = None
    setting_sources: list[str] = field(default_factory=lambda: ["user", "project"])

    # Security
    restricted: bool = True
    allowed_commands: list[str] = field(default_factory=list)

    # MCP servers (merged with project's ~/.claude.json)
    mcp_servers: dict = field(default_factory=dict)

    # Browser tool
    browser_tool: str = "playwright"

    # Rocket.Chat bot user
    rc_username: str = ""


class AgentRegistry:
    """Loads and manages agent configurations from YAML files."""

    def __init__(self, agents_dir: str | Path):
        self.agents_dir = Path(agents_dir)
        self.agents: dict[str, AgentConfig] = {}
        self._load_all()

    def _load_all(self):
        if not self.agents_dir.exists():
            print(f"  [Agents] Directory not found: {self.agents_dir}")
            return

        for yaml_file in sorted(self.agents_dir.glob("*.yaml")):
            try:
                with open(yaml_file) as f:
                    raw = yaml.safe_load(f)
                if not raw:
                    continue

                config = AgentConfig(
                    name=raw["name"],
                    display_name=raw.get("display_name", raw["name"]),
                    description=raw.get("description", ""),
                    project_dir=Path(raw["project_dir"]),
                    model=raw.get("model", "claude-sonnet-4-5-20250929"),
                    permission_mode=raw.get("permission_mode", "acceptEdits"),
                    system_prompt=raw.get("system_prompt"),
                    setting_sources=raw.get("setting_sources", ["user", "project"]),
                    restricted=raw.get("restricted", True),
                    allowed_commands=raw.get("allowed_commands", []),
                    mcp_servers=raw.get("mcp_servers", {}),
                    browser_tool=raw.get("browser_tool", "playwright"),
                    rc_username=raw.get("rc_username", f"bot.{raw['name']}"),
                )
                self.agents[config.name] = config
                print(f"  [Agents] Loaded: {config.name} → {config.project_dir} (rc: @{config.rc_username})")

            except Exception as e:
                print(f"  [Agents] Error loading {yaml_file.name}: {e}")

    def get(self, name: str) -> Optional[AgentConfig]:
        return self.agents.get(name)

    def get_by_rc_username(self, username: str) -> Optional[AgentConfig]:
        """Look up agent by Rocket.Chat bot username."""
        for agent in self.agents.values():
            if agent.rc_username == username:
                return agent
        return None

    def list_agents(self) -> list[AgentConfig]:
        return list(self.agents.values())
