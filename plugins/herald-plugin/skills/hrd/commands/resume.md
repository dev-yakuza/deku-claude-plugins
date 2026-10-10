# RESUME — continue a stopped article (`/hrd resume <topic-id>`)

Continues from `state.json.stage` on the topic's local herald branch. Works for interrupted
runs and for preserved holds (`needs-human`, `stagnation`, `budget`). Plan §3.2.1.

1. `printenv HRD_UNATTENDED`; `HRD lock acquire --cmd resume` (keep the token; `HRD lock release
   --cmd resume --token <t>` on every exit path).
2. `HRD status` → find the topic. Derived state must be `in-progress` (local branch) or a
   stored `held:needs-human|stagnation|budget` with a preserved branch. Anything else: explain
   (`pr-pending` → `/hrd ship`; `queued` → `/hrd write`; cleaned holds → `/hrd status
   --requeue`) and stop.
3. Preserved hold: show the human why it stopped (last `critique.md`/`verify.md`, the hold
   note) and ask how to proceed (attended). Unattended resume of a held topic is not allowed —
   only the batch runner's one retry of an incomplete child uses `resume`.
4. `git switch herald/<topic-id>--<slug>`; read `.claude/herald/work/<topic-id>/state.json`.
5. If `stage` is `brief` and `slug` is null, run brief as in `write.md`. Otherwise run from
   `stage` onward through publish exactly as `write.md` §1–§3 (entry checks catch stale
   artifacts: rerun the stage they name).
6. If the topic's stored state was `held`, clear it once the PR exists (an open PR then derives
   `pr-pending`): `git switch <base>`, `HRD state --topic <id> --state queued --note "resumed
   to PR"`, `HRD commit --cmd hold --kind hold -m "chore(herald): resume <id>"
   .claude/herald/topics.json`, `git push origin <base>`.
