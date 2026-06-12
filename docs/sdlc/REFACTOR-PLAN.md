# Remote Agent — SDLC Adoption & Refactor Plan

> Status: **draft for review** · Author: Claude (autonomous session) · Date: 2026-06-12
> Branch: `refactor` · Plugin: `ai-sdlc-c1@ai-sdlc-c1-marketplace`
>
> This is a **plan**, not executed work. Nothing destructive has been run. Review each phase and
> approve before we start. Where the SDLC requires *you* to make a decision (ADRs, module list),
> those are flagged "needs your sign-off" — I have not made them for you.

---

## 0. Goal

Turn Remote Agent from a "well-architected but undermaintained" prototype into a **solid, long-lived
project** by adopting the AAXIS AI-SDLC flow as the operating discipline, and using its first passes
(bootstrap → scaffold) to pay down the concrete maintainability debt the assessment found.

Two things happen in parallel:
1. **Adopt the process** — install the SDLC artifact structure so all *future* change flows through
   spec → design → plan → build → review → test.
2. **Fix the debt** — run the current hardening backlog *through* that process (the scaffold feature),
   so the first real use of the pipeline is also the cleanup.

---

## 1. How the SDLC flow maps onto an EXISTING project

The plugin's lifecycle (`using-ai-sdlc`) is written for greenfield: **Bootstrap → Scaffold → Feature**.
For an existing codebase the mapping is:

| Plugin phase | Greenfield meaning | Our (brownfield) meaning |
|---|---|---|
| **Bootstrap** | Discover & lock stack decisions as ADRs | **Retroactively document** the decisions already made (monorepo, Python, Feishu, Claude SDK, pytest, file-based sessions) as ADRs so they're explicit and supersedable. |
| **Scaffold** | Stand up a runnable skeleton | **Harden** the existing skeleton: CI, lint/type tooling, logging, pinned deps, docs. Treated as one feature under the `platform` module. |
| **Feature** | Build new user-facing features | Backfill specs for existing capabilities, then run new changes (e.g. the per-chat session question) through the full pipeline. |

Key discipline points carried from the plugin:
- Every artifact is keyed `<module>/<feature>` and lives under `docs/sdlc/<stage>/<module>/`.
- The module vocabulary is fixed in `docs/sdlc/modules.md` (proposed — see §3).
- ADRs are **system-level** decisions in `docs/adrs/`; they are written via propose-then-choose and
  must be **chosen by you**, never assumed by me.
- Reviews and test-reviews run as **fresh-context subagents** — that isolation is the point.

---

## 2. Corrected assessment (what's actually wrong)

A deep assessment was run. **One headline finding was a false alarm — corrected here:**

- ❌ ~~CRITICAL: Feishu credentials committed to git history~~ → **FALSE.** `.env` was never committed
  and is not tracked; it is gitignored from line 1 and exists only on local disk. **No leak, no history
  rewrite needed.** (Verified: `git log --all -- .env` is empty.) Standard hygiene is fine here.

With that removed, the real, verified issues — in priority order:

| # | Issue | Evidence | Severity |
|---|---|---|---|
| 1 | **No CI** — tests only run via `make test` locally; nothing gates PRs | no `.github/workflows/` | High |
| 2 | **README is stale** — tells new devs to `cd bot` and `pip install <list>`; both wrong post-monorepo | `README.md:33-51` vs `Makefile:20-23` | High |
| 3 | **Deps unpinned, no lockfile** — only `>=` floors; non-reproducible installs | `core/pyproject.toml`, `bots/*/pyproject.toml` | High |
| 4 | **Python version contradiction** — README "3.10+", Makefile `python3.12`, memory note "3.8" | `README.md:25`, `Makefile:21` | High |
| 5 | **Dead `bot/` directory** — 364MB (mostly a stray `.venv`); only live file is an unused `remoteAgent.yaml`. Untracked, so deletion is local-only and safe | `git ls-files bot/` empty; `du -sh bot/` ≈ 365MB | Med |
| 6 | **`print()` everywhere, no `logging`** — ~40 call sites; no levels, no structure, unbounded `bot.log` | `feishu_client.py`, `main.py` | Med |
| 7 | **`main.py` is 563 lines** — dispatch + resolution + streaming + git all in one module | `bots/coder/src/coder/main.py` | Med |
| 8 | **No lint / format / type tooling** — no ruff/black/mypy/pre-commit config anywhere | repo-wide | Med |
| 9 | **Broad error handling** — bare `except Exception: pass` in shutdown; errors printed not logged | `main.py:79-83`, scattered | Med |
| 10 | **Missing docs** — no CONTRIBUTING, no ARCHITECTURE, no `.claude/CLAUDE.md`, no ADRs | repo-wide | Med |
| 11 | **`bot.log` not gitignored** | `.gitignore` (covers `.venv`, `__pycache__`, etc., but not `bot.log`) | Low |
| 12 | **HR bot is a stub** — decide: example template or remove | `bots/hr/src/hr/main.py` | Low |

Strengths to preserve: clean monorepo split (`core` shared, `bots/*` consumers), strong test suite
(~1.7:1 test:source ratio, ~93% claimed coverage), isolated security module, decent `.gitignore`.

---

## 3. Proposed module registry — **needs your sign-off**

Drafted in `docs/sdlc/modules.md`: `messaging`, `sessions`, `projects`, `agent-runtime`, `git-sync`,
`platform`. These map the existing code onto product areas so future artifacts have a home. Review and
edit the table before we write any spec — `role-ba` will refuse modules not listed there.

---

## 4. Proposed ADR set (retroactive bootstrap) — **needs your sign-off, one at a time**

