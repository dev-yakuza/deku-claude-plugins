"""Stage 3 end to end (Q4): every stage-3 unit REAL — catalog, ladder, procedure, rules, acparse,
repoconfig (B1), facts, results, runner, session, store (C), leader (D), github, gitops, prbody (E) —
inside the REAL driver loop (B2): driver.Units() defaults, the fake claude for every role and leader
session, the fake gh executable, a bare remote, a temp repository and the real srt. No paid call.

  TB1  bug: reproduce → repro-red (overlay tree red twice, base green) → fix → runs → reviews →
       done-gate → PR with the reproduction table → create-followups
  TF4  a `followup` disposition → the op creates the Issue (marker line, labels), PATCHes the PR body,
       then the completion comment
  TF11 followups_dry_run (A4) → no Issue / comment / label write, the engine-local record, the PR line
  TR1  refactor: transform → verification-frozen → … → PR (a new test file passes)
"""

import json
import os
import unittest

from gxengine import driver, store
from tests import z_world as Z

SPECS = Z.SPECS
START = ["analyze", "ac-format", "plan"]


def steps_of(state):
    return {s["id"]: s["status"] for s in state["steps"]}


def events(log, name):
    return [l for l in log if l["event"] == name]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Base(unittest.TestCase):
    cfg_extra = None
    private = True

    def setUp(self):
        self.tmp = Z.new_tmp()
        self.addCleanup(Z.rmtree, self.tmp)
        self.w = Z.Z3World(self.tmp, cfg=Z.config3(self.cfg_extra), private=self.private)

    def out(self):
        return self.w.out.getvalue()

    def leader(self, what, structured, **over):
        return self.w.add(Z.leader_scenario(what, structured, **over))

    def role(self, step, **kw):
        return self.w.add(Z.role_scenario3(step, **kw))

    def bug_until_done_gate(self, audit=None):
        self.role("analyze")
        self.leader("plan-gate", Z.plan3("bug"))
        for st in Z.BUG_ROLE_STEPS:
            if st == "review-audit" and audit is not None:
                self.w.add(audit)
            else:
                self.role(st)

    def assert_all_done(self, st):
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        self.assertIsNone(st["stop"])

    def pr_body(self):
        prs = self.w.posts("/pulls")
        self.assertEqual(len(prs), 1)
        return prs[0]["body"]


