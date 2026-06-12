# Architecture

Remote Agent bridges **Feishu group chat** to the **Claude Agent SDK**, letting you drive Claude Code from a phone or desktop with no inbound server. One Python process connects outbound to Feishu over WebSocket, routes each message to a per-(user, project) Claude session, and streams tool calls back as live-updating Feishu cards.

## Monorepo layout

```
remoteClaudeCode/
├── core/                       # shared library (remoteagent-core)
│   └── src/core/
│       ├── feishu_client.py    # Feishu WebSocket + REST, interactive cards, dedup
│       ├── session_manager.py  # per-(user, project) Claude sessions + on-disk resume history
│       ├── stream_handler.py   # streams tool calls/text into Feishu cards
│       ├── logging_config.py   # stdlib logging setup (LOG_LEVEL)
│       └── config.py           # env-var settings (FEISHU_*, SESSION_TIMEOUT_HOURS, ...)
├── bots/
│   ├── coder/                  # the coder bot (remoteagent-coder)
│   │   └── src/coder/
│   │       ├── main.py             # message routing + slash commands + streaming
│   │       ├── project_registry.py # project configs (YAML), chat↔project binding
│   │       ├── sdk_client.py        # builds the ClaudeSDKClient (tools, hooks, MCP)
│   │       ├── security.py          # bash allowlist + best-effort path restriction
│   │       └── git_sync.py          # clone/pull before work; auto-commit/push
│   └── hr/                     # HR bot (stub / example)
├── docs/adrs/                  # architecture decision records
└── docs/sdlc/                  # specs, designs, plans (ai-sdlc flow)
```

Packages are wired with editable installs into one virtualenv ([ADR-0001](docs/adrs/0001-use-a-monorepo-with-pip-editable-installs.md)).

## Data flow: a message from arrival to response

```
Feishu (phone/desktop)
   │ WebSocket (outbound long-connection)
   ▼
core.feishu_client._on_event   → dedup (message-id LRU), strip @mention
   │ on_message callback
   ▼
coder.main._on_message         → "/command"? dispatch : _handle_prompt
   │
   ├─ _resolve_project(user, chat)        # chat binding → user's last → default
   ├─ git_sync.sync_repo (if github_url)  # clone/pull first
   ├─ sessions.get / create               # per-(user, project); auto-resume last session_id
   │     └─ sdk_client.create_claude_client(project, resume=...)
   │            tools + PreToolUse security hook + MCP + cwd=project_dir
   ▼
ClaudeSDKClient.query(text) → receive_response()  (streamed)
   │ AssistantMessage / ToolUseBlock / ToolResultBlock / SystemMessage
   ▼
core.stream_handler            → live-updates the Feishu card
   │ on completion
   ├─ sessions.save_to_history  # persist session_id to ~/.claude-workspace/sessions.json
   └─ auto-git commit/push (if enabled) + action buttons
```

## Key design decisions

These are recorded as ADRs in [`docs/adrs/`](docs/adrs/):

- **[ADR-0001](docs/adrs/0001-use-a-monorepo-with-pip-editable-installs.md)** — monorepo + pip editable installs
- **[ADR-0002](docs/adrs/0002-require-python-3-10-as-minimum-runtime.md)** — Python ≥ 3.10
- **[ADR-0003](docs/adrs/0003-use-feishu-lark-oapi-websocket-transport.md)** — Feishu/lark-oapi WebSocket transport (outbound, no server)
- **[ADR-0004](docs/adrs/0004-use-the-claude-agent-sdk-as-the-agent-engine.md)** — Claude Agent SDK engine
- **[ADR-0005](docs/adrs/0005-persist-session-metadata-as-file-based-json.md)** — file-based JSON session persistence
- **[ADR-0006](docs/adrs/0006-enforce-per-project-bash-allowlist-with-path-restriction.md)** — per-project bash allowlist + best-effort path restriction
- **[ADR-0007](docs/adrs/0007-manage-secrets-via-local-dotenv-files.md)** — local dotenv secrets
- **[ADR-0008](docs/adrs/0008-use-pytest-with-a-ci-coverage-gate.md)** — pytest + CI coverage gate

## Session model (important nuance)

Sessions are keyed `(user_id, project)` — **not** by chat. Two chats bound to the same project share one session for a given user; messages serialize through the session's `asyncio.Lock`. See [ADR-0005](docs/adrs/0005-persist-session-metadata-as-file-based-json.md).
