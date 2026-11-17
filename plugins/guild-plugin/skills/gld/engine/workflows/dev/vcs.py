"""workflows.dev.vcs — the execute stage's git readings of the Issue worktree, through the engine's
git (`guildcore.adapters.git`: hooks off, no system config, no prompts). The procedure replay swaps
in a fake with the same methods; the unit tests use real temp repos.

Also the H§L visual ledger's git half (spine Step 2 calls 1–4) and the merge with the developer's
`baselines:` lines and the previous block (D-2.4–D-2.7).
"""

import fnmatch
import json
import re

from guildcore.adapters import git as G
from guildcore.checks import visual as V
from guildcore.records import markers
from workflows.dev import tripwire as TW

CENTRAL = (".claude/guild/gates/scripts/gate_precommit.py", ".claude/guild/gates/rules/secrets.md",
           ".claude/guild/gates/rules/verification.md")
VISUAL_G = ("comparatorOptions|allowedMismatched|maxDiffPixel|threshold|tolerance|goldenFileComparator|"
            "autoUpdateGoldenFiles|to[A-Za-z]*Screenshot|matches(Golden|Reference)File|toMatchImageSnapshot")


class Vcs(object):
    def __init__(self, root):
        self.root = root

    def _g(self, *args):
        return G.run(self.root, *args, check=False).decode("utf-8", "replace")

    def head(self):
        return self._g("rev-parse", "HEAD").strip() or None

    def exists(self, rev):
        return G.ok(self.root, "rev-parse", "--verify", "-q", rev)

    def merge_base(self, base):
        return self._g("merge-base", base, "HEAD").strip() or None

    def symbolic(self):
        s = self._g("symbolic-ref", "-q", "HEAD").strip()
        return s[len("refs/heads/"):] if s.startswith("refs/heads/") else None

    def readings(self, mb):
        return TW.readings(self.root, mb)

    def unchanged(self, sha, path):
        """carry-forward (D-4.4): `git diff --name-only <sha> -- <file>` empty; unknown sha → False."""
        if not sha or not self.exists(sha):
            return False
        return not self._g("diff", "--name-only", sha, "--", path).strip()

    def changed_since(self, sha, path):
        return bool(sha) and self.exists(sha) and bool(self._g("diff", "--name-only", sha, "--", path).strip())

    def names(self, spec, paths=()):
        args = ["diff", "--name-only", spec] + (["--"] + list(paths) if paths else [])
        return [x for x in self._g(*args).split("\n") if x]

    def name_status(self, spec, pathspecs=(), renames=False):
        args = ["diff", "--name-status"] + (["--find-renames=100%"] if renames else ["--no-renames"]) + [spec]
        if pathspecs:
            args += ["--"] + list(pathspecs)
        out = []
        for ln in self._g(*args).split("\n"):
            p = ln.split("\t")
            if len(p) >= 2:
                out.append((p[0], p[1:]))
        return out

    def grep_changed(self, spec, regex, pathspecs):
        return [x for x in self._g("diff", "--name-only", "-G", regex, spec, "--", *pathspecs).split("\n") if x]

    def diff(self, spec, path):
        return self._g("diff", spec, "--", path)

    def hunk(self, mb, path, line, ctx=12):
        """The diff hunk around `line` of `path` (EX-ARB brief)."""
        d = self._g("diff", "-U%d" % ctx, mb, "--", path)
        return d[:6000]

    def log(self, spec):
        return self._g("log", "--oneline", spec).strip()

    def status(self):
        return self._g("status", "--porcelain").strip()

    def staged(self, paths=()):
        args = ["diff", "--cached", "--name-only", "--no-renames"] + (["--"] + list(paths) if paths else [])
        return [x for x in self._g(*args).split("\n") if x]

    def unstage(self, paths):
        if paths:
            G.run(self.root, "restore", "--staged", "--", *paths)

    def show(self, rev, path):
        spec = "%s:%s" % (rev, path)
        if not G.ok(self.root, "cat-file", "-e", spec):
            return None
        return self._g("show", spec)

    def gates_config_changed(self, base):
        """K3 carry-over 2 / K3r1-M6: did THIS BRANCH change the gate's config (`.claude/guild/
        config.json` `gates`)? Every commit in `<merge-base>..HEAD` touching the file is compared
        with its parent (a change reverted later still counts), and the worktree with HEAD. A
        difference only between <base>'s tip and the branch (a `/gld update` on base) is not the
        developer's."""
        rel = ".claude/guild/config.json"

        def gates(text):
            if text is None:
                return "absent"
            try:
                return json.dumps((json.loads(text or "{}") or {}).get("gates"), sort_keys=True)
            except ValueError:
                return "unparseable"
        mb = self.merge_base(base)
        if mb:
            for c in [x for x in self._g("rev-list", "%s..HEAD" % mb, "--", rel).split("\n") if x]:
                parent = self._g("rev-parse", "%s^" % c).strip()
                if gates(self.show(c, rel)) != gates(self.show(parent, rel) if parent else None):
                    return True
        try:
            with open(self.root + "/" + rel, encoding="utf-8") as fh:
                wt = fh.read()
        except (IOError, OSError):
            wt = None
        return gates(wt) != gates(self.show("HEAD", rel))

    def central_owned(self, mb):
        return self.names("%s..HEAD" % mb, CENTRAL) if mb else None