class BugEndToEnd(Base):
    def test_tb1_bug_template_from_plan_to_pr(self):
        self.bug_until_done_gate()
        self.leader("done-gate", Z.approve3())
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assert_all_done(st)
        tpl = [s["id"] for s in Z.instructions.load_default_template("bug", stage=3)["steps"]]
        self.assertEqual([s["id"] for s in st["steps"]], START + tpl)
        self.assertEqual(st["revision"], 2)
        # E4: procedure.yaml carries the expanded test-code glob, not the placeholder
        proc = json.loads(self.w.wt_git("show", f"HEAD:{SPECS}/procedure.yaml"))
        rep = next(s for s in proc["steps"] if s["id"] == "reproduce")
        self.assertEqual(rep["outputs"], Z.TEST_CODE_GLOBS)
        self.assertEqual(proc["origin"]["template"], "bug")
        # repro-red (D1, D10): the overlay tree red twice, the recorded base green; exit_code = the condition
        fx = store.read_facts(self.w.paths(), "repro-red", 1)
        run = fx["run"]
        self.assertEqual(run["exit_code"], 0)
        self.assertNotEqual(run["head"]["exit_code"], 0)
        self.assertNotEqual(run["head_rerun"]["exit_code"], 0)
        self.assertEqual(run["base_run"]["exit_code"], 0)
        self.assertTrue(run["evidence"]["scope"]["ok"])
        self.assertEqual([f["path"] for f in run["evidence"]["overlay"]["files"]], ["tests/test_bug.py"])
        # the fix session got the red output (E8) and the blocking-discoveries file (E18)
        ind = self.w.paths().in_dir("fix", 1)
        ev = read(os.path.join(ind, "repro-evidence.md"))
        self.assertIn("must be red twice", ev)
        self.assertIn("AssertionError", ev)
        self.assertIn("None.", read(os.path.join(ind, "blocking-discoveries.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.w.paths().in_dir("review-tests", 1), "repro-evidence.md")))
        # the stage-3 instructions and result schemas reached the role sessions
        calls = self.w.claude_calls()
        argv = calls[0]["argv"]
        schema = json.loads(argv[argv.index("--json-schema") + 1])
        self.assertIn("irreversible", schema["properties"])
        # the PR body: the reproduction table from the facts (V16), then the op and the completion comment
        body = self.pr_body()
        self.assertIn("재현 증거", body)
        self.assertIn("`tests/test_bug.py`", body)
        log = self.w.log()
        self.assertEqual([e["data"]["source"] for e in events(log, "procedure-written")], ["start", "leader-plan"])
        kinds = [(e["event"], (e.get("data") or {}).get("kind")) for e in log]
        self.assertGreater(kinds.index(("comment", "done")), kinds.index(("pr-created", None)))
        self.assertEqual(st["github"]["is_private"], True)
        self.assertEqual(st["github"]["pr_number"], 77)
        self.assertEqual([(c["situation"], c["answer"]) for c in st["leader_calls"]],
                         [("plan-gate", "plan"), ("done-gate", "approve")])


DEBT = {"kind": "debt", "where": "src/legacy.py", "note": "duplicated parsing, see @bob", "blocks_current_ac": False}
BUG2 = {"kind": "bug", "where": "src/other.py", "note": "the same off-by-one as #61", "blocks_current_ac": False}
DISPOSITIONS = [{"id": "D1", "disposition": "followup", "title": "Merge the parsing of src/legacy.py", "duplicate_of": None},
                {"id": "D2", "disposition": "duplicate", "title": None, "duplicate_of": 61}]


def audit_with_discoveries():
    a = Z.role_scenario3("review-audit")
    a["structured_output"]["discoveries"] = [dict(DEBT), dict(BUG2)]
    return a


class FollowupsEndToEnd(Base):
    def test_tf4_tf6_followup_issue_duplicate_comment_pr_patch_then_done(self):
        self.bug_until_done_gate(audit=audit_with_discoveries())
        self.leader("done-gate", Z.approve3(discoveries=DISPOSITIONS))
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assert_all_done(st)
        # the done-gate leader saw the engine-numbered discoveries and the follow-up candidates (E19)
        with open(os.path.join(self.w.paths().attempt_dir("done-gate", 1), "in", "leader-input.json")) as f:
            inp = json.load(f)
        self.assertEqual([d["id"] for d in inp["done_gate"]["discoveries"]], ["D1", "D2"])
        self.assertEqual([c["number"] for c in inp["done_gate"]["followup_candidates"]], [61])
        # TF4: one new Issue — the marker is the first body line, labels the engine's + the type label
        issues = self.w.posts("repos/acme/app/issues")
        self.assertEqual(len(issues), 1)
        self.assertRegex(issues[0]["body"].split("\n", 1)[0], r"^<!-- guild:followup origin=42 key=D1:[0-9a-f]{8} -->$")
        self.assertEqual(issues[0]["labels"], ["guild:followup", "type:refactor"])
        self.assertNotIn("@bob", issues[0]["body"])                          # neutralised like every write
        self.assertEqual(self.w.posts("repos/acme/app/labels"), [])        # guild:followup exists already
        # TF6: the duplicate is one marker comment on the candidate Issue
        dup = self.w.posts("/issues/61/comments")
        self.assertEqual(len(dup), 1)
        self.assertTrue(dup[0]["body"].startswith("<!-- guild:followup origin=42 key=D2:"))
        self.assertEqual([(f["disposition"], f["number"], f["dry_run"]) for f in st["followups"]],
                         [("followup", 90, False), ("duplicate", 61, False)])
        # the PR body is PATCHed with what the op made, then the completion comment (E20)
        patch = self.w.posts("/pulls/77")
        self.assertEqual(len(patch), 1)
        self.assertIn("D1 · debt → 후속 이슈", patch[0]["body"])
        self.assertTrue(patch[0]["body"].rstrip().endswith("Closes #42"))
        log = self.w.log()
        order = [l["event"] + ":" + str((l.get("data") or {}).get("kind")) for l in log]
        self.assertLess(order.index("followup-created:debt"), order.index("comment:done"))
        self.assertLess(order.index("pr-updated:None"), order.index("comment:done"))

    def test_tf5_a_resumed_op_finds_the_issue_by_its_marker(self):
        self.bug_until_done_gate(audit=audit_with_discoveries())
        self.leader("done-gate", Z.approve3(discoveries=DISPOSITIONS[:1] + [
            {"id": "D2", "disposition": "ignore", "title": None, "duplicate_of": None}]))
        # the marker search already sees an Issue of this key: a crash after POST, before state.json
        orig = driver._followup_work

        def seen_on_github(env, step, attempt):
            items, index, answer = orig(env, step, attempt)
            key = items[0]["key"]
            rules = Z.gh_rules3(made=[dict(Z.FOLLOWUP_CANDIDATE, number=88,
                                           body=f"<!-- guild:followup origin=42 key={key} -->\nmade before the crash")])
            self.w.set_gh(rules)
            return items, index, answer
        from unittest import mock
        with mock.patch.object(driver, "_followup_work", seen_on_github):
            rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        self.assertEqual(self.w.posts("repos/acme/app/issues"), [])         # not created again
        self.assertEqual([f["number"] for f in self.w.state()["followups"]], [88])


class DryRunEndToEnd(Base):
    cfg_extra = {"followups_dry_run": True}

    def test_tf11_dry_run_writes_nothing_and_records_what_it_would(self):
        self.bug_until_done_gate(audit=audit_with_discoveries())
        self.leader("done-gate", Z.approve3(discoveries=DISPOSITIONS))
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assert_all_done(st)
        self.assertEqual(self.w.posts("repos/acme/app/issues"), [])
        self.assertEqual(self.w.posts("/issues/61/comments"), [])
        self.assertEqual(self.w.posts("repos/acme/app/labels"), [])
        with open(self.w.paths().followups_dry_run, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f.read().splitlines()]
        self.assertEqual([(r["action"], r["target"]) for r in rows], [("create-issue", None), ("comment", 61)])
        self.assertTrue(rows[0]["body"].startswith("<!-- guild:followup origin=42 key=D1:"))
        self.assertNotIn("@bob", rows[0]["body"])
        self.assertEqual([(f["dry_run"], f["number"]) for f in st["followups"]], [(True, None), (True, None)])
        self.assertIn("(dry-run — 만들지 않음)", self.pr_body())
        patch = self.w.posts("/pulls/77")
        self.assertIn("dry-run — 만들지 않음: 후속 이슈 1건 · 중복 댓글 1건", patch[0]["body"])


REVIEW = {"id": 6001, "user": {"login": "owner"}, "author_association": "OWNER", "state": "CHANGES_REQUESTED",
          "body": "Please keep x an int.", "submitted_at": "2026-11-25T01:02:03Z"}


class PrReviewEndToEnd(Base):
    def test_tp1_a_change_request_reruns_fix_and_updates_the_same_pr(self):
        self.bug_until_done_gate()
        self.leader("done-gate", Z.approve3())
        self.assertEqual(self.w.run(), driver.EXIT_OK, self.out())
        # a collaborator review on PR 77; the human runs `resume --pr-review`
        rules = Z.gh_rules3()
        rules["rules"][:0] = [
            {"args": ["api", f"repos/{Z.REPO}/pulls/77/reviews", "--paginate"], "json": [REVIEW]},
            {"args": ["api", f"repos/{Z.REPO}/pulls/77/comments", "--paginate"], "json": []},
            {"args": ["api", f"repos/{Z.REPO}/issues/77/comments", "--paginate"], "json": []}]
        self.w.set_gh(rules)
        self.leader("pr-review", Z.envelope("rerun", "real-defect", step="fix", note="Keep x an int (review 6001).",
                                            reviews=[{"id": "review:6001", "effect": "change-request"}]))
        fix = Z.role_scenario3("fix")
        fix["actions"] = [{"op": "write", "path": "src/app.py", "content": "x = int(2)\n"},
                          {"op": "git", "args": ["commit", "-qam", "fix: keep x an int"]}]
        self.w.add(fix)
        for st in ("review-design", "review-tests", "review-audit", "qa"):
            self.role(st)
        self.leader("done-gate again", Z.approve3())
        rc = self.w.run(answer={"pr_review": True})
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assert_all_done(st)
        # the real leader judged the pr-review stop with the review text and named the item (E31)
        call = next(c for c in st["leader_calls"] if c["situation"] == "pr-review")
        self.assertEqual((call["answer"], call["step"], call["counted"]), ("rerun", "fix", False))
        k = self.w.paths().leader_dir(call["k"])
        self.assertIn("Please keep x an int.", read(os.path.join(k, "in", "pr-review.md")))
        with open(os.path.join(k, "in", "leader-input.json")) as f:
            self.assertEqual([i["id"] for i in json.load(f)["pr_review"]["new"]], ["review:6001"])
        # the developer's rerun got the review file (Q4: in:pr-review.md of the developer step)
        self.assertIn("Please keep x an int.", read(os.path.join(self.w.paths().in_dir("fix", 2), "pr-review.md")))
        # the same PR: one POST (the first run), the body PATCHed after the rerun, a push to the same branch
        self.assertEqual(len(self.w.posts("/pulls")), 1)
        self.assertTrue(self.w.posts("/pulls/77"))
        self.assertEqual(st["pr_review"]["last_seen_ids"]["review"], 6001)
        head = self.w.wt_git("rev-parse", "HEAD").strip()
        self.assertEqual(self.w.repo.remote_head("gld/42"), head)
        self.assertIn("x = int(2)", self.w.wt_git("show", "HEAD:src/app.py"))


class RefactorEndToEnd(Base):
    def test_tr1_refactor_template_with_a_new_test_file(self):
        self.role("analyze", analysis=Z.analysis3("refactor", ac="x keeps its value under a clearer name."))
        self.leader("plan-gate", Z.plan3("refactor", note="A refactor without a safety net."))
        self.role("test-cases")
        self.role("design")
        tr = Z.role_scenario3("transform")
        tr["actions"] = [{"op": "write", "path": "src/app.py", "content": "VALUE = 1\nx = VALUE\n"},
                         {"op": "write", "path": "tests/test_value.py",
                          "content": "import sys\nsys.path.insert(0, 'src')\nimport app\nassert app.VALUE == app.x\n"},
                         {"op": "git", "args": ["add", "-A"]}, {"op": "git", "args": ["commit", "-q", "-m", "refactor"]}]
        self.w.add(tr)
        reviewed = ("src/app.py", "tests/test_value.py")
        for st, checks in (("review-design", ["structure-improved", "behavior-preserved"]),
                           ("review-tests", ["test-quality", "test-change-review"]), ("review-audit", ["diff-review"])):
            self.w.add(Z.role_scenario3(st, structured_output=Z.review_result3(checks, reviewed=reviewed)))
        qa = Z.role_scenario3("qa")
        qa["structured_output"]["reviewed"] = list(reviewed)
        self.w.add(qa)
        self.leader("done-gate", Z.approve3(evidence="tests/test_value.py"))
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assert_all_done(st)
        self.assertEqual(json.loads(self.w.wt_git("show", f"HEAD:{SPECS}/procedure.yaml"))["origin"]["template"],
                         "refactor")
        # TR1: verification-frozen passed — a NEW test file is no change of the verification (E9)
        run = store.read_facts(self.w.paths(), "verification-frozen", 1)["run"]
        self.assertEqual((run["exit_code"], run["paths_check"]["ok"]), (0, True))


class BlockedReproduceEndToEnd(Base):
    def test_tb5_blocked_reproduce_escalates_and_no_answer_passes_it(self):
        self.role("analyze")
        self.leader("plan-gate", Z.plan3("bug"))
        for st in ("test-cases", "diagnose"):
            self.role(st)
        rep = Z.role_scenario3("reproduce")
        rep["structured_output"] = dict(Z.work_result3(), status="blocked",
                                        blocked_by={"kind": "other", "note": "the bug does not show on this platform"})
        rep["actions"] = []
        self.w.add(rep)
        self.leader("blocked", Z.envelope("escalate", "needs-human-decision", note="Cannot reproduce here.",
                                          recommendation={"answer": "escalate", "step": None, "note": ""},
                                          session=None))
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"], st["stop"]["step"]),
                         ("needs_human", "blocked", "reproduce"))
        with open(os.path.join(self.w.paths().leader_dir(1), "in", "leader-input.json")) as f:
            allowed = json.load(f)["allowed"]["answers"]
        self.assertNotIn("plan", allowed)
        self.assertNotIn("approve", allowed)
        self.assertNotEqual(steps_of(st)["reproduce"], "done")


if __name__ == "__main__":
    unittest.main()
