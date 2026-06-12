# Review: platform/hardening

> Reviewer: implementation-reviewer subagent · Date: 2026-06-12 · Verdict: PASS (re-review after Loop-A dev fix `77c566f`)

## Re-review (commit 77c566f) — final verdict: PASS

Loop-A dev fix verified against the prior NEEDS CHANGES findings. Upstream chain still approved and fresh (spec `249915b`, design `35a3ae9`, plan targets both). All four findings resolved:

- **C-1 (Critical, AC-8) — RESOLVED.** `core/src/core/feishu_client.py:182-183` now reads `logger.error(f"[Feishu] Error handling message: {e}", exc_info=True)`; the `traceback.print_exc()` and its local `import traceback` are gone. Repo-wide scan confirms **zero** bare `print()`/`print_exc()` calls in `core/src` or `bots/coder/src`, and no `import traceback` in `core/src`. The traceback now flows through the logging layer under LOG_LEVEL control — exactly AC-8's intent. This was the last bare print-family call in core/.
- **C-2 (AC-6) — RESOLVED / reconciliation accepted.** `Makefile:27` and the CI `quality` job (`.github/workflows/ci.yml:43`) now `pip install -r requirements.lock` ahead of the editable installs. The matrix `test` job deliberately stays on declared floors, documented in an inline comment (`ci.yml:20-22`): the lockfile is frozen on a single interpreter (3.12) while the matrix's purpose is proving 3.10–3.12 support — pinning it across the matrix would defeat that purpose. The reproducibility check lives in the single-interpreter `quality` job plus `make setup`. Defensible and acceptable.
- **C-3 (AC-8) — RESOLVED.** `core/tests/test_logging_config.py` (new, 37L) covers the fallback path (`LOG_LEVEL=NOT_A_LEVEL` → root logger stays INFO, no raise), default-to-INFO, explicit `DEBUG`, lowercase `warning`, and `get_logger` naming. Verified against the source: `setup_logging()` calls `setLevel(level)` unconditionally (`logging_config.py:34`), so the `_configured` flag does not mask per-test level changes — the tests genuinely exercise the real branch (`getattr(logging, "NOT_A_LEVEL", None)` → None → `isinstance` guard → `_DEFAULT_LEVEL`). Not vacuous. AC-8's second Given/When/Then is now protected against regression.
- **C-4 (Suggestion) — RESOLVED.** `bots/coder/src/coder/main.py:421` simplified from `except (ValueError, Exception)` to `except Exception`.

No new findings introduced by the fix diff (`558c2db..77c566f` touches only the four target files plus the new test, the review doc, and the traceability matrix). Local verification reported by dev: ruff PASS, mypy PASS, ruff format PASS, 284 tests pass, coverage 87.54% (above the 85% floor). I could not re-run pytest in the review sandbox (no pytest installed); the static read is conclusive and the reported numbers are consistent with the diff.

**Verdict: PASS.** All 10 ACs now have implementation evidence and AC-8's previously-untested fallback clause is covered. Design fidelity remains strong (no redesign, no behavior change to messaging/sessions). Ready to advance to `/sdlc-test platform/hardening` (Tester records the tooling-execution ACs — AC-1/2/3/4/5/6/7/10 — as *Non-functional, verified via tooling execution*).

---

## Original review (NEEDS CHANGES)

## Summary

Solid, faithful implementation of a build/quality/onboarding hardening pass. All 9 plan tasks are `[x]`, the upstream chain is approved and fresh (design targets spec `249915b` ✓; plan targets spec `249915b` ✓ and design `35a3ae9` ✓), and the diff matches the design's five-workstream architecture closely: CI matrix + coverage gate, ruff/mypy/pre-commit, pinned deps + lockfile, Python-version probe, the stdlib-logging layer, the `.env.example` sync, and all three docs. The `print()`→`logging` swap preserves message text and id truncation as designed, and the large `security.py`/`stream_handler.py` deltas are pure ruff-format reflows with no logic change — the non-goal of "no behavior change to messaging/sessions" is respected. Two items block a clean PASS: a residual `traceback.print_exc()` in `core/feishu_client.py` violates AC-8's "no bare print() in core/", and AC-8's LOG_LEVEL-fallback clause has no test. Everything else passes.

## A. AC coverage

> The strict `int_AC_*`/`e2e_AC_*` convention is unused here (expected for an infra feature — most ACs are tooling-execution checks the Tester will record as *Non-functional*). "Test?" below means *any* unit test gives meaningful evidence, not convention compliance. See `docs/sdlc/traceability/platform/hardening.md`.

