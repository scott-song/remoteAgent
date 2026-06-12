# Modules

> Controlled vocabulary of feature **modules** for the Remote Agent project.
>
> Every SDLC artifact is keyed by `<module>/<feature>` — a spec lives at
> `docs/sdlc/specs/<module>/<feature>.md`, its design at `docs/sdlc/designs/<module>/<feature>.md`,
> and so on. The `<module>` segment **must** be one of the rows below.
>
> **Adding a module is a deliberate act.** A new module is a new top-level area of the product —
> propose it, get it agreed, then add a row here. Do not invent a module inline while writing a spec.
>
> A feature belongs to **exactly one** module — its primary area.

| Module | Description |
|---|---|
| `messaging` | Feishu integration: WebSocket long-connection, REST replies, interactive cards, streaming updates, message de-duplication, @mention stripping |
| `sessions` | Per-(user, project) Claude session lifecycle: creation, isolation, the `Session.lock` concurrency model, resume/auto-resume, on-disk history at `~/.claude-workspace/sessions.json`, stale-session cleanup |
| `projects` | Project registry & YAML config: add / remove / bind / unbind, chat→project resolution, the `ProjectConfig` schema, per-project settings |
| `agent-runtime` | Claude Agent SDK client construction: tool allowlist, MCP server wiring, the `.claude_settings.json` generation, the PreToolUse bash security hook (command allowlist + path restriction) |
| `git-sync` | Project repo clone/pull before work, auto-commit/push after changes (`auto_git`) |
| `platform` | Dev-team-facing foundation: packaging, dependency management, CI/CD, lint/format/type tooling, logging, configuration, and developer docs. The "user" of this module is the team itself. |

<!--
Rules enforced at spec time by role-ba:
- The module slug is kebab-case, matches `^[a-z][a-z0-9-]*$`, and is unique in this table.
- role-ba refuses to write a spec whose module is not listed here; it proposes adding the row first.
- To rename a module, rename its directory under every docs/sdlc/<stage>/ and update this table in
  the same commit — the module slug is a path segment, so a rename moves files.

PROPOSED — for user confirmation when adopting the SDLC flow. These six modules map the existing
codebase onto product areas so that future specs/designs/plans have a home. `platform` is where
the bulk of the initial hardening work (CI, tooling, docs, logging, packaging) lives, treated as a
scaffold-style feature per the using-ai-sdlc lifecycle.
-->
