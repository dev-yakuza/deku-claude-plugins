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
    if name == "verify.json" and "verdicts" not in obj and "by_lang" not in obj:
        obj = with_verdicts(obj)
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


def with_verdicts(ver):
    """A 0.24.0 verify.json from an older fixture (15 D1): the claims map of these flows is empty, so
    each listed text is an unmapped `unsupported` verdict and the counts follow the verdicts."""
    listed = [x for x in ver.get("unsupported_sentences") or [] if isinstance(x, str)]
    ver["verdicts"] = [{"text": x, "verdict": "unsupported", "claims": [], "why": "no claim says it"} for x in listed]
    c = ver.setdefault("counts", {})
    if listed:
        c.update(unsupported=len(listed), unmapped=len(listed))
    c["supported"] = 0
    return ver


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
        self.write(".claude/herald/work/%s/research.md" % tid, "C1. source")
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


class AccuracyTests(Flow):
    VER_SUSPECT = {"counts": {"supported": 2, "unsupported": 0, "contradicted": 1, "unmapped": 0},
                   "research_suspects": [{"claim": "C1", "reason": "example sits under sense 1",
                                          "sentences": ["x"]}]}
    VER_CONTRA = {"counts": {"supported": 0, "unsupported": 0, "contradicted": 1, "unmapped": 0},
                  "verdicts": [{"text": "Body text for new-post.", "verdict": "contradicted", "claims": ["C1"],
                                "why": "C1 says otherwise"}]}

    def spend(self, tid, n=3):
        for _ in range(n):
            self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "depth")

    def test_research_fix_goes_to_researcher_and_keeps_claim_ids(self):
        tid, slug = self.run_flow()
        write_machine(self, tid, "verify.json", self.VER_SUSPECT, slug)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertIn("research_suspects", p.stderr)  # a listed suspect never passes verify
        self.write(".claude/herald/work/%s/research.md" % tid, "C1. source\nC2. other")
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "verify", check=False)
        self.assertIn("--cause research", p.stderr)
        _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
        self.assertNotEqual(p.returncode, 0)
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "research", "--claims", "C2", check=False)
        self.assertIn("exactly the suspects", p.stderr)
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "research", "--claims", "C1", "--note", "sense")
        self.assertEqual((out["stage"], out["loopbacks"]), ("research", 1))
        self.assertIsNone(store.load_state(self.root, tid)["verified_hash"])
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "research", "--claims", "C1", check=False)
        self.assertIn("research fix is open", p.stderr)  # one fix at a time
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "draft", check=False)
        self.assertIn("research fix is open", p.stderr)  # the researcher is never skipped
        _, p = self.hrd("loopback", "--topic", tid, "--human", check=False)
        self.assertIn("research fix is open", p.stderr)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "research", check=False)
        self.assertIn("unchanged since the research fix", p.stderr)
        self.write(".claude/herald/work/%s/research.md" % tid, "no claim here")
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "research", check=False)
        self.assertIn("no claim the tools can find", p.stderr)
        self.write(".claude/herald/work/%s/research.md" % tid, "C1. corrected\ncorrected: x")  # C2 lost
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "research", check=False)
        self.assertIn("C2", p.stderr)
        self.write(".claude/herald/work/%s/research.md" % tid, "C1. corrected\nC2. other\nC3. new")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "research")
        st = store.load_state(self.root, tid)
        self.assertEqual((st["stage"], st["research_fixes"][-1]["status"]), ("draft", "done"))
        self.assertEqual(st["research_fixes"][-1]["claims"], ["C1"])
        sig = [json.loads(x) for x in open(os.path.join(self.root, ".claude/herald/signals.jsonl"))]
        self.assertTrue(any(r["kind"] == "research-error" and r["data"]["claims"] == ["C1"] for r in sig))
        # the draft is checked against the corrected research
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        # the same claim found wrong again after its fix: no second fix, the session holds
        write_machine(self, tid, "verify.json", self.VER_SUSPECT, slug)
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "research", "--claims", "C1", check=False)
        self.assertIn("stagnation", p.stderr)

    def test_malformed_suspects_refused_and_claim_ids_are_line_starts(self):
        tid, slug = self.run_flow()
        write_machine(self, tid, "verify.json", dict(self.VER_CONTRA, research_suspects=["C1"]), slug)
        for args in (("loopback", "--topic", tid, "--cause", "verify"),
                     ("stage", "pass", "--topic", tid, "--stage", "verify")):
            _, p = self.hrd(*args, check=False)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("malformed", p.stderr)
        self.write(".claude/herald/work/%s/research.md" % tid, "**C1.** claim (see\nC40 grade)\n### C2: two\n> C7 note\n"
                   "C3 level wraps\n| C5 | row |\n1. **C6.** x\nClaim C8: y\n- C9 — z\nC10.5 percent\nC11：jp")
        self.assertEqual(store.research_claim_ids(self.root, tid), ["C1", "C2", "C5", "C6", "C8", "C9", "C11"])

    def test_research_pass_refuses_claims_it_cannot_read(self):
        tid, slug = self.run_flow()
        st = store.load_state(self.root, tid)
        st["stage"] = "research"
        store.save_state(self.root, tid, st)
        self.write(".claude/herald/work/%s/research.md" % tid, "**C1.** a\n**C2** b\n- C3 c")
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "research", check=False)
        self.assertIn("C2, C3", p.stderr)

    def test_research_change_after_verify_blocks_publish(self):
        tid, slug = self.run_flow()
        self.write(".claude/herald/work/%s/research.md" % tid, "C1 changed")
        _, p = self.hrd("finalize", "--topic", tid, check=False)
        self.assertIn("research.md", p.stderr)

    def test_accuracy_reserve_only_for_a_wrong_fact(self):
        tid, slug = self.run_flow()
        self.spend(tid)
        write_machine(self, tid, "verify.json", VER_PASS, slug)  # nothing contradicted: no reserve
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "verify")
        self.assertEqual((out["exhausted"], out["accuracy_reserve"]), (True, False))

    def test_accuracy_reserve_answers_a_contradicted_sentence_once(self):
        tid, slug = self.run_flow()
        self.spend(tid)
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "depth")
        self.assertTrue(out["exhausted"])  # readability and audit never reach it
        self.write(".claude/herald/work/%s/claims-map.json" % tid,
                   json.dumps({"sentences": [{"text": "Body text for new-post.", "claims": ["C1"]}]}))
        write_machine(self, tid, "verify.json", self.VER_CONTRA, slug)
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "verify")
        self.assertEqual((out["exhausted"], out["accuracy_reserve"], out["escalate_tier"]), (False, True, True))
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "verify")  # once per article
        self.assertEqual((out["exhausted"], out["accuracy_reserve"]), (True, False))

    def test_accuracy_reserve_covers_a_research_fix(self):
        tid, slug = self.run_flow()
        self.spend(tid)
        write_machine(self, tid, "verify.json", self.VER_SUSPECT, slug)
        out, _ = self.hrd("loopback", "--topic", tid, "--cause", "research", "--claims", "C1")
        self.assertEqual((out["exhausted"], out["accuracy_reserve"], out["stage"]), (False, True, "research"))
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "verify", "--claims", "C1", check=False)
        self.assertIn("--claims applies only", p.stderr)


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
    def pr_head(self):
        """Commit the work as the PR head would carry it, back on base; the stamp reads it there."""
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "pr head")
        branch = sh(self.root, "git", "branch", "--show-current").strip()
        sh(self.root, "git", "switch", "-q", "main")
        return ("--rev", branch, "--sha", sh(self.root, "git", "rev-parse", branch).strip(), "--consent")  # the article adds images: accepted only with consent

    def test_session_auto_stamp_keeps_a_later_record_unreviewed(self):
        tid, slug = self.run_flow()
        rev = self.pr_head()
        out, _ = self.hrd("auto-merged", "--topic", tid, "--pr", "12", *rev)
        self.assertEqual(out["auto_merged_pr"], 12)
        _, p = self.hrd("auto-merged", "--topic", tid, "--pr", "12", *rev, env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertNotEqual(p.returncode, 0)  # the batch runner stamps its own
        _, p = self.hrd("auto-merged", "--topic", tid, "--pr", "13", *rev, check=False)
        self.assertIn("already carries", p.stderr)
        for bad in (("--pr", "0", *rev), ("--pr", "12", "--clear"), (), ("--pr", "12"),
                    ("--pr", "12", *rev, "--sha", "0" * 40)):
            _, p = self.hrd("auto-merged", "--topic", tid, *bad, check=False)
            self.assertNotEqual(p.returncode, 0, bad)
        self.assertEqual(self.hrd("throttle")[0]["used"], 1)  # an unrecorded auto merge counts today
        rec, _ = self.hrd("record-published", "--topic", tid, "--slug", slug, "--pr", "12")
        self.assertFalse(rec["human_reviewed"])  # a plain later ship cannot turn it into a reviewed article
        self.assertEqual(self.hrd("throttle")[0]["used"], 1)  # counted once, recorded or not
        _, p = self.hrd("state", "--topic", tid, "--state", "queued", check=False)
        self.assertIn("already published", p.stderr)
        _, p = self.hrd("auto-merged", "--topic", tid, "--pr", "12", *rev, check=False)
        self.assertIn("already published", p.stderr)

    def test_clear_undoes_a_stamp_whose_merge_failed(self):
        tid, slug = self.run_flow()
        rev = self.pr_head()
        self.hrd("auto-merged", "--topic", tid, "--pr", "5", *rev)
        out, _ = self.hrd("auto-merged", "--topic", tid, "--clear")
        self.assertIsNone(out["auto_merged_pr"])
        self.assertEqual(self.hrd("throttle")[0]["used"], 0)


ARTICLE_BODY_AND_EXTRA = "Body text for new-post. ![x](/blog-images/new-post/01.png)\n\nListening daily helps"


class TrimTests(Flow):
    EXTRA = "\nListening daily helps (often called shadowing). The app does not read examples aloud.\n"
    S1 = "Listening daily helps (often called shadowing)."
    S2 = "The app does not read examples aloud."

    def to_verify_gap(self, tid="t0001", slug="new-post", ver=None):
        """critique passed, verify found unsupported sentences (stage stays verify)."""
        store.save_topics(self.root, {"version": 1, "topics": [{"id": tid, "title": "T", "state": "queued",
                                                                 "history": [], "reverted_by": []}]})
        self.commit("topics")
        self.hrd("begin", "--topic", tid)
        self.write(".claude/herald/work/%s/brief.md" % tid, "brief")
        self.hrd("branch", "--topic", tid, "--slug", slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "brief")
        self.write(".claude/herald/work/%s/research.md" % tid, "C1. source")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "research")
        self.article(slug, self.EXTRA)
        self.write(".claude/herald/work/%s/claims-map.json" % tid, "{}")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        self.write(".claude/herald/work/%s/critique.md" % tid, "ok")
        write_machine(self, tid, "critique.json", CRIT_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        self.write(".claude/herald/work/%s/verify.md" % tid, "two unsupported")
        write_machine(self, tid, "verify.json", ver or {
            "counts": {"supported": 3, "unsupported": 2, "contradicted": 0, "unmapped": 1},
            "unsupported_sentences": [self.S1, self.S2]}, slug)
        return tid, slug

    def body(self, slug):
        with open(os.path.join(self.root, "src/content/blog/%s.md" % slug)) as f:
            return f.read()

    def finish_with(self, tid, slug, body):
        self.write("src/content/blog/%s.md" % slug, body)
        return self.hrd("trim", "--topic", tid, "--finish", check=False)

    def test_a_sentence_holding_an_image_is_never_trimmed(self):
        # trim never touches images: deleting the reference would leave the file deployed
        # (design/herald/06-screenshots.md §2.7) — the old check only refused cutting through it
        S = "See the page ![p](/blog-images/new-post/01.png) for details."
        self.EXTRA = "\n" + S + " " + self.S2 + "\n"
        tid, slug = self.to_verify_gap(ver={"counts": {"unsupported": 2, "contradicted": 0},
                                            "unsupported_sentences": [S, self.S2]})
        _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
        self.assertIn("holds an image reference", p.stderr)

    def test_deletion_carries_critique_over_and_verify_runs_again(self):
        tid, slug = self.to_verify_gap(ver={"counts": {"unsupported": 2, "contradicted": 0},
                                            "unsupported_sentences": ["(often called shadowing)", self.S2]})
        out, _ = self.hrd("trim", "--topic", tid, "--begin")
        self.assertEqual(out["sentences"], ["(often called shadowing)", self.S2])
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "verify", check=False)
        self.assertIn("trim is open", p.stderr)
        self.write(".claude/herald/work/%s/claims-map.json" % tid, '{"sentences": []}')
        out, _ = self.finish_with(tid, slug, self.body(slug).replace(" (often called shadowing)", "")
                                  .replace(" " + self.S2, ""))
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["removed"], ["(often called shadowing)", self.S2])
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertIn("does not evaluate the current article", p.stderr)  # the old verify.json is stale
        self.assertTrue(self.hrd("stage", "check", "--topic", tid, "--stage", "verify")[0]["ok"])
        write_machine(self, tid, "verify.json", VER_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        self.hrd("finalize", "--topic", tid)  # critique hash == verify hash == the trimmed body
        self.assertEqual([t["status"] for t in store.load_state(self.root, tid)["trims"]], ["done"])
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".claude/herald/memory/trim", tid)))  # re-verified
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl")) as f:
            gaps = [json.loads(x) for x in f if '"verify-gap"' in x]
        self.assertEqual(len(gaps), 1)
        self.assertTrue(gaps[0]["data"]["trim"])
        reasons = self.hrd("auto-exclusion", "--topic", tid)[0]
        self.assertIn("trimmed", reasons["blocking"])
        self.assertNotIn("trimmed", self.hrd("auto-exclusion", "--topic", tid, "--consent")[0]["blocking"])

    def test_only_whole_listed_sentences_or_asides_may_go(self):
        tid, slug = self.to_verify_gap()
        self.hrd("trim", "--topic", tid, "--begin")
        body = self.body(slug)
        for changed in (body.replace("helps", "helps a lot"),          # added words
                        body.replace(" not", ""),                       # a negation inside a listed sentence
                        body.replace("Body text", "Body"),              # outside the listed sentences
                        body.replace("category: guide\n", ""),          # frontmatter
                        body.replace("helps (often", "helps. (often"),   # punctuation added
                        body.replace("\nListening", "\n    Listening"),  # re-indented (a code block)
                        body.replace(" (often called shadowing)", ""),  # an aside the fact-checker did not list
                        body.replace(self.S1 + " ", "\n    ")):  # a seam that changes the structure
            _, p = self.finish_with(tid, slug, changed)
            self.assertIn("changed beyond deleting", p.stderr)
        out, _ = self.finish_with(tid, slug, body.replace(self.S1 + " " + self.S2, ""))
        self.assertEqual(out["removed"], [self.S1, self.S2])

    def test_abort_restores_body_and_images_and_the_gap_is_counted_once(self):
        tid, slug = self.to_verify_gap()
        base = worktree_hash(self.root, self.cfg, slug)
        self.hrd("trim", "--topic", tid, "--begin")
        self.write("public/blog-images/%s/01.png" % slug, b"\x89PNG other", binary=True)
        self.write("public/blog-images/%s/02.png" % slug, b"\x89PNG new", binary=True)
        _, p = self.finish_with(tid, slug, self.body(slug).replace(self.S2, ""))
        self.assertIn("images changed", p.stderr)
        out, _ = self.hrd("trim", "--topic", tid, "--abort")
        self.assertTrue(out["restored"])
        self.assertEqual(worktree_hash(self.root, self.cfg, slug), base)
        _, p = self.hrd("trim", "--topic", tid, "--finish", check=False)
        self.assertIn("no open trim", p.stderr)
        _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
        self.assertIn("already tried on this verify result", p.stderr)  # an aborted trim ends this gap's trims
        self.hrd("loopback", "--topic", tid, "--cause", "verify")
        with open(os.path.join(self.root, ".claude/herald/signals.jsonl")) as f:
            self.assertEqual(sum('"verify-gap"' in x for x in f), 1)

    def gap_for(self, extra, listed):
        self.tearDown()
        self.setUp()
        self.EXTRA = extra
        return self.to_verify_gap(ver={"counts": {"unsupported": len(listed)}, "unsupported_sentences": listed})

    def test_listed_text_must_be_whole_sentences_or_a_named_aside(self):
        for extra, listed in ((self.EXTRA, ["not"]), (self.EXTRA, ["Body text for new-post"]),
                              (self.EXTRA, [ARTICLE_BODY_AND_EXTRA]),
                              ("\nThe safe dose is 2.5 mg daily.\n", ["5 mg daily."]),
                              ("\nThe safe dose is 2.5 mg daily.\n", ["The safe dose is 2."]),
                              ("\nDo not\nmix it with alcohol.\n", ["Do not"]),
                              ("\nChildren can use it\nonly under supervision.\n", ["only under supervision."]),
                              ("\nUse e.g. aspirin for kids.\n", ["aspirin for kids."]),
                              ("\n「AはBだ。」と彼は言った。\n", ["「AはBだ。」"]),
                              ("\nAsk Dr. Smith said it works.\n", ["Smith said it works."]),
                              ("\nIt was approved by the U.S. Food agency in 2020.\n", ["Food agency in 2020."]),
                              ("\n専門家は「この薬は安全だ。」と述べた。\n", ["と述べた。"])):
            tid, _ = self.gap_for(extra, listed)
            _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
            self.assertIn("not a whole sentence", p.stderr, listed)
        for extra, listed in (("\nSee [the guide](/blog/old-post/) for details.\n", ["(/blog/old-post/)"]),
                              ("\nRun `rm -rf $(pwd)/build` now.\n", ["(pwd)"]),
                              ("\nSee https://example.test/a_(b) now.\n", ["(b)"]),
                              ("\n- item\n\n   ```\n   This is safe.\n   ```\n", ["This is safe."])):
            tid, _ = self.gap_for(extra, listed)
            _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
            self.assertTrue("link, code or URL" in p.stderr or "not a whole sentence" in p.stderr, (listed, p.stderr))
        tid, slug = self.gap_for("\nSee [the guide](/blog/old-post/) for details (in Korean).\n", ["(in Korean)"])
        self.hrd("trim", "--topic", tid, "--begin")
        out, _ = self.finish_with(tid, slug, self.body(slug).replace(" (in Korean)", ""))
        self.assertEqual(out["removed"], ["(in Korean)"])

    def test_seams_keep_the_markdown_structure(self):
        extra = "\nFirst point.\n\nUnsupported point.\n\n## Warnings\n"
        tid, slug = self.gap_for(extra, ["Unsupported point."])
        self.hrd("trim", "--topic", tid, "--begin")
        body = self.body(slug)
        for bad in (body.replace("First point.\n\nUnsupported point.\n\n## Warnings", "First point. ## Warnings"),
                    body.replace("Unsupported point.\n\n## Warnings", "\n    ## Warnings")):
            _, p = self.finish_with(tid, slug, bad)
            self.assertIn("changed beyond deleting", p.stderr)
        out, _ = self.finish_with(tid, slug, body.replace("Unsupported point.\n\n", ""))
        self.assertEqual(out["status"], "done")

    def test_a_whole_list_item_goes_with_its_mark(self):
        tid, slug = self.gap_for("\n- First.\n- Unsupported.\n- Third.\n", ["Unsupported."])
        self.hrd("trim", "--topic", tid, "--begin")
        _, p = self.finish_with(tid, slug, self.body(slug).replace("Unsupported.", ""))
        self.assertIn("changed beyond deleting", p.stderr)  # an empty bullet would stay
        out, _ = self.finish_with(tid, slug, self.body(slug).replace("\n- Unsupported.", "", 1)
                                  if "- Unsupported." in self.body(slug) else
                                  self.body(slug).replace("- \n", "", 1))
        self.assertEqual(out["removed"], ["- Unsupported."])

    def test_items_with_attached_lines_headings_and_warnings_are_not_trimmed(self):
        for extra, listed, msg in (
                ("\n- Aspirin is fine.\n- Ibuprofen is approved.\n  It is not safe for children.\n- Other.\n",
                 ["Ibuprofen is approved."], "lines attached below"),
                ("\n## Dosage notes.\n\nTake one.\n", ["Dosage notes."], "whole heading")):
            tid, _ = self.gap_for(extra, listed)
            _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
            self.assertIn(msg, p.stderr)
        self.tearDown()
        self.setUp()
        tid, _ = self.to_verify_gap(ver={"counts": {"unsupported": 2}, "unsupported_sentences": [self.S1, self.S2],
                                         "unsupported_qualifiers": [self.S2]})
        _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
        self.assertIn("warning or limit", p.stderr)

    def test_seams_do_not_glue_words(self):
        tid, slug = self.gap_for("\nFirst one. Unsupported two. Third (aside) here.\n", ["Unsupported two.", "(aside)"])
        self.hrd("trim", "--topic", tid, "--begin")
        body = self.body(slug)
        for bad in (body.replace(" Unsupported two. ", ""), body.replace(" (aside) ", "")):
            _, p = self.finish_with(tid, slug, bad)
            self.assertIn("changed beyond deleting", p.stderr)
        out, _ = self.finish_with(tid, slug, body.replace(" Unsupported two.", "").replace(" (aside)", ""))
        self.assertEqual(out["status"], "done")
        tid, slug = self.gap_for("\n듣기는 매일 (섀도잉) 도움이 된다. 다른 문장이다.\n", ["(섀도잉)"])
        self.hrd("trim", "--topic", tid, "--begin")
        _, p = self.finish_with(tid, slug, self.body(slug).replace(" (섀도잉) ", ""))
        self.assertIn("changed beyond deleting", p.stderr)  # Hangul is written with spaces
        out, _ = self.finish_with(tid, slug, self.body(slug).replace("매일도움", "매일 (섀도잉) 도움").replace(" (섀도잉)", ""))
        self.assertEqual(out["status"], "done")

    def test_claims_map_changes_only_for_listed_texts(self):
        tid, slug = self.to_verify_gap()
        cm = {"sentences": [{"text": "Body text for new-post.", "claims": ["C1"]}]}
        self.write(".claude/herald/work/%s/claims-map.json" % tid, json.dumps(cm))
        st = store.load_state(self.root, tid)  # as if draft had passed with this map
        from hrdlib.hashing import file_hash
        st["stages"]["draft"]["outputs"]["claims-map.json"] = file_hash(self.root, store.work_rel(tid, "claims-map.json"))
        store.save_state(self.root, tid, st)
        ver = with_verdicts({"unsupported_sentences": [self.S1, self.S2]})
        ver["verdicts"].append({"text": "Body text for new-post.", "verdict": "supported", "claims": ["C1"]})
        ver["counts"]["supported"] = 1
        write_machine(self, tid, "verify.json", ver, slug)
        self.hrd("trim", "--topic", tid, "--begin")
        self.write(".claude/herald/work/%s/claims-map.json" % tid, json.dumps(
            {"sentences": [{"text": "Body text for new-post.", "claims": ["C9"]}]}))
        _, p = self.finish_with(tid, slug, self.body(slug).replace(" " + self.S2, ""))
        self.assertIn("claims-map.json changed outside", p.stderr)
        self.write(".claude/herald/work/%s/claims-map.json" % tid, json.dumps(
            {"sentences": cm["sentences"] + [{"text": self.S1, "claims": ["C1"]}]}))
        out, _ = self.finish_with(tid, slug, self.body(slug).replace(" " + self.S2, ""))
        self.assertEqual(out["status"], "done")

    def test_a_changed_critique_file_refuses_the_trim(self):
        tid, slug = self.to_verify_gap()
        self.hrd("trim", "--topic", tid, "--begin")
        self.write(".claude/herald/work/%s/critique.json" % tid, json.dumps({"final_round": {"verdict": "PASS"}}))
        _, p = self.finish_with(tid, slug, self.body(slug).replace(" " + self.S2, ""))
        self.assertIn("critique.json changed", p.stderr)

    def test_open_trim_blocks_stages_and_a_later_critique_supersedes_it(self):
        tid, slug = self.to_verify_gap()
        self.hrd("trim", "--topic", tid, "--begin")
        _, p = self.hrd("stage", "check", "--topic", tid, "--stage", "verify", check=False)
        self.assertIn("trim is open", p.stdout)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertIn("trim is open", p.stderr)
        self.finish_with(tid, slug, self.body(slug).replace(" " + self.S2, ""))
        self.assertIn("trimmed", self.hrd("auto-exclusion", "--topic", tid)[0]["reasons"])
        self.hrd("loopback", "--topic", tid, "--cause", "verify")
        self.write("src/content/blog/%s.md" % slug, self.body(slug) + "\nRewritten.\n")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        write_machine(self, tid, "critique.json", CRIT_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        self.assertNotIn("trimmed", self.hrd("auto-exclusion", "--topic", tid)[0]["reasons"])

    def test_force_abort_closes_a_trim_whose_snapshot_is_gone(self):
        import shutil
        tid, slug = self.to_verify_gap()
        self.hrd("trim", "--topic", tid, "--begin")
        shutil.rmtree(os.path.join(self.root, ".claude/herald/memory/trim", tid))
        _, p = self.hrd("trim", "--topic", tid, "--finish", check=False)
        self.assertIn("snapshot changed or is gone", p.stderr)
        _, p = self.hrd("trim", "--topic", tid, "--abort", check=False)
        self.assertIn("--force", p.stderr)
        out, _ = self.hrd("trim", "--topic", tid, "--abort", "--force")
        self.assertFalse(out["restored"])
        self.hrd("loopback", "--topic", tid, "--cause", "verify")

    def test_trim_only_repairs_a_small_listed_uncontradicted_gap(self):
        for ver, msg in (({"counts": {"unsupported": 1, "contradicted": 1}}, "contradicted"),
                         ({"counts": {"unsupported": 4, "contradicted": 0}}, "1 to 3"),
                         ({"counts": {"unsupported": 0, "contradicted": 0}}, "1 to 3"),
                         ({"counts": {"unsupported": 1, "contradicted": 0}}, "verbatim"),
                         ({"counts": {"unsupported": 1}, "unsupported_sentences": ["Not in the body."]}, "found 0 times"),
                         ({"counts": {"unsupported": 1}, "unsupported_sentences": ["title: Hello"]}, "found 0 times")):
            self.tearDown()
            self.setUp()
            tid, _ = self.to_verify_gap(ver=ver)
            _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
            self.assertIn(msg, p.stderr)
        self.write("src/content/blog/new-post.md", self.body("new-post") + "x")
        _, p = self.hrd("trim", "--topic", "t0001", "--begin", check=False)
        self.assertIn("critique did not pass on the current article", p.stderr)


# t0010 (ildangongbu-website 2f2c172, body lines 86–109): a table cell copied inside a later FAQ
# sentence (89/105) and one sentence written twice (93/109)
T0010 = ("---\ntitle: t\n---\n"
         '| --- | --- | --- | --- |\n'
         '| 〜ぞ | 문장 끝의 종조사 | 결의를 스스로 다짐하거나 자기 생각을 강하게 주장하며 다짐합니다. | 「<ruby>明日<rp>(</rp><rt>あした</rt><rp>)</rp></ruby>は<ruby>必<rp>(</rp><rt>かなら</rt><rp>)</rp></ruby>ず<ruby>早<rp>(</rp><rt>はや</rt><rp>)</rp></ruby>く<ruby>起<rp>(</rp><rt>お</rt><rp>)</rp></ruby>きるぞ。」 |\n'
         '일상에서 쓸 때의 수위는 표현마다 다릅니다. 「<ruby>読<rp>(</rp><rt>よ</rt><rp>)</rp></ruby>んでやる」처럼 내가 해낼 일에 붙이면 강한 의지를 나타냅니다. 「ぜ」는 윗사람에게 쓰지 않는 말이므로 학교나 직장에서는 피합니다.\n'
         '### 「ぞ」와 「ぜ」는 무엇이 다른가요?\n'
         '「ぞ」는 결의를 스스로 다짐하거나 자기 생각을 강하게 주장하며 다짐합니다. 「ぜ」는 친근함을 담아 가볍게 다짐하는 뜻이고, 남성어이며 다소 거친 느낌이 따릅니다.\n'
         '### 「〜てやる」는 윗사람에게 써도 되나요?\n'
         '상대를 위한 행동에 붙이는 「〜てやる」는 아랫사람을 위해 생색내는 느낌이 있어 윗사람에게 맞지 않습니다. 「<ruby>読<rp>(</rp><rt>よ</rt><rp>)</rp></ruby>んでやる」처럼 내가 해낼 일에 붙이면 강한 의지를 나타냅니다.\n')
T0010_CELL = "결의를 스스로 다짐하거나 자기 생각을 강하게 주장하며 다짐합니다."
T0010_FAQ = "「ぞ」는 결의를 스스로 다짐하거나 자기 생각을 강하게 주장하며 다짐합니다."
T0010_TWICE = "「<ruby>読<rp>(</rp><rt>よ</rt><rp>)</rp></ruby>んでやる」처럼 내가 해낼 일에 붙이면 강한 의지를 나타냅니다."


class CoverageTests(unittest.TestCase):
    """15 D1: every claims-map entry gets a verdict, matched by body span (store.coverage)."""

    def check(self, body, entries, verdicts, framings=None, **counts):
        body = "---\ntitle: t\n---\n" + body if not body.startswith("---") else body
        c = {"supported": 0, "unsupported": 0, "contradicted": 0, "unmapped": 0}
        for v in verdicts:
            if v["verdict"] != "not-factual":
                c[v["verdict"]] += 1
            v.setdefault("why", "one line")
        c.update(counts)
        rec = {"verdicts": verdicts, "counts": c,
               "unsupported_sentences": [v["text"] for v in verdicts if v["verdict"] == "unsupported"]}
        return store.coverage(body, store._body_start(body), entries, rec, framings)

    @staticmethod
    def v(text, verdict="supported"):
        return {"text": text, "verdict": verdict, "claims": ["C1"]}

    def test_a_missing_entry_and_an_old_verify_json_are_refused(self):
        r = self.check("One fact. Two fact.\n", ["One fact.", "Two fact."], [self.v("One fact.")])
        self.assertIn("no verdict for the claims-map entry 'Two fact.'", " ".join(r["problems"]))
        body = "---\ntitle: t\n---\nOne fact.\n"
        r = store.coverage(body, store._body_start(body), ["One fact."], {"counts": {"supported": 1}})
        self.assertIn("no `verdicts` list", r["problems"][0])
        r = self.check("One fact.\n", ["One fact.", "Gone fact."], [self.v("One fact.")])
        self.assertEqual((r["problems"], r["unplaced"]), ([], ["Gone fact."]))  # no place: no verdict needed
        r = self.check("One fact.\n", ["One fact.", "Gone fact."], [self.v("One fact."), self.v("Gone fact.", "unsupported")])
        self.assertEqual(r["problems"], [])  # a verdict on it is counted, never placed or refused
        r = self.check("Big: it runs. Small: it runs.\n", ["Big: it runs.", "Small: it runs.", "it runs."],
                       [self.v("Big: it runs."), self.v("Small: it runs."), self.v("it runs.", "contradicted")])
        self.assertEqual((r["problems"], r["unplaced"]), ([], ["it runs."]))  # nested in both, repeated: ignored

    def test_a_map_text_without_markup_is_placed_markdown_insensitively(self):
        from hrdlib import translation
        body = ("---\nt: x\n---\n「<ruby>紅葉<rp>(</rp><rt>もみじ</rt><rp>)</rp></ruby>」는 **단풍**입니다. "
                "[가이드](/g/)를 보세요.\n")
        lo = store._body_start(body)
        self.assertEqual(store._norm_tracked(body, lo)[0], translation.normalize(body[lo:]))
        entry = "「 紅葉 ( もみじ ) 」는 단풍입니다."  # t0011: the map wrote the ruby flattened
        r = self.check(body, [entry, "가이드를 보세요."], [self.v(entry), self.v("가이드를 보세요.")])
        self.assertEqual((r["problems"], r["unplaced"]), ([], []))
        a, b = r["spans"][entry][0]
        self.assertTrue(body[a:b].startswith("「<ruby>紅葉") and body[a:b].endswith("입니다."))

    def test_an_aside_or_one_sentence_marks_its_entry_and_a_listed_text_may_hold_entries(self):
        entry = "Listening daily helps (often called shadowing)."
        r = self.check(entry + "\n", [entry], [self.v("(often called shadowing)", "unsupported")])
        self.assertEqual(r["problems"], [])  # the aside's verdict marks the entry: mapped, not unmapped
        multi = "It runs at night. It stops at dawn."
        r = self.check(multi + "\n", [multi], [self.v("It stops at dawn.", "unsupported")])
        self.assertEqual(r["problems"], [])
        r = self.check(multi + "\n", ["It runs at night.", "It stops at dawn."], [self.v(multi, "contradicted")])
        self.assertEqual(r["problems"], [])  # one listed text marks both entries, counted once
        self.assertEqual(sorted(r["listed"]), [multi])

    def test_duplicates_are_refused_unless_the_entry_itself_repeats(self):
        body = "It is free. Later: it is free.\n"
        r = self.check(body, [], [self.v("it is free.", "unsupported")], unmapped=1)
        self.assertEqual(r["problems"], [])
        r = self.check(body.replace("Later: it", "Later: It"), [], [self.v("It is free.", "unsupported")], unmapped=1)
        self.assertIn("found 2 times", r["problems"][0])
        r = self.check("It is free.\n\nIt is free.\n", ["It is free."], [self.v("It is free.")])
        self.assertEqual((r["problems"], r["dup"]), ([], {"It is free."}))  # both share the verdict

    def test_nested_entries_belong_to_the_longest_t0010(self):
        entries = [T0010_CELL, T0010_FAQ, T0010_TWICE]
        r = self.check(T0010, entries, [self.v(T0010_FAQ), self.v(T0010_TWICE), self.v(T0010_CELL)])
        self.assertEqual(r["problems"], [])
        line = lambda sp: T0010[:sp[0]].count("\n") + 1  # noqa: E731
        self.assertEqual([line(sp) for sp in r["spans"][T0010_CELL]], [5])  # body line 89: the cell only
        self.assertEqual(len(r["spans"][T0010_TWICE]), 2)  # body lines 93 and 109: one entry, written twice
        self.assertEqual(r["dup"], {T0010_TWICE})
        r = self.check(T0010, entries, [self.v(T0010_FAQ), self.v(T0010_TWICE)])  # the FAQ verdict covers no cell
        self.assertIn("no verdict for the claims-map entry %r" % T0010_CELL, " ".join(r["problems"]))

    def test_alt_and_label_entries_and_not_factual_needs_a_framing(self):
        body = "Shops open early.\n\n![The shop front at dawn](/img/a.png)\n\n| Form | Use |\n"
        entries = ["Shops open early.", "The shop front at dawn", "Form"]
        ok = [self.v("Shops open early."), self.v("The shop front at dawn", "not-factual"),
              self.v("Form", "not-factual")]
        self.assertEqual(self.check(body, entries, ok)["problems"], [])
        bad = [self.v("Shops open early.", "not-factual")] + ok[1:]
        self.assertIn("without a framing", " ".join(self.check(body, entries, bad, supported=0)["problems"]))
        framed = self.check(body, entries, bad, [{"framing": "the example below", "covers": ["Shops open early."]}],
                            supported=0)
        self.assertEqual(framed["problems"], [])
        r = self.check(body, entries, [self.v("The shop front at dawn", "unsupported")] + ok[:1] + ok[2:])
        self.assertEqual(r["problems"], [])  # an alt is judged like a sentence

    def test_counts_follow_the_verdicts(self):
        body = "One fact. Two fact. Three fact.\n"
        vs = [self.v("One fact."), self.v("Two fact.", "unsupported"), self.v("Three fact.", "unsupported")]
        self.assertEqual(self.check(body, ["One fact.", "Two fact."], vs, unmapped=1)["problems"], [])
        for k, n in (("supported", 2), ("unsupported", 1), ("unmapped", 0), ("contradicted", 1)):
            r = self.check(body, ["One fact.", "Two fact."], [dict(x) for x in vs], **dict({"unmapped": 1}, **{k: n}))
            self.assertIn("counts do not follow", " ".join(r["problems"]), k)
        r = self.check(body, ["One fact."], [self.v("One fact."), self.v("Two fact.", "contradicted")])
        self.assertIn("an unmapped factual text is `unsupported`", " ".join(r["problems"]))
        rec = {"verdicts": [self.v("One fact.", "unsupported")],
               "counts": {"supported": 0, "unsupported": 1, "contradicted": 0, "unmapped": 0},
               "unsupported_sentences": []}
        text = "---\na: b\n---\n" + body
        r = store.coverage(text, store._body_start(text), ["One fact."], rec)
        self.assertIn("needs its one-line `why`", " ".join(r["problems"]))
        self.assertIn("unsupported_sentences must be exactly", " ".join(r["problems"]))


class NarrowingTests(unittest.TestCase):
    def test_whole_tokens_only_and_never_a_digit_markup_quote_quotation_or_negation(self):
        self.assertEqual(store._narrowing("Luffy is the 주인공 of it.", "Luffy is the of it."), (["주인공"], None))
        self.assertEqual(store._narrowing("A big\ncat sat.", "A\ncat sat.")[0], ["big"])
        for orig, new, why in (
                ("It took 3 days.", "It took days.", "digit"),
                ("See the **bold** part.", "See the part.", "markup"),
                ("See [the] part.", "See part.", "markup"),
                ("He said 'yes' today.", "He said today.", "quote"),
                ("He said “a big win” today.", "He said “a win” today.", "inside a quotation"),
                ("그는 「정말 큰 승리」라고 했다.", "그는 「정말 승리」라고 했다.", "inside a quotation"),
                ("It does not hurt.", "It does hurt.", "negation"),
                ("It isn’t cheap.", "It cheap.", "quote"),
                ("It cannot fail.", "It fail.", "negation"),
                ("Do it, not later.", "Do it, later.", "negation"),
                ("《원피스》 주인공 루피.", "주인공 루피.", "quote"),
                ("그는 ‘아주 큰 승리’라 했다.", "그는 ‘아주 승리’라 했다.", "inside a quotation"),
                ("먹지 말고 기다리세요.", "먹지 기다리세요.", "negation"),
                ("그것은 못했다 정말.", "그것은 정말.", "negation"),
                ("이 약은 안 써도 됩니다.", "이 약은 써도 됩니다.", "negation"),
                ("Never mix them.", "mix them.", "negation"),
                ("It helps a lot.", "It helps a", "sentence end"),
                ("It helps a lot.", "It helps a lot!", "whole words"),
                ("It helps a lot.", "It  a lot.", "whole words"),   # the seam keeps one space
                ("It helps\nbeginners a lot.", "It beginners a lot.", "line break")):
            removed, reason = store._narrowing(orig, new)
            self.assertIsNone(removed, (orig, new))
            self.assertIn(why, reason, (orig, new))
        for orig, new in (("안내 문구를 읽습니다.", "문구를 읽습니다."), ("매우 안전한 길입니다.", "매우 길입니다."),
                          ("주말 수업이 있습니다.", "수업이 있습니다."), ("말하는 연습을 합니다.", "연습을 합니다."),
                          ("I know it well.", "I it well."), ("Take a note today.", "Take a today."),
                          ("Call whenever you like.", "Call you like."), ("말고 다른 것도 됩니다.", "다른 것도 됩니다.")):
            self.assertIsNotNone(store._narrowing(orig, new)[0], (orig, new))  # not negations


class NarrowTrimTests(Flow):
    """15 D2: up to three uncounted trims, narrowing, revert."""
    EXTRA = "\nListening daily surely helps beginners. The app does not read examples aloud. Tests run fast.\n"
    S1 = "Listening daily surely helps beginners."
    N1 = "Listening daily helps beginners."
    S2 = "The app does not read examples aloud."
    S3 = "Tests run fast."
    to_verify_gap = TrimTests.to_verify_gap
    body = TrimTests.body
    finish_with = TrimTests.finish_with

    def gap(self, tid, slug, listed):
        write_machine(self, tid, "verify.json", {"unsupported_sentences": listed}, slug)

    def wfile(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as f:
            return f.read()

    def test_a_narrowing_is_checked_excluded_and_accepted_by_consent(self):
        tid, slug = self.to_verify_gap(ver={"unsupported_sentences": [self.S1, self.S2]})
        out, _ = self.hrd("trim", "--topic", tid, "--begin")
        self.assertEqual(out["may_narrow"], [self.S1, self.S2])
        body = self.body(slug)
        _, p = self.finish_with(tid, slug, body.replace(" not read", " read"))
        self.assertIn("negation", p.stderr)
        _, p = self.finish_with(tid, slug, body.replace("helps beginners.", "helps."))
        self.assertIn("changed beyond", p.stderr)  # a whole token, but its sentence end goes with it
        self.write(".claude/herald/work/%s/claims-map.json" % tid,
                   json.dumps({"sentences": [{"text": self.N1, "claims": ["C1"]}]}))
        out, _ = self.finish_with(tid, slug, body.replace(" surely", "").replace(" " + self.S2, ""))
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["removed"], [self.S2])
        self.assertEqual([(n["before"], n["after"], n["removed"]) for n in out["narrowed"]],
                         [(self.S1, self.N1, ["surely"])])
        reasons = self.hrd("auto-exclusion", "--topic", tid)[0]
        self.assertTrue({"trimmed", "narrowed"} <= set(reasons["blocking"]))
        consent = self.hrd("auto-exclusion", "--topic", tid, "--consent")[0]
        self.assertFalse({"trimmed", "narrowed"} & set(consent["blocking"]))
        self.write(".claude/herald/work/%s/verify.json" % tid, json.dumps(
            dict(VER_PASS, body_hash=worktree_hash(self.root, self.cfg, slug))))  # made before 0.24.0
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertIn("no `verdicts` list", p.stderr)
        write_machine(self, tid, "verify.json", {"verdicts": [
            {"text": self.N1, "verdict": "supported", "claims": ["C1"]}],
            "counts": {"supported": 1, "unsupported": 0, "contradicted": 0, "unmapped": 0}}, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")

    def test_the_claims_map_follows_a_narrowing_and_a_deletion(self):
        tid, slug = self.to_verify_gap(ver={"unsupported_sentences": [self.S1]})
        cm = {"sentences": [{"text": t, "claims": ["C1"]} for t in (self.S1, self.S2, self.S3)]}
        self.write(".claude/herald/work/%s/claims-map.json" % tid, json.dumps(cm))
        write_machine(self, tid, "verify.json", {"verdicts": [
            {"text": self.S1, "verdict": "unsupported", "claims": ["C1"], "why": "C1 says no degree"},
            {"text": self.S2, "verdict": "unsupported", "claims": ["C1"], "why": "C1 is silent"},
            {"text": self.S3, "verdict": "supported", "claims": ["C1"]}],
            "counts": {"supported": 1, "unsupported": 2, "contradicted": 0, "unmapped": 0},
            "unsupported_sentences": [self.S1, self.S2]}, slug)
        self.hrd("trim", "--topic", tid, "--begin")
        self.finish_with(tid, slug, self.body(slug).replace(" surely", "").replace(" " + self.S2, ""))  # map untouched
        texts = [e["text"] for e in json.loads(self.wfile(".claude/herald/work/%s/claims-map.json" % tid))["sentences"]]
        self.assertEqual(texts, [self.N1, self.S3])
        from hrdlib.hashing import file_hash
        st = store.load_state(self.root, tid)
        self.assertEqual(st["stages"]["draft"]["outputs"]["claims-map.json"],
                         file_hash(self.root, store.work_rel(tid, "claims-map.json")))

    def test_who_may_narrow(self):
        self.EXTRA = "\n## Setup. Run it fast now.\n\n- Item big one.\n\nSee it (big aside) here.\n"
        tid, _ = self.to_verify_gap(ver={"unsupported_sentences": ["Run it fast now.", "Item big one.", "(big aside)"]})
        out, _ = self.hrd("trim", "--topic", tid, "--begin")
        self.assertEqual(out["may_narrow"], ["Item big one."])  # not a heading's sentence, not an aside

    def test_three_trims_counting_aborted_and_reverted_at_exhaustion(self):
        tid, slug = self.to_verify_gap(ver={"unsupported_sentences": [self.S1, self.S2]})
        st = store.load_state(self.root, tid)
        st["loopbacks"] = 3  # the shared loopbacks are spent: a trim is still eligible
        store.save_state(self.root, tid, st)
        pre_out = dict(st["stages"]["draft"]["outputs"])
        pre_crit = st["stages"]["critique"]["body_hash"]
        self.hrd("trim", "--topic", tid, "--begin")
        self.hrd("trim", "--topic", tid, "--abort")  # 1: aborted
        self.gap(tid, slug, [self.S1])  # a new verify result on the same body: a new gap
        pre_ver = self.wfile(".claude/herald/work/%s/verify.json" % tid)
        base = worktree_hash(self.root, self.cfg, slug)
        self.hrd("trim", "--topic", tid, "--begin")
        self.write(".claude/herald/work/%s/claims-map.json" % tid,
                   json.dumps({"sentences": [{"text": self.N1, "claims": ["C1"]}]}))
        self.finish_with(tid, slug, self.body(slug).replace(" surely", ""))
        self.assertEqual(store.load_state(self.root, tid)["trims"][-1]["status"], "done")
        _, p = self.hrd("trim", "--topic", tid, "--revert", check=False)
        self.assertIn("run verify first", p.stderr)  # the re-verify has not run
        self.gap(tid, slug, [self.S2])
        _, p = self.hrd("trim", "--topic", tid, "--revert", check=False)
        self.assertIn("no narrowed text is contradicted", p.stderr)
        self.write(".claude/herald/work/%s/verify.md" % tid, "re-verify: N1 contradicted")
        write_machine(self, tid, "verify.json", {
            "verdicts": [{"text": self.N1, "verdict": "contradicted", "claims": ["C1"], "why": "C1 says only adults"}],
            "counts": {"supported": 0, "unsupported": 0, "contradicted": 1, "unmapped": 0},
            "unsupported_sentences": []}, slug)
        out, _ = self.hrd("trim", "--topic", tid, "--revert")  # 2: reverted
        self.assertTrue(out["restored"])
        st = store.load_state(self.root, tid)
        self.assertEqual(worktree_hash(self.root, self.cfg, slug), base)
        self.assertEqual(self.wfile(".claude/herald/work/%s/verify.json" % tid), pre_ver)
        self.assertEqual(self.wfile(".claude/herald/work/%s/verify.md" % tid), "two unsupported")
        self.assertEqual(self.wfile(".claude/herald/work/%s/claims-map.json" % tid), "{}")
        self.assertEqual((st["stages"]["draft"]["outputs"], st["stages"]["critique"]["body_hash"]), (pre_out, pre_crit))
        _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
        self.assertIn("already tried on this verify result (reverted)", p.stderr)
        self.gap(tid, slug, [self.S3])
        self.hrd("trim", "--topic", tid, "--begin")
        self.finish_with(tid, slug, self.body(slug).replace(" " + self.S3, ""))  # 3: done
        self.gap(tid, slug, [self.S2])
        _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
        self.assertIn("trimmed 3 times already (aborted, reverted, done)", p.stderr)
        self.assertEqual(store.load_state(self.root, tid)["loopbacks"], 3)  # trims never count

    def test_a_narrowed_span_is_never_narrowed_again_and_only_the_last_done_trim_reverts(self):
        tid, slug = self.to_verify_gap(ver={"unsupported_sentences": [self.S1]})
        self.hrd("trim", "--topic", tid, "--begin")
        self.finish_with(tid, slug, self.body(slug).replace(" surely", ""))
        self.gap(tid, slug, [self.N1])
        out, _ = self.hrd("trim", "--topic", tid, "--begin")
        self.assertEqual(out["may_narrow"], [])  # narrowed once: delete or map only
        self.hrd("trim", "--topic", tid, "--abort")
        write_machine(self, tid, "verify.json", {
            "verdicts": [{"text": self.N1, "verdict": "contradicted", "claims": [], "why": "broadened"}],
            "counts": {"supported": 0, "unsupported": 0, "contradicted": 1, "unmapped": 0}}, slug)
        _, p = self.hrd("trim", "--topic", tid, "--revert", check=False)
        self.assertIn("last trim: aborted", p.stderr)  # only the last trim is reverted

    def test_revert_force_when_the_snapshot_is_lost(self):
        import shutil
        tid, slug = self.to_verify_gap(ver={"unsupported_sentences": [self.S1]})
        self.hrd("trim", "--topic", tid, "--begin")
        self.finish_with(tid, slug, self.body(slug).replace(" surely", ""))
        write_machine(self, tid, "verify.json", {
            "verdicts": [{"text": self.N1, "verdict": "contradicted", "claims": [], "why": "broadened"}],
            "counts": {"supported": 0, "unsupported": 0, "contradicted": 1, "unmapped": 0}}, slug)
        shutil.rmtree(os.path.join(self.root, ".claude/herald/memory/trim", tid))
        _, p = self.hrd("trim", "--topic", tid, "--revert", check=False)
        self.assertIn("--revert --force", p.stderr)
        _, p = self.hrd("trim", "--topic", tid, "--finish", "--force", check=False)
        self.assertIn("--force goes with --abort or --revert", p.stderr)
        out, _ = self.hrd("trim", "--topic", tid, "--revert", "--force")
        self.assertEqual((out["restored"], out["hold"], out["trim"]["status"]), (False, "needs-human", "reverted"))

    def test_no_narrowing_in_a_language_written_without_spaces(self):
        cfg = json.loads(self.wfile(".claude/herald/config.json"))
        self.write(".claude/herald/config.json", json.dumps(dict(cfg, language="ja")))
        self.commit("ja")
        sh(self.root, "git", "push", "-q", "origin", "main")  # the herald branch forks from origin
        tid, slug = self.to_verify_gap(ver={"unsupported_sentences": [self.S1]})
        out, _ = self.hrd("trim", "--topic", tid, "--begin")
        self.assertEqual(out["may_narrow"], [])
        _, p = self.finish_with(tid, slug, self.body(slug).replace(" surely", ""))
        self.assertIn("changed beyond", p.stderr)

    def test_coverage_gates_verify_pass_and_loopback_and_old_trim_dicts_still_exclude(self):
        tid, slug = self.run_flow()
        self.write(".claude/herald/work/%s/verify.json" % tid, json.dumps(
            dict(VER_PASS, body_hash=worktree_hash(self.root, self.cfg, slug))))  # made before 0.24.0
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "verify", check=False)
        self.assertIn("no `verdicts` list", p.stderr)
        self.hrd("loopback", "--topic", tid, "--human")  # a human's loopback is not refused
        st = store.load_state(self.root, tid)
        st.pop("trims", None)  # a state written before 0.24.0
        st["trim"] = {"status": "done", "base_hash": "sha256:a", "hash": "sha256:b", "removed": ["x"]}
        self.assertEqual(store.auto_exclusion({}, st), ["trimmed"])
        st["trim"]["narrowed"] = [{"before": "a b.", "after": "a."}]
        self.assertEqual(store.auto_exclusion({}, st), ["narrowed", "trimmed"])
        store.save_state(self.root, tid, st)
        self.assertIn("narrowed", self.hrd("auto-exclusion", "--topic", tid)[0]["reasons"])
        sh(self.root, "git", "add", "-A", ".claude/herald/work/%s" % tid)
        sh(self.root, "git", "commit", "-qm", "a PR head written before 0.24.0")
        reasons = store.exclusion_reasons(self.root, self.cfg, tid, rev="HEAD")
        self.assertTrue({"trimmed", "narrowed"} <= set(reasons), reasons)
        self.assertEqual(store.trims_of(st)[0]["status"], "done")


class MapBoundTests(Flow):
    """Review 2: `unplaced` is bounded at draft (max(3, 10%)), a warning at verify; a sentence written
    once plainly and once with markup is repeated, not single; the trim's map step and dup check
    work in normalised space."""

    def to_draft(self, tid="t0001", slug="new-post"):
        store.save_topics(self.root, {"version": 1, "topics": [{"id": tid, "title": "T", "state": "queued",
                                                                 "history": [], "reverted_by": []}]})
        self.commit("topics")
        self.hrd("begin", "--topic", tid)
        self.write(".claude/herald/work/%s/brief.md" % tid, "brief")
        self.hrd("branch", "--topic", tid, "--slug", slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "brief")
        self.write(".claude/herald/work/%s/research.md" % tid, "C1. source")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "research")
        self.article(slug)
        return tid, slug

    def cmap(self, tid, texts):
        self.write(".claude/herald/work/%s/claims-map.json" % tid,
                   json.dumps({"sentences": [{"text": t, "claims": ["C1"]} for t in texts]}))

    def test_draft_refuses_an_unmatched_map_and_verify_only_warns(self):
        tid, slug = self.to_draft()
        body = "Body text for new-post."
        self.cmap(tid, ["Gone %d." % i for i in range(4)] + [body])
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "draft", check=False)
        self.assertIn("4 of 5 entries with no place", p.stderr)
        self.assertIn("copy each map text from the article", p.stderr)
        self.cmap(tid, ["Gone %d." % i for i in range(3)] + [body])
        out, _ = self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        self.assertEqual(len(out["map_warnings"]), 3)  # within the bound: the writer's to fix, no refusal
        self.write(".claude/herald/work/%s/critique.md" % tid, "ok")
        write_machine(self, tid, "critique.json", CRIT_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        self.cmap(tid, ["Gone %d." % i for i in range(4)] + [body])  # a later map change past the bound
        from hrdlib.hashing import file_hash
        st = store.load_state(self.root, tid)
        st["stages"]["draft"]["outputs"]["claims-map.json"] = file_hash(self.root, store.work_rel(tid, "claims-map.json"))
        store.save_state(self.root, tid, st)
        self.write(".claude/herald/work/%s/verify.md" % tid, "ok")
        write_machine(self, tid, "verify.json", {"verdicts": [{"text": body, "verdict": "supported", "claims": ["C1"]}],
                                                 "counts": {"supported": 1, "unsupported": 0, "contradicted": 0,
                                                            "unmapped": 0}}, slug)
        out, _ = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        self.assertEqual(len(out["unplaced"]), 4)
        self.assertIn("4 of 5", out["unplaced_warning"])
        self.assertEqual(store.unplaced_bound(5), 3)
        self.assertEqual(store.unplaced_bound(132), 13)

    def test_nested_entries_do_not_count_toward_the_bound(self):
        # review 3 m1: a table cell copied into a sentence has a place in the article — only
        # entries found nowhere count toward the draft bound
        tid, slug = self.to_draft()
        body = "Body text for new-post."
        self.cmap(tid, ["Body", "text", "for", "new-post", body])
        out, _ = self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        self.assertEqual(out.get("map_warnings") or [], [])

    def test_plain_and_marked_up_copies_are_repeated(self):
        body = "---\nt: x\n---\nIt is **free** today. Later: It is free today.\n"
        lo = store._body_start(body)
        self.assertEqual(len(store._Body(body, lo).find("It is free today.")), 2)
        rec = {"verdicts": [{"text": "It is free today.", "verdict": "unsupported", "claims": [], "why": "x"}],
               "counts": {"supported": 0, "unsupported": 1, "contradicted": 0, "unmapped": 1},
               "unsupported_sentences": ["It is free today."]}
        self.assertIn("found 2 times", " ".join(store.coverage(body, lo, [], rec)["problems"]))
        r = store.coverage(body, lo, ["It is free today."], dict(rec, counts=dict(rec["counts"], unmapped=0)))
        self.assertEqual((r["problems"], r["dup"]), ([], {"It is free today."}))

    def test_trim_refuses_a_repeated_entry_and_keeps_a_normalised_map_in_step(self):
        tid, slug = self.to_draft()
        self.write("src/content/blog/%s.md" % slug, self.body_text(slug) +
                   "\nIt is **free** today. It is free today.\n")
        self.cmap(tid, [])
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        self.write(".claude/herald/work/%s/critique.md" % tid, "ok")
        write_machine(self, tid, "critique.json", CRIT_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")
        self.cmap(tid, ["It is free today."])
        write_machine(self, tid, "verify.json", {
            "verdicts": [{"text": "It is free today.", "verdict": "unsupported", "claims": ["C1"], "why": "x"}],
            "counts": {"supported": 0, "unsupported": 1, "contradicted": 0, "unmapped": 0},
            "unsupported_sentences": ["It is free today."]}, slug)
        _, p = self.hrd("trim", "--topic", tid, "--begin", check=False)
        self.assertIn("repeated in the article", p.stderr)
        # the map step in normalised space: a t0011-style entry written without the ruby
        self.write(".claude/herald/work/t9/claims-map.json", json.dumps({"sentences": [
            {"text": "「 紅葉 ( もみじ ) 」는 정말 아름답습니다.", "claims": ["C1"]},
            {"text": "「 紅葉 ( もみじ ) 」는 가을에 핍니다.", "claims": ["C1"]},
            {"text": "Kept.", "claims": ["C1"]}]}))
        ruby = "「<ruby>紅葉<rp>(</rp><rt>もみじ</rt><rp>)</rp></ruby>」는"
        store._trim_map_in_step(self.root, "t9", [ruby + " 가을에 핍니다."],
                                [{"before": ruby + " 정말 아름답습니다.", "after": ruby + " 아름답습니다."}])
        with open(os.path.join(self.root, ".claude/herald/work/t9/claims-map.json"), encoding="utf-8") as f:
            texts = [e["text"] for e in json.load(f)["sentences"]]
        self.assertEqual(texts, ["「 紅葉 ( もみじ ) 」는 아름답습니다.", "Kept."])

    def body_text(self, slug):
        with open(os.path.join(self.root, "src/content/blog/%s.md" % slug), encoding="utf-8") as f:
            return f.read()


class ConsentTests(Flow):
    def pin(self, tid, crit):
        """A critique.json as stage pass would have recorded it."""
        from hrdlib.hashing import file_hash
        self.write(".claude/herald/work/%s/critique.json" % tid, json.dumps(crit))
        st = store.load_state(self.root, tid)
        st["stages"]["critique"]["outputs"]["critique.json"] = file_hash(self.root, store.work_rel(tid, "critique.json"))
        st["stages"]["critique"]["blobs"]["critique.json"] = store._git_blob(self.root, None, store.work_rel(tid, "critique.json"))
        store.save_state(self.root, tid, st)

    def test_framings_exclude_unless_consented(self):
        tid, slug = self.run_flow()
        self.pin(tid, {"final_round": {"verdict": "PASS", "audit_round": 1}})
        self.assertEqual(self.hrd("auto-exclusion", "--topic", tid)[0]["reasons"], [])
        ver = json.loads(json.dumps(VER_PASS))
        ver["framings"] = [{"framing": "the schedule below is an example", "covers": ["Week 1: 5 hours."]}]
        write_machine(self, tid, "verify.json", ver, slug)
        st = store.load_state(self.root, tid)  # as verify's stage pass records it
        st["stages"]["verify"]["blobs"] = {"verify.json": store._git_blob(self.root, None, store.work_rel(tid, "verify.json"))}
        store.save_state(self.root, tid, st)
        out, _ = self.hrd("auto-exclusion", "--topic", tid)
        self.assertEqual(out["blocking"], ["framed"])
        self.assertEqual(self.hrd("auto-exclusion", "--topic", tid, "--consent")[0]["blocking"], [])
        self.assertEqual(store.exclusion_reasons(self.root, self.cfg, tid, None), ["framed"])
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-qm", "work")
        self.assertIn("framed", store.exclusion_reasons(self.root, self.cfg, tid, "HEAD"))  # PR-head path
        ver["framings"] = []
        write_machine(self, tid, "verify.json", ver, slug)  # dropped after verify passed
        self.assertEqual(self.hrd("auto-exclusion", "--topic", tid, "--consent")[0]["blocking"], ["verify-changed"])
        os.remove(os.path.join(self.root, store.work_rel(tid, "verify.json")))
        self.assertIn("missing-verify", self.hrd("auto-exclusion", "--topic", tid, "--consent")[0]["blocking"])

    def test_consent_accepts_logged_decisions_but_not_blocking_ones(self):
        tid, slug = self.run_flow()
        crit = {"final_round": {"verdict": "PASS", "audit_round": 2, "audit": {"major": 1},
                                "dismissed": {"major": 1}},
                "decision_log": [{"kind": "dismissal", "note": "R1-1"}]}
        self.pin(tid, crit)
        out, _ = self.hrd("auto-exclusion", "--topic", tid)
        self.assertEqual(out["blocking"], out["reasons"])
        out, _ = self.hrd("auto-exclusion", "--topic", tid, "--consent")
        self.assertEqual(out["blocking"], [])
        self.assertEqual(sorted(out["accepted"]), ["audit-dismissed", "decision:dismissal"])
        deferred = dict(crit, audit_log=[{"round": 1, "id": "R1-1", "severity": "BLOCKER", "outcome": "deferred"}])
        self.pin(tid, deferred)
        self.assertIn("audit-log:deferred-blocker", self.hrd("auto-exclusion", "--topic", tid, "--consent")[0]["blocking"])
        self.assertTrue(any("logged deferred" in x for x in store.audit_log_problems(deferred, 2)))
        human = dict(crit, final_round=dict(crit["final_round"], audit_round=3, audit={"blocker": 1},
                                            dismissed={"blocker": 1}),
                     audit_log=[{"round": 3, "id": "R3-1", "severity": "BLOCKER", "outcome": "dismissed"}],
                     decision_log=[{"kind": "human", "id": "R3-1", "note": "human: ok"}])
        self.pin(tid, human)
        self.assertEqual(self.hrd("auto-exclusion", "--topic", tid, "--consent")[0]["blocking"], [])
        for change, reason in ((dict(crit["final_round"], audit_round=4), "audit-skipped"),
                               (dict(crit["final_round"], audit={"blocker": 1}, dismissed={"blocker": 1}),
                                "audit-dismissed:blocker")):
            self.pin(tid, dict(crit, final_round=change))
            out, _ = self.hrd("auto-exclusion", "--topic", tid, "--consent")
            self.assertEqual(out["blocking"], [reason])
        self.pin(tid, crit)
        self.write(".claude/herald/work/%s/critique.json" % tid, json.dumps(dict(crit, decision_log=[])))
        out, _ = self.hrd("auto-exclusion", "--topic", tid, "--consent")
        self.assertEqual(out["blocking"], ["critique-changed"])  # edited after critique passed
        self.pin(tid, crit)
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "wip")
        out, _ = self.hrd("auto-exclusion", "--topic", tid, "--rev", "HEAD", "--consent")
        self.assertIn("images", out["accepted"])  # the branch adds the article's images
        sh(self.root, "git", "switch", "-q", "main")
        out, _ = self.hrd("auto-exclusion", "--topic", tid, "--consent")
        self.assertEqual(out["blocking"], ["missing-critique-or-state"])  # never eligible unread

    def test_the_stamp_records_what_code_found_accepted(self):
        tid, slug = self.run_flow()
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "wip")
        branch = sh(self.root, "git", "branch", "--show-current").strip()
        sh(self.root, "git", "switch", "-q", "main")
        _, p = self.hrd("auto-merged", "--topic", tid, "--pr", "7", "--rev", branch, "--sha",
                        sh(self.root, "git", "rev-parse", branch).strip(), check=False)
        self.assertIn("excluded (images)", p.stderr)  # without consent images block
        _, p = self.hrd("auto-merged", "--topic", tid, "--pr", "7", "--consent", check=False)
        self.assertIn("needs --rev", p.stderr)
        sha = sh(self.root, "git", "rev-parse", branch).strip()
        out, _ = self.hrd("auto-merged", "--topic", tid, "--pr", "7", "--rev", branch, "--sha", sha, "--consent")
        self.assertEqual(out["accepted"], ["images"])
        rec, _ = self.hrd("record-published", "--topic", tid, "--slug", slug, "--pr", "7")
        self.assertFalse(rec["human_reviewed"])
        pub = store.load_published(self.root)
        self.assertEqual(store.find_article(pub, slug)["auto_accepted"], ["images"])


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
        gap = {"counts": {"supported": 0, "unsupported": 1, "contradicted": 0, "unmapped": 1},
               "unsupported_sentences": ["Body text for new-post."]}
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


    def test_reader_loopback_once_and_hints_written_by_draft_pass(self):
        tid, slug = self.run_flow()
        hints = os.path.join(self.root, ".claude/herald/memory/prose/%s.json" % tid)
        self.assertTrue(os.path.exists(hints))  # written by `stage pass --stage draft`
        with open(hints) as f:
            self.assertFalse(json.load(f)["reader_round_used"])
        reader = os.path.join(self.root, ".claude/herald/work/%s/reader.json" % tid)

        def say(blockers, body_hash=None):
            with open(reader, "w") as f:
                json.dump({"round": 1, "blockers": blockers, "notes": [],
                           "body_hash": body_hash or worktree_hash(self.root, self.cfg, slug)}, f)

        say(["intro: hard to follow"], body_hash="sha256:other")  # about another body: ignored
        self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "depth")
        self.assertFalse(store.load_state(self.root, tid).get("reader_revise"))
        say(["intro: hard to follow"])
        self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "clarity")
        self.assertTrue(store.load_state(self.root, tid)["reader_revise"])
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "clarity", check=False)
        self.assertIn("send-back is used", p.stderr)
        self.assertEqual(store.load_state(self.root, tid)["loopbacks"], 2)  # the refusal counted nothing
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "verify", check=False)
        self.assertEqual(p.returncode, 0, p.stderr)  # only revise looks at reader.json
        sig = [json.loads(l) for l in open(os.path.join(self.root, ".claude/herald/signals.jsonl"))]
        self.assertEqual([r["data"].get("reader") for r in sig if r["kind"] == "revise-weakness"], [None, True])
        self.write("src/content/blog/%s.md" % slug, "no frontmatter at all")
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "draft", check=False)
        self.assertNotEqual(p.returncode, 0)  # a failing gate still refreshes the hints
        with open(hints) as f:
            saved = json.load(f)
        self.assertTrue(saved["reader_round_used"])
        self.assertEqual(saved["body_hash"], worktree_hash(self.root, self.cfg, slug))
        self.hrd("begin", "--topic", tid, "--force")
        self.assertFalse(os.path.exists(hints))

    def test_critique_pass_refuses_reader_blockers(self):
        tid, slug = self.run_flow()
        with open(os.path.join(self.root, ".claude/herald/work/%s/reader.json" % tid), "w") as f:
            json.dump({"round": 1, "blockers": ["intro: hard to follow"], "notes": [],
                       "body_hash": worktree_hash(self.root, self.cfg, slug)}, f)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", "--amend", check=False)
        self.assertIn("a PASS cannot carry them", p.stderr)
        with open(os.path.join(self.root, ".claude/herald/work/%s/reader.json" % tid), "w") as f:
            json.dump({"round": 1, "blockers": [], "notes": ["intro: hard to follow"],
                       "body_hash": worktree_hash(self.root, self.cfg, slug)}, f)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", "--amend")

    def test_reader_json_malformed_refused_and_other_causes_ignore_it(self):
        tid, slug = self.run_flow()
        path = os.path.join(self.root, ".claude/herald/work/%s/reader.json" % tid)
        cur = worktree_hash(self.root, self.cfg, slug)
        for bad in ('{"blockers": ["x"]}', "{not json", '{"blockers": "x", "body_hash": "%s"}' % cur):
            with open(path, "w") as f:
                f.write(bad)
            _, p = self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "clarity", check=False)
            self.assertIn("reader.json is malformed", p.stderr, bad)
            _, p = self.hrd("audit-round", "--topic", tid, check=False)
            self.assertIn("reader.json is malformed", p.stderr, bad)
        self.assertEqual(store.load_state(self.root, tid)["loopbacks"], 0)
        with open(path, "w") as f:
            json.dump({"round": 1, "blockers": ["intro"], "notes": [], "body_hash": cur}, f)
        _, p = self.hrd("audit-round", "--topic", tid, check=False)
        self.assertIn("a PASS cannot carry them", p.stderr)
        self.hrd("loopback", "--topic", tid, "--cause", "audit", "--theme", "policy")
        self.hrd("loopback", "--topic", tid, "--human")
        self.assertFalse(store.load_state(self.root, tid).get("reader_revise"))

    def test_pass_with_blockers_after_send_back_moves_them_to_notes(self):
        tid, slug = self.run_flow()
        path = os.path.join(self.root, ".claude/herald/work/%s/reader.json" % tid)
        cur = worktree_hash(self.root, self.cfg, slug)
        with open(path, "w") as f:
            json.dump({"round": 1, "blockers": ["intro"], "notes": [], "body_hash": cur}, f)
        self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "clarity")
        with open(path, "w") as f:
            json.dump({"round": 2, "blockers": ["intro"], "notes": [], "body_hash": cur}, f)
        _, p = self.hrd("audit-round", "--topic", tid, check=False)
        self.assertIn("the editor's PASS stands; no loopback", p.stderr)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", "--amend", check=False)
        self.assertIn("the editor's PASS stands", p.stderr)
        with open(path, "w") as f:
            f.write('{"blockers": ["x"]}')
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "critique", "--amend", check=False)
        self.assertIn("reader.json is malformed", p.stderr)
        with open(path, "w") as f:
            json.dump({"round": 2, "blockers": [], "notes": ["intro"], "body_hash": cur}, f)
        self.hrd("audit-round", "--topic", tid)
        self.assertEqual(store.load_state(self.root, tid)["loopbacks"], 1)

    def test_reader_round_used_once_loopbacks_are_spent(self):
        tid, slug = self.run_flow()
        for _ in range(2):  # the last loopback stays for accuracy and audit findings
            self.hrd("loopback", "--topic", tid, "--cause", "verify")
        path = os.path.join(self.root, ".claude/herald/work/%s/reader.json" % tid)
        with open(path, "w") as f:
            json.dump({"round": 4, "blockers": ["intro"], "notes": [],
                       "body_hash": worktree_hash(self.root, self.cfg, slug)}, f)
        _, p = self.hrd("audit-round", "--topic", tid, check=False)
        self.assertIn("the editor's PASS stands; no loopback", p.stderr)
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "revise", "--theme", "clarity", check=False)
        self.assertIn("loopback budget is spent", p.stderr)
        st = store.load_state(self.root, tid)
        self.assertEqual((st["loopbacks"], st.get("reader_revise")), (2, None))
        self.assertFalse(self.hrd("loopback", "--topic", tid, "--cause", "audit", "--theme", "accuracy")[0]["exhausted"])
        self.hrd("gate", "--topic", tid)
        with open(os.path.join(self.root, ".claude/herald/memory/prose/%s.json" % tid)) as f:
            self.assertTrue(json.load(f)["reader_round_used"])

    def test_gate_record_signals_once_per_loopback(self):
        tid, slug = self.run_flow()
        self.write("src/content/blog/%s.md" % slug, "no frontmatter at all")
        sigfile = os.path.join(self.root, ".claude/herald/signals.jsonl")

        def gate_failures():
            if not os.path.exists(sigfile):
                return []
            return [json.loads(l) for l in open(sigfile) if '"gate-failure"' in l]

        _, p = self.hrd("gate", "--topic", tid, check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(gate_failures(), [])  # the writer's own check records nothing
        self.hrd("gate", "--topic", tid, "--record", check=False)
        self.hrd("gate", "--topic", tid, "--record", check=False)
        self.assertEqual([r["data"]["stage"] for r in gate_failures()], ["critique"])

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
        # not string order: "0.9.0" sorts after "0.10.0" as text, yet the 0.10+ scripts are newer
        self.assertEqual(self.hrd("version", "--against", "0.9.0")[0]["relation"], "newer")
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
