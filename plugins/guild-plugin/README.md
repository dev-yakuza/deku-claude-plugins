# Guild Plugin

A self-evolving **agent organization** for Claude Code. Guild builds an operating environment (harness) into your repository, develops through a spec-driven flow performed by a per-repo team of specialized role agents, and **co-evolves your codebase and your agent team** from real usage.

> Successor to `sdd-plugin` and `skill-quality-plugin`. — *"a leveling-up agent guild."*

## Status

**0.1.0 (M1 — walking skeleton).** Bootstrap + development flow with an **advisory** harness. The growth loop (`evolve`), enforcement gates, quality tooling, and autonomy (`sprint`) arrive in later milestones (see roadmap).

## Install

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@guild-plugin
```

## Quick Start

```bash
/gld init            # Analyze & onboard the repo → harness + founding Guild agents + standards drafts (one-time)
/gld dev 123         # Develop GitHub Issue #123 end-to-end (analyze → design → execute → test)
```

## Concept

- **Harness** — the operating environment Guild installs (CLAUDE.md, settings, agents, verification map).
- **Organization** — a per-repo team of role agents (leader, architect, developer, tester) that collaborate across the spine and are specialized to your project.
- **Co-evolution** — both the codebase and the Guild grow from usage; `evolve` (M2, proposal-only) distills traces into proposed improvements to agents, knowledge, and gates.

## Commands

| Command | Description |
|---------|-------------|
| `/gld init [lang]` | One-time setup & onboarding |
| `/gld config` | Show / adjust settings |
| `/gld dev <issue>` | Run the full development flow |
| `/gld analyze` `design` `implement` `test` `<issue>` | Individual stages |
| `/gld resume` `status` `<issue>` | Continue / inspect progress |
| `/gld help` | Usage |

## Roadmap (milestones)

- **M1** (this): init + dev spine + config/status/resume/help. Advisory harness.
- **M2**: `evolve` growth loop + project knowledge base + evolution ledger.
- **M3**: enforcement gates (draft→confirm→enforce), verify/review/slopcheck, `audit`.
- **M4**: work-type routing (`debug`/`refactor`), `rollback`, `ask`, `monitoring`, `sprint` (readiness-gated).
- **M5 (v2)**: `contribute` (upstream), `update`, `sprint` activation.

## License

MIT
