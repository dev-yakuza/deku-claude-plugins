# SHIP — publish approved articles (`/hrd ship [topic-id|slug|PR …]`, `--reverify <id>`, `--deploy-only <id …>`, `--auto`, `--session-auto <PR> [--consent]`)

The only place Herald publishes. Plan §3.2.2 (steps 1–9; step 10 is the attended report). Accuracy floor: `atoms/_invariants.md`.
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
and Herald-made images) has
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
   one row per Herald article (`origin: herald` ∪ merged Herald PRs):
   - `ok` — matches the ledger. If `merged_unrecorded`, add to the **deploy set**.
   - `no-ledger` — no ledger line on this machine: attended → ask "re-verify N articles or
     trust the committed state.json"; trust → `HRD ledger record --topic <ref> --kind trust`
     for each and continue; `--auto` → stop.
   - `mismatch` / `missing` — re-verify (§5 procedure, on base: `.claude/herald/work/<ref>/`),
     the delta artifacts are committed now.
   - `flags` (withdrawn/moved slug reappeared) — attended: explain exits (`--release-slug`,
     `--unwithdraw`, remove the files); `--auto`: stop.
   `--auto`: any non-`ok` row → no merge and no deploy this round; write that to the result
   file and stop.
   **With `translations` in config** each `mismatch`/`no-ledger` row also carries `causes`
   (design/herald/01-multilingual.md §3); handle the row by its causes, the strictest wins
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
   - ① fix the body outside Claude (or by PR), then `/hrd ship --reverify <id>`
   - ② removal/restore revert PR: branch `herald-revert/<id>` from `origin/<base>`, label
     `herald-revert` plus `herald-revert:remove` (merged-unrecorded article: revert the whole
     original PR incl. `work/<id>/`) or `herald-revert:restore` (published article: restore the
     body/images from the latest ledger SHA, `git show <sha>:<path>`; with translations restore
     every bundle path that tree has and **delete** translation files it does not have); open the
     PR and let the human merge it.

## 3. Pending PRs

`gh pr list --label herald --state open --json number,title,headRefName,headRefOid`. For each
PR first `HRD fetch-pr --pr <n>` (a human may have pushed to it; the head then lives at
`refs/remotes/origin/pr-<n>`) and use that ref below. For each
(or the ones named): summary — title, category, audit summary (from `critique.json` at the PR
head) with any deferred MAJORs listed one per line (`audit_log` outcome `deferred` — the
human decides them here), latest `/hrd review` finding for it if any (unresolved BLOCKER → warning), verify counts,
the trimmed sentences (`state.json` `trim.removed` at the PR head while `trim.status` is `done`
— critique's verdict was carried over to that shorter body unseen by the editor and auditor),
the PR body's `## Reader notes`, `## Framings` and `## Research corrections` if any (readability notes the editor did not
send back; sentences the fact-checker treated as the article's own example under a framing),
"body differs from verified" (`HRD hash --slug <s> --rev <headRefOid>` vs `HRD ledger show` — the
default hash is the bundle: source and translations),
"images changed", cannibalization re-check, and `HRD scope --topic <id> --rev <headRefOid>`.
With `translations` in config also: the languages and their verify counts (`verify.json`
`by_lang`), the line "translations were checked by the fact-checker and the gate; no editor or
auditor read them", and `HRD premerge --topic <id> --rev refs/remotes/origin/pr-<n>` — any
`problems` → this PR is not merged this run (also under `--auto` and `--session-auto`): show
them; `base-source-changed` / `base-bundle-changed` / `withdrawn-lang` → recommend decline
(then `/hrd translate` again, or a refresh).

## 4. Per-PR human approval (skipped by `--auto`)

Deferred MAJORs (`## Late audit findings`) are decided here: approve accepts them; to fix one,
skip this time and push the fix to the PR (the next ship re-verifies it, §5); or decline.

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
   source. Image-only changes still run the gate and verify (the hash covers images).
   `research_suspects` (a claim in `research.md` found wrong) fail this re-verify — no research
   fix here: the fail path below holds `verify-after-human-edit`; the human resolves it.
3. Pass → `HRD stage pass --topic <id> --stage verify --amend`, commit the artifacts, `git push origin <branch>`,
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
runs between the stamp and the merge). If `gh pr merge` fails or is declined, check `gh pr view
<n> --json state,mergedAt` — a non-zero exit can come after the merge itself (branch cleanup):
merged → continue as a successful merge (below); **not** merged → `HRD auto-merged --topic <id>
--clear`, `HRD commit --cmd ship --kind ship -m "chore(herald): auto-merge cleared <id>"
.claude/herald/topics.json`, and stop (a changed head means a human pushed: leave it to an
attended `/hrd ship`, never loop back to §5 here).

`gh pr merge <n> --squash --match-head-commit <verified sha> --delete-branch` (head changed →
back to §5). Add to the deploy set. `HRD sync`; `git branch -D` the local herald branch.
`--auto`: merge only PRs in `HRD_AUTO_PRS`, all §5 checks done for every target first; do
**not** run `HRD sync` between merges (merging needs no local base; the runner syncs); then
write the round result file and stop — the runner does 7–9.

## 7. Deploy

1. `HRD integrity --predeploy` must be `ok` (HEAD's full Herald set vs ledger, clean tree, no
   untracked build inputs, no residue). Not ok → no deploy; commit any records not yet committed
   (normally none) as `HRD commit --cmd ship --kind abort …` (unpushed), stop.
2. If the deploy set (or `--deploy-only` targets) is non-empty and `config.commands.deploy` is
   set: run it once (the guard asks — confirm it is this step). Failure → `git checkout --
   <deploy_artifacts>`, merged articles stay merged-unrecorded, stop.

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
deferred MAJORs and dismissals with their reasons, the trimmed sentences, the framings) — the human sees
them now at the latest. Then
`HRD evolve-readiness`: only when `tier` is `sufficient`, end with one line in
`config.language` (ko example: "성장 신호가 충분히 쌓였습니다(아직 evolve가 쓰지 않은 신호 N건 · 글감 M개) —
`/hrd evolve --dry-run`으로 제안을 확인해 보세요."), N = `signals`, M = `topics`. Otherwise (or if the
command fails) say nothing about evolve. The nudge is advisory: evolve's own scan decides whether a theme is strong
enough (`sufficient` = one theme — a signal kind, split by `theme` for editor REVISE and auditor
findings and by reason for holds — reached ≥ 3 signals from ≥ 2 topics with something new since the last evolve scan). Run it even if an earlier step stopped the run, as long as step 1
passed.
