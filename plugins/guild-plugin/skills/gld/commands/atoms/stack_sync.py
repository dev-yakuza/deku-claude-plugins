#!/usr/bin/env python3
"""stack_sync.py — keep a sprint's PR stack reviewable after a squash/rebase merge.

Design: design/guild/09-squash-stack.md. Contract: _sprint_dag.md Section G.

When a stacked member's dependency is merged WITHOUT a merge commit, the dependency's commits are
not ancestors of the default branch, so the member's PR shows them again. Merging the default
branch into the member's branch (a new merge commit — no rebase, no force: INV3) moves the merge
base past the squash commit and the diff is the member's own work again.

That is done automatically ONLY when it needs no judgment: the member already holds the
dependency's own work (what the dependency gained after the member's cut is only clean merges of
default-branch content) and that work is still intact on the default branch, so the merge brings
in nothing but reviewed, merged content. If the dependency's work changed after the member was
cut, that is a catch-up (`stale`) and stays the human's (daily.md: never auto-catch-up a stale
base).

Usage:
  python3 stack_sync.py --tracker <n> [--check] [--install-cmd <cmd>]...

Run from the human's checkout. Output, one line per stacked member whose dependency merged and
whose own PR is open (`--check` omits lines with nothing to act on):

  <issue> clean #<dep> none               dep merged with a merge commit; nothing to do (a draft
                                          to retarget/ready is reported as `synced`)
  <issue> stale #<dep>                    dep's own work changed after this member was cut — human
  <issue> diverged #<dep> <reason>        the dep's work is no longer intact on the default branch
                                          (reverted, re-landed without part of it) — human
  <issue> ambiguous #<dep> <reason>       cannot tell which PR/branch — human
  <issue> needs-sync #<dep> <actions>     --check only: what a sync would do (merge,retarget,ready;
                                          `held` = it will then report draft-held)
                                          (--check applies the same skipped-gates as a sync)
  <issue> synced #<dep> <actions|none>    what this call did
  <issue> draft-held #<dep> pr=<n>        brought level by a merge this script did not make, or
                                          holds a human's edited merge: the human readies it
  <issue> skipped #<dep> <reason>         not-done | branch-checked-out | head-moved
  <issue> conflict #<dep> <paths>         the merge conflicted; nothing pushed
  <issue> verify-failed #<dep> <log>      verification failed or rewrote a file; nothing pushed
  <issue> push-rejected #<dep> <log>      nothing changed on the remote
  <issue> error #<dep> <message>          anything else; the member is left as it was
  <issue> worktree-kept #<dep> <path>     extra line: the throwaway worktree was not clean

Exit: 0 (the lines carry the outcome) · 64 usage/input error · 65 GitHub/git unavailable.
"""

import sys

# Same reason as sprint_dag.py: no __pycache__ beside a plugin file updated in place.
sys.dont_write_bytecode = True

import argparse
import json
import os
import re
import subprocess
import tempfile
import time

EXIT_USAGE = 64
EXIT_ENV = 65

PLAN_OPEN = "<!-- guild:sprint:plan -->"
PLAN_CLOSE = "<!-- /guild:sprint:plan -->"
STACK_MARKER = "<!-- guild:sprint:stack -->"
TRAILER = "Guild-Sync"
BASE_TRAILER = "Guild-Sync-Base"

# init.md:163's ban list — the same character class render_supervisor.py enforces before the
# supervisor `eval`s a config command (tests/stack_sync_test.sh asserts the two are identical).
_METACHAR = re.compile(r"\$\(|`|&&|\|\||[|;<>&\n]")
_ROW = re.compile(r"^\|[^|]*\|\s*#(\d+)[^|]*\|([^|]*)\|", re.M)


class EnvError(Exception):
    pass


def die(msg, code=EXIT_USAGE):
    sys.stderr.write("stack_sync: %s\n" % msg)
    raise SystemExit(code)


def run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def git(cwd, *args):
    return run(["git", "-C", cwd] + list(args))


def git_out(cwd, *args):
    p = git(cwd, *args)
    if p.returncode != 0:
        raise EnvError("git %s: %s" % (" ".join(args[:2]), (p.stderr or p.stdout).strip()[:200]))
    return p.stdout.strip()


