# Audit 6: Static Execution Trace

Phase C audit. Walks 5 sample call graphs through the v1.0.0 atoms and stage
files, citing `file:line` for each transition.

---

## Trace 1: Fresh Issue → `/sdd analyze <N>`

Starting state: Issue exists, no SDD labels, no SDD marker comments.

1. User invokes `/sdd analyze N`. Entry point is
   `plugins/sdd-plugin/skills/sdd/commands/analyze.md:1-46`.
2. **Issue Validation** (`analyze.md:11-13`) defers to `SKILL.md` Common
   Definitions. If `$1` is a PR, stops.
3. **Direct-invocation label check** (`analyze.md:15-29`) runs
   `gh issue view $1 --json labels --jq '[.labels[].name]'`. Fresh Issue with
   no `sdd:*` label → fall-through (line 23 — "no `sdd:*` label OR
   `sdd:analyze` → continue").
4. **Phase 0 depth detection** (`analyze.md:31-36`). No `sdd:review:deep` /
   `sdd:review:shallow` → `depth = default`.
5. **Phase 1 — spawn `stage_analyze`** (`analyze.md:38-55`). One `Agent` call,
   `subagent_type=general-purpose`, `model=opus`, prompt forwards
   `Issue / Depth=default / Resume=none`.
6. Sub-agent enters `commands/atoms/stage_analyze.md`:
   - §1 Issue Validation (`stage_analyze.md:23-35`) re-validates.
   - §2 Phase 0 depth detection (`stage_analyze.md:39-52`) re-derives depth.
   - §2 Resume short-circuit (`stage_analyze.md:55-60`): `$3 == none` so
     short-circuit is SKIPPED (only fires on `continue-after-escalation`).
7. **§3 Phase 1 Work** (`stage_analyze.md:64-237`):
   - Step 0 Preflight Light tier (`stage_analyze.md:70-76`).
   - Steps 1-8 (`stage_analyze.md:78-169`) produce the analyze body.
   - Step 12 posts via Section F to
     `/tmp/sdd-analyze-output-$1.md` with marker
     `<!-- sdd:analyze:output -->` (`stage_analyze.md:210-228`).
8. **§4 Phase 2 Reviews — SERIAL** (`stage_analyze.md:240-345`). Reviewer 1
   completeness (§4.1, `:249-311`) → Reviewer 2 quality (§4.2, `:313-327`) →
   Reviewer 3 adversarial (§4.3, `:329-345`). Each posts its
   `<!-- sdd:review:analyze:<role> -->` marker via Section F.
9. **§5 Phase 3 Verdict combination** (`stage_analyze.md:349-377`). All 3
   PASS → Round-decision branch "All 3 PASS → §8 Phase 6 (Normal path)"
   (`stage_analyze.md:374`).
10. **§8 Phase 6 — Normal path** (`stage_analyze.md:446-460`). Sub-agent
    returns the line `OK ADVANCE: design` after the `>>> RESULT <<<` sentinel.
11. Back in `analyze.md`, **Phase 2 parser** (`analyze.md:57-72`) matches
    `OK ADVANCE: design`:
    - Label transition `--remove-label sdd:analyze --add-label sdd:design`
      (the remove is a no-op on a fresh Issue — `analyze.md:62-66`).
    - Reads `.github/.sdd-config` skip-review (`analyze.md:67`).
    - If `design` in skip-review → inline-Read `commands/design.md`
      (`analyze.md:68-69`). Else → prompt user to run `/sdd design $1`.

**Verdict: SOUND.** Every step has a citation; the call graph is single-spawn
single-level (`analyze.md` → `stage_analyze.md`) per Common Contracts §12.
Markers posted match `spec/stage/analyze.md` §2 listing in
`stage_analyze.md:504-516`.

---

## Trace 2: `/sdd resume <N>` with existing branch + open PR (R8 case)

Starting state: Issue has `sdd:implement` label, `feat-N` branch exists, open
PR #X references `Refs #N`.

1. User invokes `/sdd resume N`. Entry `commands/resume.md:1-31`.
2. **Step 1 — spawn bootstrap** (`resume.md:17-31`) with model=haiku.
3. Bootstrap (`commands/atoms/bootstrap.md`) runs Steps 1-9
   (`bootstrap.md:19-138`):
   - Step 7 PR detection (`bootstrap.md:84-99`):
     `gh pr list --search "Refs #$1" --state open --json number,headRefName`
     returns PR #X + `feat-N`. So `pr=#X`, `branch=feat-N`.
   - Step 8 decision table (`bootstrap.md:101-115`): label `sdd:implement` +
     not parent → `stage = implement`.
   - Step 9 emits
     `BOOTSTRAP: stage=implement depth=default branch=feat-N pr=#X parent=false children=null`
     (`bootstrap.md:117-138`).
4. `resume.md` parses (`resume.md:27-31`). Dispatch hits
   `analyze/design/implement/test` branch (`resume.md:73-87`). Skip-review
   handling (`resume.md:75-77`). Then `implement` →
   inline-Read `commands/implement.md` (`resume.md:82`).
5. `implement.md` runs in main session. Direct-invocation label check
   (`implement.md:19-41`) — `sdd:implement` matches, continues. Precondition
   check (`implement.md:43-57`) confirms `<!-- sdd:design:output -->`.
6. **Phase 1 spawn** (`implement.md:66-85`). Spawn `stage_implement` with
   `Resume=none`, `Branch=null`, `PR=null` — note: the wrapper passes `null`
   for branch/PR even though bootstrap detected them (lines 80-81). This is
   intentional: `main.md:31-34` documents `$4`/`$5` as CACHE HINTS and the
   sub-agent **re-derives from GitHub regardless**.
7. Sub-agent enters `commands/atoms/stage_implement/main.md`:
   - §1 Issue Validation (`main.md:38-50`).
   - §2 Precondition design output (`main.md:54-70`).
   - §3 Phase 0 depth (`main.md:73-90`).
   - §4 Resume routing (`main.md:94-126`): `$3 == none` → §4.3 → continue to
     §5 Phase 1.
   - §5.1 Detect children (`main.md:134-141`) — no `<!-- sdd:children:output -->`
     → §6 Phase 2.
   - §6.2 Step 1 Read context (`main.md:170-176`).
   - §6.4 Step 3 Create or reuse feature branch (`main.md:188-210`):
     `git rev-parse --verify <branch_name>` — branch exists → `git checkout`.
   - §6 Phase 2 plan posting via Section F update-in-place
     (`main.md:240-284`).
   - §7 Phase 3 TDD pipeline reads `_tdd.md` (`main.md:292-313`). R9
     idempotency (`_tdd.md:65-100`) detects prior step-evidence + step-review
     markers if present; otherwise runs fresh.
8. **CRITICAL R8 PATH — `_pr_final.md` §3.5** (`_pr_final.md:61-69`):
   `gh pr list --head <branch_name> --state open --json number --jq '.[0].number'`
   returns PR #X. → R8 auto-route.
9. **§3.6.1 Defensive verification** (`_pr_final.md:74-82`):
   `gh pr view <EXISTING_PR> --json body --jq .body` — body must contain
   `Refs #$1`. If yes → §3.6.2.
10. **§3.6.2 Soft retry path** (`_pr_final.md:84-94`): SKIPS PR creation
    (`§3.7`), sets `<PR_NUM> = X`, treats Phase 4 as complete, enters Phase
    5 PR Final round 1 against the existing PR.

**Verdict: SOUND.** The R8 path is consistent. One concern documented in
`main.md:31-34` and reinforced at `implement.md:80-81`: branch/PR hints are
intentionally discarded, with sub-agent re-derivation as authority. The Phase
2 Plan re-runs each time — `main.md:240-282` PATCHes the existing plan
comment in-place rather than skipping, which is wasteful but not unsound
(per Common Contracts §4 update-in-place invariant).

---

## Trace 3: `stage_implement` file-split coherence

1. Main session spawns `stage_implement` (`implement.md:73-83`). Sub-agent's
   spawn prompt reads `commands/atoms/stage_implement/main.md`.
2. `main.md:1-12` declares the split: `main.md` (Phases 0/1/2), `_tdd.md`
   (Phase 3), `_pr_final.md` (Phases 4/5/5.5), `_phase7.md` (Phase 7).
3. Sub-agent reads `main.md` end-to-end.
4. **§7 Phase 3** (`main.md:292-313`): instruction "Read
   `<<SKILL_DIR>>/commands/atoms/stage_implement/_tdd.md` and execute its
   instructions". Sub-agent uses the **Read tool** (not Agent — staying
   single-level per `main.md:7-8`).
