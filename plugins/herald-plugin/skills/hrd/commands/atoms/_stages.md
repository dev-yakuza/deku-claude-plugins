# ATOM — Stage spine (brief → research → draft → critique → verify → publish)

**Not a command.** `write`, `resume`, the single-stage commands and `refresh` drive stages
through this file. Contract: `atoms/_contract.md`. Design: `design/herald/00-plan.md` §3.2–§3.3.

Every stage follows the same frame:

1. `HRD stage check --topic <id> --stage <stage>` (skip for `brief`) — on failure rerun the
   stage it names; never edit state files by hand.
2. Spawn the role with the stage's **read list** only, plus output paths and the contract.
3. Handle the RESULT (`_contract.md` §B).
4. Run the stage's checks below, then `HRD stage pass --topic <id> --stage <stage>`.

`<w>` = `.claude/herald/work/<id>/`.

## brief — content-strategist (+ search-discovery if enabled)

- Before spawning: `HRD begin --topic <id>`.
- **Read list**: the topic entry (`HRD topics show --topic <id>`), `docs/editorial/charter.md`,
  the topic's `docs/editorial/categories/<category>.md`, the cannibalization set (published
  article list from `published.json` + content directory listing + `brief.md` of open Herald PRs
  via `gh pr list --label herald --state open` / `git show origin/<branch>:<w>brief.md`),
  `docs/editorial/search-checklist.md` if search-discovery is enabled (search-discovery writes
  `<w>search-notes.md` first; the strategist reads it).
- **Output**: `<w>brief.md` — search intent, target reader, primary/secondary keywords, the
  distinct angle (required — scaled-content policy), outline, CTA placement, internal links,
  and a proposed **slug** (lowercase, single hyphens, no `--`) on a line `slug: <slug>`.
- Cannibalization conflict → hold `cannibalization`.
- Approval (§C table), then `HRD branch --topic <id> --slug <slug>` (branches from
  `origin/<base>`), then `HRD stage pass --topic <id> --stage brief`.

## research — researcher

- **Read list**: `<w>brief.md`, `docs/editorial/sources.md`, `docs/editorial/promotion.md`.
  The researcher alone reads web pages (WebFetch/WebSearch); raw pages never reach other roles.
- **Output**: `<w>research.md` — claims `C1..Cn`, each with source URL, short excerpt, access
  date, confidence. Policy from `sources.md` (banned sources, mention rules) applies. What the
  article will say about the site's own product (CTA, app features) comes from `promotion.md`
  as **owner claims** (source `docs/editorial/promotion.md`, confidence `owner`); they support
  statements about that product only (fact-checker persona).
- Not enough support for the required sections → `BLOCKED` → hold `research`.

## draft — writer (+ illustrator if enabled)

Order: writer first; then the illustrator reads the draft, creates images and inserts the
references into the article itself; then the gate.

- **Read list**: `<w>brief.md`, `<w>research.md`, the category guide, `style-guide.md`,
  `promotion.md`, that category's exemplars (paths from `exemplars.md`).
- **Output**: the article at `config.paths.body_pattern` for the slug, images under
  `config.paths.images/<slug>/` (illustrator), and `<w>claims-map.json`:
  `{"sentences": [{"text": "...", "claims": ["C3"]}]}` for every factual sentence the writer
  wrote.
- **Gate**: `HRD stage pass --stage draft` runs it in code (`config.commands.validate` if set,
  else the built-in `validate_content.py`) and refuses on errors (it records `gate-failure`
  itself) → `HRD loopback --topic <id> --cause gate`, back to the writer with the errors.

## critique — subject-expert / search-discovery (if enabled) → editor → external auditor

