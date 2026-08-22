# HANDOFF & STATE (shared contract)

**Not a stage.** This file is the authoritative contract for (1) how Guild tracks development state on GitHub, (2) how stage outputs are persisted, and (3) how role agents hand off to each other within a stage. Read the section the calling file points to. (Guild's inter-role protocol. Descends from sdd's GitHub state model and sub-agent contract.)

> **Bash Command Execution**: every shell snippet below is its own simple Bash tool call. See `<<SKILL_DIR>>/commands/atoms/_bash_rules.md`. Codebase exploration uses Grep/Glob/Read.
>
> **Sections**: A labels · B markers · C role handoff · D stage return · E verify evidence ·
> F owner/repo + `gh` write failures · G roster · H unattended · I parent/child · **(no J)** ·
> K output language.
> There is deliberately **no Section J** — the letter was skipped, and callers are numerous
> enough that renaming K would be a worse fix than recording the gap. A pointer to "Section J"
> anywhere is a typo for one of the sections above; nothing was deleted.
> Safety invariants INV1–INV6 live in their own atom: `<<SKILL_DIR>>/commands/atoms/_invariants.md`.

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
| `guild:needs-human` | **additive, not a stage** — an unattended run paused here at a high-stakes gate | Section H's pause path; removed on the next forward transition (below) |
| `guild:harness` | **not a stage** — a harness readiness gap filed as a developable Issue | `init` P3.5 / `/gld audit` remediation. `resume.md` routes it to a fresh `dev` run |

The table has **four kinds of row**, and every consumer that derives "the current stage" must
filter accordingly: stage labels (`analyze`/`design`/`execute`/`test`/`qa`/`done`), the
identity marker (`guild:child`), the orchestration state (`guild:children`), and the two
non-stage annotations (`guild:needs-human`, `guild:harness`). A bare
`select(startswith("guild:"))` returns all of them. The exclusion is derived **once**, below;
consumers cite it instead of re-deriving it.

### Section A — canonical stage derivation

**The one expression that answers "which `guild:*` label is this Issue's current stage".**
Cite this subsection by name (`_handoff.md` Section A — canonical stage derivation) rather than
restating the exclusion list; a new label kind is added here, not in each consumer. Its own
Bash call, applied to the `labels` field of `gh issue view` (an array of `{"name": …}` objects —
note `gh label list --json name` returns a *flat* array of such objects instead and is a
different shape; see `audit_readiness.md`):

```bash
gh issue view <n> --json labels --jq '{stage: ([.labels[].name] | map(select(startswith("guild:") and . != "guild:child" and . != "guild:needs-human" and . != "guild:harness")) | .[0] // "none"), paused: ([.labels[].name] | any(. == "guild:needs-human")), harness: ([.labels[].name] | any(. == "guild:harness")), child: ([.labels[].name] | any(. == "guild:child"))}'
```

It yields the stage plus one flag per non-stage kind (add `state` — or any other field — to `--json` and the projection when the caller also needs it; `rollback.md` does):

- **`stage`** — the Issue's current stage label: `guild:analyze` · `guild:design` · `guild:execute` · `guild:test` · `guild:qa` · `guild:done`, or `guild:children` for a split parent — or the literal string `"none"` when the Issue carries no stage label at all (not started).
- **`paused`** — `guild:needs-human` is present. **Additive, never a stage**: it sits *on top of* the stage label (Section H), so a paused Issue still has its real `stage`. Render/count it alongside the stage, never instead of it.
- **`harness`** — `guild:harness` is present. **Provenance, never a stage**: a readiness gap filed as a developable Issue. `stage == "none"` **and** `harness == true` = filed but not started; once a stage label exists, the stage wins and `harness` is a mere annotation.
- **`child`** — `guild:child` is present. **Identity, never a stage**: a permanent marker every child carries *alongside* its real stage label (see below), which is why it is excluded from `stage`. Exposed as its own flag purely so consumers that annotate with it (`status.md`'s `(child)`, `rollback.md`'s parent-consistency check) don't re-derive it.

**Split parent**: `stage == "guild:children"` (equivalently `[.labels[].name] | any(. == "guild:children")`). This is an orchestration state, **not** a spine stage — it has no predecessor or successor in the ordinal chain `analyze < design < execute < test < qa < done`, so nothing may compute "one stage back/forward" from it.

