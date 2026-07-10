# HANDOFF & STATE (shared contract)

**Not a stage.** This file is the authoritative contract for (1) how Guild tracks development state on GitHub, (2) how stage outputs are persisted, and (3) how role agents hand off to each other within a stage. Read the section the calling file points to. (Guild's inter-role protocol — plan §18 A + §16 C4. Descends from sdd's GitHub state model and sub-agent contract.)

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. Codebase exploration uses Grep/Glob/Read.

---

## Section A — Stage progress state = GitHub labels

The single source of truth for "what stage is this Issue in" is its GitHub label. `/gld status` and `/gld resume` read these to decide the current stage.

| Label | Meaning | Set when |
|---|---|---|
| `guild:analyze` | analyze stage active / done | `/gld dev` starts, or analyze begins |
| `guild:design` | design stage active / done | analyze produced `OK ADVANCE: design` |
| `guild:execute` | execute (implement) stage active / done | design produced `OK ADVANCE: execute` |
| `guild:test` | test stage active / done | execute produced `OK ADVANCE: test` |
| `guild:qa` | QA stage active / done | test's verify gate passed → `OK ADVANCE: qa` |
| `guild:done` | Issue complete | QA gate passed |
| `guild:child` | this Issue is a child of a parent Issue | design split work into multiple PRs |

**Label transitions are the main session's responsibility only.** Stage sub-agents NEVER add/remove labels — they return a status line (Section C) and the main session (dev.md / the stage wrapper) applies the label. This keeps state changes centralized and auditable.

Transition rule: when a stage returns `OK ADVANCE: <next>`, the main session removes the current `guild:<stage>` label and adds `guild:<next>`. Labels are created by `/gld init`.

---

## Section B — Stage outputs = Issue comments + markers

Each stage persists its output as a GitHub Issue comment wrapped in a marker pair, so later stages (and `/gld resume`) can find it. Update-in-place: if a comment with the marker already exists, PATCH it rather than appending (per `_bash_rules.md` temp-file pattern).

| Marker | Produced by | Contents |
|---|---|---|
| `<!-- guild:analyze:output -->` … `<!-- /guild:analyze:output -->` | analyze (leader) | requirement analysis, work-type classification, assumptions/interpretations chosen at discuss gate |
| `<!-- guild:design:output -->` … `<!-- /guild:design:output -->` | design (tech-lead ∥ tester) | design summary, skeleton pointer, test-case pointer, PR split decision |
| `<!-- guild:test:output -->` … `<!-- /guild:test:output -->` | test (tester) | test run summary + verify gate outcome |
| `<!-- guild:test-evidence:step-<n> -->` … `<!-- /guild:test-evidence:step-<n> -->` | execute/test | raw test-runner output captured as verify evidence (Section E) |
| `<!-- guild:review:output -->` … `<!-- /guild:review:output -->` | review (fresh reviewer) | guided pair-review walkthrough (risk-weighted, rationale-backed). Posted to the PR only with `/gld review … --comment`; default is session-only. Also written to `docs/specs/<issue>/review.md`. |

**Durable design artifacts** (skeleton, architecture decisions, test cases) that outlive the Issue thread are also written to the working tree:
- `docs/specs/<issue>/` — design skeleton, notes, test-case list (committed with the PR).

This split follows plan §5: GitHub holds ephemeral stage state (①); `docs/` holds durable knowledge (②). The Issue comment is the index; `docs/specs/<issue>/` holds the detail passed **as files** between roles (never pasted into context).

---

## Section C — Role handoff (within a stage) = status enum + RESULT line

When one role hands off to another inside a stage — tech-lead → developer, tester → developer, developer → tech-lead for conformance — the handoff is a **file** (the artifact) plus a **return status**. A sub-agent spawned for a role returns EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. The line(s) before the sentinel may be narrative; the caller ignores everything until the sentinel.

**Status enum** (plan §18 A):

| Status | Meaning | Caller (leader) action |
|---|---|---|
| `DONE` | work complete, artifact written, no concerns | proceed to next role / stage |
| `DONE_WITH_CONCERNS: <one-line>` | complete but the role flags a risk worth surfacing | proceed, but record the concern in the stage output and surface to the human |
| `BLOCKED: <one-line>` | cannot proceed (missing dependency, contradiction) | leader intervenes: gather context, reassign, or escalate to human |
| `NEEDS_CONTEXT: <one-line>` | needs an input that should exist but wasn't found | leader supplies the missing artifact/pointer, then re-invokes the role |
| `FAIL: <reason>` | hard error (gh failure, Issue is a PR, etc.) | stop the stage; report to human |

