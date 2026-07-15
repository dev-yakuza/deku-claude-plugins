# MONITORING (on-demand — terminal status snapshot)

**A near-real-time snapshot of the Guild's state, rendered from git-local files (read-only).** Shows the organization, knowledge/memory status, evolution history, gates, friction trend, and active work. **Terminal output** — the HTML artifact is v2 (plan §3). Honest framing: this is a **snapshot at read time**, not a live dashboard.

`$1` (optional) = a focus section (`org|knowledge|gates|work|evolution`) · `--html` = also write a self-contained HTML dashboard · empty = full terminal snapshot.

> **Bash**: `_bash_rules.md`. Handoff + owner/repo: `_handoff.md`.
> **Output language**: render labels/prose in `config.language` (`_handoff.md` Section K); counts/paths/IDs stay ASCII.

---

## Process (read-only — gather git-local state, then render)
**0. Preflight** — read `config.json` (language, roles). Resolve `<owner>/<repo>`.

**1. Gather** (each its own read; a missing source → "없음", not an error):
- **조직 (roster, ③)** — `config.roles` + `.claude/agents/*.md`: which roles are installed; note any still at day-1 boilerplate (`[PROJECT SPECIALIZATION]` unfilled).
- **지식 ⑥ / 기억 ④** — `knowledge/index.md` seeded-slice count; `memory/ground-truth.jsonl` entry count (④ — present only if capture has fired).
- **진화 이력 ⑤** — `evolution-log.md`: run count · last run · friction trend if snapshots recorded (개선/평탄/악화).
- **게이트** — `gates/findings.json` open-violation count · `config.gates.enabled` · `gates/dismissed.md` accepted-risk count.
- **표준 ②** — `docs/standards/*`: `draft` vs `confirmed` count.
- **활성 작업** — `gh issue list --state open --json labels` bucketed by `guild:*` label (analyze/design/execute/test/qa/children/needs-human counts) + `guild:done` recent.

**2. Render** a compact terminal snapshot — sections with counts + one-line status each, most-actionable first (open gate violations, `needs-human` pauses, worsening friction trend). End with the snapshot timestamp note.

**2b. `--html` (optional)** — additionally render the same gathered data as a **self-contained HTML dashboard** (inline CSS, **no external assets** — offline/CSP-safe): an org table, status cards (⑥/④ · gates · standards), the evolution/friction trend, and an active-work board by `guild:*` label. Write it to `.claude/guild/monitoring.html` (a snapshot artifact — gitignored or scratch, **not committed**) and report the path for the human to open. Same data as the terminal snapshot, richer layout.

**3. Read-only against the repo** — reads git-local + `gh`; the only write is the optional `--html` artifact (a rendered snapshot, not repo state).

## Hard rules
- **Read-only snapshot** — reads git-local + `gh`; renders (terminal, + optional `--html` artifact); never writes repo state.
- **Deferred option — live observability (Langfuse etc.)**: this command is a **snapshot at read time**, not a live dashboard. A streaming/live backend (per-call token·latency·eval tracing) is adopted **only when** that granularity is actually needed (a scale/debugging trigger), as an optional observability layer over the same git-local data — not a data-ownership change. Until then the snapshot is the correct baseline. Not a gap; a watched trigger.
- **Honest** — a snapshot at read time, not real-time; a missing/empty source is normal early (render "없음").
- **Actionable-first** — surface open gate findings, `guild:needs-human` Issues, and worsening friction before the static counts.
