# ADR-0006: Enforce a per-project bash allowlist with path restriction

**Status:** Accepted (2026-06-12), amended 2026-08-26
**Supersedes:** —
**Superseded by:** —

## Context

The bot runs Claude with Bash enabled on behalf of remote chat users, against real project directories. Unconstrained shell access from a chat message is a serious risk (destructive commands, escaping the project directory, touching unrelated files). We need a guardrail enforced at the `agent-runtime` layer, per project, regardless of which user sent the message, and one that works **unattended** (the bot auto-approves tool use, so it cannot rely on a human approving each call). The current implementation registers a PreToolUse hook that validates bash commands against an allowlist and restricts paths to the project directory. Builds on ADR-0004 (the hook is wired into the SDK client).

## Decision

We will enforce security via a **PreToolUse hook on Bash** that (a) validates each command against a base allowlist plus per-project `allowed_commands`, and (b) when the project is `restricted`, applies a **best-effort** path restriction keeping file-path arguments within the project directory. The policy is **per-project, not per-user** — all users sharing a project share its policy.

This is a guardrail against accidental / careless commands, **not a security sandbox**. It is best-effort by design: the allowlist permits language interpreters (`python3`, `node`, `npx`) and `docker`, any of which can execute arbitrary code and bypass the path restriction. See *Consequences → Harder* for the concrete gaps.

### Amendment (2026-08-26): the command allowlist is off by default

**The command-name allowlist is no longer enforced by default.** The two gates are now independent, switchable per project via `bash_allowlist` and `restricted`:

| YAML | Effect |
| --- | --- |
| `bash_allowlist: false` (**new default**) | No command-name check. `deny` rules in the project's `.claude/settings.json` are the command-level policy. |
| `bash_allowlist: true` | Command names validated against base + `allowed_commands` — the original 2026-06-12 behavior, now opt-in per project. |
| `restricted: true` (default, unchanged) | Path arguments must stay inside the project directory — applies regardless of `bash_allowlist`. |
| `bash_allowlist: false` + `restricted: false` | No `PreToolUse` matcher registered at all; the bot layers no veto over `settings.json`. |

**Why the default flipped.** Two reasons, one practical and one that corrects an error in the original decision.

*Practical:* the allowlist denied the everyday toolchain of every project the bot serves — `make`, `pytest`, `uv`, `pip`, `jq`, `yarn`, `ruff`, `mypy` are all absent from `BASE_ALLOWED_COMMANDS`. Since a `PreToolUse` denial outranks any permission allow rule, a project could grant `Bash(*)` in every settings layer and still be refused, which reads to an operator as "permissions are broken." Per-project `allowed_commands` patching made this a standing maintenance cost with no security payoff, because the allowlist already permits `python3`, `node`, `npx`, and `docker` — each of which can run anything.

*Corrective:* the original *Alternatives considered* rejected "trust Claude's built-in permission modes alone" because the bot auto-approves tool use. That premise was measured and is **only half right**. Verified 2026-08-26 against the bundled CLI with `setting_sources=[]` and no `can_use_tool` callback:

- With a `PreToolUse` deny and `allow: ["Bash(*)"]` → **denied** by the hook. Hook decisions outrank permission rules; settings can never override a hook.
- With no hook and `deny: ["Bash(cat:*)"]` → **denied** by settings. `deny` rules are enforced and outrank `allow`.
- With no hook and `allow: []`, under both `defaultMode: "acceptEdits"` and `defaultMode: "default"` → **allowed**. With no `can_use_tool` callback, what would be an interactive prompt resolves to approval.

So the original concern was right that `allow` rules and `permission_mode` cannot restrict this bot — in headless operation they are effectively no-ops. It was wrong that *no* declarative policy survives auto-approval: `deny` rules do. That makes `settings.json` `deny` the correct home for command-level policy, and the hook's allowlist redundant with it.

**Consequences of the flip.** Command-level policy moves from Python code (`BASE_ALLOWED_COMMANDS`) to per-project `.claude/settings.json` `deny` rules, and **is empty until a project writes those rules** — a project with no `deny` rules now has unconstrained command choice within its path restriction. The path restriction (`restricted: true`) remains the only gate that is on by default. Projects wanting the old behavior set `bash_allowlist: true`. Note also that `setting_sources: ["user", "project"]` (the project-YAML default) does **not** load `.claude/settings.local.json` — `deny` rules must live in `.claude/settings.json`, or `"local"` must be added to `setting_sources`.

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
- **The path restriction is best-effort, not a hard boundary.** Allowing interpreters (`python3`/`node`/`npx`) and `docker` means arbitrary code execution can ignore the path check entirely. The token-based path parser also has gaps: it skips `--flag=/path` tokens, does not resolve `~` / `$VAR` / `$(...)` expansion, and only inspects tokens that lexically look like paths.
- Command-name extraction is heuristic (semicolon-split + shlex) and an ongoing correctness/security surface.
- No per-user accountability — any chat member inherits the project's full policy (documented limitation).

**To revisit when:**
- Untrusted users gain chat access (would force per-user authz or OS sandboxing), OR
- the allowlist becomes unmanageable, OR
- a sandbox-escape / parser-bypass is discovered.

*(The second trigger fired on 2026-08-26 — see the amendment above.)*

## References

- `bots/coder/src/coder/security.py` (`make_bash_security_hook` — `allowed_commands=None` disables the check); `sdk_client.py` PreToolUse wiring; `project_registry.py` (`ProjectConfig.bash_allowlist`).
- Related: ADR-0004 (agent engine), ADR-0007 (secrets the hook must never expose).
