#!/usr/bin/env bash
# >>> ai-sdlc-c1 vendored copy — DO NOT HAND-EDIT. Regenerate with /sdlc-ci-install.
# source: scripts/ticket-sync.sh @ ai-sdlc-c1 v0.62.0
# source-sha256: a5dd9275982f192e191d3a9234466961ca36e1ee0fd97bede4e8abb17193148e
# installed: 2026-08-26
# <<< ai-sdlc-c1
# ticket-sync.sh — SDLC↔ticketing transport. Non-fatal by contract: on any failure it warns to
# stderr and exits 3; callers treat exit 3 as "skipped, continue".
#
# Config is read STRAIGHT FROM THE ENVIRONMENT — no CLAUDE.md parsing, no caller-side mapping; the
# caller passes no config arguments at all. A value a model has to read out of prose and forward
# correctly is a value that can silently arrive wrong (a stale projectId reads as a bare 403). Set these
# in the consuming project's `.claude/settings.json` `env` block (committed) — see
# playbooks/shared/ticketing.md.
#
#   AI_SDLC_TICKETING_ENABLED       master switch; must be "true" (any case) or every verb no-ops.
#                                   NOT inferred from the other vars being set.
#   AI_SDLC_TICKETING_API_URL       ticketing API base URL
#   AI_SDLC_TICKETING_PROJECT_ID    target project UUID
#   AI_SDLC_TICKETING_PROVIDER      adapter name (read by the SKILLS, not by this script)
#   AI_SDLC_TICKETING_API_KEY_ENV   the NAME of the var holding the secret — e.g. "AI_TICKETING_API_KEY".
#                                   Committed, because the name is a shared project convention; the
#                                   project picks it so a CI runner or secret manager can impose its
#                                   own. Only the VALUE lives in gitignored settings.local.json.
#   AI_SDLC_TICKETING_DRY_RUN=1     print intended calls instead of performing them (tests / previews)
#
# Deliberately NOT read here: AI_SDLC_TICKETING_WEB_URL / _WEB_USER_ENV / _WEB_PASSWORD_ENV. Those let a
# human or agent eyeball the projection in the web UI; the transport must never depend on that surface
# being reachable, or a sync would fail for a reason unrelated to the API.
#
# Verbs. This list is authoritative — playbooks/shared/ticketing.md § Verbs covers the write verbs a
# stage footer calls, not the read verbs, `comment`, `append-desc`, `reconcile`, `version` or `preflight`.
#   ensure-module <slug>
#   upsert-ticket --title T --desc D --module SLUG [--priority P] [--id TICKET_ID] [--spec SPEC_PATH]
#   upsert-task   --title T --desc D --linked FEATURE_TICKET_ID [--priority P] [--id TASK_TICKET_ID]
#   link-artifact --ticket TID --type TYPE --title T --path REPO_REL_PATH
#   set-status    --ticket TID --status "Status Name" [--kind feature|task] [--root-cause RC]
#   set-ref       --ticket TID --ref REF            (branch name or commit SHA)
#   comment       --ticket TID --body TEXT          (append a comment; needs comments:write)
#
# Read verbs (no writes; used by `reconcile` and by /sdlc-sync):
#   get-ticket     --ticket TID                     prints  id= reference= status= gitRef=
#   list-artifacts --ticket TID                     prints  one "<type> <path>" per line
#   list-tasks     --ticket TID                     prints  one "<id> <status> <title>" per line
#   append-desc    --ticket TID --body TEXT         appends a line to the description (read-modify-write)
set -uo pipefail

# TRANSPORT_VERSION — bump whenever a VERB is added, removed, or changes its flags.
#
# WHY. `.claude/scripts/ticket-sync.sh` in a consuming project WINS over the plugin's copy (see
# ticketing.md § Invoking the transport). That is deliberate — CI and session must run the same bytes —
# but it means a project holding an installed copy from an older release silently overrides a newer
# plugin. The new plugin then calls a verb the old copy has never heard of. Without a version there is
# nothing to compare, so the skew is invisible until a stage reports a verb it cannot explain.
TRANSPORT_VERSION="4"
# 1 — ensure-module, upsert-ticket, upsert-task, link-artifact, set-status, set-ref, comment, preflight
# 2 — adds the read verbs (get-ticket, list-artifacts, list-tasks), append-desc, and reconcile
# 3 — link-artifact refuses a --type that contradicts the docs/sdlc/<stage>/ directory in --path
# 4 — adds sync-stage: one call per stage owning the sequence + status edges + the single verdict line,
#     replacing the prose sequence that was restated across 17 payload files
#     (stages: spec, design, plan, build, review, test)

VERB="${1:-}"; shift 2>/dev/null || true

# Answer the version question before ANY config gate: a caller must be able to detect skew even when
# ticketing is disabled or misconfigured, which is exactly when a confusing failure would otherwise land.
if [ "$VERB" = "version" ]; then echo "transport_version=$TRANSPORT_VERSION"; exit 0; fi
warn() { echo "⚠ ticketing: ${VERB:-?} skipped — $1" >&2; exit 3; }

