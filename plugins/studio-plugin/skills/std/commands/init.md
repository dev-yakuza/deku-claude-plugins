# INIT

Install Studio's harness into this repository (M1c). The person's confirmation is the **first harness commit**: until
it is committed, no video starts (`begin` refuses an uncommitted harness).

Rules for every step: one command per Bash call, literal paths only (replace every `<…>` with the real value before the
call), never a variable in command position. Shared rules: `atoms/_contract.md`.
Run Studio commands exactly as written: no `| head`, `; echo $?`, `2>&1 | …`, variables or `&&` chains (only
`cd <repo> &&`), and read the whole output. Do not repeat a call whose output is already in the conversation. Show
files to the person with `open <path>` only (never `code`, `vim` or another editor).

## 1. Check (read only)

- `git rev-parse --show-toplevel` — a git repository. If `.claude/studio/config.json` exists (work tree, index or
  HEAD), stop: the harness is here — offer `/std config` or `/std update`.
- `python3 --version` — 3.9 or newer.
- Ask the person for this machine's script2video checkout (an absolute path) **in a plain message**, not with
  AskUserQuestion (there is nothing to pick from). Then run, with the path they gave, quoted as given:
  `node <s2v path>/packages/cli/dist/main.js --version --json` (0.13.0 or newer, `stale_build: false`) and
  `node <s2v path>/packages/cli/dist/main.js doctor`. A failure: stop and tell the person what to fix (`yarn build`,
  models). Warn when Claude Code is not 2.1.304 (`claude --version`).

## 2. Analyze (read only)

`python3 <<SKILL_DIR>>/scripts/setup.py init analyze` — drafts: `web_roots` from the static site's settings, folders
with writing (`content_folders`), the hook manager, LFS, whether `studio/` is free, and drafts with their evidence:
`public_domains` (`host`, `from`), `brand_colors` (`color`, `from`, `evidence`), `logos` (`path`, `from`, `size`,
`video`), `project_names` (`name`, `from`), `image_folders` (`glob`, `images`, `posts`, `writing`, `example`,
`via_web_root`), `narrator_candidates` (per language: `engine`, `language`, `native`, `suggested`) and `ask_husky`
(`partial: true`: the repository was too big to read whole — say so, with `partial_reason`). Also
`gh repo view --json visibility` for every remote (`git remote -v`). If `studio/` is taken, propose another
`studio_root` name.

## 3. Interview (AskUserQuestion — the person's choices, not evidence)

Ask only what M1 needs, in the repository's language (before init: the language the person writes in).
AskUserQuestion takes at most 4 questions per call and 2–4 options per question.

**Order** — never put a question in the same call as a question it depends on. Three calls, with one plain message
between the first two:
1. **Call 1**:
   - the videos' language (`ko` · `ja` · `en`) — always the first question;
   - the project name (`project_names`);
   - which writing is public (`multiSelect`);
   - `web_roots` (when step 2 found one).
2. **Purpose message**: after call 1 and before call 2, ask in a plain message for the purpose and audience (one
   line) — there is nothing to pick from. The narrator style options of call 2 are drawn from this answer.
3. **Call 2** (it needs the language, the public writing, the web roots and the purpose). Only after the language is
   answered: the default narrator, then:
   - the narrator (`narrator_candidates` of the chosen language);
   - the narrator's speaking style;
   - the image folders (`image_folders`; skipped when none is left to offer);
   - the accent colour (when `brand_colors` has more than one).
4. **Call 3**:
   - the logo (when at least one `logos` entry has `video: true`);
   - `public_domains` (when there is more than one);
   - the hooks (only when `ask_husky` is true);
   - the notices.

