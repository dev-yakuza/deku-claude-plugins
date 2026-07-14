# ASK (on-demand — cited Q&A over Guild knowledge)

**Answer a question from the repo's durable knowledge, with source citations.** Draws on `docs/standards/` (② curated authority), the ⑥ knowledge base, `CLAUDE.md`, and (when relevant) the evolution history — and **cites every claim**. Read-only. **Does not guess**: if the answer isn't in the sources, it says so.

`$1…` = the question (natural language).

> **Bash**: `_bash_rules.md`. Handoff: `_handoff.md`. ⑥ retrieval contract: `_knowledge.md`.
> **Output language**: answer in `config.language` (`_handoff.md` Section K); code/paths/identifiers stay verbatim.

---

## Process
**0. Preflight** — read `.claude/guild/config.json` (language). Confirm Guild initialized (absent → "run `/gld init`").

**1. Retrieve (deterministic, relevant-only — `_knowledge.md` Section C — never whole-load)**
- **② Curated authority**: read the `docs/standards/` file(s) whose topic matches the question (charter / architecture / conventions / quality-bar / verification) + `CLAUDE.md`.
- **⑥ Knowledge**: read `.claude/guild/knowledge/index.md`, match the question's topic / file paths / symbols against the index keys, and read only the matched `facts/<area>.md` slice(s).
- **⑤ History (only if the question is about the team/process)**: `evolution-log.md` (past changes) or `ground-truth.jsonl` (recent corrections).
- **Code (only if needed to confirm a fact)**: a bounded Grep/Read to verify a ⑥ fact against current code.

**2. Answer**
- Synthesize from the retrieved sources. **Cite every claim** inline with its source — `docs/standards/architecture.md`, a ⑥ fact heading + file, `CLAUDE.md`, a commit/ledger entry.
- **Flag confidence by source tier**: a `status: confirmed` standard = authoritative; a ⑥ fact = **advisory** (note "현재 코드로 검증 권장"); a `draft` standard = tentative; a ledger entry = historical.
- **If the sources don't cover it → say "지식 베이스/표준에 근거 없음"**, suggest where it would live (a standard to confirm, a fact `evolve` could capture), and stop. **Never fabricate.**

**3. Read-only** — answering only; never edits any file.

## Hard rules
- **Cite or abstain** — every claim traces to a source (②/⑥/CLAUDE/⑤); no uncited assertions; absent from sources → say so.
- **Retrieve, don't whole-load** (⑥ invariant 1) — index + matched slices only.
- **Confidence-tiered** — confirmed standard > draft > ⑥ advisory fact; surface the tier so the human weights it right.
- **Read-only.**
