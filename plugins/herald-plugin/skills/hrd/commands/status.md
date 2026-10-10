# STATUS — topics, holds and maintenance (`/hrd status [flags]`)

Plan §3.2.1. Read-only unless a flag below is given.

## Show (no flags)

`HRD status` → a table in `config.language`: id · title · derived state · reason · open/merged
PRs · local branches. Group: in progress · PR pending (→ `/hrd ship`) · merged-unrecorded (→
`/hrd ship`) · held (with the next step per reason) · queued · published. Also show the lock
holder if any and `HRD ahead` warnings.

## Maintenance flags (each except `--unlock`: `HRD lock acquire --cmd status`, base checked out and clean,
`HRD sync`, then the action, then `HRD commit --cmd status --kind status -m "chore(herald):
<action> <id>" <changed files>` and `git push origin <base>`; finally `HRD lock release --cmd status
--token <t>`)

| Flag | Action | Notes |
|---|---|---|
| `--requeue <id>` | `HRD requeue --topic <id>` | held/declined → queued; deletes a preserved branch after the human confirms; keeps `reverted_by` |
| `--drop <id>` | `HRD drop --topic <id>` | declined:dropped |
| `--withdraw <id\|slug>` | `HRD withdraw <id\|slug>` | refuses while body/tracked images exist or git shows a rename (use `--move`); labels all merged PRs `herald:withdrawn` |
| `--unwithdraw <id\|slug>` | `HRD unwithdraw <id\|slug>` | body must exist; next `ship` re-checks and deploys it |
| `--move <id> <new-slug>` | `HRD move --topic <id> --new-slug <s>` | records the alias; next `ship` re-verifies (paths are hashed) |
| `--release-slug <slug>` | `HRD release-slug <slug>` | for a withdrawn/moved-away slug a human reused outside Herald |
| `--mark-published <id> <slug>` | confirm the URL opens (WebFetch or curl), then `HRD mark-published --topic <id> --slug <slug>` | for articles published by other means; refuses if a Herald PR merged |
| `--unlock` | show `HRD lock status`, ask the human, then `HRD lock unlock` | for a lock left by a crashed session |

Confirm with the human before `--withdraw`, `--move`, `--release-slug`, `--drop` (attended
only; these flags are never used unattended).