def gh_json(args):
    p = run(["gh"] + args)
    if p.returncode != 0:
        raise EnvError("gh %s: %s" % (" ".join(args[:2]), p.stderr.strip()[:200]))
    try:
        return json.loads(p.stdout or "null")
    except ValueError:
        raise EnvError("gh %s returned non-JSON" % " ".join(args[:2]))


def is_ancestor(cwd, a, b):
    rc = git(cwd, "merge-base", "--is-ancestor", a, b).returncode
    if rc not in (0, 1):
        raise EnvError("merge-base --is-ancestor %s %s failed" % (a[:12], b[:12]))
    return rc == 0


def has_commit(cwd, sha):
    return git(cwd, "cat-file", "-e", sha + "^{commit}").returncode == 0


# ─────────────────────────────────────────────────────────────────────────────
# Inputs
# ─────────────────────────────────────────────────────────────────────────────

def parse_members(body):
    """Member table (the immutable plan block) -> [(issue, base_dep or None)] in table order.

    The `base 의존` column is the linearized value — the only edge source at run time
    (_sprint_dag.md Section B). Columns are positional, so a localized header does not matter.
    """
    start = body.find(PLAN_OPEN)
    end = body.find(PLAN_CLOSE, start + 1)
    if start < 0 or end < 0:
        die("tracker body has no %s … %s block" % (PLAN_OPEN, PLAN_CLOSE))
    out = []
    for m in _ROW.finditer(body[start:end]):
        dep = re.search(r"#(\d+)", m.group(2))
        out.append((int(m.group(1)), int(dep.group(1)) if dep else None))
    if not out:
        die("member table in the tracker body has no rows")
    return out


def prs_by_issue(prs_raw, members):
    """issue -> [pr]. Same attribution as the run supervisor's refresh_dag_input:
    closingIssuesReferences first, else a unique issue-number token in the head branch."""
    nums = set(members)
    out = {}
    for pr in prs_raw or []:
        state = "MERGED" if pr.get("mergedAt") else str(pr.get("state", "")).upper()
        if state not in ("MERGED", "OPEN", "CLOSED"):
            continue
        pr = dict(pr, state=state)
        issues = [int(r["number"]) for r in (pr.get("closingIssuesReferences") or [])]
        if not issues:
            head = pr.get("headRefName") or ""
            issues = [n for n in nums if re.search(r"(?<!\d)%d(?!\d)" % n, head)]
            if len(issues) != 1:
                continue
        for n in issues:
            if n in nums:
                out.setdefault(n, []).append(pr)
    return out


def single(prs, state, key):
    """The one PR in `state`, or (None, reason). Two with different `key` values is ambiguity,
    which this module refuses to guess (the same rule as sprint_dag.py's dep-pr-ambiguous)."""
    hits = [p for p in prs if p["state"] == state]
    if not hits:
        return None, None
    vals = set(key(p) for p in hits)
    if len(vals) > 1:
        return None, "%d-%s-prs" % (len(hits), state.lower())
    return hits[0], None


def pick_dep_pr(top, merged, m_head):
    """The dependency's merged PR this member was built on. Two MERGED PRs (a revert + re-land,
    a hotfix that also says `Closes #N`) are not ambiguity — both landed (sprint_dag.py's
    resolve_base makes the same call). Prefer those whose head the member contains, then the
    latest merge; a member containing none of them classifies as stale, which is the truth."""
    if len(merged) == 1:
        return merged[0]
    for p in merged:
        if p.get("headRefOid"):
            ensure_commit(top, p["headRefOid"], p["number"])
    anc = [p for p in merged if p.get("headRefOid") and is_ancestor(top, p["headRefOid"], m_head)]
    return sorted(anc or merged, key=lambda p: p.get("mergedAt") or "")[-1]


def merge_oid(pr):
    return (pr.get("mergeCommit") or {}).get("oid") or ""


