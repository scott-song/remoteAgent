# Review: messaging/image-input

> Reviewer: implementation-reviewer subagent · Verdict: NEEDS CHANGES
> Round: 1 · Reviewed at: 3211aa8a7c9690cd61bffc8d3852fe0bf62d6bc9

> **Already merged.** The dispatcher merged before review, so this diff is on `main`. Every
> Required-changes row below is a **follow-up commit**, not a blocked merge — this review cannot and
> does not gate anything. `sdlc-stage-clock` produced no output on this host; the stage-timing
> diagnostic was skipped (noted once).

## Summary

The chain is complete and green at both layers, the dev suite passes 389/389 here, and the design's
two sharpest commitments hold: the receive path really is offloaded off the WebSocket callback
thread, and the code did **not** drift toward the base64 content-block alternative the design's
*Trade-offs* rejected. NEEDS CHANGES rests on five Important findings, none of which the suites could
have caught: a paste-then-type race that silently omits the image from the turn the user meant it for
(F-1), the reaction call shipping without the retries the design budgeted (F-2), AC-14's size not
recorded on the rejection path (F-3), T2's mandated `ACK_EMOJI` verification closed without being
performed (F-4), and images downloaded and held for the HR bot with no reclamation path (F-5).

## 1. Freshness

- **Upstreams approved** ✅ — `sdlc-review-facts`: `spec_status=approved · design_status=approved ·
  plan_status=approved`, `tasks_total=7 tasks_open=0`, `report_signoff=passed`.
- **Chain fresh** ✅ — `sdlc-freshness --only messaging/image-input`: `fresh 4 · DRIFTED 0 ·
  unresolvable 0 · unstamped 0`. No design organised around a superseded AC.
- **Report about THIS code** ✅ **by hand** — the script reported `code_moved=1 · report_at_head=false
  · blockers=report_at_head · verdict=blocked`. Resolved rather than routed: the only non-`docs`
  change since the report's stamp is an **uncommitted** `.claude/settings.json` marketplace-config
  edit, unrelated to this feature. `git diff --name-only 9e0ce9f HEAD -- . ':!docs'` is **empty** —
  the feature code the tester signed off on is byte-identical to the code reviewed here. Not routed
  to `/sdlc-test`.
- **`sdlc-audit-facts` `verdict=discrepancies`** ✅ **resolved by hand** — the two
  `evidence_missing=` rows (`sessions.json`, `test_attachments.py`) are bare filenames in prose, not
  missing artifacts: `core/tests/test_attachments.py` exists, and `sessions.json` is the runtime file
  at `core/src/core/session_manager.py:23`, never a repo artifact. Every gating field is clean:
  `ac_no_integration=` · `ac_no_e2e=` · `ac_not_in_matrix=` · `ac_not_in_report=` ·
  `report_not_passing=` all empty.
- **Known limitation, not assumed green** — the build's **security gate was NOT run**: no scanner is
  configured in this project (no bandit / semgrep / pip-audit in `pyproject.toml`, `Makefile` or
  `ci.yml`), recorded in the plan's *Build record* and flagged for an ADR. This feature parses
  external input and writes externally-supplied bytes to disk, so the gate is material. Recorded as
  an unverifiable gate — **not** treated as passing, and not raised as a new finding.

## 2. Completeness — the chain, then the suites

14/14 ACs carry both an integration and an E2E test; every matrix row reads ✅ and every report
verdict reads ✅ pass. Condensed (the matrix is the script, not re-derived here):

