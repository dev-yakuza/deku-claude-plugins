# ROLLBACK — undo a Herald change (`/hrd rollback <evolve#n|commit>`)

Non-destructive: always `git revert`, never reset or force push (INV3).

1. `HRD lock acquire --cmd rollback` (keep the token; `HRD lock release --cmd rollback --token <t>`
   on every exit path); base clean; `HRD sync`.
2. Resolve the target: `evolve#<n>` → `git log --grep="^chore(herald): evolve #<n> —" -1
   --format=%H`; otherwise a commit SHA whose subject starts with `chore(herald):`.
3. Show the files it changed and list explicitly which of them are protected (criteria files,
   critique/verify personas, gate rules, protected config keys). `git revert` does not trigger
   the guard, so ask the human to confirm reverting those files — a revert can loosen
   verification an evolve run had strengthened (INV2).
4. `git revert --no-edit <sha>`; then amend the revert's message only via
   `git commit --amend -m "chore(herald): rollback <target>" --trailer "Herald-Record: harness"`
   (allowed: it is the commit just created, not history rewrite of published commits).
   Append a rollback line to `evolution-log.md` in the same commit.
5. `git push origin <base>`. State that gitignored data (signals, ledger) is not affected.
