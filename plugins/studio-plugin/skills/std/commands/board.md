# BOARD

The board stage, visual-check and gate ③, per output of the brief (the steps below say `youtube` — run them for every
output with its name; a 9:16 or 1:1 output's layout is `shorts`, the `--look` line): the visual director decides how
the approved script looks, the person approves each picture's credits, Studio checks every picture, s2v takes stills,
and the person approves them.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std board`.
Run Studio commands exactly as written: no `| head`, `; echo $?`, `2>&1 | …`, variables or `&&` chains (only
`cd <repo> &&`), and read the whole output. Do not repeat a call whose output is already in the conversation. Show
files to the person with `open <path>` only (never `code`, `vim` or another editor).

## board

1. `python3 .claude/studio/scripts/state.py next <video> --enter board --output youtube` — exit 3: go to the stage it
   names.
2. Spawn the visual director (`std-visual-director`) with the script, `work/assets.json`, `work/source.md` and
   `.claude/studio/brand.json`. It changes only how the script looks — the frontmatter's `theme`, `logo`,
   `outputs.youtube.layout` and `transition`, and the attributes of the blocks already there — and writes
   `work/<lang>/board.md` (ending with `## Applied`) and `CREDITS.draft.yaml` (JSON). The spawn prompt gives it two
   exact commands (a third for board captures, below), which it runs itself:
   `python3 "<<SKILL_DIR>>/scripts/setup.py" doc s2v-syntax` (s2v's script syntax) and `python3 .claude/studio/scripts/check_assets.py <video> --look --output youtube` (the brand's lines to
   apply: the accent, the brand logo, the layout). `--look` exit 1: brand.json or its logo is not usable or not
   committed — tell the person (a brand change is a harness commit: `/std config`).
   - **Board captures** (optional): a picture of a web page may take the place of the picture of an `::image` block
     already there (its `src` only — never a new block). The spawn prompt gives the director a third exact command
     form, `python3 .claude/studio/scripts/capture.py shot <video> <name> --url <https url>` (optionally
     `--selector <css>` for one element of the page and `--width`/`--height` from 320 to 4096), which it runs once per
     picture with literal values: `<name>` is lowercase letters, digits and `-`, and the picture is
     `assets/capture-<name>.png` (the `src` to use). The page must be on one of `public_domains` (a public video may
     also use the third-party pages of `capture.hosts`); the address has no query or fragment and is the final one (a
     redirect to another host, even `www.`, is not usable). Exit 1: not usable (the reason is printed; an earlier
     picture of that name is gone, so the block keeps its old `src`); exit 3: refused by the host lists or the
     internal overlay — leave that picture as it was; exit 4: the internal overlay is missing (tell the person:
     `/std config`). The director lists each capture in `board.md` under
     `## Captures` (name, address, scene, why) and reports the `blocked: <host>` lines: ask the person whether to add
     each host to `capture.allow_hosts` (`/std config`), then the director captures again. A `warning:` line (the page
     did not settle) and the `floor:` line come back in the ③ question.
3. **Credits** — for every picture the script shows, the brand logo included:
   - `python3 .claude/studio/scripts/state.py credit-preview <video> <script_src>` prints eight `key=value` lines
     (ten for a board capture: its `source` and `captured_at` come from the capture, never from the draft),
     `label 출처 <video> <h12>` and the `question` block (`[<video>] 출처 — <script_src> · hash <h12>` and those
     lines, up to `end of question`) (exit 1: fix the draft as it says). A capture taken again is a new picture: its
     credit is asked again.
   - Ask with AskUserQuestion (at most 4 pictures per call, one question each): the question is **the block pasted
     unchanged** — never retype a line (the guard compares each character); options `출처 <video> <h12>` and
     "고칠 곳이 있다". Then, alone as your next tool call, in the same turn, right after the answer — do not wait for the
     person; never in the same assistant message as the question — run
     `python3 .claude/studio/scripts/state.py credit <video> <script_src> --expect <h12>`. Exit 6 with
     `fields-not-shown`: the question missed the line it names — run `credit-preview` again and ask again with the
     block.
   - "이전 승인 <v>" means another video approved the same entry: ask anyway (every video records its own).
4. `python3 .claude/studio/scripts/check_assets.py <video> --output youtube` — s2v check, content and voice unchanged
   since ②, every picture usable, unchanged and credited (a third-party or unknown image needs `public_ok: true` and
   a license), and the brand's look: brand.json committed, `theme.accent` the brand's, the brand logo, no presenter
   layout without character art. Exit 1: fix what it lists (a changed entry needs `credit` again); a look problem is
   fixed in the frontmatter by the visual director (the `--look` lines) and the check runs again — no stage change.
   - A `no-visual` failure (a scene that shows only the background), or any fix that needs a block added or removed
     (a dropped image too), is not fixed at board: blocks are in the content hash. Stop and go back to the script
     stage: run `/std script <video>` again (`python3 .claude/studio/scripts/state.py next <video> --enter script`);
     tell the writer to add (or remove) only that block and keep the rest of the script as it is — narration, cast,
     readings and presentation attributes; no rewrite. Then verify → ① → the cast check (`check_assets.py <video>
     --actors`, whose s2v lint fails on `no-visual` too) → tts with `check_tts.py` (unchanged sentences reuse their
     audio) → ②, and board again.
5. `python3 .claude/studio/scripts/state.py stage-done <video> board --output youtube`.

## visual-check

1. `python3 .claude/studio/scripts/state.py next <video> --enter visual-check --output youtube`.
2. `python3 .claude/studio/scripts/run_s2v.py snapshot <video> --output youtube` — it records `shown 3 --begin`, takes
   the stills and records `--end` (exit 1 "changed during the snapshot": run it again).
3. `python3 .claude/studio/scripts/state.py stage-done <video> visual-check --output youtube`.

## Gate ③

1. External audit (public videos — `scope: public` in `state.py next`; none for `scope: internal`): as in
   `setup.py doc verify` step 5, with the contact sheet, the stills and every board capture the script uses
   (`assets/capture-<name>.png`).
2. Open the contact sheet and the stills (`open <path>`); the last `shown 3 … --end` (printed by the snapshot) printed
   `hash12 <h12>` and the `question` block: `[<video>] ③ 정지 화면 — <stills folder> · hash <h12>`, then one
   `화면 캡처 <name>: <address> · png <sha12> · <floor>` line per board capture the script uses (with a warning when
   the page did not settle and the count of blocked hosts), up to `end of question`. `approve` refuses an answer
   whose question lacks one of those lines (`gate-lines-not-shown`: paste the block again).
3. Ask with AskUserQuestion: the question is **the block pasted unchanged**, then the auditor's findings (quote file
   paths rather than retyping long Japanese terms); options `승인 <video> <h12>` and "고칠 곳이 있다". Then, alone as your next tool call, in the same turn, right after the answer —
   do not wait for the person; never in the same assistant message as the question — run
   `python3 .claude/studio/scripts/state.py approve <video> 3 --expect <h12> --output youtube`.
4. "고칠 곳이 있다": back to board with the person's notes.

Replacing an image after ③ sends the work back to board (② stays: the audio did not change); so does taking a board
capture the script uses again, and the video commit refuses a capture whose bytes ③ did not approve.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
> Exception: when the refusal itself says 'This is not a stop', do what it says — that is not
> reaching the same effect another way.
<!-- /studio:guard-refusal -->
