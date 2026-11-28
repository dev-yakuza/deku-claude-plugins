"""VA2 — the tracking Issue, the run marker, the dependency facts (fake gh, sprint-700.json)."""

import json
import os
import tempfile
import unittest

from gxengine import github, sprintdag, sprinttracker as T
from tests.c_world import PLUGIN_ROOT
from tests.helpers import fakes

SHA = "a" * 40
R = "repos/acme/app/"


def sprint(**over):
    with open(fakes.fixture("contracts", "sprint-state.example.json"), encoding="utf-8") as f:
        return dict(json.load(f), **over)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self.n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def gh(self, rules=None):
        """The sprint-700 rules; `rules` (tuples args → answer) come first."""
        with open(fakes.gh_fixture("sprint-700.json"), encoding="utf-8") as f:
            base = json.load(f)["rules"]
        self.n += 1
        path, self.log = os.path.join(self.tmp, f"gh{self.n}.json"), os.path.join(self.tmp, f"log{self.n}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rules": [dict(r) for r in rules or ()] + base}, f)
        env = fakes.fake_env(gh_fixtures=path, gh_log=self.log)
        return github.Gh("acme/app", env=env, plugin_root=PLUGIN_ROOT)

    def calls(self):
        return fakes.gh_calls(self.log)


def comments(*rows):
    return {"args": ["api", R + "issues/700/comments", "--paginate"], "json": [
        {"id": i, "user": {"login": "x"}, "author_association": assoc, "created_at": "z", "body": body}
        for i, assoc, body in rows]}


class Read(Base):
    def test_the_tracker(self):
        gh = self.gh()
        t = T.read(gh, 700)
        self.assertEqual((t.number, t.state, t.run), (700, "OPEN", None))
        self.assertEqual([m.issue for m in sprintdag.parse_table(t.body)], [101, 102, 103])
        run = T.read(gh, 700).run                         # the second read: the marker exists
        self.assertEqual((run["id"], run["data"]["host"]), (7001, "mac"))
        self.assertFalse([c for c in self.calls() if "-X" in c["argv"]], "reads write nothing")

    def test_the_oldest_collaborator_marker_counts(self):
        m = "<!-- guild:sprint:run -->\n```json\n{\"host\": \"%s\"}\n```\n<!-- /guild:sprint:run -->"
        gh = self.gh([comments((9, "MEMBER", m % "new"), (5, "OWNER", "hi\n" + m % "old"), (2, "NONE", m % "evil"))])
        self.assertEqual(T.read(gh, 700).run, {"id": 5, "data": {"host": "old"}})
        for text in ("<!-- guild:sprint:run -->", "<!-- guild:sprint:run -->\n```json\n{oops\n```", "<!-- guild:sprint:run -->\n[1]"):
            self.assertEqual(T.read(self.gh([comments((5, "OWNER", text))]), 700).run, {"id": 5, "data": None})

    def test_a_pull_request_or_a_missing_issue_is_no_tracker(self):
        for n in (900, 999):
            with self.assertRaises(github.GhError):
                T.read(self.gh([{"args": ["api", R + "issues/999"], "exit_code": 1, "stderr": "gh: Not Found (HTTP 404)"}]), n)


class Marker(Base):
    """TM / R11: one comment, the 0.98.7 keys, codes and numbers only."""

    def body(self):
        return json.loads(self.calls()[-1]["stdin"])["body"]

    def test_created_once_then_patched(self):
        gh = self.gh()
        self.assertEqual(T.write_marker(gh, 700, None, sprint()), 7001)
        self.assertEqual(self.calls()[-1]["argv"][:3], ["api", "-X", "POST"])
        self.assertEqual(T.write_marker(gh, 700, 7001, sprint()), 7001)
        self.assertEqual(self.calls()[-1]["argv"], ["api", "-X", "PATCH", R + "issues/comments/7001", "--input", "-"])
        text = self.body()
        self.assertTrue(text.startswith("<!-- guild:sprint:run -->\n```json\n"))
        self.assertTrue(text.endswith("```\n<!-- /guild:sprint:run -->\n"))
        back = T._marker_data(text)
        self.assertEqual(set(back), {"host", "pid", "state", "started", "heartbeat", "window", "completion", "run",
                                     "allow_red_base", "members"})
        self.assertEqual((back["state"], back["completion"], back["window"]), ("running", None, "22:00-10:00"))
        self.assertEqual(back["members"][2], {"issue": 103, "outcome": "blocked", "block": "dep-stopped", "cause": 102,
                                              "stop_reason": None, "pr": None, "draft": False})
        self.assertNotIn("/", text.replace("<!-- /guild:", "").replace("22:00-10:00", ""))

    def test_an_ended_run_has_its_completion(self):
        obj = T.marker_object(sprint(state="halted", halt="signal"), "2026-11-25T01:02:03Z")
        self.assertEqual(obj["state"], "halted:signal")
        self.assertEqual((obj["completion"]["done"], obj["completion"]["stopped"], obj["completion"]["not-started"]), ([101], [102], [104]))
        self.assertEqual(T.marker_object(sprint(state="finished"), "x")["state"], "finished")

    def test_a_failed_write_is_an_error(self):
        gh = self.gh([{"args": ["api", "-X", "PATCH", R + "issues/comments/7001", "--input", "-"], "exit_code": 1, "stderr": "HTTP 502"}])
        with self.assertRaises(github.GhError):
            T.write_marker(gh, 700, 7001, sprint())

    def test_the_red_base_comment(self):
        gh = self.gh()
        T.base_red_comment(gh, 700, SHA, ["test", "lint"], None)
        self.assertIn("`test`, `lint`", self.body())
        T.base_red_comment(gh, 700, SHA, [], "worktree")
        self.assertIn("not checked: `worktree`", self.body())


