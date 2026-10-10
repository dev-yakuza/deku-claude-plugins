"""Batch runner (plan §3.2.1): completion judged from GitHub/result files, holds recorded by the
runner with the Herald-Record trailer, budget kill preserves work, auto selection exclusions."""

import json
import os
import subprocess
import sys
import unittest

from helpers import HERE, SCRIPTS, RepoCase, sh

from hrdlib import batch, commits, store


class BatchCase(RepoCase):
    def setUp(self):
        super().setUp()
        data = {"version": 1, "topics": []}
        for i in range(1, 4):
            t = {"id": "t%04d" % i, "title": "T%d" % i, "state": "queued", "history": [], "reverted_by": []}
            data["topics"].append(t)
        store.save_topics(self.root, data)
        cfg = json.load(open(os.path.join(self.root, ".claude/herald/config.json")))
        cfg["budget"] = {"per_article_usd": 1.0}
        with open(os.path.join(self.root, ".claude/herald/config.json"), "w") as f:
            json.dump(cfg, f)
        self.commit("topics")
        sh(self.root, "git", "push", "-q", "origin", "main")
        self.plan = os.path.join(self.tmp, "plan.json")

    def run_batch(self, plan, n=3):
        with open(self.plan, "w") as f:
            json.dump(plan, f)
        env = dict(os.environ, HRD_CLAUDE=os.path.join(HERE, "fake_claude.py"), HRD_FAKE_CLAUDE_PLAN=self.plan,
                   HRD_SCRIPTS=SCRIPTS)
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "batch_runner.py"), "--n", str(n)], cwd=self.root,
                           capture_output=True, text=True, env=env, timeout=600, stdin=subprocess.DEVNULL)
        return p

    def test_outcomes_and_hold_commit(self):
        p = self.run_batch({"t0001": "pr", "t0002": "held:research", "t0003": "nothing"})
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        summary = json.loads(p.stdout[p.stdout.index("{"):])
        self.assertEqual([x[0] for x in summary["pr"]], ["t0001"])
        self.assertEqual(summary["held"], [["t0002", "research"]])
        self.assertEqual(summary["incomplete"], ["t0003"])
        topics = {t["id"]: t for t in store.load_topics(self.root)["topics"]}
        self.assertEqual(topics["t0002"]["state"], "held")
        self.assertEqual(topics["t0003"]["reason"], "needs-human")
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        self.assertEqual(commits.trailer(self.root, head), "hold")
        # approve mode pushes the hold record right away
        self.assertEqual(sh(self.root, "git", "rev-parse", "origin/main").strip(), head)
        self.assertIsNone(store.paths and __import__("hrdlib.lock", fromlist=["x"]).status(self.root))

    def test_budget_kill_holds_budget(self):
        p = self.run_batch({"t0001": "budget"}, n=1)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        t = store.get_topic(store.load_topics(self.root), "t0001")
        self.assertEqual((t["state"], t["reason"]), ("held", "budget"))

    def test_foreign_unpushed_commit_stops_batch(self):
        self.write("README.md", "human")
        self.commit("human")
        p = self.run_batch({}, n=1)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("not Herald records", p.stderr)


class AutoSelectionCase(RepoCase):
    def make_pr_head(self, tid, slug, number, critique, images=False):
        sh(self.root, "git", "switch", "-q", "-c", store.branch_name(tid, slug))
        self.write(".claude/herald/work/%s/critique.json" % tid, json.dumps(critique))
        self.write(".claude/herald/work/%s/state.json" % tid, json.dumps({"topic_id": tid, "slug": slug}))
        self.write("src/content/blog/%s.md" % slug, "x")
        if images:
            self.write("public/blog-images/%s/01.png" % slug, b"img", binary=True)
        self.commit("pr")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:refs/pull/%d/head" % number)
        sh(self.root, "git", "switch", "-q", "main")

    def test_exclusions(self):
        ok = {"final_round": {"verdict": "PASS", "audit": {"blocker": 0, "major": 0}}, "decision_log": [{"kind": "routine"}]}
        dismissed = {"final_round": {"verdict": "PASS", "audit": {"blocker": 0, "major": 1}, "dismissed": {"major": 1}},
                     "decision_log": [{"kind": "dismissal"}]}
        self.make_pr_head("t0001", "a", 1, ok)
        self.make_pr_head("t0002", "b", 2, dismissed)
        self.make_pr_head("t0003", "c", 3, ok, images=True)
        self.make_pr_head("t0004", "d", 4, ok)
        chosen, skipped = batch.auto_candidates(self.root, self.cfg, [("t0001", 1), ("t0002", 2), ("t0003", 3), ("t0004", 4)])
        self.assertEqual(chosen, [("t0001", 1), ("t0004", 4)])
        reasons = dict(skipped)
        self.assertIn("decision:dismissal", reasons["t0002"])
        self.assertIn("images", reasons["t0003"])
        # throttle (max_per_day=2) reached
        chosen, skipped = batch.auto_candidates(self.root, self.cfg, [("t0001", 1), ("t0004", 4), ("t0002", 2)])
        self.assertEqual(len(chosen), 2)


if __name__ == "__main__":
    unittest.main()
