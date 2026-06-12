# ADR-0004: Use the Claude Agent SDK as the agent engine

**Status:** Proposed
**Supersedes:** —
**Superseded by:** —

## Context

The bot runs Claude Code sessions on behalf of chat users — streaming tool calls (Read/Edit/Bash), honoring CLAUDE.md and skills, resuming sessions. We need an engine that exposes Claude Code's agent loop programmatically with tool streaming, session resume, hooks, and MCP, and that runs on the operator's existing Claude CLI subscription rather than requiring separate API billing. `claude-agent-sdk` provides exactly this (`ClaudeSDKClient`, `ClaudeAgentOptions`, hooks, `resume`). Builds on ADR-0003 (Feishu events drive these sessions). Foundational to the `agent-runtime` module.

## Decision

We will use the **Claude Agent SDK (`claude-agent-sdk`)** as the agent engine — constructing a `ClaudeSDKClient` per (user, project) session and driving it via `ClaudeAgentOptions` (tools, hooks, MCP, resume), running on the operator's Claude CLI subscription.

## Alternatives considered

- **Call the Anthropic Messages API directly and hand-roll the agent loop** (tool dispatch, file ops, bash) — attractive: no SDK dependency, full control. Rejected: would reimplement Claude Code's entire harness (tools, permissions, skills, session persistence) — months of work to match what the SDK gives for free; also separate API billing.
- **Shell out to the `claude` CLI and parse stdout** — attractive: reuses the exact CLI. Rejected: brittle text parsing, no structured streaming of tool blocks, awkward session/hook control.
- **A non-Claude agent framework** (LangChain agents, etc.) — attractive: provider-agnostic. Rejected: the product is "Claude Code from anywhere"; an abstraction layer would lose Claude Code's skills/CLAUDE.md/permission semantics, which are the whole value.

## Consequences

**Easier (positive consequences):**
- Full Claude Code semantics (tools, skills, CLAUDE.md, permission modes, hooks, MCP) for free.
- Structured streaming of assistant/tool/result blocks; native session resume; uses the existing CLI subscription.

**Harder (costs / negative consequences):**
- Hard dependency on the SDK's API surface and version (`>=0.1.47`, pre-1.0 — breaking changes likely).
- Coupled to Claude specifically (no multi-provider).
- Behavior depends on the host CLI's auth/login state.

**To revisit when:**
- The SDK ships a breaking 1.0 that requires migration, OR
- we need multi-provider support, OR
- subscription-based auth becomes unviable for the deployment model.

## References

- `bots/coder/src/coder/sdk_client.py`; `claude-agent-sdk >= 0.1.47`.
- Related: ADR-0003 (transport), ADR-0006 (security hook wired into the SDK client).
