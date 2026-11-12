# STATUS — topics, holds and maintenance (`/hrd status [flags]`)

Read-only unless a flag below is given.

## Show (no flags)

`HRD status` → a table in `config.language`: id · title · derived state · reason · open/merged
PRs · local branches. Group: in progress · PR pending (→ `/hrd ship`) · merged-unrecorded (→
`/hrd ship`) · held (with the next step per reason) · queued · published. Also show the lock
holder if any (`HRD lock status`; when it carries `waiting`, say that a batch is waiting for a
usage limit until that time — `--unlock` would end that batch; `kill <pid>` stops it cleanly) and
`HRD ahead` warnings. With `translations` in config, add per published Herald
article its languages from `published.json` (`translations`, `withdrawn_langs`) and, from
`HRD integrity --report`, any `translation_added` (a translation Herald has not verified —
adopt with `/hrd translate <slug> --adopt <l>`) or other `causes`. A hold whose `note` names a
`refresh candidate: <slug>` → suggest `/hrd refresh <slug>`. A `screenshots` hold: show its note
and the inbox `.claude/herald/inbox/<id>/` — "put the files there, then `/hrd resume <id>`"
(`atoms/_screenshots.md` §5); show the reason as "screenshots/images" — a note with `e1(confirm)`
or `g1(confirm)` names external or scene images waiting for the human's look (`atoms/_images.md`
§5). Held topics whose note is `tooling: limner busy` or `tooling: limner generating <run_id>` are
shown apart as "resume when the machine is free" (display only — a batch never picks them; the
human's `/hrd resume` does). `shots_removed_bytes`
and `images_removed_bytes` (moved-away screenshots and images kept under
`.claude/herald/memory/shots/removed/` and `.claude/herald/memory/images/removed/`, never deleted
by Herald): show each when it is over 50 MB, with the path, so the human can clean it up. In a
translation repo, `HRD translate missing` `blocked` lists articles with external images
(`external-images`) or scene images (`scene-images`): "these
cannot be translated or refreshed by Herald in 0.17 — to fix one, edit it on base and `/hrd ship
--reverify`, or merge a PR that removes the external image" (`atoms/_images.md` §6). From the same output,
`supersede_pending` (old articles a newer one follows, not linked to it yet): for each, "link
`<new>` from `<old>`" — `/hrd refresh <old>` when `refreshable`, otherwise by hand.

A `notice` field (0.21.0, once per machine — stand-ins are on by default): show it as one line.
The batch summary shows it the same way when its `HRD status` carried one.

Last, one line from the `evolve` field of the same `HRD status` output (absent with scripts
older than 0.3.0 — `status` runs without the version gate — then omit the line) (`tier` is a machine
token — branch on it, never show it raw): `sufficient` → "growth signals are enough
(N unused signals · M topics[ · K SNS days]) — try `/hrd evolve --dry-run`" (K = `social_topics`, only when > 0); `watching` with non-empty
`ready_themes` → "enough signals, but evolve already looked at them on <last_scan> — the
reminder returns with new evidence (you can still run `/hrd evolve`)"; other `watching` →
"collecting growth signals (N unused signals · M topics; evolve proposes from ≥ 3 signals of
one theme from ≥ 2 topics)"; `none` → omit; an `error` field → say the signals
file could not be read. Signals are per machine (gitignored). Write it in `config.language`.

Then, when the output has a `social` field (absent before `/hrd social --setup`, and with older
scripts): `stale` channels → "the <sns> guide was researched over 180 days ago — `/hrd social
--refresh <sns>`"; `invalid` → "the <sns> guide has problems — `/hrd social --edit <sns>` (research fields:
`--refresh <sns>`)"; `reserved` → "a channel named <sns> clashes with a reserved name since 0.12.0 —
`/hrd social --remove <sns>`, then `--add` it under another name"; an
`error` → say it could not be read. Nothing to say → omit.

## Maintenance flags (each except `--unlock`: `HRD lock acquire --cmd status`, base checked out and clean,
`HRD sync`, then the action, then `HRD commit --cmd status --kind status -m "chore(herald):
<action> <id>" <changed files>` and `git push origin <base>`; finally `HRD lock release --cmd status
--token <t>`)

| Flag | Action | Notes |
|---|---|---|
| `--requeue <id> [--direction]` | `HRD requeue --topic <id> [--direction]` | held/declined → queued; deletes a preserved branch after the human confirms; keeps `reverted_by`. `--direction` attaches the saved human change (`memory/directions/<id>.diff`) as the topic's direction for brief and draft |
| `--drop <id>` | `HRD drop --topic <id>` | declined:dropped |
| `--withdraw <id\|slug>` | `HRD withdraw <id\|slug>` | refuses while body/tracked images/translations exist or git shows a rename (use `--move`); labels all merged PRs `herald:withdrawn` |
| `--withdraw-lang <slug> <lang>` | the human removes that translation from base outside Claude first; `HRD withdraw-lang <slug> --lang <lang>` (proves only that file left the verified bundle; refuses while a topic on the slug is in progress), commit the files it lists, then `python3 .claude/herald/scripts/integrity.py --record --topic <ref_topic> --kind withdraw-lang` (no `--sha`: the record names HEAD; the guard asks) | one translation taken down; `already_applied: true` (done on another machine) → only the ledger line is recorded here |
| `--unwithdraw <id\|slug>` | `HRD unwithdraw <id\|slug>` | body must exist; next `ship` re-checks and deploys it |
| `--move <id> <new-slug>` | `HRD move --topic <id> --new-slug <s>` | records the alias; next `ship` re-verifies (paths are hashed); refused for an article with translations |
| `--release-slug <slug>` | `HRD release-slug <slug>` | for a withdrawn/moved-away slug a human reused outside Herald |
| `--mark-published <id> <slug>` | confirm the URL opens (WebFetch or curl), then `HRD mark-published --topic <id> --slug <slug>` | for articles published by other means; refuses if a Herald PR merged |
| `--unlock` | show `HRD lock status`, ask the human, then `HRD lock unlock` | for a lock left by a crashed session |

Confirm with the human before `--withdraw`, `--move`, `--release-slug`, `--drop` (attended
only; these flags are never used unattended).
