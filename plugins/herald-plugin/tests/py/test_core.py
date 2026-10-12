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
            fr = obj.setdefault("final_round", {})
            fr["body_hash"] = h
            if "audit_round" not in fr:  # the main session counts each auditor round first
                fr["audit_round"] = case.hrd("audit-round", "--topic", tid)[0]["round"]
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
        self.hrd("loopback", "--topic", tid, "--cause", "verify")
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
            out, _ = self.hrd("loopback", "--topic", tid, "--cause", "verify")
        self.assertFalse(out["exhausted"])
        out, _ = self.hrd("loopback", "--topic", tid, "--human")
        self.assertEqual(out["loopbacks"], 3)
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "verify")
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
        sh(self.root, "git", "push", "-q", "origin", sh(self.root, "git", "branch", "--show-current").strip())
        rec, _ = self.hrd("ledger", "record", "--topic", tid, "--kind", "push")
        self.assertEqual(rec["kind"], "push")
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        self.assertEqual(rec["sha"], head)

    def test_push_record_names_head_not_a_typed_sha(self):
        tid, slug = self.run_flow()
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        br = sh(self.root, "git", "branch", "--show-current").strip()
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "push", check=False)
        self.assertIn("first", p.stderr)  # never pushed: no origin/<branch>
        sh(self.root, "git", "push", "-q", "origin", br)
        rec, _ = self.hrd("ledger", "record", "--topic", tid, "--kind", "push", "--sha", head[:7])
        self.assertEqual(rec["sha"], head)  # an abbreviation of HEAD is expanded
        for bad in ("abc", head[:7] + "0" * 33, "HEAD~1"):
            _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "push", "--sha", bad, check=False)
            self.assertIn("is not HEAD", p.stderr)
        lines = [r for r in store.ledger_lines(self.root) if r["kind"] == "push"]
        self.assertEqual([r["sha"] for r in lines], [head])
        sh(self.root, "git", "commit", "-q", "--allow-empty", "-m", "unpushed")
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "push", check=False)
        self.assertIn("first", p.stderr)
        # ship §5: a branch reset onto a PR ref tracks origin/pr-<n>; `git push origin <branch>`
        # updates origin/<branch>, which is what the record compares
        sh(self.root, "git", "push", "-q", "origin", "HEAD:refs/heads/pr-7")
        sh(self.root, "git", "fetch", "-q", "origin")
        sh(self.root, "git", "switch", "-q", "-C", br, "refs/remotes/origin/pr-7")
        sh(self.root, "git", "commit", "-q", "--allow-empty", "-m", "re-verify artifacts")
        sh(self.root, "git", "push", "-q", "origin", br)
        rec, _ = self.hrd("ledger", "record", "--topic", tid, "--kind", "push")
        self.assertEqual(rec["sha"], sh(self.root, "git", "rev-parse", "HEAD").strip())
        sh(self.root, "git", "switch", "-q", "--detach")
        _, p = self.hrd("ledger", "record", "--topic", tid, "--kind", "push", check=False)
        self.assertIn("detached", p.stderr)


