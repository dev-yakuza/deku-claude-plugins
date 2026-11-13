# Herald Plugin

A **per-repo editorial organization** for Claude Code. Herald installs a writing harness into a
repository; a team of role agents specialized to that repo plans topics, writes professional
blog articles through `brief → research → draft → critique → verify → publish`, ships them
through PR review, and grows its guides from real usage.

> Sibling of [Guild](../guild-plugin) (software development). Same idea — a harness, a role
> spine, an inner loop that produces and an outer loop that grows — applied to writing.

[한국어](./README.ko.md) · [日本語](./README.ja.md)

## Concepts

- **Purpose** — promote a service or app. North star: CTA clicks / sign-ups; search visibility
  is the means.
- **Accuracy is a floor** — on Herald's publishing paths nothing that has not passed `verify`
  is published, including human-edited text. Above the floor: search visibility > reader value.
- **Spine roles** — editor-in-chief (the main session), content strategist, researcher, writer,
  fact-checker, editor. **Conditional** — subject expert, search & discovery (SEO · AEO · GEO
  lenses), illustrator, translator, distributor.
- **External auditor** — a fresh, persona-less reviewer outside the organization runs after
  an editor PASS (up to 3 rounds per article; later rounds block only on BLOCKERs, unfixed
  findings and regressions, the rest goes to the PR) and again outside the flow (`/hrd review`).
- **Publishing = `/hrd ship`** — per-PR approval, re-verification of human edits, merge, deploy,
  URL check, record. Nothing is published by writing alone.

## Install

```bash
claude /plugin marketplace add dev-yakuza/deku-claude-plugins
claude /plugin install deku-claude-plugins@herald-plugin
```

Requirements: `git` ≥ 2.38, `gh` (authenticated), `python3` ≥ 3.9. Batch: the `claude` CLI.
Search Console (optional): `pip install google-auth requests`.

## Quick start

```bash
/hrd init            # analyze the repo + interview → harness (review it before committing)
/hrd plan            # topic clusters into the queue
/hrd write t0001     # one article → PR, no questions until the PR
/hrd write t0001 --attended  # same, asking at each gate and approving before the PR
/hrd ship            # approve PRs → re-verify → merge → deploy → confirm URL → record
/hrd next            # one more article published end to end (plans first if the queue is empty)
/hrd batch --n 5     # unattended writing; with autonomy.publish=auto also publishes
/hrd status          # topics, holds, maintenance flags
```

## Commands

**Setup** `init` · `config` · `update` — **Writing** `plan` · `write` · `brief` · `research` ·
`draft` · `critique` · `verify` · `publish` · `resume` · `batch` — **Publishing** `next` · `ship` ·
`review` · `refresh` · `translate` — **Social** `social` (`--setup` `--add` `--refresh` `--edit` `--persona` `--remove` `--list`; drafts: `social <sns> <slug>`, `social <sns> --daily`; `--final`) — **State** `status` (`--requeue` `--drop` `--withdraw` `--withdraw-lang` `--unwithdraw`
`--move` `--release-slug` `--mark-published` `--unlock`) — **Growth & checks** `evolve` ·
`rollback` · `audit` · `monitoring` · `ask` · `contribute` (not available yet). Details: `/hrd help`.

## Safety

- **INV1** applying changes always needs a human; unattended runs never merge in approve mode
  and never dismiss an auditor BLOCKER. **INV2** nothing loosens verification (criteria, gate,
  exemplars, the floor). **INV3** everything is reversible (git, `/hrd rollback`). **INV4**
  additive, never clobbers local evolution. **INV5** nothing leaves the machine unsanitized.
  **INV6** extracted rules start as drafts.
- A **PreToolUse guard** (`.claude/herald/scripts/guard.py`) asks (attended) or denies
  (unattended) edits to criteria, critique/verify personas, protected config keys, the
  verification ledger, merges, deploys and out-of-scope commits. It is a tripwire, not a
  boundary; `/hrd audit` checks after the fact. A guard that crashes or cannot start still asks
  before a merge or the deploy; one killed at its hook timeout (30 s) decides nothing, and since
  0.20.0 the settings no longer ask before `gh pr merge` themselves.
