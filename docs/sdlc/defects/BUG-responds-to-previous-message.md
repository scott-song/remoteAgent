# Defect: BUG-responds-to-previous-message — bot answers message N with the response to message N−1

> Owner: ssong@aaxis.io · Status: in-progress · Last updated: 2026-08-17

## Identification

- **ID**: BUG-responds-to-previous-message
- **Severity**: major
- **Reporter**: external user (ssong@aaxis.io, live Feishu usage)
- **Reported on**: 2026-08-17
- **Affected feature**: messaging streaming loop (`_stream_response` in `bots/coder/src/coder/main.py`) — pre-SDLC legacy behavior, no feature artifact
- **Related AC**: none — no AC covers message↔response pairing (missing-AC spec gap flagged, see Prevention)

## Repro steps

1. Hold a long Feishu session with the coder bot (long enough for the model to spawn auxiliary sessions — the bot enables `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`).
2. Wait until the bot appears idle, then send a new message N.
3. Observed: the bot replies with the response to message N−1 (typically re-asking a question the user already answered), repeatedly for every subsequent message, until `/new` is run.

**Environment**: production bot, main @ bd4f7b5; claude-agent-sdk 0.2.99.

## Expected vs actual

- **Expected**: each reply corresponds to the message that triggered it.
- **Actual**: once the client's message stream desyncs, every reply renders the *previous* turn's response; `/new` (which replaces the client but resumes the same transcript) clears it.

## Evidence

- Test name that fails: `test_regression_BUG_responds_to_previous_message_foreign_result_does_not_end_turn` (bots/coder/tests/test_coder_main.py)
- Mechanism evidence (scratchpad repro scripts, 2026-08-17):
  - clean resume: no replay, answer lands (`repro_resume.py`);
  - mid-turn disconnect: transcript persists (`repro_midturn_kill.py`);
  - Task-subagent turn: exactly one ResultMessage (`repro_task.py`);
  - code inspection: `receive_response()` reads one shared stream; the bot breaks on the FIRST `ResultMessage` of any origin (`main.py:313-316`), with no `session_id` check.

## Validation

- **Validation verdict**: reproduced (mechanism-level) + missing-AC spec gap
- **Validated on**: 2026-08-17 · **Environment**: main @ bd4f7b5, SDK 0.2.99, live user report + local repro scripts
- **Compared against**: none — no AC/design covers message↔response pairing. Clearly-wrong symptom (correctness: answer attributed to the wrong message) ⇒ real bug + missing-AC spec gap per role-bugfixer.
- **Notes**: user confirmed the symptom repeatedly in production and that `/new` heals it. The end-to-end desync trigger (a teammate session's ResultMessage) was not reproduced live — teammate spawns are model-driven — but the vulnerable loop is proven by inspection and the fix removes the entire class (any foreign ResultMessage). Routing decision (user, 2026-08-17 via AskUserQuestion): fix-first; spec authored as follow-up.

## Diagnosis

- **Root cause**: `_stream_response` iterates `client.receive_response()` and treats the **first `ResultMessage` of any origin** as end-of-turn. The SDK multiplexes all messages — including those of other sessions (agent-teams teammates; the bot sets `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) — onto one stream, and each message carries a `session_id` the bot never checks. One foreign `ResultMessage` mid-turn ends the bot's read loop early; the turn's real messages stay buffered, and every subsequent turn then renders the *previous* turn's buffered response — a permanent off-by-one until the client is replaced (`/new`). A foreign `SystemMessage`/`ResultMessage` could also overwrite `session.session_id`, corrupting resume history.
- **Why existing tests didn't catch it**: `test_result_message_breaks_loop` models only single-session streams — no test injects a message with a foreign `session_id`, so break-on-first-Result always looked correct.

### Root-cause category

- [x] **Implementation bug** — the streaming loop ignores message origin on a multiplexed stream.
- [x] **Test gap** — no test modeled multi-session streams.
- [ ] Spec / Design / Plan / Convention gap — *missing-AC spec gap flagged as follow-up (fix-first routing per user); see Prevention.*

## Fix

- **Tasks** added to plan: none (no feature plan exists for the legacy messaging loop; tracked by this record)
- **Bug-proof test**: `test_regression_BUG_responds_to_previous_message_two_turn_desync` (+ `..._foreign_result_does_not_end_turn`, `..._foreign_messages_not_rendered`) in `bots/coder/tests/test_coder_main.py` — fail first, pass after fix, against an SDK-faithful fake stream (`FakeMessageStream`: `receive_response()` terminates on the first ResultMessage of any origin; buffer position persists across calls)
- **Solution** (round 2, after implementation review): the SDK's own `receive_response()` generator terminates on the first `ResultMessage` of **any** origin, so filtering inside it cannot work (review finding F-1). `_stream_response` now consumes `client.receive_messages()` — which does not self-terminate — and ends the turn only on this session's own `ResultMessage`; foreign results are logged and skipped, and foreign `AssistantMessage` text is not rendered. `session.session_id` is adopted only from an `init`-subtype `SystemMessage` and only while the session has no id yet (a just-connected client, before anything foreign can share its stream) — a foreign system message can no longer hijack the id (F-3). Known limits, accepted: SDK `UserMessage` (tool results) carries no `session_id` and cannot be origin-filtered (F-4); when no session id is known and no init arrives, the filter is disabled — pre-fix fail-open behavior (F-5).
- **Files touched**: `bots/coder/src/coder/main.py`, `bots/coder/tests/test_coder_main.py`

## Propagation (per root-cause category)

- [ ] Spec edited via `role-ba` — *deferred: missing-AC spec gap filed as follow-up (user-approved fix-first routing)*
- [ ] Design updated — n/a
- [ ] Plan task added — n/a (no plan artifact for legacy messaging)
- [ ] Other features audited — n/a
- [ ] ADR filed — n/a
- [x] All edited artifacts back to `Status: approved` — no artifacts edited
- [ ] E2E tests reconciled by `role-tester` — pending `/sdlc-test`

## Resolution

- **Resolved on**: <pending>
- **Verified by**: <pending>
- **Regression run**: <pending>
- **Review + test**: <pending>
- **Deployed in**: <pending>

## Prevention (feeds the defect retrospective)

- **What would have caught / prevented this earlier**: an AC set for the messaging module's turn integrity ("a reply always corresponds to the triggering message; foreign stream events never end a turn"), and a test convention that any consumer of a multiplexed stream must be tested with foreign-origin messages.
- **Suggested improvement**: author `docs/sdlc/specs/messaging/turn-response-integrity.md` via role-ba (follow-up), and add to project test conventions: "streams shared across sessions must be tested with interleaved foreign-session messages". · **Layer**: project (spec + skill-extension note)
- **Recurrence**: first time recorded; same underlying confusion previously produced user reports of "responds to my last message" (this session's report).

## Links

- Related records: `BUG-stop-never-interrupts`, `BUG-queued-message-acked-as-processing` (same fix cycle, same branch `bugfix/BUG-responds-to-previous-message`)
