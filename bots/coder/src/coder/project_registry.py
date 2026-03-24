"""
Project registry — loads project configs from YAML, supports runtime add/remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_MODEL = "claude-opus-4-6"


def _to_list(val) -> list:
    if isinstance(val, str):
        return [val]
    return val or []


@dataclass
class ProjectConfig:
    name: str
    project_dir: Path
    display_name: str = ""
    description: str = ""
    model: str = DEFAULT_MODEL
    permission_mode: str = "acceptEdits"
    system_prompt: Optional[str] = None
    setting_sources: list[str] = field(default_factory=lambda: ["user", "project"])
    restricted: bool = True
    allowed_commands: list[str] = field(default_factory=list)
    mcp_servers: dict = field(default_factory=dict)
    browser_tool: str = "playwright"
    feishu_chat_ids: list[str] = field(default_factory=list)
    github_url: Optional[str] = None


class ProjectRegistry:
    def __init__(self, projects_dir: str | Path):
        self.projects_dir = Path(projects_dir)
        self.projects: dict[str, ProjectConfig] = {}
        self._chat_id_map: dict[str, str] = {}
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()

    def _load_all(self):
        for yaml_file in sorted(self.projects_dir.glob("*.yaml")):
            try:
                with open(yaml_file) as f:
                    raw = yaml.safe_load(f)
                if raw:
                    self._register(raw)
            except Exception as e:
                print(f"  [Projects] Error loading {yaml_file.name}: {e}")

    def _register(self, raw: dict) -> ProjectConfig:
        config = ProjectConfig(
            name=raw["name"],
            project_dir=Path(raw["project_dir"]),
            display_name=raw.get("display_name", raw["name"]),
            description=raw.get("description", ""),
            model=raw.get("model", DEFAULT_MODEL),
            permission_mode=raw.get("permission_mode", "acceptEdits"),
            system_prompt=raw.get("system_prompt"),
            setting_sources=raw.get("setting_sources", ["user", "project"]),
            restricted=raw.get("restricted", True),
            allowed_commands=raw.get("allowed_commands", []),
            mcp_servers=raw.get("mcp_servers", {}),
            browser_tool=raw.get("browser_tool", "playwright"),
            feishu_chat_ids=_to_list(raw.get("feishu_chat_ids", raw.get("feishu_chat_id"))),
            github_url=raw.get("github_url"),
        )
        self.projects[config.name] = config
        for chat_id in config.feishu_chat_ids:
            self._chat_id_map[chat_id] = config.name
        chat_info = f" (chats: {len(config.feishu_chat_ids)})" if config.feishu_chat_ids else ""
        print(f"  [Projects] {config.name} → {config.project_dir} ({config.model}){chat_info}")
        return config

    def get(self, name: str) -> Optional[ProjectConfig]:
        return self.projects.get(name)

    def get_by_chat_id(self, chat_id: str) -> Optional[ProjectConfig]:
        name = self._chat_id_map.get(chat_id)
        return self.projects.get(name) if name else None

    def list_projects(self) -> list[ProjectConfig]:
        return list(self.projects.values())

    def add(self, name: str, project_dir: str, chat_id: Optional[str] = None,
            model: str = DEFAULT_MODEL, github_url: Optional[str] = None) -> ProjectConfig:
        if name in self.projects:
            raise ValueError(f"Project '{name}' already exists")
        raw = {
            "name": name, "project_dir": project_dir, "display_name": name,
            "description": f"Project: {project_dir}", "model": model,
            "permission_mode": "acceptEdits", "setting_sources": ["user", "project"],
            "restricted": True, "feishu_chat_ids": [chat_id] if chat_id else [],
        }
        if github_url:
            raw["github_url"] = github_url
        config = self._register(raw)
        self._save_yaml(config)
        return config

    def bind_chat(self, name: str, chat_id: str) -> None:
        project = self.projects.get(name)
        if not project:
            raise ValueError(f"Project '{name}' not found")
        if chat_id in self._chat_id_map:
            existing = self._chat_id_map[chat_id]
            if existing != name:
                raise ValueError(f"Chat already bound to '{existing}'")
            return
        project.feishu_chat_ids.append(chat_id)
        self._chat_id_map[chat_id] = name
        self._save_yaml(project)

    def unbind_chat(self, chat_id: str) -> Optional[str]:
        name = self._chat_id_map.pop(chat_id, None)
        if name and name in self.projects:
            project = self.projects[name]
            project.feishu_chat_ids = [c for c in project.feishu_chat_ids if c != chat_id]
            self._save_yaml(project)
        return name

    def remove(self, name: str) -> bool:
        project = self.projects.pop(name, None)
        if not project:
            return False
        for chat_id in project.feishu_chat_ids:
            self._chat_id_map.pop(chat_id, None)
        yaml_path = self.projects_dir / f"{name}.yaml"
        if yaml_path.exists():
            yaml_path.unlink()
        return True

    def _save_yaml(self, project: ProjectConfig) -> None:
        data = {
            "name": project.name, "display_name": project.display_name,
            "description": project.description, "project_dir": str(project.project_dir),
            "model": project.model, "permission_mode": project.permission_mode,
            "setting_sources": project.setting_sources, "restricted": project.restricted,
        }
        if project.system_prompt:
            data["system_prompt"] = project.system_prompt
        if project.allowed_commands:
            data["allowed_commands"] = project.allowed_commands
        if project.mcp_servers:
            data["mcp_servers"] = project.mcp_servers
        if project.feishu_chat_ids:
            data["feishu_chat_ids"] = project.feishu_chat_ids
        if project.github_url:
            data["github_url"] = project.github_url
        with open(self.projects_dir / f"{project.name}.yaml", "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
