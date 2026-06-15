# Commands Inventory

Full `/sdd <command>` surface, routing rules, and plugin packaging metadata. Sources: `SKILL.md` (routing), `commands/*.md` (per-command), `plugins/sdd-plugin/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CLAUDE.md`.

---

## 1. Command Table

| Command | Purpose | Args | Modifies state? | User-confirmable? | Spawns sub-agents? | Source file | Tag |
|---|---|---|---|---|---|---|---|
| `/sdd init` | Repo setup: templates, labels, language save | `[lang]` (optional: en/ko/ja + aliases) | Yes — writes `.github/ISSUE_TEMPLATE/*`, `.github/.sdd-lang`, creates labels | No (one-shot) | No | `commands/init.md` | [PRESERVE] |
| `/sdd analyze` | Stage 1: requirements analysis (What/Why) | `<issue>` | Yes — posts `sdd:analyze:output`, sets `sdd:design` or `sdd:done` | Yes (Phase 2 gate unless `skip-review: analyze`) | Yes — `analyze_work` + 3 review atoms per round | `commands/analyze.md` | [PRESERVE] |
| `/sdd design` | Stage 2: design (How) | `<issue>` | Yes — posts `sdd:design:output` / `sdd:children:output`, child Issues, label transition | Yes (unless `skip-review: design`) | Yes — `design_work` + 3 review atoms | `commands/design.md` | [PRESERVE] |
| `/sdd implement` | Stage 3: TDD + PR Final | `<issue>` | Yes — branch, commits, PR, `sdd:implement:plan`, TDD step evidence, PR Final reviews, label transition | Yes (plan + PR Final gates unless `skip-review: implement` / `pr`) | Yes — `implement_plan`, 4 TDD step atoms, step reviewers, `implement_pr`, 3 PR Final reviewers | `commands/implement.md` | [PRESERVE] |
| `/sdd test` | Stage 4: E2E + QA | `<issue>` | Yes — posts `sdd:test:output`, optionally `sdd:review:parent` for parents, closes Issue → `sdd:done` | Yes (QA gate unless `skip-review: qa`) | Yes — `test_work` + 3 review atoms (+ `parent_integration_review` for parents) | `commands/test.md` | [PRESERVE] |
| `/sdd resume` | Auto-detect current stage and continue | `<issue>` | Indirectly — inline-executes the detected stage's command | Inherits detected stage's gates | Inherits detected stage's spawns | `commands/resume.md` | [PRESERVE] |
| `/sdd rollback` | Revert Issue to earlier stage, re-execute | `<issue> <target-stage>` (analyze/design/implement) | Yes — label change, `sdd:rollback` comment, inline target-stage execution | Yes (pre-rollback confirmation) | Inline target stage spawns its own atoms | `commands/rollback.md` | [PRESERVE] |
| `/sdd status` | Read-only progress inspection | `<issue>` | No | No | No | `commands/status.md` | [IMPROVE] |
| `/sdd review` | Re-run AI review on latest stage output | `<issue>` | Yes — posts/updates `sdd:review:<stage>:<role>` comments; for parents posts `sdd:review:parent`. No label change. | No (read-side only) | Yes — 2 review atoms (completeness + quality); adversarial NOT re-spawned | `commands/review.md` | [PRESERVE] |
| `/sdd config` | Manage `.github/.sdd-config` skip-review | `[--skip-review=<v1,v2,...>]` (empty value = reset) | Yes — writes / deletes `.github/.sdd-config` | No | No | `commands/config.md` | [PRESERVE] |
| `/sdd auto` | In-session sequential multi-Issue processing | `[issues]` (csv or empty = all open) | Yes — temp `.sdd-config` overlay, sandbox toggle, inline-runs each Issue's pipeline | Yes (session-start prompts: skip-review, sandbox, allowlist) | Yes — inherits stage spawns per Issue | `commands/auto.md` | [PRESERVE] |
| `/sdd batch` | Unattended shell processing via separate `claude -p` sessions | `[issues]` | Yes — generates `.github/.sdd-batch.sh`, per-Issue logs under `.github/.sdd-batch-logs/` | Yes (pre-generation prompts) | One `claude -p` subprocess per Issue (not Agent-tool subagents) | `commands/batch.md` | [PRESERVE] |
| `/sdd help` | Show help text | none | No | No | No | `commands/help.md` | [IMPROVE] |

### Notes on the table

- **Spawns sub-agents?** refers to Claude Code's `Agent` tool (single-level subagent spawn — Common Contracts §12). `/sdd batch` uses OS-level subprocess (`claude -p`), not Agent tool.
- **User-confirmable?** distinguishes commands with explicit user gates from one-shot operations. Stage commands' gates are skippable via `skip-review` config (`01-config.md` §2).
- **Modifies state?** flags side effects to disk, `gh` labels/comments, or branches/PRs.

---

## 2. Command Routing Rules (from `SKILL.md`)