**Each question** has one subject. No detection notes and no remarks about another subject in its text (never "plain
hooks were found" in the narrator question).

**Options** are pickable values from step 2 or from earlier answers, each with its `from` / `evidence` as the
description, plus one meaningful alternative where it applies (`로고 없음`, `도메인 없음`, `없음`).
Never add an option that means "I'll type it" (`직접 입력`, `Other로 입력`, `기타`): the person can always type their
own answer. Only the first question says so: its text ends with one line in the repository's language, e.g. "목록에
없으면 직접 입력해 주세요" (never naming a UI label); the other questions do not repeat it. The free-input line is on the
language question only. Never invent a value: a colour, a logo, a host, a name or a folder comes from step 2 or from
the person.

**One value only → do not ask**: when there is a single value (nothing detected, so only the default), use it and
state it in the plan summary (step 4), with how to change it later. Exceptions: which writing is public, the image
folders, the narrator and the logo are always asked when step 2 has anything to offer for them.

What to ask:
- **project name**: the `project_names` candidates (at most 3), each with its `from` as the description; the first is
  the suggestion. With a single candidate (for example only the folder name), do not ask: use it and say so.
- **which writing is public** (`visibility_public`: globs of folders from `content_folders`, never the whole
  repository): which writing is public is always asked, even with one folder — at most 3 folders, the most Markdown
  files first, each as its glob (`<folder>**`), plus `공개 글 없음`.
- **`web_roots`** (site path → folder): the value from step 2, plus `없음`. None found: do not ask; none.
- **narrator**: the chosen language's `narrator_candidates` — the native speaker(s) first, the `suggested` one first
  and marked as the suggestion, then the others it lists (at most two). Each native option's description says it is a
  native speaker of the language. Each other option's description: "<its language> native speaker — may carry an
  accent and fail the ② pronunciation check (CER ≤ 0.15)". Always asked, even when the language has one native
  speaker.
- **narrator style**: its own question — two or three short speaking styles that fit the purpose the person gave.
- **image folders** (more `visibility_public` globs, `multiSelect`): the `image_folders` entries whose images the
  chosen web roots reach — when the person chose `없음` for `web_roots`, leave out every entry with
  `via_web_root: true` (site paths then do not resolve); also leave out a glob already inside a chosen public-writing
  glob. At most 3 — those whose `writing` includes a chosen public folder first, marked as the suggestion — each with
  `images`, `posts` and `example` as the description, plus `없음`. Nothing left: do not ask. Never suggest removing a
  glob the analysis lists: images outside `visibility_public` are `unknown` and need a licence at board.
- **accent colour**: at most three candidates from `brand_colors`; the first is marked as the suggestion. No
  `brand_colors`: do not ask; the colour is `#2563EB` (Studio's default) — say so in the summary. One: use it and say
  so.
- **logo**: only `logos` entries with `video: true` (PNG or JPEG: the video cannot show an SVG or WebP logo), at most
  three, plus `로고 없음` — asked even with a single candidate (that candidate and `로고 없음`). Before asking about
  the logo, open up to two logo candidates for the person (`open <path>` on macOS, `xdg-open <path>` on Linux;
  otherwise print their paths). None with `video: true`: do not ask; no logo
  (say so, and that a PNG or JPEG logo can be named later in `.claude/studio/brand.json`).
- **`public_domains`** (the site's host names): the hosts of `public_domains`, `multiSelect` when there is more than
  one, plus `도메인 없음`. None detected: do not ask; none.
- **the hooks**: only when `ask_husky` is true — whether to add Studio's block to `.husky/pre-commit`. When it is
  false, never mention hooks in a question (the plan summary shows what init installs).
- **the notices**: that they know them — videos are rendered with Remotion (its license) and the narration is a
  synthetic voice (platforms ask to mark it); options `확인했습니다` and `자세히 알려 주세요`.
- **brand name**: not asked — it is the project name.

## 4. Plan

Write the answers as a JSON file **outside the repository** (the system's temporary folder), with the keys
`language`, `studio_root`, `project_name`, `purpose`, `brand` {`name`, `accent_color`, `logo`}, `public_domains`,
`web_roots`, `visibility_public`, `narrator` {`id`, `engine`, `style`}, `husky`, `s2v_path`. Then:

`python3 <<SKILL_DIR>>/scripts/setup.py init plan --answers <answers file>`

`visibility_public` holds the chosen public-writing globs and the chosen image-folder globs. If the plan refuses the
logo with "commit the logo first, or choose 로고 없음 now" (the logo is not committed at HEAD, or the repository has no
commit yet) or because it is not a PNG or JPEG, tell the person why and ask the logo question again with
AskUserQuestion: the logo candidates plus `로고 없음`. Then write the answers again and rerun the plan.

Show the person the files it lists and the values (a short summary), and ask "이대로 만들까요?" — a go-ahead only;
the person's real check is the harness commit in step 6. The summary names every value that was not asked and how to
change it later: the brand (edit `.claude/studio/brand.json`; the next harness commit shows it), the narrator
(`/std config`, the default narrator), the domains (`/std config`), and the hooks init installs.

## 5. Apply

`python3 <<SKILL_DIR>>/scripts/setup.py init apply` — writes the harness (templates, agents, the scripts copy, the
default narrator, `.gitignore` and `info/exclude` blocks, this machine's `machine.json`, the empty internal overlay, the
marker) and installs the pre-commit hook. Exit 3: a harness or traces of one exist — stop and tell the person.

## 6. Harness commit (the person's check)

1. `python3 .claude/studio/scripts/check_commit.py --stage harness` — it prints the summary line and the **value
   block** (every protected setting's new value, the criteria of `formats/` as `criteria.<kind>.<key>: old → new`, one
   line per criteria file — `charter.md`, `formats/*`, `platforms/*` — with its sha, the narrator, this machine's s2v
   path and id).
2. Open every criteria file the block lists for the person (`open <path>`), and, if it says the block is long, the
   file it names too.
3. Ask with AskUserQuestion: the question text contains the summary line **and every value line exactly as printed**
   (each on its own line); options: the fixed label `커밋 <tree12>` and "고칠 곳이 있다".
4. Then, alone as your next tool call, in the same turn, right after the answer — do not wait for the person; never in
   the same assistant message as the question — run `git commit -m "studio: harness"`.

If the person wants changes: `/std config` (and stage again).

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
> Exception: when the refusal itself says 'This is not a stop', do what it says — that is not
> reaching the same effect another way.
<!-- /studio:guard-refusal -->
