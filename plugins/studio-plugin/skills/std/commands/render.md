# RENDER

The render stage and gate ④a (M1h), per output (`youtube` in M1): the approved script rendered from the locked
audio, then the person approves the video, its thumbnail and its chapters.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std render`.

## render

1. `python3 .claude/studio/scripts/state.py next <video> --enter render --output youtube` — exit 3: go to the stage it
   names.
2. `python3 .claude/studio/scripts/check_scope.py <video>` and
   `python3 .claude/studio/scripts/check_assets.py <video> --output youtube` again (nothing may have changed since ③).
3. With `run_in_background`: `python3 .claude/studio/scripts/run_s2v.py render <video> --output youtube`. The
   wrapper decides the proxy watermark from the approvals (never pass one). Exit 1: the render failed — show the
   person the `CHECK FAILED` line it printed.
4. `python3 .claude/studio/scripts/state.py record-render <video> --output youtube` — exit 4 `held:render`: the render
   was not clean; ask the person.
5. `python3 .claude/studio/scripts/state.py stage-done <video> render --output youtube`.

A video approved in the proxy mode renders with a watermark (`.proxy.mp4`). When a person takes it over, the earlier
gates are approved by the person again; the wrapper then renders without the watermark, and ④a is asked again.

## Gate ④a

1. External audit: as in `commands/verify.md` step 5, with the thumbnail, the chapters and the stills of ③.
2. `python3 .claude/studio/scripts/state.py shown <video> 4a --output youtube` right as you open the mp4, the
   thumbnail and the chapters (`open <path>`) — it prints `hash12 <h12>`.
3. Ask with AskUserQuestion: `[<video>] ④a 최종 — <mp4 path> · hash <h12>`, the auditor's findings; options
   `승인 <video> <h12>` and "고칠 곳이 있다". Then, in a later message and alone — never in the same message as the
   question — run `python3 .claude/studio/scripts/state.py approve <video> 4a --expect <h12> --output youtube`.
4. "고칠 곳이 있다": back to the stage the change belongs to (board for pictures, cast/tts for the voice).

A new render (any change of the mp4) needs ④a again.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
