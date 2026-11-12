# Studio Plugin

> **In development (0.0.x).** Studio is not in the marketplace yet and its commands answer
> "not implemented yet". Do not use it on a real repository.

A **per-repo video production organization** for Claude Code. Studio installs a production
harness into a repository; a team of role agents specialized to that repo turns writing that
already exists there (blog posts, docs, app pages) into narrated videos with
[script2video](https://github.com/dev-yakuza/script2video), and drafts the text that goes
with each video on the platforms you choose.

[한국어](./README.ko.md) · [日本語](./README.ja.md)

## Concepts

- **The source is the writing that already exists.** Every fact in a video (narration, on-screen
  text, title, thumbnail, chapters, platform copy) comes from the source and is checked against it.
- **Four human review gates** — ① script ② audition ③ stills ④ final (④a video · ④b copy).
  Agents never approve on a person's behalf.
- **Generate, never publish** — Studio makes the files; a person uploads them.
- **script2video does the rendering** — Studio plans, checks, asks and commits.

## Try it locally

```bash
claude --plugin-dir plugins/studio-plugin
```

Then `/std help`. Requires script2video 0.13.0 or later (set up later by `/std init`).

## Notes

- **The s2v path is this machine's.** It lives in `.claude/studio/local/machine.json` (not committed), once per
  clone or worktree; `config.json` keeps only the minimum s2v version.
- **An approval answer is used once per repository.** Worktrees of one repository share that record; separate
  clones (another `git clone`) do not. A video's answer still names that video and its hash, so it rarely fits
  another clone; answers without a video (settings, updates) are the remaining case. Records kept per worktree by
  0.0.9 and earlier are ignored.
- **Upgrading a 0.0.x sandbox by hand** (until `/std config` arrives): delete `"path"` under `"s2v"` in
  `.claude/studio/config.json` and write `{"schema": 1, "s2v": {"path": "<absolute path>"}}` to
  `.claude/studio/local/machine.json` (a real folder, not a link).
- **Upgrading to 0.0.23**: `/std update` refreshes Studio's ignore block (`.gitignore` and `info/exclude`) so the
  credits draft and the audio folder no longer show as untracked; commit the `.gitignore` change with the harness
  commit that follows the update.
- **Studio's documents are printed, not opened (0.0.24).** `/std` reads its command documents by running
  `python3 "<plugin>/skills/std/scripts/setup.py" doc <name>`, which only prints one of Studio's own documents (read
  only; nothing is added to your settings). Opening the plugin folder with Read would ask you for every file, because
  the plugin is outside your working directories. The skill pre-approves that command only for the turn that starts
  `/std`; after that, Studio's guard allows exactly that call — alone in its Bash call, the plugin's own `setup.py`,
  a known document name — in every session where the plugin is enabled (any repository, subagents too). Your deny
  and ask rules still apply. There is no allow when the run folder's repository holds the plugin itself or its own
  Python (a virtual environment inside it). Not covered (residual risk): conda environments, virtual environments
  outside the repository or in additional working directories, a plugin checkout in an additional working directory.
  `blockReadsOutsideWorkingDirectories` fences file tools, not processes, so it does not stop `doc`. An agent that
  still opens a plugin file with Read gets the normal prompt (no hook on Read).
- **`/std init` suggests values (0.0.24).** It offers the site's domains (CNAME files, the site settings), up to
  three brand colours (theme-color, brand/primary/accent properties, then the most used colour of the site's own
  styles — vendor builds and minified files are left out) and up to three logo files, each with where it was found.
  It reads tracked files only and never `.env*`. When nothing is found it uses Studio's default (`#2563EB`, no logo,
  no domain) and says so in the summary; you can type your own answer to any question.
