"""Safety tests from plan §7 that exercise the deterministic layer end to end."""

import json
import os
import unittest

from helpers import RepoCase, sh

from hrdlib import commits, ghstate, integrity, lock, store
from hrdlib.hashing import tree_hash, worktree_hash
from hrdlib.util import HeraldError


def write_machine(case, tid, name, obj, slug=None):
    """Verdict files carry the hash of the article they evaluated (plan §3.2)."""
    obj = json.loads(json.dumps(obj))
    if slug:
        h = worktree_hash(case.root, case.cfg, slug)
        if name == "critique.json":
            obj.setdefault("final_round", {})["body_hash"] = h
        else:
            obj["body_hash"] = h
    case.write(".claude/herald/work/%s/%s" % (tid, name), json.dumps(obj))


CRIT_PASS = {"final_round": {"round": 1, "verdict": "PASS", "audit": {"blocker": 0, "major": 0},
                             "dismissed": {"blocker": 0, "major": 0}}, "decision_log": []}
VER_PASS = {"counts": {"supported": 3, "unsupported": 0, "contradicted": 0, "unmapped": 0}}


class Flow(RepoCase):
    def run_flow(self, tid="t0001", slug="new-post"):
        """brief → … → verify on a herald branch, the way /hrd write drives it."""
        store.save_topics(self.root, {"version": 1, "topics": []})
        data = store.load_topics(self.root)
        t = {"id": tid, "title": "T", "state": "queued", "history": [], "reverted_by": []}
        data["topics"].append(t)
        store.save_topics(self.root, data)
        self.commit("topics")
        sh(self.root, "git", "push", "-q", "origin", "main")
        self.hrd("begin", "--topic", tid)
        self.write(".claude/herald/work/%s/brief.md" % tid, "brief")
        self.hrd("branch", "--topic", tid, "--slug", slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "brief")
        self.write(".claude/herald/work/%s/research.md" % tid, "C1 source")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "research")
        self.article(slug)
        self.write(".claude/herald/work/%s/claims-map.json" % tid, "{}")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        self.write(".claude/herald/work/%s/critique.md" % tid, "ok")
        write_machine(self, tid, "critique.json", CRIT_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        self.write(".claude/herald/work/%s/verify.md" % tid, "ok")
        write_machine(self, tid, "verify.json", VER_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        return tid, slug


class HashTests(Flow):
    def test_worktree_and_tree_modes_agree_and_ignore_derivatives(self):
        self.article("p1")
        self.write("public/blog-images/p1/01.webp", b"derived", binary=True)  # gitignored
        before = worktree_hash(self.root, self.cfg, "p1")
        sha = self.commit("p1")
        self.assertEqual(before, worktree_hash(self.root, self.cfg, "p1"))
        self.assertEqual(before, tree_hash(self.root, self.cfg, sha, "p1"))
        self.write("public/blog-images/p1/02.webp", b"more", binary=True)
        self.assertEqual(before, worktree_hash(self.root, self.cfg, "p1"))

    def test_untracked_change_changes_hash(self):
        self.article("p2")
        h1 = worktree_hash(self.root, self.cfg, "p2")
        self.write("src/content/blog/p2.md", "changed")
        self.assertNotEqual(h1, worktree_hash(self.root, self.cfg, "p2"))


class StageTests(Flow):
    def test_publish_refused_after_body_edit_post_verify(self):
        tid, slug = self.run_flow()
        self.hrd("finalize", "--topic", tid)
        with open(os.path.join(self.root, "src/content/blog/%s.md" % slug)) as f:
            self.write("src/content/blog/%s.md" % slug, f.read() + "x")
        _, p = self.hrd("finalize", "--topic", tid, check=False)
        self.assertNotEqual(p.returncode, 0)

    def test_skipping_critique_after_loopback_is_blocked(self):
        tid, slug = self.run_flow()
        self.hrd("loopback", "--topic", tid)
        self.write("src/content/blog/%s.md" % slug, "---\ntitle: a\ndescription: d\nslug: %s\ndate: x\n---\nrewritten body\n" % slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        # verify passes on the new body but critique evaluated the old one
        write_machine(self, tid, "verify.json", VER_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        _, p = self.hrd("finalize", "--topic", tid, check=False)
        self.assertIn("critique", p.stderr)

    def test_critique_needs_zero_undismissed_findings(self):
        tid, slug = self.run_flow()
        write_machine(self, tid, "critique.json", {"final_round": {"verdict": "PASS", "audit": {"blocker": 0, "major": 1},
                                                                   "dismissed": {"major": 0}}}, slug)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", check=False)
        self.assertNotEqual(p.returncode, 0)

    def test_loopback_cap_and_human_requests_not_counted(self):
        tid, _ = self.run_flow()
        for _ in range(3):
            out, _ = self.hrd("loopback", "--topic", tid)
        self.assertFalse(out["exhausted"])
        out, _ = self.hrd("loopback", "--topic", tid, "--human")
        self.assertEqual(out["loopbacks"], 3)
        out, _ = self.hrd("loopback", "--topic", tid)
        self.assertTrue(out["exhausted"])


class LedgerTests(Flow):
    def test_record_requires_verified_body(self):
        tid, slug = self.run_flow()
        rec, _ = self.hrd("ledger", "record", "--topic", tid)
        self.assertEqual(rec["verified_hash"], worktree_hash(self.root, self.cfg, slug))
        self.write("src/content/blog/%s.md" % slug, "tampered")
        _, p = self.hrd("ledger", "record", "--topic", tid, check=False)
        self.assertIn("refusing", p.stderr)

    def test_human_edit_reverify_path_can_record(self):
        """critique is not rerun on the human-edit path; --record keys on verify only."""
        tid, slug = self.run_flow()
        self.write("src/content/blog/%s.md" % slug, "human edited body")
        write_machine(self, tid, "verify.json", VER_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", "--amend")
        rec, _ = self.hrd("ledger", "record", "--topic", tid, "--kind", "push", "--sha", "abc")
        self.assertEqual(rec["kind"], "push")


class LockTests(RepoCase):
    def test_lock_reentry_and_conflict(self):
        tok = lock.acquire(self.root, "write")
        self.assertEqual(lock.acquire(self.root, "x", token=tok), tok)
        with self.assertRaises(HeraldError):
            lock.acquire(self.root, "ship")
        lock.release(self.root, tok)
        self.assertIsNone(lock.status(self.root))


class CommitTests(RepoCase):
    def test_commit_state_allowlist(self):
        self.write(".claude/herald/topics.json", "{}")
        self.write("src/content/blog/x.md", "x")
        with self.assertRaises(HeraldError):
            commits.commit_state(self.root, self.cfg, "plan", "m", "plan", [".claude/herald/topics.json", "src/content/blog/x.md"])
        sha = commits.commit_state(self.root, self.cfg, "plan", "m", "plan", [".claude/herald/topics.json"])
        self.assertTrue(sha)
        self.assertEqual(commits.trailer(self.root, sha), "plan")

    def test_classify_ahead_record_vs_human_commit(self):
        self.write(".claude/herald/topics.json", "{}")
        commits.commit_state(self.root, self.cfg, "plan", "m", "plan", [".claude/herald/topics.json"])
        self.write("README.md", "human")
        self.commit("human change")
        rows = commits.classify_ahead(self.root, self.cfg, "main")
        self.assertEqual([r["ok"] for r in rows], [True, False])

    def test_sync_merge_and_evil_merge(self):
        # origin moves
        other = os.path.join(self.tmp, "other")
        sh(self.tmp, "git", "clone", "-q", self.origin, other)
        sh(other, "git", "config", "user.email", "o@x"); sh(other, "git", "config", "user.name", "o")
        open(os.path.join(other, "remote.txt"), "w").write("r")
        sh(other, "git", "add", "-A"); sh(other, "git", "commit", "-qm", "remote"); sh(other, "git", "push", "-q")
        self.write(".claude/herald/topics.json", "{}")
        commits.commit_state(self.root, self.cfg, "plan", "m", "plan", [".claude/herald/topics.json"])
        self.assertEqual(commits.sync_base(self.root, self.cfg), "merged")
        rows = commits.classify_ahead(self.root, self.cfg, "main")
        self.assertTrue(all(r["ok"] for r in rows), rows)
        # evil merge: amend the sync merge to also touch an article
        self.write("src/content/blog/old-post.md", "evil")
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "--amend", "--no-edit")
        rows = commits.classify_ahead(self.root, self.cfg, "main")
        self.assertFalse(rows[-1]["ok"])


class ScopeTests(Flow):
    def test_scope_rejects_foreign_files_and_ignores_unpushed_base(self):
        # an unpushed Herald record commit on base must not leak into the PR diff
        self.write(".claude/herald/topics.json", json.dumps({"version": 1, "topics": []}))
        tid, slug = self.run_flow()
        self.commit("article")
        self.assertTrue(commits.scope_check(self.root, self.cfg, tid, slug)["ok"])
        self.write("src/content/blog/old-post.md", "sneaky")
        self.commit("sneaky")
        res = commits.scope_check(self.root, self.cfg, tid, slug)
        self.assertFalse(res["ok"])
        self.assertIn("src/content/blog/old-post.md", res["out_of_scope"])


class IntegrityTests(Flow):
    def publish_herald(self, tid, slug, number=1):
        """Simulate: verified article merged to main + ledger + published.json."""
        self.run_flow(tid, slug)
        self.hrd("ledger", "record", "--topic", tid)
        self.commit("article")
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        sh(self.root, "git", "checkout", "-q", "main")
        sh(self.root, "git", "merge", "-q", "--no-ff", "-m", "merge", store.branch_name(tid, slug))
        sh(self.root, "git", "push", "-q", "origin", "main")
        prs = self.gh_prs() + [{"number": number, "state": "MERGED", "headRefName": store.branch_name(tid, slug),
                                "headRefOid": head, "mergedAt": "2026-10-10T00:00:0%dZ" % number, "labels": ["herald"]}]
        self.set_prs(prs)
        return head

    def test_merged_unrecorded_detected_and_clean(self):
        self.publish_herald("t0001", "new-post")
        rep = integrity.check(self.root, self.cfg)
        self.assertTrue(rep["ok"], rep)
        self.assertTrue(rep["articles"][0]["merged_unrecorded"])

    def test_base_edit_breaks_integrity_and_external_ignored(self):
        self.publish_herald("t0001", "new-post")
        self.write("src/content/blog/old-post.md", "external edits are not Herald's")
        self.commit("ext")
        self.assertTrue(integrity.check(self.root, self.cfg)["ok"])
        self.write("src/content/blog/new-post.md", "human edit on base")
        self.commit("edit")
        rep = integrity.check(self.root, self.cfg)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["articles"][0]["status"], "mismatch")

    def test_no_ledger_is_not_trusted(self):
        self.publish_herald("t0001", "new-post")
        os.remove(os.path.join(self.root, ".claude/herald/ledger/verified.jsonl"))
        self.assertEqual(integrity.check(self.root, self.cfg)["articles"][0]["status"], "no-ledger")

    def test_predeploy_blocks_untracked_build_input_and_residue(self):
        self.publish_herald("t0001", "new-post")
        self.write("src/content/blog/stray.md", "unverified")
        self.assertFalse(integrity.predeploy(self.root, self.cfg)["ok"])
        os.remove(os.path.join(self.root, "src/content/blog/stray.md"))
        self.write("public/blog-images/gone/01.webp", b"x", binary=True)
        rep = integrity.predeploy(self.root, self.cfg)
        self.assertEqual(rep["ignored_residue"], ["public/blog-images/gone"])

    def test_human_merged_held_pr_is_still_checked(self):
        self.publish_herald("t0001", "new-post")
        data = store.load_topics(self.root)
        store.set_topic_state(store.get_topic(data, "t0001"), "held", "verify-after-human-edit")
        store.save_topics(self.root, data)
        self.write("src/content/blog/new-post.md", "unverified human change")
        self.commit("x")
        members = ghstate.herald_set(self.root, self.cfg)
        self.assertIn("new-post", members)
        self.assertFalse(integrity.check(self.root, self.cfg)["ok"])

    def test_withdraw_requires_absent_files_then_reappearance_flagged(self):
        self.publish_herald("t0001", "new-post")
        self.hrd("record-published", "--topic", "t0001", "--slug", "new-post", "--pr", "1")
        _, p = self.hrd("withdraw", "new-post", check=False)
        self.assertNotEqual(p.returncode, 0)
        sh(self.root, "git", "rm", "-q", "-r", "src/content/blog/new-post.md", "public/blog-images/new-post")
        self.commit("remove")
        self.hrd("withdraw", "new-post")
        self.assertTrue(integrity.check(self.root, self.cfg)["ok"])
        self.article("new-post")  # someone restores it without Herald
        self.commit("restore")
        rep = integrity.check(self.root, self.cfg)
        self.assertEqual(rep["flags"], [{"slug": "new-post", "why": "withdrawn"}])

    def test_move_alias_and_slug_reuse(self):
        self.publish_herald("t0001", "new-post")
        self.hrd("record-published", "--topic", "t0001", "--slug", "new-post", "--pr", "1")
        sh(self.root, "git", "mv", "src/content/blog/new-post.md", "src/content/blog/renamed.md")
        sh(self.root, "git", "mv", "public/blog-images/new-post", "public/blog-images/renamed")
        self.commit("rename")
        self.hrd("move", "--topic", "t0001", "--new-slug", "renamed")
        members = ghstate.herald_set(self.root, self.cfg)
        self.assertIn("renamed", members)
        self.assertNotIn("new-post", members)
        # a different topic reuses the old slug later
        self.set_prs(self.gh_prs() + [{"number": 2, "state": "MERGED", "headRefName": store.branch_name("t0002", "new-post"),
                                       "mergedAt": "2026-10-11T00:00:00Z", "labels": ["herald"]}])
        members = ghstate.herald_set(self.root, self.cfg)
        self.assertEqual(members["new-post"]["ref_topic"], "t0002")
        self.assertEqual(members["renamed"]["ref_topic"], "t0001")


class RevertTests(IntegrityTests):
    def test_revert_detection_keyed_by_pr(self):
        self.publish_herald("t0001", "new-post")
        self.set_prs(self.gh_prs() + [{"number": 9, "state": "MERGED", "headRefName": "herald-revert/t0001",
                                       "mergedAt": "2026-10-12T00:00:00Z", "labels": ["herald-revert", "herald-revert:remove"]}])
        out, _ = self.hrd("reverts", "apply")
        self.assertEqual(out["pending"], [{"topic_id": "t0001", "pr": 9}])
        self.hrd("requeue", "--topic", "t0001")
        out, _ = self.hrd("reverts", "list")
        self.assertEqual(out["pending"], [])
        self.assertEqual(store.get_topic(store.load_topics(self.root), "t0001")["state"], "queued")


class SelectionTests(IntegrityTests):
    def test_merged_or_branched_topics_are_not_selectable(self):
        self.publish_herald("t0001", "new-post")
        out, _ = self.hrd("select")
        self.assertNotIn("t0001", out)


class RegressionRound1(IntegrityTests):
    def test_stale_verdict_files_cannot_vouch_for_new_body(self):
        tid, slug = self.run_flow()
        self.hrd("loopback", "--topic", tid)
        self.write("src/content/blog/%s.md" % slug, "---\ntitle: a\ndescription: d\nslug: %s\ndate: x\n---\nUNVERIFIED NEW CLAIM: 99%% of users\n" % slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", check=False)
        self.assertIn("does not evaluate the current article", p.stderr)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertNotEqual(p.returncode, 0)

    def test_trust_only_without_ledger_and_attended(self):
        tid, slug = self.run_flow()
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "trust", env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("need a human", p.stderr)
        self.hrd("ledger", "record", "--topic", tid, "--kind", "trust")
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "trust", check=False)
        self.assertIn("already has a ledger line", p.stderr)

    def test_trust_refused_for_unverified_body(self):
        tid, slug = self.run_flow()
        self.write("src/content/blog/%s.md" % slug, "human change")
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "trust", check=False)
        self.assertIn("differs from the committed verified_hash", p.stderr)

    def test_inherited_lock_release_is_noop(self):
        tok = lock.acquire(self.root, "batch")
        _, p = self.hrd("lock", "release", "--token", tok, env={"HRD_LOCK_TOKEN": tok})
        self.assertIsNotNone(lock.status(self.root))
        self.assertTrue(lock.release(self.root, tok, owner=True))

    def test_move_then_reverify_then_integrity_ok(self):
        self.publish_herald("t0001", "new-post")
        self.hrd("record-published", "--topic", "t0001", "--slug", "new-post", "--pr", "1")
        sh(self.root, "git", "mv", "src/content/blog/new-post.md", "src/content/blog/renamed.md")
        sh(self.root, "git", "mv", "public/blog-images/new-post", "public/blog-images/renamed")
        self.write("src/content/blog/renamed.md", (open(os.path.join(self.root, "src/content/blog/renamed.md")).read()
                                                   .replace("/blog-images/new-post/", "/blog-images/renamed/")
                                                   .replace("slug: new-post", "slug: renamed")))
        self.commit("rename")
        self.hrd("move", "--topic", "t0001", "--new-slug", "renamed")
        rep = integrity.check(self.root, self.cfg)
        self.assertEqual(rep["articles"][0]["status"], "mismatch")
        write_machine(self, "t0001", "verify.json", VER_PASS, "renamed")
        self.hrd("stage", "pass", "--topic", "t0001", "--stage", "verify", "--amend")
        self.hrd("ledger", "record", "--topic", "t0001", "--kind", "base-commit")
        self.assertTrue(integrity.check(self.root, self.cfg)["ok"])

    def test_withdraw_refused_after_rename(self):
        self.publish_herald("t0001", "new-post")
        self.hrd("record-published", "--topic", "t0001", "--slug", "new-post", "--pr", "1")
        sh(self.root, "git", "mv", "src/content/blog/new-post.md", "src/content/blog/other.md")
        sh(self.root, "git", "mv", "public/blog-images/new-post", "public/blog-images/other")
        self.commit("rename")
        _, p = self.hrd("withdraw", "new-post", check=False)
        self.assertIn("renamed", p.stderr)

    def test_unattended_base_writers_refused(self):
        self.write(".claude/herald/topics.json", "{}")
        _, p = self.hrd("commit", "--cmd", "plan", "--kind", "plan", "-m", "m", ".claude/herald/topics.json",
                        env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("unattended", p.stderr)


if __name__ == "__main__":
    unittest.main()