class Settings(Base):
    def rule(self, answer):
        return [dict({"args": ["repo", "view", "acme/app", "--json", "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"]}, **answer)]

    def test_merge_settings(self):
        self.assertEqual(T.merge_settings(self.gh()), {"merge": False, "squash": True, "rebase": False})
        for answer in ({"exit_code": 1, "stderr": "x"}, {"stdout": "nope"}, {"json": {}}, {"json": []},
                       {"json": {"mergeCommitAllowed": None, "squashMergeAllowed": True, "rebaseMergeAllowed": False}}):
            self.assertIsNone(T.merge_settings(self.gh(self.rule(answer))), answer)

    def test_default_branch(self):
        self.assertEqual(T.default_branch(self.gh()), "main")
        for answer in ({}, {"defaultBranchRef": None}, {"defaultBranchRef": {"name": "-x"}}):
            with self.assertRaises(github.GhError):
                T.default_branch(self.gh([{"args": ["repo", "view", "acme/app", "--json", "defaultBranchRef"], "json": answer}]))


class Facts(Base):
    LOCAL = {"finished": True, "stopped": False, "pr_number": 900}

    def test_issue_facts(self):
        self.assertEqual(T.issue_facts(self.gh(), 103), {"number": 103, "state": "CLOSED", "state_reason": "COMPLETED", "labels": []})
        with self.assertRaises(github.GhError):
            T.issue_facts(self.gh(), 900)

    def test_dep_facts(self):
        gh = self.gh()
        f = T.dep_facts(gh, 101, self.LOCAL)
        self.assertEqual(f.prs, [{"number": 900, "state": "OPEN", "head_sha": SHA, "base": "main"}])
        self.assertIn("pulls/900", self.calls()[-1]["argv"][-1])
        self.assertEqual(sprintdag.member_state(f).base, "stack")
        f = T.dep_facts(gh, 101, None, outcome="done")
        self.assertEqual((len(f.prs), f.outcome), (1, "done"))
        self.assertEqual(sprintdag.member_state(f).block, "dep-not-done")
        f = T.dep_facts(gh, 103, None)
        self.assertEqual((f.prs[0]["state"], sprintdag.member_state(f).base), ("MERGED", "default"))
        self.assertEqual(T.dep_facts(gh, 102, None).prs, [])

    def test_an_unexpected_answer_is_never_a_guess(self):
        ok = {"number": 900, "state": "open", "merged_at": None, "head": {"ref": "gld/101", "sha": SHA}, "base": {"ref": "main"}}
        for over in ({"number": 901}, {"head": {"ref": "gld/102", "sha": SHA}}, {"head": {"ref": "gld/101", "sha": "main"}},
                     {"state": "weird"}, {"base": {}}, {"number": True}):
            gh = self.gh([{"args": ["api", R + "pulls/900"], "json": dict(ok, **over)}])
            with self.subTest(over=over), self.assertRaises(github.GhError):
                T.dep_facts(gh, 101, self.LOCAL)
        with self.assertRaises(github.GhError):
            T.dep_facts(self.gh([{"args": ["api", R + "issues/101"], "exit_code": 1, "stderr": "HTTP 502"}]), 101, None)

    def test_remote_state(self):
        gh = self.gh()
        self.assertEqual(T.remote_state(gh, 102), {"branch": False, "open_pr": None})
        self.assertEqual(T.remote_state(gh, 101), {"branch": True, "open_pr": 900})
        self.assertEqual(T.remote_state(gh, 10), {"branch": False, "open_pr": None}, "a prefix is another branch")
        with self.assertRaises(github.GhError):
            T.remote_state(self.gh([{"args": ["api", R + "git/matching-refs/heads/gld/102"], "json": {"ref": "x"}}]), 102)


if __name__ == "__main__":
    unittest.main()
