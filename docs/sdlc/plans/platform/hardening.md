# Implementation plan: platform/hardening

> Owner: Planner → Dev (live updates) · Status: approved · Last updated: 2026-06-12
> Spec: `docs/sdlc/specs/platform/hardening.md` · Spec version targeted: 2026-06-12 (commit `249915b`)
> Design: `docs/sdlc/designs/platform/hardening.md` · Design version targeted: 2026-06-12 (commit `e727b38`)

## Approach

Nine independently-committable tasks, ordered so each is testable on its own. Foundation first (dep pins, Makefile, tooling config), then the largest code change (logging), then make lint/type green, then the remaining wiring (pre-commit, env, CI) and docs. No runtime behavior changes — only build/tooling/docs and the `print()`→`logging` swap (message text preserved). Lands on the `refactor` branch; CI proves AC-1/AC-2 once pushed.

## Tasks

> `[ ]` pending · `[~]` in progress · `[x]` done · `[!]` blocked. `[x]` is immutable.

### T1 — Pin dependencies, version core, generate lockfile

- **Status**: `[x]`
- **Files**: `core/pyproject.toml`, `bots/coder/pyproject.toml`, `bots/hr/pyproject.toml`, `requirements.lock`
- **Design**: § Dependency pinning + lockfile
- **Covers**: AC-6
- **Risk**: medium — pinning must not break the existing test suite; choose versions matching what's currently resolvable.
- **Notes**: set `core` `version = "0.1.0"`; consumers depend on `remoteagent-core==0.1.0`. Generate `requirements.lock` via pip-compile (or `pip freeze` of a clean install if pip-tools unavailable).

### T2 — Makefile: Python ≥3.10 probe + quality targets

- **Status**: `[x]`
- **Files**: `Makefile`
- **Design**: § Makefile Python probe; § Tooling config
- **Covers**: AC-7 (probe); infrastructure for AC-3/AC-4 (`lint`/`typecheck`/`format`/`lock` targets)
- **Risk**: low

### T3 — ruff + mypy config

- **Status**: `[x]`
- **Files**: `pyproject.toml` (root — add `[tool.ruff]`, `[tool.mypy]`)
- **Design**: § Tooling config
- **Covers**: AC-3 (config), AC-4 (config) — *completed by T5*
- **Risk**: low — mypy in gradual mode (`ignore_missing_imports`, no strict).

### T4 — Logging layer + replace print()

- **Status**: `[x]`
- **Files**: `core/src/core/logging_config.py` (new), `core/src/core/feishu_client.py`, `core/src/core/session_manager.py`, `bots/coder/src/coder/main.py`, `bots/coder/src/coder/project_registry.py`, bot entrypoint(s) call `setup_logging()`
- **Design**: § Logging layer (AC-8)
- **Covers**: AC-8
- **Risk**: medium — 40 call sites; preserve message text, map prefixes to levels, keep id truncation (no secret leakage). Must not change control flow.

### T5 — Make lint + typecheck + format green

- **Status**: `[x]`
- **Files**: across `core/`, `bots/` (auto-fixes + residual manual fixes)
- **Design**: § Tooling config
- **Covers**: AC-3 (completion), AC-4 (completion)
- **Risk**: medium — `ruff format` + `ruff check --fix` then resolve residual lint; run `mypy` and reach exit 0 (gradual config). Must keep tests passing.

### T6 — pre-commit hooks

- **Status**: `[x]`
- **Files**: `.pre-commit-config.yaml`
- **Design**: § Tooling config
- **Covers**: AC-5
- **Risk**: low

### T7 — Sync .env.example (+ LOG_LEVEL)

- **Status**: `[x]`
- **Files**: `.env.example`
- **Design**: § `.env.example` sync (AC-9)
- **Covers**: AC-9
- **Risk**: low — vars read: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `SESSION_TIMEOUT_HOURS`, `STREAM_UPDATE_INTERVAL`, + new `LOG_LEVEL`; keep `ANTHROPIC_API_KEY` optional.

### T8 — CI workflow

- **Status**: `[x]`
- **Files**: `.github/workflows/ci.yml`
- **Design**: § CI workflow (AC-1, AC-2)
- **Covers**: AC-1, AC-2
- **Risk**: medium — matrix 3.10/3.11/3.12; `--cov-fail-under=85`; must install without real secrets (tests mock boundaries).

### T9 — Developer docs

- **Status**: `[x]`
- **Files**: `CONTRIBUTING.md`, `ARCHITECTURE.md`, `.claude/CLAUDE.md`
- **Design**: § Docs (AC-10)
- **Covers**: AC-10
- **Risk**: low

## Risk register

- **Cannot run tooling/tests locally without an installed venv + network** — likelihood medium. If `make setup` / `pip install` cannot reach the index in this environment, T5 and the Tester stage can't prove green locally; CI (T8) proves it on push instead. Owner: Dev — surface to user as a decision if hit.
- **mypy gradual still surfaces real errors** — if T5 finds genuine type errors (not just missing stubs), fixing them must not alter runtime behavior; if a fix is risky, narrow with a targeted `# type: ignore` + note rather than changing logic.

## Out-of-band changes

None — design and spec cover the scope.

## Amendments

*(none yet)*
