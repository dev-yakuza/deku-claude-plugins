# Tests — Phase C Verification

Manual verification harness for Phase C milestones. No automated test framework yet; each milestone's verification is a procedure run by the implementer.

## Structure

```
tests/
├ README.md                          # this file
├ fixtures/                          # captured 0.x outputs for diff against v1.0.0
│  ├ README.md                       # capture procedure
│  └ (populated during milestone verification — not yet)
└ scripts/                           # helper scripts for milestone verification
   └ (populated as needed)
```

## Verification approach (per design/07-implementation-plan.md §5)

### Smoke tests (after every milestone)
- `/sdd <command> <N>` on a known-state Issue; no errors.
- `grep` audits per milestone's checklist.

### Integration tests (after M4/M5/M6/M7)
- Full single-Issue lifecycle: analyze → design → implement → test → done.
- Parent + children lifecycle.

### Acceptance tests (before M12)
- `/sdd auto` with N=3 mixed-state Issues. Measure: main session tokens (`/context`), wall-clock.
- `/sdd batch` with N=3 Issues. Measure: log output, total time.
- Sandbox toggle path on a TLS-proxy environment (if available).

## Fixture capture procedure

To diff v1.0.0 behavior against 0.x:

1. Switch to legacy/0.x branch (or have v0.37.0 plugin installed in a separate workspace).
2. Run `/sdd <command> <N>` on a target Issue.
3. After completion, capture state:
   ```bash
   gh issue view <N> --json labels,comments > tests/fixtures/<stage>-<scenario>-0.x.json
   ```
4. Switch back to rewrite/v1.0.0 branch.
5. Repeat step 2 with the v1.0.0 implementation on a fresh equivalent Issue.
6. `diff` the two JSONs — accept body-text differences if equivalent, fail on label/marker mismatch.

### Fixtures to capture during Phase C

| Milestone | Scenario | When |
|---|---|---|
| M4 verification | analyze: fresh Issue → sdd:design | M4 |
| M4 verification | analyze: no-action Issue → sdd:done | M4 |
| M5 verification | design: SINGLE → sdd:implement | M5 |
| M5 verification | design: CHILDREN → children created | M5 |
| M6 verification | implement: full TDD + PR Final pass | M6 |
| M6 verification | implement: PR Final round 3 retry | M6 |
| M6 verification | R8 — empty-$3 + existing PR auto-route | M6 |
| M6 verification | R9 — TDD step idempotency on resume | M6 |
| M7 verification | test: single path → sdd:done | M7 |
| M7 verification | test: parent path → integration PR | M7 |
| M8 verification | /sdd auto with N=3 Issues | M8 |
| M9 verification | /sdd batch with N=2 Issues | M9 |
| M10 verification | /sdd init R10 transactional rollback | M10 |

This list is normative for verification — populate `fixtures/` as each milestone runs.