| AC | Tasks | Tests (integration · E2E) | Recorded result |
|---|---|---|---|
| AC-1 | T1, T5 — `[x]` | `int_AC_1_*` ×2 · `e2e_AC_1_*` (+ real-model harness probe) | ✅ green |
| AC-2 | T3 — `[x]` | `int_AC_2_*` · `e2e_AC_2_*` | ✅ green |
| AC-3 | T2, T3 — `[x]` | `int_AC_3_*` ×2 · `e2e_AC_3_*` | ✅ green (live emoji unverified — F-4) |
| AC-4 | T5 — `[x]` | `int_AC_4_*` ×2 · `e2e_AC_4_*` | ✅ green |
| AC-5 | T1, T5 — `[x]` | `int_AC_5_*` ×2 · `e2e_AC_5_*` | ✅ green |
| AC-6 | T1, T3, T5 — `[x]` | `int_AC_6_*` ×3 · `e2e_AC_6_*` | ✅ green |
| AC-7 | T2 — `[x]` | `int_AC_7_*` ×2 · `e2e_AC_7_*` | ✅ green |
| AC-8 | T2, T3 — `[x]` | `int_AC_8_*` ×2 · `e2e_AC_8_*` | ✅ green |
| AC-9 | T1, T5 — `[x]` | `int_AC_9_*` ×2 · `e2e_AC_9_*` | ✅ green |
| AC-10 | T1, T5 — `[x]` | `int_AC_10_*` ×2 · `e2e_AC_10_*` | ✅ green |
| AC-11 | T1 — `[x]` | `int_AC_11_*` · `e2e_AC_11_*` | ✅ green |
| AC-12 | T3 — `[x]` | `int_AC_12_*` · `e2e_AC_12_*` | ✅ green |
| AC-13 | T1, T6 — `[x]` | `int_AC_13_*` ×2 · `e2e_AC_13_*` | ✅ green |
| AC-14 | T7 — `[x]` | `int_AC_14_*` ×3 · `e2e_AC_14_*` | ✅ green (size gap on rejection — F-3) |

Three spec NFRs are non-functional and satisfied via the report's *Non-functional ACs* table with
method and evidence named — 1 ✅, 2 ⚠ partial (offload proven structurally, never under concurrent
load; disk growth bounded by construction, never soaked). Both partials are honestly labelled.

**Dev-layer suites**: `.venv/bin/python -m pytest core/tests/ bots/coder/tests/ bots/hr/tests/
--ignore=bots/coder/tests/test_e2e_image_input.py` — **389 passed, 0 failed** (6.4 s). Run because
`build_run=stale`, which is the *ordinary* reading here: the tester's spec commits (`9e0ce9f`,
`4365b21`) land above the dev's gate stamp (`c359600`). The partition excludes only the tester's E2E
file, which I never execute. `make lint` → **All checks passed**. `make typecheck` → **Success: no
issues found in 21 source files**. No suppression appears anywhere in the diff — no `noqa`, no
`# type: ignore`, no `pragma: no cover`, no `skip`/`xfail`.
**E2E**: `trusted: tester run @ 9e0ce9f` — 14 tests, 2.5 s; 389 + 14 = the report's 403. The
reviewer never executes E2E.

## 3. Code review

### A. Implementation correctness (vs the design)

- **Backend API — signatures** ✅ `download_resource` returns `tuple[bytes | None, str | None]` with
  `"too_large"` / `"failed"` distinguishable (`feishu_client.py:509-556`), matching the design's
  revised snippet and the plan's recorded divergence; it reads `max_bytes + 1` so an oversized image
  is never fully buffered (`:544`). `react` returns `bool` and never escalates to a reply
  (`:574-596`). `OnMessage` widened to six parameters exactly as designed (`:145-151`).
- **Backend API — the rejected alternative** ✅ **no drift.** `grep` for `base64`/`b64`/
  `content_block`/`image_url`/`AsyncIterable` across `core/src` and `bots/*/src` returns **nothing**;
  `query()` still takes a `str` (`bots/coder/src/coder/main.py:319`); `_compose_prompt` emits
  `Attached image: <abs path>` lines plus the fixed framing line the design specified
  (`main.py:107-118`). `sdk_client.py`, `security.py` and `git_sync.py` are **untouched** by this
  diff, so `BUILTIN_TOOLS` and the Bash-only hook scope are unchanged as the design promised.
- **Performance / NFR-1 — the offload really works** ✅, with the honest boundary stated. `_on_event`
  dedups, parses, dispatches via `asyncio.run_coroutine_threadsafe` (`:242`) and returns; nothing
  blocking runs on the lark WebSocket callback thread, and `download_resource` is further pushed to a
  worker via `run_in_executor` (`:278-280`). That is precisely the failure NFR-1 names — one 10 MB
  transfer stalling event delivery for every chat — and it is closed. What the offload does **not**
  do is keep the *bot loop* unblocked: `attachments.put()` (a disk write up to 10 MB) and the
  blocking `reply()` / `react()` REST calls run synchronously on the loop inside
  `_handle_attachments`. I am **not** raising that: it is the project's established idiom, not a
  divergence — `_handle_prompt` and `StreamHandler` already make blocking `feishu.send_message` /
  `update_message` calls straight from loop coroutines (`main.py:305,400,414`,
  `stream_handler.py:67-76`). Pattern-consistent, and the report's ⚠ partial on this NFR is the right
  label.
