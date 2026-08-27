#!/usr/bin/env python3
"""Sprint dependency-graph calculator for `/gld sprint` (design: design/guild/02-sprint.md §5).

Why this is code and not a prompt: topological order, cycle detection, linearization,
base resolution and the plan-hash are *calculations*. Left to a prompt they cannot be
tested, can answer differently for the same input, and a missed cycle deadlocks an
unattended run. Precedents in this plugin: `scan_transcript.py`, `capture_signal.py`,
`gate_precommit.py`.

⚠ INTERFACE IS FILE-BASED, NOT STDIN. `_bash_rules.md` forbids pipes (FORBIDDEN 2) and
redirection (FORBIDDEN 7) in Bash *tool* calls, and its sanctioned python exception (:84)
is the flag form — both existing precedents are argparse-only with no stdin. Two callers,
two ways to produce the input file:
  - LLM caller (`sprint plan`)  — writes it with the Write tool.
  - shell caller (`sprint run`) — builds it inside the generated `.sh`, where redirection
    IS allowed (`_bash_rules.md:85` puts a generated script's own contents outside these
    rules). See §8.4c.

    python3 sprint_dag.py --input <path> --mode <mode>

Exit codes are deliberately distinct per meaning (§5.2). An earlier design draft overloaded
`2` for "cycle found", "unresolvable" and "bad JSON" at once — then an `--input` typo read
back as a cycle and the caller reported a cycle that did not exist.

    0   success
    2   cycle detected (linearize / order) · input not linearized (base)
    3   cycle detected (cycles — "found" is the exceptional answer for that mode)
    4   depth exceeds max_depth (depth)
    64  usage / input error (missing file, bad JSON, unknown mode, missing key)

Warnings (deps pointing outside the member set, extra markers, …) go to stderr; the
supervisor captures them into its log, an LLM caller sees them in the tool result.
"""

import sys

# Do not leave a __pycache__ behind. `.gitignore` already keeps one out of the REPOSITORY
# (`__pycache__/`, line 1 — verified: `git ls-files` tracks no .pyc), so this is about not
# writing the directory into the user's checkout at all: this module is imported by
# tests/sprint_dag_test.sh, and a stale .pyc beside a plugin file that gets updated in place
# is a confusing thing to find. Stated as the goal rather than copied from
# `gate_precommit.py`'s temporary-toggle form, which restores the flag afterwards.
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import re

EXIT_OK = 0
EXIT_CYCLE = 2
EXIT_NOT_LINEARIZED = 2
EXIT_CYCLE_FOUND = 3
EXIT_DEPTH_EXCEEDED = 4
EXIT_USAGE = 64

_MISSING = object()      # distinguishes an absent key from a present-but-empty one

PLAN_OPEN = "<!-- guild:sprint:plan -->"
PLAN_CLOSE = "<!-- /guild:sprint:plan -->"

TERMINAL_BLOCKING = ("needs-human", "failed")


def warn(msg):
    print("sprint_dag: %s" % msg, file=sys.stderr)


def die(msg):
    print("sprint_dag: %s" % msg, file=sys.stderr)
    raise SystemExit(EXIT_USAGE)


# ─────────────────────────────────────────────────────────────────────────────
# Input
# ─────────────────────────────────────────────────────────────────────────────

