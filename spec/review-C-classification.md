# Reviewer C: Classification Findings

This review audits the [PRESERVE] / [IMPROVE] / [RETHINK] tags applied to behavioral
items in Phase A spec. Findings target mistagged items, items missing tags, and
inconsistencies across files.

---

## Mistagged items

### Should be PRESERVE but tagged IMPROVE

- **TAG-C1**: spec/00-common-contracts.md §1 — "label names may be renamed (e.g. `sdd/analyze` namespace separator)" → `[IMPROVE: label naming convention]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE]
  - Reason: Label names like `sdd:analyze` are external GitHub-visible contracts that users have written automation/filters against; renaming them would break user workflows. The "loose-compat" disclaimer in the README does not change that they are external contracts today.

- **TAG-C2**: spec/00-common-contracts.md §2 — marker namespace inconsistency ("singular `output` vs role-suffixed ... step-numbered") → `[IMPROVE: marker namespace]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE]
  - Reason: GitHub comment markers (HTML comment substrings) are matched by external scripts and the dispatcher's `gh api ... contains("sdd:analyze:output")` — they are external contracts. Per Reviewer C guidelines: "Markers tagged IMPROVE: GitHub comment markers ARE external contracts — PRESERVE."

- **TAG-C3**: spec/00-common-contracts.md §3 — "depth label values may be renamed" → `[IMPROVE: depth label naming, but tier count is locked]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE]
  - Reason: `sdd:review:deep` / `sdd:review:shallow` are GitHub labels users apply by hand and reference in automation. The naming IS the external contract; only the tier-count clause is preserved correctly.

- **TAG-C4**: spec/00-common-contracts.md §6 — Sub-agent Result Contract sentinel format → "[IMPROVE: this contract has accreted over time; the rewrite should standardize on a structured form."
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE]
  - Reason: The `>>> RESULT <<<` sentinel + literal status strings (`OK CHILDREN: #...`, `OK E2E_SKIPPED`, `OK PR: #N`) are parsed verbatim by orchestrators in dozens of locations. Reformatting to JSON breaks every grep/regex parsing call site. The whole section is marked PRESERVE — only the trailing IMPROVE note misclassifies the rewrite freedom available.

- **TAG-C5**: spec/01-config.md §2 — "the key names mix stage labels ... with phase labels (`pr`/`qa`). Inconsistent." → `[IMPROVE]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE]
  - Reason: `skip-review: analyze,design,implement,pr,qa` is the literal config key the user writes by hand in `.github/.sdd-config`. Renaming the values breaks every user's existing config file. CLI flag / config token names that users type are external contracts.

- **TAG-C6**: spec/01-config.md §3 — "this table is duplicated in each orchestrator. Single canonical source needed." → `[IMPROVE]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE] (for the values) + [IMPROVE] (for the DRY structure)
  - Reason: The reasoning conflates two issues. The values (sonnet/opus/haiku) are explicitly tagged PRESERVE in the line above. The "DRY duplication" is correct IMPROVE, but the way it's written suggests the table itself is IMPROVE. Reword or split.

- **TAG-C7**: spec/02-multilingual.md §3 — "regex literal duplicated in many files. Single helper definition + reference." → `[IMPROVE]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE] (the regex itself) — the IMPROVE applies to internal DRY only
  - Reason: Same as C6 — the regex pattern (`(Parent|상위 |親)Issue: #<n>`) is PRESERVE (load-bearing across 5+ callers, also marked PRESERVE just above). Only the "single helper definition" is genuinely IMPROVE territory. Tag is misplaced.

