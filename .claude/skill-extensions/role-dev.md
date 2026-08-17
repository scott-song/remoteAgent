# role-dev — project extensions (remoteClaudeCode)

## Test fakes must model the dependency's termination semantics

**Why:** BUG-responds-to-previous-message round 1 shipped an ineffective fix that its
bug-proof test green-lit: the test fake for `ClaudeSDKClient.receive_response()` yielded
messages *past* a `ResultMessage`, a stream the real SDK can never produce (the real
generator terminates on the first `ResultMessage` of any origin). The test discriminated
against the old code but not against the still-broken new code.

**Rule:** when faking a stream/iterator/connection from a third-party SDK, reproduce its
termination and buffering semantics, not just its message shapes — read the SDK source for
the generator's exit condition and encode it in the fake (see `FakeMessageStream` in
`bots/coder/tests/test_coder_main.py`). A fake that is more permissive than the real
dependency proves nothing.

## Async client methods in fakes

Fake async SDK methods with `AsyncMock` and assert with `assert_awaited*`, never
`assert_called*` alone — a call is recorded whether or not the coroutine was awaited
(BUG-stop-never-interrupts: `interrupt()` called without `await` passed `assert_called_once`).