# ── preflight (read-only) — above the master-switch gate: it must report DISABLED out loud,
# while the gate below exits 0 silently. ALWAYS prints, ALWAYS exits 0, never warn()/api() —
# a nonzero exit here aborts the SessionStart hook.
if [ "$VERB" = "preflight" ]; then
  # OUTPUT CONTRACT: exactly one `key=value` per line — env values are folded (never dropped) over
  # CR/LF/NEL/LS/PS and angle brackets so a stray byte cannot forge extra report lines. Byte escapes,
  # not \uHHHH (macOS bash 3.2 expands \u literally); whole-sequence matches stay UTF-8-safe.
  _sep_nel=$'\xc2\x85'; _sep_ls=$'\xe2\x80\xa8'; _sep_ps=$'\xe2\x80\xa9'
  _pf_line() {                    # _pf_line <key> <value>
    local _v="$2"
    _v="${_v//$'\r'/ }"
    _v="${_v//$'\n'/ }"
    _v="${_v//$_sep_nel/ }"
    _v="${_v//$_sep_ls/ }"
    _v="${_v//$_sep_ps/ }"
    _v="${_v//</ }"
    _v="${_v//>/ }"
    printf '%s=%s\n' "$1" "$_v"
  }
  _pf_en="$(printf '%s' "${AI_SDLC_TICKETING_ENABLED:-}" | tr '[:upper:]' '[:lower:]')"
  _pf_reason=""
  case "$_pf_en" in
    true)     _pf_state="enabled" ;;
    ''|false) _pf_state="disabled" ;;
    *)        _pf_state="misconfigured"
              _pf_reason="AI_SDLC_TICKETING_ENABLED must be true or false, got '${AI_SDLC_TICKETING_ENABLED:-}'" ;;
  esac

  # Indirect expansion only after proving the NAME is non-empty (set -u).
  _pf_key_var="${AI_SDLC_TICKETING_API_KEY_ENV:-}"
  _pf_key_resolves="no"
  if [ -n "$_pf_key_var" ] && [ -n "${!_pf_key_var:-}" ]; then _pf_key_resolves="yes"; fi

  # Enabled but incomplete is a misconfiguration. Saying so here beats letting the first mutating
  # verb discover it mid-stage as a bare 403.
  if [ "$_pf_state" = "enabled" ]; then
    for _pf_v in AI_SDLC_TICKETING_API_URL AI_SDLC_TICKETING_PROJECT_ID AI_SDLC_TICKETING_API_KEY_ENV; do
      if [ -z "${!_pf_v:-}" ]; then
        _pf_state="misconfigured"; _pf_reason="$_pf_v unset"; break
      fi
    done
    if [ "$_pf_state" = "enabled" ] && [ "$_pf_key_resolves" = "no" ]; then
      _pf_state="misconfigured"
      _pf_reason="\$$_pf_key_var is empty — set it in .claude/settings.local.json (gitignored)"
    fi
  fi

  # Every line goes through _pf_line — including the ones whose value is derived rather than copied
  # (`ticketing=`, `key_resolves=`). Uniformity is the point: the next key added here inherits the
  # guarantee instead of having to remember it.
  _pf_line ticketing     "$_pf_state"
  _pf_line provider      "${AI_SDLC_TICKETING_PROVIDER:-}"
  _pf_line api_url       "${AI_SDLC_TICKETING_API_URL:-}"
  _pf_line project_id    "${AI_SDLC_TICKETING_PROJECT_ID:-}"
  _pf_line key_var       "$_pf_key_var"
  _pf_line key_resolves  "$_pf_key_resolves"      # boolean ONLY — the value never leaves this process
  [ -z "$_pf_reason" ] || _pf_line reason "$_pf_reason"

  # --probe — one read-only GET proving the credentials actually work. Self-contained curl on
  # purpose: api() calls warn() (exit 3) on failure, which this verb must never do. Never used by
  # the SessionStart hook — hooks stay offline and fast.
  _pf_want_probe=0
  for _pf_a in "$@"; do [ "$_pf_a" = "--probe" ] && _pf_want_probe=1; done
  if [ "$_pf_want_probe" = 1 ]; then
    if [ "${AI_SDLC_TICKETING_DRY_RUN:-}" = "1" ]; then
      _pf_line probe "skipped:dry-run"
    elif [ "$_pf_state" != "enabled" ]; then
      _pf_line probe "skipped:disabled"
    else
      _pf_code="$(printf 'header = "Authorization: Bearer %s"\n' "${!_pf_key_var}" \
        | curl -sS --config - -o /dev/null -w '%{http_code}' --max-time 10 \
            "${AI_SDLC_TICKETING_API_URL}/projects/${AI_SDLC_TICKETING_PROJECT_ID}/automation-options" \
            2>/dev/null)" || _pf_code="000"
      case "$_pf_code" in
        200)     _pf_line probe "ok" ;;
        000|"")  _pf_line probe "failed:unreachable" ;;
        *)       _pf_line probe "failed:http-$_pf_code" ;;
      esac
    fi
  fi
  exit 0
fi

# The master switch, checked FIRST and separately from every other var.
#   unset | "" | false  → SILENT exit 0. An intentional disable has nothing to report.
#   true (any case)     → proceed.
#   anything else       → WARN. `1` / `yes` / a typo would otherwise vanish into the silent path and
#                         look like the sync is broken for no reason. Loud beats mysterious.
_EN="$(printf '%s' "${AI_SDLC_TICKETING_ENABLED:-}" | tr '[:upper:]' '[:lower:]')"
case "$_EN" in
  true)        ;;
  ''|false)    exit 0 ;;
  *)           warn "AI_SDLC_TICKETING_ENABLED must be true or false, got '${AI_SDLC_TICKETING_ENABLED}'" ;;
esac

API_URL="${AI_SDLC_TICKETING_API_URL:-}"
PROJECT_ID="${AI_SDLC_TICKETING_PROJECT_ID:-}"
[ -n "$API_URL" ]    || warn "AI_SDLC_TICKETING_API_URL unset"
[ -n "$PROJECT_ID" ] || warn "AI_SDLC_TICKETING_PROJECT_ID unset"

# Secret resolution is a deliberate two-hop: the pointer var names the secret var, then we read it by
# indirect expansion. Naming both in the error keeps a missing secret self-diagnosing — you learn WHICH
# var to populate, not just that "the key" is absent.
KEY_VAR="${AI_SDLC_TICKETING_API_KEY_ENV:-}"
[ -n "$KEY_VAR" ] || warn "AI_SDLC_TICKETING_API_KEY_ENV unset (it names the var holding the secret)"
API_KEY="${!KEY_VAR:-}"
[ -n "$API_KEY" ] || warn "\$$KEY_VAR is empty — set it in .claude/settings.local.json (gitignored)"

DRY="${AI_SDLC_TICKETING_DRY_RUN:-}"
BASE="/projects/$PROJECT_ID"
HTTP=""; BODY=""

# ─────────────────────────── helpers ───────────────────────────
# api METHOD PATH [BODY] — sets $HTTP and $BODY. The key is passed via a --config stanza on stdin
# so it never appears in argv (ps) or shell history.
api() {
  local method="$1" path="$2" body="${3:-}"
  if [ "$DRY" = "1" ]; then echo "DRYRUN $method ${API_URL}${path} ${body}" >&2; HTTP=200; BODY=""; return 0; fi
  local resp
  resp="$(printf 'header = "Authorization: Bearer %s"\n' "$API_KEY" \
    | curl -sS --config - -X "$method" -H 'Content-Type: application/json' \
        ${body:+--data-binary "$body"} -w $'\n%{http_code}' "${API_URL}${path}")" \
    || warn "$method $path unreachable"
  HTTP="$(printf '%s' "$resp" | tail -n1)"
  BODY="$(printf '%s' "$resp" | sed '$d')"
  printf '%s' "$BODY"
}