- **TAG-C8**: spec/stage/implement.md §10 — Skip-review key naming: "naming is opaque — `pr` suggests it gates PR creation but actually gates final approval. Rewrite could rename to `skip-review: pr-final` or `:implement-final`." → `[IMPROVE]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE]
  - Reason: `pr` and `qa` are user-typed config tokens. Renaming them is a breaking change for every user with an existing `.sdd-config`. Per Reviewer C guidelines: "CLI flag names tagged IMPROVE: command-line argument names users type ARE external — PRESERVE."

- **TAG-C9**: spec/utilities.md §1 — alias normalization: "alias list is hardcoded across commands... Rewrite should normalize input to the 2-letter code before save." → `[IMPROVE]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE] (the accepted aliases) + [IMPROVE] (the dedup of the alias list)
  - Reason: `korean`, `한국어`, `japanese`, `日本語` are user-typed argument values to `/sdd init`. Removing them is a breaking change for users running scripts like `/sdd init korean`. The internal normalization (canonical 2-letter code on save) IS IMPROVE territory; the accepted alias surface is PRESERVE.

- **TAG-C10**: spec/edge-cases.md §18 — skip-review naming: "rename `skip-review:` to `skip-confirm:` to make the semantic clearer." → `[IMPROVE]`
  - Current tag: [IMPROVE]
  - Should be: [PRESERVE] or [RETHINK]
  - Reason: `skip-review:` is the literal key users have in their `.github/.sdd-config` file. Renaming the key is a breaking config-file change. The README's "loose-compat" disclaimer may permit a dual-read shim, but the rename itself is a contract break that needs explicit user decision — RETHINK is the better tag.

---

### Should be IMPROVE but tagged PRESERVE

- **TAG-C11**: spec/00-common-contracts.md §9 — "Deterministic temp file paths" table → `[PRESERVE]`
  - Current tag: [PRESERVE]
  - Should be: [IMPROVE]
  - Reason: `/tmp/sdd-analyze-output-$1.md` is purely internal — no external system reads these paths and they exist only during a single Bash call chain. No user/automation depends on the exact filename pattern. The rewrite has full freedom here. Compare to the rewrite-note line: "temp file naming is consistent and good. Keep. [PRESERVE]" — keeping the pattern is fine, but classifying internal scratch paths as PRESERVE muddles which freedoms remain.

- **TAG-C12**: spec/00-common-contracts.md §11 — "**Rewrite note**: this is a defensive contract. Keep as-is. [PRESERVE]"
  - Current tag: [PRESERVE] on the rewrite note
  - Should be: [IMPROVE] (the rewrite-note framing — the contract semantics ARE PRESERVE, but "keep as-is" is style preference)
  - Reason: The forbidden sources (`git config user.name` etc.) being rejected is PRESERVE (semantic invariant). The exact wording or location of the helper is IMPROVE. The current note conflates the two.

- **TAG-C13**: spec/01-config.md §6 — Label colors table → `[PRESERVE: colors are a user-visible contract; users may have customized their GitHub label colors. Keep defaults.]`
  - Current tag: [PRESERVE]
  - Should be: [IMPROVE] or [RETHINK]
  - Reason: The hex colors (`1d76db`, `0e8a16`, etc.) are applied only on `/sdd init` via `--force`. Users who customized colors will get them overwritten on re-init — the rationale given actually argues against PRESERVE. If colors were truly preserved, init wouldn't `--force` overwrite. The defaults are arbitrary internal choices.

- **TAG-C14**: spec/stage/implement.md §1 — "Existing feature branch — `implement_plan` step 3 falls back to `git checkout` instead of `git checkout -b`. [PRESERVE]"
  - Current tag: [PRESERVE]
  - Should be: [IMPROVE]
  - Reason: This is internal atom logic ("how `implement_plan` step 3 behaves"). Users do not depend on the specific fallback mechanism — they only depend on "resume works from an existing branch." The internal implementation is IMPROVE freedom; the user-facing behavior is the PRESERVE.

- **TAG-C15**: spec/flow/auto.md §7 — In-memory state variables table (QUEUE, SEEN, TOTAL_TARGETS, etc.) → `[PRESERVE]` (whole §7 tagged)
  - Current tag: [PRESERVE]
  - Should be: [IMPROVE]
  - Reason: Variable names like `QUEUE`, `SEEN`, `BATCH_START` are internal narrative state with no external visibility. The behavior of FIFO + dedup is PRESERVE; the specific variable names and structure are pure IMPROVE freedom.

