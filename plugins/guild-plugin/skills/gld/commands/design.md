# DESIGN (stage)

**Stage: design.** Core roles: **tech-lead ∥ tester** (leader orchestrates), **plus any conditional participation specialists the leader convenes** (designer/i18n/dba/analytics/performance — Step 1.5). The tech-lead drafts the skeleton; the tester writes test cases from the acceptance criteria **without seeing the skeleton** (bias-free — plan §4, §16 C4). They run in parallel. Invocable directly (`/gld design <issue>`) or via `/gld dev`.

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.

---

## Step 0 — Preflight
As the leader, follow `_preflight.md` **Medium tier** (per its Section A table: items **1 + 2 + 3 + 4 + 6 + 8** — not just 1–4; items 6/8 are the ⑥ knowledge-slice retrieval and ④ working-memory read, both needed to honestly populate the Section C self-review trace). Item 4 loads the `<!-- guild:analyze:output -->` comment (feature list + **acceptance criteria**). If analyze output is missing → the stage is out of order; return `NEEDS_CONTEXT: analyze output not found for #$1` (leader should run analyze first).

Validate `$1` is an Issue (not a PR). **Read current labels first** (its own Bash call, same pattern as `analyze.md`):
```bash
gh issue view $1 --json labels --jq '[.labels[].name] | map(select(startswith("guild:")))'
```
- Empty (no `guild:*` label — fresh, direct invocation) → add `guild:design`: `gh issue edit $1 --add-label "guild:design"`.
- Contains `guild:child` → **note this as `IS_LEAF = true` and carry it to Step 2 — do NOT refuse here.** ⚠ A `guild:child` label is **permanent** on a child Issue (nothing ever removes it — it's an identity marker, not a stage label) and every child of every split carries it, so refusing here unconditionally (an earlier version of this fix did exactly that) would make `NEEDS_HUMAN: child #$1 cannot be re-split` fire on **every single child's own ordinary design stage**, permanently breaking the multi-PR-split feature — `_handoff.md` Section I's actual invariant is conditional ("**if** a `guild:child` Issue's design **flags a further split**, that is a scoping error"), not "a child may never pass design at all." The refusal belongs in Step 2, gated on whether *this issue's own* tech-lead actually proposes another split — see below. A leaf child with no further split proposed goes through the single-PR path exactly like any other Issue.
- Non-empty otherwise (any other `guild:*` label, including `guild:design` itself or `guild:children`) → do **not** add `guild:design` on top (would dual-label).

**Then ALWAYS run the Section I discovery query** (its own Bash call — cheap and read-only) to check whether children already exist for `$1`:
```bash
gh issue list --label guild:child --state all --limit 200 --json number,title,labels,body --jq '[.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))] | sort_by(.number)'
```
⚠ **Gate this check on the discovery query's result, never on the current label** — an interrupted split is left labeled `guild:design` (the label only flips to `guild:children` *after* every child already exists, Step 2 below), so a genuinely-interrupted resume case does **not** show `guild:children` at Step 0; checking the label instead of just running the query is exactly the bug an earlier version of this fix had (it gated resume-detection on `guild:children`, which by construction never coexists with a partial child set — so that version's resume path could never actually fire for the case it was meant to catch). Non-empty result → **resuming an interrupted split**: carry the full result (each child's `number`/`title`/`body`) into Step 1's tech-lead prompt below. Empty → fresh start, nothing to carry.

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
  > Adopt the persona in `.claude/agents/tech-lead.md`. You are designing Issue #$1 for this repo. Read the analyze output (`<!-- guild:analyze:output -->` on the Issue) and `docs/standards/`. Produce the **skeleton**: module boundaries, data flow, extension seams, file structure. Write it as a FILE to `docs/specs/$1/skeleton.md` (do not paste it back). Decide whether this needs a **multi-PR split** (child issues) and note it. **If Step 0's discovery query found existing children**: <for each, in dependency order: its issue number, title, and body text — the body already states its scope + AC per the creation format below, there is no separate "scope" field to look up>. These slices are ALREADY COMMITTED (real GitHub Issues exist for them) — do NOT redecide the split from scratch or reorder/resize/rename these existing slices. Treat them as fixed and decide ONLY the remaining slice(s) needed to complete the same split, in a way that's consistent with what already exists (same dependency ordering, no scope overlap/gap with the committed ones). If on reflection the already-committed slices don't make sense to you, that's a real design conflict — return `BLOCKED: existing split slices #<n> conflict with — <reason>` instead of silently re-splitting differently. Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C (`DONE: skeleton at docs/specs/$1/skeleton.md — <one-line>`), or `BLOCKED:`/`NEEDS_CONTEXT:`/`FAIL:`.

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
- Any `BLOCKED`/`NEEDS_CONTEXT` → as the leader, intervene: supply the missing context and re-invoke that role, or if unresolvable → **attended**: `NEEDS_HUMAN: <one-line>` · **unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H): low/medium design ambiguity → decide charter-anchored + record assumption; high/scope-defining or genuinely blocked → add the **`guild:needs-human` label** + a `<!-- guild:needs-human -->` comment stating the unresolved concern, and return `OK PAUSE: needs-human — <one-line>` (do NOT transition the stage label). This mirrors `implement.md`/`debug.md`/`refactor.md`'s unattended bounded-retry-exit handling.
- Any `FAIL` → return `FAIL: <reason>`.

