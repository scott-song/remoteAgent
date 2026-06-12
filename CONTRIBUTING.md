# Contributing to Remote Agent

## Prerequisites

- **Python ≥ 3.10** (the system `python3` may be older; `make setup` finds a suitable interpreter — see [ADR-0002](docs/adrs/0002-require-python-3-10-as-minimum-runtime.md))
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (logged in)
- A [Feishu app](https://open.feishu.cn) with Bot capability + WebSocket mode (for running the bot)

## Setup

```bash
git clone https://github.com/scott-song/remoteAgent.git
cd remoteAgent
make setup          # creates .venv (Python 3.10+), installs core + bots editable, installs pre-commit
cp .env.example .env # fill in FEISHU_APP_ID / FEISHU_APP_SECRET
```

This is a **monorepo** ([ADR-0001](docs/adrs/0001-use-a-monorepo-with-pip-editable-installs.md)): one shared `core` package and per-bot packages under `bots/`, wired with editable installs into a single virtualenv.

## Everyday commands

| Command | What it does |
|---|---|
| `make run-coder` | Run the coder bot (`make run-hr` for the HR stub) |
| `make test` | Run the full pytest suite |
| `make test-core` / `test-coder` / `test-hr` | Per-package tests |
| `make lint` | ruff lint over `core/` + `bots/` |
| `make format` | ruff format + autofix |
| `make typecheck` | mypy (gradual mode) over `core/` + `bots/` |
| `make lock` | Regenerate `requirements.lock` from the current venv |

## Conventions

- **Logging, not print.** Use `from core.logging_config import get_logger` and `logger = get_logger(__name__)`. Level is controlled by `LOG_LEVEL` (default `INFO`). Do not use `print()` for operational output.
- **Tests** live in `<package>/tests/` and run under pytest (asyncio auto mode). New behavior needs a test.
- **Lint/format** is ruff; **types** are checked by mypy in gradual mode. `make lint` and `make typecheck` must pass.

## Pull request flow

1. Branch off `main`.
2. Make your change; keep `make test`, `make lint`, `make typecheck` green. The pre-commit hook runs ruff automatically.
3. Open a PR. **CI** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the suite on Python 3.10/3.11/3.12 with a coverage gate (≥85%) plus lint + type-check; all must pass to merge ([ADR-0008](docs/adrs/0008-use-pytest-with-a-ci-coverage-gate.md)).

## Where things live

- **Architecture overview**: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Architecture decisions (ADRs)**: [`docs/adrs/`](docs/adrs/)
- **SDLC working docs** (specs/designs/plans): [`docs/sdlc/`](docs/sdlc/) — this project follows the [`ai-sdlc-c1`](https://github.com/scott-song/ai-sdlc) flow for substantive features.
