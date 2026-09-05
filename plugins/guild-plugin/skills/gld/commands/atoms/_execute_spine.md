# EXECUTE SPINE (shared stage skeleton — implement / debug / refactor)

**Not a stage.** The **execute** stage's common Steps 0–6, shared by its three variants: `implement.md` (`type:feature`), `debug.md` (`type:bug`), `refactor.md` (`type:refactor`). Read by whichever variant `dev.md` Phase 2 selected (or by a direct `/gld implement|debug|refactor <issue>`). The spine is identical across the three — only the *developer's task shape* and a few checks differ, so each variant file supplies the **slots** in Section A and this file runs everything else. A variant stays individually runnable: read the variant file (its header, its slot values, its own hard rules), then execute the steps below substituting those values.

> **Bash**: `_bash_rules.md` — one simple call each, no `&&`, `|`, `;`, `$(...)`, or redirection. State/handoff: `_handoff.md`.
> **Output language**: all human-readable output in `config.language` (`_handoff.md` Section K); **every** sub-agent prompt below ends with "Write output in `config.language`" — never drop it from a spawn.

`<N>` = the Issue number (the variant file receives it as `$1`). Substitute the **literal** Issue number for `<N>` — and the literal value for every other `<…>` — before the Bash call: `_bash_rules.md` forbids passing `<N>`/`$1` through unresolved, and `capture_signal.py` accepts a non-numeric `--issue` silently rather than erroring, so an unresolved `$1` would land in the ground-truth log as `"issue": "$1"` and quietly poison the record evolve reads.

**Step numbering is deliberately unchanged** from when these steps lived inline in the three variant files: when another file cites "`implement.md`/`debug.md`/`refactor.md` Step N" (`_stagnation.md` Section C, `_model_tiering.md` Section A, `_signals.md` Sections A/C, `_handoff.md` Sections A/D/E, `review.md`, `batch.md`), it means Step N **below**, as run by that variant.

---

## Section A — Slots the variant supplies

| Slot | What the variant states | Consumed at |
|---|---|---|
| **DESIGN INPUT** | which design artifact(s) Step 0 loads, and the exact `NEEDS_CONTEXT:` line when they're missing | Step 0 |
| **BRANCH + RESUME PROBE** | the branch prefix (`feature/` · `fix/` · `refactor/`), and what the one resume test-run probes on an existing branch | Step 0 |
| **DEVELOPER TASK SHAPE** | the spawn `description`, the ordered task body the developer follows, and the extras its `>>> RESULT <<<` line must carry | Step 1 |
| **EVIDENCE RULE** | what Step 2 requires of the raw evidence *beyond* the base cross-check (and therefore what "green" means at Step 4) | Steps 2, 4 |
| **CONFORMANCE CHECKS** | what the tech-lead is asked to check (and therefore what a tech-lead `BLOCKED` means at Step 4) | Steps 3, 4 |
| **SIGNAL AREA** | the `--area` phrasing (and the likely `--role` set) for Step 4's ground-truth capture | Step 4 |
| **PR SUMMARY** | what the PR body must name beyond `Closes #<N>` | Step 5 |

Every slot is mandatory — a variant that leaves one unstated is not runnable. Anything **not** in this table is spine-common and must not be re-stated (or silently altered) per variant.

---

## Step 0 — Preflight

As the leader, follow `_preflight.md` **Heavy tier** (per its Section A table: items **1 + 2 + 3 + 4 + 5 + 6 + 8** — not just 1–5; item 5 is the target-dir survey, items 6/8 are the ⑥ knowledge-slice retrieval and ④ working-memory read, both needed to honestly populate the Section C self-review trace). If `.claude/guild/config.json` is absent → `FAIL: Guild not initialized (run /gld init)` — the same hard check `analyze.md`/`design.md`/`test.md`/`qa.md` make at their own Step 0, so every spine stage behaves identically on an uninitialized repo regardless of which one the human invoked directly. Load the design output (`<!-- guild:design:output -->`) plus the variant's **DESIGN INPUT**; if it is missing → return that slot's `NEEDS_CONTEXT:` line.

Validate `<N>` is an Issue. **Read current labels first** (its own Bash call):

```bash
gh issue view <N> --json labels --jq '[.labels[].name] | map(select(startswith("guild:")))'
```

**Split-parent guard** (right here, before any other work): if that read contains `guild:children`, refuse — a parent at `guild:children` is in an *orchestration* state, not a stage (`_handoff.md` Section A: a parent never carries both `guild:children` and a stage label at once), so Step 6's transition would destroy the link `dev.md` Phase 2b uses to drive the children:

```
>>> RESULT <<<
FAIL: #<N> is a split parent (guild:children) — its work is its children's, not its own. Run `/gld dev <N>` (or `/gld resume <N>`) to drive the children.
```

(`guild:child` is **not** this case — a child legitimately carries `guild:child` + its stage label and proceeds normally.)

