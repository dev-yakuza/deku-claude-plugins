# 00 — Common Contracts

Cross-cutting contracts every stage / atom / orchestrator depends on. Sources: `SKILL.md`, `atoms/_review_helpers.md`, `atoms/_preflight.md`, `atoms/_test_evidence.md`.

---

## 1. Stage Flow [PRESERVE]

Linear pipeline driven by GitHub label transitions:

```
(no label) → sdd:analyze → sdd:design → sdd:implement → sdd:test → sdd:done
                                                                  ↑
                                                          sdd:child (orthogonal)
```

- Each stage's exit condition is a label transition (or sdd:done close).
- `sdd:child` is orthogonal — marks a child Issue spawned by a parent's `design`; appears alongside the lifecycle label.
- Parent Issues stop at `sdd:implement` after `design` creates children. Children progress independently; parent advances to `sdd:test` when all children reach `sdd:done`.

**Rewrite note**: [PRESERVE] label names (`sdd:analyze`, `sdd:design`, ...) are external GitHub-visible contracts — users write automation/filters against them. Renaming requires a dual-read shim release + explicit migration. The **linear progression and the parent-pause invariant** are equally PRESERVE. (Was [IMPROVE] in v1; corrected per Reviewer C TAG-C1.)

---

## 2. GitHub State Model [PRESERVE]

The system has **no in-process FSM**. All state lives on GitHub:

| State | Where | Set by |
|---|---|---|
| Current stage | Issue label `sdd:<stage>` | Orchestrator on exit of each stage |
| Stage output | Issue comment `<!-- sdd:<stage>:output -->` | Work atom |
| Stage review verdict | Issue/PR comment `<!-- sdd:review:<stage>:<role> -->` | Review atom |
| Children list (parent only) | Issue comment `<!-- sdd:children:output -->` | `design_work` atom |
| Parent reference (child only) | Issue body `<!-- sdd:child-issue -->` block with `Parent Issue: #N` | `design_work` atom (multilingual — see 02-multilingual.md) |
| TDD plan | Issue comment `<!-- sdd:implement:plan -->` | `implement_plan` atom |
| TDD step review | Issue comment `<!-- sdd:review:implement:step-<n> -->` | `tdd_step_review` atom |
| Raw test output | Issue comment `<!-- sdd:test-evidence:step-<n> -->` | `implement_<step>` work atom |
| PR Final tools summary | PR comment `<!-- sdd:review:implement:tools -->` | `implement.md` Phase 5 (per-round) |
| Cross-stage parent integration review | Parent Issue comment `<!-- sdd:review:parent -->` | `parent_integration_review` atom |
| Rollback notice | Issue comment `<!-- sdd:rollback -->` | `/sdd rollback` |

**Rewrite note**: [PRESERVE] marker substrings are external contracts — orchestrators match them via `gh api ... contains("sdd:analyze:output")` and external scripts may parse them too. Inconsistent grammar (singular `output` vs role-suffixed vs step-numbered) is a known wart but **renaming requires dual-read shim**. If unified grammar is adopted in rewrite, old markers must be readable for at least one release. (Was [IMPROVE] in v1; corrected per Reviewer C TAG-C2.)

---

## 3. Label Inventory [PRESERVE]

### Lifecycle labels (mutually exclusive within an Issue)
- `sdd:analyze` — analyze stage active
- `sdd:design` — design stage active
- `sdd:implement` — implement stage active (or parent paused after children created)
- `sdd:test` — test stage active
- `sdd:done` — pipeline complete (Issue closed)

### Orthogonal labels
- `sdd:child` — Issue was spawned by a parent's design
- `sdd:review:deep` — force all reviewers to Opus, Heavy tier preflight, `/code-review` effort `max`
- `sdd:review:shallow` — cheaper models, Light tier preflight, skip `/security-review`, `/code-review` effort `medium`

