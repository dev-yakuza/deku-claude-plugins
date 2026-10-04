# REFACTOR (stage: execute variant — refactor)

**Stage: execute, variant for `type:refactor`.** Roles: **developer** (behavior-preserving transform) with **tech-lead conformance** (structure improved *and* behavior preserved), plus the always-on external auditor and any conditional specialists (Step 3.5). Invocable directly (`/gld refactor <issue>`) or via `/gld dev` (auto-selected when the Issue is `type:refactor`). Same spine as `implement` (execute → test); the developer's task shape differs — code is **transformed without changing behavior**, so the **existing tests are the safety net** (no new feature test).

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## How to run this stage

Run **Steps 0–6 of `atoms/_execute_spine.md`** — Step 0 preflight (incl. the label read and the **`guild:children`** split-parent guard) · Step 1 spawn developer · Step 2 verify evidence · Step 3 tech-lead conformance · Step 3.5 external auditor (**always**) + conditional specialists/gates (`_handoff.md` Section G — a refactor touching a hot path → performance; schema → dba; etc. A gate `BLOCKED` blocks advancement, as does an auditor `BLOCKER`) · Step 4 arbitrate · Step 5 PR · Step 6 transition + return — filling its Section A slots with the values below. Nothing about the spine changes for this variant.

## Slot values (`type:refactor`)

**DESIGN INPUT** — load the design output — for a refactor the design **is the target structure** (design = 목표 구조). Load `docs/specs/$1/skeleton.md` (the target shape). Missing → `NEEDS_CONTEXT: design/target-structure not found for #$1`. Also read the Issue body (`gh issue view $1 --json body --jq .body`, its own call) for two things a sprint's refactor slot may carry (`sprint/plan.md` — Refactor slot): a **Safety net** section (behaviors to pin first), and the `<!-- guild:safety-net-only -->` line (no transform at all — only the net). Hold `SAFETY_NET = <none|with-refactor|only>`. (The spine's Heavy-tier preflight covers ⑥ knowledge + the target-dir survey.)

**BRANCH + RESUME PROBE** — a **refactor** branch, e.g. `refactor/#$1-<slug>`. The resume test-run confirms **all existing tests are still green on the partial work** → continue the transform, don't restart.

**DEVELOPER TASK SHAPE** — `description`: `developer refactor #$1`. Body inserted into the spine's Step 1 prompt:

> Refactor Issue #$1 on the current branch toward the target structure (`docs/specs/$1/skeleton.md`). **Resume**: CONTINUE the transform from the committed partial state (tests green), do not restart. **Behavior-preserving — this is the core constraint**:
> - The **existing tests MUST stay green throughout** — run them before and after; behavior does not change. They are your safety net.
> - Do **NOT** add features, change observable behavior, or **weaken/delete/skip tests** (INV2). If a test asserted an *implementation detail* that the refactor legitimately removes, surface it **explicitly with justification** in your RESULT — never silently drop it.
> - Prefer many small behavior-preserving steps, tests green at each.
> Capture the raw runner output (all green) as evidence.
> **Safety net — `SAFETY_NET = <none|with-refactor|only>`** (the leader substitutes; omit this paragraph when `none`). The Issue's Safety net section lists behaviors to pin (and visual cases, when present). Do this **first, before touching any production file**:
> 1. Add the tests (and visual tests + their images, per the visual-baselines rules below) for exactly those behaviors, and nothing else, as **one commit that changes only test files, visual baselines and `docs/specs/`**. Run the test command (and the visual run, when you can) **at that commit** — the code is still unchanged, so a green run there is the proof the net pins today's behavior. A safety-net test that is red on unchanged code is pinning something the code does not do: fix the test, never the code.
> 2. Test **public behavior only** — exported functions, a component's rendered states, a module's documented contract. No private functions, no mocks of the file's own internals, no snapshot of internal structure: a test that pins implementation blocks this refactor and the next.
> 3. A behavior that looks like a bug is **not** pinned — report it under `findings:` in your RESULT for the human.
> 4. `with-refactor`: then do the transform in later commits **without touching the safety-net files** — they are the referee; editing them after the fact unpins them. `only`: stop after step 1 — no production file changes in this Issue.
> RESULT extras for this paragraph: `safety-net: <commit sha>` and the raw summary of the run at that commit.

RESULT extras: the raw test summary (all green), **what structural improvement was made** (`only`: the behaviors now covered), and the branch.

