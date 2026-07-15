# KNOWLEDGE (⑥ — semantic memory, shared contract)

**Not a stage.** The authoritative contract for Guild's **semantic memory** — durable codebase *facts* (structure, coupling, pitfalls) that agents need at runtime but that are neither curated docs (`docs/standards/`, ②) nor agent habits (`.claude/agents/`, ③) nor raw episodes (`memory/`, ④). Plan §5 ⑥. Read by `_preflight.md` (retrieval), `init.md` (baseline seed), and `/gld evolve` (write proposals + densify).

> **Bash**: read-only exploration via Grep/Glob/Read (`_bash_rules.md`). The only writes are init's baseline seed and a human applying an evolve proposal — never an inline stage write.

---

## Section A — What lives here (and what does not)

| Memory | Store | This file? |
|---|---|---|
| semantic — **codebase facts** ("auth is coupled to session", "X co-changes with Y", "`disabledColor` token isn't mode-branched") | `.claude/guild/knowledge/` (⑥) | ✅ |
| procedural — **habits** ("type-check before commit") | `.claude/agents/<role>.md` (③) | ❌ |
| episodic — **raw events** ("this run failed, human fixed") | `.claude/guild/memory/` (④, gitignored) | ❌ |
| curated authority — charter, architecture, conventions | `docs/standards/` (②) | ❌ |

A ⑥ fact is a **discovered property of the code** an agent would otherwise rediscover each time. If it's a rule the team *decides*, it belongs in `docs/standards/` (②); if it's how a *role* should behave, it belongs in the agent def (③). ⑥ is committed (team-shared, semantic) — unlike ④.

## Section B — Layout & formats

```
.claude/guild/knowledge/
├── index.md          # ALWAYS loaded. Finite pointer map, keyed by path/area/symbol.
└── facts/
    ├── <area>.md     # Retrieved ONLY when a task touches <area>.
    └── …
```

**`index.md`** — the always-loaded map. Keep it **finite** (a compressed pointer list, `MEMORY.md`-style): one line per fact-slice, keyed by a **path / area / symbol** so lookup is deterministic. No fact bodies here — only keys + a one-line hook + the link.
```markdown
# Knowledge Index (⑥ codebase facts)
> Always-loaded map. For a task, retrieve ONLY the linked slice(s) whose key matches a path/area the task touches — never load all of facts/. Verify a fact against current code before relying on it (facts can go stale; evolve densifies).

## Facts by area
- `lib/db/**` · `db_helper.dart` → [db.md](facts/db.md) — DB lifecycle · migration · sync coupling
- `lib/screen/**` · theming · widgets → [ui.md](facts/ui.md) — theme tokens · a11y · disabled-state contrast
- co-change groups → [coupling.md](facts/coupling.md) — files that change together
```

**`facts/<area>.md`** — a retrieved slice. Group related facts under headings (symbol/pitfall/relation). Each fact is compact and **evidence-anchored**:
```markdown
# Facts: <area>
> Retrieved when a task touches <area>. Advisory — verify against current code before relying on it.

## <symbol or pitfall, e.g. theme disabledColor not mode-branched>
- **Fact**: `disabledColor` is a single token, not branched by `isLightMode` → hardcoding a disabled color can fail WCAG contrast in one mode.
- **Evidence**: #891 · #893 · #894 (recurring low-contrast fix).
- **Relation** (opt): co-change `app_theme.dart` ↔ widget color use.
- **Provenance**: init-scan | evolve #<n> (<yyyy-mm-dd>).
```

## Section C — Retrieval (runtime read — the crux, plan §5 "검색이 최난도")

Deterministic, no embeddings (v1 — invariant 1). At a stage's pre-flight (`_preflight.md` Item 6):
1. **Always Read `index.md`** — it is finite, so this is cheap and gives the map of what's known.
2. **Determine the task's touched paths/areas** — from the Issue/AC, the design structure, and (execute) the target directory.
3. **Match those against index keys** (path prefix, area tag, or symbol name — plain string/glob match, deterministic) and **Read only the matched `facts/<area>.md` slice(s)**.
4. **Never Read all of `facts/`** (invariant 1: no whole-load). No key match → load nothing beyond the index; that is normal for a well-scoped task.
5. **Verify before relying** — a fact is advisory; confirm it still holds against current code (facts can go stale between evolve runs).

## Section D — Scaling invariants (overflow prevention — plan §5, hard rules)

1. **No whole-load.** Fetch only the slices for the files/areas the task touches. Storage size ≠ context size. v1 key = **path/symbol index** (deterministic); semantic search is a later option.
2. **Finite always-loaded index.** `index.md` is a compressed pointer list. If it outgrows a screenful, **split by module** — move an area's pointers into a nested index loaded only when that area is touched (the nested-CLAUDE.md principle). The always-loaded set stays bounded.
3. **evolve densifies (growth = density, not monotonic).** On each evolve run, ⑥ proposals **merge duplicates, clean stale facts (contradicted by current code), and generalize** — so ⑥ gets *denser*, not just bigger. A fact whose evidence no longer reproduces is a removal candidate.
   - **⚠ Interleaved-replay guard (CLS — avoid catastrophic forgetting · 생물학 B, 항목 5).** Densifying must not let a new fact **silently overwrite a still-valid old one**. A fact is dropped/replaced **only when it is genuinely stale** — its evidence no longer reproduces against *current code* — **never merely because it differs from the incoming fact**. On a conflict between a new fact and an existing one, **re-verify both against current code** (interleaved replay) and keep whichever reproduces; if both do, they are not duplicates — keep both. The **ledger is the forgetting-prevention record**: a fact evolve previously promoted with corroboration is not quietly erased by a later run without evidence it went stale.

## Section E — Write discipline (who writes, when)

- **init** seeds a **baseline** from the P1 scans (hotspots, strong co-change groups, layer/coupling boundaries) — a solid starting map, not an exhaustive dump (plan §7). Direct write (bootstrap).
- **evolve** (M2 = **proposal-only**) proposes ⑥ facts and their `index.md` pointer; the **human applies** the edit (no auto-write in M2 — application machinery is v2+, plan §8). An `agent-friction`/`tool-error`/`co-change` signal that maps to a *fact* (not a habit or a decided rule) routes here.
- **No stage writes ⑥ inline.** Stages only *read* it (Section C). Facts are committed (semantic, team-shared).

## Hard rules
- **Read is retrieval, not whole-load** — index always, slices on match, nothing on no-match.
- **Facts are advisory** — verify against current code; stale facts are evolve's cleanup target, not a gate.
- **Right store** — a decided rule → `docs/standards/` (②); a role behavior → agent def (③); a raw event → `memory/` (④). ⑥ is discovered *code facts* only.
- **Keep the index finite** — split by module before it stops being a quick map.
