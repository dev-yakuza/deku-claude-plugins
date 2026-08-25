# EXECUTE SPINE (shared stage skeleton — implement / debug / refactor)

**Not a stage.** The **execute** stage's common Steps 0–6, shared by its three variants: `implement.md` (`type:feature`), `debug.md` (`type:bug`), `refactor.md` (`type:refactor`). Read by whichever variant `dev.md` Phase 2 selected (or by a direct `/gld implement|debug|refactor <issue>`). The spine is identical across the three — only the *developer's task shape* and a few checks differ, so each variant file supplies the **slots** in Section A and this file runs everything else. A variant stays individually runnable: read the variant file (its header, its slot values, its own hard rules), then execute the steps below substituting those values.

> **Bash**: `_bash_rules.md` — one simple call each, no `&&`, `|`, `;`, `$(...)`, or redirection. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); **every** sub-agent prompt below ends with "Write output in `config.language`" — never drop it from a spawn.

`<N>` = the Issue number (the variant file receives it as `$1`). Substitute the **literal** Issue number for `<N>` — and the literal value for every other `<…>` — before the Bash call: `_bash_rules.md` forbids passing `<N>`/`$1` through unresolved, and `capture_signal.py` accepts a non-numeric `--issue` silently rather than erroring, so an unresolved `$1` would land in the ground-truth log as `"issue": "$1"` and quietly poison the record evolve reads.

**Step numbering is deliberately unchanged** from when these steps lived inline in the three variant files: when another file cites "`implement.md`/`debug.md`/`refactor.md` Step N" (`_stagnation.md` Section C, `_model_tiering.md` Section A, `_signals.md` Sections A/C, `_handoff.md` Sections A/D/E, `review.md`, `batch.md`), it means Step N **below**, as run by that variant.

---

## Section A — Slots the variant supplies

| Slot | What the variant states | Consumed at |
|---|---|---|
| **DESIGN INPUT** | which design artifact(s) Step 0 loads, and the exact `NEEDS_CONTEXT:` line when they're missing | Step 0 |
| **BRANCH + RESUME PROBE** | the branch prefix (`feature/` · `fix/` · `refactor/`), and what the one resume test-run probes on an existing branch | Step 0 |
| **DEVELOPER TASK SHAPE** | the spawn `description`, the ordered task body the developer follows, and the extras its `>>> RESULT <<<` line must carry | Step 1 |
| **EVIDENCE RULE** | what Step 2 requires of the raw evidence *beyond* the base cross-check (and therefore what "green" means at Step 4) | Steps 2, 4 |
| **CONFORMANCE CHECKS** | what the tech-lead is asked to check (and therefore what a tech-lead `BLOCKED` means at Step 4) | Steps 3, 4 |
| **SIGNAL AREA** | the `--area` phrasing (and the likely `--role` set) for Step 4's ground-truth capture | Step 4 |
| **PR SUMMARY** | what the PR body must name beyond `Closes #<N>` | Step 5 |

Every slot is mandatory — a variant that leaves one unstated is not runnable. Anything **not** in this table is spine-common and must not be re-stated (or silently altered) per variant.

---

## Step 0 — Preflight

As the leader, follow `_preflight.md` **Heavy tier** (per its Section A table: items **1 + 2 + 3 + 4 + 5 + 6 + 8** — not just 1–5; item 5 is the target-dir survey, items 6/8 are the ⑥ knowledge-slice retrieval and ④ working-memory read, both needed to honestly populate the Section C self-review trace). If `.claude/guild/config.json` is absent → `FAIL: Guild not initialized (run /gld init)` — the same hard check `analyze.md`/`design.md`/`test.md`/`qa.md` make at their own Step 0, so every spine stage behaves identically on an uninitialized repo regardless of which one the human invoked directly. Load the design output (`<!-- guild:design:output -->`) plus the variant's **DESIGN INPUT**; if it is missing → return that slot's `NEEDS_CONTEXT:` line.

Validate `<N>` is an Issue. **Read current labels first** (its own Bash call):

```bash
gh issue view <N> --json labels --jq '[.labels[].name] | map(select(startswith("guild:")))'
```

