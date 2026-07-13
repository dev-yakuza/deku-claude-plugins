# EVOLVE (M2 — proposal-only)

**Read the repo's traces and propose how the Guild should grow — the Outer Loop.** `/gld evolve` scans durable + captured signals, synthesizes them into ranked themes, and presents a **proposal list**. It is the growth loop's first codified form (plan §8 · 부록 B "성장 엔진"), validated by the M2 kill-gate on real word_app data (2026-07-11, PASS).

> ⚠️ **This version is PROPOSAL-ONLY.** evolve does **scan → dedup → rank → present a list**. **The human edits the files.** There is **no** application machinery — no auto-apply, no backup/rollback, no document-TDD, no multi-perspective panel, no provenance stamping, no ledger writes. Those are **v2+** (plan §8 P3–P7, §14 "v1에서 컷"), built only after this proposal-only stage proves the signals are useful. evolve **never modifies the repo** — it is entirely read-only except for an optional session-scratchpad digest.
>
> **Why proposal-only**: the co-evolution premise ("can a human tell a good proposal from noise?") was validated manually at the kill-gate; this command codifies that manual pipeline. Building the apply machinery before the signals earn trust would be "미검증 위에 성당 짓기" (plan §14).

`$1` (optional) = history window in **days** for the transcript scan (default: 30). Git scans use a commit-count window regardless.

> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`) — **except** the bundled Python tool (`scan_transcript.py`), run as ONE `python3` call (atomic-bash exception, plan §8 정정). Signal contract: `<<SKILL_DIR>>/commands/atoms/_signals.md`. Handoff/RESULT + owner/repo: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.

---

## Phase 0 — Preflight & ledger

1. **Confirm Guild is initialized** (its own Bash call):
   ```bash
   ls .claude/guild/config.json
   ```
   Absent → report "Guild is not initialized in this repo. Run `/gld init` first." Stop.

2. **Resolve owner/repo** once (`_handoff.md` Section F); hold the literal value for the gh-based scans. If the remote is not GitHub, note it — the git-based scans still work; CI/PR scans degrade.

3. **Load the ledger** (skip-list / prior context) — Read `.claude/guild/evolution-log.md`:
   - Present with prior run entries → note any **previously-rejected** proposals so P3 does not re-propose them unchanged (plan §8 "declined-stays-declined"). In M2 the ledger is typically just the init header (no runs yet) — that's fine.
   - ⚠️ evolve **does not write** the ledger in M2 (ledger writes belong to the v2+ approval gate P5–P7). It is read-only here.

4. **Load the leader persona** (optional but preferred): Read `.claude/agents/leader.md` and adopt it — synthesis (P2) and proposal framing (P3) are leader judgment, anchored to `docs/standards/charter.md` priorities when ranking impact.

---

## Phase 1 — Signal scan (fan-out, read-only)

Run the four scans. The three Markdown scan atoms are **spawned as sub-agents in parallel** (each returns one `>>> RESULT <<<` JSON); the transcript parser is a **bundled Python call** you run directly. All are read-only.

**Spawn in parallel** (Agent tool, one message, `subagent_type: general-purpose`):

| Scan | Atom | Model | Returns |
|---|---|---|---|
| scan_git | `<<SKILL_DIR>>/commands/atoms/scan_git.md` | sonnet | co-change · hotspot · convention · revert |
| scan_failures | `<<SKILL_DIR>>/commands/atoms/scan_failures.md` | haiku | CI patterns · readiness-report gaps |
| scan_corrections | `<<SKILL_DIR>>/commands/atoms/scan_corrections.md` | sonnet | ground-truth log · PR rejections · reverts |

Prompt each sub-agent: *"Read `<atom-path>` and execute it for this repo (owner/repo = `<literal>`). Return exactly one `>>> RESULT <<<` line with the findings JSON."*

**Transcript scan** (best-effort, its own Bash call — replace `<abs-repo-path>` with `pwd`'s literal value):
```bash
python3 <<SKILL_DIR>>/commands/atoms/scan_transcript.py --repo-cwd <abs-repo-path>
```
(No time-window flag: frequency = distinct session count, and staleness is handled by the ledger skip-list, not a recency cutoff — plan 부록 D 3중 리뷰 P3.)
- Exit 0 → parse its `>>> RESULT <<<` JSON (`signals[]`).
- **Exit non-zero → degrade silently**: the transcript source is fragile (undocumented format, lossy cwd encoding — `_signals.md` Section F). Note "transcript signals unavailable — proceeding on durable backbone" and continue. **The durable backbone (git/CI/corrections) stands alone** (plan §8 정정, kill-gate confirmed: the top signals came from git+PR without transcripts).

**Collect** all available scan RESULTs. Any single scan may return empty/degraded — proceed with whatever succeeded. evolve must produce output even if only `scan_git` succeeded.

---

## Phase 2 — Synthesize (leader step — dedup · cluster · rank)

Converge the scan outputs into ranked themes. This is inline leader judgment (not spawned — it needs all scan JSON in context; the outputs are compact).

1. **Dedup** — the same underlying signal often appears in >1 scan. Merge by **evidence identity**:
   - a revert SHA in both `scan_git.reverts` and `scan_corrections.reverts` → one item.
   - a hotspot area that also shows up as a correction → one item, carrying both evidences.
   Keep the union of evidence; do not double-count frequency.

2. **Cluster into themes** and route each to its evolution target (plan §8 P2):
   - **agent friction** (rediscovery, repeated tool-error, rework) → ③ habit (a role's `.claude/agents/<role>.md`) or ⑥ fact (`.claude/guild/knowledge/`).
   - **gate friction** (repeated lint/type failure, committed secret, a correction that recurs) → **fail-to-rule** → a gate/standards rule.
   - **flow friction** (the spine itself was awkward) → **upstream-contribution candidate** (flag only — do NOT apply locally; not a runnable command yet).
   - **convention drift** → `docs/standards/conventions.md`.

3. **Rank** each theme by **frequency × impact × surprise** (plan §8-A — the ranking lever the kill-gate validated):
   - **frequency** — recurrence count / distinct sessions (apply the ≥K discipline: drop 1-offs *unless* anchored+high-impact).
   - **impact** — a human correction (overturned work) > a **cross-role reversal** (one role's confident output overturned by another, anchored to a `BLOCKED`/defect — `scan_corrections` tags the source) > a structural coupling fact > a convention nit; BLOCKER/MAJOR readiness gaps outrank MINOR. Anchor impact to charter priorities when known.
   - **surprise** — boost items where a **confident choice was overturned** or a **guard was pierced** (§8-A). Sources, in order of strength:
     1. `surprise:true` flags in the ground-truth log — a human overturning a confident choice (discuss-override), a verify self-report ↔ runner gap, OR a **cross-role reversal** (a design-stage specialist `BLOCKED` reversing a decided approach, tech-lead/gate `BLOCKED`, or a QA/designer defect the test stage passed). All carry the flag; rank them human > cross-role > verify-gap per their anchor (`_signals.md` Section B).
     2. **Derived from durable signals when the log is empty** (the kill-gate case): a revert, an immediate fix-on-fix, a PR closed-unmerged, or a duplicate-issue discovery are all inherently surprising (confident work undone) — treat them as surprise-positive even with no ground-truth entry. *(This is why A1 "guard existed yet bug escaped" and A3 "confident work reversed" ranked top at the kill-gate without any transcript.)* ⚠ **Caveat**: *derived* surprise overlaps with the correction signal itself (not a fully independent third factor) — use it as a tie-breaker that lifts overturns, not as independent evidence. Only ground-truth `surprise:true` flags (source 1) are truly independent.

4. Assign each theme a **tier** for human triage: **A** (accept — clear, anchored, high rank), **B** (worth considering), **C** (noise / not actionable — surface anyway, as the discriminating power *is* the signal quality). Drop anything the ledger already rejected (P0) unless new evidence crossed the threshold.

---

## Phase 3 — Propose (proposal-only list · distillation ladder)

Present a **ranked proposal list** to the human. For each Tier A/B theme, propose the **smallest sufficient change** via the distillation ladder (plan §8 P3 · §5 "성장=밀도, not 단조증가"):

> **patch** (tweak an existing line/section) **> umbrella-extend** (widen an existing rule/habit to cover the case) **> reference-add** (add a fact/pointer) **> new** (create a new rule/role — last resort).

Each proposal states, in ≤ ~500 chars (plan §6 context budget):
- **Target file** the human should edit (e.g. `.claude/agents/developer.md`, `docs/standards/conventions.md`, `.claude/guild/knowledge/facts/<area>.md`).
- **Ladder rung** + the concrete proposed edit (a habit line, a fact, a convention, a gate-rule candidate).
- **Evidence** — the concrete artifact(s) (SHA / PR# / issue# / ground-truth entry / session count). No bulk paste.
- **Mapping + rank + tier** (why it ranks where it does; surprise noted if it drove the rank).

**Presentation**:
- Print the Tier A list first (most-severe first), then B, then C (C shown compactly — "surfaced, not recommended", with the one-line reason each is noise; this transparency is the anchor discipline, kill-gate C-tier).
- End with the **explicit hand-off**: *"이것은 제안 목록입니다 (proposal-only). Guild는 파일을 수정하지 않았습니다 — 위 target 파일을 직접 편집하세요. 자동 적용·백업/롤백·문서-TDD·패널 검증은 v2+입니다."*
- **Optionally** offer to write the full ranked list to a session-scratchpad digest (`<scratchpad>/gld-evolve-<repo>.md`) for the human to work from — **scratchpad only, never the repo** (session-ephemeral; not an application).

**Nudge (read-only)**: if synthesis found the friction *trend* worsening or a signal that reads like a diagnostic gap rather than a single fix, **note that a future `/gld audit` pass would help** (plan §9 evolve↔audit mutual nudge) — **audit is a later milestone, not yet runnable**; this is a flag for the human, not an invocation.

---

## Hard rules (INV alignment)
- **Proposal-only — never modifies the repo.** No Edit/Write to tracked files, no git mutations, no issue/label creation. The only sanctioned write is the optional scratchpad digest. (INV1: application always needs human action — here the human *is* the applier.)
- **Never weakens verification** (INV2): a proposal that would delete/weaken a test or gate is **inadmissible** — flag it as noise (kill-gate Tier C: "위험명령 거부 allow화 = 안전약화, 기각").
- **Anchor everything to ground truth** (`_signals.md` Section B): AI self-review ≠ signal; a reasonless rejection weights low.
- **Durable-first, degrade gracefully**: a missing ground-truth log or an unreadable transcript never blocks evolve — it proceeds on git/CI/corrections. evolve produces a useful list even on a repo that has never run `/gld dev`.
- **Read-only scans, bounded output**: scans return compact JSON; synthesis keeps the leader context thin (no transcript/diff dumps — plan §12 컨텍스트 규율).
