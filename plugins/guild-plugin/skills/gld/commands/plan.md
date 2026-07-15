# PLAN (intake — decompose a design doc / epic issue into a dev-unit backlog)

**Upstream of the spine.** Guild's spine (`analyze → design → execute → test → qa`) develops **one existing Issue**. `plan` is the step *before* that: it reads a **project/epic-level source** and decomposes it into a **dependency-ordered set of dev-unit GitHub Issues** that the spine then develops. It is the only Guild command that ingests a **file** (or an epic Issue) and *creates many* Issues — the intake that fills the backlog.

`$1` = **a design-doc file path** *or* **an Issue number/URL** (auto-detected). `$2` = `--create` (default = **dry-run**: propose only, create nothing).

> **Bash**: `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. Handoff / owner-repo / labels / parent-child: `<<SKILL_DIR>>/commands/atoms/_handoff.md` (Sections A, F, I). Roles: product-owner + tech-lead personas.
> **Output language**: all human-readable output (proposal, discuss, report) in `config.language` (`_handoff.md` Section K). Machine tokens / `file:line` / `#N` stay ASCII.

> **This is a MULTI-TURN, attended flow** (Phase 2 discuss). It runs in the **main session** — decomposing a backlog is a high-judgment decision the human refines before anything is created.

> **`plan` vs design's multi-PR split** — both produce parent/child Issues, but differ in intent/timing: `plan` (issue mode) is the *deliberate, upfront* decomposition of an epic into its backlog (before dev); design's split is the *emergent* one discovered while designing one Issue. Both converge on the same `dev` Phase 2b orchestration. `plan` decomposes only to **dev-unit grain**, so its children are leaves design won't re-split.

---

## Phase 0 — Preflight & mode detection

1. **Guild initialized?** `ls .claude/guild/config.json` — absent → `FAIL: Guild not initialized (run /gld init first)`. `plan` needs the config, the product-owner/tech-lead role defs, and `docs/standards/charter.md` (value-alignment).
2. **Resolve owner/repo** once (`_handoff.md` Section F).
3. **Detect mode** (its own Bash call — inspect `$1`): a bare integer or a URL containing `/issues/` → **issue mode**; otherwise → **file mode**.
4. **Load the source + context**:
   - **file mode**: Read the file at `$1` (the design doc). Absent/unreadable → `FAIL: design doc not found at $1`. Also read `CLAUDE.md` + `docs/standards/` (charter/architecture/conventions) for the decomposition's grounding.
   - **issue mode**: `gh issue view $1` — validate it is an Issue, not a PR (`/pull/` in URL → `FAIL`). Its body is the source. **Leaf guard**: if the Issue's labels include `guild:child`, refuse — a child cannot be planned/re-split → `NEEDS_HUMAN: #$1 is a child issue — re-scope its parent instead`. Read `CLAUDE.md` + `docs/standards/` too.
5. **Idempotency check**:
   - **file mode**: look for an existing manifest `docs/specs/PLAN-<doc-slug>.md`. Present → this doc was already planned; re-derive the created set and offer to add **only new** issues (do not duplicate).
   - **issue mode**: if `#$1` already has the `guild:children` label (already planned/split), re-derive the roster from its `<!-- guild:children:output -->` comment and offer to add only new children.

## Phase 1 — Decompose (product-owner ∥ tech-lead, parallel)

As the leader, spawn BOTH role sub-agents in one message (independent, concurrent):

**Product Owner** (value slicing):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `product-owner plan`
- `prompt`:
  > Adopt the persona in `.claude/agents/product-owner.md`. Decompose the following source into a backlog of **vertically-sliced, independently-deliverable dev-unit issues**, each aligned to user value against `docs/standards/charter.md`. SOURCE: <the doc contents (file mode) OR the Issue #$1 body (issue mode)>. For each proposed issue produce: a concise **title**, **scope** (what + why, not how), **acceptance criteria** (verifiable), a **priority**, and **non-goals**. Right-size each to a **single dev unit** (one analyze→…→qa pass) — split a too-large feature, merge trivial ones. Group issues under **epics/areas**. Write the result as a FILE to `docs/specs/plan-<slug>/po.md` (do not paste it back). Return one `>>> RESULT <<<` line per `_handoff.md` Section C.

