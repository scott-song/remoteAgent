# Implementation plan: messaging/image-input

> Owner: Planner → Dev (live updates) · Status: approved
> Spec: `docs/sdlc/specs/messaging/image-input.md` · Spec version targeted: `h1:b82962101050`
> Design: `docs/sdlc/designs/messaging/image-input.md` · Design version targeted: `h1:3cb3e392ea6d`

## Approach  <!-- Context -->

Build outward from the contract: the attachment store lands first because it owns every constant and
every rule (TTL, cap, single-use, storage root) that the other six tasks import rather than restate.
Then the two Feishu calls, then the widened event path, then the two bots. One commit per task on
`feature/messaging-image-input`, one PR at the end; no feature flag, per the design's rollout decision.
The one hard sequencing constraint is that the callback-widening task and both bot-update tasks must
land together in the same PR — see the risk register.

## Execution waves  <!-- Contract -->

| Wave | Tasks | `Files:` disjoint? | Concurrency-safe |
|---|---|---|---|
| Wave 1 | T1 | yes (single task) | **yes** |
| Wave 2 | T2, T6 | yes — `feishu_client.py` vs `session_manager.py` | **yes** |
| Wave 3 | T3 | yes (single task) | **yes** |
| Wave 4 | T4, T5, T7 | yes — `bots/hr/` vs `bots/coder/` vs `core/` | **yes** |

## Tasks  <!-- Contract -->

### T1 — Add the attachment store with its constants and rules

- **Status**: `[x]`
- **Depends**: none
- **Files**: `core/src/core/attachments.py` (new), `core/tests/test_attachments.py` (new)
- **Design**: `§ Architecture → New module` (the `AttachmentStore` contract) · `§ Security → Data classification`
- **Covers**: AC-5 (partial — warning surfaced by T5), AC-6 (partial — per-message cap in T3, warning in T5), AC-9 (partial — completed by T5), AC-10 (partial — completed by T5), AC-11 (full), AC-13 (partial — wiring in T6)
- **Risk**: low
- **Notes**: `red: ModuleNotFoundError: No module named 'core.attachments'` (29 tests, collection error before implementation). `put` sniffs magic bytes and **rejects** an unrecognised signature rather than storing under a fallback name; the stored filename is a generated `uuid4`, never Feishu's `file_name` (`§ Security → Tampering`). Write files `0600`, directories `0700`. Storage root `~/.claude-workspace/attachments/<sha256(sender:chat)[:16]>/` — outside every `project_dir`, which is the whole of AC-10. Expose a module-level default store instance so `session_manager` can import it without a constructor-injection refactor. `take` returns `(attachments, warnings)` so no caller re-derives expiry or cap rules. Owns `IMAGE_MAX_BYTES`, `MAX_ATTACHMENTS`, `HOLD_TTL_SECONDS`, `ACK_EMOJI`, `ACCEPTED_MSG_TYPES`.

### T2 — Add the two outbound Feishu calls: resource download and reaction

- **Status**: `[x]`
- **Depends**: T1 — imports `IMAGE_MAX_BYTES` and `ACK_EMOJI`
- **Files**: `core/src/core/feishu_client.py`, `core/tests/test_feishu_client.py`
- **Design**: `§ Backend API` (both signature snippets, the error table)
- **Covers**: AC-3 (partial — the bare-image branch is T3), AC-7 (full), AC-8 (partial — the reply is T3)
- **Risk**: medium — `ACK_EMOJI = "EYES"` is unverified against Feishu's `emoji_type` set; an invalid value makes AC-3's acknowledgement silently never appear.
- **Notes**: `red: AttributeError: 'FeishuClient' object has no attribute 'react'` (10 new tests failing before implementation). **Design divergence, corrected in the design in this step**: `download_resource` returns `tuple[bytes | None, str | None]`, not `bytes | None` — AC-7 and AC-8 carry different replies, so oversize and failure must stay distinguishable at the call boundary. `download_resource` reads at most `max_bytes + 1` so an oversized image is never fully buffered (AC-7), and returns `None` as the single failure signal (AC-8). Reuse the existing `UPDATE_MAX_RETRIES` / `UPDATE_RETRY_DELAY` loop — do not invent a second retry policy. `react` returns `bool` and **never** escalates a failure to a chat reply, because AC-3 forbids a message. Verify the emoji value against the live API as part of this task and record the confirmed value.

