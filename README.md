# Remote Agent

Access Claude Code from anywhere via Feishu group chat.

## Why

Claude Code is powerful but tied to your terminal. You can't use it from your phone, continue a session from a different machine, or let teammates interact with it. Remote Agent removes that constraint — talk to Claude Code through Feishu, with full tool visibility and multi-project support.

## What

A Python bot that bridges Feishu to Claude Agent SDK. One bot, multiple projects, separate sessions per user.

- **Multi-project** — bind Feishu group chats to project directories
- **Streaming** — see tool calls (Read, Edit, Bash) as they happen
- **Skills & CLAUDE.md** — loaded automatically from each project
- **Session resume** — paste a session UUID to continue from any machine
- **Git sync** — auto clone/pull before starting work
- **Security** — command allowlist + path restriction per project
- **No server** — just one Python process, connects outbound to Feishu

## How

### Prerequisites

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (logged in)
- [Feishu app](https://open.feishu.cn) with Bot capability + WebSocket mode

### Setup

```bash
git clone https://github.com/scott-song/remoteAgent.git
cd remoteAgent/bot
python3 -m venv .venv
source .venv/bin/activate
pip install lark-oapi requests pyyaml python-dotenv claude-agent-sdk
```

```bash
cp ../.env.example ../.env
# Edit .env with your Feishu app credentials:
#   FEISHU_APP_ID=cli_xxxx
#   FEISHU_APP_SECRET=xxxx
```

### Run

```bash
cd bot
.venv/bin/python -m bot.main
```

### Add a project (from Feishu)

```
/addproject my-app /path/to/project --github https://github.com/user/repo --bind
```

### Commands

```
/projects                — list all projects
/project <name>          — switch project
/addproject <name> <path> — add project (--github <url> --bind)
/removeproject <name>    — remove project
/bind <name>             — bind this chat to a project
/unbind                  — unbind this chat
/mode [plan|auto|ask]    — switch permission mode
/skills                  — list project skills
/skill <name>            — invoke a skill
/resume [id|number]      — resume a session
/new                     — fresh conversation
/stop                    — interrupt current request
/status                  — check agent status
/help                    — show commands
```

Or just send a message — it goes to Claude directly.

## Architecture

```
Feishu (phone/desktop)
  │ WebSocket (outbound)
  ▼
Bot Service (Python)
  ├── feishu_client.py    — Feishu WebSocket + REST
  ├── agent_registry.py   — project configs (YAML)
  ├── session_manager.py  — per-user Claude sessions
  ├── stream_handler.py   — streaming tool calls to cards
  ├── sdk_client.py       — Claude Agent SDK factory
  ├── security.py         — command allowlist
  └── git_sync.py         — clone/pull before work
  │
  ▼
Claude Agent SDK → Claude API
  (uses your CLI subscription)
```

## License

MIT