**Rewrite note**: [PRESERVE] `sdd:review:deep` and `sdd:review:shallow` are GitHub labels users apply by hand and reference in their automation. Both the label names AND the 3-tier dial are external contracts. Rename requires dual-read shim. (Was [IMPROVE] in v1; corrected per Reviewer C TAG-C3.)

---

## 4. Marker Inventory [PRESERVE]

| Marker | Scope | Posted by |
|---|---|---|
| `<!-- sdd:analyze:output -->` | Issue comment | `analyze_work` |
| `<!-- sdd:design:output -->` | Issue comment | `design_work` |
| `<!-- sdd:children:output -->` | Parent Issue comment | `design_work` |
| `<!-- sdd:child-issue -->` | New child Issue body | `design_work` |
| `<!-- sdd:implement:plan -->` | Issue comment | `implement_plan` |
| `<!-- sdd:test:output -->` | Issue comment | `test_work` |
| `<!-- sdd:review:<stage>:<role> -->` | Issue (or PR for implement PR Final) | review atoms |
| `<!-- sdd:review:implement:step-<n> -->` | Issue comment | `tdd_step_review` |
| `<!-- sdd:test-evidence:step-<n> -->` | Issue comment | `implement_<step>` |
| `<!-- sdd:review:implement:tools -->` | PR comment | `implement.md` Phase 5 |
| `<!-- sdd:review:parent -->` | Parent Issue comment | `parent_integration_review` |
| `<!-- sdd:findings:json -->` … `<!-- /sdd:findings:json -->` | Inside any review comment | review atoms |
| `<!-- sdd:rollback -->` | Issue comment | `/sdd rollback` |

**Marker matching invariant** [PRESERVE]: exact substring match **including** leading `<!-- ` and trailing ` -->`. Prevents prefix collisions (e.g. `step-1` matching `step-10`).

**Update-in-place invariant** [PRESERVE]: duplicate-prevention pattern (Section F.2) means the same marker exists at most once per Issue/PR (latest version). Round-to-round retries overwrite, **not append**. Consequence: prior-round content is lost from GitHub once the new round posts. [RETHINK: should rounds be preserved for audit? Consider round-suffixed markers `:r1/:r2/:r3` or append-only.]

---

## 5. Findings JSON Schema [PRESERVE]

Every review atom embeds inside its posted comment:

```
<!-- sdd:findings:json -->
```json
{
  "stage":   "analyze" | "design" | "implement" | "test" | "parent",
  "role":    "completeness" | "quality" | "adversarial" | "step-<N>" | "parent-integration" | "tools-summary",
  "issue":   <number>,
  "pr":      <number> | null,
  "round":   <number> | null,
  "verdict": "PASS" | "FAIL" | null,
  "model":   "opus" | "sonnet" | "haiku" | null,
  "findings": [
    {
      "severity":       "critical" | "major" | "minor",
      "file":           "<path>" | null,
      "line":           <number> | null,
      "rule_id":        "<short-kebab-case-id>",
      "description":    "<one-line summary>",
      "fix_suggestion": "<one-line suggestion>" | null
    }
  ],
  "suggestions":  ["<one-line suggestion>", ...],
  "tools_run":    ["<skill-name>", ...] | null,
  "tools_skipped":[{"name": "<skill-name>", "reason": "skill-unavailable" | "shallow-label-skip" | "<other>"}] | null
}
```
<!-- /sdd:findings:json -->
```

### Verdict rule [PRESERVE]
- Any `critical` or `major` finding → `verdict = "FAIL"`
- Otherwise → `verdict = "PASS"`

### Role-specific field usage [PRESERVE]
- `completeness` / `quality` / `adversarial` / `step-<N>` / `parent-integration`: use `verdict`, `model`, `findings`, `suggestions`. Omit `round`, `tools_run`, `tools_skipped`.
- `tools-summary`: use `round`, `tools_run`, `tools_skipped`. `verdict` and `model` `null`. `findings = []`.

