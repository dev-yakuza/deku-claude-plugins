# Edge Cases — Cross-cutting Catalog

Edge cases that touch multiple stages/files, platform-level constraints, recovery paths, and subtle behaviors. This file is a **cross-reference index** — most details live in stage/flow specs. Use this to find "where is X handled" or to audit failure modes.

---

## 1. Multilingual Parent Reference [PRESERVE — load-bearing]

**Concern**: child Issues created from non-English templates use translated keywords for parent reference.

**Pattern** (canonical, see `02-multilingual.md` §3):
```
(Parent|상위 |親)Issue: #<n>
```

**Used by**:
- `/sdd auto` Phase 3.3 child auto-discovery (`flow/auto.md` §3.3)
- `/sdd batch` Phase 3 generated script (`flow/batch.md` §3)
- `implement.md` Phase 7 child completion notification (parent lookup) (`stage/implement.md` §11)
- `test.md` Phase 5 child completion (`stage/test.md` §11)
- `SKILL.md` Common Definitions

**Failure mode**: regex must match `([^0-9]|$)` boundary or `#683` will match `#6831`.

[PRESERVE: 5+ callers depend on this exact pattern.]

---

## 2. Parent/Child Issue Lifecycle [PRESERVE]

**Three Issue states**:
- **Parent**: has `<!-- sdd:children:output -->` comment
- **Child**: body contains `(Parent|상위 |親)Issue: #<n>` inside `<!-- sdd:child-issue -->` block
- **Single**: neither

**Lifecycle invariants** [PRESERVE]:

| Phase | Parent | Child | Single |
|---|---|---|---|
| analyze | runs normally | runs normally (with parent context) | runs normally |
| design | creates children with `sdd:analyze + sdd:child` labels | proceeds to design | proceeds to design |
| implement (entry) | STOPS — outer flow queues children | runs full TDD | runs full TDD |
| implement Phase 7 (child completion) | N/A | updates parent's children comment row; notifies parent if all children done | N/A |
| test | requires all children `sdd:done`; may create integration PR | runs normally; Phase 5 child completion same as implement Phase 7 | runs normally |
| sdd:done | only after all children done + parent's own test | normal | normal |

**Race condition risk** [RETHINK]: two children completing concurrently might both update parent's `<!-- sdd:children:output -->` table. Mitigated by duplicate-prevention search + PATCH (not atomic in GitHub, but unlikely in practice for SDD's serial-per-Issue pipeline).

**Cross-reference**:
- design creation: `stage/design.md` §5
- parent pause: `stage/implement.md` §10 ("Parent Issue (has children)")
- child completion: `stage/implement.md` §11 ("Phase 7"), `stage/test.md` §11 ("Phase 5")

---

## 3. Sandbox + Permission Heuristic Bypass [PRESERVE — UNSUPPRESSIBLE]

**Concern**: certain Claude Code argument heuristics cannot be auto-approved via `permissions.allow`, `--dangerously-skip-permissions`, or `sandbox.enabled = false`. They break unattended `/sdd auto`/`/sdd batch` runs.

**Unsuppressible heuristics** [PRESERVE]:

| Heuristic | Trigger | Workaround |
|---|---|---|
| "Quoted variable expansion obfuscation" | `"...${VAR}..."` in args | Substitute literal before Bash call |
| "Newline + `#` in quoted arg" | Multi-line markdown in `--body "..."` | Write tool → temp file → `--body-file` |
| "Recursive broad search" | `find /`, `find ~`, `find /Users` | Use Grep/Glob tools instead |
| "Compound command" | `&&`, `\|\|`, `;`, `\|`, `$(...)`, etc. | Sequential Bash calls, observe + inline |
| `dangerouslyDisableSandbox: true` confirmation | TLS-proxy environments | `/sdd auto` sandbox toggle (Phase 3.1 step 5) — requires restart |

**Workarounds documented**:
- Bash rules: `00-common-contracts.md` §8
- Comment posting temp-file pattern: `00-common-contracts.md` §9
- Sandbox toggle flow: `01-config.md` §4
- `--dangerously-skip-permissions` companion flag: `01-config.md` §4

[PRESERVE: every constraint exists because of a Claude Code safeguard. None negotiable.]
[RETHINK: sandbox-toggle UX (~190 lines in `auto.md` Phase 3.1) is heavy. Investigate if Claude Code offers a per-tool bypass.]

