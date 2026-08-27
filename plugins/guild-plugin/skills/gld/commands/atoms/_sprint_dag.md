# SPRINT DAG & MEMBERSHIP (shared contract)

**Not a stage.** The authoritative contract for (1) what a sprint's membership is and where it
is recorded, (2) where the dependency graph's edges live, (3) how `sprint_dag.py` is called,
and (4) how a PR base is decided at run time. Read the section the calling file points to.

> **`sprint_dag.py` is the canonical definition of the calculations.** This file states the
> contract and the reasoning; the script states the behaviour, and its
> `tests/sprint_dag_test.sh` states what is guaranteed. If this file and the script ever
> disagree, **the script wins and this file is the bug** — the calculations were pushed into
> code precisely so they could be tested rather than re-derived per run.
>
> **Bash**: simple calls only (`<<SKILL_DIR>>/commands/atoms/_bash_rules.md`) — with the
> generated-script carve-out noted in Section F. State/labels: `_handoff.md`.

---

## Section A — Membership: where a sprint's issue set is recorded

A sprint is **one GitHub Issue** carrying the `guild:sprint` label — the *tracking Issue*.
Membership is recorded twice, on purpose:

| | What | Who writes it |
|---|---|---|
| **Canonical** | the member table inside `<!-- guild:sprint:plan -->` in the tracking Issue body | `sprint plan` (once, then immutable) |
| **Back-reference** | a `Sprint: #<tracker>` line in each member Issue's body | `sprint plan --create` |

The back-reference exists so a member can be found *from the member side* (the same idiom as
`Parent Issue: #<parent>` — `_handoff.md` Section I):

```bash
gh issue list --state all --limit 200 --json number,title,body,labels --jq '[.[] | select((.body // "") | test("Sprint: #<tracker>([^0-9]|$)"))] | sort_by(.number)'
```

⚠ **The back-reference does NOT cover sub-issues discovered mid-run.** A child created by
`design.md`/`plan.md` gets `Parent Issue: #<parent>` and nothing else — no `Sprint:` line, and
no step in any flow adds one. So a crash cannot re-derive the discovered set from GitHub; the
`run` supervisor records it in the checkpoint marker instead (`_sprint_dag.md` Section F ·
sprint design §8.5).

⚠ `--limit 200` with a client-side body filter silently misses members outside the newest 200
Issues. Above that scale use the server-side form (`--search '"Sprint: #<tracker>" in:body'`).

**Members never get a new `guild:*` label.** Labelling them would pollute the canonical stage
derivation again (`_handoff.md` Section A) and would need a cleanup rule when an Issue carries
over into the next sprint. A body line just gets appended, and the previous sprint's line is
**kept** — one Issue having passed through two sprints is accurate history.

⚠ **`gh issue edit` has no append.** It offers `--body` (full replace) and `--body-file`, so
adding the line is read → splice → full rewrite. The **truncation check is mandatory**, exactly
as for the cumulative auditor record (`_execute_spine.md` Step 4): if the read comes back as a preview, read the
persisted full-output file, and if that is unavailable do **not** write — a truncated rewrite
destroys the member Issue's body.

## Section B — Edges: the member table is canonical, `Depends on:` is only input

| Stage | Reads | Writes |
|---|---|---|
| `sprint plan` (candidate scan) | `Depends on: #<n>` in candidate Issue bodies (the idiom `plan.md` already writes) | — |
| `sprint plan` (after linearization) | — | the **`base 의존`** column of the member table |
| `sprint run` · `sprint daily` | the **`base 의존`** column | — |

**`run` never reads `Depends on:`.** If it did, it would see the original fan-in graph rather
than the linearized one, and reach a branch (two or more deps) that linearization exists to
make unreachable.

The member table also keeps an **`원래 의존`** column — the pre-linearization declaration. It is
for the human to read and is **never** an input to any calculation.

**Edges pointing outside the member set are dropped with a warning.** You cannot wait on an
Issue that is not in the sprint: if it is already finished, dropping is right; if it is
unfinished, `plan` should have included it.

## Section C — Calling `sprint_dag.py`

```
python3 <<SKILL_DIR>>/commands/atoms/sprint_dag.py --input <path> --mode <mode>
```

**File-based, not stdin.** `_bash_rules.md` forbids pipes and redirection in a Bash *tool*
call, and its sanctioned python exception is the flag form (both existing precedents,
`scan_transcript.py` and `capture_signal.py`, are argparse-only). Section F says how each kind
of caller produces the file.

**Input** (per-mode keys only; omit what a mode does not need):

