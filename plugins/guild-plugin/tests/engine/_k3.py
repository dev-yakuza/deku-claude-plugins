"""Helpers for the K3 engine tests (execute): a real temp git repo as the Issue worktree, the fake
GitHub of K2, canned roles/judges/suites, a fake push."""

import json
import os

import _util  # noqa: F401
from _k1 import Clock, git, repo, tmpdir  # noqa: F401
from _k2 import (CFG, FLUTTER_GREEN, FLUTTER_RED, Harness, comment, decision, fixture, role,  # noqa: F401
                 suite)

from guildcore.records import audit as AU
from guildcore.records import markers
from workflows.dev import vcs as VC
from workflows.dev.stages import execute as X

XCFG = dict(CFG, visual={"baselines": [], "tests": [], "config_files": []})
DESIGN = "<!-- guild:design:output -->\n## design\nok\n<!-- /guild:design:output -->"


def wt_repo(case, files=None, branch="feature/#7-x", change=None, base="main"):
    """main with one commit; the Issue branch with `change` committed (default lib/a.dart)."""
    d = repo(case, dict({"README.md": "hi\n", "lib/a.dart": "int a() => 1;\n",
                         "docs/specs/7/skeleton.md": "# skeleton\n", "docs/specs/7/test-cases.md": "| C1 | a |\n"},
                        **(files or {})), branch=base)
    git(d, "switch", "-q", "-c", branch)
    for rel, text in (change or {"lib/a.dart": "int a() => 2;\n", "test/a_test.dart": "test('a', () {});\n"}).items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)
    git(d, "add", "-A")
    git(d, "commit", "-qm", "work")
    return d


class XHarness(Harness):
    def __init__(self, case, comments=(), labels=("guild:execute",), roles=(), judges=None, suites=(),
                 unattended=True, root=None, config=None, prs=(), body="Issue body", push_fail=None, author="OWNER",
                 **kw):
        cm = list(comments)
        if not any(DESIGN.split("\n")[0] in (c.get("body") or "") for c in cm):
            cm.insert(0, comment(DESIGN, 50))
        root = root or wt_repo(case)
        fx = fixture(labels=labels, comments=cm, prs=prs, body=body)
        if author is not None:                  # K4r3-m2: execute reads the net marker only from a member's body
            fx["issues"]["7"]["author_association"] = author
        Harness.__init__(self, case, fx, roles=roles, judges=judges, suites=suites, unattended=unattended,
                         root=root, config=config or XCFG, base="main", test_cases=None, **kw)
        self.p.branch = "feature/#7-x"
        self.p.vcs = VC.Vcs(root)
        self.p.remote_url = "/nonexistent/remote.git"
        self.pushes = []
        self.push_fail = push_fail

        def push():
            if self.push_fail:
                raise X.PushProblem(*self.push_fail)
            self.pushes.append(self.p.branch)
            return "sha"
        self.p.push_branch = push
        self.p.stage_start = "2026-11-16T00:00:30Z"

    def audit(self):
        b = self.body_with(AU.NAME)
        return AU.AuditRecord.parse(b) if b else None


def auditor(findings=()):
    return role("DONE", None, findings=list(findings))


def dev(status="DONE", line=None, **extras):
    extras.setdefault("tests", ["test/a_test.dart"])
    extras.setdefault("impl_files", ["lib/a.dart"])
    extras.setdefault("baselines", ["none"])
    extras.setdefault("branch", "feature/#7-x")
    extras.setdefault("pr_summary_path", "out/pr.md")
    return role(status, line, **extras)


def finding(sev="BLOCKER", f="lib/a.dart", line=1, text="returns the wrong value", axis="spec"):
    return {"severity": sev, "axis": axis, "file": f, "line": line, "finding": text, "why": "w"}


def dump(o):
    return json.dumps(o, ensure_ascii=False, indent=1)


def neutral(s):
    return markers.clean(s)