# ---- the visual ledger (H§L.3) ----------------------------------------------------------------

DECL_RE = re.compile(r"^(C|M|D|P|P-withdrawn|A|R) (\S.*?)(?: — (.*))?$")


def declared(lines):
    """The developer's `baselines:` lines → {path: (code, reason)}; `none` → {}."""
    out = {}
    for ln in lines or []:
        m = DECL_RE.match((ln or "").strip())
        if m:
            out[m.group(2).split(" -> ")[0].strip()] = (m.group(1), (m.group(3) or "").strip())
    return out


def visual_rows(vcs, base, cfg, decl, prev_rows):
    """(rows[(code, path, reason)], run, notes). Calls 1–4 of the spine with their skip rules."""
    v = (cfg or {}).get("visual") or {}
    spec = "%s...HEAD" % base
    bl, cf, tests, pkgs = (v.get("baselines") or []), (v.get("config_files") or []), (v.get("tests") or []), \
        (v.get("packages") or [])
    rows, notes = {}, []
    if bl or cf:
        for st, paths in vcs.name_status(spec, [":(glob)%s" % g for g in bl + cf]):
            p = paths[-1]
            rows[p] = ("C" if any(fnmatch.fnmatch(p, g) for g in cf) else st[:1], "")
        ds = [p for p, r in rows.items() if r[0] == "D"]
        if ds and any(r[0] == "A" for r in rows.values()):
            for st, paths in vcs.name_status(spec, [":(glob)%s" % g for g in bl], renames=True):
                if st.startswith("R100") and len(paths) == 2:
                    rows.pop(paths[0], None)
                    rows.pop(paths[1], None)
                    rows["%s -> %s" % (paths[0], paths[1])] = ("R", "moved, unchanged")
    if tests:
        rx = VISUAL_G + "".join("|" + re.escape(m) for m in (v.get("matchers") or []))
        for f in vcs.grep_changed(spec, rx, [":(glob)%s" % g for g in tests]):
            rows.setdefault(f, ("C", ""))
    else:
        notes.append("inline comparison changes not checked (visual.tests empty)")
    prevP = dict((p, r) for c, p, r in prev_rows if c == "P")
    for path, (code, reason) in decl.items():
        if code == "P-withdrawn":
            prevP.pop(path, None)
            notes.append("P-withdrawn %s — %s" % (path, reason or "-"))
            continue
        if code == "P":
            prevP[path] = reason
            continue
        if path in rows and reason:
            rows[path] = (rows[path][0], reason)
    for path, reason in prevP.items():
        if path in rows:
            rows[path] = ("M", reason or rows[path][1])
        else:
            rows[path] = ("P", reason)
    for c, p, r in prev_rows:                     # reason from the previous block, same path
        if p in rows and not rows[p][1] and r:
            rows[p] = (rows[p][0], r)
    run = bool(rows) or (bool(vcs.names(spec, pkgs)) if pkgs else bool(vcs.names(spec)))
    return [(c, p, r) for p, (c, r) in sorted(rows.items())], run, notes


def undeclared(rows, cases):
    """D-2.6: C/M/D/replacing-A without a reason; any other A with neither a valid case nor a reason."""
    bad = []
    for c, p, r in rows:
        if c in ("C", "M", "D") and not r:
            bad.append(p)
        elif c == "A" and not r and not any(x and x in (r or "") for x in cases):
            bad.append(p)
    return bad


def render_ledger(rows, run):
    lines = [markers.open_tag(V.NAME), "run: %s" % ("yes" if run else "no")]
    if not rows:
        lines.append("none")
    for c, p, r in rows:
        lines.append("%s %s%s" % (c, markers.value(p), (" — " + markers.value(r)) if r else ""))
    lines.append(markers.close_tag(V.NAME))
    return "\n".join(lines)


def parse_ledger(block_text):
    rows = []
    for ln in (block_text or "").split("\n"):
        m = V.ROW_RE.match(markers.clean(ln))
        if m:
            rows.append((m.group(1), m.group(2), (m.group(3) or "").strip()))
    return rows