Why the exclusions must be explicit (**this reasoning lives here only**): a bare
`select(startswith("guild:"))` returns all four kinds at once, so taking `.[0]` picks whatever
label GitHub happened to return first — a child reads as `guild:child`, a paused Issue can read
as `guild:needs-human`, a started harness Issue as `guild:harness` — while `join(",")` instead
yields a comma-joined string like `"guild:child,guild:execute"` that matches **no** stage row.
Verified against the real `jq` binary: `["guild:child","guild:test"]` → `guild:test`;
`["guild:children"]` → `guild:children`; `["guild:qa","guild:needs-human"]` → `guild:qa` +
`paused: true`; `["guild:harness"]` → `"none"` + `harness: true`.

**In a list query** (`gh issue list … --json …,labels`), apply the same projection per element —
`stage` + `paused` is the usual pair (add `harness`/`child` only if that caller renders them).
This is exactly what `status.md`'s child discovery and `monitoring.md`'s bucketing do:

```
{number, stage: ([.labels[].name] | map(select(startswith("guild:") and . != "guild:child" and . != "guild:needs-human" and . != "guild:harness")) | .[0] // "none"), paused: ([.labels[].name] | any(. == "guild:needs-human"))}
```

**The shell-side equivalent — `batch.md`.** batch's supervisor is a generated `.sh` script (the
sanctioned `_bash_rules.md` exception), so it cannot use this projection: it flattens the labels
to a comma-joined string and matches them with a bash `case`. The same rule appears there as
**arm ordering** — `*guild:needs-human*` MUST be tested **before** `*guild:done*` and
`*guild:children*`, because a bash `case` fires the **first** matching arm rather than the most
specific one, and these labels coexist on one Issue. So a future label kind has to be reflected
in **two** places: this derivation, and batch's `case` arms.

**Split parents do not run the spine themselves.** When design splits an Issue, the parent leaves the normal `analyze→…→done` track and enters `guild:children` — it is an *orchestration* state, not a stage. Its "execute/test/qa" is the sum of its children plus a final parent-integration check (Section I). A parent never carries both `guild:children` and a stage label at once.

**`guild:child` is a permanent identity marker, never removed.** Unlike every other row in the table above, `guild:child` is not itself a stage — it marks a child Issue's identity for its entire lifetime (added once at creation by `design.md`/`plan.md`, alongside its starting stage label `guild:analyze`; never removed by any later stage). A child Issue therefore always carries **two** `guild:*` labels at once: `guild:child` plus its actual current stage label — so "read current labels" at any stage's Step 0 returns a 2-element (not 1-element) array for a child. Every stage's transition ("remove whatever `guild:*` label Step 0 found, add the next one") must operate on the **stage** label only; stripping `guild:child` would silently drop the Issue out of Section I's `gh issue list --label guild:child` discovery query, breaking its parent's ability to find it. `design.md` additionally tracks this as `IS_LEAF` for its own leaf-only-split guard (Section I) — every other stage file just needs to leave the label untouched.

**Label transitions belong to the main session, never to a spawned sub-agent.** Role sub-agents (tech-lead/developer/tester/qa/specialists) NEVER add or remove labels — they return a status line (Section C) and the main session acts on it. This keeps state changes centralized and auditable.

**Within the main session, the stage wrapper owns its own transition.** Each wrapper performs
the `gh issue edit` itself as its last step, *before* returning `OK ADVANCE: <next>`; `dev.md`
reads that line only to decide which wrapper to run next, and does not re-apply the label.
Single source, so a directly-invoked `/gld design 12` transitions identically to the same
stage running inside `/gld dev 12`. (An earlier revision of this section said the main session
applied the label *after* reading the return line, which contradicted every wrapper and
`dev.md` alike — and would double-apply a transition the wrapper had already made.)

