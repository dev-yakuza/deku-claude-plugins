"""workflows.dev.variants.refactor_net — the refactor Safety net as code (refactor.md EVIDENCE RULE,
catalog B P0.R1/P0.R2, D-R1–D-R9, design §5.1 "순서" R7C-M1).

* `mode(issue_body)` — `only` | `with-refactor` | `none` from the two ASCII markers.
* `residue(root, branch, base)` (P0.R2 / D-R9) — the proof-residue state after a crashed step 6, read
  with engine git: on <branch> (+ staged?), on another branch, detached (+ staged → proof copies or
  not). `cleanup()` puts a proof's index back (`git rm -f` the A copies, `git checkout HEAD --` the
  M copies, `diff --cached --quiet`, `git switch <branch>`) — called by the stage right after the
  developer returns and BEFORE the §5.1 scope check (R7C-M1); a failure is the P0.R2 needs-human
  (`branch-blocked` / `proof residue`), never a scope `defect:`.
* `checks(root, base, branch, block, …)` — D-R1–D-R7 over the `<!-- guild:safety-net-evidence -->`
  block; each failure is one loop-back line ("re-prove the net — <check>").
* `module_only(diff_text)` — D-R3/F-17: every changed line differs from its counterpart only in a
  quoted module path (`import … from`, the tail line of a wrapped import, `require(`, `import(`,
  `jest.mock(`, `vi.mock(`, Dart `import`/`export`/`part`).
"""

import re

from guildcore.adapters import git as G
from guildcore.records import markers

NAME = "safety-net-evidence"
KEYS = ("verified", "sha", "run", "net", "deferred", "post-transform-net", "leftover")
_IMPORT_LINE = re.compile(r"^\s*(import\b.*\bfrom\b|\}?\s*from\s+['\"]|.*\brequire\(|.*\bimport\(|"
                          r".*\b(?:jest|vi)\.mock\(|import\s+['\"]|export\s+['\"]|part\s+['\"])")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")
SNAPSHOT_RE = re.compile(r"(__snapshots__/|\.snap$|__screenshots__/|/goldens?/|\.png$)")


def mode(issue_body):
    b = issue_body or ""
    if "<!-- guild:safety-net-only -->" in b:
        return "only"
    if "<!-- guild:safety-net -->" in b:
        return "with-refactor"
    return "none"


def _g(root, *args):
    return G.run(root, *args, check=False).decode("utf-8", "replace")


def _ok(root, *args):
    return G.ok(root, *args)


# ---- P0.R2 proof residue ----------------------------------------------------------------------

class Residue(object):
    """state ∈ clean | staged-on-branch | other-branch | detached-clean | proof-copies | not-proof |
    unstaged-tracked. `copies` = [(status, path)] for proof-copies."""

    def __init__(self, state, detail=None, copies=()):
        self.state, self.detail, self.copies = state, detail, list(copies)

    def __repr__(self):
        return "<Residue %s %s>" % (self.state, self.detail or "")


def _staged(root):
    out = []
    for ln in _g(root, "diff", "--cached", "--name-status", "--no-renames").split("\n"):
        if "\t" in ln:
            st, path = ln.split("\t", 1)
            out.append((st.strip()[:1], path))
    return out


def _blob(root, spec):
    return _g(root, "rev-parse", "-q", "--verify", spec).strip() or None


def residue(root, branch, base, post_move=None):
    """`post_move(path) -> branch path or None` maps a proof copy back to its moved place."""
    sym = _g(root, "symbolic-ref", "-q", "HEAD").strip()
    staged = _staged(root)
    if sym:
        if sym == "refs/heads/%s" % branch:
            return Residue("staged-on-branch" if staged else "clean")
        return Residue("other-branch", sym[len("refs/heads/"):])
    if not staged:
        return Residue("detached-clean")
    if not _ok(root, "merge-base", "--is-ancestor", "HEAD", base):
        return Residue("not-proof", "detached HEAD is not an ancestor of %s" % base)
    copies = []
    for st, path in staged:
        idx = _blob(root, ":%s" % path)
        cands = [path] + ([post_move(path)] if post_move and post_move(path) else [])
        same = any(idx and _blob(root, "%s:%s" % (branch, c)) == idx for c in cands)
        if not same:
            for c in cands:
                if _blob(root, "%s:%s" % (branch, c)) and module_only(_g(root, "diff", "-U0", "%s:%s" % (branch, c), ":%s" % path)):
                    same = True
                    break
        if not same:
            return Residue("not-proof", path)
        copies.append((st, path))
    return Residue("proof-copies", None, copies)


