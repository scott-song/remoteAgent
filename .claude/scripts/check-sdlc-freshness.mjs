#!/usr/bin/env node
// >>> ai-sdlc-c1 vendored copy — DO NOT HAND-EDIT. Regenerate with /sdlc-ci-install.
// source: scripts/check-sdlc-freshness.mjs @ ai-sdlc-c1 v0.62.0
// source-sha256: 0c4a304db39c2c65c0970813e41fb7475ac9e1a19f3447b29cdb05a26cf3d254
// installed: 2026-08-26
// <<< ai-sdlc-c1
/**
 * SDLC freshness check — compares artifact CONTENT, not commit identity.
 *
 * Each downstream artifact stamps the git SHA of its upstream, so drift is naively "stamped SHA ≠
 * current SHA". That is broken in a squash-merge repo: the stamped commit vanishes when the PR lands,
 * while the file's content is byte-identical. This resolves the stamped ref to the file's content at
 * that ref and hashes it, so identical content is fresh however history was rewritten — and no
 * re-stamping of the existing corpus is needed.
 *
 * Verdicts:
 *   fresh        content at the stamped ref is identical to current content
 *   DRIFTED      content differs — the downstream artifact predates a genuine change
 *   unresolvable the stamped object is gone (aggressive gc). Never reported as drift: "cannot tell"
 *                and "has changed" call for different actions
 *   unstamped    no stamp to check. Also not drift — and invisible to a SHA-equality check, which is
 *                how 8 test reports went uncheckable without anyone noticing
 *
 * IT ANSWERS "HAS THE UPSTREAM FILE CHANGED?", NOT "HAS THE CONTRACT CHANGED?" — a typo fix, a status
 * flip or an amendment note all count as drift. That makes it the right PRIMARY signal, because it is
 * mechanical and cannot produce a false fresh; an AC-level diff is the right second filter for deciding
 * whether drift needs a re-test or only a re-stamp.
 *
 * Usage:  sdlc-freshness [--json] [--only <module/feature>] [--strict]
 *         sdlc-freshness --anchor <file>     # print that file's h1: stamp
 * Exit:   0 always, UNLESS `--strict` — then 1 when anything DRIFTED. 2 for a configuration error and
 *         it ignores `--strict`: an explicitly-passed directory flag that yields nothing, no specs, no
 *         downstream artifacts, every stamped edge unresolvable, or an unreadable `--anchor` file. Report-by-default is
 *         deliberate: a failing default makes a tool people switch off rather than read. Add `--strict`
 *         in CI once the corpus is clean.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { globSync } from 'node:fs';
import path from 'node:path';

const hash = (buf) => createHash('sha256').update(buf).digest('hex').slice(0, 12);

/**
 * Strip a leading machine-managed YAML frontmatter block before comparing.
 *
 * That block is written by the ticketing sync — `ticketId`, `ticket`, `ticketSyncedAt` — and says so on its
 * own second line. It records where the artifact is projected, not one word of the contract a downstream
 * artifact was built against. Comparing it meant every ticket-handle write drifted that spec's design, plan
 * and report edges at once. Measured: recording one handle in `tickets/ticket-artifacts.md` produced three
 * DRIFTED edges whose entire diff was those six lines.
 *
 * That is precisely the false-positive class this script exists to avoid — a DRIFTED verdict on a healthy
 * chain sends someone to re-verify work that never changed, and teaches them to distrust the check.
 *
 * Only a LEADING block is stripped, up to its closing `---`. An unterminated block is not frontmatter and is
 * compared as-is; `---` elsewhere in the file is ordinary content.
 */
const stripMachineFrontmatter = (buf) => {
  const s = typeof buf === 'string' ? buf : buf.toString('utf8');
  if (!s.startsWith('---')) return s;
  const end = s.indexOf('\n---', 3);
  if (end === -1) return s;
  return s.slice(end + 4).replace(/^\n+/, '');
};

/**
 * Blank an artifact's OWN anchor values before hashing it.
 *
 * SAME ARGUMENT AS THE FRONTMATTER STRIP ABOVE, ONE LEVEL UP. An artifact's stamp records *which upstream
 * version it targets*. That is bookkeeping about the artifact's own dependencies — not one word of the
 * contract that the artifact's own DOWNSTREAMS were built against. A design's downstream is its plan, and
 * the plan cares about the design's components and signatures, never about which spec revision the design
 * happens to cite.
 *
 * Without this, re-stamping is self-propagating: advancing a design's `Targets spec version` changes the
 * design's bytes, so its hash moves, so `plan→design` reports DRIFTED, so the plan must be re-stamped too —
 * a second commit for a change that altered no design decision. Measured on a consuming project on
 * 2026-08-05: this cost two extra commits on two separate occasions in a single day, and it was very nearly
 * "solved" by deleting the `plan→design` edge, which would have thrown away a real check (a changed
 * component contract silently leaving a stale task list) to fix a normalisation bug.
 *
 * The replacement is a fixed-width placeholder rather than a deletion so the surrounding bytes keep their
 * offsets and a stamp cannot be confused with adjacent prose.
 *
 * DELIBERATELY NOT APPLIED TO LEGACY SHA STAMPS. A bare 7-40 hex string is indistinguishable from a commit
 * id quoted in ordinary prose — and these artifacts quote them constantly ("rebased onto `main` at
 * `6a9c231`", "spec commit `9691044`"). Blanking every hex-looking token would erase real content from the
 * comparison, which fails in the dangerous direction: a FALSE FRESH. `h1:` is unambiguous by construction,
 * which is a large part of why the prefix exists.
 */
