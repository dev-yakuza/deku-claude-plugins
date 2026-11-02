# SCRIPT

The script stage (M1e): the script writer writes the script and its claims map; Studio's check runs s2v lint itself
and checks the claims, the narration and the images.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std script`.

1. `python3 .claude/studio/scripts/state.py next <video> --enter script` — exit 3: go to the stage it names.
2. Spawn the script writer (`std-writer`) with `work/brief.md`, `work/brief.json`, `work/source.md`,
   `work/assets.json`, `.claude/studio/guides/script.md` and the brand. It writes `script.<lang>.md` (frontmatter
   `title` · `lang` · `outputs.youtube` with `maxDuration` = the format's upper bound · `targetDuration` within the
   format's range; no cast, no acting, no `layout`; scene 1 the title scene with `::title[<title>]` as its only visual)
   and `work/<lang>/claims-map.json` (with `unused_images` for any usable image it does not show). The spawn prompt gives the writer the exact command for s2v's script syntax, which
   it runs itself: `python3 "<<SKILL_DIR>>/scripts/setup.py" doc s2v-syntax` (exit 2 "no s2v path": `/std config`
   s2v.path first).
3. `python3 .claude/studio/scripts/check_claims.py <video> --narration` — runs `s2v lint` (its length warnings —
   over `maxDuration`, `targetDuration` ±15 % — and `no-visual`, a scene that shows only the background, fail here
   although s2v exits 0; `unread-word` is only information at this stage), checks the claims map against the brief and the source copy, that the narration has no kana or kanji
   (Japanese goes on screen), that every image is a usable `script_src` of `work/assets.json`, that every usable image
   is shown or has a one-line reason in `unused_images`, that scene 1 is the title scene (its only visual
   `::title[<frontmatter title>]`; skipped when the script has its own `::thumbnail{src=…}`) and that no presenter or
   dialogue layout is set without character art. Exit 1: give the
   writer the listed problems and run it again.
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
