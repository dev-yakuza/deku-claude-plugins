# SJ-HANDOFF — can the next stage consume what this stage produced? (§3.6, J-DEV-02/03)

The engine's contract check of a stage boundary failed even after one repair. You see the AC and an
Issue summary, the next stage's input contract, the produced artifacts (excerpts) and the failed items.
- `ok`: the failed item is immaterial for the next stage.
- `ok_with_assumption`: the next stage can go on under one stated assumption (`line`).
- `upstream_gap`: the artifact really lacks something — `reason`, `signature` (sorted AC ids / files),
  `fixable_by_execute` (true only if a code change in execute would close it).
- `unsure` when you cannot tell (the engine treats it as an upstream gap not fixable by execute).