# jval JSON PYEXPR — evaluate a python expression against the parsed JSON root `d`.
jval() { printf '%s' "$1" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(eval(sys.argv[1]))' "$2" 2>/dev/null; }
# pyq STR — JSON-quote a shell string for safe embedding in a python expression.
pyq() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }
# json k=v ... — build a JSON object from key=value pairs.
json() { python3 -c 'import json,sys; print(json.dumps(dict(z.split("=",1) for z in sys.argv[1:])))' "$@"; }
# emit_created DRY_SENTINEL_ID — print `id=<id> reference=<ref>` from a create response ($BODY). A
# create that returns no id (renamed/absent key, null, empty body) must NOT record an empty handle:
# the next sync would treat the feature/task as uncorrelated and fork a DUPLICATE. So warn + exit 3.
emit_created() {
  if [ "$DRY" = "1" ]; then echo "id=$1 reference=TIC-DRY"; return 0; fi
  local id ref
  id="$(jval "$BODY" "d.get('id') or ''")"      # null/absent → '' (never the literal 'None')
  ref="$(jval "$BODY" "d.get('reference') or ''")"
  [ -n "$id" ] || warn "create succeeded (HTTP $HTTP) but the response carried no id — not recording an empty handle"
  echo "id=$id reference=$ref"
}

# write_spec_frontmatter SPEC_PATH TICKET_ID REFERENCE — record the ticket handle IN the spec.
# In the transport, not an instruction: the call that mints the ticket is the only place that
# certainly knows the id. Updates the three keys in place; never a second `---`; an unwritable
# path is a notice, never a failure.
write_spec_frontmatter() {
  local sp="$1" tid="$2" ref="$3"
  [ -n "$sp" ] || return 0
  [ -n "$tid" ] || { echo "— ticketing: no ticket id to record in '$sp'" >&2; return 0; }
  [ -f "$sp" ] || { echo "— ticketing: --spec '$sp' not found; handle NOT recorded" >&2; return 0; }
  SP="$sp" TID="$tid" REF="$ref" python3 -c '
import os, re, datetime, sys
sp, tid, ref = os.environ["SP"], os.environ["TID"], os.environ.get("REF", "")
src = open(sp).read()
vals = {"ticketId": tid, "ticket": ref,
        "ticketSyncedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
def line(k, v):
    return k + ":" + " " * max(1, 16 - len(k) - 1) + v
if src.startswith("---"):
    end = src.find("\n---", 3)
    if end == -1:
        sys.exit("unterminated frontmatter")
    head, rest = src[:end], src[end:]
    for k, v in vals.items():
        pat = re.compile("^" + k + r": *.*$", re.M)
        head = pat.sub(line(k, v), head) if pat.search(head) else head.rstrip("\n") + "\n" + line(k, v)
    open(sp, "w").write(head + rest)
else:
    fm = "---\n# MACHINE-MANAGED — written by the ticketing sync, not by hand.\n"
    fm += "".join(line(k, v) + "\n" for k, v in vals.items()) + "---\n\n"
    open(sp, "w").write(fm + src)
' || { echo "— ticketing: could not write frontmatter to '$sp'" >&2; return 0; }
  echo "— ticketing: recorded $ref ($tid) in $sp" >&2
}

# resolve KIND NAME — print the id of a module / feature-status by NAME (via automation-options).
resolve() {
  local kind="$1" name="$2" stype="${3:-feature}"
  # Direct call (NOT command substitution) so api()'s $HTTP/$BODY globals propagate to this shell.
  api GET "$BASE/automation-options" >/dev/null
  if [ "$DRY" = "1" ]; then
    # module → empty forces the create path (exercised in tests); status → fake id so callers proceed
    [ "$kind" = "module" ] && { echo ""; return 0; }
    echo "dry-$kind-id"; return 0
  fi
  [ "$HTTP" = "200" ] || warn "automation-options HTTP $HTTP"
  # kind=module → d["modules"];  kind=status → d["statuses"][<stype>] (feature|task|bug). name→id, or "".
  printf '%s' "$BODY" | _RESOLVE_KIND="$kind" _RESOLVE_NAME="$name" _RESOLVE_STYPE="$stype" python3 -c '
import sys, os, json
d = json.load(sys.stdin)
items = d.get("modules", []) if os.environ["_RESOLVE_KIND"] == "module" else d.get("statuses", {}).get(os.environ["_RESOLVE_STYPE"], [])
print(next((i["id"] for i in items if i.get("name") == os.environ["_RESOLVE_NAME"]), ""))
' 2>/dev/null
}

# create_or_update LABEL CREATE_JSON UPDATE_JSON [CREATE_REQ_VAL CREATE_REQ_MSG]
# The shared body of upsert-ticket / upsert-task. Decide create vs update by probing the stored id:
#   dry or 200 → PATCH (update)   ·   404 → POST (recreate; deleted upstream)   ·   any other → refuse
#   (warn+exit 3, NEVER create — a failed read must not fork a duplicate)   ·   no id at all → POST (create).
# On the create branch it (a) validates the optional CREATE_REQ pair — a create-only precondition such
# as a task needing --linked (update ignores it) — and (b) prints `id=/reference=` via emit_created,
# which refuses an id-less response. LABEL ("ticket"/"task") only shapes the warning text + dry sentinel.
create_or_update() {
  local label="$1" create="$2" update="$3" req_val="${4:-}" req_msg="${5:-}" mode="create"
  if [ -n "$TICKET" ]; then
    api GET "$BASE/tickets/$TICKET" >/dev/null
    case "${DRY}:${HTTP}" in
      1:*|*:200) mode="update" ;;
      *:404)     mode="create" ;;
      *)         warn "$label GET HTTP $HTTP (not creating a duplicate)" ;;
    esac
  fi
  if [ "$mode" = "update" ]; then
    api PATCH "$BASE/tickets/$TICKET" "$update" >/dev/null
    [ "$DRY" = "1" ] || [ "$HTTP" = "200" ] || warn "$label update HTTP $HTTP"
    # Echo the handle on UPDATE too, not only on create. Without this `--spec` silently did nothing on the
    # update path -- the caller passes `--id`, so the id is known, but nothing printed it and the frontmatter
    # writer had no id to record. Found by using the flag to backfill an existing ticket, which is precisely
    # the case it was added for. `reference` comes from the PATCH response when present.
    local uref
    uref="$(jval "$BODY" "d.get('reference') or ''" 2>/dev/null || true)"
    echo "id=$TICKET reference=$uref"
  else
    [ -z "$req_msg" ] || [ -n "$req_val" ] || warn "$req_msg"
    api POST "$BASE/tickets" "$create" >/dev/null
    [ "$DRY" = "1" ] || [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ] || warn "$label create HTTP $HTTP"
    emit_created "dry-$label-id"
  fi
}