const ANCHOR_TOKEN = /h1:[0-9a-f]{12}/g;
const normalise = (buf) => stripMachineFrontmatter(buf).replace(ANCHOR_TOKEN, 'h1:<<<ANCHOR>>>');

/** Content of `file` as of `ref`, or null when the object is unreachable. */
function contentAt(ref, file) {
  try {
    // stderr IGNORED, not inherited. An unresolvable stamp is an expected, reported outcome — the `catch`
    // below turns it into a verdict — but `execFileSync` inherits stderr by default, so git's
    // "fatal: invalid object name <sha>" still reached the terminal. On a shallow clone that is one line
    // PER EDGE: a real run emitted 204 of them and buried the error that explains the cause underneath.
    // A diagnostic nobody can find is not a diagnostic.
    return execFileSync('git', ['show', `${ref}:${file}`], {
      maxBuffer: 64 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'ignore'],
    });
  } catch {
    return null;
  }
}

/**
 * TEST REPORTS carry a CANONICAL machine-readable anchor block, and nothing else is trusted:
 *
 *   <!-- sdlc-anchors: spec=<sha> design=<sha> plan=<sha> verified=<YYYY-MM-DD> -->
 *
 * WHY IT EXISTS. Prose stamps turned out to be unreadable in practice. Measured across the 45 reports on
 * 2026-07-30: **five** dialects — `Spec version tested: <date> (commit \`x\`)` ×23, `> Spec: <date>
 * (commit \`x\`)` ×8, `> Anchors — spec \`x\`` ×5, `> Tester · Verdict · Spec \`x\`` ×2 — plus **three**
 * reports mixing two dialects and **four** carrying no stamp line at all.
 *
 * A loose regex over that is not a lenient reader, it is a WRONG one. The previous pattern
 * (`spec` … backtick-sha, anywhere in the file) matched the first such prose it found, so
 * `workflow/workflow-designer` — which has no stamp line — resolved to a sentence about a rebase
 * ("rebased onto `main` at `6a9c231`") and was reported DRIFTED against a SHA that was never a stamp.
 * That is this script's own false-positive class arriving through a different door, and it is worse than
 * the original: a false DRIFTED on a healthy report sends someone to re-run a passing test pass.
 *
 * The human-readable prose stamps STAY, untouched. Several reports carry per-amendment historical stamps
 * that are the audit trail — `tickets/ticket-creation` records Amendment #10's and #11's anchors
 * separately — so rewriting them to today's SHA would have falsified history. Hence an additive block,
 * not a sed over the corpus.
 *
 * DESIGNS and PLANS keep their prose stamp ("Targets spec version" / "Spec version targeted"): those two
 * wordings are consistent across the corpus, each written by a single role. No block is imposed where
 * there is no dialect problem.
 *
 * A report with no block reads `unstamped`, never a guessed SHA. "I cannot tell" is a verdict.
 */
const ANCHOR_BLOCK = /<!--\s*sdlc-anchors:([^>]*?)-->/;

