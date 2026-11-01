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

## License

MIT
