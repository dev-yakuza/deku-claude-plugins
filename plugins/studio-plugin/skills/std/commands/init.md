# INIT

Install Studio's harness into this repository (M1c). The person's confirmation is the **first harness commit**: until
it is committed, no video starts (`begin` refuses an uncommitted harness).

Rules for every step: one command per Bash call, literal paths only (replace every `<…>` with the real value before the
call), never a variable in command position. Shared rules: `atoms/_contract.md`.

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
with writing, the hook manager, LFS, whether `studio/` is free, and drafts with their evidence: `public_domains`
(`host`, `from`), `brand_colors` (`color`, `from`, `evidence`), `logos` (`path`, `from`, `size`) and `ask_husky`
(`partial: true`: the repository was too big to read whole — say so). Also `gh repo view --json visibility` for every
remote (`git remote -v`). If `studio/` is taken, propose another `studio_root` name.

## 3. Interview (AskUserQuestion — the person's choices, not evidence)

Ask only what M1 needs, in the repository's language (before init: the language the person writes in).
AskUserQuestion takes at most 4 questions per call and 2–4 options per question.

**Order** — never put a question in the same call as a question it depends on:
1. First call: the videos' language (`ko` · `ja` · `en`) and questions that do not depend on it (at most 4 per call;
   the rest in the next call).
2. Only after the language is answered: the default narrator, with that language's built-in speakers only — ko
   `qwen:Sohee`, ja `qwen:Ono_Anna`, en `qwen:Ryan` (suggested) or `qwen:Aiden` — the suggested one first. When the
   language has one built-in speaker (ko, ja), do not ask for the speaker: it is fixed; ask only the speaking style
   (two or three short styles that fit the purpose as options).

**Each question** has one subject. No detection notes and no remarks about another subject in its text (never "plain
hooks were found" in the narrator question).

**Options** are pickable values from step 2 or from earlier answers, each with its `from` / `evidence` as the
description, plus one meaningful alternative where it applies (`로고 없음`, `도메인 없음`, `없음`).
Never add an option that means "I'll type it" (`직접 입력`, `Other로 입력`, `기타`): the person can always type their
own answer. Only the first question says so: its text ends with one line in the repository's language, e.g. "목록에
없으면 직접 입력해 주세요" (never naming a UI label); the other questions do not repeat it. Never invent a value: a colour, a
logo, a host or a folder comes from
step 2 or from the person.

**One value only → do not ask**: when there is a single value (nothing detected, so only the default; a language with
one built-in speaker), use it and state it in the plan summary (step 4), with how to change it later. Exception:
which writing is public is always asked.

What to ask:
- **project name**: the repository's name (and the site's name when step 2 shows one); purpose and audience (one line)
  in a plain message — there is nothing to pick from.
- **brand**: the name defaults to the project name. The accent colour and the logo are two questions, at most three
  candidates each, from `brand_colors` and `logos`. The first colour is marked as the suggestion. Before asking about
  the logo, open up to two logo candidates for the person (`open <path>` on macOS, `xdg-open <path>` on Linux;
  otherwise print their paths). No `brand_colors`: do not ask; the colour is `#2563EB` (Studio's default) — say so in
  the summary. No `logos`: do not ask; no logo.
- **`public_domains`** (the site's host names): the hosts of `public_domains`, `multiSelect` when there is more than
  one, plus `도메인 없음`. None detected: do not ask; none.
- **`web_roots`** (site path → folder): the value from step 2, plus `없음`. None found: do not ask; none.
- **which writing is public** (`visibility_public`: globs of folders from `content_folders`, never the whole
  repository): always asked, even with one folder — each folder's glob, plus `공개 글 없음`.
- **the hooks**: only when `ask_husky` is true — whether to add Studio's block to `.husky/pre-commit`. When it is
  false, never mention hooks in a question (the plan summary shows what init installs).
- **the notices**: that they know them — videos are rendered with Remotion (its license) and the narration is a
  synthetic voice (platforms ask to mark it); options `확인했습니다` and `자세히 알려 주세요`.

## 4. Plan

Write the answers as a JSON file **outside the repository** (the system's temporary folder), with the keys
`language`, `studio_root`, `project_name`, `purpose`, `brand` {`name`, `accent_color`, `logo`}, `public_domains`,
`web_roots`, `visibility_public`, `narrator` {`id`, `engine`, `style`}, `husky`, `s2v_path`. Then:

`python3 <<SKILL_DIR>>/scripts/setup.py init plan --answers <answers file>`

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
