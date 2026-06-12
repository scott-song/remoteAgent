# ADR-0005: Persist session metadata as file-based JSON

**Status:** Proposed
**Supersedes:** —
**Superseded by:** —

## Context

Users resume Claude sessions across bot restarts and from different chats, so the bot must durably store — per (user, project) — the Claude `session_id`, a summary, and last-active time, so `/resume` and auto-resume work. Live `ClaudeSDKClient` objects (per ADR-0004) stay in memory; only the lightweight metadata needs durability. Deployment is single-host (one operator's machine), so there is no cross-node consistency requirement. The current implementation writes `~/.claude-workspace/sessions.json`. A `sessions`-module decision.

## Decision

We will persist session metadata as a **single JSON file at `~/.claude-workspace/sessions.json`**, keyed by `<user_id>::<project>`, capped to the most recent N entries per key. Live SDK clients remain in-memory only and are not persisted.

## Alternatives considered

- **SQLite** — attractive: transactional, queryable, still file-based / zero-ops. Rejected: overkill for a small, append-mostly key→list map; adds schema/migration surface; no query needs today.
- **A networked datastore** (Postgres/Redis) — attractive: multi-host, concurrency-safe. Rejected: single-host deployment has no need; adds a service to operate, contradicting the "one process, no server" design.
- **No persistence (in-memory only)** — attractive: simplest. Rejected: sessions would not survive restarts; `/resume` from another machine/day is a core feature.

## Consequences

**Easier (positive consequences):**
- Zero ops; human-readable; trivially backed up and inspected; survives restarts.
- Lives in user home, not the repo.

**Harder (costs / negative consequences):**
- Not safe for concurrent multi-process writers (fine for one process).
- Whole-file read/write doesn't scale to huge histories (mitigated by the per-key cap).
- No query/index; the file location is undocumented for users.

**To revisit when:**
- Deployment becomes multi-host or multi-process, OR
- a single user's history regularly exceeds a few thousand entries, OR
- we need to query sessions across users.

## References

- `core/src/core/session_manager.py` (`HISTORY_FILE`, `save_to_history`).
- Related: ADR-0004 (live clients held in memory).