Transition rule: remove whatever `guild:<stage>` label Step 0 actually found and add
`guild:<next>` — plus `--remove-label "guild:needs-human"` when that label is present (below).
Labels are created by `/gld init`.

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
| `<!-- guild:children:output -->` … `<!-- /guild:children:output -->` | design / plan (leader) | the child roster of a split parent — one line per child Issue. Written **once**, after every child already exists. ⚠ Informational only: it is **never** the split-idempotency guard (Section I) — the discovery query is. |
| `<!-- guild:integration:output -->` … `<!-- /guild:integration:output -->` | dev Phase 2c (leader ∥ tech-lead) | parent-integration check once all children are `guild:done`: parent-AC → child coverage map, cross-child consistency, DoD closure, any gap found. |
| `<!-- guild:review:output -->` … `<!-- /guild:review:output -->` | review (fresh reviewer) | guided pair-review walkthrough (risk-weighted, rationale-backed). Posted to the PR only with `/gld review … --comment`; default is **session-only, nothing persisted to disk** (unlike the other stages, `review.md` never writes a `docs/specs/<issue>/` file for its own recap) — this row documents the marker's shape for that opt-in case, not a durable output. |

**Durable design artifacts** (skeleton, architecture decisions, test cases) that outlive the Issue thread are also written to the working tree:
- `docs/specs/<issue>/` — design skeleton, notes, test-case list (committed with the PR).

GitHub holds ephemeral stage state (①); `docs/` holds durable knowledge (②). The Issue comment is the index; `docs/specs/<issue>/` holds the detail passed **as files** between roles (never pasted into context).

---

## Section C — Role handoff (within a stage) = status enum + RESULT line

When one role hands off to another inside a stage — tech-lead → developer, tester → developer, developer → tech-lead for conformance — the handoff is a **file** (the artifact) plus a **return status**. A sub-agent spawned for a role returns EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. The line(s) before the sentinel may be narrative; the caller ignores everything until the sentinel.

**Status enum**:

| Status | Meaning | Caller (leader) action |
|---|---|---|
| `DONE` | work complete, artifact written, no concerns | proceed to next role / stage |
| `DONE_WITH_CONCERNS: <one-line>` | complete but the role flags a risk worth surfacing | proceed, but record the concern in the stage output and surface to the human |
| `BLOCKED: <one-line>` | cannot proceed (missing dependency, contradiction) | leader intervenes: gather context, reassign, or escalate to human |
| `NEEDS_CONTEXT: <one-line>` | needs an input that should exist but wasn't found | leader supplies the missing artifact/pointer, then re-invokes the role |
| `FAIL: <reason>` | hard error (gh failure, Issue is a PR, etc.) | stop the stage; report to human |

**Artifacts are passed as files, not pasted** (context protection). The producer writes to the working tree or `docs/specs/<issue>/`; the RESULT line names the path. The consumer reads that path. Never inline a skeleton or full test-case list into a RESULT line — keep RESULT to one summary line.

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

### When the RESULT line is missing or malformed (contract violation)

A reply that does not carry **exactly one** `>>> RESULT <<<` followed by **one** enum status is a
**failed invocation**, never a pass. Three shapes, one rule:

- **No sentinel at all** — the reply is narrative only.
- **More than one sentinel** — do NOT pick one (not the last, not the "best"); the contract is one.
- **Sentinel present, but the next non-empty line is not** `DONE` / `DONE_WITH_CONCERNS:` /
  `BLOCKED:` / `NEEDS_CONTEXT:` / `FAIL:`.

**Never infer a verdict from the prose** — reading "looks like it passed" out of narrative text is
exactly the self-report-over-evidence failure the verify gate (Section E) exists to prevent.

