# Test review: platform/hardening

> Reviewer: test-reviewer subagent · Date: 2026-06-12
> Test report reviewed: docs/sdlc/test-reports/platform/hardening.md (run 2026-06-12, code SHA `77c566f`)
> Current HEAD: `37dc407` (adds report + review artifacts only, on top of verified code `77c566f`)
> Verdict: **PASS**

## Summary

The `passed` (10/10) verdict is honest. This is a build/tooling/docs feature with no integration/E2E layer; all ACs are verified by tooling execution and recorded in the *Non-functional ACs* table — the correct vehicle, not "n/a — verified" hand-waving. I independently re-ran every claim that doesn't require pytest (Makefile probe, print scan, env-var diff, lockfile pins, doc existence) and all held. The two claims I could not re-run locally (pytest is not installed here; only Python 3.8.8 and 3.12 are available) — AC-2's directional coverage gate and AC-1's "284 passed" — are strongly corroborated by independent static evidence: the suite contains exactly 284 test functions, coverage is `source`-scoped to the three `src` trees, and both dev and implementation-reviewer reported consistent numbers (87.54% / 87.48%). The feature is shippable.

## Freshness & precondition checks

- **Approval gate**: spec (`approved`), design (`approved`), plan (`approved`). All clear.
- **Freshness**: report anchors spec `249915b`, design `35a3ae9`, plan `90f8c84` (branch). `git log` confirms these are the current committed SHAs — no drift. Code under test `77c566f` exists; current HEAD `37dc407` only layers the report/review docs on top, so the audited code is intact.
- The audit prompt cited code SHA `37dc407` while the report cites `77c566f`; this is not drift — `37dc407` is the report commit and contains no source changes over `77c566f`.

## A. Verdict honesty

| AC | Tester verdict | Evidence honest? | Notes |
|----|----------------|------------------|-------|
| AC-1 | ✅ pass | ✅ | Re-verified `ci.yml` matrix `["3.10","3.11","3.12"]`, `fail-fast: false`, pytest+gate step. Suite = 284 test fns (matches "284 passed"). Full matrix runs in Actions only (no local 3.10/3.11) — honestly disclosed in *Coverage notes*. |
| AC-2 | ✅ pass | ✅ | Could not re-run pytest (not installed). Corroborated: `--cov-fail-under=85` present in `ci.yml:30`; coverage `source`-scoped (`pyproject.toml:22`); 87.54%/87.48% reported by two independent prior runs. Directional (99% fails / 85% passes) claim is plausible and consistent. |
| AC-3 | ✅ pass | ✅ | `Makefile:46-47` `ruff check core bots`; "All checks passed!" is the standard ruff success line. Tool execution by tester accepted. |
| AC-4 | ✅ pass | ✅ | `Makefile:55-56` `mypy core bots`; "no issues found in 17 source files" is the standard mypy success line. |
| AC-5 | ✅ pass | ✅ | `.pre-commit-config.yaml` has ruff + ruff-format; `Makefile:29` runs `pre-commit install`. Live block-on-commit not staged — same ruff checker as AC-3; disclosed. See B/F notes. |
| AC-6 | ✅ pass | ✅ | Re-verified: 67/67 lines are `==` exact pins, zero loose specifiers; both consumers pin `remoteagent-core==0.1.0`. Lockfile now consumed (`Makefile:27`, `ci.yml:43`). |
| AC-7 | ✅ pass | ✅ | **Re-ran the probe**: resolves to `python3.12`, correctly skips system `python3` (3.8.8). **Re-ran negative path**: `make setup PYTHON=` prints exactly "Python 3.10+ is required" and exits non-zero. Both directions verified. |
| AC-8 | ✅ pass | ✅ | **Re-ran the scan**: zero `print(`/`print_exc` in `core/src` and `bots/coder/src`; zero `import traceback` in `core/src`. HR bot retains prints (correctly out of scope per spec non-goal). Fallback covered by a genuine (non-vacuous) test — see D. |
| AC-9 | ✅ pass | ✅ | **Re-ran the diff**: code reads `FEISHU_APP_ID/SECRET`, `SESSION_TIMEOUT_HOURS`, `STREAM_UPDATE_INTERVAL`, `LOG_LEVEL` — all five documented. `ANTHROPIC_API_KEY` documented but not read by our code; justified (read by the `claude_agent_sdk` runtime from env) — minor strictness note, not a finding. |
| AC-10 | ✅ pass | ✅ | Re-verified existence + content: `CONTRIBUTING.md` (48L, setup/commands/PR flow), `ARCHITECTURE.md` (72L, layout/data-flow/ADR link), `.claude/CLAUDE.md` (36L, project context). All non-empty with the spec's required topics. |

No AC is silently skipped, no `⏸ blocked` used to dodge a hard AC, and no multi-observable AC was passed on partial evidence (AC-2, AC-7, AC-8 each exercise both their directions/clauses).

## B. Coverage truth