1. Conditional reviewers first. subject-expert: article + category guide + its domain checklist
   (its persona's Project specifics) → `<w>review-subject-expert.md`. search-discovery:
   article + `search-checklist.md` → `<w>review-search-discovery.md`.
2. **editor** — read list: the article, category guide, `style-guide.md`, exemplars, the
   `<w>review-*.md` notes. The editor writes its round into `<w>critique.md`; the
   editor-in-chief appends auditor findings and dismissals and writes `<w>critique.json`. **Never** `research.md`. Verdict PASS / REVISE / REJECT with strengths,
   weaknesses, revision direction.
   - REVISE → `HRD loopback --topic <id> --cause revise --theme <t> --note "<main weakness>"`
     (records `revise-weakness`; `<t>` is the closest of: intro, structure, length, depth,
     clarity, tone, search, promotion, policy, accuracy, images, exemplar, other), back to
     draft (stagnation guard).
   - REJECT → hold `rejected`.
3. **external auditor** — only after the editor's PASS; procedure in `atoms/_auditor.md`.
   First `HRD audit-round --topic <id>` (counts every auditor round of this article, human-
   requested revisions included; cap 3) → `mode`:
   - `full` (round 1): every `BLOCKER`/`MAJOR` must be fixed (loop back) or dismissed.
   - `recheck` (rounds 2–3): the auditor also gets the earlier findings and their outcomes and
     tags each finding `unfixed <id>` (an earlier `fixed` finding still present), `regression
     <id>` (a fix since the last round caused it) or `new`. Loop back only for a `BLOCKER`, an
     `unfixed` or a `regression` `MAJOR`; a `new` `MAJOR` — and on the `last` round any `MAJOR`
     — is **deferred**: not fixed now, listed in the PR body under `## Late audit findings` for
     the human at ship, logged as `decision_log` `kind: deferral`. A `BLOCKER` is never
     deferred.
   - `skip` (past the cap): do not spawn the auditor; write `final_round` with `audit`,
     `dismissed` and `deferred` empty (earlier decisions stay in `audit_log`) and say so in
     `critique.md`. The editor's PASS and verify still apply; the PR is never
     auto-published (`audit-skipped`), and `stage pass` refuses while `audit_log` has a BLOCKER
     whose outcome is not `fixed`/`dismissed`.
   `audit-round` returns the same round (`repeat: true`) while the article is unchanged, so a
   rerun of an interrupted or discarded round is not counted twice; if that round's findings are
   already in `audit_log`, reuse them and do not spawn the auditor again. Call it before taking
   the tripwire hashes (it writes `state.json`). Finding ids are `R<round>-<n>`; a repeated
   round replaces its own entries.
   A finding that blocks → first write this round's `<w>critique.json` (step 4, including any
   dismissals; the finding goes into `audit_log` with outcome `fixed` — the next recheck checks
   it, `unfixed` if it is still there), then `HRD loopback --topic <id> --cause audit --theme <t> --note "<finding>"`
   (records `audit-finding` and the logged dismissals), back to draft; after the fix, editor →
   auditor → verify run again. A `BLOCKER` on the `last` round is never looped back
   automatically (no auditor would check the fix): log it with outcome `open` and hold
   `needs-human` (cause `defect:`) — `--attended` and single-stage commands (`/hrd critique`): ask first;
   in-session auto and unattended: hold without asking (`_contract.md` §C). The human decides (on the spot, or
   on `/hrd resume` before anything runs), recorded as `decision_log` `{"kind": "human", "id":
   "<id>", "note": "human: <their words>"}`:
   - **dismiss** → set the entry's outcome to `dismissed`, add 1 to `final_round.dismissed.blocker`
     of that same round, add a `dismissal` entry with the reason as well as the `human` entry,
     `HRD stage pass --stage critique` — no new auditor round.
   - **fix** → the writer applies the human's direction under `HRD loopback --topic <id> --human`
     (not counted), then gate, editor, `audit-round` (→ `skip`); show the fix and ask the human
     to confirm it — even in in-session auto — then outcome `fixed` and the `human` entry.
   `stage pass` refuses a last-round BLOCKER without that `human` entry (and refuses any in an
   unattended run). A BLOCKER held on round 1–2 (hold chosen, loop cap, stagnation) is logged
   `open` while held; the human's decision on resume sets it to `fixed` (sent back to the
   writer under `HRD loopback --human` — the next recheck verifies it) or `dismissed`, before
   any further audit round (an `open` finding is never handed to an auditor as pending). `MINOR` → PR body only (`noted`).
4. Before spawning the editor, take `HRD hash --slug <slug>`. Write `<w>critique.md` (prose:
   verdicts, findings, dismissals with reasons) and `<w>critique.json` — `final_round.body_hash`
   is that hash (the article this round evaluated):

