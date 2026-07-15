# Marketplace Roadmap (maintainer notes)

Internal, maintainer-facing notes for the `deku-claude-plugins` marketplace. Not user documentation.

## Plugin lineup

- **guild-plugin** — self-evolving agent organization; sets up a Claude Code harness and runs a spec-driven flow (analyze → design → execute → test → qa), co-evolving the codebase, the agent team, and the human overseer.
- **sdd-plugin** — Spec-Driven Development flow with GitHub integration. Guild's direct predecessor in intent (Guild generalizes the flow into a per-repo, self-evolving organization).
- **skill-quality-plugin** — a structured 38-item rubric for evaluating Claude Code skill quality.

## Successor sunset — sdd / skill-quality (evidence-based, no timeline)

Guild is positioned as the successor to both, but **retirement is deliberately decoupled from Guild's version/milestones.** The three coexist until Guild has *earned* the replacement in real use. This is a **human maintainer judgment**, not an automated trigger — and deliberately so: "the successor has surpassed its predecessor" is the most self-serving claim a tool could make, so it must never be self-certified by Guild (the same back-patting / human-authority guard that governs Guild's own growth). There is also no A/B signal to automate it — a repo uses one flow, not two in parallel.

**Trigger (all must hold, judged by the maintainer):**
- Guild demonstrably does the predecessor's job **at least as well in real, independent use** (not a lab comparison) — for skill-quality, that its rubric is genuinely covered by Guild's `audit` + quality-bar standard; for sdd, that Guild's spine has matured past sdd's flow in practice.
- Evidence is accumulated usage and outcomes, **not** a Guild self-assessment.

**Order** (independent, each gated on its own evidence):
1. **skill-quality first** — once Guild's `audit` has absorbed its rubric in practice.
2. **sdd later** — once Guild's flow has proven itself the mature path.

**Procedure** (reversible at every step — INV3 spirit):
1. Mark the plugin **deprecated** in its README + marketplace entry (a notice, not removal). Observe.
2. Observe real usage falling off / migrating to Guild.
3. **Remove** the plugin directory + marketplace entry only after the deprecation window is clean.

**Current status:** trigger **not met** — Guild was published recently and has not yet proven itself in independent real use. **All three coexist.** No deprecation notices posted. Revisit when accumulated usage gives the maintainer the evidence above.

## Deferred capabilities (built-trigger watched, not scheduled)

Recorded so they aren't lost; each is deferred on principle (adopt only when it beats the current baseline), with an in-code marker where relevant:

- **Population variation** (evolve — competing agent-def variants judged in parallel): token-expensive; adopt only at a scale where N-variant judging amortizes. Marker: `evolve.md` biological design note (D).
- **⑥ semantic / embedding search**: adopt only if the deterministic path/symbol key-match is shown to miss relevant facts. Marker: `_knowledge.md` retrieval note.
- **Live observability (Langfuse etc.)**: adopt only when per-call token/latency tracing is actually needed; the read-time snapshot is the baseline. Marker: `monitoring.md`.
- **`/gld migrate`**: a dedicated migration tool; `/gld init` already works on any repo, so this is convenience, not a gap.
