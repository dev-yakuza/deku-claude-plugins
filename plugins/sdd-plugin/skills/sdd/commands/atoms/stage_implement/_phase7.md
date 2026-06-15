# STAGE: implement — Phase 7 child completion notification (topic file)

Topic file read inline by `main.md` §4.1 when Resume hint = `phase-7`. Executes inside the same single sub-agent context — no Agent spawns.

[PRESERVE — load-bearing edge case per `spec/stage/implement.md` §4 Phase 7 + `design/stage-designs/implement.md` §16]: Phase 7 runs ONLY when:
- The Issue body matches the multilingual parent regex `(Parent|상위 |親)Issue: #<n>` (i.e. this is a child Issue), AND
- The Issue's label has just transitioned to `sdd:done` (typically after `/sdd test <child>` completed and the test stage closed the Issue).

The "just transitioned" trigger is detected by the main session bootstrap / dispatcher. Main routes back into `stage_implement` with `Resume: phase-7` specifically — NOT for fresh implement. This sub-agent invocation does NOT touch the child's own labels (already `sdd:done`); it updates the **parent's** `<!-- sdd:children:output -->` row for this child and optionally posts an "all done" notification on the parent.

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`.

---

## §1. Inputs (held in narrative from `main.md`)

- `$1` — child Issue number.
- `<owner>/<repo>` — captured in `main.md` §2.

## §2. Return value (to `main.md`)

- `OK PAUSE` — Phase 7 complete (regardless of all-children-done state). `main.md` returns this verbatim. Sub-agent does NOT advance any label; main session does nothing further (per `design/stage-designs/implement.md` §16.4 — "side-effect-only path").
- `FAIL: <reason>` — atom-level error (e.g. gh API failure).

---

## §3. Step 1 — Detect Phase 7 trigger conditions (defensive re-check)

`main.md` already routed here based on Resume = `phase-7`, but re-verify the trigger conditions as defense in depth:

### §3.1 Read Issue labels + body

```bash
gh issue view $1 --json labels,body
```

Observe the literal output. Parse `labels` (array of `{name: ...}`) and `body` (string).

### §3.2 Verify `sdd:done` label

Inspect labels array. If it does NOT contain `sdd:done` → this is not a Phase 7 trigger. Return `FAIL: phase-7 requested but Issue #$1 does not have sdd:done label` (defensive — main session bootstrap should not have routed here).

### §3.3 Multilingual parent regex

Scan the Issue body for `(Parent|상위 |親)Issue: #([0-9]+)([^0-9]|$)` per `<<SKILL_DIR>>/commands/atoms/_multilingual.md` and `spec/02-multilingual.md` §3:
- `Parent` (en), `상위 ` (ko, followed by a space), `親` (ja, NOT followed by a space).
- `([^0-9]|$)` boundary class prevents `#683` matching `#6831` — load-bearing per `spec/edge-cases.md` §1 (5+ callers depend on this exact pattern).

- No match → this Issue is NOT a child. Return `FAIL: phase-7 requested but Issue #$1 is not a child Issue (no parent reference in body)`.
- Match → capture `<parent_num>` from group 2. Continue §4.

---

## §4. Step 2 — Find the most-recent children comment on parent

`spec/stage/implement.md` §4 Phase 7 step 2; `design/stage-designs/implement.md` §16.2 step 2.

```bash
gh api repos/<owner>/<repo>/issues/<parent_num>/comments --jq '.[] | select((.body | contains("<!-- sdd:children:output -->")) and (.body | contains("<!-- /sdd:children:output -->"))) | {id: .id, body: .body, created_at: .created_at}'
```

(Substitute literal `<owner>/<repo>` and `<parent_num>`.)

Observe the output:
- **No matching comments** → log to narrative: "Parent #<parent_num> has no `<!-- sdd:children:output -->` comment; skipping children-row update (no error)." Skip §5 and §6; jump directly to §7 (check every child's label + optional completion notification).
- **Single match** → use that comment's `id` and `body`.
- **Multiple matches** → use the **last** (most recent) per `spec/stage/implement.md` §10 edge case + `design/stage-designs/implement.md` §16.2 step 2. Choose by highest `created_at`.

Hold `<children_comment_id>` and `<children_comment_body>` as stage-internal state.

---

## §5. Step 3 — Update the children comment (replace this child's row)

`spec/stage/implement.md` §4 Phase 7 step 3 + `design/stage-designs/implement.md` §16.2 step 3.

The children comment body holds a narrative table or list (per `templates/<lang>/output_children.md`) with one row per child Issue. Update **in narrative reasoning** (NOT via shell text manipulation — there are no `sed` / `awk` / piped commands allowed per `_bash_rules.md`):

1. Read `<children_comment_body>` from §4.
2. Locate this child's row by `#$1`. The row typically contains the child's status / label (e.g. `sdd:implement`, `sdd:test`, etc.).
3. Replace this row's status with the new state: `sdd:done`.
4. Render the updated body (keep `<!-- sdd:children:output -->` and `<!-- /sdd:children:output -->` markers intact; preserve all other rows verbatim).

Post the updated body via Section F (PATCH the existing comment — we know the `id`):

1. **Write tool** → render the updated body to `/tmp/sdd-children-output-<parent_num>.md`.
2. **Bash** PATCH:
   ```bash
   gh api repos/<owner>/<repo>/issues/comments/<children_comment_id> -X PATCH --field body=@/tmp/sdd-children-output-<parent_num>.md
   ```
   (Use `--field`, NOT `-F`, per Common Contracts §9.)

---

## §6. Step 4 — Verify the update by re-read

```bash
gh api repos/<owner>/<repo>/issues/<parent_num>/comments --jq '.[] | select(.id == <children_comment_id>) | .body'
```

(Substitute literal `<children_comment_id>`.)

- Empty → return `FAIL: children comment <children_comment_id> on parent #<parent_num> not found after PATCH`.
- Has body → inspect that this child's row now shows `sdd:done`. If not, the PATCH may have been overwritten by a concurrent update — log warning to narrative and continue. (Sub-agent does NOT retry to avoid contention; race is rare in SDD's serial-per-Issue pipeline per `spec/edge-cases.md` §2.)

