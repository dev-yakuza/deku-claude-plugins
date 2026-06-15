# Reviewer B: Migration Risk Findings

Migration risk review of Phase B design for the 0.x → v1.0.0 cutover. Focuses on
cutover mechanics, in-flight Issue compatibility, R7-R10 rollout, doc/MIGRATION
needs, and rollback. Does not repeat SR-D1..SR-D10.

---

## High risk (must mitigate before v1.0.0)

- **MIG-B1: Version-sync enforcement is named but not specified**
  - Risk: `06-migration-plan.md` §2.1 and `07-implementation-plan.md` M0/M12
    promise a "CI check or pre-commit hook" enforcing `plugin.json` ==
    `marketplace.json`. Neither doc specifies the hook content, hook location
    (`.husky/`, `.git/hooks/`, GitHub Actions?), nor what happens for the
    `legacy/0.x` branch. Without a concrete design, v1.0.0 ships with the bug
    that already produced the 0.35.0/0.36.0 drift.
  - Source: `design/06-migration-plan.md` §2.1; `design/07-implementation-plan.md`
    M0 + M12; `spec/edge-cases.md` §20.
  - Mitigation: write the actual hook (~10-line shell diffing the two
    `"version"` fields) and commit it in M0. Add a `legacy/0.x` exemption (or
    freeze that branch at 0.36.x with an immutable tag). Document the exemption
    in MIGRATION.md.