**Tech Lead** (dependency order + sizing):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tech-lead plan`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. From the same SOURCE (below) and `docs/standards/architecture.md`, produce a **dependency ordering** of the work: **foundations first** (data model / schema / core state / shared modules) before the features that depend on them. Flag each **foundational** issue, note **cross-cutting** concerns, and **size** each candidate (single dev-unit ✅, or ⚠ likely to child-split at design). Do NOT read the product-owner's output (order independently from the source). Write to a FILE `docs/specs/plan-<slug>/sequence.md`. Return one `>>> RESULT <<<` line per `_handoff.md` Section C. SOURCE: <same as above>.

Collect both RESULTs. As the leader, **arbitrate into one unified proposed issue set**: PO's value slices + AC, ordered/sized by the tech-lead's sequence, foundations first. Note any disagreement (PO wants a slice the tech-lead says must wait on a foundation → order accordingly).

## Phase 2 — Discuss & refine (attended) + STOP

Present the proposed backlog and **stop for the human**:
```
<source>를 <K>개 dev-unit 이슈로 분해했습니다 (에픽·의존성 순서):

▎에픽: <area A>
  ① [type] <제목>  — <한 줄 범위>  · AC: <n>개 · <🏗 기초 | 크기⚠ design서 분할 예상>
  ② [type] <제목>  — …  (① 의존)
▎에픽: <area B>
  ③ …

권장 실행 순서: ① → ② → ③ …
이대로 만들까요? (이슈 드롭/병합/재범위/재정렬 요청 가능. `--create` 없이 실행하셨다면 지금은 제안만 — 확정 시 생성합니다.)
```
Handle the human's edits (drop / merge / re-scope / reorder / adjust AC) and re-present until they approve. **Do not create anything in dry-run** (no `--create` and no explicit approval). **Unattended** (`GLD_UNATTENDED=1`): creating a backlog is too high-stakes to auto-commit → post the proposal and return `OK PAUSE: needs-human — backlog proposed, awaiting approval` (no creation).

## Phase 3 — Create the backlog (only on `--create` or explicit approval)

Create issues in **dependency order** (temp-file body per `_bash_rules.md`; each `gh issue create` its own Bash call). Label by mode:

- **file mode** — top-level backlog issues:
  ```bash
  gh issue create --title "<title>" --body-file <temp> --label "guild:analyze" --label "type:<feature|bug|refactor>" --label "area:<epic>"
  ```
  Body = scope + acceptance criteria + a `Planned from: <doc path>` line + any `Depends on: #<n>` notes.
- **issue mode** — children under the epic `#$1` (reuses the parent/child model — `_handoff.md` Section I):
  ```bash
  gh issue create --title "[Guild子] <title>" --body-file <temp> --label "guild:child" --label "guild:analyze" --label "type:<...>"
  ```
  Body = scope + AC + a `Parent Issue: #$1` line.

**Record the manifest (idempotency + humans):**
- **file mode**: write `docs/specs/PLAN-<doc-slug>.md` — the created issues (`#<n>` · epic · title · one-line scope · order · depends-on). Committed with the work.
- **issue mode**: post the roster on the parent under `<!-- guild:children:output -->` … `<!-- /guild:children:output -->` (one row per child), then label the parent:
  ```bash
  gh issue edit $1 --add-label "guild:children"
  ```
  This routes `/gld dev $1` into child orchestration (dev Phase 2b).

## Phase 4 — Return + next steps

- **dry-run** (no `--create`): present the proposed set + *"확정하려면 `--create`로 다시 실행하세요."* Return `OK: proposed N issues (dry-run)`.
- **created**: report the created issues (#s, titles, order) + the next command:
  - **file mode** → *"`/gld batch <issues>`로 일괄 개발하거나, 순서대로 `/gld dev <첫 이슈>`부터 시작하세요."*
  - **issue mode** → *"`/gld dev #$1` — 자식들을 의존성 순서로 오케스트레이션합니다 (Phase 2b)."*

Returns: `OK: created N issues` · `OK: proposed N issues (dry-run)` · `NEEDS_HUMAN: <...>` · `FAIL: <reason>`.

## Hard rules
- **Default dry-run.** Issues are created **only** with `--create` or an explicit human approval at Phase 2 — creating GitHub Issues is an outward, hard-to-reverse action (INV1).
- **`plan` proposes/creates Issues only** — it does **not** design or implement. It stops at a filled backlog; the spine (`dev`/`batch`) takes over.
- **Decompose to dev-unit grain** — each issue is one bounded spine pass. Issue-mode children are **leaves** (design won't re-split them; the leaf guard holds).
- **Idempotent** — a re-run detects the manifest (file mode) or `guild:children` (issue mode) and adds only new issues, never duplicates.
- All Bash per `_bash_rules.md`; every issue body via a temp file + `--body-file` (never inline multi-line `--body`).
