# Design: platform/hardening

> Owner: Architect · Status: approved · Last updated: 2026-06-12
> Spec: `docs/sdlc/specs/platform/hardening.md` · Targets spec version: 2026-06-12 (commit `249915b`)

## Summary

Add the build/quality/onboarding scaffolding the monorepo lacks: a GitHub Actions CI workflow (test matrix + coverage gate), ruff + mypy + pre-commit tooling wired into the Makefile, pinned dependencies with a compiled lockfile, a Python-version probe in the Makefile, a small stdlib-`logging` layer in `core` that replaces the 40 `print()` sites, a synced `.env.example`, and three docs (`CONTRIBUTING.md`, `ARCHITECTURE.md`, `.claude/CLAUDE.md`). No runtime behavior changes.

## System constraints

- **ADR-0001 (monorepo + pip editable)** → tooling runs across `core/` + `bots/*` from repo root; lockfile must capture the editable workspace; `remoteagent-core` gets a real version to pin against.
- **ADR-0002 (Python ≥ 3.10)** → CI matrix is 3.10/3.11/3.12; `requires-python = ">=3.10"`; Makefile probes for ≥3.10 instead of hardcoding 3.12.
- **ADR-0007 (dotenv secrets)** → `.env.example` is the canonical var list; CI must not require real secrets (tests mock the Feishu/SDK boundaries).
- **ADR-0008 (pytest + CI coverage gate)** → CI runs pytest with `pytest-cov` and fails under the coverage floor (85%, per spec).

## Architecture

Five independent workstreams, no runtime coupling:

```
repo root
├── .github/workflows/ci.yml      ← AC-1,2  (test matrix 3.10-3.12 + coverage gate; lint+type job)
├── pyproject.toml (root)         ← AC-3,4  [tool.ruff], [tool.mypy] config (single source)
├── .pre-commit-config.yaml       ← AC-5    ruff lint+format hooks
├── requirements.lock + pins      ← AC-6    pip-compile output; remoteagent-core pinned in consumers
├── Makefile                      ← AC-3,4,7 lint/typecheck/format targets; python>=3.10 probe
├── core/src/core/logging_config.py ← AC-8  setup_logging() + get_logger(); replaces 40 print()s
├── .env.example                  ← AC-9    LOG_LEVEL + the 4 read vars
└── CONTRIBUTING.md, ARCHITECTURE.md, .claude/CLAUDE.md ← AC-10
```

## Component-level design

### UX / Frontend components / Frontend UX
*n/a — no user-facing surface; this is dev-facing infrastructure.*

### Backend API
*n/a — no endpoints. The "interface" is the Makefile targets and the CI workflow.*

### Database
*n/a — no persistence changes.*

### Security
- **Secrets in CI**: the workflow must run with **no real Feishu/Anthropic credentials**; the existing tests mock those boundaries, so CI sets only dummy/empty env if anything. No secrets are added to the repo or workflow. (ADR-0007)
- **Logging redaction**: the new logging layer must not log `FEISHU_APP_SECRET` or full credentials. `feishu_client` already truncates ids (`[:8]`); preserve that. STRIDE: only *Information disclosure* is relevant (logs) — addressed by redaction; others n/a (no new surface).

### Performance
*n/a — build-time tooling; no runtime hot path affected. The logging change is INFO-level and not in a tight loop.*

### Logging layer (AC-8) — the one piece of new application code

