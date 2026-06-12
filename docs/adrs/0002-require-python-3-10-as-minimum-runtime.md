# ADR-0002: Require Python 3.10 as the minimum runtime

**Status:** Accepted (2026-06-12)
**Supersedes:** —
**Superseded by:** —

## Context

The codebase carries three conflicting Python-version signals: `README.md:25` says "3.10+", `Makefile:21` hardcodes `python3.12`, and an old project note said 3.8. The source already uses PEP 604 union syntax (`X | None`) and PEP 585 builtin generics (`dict[str, str]`), which require **≥ 3.10** — so 3.8/3.9 are not viable without rewriting type hints. We need one committed floor to drive `requires-python`, the CI test matrix, and the Makefile. The user confirmed the floor (2026-06-12). Builds on the monorepo packaging in ADR-0001 (the floor applies uniformly to every package).

## Decision

We will require **Python ≥ 3.10** as the minimum supported runtime: `requires-python = ">=3.10"` in every `pyproject.toml`; CI tests against **3.10, 3.11, and 3.12**; the Makefile probes for a `python3 >= 3.10` interpreter instead of hardcoding `python3.12`.

## Alternatives considered

- **Floor at 3.12** (match Makefile + dev box) — attractive: single-version simplicity, access to 3.11/3.12-only features. Rejected: excludes 3.10/3.11 users for no concrete need; the code uses no 3.11+ feature today.
- **Floor at 3.11** — attractive: 3.11 perf + exception groups, one version below the dev env. Rejected: no current dependency on 3.11 features; a 3.10 floor costs nothing extra and widens reach.
- **Stay ambiguous / claim 3.8** — rejected: factually impossible given existing type-hint syntax; the source would not import on 3.8/3.9.

## Consequences

**Easier (positive consequences):**
- One authoritative floor ends the README / Makefile / note drift.
- Broadest install compatibility; the CI matrix proves portability across 3.10–3.12.

**Harder (costs / negative consequences):**
- Cannot use 3.11/3.12-only syntax without a future ADR raising the floor.
- A 3-version CI matrix costs slightly more CI time.

**To revisit when:**
- A required dependency drops 3.10 support, OR
- we need a 3.11+/3.12+ language feature, OR
- Python 3.10 reaches end-of-life (Oct 2026) and we choose to drop it.

## References

- `README.md:25`; `Makefile:21`; PEP 604 / PEP 585.
- Verified: source uses `X | None` and lowercase `dict[...]` generics (≥3.10).
- Related: ADR-0001 (packaging), ADR-0008 (CI matrix).
