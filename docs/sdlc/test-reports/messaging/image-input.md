# Test report: messaging/image-input

> Owner: Tester
> Code under test (commit SHA): 1444e7523acbcd8e61b6bc0721c1e8b0241e4406
> Spec: `docs/sdlc/specs/messaging/image-input.md`
> Design: `docs/sdlc/designs/messaging/image-input.md`
> Plan: `docs/sdlc/plans/messaging/image-input.md`

<!-- sdlc-anchors: spec=h1:b82962101050 design=h1:b506e9264aab plan=h1:da6f8a2cebf3 verified=2026-08-26 -->

## Summary  <!-- Context -->

- **ACs total**: 14
- **ACs passed**: 0
- **ACs failed**: 0
- **ACs blocked / not testable**: 14 (see *Blocked*)

**No acceptance test was executed.** Nothing failed — the acceptance environment does not exist for
this feature, and the report says so rather than promoting the dev-layer suite into a verdict it did
not earn.

## Environment  <!-- Context -->

- **Target**: none. There is no `BASE_URL`: the bot exposes no inbound surface by design (ADR-0003),
  so its only user-facing interface is a live Feishu chat.
- **Stack confirmed**: running ❌ · serving this branch ❌ · migrations pending: n/a (no datastore) ·
  data: n/a
