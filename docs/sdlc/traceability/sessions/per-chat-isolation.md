# Traceability matrix: sessions/per-chat-isolation

> Generated: 2026-06-12 · Source: spec `fd92f27`, plan `02b1c60` · Generator: /sdlc-trace
> Scope: grep limited to `core/tests/`, `bots/coder/tests/` (from plan task `Files` lines).

## Summary

- Total ACs: 6
- ✅ fully covered (integration + E2E): 0
- ⚠ partial: 0
- ❌ no convention-named coverage: 6
- Note: this matrix is generated **before** the tester stage (no test report exists). Dev-authored unit/integration tests covering the ACs exist but do **not** follow the strict `int_AC_<n>_*` / `e2e_AC_<n>_*` naming convention, so they are invisible to traceability by design. They are listed under "Dev tests (non-convention)" for the reviewer's benefit only.

## AC → convention-named tests

| AC | Behavior | Integration (`int_AC_*`) | E2E (`e2e_AC_*`) | Status |
|----|----------|--------------------------|------------------|--------|
| AC-1 | Independent sessions per chat | — | — | ❌ |
| AC-2 | Same chat reuses its session | — | — | ❌ |
| AC-3 | Session key includes the chat | — | — | ❌ |
| AC-4 | Lifecycle commands act on originating chat | — | — | ❌ |
| AC-5 | Stale cleanup is per-chat | — | — | ❌ |
| AC-6 | Legacy history does not break resume (fresh start) | — | — | ❌ |

## Dev tests (non-convention, informational)

These exercise the ACs but are not named per the traceability contract; the tester stage will author the convention-named tests.

| Likely AC | Test | File |
|-----------|------|------|
| AC-1, AC-3 | `TestPerChatIsolation::test_distinct_chats_distinct_sessions` | core/tests/test_session_manager.py |
| AC-2 | `TestPerChatIsolation::test_same_chat_reuses_session` | core/tests/test_session_manager.py |
| AC-3 | `TestSession::test_key_property` | core/tests/test_session_manager.py |
| AC-5 | `TestPerChatIsolation::test_cleanup_is_per_chat` | core/tests/test_session_manager.py |
| AC-6 / OQ-1 | `TestGetHistory::test_history_is_per_chat` | core/tests/test_session_manager.py |
| AC-4 (close path) | `TestStreamResponse` close-on-error asserts 3-arg `close` | bots/coder/tests/test_coder_main.py |

## Gaps

- All 6 ACs lack convention-named integration + E2E tests. This is expected pre-tester; resolve by running `/sdlc-test sessions/per-chat-isolation` (stage 6), which authors `int_AC_*` / `e2e_AC_*` tests and produces the test report.
- AC-4 lifecycle commands (`/new`, `/stop`, `/status`) have no dedicated dev test asserting "chat A command leaves chat B untouched" at the command layer — only the underlying `close`/`get` arity is exercised. The tester should cover this explicitly.

## Non-functional ACs

None declared.

## Bugs

No defect records reference this feature.
