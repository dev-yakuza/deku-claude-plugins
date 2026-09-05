# Guild Plugin

A self-evolving **agent organization** for Claude Code. Guild builds an operating environment (a *harness*) into your repository, develops GitHub Issues through a spec-driven flow performed by a per-repo team of specialized role agents, and **co-evolves your codebase and your agent team** from real usage.

> Successor to `sdd-plugin` and `skill-quality-plugin`. — *"a leveling-up agent guild."*

[한국어](./README.ko.md) · [日本語](./README.ja.md)

## Concept

- **Harness** — the operating environment Guild installs: `CLAUDE.md`, settings, a roster of role agents, a ⑥ knowledge base, standards drafts, and a deterministic commit gate.
- **Organization** — a per-repo team of **16 role agents** (spine: leader · tech-lead · developer · tester · qa; plus conditional specialists — designer, security, dba, i18n, …) that collaborate across the spine and are specialized to *your* project.
- **Two loops** — the **Inner loop** develops code (`analyze → design → execute → test → qa`); the **Outer loop** (`evolve`) reads real traces and grows the agents, knowledge, and gates.
- **Co-evolution** — both the codebase (the product) and the Guild (the developer) improve from usage. `evolve` distills traces into reviewed, human-approved improvements.

## Install

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@guild-plugin
```

## Quick Start

```bash
/gld init            # Analyze & onboard the repo → harness + founding Guild agents + standards + ⑥ baseline + readiness audit → guild:harness issues (one-time)
/gld dev 123         # Develop GitHub Issue #123 end-to-end (auto-selects feature/bug/refactor)
/gld status 123      # Inspect progress   ·   /gld resume 123 to continue
/gld audit           # Read-only health check of harness + team + codebase
/gld evolve --dry-run  # Propose how the Guild should grow (no changes)
```

## Commands

**Setup** — `init [lang]` (one-time onboarding, harness build + readiness audit) · `onboard [area]` (guided codebase tour for a human maintainer) · `config` (dials, off-switches) · `update [--check]` (adopt central improvements, preserve local evolution)

**Develop** (spine: analyze → design → execute → test → qa — `execute` always runs a read-only **external auditor** over the developer's diff before the PR opens; `BLOCKER` findings loop back and the fix is re-verified by `test`/`qa`, while `review` re-runs the same auditor outside the flow as the independent measure of whether the in-flow one is working) — `plan <doc|epic-issue> [--create]` (decompose an epic/design doc into a dependency-ordered Issue backlog) · `dev <issue>` (full flow, auto-selects the execute variant) · `analyze` · `design` · `implement` (feature) · `debug` (bug: reproduce→root-cause→fix) · `refactor` (behavior-preserving) · `test` · `qa` · `review <issue|PR>` (guided pair-review + adversarial pre-scan, accepts an Issue or a PR number directly) · `resume` · `status` · `batch [issues]` (unattended; waits out a rate limit whose reset is within 4h)

**Diagnose & grow** — `audit` (read-only, routes to evolve/refactor) · `evolve [--dry-run|--apply]` (scan → adversarial panel → per-item approval → apply with backup/rollback/provenance/ledger) · `contribute` (upstream a flow improvement)

**On-demand & observe** — `rollback <target>` (non-destructive undo) · `ask <question>` (cited Q&A over standards + ⑥) · `monitoring [--html]` (state snapshot)

**Iteration** — `sprint plan` (choose this sprint's issues, order them by dependency, open a tracking Issue) · `sprint run` (develop them unattended into dependency-ordered **PR stacks**, one git worktree per issue, rate-limit resilient: a reset within 4h is waited out, a longer one blocks that member for the re-run to pick up — you review and merge concurrently) · `sprint daily` (what to merge and in what order, what's waiting on you, what broke) · `sprint board` (mirror the sprint onto a GitHub Projects kanban — `Issues → Backlog → Ready → In progress → Blocked → In review → Done` — set up once, written by `plan` and `run` thereafter) · `sprint retro` (metrics → capacity calibration → evolve → close the sprint)

## Safety (the invariants)

Guild is a self-modifying system, so safety is deterministic, not advisory:

- **INV1 — application always needs human approval.** Triggers auto-fire; changes never apply unattended (evolve apply, HR, and every gate are per-item human-gated).
- **INV2 — nothing weakens verification.** A change that deletes/weakens a test or gate is hard-blocked (commit gate + evolve validation).
- **INV3 — everything is reversible** (git · `/gld rollback` · evolve auto-rollback on validation failure).
- **INV4 — additive, never clobbers** local evolution (agents, knowledge, standards, overlay).
- **INV5 — nothing leaves the machine un-sanitized** (`contribute` sanitizes + dedups + human-reviews before any upstream send).
- **INV6 — draft→confirm→enforce.** Auto-generated gate rules (e.g. structure/boundary rules) start `status: draft` (WARN-only) and only start blocking once a human confirms them (`status: confirmed`); the two universal secret/verification gates are non-hallucinated so `init` installs them pre-confirmed.
- **Off-switch** — `/gld config` pauses automation and gate blocking.

A **deterministic commit gate** blocks committing secrets or weakening verification. It runs
as a `.git/hooks/pre-commit` (authoritative — git runs it with the index final, so a compound
`create-and-commit` in one call is caught) plus a `PreToolUse` early-warning pass that gives
the agent a specific reason before it spends a turn.

**Its honest limits**, because a gate described as more than it is hides a real gap:
`git commit --no-verify` skips it, as it skips every git hook; `.git/hooks/` is untracked, so
a fresh clone needs `/gld update` to reinstall it; it never fires if the repo sets
`core.hooksPath`; and it does not inspect history already written. Editing the gate's own
off-switch or rule files prompts for human confirmation rather than being blocked outright —
turning the gate off is a legitimate action, it just should not be a side effect. The gate
raises the cost of a mistake; it is not a boundary against a determined bypass.

## Reference

### What Guild is
Guild installs a **harness** into the target repo and grows a per-repo agent organization — **the Guild** — of role agents that develop the codebase. The codebase (**결과물**) and the Guild (**개발자**) co-evolve. The harness combines an **advisory** layer (standards, knowledge, agent roster) with a **deterministic enforcement layer**: `init` installs a commit gate — authoritative as a `.git/hooks/pre-commit`, plus a `PreToolUse` early-warning pass — confirmed = block on secrets/verification-weakening from day one (further, stack-specific rules start `status: draft` = WARN-only until a human confirms them — INV6 draft→confirm→enforce). The six invariants are defined in one place: `<<SKILL_DIR>>/commands/atoms/_invariants.md`, which also states the gate's honest limits (`--no-verify` bypasses it; `.git/hooks/` does not survive a clone). The `evolve` growth loop reads traces and proposes how the Guild should grow; the human reviews and applies changes per item — never auto-applied (INV1). Full unattended autonomy (`sprint`) is built and **not readiness-gated** (see the note above): `run`'s preflight blocks only on what makes the flow meaningless — a repo with no way to *run* tests — and warns on everything else. The human still reviews and merges every PR (INV1).

### The Guild (per-repo agent organization)
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

## How it stores state

| What | Where |
|---|---|
| Development state (stages, outputs) | GitHub Issues/PRs + `guild:*` labels |
| Role agents (habits) | `.claude/agents/*.md` |
| Codebase facts (⑥, retrieved relevant-only) | `.claude/guild/knowledge/` |
| Raw episodic memory | `.claude/guild/memory/` (gitignored) |
| Evolution ledger + gates + config | `.claude/guild/` |
| Curated standards (charter, architecture, …) | `docs/standards/` |

## License

MIT
