# ADR-0008: Use pytest with a CI coverage gate as the test strategy

**Status:** Proposed
**Supersedes:** —
**Superseded by:** —

## Context

The repo has a substantial pytest suite (~231 tests, ~1.7:1 test-to-source ratio, ~93% claimed coverage) run via `make test` across `core/tests`, `bots/coder/tests`, and `bots/hr/tests`. There is **no CI**, so nothing enforces that tests pass or that coverage holds on changes — the central maintainability gap for a long-lived project. Per the SDLC's unit-integration-collapse rule, pytest covers both unit and integration layers; the bot is a backend process with **no browser/UI surface**, so there is no separate E2E framework. Builds on ADR-0001 (monorepo test layout) and ADR-0002 (version matrix). A `platform`/test-strategy decision.

## Decision

We will standardize on **pytest** as the single test framework for unit and integration tests (collapsed — pytest covers both layers), and add a **CI coverage gate**: GitHub Actions runs the suite on the 3.10–3.12 matrix (per ADR-0002) with `pytest-cov`, failing the build on any test failure or a coverage drop below an agreed threshold. No separate E2E framework (no UI surface).

## Alternatives considered

- **unittest (stdlib)** — attractive: no dependency. Rejected: the suite is already pytest; pytest's fixtures/parametrize/plugins are materially better and already relied upon.
- **pytest for unit + a separate integration/E2E framework** — attractive: a layered test pyramid. Rejected: the bot has no browser/HTTP-UI surface to E2E; pytest already exercises integration paths (async, mocked Feishu/SDK boundaries); a second framework adds tooling for no coverage gain (unit-integration-collapse).
- **Keep pytest but no CI gate (status quo)** — attractive: zero setup. Rejected: nothing prevents a PR from merging red or eroding coverage; the absence of a gate is exactly the gap this ADR closes.

## Consequences

**Easier (positive consequences):**
- One familiar runner; the existing suite needs no migration.
- The CI gate makes test health a merge precondition and surfaces coverage trends; the matrix proves cross-version support.

**Harder (costs / negative consequences):**
- CI minutes cost (3-version matrix).
- A coverage threshold can cause friction on flaky / hard-to-test async paths.
- Mocking the Feishu / Claude SDK boundaries is ongoing effort.

**To revisit when:**
- A user-facing UI is added (would need an E2E ADR), OR
- test runtime grows enough to require parallelization/sharding, OR
- the team wants a different runner.

## References

- `TESTING_REPORT.md`; `Makefile` test targets; `core/tests`, `bots/coder/tests`, `bots/hr/tests`.
- Related: ADR-0001 (layout), ADR-0002 (CI matrix).
