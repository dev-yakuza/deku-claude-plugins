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
        self.write("src/content/blog/%s.md" % slug, "---\ntitle: a\ndescription: d\nslug: %s\ndate: x\n---\nhuman edited body\n" % slug)
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
        self.commit("work")
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "trust", env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("need a human", p.stderr)
        self.hrd("ledger", "record", "--topic", tid, "--kind", "trust")
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "trust", check=False)
        self.assertIn("already has a ledger line", p.stderr)

    def test_trust_refused_for_unverified_body(self):
        tid, slug = self.run_flow()
        self.commit("work")
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

    def test_trust_refused_for_uncommitted_state(self):
        tid, slug = self.run_flow()
        self.commit("work")
        st = json.load(open(store.state_path(self.root, tid))); st["note"] = "local edit"
        with open(store.state_path(self.root, tid), "w") as f:
            json.dump(st, f)
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "trust", check=False)
        self.assertIn("differs from HEAD", p.stderr)

    def test_result_status_validated(self):
        _, p = self.hrd("result", "--topic", "t0001", "--status", "held:cannibalisation", check=False)
        self.assertIn("unknown result status", p.stderr)

    def test_nested_lock_release_left_to_owner(self):
        out, _ = self.hrd("lock", "acquire", "--cmd", "refresh")
        tok = out["token"]
        self.hrd("lock", "acquire", "--cmd", "write", "--token", tok)
        out, _ = self.hrd("lock", "release", "--cmd", "write", "--token", tok)
        self.assertFalse(out["released"])
        out, _ = self.hrd("lock", "release", "--cmd", "refresh", "--token", tok)
        self.assertTrue(out["released"])

    def test_integrity_report_mode_exits_zero(self):
        self.publish_herald("t0001", "new-post")
        self.write("src/content/blog/new-post.md", "changed on base")
        self.commit("x")
        out, p = self.hrd("integrity", "--report")
        self.assertFalse(out["ok"])
        _, p = self.hrd("integrity", check=False)
        self.assertEqual(p.returncode, 1)

    def test_commit_state_refuses_bytecode(self):
        self.write(".claude/herald/scripts/hrdlib/__pycache__/x.cpython-314.pyc", b"x", binary=True)
        with self.assertRaises(HeraldError):
            commits.commit_state(self.root, self.cfg, "harness", "m", "harness",
                                 [".claude/herald/scripts/hrdlib/__pycache__/x.cpython-314.pyc"])

    def test_auto_merged_topic_stays_unreviewed(self):
        self.publish_herald("t0001", "new-post")
        data = store.load_topics(self.root)
        store.get_topic(data, "t0001")["auto_merged_pr"] = 1
        store.save_topics(self.root, data)
        out, _ = self.hrd("record-published", "--topic", "t0001", "--slug", "new-post", "--pr", "1")
        self.assertFalse(out["human_reviewed"])

    def test_requeue_clears_auto_merge_mark(self):
        self.publish_herald("t0001", "new-post")
        data = store.load_topics(self.root)
        t = store.get_topic(data, "t0001")
        t["auto_merged_pr"] = 1
        store.set_topic_state(t, "held", "reverted")
        store.save_topics(self.root, data)
        self.hrd("requeue", "--topic", "t0001")
        self.assertNotIn("auto_merged_pr", store.get_topic(store.load_topics(self.root), "t0001"))
        data = store.load_topics(self.root)
        store.get_topic(data, "t0001")["auto_merged_pr"] = 1
        store.save_topics(self.root, data)
        out, _ = self.hrd("record-published", "--topic", "t0001", "--slug", "new-post", "--pr", "5")
        self.assertTrue(out["human_reviewed"])  # a different, human-approved PR

    def test_unattended_base_writers_refused(self):
        self.write(".claude/herald/topics.json", "{}")
        _, p = self.hrd("commit", "--cmd", "plan", "--kind", "plan", "-m", "m", ".claude/herald/topics.json",
                        env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("unattended", p.stderr)


class EvolveReadinessTests(RepoCase):
    def sig(self, kind, tid, data=None, at="2026-10-10T00:00:00+00:00", reviewed=None):
        rec = {"at": at, "kind": kind, "topic_id": tid, "data": data or {}}
        if reviewed is not None:
            rec["human_reviewed"] = reviewed
        self.raw(json.dumps(rec))

    def raw(self, line):
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl"), "a") as f:
            f.write(line + "\n")

    def ready(self):
        return store.evolve_readiness(self.root, self.cfg)

    def test_tiers_dedup_and_topic_spread(self):
        self.assertEqual(self.ready()["tier"], "none")
        self.sig("revise-weakness", "t0001", {"w": "intro"})
        self.sig("revise-weakness", "t0001", {"w": "intro"}, at="2026-10-10T01:00:00+00:00")  # same event
        self.sig("revise-weakness", "t0001", {"w": "cta"})
        self.sig("revise-weakness", "t0001", {"w": "faq"})
        r = self.ready()
        self.assertEqual((r["tier"], r["signals"], r["topics"]), ("watching", 3, 1))  # one topic only
        self.sig("revise-weakness", "t0002", {"w": "intro"})
        r = self.ready()
        self.assertEqual((r["tier"], r["ready_kinds"]), ("sufficient", ["revise-weakness"]))

    def test_unreviewed_zero_line_and_clean_review_not_counted(self):
        self.sig("human-edit", "t0001", {"lines_changed": 4}, reviewed=False)
        self.sig("human-edit", "t0002", {"lines_changed": 0}, reviewed=True)
        self.sig("human-edit", "t0003", {"lines_changed": 2})  # no reviewed flag
        for t in ("t0001", "t0002", "t0003"):
            self.sig("review-finding", t, {"pr": 1, "blocker": 0, "major": 0, "minor": 0, "findings": []})
        self.assertEqual(self.ready()["tier"], "none")
        for t in ("t0001", "t0002", "t0003"):
            self.sig("human-edit", t, {"lines_changed": 3}, reviewed=True)
        self.assertEqual(self.ready()["tier"], "sufficient")

    def test_session_edit_request_paired_by_id(self):
        req, _ = self.hrd("signal", "--kind", "session-edit-request", "--topic", "t0001",
                          "--data", json.dumps({"request": "shorter intro, please"}))
        self.hrd("signal", "--kind", "session-edit-request", "--topic", "t0001",
                 "--data", json.dumps({"request_id": req["id"], "diff_summary": "x", "lines_changed": 4}))
        self.assertEqual(self.ready()["signals"], 1)
        listed = store.evolve_readiness(self.root, self.cfg, listing=True)["list"]
        self.assertEqual((listed[0]["data"]["request"], listed[0]["data"]["diff_summary"]),
                         ("shorter intro, please", "x"))  # the diff reaches evolve with its request
        self.hrd("signal", "--kind", "session-edit-request", "--topic", "t0001",
                 "--data", json.dumps({"request": "shorter intro, please"}))  # same words, new request (same second)
        self.assertEqual(self.ready()["signals"], 2)
        self.hrd("evolve-mark", "--consume", req["id"])
        self.assertEqual(self.ready()["signals"], 1)  # the pair is consumed together

    def test_baseline_listed_not_counted_and_recurrence_after_consume(self):
        self.sig("human-edit", "t0001", {"lines_changed": 0}, reviewed=True)
        self.sig("review-finding", "t0001", {"pr": 1, "blocker": 0, "major": 0, "minor": 0, "findings": []})
        r = store.evolve_readiness(self.root, self.cfg, listing=True)
        self.assertEqual((r["signals"], len(r["baseline"])), (0, 2))
        self.sig("hold", "t0002", {"reason": "budget"})
        sid = store.evolve_readiness(self.root, self.cfg, listing=True)["list"][0]["id"]
        self.hrd("evolve-mark", "--consume", sid)
        self.assertEqual(self.ready()["signals"], 0)
        self.sig("hold", "t0002", {"reason": "budget"}, at="2026-12-01T00:00:00+00:00")  # same reason, later
        self.assertEqual(self.ready()["signals"], 1)

    def test_invalid_utf8_line_is_skipped(self):
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl"), "ab") as f:
            f.write(b"\xff\xfe\n")
            f.write(b'{"at": "x", "kind": "hold", "topic_id": "t000\xff", "data": {}}\n')  # bad byte in a string
        self.sig("hold", "t0001", {"reason": "budget"})
        out, _ = self.hrd("evolve-readiness")
        self.assertEqual((out["signals"], out["topics"]), (1, 1))
        os.makedirs(os.path.join(self.root, ".claude/herald/ledger"), exist_ok=True)
        with open(os.path.join(self.root, ".claude/herald/ledger/verified.jsonl"), "wb") as f:
            f.write(b'{"topic_id": "t0001", "verified_hash": "ab\xff"}\n')
        with self.assertRaises(HeraldError):  # the ledger fails closed on bad bytes
            store.ledger_lines(self.root)

    def test_unreadable_counts_legacy_diffs_baseline_cites_and_stale_snapshot(self):
        self.sig("human-edit", "t0001", {"lines_changed": -40}, reviewed=True)
        self.raw('{"at": "x", "kind": "human-edit", "human_reviewed": true, "topic_id": "t0002", "data": {"lines_changed": %s}}'
                 % ("9" * 400))
        self.sig("review-finding", "t0003", {"pr": 3})  # no counts at all
        self.sig("session-edit-request", "t0004", {"request": "r"})
        self.sig("session-edit-request", "t0004", {"request": "r", "diff_summary": "d", "lines_changed": 3})  # 0.2.0 pair
        r = store.evolve_readiness(self.root, self.cfg, listing=True)
        self.assertEqual((r["kinds"]["human-edit"]["count"], r["kinds"]["review-finding"]["count"],
                          r["kinds"]["session-edit-request"]["count"], r["baseline"]), (2, 1, 1, []))
        self.sig("human-edit", "t0005", {"lines_changed": 0}, reviewed=True)
        base = store.evolve_readiness(self.root, self.cfg, listing=True)["baseline"][0]["id"]
        out, _ = self.hrd("evolve-mark", "--consume", base)
        self.assertEqual((out["baseline_cited"], out["unknown"]), ([base], []))
        self.hrd("evolve-readiness", "--snapshot", "--token", "run-a")  # run A aborts after Phase 1
        self.sig("verify-gap", "t0001", {"c": 1})
        self.hrd("evolve-mark", "--scan", "--token", "run-b")  # run B completes without a snapshot of its own
        self.assertEqual(self.ready()["kinds"]["verify-gap"]["new"], 0)  # B's current list, not A's stale one
        self.write(".claude/herald/memory/evolve-scan.json", "{broken")
        self.hrd("evolve-mark", "--scan", "--token", "run-c")  # unreadable snapshot = none
        _, p = self.hrd("evolve-readiness", "--snapshot", check=False)
        self.assertIn("--token", p.stderr)

    def test_orphan_diffs_combined_records_surrogates_and_stored_shape(self):
        self.sig("session-edit-request", "t0001", {"request_id": "nope", "diff_summary": "d"})  # orphan
        self.sig("session-edit-request", "t0001", {"request_id": None, "diff_summary": "d"})
        self.sig("session-edit-request", "t0002", {"request": "x", "diff_summary": "d", "lines_changed": 3})  # one record
        self.raw('{"at": "x", "kind": "hold", "topic_id": "t0003", "data": {"note": "\\ud800"}}')
        r = store.evolve_readiness(self.root, self.cfg, listing=True)
        self.assertEqual((r["kinds"]["session-edit-request"]["count"], r["kinds"]["hold"]["count"]), (1, 1))
        out, _ = self.hrd("signal", "--kind", "hold", "--topic", "t0004", "--data", "{}")
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl")) as f:
            last = json.loads(f.read().splitlines()[-1])
        self.assertNotIn("id", last)
        self.assertEqual(store.signal_id(last), out["id"])
        self.hrd("evolve-mark", "--consume", out["id"])
        out2, _ = self.hrd("evolve-mark", "--consume", out["id"])
        self.assertEqual((out2["already_consumed"], out2["unknown"]), ([out["id"]], []))

    def test_counts_low_line_edits_numeric_strings_and_seen_recurrence(self):
        for t in ("t0001", "t0002", "t0003"):
            self.sig("human-edit", t, {"lines_changed": 1}, reviewed=True)  # typo fixes: exemplar evidence
            self.sig("review-finding", t, {"blocker": "0", "major": "2", "findings": []})  # hand-written counts
        r = store.evolve_readiness(self.root, self.cfg, listing=True)
        self.assertEqual((sorted(r["kinds"]), len(r["baseline"])), (["review-finding"], 3))
        self.hrd("evolve-readiness", "--snapshot", "--token", "run-1")
        self.sig("verify-gap", "t0001", {"c": 1})  # arrives while the run waits
        self.hrd("evolve-mark", "--scan", "--token", "run-1")
        r = self.ready()
        self.assertEqual((r["tier"], r["kinds"]["verify-gap"]["new"]), ("watching", 1))  # not marked seen
        self.sig("review-finding", "t0001", {"blocker": "0", "major": "2", "findings": []}, at="2026-12-01T00:00:00+00:00")
        self.assertEqual(self.ready()["tier"], "watching")  # identical recurrence of a seen group: not new
        sid = store.evolve_readiness(self.root, self.cfg, listing=True)["list"][0]["id"]
        out, _ = self.hrd("evolve-mark", "--scan", "--consume", sid)
        self.assertEqual(out["unknown"], [])
        st = store.load_evolve_state(self.root)
        self.assertFalse(set(st["seen"]) & set(st["consumed"]))

    def test_malformed_records_are_skipped_and_status_survives(self):
        self.raw("[1]")
        self.raw("not json")
        self.raw(json.dumps({"at": "x", "kind": "human-edit", "human_reviewed": True, "data": "x"}))
        self.raw(json.dumps({"at": "x", "kind": "hold", "topic_id": ["t1"], "data": {}}))
        self.assertEqual(self.ready()["tier"], "none")
        self.write(".claude/herald/memory/evolve-state.json", "{broken")
        out, _ = self.hrd("status")
        self.assertIn("error", out["evolve"])

    def test_consume_only_decided_evidence_and_scan_suppresses_renudge(self):
        for t in ("t0001", "t0002", "t0003"):
            self.sig("verify-gap", t, {"c": t})
            self.sig("revise-weakness", t, {"w": t})
        out, _ = self.hrd("evolve-readiness", "--list")
        self.assertEqual(out["tier"], "sufficient")
        gap_ids = [r["id"] for r in out["list"] if r["kind"] == "verify-gap"]
        self.hrd("evolve-mark", "--scan")
        r = self.ready()
        self.assertEqual(r["tier"], "watching")  # scanned, nothing new: no nudge
        self.hrd("evolve-mark", "--consume", *gap_ids)
        r = self.ready()
        self.assertEqual((r["signals"], sorted(r["kinds"])), (3, ["revise-weakness"]))  # watching evidence kept
        self.sig("revise-weakness", "t0004", {"w": "new"}, at="2000-01-01T00:00:00+00:00")  # old clock: still new
        self.assertEqual(self.ready()["new_ready_kinds"], ["revise-weakness"])
        out, _ = self.hrd("evolve-mark", "--consume", gap_ids[0], "bogus")
        self.assertEqual((out["already_consumed"], out["unknown"]), ([gap_ids[0]], ["bogus"]))
        _, p = self.hrd("evolve-mark", "--scan", env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("attended only", p.stderr)

    def test_signals_are_per_machine_not_closed_by_git_history(self):
        for t in ("t0001", "t0002", "t0003"):
            self.sig("verify-gap", t, {"c": t})
        self.write(".claude/herald/evolution-log.md", "| 1 | 2026-10-11 | x | y | applied | | |\n")
        self.hrd("commit", "--cmd", "harness", "--kind", "evolve", "-m", "chore(herald): evolve #1 — x",
                 ".claude/herald/evolution-log.md")  # another machine's evolve, synced here
        self.assertEqual(self.ready()["tier"], "sufficient")


if __name__ == "__main__":
    unittest.main()
