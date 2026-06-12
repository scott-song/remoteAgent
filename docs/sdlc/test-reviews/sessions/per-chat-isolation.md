# Test review: sessions/per-chat-isolation

> Reviewer: test-reviewer subagent · Date: 2026-06-12
> Test report reviewed: docs/sdlc/test-reports/sessions/per-chat-isolation.md (run 2026-06-12, code SHA `35b8a45`)
> Verdict: **PASS**

## Summary

The `passed` verdict (6/6 ACs) is honest. Every AC maps to a real, executed test with a
meaningful assertion — confirmed by re-running the suite (287 passed, 88% coverage, matching the
report) and by mutation testing: reverting the session key to its old 2-part `(user, project)` form
kills 4 of the isolation tests, and forwarding the wrong `chat_id` in `_cmd_new` kills the AC-4
test. No tautologies, no silent skips, no false-confidence tests. The impl-reviewer's specific
AC-4 request (assert the `chat_id` argument value, not just `close` was called) was honored. One
documentation-honesty nuance on AC-4 `/stop`/`/status` (covered by composition, not a dedicated
cross-chat test) is noted but does not undermine the verdict.

## Freshness & integrity

- Spec `fd92f27`, design `260d697` — both match the report's anchors. Plan = branch `refactor`
  (`02b1c60`), consistent. Spec/design/plan all `Status: approved`. Chain is fresh.
- The report's code SHA `35b8a45` differs from current HEAD `aa60b2a`, but the only commit between
  them (`aa60b2a`) is the docs commit that added this very report — **zero code-under-test files
  changed** (`git diff --stat 35b8a45 aa60b2a` over `session_manager.py` / `main.py` /
  `commands.py` and their tests is empty). The dispatcher's `aa60b2a` and the report's `35b8a45`
  audit the same code. Not stale.

## A. Verdict honesty

All tests re-run locally (`.venv/bin/python -m pytest`) — 7/7 AC-mapped tests pass; full suite 287
passed, coverage 88% (report says 87.65% / ≥85% gate — consistent).

| AC | Tester verdict | Evidence honest? | Notes |
|----|----------------|------------------|-------|
| AC-1 Independent sessions per chat | ✅ pass | ✅ | `test_distinct_chats_distinct_sessions` stores two chats through the manager and asserts `get(...,"chatA") is a`, `get(...,"chatB") is b`. Mutation (2-part key) → second store overwrites first → test fails. Genuine. |
| AC-2 Same chat reuses | ✅ pass | ✅ | `test_same_chat_reuses_session`: `get(...,"chatA") is a` for the stored instance (identity, not equality). |
| AC-3 Key includes chat | ✅ pass | ✅ | `test_key_property` asserts `alice:mybot:oc_1`; `a.key != b.key` in the distinct-chats test. Mutation killed both. |
| AC-4 Lifecycle commands act on originating chat | ✅ pass | ✅ (with nuance, see D) | `TestCmdNew::test_new_resets` asserts `sessions.close.assert_called_once_with("user1","proj1","chat1")`. The `chat_id` value is asserted — impl-reviewer's request honored. |
| AC-5 Stale cleanup per-chat | ✅ pass | ✅ | `test_cleanup_is_per_chat` makes chatA stale + chatB fresh, runs `cleanup_stale()`, asserts `get(chatA) is None` AND `get(chatB) is fresh` — one closed, one survives (not both/neither). |
| AC-6 Legacy history → fresh start, no error | ✅ pass | ✅ | `test_history_is_per_chat` (chatB → `[]`) + `test_returns_empty_for_unknown`. `get_history` (`session_manager.py:132-136`) has no raise path — returns `sorted(self._history.get(key, []))`. A legacy `user::project` key simply doesn't match the 3-segment key; cannot error. |

No ✅ pass rests on "test ran" vagueness; each entry names the test + the observable assertion.

## B. Coverage truth

- All 6 ACs appear in the report's per-AC table, each backed by a named, existing, passing test.
- The traceability matrix (`docs/sdlc/traceability/sessions/per-chat-isolation.md`) shows all 6 ACs
  as ❌ "no convention-named coverage". This is **not a coverage gap** — the matrix was generated
  pre-tester and explicitly documents (line 12) that the dev-authored tests exercise every AC but
  don't follow the `int_AC_*` / `e2e_AC_*` naming convention, so they're invisible to the grep.
  The tester chose **not** to author convention-named wrappers (reasonable: this is a pure
  behavior/session-layer feature with no live Feishu in CI, and the existing unit/integration tests
  already prove every AC at the layer where the behavior lives). Per my instructions I do not flag
  the matrix's pre-tester staleness as a finding. **Informational only:** the matrix was not
  regenerated after the tester stage, so on disk it still reads "0 covered" — anyone reading the
  matrix alone (without the report) would be misled. See "What the tester should do next".
- No AC is marked `n/a` or verified-via-other-method without evidence. The one "NOT tested" item
  (live two-Feishu-chat E2E) is honestly disclosed in Coverage notes with the correct rationale:
  no live Feishu in CI; the behavior is the session key, proven by distinct-key assertions.

## C. Test-code quality

E2E naming convention does not apply (no E2E layer for this feature; verified by unit/integration
per the report). Judged the cited unit/integration tests against general best practice.

