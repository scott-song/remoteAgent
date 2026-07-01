# Remote Agent — project context for Claude Code

A Python bot that bridges **Feishu group chat** to the **Claude Agent SDK** ("Claude Code from anywhere"). One outbound process; no inbound server.

## Layout (monorepo)

- `core/src/core/` — shared library: `feishu_client`, `session_manager`, `stream_handler`, `logging_config`, `config`.
- `bots/coder/src/coder/` — the active bot: `main` (routing + commands), `project_registry`, `sdk_client`, `security`, `git_sync`.
- `bots/hr/` — stub/example bot.
- `docs/adrs/` — architecture decisions. `docs/sdlc/` — specs/designs/plans.

See `ARCHITECTURE.md` for the full data flow.

## Conventions (follow these when editing)

- **Python ≥ 3.10** (ADR-0002). Use `X | None` / `dict[...]` generics.
- **Logging, never `print()`** for operational output: `from core.logging_config import get_logger; logger = get_logger(__name__)`. Level via `LOG_LEVEL` (default INFO). ADR-context: `docs/sdlc/specs/platform/hardening.md` AC-8.
- **Tests**: pytest under `<package>/tests/`, asyncio auto mode. Run `make test`. New behavior needs a test; keep coverage ≥ 85% (CI gate, ADR-0008).
- **Lint/format**: ruff (`make lint`, `make format`). **Types**: mypy gradual mode (`make typecheck`). Both must stay green.
- **Editable monorepo**: import `core` as `from core.<module> import ...`; within `core`, use relative imports.

## Build / run

- Setup: `make setup` (finds Python ≥ 3.10; the system `python3` may be 3.8).
- Run: `make run-coder`. Tests: `make test`. Lock deps: `make lock`.

## Working method

Substantive features follow the **ai-sdlc-c1** flow: `/sdlc-spec → /sdlc-design → /sdlc-plan → /sdlc-build → /sdlc-review → /sdlc-test`, with artifacts under `docs/sdlc/`. Read ADRs in `docs/adrs/` before changing foundational behavior (transport, sessions, security, packaging).

## Important constraints

- Don't introduce a second chat platform or an inbound web server without an ADR (ADR-0003).
- Sessions are keyed `(user, project, chat)` (ADR-0009, which superseded ADR-0005's `(user, project)` key).
- The bash security hook is **best-effort, not a sandbox** — interpreters are allowed (ADR-0006).
- Secrets live in a gitignored `.env`; never commit secrets (ADR-0007).
