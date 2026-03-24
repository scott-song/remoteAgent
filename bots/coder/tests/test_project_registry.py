"""Tests for bot.project_registry module."""

from pathlib import Path

import yaml
import pytest

from coder.project_registry import ProjectConfig, ProjectRegistry, DEFAULT_MODEL, _to_list


# ---------------------------------------------------------------------------
# _to_list
# ---------------------------------------------------------------------------

class TestToList:
    def test_string_returns_list(self):
        assert _to_list("abc") == ["abc"]

    def test_list_returns_same_list(self):
        lst = ["a", "b"]
        assert _to_list(lst) == ["a", "b"]

    def test_none_returns_empty_list(self):
        assert _to_list(None) == []

    def test_empty_list_returns_empty_list(self):
        assert _to_list([]) == []


# ---------------------------------------------------------------------------
# ProjectConfig dataclass defaults
# ---------------------------------------------------------------------------

class TestProjectConfig:
    def test_defaults(self):
        cfg = ProjectConfig(name="test", project_dir=Path("/tmp/proj"))
        assert cfg.model == DEFAULT_MODEL
        assert cfg.restricted is True
        assert cfg.permission_mode == "acceptEdits"
        assert cfg.display_name == ""
        assert cfg.description == ""
        assert cfg.system_prompt is None
        assert cfg.setting_sources == ["user", "project"]
        assert cfg.allowed_commands == []
        assert cfg.mcp_servers == {}
        assert cfg.browser_tool == "playwright"
        assert cfg.feishu_chat_ids == []
        assert cfg.github_url is None


# ---------------------------------------------------------------------------
# ProjectRegistry
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def _minimal_raw(name: str = "proj1", project_dir: str = "/tmp/proj1", **overrides) -> dict:
    raw = {"name": name, "project_dir": project_dir}
    raw.update(overrides)
    return raw


class TestProjectRegistryInit:
    def test_creates_directory_if_not_exists(self, tmp_path):
        new_dir = tmp_path / "projects"
        assert not new_dir.exists()
        ProjectRegistry(new_dir)
        assert new_dir.is_dir()


class TestProjectRegistryLoading:
    def test_load_valid_yaml(self, tmp_path):
        _write_yaml(tmp_path / "proj1.yaml", _minimal_raw())
        reg = ProjectRegistry(tmp_path)
        project = reg.get("proj1")
        assert project is not None
        assert project.name == "proj1"
        assert project.project_dir == Path("/tmp/proj1")

    def test_load_invalid_yaml_does_not_crash(self, tmp_path):
        (tmp_path / "bad.yaml").write_text("{{{{not yaml at all!!!!")
        reg = ProjectRegistry(tmp_path)
        assert reg.list_projects() == []

    def test_load_empty_yaml_does_not_crash(self, tmp_path):
        (tmp_path / "empty.yaml").write_text("")
        reg = ProjectRegistry(tmp_path)
        assert reg.list_projects() == []


