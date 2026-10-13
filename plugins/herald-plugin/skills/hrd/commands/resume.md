# RESUME — continue a stopped article (`/hrd resume <topic-id> [--attended] [--ship]`)

Continues from `state.json.stage` on the topic's local herald branch. Works for interrupted
runs and for preserved holds (`needs-human`, `stagnation`, `budget`). Plan §3.2.1.

1. `printenv HRD_UNATTENDED`; `HRD lock acquire --cmd resume` (keep the token; `HRD lock release
   --cmd resume --token <t>` on every exit path).
2. `HRD status` → find the topic. Derived state must be `in-progress` (local branch) or a
   stored `held:needs-human|stagnation|budget` with a preserved branch. Anything else: explain
   (`pr-pending` → `/hrd ship`; `queued` → `/hrd write`; cleaned holds → `/hrd status
   --requeue`) and stop.
3. Preserved hold: show the human why it stopped (last `critique.md`/`verify.md`, the hold
   note, and whether the one reader-pass send-back is used — `state.json` `reader_revise`, with the last
   `reader.json`) and ask how to proceed — for an `open` BLOCKER (any round), dismiss or fix as in
   `atoms/_stages.md` § critique 3, a fix always under `HRD loopback --human`; record the
   decision in `critique.json` only after step 4's switch and version check — if step 4 stops,
   nothing is recorded and the next resume asks again (asked in every mode but unattended — a pre-flow question: a hold is resumed by a human's
   decision; after it, the rest runs without questions unless `--attended`). Unattended resume of a held topic is not allowed —
   only the batch runner's one retry of an incomplete child uses `resume`.
4. `git switch herald/<topic-id>--<slug>`; read `.claude/herald/work/<topic-id>/state.json`.
   Then the version check in `atoms/_stages.md` § Existing branches. A `trim` still `open`
   (interrupted) → `HRD trim --topic <id> --abort` first (puts back the article critique
   passed; the trim stays used). `stage` `research` with `research_fixes[-1]` `open` (a research
   fix that was held or interrupted) → run the research fix (`atoms/_stages.md` § research).
5. Budget baseline as in `write.md` §0 step 7 (a fresh baseline: resuming is the human's choice
   to spend more). Then: if `stage` is `brief` and `slug` is null, run brief as in `write.md`. Otherwise run from
   `stage` onward through publish exactly as `write.md` §1–§3 (unattended if `HRD_UNATTENDED=1`; else in-session auto by
   default, attended with `--attended`; `--auto` is accepted and means the default; `--ship` as in `write.md` §3) (entry checks catch stale
   artifacts: rerun the stage they name).
6. If the stored state is still the hold this resume lifted (`needs-human`, `stagnation` or
   `budget` — skip if a `--session-auto` ship published it or set its own
   `verify-after-human-edit` hold, or if it stopped on a version mismatch), clear it once the PR
   exists (an open PR then derives
   `pr-pending`): `git switch <base>`, `HRD state --topic <id> --state queued --note "resumed
   to PR"`, `HRD commit --cmd hold --kind hold -m "chore(herald): resume <id>"
   .claude/herald/topics.json`, `git push origin <base>`.
