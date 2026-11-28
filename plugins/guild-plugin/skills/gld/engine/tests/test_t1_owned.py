"""Readiness T1 P5 — `engine.py owned` (the stage commands' engine guard, `_preflight.md` Section 0) and the `exists`
field of `engine.py status --json`. Read only: nothing is written to GitHub or the records."""

import io
import json
import tempfile
import unittest

from gxengine import cli, paths as pathsmod, store
from tests import c_world as W
from tests.helpers import fakes

SUMMARY = "<!-- guild:summary -->\n**Guild (gld)** analyze"


def comment(cid, body):
    return {"id": cid, "user": {"login": "x"}, "author_association": "MEMBER", "body": body, "created_at": "t"}


def rules(refs=(), prs=(), comments=(), fail=None):
    """gh rules of the three reads: matching-refs of gld/42, pulls of head gld/42, the Issue's comments."""
    q = f"repos/{W.REPO}/"
    out = [{"args": ["api", q + "git/matching-refs/heads/gld/42"], "json": [{"ref": r} for r in refs]},
           {"args": ["api", q + "pulls?head=acme%3Agld%2F42&state=all"], "json": list(prs)},
           {"args": ["api", q + f"issues/{W.ISSUE}/comments", "--paginate"], "json": list(comments)}]
    if fail is not None:
        out[fail] = dict(out[fail], exit_code=1, stderr="HTTP 502")
    return {"rules": out}


def open_pr(n, ref="gld/42"):
    return {"number": n, "state": "open", "merged_at": None, "head": {"ref": ref, "sha": "a" * 40}, "base": {"ref": "main"}}