def load_verify_cmds(top):
    """config.commands test · lint · typecheck (each a string, an array of steps, or null)."""
    path = os.path.join(top, ".claude", "guild", "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cmds = (json.load(fh) or {}).get("commands") or {}
    except (OSError, ValueError) as exc:
        die("cannot read %s (%s)" % (path, exc))
    out = []
    for key in ("test", "lint", "typecheck"):
        v = cmds.get(key)
        for c in (v if isinstance(v, list) else [v]):
            if isinstance(c, str) and c.strip():
                out.append(c)
    if not out:
        # Pushing an unverified merge is the one thing this script must not do quietly.
        die("config.commands has no test/lint/typecheck command — refusing to sync unverified")
    return out


def check_simple(cmds, what):
    for c in cmds:
        if not c.strip():
            die("%s must not be empty" % what)
        if _METACHAR.search(c):
            die("%s %r contains shell metacharacters (init.md:163)" % (what, c))


# ─────────────────────────────────────────────────────────────────────────────
# Classification (shared by --check and apply)
# ─────────────────────────────────────────────────────────────────────────────

def ensure_commit(top, sha, pr_number):
    """GitHub keeps every PR head under refs/pull/<n>/head, even after the branch is deleted."""
    if not has_commit(top, sha):
        git(top, "fetch", "--quiet", "origin", "refs/pull/%d/head" % pr_number)
        if not has_commit(top, sha):
            raise EnvError("head %s of PR #%d not available locally or from refs/pull"
                           % (sha[:12], pr_number))


def clean_merge(top, sha, onto):
    """True for an unedited, conflict-free two-parent merge whose second parent is already in
    `onto`, with exactly the tree git itself produces. Our own sync merge and GitHub's "Update
    branch" are such merges — they bring `onto`'s content and change nothing else. A merge whose
    result was edited (a conflict resolution), an octopus, or one bringing in another branch is
    not."""
    parents = git_out(top, "show", "-s", "--format=%P", sha).split()
    if len(parents) != 2 or not is_ancestor(top, parents[1], onto):
        return False
    want = git_out(top, "rev-parse", sha + "^{tree}")
    if merge_tree(top, parents[0], parents[1]) == want:
        return True
    # Our own sync merge was built against a recorded cut point (sync_tree), which git's natural
    # base cannot reproduce after a squash. Re-derive it from that base — only a base inside the
    # first parent's history counts, so a typed trailer cannot whitelist arbitrary content.
    base = git_out(top, "show", "-s", "--format=%(trailers:key=" + BASE_TRAILER + ",valueonly)",
                   sha).strip()
    if not re.match(r"\A[0-9a-f]{40}\Z", base) or not is_ancestor(top, base, parents[0]):
        return False
    p = git(top, "merge-tree", "--write-tree", "--merge-base=" + base, parents[0], parents[1])
    return p.returncode == 0 and p.stdout.split()[:1] == [want]


def merge_tree(top, a, b):
    """Tree of a clean merge of a and b, or None (conflict, or git < 2.38 — be strict)."""
    p = git(top, "merge-tree", "--write-tree", a, b)
    return p.stdout.split()[0] if p.returncode == 0 and p.stdout.split() else None


def sync_tree(top, cut, m_head, ref_default):
    """-> (tree, conflicted paths). The sync merge, computed with the member's CUT POINT on the
    dependency as the merge base. After a squash, git's own merge base is the default branch as
    it was before the dependency landed, so every file the dependency added or touched and the
    member then edited is an add/add or overlapping-hunk conflict — the common stack shape.
    Against the cut point, "ours" is exactly the member's own work and "theirs" is what the
    default branch did since (the squashed dependency included), so the result is the default
    branch plus the member's work. Needs git >= 2.40 (`--merge-base`)."""
    p = git(top, "merge-tree", "--write-tree", "--name-only", "--no-messages",
            "--merge-base=" + cut, m_head, ref_default)
    lines = p.stdout.split("\n")
    if p.returncode == 0 and lines[0].strip():
        return lines[0].strip(), []
    if p.returncode == 1 and lines[0].strip():
        return None, sorted(set(l for l in lines[1:] if l.strip()))
    raise EnvError("git merge-tree --merge-base failed (git >= 2.40 required): %s"
                   % (p.stderr.strip() or p.stdout.strip())[:160])


def cut_point(top, h_d, m_head):
    """Where the member was cut off the dependency: the single merge base, or — with several —
    the newest commit on the dependency's own first-parent line that the member contains. Not
    git's pick among several: once both merged the default branch (the member directly, the
    dependency via "Update branch"), git may pick a default-branch commit — a default-branch commit makes the cut-point merge re-add what
    the member deleted from the dependency's files, or conflict on what it edited."""
    bases = git_out(top, "merge-base", "--all", h_d, m_head).split()
    if len(bases) == 1:
        return bases[0]
    for sha in git_out(top, "rev-list", "--first-parent", h_d).split():
        if is_ancestor(top, sha, m_head):
            return sha
    raise EnvError("member shares no commit with the dependency's own line")


def classify(top, default, dep_pr, m_head):
    """-> (status, detail). See design/guild/09-squash-stack.md §3."""
    h_d, s = dep_pr.get("headRefOid") or "", merge_oid(dep_pr)
    if not h_d or not s:
        return "ambiguous", "dep-pr-without-head-or-merge-commit"
    if dep_pr.get("baseRefName") != default:
        # Merged into another branch (out of order). Merging the default branch would not bring
        # its squash commit in, so "sync" would mean nothing — the human sorts out the order.
        return "ambiguous", "dep-merged-into-%s" % dep_pr.get("baseRefName")
    ensure_commit(top, h_d, dep_pr["number"])
    ref_default = "refs/remotes/origin/" + default
    if not has_commit(top, s) or not is_ancestor(top, s, ref_default):
        raise EnvError("merge commit %s of PR #%d is not on origin/%s (force-pushed?)"
                       % (s[:12], dep_pr["number"], default))
    if is_ancestor(top, s, m_head):
        return "synced", None
    # The dependency's own line of work after the member's cut (first parents only — what a
    # merge brought in through its second parent is not the dependency's own work). Anything
    # but clean merges of default-branch content means it changed after the member was cut —
    # also when it then landed with a merge commit.
    for sha in git_out(top, "rev-list", "--first-parent", h_d, "^" + m_head).split():
        if not clean_merge(top, sha, ref_default):
            return "stale", None
    if is_ancestor(top, h_d, ref_default):
        return "clean", None
    # The dependency's work must still be on the default branch: re-applying ALL of it (from
    # where it last met the default branch — right for squash, multi-commit and rebase merges)
    # must change nothing. A revert, or a re-land by another PR that dropped part of it, changes
    # something: the member was built on work the default branch no longer has. A conflict
    # proves nothing (later work legitimately edited those lines) — sync_tree and verification
    # then decide.
    base = git_out(top, "merge-base", h_d, ref_default)
    p = git(top, "merge-tree", "--write-tree", "--name-only", "--no-messages",
            "--merge-base=" + base, ref_default, h_d)
    lines = [l for l in p.stdout.split("\n") if l.strip()]
    if p.returncode not in (0, 1) or not lines:
        raise EnvError("git merge-tree --merge-base failed (git >= 2.40 required): %s"
                       % (p.stderr.strip() or p.stdout.strip())[:160])
    # A conflicted path proves nothing — later work may have edited those lines legitimately —
    # but it must not hide the rest: any OTHER path the re-apply would change is missing work.
    changed = git_out(top, "diff-tree", "-r", "--name-only", "--no-commit-id",
                      ref_default + "^{tree}", lines[0]).split("\n")
    if set(c for c in changed if c) - set(lines[1:]):
        return "diverged", "dep-not-intact-on-" + default
    tree, conflicts = sync_tree(top, cut_point(top, h_d, m_head), m_head, ref_default)
    if conflicts:
        return "conflict", ",".join(conflicts[:5]) + (",…" if len(conflicts) > 5 else "")
    return "needs-sync", None


def foreign_merge(top, m_head, h_d, ref_default):
    """A merge in the member's own range that is not a clean merge of the dependency or the
    default branch — a human's catch-up with a conflict edit. Its result never went through
    our verification or the auditor, so the draft is the human's to ready (`draft-held`; so is
    a draft brought level by any merge this script did not make — plan_actions)."""
    for sha in git_out(top, "rev-list", "--merges", m_head, "^" + h_d, "^" + ref_default).split():
        if not (clean_merge(top, sha, h_d) or clean_merge(top, sha, ref_default)):
            return True
    return False


def guild_synced(top, m_head, dep):
    """Did one of OUR merges bring the dependency in? Only then may a draft be marked ready —
    a human's own catch-up merge has not been re-verified (daily.md: re-enter /gld dev)."""
    log = git_out(top, "log", "--merges", "--format=%(trailers:key=" + TRAILER + ",valueonly)",
                  m_head)
    return any(l.strip() == "#%d" % dep for l in log.splitlines())


# ─────────────────────────────────────────────────────────────────────────────
# Apply
# ─────────────────────────────────────────────────────────────────────────────

def checked_out_branches(top):
    """branch -> the worktree path holding it."""
    held, path = {}, None
    for l in git_out(top, "worktree", "list", "--porcelain").splitlines():
        if l.startswith("worktree "):
            path = l[len("worktree "):]
        elif l.startswith("branch refs/heads/"):
            held[l[len("branch refs/heads/"):]] = path
    return held


def container_dir(top, tracker):
    """run.md's container: <repo-parent>/.gld-<repo-basename>-sprint-<tracker>, else $TMPDIR.
    Inside it, the run's `worktree prune` rule counts our worktree as its own."""
    name = ".gld-%s-sprint-%s" % (os.path.basename(top), tracker)
    for base in (os.path.dirname(top), tempfile.gettempdir()):
        path = os.path.join(base, name)
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            continue
    raise EnvError("no writable container directory for %s" % name)


def rmdir_quiet(path):
    try:
        os.rmdir(path)
    except OSError:
        pass


def run_logged(cmds, cwd, log):
    with open(log, "a", encoding="utf-8") as fh:
        for c in cmds:
            fh.write("$ %s\n" % c)
            fh.flush()
            # bash -c, like the supervisor's `eval`: globs/$VAR/~ expand; chaining was refused
            # above by the same character class.
            p = subprocess.run(["bash", "-c", c], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT)
            if p.returncode != 0:
                fh.write("exit %d\n" % p.returncode)
                return False
    return True


def merge_verify_push(ctx, issue, dep, branch, m_head, h_d):
    """Commit the sync merge (parents: the member's head and origin/<default>; tree: sync_tree),
    then verify it in a throwaway detached worktree and push it. -> (None, None) on success,
    else (status, detail). A merge commit like any other — never --force, never rebase (INV3)."""
    top, default = ctx["top"], ctx["default"]
    ref_default = "refs/remotes/origin/" + default
    cut = cut_point(top, h_d, m_head)
    tree, conflicts = sync_tree(top, cut, m_head, ref_default)
    if conflicts:
        return "conflict", ",".join(conflicts[:5]) + (",…" if len(conflicts) > 5 else "")
    msg = ("Merge %s into %s\n\n#%d landed on %s without a merge commit; this brings its squashed "
           "form in so the PR shows only #%d's own changes (gld sprint sync, tracker #%s).\n\n"
           "%s: #%d\n%s: %s\n" % (default, branch, dep, default, issue, ctx["tracker"],
                                   TRAILER, dep, BASE_TRAILER, cut))
    p = subprocess.run(["git", "-C", top, "commit-tree", tree, "-p", m_head, "-p", ref_default],
                       input=msg, capture_output=True, text=True)
    if p.returncode != 0:
        return "error", "commit-tree failed: %s" % p.stderr.strip()[:200]
    new = p.stdout.strip()
    wt = os.path.join(container_dir(top, ctx["tracker"]), "sync-%d" % issue)
    log = os.path.join(ctx["logdir"], "sync-%d-%s.log" % (issue, time.strftime("%Y%m%d-%H%M%S")))
    listed = git_out(top, "worktree", "list", "--porcelain").splitlines()
    if "worktree " + os.path.realpath(wt) in listed or "worktree " + wt in listed:
        if git(top, "worktree", "remove", wt).returncode != 0:      # a crashed earlier sync
            return "error", "leftover worktree %s is not clean — inspect and remove it" % wt
    elif os.path.exists(wt):
        return "error", "%s exists but is not a registered worktree — remove it" % wt
    if git(top, "worktree", "add", "--quiet", "--detach", wt, new).returncode != 0:
        rmdir_quiet(os.path.dirname(wt))
        return "error", "worktree add failed at %s" % wt
    try:
        os.makedirs(ctx["logdir"], exist_ok=True)
        if not run_logged(ctx["install"] + ctx["verify"], wt, log):
            return "verify-failed", log
        # What was verified must be what is pushed: a step that rewrote a tracked file (a
        # formatter run as lint, a lockfile refresh) verified a different tree.
        if git_out(wt, "status", "--porcelain", "--untracked-files=no"):
            return "verify-failed", "verification changed tracked files — %s" % log
        p = git(wt, "push", "origin", new + ":refs/heads/" + branch)
        if p.returncode != 0:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("$ git push origin %s:refs/heads/%s\n%s%s" % (new[:12], branch, p.stdout, p.stderr))
            return "push-rejected", log
        # Advance the local branch too (fast-forward only), or a later `/gld dev` re-entry would
        # push from the pre-sync tip. ⚠ Re-check NOW: install/verify took minutes, and moving a
        # branch someone checked out meanwhile would stage a reversal in their index.
        old = git(top, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch).stdout.strip()
        if old and branch not in checked_out_branches(top) and is_ancestor(top, old, new):
            git(top, "update-ref", "refs/heads/" + branch, new, old)
        return None, None
    finally:
        # Our own throwaway checkout: drop what install/verify left (coverage, junit, deps) so the
        # removal below needs no --force. Tracked changes were refused above, never cleaned here.
        git(wt, "clean", "-fdxq")
        if git(top, "worktree", "remove", wt).returncode != 0:          # never --force
            ctx["notes"].append("%d worktree-kept #%d %s" % (issue, dep, wt))
        rmdir_quiet(os.path.dirname(wt))           # the container, only if nothing else is in it


def sync_member(ctx, issue, dep, m_pr, branch, m_head, h_d, actions):
    """merge (+verify +push), then retarget, then ready — in that order, so a PR is never
    marked ready on a diff that has not been fixed. -> (status, detail)."""
    done = []
    if "merge" in actions:
        status, detail = merge_verify_push(ctx, issue, dep, branch, m_head, h_d)
        if status:
            return status, detail
        done.append("merge")
    for action, cmd in (("retarget", ["edit", str(m_pr["number"]), "--base", ctx["default"]]),
                        ("ready", ["ready", str(m_pr["number"])])):
        if action not in actions:
            continue
        p = run(["gh", "pr"] + cmd + ["-R", ctx["repo"]])
        if p.returncode != 0:
            return "error", "%s failed after %s: %s" % (
                action, "+".join(done) or "no change", p.stderr.strip()[:160])
        done.append(action)
    return "synced", "+".join(done) or "none"


def plan_actions(ctx, status, dep, m_pr, m_head, h_d):
    """-> (actions, held). `held`: a Guild stack draft this script must NOT ready — the
    dependency came in through someone else's merge (a human catch-up after `stale`), which has
    not been through our verification. The human readies it after `/gld dev <n>`."""
    actions, held = [], False
    if status == "needs-sync":
        actions.append("merge")
    if m_pr.get("baseRefName") != ctx["default"]:
        actions.append("retarget")
    if m_pr.get("isDraft"):
        body = gh_json(["pr", "view", str(m_pr["number"]), "-R", ctx["repo"], "--json", "body"])
        if STACK_MARKER in ((body or {}).get("body") or ""):
            ref_default = "refs/remotes/origin/" + ctx["default"]
            ours = status in ("needs-sync", "clean") or guild_synced(ctx["top"], m_head, dep)
            if ours and not foreign_merge(ctx["top"], m_head, h_d, ref_default):
                actions.append("ready")
            else:
                held = True
    return actions, held


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tracker", required=True)
    ap.add_argument("--check", action="store_true", help="classify only; change nothing")
    ap.add_argument("--install-cmd", action="append", default=[])
    args = ap.parse_args(argv)
    if not re.match(r"\A[0-9]+\Z", args.tracker):
        die("--tracker must be digits only, got %r" % args.tracker)
    if not args.check and os.environ.get("GLD_UNATTENDED") == "1":
        die("refusing to push unattended — sync runs after a human merge (sprint/sync.md)")
    check_simple(args.install_cmd, "--install-cmd")

    try:
        top = git_out(os.getcwd(), "rev-parse", "--show-toplevel")
        info = gh_json(["repo", "view", "--json", "nameWithOwner,defaultBranchRef"])
        repo, default = info["nameWithOwner"], info["defaultBranchRef"]["name"]
        ctx = {"top": top, "repo": repo, "default": default, "tracker": args.tracker,
               "install": args.install_cmd, "notes": [],
               "logdir": os.path.join(top, ".claude", "guild", ".sprint-logs", args.tracker)}
        if not args.check:
            ctx["verify"] = load_verify_cmds(top)
            check_simple(ctx["verify"], "config.commands value")

        tracker = gh_json(["issue", "view", args.tracker, "-R", repo, "--json", "body,labels"])
        if "guild:sprint" not in [l["name"] for l in tracker.get("labels") or []]:
            die("#%s is not a sprint tracking Issue (no guild:sprint label)" % args.tracker)
        members = parse_members(tracker.get("body") or "")
        prs = prs_by_issue(gh_json(["pr", "list", "-R", repo, "--state", "all", "--limit", "200",
                                    "--json", "number,headRefName,headRefOid,baseRefName,state,"
                                    "mergedAt,isDraft,mergeCommit,closingIssuesReferences"]),
                           [n for n, _ in members])

        work = []          # (issue, dep, member PR, dep's merged PRs, status, detail)
        for issue, dep in members:
            if dep is None:
                continue
            merged = [p for p in prs.get(dep, []) if p["state"] == "MERGED"]
            if not merged:
                continue                                  # dep not merged yet — still stacked
            m_pr, why = single(prs.get(issue, []), "OPEN", lambda p: p.get("headRefName"))
            if why:
                work.append((issue, dep, None, None, "ambiguous", why))
            elif m_pr is not None:
                work.append((issue, dep, m_pr, merged, None, None))
        if not work:
            return 0

        refspecs = ["+refs/heads/%s:refs/remotes/origin/%s" % (default, default)]
        refspecs += ["+refs/heads/{0}:refs/remotes/origin/{0}".format(w[2]["headRefName"])
                     for w in work if w[3]]
        p = git(top, "fetch", "--quiet", "origin", *refspecs)
        if p.returncode != 0:
            raise EnvError("fetch failed: %s" % p.stderr.strip()[:200])
    except EnvError as exc:
        die(str(exc), EXIT_ENV)

    for issue, dep, m_pr, merged, status, detail in work:
        try:
            if merged:
                status, detail = member_outcome(ctx, args.check, issue, dep, m_pr, merged)
        except EnvError as exc:
            status, detail = "error", str(exc)
        if not (args.check and (status == "clean" and not detail or detail == "none")):
            print("%d %s #%d%s" % (issue, status, dep, " " + detail if detail else ""))
        for note in ctx["notes"]:
            print(note)
        del ctx["notes"][:]
        sys.stdout.flush()
    return 0


def member_outcome(ctx, check, issue, dep, m_pr, merged):
    top = ctx["top"]
    branch = m_pr["headRefName"]
    m_head = git_out(top, "rev-parse", "refs/remotes/origin/" + branch)
    dep_pr = pick_dep_pr(top, merged, m_head)
    status, detail = classify(top, ctx["default"], dep_pr, m_head)
    if status not in ("clean", "needs-sync", "synced"):
        return status, detail
    actions, held = plan_actions(ctx, status, dep, m_pr, m_head, dep_pr["headRefOid"])
    if actions:
        # Same gates in --check: `daily` must not send the human to a sync that will refuse.
        labels = gh_json(["issue", "view", str(issue), "-R", ctx["repo"], "--json", "labels"])
        names = [l["name"] for l in (labels or {}).get("labels") or []]
        if "guild:done" not in names or "guild:needs-human" in names:
            return "skipped", "not-done"
        holder = checked_out_branches(top).get(branch)
        if holder:
            return "skipped", "branch-checked-out " + holder
        if m_head != m_pr.get("headRefOid"):
            return "skipped", "head-moved"
        if check:
            # `held`: the sync will push but leave the draft to the human — say so now.
            return "needs-sync", ",".join(actions + (["held"] if held else []))
        status, detail = sync_member(ctx, issue, dep, m_pr, branch, m_head,
                                     dep_pr["headRefOid"], actions)
        if status != "synced":
            return status, detail
    if held:
        return "draft-held", "pr=%d" % m_pr["number"]
    return ("synced", detail) if actions else (status, "none")


if __name__ == "__main__":
    sys.exit(main())
