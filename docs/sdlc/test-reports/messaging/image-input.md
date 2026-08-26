# Test report: messaging/image-input

> Owner: Tester
> Code under test (commit SHA): 9e0ce9fcaae83d8f76feb21ebb96318942330378
> Spec: `docs/sdlc/specs/messaging/image-input.md`
> Design: `docs/sdlc/designs/messaging/image-input.md`
> Plan: `docs/sdlc/plans/messaging/image-input.md`

<!-- sdlc-anchors: spec=h1:b82962101050 design=h1:b506e9264aab plan=h1:da6f8a2cebf3 verified=2026-08-26 -->

## Summary  <!-- Context -->

- **ACs total**: 14
- **ACs passed**: 14
- **ACs failed**: 0
- **ACs blocked / not testable**: 0

**Correcting the previous revision of this report**, which claimed no acceptance harness existed. That
was wrong: `bots/coder/tools/harness.py` already stood up the real bot with only the Feishu transport
faked. An acceptance layer was available the whole time, and the earlier `blocked` verdict rested on a
false premise.

## Environment  <!-- Context -->

- **Target**: in-process. The bot exposes no inbound surface (ADR-0003), so "deployed" means the real
  object graph wired in one process — `FeishuClient` + `ClaudeWorkspaceBot` + `ProjectRegistry` +
  `SessionManager` + `AttachmentStore`, all real.
- **Stack confirmed**: running ✅ (constructed per test) · serving this branch ✅ (imported from the
  working tree at `9e0ce9f`) · migrations pending: none ✅ (no datastore) · data: fresh per test
  (`tmp_path` store root, temp `sessions.json`)
- **Data**: a real PNG generated in-test by a stdlib encoder (`solid_png`) — crimson `(220, 20, 60)`,
  chosen because a model can name it unambiguously.
- **Runner concurrency**: 1 (pytest default; the e2e fixture owns a loop per test)
- **Level 1 (this feature's E2E)**: **14 tests, 2.5s** — `bots/coder/tests/test_e2e_image_input.py`
- **Level 2 (regression sweep)**: **full suite — 403 tests, 4.1s**, `EXIT=0`. Full rather than scoped
  because CI runs pytest only post-merge on this project, so the full sweep is the gate.

**What is faked, and why that is the honest boundary.** Two seams: the lark SDK client (no network)
and the Claude SDK client (no model). Everything between a Feishu *event* and the *prompt the agent
receives* is real code. AC-1 additionally ran against the **real model** through the harness, because
its observable is precisely what a fake cannot answer.

## Per-AC results  <!-- Contract -->

### AC-1: A pasted image is carried by the next message
- **Result**: ✅ pass
- **Test executed**: `pytest bots/coder/tests/test_e2e_image_input.py -k e2e_AC_1` **and** the real-model
  probe: `.venv/bin/python bots/coder/tools/harness.py` (Phase 4)
- **Evidence**: the e2e asserts the prompt carries `Attached image: <abs path>` and that the path
  exists on disk. The real-model run is the one that matters — the agent **called `Read` on the exact
  attachment path** and answered correctly:
  ```
  ↩️  reply→srv28: ⏳ Processing... (1 image attached)
  ✏️  update srv29: ✅ **Read** 2502ms
        /private/var/.../attachments/c658fd05f01a9c7a/b30e2012...png
        ---
        Red
  ```
  The image was crimson and the model said *"Red"*. **This retires the design's largest risk** — that
  a path-referenced image would be silently ignored. It is not.

### AC-2: An image and its caption in one message are used together
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_2`
- **Evidence**: a synthetic `post` event carrying text + one `img` element yields a single prompt with
  both, and **no** reaction is sent (no hold occurred).

### AC-3: Receipt is acknowledged without adding a chat message
- **Result**: ✅ pass (bot-side)
- **Test executed**: `-k e2e_AC_3`
- **Evidence**: a bare `image` event produces exactly one reaction on `m_img`, zero replies, and no
  agent turn (`FakeClaude.last_query == ""`).
- **Caveat that must not be lost**: this proves the bot *calls* `message_reaction.create` with
  `ACK_EMOJI = "EYES"`. It does **not** prove Feishu accepts that `emoji_type`. If the value is not in
  Feishu's enum the call fails and the acknowledgement never appears. **This is the single most likely
  live failure** — see *Coverage notes*.

### AC-4: Plain text is unaffected when nothing is held
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_4`
- **Evidence**: prompt is byte-identical to the user's text (`== "run the tests"`, not merely
  containing it) and the reply is exactly `⏳ Processing...` with no count. Real-model Phase 4b
  confirms the same path end to end.