**EVIDENCE RULE** — **all existing tests must be green** (there is no new feature test — a Safety net adds characterization tests that pin existing behavior, which is not the same thing). A refactor that turns a test red has changed behavior (or broke something); that is not-done, loop back. **Visual baselines are existing tests too**: the spine's Step 2 ledger must hold **no `C`, `M`, `D`, `P` or replacing `A`, and no `A` without an existing visual case** (an `R` — the image moved byte-for-byte with its component — is fine) — a rewritten image or a loosened comparison means the screen (or what counts as the same screen) changed, which a behavior-preserving transform does not do. A declared reason does not rescue it here (unlike `implement`/`debug`): loop back, or surface it to the human as a scope change. If the developer changed any test, verify the justification is real — **implementation-detail only, not a weakened assertion**.
**Safety net (`SAFETY_NET` ≠ `none`)** — resolve `<mb>` (`git merge-base <base> HEAD`, its own call), then each its own call, with the developer's `safety-net:` sha substituted:
```bash
git diff --name-only <mb> <safety-net-sha>
```
```bash
git diff --name-status <safety-net-sha> HEAD -- <each path the first call listed>
```
Not-done (loop back) when: the RESULT has no `safety-net:` line or no raw green run at that commit; the first call lists anything that is not a test path, a visual baseline (`visual.baselines`) or under `docs/specs/` (production code changed before the net existed, so the run did not prove today's behavior); or the second call lists anything (a net edited after the refactor started no longer referees it). Visual images added in that commit are `A` rows citing their visual case — the ledger rule above already accepts them. `only` additionally: `git diff --name-only <mb>...HEAD` (its own call) lists only test paths, visual baselines and `docs/specs/` — a production file there means this was not a safety-net-only change.

**CONFORMANCE CHECKS** — inserted into the spine's Step 3 prompt:

> Review the refactor on the current branch against the target structure (`docs/specs/$1/skeleton.md`) + `docs/standards/architecture.md`. ⚠ **Read it whole, in one Read.** You are checking against the *whole* intent, so a clause you did not read is one this change passes silently — and an empty finding list is what clean work looks like, so the failure is invisible. The Read tool returns up to 2000 lines and does not say when it stopped: compare the last line number you got against the file's length, page from there if they differ, and say so if you still cannot get all of it. Check TWO things: (1) is the **structure genuinely improved** toward the target (not churn)? (2) is **behavior preserved** — no functional change, and **no test weakened/removed** except a justified implementation-detail test? **When the Issue carries a Safety net** (mode: <with-refactor|only>, substituted by the leader): also check that the new tests cover the Issue's listed behaviors and test **public behavior only** (no private functions, no mocks of the file's own internals, no structural snapshots) — a test that pins implementation is a `BLOCKED`, because it blocks the next change. For `only`, check (2) and this coverage check **instead of** (1): there is no structure to improve. Your `BLOCKED` line names the non-conformance *or* the behavior/verification change.

A tech-lead `BLOCKED` here means **structure not improved (not for `only`), behavior changed, a test weakened, or a safety net that pins implementation or misses a listed behavior** — that, or a test going red, is the Step 4 loop-back trigger for this variant.

**SIGNAL AREA** — `--area "<the refactored file/area>"`; typical `--role` set `<tech-lead|performance|…>`. A **weakened-verification** reversal (a refactor that quietly removed/weakened a test, caught here) is exactly the INV2 signal worth capturing.

**PR SUMMARY** — what structure improved, the behavior-preserved statement, and the existing-tests-green evidence. With a Safety net: the behaviors pinned, the `safety-net:` commit, and its green run on the unchanged code; any `findings:` (suspected bugs left unpinned) listed for the human. `only`: say plainly that this PR adds coverage and changes no production code.

## Hard rules

Spine-common rules apply — **read `_execute_spine.md`'s "Hard rules" section directly; it is the authority and it is longer than this summary**, notably the auditor rules (3.5a never gates by itself and never edits, and the mutation check around it — `git diff --numstat --no-renames <mb>` + `git status --porcelain -uall`, compared before/after — is mandatory on **every** path — a standalone run of this variant that skips them loses the mutation check entirely). The most-cited ones, for orientation: verify evidence mandatory · no verification weakening (INV2) · conformance by the tech-lead, not self-review · artifacts as files, one-line RESULT. Refactor-specific, on top:

- **Behavior preservation is the contract** — existing tests green **before and after**; a red test = behavior changed = not a refactor.
- **No verification weakening** (INV2 — *especially* critical for refactor, where "cleaning up" can quietly drop tests). A changed test needs an explicit, justified, implementation-detail-only reason surfaced to the human.
- **Structure must actually improve** (tech-lead judges — not churn for its own sake). **No new features.** (A safety-net-only Issue improves coverage instead, and changes no production file.)
- **Safety net first, then hands off** — added in its own commit before any production change, green on the unchanged code, and never edited after the transform starts. Public behavior only; a suspected bug is reported, not pinned.
