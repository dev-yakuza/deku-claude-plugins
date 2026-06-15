# Flow: Resume

Pure dispatcher (not orchestrator). Sources: `commands/resume.md`.

---

## 1. Role [PRESERVE]

`resume.md` is a **dispatcher**. It runs in the main session, reads Issue state from GitHub (labels + comments + PRs), determines which stage orchestrator to invoke, then **reads + executes that orchestrator inline** in the same session.

Invariants:
- **Does NOT spawn sub-agents itself.** All Agent spawning belongs to the target stage orchestrators (`analyze.md` / `design.md` / `implement.md` / `test.md`).
- **Single-level safe**: because the dispatcher does not nest below an Agent call, it can be invoked from inside `/sdd auto` and `/sdd batch` loops without violating `00-common-contracts.md` §12.
- **No state writes beyond label transitions** in the parent-completion path (§3). All other state writes belong to the dispatched orchestrator.

[PRESERVE: dispatcher-vs-worker separation is a load-bearing architectural contract — the rewrite must preserve it so loop commands can re-enter without nesting violations.]

---

## 2. Dispatch Rules [PRESERVE]

State sources read in order (each is a single simple Bash call per `00-common-contracts.md` §8):

1. **Issue labels + title** — `gh issue view $1 --json labels,title --jq '{title: .title, labels: [.labels[].name]}'`
2. **Owner/repo** — `gh repo view --json nameWithOwner -q .nameWithOwner` (inline the literal `<owner>/<repo>` per `00-common-contracts.md` §11).
3. **Stage-output markers in Issue comments** — `gh api repos/<owner>/<repo>/issues/$1/comments --jq '.[] | select(.body | contains("sdd:analyze:output") or contains("sdd:design:output") or contains("sdd:children:output") or contains("sdd:implement:plan") or contains("sdd:test:output")) | .body'`
4. **Related PRs** — `gh pr list --search "Refs #$1" --json number,title,state,headRefName`

Markers checked:
- `<!-- sdd:analyze:output -->`
- `<!-- sdd:design:output -->`
- `<!-- sdd:children:output -->` (parent Issue indicator — branches to §3)
- `<!-- sdd:implement:plan -->`
- `<!-- sdd:test:output -->`

### Single-Issue / Child-Issue dispatch table

| Label | Output / PR state | Dispatch target |
|---|---|---|
| (no SDD label) | — | Add `sdd:analyze` label, then `analyze.md` |
| `sdd:analyze` | no `analyze:output` | `analyze.md` |
| `sdd:analyze` | `analyze:output` exists | `analyze.md` (re-confirms; atom duplicate-prevention handles in-place update) |
| `sdd:design` | `analyze:output` present, no `design:output` | `design.md` |
| `sdd:design` | `design:output` exists | `design.md` (re-confirm; same pattern) |
| `sdd:implement` | `design:output` exists, no PR | `implement.md` (plan + TDD from scratch) |
| `sdd:implement` | open PR exists | `implement.md` (TDD atom mode-detects, continues from existing PR) |
| `sdd:implement` | PR closed (not merged) | skip-review `implement` → start new PR automatically; interactive → ask reopen vs new. Then `implement.md` |
| `sdd:implement` | branch exists, no PR | skip-review `implement` → create PR from branch automatically; interactive → ask. Then `implement.md` |
| `sdd:test` | PR(s) present | `test.md` |
| `sdd:done` | — | Report "Issue is already complete." Stop. |

**Dispatch action**: read the target orchestrator file via the Read tool, execute its instructions inline in the same main session. `resume.md` does not spawn sub-agents.

[PRESERVE: table is the canonical state→action mapping; loose-compat rewrite may rename labels but must preserve the resume-from-state semantics.]

