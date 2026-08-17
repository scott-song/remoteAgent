# Defect: BUG-stop-never-interrupts — /stop reports "Interrupted." but never interrupts

> Owner: ssong@aaxis.io · Status: fixed · Last updated: 2026-08-17

## Identification

- **ID**: BUG-stop-never-interrupts
- **Severity**: major
- **Reporter**: found during diagnosis of BUG-responds-to-previous-message
- **Reported on**: 2026-08-17
- **Affected feature**: `/stop` command (`_cmd_stop` in `bots/coder/src/coder/commands.py`)
- **Related AC**: none directly — HELP_TEXT documents "`/stop` — interrupt request"; `sessions/per-chat-isolation` AC-4 governs only *which* session it targets, not that the interrupt works

## Repro steps

1. Start a long-running request in a chat.
2. Send `/stop` while it runs.
3. Observed: the bot replies "Interrupted." but the request keeps running to completion.

**Environment**: main @ bd4f7b5; claude-agent-sdk 0.2.99.

## Expected vs actual

- **Expected**: the running request is interrupted (per HELP_TEXT's own contract "interrupt request").
- **Actual**: `session.client.interrupt()` is a **coroutine that is never awaited** (`commands.py:143`) — a silent no-op plus a "coroutine was never awaited" RuntimeWarning; the success reply is a lie.

## Evidence

- Test name that fails: `test_regression_BUG_stop_never_interrupts_interrupt_is_awaited` (bots/coder/tests/test_coder_main.py)
- SDK: `ClaudeSDKClient.interrupt` is `async def` (claude_agent_sdk/client.py:313).
- Existing test `test_stop_interrupts_running` could not have failed: its fake used `interrupt = MagicMock()` and asserted only `assert_called_once()` — a call is recorded whether or not the coroutine is awaited. Systemic weakness noted in Prevention.

## Validation

- **Validation verdict**: reproduced
- **Validated on**: 2026-08-17 · **Environment**: main @ bd4f7b5, SDK 0.2.99
- **Compared against**: HELP_TEXT contract ("`/stop` — interrupt request"); no AC covers interrupt semantics. Checked the contract for an intentional fire-and-forget: none — specs and ADRs are silent on /stop; the code's own success reply ("Interrupted.") shows intent.
- **Notes**: contradiction is between the code's stated intent and its effect; the un-awaited call is a defect, not a specified best-effort behavior.

## Diagnosis

- **Root cause**: `interrupt()` became async in the SDK API but the call site invokes it synchronously; Python creates the coroutine object and discards it, so the control request is never sent to the CLI.
- **Why existing tests didn't catch it**: the shared fake modeled `interrupt` as a sync `MagicMock`, and the assertion (`assert_called_once`) cannot distinguish "called" from "awaited".

### Root-cause category

- [x] **Implementation bug** — missing `await`.
- [x] **Test gap** — fake modeled the wrong interface; assertion could not fail for this bug.

## Fix

- **Tasks** added to plan: none (tracked by this record)
- **Bug-proof test**: `test_regression_BUG_stop_never_interrupts_interrupt_is_awaited` in `bots/coder/tests/test_coder_main.py` — uses `AsyncMock` + `assert_awaited_once()`; fails first (called but not awaited), passes after fix
- **Solution**: `await session.client.interrupt()`; the shared test fake now models `interrupt` as `AsyncMock` so await-vs-call is distinguishable.
- **Files touched**: `bots/coder/src/coder/commands.py`, `bots/coder/tests/test_coder_main.py`

## Propagation (per root-cause category)

- [x] All edited artifacts back to `Status: approved` — no artifacts edited
- [ ] E2E tests reconciled by `role-tester` — pending `/sdlc-test`

## Resolution

- **Resolved on**: 2026-08-17
- **Verified by**: `.venv/bin/python -m pytest bots/coder/tests/test_coder_main.py -k stop_never_interrupts -q` → passed (failed pre-fix: interrupt called but never awaited)
- **Regression run**: full suite (`make test`) — 299 passed
- **Review + test**: `/sdlc-review` round 1 approved this fix as-is; round 2 APPROVE overall · E2E pending spec follow-up
- **Deployed in**: a47fcf2 (branch `bugfix/BUG-responds-to-previous-message`, not yet merged)

## Prevention (feeds the defect retrospective)

- **What would have caught / prevented this earlier**: a lint rule for un-awaited coroutines — ruff's `RUF006`/flake8-async class, or mypy `disallow_untyped_calls` with `unused-coroutine` (mypy flags "coroutine is not awaited" via `--enable-error-code unused-awaitable` / default `unused-coroutine` in strict).
- **Suggested improvement**: enable ruff rule `ASYNC` group or mypy `unused-coroutine` error code in CI; test-convention: async client methods are faked with `AsyncMock` and asserted with `assert_awaited*`. · **Layer**: project (lint config + skill-extension note for role-dev)
- **Recurrence**: first time.

## Links

- Related records: `BUG-responds-to-previous-message` (same fix cycle/branch)