class Owned(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.w = W.World(self._tmp.name)

    def owned(self, gh_rules, as_json=True):
        self.w.set_gh(gh_rules)
        out = io.StringIO()
        argv = ["owned", "--repo", W.REPO, "--issue", str(W.ISSUE)] + (["--json"] if as_json else [])
        rc = cli.main(argv, environ=self.w.environ, out=out, units=W.units(self.w))
        return rc, (json.loads(out.getvalue()) if as_json else out.getvalue())

    def records(self):
        """The contract example state of acme/app#42 as this machine's engine record."""
        paths = pathsmod.EnginePaths(pathsmod.engine_home(self.w.environ), W.REPO, W.ISSUE)
        with open(fakes.fixture("contracts", "state.stage4.example.json"), encoding="utf-8") as f:
            store.save_state(paths, json.load(f))

    def test_a_plain_issue_is_free(self):
        rc, rep = self.owned(rules(refs=("refs/heads/gld/421",), prs=[dict(open_pr(3), state="closed")],
                                   comments=[comment(1, "Looks good\n<!-- guild:summary -->")]))
        self.assertEqual(rc, 0)
        self.assertEqual((rep["owned"], rep["records"], rep["remote_branch"], rep["open_pr"], rep["summary_comment"]),
                         (False, False, False, None, None))
        rc, text = self.owned(rules(), as_json=False)
        self.assertEqual((rc, text), (0, "not an engine Issue: acme/app#42\n"))

    def test_each_mark_alone_refuses(self):
        for name, gh in (("remote branch", rules(refs=("refs/heads/gld/42",))),
                         ("open pull request", rules(prs=[open_pr(8)])),
                         ("summary comment", rules(comments=[comment(5, "hi"), comment(9, SUMMARY)]))):
            with self.subTest(name):
                rc, rep = self.owned(gh)
                self.assertEqual((rc, rep["owned"]), (4, True))
        rc, text = self.owned(rules(refs=("refs/heads/gld/42",), prs=[open_pr(8)], comments=[comment(9, SUMMARY)]),
                              as_json=False)
        self.assertEqual(rc, 4)
        self.assertEqual(text, "engine Issue acme/app#42: gld/42 on the remote, its pull request #8, the engine's summary "
                               "comment — use /gld resume 42 (state: /gld status 42)\n")

    def test_records_on_this_machine_refuse(self):
        self.records()
        rc, rep = self.owned(rules())
        self.assertEqual((rc, rep["owned"], rep["records"]), (4, True, True))

    def test_github_not_answering_never_passes(self):
        for fail in (0, 1, 2):
            with self.subTest(fail=fail):
                rc, rep = self.owned(rules(fail=fail))
                self.assertEqual((rc, rep["owned"]), (4, None))
                self.assertTrue(rep["problem"])
        rc, text = self.owned(rules(fail=2), as_json=False)
        self.assertTrue(text.startswith("cannot tell whether the engine works on acme/app#42"))

    def test_records_decide_even_when_github_does_not_answer(self):
        self.records()
        rc, rep = self.owned(rules(fail=0))
        self.assertEqual((rc, rep["owned"]), (4, True))

    def test_nothing_is_written(self):
        self.owned(rules(refs=("refs/heads/gld/42",)))
        self.assertFalse([c for c in self.w.gh_calls() if "-X" in c["argv"]])

    def test_status_json_says_whether_records_exist(self):
        out = io.StringIO()
        self.assertEqual(cli.main(["status", "--repo", W.REPO, "--issue", "42", "--json"], environ=self.w.environ,
                                  out=out), 0)
        self.assertIs(json.loads(out.getvalue())["exists"], False)
        self.records()
        out = io.StringIO()
        cli.main(["status", "--repo", W.REPO, "--issue", "42", "--json"], environ=self.w.environ, out=out)
        self.assertIs(json.loads(out.getvalue())["exists"], True)


class Taken(unittest.TestCase):
    """Readiness T1 P7: `engine.py taken` — what sprint plan leaves out (an open pull request on any branch closes the
    Issue; gld/N is on the remote). Two reads, nothing written."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.w = W.World(self._tmp.name)

    def taken(self, prs=(), refs=(), fail=False, as_json=True):
        q = f"repos/{W.REPO}/"
        pr_rule = {"args": ["pr", "list", "--repo", W.REPO, "--state", "open", "--limit", "*", "--json",
                            "number,headRefName,body,closingIssuesReferences"]}
        pr_rule.update({"exit_code": 1, "stderr": "HTTP 502"} if fail else {"json": list(prs)})
        self.w.set_gh({"rules": [pr_rule, {"args": ["api", q + "git/matching-refs/heads/gld/", "--paginate"],
                                           "json": [{"ref": r} for r in refs]}]})
        out = io.StringIO()
        rc = cli.main(["taken", "--repo", W.REPO] + (["--json"] if as_json else []), environ=self.w.environ, out=out,
                      units=W.units(self.w))
        return rc, (json.loads(out.getvalue()) if as_json and rc == 0 else out.getvalue())

    def test_both_kinds(self):
        ref7 = {"number": 7, "repository": {"name": "app", "owner": {"login": "acme"}}}
        prs = [{"number": 1924, "headRefName": "feature/#5-a", "body": "Fixes #5 and closes #6",
                "closingIssuesReferences": []},
               {"number": 1925, "headRefName": "fix/x", "body": "", "closingIssuesReferences": [ref7]},
               {"number": 1926, "headRefName": "y", "body": "Refs #8", "closingIssuesReferences": []}]
        rc, rep = self.taken(prs, refs=("refs/heads/gld/12", "refs/heads/gld/12-old", "refs/heads/gld/x"))
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(rep["closing_prs"]), ["5", "6", "7"])
        self.assertEqual(rep["closing_prs"]["7"], [{"number": 1925, "head": "fix/x", "via": "reference"}])
        self.assertEqual(rep["engine_branches"], [12])
        rc, text = self.taken(prs, refs=("refs/heads/gld/12",), as_json=False)
        self.assertIn("  #5: open pull request #1924 (feature/#5-a)\n", text)
        self.assertIn("  #12: gld/12 on the remote\n", text)
        self.assertFalse([c for c in self.w.gh_calls() if "-X" in c["argv"]])

    def test_github_not_answering_refuses(self):
        rc, text = self.taken(fail=True, as_json=False)
        self.assertEqual(rc, 4)
        self.assertIn("cannot tell which Issues are taken", text)
