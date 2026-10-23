# ABANDON

**Not implemented yet** (Studio 0.0.x). Milestone: **M1** (completed in M1i).

What it will do: stop a video (or one language); asks first.

Do nothing else. Tell the user (in their language) that `/std abandon` arrives with milestone M1,
then show `help` (`<<SKILL_DIR>>/commands/help.md`).

<!-- Pieces that exist already (M1b), for the M1i command — do not run them from this file yet:
the person answers an AskUserQuestion that starts with `[<video>]` and offers the fixed option `중단 <video> <lang>`;
then, in a later message and alone, `python3 .claude/studio/scripts/state.py abandon <video> [--lang <lang>]` marks
the language aborted (the committed script stays). -->