### AC-5: An expired image is not attached, and the user is told
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_5`
- **Evidence**: with the store's clock advanced past `HOLD_TTL_SECONDS`, the prompt carries no
  attachment and a reply contains *"expired after 10 minutes"*.

### AC-6: Beyond the cap, the newest images win and the drop is visible
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_6`
- **Evidence**: six image events then one text message → the prompt contains exactly 5
  `Attached image:` lines and a reply names the dropped older image.

### AC-7: An oversized image is rejected on receipt
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_7`
- **Evidence**: reply is exactly *"⚠️ That image is over the 10 MB limit and was not attached."*,
  nothing is held (`store.take(...) == ([], [])`), and no turn starts. The size decision itself is
  proven at the unit layer by `int_AC_7_an_image_over_the_cap_is_rejected`, which asserts the read
  stops at `max_bytes + 1`.

### AC-8: A failed download is reported, not swallowed
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_8`
- **Evidence**: reply is exactly *"⚠️ Could not download that image from Feishu. Try sending it
  again."* and no turn starts.

### AC-9: One member's image never reaches another member's prompt
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_9`
- **Evidence**: user A pastes; user B's message carries no attachment; A's *next* message still
  carries it. Both halves asserted in one flow, which is what makes it meaningful.

### AC-10: A received image never enters the project repository
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_10`
- **Evidence**: a real `git init` in the project dir, a real image turn, then the real `git add -A`
  that `git_sync.commit_and_push` uses → `git diff --cached --name-only` is **empty**, and the
  attachment path is confirmed outside the project tree.

### AC-11: A held image is used once
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_11`
- **Evidence**: first message carries the image, second carries none while still carrying its own text.

### AC-12: A non-image attachment changes nothing
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_12`
- **Evidence**: a `file` event yields no reply, no reaction, no turn, and nothing held.

