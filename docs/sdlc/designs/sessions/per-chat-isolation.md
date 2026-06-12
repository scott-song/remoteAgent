# Design: sessions/per-chat-isolation

> Owner: Architect · Status: approved · Last updated: 2026-06-12
> Spec: `docs/sdlc/specs/sessions/per-chat-isolation.md` · Targets spec version: 2026-06-12 (commit `fd92f27`)

## Summary

Thread `chat_id` through the session layer so the session identity is `(user, project, chat)` instead of `(user, project)`. This is a localized change: add a `chat_id` field to `Session`, extend `SessionManager` method signatures and the history key with a chat segment, and pass `chat_id` at every call site in `coder/main.py` and `coder/commands.py`. No new modules; persistence mechanism unchanged (ADR-0005).

## System constraints

- **ADR-0005 (file-based JSON sessions)** → the on-disk history key gains a chat segment; the storage format/location is otherwise unchanged. Legacy entries are not migrated (fresh start, resolved OQ-2).

## Component-level design

### `core/src/core/session_manager.py`

- **`Session`**: add field `chat_id: str` (no default; set at construction). Update:
  ```python
  @property
  def key(self) -> str:
      return f"{self.user_id}:{self.bot_name}:{self.chat_id}"
  ```
- **`SessionManager`** — add `chat_id: str` to `get`, `close`; key the in-memory dict by the 3-part key:
  ```python
  def get(self, user_id, bot_name, chat_id): key = f"{user_id}:{bot_name}:{chat_id}"; ...
  async def close(self, user_id, bot_name, chat_id): key = f"{user_id}:{bot_name}:{chat_id}"; ...
  ```
- **History key** gains a chat segment (per-chat resume, resolved OQ-1):
  ```python
  def _history_key(self, user_id, bot_name, chat_id) -> str:
      return f"{user_id}::{bot_name}::{chat_id}"
  ```
  `get_history(user_id, bot_name, chat_id)`, `get_last_session_id(user_id, bot_name, chat_id)` take `chat_id`. **Remove** the legacy `bot_name`-only fallback in `get_history` (fresh start — legacy entries simply don't match, return `[]`, no error → AC-6).
- **`save_to_history(session)`** uses `session.chat_id` for the key (no signature change).
- **`cleanup_stale`** closes via `self.close(s.user_id, s.bot_name, s.chat_id)` (AC-5).

### `bots/coder/src/coder/main.py` and `commands.py`

Pass `chat_id` at every session-manager call site, and set `chat_id=chat_id` when constructing `Session`:
- `main._handle_prompt`: `sessions.get(sender_id, project_name, chat_id)`, `get_last_session_id(sender_id, project_name, chat_id)`, both `Session(...)` constructions add `chat_id=chat_id`.
- `main._stream_response` error path: `sessions.close(session.user_id, session.bot_name, session.chat_id)`.
- `main._do_resume`: `sessions.close(sender_id, project_name, chat_id)`, `Session(..., chat_id=chat_id)`.
- `main._cmd_commit`: `sessions.get(sender_id, project_name, chat_id)`.
- `main.start` shutdown loop: `sessions.close(s.user_id, s.bot_name, s.chat_id)`.
- `commands._cmd_mode` / `_cmd_stop` / `_cmd_status`: `sessions.get(sender_id, project_name, chat_id)`.
- `commands._cmd_new`: `sessions.close(sender_id, project_name, chat_id)`.
- `commands._cmd_resume`: `sessions.get_history(sender_id, project_name, chat_id)` (the listing) — chat available in the method.

All these methods already receive `chat_id` as a parameter, so no plumbing of new arguments through the call chain is needed.

## Trade-offs considered

- Chose **adding `chat_id` to the existing key** over a nested `{(user,project): {chat: session}}` registry because it's the minimal change with one consistent key concept. Cost: every `SessionManager` call gains an argument (touches call sites + the tests that drive them).
- Chose **fresh start** (no legacy migration) per resolved OQ-2 — simplest, and the removed `get_history` fallback also deletes dead complexity. Cost: pre-change session history is not resumable (accepted).

## Cross-cutting concerns

- **Backwards compatibility**: legacy `user::project` history entries become unreachable (fresh start); `get_history` returns `[]` for a new chat rather than erroring (AC-6). No crash, no migration.
- **Failure modes**: none new — the key is a pure function of three strings already in hand.
- **Tests**: existing session-manager and main tests call `sessions.get(user, project)` / `close(...)` and construct `Session(...)` — they must pass a `chat_id`. This is expected test churn for a behavior change; the updated tests encode the new contract (AC-1..AC-5).
- **Rollout**: direct, on the `refactor` branch; no flag.

## Open questions

None — OQ-1 (per-chat) and OQ-2 (fresh start) resolved in the spec.

## ADRs referenced or created

- ADR-0005 (referenced). No new ADR.

## Links

- Spec: `docs/sdlc/specs/sessions/per-chat-isolation.md`
- Plan: `docs/sdlc/plans/sessions/per-chat-isolation.md`