5. `_tdd.md` runs in same sub-agent context. `_tdd.md:1-3` re-affirms "no
   Agent spawns". Inputs forwarded as narrative-held state
   (`_tdd.md:9-15`).
6. **§8 Phase 4+5+5.5** (`main.md:317-344`): instruction "Read
   `_pr_final.md` and execute its instructions". Same Read-tool pattern.
7. `_pr_final.md` returns `OK ADVANCE PR: #<PR_NUM>` /
   `ESCALATE:` / `FAIL:` to narrative; `main.md` §9 (`main.md:348-393`)
   composes the final `>>> RESULT <<<` line.

**Verdict: SOUND.** The file-split is purely a textual concern — the
sub-agent's tool-side state is a single Read-tool sequence inside one Agent
context. `main.md:426` hard-rule states "no nested Agent spawns" and the
four files only reference each other by Read instruction
(`main.md:102, 296, 321`). Context accumulates linearly; no orphan or
double-load.

---

## Trace 4: PR Final escalation → user Continue → re-spawn

Starting state: PR Final round 3 FAIL in interactive mode (no
`skip-review: pr`).

1. Inside `stage_implement`, `_pr_final.md` round 3 fails. Per
   `_pr_final.md:26`, returns
   `ESCALATE: implement round 3 FAIL — findings: ... PR: #N BRANCH: <name>`.