/**
 * TWO ANCHOR DIALECTS, AND THE NEWER ONE IS THE POINT.
 *
 *   h1:<12 hex>   CONTENT ANCHOR (preferred). The upstream's own normalised content hash — literally
 *                 `hash(stripMachineFrontmatter(bytes))`, the same value this script already computes to
 *                 judge drift. Resolving it requires NO git: no object lookup, no history, no clone.
 *   <7-40 hex>    LEGACY GIT SHA. Resolved with `git show <sha>:<file>`. Still fully supported.
 *
 * WHY THE CONTENT ANCHOR EXISTS. A git SHA is not a durable identifier in a squash-merging repo. Squashing
 * a feature branch discards its original commits from the trunk's history, so every artifact stamped while
 * the work was on that branch points at an object that no fresh clone can resolve — permanently, at any
 * fetch depth, because it is not there to fetch. Measured on a consuming project, 2026-08-05, ONE commit:
 *
 *     author's clone   fresh 208 · DRIFTED 0 · unresolvable 0     -> exit 0
 *     CI               fresh 166 · DRIFTED 1 · unresolvable 41    -> exit 1
 *
 * Nine dead SHAs covered those 41 edges. Worse, one came back DRIFTED rather than unresolvable: a
 * 7-character prefix resolved to a DIFFERENT object in CI's clone. Short SHAs are not stable identifiers
 * across clones, so a SHA-anchored gate can report a confident wrong answer, not merely an absent one.
 *
 * A content anchor cannot fail that way. It is derived from the bytes being compared, so it answers
 * identically in every clone, before and after any squash, with no `.git` at all. `unresolvable` is
 * structurally impossible for an `h1:` edge.
 *
 * MIGRATION IS DELIBERATELY GRADUAL — legacy SHAs keep working exactly as before, so adopting this
 * changes no existing verdict. An artifact moves to `h1:` when a stage rewrites its stamp anyway (see
 * `playbooks/shared/anchors.md`); nobody is asked to sed the corpus, and nothing pre-existing breaks.
 */
const CONTENT_ANCHOR = /^h1:[0-9a-f]{12}$/;
const ANCHOR_VALUE = 'h1:[0-9a-f]{12}|[0-9a-f]{7,40}';

/** The stamp value for a file, as a stage should write it. Same normalisation used to judge drift. */
const contentAnchor = (buf) => `h1:${hash(normalise(buf))}`;

function readStamp(text, upstream, isReport) {
  if (isReport) {
    // The canonical block is preferred, but it is an OPT-IN convention: `role-tester` step 13 writes prose
    // stamps by default, so a project that has not adopted the block must still be checkable. Try the block,
    // then fall through to the same phrase matching designs and plans use. A project that HAS adopted the
    // block can tighten this to block-only in a fork or a wrapper — doing so buys stricter guarantees at the
    // cost of reporting `unstamped` for every legacy report.
    const m = text.match(ANCHOR_BLOCK);
    if (m) {
      // `h1:` is tried FIRST. With the legacy branch first, `[0-9a-f]{7,40}` would happily match the
      // 12 hex digits sitting after the `h1:` prefix and silently treat a content anchor as a git SHA —
      // which then reports `unresolvable` on a stamp that needed no git at all.
      const kv = m[1].match(new RegExp(`\\b${upstream}=(${ANCHOR_VALUE})`));
      if (kv) return kv[1];
    }
  }
  // Anchor on the STAMP PHRASE, not the bare word. Matching `design` alone had a bug with real
  // consequences: in `plans/workflow/workflow-designer.md` and `plans/ui/design-system.md` the first
  // case-insensitive `design` in the file sits inside the SPEC line's path (`…/workflow-designer.md`,
  // `…/design-system.md`), so a lazy match ran on to the SPEC's sha and reported it as the design stamp.
  // Both plans were correctly stamped and both were reported DRIFTED — i.e. ANY feature whose name contains
  // "design" was mis-read. The phrases below are the wordings the planner and architect actually write.
  const phrases =
    upstream === 'spec'
      ? ['Spec version targeted', 'Targets spec version', 'Spec version tested']
      : ['Design version targeted', 'Targets design version', 'Design version tested'];
  for (const phrase of phrases) {
    const m = text.match(new RegExp(`${phrase}[^\\n]*?\`(${ANCHOR_VALUE})\``, 'i'));
    if (m) return m[1];
  }
  return null;
}

const REL = (p) => path.relative(process.cwd(), p).split(path.sep).join('/');

function check(kind, artifact, upstream, upstreamFile) {
  const text = readFileSync(artifact, 'utf8');
  const stamp = readStamp(text, upstream, kind.startsWith('report'));
  const rel = REL(upstreamFile);
  if (!stamp) return { kind, artifact: REL(artifact), upstream: rel, verdict: 'unstamped' };
  const now = readFileSync(upstreamFile);
  const nowBody = normalise(now);

  // CONTENT ANCHOR — the stamp IS the expected hash, so this is a direct comparison. No git, therefore
  // no `unresolvable` branch: the only two outcomes are fresh and DRIFTED, in every clone alike.
  if (CONTENT_ANCHOR.test(stamp)) {
    const currentHash = hash(nowBody);
    const same = stamp === `h1:${currentHash}`;
    return {
      kind,
      artifact: REL(artifact),
      upstream: rel,
      stamp,
      anchor: 'content',
      verdict: same ? 'fresh' : 'DRIFTED',
      ...(same ? {} : { stampedHash: stamp.slice(3), currentHash }),
    };
  }

  // LEGACY GIT SHA — unchanged behaviour, so no pre-existing verdict moves.
  const then = contentAt(stamp, rel);
  if (then === null)
    return {
      kind,
      artifact: REL(artifact),
      upstream: rel,
      stamp,
      anchor: 'sha',
      verdict: 'unresolvable',
    };
  const thenBody = normalise(then);
  const same = hash(thenBody) === hash(nowBody);
  return {
    kind,
    artifact: REL(artifact),
    upstream: rel,
    stamp,
    anchor: 'sha',
    verdict: same ? 'fresh' : 'DRIFTED',
    ...(same ? {} : { stampedHash: hash(thenBody), currentHash: hash(nowBody) }),
  };
}

