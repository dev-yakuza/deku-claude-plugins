# HELP

Show this in `config.language` (not initialized: the language rule in SKILL.md):

**Setup** — `init [lang]` install the harness · `config [key value]` dials · `update [--check]`
adopt central improvements

**Writing** — `plan [--n N] [--auto]` build the topic queue (`--auto`: the editor-in-chief picks) · `write <id> [--attended] [--ship]` one article to a PR (no questions until the PR; `--attended`: ask at each gate and approve before the PR; `--ship`: publish it right away) ·
`brief|research|draft|critique|verify|publish <id>` one stage · `resume <id> [--attended] [--ship]` continue ·
`batch [--n N]` unattended writing (and auto publish if enabled)

**Publishing** — `next [--attended]` one more article published end to end (plans first if the queue is empty; the guard still confirms merge and deploy) · `ship [ids|PRs]` approve, re-verify, merge, deploy, confirm, record ·
`ship --reverify <id>` · `ship --deploy-only <id …>` · `ship <PR> --session-auto [--consent]` · `review <id|slug|PR>` independent audit ·
`refresh <slug> [--attended] [--ship] [--direction <id>] [--force-update] [--for-translation]` bring an article up to date — the strategist recommends update (same URL), new article or nothing; you decide · `translate <slug> [--lang l,…] [--adopt l,…]` add languages to a published article (`--missing`: every article lacking one; `--resume <id>` continue)

**Social** — `social --setup` the account persona · `social --add|--edit|--remove <sns>` a channel guide (researched) · `social --persona` · `social --list` · `social <sns> <slug> [--n N]` promotional drafts for a published article · `social <sns> --daily [--theme …]` daily drafts — Herald drafts; a human picks and uploads

**State** — `status [--requeue|--drop|--withdraw|--withdraw-lang|--unwithdraw|--move|--release-slug|
--mark-published|--unlock]`

**Growth & checks** — `evolve [--dry-run|--apply]` · `rollback <evolve#n|commit>` · `audit` ·
`monitoring [--connect-gsc]` · `ask <question>` · `contribute` (not available yet)

Flow: `init` → `plan` → `write` (or `batch`) → `ship` — or `next` for all of it, one article at a time. Accuracy is a floor: nothing unverified
is published through Herald.
