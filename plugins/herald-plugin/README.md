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
  every editor PASS and again outside the flow (`/hrd review`).
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
/hrd write t0001     # one article → PR (approve it in the session first)
/hrd ship            # approve PRs → re-verify → merge → deploy → confirm URL → record
/hrd batch --n 5     # unattended writing; with autonomy.publish=auto also publishes
/hrd status          # topics, holds, maintenance flags
```

## Commands

**Setup** `init` · `config` · `update` — **Writing** `plan` · `write` · `brief` · `research` ·
`draft` · `critique` · `verify` · `publish` · `resume` · `batch` — **Publishing** `ship` ·
`review` · `refresh` — **State** `status` (`--requeue` `--drop` `--withdraw` `--unwithdraw`
`--move` `--release-slug` `--mark-published` `--unlock`) — **Growth & checks** `evolve` ·
`rollback` · `audit` · `monitoring` · `ask` · `contribute`. Details: `/hrd help`.

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

`0.2.0` — implemented end to end, after ten rounds of adversarial implementation review; the deterministic layer is covered by tests
(`bash plugins/herald-plugin/tests/run_tests.sh`). `evolve`'s usefulness and metric-driven
proposals need accumulated real use before they can be judged.
