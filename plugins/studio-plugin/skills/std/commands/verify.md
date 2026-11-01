# VERIFY

The verify stage and gate ① (M1e): the fact-checker judges every sentence against the source copy, Studio's check
turns its draft into `verify.json` and `verify.md`, an external auditor reads the result, and the person approves the
script.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std verify`.

1. `python3 .claude/studio/scripts/state.py next <video> --enter verify` — exit 3: go to the stage it names.
2. `python3 .claude/studio/scripts/check_claims.py <video> --skeleton` — (re)writes `work/<lang>/verify.draft.json`
   with one entry for every narration sentence, on-screen text and scene title to judge (claims and excerpts from the
   claims map, an empty verdict); an entry still in the script keeps what the fact-checker wrote. It prints
   `kept N · added M · dropped K`. Then spawn the fact-checker (`std-fact-checker`) with the script, `s2v inspect`'s
   screen text, `s2v sentences`, `work/<lang>/claims-map.json`, `work/source.md`, `work/source/` and the draft. It
   fills the draft with Edit and writes nothing else.
3. `python3 .claude/studio/scripts/check_claims.py <video>` — every excerpt in the source copy, no `unsupported` or
   `contradicted`, every `fact` mapped to claims, every sentence and on-screen text judged, at most 2 link sentences,
   or a quarter of the judged entries (rounded down) when that is more. It writes `verify.json` and `verify.md` (never
   write them yourself). Exit 1: `python3 .claude/studio/scripts/state.py loop <video> verify`, then fix the script or
   the claims (the writer) and go back to step 2 (`--skeleton`, then the fact-checker). The third loop holds the
   video (`held:stagnation`, exit 4): ask the person.
4. `python3 .claude/studio/scripts/state.py stage-done <video> verify`.
5. **External audit**: run `git status --porcelain --untracked-files=all` and `shasum` on the files you will pass,
   spawn `std-auditor` with the script, `studio/videos/<video>/work/<lang>/verify.md` and the source copy, then run
   both again. If anything changed, discard its result. It only reads (the guard denies its writes and its non-reading
   commands). Show its findings to the person with ①.
6. **Gate ①**: `python3 .claude/studio/scripts/state.py shown <video> 1` (right as you show `verify.md` and the
   script) prints `hash12 <h12>`, an `in the question:` line per commit to the source after begin
   (`원본이 begin 뒤에 커밋됨: <sha> <subject> (<diffstat>)`) and the `question` block (`[<video>] ① 대본 — <script
   path> · hash <h12>` with those lines, up to `end of question`). Before asking, run `git show <sha> --
   <source path> <image paths>` for each commit and show the person what changed. Ask with AskUserQuestion: the
   question is **the block pasted unchanged** — never retype a line (the guard compares each character) — with the
   auditor's findings after it; options `승인 <video> <h12>` and "고칠 곳이 있다". Then, alone as your next tool call, in the
   same turn, right after the answer — do not wait for the person; never in the same assistant message as the question
   — run
   `python3 .claude/studio/scripts/state.py approve <video> 1 --expect <h12>`.
   "고칠 곳이 있다": take the person's notes back to the script stage.

Anything that changes after `shown` (the script, `verify.json`, `verify.md`) needs `shown` and the question again.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
> Exception: when the refusal itself says 'This is not a stop', do what it says — that is not
> reaching the same effect another way.
<!-- /studio:guard-refusal -->