**Rewrite note**: schema is workable. Add a `schema_version: 1` field to enable future evolution without breaking existing comments. [IMPROVE: schema versioning]

---

## 6. Sub-agent Result Contract [PRESERVE]

Every atom returns **exactly one line** prefixed by a sentinel:

```
>>> RESULT <<<
<status> <fields...>
```

Examples observed in source:
- `OK` — work atom success, no extra info
- `OK NO_ACTION` — analyze_work concluded the Issue needs no code change
- `OK SINGLE` / `OK CHILDREN: #A,#B,#C` — design_work output type
- `OK BRANCH: <branch-name>` — implement_plan success
- `OK <STEP_TYPE> COMMIT: <sha> TESTS: <p>/<t> FAILED: <f>` — TDD step
- `OK REFACTOR EMPTY` — refactor step found nothing to refactor
- `OK E2E_SKIPPED` — E2E not applicable
- `OK PR: #N` / `OK PR: #N E2E_SKIPPED` — implement_pr
- `OK SINGLE PR: #N` / `OK PARENT INTEGRATION_PR: #M` / `OK PARENT NO_INTEGRATION` — test_work
- `OK PASS` / `OK FAIL: <summary>` — review atom verdict
- `OK PASS PR: #N` / `OK FAIL PR: #N: <summary>` — implement review on PR
- `FAIL: <reason>` — atom-level error (orchestrator stops on this)

[PRESERVE — load-bearing]: the `>>> RESULT <<<` sentinel + literal status strings (`OK CHILDREN: #...`, `OK E2E_SKIPPED`, `OK PR: #N`, etc.) are parsed verbatim by orchestrators in dozens of call sites. Reformatting to JSON is a breaking change for every parser.

[RETHINK — for rewrite design]: candidate is single-line JSON after sentinel (`>>> RESULT <<<\n{"status":"OK","kind":"...","fields":{...}}`). Keeps grep-resistance; makes parsing deterministic. Requires concurrent migration of all parsers OR a parallel `>>> RESULT JSON <<<` sentinel during transition. (Was [IMPROVE] in v1; corrected per Reviewer C TAG-C4.)

---

## 7. Retry Mode Trigger [PRESERVE]

### Mechanism
- Orchestrator passes the literal string `"retry"` to the work atom's relevant slot:
  - `analyze_work`, `design_work`, `test_work`: `$2 = "retry"`
  - `implement_red/green/refactor/e2e`: `$3 = "retry"`
  - `implement_pr`: `$3 = "retry"`
- Atom self-fetches previous round's review markers from GitHub (Section C of `_review_helpers.md`).
- Atom must reject unrecognized slot values with `FAIL: unrecognized retry slot value: <truncated>` to prevent silent context loss from legacy callers (pre-v0.36).

### Round retry budgets [PRESERVE]
| Loop | Max rounds | Retry feedback source |
|---|---|---|
| analyze AI Review | 3 | sdd:review:analyze:{completeness,quality,adversarial} |
| design AI Review | 3 | sdd:review:design:{...} |
| implement TDD step (red/green/refactor/e2e) | 2 retries per step (3 attempts total) | sdd:review:implement:step-{1..4} |
| implement PR Final | 3 | sdd:review:implement:{...} + `/code-review` + `/security-review` inline PR comments |
| test AI Review | 3 | sdd:review:test:{...} (+sdd:review:parent for parent path) |

**After max rounds** → escalation gate. If skip-review for that stage is set → auto-continue with findings persisted on Issue/PR. Else → ask user.

---

## 8. Bash Command Execution Rules [PRESERVE — load-bearing]

Every Bash tool invocation MUST be a **single simple command** with NO:

| Forbidden | Reason |
|---|---|
| `&&`, `\|\|`, `;`, `\|` | compound — breaks `Bash(gh:*)` allow-pattern matching |
| `VAR=$(...)` / inline `$(...)` | command substitution — same as above |
| Subshells `(...)`, groups `{...}` | compound |
| Process substitution `<(...)`, `>(...)` | compound |
| `> file`, `2>/dev/null`, `2>&1`, `&> file` | output redirection heuristic |
| Multi-line heredoc wrapping multiple commands | compound |
| `"...${VAR}..."` or `"...$VAR..."` inside quoted args | "expansion obfuscation" heuristic — UNSUPPRESSIBLE by `permissions.allow`, `--dangerously-skip-permissions`, or `sandbox.enabled = false` |
| `find` against `/`, `/Users`, `/private`, `~`, `~/<anything>`, or any absolute path outside repo root | recursive-broad-search safeguard — UNSUPPRESSIBLE |
| Unresolved doc placeholders (`<<SKILL_DIR>>`, `<owner>/<repo>`, `<branch-name>`, `<N>`, `$1`, `$2`) | reach shell as literal text; fails or prompts |

### Chaining results between commands [PRESERVE]
1. Run first command → observe literal output from tool result.
2. Inline the **literal value** into the next command.

### Codebase exploration [PRESERVE]
Use **Grep / Glob / Read tools**, NOT Bash `find`/`grep`/`cat`/`head`/`tail`/`awk`/`sed`. These dedicated tools are bound to the working tree and don't trigger the safeguards.

**Rewrite note**: this rule set is verbose but every clause exists because of a real Claude Code argument heuristic. None can be relaxed. The rewrite should keep a single canonical version (not repeated in every orchestrator). [IMPROVE: DRY — one canonical reference, atoms link]

---

## 9. Comment Posting Pattern (mandatory) [PRESERVE — load-bearing]

Multi-line markdown bodies (every SDD comment) trip Claude Code's "newline + `#` inside quoted arg" heuristic. UNSUPPRESSIBLE by permission gates.

### Mandatory flow (Section F of `_review_helpers.md`)
1. **Write tool** renders body to `/tmp/sdd-<marker-stub>-<id>.md` (deterministic per-marker path).
2. Duplicate-prevention search via `gh api repos/<owner>/<repo>/issues/<N>/comments --jq '...'` for marker.
3. Branch:
   - Empty result → `gh issue comment <N> --body-file <path>` (or `gh pr comment <PR_NUM> ...`).
   - Has id → `gh api repos/<owner>/<repo>/issues/comments/<id> -X PATCH --field body=@<path>`.
4. (Optional) Verify by re-querying.

### Forbidden alternatives [PRESERVE]
- Inline `gh issue comment <N> --body "..."` with multi-line content
- Heredocs: `--body "$(cat <<EOF ... EOF)"`
- `echo "..." | gh ...` (pipe = compound)
- `printf '...' > /tmp/foo.md && gh ...` (compound)

### Deterministic temp file paths [PRESERVE]

| Marker | Path |
|---|---|
| `sdd:analyze:output` | `/tmp/sdd-analyze-output-$1.md` |
| `sdd:design:output` | `/tmp/sdd-design-output-$1.md` |
| `sdd:children:output` | `/tmp/sdd-children-output-$1.md` |
| `sdd:child-issue` (new child) | `/tmp/sdd-child-issue-$1-<seq>.md` |
| `sdd:implement:plan` | `/tmp/sdd-implement-plan-$1.md` |
| `sdd:test:output` | `/tmp/sdd-test-output-$1.md` |
| `sdd:review:<stage>:<role>` (Issue) | `/tmp/sdd-review-<stage>-<role>-$1.md` |
| `sdd:review:<stage>:<role>` (PR) | `/tmp/sdd-review-<stage>-<role>-pr<PR_NUM>.md` |
| `sdd:review:implement:step-<n>` | `/tmp/sdd-review-implement-step-<n>-$1.md` |
| `sdd:review:parent` | `/tmp/sdd-review-parent-$1.md` |
| `sdd:test-evidence:step-<n>` | `/tmp/sdd-test-evidence-$1-step-<n>.md` |