These document decisions **already made**. Per the bootstrap discipline I will *not* author them as
"Accepted" unilaterally — each goes through propose-then-choose with you (or we batch-confirm since
they're retroactive). Run via `/sdlc-bootstrap "Feishu↔Claude-Code bridge bot, Python, self-hosted, single operator + small team"` or file individually with `/sdlc-adr`.

| ADR | Decision to record | Notes / open question |
|---|---|---|
| Repo strategy | **Monorepo**, plain pip + editable installs, shared `core` package | JS monorepo tools (Nx/Turbo) N/A for Python; sub-decision = setuptools workspaces |
| Language/runtime | **Python 3.1x** | ⚠️ Resolve the 3.8 / 3.10 / 3.12 contradiction here — pick the floor, make README + Makefile + `requires-python` agree |
| Messaging transport | **Feishu (Lark) via `lark-oapi` WebSocket long-connection**, outbound-only, no inbound server | |
| Agent engine | **Claude Agent SDK (`claude-agent-sdk`)** on the CLI subscription | |
| Session persistence | **File-based JSON** at `~/.claude-workspace/sessions.json` | Revisit-when: multi-host or >1 operator needs shared state → DB |
| Security model | **Per-project bash allowlist + path restriction** via PreToolUse hook | |
| Config & secrets | **dotenv `.env`** local + gitignored; no secrets manager | Revisit-when: deployed to shared infra |
| Test strategy | **pytest**, unit+integration collapsed; coverage gate in CI | |

Target: 8 ADRs — squarely in the plugin's 8–10 range.

---

## 5. The phased plan

### Phase 0 — Adopt the scaffolding *(done in this session, for your review)*
- ✅ Plugin enabled in `.claude/settings.json` (project scope) — needs a Claude Code reload to activate.
- ✅ `docs/sdlc/` + `docs/adrs/` + `docs/preferences/` tree created.
- ✅ `docs/sdlc/modules.md` drafted (proposed).
- ✅ This plan written.
- **Your action when back:** reload Claude Code so `/sdlc-*` commands load; review modules + ADR list.

### Phase 1 — Retroactive bootstrap (ADRs)  ·  module: n/a (system-level)
Record the 8 decisions in §4 as accepted ADRs; seed `docs/preferences/tech-preferences.md`.
**First real decision to make:** the Python version floor (resolves issue #4).
*Gate: you confirm each ADR.*

### Phase 2 — Platform hardening (the "scaffold" feature)  ·  module: `platform`
Run as **one feature** through the full pipeline: `platform/hardening`.
Spec ACs (each independently testable) cover the high/med issues:
- **AC: CI runs** — `.github/workflows/ci.yml` runs pytest on the agreed Python matrix + reports coverage; fails on test failure. (issue #1)
- **AC: lint/type green** — ruff + mypy configured in root `pyproject.toml`, `make lint`/`make typecheck` pass; pre-commit hook installs them. (issues #8)
- **AC: deps reproducible** — versions pinned, lockfile generated (pip-tools), `remoteagent-core` pinned in consumers. (issue #3)
- **AC: README accurate** — setup uses monorepo root + `make setup`/`make run-coder`; no `cd bot`. (issue #2)
- **AC: structured logging** — stdlib `logging` replaces `print()`; configurable level; `bot.log` rotated + gitignored. (issues #6, #11)
- **AC: dead code gone** — `bot/` deleted (local-only; safe), `.gitignore` hardened. (issue #5)
- **AC: docs exist** — `CONTRIBUTING.md`, `ARCHITECTURE.md`, `.claude/CLAUDE.md`. (issue #10)
*Gate: `/sdlc-review` (subagent) PASS, then `/sdlc-test` + `test-reviewer` PASS before merge.*

### Phase 3 — Code-structure features  ·  modules: `messaging`, `agent-runtime`
- `agent-runtime/main-decomposition` — split `main.py` into dispatch / command handlers / streaming. (issue #7)
- Tighten error handling; type the untyped Feishu event handlers. (issue #9)
*Run each as its own small feature so the diff stays reviewable.*

### Phase 4 — Backfill specs + first new feature  ·  all modules
- Backfill lightweight specs for the existing capabilities per module (documents current behavior as
  the baseline the tests defend).
- **First genuinely new feature through the full flow:** the per-chat session-isolation change you
  raised — `sessions/per-chat-isolation` (key the session by `(user, project, chat)` instead of
  `(user, project)`). Good first end-to-end demonstration of the pipeline on a real behavior change.
- Decide HR bot's fate (issue #12): document as example template, or remove.

---

## 6. Sequencing & risk

- **Order matters:** Phase 1 (ADRs) before Phase 2, because the Python-version ADR unblocks the CI
  matrix and `requires-python`. Everything else in Phase 2 is parallelizable.
- **Lowest-risk quick wins** (can do first, even before full pipeline adoption): delete `bot/`, fix
  README, gitignore `bot.log`. All reversible / local.
- **Highest-leverage:** CI + pinned deps — these stop *future* drift, which is the whole point of
  "long-lived."
- **Don't skip the review/test gates** on Phase 2 even though it's "just infra" — the plugin treats
  scaffold as a feature precisely so tooling changes get the same scrutiny.

---

## 7. What I did NOT do (waiting on you)

- Did **not** author/accept any ADR (those are your decisions).
- Did **not** delete `bot/` or any file.
- Did **not** push anything to remote.
- Did **not** modify source code.
- Did **not** rewrite git history (and confirmed there's no reason to).

## 8. Your next actions when you're back

1. **Reload Claude Code** so the plugin's `/sdlc-*` commands activate.
2. Review & edit `docs/sdlc/modules.md` (§3).
3. Confirm the Python version floor (§4) — the one decision blocking the rest.
4. Say "go" and I'll start Phase 1 (`/sdlc-bootstrap` or `/sdlc-adr` per decision), then Phase 2.
