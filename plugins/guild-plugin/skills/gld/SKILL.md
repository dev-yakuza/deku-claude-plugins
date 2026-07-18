---
name: gld
description: "Guild builds a Claude Code operating environment (harness) into a repository and runs a spec-driven development flow (analyze -> design -> execute -> test -> qa) performed by a per-repo organization of specialized agent roles (spine: leader, tech-lead, developer, tester, qa; plus conditional specialists like designer, security, i18n, dba) that co-evolve with the codebase. Use to set up Guild in a repo (init), develop a GitHub Issue end-to-end (dev), run an individual stage, or check/continue progress."
argument-hint: "<command> [issue-number|args]"
user-invocable: true
---

# Guild (`/gld`)

Route to the appropriate command based on `$0`. Read `<<SKILL_DIR>>/commands/$0.md` and execute its instructions. Pass `$1`, `$2`… to the command file (meanings vary per command; typical `$1` = issue number, or language for `init`).

## Command Routing

- Valid commands: `init`, `plan`, `dev`, `analyze`, `design`, `implement`, `debug`, `refactor`, `test`, `qa`, `review`, `audit`, `batch`, `evolve`, `sprint`, `rollback`, `ask`, `onboard`, `monitoring`, `update`, `contribute`, `config`, `resume`, `status`, `help`
- If `$0` is empty → route to `help`.
- If `$0` is not in the list → report unknown command, then route to `help`.
- All §3 commands are implemented. (`sprint` is built but **readiness-gated** — it refuses to run autonomously until measured prerequisites pass; see `sprint.md`.)

---

## Common Definitions

### What Guild is
Guild installs a **harness** into the target repo and grows a per-repo agent organization — **the Guild** — of role agents that develop the codebase. The codebase (**결과물**) and the Guild (**개발자**) co-evolve. This version is a **walking skeleton** (M1: bootstrap + development flow with an **advisory** harness) plus a **proposal-only `evolve` growth loop** (M2): evolve reads traces and proposes how the Guild should grow, but the human applies the changes — no auto-apply yet. Enforcement gates and autonomy are later milestones.

### The Guild (per-repo agent organization)
- **Terminology (user-facing)**: in all output and GitHub comments, call the per-repo agent organization the **Guild** (길드) — the brand. Do NOT surface the internal shorthand "org" to the user (e.g. write "Guild 내부 검증", not "내부 org verify").
- Role agents live in `.claude/agents/` (native Claude Code project agents), specialized to this repo. `init` installs the **full roster (16)**: spine roles **leader, tech-lead, developer, tester, qa** (always in the flow) + conditional specialists **product-owner, designer, infra, dba, security, performance, i18n, analytics, tech-writer, release-manager, support-triage** (the leader convenes these per task by work-type/risk — participation model in `commands/atoms/_handoff.md` Section G).
- The **leader** is not a separate spawned subagent — the main session **embodies** the leader role (loaded from `.claude/agents/leader.md`): it assembles the team for a task, delegates to roles, arbitrates, and judges completion.
- Roles collaborate across stages (not a 1-role-per-stage pipeline): the tech-lead sets technical direction, drafts the skeleton, and later checks conformance; tester writes test cases from acceptance criteria before implementation; developer fills the skeleton.

### The spine (invariant)
```
analyze → design → execute → test → qa
                    └ execute variant by work type: implement (feature) | debug (bug) | refactor (refactor)
```
- `test` = automated correctness (tester, verify gate). `qa` = holistic quality (qa role, exploratory/E2E/user-flow, risk-based). `qa` marks `guild:done`.
- Conditional participants + gates (leader assembles per task/risk): designer (UI → design + UI/UX review gate), security (→ security review gate), infra, dba, i18n, analytics, performance, tech-writer, release-manager, support-triage. See `commands/atoms/_handoff.md`.
- Work type comes from the issue's `type:` label; `analyze` may reclassify. In M1, execute = **implement** only (debug/refactor are later).
- `/gld dev <issue>` runs the whole spine and auto-selects the execute variant. Individual stages are also invocable (`/gld analyze`, `design`, `implement`, `test`).

### Repo layout Guild manages
```
CLAUDE.md                      # advisory: repo map + verification commands + knowledge routing
.claude/settings.json          # permission allowlist (+ hooks in later milestones)
.claude/agents/                # role agents (the Guild)
.claude/guild/
  config.json                  # Guild settings (managed by /gld config)
  knowledge/                   # ⑥ codebase facts: index.md (always loaded) + facts/ (retrieved relevant-only). init seeds a baseline; evolve grows it
  memory/                      # ④ episodic working tier (gitignored → local per-clone, low-trust): ground-truth.jsonl (captured signals, read at runtime by pre-flight Item 8) + consolidated.jsonl (archive of entries evolve grew into ③/⑥) + gate-firings.jsonl (gate firing log feeding the evolve rule scorecard)
  evolution-log.md             # evolution ledger — used by evolve later
docs/standards/                # charter, architecture, conventions, quality-bar, verification (init drafts; status: draft|confirmed)
docs/adr/ , docs/specs/
```
- **commit** everything under `.claude/agents/`, `.claude/guild/` (except `memory/`), `docs/`, `CLAUDE.md`, `.claude/settings.json`. **gitignore** `.claude/guild/memory/`.

### Bash & GitHub conventions
- Run each shell command as its own isolated Bash call. Avoid compound commands (`&&`, `$(...)`), variable substitution, and inline multi-line `--body` for GitHub comments — render bodies to a temp file and use `--body-file`. Full rules: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/label/handoff contract: `<<SKILL_DIR>>/commands/atoms/_handoff.md`. Stage pre-flight: `<<SKILL_DIR>>/commands/atoms/_preflight.md`. ⑥ knowledge contract: `<<SKILL_DIR>>/commands/atoms/_knowledge.md`. Growth-loop signal contract: `<<SKILL_DIR>>/commands/atoms/_signals.md`. Loop-back stagnation guard: `<<SKILL_DIR>>/commands/atoms/_stagnation.md`.
- Obtain `{owner}/{repo}` via `gh repo view --json nameWithOwner -q .nameWithOwner` as its own call; inline the literal value. Never infer it from git user or the system prompt.

### Model tiering
Assign models by task cost: mechanical scans / rule checks → **Haiku**; stage execution and most orchestration → **Sonnet**; hard judgments (deep review) → **Opus**.

### State & idempotency
`init` is one-time (re-running reports "already initialized"). Development state lives in GitHub Issues/PRs; durable knowledge in `docs/` and `.claude/guild/`.
