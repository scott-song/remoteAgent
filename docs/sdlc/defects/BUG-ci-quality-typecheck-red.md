# Defect: BUG-ci-quality-typecheck-red — CI quality job red on main since the E2E harness landed

> Owner: ssong@aaxis.io · Status: fixed · Last updated: 2026-08-17

## Identification

- **ID**: BUG-ci-quality-typecheck-red
- **Severity**: major (CI gate red on main for six weeks; masks any new typecheck regression)
- **Reporter**: ssong@aaxis.io (surfaced while reviewing PR #1's checks)
- **Reported on**: 2026-08-17
- **Affected feature**: platform/hardening — CI quality gate
- **Related AC**: platform/hardening **AC-4** ("Type-check passes via a single command")

## Repro steps

1. Run `make typecheck` on main (any commit since `ffd6a39`, 2026-07-01).
2. Observed: mypy fails with 2 errors in `bots/coder/tools/harness.py:249,257`; the CI `quality` job has been red on every push since (last green run: `adr(0009)`, 2026-07-01).

**Environment**: main @ 8816e11; mypy per `make typecheck`.

## Expected vs actual

- **Expected** (AC-4): `make typecheck` exits 0.
- **Actual**: `harness.py:249` — `enter_context` receives `object` (the heterogeneous `patches` list literal is inferred as `list[object]`); `harness.py:257` — `method-assign`: lambda assigned over the bot's `_schedule` method.

## Validation

- **Validation verdict**: reproduced
- **Validated on**: 2026-08-17 · **Environment**: main @ 8816e11
- **Compared against**: platform/hardening AC-4 — the gate must pass; the failing state directly contradicts it.
- **Notes**: introduced by `ffd6a39` (test(coder): add local E2E harness); confirmed pre-existing relative to PR #1 by diffing (`git diff a47fcf2^ a47fcf2 -- harness.py` empty).

## Diagnosis

- **Root cause**: `ffd6a39` landed while the quality job was already failing on the same push, so the type errors were merged red-on-red and never noticed — the test jobs stayed green, and GitHub's failure signals (commit ❌, push-author email) were easy to miss.
- **Why existing tests didn't catch it**: mypy IS the test and it did catch it — the gap is process: nothing blocked a push/merge with a red quality job (no branch protection requiring checks).

### Root-cause category

- [x] **Implementation bug** — two typing defects in harness.py.
- [x] **Convention / preference gap (process)** — red CI on main does not block merges; see Prevention.

## Fix

- **Tasks** added to plan: none (tracked by this record)
- **Bug-proof test**: the CI `quality` job / `make typecheck` itself — failing before (every run since 2026-07-01), passing after. No pytest-level duplicate added: shelling out to mypy from a test would duplicate the existing CI gate.
- **Solution**: annotate the heterogeneous patch list as `list[Any]` so `enter_context` accepts its elements, and monkeypatch `_schedule` via a named function + `setattr` (the supported way to replace a method on an instance) instead of lambda-assignment. No behavior change — the harness's blocking-schedule semantics are identical.
- **Files touched**: `bots/coder/tools/harness.py`

## Propagation (per root-cause category)

- [x] All edited artifacts back to `Status: approved` — no artifacts edited
- [ ] E2E tests reconciled by `role-tester` — n/a (typing-only, no behavioral AC changed)

## Resolution

- **Resolved on**: 2026-08-17
- **Verified by**: `make typecheck` → "Success: no issues found" (was: 2 errors)
- **Regression run**: full suite (`make test`) + `make lint` — green; harness smoke (`--mock-claude`) run to confirm no behavior change
- **Review + test**: typing-only fix, two lines of mechanical change — reviewed inline, no subagent review dispatched
- **Deployed in**: <filled at merge>

## Prevention (feeds the defect retrospective)

- **What would have caught / prevented this earlier**: branch protection on main requiring the `quality` and `test` checks — the red job would have blocked `ffd6a39`'s merge instead of festering.
- **Suggested improvement**: enable GitHub branch protection (require status checks `quality`, `test (3.10-3.12)` before merge). · **Layer**: project (repo settings; note in docs)
- **Recurrence**: first time for this class (red-gate-ignored); the un-awaited-coroutine class from BUG-stop-never-interrupts would also be caught by a stricter mypy/ruff config — same prevention theme.

## Links

- Introduced by: `ffd6a39` · Surfaced during: PR #1 checks review