2. `main.md:343` returns the line verbatim from §9.
3. Main session in `implement.md:129-163`. Phase 2 parser hits `ESCALATE:`.
4. **Batch detection** (`implement.md:131-142`): reads `.github/.sdd-config`;
   no `pr` in skip-review (interactive mode) → fall to interactive branch
   (`implement.md:144-163`).
5. **Interactive branch** (`implement.md:144-163`):
   - Render summary verbatim.
   - `AskUserQuestion` with `Continue / Pause / Stop`.
   - On **Continue** (`implement.md:148-161`): re-spawn `stage_implement`
     with `Resume: continue-after-escalation`, `Branch: null`, `PR: null`.
6. Re-spawned sub-agent enters `main.md`. §1 Issue Validation +
   §2 Precondition + §3 Phase 0 depth all run again (defense in depth).
7. **§4.2 Resume = continue-after-escalation** (`main.md:104-122`):
   - Step 2: re-derive PR_NUM + branch_name via
     `gh pr list --search "Refs #$1" --state open` (`main.md:111-115`). If
     empty → `FAIL`.
   - Step 3: confirm 3 PR Final markers exist on the PR (`main.md:116-120`).
     If <3 markers → `FAIL: continue-after-escalation requested but prior
     round's PR Final review markers missing`.
   - Step 4: determine `e2e_skipped` best-effort (`main.md:121`).
   - Step 5: **Skip directly to §8 Return — Normal path** with
     `OK ADVANCE: test PR: #N BRANCH: <name>` (`main.md:122`).
8. Sub-agent returns. `implement.md:161` parser handles the re-spawn return,
   re-applies label transition (idempotent on a clean Issue) and
   skip-review.qa branch.

**Verdict: SOUND.** Short-circuit skips Phases 1-5 entirely, does NOT
re-validate/re-run reviews — only existence of the 3 PR Final markers as a
sanity gate. This matches `design/01-sub-agent-contract.md` §3 +
SYNTHESIS-v2 T1.5 (cited at `main.md:108`).

---

## Trace 5: `/sdd auto` loop body — bootstrap + stage-spawn per Issue

`auto.md:238-291`.

