# VERIFY

The verify stage and gate ① (M1e): the fact-checker judges every sentence against the source copy, Studio's check
turns its draft into `verify.json` and `verify.md`, an external auditor reads the result, and the person approves the
script.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std verify`.

1. `python3 .claude/studio/scripts/state.py next <video> --enter verify` — exit 3: go to the stage it names.
2. Spawn the fact-checker (`std-fact-checker`) with the script, `s2v inspect`'s screen text, `s2v sentences`,
   `work/<lang>/claims-map.json`, `work/source.md` and `work/source/`. It writes only
   `work/<lang>/verify.draft.json`.
3. `python3 .claude/studio/scripts/check_claims.py <video>` — every excerpt in the source copy, no `unsupported` or
   `contradicted`, every `fact` mapped to claims, every sentence and on-screen text judged. It writes
   `verify.json` and `verify.md` (never write them yourself). Exit 1:
   `python3 .claude/studio/scripts/state.py loop <video> verify`, then fix the script or the claims (the writer) and
   run the fact-checker again. The third loop holds the video (`held:stagnation`, exit 4): ask the person.
4. `python3 .claude/studio/scripts/state.py stage-done <video> verify`.
5. **External audit**: run `git status --porcelain --untracked-files=all` and `shasum` on the files you will pass,
   spawn `std-auditor` with the script, `verify.md` and the source copy, then run both again. If anything changed,
   discard its result. It only reads (the guard denies its writes and its non-reading commands). Show its findings to
   the person with ①.
6. **Gate ①**: `python3 .claude/studio/scripts/state.py shown <video> 1` (right as you show `verify.md` and the
   script) prints `hash12 <h12>`. Ask with AskUserQuestion: `[<video>] ① 대본 — <script path> · hash <h12>`, the
   auditor's findings, every `원본이 begin 뒤에 커밋됨: <sha> <subject> (<diffstat>)` line `record-source` printed
   (the guard requires each one) — before asking, run `git show <sha> -- <source path> <image paths>` for each and
   show the person what changed — options `승인 <video> <h12>` and "고칠 곳이 있다". Then, in a later message and alone —
   never in the same message as the question — run
   `python3 .claude/studio/scripts/state.py approve <video> 1 --expect <h12>`.
   "고칠 곳이 있다": take the person's notes back to the script stage.

Anything that changes after `shown` (the script, `verify.json`, `verify.md`) needs `shown` and the question again.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
