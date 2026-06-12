# Spec: sessions/per-chat-isolation

> Owner: BA · Module: sessions · Status: approved · Last updated: 2026-06-12

> **Module** `sessions` is registered in `docs/sdlc/modules.md`.

## Problem

Today a user who works in two Feishu group chats that are both bound to the same project gets a **single shared Claude session** — messages typed in one chat carry context into the other, and the two chats' prompts serialize on one session lock — *because sessions are keyed by `(user_id, project)`, not by the chat they came from.* Users reasonably expect each group chat to be an independent conversation.

## Users & context

- **Primary user**: a person who uses the bot from more than one Feishu group chat that map to the same project.
- **When this happens**: a user sends a prompt in chat A, then a prompt in chat B, both resolving to the same project.
- **Where this happens**: Feishu group chats bound (or defaulting) to the same project.

## Goals

- Two different chats for the same user+project run **independent** Claude sessions (separate conversation context; separate concurrency).
- Single-chat usage is **unchanged** (no regression for the common case).
- The change is observable and testable via the session key and the session lifecycle commands.

## Non-goals

- Per-**user** access control or identity changes (out of scope; ADR-0006 unchanged).
- Changing the transport, the SDK engine, or the persistence mechanism (still file-based JSON per ADR-0005).
- Cross-chat session sharing as an opt-in feature (not in this iteration).

## Acceptance criteria

### AC-1: Independent sessions per chat
- **Given** the same user and project, reached from two different chats (chat A and chat B)
- **When** the user sends a prompt in chat A and then a prompt in chat B
- **Then** two distinct Claude sessions exist (distinct session keys), and a prompt in chat B does not reuse chat A's live session.

### AC-2: Same chat reuses its session
- **Given** an active session for (user, project, chat A)
- **When** the same user sends another prompt in chat A
- **Then** the existing session for chat A is reused (not recreated).

### AC-3: Session key includes the chat
- **Given** a session is created
- **When** its key is computed
- **Then** the key is a function of user, project, **and** chat — two chats for the same user+project produce different keys; the same chat reproduces the same key.

### AC-4: Lifecycle commands act on the originating chat's session
- **Given** the user has separate sessions in chat A and chat B
- **When** the user runs `/new`, `/stop`, or `/status` in chat A
- **Then** the command affects only chat A's session, leaving chat B's session untouched.

### AC-5: Stale cleanup is per-chat
- **Given** chat A's session is idle past the timeout while chat B's is active
- **When** stale cleanup runs
- **Then** chat A's session is closed and chat B's session remains.

### AC-6: Legacy history does not break resume (fresh start)
- **Given** session history saved before this change (entries keyed `user::project`, without a chat segment)
- **When** the user runs `/resume` in a chat after the change
- **Then** the bot does not error; per-chat history is used, and legacy entries are simply **not** listed — pre-change sessions are not auto-resumable. This is the accepted "fresh start" behavior (see resolved OQ-2).

## Out of scope (deferred)

- A command to explicitly share/merge a session across chats.
- Per-chat configuration overrides (model, mode) — chats still inherit project config.

## Resolved decisions

- **OQ-1 — Resume-history scope → PER-CHAT** (resolved 2026-06-12). `/resume` in a chat lists/loads only sessions started in that chat. The history key gains a chat segment.
- **OQ-2 — Legacy `~/.claude-workspace/sessions.json` entries → FRESH START** (resolved 2026-06-12). Pre-change entries (keyed `user::project`) are not migrated and not auto-resumed; the bot ignores them for resume without erroring (see AC-6). Accepted trade-off: old session history is not carried forward.

## Links

- Related: `docs/adrs/0005-persist-session-metadata-as-file-based-json.md`; `core/src/core/session_manager.py` (`Session.key`, `_history_key`).
- Design doc (filled in by Architect): `docs/sdlc/designs/sessions/per-chat-isolation.md`