/**
 * `paths.*` overrides (see `playbooks/shared/paths.md`). A consuming project may relocate any artifact
 * directory in its `CLAUDE.md` `[ai-sdlc]` block, so these cannot be hardcoded. They are CLI flags rather
 * than parsed out of CLAUDE.md on purpose: this script must stay a plain executable with no markdown
 * parsing and no dependency on prose staying machine-readable — the exact failure that made the stamps
 * unreadable in the first place.
 */
const flag = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1].replace(/\/+$/, '') : fallback;
};
/**
 * `--anchor <file>` — print the content anchor a stage should stamp for that upstream, then exit.
 *
 * This exists so a stamp is never typed by hand. The value must be `hash(stripMachineFrontmatter(bytes))`
 * exactly, because that is the function this script compares with; a hand-computed `sha256 | cut` would
 * skip the frontmatter strip and drift on the next ticketing-sync write. Deriving it from the same code
 * path is the only way the stamp and the check cannot disagree.
 *
 * Runs before the corpus scan on purpose: it needs one file, not a configured project.
 */
{
  const i = process.argv.indexOf('--anchor');
  if (i !== -1) {
    const target = process.argv[i + 1];
    if (!target || !existsSync(target)) {
      console.error(`ERROR: --anchor needs a readable file (got: ${target ?? '<missing>'})`);
      process.exit(2);
    }
    console.log(contentAnchor(readFileSync(target)));
    process.exit(0);
  }
}

const DIRS = {
  specs: flag('specs', 'docs/sdlc/specs'),
  designs: flag('designs', 'docs/sdlc/designs'),
  plans: flag('plans', 'docs/sdlc/plans'),
  reports: flag('test-reports', 'docs/sdlc/test-reports'),
};

/**
 * AN EXPLICIT FLAG THAT YIELDS NOTHING IS AN ERROR; AN EMPTY DEFAULT IS NOT.
 *
 * The distinction matters and has no false positives. If you *passed* `--designs <dir>` you asserted where
 * the designs are, so a dir that produces no artifacts is unambiguously a typo — and silently dropping the
 * `design→spec` and `plan→design` edges would remove half the checks while still exiting 0. If the dir is
 * simply the *default* and yields nothing, that is a young project which genuinely has no designs yet; warn
 * and carry on.
 *
 * Caught before shipping: a bogus `--specs` was already fatal, but a bogus `--designs` exited **0** with half
 * the edges quietly gone. That is the same "an empty result looks like a pass" failure this script exists to
 * eliminate, reintroduced by its own CLI.
 *
 * THE RESIDUAL, fixed here: the test was directory EXISTENCE, but existence is not what the script consumes —
 * the glob is. `--designs <an-existing-empty-dir>` therefore exited **0**, printed "No content drift." and
 * emitted no warning whatsoever, with two of the four edges never run; the only trace was the summary count
 * falling from `(of 4)` to `(of 2)`. Worse, the polarity was backwards: a *missing default* warned loudly
 * while an *explicitly asserted* empty dir said nothing, so the stronger claim got the weaker checking. The
 * condition below is now "yields at least one matching artifact", which is the thing actually relied on.
 *
 * `--specs` is deliberately exempt from the zero-match half: the `specCount` guard further down already owns
 * that case, with the message this one is modelled on. Existence is still checked for it here so a bogus
 * `--specs` keeps failing at the same point it always has.
 */
for (const [name, dir] of Object.entries(DIRS)) {
  const flagName = name === 'reports' ? 'test-reports' : name;
  const wasExplicit = process.argv.includes(`--${flagName}`);
  const glob = `${dir}/*/*.md`;
  const exists = existsSync(dir);
  const emptyGlob = exists && name !== 'specs' && globSync(glob).length === 0;
  if (exists && !emptyGlob) continue;
  const why = exists ? `exists but matches no artifacts ("${glob}")` : 'does not exist';
  if (wasExplicit) {
    console.error(
      `\nERROR: --${flagName} was given as "${dir}", which ${why}.\n` +
        `  Nothing was checked from it, so this is a configuration error, not a clean result.\n` +
        `  Continuing would silently skip every edge that reads it and still exit 0.\n`,
    );
    process.exit(2);
  }
  console.error(
    `WARNING: default ${name} directory "${dir}" ${why} — every edge reading it is SKIPPED, not passed.`,
  );
}