**Artifacts are passed as files, not pasted** (plan §16 C4 — context protection). The producer writes to the working tree or `docs/specs/<issue>/`; the RESULT line names the path. The consumer reads that path. Never inline a skeleton or full test-case list into a RESULT line — keep RESULT to one summary line.

### RESULT line format

```
>>> RESULT <<<
DONE: <=1 line summary + artifact path
```

Examples:
```
>>> RESULT <<<
DONE: skeleton at docs/specs/42/skeleton.md — 3 modules, 2 seams for DI
```
```
>>> RESULT <<<
DONE_WITH_CONCERNS: tests written to docs/specs/42/test-cases.md; AC #3 is ambiguous about empty-list behavior
```
```
>>> RESULT <<<
BLOCKED: design output references an auth module that does not exist in this repo
```

---

## Section D — Stage-level return (stage → main session)

A stage wrapper (analyze/design/implement/test) returns one line to the main session (dev.md or the direct-invocation command). This drives the Section A label transition.

| Return | Meaning | Main session action |
|---|---|---|
| `OK ADVANCE: <next-stage>` | stage complete, advance | transition label to `guild:<next-stage>` |
| `OK DONE` | qa's gate passed (after test's verify gate) | transition to `guild:done`, close if appropriate |
| `OK PAUSE: <one-line>` | leader/human chose to stop here | leave label as-is; report |
| `NEEDS_HUMAN: <one-line>` | a discuss/verify gate needs a human decision | main session prompts the human (`AskUserQuestion`), then resumes |
| `FAIL: <reason>` | hard error | stop; report |

`<next-stage>` values: `analyze → design → execute → test → qa → done`.

**Sub-agents never call `AskUserQuestion`** (they are non-interactive). A gate that needs a human decision returns `NEEDS_HUMAN:` and the main session runs the interactive prompt. In M1, the human is also the external reviewer (plan §18 A: "M1의 독립 리뷰어 = 사람"), so `NEEDS_HUMAN` at the discuss/verify gates is the primary human-in-the-loop point.

---

## Section E — Test evidence capture (verify gate concrete impl)

The **verify gate** (plan §4, §18 B) is implemented as evidence capture: whenever a test runner is executed during execute or test, capture the **raw runner output** and cross-check it against any self-reported pass/fail claim. This prevents an agent from claiming "tests pass" without proof (plan §18 B — "자기보고를 원문과 대조").

