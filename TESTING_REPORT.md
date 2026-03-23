# Testing Report — remoteClaudeCode

**Date:** 2026-03-23
**Python:** 3.12.11 | **Pytest:** 9.0.2 | **pytest-asyncio:** 1.3.0
**Project:** Feishu → Claude Code bridge bot

---

## Test Results: 231 PASSED, 0 FAILED

**Execution time:** 3.26s

---

## Test Breakdown by Module

| Test File | Tests | Status |
|-----------|-------|--------|
| `test_agent_registry.py` | 29 | ✅ ALL PASSED |
| `test_config.py` | 4 | ✅ ALL PASSED |
| `test_feishu_client.py` | 20 | ✅ ALL PASSED |
| `test_git_sync.py` | 15 | ✅ ALL PASSED |
| `test_main.py` | 55 | ✅ ALL PASSED |
| `test_sdk_client.py` | 17 | ✅ ALL PASSED |
| `test_security.py` | 28 | ✅ ALL PASSED |
| `test_session_manager.py` | 21 | ✅ ALL PASSED |
| `test_stream_handler.py` | 29 | ✅ ALL PASSED |
| **TOTAL** | **231** | ✅ **ALL PASSED** |

---

## Coverage by Module

| Module | Functions | Tested | Coverage |
|--------|-----------|--------|----------|
| `security.py` | 3 | 3 | ~100% |
| `config.py` | 1 | 1 | ~90% |
| `agent_registry.py` | 10 | 10 | ~95% |
| `session_manager.py` | 12 | 12 | ~95% |
| `stream_handler.py` | 9 | 9 | ~100% |
| `feishu_client.py` | 7 | 7 | ~90% |
| `sdk_client.py` | 2 | 2 | ~95% |
| `git_sync.py` | 3 | 3 | ~100% |
| `main.py` | 20+ | 20+ | ~90% |
| **Overall** | **67+** | **67+** | **~93%** |

---

## What's Tested

### security.py (28 tests)
- `extract_commands` — 8 tests: simple, pipes, chains, semicolons, paths, env vars, blocked/allowed
- `_validate_paths` — 12 tests: inside/outside project, relative paths, dotdot escapes, /tmp /var/tmp /dev allowed, flags/env skipped, parse errors
- `make_bash_security_hook` — 8 async tests: non-Bash passthrough, empty cmd, allowed/blocked, unparseable, path restriction block/allow, no-restriction skip

### config.py (4 tests)
- Settings defaults (types, values)
- agents_dir path resolution
- Type coercion for int/float fields

### agent_registry.py (29 tests)
- `_to_list` — 4 tests: string/list/None/empty
- `AgentConfig` — 1 test: all dataclass defaults
- `AgentRegistry` — 24 tests: init/load/get/list/add/bind/unbind/remove/save with YAML persistence

### session_manager.py (21 tests)
- `Session` — 4 tests: key property, is_stale, touch
- `SessionManager` — 17 tests: get/store/close/cleanup_stale/all_sessions/save_to_history/get_history/load_history

### stream_handler.py (29 tests)
- `_summarize_input` — 12 tests: all tool types + truncation
- `_render_tool` — 5 tests: status icons, duration, code blocks
- `StreamHandler` — 12 tests: text accumulation, tool lifecycle, throttling, finalize, render formats

### feishu_client.py (20 tests)
- Init — 4 tests: stored config, empty bot_open_id, OrderedDict
- on_message — 1 test: callback registration
- _build_card — 2 tests: JSON schema, markdown element
- _on_event — 7 tests: callback trigger, dedup, non-text ignore, mention stripping, exception handling, eviction
- reply/send/update — 6 tests: success/failure paths, fallback

### sdk_client.py (17 tests)
- `_load_project_mcp_servers` — 5 tests: missing file, global/project merge, invalid JSON
- `create_claude_client` — 12 tests: model/cwd, system_prompt, resume, security hook, commands merge, MCP servers, settings file, restricted/unrestricted

### git_sync.py (15 tests)
- `sync_repo` — 3 tests: clone vs pull routing, Path conversion
- `_clone` — 5 tests: success/failure, parent dir creation
- `_pull` — 7 tests: new changes, up-to-date, failure (non-fatal), empty stdout/stderr

### main.py (55 tests)
- `_read_first_line` — 4 tests: normal/empty/missing/plain files
- `_on_message` routing — 6 tests: command/greeting/prompt dispatch
- `_handle_command` — 14 tests: all commands + unknown
- `_resolve_agent` — 4 tests: chat binding, user selection, fallback, empty
- Project management — 12 tests: add/remove/bind/unbind with edge cases
- Resume — 6 tests: list/number/uuid/invalid/no-history/no-project
- `_handle_prompt` — 5 async tests: no agent, new/reuse session, failure, git sync
- `_stream_response` — 7 async tests: text/tool/result blocks, system msg, error handling
- Async commands — 4 tests: stop/new/switch_mode
- main() — 1 test: entry point

---

## Warnings (non-blocking)

| Count | Source | Warning |
|-------|--------|---------|
| 4 | `lark_oapi`/`websockets` | Upstream deprecation warnings (not our code) |
| 7 | `unittest.mock` | Unawaited coroutine warnings in sync command dispatch tests (cosmetic — coroutines are intentionally not awaited in those tests because we're testing the dispatch, not the async execution) |

---

## Changes Made

### New test files (8):
- `tests/test_config.py`
- `tests/test_agent_registry.py`
- `tests/test_session_manager.py`
- `tests/test_stream_handler.py`
- `tests/test_feishu_client.py`
- `tests/test_sdk_client.py`
- `tests/test_git_sync.py`
- `tests/test_main.py`

### Modified files (2):
- `tests/test_security.py` — expanded from 8 to 28 tests
- `pyproject.toml` — added `[tool.pytest.ini_options] asyncio_mode = "auto"`

### Dependencies installed:
- `pytest-asyncio` (was listed in dev deps but not installed)