- **Security — Tampering** ✅ on the load-bearing half. The stored filename is `uuid4().hex` plus an
  extension derived from **sniffed magic bytes**, never Feishu's `file_name`
  (`attachments.py:116-126`), and an unrecognised signature is **rejected**, not stored under a
  fallback name (`:117-122`) — both asserted by `test_stored_name_is_generated_not_caller_supplied`
  and `test_rejects_an_unrecognised_signature`. The `realpath`-containment assert the design's STRIDE
  row also names is **absent** — see F-6; nothing is exploitable today because every path component
  is machine-generated.
- **Security — data classification** ✅ files `0600`, per-pair directories `0700`, both asserted
  (`test_attachments.py:75-79,244-250`). See F-7 for the write-then-chmod window and the umask-default
  intermediate directory.
- **Security — AuthZ by construction** ✅ `take(sender_id, chat_id)` is keyed on the signed event's
  `open_id`, so another member's drain returns empty with no rejection message that would leak the
  paste — the design's stated choice, and `int_AC_9_one_members_image_never_reaches_another`
  (`test_attachments.py:196-207`) is the real guard for it.
- **Audit logging** ✅ `_log_receipt` (`:561-572`) carries disposition, truncated sender, truncated
  chat, size and `message_id`, and `ack_ms=` rides the same line (`:319-324`) so the 5-second budget
  is log-checkable. The truncation to `[:8]` is the design's explicit choice, matching the existing
  `sender_id[:8]` convention — conformant; I note only that 8 characters of an `ou_`-prefixed
  `open_id` leaves ~5 significant characters, which is the design's accepted posture, not a code
  defect. **BR-7 holds**: no logger call anywhere in the diff carries the payload; the deletion and
  write-failure lines log a path, which is not "a copy kept solely for logging". F-3 is the one
  AC-14 clause that does not hold.
- **Idempotency** ✅ the `_seen_ids` dedup stays **upstream** of the download (`:207-217`), so a
  redelivered event neither re-downloads nor re-reacts — asserted by
  `test_duplicate_image_event_is_dropped_before_any_download`.
- **Lifecycle / AC-13** ✅ `purge(user_id, chat_id)` is called unconditionally from
  `SessionManager.close` (`session_manager.py:81-90`), which is the single point `/new`, session end
  and the stale sweep all route through — exactly as T6 designed, and no change to `commands.py` was
  needed.
- **Callback widening across both bots** ✅ verified, not assumed. `grep` finds exactly two
  registrations (`bots/coder/src/coder/main.py:39`, `bots/hr/src/hr/main.py:31`) and two callers
  inside `feishu_client` (`:254`, `:327`), both passing six positional arguments. `HRBot._on_message`
  accepts `_attachments: list | None = None` (`hr/main.py:47-54`) and mypy is clean across 21 source
  files, so nothing else calls the old five-argument shape. The HR bot genuinely still works — the
  problem is what it now *does* with images (F-5).
- **Deliberate divergence, design-covered** ✅ a `post` with text whose image failed to download
  still starts a text-only turn (`:311-329`) rather than aborting. AC-8's literal wording says "no
  agent turn starts", but the design's *Cross-cutting → Failure modes* explicitly rules that "a
  broken attachment path must never abort a turn the user asked for". Conformant; AC-8's tests use a
  bare image, where no turn does start.
- **Divergences raised**: F-2 (`react` retries), F-3 (AC-14 size on rejection), F-6 (containment
  assert), F-7 (directory mode).

### B. Test validity — the dev's tests and the tester's E2E code

**E2E self-review sample:** 6 of the report's named flips traced to their exact assertion lines — all
would red their test. `Attached image:`→`Attached photo:` reds `:238, :266, :279, :350, :383, :438`;
`⏳ Processing...`→`⏳ Working...` reds the equality at `:290`; cap `5`→`4` reds `:350`;
`10 minutes`→`11 minutes` reds `:371`; the reaction-id flip reds `:254`; `attachment accepted`→
`refused` and `ack_ms=`→`ack_us=` red `:408` and `:410`; inverting AC-13's deletion assertion reds
`:392`. **Nothing disproven.** Two honest observations rather than findings: the report's own cell
says "**13 of 13** then-existing tests" while the header says "across all 14", so one of the 14 tests
was added after the probe and the report does not say which — the report discloses this itself rather
than overclaiming, and 16 flips over 14 tests remains arithmetically consistent. And the
`.skip`/`.only`/`xfail` claim checks out: `grep` over the whole diff finds no suppression of any
kind. The one deleted test (`test_non_text_message_ignored`) is recorded in T3's *Notes* with a
reason and a named replacement, and the replacement is genuinely broader —
`int_AC_12_a_non_image_attachment_changes_nothing` loops `file`, `audio`, `media`, `sticker` and
asserts no schedule, no callback, no reply.