class TestProjectRegistryGet:
    def test_get_returns_none_for_missing(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        assert reg.get("nonexistent") is None

    def test_get_by_chat_id_finds_project(self, tmp_path):
        _write_yaml(tmp_path / "proj1.yaml", _minimal_raw(feishu_chat_ids=["chat_abc"]))
        reg = ProjectRegistry(tmp_path)
        project = reg.get_by_chat_id("chat_abc")
        assert project is not None
        assert project.name == "proj1"

    def test_get_by_chat_id_returns_none_for_unknown(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        assert reg.get_by_chat_id("unknown_chat") is None


class TestProjectRegistryListProjects:
    def test_list_projects_returns_all(self, tmp_path):
        _write_yaml(tmp_path / "a.yaml", _minimal_raw(name="a"))
        _write_yaml(tmp_path / "b.yaml", _minimal_raw(name="b", project_dir="/tmp/b"))
        reg = ProjectRegistry(tmp_path)
        names = sorted(p.name for p in reg.list_projects())
        assert names == ["a", "b"]


class TestProjectRegistryAdd:
    def test_add_creates_project_and_yaml(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        project = reg.add("newproj", "/tmp/newproj")
        assert project.name == "newproj"
        assert reg.get("newproj") is not None
        yaml_path = tmp_path / "newproj.yaml"
        assert yaml_path.exists()
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["name"] == "newproj"
        assert data["project_dir"] == "/tmp/newproj"

    def test_add_duplicate_raises(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        reg.add("dup", "/tmp/dup")
        with pytest.raises(ValueError, match="already exists"):
            reg.add("dup", "/tmp/dup")

    def test_add_with_github_url(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        project = reg.add("gh", "/tmp/gh", github_url="https://github.com/org/repo")
        assert project.github_url == "https://github.com/org/repo"
        with open(tmp_path / "gh.yaml") as f:
            data = yaml.safe_load(f)
        assert data["github_url"] == "https://github.com/org/repo"


class TestProjectRegistryBindChat:
    def test_bind_chat(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        reg.add("proj", "/tmp/proj")
        reg.bind_chat("proj", "chat_123")
        project = reg.get_by_chat_id("chat_123")
        assert project is not None
        assert project.name == "proj"

    def test_bind_chat_unknown_project_raises(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            reg.bind_chat("nope", "chat_123")

    def test_bind_chat_already_bound_different_raises(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        reg.add("proj_a", "/tmp/a")
        reg.add("proj_b", "/tmp/b")
        reg.bind_chat("proj_a", "chat_x")
        with pytest.raises(ValueError, match="already bound"):
            reg.bind_chat("proj_b", "chat_x")

    def test_bind_chat_same_binding_is_idempotent(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        reg.add("proj", "/tmp/proj")
        reg.bind_chat("proj", "chat_x")
        reg.bind_chat("proj", "chat_x")  # no error
        assert reg.get_by_chat_id("chat_x").name == "proj"


class TestProjectRegistryUnbindChat:
    def test_unbind_chat_removes_mapping(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        reg.add("proj", "/tmp/proj", chat_id="chat_1")
        name = reg.unbind_chat("chat_1")
        assert name == "proj"
        assert reg.get_by_chat_id("chat_1") is None

    def test_unbind_chat_not_bound_returns_none(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        assert reg.unbind_chat("ghost_chat") is None


class TestProjectRegistryRemove:
    def test_remove_deletes_project_and_yaml(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        reg.add("proj", "/tmp/proj", chat_id="chat_1")
        assert reg.remove("proj") is True
        assert reg.get("proj") is None
        assert not (tmp_path / "proj.yaml").exists()
        assert reg.get_by_chat_id("chat_1") is None

    def test_remove_nonexistent_returns_false(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        assert reg.remove("nope") is False


class TestSaveYamlOptionalFields:
    def test_system_prompt_persisted(self, tmp_path):
        _write_yaml(tmp_path / "sp.yaml", _minimal_raw(name="sp", system_prompt="Be helpful"))
        reg = ProjectRegistry(tmp_path)
        project = reg.get("sp")
        assert project.system_prompt == "Be helpful"
        # Re-save and verify round-trip
        reg._save_yaml(project)
        with open(tmp_path / "sp.yaml") as f:
            data = yaml.safe_load(f)
        assert data["system_prompt"] == "Be helpful"

    def test_allowed_commands_persisted(self, tmp_path):
        _write_yaml(tmp_path / "ac.yaml", _minimal_raw(name="ac", allowed_commands=["ls", "git"]))
        reg = ProjectRegistry(tmp_path)
        project = reg.get("ac")
        reg._save_yaml(project)
        with open(tmp_path / "ac.yaml") as f:
            data = yaml.safe_load(f)
        assert data["allowed_commands"] == ["ls", "git"]

    def test_mcp_servers_persisted(self, tmp_path):
        servers = {"server1": {"url": "http://localhost:8080"}}
        _write_yaml(tmp_path / "mc.yaml", _minimal_raw(name="mc", mcp_servers=servers))
        reg = ProjectRegistry(tmp_path)
        project = reg.get("mc")
        reg._save_yaml(project)
        with open(tmp_path / "mc.yaml") as f:
            data = yaml.safe_load(f)
        assert data["mcp_servers"] == servers

    def test_github_url_persisted(self, tmp_path):
        _write_yaml(tmp_path / "gh.yaml", _minimal_raw(name="gh", github_url="https://github.com/x/y"))
        reg = ProjectRegistry(tmp_path)
        project = reg.get("gh")
        reg._save_yaml(project)
        with open(tmp_path / "gh.yaml") as f:
            data = yaml.safe_load(f)
        assert data["github_url"] == "https://github.com/x/y"

    def test_optional_fields_omitted_when_empty(self, tmp_path):
        reg = ProjectRegistry(tmp_path)
        reg.add("plain", "/tmp/plain")
        with open(tmp_path / "plain.yaml") as f:
            data = yaml.safe_load(f)
        assert "system_prompt" not in data
        assert "allowed_commands" not in data
        assert "mcp_servers" not in data
        assert "github_url" not in data
        assert "feishu_chat_ids" not in data
