# AUDIT (read-only diagnosis + routing)

**Diagnose both co-evolution targets and route to treatment (plan §9).** `audit` is the **read-only health check** — input is the *current state* (not usage traces; that is `evolve`). It scores the **harness + team** (the developer) and the **codebase** (the product), then nudges the right treatment:
```
audit ──┬─ developer (team · harness) weak → evolve 권장 (nudge, not auto-run)
        └─ codebase weak → refactor Issue 권고 (create only after human confirm)
```

`$1` (optional): a focus dimension (`harness|team|knowledge|standards|codebase`) to scope the pass; empty = full audit. (`--apply` for lifecycle prune/pin is v2 — this command is read-only.)

> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`). Codebase discovery via Grep/Glob/Read. Handoff/RESULT + owner/repo: `<<SKILL_DIR>>/commands/atoms/_handoff.md`.
> **Output language**: the report, grades, findings, and nudges in `config.language` (`_handoff.md` Section K). Grades/severity keywords (`S`/`A`/`BLOCKER`…), IDs, paths, and code stay ASCII.

---

## Phase 0 — Preflight
As the leader (`_preflight.md` Item 1 — read `config.json` incl. `language`), confirm Guild is initialized (`ls .claude/guild/config.json`; absent → "run `/gld init` first", stop). Resolve `<owner>/<repo>` once (`_handoff.md` Section F). Load `docs/standards/` for the authority baseline. **This whole command is read-only** — no Edit/Write (except the report artifact), no issue creation without confirmation, no git mutations.

**Data-sufficiency banner** (`<<SKILL_DIR>>/commands/atoms/_data_sufficiency.md`): compute the **cheap proxy** (Section B — `ground-truth.jsonl` line count + ledger run count; folds in the reverts/CI-gaps read in dimensions E/F) and print the banner (Section D) at the **top of the report**. ⚠ **audit never blocks on it** — a low tier is surfaced as a finding (*"evolve는 아직 이릅니다 — 신호 N개·run M회"*) but the full diagnosis continues; audit is precisely how the human learns they are thin and what to do next.

## Phase 1 — Diagnose (read-only; reuse atoms, fan out where independent)
Assess each dimension. Emit findings with **severity** (`BLOCKER|MAJOR|MINOR`, same rubric as `audit_readiness.md`) and a per-dimension **grade** (`S`/`A`/`B`/`C`/`D`/`F`). Dimensions A–E = the **developer** (team+harness); F = the **product** (codebase).

**A. 하네스 준비도 (harness)** — run the shared diagnostic: read `<<SKILL_DIR>>/commands/atoms/audit_readiness.md` and execute it (verify signal · static gates · CI · GitHub workflow · hygiene). Fold its findings JSON in as dimension A.

**B. 팀 (③ agents)** — read `.claude/agents/*.md`. Are the spine roles present and **specialized to this repo** (the `[PROJECT SPECIALIZATION]` / 프로젝트 특화 section filled with real stack/convention/hotspot facts, not placeholders)? A role still at day-1 boilerplate → MINOR (evolve should grow it). Missing a spine role → MAJOR. *(Per-agent scorecard trend is v2/360 — not scored here.)*

**C. 지식 (⑥ knowledge)** — read `.claude/guild/knowledge/index.md` (+ sample `facts/`). Seeded (not a blank header)? Index **finite** (a screenful, not sprawling)? Facts **evidence-anchored** + not obviously stale vs current code? Blank/absent → MAJOR ("런타임 검색이 빈손"); sprawling index → MINOR (should split by module, `_knowledge.md` invariant 2).

**D. Standards (② docs/standards — lifecycle, 항목 2)** — count `status: draft` vs `confirmed` in `docs/standards/*`. Many unconfirmed → MINOR ("게이트가 warn에 머묾 — 확정하면 block 승격"); note these are **`/gld evolve` confirmation candidates** (evolve derives draft→confirmed from held-without-correction — 항목 2b — not a manual flip). Missing a core standard (charter/architecture/conventions/quality-bar/verification) → MAJOR. **architecture.md staleness (drift — 항목 2a)**: compare `architecture.md`'s described skeleton against the **actual top-level structure** (a bounded Glob/ls of the repo's module dirs) — mentions modules no longer present, or misses a major new one → MINOR ("architecture.md 낡았을 수 있음"). Also surface any open `<!-- guild:arch-drift -->` flags left by unattended execute runs (a confirmed architecture.md pending a skeleton update).

**E. 진화 위생 (⑤ evolution hygiene)** — is `.claude/guild/evolution-log.md` present and used (any runs recorded)? The run count here is the Phase 0 banner's **Axis 2** (trend depth — `_data_sufficiency.md`). **Friction trend**: if the ledger has per-run friction snapshots, judge improving / flat / worsening (plan §8 — "공진화가 돕나" meta-signal). Empty ledger is normal early (MINOR note — the banner already flags 추세없음); a **worsening** trend → surface prominently (→ the evolve→audit reverse nudge fired for a reason).

**F. 코드베이스 품질 (codebase)** — the product side. Reuse `<<SKILL_DIR>>/commands/atoms/scan_git.md` signals (hotspots · co-change · churn) as the spine, plus a **bounded** structural read:
- **hotspots** — top `fix:`-frequency files (fragility). High + rising → MAJOR refactor candidate.
- **coupling** — strong co-change groups (hidden coupling). 
- **complexity/smells** — a bounded sample of the hotspot files (Read the top ~3): oversized files/functions, duplication, missing seams. Do NOT deep-scan the whole repo (budget).
- **coverage** — from dimension A (test presence) + any coverage tooling.
Grade the codebase and list the top refactor candidates with evidence (file · why · `fix:` freq).

## Phase 2 — Score, trend, lifecycle
- **Overall grades**: a per-dimension grade table (A–F dimensions) + a one-line overall read. Anchor severity to charter priorities when known.
- **Lifecycle (read-only recommend)**: flag **stale** roles (never convened / superseded) or **stale knowledge** (facts contradicted by current code) as prune candidates, and high-value items to **pin**. Recommendation only — application is `audit --apply` (v2). State the Active→Stale→Archived reasoning.
- **Depth honesty**: v1 audit = **rule-check + shallow model-check**. Deep per-role adversarial review (architect/tester/security judging their dimension as external auditors) is a v2 depth increment — say so; do not imply a deep audit was done.

## Phase 3 — Report + route (nudges only)
Post/print the audit report (grades + findings by dimension, most-severe first). Then route — **nudges, never auto-run** (plan §9):
- **Developer weakness** (dimensions A–E: harness/team/knowledge/standards/hygiene) → *"`/gld evolve` 권장 — 사용 흔적에서 이 약점들의 치료 제안을 뽑습니다."* (evolve is runnable now.)
- **Codebase weakness** (dimension F) → recommend a **refactor Issue** per top candidate. **Do NOT create it unattended** — list the candidates and, only if the human confirms, create a `type:refactor` Issue (temp-file `gh issue create`). Default = recommend, not create.
- **evolve↔audit mutual nudge**: if the friction trend (E) is worsening or a finding reads like a diagnostic gap rather than a single fix, that is the signal audit exists for; conversely evolve nudges *here* when local treatment isn't helping (plan §9).
- Optionally write the full report to the session scratchpad for the human to work from — **scratchpad only, never the repo** (read-only).

## Hard rules
- **Read-only.** No Edit/Write to tracked files, no git mutations, no issue/label creation **without explicit human confirmation** (the one exception, and only for recommended refactor Issues). The report is the only sanctioned output (comment/scratchpad).
- **Honest depth** — rule + shallow model only (v1); never claim a deep audit. Bounded exploration (reuse atom budgets; ≤ ~3 hotspot Reads for dimension F).
- **Never print secret values** — file/line/identifier only (dimension A hygiene defers to `audit_readiness.md`).
- **Nudge, don't run** — audit diagnoses; evolve/refactor treat. Return a clear routing summary.