Handling: re-invoke that role **exactly once**, same task plus one line naming the violation
("your previous reply had no/duplicate/invalid `>>> RESULT <<<` — return EXACTLY one sentinel and
one status from the enum"). Still malformed → escalate exactly as an exhausted bounded retry does:
**attended** → `NEEDS_HUMAN: <role> returned no valid RESULT line for #<n>`; **unattended**
(Section H) → add the `guild:needs-human` label + a `<!-- guild:needs-human -->` comment and return
`OK PAUSE: needs-human — <role> returned no valid RESULT line` (do NOT transition the stage label).
A failed invocation satisfies no gate: the stage must not return `OK ADVANCE` on it.

---

## Section D — Stage-level return (stage → main session)

A stage wrapper (analyze/design/implement/test) returns one line to the main session (dev.md or the direct-invocation command). This drives the Section A label transition.

| Return | Meaning | Main session action |
|---|---|---|
| `OK ADVANCE: <next-stage>` | stage complete, advance | transition label to `guild:<next-stage>` |
| `OK SPLIT: <N> children` | design split the Issue into `N` child Issues | transition the **parent** to `guild:children` and enter child orchestration (dev Phase 2b — Section I) |
| `OK DONE` | qa's gate passed (after test's verify gate) | transition to `guild:done` — **Guild's work is complete; the PR is open awaiting human review + merge**. Do **not** close the Issue: the PR body carries `Closes #<N>`, so **GitHub** closes it when the human merges — INV1 (nothing merges unattended; the human is the external reviewer of record). No Guild command closes an Issue deliberately. |
| `OK PAUSE: <one-line>` | leader/human chose to stop here | leave label as-is; report |
| `NEEDS_HUMAN: <one-line>` | a discuss/verify gate needs a human decision | main session prompts the human (`AskUserQuestion`), then resumes |
| `NEEDS_CONTEXT: <one-line>` | a **required upstream artifact is missing** — design without analyze output, execute without a design skeleton | do **not** advance and do **not** treat as a hard error: the fix is to run the missing stage. Report which artifact is absent and re-enter the spine at the stage that produces it; if that stage's label is already set (so it "ran" but left nothing), surface it as `NEEDS_HUMAN` — a silent no-op upstream is a state inconsistency a human should see. |
| `FAIL: <reason>` | hard error | stop; report |

`<next-stage>` values: `analyze → design → execute → test → qa → done`.

⚠ `NEEDS_CONTEXT` is **also** a role-level status (Section C), and the two are distinct: at
role level it means "the sub-agent needs more context from the leader," and the leader
supplies it and re-invokes. At *stage* level it escapes to the main session and means "an
earlier stage's output does not exist." `design.md`/`implement.md`/`debug.md`/`refactor.md`
have always returned this line, but it was absent from this table, so `dev.md` Phase 2 had no
branch for it — a missing analyze output produced a return value the driver did not know how
to route. Non-spine commands (`plan.md`) use their own `OK: …` vocabulary and are not driven
by this table.

**Sub-agents never call `AskUserQuestion`** (they are non-interactive). A gate that needs a human decision returns `NEEDS_HUMAN:` and the main session runs the interactive prompt. In M1, the human is also the external reviewer ("M1의 독립 리뷰어 = 사람"), so `NEEDS_HUMAN` at the discuss/verify gates is the primary human-in-the-loop point.

---

## Section E — Test evidence capture (verify gate concrete impl)

The **verify gate** is implemented as evidence capture: whenever a test runner is executed during execute or test, capture the **raw runner output** and cross-check it against any self-reported pass/fail claim. This prevents an agent from claiming "tests pass" without proof ("자기보고를 원문과 대조").

