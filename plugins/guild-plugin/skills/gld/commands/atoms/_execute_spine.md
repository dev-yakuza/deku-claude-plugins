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

Create/switch to the branch for this Issue using the variant's **BRANCH + RESUME PROBE** prefix (follow the repo's branch convention from conventions.md; e.g. `feature/#<N>-<slug>` for implement). Do this as the leader **before** spawning the developer, so the developer works on the branch. **Resume-safe (rate-limit/interruption)**: if a branch for this Issue **already exists** (a prior interrupted execute), switch to it and build a concise **partial-work summary** — `git log <base>..HEAD --oneline` (what's committed) **plus one run of the test command**, read per the variant's RESUME PROBE (where the work left off). This summary is passed into the developer prompt (Step 1) so it **continues from the partial state, not from scratch**. Only create the branch (no summary) if absent. ("중단 내성" — mid-execute resume.)

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

## Step 3.5 — Conditional specialists + gate reviews (leader)

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

As the leader, over the developer + tech-lead + any conditional specialist/gate verdicts:

- Developer `DONE`/`DONE_WITH_CONCERNS` + tech-lead `DONE`/`DONE_WITH_CONCERNS` + all gate/specialist verdicts `DONE`/`DONE_WITH_CONCERNS` + raw evidence green **as the variant's EVIDENCE RULE defines green** → proceed to Step 5. Record specialist concerns in the PR body.
- Tech-lead `BLOCKED` (a failure of the variant's **CONFORMANCE CHECKS**), a **gate `BLOCKED`** (e.g. security vulnerability), OR evidence contradicting the EVIDENCE RULE → before looping back, apply the **stagnation guard** (`_stagnation.md`): compare this reason against the immediately-prior loop-back's reason for this Issue (if any). **Same root cause repeated** → stagnation — escalate immediately (`_stagnation.md` Section B) instead of consuming another attempt. **Different concern** → **defined loop back to execute**: re-invoke the developer (Step 1) — and the tech-lead/gate role whose `BLOCKED` triggered this — **at one model tier above their default** (`_model_tiering.md` Section A: sonnet → opus; attempt 1 always ran at the default, this is the one bounded retry), with the specific concern. Bounded — after ~2 loops without resolution: **Attended** → return `NEEDS_HUMAN: <one-line>`. **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H — detect via `printenv GLD_UNATTENDED`): there is no human to answer `NEEDS_HUMAN` here, so treat bounded-retry exhaustion the same as a stagnation escalation — add the **`guild:needs-human` label** + a `<!-- guild:needs-human -->` comment stating the unresolved concern, and return `OK PAUSE: needs-human — <one-line>` (do NOT transition the stage label). This mirrors `test.md`/`qa.md`'s unattended handling at their own bounded-retry exit.
  - **Ground-truth capture (①, `_signals.md` Section C — agent↔agent correction):** when this loop-back fires on a **real reversal** (a `BLOCKED`, or raw evidence contradicting a claimed green — **not** a mere `DONE_WITH_CONCERNS`), append one entry (its own Bash call, best-effort — never blocks the loop). The `BLOCKED` non-conformance/finding (or the contradicting raw line) **is** the objective anchor — a role overturning *another* role's confident output, not self-review (`_signals.md` Section B). `--surprise` always (confident work reversed); add `--escalated` since Step 4 just bumped the retry's model tier (`_model_tiering.md` Section B):
    ```bash
    python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue <N> --stage execute --role <tech-lead|security|infra|…> --area "<the variant's SIGNAL AREA>" --summary "<what was reversed, 1 line>" --evidence "<the BLOCKED non-conformance/finding, 1 line>" --surprise --escalated
    ```
    For the **evidence-contradicts-green** case (developer claimed green, the raw runner disagreed) use `--kind verify-gap --role developer` instead — the same claimed↔raw shape as the test stage, caught earlier at execute. **Skip** when no loop-back occurred (all `DONE`/green) — a passed conformance check is not a signal (agreement ≠ correction). **When the stagnation guard fires** (identical reason repeated), capture `--kind stagnation` instead (`_stagnation.md` Section C) — the recurrence is the signal, not a single role's reversal; drop `--escalated` there (a stagnant loop-back does not retry at all, so no tier was bumped).
- Any `FAIL` → return `FAIL: <reason>`.

## Step 5 — Open PR

As the leader, push the branch and open a PR referencing the Issue (temp-file body via `--body-file`; body references `Closes #<N>` and carries the variant's **PR SUMMARY**). The PR is where the **human reviewer** (M1's external reviewer) approves. **Resume-safe**: if a PR for this branch already exists (interrupted prior run), PATCH it rather than opening a duplicate. **Unattended (`GLD_UNATTENDED=1`)**: append a `## 무인 결정 로그 (GLD_UNATTENDED)` section to the PR body aggregating the leader-proxy gate decisions recorded in the analyze/design outputs (chosen interpretation · charter rationale · "사람 확인 요") — `_handoff.md` Section H — so the deferred human gate (PR review) is informed, not blind.

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