**Rewrite note**: temp file naming is consistent and good. Keep behavior; internal naming scheme is [IMPROVE] freedom.

### Source inconsistency note: `-F` vs `--field` [from Reviewer A GAP-A5]

Almost all atoms use `gh api ... -X PATCH --field body=@<path>`. **Exception**: `commands/atoms/implement_review.md` line 64 uses `gh api ... -X PATCH -F body=@<path>` (form-data flag). The `-F` and `--field` flags have different semantics in `gh api` — `-F` posts as form-encoded, `--field` posts as JSON-encoded.

**Rewrite directive**: standardize on `--field body=@<path>` across all atoms (canonical form per `_review_helpers.md` Section F.2 step 3). Audit existing `-F` callers. [IMPROVE — source bug to normalize.]

---

## 10. Issue Validation [PRESERVE]

Before any command that takes an Issue number:

```bash
gh issue view $1 --json url --jq .url
```

- Empty/error → does not exist → stop, report.
- URL contains `/issues/` → valid Issue → proceed.
- URL contains `/pull/` → PR, not Issue → stop immediately. Do NOT modify labels, post comments, create branches. Report:
  > Error: #$1 is a Pull Request, not an Issue. SDD commands operate on Issues only.

**Applies to**: every command taking an Issue number — `analyze`, `design`, `implement`, `test`, `resume`, `rollback`, `status`, `review`. Loop commands (`auto`, `batch`) validate per-Issue inside the loop.

---

## 11. Repository Owner/Repo Resolution [PRESERVE]

Required for every `gh api repos/<owner>/<repo>/...` call.

### Mandatory derivation
```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Inline the literal `<owner>/<repo>` (e.g. `deku-word-app/word_app`) into subsequent calls.

### Forbidden sources [PRESERVE]
- `git config user.name` — that's user identity, not repo owner
- System prompt's "Git user" field — same
- Commit authors
- Environment variables

Using these will hit a wrong repository with potentially overlapping Issue/PR numbers.

**Rewrite note**: this is a defensive contract. Keep as-is. [PRESERVE]

---

## 12. Sub-agent Spawning Rules [PRESERVE — architectural invariant]

### Single-level spawn (current)
- Main session reads orchestrator markdown → spawns atom sub-agents via Agent tool.
- Atoms **cannot** spawn other sub-agents (Claude Code architectural rule).
- All Agent calls happen in the orchestrator layer.

### Implication for rewrite
Arch B (stage-as-subagent) requires the **stage sub-agent** to inline the atom logic (no inner Agent calls). This serializes parallel reviews. Wall-clock penalty accepted for main-session token savings.

[PRESERVE: single-level rule is platform constraint, not negotiable]
[RETHINK: if Claude Code adds 2-level spawning in the future, Arch B can re-enable inner parallelism. Document this as a future migration path.]

---

## 13. Skill Tool Availability in Sub-agents [VERIFIED — see R5 spike]

Sub-agents (`general-purpose` Agent type) **CAN** invoke the Skill tool. Verified empirically: `/code-review` dispatches successfully from inside a sub-agent. `/security-review` and `/verify` are similarly reachable.

**Exception**: skills flagged as UI-only (e.g. `/help`) return a semantic error when invoked via the Skill tool. This is not a sub-agent restriction — same error occurs from main.

### Implication for rewrite
External Skill invocations (`/code-review`, `/security-review`, `/verify`) can move INSIDE stage sub-agents, removing them from the main session context. [PRESERVE: capability confirmed; design freedom available]

---

## Cross-references

- Marker conventions → §4
- JSON schema → §5
- Result contract → §6
- Retry semantics → §7
- Bash rules → §8
- Comment posting → §9

Detailed source: `plugins/sdd-plugin/skills/sdd/SKILL.md`, `commands/atoms/_review_helpers.md` Sections A-F.
