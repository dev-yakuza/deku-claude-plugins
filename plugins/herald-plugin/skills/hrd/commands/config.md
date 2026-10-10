# CONFIG — dials and off-switches (`/hrd config [key value]`)

Shows `.claude/herald/config.json` in `config.language` with what each dial does; with
`key value` changes one dial. Plan §3.5.

- Protected keys (`autonomy`, `budget`, `commands`, `paths`, `base_branch`, `roles`, `models`)
  are guarded: the edit triggers an `ask` — the human approves it on the record (INV1/INV2).
  Turning on `autonomy.publish: auto` deserves a one-line warning: PRs then merge and deploy
  without per-PR approval (still excluding dismissals, assumptions and image changes).
- `language` is free to change.
- After editing: `HRD lock acquire --cmd config`, base clean, `HRD sync`,
  `HRD commit --cmd harness --kind config -m "chore(herald): config <key>"
  .claude/herald/config.json`, `git push origin <base>`, release the lock.
