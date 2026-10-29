"""Is the harness committed? (m1-plan §4.1 `begin`, v3 N13 · v4 R1 · R7 · v5 S2 · v5.1 T1 · T3 · T4).

A video starts (`begin`) and a stage finishes (`stage-done`) only on a committed harness: the set of paths a harness
commit would stage now (`HarnessKind.collect` — `.claude/studio/**` but local/, `.claude/agents/std-*.md`, the Studio
block of `.gitignore` and of the tracked husky hook; untracked files outside that list and edits outside the Studio
blocks do not count) must be empty. `status` shows the same list.

One exception (S2, T1): `.claude/studio/pronounce.json` whose difference from HEAD is additions only, each (key,
value) of them in the `work/<l>/pronounce-approved.json` of a video in progress that is still valid — its sha is the
one the language's current ② record holds, that record is a person's (`approved_by: human`) and its tuple is the
current one. That is what is left after a person refused a video commit (`--stage video` had merged it); the video's
commit puts it in. Everything is compared as parsed JSON (key order, spacing and line ends do not matter, T4)."""

import json
import os

from .. import paths
from ..commit import checks as cchecks, kinds as ckinds
from ..commit.gitx import Git, GitError
from ..commit.harness import HarnessKind
from . import hashes, schema
from .collect import CollectError
from .tuples import changed, tuple_for

PRONOUNCE = ".claude/studio/pronounce.json"
APPROVED = "pronounce-approved.json"
MAX_LIST = 10
LEFTOVER = ("left over from a refused video commit: commit that video, or drop them with "
            "git checkout -- .claude/studio/pronounce.json")


class Result(object):
    def __init__(self, paths_=(), problems=(), leftover=False, exempted=False, error=None):
        self.paths = sorted(paths_)
        self.problems = list(problems)  # (message, path or None)
        self.leftover = leftover  # pronounce.json blocks and its difference is additions only (T3's hint)
        self.exempted = exempted  # pronounce.json had only exempt additions (not counted)
        self.error = error

    @property
    def blocking(self):
        return bool(self.paths or self.problems or self.error)

    def message(self):
        """The refusal (exit 3): the blocking paths, at most MAX_LIST, and the rest's number (v4 R7)."""
        if self.error:
            return "cannot tell whether the harness is committed: %s" % self.error
        items = list(self.paths) + [p for _m, p in self.problems if p and p not in self.paths]
        shown = items[:MAX_LIST]
        more = len(items) - len(shown)
        text = "commit the harness first (python3 .claude/studio/scripts/check_commit.py --stage harness, then the " \
               "person's answer): %s%s" % (", ".join(shown) if shown else "(see below)",
                                          " and %d more" % more if more > 0 else "")
        for m, _p in self.problems:
            text += "\n  - " + m
        if self.leftover:
            text += "\n  - %s: %s" % (PRONOUNCE, LEFTOVER)
        return text

    def lines(self):
        """For `status`: one line per blocking path."""
        out = list(self.paths)
        out += ["%s (%s)" % (p or "-", m) for m, p in self.problems]
        if self.error:
            out.append("unknown (%s)" % self.error)
        return out


def _parse(data):
    if data is None:
        return {}
    try:
        v = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except (ValueError, UnicodeDecodeError):
        return None
    return v if isinstance(v, dict) else None


def _video_dirs(repo, root):
    out = []
    for base in (os.path.join(repo, root, "videos"), os.path.join(repo, root, "local", "videos")):
        if os.path.isdir(base):
            out += [os.path.join(base, n) for n in sorted(os.listdir(base))]
    return out


def approved_additions(repo, root, providers, ctx_of, videos=None, per_video=None):
    """{key: [values]} of the valid pronounce-approved.json of every video in progress (T1). `ctx_of(vdir, lang)`
    gives the collect context of a video's language; `videos` (a set) receives the ids that contributed and
    `per_video` (a dict) each video's own object (M1f: the cast stage's conflicts)."""
    from .store import read_state  # read-only use
    out = {}
    for vdir in _video_dirs(repo, root):
        try:
            st = read_state(vdir)
        except schema.SchemaError:
            continue
        for lang, L in st["langs"].items():
            if L.get("status") != "active":
                continue  # a finished or abandoned language exempts nothing (T3)
            rec = L["approved"].get("2")
            p = os.path.join(vdir, "work", lang, APPROVED)
            sha = hashes.file_sha(p)
            if not isinstance(rec, dict) or rec.get("approved_by") != "human" or sha is None or \
                    rec.get(schema.PRONOUNCE_SHA) != sha:
                continue
            if providers is None:
                continue  # the tuple cannot be checked: nothing is exempt (closed)
            try:
                cur = providers.collect(ctx_of(vdir, lang), st, lang)
            except (CollectError, KeyError, TypeError, ValueError):
                continue
            diff = [k for k in changed(rec.get("tuple") or {}, tuple_for("2", cur)) if k != "engine.defaults_voice"]
            if diff:
                continue  # ② is stale (the script changed after it): its file exempts nothing (T1)
            try:
                with open(p, "rb") as f:
                    data = _parse(f.read())
            except OSError:
                data = None
            for k, v in (data or {}).items():
                out.setdefault(k, []).append(v)
            if data and videos is not None:
                videos.add(st["video"])
            if data and per_video is not None:
                per_video.setdefault(st["video"], {}).update(data)
    return out