| Test | Evidence | Valid? | Why |
|---|---|---|---|
| `int_AC_5/6/9/11/13_*` (`test_attachments.py`) | trusted: `red:` line in T1 *Notes* (29 tests, collection error) | ✅ | AC-9 puts for one sender and drains as another, then re-drains as the first — both halves; AC-6 asserts the oldest is the one dropped and that its file is unlinked |
| `int_AC_7_an_image_over_the_cap_is_rejected` | trusted: `red:` line in T2 *Notes* | ✅ | asserts `(None, "too_large")` at `max_bytes=16`; the read-bound claim is the sibling `test_oversized_payload_is_not_fully_buffered`, not this test (the report cites the pair slightly loosely) |
| `int_..._attachment_work_is_offloaded_not_run_on_the_websocket_thread` | trusted: T3 *Notes*; `test_feishu_client.py:699-711` | ✅ | `download_resource.assert_not_called()` flips the moment the download moves inline — narrow but exactly the property NFR-1 claims |
| `int_AC_14_the_log_never_carries_the_bytes` | `test_feishu_client.py:927-938` | ✅ | embeds the ASCII marker `SECRETPIXELDATA` in the payload and greps `caplog` at DEBUG — a `repr`-style leak would red it. This is the real BR-7 guard |
| `e2e_AC_10_a_received_image_never_enters_the_project_repository` | tester flip row; `test_e2e_image_input.py:416-455` | ✅ | real `git init`, real `git add -A`, asserts `--cached --name-only` empty **and** the path outside the resolved project tree — a store root inside the project would stage the file and red it |
| `e2e_AC_4_plain_text_is_unaffected...` | flip row (`⏳ Working...`) | ✅ | prompt **equality**, not containment, plus exact reply list — the strongest assertion in the file |
| `e2e_AC_14_a_receipt_is_recorded_without_its_content` | mutation thought-experiment (confidentiality AC, named doubt) | ⚠ weak | `payload[:16].hex() not in caplog.text` (`:412`) passes on an implementation that logged raw bytes or their `repr`. Coverage still stands because the integration guard above is strong — F-10 |
| `int_AC_9_another_members_message_carries_nothing` (`test_coder_main.py`) | read the body | ⚠ weak, not invalid | passes `[]` and asserts the ack; nothing was ever `put`, so it would pass even if the store were keyed by chat alone. Its own docstring says as much. AC-9's real integration guard is the `test_attachments.py` test above |
| `int_AC_10_attachments_live_outside_every_project_tree` | read the body | ⚠ weak, not invalid | `tmp_path` can never be under `~/.claude-workspace`, so the first assertion is near-vacuous; the second (`".claude-workspace" in str(ATTACHMENTS_ROOT)`) is a real guard on the constant, and `e2e_AC_10` is the substantive one |
| `Stack.deliver` (`test_e2e_image_input.py:136-153`) | read the body | ✅ for the ACs as written | it captures the offloaded coroutine and **awaits it before returning**, so the store is always settled before the next event. That is why no test at any layer exercises the paste-then-type ordering — F-1 |
| `harness.py` AC-1 colour probe | report quotes the real transcript (`✅ Read <path>` → `Red`) | ✅ as one-off evidence, ✗ as a guard | the run's conclusion stands on the quoted transcript, but the probe prints YES/NO and never asserts, and its matching is loose — F-11 |

### C. Red flags