# ─────────────────────────── flag parsing ───────────────────────────
SPECPATH=""
TITLE="" DESC="" MODULE="" PRIORITY="major" TICKET="" TYPE="" APATH="" STATUS="" ROOTCAUSE="" REF="" LINKED="" STATUSKIND="feature" BODY_TEXT="" EXPECTS="" EXPSTATUS="" EXPTASKS="" EXPREF="" VERDICT="" CAUSE="" REPORTPATH="" MATRIXPATH="" POS=""
# Note: `${2:-}` (not `$2`) so a dangling flag with no value doesn't abort under `set -u` (exit 1,
# outside the exit-3 contract); a missing value becomes empty and the verb's own required-arg check warns+exits 3.
while [ $# -gt 0 ]; do case "$1" in
  --title) TITLE="${2:-}"; shift 2;;      --desc) DESC="${2:-}"; shift 2;;
  --module) MODULE="${2:-}"; shift 2;;    --priority) PRIORITY="${2:-major}"; shift 2;;
  --spec) SPECPATH="${2:-}"; shift 2;;
  --id|--ticket) TICKET="${2:-}"; shift 2;; --type) TYPE="${2:-}"; shift 2;;
  --path) APATH="${2:-}"; shift 2;;       --status) STATUS="${2:-}"; shift 2;;
  --root-cause) ROOTCAUSE="${2:-}"; shift 2;; --ref) REF="${2:-}"; shift 2;;
  --body) BODY_TEXT="${2:-}"; shift 2;;
  --expect) EXPECTS="$EXPECTS
${2:-}"; shift 2;;
  --expect-status) EXPSTATUS="${2:-}"; shift 2;;
  --expect-ref) EXPREF="${2:-}"; shift 2;;
  --expect-task) EXPTASKS="$EXPTASKS
${2:-}"; shift 2;;
  --linked) LINKED="${2:-}"; shift 2;;    --kind) STATUSKIND="${2:-feature}"; shift 2;;
  --verdict) VERDICT="${2:-}"; shift 2;;  --cause) CAUSE="${2:-}"; shift 2;;
  --report) REPORTPATH="${2:-}"; shift 2;;   --matrix) MATRIXPATH="${2:-}"; shift 2;;
  *) POS="${POS}$1 "; shift;; esac; done