const only = process.argv.includes('--only')
  ? process.argv[process.argv.indexOf('--only') + 1]
  : null;
const rows = [];
for (const spec of globSync(`${DIRS.specs}/*/*.md`)) {
  const key = `${path.basename(path.dirname(spec))}/${path.basename(spec, '.md')}`;
  if (only && key !== only) continue;
  for (const [kind, dir, upstream, up] of [
    ['design→spec', DIRS.designs, 'spec', spec],
    ['plan→spec', DIRS.plans, 'spec', spec],
    ['report→spec', DIRS.reports, 'spec', spec],
    ['plan→design', DIRS.plans, 'design', `${DIRS.designs}/${key}.md`],
  ]) {
    const artifact = `${dir}/${key}.md`;
    if (!existsSync(artifact) || !existsSync(up)) continue;
    rows.push({ key, ...check(kind, artifact, upstream, up) });
  }
}

/**
 * SUPERSESSION CHECK — catches a design that is WRONG, not merely behind.
 *
 * The freshness check above answers "has the spec changed since the design was stamped?". That is a useful
 * question and an incomplete one: a design can be perfectly re-anchored and still specify behaviour the spec
 * has replaced. Re-stamping such a design makes it *look* current, which is worse than leaving it drifted.
 *
 * Found by hand on 2026-07-30, in two of thirteen drifted designs — and by nothing else:
 *
 *   tickets/ticket-artifacts — AC-10 says a link "stores only the path … no `url`" and states outright that
 *     it supersedes AC-1, AC-2 and AC-7's URL clause. The design still models `url String` with a Zod
 *     `.url()` validator, and never cites AC-10/11/12. Building from it produces the forbidden schema.
 *   board/flowboard-shell — AC-6/7/8 were RETIRED (Amendment #3, BUG-017: "Board drag-and-drop is
 *     removed"). The design still details drag-to-move under those AC numbers and carries a coverage row
 *     for them, while never describing AC-5, the AC that replaced them.
 *
 * THE SIGNAL. An AC whose text says it supersedes / replaces / reworks / retires specific earlier ACs, where
 * the design still cites the OLD numbers but never cites the NEW one. Both halves matter: citing the old
 * numbers alone is normal (history and coverage tables reference them), and not citing the new one alone is
 * weak (designs cite unevenly). Together they mean the design is organised around the replaced behaviour.
 *
 * WHAT IT IS NOT. It cannot read prose, so it cannot prove a design is correct — only flag the shape that
 * made these two findable. A `superseded` row is a prompt to read the design, not a verdict on it. It is
 * reported separately from DRIFTED for exactly that reason, and `--strict` gates on it because a wrong
 * design is a worse failure than a stale stamp.
 */
const SUPERSEDES =
  /\b(supersedes?|superseded|replaces?|reworked from|retired|withdrawn|no longer)\b/i;

