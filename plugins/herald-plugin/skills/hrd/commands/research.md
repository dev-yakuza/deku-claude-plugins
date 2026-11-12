# RESEARCH — run one stage (`/hrd research <topic-id>`)

Runs only the **research** stage of `atoms/_stages.md` for one topic, for repairs and reruns.
The full flow is `/hrd write`; continuing a stopped flow is `/hrd resume`.

1. `HRD lock acquire --cmd research` (release on every exit).
2. The topic's work must exist on its herald branch: `git switch herald/<topic-id>--<slug>`
   (find it with `HRD status`), then the version check in `atoms/_stages.md` § Existing
   branches. For `brief` on a fresh topic use `/hrd write` instead.
3. Entry condition: `HRD stage check --topic <topic-id> --stage research` — if it names an earlier
   stage, stop and tell the user to rerun that stage first. Do not edit `state.json`.
4. Execute the stage exactly as `atoms/_stages.md` § research describes (read list, role, outputs,
   checks, `HRD stage pass`). When the topic is already past research, this is a human's rerun:
   `HRD stage pass --topic <topic-id> --stage research --rerun` (0.21.0 — the guard asks; refused
   unattended and in a `--ship` run). Tell the human first: a rerun may change `## Image candidates`
   (fixed otherwise after the first pass), and the new candidates decide which places may get an AI
   stand-in. A research fix is no rerun (no `--rerun`). Right after a brief rerun the topic is at
   research again: a plain `stage pass` (no `--rerun`) fixes the new candidates.
5. Report the result and the next stage. A body change invalidates later stages: after
   `draft`, both `critique` and `verify` must run again before `publish`.