**Split-parent guard** (right here, before any other work): if that read contains `guild:children`, refuse — a parent at `guild:children` is in an *orchestration* state, not a stage (`_handoff.md` Section A: a parent never carries both `guild:children` and a stage label at once), so Step 6's transition would destroy the link `dev.md` Phase 2b uses to drive the children:

```
>>> RESULT <<<
FAIL: #<N> is a split parent (guild:children) — its work is its children's, not its own. Run `/gld dev <N>` (or `/gld resume <N>`) to drive the children.
```

(`guild:child` is **not** this case — a child legitimately carries `guild:child` + its stage label and proceeds normally.)

Empty → add `guild:execute`. Non-empty → do not add on top (Step 6's transition removes whatever **stage** label was actually found here, not necessarily `guild:execute` — never `guild:child`, which is a permanent identity marker a child Issue also carries alongside its stage label and no stage ever removes; `_handoff.md` Section A).

Create/switch to the branch for this Issue using the variant's **BRANCH + RESUME PROBE** prefix (follow the repo's branch convention from conventions.md; e.g. `feature/#<N>-<slug>` for implement). Do this as the leader **before** spawning the developer, so the developer works on the branch.

**Record four values while doing it.** They are three different types — do not collapse them into one symbol; later steps feed them to consumers that accept only one type each.

| Value | How | Used by |
|---|---|---|
| `<branch-point>` (**SHA**) | **Creating** the branch: `git rev-parse HEAD` **immediately before** creating it — that is the real fork point. **Switching** to an existing one: `git merge-base <base-branch> HEAD` (an estimate, not the recorded fork point). If that command fails (missing ref, no common ancestor) `<branch-point>` is **empty**. | left-hand side of `git log`/`git diff` — the resume summary below, and Step 3.5's audit aperture |
| `<base-branch>` (**branch name**) | `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` | Anything that needs a **name** rather than a SHA: `gh pr create --base` (a SHA there returns 422, which Step 5 maps to a terminal `FAIL`; Step 5 does not name the flag explicitly yet), the `<stack-warning>` comparison below, and Step 5's `Base:` line |
| `<branch>` | Known directly — this step creates or switches to it | `gh pr list --head <branch>` on the resume path (and `gh pr create --head` once Step 5 names its flags explicitly) |
| `<stack-warning>` | **Before** creating the branch: `git rev-parse --abbrev-ref HEAD`. If that name differs from `<base-branch>`, record it; if it is the same, or this is the switch path, record empty. | Step 5 notes it in the PR body — the branch was cut from another feature branch, so the PR may carry commits that are not this Issue's |

⚠ **These live in the leader's context, not in persisted state** — `_handoff.md` Section F: *"the spine's **only** persisted state is the label"*. They are valid for **this** execute invocation, including its loop-backs (which re-enter at Step 1 and therefore do **not** re-record them). A later session re-derives `<base-branch>` and re-estimates `<branch-point>`, which can yield a **wider** commit set than the original run saw.

