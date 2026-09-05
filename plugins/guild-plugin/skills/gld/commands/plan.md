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
   - **issue mode**: `gh issue view $1 --json state,url,labels,body` — validate it is an Issue, not a PR (`/pull/` in URL → `FAIL`). Its body is the source. **Leaf guard**: if the Issue's labels include `guild:child`, refuse — a child cannot be planned/re-split → `NEEDS_HUMAN: #$1 is a child issue — re-scope its parent instead`. **Stage-label guard**: if `$1` already carries a spine stage label (`guild:analyze`/`design`/`execute`/`test`/`qa`/`done`) — e.g. someone ran `/gld dev #$1` directly on what turns out to be an epic-sized Issue — surface this to the human before proceeding (*"이 이슈는 이미 `guild:<stage>` 단계입니다 — 지금 분해하면 Phase 3에서 `guild:children`이 함께 붙어 두 라벨이 공존하게 됩니다(`_handoff.md`: parent는 절대 스테이지 라벨과 `guild:children`을 동시에 가지면 안 됨). 계속할까요?"*), and if they confirm, **remove that stage label** (and `guild:needs-human` too, if present — same rule as every stage transition, `_handoff.md` Section A) before Phase 3 adds `guild:children` (do not leave either behind). Read `CLAUDE.md` + `docs/standards/` too.
5. **Idempotency check**:
   - **file mode**: look for an existing manifest `docs/specs/PLAN-<doc-slug>.md`. Present → this doc was already planned; re-derive the created set and offer to add **only new** issues (do not duplicate).
   - **issue mode**: whether or not `#$1` already has the `guild:children` label, first re-derive the actual child set from the Section I discovery query (`gh issue list --label guild:child ... --jq '... test("Parent Issue: #<parent>...")'`, `_handoff.md` Section I) rather than trusting the `<!-- guild:children:output -->` comment alone — the comment is posted last (Phase 3), so it may be stale or absent if a prior run was interrupted after creating some children but before posting it or relabeling the parent. Non-empty result → already planned (fully or partially); offer to add only children still missing from that query's result, then apply whichever of the label/roster is still missing (Phase 3). Empty result (regardless of the label) → nothing created yet; proceed to Phase 1 normally.

## Phase 1 — Decompose (product-owner ∥ tech-lead, parallel)

As the leader, spawn BOTH role sub-agents in one message (independent, concurrent):

**If Phase 0's idempotency check found existing items** (a file-mode manifest, or issue-mode children from the discovery query), append the same note to **both** prompts below: <the existing set — for file mode, the manifest's issue list (`#<n>` · title · scope); for issue mode, the discovered children's number/title/body>. These are ALREADY COMMITTED (real GitHub Issues) — do NOT redecide/reorder/resize/rename them. Treat them as fixed and decompose/order ONLY the remaining work needed to complete the same backlog, consistent with what already exists. If the existing items don't make sense on reflection, that's a real conflict — return `BLOCKED: existing backlog items conflict with — <reason>` instead of silently redeciding differently. (Same fix pattern as `design.md` Step 1's tech-lead prompt for a resumed multi-PR split — this file had the identical gap: Phase 1 used to always redecompose from scratch even when Phase 0 had already found a partial prior run, risking duplicate/inconsistent re-creation in Phase 3.)

**Product Owner** (value slicing):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `product-owner plan`
- `prompt`:
  > Adopt the persona in `.claude/agents/product-owner.md`. Decompose the following source into a backlog of **vertically-sliced, independently-deliverable dev-unit issues**, each aligned to user value against `docs/standards/charter.md`. SOURCE: <the doc contents (file mode) OR the Issue #$1 body (issue mode)>. For each proposed issue produce: a concise **title**, **scope** (what + why, not how), **acceptance criteria** (verifiable), a **priority**, and **non-goals**. Right-size each to a **single dev unit** (one analyze→…→qa pass) — split a too-large feature, merge trivial ones. Group issues under **epics/areas**. Write the result as a FILE to `docs/specs/plan-<slug>/po.md` (do not paste it back).
  > <!-- guild:result-contract -->
  > Return EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. Anything before the sentinel is ignored. Status is one of `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <one-line>` / `NEEDS_CONTEXT: <one-line>` / `FAIL: <reason>`. **Artifacts are passed as files, not pasted** — write to the working tree or `docs/specs/<issue>/` and name the path in the RESULT line; never inline an artifact body into it.
  > <!-- /guild:result-contract -->

