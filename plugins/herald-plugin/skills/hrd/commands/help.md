# HELP

Show this in `config.language` (English if not initialized):

**Setup** — `init [lang]` install the harness · `config [key value]` dials · `update [--check]`
adopt central improvements

**Writing** — `plan [--n N]` build the topic queue · `write <id>` one article to a PR ·
`brief|research|draft|critique|verify|publish <id>` one stage · `resume <id>` continue ·
`batch [--n N]` unattended writing (and auto publish if enabled)

**Publishing** — `ship [ids|PRs]` approve, re-verify, merge, deploy, confirm, record ·
`ship --reverify <id>` · `ship --deploy-only <id …>` · `review <id|slug|PR>` independent audit ·
`refresh <slug>` update an article

**State** — `status [--requeue|--drop|--withdraw|--unwithdraw|--move|--release-slug|
--mark-published|--unlock]`

**Growth & checks** — `evolve [--dry-run|--apply]` · `rollback <evolve#n|commit>` · `audit` ·
`monitoring [--connect-gsc]` · `ask <question>` · `contribute`

Flow: `init` → `plan` → `write` (or `batch`) → `ship`. Accuracy is a floor: nothing unverified
is published through Herald.
