# BRIEF

The brief stage of a video whose source is recorded (M1e): the content strategist chooses the claims and the role
structure, and Studio itself computes the expected length from the chosen excerpts.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std brief`.

1. `python3 .claude/studio/scripts/state.py next <video> --enter brief` — exit 3: go to the stage it names.
2. Spawn the content strategist (`std-strategist`) with `work/source.md`, `.claude/studio/formats/<kind>.md` and the
   platform rules. It writes `work/brief.json` (`claims` · `roles` · `outputs` · `platforms`) and `work/brief.md`.
3. `python3 .claude/studio/scripts/state.py record-brief <video> --from work/brief.json` — it prints
   `estimated length <s> s`: the normalized characters of the chosen excerpts ÷ the format's `chars_per_sec`. The
   strategist's own estimate is never used.
   - Exit 1: the estimate is outside the format's length range, a chosen claim is not in `work/source.md` (or its
     excerpt is not in the source copy), or the format cannot be read — spawn the strategist again with the message.
   - Exit 3: the source's images are not checked (run `/std source` to its end), or approved outputs would be removed
     (ask the person; removing them is `exclude-output`).
4. `python3 .claude/studio/scripts/state.py next <video>` — the next stage (script).

Never edit the format file to make a brief fit: only a person changes it.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