| ID | Issue | Severity | Evidence (file:line) | Status |
|---|---|---|---|---|
| F-1 | Paste-then-type race: a text message arriving before the offloaded download finishes drains an empty hold, silently omitting the image from the intended turn | Important | `core/src/core/feishu_client.py:242`; `bots/coder/src/coder/main.py:96`; design § Performance → *Where the work runs* | fixed |
| F-2 | `react()` ships with no retry loop, diverging from the design's own latency budget ("plus up to 2 retries × 0.5 s") and from every other outbound call in the file | Important | `core/src/core/feishu_client.py:574-596` vs `:384, :415, :459, :495, :533` | fixed |
| F-3 | AC-14's "and the size" is not recorded on the rejection path — `size=0` is logged for `rejected:too_large` and `rejected:error`, and no test asserts the size on rejection | Important | `core/src/core/feishu_client.py:287, :292-295`; `core/tests/test_feishu_client.py:916-925` | fixed |
| F-4 | T2's mandated `ACK_EMOJI` verification against Feishu's live `emoji_type` set was never performed, yet T2 is `[x]` with no deferral recorded — the plan's risk register names this verification as the mitigation | Important | plan T2 *Notes* + *Risk register*; `core/src/core/attachments.py:37`; test report AC-3 *Caveat* | fixed |
| F-5 | The callback widening made `_on_event` download and hold images for **every** bot, but `HRBot` has no `SessionManager`, never calls `take()` and never calls `purge()` — HR-chat attachments are never reclaimed | Important | `bots/hr/src/hr/main.py:25-31, 47-61`; `core/src/core/feishu_client.py:227-241`; `core/src/core/attachments.py:176` | fixed |
| F-6 | Design divergence: the `realpath`-containment assert the design's STRIDE *Tampering* row names is absent from the store | Suggestion | design § Security → STRIDE *Tampering*; `core/src/core/attachments.py:125-133` | open |
| F-7 | `write_bytes` then `chmod(0o600)` leaves a brief umask-default window; `mkdir(parents=True, mode=0o700)` applies `0700` only to the leaf, so the `attachments` root lands at the umask default the design's *Data classification* row says is `0700` | Suggestion | `core/src/core/attachments.py:128-130` | open |
| F-8 | A magic-byte rejection is reported to the user as AC-8's *"Could not download that image from Feishu. Try sending it again."* — sending them into a retry loop that will fail identically forever (e.g. BMP, HEIC: neither is in `_SIGNATURES`) | Suggestion | `core/src/core/feishu_client.py:300-303`; `core/src/core/attachments.py:43-48`; recorded in the plan's `W4 self-review` and not fixed | open |
| F-9 | The `10 MB` figure is hard-coded in the user-facing string while `IMAGE_MAX_BYTES` is the constant — its sibling warnings in the store derive their numbers from the constants | Suggestion | `core/src/core/feishu_client.py:75` vs `core/src/core/attachments.py:50-53, 171-173` | open |
| F-10 | The E2E AC-14 no-leak assertion checks only a hex-encoded run of the payload and would pass on an implementation that logged the raw bytes | Suggestion | `bots/coder/tests/test_e2e_image_input.py:412` | open |
| F-11 | The harness's AC-1 colour probe cannot guard a regression: `"red"` is substring-matched across the whole transcript, `feishu.sent` is sliced with an index taken from `len(feishu.updated)`, and the probe prints rather than asserts | Suggestion | `bots/coder/tools/harness.py:363, 370-374` | open |
| F-12 | A `post` carrying only text now starts an agent turn where the old `msg_type != "text"` gate dropped it — an unspecified behaviour change, covered by no AC and no test | Suggestion | `core/src/core/feishu_client.py:219`, `:84-95` | open |

## Verdict

**NEEDS CHANGES.** Not because anything upstream is missing — the chain is complete at both layers,
the suites are green, lint and types are clean, and the two design commitments most likely to have
been quietly abandoned (the WebSocket-thread offload and the path-reference-over-base64 decision) both
hold under direct inspection. It is NEEDS CHANGES because five Important findings are `open`, and all
five sit in the blind spot the suites share: F-1 is invisible because the E2E driver awaits the
offloaded coroutine before delivering the next event; F-3 and F-4 are assertions and verifications
that were specified and then not made; F-2 and F-5 are consequences of the widening that the design's
own *Consumers* and *Latency budget* sections assumed away. None is a PASS-with-nits: each changes
what a reader would conclude about behaviour in production. Since the work is already merged and
pushed, these are follow-up commits on `main`, and the disposition of each row — fix, or "will not
fix" — is the user's.

## Required changes (NEEDS CHANGES)

