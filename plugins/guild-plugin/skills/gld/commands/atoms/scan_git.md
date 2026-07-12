# SCAN: git (evolve P1 — durable signal reader)

**Read-only git-history reader for `/gld evolve` Phase 1.** One of the four evolve scan atoms (`_signals.md` Section E). Derives **durable** friction signals from `git log` — signals that are re-derivable any time, so evolve reads them live (no capture infra). Independently spawnable; returns a compact `>>> RESULT <<<` JSON that P2 (synthesize) consumes.

> **Bash**: simple calls only (`_bash_rules.md`) — no `|`, `&&`, `$(...)`, redirections. For code discovery use Grep/Glob/Read, never Bash `find`. **Read-only**: no Edit/Write, no git mutations.
>
> ⚠ **Analytical, not mechanical** — this scan tallies frequencies across many commits by **reading** the raw log (pipes are forbidden). Spawn at **Sonnet**. Exact counts are not required; an approximate "which paths/pairs repeat most" is the goal. Keep windows modest so output stays readable.

---

## Goal

Four durable git-derived signal classes (`_signals.md` Section A · plan §8 scan_git row):

| Class | What | Maps to |
|---|---|---|
| **co-change** | files that repeatedly change *together* (hidden coupling X→Y) | ⑥ fact |
| **hotspot** | where `fix:` commits cluster + high churn — **`fix:`-label & churn correlation, NOT proven fragility** (a disciplined `fix:`-prefixer looks buggy; a central well-tested file looks fragile) | ⑥ fact / role 주의 |
| **convention** | commit-message convention coverage + violations | `conventions.md` |
| **revert / re-fix** | reverts + fix-on-fix churn = a change that was undone/redone | correction (strong) |

⚠ **Revert overlap**: reverts of Guild-authored commits are *also* read by `scan_corrections` (as the strongest correction class). Report them here from the log mechanically; **P2 dedups by commit SHA / evidence**. Do not suppress — surfacing in both scans is expected.

---

## Procedure (each step its own read-only Bash call)

Default window ≈ last 80–120 commits (keep it modest); the caller may pass a narrower window. All calls read the raw output; **rank by reading** (no pipes).

⚠ **Generated-asset flood (robustness — observed on real data, MUST handle)**: a single commit that regenerates assets (SVG/PNG icons, golden images, minified bundles, lockfiles) can dump **thousands** of file paths into `--name-only` output — enough to blow this sub-agent's context. Measured on word_app: an unscoped `-120` name-only log = **6675 lines** (mostly SVG assets from one regen commit); the same log **scoped to the source dir = 719 lines**. So:

**Step 0 — detect the main source dir(s) first** (Glob, not Bash): look for `lib/` (Dart/Flutter), `src/`, `app/`, `packages/*/src`. Then **scope every name-only log to that dir with a pathspec** (`-- lib`) — a pathspec is not a pipe, so it stays atomic-bash-safe. Scoping is the **default**, not a fallback. Only run unscoped if no clear source dir exists (then keep the window small and ignore asset paths by eye).

Generated-asset paths (`assets/`, `*.svg`, `*.png`, golden dirs, `*.g.dart`/`*.freezed.dart`, lockfiles) are churn-*noise*, not bug hotspots — the kill-gate explicitly distinguished this. Never let them dominate the ranking.

1. **Fix concentration** — where `fix:` commits cluster (conventional `fix:` = a past bug). Scoped to the source dir from Step 0 (substitute the literal, e.g. `lib`):
   ```bash
   git log --name-only --pretty=format: --grep=^fix -i -80 -- lib
   ```
   Identify the ~8 most-frequently-appearing source paths (approximate ranking by eye). Group nearby files into their area/layer.

2. **Churn + co-change** — most-frequently-changed files, and files that recur *together* (same source-dir pathspec):
   ```bash
   git log --name-only --pretty=format: -120 -- lib
   ```
   - **Churn**: top repeated paths (instability). Note that i18n/string files often top churn without being *bug* hotspots — distinguish.
   - **Co-change**: pairs/groups of paths that recur across the *same* commits (hidden coupling). Report the strongest recurring groups with an approximate co-occurrence count.

3. **Convention coverage** — commit-message style + violations:
   ```bash
   git log --pretty=%s -80
   ```
   Determine the prevailing convention (prefix scheme, language, em-dash, version-bump format) and roughly what fraction of recent subjects follow it. List a few concrete violators if the convention is otherwise near-universal (a small violation set = a `conventions.md` candidate; near-100% coverage = no signal).

4. **Reverts** — explicit reverts (a change that was undone = a correction):
   ```bash
   git log --grep=revert -i --oneline -100
   ```
   Report each revert's short SHA + subject. If a `fix:` commit lands on the *same paths* immediately after another `fix:` (fix-on-fix), note it as a weaker revert-like signal.

Cross-reference co-change/hotspot with the repo's layers to describe signals by **area** (e.g. "sync/ 계층", "i18n triad") not just single files.

---

## Frequency discipline (`_signals.md` Section E)
- **Repeated ≥ K only** — co-change/churn need ≥3 recurrences; drop 1-offs. A single explicit `revert` is admissible (it is an anchored correction — impact overrides frequency), but note it as count=1.
- **Evidence required** — every signal names a concrete path/pair/SHA. No evidence → not a signal.
- **Local & read-only.**

---

## Output

Exactly one `>>> RESULT <<<` line + compact JSON. Keep it a summary, not a dump.

```
>>> RESULT <<<
```
```json
{ "scan": "git", "findings": {
  "co_change": [ { "group": ["lib/l10n/app_en.arb", "lib/l10n/app_ja.arb", "lib/l10n/app_ko.arb"], "count": 22, "mapping": "⑥ fact" } ],
  "hotspots": [ { "path": "lib/controller/sync_data_controller.dart", "fix_count": 9, "mapping": "⑥ fact" } ],
  "high_churn": [ "lib/settings_controller.dart" ],
  "convention": { "style": "conventional (feat:/fix:), Japanese subject, em-dash", "coverage": "~100%", "violations": [] },
  "reverts": [ { "commit": "abc1234", "summary": "Revert \"feat: X\"", "mapping": "correction" } ],
  "notes": "i18n triad co-changes 22× — 한 언어만 고치면 회귀; sync 계층이 fix·churn 상위." } }
```

## Hard rules
- **Read-only.** No Edit/Write/NotebookEdit, no git mutations.
- **Bounded.** ~5 git-log reads; summarize, do not dump the log into RESULT.
- **Never block evolve.** Shallow/unavailable history → return empty lists (best-effort). A git failure degrades this scan only; the other scans stand alone.
- Return exactly one `>>> RESULT <<<` line + JSON.
