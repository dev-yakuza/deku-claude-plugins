# BOARD

The board stage, visual-check and gate ③ (M1g), per output (`youtube` in M1): the visual director decides how the
approved script looks, the person approves each picture's credits, Studio checks every picture, s2v takes stills, and
the person approves them.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std board`.

## board

1. `python3 .claude/studio/scripts/state.py next <video> --enter board --output youtube` — exit 3: go to the stage it
   names.
2. Spawn the visual director (`std-visual-director`) with the script, `work/assets.json`, `work/source.md` and the
   brand. It changes only presentation attributes in the script and writes `work/<lang>/board.md` and
   `CREDITS.draft.yaml` (JSON).
3. **Credits** — for every picture the script shows:
   - `python3 .claude/studio/scripts/state.py credit-preview <video> <script_src>` prints eight `key=value` lines
     and `label 출처 <video> <h12>` (exit 1: fix the draft as it says).
   - Ask with AskUserQuestion (at most 4 pictures per call, one question each): `[<video>] 출처 — <script_src> · hash
     <h12>` and **all eight lines exactly as printed**; options `출처 <video> <h12>` and "고칠 곳이 있다". Then, in a
     later message and alone — never in the same message as the question — run
     `python3 .claude/studio/scripts/state.py credit <video> <script_src> --expect <h12>`. Exit 6 with
     `fields-not-shown`: the question missed a line — ask again.
   - "이전 승인 <v>" means another video approved the same entry: ask anyway (every video records its own).
4. `python3 .claude/studio/scripts/check_assets.py <video> --output youtube` — s2v check, content and voice unchanged
   since ②, every picture usable, unchanged and credited (a third-party or unknown image needs `public_ok: true` and
   a license). Exit 1: fix what it lists (a changed entry needs `credit` again).
5. `python3 .claude/studio/scripts/state.py stage-done <video> board --output youtube`.

## visual-check

1. `python3 .claude/studio/scripts/state.py next <video> --enter visual-check --output youtube`.
2. `python3 .claude/studio/scripts/run_s2v.py snapshot <video> --output youtube` — it records `shown 3 --begin`, takes
   the stills and records `--end` (exit 1 "changed during the snapshot": run it again).
3. `python3 .claude/studio/scripts/state.py stage-done <video> visual-check --output youtube`.

## Gate ③

1. External audit (public videos): as in `commands/verify.md` step 5, with the contact sheet and the stills.
2. Open the contact sheet and the stills (`open <path>`); the last `shown 3 … --end` printed `hash12 <h12>`.
3. Ask with AskUserQuestion: `[<video>] ③ 정지 화면 — youtube · hash <h12>`, the auditor's findings; options
   `승인 <video> <h12>` and "고칠 곳이 있다". Then, in a later message and alone — never in the same message as the
   question — run `python3 .claude/studio/scripts/state.py approve <video> 3 --expect <h12> --output youtube`.
4. "고칠 곳이 있다": back to board with the person's notes.

Replacing an image after ③ sends the work back to board (② stays: the audio did not change).

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