- All 10 spec ACs appear in the test report and in the traceability matrix. None silently skipped.
- The matrix's strict-convention grep correctly shows no `int_AC_*`/`e2e_AC_*` tests (status `❌` per strict convention) and its scope note correctly explains why that is **expected, not a defect** for an infra feature. This matches disk — the 284-test suite uses conventional names and is invisible to the strict matrix by contract. No false coverage claim.
- The matrix is stamped before the test run ("Test report: none yet"), i.e. slightly stale relative to the report. Per review policy this is process noise, not a finding — its substance (AC→task mapping, strict-grep result) is accurate and matches the current tree, so I did not regenerate it.
- The report's *Non-functional ACs* table is the correct vehicle for these tooling-execution verifications and every row carries a method + evidence.

## C. Test-code quality

No `e2e_AC_*` / `int_AC_*` tests were authored (expected — infra feature). The one test file the tester relies on for AC-8 is `core/tests/test_logging_config.py`:

| Test | Naming | AC ref | Locator/setup | Assertion quality | Notes |
|------|--------|--------|---------------|-------------------|-------|
| `test_default_level_is_info` | n/a convention (unit) | implicit AC-8 | `monkeypatch.delenv` — clean per-test env | asserts root level == INFO | Good. |
| `test_explicit_level_applied` | unit | AC-8 | `monkeypatch.setenv DEBUG` | asserts level == DEBUG | Good. |
| `test_lowercase_level_applied` | unit | AC-8 | `monkeypatch.setenv warning` | asserts WARNING (proves `.upper()`) | Good edge. |
| `test_invalid_level_falls_back_to_info` | unit | AC-8 clause 2 | `monkeypatch.setenv NOT_A_LEVEL` | asserts INFO, no raise | The load-bearing test — see D. |
| `test_get_logger_returns_named_logger` | unit | AC-8 | none | asserts type + name | Good. |

Quality is sound: per-test env isolation via `monkeypatch`, no `sleep`/arbitrary waits, no tautologies, assertions target the AC's observable (the configured level), not adjacent state.

## D. Test-code validity

- **`test_invalid_level_falls_back_to_info` is genuinely valid (not vacuous).** Mutation check: `setup_logging()` calls `logging.getLogger().setLevel(level)` **unconditionally** (`logging_config.py:34`), so the `_configured` idempotency flag does not mask per-test level changes — each test re-applies. If a regression removed the `isinstance(level, int)` guard (`:30`), `getattr(logging, "NOT_A_LEVEL", None)` returns `None`, `setLevel(None)` raises, and this test fails. The test would catch the real regression. Confirms the implementation-reviewer's C-3 resolution.
- AC-8's primary clause ("no bare print in core/+bots/coder") is validated by a repo-wide grep, which I re-ran with a zero result — the strongest possible evidence for a "no occurrences" AC.
- AC-7's negative path is validated by actually invoking `make setup PYTHON=` and observing the exact required message — a real behavioral check, not a config read.

## E. Defect honesty

No defects filed. None warranted — every AC passed and I found no honesty or severity issue that should have produced one.

## F. Manual / n/a audit

No AC is recorded as a bare "n/a — verified" without method. Every *Non-functional* row names a concrete method (CI config inspection, `make` target run, grep scan, lockfile/pyproject inspection, file existence) **and** cites evidence. Two honestly-disclosed not-staged items, both acceptable for this feature type:

- **AC-1 full 3.10/3.11 matrix** runs only in GitHub Actions (no local interpreters). Proven by config; the gate runs on every push/PR. Acceptable — local execution of three interpreters is not a reasonable Tester obligation.
- **AC-5 live block-on-commit** not staged. The hook invokes the same ruff checker proven to flag violations in AC-3, and `pre-commit install` is wired in `make setup`. Residual risk is negligible. Acceptable.

Neither rises to NEEDS CHANGES: both are disclosed in *Coverage notes*, both have compensating evidence, and neither leaves an AC unverified in substance.

## Verdict

**PASS.** Every AC verdict is honest and backed by either a re-runnable check I independently confirmed or strongly-corroborated tooling output. The lone supporting test (`test_logging_config.py`) is well-formed and would catch the regression it guards. No defects were under-classified (none exist). The traceability matrix makes no false coverage claim. The single coverage number I could not re-execute (pytest unavailable in this audit environment) is consistent across three independent observers and adjacent static facts.

**The feature is shippable.** Recommend the user mark `platform/hardening` done. The standing release gate is the CI workflow itself (`.github/workflows/ci.yml`): once merged, the `test` matrix (3.10–3.12 + 85% coverage floor) and the `quality` job (ruff + mypy + lockfile reproducibility) become the enforced gate this feature was built to establish.

## What the tester should do next

Nothing required. Optional, non-blocking polish for a future pass:

1. Regenerate the traceability matrix (`/sdlc-trace platform/hardening`) so its header reflects the completed test run rather than "testing stage not run" — cosmetic only.
2. If you ever want AC-5's live behavior locked against regression, a tiny throwaway test that stages a deliberately-malformed file and asserts `pre-commit run --files` exits non-zero would close the only un-staged behavioral gap. Not needed for ship.
