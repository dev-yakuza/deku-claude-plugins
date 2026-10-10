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

    def test_several_holds_then_pr_all_recorded(self):
        self.write("notes/draft.txt", "user's own untracked file outside build inputs")
        p = self.run_batch({"t0001": "held:research", "t0002": "held:rejected", "t0003": "pr"})
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        topics = {t["id"]: t for t in store.load_topics(self.root)["topics"]}
        self.assertEqual((topics["t0001"]["state"], topics["t0001"]["reason"]), ("held", "research"))
        self.assertEqual((topics["t0002"]["state"], topics["t0002"]["reason"]), ("held", "rejected"))
        summary = json.loads(p.stdout[p.stdout.index("{"):])
        self.assertEqual([x[0] for x in summary["pr"]], ["t0003"])
        self.assertTrue(os.path.exists(os.path.join(self.root, "notes/draft.txt")))
        self.assertEqual(sh(self.root, "git", "status", "--porcelain", "--untracked-files=no").strip(), "")

    def test_preserve_without_image_dir_and_incomplete_child(self):
        p = self.run_batch({"t0001": "branch-budget", "t0002": "branch-nothing", "t0003": "pr"})
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        topics = {t["id"]: t for t in store.load_topics(self.root)["topics"]}
        self.assertEqual(topics["t0001"]["reason"], "budget")
        self.assertEqual(topics["t0002"]["reason"], "needs-human")
        # preserved branches carry the work; base is clean
        log = sh(self.root, "git", "log", "--format=%s", "herald/t0001--post-t0001")
        self.assertIn("wip(herald): t0001", log)
        self.assertEqual(sh(self.root, "git", "status", "--porcelain").strip(), "")

    def test_sloppy_rejected_child_leaves_no_residue(self):
        p = self.run_batch({"t0001": "branch-rejected-sloppy"}, n=1)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.root, "src/content/blog/post-t0001.md")))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/work/t0001")))

    def test_requeued_reverted_topic_old_pr_is_not_success(self):
        self.set_prs([{"number": 7, "state": "MERGED", "headRefName": "herald/t0001--old", "mergedAt": "2026-01-01T00:00:00Z",
                       "labels": ["herald", "herald:reverted"]}])
        p = self.run_batch({"t0001": "nothing"}, n=1)
        summary = json.loads(p.stdout[p.stdout.index("{"):])
        self.assertEqual(summary["pr"], [])
        self.assertEqual(summary["incomplete"], ["t0001"])

    def test_auto_with_hold_ship_child_can_sync(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp)); cfg["autonomy"]["publish"] = "auto"
        with open(cfgp, "w") as f:
            json.dump(cfg, f)
        self.commit("auto"); sh(self.root, "git", "push", "-q", "origin", "main")
        other = os.path.join(self.tmp, "other")
        sh(self.tmp, "git", "clone", "-q", self.origin, other)
        sh(other, "git", "config", "user.email", "o@x"); sh(other, "git", "config", "user.name", "o")
        os.environ["HRD_FAKE_OTHER_CLONE"] = other
        # a PR head with a clean critique so auto selection picks it
        from test_batch import AutoSelectionCase  # noqa
        sh(self.root, "git", "switch", "-q", "-c", "herald/t0002--post-t0002")
        self.write(".claude/herald/work/t0002/critique.json", json.dumps({"final_round": {"verdict": "PASS", "audit": {}}}))
        self.write(".claude/herald/work/t0002/state.json", json.dumps({"topic_id": "t0002", "slug": "post-t0002"}))
        self.write("src/content/blog/post-t0002.md", "x")
        self.commit("pr head")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:refs/pull/100/head")
        sh(self.root, "git", "switch", "-q", "main")
        sh(self.root, "git", "branch", "-q", "-D", "herald/t0002--post-t0002")
        p = self.run_batch({"t0001": "held:research", "t0002": "pr"}, n=2)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        summary = json.loads(p.stdout[p.stdout.index("{"):])
        self.assertEqual(summary["auto"]["chosen"], [["t0002", 100]])
        ship = json.load(open(os.path.join(self.root, ".claude/herald/memory/batch/ship.json")))
        self.assertEqual(ship["merged"], [100])
        # no ledger line for the merged article on this machine → integrity refuses to deploy
        self.assertFalse(summary["auto"]["published"])

    def test_runner_refuses_to_push_foreign_base_commits(self):
        from hrdlib import batch as b
        self.write("README.md", "moved base")
        self.commit("foreign")  # e.g. a child moved base with update-ref
        self.assertFalse(b.push_base(self.root, self.cfg))
        self.assertNotEqual(sh(self.root, "git", "rev-parse", "origin/main").strip(),
                            sh(self.root, "git", "rev-parse", "main").strip())

    def test_vanished_record_commit_blocks_push(self):
        from hrdlib import batch as b
        data = store.load_topics(self.root)
        store.set_topic_state(store.get_topic(data, "t0001"), "held", "research")
        store.save_topics(self.root, data)
        sha = b.remember(commits.commit_state(self.root, self.cfg, "runner", "hold", "hold", [".claude/herald/topics.json"]))
        sh(self.root, "git", "reset", "-q", "--hard", "HEAD~1")  # e.g. a child reset base
        self.assertFalse(b.push_base(self.root, self.cfg))
        b.LAST_RECORD["sha"] = None

    def test_detach_writes_pid_and_summary(self):
        import time
        with open(self.plan, "w") as f:
            json.dump({"t0001": "held:research"}, f)
        env = dict(os.environ, HRD_CLAUDE=os.path.join(HERE, "fake_claude.py"), HRD_FAKE_CLAUDE_PLAN=self.plan,
                   HRD_SCRIPTS=SCRIPTS)
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "batch_runner.py"), "--n", "1", "--detach"],
                           cwd=self.root, capture_output=True, text=True, env=env, timeout=60, stdin=subprocess.DEVNULL)
        info = json.loads(p.stdout)
        self.assertTrue(info["detached"])
        deadline = time.time() + 120
        out = ""
        while time.time() < deadline:
            if os.path.exists(info["summary"]):
                out = open(info["summary"]).read()
                if out.strip().endswith("}"):
                    break
            time.sleep(2)
        self.assertIn('"held"', out)
        self.assertTrue(os.path.exists(info["pid_file"]))

    def test_throttle_ignores_old_or_reverted_auto_merges(self):
        from hrdlib import batch as b
        topics = {"topics": [{"auto_merged_pr": 1, "auto_merged_at": "2000-01-01T00:00:00+00:00", "state": "queued"},
                             {"auto_merged_pr": 2, "auto_merged_at": b.now_iso(), "state": "held", "reason": "reverted"},
                             {"auto_merged_pr": 3, "auto_merged_at": b.now_iso(), "state": "queued"}]}
        self.assertEqual(b.auto_published_today({"articles": []}, topics), 1)

    def test_untracked_build_input_blocks_batch(self):
        self.write("src/content/blog/wip.md", "unfinished")
        p = self.run_batch({}, n=1)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("untracked files in build inputs", p.stderr)

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
