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
| `guild:children` | this (parent) Issue is split; its children are being driven sequentially | design decided a multi-PR split (Section I) |

**Split parents do not run the spine themselves.** When design splits an Issue, the parent leaves the normal `analyze→…→done` track and enters `guild:children` — it is an *orchestration* state, not a stage. Its "execute/test/qa" is the sum of its children plus a final parent-integration check (Section I). A parent never carries both `guild:children` and a stage label at once.

**`guild:child` is a permanent identity marker, never removed.** Unlike every other row in the table above, `guild:child` is not itself a stage — it marks a child Issue's identity for its entire lifetime (added once at creation by `design.md`/`plan.md`, alongside its starting stage label `guild:analyze`; never removed by any later stage). A child Issue therefore always carries **two** `guild:*` labels at once: `guild:child` plus its actual current stage label — so "read current labels" at any stage's Step 0 returns a 2-element (not 1-element) array for a child. Every stage's transition ("remove whatever `guild:*` label Step 0 found, add the next one") must operate on the **stage** label only; stripping `guild:child` would silently drop the Issue out of Section I's `gh issue list --label guild:child` discovery query, breaking its parent's ability to find it. `design.md` additionally tracks this as `IS_LEAF` for its own leaf-only-split guard (Section I) — every other stage file just needs to leave the label untouched.

**Label transitions are the main session's responsibility only.** Stage sub-agents NEVER add/remove labels — they return a status line (Section C) and the main session (dev.md / the stage wrapper) applies the label. This keeps state changes centralized and auditable.

Transition rule: when a stage returns `OK ADVANCE: <next>`, the main session removes the current `guild:<stage>` label and adds `guild:<next>`. Labels are created by `/gld init`.

**`guild:needs-human` removal.** This label is *additive* to whatever `guild:<stage>` label the Issue already carries (Section H) — a paused Issue keeps its stage label and gains this one on top. It is added by the unattended-mode pause path; it must also be **removed** somewhere, or a resolved pause stays permanently mis-reported to `batch`/`monitoring`/`status`, which all poll it as a first-class state. There is exactly one removal point: **whenever the main session performs ANY successful forward-progress label transition on an Issue that currently carries `guild:needs-human`** — an `OK ADVANCE`/`OK SPLIT`/`OK DONE` after the human resolved the pause and a re-run/`resume` made real progress, whether the transition is between two spine stages (`guild:<stage>` → `guild:<next-stage>`) or into/out of the `guild:children` orchestration state (which Section A above already notes is *not itself* a stage, but still counts as forward progress) — remove `guild:needs-human` as part of that same transition. The advance itself is the evidence the pause was resolved:
```bash
gh issue edit <n> --remove-label "guild:execute" --add-label "guild:test" --remove-label "guild:needs-human"
```
Check the Issue's current labels first (already read at Step 0 of every stage — analyze/design/implement/debug/refactor/qa/test all read labels before deciding whether to add their entry label) and only include `--remove-label "guild:needs-human"` when it's actually present — `gh issue edit` can error removing a label the Issue doesn't carry, so don't include it speculatively.

---

## Section B — Stage outputs = Issue comments + markers

Each stage persists its output as a GitHub Issue comment wrapped in a marker pair, so later stages (and `/gld resume`) can find it. Update-in-place: if a comment with the marker already exists, PATCH it rather than appending (per `_bash_rules.md` temp-file pattern).