def cleanup(root, branch, res):
    """Put a proof's index back and return to <branch>. Returns None or the failing step."""
    if res.state == "proof-copies":
        a = [p for s, p in res.copies if s == "A"]
        m = [p for s, p in res.copies if s != "A"]
        try:
            if a:
                G.run(root, "rm", "-f", "-q", "--", *a)
            if m:
                G.run(root, "checkout", "HEAD", "--", *m)
        except G.GitError as e:
            return str(e)
        if not _ok(root, "diff", "--cached", "--quiet"):
            return "index still differs from HEAD after putting the proof back"
    if res.state in ("proof-copies", "detached-clean"):
        if not _ok(root, "diff", "--quiet"):
            return "unstaged edits to tracked files before `git switch %s`" % branch
        try:
            G.run(root, "switch", branch)
        except G.GitError as e:
            return str(e)
    return None


def untracked_leftovers(root):
    out = []
    raw = G.run(root, "status", "--porcelain", "-uall", "-z", check=False).decode("utf-8", "replace")
    for e in raw.split("\0"):
        if e.startswith("?? ") and (SNAPSHOT_RE.search(e[3:]) or "safety" in e[3:].lower()):
            out.append(e[3:])
    return out


# ---- D-R3 module specifiers ---------------------------------------------------------------------

def module_only(diff_text):
    """True when every -/+ line pair of a -U0 diff differs only inside quoted module paths of
    import-like lines (pairs in order within each hunk; unequal counts → False)."""
    rem, add, ok = [], [], True

    def flush():
        if len(rem) != len(add):
            return False
        for a, b in zip(rem, add):
            if not (_IMPORT_LINE.match(a) and _IMPORT_LINE.match(b)):
                return False
            if _QUOTED.sub("''", a) != _QUOTED.sub("''", b):
                return False
        return True
    for ln in (diff_text or "").split("\n"):
        if ln.startswith("@@"):
            ok = ok and flush()
            rem, add = [], []
        elif ln.startswith("-") and not ln.startswith("---"):
            rem.append(ln[1:])
        elif ln.startswith("+") and not ln.startswith("+++"):
            add.append(ln[1:])
    return ok and flush()


# ---- the block ------------------------------------------------------------------------------------

def parse_block(text):
    """→ {verified, sha, run[], net[], deferred[], post-transform-net[], leftover[]} or None."""
    if text is None:
        return None
    out = {"verified": None, "sha": None, "run": [], "net": [], "deferred": [], "post-transform-net": [],
           "leftover": []}
    cur = None
    for raw in text.split("\n"):
        ln = markers.clean(raw)
        if ln.startswith("<!--"):
            continue
        m = re.match(r"^(%s):\s?(.*)$" % "|".join(re.escape(k) for k in KEYS), ln)
        if m:
            cur, val = m.group(1), m.group(2).strip()
            if cur in ("verified", "sha"):
                out[cur] = val or None
            elif val and val != "none":
                out[cur].append(val[2:] if val.startswith("- ") else val)
            continue
        if cur and cur not in ("verified", "sha") and ln.strip():
            v = ln.strip()
            out[cur].append(v[2:] if v.startswith("- ") else v)
    return out


def render_block(f):
    def many(k):
        vals = f.get(k) or []
        return ["%s: none" % k] if not vals else ["%s:" % k] + ["- %s" % markers.value(v) for v in vals]
    lines = [markers.open_tag(NAME), "verified: %s" % ("yes" if f.get("verified") == "yes" else "no"),
             "sha: %s" % (f.get("sha") or "none")]
    runs = f.get("run") or []
    lines += ["run:"] + ["  %s" % markers.value(r) for r in runs] if runs else ["run: none"]
    lines += many("net") + many("deferred") + many("post-transform-net") + many("leftover")
    lines.append(markers.close_tag(NAME))
    return "\n".join(lines)


