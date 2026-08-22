# MONITORING (on-demand — terminal status snapshot)

**A near-real-time snapshot of the Guild's state, rendered from git-local files (read-only).** Shows the organization, knowledge/memory status, evolution history, gates, friction trend, and active work. **Terminal output** — the HTML artifact is v2. Honest framing: this is a **snapshot at read time**, not a live dashboard.

`$1` (optional) = a focus section (`org|knowledge|gates|work|evolution|standards`) · `--html` = also write a self-contained HTML dashboard · empty = full terminal snapshot.

> **Bash**: `_bash_rules.md`. Handoff + owner/repo: `_handoff.md`.
> **Output language**: render labels/prose in `config.language` (`_handoff.md` Section K); counts/paths/IDs stay ASCII.

---

## Process (read-only — gather git-local state, then render)
**0. Preflight** — read `config.json` (language, roles). Resolve `<owner>/<repo>`.

**1. Gather** — **scope to `$1` when given** (`org`→조직, `knowledge`→지식⑥/기억④, `gates`→게이트, `work`→활성작업, `evolution`→진화이력⑤, `standards`→표준②). When scoped, gather and render only that one section (skip the rest — cheaper, and head the output "포커스: <section>" so it's clearly partial). Unrecognized `$1` → report the valid options and fall back to the full snapshot. Empty/absent `$1` → gather all sections below (each its own read; a missing source → "없음", not an error):
- **조직 (roster, ③)** — `config.roles` + `.claude/agents/*.md`: which roles are installed; note any still at day-1 boilerplate — check for a localized unknown-placeholder note (e.g. `(미정 — 추후 확정)` / `(TBD)`) still present in the "프로젝트 특화" section, **not** a raw `{{TOKEN}}` — `init.md`'s Output Convention 2 guarantees every `{{TOKEN}}` is resolved (to real content or exactly this localized note) before a file is ever written, so a raw token never survives to check for. Also never the literal string `[PROJECT SPECIALIZATION]`, which no template ever contains (the section heading is always the localized `## 프로젝트 특화`, per `init.md`'s Output Convention 4 — a bracketed English tag like that is exactly what init.md forbids ever appearing).
- **지식 ⑥ / 기억 ④** — `knowledge/index.md` seeded-slice count; `memory/ground-truth.jsonl` entry count (④ — present only if capture has fired).
- **진화 이력 ⑤** — `evolution-log.md`: run count · last run · friction trend if snapshots recorded (개선/평탄/악화).
- **게이트** — `gates/findings.json` open-violation count · `config.gates.enabled` · `gates/dismissed.md` accepted-risk count.
- **표준 ②** — `docs/standards/*`: `draft` vs `confirmed` count.
- **활성 작업** — `gh issue list --state open --json labels` bucketed by **stage** label (analyze/design/execute/test/qa/children — mutually exclusive, one per Issue) + `guild:done` recent. ⚠ The stage-derivation must exclude `guild:child` from this bucketing the same way `status.md`'s split-parent discovery query does (`_handoff.md` Section I): every child Issue carries `guild:child` **alongside** its real stage label, so deriving "the stage" from the raw label array without filtering it out first either drops the child from every bucket (a 2-element array/comma-joined string matches none of the named buckets) or double-counts it. **`guild:needs-human` is a separate cross-cutting count, not a same-level bucket** — it's additive (`_handoff.md` Section A: a paused Issue keeps its stage label and gains this one on top), so summing it alongside the stage buckets double-counts a paused Issue in both its stage bucket and the needs-human bucket; render it instead as its own highlighted line ("N개 이슈 사람 대기 중"), consistent with this file's own Hard rule below ("surface ... `guild:needs-human` Issues ... before the static counts").

**2. Render** a compact terminal snapshot — sections with counts + one-line status each, most-actionable first (open gate violations, `needs-human` pauses, worsening friction trend). End with the snapshot timestamp note.

**2b. `--html` (optional)** — additionally render the same gathered data as a **self-contained HTML dashboard** (inline CSS, **no external assets** — offline/CSP-safe): an org table, status cards (⑥/④ · gates · standards), the evolution/friction trend, and an active-work board by `guild:*` label. Write it to `.claude/guild/memory/monitoring.html` — **not** `.claude/guild/monitoring.html` directly (only the `memory/` subpath is actually covered by `.claude/guild/.gitignore`, per `init.md`; SKILL.md's own commit policy is "commit everything under `.claude/guild/` except `memory/`", so a file written outside `memory/` would be tracked, contradicting the "not committed" intent here) — and report the path for the human to open. Same data as the terminal snapshot, richer layout.

**3. Read-only against the repo** — reads git-local + `gh`; the only write is the optional `--html` artifact (a rendered snapshot, not repo state).

## Hard rules
- **Read-only snapshot** — reads git-local + `gh`; renders (terminal, + optional `--html` artifact); never writes repo state.
- **Deferred option — live observability (Langfuse etc.)**: this command is a **snapshot at read time**, not a live dashboard. A streaming/live backend (per-call token·latency·eval tracing) is adopted **only when** that granularity is actually needed (a scale/debugging trigger), as an optional observability layer over the same git-local data — not a data-ownership change. Until then the snapshot is the correct baseline. Not a gap; a watched trigger.
- **Honest** — a snapshot at read time, not real-time; a missing/empty source is normal early (render "없음").
- **Actionable-first** — surface open gate findings, `guild:needs-human` Issues, and worsening friction before the static counts.