| Test | Naming/intent | AC ref | Isolation | Assertion quality | Notes |
|------|---------------|--------|-----------|-------------------|-------|
| `test_distinct_chats_distinct_sessions` | ✅ clear | ✅ docstring "AC-1/2/3" + inline `# AC-3` | ✅ fresh `sm` fixture (tmp_path) | ✅ identity asserts through the manager + `key !=` | Drives the real manager, not just string compare. |
| `test_same_chat_reuses_session` | ✅ | ✅ `# AC-2` | ✅ | ✅ identity (`is a`) | Correct: reuse means same instance. |
| `test_cleanup_is_per_chat` | ✅ | ✅ docstring AC-5 | ✅ | ✅ differential survival | Uses `patch.object(time,"time")` to freeze time — no `sleep`, no flake. |
| `test_key_property` | ✅ | ✅ | ✅ | ✅ exact string `alice:mybot:oc_1` | Specific, not a regex/loose match. |
| `test_history_is_per_chat` | ✅ | ✅ docstring AC-6/OQ-1 | ✅ | ✅ len==1 for A, `==[]` for B | Seeds via `_history_key` then queries — correct. |
| `test_returns_empty_for_unknown` | ✅ | (AC-6 support) | ✅ | ✅ `== []` | — |
| `TestCmdNew::test_new_resets` | ✅ | ✅ inline `# AC-4` | ✅ `bot` fixture, `AsyncMock` close | ✅ `assert_called_once_with(...)` exact 3-arg | Also asserts `registry.reload` + reply text "reset". |

Wait discipline: clean — time is frozen via `patch.object` where staleness matters; no
`waitForTimeout`/`sleep` in assertions (the only `time.sleep(0.01)` is in `test_touch`/`test_calls_touch`
to advance the clock, which is legitimate and not a flake source). Locators: N/A (no UI).

## D. Test-code validity (mutation thought-experiments, executed)

I ran two real mutations and confirmed the tests catch them (restored after each):

1. **Revert key to 2-part** (`{user}:{bot}` and `{user}::{bot}`, dropping `chat_id` from `Session.key`,
   `get`/`close`, and `_history_key`): **4 tests failed** —
   `test_distinct_chats_distinct_sessions`, `test_cleanup_is_per_chat`, `test_history_is_per_chat`,
   `test_key_property`. So AC-1/2/3/5/6 are genuinely guarded: if the feature regressed to the old
   shared-session behavior, the suite goes red.
2. **Wrong chat in `_cmd_new`** (`close(sender_id, project_name, "WRONG_CHAT")`):
   `TestCmdNew::test_new_resets` failed. So AC-4's "targets the originating chat" is genuinely
   guarded — the `assert_called_once_with("user1","proj1","chat1")` is load-bearing, not decorative.

**AC-4 nuance (not a defect, disclosed for honesty):** the report states `/stop` and `/status`
"resolve the session via the same `sessions.get(..., chat_id)` path." That is true by code
inspection (`commands.py:135,150` both pass `chat_id`), and `_stream_response`'s error-path close
also asserts the 3-part identity (`test_coder_main.py:756`). But there is **no dedicated test**
asserting that a `/stop` or `/status` issued in chat A leaves chat B's session untouched at the
command layer — the `TestCmdStop` tests assert reply text, not the `chat_id` passed to
`sessions.get`. AC-4 therefore holds by **composition** (manager-layer isolation proven by
`test_cleanup_is_per_chat` + `_cmd_new`'s explicit chat assertion + correct forwarding), exactly as
the impl-reviewer noted in finding C. This is acceptable for a PASS — the originating-chat
guarantee is the manager's, and the manager is well-tested — but a one-line `get.assert_called_with`
on `/stop`/`/status` would make AC-4 self-evident rather than inferred.

No over-mocking concern: these are unit/integration tests by design (the feature is the in-process
session key), not mislabeled E2E. Mocking the SDK client's `disconnect`/`interrupt` is appropriate
at this layer.

## E. Defect honesty

No defects filed. Verified none were warranted — all ACs pass against real assertions; nothing was
suppressed into a `blocked`/`n/a`. Honest.

## F. Manual / n/a audit

The only `n/a` is the "Non-functional ACs" line — correct, the spec declares none. The "live
two-Feishu E2E not tested" disclosure names its rationale (no live Feishu in CI) and the
compensating coverage (distinct-key assertions). Justified.

## Verdict

**PASS** — every AC verdict is honest and backed by an executed test with a meaningful assertion;
mutation testing confirms the tests would catch a real regression (both the key-reversion and the
wrong-chat cases go red); the impl-reviewer's AC-4 request was honored; coverage and suite counts in
the report reproduce exactly (287 passed, 88%). The feature is **shippable**.

## What the tester should do next

No required changes. Two optional, low-effort improvements (do not gate shipping):

1. **(Optional) Regenerate the traceability matrix.** Run `/sdlc-trace sessions/per-chat-isolation`
   so the on-disk matrix reflects the post-tester state instead of still showing "0 covered" — it
   currently misleads anyone reading the matrix without the test report. (The tests themselves are
   fine; this is a derived-artifact freshness fix.)
2. **(Optional) Add an explicit AC-4 cross-chat assertion** for `/stop` and `/status`: assert
   `bot.sessions.get` is called with `("user1","proj1","chat1")` in `TestCmdStop` /
   `test_status_with_session`. This converts AC-4 from "holds by composition" to "directly proven"
   and closes the exact gap the impl-reviewer flagged.

Neither blocks merge. Recommend the user mark `sessions/per-chat-isolation` done.
