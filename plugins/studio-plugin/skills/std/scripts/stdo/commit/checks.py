"""The checks shared by `--staged` (the pre-commit hook) and `--stage` (m0e-plan §5, §7)."""

import hashlib
import json
import os

from .. import SCRIPTS_VERSION, ignore, paths
from . import approvals, inprogress, okfile, spaths
from .approvals import Problem

# the same sentence in --stage and in the hook (review NIT)
GUARD_RAN = ("the Studio guard has not run in this Claude Code session (%s) — enable the Studio plugin and retry; "
             "do not remove the session markers")


class Ctx(object):
    def __init__(self, git, env, kinds):
        self.git = git
        self.env = env
        self.kinds = kinds
        self.top = git.toplevel()
        git.cwd = self.top
        self.cfg, self.cfg_error = spaths.read_config(self.top)
        self.head = git.head()
        self.roots = spaths.studio_roots(self.top, git, env, self.head)
        self.cls = spaths.Classifier(self.roots, git.ignorecase())
        self.base = self.head or git.empty_tree()

    @property
    def harness(self):
        return self.cfg is not None or self.cfg_error is not None


class Staged(object):
    """The index against HEAD, split (m0e-plan §2)."""

    def __init__(self, ctx):
        self.all = ctx.git.staged(ctx.base)
        names = [p for _s, p in self.all]
        # a leak adds or changes a local/ file; unstaging or deleting one (status D) is not a leak
        self.local = [p for st, p in self.all if st != "D" and ctx.cls.is_local(p)]
        self.gi_kind = "none"
        if spaths.GITIGNORE in names:
            old = ctx.git.show("%s:%s" % (ctx.head, spaths.GITIGNORE)) if ctx.head else None
            self.gi_kind = spaths.gitignore_kind(old, ctx.git.show(":" + spaths.GITIGNORE))
        self.studio, self.other = [], []
        # removing a local/ file from the index (a leak being cleaned up) is neither a Studio nor another change
        cleanup = set(p for st, p in self.all if st == "D" and ctx.cls.is_local(p))
        for p in names:
            if p in cleanup:
                continue
            if p == spaths.GITIGNORE:
                if self.gi_kind in ("studio", "broken"):
                    self.studio.append(p)
                elif self.gi_kind == "other":
                    self.other.append(p)
                elif self.gi_kind == "mixed":
                    self.studio.append(p)
                    self.other.append(p)
            elif ctx.cls.is_studio(p):
                self.studio.append(p)
            else:
                self.other.append(p)
        self.progress, self.parents, self.three = inprogress.detect(ctx.git)
        if self.progress:
            self.studio = inprogress.new_changes(ctx.git, [p for p in self.studio], ctx.head, self.parents,
                                                 gitignore_in=spaths.GITIGNORE in self.studio, three=self.three)


def local_problems(st):
    return [Problem(1, "%s is a machine-only Studio file (local/) staged to be added or changed — it is never "
                       "committed. Unstage it: git restore --staged -- '%s'" % (p, p), p) for p in st.local]


def mixed_problem(ctx, st):
    if st.progress or not st.studio or not st.other:
        return None
    if st.gi_kind == "mixed":
        what = ".gitignore changes both the Studio block and other lines — stage them separately"
    else:
        what = "this commit mixes Studio paths (%d) with other paths (%d) — commit them separately" % (
            len(st.studio), len(st.other))
    studio = " ".join("'%s'" % p for p in st.studio[:10]) + (" …" if len(st.studio) > 10 else "")
    return Problem(1, "%s. To drop the Studio side: git restore --staged -- %s; to commit only the Studio side, "
                      "unstage the others (git restore --staged -- <path>)" % (what, studio))


def session(env):
    """(is a Claude Code session, its id)."""
    if env.get("CLAUDECODE"):
        return True, env.get("CLAUDE_CODE_SESSION_ID") or ""
    return False, None


def guard_ran_problem(ctx):
    claude, sid = session(ctx.env)
    if not claude:
        return None
    if sid:
        p = os.path.join(ctx.top, ".claude", "studio", "local", "guard-ran.json")
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("sessions"), dict) and sid in data["sessions"]:
                return None
        except (OSError, ValueError):
            pass
    return Problem(7, GUARD_RAN % ((sid or "no session id")[:8]))


def overlay_problem(ctx):
    if not isinstance(ctx.cfg, dict) or ctx.cfg.get("internal_overlay") != "required":
        return None
    p = os.path.join(ctx.top, ".claude", "studio", "local", "config.internal.json")
    try:
        with open(p, "rb") as f:
            have = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return Problem(4, "the internal overlay (.claude/studio/local/config.internal.json) is missing in this "
                          "clone — ask the user to recreate it (/std config) before a Studio commit")
    try:
        sha_file = os.path.join(paths.backup_root(ctx.env), paths.repo_key(ctx.top), "overlay.sha")
        with open(sha_file, encoding="utf-8") as f:
            want = f.read().strip()
    except (OSError, RuntimeError, ValueError):
        want = None
    if want != have:
        return Problem(4, "the internal overlay does not match its recorded sha (or the record is missing) — ask "
                          "the user to confirm it (/std config) before a Studio commit")
    return None


