# CRITIQUE — run one stage (`/hrd critique <topic-id>`)

Runs only the **critique** stage of `atoms/_stages.md` for one topic, for repairs and reruns.
The full flow is `/hrd write`; continuing a stopped flow is `/hrd resume`.

1. `HRD lock acquire --cmd critique` (release on every exit).
2. The topic's work must exist on its herald branch: `git switch herald/<topic-id>--<slug>`
   (find it with `HRD status`). For `brief` on a fresh topic use `/hrd write` instead.
3. Entry condition: `HRD stage check --topic <topic-id> --stage critique` — if it names an earlier
   stage, stop and tell the user to rerun that stage first. Do not edit `state.json`.
4. Execute the stage exactly as `atoms/_stages.md` § critique describes (read list, role, outputs,
   checks, `HRD stage pass`).
5. Report the result and the next stage. A body change invalidates later stages: after
   `draft`, both `critique` and `verify` must run again before `publish`.
