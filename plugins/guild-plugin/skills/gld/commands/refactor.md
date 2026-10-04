# REFACTOR (stage: execute variant — refactor)

**Stage: execute, variant for `type:refactor`.** Roles: **developer** (behavior-preserving transform) with **tech-lead conformance** (structure improved *and* behavior preserved), plus the always-on external auditor and any conditional specialists (Step 3.5). Invocable directly (`/gld refactor <issue>`) or via `/gld dev` (auto-selected when the Issue is `type:refactor`). Same spine as `implement` (execute → test); the developer's task shape differs — code is **transformed without changing behavior**, so the **existing tests are the safety net** (no new feature test).

`$1` = Issue number. Returns a Section D line.

> **Bash**: `_bash_rules.md`. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); sub-agent prompts carry that instruction.

---

## How to run this stage

Run **Steps 0–6 of `atoms/_execute_spine.md`** — Step 0 preflight (incl. the label read and the **`guild:children`** split-parent guard) · Step 1 spawn developer · Step 2 verify evidence · Step 3 tech-lead conformance · Step 3.5 external auditor (**always**) + conditional specialists/gates (`_handoff.md` Section G — a refactor touching a hot path → performance; schema → dba; etc. A gate `BLOCKED` blocks advancement, as does an auditor `BLOCKER`) · Step 4 arbitrate · Step 5 PR · Step 6 transition + return — filling its Section A slots with the values below. Nothing about the spine changes for this variant.

## Slot values (`type:refactor`)

**DESIGN INPUT** — load the design output — for a refactor the design **is the target structure** (design = 목표 구조). Load `docs/specs/$1/skeleton.md` (the target shape). Missing → `NEEDS_CONTEXT: design/target-structure not found for #$1`. Also read the Issue body (`gh issue view $1 --json body --jq .body`, its own call) for the two ASCII markers a sprint's refactor slot may carry (`sprint/plan.md` — Refactor slot): `<!-- guild:safety-net -->` (a Safety net — behaviors to pin first) and `<!-- guild:safety-net-only -->` (no transform at all — only the net). Hold `SAFETY_NET` = `only` when the second is present, `with-refactor` when only the first is, else `none`. The behaviors themselves come from `docs/specs/$1/test-cases.md`'s cases tagged `(safety net)` (analyze made each net line an AC; design made each AC a case) — that list, not the Issue's prose, is what the test stage will check coverage against. (The spine's Heavy-tier preflight covers ⑥ knowledge + the target-dir survey.)

**BRANCH + RESUME PROBE** — a **refactor** branch, e.g. `refactor/#$1-<slug>`. The resume test-run confirms **all existing tests are still green on the partial work** → continue the transform, don't restart.

**DEVELOPER TASK SHAPE** — `description`: `developer refactor #$1`. Body inserted into the spine's Step 1 prompt:

> Refactor Issue #$1 on the current branch toward the target structure (`docs/specs/$1/skeleton.md`). **Resume**: CONTINUE the transform from the committed partial state (tests green), do not restart. **Behavior-preserving — this is the core constraint**:
> - The **existing tests MUST stay green throughout** — run them before and after; behavior does not change. They are your safety net.
> - Do **NOT** add features, change observable behavior, or **weaken/delete/skip tests** (INV2). If a test asserted an *implementation detail* that the refactor legitimately removes, surface it **explicitly with justification** in your RESULT — never silently drop it.
> - Prefer many small behavior-preserving steps, tests green at each.
> Capture the raw runner output (all green) as evidence.
> **Safety net — `SAFETY_NET = <none|with-refactor|only>`, earlier net: `<the previous <!-- guild:safety-net-evidence --> block — only when it says verified: yes — or none>`** (the leader substitutes both, reading the previous block with the same early read Step 1 does for the visual paragraph; omit this paragraph when `none`). The cases tagged `(safety net)` in `docs/specs/$1/test-cases.md` — behavior rows and visual rows — and the Issue's named test-support files are the net. **If an earlier net block is given, the net already exists**: do not lay it again; carry on from step 5. Otherwise do this **first, before touching any production file**:
> 1. Write the net in **new test files of its own**, named so that **a runner Guild can run here** picks them up — `commands.test`, or `commands.vrt` when `visual.runnable` is true (`index.safety-net.test.tsx` when `commands.test` is Jest and the visual runner is not runnable, `index.safety-net.vitest.tsx` when it is, `foo_safety_net_test.dart`) — never inside an existing test file, which would freeze its older tests along with the net. A behavior case no runnable runner can host → `NEEDS_CONTEXT: no runnable runner for <case>`; a net that is never run proves nothing. Name every net image with a `safety-net-` prefix, so it is a new image and never a comparison against an existing one. Include the visual tests and their images for the `(safety net)` visual rows (per the visual-baselines rules below). Commit them as **one commit that changes only those new files, their images, the Issue's named test-support files and `docs/specs/`**. Run the test command — and the visual run, under the same conditions the visual-baselines rules give — **at that commit**, with a reporter that names each test file it ran (e.g. `--reporter=verbose`): the production code is still unchanged, so a green run there is the proof the net pins today's behavior. A net test that is red on unchanged code is pinning something the code does not do: fix the test, never the code.
> 2. Test **public behavior only**, through the module's public entry point — exported functions, a component's rendered states, a documented contract. No private functions, no mocks of the file's own internals, no snapshot of internal structure. Each test must **fail if its behavior broke** — a render-without-crash test for a behavior about timing or position covers nothing.
> 3. A behavior that looks like a bug is **not** pinned — report it under `findings:` in your RESULT for the human.
> 4. Untestable without a seam: first use what the repo already has (fake timers, the browser test mode, the test helpers in the Issue). Only a behavior that none of those can reach is deferred — return `DONE_WITH_CONCERNS: untestable without a seam: <behavior> — needs <seam> — tried: <the repo's tools you tried and why each cannot reach it>`, with the rest of the net done. Do not write a test that passes without exercising it, and do not add the seam in the net's commit.
> 5. `with-refactor`: then do the transform in later commits. The net is the referee — **never change its assertions**. Allowed to a net file after the transform started: moving it with the code it tests (a byte-identical rename), and changing only its import lines when a module moved. Missing coverage found later (e.g. a tech-lead loop-back) may be **added in new files only** — never a case added to, or an edit of, an existing net file — in their own commit, listed under `post-transform-net:`; they are shown to the human as *not* proven on unchanged code, and from then on they are frozen like the rest of the net. A net assertion that goes red under the transform means the transform changed behavior: fix the transform. `only`: stop after step 1 — no production file changes in this Issue.
> RESULT extras for this paragraph: `safety-net: <commit sha>` (or `existing` when an earlier block was given), the raw summary of the run at that commit, and `post-transform-net: <paths or none>`.