def ignore_problems(ctx, index=True):
    out = []
    root = ctx.roots[0]
    data = ctx.git.show(":" + spaths.GITIGNORE) if index else None
    if not index:
        try:
            with open(os.path.join(ctx.top, spaths.GITIGNORE), "rb") as f:
                data = f.read()
        except OSError:
            data = None
    if not ignore.ok((data or b"").decode("utf-8", "surrogateescape"), root):
        out.append(Problem(1, ".gitignore lacks Studio's block (or its local/ lines) — restore it (/std init) before "
                              "a Studio commit", spaths.GITIGNORE))
    try:
        with open(os.path.join(ctx.git.common_dir(), "info", "exclude"), encoding="utf-8") as f:
            ex = f.read()
    except OSError:
        ex = ""
    if not ignore.ok(ex, root):
        out.append(Problem(1, "info/exclude lacks Studio's block — run \"python3 .claude/studio/scripts/hooks.py "
                              "install\" before a Studio commit"))
    return out


def videos_of(ctx, studio_paths):
    out = {}
    for p in studio_paths:
        v = ctx.cls.video_of(p)
        if v:
            out[v[1]] = approvals.video_dir(ctx.top, v[0], v[1])
    return out


def video_problems(ctx, studio_paths):
    out = []
    for video, vdir in sorted(videos_of(ctx, studio_paths).items()):
        if not os.path.exists(os.path.join(vdir, "work", "state.json")):
            out.append(Problem(1, "video %s has no state (work/state.json) on this machine — Studio commits a video "
                                  "only after its gates" % video))
            continue
        out.extend(approvals.light_check(vdir, video))
    return out


def kind_problems(ctx, kind_name, studio_paths):
    if kind_name not in ctx.kinds:
        return [Problem(1, "unknown commit kind %r" % kind_name)]
    kind = ctx.kinds[kind_name]
    if kind is None:
        return [Problem(3, "commit kind \"%s\" arrives in %s — Studio cannot make this commit yet"
                           % (kind_name, approvals_planned(kind_name)))]
    bad = [p for p in studio_paths if not kind.allowed(ctx, p)]
    return [Problem(1, "%s is outside the allow-list of a %s commit" % (p, kind_name), p) for p in bad]


def approvals_planned(name):
    from .kinds import PLANNED
    return PLANNED.get(name, "a later version")


def ok_problems(ctx, st, ok):
    out = []
    tree = ctx.git.write_tree()
    if ok.get("tree") != tree:
        out.append(Problem(1, "the staged tree (%s) is not the one Studio prepared (%s) — run \"python3 "
                              ".claude/studio/scripts/check_commit.py --stage …\" and ask the user again"
                              % (tree[:12], str(ok.get("tree"))[:12])))
    if ok.get("head") != ctx.head:
        out.append(Problem(1, "HEAD moved since Studio prepared this commit — stage it again and ask again"))
    if ok.get("studio_root") != ctx.roots[0]:
        out.append(Problem(1, "studio_root changed since Studio prepared this commit — stage it again"))
    if sorted(ok.get("paths") or []) != sorted(st.studio):
        out.append(Problem(1, "the staged Studio paths are not the ones Studio prepared — stage them again"))
    if (ok.get("in_progress") or None) != (st.progress or None):
        out.append(Problem(1, "commit-ok.json was prepared for a different situation (%s) — stage again"
                              % (ok.get("in_progress") or "no merge/rebase")))
    claude, sid = session(ctx.env)
    if claude and ok.get("session_id") != sid:
        out.append(Problem(1, "commit-ok.json was prepared in another Claude Code session — stage again in this one"))
    for video, want in sorted((ok.get("states") or {}).items()):
        have = approvals.state_seq(approvals.video_dir(ctx.top, ctx.roots[0], video))
        if not isinstance(want, dict) or want.get("last_seq") != have:
            out.append(Problem(1, "video %s changed since Studio prepared this commit (state seq) — stage again"
                                  % video))
    return out


def staged_check(ctx):
    """(code, problems) of the pre-commit hook."""
    problems = []
    st = Staged(ctx)
    problems += local_problems(st)
    m = mixed_problem(ctx, st)
    if m:
        problems.append(m)
    if st.gi_kind == "broken":
        problems.append(Problem(1, ".gitignore's Studio block markers are unpaired or repeated", spaths.GITIGNORE))
    if not st.studio:
        return code_of(problems), problems
    if ctx.cfg_error:
        problems.append(Problem(2, ctx.cfg_error))
        return code_of(problems), problems
    if not ctx.harness:
        # a branch without the harness: only the local check applies (00-plan §3.4)
        return code_of(problems), problems
    g = guard_ran_problem(ctx)
    if g:
        problems.append(g)
    ok, why = okfile.read(ctx.top)
    kind = ctx.kinds.get(ok.get("kind")) if ok else None
    if not (ok and ok.get("kind") in ctx.kinds and kind is not None and not getattr(kind, "needs_overlay", True)):
        o = overlay_problem(ctx)
        if o:
            problems.append(o)
    problems += ignore_problems(ctx, index=True)
    if ok is None:
        problems.append(Problem(1, "Studio files are staged but Studio did not prepare this commit (commit-ok.json "
                                   "%s) — run \"python3 .claude/studio/scripts/check_commit.py --stage …\" and ask "
                                   "the user" % why))
    else:
        problems += ok_problems(ctx, st, ok)
        problems += kind_problems(ctx, ok.get("kind"), st.studio)
    problems += video_problems(ctx, st.studio)
    return code_of(problems), problems


def code_of(problems):
    return problems[0].code if problems else 0


def scripts_version():
    return SCRIPTS_VERSION
