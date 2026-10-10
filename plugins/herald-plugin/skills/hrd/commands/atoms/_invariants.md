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

**INV3 — everything is reversible.**
git is the substrate; `/hrd rollback` reverts an evolve run. No `reset --hard`, no force push,
no history rewrite by any command. *Boundary*: gitignored files (`signals.jsonl`, `ledger/`,
`memory/`) and remote state (labels, deployed site) are not git-recoverable.

**INV4 — additive; never clobbers local evolution.**
`init`/`update` merge. `update` refreshes only persona frontmatter `name`/`description` and the
region between `<!-- herald:persona:start -->` and `<!-- herald:persona:end -->`. Everything else
under `.claude/agents/`, `docs/editorial/`, `config.json` is local-owned.

**INV5 — nothing leaves the machine un-sanitized.**
`/hrd contribute` is the only outbound path (secret scan, generalization, human preview).
Search Console credentials live only in `.claude/herald/secrets/` (gitignored).

**INV6 — draft → confirm → enforce.**
Rules `init` extracts from existing articles (style rules, forbidden phrases) start with
`"status": "draft"` in `gate-rules.json` and only warn until a human sets `"confirmed"`.

## Honest scope of the enforcement layer

The guard (`.claude/herald/scripts/guard.py`, PreToolUse) is a **string-pattern tripwire**:
it inspects tool calls Claude makes in this repo. It does not see edits made outside Claude,
`git commit --no-verify` by a human, or GitHub UI merges. `/hrd audit` checks after the fact
(protected-file history vs the evolve ledger; ledger append-only). Never describe the guard as
a boundary against a determined bypass.
