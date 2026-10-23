# RESUME

**Not implemented yet** (Studio 0.0.x). Milestone: **M1** (completed in M1i).

What it will do: continue a video, re-checking held states.

Do nothing else. Tell the user (in their language) that `/std resume` arrives with milestone M1,
then show `help` (`<<SKILL_DIR>>/commands/help.md`).

<!-- Pieces that exist already (M1b), for the M1i command — do not run them from this file yet:
held:lock (the machine lock was busy, s2v exit 73) is left with
`python3 .claude/studio/scripts/state.py release-lock <video>` — no person's answer needed; it asks s2v itself
(`services status`) and exits 4 while the lock is still busy. Every other held state is the person's (unlock with
their answer, or the gate it waits for); release-lock refuses them (3). -->