---

## 4. Billing Pool Split (2026-06-15) [PRESERVE]

**Concern**: Claude Code split billing pools — `claude -p` moved to a metered Agent SDK Credit pool; interactive sessions stay on subscription pool.

**Consequence**:
- `/sdd batch` (uses `claude -p` subprocesses) → metered pool, charged at API list prices, no rollover
- `/sdd auto` (in-session loop) → stays on subscription pool

**User-facing impact**: heuristic for choosing between auto and batch.

| Use case | Recommended |
|---|---|
| Watching progress, small queue, interactive billing | `/sdd auto` |
| Large queue, walk-away, accept metered billing | `/sdd batch` |

**Cross-reference**: `flow/auto.md` §1, `flow/batch.md` §1.

[PRESERVE: documented user-facing trade-off.]
[RETHINK: if Anthropic merges pools again or changes policy, this distinction may become moot. Auto/batch unification candidate.]

---

## 5. Depth Labels [PRESERVE]

**Per-Issue dial**: `sdd:review:deep` (force opus) or `sdd:review:shallow` (cheaper models).

**Effects across stages** [PRESERVE]:
- Reviewer model assignment (all 4 stages)
- Preflight tier (Light/Medium/Heavy/Code-focused)
- `/code-review` effort (`medium`/`high`/`max`)
- `/security-review` skip (shallow only)
- `/verify` skip (shallow only)

**Single source of truth**: `_review_helpers.md` Section A.2 (canonical model table).