### AC-13: Retained images are cleaned up
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_13`
- **Evidence**: the file referenced by a completed turn exists, then `/new` (routing through the real
  `SessionManager.close`) deletes it — asserted on the real path from the real prompt.

### AC-14: Every receipt is recorded without its content
- **Result**: ✅ pass
- **Test executed**: `-k e2e_AC_14`
- **Evidence**: log carries `attachment accepted`, the byte size, and `ack_ms=`; the payload's leading
  bytes appear nowhere in the log.

## Defects filed  <!-- Contract -->

| ID | AC | Severity | Description | Status |
|----|----|----------|-------------|--------|

None. One **pre-existing** defect was found and fixed in passing rather than filed, because it is
neither an AC failure nor broken on `main` in a way this feature caused: the harness's
`FakeClaudeClient` implemented `receive_response()` while `_stream_response` consumes
`receive_messages()` (`main.py:293`), so `--mock-claude` could not run at all. Broken on `main` since
the `BUG-responds-to-previous-message` fix. Fixed in `9e0ce9f`.

## Blocked  <!-- Contract -->

None.

## Non-functional ACs  <!-- Contract -->

| AC | Verification method | Evidence (path or excerpt) | Result |
|----|---------------------|----------------------------|--------|
| Spec NFR: ack observable within 5 seconds | real-model harness run; `Read` completed in 2502ms, whole turn 6s, and the `⏳ Processing... (1 image attached)` ack precedes it | `/tmp/harness-real.log` Phase 4 | ✅ pass |
| Spec NFR: receiving must not block other chats | structural — `int_..._attachment_work_is_offloaded_not_run_on_the_websocket_thread` proves `_on_event` schedules and returns without downloading | `core/tests/test_feishu_client.py` | ⚠ partial — proven structurally, never under concurrent load |
| Spec NFR: bounded disk growth | TTL + cap + purge asserted at unit and e2e layers; no soak test run | `test_attachments.py`, `-k e2e_AC_13` | ⚠ partial — bounded by construction, not measured over time |

## Visual pass  <!-- Contract -->

`n/a — no UI built in this feature.` The bot renders no surface of its own; Feishu's client renders
everything. The user-visible strings are asserted verbatim at both layers.

## Self-review  <!-- Contract -->

| Check | Result | What changed |
|---|---|---|
| Assertion wired to reality (flipped the expected value → test failed → reverted) | ✅ | **16 flips across all 14 e2e tests, batched into one run: 13 of 13 then-existing tests went red, none survived.** Flips included `Attached image:`→`Attached photo:`, the reaction id, `⏳ Processing...`→`⏳ Working...`, cap 5→4, `10 minutes`→`11 minutes`, `attachment accepted`→`attachment refused`, `ack_ms=`→`ack_us=`, and inverting AC-13's deletion assertion. Reverted; re-run green (14/14). |
| Asserts the AC's observable, not just status/visibility | ✅ | AC-4 asserts prompt **equality**, not containment. AC-1 asserts the referenced path is a real file. AC-10 runs a real `git add -A`. AC-13 deletes the real path taken from the real prompt. |
| Nothing disabled (`.skip` / `.only` / `fixme` / commented assertion) | ✅ | `grep` for `skip`/`xfail`/`only` in the e2e file: no hits |
| Stands alone (isolation, shuffled, parallel workers) | ✅ | `-k "AC_1 or AC_13"` in isolation: 5 passed. Each test gets its own `tmp_path`, its own store and its own loop; no module-level state except `FakeClaude.last_query`, reset by the fixture. |
| Fixture is not the production predicate restated | ✅ | The PNG comes from a standalone stdlib encoder, not from `_sniff`'s signature table — so a wrong signature table would fail the test rather than agree with it. |

## Coverage notes  <!-- Context -->

- **Out-of-AC probes run**: the real-model harness phase (AC-1) and a real `git add -A` (AC-10) both go
  beyond what the ACs strictly require, because both were named risks in the design.
- **Out-of-AC risks NOT probed** — these are exactly what a live Feishu pass should target:
  1. **`ACK_EMOJI = "EYES"` is unvalidated against Feishu's `emoji_type` enum.** Highest-likelihood
     live failure; symptom is a silently missing reaction with a WARNING in the log.
  2. **Feishu's live wire format.** Every event here is synthetic, built from the documented shape. If
     a real `post` nests rich text differently, AC-2's extraction breaks and nothing here would notice.
  3. **The real `message_resource.get` call.** `download_resource` is mocked at the e2e layer; its
     retry/stream handling is unit-tested against a `BytesIO`, never against Feishu.
  4. **The 10 MB cap vs Feishu's real ceiling** — still the spec's open question.
  5. **Prompt injection via image content** — accepted residual risk in the design; no AC asserts it.
  6. **Concurrent pastes from one sender** — `AttachmentStore` is documented single-writer; not probed.
- **Structural gap still standing**: ADR-0008 declined an E2E framework for "no UI surface". This pass
  shows an acceptance layer was buildable without one — but it is bespoke, and the ADR still describes
  a project with no such layer. Worth an ADR revision.

## Sign-off  <!-- Contract -->

- Tester: Claude (agent)
- **Verdict**: `passed`