```json
{
  "members":        [{"number": 101, "deps": [], "base_deps": [], "split": false}],
  "prs":            [{"issue": 101, "branch": "feature/#101-x", "state": "MERGED|OPEN|CLOSED"}],
  "branches":       ["feature/#101-x"],
  "terminal":       {"101": "done|needs-human|failed|children"},
  "default_branch": "develop",
  "max_depth":      3,
  "text":           "<the tracking Issue body — mode=hash only>"
}
```

- `terminal` keys are JSON object keys and therefore **strings**; `members[].number` is an
  integer. The script normalizes.
- **`split`** — this member finished via a design-time split. Such a parent reaches
  `guild:done` with **no branch and no PR of its own** (its children carry those), so the plain
  "no PR, no branch → blocked" rule would turn a *completed* Issue into a downstream blocker.
  The script cannot see the `<!-- guild:children:output -->` comment — **the caller sets this.**
- **`branches`** — local branch inventory (`git branch --format='%(refname:short)'`). Section D's
  "dep has no PR but has a branch" case cannot be computed without it. ⚠ **`blocked` needs it
  too**, not only `base`: without it a dep that is finished but has no PR record reads as
  `dep-no-branch` and a *completed* member is reported as the thing blocking its dependents.
- **`default_branch`** — accepted, **not read**. `DEFAULT` is a token and the caller adds the
  `origin/` prefix (Section D), so no mode needs the name. It was a required-and-ignored key.

⚠ **A required key that is ABSENT is an input error (64), not "no dependencies".** Passing the
pre-linearization file (which has `deps` but not yet `base_deps`) used to make `order` return
plain issue-number order, `depth` return 1 and `base` return `DEFAULT` for every member — all
with exit 0. A key that is *present and empty* is still legitimate and means what it says.

| Mode | Needs | stdout (one item per line) | exit |
|---|---|---|---|
| `linearize` | `members.deps` | `<issue> <base_dep\|->` | 0 · cycle **2** |
| `order` | `members.base_deps` | execution order; tie-break = **issue number ascending** | 0 · cycle **2** |
| `cycles` | `members.deps` | one witness path per cycle | 0=none · **3=found** |
| `depth` | `members.base_deps`; `max_depth` **optional** (omit = compute, do not judge) | `depth <n>` + `chain <n1,n2,…>` per over-limit chain | 0 · not linearized **2** · over cap **4** |
| `base` | `members.base_deps`, `members.split`, `prs`, `branches` | `<issue> <branch>` \| `<issue> DEFAULT` \| `<issue> BLOCKED:<reason>` | 0 · not linearized **2** |
| `blocked` | `members.base_deps`, `members.split`, `terminal`, `prs`, **`branches`** | blocked issues + reason (transitive) | 0 · not linearized **2** · `base_deps` cycle **2** |
| `hash` | `text` | first 12 chars of the sha256 (sprint design §4.6) | 0 |
| **all modes** | — | warnings go to **stderr** | usage/input error **64** |

⚠ **Exit codes are distinct per meaning, and the caller MUST absorb them.** `2` used to mean
"cycle", "unresolvable" and "bad JSON" at once — then an `--input` typo read back as a cycle
and the caller reported one that did not exist. And because a generated supervisor runs under
`set -e` + `pipefail`, an unguarded command substitution in an assignment **kills the whole
run** on a meaningful non-zero. Every call carries `|| true` and branches on the *value*.

⚠ `depth`'s expectation for a 4-node diamond is depth 4, which exceeds the default cap of 3 —
a caller that wants "compute, don't judge" omits `max_depth`.

## Section D — Base decision (run time, not plan time)

```
Issue X, base_dep = D (0 or 1 after linearization):
  D has 2+ PRs in its most-final state, with DIFFERENT heads
                              → BLOCKED:dep-pr-ambiguous
  D absent                    → DEFAULT
  D's PR = MERGED             → DEFAULT                    (no stack needed)
  D's PR = OPEN               → D's branch                 (one stack level)
                              → BLOCKED:dep-pr-no-branch   (PR recorded without a head branch)
  D's PR = CLOSED             → BLOCKED:dep-pr-closed
  D has no PR, branch exists  → that branch
  D has no PR, no branch      → BLOCKED:dep-no-branch
  D is a split-completed parent → DEFAULT                  (`split: true`)
```

`DEFAULT` is a token, not a ref. **The caller adds the `origin/` prefix** — the script never
does, so that responsibility lives in exactly one place (sprint design §8.4).

⚠ **"D has no PR, branch exists" is implemented by the `branches` inventory alone** — there is
deliberately no second lookup in the PR index for that case, because the PR index only ever
holds a branch for an issue it also holds a state for, so in the no-PR path it is always empty.
An earlier version checked it anyway: dead code that read as a more authoritative source than
it was.