### T3 — Widen the event path to carry attachments

- **Status**: `[x]`
- **Depends**: T1, T2 — needs the store and both calls
- **Files**: `core/src/core/feishu_client.py`, `core/tests/test_feishu_client.py`
- **Design**: `§ Architecture` (the flow diagram) · `§ Backend API → widened callback contract` · `§ Performance → Where the work runs`
- **Covers**: AC-2 (full), AC-3 (full — completes T2), AC-6 (partial — the per-message download cap), AC-8 (full — completes T2), AC-12 (full)
- **Risk**: high — this is the breaking signature change; it cannot land without T4 (see risk register).
- **Notes**: `red: AttributeError: 'FeishuClient' object has no attribute '_handle_attachments'` (11 tests). Two legacy tests changed per the case table: `test_valid_text_triggers_callback` **modified** (the callback gained its trailing `[]`), `test_non_text_message_ignored` **deleted** — an `image` message is no longer ignored, so its assertion became wrong rather than stale, and the surviving behaviour is covered by `test_int_AC_12_a_non_image_attachment_changes_nothing`. Blocking downloads run via `run_in_executor` so neither the WS thread nor the bot loop stalls. replace the `msg_type != "text"` early return at `feishu_client.py:158` with the `ACCEPTED_MSG_TYPES` allowlist; everything outside it keeps returning silently (AC-12). Extract `image_key` from an `image` message and every embedded image from a `post`, **capping downloads at `MAX_ATTACHMENTS` per message** so one `post` cannot authorise unbounded transfer. Offload the download onto the loop stored at `feishu_client.py:100` via `run_coroutine_threadsafe` — a synchronous download here would stall event delivery for every chat (NFR-1). A message with images **and** text passes attachments straight through; a bare image reacts and returns without invoking the callback (AC-3). The existing `_seen_ids` dedup at `:151-156` must stay **upstream** of the download so a redelivered event neither re-downloads nor re-reacts.

### T4 — Update the HR bot for the widened callback

- **Status**: `[x]`
- **Depends**: T3 — consumes the new callback contract
- **Files**: `bots/hr/src/hr/main.py`, `bots/hr/tests/test_hr_main.py`
- **Design**: `§ Backend API → Consumers`
- **Covers**: infrastructure (no AC) — backwards compatibility
- **Risk**: low
- **Notes**: `red: 2 new tests failed — HRBot._on_message took 5 positional args`. The parameter is **defaulted** (`_attachments: list | None = None`) so an older caller is not broken, which also keeps this task independently revertible. accept and ignore the parameter as `_attachments`, exactly as `_sender_name` is already ignored. `bots/hr/tests/test_hr_main.py:20,29` call `_on_message` directly with five positional args and must be updated in this task, or the suite fails.

### T5 — Attach held images to the coder bot's prompts

- **Status**: `[ ]`
- **Depends**: T1, T3 — needs `take()` and the new callback contract
- **Files**: `bots/coder/src/coder/main.py`, `bots/coder/src/coder/commands.py`
- **Design**: `§ Backend API → the agent-SDK handoff` · `§ Trade-offs` (path reference over base64)
- **Covers**: AC-1 (full), AC-4 (full), AC-5 (full — completes T1), AC-6 (full — completes T1/T3), AC-9 (full — completes T1), AC-10 (full — completes T1)
- **Risk**: medium — AC-1 depends on the agent electing to call `Read` on the referenced path; failure is a confident answer about an unread image, not an exception.
- **Notes**: call `take(sender_id, chat_id)` in `_on_message`, compose the prompt via `_compose_prompt` with one `Attached image: <abs path>` line per attachment, and pass the count plus any warnings into `_prompt_ack` (`commands.py:73`) so the ack reads *"⏳ Processing... (1 image attached)"* — and reads exactly as today when nothing is held (AC-4). `query()` keeps taking a `str`; do not switch to the `AsyncIterable` form. AC-10's guard belongs here as a test: a project with `auto_git` enabled must produce a commit containing no attachment and an unchanged working tree after an image turn.

### T6 — Purge attachments on session end, reset, and stale cleanup

