"""Stage 2 — the done-gate, engine side (scope §2.2, D6, D7, D19, D26, V8: L16, L17, L19, L24).

The leader's own D6 checks (AC / discovery cover, approve-with-unmet / -include) are session
A's (test_leader). Here: the done-gate request facts, approve → PR, rerun → back_to and the
counter, the engine's own manual-AC ↔ checklist check before an approve is applied, the
mandatory-rule gate position and the §4.4-3 re-verification right before the done-gate and
again before the push (the done-gate writes nothing — D26).
"""

import json
import tempfile
import unittest

from gxengine import codes, driver, instructions, lifecycle, procedure as procmod, rules
from tests import c_world as W
from tests.test_leader_flow import LA, Stage2, events, steps_of

SPECS = W.SPECS


def approve(**kw):
    kw.setdefault("ac_verdicts", [{"ac": 1, "status": "met", "evidence": "x = 2"}])
    kw.setdefault("discoveries", [])
    return LA("approve", reason="acceptance-met", **kw)


def with_qa():
    steps = W.stage2_steps()
    steps.insert(3, {"id": "qa", "role": "qa", "inputs": ["in:review.diff"],
                     "outputs": ["docs/specs/{issue}/manual-test-checklist.md"], "checks": ["qa-acceptance"],
                     "on_fail": {"back_to": "implement", "max": 2}})
    return steps


class DoneGate(Stage2):
    def test_l16_approve_goes_to_the_pr_with_the_done_gate_facts(self):
        ld = self.leader({"done-gate": [approve()]})
        rc = self.run2(ld)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        st = self.w.state()
        self.assertEqual(st["github"]["pr_number"], 77)
        self.assertEqual(steps_of(st)["done-gate"], "done")
        call = [c for c in ld.calls if c["situation"] == "done-gate"][0]
        self.assertEqual((call["kind"], call["step"]), ("check", "done-gate"))
        req = call["request"]
        self.assertIn("x = 2", req.review_diff)                          # in:review.diff (base range)
        self.assertIn("Please show the quiz type.", req.issue_md)
        self.assertIsNone(req.templates)
        log = self.w.log()
        order = [l["event"] for l in log if l["event"] in ("leader-call", "pr-created")]
        self.assertEqual(order[-1], "pr-created")
        self.assertEqual(events(log, "answer")[-1]["data"]["answer"], "approve")

    def test_review_diff_of_the_done_gate_shows_a_binary_file_as_one_line(self):
        # Q4 × P5 (#1797): the done-gate's in:review.diff is the review steps' text (no `-a`)
        session = W.FakeSession(self.w, {"implement": [{"write": {"src/app.py": "x = 2\n",
                                                                  "assets/golden.png": "\x00PNG\x00\x01\x02"},
                                                        "commit": "feat: quiz type"}]})
        ld = self.leader({"done-gate": [approve()]})
        rc = self.run2(ld, session=session)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        req = [c for c in ld.calls if c["situation"] == "done-gate"][0]["request"]
        self.assertIn("Binary files", req.review_diff)
        self.assertIn("assets/golden.png", req.review_diff)
        self.assertNotIn("\x00", req.review_diff)
        self.assertIn("x = 2", req.review_diff)

    def test_l17_rerun_implement_goes_back_and_counts(self):
        ld = self.leader({"done-gate": [LA("rerun", step="implement", reason="real-defect", note="AC 1 unmet"),
                                        LA("rerun", step="review", reason="upstream-gap"), approve()]})
        rc = self.run2(ld)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        st = self.w.state()
        self.assertEqual(st["counters"]["done_rerun"], 2)
        backs = [l["data"]["target"] for l in events(self.w.log(), "back-to") if l["data"].get("answer") == "rerun"]
        self.assertEqual(backs, ["implement", "review"])
        self.assertEqual([c["situation"] for c in ld.calls].count("done-gate"), 3)
        # the third done-gate call sees both reruns used (the narrowing itself is session A's)
        third = [c for c in ld.calls if c["situation"] == "done-gate"][2]["request"]
        self.assertEqual(third.state["counters"]["done_rerun"], 2)
        self.assertIn("AC 1 unmet", lifecycle.read_leader_decision(self.w.paths()))
        self.assertEqual([w["data"]["revision"] for w in events(self.w.log(), "procedure-written")], [1, 2])

    def test_engine_refuses_an_approve_with_an_unreferenced_manual_ac(self):
        ld = self.leader({"done-gate": [approve(ac_verdicts=[{"ac": 1, "status": "manual", "evidence": "tap"}])]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["status"]), ("done-gate", "needs_human"))
        self.assertEqual(st["stop"]["leader_failed"], {"code": "output-format", "detail": "manual-not-in-checklist"})
        self.assertIsNone(st["github"]["pr_number"])
        self.assertFalse([c for c in self.w.gh_calls() if c["argv"][:4] == ["api", "-X", "POST", "repos/acme/app/pulls"]])

    def test_l19_a_red_run_never_reaches_the_done_gate(self):
        runner = W.FakeRunner({"test": [1]})
        ld = self.leader({"on-fail-exceeded": [LA("escalate", reason="real-defect", recommendation={
            "answer": "rerun", "step": "implement", "note": "fix"})]})
        self.assertEqual(self.run2(ld, runner=runner), driver.EXIT_NEEDS_HUMAN)
        self.assertNotIn("done-gate", [c["situation"] for c in ld.calls])
        self.assertEqual(steps_of(self.w.state())["done-gate"], "pending")


