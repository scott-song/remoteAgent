# Tech preferences

> Team's preferred technology and framework choices. Read by `role-system-architect` when authoring ADRs — the preference-aligned option must appear as a candidate. After an ADR is accepted, the ADR is the authority; these preferences are no longer consulted for that decision area.
>
> **Owner:** Remote Agent maintainers
> **Last updated:** 2026-06-12
> **Location:** `docs/preferences/tech-preferences.md`

> Seeded during the retroactive bootstrap (ADR-0001…0008). Remote Agent is a backend bot (no web UI), so frontend rows are intentionally "none."

---

## Backend

- Framework: none in the web sense — an event-driven bot process (`lark-oapi` WebSocket loop) bridging to the Claude Agent SDK
- Language: Python ≥ 3.10 (per ADR-0002)
- ORM / query builder: none (file-based persistence — ADR-0005)
- API style: inbound Feishu events over WebSocket long-connection + REST replies (ADR-0003); no public API surface

## Database

- Primary datastore: file-based JSON at `~/.claude-workspace/sessions.json` (ADR-0005)
- Cache: in-process (LRU of recent Feishu message IDs for de-duplication)
- Search: none

## Frontend

- Framework: none — Feishu's own phone/desktop clients are the UI (ADR-0003)
- Styling: n/a
- State management: n/a

## Infrastructure

- Cloud provider: none — self-hosted single process on the operator's machine, outbound-only (ADR-0003)
- Container / compute: none (runs directly as a Python process)
- CI/CD: GitHub Actions (per ADR-0008; to be implemented in Phase 2)

## Testing

- Unit + integration: pytest (collapsed — one runner for both layers, ADR-0008)
- E2E: none — no browser/UI surface
- Load testing: none

## Auth

- Identity provider: Feishu app credentials (`FEISHU_APP_ID` / `FEISHU_APP_SECRET`); Claude via CLI subscription (ADR-0004)
- Session model: file-persisted Claude `session_id`, keyed per (user, project, chat), with resume (ADR-0009, superseding ADR-0005)

## Other

- Repo strategy: monorepo with pip editable installs, shared `core` + per-bot packages (ADR-0001)
- Secrets: local `.env` via `python-dotenv`, gitignored, with committed `.env.example` (ADR-0007)
- Agent engine: Claude Agent SDK (`claude-agent-sdk`), pre-1.0 (ADR-0004)
- Security: per-project bash allowlist + best-effort path restriction via PreToolUse hook (ADR-0006)
