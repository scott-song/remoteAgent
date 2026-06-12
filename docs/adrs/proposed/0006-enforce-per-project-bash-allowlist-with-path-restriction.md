# ADR-0006: Enforce a per-project bash allowlist with path restriction

**Status:** Proposed
**Supersedes:** —
**Superseded by:** —

## Context

The bot runs Claude with Bash enabled on behalf of remote chat users, against real project directories. Unconstrained shell access from a chat message is a serious risk (destructive commands, escaping the project directory, touching unrelated files). We need a guardrail enforced at the `agent-runtime` layer, per project, regardless of which user sent the message, and one that works **unattended** (the bot auto-approves tool use, so it cannot rely on a human approving each call). The current implementation registers a PreToolUse hook that validates bash commands against an allowlist and restricts paths to the project directory. Builds on ADR-0004 (the hook is wired into the SDK client).

## Decision

We will enforce security via a **PreToolUse hook on Bash** that (a) validates each command against a base allowlist plus per-project `allowed_commands`, and (b) when the project is `restricted`, confines file paths to the project directory. The policy is **per-project, not per-user** — all users sharing a project share its policy.

## Alternatives considered

- **Trust Claude's built-in permission modes alone** (acceptEdits/plan/ask) — attractive: no custom code. Rejected: permission modes gate tool use *interactively*, but the bot auto-approves to run unattended; we still need a hard server-side allowlist independent of human approval.
- **OS-level sandboxing** (containers/seccomp/chroot per session) — attractive: strongest isolation. Rejected: heavy to operate on a dev machine; complicates the git/venv access the bot legitimately needs; disproportionate for the threat model (trusted-but-careless operators, not adversaries).
- **Per-user ACLs** — attractive: finer-grained control. Rejected: no per-user identity/role model exists; chats are small and trusted; per-project is the natural unit (it maps to a codebase).

## Consequences

**Easier (positive consequences):**
- A single choke point (the hook) for all shell commands; per-project tuning via `allowed_commands`.
- Path restriction prevents accidental escape; independent of interactive approval, so the bot runs unattended.

**Harder (costs / negative consequences):**
- Allowlist maintenance burden — new legitimate commands must be added.
- Command parsing/validation is an ongoing correctness and security surface.
- No per-user accountability — any chat member inherits the project's full policy (documented limitation).

**To revisit when:**
- Untrusted users gain chat access (would force per-user authz or OS sandboxing), OR
- the allowlist becomes unmanageable, OR
- a sandbox-escape / parser-bypass is discovered.

## References

- `bots/coder/src/coder/security.py` (`make_bash_security_hook`); `sdk_client.py` PreToolUse wiring.
- Related: ADR-0004 (agent engine), ADR-0007 (secrets the hook must never expose).
