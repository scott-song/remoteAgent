# ADR-0003: Use Feishu (lark-oapi) WebSocket long-connection as the messaging transport

**Status:** Accepted (2026-06-12)
**Supersedes:** —
**Superseded by:** —

## Context

Remote Agent's purpose is to reach Claude Code from a chat client (phone/desktop) without standing up an inbound server. The product is built around Feishu group chats. The transport must work **outbound-only** — no public ingress, no webhook endpoint to host or secure — because the bot runs on a developer's machine behind NAT. `lark-oapi` provides a WebSocket long-connection mode that delivers events outbound and sends replies via REST. This is foundational: all of `core/feishu_client.py` depends on it.

## Decision

We will use **Feishu (Lark) via the `lark-oapi` SDK in WebSocket long-connection mode** as the sole messaging transport — an outbound persistent socket for inbound events, with replies sent via Feishu REST. No inbound HTTP server.

## Alternatives considered

- **Feishu webhook / HTTP callback mode** — attractive: standard request/response, stateless. Rejected: requires a public HTTPS endpoint with TLS + event verification, impossible on a NAT'd dev machine without tunneling; defeats the "no server" goal.
- **A different chat platform** (Slack/Discord/Telegram bot API) — attractive: larger ecosystems. Rejected: the team operates on Feishu; switching platforms is a product decision, not a transport one; no benefit here.
- **A custom mobile/web client talking directly to the bot** — attractive: full control over UX. Rejected: enormous build cost; Feishu already provides phone+desktop clients, threading, and identity for free.

## Consequences

**Easier (positive consequences):**
- Zero inbound attack surface; runs anywhere with outbound internet.
- Feishu provides the client apps, identity, threading, and delivery; one dependency (`lark-oapi`).

**Harder (costs / negative consequences):**
- Hard coupling to Feishu's API and event model — `core/feishu_client.py` is Feishu-specific.
- A single long-lived socket is a reconnect / de-dup concern (handled via a message-ID LRU).
- Card-update semantics and rate limits are Feishu's to dictate.

**To revisit when:**
- We need to support a second chat platform (would motivate a transport-abstraction layer), OR
- Feishu changes or deprecates the long-connection mode, OR
- inbound webhooks become necessary for scale.

## References

- `core/src/core/feishu_client.py`; `lark-oapi` WebSocket client.
- Related: ADR-0004 (agent engine consuming these events).