class DoneGateWithQa(Stage2):
    world_kw = {"steps": with_qa()}

    def test_manual_ac_referenced_by_the_checklist_is_approved(self):
        sess = W.FakeSession(self.w, {"qa": [{"write": {f"{SPECS}/manual-test-checklist.md": "- [ ] AC #1: tap\n"}}]})
        ld = self.leader({"done-gate": [approve(ac_verdicts=[{"ac": 1, "status": "manual", "evidence": "tap"}])]})
        self.assertEqual(self.run2(ld, session=sess), driver.EXIT_OK, self.w.out.getvalue())

    def test_v4_judgment_documents_alone_do_not_rerun_before_the_done_gate(self):
        sess = W.FakeSession(self.w, {"qa": [{"write": {f"{SPECS}/manual-test-checklist.md": "- [ ] tap\n"}}]})
        runner = W.FakeRunner()
        ld = self.leader({"done-gate": [approve()]})
        self.assertEqual(self.run2(ld, session=sess, runner=runner), driver.EXIT_OK, self.w.out.getvalue())
        rv = [l["step"] for l in events(self.w.log(), "reverify")]
        # the engine's revision-2 commit of procedure.yaml (after ac-format ran) is not exempt
        # from §4.4-3 (fail-closed, as in stage 1): the free plugin check ac-format runs again.
        self.assertEqual(rv, ["ac-format"])
        self.assertEqual(runner.calls.count("test"), 1)
        self.assertEqual([c["situation"] for c in ld.calls].count("done-gate"), 1)


class Reverify(Stage2):
    def test_v3_a_change_after_the_reviews_reruns_them_and_the_done_gate(self):
        # The push stops (remote diverged). A human commits a code change and answers rerun:
        # §4.4-3 resets test + review — and the done-gate, whose approval saw the old tree.
        self.w.repo.diverge_remote("gld/42", "other.txt", "x")
        runner = W.FakeRunner()
        ld = self.leader({"done-gate": [approve()]})
        self.assertEqual(self.run2(ld, runner=runner), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("remote-diverged", "pr"))
        self.w.repo.git("push", "-q", "origin", "--delete", "gld/42")
        self.w.repo.write("src/app.py", "x = 3\n", cwd=self.w.worktree)
        self.w.repo.commit("fix: by hand", cwd=self.w.worktree)
        rc = self.run2(ld, runner=runner, answer={"answer": "rerun"})
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        rv = [l["step"] for l in events(self.w.log(), "reverify")]
        for s in ("test", "review", "done-gate"):
            self.assertIn(s, rv)
        self.assertEqual(runner.calls.count("test"), 2)
        self.assertEqual([c["situation"] for c in ld.calls].count("done-gate"), 2)
        self.assertEqual(self.w.repo.remote_head("gld/42"), self.w.state()["last_head"])


class GatePosition(unittest.TestCase):
    """L24: a mandatory-rule gate goes right before the done-gate (§7, D19)."""

    def test_l24_gate_inserted_before_the_done_gate(self):
        cmds = list(W.config()["commands"])
        start = instructions.load_start_procedure(stage=2)
        p = procmod.attach_template(procmod.build_start(start, 42, cmds, stage=2), W.template(W.stage2_steps()),
                                    cmds, stage=2)
        from gxengine import store
        state = store.new_state(42, p.revision, p.step_ids, "a" * 40)
        cfg = W.config({"path_rules": [{"kind": "risk", "area": "auth", "gate": "security-review",
                                        "globs": ["src/**"]}]})
        from gxengine import repoconfig
        conf = repoconfig.RepoConfig.from_text(json.dumps(cfg))
        sup = rules.evaluate(p, state, conf, ["src/app.py"], 42, {"security"})
        self.assertFalse(sup.unfillable)
        new, _ = rules.apply(p, state, sup, commands=cmds, stage=2)
        ids = new.step_ids
        self.assertEqual(ids[-3:], ["security-review", "done-gate", "pr"])
        self.assertEqual([s["id"] for s in state["steps"]], ids)
        self.assertEqual(procmod.check(new, cmds, stage=2), [])
        # a stage-1 procedure (no done-gate): before create-pr, as in stage 1
        p1 = procmod.build(start, W.template(), 42, cmds)
        st1 = store.new_state(42, 1, p1.step_ids, "a" * 40)
        new1, _ = rules.apply(p1, st1, rules.evaluate(p1, st1, conf, ["src/app.py"], 42, {"security"}),
                              commands=cmds, stage=2)
        self.assertEqual(new1.step_ids[-2:], ["security-review", "pr"])
        self.assertEqual(codes.CheckKind.DONE_GATE.value, "done-gate")


if __name__ == "__main__":
    unittest.main()
