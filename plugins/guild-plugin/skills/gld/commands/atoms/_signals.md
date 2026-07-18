# SIGNALS: capture & ground-truth (shared contract)

**Not a stage.** Foundation for the growth loop (plan §8 evolve · 부록 B "성장 엔진 ① 토대"). Defines (1) the signal taxonomy evolve/audit read from, (2) which signals are read **on-demand** vs **captured at occurrence**, (3) the ground-truth log format + location, (4) graceful degradation + the ground-truth **anchor** rule. Read by the future `/gld evolve`·`/gld audit` and by the gate-capture points wired into the spine. **① 토대 = 흔적·ground-truth 포착** — validated by the M2 kill-gate on real word_app data (2026-07-11, PASS).

> **Bash**: simple calls only (`_bash_rules.md`) — **except** the bundled transcript parser (`scan_transcript.py`), which runs as ONE `python3` command (its jq-like parsing would otherwise violate atomic-bash — plan §8 정정). Read-only everywhere it reads; the only sanctioned writes are append-to-ground-truth-log at the Section C capture points.

---

## Section A — Signal taxonomy (what the growth loop reads)

Four signal classes (plan §8 P1 scan atoms). Each has a SOURCE and a DURABILITY, and durability decides **how** it is obtained:

| Class | Source | Durability | How obtained |
|---|---|---|---|
| scan_git | `git log` — co-change, hotspots, conventions, reverts | **durable** (re-derivable any time) | on-demand read at evolve time |
| scan_failures | CI (`gh run`), gate findings (`readiness-report.md`), test/lint output | **durable** | on-demand read |
| scan_corrections | git revert · PR reject/close · **in-session human correction** · **verify self-report↔runner gap** | **mixed** — git/PR durable; in-session **ephemeral** | durable part on-demand; ephemeral part **captured at occurrence** |
| scan_transcript | CC transcript `~/.claude/projects/<enc-cwd>/*.jsonl` — repeated permission, tool errors, rediscovery, repeated cmd | **fragile** (undocumented format, lossy cwd encoding) | **best-effort** via bundled parser; degrade to durable on failure |

