# MAKE

One video end to end: `make <source> --kind <kind>`, from begin to the video's commit (or, for an internal video, its
end on this machine).

Kinds: `youtube` and `sns` are public; `onboarding` and `explainer` (explaining a document to other members) are
internal. The kind is fixed at begin (another kind is `abandon` and a new begin). An internal video is local: its
folder, renders and copy stay under `studio/local/` on this machine (backed up, never committed). Each kind's lengths
are in `.claude/studio/formats/<kind>.md` (`sns`, `onboarding` and `explainer` are added with `/std update`; without
the file the brief stops); the brief may name only platforms whose file says the kind's `audience`.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`.
Run Studio commands exactly as written: no `| head`, `; echo $?`, `2>&1 | …`, variables or `&&` chains (only
`cd <repo> &&`), and read the whole output. Do not repeat a call whose output is already in the conversation. Show
files to the person with `open <path>` only (never `code`, `vim` or another editor).

**The flow** — print each stage's document when you reach it (`python3 "<<SKILL_DIR>>/scripts/setup.py" doc <stage>`,
short `setup.py doc <stage>` below; never open it with Read) and do exactly what it says:

1. `python3 .claude/studio/scripts/state.py begin <video> --source <path> --kind <kind>` — the writing must be
   committed (exit 3 otherwise: ask the person to commit it). From a public web page (a `youtube` or `sns` video
   only): `state.py begin <video> --url <https url> --kind <kind>` — the address must be on one of `public_domains`,
   with no `#` part and no in-house name (exit 2 says why; exit 4: the internal overlay is missing — ask the person);
   the source stage then starts with `capture.py source` (`setup.py doc source`). When the request asks to stop before steps ("tts 전에
   멈추고 물어봐", "stop before render"), add `--ask-before <steps>` with those of `tts`, `render`, `copy`, `commit`
   (comma-separated), and show the parsed list in your first reply. A later request changes it:
   `python3 .claude/studio/scripts/state.py ask-before <video> <steps|none>`.
2. `setup.py doc source` → `setup.py doc brief` → `setup.py doc script` → `setup.py doc verify` (gate ①).
3. The voice section below: cast → tts → audition → gate ②.
4. `setup.py doc board` (board with the credits, visual-check, gate ③).
5. `setup.py doc render` (render, gate ④a) → `setup.py doc copy` (copy, gate ④b).
6. The video's commit (below), then `state.py done`; an internal video ends without a commit (below).

**Always**
- On every stage: `state.py next <video> --enter <stage>` first; exit 3 means another stage comes first — go there.
  `state.py next <video>` says where the video is after any stop (`setup.py doc resume`). It also prints `scope:`
  (`public` or `internal`), `out:` (the folder of the renders and the audition) and `copy:` (the folder of the platform
  copy) — use those folders, never a path of your own.
- Every person gate is the same: `state.py shown …` as you show the artifact, then AskUserQuestion whose question is
  the `question` block `shown` printed, pasted unchanged — never retype a line (the guard compares each character) —,
  the fixed option, and the approval command alone as your next tool call, in the same turn, right after the answer —
  do not wait for the person; never in the same assistant message as the question.
- The heavy runs — `lock.py run --kind tts -- …` and `run_s2v.py render …` — go with `run_in_background`.
- When `state.py next` prints `ask the person before <step> (they asked)`, ask with AskUserQuestion before the stage's
  first command, and go on only after the answer.
- After a gate approval, continue to the next stage in the same turn. Stop only at a gate, an ask-before step or an
  error, and end the turn with a question — never with a statement that sounds like work continues ("TTS 전에
  멈추고 여쭙겠습니다").
- When the guard refuses something, follow INV9 below: stop and ask; never reach the same effect another way.

## cast

1. `python3 .claude/studio/scripts/state.py next <video> --enter cast` — exit 3: go to the stage it names.
2. The `cast:` block is already in the script (the writer put the default narrator there at the script stage, and ①
   approved it): do not change it. A different narrator after ①, or a script approved without the block (before
   0.0.28), goes back to the script stage (`/std script <video>`): the cast is part of the script the person approved.
3. Readings: for each Japanese or other word the narration must read in a set way, add it under the frontmatter
   `pronounce:` (`  空港: 쿠우코오`), and write `work/<lang>/pronounce-changes.json` — a flat JSON object of exactly
   what `pronounce` adds or changes against `.claude/studio/pronounce.json` (`{}` when nothing).
4. `python3 .claude/studio/scripts/check_assets.py <video> --actors` — s2v lint (`unread-word` fails from here on),
   content unchanged, the cast in the roster, the readings file. It prints `reading elsewhere: …` for readings that
   differ from HEAD or another video in progress — information for ②, not a failure. Exit 1: fix what it lists.
   A `no-visual` failure or a content change is not fixed here: go back to `/std script <video>` as in
   `setup.py doc board` step 4 (only the block is added; the rest of the script stays).
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
   `audition/narrator.wav` with `audition.md` in the `out:` folder `state.py next` prints. Exit 2: ffmpeg is missing (tell the person).
3. `python3 .claude/studio/scripts/state.py stage-done <video> audition`.

## Gate ②

1. `python3 .claude/studio/scripts/state.py shown <video> 2` right as you open `narrator.wav` (`open <path>`) and
   show `audition/audition.md` of the `out:` folder (read it with Read: the block's `read:` line names it) — it
   prints `hash12 <h12>` and `in the question: …` lines: one per sentence `narrator.wav` plays (`- "<text>" — <why>`,
   at most 8), one per exempted line (`면제 <id>: "<text>" → 들림 "<heard>" (CER x)`), one per reading change
   (`발음 <written> → <reading>`) and the readings that differ elsewhere — or, when there are too many, one
   `② 목록 파일: …` line (open that file for the person) — then `read: <audition.md>`, and then the `question` block:
   `[<video>] ② 오디션 — <narrator.wav path> · hash <h12>` with those lines, up to `end of question`.
2. Ask with AskUserQuestion: the question is **the block between `question (…):` and `end of question`, pasted
   unchanged** — never retype a line (the guard compares each character) — with the length warning after it if any;
   options `승인 <video> <h12>` and "고칠 곳이 있다". Then, alone as your next tool call, in the same turn, right after the
   answer — do not wait for the person; never in the same assistant message as the question — run
   `python3 .claude/studio/scripts/state.py approve <video> 2 --expect <h12>`. It records the
   sentences heard and writes `work/<lang>/pronounce-approved.json` (never write it yourself).
3. "고칠 곳이 있다": change readings (cast) or retry lines (tts) and go through the section again.

Anything that changes after `shown` (the audition, the exemptions, the readings) needs `shown` and the question again.

## board · visual-check · ③

`setup.py doc board` (board with the credits and the brand's look — `check_assets.py <video> --look --output <o>` —,
visual-check, gate ③).

## render · ④a · copy · ④b

`setup.py doc render` (render, gate ④a), then `setup.py doc copy` (copy, gate ④b).

## The video's commit

The render (the `out:` folder) and the copy (the `copy:` folder) are ignored by git and never committed; the commit
holds only what `check_commit.py` stages. An internal video (`scope: internal`) is never committed: see "An internal
video's end" below.

0. A video from a web page (`--url`): read the page again first —
   `python3 .claude/studio/scripts/capture.py recheck <video>`, then the `state.py record-recheck <video> <n>` line it
   prints (run it even when capture.py exits 1: an unreadable page is recorded too, and holds the commit until a
   later recheck reads it — tell the person and try again later). When record-recheck says the page changed, run the
   `state.py record-source <video> --from-recheck <n>` line it prints: the changed page becomes the copy and
   `next` holds the video at the source diff — do `setup.py doc resume` (show `work/source-diff.txt`, the person
   approves or rejects); after an approval, come back here without another recheck. The commit needs a recheck that
   read the page at most 24 hours before `check_commit.py --stage` (the hook does not count again).
1. `python3 .claude/studio/scripts/check_commit.py --stage video <video>` — it checks everything again (the router,
   the source stage, check_assets, validate_copy, a person's approvals and credits), merges the video's approved
   readings into `.claude/studio/pronounce.json`, stages the allow-list and prints the summary line
   (`커밋 <tree12> | …`, with `발음 사전: 충돌 N개 건너뜀 (…)` when a reading was skipped). Exit 1: fix what it lists;
   exit 4: a person approves what was approved in the proxy mode.
2. Ask with AskUserQuestion: `[<video>]` and the summary line **verbatim**, the staged paths; options `커밋 <tree12>`
   and "아직". Then, alone as your next tool call, in the same turn, right after the answer — do not wait for the
   person; never in the same assistant message as the question — run
   `git commit -m "<message>"`.
3. `python3 .claude/studio/scripts/state.py done <video>`.

## An internal video's end

No `check_commit.py` (it refuses a local video). After ④b:

1. Ask with AskUserQuestion: `[<video>]` and that the video is finished on this machine (its files stay under
   `studio/local/`, backed up, not committed); options `완료 <video>` and "아직".
2. `완료 <video>`: `python3 .claude/studio/scripts/state.py done <video>` — it checks what a commit would (every gate
   approved by a person, every credit a person's, nothing held, nothing to redo), then records `done` and takes a last
   backup. Exit 4: a person is needed first — a gate or a credit approved in the proxy mode (a person approves it
   again) or a stopped video (the message names the stop; `setup.py doc resume`); exit 1: fix what it lists.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
> Exception: when the refusal itself says 'This is not a stop', do what it says — that is not
> reaching the same effect another way.
<!-- /studio:guard-refusal -->