```json
{"final_round": {"round": 2, "audit_round": 2, "verdict": "PASS", "body_hash": "sha256:…",
                 "audit": {"blocker": 0, "major": 2, "minor": 1},
                 "dismissed": {"blocker": 0, "major": 1}, "deferred": {"major": 1}},
 "audit_log": [{"round": 1, "id": "R1-1", "severity": "MAJOR", "summary": "…", "outcome": "fixed"},
               {"round": 2, "id": "R2-1", "severity": "MAJOR", "tag": "new", "summary": "…",
                "outcome": "deferred"},
               {"round": 2, "id": "R2-2", "severity": "MAJOR", "tag": "new", "summary": "…",
                "outcome": "dismissed"},
               {"round": 2, "id": "R2-3", "severity": "MINOR", "tag": "new", "summary": "…",
                "outcome": "noted"}],
 "decision_log": [{"kind": "routine", "note": "brief approved"},
                  {"kind": "dismissal", "note": "R2-2: app mention count is policy"},
                  {"kind": "deferral", "note": "R2-1: …"}]}
```

   `final_round` describes only the round that evaluated the current article; `audit_round` is
   the number `HRD audit-round` returned for it. `audit_log` (every finding with its outcome:
   `fixed` / `dismissed` / `deferred` / `open` / `noted` — `noted` for every MINOR; `open` for a
   BLOCKER held for a human; a finding re-raised as `unfixed`/`regression` gets a new
   `R<round>-<n>` entry and the earlier one stays as is; update an outcome in place — the last entry per id
   counts) and `decision_log` are append-only across rounds (keep earlier entries when rewriting
   the file); `audit_log` is what a recheck auditor receives.
   `HRD stage pass --stage critique` refuses unless verdict is PASS, `audit_round` equals the
   counted round, every BLOCKER is dismissed and every MAJOR is dismissed or (recheck rounds
   only) deferred — each deferred one logged in this round's `audit_log` with outcome
   `deferred` and tag `new` (any tag on the last round) — and `body_hash` equals the current article hash (a verdict file left over
   from an earlier round cannot vouch for a changed body).

## translation (M6, translator enabled)

After critique, before verify. Read list: the source article, `<w>claims-map.json`,
`style-guide.md`. Output: the translated file (path from `config.paths` locale pattern) and
`<w>claims-map.<lang>.json` mapping translated sentences to the same `C#`. verify then checks
the source and the translation; the critique body hash covers the source only. (Translation
hashing joins the verify target set when M6 is enabled.)

## verify — fact-checker

- **Read list**: the article, `<w>claims-map.json`, `<w>research.md`,
  `docs/editorial/promotion.md` (only to check `owner` claims).
- The fact-checker **extracts factual sentences from the article independently**. A factual
  sentence missing from the claims map is automatically `unsupported`.
- Before spawning, take `HRD hash --slug <slug>`; after the role returns, the editor-in-chief
  writes that value into `verify.json` as `body_hash` (the fact-checker does not compute it).
- **Output**: `<w>verify.md` (per sentence: supported / unsupported / contradicted, with
  claim ids) and `<w>verify.json` `{"body_hash": "<added by the editor-in-chief>",
  "counts": {"supported": n, "unsupported": n, "contradicted": n, "unmapped": n},
  "unsupported_sentences": ["<verbatim>", …]}` — `unmapped` is a subset already counted in
  `unsupported`; each unsupported sentence is listed exactly as it appears in the article
  (markdown included) — or only its parenthetical aside `(…)` when that aside alone is the
  unsupported part and it is not a qualifier, warning or limit; an unsupported sentence that
  warns about or limits another one is also listed under `"unsupported_qualifiers"` and is
  never trimmed (fact-checker persona); `stage pass` refuses a stale `body_hash`.
