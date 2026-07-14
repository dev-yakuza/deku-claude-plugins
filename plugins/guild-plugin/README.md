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
/gld init            # Analyze & onboard the repo → harness + founding Guild agents + standards + ⑥ baseline (one-time)
/gld dev 123         # Develop GitHub Issue #123 end-to-end (auto-selects feature/bug/refactor)
/gld status 123      # Inspect progress   ·   /gld resume 123 to continue
/gld audit           # Read-only health check of harness + team + codebase
/gld evolve --dry-run  # Propose how the Guild should grow (no changes)
```

## Commands

**Setup** — `init [lang]` (one-time onboarding) · `config` (dials, off-switches) · `update [--check]` (adopt central improvements, preserve local evolution)

**Develop** (spine: analyze → design → execute → test → qa) — `dev <issue>` (full flow, auto-selects the execute variant) · `analyze` · `design` · `implement` (feature) · `debug` (bug: reproduce→root-cause→fix) · `refactor` (behavior-preserving) · `test` · `qa` · `review <issue>` (guided pair-review + adversarial pre-scan) · `resume` · `status` · `batch [issues]` (unattended, rate-limit resilient)

**Diagnose & grow** — `audit` (read-only, routes to evolve/refactor) · `evolve [--dry-run|--apply]` (scan → adversarial panel → per-item approval → apply with backup/rollback/provenance/ledger) · `contribute` (upstream a flow improvement)

**On-demand & observe** — `rollback <target>` (non-destructive undo) · `ask <question>` (cited Q&A over standards + ⑥) · `monitoring [--html]` (state snapshot)

**Autonomous** — `sprint [issues]` (Inner+Outer, **readiness-gated** — earns autonomy by measurement)

## Safety (the invariants)

Guild is a self-modifying system, so safety is deterministic, not advisory:

- **INV1 — application always needs human approval.** Triggers auto-fire; changes never apply unattended (evolve apply, HR, and every gate are per-item human-gated).
- **INV2 — nothing weakens verification.** A change that deletes/weakens a test or gate is hard-blocked (commit gate + evolve validation).
- **INV3 — everything is reversible** (git · `/gld rollback` · evolve auto-rollback on validation failure).
- **INV4 — additive, never clobbers** local evolution (agents, knowledge, standards, overlay).
- **INV5 — nothing leaves the machine un-sanitized** (`contribute` sanitizes + dedups + human-reviews before any upstream send).
- **Off-switch** — `/gld config` pauses automation and gate blocking.

A **deterministic commit gate** (a `PreToolUse` hook) blocks committing secrets or weakening verification, and can't be bypassed by permission mode.

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