# ─────────────────────────── verbs ───────────────────────────
case "$VERB" in
  ensure-module)
    slug="$(printf '%s' "$POS" | xargs 2>/dev/null)"; [ -n "$slug" ] || warn "module slug required"
    # A module slug is one kebab-case token. Reject multi-token input rather than silently using the
    # first word (which would attach the ticket to the wrong / a half-named module).
    case "$slug" in *' '*) warn "module slug must be a single token, got '$slug'";; esac
    # `|| exit 3` because resolve() runs in a command substitution: warn()'s exit only kills the
    # SUBSHELL. Without this, a read failure (unreachable / 500 / 403) is indistinguishable from
    # "module not found" — the script would fall through to the CREATE below and turn a failed READ
    # into an attempted WRITE. It also double-warned, the second message misdiagnosing the cause.
    id="$(resolve module "$slug")" || exit 3
    if [ -z "$id" ]; then
      api POST "$BASE/modules" "$(json "name=$slug" "description=")" >/dev/null
      [ "$DRY" = "1" ] || [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ] || warn "module create HTTP $HTTP"
      if [ "$DRY" = "1" ]; then
        id="dry-module-id"
      else
        # Re-resolve by NAME instead of parsing the create response. ai-ticketing's POST /modules
        # returns the refreshed LIST (`{modules:[…],viewerRole}`), not the created `{id}` — reading
        # d['id'] yielded empty and the old `${id:-dry-module-id}` fallback then printed a fake
        # dry-run id on a live run. Re-resolving is shape-agnostic: it can't silently half-work.
        id="$(resolve module "$slug")" || exit 3
      fi
    fi
    # No fake-id fallback: an empty id here means the module genuinely isn't there, and a caller
    # given a bogus id would attach the ticket to nothing.
    [ -n "$id" ] || warn "module '$slug' not resolvable after create"
    echo "$id" ;;

  # A feature ticket. `--desc` is a real spec summary (role-ba), never the title; `moduleId` is
  # required by the API and resolved by name (run ensure-module first).
  upsert-ticket)
    [ -n "$TITLE" ] && [ -n "$MODULE" ] || warn "title and module required"
    # --spec is optional but strongly recommended on a CREATE: it is what records the ticket handle in the
    # spec, so the next stage's footer can find it without being told the id.
    [ -n "$DESC" ] || warn "--desc required (a concise feature summary from the spec, not the title)"
    mid="$(resolve module "$MODULE")" || exit 3
    [ "$DRY" = "1" ] || [ -n "$mid" ] || warn "module '$MODULE' not resolvable (run ensure-module first)"
    out="$(create_or_update ticket \
      "$(json type=feature title="$TITLE" description="$DESC" priority="$PRIORITY" moduleId="$mid")" \
      "$(json title="$TITLE" description="$DESC" priority="$PRIORITY" moduleId="$mid")")" || exit $?
    echo "$out"
    if [ -n "${SPECPATH:-}" ] && [ "$DRY" != "1" ]; then
      write_spec_frontmatter "$SPECPATH" \
        "$(printf '%s' "$out" | sed -n 's/.*id=\([^ ]*\).*/\1/p')" \
        "$(printf '%s' "$out" | sed -n 's/.*reference=\([^ ]*\).*/\1/p')"
    fi ;;

  # A plan task, linked to its feature via linkedTicketId (task-create carries no module). `--linked`
  # is required to CREATE (an update-by-id ignores it — hence the create-only precondition).
  upsert-task)
    [ -n "$TITLE" ] || warn "title required"
    [ -n "$DESC" ]  || warn "--desc required (a concise task summary from the plan, not the title)"
    create_or_update task \
      "$(json type=task title="$TITLE" description="$DESC" priority="$PRIORITY" linkedTicketId="$LINKED")" \
      "$(json title="$TITLE" description="$DESC" priority="$PRIORITY")" \
      "$LINKED" "--linked <feature-ticket-id> required to create a task" ;;

  link-artifact)
    [ -n "$TICKET" ] && [ -n "$TYPE" ] && [ -n "$APATH" ] || warn "ticket, type, path required"
    [ -n "$TITLE" ] || TITLE="$(basename "$APATH")"   # artifact title is MANDATORY on the API (≥1 char); default to the filename

    # ── STAGE/TYPE MISMATCH GUARD ────────────────────────────────────────────────────────────────
    # Refuse an artifact whose --type contradicts the SDLC stage directory its --path sits in. The API
    # accepts any (type, path) pair and a mislabelled link is INVISIBLE at the call site: the sync
    # prints ✓ and the artifact appears under the wrong tab, where nobody looks until they go hunting
    # for a test report and find a plan. There is no delete verb to undo it with.
    #
    # A MISMATCH DETECTOR, NOT A WHITELIST. It fires only when the path is under `docs/sdlc/<stage>/`
    # AND that stage maps to a different type, so an unrecognised stage segment, a `ux` handoff screen,
    # and a project that relocated its artifacts via paths.* are all left alone.
    case "$APATH" in
      */docs/sdlc/*|docs/sdlc/*)
        _stage="${APATH#*docs/sdlc/}"; _stage="${_stage%%/*}"
        case "$_stage" in
          specs)        _want=spec   ;;
          designs)      _want=design ;;
          plans)        _want=plan   ;;
          reviews)      _want=review ;;
          test-reports) _want=testReport         ;;
          audits)       _want=auditReport        ;;
          test-reviews) _want=auditReport        ;;   # pre-0.35 directory name; still detected
          traceability) _want=traceabilityReport ;;
          *)            _want=""     ;;   # unknown stage dir → no opinion
        esac
        # The supplied TYPE must ITSELF be one of the known stage types before we have an opinion.
        # Artifact type names are PROVIDER vocabulary, not the plugin's: a ticketing system may call a
        # spec `requirement`, `story`, or anything else, and refusing those would break every project
        # whose provider does not happen to use these five words. Caught by tests/e2e/mock-ticketing,
        # which links `--type requirement` at docs/sdlc/specs/ — a correct pairing in that vocabulary.
        case "$TYPE" in
          spec|ux|design|plan|review|testReport|traceabilityReport|auditReport) _known_type=1 ;;
          *)                          _known_type=0 ;;
        esac
        if [ "$_known_type" = 1 ] && [ -n "$_want" ] && [ "$_want" != "$TYPE" ]; then
          warn "refusing to link a '$TYPE' artifact at docs/sdlc/$_stage/… — that directory holds '$_want' artifacts. Fix --type (or --path); a mislabelled artifact lands on the wrong tab and, on an API without a delete verb, cannot be removed."
        fi ;;
    esac

    api POST "$BASE/tickets/$TICKET/artifacts" "$(json "type=$TYPE" "title=$TITLE" "path=$APATH")" >/dev/null
    [ "$DRY" = "1" ] || [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ] || warn "link HTTP $HTTP" ;;

  set-status)
    [ -n "$TICKET" ] && [ -n "$STATUS" ] || warn "ticket and status required"
    # --kind picks the workflow whose status names to resolve against (feature default; task for task tickets).
    sid="$(resolve status "$STATUS" "$STATUSKIND")" || exit 3
    [ -n "$sid" ] || warn "status '$STATUS' not in the $STATUSKIND workflow"
    if [ -n "$ROOTCAUSE" ]; then payload="$(json "toStatusId=$sid" "rootCause=$ROOTCAUSE")"
    else payload="$(json "toStatusId=$sid")"; fi
    api PATCH "$BASE/tickets/$TICKET/status" "$payload" >/dev/null
    if [ "$DRY" = "1" ] || [ "$HTTP" = "200" ]; then :; else
      # Edge refused → reset through `Reopen` (reachable from ANY status — never `Open`, whose
      # every-status edges are seeded test data), then re-walk forward one enforced edge at a time.
      # Feature workflow only, and only on a refusal — the walk is visible churn on the board.
      if [ "$STATUSKIND" = feature ] && [ "$STATUS" != Reopen ]; then
        _oid="$(resolve status Reopen feature 2>/dev/null || true)"
        if [ -n "$_oid" ] && api PATCH "$BASE/tickets/$TICKET/status" "$(json "toStatusId=$_oid")" >/dev/null \
           && [ "$HTTP" = "200" ]; then
          _walked=Reopen
          for _st in Define Design Plan Build Review Test; do
            _sid="$(resolve status "$_st" feature 2>/dev/null || true)"
            [ -n "$_sid" ] || break
            api PATCH "$BASE/tickets/$TICKET/status" "$(json "toStatusId=$_sid")" >/dev/null
            [ "$HTTP" = "200" ] || break
            # ${...} braces are REQUIRED: the arrow is multibyte, and bash swallows its first byte
            # into the variable name, so `$_walked→` is an unbound-variable error under set -u.
            _walked="${_walked}→${_st}"
            [ "$_st" = "$STATUS" ] && break
          done
          case "$_walked" in
            *"→$STATUS") echo "  reset via Reopen and re-walked: $_walked" >&2 ;;
            *) warn "status $STATUS unreachable — reset to Reopen but the walk stopped at ${_walked##*→}" ;;
          esac
        else
          warn "status HTTP $HTTP, and the reset through Reopen was refused too"
        fi
      else
        warn "status HTTP $HTTP"
      fi
    fi ;;

  # ONE caller per verb-run: the caller keeps artifact PATHS (paths.* lives in prose the transport
  # cannot read) and --desc (judgement); sequencing and status edges live here. NON-GATING BY
  # CONSTRUCTION: every sub-step is attempted even after a failure, all failures land in ONE verdict
  # line, exit 3 — aborting early would silently drop the later links.
  sync-stage)
    _stage="$(printf '%s' "$POS" | xargs 2>/dev/null)"
    [ -n "$_stage" ] || warn "stage required (spec)"
    _fails=""; _ref_out=""; _last_status=""

    # step() runs a sub-verb, records a failure, and NEVER aborts the sequence.
    step() { _label="$1"; shift
             if _o="$("$0" "$@" 2>&1)"; then printf '%s' "$_o"
             else _fails="$_fails $_label"; fi; }

    case "$_stage" in
      spec)
        # Per-stage contract. Missing args are a caller bug, so they warn+exit BEFORE any write:
        # a half-applied projection is worse than none.
        [ -n "$MODULE" ]   || warn "--module required for stage spec"
        [ -n "$TITLE" ]    || warn "--title required for stage spec (the spec's H1)"
        [ -n "$DESC" ]     || warn "--desc required for stage spec (a concise spec summary, not the title)"
        [ -n "$SPECPATH" ] || warn "--spec required for stage spec (the spec path — links it and records the ticket handle)"
        [ -n "$REF" ]      || warn "--ref required for stage spec (the feature branch; artifact URLs resolve on it)"

        step ensure-module ensure-module "$MODULE" >/dev/null

        # upsert-ticket both creates and updates, and --spec makes it record id/reference/syncedAt into
        # the spec frontmatter itself — so a forgotten write-back is not reachable from here.
        _t="$(step upsert-ticket upsert-ticket --title "$TITLE" --desc "$DESC" --module "$MODULE" \
                   --spec "$SPECPATH" ${TICKET:+--id "$TICKET"})"
        [ -n "$TICKET" ] || TICKET="$(printf '%s' "$_t" | sed -n 's/.*id=\([^ ]*\).*/\1/p')"
        _ref_out="$(printf '%s' "$_t" | sed -n 's/.*reference=\([^ ]*\).*/\1/p')"
        [ -n "$_ref_out" ] || _ref_out="${TICKET:-?}"

        if [ -n "$TICKET" ]; then
          step set-ref       set-ref       --ticket "$TICKET" --ref "$REF" >/dev/null
          step link-artifact link-artifact --ticket "$TICKET" --type spec --path "$SPECPATH" >/dev/null
          # UX links, one per referenced handoff screen. Repeatable `--ux <repo-rel-path>|<SCR-N>`; the
          # caller resolves the Page file because screens.md sits under paths.handoffs.
          printf '%s\n' "$EXPECTS" | while IFS= read -r _u; do
            [ -n "$_u" ] || continue
            "$0" link-artifact --ticket "$TICKET" --type ux \
                 --path "${_u%%|*}" --title "${_u##*|}" >/dev/null 2>&1 || true
          done
          # TWO edges, in order. `Open → Define` must be ISSUED — the server creates at `Open`, `Open`
          # is never a set-status target, and edges are enforced one at a time, so an `Open → Design`
          # jump warns and skips and the ticket never leaves `Open`.
          for _s in Define Design; do
            if step "set-status-$_s" set-status --ticket "$TICKET" --status "$_s" >/dev/null; then
              _last_status="$_s"
            fi
          done
        else
          _fails="$_fails no-ticket-id"
        fi ;;
      # Every stage after `spec` UPDATES an existing ticket: the id lives in the spec frontmatter,
      # written there by stage `spec`. None of them may create one — a second feature ticket is the
      # duplicate this whole correlation scheme exists to prevent.
      design)
        [ -n "$TICKET" ] || warn "--ticket required for stage design (read ticketId from the spec frontmatter; never create a ticket here)"
        [ -n "$APATH" ]  || warn "--path required for stage design (the design doc)"
        step link-artifact link-artifact --ticket "$TICKET" --type design --path "$APATH" >/dev/null
        # ONE edge. On a Loop B design-drift revision the ticket already sits at `Design`, so `Plan` is
        # legal; from anywhere else the state machine refuses it, warns, and skips — which is reported,
        # never forced.
        if step set-status-Plan set-status --ticket "$TICKET" --status Plan >/dev/null; then
          _last_status="Plan"
        fi
        _ref_out="$TICKET" ;;
      # NOT the task projection. Reconciling plan tasks to task tickets needs a per-task `--desc`
      # (a judgement) and needs the plan's `### Task N: … <!-- ticket: … -->` headings parsed and
      # written back — so it stays a caller loop over `upsert-task` / `set-status --kind task`.
      # This verb owns the deterministic tail only: the plan document's own link and the one edge.
      plan)
        [ -n "$TICKET" ] || warn "--ticket required for stage plan (read ticketId from the spec frontmatter)"
        [ -n "$APATH" ]  || warn "--path required for stage plan (the plan doc)"
        step link-artifact link-artifact --ticket "$TICKET" --type plan --path "$APATH" >/dev/null
        if step set-status-Build set-status --ticket "$TICKET" --status Build >/dev/null; then
          _last_status="Build"
        fi
        _ref_out="$TICKET" ;;
      # No artifact: code lands as ordinary commits on the branch, not as an SDLC doc. So this stage is
      # the one edge and nothing else — and per-TASK mirroring (`set-status --kind task`) stays the
      # caller's loop, because only the caller knows which plan task just changed state.
      build)
        [ -n "$TICKET" ] || warn "--ticket required for stage build (read ticketId from the spec frontmatter)"
        if step set-status-Review set-status --ticket "$TICKET" --status Review >/dev/null; then
          _last_status="Review"
        fi
        _ref_out="$TICKET" ;;
      # A feature has SEVERAL review artifacts — one per execution wave plus the feature-pass report — so this
      # verb runs once per report. `--verdict` is what separates them: a WAVE pass links only (it must not
      # move status; the feature is not reviewed yet), the FEATURE pass links and routes.
      review)
        [ -n "$TICKET" ] || warn "--ticket required for stage review (read ticketId from the spec frontmatter)"
        [ -n "$APATH" ]  || warn "--path required for stage review (this report — <feature>.md or <feature>.wave-<n>.md)"
        step link-artifact link-artifact --ticket "$TICKET" --type review --path "$APATH" >/dev/null
        case "$VERDICT" in
          '')  # wave pass — link only, no edge. Not an error, and not a silent skip either.
               _last_status="(no edge — wave pass)" ;;
          pass|PASS)
               if step set-status-Test set-status --ticket "$TICKET" --status Test >/dev/null; then
                 _last_status="Test"
               fi ;;
          needs-changes|NEEDS-CHANGES|fail|FAIL)
               # The back-route target is the ROOT CAUSE, not the verdict — only the reviewer knows which
               # layer was wrong, so the caller must say. Guessing here would move the ticket to the wrong
               # stage and send the wrong role back to work.
               case "$CAUSE" in
                 requirement) _t=Define ;;
                 design)      _t=Design ;;
                 plan)        _t=Plan   ;;
                 coding)      _t=Build  ;;
                 *) warn "--cause required with a non-pass verdict (requirement|design|plan|coding)" ;;
               esac
               if step "set-status-$_t" set-status --ticket "$TICKET" --status "$_t" >/dev/null; then
                 _last_status="$_t"
               fi ;;
          *)   warn "--verdict must be pass, needs-changes or fail (got '$VERDICT')" ;;
        esac
        _ref_out="$TICKET" ;;
      # ONE flag per artifact, each carrying its own type (ticketing.md § Artifact-type map). They render
      # together under the ticket's testing tab but are NOT interchangeable, and inferring a type from a
      # path is how one lands on the wrong tab. `role-tester` owns this stage; the AUDITOR's own doc is
      # linked by `reconcile`, not here, so there is no --review flag.
      test)
        [ -n "$TICKET" ] || warn "--ticket required for stage test (read ticketId from the spec frontmatter)"
        [ -n "$REPORTPATH$MATRIXPATH" ] || warn "stage test needs --report (testReport) and/or --matrix (traceabilityReport)"
        [ -z "$REPORTPATH" ] || step link-report link-artifact --ticket "$TICKET" --type testReport         --path "$REPORTPATH" >/dev/null
        [ -z "$MATRIXPATH" ] || step link-matrix link-artifact --ticket "$TICKET" --type traceabilityReport --path "$MATRIXPATH" >/dev/null
        case "$VERDICT" in
          # `passed` and `blocked` issue NO status edge, deliberately. The test stage runs before the
          # review, so the ladder advances to Test on the review's pass; the finish is deploy-gated (the
          # project's CD sets Test deploy), and an external blocker is not work returned for rework —
          # Reopening it would file an environment problem as a code defect.
          passed|blocked)  _last_status="held ($VERDICT)" ;;
          failed)          if step set-status-Reopen set-status --ticket "$TICKET" --status Reopen >/dev/null; then
                             _last_status="Reopen"
                           fi ;;
          '') warn "--verdict required for stage test (passed|failed|blocked)" ;;
          *)  warn "--verdict must be passed, failed or blocked (got '$VERDICT')" ;;
        esac
        _ref_out="$TICKET" ;;
      *) warn "unknown stage '$_stage' (implemented: spec, design, plan, build, review, test)" ;;
    esac

    # ONE verdict line, on stdout, in ticketing.md's exhaustive vocabulary — the caller relays it
    # verbatim rather than composing its own.
    if [ -z "$_fails" ]; then
      echo "✓ synced $_ref_out → ${_last_status:-?}"
    else
      echo "⚠ ticketing: sync-stage skipped —$_fails (ref ${_ref_out:-?})"
      exit 3
    fi ;;

  reconcile)
    # THE FINAL-GATE CHECK. Everything upstream is non-gating: any set-status or link-artifact may have
    # warned and continued, which is correct per-stage but means nobody has ever checked whether the
    # ticket actually matches reality. This verb is that check — diff, repair, re-read, report a COUNT.
    #
    # DELIBERATELY DUMB. The caller passes the expected set (`--expect <type>=<path>`, repeatable, and
    # `--expect-status`), because the caller is what knows the project's paths.* overrides. Teaching the
    # transport the artifact map would put policy in the transport and duplicate ticketing.md.
    [ -n "$TICKET" ] || warn "ticket required"
    total=0; ok=0; unrepaired=""

    # -- the ticket itself. 404 => create is handled by upsert-ticket, not here; reconcile REPORTS it,
    #    because silently creating a feature ticket without a title/description would make a junk row.
    total=$((total+1))
    tinfo="$("$0" get-ticket --ticket "$TICKET" 2>/dev/null || true)"
    case "$tinfo" in
      *missing=yes*) unrepaired="$unrepaired ticket-$TICKET-missing" ;;
      *) ok=$((ok+1)) ;;
    esac

    # -- status
    if [ -n "$EXPSTATUS" ]; then
      total=$((total+1))
      cur="$(printf '%s' "$tinfo" | sed -n 's/.*status=\([^ ]*\).*/\1/p')"
      if [ "$cur" = "$EXPSTATUS" ]; then ok=$((ok+1))
      else
        if "$0" set-status --ticket "$TICKET" --status "$EXPSTATUS" >/dev/null 2>&1; then ok=$((ok+1))
        else unrepaired="$unrepaired status(want=$EXPSTATUS,got=${cur:-?})"; fi
      fi
    fi

    # -- gitRef. Artifact URLs resolve on it, so a ticket pointing at the wrong branch shows 404s for
    #    every link that IS correctly recorded.
    if [ -n "$EXPREF" ]; then
      total=$((total+1))
      curref="$(printf '%s' "$tinfo" | sed -n 's/.*gitRef=\([^ ]*\).*/\1/p')"
      if [ "$curref" = "$EXPREF" ]; then ok=$((ok+1))
      else
        if "$0" set-ref --ticket "$TICKET" --ref "$EXPREF" >/dev/null 2>&1; then ok=$((ok+1))
        else unrepaired="$unrepaired gitRef(want=$EXPREF,got=${curref:-?})"; fi
      fi
    fi

    # -- task tickets. `--expect-task <taskTicketId>=<Status>`, one per plan task. A task with no id was
    #    never projected: report it, never create it — a task ticket needs a title and summary that are
    #    judgement, not data, so inventing one would put a junk row on the board.
    if [ -n "$(printf '%s' "$EXPTASKS" | tr -d '[:space:]')" ]; then
      htasks="$("$0" list-tasks --ticket "$TICKET" 2>/dev/null || true)"
      for t in $(printf '%s\n' "$EXPTASKS" | grep -v '^$'); do
        total=$((total+1))
        tid="${t%%=*}"; tstatus="${t#*=}"
        case "$tid" in
          ''|none|unprojected) unrepaired="$unrepaired task-unprojected"; continue ;;
        esac
        # list-tasks prints "<id> <status> <title>" per line.
        cur_t="$(printf '%s\n' "$htasks" | awk -v i="$tid" '$1==i {print $2}')"
        if [ -z "$cur_t" ]; then unrepaired="$unrepaired task($tid)-missing"
        elif [ "$cur_t" = "$tstatus" ]; then ok=$((ok+1))
        else
          if "$0" set-status --ticket "$tid" --status "$tstatus" --kind task >/dev/null 2>&1; then ok=$((ok+1))
          else unrepaired="$unrepaired task($tid,want=$tstatus,got=$cur_t)"; fi
        fi
      done
    fi

    # -- artifacts: exactly one per expected type, pointing at the current path
    have="$("$0" list-artifacts --ticket "$TICKET" 2>/dev/null || true)"
    for e in $(printf '%s\n' "$EXPECTS" | grep -v '^$'); do
      total=$((total+1))
      etype="${e%%=*}"; epath="${e#*=}"
      if printf '%s\n' "$have" | grep -qxF "$etype $epath"; then ok=$((ok+1))
      else
        if "$0" link-artifact --ticket "$TICKET" --type "$etype" --title "$(basename "$epath")" --path "$epath" >/dev/null 2>&1; then ok=$((ok+1))
        else unrepaired="$unrepaired artifact($etype)"; fi
      fi
    done

    if [ -z "$unrepaired" ]; then echo "✓ reconciled $ok/$total"
    else echo "⚠ ticketing: reconciled $ok/$total —$unrepaired" >&2; fi
    exit 0 ;;

  get-ticket)
    # Read-only. Prints a stable, greppable line so `reconcile` (and a human) can diff expected vs
    # actual without parsing JSON in shell.
    [ -n "$TICKET" ] || warn "ticket required"
    api GET "$BASE/tickets/$TICKET" >/dev/null   # NOT $( ): api sets HTTP/BODY, a subshell would lose them
    [ "$DRY" = "1" ] && { echo "id=$TICKET reference= status= gitRef="; exit 0; }
    out="$BODY"
    [ "$HTTP" = "200" ] || { echo "id=$TICKET missing=yes http=$HTTP"; exit 0; }
    printf '%s' "$out" | python3 -c '
