# ADR-0001: Use a monorepo with pip editable installs

**Status:** Proposed
**Supersedes:** —
**Superseded by:** —

## Context

Remote Agent began as a single `bot/` package and was refactored (commit `2849dc3`) into multiple Python packages: a shared `core` library and one package per bot (`bots/coder`, `bots/hr`). The bots depend on `core` for the Feishu client, session manager, and streaming code, and they evolve together. The team is small (one operator + a small team). We need an explicit record of repository structure because it constrains packaging, CI, dependency flow, and access control. No `docs/preferences/tech-preferences.md` existed when this was authored; this decision sets precedent. Python lacks the JS monorepo-tool ecosystem (Nx/Turborepo), so the relevant axes are repo layout and how packages reference each other.

## Decision

We will use a single Git **monorepo** containing multiple Python packages — a shared `core` library plus one package per bot under `bots/`.

Second decision clause (tooling within the paradigm): packages are wired with **pip editable installs** (`pip install -e core -e bots/coder …`) into one shared virtualenv, declared via per-package `pyproject.toml`. There is **no** separate monorepo orchestrator (no Nx/Bazel/Pants).

## Alternatives considered

- **Polyrepo** (one repo per bot + `core` published to a private index) — attractive: hard ownership boundaries, independent release cadence. Rejected: tiny team; `core` and the bots churn together, so every `core` change would force a publish + version-bump dance across repos — months of coordination for isolation we don't need.
- **Single flat package** (the pre-refactor `bot/`) — attractive: simplest, no install wiring. Rejected: already outgrown; shared logic was being copied toward would-be second bots; the refactor exists precisely to extract `core`.
- **Monorepo with a build orchestrator** (Pants/Bazel for Python) — attractive: caching, affected-graph CI. Rejected: large operational overhead for a ~2k-line codebase; orchestrators pay off at 100+ packages, not 3.

## Consequences

**Easier (positive consequences):**
- Atomic cross-package refactors in one commit; `core` and its consumers ship together.
- One virtualenv, one `make setup`; AI agents and humans see the whole graph.

**Harder (costs / negative consequences):**
- No independent versioning of `core` — a breaking change must update all consumers in the same PR.
- `remoteagent-core` is referenced unpinned by consumers (a packaging follow-up under the `platform` module).
- Cannot grant repository access per-bot.

**To revisit when:**
- The team exceeds ~30 engineers, OR
- a bot needs an independent release cadence / hard access boundary, OR
- a third party needs to consume `core` as a published library.

## References

- Refactor commit `2849dc3` (monorepo split).
- `playbooks/architect/repo-strategy.md` — monorepo-by-default 2026 consensus.
- Related: ADR-0002 (runtime), ADR-0008 (test strategy / CI).