---

## §7. Step 5 — Check every child's actual label

`spec/stage/implement.md` §4 Phase 7 step 5 + `design/stage-designs/implement.md` §16.2 step 5.

### §7.1 Enumerate sibling children

Two ways to discover the child set:
- **Preferred**: parse the children comment body for all `#<n>` Issue references. For each `<n>`, check labels.
- **Fallback** (if children comment is absent per §4): search by `<!-- sdd:child-issue -->` body marker referencing parent `<parent_num>` — but this requires `gh issue list` with a filter the API doesn't directly support; cheaper to rely on the children comment as the authoritative source.

If the children comment was absent (§4 "No matching comments" branch) — skip §7 entirely and return `OK PAUSE` to `main.md`. The completion notification cannot fire without the children list.

Otherwise, parse all `#<n>` references from the children comment body (use regex `#([0-9]+)([^0-9]|$)` — apply the same boundary class).

### §7.2 Check each child's label

For each child number `<child_n>` parsed from the comment:

```bash
gh issue view <child_n> --json labels --jq '[.labels[].name]'
```

(Substitute literal `<child_n>`.)

Inspect the labels array.

### §7.3 Branch on completion state

- **ALL children are `sdd:done`** → post completion notification on parent (new comment, no duplicate-prevention — each completion event is a new comment per `design/stage-designs/implement.md` §16.2 step 5).

  Determine language from `.github/.sdd-lang` (fallback per `<<SKILL_DIR>>/commands/atoms/_multilingual.md`). Compose notification body:
  - en: `All children done. Run /sdd test <parent_num> to continue, or /sdd resume <parent_num>.`
  - ko: `모든 자식 Issue가 완료되었습니다. /sdd test <parent_num> 또는 /sdd resume <parent_num>을 실행하세요.`
  - ja: `全ての子Issueが完了しました。/sdd test <parent_num> または /sdd resume <parent_num> を実行してください。`

  Procedure (Section F, but **no duplicate-prevention** — fresh comment per completion event):
  1. **Write tool** → `/tmp/sdd-implement-completion-<parent_num>.md`.
  2. **Bash** post:
     ```bash
     gh issue comment <parent_num> --body-file /tmp/sdd-implement-completion-<parent_num>.md
     ```

- **NOT all children are `sdd:done`** → log to sub-agent narrative: "Remaining children: <list of #<n> not yet done>. Outer auto-discovery (`/sdd auto` / `/sdd batch`) will pick up remaining children." Per `spec/stage/implement.md` §10 Phase 7 edge case + `design/stage-designs/implement.md` §16.2 step 5 — **DO NOT** post a comment in this branch.

  Sub-agent does NOT ask user (`design/01-sub-agent-contract.md` §4). Interactive next-child selection is main session's job — but in Phase 7 main session does not ask either (this is a side-effect-only re-entry per §8 below). The outer auto / batch flow handles remaining children via its own auto-discovery (`spec/edge-cases.md` §2).

---

## §8. Return

Return `OK PAUSE` to `main.md`.

Phase 7 is a **side-effect-only path** (`design/stage-designs/implement.md` §16.4): no further stage work; no label transitions (main session does nothing further after `OK PAUSE` from this stage). The completion notification (if §7.3 first branch fired) is the user-visible signal that parent is ready for `/sdd test <parent_num>`.

```
OK PAUSE
```

---

## §9. Hard rules (this topic file)

- **No Agent spawns, no Skill calls.**
- **No label changes** on this child Issue (already `sdd:done`) or on the parent. The parent's label transition to `sdd:test` is the user's call (or main session's after the user runs `/sdd test <parent_num>`).
- **No new commits, no branches, no PRs.** Phase 7 only touches parent's children comment + optional notification comment.
- **All Bash per `_bash_rules.md`.** No shell text manipulation (no `sed` / `awk` / pipes) — the children-row update is done in narrative reasoning, then rendered via the Write tool.
- **All comment posting per `_review_helpers.md` Section F.** PATCH for children comment update (we have the `id`); fresh POST for completion notification (no duplicate-prevention — each completion is a new comment).
- **`--field`, NOT `-F`** per Common Contracts §9.
- **No file modifications outside the working tree.** Write tool permitted only for `/tmp/sdd-children-output-<parent_num>.md` and `/tmp/sdd-implement-completion-<parent_num>.md`.
- **Multilingual regex is canonical** per `<<SKILL_DIR>>/commands/atoms/_multilingual.md` + `spec/02-multilingual.md` §3. Boundary `([^0-9]|$)` is load-bearing.