import sys, json
d = json.load(sys.stdin)
def g(*ks):
    for k in ks:
        v = d.get(k)
        if isinstance(v, dict): v = v.get("name") or v.get("id")
        if v: return v
    return ""
print("id=%s reference=%s status=%s gitRef=%s" % (g("id"), g("reference","ref"), g("status","statusName"), g("gitRef","gitref")))' 2>/dev/null \
      || echo "id=$TICKET parse=failed" ;;

  list-artifacts)
    # Read-only. One "<type> <path>" per line — the shape `reconcile` diffs against the artifact map.
    [ -n "$TICKET" ] || warn "ticket required"
    api GET "$BASE/tickets/$TICKET/artifacts" >/dev/null
    [ "$DRY" = "1" ] && exit 0
    out="$BODY"
    [ "$HTTP" = "200" ] || { echo "http=$HTTP" >&2; exit 0; }
    printf '%s' "$out" | python3 -c '
import sys, json
d = json.load(sys.stdin)
items = d if isinstance(d, list) else (d.get("artifacts") or d.get("items") or [])
for a in items:
    print("%s %s" % (a.get("type",""), a.get("path") or a.get("url") or ""))' 2>/dev/null || true ;;

  list-tasks)
    # Read-only. One "<id> <status> <title>" per line.
    [ -n "$TICKET" ] || warn "ticket required"
    # `linkedTicketId`, NOT `linkedTo`. The provider's TicketListQuerySchema names the column verbatim and
    # the query object is `.strict()`, so `linkedTo` is a 400 — and a 400 here is SILENT: the caller sees
    # an empty task list and reports every task "missing" while every task exists. Confirmed against 24
    # real tasks in a consuming project; the wrong name had been shipping since the verb was added.
    api GET "$BASE/tickets?linkedTicketId=$TICKET&type=task" >/dev/null
    [ "$DRY" = "1" ] && exit 0
    out="$BODY"
    [ "$HTTP" = "200" ] || { echo "http=$HTTP" >&2; exit 0; }
    printf '%s' "$out" | python3 -c '