Empty → add `guild:execute`. Non-empty → do not add on top (Step 6's transition removes whatever **stage** label was actually found here, not necessarily `guild:execute` — never `guild:child`, which is a permanent identity marker a child Issue also carries alongside its stage label and no stage ever removes; `_handoff.md` Section A).

**Detect run mode now** (its own Bash call) — `printenv GLD_UNATTENDED`; `1` → unattended (`_handoff.md` Section H), anything else → attended. Do this **first**, before anything below it: the auditor-violation guard immediately following, the `<base>` failure path, Step 3.5a (a failed auditor scan, a mutating auditor) and Step 4 (a disputed `BLOCKER`, a bounded-retry exit) all branch attended/unattended, and the earliest of those is a few lines down — well before Step 4's own detection call would have run. Hold the resolved mode for the whole stage.

**Auditor-violation guard** (right here, alongside the split-parent guard — after the mode detection above, whose value its escalation branches on, and before any branch or spawn work). A prior run may have left this branch deliberately mutated by a misbehaving external auditor (Step 3.5a leaves the tree untouched on purpose, because INV3 forbids an automated repair). Ask whether **this Issue** carries an unresolved note. Run it on **both** the fresh and the resume path — it is a Step 0 guard in its own right and is never skipped (its own Bash call — substitute the literal `<owner>/<repo>` and `<N>`):

```bash
gh api --paginate repos/<owner>/<repo>/issues/<N>/comments --jq '.[] | select(.body | contains("<!-- guild:auditor-violation -->")) | select((.body | split("\n") | map(gsub("^\\s+|\\s+$";"")) | map(select(. != "")) | last) != "<!-- guild:auditor-violation:resolved -->") | .id'
```

(`map(select(. != ""))` rather than the more natural `length > 0`: a bare ` > ` inside a Bash argument trips Claude Code's compound-shell heuristic — `_bash_rules.md` item 7 — and no allowlist entry suppresses that prompt, which would stop an attended run at Step 0's very first guard. The two are equivalent here.)

⚠ **Resolution is judged by POSITION, not by presence or by a count.** The note has to tell the human which literal string to append (Step 3.5a — a protocol they cannot follow is no protocol), so **every note already contains that string inside its own instructions**. A plain `contains(...) | not` would therefore be false for every note ever written: the guard would look implemented and never fire. Counting occurrences is no better — it silently hard-codes "the prose contains exactly one copy", and a leader that also shows the marker in a copy-pasteable block (the natural way to render it) writes two, disarming the guard at birth with no signal.

So the test is: **the last non-blank line of the comment, trimmed, is exactly the resolved marker.** That is stable no matter how many times the instructions mention it, and it is what the protocol asks the human to do — append it as the final line. A note whose last line is anything else (its closing marker, prose, the instructions themselves) is **unresolved**.

⚠ `--paginate` is required, not decorative: without it the call returns only the first 30 comments, and an Issue that re-entered execute from `test`/`qa` — plus its stage outputs and any human discussion — passes 30 easily. A truncated read here returns empty and the guard silently waves through a branch that still carries unreverted auditor changes.

Non-empty → this Issue's branch still carries unreviewed auditor changes: a violation note exists and nobody has appended the resolved marker to it. Do **not** proceed: Step 0's resume path would otherwise fold the auditor's commit into the partial-work summary and Step 1 would hand it to the developer as "already-correct committed work" to keep, while Step 6 strips `guild:needs-human` on the forward transition — shipping the contamination with no trace.

```
>>> RESULT <<<
NEEDS_HUMAN: #<N>'s branch still carries unreviewed auditor changes — revert them, then append the resolved marker to the auditor-violation note on this Issue
```

Unattended → `guild:needs-human` label **+ a `<!-- guild:needs-human -->` comment pointing at the unresolved violation note** (`_handoff.md` Section H requires the comment; `status.md` tells the human to look for it) — ⚠ reference that note by its **comment URL/id, never by quoting `<!-- guild:auditor-violation -->`**: this guard matches any comment containing that marker, so a quoting comment becomes a second "violation" that the human's protocol (which resolves the *note*) can never clear, locking the stage permanently + `OK PAUSE: needs-human — unresolved auditor violation` (do NOT transition). Empty result → proceed normally (the common case by far).

⚠ **Stated limit — this guard is per-Issue, and a shared checkout is wider than that.** `/gld batch` drives every Issue through **one working copy**, so a mutation left unreverted on Issue #10 is physically present while #11 runs, and #11's own labels and comments say nothing about it. **Nothing catches it at branch-creation time on any path** — (b) below explains why no path-keyed working-tree check can work here, and this step does not pretend to have one. What *does* happen is that the leftover ends up in the audit: Step 3.5a discounts only `docs/specs/…`, so a sibling's stranded file is handed to the auditor and reported. That is noise on an attended run and a non-dismissible pause on an unattended one — visible either way, which is the point. The mitigation is deliberately placed where a human can act rather than in cross-Issue label bookkeeping — a repo-wide `guild:*` annotation would have to be understood by every stage-derivation consumer in the plugin (`status`, `resume`, `rollback`, `monitoring`, and `_handoff.md`'s own two jq forms), and a single missed copy turns an annotation into a bogus "current stage". Instead, the violation note's protocol (Step 3.5a) tells the human to **revert before resuming anything else in that checkout**. Do not restate this guard as checkout-wide; it is not.

**Resolve `<base>` now** — the ref this Issue's work is diffed against and the branch Step 5's PR targets. It is used by the resume probe below and by Step 3.5a's audit. **Two steps, in this order**, each its own Bash call:

**(1) An injected base wins.** `/gld sprint` stacks a dependent Issue's work on the branch its dependency is still reviewing in, so it hands the base in rather than letting this stage guess it:

```bash
printenv GLD_SPRINT_BASE
```

Non-empty → validate it before use (all three, each its own call): it resolves as a ref (`git rev-parse --verify <v>`); it is either `origin/<default branch>` or matches this repo's branch-naming convention; and it is not the current HEAD. Any check failing → `FAIL: injected base <v> is not usable for #<N>` (unattended: add the `guild:needs-human` label + comment alongside). ⚠ This validation catches a typo or an accident, **not an adversary** — the caller already runs with `--dangerously-skip-permissions`, so describing it as a security boundary would overstate it.

**(2) Empty → the repo's default branch** (every invocation outside `/gld sprint` takes this path, unchanged):

```bash
gh repo view --json defaultBranchRef --jq .defaultBranchRef.name
```

Hold the returned value as the **literal** `<base>` for the rest of this stage (empty/error → `FAIL: could not resolve the base branch for #<N>` — and when unattended, add the `guild:needs-human` label + comment alongside the `FAIL` so `batch.md` records it as paused once rather than re-resuming into the same deterministic failure; do **not** guess `main` — a repo based on `develop` would give the auditor a diff of unrelated commits and produce a flood of false findings). Substitute that literal everywhere `<base>` appears below — `_bash_rules.md` item 9 forbids passing `<base>` through unresolved.

Set up the branch for this Issue, as the leader, **before** spawning the developer. Do the three sub-steps in this order — the checks gate the command, so running the command first defeats them.

**(a) Fresh or resume?** Determine it explicitly — do not let (c) discover it by failing, and do **not** test an exact branch name. The name is not reproducible across sessions: Section A fixes only the *prefix*, the slug is derived per-invocation, and the repo's own branch convention is evidence-scanned (`conventions.md` fills `branch_naming` from `scan_repo.md`), so it may not contain `#`, a slug, or a separator at all. An exact-name probe that missed would report "fresh", cut a second branch from `<base>`, orphan the first one's commits, and — because Step 5's duplicate-PR guard keys on the branch — open a second PR closing the same Issue.

Instead, list **every local branch** and pick by reading (its own Bash call each):

```bash
git branch --list --format='%(refname:short)'
```
```bash
git rev-parse --abbrev-ref HEAD
```

⚠ **No glob, not even on the variant's prefix.** Filtering by any name-shape reintroduces the same hole one level up: the prefix a *later* invocation would glob with comes from Section A, while the name an *earlier* one actually created came from the repo's scanned `branch_naming` convention, and the two can disagree (`feat/` vs `feature/`, `12-` vs `#12-`). A prefix glob that misses returns "no candidates", the run goes down the fresh path, and it cuts a second branch and opens a second PR — exactly what this sub-step exists to prevent. Reading the full list has no such name-shape failure mode. ⚠ It has a different one to guard: Guild creates a branch per Issue and no step deletes them, so a long-lived repo accumulates them and the listing can be **truncated to a preview** — in which case the tail is invisible, the probe reports "no candidates", and the run cuts a duplicate branch and opens a duplicate PR. If the output came back truncated, read the persisted full-output file the tool result names before deciding; if neither is available, do **not** conclude "fresh" — `NEEDS_HUMAN: could not read the branch list for #<N>` (attended) / `guild:needs-human` label + a `<!-- guild:needs-human -->` comment stating that the branch list could not be read + `OK PAUSE: needs-human — branch list unreadable` (unattended — `_handoff.md` Section H requires the comment).

⚠ **Quote the format string exactly as shown.** `%(refname:short)` unquoted is a bash subshell and fails with a syntax error (`_bash_rules.md` FORBIDDEN item 3 names `(...)`). The format is also what makes the output usable at all: the default `git branch` listing is decorated (`  name`, `* name`, `+ name`), and a decorated line fed to `git switch` fails.

From that list, take as **candidates** the branches whose name refers to *this* Issue's number as a whole token — for `<N>` = 12, `feature/#12-login`, `feature/12-login` and `feat/ISSUE-12` all qualify; `feature/#123-x` and `release/2012-01` do not. Judging that by reading is the whole point: no glob expresses "this number as a token" across the naming conventions a repo may have, which is why the listing above is deliberately unfiltered.

⚠ **A name match alone is not enough — confirm before resuming on it.** Dropping the prefix filter means a branch that merely *contains* the number as a token can match without being this Issue's work at all: for `<N>` = 12, `release/1.12`, `support/1.12.x` and `v1.12` all do. Resuming onto one of those would hand its unrelated commits to the developer as "already-correct committed work", and Step 5 would then push it and open a PR closing #<N> from a release line. So before treating any candidate as this Issue's branch, check what is actually on it (its own Bash call per candidate):

```bash
git log <base>..<the candidate> --oneline
```

**Reject, do not require** — and an empty log alone is never the reason. The interruption this sub-step exists to survive stopped *mid-developer*, and the developer only commits at the end of its task, so the legitimate resume branch routinely has **zero** commits with the work uncommitted in the tree. Requiring commits would drop exactly that branch and send a resumable run down the fresh path.

But an empty log does not identify it either: a release line or tag branch cut from an **older** `<base>` is also empty against it. And git topology cannot separate the two — a branch cut at `<base>`'s tip becomes "behind `<base>`" the moment anyone advances `<base>`, which this file notes is routine ("a human pulling `main` between sessions"), so a tip comparison would drop the very branch it is meant to keep.

What *does* separate them is not in the history at all: **an interrupted run leaves its branch checked out.** That is the shape this sub-step exists for — a rate-limit or crash mid-developer ends the session on that branch, and `test`/`qa` loop-backs re-enter with it still current. So for the ambiguous case, use the second reading (a) already took:

Drop the candidate when any of these holds:

- it **is** `<base>`;
- its log against `<base>` is **empty and it is not the current branch** — nothing identifies it as this Issue's work in progress, while a release/tag line looks exactly like this;
- its log is **non-empty and the commits are plainly unrelated** to this Issue (another feature, a release history).

Keep it otherwise — in particular, **empty log on the current branch is the just-cut, interrupted branch**: keep it, whether or not `<base>` has moved since.

⚠ **One more drop, for the direction that is unsafe.** "Current and empty" is also what a `release/1.12` or `v1.12` cut moments ago and left checked out looks like — and that one, kept, is worse than any false drop: the developer's work lands on a release line and Step 5 opens a PR closing this Issue from it. So on the **empty-log path only**, also drop a candidate whose name reads as a release, version or maintenance line (`release/…`, `support/…`, `hotfix/…`, a bare `v1.2`-style tag name) rather than as work on an Issue. That test is by name because there is nothing else to go on — an empty branch has no history to judge — and it is safe in a way the earlier prefix filter was not: it only ever *removes* candidates, so a repo whose Issue branches happen to be named unusually falls back to the fresh path rather than onto a release line.

⚠ **When the judgment is genuinely unclear, DROP.** That applies to both judgment clauses — "plainly unrelated" commits, and "reads as a release line". A wrong drop costs a duplicate branch, visible and fixable; a wrong keep commits this Issue's work onto someone else's branch and opens a PR from it, which is neither.

⚠ **Stated limit.** A branch this Issue started, left with nothing committed, and then *switched away from* is dropped, and the run takes the fresh path. That case is narrow (something else had to move HEAD after the interruption). What happens next depends on whether the repo's branch name is reproducible: with a per-invocation slug the fresh path simply cuts a new branch beside the empty one — untidy, not unsafe. **With a fully reproducible convention** (`support-<N>`, `hotfix-<N>` — which is also the shape most likely to trip the name test above) it instead collides: `git switch -c` fails with "a branch named … already exists", (c)'s error handling catches it, and the Issue **pauses** rather than resuming. That is a worse outcome than a duplicate branch, and worth knowing about — but still the right side of the trade, because the alternative is the developer's work landing on a release line and a PR opened from it. Do not "fix" it by keeping empty non-current candidates: that is precisely how `v1.12` gets committed to.

If dropping leaves none, that is the fresh path — correctly, because no branch of this Issue's work exists.

⚠ **`<base>` must resolve locally for this command.** It is the first use of the bare `<base>` in the stage, and a shallow or `--single-branch` clone may not have it: if `git log` errors with an unknown revision, run **the recovery (c) describes for the shape `<base>` actually has** — the plain `git fetch origin <base>:<base>` refspec is correct only when `<base>` is a local branch name, and is *wrong* for both injected shapes (see (c)'s ⚠ on injected bases) — and retry. Do **not** read that error as "empty" — that would drop every candidate and send a resumable run down the fresh path. Then decide — **the current branch never decides on its own**:

- **Exactly one candidate** → **resume** on it. Bind that exact string as the literal `<branch>` for the whole stage (the resume probe below, and Step 5's push, its `gh pr list --head <branch>` duplicate-PR guard and its failure messages all consume it). Do not re-derive it anywhere.
- **No candidates** → **fresh**. This is the correct answer even though `git rev-parse --abbrev-ref HEAD` printed something: it always does — the current branch name, or the literal `HEAD` when detached — so a rule keyed on *that* being non-empty would make every run a "resume", onto `main` on a plain `/gld dev`, onto the previous Issue's branch under `/gld batch` (which (c) warns about), or onto a branch literally named `HEAD`.
- **More than one candidate** → do not guess: two branches for one Issue is exactly what a re-derived slug produces, and picking one orphans the other's commits. If the **current** branch is among them, resume on that one — it is where the work actually is, the normal `test`/`qa` loop-back shape. Otherwise `NEEDS_HUMAN: #<N> has more than one branch (<the names>) — tell me which to continue` (attended) / `guild:needs-human` label + comment + `OK PAUSE: needs-human — ambiguous branch for #<N>` (unattended).

**(b) No working-tree precondition — and that is deliberate.** An earlier draft refused to create the branch when `git status --porcelain` showed anything "foreign", to stop a prior Issue's leftovers being attributed to this one under `/gld batch`'s shared checkout. It is **removed**, because the distinction it rests on is not decidable from a path: the normal flow arrives here dirty (design leaves `docs/specs/<N>/` uncommitted for this stage's developer to commit; `/gld init` writes `.claude/`, `docs/standards/`, `CLAUDE.md`, the root `.gitignore`, the hook-manager config and several linter configs and commits none of it; 3.5b's tech-writer leaves doc updates untracked), so an allow-list has to cover all of that or it halts healthy runs — yet several of those same paths (`setup.cfg`, `.eslintrc*`, `.pre-commit-config.yaml`, the root `.gitignore`) are **also ordinary repo source** that the repo itself edits, so allow-listing them by name hands back the contamination the check existed to catch. There is no path-keyed rule that gets both halves right, so this step does not pretend to have one. The cross-Issue hazard is a property of `batch.md`'s single shared working copy, not of this change, and it is handled where a human can act: Step 3.5a's read-only-violation note records the exact paths a misbehaving auditor left behind and tells the human to revert them before running anything else in that checkout, and Step 0's guard refuses to re-enter *this* Issue while its note is unresolved. A stated, partial mitigation — not a claim of coverage.

**(c) Create or switch.** **On the resume path there is nothing to derive** — switch to the exact `<branch>` (a) bound and go straight to the partial-work summary below. ⚠ **If that switch fails, do not carry on**: the two shapes to expect are a branch already checked out in another worktree (`fatal: '<branch>' is already checked out at …`) and uncommitted changes that would be overwritten — (b) above deliberately allows a dirty tree, so the second is a routine `batch.md` shape rather than a bug. Neither is recoverable here: `NEEDS_HUMAN: cannot switch to #<N>'s branch <branch> — <the git error>` (attended) / `guild:needs-human` label + comment + `OK PAUSE: needs-human — branch switch blocked` (unattended). **On the fresh path only**, build the name from the variant's **BRANCH + RESUME PROBE** prefix and the repo's convention from conventions.md (e.g. `feature/#<N>-<slug>` for implement), then bind *that* as `<branch>` for the rest of the stage.

*Fresh path* — cut it from `<base>` **explicitly**, never from whatever HEAD happens to be checked out (its own Bash call; literal branch names substituted):

```bash
git switch --no-track -c <branch> <base>
```

⚠ **The flag goes BEFORE `-c`, and that is not cosmetic.** `-c` takes the new branch name as
its argument, so `git switch -c --no-track <branch> <base>` makes git read `--no-track` **as the
branch name**, leaves `<branch>` and `<base>` as two positional refs, and dies with
`fatal: only one reference expected` (exit 128, no branch created — measured on git 2.50.1).
Because that error string matches neither of (c)'s expected shapes, the Issue then **pauses**
instead of failing loudly. Any of `--no-track -c <branch> <base>`, `-c <branch> --no-track <base>`
or `-c <branch> <base> --no-track` works; the one broken arrangement is the flag directly after
`-c`. Do not "fix" a failure here by dropping `--no-track` — see why it is required next.

⚠ **`--no-track` is not optional.** When `<base>` is a **remote-tracking ref** (the injected form, step (1) above), `git switch -c` would set the new branch's upstream to it — and then a bare `git push` in this step's own "push the branch" below is one `push.default=upstream` away from **pushing this Issue's commits straight onto the base branch, with no PR** (measured: git even prints `git push origin HEAD:<base>` as its suggested fix). That would breach INV1's "nothing merges unattended". When `<base>` is a local branch — every non-sprint invocation — no upstream is set either way, so the flag is a **no-op** and costs nothing.

Use `switch --no-track -c` (or `checkout --no-track -b <branch> <base>` — carry the flag over,
it is required for the same reason), **never `checkout -B`** — `-B` resets an existing branch onto `<base>` and would destroy committed partial work.

Why explicit: `batch.md` has no branch isolation, so the previous Issue's branch is routinely still checked out when the next one starts. Branching off it would make `git merge-base <base> HEAD` (Step 3.5a) return *that* Issue's divergence point, handing the auditor the previous Issue's commits to review — `BLOCKER`s on work this Issue never touched, which no redo can clear and which unattended cannot be dismissed.

⚠ **`<base>` must resolve as a LOCAL ref, and Step 0's earlier check did not prove that** — `gh repo view` proved it exists on the *remote*, which a shallow or `--single-branch` clone may never have fetched. If this call fails because `<base>` is unknown locally, create the local ref in one additive fetch (no reset, no rewrite — its own Bash call). The **refspec form is mandatory**: a bare `git fetch origin <base>` updates only `FETCH_HEAD` and, in a `--single-branch` clone (which `--depth 1` implies), does not even create `origin/<base>`, because `remote.origin.fetch` is narrowed to the one cloned branch. Fetch into a local branch name instead, so every later bare-`<base>` command in this stage keeps working:

```bash
git fetch origin <base>:<base>
```

Then retry `git switch --no-track -c <branch> <base>`. Still failing **for that reason** → `FAIL: base branch <base> is not available locally for #<N> — fetch it and re-run` (attended) / same `FAIL` plus the `guild:needs-human` label + comment when unattended.

⚠ **The refspec form above assumes `<base>` is a local branch name — with an injected base it is not, and the command as written fails.** Two cases, and neither is the plain form:
- `<base>` is `origin/<default>` → the correct recovery is `git fetch origin <default>:refs/remotes/origin/<default>`. `git fetch origin origin/<default>:origin/<default>` fails with `couldn't find remote ref origin/<default>`. In practice this recovery is unreachable under `/gld sprint`: the supervisor refreshes that ref before every Issue.
- `<base>` is a **dependency's branch** → do **not** fetch. That branch was created by a previous Issue in this same repo, so its absence is a state inconsistency, not a missing fetch: `FAIL: base branch <base> is not available locally for #<N>`. The supervisor should have caught it as a blocked dependency first.

⚠ **Read the error before assuming that is the reason.** This step has no working-tree precondition ((b) explains why), so a dirty tree is allowed and routine — so `git switch -c` can also refuse with "Your local changes to the following files would be overwritten by checkout" when a tracked file differs between the currently checked-out branch (under `batch.md`, the previous Issue's) and `<base>`. Reporting *that* as "base branch not available" sends the human to fetch a branch they already have. Surface the real cause instead: `NEEDS_HUMAN: cannot create #<N>'s branch from <base> — <the git error>` (attended) / `guild:needs-human` label + a `<!-- guild:needs-human -->` comment carrying the git error + `OK PAUSE: needs-human — branch creation blocked` (unattended — `_handoff.md` Section H requires the comment). Do not proceed with an unresolved base: the resume probe, Step 3.5a's merge base, and the audit itself all use the bare `<base>` name.

*Resume path* — switch to the existing branch and build a concise **partial-work summary** from two readings: `git log <base>..HEAD --oneline` (what's committed) **plus one run of the test command**, read per the variant's RESUME PROBE (where the work left off). Both are required — the commit log alone tells the developer what exists but not where it stopped, and RESUME PROBE is a mandatory Section A slot precisely because this is its only consumption point.

⚠ The `git log` reading uses the bare `<base>` too, so if it errors because `<base>` is unknown locally, run **the same shape-dependent recovery the fresh path describes above** and retry — the resume path is not exempt just because it skipped the branch creation that would normally have surfaced the problem. ⚠ Under `/gld sprint` the resume path is the **common** one and `<base>` is **always** an injected value, so the plain `git fetch origin <base>:<base>` form would fail here every time: for `origin/<default>` fetch `<default>:refs/remotes/origin/<default>`, and for a dependency branch do **not** fetch at all — report it, as (c) says. This summary goes into the developer prompt (Step 1) so it **continues from the partial state, not from scratch**. ("중단 내성" — mid-execute resume.)

## Step 1 — Spawn developer

Spawn the developer sub-agent:

- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: the variant's **DEVELOPER TASK SHAPE** description (e.g. `developer implement #<N>`)
- `prompt`:
  > Adopt the persona in `.claude/agents/developer.md`. Work Issue #<N> on the current branch. **Resume**: if Step 0 supplied a partial-work summary here — `<partial-work summary from Step 0, or "none — fresh branch">` — a prior run was interrupted mid-execute, so **CONTINUE from it**: keep the already-correct committed work, pick up where it stopped, complete the rest; redo only what is wrong. Do NOT rewrite correct existing work from scratch.
  > **‹ the variant's DEVELOPER TASK SHAPE body goes here verbatim — its inputs, its ordered steps, its constraints ›**
  > Run the project's test command and **capture the raw runner output** as verify evidence — do NOT claim green/fixed/done without it (`_handoff.md` Section E). slopcheck: verify every import/dependency exists (no hallucinated packages). Commit with the repo's convention.
  > <!-- guild:result-contract -->
  > Return EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. Anything before the sentinel is ignored. Status is one of `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <one-line>` / `NEEDS_CONTEXT: <one-line>` / `FAIL: <reason>`. **Artifacts are passed as files, not pasted** — write to the working tree or `docs/specs/<issue>/` and name the path in the RESULT line; never inline an artifact body into it.
  > <!-- /guild:result-contract -->
  > Include the raw test summary line, the branch name, **and the variant's stated RESULT extras**. Write output in `config.language`.

## Step 2 — Capture verify evidence

When the developer reports green, post the raw test-runner output to the Issue as evidence (temp-file pattern):

- Marker: `<!-- guild:test-evidence:step-1 -->` … `<!-- /guild:test-evidence:step-1 -->`. (Execute only — `test.md` writes its own raw evidence under `<!-- guild:test:output -->` instead; `_handoff.md` Section D marker table.)
- Body: the raw runner summary line(s) the developer captured.
- As the leader, cross-check the developer's self-report against this raw output — if they disagree, **the raw output wins**; treat as not-green and loop back (Step 4).
- Then apply the variant's **EVIDENCE RULE** — the extra thing this variant's evidence must show. Failing it is not-done: loop back the same way.

## Step 3 — Tech-lead conformance check

Spawn the tech-lead sub-agent to check the implementation against the design (separate eyes — anti-confirmation-bias):

- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `tech-lead conformance #<N>`
- `prompt`:
  > Adopt the persona in `.claude/agents/tech-lead.md`. Review the work on the current branch for Issue #<N>. **‹ the variant's CONFORMANCE CHECKS go here verbatim — what to review it against, and exactly what to check ›** You are reviewing the DEVELOPER's output, not your own.
  > Your one-line verdict is read by the leader's arbitration step, which decides whether the stage advances or loops back. Name the specific non-conformance — which file, which design decision it breaks — not a general impression.
  > Return one `>>> RESULT <<<` line: `DONE` (conformant), `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <non-conformance>` (requires an execute loop). Write output in `config.language`.

## Step 3.5 — External auditor (always) + conditional specialists / gate reviews (leader)

As the leader, run the **execute-stage independent review layer**. It has two halves: an **external auditor that always runs** (3.5a), and the **participation specialists / gate reviews** this change warrants (3.5b).

**Order matters: run 3.5a alone and to completion, then 3.5b.** Do **not** batch them into one parallel message. 3.5b legitimately contains roles that *write* files (tech-writer drafts docs and may update `architecture.md` in place), so running them concurrently would make the working-tree check below unattributable — any change seen afterwards could be the tech-writer's legitimate output or the auditor's forbidden one, with no way to tell them apart. 3.5a is a single short read-only scan; serialising it costs one round-trip and buys an unambiguous check. Within 3.5b, spawn the matched roles in parallel as before.

### 3.5a — External auditor (ALWAYS — not conditional)

A fresh, persona-less adversarial read of the developer's diff, **before the PR exists**. This is the same auditor `review.md` Step 2.5 runs after the PR — deliberately **duplicated, not relocated**. The two prompts must stay **calibrated identically** (same defect list, the same severity/axis core, and the same anti-rubber-stamp and anti-padding instructions — the stage-consequence line below the core is the one intended difference); if you change one, change the other, or the two stop being comparable and the outside reading below becomes meaningless. Two distinct jobs:

- The **in-spine copy (here)** catches `BLOCKER`/`MAJOR` early enough that Step 4's loop-back fixes them *before* `test` and `qa` run, so the fix is verified by the normal gates instead of landing behind them.
- The **`/gld review` copy** stays outside `dev` as the **independent reading** of whether `dev` is actually improving: a scan that runs only inside the thing it measures cannot measure it. Be precise about what that buys — the flow **computes no such metric**. Nothing tallies review findings across PRs, and `/gld batch` skips review entirely. It is a human judgment over the counts left on each PR by a `/gld review --comment` run (`review.md` Step 5). Keeping the copy outside is what makes that judgment *possible*; it does not make it automatic.

Running the same auditor twice is intended, not waste: on a clean run the second pass should find nothing.

**Cost, stated honestly.** The auditor is one extra `sonnet` sub-agent per execute *invocation*, plus one per loop-back within it (bounded by the stage's ~2-attempt cap). Execute can be **re-entered** from later stages — `test.md` Step 3 and `qa.md` Step 2 both loop back into a fresh execute run — and each re-entry runs 3.5a again and starts a fresh MAJOR budget. So the honest worst case for one Issue is roughly *(execute invocations) × (attempts each)* auditor spawns, not one; a typical clean Issue is exactly one. This is a real cost increase and is not hidden by any cap other than the ones already in the spine.

⚠ **Read-only here is only partly enforceable — do not overstate it.** Unlike `review.md` Step 2.5 — which scans a finished PR, after the stage's own edits are done and with a human present at the end of it — this auditor runs **mid-execute**, while the stage is still writing, so an auditor that "helpfully" fixes what it finds destroys the independence this step exists for and can silently weaken tests (INV2). Prefer a `subagent_type` that **removes the Edit/Write tools** (`Explore` in current Claude Code builds) over `general-purpose` — while noting that `Explore` is defined as a *search* agent that reads excerpts rather than whole files, so if it degrades finding quality on a real diff, `general-purpose` with the mandatory check below is the acceptable trade, not a shortcut. But be honest about the limit: **that agent type still has Bash**, so file mutation remains reachable (`sed -i`, a redirect, `git checkout`, even `git commit`). A restricted type raises the bar; it does not close the hole.

**Resolve the audit range first.** `<base>` from Step 0 is a *branch name*, and diffing against its **tip** is wrong: Guild never pulls, but a human pulling `main` between sessions is routine, and `test.md` Step 3 / `qa.md` Step 2 re-enter execute much later. Against the tip, every upstream commit merged since this branch was cut appears as a deletion the developer never made — the auditor is explicitly asked to hunt "blast radius beyond the reported scope", so it would return `BLOCKER`s for other people's merged work, and no redo could ever clear them. Diff against the **merge base** instead (its own Bash call):

```bash
git merge-base <base> HEAD
```

Hold the returned commit as the **literal** `<mb>` for the rest of this step (`_bash_rules.md` item 9 — and item 1: never inline it as `$(...)`, it is its own call). Errors → `FAIL: cannot resolve the merge base of #<N>'s branch and <base> — the execute-stage audit could not run` (attended) / same `FAIL` plus the `guild:needs-human` label + comment when unattended, so `batch.md` records it as paused once instead of re-resuming into the same deterministic failure. This also catches `<base>` not resolving as a **local** ref — Step 0's `gh repo view` proved it exists on the *remote*, which a shallow or single-branch clone may never have fetched.

**Then establish that there is something to audit** (this is the same `git diff --numstat --no-renames <mb>` and `git status --porcelain -uall` pair the mutation check below takes pre-spawn — take each once, in exactly that form, and use it for both purposes; taking the flagless variant here and the `--no-renames` one below would make a renamed file's before-set and after-set disagree by construction). It compares the **working tree** to the merge-base commit (a bare commit argument — **no `..` and no `...`**), so it covers committed *and* uncommitted tracked changes; `git status --porcelain` covers what `git diff` structurally cannot, namely untracked files. Both matter, because the developer's work is not reliably committed at this point (a blocked pre-commit hook can leave it in the tree; `batch.md` documents that state).

⚠ **Discount `docs/specs/…` from both readings before judging — for any Issue, EXCEPT where this Issue's own developer produced it** (the next ⚠ states that carve-out; read the two together, they are one rule). In the ordinary case the root has unambiguous provenance: Guild's design-stage roles write it, this Issue's copy is the *intent* the audit measures against rather than part of the change, and a sibling Issue's copy is someone else's work outright. `design.md` leaves it uncommitted by design, so it is present on essentially every run — judging emptiness without discounting it would make the check below dead code that can never fire.

⚠ **Never discount this Issue's OWN work under that path — committed or not.** The discount exists because Guild's *other* steps (and other Issues) strand files there, not because the path is uninteresting. An Issue whose deliverable genuinely is a spec change may have that work committed, or sitting uncommitted because a hook blocked the commit — the spine says elsewhere that this is routine, so committed-ness is the wrong test. Judge by whose work it is: this Issue's developer produced it → audit it; design/another Issue produced it → discount it. Getting this backwards makes a spec-deliverable Issue fail with "nothing to audit" on work that was actually done.

⚠ **Everything else in the tree is audited, including Guild's own uncommitted leftovers.** That is the deliberate consequence of Step 0 having no working-tree precondition (see (b) there for why one is not possible): an untracked `docs/adr/…`, a modified `lefthook.yml`, or a sibling Issue's stranded file may well not be this developer's, but no path-keyed rule separates Guild's writes from the repo's own, so the auditor sees them. The failure mode is a finding about something the developer did not write — noisy and visible, dismissible attended; unattended it is a `BLOCKER` that cannot be dismissed and ends at `OK PAUSE: needs-human` with the evidence attached. That is the trade this step accepts: a paused Issue over an unaudited change that ships. ⚠ Be honest about the cost under `/gld batch`, where there is no human mid-run and no Guild step commits those leftovers: the same non-dismissible finding can recur Issue after Issue, so one uncommitted `/gld init` harness can pause a whole batch rather than one Issue. Committing the harness once — which `/gld init` deliberately leaves to the human — removes the recurring cause; the note in the pause should say so. **When such a finding forces an unattended pause, name the suspected foreign path in the escalation** so the human sees in one line that it is about something this Issue did not write.

Call what is left after discounting the **audited remainder** — that is what the judgment here uses and what is named to the auditor. It is *not* a claim that every path in it is the developer's.

- **Audited remainder empty in BOTH readings** → the developer produced nothing to audit. Do **not** spawn and do **not** advance: this contradicts a developer `DONE` and is a real defect, not a ref problem — `FAIL: #<N>'s branch has no changes against <base> — nothing to audit` (same unattended handling as above). ⚠ **Judge on BOTH readings, never on the diff alone**: a change made entirely of new files is invisible to `git diff` and shows only as `??` entries.
- **Either non-empty** → proceed, and name the audited remainder's untracked paths to the auditor below so a new-file change is not silently outside the diff it is told to read.

Therefore a mutation check around the auditor is **mandatory on every path, not only the `general-purpose` fallback**. It has to be **content-sensitive and commit-insensitive**: an auditor that edited *and committed* leaves `git status --porcelain` looking exactly as before, while a pre-commit hook completing asynchronously moves `HEAD` and clears porcelain entries without anything having been edited. Comparing `HEAD` and porcelain alone cannot separate those two, and a `--stat` summary cannot either — an edit that replaces one line with another (weakening an assertion, say — the INV2 harm this exists to catch) leaves the line counts identical.

**Take these three readings immediately before spawning; take the first two again after the auditor returns** (each its own Bash call):

```bash
git diff --numstat --no-renames <mb>
```
```bash
git status --porcelain -uall
```
```bash
git rev-parse HEAD
```

⚠ **`--no-renames` is required.** With rename detection on (git's default since 2.9), `--numstat` collapses a rename into one entry printed as `old => new` — or `dir/{old => new}` — so a renamed file has no entry under either of its real paths. Two things break: the `??`-vanished-and-a-triple-appeared benign shape can never match (the new path has no triple of its own), and a renamed file's entry is not a usable pathspec. `--no-renames` splits it back into a deletion of the old path and an addition of the new, which is what a path-keyed comparison needs.

⚠ **`--numstat`, not `--stat` — this is not a style choice.** `git diff --stat` renders for humans: it pads the path column to the longest filename and **elides long paths to `.../tail/of/path`**, and it re-elides them whenever another entry changes the available width. Two consequences, both fatal to a path-keyed comparison: a deep path never appears as its real path, so it can never be matched against the full path `git status --porcelain -uall` prints; and one unrelated addition can make an untouched file's entry "vanish" and a differently-elided one "appear". `--numstat` prints `<added>\t<deleted>\t<full path>` with no padding, no elision, and no totals line. `-uall` is likewise required: plain `--porcelain` collapses an untracked directory to a single `?? docs/` line, hiding a file added inside one.

The `git rev-parse HEAD` reading is **not** part of the comparison — it is recorded once, for Step 4's audit-record block, whose carry-forward test diffs against it. There is exactly one such value per attempt (the pre-spawn one); the check never takes a second.

⚠ **Compare the RAW readings — never the discounted ones.** The `docs/specs/…` discounting above exists for the "is there anything to audit" judgment and for what is named to the auditor. Applying it here would make an auditor write under `docs/specs/<N>/` invisible to the tripwire — and that is the very directory the prompt hands it to read.

**Reduce each reading before comparing:**

- From `git diff --numstat --no-renames <mb>`, take the **set of `(path, added, deleted)` triples**.
- From `git status --porcelain -uall`, take **only the `??` (untracked) lines**. The tracked status lines (` M`, `A `, ` D`, `MM`) are *expected* to change: committing clears ` M`, staging turns it into `A `. Including them would make every mid-scan commit look like a mutation — the single most common benign event this check must see past.

Then compare the two reduced pairs:

- **Both sets unchanged** → nothing observable changed. `HEAD` may have moved and tracked status lines may have cleared; neither alters a reduced set, so a commit landing mid-scan is correctly invisible.
- **A `??` entry appeared** → a new untracked file, which the diff structurally cannot show. ⚠ **Attribute this one too, before calling it a mutation** — the same courtesy the tracked-content path gets. A read-only auditor legitimately *runs things*: the prompt asks it to judge "weakened or vacuous tests", which invites executing the suite or importing a module, and that leaves `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `coverage.xml` and the like behind in any repo whose `.gitignore` does not already cover them. Those are **build and cache artifacts, not source**: note them in the narration, do not treat them as a read-only violation, and do not let them discard a valid scan. A new path that is *source* — a file under the repo's own code or docs tree — is a mutation. When the path's nature is genuinely unclear, escalate as below, but word it as "the working tree gained <path> during the scan", never as a bare accusation.
- **A `??` entry vanished AND a `numstat` triple appeared for that same path** → that file was committed or staged. Benign — the shape of the developer's own commit completing mid-scan, which `batch.md` documents as routine.
- **A `??` entry vanished with NO `numstat` triple for that path** → deleted rather than committed → mutation.
- **Any other `numstat` difference** — a triple appeared with no matching `??` disappearance, a triple vanished, or a triple's counts changed → **something other than the developer changed tracked content**. See the attribution rule below before concluding.
- **The single known exception, in every direction**: differences confined to `.claude/guild/gates/findings.json`. `gate_precommit.py` rewrites it on every gate run — including the **blocking** path where no commit lands — and never stages it. Ignore it in both readings.

⚠ **Attribute before accusing — the auditor is not the only possible writer.** 3.5b has not been spawned yet, so no other Guild *role* is a candidate; but a repo's own **auto-fixing pre-commit hook** (prettier, black, `eslint --fix`, a formatter that re-stages) rewrites tracked content on commit, and `/gld init` registers Guild's gate into exactly that hook manager. A formatter's output persists, so the re-take below will not clear it. The reduced readings carry counts, not content, so they cannot answer this on their own — **read the actual difference before attributing** (its own Bash call, restricted to the differing paths):

```bash
git diff --no-renames <mb> -- <the paths whose triples differ>
```

If what it shows is a formatting pass over files the developer touched — reflow, quoting, import ordering, trailing commas — that is a hook, not a violation: proceed with the scan and say so in the narration. If it shows a semantic change, or touches a path the developer never did, it is not attributable to a formatter. Only when the change is **not** attributable that way is it a **failed scan**. Either way, word the escalation as "the working tree changed during the scan — the auditor or a repo hook", never as a bare accusation: a violation note that tells a human to revert their own formatter's legitimate output is worse than no note.

⚠ **State the limits honestly — this is a tripwire, not a proof.** Two auditor edits are invisible to it. **(1)** Rewriting a line that is *already part of the diff against `<mb>`* — code the developer just wrote — because `numstat` counts changed lines, not their content, so replacing one changed line with another leaves the counts identical. That is precisely where the INV2 harm lives: silently weakening an assertion the developer just added. **(2)** Editing the *content* of an untracked file, which `git diff` cannot see and `-uall` reports without content — and this step names untracked paths to the auditor as part of the change, so those files are in scope. Three further gaps, named so the list is not read as exhaustive at two: a bare `git add` leaves content untouched but seeds the index and reads as the benign commit/stage shape; any write under a **gitignored** path is invisible to both readings (`.claude/guild/memory/` is gitignored and holds `ground-truth.jsonl`, which the growth loop reads); and a **binary** file already in the diff shows `- - <path>` before and after, so replacing its contents entirely leaves the triple unchanged. The primary defence against all three is **not** this check but the **agent type**: use one without Edit/Write wherever the environment offers it. Where it does not, the residual risk is accepted and named here rather than papered over — never describe this check as guaranteeing the auditor edited nothing.

Where a difference is neither excused nor attributable, re-take the readings once in case a hook was mid-flight; if they still differ, it is a **failed scan**, not a fix.

⚠ **On a failed scan — do NOT attempt an automated repair.** Two tempting recoveries are both wrong:

- **`git reset --hard` is forbidden outright** — INV3 (`_invariants.md`: "No `reset --hard`, no force-push, no history rewrite — ever, by any command"). That prohibition is the whole reason; do not lean on the `ask` entry in `templates/settings.json.tmpl` as a second one, because it does **not** hold unattended: `batch.md` invokes each child with permission prompts bypassed, so the prompt never fires there and the command would simply run.
- **A blanket `git checkout -- .` is worse than the problem.** It destroys *any* uncommitted work, and the developer's work is not reliably committed by this point. It also removes neither untracked files nor anything already `git add`ed, so it would not even undo the mutation it was invoked for.

The correct handling: **(1)** discard the auditor's output entirely — do not act on findings from a scan that violated its own contract; **(2)** leave the tree exactly as it is; **(3)** escalate immediately — `NEEDS_HUMAN: execute-stage auditor modified the repo — <what changed, one line>` (attended) / `guild:needs-human` label + a `<!-- guild:needs-human -->` comment pointing at the violation note just written + `OK PAUSE: needs-human — auditor violated read-only` (unattended). Do **not** re-run the auditor and do **not** advance. ⚠ Reference the note by its **comment URL/id, never by quoting `<!-- guild:auditor-violation -->`**: Step 0's guard matches any comment containing that marker, so a quoting comment becomes a second "violation" the human's protocol can never clear.

⚠ **Writing the violation note is MANDATORY on both the attended and the unattended path** — write it *before* returning either line. Step 0's re-entry guard keys entirely off this comment existing, so an attended run that returns only `NEEDS_HUMAN` and is then abandoned would leave the guard inert and the mutation would be folded into the next resume's partial-work summary as legitimate committed work.

It uses its own marker pair, `<!-- guild:auditor-violation -->` … `<!-- /guild:auditor-violation -->`, and must carry two things:

1. **The evidence a human needs to undo it** — the before/after `git diff --numstat --no-renames <mb>` and `git status --porcelain -uall` readings (name the concrete paths that differ), and the pre-spawn `git rev-parse HEAD` value (there is only one — the check never takes a second). A bare "auditor misbehaved" note is not enough, because the branch is being left mutated on purpose.
2. **The resolution protocol, spelled out for the human in `config.language`** — **revert the listed changes before running any other Issue in this checkout** (`/gld batch` shares one working copy, so the mutation is physically present for everything that follows and only this note records it), then **edit THIS comment and add the literal string `<!-- guild:auditor-violation:resolved -->` as its LAST line — below the note's closing `<!-- /guild:auditor-violation -->`, with nothing after it**. That keeps the note a well-formed marker pair while still putting the resolved marker last, which is what the guard checks. Position is what counts: the marker appears above only as something to copy, and a copy left anywhere but the final line does not clear the guard. The human never reads this file, so a protocol stated only here is a protocol they cannot follow.

⚠ **Post a NEW comment for every violation — never PATCH an existing one.** This is the one Guild record that skips the duplicate-prevention search entirely (`_bash_rules.md` sanctioned exception 3): overwriting would destroy the earlier violation's readings, and pooling violations into one comment would let a single stale `:resolved` marker disarm the guard for every future violation on that Issue.

- `subagent_type`: an agent type without Edit/Write if available, else `general-purpose`; `model`: `sonnet`; `description`: `external auditor #<N>`
- `prompt`:
  > You are an **independent, adversarial** code reviewer with NO prior context — fresh eyes. **⚠ READ-ONLY: you MUST NOT edit, write, create, delete, fix, or commit ANY file — you only READ and report.** Do not "fix" the defects you find; report them. Read, in this order: **(1)** the diff for this branch — `git diff --no-renames <mb>`, a bare commit argument so it compares the **working tree** to the merge base and therefore includes uncommitted work (there is no PR yet); never `git diff` alone, `git diff HEAD`, or a `..`/`...` range, all of which would miss part or all of the change; **(2)** any untracked files the leader names here as part of the change — `<the audited remainder's untracked paths, or "none">`; **(3)** `docs/standards/`; **(4)** the Issue AC/design (`docs/specs/<N>/`, the `guild:analyze:output` / `guild:design:output` comments on Issue #<N>). ⚠ **Make sure you actually read the WHOLE diff.** A whole-branch `git diff` can exceed the output limit, in which case only a preview is shown and the full text is written to a file whose path the tool result gives — **read that file**. A scan of a truncated diff returns perfectly well-formed JSON, so the failure would look exactly like a clean review, on the largest and riskiest changes. If the full text is not available that way, fall back to reading it **file by file**: get the list with `git diff --numstat --no-renames <mb>`, then `git diff --no-renames <mb> -- <one path>` for each. `--no-renames` matters there: with rename detection on, `--numstat` prints `old => new` (or `dir/{old => new}`), which is **not** a usable pathspec — feeding it back gives empty output and exit 0, so a renamed file would be silently skipped. If a read still comes back incomplete, say so explicitly rather than reporting only on the part you saw. ⚠ **`docs/specs/…` is normally NOT the developer's output** — `docs/specs/<N>/` is the **intent you review against**, written upstream by the tech-lead and tester, and another Issue's spec directory is someone else's work entirely that you have not been given the AC to judge. Do not report findings against it as a defect in this change **unless the leader states otherwise right here**: `<'docs/specs/<N>/ IS this Issue's deliverable — review it as the change' or 'docs/specs/ is intent only'>`. That carve-out is deliberately narrow: it names one root whose author is never the developer. **Do not extend it to documentation generally** — `docs/adr/…`, `README*` and `docs/standards/architecture.md` are frequently the developer's own deliverable, and suppressing findings there would let an Issue whose entire AC is "add ADR-0012" pass with an empty audit that is indistinguishable from a genuinely clean one. Hunt for **real defects**: correctness bugs, security/exposure, missing error/null handling, **blast radius** beyond the reported scope, convention/standard violations, AC gaps, and **weakened or vacuous tests** (pass-but-verify-nothing — INV2 spirit). Be skeptical; do NOT rubber-stamp — but do NOT invent findings to fill a quota either: **returning `[]` is a correct and expected answer** for a clean diff, and a padded list costs a real loop-back. Write `finding`/`why` in **plain, jargon-free language** — spell out any acronym/pattern name on first use and state the concrete consequence, not just the violated rule.
  > <!-- guild:severity-core -->
  > Severity is not a mood, and it is not about how hard the fix is — it is the
  > consequence of shipping the defect as it stands.
  > BLOCKER = shipping it causes real harm. The harms are exactly these five:
  >           (1) a security or data exposure; (2) data loss or corruption;
  >           (3) loss of availability; (4) a correctness failure a user hits on
  >           the main path; (5) the change not delivering what the Issue asked
  >           for at all. Plus one rule-based case: weakening verification the way
  >           INV2 defines it — deleting a test file, net-removing assertions, or
  >           adding skip/focus directives — is always a BLOCKER, whatever its
  >           apparent consequence. A newly added but weak assertion is not that
  >           case; grade it by consequence like anything else.
  > MAJOR   = a real defect with a bounded consequence — e.g. an edge case or one branch
  >           of a requirement left unmet, a degraded behavior, or a broken rule
  >           that has teeth — where the change still delivers its purpose and none
  >           of the six BLOCKER cases applies.
  > MINOR   = everything else you would still report: a defect or rule violation
  >           with no consequence at all — not behavior, not exposure, not data,
  >           not availability, not the acceptance criteria — and none of the
  >           BLOCKER cases.
  > axis: spec      = it misses or contradicts the Issue's AC or the design intent
  >                   in docs/specs/<N>/.
  >       standards = everything else — it violates docs/standards/, a Guild gate
  >                   rule, or simply the quality this repo ships. If it is a real
  >                   defect and it is not a spec miss, it is standards.
  > When unsure between MAJOR and MINOR, choose MINOR. When unsure whether
  > something is a BLOCKER, report it as a BLOCKER and say in `why` exactly what
  > you are unsure about, so the reader can weigh it.
  > <!-- /guild:severity-core -->
  >
  > NOT a finding — do not report this shape:
  > "this function looks like it could be split into smaller pieces"
  > Why rejected: no concrete consequence and no rule identified. Padding the list
  > with this shape costs a real loop-back.
  >
  > A BLOCKER here stops the run: the diff goes back for a redo before the test
  > stage runs, it loops back for as many attempts as the stage's cap allows, and
  > unattended it cannot be dismissed. A MAJOR that blocks does so at most once
  > per execute invocation; after that it is recorded and ships.
  >
  > Return findings as JSON: `[{"severity":"BLOCKER|MAJOR|MINOR","axis":"standards|spec","file":"...","line":<n>,"finding":"<1 line, plain language>","why":"<1 line, concrete evidence>"}]` — no vague nits; every finding anchored to a concrete line + reason. Write output in `config.language`.

**One criterion decides it: did *this Issue's own work* touch `docs/specs/<N>/`?** Committed or uncommitted — a blocked hook routinely leaves the work in the tree, so committed-ness is the wrong test — and judged from the developer's output, not from how the AC was phrased. Without this line an Issue whose entire AC is "revise the spec for #N" would get an empty audit indistinguishable from a genuinely clean one. (The discount rule above decides both what is dropped from the emptiness judgment *and* which untracked paths are named to the auditor — the "audited remainder" is one set used for both. What it does **not** decide is this line: whether `docs/specs/<N>/` is the change under review or the intent behind it.)

Substitute the **literal** merge-base commit for `<mb>`, the literal Issue number for `<N>`, **and the literal value for every other `<…>` in that prompt** — the untracked-path list *and* the spec-deliverable line, which carries a leader decision and must not reach the auditor as an unresolved either/or (`_bash_rules.md` item 9).

The auditor returns **JSON, not a `>>> RESULT <<<` verdict**, and it **never decides whether the stage advances** — Step 4 applies the severity policy over its findings.

⚠ **If the mutation check already failed, stop here — do not reach this rule.** A mutating auditor is never re-invoked (see above): an agent that has broken its read-only contract must not be handed a second window to write, whatever its reply looked like. The re-invocation below is only for a scan that was **clean on the tree** and merely unusable in its reply.

⚠ **A reply that is not parseable JSON is a FAILED SCAN, never an empty one.** `_handoff.md` Section C's malformed-reply handling is scoped to the `>>> RESULT <<<` sentinel and so does not cover this agent, and Step 4's advance condition is phrased negatively ("no un-dismissed `BLOCKER`") — which an empty string, a prose apology, or JSON truncated by a context limit would satisfy silently, advancing the stage while the always-on scan this whole step exists for never actually happened. So: an empty reply, prose instead of JSON, or JSON that does not parse → **re-invoke the auditor once, bracketed by its own before/after readings** (the mutation check is mandatory on every spawn, and the run that just broke its output contract is the last one to exempt); if the second reply is also unusable, do **not** advance — return `NEEDS_HUMAN: execute-stage auditor returned no usable findings for #<N>` (attended) / `guild:needs-human` label **+ a `<!-- guild:needs-human -->` comment stating that the auditor returned nothing parseable twice** + `OK PAUSE: needs-human — auditor scan failed` (unattended — `_handoff.md` Section H requires the comment, and without it the human finds a paused Issue with no record of why). Only a **parsed** `[]` counts as "clean".

### 3.5b — Conditional specialists + gate reviews

Convene the **execute-stage participation specialists** and **gate reviews** this change warrants (assembly rules in `.claude/agents/leader.md`; participation model in `_handoff.md` Section G). Match the diff surface against triggers; spawn only what matches (none matched → skip this half; 3.5a still runs). Run the independent reviews in parallel:

- **auth / external exposure / secrets / sensitive data / input validation** → **security**: adversarial review of the developer's diff (a **gate** — reviewing someone else's output, not self-review). Returns findings with severity.
- **CI/CD / deploy / env / IaC touched** → **infra**: review the infra change (rollback/verify path correct?).
- **user-facing strings** → **i18n** · **schema/migration** → **dba** · **instrumentation** → **analytics** · **hot path/render/query** → **performance**: execute-time participation on their slice.
- **user-facing / API / documented-behavior change, OR an architecture-impacting change** (new module / changed boundary / major dependency) → **tech-writer**: draft/update the docs (README, user docs, ADR follow-through) against the **implemented** change — docs describe what was actually built. **② architecture.md drift-sync (Inner Loop)**: when the change is architecture-impacting, keep `docs/standards/architecture.md`'s **high-level skeleton** current (details stay in the ADR + ⑥ — architecture.md is the *slow overview*, not a detail log). By its `status`: `draft` → **update in place** (provisional, safe); `confirmed` → **never silently rewrite** — **attended**: propose the skeleton update, apply on human approval; **unattended** (`GLD_UNATTENDED`): the ADR already preserves the decision, so append a `<!-- guild:arch-drift -->` flag noting architecture.md needs a skeleton update → surfaced at the next `/gld review` or `/gld audit`. (Release notes are the release-manager's job, out of the spine.)

For each matched role:

- `subagent_type`: `general-purpose`, `model`: `sonnet`, `description`: `<role> review #<N>`
- `prompt`:
  > Adopt the persona in `.claude/agents/<role>.md`. Review the implementation on the current branch for Issue #<N> from your specialty. You are reviewing the DEVELOPER's diff, not your own work (external, adversarial). Read `docs/specs/<N>/` for design/intent.
  > <!-- guild:result-contract -->
  > Return EXACTLY one status line, preceded by a `>>> RESULT <<<` sentinel on its own line. Anything before the sentinel is ignored. Status is one of `DONE` / `DONE_WITH_CONCERNS: <one-line>` / `BLOCKED: <one-line>` / `NEEDS_CONTEXT: <one-line>` / `FAIL: <reason>`. **Artifacts are passed as files, not pasted** — write to the working tree or `docs/specs/<issue>/` and name the path in the RESULT line; never inline an artifact body into it.
  > <!-- /guild:result-contract -->
  > Narrowed for this gate: only `DONE`, `DONE_WITH_CONCERNS: <one-line>`, or `BLOCKED: <blocking finding>`. Write output in `config.language`.

ℹ **Known gap, deliberately NOT closed here: 3.5b's doc output is not committed by this spine.** The doc-producing roles write files after the developer's Step 1 commit, and no later step stages them, so a tech-writer ADR/README update stays untracked unless a human commits it. That predates this step and is left alone on purpose — the obvious fix (have the leader `git add`/`git commit` here) was tried and withdrawn, because it made the auditor's own machinery wrong in four ways at once: the leader has no path list to `add` (3.5b roles return a one-line verdict, not a file list, so the fallback is `git add -A`, which would sweep in a sibling Issue's stranded specs); the committed docs then enter `git diff <mb>` and are handed to the next attempt's auditor as the developer's work; a doc commit landing asynchronously breaks the mutation check's attribution; and a tech-writer that must be re-run on loop-back to keep its docs truthful reintroduces the serialisation hazard. What this step does **not** do is pretend the leftover is harmless: with Step 0 running no working-tree check (see (b) there), an untracked ADR is simply part of what Step 3.5a audits on a later attempt, and a finding against it is the visible, human-resolvable cost of not having a path rule that could tell Guild's prose from the repo's.

Fold these verdicts **and 3.5a's findings** into Step 4. A gate role's `BLOCKED` (e.g. security finds a real vulnerability) blocks advancement the same as a tech-lead non-conformance. Which specialties a given variant most often pulls in is noted in the variant file, but the trigger table above is the authority.

**Dedup 3.5a against 3.5b before Step 4** — but do it **by judgment, not by a key**: a 3.5b role returns one free-text `>>> RESULT <<<` line with no `file`/`line` fields (the `guild:result-contract` fence in its prompt forbids more — `_handoff.md` Section C holds the canonical copy), so there is nothing to join the auditor's `file`+`line` JSON against mechanically. As the leader, read the gate verdict's one-line reason and the auditor's findings and merge only where they plainly describe **the same defect** — e.g. security returns `BLOCKED: token logged in the request handler` and the auditor returns a `BLOCKER` at that handler's line. Counting one defect twice inflates the loop-back reason handed to the developer, distorts the stagnation signature (`_stagnation.md` Section A), and would double-count it in the ground-truth log.

⚠ **Merging may reduce the count; it may NEVER reduce the severity.** Where a gate verdict and an auditor finding describe the same defect, keep the gate role's wording as canonical (it carries the specialist's reasoning) but keep **the stricter of the two dispositions**. A `DONE_WITH_CONCERNS` from a gate role does **not** neutralise an auditor `BLOCKER` on the same defect — treating it as one non-blocking item would silently drop something the severity policy says blocks unconditionally. When unsure whether two items are the same defect, **do not merge** — a duplicated finding costs one redundant line, a wrongly-merged one costs the block.

## Step 4 — Arbitrate (defined feedback loop)

As the leader, over the developer + tech-lead + any conditional specialist/gate verdicts + the **Step 3.5a auditor findings** (deduped per 3.5b's closing note):

**Auditor severity policy** — applies to 3.5a findings only; a 3.5b gate role's `BLOCKED` keeps its own rule (the bullet below) regardless of any severity the auditor assigned to the same area:

| Severity | Action |
|---|---|
| `BLOCKER` | **Blocks.** Loops back on the same path as a tech-lead `BLOCKED`, for as many attempts as the shared cap allows. |
| `MAJOR` | **Blocks at most once per execute invocation.** See the budget rule below. |
| `MINOR` | **Never blocks.** Record verbatim (Step 4's Issue record + Step 5's PR body) so the human sees it at `/gld review`. |

**The MAJOR budget is per execute invocation, not per finding — one rule, stated once, so nothing else has to infer it.** This execute invocation may spend **at most one** loop-back whose *only* blocking trigger was a `MAJOR`. Once that attempt is spent, every subsequent un-fixed `MAJOR` — the same one, or a different one first seen on a later attempt — is **recorded and not retried**; it does not block the advance. A `MAJOR` riding along with a `BLOCKER` costs nothing extra: that loop-back was already owed to the `BLOCKER`, and the developer is handed both. The MAJOR loop-back **consumes one of the stage's ~2 attempts** — it is not an extra allowance on top of them.

⚠ **The attempt cap outranks the MAJOR budget: an un-fixed `MAJOR` NEVER holds the stage open once the cap is reached.** The two limits can otherwise deadlock. Walk it: attempt 1 raises `BLOCKER A` + `MAJOR M`, so the loop-back is owed to `A` and the MAJOR budget stays *unspent*; attempt 2 fixes `A` but not `M`; the advance condition still says "no un-fixed `MAJOR` while the MAJOR budget is unspent", so it refuses — yet the ~2-attempt cap is already exhausted, and its only exit is `NEEDS_HUMAN` / `OK PAUSE`. That would escalate a run in which every blocking finding was fixed, over a severity the policy calls non-blocking, and unattended it would pause a `batch` Issue for it. So when the cap is reached, an un-fixed `MAJOR` is **`recorded`, not blocking** — exactly as when the budget itself is spent. The MAJOR budget can only ever *spend* an attempt that remains; it can never *create* the need for one.

Why the severities are not treated alike: a human applies `MINOR` findings *selectively*, so the **selection is the judgment** — automating the fix while discarding the judgment produces churn, not quality. `MAJOR` is usually real but occasionally directionally-right-yet-wrongly-fixed, so it gets exactly one bounded attempt. `BLOCKER` is the severity that keeps looping back for as long as the shared cap allows.

**The auditor is advisory about *what*, never about *whether*.** It reports; the leader decides. A finding the leader judges wrong (misread intent, a rule that does not apply here, a "defect" the design deliberately chose) is **dismissed with a one-line reason**, recorded per the "Auditor record" rule below — never silently. Dismissing is a normal outcome, not a failure of the scan.

⚠ **Unattended (`GLD_UNATTENDED=1`), a `BLOCKER` may NOT be dismissed.** Attended, a dismissal is safe because the human sees it at `/gld review` before approving. Unattended there is no such reader in the loop, and `batch.md` would count the Issue as succeeded — so a self-issued dismissal would be the one place in the spine where an agent overrules a blocking finding with nobody ever checking. It would also make the always-on path *weaker* than the conditional one it backstops, since a 3.5b gate `BLOCKED` cannot be dismissed at all. So when unattended, an auditor `BLOCKER` has exactly two outcomes: **fixed**, or — if the leader believes it is wrong, or the loop-back budget is exhausted — `guild:needs-human` label + a `<!-- guild:needs-human -->` comment stating the finding and why the leader disputes it, then `OK PAUSE: needs-human — disputed auditor BLOCKER` (do NOT transition). `MAJOR`/`MINOR` may be dismissed with a recorded reason in either mode.

⚠ **Read the existing auditor record BEFORE arbitrating — a re-entered invocation must not re-litigate what an earlier one already settled.** Execute is re-entered from `test`/`qa` as a fresh invocation with no memory, and 3.5a re-scans unchanged code, so an auditor `BLOCKER` that a previous invocation **dismissed with a recorded reason** comes back verbatim. Treating it as new would burn the whole retry budget forcing the developer to undo a decision the spine already made and recorded — and unattended, where a `BLOCKER` may not be dismissed, it would end in a pause over an already-adjudicated finding. So fetch the record (the query below) first, and for each of this attempt's findings that matches a prior **`dismissed` or `recorded`** entry — **same file and same underlying defect, not necessarily the same line number** (a redo elsewhere in the file shifts line numbers, and keying on `file:line` alone would silently fail to recognise the very finding it was written to recognise; this is the same "same root cause, reworded" judgment `_stagnation.md`'s calibration describes) — decide whether that dismissal still applies by asking whether the file has changed since it was made (its own Bash call — the recorded block names the HEAD it was produced against):

```bash
git diff --name-only <that block's recorded HEAD> -- <the finding's file>
```

`<that block's recorded HEAD>` is unambiguous: it is the **pre-spawn** `git rev-parse HEAD` reading of the attempt that wrote the block (the "before" half of that attempt's mutation check) — not the post-scan reading, and not any re-take.

Empty → **usually** the file is untouched since the dismissal, so the reasoning behind it still holds: carry it forward as `dismissed` with the **original** reason; it does not block.

⚠ **But an empty result is meaningless for an UNTRACKED path** — `git diff` never reports one, as 3.5a says twice about its own readings. That is not a corner case here: the commit gate blocking a commit routinely leaves the developer's new files untracked, and a redo can rewrite such a file wholesale while this predicate still returns empty, carrying forward a dismissal about content that no longer exists. So before trusting an empty result, check whether the finding's path is untracked (it is in the `git status --porcelain -uall` reading 3.5a already took — a `??` entry). If it is, the predicate cannot decide: **treat the finding as new**, per the same err-toward-re-examining default as the unreadable case below. Non-empty → **look before concluding**: the spine allows the developer's work to be uncommitted at scan time, so the file can differ purely because that same already-dismissed work was committed afterwards, with no change to the code the dismissal was about. Compare the current content at the finding's location against what the dismissal describes; only a *substantive* change to it retires the dismissal. When the comparison is genuinely unclear, treat the finding as new — re-examining a settled finding costs one bounded attempt, while wrongly carrying a dismissal forward silently waves through a real defect.

⚠ **The predicate looks at the finding's own file, which is a real limit**: a dismissal reasoned on another file ("X is safe because Y validates it") is not retired by a change to Y. State the dismissal's dependency in its recorded reason when it has one, and treat a finding whose reason names another file as new whenever that file has moved.

A `recorded` entry carries forward the same way **only when it is a `MAJOR`**: the spine already decided not to retry that one (out of budget, or at the attempt cap), and a re-entered invocation gets a fresh MAJOR budget — so without this the auditor's verbatim re-report would spend a full opus-tier retry of developer + tech-lead + 3.5a + 3.5b on a finding the spine had deliberately set aside. Carry a `recorded` `MAJOR` forward as `recorded`; it does not block.

⚠ **A `recorded` `BLOCKER` is the one disposition that NEVER carries forward — it re-blocks.** It reaches that state whenever an attempt ended with it un-fixed and un-dismissed — unattended (where dismissing a `BLOCKER` is forbidden outright), but also attended, when the cap was reached and the leader did not judge the finding wrong. **The rule is the same in both cases and does not depend on which one produced it**: `recorded` means "nobody fixed this and nobody ruled it invalid", so carrying it forward as non-blocking would turn "stop and get a decision" into "advance", letting one pause-plus-resume achieve exactly the dismissal that was never made. On re-entry an un-fixed `BLOCKER` is a `BLOCKER` again, with the full loop-back and, failing that, the same pause. Only a **`dismissed`** `BLOCKER` carries forward, and only because that disposition can only ever have been created attended.

⚠ **This is a carry-forward, not a new dismissal, so the unattended prohibition does not bite** — and cannot be used to evade it. A recorded `dismissed` `BLOCKER` can only ever have been created on an attended run (unattended, a `BLOCKER` has exactly two outcomes: fixed, or `OK PAUSE`), so carrying it forward re-uses a *human-visible* decision rather than making a fresh one. If the `git diff` above cannot be run, or the recorded HEAD is missing, do **not** guess in the permissive direction: treat the finding as new.

**Auditor record (on the Issue, written HERE at Step 4 — not deferred to Step 5).** As soon as the disposition of this attempt's findings is decided, post them to the Issue under `<!-- guild:auditor:execute -->` … `<!-- /guild:auditor:execute -->` (temp-file pattern — one comment for the Issue, PATCHed rather than duplicated): every finding with severity + `file:line` + the one-line finding, its disposition, and for a dismissal the one-line reason. The disposition vocabulary is **four** ASCII tokens (`_handoff.md` Section K), one of which exists precisely because the record is written *at loop-back time*, before anyone knows the outcome:

| Token | Meaning |
|---|---|
| `looped-back` | it triggered this attempt's loop-back — outcome not yet known |
| `fixed` | a later attempt confirmed the redo addressed it |
| `recorded` | not retried (an out-of-budget `MAJOR`, or a concern carried to the PR) |
| `dismissed` | the leader judged it wrong — **reason required** |

⚠ **Earlier blocks are never edited, so a resolution is recorded by the NEXT block, and a finding's disposition is its most recent one across all blocks.** When an attempt opens, re-state **every** finding the previous block left at `looped-back`, choosing by what is true now — not by the re-scan alone:

- the re-scan no longer reports it → **`fixed`**;
- it is still reported **and still being retried** → **`looped-back`** again;
- it is still reported but **no longer being retried** — the MAJOR budget is spent, the leader dismissed it this attempt, or the stage is exiting via advance / bounded-retry exhaustion / stagnation → **`recorded`** (or **`dismissed`**, with the reason — ⚠ but **never write `dismissed` for a `BLOCKER` on an unattended run**, at an exit path or anywhere else: the severity policy allows an unattended `BLOCKER` exactly two outcomes, and the carry-forward rule in Step 4 relies on every recorded `BLOCKER` dismissal having been a human-visible, attended decision. Unattended, an un-fixed `BLOCKER` at an exit path is `recorded`.).

A finding must never be left at `looped-back` on a block that is not itself issuing a loop-back for it: `looped-back` means "outcome pending", so leaving a settled finding there would strand it — Step 5 renders `fixed` as a summary line and `recorded`/`dismissed` individually, and a stale `looped-back` matches neither, silently dropping a real unfixed defect from the PR.

⚠ **This re-statement is owed even when this attempt's auditor returned `[]`.** Step 4 writes no block when there is nothing at all to record, but a pending `looped-back` from the previous block *is* something to record — a clean re-scan is exactly the evidence that it is now `fixed`. That case (attempt 1 blocks, redo fixes it, attempt 2 clean) is the most common shape there is, so getting it wrong would leave essentially every resolved blocker showing as pending. Without that, every blocking finding would stay frozen at `looped-back` forever and Step 5 — which now renders the PR section straight from this record — would publish a defect the developer actually fixed as still open, on the one surface the human reads at `/gld review`.

⚠ **This marker is the documented exception to Section B's "PATCH rather than appending" rule — the PATCH here is CUMULATIVE.** Replacing is a real data-loss bug, not a tidiness question: execute is re-entered from `test.md` Step 3 and `qa.md` Step 2 as a *fresh invocation* (see the cost note in Step 3.5a) whose leader has no memory of the earlier one, so a replacing PATCH would erase invocation 1's dismissals — including a dismissed `BLOCKER` — and the human at `/gld review` would never learn a blocking finding had been overruled. That is precisely the failure this record exists to prevent.

**So the write takes one extra step over `_bash_rules.md`'s temp-file flow: fetch the existing BODY, not just the comment id — and BOTH lookups must be paginated.** The sanctioned discovery query returns `.id` and carries no `--paginate`; for this marker, run **both** the `.id` and the `.body` lookup with `--paginate`. Paginating only one of them is worse than paginating neither: the `.body` read would find the record while the `.id` read came back empty, sending the write down `_bash_rules.md`'s "Empty → create" branch and posting a **second** record comment. Run **both** of these, each its own Bash call (substitute the literal `<owner>/<repo>` and `<N>`). Note that only the **final** field differs; the one inside `select(...)` stays `.body`, since that is what carries the marker:

```bash
gh api --paginate repos/<owner>/<repo>/issues/<N>/comments --jq '.[] | select(.body | contains("<!-- guild:auditor:execute -->")) | .id'
```


```bash
gh api --paginate repos/<owner>/<repo>/issues/<N>/comments --jq '.[] | select(.body | contains("<!-- guild:auditor:execute -->")) | .body'
```

⚠ `--paginate` is required here too. Without it a long Issue's record falls off the first page, the fetch returns empty, the "first write" branch below creates a **second** `guild:auditor:execute` comment, and Step 5 then renders the PR section from that stub — dropping every earlier dismissed `BLOCKER`, which is the exact erasure this record exists to prevent.

⚠ **Check that `.body` read for truncation before rendering anything from it.** This comment grows a block per attempt and per re-entry, so it is exactly the kind of long output that comes back as a preview — and rendering "returned body + new block" from a preview silently deletes the earlier blocks, including a dismissed `BLOCKER`, which is the erasure this cumulative rule exists to prevent, propagated to the PR by Step 5's render. If it was truncated, read the persisted full-output file the tool result names; if the full body is not available either way, do **not** PATCH — `NEEDS_HUMAN: could not read #<N>'s auditor record in full` (attended) / `guild:needs-human` label + a `<!-- guild:needs-human -->` comment + `OK PAUSE: needs-human — auditor record unreadable` (unattended).

Then render the new comment body with the Write tool as **the returned body with this attempt's block inserted immediately BEFORE the closing `<!-- /guild:auditor:execute -->` marker**, everything else byte-intact, and PATCH by id as usual. ⚠ Append *inside* the pair, not after it — a block written below the closing marker leaves this record no longer a marker-delimited block, and Step 5 renders the PR section from the delimited content. ⚠ **This is specific to the audit record.** The sibling `<!-- guild:auditor-violation -->` note deliberately takes its resolved marker *below* its closing marker, because Step 0's guard reads the comment's **last non-blank line**, not the pair — two different comments, two different read mechanisms, and neither rule generalises to the other. Empty result → this is the first write; render the marker pair plus the first block.

**Numbering is derived from the body you just read, not remembered**: the block heading is `### audit-record <n>` — an **ASCII machine token, never localized** (`_handoff.md` Section K), so that counting works identically on an English- and a Korean-configured repo; the surrounding prose inside the block is in `config.language` as usual. Count the `### audit-record ` headings already present and use the next integer. One block per *attempt*, not per invocation — attempt 2 of one invocation and the first attempt of a re-entered invocation are both simply the next `audit-record`, so nothing has to reconstruct an invocation ordinal it cannot know. Each block names the branch HEAD it was produced against — specifically the **pre-spawn** `git rev-parse HEAD` reading of this attempt's mutation check (its "before" half), never the post-scan reading and never a re-take; record the full SHA and do not take a second `--short` reading. ⚠ **When this attempt never reached 3.5a** — Step 2's evidence cross-check can loop back to Step 4 directly, so no scan and no readings happened — there is no such value: take `git rev-parse HEAD` now, record it, and mark the block "no scan this attempt". The carry-forward test below still works against it (it only needs a commit to diff from), and the marker keeps a reader from mistaking a missing scan for a clean one. Step 4's carry-forward test diffs against exactly this value, so recording a later one would make a changed file look untouched — so a reader can tell which diff each disposition refers to.

This is deliberately **not** kept only in the PR body. Step 4 can exit without ever reaching Step 5 — `FAIL`, `NEEDS_HUMAN`, `OK PAUSE: needs-human`, a stagnation escalation — and Step 5 itself has four non-PR exits (no remote, push rejected, protected branch, `gh pr create` failure). Every one of those paths would otherwise destroy the dismissal record, which this step's own rule calls the one failure mode that would make the auditor untrustworthy. The Issue comment survives all of them. Be precise about who reads it back. **No stage treats it as a stage input and `/gld resume` re-enters from the *label*, so it never routes the flow.** It does, however, influence the outcome of *this* stage — deliberately: a dismissal carried forward from it is the difference between advancing and pausing on an already-adjudicated finding, which means it can decide both the stage transition and the `guild:needs-human` label. Two steps read it, and both are mandatory: **Step 4** fetches it before arbitrating (to carry a prior invocation's dismissal forward instead of re-litigating it) and **Step 5** fetches it to render the PR section. Beyond that its readers are the **human** (on the Issue, and via the PR copy at `/gld review`) and anyone auditing after the fact. Step 5's PR-body section is a **convenience copy for the reviewer**, not the record of account.

- Developer `DONE`/`DONE_WITH_CONCERNS` + tech-lead `DONE`/`DONE_WITH_CONCERNS` + all gate/specialist verdicts `DONE`/`DONE_WITH_CONCERNS` + **no un-dismissed auditor `BLOCKER`, and no un-fixed `MAJOR` while this invocation's single MAJOR loop-back is still unspent — except at the attempt cap, where the ⚠ rule in the severity policy above makes an un-fixed `MAJOR` `recorded` rather than blocking** + raw evidence green **as the variant's EVIDENCE RULE defines green** → **first evaluate any deferred auditor captures a prior attempt left pending** (the ⚠⚠ rule under the loop-back bullet below — it is owed on this path, not only on a loop-back), then proceed to Step 5. **Record every `DONE_WITH_CONCERNS` from the tech-lead or a specialist/gate role in the PR body**, alongside the auditor's surviving findings — a concern that advances silently is a concern the human reviewer never sees, and execute writes no `guild:*:output` Issue comment of its own for it to land in instead.
- Tech-lead `BLOCKED` (a failure of the variant's **CONFORMANCE CHECKS**), a **gate `BLOCKED`** (e.g. security vulnerability), an **auditor `BLOCKER`, or a `MAJOR` while this invocation's single MAJOR loop-back is still unspent (per the severity policy above)**, OR evidence contradicting the EVIDENCE RULE → before looping back, apply the **stagnation guard** (`_stagnation.md`): compare this reason against the immediately-prior loop-back's reason for this Issue (if any). The comparison is **per source, not pooled** — the role reason(s) on one axis, the auditor's `BLOCKER`/`MAJOR` signature set on the other, with either axis repeating enough to flag stagnation. `_stagnation.md` Section A defines both axes; the chain rule below means both are usually present on an execute loop-back. **Same root cause repeated** → stagnation — escalate immediately (`_stagnation.md` Section B) instead of consuming another attempt. **Different concern** → **defined loop back to execute**: re-invoke the developer (Step 1) — and **every role re-run in that retry**, which per the chain rule below means the tech-lead (Step 3), the auditor (Step 3.5a), **and every 3.5b specialist/gate role the redone diff matches** — not merely the one whose `BLOCKED` triggered this, since that cast is re-derived from the new diff and may include a role that did not run on attempt 1 (`_model_tiering.md` Section A says the same: no narrower list) — **at one model tier above their default** (`_model_tiering.md` Section A: sonnet → opus; attempt 1 always ran at the default, this is the one bounded retry), with the specific concern. **A loop-back re-runs the whole check chain over the redone diff — Step 1 → Step 2 → Step 3 → Step 3.5a → Step 3.5b.** All of it, including **re-matching 3.5b's triggers against the redone diff** rather than re-running only the role that blocked. Not just the trigger: an auditor `BLOCKER` is a trigger no *role* raised, so a narrow "re-invoke the developer and the role that blocked" reading would leave the stage advancing on attempt 1's tech-lead conformance verdict, issued against a diff that no longer exists. The advance condition still demands a tech-lead verdict, so that verdict must be about the code that actually ships. In particular, **re-run 3.5a on EVERY loop-back, whatever triggered it** — not only on auditor-triggered ones.

⚠ **And re-derive 3.5b's cast from the REDONE diff — a redo can change which specialists the change warrants.** Two distinct failures otherwise. (a) A role that returned `DONE` on attempt 1 has judged a diff that no longer exists, yet the advance condition still counts its verdict as current. (b) Worse, a role that *did not match* attempt 1 may match now: a redo that routes the fix through an auth helper, adds a migration, or touches CI newly warrants **security**/**dba**/**infra** — and if triggers are never re-matched, that gate never runs at all, so the stage can advance past the exact risk the gate exists for. Re-matching costs nothing when the surface is unchanged (the same roles match, and an unaffected role's re-run is cheap); skipping it can ship an unreviewed auth change. The auditor's whole purpose is that the diff which ships has been audited; if a tech-lead `BLOCKED` (or a failed EVIDENCE RULE) sends the developer back and only the tech-lead re-checks, the rewritten code is never audited at all, and the Issue/PR record would still be listing attempt 1's `file:line` findings against a diff that no longer exists. The re-run is bumped one tier like the rest of the retry (it has no persona and no default of its own to change — it simply re-scans), and it is what produces attempt 2's blocking signature for the stagnation guard. Bounded — after ~2 loops without resolution: **Attended** → return `NEEDS_HUMAN: <one-line>`. **Unattended** (`GLD_UNATTENDED=1`, `_handoff.md` Section H — detect via `printenv GLD_UNATTENDED`): there is no human to answer `NEEDS_HUMAN` here, so treat bounded-retry exhaustion the same as a stagnation escalation — add the **`guild:needs-human` label** + a `<!-- guild:needs-human -->` comment stating the unresolved concern, and return `OK PAUSE: needs-human — <one-line>` (do NOT transition the stage label). This mirrors `test.md`/`qa.md`'s unattended handling at their own bounded-retry exit.
  - **Ground-truth capture (①, `_signals.md` Section C — agent↔agent correction):** when this loop-back fires on a **real reversal** (a `BLOCKED`, or raw evidence contradicting a claimed green — **not** a mere `DONE_WITH_CONCERNS`), append one entry (its own Bash call, best-effort — never blocks the loop). The `BLOCKED` non-conformance/finding (or the contradicting raw line) **is** the objective anchor — a role overturning *another* role's confident output, not self-review (`_signals.md` Section B). `--surprise` always (confident work reversed); add `--escalated` since Step 4 just bumped the retry's model tier (`_model_tiering.md` Section B):
    ```bash
    python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue <N> --stage execute --role <tech-lead|security|infra|…> --area "<the variant's SIGNAL AREA>" --summary "<what was reversed, 1 line>" --evidence "<the BLOCKED non-conformance/finding, 1 line>" --surprise --escalated
    ```
    For the **evidence-contradicts-green** case (developer claimed green, the raw runner disagreed) use `--kind verify-gap --role developer` instead — the same claimed↔raw shape as the test stage, caught earlier at execute. **Skip** when no loop-back occurred (all `DONE`/green) — a passed conformance check is not a signal (agreement ≠ correction). **When the stagnation guard fires** (the blocking signature repeated), capture `--kind stagnation` instead of a `correction` **for the stall itself** (`_stagnation.md` Section C) — this applies to an auditor-triggered stall too. ⚠ "Instead" scopes to *this* entry only: it does **not** cancel the deferred auditor captures owed for `BLOCKER`s the redo actually resolved (see the ⚠⚠ rule below, which names the stagnation exit explicitly) — the recurrence is the signal, not a single role's reversal; drop `--escalated` there (a stagnant loop-back does not retry at all, so no tier was bumped).

    **Auditor findings are capped hard, and captured LATE — this is a volume guard, not a preference.** The 3.5a auditor runs on **every** Issue, so appending an entry per finding per run would flood `ground-truth.jsonl`. That is not merely noisy: it would let `_data_sufficiency.md`'s "≥5 anchored signals" threshold be satisfied by **scan volume instead of real reversals**, firing `evolve` on noise — and the extra loop-backs would inflate the `--escalated` rate feeding `_model_tiering.md` Section C, which could then propose raising a role's default tier on the strength of that same noise. Capture an auditor finding **only when both** hold: **(a)** it was `BLOCKER` severity, **and (b)** the loop-back it triggered **actually changed code** — the developer's redo produced a diff addressing it.

⚠ **Condition (b) is unknowable at loop-back time, so this one capture does not fire with the others — and it is NOT covered by the "skip when no loop-back occurred" rule above.** Every other capture on this step fires *as* the loop-back is decided; whether the redo addressed the finding is only known once the redo exists. So defer it: on the **next** pass through Step 4 (after the redo), compare the prior attempt's un-dismissed `BLOCKER`s against the redone diff and append one entry for each the redo actually addressed.

⚠⚠ **That next pass is usually the all-green ADVANCE pass, so this evaluation belongs to the advance bullet as much as to the loop-back bullet.** The most common shape by far is: attempt 1 raises an auditor `BLOCKER` → the developer fixes it → attempt 2 is clean and the stage advances. The general rule above ("skip when no loop-back occurred — a passed conformance check is not a signal") is about *this* attempt having nothing to report; it must not be read as cancelling the **previous** attempt's deferred evaluation. So: **before taking the advance bullet, if a prior attempt in this invocation left un-dismissed `BLOCKER`s pending evaluation, evaluate and capture them now.** Dropping them here would mean the signal is never written on the exact path it was designed for. Deferring only ever skips the capture when **no redo ran at all** — in practice a `FAIL` before the developer was re-invoked. Two paths that look like exits are **not** exemptions, because the redo did run on both:

- **Bounded-retry exhaustion** — the retries ran; some attempt-1 `BLOCKER`s may well have been addressed even though a different concern kept the stage blocked.
- **A stagnation escalation** — under `_stagnation.md`'s *containment* rule, stagnation fires whenever nothing **new** is driving the loop, which explicitly includes the case where part of the previous set was resolved (`{A, B}` → `{A}` fires: "B was fixed"). So a stagnation exit routinely follows a redo that fixed something. `_stagnation.md` Section C owns the *stagnation* entry itself; it does not speak for the auditor `BLOCKER`s the same redo resolved.

On both, evaluate condition (b) exactly as on the success path and capture what the redo did address **before** returning `NEEDS_HUMAN`/`OK PAUSE`. These are the paths where the signal is most worth having, so they must not be dropped as a side effect of the deferral.

A `MAJOR`, a dismissed finding, or a `BLOCKER` the redo did not act on is **not** a captured signal; it lives in the Issue's `guild:auditor:execute` record and the PR body. The command, in full (its own Bash call, best-effort — never blocks):

```bash
python3 <<SKILL_DIR>>/commands/atoms/capture_signal.py --kind correction --issue <N> --stage execute --role auditor --area "<the file/area the finding concerns>" --summary "<the BLOCKER the redo resolved, 1 line>" --evidence "<file:line + why, 1 line>" --surprise
```

`--role auditor` is deliberately not a roster role name (`_handoff.md` Section G) so role-keyed aggregations can tell it apart. ⚠ **Never pass `--escalated` on this capture**, even though the loop-back it describes did bump the retry tier: `--escalated` exists to feed `_model_tiering.md` Section C's per-role default-tier proposal, and the auditor has no `.claude/agents/*.md` and no stated default for that proposal to change. Tagging it would put a permanently-100% row into a scorecard that must not contain it at all.
- Any `FAIL` → return `FAIL: <reason>`.

## Step 5 — Open PR

As the leader, push the branch and open a PR referencing the Issue (temp-file body via `--body-file`; body references `Closes #<N>` and carries the variant's **PR SUMMARY**). **Push with an explicit refspec** — `git push -u origin <branch>` — never a bare `git push`: with an injected remote-tracking base the branch may carry an upstream pointing at the base (Step 0 sets `--no-track` to prevent it, and this makes the push safe even if that flag is ever lost).

**Target the PR at `<base>`** — pass `--base <base-branch-name>` to `gh pr create`. Two details:
- **Strip a remote-tracking prefix.** `--base` takes a *branch name*, so `origin/develop` must be passed as `develop`.
- **Re-verify the base exists ON THE REMOTE, now.** `<base>` was resolved at Step 0 and this step can run hours later; a human may have merged the dependency's PR and deleted its branch in between. `git rev-parse --verify` is not enough — the local branch survives that deletion and the check would pass while `gh pr create` returns **422**, which the failure table below classifies as terminal. Its own Bash call:
  ```bash
  git ls-remote --heads origin <base-branch-name>
  ```
  **Judge the exit code before the output.** A network or auth failure prints nothing on stdout either (measured: no remote → `fatal: 'origin' does not appear to be a git repository`, exit 128, stdout empty), and this file's own rule at (c) — *"Read the error before assuming that is the reason"* — applies here:
  - **exit 0 + non-empty** → the base is still there; pass it to `--base`.
  - **exit 0 + empty** → the branch really is gone. Fall back to the repo's default branch and **say so in the PR body**; the dependency has landed, so targeting the default branch is now correct.
  - **non-zero exit** → the remote could not be reached. Do **not** claim the dependency landed: keep `<base>` and let `gh pr create` report the truth, or if that also fails, surface the git error itself. Writing "the dependency has landed" into a PR body on a transient network error is a false statement in a permanent record.

⚠ Until this step, PRs were always opened against the repo's default branch even though Step 0 called `<base>` "the branch Step 5's PR targets" — `--base` was simply never passed. With no injection `<base>` is *derived from* `defaultBranchRef`, so the two agreed and nothing was broken; passing `--base` explicitly is what makes the injected case work, and it leaves the non-sprint case unchanged.

**Stack notice (only when `<base>` is not the default branch)** — add a marker-delimited block so the reviewer learns the ordering *in the PR*, where they actually arrive from a GitHub notification rather than from a terminal:

```markdown
<!-- guild:sprint:stack -->
## 스택 PR (스프린트 #<tracker>)
- 이 PR은 **#<하단 PR> 위에 쌓여** 있습니다 (스택 <n>단 중 <i>번째).
- **먼저 머지**: #<하단 PR> → … → 이 PR
- 이 diff는 base 브랜치 위의 변경만 담습니다 — 하단 PR들의 변경은 포함되지 않습니다.
- 전체 순서: `/gld sprint daily`
<!-- /guild:sprint:stack -->
```

Same in-place-replacement rule as the auditor block below (markers are the anchor, heading text in `config.language`). ⚠ Merging out of order is not prevented by GitHub's UI — this notice and `daily`'s ordered list are the only defences. The PR is where the **human reviewer** (M1's external reviewer) approves. **Resume-safe**: if a PR for this branch already exists (interrupted prior run), PATCH it rather than opening a duplicate. **Unattended (`GLD_UNATTENDED=1`)**: append a `## 무인 결정 로그 (GLD_UNATTENDED)` section to the PR body aggregating the leader-proxy gate decisions recorded in the analyze/design outputs (chosen interpretation · charter rationale · "사람 확인 요") — `_handoff.md` Section H — so the deferred human gate (PR review) is informed, not blind.

**Auditor section (a reviewer-facing copy of the Step 4 Issue record; mandatory whenever that record is non-empty — NOT keyed to whether *this* invocation's auditor found anything)** — add a marker-delimited **"external auditor (execute)" section** to the PR body — the heading text itself in `config.language` (`## 외부 감사자 (execute)` on a `ko` repo), since the stable anchor is the HTML marker, not the words — wrapped in `<!-- guild:auditor:pr -->` … `<!-- /guild:auditor:pr -->` so a later write replaces that block in place instead of leaving two contradictory copies (Step 5 already PATCHes an existing PR rather than opening a duplicate, and execute can be re-entered from test/qa).

⚠ **This read-then-render sequence applies when a PR ALREADY EXISTS** (the resume-safe PATCH path, and any later re-entry). **When Step 5 is creating the PR**, there is no body to read and no `<PR_NUM>` yet: compose the body with this section already in it and pass it to `gh pr create --body-file`. Do not run the read on that path — "neither available" would be literally true and would pause a healthy run over a body that does not exist yet.

⚠ **On the PATCH path, read the current PR body first — this is mandatory, not optional.** `gh pr edit --body-file` **REPLACES the entire PR body**; it does not patch it (the same hazard `qa.md` Step 2.5 documents for its `<!-- guild:manual-qa -->` section). Writing this section without reading first would silently destroy whatever else is in the body — qa's Manual Test Checklist, and the `## 무인 결정 로그 (GLD_UNATTENDED)` block written earlier in this very step (INV4). So, in order: (1) `gh pr view <PR_NUM> --repo <owner>/<repo> --json body --jq .body` (its own Bash call) — ⚠ **and check that read for truncation before using it**: a long PR body comes back as a preview, and "everything outside the markers preserved byte-for-byte" then silently drops the tail, destroying exactly what this read exists to protect. Truncated → read the persisted full-output file the tool result names; neither available → do **not** write the body: `NEEDS_HUMAN: could not read #<N>'s PR body in full` (attended) / `guild:needs-human` label + a `<!-- guild:needs-human -->` comment + `OK PAUSE: needs-human — PR body unreadable` (unattended); (2) render the full new body = the returned body with **only** the `<!-- guild:auditor:pr -->` block replaced or appended, everything outside the markers preserved byte-for-byte; (3) write it with the temp-file pattern.

The section contains:

- **one single aggregate line covering ALL findings whose latest disposition is `fixed`** — how many `BLOCKER`s and how many `MAJOR`s, and one clause on what changed. Not one line each, and not an item-by-item list: the diff already shows them;
- **every finding whose latest disposition is `recorded` or `dismissed`**, listed individually: severity, `file:line`, the plain-language finding, and — for a dismissal — the one-line reason.

Resolve each finding by its **latest** block, never its first (Step 4's rule): a finding that appears as `looped-back` in `audit-record 1` and `fixed` in `audit-record 2` is fixed, and listing it as outstanding would be a false alarm on the PR.

This section is what puts the record in front of the human at `/gld review`: they see exactly what the spine chose **not** to act on, and `review.md` Step 2.5's independent pass can be read against it. It is a **copy**, and like the Issue record it is **cumulative** — and it has a concrete source, because a re-entered execute remembers nothing on its own: **fetch the `<!-- guild:auditor:execute -->` comment body here and render this block from it** (its own Bash call — the same discovery query Step 4 uses, asking for `.body`, and with the same truncation check: a preview of a long record would render a partial history and drop the earliest dismissed `BLOCKER` from the PR — the omit rule below keys on the fetch returning *nothing*, which a preview does not). Fetch it *now* rather than reusing anything from Step 4: the body Step 4 fetched predates its own append, and on an invocation whose auditor returned `[]` Step 4 wrote nothing at all, so neither of Step 4's copies is a reliable source. A fresh read is correct on every path and costs one call.

That body holds every `### audit-record <n>` block from every attempt and invocation, which is exactly what this section must show. Rendering from *this* invocation's findings instead would let a re-entered run replace the block with its own results and erase an earlier dismissed `BLOCKER` from the very surface the human reads. The record of account is the `<!-- guild:auditor:execute -->` comment Step 4 already wrote on the Issue, which survives the paths that never reach this step. Keep the two consistent; if they ever disagree, the Issue comment wins. ⚠ **The omit rule keys off that fetched record, never off this invocation alone.** Omit the section only when the fetch above returns **nothing** — no attempt of any invocation ever recorded a finding — and then say nothing rather than writing a "없음" placeholder. A re-entered execute whose own auditor returned `[]` still renders the section from what the fetch returned: reading "no findings → omit" as "this run found nothing → drop the block" would delete an earlier invocation's dismissed `BLOCKER` from the PR, which is the erasure this whole rule exists to prevent. The Step 4 Issue comment is likewise only skipped when there has never been anything to record.

**Both the push and the PR call are state mutations — `_handoff.md` Section F (`gh` write failures) governs them**: verify each landed (the push's remote ref exists; `gh pr create` returned a non-empty PR URL), one retry only if transient, and **never report a failed push/PR as success**. Failure paths:

- **No remote configured** (`git remote -v` empty) → terminal: `FAIL: no git remote — the PR step requires one; the work is committed on branch <branch>`.
- **Push rejected (non-fast-forward)** — the remote branch diverged. **Do NOT force-push and do NOT rewrite history** (INV3). Re-read the divergence (`git fetch`, then `git log --oneline origin/<branch>..<branch>` / the reverse) and escalate: **attended** → `NEEDS_HUMAN: branch <branch> diverged from origin — resolve before the PR`; **unattended** → `guild:needs-human` label + comment, `OK PAUSE: needs-human — branch diverged from origin` (do NOT transition).
- **Protected branch / push permission denied** → terminal `FAIL:` (a retry cannot help — `_handoff.md` Section F).
- **A PR already exists for this branch** — not an error: this is the resume-safe case above. Find it (`gh pr list --head <branch> --state open`) and PATCH its body instead of creating a second PR.
- **PR creation fails otherwise** — template/validation (422) or insufficient permission (403) → terminal `FAIL: gh pr create failed for #<N> — <gh error>`; rate limit / 5xx / network → one retry, then the same `FAIL`.

In every failure case the branch still holds the committed work — say so, and do **not** return `OK ADVANCE: test`: work with no open PR has no human reviewer (INV1), so the stage has not advanced.

## Step 6 — Transition + return

Remove **whatever `guild:*` stage label Step 0 actually found** (substitute in place of `guild:execute` below if it was something else — `gh issue edit --remove-label` on a label the Issue doesn't carry can error; **never remove `guild:child`** if present — `_handoff.md` Section A). **Also remove `guild:needs-human` in this same call if Step 0's label read found it present** (`_handoff.md` Section A):

```bash
gh issue edit <N> --remove-label "guild:execute" --add-label "guild:test" --remove-label "guild:needs-human"
```

Return:

```
>>> RESULT <<<
OK ADVANCE: test
```

Other returns: `NEEDS_HUMAN`, `NEEDS_CONTEXT`, `FAIL`, `OK PAUSE: needs-human — <one-line>` (do NOT transition).

---

## Hard rules (all three variants)

- **Verify evidence is mandatory** (`_handoff.md` Section E): no "green" claim without the raw runner output; raw output wins over self-report.
- **No verification weakening** (INV2): the developer must not delete/skip/weaken tests to pass. If a test must change, it requires an explicit, justified reason surfaced to the human.
- **Conformance is by the tech-lead, not self-review** (roles don't self-check).
- **The external auditor (3.5a) never gates by itself and never edits.** It returns findings; Step 4's leader decides what blocks, what is recorded, and what is dismissed-with-reason. Its read-only status is **not** guaranteed by agent type (every available type retains Bash), so the mutation check around it is mandatory on **every** path — a before/after comparison of `git diff --numstat --no-renames <mb>` (by `(path, added, deleted)` triple) and the `??` lines of `git status --porcelain -uall`, with its limits stated where it is defined — it is a **tripwire, not a proof**, and the primary defence is an agent type without Edit/Write. A mutating auditor is a **failed scan**: discard its output, change nothing, escalate — never repair the tree automatically (INV3).
- **The `/gld review` adversarial scan is never removed or downgraded because this one exists.** It is the outside measurement of whether this step works; folding it in would destroy the only evidence that could justify keeping it.
- Artifacts/inputs pass as files; RESULT lines stay one line.
- **Slots only** — a variant may fill the Section A slots and add its own hard rules; it may not quietly re-word a spine step. Behavior (return tokens, labels, markers, tiers, retry bound, capture rules) is defined here, once.
