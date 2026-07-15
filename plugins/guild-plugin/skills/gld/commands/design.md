# DESIGN (stage)

**Stage: design.** Core roles: **tech-lead ∥ tester** (leader orchestrates), **plus any conditional participation specialists the leader convenes** (designer/i18n/dba/analytics/performance — Step 1.5). The tech-lead drafts the skeleton; the tester writes test cases from the acceptance criteria **without seeing the skeleton** (bias-free — plan §4, §16 C4). They run in parallel. Invocable directly (`/gld design <issue>`) or via `/gld dev`.

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Medium tier** (items 1–4). Item 4 loads the `<!-- guild:analyze:output -->` comment (feature list + **acceptance criteria**). If analyze output is missing → the stage is out of order; return `NEEDS_CONTEXT: analyze output not found for #$1` (leader should run analyze first).

Validate `$1` is an Issue (not a PR). Ensure entry label `guild:design` if invoked directly.

Ensure the spec dir exists for file-based handoff:
```bash
ls docs/specs/$1
```
(If absent, the role sub-agents create `docs/specs/$1/` when writing their artifacts.)

## Step 1 — Spawn tech-lead and tester in parallel
As the leader, spawn BOTH role sub-agents in a single message (two Agent tool calls) so they run concurrently and independently (`claude -p`-style isolation is unnecessary in M1 — in-process Agent is fine, plan §12):

**Tech Lead** (skeleton first):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tech-lead design #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. You are designing Issue #$1 for this repo. Read the analyze output (`<!-- guild:analyze:output -->` on the Issue) and `docs/standards/`. Produce the **skeleton**: module boundaries, data flow, extension seams, file structure. Write it as a FILE to `docs/specs/$1/skeleton.md` (do not paste it back). Decide whether this needs a **multi-PR split** (child issues) and note it. Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C (`DONE: skeleton at docs/specs/$1/skeleton.md — <one-line>`), or `BLOCKED:`/`NEEDS_CONTEXT:`/`FAIL:`.

**Tester** (test cases from AC only — do NOT read the skeleton):
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tester cases #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/tester.md`. Read ONLY the acceptance criteria from the analyze output (`<!-- guild:analyze:output -->`) — do NOT read the tech-lead's skeleton (bias-free test design). Write test cases (normal + edge + failure paths) as a FILE to `docs/specs/$1/test-cases.md`. Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C.

## Step 1.5 — Conditional participants (leader assembles)
As the leader, decide which **participation specialists** this design needs, using the assembly rules in `.claude/agents/leader.md` ("팀 조립 규칙") and `_handoff.md` Section G. Match the change surface (Issue body + AC + hotspots) against triggers:
- **UI/screen surface** → **designer** (UX/interaction/visual/a11y design).
- **user-facing strings / multi-language** → **i18n**.
- **schema / migration / data-model** → **dba**.
- **instrumentation / metrics** → **analytics**.
- **performance-sensitive (hot path, render, query)** → **performance**.
- **doc-worthy change (an architecture decision → ADR, or user-facing docs)** → **tech-writer** (plan the ADR / which docs need updating; the actual drafts follow the implementation at execute).
- **auth / external exposure / secrets / sensitive data** → **security** (design-time **threat modeling** — review the approach, data flow, and trust boundaries *before* it is built; the adversarial diff review is a separate execute-stage gate).

Spawn only the matched roles (none matched → skip this step entirely; that is the common case and costs nothing). Spawn them **in the same parallel message as tech-lead+tester when possible** (all design-stage work is independent). For each matched role:
- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `<role> design #$1`
- `prompt`:
  > Adopt the persona in `.claude/agents/<role>.md`. Contribute to the **design** of Issue #$1 for this repo. Read the analyze output (`<!-- guild:analyze:output -->`) and `docs/standards/`. Do NOT read the tech-lead's skeleton (design in parallel, from AC). Write your design contribution as a FILE to `docs/specs/$1/<role>.md` (e.g. `ux.md` for designer). Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C.

(The designer writes `docs/specs/$1/ux.md` per its template. If a specialist reports the area is not applicable to this change, it returns `DONE` with a one-line "해당 없음" note and no file — that is fine.)

## Step 2 — Collect handoff, arbitrate
Read every RESULT line (tech-lead, tester, and any conditional participants):
- All `DONE`/`DONE_WITH_CONCERNS` → proceed. Record any concerns (esp. a specialist's — e.g. designer a11y concern, i18n sync concern) in the design output.
- Any `BLOCKED`/`NEEDS_CONTEXT` → as the leader, intervene: supply the missing context and re-invoke that role, or if unresolvable → **attended**: `NEEDS_HUMAN: <one-line>` · **unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H): low/medium design ambiguity → decide charter-anchored + record assumption; high/scope-defining or genuinely blocked → `OK PAUSE: needs-human — <one-line>` (no transition).
- Any `FAIL` → return `FAIL: <reason>`.