function supersessionRows(key, specFile, designFile) {
  if (!existsSync(specFile) || !existsSync(designFile)) return [];
  const spec = readFileSync(specFile, 'utf8');
  const design = readFileSync(designFile, 'utf8');
  const out = [];
  // Each AC's body ends at the NEXT HEADING OF ANY LEVEL, not at the next AC heading and not at an
  // arbitrary character count. Both of those were wrong, and the fixed window was wrong in the way that
  // matters: it produced a false positive before this ever shipped.
  //
  // `projects/sprint-planning`'s `### AC-17: Empty states` is the LAST AC heading in its spec, so a
  // split-on-AC-headings gives it a 21,365-character "body" running to end-of-file. A 900-character window
  // into that reached the Non-goals section, which says "superseded by Amendment #2 … AC-26..AC-29" about
  // something else entirely — and the check reported that an empty-states AC supersedes two inline-edit
  // ACs. Semantically absurd, and it would have been the first thing a reader saw.
  //
  // A gate that cries wolf gets switched off, so the boundary is the structural one: an AC's text is what
  // sits between its heading and the next `##`/`###`.
  const AC_HEAD = /^(#{2,3}) +((?:~~)?AC-(\d+)[^\n]*)$/gm;
  const sections = [];
  for (const m of spec.matchAll(AC_HEAD)) {
    sections.push({ self: Number(m[3]), heading: m[0], start: m.index + m[0].length });
  }
  const NEXT_HEAD = /^#{2,3} +/gm;
  for (const sec of sections) {
    NEXT_HEAD.lastIndex = sec.start;
    const nxt = NEXT_HEAD.exec(spec);
    const body = spec.slice(sec.start, nxt ? nxt.index : spec.length);
    const heading = sec.heading;
    const self = sec.self;
    if (!self) continue;

    // A RETIRED AC is not a superseding one. `### ~~AC-5: …~~ — RETIRED` carries the keyword in its own
    // heading, and a design is CORRECT not to cite it — so "cites the old, not the new" is backwards here.
    // Without this, `platform/workflow-defaults-drift` reported its own retired AC-5 as superseding AC-1.
    if (/~~/.test(heading)) continue;

    const blob = heading + body;

    // The named ACs must sit ADJACENT to the supersession keyword, not merely somewhere in the section.
    // `tickets/ticket-detail` AC-5 cross-references "(AC-19 + AC-23..AC-27)" while discussing a shared
    // component; that is a pointer, not a claim of replacement. The true positives all read as one clause —
    // "AC-10 (new / supersedes AC-1, AC-2, AC-7's URL clause)", "AC-6, AC-7, AC-8 — RETIRED (Amendment #3)"
    // — so proximity is what separates a supersession statement from a citation.
    const named = new Set();
    for (const km of blob.matchAll(new RegExp(SUPERSEDES.source, 'gi'))) {
      const from = Math.max(0, km.index - 90);
      const window = blob.slice(from, km.index + km[0].length + 90);
      for (const am of window.matchAll(/\bAC-(\d+)\b/g)) {
        const n = Number(am[1]);
        if (n !== self) named.add(n);
      }
    }
    if (!named.size) continue;
    const citesNew = new RegExp(`\\bAC-${self}\\b`).test(design);
    const stillCitesOld = [...named].filter((n) => new RegExp(`\\bAC-${n}\\b`).test(design));
    if (!citesNew && stillCitesOld.length) {
      out.push({
        key,
        kind: 'supersession',
        artifact: REL(designFile),
        upstream: REL(specFile),
        verdict: 'superseded',
        ac: self,
        supersedes: stillCitesOld.sort((a, b) => a - b),
      });
    }
  }
  return out;
}

const superseded = [];
for (const spec of globSync(`${DIRS.specs}/*/*.md`)) {
  const key = `${path.basename(path.dirname(spec))}/${path.basename(spec, '.md')}`;
  if (only && key !== only) continue;
  superseded.push(...supersessionRows(key, spec, `${DIRS.designs}/${key}.md`));
}

/**
 * AN EMPTY SCOPE IS A CONFIGURATION ERROR, NOT A PASS.
 *
 * Found before shipping, by running the script with a deliberately wrong `--specs`: it produced zero rows,
 * printed "no drift", and **exited 0 under `--strict`**. A typo in a path flag — or a `paths.*` override the
 * invocation forgot — would therefore switch the gate off silently while still reporting success. That is the
 * single most dangerous failure mode a checker can have, because nothing about the output looks wrong.
 *
 * So: no specs found, or specs found but no edges built, is a hard error regardless of `--strict`. "I checked
 * nothing" must never be indistinguishable from "I found nothing wrong".
 */
const specCount = globSync(`${DIRS.specs}/*/*.md`).length;
if (specCount === 0) {
  console.error(
    `\nERROR: no specs found under "${DIRS.specs}/*/*.md".\n` +
      `  Nothing was checked, so this is a configuration error, not a clean result.\n` +
      `  If this project relocates its artifacts (paths.* in the CLAUDE.md [ai-sdlc] block), pass them:\n` +
      `    --specs <dir> --designs <dir> --plans <dir> --test-reports <dir>\n`,
  );
  process.exit(2);
}
if (rows.length === 0) {
  /**
   * TWO CAUSES, AND THEY SEND THE READER TO DIFFERENT FILES. Zero rows with no `--only` means the
   * artifact directories really are empty or mis-pointed. Zero rows WITH `--only` almost always means
   * the key was wrong — most often the module half, since a key is `<module>/<feature>` and the feature
   * basename is the part a human remembers.
   *
   * Reported as one message, this misdiagnoses the common case: it named the directories (which are
   * fine), quoted the UNFILTERED spec count (which makes the claim look authoritative), and exited 2.
   * Observed on a real project — `--only auth/login-logout` against a feature that lives at
   * `my-account/login-logout` produced "77 spec(s) found ... but no downstream artifacts", pointing at
   * three healthy directories. A gate that names the wrong cause costs more than one that says nothing.
   */
  if (only) {
    const near = [
      ...globSync(`${DIRS.designs}/*/*.md`),
      ...globSync(`${DIRS.plans}/*/*.md`),
      ...globSync(`${DIRS.reports}/*/*.md`),
    ]
      .map((f) => f.split('/').slice(-2).join('/').replace(/\.md$/, ''))
      .filter((k) => k.split('/')[1] === only.split('/').pop())
      .filter((k, i, a) => a.indexOf(k) === i)
      .sort();
    console.error(
      `\nERROR: --only "${only}" matched no design, plan or test report.\n` +
        (near.length
          ? `  Did you mean: ${near.join(' · ')}\n` +
            `  A key is <module>/<feature>; the module half is the one that is usually wrong.\n`
          : `  No artifact of any stage carries that feature name. Check the key, or the artifact paths:\n` +
            `    --specs <dir> --designs <dir> --plans <dir> --test-reports <dir>\n`) +
        `  Nothing was compared, so this is not a clean result.\n`,
    );
    process.exit(2);
  }
  console.error(
    `\nERROR: ${specCount} spec(s) found under "${DIRS.specs}" but no downstream artifacts to check.\n` +
      `  Expected designs in "${DIRS.designs}", plans in "${DIRS.plans}", reports in "${DIRS.reports}".\n` +
      `  Nothing was compared, so this is a configuration error, not a clean result.\n`,
  );
  process.exit(2);
}

/**
 * THE THIRD WAY TO CHECK NOTHING AND CALL IT CLEAN — and the one that actually happened in a real repo.
 *
 * Rows can exist, every one of them can be stamped, and not a single stamp can be RESOLVED. `contentAt`
 * returns null for each, every edge lands on `unresolvable`, `drifted` is therefore empty by
 * construction, and `--strict` exits 0 while having compared exactly nothing. The output even says
 * "No content drift.", which is true and completely misleading.
 *
 * The cause found in the field was `actions/checkout@v4` at its DEFAULT `fetch-depth: 1`. A depth-1
 * clone contains one commit, so no stamped object is present. Measured on a real corpus:
 *
 *     fresh 0 · DRIFTED 0 · unresolvable 204 · unstamped 0  (of 204)      <- exit 0 under --strict
 *
 * The `unresolvable` verdict was introduced for "aggressive gc" and documented that way, which is why
 * nobody looked at it from this direction: gc removes SOME objects, a shallow checkout removes ALL of
 * them, and only the second one silences the gate completely.
 *
 * This is the same defect the two guards above exist for — see the commit that made an explicitly-passed
 * empty artifact directory a configuration error. Same rule, third arrival: **"I checked nothing" must
 * never be indistinguishable from "I found nothing wrong."** So it is a hard error regardless of
 * `--strict`, exactly like its siblings, and it exits 2 rather than 1: this is a configuration fault,
 * not a drift finding, and a CI log that conflates the two sends the reader to the wrong file.
 *
 * The condition is the OUTCOME (nothing resolved), not the cause — so aggressive gc, a corrupt object
 * store or a filtered clone are caught too. Shallowness is only used to make the remedy specific.
 *
 * Deliberately NOT gated on `unresolvable > 0` alone: a partially-resolvable history is a real, if
 * understated, report, and blocking it would make the tool something people switch off rather than read.
 */
const stampedRows = rows.filter((r) => r.verdict !== 'unstamped');
const resolvedRows = rows.filter((r) => r.verdict === 'fresh' || r.verdict === 'DRIFTED');
if (stampedRows.length > 0 && resolvedRows.length === 0) {
  const shallow = (() => {
    try {
      return execFileSync('git', ['rev-parse', '--is-shallow-repository'], { encoding: 'utf8' }).trim() === 'true';
    } catch {
      return false;
    }
  })();
  console.error(
    `\nERROR: all ${stampedRows.length} stamped edge(s) are unresolvable — the stamped commits are not in\n` +
      `  this repository, so NOTHING was compared. Reporting that as "no drift" would be a lie.\n` +
      (shallow
        ? `\n  Cause: this is a SHALLOW clone (git rev-parse --is-shallow-repository = true). A stamp names a\n` +
          `  commit the clone does not contain.\n` +
          `\n  Fix in CI — checkout with full history:\n` +
          `      - uses: actions/checkout@v4\n` +
          `        with:\n` +
          `          fetch-depth: 0        # freshness stamps name commits; depth-1 has none of them\n`
        : `\n  The clone is not shallow, so the objects were removed some other way — aggressive gc, a\n` +
          `  filtered/partial clone, or a restored cache missing its object store. Verify with:\n` +
          `      git cat-file -e <a stamped sha>^{commit}\n`) +
      `\n  This is a configuration error, not a clean result.\n`,
  );
  process.exit(2);
}

const drifted = rows.filter((r) => r.verdict === 'DRIFTED');
if (process.argv.includes('--json')) {
  console.log(JSON.stringify({ rows, superseded, summary: tally(rows) }, null, 2));
} else {
  const t = tally(rows);
  console.log(
    `\nSDLC freshness — content-compared at the stamped ref (squash-immune)\n${'-'.repeat(72)}`,
  );
  for (const r of rows.filter((x) => x.verdict !== 'fresh')) {
    console.log(`  ${r.verdict.padEnd(12)} ${r.kind.padEnd(12)} ${r.artifact}`);
  }
  console.log(
    `\n  fresh ${t.fresh} · DRIFTED ${t.DRIFTED} · unresolvable ${t.unresolvable} · unstamped ${t.unstamped}  (of ${rows.length})\n`,
  );
  if (!drifted.length) console.log('  No content drift.\n');

  // Anchor-format progress. Legacy SHA anchors still work, but every one of them is a potential
  // `unresolvable` the day its commit is squashed away — so the count is worth seeing, and the
  // unresolvable ones are worth naming, since those are already answering nothing.
  const legacy = rows.filter((r) => r.anchor === 'sha');
  const content = rows.filter((r) => r.anchor === 'content');
  if (legacy.length) {
    const dead = legacy.filter((r) => r.verdict === 'unresolvable');
    console.log(
      `  anchors: ${content.length} content (h1:) · ${legacy.length} legacy git-SHA` +
        (dead.length ? ` — ${dead.length} of the legacy ones resolve to nothing` : ''),
    );
    if (dead.length) {
      console.log(
        `  A legacy anchor whose commit was squashed away can never resolve again, and an unresolvable\n` +
          `  edge is NOT compared — it is skipped, not passed. Re-stamp these with a content anchor\n` +
          `  (\`--anchor <upstream-file>\`) next time a stage rewrites them; see playbooks/shared/anchors.md.`,
      );
    }
    console.log('');
  }

  if (superseded.length) {
    console.log(
      `SUPERSEDED — the design still cites replaced ACs and never the AC that replaced them.`,
    );
    console.log(`These are a prompt to READ the design, not a verdict on it.\n${'-'.repeat(72)}`);
    for (const s of superseded) {
      console.log(
        `  ${s.artifact}\n      AC-${s.ac} supersedes ${s.supersedes.map((n) => `AC-${n}`).join(', ')} — design cites the old, not the new`,
      );
    }
    console.log('');
  } else {
    console.log('  No design is organised around a superseded AC.\n');
  }
}
function tally(rs) {
  return rs.reduce((a, r) => ({ ...a, [r.verdict]: (a[r.verdict] ?? 0) + 1 }), {
    fresh: 0,
    DRIFTED: 0,
    unresolvable: 0,
    unstamped: 0,
  });
}
/**
 * `--strict` gates on DRIFT ONLY. The supersession pass reports; it does not fail.
 *
 * It used to gate, and on 2026-08-05 that made it the sole cause of a red build on a consuming project —
 * with the summary directly above it reading "No content drift." Both halves of that finding were wrong:
 *
 *   1. The design DID address the superseding AC, inside the range `AC-15–AC-20`. `citesNew` greps
 *      `\bAC-17\b`, which a range cannot match.
 *   2. The ACs it named as still-cited (AC-5, AC-12) belong to a DIFFERENT feature — the spec says so
 *      explicitly ("Supersedes `ticket-artifacts` AC-5 / AC-12"). The design's own AC-5 and AC-12 are
 *      unrelated criteria that merely share those numbers. AC numbering is per-feature; this comparison
 *      is not.
 *
 * Neither is cheaply fixable: ranges are free-form prose, and cross-feature AC references have no marker
 * to key on. So this is a heuristic over prose, and the block's own header has always said what that
 * makes it — "a prompt to READ the design, not a verdict on it". A prompt must not fail a build.
 *
 * It stays in the output because when it is right it is valuable, and a human reading the design settles
 * it in under a minute. Deleting it would trade a false positive for a blind spot.
 */
/**
 * ONE ASYMMETRY, DELIBERATE: `--only` also gates on `unstamped`; project-wide does not.
 *
 * An unstamped edge is not "no drift found" — it is the SAME condition the shallow-clone guard above
 * exists for, one edge at a time: nothing was compared, and nobody was told in a way that stops
 * anything. Measured on a real corpus before this line existed: 13 unstamped edges, 7 of them
 * `report→spec` (the last artifact in the chain, so no later stage ever re-checks it), and TWO
 * features passed review and shipped with a fully unstamped chain — `--strict` exiting 0 the whole way,
 * including through the ship summary, which reads its freshness counts from exactly this flag.
 *
 * Why project-wide stays tolerant: a project mid-adoption legitimately has unstamped rows for every
 * feature that predates the convention (`/sdlc-ci-install` says so), and failing there makes the tool
 * something people switch off rather than read. But `--only <module>/<feature>` is a GATE on one chain
 * the flow is working on right now, and on that chain an unstamped edge is a stage that skipped its
 * stamp — never a legacy row. Same rule as its siblings, fourth arrival.
 */
const gateUnstamped = Boolean(only) && tally(rows).unstamped > 0;
process.exit(
  process.argv.includes('--strict') && (drifted.length || gateUnstamped) ? 1 : 0,
);