def _judge(head, obj, allowed):
    """"same" (no difference as objects, T4) · "exempt" (additions only, every one approved, S2/T1) · "additions"
    (additions only, not all approved: T3's leftover hint) · "block" (anything else)."""
    if head is None or obj is None:
        return "block"
    if obj == head:
        return "same"
    if not all(k in obj and obj[k] == v for k, v in head.items()):
        return "block"
    added = {k: v for k, v in obj.items() if k not in head}
    ok = allowed()
    return "exempt" if all(v in ok.get(k, []) for k, v in added.items()) else "additions"


class Verdict(object):
    def __init__(self, discard=False, exempted=False, leftover=False, videos=()):
        self.discard, self.exempted, self.leftover, self.videos = discard, exempted, leftover, sorted(videos)


def _default_providers(ctx):
    """state.py's providers and contexts (real s2v inspect) for a caller that has none (check_commit --stage)."""
    from . import cli as scli
    from .collect import Providers
    return Providers(), scli._ctx_of(ctx.top, ctx.cfg if isinstance(ctx.cfg, dict) else {})


def pronounce_verdict(ctx, providers=None, ctx_of=None):
    """How pronounce.json's difference from HEAD counts (T1–T4, Y5): `discard` — the work tree and the index are each
    the same as HEAD or only approved additions; `exempted` — some approved addition was left out; `leftover` —
    additions only, not all approved (the hint)."""
    if providers is None:
        providers, ctx_of = _default_providers(ctx)
    head_blob = ctx.git.show("%s:%s" % (ctx.head, PRONOUNCE)) if ctx.head else None
    head = _parse(head_blob)
    try:
        with open(os.path.join(ctx.top, PRONOUNCE), "rb") as f:
            work = _parse(f.read())
    except OSError:
        work = None
    # the index too (M1b review Y5): a staged pronounce.json is what the next commit takes
    staged = ctx.git.show(":" + PRONOUNCE)
    # not in the index: untracked (as in HEAD: nothing) or a staged deletion (blocks)
    index = _parse(staged) if staged is not None else ({} if head_blob is None else None)
    root = ctx.roots[0] if ctx.roots else "studio"
    cache, videos = {}, set()

    def allowed():
        if "a" not in cache:
            cache["a"] = approved_additions(ctx.top, root, providers, ctx_of or (lambda v, l: None), videos)
        return cache["a"]
    verdicts = [_judge(head, work, allowed), _judge(head, index, allowed)]
    discard = all(v in ("same", "exempt") for v in verdicts)
    return Verdict(discard=discard, exempted=discard and "exempt" in verdicts,
                   leftover="additions" in verdicts and "block" not in verdicts, videos=videos)


def check(repo, env=None, providers=None, ctx_of=None):
    """Result for the work tree `repo`."""
    env = paths.git_env(env)
    try:
        git = Git(repo, env)
        ctx = cchecks.Ctx(git, env, ckinds.registry({}))
    except (GitError, OSError) as e:
        return Result(error=str(e))
    if not ctx.harness:
        return Result(error="no Studio harness here")
    try:
        col = HarnessKind().collect(ctx, None, judge_pronounce=False)
    except (GitError, OSError) as e:
        return Result(error=str(e))
    found = set(col.paths)
    if col.gitignore:
        found.add(".gitignore")
    problems = [(p.message, p.path) for p in col.problems]
    leftover = exempted = False
    if PRONOUNCE in found:
        v = pronounce_verdict(ctx, providers=providers or _NoProviders(), ctx_of=ctx_of)
        if v.discard:
            found.discard(PRONOUNCE)
        exempted, leftover = v.exempted, v.leftover
    return Result(found, problems, leftover=leftover, exempted=exempted)


class _NoProviders(object):
    """No providers given: nothing can be checked as current, so nothing is exempt (closed)."""

    def collect(self, *a, **k):
        raise CollectError("no providers")
