# EVOLVE (Outer Loop — HITL apply with safety machinery)

**Read the repo's traces and grow the Guild — propose, review, and (with human approval) apply.** `/gld evolve` scans durable + captured signals, synthesizes ranked themes, has them **adversarially reviewed** by an isolated panel, gates each on **per-item human approval**, then **applies the accepted changes with backup → validate → auto-rollback → provenance**, and records the run in the ledger. The signal half was validated by the M2 kill-gate (2026-07-11, PASS); this adds the apply half on top of that verified foundation.

> **This is the self-modification loop — safety is the design.** The invariants are non-negotiable:
> - **INV1 — nothing applies without per-item human approval** (Phase 5). `evolve` itself is **always manually invoked** by the human (`config.md`: "there is no automatic evolve trigger") — INV1 is about what happens *inside* a manually-started run: the scan/synthesis/panel phases proceed on their own once you run `/gld evolve`, but the *application* of any change always stops for a per-item human approval.
> - **INV2 — no change may weaken verification** (a proposal that deletes/weakens a test or gate is inadmissible — hard-blocked in Phase 4 & 6).
> - **INV3 — every application is reversible** (Phase 6 backs up, applies as one commit, auto-rolls-back on validation failure; `/gld rollback` undoes an applied run).
> - **Adversarial panel before apply** (Phase 4): isolated fresh reviewers try to refute each change (correctness / degradation / redundancy) — a change that doesn't survive is dropped.
>
> **`--dry-run`** = the proposal-only mode (scan → rank → present, **no apply**) — the safe default for exploration. **`--apply`** (or answering the approval gate) runs the full HITL apply pipeline. Absent a flag, evolve proposes and then *asks* whether to enter the approval gate.
> **Off-switch**: `evolve` has no automatic trigger to disable in the first place (it's always human-run) — `/gld config --evolve-nudge=off` instead silences the *review-stage nudge* that suggests running it (`config.md`, `review.md` Step 5). **`gates.enabled` does not reach evolve's own INV2 hard-block** (Phase 6 step 3): that dial governs the *commit gate* — whether `gate_precommit.py` blocks a `git commit` — and turning it off is an escape hatch for a repo the gate misjudges. It is not an authorisation to apply a change that weakens verification. An earlier revision of this line said evolve apply "respects `gates.enabled`" for that block, which directly contradicted Phase 6's own "non-negotiable, no override" — the invariant wins, and the two statements now agree.

Args: `--dry-run` (propose only) | `--apply` (run the approval+apply pipeline). Default: propose, then ask.

> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`) — **except** the bundled Python tool (`scan_transcript.py`), run as ONE `python3` call (atomic-bash exception). Signal contract: `<<SKILL_DIR>>/commands/atoms/_signals.md`. Handoff/RESULT + owner/repo: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.
> **Output language (all phases — this is a long, multi-phase command; do NOT drift to English after Phase 1)**: EVERY human-readable output — proposals (P3), **panel verdicts (P4), approval-gate questions (P5), apply/ledger report (P6/P7)**, and nudges — MUST be in `config.language` (`_handoff.md` Section K). **The Phase 4 panel sub-agents must be told to return their verdicts + reasons in `config.language`** (a spawned agent defaults to English otherwise, and the leader would relay it in English). Only machine tokens stay ASCII: file paths, `RESULT`/verdict enums (`keep`/`drop`/`edit`), SHA/PR#.
> **Plain language for the human reader (P3/P5/P7 — separate from the language rule above)**: this document's own vocabulary — `Phase N`, `P1–P7`, `INV1/2/3`, `Tier A/B/C`, `Axis 1/2`, ladder-rung terms (patch/umbrella-extend/reference-add/new), lens names (correctness/degradation/redundancy) — is **internal authoring shorthand for whoever edits this skill file. None of it may appear verbatim in what the human actually reads.** Every proposal, panel-verdict summary, and report line shown to the human must read like something a non-specialist colleague would say out loud, in one pass, with no glossary needed:
> - **Tier** → say the priority in plain words ("우선순위 높음: 바로 확인해 주세요" / "참고용: 급하지 않음"), never the bare letter.
> - **Ladder rung** → describe the edit itself in one plain clause ("기존 규칙 문구를 한 줄 조정" / "완전히 새로운 규칙을 신설"), never the rung name.
> - **Evidence** → weave the reference into a short plain sentence ("최근 PR #123, #145에서 같은 문제가 반복됐어요"), never a bare `evidence:` field or a raw SHA list with no story.
> - **Panel verdict** → give the plain-language reason as a short sanity-check sentence ("검토 결과 이 변경은 안전하고 실제 문제를 고칩니다"), never `lens: correctness → keep`.
> - Never print the words "Phase", "INV", "P3/P4/P5", "Axis", "Tier" themselves, or panel/lens jargon, to the human — those stay in this file only. When in doubt, read the line back and ask "would a teammate who has never seen this document understand this sentence unaided?" — if not, rewrite it.

---

## Phase 0 — Preflight & ledger

1. **Confirm Guild is initialized** (its own Bash call):
   ```bash
   ls .claude/guild/config.json
   ```
   Absent → report "Guild is not initialized in this repo. Run `/gld init` first." Stop.

2. **Resolve owner/repo** once (`_handoff.md` Section F); hold the literal value for the gh-based scans. If the remote is not GitHub, note it — the git-based scans still work; CI/PR scans degrade.

3. **Load the ledger** (skip-list / prior context) — Read `.claude/guild/evolution-log.md`:
   - **Compute `<n>` here — this is the authoritative definition of the `evolve #<n>` tag used everywhere below.** `<n>` = **the count of run entries already in the ledger, plus 1**. An absent/empty file = 0 prior entries, so the first ever run is `evolve #1`. Count them in *this same read* and hold the literal (e.g. `evolve #7`) for the whole run — every later use refers back to this one value and none of them recompute it: the provenance stamp (P3 ⑥-fact `provenance`, P6 step 6), the `contribute-candidates.md` suffix (P2 flow-friction), the ledger key + commit subject (P6 step 7), the run header (P7), and the tag `/gld rollback` greps by (`rollback.md` step 1). Three properties those consumers depend on:
     - **stable** — a run's number is fixed once its entry is written, and is never renumbered afterwards.
     - **monotonic within this repo** — always the next integer, never reused, so `evolve #7` names exactly one run.
     - **repo-local** — it identifies a run of *this* ledger and means nothing upstream, which is why `contribute.md` sanitizes it away before sending (it keeps it only for the local dedup search and line match).
     **Only a run that writes a ledger entry spends its number.** Phase 7's nothing-applied case *does* write one (the `[rejected]` skip-list, committed alone) → it spends `<n>`. A pure `--dry-run` stops at Phase 3 and writes no entry at all → it spends nothing, and the next run takes this same `<n>`. Otherwise skipped numbers would leave gaps in the sequence that Phase 0's prior-applied-targets read and `rollback.md`'s subject-tag grep would then have to interpret. ⚠ **Accepted consequence**: a dry-run's `contribute-candidates.md` line carries a number that a *later* run will be the one to actually record — that suffix is a best-effort backpointer to the proposing run, not a unique key (`contribute.md` step 4 matches the whole raw line for exactly this reason).
   - Present with prior run entries → note any **previously-rejected** proposals so P3 does not re-propose them unchanged ("declined-stays-declined" + offset). Read the **friction snapshot** history for the trend (does prior evolution help? — thrashing guard).
   - **Load prior-applied targets (regression-tracking input, feeds Phase 2 & Phase 4)** — from the last ~3 runs' `[applied]` entries, extract each item's **target file/role/rule + evolve #N + date** into a short in-context list (targets only, not the diffs — stay bounded). Phase 2 cross-references this run's fresh signals against it to catch a self-modification that later caused friction; Phase 4 uses any hit as calibration input for the panel.
   - evolve **writes** the ledger at **Phase 6 step 7** — *before* the commit, so the entry ships inside it (Phase 7 holds the entry's schema). Read-only here.

4. **Clean-tree check — early warning only, on the `--apply` path** — when `--apply` was passed up front, confirm now that the working tree is clean enough that Phase 6's per-item backup/rollback would be safe (`git status --porcelain`). Uncommitted unrelated changes → warn and offer to proceed dry-run only (apply needs a clean baseline to roll back to). Dry-run mode skips this. ⚠ **This check is *not* the gate.** The documented default is "propose, then ask" — that path never passes through here at all, and even on `--apply` the human spends the whole of Phase 5 answering approvals while the tree can change under them. The **binding** check is the one at the top of Phase 6, which runs on *every* path that reaches apply; this one exists only so a `--apply` run fails fast instead of after the human has approved a dozen items.

5. **Load the leader persona** (optional but preferred): Read `.claude/agents/leader.md` and adopt it — synthesis (P2) and proposal framing (P3) are leader judgment, anchored to `docs/standards/charter.md` priorities when ranking impact.

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
(No time-window flag: frequency = distinct session count, and staleness is handled by the ledger skip-list, not a recency cutoff.)
- Exit 0 → parse its `>>> RESULT <<<` JSON (`signals[]`).
- **Exit non-zero → degrade silently**: the transcript source is fragile (undocumented format, lossy cwd encoding — `_signals.md` Section F). Note "transcript signals unavailable — proceeding on durable backbone" and continue. **The durable backbone (git/CI/corrections) stands alone** (kill-gate confirmed: the top signals came from git+PR without transcripts).

**Collect** all available scan RESULTs. Any single scan may return empty/degraded — proceed with whatever succeeded. evolve must produce output even if only `scan_git` succeeded.

**docs/specs mining (⑥-fact source — "금광")**: also skim `docs/specs/<recent-issue>/` (skeleton · ux · test-cases · qa notes) from the last few dev runs — they are a rich source of ⑥ facts (theme-token pitfalls, verified contrast pairs, call-site geography) and cross-role corrections. ⚠ **Mining discipline**: specs are long narrative → do NOT whole-load; extract only the **final adopted values · leader arbitrations · qa정정** (high-trust), never the tentative proposals (back-patting anchor). Feed extracted facts into P3 as ⑥-fact proposals.

---

## Phase 1.5 — Data-sufficiency gate (⚠ evolve is the only consumer that blocks — it mutates)

Compute data-sufficiency per `<<SKILL_DIR>>/commands/atoms/_data_sufficiency.md` — this is the **authoritative** measure (Section B: **Axis 1 counted after the Phase 1 scans**, so durable git/CI signals count, not just the captured log; **Axis 2** from the ledger's prior-run count, Phase 0). Emit the **banner** (Section D) at the top of this run's output, then gate:

- **Axis 1 `none` (0 signals)** → **HARD BLOCK.** Present the banner + *"성장시킬 ground-truth가 없습니다 — 먼저 `/gld dev`(또는 `batch`)로 실제 작업 흔적을 쌓으세요."* and **stop** (no Phase 2+). Shallow-data growth injects wrong habits/rules; refusing is the safe act.
- **Axis 1 `shallow` (1–4)** → **DRY-RUN ONLY.** If `--apply`/approval was requested, **refuse it** → downgrade to dry-run with the reason; stamp every Phase 3 proposal **`미검증 후보 — 적용 보류`**. Proceed to propose (the human sees what is accumulating) but nothing applies.
- **Axis 1 `sufficient` (≥5)** → proceed normally (apply still per-item HITL — INV1).
- **Axis 2 `no-trend` (0 prior runs — this is the first run)** → skip the **trend-dependent** outputs (HR proposals, 360 scorecard *verdicts*, 감독자 회고). **Low-risk applies still proceed** if Axis 1 `sufficient` (⑥ facts, small habit refinements — anchored + reversible) so the ledger accrues its first run and HR/scorecard unlock starting the *next* (2nd) run, which then has 1 prior run → `trend`. *(Gating all apply on `trend` would make the 2nd run unreachable — the bootstrap deadlock, `_data_sufficiency.md` Section C.)*

---

## Phase 2 — Synthesize (leader step — dedup · cluster · rank)

Converge the scan outputs into ranked themes. This is inline leader judgment (not spawned — it needs all scan JSON in context; the outputs are compact).

⚠ **Ordering note — three of step 2's bullets need Phase 2.5 first.** Most of step 2's clustering bullets (agent/gate/tool/flow friction, convention drift, standards confirmation) route straight from Phase 1's scan output and have no cross-phase dependency. But the **role performance**, **rule performance**, and **model-tier performance** bullets below explicitly source from "the Phase 2.5 scorecard" — so, for those three bullets only, compute Phase 2.5 (below — it's inline leader judgment too, no new instrumentation, cheap to run early) *before* finishing this clustering step. Phase 2.5 is numbered and written after Phase 2 purely because it's a large, self-contained computation that deserves its own section, not because it executes strictly after Phase 2 end-to-end.

1. **Dedup** — the same underlying signal often appears in >1 scan. Merge by **evidence identity**:
   - a revert SHA in both `scan_git.reverts` and `scan_corrections.reverts` → one item.
   - a hotspot area that also shows up as a correction → one item, carrying both evidences.
   Keep the union of evidence; do not double-count frequency.

2. **Cluster into themes** and route each to its evolution target:
   - **agent friction** (rediscovery, repeated tool-error, rework) → ③ habit (a role's `.claude/agents/<role>.md`, **below its `<!-- guild:persona:habits -->` marker**) or ⑥ fact (`.claude/guild/knowledge/`).
   - **gate friction** (repeated lint/type failure, committed secret, a correction that recurs) → **fail-to-rule** → a new rule that catches what tests couldn't (quality-tool evolution). **Two routes by scope:**
     - **A · native boundary rule** — express it as a `- forbid: <glob> imports <substr>` line in `.claude/guild/gates/rules/boundaries.md`. **evolve applies it directly** (HITL), starting `status: draft` (WARN-only until confirmed — INV6); the Guild gate enforces it. Self-contained, low blast radius.
     - **B · external lint/Semgrep rule** — when the check needs a real linter (e.g. "no hardcoded widget text-color literal, use CustomTheme token"): **run the tool to self-verify** (`_data_sufficiency`-style evidence). *Tool present + 0 existing violations* → evolve applies the config rule directly (verified by the run). *Tool missing, OR existing violations found* → this exceeds a micro-apply (needs tool install and/or multi-file fixes) → **create a GitHub issue** (`/gld dev` will implement+test+review it: "[Guild] adopt/configure `<tool>` + rule `<X>` + fix N existing violations in `<files>`") — human confirms issue creation (same pattern as audit→refactor issue). ⚠ Never leave CI red; never weaken an existing lint rule to make room (INV2).
   - **tool friction** (the same multi-step bash/command sequence is reinvented across sessions or PRs — visible as repeated near-identical command blocks in `scan_transcript`/`scan_git`) → propose codifying it as a reusable script under `.claude/guild/tools/<name>.sh`, referenced from the relevant role's habit via a one-line pointer ("use `.claude/guild/tools/<name>.sh` instead of retyping the sequence") rather than a new external integration — Guild's Tool axis here means scripts the harness already has permission to run, not new tools/APIs. Low-risk additive, same track as a ⑥ fact.
   - **flow friction** (the spine itself was awkward) → **upstream-contribution candidate** (flag for `/gld contribute`; do NOT apply locally). **Concretely**: append one entry to `.claude/guild/overlay/contribute-candidates.md` — `- problem: <one-line> — change: <one-line proposed flow/base change> — evidence: <ref> — evolve #<n>` (labeled fields, in this exact order — `contribute.md`'s sanitize step reads them by these labels: `problem`/`change` generalize into contribute's "왜 broadly useful" framing, `evidence` gets stripped/genericized as repo-local, `evolve #<n>` is this run's number from Phase 0 step 3, the provenance carried into the upstream issue for dedup). ⚠ **This is a genuine exception to INV1's "dry-run never writes"** (below, Hard rules) — it fires during `--dry-run` too, since it's a passive advisory note (like `_signals.md`'s append-only capture), not an applied change to the codebase/agents/knowledge/gates; nothing about the harness's actual behavior changes from this write. **Mechanism** (its own Bash call — `_bash_rules.md`'s temp-file *comment*-PATCH pattern doesn't apply here, this is a local-file append, not a GitHub comment; use the bundled-Python sanctioned exception instead, same pattern as Phase 7's consolidation bridge below):
     ```bash
     python3 -c "
import os
p = '.claude/guild/overlay/contribute-candidates.md'
os.makedirs(os.path.dirname(p), exist_ok=True)
new = not os.path.exists(p) or os.path.getsize(p) == 0
with open(p, 'a', encoding='utf-8') as f:
    if new:
        f.write('# Contribute candidates (upstream-flagged flow friction — /gld contribute reads this)\n\n')
    f.write('- problem: <one-line> — change: <one-line> — evidence: <ref> — evolve #<n>\n')
"
     ```
     (Fill the four `<...>` placeholders with the real values before running — the literal snippet above is the template, not the call to make verbatim.) Without a durable artifact here, `/gld contribute` Step 1 (which reads exactly this file) has nothing to detect — a flag that only exists as narration in this run's chat output is invisible to a later, separate `/gld contribute` invocation.
   - **convention drift** → `docs/standards/conventions.md`.
   - **standards confirmation (② lifecycle — Outer Loop)** → a **`draft → confirmed`** proposal for a `docs/standards/*` entry, **derived** (no new signal): a draft standard whose governed **area was active** (scan_git shows commits there) yet accumulated **no corrections** against it (scan_corrections clean for that area) across recent cycles → evidence it *held up*. ⚠ **Rubber-stamp guard**: propose confirm **only** with that positive evidence ("governed a real cycle uncorrected"), never merely because it is old/unconfirmed. Applied via the normal HITL pipeline (a `status:` field flip is low-risk + reversible — INV3). This makes confirmation an evolve byproduct instead of a manual flip that never fires.
   - **role performance** (from the Phase 2.5 scorecard) → **HR proposal**: **promote** a ground-truth-successful habit — **explicit skill-automation threshold: a habit that has held ground-truth-successful across N≥3 consecutive cycles** (deliberate → automatic "compiles" into a deterministic gate/checklist rule — the 대뇌→소뇌 move) → propose promoting it to a gate rule (route via the fail-to-rule path: native boundary rule, or a `draft` standard). Below N, keep it a habit. Also **hire** a recurring unmet-need specialist (activate a roster role) · **retire** a never-convened role · **replace** a consistently-overturned one. ⚠ **`role: auditor` is never an HR subject** — it is not on the roster (`_handoff.md` Section G), so it can be neither hired, retired, nor replaced; its entries count only as *evidence about the roles it overturned*, never as a row of their own. HR needs a *trend* (Phase 2.5) — never propose off one run.
   - **rule performance** (from the Phase 2.5 **rule scorecard**) → **rule HR (completes the lifecycle: rules grow *and* retire, symmetric with agent HR)**: **demote** a noisy rule (fires often, high dismissal rate, ~0 real hits) down the ladder `block → warn → off` (the reverse of draft→warn→block promotion) · **retire/archive** a stale rule (its guarded area long-unchanged, 0 real hits — `Active→Stale→Archived` lifecycle). ⚠⚠ **INV2 HARD EXEMPTION — non-negotiable**: the **secret** and **verification-weakening** gates are universal and MUST NEVER be demoted, disabled, or retired by this mechanism, regardless of firing/dismissal stats. Rule HR applies **only to stack-specific / boundary rules**. A rule-retirement engine that could weaken core verification would defeat its own purpose. Needs a **consistent trend across ≥3 cycles, never off one run** — the same stricter-than-base-Axis-2 bar as model-tier HR (`_model_tiering.md` Section C), since a bare 2-point trend (the base Axis-2 unlock, `_data_sufficiency.md` Section A) is too noisy for a demote/retire call.
   - **model-tier performance** (from the Phase 2.5 **model-tier scorecard**, `_model_tiering.md` Section C) → **model-tier HR**: a role/stage combo escalated (`--escalated`) across most recent loop-backs → propose **raising its stated default** (sonnet → opus) in the command file / `.claude/agents/<role>.md`, since the retry tier is already doing the real work most of the time. Never propose *lowering* a judgment role's default to haiku on clean-run evidence alone (`_model_tiering.md` Section C — de-escalation needs the opposite-direction trend, not just an absence of escalation). Needs a **consistent trend across ≥3 cycles, never off one run** (`_model_tiering.md` Section C) — same stricter-than-base-Axis-2 bar as rule HR above.

3. **Rank** each theme by **frequency × impact × surprise** (the ranking lever the kill-gate validated):
   - **frequency** — recurrence count / distinct sessions (apply the ≥K discipline: drop 1-offs *unless* anchored+high-impact).
   - **impact** — a human correction (overturned work) > a **cross-role reversal** (one role's confident output overturned by another, anchored to a `BLOCKED`/defect — `scan_corrections` tags the source) > a structural coupling fact > a convention nit; BLOCKER/MAJOR readiness gaps outrank MINOR. Anchor impact to charter priorities when known.
   - **surprise** — boost items where a **confident choice was overturned** or a **guard was pierced**. Sources, in order of strength:
     1. `surprise:true` flags in the ground-truth log — a human overturning a confident choice (discuss-override), a **stagnant loop-back** (the same blocking reason recurring across attempts — `_stagnation.md`), a **cross-role reversal** (a design-stage specialist `BLOCKED` reversing a decided approach, tech-lead/gate `BLOCKED`, or a QA/designer defect the test stage passed), OR a verify self-report ↔ runner gap. All carry the flag; rank them human > stagnation > cross-role > verify-gap per their anchor (`_signals.md` Section B) — stagnation ranks above a single cross-role reversal because it is a *repeated*, unresolved reversal (two loop-backs failed against the same reason), stronger evidence of a systemic problem (skeleton/standard/rule) than a one-off catch.
     2. **Derived from durable signals when the log is empty** (the kill-gate case): a revert, an immediate fix-on-fix, a PR closed-unmerged, or a duplicate-issue discovery are all inherently surprising (confident work undone) — treat them as surprise-positive even with no ground-truth entry. *(This is why A1 "guard existed yet bug escaped" and A3 "confident work reversed" ranked top at the kill-gate without any transcript.)* ⚠ **Caveat**: *derived* surprise overlaps with the correction signal itself (not a fully independent third factor) — use it as a tie-breaker that lifts overturns, not as independent evidence. Only ground-truth `surprise:true` flags (source 1) are truly independent.
     3. **Prior-applied regression (self-inflicted — ranks above sources 1 & 2)**: a fresh signal (revert, correction, gate-firing, or new friction) whose target — file, role, or rule — matches an entry in the **prior-applied targets** list (Phase 0 step 3) is evidence the growth engine itself introduced or missed a problem, not merely that one existed. Rank it **above** a plain human-surprise flag: the system did not just fail to catch a bug, it *caused* one via self-modification. Tag the theme `panel-miss candidate`; carry it into Phase 3 as a **correction/tightening of the original item** (not a fresh unrelated theme) and into Phase 4 as calibration input for the panel ("Panel calibration input"). Log every hit to the ledger's regression tally **regardless of tier** (Phase 7) — this is the held-out check for whether a past apply actually helped, not just whether it looked safe at apply time ("test transfer beyond the improvement signal").

4. Assign each theme a **tier** for human triage: **A** (accept — clear, anchored, high rank), **B** (worth considering), **C** (noise / not actionable — surface anyway, as the discriminating power *is* the signal quality). Drop anything the ledger already rejected (P0) unless new evidence crossed the threshold.

---

## Phase 2.5 — Per-agent scorecard (360° · ground-truth-anchored) — HR basis

Score each **active role's** recent performance — the basis for HR proposals (Phase 3) and for `sprint retro`'s capacity calibration (per-agent 성적표). **Ground truth is highest-weight; agent opinion counts only when it anchors to ground truth (back-patting guard).**
- **Ground truth (per role — highest weight)**: objective outcomes tied to the role's own work — its stage's test/gate/CI pass↔fail, reverts of its commits, human corrections/acceptances (`scan_corrections.role`), and the **agent↔agent captures** (was this role *overturned* [−] or did it *do the overturning* on solid grounds [+]?).
- **Agent opinion (lower — only if corroborated)**: self / peer (sibling role) / leader / external-auditor views. An unanchored "동료가 좋다고 함" does **not** move the score (back-patting; the external auditor guards this). No promotion on opinion alone.
- **Trend**: compare to prior-run scorecards in the ledger — improving / flat / declining per role. A single run is a **weak sample** — advisory until corroborated across runs.
- **Held-out evidence (overfitting guard)**: when judging whether a *previously applied* item helped, count only evidence **not already cited** as that item's original Phase 3 evidence (match by evidence identity — same mechanic as Phase 2's dedup). A role/rule reads as "improving" only if the same PR/SHA that justified the original change is being recounted is **not** confirmation — it's circularity. This applies to the per-agent, rule, and model-tier scorecards alike; a trend needs *fresh* post-application evidence, not a restatement of the evidence that triggered the change.

Carry the scorecard into Phase 3 (HR) and record it in Phase 7. **Trend-gated by Phase 1.5 Axis 2** (`_data_sufficiency.md`): at `no-trend` (0 prior runs) the scorecard *verdicts* and HR proposals are skipped — HR needs a trend, not one run (the banner already stated this; do not re-explain).

**Overseer row (③ human-growth engine — `_learning.md` Section D)**: also score the **human overseer** as a distinguished, authority-tier member (NOT HR-able) — their **decision patterns** (recurring discuss-overrides by theme, accepted-risks = measured defects knowingly kept, PR-rejection reasons), **blind spots** (a decision later contradicted by an *objective* outcome — a kept risk that became a real defect; anchor to the outcome, not "an agent disagreed"), and **per-area competence trend**. Ground-truth-anchored (higher bar — `_learning.md` Section B); advisory until corroborated.

**Rule scorecard (symmetric with the per-agent scorecard; feeds rule HR)**: score each **stack-specific / boundary** rule from durable data (no new instrumentation): read `.claude/guild/memory/gate-firings.jsonl` (the gate's firing log — count firings, block/warn split), cross-reference `.claude/guild/gates/dismissed.md` (accepted-risk = the human overrode → a **noise/false-positive** proxy), and `scan_git` for the **guarded-area churn** (is the area it protects even changing?). Per rule: **firing count · dismissal rate · estimated real-hits** (fired → human *fixed* the code) **vs false-positives** (fired → *dismissed*) **· area churn**. Trend across runs (ledger) — same weak-sample caveat as the agent scorecard, and the same ≥3-cycle consistency bar as model-tier HR (Phase 2's rule-HR gate above; this ≥3-cycle bar is specific to rule/model-tier HR's demote/retire/tier-change proposals — it does not extend to general agent hire/retire/replace, which only needs *a* trend, never one run, per Phase 2 step 2's "role performance" bullet). ⚠ **Do NOT score the secret / verification gates for retirement** — they are exempt (INV2, see Phase 2 rule HR); the scorecard covers only demotable stack-specific/boundary rules.

**Model-tier scorecard (`_model_tiering.md` Section C — feeds model-tier HR)**: no new instrumentation, no second read — reuse Phase 1's `scan_corrections` output (`ground_truth[]`, which already carries `escalated` through per entry). Group execute-stage loop-back entries by `role`+`stage`; per group, the fraction carrying `escalated:true` is the escalation rate. ⚠ **Exclude `role: auditor` entries from every group and from the denominator.** They come from the execute stage's always-on external auditor (`_execute_spine.md` Step 3.5a), which is **not a roster role** (`_handoff.md` Section G): it has no `.claude/agents/auditor.md` and no stated default, so the proposal below would have no file to edit. Its entries also never carry `--escalated` (the spine forbids the flag there for exactly this reason), so leaving them in the denominator would silently deflate the escalation rate of whatever group they landed in — a rate about a role that was never being measured (`_model_tiering.md` Section C). Trend across runs (ledger), same weak-sample caveat + Axis-2 trend gate as the agent/rule scorecards — a role/stage combo needs a **consistent** pattern (repeatedly escalated, or repeatedly never-escalated) across ≥3 cycles before Phase 2 proposes anything.

## Phase 3 — Propose (proposal list · distillation ladder)

Present a **ranked proposal list** to the human. For each Tier A/B theme, propose the **smallest sufficient change** via the distillation ladder ("성장=밀도, not 단조증가"):

> **patch** (tweak an existing line/section) **> umbrella-extend** (widen an existing rule/habit to cover the case) **> reference-add** (add a fact/pointer) **> new** (create a new rule/role — last resort).

Each proposal states, in ≤ ~500 chars (context budget):
- **Target file** the human should edit — a role habit → `.claude/agents/<role>.md`, **below its `<!-- guild:persona:habits -->` marker** (③); a decided rule → `docs/standards/…` (②); a **discovered code fact** → `.claude/guild/knowledge/facts/<area>.md` (⑥); a **repeated command sequence** → `.claude/guild/tools/<name>.sh` (Tool axis) plus the one-line habit pointer to it; an **HR change** → `config.json` `roles` + the agent file. **HR mechanics:**
  - ⚠ **Where a habit goes, and how to write it.** The region between `<!-- guild:persona:start -->`
    and `<!-- guild:persona:end -->` is central-owned — `update` replaces it wholesale, so anything
    written there is lost on the next update. Habits go **below `<!-- guild:persona:habits -->`**.
    - **If the file has no habits marker** (every repo initialized before this shipped), create the
      section at the end of the file: a `## ` heading rendered in `config.language` — "역할 습관" in
      `ko` — followed by the marker line, which is **never** localized. If there is more than one
      habits marker, use the topmost and report the duplicate.
    - **Name the anchor in the lead.** Start a habit bullet with `**<중앙 불릿 이름> — <한 줄 제목>**:`,
      naming the central bullet it refines. Prose narrows by succession — a later sentence qualifies
      an earlier one — so a habit that says which bullet it attaches to reads as a refinement of that
      bullet rather than a free-floating rule. This is what keeps a habit out of the central region
      without losing the connection to it.
  - **hire** = add a `.claude/agents/<role>.md` (canonical descriptive name) + add to `roles`. ⚠ Give it
    the **habits section only** — the `## ` heading plus `<!-- guild:persona:habits -->`. Do **not** add
    a `persona:start`/`end` pair: that pair declares a central-owned region, and a hired file's body is
    local prose that did not come from a template. `update` leaves it alone, which is the correct
    outcome — but it must not be *counted* as pending migration: that reads as backlog and the
    remedy it prints (`--migrate-personas`) refuses the file (`HITL(not-from-init)`). `update`
    reports these under **hired (local body, no central region)**, a steady state with no action.
  - **retire** = **reversible archive, NOT delete** — move `.claude/agents/<role>.md` → `.claude/guild/archive/agents/<role>.md` (committed, so it is auditable and **restorable**) and drop the name from `config.json roles`.
  - **replace** = archive the old role + hire the new.
  - ⚠ **Knowledge survives retirement**: ⑥ facts are **org-shared** (`.claude/guild/knowledge/`) and are **never removed** when a role retires — a retiring role takes only its own ③ habit (its agent file, now archived) and ④ episodes; the discovered code knowledge stays for the remaining org (this is why retirement is safe — no knowledge loss). **Restore** = move the file back from `archive/agents/` + re-add to `roles`.
  - `leader` is **never** hired/retired/replaced. Pick the store by kind (`_knowledge.md` Section A).
- **Ladder rung** + the concrete proposed edit (a habit line, a fact, a convention, a gate-rule candidate).
- **⑥-fact proposals** (`_knowledge.md`): specify **both** the `facts/<area>.md` fact (statement · evidence · relation · provenance `evolve #<n>`) **and** its `index.md` pointer (key = path/area) — a fact with no index entry is unreachable at retrieval. Prefer patching an existing slice over a new one (ladder).
- **Evidence** — the concrete artifact(s) (SHA / PR# / issue# / ground-truth entry / session count). No bulk paste.
- **Mapping + rank + tier** (why it ranks where it does; surprise noted if it drove the rank).

The four fields above (target file · ladder rung · evidence · mapping/rank/tier) are the **internal bookkeeping** for this proposal — keep them, they drive Phase 4/6/7. But whenever this proposal is actually **shown to the human** (Phase 5), translate it through the plain-language rule (top of file) into something like:
> *"제안: OO 파일에 이런 내용을 추가/수정하려고 합니다. 이유: 최근 PR #123, #145에서 같은 문제가 반복됐어요. 검토 결과: 안전하고 실제로 도움이 됩니다."*
No "Tier A", no "ladder rung: patch", no bare `evidence:` field, no `INV`/`Phase` labels.

**Population-based candidate generation (meta-prompting — trigger-gated, not a flag)**: for a ③ habit **patch** proposal, generate **3 candidate phrasings instead of 1** only when **both** hold this run — (a) **≥3** Tier-A themes route to a ③ habit patch (the "N candidate habits per run" heuristic), **and** (b) Phase 0's Axis 2 reads `trend` (≥1 prior run — the scale proxy the deferred trigger called for; reused from `_data_sufficiency.md`, no new instrumentation). Below threshold, propose the single best candidate as before — population mode never replaces the validated default path, it only activates when the run's own evidence justifies the extra cost.
- **Generation** — one sub-agent call per theme produces all 3 candidates together (not three separate spawns, so the cost is N× text, not N× agents): a **terse-imperative** phrasing (mirrors the target habit file's existing terseness), an **example-anchored** phrasing (states the rule via the concrete evidence case), and a **minimal-diff** phrasing (smallest edit that satisfies the evidence, ladder discipline maximized). The call's meta-prompt carries the theme's evidence + the target habit file's current content as style context.
- **Selection is Phase 4's job, not a new judge**: all 3 candidates for a theme are carried into Phase 4 as one bundle; each of the 3 lenses picks the strongest candidate (or drops all) instead of reviewing a single draft — reuses the existing panel, adds no unaudited judge. Phase 5 shows the human only the winner, with a one-line footnote ("대안 2개 중 이게 최선이었어요") — never a dump of all candidates.
- **Self-validating the trigger**: Phase 7 records, per population-mode item, which candidate won. This is the evidence the deferred guard itself asked for ("adopt only when it beats the single-attempt baseline") — if the held-out check (Phase 2.5) later shows population-mode items faring no better than historical single-attempt patches, that is grounds to raise the threshold back up, not evidence to keep silently.

**Densify (⑥, invariant 3 — growth = density):** also scan the existing `knowledge/` for **duplicate facts to merge, stale facts to remove** (evidence no longer reproduces against current code), and **over-specific facts to generalize** — propose these as first-class items too. ⑥ should get *denser*, not just bigger.

**Index-overflow split (flat structure doesn't scale, `_knowledge.md` Section D.2)**: also check `index.md`'s length. Past a screenful (the same bar `_knowledge.md` invariant 2 and `audit.md` dimension C already use for "sprawling"), propose splitting the most sprawling area's pointers into a **nested index** under a module-scoped path, loaded only when that area is touched — the split mechanism itself is already specified in `_knowledge.md` Section D.2; evolve's job here is to **notice the threshold and propose triggering it**, not invent a new structure. Ladder rung: `patch` (the top-level index shrinks to a pointer to the nested one). Left unchecked, a flat index degrades into recency-biased, noisy recall as ⑥ grows.

**Presentation** (plain language throughout — per the top-of-file rule; group/order internally by tier, but never print the word "Tier" or a bare letter grade to the human):
- **`--dry-run`** → print the full list, most-important first, each item in the plain "무엇을 / 왜 / (아직 패널 검토 전이므로 검토 결과는 생략)" shape from Phase 5's template. Group with plain headers — "먼저 확인해 주세요" (priority items) / "참고해 보세요" (worth considering) / "이런 것도 있어요, 급하진 않아요" (noise-leaning, shown for transparency, one-line reason each). **Stop here** with the hand-off: *"제안 목록입니다 (dry-run). 코드베이스/에이전트/지식/게이트는 미수정 — 직접 편집하거나 `/gld evolve --apply`로 승인·적용 파이프라인을 도세요."* (if any flow-friction candidates were flagged this run, also note: *"흐름 개선 후보 N건은 `contribute-candidates.md`에 기록했습니다 (dry-run에서도 기록 — `/gld contribute`용 별도 advisory 트랙)."*) Optionally write the full list to a session-scratchpad digest (`<scratchpad>/gld-evolve-<repo>.md`) — **scratchpad only, never the repo**.
- **Otherwise (apply mode / default-then-ask)** → **do NOT dump the full detailed list up front** (that produces a wall of items the human has to hold in their head before the real per-item decision even starts). Print only a **one-line tally** in plain words — *"제안 N건을 찾았어요 — 검토 후 하나씩 함께 살펴보겠습니다."* (no letter grades) — then carry the priority items into **Phase 4**. The lowest-priority ("noise-leaning") items are not carried forward but stay in this run's record for Phase 7. The detailed per-item content is what Phase 5 shows, one item at a time, in plain language — do not repeat it here.

**Nudge (read-only)**: if the friction *trend* is worsening or a signal reads like a diagnostic gap rather than a single fix, **note that a `/gld audit` pass would help** (evolve↔audit mutual nudge).

**감독자 회고 (③ overseer growth — B, `_learning.md`)**: after the proposal list, present a short **overseer reflection** from the Phase 2.5 overseer row — the human's recurring decision patterns / blind spots + **the principle behind each** (A). E.g. *"WCAG 대비 위험을 3회 수용하셨습니다(#891/#893/#894) — 근본 원리: 모드 의존 토큰은 isLightMode 분기 필수."* **Hard rules (`_learning.md` Section B)**: every reflection **ground-truth-anchored** (a verified outcome / ⑥ fact / confirmed standard — never AI opinion; unanchored → "인사이트 후보(미검증)"); **advisory · opt-in · non-condescending** ("이런 인사이트가 있습니다", not "틀렸습니다"); read-only toward the human (INV1 authority intact). **Skip at `no-trend`** (Phase 1.5 Axis 2 — `_data_sufficiency.md`; needs a trend). Fade with competence (F).

---

## Phase 4 — Adversarial panel review (P4 — refute before apply)

For each Tier A/B proposal, run an **isolated multi-lens panel** that tries to **refute** the change (외부자). Spawn **fresh sub-agents** (`subagent_type: general-purpose`, no Guild persona → no confirmation bias; an isolated fresh session via independent context).

**Panel calibration input (self-correcting critic, additive-only)**: before spawning lenses, check whether Phase 2 flagged any `panel-miss candidate` this run (a fresh signal whose target matches a prior-applied item — surprise source 3). If so, append the most recent 3–5 such misses (target · what was applied · what went wrong afterward, one line each) to the **degradation lens's** prompt as explicit caveats to watch for. This is the only channel by which the panel's own rigor evolves, and it is **strictly additive**: it may only make a lens *more* skeptical about a pattern that has bitten before — it may never loosen a verdict criterion, drop a lens, or override a fresh lens's independent judgment. The lens definitions themselves (correctness/degradation/redundancy) stay fixed in this file, gated by this skill file's own review process — only the caveat list carried into the prompt changes run to run, and it only ever grows more cautious.

Scale the panel to risk:
- **Agent-def (③) / gate / standard (②) changes** = higher risk (they alter how every future task runs) → **3 lenses**, each a separate agent: **correctness** ("is the change factually right + does it actually address the evidence?"), **degradation** ("does it over-constrain, contradict an existing rule, or **weaken verification**? — INV2"), **redundancy** ("is this already covered by an existing rule/habit/fact?").
- **⑥-fact / convention / tool-script (low-risk additive) changes** → **1 lens** (correctness + redundancy combined) is enough.

Each lens returns `{verdict: keep|drop|edit, reason, (edit: suggested change)}` — **its `reason`/`edit` prose in `config.language`** (tell the spawned lens explicitly; the `verdict` enum stays ASCII). **Drop rule**: a proposal a **majority of its lenses reject** is dropped (recorded to the skip-list, P7). A **degradation-lens veto on an INV2 grounds is absolute** — any hint of verification-weakening drops the item regardless of the other lenses. Surviving proposals (some possibly edited by a lens) go to Phase 5, carrying the **per-lens verdict mix** with them — Phase 5 turns that mix into the human-facing recommendation label (승인 / 수정 후 승인 / 신중히 검토).

**Population-mode bundles (Phase 3 candidate generation)**: when a theme carries 3 candidates instead of 1, each lens returns `{verdict: keep|drop, chosen: <A|B|C>, reason, (edit: optional refinement of the chosen candidate)}` instead of reviewing a single draft — same three questions (correctness/degradation/redundancy), applied comparatively. **Drop rule unchanged** (majority-reject drops the theme entirely, not just one candidate); **chosen-candidate rule**: the candidate picked by a majority of lenses wins — a 3-way split with no majority falls back to the **minimal-diff** candidate (the most conservative option, consistent with the ladder's own bias toward the smallest sufficient change). This is the only place the panel compares options rather than refuting one; it does not relax the refutation bar.

**`edit` verdict bar (keep it meaningful, not the default)**: tell every spawned lens explicitly — `edit` is for a **substantive** problem with the proposed wording/scope (it materially changes what the rule/fact/habit will do, or fixes something that would otherwise mislead). A lens that would merely polish phrasing, tighten wording, or make a cosmetic style tweak must return `keep` and put the nit in `reason` as an aside (not the `edit` field) — it does not change what gets applied. **Rationale**: lenses are instructed to hunt for problems (Phase 4 opening), so left unconstrained they tend to always find *some* wording nit, which would make `edit` — and the `패널 권장: 수정 후 승인` label it drives — the default for nearly every item and drain it of signal. Reserve the label for proposals that genuinely changed shape under review.

## Phase 5 — Approval gate (P5 — per-item HITL · INV1)

**Step 0 — persona boundary re-targeting (before presenting anything).** A persona file has a
central-owned region between `<!-- guild:persona:start -->` and `<!-- guild:persona:end -->` that
`update` replaces wholesale. A habit written there is lost on the next update — silently, months
later. So before an item reaches the human, check where it would land:

- **Scope**: items that add, change, **or delete a body line** in `.claude/agents/<role>.md`. Not
  frontmatter-only items (model-tier HR), not `hire` (new file), not pointer updates elsewhere.
  ⚠ Deletion and in-place change both count. Welding — a habit edited *into* an existing central
  bullet — changes a line without adding one, and that is the common shape, not the rare one.
- **Locate it yourself.** The proposal carries a target *file*, not a target line. Find the line the
  patch would touch. If you cannot find it, present the item unchanged and say so.
- **If the file has a `persona:start`/`end` pair** and the line falls between them → re-target the
  item to sit below `<!-- guild:persona:habits -->` instead, and present *that* version.
  ⚠ **If there is more than one habits marker, take the topmost first, then apply the order
  check below to that one** — the two rules compose in that order and only in that order.
  ⚠ **Check that the habits marker is below `persona:end` before re-targeting to it.** If it is
  above — a shape `--migrate-personas` refuses and `update`'s rule 3b reports as `marker order` —
  then "below the habits marker" is still inside the central region, and re-targeting there writes
  the habit into exactly the span the next `update` replaces. That is the loss this gate exists to
  prevent, arrived at by obeying the gate. In that case do not re-target: present the item
  unchanged, say the file's markers are out of order, and point at `/gld update` (its rule 3b
  names the repair).
- **If the file has no pair** (every repo initialized before this shipped) → re-target unless the
  line is already below the habits marker or inside the project-specialization section (`##
  프로젝트 특화` in `ko`, its localized equivalent otherwise). That section is where `/gld audit`
  routes day-1 boilerplate for evolve to grow, so leave it reachable.
- **Do not re-target a proposal that contradicts the central line.** If the proposed text keeps the
  central line as a substring — a pure addition or a qualifier appended — it is a refinement: 
  re-target it. If it deletes or replaces words of the central line, it may be *negating* the norm
  rather than narrowing it, and prose cannot hold both. Present that one to the human with the
  question stated plainly ("좁히는 것입니까, 아니면 뒤집는 것입니까?"); if it is a negation, route it
  to `contribute-candidates` instead of writing it anywhere. The substring test is a proxy and will
  mis-sort some items — it errs toward asking, which costs one question.
- **More than one habits marker** → use the topmost; report the duplicate.
- **If the file has no markers at all**, mention `/gld update --migrate-personas` once, alongside
  the item — the human is already looking at that persona, which is the cheapest moment to draw
  the boundary. Do not block on it: the item still gets presented and applied to the habits
  section either way.

⚠ **Re-targeting is not `reject`.** It does not touch the skip-list — the item is still presented and
the human still decides. `reject` (step 3) means declined-stays-declined; this is a correction of
*where*, made before the human sees it.

⚠ **This gate cannot live in Phase 6.** By the time step 3 validates, step 2 has already edited the
file, and the only per-item undo there is `git checkout -- <file>` — which also discards every other
habit this run applied to the same file (a run applies 2–5 items). Phase 6 also cannot attribute a
violating line to one item, because its diff is cumulative for the run.

Walk the **panel-surviving** proposals **one item per turn** — this is a sequential conversation, not a batch listing. For each item, in order (highest-priority first):
1. Present **only that one item**, in **plain language** (per the rule at the top of this file — no "Tier", "ladder rung", "INV", "Phase", or bare `evidence:`/`lens:` fields). Lead with an explicit, standardized **recommendation label** derived from the lens verdicts — do not bury it in prose:
   - all lenses `keep` (with no `edit` field attached — see below) → **`패널 권장: 승인`**
   - any lens carries an edit/refinement (and none dissenting) → **`패널 권장: 수정 후 승인`** — fold the suggested edit into the 왜/무엇을 lines. This check has two shapes depending on the item: **single-draft items** (Phase 4's default 3-lens/1-lens review) — a lens's top-level `verdict` is literally `"edit"`. **Population-mode bundles** (Phase 3 generated 3 candidates) — a lens's `verdict` is only ever `keep`/`drop` (never `"edit"` — see the bundle shape above); the refinement instead lives in that lens's optional `edit` **field** alongside a `keep` verdict. Treat both the same way: `verdict == "edit"` OR (`verdict == "keep"` AND an `edit` field is present) → this label. Missing this second form would mean a population-mode refinement silently falls into the "all keep" bucket above and never reaches the human.
   - a lens `drop`ped but was outvoted (survived only because it wasn't a majority) → **`패널 권장: 신중히 검토 (우려 있음)`** — this is the one case where the human is choosing against a real dissent, so surface it clearly.
   Then the plain-language body:
   - **무엇을**: one plain sentence — what would change and where (name the file/role in ordinary words, e.g. "테스터 역할의 습관에 한 줄 추가").
   - **왜**: one plain sentence with the evidence woven in as a story, not a field (e.g. "최근 PR #123, #145에서 같은 실수가 반복됐어요").
   - **우려** (only when the label is `신중히 검토`): one plain sentence naming the dissenting lens's concern, so the human's accept/reject/edit choice is informed (e.g. "우려: 기존 규칙과 살짝 겹칠 수 있다는 의견이 있었어요").
   - **변경 내용 (diff)**: right after the plain-language body, show the actual proposed edit as a small unified-diff snippet (fenced ` ```diff ` block, `-`/`+` lines, minimal surrounding context — not the whole file). This is the **one exception** to the plain-language rule: a diff is the ground truth of what will happen to the file, so show it as-is rather than paraphrasing it. Build it from the concrete edit already drafted in Phase 3 (target file's current content vs. the proposed replacement) — nothing is written to disk yet, this is a preview. If a lens suggested an `edit`, the diff reflects the lens's revised version, not the original draft. For a **population-mode** item (Phase 4's majority-vote synthesis over several candidates), diff against the **winning candidate** Phase 4 selected — never re-derive or re-pick from the original population here.
2. Ask the human to choose **accept / reject / edit** for *this item alone* and **wait for the reply** before showing the next item — never list several items in the same message and ask for a combined decision, and never move to item N+1 until item N is resolved. **Repeat the recommendation label in the question itself** (the body above may be long enough that the human has forgotten the label by the time they reach the decision) — e.g. *"(패널 권장: 수정 후 승인) 이 항목을 적용(accept) / 거절(reject) / 수정(edit) 중 무엇으로 할까요?"*.
3. Record the decision and move to the next item:
   - **accept** → queued for Phase 6.
   - **edit** → the human's revised version is queued.
   - **reject** → recorded to the skip-list with the reason (P7; declined-stays-declined + offset).

**Nothing proceeds to apply without an explicit accept** (INV1). Unattended (`GLD_UNATTENDED`): evolve does **not** auto-accept harness changes — it stops here and marks the run "needs-human" (self-modification is never unattended).

## Phase 6 — Apply (P6 — backup → apply → validate → auto-rollback → provenance)

**Step 0 — clean-tree gate (blocking; runs on EVERY path that reaches apply, not only after `--apply`).** Before touching a single file, re-check the working tree — its own Bash call:
```bash
git status --porcelain
```
- **Empty** → proceed; this tree state is the backup baseline every step below relies on.
- **Non-empty** → **stop before applying anything.** Do not apply a subset, do not auto-stash, do not `git stash`/`git checkout` anything the human did not ask you to. Report, in plain language: that nothing was applied, **which files are dirty** (list the paths `git status --porcelain` returned), and that the human should **commit or stash them and re-run `/gld evolve --apply`**. The Phase 5 accept/reject/edit decisions stay in this run's chat record so the re-run can be told what was already agreed, but **write nothing to the ledger** — the tree is already dirty, an uncommitted entry would only add to it, and the re-run produces the real entry.

⚠ **Why it is re-checked here and not trusted from Phase 0**: the default invocation ("propose, then ask") never runs Phase 0 step 4 at all, and on the `--apply` path Phase 5's per-item conversation can take arbitrarily long while the human edits files in another window. Step 1's backup *is* the tree's pre-state and step 4's rollback is `git checkout -- <file>` — against a dirty tree that would discard the human's unrelated in-flight work, which is exactly the harm INV3 exists to prevent. An auto-stash was deliberately **not** chosen: silently moving a human's work is a bigger surprise than stopping.

For the accepted set, apply as **one reversible unit** (INV3). Per item:

⚠ **Writing the first habit into a persona.** The habits section ships with one placeholder line —
`- (아직 없음 — …)` in `ko`, localized elsewhere. **Delete that line and write in its place**; do not
leave it above the real habit. `/gld audit` and `/gld monitoring` read a persona's boilerplate state,
and a placeholder sitting above real content reports a grown role as still at day one.

⚠ **Multi-file items** (a hire/retire/replace HR item touches both the agent file *and* `config.json`'s `roles` field; a ⑥-fact proposal touches both `facts/<area>.md` *and* `index.md`; a tool-script proposal touches both the new script *and* a habit-pointer edit in the role's agent file): steps 1-4 below apply **independently, per constituent file** — back up, apply, and (on failure) roll back each file separately, not as an opaque single unit. A **retire** (an existing agent file's path disappearing, or moving to an archive path) is a pre-existing-file case for rollback purposes even though the net effect looks like a deletion — `git checkout -- <file>` restores it. Step 6's provenance stamp only applies to file formats that support a frontmatter/comment annotation (agent `.md`, ⑥ fact `.md`, standards `.md`) — skip it for `config.json` (pure JSON, no comment syntax); its change is already accounted for by the commit message and the ledger entry (Phase 7).

1. **Backup** — the clean git tree is the baseline (Step 0's gate just confirmed it); note the pre-state. Also note whether the target file **already existed** before this apply (`git status --porcelain <file>` on the untouched tree, or simply: does the file exist yet) — step 4's rollback needs to know this.
2. **Apply** — Edit/Write the target file with the accepted (or edited) change.
3. **Validate** (deterministic):
   - **schema** — an agent def still has valid frontmatter (`name`/`description`/`model`); a ⑥ fact has its `index.md` pointer; a standard keeps its `status` frontmatter.
   - **description budget** — any changed `description`/fact ≤ ~500 chars (context budget).
   - **quality gate** — the repo still parses / the harness still loads (no broken markers/refs).
   - **tool script sanity** — a new/changed `.claude/guild/tools/<name>.sh` parses (`bash -n <script>`) and its referencing habit pointer resolves to an existing file.
   - **⚠ verification-weakening HARD-BLOCK (INV2)** — if the change (or its side effects) deletes/weakens a test, a gate rule, or a verify step → **reject the item + roll it back**. Non-negotiable, no override.
4. **Auto-rollback on any validation failure** — the correct undo depends on whether step 1 found the file pre-existing: **pre-existing file** (an edit) → `git checkout -- <file>` (restores the tracked pre-state). **Brand-new file** (a hire/new-rule/new-script apply) → `git checkout -- <file>` does **not** work here (nothing tracked to restore to — it errors/no-ops on an untracked path); use `rm -f <file>` instead. Report either as "applied-then-rolled-back: <reason>". Other accepted items still proceed.
5. **Stage the surviving applied files** — `git add <file>` for each item that passed validation (its own Bash call per file, or one call listing all surviving paths) — the commit below has nothing to commit without this.
6. **Provenance stamp** — annotate the applied artifact (frontmatter/comment or the fact's `provenance`) with `evolve #<n> (<date>) — evidence: <ref>`, **then re-stage it** (`git add <file>` again — the provenance edit happens after step 5's staging, so the staged version would otherwise miss it).
7. **Write the run's ledger entry NOW — before the commit, so it lands *inside* it.** Read the pre-commit baseline first (its own Bash call):
   ```bash
   git rev-parse HEAD
   ```
   Then write the full **Phase 7** run entry (whole schema, below — header · per-item `[applied]`/`[rejected]` · regression tally · cost summary · scorecards) into `.claude/guild/evolution-log.md` with the Edit/Write tool, keying it on `evolve #<n>` (the run number computed at **Phase 0 step 3** — use that held literal, never recount here; the same tag the commit subject below carries) and recording that literal parent SHA as `applied-onto: <parent-sha>`. Then stage it (its own Bash call):
   ```bash
   git add .claude/guild/evolution-log.md
   ```
   ⚠ **Reasoning — this ordering is the fix, do not "tidy" it back**: `rollback.md` and Phase 0 step 3 both read this file as a *durable* record (skip-list, prior-applied targets, `[reverted]` annotation), so an entry appended after the commit would be uncommitted, invisible to a fresh clone or a `git checkout`, **and** would leave the tree dirty — which Step 0's gate then blocks on the next run.
   ⚠ **Why the entry carries no SHA of its own commit**: a commit can never contain its own hash (writing it in would rehash the commit — the fixed point does not exist), and folding it in with a second `git commit --amend` only records the *pre-amend*, now-dangling hash. So the run's commit is identified by two things that *are* knowable beforehand and stay true: the `evolve #<n>` tag in its subject, and `applied-onto: <parent-sha>` (the commit is `<parent-sha>..HEAD`, always exactly one commit). When `/gld rollback <sha>`'s ledger grep for a raw SHA misses, resolve the entry by that subject tag instead (`git show <sha>` prints it) — same entry, no stale hash published.

Commit the surviving, staged applied set — **applied files + provenance stamps + the ledger entry, all as one commit** (one commit per run, INV3, unchanged). Use `--no-verify` — the applied changes are **harness docs/config, not code**, so the repo's own code-test pre-commit hook is irrelevant here and can hang on a large suite.

⚠ **`--no-verify` skips *every* git hook, Guild's included.** Since `0.41` the authoritative gate lives in `.git/hooks/pre-commit`, so unlike the earlier `PreToolUse`-only wiring it is **not** a separate layer that survives this flag. Run it explicitly first, as its own Bash call, so the applied set is still gated:
```bash
python3 .claude/guild/gates/scripts/gate_precommit.py --git-hook
```
Non-zero exit → **do not commit**. Treat it exactly as a Phase 6 validation failure: auto-rollback the staged set **and step 7's ledger entry with it** (`git checkout -- .claude/guild/evolution-log.md`, or `rm -f` it when this was the very first run and the file was untracked — same pre-existing-vs-brand-new distinction as step 4; nothing was applied, so nothing may stay recorded as `[applied]`, and the tree must be left clean for the next run's Step 0 gate), then report the gate's reason. (This should be unreachable — Phase 6 step 3's INV2 hard-block already refuses a verification-weakening item — so a firing here means an item slipped that check, which is itself worth surfacing.) Then:
```
chore(guild): evolve #<n> — <n> changes applied
``` — so `/gld rollback <sha>` (or the ledger) can undo the whole run. Do **not** push/PR automatically (the human's repo workflow owns that). ⚠ **Exception — a route-B external-linter config edit** (direct-apply: repo `.eslintrc`/semgrep config, which is repo tooling, **not** Guild harness): commit it **through the repo's normal hook (no `--no-verify`)** — the "harness not code" rationale does not hold for a repo-config file, and the repo's own pre-commit checks should run on it. (This is the 0-violation direct-apply case; anything needing installs or multi-file fixes already routes to a `/gld dev` issue, not here.)

## Phase 7 — Ledger update (P7 — record the run)

The run entry appended to `.claude/guild/evolution-log.md` is specified here but **written at Phase 6 step 7, before the commit**, so it ships inside the run's single commit (see the reasoning there) — this section is its schema, not a separate later write. **When nothing survived to apply** (every item rejected at Phase 5, or every item rolled back at Phase 6) there is still a `[rejected]` skip-list worth keeping: write the entry here, stage it, and commit *it alone* as the run's single commit (`chore(guild): evolve #<n> — 0 changes applied`) — one commit per run holds, and the tree is left clean for the next run's Step 0 gate. (A `--dry-run` never reaches this phase — it stops at Phase 3 — so it still writes no ledger at all, and therefore spends no run number: the next run takes the same `<n>`. Phase 0 step 3.)
- **Run header** — date · `evolve #<n>` (Phase 0 step 3's held literal — writing this entry is what spends the number) · `applied-onto: <parent-sha>` (Phase 6 step 7) · signal counts (by scan) · **friction snapshot** (permission/rework/gate-violation counts vs the prior run — the trend that measures "did evolution help?").
- **Per accepted item** — `[applied]` theme · target · class · evidence · panel verdicts · provenance. (No per-item commit SHA — the whole run is one commit, identified by the header's `evolve #N` tag + `applied-onto`; see Phase 6 step 7 for why the entry cannot cite the hash of the commit it lives in.)
- **Per rejected item** — `[rejected]` reason + evidence → **skip-list** (declined-stays-declined; re-propose only when new evidence crosses the threshold, with an offset).
- **Regression tally (held-out check)** — count this run's Phase 2 `panel-miss candidate` hits (fresh friction whose target matches a prior-applied item, Phase 0 step 3) against the tracked prior-applied count → a **regression rate**. List each hit as `[panel-miss] target · original evolve#N · this run's evidence`. Report even when the count is **0** — a clean run is itself the signal that recent self-modifications are holding, and silence would be indistinguishable from "not checked."
- **Cost summary ("account for resource efficiency and supervision")** — sub-agents spawned this run (Phase 1 scan count + Phase 4 panel lens count) and the human-decision tally (Phase 5 accept/reject/edit counts). Keeps the pipeline's own overhead visible, not just its output — the "self" in self-improvement is only meaningful if its cost is reported alongside its gains.
- **Per-agent scorecard (360°)** — each active role's ground-truth-anchored score + trend this run (Phase 2.5, held-out per its rule). This is the **time-series** the next run's HR read (Phase 2.5 trend) and **`sprint retro`'s capacity calibration** consume. Keep it compact (role · score · trend · anchor evidence).
- **Rule scorecard** — each stack-specific/boundary rule's firing count · dismissal rate · real-hits vs false-positives · area churn + trend (Phase 2.5, held-out per its rule). The time-series the next run's **rule HR** (demote/retire) reads. Secret/verification gates are not listed (INV2-exempt).
- **Consolidation bridge — move, don't copy (④ → ③/⑥)**: for each **applied** item, the ground-truth entries that were its source (match by evidence identity, best-effort — this identification step is leader judgment: read `ground-truth.jsonl` and pick out which entries' `ts` correspond to each applied item's cited evidence) are now durable in ③/⑥/gates, so **move them out of the active working tier**. ⚠ This is the **one sanctioned exception** to the append-only rule (`_signals.md` "Capture is append-only... at the Section C capture points" — that rule governs the frequent per-stage `capture_signal.py` writes; this is a separate, occasional, evolve-only operation on the same file). Concrete mechanism (its own Bash call, after identifying the `ts` values to move):
  ```bash
  python3 -c "
  import json, sys
  src = '.claude/guild/memory/ground-truth.jsonl'
  dst = '.claude/guild/memory/consolidated.jsonl'
  move_ts = set(sys.argv[1:])
  with open(src, encoding='utf-8') as fh:
      lines = [ln for ln in fh if ln.strip()]
  moved = [ln for ln in lines if json.loads(ln).get('ts') in move_ts]
  kept = [ln for ln in lines if json.loads(ln).get('ts') not in move_ts]
  with open(dst, 'a', encoding='utf-8') as fh:
      fh.writelines(moved)
  with open(src, 'w', encoding='utf-8') as fh:
      fh.writelines(kept)
  " <ts1> <ts2>
  ```
  This keeps the working tier (read at runtime by `_preflight.md` Item 8) a **bounded, un-consolidated tail** and keeps the data-sufficiency count (`_data_sufficiency.md`) meaning "signal *not yet* grown from." **Leave genuinely-pending un-applied entries** in the active tier (still open — a recurrence re-earns them; the ledger skip-list separately prevents re-*proposing* rejected themes). **Only on an apply run** that promoted ≥1 item — a dry-run consolidates nothing. Best-effort: if the evidence match is uncertain, **leave the entry** (erring toward keeping signal over losing it — just omit its `ts` from `move_ts`). Both files are gitignored (`memory/`).
  - **Residual hygiene — also archive resolved-elsewhere residuals (넛지 floor 관리)**: beyond apply-sourced entries, also move out any residual this run **affirmatively classifies as closed via a non-evolve channel** — a human already **codified** it into a standard, a **regression test** now guards it, or a prior run's panel **refuted** its premise (skip-listed). These are durable-or-dead, **not pending**, so leaving them permanently pins the data-sufficiency count at `sufficient` and keeps review's evolve-nudge armed (`review.md` cooldown floor). Move each to `consolidated.jsonl` with a `resolution:` note (why it's closed) + `consolidated_by`, then drop from `ground-truth.jsonl` — same mechanism as the Bash snippet above, but since these entries need the two extra fields added (not just moved as-is), enrich the JSON object with `resolution`/`consolidated_by` before appending (adapt the snippet: build `moved` as enriched dicts — `{**json.loads(ln), "resolution": "...", "consolidated_by": "evolve #<n>"}` — and `json.dumps()` each before writing, rather than writing the raw line). ⚠ **Archive only on an affirmative resolved judgment** (you can name the channel that closed it) — a genuinely-pending signal (no rule made, not refuted, could still recur productively, e.g. a repeated habit-transfer miss) **stays**. Archiving never loses a live signal: a recurrence re-captures a fresh entry regardless (`capture_signal.py`). This is the mechanism that keeps the working tier reflecting *live* signal rather than an ever-growing pile of already-handled corrections.

**Report to the human** — plain language (per the top-of-file rule), not the raw ledger schema: how many changes were made and applied, how many were rolled back and why (in a plain sentence per item, not a code), how many were declined, that the log was updated **in that same commit**, the commit to look at (read it once after committing — `git rev-parse HEAD`, its own Bash call), and the one-line undo instruction (`/gld rollback <sha>`). The `.claude/guild/evolution-log.md` entry itself (Phase 7 above) can stay in the structured/technical format — it's an internal record, not the chat reply.

---

## Hard rules (INV alignment)
- **INV1 — application is always per-item human-approved** (Phase 5). Dry-run never writes to the codebase/agents/knowledge/gates; apply never proceeds without an accept; unattended never auto-applies harness changes. **One narrow, explicit exception**: Phase 2's flow-friction bullet appends to `.claude/guild/overlay/contribute-candidates.md` even under `--dry-run` — a passive advisory note for a *later, separate* `/gld contribute` run, not an applied harness change, same category as `_signals.md`'s append-only capture.
- **INV2 — never weakens verification.** A test/gate/verify-weakening change is inadmissible at Phase 4 (degradation-lens absolute veto) and hard-blocked + rolled back at Phase 6. No override.
- **INV3 — every applied run is reversible** — clean-tree baseline **re-verified at Phase 6 Step 0 on every path that reaches apply** (not merely at Phase 0, which the default "propose, then ask" path never runs), one commit per run **carrying the ledger entry with it**, auto-rollback on validation failure, `/gld rollback` undoes it. A dirty tree stops the apply; it is never auto-stashed.
- **HR retirement is a reversible archive, never a delete** — a retired role's agent file moves to `.claude/guild/archive/agents/` (committed, restorable); ⑥ knowledge is org-shared and is preserved across retirement (only the role's ③ habit + ④ episodes leave). `leader` is never HR-touched.
- **Adversarial panel before apply** — a change that doesn't survive isolated refutation is dropped (no rubber-stamping self-modifications).
- **Panel calibration is additive-only** (Phase 4) — past panel misses may only add caveats that make a lens *more* skeptical; they never loosen a verdict criterion, skip a lens, or override an independent judgment. The critic evolves under the same review process as everything else, never unilaterally.
- **Every apply is regression-tracked, not just apply-time-validated** (Phase 2 surprise source 3 · Phase 7 regression tally) — Phase 6's validation confirms a change looked safe *at the moment it was applied*; the regression tally is the separate, later check for whether it actually held up. A 0-hit tally is reported, not omitted.
- **Anchor everything to ground truth** (`_signals.md` Section B): AI self-review ≠ signal; a reasonless rejection weights low.
- **INV2 rule-HR exemption**: rule demotion/retirement applies **only** to stack-specific/boundary rules. The **secret** and **verification-weakening** gates are universal and are **never** demoted/disabled/retired by evolve, whatever their firing stats — a lifecycle that could weaken core verification is inadmissible.
- **Durable-first, degrade gracefully**: a missing ground-truth log / unreadable transcript never blocks evolve — it proceeds on git/CI/corrections.
- **Read-only scans, bounded output**: scans return compact JSON; synthesis keeps leader context thin (no transcript/diff dumps).

---

## Design note — biological enhancements (A–D): embodied where earned, deferred where not

The bio-inspired ideas below are adopted **only when they beat the simple baseline** (bio-mimicry-trap guard). Status:
- **A. Surprise-weighted consolidation** — **embodied**: Phase 2 ranks `frequency × impact × surprise`; the `surprise` flag drives it. Reinforced toward the human by the ③ engine's predict-before-reveal (`_learning.md` D).
- **B. Interleaved replay (CLS — avoid catastrophic forgetting)** — **embodied** in ⑥ densify with an **explicit guard** (`_knowledge.md` invariant 3): a fact is dropped only when genuinely code-stale, never merely because a new fact differs; conflicts are resolved by re-verifying both against current code; the ledger is the forgetting-prevention record.
- **C. Skill automation (habit → gate)** — **embodied** with an **explicit N≥3 consecutive-cycle threshold** (Phase 2 promote): a habit that holds ground-truth-successful across N cycles compiles into a deterministic gate rule (via the fail-to-rule path).
- **D. Variation–selection–inheritance** — **selection** is embodied (Phase 4 adversarial panel + HR replace/retire pick winners on ground truth). **Population variation** (Phase 3 "Population-based candidate generation") is now **embodied, trigger-gated** — it activates automatically only when ≥3 Tier-A ③-habit patches land in the same run *and* Axis 2 reads `trend` (the scale proxy the guard originally called for), never via a manual flag. Below threshold it stays dormant and the single-attempt path remains the default — the bio-mimicry-trap guard (adopt only when it beats the baseline) is enforced by Phase 7's self-validating record (which candidate won, whether population-mode items later hold up on the held-out check) rather than by asserting the win up front.