- A **verification ledger** (local) and a **pre-deploy integrity check** compare every Herald
  article on the base branch with what was verified before any deploy.

## Scene images (0.18.0)

With `images.scenes` (`/hrd config images`), an image place can be a **scene** — a situation that
need not be real (a traveler at an immigration counter), never a real person, place, brand or work.
limner generates it locally with **Qwen-Image-Edit-2511 (4-bit) + Lightning 8-step** (Apache-2.0,
the model store shared with script2video, `lmn setup` ≈ 54 GB): about 2–3 minutes per picture on
an M2 Max with 64 GB, so the editor-in-chief starts limner's detached worker and checks on it in
short calls, holding the article (`tooling: limner …`) past `wait_minutes`; `/hrd resume` takes the
same run over. Scenes carry **no text** (Herald appends a fixed no-text sentence to an English
prompt), and the body always shows an **AI label** next to the picture (`images.figure.scene`'s
`{label}` — checked for every article of the slug at draft, verify and publish, outside the repo's
own validator, never trimmed away). The illustrator reviews each picture first, and **a human
confirms every scene** before draft passes: a generation ledger plus the confirmation ledger, not a
state field, decide it, so an unconfirmed picture never reaches the remote. Without limner, a model
or the RAM, scenes are simply off; translation repos keep them off.

## SNS formats (0.19.0)

`/hrd social <sns> <slug> --format image|cards|comic` (and `--daily`) adds pictures to a post: **one
image**, **card news** (a carousel of a cover, 1–8 point cards and an end card) or **a comic** (one
2×2 or 3×2 strip, one draft per run). Every picture is composed by limner from layouts that are
Herald constants — words are never drawn by a model; a comic's panels are generated without text
and the bubbles and captions are composed on top. Pictures come only from the article's own
diagrams, its limner OG card and scenes a human confirmed (as committed), or are generated for the
draft; a quotation's or an external image's bytes never go out. The words in the pictures are
checked together with the post text (statistics, service experience, quotes, a service mention
makes the post an ad), and a post with a generated picture always carries the channel's
**`ai_disclosure`** (a text in the post or the platform's AI label setting, separate from the ad
disclosure). `check` and `close` compare each picture with limner's protected compose record — the
output, every input picture and the layout rebuilt from the spec — so the picture the human approves
is the one Herald checked; `--final` keeps the approved profile and the AI disclosure. A guide
without `formats` stays text only (`/hrd social --refresh <sns>` researches the formats).

## `--ship` all the way (0.20.0)

`/hrd write <id> --ship` (also `resume`, `refresh`, `translate` with `--ship`, and `/hrd next`) is
the human's request to publish that one article with **no human look**. Where a human used to
confirm an external image, a quotation, a scene or an automatic screenshot, a **fresh illustrator
spawn reviews it** and Herald confirms it with `--agent` — recorded apart from a human's
confirmation (`by: agent` in the ledger, the PR body's `agent-reviewed (no human look)`, the ship
report, `agent_confirmed` in `published.json`) and valid only for that topic, place and content.
The PR is then merged and deployed without a question: `HRD lock ship-pass` re-checks the PR head
and the guard answers `allow` to exactly the verified `gh pr merge … --match-head-commit <sha>` and
the configured deploy string. The only proof of the flag is the checkout lock's mark (guarded), so
it is added only when a human writes it. Defects still stop the article at its PR — an open,
deferred or agent-dismissed BLOCKER, a changed critique or verify file, a file in the PR nobody
vouched for (`images-unconfirmed`), a screenshot only a human can take, a capture the review
flagged, the daily throttle. Batch and every run without `--ship` are unchanged; `/hrd update`
offers to remove the 0.19.0 settings rule that asked before `gh pr merge` (the guard asks itself).

## Stand-ins and decorative pictures (0.21.0)

