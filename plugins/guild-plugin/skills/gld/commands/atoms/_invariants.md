# ATOM — Invariants (INV1–INV6)

**Not a stage.** The single definition of Guild's six safety invariants. Every command that
cites an `INVn` cites *this* file. Before writing a new `INVn` reference anywhere, check the
number against this list.

Why this file exists: the six were previously defined nowhere and used everywhere — INV1–3
across most commands, INV4 only in `init`/`update`/`rollback`, INV5 only in `contribute`,
INV6 only in `SKILL.md`/`init`. Nothing enumerated all six, so `sprint.md` could claim "all
6 invariants hold" while listing three, and `evolve.md`'s Hard Rules — the natural home for
the canonical list — omitted three. A number with no definition is not an invariant.

---

## The six

**INV1 — application always needs human approval.**
Triggers may fire automatically; *changes never apply unattended*. evolve applies per item
after a human says yes; role/rule HR is per item; every gate is human-gated; **nothing
merges a PR**. Unattended runs (`batch`, `sprint`) *defer* this, they do not remove it: the
leader stands in only for low/medium-stakes discuss decisions, and anything high-stakes
pauses with `guild:needs-human` (`_handoff.md` Section H).
*Mechanically*: `permissions.ask` on `gh pr merge`; evolve's per-item HITL loop.

**INV2 — nothing weakens verification.**
A change that deletes a test file, net-removes assertions, or adds skip/focus directives is
**blocked**, not warned. This is the one invariant with no override: the `gates.enabled`
off-switch governs whether the *commit gate* blocks a `git commit` in a repo it misjudges —
it is not an authorisation to *apply* a verification-weakening change. evolve's Phase 6
step 3 hard-block and the adversarial panel's degradation-lens veto are both absolute.
*Mechanically*: `gate_precommit.py` gate B (git hook + PreToolUse); evolve P4 veto + P6 block.

**INV3 — everything is reversible.**
git is the substrate; `/gld rollback <target>` is the escape hatch; evolve backs up each
constituent file and auto-rolls-back on validation failure. No `reset --hard`, no
force-push, no history rewrite — ever, by any command.
*Known boundary*: reversibility stops at the gitignore line **and at the network boundary**.
`.claude/guild/memory/*` is not committed, so evolve's consolidation bridge (moving
applied-source entries from `ground-truth.jsonl` to `consolidated.jsonl`) and the
review-nudge state are **not** git-recoverable. The second boundary is remote state Guild
writes but git never sees — today that is the GitHub Projects board (`sprint board`): which
column a card sits in cannot be restored by any Guild path, because `--reset` deliberately
leaves the column field alone (clearing it would move every card into the null bucket and
assert something false). Say so rather than implying total coverage. ⚠ **Order matters when
rolling this back**: `sprint board --reset` needs `owner`/`number`/field names out of
`config.sprint.board`, so clearing that config first leaves every value on the board with no
Guild path left to reach it. `--reset`, then null the config.
*Mechanically*: one commit per evolve run; `permissions.ask` on the destructive git family.

**INV4 — additive, never clobbers local evolution.**
`init` and `update` merge; they do not overwrite. Locally-grown artifacts — specialized
agents, ⑥ knowledge, `docs/standards/*`, the overlay, the evolution ledger,
`gates/rules/boundaries.md`, `gates/dismissed.md` — are LOCAL-owned and never refreshed from
central. `CLAUDE.md` merges by marker, `settings.json` by key union, `.gitignore` by
appended negation, an existing `pre-commit` hook by chaining to `pre-commit.local`.

**INV5 — nothing leaves the machine un-sanitized.**
`/gld contribute` is the only outbound path. It runs a deterministic secret scan, then
generalizes away repo/owner names, paths, evidence lines and run numbers, dedups against the
central repo, and shows the human the final text before sending. Verify-gate evidence posted
to GitHub is scrubbed the same way (`_handoff.md` Section E).

**INV6 — draft → confirm → enforce.**
An auto-generated rule starts `status: draft` in its rule file's **frontmatter** and only
WARNS. It begins blocking when a human changes that to `status: confirmed`. This is why the
gate parses the frontmatter and not the document body: prose that merely mentions the string
`status: confirmed` must not arm a rule.
*Exception, deliberate*: the secret and verification gates are universal and non-hallucinated
— not inferred from this repo — so `init` installs them pre-confirmed, and they are hardcoded
in `gate_precommit.py` rather than parsed from a rule file. Only `rules/boundaries.md` is
data-driven; `rules/secrets.md` and `rules/verification.md` are the human-readable
*declaration* of what the gate enforces, not inputs it reads.

---

## Honest scope of the enforcement layer

Claiming more than the layer delivers is its own failure mode — it makes a real gap invisible.
The commit gate constrains commits made through git **in this working copy**:

- It **does** catch a compound `create-and-commit` in one call, because the authoritative
  layer is a `.git/hooks/pre-commit` that git runs with the index final.
- It **does not** survive `git commit --no-verify`, which skips every git hook.
- It **does not** travel with a clone — `.git/hooks/` is untracked, so a fresh clone needs
  `/gld update` to reinstall it — and it never fires if the repo sets `core.hooksPath`.
- It **does not** inspect history that is already written, or anything pushed elsewhere.
- Its off-switch and control files are guarded by an `ask`, not a block (`--guard-config`):
  turning the gate off is a legitimate action that should be a human's, on the record.

It raises the cost of a mistake. It is not a boundary against a determined bypass, and no
Guild output should describe it as one.
