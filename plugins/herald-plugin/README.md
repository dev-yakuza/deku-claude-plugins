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
`review` · `refresh` · `translate` — **State** `status` (`--requeue` `--drop` `--withdraw` `--withdraw-lang` `--unwithdraw`
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
  boundary; `/hrd audit` checks after the fact.
- A **verification ledger** (local) and a **pre-deploy integrity check** compare every Herald
  article on the base branch with what was verified before any deploy.

## Status

`0.9.0` — implemented end to end, after ten rounds of adversarial implementation review plus a review loop per later change; 0.3.0 records growth signals in code, 0.4.0 caps external-audit rounds, 0.5.0 makes `write` run without questions by default (`--attended` to ask) and answers in the configured language, 0.6.0 adds `/hrd next` (plan if needed → write → ship one article) and lets the agents repair a small verify gap by deleting the unsupported sentences instead of holding, 0.7.0 makes readability part of the bar (writer rules for plain, human prose without invented experience; an editor reader pass; readability hints in the gate; sentences the fact-checker treats as the article's own example under a framing are listed and keep the PR out of auto publish unless consented), 0.7.1 shows the review panel's recommendation (apply or reject, with the reason) on each `/hrd evolve` approval, 0.8.0 sends a claim the fact-checker finds wrong in the research back to the researcher (not only the writer) and keeps one loopback past the cap for a wrong fact, so polishing never leaves a factual error without a fix, 0.9.0 adds multilingual publishing — one source article translated into the `translations` languages of config (a `translation` stage after critique, one translator per language, translations mapped to the same claims so code catches dropped or added facts, the fact-checker checking each against its claims and the source sentence), the source and its translations verified, ledgered and published as one bundle with integrity reporting what changed (source, translation, image, a translation added or removed), later translation of published articles with `/hrd translate` (`--adopt` a human translation, `--missing`), `status --withdraw-lang` to take one language down, and translated PRs kept out of auto publish unless `translations.auto_publish` — repos without `translations` behave as in 0.8.0 (existing repos: run `/hrd update`, then `/hrd resume` asks to merge base into an article's branch; from before 0.4.0, an article in progress counts its audit rounds from 1 again); the deterministic layer is covered by tests
(`bash plugins/herald-plugin/tests/run_tests.sh`). `evolve`'s usefulness and metric-driven
proposals need accumulated real use before they can be judged.
