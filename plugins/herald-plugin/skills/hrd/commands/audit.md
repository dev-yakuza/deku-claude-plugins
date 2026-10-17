# AUDIT — read-only health check (`/hrd audit`)

Checks the harness, the state and the enforcement layer after the fact. Never changes files;
routes findings to `evolve`, `status` or `update`. Plan §3.4 (limits of the guard).

1. **Harness**: required files exist (§3.5 tree), no `{{...}}` placeholders, personas have the
   marker region, `settings.json` wires `guard.py` for Bash and Edit/Write, the scripts match
   the installed plugin version (else → `/hrd update`).
2. **Enforcement after the fact**:
   - Protected files (criteria, critique/verify personas, gate rules, config protected keys):
     `git log --format='%H %s' -- <file>` — every change must be an `evolve #n`, `config`,
     `update`, `init`, `rollback` or `social` (`chore(herald): social …`) commit, or a human commit outside
     Claude. List others. Floor changes a human accepted carry `Herald-Floor:` trailers
     (`git log --format='%h %s %(trailers:key=Herald-Floor,valueonly,separator=; )' -- docs/editorial`):
     list them with their reasons.
   - Ledger: `.claude/herald/ledger/verified.jsonl` lines are append-only in time order; every
     `push` line's SHA exists; ledger hashes agree with `verify.json`/`state.json` committed in
     `work/<id>/` (spot-check the last 10).
   - `HRD integrity` on base (read-only): mismatches mean a Herald article changed outside
     `ship`.
3. **State**: `HRD status` anomalies — held topics older than 14 days, merged-unrecorded
   articles, stale lock, unpushed Herald record commits (`HRD ahead`).
4. **Gate**: `validate_content.py` over every `origin: herald` article and each of its
   translations (the path selects the language's rules); draft forbidden rules
   that fired often (candidates for a human to confirm — INV6).
5. Report with a stated verdict per finding and the command that fixes it.
