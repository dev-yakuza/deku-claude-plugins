---
name: gld
description: "Guild builds a Claude Code operating environment (harness) into a repository and runs a spec-driven development flow (analyze -> design -> execute -> test -> qa) performed by a per-repo organization of specialized agent roles (spine: leader, tech-lead, developer, tester, qa; plus conditional specialists like designer, security, i18n, dba) that co-evolve with the codebase. Use to set up Guild in a repo (init), develop a GitHub Issue end-to-end (dev), run an individual stage, or check/continue progress."
argument-hint: "<command> [issue-number|args]"
user-invocable: true
---

# Guild (`/gld`)

Route to the appropriate command based on `$0`. Read `<<SKILL_DIR>>/commands/$0.md` and execute its instructions. Pass `$1`, `$2`… to the command file (meanings vary per command; typical `$1` = issue number, or language for `init`).

## Command Routing

- **Channel guard — before routing any command except `channel` and `help`** (one repository uses one Guild channel at a time, `gldx` or `gld`): run this ONE Bash call in the repository (read only, inside the sandbox is fine): <!-- promote: other -->
  ```bash
  python3 -I <<SKILL_DIR>>/engine/engine.py channel show
  ```
  Exit 0 → route as below. **Exit 4 → do not route**: show the human its `refused:` line as it is (the active channel is the other one — use that channel's command, or switch with `/gld channel <channel>`; or both channels are set up and none is chosen) and stop. Any other exit → stop and show the output (the guard did not answer). The engine's own write commands refuse the same way at their entry.
- Valid commands: `init`, `plan`, `dev`, `analyze`, `design`, `implement`, `debug`, `refactor`, `test`, `qa`, `review`, `audit`, `evolve`, `sprint`, `rollback`, `ask`, `onboard`, `monitoring`, `update`, `contribute`, `config`, `resume`, `status`, `channel`, `help`
- `dev`, `resume` and `status` run the **engine** (stage 1; stage 2 adds the leader; stage 3 adds issue types and risk handling): their command files point to `commands/engine/<command>.md` (the engine CLI contract is `engine/gxengine/cli.py`). A stop is answered in the same conversation through the resume flow (`commands/engine/dev.md` section 3) — in stage 2 with the leader's recommendation shown first; a `needs_leader` stop (exit 11) is resumed without an answer.
- `sprint run` runs the **engine's supervisor** (stage 4): `commands/sprint/run.md` asks the human, `engine.py sprint …` (`commands/engine/sprint.md`) does the rest. Every member is the same engine run as `dev`, unattended.
- `batch` is **refused** in this edition: read `<<SKILL_DIR>>/commands/batch.md` and report its one line (use `/gld sprint run`).
- If `$0` is empty → route to `help`.
- If `$0` is not in the list → report unknown command, then route to `help`.
- Every command listed above is implemented. (`sprint` routes to six subcommands — `plan`·`run`·`daily`·`sync`·`retro`·`board`. It is **no longer readiness-gated**: the old lock required `evolve`-accumulated data that a young repo cannot have, so it could never run. `run` refuses a repository whose base is red and starts only on a human's word. See `commands/sprint.md`.)

---

## Common Definitions


### Terminology (user-facing)
- **Terminology (user-facing)**: in all output and GitHub comments, call the per-repo agent organization the **Guild** (길드) — the brand. Do NOT surface the internal shorthand "org" to the user (e.g. write "Guild 내부 검증", not "내부 org verify").

### The roster
- Role agents live in `.claude/agents/` (native Claude Code project agents), specialized to this repo — **one file per role, and that directory is the roster**. `init` installs the full roster (16); a repo may grow or prune it later via `evolve` HR, so read the directory rather than assuming a fixed list. Spine roles **leader, tech-lead, developer, tester, qa** always run; every other role is a conditional specialist the leader convenes per task by work-type/risk. The roster and the participation model are defined once in `commands/atoms/_handoff.md` **Section G** — do not re-enumerate them elsewhere.

### Repo conventions
- **commit** everything under `.claude/agents/`, `.claude/guild/` (except `memory/`), `docs/`, `CLAUDE.md`, `.claude/settings.json`. **gitignore** `.claude/guild/memory/`.

### Bash & GitHub conventions
- Run each shell command as its own isolated Bash call. Avoid compound commands (`&&`, `$(...)`), variable substitution, and inline multi-line `--body` for GitHub comments — render bodies to a temp file and use `--body-file`. Full rules: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/label/handoff contract: `<<SKILL_DIR>>/commands/atoms/_handoff.md`. Stage pre-flight: `<<SKILL_DIR>>/commands/atoms/_preflight.md`. ⑥ knowledge contract: `<<SKILL_DIR>>/commands/atoms/_knowledge.md`. Growth-loop signal contract: `<<SKILL_DIR>>/commands/atoms/_signals.md`. Loop-back stagnation guard: `<<SKILL_DIR>>/commands/atoms/_stagnation.md`. Dynamic model-tier escalation: `<<SKILL_DIR>>/commands/atoms/_model_tiering.md`. Shared execute-stage spine (the Steps 0–6 that `implement`/`debug`/`refactor` all run, with per-variant slots): `<<SKILL_DIR>>/commands/atoms/_execute_spine.md`. Discuss-gate readiness check: `<<SKILL_DIR>>/commands/atoms/_readiness.md`. Safety invariants INV1–INV6 (the single definition): `<<SKILL_DIR>>/commands/atoms/_invariants.md`.
- Obtain `{owner}/{repo}` via `gh repo view --json nameWithOwner -q .nameWithOwner` as its own call; inline the literal value. Never infer it from git user or the system prompt.