class AutoMergeStampTests(Flow):
    def test_session_auto_stamp_keeps_a_later_record_unreviewed(self):
        tid, slug = self.run_flow()
        sh(self.root, "git", "stash", "-u", "-q")
        sh(self.root, "git", "switch", "-q", "main")
        out, _ = self.hrd("auto-merged", "--topic", tid, "--pr", "12")
        self.assertEqual(out["auto_merged_pr"], 12)
        _, p = self.hrd("auto-merged", "--topic", tid, "--pr", "12", env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertNotEqual(p.returncode, 0)  # the batch runner stamps its own
        _, p = self.hrd("auto-merged", "--topic", tid, "--pr", "13", check=False)
        self.assertIn("already carries", p.stderr)
        for bad in (("--pr", "0"), ("--pr", "12", "--clear"), ()):
            _, p = self.hrd("auto-merged", "--topic", tid, *bad, check=False)
            self.assertNotEqual(p.returncode, 0, bad)
        self.assertEqual(self.hrd("throttle")[0]["used"], 1)  # an unrecorded auto merge counts today
        rec, _ = self.hrd("record-published", "--topic", tid, "--slug", slug, "--pr", "12")
        self.assertFalse(rec["human_reviewed"])  # a plain later ship cannot turn it into a reviewed article
        self.assertEqual(self.hrd("throttle")[0]["used"], 1)  # counted once, recorded or not
        _, p = self.hrd("state", "--topic", tid, "--state", "queued", check=False)
        self.assertIn("already published", p.stderr)
        _, p = self.hrd("auto-merged", "--topic", tid, "--pr", "12", check=False)
        self.assertIn("already published", p.stderr)

    def test_clear_undoes_a_stamp_whose_merge_failed(self):
        tid, slug = self.run_flow()
        sh(self.root, "git", "stash", "-u", "-q")
        sh(self.root, "git", "switch", "-q", "main")
        self.hrd("auto-merged", "--topic", tid, "--pr", "5")
        out, _ = self.hrd("auto-merged", "--topic", tid, "--clear")
        self.assertIsNone(out["auto_merged_pr"])
        self.assertEqual(self.hrd("throttle")[0]["used"], 0)


class AuditRoundTests(Flow):
    def crit(self, tid, slug, log=None, **fr):
        c = json.loads(json.dumps(CRIT_PASS))
        c["final_round"].update(fr)
        if log is not None:
            c["audit_log"] = log
        write_machine(self, tid, "critique.json", c, slug)
        return self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", check=False)[1]

    def edit(self, slug, n):
        self.write("src/content/blog/%s.md" % slug,
                   "---\ntitle: a\ndescription: d\nslug: %s\ndate: x\n---\nrevision %d\n" % (slug, n))

    def at_round(self, tid, n):
        st = store.load_state(self.root, tid)
        st["audit_rounds"], st["audit_round_body"] = n, None
        store.save_state(self.root, tid, st)

    def test_rounds_full_then_recheck_then_skip_and_repeat_counts_once(self):
        tid, slug = self.run_flow()  # the flow's critique used round 1
        again, _ = self.hrd("audit-round", "--topic", tid)
        self.assertEqual((again["round"], again["mode"], again["repeat"]), (1, "full", True))  # same article
        modes = []
        for i in range(3):
            self.edit(slug, i)
            modes.append(self.hrd("audit-round", "--topic", tid)[0])
        self.assertEqual([(m["round"], m["mode"], m["last"]) for m in modes],
                         [(2, "recheck", False), (3, "recheck", True), (4, "skip", False)])

    def test_critique_pass_needs_the_counted_round(self):
        tid, slug = self.run_flow()
        p = self.crit(tid, slug, audit_round=1)
        self.assertEqual(p.returncode, 0, p.stderr)
        p = self.crit(tid, slug, audit_round=5)
        self.assertIn("audit_round is 5", p.stderr)
        st = store.load_state(self.root, tid)
        st.pop("audit_rounds")
        store.save_state(self.root, tid, st)
        p = self.crit(tid, slug, audit_round=1)
        self.assertIn("HRD audit-round", p.stderr)

    def test_deferral_rules(self):
        tid, slug = self.run_flow()
        new = lambda r, tag="new", sev="MAJOR", out="deferred", i="B1": {"round": r, "id": i, "severity": sev,  # noqa: E731
                                                                         "tag": tag, "outcome": out}
        p = self.crit(tid, slug, [new(1)], audit_round=1, audit={"major": 1}, deferred={"major": 1})
        self.assertNotEqual(p.returncode, 0)  # round 1: fixed or dismissed, never deferred
        self.at_round(tid, 2)
        p = self.crit(tid, slug, [], audit_round=2, audit={"major": 1}, deferred={"major": 1})
        self.assertIn("deferrable", p.stderr)  # not logged
        p = self.crit(tid, slug, [new(2, tag="regression")], audit_round=2, audit={"major": 1}, deferred={"major": 1})
        self.assertIn("deferrable", p.stderr)  # a regression blocks before the last round
        p = self.crit(tid, slug, [new(2), new(2, i="B2")], audit_round=2, audit={"major": 2}, deferred={"major": 2})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.at_round(tid, 3)
        p = self.crit(tid, slug, [new(3, tag="unfixed")], audit_round=3, audit={"major": 1}, deferred={"major": 1})
        self.assertEqual(p.returncode, 0, p.stderr)  # last round: any MAJOR is deferred
        p = self.crit(tid, slug, [new(3, sev="BLOCKER", out="open")], audit_round=3, audit={"blocker": 1},
                      dismissed={"blocker": 1})
        self.assertIn("needs a human", p.stderr)  # open + a dismissal count without a human decision
        p = self.crit(tid, slug, [], audit_round=3, audit={"blocker": 1}, dismissed={"blocker": 1})
        self.assertIn("must be in audit_log", p.stderr)  # an unlogged last-round BLOCKER
        p = self.crit(tid, slug, [{"id": "R3-1", "severity": "BLOCKER", "outcome": "dismissed"}], audit_round=3,
                      audit={"blocker": 1}, dismissed={"blocker": 1})
        self.assertIn("no integer round", p.stderr)
        self.at_round(tid, 2)
        p = self.crit(tid, slug, [new(1, out="open")], audit_round=2)
        self.assertIn("is open", p.stderr)  # a looped-back finding is logged as fixed
        p = self.crit(tid, slug, [new(1, sev="BLOCKER", out="open")], audit_round=2)
        self.assertIn("is open", p.stderr)  # a held round-1 BLOCKER is resolved with the human first
        self.at_round(tid, 4)
        p = self.crit(tid, slug, [new(1, sev="BLOCKER", out="open")], audit_round=4, audit={})
        self.assertIn("still open", p.stderr)
        crit = {"final_round": {"verdict": "PASS", "audit": {}}, "audit_log": [new(3, out="open")]}
        self.assertEqual(store.auto_exclusion(crit), ["audit-log:open"])

    def test_last_round_blocker_needs_a_human_and_skip_is_never_auto_published(self):
        tid, slug = self.run_flow()
        self.at_round(tid, 4)
        blocker = {"round": 3, "id": "R3-1", "severity": "BLOCKER", "outcome": "open"}
        p = self.crit(tid, slug, [blocker], audit_round=4, audit={})
        self.assertIn("needs a human", p.stderr)
        p = self.crit(tid, slug, [dict(blocker, outcome="fixed")], audit_round=4, audit={})
        self.assertIn("needs a human", p.stderr)  # a loopback alone cannot close it
        human = [{"kind": "human", "id": "R3-1", "note": "human: confirmed the fix"}]
        c = json.loads(json.dumps(CRIT_PASS))
        c["final_round"].update(audit_round=4, audit={"major": 1}, dismissed={"major": 1})
        c["audit_log"], c["decision_log"] = [blocker, dict(blocker, outcome="fixed")], human
        write_machine(self, tid, "critique.json", c, slug)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", check=False)
        self.assertIn("past the cap", p.stderr)
        c["final_round"].update(audit={}, dismissed={}, deferred={"major": 1})
        write_machine(self, tid, "critique.json", c, slug)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", check=False)
        self.assertIn("final_round.deferred must be empty", p.stderr)  # round 3's deferral is not carried over
        c["final_round"].pop("deferred")
        write_machine(self, tid, "critique.json", c, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")  # the later entry for R3-1 wins
        crit = store.load_machine(self.root, tid, "critique.json")
        self.assertEqual(store.auto_exclusion(crit), ["audit-skipped"])

    def test_last_round_blocker_dismissed_by_a_human_passes_the_same_round(self):
        tid, slug = self.run_flow()
        self.at_round(tid, 3)
        blocker = {"round": 3, "id": "R3-1", "severity": "BLOCKER", "outcome": "dismissed"}
        p = self.crit(tid, slug, [blocker], audit_round=3, audit={"blocker": 1}, dismissed={"blocker": 1})
        self.assertIn("needs a human", p.stderr)
        c = json.loads(json.dumps(CRIT_PASS))
        c["final_round"].update(audit_round=3, audit={"blocker": 1}, dismissed={"blocker": 1})
        c["audit_log"], c["decision_log"] = [blocker], [{"kind": "human", "id": "R3-1", "note": "human: policy"}]
        write_machine(self, tid, "critique.json", c, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")

    def test_last_round_refuses_audit_loopback_and_unattended_human_closure(self):
        tid, slug = self.run_flow()
        self.at_round(tid, 3)
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "audit", "--theme", "depth", check=False)
        self.assertIn("no audit loopback on the last audit round", p.stderr)
        out, _ = self.hrd("loopback", "--topic", tid, "--human")
        self.assertEqual(out["loopbacks"], 0)
        self.article(slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        c = json.loads(json.dumps(CRIT_PASS))
        c["final_round"].update(audit_round=3, audit={"blocker": 1}, dismissed={"blocker": 1})
        c["audit_log"] = [{"round": 3, "id": "R3-1", "severity": "BLOCKER", "outcome": "dismissed"}]
        c["decision_log"] = [{"kind": "human", "id": "R3-1", "note": "human: ok"}, {"kind": "dismissal", "note": "R3-1: ok"}]
        write_machine(self, tid, "critique.json", c, slug)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("unattended", p.stderr)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl")) as f:
            kinds = [json.loads(l)["kind"] for l in f if l.strip()]
        self.assertEqual(kinds.count("dismissal"), 1)  # a human dismissal is a signal

    def test_minor_findings_are_noted_and_never_block(self):
        tid, slug = self.run_flow()
        self.at_round(tid, 2)
        minor = {"round": 1, "id": "R1-2", "severity": "MINOR", "outcome": "open"}
        p = self.crit(tid, slug, [minor, dict(minor, id="R1-3", outcome="noted")], audit_round=2, audit={"minor": 2})
        self.assertEqual(p.returncode, 0, p.stderr)
        crit = store.load_machine(self.root, tid, "critique.json")
        self.assertEqual(store.auto_exclusion(crit), [])

    def test_junk_counts_and_deferral_exclusion(self):
        self.assertFalse(store.critique_passed({"final_round": {"verdict": "PASS", "audit_round": True,
                                                                "audit": {"major": 1}, "deferred": {"major": 1}}}))
        self.assertTrue(store.critique_passed({"final_round": {"verdict": "PASS", "audit": {"major": "x"},
                                                               "dismissed": {"major": None}}}))  # junk counts as 0
        crit = {"final_round": {"verdict": "PASS", "audit": {"major": "x"}}, "decision_log": [{"kind": "deferral"}, "junk"]}
        self.assertEqual(store.auto_exclusion(crit), ["decision:deferral"])
        # a deferred finding excludes auto publish even when the decision log forgot it
        crit = {"final_round": {"verdict": "PASS", "audit": {}}, "decision_log": [],
                "audit_log": [{"id": "R2-1", "severity": "MAJOR", "outcome": "deferred"}]}
        self.assertEqual(store.auto_exclusion(crit), ["audit-log:deferred"])

    def test_stage_pass_refuses_junk_counts(self):
        tid, slug = self.run_flow()
        for bad in ({"major": "1"}, {"major": True}, {"blocker": -1}, [0]):
            p = self.crit(tid, slug, audit_round=1, audit=bad)
            self.assertNotEqual(p.returncode, 0, bad)

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
        self.hrd("loopback", "--topic", tid, "--cause", "verify")
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
        self.assertEqual((r["tier"], r["ready_themes"]), ("sufficient", ["revise-weakness"]))

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
        self.assertEqual((r["themes"]["human-edit"]["count"], r["themes"]["review-finding"]["count"],
                          r["themes"]["session-edit-request"]["count"], r["baseline"]), (2, 1, 1, []))
        self.sig("human-edit", "t0005", {"lines_changed": 0}, reviewed=True)
        base = store.evolve_readiness(self.root, self.cfg, listing=True)["baseline"][0]["id"]
        out, _ = self.hrd("evolve-mark", "--consume", base)
        self.assertEqual((out["baseline_cited"], out["unknown"]), ([base], []))
        self.hrd("evolve-readiness", "--snapshot", "--token", "run-a")  # run A aborts after Phase 1
        self.sig("verify-gap", "t0001", {"c": 1})
        self.hrd("evolve-mark", "--scan", "--token", "run-b")  # run B completes without a snapshot of its own
        self.assertEqual(self.ready()["themes"]["verify-gap"]["new"], 0)  # B's current list, not A's stale one
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
        self.assertEqual((r["themes"]["session-edit-request"]["count"], r["themes"]["hold"]["count"]), (1, 1))
        _, p = self.hrd("signal", "--kind", "hold", "--topic", "t0004", "--data", "{}", check=False)
        self.assertIn("recorded by HRD itself", p.stderr)  # automatic kinds are not manual
        out, _ = self.hrd("signal", "--kind", "review-finding", "--topic", "t0004", "--data", '{"major": 1}')
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
        self.assertEqual((r["tier"], r["themes"]["verify-gap"]["new"]), ("watching", 1))  # not marked seen
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
        self.assertEqual(self.ready()["new_ready_themes"], ["revise-weakness"])
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


class AutoSignalTests(Flow):
    def kinds(self):
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl")) as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_loopbacks_gate_dismissal_hold_and_decline_record_themselves(self):
        tid, slug = self.run_flow()
        _, p = self.hrd("loopback", "--topic", tid, check=False)
        self.assertIn("--cause", p.stderr)
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "revise", check=False)
        self.assertIn("--theme", p.stderr)
        self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "intro", "--note", "weak hook")
        gap = {"counts": {"supported": 2, "unsupported": 1, "contradicted": 0, "unmapped": 0}}
        write_machine(self, tid, "verify.json", gap, slug)
        self.hrd("loopback", "--topic", tid, "--cause", "verify", "--note", "s1")
        self.hrd("loopback", "--topic", tid, "--human")
        recs = self.kinds()
        self.assertEqual([r["kind"] for r in recs], ["revise-weakness", "verify-gap", "escalation"])
        self.assertEqual(recs[0]["data"]["theme"], "intro")
        self.assertEqual(recs[1]["data"]["counts"], gap["counts"])
        # gate failure inside stage pass
        self.write("src/content/blog/%s.md" % slug, "no frontmatter at all")
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "draft", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.kinds()[-1]["kind"], "escalation")  # after a --human loopback: not the flow's
        # dismissals from the decision log, once per entry however often critique passes
        self.article(slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        crit = json.loads(json.dumps(CRIT_PASS))
        crit["decision_log"] = [{"kind": "dismissal", "note": "MAJOR-1 policy"}, {"kind": "routine", "note": "x"}]
        write_machine(self, tid, "critique.json", crit, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        self.assertEqual(sum(r["kind"] == "dismissal" for r in self.kinds()), 1)
        # holds and declines via HRD state (base)
        sh(self.root, "git", "stash", "-u", "-q")
        sh(self.root, "git", "switch", "-q", "main")
        self.hrd("state", "--topic", tid, "--state", "held", "--reason", "needs-human")
        self.hrd("state", "--topic", tid, "--state", "declined", "--reason", "off-topic")
        self.assertEqual([r["kind"] for r in self.kinds()[-2:]], ["hold", "ship-decline"])

    def test_revise_themes_split_the_count(self):
        for i, t in enumerate(("t0001", "t0002", "t0003")):
            store.signal(self.root, "revise-weakness", t, {"theme": ("intro", "tone", "search")[i]})
        self.assertEqual(store.evolve_readiness(self.root, self.cfg)["tier"], "watching")
        store.signal(self.root, "revise-weakness", "t0004", {"theme": "intro"})
        store.signal(self.root, "revise-weakness", "t0005", {"theme": "intro"})
        r = store.evolve_readiness(self.root, self.cfg)
        self.assertEqual((r["tier"], r["ready_themes"]), ("sufficient", ["revise-weakness:intro"]))


    def test_loopback_edges_amend_gate_and_dismissal_once(self):
        tid, slug = self.run_flow()
        self.write("src/content/blog/%s.md" % slug, "no frontmatter at all")
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", "--amend", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/signals.jsonl")))  # human's edit
        self.article(slug)
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "gate")
        self.assertEqual((out["loopbacks"], out["escalate_tier"]), (1, False))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/signals.jsonl")))
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "verify", "--theme", "intro", check=False)
        self.assertIn("--theme applies only", p.stderr)
        crit = json.loads(json.dumps(CRIT_PASS))
        crit["decision_log"] = [{"kind": "dismissal", "note": "MAJOR-1 policy", "round": 1}]
        write_machine(self, tid, "critique.json", crit, slug)
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "audit", "--theme", "policy", "--note", "B-1")
        self.assertTrue(out["escalate_tier"])
        out, _ = self.hrd("loopback", "--topic", tid, "--human")
        self.assertFalse(out["escalate_tier"])
        self.hrd("loopback", "--topic", tid, "--cause", "verify")
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "verify")
        self.assertEqual((out["exhausted"], out["escalate_tier"]), (True, False))
        kinds = [r["kind"] for r in self.kinds()]
        self.assertEqual(kinds.count("escalation"), 2)  # loopbacks 2 and 3 only
        dis = [r for r in self.kinds() if r["kind"] == "dismissal"]
        self.assertEqual(len(dis), 1)
        self.hrd("evolve-mark", "--consume", store.signal_id(dis[0]))
        store.record_dismissals(self.root, tid, crit)  # a later critique pass re-derives it
        self.assertEqual(sum(r["kind"] == "dismissal" for r in self.kinds()), 1)
        _, p = self.hrd("state", "--topic", tid, "--state", "held", "--reason", "x", env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("unattended", p.stderr)

    def test_bad_verdict_files_never_break_a_counted_loopback(self):
        tid, slug = self.run_flow()
        self.write(".claude/herald/work/%s/verify.json" % tid, "{broken")
        out, p = self.hrd("loopback", "--topic", tid, "--cause", "verify")
        self.assertEqual(out["loopbacks"], 1)
        self.write(".claude/herald/work/%s/critique.json" % tid, "[1]")
        out, p = self.hrd("loopback", "--topic", tid, "--cause", "audit", "--theme", "tone")
        self.assertEqual((out["loopbacks"], out["escalate_tier"]), (2, True))
        self.assertEqual([r["kind"] for r in self.kinds()], ["verify-gap", "audit-finding", "escalation"])

    def test_critique_pass_after_consume_and_human_caused_holds(self):
        tid, slug = self.run_flow()
        crit = json.loads(json.dumps(CRIT_PASS))
        crit["decision_log"] = [{"kind": "dismissal", "note": "MAJOR-1 policy"}]
        self.hrd("loopback", "--topic", tid, "--cause", "gate")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        write_machine(self, tid, "critique.json", crit, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        dis = [r for r in self.kinds() if r["kind"] == "dismissal"]
        self.hrd("evolve-mark", "--consume", store.signal_id(dis[0]))
        self.hrd("loopback", "--topic", tid, "--cause", "gate")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        self.write(".claude/herald/work/%s/critique.md" % tid, "round 2")
        write_machine(self, tid, "critique.json", crit, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        self.assertEqual(sum(r["kind"] == "dismissal" for r in self.kinds()), 1)
        sh(self.root, "git", "stash", "-u", "-q")
        sh(self.root, "git", "switch", "-q", "main")
        self.hrd("state", "--topic", tid, "--state", "held", "--reason", "verify-after-human-edit")
        self.hrd("state", "--topic", tid, "--state", "held", "--reason", "stagnation")
        self.assertEqual([r["data"].get("reason") for r in self.kinds() if r["kind"] == "hold"], ["stagnation"])
        store.signal(self.root, "stagnation", "t0009", {})  # a 0.2.x record
        self.assertIn("hold:stagnation", store.evolve_readiness(self.root, self.cfg)["themes"])

    def test_version_stale_counts_gate_once_legacy_and_dismissal_by_note(self):
        import subprocess, sys as _sys
        from helpers import SCRIPTS
        out = subprocess.run([_sys.executable, os.path.join(SCRIPTS, "hrd.py"), "version"], cwd=self.tmp,
                             capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout)["version"],
                         json.load(open(os.path.join(SCRIPTS, "..", "..", "..", ".claude-plugin", "plugin.json")))["version"])
        tid, slug = self.run_flow()
        self.article(slug, extra="\nchanged")  # verify.json now describes an older body
        self.hrd("loopback", "--topic", tid, "--cause", "verify")
        self.assertNotIn("counts", self.kinds()[-1]["data"])
        self.write("src/content/blog/%s.md" % slug, "no frontmatter at all")
        for _ in range(2):
            self.hrd("stage", "pass", "--topic", tid, "--stage", "draft", check=False)
        self.assertEqual(sum(r["kind"] == "gate-failure" for r in self.kinds()), 1)  # retries of one draft
        self.hrd("loopback", "--topic", tid, "--human")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft", check=False)
        self.assertEqual(sum(r["kind"] == "gate-failure" for r in self.kinds()), 1)  # human's revision
        store.signal(self.root, "dismissal", tid, {"note": "MAJOR-1 policy", "by": "hand (0.2.x)"})
        store.record_dismissals(self.root, tid, {"decision_log": [{"kind": "dismissal", "note": "MAJOR-1 policy", "round": 2}]})
        self.assertEqual(sum(r["kind"] == "dismissal" for r in self.kinds()), 1)
        store.signal(self.root, "hold", "t0007", {"reason": "stagnation"})
        store.signal(self.root, "stagnation", "t0007", {"x": 1})
        self.assertEqual(store.evolve_readiness(self.root, self.cfg)["themes"]["hold:stagnation"]["count"], 1)

    def test_malformed_counts_new_attempt_gate_and_noteless_dismissal(self):
        tid, slug = self.run_flow()
        write_machine(self, tid, "verify.json", {"counts": {"unsupported": "two"}}, slug)
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "verify")
        self.assertEqual(out["loopbacks"], 1)
        self.write("src/content/blog/%s.md" % slug, "no frontmatter at all")
        self.hrd("loopback", "--topic", tid, "--cause", "gate")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft", check=False)
        st = store.load_state(self.root, tid)
        st["created_at"], st["loopbacks"] = "2099-01-01T00:00:00+00:00", 2  # requeued: a new attempt
        store.save_state(self.root, tid, st)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft", check=False)
        self.assertEqual(sum(r["kind"] == "gate-failure" for r in self.kinds()), 2)
        log = {"decision_log": [{"kind": "dismissal", "finding": "MAJOR-2"}]}
        store.record_dismissals(self.root, tid, log)
        store.record_dismissals(self.root, tid, log)
        self.assertEqual(sum(r["kind"] == "dismissal" for r in self.kinds()), 1)

    def test_version_relation_and_tooling_holds(self):
        from hrdlib import batch
        out, _ = self.hrd("version", "--against", "0.0.1")
        self.assertEqual(out["relation"], "newer")
        out, _ = self.hrd("version", "--against", "99.10.0")
        self.assertEqual(out["relation"], "older")
        self.assertEqual(self.hrd("version", "--against", out["version"])[0]["relation"], "equal")
        self.assertEqual(self.hrd("version", "--against", "0.10.0")[0]["relation"], "older")  # not string order
        short = ".".join(out["version"].split(".")[:2]) if out["version"].endswith(".0") else out["version"]
        self.assertEqual(self.hrd("version", "--against", short)[0]["relation"], "equal")  # 0.3 == 0.3.0
        _, p = self.hrd("version", "--against", "0.3.0-rc1", check=False)
        self.assertIn("malformed version", p.stderr)
        self.write(".claude/herald/scripts/hrd.py", 'x = 1\nSCRIPTS_VERSION = "9.9.9"\n')
        self.assertEqual(batch.scripts_version(self.root), "9.9.9")
        store.save_topics(self.root, {"version": 1, "topics": [{"id": "t0001", "title": "T", "state": "queued",
                                                                 "history": [], "reverted_by": []}]})
        self.hrd("state", "--topic", "t0001", "--state", "held", "--reason", "needs-human",
                 "--note", "tooling: herald version mismatch")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/signals.jsonl")))

    def test_legacy_tooling_holds_and_human_choice_not_counted(self):
        for t in ("t0001", "t0002", "t0003"):
            store.signal(self.root, "hold", t, {"reason": "needs-human", "note": "batch child did not finish (exited:1)"})
        self.assertEqual(store.evolve_readiness(self.root, self.cfg)["tier"], "none")
        store.save_topics(self.root, {"version": 1, "topics": [{"id": "t0001", "title": "T", "state": "queued",
                                                                 "history": [], "reverted_by": []}]})
        self.hrd("state", "--topic", "t0001", "--state", "held", "--reason", "needs-human", "--note", "human: later")
        self.assertEqual(store.evolve_readiness(self.root, self.cfg)["tier"], "none")

    def test_escalations_not_counted_and_holds_split_by_reason(self):
        for t in ("t0001", "t0002", "t0003"):
            store.signal(self.root, "escalation", t, {"loopback": 2})
            store.signal(self.root, "hold", t, {"reason": ("budget", "research", "budget")[int(t[-1]) - 1]})
        r = store.evolve_readiness(self.root, self.cfg)
        self.assertEqual((r["tier"], r["kinds"]["escalation"], sorted(r["themes"])),
                         ("watching", 3, ["hold:budget", "hold:research"]))
        store.signal(self.root, "hold", "t0004", {"reason": "budget"})
        self.assertEqual(store.evolve_readiness(self.root, self.cfg)["ready_themes"], ["hold:budget"])


if __name__ == "__main__":
    unittest.main()
