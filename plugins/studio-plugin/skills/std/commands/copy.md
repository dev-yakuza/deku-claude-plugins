# COPY

The copy stage and gate ④b (M1h), per platform (`youtube` in M1): the distributor writes the title, description
and hashtags, Studio checks them against the platform rules, the fact-checker checks the copy against the source, and
the person approves it.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std copy`.

## copy

1. `python3 .claude/studio/scripts/state.py next <video> --enter copy --platform youtube` — exit 3: go to the stage
   it names.
2. Spawn the distributor (`std-distributor`) with `work/brief.md`, the script, the render's `.chapters.txt`,
   `.claude/studio/platforms/youtube.md` and `CREDITS.yaml`. It writes `studio/copy/<video>/<lang>/youtube.md`.
3. Spawn the fact-checker (`std-fact-checker`) with the copy, `work/<lang>/claims-map.json` and the source copy: it
   judges the copy's sentences in `work/<lang>/copy-verify.youtube.json` and sets `copy_excerpts.youtube` in the
   claims map to exactly their excerpts.
4. `python3 .claude/studio/scripts/validate_copy.py <video> --platform youtube` — the platform file is checked by a
   person (`checked`; until then every copy fails — tell the person), limits, required notices, every credit line, the
   render's chapters, no home path, in-house term, `<` or `>`, every sentence with a number or a term of the
   excerpts judged with excerpts in the source, and `copy_excerpts` equal to them. Exit 1: fix what it lists.
5. External audit: as in `commands/verify.md` step 5, with the copy and the source copy.
6. `python3 .claude/studio/scripts/state.py stage-done <video> copy --platform youtube`.

## Gate ④b

1. `python3 .claude/studio/scripts/state.py shown <video> 4b --platform youtube` right as you show the copy — it
   prints `hash12 <h12>` and `in the question: 근거: "<sentence>" ← "<excerpt>"` lines (one per fact of the copy, or one
   `④b 근거 목록 파일: …` line when there are many — open that file for the person).
2. Ask with AskUserQuestion: `[<video>] ④b 배포용 글 — <copy path> · hash <h12>`, **every `in the question:` line
   exactly** (the guard requires each one), the auditor's findings; options
   `승인 <video> <h12>` and "고칠 곳이 있다". Then, in a later message and alone — never in the same message as the
   question — run `python3 .claude/studio/scripts/state.py approve <video> 4b --expect <h12> --platform youtube`.
3. When the person edits the copy themselves: run steps 3–6 of copy again, then show and ask again.

After ④b the video is ready for its commit (M1i).

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