| ID | Finding | Severity | Chance (trigger) | Impact (blast · recovery) | Evidence | Fix | Route | Status |
|---|---|---|---|---|---|---|---|---|
| F-1 | A text message arriving before the offloaded download finishes drains an empty hold; the image is silently omitted from the intended turn and then attaches to the user's *next*, unrelated message | Important | medium-high — paste-then-immediately-type is the flow the spec's *Goals* name ("image and text arriving as two separate messages … without the user having to know"); the design budgets the download at <500 ms typical, 1–3 s at the cap | medium · the intended turn answers about nothing, and a later unrelated turn silently carries the stale image for up to the 10-min TTL; visible via the missing count in the ack; recoverable by re-pasting | `feishu_client.py:242` schedules and returns; `main.py:96` drains synchronously with no wait; `test_e2e_image_input.py:149-153` awaits the offload before the next event, which is why nothing catches it | make the drain wait on this sender's in-flight receives (a per-`(sender, chat)` pending set awaited in `_on_message`, or a bounded grace wait). The mechanism is a design decision — record it in the design's *Open questions* rather than choosing it in code alone | dev | fixed |
| F-2 | `react()` makes a single un-retried REST call, so one transient failure means AC-3's acknowledgement never appears — WARNING log only, by design no reply | Important | medium — every other outbound call in this file wraps `UPDATE_MAX_RETRIES` precisely because these calls do fail transiently; the design's *Latency budget* itself allots "up to 2 retries × 0.5 s" to this call | medium · the user's only signal that the paste landed is lost, so they re-paste and the next prompt carries two copies of one image (and double vision-token cost) · recoverable but confusing | `feishu_client.py:574-596` (no loop) against `:384, :415, :459, :495, :533` | wrap `message_reaction.create` in the existing `UPDATE_MAX_RETRIES` / `UPDATE_RETRY_DELAY` loop, as the design's budget assumed; keep the never-escalate-to-a-reply rule | dev | fixed |
| F-3 | AC-14 requires the size on **rejection** as well as acceptance; the audit line logs `size=0` for `rejected:too_large` and `rejected:error` — the one rejection where the size *is* the reason | Important | high — every oversized or errored receipt | low · the audit record misstates the size, though the disposition still explains the rejection · fixed forward, no data loss | `feishu_client.py:287, :292-295`; `int_AC_14_a_rejected_receipt_records_why` (`test_feishu_client.py:916-925`) asserts only the disposition | have `download_resource` return the observed byte count with `"too_large"` (it already knows `len(data) > max_bytes`) and log it; extend the rejection test to assert the size, and tighten the accepted-path test from the bare substring `"32"` to `size=32` | dev | fixed |
| F-4 | T2 is `[x]` but its mandated step — "Verify the emoji value against the live API as part of this task and record the confirmed value" — was not performed, and no deferral is recorded | Important | unknown until a live pass; the tester names it "the single most likely live failure" | medium · if `"EYES"` is not in Feishu's `emoji_type` enum, AC-3 never works in production and the receipt signal silently never appears · one-line fix once observed | plan T2 *Notes* (no confirmed value) + *Risk register* ("Mitigation: verify the emoji in T2"); `attachments.py:37`; report AC-3 *Caveat* | verify against the live API and record the confirmed value on T2 — or, if no live access exists, record the deferral explicitly on T2 and in the design's *Open questions* with an owner, so the task no longer claims a verification it did not do | dev | fixed |
| F-5 | Widening `_on_event` made **every** bot download, write and hold images; `HRBot` has no `SessionManager`, so `take()` and `purge()` are never called and HR-chat attachments are never reclaimed — plus HR now reacts EYES to bare images, behaviour it never had | Important | low — `bots/hr` is a placeholder; needs someone to run it and paste an image | medium · up to `MAX_ATTACHMENTS × IMAGE_MAX_BYTES` = 50 MB per pasting `(sender, chat)` pair, retained for the process lifetime with no reclamation path — against the spec's "must not grow without bound on the host" · recoverable only by deleting the directory by hand | `bots/hr/src/hr/main.py:25-31, 47-61` (no `SessionManager`, no purge); `feishu_client.py:227-241`; `attachments.py:176` | give `FeishuClient` an opt-in for the attachment path (a constructor flag or an injectable store, defaulting off) so a bot that ignores images does not accumulate them — and record the two-consumer consequence in the design's *Consumers* section, which analysed only the signature | dev | fixed |

