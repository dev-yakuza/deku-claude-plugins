# SOCIAL — SNS post drafts (`/hrd social …`)

Drafts posts for social channels in the voice of the account's one fictional persona:
promotional posts for published articles and daily posts of the persona's ordinary life (mixed
in so the account does not read as an ad account). Herald never posts — a human or another tool
uploads the post the human picked. Design: `design/herald/03-social.md`. Interactive only: refuse when `HRD_UNATTENDED=1`.

| Input | What it does |
|---|---|
| `--setup` | first setup: the persona, its empathy notes, the distributor role |
| `--add <sns>` | research a channel into a guide |
| `--refresh <sns>` | re-research a channel; only the researched part changes |
| `--edit <sns>` | a human's change to a channel guide (house rules, disclosure, confirming rules, aliases, language) |
| `--persona` | change the persona or its empathy notes |
| `--remove <sns>` | delete a channel guide (local drafts stay) |
| `--list` | channels, their state and the recent post mix |
| `<sns> <slug> [--n N]` | N promotional drafts (1–5, default 3) for a published article |
| `<sns> --daily [--theme "…"] [--n N]` | N daily drafts |
| `--final <draft>` | record the text actually uploaded for an approved draft |
| `<sns>` alone | show this table and stop |

Options may come in any order; the first positional argument after `<sns>` is the slug. A slug
together with `--daily` is an error. `<sns>` is matched case-insensitively against guide names
and their aliases; an unknown name → "`/hrd social --add <sns>` first".

Translate `HRD` output into `config.language`; keep ids, paths, rule ids and commands as they are.

## Common start (every mode except `--list` and `--final`)

1. `HRD lock acquire --cmd social` (keep the token; `HRD lock release --cmd social --token <t>`
   on every exit path).
2. Base checked out, tracked tree clean (else stop); `HRD sync`; the version check again
   (SKILL.md).

## Setting modes

Work in `.claude/herald/memory/social/pending/` (local): never write `docs/editorial/` before
the human approved. For each file: `HRD social lint --mode <setup|add|edit|persona|refresh> --file
<pending file> --target <repo path>` must pass before the human sees it (errors → fix and lint
again). `lint` checks the format and, against HEAD, the floor — a removed or downgraded
confirmed rule, a weaker disclosure, a removed service term, an added exclusion, a disclosure
waiver, a channel language without default checks. Each floor change needs the human's explicit
yes (`AskUserQuestion`, naming exactly what is lost) before you pass `--allow-floor <token>`; a
rule the human confirms needs `--strengthen <token>`. `lint` prints the trailers to commit with
(`trailers`, each naming its file: `<file>::<token>`); add the human's reason in English:
`--trailer "Herald-Floor: <file>::<token> — <reason>"`. A commit of several social files accepts
only file-named tokens.

After approval: **you** copy each pending file to its repo path with Write or `cp` (the guard
asks — these are criteria files; `HRD` never writes them), run `lint` again with `--file` = the
repo path (a later tweak must not skip the check), then `HRD commit --cmd harness --kind social
-m "chore(herald): social <setup|add|refresh|edit|persona|remove> [<sns>]" [--trailer …] <paths>` and
`git push origin <base>`, then release. `HRD commit` checks the floor of these files again against
the trailers (whichever command commits them), and the guard asks before a plain `git commit` of them. Declined, aborted or a failed commit → put every repo
file you wrote back (`git checkout HEAD -- <path>`; delete a new file), release and stop. A failed
push → keep the commit, say so, and tell the human to push again.

Say once, at `--setup` and `--add`: the persona, the channel guides (a waiver's reason too) and
the empathy notes are committed with the repo, which may be public.

### `--setup`
1. `docs/editorial/persona.md` already on base → point to `--persona` and stop.
2. Article rules on posts: list the `confirmed` forbidden rules of `docs/editorial/gate-rules.json`
   (common and per language). Ask per rule whether it is for articles only (e.g. a ban on the
   first person) or for posts too; set `"scope": "article"` on the articles-only ones (the guard
   asks) and commit each with `--trailer "Herald-Floor: gate-scope:<pattern> — <reason>"`.
   Later, turning a confirmed rule to `article` loosens posts — only by a human, the same way.
3. Interview (`AskUserQuestion`, at most 4 per call): the persona's background (never stated in
   posts), voice, point of view, daily themes, things it never says; the service terms — the
   service's names, product and feature names, their spelling in each language the channels will
   use (transliterations), official account handles; the mix of promotional to daily posts
   (default 1 : 3). Lay out `pending/persona.md` from `<<SKILL_DIR>>/templates/editorial/persona.md.tmpl`,
   filled in `config.language`, every `{{…}}` replaced.