- **Data**: n/a — no fixture layer exists for a Feishu workspace.
- **Runner concurrency**: n/a
- **Level 1 (this feature's E2E)**: **not run — 0 tests authored.** ADR-0008 states *"No separate E2E
  framework (no UI surface)"*, and no Playwright / Cypress / pytest-bdd is configured in any
  `pyproject.toml`. There is no acceptance harness to author into.
- **Level 2 (regression sweep)**: **not run.** Scoping it would be meaningless with level 1 at zero.

Four environment confirms, checked before any test work:

| Confirm | Result | Evidence |
|---|---|---|
| stack running | ❌ | `pgrep -fl coder` returns no bot process |
| serves this branch | ❌ | nothing deployed; the bot host is a separate machine |
| migrations applied | n/a | no datastore (design § Database) |
| data fresh | n/a | no seedable data layer |

Credentials are **not** the gap: `.env` holds both `FEISHU_APP_ID` and `FEISHU_APP_SECRET`. Two other
things block a live pass, and neither is mine to resolve unilaterally:

1. **The acceptance instrument is a human.** Every AC's *When* is a person pasting an image into a
   Feishu chat. No API drives that.
2. **Starting the bot is an outward-facing act.** It would connect to the live Feishu workspace and
   answer real messages in real chats, and `bots/coder/src/coder/instance_lock.py` exists because a
   second instance conflicts with the one already running on its host.

## Per-AC results  <!-- Contract -->

Every AC carries the same result and the same reason. The *dev-layer evidence* column records what the
build's integration tests already assert — that is `role-dev`'s layer and the reviewer's gate, cited
here as context, **not** as acceptance verification.

### AC-1: A pasted image is carried by the next message
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_1_a_pasted_image_is_carried_by_the_next_message`,
  `int_AC_1_held_images_reach_the_prompt` (`bots/coder/tests/test_coder_main.py`) assert the prompt
  carries the absolute path. **They cannot assert the thing AC-1 actually claims** — that the agent
  reads the image and the reply reflects its content. This is the design's flagged risk and it is
  precisely what a live pass exists to settle.

### AC-2: An image and its caption in one message are used together
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_2_an_image_and_its_caption_are_used_together` covers the `post`
  parse and callback fan-out against a synthetic event, not a real Feishu payload.

### AC-3: Receipt is acknowledged without adding a chat message
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_3_receipt_is_acknowledged_with_a_reaction` and
  `int_AC_3_a_bare_image_is_acknowledged_with_no_reply_or_turn` assert the call is made with
  `ACK_EMOJI`. **Whether `"EYES"` is a valid Feishu `emoji_type` is unverified** — if it is not, the
  reaction fails and the acknowledgement silently never appears. Only a live call proves it.

### AC-4: Plain text is unaffected when nothing is held
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_4_plain_text_is_unchanged_when_nothing_is_held` and
  `int_AC_4_ack_is_unchanged_with_no_attachments`. The strongest of the fourteen at the dev layer,
  since its observable is a pure function of the prompt and ack builders.

### AC-5: An expired image is not attached, and the user is told
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_5_expired_hold_is_dropped_and_reported` (injected clock) and
  `int_AC_5_expiry_warning_reaches_the_user`. The 10-minute wall-clock path is untested live.

### AC-6: Beyond the cap, the newest images win and the drop is visible
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_6_beyond_the_cap_the_newest_win_and_the_drop_is_reported`,
  `int_AC_6_downloads_are_capped_per_message`, `int_AC_6_cap_warning_reaches_the_user`.

### AC-7: An oversized image is rejected on receipt
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_7_an_image_over_the_cap_is_rejected` and
  `int_AC_7_an_oversized_image_is_reported_and_nothing_held`. **The 10 MB threshold itself is an open
  question** — whether it sits at or below Feishu's real ceiling is unverified, so a live pass may
  find the cap rejects images Feishu would have delivered.

### AC-8: A failed download is reported, not swallowed
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_8_a_failed_download_is_reported_distinctly` and
  `int_AC_8_a_failed_download_is_reported_and_nothing_held`, both against a mocked error response.

### AC-9: One member's image never reaches another member's prompt
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_9_one_members_image_never_reaches_another` and
  `int_AC_9_another_members_message_carries_nothing`. A two-human group chat is the real test.

### AC-10: A received image never enters the project repository
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_10_default_root_is_outside_any_project_tree` and
  `int_AC_10_attachments_live_outside_every_project_tree` assert the structural guarantee. A live
  pass on an `auto_git` project with a real push is what would confirm it end to end.

### AC-11: A held image is used once
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_11_held_image_is_attached_once`.

### AC-12: A non-image attachment changes nothing
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_12_a_non_image_attachment_changes_nothing` across `file`, `audio`,
  `media` and `sticker` synthetic events.

### AC-13: Retained images are cleaned up
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_13_purge_deletes_every_held_file`,
  `int_AC_13_closing_a_session_purges_its_attachments`.

### AC-14: Every receipt is recorded without its content
- **Result**: ⏸ blocked
- **Test executed**: none
- **Evidence**: dev-layer `int_AC_14_an_accepted_receipt_is_recorded`,
  `int_AC_14_a_rejected_receipt_records_why`, `int_AC_14_the_log_never_carries_the_bytes`.

## Defects filed  <!-- Contract -->

| ID | AC | Severity | Description | Status |
|----|----|----------|-------------|--------|

None. Nothing failed, and a blocked AC never gets a defect record.

## Blocked  <!-- Contract -->

- **AC-1 … AC-14 (all fourteen)**: no acceptance environment. Clearing it needs (a) the bot running on
  its host from branch `feature/messaging-image-input`, and (b) a human pasting images in a test chat
  while the AC checklist is walked. **Owner: user.** The receipt log lines (`attachment accepted`,
  `attachment rejected:<reason>`, `ack_ms=`) were built to make that walkthrough checkable from logs.
- **Structural gap, owner: `role-system-architect`.** ADR-0008 declined an E2E framework on the
  grounds of "no UI surface". This feature shows the premise is incomplete: there is no UI, but there
  *is* a user-facing surface (the chat), and it now has fourteen ACs with no automated acceptance
  layer. A Feishu-transport test double would make ACs 2–14 automatable; only AC-1 genuinely needs a
  live model. That is an ADR-level decision, not a feature call.

## Non-functional ACs  <!-- Contract -->

| AC | Verification method | Evidence (path or excerpt) | Result |
|----|---------------------|----------------------------|--------|
| Spec NFR: ack observable within 5 seconds | live paste, read `ack_ms=` from the receipt log | not gathered — no live run | ⏸ blocked |
| Spec NFR: receiving must not block other chats | live concurrent paste across two chats | `int_..._attachment_work_is_offloaded_not_run_on_the_websocket_thread` proves the offload structurally, not under load | ⏸ blocked |
| Spec NFR: bounded disk growth | inspect `~/.claude-workspace/attachments/` after a session sweep | not gathered — no live run | ⏸ blocked |

## Visual pass  <!-- Contract -->

`n/a — no UI built in this feature.` The bot renders no surface of its own; Feishu's client renders
everything, and the only user-visible strings are the reply texts asserted verbatim at the dev layer.

## Self-review  <!-- Contract -->

`n/a — no tests were authored in this stage.` The flip probe requires a green baseline to flip
against, and level 1 never ran. Filling this table with ✅s would be the verdict-dishonesty the
process exists to prevent.

## Coverage notes  <!-- Context -->

- **Out-of-AC probes run**: none.
- **Out-of-AC risks NOT probed** (and why):
  - **Prompt injection via image content** — the design accepts this as residual risk
    (§ Security → Elevation of privilege). Untested, and no AC asserts it.
  - **A real Feishu `post` payload's shape** — every `post` test uses a synthetic envelope built from
    the documented shape. If Feishu nests rich text differently in practice, AC-2 breaks and no
    dev-layer test would notice. **This is the highest-value thing a live pass would catch.**
  - **Concurrent pastes from the same sender** — `AttachmentStore` is documented as not thread-safe
    and relies on the single-writer loop; not probed.

## Sign-off  <!-- Contract -->

- Tester: Claude (agent)
- **Verdict**: `blocked`
