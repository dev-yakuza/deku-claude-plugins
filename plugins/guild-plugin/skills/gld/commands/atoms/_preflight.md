# PRE-FLIGHT (shared procedure)

**Not a stage.** This file documents the pre-flight context discovery run at **Step 0** of every stage (analyze/design/implement/test). A stage reads the section for its tier when instructed. (Adapted from sdd-plugin's `_preflight.md`, trimmed for Guild M1 — no depth labels, no AI-review tiers.)

> **Bash Command Execution**: every snippet is its own simple Bash tool call — no `&&`, `|`, `;`, redirections, `$(...)`, or quoted `$VAR`. For codebase exploration use Grep/Glob/Read, never Bash `find` outside the repo root. See `_bash_rules.md`.

---

## Section A — Tiers

Each stage runs only the items matching its tier. Lower tiers are subsets of higher.

| Tier | Items | Applies to (default) |
|---|---|---|
| Light | 1 + 2 + 3 + 6 | analyze |
| Medium | 1 + 2 + 3 + 4 + 6 | design, test |
| Heavy | 1 + 2 + 3 + 4 + 5 + 6 | execute (implement) |

All items are **best-effort**. No individual failure blocks the stage — log and proceed.

---

## Section B — Items

### Item 1: Guild config + role definitions (always)
1. Read `.claude/guild/config.json` — note `language`, active `roles`, and any `gates`/automation flags. **`language` governs all human-readable output** this stage emits — its comments, discuss questions, narration, RESULT summaries, and artifact prose — **and every sub-agent prompt the leader spawns must carry that output-language instruction** (`_handoff.md` Section K; machine tokens stay ASCII).
2. Read the role agent file(s) for the roles participating in this stage (`.claude/agents/<role>.md`). Their project-specialization section (`## 프로젝트 특화`, or its localized equivalent) carries stack/convention/hotspot facts the stage needs.

**Failure**: config or agent files absent → this repo may not be initialized. Log "Guild not initialized (run /gld init)" and return that as a stage-level `FAIL` if the stage cannot proceed without them.

### Item 2: Project conventions (always)
1. Check for convention files: `ls CLAUDE.md AGENTS.md README.md`
2. Read each present file. Extract code style, naming, architecture rules, testing conventions.
3. Read `docs/standards/` if present (charter, architecture, conventions, quality-bar, verification) — these are the authoritative standards Guild's init drafted. Honor `status: confirmed` entries as hard constraints; treat `status: draft` as strong guidance.

**Budget**: ~5 Read calls max.

### Item 3: Commit message style (always)
1. `git log --oneline -20`
2. Observe prefix conventions (`feat:`, `fix:`, `refactor:`), version-bump format, capitalization.

**Failure**: `git log` fails (shallow clone, no history) → log "no commit history" and proceed.

### Item 4: Prior stage output for this Issue (design/execute/test)
1. Resolve owner/repo (per `_handoff.md` Section F).
2. Fetch prior stage comments for the Issue:
   ```bash
   gh api repos/<owner>/<repo>/issues/<N>/comments --jq '.[] | select(.body | contains("guild:analyze:output") or contains("guild:design:output")) | .body'
   ```
   (substitute literal owner/repo and `<N>`.)
3. Also read `docs/specs/<N>/` if present (skeleton, test cases passed as files between roles).

**Failure**: no prior output → the stage may be running out of order; return `NEEDS_CONTEXT` if the stage requires it.

### Item 5: Target directory survey (execute only)
1. Derive the target directory from the design output's structure section / `docs/specs/<N>/`.
2. `ls <target-dir>`; identify the 2 most recently modified files; Read both.
3. Extract import style, error handling, naming, test structure to match.

**Budget**: 2 Read calls max. **Failure**: target dir doesn't exist yet (greenfield) → proceed; the stage creates it.

### Item 6: ⑥ knowledge retrieval (always — relevant slices only)
Semantic memory — discovered codebase facts (`_knowledge.md`). **Retrieve, do not whole-load.**
1. Read `.claude/guild/knowledge/index.md` — the finite always-loaded map (absent/empty → this repo hasn't accumulated facts yet; that is normal, skip the rest).
2. Determine the paths/areas this stage touches (analyze: the Issue's area; design: the planned structure; execute: the target directory from Item 5).
3. Match those against the index keys (path prefix / area tag / symbol — plain string/glob) and **Read only the matched `facts/<area>.md` slice(s)**. No match → load nothing further (normal for a well-scoped task).
4. Treat each fact as **advisory** — verify against current code before relying on it (facts can go stale; `_knowledge.md` Section C).

**Budget**: index + ≤3 slice Reads. **Never** Read all of `facts/` (invariant 1 — no whole-load). **Failure**: any read fails → log and proceed on the durable context (Items 1–5).

---

## Section C — Self-review trace

After Step 0, record a short trace for the stage output's `<details>` block:

```markdown
<details>
<summary>Pre-flight context (Step 0)</summary>

- [x] config.json + role defs loaded
- [x] CLAUDE.md read; docs/standards/ (charter confirmed)
- [x] git log -20 (prefix: `feat:`/`fix:`)
- [ ] prior design output: N/A (analyze stage)
- [x] ⑥ knowledge: index.md loaded; retrieved facts/ui.md (touches lib/screen/)

</details>
```

Skip the block entirely if Step 0 was skipped (e.g. retry within a stage).

---

## Hard rules
- Step 0 is **read-only** (no Edit/Write except the stage's own temp comment bodies).
- Step 0 must complete or fail gracefully before the stage proceeds to its work.