- **Status**: `[x]`
- **Depends**: T1 — calls `purge()`
- **Files**: `core/src/core/session_manager.py`, `core/tests/test_session_manager.py`, `core/tests/test_stream_handler.py`
- **Design**: `§ Architecture → Integrates with` (the two lifecycle exits) · `§ Performance` (lazy reclamation)
- **Covers**: AC-13 (full — completes T1)
- **Risk**: low
- **Notes**: `red: AttributeError — core.session_manager has no attribute 'attachment_store'` (5 tests). Also fixed fallout from T2 that the wave gate caught: `core/tests/test_stream_handler.py:14-27` stubs `lark_oapi.api.im.v1` with only the names `feishu_client` originally imported, so T2's four new imports broke its collection — the stub now lists them. Running that file alone had hidden it. call `purge(session.user_id, session.chat_id)` from `close()` (`:70`) so it covers all three AC-13 triggers at once — `/new` already routes through `close()` via `commands.py:145`, and `cleanup_stale()` (`:80`) calls `close()` per stale session. No change to `commands.py` is needed. Reclamation stays lazy by design: the sweep self-throttles to 300 s and only runs when a message arrives, which the design records as accepted.

### T7 — Record every receipt and the acknowledgement latency

- **Status**: `[ ]`
- **Depends**: T2, T3 — logs their dispositions
- **Files**: `core/src/core/feishu_client.py`, `core/src/core/attachments.py`
- **Design**: `§ Security → Audit logging` · `§ Performance → Observability`
- **Covers**: AC-14 (full)
- **Risk**: low
- **Notes**: one INFO line per accepted or rejected receipt with disposition, truncated `sender_id`, truncated `chat_id`, byte size and `message_id` — and **never** the bytes or a path to a retained copy (BR-7). Add event-receipt → reaction-success elapsed ms to the same line, which is what makes the spec's 5-second budget checkable from logs with no new infrastructure. One line per purge sweep with a count. Use `core.logging_config.get_logger`, never `print()`.

## Risk register  <!-- Context -->

- **The widened callback is a runtime break across two packages** — likelihood high if tasks land
  separately, impact high (the HR bot raises `TypeError` on every message). Mitigation: T3 and T4 ship
  in the same PR, and `make typecheck` is the gate that names both call sites before runtime does.
  Owner: dev.
- **AC-1 rests on the agent choosing to read the path** — likelihood unknown, impact high (a silent
  wrong answer, the only AC whose failure produces no error). Mitigation: the tester exercises AC-1
  against a real image at stage 5; if unreliable, the fallback is the base64 content-block path named
  in the design's *Trade-offs*, which would be a new task, not an edit to T5. Owner: tester → dev.
- **Two constants are unverified** — `ACK_EMOJI` (breaks AC-3 if invalid) and `IMAGE_MAX_BYTES`
  (may sit below Feishu's real ceiling, rejecting images Feishu would have delivered). Likelihood
  medium, impact low-to-medium and both immediately visible. Mitigation: verify the emoji in T2;
  the size cap is the user's open question, resolvable without code change. Owner: dev / user.
- **Coverage gate** — ADR-0008 holds the suite at ≥ 85%; T1 and T3 carry most of the new branches, so
  their tests are where the gate is won or lost. Owner: dev.

## Out-of-band changes  <!-- Context -->

None. Every task traces to an approved AC or to backwards compatibility (T4); the two items the design
deferred — eager reclamation and a per-project `accept_images` toggle — are recorded in the design's
*Open questions* as post-ship, not silently absorbed here.

## Build record  <!-- role-dev writes this during the build — empty at plan time -->

- `W1 self-review @ 76deebd — 2 files · 0 critical, 0 important, 1 suggestion (chmod applied after write_bytes; brief default-perm window)`
- `W3 self-review @ 5cf2a9c — 2 files · 0 critical, 1 important FOUND AND FIXED IN-WAVE (two AC-7/AC-8 assertions read lark's builder output, which test_stream_handler's sys.modules stub turns into a MagicMock — order-dependent; now spy on client.reply)`
- `W2 self-review @ 8e43f60 — 6 files · 1 important FOUND AND FIXED IN-WAVE (test_stream_handler's lark stub broke on T2's new imports), 0 critical, 0 suggestions`

## Revisions  <!-- History -->
