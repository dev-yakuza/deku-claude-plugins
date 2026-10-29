# MAKE

One video end to end: `make <source> --kind youtube`. **So far (M1h) it runs to gate ④b**; the video commit
arrives with M1i — stop after ④b and tell the person what is next.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`.

1. `python3 .claude/studio/scripts/state.py begin <video> --source <path> --kind youtube` — the writing must be
   committed (exit 3 otherwise: ask the person to commit it).
2. The stages so far, each with its own document: `commands/source.md` → `commands/brief.md` →
   `commands/script.md` → `commands/verify.md` (ends with gate ①). Then the voice section below.

## cast

1. `python3 .claude/studio/scripts/state.py next <video> --enter cast` — exit 3: go to the stage it names.
2. Write the default narrator into the script's frontmatter, one entry per speaker of the narration, with the voice
   and style of an actor of `studio/cast/<id>/status.json` exactly: `cast:` / `  narrator: { voice: "qwen:Sohee",
   style: "<its style>" }`. Change nothing else of the script (its content hash must stay ①'s).
3. Readings: for each Japanese or other word the narration must read in a set way, add it under the frontmatter
   `pronounce:` (`  空港: 쿠우코오`), and write `work/<lang>/pronounce-changes.json` — a flat JSON object of exactly
   what `pronounce` adds or changes against `.claude/studio/pronounce.json` (`{}` when nothing).
4. `python3 .claude/studio/scripts/check_assets.py <video> --actors` — s2v lint (`unread-word` fails from here on),
   content unchanged, the cast in the roster, the readings file. It prints `reading elsewhere: …` for readings that
   differ from HEAD or another video in progress — information for ②, not a failure. Exit 1: fix what it lists.
5. `python3 .claude/studio/scripts/state.py stage-done <video> cast`.

## tts

1. `python3 .claude/studio/scripts/state.py next <video> --enter tts`.
2. `node <s2v>/packages/cli/dist/main.js services status --json` — when `busy.tts` is not null, run
   `python3 .claude/studio/scripts/state.py hold <video> lock --reason "<the busy line>"` and stop.
3. With `run_in_background`: `python3 .claude/studio/scripts/lock.py run --kind tts -- node
   <s2v>/packages/cli/dist/main.js tts <script path>`.
   - Exit 73: `python3 .claude/studio/scripts/state.py hold <video> lock --reason "<the busy line>"`; when the machine is
     free, `python3 .claude/studio/scripts/state.py release-lock <video>` and run it again.
   - Exit 128+n (a signal): tell the person it stopped; `/std resume <video>` runs it again (s2v reuses what it
     finished).
4. `python3 .claude/studio/scripts/check_tts.py <video>` — every synthesized line needs ASR (a mock TTS never
   passes), CER within the format's `cer_max`, and the numbers and negations heard as written. Exit 1 with a
   `retry:` line: run that line (under lock.py, in the background), then check again. After two retries a line is
   exempted (`work/<lang>/exemptions.json`, shown at ②); Studio counts a retry only when s2v kept another take.
   A `warning:` about the length goes into the ② question.
5. `python3 .claude/studio/scripts/state.py stage-done <video> tts`.

## audition

1. `python3 .claude/studio/scripts/state.py next <video> --enter audition`.
2. `python3 .claude/studio/scripts/audition.py <video>` — joins the longest sentence, a sentence with a number or a
   name, a sentence with each reading change, every sentence changed since the last ②, and every exempted line into
   `studio/out/<video>/<lang>/audition/narrator.wav` with `audition.md`. Exit 2: ffmpeg is missing (tell the person).
3. `python3 .claude/studio/scripts/state.py stage-done <video> audition`.

## Gate ②

1. `python3 .claude/studio/scripts/state.py shown <video> 2` right as you open `narrator.wav` (`open <path>`) and
   show `audition.md` — it prints `hash12 <h12>` and `in the question: …` lines: one per exempted line
   (`면제 <id>: "<text>" → 들림 "<heard>" (CER x)`), one per reading change (`발음 <written> → <reading>`) and the
   readings that differ elsewhere — or, when there are too many, one `② 목록 파일: …` line (open that file for the
   person).
2. Ask with AskUserQuestion: `[<video>] ② 오디션 — <narrator.wav path> · hash <h12>`, **every `in the question:` line
   exactly** (the guard requires each one), the length warning if any; options `승인 <video> <h12>` and "고칠 곳이 있다". Then, in a later message and alone — never in the same message
   as the question — run `python3 .claude/studio/scripts/state.py approve <video> 2 --expect <h12>`. It records the
   sentences heard and writes `work/<lang>/pronounce-approved.json` (never write it yourself).
3. "고칠 곳이 있다": change readings (cast) or retry lines (tts) and go through the section again.

Anything that changes after `shown` (the audition, the exemptions, the readings) needs `shown` and the question again.

## board · visual-check · ③

`commands/board.md` (board with the credits, visual-check, gate ③).

## render · ④a · copy · ④b

`commands/render.md` (render, gate ④a), then `commands/copy.md` (copy, gate ④b).

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