**Multi-PR split (parent/child — `_handoff.md` Section I):** the single-PR path is the common case. Only if the tech-lead flagged a genuine **multi-PR split** (independently deliverable slices, each with its own PR + tests) do the following, as the leader:
- **Leaf-only guard first**: if `$1` is itself a child (its labels include `guild:child`), a child must not be re-split — return `NEEDS_HUMAN: child #$1 cannot be re-split — re-scope the parent` and do NOT proceed to Step 4.
- **Idempotency guard** (its own Bash call): check whether children already exist before creating any —
  ```bash
  gh issue view $1 --json comments --jq '[.comments[].body | select(contains("<!-- guild:children:output -->"))] | length'
  ```
  `> 0` → children already created (a prior interrupted design); re-derive them via the Section I discovery query and skip creation. `0` → create them now.
- **Create each child** in intended dependency order (temp-file body per `_bash_rules.md`); body = slice scope + AC + a `Parent Issue: #$1` line:
  ```bash
  gh issue create --title "[Guild子] <slice name>" --body-file <temp> --label "guild:child" --label "guild:analyze"
  ```
- **Post the roster** on the parent under `<!-- guild:children:output -->` … `<!-- /guild:children:output -->` (temp-file pattern): one row per child (`#<n>` · slice · one-line scope). Static index — not PATCHed per child (Section I).
- Note the split decision + child numbers in the design output too, then go to **Step 4b** (split transition) instead of Step 4.

**Ground-truth capture (①, `_signals.md` Section C):** if a human **overrides the design approach** at this gate — rejects the tech-lead's approach for a different one, or the design is found **superseded / a duplicate** of prior work (e.g. #893 turned out to duplicate #891) — append one entry (its own Bash call), `--surprise` when it reverses a confident design choice:
```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue $1 --stage design --role tech-lead --area "<the changed area — path-prefix/module>" --summary "<design approach → override/supersede>" --evidence "<1 line: chosen alt / duplicate ref>" --surprise
```
Do **not** capture routine acceptance of the design (agreement ≠ correction).

**③ Overseer learning (D 예측-후-공개 + 자기설명 — `_learning.md`)**: for a material design fork (attended), before revealing the tech-lead's approach or a specialist's finding, **first invite the human's prediction** — *"이 설계에서 뭐가 걸릴까요?" / "어떤 접근이 맞을까요?"* — then reveal, and **name the principle** behind it (A — e.g. "테마 토큰 모드 분기", "동작보존 리팩터"). On an override, optionally capture the human's one-line *"왜?"* (self-explanation). Opt-in, non-condescending; fade with competence (F).

**Ground-truth capture (①, agent↔agent — `_signals.md` Sections B & C):** if a design-stage **participation specialist** (designer/dba/security/performance/i18n/…) returns a `BLOCKED` whose **concrete objective finding reverses a decided or proposed approach** — e.g. the designer's WCAG measurement overturns a chosen color, dba finds a schema-integrity violation in the proposed model, security finds a threat in the approach — append one entry (its own Bash call, best-effort — never blocks). The objective finding (the measured ratio / integrity rule / vuln) **is** the anchor — one role overturning another's decided output, not self-review (Section B). `--surprise` always (a decided approach reversed — §8-A):
```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue $1 --stage design --role <designer|dba|security|…> --area "<the area the finding concerns — e.g. lib/theme, db/schema>" --summary "<what was reversed, 1 line>" --evidence "<the objective finding, e.g. #CCCCCC vs #9E9E9E = 1.67:1 < 4.5:1 WCAG>" --surprise
```
**Skip** a mere `DONE_WITH_CONCERNS` (a flagged concern is not a reversal), a `NEEDS_CONTEXT` (missing input, not a defect), and any subjective preference not anchored to an objective finding.

## Step 3 — Post design output + durable spec
Post the design summary comment (temp-file pattern):
- Marker: `<!-- guild:design:output -->` … `<!-- /guild:design:output -->`.
- Contents: design summary, pointer to `docs/specs/$1/skeleton.md`, pointer to `docs/specs/$1/test-cases.md`, pointers to any conditional-participant artifacts (`docs/specs/$1/ux.md` etc.), which specialists participated (and why), PR-split decision, any concerns. `<details>` preflight trace.

The durable artifacts already live in `docs/specs/$1/` (written by the roles) and are committed with the PR.

## Step 4 — Transition + return (single-PR path)
```bash
gh issue edit $1 --remove-label "guild:design" --add-label "guild:execute"
```
Return:
```
>>> RESULT <<<
OK ADVANCE: execute
```
Other returns: `NEEDS_HUMAN`, `NEEDS_CONTEXT`, `FAIL` (do NOT transition on these).

## Step 4b — Split transition + return (multi-PR path only)
When children were created (or re-derived) above, the parent does **not** advance to execute — it enters orchestration (`_handoff.md` Section I):
```bash
gh issue edit $1 --remove-label "guild:design" --add-label "guild:children"
```
Return (`N` = number of children):
```
>>> RESULT <<<
OK SPLIT: N children
```
This routes `/gld dev` into child orchestration (dev Phase 2b). The parent's execute/test/qa are the sum of its children + a parent-integration check.

## Hard rules
- **Tester independence**: the tester MUST NOT see the skeleton (spawn prompt enforces this). This is the anti-bias core of design.
- Artifacts pass as **files** (`docs/specs/$1/`), never pasted into RESULT lines (context protection).
- Design is read-only against source code — it writes only spec files + the Issue comment + label.