**Design rule — hybrid capture (the ① decision · plan 부록 B · kill-gate PASS):**
- **Durable → read on-demand.** git/CI/gate/gh are already persisted and re-derivable; evolve reads them live when it runs. No capture infra, no drift.
- **Ephemeral → capture at occurrence.** In-session human corrections and verify-gaps vanish when the session ends (they live only in fragile transcripts). Capture them deterministically to the ground-truth log the moment they happen (Section C). Rationale from the kill-gate: the strong correction signals that survived (design superseded, #893=#891 duplicate) survived *because* they left a durable git/PR trace — the finer in-session corrections have no such trace. The kill-gate could not even locate the #891/#893 dev-run transcripts by cwd encoding → ephemeral signals must be **captured, not mined**.
- **Fragile → best-effort, degrade.** Transcript friction (permission / tool-error / rediscovery / repeated-cmd) is genuinely valuable — the kill-gate's top two signals came from here (A6 `fvm flutter` vs the `flutter` mis-registered in `config.json`; A7 the `dev-yakuza` gh-account access set). But the source is unstable; read via the bundled parser (Section F) and, on **any** failure, degrade silently to the durable backbone (which stands alone).

## Section B — Ground-truth anchor (⚠ hard rule — back-patting prevention)

Every signal that will drive a change MUST be anchored to **real ground truth**: an objective outcome (test / gate / CI result) or a **real human action** (correction, revert, PR reject). (plan §8 back-patting 방지.)
- **AI self-review is NOT ground truth.** Kill-gate finding C7: the word_app PR "reviews" (#869–874) were all AI-authored self-reviews (`viewerDidAuthor=true`, `<!-- sdd:review -->` markers). A correction signal must not come from an agent critiquing its **own** output. When reading PR-review corrections, **exclude self-authored reviews** (author = acting agent identity, or `viewerDidAuthor`).
- **Cross-role reversal ≠ self-review (the agent↔agent capture — plan §16 C1 insider/outsider · 부록 D P0).** A *different* role overturning another role's confident output — a **design-stage specialist `BLOCKED`** reversing a decided approach (designer WCAG, dba integrity, security threat), tech-lead/gate `BLOCKED` on the developer's diff, or QA/designer finding a defect the test stage passed — **is** legitimate ground truth **when anchored to an objective outcome** (a measured ratio, a concrete non-conformance, a real security/a11y defect, or raw runner output contradicting a claimed green). That anchor is what separates it from self-review; external cross-role review is exactly what §16 C1 relies on. Weight it **below** a real human correction, above an unanchored opinion. This is where the "몸통" of the correction distribution lives (the human-override capture only sees the "꼬리" — plan 부록 D P0).
- **"귀찮아서 기각" ≠ "틀려서 기각".** A rejection is a strong signal only with a stated reason, or a subsequent real defect in that area (plan 부록 B rule-loop anchor). Record the reason when known; absent a reason, weight low.

## Section C — Capture points (ephemeral → ground-truth log)

Ephemeral signals are appended to the ground-truth log **at the moment they occur**, by the spine step that observes them. **These are the only sanctioned writes in the growth-loop foundation.** Each is a single append — no read-back, no heavy logic (keep the spine fast).

| Event | Observed at | Entry kind |
|---|---|---|
| Human rejects/overrides a discuss-gate option | discuss gate (analyze/design) — main session, after `NEEDS_HUMAN` → `AskUserQuestion` | `correction` — options offered · human's choice · reason (if given) |
| verify self-report ↔ raw-runner gap | verify gate (`_handoff.md` Section E) | `verify-gap` — claimed vs raw · `surprise` (plan §8-A) |
| Design-stage specialist `BLOCKED` reverses a decided approach (designer WCAG, dba integrity, security threat) | design Step 2 (`design.md`) | `correction` agent↔agent (role = specialist) · `surprise` |
| Role overturns another role's output at execute (tech-lead/gate `BLOCKED`, or dev claimed-green contradicted by raw) | implement Step 4 loop-back (`implement.md`) | `correction` agent↔agent (role = overturner) · `surprise` — or `verify-gap`/dev for claimed-green↔raw |
| QA/designer finds a blocking defect the test stage passed | qa Step 2 defect / UI-UX gate `BLOCKED` (`qa.md`) | `correction` agent↔agent (role = qa\|designer) · `surprise` |
| A role **measured a real defect the human knowingly ACCEPTED** (kept the risky choice / locked it at discuss) | discuss-lock or gate-dismiss (analyze/design/qa) — human chooses the flagged-risky option | recorded in **`gates/dismissed.md`** (the accepted-risk registry, human-edited), **not** auto-appended to the jsonl — evolve reads it from there. *(`--kind accepted-risk` exists in `capture_signal.py` for future auto-capture but is not wired at the spine.)* |
| A loop-back's blocking reason **repeats identically** on the next attempt (stalled retry) | stagnation guard (`_stagnation.md` Section B) — `implement.md`/`debug.md`/`refactor.md` Step 4, `test.md`/`qa.md` Step 3 | `stagnation` — the recurring reason · attempt-1↔2 evidence |
| Unattended auto-decision overturned by human at PR review | *(deferred — needs PR-review read-back)* | `correction` (unattended) |
| git revert of a Guild-authored commit | on-demand via scan_git — **not** captured | — (durable) |

**Append mechanism** = `capture_signal.py`, run as ONE bash call (atomic-bash forbids `>>` — same bundled-command exception as the parser):
```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction|verify-gap|revert \
  --issue <n> --stage <stage> --role <role> [--area "<path/keyword>"] --summary "<=1 line" --evidence "<=1 line" [--surprise]
```
It appends one line to `.claude/guild/memory/ground-truth.jsonl` (Section D), creating the dir if missing, and never crashes the caller (a logging failure warns and exits non-zero without blocking the spine).

**`--area` (optional but recommended)** = the path-prefix or short area keyword the signal touches (e.g. `lib/theme`, `auth`, `db/schema`). It is the **retrieval key for runtime working-memory** (`_preflight.md` Item 8 — the ④ episodic tier is read back at pre-flight and matched by area, mirroring ⑥ knowledge retrieval). Each capture point should pass the area it already knows (the Issue's area / target dir / changed file). Absent → the entry still logs; runtime retrieval falls back to role+recency matching.

**Wired (increment 2 — human/verify):** `analyze.md`/`design.md` discuss gates append a `correction` **only when the human overrides** the agent's recommendation (agreement is not a correction; anchor per Section B); `test.md` verify gate appends a `verify-gap` **only when the tester's claim disagreed with raw output or verify failed** (green-with-no-gap = nothing to learn). Section E of `_handoff.md` already **computes** the verify gap — this only *logs* it, the minimal extension the plan calls for ("verify 게이트의 원문-증거 패턴을 교정·revert 로깅으로 확장"). Unattended auto-assumptions are **not** captured (deferred — the last row above needs PR-review read-back).

**Wired (increment 3 — agent↔agent):** `design.md` Step 2 appends a `correction` **when a design-stage specialist `BLOCKED` reverses a decided approach** (designer WCAG / dba integrity / security threat); `implement.md` Step 4 appends a `correction` (or `verify-gap` for the claimed-green↔raw case) **only when a loop-back fires on a real reversal** — a tech-lead/gate `BLOCKED` or raw evidence contradicting a claimed green, never a `DONE_WITH_CONCERNS`; `qa.md` Step 2 appends a `correction` **only when QA or the UI/UX gate finds a blocking defect the test stage passed**. These capture the *body* of the correction distribution (cross-role reversals) that the increment-2 human-override capture cannot see — legitimate because each is anchored to an objective outcome (Section B). Role = the overturner. `--surprise` always (confident work reversed — plan §8-A). *(The design-stage hook was added after #898 live-verification showed the designer catching a WCAG trap at design — a real reversal the execute/qa hooks alone would miss.)*

**Wired (stagnation guard — `_stagnation.md`):** `implement.md`/`debug.md`/`refactor.md` Step 4 and `test.md`/`qa.md` Step 3 compare a loop-back's blocking reason against the immediately-prior attempt's before consuming another retry; an identical-reason repeat appends `--kind stagnation` and escalates immediately rather than exhausting the numeric cap. This is orthogonal to increment 2/3 above — it fires on *recurrence*, not on a single reversal.

## Section D — Ground-truth log (format & location)

- **Location**: `.claude/guild/memory/ground-truth.jsonl` — episodic tier (plan §5 ④), **gitignored** (init already gitignores `memory/`). Append-only; one JSON object per line (machine-parseable; human-scannable with `tail`).
- **Commit vs gitignore is still open** (plan 부록 B ⓐ — team-share benefit vs leak/noise risk). ① keeps it gitignored (matches init default = lowest risk); revisit when the working-tier read is built.
- **Entry schema** (one line each):
  ```json
  {"ts":"<iso8601>","kind":"correction|verify-gap|revert|accepted-risk|stagnation","issue":<n|null>,"stage":"<stage>","role":"<role|null>","area":"<path/keyword|null>","summary":"<=1 line","evidence":"<=1 line, concrete","surprise":true|false}
  ```
  - `area` = the retrieval key for runtime working-memory (항목 1 / `_preflight.md` Item 8). Optional; null when the signal isn't tied to a path (e.g. a scope-interpretation correction).
  - `surprise:true` when the human overturned a choice the agent was confident in, **or** a claimed-pass was actually red (plan §8-A — this is the ranking lever the kill-gate validated: A1 "guard existed yet bug escaped", A3 "confident work reversed" ranked top).
  - `evidence` names the concrete artifact (commit / comment / runner line); never paste bulk.
- **Read** on-demand by evolve/audit alongside the durable signals. It is the **only** persisted trace — everything else is re-derived. Treated as **advisory, low-weight** until evolve promotes an item with corroborating ground truth (plan §5 2-tier safety; a wrong entry perturbs at most the next single run, never the authority store).
- **`accepted-risk` treatment (evolve/audit)**: NOT a correction (no habit change, no `surprise` ranking boost). evolve reads it as **(a)** a ⑥-fact candidate — the *measured* risk is durable knowledge worth recording (e.g. "`#CCCCCC` on dark disabledColor = 1.67:1, WCAG-fail, **accepted trade-off**"); **(b)** a **skip-list** entry — do NOT re-propose fixing it (the human consciously accepted it; re-proposing = noise). **Source of record**: the human-edited **`gates/dismissed.md`** registry (where a role measured a real defect — designer WCAG #898, dba sync #900 — but the human kept the choice). evolve reads accepted risks from there; they are **not** auto-appended to `ground-truth.jsonl` at the spine (the `--kind accepted-risk` path exists for future auto-capture but is unwired).

## Section E — On-demand readers (durable backbone)

The durable backbone needs no new storage — evolve reads it live. Reader-atom contracts (built with `/gld evolve`, ②; listed here so the foundation is complete):
- **scan_git** — `git log` file-pair co-occurrence counts (co-change), churn hotspots, commit-convention coverage, revert/re-fix detection. *(kill-gate: i18n-triad co-change 22×, controller↔test 13/9/6, conventions ~100%.)*
- **scan_failures** — `gh run list` failure patterns + `readiness-report.md` gap findings + test/lint output. *(kill-gate: ci-gated-by-label, committed-secret #890.)*
- **scan_corrections (durable part)** — git reverts + PR reject/close (`gh pr view --json state,mergedAt,baseRefName`) + the ground-truth log (Section D). **Exclude AI self-reviews** (Section B). *(kill-gate: #893=#891 duplicate, PR#892 wrong-base close.)*
- **scan_transcript** — via `scan_transcript.py` (Section F). Best-effort; degrade on failure.

Frequency discipline (all readers, plan §8): repeated ≥K only (drop 1-offs), evidence required (no evidence → not a signal), local & read-only.

## Section F — Bundled transcript parser (`scan_transcript.py`)

Fragile source → one bundled command (not atomic-bash pipes — plan §8 정정). Invoked as a single Bash call:
```bash
python3 <<SKILL_DIR>>/commands/atoms/scan_transcript.py --repo-cwd <abs-repo-path>
```
- **No time-window flag** — frequency = distinct **session count** (≥K), not recency; a `--since-days` filter over the fragile transcript timestamps was error-prone (undated sessions, mixed ISO formats) for no benefit, so staleness is left to the evolve ledger skip-list (plan 부록 D 3중 리뷰 P3).
- **cwd resolution by probing, not string assembly** — the encoded dir name is lossy (`/` and `_` both collapse toward `-`; kill-gate: `/Users/j-kim/projects/word_app` → dir `-Users-j-kim-projects-word-app`). The parser lists `~/.claude/projects/*/` and matches by the **in-record `cwd` field** (records carry the true path even when the dir name is lossy — kill-gate confirmed).
- **Best-effort + graceful degrade** — unparseable lines are skipped; if the dir/format cannot be read at all, exit non-zero with a one-line reason → the caller drops transcript signals and proceeds on the durable backbone.
- **Robustness rules learned in the kill-gate**: dedupe duplicate records; report **session-count** (how many distinct transcripts) as the frequency metric, not raw hit-count; `is_error` is unreliable → regex the tool_result bodies; **discount `Cancelled: parallel tool call` cascades** (one real failure aborts its batch-mates — a symptom, not an independent signal).
- **Output**: `>>> RESULT <<<` + JSON:
  ```json
  { "feasibility": "<=1 line — parse success/limits", "degraded": false,
    "signals": [ { "confidence": "high|med|low", "class": "permission|tool-error|rediscovery|repeated-cmd",
                   "summary": "<=1 line", "evidence": "<=1 line", "sessions": <N>, "mapping": "allow-rule|⑥ fact|③ habit" } ] }
  ```
- **Read-only** — never writes transcripts.

## Hard rules
- **Durable-first**: a transcript failure never blocks the growth loop — degrade to git/CI/gate.
- **Anchor everything** to an objective outcome or a real human action (Section B). Self-review ≠ ground truth.
- **Capture is append-only, minimal, at-occurrence** (Section C) — never a heavy inline scan on the spine.
- The ground-truth log is **advisory / low-weight** until evolve promotes with corroboration (HITL — INV1: application always needs human approval).
- **Nothing here weakens verification** (INV2): the verify gate's behavior (`_handoff.md` Section E) is unchanged; ① only *logs* the gap it already computes.
