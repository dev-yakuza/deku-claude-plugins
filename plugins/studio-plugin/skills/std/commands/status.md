# STATUS

**Not implemented yet** (Studio 0.0.x). Milestone: **M1** (completed in M1i).

What it will do: progress of videos and actors; `--unlock`.

Do nothing else. Tell the user (in their language) that `/std status` arrives with milestone M1,
then show `help` (`<<SKILL_DIR>>/commands/help.md`).

<!-- Pieces that exist already (M1b), for the M1i command — do not run them from this file yet:
`python3 .claude/studio/scripts/state.py status [--json]` lists each video's languages (status, stage, held state),
approvals by the proxy mode, backup warnings, and "harness changes not committed" (the paths a harness commit would
stage; `begin` and `stage-done` wait for that commit). A leftover pronunciation merge of a refused video commit is
shown with how to clear it (commit that video, or `git checkout -- .claude/studio/pronounce.json`). -->