```python
# core/src/core/logging_config.py
import logging, os

def setup_logging() -> None:
    """Configure root logging once, at process startup. LOG_LEVEL (default INFO);
    unrecognized values fall back to INFO rather than raising."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

- Each module replaces `print(...)` with a module-level `logger = get_logger(__name__)` and `logger.info/debug/warning/error(...)`. Mapping of existing prefixes → level: `[Feishu]/[Session]/[Git]` status → `info`; errors / "failed"/"error" strings → `error` (with `exc_info=True` where an exception is in scope); verbose per-message traces → `debug`.
- `main` (each bot entrypoint) calls `setup_logging()` once before starting. Message **text is preserved** (only the emit mechanism changes) to keep behavior recognizable.

### CI workflow (AC-1, AC-2)
- `.github/workflows/ci.yml`, triggers `on: [push, pull_request]`.
- Job `test`: `strategy.matrix.python-version: ["3.10","3.11","3.12"]`; steps: checkout → setup-python → `make setup` → `pytest ... --cov --cov-report=term-missing --cov-fail-under=85`. Fails the run on test failure (AC-1) or coverage < 85 (AC-2).
- Job `quality` (single version 3.12): `make lint` + `make typecheck`.

### Tooling config (AC-3, AC-4, AC-5)
- **ruff** in root `pyproject.toml` `[tool.ruff]`: `line-length = 100`, `target-version = "py310"`, `lint.select = ["E","F","W","I"]`. Provides both lint and format.
- **mypy** `[tool.mypy]`: `python_version = "3.10"`, **gradual mode** — `ignore_missing_imports = true`, no `strict`. Rationale: the existing code is partially typed (`data` untyped, `client: object`); strict mode would generate a large backlog and block AC-4. Gradual mode makes `make typecheck` green now; tightening is a future ADR/feature.
- **pre-commit** `.pre-commit-config.yaml`: `ruff` (lint, `--fix`) + `ruff-format` hooks.
- **Makefile** targets: `lint` (`ruff check core bots`), `format` (`ruff format` + `ruff check --fix`), `typecheck` (`mypy core bots`).

### Dependency pinning + lockfile (AC-6)
- Add explicit pins in each `pyproject.toml` (compatible-release floors stay as declared minimums; the **lockfile** carries exact versions). Set `core` package `version = "0.1.0"` and change consumers to depend on `remoteagent-core==0.1.0`.
- Use **pip-tools** (`pip-compile`) to generate `requirements.lock` from the three `pyproject.toml`s. `make lock` regenerates it; CI/`make setup` can install from it for reproducibility.

### Makefile Python probe (AC-7)
- Replace `python3.12` with a shell probe: try `python3.12 python3.11 python3.10 python3` in order; pick the first whose `--version` is ≥ 3.10; if none, `echo "Python 3.10+ is required" && exit 1`.

### `.env.example` sync (AC-9)
- Code reads exactly: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `SESSION_TIMEOUT_HOURS` (default 50), `STREAM_UPDATE_INTERVAL` (default 1.5). Add the new `LOG_LEVEL` (default INFO). Keep `ANTHROPIC_API_KEY` documented as optional. Remove any documented-but-unread var.

### Docs (AC-10)
- `CONTRIBUTING.md`: prerequisites, `make setup`, `make test`/`lint`/`typecheck`, branch+PR flow, where ADRs/SDLC docs live.
- `ARCHITECTURE.md`: monorepo layout, Feishu→SDK data flow (lifted from README + the modules), pointer to `docs/adrs/`.
- `.claude/CLAUDE.md`: project context for Claude Code — what the repo is, layout, conventions (logging, tests), the SDLC flow, links to ADRs.

## Trade-offs considered

- Chose **mypy in gradual mode** over **strict mode** because the existing code is only partially typed and strict would block AC-4 behind a large typing backlog. Cost: type coverage is shallow initially; real type bugs may slip until a later tightening pass.
- Chose **pip-tools (`pip-compile`)** over **uv** or **Poetry** because the project already uses plain pip + `pyproject.toml` (ADR-0001) and pip-tools is the least disruptive lockfile layer. Cost: an extra `make lock` step; no automatic resolver caching like uv.
- Chose a **single combined CI workflow** (test matrix + quality job) over separate workflows because the repo is small and one file is easier to reason about. Cost: less granular re-run control.
- Chose to **preserve existing log message text** when swapping `print()`→`logger` over rewriting messages because it minimizes behavior surprise and keeps the diff reviewable. Cost: message wording isn't re-examined for quality in this pass.

## Cross-cutting concerns

- **Failure modes / blast radius**: tooling/docs only; worst case a misconfigured CI gate blocks merges (fixable in-repo). Logging change could alter output destination — mitigated by preserving text and defaulting INFO.
- **Cross-team consumers**: none.
- **Rollout plan**: direct (no feature flag). Lands on the `refactor` branch for review before merge to `main`.
- **Backwards compatibility**: `LOG_LEVEL` is new and optional (defaults INFO); all other env vars unchanged. No CLI/command behavior change.
- **Operational impact**: operators may notice log format change (timestamps/levels) — documented in CONTRIBUTING/`.env.example`.
- **Cost impact**: CI minutes (3-version matrix) — modest.
- **Capacity / scale**: n/a.

## Open questions

- None blocking. Coverage floor (85%) and tools (ruff+mypy) are settled per spec + this design.

## ADRs referenced or created

- ADR-0001, ADR-0002, ADR-0007, ADR-0008 (referenced). No new ADR required.

## Links

- Spec: `docs/sdlc/specs/platform/hardening.md`
- Plan (filled in by Planner): `docs/sdlc/plans/platform/hardening.md`
- Test report (filled in by Tester): `docs/sdlc/test-reports/platform/hardening.md`
