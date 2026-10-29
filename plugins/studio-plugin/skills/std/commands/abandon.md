# ABANDON

Stop a video, or one of its languages (M1i). The video id is the first argument of `/std abandon`.

Rules: one command per Bash call, literal values. Shared rules: `atoms/_contract.md`.

1. `python3 .claude/studio/scripts/state.py status <video>` — show the person what stops (the language, its stage).
2. Ask with AskUserQuestion: `[<video>] 중단 — <lang>`, what is kept (a committed script stays; the work files stay
   on this machine) and what is not; options `중단 <video> <lang>` and "계속하기". Then, in a later message and
   alone — never in the same message as the question — run
   `python3 .claude/studio/scripts/state.py abandon <video> --lang <lang>`.
3. An abandoned language exempts nothing any more (its approved readings no longer count for the shared dictionary).

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