[IMPROVE: the two "re-confirm pattern" rows (`sdd:analyze` + output exists, `sdd:design` + output exists) silently re-invoke the orchestrator and rely on the work atom's duplicate-prevention to no-op. Cleaner: detect the redundancy at the dispatcher and either skip-to-next-stage or ask the user. Current behavior leaks responsibility into atoms.]

---

## 3. Parent Issue Handling [PRESERVE]

If the Issue has `<!-- sdd:children:output -->` posted, it is a **parent** (see `00-common-contracts.md` §1: parent stops at `sdd:implement` after `design` creates children).

Flow:
1. Read child Issue numbers from the children comment body.
2. Check each child's current label via `gh issue view <child> --json labels`.
3. Report child progress to the user, one row per child (label + name).
4. Decide action:
   - **All children `sdd:done`** → transition parent label `sdd:implement` → `sdd:test` (single `gh issue edit` Bash call with `--remove-label sdd:implement --add-label sdd:test`), then **read + execute `test.md` inline** for the parent. `test.md` has internal parent-path logic (`parent_integration_review` atom, optional integration PR, etc.).
   - **Any child incomplete**:
     - If skip-review for `analyze` / `design` / `implement` / `pr` is set in `.github/.sdd-config` → **stop silently**, report pending children, exit cleanly. The surrounding loop (`/sdd auto` / `/sdd batch`) is responsible for queuing the pending children.
     - Else (interactive) → **ask user which child to resume**, then read + execute `resume.md` inline for the chosen child Issue.

**Why stop silently in unattended modes**: parent's incomplete-children branch must not block the loop. Children are queued by `auto.md` §3.3 / `batch.md` Phase 3 child auto-discovery, so re-prompting inside `resume.md` would deadlock unattended runs.

[PRESERVE: parent-pause + child-completion-promotes-parent invariant is the contract from `00-common-contracts.md` §1.]

[RETHINK: the "ask which child to resume" interactive path is reachable from inside `/sdd auto` only if skip-review is incomplete (e.g. user enabled only `analyze` but not `implement`). This is a partial-skip-review hole — the loop would block. In practice `/sdd auto` pre-loop writes the full set `analyze,design,implement,pr,qa`, so the silent-exit branch always wins. Document the invariant explicitly: **any caller of `resume.md` in unattended mode MUST set all four user-gate skip-review keys**.]

---

## 4. Skip-Review Handling [PRESERVE]

Per `01-config.md` §2: skip-review skips the **user confirmation gate**, not the AI review loop.

Dispatcher behavior:
- If the determined stage's skip-review key is set in `.github/.sdd-config` → **skip user confirmation** and immediately read + execute the target orchestrator. This enables `/sdd auto` and `/sdd batch` to chain stages without prompting.
- Otherwise → ask the user `"Resume from <stage>? [y/N]"`, then read + execute the target orchestrator on yes.

**Valid skip-review keys consumed directly by the dispatcher**: `analyze`, `design`, `implement`.

**Keys consumed elsewhere**: `pr` and `qa` are consumed inside `implement.md` / `test.md` respectively. **`test` is NOT a valid skip-review value** — the test stage's user-confirmation gate is `qa`.

[PRESERVE: gate semantics are a user-visible contract from `01-config.md` §2.]

[IMPROVE: the asymmetry — dispatcher reads `analyze`/`design`/`implement` but `pr`/`qa` get read by their orchestrators — is a maintenance hazard. Centralize the "should I prompt?" decision in a single helper used by all gates.]

---

## 5. Idempotent Re-Entry [PRESERVE]

Calling `/sdd resume <N>` multiple times on the same Issue:
- Produces the **same dispatch decision** for the same on-GitHub state.
- Partial-state recovery is handled by atom-level marker duplicate prevention (Section F of `_review_helpers.md`, surfaced in `00-common-contracts.md` §9). Comments update in place; labels advance only when their stage genuinely completes.

This is what makes `resume.md` safe inside `/sdd auto`'s loop: a re-run after a failure picks up from the last on-GitHub state, even if the in-memory main-session state was lost.

[PRESERVE: on-GitHub state as the only durable state is `00-common-contracts.md` §2.]

[IMPROVE: "idempotent" is asymptotic — there is a small window between label transition and output marker write where re-entry could see the new label but no output, causing redundant work. Document the window or close it (e.g. label transition is the LAST step of an orchestrator, not the first).]

---

## 6. Reporting [PRESERVE]

Before dispatching, print:

```
Issue #$1: <title>
Current stage: <stage>
Resuming from: <specific point>
```

For parents: print the child-progress table from §3 instead.

---

## 7. Input Validation [PRESERVE]

Per `00-common-contracts.md` §10: validate `$1` is an Issue (not a PR). PRs → stop with the standard error message. Empty / nonexistent → stop with not-found.

---

## Cross-references

- Common contracts → `spec/00-common-contracts.md` (§1 stage flow, §8 bash rules, §9 comment posting, §10 issue validation, §11 owner/repo, §12 sub-agent spawning)
- Skip-review semantics → `spec/01-config.md` §2
- Multilingual parent regex → `spec/02-multilingual.md` §3
- Loop callers → `spec/flow/auto.md`, `spec/flow/batch.md`