- **TAG-C16**: spec/flow/batch.md §7.1 — "`set -euo pipefail` is the bash strict-mode contract" → `[PRESERVE]`
  - Current tag: [PRESERVE]
  - Should be: [IMPROVE]
  - Reason: Inside an internally-generated shell script, `set -euo pipefail` is an implementation choice. The behavioral contract is "jq parse errors don't silently corrupt the loop" which can be achieved via other means. The exact flags are not externally observable.

---

### Should be RETHINK but tagged PRESERVE or IMPROVE

- **TAG-C17**: spec/stage/implement.md §1 — "Existing open PR ... Empty-`$3` + existing PR is an unhandled gap" → `[PRESERVE / RETHINK]`
  - Current tag: [PRESERVE / RETHINK] (ambiguous dual-tag)
  - Should be: [RETHINK]
  - Reason: An unhandled gap is not a preserved contract — it's a bug-prone state in need of user discussion. Marking it PRESERVE implicitly endorses keeping the gap. The §6 RETHINK on the matrix is correctly tagged, but the §1 entry is internally inconsistent.

- **TAG-C18**: spec/stage/implement.md §1 — "Prior TDD commits — each step atom re-verifies branch state via `git rev-parse` / `git checkout`. No idempotency check skips already-done steps." → `[PRESERVE; RETHINK]`
  - Current tag: [PRESERVE; RETHINK] (ambiguous dual-tag)
  - Should be: [RETHINK]
  - Reason: Same as C17 — "no idempotency check" is not a contract worth preserving; it's a known limitation. The cross-ref to §10 "Resume from existing branch" correctly says RETHINK. Tag the source consistently.

- **TAG-C19**: spec/stage/implement.md §2 — TDD step reviews go on the Issue (not PR) because PR may not exist → `[PRESERVE — load-bearing]`
  - Current tag: [PRESERVE — load-bearing]
  - Should be: PRESERVE is fine, but the duplicate-state risk (step reviews on Issue, PR Final on PR — same marker family split across two locations) deserves a RETHINK note.
  - Reason: The dual-location for `<!-- sdd:review:implement:* -->` markers is bug-prone (retry self-fetch must know which location). No RETHINK is flagged; one should be considered.

- **TAG-C20**: spec/stage/design.md §5 idempotency: "a wrong PR split cannot be corrected by retry" → existing `[RETHINK]` flagged inline, but the parent `[PRESERVE — load-bearing]` on §5 Hard rules contradicts.
  - Current tag: [PRESERVE — load-bearing] (Hard rule line); inline RETHINK exists
  - Should be: Surface the RETHINK at the section level — the load-bearing claim and the bug-prone behavior conflict, deserving explicit discussion.
  - Reason: Per Reviewer C guidelines: "Bug-prone patterns tagged PRESERVE: if the behavior is harmful, it should be RETHINK even if 'users depend on it.'" The idempotency is correct for normal flow but harmful for the retry-after-bad-split case — needs user decision.

- **TAG-C21**: spec/utilities.md §1 — "No `gh` auth or wrong repo → `gh label create` fails per-label; no transactional rollback. [RETHINK: partial label set leaves the repo in a half-configured state.]"
  - Current tag: RETHINK already flagged
  - Should be: The parent `[PRESERVE]` on §1 conflicts — `/sdd init`'s partial-failure mode is a known hole. Either RETHINK the §1 contract or accept the bug.
  - Reason: Acceptable as-is, but worth surfacing in summary that the parent PRESERVE absorbs a child RETHINK that may need addressing.

---

### Untagged items

- **TAG-C22**: spec/00-common-contracts.md §13 — Skill Tool Availability tagged `[VERIFIED — see R5 spike]`, not PRESERVE/IMPROVE/RETHINK.
  - Issue: `[VERIFIED]` is not one of the three official tags from README.md §11. Implication for rewrite freedom is ambiguous. The conclusion is tagged `[PRESERVE: capability confirmed; design freedom available]` later, but the section header itself doesn't follow the schema.