Suggestions F-6 … F-12 are listed in section C with the same evidence and are not repeated here;
they do not gate the verdict and are the user's to take or decline.

## What to fix next

1. **F-1 (dev)** — `core/src/core/feishu_client.py:242` + `bots/coder/src/coder/main.py:96`: make the
   drain wait on this sender's in-flight receives, and record the chosen mechanism in
   `docs/sdlc/designs/messaging/image-input.md` § *Open questions*. Add an E2E that delivers the text
   event **before** awaiting the offloaded coroutine — the current `Stack.deliver` cannot express the
   ordering. Touches AC-1 and the spec's *Goals*.
2. **F-2 (dev)** — `core/src/core/feishu_client.py:574-596`: wrap the reaction in the existing
   `UPDATE_MAX_RETRIES` / `UPDATE_RETRY_DELAY` loop. Touches AC-3.
3. **F-3 (dev)** — `core/src/core/feishu_client.py:287, :292-295` and
   `core/tests/test_feishu_client.py:916-925`: carry the observed size into the rejection audit line
   and assert it. Touches AC-14.
4. **F-4 (dev)** — `docs/sdlc/plans/messaging/image-input.md` T2 and `core/src/core/attachments.py:37`:
   verify `ACK_EMOJI` live, or record the deferral with an owner. Touches AC-3.
5. **F-5 (dev)** — `core/src/core/feishu_client.py:227-241` and `bots/hr/src/hr/main.py`: make the
   attachment path opt-in per consumer, and update the design's *Consumers* section. Touches BR-5 and
   the spec's bounded-growth NFR.
6. **F-10, F-11 (tester)** — `bots/coder/tests/test_e2e_image_input.py:412` (assert against an ASCII
   marker in the payload, as the integration test does) and `bots/coder/tools/harness.py:363, 370-374`
   (word-boundary match on the final reply only; separate slice indices for `updated` and `sent`;
   assert rather than print).
7. **F-6 … F-9, F-12 (dev)** — Suggestions; take or decline per row in section C.

## History

Round 1 — n/a.

## Disposition (round 1)

Recorded per `playbooks/shared/finding-disposition.md`. The user chose **fix all five Important,
carry the Suggestions**, on 2026-08-26.

| ID | Status | How |
|---|---|---|
| F-1 | **fixed** | `FeishuClient` tracks in-flight receives per `(sender, chat)`; a text message from a sender with a pending receive is delivered behind it on the bot loop. A failed receive never withholds the text, and with nothing in flight the direct path is untouched (AC-4 unchanged). Mechanism recorded in the design's *Performance* section as the reviewer asked. Proven by removing the guard: `int_AC_1_text_waits_for_an_in_flight_receive` fails with *"the text was delivered before the image was held"*, and passes with it restored. |
| F-2 | **fixed** | `react()` now wraps `message_reaction.create` in the existing `UPDATE_MAX_RETRIES` / `UPDATE_RETRY_DELAY` loop; the never-escalate-to-a-reply rule is kept and asserted. |
| F-3 | **fixed** | `download_resource` returns the observed byte count as a third element, and the audit line logs it on rejection. The accepted-path assertion tightened from the bare substring `"32"` to `size=32`, and a new test asserts `size=11534336` on `rejected:too_large`. |
| F-4 | **fixed (as a recorded deferral, not a verification)** | The reviewer was right that this was an artifact overstating what happened. T2's *Notes* now say the mandated `ACK_EMOJI` check was **not** performed and why; the design's *Open questions* carries it as an explicit deferral owned by the user, to be settled at the first live Feishu run; the plan's risk register records that its own named mitigation did not happen. No verification is claimed. |
| F-5 | **fixed** | The attachment path is opt-in: `FeishuClient(..., accept_attachments=False)` by default, and only the coder bot — which drains on every message and purges on session close — enables it. A bot that opts out still receives the **text** of a captioned `post`. The two-consumer consequence is now in the design's *Consumers* section, which had analysed only the signature. |
| F-6 … F-12 | **carried, open** | Suggestions, by the user's decision. They ship as known nits and are not accepted (not "will not fix") — `role-dev` batches them before the build is called complete. Expect them re-raised next round; that is the status working as intended. |

Gates after the fixes, at the tree these were landed on: suite **412/412**, coverage **95%**,
`make typecheck` clean, `ruff check` and `ruff format` clean.
