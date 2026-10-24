# INIT

Install Studio's harness into this repository (M1c). The person's confirmation is the **first harness commit**: until
it is committed, no video starts (`begin` refuses an uncommitted harness).

Rules for every step: one command per Bash call, literal paths only (replace `<<SKILL_DIR>>` and every `<…>` with the
real value before the call), never a variable in command position. Shared rules: `atoms/_contract.md`.

## 1. Check (read only)

- `git rev-parse --show-toplevel` — a git repository. If `.claude/studio/config.json` exists (work tree, index or
  HEAD), stop: the harness is here — offer `/std config` or `/std update`.
- `python3 --version` — 3.9 or newer.
- Ask the person for this machine's script2video checkout (an absolute path), then run, with that literal path:
  `node <s2v path>/packages/cli/dist/main.js --version --json` (0.12.1 or newer, `stale_build: false`) and
  `node <s2v path>/packages/cli/dist/main.js doctor`. A failure: stop and tell the person what to fix (`yarn build`,
  models). Warn when Claude Code is not 2.1.304 (`claude --version`).

## 2. Analyze (read only)

`python3 <<SKILL_DIR>>/scripts/setup.py init analyze` — drafts: `web_roots` from the static site's settings, folders
with writing, the hook manager, LFS, whether `studio/` is free. Also `gh repo view --json visibility` for every remote
(`git remote -v`). If `studio/` is taken, propose another `studio_root` name.

## 3. Interview (AskUserQuestion — the person's choices, not evidence)

Ask only what M1 needs, a few questions per call, in the repository's language:
- the videos' language (`ko` · `ja` · `en`) · the purpose and audience (one line) · the project name;
- brand: name, accent color (`#RRGGBB`), logo (a file in the repository, or none);
- `public_domains` (the site's host names) · `web_roots` (site path → folder, from step 2);
- **which writing is public** (`visibility_public`: globs of folders, never the whole repository);
- **the default narrator**: show the built-in speakers of that language — ko `qwen:Sohee` (suggested), ja
  `qwen:Ono_Anna`, en `qwen:Ryan` or `qwen:Aiden` — and ask for the speaking style in one line;
- whether to add Studio's block to `.husky/pre-commit` (only when step 2 found husky);
- that they know the notices: videos are rendered with Remotion (its license) and the narration is a synthetic voice
  (platforms ask to mark it).

## 4. Plan

Write the answers as a JSON file **outside the repository** (the system's temporary folder), with the keys
`language`, `studio_root`, `project_name`, `purpose`, `brand` {`name`, `accent_color`, `logo`}, `public_domains`,
`web_roots`, `visibility_public`, `narrator` {`id`, `engine`, `style`}, `husky`, `s2v_path`. Then:

`python3 <<SKILL_DIR>>/scripts/setup.py init plan --answers <answers file>`

Show the person the files it lists and the values (a short summary), and ask "이대로 만들까요?" — a go-ahead only;
the person's real check is the harness commit in step 6.

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
4. Then, in a later message and alone — never in the same message as the question — run `git commit -m "studio: harness"`.

If the person wants changes: `/std config` (and stage again).

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
