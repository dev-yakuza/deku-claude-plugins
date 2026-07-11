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
- **AI self-review is NOT ground truth.** Kill-gate finding C7: the word_app PR "reviews" (#869–874) were all AI-authored self-reviews (`viewerDidAuthor=true`, `<!-- sdd:review -->` markers). A correction signal must come from a **human** overturning/rejecting — not from an agent critiquing its own output. When reading PR-review corrections, **exclude self-authored reviews** (author = acting agent identity, or `viewerDidAuthor`).
- **"귀찮아서 기각" ≠ "틀려서 기각".** A rejection is a strong signal only with a stated reason, or a subsequent real defect in that area (plan 부록 B rule-loop anchor). Record the reason when known; absent a reason, weight low.

## Section C — Capture points (ephemeral → ground-truth log)

Ephemeral signals are appended to the ground-truth log **at the moment they occur**, by the spine step that observes them. **These are the only sanctioned writes in the growth-loop foundation.** Each is a single append — no read-back, no heavy logic (keep the spine fast).

| Event | Observed at | Entry kind |
|---|---|---|
| Human rejects/overrides a discuss-gate option | discuss gate (analyze/design) — main session, after `NEEDS_HUMAN` → `AskUserQuestion` | `correction` — options offered · human's choice · reason (if given) |
| verify self-report ↔ raw-runner gap | verify gate (`_handoff.md` Section E) | `verify-gap` — claimed vs raw · `surprise` (plan §8-A) |
| Unattended auto-decision overturned by human at PR review | *(deferred — needs PR-review read-back)* | `correction` (unattended) |
| git revert of a Guild-authored commit | on-demand via scan_git — **not** captured | — (durable) |

**Append mechanism** = `capture_signal.py`, run as ONE bash call (atomic-bash forbids `>>` — same bundled-command exception as the parser):
```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction|verify-gap|revert \
  --issue <n> --stage <stage> --role <role> --summary "<=1 line" --evidence "<=1 line" [--surprise]
```
It appends one line to `.claude/guild/memory/ground-truth.jsonl` (Section D), creating the dir if missing, and never crashes the caller (a logging failure warns and exits non-zero without blocking the spine).

**Wired (increment 2):** `analyze.md`/`design.md` discuss gates append a `correction` **only when the human overrides** the agent's recommendation (agreement is not a correction; anchor per Section B); `test.md` verify gate appends a `verify-gap` **only when the tester's claim disagreed with raw output or verify failed** (green-with-no-gap = nothing to learn). Section E of `_handoff.md` already **computes** the verify gap — this only *logs* it, the minimal extension the plan calls for ("verify 게이트의 원문-증거 패턴을 교정·revert 로깅으로 확장"). Unattended auto-assumptions are **not** captured (deferred — the third row above needs PR-review read-back).

## Section D — Ground-truth log (format & location)

- **Location**: `.claude/guild/memory/ground-truth.jsonl` — episodic tier (plan §5 ④), **gitignored** (init already gitignores `memory/`). Append-only; one JSON object per line (machine-parseable; human-scannable with `tail`).
- **Commit vs gitignore is still open** (plan 부록 B ⓐ — team-share benefit vs leak/noise risk). ① keeps it gitignored (matches init default = lowest risk); revisit when the working-tier read is built.
- **Entry schema** (one line each):
  ```json
  {"ts":"<iso8601>","kind":"correction|verify-gap|revert","issue":<n|null>,"stage":"<stage>","role":"<role|null>","summary":"<=1 line","evidence":"<=1 line, concrete","surprise":true|false}
  ```
  - `surprise:true` when the human overturned a choice the agent was confident in, **or** a claimed-pass was actually red (plan §8-A — this is the ranking lever the kill-gate validated: A1 "guard existed yet bug escaped", A3 "confident work reversed" ranked top).
  - `evidence` names the concrete artifact (commit / comment / runner line); never paste bulk.
- **Read** on-demand by evolve/audit alongside the durable signals. It is the **only** persisted trace — everything else is re-derived. Treated as **advisory, low-weight** until evolve promotes an item with corroborating ground truth (plan §5 2-tier safety; a wrong entry perturbs at most the next single run, never the authority store).

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
python3 <<SKILL_DIR>>/commands/atoms/scan_transcript.py --repo-cwd <abs-repo-path> --since-days <N>
```
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