def load(path):
    if not os.path.isfile(path):
        die("--input not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        die("--input is not valid JSON (%s): %s" % (exc, path))
    if not isinstance(data, dict):
        die("--input must be a JSON object, got %s" % type(data).__name__)
    return data


def members_of(data, dep_key):
    """Return (nodes, deps) reading either `deps` (declared) or `base_deps` (linearized).

    Members whose deps point outside the member set are warned about and those edges are
    dropped — you cannot wait on an Issue that is not in the sprint. If it is already
    finished, dropping is correct; if it is unfinished, `plan` should have included it.
    """
    raw = data.get("members")
    if not isinstance(raw, list) or not raw:
        die("`members` must be a non-empty list")
    nodes, deps, missing_key = [], {}, []
    for m in raw:
        if not isinstance(m, dict) or "number" not in m:
            die("each member needs a `number`: %r" % (m,))
        try:
            n = int(m["number"])
        except (TypeError, ValueError):
            die("member `number` must be an integer: %r" % (m["number"],))
        if n in deps:
            die("duplicate member #%d" % n)
        nodes.append(n)
        # ⚠ A key that is ABSENT is not the same as an empty list. `m.get(dep_key) or []` read
        # both as "no dependencies", so passing the pre-linearization file (which has `deps`
        # but not yet `base_deps`) made `order` return plain issue-number order, `depth` return
        # 1, and `base` return DEFAULT for every member — all with exit 0. Measured; it is the
        # most dangerous shape this script can be given, because nothing warns.
        val = m.get(dep_key, _MISSING)
        if val is _MISSING:
            missing_key.append(n)
            val = []
        elif not isinstance(val, list):
            die("member #%d's `%s` must be a list, got %r" % (n, dep_key, val))
        parsed = []
        for d in val:
            # bool is an int subclass; a JSON `true` here means the caller built the wrong shape.
            if isinstance(d, bool) or not isinstance(d, (int, str)):
                die("member #%d's `%s` entries must be issue numbers, got %r" % (n, dep_key, d))
            try:
                parsed.append(int(d))
            except ValueError:
                die("member #%d's `%s` entries must be issue numbers, got %r" % (n, dep_key, d))
        deps[n] = parsed
    if missing_key and len(missing_key) == len(nodes):
        die("no member carries `%s`, which this mode reads. Absence is not \"no dependencies\" "
            "— returning that would be a silent wrong answer. Did you pass the "
            "pre-linearization input? Run --mode linearize and write its output back as "
            "`base_deps` first." % dep_key)
    if missing_key:
        warn("%s missing `%s` — treated as no dependencies: %s"
             % (len(missing_key), dep_key, ", ".join("#%d" % n for n in missing_key)))
    inside = set(nodes)
    for n in nodes:
        kept, dropped = [], []
        for d in deps[n]:
            (kept if d in inside else dropped).append(d)
        if dropped:
            warn("#%d: dep(s) outside the sprint ignored: %s"
                 % (n, ", ".join("#%d" % d for d in dropped)))
        # self-dep would be a 1-cycle; drop it loudly rather than reporting a cycle
        if n in kept:
            warn("#%d depends on itself — ignored" % n)
            kept = [d for d in kept if d != n]
        deps[n] = sorted(set(kept))
    return nodes, deps


# ─────────────────────────────────────────────────────────────────────────────
# Graph primitives
# ─────────────────────────────────────────────────────────────────────────────

def topo(nodes, deps):
    """Kahn's algorithm. Tie-break by issue number ascending, so the same plan always
    yields the same order — that is what makes a resumed run reproducible (§8.6 step 6).
    Returns None when a cycle is present."""
    indeg = {n: 0 for n in nodes}
    adj = {n: [] for n in nodes}
    for x, ds in deps.items():
        for d in ds:
            adj[d].append(x)
            indeg[x] += 1
    ready = sorted(n for n in nodes if indeg[n] == 0)
    out = []
    while ready:
        n = ready.pop(0)
        out.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort()
    return out if len(out) == len(nodes) else None


def find_cycles(nodes, deps):
    """Return one simple cycle per strongly-connected component, as a readable path.
    We report a witness rather than every cycle: a human resolving it needs one concrete
    loop, and enumerating all of them in a dense graph is unbounded."""
    colour = {n: 0 for n in nodes}   # 0 unvisited · 1 on stack · 2 done
    stack = []
    found = []

    def visit(n):
        colour[n] = 1
        stack.append(n)
        for d in deps.get(n, ()):
            if colour[d] == 1:
                i = stack.index(d)
                found.append(stack[i:] + [d])
                return True
            if colour[d] == 0 and visit(d):
                return True
        stack.pop()
        colour[n] = 2
        return False

    sys.setrecursionlimit(max(1000, len(nodes) * 10))
    for n in sorted(nodes):
        if colour[n] == 0:
            visit(n)
    return found


def linearize(nodes, deps0):
    """Turn fan-in into pure chains by ADDING edges, never by reassigning an assignment.

    ⚠ This is the corrected algorithm. An earlier design draft said "chain the remaining
    deps by reassigning each one's base_dep to the previous one" — and reassigning a node
    that already had a base_dep DROPS that node's own dependency from the chain. Measured
    over every DAG: 6% loss at N=4, 19% at N=5, 35% at N=6, 50% at N=7 — and most losses
    sat *under* the depth cap, so no warning fired either.

    Here: while some node's deps are not totally ordered, add the missing edge between
    consecutive deps (in topological order) and repeat. Added edges always run
    earlier→later, so no cycle can be introduced. At the fixpoint every node's deps form
    a chain, so the single latest dep is a descendant of all the others — one base_dep
    transitively covers them. Assignment happens once, at the end, and is never revised.

    Returns (base_dep, deps_after) or (None, None) on a cycle.
    """
    deps = {n: set(deps0.get(n, ())) for n in nodes}
    # Each pass adds at least one edge, and edges are bounded by n*(n-1)/2.
    for _ in range(len(nodes) * len(nodes) + 2):
        order = topo(nodes, deps)
        if order is None:
            return None, None
        pos = {n: i for i, n in enumerate(order)}
        added = False
        for x in order:
            chain = sorted(deps[x], key=lambda d: pos[d])
            for a, b in zip(chain, chain[1:]):
                if a not in deps[b]:
                    deps[b].add(a)
                    added = True
        if not added:
            break
    else:
        die("linearize did not converge — this is a bug, please report the input")

    order = topo(nodes, deps)
    if order is None:
        return None, None
    pos = {n: i for i, n in enumerate(order)}
    base = {}
    for x in order:
        chain = sorted(deps[x], key=lambda d: pos[d])
        base[x] = chain[-1] if chain else None
    return base, deps


def ancestors(base, x):
    out, p, guard = [], base.get(x), 0
    while p is not None:
        out.append(p)
        p = base.get(p)
        guard += 1
        if guard > len(base) + 1:      # defensive: a malformed base map
            die("base_dep chain does not terminate at #%d" % x)
    return out


def verify_cover(nodes, deps0, base):
    """Post-check (§5.4a step 3) — MANDATORY, not optional.

    For every declared dep of every node, that dep must be an ancestor in the base_dep
    forest. Without this the per-graph expectations in §12.1 pass while dependencies are
    silently lost — which is exactly how the earlier algorithm's defect went unnoticed.
    """
    missing = []
    for x in nodes:
        anc = set(ancestors(base, x))
        for d in deps0.get(x, ()):
            if d not in anc:
                missing.append((x, d))
    return missing


def chain_depths(nodes, base):
    return {n: len(ancestors(base, n)) + 1 for n in nodes}


def base_map_from(data):
    """Build base_dep from `base_deps`, rejecting non-linearized input.

    `base` mode must not silently fall back to picking one of several deps — that is the
    merge-fallback the design withdrew (D9). Two or more means the caller skipped
    `linearize`, which is a caller bug worth failing on.
    """
    nodes, bd = members_of(data, "base_deps")
    base = {}
    for n in nodes:
        if len(bd[n]) > 1:
            print("sprint_dag: #%d has %d base_deps (%s) — input was not linearized; "
                  "run --mode linearize first" % (n, len(bd[n]),
                                                 ", ".join("#%d" % d for d in bd[n])),
                  file=sys.stderr)
            raise SystemExit(EXIT_NOT_LINEARIZED)
        base[n] = bd[n][0] if bd[n] else None
    return nodes, base


# ─────────────────────────────────────────────────────────────────────────────
# PR / branch state
# ─────────────────────────────────────────────────────────────────────────────

def pr_index(data):
    """issue -> PR state, issue -> head branch, issue -> ambiguous head branches.

    The third value names issues whose most-final state is held by MORE THAN ONE PR with
    DIFFERENT heads. Picking one is a guess, and this module refuses to guess (`resolve_base`
    answers dep-branch-ambiguous for the same shape) — but this function used to take whichever
    arrived first, so the answer depended on the order `gh` happened to return. Measured:
    reversing the input flipped a dependant's base between the real branch and an abandoned one.
    """
    state, branch, rival = {}, {}, {}
    for pr in data.get("prs") or []:
        if not isinstance(pr, dict) or "issue" not in pr:
            die("each `prs` entry needs an `issue`: %r" % (pr,))
        try:
            i = int(pr["issue"])
        except (TypeError, ValueError):
            die("`prs[].issue` must be an integer: %r" % (pr["issue"],))
        st = str(pr.get("state", "")).upper()
        if st not in ("MERGED", "OPEN", "CLOSED"):
            die("`prs[].state` for #%d must be MERGED|OPEN|CLOSED, got %r" % (i, pr.get("state")))
        # A later entry wins only if it is "more final" — an issue can carry several PRs
        # (a closed first attempt plus the real one). MERGED > OPEN > CLOSED.
        rank = {"CLOSED": 0, "OPEN": 1, "MERGED": 2}
        if i not in state or rank[st] > rank[state[i]]:
            state[i] = st
            rival.pop(i, None)
            # The branch must be REPLACED, not just overwritten-when-present. A CLOSED first
            # attempt seen earlier left its dead branch in place, so a later OPEN PR recorded
            # without a head branch returned that abandoned branch as the base — this Issue's
            # PR would stack on work the human explicitly rejected, instead of reporting
            # BLOCKED:dep-pr-no-branch. Measured.
            branch.pop(i, None)
            if pr.get("branch"):
                branch[i] = str(pr["branch"])
        elif i in state and st == state[i] and pr.get("branch"):
            b = str(pr["branch"])
            if i not in branch:
                branch[i] = b
            elif branch[i] != b:
                rival.setdefault(i, set()).update((branch[i], b))
    ambiguous = {i: sorted(v) for i, v in rival.items()}
    for i in sorted(ambiguous):
        warn("#%d has %d PRs in state %s with different head branches: %s"
             % (i, len(ambiguous[i]), state[i], ", ".join(ambiguous[i])))
    return state, branch, ambiguous


def split_done_set(data):
    """Members that completed via a design-time split (§8.7).

    Such a parent reaches `guild:done` with NO branch and NO PR of its own — its children
    carry those. Treating it by the plain "no PR, no branch -> BLOCKED" rule would turn a
    *completed* Issue into a downstream blocker. The caller detects the split (the
    `<!-- guild:children:output -->` comment) and marks the member `"split": true`; this
    script cannot read GitHub.
    """
    out = set()
    for m in data.get("members") or []:
        if isinstance(m, dict) and m.get("split"):
            try:
                out.add(int(m["number"]))
            except (TypeError, ValueError):
                pass
    return out


def resolve_base(dep, state, branch, branches, split, ambiguous=None):
    """§5.3. Returns (token, reason|None). Token is a branch name, 'DEFAULT', or 'BLOCKED'."""
    if dep is None:
        return "DEFAULT", None
    if dep in split:
        # Completed-by-split parent: nothing to stack on, and nothing is wrong.
        return "DEFAULT", None
    st = state.get(dep)
    # ⚠ ORDER MATTERS, and getting it wrong made a LANDED dependency a permanent blocker.
    # Ambiguity is only a problem when a BRANCH has to be picked — i.e. only for OPEN. When the
    # state is MERGED there is nothing to pick: the work is in, and the answer is DEFAULT
    # whether one PR landed it or three did. When it is CLOSED the human rejected the work, and
    # `dep-pr-closed` is the prescription; `dep-pr-ambiguous` would tell them to rename a
    # branch instead. Checking `ambiguous` first returned dep-pr-ambiguous for two MERGED PRs
    # (a revert + a re-land, or a hotfix that also says `Closes #N`) and nothing the human could
    # do would clear it — the branches are already merged.
    if st == "MERGED":
        return "DEFAULT", None
    if st == "CLOSED":
        return "BLOCKED", "dep-pr-closed"
    if st == "OPEN":
        if ambiguous and dep in ambiguous:
            # Same state, different heads — the shape the branch-inventory fallback below also
            # refuses. Answering would be a coin flip on which branch to stack onto.
            return "BLOCKED", "dep-pr-ambiguous"
        b = branch.get(dep)
        return (b, None) if b else ("BLOCKED", "dep-pr-no-branch")
    # No PR recorded for the dep. ⚠ There is deliberately NO `branch.get(dep)` lookup here:
    # `branch` only ever has keys that `state` also has, so in this path it is always empty for
    # `dep`. An earlier version checked it anyway — dead code that read as a second, more
    # trustworthy source than it was. The local-branch inventory below is the real fallback.
    cand = [x for x in branches if re.search(r"(?<!\d)%d(?!\d)" % dep, x)]
    if len(cand) == 1:
        # Fallback for an empty `closingIssuesReferences` (§5.3): match the issue number
        # as a token in a local branch name. Ambiguous matches are NOT guessed.
        return cand[0], None
    if len(cand) > 1:
        return "BLOCKED", "dep-branch-ambiguous"
    return "BLOCKED", "dep-no-branch"


# ─────────────────────────────────────────────────────────────────────────────
# Modes
# ─────────────────────────────────────────────────────────────────────────────

def mode_linearize(data):
    nodes, deps0 = members_of(data, "deps")
    base, _ = linearize(nodes, deps0)
    if base is None:
        warn("cycle detected — run --mode cycles for the path")
        return EXIT_CYCLE
    missing = verify_cover(nodes, deps0, base)
    if missing:
        # Should be unreachable. If it ever fires, the algorithm regressed and the run
        # must stop rather than open PRs on bases that omit declared dependencies.
        for x, d in missing:
            warn("INVARIANT VIOLATION: #%d's dep #%d is not an ancestor of its base_dep" % (x, d))
        return EXIT_CYCLE
    for n in sorted(nodes):
        print("%d %s" % (n, base[n] if base[n] is not None else "-"))
    return EXIT_OK


def mode_order(data):
    nodes, bd = members_of(data, "base_deps")
    order = topo(nodes, bd)
    if order is None:
        warn("cycle detected in base_deps — run --mode cycles for the path")
        return EXIT_CYCLE
    for n in order:
        print(n)
    return EXIT_OK


def mode_cycles(data):
    nodes, deps = members_of(data, "deps")
    cycles = find_cycles(nodes, deps)
    if not cycles:
        return EXIT_OK
    for path in cycles:
        print(" -> ".join("#%d" % n for n in path))
    return EXIT_CYCLE_FOUND


def mode_depth(data):
    nodes, base = base_map_from(data)
    depths = chain_depths(nodes, base)
    worst = max(depths.values()) if depths else 0
    print("depth %d" % worst)
    limit = data.get("max_depth")
    over = []
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            die("`max_depth` must be an integer, got %r" % (data["max_depth"],))
        # Report each maximal over-limit chain once, from its tip.
        tips = [n for n in nodes if n not in set(v for v in base.values() if v is not None)]
        for t in sorted(tips):
            if depths[t] > limit:
                chain = list(reversed([t] + ancestors(base, t)))
                over.append(chain)
    for chain in over:
        print("chain %s" % ",".join(str(n) for n in chain))
    return EXIT_DEPTH_EXCEEDED if over else EXIT_OK


def mode_base(data):
    nodes, base = base_map_from(data)
    state, branch, pr_ambig = pr_index(data)
    branches = set(str(b) for b in (data.get("branches") or []))
    # `default_branch` is NOT read: `DEFAULT` is a token and the caller adds the `origin/`
    # prefix (_sprint_dag.md Section D), so this mode never needs the name. It was a required
    # key that was validated and then ignored — accepted when present, no longer demanded.
    split = split_done_set(data)
    for n in sorted(nodes):
        token, reason = resolve_base(base[n], state, branch, branches, split, pr_ambig)
        if token == "BLOCKED":
            print("%d BLOCKED:%s" % (n, reason))
        else:
            print("%d %s" % (n, token))
    return EXIT_OK


def mode_blocked(data):
    """Transitively blocked members, with the originating reason.

    Direct causes: the dep is paused/failed, its PR was closed by a human, or its base
    cannot be resolved at all. Anything downstream of those is blocked too — starting it
    would branch off something that is not going to land.
    """
    nodes, base = base_map_from(data)
    state, branch, pr_ambig = pr_index(data)
    branches = set(str(b) for b in (data.get("branches") or []))
    split = split_done_set(data)
    terminal = {}
    for k, v in (data.get("terminal") or {}).items():
        try:
            terminal[int(k)] = str(v)
        except (TypeError, ValueError):
            die("`terminal` keys must be issue numbers, got %r" % (k,))

    # ⚠ A MERGED PR outranks a recorded failure, HERE TOO. `resolve_base` learned this but
    # `mode_blocked` reads `terminal` directly, so the two modes contradicted each other on the
    # same input: `base` answered DEFAULT (the work is in) while `blocked` answered
    # `dep-failed:#N` — and the supervisor believes `blocked`, so a landed dependency blocked its
    # dependants on every pass with nothing the human could do about it. The supervisor's own
    # input builder applies this rule; a caller that assembles `terminal` by hand (daily, a
    # test) must not be able to defeat it.
    for n in [i for i, v in terminal.items() if v == "failed"]:
        if state.get(n) == "MERGED":
            del terminal[n]

    # Process in chain order so a dep's status is final before its child is judged.
    # ⚠ `upstream` must WIN over a node's own direct reason. Reporting #103 as
    # "dep-no-branch:#102" when #102 is itself blocked hides the root cause (#101 needs a
    # human) behind a symptom — and the whole point of this mode is to let the human see
    # the cause. Found by the test, not by reading.
    order = topo(nodes, {n: ([base[n]] if base[n] is not None else []) for n in nodes})
    if order is None:
        # NOT a usage error: the input is well-formed and the graph is the problem. 64 would
        # read as "bad JSON / bad flag", and the supervisor treats an unparsed `blocked` result
        # as "nothing blocked" — it would then run every member on top of a cyclic mess.
        print("sprint_dag: base_deps contain a cycle — run --mode cycles", file=sys.stderr)
        raise SystemExit(EXIT_CYCLE)

    blocked = {}
    for n in order:
        dep = base[n]
        if dep is None:
            continue
        if dep in blocked:
            blocked[n] = "upstream:#%d" % dep
            continue
        t = terminal.get(dep)
        if t in TERMINAL_BLOCKING:
            blocked[n] = "dep-%s:#%d" % (t, dep)
            continue
        token, reason = resolve_base(dep, state, branch, branches, split, pr_ambig)
        if token == "BLOCKED":
            blocked[n] = "%s:#%d" % (reason, dep)

    for n in sorted(blocked):
        print("%d %s" % (n, blocked[n]))
    return EXIT_OK


def mode_hash(data):
    """§4.6 — the one verbatim algorithm. No other reading is permitted.

    Six plausible readings of the earlier prose ("the sha256 of this block, minus the hash
    line") produced six different values, and the failure direction is a full stop of every
    unattended resume — so the normalisation is spelled out and computed in exactly one
    place, reachable from both the LLM caller and the shell.
    """
    text = data.get("text")
    if not isinstance(text, str) or not text:
        die("`text` (the tracking Issue body) is required for --mode hash")
    if PLAN_OPEN not in text or PLAN_CLOSE not in text:
        die("`text` does not contain the %s … %s marker pair" % (PLAN_OPEN, PLAN_CLOSE))
    # Presence is not order. With CLOSE before OPEN the split below silently hashes everything
    # AFTER the closing marker, so unrelated later edits to the Issue body change the value.
    if text.index(PLAN_CLOSE) < text.index(PLAN_OPEN):
        die("the closing plan marker precedes the opening one — the tracking Issue body is malformed")
    if text.count(PLAN_OPEN) > 1 or text.count(PLAN_CLOSE) > 1:
        warn("more than one plan marker found — using the first pair")
    inner = text.split(PLAN_OPEN, 1)[1].split(PLAN_CLOSE, 1)[0]
    lines = inner.split("\n")
    # The marker lines themselves are excluded by the split above. Strip EVERY leading and
    # trailing blank line, not one each: stripping one meant adding a second blank line after
    # the opening marker changed the hash, so a human tidying whitespace in the tracking Issue
    # halted every unattended resume with `plan-hash-mismatch` — the exact failure §4.6 exists
    # to prevent. Trailing whitespace and CR are already normalised below; blank lines are the
    # same class of pure-formatting edit and are treated the same way.
    while lines and lines[0].strip() == "":
        lines = lines[1:]
    while lines and lines[-1].strip() == "":
        lines = lines[:-1]
    kept = []
    for ln in lines:
        if ln.lstrip().startswith("plan-hash:"):
            continue                      # removed, not blanked
        kept.append(ln.replace("\r", "").rstrip())
    payload = "\n".join(kept)             # no trailing newline
    print(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12])
    return EXIT_OK


MODES = {
    "linearize": mode_linearize,
    "order": mode_order,
    "cycles": mode_cycles,
    "depth": mode_depth,
    "base": mode_base,
    "blocked": mode_blocked,
    "hash": mode_hash,
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="sprint_dag.py",
        description="Sprint dependency-graph calculator (design: 02-sprint.md §5).",
    )
    ap.add_argument("--input", required=True, metavar="PATH",
                    help="JSON input file (schema: 02-sprint.md §5.2)")
    ap.add_argument("--mode", required=True, choices=sorted(MODES),
                    help="calculation to run")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        # argparse exits 2 on a usage error; remap so it cannot be mistaken for "cycle".
        # ⚠ Only remap FAILURES: `--help` and `--version` also raise SystemExit, with code 0,
        # and reporting a help request as an input error is wrong.
        raise SystemExit(EXIT_OK if e.code in (0, None) else EXIT_USAGE)
    return MODES[args.mode](load(args.input))


if __name__ == "__main__":
    raise SystemExit(main())