- Any unsupported/contradicted → first the **trim**, once per article, when nothing is
  contradicted and 1–3 sentences are unsupported (`--attended`: ask the human — trim, loop back
  or hold; otherwise no question):
  1. `HRD trim --topic <id> --begin` — refuses when the counts or the state do not qualify, a
     listed text is not found once verbatim in the body (frontmatter excluded), a listed
     sentence is not whole (it starts a paragraph, a list item or heading, or follows a
     sentence end; it ends with a sentence end; one paragraph, at most 400 characters) or cuts
     through code, a URL or a link, a listed aside sits inside one, a listed text is a warning
     or limit (`unsupported_qualifiers`), a whole heading, or a list item with lines attached
     below it, a translator is enabled, or the article was
     trimmed before (→ loop back below). It snapshots the article and records `verify-gap`
     itself.
  2. Spawn the **writer** for the trim — read list: the article, `<w>claims-map.json`,
     `<w>research.md`, `<w>verify.md`, the texts `--begin` returned. Each is mapped to an
     existing claim that says it or deleted whole; nothing else changes. A text the article
     cannot do without (its CTA, a required section's point) → `BLOCKED` (→ abort, loop back).
  3. `HRD trim --topic <id> --finish` — code checks that the body equals the snapshot minus
     listed texts byte for byte (at a seam only the whitespace the deletion left may change,
     never the line breaks or indentation around it; a list item goes with its mark),
     the claims map changed only for the listed texts, the images and critique files are
     unchanged and the gate passes; critique's verdict then carries over to the shorter body. Refused → `HRD trim
     --topic <id> --abort` (puts back the article, claims map and images critique passed) and
     loop back below (snapshot lost → `--abort --force`, which only closes the trim). While a
     trim is open, `loopback`, `stage check` and `stage pass` refuse; a hold or stop aborts it
     first.
  4. Verify again (new hash, new `verify.json`); a gap again → loop back below.
  The trim is not a loopback (not counted) and runs no editor or auditor round: deletions add
  no claim to check. It is the agents' decision, so it excludes the PR from auto publish
  (`trimmed`) unless the human asked for this publish (`--consent`); the PR body lists the
  deleted passages (`state.json` `trim.removed`, while `trim.status` is `done` — a later
  critique of a rewritten body marks it `superseded`).
- Otherwise → `HRD loopback --topic <id> --cause verify --note "<first unsupported
  sentence>"` (records `verify-gap` with the counts), back to draft. (In `ship`'s re-verify of
  a human's push: delta research instead — no trim, no loopback; see `ship.md` §5.)
- Pass: `HRD stage pass --stage verify` (sets `verified_hash`), then
  `python3 .claude/herald/scripts/integrity.py --record --topic <id>`.
- Any later body change (loopback, translation, session edit) means verify runs again.

## publish

1. Re-check cannibalization (anything published or PR'd since brief). Conflict → hold.
2. `--attended` (`write`/`resume`) and attended `/hrd publish`: session approval and any
   requested changes happen first (`write.md` §2) — so the approved body becomes
   `agent_final_hash`. In-session auto and unattended: skip.
3. `HRD finalize --topic <id>` (entry condition: article == critique hash == verify hash;
   fixes `agent_final_hash` once).
4. Commit on the herald branch: `git add` the article, its images and `<w>` — nothing else;
   `HRD scope --topic <id>` must pass.
5. `git push -u origin <branch>`; then `python3 .claude/herald/scripts/integrity.py --record
   --topic <id> --kind push` (no `--sha`: the record reads HEAD itself).
6. `gh pr create --base <base> --label herald --title "<title>" --body-file <tmp>` — body:
   summary, sources count, audit summary, MINOR findings, `## Late audit findings` (deferred
   MAJORs) if any, `## Unattended decisions` if any (`human` entries go under `## Human decisions`),
   `## Trimmed sentences` (`state.json` `trim.removed`, `trim.status` `done`) if the trim
   deleted anything, and the
   marker `<!-- herald:topic=<id> slug=<slug> -->`.
7. Unattended: `HRD result --topic <id> --status pr-open --pr <n>`.
8. `git switch <base>`.

## Existing branches (stage commands, resume)

A herald branch carries the scripts from when it was forked. Right after `git switch
herald/<topic-id>--<slug>` to a branch that already existed, run `HRD version --against <plugin
version>` (SKILL.md version gate):
- `equal` → continue.
- `newer` → stop: update the installed plugin and restart (a merge cannot fix this).
- `older` or failing, attended or in-session auto (a pre-flow question, `_contract.md` §C): the tracked tree must be clean (`git status --porcelain
  --untracked-files=no` empty; leftovers → commit them as `wip(herald): <id>` first). Explain and,
  on approval, `git fetch origin <base>` and `git merge --no-edit origin/<base>` (brings base's
  scripts; the PR scope check compares from the merge base, so base's files do not count as the
  PR's). Merge refused (no `MERGE_HEAD`) → stop and show git's message; conflict (`MERGE_HEAD`
  exists) → `git merge --abort`, stop and explain. Then run the version check again: still not
  `equal` (base's update has not reached origin yet) → stop. Declined → stop. Every stop
  releases the lock.
- unattended: `HRD result --topic <id> --status held:needs-human --note "tooling: herald version
  mismatch on branch"`, exit 0 (the runner records tooling holds without a growth signal).

## Holds (any stage)

- `cannibalization` / `research` / `rejected`: remove this topic's files **before switching**
  (they are untracked until publish — or, for a refresh, tracked and modified — and would
  follow you to base): restore tracked ones with `git checkout HEAD -- <tracked paths>`, then
  `git clean -fd -- <body path> <image dir> <w>` (only the paths that exist), then
  `git switch <base>`, `git branch -D <branch>`. Attended: `HRD state --topic
  <id> --state held --reason <r>` (records the `hold` signal) then `HRD commit --cmd hold --kind hold -m "chore(herald):
  hold <id>" .claude/herald/topics.json` and `git push origin <base>`. Unattended: `HRD result`
  only.
- Any hold or stop with a trim `open`: `HRD trim --topic <id> --abort` first.
- `needs-human` / `stagnation` / `budget`: keep the branch — commit leftovers as
  `wip(herald): <id>` on it (no push), switch to base, record as above.