**Issue → branch comes from PRs, reverse-indexed.** The supervisor never names a branch (that
is the spine's job — `_execute_spine.md` Step 0), so the mapping is read back:

```bash
gh pr list --state all --limit 200 --json number,headRefName,baseRefName,state,mergedAt,reviewDecision,closingIssuesReferences
```

`closingIssuesReferences` is the primary link (Step 5 puts `Closes #<N>` in the body). ⚠ It can
come back empty — **fall back to matching the issue number as a token in the head branch
name**, and when that matches more than one branch return `BLOCKED:dep-branch-ambiguous`
rather than guessing.

⚠ **One issue can carry several PRs**, and the state resolves `MERGED > OPEN > CLOSED`. The
**head branch must be replaced along with the state**, not merely filled in when absent: a
CLOSED first attempt seen earlier otherwise leaves its abandoned branch in place, and a later
OPEN PR recorded without a head returns that dead branch as the base — stacking this Issue's
work on something the human explicitly rejected instead of reporting `dep-pr-no-branch`.

⚠ **And two PRs in the SAME most-final state, with different heads, is ambiguity — not a
tie-break.** The earlier code took whichever `gh` returned first, so reversing the input flipped
the answer between the real branch and an abandoned one, with no warning (measured). That is the
one thing this file forbids everywhere else, so it returns `BLOCKED:dep-pr-ambiguous` and warns
on stderr naming both branches. The human closes one PR and re-runs.

⚠ **`blocked` reasons have a precedence.** When the dep is itself blocked, `upstream:#N` **wins
over** the node's own direct reason. Otherwise `#103` reports `dep-no-branch:#102` and the root
cause (`#101` is waiting for a human) hides behind a symptom — and letting the human see the
cause is the entire purpose of this mode. The script walks the base_dep chain in topological
order so an upstream verdict is final before a downstream one is formed.

## Section E — Linearization (why fan-in cannot reach the base decision)

Two branches cannot both be a base, so a node must have **at most one** `base_dep` with every
declared dep as an ancestor of it. `--mode linearize` achieves that by **adding edges to the
dependency graph and assigning once at the end** — it never revises an assignment.

Reassigning is the trap: overwriting a node's existing `base_dep` **drops that node's own
dependency** from the chain. Measured over every DAG, the reassigning form lost dependencies in
6% of 4-node, 19% of 5-node, 35% of 6-node and 50% of 7-node graphs — and most losses sat
*under* the depth cap, so nothing warned.

**`--mode linearize` post-verifies its own output** (every declared dep is an ancestor of the
node's `base_dep`) and exits non-zero if not. That check is not optional: per-shape
expectations pass while dependencies are silently lost, which is exactly how the earlier
algorithm's defect went unnoticed.

**The cost moves to stack depth**, which the sprint's depth cap bounds and `retro` measures.
Measured for 7 members: with ≤2 dependency edges the cap of 3 is **never** exceeded; with 4+
edges it usually is. The most common shape — one foundation plus N independents — is depth 2.

## Section F — Producing the input file (two kinds of caller)

**LLM caller** (`sprint plan`, `sprint daily`): assemble the JSON and write it with the **Write
tool**, then call the script as its own Bash call.

**Shell caller** (the `run` supervisor): assemble it **inside the generated `.sh`**, where
redirection and heredocs are allowed — `_bash_rules.md:85` puts a generated script's own
contents outside this file's rules, and that carve-out is what makes the plumbing possible at
all. Sources, one file each, then one python pass to merge:

```
gh pr list … > prs.json          gh issue list --json number,labels > labels.json
git -C <sup> branch --format=… > branches.txt        members.json  (written once at run start)
```

⚠ **Never put a python heredoc inside `$( … )`.** bash mis-parses parentheses and quotes in a
heredoc nested in a command substitution. Write the helper to a temp file, then call it.

⚠ **Never end a heredoc opener line with `|| { … }`.** The closing brace lands on the next
line, which is the heredoc's **first body line**, leaving the group open forever — `bash -n`
then reports `unexpected end of file` at the end of the file, hundreds of lines from the cause.
Use a form that completes on that line (`|| RC=$?`) and judge after the terminator.

---

## Hard rules

- **The script is canonical for the calculations; this file is canonical for the contract.**
  On disagreement the script wins.
- **The member table is the only edge source at run time.** `Depends on:` is plan-time input.
- **Never guess a base.** Ambiguity returns `BLOCKED:<reason>`; the caller records it as
  *blocked*, which is not a failure.
- **Never reassign a `base_dep`.** Add edges, assign once, post-verify.
- **Absorb the exit code, branch on the value.** A meaningful non-zero must never kill a run.
- **A missing required key is an error, never a default.** Silence there is a wrong answer.
- **`origin/` is added by the caller**, never by the script.
- **Members carry no new `guild:*` label** — membership is derived (Section A).
- All Bash per `_bash_rules.md`, except inside a generated supervisor script (Section F).