| AC | Implemented? | Test evidence? | Evidence |
|----|--------------|----------------|----------|
| AC-1 CI matrix 3.10–3.12, fails on test failure | ✅ | n/a (CI exec) | `.github/workflows/ci.yml:10-27` — `matrix.python-version: ["3.10","3.11","3.12"]`, `fail-fast: false`, pytest step |
| AC-2 coverage floor 85% | ✅ | n/a (CI exec) | `.github/workflows/ci.yml:26-27` — `--cov-fail-under=85` |
| AC-3 `make lint` | ✅ | n/a (tool exec) | `Makefile:45-46` `ruff check core bots`; root config `pyproject.toml:5-11` |
| AC-4 `make typecheck` | ✅ | n/a (tool exec) | `Makefile:54-55` `mypy core bots`; `pyproject.toml:13-19` gradual mode |
| AC-5 pre-commit blocks violations | ✅ | n/a (tool exec) | `.pre-commit-config.yaml:3-9` ruff + ruff-format; `Makefile:28` installs hook |
| AC-6 reproducible deps + core pinned | ⚠️ | n/a | `requirements.lock` (67 exact pins); consumers pin `remoteagent-core==0.1.0` (`bots/coder/pyproject.toml:7`, `bots/hr/pyproject.toml:7`). **But nothing installs *from* the lockfile** — see C-2 |
| AC-7 Python ≥3.10 probe + clear failure | ✅ | n/a (tool exec) | `Makefile:4` probe loop; `Makefile:24` `… \|\| { echo "Python 3.10+ is required"; exit 1; }` |
| AC-8 logging + LOG_LEVEL + no bare print | ⚠️ | ⚠️ partial | Layer at `core/src/core/logging_config.py`; print→logger across core/ + bots/coder/. **Residual `traceback.print_exc()` at `feishu_client.py:186`** (C-1). LOG_LEVEL-fallback clause untested (C-3). `caplog` tests at `test_feishu_client.py:348-371` validate the swap |
| AC-9 `.env.example` documents every read var | ✅ | n/a | Code reads `FEISHU_APP_ID/SECRET`, `SESSION_TIMEOUT_HOURS`, `STREAM_UPDATE_INTERVAL` (`core/config.py:19-22`), `LOG_LEVEL` (`logging_config.py:28`); `.env.example` documents exactly those + optional `ANTHROPIC_API_KEY`. No documented-but-unread var |
| AC-10 dev docs exist & non-empty | ✅ | n/a | `CONTRIBUTING.md` (48L), `ARCHITECTURE.md` (72L), `.claude/CLAUDE.md` (36L) |

## B. Design fidelity

- **Logging layer**: matches the design snippet (`setup_logging()` + `get_logger()`, LOG_LEVEL→`getattr`→`isinstance` int guard → fallback INFO, basicConfig format identical). Implementation adds an idempotent `_configured` flag and an explicit `setLevel` — minor, harmless improvements. Prefix→level mapping followed: `[Feishu]/[Session]/[Git]` → info, errors → error with `exc_info=True` where an exception is in scope (`main.py:384,609`). Message text preserved. ✅
- **mypy gradual mode**: `ignore_missing_imports = true`, no `strict`, `check_untyped_defs = false`, tests/docs excluded — exactly the design's deferred trade-off. ✅ (deferred per design Trade-offs — not bounced)
- **Lockfile**: design allowed "`pip freeze` of a clean install if pip-tools unavailable"; `Makefile:58-59` uses `pip freeze --exclude-editable`. Exact pins present. ✅ on existence; see C-2 on the consumption wiring.
- **Single combined CI workflow**: one `ci.yml` with `test` matrix + `quality` job. ✅
- **`Session.client: object`→`Any`** (`session_manager.py:31`) and **`options_kwargs: dict[str, Any]`** (`sdk_client.py:76`): present, both narrowing-for-mypy only, no runtime effect. ✅
- **Security/redaction**: id truncation preserved (`[:8]` at `feishu_client.py:140,177`; main.py logs `sender_id[:8]`, `session_id[:8]`). No secret logged. ✅
- **Frontend / UX / API / DB / Performance**: n/a per design (dev-facing infra). ✅
- **Non-goals**: `main.py` NOT split (still one 635-line module — correct, Phase 3); no messaging/session behavior change; HR bot stub unchanged (still `print()`-based, deliberately out of scope, so its `main()` correctly does not call `setup_logging()`). ✅

## C. Quality findings