- **0.0.25 (pilot 2).** The source analyst writes the placeholder id `C-00000000` for every claim and
  `check_claims.py <video> --source --fill` writes the real ids (`--source` alone lists them). `check_claims.py <video>
  --skeleton` writes the verify draft with every entry to judge; the fact-checker fills it with Edit, and a second run
  keeps what was filled. The script writer and the visual director read s2v's script syntax with
  `setup.py doc s2v-syntax` (this work tree's s2v, a regular file inside it of at most 25,000 characters). An approval
  command now runs as the next tool call of the same turn, right after the person's answer — never in the same
  assistant message as the question. A refusal that says "This is not a stop" is followed instead of stopping: read with
  Read, write with Write or Edit; role agents do all their file work that way. The guard now checks `sed` by the shape of
  its script and options: plain prints, deletes and substitutions pass (in place too with `-i ''` or `-i.bak`, judged as writes of their files);
  a script or option it cannot check is refused inside a Studio repository. `state.py shown <video> 2` names
  `audition.md` on a `read:` line.
- **Upgrading to 0.0.25**: run `/std update` and choose "new" for every changed role agent file — all `std-*` agents
  (the Read/Write rule and the guard rule's exception), and among them `std-writer` and `std-visual-director` (the s2v
  syntax command), `std-fact-checker` (the skeleton, the link limit, list items and dropped conditions) and
  `std-source-analyst` (the placeholder id).
- **0.0.26 (pilot 2, the look and init).** The visual director applies the brand: `check_assets.py <video> --look
  --output <o>` prints the frontmatter lines brand.json asks for — `theme.accent`, the brand logo (`logo.src`) and the
  layout (`fullscreen` unless every speaker has character art; s2v's default `presenter` shows no one without it) —
  and the board check fails until the script has them. Board may now change the frontmatter's `theme`, `logo`,
  `outputs.<o>.layout` and `transition` (never a block). The brand logo is a picture with its own credit (floor
  `public/brand.json logo (committed in the harness)`). brand.json and the logo must be committed: the board check
  refuses an uncommitted one and the harness commit warns about an uncommitted logo; the logo must be PNG or JPEG.
  At the script stage, scene 1 is a title scene (`::title[<frontmatter title>]` its only visual, so the thumbnail
  carries the title; skipped when the script has its own `::thumbnail{src=…}`), every usable image of the post is
  shown or has a one-line reason in the claims map's `unused_images` (printed as `unused:` lines at ①), and the
  writer never sets a layout. `/std init` now always asks the narrator (the language's native speaker first, up to
  two others marked as possibly accented — they may fail ②'s pronunciation check), offers the image folders the posts
  use for `visibility.public`, offers project names from the site's title, the web manifest, package.json and the
  origin remote's repository name (never its URL), and refuses a logo that is not committed (choose 로고 없음 or
  commit it first).
- **Upgrading to 0.0.26**: run `/std update` and choose "new" for `std-visual-director`, `std-writer`,
  `guides/board.md` and `guides/script.md` (the guides may hold your own edits; the update shows the difference).
  Make sure brand.json and its logo are committed and the logo is PNG or JPEG (or set it to `""`). Put the folder of
  your posts' images in `visibility.public` with `/std config` if it is missing. For any video already past board,
  run `/std board <video>` first, before render: otherwise the board check's look rules fail it at the video commit
  and it goes back to board, then ③, the ④a render and ④a again. Videos in progress need no new source stage.
- **0.0.27 (G1: the guard reads more).** The guard reads the options of the common runners it unwraps (env, nohup, nice,
  timeout, time, script, flock, xargs, npx, …) and judges their file arguments. In a Studio repository it refuses
  runners and options it cannot read, the command-valued options and variables it knows (such as `git -c core.editor`),
  git settings that run commands through every route it knows, and zsh forms it cannot parse, such as a file-name word
  with a glob group `(…)` (the Bash tool runs zsh with `BARE_GLOB_QUAL` off, so `studi(o)` matches `studio`). After a
  shell function of yours or one the command defines, and after a hook (`chpwd`, `TRAP*`), what the guard cannot follow
  is unknown: git, deletions and unquoted `$X` may then be refused. Every call is also checked by the 0.0.26 guard:
  what it refused stays refused, its false refusals too (such as `rm -rf **/__pycache__`). After a `source` or `.`
  (and after an `eval` whose text the guard cannot read), the rest of the call is judged by the 0.0.26 rules only;
  stronger checks there are planned for 0.0.28. In a Studio repository a `~[name]` path that a command deletes or
  writes is refused. Outside a Studio repository a command too
  long for the guard's limits is refused unless nothing in it can name a repository. Details:
  [docs/guard-limits.md](docs/guard-limits.md). The guard is part of the plugin: no `/std update` is needed.
- **What the guard still does not see (0.0.27).** The full list is in
  [docs/guard-limits.md](docs/guard-limits.md). In short:
  - Programs and settings that run commands the guard does not model, such as awk programs or `NODE_OPTIONS`.
  - Values it cannot read, such as a deletion through one (`rm -rf $X`, `f() { rm -rf $1; }; f studio`).
  - Forms used from outside a Studio repository, such as interpreter code that names it (`python3 -c`) or a folder
    named only in a default value (`cd ${U:-<repo>}`).
  - Other cases, such as `chmod 000 studio` or an archive written over a protected file.

  The pre-commit hook, the commit checks and the person's gates stay behind these.
- **0.0.28 (pilot 3).** `state.py next <video> --enter script` prints the frontmatter lines the writer copies: the
  default narrator's `cast:` block (part of the script from the start — s2v's content hash includes it, so the cast
  stage no longer edits it), each output's `aspect` and `maxDuration`, and the range for `targetDuration`
  (ceil(min ÷ 0.85) to floor(max ÷ 1.15): youtube 212–417, so a script s2v lint passes is inside the format's length).
  `check_claims --narration` checks the cast block and prints every s2v failure message; the claims map lists every
  script text that says a claim (on-screen text and titles too), and the verify message names the text and where it
  is. `check_claims --source` refuses an excerpt that is not in the copy, stops inside a tag or mid-sentence.
  `record-brief --from` also takes a path from the repository root (inside the video folder only). The ② question
  lists the sentences the audition plays and the `read:` line; `shown 3` and `shown 4a` print their question blocks
  (④a asks the person to check sound, subtitles and pictures together). `assets.json` carries each image's
  `floor_text` for CREDITS. `record-source --url <https://<public domain>/…>` records the writing's address and the
  copy's description must carry `원문: <url>`. The harness commit's value block shows brand.json's name, colour and
  logo. `begin --ask-before tts,render` (and `state.py ask-before`) records the steps the person asked to be asked
  before. Every command document's Rules line now asks for exact commands, no repeats and `open` only.
- **Fewer prompts (0.0.28).** In `default` permission mode the guard now allows Studio's own script calls (the
  repository copy, unchanged and whole, run alone with literal arguments) and each role's writes to its own output
  files without a prompt, when every condition holds; otherwise the normal prompt stays. `run_s2v.py`, `lock.py`,
  `check_commit.py` and `state.py ask-before` still prompt. Start Claude in the repository itself. Conditions and
  limits: [docs/guard-limits.md](docs/guard-limits.md).
- **Upgrading to 0.0.28**: run `/std update` (the scripts' version is 25) and choose "new" for `std-writer`,
  `std-source-analyst`, `std-visual-director`, `std-distributor`, `guides/script.md` and `formats/youtube.md` (its new
  `source_label`). A narrator style with `"` or `\` is refused by `/std config` narrator now; change it there. A video
  still at the script stage needs the cast block in its script (the script check says so); one approved at ① without
  it goes back to the script stage (`/std script <video>`, then verify and ① again); videos past cast keep theirs.

## License

MIT