RESULT extras: the raw test summary (all green), **what structural improvement was made** (`only`: the behaviors now covered), and the branch.

**EVIDENCE RULE** — **all existing tests must be green** (there is no new feature test — a Safety net adds characterization tests that pin existing behavior, which is not the same thing). A refactor that turns a test red has changed behavior (or broke something); that is not-done, loop back. **Visual baselines are existing tests too**: the spine's Step 2 ledger must hold **no `C`, `M`, `D`, `P` or replacing `A`, and no `A` without an existing visual case** (an `R` — the image moved byte-for-byte with its component — is fine) — a rewritten image or a loosened comparison means the screen (or what counts as the same screen) changed, which a behavior-preserving transform does not do. A declared reason does not rescue it here (unlike `implement`/`debug`): loop back, or surface it to the human as a scope change. If the developer changed any test, verify the justification is real — **implementation-detail only, not a weakened assertion**.
**Safety net (`SAFETY_NET` ≠ `none`)** — the proof lives in an ASCII block the leader keeps in this Issue's execute evidence comment (`<!-- guild:test-evidence:step-1 -->`) and writes **inside Step 2's one PATCH of that comment**; on re-entry it is read by the same early read Step 1 does for the visual paragraph (the paginated `contains("<!-- guild:test-evidence:step-1 -->")` call) and carried into the new version:
```
<!-- guild:safety-net-evidence -->
verified: <yes|no>
sha: <safety-net commit>
run: <the raw summary lines of the green run at that commit — one per net file>
net: <the net's files, one per line, prefixed "- "; post-transform-net files join this list>
deferred: <case> — needs <seam> — tried: <…>   (one line each, or "none")
post-transform-net: <paths, or none>
<!-- /guild:safety-net-evidence -->
```
On the attempt that lays the net, build it from the developer's RESULT and run the checks below **before** writing `verified: yes`; a later attempt with `verified: yes` is told the net exists and the checks run against its `sha`. Each its own call:
```bash
git merge-base <base> HEAD
```
```bash
git diff --name-only <mb> <sha>
```
```bash
git diff --name-status -M <sha> HEAD
```
(no pathspec on the last call, and git's default rename similarity: git pairs renames only among the paths it is given, and at `100%` a net file moved **and** given a new import line never pairs — both read as `D` + `A`). Not-done (loop back) when:
- `run:` does not show **every** `net:` file executed and green at `sha` (a Jest summary does not prove a Vitest file ran) — or there is no `sha:`;
- the second call lists anything outside the net's new files, their images, the Issue's named test-support files and `docs/specs/` (production code changed before the net existed, so that run proved nothing about today's behavior), or a `(safety net)` visual row's image is not among them (an image made after the transform pins the transformed code);
- in the third call, a `net:` file appears as `D` with no pairing, or as `M`/`R<100` whose change is not **import lines only** — check each with `git diff -U0 -M <sha> HEAD -- <old path> <new path>` (its own call): every changed line must be an `import`/`require`/`export … from` line. `R100` is fine. Any other change unpins the net.
When a check fails on the attempt that lays the net, write `verified: no` and loop back with *"re-lay the net from step 1"*: this happens before Step 5 opens the PR, so the developer resets the branch to `<mb>` (`git reset --hard <mb>`, its own call), lays the net as one commit, and re-applies the transform after it. `post-transform-net:` paths must be **new** files (status `A` in the third call); they join `net:`. A `deferred:` line is not a loop-back by itself, but the tech-lead confirms it (Step 3) — and when the deferred behavior lies in the code the transform reshapes, the transform must not proceed over it: loop back to drop that part of the transform, or `NEEDS_HUMAN` when it cannot be separated. Deferred cases are listed in the PR as holes with the seam each needs. `only` additionally: `git diff --name-only <mb>...HEAD` (its own call) lists only the net's files, their images, named test-support files and `docs/specs/` — a production file there means this was not a safety-net-only change.

**CONFORMANCE CHECKS** — inserted into the spine's Step 3 prompt:

> Review the refactor on the current branch against the target structure (`docs/specs/$1/skeleton.md`) + `docs/standards/architecture.md`. ⚠ **Read it whole, in one Read.** You are checking against the *whole* intent, so a clause you did not read is one this change passes silently — and an empty finding list is what clean work looks like, so the failure is invisible. The Read tool returns up to 2000 lines and does not say when it stopped: compare the last line number you got against the file's length, page from there if they differ, and say so if you still cannot get all of it. Check TWO things: (1) is the **structure genuinely improved** toward the target (not churn)? (2) is **behavior preserved** — no functional change, and **no test weakened/removed** except a justified implementation-detail test? **When the Issue carries a Safety net** (mode: <with-refactor|only>, substituted by the leader): also check that the new tests cover every `(safety net)` case in `docs/specs/$1/test-cases.md`, test **public behavior only** (no private functions, no mocks of the file's own internals, no structural snapshots), and would each **fail if their behavior broke** (ask it of every assertion — a render-without-crash test for a timing or position behavior covers nothing) — a test that pins implementation, or one that cannot fail, is a `BLOCKED`. For each deferred case — `<the deferred: lines of the safety-net evidence block, or none>` (substituted by the leader) — confirm the developer's "tried" line: if the repo's own test tooling (fake timers, browser mode, existing helpers) could reach it, that deferral is a `BLOCKED`. For `only`, check (2) and this coverage check **instead of** (1): there is no structure to improve. Your `BLOCKED` line names the non-conformance *or* the behavior/verification change.

A tech-lead `BLOCKED` here means **structure not improved (not for `only`), behavior changed, a test weakened, or a safety net that pins implementation or misses a listed behavior** — that, or a test going red, is the Step 4 loop-back trigger for this variant.

**SIGNAL AREA** — `--area "<the refactored file/area>"`; typical `--role` set `<tech-lead|performance|…>`. A **weakened-verification** reversal (a refactor that quietly removed/weakened a test, caught here) is exactly the INV2 signal worth capturing.

**PR SUMMARY** — what structure improved, the behavior-preserved statement, and the existing-tests-green evidence. With a Safety net: the behaviors pinned, the `safety-net:` commit, and its green run on the unchanged code (and, when no visual net was laid because visual tests are not runnable here, one line saying the screen has no visual net); any `post-transform-net:` tests, labelled as **not** proven on unchanged code; deferred behaviors (untestable without a seam) with the seam each needs; and any `findings:` (suspected bugs left unpinned) for the human. `only`: say plainly that this PR adds coverage and changes no production code.

## Hard rules

Spine-common rules apply — **read `_execute_spine.md`'s "Hard rules" section directly; it is the authority and it is longer than this summary**, notably the auditor rules (3.5a never gates by itself and never edits, and the mutation check around it — `git diff --numstat --no-renames <mb>` + `git status --porcelain -uall`, compared before/after — is mandatory on **every** path — a standalone run of this variant that skips them loses the mutation check entirely). The most-cited ones, for orientation: verify evidence mandatory · no verification weakening (INV2) · conformance by the tech-lead, not self-review · artifacts as files, one-line RESULT. Refactor-specific, on top:

- **Behavior preservation is the contract** — existing tests green **before and after**; a red test = behavior changed = not a refactor.
- **No verification weakening** (INV2 — *especially* critical for refactor, where "cleaning up" can quietly drop tests). A changed test needs an explicit, justified, implementation-detail-only reason surfaced to the human.
- **Structure must actually improve** (tech-lead judges — not churn for its own sake). **No new features.** (A safety-net-only Issue improves coverage instead, and changes no production file.)
- **Safety net first, then hands off** — added in its own commit before any production change, green on the unchanged code, and never edited after the transform starts. Public behavior only; a suspected bug is reported, not pinned.
