"""Commit kinds (m0e-plan §7.2): each kind gives the paths it stages (its allow-list) and its checks.
`harness` (M0f) is real; `video` (M1) and `actor` (M3b) refuse with exit 3.

A kind: `name`, `needs_overlay` (the internal overlay must be present: video and actor yes, harness no —
it holds nothing internal), `collect(ctx, target) -> Collected`, `allowed(ctx, path) -> bool`."""

import os

from . import approvals

PLANNED = {"video": "M1", "actor": "M3b"}
TEST_ENV = "STUDIO_TEST_COMMIT_KIND"  # test only (the guard refuses STUDIO_TEST_* in agent commands)


class Collected(object):
    def __init__(self, paths, gitignore=False, problems=(), states=None):
        self.paths = sorted(paths)
        self.gitignore = gitignore
        self.problems = list(problems)
        self.states = dict(states or {})


class FolderKind(object):
    """Test kind: everything changed under `<sr>/videos/<target>/` (and the .gitignore block on request),
    with the video's light approval check when it has a state. Registered only by tests."""

    name = "test"
    needs_overlay = True
    proxy_commit = True  # the sandbox proxy mode may commit the test kind (M0d-2 checks; real kinds decide later)

    def __init__(self, with_gitignore=False):
        self.with_gitignore = with_gitignore

    def _prefix(self, ctx, target):
        return "%s/videos/%s/" % (ctx.roots[0], target)

    def collect(self, ctx, target):
        if not target:
            return Collected([], problems=[approvals.Problem(2, "the test kind needs a target")])
        pre = self._prefix(ctx, target)
        raw = ctx.git.text("ls-files", "-z", "--modified", "--deleted", "--others", "--exclude-standard", "--",
                           ":(literal)" + pre.rstrip("/"))
        cached = ctx.git.text("diff", "--name-only", "-z", "--no-renames", ctx.head or ctx.git.empty_tree(), "--",
                              ":(literal)" + pre.rstrip("/"))
        found = sorted(set(p for p in (raw + "\0" + cached).split("\0") if p))
        vdir = os.path.join(ctx.top, ctx.roots[0], "videos", target)
        problems, states = [], {}
        if os.path.exists(os.path.join(vdir, "work", "state.json")):
            problems = approvals.light_check(vdir, target)
            states[target] = {"last_seq": approvals.state_seq(vdir)}
        return Collected(found, gitignore=self.with_gitignore, problems=problems, states=states)

    def allowed(self, ctx, path):
        if path == ".gitignore":
            return self.with_gitignore
        return any(path.startswith("%s/videos/" % r) for r in ctx.roots) and "/work/" not in path


def registry(env, extra=None):
    kinds = {name: None for name in PLANNED}
    from .harness import HarnessKind  # (M0f) imported here: harness.py uses Collected from this module
    kinds["harness"] = HarnessKind()
    if env.get(TEST_ENV):
        kinds["test"] = FolderKind(with_gitignore=env.get(TEST_ENV) == "gitignore")
    if extra:
        kinds.update(extra)
    return kinds