- **MIG-B2: R7 path migration risk to in-flight retries**
  - Risk: An Issue currently mid-retry on 0.x (sdd:review:* comment present,
    awaiting Round 2 spawn) when the user updates to v1.0.0: any atom that
    hard-coded the old `commands/ai-review-*.md` path will fail. The reviewer
    atoms themselves are inlined into stage_X sub-agents in v1.0.0, so the
    transition is atomic from main's perspective; however the `grep -r
    "ai-review-"` audit is the only safety net and it does not check templates,
    fixtures, or external user forks.
  - Source: `design/06-migration-plan.md` §5 step 4; `design/05-rethink-decisions.md` R7.
  - Mitigation: extend the audit grep to scan `plugins/sdd-plugin/templates/`
    and the repo's own docs (README.md, CLAUDE.md). Add a CI job that fails on
    any new occurrence of `ai-review-*` after M11.

- **MIG-B3: R8 `strict-pr-creation` config key contradicts R2/R3 KEEP**
  - Risk: `design/stage-designs/implement.md` §11.3 + §20.4 introduce a NEW
    `strict-pr-creation: <bool>` config key. R2/R3 explicitly KEEP current
    config without new keys. SR-D8 flagged this. From a migration standpoint,
    silently adding a key that 0.x doesn't know about means a user editing
    their `.sdd-config` on 0.x (e.g. backporting their v1.0.0 config) gets
    no warning — and downgrade users carry orphan keys.
  - Source: `design/stage-designs/implement.md` §11.3, §20.4;
    `design/05-rethink-decisions.md` R2/R3/R8; `design/SELF-REVIEW.md` SR-D8.
  - Mitigation: drop `strict-pr-creation` for v1.0.0; auto-route is the only
    behavior. If users later request opt-out, add the key in v1.1 with proper
    decision + dual-read.

- **MIG-B4: MIGRATION.md is required but contents are unspecified**
  - Risk: `06-migration-plan.md` §2.3 and M12 reference a `MIGRATION.md` but no
    table of contents, audience, or minimum coverage is defined. Doc may ship
    incomplete (e.g. missing "what to do if you have an in-flight Issue").
  - Source: `06-migration-plan.md` §2.3; `07-implementation-plan.md` M12.
  - Mitigation: see "MIGRATION.md required content" section below — make that
    list normative for M12.

## Medium risk

- **MIG-B5: Rollback Option A is not actually feasible for already-updated users**
  - Risk: `06-migration-plan.md` §11 Option A says "re-tag 0.36.x as
    marketplace HEAD". Users who already auto-pulled v1.0.0 will not be
    auto-downgraded — Claude Code's plugin system pulls forward, not
    backward. Re-tag only helps fresh installs. Worse, R9's
    `<!-- sdd:tdd:step-N -->` markers committed by v1.0.0 persist in user
    repos and look unfamiliar to a 0.x re-install (treated as no-op markers,
    harmless but visually surprising).
  - Source: `design/06-migration-plan.md` §11; R9 in `05-rethink-decisions.md`.
  - Mitigation: re-label Option A as "fresh-install rollback only". Lead with
    Option B (hotfix v1.0.1). Document the marker-leftover as expected.

- **MIG-B6: Multi-user/multi-org rollout with mixed-version teammates**
  - Risk: A user on v1.0.0 implements an Issue, leaving R9 commit markers.
    A teammate still on 0.x runs `/sdd resume <N>` on that branch. 0.x atoms
    don't know the new marker — they re-execute the TDD steps, potentially
    writing duplicate test files or causing a Red step that writes a test
    that already exists. Conflict/duplicate test, wasted work.
  - Source: `design/06-migration-plan.md` §7 "edge case";
    `design/stage-designs/implement.md` §14.3 "branch divergence" note.
  - Mitigation: document in MIGRATION.md that teams should upgrade together.
    Add an explicit warning in the R9 marker text (e.g. include the producing
    version `<!-- sdd:tdd:step-N v=1.0.0 -->`) so future tooling can spot
    cross-version operations. Cheap to add now, costly later.

- **MIG-B7: `gh label delete` rollback can itself fail (R10)**
  - Risk: `design/06-migration-plan.md` §8 + `design/05-rethink-decisions.md` R10:
    transactional rollback deletes successful labels on failure. If the
    rollback itself fails (rate limit, network, auth revoked mid-flight), the
    repo is left in a worse state than 0.x — partial create + partial delete.
    No spec for "rollback of rollback".
  - Source: `design/06-migration-plan.md` §8, §10 risk table; R10.
  - Mitigation: rollback should log every delete attempt + outcome to stdout
    AND post a single `<!-- sdd:init:rollback-log -->` comment on the repo's
    pinned Issue (or to a local file). On any delete failure, surface a
    clear "manual cleanup required: delete labels X, Y, Z" message with the
    exact `gh label delete` commands the user can paste.

- **MIG-B8: Re-running `init` on a partial-then-partial state is unspecified**
  - Risk: §8 covers re-run on partial-from-0.x (heals). It does not cover
    re-run after R10 rollback **also** partially failed (some succeeded
    creates were deleted, some weren't). The "heal" path assumes `--force`
    succeeds on all 8 — but with leftover state plus another rate-limit, the
    loop can revisit the same bad state.
  - Source: `design/06-migration-plan.md` §8.
  - Mitigation: make `init` strictly idempotent — query existing labels first,
    only attempt creates for missing labels, never rollback what was already
    there before this invocation.

- **MIG-B9: Sandbox toggle relocation drift risk (~190 LOC)**
  - Risk: Design says preserved verbatim, but it currently lives in
    `auto.md` Phase 3.1 step 5. M8 slims `auto.md` from ~370 → ~100 lines. If
    the sandbox toggle is moved into a helper or split across files, subtle
    behavior drift (e.g. the `<SETTINGS_PATH>.sdd-auto.bak` lifecycle,
    restart prompt timing) becomes a one-time review burden.
  - Source: `design/06-migration-plan.md` §3 (Internal-only changes);
    `design/07-implementation-plan.md` M8; `spec/edge-cases.md` §3.
  - Mitigation: explicit M8 sub-task "preserve sandbox toggle line-for-line
    in a single `commands/atoms/_sandbox_toggle.md` helper (or keep in
    auto.md)". Diff the relocated block against the 0.x version pre-merge.

## Low risk / observations

- **MIG-B10: Deleted-atom path references (M11)**
  - Risk: 17 atom files deleted. External plugin forks, user CLAUDE.md, README,
    or stale documentation may reference deleted paths
    (`commands/atoms/implement_red.md` etc.).
  - Source: `design/07-implementation-plan.md` M11;
    `design/02-file-layout.md` §2.
  - Mitigation: in M11, scan `plugins/sdd-plugin/` README.md + CLAUDE.md +
    `templates/**` for any old atom paths. Search marketplace metadata for
    references. Add `git grep` output to PR description.

- **MIG-B11: CI/CD `claude -p` script version drift (batch)**
  - Risk: `/sdd batch` generates a shell script that runs in user CI. The
    script invokes `/sdd resume <N>` via `claude -p
    --dangerously-skip-permissions`. If v1.0.0 batch.md changes the prompt
    text and a CI re-uses a previously-generated script from 0.x, the script
    keeps working (entry point unchanged) but new features (R8/R9) don't
    activate. Worse: if v1.0.0 changes the script template, a CI cache that
    pre-built the script under 0.x has stale behavior.
  - Source: `design/07-implementation-plan.md` M9; `spec/edge-cases.md` §4.
  - Mitigation: include `# generated by sdd-plugin <version>` header in the
    generated script. Note in MIGRATION.md that CI should regenerate the
    script on plugin update.

- **MIG-B12: R9 re-execution may mutate code on old branches**
  - Risk: 0.x branch resumed on v1.0.0 has no `<!-- sdd:tdd:step-N -->`
    markers — `stage_implement` §14 idempotency check fails for all 4 steps
    → re-runs. The Red step writes a test file that may already exist (from
    the 0.x run). git commit produces a no-op or a conflict if the file
    diverged.
  - Source: `design/stage-designs/implement.md` §14.1 (commit subject
    heuristic step); `06-migration-plan.md` §7 edge case.
  - Mitigation: §14.1's "commit subject matches step expectation" heuristic
    PARTIALLY covers this — if the 0.x commit subject matches "test:
    ... (Red)" it could be claimed as the step, but no marker means the
    sub-agent can't confirm. Acceptable as documented; call out in
    MIGRATION.md "re-running an in-flight Issue under v1.0.0 may produce
    duplicate-effort commits; safer to finish on 0.x or restart fresh".

- **MIG-B13: `/sdd retroactive-mark` is proposed but not designed**
  - Risk: `06-migration-plan.md` §7 floats a one-shot command to backfill R9
    markers. SR-D4 flags this. No design exists for it; if users actually
    need it post-release, ad-hoc design under time pressure.
  - Source: `06-migration-plan.md` §7.
  - Mitigation: either commit to implementing in v1.0.0 (small atom) OR
    explicitly defer to v1.1 in MIGRATION.md with no promise.

---

## MIGRATION.md required content

Minimum viable migration guide (normative for M12):

- **What changed**: 1-paragraph summary (Arch B, R7-R10) with links to design/
- **What is identical**: explicit list of preserved contracts (commands,
  labels, markers, config keys, schemas)
- **Action required (none for typical users)**: confirm zero migration steps
- **In-flight Issue behavior**: per-stage table (analyze/design/implement/test)
  describing what v1.0.0 does with a 0.x mid-pipeline Issue. Include the R9
  re-execution caveat (MIG-B12).
- **Mixed-version teams warning**: do not have teammates on 0.x and v1.0.0
  resuming each other's Issues (MIG-B6).
- **R7 path change**: the `ai-review-*.md → atoms/rubrics/*` move, with note
  that no user automation should reference these paths (and what to update if
  they do).
- **R8 behavior change**: `/sdd implement <N>` after a PR exists no longer
  errors. Anyone who scripted around the old "PR already exists" error
  message must update.
- **R10 init behavior**: transactional rollback; manual recovery commands if
  rollback itself fails (MIG-B7).
- **CI/CD note**: `/sdd batch` script regeneration on upgrade (MIG-B11).
- **Rollback policy**: how to pin to 0.36.x; Option A caveat (fresh-install
  only); recommended path is hotfix v1.0.1 (MIG-B5).
- **Version-sync rule**: reminder that both `plugin.json` and
  `marketplace.json` must move together — link the hook.
- **Known limitations / deferred**: `/sdd retroactive-mark` status (MIG-B13),
  sandbox-toggle UX deferred.
- **Support**: where to file regressions (link to repo issues).

---

## Summary
- High: 4
- Medium: 5
- Low: 4