- **TAG-C23**: spec/02-multilingual.md §8 — "Issue Template Multilingual Examples [REFERENCE]"
  - Issue: `[REFERENCE]` is not one of the three official tags. Either reclassify or document a fourth tag in README.md.

- **TAG-C24**: spec/01-config.md §1 — Storage paths table has IMPROVE/RETHINK on the rewrite note but no top-level tag on the table itself.
  - Issue: The section header is `[PRESERVE]` but the table-vs-paths-vs-bak distinction is ambiguous about whether `.sdd-config.bak` filename is PRESERVE or IMPROVE.

- **TAG-C25**: spec/flow/auto.md §5 — Phase 2 Verify Tool Permissions, "Auto-specific differences" → no explicit tag on the bullets (inherits §5's `[PRESERVE — shared with batch, reference 01-config.md]`).
  - Issue: The display header text and replacement wording bullets are arguably IMPROVE (UI strings), but inherit PRESERVE by default — should be explicitly disambiguated.

- **TAG-C26**: spec/stage/implement.md §5 "Per-step retry budget" paragraph — no explicit tag at paragraph level (inherits §5 context).
  - Issue: The "2 retries per step (3 attempts total)" is a load-bearing number — should have an explicit PRESERVE tag.

- **TAG-C27**: spec/utilities.md §3 `/sdd status` — section header tagged `[IMPROVE]` but multiple sub-bullets (validation, process steps, output formats) have no explicit tags. The contract that status is read-only is implicit.
  - Issue: Mixed implicit/explicit tagging within a single section.

---

### Inconsistent tagging across files

- **TAG-C28**: Marker namespace inconsistency
  - spec/00-common-contracts.md §2: `[IMPROVE: marker namespace]` — implies markers can be renamed
  - spec/00-common-contracts.md §4: "Marker matching invariant [PRESERVE]" + "Update-in-place invariant [PRESERVE]"
  - spec/edge-cases.md §17: "Duplicate-Prevention Pattern [PRESERVE]" includes marker matching
  - Issue: The same markers are simultaneously IMPROVE (renameable) and PRESERVE (exact-match contract). Resolve in one direction.

- **TAG-C29**: Skip-review key names
  - spec/01-config.md §2: `[IMPROVE: ... renaming `implement` → `plan`]`
  - spec/edge-cases.md §18: `[IMPROVE: rename `skip-review:` to `skip-confirm:`]`
  - spec/stage/implement.md §10: `[IMPROVE: rename to `skip-review: pr-final`]`
  - Issue: Three different IMPROVE proposals for the same user-facing config key. None acknowledges these are user-typed external tokens (per TAG-C5, C8, C10 above). Should be unified — PRESERVE the existing keys, RETHINK any rename.

- **TAG-C30**: Sandbox toggle UX
  - spec/01-config.md §4: `[RETHINK: sandbox toggle UX (~190 lines in auto.md Phase 3.1) is complex.]`
  - spec/flow/auto.md §6.5: `[RETHINK: this step occupies ~190 lines ... Maintainability cost: editing the prompt requires touching three near-identical text blobs.]`
  - spec/edge-cases.md §3: `[RETHINK: sandbox-toggle UX (~190 lines in `auto.md` Phase 3.1) is heavy.]`
  - Issue: Triple-listed RETHINK for the same item. Consolidate cross-refs to a single canonical RETHINK source.

- **TAG-C31**: `ai-review-*.md` file location
  - spec/utilities.md §7: `[IMPROVE]` tagged; `[RETHINK: the rubrics could be inlined ...]`
  - spec/edge-cases.md §21: `[IMPROVE: file location ... is misleading]`
  - Issue: Edge-cases.md §21 says only IMPROVE; utilities.md §7 also raises a RETHINK on inlining. The inline-vs-separate question is a true RETHINK; the location move is IMPROVE. Split the concerns explicitly.

- **TAG-C32**: Round-suffixed markers / round preservation
  - spec/00-common-contracts.md §4: `[RETHINK: should rounds be preserved for audit?]`
  - spec/edge-cases.md §6: `[RETHINK]` flagged separately
  - spec/stage/analyze.md §2: `[PRESERVE — but see Common Contracts §4 RETHINK on round preservation]`
  - spec/stage/design.md §2: same pattern repeated
  - spec/stage/implement.md §7: `[PRESERVE — but Common Contracts §4 RETHINK ... applies]`
  - Issue: The `[PRESERVE — but RETHINK ...]` hybrid pattern is repeated 5+ times. Either centralize to one RETHINK reference or surface explicitly that the current behavior is bug-prone (PRESERVE-with-known-issue). The hybrid hides the dissent.

- **TAG-C33**: Adversarial-only FAIL escalation
  - spec/stage/analyze.md §6: `[RETHINK: rationale ... consider whether adversarial-only FAIL should have a separate threshold]`
  - spec/stage/design.md §7: `[RETHINK: same dilemma as analyze ...]`
  - spec/stage/test.md: (PRESERVE in §10 with no RETHINK)
  - spec/edge-cases.md §19: `[PRESERVE: behavior is to surface adversarial dissent prominently.]`
  - Issue: Analyze + design flag this as RETHINK; test stage and edge-cases.md leave it as PRESERVE. The same behavior across 4 stages should have the same classification — either all RETHINK or all PRESERVE.

- **TAG-C34**: `find` restrictions / Bash heuristic rules
  - spec/00-common-contracts.md §8: tagged `[PRESERVE — load-bearing]` at section level, with rewrite note `[IMPROVE: DRY — one canonical reference]`
  - spec/edge-cases.md §3: same rules tagged `[PRESERVE — UNSUPPRESSIBLE]` and `[PRESERVE]`
  - spec/edge-cases.md §14: "Bash Heuristic Cheat Sheet [PRESERVE — load-bearing]"
  - Issue: Consistent on the PRESERVE classification but the rules are duplicated verbatim across 3 sections. The IMPROVE-DRY note exists in §8 but not the others — inconsistent attention to the DRY opportunity.

- **TAG-C35**: Multilingual aliases (`korean` / `한국어` / `japanese` / `日本語`)
  - spec/utilities.md §1: tagged `[IMPROVE]` (see TAG-C9)
  - spec/02-multilingual.md §1: tagged `[PRESERVE]` at the section level
  - spec/edge-cases.md: no entry
  - Issue: The same alias surface is PRESERVE in 02-multilingual.md and IMPROVE in utilities.md. Per TAG-C9 the user-typed aliases should be PRESERVE.

- **TAG-C36**: Atom Skill-tool invocation (sub-agents can invoke Skills)
  - spec/00-common-contracts.md §13: `[VERIFIED]` (see TAG-C22) + `[PRESERVE: capability confirmed]`
  - spec/stage/implement.md §3: `[PRESERVE; RETHINK per Common Contracts §13]` (dual-tag)
  - spec/edge-cases.md §12: `[VERIFIED: design freedom available.]`
  - Issue: `[VERIFIED]` is non-standard (TAG-C22). The Common Contracts entry says PRESERVE (capability confirmed) but implement.md uses RETHINK to mean "consider migrating". These two are not contradictory but the language varies — settle on RETHINK (since it's a design decision) or PRESERVE-with-design-note.

---

## Summary

- Under-tagged (should be PRESERVE, tagged IMPROVE): 10 (TAG-C1..C10)
- Over-tagged (should be IMPROVE, tagged PRESERVE): 6 (TAG-C11..C16)
- Missing RETHINK (should be RETHINK, tagged PRESERVE/IMPROVE): 5 (TAG-C17..C21)
- Untagged: 6 (TAG-C22..C27)
- Inconsistent: 9 (TAG-C28..C36)
- Total: 36
