# Test report: sessions/per-chat-isolation

> Owner: Tester · Status: passed · Run on: 2026-06-12 (local, Python 3.12.11)
> Code under test (commit SHA or branch): `35b8a45` (branch `refactor`)
> Spec: `docs/sdlc/specs/sessions/per-chat-isolation.md` · Spec version tested: 2026-06-12 (commit `fd92f27`)
> Design: `docs/sdlc/designs/sessions/per-chat-isolation.md` · Design version tested: 2026-06-12 (commit `260d697`)
> Plan: `docs/sdlc/plans/sessions/per-chat-isolation.md` · Plan version tested: 2026-06-12 (branch `refactor`)

## Summary

- **Result**: passed
- **ACs total**: 6
- **ACs passed**: 6
- **ACs failed**: 0
- **ACs blocked / not testable**: 0

This is a behavior feature; each AC is verified by executed unit/integration tests against the session layer and the bot command path. Full suite: **287 passed**, coverage **87.65%** (≥85% gate).

## Per-AC results

### AC-1: Independent sessions per chat
- **Result**: ✅ pass
- **Test executed**: `core/tests/test_session_manager.py::TestPerChatIsolation::test_distinct_chats_distinct_sessions`
- **Evidence**: two sessions for `(u, proj, chatA)` and `(u, proj, chatB)` are stored and retrieved independently; `get(u, proj, chatA) is a`, `get(u, proj, chatB) is b`.

### AC-2: Same chat reuses its session
- **Result**: ✅ pass
- **Test executed**: `TestPerChatIsolation::test_same_chat_reuses_session` (+ `TestGet::test_returns_connected_session`)
- **Evidence**: `get(u, proj, chatA)` returns the same stored instance.

### AC-3: Session key includes the chat
- **Result**: ✅ pass
- **Test executed**: `TestSession::test_key_property` (`alice:mybot:oc_1`) + `test_distinct_chats_distinct_sessions` (`a.key != b.key`).
- **Evidence**: `Session.key` is `user:bot:chat`; distinct chats → distinct keys, same chat → same key.

### AC-4: Lifecycle commands act on the originating chat's session
- **Result**: ✅ pass
- **Test executed**: `bots/coder/tests/test_coder_main.py::TestCmdNew::test_new_resets`
- **Evidence**: `_cmd_new("user1", "chat1", ...)` calls `sessions.close("user1", "proj1", "chat1")` — the chat_id is forwarded, so the command targets only that chat's session. `/stop` and `/status` resolve the session via the same `sessions.get(..., chat_id)` path.

### AC-5: Stale cleanup is per-chat
- **Result**: ✅ pass
- **Test executed**: `TestPerChatIsolation::test_cleanup_is_per_chat`
- **Evidence**: with one chat's session stale and another's fresh, `cleanup_stale()` closes only the stale chat's session; the fresh chat's session survives.

### AC-6: Legacy history does not break resume (fresh start)
- **Result**: ✅ pass
- **Test executed**: `TestGetHistory::test_history_is_per_chat` + `test_returns_empty_for_unknown`
- **Evidence**: history is keyed `user::bot::chat`; a chat with no history returns `[]` (no error). Legacy `user::project` entries simply don't match the new key — the documented fresh-start behavior; `get_history` cannot raise on them.

## Defects filed

None.

## Blocked

None.

## Non-functional ACs

n/a — all ACs verified via executed unit/integration tests above.

## Coverage notes

- **Edge cases tested beyond the AC**: disconnect-error handling during per-chat close; history cap; sorted-desc ordering — all still green under the new signatures.
- **Edge cases NOT tested**: live two-Feishu-chat end-to-end (no live Feishu in CI) — covered at the unit/integration layer by distinct-key assertions, which is where the behavior lives.

## Sign-off

- Tester: Claude (role-tester, executed via dispatcher)
- Date: 2026-06-12
- Verdict: **feature meets spec** — all 6 ACs pass; no defects.
