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
- Every command listed above is implemented. (`sprint` routes to four subcommands — `plan`·`run`·`daily`·`retro`. It is **no longer readiness-gated**: the old lock required `evolve`-accumulated data that a young repo cannot have, so it could never run. `run`'s preflight blocks only on what makes the flow meaningless — a repo with no way to *run* tests — and warns on the rest. See `commands/sprint.md`.)

---

## Common Definitions

### What Guild is
Guild installs a **harness** into the target repo and grows a per-repo agent organization — **the Guild** — of role agents that develop the codebase. The codebase (**결과물**) and the Guild (**개발자**) co-evolve. The harness combines an **advisory** layer (standards, knowledge, agent roster) with a **deterministic enforcement layer**: `init` installs a commit gate — authoritative as a `.git/hooks/pre-commit`, plus a `PreToolUse` early-warning pass — confirmed = block on secrets/verification-weakening from day one (further, stack-specific rules start `status: draft` = WARN-only until a human confirms them — INV6 draft→confirm→enforce). The six invariants are defined in one place: `<<SKILL_DIR>>/commands/atoms/_invariants.md`, which also states the gate's honest limits (`--no-verify` bypasses it; `.git/hooks/` does not survive a clone). The `evolve` growth loop reads traces and proposes how the Guild should grow; the human reviews and applies changes per item — never auto-applied (INV1). Full unattended autonomy (`sprint`) is built and **not readiness-gated** (see the note above): `run`'s preflight blocks only on what makes the flow meaningless — a repo with no way to *run* tests — and warns on everything else. The human still reviews and merges every PR (INV1).

### The Guild (per-repo agent organization)
- **Terminology (user-facing)**: in all output and GitHub comments, call the per-repo agent organization the **Guild** (길드) — the brand. Do NOT surface the internal shorthand "org" to the user (e.g. write "Guild 내부 검증", not "내부 org verify").
- Role agents live in `.claude/agents/` (native Claude Code project agents), specialized to this repo — **one file per role, and that directory is the roster**. `init` installs the full roster (16); a repo may grow or prune it later via `evolve` HR, so read the directory rather than assuming a fixed list. Spine roles **leader, tech-lead, developer, tester, qa** always run; every other role is a conditional specialist the leader convenes per task by work-type/risk. The roster and the participation model are defined once in `commands/atoms/_handoff.md` **Section G** — do not re-enumerate them elsewhere.
- The **leader** is not a separate spawned subagent — the main session **embodies** the leader role (loaded from `.claude/agents/leader.md`): it assembles the team for a task, delegates to roles, arbitrates, and judges completion.
- Roles collaborate across stages (not a 1-role-per-stage pipeline): the tech-lead sets technical direction, drafts the skeleton, and later checks conformance; tester writes test cases from acceptance criteria before implementation; developer fills the skeleton.

### The spine (invariant)
```
analyze → design → execute → test → qa
                    └ execute variant by work type: implement (feature) | debug (bug) | refactor (refactor)
```
- `test` = automated correctness (tester, verify gate). `qa` = holistic quality (qa role, exploratory/E2E/user-flow, risk-based). `qa` marks `guild:done`.
- The **execute** stage always runs a persona-less **external auditor** on the developer's diff before the PR opens (`commands/atoms/_execute_spine.md` Step 3.5a): read-only, severity-tagged findings, `BLOCKER` blocks and loops back so the fix is still verified by `test`/`qa`. `/gld review` runs the same auditor again *outside* `dev` — duplicated on purpose, as the independent measure of whether the in-spine one is working.
- Conditional participants + **gate reviews** the leader inserts before advancing when risk matches: designer (UI → design + a UI/UX review gate), security (→ a security review gate), infra (CI/CD·deploy·env·IaC → an execute review gate; **review-only — never authors its own diff**). Those three gate roles are the ones that can block a stage *by trigger* — plus the always-on external auditor above, whose `BLOCKER` blocks the same way; the remaining specialists participate without a gate. Full roster and triggers: `commands/atoms/_handoff.md` Section G.
- Work type comes from the issue's `type:` label; `analyze` may reclassify. The execute variant is chosen accordingly — `implement` (feature), `debug` (bug), or `refactor` (refactor) — see the spine diagram above.
- `/gld dev <issue>` runs the whole spine and auto-selects the execute variant. Individual stages are also invocable (`/gld analyze`, `design`, `implement`, `test`).

### Repo layout Guild manages
```
CLAUDE.md                      # advisory: repo map + verification commands + knowledge routing
.claude/settings.json          # permission allowlist + PreToolUse commit-gate hook
.claude/agents/                # role agents (the Guild)
.claude/guild/
  config.json                  # Guild settings (managed by /gld config)
  knowledge/                   # ⑥ codebase facts: index.md (always loaded) + facts/ (retrieved relevant-only). init seeds a baseline; evolve grows it
  memory/                      # ④ episodic working tier (gitignored → local per-clone, low-trust): ground-truth.jsonl (captured signals, read at runtime by pre-flight Item 8) + consolidated.jsonl (archive of entries evolve grew into ③/⑥) + gate-firings.jsonl (gate firing log feeding the evolve rule scorecard) + review-nudge-state.json (review's evolve-nudge cooldown, a single repo-global {count, runs} at the last nudge, so the 충분 state doesn't nudge every review — deliberately NOT keyed by PR: since the common workflow is one PR per issue, a per-PR key made nearly every review "first time" and nudged anyway; the global key accepts a rare, self-healing race between two PRs reviewed close together instead)
  gates/                       # 강제층 (enforcement layer): scripts/gate_precommit.py — the commit gate, run three ways (.git/hooks/pre-commit = authoritative · PreToolUse(Bash) = early warning · PreToolUse(Edit|Write) --guard-config = asks before its own off-switch/rules are edited) + rules/secrets.md, rules/verification.md (the human-readable declaration of what the gate enforces — the checks themselves are hardcoded, since they are universal and non-hallucinated) + rules/boundaries.md (the one data-driven rule file: `- forbid:` lines, frontmatter status: draft → WARN-only until confirmed — INV6) + dismissed.md (accepted-risk registry) + findings.json (open violations)
  overlay/                     # flow-policy override surface (empty by default; /gld contribute upstreams diffs here)
  evolution-log.md             # evolution ledger — used by evolve later
docs/standards/                # charter, architecture, conventions, quality-bar, verification (init drafts; status: draft|confirmed)
docs/adr/ , docs/specs/
```
- **commit** everything under `.claude/agents/`, `.claude/guild/` (except `memory/`), `docs/`, `CLAUDE.md`, `.claude/settings.json`. **gitignore** `.claude/guild/memory/`.

### Bash & GitHub conventions
- Run each shell command as its own isolated Bash call. Avoid compound commands (`&&`, `$(...)`), variable substitution, and inline multi-line `--body` for GitHub comments — render bodies to a temp file and use `--body-file`. Full rules: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. State/label/handoff contract: `<<SKILL_DIR>>/commands/atoms/_handoff.md`. Stage pre-flight: `<<SKILL_DIR>>/commands/atoms/_preflight.md`. ⑥ knowledge contract: `<<SKILL_DIR>>/commands/atoms/_knowledge.md`. Growth-loop signal contract: `<<SKILL_DIR>>/commands/atoms/_signals.md`. Loop-back stagnation guard: `<<SKILL_DIR>>/commands/atoms/_stagnation.md`. Dynamic model-tier escalation: `<<SKILL_DIR>>/commands/atoms/_model_tiering.md`. Shared execute-stage spine (the Steps 0–6 that `implement`/`debug`/`refactor` all run, with per-variant slots): `<<SKILL_DIR>>/commands/atoms/_execute_spine.md`. Discuss-gate readiness check: `<<SKILL_DIR>>/commands/atoms/_readiness.md`. Safety invariants INV1–INV6 (the single definition): `<<SKILL_DIR>>/commands/atoms/_invariants.md`.
- Obtain `{owner}/{repo}` via `gh repo view --json nameWithOwner -q .nameWithOwner` as its own call; inline the literal value. Never infer it from git user or the system prompt.

### Model tiering
Assign models by task cost: mechanical scans / rule checks → **Haiku**; stage execution and most orchestration → **Sonnet**; hard judgments (deep review) → **Opus**. On top of these static defaults, execute-stage loop-backs dynamically escalate a genuine retry one tier up, and evolve periodically reviews whether a role/stage's default should move — see `<<SKILL_DIR>>/commands/atoms/_model_tiering.md`.

### State & idempotency
`init` is one-time (re-running reports "already initialized"). Development state lives in GitHub Issues/PRs; durable knowledge in `docs/` and `.claude/guild/`.
