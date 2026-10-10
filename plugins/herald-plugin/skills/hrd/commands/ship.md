# SHIP — publish approved articles (`/hrd ship [topic-id|slug|PR …]`, `--reverify <id>`, `--deploy-only <id …>`, `--auto`)

The only place Herald publishes. Plan §3.2.2 (steps 1–9). Accuracy floor: `atoms/_invariants.md`.
`<base>` = `config.base_branch`. Every `HRD …` is its own Bash call.

`--auto` (batch ship child, `HRD_UNATTENDED=1`) differs: step 1 does not sync (base must
already contain `origin/<base>`); step 2 runs `HRD reverts list` and `HRD integrity --report`
only — any pending revert, non-`ok` row or flag → stop without merging; **every** stop writes
`HRD result --topic ship --status merged --merged --note "<reason>"` (empty list) so the runner
can still record reverts; step 5 never re-verifies — a head
that differs from the ledger → skip that PR; after step 6 write the round result with
`HRD result --topic ship --status merged --merged <PR numbers…>` and stop (the runner does 7–9
and re-checks the merges against GitHub).

Variants: default (all steps) · `--reverify <id>` (steps 1, 2, 7, 8, 9 for one article after a
human fixed it on base) · `--deploy-only <id …>` (steps 1, 2, 7, 8, 9; the ids are articles
merged outside Herald → external deploy targets) · `--auto` (batch ship child only: step 4 is
skipped, merges limited to `HRD_AUTO_PRS`, steps 7–9 belong to the runner).

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
     body/images from the latest ledger SHA, `git show <sha>:<path>`); open the PR and let the
     human merge it.

## 3. Pending PRs

`gh pr list --label herald --state open --json number,title,headRefName,headRefOid`. For each
PR first `HRD fetch-pr --pr <n>` (a human may have pushed to it; the head then lives at
`refs/remotes/origin/pr-<n>`) and use that ref below. For each
(or the ones named): summary — title, category, audit summary (from `critique.json` at the PR
head), latest `/hrd review` finding for it if any (unresolved BLOCKER → warning), verify counts,
"body differs from verified" (`HRD hash --slug <s> --rev <headRefOid>` vs `HRD ledger show`),
"images changed", cannibalization re-check, and `HRD scope --topic <id> --rev <headRefOid>`.

## 4. Per-PR human approval (skipped by `--auto`)

approve / skip this time (no state change) / decline (reason → `HRD state --topic <id> --state
declined --reason <short-reason>`, `gh pr close <n>`, delete the remote branch, `HRD signal
--kind ship-decline`).

## 5. Re-verify (before checking out the PR)

1. With base scripts, before switching: scope must pass; if the PR head hash ≠ the ledger's
   `verified_hash` (a human pushed changes), re-verify:
2. `git switch -C <branch> refs/remotes/origin/pr-<n>` (the local branch follows the human's
   pushed head); run the gate (`HRD gate --topic <id>`) and verify (`atoms/_stages.md` § verify). If
   unsupported sentences remain, **delta research**: the researcher sources only those
   sentences and appends `C#` to `research.md`; the fact-checker adds the mappings to
   `claims-map.json`; a PR comment `herald-source: <sentence> <URL>` from a human counts as a
   source. Image-only changes still run the gate and verify (the hash covers images).
3. Pass → `HRD stage pass --topic <id> --stage verify --amend`, commit the artifacts, push,
   `integrity.py --record --topic <id> --kind push --sha <new head>`. Fail →
   `held:verify-after-human-edit` (PR stays open), next PR.
4. Note the verified head SHA. `git switch <base>`.

## 6. Merge

`gh pr merge <n> --squash --match-head-commit <verified sha> --delete-branch` (head changed →
back to §5). Add to the deploy set. `HRD sync`; `git branch -D` the local herald branch.
`--auto`: merge only PRs in `HRD_AUTO_PRS`, all §5 checks done for every target first; do
**not** run `HRD sync` between merges (merging needs no local base; the runner syncs); then
write the round result file and stop — the runner does 7–9.

## 7. Deploy

1. `HRD integrity --predeploy` must be `ok` (HEAD's full Herald set vs ledger, clean tree, no
   untracked build inputs, no residue). Not ok → no deploy; commit only the non-deploy records
   (declines, holds) as `HRD commit --cmd ship --kind abort …` (unpushed), stop.
2. If the deploy set (or `--deploy-only` targets) is non-empty and `config.commands.deploy` is
   set: run it once (the guard asks — confirm it is this step). Failure → `git checkout --
   <deploy_artifacts>`, merged articles stay merged-unrecorded, stop.

## 8. URL check

For each deployed article: open `config.site.base_url` + `url_pattern` (WebFetch or `curl -sI`)
with retries for up to ~10 minutes. Failures stay merged-unrecorded for the next ship.

## 9. Record and push

- Published Herald articles: `HRD record-published --topic <id> --slug <slug> --pr <n>`.
- `--deploy-only` targets: `HRD mark-published --topic <id> --slug <slug>`.
- Signals: per merged PR, the diff between `agent_final_hash` content (state.json at the first
  Herald push) and the merged body → `HRD signal --kind human-edit --topic <id> --data
  '{"diff_summary": "...", "lines_changed": n}' --human-reviewed true`.
- `HRD commit --cmd ship --kind ship -m "chore(herald): ship <ids>" .claude/herald/topics.json
  .claude/herald/published.json <deploy_artifacts>` (artifacts even if a URL failed), then
  `git push origin <base>`; refused → `HRD sync` and push once more; still refused → leave it
  unpushed (next ship step 1 picks it up) and say why (branch protection?).