1. For each `ISSUE` in `QUEUE` (`auto.md:249-251`).
2. **Bootstrap spawn** (`auto.md:254-260`): one Agent call, `model=haiku`,
   prompt reads `bootstrap.md`. Parses `>>> RESULT <<<` per `auto.md:262-266`.
3. **Dispatch on stage** (`auto.md:268-285`):
   - `done` → `SUCCEEDED += 1` + child auto-discovery; continue.
   - `implement-parent` → per-child label scan (`auto.md:272-276`); never
     prompts (auto's 5-key skip-review covers `implement`).
   - `analyze` / `design` / `implement` / `test` (`auto.md:278-285`) →
     inline-Read the matching wrapper command. Each wrapper does its own
     Phase 0 depth + spawns ONE `stage_<X>` sub-agent and handles label
     transition + skip-review chain into the next wrapper.
4. Wrapper command (e.g. `analyze.md`) chains via `analyze.md:67-72`
   skip-review check, which for `/sdd auto` is `analyze,design,implement,pr,qa`
   (set pre-loop in `auto.md:121-125`). So chain auto-advances stage-by-stage
   in the SAME main-session iteration until `sdd:done`.
5. Child auto-discovery (`auto.md:293-311`) queries
   `gh issue list --label sdd:child` + multilingual regex for the parent
   reference. New children appended to QUEUE.

### Token-budget claim verification

`auto.md:27` claims "Per-Issue main-session budget in Arch B is ~2,610
tokens", citing `design/00-architecture.md` §5. The math
(`00-architecture.md:139-142`): `auto.md` 80×12=960 + 4×350 envelopes=1,400 +
bootstrap 250 = 2,610. Counted: the loop body re-reads of stage wrappers
(analyze.md/design.md/implement.md/test.md) and AskUserQuestion paths
amortize across many Issues. The "4 stage sub-agent envelopes" count is the
4 stages in the canonical pipeline (analyze → design → implement → test).
**Math is internally consistent**; the cited measurement is at
`00-architecture.md:146` ("VERIFIED — Phase A cost analysis").

**Verdict: SOUND.** The auto loop only ever spawns leaf sub-agents
(bootstrap + 1×stage_<X> per stage wrapper) from main session — no nesting.
The skip-review override (`auto.md:121-125`) is what enables the
analyze→design→implement→test chain to fire in a single iteration.

---

## Critical issues found in traces

- **Trace 2, minor (non-blocking):** On `/sdd resume` with existing PR, the
  wrapper passes `Branch: null` / `PR: null` even though bootstrap detected
  them (`implement.md:80-81`). Sub-agent re-derives via `gh pr list --head`
  — works correctly, but a freshly-named branch in a forked repo edge case
  could produce a different head ref. Documented as "cache hints, not
  authoritative" at `main.md:31-34`. Not a bug; an intentional design.

- **Trace 2, minor:** `main.md` §6 Phase 2 Plan **always re-runs** on
  resume, even when the plan comment already exists. PATCH semantics make
  it correct but wasteful. Could be optimized by checking the duplicate-id
  result before regenerating the body. Not a soundness bug.

- **Trace 4, minor:** §4.2 step 4 `e2e_skipped` detection (`main.md:121`)
  is "best-effort; conservative" — defaults to `false` if unclear. If the
  pre-escalation TDD legitimately skipped E2E, this loses the
  `E2E_SKIPPED` flag on resume and the test stage might re-install an
  E2E framework. Documented but loose.

- **Trace 5, observation:** The "4 stage sub-agent envelopes" figure
  assumes a non-parent, non-no-action Issue running every stage. Parent
  Issues exit at `implement-parent` (skip test/done) and fresh
  no-action exits at analyze. So 2,610 is an upper-bound per Issue, not
  per-stage-per-Issue — matches the cited `00-architecture.md` accounting.

No load-bearing call-graph breaks identified.

---

## Summary

- Sound traces: **5/5**
- Gaps identified: **0 load-bearing; 3 minor observations** (cache-hint
  discard, plan re-post on resume, e2e_skipped best-effort)
