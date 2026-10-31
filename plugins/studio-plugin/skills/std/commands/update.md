# UPDATE

Adopt this plugin's Studio into the repository (M1c): its scripts and, three ways, its templates. Asks first.

Rules: one command per Bash call, literal values (replace `<<SKILL_DIR>>` and every `<…>` before the call), never a
variable in command position. Shared rules: `atoms/_contract.md`.

1. `python3 <<SKILL_DIR>>/scripts/setup.py update plan` — the scripts' versions (repository → plugin), the scripts it
   replaces, adds and removes, every template's state (`same` · `update` · `keep-local` · `conflict` ·
   `protected-needs-choice` · `missing`), `s2v.min_version`, `ignore`, `refused` and `h12`. If `refused` is set, stop
   and tell the person why. `ignore` says whether the Studio blocks of `.gitignore` and `info/exclude` are rewritten
   for this version: lines a person added to the `.gitignore` block are kept (`kept`), lines older versions shipped
   are dropped (`removed`); `info/exclude` is written whole (this clone only). If `ignore.problems` is set (broken
   block markers), stop and tell the person: `update apply` refuses (3) until they fix the markers by hand and the
   plan is run again.
2. Every item that is not `same` carries `diff`: `unified` (for an agent, of its persona block) and, for a format,
   `criteria` (`criteria.<kind>.<key>: old → new`). Show the person each of them. For each `conflict` and
   `protected-needs-choice` ask which to keep: `new` (an agent: its persona block only — the repository's frontmatter
   stays), `new-file` (the whole new file) or `local`. Run the plan again with the choices:
   `python3 <<SKILL_DIR>>/scripts/setup.py update plan --take <path>=new,<path>=local` (comma-separated) — the choices
   are part of the `h12` the person approves.
3. Ask with AskUserQuestion: the question shows the versions, what changes, every `ignore.lines` line (e.g.
   `.gitignore Studio 블록: 0.0.22 → 0.0.23`) and `h12`; options: the fixed label
   `갱신 <h12>` and "그만두기". Then, in a later message and alone — never in the same message as the question — run
   `python3 <<SKILL_DIR>>/scripts/setup.py update apply --expect <h12>` (with the same `--take`).
4. Commit like in `/std init` step 6 — a rewritten `.gitignore` block goes into this harness commit (stage, open the criteria files the value block lists, summary line and value
   lines, `커밋 <tree12>`, then `git commit` alone in a later message).

<!-- studio:guard-refusal -->
> **When the guard refuses something (INV9)**: stop. Do not reach the same effect another way
> (another command, a script, editing the file directly, removing environment markers, retrying
> with different flags). Tell the user what was refused and why, and ask how to proceed.
<!-- /studio:guard-refusal -->
