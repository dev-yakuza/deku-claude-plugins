# SHIP — publish approved articles (`/hrd ship [topic-id|slug|PR …]`, `--reverify <id>`, `--deploy-only <id …>`, `--auto`, `--session-auto <PR> [--consent]`)

The only place Herald publishes (steps 1–9; step 10 is the attended report). Accuracy floor: `atoms/_invariants.md`.
`<base>` = `config.base_branch`. Every `HRD …` is its own Bash call.

`--auto` (batch ship child, `HRD_UNATTENDED=1`) differs: step 1 does not sync (base must
already contain `origin/<base>`); step 2 runs `HRD reverts list` and `HRD integrity --report`
only — any pending revert, non-`ok` row or flag → stop without merging; **every** stop writes
`HRD result --topic ship --status merged --merged --note "<reason>"` (empty list) so the runner
can still record reverts; step 5 never re-verifies — a head
that differs from the ledger → skip that PR; after step 6 write the round result with
`HRD result --topic ship --status merged --merged <PR numbers…>` and stop (the runner does 7–9
and re-checks the merges against GitHub).

`--session-auto <PR>` (interactive, `autonomy.publish: auto` or `--ship`, called by `write` —
also when run by `refresh` or `/hrd next` — or `resume` for the PR it just created, while it still holds its lock — step 1
acquires with `--token <the token of the command holding the lock>` and every release is `HRD lock release --cmd ship --token <t>`, a
no-op while nested — the caller's own release ends the lock): all steps for
that one PR, step 4 skipped; refuse if the PR was not created in this session, if `HRD
auto-exclusion --topic <id> --rev refs/remotes/origin/pr-<n>` (after §3's fetch — the work
files live on the PR head; with `--consent` when the caller passed it — the human asked for
this publish, which accepts the agents' logged decisions, a trim, the fact-checker's framings
and Herald-made images — diagrams and the OG card; screenshots and external images only when the
caller's lock carries the `--ship` mark for this topic (`strong: true` in the output: the agent
review confirmed them in draft — never `images-unconfirmed`, a file nobody vouched for) has
anything under `blocking`, or if
`HRD throttle` shows `room` 0. Unless that run was
`--attended` (a human approved the body in the session), the article is published without a
human reading it, so §6 stamps it before merging (below): the stamp keeps it `human_reviewed:
false` and counted in today's throttle even if deploy fails and a later ship records it.

Variants: default (all steps) · `--reverify <id>` (steps 1, 2, 7, 8, 9, 10 for one article after a
human fixed it on base) · `--deploy-only <id …>` (steps 1, 2, 7, 8, 9, 10; the ids are articles
merged outside Herald → external deploy targets) · `--auto` (batch ship child only: step 4 is
skipped, merges limited to `HRD_AUTO_PRS`, steps 7–9 belong to the runner).

A version mismatch found by the re-check after §6's `HRD sync` (only after a merge; SKILL.md version
gate): delete that PR's local herald branch as §6 says, commit any records not yet committed (normally none: §4, §5 and §6 commit as they go) — `HRD
commit --cmd ship --kind abort -m "chore(herald): ship stopped (version)"
.claude/herald/topics.json`, which commits nothing if nothing changed — so the tree is clean for
`/hrd update`, then stop — a nested `--session-auto` stop also ends the calling `write`/`resume`
(release its lock; no further steps): merged PRs stay merged-unrecorded for the next `ship` (after the
update). Release the lock and say which PRs merged. §9's push-retry sync needs no re-check: the
records are already committed and pushing is plain git — push first, then run the check and
report a mismatch.

## 1. Preflight

1. `HRD lock acquire --cmd ship` (release on every exit path).
2. `git switch <base>`; `HRD sync` (fetch + merge; conflict → stop).
3. `git status --porcelain --untracked-files=no` empty, and `HRD integrity --predeploy --report` fields
   `untracked_build_inputs` and `ignored_residue`: untracked files in build inputs → stop and
   list them (they would deploy unverified). Ignored residue (image dirs with no article and
   only gitignored files) → attended: show, ask, then `HRD residue --clean`; `--auto`: stop
   with "cleanup needed — run /hrd ship".
4. `HRD ahead`: commits with `ok: true` (Herald records, sync merges) pass silently; others →
   attended: show and ask; `--auto`: stop.

## 2. Pre-deploy integrity (no deploy inside this step)

1. Removal reverts first: `HRD reverts apply` (labels the original PRs `herald:reverted`, holds
   the topics `reverted`, keyed by revert PR).
2. `HRD integrity --report` (exit 0; `integrity` without `--report` exits 1 when not ok) →
   a row per Herald article (`origin: herald` ∪ merged Herald PRs) that needs something; the
   articles that are `ok` and already recorded are only counted (`ok_count`):
   - `ok` — matches the ledger. If `merged_unrecorded`, add to the **deploy set**.
   - `no-ledger` — no ledger line on this machine: attended → ask "re-verify N articles or
     trust the committed state.json"; trust → `HRD ledger record --topic <ref> --kind trust`
     for each and continue; `--auto` → stop.
   - `mismatch` / `missing` — `HRD shot scan --slug <slug>` first (base runs this version's scripts;
     a slug with no screenshot records finds nothing): anything found → stop the
     whole ship (as step 4) and tell the human to run `HRD shot strip --path <file>` on base and
     commit (and push) the stripped files,
     then `/hrd ship --reverify <id>`; else re-verify (§5 procedure, on base: `.claude/herald/work/<ref>/`;
     a diagram is never rendered on base — its published PNG passes by its render record, and
     `image_warnings` from `stage pass --stage verify --amend` ("the SVG source differs from the
     published picture") go into the step 10 report without stopping the ship),
     the delta artifacts are committed now.
   - `flags` (withdrawn/moved slug reappeared) — attended: explain exits (`--release-slug`,
     `--unwithdraw`, remove the files); `--auto`: stop.
   `--auto`: any non-`ok` row → no merge and no deploy this round; write that to the result
   file and stop.
   **With `translations` in config** each `mismatch`/`no-ledger` row also carries `causes`;
   handle the row by its causes, the strictest wins
   (stop > adopt-pending > re-verify):

   | causes | handling | exits |
   |---|---|---|
   | `moved`, `image_changed`, `source_changed` with no translation in the bundle | re-verify as above (0.8.0); `image_changed` with translations: the gate for **every** language (`HRD gate --topic <ref> --lang <l>`) and verify of the source; `by_lang` of unchanged languages carries over | §2.4 |
   | `translation_changed:<l>` (source unchanged) | re-verify only those languages: their gate, then the fact-checker re-maps the language's sentences to **existing** claim ids only and verifies them; a fact found only in the translation is not delta-researched — it fails | §2.4 ① / ② |
   | `translation_added:<l>` alone | **no re-verify** — an unmapped human translation never enters the ledger through the fact-checker alone. The article is *adopt-pending*: attended ship may continue to §3–§6, but §7 deploys only if integrity is all `ok` after the merges (the `tr-…` adopt PR for it, `/hrd translate <slug> --adopt <l>`, clears it). `--auto`: stop as for any non-`ok` row | adopt, or remove the file |
   | `translation_missing:<l>` | stop — re-verifying the rest would silently accept the deletion | `HRD withdraw-lang <slug> --lang <l>` (attended; then commit and `integrity.py --record --kind withdraw-lang`), or ② restore. Already withdrawn on another machine whose later re-verify this machine's ledger lacks (the record refuses: "differs from what was verified") → record from that machine, or the human removes this topic's lines from this machine's ledger (`.claude/herald/ledger/verified.jsonl`; the guard asks) and records `--kind trust` |
   | `source_changed` / `source_missing` with translations in the bundle | stop — the translations no longer render this source; Herald does not translate onto base | ② restore, then `/hrd refresh <slug> --direction <ref>` (published slug; before the restore save the base diff: `git diff <ledger sha> HEAD -- <bundle paths> > .claude/herald/memory/directions/<ref>.diff`); a merged-unrecorded first publish: ② remove, then `status --requeue <ref> --direction`; `source_missing` meant: remove the rest of the bundle, then ⓪ withdraw |
   | `unknown_path` | stop — a translation pattern changed under published files | put `translations` back, or change it through `/hrd config` |
   | `translation_added` with any other cause | stop | take the added file out of base for now, handle the rest, put it back and adopt |
3. Commit what this step produced (re-verified artifacts, `held:reverted`):
   `HRD commit --cmd ship --kind integrity -m "chore(herald): integrity" <paths>` (do **not**
   push yet); then for each re-verified article `python3 .claude/herald/scripts/integrity.py
   --record --topic <ref> --kind base-commit --sha <that commit>`.
4. Any article that still fails re-verification → **stop the whole ship** (deploy publishes all
   of base). Move its delta artifacts to `.claude/herald/memory/reverify/<id>/`, restore
   `work/<id>/` with `git checkout -- .claude/herald/work/<id>/`, and offer the exits:
   - ⓪ intentionally removed → `/hrd status --withdraw`; slug changed → `/hrd status --move`
   - ① fix the body outside Claude (or by PR), then `/hrd ship --reverify <id>` (a diagram whose
     published PNG was changed on base has no record of what it draws: fix it by a PR that edits
     the SVG — Herald renders it — or restore it with ②)
   - ② removal/restore revert PR: branch `herald-revert/<id>` from `origin/<base>`, label
     `herald-revert` plus `herald-revert:remove` (merged-unrecorded article: revert the whole
     original PR incl. `work/<id>/`) or `herald-revert:restore` (published article: restore the
     body/images from the latest ledger SHA, `git show <sha>:<path>` — the OG path too when it lies
     outside the image directory (from that tree, or deleted when the tree has none); with translations restore
     every bundle path that tree has and **delete** translation files it does not have); open the
     PR and let the human merge it.

## 3. Pending PRs

`gh pr list --label herald --state open --json number,title,headRefName,headRefOid`. For each
PR first `HRD fetch-pr --pr <n>` (a human may have pushed to it; the head then lives at
`refs/remotes/origin/pr-<n>`) and use that ref below. For each
(or the ones named): summary — title, category, audit summary (from `critique.json` at the PR
head) with any deferred MAJORs listed one per line (`audit_log` outcome `deferred` — the
human decides them here) and, for a refresh, any out-of-scope MAJORs one per line likewise
(outcome `out-of-scope`, with the quoted sentence — left for the next refresh), latest `/hrd review` finding for it if any (unresolved BLOCKER → warning), verify counts,
the trimmed sentences (`state.json` `trim.removed` at the PR head while `trim.status` is `done`
— critique's verdict was carried over to that shorter body unseen by the editor and auditor),
the PR body's `## Reader notes`, `## Framings` and `## Research corrections` if any (readability notes the editor did not
send back; sentences the fact-checker treated as the article's own example under a framing),
"body differs from verified" (`HRD hash --slug <s> --rev <headRefOid>` vs `HRD ledger show` — the
default hash is the bundle: source and translations),
"images changed" (with the number of external images and quotations, `HRD image status --topic <id> --rev <headRefOid>`), cannibalization re-check (with the brief's exceptions: a refresh's own
article and what follows it; a following topic's old article — `atoms/_stages.md` § brief), and
`HRD scope --topic <id> --rev <headRefOid>`.
With `translations` in config also: the languages and their verify counts (`verify.json`
`by_lang`), the line "translations were checked by the fact-checker and the gate; no editor or
auditor read them", and `HRD premerge --topic <id> --rev refs/remotes/origin/pr-<n>` — any
`problems` → this PR is not merged this run (also under `--auto` and `--session-auto`): show
them; `base-source-changed` / `base-bundle-changed` / `withdrawn-lang` → recommend decline
(then `/hrd translate` again, or a refresh).

## 4. Per-PR human approval (skipped by `--auto`)

Deferred MAJORs (`## Late audit findings`) and out-of-scope MAJORs (`## Out-of-scope audit
findings (next refresh)` — they stay as candidates for the next refresh) are decided here:
approve accepts them; to fix one,
skip this time and push the fix to the PR (the next ship re-verifies it, §5); or decline.

A PR with screenshots (its head's `<w>screenshots.json`, read with `git show
<headRefOid>:.claude/herald/work/<id>/screenshots.json`; `auto-exclusion` lists `screenshots`):
show them (file links, `mask` categories, the capture column — `human` or `auto <url>
<captured_at>` from the PR body's `## Screenshots`; "replaced by a human" where the blob differs from the
recorded one, shown as `human` without URL or time)
and ask for a **separate confirmation** — "I looked at the screenshots" — before approve; no
merge without it (`atoms/_screenshots.md` §6).

A PR with external images (`auto-exclusion` lists `external-images`): list them from `HRD image
status --topic <id> --rev refs/remotes/origin/pr-<n>` — file links, source page, credit, license
or **quotation — no OG/SNS use**, "replaced by a human" where `replaced` is true — and ask for a
**separate confirmation** "I checked the external images and their attribution" (one question
with two items when screenshots are there too); no merge without it (`atoms/_images.md` §6). Show
diagrams, scenes and the OG card as links (`pr_rows`; a scene with "replaced by a human" when
`replaced` — no separate confirmation, a human confirmed it in draft); an OG line "old title kept"
(`stale_base`) is shown as such, and `HRD image status --rev` `warnings` (a scene whose prompt or
seed a human changed without a new picture) are shown too.

A topic whose `auto_merged_pr` names this open PR (a session-auto stamp whose merge never
happened): on approve or decline, `HRD auto-merged --topic <id> --clear` — a human decided it
now.

approve / skip this time (no state change) / decline (reason → `HRD state --topic <id> --state
declined --reason <short-reason>` (records `ship-decline`), `gh pr close <n>`, delete the
remote branch). Declining a PR held `verify-after-human-edit` because a human edited the source
of a translated article: first save the human's change as a *direction file* —
`git diff <the ledger's push sha> refs/remotes/origin/pr-<n> -- <bundle paths> >
.claude/herald/memory/directions/<id>.diff` — then decline; tell the human to continue with
`/hrd refresh <slug> --direction <id>` (published slug) or `/hrd status --requeue <id>
--direction` (first publish).

After §4, if `topics.json` changed (clears, declines): `HRD commit --cmd ship --kind ship -m
"chore(herald): ship decisions" .claude/herald/topics.json` (not pushed yet) — §5's branch
switch and §7.1 need a clean tree.

## 5. Re-verify (before checking out the PR)

1. With base scripts, before switching: scope must pass; if the PR head hash ≠ the ledger's
   `verified_hash` (a human pushed changes), re-verify — with `translations` in config first
   decide by what the human changed (`HRD premerge` above already refused deletions and added
   languages):
   - the source changed and the PR carries translations → do **not** re-verify: the
     translations no longer render it. Hold `verify-after-human-edit` with the note "source edited
     on a translated article — decline and refresh/requeue with the direction file" (§4 decline).
   - only translations changed → re-verify those languages as in §2's cause table
     (`translation_changed`).
   - otherwise as below.
2. `git switch -C <branch> --no-track refs/remotes/origin/pr-<n>` (the local branch follows the human's
   pushed head; no version re-check: the PR head is re-verified with its own scripts and never
   merged into); run the gate (`HRD gate --topic <id>`) and verify (`atoms/_stages.md` § verify). If
   unsupported sentences remain, **delta research**: the researcher sources only those
   sentences and appends `C#` to `research.md`; the fact-checker adds the mappings to
   `claims-map.json`; a PR comment `herald-source: <sentence> <URL>` from a human counts as a
   source. Image-only changes still run the gate and verify (the hash covers images). First,
   only when the PR head's scripts are 0.15.0 or later (`HRD version` on the head; an older head
   has no `shot` command — a screenshot recorded by any topic of this slug needs 0.15.0, so an
   older head carries none): `HRD shot scan --slug <slug>` (every topic of the slug, refresh
   topics included; nothing recorded → nothing found), and for each
   file it finds `HRD shot strip --path <file>` (a refusal → hold `verify-after-human-edit` with
   its reason), then the gate and verify, so the recorded hashes cover the stripped files
   (`atoms/_screenshots.md` §6). Tell the human now that the stripped originals stay in the PR's
   history (§4 ran before this).
   Then, only when the PR head's scripts are 0.17.0 or later and the repo manages images
   (`atoms/_images.md` §6): `HRD image status --topic <id>` — a diagram under `pending.render_after_push`
   (the human changed its PNG or SVG; a settings change alone never lists one) → `HRD image render
   --topic <id> --after-push` (no limner on this machine
   → the fail path below with `verify-after-human-edit`; tell the human at step 4 next time that a
   PNG edit is replaced by a render of the SVG); then `HRD image og --topic <id>` (no flag; it does
   nothing when the inputs and the file are as recorded); with PR head scripts 0.21.0 or later also
   `HRD image removed --topic <id> --rev <head>` (a picture the human's push took out is that
   human's "go without" for its place — `atoms/_images.md` §6). Scenes are never generated here: a scene
   PNG a human replaced is a human's image (scan, strip, `images`). `needs-human` (a file a human put at the
   OG path, or base's card a human deleted — `unknown_file` ends in `(deleted)`) → attended: ask
   "use this OG image?" (for a deletion: "publish without the OG card?") — yes → `HRD image og --topic <id> --human-push
   --pr <n>` (a refusal: tell the human why — ship from the machine that pushed, or remove the file
   — and skip this PR this time); no → skip this PR this time (the file stays). `--auto`: this PR
   only → the fail path below with `verify-after-human-edit` and the note `human: OG file needs a
   human ship` (the human's file is not moved). When `og` changed the OG (file, `status` or
   `stale_base`), this PR is **not merged this run** (attended and `--auto`): §4 approved the head
   before it — the next ship shows it again; `--session-auto` goes on (§6 recomputes the
   exclusions on the verified head). Commit what `render`/`og` wrote with the artifacts.
   `research_suspects` (a claim in `research.md` found wrong) fail this re-verify — no research
   fix here: the fail path below holds `verify-after-human-edit`; the human resolves it.
3. Pass → `HRD stage pass --topic <id> --stage verify --amend`, commit the artifacts (and any image
   `shot strip` rewrote), `git push origin <branch>`,
   `git rev-parse HEAD` as its own call, then `integrity.py --record --topic <id> --kind push --sha
   <that literal SHA>` (the PR head may carry older scripts that need `--sha`; newer ones check it
   is the pushed HEAD). Fail (or the push is refused: the head moved) → discard this run's
   changes on the PR branch — of `<w>`, the body path, the image dir and the translation paths, `git checkout HEAD -- <those tracked
   in HEAD>` and `git clean -fd -- <those that exist>` (as in `atoms/_stages.md` § Holds; a local commit left by a refused push is dropped by the next `switch -C`) —
   `git switch <base>`, then `HRD
   state --topic <id> --state held --reason verify-after-human-edit` and `HRD commit --cmd ship
   --kind ship -m "chore(herald): hold <id>" .claude/herald/topics.json` (not pushed yet — §7.1
   needs a clean tree); the PR stays open; next PR.
4. Note the verified head SHA. `git switch <base>`.

## 6. Merge

`--session-auto` of a PR no human approved: immediately before `gh pr merge`, `HRD
auto-merged --topic <id> --pr <n> --rev refs/remotes/origin/pr-<n> --sha <verified sha>` (plus
`--consent` when the caller passed it; code checks the ref is the verified head, recomputes the
exclusions there, refuses if any blocks, and keeps the accepted ones for the published
record — refused: do not merge and do not `--clear`; the PR stays pending, report why, stop) and `HRD commit --cmd ship --kind ship -m "chore(herald):
auto-merge <id>" .claude/herald/topics.json` (local only — §9's push carries it out; nothing
runs between the stamp and the merge but the pass below).

`--session-auto` with `--consent` from a `--ship` run (0.20.0 — the lock carries the ship mark;
`--attended --ship` too, after its stamp-free approval): right after that commit (attended: right
before the merge), `HRD lock ship-pass --topic <id> --pr <n> --rev refs/remotes/origin/pr-<n> --sha
<verified sha>`. Code refuses unless the mark is for this topic, the ref is that sha, GitHub says
the PR's head branch is this topic's, in this repository (no fork) and targeting `<base>`, the
topic carries this PR's stamp (not checked attended), today's throttle has room, and the
exclusions recomputed at that head — strong — block nothing. It writes `lock.pass`; the guard then
lets exactly the merge below through (only before the merge). Refused (or GitHub not reachable) →
go on all the same: the guard asks for the merge as before 0.20.0. After a merge that happened
(below, or `gh pr view` says merged) and its `HRD sync`: `HRD lock ship-pass --merged --topic <id>
--pr <n>` — code checks GitHub says that head was merged and the merge commit is in this base,
and records that base commit; only then does the pass cover §7's deploy, and only while base is
still that commit (anything synced later is asked about). Refused → the guard asks for the deploy. If `gh pr merge` fails or is declined, check `gh pr view
<n> --json state,mergedAt` — a non-zero exit can come after the merge itself (branch cleanup):
merged → continue as a successful merge (below); **not** merged → `HRD auto-merged --topic <id>
--clear`, `HRD commit --cmd ship --kind ship -m "chore(herald): auto-merge cleared <id>"
.claude/herald/topics.json`, and stop (a changed head means a human pushed: leave it to an
attended `/hrd ship`, never loop back to §5 here).

`gh pr merge <n> --squash --match-head-commit <verified sha> --delete-branch` — run it exactly
like this, alone: no `cd … &&`, no `2>&1`, no redirection, no variable, no other flag (the guard
asks for anything else; without a pass it asks anyway) (head changed → back to §5). Add to the deploy set. `HRD sync`
(then, in a `--ship` run with a pass, `HRD lock ship-pass --merged --topic <id> --pr <n>`); `git branch -D` the local herald branch.
`--auto`: merge only PRs in `HRD_AUTO_PRS`, all §5 checks done for every target first; do
**not** run `HRD sync` between merges (merging needs no local base; the runner syncs); then
write the round result file and stop — the runner does 7–9.

## 7. Deploy

1. `HRD integrity --predeploy` must be `ok` (HEAD's full Herald set vs ledger, clean tree, no
   untracked build inputs, no residue). Not ok → no deploy; commit any records not yet committed
   (normally none) as `HRD commit --cmd ship --kind abort …` (unpushed), stop.
2. If the deploy set (or `--deploy-only` targets) is non-empty and `config.commands.deploy` is
   set: run it once, as the configured string verbatim, on base — nothing before or after it in
   the same call (the guard asks — confirm it is this step; in a `--ship` run whose pass §6 marked
   `--merged` it lets that exact string through without asking). Failure → `git checkout --
   <deploy_artifacts>`, merged articles stay merged-unrecorded, stop.
3. A `--ship` run: when the deploy step is over (it succeeded, failed or did not run), `HRD lock
   ship-pass --clear` — on every exit after §6 too.

## 8. URL check

For each deployed article: open `config.site.base_url` + `url_pattern` (WebFetch or `curl -sI`)
with retries for up to ~10 minutes — with translations, every translation URL of the bundle too
(`url_pattern` of each `translations.targets` entry whose file exists); the bundle is one
publish: any failed URL leaves the article merged-unrecorded. Failures stay merged-unrecorded for the next ship.

## 9. Record and push

- Published Herald articles: `HRD record-published --topic <id> --slug <slug> --pr <n>` (an
  auto-merge stamp on the topic makes it `human_reviewed: false` by itself).
- `--deploy-only` targets: `HRD mark-published --topic <id> --slug <slug>`.
- Signals: per merged PR, the diff between `agent_final_hash` content (state.json at the first
  Herald push) and the merged body → `HRD signal --kind human-edit --topic <id> --data
  '{"diff_summary": "...", "lines_changed": n}' --human-reviewed <the human_reviewed value
  record-published returned for it>`. With translations, one signal per changed file of the
  bundle: add `"lang": "<l>"` to the data and use that entry's value from record-published
  `entries`.
- `HRD commit --cmd ship --kind ship -m "chore(herald): ship <ids>" .claude/herald/topics.json
  .claude/herald/published.json <deploy_artifacts>` (artifacts even if a URL failed), then
  `git push origin <base>`; refused → `HRD sync` and push once more; still refused → leave it
  unpushed (next ship step 1 picks it up) and say why (branch protection?).

## 10. Report (attended runs only — not `--auto`)

Summarize what was published, declined, held and left merged-unrecorded. For a `--session-auto`
publish nobody approved, also list what was accepted unread (the `accepted` exclusions, the
deferred and out-of-scope MAJORs and dismissals with their reasons, the trimmed sentences, the framings, and in a
`--ship` run the images and screenshots the agent review confirmed or turned down — id, kind, its
one-line note, from `HRD image status --topic <id> --rev <head>` `agent` and `HRD shot status`
`agent_confirmed`; nobody looked at them) — the human sees them now at the latest. A published
topic whose brief kept a `guide:` clause `unsure` (0.23.0 — read from `<w>brief.md` `## Images`
at the PR head, `git show <headRefOid>:<w>brief.md`, or from the PR body's `## Images` paragraph,
`atoms/_images.md` §6): quote each such line and say which clause was read as `only <kinds>`
(the fail-safe) — clarifying that guide line is the human's. A published topic that `follows` an older article: say that the older
one now has `superseded` set and, while `HRD status` lists it under `supersede_pending`, how to
link it — `/hrd refresh <old>` (`refreshable: true`), or by hand. Then
`HRD evolve-readiness`: only when `tier` is `sufficient`, end with one line in
`config.language` (ko example: "성장 신호가 충분히 쌓였습니다(아직 evolve가 쓰지 않은 신호 N건 · 글감 M개) —
`/hrd evolve --dry-run`으로 제안을 확인해 보세요."), N = `signals`, M = `topics` (articles; when
`social_topics` > 0 add "· SNS 일자 K개", K = `social_topics`). Otherwise (or if the
command fails) say nothing about evolve. The nudge is advisory: evolve's own scan decides whether a theme is strong
enough (`sufficient` = one theme — a signal kind, split by `theme` for editor REVISE and auditor
findings and by reason for holds — reached ≥ 3 signals from ≥ 2 topics with something new since the last evolve scan). Run it even if an earlier step stopped the run, as long as step 1
passed.
