# Spec: platform/hardening

> Owner: BA · Module: platform · Status: approved · Last updated: 2026-06-12

> **Module** `platform` is a registered row in `docs/sdlc/modules.md`. This spec and every downstream artifact live under `docs/sdlc/<stage>/platform/hardening.md`.

## Problem

Remote Agent is well-architected but undermaintained: there is no CI, so nothing stops a pull request from merging with failing tests or eroding coverage; there is no automated lint / type-check / formatting; dependency versions are unpinned so installs are not reproducible; the build hardcodes one Python interpreter; operational output uses `print()` rather than configurable logging; `.env.example` omits variables the code reads; and there is no contributor or architecture documentation. Today a new contributor cannot reliably set the project up, and a regression can land unnoticed — *because today the project has no automated quality gate or onboarding path.*

## Users & context

- **Primary user**: the Remote Agent maintainers / dev team (the "user" of this scaffold-style feature).
- **Secondary users**: new contributors onboarding to the repo; the CI system acting on pull requests.
- **When this happens**: on every pull request and push (CI), during local development (lint/type/test/run), and at first-time setup (onboarding).
- **Where this happens**: the GitHub repository, GitHub Actions CI, and local developer machines.

## Goals

- Every pull request is gated by an automated check that runs the test suite on all supported Python versions (binary: gate exists and blocks red PRs).
- `make lint`, `make typecheck`, and `make test` each exit 0 on the default branch.
- A fresh environment can be reproduced from a committed lockfile (binary: lockfile exists and pins exact versions).
- Zero bare `print()` calls remain for operational logging in `core/` and `bots/coder/`.
- 100% of environment variables the code reads are documented in `.env.example`.
- A new contributor can go from clone to running tests using only `CONTRIBUTING.md`.

## Non-goals

- **Splitting `main.py`** or any other code-structure refactor — that is Phase 3 (`agent-runtime`/`messaging`).
- **Any behavior change to messaging or sessions** — this feature is build/tooling/docs only; runtime behavior is preserved.
- **OS-level sandboxing or a secrets manager** — explicitly deferred by ADR-0006 / ADR-0007 revisit triggers.
- **Fleshing out the HR bot** — out of scope; its stub status is unchanged.
- **Multi-host / multi-process support** — deferred by ADR-0005.

## Acceptance criteria

> Format is Given / When / Then. Each AC is independently testable. "The code" / "the suite" refer to the existing test suite under `core/tests`, `bots/coder/tests`, `bots/hr/tests`.

### AC-1: CI runs the suite on the supported Python matrix

- **Given** a pull request or push to the repository
- **When** CI runs
- **Then** the test suite executes on Python 3.10, 3.11, and 3.12, and the workflow run **fails** if any test fails on any version.

### AC-2: CI enforces a coverage floor

- **Given** the test suite running under CI with coverage measurement enabled
- **When** total line coverage is computed
- **Then** the workflow run **fails** if total line coverage is below **85%**, and **passes** at or above 85%.

### AC-3: Lint passes via a single command

- **Given** a clean checkout with the dev environment installed
- **When** a developer runs `make lint`
- **Then** the linter checks `core/` and `bots/` and exits 0 when there are no violations, and exits non-zero (naming the offending file:line) when there are.

### AC-4: Type-check passes via a single command

- **Given** a clean checkout with the dev environment installed
- **When** a developer runs `make typecheck`
- **Then** the type checker checks `core/` and `bots/` and exits 0, and exits non-zero (naming the offending file:line) on a type error.

### AC-5: A pre-commit hook enforces lint + format before commit

- **Given** the pre-commit hook is installed
- **When** a developer attempts a commit that contains lint or formatting violations
- **Then** the commit is blocked and the violations are reported; **and** a commit with no violations proceeds.

### AC-6: Dependencies are reproducible and the internal package is pinned

- **Given** a fresh virtual environment
- **When** a developer installs from the committed lockfile
- **Then** the exact pinned dependency versions are installed; **and** each consumer package (`bots/coder`, `bots/hr`) references `remoteagent-core` by a pinned version (not an unconstrained name).

### AC-7: Setup works on any Python ≥ 3.10 and fails clearly otherwise

- **Given** a machine whose available `python3` is ≥ 3.10
- **When** the developer runs `make setup`
- **Then** the virtualenv is created with that interpreter (no hardcoded `python3.12`) and setup completes successfully.
- **Given** a machine with no `python3` ≥ 3.10 available
- **When** the developer runs `make setup`
- **Then** setup fails with a message naming the minimum required version *"Python 3.10+ is required"*.

### AC-8: Operational output goes through configurable structured logging

- **Given** the bot is running
- **When** it emits operational messages (startup, Feishu events, git sync, session lifecycle, errors)
- **Then** the messages are emitted via the stdlib `logging` module, and the log level is controlled by the `LOG_LEVEL` environment variable defaulting to `INFO`; **and** no bare `print()` calls remain for operational logging in `core/` and `bots/coder/`.
- **Given** `LOG_LEVEL` is set to an unrecognized value
- **When** the bot starts
- **Then** it falls back to `INFO` rather than crashing.

### AC-9: `.env.example` documents every variable the code reads

- **Given** the set of environment variables the code reads at runtime
- **When** `.env.example` is compared against that set
- **Then** every read variable appears in `.env.example` with a placeholder or default, and no documented variable is one the code never reads.

### AC-10: Developer documentation exists

- **Given** a new contributor with a fresh clone
- **When** they look for setup and contribution guidance
- **Then** `CONTRIBUTING.md` (setup, how to run tests/lint/typecheck, PR flow), `ARCHITECTURE.md` (monorepo layout, Feishu→SDK data flow, link to `docs/adrs/`), and `.claude/CLAUDE.md` (project context for Claude Code) all exist and are non-empty.

## Out of scope (deferred)

- Raising coverage above its current level — this feature only *gates* coverage, it does not add tests.
- Log rotation / structured JSON log shipping — `LOG_LEVEL` + stdlib logging only; richer observability is deferred until ADR-worthy.
- CI deployment / release automation — testing/lint gate only.

## Open questions

- **Coverage floor value** — drafted at **85%** (current suite is ~93% per `TESTING_REPORT.md`; 85% leaves headroom for flaky async paths). *Recommendation: 85%.* Resolver: maintainers (Scott) — confirm or adjust at spec approval.
- **Lint/format + type-check tool choice** — spec is tool-agnostic (says "linter"/"type checker"); ADR-context and the plan assume **ruff** (lint+format) and **mypy**. Final tool selection is an Architect/design decision, not a spec constraint. Resolver: Architect at `/sdlc-design`.

## Links

- Related: `docs/sdlc/REFACTOR-PLAN.md` §5 Phase 2; ADR-0001, ADR-0002, ADR-0007, ADR-0008.
- Design doc (filled in by Architect): `docs/sdlc/designs/platform/hardening.md`