import sys, json
d = json.load(sys.stdin)
items = d if isinstance(d, list) else (d.get("tickets") or d.get("items") or [])
for x in items:
    st = x.get("status")
    if isinstance(st, dict): st = st.get("name","")
    print("%s %s %s" % (x.get("id",""), st or "", x.get("title","")))' 2>/dev/null || true ;;

  append-desc)
    # Read-modify-write. The CR log lives in the feature ticket's description, so a CR needs no ticket
    # of its own — appending is the whole mechanism. PATCH replaces, so the current text must be read
    # first; a failed read must NOT write, or the log is silently truncated to one line.
    [ -n "$TICKET" ] && [ -n "$BODY_TEXT" ] || warn "ticket and body required"
    if [ "$DRY" = "1" ]; then api PATCH "$BASE/tickets/$TICKET" "$(json description="<appended>")" >/dev/null; exit 0; fi
    api GET "$BASE/tickets/$TICKET" >/dev/null
    [ "$HTTP" = "200" ] || warn "cannot read description to append to (HTTP $HTTP)"
    cur="$BODY"
    newdesc="$(printf '%s' "$cur" | BODY_TEXT="$BODY_TEXT" python3 -c '
import sys, json, os
d = json.load(sys.stdin)
cur = d.get("description") or ""
line = os.environ["BODY_TEXT"]
if line in cur:          # idempotent: re-running a stage must not duplicate the entry
    print(cur, end="")
