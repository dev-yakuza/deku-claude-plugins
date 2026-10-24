# SOURCE

The source stage of a video that was begun (M1d): pin the writing, resolve its images, have the source analyst list
its claims, readings and images, check what a public video may use, and record it.

Rules: one command per Bash call, literal values (replace every `<…>` before the call), never a variable in command
position. Shared rules: `atoms/_contract.md`. The video id is the first argument of `/std source`.

1. `python3 .claude/studio/scripts/state.py record-source <video>` — pins a copy of the writing
   (`work/source/<file>`).
2. `python3 .claude/studio/scripts/resolve_assets.py <video>` — every image the writing refers to, resolved and
   judged (PNG/JPEG only; URLs, missing files, WebP/AVIF and the like are listed as not usable), with its floor
   (`third-party` when a caption names a copyright or a source, `unknown` outside the public folders). Exit 1: run
   step 1 first. Exit 2: a setting is wrong — tell the person.
3. Spawn the source analyst (`std-source-analyst`) with the copy and `work/assets.json`. It writes
   `work/source.md`: claims with exact excerpts, ruby pairs, and the class of every image.
4. `python3 .claude/studio/scripts/check_scope.py <video>` — the source must be public (and not internal), and every
   image gets its scope (the stricter of floor and class). Exit 1: tell the person what it says (another source, or
   the person changes `visibility` with `/std config`). Exit 4: the internal overlay is missing — ask the person to
   recreate it (`/std config`).
5. `python3 .claude/studio/scripts/state.py record-source <video>` again — now it records the images and
   `assets.json`. It says "note: …" when something is still missing; do what it says.
6. `python3 .claude/studio/scripts/state.py next <video>` — the next stage (brief).

Never edit `work/assets.json` or `work/source/` yourself (the guard refuses it); run the scripts again instead.

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
