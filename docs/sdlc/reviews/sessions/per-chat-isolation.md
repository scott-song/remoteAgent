# Review: sessions/per-chat-isolation

> Reviewer: implementation-reviewer subagent · Date: 2026-06-12 · Verdict: PASS

## Summary

Clean, surgical implementation that does exactly what the design prescribed and nothing more. `chat_id` is threaded through the session identity as a first-class field, the 3-part key is consistent across in-memory and persisted-history paths, and **every** non-test `sessions.get/close/get_history/get_last_session_id` call site and all three `Session(...)` constructions were updated to the new arity — the arity sweep found zero missed 2-arg calls, so the runtime-`TypeError` risk called out in the brief is not present. The removed legacy `get_history` fallback has no remaining dependents. Only nits: a stale module docstring and a thin AC-4 command-layer assertion (a tester concern, not a blocker).

## A. AC coverage

| AC | Implemented? | Integration test? | Evidence |
|----|--------------|-------------------|----------|
| AC-1 Independent sessions per chat | ✅ | ✅ (dev, non-convention) | 3-part key in `session_manager.py:44,57,60`; `core/tests/test_session_manager.py::TestPerChatIsolation::test_distinct_chats_distinct_sessions` stores two chats, asserts `get(...,"chatA") is a` and `(...,"chatB") is b` through the manager |
| AC-2 Same chat reuses | ✅ | ✅ | `get` returns the stored session for the same 3-part key — `test_same_chat_reuses_session` |
| AC-3 Key includes chat | ✅ | ✅ | `Session.key` = `f"{user_id}:{bot_name}:{chat_id}"` (`session_manager.py:44`); `test_key_property` asserts `alice:mybot:oc_1`; distinctness in `test_distinct_chats_distinct_sessions` (`a.key != b.key`) |
| AC-4 Lifecycle commands act on originating chat | ✅ | ⚠ partial | `_cmd_new/_cmd_stop/_cmd_status` forward `chat_id` to `sessions.close/get` (`commands.py:113,129,135,150`); manager isolates by key. Command-layer tests pass `chat_id` but don't assert the *other* chat is untouched (see C) |
| AC-5 Stale cleanup per-chat | ✅ | ✅ | `cleanup_stale` closes via `self.close(s.user_id, s.bot_name, s.chat_id)` (`session_manager.py:88`); `test_cleanup_is_per_chat` proves stale chatA closed, active chatB survives |
| AC-6 Legacy history → fresh start, no error | ✅ | ✅ | Legacy `bot_name`-only fallback removed from `get_history` (`session_manager.py:131-135`); returns `[]` for an unmatched key (no error path); `test_history_is_per_chat` asserts chatB → `[]`. Note: `get_history` already returned `[]` for unknown keys, so removing the fallback cannot introduce an exception |

All convention-named (`int_AC_*` / `e2e_AC_*`) tests are absent — expected, since the tester stage hasn't run. Dev tests cover the behavior at the unit/integration layer. The traceability matrix at `docs/sdlc/traceability/sessions/per-chat-isolation.md` was missing on entry and regenerated.

## B. Design fidelity

- **API / signatures**: Matches the design's component-level spec exactly. `get`/`close` gained `chat_id: str` (`session_manager.py:59,69`); `_history_key`/`get_history`/`get_last_session_id` gained the chat segment (`133,131,138`); `save_to_history` kept its signature and uses `session.chat_id` (`104`). No deviation.
- **Database / persistence**: History key is `f"{user_id}::{bot_name}::{chat_id}"` (`session_manager.py:133`), the design's stated format. Storage format/location unchanged — still `HISTORY_FILE = ~/.claude-workspace/sessions.json` (`:22`), ADR-0005 honored. No migration, per resolved OQ-2.
- **Security**: No new external surface, no auth change. ADR-0006 untouched. `chat_id` is an existing transport-supplied identifier already in hand at every call site — no new trust boundary.
- **Performance**: Key is a pure function of three strings already available; no added I/O or query. No concern.
- **Frontend / UX**: N/A (no UI surface).
- **Trade-offs**: Implementation took the "add chat_id to the existing key" approach (not a nested registry) exactly as the design chose; the rejected nested-registry alternative was not reintroduced. Fresh-start trade-off implemented as designed (fallback deleted).

## Correctness checks (from the brief)

- **Removed legacy fallback**: No remaining code reads `self._history.get(bot_name, ...)` or calls `_history_key` with 2 args (grep clean across `core` + `bots`, non-test). The only `get_history` callers (`commands.py:205,225`, `get_last_session_id` at `session_manager.py:140`) all pass `chat_id`. Nothing depends on the deleted branch.
- **Dataclass field ordering**: `chat_id: str` (`session_manager.py:31`) is placed among the no-default fields (after `bot_name`, before the first defaulted field `connected` at `:34`). Valid — no "non-default follows default" error. Consistent with ruff/mypy PASS.
- **New isolation tests exercise distinct keys**: `test_distinct_chats_distinct_sessions` stores two sessions and retrieves each through `sm.get(...)` by distinct chat, not merely comparing key strings — genuine through-the-manager isolation. `test_cleanup_is_per_chat` likewise drives `cleanup_stale` and asserts differential survival.
- **Arity sweep**: 12 non-test `sessions.*` call sites, all 3-arg; the arity-missing regex returned zero hits. All 3 `Session(...)` constructions (`main.py:166,218,240`) include `chat_id=chat_id`, with `chat_id` confirmed in scope at each enclosing method.

## Non-goals respected

- No per-user auth/identity change (ADR-0006 untouched). ✅
- Persistence mechanism unchanged — still file-based JSON per ADR-0005. ✅
- Transport / SDK engine untouched (diff is confined to `session_manager.py`, `main.py`, `commands.py` + their tests). ✅

## C. Quality findings

- Module docstring drift — `core/src/core/session_manager.py:2` still reads "sessions keyed by (user_id, project_name)"; sessions are now keyed by `(user_id, bot_name, chat_id)`. — Suggestion.
- AC-4 command-layer test is thin — `bots/coder/tests/test_coder_main.py:855-856` (`test_new_resets`) asserts `close.assert_called_once()` but not the `chat_id` argument value, so it doesn't prove a `/new` in chat A leaves chat B's session intact at the command layer. Isolation is proven at the manager layer (`test_cleanup_is_per_chat`) and the command correctly forwards `chat_id`, so AC-4 holds by composition — but a dedicated cross-chat assertion belongs in the tester stage. — Important (for the tester, not a merge blocker).

## D. Security findings

- None. No new surface, no secret handling, no error-path leakage introduced. The error path in `_stream_response` (`main.py:349`) closes the session with `session.chat_id` (a valid field) — no behavior change beyond arity.

## Verdict

**PASS** — all six ACs have implementation evidence, design fidelity is exact, the arity sweep is clean (no runtime-TypeError risk), the removed fallback is safely dead, and non-goals are respected. Ready to advance to testing.

## What the dev should do next

- (Optional, Suggestion) Fix the stale module docstring at `core/src/core/session_manager.py:2` to reflect the `(user_id, bot_name, chat_id)` key.
- No required changes before merge.
- **Advance to `/sdlc-test sessions/per-chat-isolation`** (stage 6, role-tester). Flag for the tester: author `int_AC_*` / `e2e_AC_*` convention-named tests, and add an explicit AC-4 cross-chat assertion (`/new` / `/stop` / `/status` in chat A leaves chat B's session untouched) — currently covered only by composition.