else:
    if "## Changes" not in cur:
        cur = cur.rstrip() + "\n\n## Changes\n"
    print(cur.rstrip() + "\n" + line, end="")')" || warn "could not build the appended description"
    api PATCH "$BASE/tickets/$TICKET" "$(json description="$newdesc")" >/dev/null
    [ "$HTTP" = "200" ] || warn "append-desc HTTP $HTTP" ;;

  set-ref)
    [ -n "$TICKET" ] && [ -n "$REF" ] || warn "ticket and ref required"
    api PATCH "$BASE/tickets/$TICKET" "$(json "gitRef=$REF")" >/dev/null
    [ "$DRY" = "1" ] || [ "$HTTP" = "200" ] || warn "set-ref HTTP $HTTP" ;;

  # Carries the WHY a status edge cannot: `rootCause` records the CATEGORY (`deployment`), the comment
  # records the EVIDENCE. Needs `comments:write` on the key — without it, 403 is warned + exit 3 like any
  # transport failure, so a missing grant degrades the sync rather than breaking the caller.
  #
  # Body cap is the API's own (max 5000, CreateCommentInputSchema) — truncated here rather than sent
  # over-length, because a 400 on an audit comment is worse than a shortened one.
  comment)
    [ -n "$TICKET" ] && [ -n "$BODY_TEXT" ] || warn "ticket and body required"
    if [ "${#BODY_TEXT}" -gt 5000 ]; then
      BODY_TEXT="$(printf '%.4997s' "$BODY_TEXT")..."
    fi
    api POST "$BASE/tickets/$TICKET/comments" "$(json "body=$BODY_TEXT")" >/dev/null
    if [ "$DRY" != "1" ] && [ "$HTTP" != "200" ] && [ "$HTTP" != "201" ]; then
      if [ "$HTTP" = "403" ]; then
        warn "comment HTTP 403 — the API key lacks the comments:write grant"
      else
        warn "comment HTTP $HTTP"
      fi
    fi ;;

  *)
    # The overwhelmingly likely cause is a STALE PROJECT OVERRIDE, not a typo: the plugin was updated,
    # .claude/scripts/ticket-sync.sh was not, and the project copy wins. Say so and name the remedy —
    # "unknown verb" alone sends people looking for a bug in the caller.
    warn "unknown verb '$VERB' (this transport is version $TRANSPORT_VERSION). If a project copy at .claude/scripts/ticket-sync.sh is in use, it is older than the plugin that called it — re-run /sdlc-ci-install ticket-sync.sh to refresh it" ;;
esac
