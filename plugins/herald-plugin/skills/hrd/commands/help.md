# HELP

Show this in `config.language` (not initialized: the language rule in SKILL.md):

**Setup** — `init [lang]` install the harness · `config [key value]` dials (`config images`: SVG diagrams, external images, scene images, stand-ins for places with no photo, decorative pictures and the OG card, with limner) · `update [--check]`
adopt central improvements

**Writing** — `plan [--n N] [--auto]` build the topic queue (`--auto`: the editor-in-chief picks) · `write <id> [--attended] [--ship]` one article to a PR (no questions until the PR; `--attended`: ask at each gate and approve before the PR; `--ship`: publish it right away — no human look: a fresh agent review stands in for the image and screenshot confirmations, and the guard lets the verified merge and the deploy through; an article with a defect still stops at its PR) ·
`brief|research|draft|critique|verify|publish <id>` one stage · `resume <id> [--attended] [--ship]` continue (a `screenshots` hold: put the files in `.claude/herald/inbox/<id>/` first, as the capture guide says — or look at the external images and scenes it lists) ·
`batch [--n N]` unattended writing (and auto publish if enabled)

**Publishing** — `next [--attended]` one more article published end to end, as `write --ship` (plans first if the queue is empty) · `ship [ids|PRs]` approve, re-verify, merge, deploy, confirm, record ·
`ship --reverify <id>` · `ship --deploy-only <id …>` · `ship <PR> --session-auto [--consent]` · `review <id|slug|PR>` independent audit ·
`refresh <slug> [--attended] [--ship] [--direction <id>] [--force-update] [--for-translation]` bring an article up to date — the strategist recommends update (same URL), new article or nothing; you decide · `translate <slug> [--lang l,…] [--adopt l,…]` add languages to a published article (`--missing`: every article lacking one; `--resume <id>` continue)

**Social** — `social --setup` the account persona · `social --add|--refresh|--edit|--remove <sns>` a channel guide (researched) · `social --persona` · `social --list` · `social <sns> <slug> [--n N]` promotional drafts for a published article · `social <sns> --daily [--theme …]` daily drafts · `social --final <draft>` the text actually posted — Herald drafts; a human picks and uploads

**State** — `status [--requeue|--drop|--withdraw|--withdraw-lang|--unwithdraw|--move|--release-slug|
--mark-published|--unlock]`

**Growth & checks** — `evolve [--dry-run|--apply]` · `rollback <evolve#n|commit>` · `audit` ·
`monitoring [--connect-gsc]` · `ask <question>` · `contribute` (not available yet)

Flow: `init` → `plan` → `write` (or `batch`) → `ship` — or `next` for all of it, one article at a time. Accuracy is a floor: nothing unverified
is published through Herald.
