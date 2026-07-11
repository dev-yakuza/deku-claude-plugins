# SCAN: failures (evolve P1 — durable signal reader)

**Read-only failure-signal reader for `/gld evolve` Phase 1.** One of the four evolve scan atoms (`_signals.md` Section E). Derives **durable** failure signals — CI outcomes and recorded harness gaps — that are re-derivable any time, so evolve reads them live. Independently spawnable; returns a compact `>>> RESULT <<<` JSON that P2 (synthesize) consumes.

> **Bash**: simple calls only (`_bash_rules.md`) — no `|`, `&&`, `$(...)`, redirections. Codebase discovery via Grep/Glob/Read. **Read-only**: no Edit/Write, no installs, no git mutations.
> Model: **Haiku** (mostly mechanical reads); if CI-log ranking gets analytical, Sonnet is fine.

---

## Goal

Two durable failure sources (`_signals.md` Section A · plan §8 scan_failures row). **This scan does NOT run the test/lint suite** — running it is expensive and is the verify gate's job at dev-time (the resulting verify-gaps are captured to the ground-truth log and read by `scan_corrections`). Here we read *already-persisted* outcomes only.

| Source | What | Maps to |
|---|---|---|
| **CI** (`gh run list`) | workflows that fail repeatedly / are gated by branch or label | lint/type → gate (fail-to-rule) or ③ habit · area failure → ⑥ fact |
| **readiness-report** (`.claude/guild/readiness-report.md`) | harness gaps init/audit already found (missing tests, no CI, committed secret) | gate / ⑥ fact / security |

---

## Procedure (each step its own read-only Bash call)

1. **CI outcomes** — recent run conclusions and their patterns:
   ```bash
   gh run list --limit 40 --json conclusion,name,event,headBranch,createdAt
   ```
   Read the output and identify **repeated** failure patterns: which workflow(s) fail often, whether failures cluster on a branch/event (e.g. only on `pull_request`, or only when a label is absent). Report a pattern only when it recurs (≥2). *(kill-gate: "CI gated by label".)*
   - `gh` unavailable / non-GitHub remote → skip this source, set `ci: []`, note it in `degraded`. Never block.

2. **Recorded harness gaps** — read `.claude/guild/readiness-report.md` (Read tool) if present:
   - Extract the gap findings with their severity (BLOCKER / MAJOR / MINOR) and map each: verification gaps (no tests / no coverage) → ⑥ / gate · static-gate gaps (no linter / typecheck) → gate (fail-to-rule) · committed-secret → gate / security · label/CI gaps → routing.
   - Absent → `readiness_gaps: []` (the report is written by `/gld init` P3.5; a repo may predate it). Not a failure.

3. *(optional, bounded)* **Gate findings** — if `.claude/guild/gates/findings.json` exists (later milestone), read open violations and fold them in. Absent in M1/M2 → skip silently.

---

## Anchor & discipline (`_signals.md` Sections B, E)
- A CI failure pattern is a signal only when it **recurs** (≥2) and names a concrete workflow/branch. A one-off red run is noise.
- Readiness gaps are already severity-anchored (objective checks) — carry the severity through.
- **Local & read-only.** Never run the suite, never install a scanner, never create an issue — those are the caller's HITL actions.

---

## Output

Exactly one `>>> RESULT <<<` line + compact JSON.

```
>>> RESULT <<<
```
```json
{ "scan": "failures", "findings": {
  "ci": [ { "pattern": "e2e.yml fails on PRs missing the `run-e2e` label", "runs": 5, "mapping": "gate / routing" } ],
  "readiness_gaps": [ { "id": "committed-secret-file", "severity": "BLOCKER", "mapping": "gate / security" },
                      { "id": "no-e2e", "severity": "MAJOR", "mapping": "⑥ fact / gate" } ],
  "gate_findings": [],
  "degraded": false,
  "notes": "커밋된 시크릿(#890) = 최우선; e2e는 라벨 게이트." } }
```
Set `"degraded": true` and add a one-line reason to `notes` when a source could not be read (no `gh`, no report).

## Hard rules
- **Read-only.** No Edit/Write, no installs, no `gh label create`/issue creation, no git mutations, **no test/lint execution**.
- **Never print secret values** — reference the readiness-report finding id / file only.
- **Never block evolve.** Any unreadable source degrades this scan only; the durable backbone (scan_git, scan_corrections) stands alone.
- Return exactly one `>>> RESULT <<<` line + JSON.
