# SCAN: corrections (evolve P1 — the strongest signal reader)

**Read-only human-correction reader for `/gld evolve` Phase 1.** One of the four evolve scan atoms (`_signals.md` Section E). Corrections — things a **human** overturned — are the **strongest** evolve signal (plan §8: "사람이 되돌린 것 = 가장 강한 신호"). This atom aggregates them from three sources and **anchors every one to real ground truth** (Section B). Independently spawnable; returns a compact `>>> RESULT <<<` JSON.

> **Bash**: simple calls only (`_bash_rules.md`). Codebase/log reads via Grep/Glob/Read/git. **Read-only**: no Edit/Write, no git mutations.
> Model: **Sonnet** (anchor judgment — a rejection with no reason ≠ a real correction).

---

## Goal — three correction sources

| Source | Durability | What |
|---|---|---|
| **ground-truth log** (`.claude/guild/memory/ground-truth.jsonl`) | ephemeral, **captured at occurrence** (① — `capture_signal.py`) | in-session `correction` / `verify-gap` / `revert` / `stagnation` entries with a `surprise` flag |
| **PR reject / close** (`gh pr list --state closed`) | durable | PRs closed **unmerged** = rejected work; human review corrections |
| **git revert** (`git log --grep=revert`) | durable | a Guild-authored commit that was reverted (overlaps `scan_git` — P2 dedups by SHA) |

Maps to: ③ habit + ⑥ fact (a correction usually teaches both a habit *and* a fact), **+ gate** when the same correction recurs (fail-to-rule).

---

## ⚠ Ground-truth anchor (hard rule — `_signals.md` Section B)

Every correction MUST be anchored to a **real human action or objective outcome**, never to an agent's opinion:

1. **AI self-review is NOT ground truth.** Kill-gate finding C7: word_app PRs #869–874 "reviews" were all AI self-authored (`viewerDidAuthor=true`, `<!-- sdd:review -->` markers). **When reading PR reviews/comments, exclude self-authored ones** (review/comment author == the acting agent identity, or `viewerDidAuthor==true`). A correction must come from a **human** overturning the work.
2. **"귀찮아서 기각" ≠ "틀려서 기각".** A rejection/close is a strong signal only with a **stated reason**, or a **subsequent real defect** in that area. Record the reason when known; absent a reason, mark `anchored: false` and weight it low (do not drop — surface it as a weak candidate).

---

## Procedure (each step its own read-only Bash call / Read)

1. **Ground-truth log** — Read `.claude/guild/memory/ground-truth.jsonl` (Read tool):
   - Present → parse each line (one JSON object: `kind`, `issue`, `stage`, `role`, `summary`, `evidence`, `surprise`, `escalated`). Group by theme; carry the `surprise` flag through (it is the ranking lever — `_signals.md` Section D / plan §8-A) and carry `escalated` through too (feeds evolve's Phase 2.5 model-tier scorecard — `_model_tiering.md` Section C — so it doesn't need a second read of the log).
   - **Weight by anchor source (`role` discriminates — `_signals.md` Section B):** a discuss-override (`role: leader`, a real human overturning the recommendation) is the **strongest**; a `stagnation` entry (the same blocking reason recurring across loop-back attempts — `_stagnation.md`) ranks next, above a single **cross-role reversal** (`role: tech-lead|qa|designer|security|…`, one role overturning another's confident output, anchored to a `BLOCKED`/defect) — the *body* of the distribution, weighing **below** a human correction and **above** an unanchored opinion; a `verify-gap` is anchored to raw runner output. Set `anchored: true` for all four (each carries an objective anchor by construction) but tag the source so P2 can rank human > stagnation > cross-role > verify-gap. This is **not** self-review — the log only ever holds sanctioned captures (`_signals.md` Section C), never an agent grading its own work.
   - **Missing or empty → this is normal, not a failure.** The log is gitignored and only fills once a live `/gld dev` run hits a discuss-override or verify-gap (① dogfooding may not have run yet). Set `gt_log_status: "missing"` / `"empty"` and continue on the durable sources. **Do not block or warn loudly.**
   - The log is **advisory / low-weight** until P2 corroborates it with a durable signal (plan §5 2-tier safety).

2. **PR rejections** — closed-unmerged PRs (durable human correction):
   ```bash
   gh pr list --state closed --limit 40 --json number,title,mergedAt,closedAt,author,baseRefName
   ```
   A PR with `mergedAt == null` but a `closedAt` = **closed without merging** = rejected/abandoned work. For each, try to recover the **reason** (from the PR's closing comment or title). Anchor per the rule above. *(kill-gate: PR #892 closed for wrong base branch — a human correction of the #893=#891 duplicate.)*
   - ⚠ **Exclude bot-authored closes** (`author.is_bot == true`, e.g. `dependabot`, `renovate`): a bot routinely closes-unmerged its own superseded dependency PRs — that is **automated housekeeping, not a human correction** (observed on real data: ~10 dependabot closed-unmerged PRs would otherwise masquerade as rejections = kill-gate Tier C noise). Drop them or mark `anchored: false`.
   - To exclude AI self-review noise on the *reasons*, if you inspect review threads, drop self-authored reviews (see anchor rule). `gh` unavailable → skip, `pr_rejections: []`, note in `degraded`.

3. **Reverts** — Guild/authored commits that were undone:
   ```bash
   git log --grep=revert -i --oneline -80
   ```
   Report short SHA + subject. Overlaps `scan_git.reverts` — that is expected; **P2 dedups by SHA**. A revert is an anchored correction (count=1 is admissible — impact overrides frequency).

---

## Output

Exactly one `>>> RESULT <<<` line + compact JSON.

```
>>> RESULT <<<
```
```json
{ "scan": "corrections", "findings": {
  "ground_truth": [ { "kind": "correction", "issue": 893, "role": "tech-lead", "stage": "execute", "summary": "설계 override: 전역 토큰 → 위젯 레벨", "surprise": true, "escalated": false, "anchored": true } ],
  "pr_rejections": [ { "pr": 892, "reason": "wrong base branch", "anchored": true } ],
  "reverts": [ { "commit": "abc1234", "summary": "Revert \"feat: X\"", "anchored": true } ],
  "gt_log_status": "present",
  "excluded_self_reviews": 6,
  "degraded": false,
  "notes": "ground-truth 로그 캡처됨; #893 override는 surprise (확신 뒤집힘 → 랭킹 상위 후보)." } }
```
- `gt_log_status`: `present` | `empty` | `missing` — tells P2 whether ephemeral capture is live.
- `excluded_self_reviews`: how many self-authored reviews were dropped (anchor transparency; kill-gate C7).
- `degraded`: true if a durable source (gh) was unreadable.

## Hard rules
- **Anchor everything** to a real human action or objective outcome. **AI self-review ≠ ground truth** — exclude self-authored reviews.
- **A missing ground-truth log is normal** — degrade silently to the durable sources; never block.
- **Read-only.** No Edit/Write, no git mutations. Never paste bulk log/diff into RESULT — name the evidence artifact.
- Return exactly one `>>> RESULT <<<` line + JSON.