**Multi-PR split (parent/child — `_handoff.md` Section I):** the single-PR path is the common case. Only if the tech-lead flagged a genuine **multi-PR split** (independently deliverable slices, each with its own PR + tests) do the following, as the leader:
- **Leaf-only guard first** — check `IS_LEAF` from Step 0: if `$1` is itself a child (carries `guild:child`) and its *own* tech-lead just proposed splitting it further, that's the actual scoping error `_handoff.md` Section I's leaf invariant means — return `NEEDS_HUMAN: child #$1 cannot be re-split — re-scope the parent` now and do NOT proceed to child creation below. (A leaf whose tech-lead did *not* propose a split never reaches this bullet at all — it took the single-PR path above instead, which is the normal case for almost every child.)
- **Idempotency guard** — reuse the discovery-query result **Step 0 already fetched unconditionally** (never the roster-comment presence alone — the roster is posted *last*, below, so an interruption between "create child #1" and "post the roster" would otherwise leave a comment-presence check blind to the just-created child and **recreate it as a duplicate** on retry; never the current label either, since a genuinely-interrupted split stays labeled `guild:design` until every child exists, per the ordering below — see Step 0). Non-empty → children already exist — **do NOT skip creation outright**: create **only the slices Step 1's tech-lead didn't already treat as fixed** (Step 1's prompt, when Step 0 found existing children, explicitly instructed the tech-lead to keep them as-is and decide only what's still missing — so its returned slice list should already exclude the existing ones; do not re-derive "missing" by guessing positional order). Skipping creation entirely when *any* children are found (an earlier version of this guard did that) silently drops the remaining slices forever with no error. Also check whether the parent already carries `guild:children` (in hand from Step 0) and whether the roster comment exists (`gh issue view $1 --json comments --jq '[.comments[].body | select(contains("<!-- guild:children:output -->"))] | length'`); apply whichever of those is still missing (below). Empty result → create every slice fresh, below.
- **Create each still-missing child** in intended dependency order (temp-file body per `_bash_rules.md`); body = slice scope + AC + a `Parent Issue: #$1` line:
  ```bash
  gh issue create --title "[Guild子] <slice name>" --body-file <temp> --label "guild:child" --label "guild:analyze"
  ```
- **Flip the label right after the LAST child exists** (before posting the roster) — skip this if the idempotency guard above already found `guild:children` present. **Also strip `guild:needs-human` in this same call if present** (same rule as every other stage transition — `_handoff.md` Section A):
  ```bash
  gh issue edit $1 --remove-label "guild:design" --add-label "guild:children" --remove-label "guild:needs-human"
  ```
  Ordering matters in both directions. Flipping it only after the roster is posted (an earlier version of this doc did that) leaves a race window where a concurrent `/gld resume $1`/`/gld dev $1` still sees `guild:design` while children already exist, and tries to design/execute the parent directly instead of routing to child orchestration. But flipping it *before any child is created* is also wrong (a version of this fix briefly tried that): an interruption between the label flip and the first `gh issue create` leaves the parent labeled `guild:children` with **zero** children, and `dev.md` Phase 2b's discovery step treats that as an unrecoverable state-inconsistency `FAIL` (it does not wait or retry) — a worse failure mode than the one being fixed, since resuming the parent no longer routes back through design's own idempotency guard at all. Flipping the label **after every child exists but before the roster** gets the benefit (a concurrent reader during the now-much-shorter remaining window sees `guild:children` and correctly routes to Phase 2b, where it will always find ≥1 child) without the risk (the label is never set while the child count is provably zero).
- **Post the roster** on the parent under `<!-- guild:children:output -->` … `<!-- /guild:children:output -->` (temp-file pattern) — only if not already present (idempotency guard above): one row per child (`#<n>` · slice · one-line scope). Static index — not PATCHed per child (Section I).
- Note the split decision + child numbers in the design output too, then go to **Step 4b** (return only — the label transition already happened above) instead of Step 4.

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
Remove **whatever `guild:*` stage label Step 0 actually found** (normally `guild:design`, but a direct `/gld design` invocation on an Issue already past design — Step 0's "any other label → leave it, proceed anyway" branch — leaves its real label, e.g. `guild:execute` or `guild:test`, in place instead; `gh issue edit --remove-label` on a label the Issue doesn't carry can error, per `_handoff.md`'s documented caveat, leaving the Issue stuck un-transitioned; **never remove `guild:child`** if present — this is the normal path for a leaf child whose own tech-lead didn't propose a split; substitute the actual pre-existing label from Step 0's read in place of `guild:design` below when it was something else). **Also remove `guild:needs-human` in this same call if Step 0's label read found it present** (`_handoff.md` Section A):
```bash
gh issue edit $1 --remove-label "guild:design" --add-label "guild:execute" --remove-label "guild:needs-human"
```
Return:
```
>>> RESULT <<<
OK ADVANCE: execute
```
Other returns: `NEEDS_HUMAN`, `NEEDS_CONTEXT`, `FAIL` (do NOT transition on these).

## Step 4b — Split return (multi-PR path only)
When children were created (or re-derived) above, the parent does **not** advance to execute — it enters orchestration (`_handoff.md` Section I). The `guild:design` → `guild:children` label transition already happened in Step 2 — **after every child existed, before the roster was posted** (not before creation — Step 2 explains why flipping it earlier would be worse). By the time this label transition happens, no reader ever sees a parent labeled `guild:children` with fewer children than intended. This step only returns (`N` = the **total** number of children now existing for this parent — i.e. the discovery-query count after this step, not just how many were newly created this run; on a resume, N includes the previously-existing ones too):
```
>>> RESULT <<<
OK SPLIT: N children
```
This routes `/gld dev` into child orchestration (dev Phase 2b). The parent's execute/test/qa are the sum of its children + a parent-integration check.

## Hard rules
- **Tester independence**: the tester MUST NOT see the skeleton (spawn prompt enforces this). This is the anti-bias core of design.
- Artifacts pass as **files** (`docs/specs/$1/`), never pasted into RESULT lines (context protection).
- Design is read-only against source code — it writes only spec files + the Issue comment + label.