When an external image of a real **place or ordinary thing** has no usable photo (no candidate,
every candidate failed or was turned down, or a human chose "a generic AI picture instead"),
Herald draws a **generic** scene that is not that place — "a mountain temple among autumn leaves"
for Kiyomizu-dera — labelled next to the picture as "AI-generated image (not the actual place)".
The brief marks what each place is (`external (place|thing|work|person|quotation)`); works,
characters, branded products, logos, real people and text are never drawn instead, and a human's
"go without" is never turned into one. Every decision is tied to the brief line (its hash), which
cannot change after brief passes; the research candidates are fixed after the first research pass.
A stand-in gets a subject check before it is generated, a stricter review (Japanese details, no
recognisable landmark), a human's look (or a `--ship` run's fresh review), stays out of SNS
materials, and is listed in the PR body and `published.json`. Stand-ins are **on by default**
where scenes and external images are both on (`images.scenes.stand_in: false` turns them off;
quoting categories are off unless named in `stand_in_per_category`). Decorative pictures are
opt-in (`images.scenes.decorative`, 0–3, default 0): between sections only, never first, within
the article's scene, external and total limits.

## Status

`0.22.1` — implemented end to end, after ten rounds of adversarial implementation review plus a review loop per later change; 0.3.0 records growth signals in code, 0.4.0 caps external-audit rounds, 0.5.0 makes `write` run without questions by default (`--attended` to ask) and answers in the configured language, 0.6.0 adds `/hrd next` (plan if needed → write → ship one article) and lets the agents repair a small verify gap by deleting the unsupported sentences instead of holding, 0.7.0 makes readability part of the bar (writer rules for plain, human prose without invented experience; an editor reader pass; readability hints in the gate; sentences the fact-checker treats as the article's own example under a framing are listed and keep the PR out of auto publish unless consented), 0.7.1 shows the review panel's recommendation (apply or reject, with the reason) on each `/hrd evolve` approval, 0.8.0 sends a claim the fact-checker finds wrong in the research back to the researcher (not only the writer) and keeps one loopback past the cap for a wrong fact, so polishing never leaves a factual error without a fix, 0.9.0 adds multilingual publishing — one source article translated into the `translations` languages of config (a `translation` stage after critique, one translator per language, translations mapped to the same claims so code catches dropped or added facts, the fact-checker checking each against its claims and the source sentence), the source and its translations verified, ledgered and published as one bundle with integrity reporting what changed (source, translation, image, a translation added or removed), later translation of published articles with `/hrd translate` (`--adopt` a human translation, `--missing`), `status --withdraw-lang` to take one language down, and translated PRs kept out of auto publish unless `translations.auto_publish` — repos without `translations` behave as in 0.8.0, 0.10.0 adds the refresh decision — before `/hrd refresh` queues anything the strategist recommends update (same URL), a new article or nothing, with its reasons and the repo's `refresh-policy.md`, and a human decides (an overturned recommendation is an evolve signal); a new article continues into write in the same session and the old one is flagged for a link; plan turns rejected near-duplicates into refresh suggestions; refresh behaviour now lives in the stage spine so next, batch and resume apply it too; a new article never takes a slug in use (existing repos: run `/hrd update`, then `/hrd resume` asks to merge base into an article's branch; from before 0.4.0, an article in progress counts its audit rounds from 1 again), 0.11.0 adds social post drafts — `/hrd social --setup` defines the account's one fictional persona (background kept off the posts, voice, service terms, the mix of promotional to daily posts) and researched empathy themes, `--add <sns>` researches a channel into a guide (format, length, hashtags, links, ad and operator disclosure rules), and `/hrd social <sns> <slug>` or `--daily` drafts posts that code checks before a human picks one: promotional facts only as exact quotes of the verified article or `promotion.md`, only the article's own URL, the channel's disclosure, no statistics in daily posts, no service effect told as a personal experience; floor changes to the guides need a named human approval; Herald never posts, 0.12.0 adds `--refresh <sns>` (re-research merged by code: identity, house rules and confirmed rules stay, a weaker disclosure only on a named approval), `--final` (the text actually posted), growth signals from social drafts (edit requests, rejected runs, failed checks, changed finals — counted per SNS day) for `/hrd evolve`, and a floor check on every commit of the guides and the persona, 0.13.0 trims what enters the session's context — compact HRD output, only the integrity rows that need something, `gsc.py show --slug`, no pointers to design documents users do not have — and makes cost measurable: `measure.py` follows `CLAUDE_CONFIG_DIR` (budget checks found no transcript when it was set), counts nested sub-agents, labels each spawn by its `description` (`Herald: <role> — <task>`, never shown to the sub-agent), and `--detail` attributes the main session's context to files, commands and agents, 0.13.1 makes `--detail` attribute shell commands that call HRD through a variable, a function or `eval`, or read prompt files through a path variable, to the HRD command or file instead of the shell word, 0.14.0 makes `/hrd batch` wait out Claude usage limits — it reads the limit from the child's stream (any exit code: the last rate-limit event, a damaged one, or the error and result text, with the reset time when one is named), keeps the work on the topic's branch and holds it before sleeping, waits until the reset (up to 5h per wait, 12h per run, while the checkout lock names the waiting pid), resumes the topic with `/hrd resume` and releases the hold once its PR exists; a longer limit stops the run cleanly, a sub-agent's usage limit is treated the same way, and the ship child is never re-run after one; in 0.15.0 screenshots a human takes — when an article needs screens, the strategist, researcher and writer produce a capture guide (the steps to each screen with their sources, what to hide), the human drops the files into a local inbox, Herald strips them to the image data alone (an allowlist, so no metadata leaves) and the draft does not pass until every one is in (default and batch: a `screenshots` hold, then `/hrd resume`); the editor and auditor look at each screen (anything personal is a BLOCKER), an article with screenshots is never published by consent but waits for a separate confirmation in `/hrd ship`, and publish rebuilds the branch as one commit so no unreviewed screen stays in its history; in 0.16.0 Herald captures public, login-free pages itself when `screenshots.capture` is set (an argv template run without a shell, only restricted `https://` URLs on public hosts, a failure hands the screen to a human for good), and every capture counts only after a human confirms it — a protected capture log and confirmation ledger, not a state field, tell an unconfirmed capture from a human's file, and publish checks every commit it pushes; in 0.17.0 (`/hrd config images`) brief plans each image as one kind — a screenshot, an SVG diagram the illustrator draws and limner renders to PNG (its text is verified like sentences, by a committed render record only `HRD image render` writes), or an external image fetched from a free license or quoted from a rights holder's page (fetched by Herald itself with SSRF guards, metadata stripped but colour kept, attribution in the body, confirmed by a human and never consented away; a quotation never becomes an OG or SNS image) — plus an OG card from the repo's generator or limner `og-title` that turns `off` instead of holding when it cannot be made; without an `images` block or limner everything is 0.16.0; in 0.18.0 scene images (above) —
generated by limner, reviewed by the illustrator, confirmed by a human, always labelled as
AI-generated — and a repo without `images.scenes` behaves as 0.17.0; in 0.19.0 SNS formats (above) — a single
image, card news and comics composed by limner, the AI disclosure separate from the ad one — and a
channel guide without `formats` behaves as 0.18.0; in 0.20.0 `--ship` all the way (above) — an agent review instead of the image and screenshot confirmations, the verified merge and the deploy without a question — and every run without `--ship` behaves as 0.19.0; in 0.21.0 stand-ins and decorative pictures (above) — a topic started with a 0.20.0 brief gets none; in 0.22.0 the auditor of a refresh gets the refresh's scope quoted by code, a finding in a sentence the refresh did not touch is left for the next refresh (checked in code against the article as the refresh found it, never a BLOCKER, listed in the PR and the ship report, kept in `published.json` `refresh_candidates` for the next refresh's brief), a dismissal resting on research the auditor cannot see names its claims (`grounds`, an extra evolve axis that still counts as a dismissal), and `/hrd evolve` can retire stale signals on a human's decision (recorded with the reason in the evolution log, undone with `--unretire`), in 0.22.1 a decorative photo's whole figure — picture plus caption lines — is what must sit right before the next section heading (a figcaption template no longer reads as misplaced); the deterministic layer is covered by tests
(`bash plugins/herald-plugin/tests/run_tests.sh`). `evolve`'s usefulness and metric-driven
proposals need accumulated real use before they can be judged.