### Entry point (`SKILL.md` lines 11–19)
1. `$0` is the command name. Read `<<SKILL_DIR>>/commands/$0.md` and execute its instructions.
2. Pass `$1` as Issue number for stage/utility commands, or language for `init`, or csv-issue-list for `auto`/`batch`.
3. Pass `$2` as target stage for `rollback`.

### Valid command set
```
init, analyze, design, implement, test, resume, status, review, rollback, config, batch, auto, help
```
(13 commands. `SKILL.md` line 18 is the authoritative list.)

### Fallback behavior
- `$0` empty → route to `help`.
- `$0` not in the list → report `unknown command`, then route to `help`.

[IMPROVE: the SKILL.md routing is one line of free-form prose. A structured command registry (with explicit arg arity per command) would let argument validation move out of each command file.]

[PRESERVE: the Issue Validation gate in Common Contracts §10 + load-time `<<SKILL_DIR>>` placeholder substitution are documented elsewhere and apply uniformly.]

### Argument-parsing inconsistencies [IMPROVE]
- `init` accepts language **aliases** (`korean`, `한국어`, `japanese`, `日本語`) — bespoke per-command parsing.
- `config` accepts a single `--skip-review=<csv>` flag with empty-value-means-reset semantics — bespoke flag parsing.
- `rollback` requires a positional second argument — no flag form.
- All others take a single positional Issue number (or csv for auto/batch).

No command uses a shared parser. Inconsistency surface area is small today but grows linearly with any new arg shape.

---

## 3. Plugin Metadata

### `plugins/sdd-plugin/.claude-plugin/plugin.json`
```json
{
  "name": "sdd-plugin",
  "description": "Spec-Driven Development (SDD) - AI collaborative development process with GitHub integration",
  "version": "0.36.0",
  "author": { "name": "dev-yakuza" },
  "homepage": "https://github.com/dev-yakuza/deku-claude-plugins",
  "repository": "https://github.com/dev-yakuza/deku-claude-plugins",
  "license": "MIT"
}
```

### `.claude-plugin/marketplace.json`
```json
{
  "name": "deku-claude-plugins",
  "owner": { "name": "dev-yakuza" },
  "plugins": [
    {
      "name": "sdd-plugin",
      "source": "./plugins/sdd-plugin",
      "description": "Spec-Driven Development (SDD) - AI collaborative development process",
      "version": "0.35.0"
    }
  ]
}
```

### Version sync requirement [PRESERVE]
Per `CLAUDE.md`: when a plugin's version changes, both files must be updated together — `plugin.json` (canonical version source) and the corresponding `plugins[].version` entry in `marketplace.json`.

[IMPROVE: as of this writing the two files disagree (plugin.json `0.36.0` vs marketplace.json `0.35.0`). Either a missed sync step or marketplace lag. Rewrite candidate: a pre-commit hook or release script that fails when versions drift. This is exactly the failure CLAUDE.md warns about.]

---

## 4. Surface-Level Tagging

### [PRESERVE] commands
- All stage commands (`analyze`, `design`, `implement`, `test`) — load-bearing pipeline.
- `resume`, `rollback`, `auto`, `batch` — workflow continuity and multi-Issue control.
- `init`, `config`, `review` — setup and re-review primitives.

These are the user-facing surface contracts. The names, argument shapes (modulo IMPROVE notes), and observable effects must persist across a rewrite.

### [IMPROVE] commands
- `/sdd status` — ambiguous required-vs-optional `$1`; output schema differs single vs parent without unified renderer.
- `/sdd help` — duplicated content vs per-command markdown; drift risk; would benefit from registry generation.

### [RETHINK] candidates (surface-level)
- **`/sdd auto` vs `/sdd batch`** — both exist for unattended multi-Issue processing; the distinction (Interactive billing pool vs Agent SDK Credit pool, in-session vs subprocess) is an artifact of Claude Code billing/runtime constraints rather than a user-facing capability difference. Consider unifying behind one command with an explicit `--mode=in-session|subprocess` flag.
- **`/sdd review` lacks adversarial re-spawn** — asymmetric vs per-stage orchestrator's 3-reviewer model. Either document this loudly or add an opt-in flag (`/sdd review --deep`).
- **`/sdd resume` and `/sdd rollback`'s inline target execution** — sound architectural decision (Common Contracts §12), but means a failure mid-stage leaves no clean re-entry point distinct from `/sdd resume` itself.

### Architectural invariants (apply to all commands)
- Single-level Agent spawn only — atoms cannot spawn atoms (Common Contracts §12).
- All persistent state on GitHub (labels, comments) — no in-process FSM (Common Contracts §2).
- Bash safety rules (Common Contracts §8) apply to every command file.
- Multi-line comment posting via temp-file pattern (Common Contracts §9).
- Issue Validation gate (Common Contracts §10) at the head of every Issue-taking command.

[PRESERVE: these invariants are platform constraints, not stylistic choices.]
