# ADR-0007: Manage secrets via local dotenv files

**Status:** Proposed
**Supersedes:** —
**Superseded by:** —

## Context

The bot needs Feishu app credentials (`FEISHU_APP_ID` / `FEISHU_APP_SECRET`) and optionally an Anthropic API key. It runs as a single process on an operator's machine (per ADR-0001's deployment shape). We need a secrets mechanism appropriate to that deployment. The current approach is a gitignored `.env` loaded via `python-dotenv`, with a committed `.env.example` template. Verified: `.env` has **never** been committed (`git log --all -- .env` is empty; `.gitignore` line 1 ignores it). A `platform`-module decision.

## Decision

We will manage secrets via a **local `.env` file loaded with `python-dotenv`**, gitignored, with a committed `.env.example` documenting required and optional variables. No external secrets manager.

## Alternatives considered

- **A secrets manager** (AWS Secrets Manager / HashiCorp Vault / Doppler) — attractive: rotation, audit, central control. Rejected: requires cloud infra + network auth; overkill for a single-host, single-operator process; contradicts the no-server design.
- **Shell / systemd environment variables** — attractive: no secret file on disk. Rejected: less ergonomic for local dev; `.env` is the de-facto Python convention and pairs with `.env.example` for onboarding (it is still env-var-based underneath).
- **Committed encrypted secrets** (git-crypt / SOPS) — attractive: secrets travel with the repo. Rejected: adds a key-distribution problem; a single operator has no need for secrets in the repo at all.

## Consequences

**Easier (positive consequences):**
- Zero infra; standard Python workflow; `.env.example` makes required vars discoverable.
- Nothing secret enters git.

**Harder (costs / negative consequences):**
- No rotation / audit / access-control; leak prevention relies on filesystem hygiene.
- Doesn't scale to multi-host or team-shared secrets.
- `.env.example` must be kept in sync with actual required vars (currently missing `SESSION_TIMEOUT_HOURS` etc. — a `platform` follow-up).

**To revisit when:**
- The bot is deployed to shared/cloud infrastructure, OR
- more than one operator must share credentials, OR
- a compliance regime requires secret rotation/audit.

## References

- `.env.example`; `python-dotenv` usage; `.gitignore` line 1.
- Verified: `.env` never committed (`git log --all -- .env` empty).
- Related: ADR-0006 (security hook must never leak these).