Procedure:
1. Run the project's test command (from `config.json` `commands.test` / conventions) as a simple Bash call. **Commands are pre-normalized** (`scan_repo.md` Section 2): a value is either a simple string or an **array** of simple steps. Run each array element as its **own** Bash call in order — never join them with `&&`. The stored form never contains `$(...)`/`&&`/`|`; if you encounter a raw compound command from an older install, split it yourself and drop any `$(...)` flag before running.
2. Capture the raw tail of the output (the runner's own summary line, e.g. `Tests: 12 passed, 0 failed`). ⚠ **INV5 — scrub before posting, never paste blindly**: this is raw process output pasted into a public/shared GitHub comment — a crashing runner can print environment-variable dumps, connection strings, or tokens in its stack trace. Before writing it in step 3, scan the captured tail for the same high-signal secret patterns the commit gate uses (`gate_precommit.py`'s `INLINE_SECRET_RES` — AWS/PEM/Google/Slack/GitHub/Stripe keys) and redact any hit (`[REDACTED]`) rather than posting it verbatim. This mirrors `audit_readiness.md`'s "never print secret values" rule, which this exact raw-output path was missing until now.
3. Write it to an Issue comment via the temp-file pattern — **the marker depends on which stage is running this procedure**: execute (`implement.md`/`debug.md`/`refactor.md` Step 2) uses `<!-- guild:test-evidence:step-<n> -->`; test (`test.md` Step 2) uses `<!-- guild:test:output -->` instead (not the `step-<n>` marker — see the marker table above).
4. In any narrative claim ("all tests green"), the claim MUST be backed by the captured raw line. If the self-report and the raw output disagree, the raw output wins and the stage returns `BLOCKED`/`FAIL`. **When they disagree (a verify-gap), the enforcing stage also logs it as a ground-truth signal for the growth loop** (`_signals.md` Section C — `capture_signal.py --kind verify-gap`; this is the plan's "verify 증거패턴을 교정·revert 로깅으로 확장"). Logging is observational only and never changes the gate verdict (INV2).
5. **Honesty of scope**: the verify output must also state what was **NOT** run — in M1, `commands.e2e` (integration/E2E) is detected but not auto-run, and manual/visual QA is the human's step. "verify passed" means *automated-test verification*, never "fully QA'd." Do not imply full QA.

This is a hard requirement in M1 (no separate AI verify reviewer exists yet — the raw-output cross-check IS the verify gate). Honesty covers both directions: don't overstate results (claim vs raw), and don't overstate coverage (what ran vs what didn't).

---

## Section F — Owner/repo resolution

Obtain `<owner>/<repo>` once per command via its own Bash call, then inline the literal value everywhere it is needed:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

Never infer owner/repo from the git user, the system prompt, or path names. If the command fails (non-GitHub remote), Guild's GitHub-backed state is unavailable — report and stop (M1 requires a GitHub repo).

### Section F — `gh` write failures (any state-mutating call)

Expired auth, rate limits and network errors are ordinary, and the spine's **only** persisted
state is the label — so a silently-failed `gh issue edit` desynchronises the state model: the
stage believes it advanced while GitHub still shows the old stage. Applies to every state
mutation: label edit, comment create/PATCH, `gh issue create`, `gh pr create` / `gh pr edit`.

- **Verify it landed — never assume.** After a label edit, re-read the labels (Section A's
  derivation) and confirm the new set; after a create, confirm the returned URL/number is
  non-empty. A non-zero exit, an error line, or an empty URL/number **is** a failure.
- **Transient** — rate limit (429 / "API rate limit exceeded"), network/DNS, 5xx → **one** bounded
  retry of the same call, then verify again.
- **Terminal** — auth (401 / "gh auth login"), permission (403), not-found (404), validation (422,
  e.g. a label that doesn't exist) → do **not** retry, it will not help: stop and return
  `FAIL: gh <operation> failed for #<n> — <gh error, 1 line>`.
- **A failed state mutation is never reported as success.** The stage does not return
  `OK ADVANCE`/`OK SPLIT`/`OK DONE` on it, and no narrative may claim a transition, PR, or comment
  that did not land. (Read-only `gh` reads are out of scope — they fail loudly and are re-runnable.)
- **Scope: Issue/PR *state*, not repo setup.** "Label edit" here means `gh issue edit --add-label`
  / `--remove-label` — mutating one Issue's stage. `init`'s `gh label create … --force` is repo
  setup: idempotent, deliberately non-transactional, and documented to report-and-continue on a
  per-label failure (`init.md` P2 step 7). Do not apply the stop-and-`FAIL` rule there; a missing
  label surfaces later as a terminal 422 on the first `gh issue edit` that needs it, which this
  contract already covers.

---

## Section G — Roster & participation model (who works on a task)

`/gld init` installs the **full roster of 16 roles** into `.claude/agents/`. Installing everyone is cheap; what varies per task is **who participates**. The leader (embodied by the main session — `leader.md`) assembles the cast from the roster using work-type + risk + charter. There are **three participation kinds**:

- **Stage role (always)** — lives on the spine; present in every task. Depth scales with the work (a one-line fix still passes through them, lightly). Never conditional.
- **Participation role (conditional join)** — the leader convenes it **only when the task's nature warrants** (e.g. a designer on a UI change). Not warranted → never spawned → zero token cost. This is how a 16-role roster stays cheap.
- **Gate role (conditional review)** — a **review check** the leader inserts *before advancing past a stage* when risk warrants (e.g. security review on auth/exposure changes). A gate role reviews **someone else's** output (external-auditor stance — it never self-reviews its own artifact). Three roles carry gate capability on top of conditional participation, but not identically: designer/security **build during the stage and also provide the review check** (e.g. designer authors the UX design in `design`, then separately reviews the built UI at the `qa` gate); infra, by contrast, **never builds** — it conditionally joins `execute` purely to review the developer's already-produced CI/deploy/env/IaC diff (external-auditor stance from the start, per its own persona, not a build-then-review split like designer/security).

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