# ---- D-R1–D-R7 --------------------------------------------------------------------------------------

def _name_status(root, a, b, rename=True):
    out = []
    args = ["diff", "--name-status"] + (["-M"] if rename else ["--no-renames"]) + [a, b]
    for ln in _g(root, *args).split("\n"):
        parts = ln.split("\t")
        if len(parts) >= 2:
            out.append((parts[0], parts[1:]))
    return out


def checks(root, base, branch, block, support=(), visual_images=(), net_mode="with-refactor"):
    """The not-done reasons (empty = the net holds). `block` = parse_block(...)."""
    bad = []
    if not block or not block.get("sha") or block["sha"] == "none":
        return ["no sha: in the safety-net block"]
    sha = block["sha"]
    if not _ok(root, "cat-file", "-e", sha):                                   # D-R6
        return ["proof tree %s is gone — re-prove the net" % sha[:12]]
    mb = _g(root, "merge-base", base, branch).strip()
    if not mb:
        return ["no merge base of %s and %s" % (base, branch)]
    net = list(dict.fromkeys(block.get("net") or []))
    ptn = [p.split(" @ ")[0].strip() for p in block.get("post-transform-net") or []]
    run = "\n".join(block.get("run") or [])
    # D-R1: every net file at sha ran green there; no snapshot written
    for f in net:
        if f in ptn:
            continue
        if f not in run:
            bad.append("run: does not show net file %s executed in %s" % (f, sha[:12]))
    if re.search(r"\b(\d+ )?snapshots? (written|updated)\b", run, re.I):
        bad.append("the proof run wrote a snapshot")
    # D-R2: production code at sha == the merge base
    allowed = set(net) | set(support)
    for path in _g(root, "diff", "--name-only", mb, sha).split("\n"):
        if not path:
            continue
        if path in allowed or path.startswith("docs/specs/") or SNAPSHOT_RE.search(path) or \
                any(path.startswith(n.rsplit("/", 1)[0] + "/") and SNAPSHOT_RE.search(path) for n in net):
            continue
        bad.append("proof tree holds a production change: %s" % path)
    tree_files = set(_g(root, "diff", "--name-only", mb, sha).split("\n"))
    for img in visual_images:
        if img not in tree_files:
            bad.append("safety-net visual image %s is not in the proof" % img)
    # D-R3/D-R5: the net between sha and <branch>
    for st, paths in _name_status(root, sha, branch):
        old = paths[0]
        new = paths[-1]
        is_net = old in net or SNAPSHOT_RE.search(old) and any(old.startswith(n.rsplit("/", 1)[0]) for n in net)
        if st == "D" and is_net:
            bad.append("net file deleted: %s" % old)
        elif st.startswith("M") and is_net or (st.startswith("R") and st != "R100" and is_net):
            d = _g(root, "diff", "-U0", "-M", sha, branch, "--", old, new)
            if not module_only(d):
                bad.append("net file changed beyond module paths: %s" % new)
        elif st == "A" and SNAPSHOT_RE.search(new) and new not in ptn and \
                any(new.startswith(n.rsplit("/", 1)[0] + "/") for n in net):
            bad.append("net snapshot added after the proof: %s" % new)            # D-R5
    # D-R4: post-transform-net files frozen at their recorded blob
    for ent in block.get("post-transform-net") or []:
        path, _, blob = ent.partition(" @ ")
        path, blob = path.strip(), blob.strip()
        cur = _blob(root, "%s:%s" % (branch, path))
        if not cur:
            bad.append("post-transform-net file missing on %s: %s" % (branch, path))
        elif blob and cur != blob and not module_only(_g(root, "diff", "-U0", blob, cur)):
            bad.append("post-transform-net file edited: %s" % path)
    # D-R7: only → nothing but the net on the branch
    if net_mode == "only":
        for path in _g(root, "diff", "--name-only", "%s...%s" % (mb, branch)).split("\n"):
            if path and path not in allowed and not path.startswith("docs/specs/") and not SNAPSHOT_RE.search(path):
                bad.append("safety-net-only Issue changed a production file: %s" % path)
    return bad
