# ATOM — Invariants (INV1–INV6)

**Not a stage.** The single definition of Herald's safety invariants. Every command that cites
an `INVn` cites this file. Design source: `design/herald/00-plan.md` §3.4.

## Charter floor (D2)

> Accuracy is a **floor**, not a priority. On Herald's publishing paths (`ship`, auto publish)
> no body that has not passed `verify` is ever published — including bodies a human edited.
> Above the floor: search visibility > reader value.

The charter's priority order is never an `evolve` proposal target; only a human edits it.

## The six

**INV1 — application always needs human approval.**
`evolve` applies per item after a human says yes; publishing (`ship`) asks per PR by default;
auto-generated rules start as drafts; unattended runs never dismiss an auditor `BLOCKER`.
*Mechanically*: guard `ask` (attended) / `deny` (unattended) on `gh pr merge` and the deploy
command; `autonomy.publish: auto` merges only PRs in `HRD_AUTO_PRS` with `--match-head-commit`.

**INV2 — nothing weakens verification.**
Changes that loosen fact-check rules, critique criteria, exemplars (replacing is allowed,
deleting or downgrading is not), the deterministic gate, or the charter floor are blocked.
*Mechanically*: guard on criteria files, critique/verify personas and protected config keys;
`evolve` panel veto + apply-time check.
For social posts (`design/herald/03-social.md` S14) the floor is: the post checks themselves
(no service effect told as a personal experience, no statistics in daily posts), confirmed
`forbidden` rules in channel guides, the persona and gate rules (including turning a confirmed
gate rule to `"scope": "article"`), the disclosure items and the waiver, and the persona's
`service_terms` (removing one, adding an exclusion). Only a human loosens them, one named item at
a time (`HRD social lint --allow-floor`, recorded as a `Herald-Floor:` commit trailer); the
distributor's Habits never contradict them.

**INV3 — everything is reversible.**
git is the substrate; `/hrd rollback` reverts an evolve run. No `reset --hard`, no force push,
no history rewrite by any command. *Boundary*: gitignored files (`signals.jsonl`, `ledger/`,
`memory/`) and remote state (labels, deployed site) are not git-recoverable.

**INV4 — additive; never clobbers local evolution.**
`init`/`update` merge. `update` refreshes only persona frontmatter `name`/`description` and the
region between `<!-- herald:persona:start -->` and `<!-- herald:persona:end -->`. Everything else
under `.claude/agents/`, `docs/editorial/`, `config.json` is local-owned. The exceptions are
`update`'s offers, each applied only on the human's approval: to append new style-guide lines (a
decline appends only a version marker comment, so the offer is not repeated; never removing or
rewording a line — `update.md` step 3), to create a missing `refresh-policy.md` from the
template (a new file), and to replace the old "Project specifics" values of a translator
(pre-0.9.0) or distributor (pre-0.11.0) persona with the line pointing to `config.json`
`translations` or the channel guides.

**INV5 — nothing leaves the machine un-sanitized.**
Local growth data (signals, memory, ledger) and article drafts never go to the plugin
repository or any third party: `/hrd contribute` is not available yet (it needs a deterministic
secret scanner first), so flow-level ideas are filed by hand by the human. (Pushes, PRs and
deploys to this repo's own remote are the normal flow, not outbound sharing.)
Search Console credentials live only in `.claude/herald/secrets/` (gitignored).

**INV6 — draft → confirm → enforce.**
Rules `init` extracts from existing articles (style rules, forbidden phrases) start with
`"status": "draft"` in `gate-rules.json` and only warn until a human sets `"confirmed"`. The
same holds for `forbidden` rules research or evolve adds to channel guides and the persona: only
a human confirms one (`HRD social lint` refuses anything else).

## Honest scope of the enforcement layer

The guard (`.claude/herald/scripts/guard.py`, PreToolUse) is a **string-pattern tripwire**:
it inspects tool calls Claude makes in this repo. It does not see edits made outside Claude,
`git commit --no-verify` by a human, or GitHub UI merges. `/hrd audit` checks after the fact
(protected-file history vs the evolve ledger; ledger append-only). Never describe the guard as
a boundary against a determined bypass.
