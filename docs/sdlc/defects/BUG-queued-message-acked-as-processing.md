# Defect: BUG-queued-message-acked-as-processing — queued message acknowledged as if it were being processed

> Owner: ssong@aaxis.io · Status: in-progress · Last updated: 2026-08-17

## Identification

- **ID**: BUG-queued-message-acked-as-processing
- **Severity**: minor
- **Reporter**: found during diagnosis of BUG-responds-to-previous-message (it amplified that bug's confusion)
- **Reported on**: 2026-08-17
- **Affected feature**: message acknowledgment (`_on_message` in `bots/coder/src/coder/main.py`, `_quick_action` in `commands.py`)
- **Related AC**: none — no AC governs acknowledgment content

## Repro steps

1. Send a message that starts a long-running turn.
2. While it runs, send a second message.
3. Observed: the second message is immediately acked "⏳ Processing..." although it is queued behind the running turn (`Session.lock`) and will not start until that turn finishes.

**Environment**: main @ bd4f7b5.

## Expected vs actual

- **Expected**: the ack tells the user the message is queued behind the previous one (and how to interrupt), so a late-arriving answer is not mistaken for a reply to the new message.
- **Actual**: unconditional "⏳ Processing..." signals the new message is being worked on when it is not.

## Validation

- **Validation verdict**: cannot-decide → user decision recorded
- **Validated on**: 2026-08-17 · **Environment**: main @ bd4f7b5
- **Compared against**: none — no AC/design governs ack content.
- **Notes**: behavior reproduced trivially from code (`main.py:82` acks before scheduling; `_handle_prompt` then blocks on `session.lock`). No contract governs it, so the disposition was routed to the user (AskUserQuestion, 2026-08-17): **user chose to treat it as a defect and fix it in this cycle** ("All three"). Decision recorded here per role-bugfixer cannot-decide protocol.

## Diagnosis

- **Root cause**: the ack is emitted in `_on_message` before the per-session lock is consulted, so it cannot reflect queueing; turns are serialized per session with no feedback, which in long sessions (slow turns) puts the user permanently one message "behind" perceptually.
- **Why existing tests didn't catch it**: tests asserted the unconditional ack (`test_regular_text_sends_processing`) — they encoded the defect.

### Root-cause category

- [x] **Implementation bug** — ack ignores session busy state (per user's disposition; no spec to gap against).

## Fix

- **Tasks** added to plan: none (tracked by this record)
- **Bug-proof test**: `test_regression_BUG_queued_message_acked_as_processing_busy_gets_queued_notice` in `bots/coder/tests/test_coder_main.py` — fails first, passes after fix
- **Solution**: `_on_message` and `_quick_action` check whether the resolved session's lock is held (`_session_busy`) and ack busy sessions with "⏳ Still working on your previous message — this one is queued. Send /stop to interrupt." Existing ack tests updated to the new contract (idle → "Processing...", busy → queued notice).
- **Files touched**: `bots/coder/src/coder/main.py`, `bots/coder/src/coder/commands.py`, `bots/coder/tests/test_coder_main.py`

## Propagation (per root-cause category)

- [x] All edited artifacts back to `Status: approved` — no artifacts edited
- [ ] E2E tests reconciled by `role-tester` — pending `/sdlc-test`

## Resolution

- **Resolved on**: <pending>
- **Verified by**: <pending>
- **Regression run**: <pending>
- **Review + test**: <pending>
- **Deployed in**: <pending>

## Prevention (feeds the defect retrospective)

- **What would have caught / prevented this earlier**: the missing messaging spec (see BUG-responds-to-previous-message Prevention) — an AC on acknowledgment semantics would have caught the misleading ack at spec review.
- **Suggested improvement**: include ack/queue-feedback ACs in the follow-up `messaging/turn-response-integrity` spec. · **Layer**: project (spec)
- **Recurrence**: first time.

## Links

- Related records: `BUG-responds-to-previous-message`, `BUG-stop-never-interrupts` (same fix cycle/branch)
