# stage_test — Sub-agent Design

Phase B / Arch B design for the **test** stage as a single sub-agent. Inlines `test_work` + 3 (or 4) review atoms + `/verify` Skill invocation + manual QA gate logic, returns one `>>> RESULT <<<` line to the main session.

Sources: `spec/stage/test.md`, `spec/00-common-contracts.md`, `spec/edge-cases.md`, `design/00-architecture.md`, `design/01-sub-agent-contract.md`, `design/02-file-layout.md`.

---

## §1. Inputs

Spawned by main session via Agent tool (`subagent_type: general-purpose`) with prompt template per `01-sub-agent-contract.md` §1:

```
Read <<SKILL_DIR>>/skills/sdd/atoms/stage_test.md and execute its
instructions for Issue #<N>.

Inputs:
  Issue:  #<N>
  Depth:  <default|deep|shallow>
  Branch: <branch-name|null>          # threaded from implement
  PR:     #<PR_NUM|null>              # threaded from implement
  Resume: <none|continue-after-escalation|qa-back-to-implement>
```

### Field semantics

| Field | Use |
|---|---|
| Issue | Under test. Validated per Common Contracts §10 (Issue, not PR). |
| Depth | Selects reviewer models (`_review_helpers.md` A.2). `test_work` always opus. |
| Branch / PR | Cache hints; sub-agent re-derives via `gh pr list --search "Refs #<N>"` if absent. |
| Resume | `none` (fresh) / `continue-after-escalation` (Round 3 Continue → skip to §7) / `qa-approved` / `qa-failed` (returned from main's manual-QA prompt — see §6/§12). |

Additional optional input (set by main after §13 re-spawn): `Framework: <name>`.

[PRESERVE — contract §1]: sub-agent does NOT receive prior stage outputs in the prompt; it re-reads GitHub.

### Entry preconditions (verified in §3)

- Issue exists, labelled `sdd:test`.
- Either: open PR matching `Refs #<N>` (single/child), OR `<!-- sdd:children:output -->` exists with ALL children at `sdd:done` (parent).

---

## §2. Phase 0 — Depth detection

```
1. gh issue view <N> --json labels --jq '[.labels[].name]'
2. Resolve depth:
     - sdd:review:deep   → deep
     - sdd:review:shallow → shallow
     - else              → default
3. Model assignments (per _review_helpers.md A.2):
     test_work               : opus (always, regardless of depth) [§2 PRESERVE]
     test_review:completeness: sonnet / opus / sonnet
     test_review:quality     : sonnet / opus / sonnet
     test_adversarial        : opus  / opus / sonnet
     parent_integration_review (parent only): opus / opus / sonnet
```

[PRESERVE — spec/stage/test.md Phase 0]: `test_work` opus is non-negotiable; producer atom does the most consequential reasoning.

---

## §3. Phase 1 — Path detection (SINGLE/CHILD vs PARENT)

See §10 for the full path-detection algorithm + reviewer-count rules. Phase 1 sets the routing variable `path ∈ {SINGLE, PARENT}` used in §4–§7.

Outcomes:
- `path = PARENT` if `<!-- sdd:children:output -->` exists on the Issue.
  - Sub-step: confirm ALL children are `sdd:done`. If any child not done → return `FAIL: parent has incomplete children: #X, #Y, ...` immediately.
- `path = SINGLE` otherwise. Defer determination of whether literal kind is "single" or "child" to `test_work`'s `OK` variant (cf. §10).

[PRESERVE — spec/stage/test.md Phase 1; edge-cases.md §2]: parent gating is double-checked here AND inside `test_work` (defensive).

---

## §4. Phase 2 — Test + AI Review Loop (max 3 rounds)

The retry loop is the core of stage_test. Per `00-architecture.md` §3, reviews run **serially** inside this sub-agent (single-level spawn rule — sub-agents cannot spawn sub-agents).

### Round structure (each round)

```
2.X.1 — Inline test_work logic (Phase 2.X.1 below) → posts <!-- sdd:test:output -->
2.X.2 — Inline review atoms SERIALLY:
          a) test_review (role=completeness)  → posts marker
          b) test_review (role=quality)       → posts marker
          c) test_adversarial                 → posts marker
          d) parent_integration_review        → posts marker  (PARENT path ONLY)
2.X.3 — Combine verdicts; decide retry/exit/escalate
```

### Round 1 — Phase 2.1.1 (work)

Inline `test_work` logic (formerly `commands/atoms/test_work.md`):

1. Re-validate path (defensive, see §10):
   - SINGLE: `gh pr list --search "Refs #<N>" --state open` returns ≥1 PR. Else `FAIL: no open PR found for Issue #<N>`.
   - PARENT: all children `sdd:done` (§10). Else `FAIL: parent has incomplete children: ...`.
2. Test framework detection (PARENT only — see §13).
3. Generate/validate test scope:
   - SINGLE: validate Stage 3's PR diff covers analyze/design DoD via Grep/Glob/Read tools (NOT Bash find/grep).
   - PARENT w/ integration: create `test/<parent-feature-name>` branch, author E2E tests, push, open integration PR (body via Write tool + `--body-file`, NEVER heredoc — Common Contracts §8/§9).
   - PARENT w/o integration: document rationale in `<!-- sdd:test:output -->`.
4. Compose QA checklist (Automated / Manual / Regression — see §12).
5. Render `<!-- sdd:test:output -->` body to `/tmp/sdd-test-output-<N>.md`; post via Section F.2 duplicate-prevention.
6. Return one of:
   - `OK SINGLE PR: #N` | `OK PARENT INTEGRATION_PR: #M` | `OK PARENT NO_INTEGRATION`
   - `FAIL: <reason>` (incl. the special `FAIL: no E2E test setup detected; recommended framework: <name>` re-spawn case — see §13).

### Round 1 — Phase 2.1.2 (reviews, serial)

For each reviewer in order (completeness → quality → adversarial → [parent_integration]):

```
- Re-read shared context (Round 1 only; round 2+ self-fetches prior findings instead):
    - <!-- sdd:analyze:output -->, <!-- sdd:design:output -->, <!-- sdd:test:output --> from Issue
    - SINGLE: gh pr diff <PR> + relevant files via Read tool
    - PARENT: each child's analyze/design/implement findings JSON; integration PR diff if any
- Apply role rubric: atoms/rubrics/test-<role>.md (per 02-file-layout.md §1)
- Compose review body with findings JSON block (Common Contracts §5)
- Render to /tmp/sdd-review-test-<role>-{<N>|pr<PR_NUM>}.md via Write tool
- Post to PR (SINGLE) or Issue (PARENT) via Section F.2 duplicate-prevention
- Internal return: OK PASS | OK FAIL: <summary> | FAIL: <reason>
```

[PRESERVE — spec/stage/test.md §2.1.2]: post location varies by path. See §5/§10.

[PRESERVE — Common Contracts §12]: each review applies its OWN rubric only. No cross-visibility of other reviewers' verdicts within a round.

### Round 1 — Phase 2.1.3 (verdict combine + retry decision)

```
Collect verdicts: V_c, V_q, V_a [, V_p for PARENT].
- Any FAIL: → return FAIL: <first reason>; stop entire stage.
- All OK PASS → exit retry loop; go to §5 (SINGLE) or §6 (PARENT).
- Otherwise (one or more OK FAIL):
    Combine FAIL summaries.
    Adversarial-only FAIL: if V_a = OK FAIL while V_c = V_q [= V_p] = OK PASS:
        Log "⚠ Adversarial reviewer alone identified critical/major issues. Surfacing for awareness."
        Round still counts as FAIL (edge-cases.md §19).
    If round < 3 → enter Round (R+1) with internal retry flag = "retry".
    If round == 3 → exit; go to §8 (escalation gate).
```

[PRESERVE — edge-cases.md §19]: adversarial-only-FAIL behavior matches all other stages.

### Round 2 & 3 — retry mode

Identical structure to Round 1, with inlined work logic in retry mode:

- Stage-internal flag (NOT main-session-driven — per contract §5).
- Work logic self-fetches round-(R-1) review markers via `gh api ... contains("<marker>")`:
  - **SINGLE**: 3 markers — `sdd:review:test:{completeness,quality,adversarial}`.
  - **PARENT**: 4 markers — same 3 PLUS `<!-- sdd:review:parent -->`.
- Addresses every `critical` and `major` finding; `minor` is read for context only.
- Step 0 preflight SKIPPED on round 2+ (edge-cases.md §13 — ~30K tokens saved).

[PRESERVE — Common Contracts §7]: self-fetch is atom-side. Main session NEVER reads the JSON itself (v0.36 token-savings invariant). Defensive: any retry-flag value other than `"retry"` → return `FAIL: unrecognized retry slot value: <truncated>`.

---

## §5. Phase 2.7 — `/verify` Skill (single/child path only)

See §11 for the full `/verify` Skill invocation details. Triggered only when `path = SINGLE` and `sdd:review:shallow` is not set, AND `/verify` Skill is available.

After §4's retry loop exits with all reviewers PASS (or escalation Continue):

```
if path == PARENT:                       → skip §5; go to §6
if depth == 'shallow':                    → skip §5; record tools_skipped reason=shallow-label-skip
if /verify Skill unavailable:             → skip §5; record tools_skipped reason=skill-unavailable
else:
    Invoke /verify via Skill tool (inside this sub-agent — VERIFIED reachable per Common Contracts §13).
    Map /verify transcript output:
        "feature works as expected" → PASS_EVIDENCE
        "feature does not work" / "crash" / "error observed" → FAIL_EVIDENCE
    Record outcome inside the <details> self-review trace block of <!-- sdd:test:output --> (update-in-place via Section F.2).
```

Non-blocking: §5's outcome is **additional context** for §6's user gate. It does NOT by itself decide PASS/FAIL. (Manual QA — or `skip-review: qa` auto-approval — is the final gate.) See §11.

---

## §6. Phase 3 — User review + manual QA

Stage sub-agents do NOT call `AskUserQuestion` (contract §4 — only main session may prompt the user). The Phase 3 user gate is split:

Read `.github/.sdd-config` once via Read tool to detect `skip-review: qa`. See §12 for full branching.

**Case A — `qa` in skip-review (auto-approve)**: log "User review skipped (skip-review: qa)" in the self-review trace, auto-approve checklist, auto-continue past any "E2E was skipped in Stage 3" prompt; proceed to §7.

**Case B — `qa` NOT in skip-review (interactive)**: return
```
>>> RESULT <<<
OK NEEDS_MANUAL_QA: <summary including verify evidence, test output URL, E2E_SKIPPED flag if any>
```

Main session renders the summary, calls `AskUserQuestion` for the manual QA item results, and re-spawns `stage_test`:
- All pass → `Resume: qa-approved` → sub-agent jumps to §7.
- Any fail → `Resume: qa-failed` → sub-agent returns `OK BACK_TO_IMPLEMENT` (main routes user to `/sdd implement <N>`).

[RETHINK — vs current arch]: v0.x's orchestrator handled this dialog directly. Arch B's split costs an extra spawn but preserves the "sub-agents non-interactive" invariant.

[PRESERVE — spec/stage/test.md Phase 3.2]: user MAY edit the QA checklist comment directly on GitHub before reporting. Main re-reads latest state before §7.

---

## §7. Phase 4 — Results review (label transition)

Triggered when:
- §6 case A (skip-review.qa auto-approval) finished, OR
- §6 case B's main session returns with `Resume: qa-approved`.

```
1. Atomic label transition (two simple Bash calls, per Common Contracts §8):
     gh issue edit <N> --remove-label "sdd:test" --add-label "sdd:done"
     gh issue close <N>
2. If this Issue is a CHILD (body matches multilingual parent regex — see §14):
     → execute §14 (Phase 5) child completion notification
3. Return:
     >>> RESULT <<<
     OK DONE
```

If §6 case B's main session returns with `Resume: qa-failed`:

```
1. NO label transition. Leave label as sdd:test.
2. Return:
     >>> RESULT <<<
     OK BACK_TO_IMPLEMENT
```

Main session then surfaces `/sdd implement <N>` to the user (or auto-invokes for `/sdd auto`). The current `stage_test` invocation ends here; on a future test stage re-entry, §3 Phase 1 will re-evaluate the (updated) PR and run the AI review loop from scratch (3-round budget resets — spec/stage/test.md Phase 4 step 1).

[PRESERVE — spec/stage/test.md Phase 4]: label is the authoritative state. No file, no env var, no in-process state.

---

## §8. Phase 2.5 — Round 3 escalation gate

Reached only when §4's round 3 also failed. Sub-agent CANNOT call `AskUserQuestion` (contract §4).

**Case A — `qa` in skip-review**: post a self-review-trace addendum to `<!-- sdd:test:output -->` (update-in-place): "⚠ Round 3 escalation: tests still failing after 3 rounds, but skip-review: qa is set — auto-continuing. Findings remain on Issue/PR for human follow-up." Then proceed to §5 (or §6 for PARENT) without prompting.

**Case B — interactive**: return
```
>>> RESULT <<<
ESCALATE: test round 3 FAIL — findings: [critical] X, [major] Y
```

Main session handles per contract §6:
- Continue → re-spawn `stage_test` with `Resume: continue-after-escalation`. Sub-agent skips Round 1 work and review rounds (already posted), jumps to §5 (SINGLE) or §6 (PARENT). Findings remain on GitHub for human follow-up.
- Pause → main exits gracefully ("Resume later with `/sdd resume <N>`"). Label stays `sdd:test`.
- Stop → main exits immediately.

---

## §9. Phase 6 — Output (return contract)

Final `>>> RESULT <<<` line, one of:

| Return | Meaning | Triggering path |
|---|---|---|
| `OK DONE` | All tests passed; label → sdd:done; Issue closed | §7 success branch |
| `OK BACK_TO_IMPLEMENT` | QA failure (interactive); user routed to implement | §7 failure branch |
| `OK NEEDS_MANUAL_QA: <summary>` | Sub-agent paused for user manual-QA gate | §6 case B (interactive) |
| `OK PAUSE` | User chose Pause in escalation (via main) | §8 case B + main Pause |
| `ESCALATE: <summary>` | Round 3 FAIL interactive — main asks user | §8 case B |
| `FAIL: <reason>` | Atom-level error — main stops | any §4 / §5 / §6 atom-level failure, §1 validation failure |

[PRESERVE — `01-sub-agent-contract.md` §2 stage_test row]: the "core" 5 returns (DONE / BACK_TO_IMPLEMENT / PAUSE / ESCALATE / FAIL) match the contract spec. The `OK NEEDS_MANUAL_QA` is a stage_test-specific addition not present in stage_analyze/design — because test is the only stage with a mid-stage interactive gate that isn't pure pass/fail (manual QA results are user data, not a yes/no escalation).

[NEW — Arch B]: `OK NEEDS_MANUAL_QA` is new to the stage-level contract. Main session contract validation (`01-sub-agent-contract.md` §9) must be extended to accept this keyword for stage_test only.

---

## §10. Path detection (SINGLE/CHILD vs PARENT) + reviewer count

### Detection algorithm (Phase 1)

```
1. gh api repos/<owner>/<repo>/issues/<N>/comments
       --jq '.[] | select(.body | contains("sdd:children:output")) | .id'
   (Common Contracts §4: exact substring including leading "<!-- " and trailing " -->".)
2. If marker found:
     path = PARENT
     Parse child Issue numbers from the table; for each child:
       gh issue view <child> --json labels --jq '[.labels[].name]'
       If "sdd:done" NOT in labels → record as incomplete.
     If any incomplete → return FAIL: parent has incomplete children: #X, #Y, ...
3. Else: path = SINGLE  (literal single vs spawned child determined later by test_work's OK variant).
```

### Re-detection inside test_work (defensive)

§4 Phase 2.X.1 step 1 re-validates path. Preserves v0.x defensive behavior (catches drift if a child's label flips between Phase 1 and the work step). [RETHINK — spec/stage/test.md §5]: dual detection is duplicative; future cleanup is to pass `path` explicitly into inlined work logic.

### Reviewer count by path

| | SINGLE/CHILD | PARENT (with integration) | PARENT (no integration) |
|---|---|---|---|
| Reviewers spawned in §4 Phase 2.X.2 | **3** (completeness/quality/adversarial) | **4** (+ parent_integration_review) | **4** (+ parent_integration_review) |
| Review marker post location | PR (Refs #<N>) | Parent Issue | Parent Issue |
| `parent_integration_review` marker | n/a | Parent Issue `<!-- sdd:review:parent -->` | Parent Issue `<!-- sdd:review:parent -->` |
| §5 `/verify` Skill | Runs (unless shallow/unavailable) | **Skipped** | **Skipped** |
| §6 Manual QA scope | Single feature on PR #N | Cross-child + integration PR #M | Cross-child + per-child manual items |
| §6 Integration PR created? | No (uses Stage 3's PR) | Yes (`test/<parent-feature-name>`) | No |
| §14 Child completion notify | If Issue body has parent ref | n/a (parent has no parent) | n/a |

[PRESERVE — spec/stage/test.md §5]: dual-location review posting (PR vs Issue) is the most error-prone part of test stage. The inlined reviewer logic in §4 must read `path` from the stage-internal variable set in §3, NOT re-derive it.

### Why path determines reviewer count

- **SINGLE/CHILD**: the PR diff is the focus. 3 reviewers suffice; no cross-Issue synthesis needed.
- **PARENT (either variant)**: no single PR encompasses the parent's scope. `parent_integration_review` is mandatory — it aggregates cross-child state by reading each child's analyze/design/implement findings JSON + interface contract files.

### `test_work` OK-variant → path mapping

| `test_work` return | path | integration_pr |
|---|---|---|
| `OK SINGLE PR: #N` | SINGLE | n/a |
| `OK PARENT INTEGRATION_PR: #M` | PARENT | #M |
| `OK PARENT NO_INTEGRATION` | PARENT | null |

The 4-reviewer rule for PARENT applies regardless of `INTEGRATION_PR` vs `NO_INTEGRATION`. `parent_integration_review` adjusts its codebase exploration based on whether an integration PR exists, but spawns identically.

---

## §11. `/verify` Skill invocation (Phase 2.7)

Inline behavior, single/child path only. Implements spec/stage/test.md Phase 2.7 inside the stage sub-agent (Common Contracts §13 — Skill tool reachable from `general-purpose` sub-agent, VERIFIED).

### Pre-checks (skip conditions)

```
if path == PARENT          → skip silently (semantic skip, not tools_skipped)
elif depth == 'shallow'     → skip; tools_skipped += {"name":"/verify","reason":"shallow-label-skip"}
elif /verify unavailable    → log to self-review trace; skip;
                              tools_skipped += {"name":"/verify","reason":"skill-unavailable"}
                              # Causes: Claude Code ≤ v2.1.145, Skill disabled, or no app-launch capability
else                        → invoke
```

[IMPROVE — spec/stage/test.md Phase 2.7 RETHINK]: spec called out that graceful-skip silently downgraded coverage. This design wires the `tools_skipped` array (Common Contracts §5 schema) for auditability — both reason enums already in the schema.

### Invocation + output mapping

```
Invoke Skill tool: /verify (no args; Skill reads project context).
Capture transcript.
```

| `/verify` phrase | Recorded as |
|---|---|
| "feature works as expected" | PASS evidence for §6 |
| "feature does not work" / "crash" / "error observed" | FAIL evidence for §6 |

### Recording

Update `<!-- sdd:test:output -->` self-review trace (update-in-place via Section F.2):

- `[x] /verify ran: feature launches and matches description`
- `[ ] /verify reported: error on login screen — see transcript`

Plus `tools_run` / `tools_skipped` fields of the findings JSON inside `<!-- sdd:test:output -->`.

**Non-blocking**: `/verify`'s verdict is *added to* §6's context. It does NOT itself decide PASS/FAIL — manual QA (or skip-review.qa auto-approval) is the final gate.

---

## §12. Manual QA (Phase 3) — skip-review.qa branch

The QA checklist lives inside `<!-- sdd:test:output -->`'s body, structured into three sub-sections (per `test_work.md` source):

```
- Automated:  items verified by tests in the PR (auto-PASS).
- Manual:     items requiring human verification (UI behavior, locale-dependent flows, visual states).
- Regression: items targeting prior fragility areas.
```

### skip-review parsing

Read `.github/.sdd-config` once via Read tool. Parse YAML-ish `skip-review:` list. Token `qa` triggers the auto-approve branch.

### Auto-approve branch (`qa` in skip-review)

| Gate | Behavior under skip-review.qa |
|---|---|
| §6 user-review gate | Bypassed. Log "User review skipped (skip-review: qa)" in self-review trace. |
| §8 Round 3 escalation gate | Auto-continues to §5 (Phase 2.7) without prompting. |
| §6 "E2E was skipped in Stage 3" prompt | Auto-continues. Gap remains documented on Issue/PR for human follow-up. |

Path through stage_test under skip-review.qa: §1 → §2 → §3 → §4 (full retry loop, AI review always runs) → §5 (if SINGLE+available) → §7 → return `OK DONE`. Zero `OK NEEDS_MANUAL_QA` or `ESCALATE` returns.

[PRESERVE — edge-cases.md §8, §18]: skip-review.qa does NOT skip AI reviewers. Loaded warning: only USER gates are bypassed.

### Interactive branch (`qa` NOT in skip-review)

Three sub-gates require main-session interaction:

1. **§8 Round 3 escalation**: returns `ESCALATE`. Main asks Continue/Pause/Stop.
2. **"E2E was skipped in Stage 3"** (single/child only): if `test_work` posted with E2E_SKIPPED flag, `OK NEEDS_MANUAL_QA` summary must include this fact; main asks "add E2E now (push to PR branch) or proceed without."
3. **§6 manual QA gate**: returns `OK NEEDS_MANUAL_QA: <summary>`. Main asks user for each manual checklist item pass/fail.

Main re-spawns `stage_test` with a `Resume:` value:

| User input | Resume value | Sub-agent behavior |
|---|---|---|
| Escalation Continue | `continue-after-escalation` | Skip to §5 (SINGLE) or §6 (PARENT) |
| Escalation Pause / Stop | (no re-spawn) | Main exits; label stays sdd:test |
| QA all-pass | `qa-approved` | Execute §7 label transition + child notify; return OK DONE |
| QA any-fail | `qa-failed` | Return OK BACK_TO_IMPLEMENT immediately (no label change) |

### QA failure → implement loop-back

On any failed manual QA item (spec/stage/test.md Phase 4 step 1): main analyzes cause with user (pure conversation), user invokes `/sdd implement <N>` for TDD bug-fix cycle. `stage_test` already returned `OK BACK_TO_IMPLEMENT`; label stays `sdd:test`. On next test entry (after fixes), §3 re-evaluates the updated PR and runs §4 from scratch — the 3-round budget RESETS, not a continuation.

[PRESERVE — spec/stage/test.md §7]: implicit re-entry via `/sdd implement`. [RETHINK]: `sdd:test:retry` marker for auto-resume — deferred.

---

## §13. Test framework detection + re-spawn pattern

### Trigger

Inside §4 Phase 2.X.1 step 2 (inlined `test_work` logic), **PARENT path only**, at the test-setup-detection sub-step.

Single/child path expects an existing framework (Stage 3's implement_e2e already used one). If single/child has no framework, the gap is surfaced via the "E2E was skipped in Stage 3" flag in §6, NOT via this detection.

### Detection signals

```
- Framework type: Jest, Vitest, Pytest, Go test, Playwright, Cypress, etc.
- Test directory layout: tests/, __tests__/, e2e/, ...
- Test run command: package.json scripts, Makefile, etc.
- Test configuration files: jest.config.*, pytest.ini, playwright.config.*, etc.
```

All detection uses Grep / Glob / Read tools (per Common Contracts §8 — NEVER Bash `find` outside repo root, NEVER `cat`/`head`/`tail`/`awk`/`sed`).

### Failure path: no E2E setup found

```
1. Inlined test_work returns the special FAIL prefix:
     FAIL: no E2E test setup detected; recommended framework: <name>; user confirmation required
2. §4 detects this prefix BEFORE the generic `FAIL: → stop` branch and returns:
     >>> RESULT <<<
     OK NEEDS_FRAMEWORK_CHOICE: recommended=<name>
3. Main session surfaces recommendation, calls AskUserQuestion (recommended + alternates),
   re-spawns stage_test with extra input: `Framework: <chosen-name>`.
4. Sub-agent re-runs §4 Phase 2.X.1; inlined test_work skips detection and uses the chosen framework.
```

[PRESERVE — spec/stage/test.md §9]: special-prefix detection is required. Generic `FAIL:` stops the stage; this one prefix surfaces a recoverable case.

[NEW — Arch B]: `OK NEEDS_FRAMEWORK_CHOICE` is stage_test-specific (like `OK NEEDS_MANUAL_QA`). Contract validation (§9) accepts it for stage_test only. Arch B's prompt template (§1) makes `Framework:` an explicit input field, tightening spec/stage/test.md §9's RETHINK about implicit prompt-text passing.

---

## §14. Child completion notification (Phase 5)

Triggered inside §7 (Phase 4 label transition) when the just-completed Issue is a **child**.

### Detection

```
1. Read Issue body via cached fetch from §1 or `gh issue view <N> --json body`.
2. Apply multilingual parent regex (per spec/02-multilingual.md §3 / edge-cases.md §1):
       (Parent|상위 |親)Issue: #<n>
   Boundary safeguard: `([^0-9]|$)` after the number, so #683 doesn't match #6831.
3. If match found → this Issue is a child; capture parent's <n> as PARENT_N.
4. Else → not a child; skip §14.
```

### Update parent's children comment row

```
1. Fetch parent's <!-- sdd:children:output --> comment id via duplicate-prevention search.
2. Fetch its body, update the table row for child #<N> to "done" state.
3. Render new body to /tmp/sdd-children-output-<PARENT_N>.md via Write tool.
4. PATCH the comment: gh api .../comments/<id> -X PATCH --field body=@<path>
   (Common Contracts §9 — --field, NOT -F.)
```

### Notify parent when all children done

```
1. Re-parse the updated table; count rows in "done" state.
2. If ALL done:
     - Compose multilingual notification (templates/<lang>/..., language detected per parent's body):
         en: "All children complete; parent ready for /sdd test #<PARENT_N>."
         ko: "모든 하위 Issue 완료; 상위 Issue 준비 완료: /sdd test #<PARENT_N>."
         ja: "全ての子Issueが完了しました; 親Issue準備完了: /sdd test #<PARENT_N>。"
     - Post as a NEW (accumulating) comment on the parent — not marker-keyed:
         gh issue comment <PARENT_N> --body-file /tmp/sdd-children-notify-<PARENT_N>-<seq>.md
   Else: no notification posted.
```

[PRESERVE — spec/stage/test.md §11]: Phase 5 logic is shared verbatim with `implement.md` Phase 7 (single source of truth). This section reproduces the logic for `stage_test`'s self-contained inlining, but the canonical version lives in the design for `stage_implement.md`.

### Race condition + ordering

Concurrent child completions could both PATCH the parent's children table; PATCH isn't atomic in GitHub. SDD's serial-per-Issue pipeline makes this unlikely; `/sdd resume <PARENT_N>` re-derives state if it does occur (edge-cases.md §2 — empirically tolerated).

Ordering inside §7 (§14 runs AFTER successful label transition):

```
1. gh issue edit <N> --remove-label "sdd:test" --add-label "sdd:done"   [must succeed]
2. gh issue close <N>                                                    [must succeed]
3. If child → §14 (update parent's children comment + notify if all done)
4. Return OK DONE
```

If step 1 or 2 fails → return `FAIL: <reason>`; §14 unreached; no parent notification sent.

---

## §15. Open questions / RETHINK summary

Carried forward from spec/stage/test.md for visibility:

1. **Dual path detection** (Phase 1 + inlined test_work re-detection in §10): duplicative. Future cleanup is to pass `path` explicitly into inlined work logic.
2. **`tools_skipped` wiring for `/verify` skip reasons** (§11): IMPLEMENTED here via `"skill-unavailable"` / `"shallow-label-skip"` enum values. Resolves spec/stage/test.md Phase 2.7 RETHINK.
3. **Test stage re-entry signal after QA failure** (§12): currently implicit (`/sdd implement <N>`). `sdd:test:retry` marker candidate; deferred.
4. **Hard-gate test-evidence comments** (spec/stage/test.md §8 IMPROVE): currently reviewer-discretionary. Promote to `test_work` hard gate? Catches silent E2E skips. Deferred.
5. **`OK NEEDS_MANUAL_QA` / `OK NEEDS_FRAMEWORK_CHOICE`**: new stage_test-specific return keywords. Main session contract validation (`01-sub-agent-contract.md` §9) needs the stage_test row extended.
6. **Round preservation** (in-place marker overwrite — Common Contracts §4 / edge-cases.md §6): round 1 / round 2 review content lost after round 3 PATCH. Round-suffixed markers (`:r1`/`:r2`/`:r3`) deferred globally; affects test stage uniformly with other stages.

---

## §16. Cross-references

- Architecture overview: `design/00-architecture.md`
- Sub-agent return contract: `design/01-sub-agent-contract.md`
- File layout (`atoms/rubrics/test-*.md`): `design/02-file-layout.md`
- Source spec: `spec/stage/test.md`
- Common contracts (markers, retry, Bash, comment posting): `spec/00-common-contracts.md`
- Edge cases (parent/child, multilingual, race conditions): `spec/edge-cases.md`
- Multilingual parent regex: `spec/02-multilingual.md` §3
- Phase 5 canonical implementation: `design/stage-designs/implement.md` (Phase 7, when written)
- Test evidence procedure: `commands/atoms/_test_evidence.md` (consumed by §4 reviewers)
- Parent integration review rubric: `atoms/rubrics/parent-integration.md`