- **C-1 — Residual `traceback.print_exc()` in core/ — `core/src/core/feishu_client.py:186`** — Critical (AC violation). The `_on_event` except block was converted to `logger.error(f"[Feishu] Error handling message: {e}")` (line 183) but the following `traceback.print_exc()` (line 186) was left in place. AC-8 requires "no bare `print()` calls remain for operational logging in `core/`"; `traceback.print_exc()` writes the stack trace to stderr, bypassing the logging layer and LOG_LEVEL control. Worse, the adjacent `logger.error` does **not** pass `exc_info=True`, so the only place the traceback survives is the stderr print — exactly the output the feature set out to route through logging. Fix: drop `traceback.print_exc()` (and the now-unused `import traceback`) and add `exc_info=True` to the `logger.error` call (mirrors the correct pattern at `main.py:384` and `main.py:609`).

- **C-2 — Lockfile is generated but never consumed — `Makefile:27`, `.github/workflows/ci.yml:23,40`** — Important. `requirements.lock` exists and pins exact versions (satisfying AC-6's literal text), but neither `make setup` nor CI installs *from* it — both run `pip install -e "core[dev]" …` against unpinned floors. The design's stated intent ("CI/`make setup` can install from it for reproducibility") is therefore not realized: a fresh `make setup` resolves latest-compatible versions, not the locked set, so installs are not actually reproducible. Recommend adding `pip install -r requirements.lock` (or `pip-sync`) ahead of the editable installs in `setup` and the CI `test`/`quality` jobs. Not a merge blocker because the AC is phrased around the lockfile existing and pinning, which it does.

- **C-3 — LOG_LEVEL fallback path untested — `core/src/core/logging_config.py:28-31`** — Important. AC-8's second Given/When/Then ("unrecognized LOG_LEVEL → falls back to INFO rather than crashing") has no test; there is no test module for `logging_config.py` at all. The `caplog` tests at `test_feishu_client.py:348-371` cover the print→logging swap but not the config layer. Add a small test asserting `setup_logging()` with `LOG_LEVEL=BOGUS` does not raise and leaves the root logger at INFO, plus a happy-path `LOG_LEVEL=DEBUG` assertion.

- **C-4 — `except (ValueError, Exception)` is redundant — `bots/coder/src/coder/main.py:421`** — Suggestion (pre-existing, not introduced by this diff). `Exception` already subsumes `ValueError`; the tuple is dead. Flag only — fixing is optional and outside this feature's scope.

## D. Security findings

- **D-1 — No secrets in CI or repo** — pass. `ci.yml` sets no real Feishu/Anthropic credentials; tests mock those boundaries. `.env.example` carries only placeholders. Matches design Security section. ✅
- **D-2 — Log redaction preserved** — pass. App/session ids truncated to `[:8]`; `FEISHU_APP_SECRET` is never logged. ✅
- **D-3 — `traceback.print_exc()` (see C-1)** — the residual stack-trace print is a minor info-disclosure/consistency concern (full traceback to stderr unconditionally, outside LOG_LEVEL control). Folded into C-1; no separate action.

## Verdict

**NEEDS CHANGES** — one AC-violating defect (C-1) and two test/fidelity gaps (C-2, C-3). Coverage and design fidelity are otherwise strong; no structural problems, so this is a focused dev fix, not a redesign.

This is **Loop A — Dev fix**. None of the findings require touching the spec or design (the lockfile-consumption gap in C-2 is an implementation detail the design already anticipated, not a design error). The dev can resolve all three in-place and re-invoke `/sdlc-review`.

## What the dev should do next

1. **C-1 (blocker, AC-8)** — In `core/src/core/feishu_client.py:182-186`, delete `traceback.print_exc()` (and the now-unused `import traceback` on line 184) and change line 183 to `logger.error(f"[Feishu] Error handling message: {e}", exc_info=True)`. This is the last bare print-family call in `core/`.
2. **C-3 (AC-8 coverage)** — Add `core/tests/test_logging_config.py` asserting: (a) `LOG_LEVEL=BOGUS` → `setup_logging()` does not raise and root logger level is INFO; (b) `LOG_LEVEL=DEBUG` → level is DEBUG. Keeps AC-8's fallback clause from regressing.
3. **C-2 (AC-6 reproducibility)** — Wire the lockfile into install: add `pip install -r requirements.lock` before the editable installs in `Makefile` `setup` and in `.github/workflows/ci.yml` (`test` and `quality` jobs), so a fresh environment actually resolves to the pinned set.
4. **C-4 (optional)** — If touching `main.py:421`, simplify `except (ValueError, Exception)` to `except Exception`.
5. Re-run `make lint typecheck test` and re-invoke `/sdlc-review platform/hardening`. On PASS, proceed to `/sdlc-test platform/hardening` (the Tester will execute the tooling-based ACs and record AC-1/2/3/4/5/6/7/10 as *Non-functional — verified via tooling execution*).
