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

- **Read list**: `<w>brief.md`, `docs/editorial/sources.md`. The researcher alone reads web
  pages (WebFetch/WebSearch); raw pages never reach other roles.
- **Output**: `<w>research.md` — claims `C1..Cn`, each with source URL, short excerpt, access
  date, confidence. Policy from `sources.md` (banned sources, mention rules) applies.
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
  else the built-in `validate_content.py`) and refuses on errors → loop back to the writer with
  the errors (counts as a loopback; record `gate-failure`).

## critique — subject-expert / search-discovery (if enabled) → editor → external auditor

1. Conditional reviewers first. subject-expert: article + category guide + its domain checklist
   (its persona's Project specifics) → `<w>review-subject-expert.md`. search-discovery:
   article + `search-checklist.md` → `<w>review-search-discovery.md`.
2. **editor** — read list: the article, category guide, `style-guide.md`, exemplars, the
   `<w>review-*.md` notes. The editor writes its round into `<w>critique.md`; the
   editor-in-chief appends auditor findings and dismissals and writes `<w>critique.json`. **Never** `research.md`. Verdict PASS / REVISE / REJECT with strengths,
   weaknesses, revision direction.
   - REVISE → record `revise-weakness`, `HRD loopback`, back to draft (stagnation guard).
   - REJECT → hold `rejected`.
3. **external auditor** — only after the editor's PASS; procedure in `atoms/_auditor.md`.
   Undismissed `BLOCKER`/`MAJOR` → loopback to draft; after the fix, editor → auditor → verify
   run again. `MINOR` → PR body only.
4. Before spawning the editor, take `HRD hash --slug <slug>`. Write `<w>critique.md` (prose:
   verdicts, findings, dismissals with reasons) and `<w>critique.json` — `final_round.body_hash`
   is that hash (the article this round evaluated):

```json
{"final_round": {"round": 2, "verdict": "PASS", "body_hash": "sha256:…",
                 "audit": {"blocker": 0, "major": 1, "minor": 2},
                 "dismissed": {"blocker": 0, "major": 1}},
 "decision_log": [{"kind": "routine", "note": "brief approved"},
                  {"kind": "dismissal", "note": "MAJOR-2: app mention count is policy"}]}
```

   `final_round` describes only the round that evaluated the current article. `HRD stage pass
   --stage critique` refuses unless verdict is PASS, undismissed BLOCKER+MAJOR is 0, and
   `body_hash` equals the current article hash (a verdict file left over from an earlier round
   cannot vouch for a changed body).

## translation (M6, translator enabled)

After critique, before verify. Read list: the source article, `<w>claims-map.json`,
`style-guide.md`. Output: the translated file (path from `config.paths` locale pattern) and
`<w>claims-map.<lang>.json` mapping translated sentences to the same `C#`. verify then checks
the source and the translation; the critique body hash covers the source only. (Translation
hashing joins the verify target set when M6 is enabled.)

## verify — fact-checker

- **Read list**: the article, `<w>claims-map.json`, `<w>research.md`.
- The fact-checker **extracts factual sentences from the article independently**. A factual
  sentence missing from the claims map is automatically `unsupported`.
- Before spawning, take `HRD hash --slug <slug>`; after the role returns, the editor-in-chief
  writes that value into `verify.json` as `body_hash` (the fact-checker does not compute it).
- **Output**: `<w>verify.md` (per sentence: supported / unsupported / contradicted, with
  claim ids) and `<w>verify.json` `{"body_hash": "<added by the editor-in-chief>",
  "counts": {"supported": n, "unsupported": n, "contradicted": n, "unmapped": n}}` —
  `unmapped` is a subset already counted in `unsupported`; `stage pass` refuses a stale
  `body_hash`.
- Any unsupported/contradicted → record `verify-gap`, `HRD loopback`, back to draft.
- Pass: `HRD stage pass --stage verify` (sets `verified_hash`), then
  `python3 .claude/herald/scripts/integrity.py --record --topic <id>`.
- Any later body change (loopback, translation, session edit) means verify runs again.

## publish

1. Re-check cannibalization (anything published or PR'd since brief). Conflict → hold.
2. Attended `write`: session approval and any requested changes happen first (`write.md` §2) —
   so the approved body becomes `agent_final_hash`. Unattended: skip.
3. `HRD finalize --topic <id>` (entry condition: article == critique hash == verify hash;
   fixes `agent_final_hash` once).
4. Commit on the herald branch: `git add` the article, its images and `<w>` — nothing else;
   `HRD scope --topic <id>` must pass.
5. `git push -u origin <branch>`; then `python3 .claude/herald/scripts/integrity.py --record
   --topic <id> --kind push --sha $(git rev-parse HEAD)` — run `git rev-parse HEAD` as its own
   call and pass the literal SHA.
6. `gh pr create --base <base> --label herald --title "<title>" --body-file <tmp>` — body:
   summary, sources count, audit summary, MINOR findings, `## Unattended decisions` if any,
   and the marker `<!-- herald:topic=<id> slug=<slug> -->`.
7. Unattended: `HRD result --topic <id> --status pr-open --pr <n>`.
8. `git switch <base>`.

## Holds (any stage)

- `cannibalization` / `research` / `rejected`: remove this topic's files **before switching**
  (the body and images are untracked until publish and would follow you to base):
  `git clean -fd -- <body path> <image dir> <w>` (only the paths that exist), then
  `git switch <base>`, `git branch -D <branch>`, record `hold`. Attended: `HRD state --topic
  <id> --state held --reason <r>` then `HRD commit --cmd hold --kind hold -m "chore(herald):
  hold <id>" .claude/herald/topics.json` and `git push origin <base>`. Unattended: `HRD result`
  only.
- `needs-human` / `stagnation` / `budget`: keep the branch — commit leftovers as
  `wip(herald): <id>` on it (no push), switch to base, record as above.
