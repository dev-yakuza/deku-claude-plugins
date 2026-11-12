# SCRIPT

The script stage: the script writer writes the script and its claims map; Studio's check runs s2v lint itself
and checks the claims, the narration and the images.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std script`.
Run Studio commands exactly as written: no `| head`, `; echo $?`, `2>&1 | …`, variables or `&&` chains (only
`cd <repo> &&`), and read the whole output. Do not repeat a call whose output is already in the conversation. Show
files to the person with `open <path>` only (never `code`, `vim` or another editor).

1. `python3 .claude/studio/scripts/state.py next <video> --enter script` — exit 3: go to the stage it names.
   On go it prints the `frontmatter` lines: the `cast:` block of the default narrator, `outputs:` with each output's
   `aspect` and `maxDuration`, and the `targetDuration` range. Exit 1 "no ready voice": run the narrator setup of
   `/std init` (or `/std config` narrator) first.
2. Spawn the script writer (`std-writer`) with `work/brief.md`, `work/brief.json`, `work/source.md`,
   `work/assets.json`, `.claude/studio/guides/script.md`, the brand and the `frontmatter` lines step 1 printed,
   pasted unchanged. It writes `script.<lang>.md` (frontmatter `title` · `lang` · those lines exactly — the cast block
   included, no acting, no `layout` — with `targetDuration` a number in the printed range; scene 1 the title scene
   with `::title[<title>]` as its only visual) and `work/<lang>/claims-map.json` (each claim's `sentences` list every
   script text that says it — narration, on-screen text, titles; the whole file in one Write; `unused_images` for any
   usable image it does not show). The spawn prompt gives the writer the exact command for s2v's script syntax, which
   it runs itself: `python3 "<<SKILL_DIR>>/scripts/setup.py" doc s2v-syntax` (exit 2 "no s2v path": `/std config`
   s2v.path first).
3. `python3 .claude/studio/scripts/check_claims.py <video> --narration` — runs `s2v lint` (its length warnings —
   over `maxDuration`, `targetDuration` ±15 % — and `no-visual`, a scene that shows only the background, fail here
   although s2v exits 0; `unread-word` is only information at this stage; every failure's s2v message is printed —
   give it to the writer as it is), checks `targetDuration` is in the range step 1 printed and the cast block is the
   default narrator's, checks the claims map against the brief and the source copy, that the narration has no kana or kanji
   (Japanese goes on screen), that every image is a usable `script_src` of `work/assets.json`, that every usable image
   is shown or has a one-line reason in `unused_images`, that scene 1 is the title scene (its only visual
   `::title[<frontmatter title>]`; skipped when the script has its own `::thumbnail{src=…}`) and that no presenter or
   dialogue layout is set without character art. Exit 1: give the
   writer the listed problems and run it again. A `warning:` line (on-screen text with digits or kanji no claim lists)
   is a hint for the writer, not a failure.
4. `python3 .claude/studio/scripts/state.py stage-done <video> script` — exit 1: run step 3 again (something
   changed); exit 3: the work is at an earlier stage, or the checked images changed (`/std source`).
5. `python3 .claude/studio/scripts/state.py next <video>` — the next stage (verify).

Never write `work/<lang>/checks/` yourself (the guard refuses it); run the check again instead.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
> Exception: when the refusal itself says 'This is not a stop', do what it says — that is not
> reaching the same effect another way.
<!-- /studio:guard-refusal -->