**Resume-safe (rate-limit/interruption)**: if a branch for this Issue **already exists** (a prior interrupted execute), switch to it and build a concise **partial-work summary** — `git log <branch-point>..HEAD --oneline` (what's committed) **plus one run of the test command**, read per the variant's RESUME PROBE (where the work left off). ⚠ **If `<branch-point>` is empty, skip the `git log` entirely** (an empty left-hand side makes git read it as `HEAD`, so `HEAD..HEAD` returns nothing with exit 0 — a silent no-op) and say so in the developer prompt instead of passing a summary. This summary is passed into the developer prompt (Step 1) so it **continues from the partial state, not from scratch**. Only create the branch (no summary) if absent. ("중단 내성" — mid-execute resume.)

## Step 1 — Spawn developer

Spawn the developer sub-agent:

- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: the variant's **DEVELOPER TASK SHAPE** description (e.g. `developer implement #<N>`)
- `prompt`:
  > Adopt the persona in `.claude/agents/developer.md`. Work Issue #<N> on the current branch. **Resume**: if Step 0 supplied a partial-work summary here — `<partial-work summary from Step 0, or "none — fresh branch">` — a prior run was interrupted mid-execute, so **CONTINUE from it**: keep the already-correct committed work, pick up where it stopped, complete the rest; redo only what is wrong. Do NOT rewrite correct existing work from scratch.
  > **‹ the variant's DEVELOPER TASK SHAPE body goes here verbatim — its inputs, its ordered steps, its constraints ›**
  > Run the project's test command and **capture the raw runner output** as verify evidence — do NOT claim green/fixed/done without it (`_handoff.md` Section E). slopcheck: verify every import/dependency exists (no hallucinated packages). Commit with the repo's convention. Return EXACTLY one `>>> RESULT <<<` line per `_handoff.md` Section C, including the raw test summary line, the branch name, **and the variant's stated RESULT extras**. Write output in `config.language`.

## Step 2 — Capture verify evidence

When the developer reports green, post the raw test-runner output to the Issue as evidence (temp-file pattern):

- Marker: `<!-- guild:test-evidence:step-1 -->` … `<!-- /guild:test-evidence:step-1 -->`. (Execute only — `test.md` writes its own raw evidence under `<!-- guild:test:output -->` instead; `_handoff.md` Section D marker table.)
- Body: the raw runner summary line(s) the developer captured.
- As the leader, cross-check the developer's self-report against this raw output — if they disagree, **the raw output wins**; treat as not-green and loop back (Step 4).
- Then apply the variant's **EVIDENCE RULE** — the extra thing this variant's evidence must show. Failing it is not-done: loop back the same way.

## Step 3 — Tech-lead conformance check

Spawn the tech-lead sub-agent to check the implementation against the design (separate eyes — anti-confirmation-bias):

- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tech-lead conformance #<N>`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. Review the work on the current branch for Issue #<N>. **‹ the variant's CONFORMANCE CHECKS go here verbatim — what to review it against, and exactly what to check ›** You are reviewing the DEVELOPER's output, not your own. Return one `>>> RESULT <<<` line: `DONE` (conformant), `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <non-conformance>` (requires an execute loop). Write output in `config.language`.

## Step 3.5 — Adversarial audit (always) + conditional specialists / gate reviews (leader)

### 3.5a — Adversarial audit (unconditional)

**Always run this, regardless of which triggers match below.** Every other reviewer here is conditional and looks at its own slice; the tech-lead (Step 3) checks the work against the *design*. **Nobody reads the finished change as a diff, looking for defects** — that is the gap this closes. It holds no gate: its findings are data, the disposition is the leader's (Step 4).

**First, decide whether there is anything to audit.** If Step 0 recorded an empty `<branch-point>`, **skip this command entirely** and record the absence — an empty left-hand side makes git read `..HEAD` as `HEAD..HEAD`, which exits 0 and would be misrecorded as "empty diff". Otherwise (its own Bash call, before the parallel block below):

```bash
git diff --quiet <branch-point>..HEAD -- ':!docs/specs/<N>/inv2-findings.md'
```

Substitute the **literal** SHA and Issue number recorded at Step 0 — into **this command and into every occurrence in the spawn prompt below** — the prompt ships `<branch-point>`/`<N>` in several places: the diff command it hands the sub-agent, the AC/design read and the self-exclusion note (both `docs/specs/<N>/`), and **both** mentions of the `audit-<N>.json` path (the write instruction and the RESULT template). `_bash_rules.md` item 9 is written for command arguments; a placeholder shipped inside a prompt fails the same way, one level down — the sub-agent runs `git diff <branch-point>..HEAD` verbatim, gets `fatal: ambiguous argument`, and returns `NEEDS_CONTEXT` that no amount of "supplying the missing input" can fix. ⚠ **An unresolved `docs/specs/<N>/` is worse** — the prompt's AC/design read below is conditional (*"if present"*), so the auditor does **not** report a problem; it returns an audit with the `spec` axis blind, indistinguishable from a clean one. Read the exit code:

| exit | meaning | action |
|---|---|---|
| **1** | there are changes | **spawn the auditor** |
| **0** | empty diff | **do not spawn** — record the absence in the PR body (Step 5) and continue |
| **128** | not a valid ref (a stale SHA, a ref that has since gone) | **do not spawn** — same |

⚠ **Do not run a bare `git diff` to decide this** — that loads the whole diff into the leader's context, which `_handoff.md` Section C's *"Artifacts are passed as files, not pasted (context protection)"* exists to prevent. `--quiet` answers the question with an exit code and prints nothing.

⚠ **There is no fallback aperture.** If `<branch-point>` is empty the auditor does not run; the absence is recorded, not papered over. Widening to `git diff <base-branch>..HEAD` was tried and rejected: a two-dot tree comparison shows the base branch's own commits as **deletions**, which is byte-identical to a deleted test file — the exact finding class this auditor exists for — and the three-dot form fails for the same reason `merge-base` failed. Where it *does* produce output is a stacked branch, where the output is **another Issue's commits**.

**Spawn** it in the same parallel message as any specialists 3.5b matched; **if none matched, spawn it alone** — 3.5b's "none matched → skip" never skips this one:

- `subagent_type`: **`general-purpose`** — ⚠ **not** a read-only/explore-style type, even though one is usually available and a real tool restriction would otherwise beat a prompt instruction. This role must write exactly one file (`audit-<N>.json` below); a type with no Edit/Write access cannot, and would fail every run. READ-ONLY is therefore prompt-enforced here, and the PR reviewer (INV1) is the backstop.
- `model`: `sonnet`, `description`: `adversarial audit #<N>`
- `prompt`:
  > You are an **independent, adversarial** code reviewer with NO prior context — fresh eyes. **⚠ READ-ONLY: you MUST NOT edit, write, create, delete, fix, or commit ANY file — you only READ and report.** Do not "fix" the defects you find; report them. In this step you **review only** — do not produce files, return a verdict.
  > Read the diff (`git diff <branch-point>..HEAD -- ':!docs/specs/<N>/inv2-findings.md'`), `docs/standards/`, and the Issue AC/design if present (`docs/specs/<N>/`, the `guild:*:output` comments). `docs/specs/<N>/inv2-findings.md` is this audit's own record — it is excluded above and is not under audit.
  > Hunt for **real defects**: correctness bugs, security/exposure, missing error/null handling, **blast radius** beyond the reported scope, convention/standard violations, AC gaps, and **weakened or vacuous tests**. Be skeptical; do NOT rubber-stamp.
  > **Three axes** — the `axis` field takes exactly one of these, and nothing else: `standards` — does the diff violate `docs/standards/` (architecture · conventions · quality-bar) or a Guild gate rule? · `spec` — does it satisfy the Issue's AC / design intent, or miss/contradict a requirement? · `verification` — findings about the **effectiveness** of tests/verification: weakened, **or ineffective from the start**. (If a repo standard describes only two axes, that text is scoped to `/gld review`.)
  > **Signature rule**: if a finding points at one of — deleting a test file · a net removal of assertions · adding a skip/focus directive to a test file · a test that passes but verifies nothing, **including one newly added in this diff** — then set `axis` to `verification` **even when it also fits `standards`/`spec`**, and name the signature in `inv2` (`test-deleted` · `assertion-drop` · `test-skip` · `vacuous`). Everything else is `inv2: none`.
  > Write `finding`/`why` in **plain, jargon-free language a non-expert reviewer can understand without follow-up** — spell out any acronym/pattern name on first use and state the concrete consequence, not just the violated rule.
  > **Loop-back — your own previous verdict**: `<the auditor's RESULT line from the previous loop, or "none — first attempt">`. Do not repeat the same wording; judge whether it has been **resolved**.
  > **Loop-back — why the leader sent it back**: `<the leader's one-line reason for this loop-back, or "n/a">`. Context only — it is not your verdict and you are not asked to adjudicate it.
  > Write the findings as JSON to `.claude/guild/memory/audit-<N>.json`: `[{"severity":"BLOCKER|MAJOR|MINOR","axis":"standards|spec|verification","inv2":"test-deleted|assertion-drop|test-skip|vacuous|none","file":"...","line":<n>,"finding":"<1 line, plain language>","why":"<1 line, concrete evidence>"}]` — no vague nits; every finding anchored to a concrete line + reason. *(Writing this one file is the sole exception to READ-ONLY **and to the review-only clause above** — it is the verdict's payload, not a produced artifact.)*
  > Return EXACTLY one `>>> RESULT <<<` line — one of **exactly these three**:
  > `DONE_WITH_CONCERNS: <n>건 (BLOCKER <b>/MAJOR <m>/MINOR <i>, verification <v>) — .claude/guild/memory/audit-<N>.json` · `DONE` (no findings) · `NEEDS_CONTEXT: <what is missing>` (the diff could not be read).
  > Write output in `config.language`.

⚠ **The three tokens above are the whole contract — do not point the auditor at `_handoff.md` Section C.** Shown the full five-value set, an agent instructed to be adversarial picks `BLOCKED:` as the semantically natural choice the moment it finds a real BLOCKER, and that hands the finder a gate. If `BLOCKED:` or `FAIL:` comes back anyway (the JSON shape hands it the word "BLOCKER", so this is a common path, not an exception), **treat it as `DONE_WITH_CONCERNS` in place** — act on the finding first, note the contract deviation second — and continue to Step 4. If the RESULT line is missing or malformed, re-invoke once; if it is malformed again, **record the auditor as absent and advance** rather than escalating (`_handoff.md`'s malformed-RESULT path ends in *"satisfies no **gate**"*, and this role holds none). Same for a second `NEEDS_CONTEXT:` after the leader has supplied the missing input.

### 3.5b — Conditional specialists + gate reviews

As the leader, convene the **execute-stage participation specialists** and **gate reviews** this change warrants (assembly rules in `.claude/agents/leader.md`; participation model in `_handoff.md` Section G). Match the diff surface against triggers; spawn only what matches (none matched → skip). Run the independent reviews in parallel:

- **auth / external exposure / secrets / sensitive data / input validation** → **security**: adversarial review of the developer's diff (a **gate** — reviewing someone else's output, not self-review). Returns findings with severity.
- **CI/CD / deploy / env / IaC touched** → **infra**: review the infra change (rollback/verify path correct?).
- **user-facing strings** → **i18n** · **schema/migration** → **dba** · **instrumentation** → **analytics** · **hot path/render/query** → **performance**: execute-time participation on their slice.
- **user-facing / API / documented-behavior change, OR an architecture-impacting change** (new module / changed boundary / major dependency) → **tech-writer**: draft/update the docs (README, user docs, ADR follow-through) against the **implemented** change — docs describe what was actually built. **② architecture.md drift-sync (Inner Loop)**: when the change is architecture-impacting, keep `docs/standards/architecture.md`'s **high-level skeleton** current (details stay in the ADR + ⑥ — architecture.md is the *slow overview*, not a detail log). By its `status`: `draft` → **update in place** (provisional, safe); `confirmed` → **never silently rewrite** — **attended**: propose the skeleton update, apply on human approval; **unattended** (`GLD_UNATTENDED`): the ADR already preserves the decision, so append a `<!-- guild:arch-drift -->` flag noting architecture.md needs a skeleton update → surfaced at the next `/gld review` or `/gld audit`. (Release notes are the release-manager's job, out of the spine.)

For each matched role:

- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `<role> review #<N>`
- `prompt`:
  > Adopt the persona in `.claude/agents/<role>.md`. Review the implementation on the current branch for Issue #<N> from your specialty. You are reviewing the DEVELOPER's diff, not your own work (external, adversarial). Read `docs/specs/<N>/` for design/intent. Return one `>>> RESULT <<<` line per `_handoff.md` Section C — `DONE`, `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <blocking finding>`. Write output in `config.language`.

Fold these verdicts into Step 4. A gate role's `BLOCKED` (e.g. security finds a real vulnerability) blocks advancement the same as a tech-lead non-conformance. Which specialties a given variant most often pulls in is noted in the variant file, but the trigger table above is the authority.

## Step 4 — Arbitrate (defined feedback loop)

As the leader, over the developer + tech-lead + the Step 3.5a **audit verdict** + any conditional specialist/gate verdicts:

**Auditor findings — disposition.** If the auditor reported findings, read the path its RESULT names — ⚠ **and if it named none, read the fixed `.claude/guild/memory/audit-<N>.json` the prompt assigned.** A demoted `BLOCKED:`/`FAIL:` (Step 3.5a) reports findings but carries no path, and that is the *common* path, not an edge case; routing it straight to "malformed" would discard findings the auditor already wrote to disk. (**`DONE` is not this case** — it reports no findings, names no path, and needs no file. Advance normally and render `발견 없음`.) ⚠ **If a run that reported findings has no file at either location**, treat it exactly as a malformed RESULT — re-invoke once, and if it is still absent record the auditor as absent and advance. A count with no findings behind it must not be rendered as an audit. **Advancing is entirely your call**: the default is to record and proceed. If you judge a finding real and material you may loop back (below). If you advance past a `severity: BLOCKER` finding, put a one-line reason in the PR body — "the leader judged it" carries nothing, a recorded reason does.

**Two records are not your call:**
1. Every `axis: verification` finding goes into the PR body under the audit block, listed separately from the rest — that block is what the PR reviewer (INV1) actually reads.
2. If there is **any** `axis: verification` finding, write `docs/specs/<N>/inv2-findings.md` with a `<!-- guild:inv2-findings -->` marker, grouping the findings by their `inv2` signature, then commit it — two Bash calls of your own:

```bash
git add -- docs/specs/<N>/inv2-findings.md
```
```bash
git commit -m "docs(guild): INV2 audit findings for #<N>" -- docs/specs/<N>/inv2-findings.md
```

   ⚠ **Evidence is path · line number · signature · one line of description — never quote the deleted or changed source lines.** A deleted test file's contents can carry a fixture token, and the commit gate's inline secret scan has no path filter; the gate applies the same rule to itself ("never prints secret VALUES — only file path / line number").
   ⚠ **Best-effort, like the ground-truth capture below — a failure here never blocks the loop.** If either call fails (gate rejection, anything else), note `inv2-findings.md commit failed — <reason>` in the PR body and advance. Do **not** return `FAIL:`.
   **Why a file and not just the PR body**: the PR body block is lost on a whole-body re-render, and on the bounded-retry exhaustion path there is no PR at all. A committed file survives both, and `/gld review` and `/gld audit` both surface open `<!-- guild:… -->` flags. On later loops append rather than overwrite.

- Developer `DONE`/`DONE_WITH_CONCERNS` + tech-lead `DONE`/`DONE_WITH_CONCERNS` + all gate/specialist verdicts `DONE`/`DONE_WITH_CONCERNS` + **the auditor `DONE`/`DONE_WITH_CONCERNS`, *or* a recorded skip/abandonment** (Step 3.5a: empty diff, no `<branch-point>`, or — after one re-invocation — a contract failure or a second `NEEDS_CONTEXT:` — the auditor's absence must never stall the stage) + raw evidence green **as the variant's EVIDENCE RULE defines green** → proceed to Step 5. Record specialist concerns **and the audit summary** in the PR body.
- Tech-lead `BLOCKED` (a failure of the variant's **CONFORMANCE CHECKS**), a **gate `BLOCKED`** (e.g. security vulnerability), **a leader decision to act on an auditor finding** (your call — the auditor issues no `BLOCKED`; the stagnation comparison below uses that same one-line reason, which you then also put in the auditor's second Loop-back slot, and the tier bump applies to the developer only, since no role's `BLOCKED` triggered this), OR evidence contradicting the EVIDENCE RULE → before looping back, apply the **stagnation guard** (`_stagnation.md`): compare this reason against the immediately-prior loop-back's reason for this Issue (if any). **Same root cause repeated** → stagnation — escalate immediately (`_stagnation.md` Section B) instead of consuming another attempt. **Different concern** → **defined loop back to execute**: re-invoke the developer (Step 1) — and the tech-lead/gate role whose `BLOCKED` triggered this — **at one model tier above their default** (`_model_tiering.md` Section A: sonnet → opus; attempt 1 always ran at the default, this is the one bounded retry), with the specific concern. **Re-run Step 3.5a as well**, at its default tier (it issued no `BLOCKED`, so it is not the role that triggered this), filling **both** of its Loop-back slots — its own previous RESULT line, and your one-line reason for this loop-back. They are different slots with different owners: the auditor judges whether *its own* prior finding is resolved, and your reason is context. An audit verdict from before the redo is a stale verdict, and the advance condition above counts it. Bounded — after ~2 loops without resolution: **Attended** → return `NEEDS_HUMAN: <one-line>`. **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H — detect via `printenv GLD_UNATTENDED`): there is no human to answer `NEEDS_HUMAN` here, so treat bounded-retry exhaustion the same as a stagnation escalation — add the **`guild:needs-human` label** + a `<!-- guild:needs-human -->` comment stating the unresolved concern, and return `OK PAUSE: needs-human — <one-line>` (do NOT transition the stage label). This mirrors `test.md`/`qa.md`'s unattended handling at their own bounded-retry exit.
  - ⚠ **An auditor-driven loop-back is deliberately NOT captured below.** `_signals.md` **Section B**'s anchor rule requires an objective outcome (test / gate / CI result) or a real human action; an LLM finding that a leader chose to act on is neither, and logging it would let a hallucinated defect drive an evolve proposal. This is a decision, not an omission.
  - **Ground-truth capture (①, `_signals.md` Section C — agent↔agent correction):** when this loop-back fires on a **real reversal** (a `BLOCKED`, or raw evidence contradicting a claimed green — **not** a mere `DONE_WITH_CONCERNS`), append one entry (its own Bash call, best-effort — never blocks the loop). The `BLOCKED` non-conformance/finding (or the contradicting raw line) **is** the objective anchor — a role overturning *another* role's confident output, not self-review (`_signals.md` Section B). `--surprise` always (confident work reversed); add `--escalated` since Step 4 just bumped the retry's model tier (`_model_tiering.md` Section B):
    ```bash
    python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue <N> --stage execute --role <tech-lead|security|infra|…> --area "<the variant's SIGNAL AREA>" --summary "<what was reversed, 1 line>" --evidence "<the BLOCKED non-conformance/finding, 1 line>" --surprise --escalated
    ```
    For the **evidence-contradicts-green** case (developer claimed green, the raw runner disagreed) use `--kind verify-gap --role developer` instead — the same claimed↔raw shape as the test stage, caught earlier at execute. **Skip** when no loop-back occurred (all `DONE`/green) — a passed conformance check is not a signal (agreement ≠ correction). **When the stagnation guard fires** (identical reason repeated), capture `--kind stagnation` instead (`_stagnation.md` Section C) — the recurrence is the signal, not a single role's reversal; drop `--escalated` there (a stagnant loop-back does not retry at all, so no tier was bumped).
- Any `FAIL` → return `FAIL: <reason>`. ⚠ **Except the Step 3.5a auditor**: it is offered only three tokens and holds no gate, so a `FAIL:`/`BLOCKED:` from it is a contract slip, not a hard error — demote it in place per Step 3.5a and continue.

## Step 5 — Open PR

As the leader, push the branch and open a PR referencing the Issue. The PR is where the **human reviewer** (M1's external reviewer) approves. **Resume-safe**: if a PR for this branch already exists (interrupted prior run), PATCH it rather than opening a duplicate. **Unattended (`GLD_UNATTENDED=1`)**: render a `## 무인 결정 로그 (GLD_UNATTENDED)` section **inside the `<!-- guild:execute:unattended-log -->` marker pair** (replaced in place, never appended — an append duplicates the section on every resume pass) aggregating the leader-proxy gate decisions recorded in the analyze/design outputs (chosen interpretation · charter rationale · "사람 확인 요") — `_handoff.md` Section H — so the deferred human gate (PR review) is informed, not blind.

**Render the body with markers** (`_handoff.md` Section B, *PR-body markers*) — temp-file + `--body-file`:

```
Closes #<N>
Base: <base-branch> · Branch point: <branch-point> <on the switch path add: (merge-base estimate — not the recorded fork point)> · <stack-warning>

<!-- guild:execute:pr-body -->
<the variant's PR SUMMARY>

**Specialist concerns**: <one line per conditional-role concern, or "none">

**Audit** (Step 3.5a adversarial auditor): one of — `<n>건 (BLOCKER <b>/MAJOR <m>/MINOR <i>)` · `발견 없음` · `감사자 미실행 — <사유>`
<one line per BLOCKER-severity finding the leader advanced past, with its reason — omit if none>
<"inv2-findings.md commit failed — <reason>" if Step 4's commit did not land>

**Verification findings** (INV2-related — read these first): <one line per `axis: verification` finding, as "<inv2 signature> — <file>:<line> — <finding>"; or "none">
Recorded at: docs/specs/<N>/inv2-findings.md   <omit this line when there were none>
<!-- /guild:execute:pr-body -->
```

- **`Closes #<N>` and the base/branch-point line stay OUTSIDE the markers** — `Closes` is INV1's auto-close linchpin and must not be re-rendered content; the base line is the only signal a PR reviewer gets that this branch may have been cut from another feature branch (`<stack-warning>` non-empty).
- **Omit an empty field rather than rendering it blank** — no `<stack-warning>` means no trailing ` · `, and an empty `<branch-point>` drops the whole `Branch point:` clause.
- **On a loop-back the audit lines accumulate, they do not overwrite** — one labelled block per loop (`loop 1`, `loop 2`). A later loop resolving an earlier finding is itself worth seeing.
- **Unattended runs** additionally emit a `<!-- guild:execute:unattended-log -->` … `<!-- /guild:execute:unattended-log -->` block recording decisions taken without a human.
- **If the PR already exists** (resume path): **read the current body first** (`gh pr view <PR> --json body --jq .body`), replace only the text between **this stage's marker pairs** (`guild:execute:pr-body`, plus `guild:execute:unattended-log` on unattended runs) **in the fetched text**, then write the whole re-rendered body back with `gh pr edit <PR> --body-file <temp>`. ⚠ **There is no partial-patch primitive for a PR body** — `--body-file` always replaces all of it, which is exactly why the read-first step is mandatory (`qa.md` states the same for its own marker). Do **not** rebuild the body from your own knowledge — `qa.md`'s `<!-- guild:manual-qa -->` block and any human-written prose live outside these markers and a full rebuild destroys them.
- If the existing body has no marker pair (a PR opened before markers existed), append a fresh marked block at the end rather than rewriting what is there.

**Both the push and the PR call are state mutations — `_handoff.md` Section F (`gh` write failures) governs them**: verify each landed (the push's remote ref exists; `gh pr create` returned a non-empty PR URL), one retry only if transient, and **never report a failed push/PR as success**. Failure paths:

- **No remote configured** (`git remote -v` empty) → terminal: `FAIL: no git remote — the PR step requires one; the work is committed on branch <branch>`.
- **Push rejected (non-fast-forward)** — the remote branch diverged. **Do NOT force-push and do NOT rewrite history** (INV3). Re-read the divergence (`git fetch`, then `git log --oneline origin/<branch>..<branch>` / the reverse) and escalate: **attended** → `NEEDS_HUMAN: branch <branch> diverged from origin — resolve before the PR`; **unattended** → `guild:needs-human` label + comment, `OK PAUSE: needs-human — branch diverged from origin` (do NOT transition).
- **Protected branch / push permission denied** → terminal `FAIL:` (a retry cannot help — `_handoff.md` Section F).
- **A PR already exists for this branch** — not an error: this is the resume-safe case above. Find it (`gh pr list --head <branch> --state open`) and PATCH its body instead of creating a second PR.
- **PR creation fails otherwise** — template/validation (422) or insufficient permission (403) → terminal `FAIL: gh pr create failed for #<N> — <gh error>`; rate limit / 5xx / network → one retry, then the same `FAIL`.

In every failure case the branch still holds the committed work — say so, and do **not** return `OK ADVANCE: test`: work with no open PR has no human reviewer (INV1), so the stage has not advanced.

## Step 6 — Transition + return

Remove **whatever `guild:*` stage label Step 0 actually found** (substitute in place of `guild:execute` below if it was something else — `gh issue edit --remove-label` on a label the Issue doesn't carry can error; **never remove `guild:child`** if present — `_handoff.md` Section A). **Also remove `guild:needs-human` in this same call if Step 0's label read found it present** (`_handoff.md` Section A):

```bash
gh issue edit <N> --remove-label "guild:execute" --add-label "guild:test" --remove-label "guild:needs-human"
```

Return:

```
>>> RESULT <<<
OK ADVANCE: test
```

Other returns: `NEEDS_HUMAN`, `NEEDS_CONTEXT`, `FAIL`, `OK PAUSE: needs-human — <one-line>` (do NOT transition).

---

## Hard rules (all three variants)

- **Verify evidence is mandatory** (`_handoff.md` Section E): no "green" claim without the raw runner output; raw output wins over self-report.
- **No verification weakening** (INV2): the developer must not delete/skip/weaken tests to pass. If a test must change, it requires an explicit, justified reason surfaced to the human.
- **Conformance is by the tech-lead, not self-review** (roles don't self-check).
- Artifacts/inputs pass as files; RESULT lines stay one line.
- **Slots only** — a variant may fill the Section A slots and add its own hard rules; it may not quietly re-word a spine step. Behavior (return tokens, labels, markers, tiers, retry bound, capture rules) is defined here, once.