[PRESERVE: dollar-impacting; preserve exact mapping.]
[IMPROVE: depth-label table duplicated in every orchestrator's Phase 0. DRY candidate.]

---

## 6. In-Place Marker Updates [RETHINK]

**Concern**: review comments share a single marker per role per Issue/PR (e.g. `<!-- sdd:review:analyze:completeness -->`). Round 2/3 retries **overwrite** the round-1 body via PATCH.

**Audit trail loss**: prior-round content is gone from GitHub after the next round posts. Only the latest round is observable.

**Mitigation in current SDD**:
- Each round's atom self-fetches the latest comment → reconstructs context from there
- Findings JSON includes `round` field, but the comment-level audit is lost

**Round-aware marker candidate** [RETHINK]:
- Append `:r{N}` suffix to retain rounds (e.g. `<!-- sdd:review:analyze:completeness:r2 -->`)
- Cost: every round = new comment; Issue grows comments
- Benefit: full audit, no overwrite

**Decision deferred to design phase**. Both have trade-offs.

**Cross-reference**: `00-common-contracts.md` §4 ("Update-in-place invariant"), this file §6.

---

## 7. Recovery from Interruption [PRESERVE]

**Hard kill (Cmd-Q / terminal close / kernel)**:

| Artifact | State after kill | Recovery |
|---|---|---|
| `.github/.sdd-config` | Temporary skip-review write left in place | `mv .github/.sdd-config.bak .github/.sdd-config` (manual) |
| `.github/.sdd-config.bak` | Backup persists | Used by manual recovery above |
| GitHub state | Last successful write persists | re-run `/sdd resume <N>` — dispatcher reads current label/comments |
| Branch | If implement_plan ran, branch exists | normal git state |
| PR | If created, PR exists | open PR is recoverable |
| `<SETTINGS_PATH>.sdd-auto.bak` (sandbox) | Persists intentionally | User restores manually via `mv` |
| `.github/.sdd-batch.sh` | Persists if batch died | bash's trap should have cleaned; if not, `rm` |
| `.github/.sdd-batch-logs/*.log` | Persists for audit | normal |

**Soft cleanup (auto.md Phase 3.4 / batch.md trap)**:
- Restores `.sdd-config` from `.bak`
- Removes `.sdd-batch.sh` (batch)
- Re-reads sandbox state, warns if disabled

**Cross-reference**: `flow/auto.md` §9, `flow/batch.md` §6.

[PRESERVE: recovery contract is documented in user-visible recovery hints.]

---

## 8. Skip-Review Semantics — Multi-Stage Cascade [PRESERVE — subtle]

**Critical invariant**: skip-review skips the **user confirmation gate**, NOT the **AI review loop**. AI review always runs.

**Cascade effect** [PRESERVE]: when `analyze` is in skip-review AND analyze AI review passes, the orchestrator **auto-proceeds** to `design.md` inline (no user trigger). Same chain:
- `analyze` skipped → auto-advance to `design.md`
- `design` skipped → auto-advance to `implement.md`
- `implement` (plan gate only) skipped → auto-advance to TDD pipeline (which has no user gates)
- `pr` (PR Final gate) skipped → auto-advance to label `sdd:test`. If `qa` also skipped → auto-advance to `test.md`

**Auto/batch use both skipped** for unattended runs. Auto adds `qa` too (`flow/auto.md` §5).

**Common error pattern** [RETHINK]: users add `skip-review: analyze` expecting AI review also skipped. The docs/UI never made this explicit until later versions. Consider clearer key naming (e.g. `skip-confirm:` instead of `skip-review:`).

**Cross-reference**: `01-config.md` §2, `stage/analyze.md`, `stage/design.md`, etc.

---

## 9. Retry Mode — Atom Self-Fetch [PRESERVE]

**Trigger**: orchestrator passes literal string `"retry"` to atom slot.

**Slot positions** [PRESERVE]:
- `analyze_work`, `design_work`, `test_work`: `$2 = "retry"`
- `implement_red/green/refactor/e2e`: `$3 = "retry"`
- `implement_pr`: `$3 = "retry"`

**Atom behavior** [PRESERVE]:
- Empty/absent slot → first round; do not self-fetch
- Literal `"retry"` → execute `_review_helpers.md` Section C
- Anything else → return `FAIL: unrecognized retry slot value: <truncated>` (prevents silent context loss from legacy callers pre-v0.36)

**Why atom-side fetch** [PRESERVE]: orchestrator runs in main session; pre-fetching review comments would accumulate main-session context. Atom-side fetch confines that token weight to the atom's own context.

**Cross-reference**: `00-common-contracts.md` §7, `_review_helpers.md` Section C.

---

## 10. GitHub API Eventual Consistency [PRESERVE]

**Concern**: PATCH to a comment may take seconds to propagate. A retry-mode atom fetching the just-updated comment may see stale body.

**Mitigation** [PRESERVE]:
- Orchestrator waits for all reviewer atoms' `>>> RESULT <<<` before spawning retry work atom — GitHub's eventual-consistency window has elapsed in practice by then.
- No active retry-on-stale is required.

**Failure mode if violated**: retry atom addresses round-1 findings instead of round-2 findings. Detected by subsequent round AI review (will re-flag same findings).

**Cross-reference**: `_review_helpers.md` Section C.4.

[PRESERVE: empirical observation; mitigation is timing-based and works in practice.]

---

## 11. Single-Level Spawn Rule [PRESERVE — platform constraint]

**Claude Code architectural rule**: atoms (sub-agents) cannot spawn other sub-agents via Agent tool.

**Consequence**:
- All Agent calls happen in **orchestrator layer** (current architecture: main session reads orchestrator inline)
- Rewrite "stage-as-subagent" must inline atom logic — no nested spawns
- Review parallelism (3 parallel reviewers) survives only when spawn happens at orchestrator level

**Cross-reference**: `00-common-contracts.md` §12.

[PRESERVE: platform constraint, not negotiable.]
[RETHINK: if Claude Code adds 2-level spawning, Arch B can re-enable inner parallelism — design phase migration path.]

---

## 12. Skill Tool in Sub-agents [VERIFIED]

**Empirically confirmed** (R5 spike): `general-purpose` Agent type CAN invoke Skill tool. `/code-review`, `/security-review`, `/verify`, `/simplify` all reachable.

**Exception**: skills flagged as UI-only (`/help`) return semantic error — not a sub-agent restriction.

**Implication for rewrite**: Skill invocations can move INSIDE stage sub-agents, removing them from main session context.

**Cross-reference**: `00-common-contracts.md` §13.

[VERIFIED: design freedom available.]

---

## 13. Step 0 Preflight Skip on Retry [PRESERVE]

**Concern**: every work atom has a Step 0 preflight context discovery (project conventions, commit message style, similar PRs, target dir survey). This is ~30K tokens of context per round.

**Behavior** [PRESERVE]: work atoms **SKIP Step 0** entirely on round 2+ retries. Round-1 context is retained in atom's reasoning context (via round-1 `<details>` self-review trace which round-2 can re-read).

**Detection**: orchestrators signal retry by presence of `$2` (or `$3` for implement_pr). Atom checks slot.

**Cross-reference**: `_preflight.md` Section E.

[PRESERVE: ~30K tokens × 2 retries = ~60K tokens saved per failed stage. Material.]

---

## 14. Bash Heuristic Cheat Sheet [PRESERVE — load-bearing]

Quick reference (full in `00-common-contracts.md` §8):

**FORBIDDEN inside a single Bash tool call**:
1. `&&`, `||`, `;`, `|` (compound)
2. `VAR=$(...)`, inline `$(...)` (command substitution)
3. Subshells `(...)`, groups `{...}`
4. Process substitution `<(...)`, `>(...)`
5. Output redirection `> file`, `2>/dev/null`, `2>&1`, `&> file`
6. `"...${VAR}..."` / `"...$VAR..."` inside quoted args (UNSUPPRESSIBLE)
7. `find` outside repo root, including `~`, `/`, `/Users`, `/private` (UNSUPPRESSIBLE)
8. Multi-line heredoc wrapping multiple commands
9. Unresolved doc placeholders (`<<SKILL_DIR>>`, `<owner>/<repo>`, `<N>`, `$1`, `$2`)

**Multi-line markdown bodies**: use Write tool + `--body-file <path>` (UNSUPPRESSIBLE if inline).

[PRESERVE: every rule exists because of a real heuristic.]

---

## 15. Issue vs PR Validation [PRESERVE]

**Pre-flight check** for all stage commands:
```bash
gh issue view $1 --json url --jq .url
```

- Empty/error → does not exist → stop, report
- URL contains `/issues/` → valid Issue
- URL contains `/pull/` → PR, not Issue → stop immediately, do NOT modify state

**Why this matters**: GitHub Issues and PRs share the same `/issues/<N>/comments` API endpoint. Same number can refer to different things. Easy to corrupt PR state if /sdd applied accidentally.

**Cross-reference**: `00-common-contracts.md` §10.

[PRESERVE: defensive.]

---

## 16. Owner/Repo Resolution Discipline [PRESERVE]

**Mandatory derivation**:
```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

**Forbidden sources** [PRESERVE]:
- `git config user.name` (user identity, NOT repo owner)
- System prompt's "Git user" field
- Commit authors
- Environment variables

**Failure mode if violated**: requests hit a wrong repository where the same Issue/PR number may refer to entirely unrelated content.

**Cross-reference**: `00-common-contracts.md` §11.

[PRESERVE: defensive; pure-defensive contract.]

---

## 17. Duplicate-Prevention Pattern [PRESERVE]

**Every comment-posting atom** follows this discipline:

1. Write tool renders body to `/tmp/sdd-<marker>-<id>.md`
2. Search for existing comment with the marker:
   ```bash
   gh api repos/<owner>/<repo>/issues/<N>/comments --jq '.[] | select(.body | contains("<MARKER>")) | .id'
   ```
3. Empty result → create new (`gh issue comment <N> --body-file <path>`)
4. Has id → update in place (`gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@<path>`)

**Marker matching invariant** [PRESERVE]: exact substring INCLUDING leading `<!-- ` and trailing ` -->`. Prevents `step-1` matching `step-10`.

**Exception**: `/sdd rollback` intentionally accumulates `<!-- sdd:rollback -->` comments (per-event audit log).

**Cross-reference**: `_review_helpers.md` Section F.2, `00-common-contracts.md` §9.

[PRESERVE: load-bearing pattern.]

---

## 18. AI Review Always Runs [PRESERVE — common misunderstanding]

skip-review keys (`analyze`, `design`, `implement`, `pr`, `qa`) skip the **user confirmation gate**. AI review (3 parallel reviewers + escalation gate) **always runs**.

In skip-review mode, Round 3 escalation auto-continues with findings persisted to Issue/PR. Interactive mode asks user (Continue/Pause/Stop).

**Common misconception**: setting `skip-review: analyze` will skip the analyze AI review. False.

[PRESERVE — load-bearing]: `skip-review:` is the literal key users have in their `.github/.sdd-config` file. Renaming requires breaking change + dual-read shim.
[RETHINK — for rewrite design]: the semantic mismatch ("skip-review" suggests skipping AI review, but it only skips user confirmation) is a real source of misunderstanding. Candidate rename: `skip-confirm:`. Requires user-decision + dual-read shim release. Decision deferred. (Was [IMPROVE] in v1; corrected per Reviewer C TAG-C10.)

---

## 19. Adversarial Single-FAIL Escalation [PRESERVE]

**Pattern observed in every stage** [PRESERVE]:
- All 3 reviewers PASS → reviews passed
- Any reviewer FAIL → reviews failed
- **Special case**: adversarial alone FAIL, others PASS → log warning to user "⚠ Adversarial reviewer alone identified critical/major issues. Surfacing for awareness." Then continue as if failed (treated as failure for verdict).

**Cross-reference**: `stage/analyze.md` Step 1.2, `stage/design.md`, `stage/implement.md` 5.1.1, `stage/test.md` 2.1.2.

[PRESERVE: behavior is to surface adversarial dissent prominently.]

---

## 20. Version Sync Requirement (plugin.json + marketplace.json) [PRESERVE]

**CLAUDE.md rule**:
> When changing a plugin's version, always update BOTH files together:
> - `plugins/<plugin-name>/.claude-plugin/plugin.json`
> - `.claude-plugin/marketplace.json` (해당 plugin의 version 필드)

**Current state (Phase A discovery)**: drift detected — `plugin.json` 0.36.0 vs `marketplace.json` 0.35.0. Likely from v0.36.0 release commit missing the marketplace.json bump.

[PRESERVE: rule. Active bug to fix outside Phase A.]

---

## 21. ai-review-*.md Files Role [PRESERVE — verified]

**Files**: 14 files under `commands/` matching `ai-review-*.md` (analyze/design/implement/test × completeness/quality/adversarial = 12, plus implement-step and parent-integration = 14 total).

**Role** [PRESERVE]: NOT atoms. NOT vestigial. They are **role-specific rubric/criteria documents** referenced by reviewer atoms (e.g. `analyze_review.md` reads `ai-review-analyze-completeness.md` for the completeness rubric).

**Mapping**: see `spec/utilities.md` §7 for the canonical reviewer-atom → rubric-file table.

[IMPROVE: file location (`commands/`) is misleading — they're not user-invocable commands. Suggest `commands/rubrics/` or `atoms/rubrics/`.]

---

## 22. Step Counts and Retry Budgets — Summary Table [PRESERVE]

| Loop | Max rounds | Retry feedback source |
|---|---|---|
| analyze AI Review | 3 | sdd:review:analyze:{completeness,quality,adversarial} |
| design AI Review | 3 | sdd:review:design:{...} |
| implement TDD step (each of 4 steps) | 2 retries per step (3 attempts) | sdd:review:implement:step-{1..4} |
| implement PR Final | 3 | sdd:review:implement:{...} + /code-review + /security-review |
| test AI Review | 3 | sdd:review:test:{...} (+sdd:review:parent for parent path) |

After max → escalation gate (skip-review auto-continues, else user gate).

**Cross-reference**: `00-common-contracts.md` §7.

[PRESERVE: budget values are visible to users via stage docs.]

---

## 23. Branch Protection / Force-Push Prohibition [PRESERVE — load-bearing]

**Rule** [PRESERVE]: `implement_pr` retry mode pushes new commits to existing PR branch. **No force-push. No amend.**

**Rationale**: preserves PR review history, GitHub PR conversations, CI runs.

**Cross-reference**: `stage/implement.md` Phase 5.N.0, `implement_pr.md` retry mode.

[PRESERVE: invariant.]

---

## 24. /code-review and /security-review Ordering [PRESERVE]

**Constraint** [PRESERVE]: the Skill tool invocation **cannot** be in the same parallel batch as Agent tool calls. The orchestrator must serialize:
1. Spawn 3 parallel SDD reviewers (Agent tool, parallel)
2. Wait for all 3 results
3. Invoke `/code-review` Skill (serial)
4. Invoke `/security-review` Skill (serial, skip on shallow)
5. Post tools-summary comment

**Rationale**: Claude Code limitation — mixing Skill + Agent in one batch fails.

**Cross-reference**: `stage/implement.md` §7, `implement.md` Phase 5.1.2.

[PRESERVE: platform constraint.]

---

## 25. Skill-induced Premature end_turn (B1) [PRESERVE — load-bearing]

### Pattern

Sub-agents (`stage_implement`, `stage_test`) reliably stop with `stop_reason=end_turn` immediately after a Skill invocation (`/code-review`, `/security-review`, `/verify`), BEFORE emitting the remaining substantive steps (tools-summary marker, verdict, `>>> RESULT <<<` contract line).

### Empirical evidence (word_app 2026-06-15 session)

**Phase 1 — natural runs (4/4 failure):**

| Sub-agent | Tokens | Last assistant text | stop_reason |
|---|---|---|---|
| stage_implement #832 | 146k | `## Security Review / # No Security Findings` | `end_turn` |
| stage_test #832 | 111k | `/verify` skill preamble (Base directory + how-to text) | `end_turn` |
| stage_implement #836 | 196k | `# Security Review Report / ## Scope` | `end_turn` |
| stage_implement #866 | 151k | `/code-review` result text (deletion-only diff analysis) | `end_turn` |

Successful agents (e.g. #836 stage_test, 112k tokens) wrote an explicit summary + `>>> RESULT <<<` line after the Skill returned and stopped only AFTER emitting the contract.

**Phase 2 — controlled A/B against modified atom (with prompt-level guard inserted in §4.5.1 / §7.1):**

| Verification run | Tokens | Last assistant text | stop_reason | RESULT emitted |
|---|---|---|---|---|
| verify-1 (PR #869 dry-run) | 80k | `# Security Review — PR #869 / ## Analysis ...` | `end_turn` | No |
| verify-2 (PR #869 dry-run) | 71k | `/code-review` multi-angle finder + `findings: []` | `end_turn` | No |

Combined: **N=7/7 failure** under both natural and guard-augmented conditions. Token-budget exhaustion ruled out (all stops voluntary `end_turn` at 71k-196k, well below limits and overlapping with successful-agent distribution at 78k-135k).

### Root cause

Skill output is "report-style" — comprehensive, terminal-looking. The model interprets the Skill's deliverable as the stage's deliverable and emits `end_turn` rather than continuing the workflow. The interpretation triggers regardless of Skill output size (verify-2 stopped after a 1-line `findings: []` from `/code-review`) and regardless of explicit in-prompt reminders that further steps remain.

### Mitigation evaluation

| Layer | Approach | Empirical result | Status |
|---|---|---|---|
| 1 — Atom-level prompt guard (`_pr_final.md` §4.5.1, `stage_test.md` §7.1) | Explicit post-Skill checklist reminding the agent that Skill output is input data | 0/2 efficacy in verify-1/2 (same failure pattern as natural runs) | **Removed in v1.1.0 post-verification** |
| 2 — Wrapper-level auto-recovery (`commands/implement.md` and `commands/test.md` Unknown / malformed branches) | Probe GitHub state (PR existence + reviewer PASS verdicts + test:output marker) and synthesize the missing closing steps when probe succeeds | Works deterministically — main session is not subject to B1 | **Active in v1.1.0 — sole effective mitigation** |
| 3 (future) — Atom structural split | Split PR Final into two sub-agent invocations: `_pr_final_reviewers.md` (Skills + verdict input collection) → main session synthesizes `_pr_final_verdict.md` invocation with explicit "you have NO Skills left to run, only emit marker + verdict + RESULT" context | Untested | **Recommended next iteration if v1.1.0 auto-recovery activation rate is high** |

### Recommended monitoring

If wrapper auto-recovery activates (logged as `⚠ Sub-agent dropped the >>> RESULT <<< contract line`), surface this in operator telemetry. Under v1.1.0 the activation rate is expected to be high — Phase 1+2 evidence projects ~100% activation for PR Final and ~50%+ for test stage. Repeated activations are an observability signal of a known, mitigated condition — not an error to triage per occurrence. Aggregate activation count over time to detect drift in either direction (model improvement → lower rate, or regression → consider layer 3).

**Cross-reference**: `commands/implement.md` Phase 2 Unknown branch (auto-recovery), `commands/test.md` Phase 2 Unknown branch (auto-recovery), `spec/00-common-contracts.md` §6 FAIL reason prefix convention.

[PRESERVE — empirically characterized; layer 2 mitigation in place per sdd-plugin v1.1.0.]

---

## Notes on RETHINK items

The following items are candidates for design-phase discussion (not Phase A decisions):

1. **§4 Billing pool split** — auto/batch unification candidate
2. **§6 In-place marker updates** — round-aware markers vs current overwrite
3. **§8 Skip-review naming** — rename to `skip-confirm:` for clarity
4. **§21 ai-review-*.md location** — move to subdir

These will be revisited in the design phase. Phase A only catalogs.