| Marker | Produced by | Contents |
|---|---|---|
| `<!-- guild:analyze:output -->` … `<!-- /guild:analyze:output -->` | analyze (leader) | requirement analysis, work-type classification, assumptions/interpretations chosen at discuss gate |
| `<!-- guild:design:output -->` … `<!-- /guild:design:output -->` | design (tech-lead ∥ tester) | design summary, skeleton pointer, test-case pointer, PR split decision |
| `<!-- guild:test:output -->` … `<!-- /guild:test:output -->` | test (tester) | test run summary + verify gate outcome |
| `<!-- guild:test-evidence:step-<n> -->` … `<!-- /guild:test-evidence:step-<n> -->` | **execute only** (`implement.md`/`debug.md`/`refactor.md` Step 2, as `step-1`) | raw test-runner output captured as verify evidence (Section E). ⚠ `test.md` does **not** also write this marker — its own raw evidence goes under `<!-- guild:test:output -->` above instead (an earlier version of this table said "execute/test," which `status.md`'s own marker list correctly never claimed). |
| `<!-- guild:qa:output -->` … `<!-- /guild:qa:output -->` | qa | holistic QA plan + result (exploratory/E2E/user-flow) + UI/UX gate verdict when applicable. Read by `status.md` and `review.md` (Step 1's agent-authored-PR rationale load). |
| `<!-- guild:review:output -->` … `<!-- /guild:review:output -->` | review (fresh reviewer) | guided pair-review walkthrough (risk-weighted, rationale-backed). Posted to the PR only with `/gld review … --comment`; default is **session-only, nothing persisted to disk** (unlike the other stages, `review.md` never writes a `docs/specs/<issue>/` file for its own recap). |

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
| `OK SPLIT: <N> children` | design split the Issue into `N` child Issues | transition the **parent** to `guild:children` and enter child orchestration (dev Phase 2b — Section I) |
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
2. Capture the raw tail of the output (the runner's own summary line, e.g. `Tests: 12 passed, 0 failed`). ⚠ **INV5 — scrub before posting, never paste blindly**: this is raw process output pasted into a public/shared GitHub comment — a crashing runner can print environment-variable dumps, connection strings, or tokens in its stack trace. Before writing it in step 3, scan the captured tail for the same high-signal secret patterns the commit gate uses (`gate_precommit.py`'s `INLINE_SECRET_RES` — AWS/PEM/Google/Slack/GitHub/Stripe keys) and redact any hit (`[REDACTED]`) rather than posting it verbatim. This mirrors `audit_readiness.md`'s "never print secret values" rule, which this exact raw-output path was missing until now.
3. Write it to an Issue comment via the temp-file pattern — **the marker depends on which stage is running this procedure**: execute (`implement.md`/`debug.md`/`refactor.md` Step 2) uses `<!-- guild:test-evidence:step-<n> -->`; test (`test.md` Step 2) uses `<!-- guild:test:output -->` instead (not the `step-<n>` marker — see the marker table above).
4. In any narrative claim ("all tests green"), the claim MUST be backed by the captured raw line. If the self-report and the raw output disagree, the raw output wins and the stage returns `BLOCKED`/`FAIL`. **When they disagree (a verify-gap), the enforcing stage also logs it as a ground-truth signal for the growth loop** (`_signals.md` Section C — `capture_signal.py --kind verify-gap`; this is the plan's "verify 증거패턴을 교정·revert 로깅으로 확장"). Logging is observational only and never changes the gate verdict (INV2).
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
- **Gate role (conditional review)** — a **review check** the leader inserts *before advancing past a stage* when risk warrants (e.g. security review on auth/exposure changes). A gate role reviews **someone else's** output (external-auditor stance — it never self-reviews its own artifact; plan §9/§16). Three roles carry gate capability on top of conditional participation, but not identically: designer/security **build during the stage and also provide the review check** (e.g. designer authors the UX design in `design`, then separately reviews the built UI at the `qa` gate); infra, by contrast, **never builds** — it conditionally joins `execute` purely to review the developer's already-produced CI/deploy/env/IaC diff (external-auditor stance from the start, per its own persona, not a build-then-review split like designer/security).

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
| infra | participation **+ gate** | CI/CD · deploy · env · IaC changes | execute (**infra review gate** — reviews the developer's already-produced CI/deploy/env/IaC diff, never authors its own; external-auditor stance, same as designer/security) | review verdict + rollback/verify notes (not a diff) |
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

---

## Section H — Unattended mode (`GLD_UNATTENDED`, used by `/gld batch`·`/gld sprint`)

When Guild runs unattended (a supervisor invokes `claude -p "/gld resume <n>"` with `GLD_UNATTENDED=1` set), no human is present to answer a gate. **The leader stands in for the human at in-flow gates — but the human's real authority is deferred to PR review + merge, never removed** (INV1: nothing merges unattended). This is the plan's sprint principle ("사람 리뷰를 뒤로 미룰 뿐 없애지 않음"). Attended runs are unchanged.

**Detection** — at stage start (its own Bash call):
```bash
printenv GLD_UNATTENDED
```
Value `1` → unattended. Anything else / empty → attended (default; behave exactly as before).

**Gate policy when unattended:**

| Gate | Attended (default) | Unattended (leader stands in) |
|---|---|---|
| **discuss** (analyze/design) | return `NEEDS_HUMAN` → main session `AskUserQuestion` | leader classifies the ambiguity's stakes, **charter-anchored**: **low/medium** (local, reversible) → pick the most charter/standards-aligned interpretation, **record it as an explicit assumption** in the stage output (for the decision log), proceed. **high** (scope-defining / materially different product / hard to reverse) → do NOT guess: post a `<!-- guild:needs-human -->` comment listing the options, **add the `guild:needs-human` label**, and return `OK PAUSE: needs-human — <one-line>` (do NOT transition the stage label). |
| **verify** (test) | `NEEDS_HUMAN` on red/AC-gap | **deterministic**: raw evidence green + AC covered + DoD → advance. Else bounded loop-back to execute (≤2 attempts). Still failing → `OK PAUSE: needs-human — tests not green / AC gap`. **Never weaken/skip tests to pass** (INV2). |
| **qa** (blocking defect) | `NEEDS_HUMAN` | record the concern; bounded loop-back to execute if fixable, else `OK PAUSE: needs-human — QA defect`. Never force `done`. |

**Decision log (mandatory when unattended)**: every gate the leader auto-resolved is recorded — analyze/design write each assumption into their output comment; the execute stage's **PR body** aggregates them under a `## 무인 결정 로그 (GLD_UNATTENDED)` heading (chosen interpretation · rationale/charter anchor · "사람 확인 요"). This makes the human's PR review **informed, not blind** — the deferred human gate lands here.

**Hard rules (unchanged under unattended)**: INV1 (never merge — stop at `guild:done` = PR open) · INV2 (never weaken verification) · never fabricate a pass. `OK PAUSE: needs-human` is the honest escape hatch: mark the Issue with the **`guild:needs-human` label** (+ comment) so it is discoverable (`gh issue list --label guild:needs-human`), then stop **cleanly** (exit 0) so the supervisor counts it and moves to the next Issue.

---

## Section I — Parent/child orchestration (multi-PR split)

When a task is too large for one PR, design splits it into **child Issues** that are developed **sequentially**, one full spine each, then integrated back into the parent. Lifted and simplified from sdd's parent/child model (labels are the state — no temp-file crash-recovery, no multilingual regex; guild is EN-canonical). Read by `design.md` (creates children), `dev.md` (orchestrates — Phase 2b/2c), `resume.md` and `status.md`.

**The parent↔child link (two records):**
- **In each child's body**: a line `Parent Issue: #<parent>` (canonical, single-language). This is the discovery key.
- **On the parent**: one `<!-- guild:children:output -->` … `<!-- /guild:children:output -->` comment — a static roster of the children (`#<n>` · slice · one-line scope), and a human-readable index. **Not** a live status board: per-child status is always derived fresh from each child's label, so this comment is posted once and not PATCHed per child. ⚠ **Not the idempotency guard** — it's posted *last*, after every child already exists (`design.md`/`plan.md` Step-ordering), so an interruption before it's posted would make a presence-only check blind to already-created children and cause duplicates on retry. The actual idempotency guard is the **discovery query** below (re-derive the real child set every time, before creating anything) — the roster comment is written once creation is already known-complete, purely for humans, never read back as a completeness signal.

**Child creation format** (design, its own Bash calls — temp-file body per `_bash_rules.md`):
```bash
gh issue create --title "[Guild子] <slice name>" --body-file <temp> --label "guild:child" --label "guild:analyze"
```
The body states the slice's scope + acceptance criteria + a `Parent Issue: #<parent>` line. Create children in **intended dependency order** (ascending Issue number then = execution order).

**Child discovery** (its own Bash call — literal parent number substituted, no shell vars in the jq string per `_bash_rules.md`):
```bash
gh issue list --label guild:child --state all --limit 200 --json number,title,labels,body --jq '[.[] | select((.body // "") | test("Parent Issue: #<parent>([^0-9]|$)"))] | sort_by(.number)'
```
⚠ **`body` MUST be in `--json`** — the `--jq` filter tests `.body`; omitting it from `--json` (as an earlier version of this doc did) makes `.body` always `null`, the regex never matches, and the query silently returns `[]` **every time regardless of how many children actually exist** — orchestration would never discover any child and a split parent would stay at `guild:children` forever. Verified against the real `jq` binary: with `body` present the filter matches correctly; without it, it does not. The boundary class `([^0-9]|$)` is also **load-bearing** — without it `#68` matches `#680`.

**Ordering & execution (sequential, in-session):** process children in ascending-number order (creation = intended order). For each child **not yet `guild:done`**, drive it through the **full spine** (analyze→design→execute→test→qa→done) exactly as a normal single Issue. A child pausing (`NEEDS_HUMAN`/`OK PAUSE`/`FAIL`) stops orchestration where it is; a later `/gld dev`/`/gld resume` on the parent re-discovers children and continues from the first not-done one (labels are the checkpoint — nothing local to corrupt).

**Leaf-only invariant:** a child is a leaf — it is **not** re-split. If a `guild:child` Issue's design flags a further split, that is a scoping error: return `NEEDS_HUMAN: child #<n> cannot be re-split — re-scope the parent #<parent>` rather than recursing.

**Parent integration & completion:** the parent stays at `guild:children` while any child is open. When **every** child is `guild:done`, the leader runs a **parent-integration** check (dev Phase 2c): does the union of children satisfy every parent acceptance criterion? are the children mutually consistent (no seam/data-shape mismatch, no duplicated or orphaned work)? are all parent DoD items closed? Post the result under `<!-- guild:integration:output -->` on the parent. A gap → `NEEDS_HUMAN` (or a targeted loop-back to the relevant child); clean → transition the parent `guild:children` → `guild:done`.

---

## Section K — Output language

Every **human-readable string Guild emits is written in the repo's `config.language`** (`.claude/guild/config.json`; default `en` when absent) — Issue/PR comments, discuss `AskUserQuestion` questions/options, stage narration to the user, `>>> RESULT <<<` one-line summaries, and the **prose inside artifact files** (`docs/specs/<issue>/*`). This is the same language `/gld init` wrote the agents and standards in.

**Never localized — stays ASCII/English (machine tokens):** the `RESULT`/return keywords (`DONE`, `BLOCKED`, `NEEDS_CONTEXT`, `OK ADVANCE`, `OK SPLIT`, …), HTML markers (`<!-- guild:* -->`), `guild:*` label names, file paths, code identifiers, and git branch/commit conventions. Localizing these would break parsing.

**Two emission points, both must comply:**
1. **The leader (main session)** localizes its own output — every comment it posts, every `AskUserQuestion`, every narration line. It learns the language at pre-flight (`_preflight.md` Item 1).
2. **Spawned role sub-agents** — the persona file is already in the target language, but the persona alone does not guarantee the *response* language. So when the leader spawns a role, its prompt **must append**: *"모든 사람이 읽는 산출물(코멘트·파일 산문·RESULT 요약)은 이 레포의 `config.language`로 작성한다 (기계 토큰·코드·경로·마커는 영어 유지)."* — rendered in that language. A sub-agent's RESULT summary and any prose it writes then match.
