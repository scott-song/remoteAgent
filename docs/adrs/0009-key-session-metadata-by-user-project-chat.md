# ADR-0009: Key session metadata by (user, project, chat)

**Status:** Accepted (2026-07-01)
**Supersedes:** ADR-0005
**Superseded by:** —

## Context

ADR-0005 persists session metadata as a single JSON file at `~/.claude-workspace/sessions.json`, keyed by `<user_id>::<project>`. That key is chat-agnostic: a user working from two different Feishu group chats bound to the same project shared **one** Claude session — context from one chat leaked into the other, and both chats' prompts serialized on a single session lock. ADR-0005's own Context assumed this was acceptable ("resume ... from different chats ... per (user, project)").

The `sessions/per-chat-isolation` feature (spec/design/plan/build/test all merged to `main`, 6/6 ACs passing, test-review PASS) reversed that assumption: each chat is now an independent conversation. The shipped code keys live sessions by `<user_id>:<project>:<chat_id>` and persisted history by `<user_id>::<project>::<chat_id>`. Legacy entries written under the old two-segment key are intentionally not migrated (a "fresh start" — resolved OQ-2 in the spec): they are ignored for `/resume` without erroring, and pre-change sessions are not auto-resumable.

The **persistence mechanism** ADR-0005 chose — a single human-readable JSON file, capped to the most recent N entries per key, live SDK clients in memory only — is unchanged and still correct. Only the **key** changed (a chat segment was added) plus the fresh-start consequence. Because ADR-0005 is `Accepted` (immutable) and states both the mechanism and the now-false key in one Decision sentence, this ADR supersedes it in full rather than editing it, restating the still-valid mechanism and correcting the key.

**Why now?** Shipped, tested code contradicts an `Accepted` ADR and the `CLAUDE.md` invariant ("Sessions are keyed `(user, project)`, not by chat"). The governing record must match reality before the next feature reads a stale invariant.

Tech preference bearing on this decision: `docs/preferences/tech-preferences.md` → Auth → *"Session model: file-persisted Claude `session_id`, keyed per (user, project), with resume (ADR-0005)"* — now stale; must be updated on acceptance.

## Decision

We will persist session metadata as a **single JSON file at `~/.claude-workspace/sessions.json`** (mechanism unchanged from ADR-0005), keyed by **`<user_id>::<project>::<chat_id>`**, capped to the most recent N entries per key. Live `ClaudeSDKClient` objects remain in memory only and are not persisted. Legacy entries keyed `<user_id>::<project>` (written before this change) are **not migrated** — they are ignored for resume without error, and pre-change sessions are not auto-resumable.

Note: deviates from the stated tech preference (`Session model: keyed per (user, project)`) — see Consequences → Harder. The preference line is itself a stale reference to ADR-0005 and is corrected on acceptance.

## Alternatives considered

- **Narrow keying-only ADR** (leave ADR-0005 as the authority on the JSON-file mechanism, scope this ADR to the key tuple only) — attractive: smaller record, avoids restating the unchanged mechanism. Rejected: ADR-0005's single Decision sentence bundles mechanism *and* key, so a partial supersession leaves that sentence half-true with no clean `Superseded by` — two ADRs would ambiguously govern the same statement.
- **Amend ADR-0005 in place** (edit its Decision line, add an amendment note) — attractive: cheapest, one file. Rejected: `Accepted` ADRs are immutable in this process; editing one loses the decision-history trail and violates the supersession discipline (a documented red flag).
- **Keep `(user, project)` keying** (status quo per ADR-0005 and tech-preferences) — attractive: no change, matches the stated preference. Rejected: the shared-session-across-chats behavior is exactly the bug `per-chat-isolation` fixed; this option is contradicted by shipped, tested, reviewed behavior on `main`.

## Consequences

**Easier (positive consequences):**
- Two chats for the same user+project run independent Claude sessions — separate context and separate concurrency (the intended fix).
- Single-chat usage is unchanged; the common case does not regress.
- Session identity is observable and testable directly from the key; lifecycle commands (`/new`, `/stop`, `/status`) and stale cleanup act per-chat.
- Inherits ADR-0005's operational wins unchanged: zero ops, human-readable, survives restarts, per-key cap.

**Harder (costs / negative consequences):**
- **Deviates from the stated tech preference** (`Session model: keyed per (user, project)`). Reason for deviation: that preference line simply mirrors the now-superseded ADR-0005; the deviation is the whole point of the feature. Cost: the preference file must be updated on acceptance or it will mislead future ADR authoring.
- Legacy `<user_id>::<project>` history is orphaned — old session history is not carried forward and pre-change sessions are not auto-resumable (accepted "fresh start" trade-off, spec OQ-2).
- Key cardinality grows: one entry set per (user × project × chat) instead of per (user × project). The per-key cap still bounds entries *within* a key, but the total file grows with the number of distinct chats — bringing ADR-0005's single-file scale limit closer.
- The code field carrying the project segment is historically named `bot_name` (`Session.bot_name`), populated with `project_name` at call sites — a naming misnomer, not a behavior difference. Minor tech debt; the persisted key is semantically `user::project::chat`.

**To revisit when:**
- Cross-chat session sharing/merge becomes a requested feature (currently a deferred non-goal), OR
- the distinct-key count makes the single JSON file unwieldy (folds into ADR-0005's original triggers: multi-host/multi-process deployment, or a single file growing beyond a few thousand entries), OR
- migrating legacy pre-chat history into per-chat keys becomes required, OR
- the `docs/preferences/tech-preferences.md` session-model entry changes.

## References

- Supersedes ADR-0005 (file-based JSON persistence; original `<user_id>::<project>` key).
- Feature: `docs/sdlc/specs/sessions/per-chat-isolation.md` (resolved OQ-1 per-chat resume, OQ-2 fresh start), design/plan/test-report/test-review under `docs/sdlc/*/sessions/per-chat-isolation.md`.
- Code: `core/src/core/session_manager.py` (`Session.key`, `_history_key`); call sites pass `project_name` into the `Session.bot_name` field (`bots/coder/src/coder/main.py`, `commands.py`).
- Related: ADR-0004 (live clients held in memory).