4. Spawn **researcher** for the empathy notes: the persona file; output `pending/persona-notes.md`
   laid out from `persona-notes.md.tmpl`.
5. Lint both (`--mode setup`), show them, the human approves or edits.
6. Turn the role on: add `distributor` to `roles.conditional` in `.claude/herald/config.json`
   (protected — the guard asks); `.claude/agents/distributor.md` missing → create it from
   `<<SKILL_DIR>>/templates/agents/distributor.md` with `{{PROJECT_NAME}}` taken from another
   persona's title (`# Editor — <name>`), else ask. Offer to update "Enabled conditional roles" in
   `.claude/agents/editor-in-chief.md` (local-owned; on approval only).
7. Copy, lint, commit (persona, notes, config.json, distributor.md, and any gate-rules or
   editor-in-chief change), push, release. Next: `/hrd social --add <sns>`.

### `--add <sns>`
1. No persona on base → `--setup` first. The name: lowercase `[a-z0-9-]`, not `pending`,
   `approved`, `final` or `drafts`; already a guide's name or alias (`HRD social list`) → point
   to `--edit` and stop.
2. Ask the human the posts' language (default: the source language — `HRD social list`
   `source_lang`) and other names people type for this channel (aliases). A channel that existed before (`--remove`d) is compared with its removed version: carry its
   confirmed rules and disclosure texts over, or each loss needs the human's yes. A language that is
   neither the source nor a translation target makes the channel daily-only; a language other
   than `config.language` means daily posts never mention the service there (`promotion.md` is in
   `config.language`) — say so.
3. Lay out `pending/channels/<sns>.md` from `<<SKILL_DIR>>/templates/editorial/channel.md.tmpl`
   (name, aliases, lang filled) and spawn **researcher** (channel research) with that path, the
   persona and the language line.
4. `lint --mode add`. Typical decisions:
   - no required ad disclosure (post text or platform setting) — ask the human: add one (its text
     and where), or waive it for this channel. A waiver is written by you, from the human's own
     reason: `"disclosure_waiver": {"kind": "ad", "reason": "…", "approved_at": "<today>"}`, with
     `--allow-floor disclosure_waiver`. Research finding no rule is not a reason;
   - a language without default checks (`s9:<lang>`) — the statistics and service-experience
     checks are off for this channel; only the human accepts that;
   - a warning that no service term is written in this channel's script → offer `--persona`.
5. Show the guide, approve, copy, lint, commit, push, release. Any `where: profile` disclosure →
   give the human the profile checklist (what to put in the account profile).

### `--refresh <sns>`
1. Spawn **researcher** (channel re-research) with the committed guide as the starting point and
   the path `pending/channels/<sns>.md`; it rewrites the head block's research fields, the
   researched region, the `disclosure` items and new `forbidden` entries (as draft) from current
   sources — the disclosure rules are the main reason to re-research.
2. `HRD social merge --sns <sns> --researched pending/channels/<sns>.md` — code merges: research
   fields and the researched region from the draft; name, aliases, language, `house`, the house
   rules, the waiver and every existing rule's status stay; new `forbidden` rules join as
   `draft`; a disclosure that would get weaker stays as it was. It writes
   `pending/channels/<sns>.merged.md` and prints `changed`, `added_rules`, `disclosure_added`
   and `floor_changes` (each with `applied: false`).
3. Show the human what changed, field by field, and each floor change separately, in plain
   words (what posts lose). The human picks what to take: run `merge` again with `--accept
   <field|region …>` (only those) and `--accept-floor <token>` for each floor change the human
   explicitly accepted (`AskUserQuestion` per item) — never edit the merged file by hand.
4. `HRD social lint --mode refresh --file pending/channels/<sns>.merged.md --target
   docs/editorial/channels/<sns>.md` with `--allow-floor <token>` for the accepted floor changes
   (`next` in the merge output). A merged guide that loses its last required ad disclosure fails
   here: stop and point to `--edit <sns>` (the human decides the disclosure or a waiver there).
5. Copy the merged file to the guide, lint again, commit (`chore(herald): social refresh <sns>`,
   the `Herald-Floor` trailers), push, release. A `where: profile` item that is new → the profile
   checklist.

