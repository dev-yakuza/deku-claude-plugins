"""Helpers for the K2 engine tests: a fake GitHub + writer + decision log, canned roles/judges/suites."""

import json
import os

import _util  # noqa: F401  (engine on sys.path, gh blocked)
from _k1 import Clock, repo, tmpdir, git  # noqa: F401

from guildcore.adapters.gh import FakeGh, FakeGhWrite
from guildcore.checks import CheckResult
from guildcore.decisions import DecisionWriter
from guildcore.judges.runner import Decision
from guildcore.records.write import GhWriter
from guildcore.roles.runner import RoleResult, stage_inputs
from workflows.dev.stages.base import Ports

# K5r4: the K2–K4 fixtures test the steady state — first-sprint mode (§10.4: auto = on until a recorded go) changes
# asks, EX-ARB dismissals and HANDOFF shadows, so it is off here and tested on purpose (test_k5_r4_first_sprint)
CFG = {"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": "off"},
       "commands": {"test": "flutter test", "e2e": "flutter test integration_test/app_test.dart", "vrt": None},
       "visual": {"baselines": ["test/**/goldens/**"], "tests": [], "config_files": [],
                  "runnable": True, "env": "macOS arm64 local"}}

FLUTTER_GREEN = "00:01 +1: a\n00:02 +2: b\n03:19 +2: All tests passed!\n"
FLUTTER_RED = "00:01 +1: a\n00:02 +1 -1: widget shows title [E]\n00:03 +1 -1: Some tests failed.\n"


def fixture(labels=("guild:test",), comments=(), prs=(), body="Issue body", n=7, extra_issues=None, author="OWNER"):
    # K5 (K4r2-m10): execute/test/qa read the Issue text through the three-valued author trust — the fixture's
    # Issue carries its author's association (None = unreadable)
    fx = {"repo": "o/r", "issues": {str(n): {"number": n, "title": "t", "body": body, "state": "OPEN",
                                             "author_association": author,
                                             "url": "https://github.com/o/r/issues/%d" % n,
                                             "labels": [{"name": l} for l in labels],
                                             "comments": list(comments), "timeline": []}},
          "prs": list(prs), "check_runs": {}, "annotations": {}}
    for k, v in (extra_issues or {}).items():
        fx["issues"][str(k)] = v
    for pr in prs:
        fx["issues"].setdefault(str(pr["number"]), {"number": pr["number"], "labels": [], "comments": [],
                                                    "url": "https://github.com/o/r/pull/%d" % pr["number"]})
    return fx


def comment(body, cid, at="2026-11-15T00:00:00Z"):
    return {"id": cid, "body": body, "created_at": at, "updated_at": at, "author_association": "OWNER",
            "user": {"login": "owner"}}


def role(status="DONE", line=None, **extras):
    return RoleResult(status, line, extras)


def decision(choice, fields, by="judge:sonnet", unsure=False, coerced=False, coerced_by=None):
    return Decision(choice, fields, by, "d" * 12, unsure, coerced, coerced_by, None)


def suite(raw, passed=True, rc=0, timed_out=False):
    return CheckResult(passed, rc, timed_out, raw, [{"cmd": "flutter test", "rc": rc, "timed_out": timed_out}],
                       3600, "x" if timed_out else None)


class Harness(object):
    def __init__(self, case, fx, roles=(), judges=None, suites=(), unattended=True, root=None,
                 config=None, host="macOS arm64", base=None, impl_files=None, checks=None, n=7,
                 test_cases="| C1 | a |\n| C2 | b |\n"):
        self.case = case
        self.gh = FakeGh(fx)
        self.clock = Clock()
        self.w = FakeGhWrite(self.gh, self.clock)
        self.writer = GhWriter(self.gh, self.w, sleep=lambda s: None)
        self.decisions = DecisionWriter(self.writer, n, self.clock)
        self.roles = list(roles)
        self.judges = judges if judges is not None else {}
        self.suites = list(suites)
        self.calls = {"roles": [], "judges": [], "suites": [], "checks": []}
        self.captures = []
        self.marks = []
        self.pushed = []
        self.checks = list(checks or [])
        self.p = Ports(n, self.gh, self.writer, self.decisions, self.clock, config or CFG,
                       root or tmpdir(case), unattended=unattended, run_role=self._role, judge=self._judge,
                       suite=self._suite, check=self._check, capture=self._capture, mark=self.marks.append,
                       host=host, base=base, impl_files=impl_files, branch="feature/7-x",
                       push=lambda: self.pushed.append(1))
        self.n = n
        if test_cases is not None and root is None:
            self.write_file("docs/specs/%d/test-cases.md" % n, test_cases)

    def _role(self, call):
        self.calls["roles"].append(call)
        # 0.102.1: every role call's inputs go through the real runner's staging, so an input the live runner cannot
        # stage (a text read as a path) fails here instead of only in a real repo
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            stage_inputs(td, getattr(call, "inputs", None))
        if not self.roles:
            raise AssertionError("unexpected role call %s-%s" % (call.role, call.task))
        r = self.roles.pop(0)
        return r(call) if callable(r) else r

    def _judge(self, spec):
        self.calls["judges"].append(spec)
        q = self.judges.get(spec.group)
        if q is None:
            raise AssertionError("unexpected judge %s" % spec.group)
        d = q.pop(0) if isinstance(q, list) else q
        return d(spec) if callable(d) else d

    def _suite(self, cmds, owner, timeout_s):
        self.calls["suites"].append(cmds)
        return self.suites.pop(0)

    def _check(self, cmd, cwd, owner, timeout_s, write_dirs):
        self.calls["checks"].append((cmd, cwd))
        if self.checks:
            return self.checks.pop(0)
        from guildcore import checks as CH
        return CH.run_command([cmd], timeout_s, cwd=cwd)

    def _capture(self, kind, stage, role, summary, evidence, area, surprise):
        self.captures.append((kind, stage, role, summary, surprise))

    # -- reads --------------------------------------------------------------------------------
    def issue(self):
        return self.gh.fx["issues"][str(self.n)]

    def labels(self):
        return sorted(l["name"] for l in self.issue()["labels"])

    def bodies(self, n=None):
        return [c["body"] for c in self.gh.fx["issues"][str(n or self.n)].get("comments", [])]

    def body_with(self, marker, n=None):
        hits = [b for b in self.bodies(n) if b.startswith("<!-- guild:%s -->" % marker)]
        return hits[-1] if hits else None

    def write_file(self, rel, text):
        p = os.path.join(self.p.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)


def judge_test(acs, verdict="effective", overall=None, covered_by=None):
    return decision(overall or ("all_effective" if verdict == "effective" else "gap"),
                    {"ac": [{"id": a, "covered_by": covered_by or ["test/a_test.dart::t"], "verdict": verdict,
                             "why": "w"} for a in acs], "visual_rows": [],
                     "overall": overall or ("all_effective" if verdict == "effective" else "gap")})


def judge_qa(verdict="pass", defects=(), checklist=(), bar="yes"):
    return decision(verdict, {"defects": list(defects), "checklist": list(checklist), "quality_bar_met": bar,
                              "verdict": verdict})


def dump(o):
    return json.dumps(o, ensure_ascii=False, indent=1)