**Tech Lead** (dependency order + sizing):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tech-lead plan`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. From the same SOURCE (below) and `docs/standards/architecture.md`, produce a **dependency ordering** of the work: **foundations first** (data model / schema / core state / shared modules) before the features that depend on them. Flag each **foundational** issue, note **cross-cutting** concerns, and **size** each candidate (single dev-unit ✅, or ⚠ likely to child-split at design). Do NOT read the product-owner's output (order independently from the source). Write to a FILE `docs/specs/plan-<slug>/sequence.md`.
  > <!-- guild:result-contract -->
  > Return EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. Anything before the sentinel is ignored. Status is one of `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <one-line>` / `NEEDS_CONTEXT: <one-line>` / `FAIL: <reason>`. **Artifacts are passed as files, not pasted** — write to the working tree or `docs/specs/<issue>/` and name the path in the RESULT line; never inline an artifact body into it.
  > <!-- /guild:result-contract -->
  > SOURCE: <same as above>.

Collect both RESULTs. As the leader, **arbitrate into one unified proposed issue set**: PO's value slices + AC, ordered/sized by the tech-lead's sequence, foundations first (on a resume, this unified set should already exclude the existing items per the prompts above). Note any disagreement (PO wants a slice the tech-lead says must wait on a foundation → order accordingly).

## Phase 2 — Discuss & refine (attended) + STOP

Present the proposed backlog and **stop for the human**. **On a resume** (Phase 0 found existing items), lead with a one-line note of what already exists (`"#61, #62는 이미 생성됨 — 나머지 <N>개만 새로 만듭니다."`) before the list, so the human isn't confused about why the count looks smaller than expected:
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

**Check which labels actually exist first** (its own Bash call) — `init.md` only ever creates the `guild:*` labels of its P2 §7 block (never `type:*`/`area:*`), and `gh issue create --label <name>` **errors** on a label that doesn't exist in the repo yet (unlike `gh label create`, it does not auto-create one). A fresh `/gld init`'d repo has no `type:*`/`area:*` labels at all, so using them unconditionally below would make every `gh issue create` call in this phase fail outright:
```bash
gh label list --limit 200 --json name --jq '[.[].name]'
```
Only attach `--label "type:<...>"` / `--label "area:<...>"` below when that exact label name is present in this result (same guard `init.md`'s own harness-remediation issue creation uses: *"`+ type:refactor/type:chore if those labels exist`"*). When a needed one is missing, either skip attaching it (the issue still gets created, just without that label) or offer to `gh label create` it first if the human wants the taxonomy — but never assume it exists.

Create issues in **dependency order** (temp-file body per `_bash_rules.md`; each `gh issue create` its own Bash call). Label by mode:

- **file mode** — top-level backlog issues:
  ```bash
  gh issue create --title "<title>" --body-file <temp> --label "guild:analyze" --label "type:<feature|bug|refactor>" --label "area:<epic>"
  ```
  (Omit the `type:*`/`area:*` labels above per the existence check if they're not in the repo's label set.) Body = scope + acceptance criteria + a `Planned from: <doc path>` line + any `Depends on: #<n>` notes.
- **issue mode** — children under the epic `#$1` (reuses the parent/child model — `_handoff.md` Section I). **Create every child first**, THEN label the parent, THEN post the roster — in that order:
  ```bash
  gh issue create --title "[Guild子] <title>" --body-file <temp> --label "guild:child" --label "guild:analyze" --label "type:<...>"
  ```
  (Same `type:*` existence guard as file mode.)
  Body = scope + AC + a `Parent Issue: #$1` line. Once every child exists, relabel the parent:
  ```bash
  gh issue edit $1 --add-label "guild:children"
  ```
  Ordering matters in both directions. Relabeling only after posting the roster (an earlier version of this doc did that) leaves a race window where a concurrent `/gld resume $1`/`/gld dev $1` still sees the epic's plain issue state and fails to route into child orchestration. But relabeling *before any child is created* is also wrong (a version of this fix briefly tried that): an interruption between the relabel and the first `gh issue create` leaves the parent labeled `guild:children` with **zero** children, and `dev.md` Phase 2b's discovery step treats that as an unrecoverable state-inconsistency `FAIL` rather than waiting — worse than the race being fixed. Relabeling **after every child exists but before the roster** gets the benefit without that risk — the label is never set while the child count is provably zero.

**Record the manifest (idempotency + humans):**
- **file mode**: write `docs/specs/PLAN-<doc-slug>.md` — the created issues (`#<n>` · epic · title · one-line scope · order · depends-on). Committed with the work.
- **issue mode**: post the roster on the parent under `<!-- guild:children:output -->` … `<!-- /guild:children:output -->` (one row per child) — the label was already set above, right after the last child was created. This routes `/gld dev $1` into child orchestration (dev Phase 2b).

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