### `--edit <sns>`
Copy the guide from base to `pending/channels/<sns>.md`, apply the human's change there, then
`lint --mode edit`. Research fields and the researched region change only by `--refresh`. Show
the diff, approve, copy, lint, commit, push, release.

### `--persona`
No persona on base → `--setup`. Copy `persona.md` (and `persona-notes.md` when it changes) to
`pending/`, apply the change, `lint --mode persona` for each, show the diff, approve, copy,
lint, commit, push, release. Removing a service term or adding an exclusion is a floor change.

### `--remove <sns>`
Ask the human to confirm. `rm docs/editorial/channels/<sns>.md` (the guard asks; not `git rm`),
commit with `-m "chore(herald): social remove <sns>"`, push, release. Local drafts stay.

### `--list`
`HRD social list` (no lock; reads base): each channel with its language, aliases, research date
(stale after 180 days), daily-only or not, whether daily posts may mention the service, its
disclosure items or waiver, limits and any problems; whether the persona exists and the role is
on; the recent mix of approved posts against the persona's `mix`.

## Content modes (`<sns> <slug>`, `<sns> --daily`)

After the common start:

1. `HRD social prepare --sns <sns> [--slug <slug>] --n <N>`. A refusal names the reason and the
   next step (`/hrd ship`, `/hrd translate …`, `/hrd config`, `--setup`, `--add`, `--edit`) —
   relay it, release, stop. Show the warnings; an article published without a human reading it →
   ask whether to go on.
2. Spawn **distributor** with: `run`, `kind`, `slug`, `lang`, the draft paths (`drafts` — one file
   each), `limits`, `disclosure`, `daily_service_allowed`, the read list (`read`), the theme
   (`--theme`, daily), and the language line (`atoms/_contract.md` §D).
3. `HRD social check --file <every draft>`. A draft that fails: send its failed rules back to the
   distributor once for that draft, then check it again with `--record` (the last check; a rule
   still failing becomes a growth signal). Still failing → keep it, marked.
   `basis-changed` (the article or the guide's language changed on base since prepare) and
   `check-error` (no such draft, or not a draft prepare laid out) are not writing problems: never
   send them to the distributor — `basis-changed` → run `prepare` again; `check-error` → relay it.
4. Show the human every draft: the text, its profile (`promo`, `daily`, or `daily+service` — a
   daily post naming the service, checked like an ad), failed rules and warnings, its
   `from: promotion` quotes highlighted (the human judges what code cannot: claims beyond the
   quotes, comparisons), and the mix line (`recent_mix` against the persona's `mix`). Ask
   (`AskUserQuestion`):
   - **edit** — record the request first: `HRD signal --kind social-edit-request --topic
     <signal_topic> --data '{"theme": "<tone|length|format|persona|hashtags|disclosure|fact|other>",
     "request": "<what the human asked, in one line>", "run": "<run>", "draft": "<draft>"}'` (pick
     the theme that names what the human objected to); then the distributor rewrites that draft
     (or you write the human's own text to the draft path); every changed draft is checked again
     (step 3, without `--record` until its last check; never `--record` on a text the human wrote —
     a signal is evidence about the distributor's writing);
   - **pick one** — rules marked `overridable: false` cannot be approved (rewrite or pick another).
     Overridable failures (`length`, `hashtags`, `link-position`, `s9b-statistic`,
     `s9a-service-experience` on promotional posts) → ask the human to accept each, with their
     reason → `--override "<reason>"`. Each `settings_to_confirm` → ask the human to turn that
     platform disclosure setting on for this post → `--setting-confirmed <kind>` only on a yes.
     Then `HRD social close --run <run> --approved <draft> […]` (it checks the draft again);
   - **reject all** — `HRD social close --run <run> --reject-all` (it records the growth signal).
5. Release. Show the approved post ready to paste, the platform settings to turn on, and say
   that Herald does not post — and that after uploading, `/hrd social --final <draft>` records
   the text actually posted (optional; a changed text teaches evolve).

## `--final <draft>`

No lock (local records only). The draft must be approved. Ask the human to paste the text as
posted; write it, body only, to `.claude/herald/memory/social/final/<sns>/<draft file name>`,
then `HRD social final --draft <draft> --final-file <that path>`. It records `uploaded`, compares
the text with the approved copy (a change becomes a `social-final` signal; small changes are
evidence, not problems) and checks it for information. `fix_live_post` non-empty (a
disclosure missing, another URL) → tell the human plainly to fix the live post.