Procedure:
1. Run the project's test command (from `config.json` `commands.test` / conventions) as a simple Bash call. **Commands are pre-normalized** (`scan_repo.md` Section 2): a value is either a simple string or an **array** of simple steps. Run each array element as its **own** Bash call in order — never join them with `&&`. The stored form never contains `$(...)`/`&&`/`|`; if you encounter a raw compound command from an older install, split it yourself and drop any `$(...)` flag before running.
2. Capture the raw tail of the output (the runner's own summary line, e.g. `Tests: 12 passed, 0 failed`).
3. Write it to an Issue comment under `<!-- guild:test-evidence:step-<n> -->` via the temp-file pattern.
4. In any narrative claim ("all tests green"), the claim MUST be backed by the captured raw line. If the self-report and the raw output disagree, the raw output wins and the stage returns `BLOCKED`/`FAIL`.
5. **Honesty of scope**: the verify output must also state what was **NOT** run — in M1, `commands.e2e` (integration/E2E) is detected but not auto-run, and manual/visual QA is the human's step (plan §18 B). "verify passed" means *automated-test verification*, never "fully QA'd." Do not imply full QA.

This is a hard requirement in M1 (no separate AI verify reviewer exists yet — the raw-output cross-check IS the verify gate). Honesty covers both directions: don't overstate results (claim vs raw), and don't overstate coverage (what ran vs what didn't).

---

## Section F — Owner/repo resolution

Obtain `<owner>/<repo>` once per command via its own Bash call, then inline the literal value everywhere it is needed:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Never infer owner/repo from the git user, the system prompt, or path names. If the command fails (non-GitHub remote), Guild's GitHub-backed state is unavailable — report and stop (M1 requires a GitHub repo).

---

## Section G — Roster & participation model (who works on a task)

`/gld init` installs the **full roster of 16 roles** into `.claude/agents/` (plan §18 D). Installing everyone is cheap; what varies per task is **who participates**. The leader (embodied by the main session — `leader.md`) assembles the cast from the roster using work-type + risk + charter. There are **three participation kinds**:

- **Stage role (always)** — lives on the spine; present in every task. Depth scales with the work (a one-line fix still passes through them, lightly). Never conditional.
- **Participation role (conditional join)** — the leader convenes it **only when the task's nature warrants** (e.g. a designer on a UI change). Not warranted → never spawned → zero token cost. This is how a 16-role roster stays cheap.
- **Gate role (conditional review)** — a **review check** the leader inserts *before advancing past a stage* when risk warrants (e.g. security review on auth/exposure changes). A gate role reviews **someone else's** output (external-auditor stance — it never self-reviews its own artifact; plan §9/§16). Some roles are both a participation role and a gate role (designer, security): they help build during the stage **and** provide the review check.

**The roster (16):**

| Role | Kind | Joins when | Stage(s) | Produces |
|---|---|---|---|---|
| leader | stage (embodied) | always | all | assembly, arbitration, gate rulings, completion judgment |
| tech-lead | stage | always | design (skeleton + tech direction) · execute (conformance check + loop-back) | skeleton, technical approach + architecture decisions, conformance verdict |
| developer | stage | always | execute | implementation |
| tester | stage | always | design (cases from AC) · test | test cases, verify-gate result |
| qa | stage | always (risk-based depth) | qa | holistic quality plan + result (exploratory/E2E/user-flow) |
| product-owner | participation | requirements need value-alignment / AC ownership / scope calls | analyze | aligned requirements, AC, priorities, non-goals |
| designer | participation **+ gate** | the change has UI/UX surface | design (UX design) · **UI/UX review gate** (built UI vs intent) | `docs/specs/<issue>/ux.md`; UI/UX review verdict |
| security | participation **+ gate** | auth / external exposure / secrets / sensitive data / input validation | design (threat modeling) · execute (review) · **security review gate** (adversarial diff review) | threat-model notes; security findings (with severity); gate verdict |
| infra | participation | CI/CD · deploy · env · IaC changes | execute | infra diff + rollback/verify notes |
| dba | participation | schema · migration · data-model · queries | design/execute | schema/migration change + integrity/rollback notes |
| i18n | participation | user-facing strings · multi-language · flavor/brand variants | design/execute | i18n keys · translations · sync notes |
| analytics | participation | event tracking · metrics · A/B · instrumentation | design/execute | instrumentation design · event definitions |
| performance | participation | hot path · rendering · memory · load · cost | design/execute | performance notes/measurements; regression guard |
| tech-writer | participation | doc-worthy change: ADR · README · user docs | design (ADR / doc plan) · execute (write docs vs implemented change) | ADR; doc draft/update (file) |
| release-manager | participation · **out of spine** | version bump · store/deploy · release notes · tagging | **after `done`** — a release event bundling many issues (not a `/gld dev` stage) | release prep (version · notes · tag) + checklist result |
| support-triage | participation · **out of spine** | raw user feedback/report needs refining into an issue | **before `analyze`** — intake (not a `/gld dev` stage) | refined issue draft (symptom · repro · AC · type label) |

**Out-of-spine roles** (`support-triage`, `release-manager`): these two are convened *around* the per-issue flow, not *inside* it. `support-triage` runs **before** `analyze` — it refines raw feedback into a well-formed Issue (intake), which then enters the spine normally. `release-manager` runs **after** `done` — at a **release event** that bundles many already-`done` Issues (version bump, notes, tagging). Neither is a stage in `/gld dev`; they have no wrapper step and are invoked by the leader/human at those boundary moments. They are in the roster so the leader *can* convene them, but they never appear inside the `analyze→…→qa→done` sequence.

**How roles hand off** is unchanged (Section C — status enum + `>>> RESULT <<<`, artifacts as files). Section G only answers *which* roles are in the cast; once convened, every role uses the same handoff contract. **A conditional role that is not convened produces nothing and is not spawned** — its absence is normal, not a gap.

**Leader assembly (authoritative logic lives in `leader.md` + `dev.md`)**: the leader reads the task (work-type label, diff/AC surface, hotspots) against charter priorities and (1) always runs the spine, (2) convenes the participation roles whose trigger matches, (3) inserts the gate reviews whose risk matches — then delegates via the Section C contract. Assembly decisions on large/risky tasks are surfaced to the human (HITL).
