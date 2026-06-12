# Implementation plan: sessions/per-chat-isolation

> Owner: Planner → Dev · Status: approved · Last updated: 2026-06-12
> Spec: `docs/sdlc/specs/sessions/per-chat-isolation.md` · Spec version targeted: 2026-06-12 (commit `fd92f27`)
> Design: `docs/sdlc/designs/sessions/per-chat-isolation.md` · Design version targeted: 2026-06-12 (commit `260d697`)

## Approach

Three tasks, sequential (each leaves the suite green). Add `chat_id` to the session identity in `core`, propagate it through the `coder` call sites, then update + extend the tests to encode the new contract. Single PR on `refactor`.

## Tasks

### T1 — Add chat_id to the session layer
- **Status**: `[x]`
- **Files**: `core/src/core/session_manager.py`
- **Design**: § `session_manager.py`
- **Covers**: AC-3, AC-5, AC-6
- **Notes**: `Session.chat_id` field + 3-part `key`; `get`/`close` take `chat_id`; `_history_key`/`get_history`/`get_last_session_id` gain a chat segment; `save_to_history` uses `session.chat_id`; `cleanup_stale` closes with `s.chat_id`; remove the legacy `bot_name`-only fallback in `get_history`.

### T2 — Propagate chat_id through coder call sites
- **Status**: `[x]`
- **Files**: `bots/coder/src/coder/main.py`, `bots/coder/src/coder/commands.py`
- **Design**: § `main.py` and `commands.py`
- **Covers**: AC-1, AC-2, AC-4
- **Notes**: pass `chat_id` to every `sessions.get/close/get_history/get_last_session_id`; add `chat_id=chat_id` to every `Session(...)`; shutdown loop and `_stream_response` error path use `session.chat_id`.

### T3 — Update and extend tests
- **Status**: `[x]`
- **Files**: `core/tests/test_session_manager.py`, `bots/coder/tests/test_coder_main.py`
- **Design**: § Cross-cutting (Tests)
- **Covers**: AC-1, AC-2, AC-3, AC-4, AC-5
- **Notes**: update existing calls to the new signatures; add tests: two chats → distinct sessions/keys (AC-1, AC-3); same chat → reuse (AC-2); `/new` in one chat leaves the other (AC-4); stale cleanup per chat (AC-5). Keep coverage ≥ 85%.

## Risk register

- **Wide call-site churn** — many `sessions.*` call sites + tests change signature; mitigation: tests are the safety net, run `make test` after each task.

## Amendments

*(none)*
