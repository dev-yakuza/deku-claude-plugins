# EVOLVE (Outer Loop — HITL apply with safety machinery)

**Read the repo's traces and grow the Guild — propose, review, and (with human approval) apply.** `/gld evolve` scans durable + captured signals, synthesizes ranked themes, has them **adversarially reviewed** by an isolated panel, gates each on **per-item human approval**, then **applies the accepted changes with backup → validate → auto-rollback → provenance**, and records the run in the ledger. Plan §8 (P1–P7) · 부록 B "성장 엔진". The signal half was validated by the M2 kill-gate (2026-07-11, PASS); this adds the apply half on top of that verified foundation.

> **This is the self-modification loop (T1) — safety is the design.** The invariants are non-negotiable:
> - **INV1 — nothing applies without per-item human approval** (Phase 5). The trigger is automatic; the *application* is always human-gated.
> - **INV2 — no change may weaken verification** (a proposal that deletes/weakens a test or gate is inadmissible — hard-blocked in Phase 4 & 6).
> - **INV3 — every application is reversible** (Phase 6 backs up, applies as one commit, auto-rolls-back on validation failure; `/gld rollback` undoes an applied run).
> - **Adversarial panel before apply** (Phase 4): isolated fresh reviewers try to refute each change (correctness / degradation / redundancy) — a change that doesn't survive is dropped.
>
> **`--dry-run`** = the proposal-only mode (scan → rank → present, **no apply**) — the safe default for exploration. **`--apply`** (or answering the approval gate) runs the full HITL apply pipeline. Absent a flag, evolve proposes and then *asks* whether to enter the approval gate.
> **Off-switch**: `/gld config` can disable evolve automation; evolve apply also respects `gates.enabled` for the verification hard-block.

Args: `--dry-run` (propose only) | `--apply` (run the approval+apply pipeline). Default: propose, then ask.

> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`) — **except** the bundled Python tool (`scan_transcript.py`), run as ONE `python3` call (atomic-bash exception, plan §8 정정). Signal contract: `<<SKILL_DIR>>/commands/atoms/_signals.md`. Handoff/RESULT + owner/repo: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.
> **Output language**: present the ranked proposal list, hand-off text, and nudges in `config.language` (`_handoff.md` Section K). Target file paths, `RESULT` tokens, and evidence refs (SHA/PR#) stay ASCII.

---

## Phase 0 — Preflight & ledger

1. **Confirm Guild is initialized** (its own Bash call):
   ```bash
   ls .claude/guild/config.json
   ```
   Absent → report "Guild is not initialized in this repo. Run `/gld init` first." Stop.

2. **Resolve owner/repo** once (`_handoff.md` Section F); hold the literal value for the gh-based scans. If the remote is not GitHub, note it — the git-based scans still work; CI/PR scans degrade.

3. **Load the ledger** (skip-list / prior context) — Read `.claude/guild/evolution-log.md`:
   - Present with prior run entries → note any **previously-rejected** proposals so P3 does not re-propose them unchanged (plan §8 "declined-stays-declined" + offset). Read the **friction snapshot** history for the trend (does prior evolution help? — thrashing guard).
   - evolve **writes** the ledger in **Phase 7** (after apply). Read-only here.

4. **Clean-tree check (apply mode only)** — if entering the apply pipeline (`--apply` / approval), confirm the working tree is clean enough that Phase 6's per-item backup/rollback is safe (`git status --porcelain`). Uncommitted unrelated changes → warn and offer to proceed dry-run only (apply needs a clean baseline to roll back to). Dry-run mode skips this.

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

**docs/specs mining (⑥-fact source — plan 부록 D #894 "금광")**: also skim `docs/specs/<recent-issue>/` (skeleton · ux · test-cases · qa notes) from the last few dev runs — they are a rich source of ⑥ facts (theme-token pitfalls, verified contrast pairs, call-site geography) and cross-role corrections. ⚠ **Mining discipline**: specs are long narrative → do NOT whole-load; extract only the **final adopted values · leader arbitrations (§10) · qa정정** (high-trust), never the tentative §3 proposals (back-patting anchor). Feed extracted facts into P3 as ⑥-fact proposals.

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
   - **flow friction** (the spine itself was awkward) → **upstream-contribution candidate** (flag for `/gld contribute`; do NOT apply locally).
   - **convention drift** → `docs/standards/conventions.md`.
   - **role performance** (from the Phase 2.5 scorecard) → **HR proposal (C3, §16)**: **promote** a consistently ground-truth-successful habit (→ a stronger habit, or a gate rule — §8-C 기술 자동화) · **hire** a recurring unmet-need specialist (activate a roster role) · **retire** a never-convened role · **replace** a consistently-overturned one. HR needs a *trend* (Phase 2.5) — never propose off one run.

3. **Rank** each theme by **frequency × impact × surprise** (plan §8-A — the ranking lever the kill-gate validated):
   - **frequency** — recurrence count / distinct sessions (apply the ≥K discipline: drop 1-offs *unless* anchored+high-impact).
   - **impact** — a human correction (overturned work) > a **cross-role reversal** (one role's confident output overturned by another, anchored to a `BLOCKED`/defect — `scan_corrections` tags the source) > a structural coupling fact > a convention nit; BLOCKER/MAJOR readiness gaps outrank MINOR. Anchor impact to charter priorities when known.
   - **surprise** — boost items where a **confident choice was overturned** or a **guard was pierced** (§8-A). Sources, in order of strength:
     1. `surprise:true` flags in the ground-truth log — a human overturning a confident choice (discuss-override), a verify self-report ↔ runner gap, OR a **cross-role reversal** (a design-stage specialist `BLOCKED` reversing a decided approach, tech-lead/gate `BLOCKED`, or a QA/designer defect the test stage passed). All carry the flag; rank them human > cross-role > verify-gap per their anchor (`_signals.md` Section B).
     2. **Derived from durable signals when the log is empty** (the kill-gate case): a revert, an immediate fix-on-fix, a PR closed-unmerged, or a duplicate-issue discovery are all inherently surprising (confident work undone) — treat them as surprise-positive even with no ground-truth entry. *(This is why A1 "guard existed yet bug escaped" and A3 "confident work reversed" ranked top at the kill-gate without any transcript.)* ⚠ **Caveat**: *derived* surprise overlaps with the correction signal itself (not a fully independent third factor) — use it as a tie-breaker that lifts overturns, not as independent evidence. Only ground-truth `surprise:true` flags (source 1) are truly independent.

4. Assign each theme a **tier** for human triage: **A** (accept — clear, anchored, high rank), **B** (worth considering), **C** (noise / not actionable — surface anyway, as the discriminating power *is* the signal quality). Drop anything the ledger already rejected (P0) unless new evidence crossed the threshold.

---

## Phase 2.5 — Per-agent scorecard (360° · ground-truth-anchored) — C3 HR basis

Score each **active role's** recent performance — the basis for HR proposals (Phase 3) and sprint's readiness gate (§8 per-agent 성적표 · §16 C3). **Ground truth is highest-weight; agent opinion counts only when it anchors to ground truth (back-patting guard).**
- **Ground truth (per role — highest weight)**: objective outcomes tied to the role's own work — its stage's test/gate/CI pass↔fail, reverts of its commits, human corrections/acceptances (`scan_corrections.role`), and the **agent↔agent captures** (was this role *overturned* [−] or did it *do the overturning* on solid grounds [+]?).
- **Agent opinion (lower — only if corroborated)**: self / peer (sibling role) / leader / external-auditor views. An unanchored "동료가 좋다고 함" does **not** move the score (§8 back-patting; the external auditor guards this). No promotion on opinion alone.
- **Trend**: compare to prior-run scorecards in the ledger — improving / flat / declining per role. A single run is a **weak sample** — advisory until corroborated across runs.

Carry the scorecard into Phase 3 (HR) and record it in Phase 7. On a repo with no history yet, note "성적표 데이터 부족 (초기)" and skip HR proposals — HR needs a trend, not one run.

## Phase 3 — Propose (proposal list · distillation ladder)

Present a **ranked proposal list** to the human. For each Tier A/B theme, propose the **smallest sufficient change** via the distillation ladder (plan §8 P3 · §5 "성장=밀도, not 단조증가"):

> **patch** (tweak an existing line/section) **> umbrella-extend** (widen an existing rule/habit to cover the case) **> reference-add** (add a fact/pointer) **> new** (create a new rule/role — last resort).

Each proposal states, in ≤ ~500 chars (plan §6 context budget):
- **Target file** the human should edit — a role habit → `.claude/agents/<role>.md` (③); a decided rule → `docs/standards/…` (②); a **discovered code fact** → `.claude/guild/knowledge/facts/<area>.md` (⑥); an **HR change** → `config.json` `roles` + add/remove/rename a `.claude/agents/<role>.md` (hire/retire/replace — a canonical descriptive name; `leader` is never touched). Pick the store by kind (`_knowledge.md` Section A).
- **Ladder rung** + the concrete proposed edit (a habit line, a fact, a convention, a gate-rule candidate).
- **⑥-fact proposals** (`_knowledge.md`): specify **both** the `facts/<area>.md` fact (statement · evidence · relation · provenance `evolve #<n>`) **and** its `index.md` pointer (key = path/area) — a fact with no index entry is unreachable at retrieval. Prefer patching an existing slice over a new one (ladder).
- **Evidence** — the concrete artifact(s) (SHA / PR# / issue# / ground-truth entry / session count). No bulk paste.
- **Mapping + rank + tier** (why it ranks where it does; surprise noted if it drove the rank).

**Densify (⑥, invariant 3 — growth = density):** also scan the existing `knowledge/` for **duplicate facts to merge, stale facts to remove** (evidence no longer reproduces against current code), and **over-specific facts to generalize** — propose these as first-class items too. ⑥ should get *denser*, not just bigger.

**Presentation**:
- Print the Tier A list first (most-severe first), then B, then C (C shown compactly — "surfaced, not recommended", with the one-line reason each is noise; this transparency is the anchor discipline, kill-gate C-tier).
- **`--dry-run`** → **stop here** with the hand-off: *"제안 목록입니다 (dry-run). 파일 미수정 — 직접 편집하거나 `/gld evolve --apply`로 승인·적용 파이프라인을 도세요."* Optionally write the full list to a session-scratchpad digest (`<scratchpad>/gld-evolve-<repo>.md`) — **scratchpad only, never the repo**.
- **Otherwise (apply mode / default-then-ask)** → carry the Tier A/B proposals into **Phase 4**.

**Nudge (read-only)**: if the friction *trend* is worsening or a signal reads like a diagnostic gap rather than a single fix, **note that a `/gld audit` pass would help** (plan §9 evolve↔audit mutual nudge).

---

## Phase 4 — Adversarial panel review (P4 — refute before apply)

For each Tier A/B proposal, run an **isolated multi-lens panel** that tries to **refute** the change (plan §8 P4 · §16 C1 외부자). Spawn **fresh sub-agents** (`subagent_type: general-purpose`, no Guild persona → no confirmation bias; the plan's "격리 새 세션" via independent context). Scale the panel to risk:
- **Agent-def (③) / gate / standard (②) changes** = higher risk (they alter how every future task runs) → **3 lenses**, each a separate agent: **correctness** ("is the change factually right + does it actually address the evidence?"), **degradation** ("does it over-constrain, contradict an existing rule, or **weaken verification**? — INV2"), **redundancy** ("is this already covered by an existing rule/habit/fact?").
- **⑥-fact / convention (low-risk additive) changes** → **1 lens** (correctness + redundancy combined) is enough.

Each lens returns `{verdict: keep|drop|edit, reason, (edit: suggested change)}`. **Drop rule**: a proposal a **majority of its lenses reject** is dropped (recorded to the skip-list, P7). A **degradation-lens veto on an INV2 grounds is absolute** — any hint of verification-weakening drops the item regardless of the other lenses. Surviving proposals (some possibly edited by a lens) go to Phase 5.

## Phase 5 — Approval gate (P5 — per-item HITL · INV1)

Present the **panel-surviving** proposals to the human, **one at a time**, with: the change, its target file, evidence, rank/tier, and the panel verdicts (incl. any drop reasons for transparency). For each, the human chooses **accept / reject / edit**:
- **accept** → queued for Phase 6.
- **edit** → the human's revised version is queued.
- **reject** → recorded to the skip-list with the reason (P7; declined-stays-declined + offset).

**Nothing proceeds to apply without an explicit accept** (INV1). Unattended (`GLD_UNATTENDED`): evolve does **not** auto-accept harness changes — it stops here and marks the run "needs-human" (self-modification is never unattended; plan §8/§11).

## Phase 6 — Apply (P6 — backup → apply → validate → auto-rollback → provenance)

For the accepted set, apply as **one reversible unit** (INV3). Per item:
1. **Backup** — the clean git tree is the baseline (Phase 0 step 4 ensured it); note the pre-state.
2. **Apply** — Edit/Write the target file with the accepted (or edited) change.
3. **Validate** (deterministic, plan §8 P6):
   - **schema** — an agent def still has valid frontmatter (`name`/`description`/`model`); a ⑥ fact has its `index.md` pointer; a standard keeps its `status` frontmatter.
   - **description budget** — any changed `description`/fact ≤ ~500 chars (§6 context budget).
   - **quality gate** — the repo still parses / the harness still loads (no broken markers/refs).
   - **⚠ verification-weakening HARD-BLOCK (INV2)** — if the change (or its side effects) deletes/weakens a test, a gate rule, or a verify step → **reject the item + roll it back**. Non-negotiable, no override.
4. **Auto-rollback on any validation failure** — `git checkout -- <file>` (or revert the Write) for that item; report it as "applied-then-rolled-back: <reason>". Other accepted items still proceed.
5. **Provenance stamp** — annotate the applied artifact (frontmatter/comment or the fact's `provenance`) with `evolve #<n> (<date>) — evidence: <ref>`.

Commit the surviving applied set as **one commit** — `chore(guild): evolve #<n> — <n> changes applied` — so `/gld rollback <sha>` (or the ledger) can undo the whole run. Do **not** push/PR automatically (the human's repo workflow owns that).

## Phase 7 — Ledger update (P7 — record the run)

Append a run entry to `.claude/guild/evolution-log.md` (the format in plan §8):
- **Run header** — date · evolve #N · signal counts (by scan) · **friction snapshot** (permission/rework/gate-violation counts vs the prior run — the trend that measures "did evolution help?").
- **Per accepted item** — `[applied]` theme · target · class · evidence · panel verdicts · commit SHA · provenance.
- **Per rejected item** — `[rejected]` reason + evidence → **skip-list** (declined-stays-declined; re-propose only when new evidence crosses the threshold, with an offset).
- **Per-agent scorecard (360°)** — each active role's ground-truth-anchored score + trend this run (Phase 2.5). This is the **time-series** the next run's HR read (Phase 2.5 trend) and **sprint's readiness gate** consume. Keep it compact (role · score · trend · anchor evidence).
- **Archive** the ④ episodic entries this run distilled (they've been consolidated into ③/⑥/gates now — plan §5 "consolidation").

Report: applied N, rolled-back M (with reasons), rejected K, ledger updated, the commit SHA, and how to undo (`/gld rollback <sha>`).

---

## Hard rules (INV alignment)
- **INV1 — application is always per-item human-approved** (Phase 5). Dry-run never writes; apply never proceeds without an accept; unattended never auto-applies harness changes.
- **INV2 — never weakens verification.** A test/gate/verify-weakening change is inadmissible at Phase 4 (degradation-lens absolute veto) and hard-blocked + rolled back at Phase 6. No override.
- **INV3 — every applied run is reversible** — clean-tree baseline, one commit per run, auto-rollback on validation failure, `/gld rollback` undoes it.
- **Adversarial panel before apply** — a change that doesn't survive isolated refutation is dropped (no rubber-stamping self-modifications).
- **Anchor everything to ground truth** (`_signals.md` Section B): AI self-review ≠ signal; a reasonless rejection weights low.
- **Durable-first, degrade gracefully**: a missing ground-truth log / unreadable transcript never blocks evolve — it proceeds on git/CI/corrections.
- **Read-only scans, bounded output**: scans return compact JSON; synthesis keeps leader context thin (no transcript/diff dumps — §12).
