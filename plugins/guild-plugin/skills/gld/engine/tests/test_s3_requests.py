"""Stage 3 flow — role requests, the catalog cap, removal requests, gates (V6 · V2 wiring, session B2).

TC1–TC5, TC7–TC9, TC11, TX3, TX4 and the mandatory gate of TI5 from the driver's side. The
decisions themselves are catalog.evaluate_requests (session B1; tests/s3_world.FakeCatalog).
"""

import unittest

from gxengine import codes, driver, lifecycle, procedure as procmod, statemachine, store
from tests import s3_world as S


def ends(state):
    return [(q["op"], q["step"], q["outcome"], q["reason"]) for q in state.get("requests") or ()]


class Requests(S.Stage3):
    def design(self, *requests):
        return [{"write": {f"{S.SPECS}/skeleton.md": "s\n"}, "structured": S.result(requests=list(requests))}]

    def ids(self):
        return [s["id"] for s in self.procedure()["steps"]]

    def test_tc1_tc3_tc4_tc11_one_revision_for_all_requests_of_one_step(self):
        ld = self.leader()
        self.ok(self.run3(ld, session=self.sess(design=self.design(
            S.request("ux-review", note="a dialog"), S.request("i18n-review", trigger="user-facing-text"),
            S.request("ux-review"), S.request("infra-review", trigger="infra-change")))))
        st = self.state()
        self.assertEqual(ends(st), [("add", "ux-review", "applied", None),
                                    ("add", "i18n-review", "declined", "role-unavailable"),
                                    ("add", "ux-review", "noop", "already-present"),
                                    ("add", "infra-review", "applied", None)])
        self.assertEqual(st["revision"], 3)
        self.assertEqual(self.ids()[3:8], ["design", "implement", "test", "ux-review", "infra-review"])
        by = {s["id"]: s for s in self.procedure()["steps"]}
        self.assertEqual(by["ux-review"]["on_fail"], {"back_to": "implement", "max": 2})
        self.assertEqual([(a["step"], a["source"], a["from_step"], a["revision"]) for a in st["catalog_adds"]],
                         [("ux-review", "role-request", "design", 3), ("infra-review", "role-request", "design", 3)])
        self.assertEqual(S.steps_of(st)["ux-review"], "done")                        # it really ran
        # TX3: exactly one log line and one engine commit per revision
        written = self.log("procedure-written")
        self.assertEqual([(l["data"]["revision"], l["data"]["source"]) for l in written],
                         [(1, "start"), (2, "leader-plan"), (3, "role-request")])
        req = written[2]["data"]["requests"]
        self.assertEqual((req[0]["from_step"], req[0]["trigger"], req[0]["note"], req[0]["outcome"]),
                         ("design", "ui-change", "a dialog", "applied"))
        commits = {l["data"]["sha"] for l in self.log("commit") if f"{S.SPECS}/procedure.yaml" in (l["data"].get("paths") or ())}
        self.assertEqual(commits, {l["data"]["commit"] for l in written})
        self.assertEqual(len(commits), 3)
        line = self.log("request")[0]
        self.assertEqual((line["who"], line["step"], line["attempt"], line["trigger"]),
                         ("role:tech-lead", "design", 1, "ui-change"))
        # the done-gate leader sees every end
        gate = [c["request"] for c in ld.calls if c["situation"] == "done-gate"][0]
        self.assertEqual([q["outcome"] for q in gate.requests], ["applied", "declined", "noop", "applied"])

    def test_tc2_a_design_step_after_the_developer_is_declined(self):
        self.ok(self.run3(self.leader(), session=self.sess(
            review=[{"structured": S.result(requests=[S.request("ux-design")])}])))
        self.assertEqual(ends(self.state())[0], ("add", "ux-design", "declined", "position"))
        self.assertEqual(self.state()["revision"], 2)

    def test_tc9_a_start_step_request_is_for_the_plan_gate(self):
        ld = self.leader()
        self.ok(self.run3(ld, session=self.sess(analyze=[{
            "write": {f"{S.SPECS}/analysis.md": S.analysis()},
            "structured": S.result(requests=[S.request("product-review", trigger="scope-question", note="scope?")])}])))
        self.assertEqual(ends(self.state()), [("add", "product-review", "deferred-to-plan", None)])
        self.assertEqual(ld.calls[0]["request"].requested_steps,
                         [{"from_step": "analyze", "step": "product-review", "trigger": "scope-question",
                           "note": "scope?"}])
        self.assertNotIn("product-review", self.ids())

    def test_a_procedure_the_grammar_refuses_declines_the_requests(self):
        real = self.procs.check

        def check(proc, commands, stage=3):
            errs = real(proc, commands, stage=stage)
            return errs + (["no ux-review here"] if any(s.id == "ux-review" for s in proc.steps) else [])

        self.procs.check = check
        self.ok(self.run3(self.leader(), session=self.sess(design=self.design(S.request("ux-review")))))
        self.assertEqual(ends(self.state()), [("add", "ux-review", "declined", "grammar")])
        self.assertEqual(self.state()["revision"], 2)

    FOUR = [S.request("ux-design"), S.request("ux-review"), S.request("infra-review"),
            S.request("data-review", trigger="schema-change", note="index")]

    def four(self):
        return self.sess(design=self.design(*self.FOUR), ux_design=[{"write": {f"{S.SPECS}/ux.md": "u\n"}}])

    def test_tc5_tx4_the_fourth_request_is_the_leaders(self):
        ld = self.leader({"step-add-limit": [S.LA("continue", reason="other")]})
        self.ok(self.run3(ld, session=self.four()))
        call = [c for c in ld.calls if c["situation"] == "step-add-limit"]
        self.assertEqual([(c["kind"], c["step"]) for c in call], [("leader", "design")])
        self.assertEqual(call[0]["request"].add_limit,
                         {"from_step": "design", "limit": 3, "used": 3,
                          "requests": [{"step": "data-review", "trigger": "schema-change", "note": "index",
                                        "summary": "data-review summary"}]})
        st = self.state()
        self.assertEqual(ends(st)[3], ("add", "data-review", "declined", "limit"))
        self.assertEqual(st["totals"]["leader_calls"], 1)                     # counted (E35)
        self.assertEqual(self.sstep("design")["latest_attempt"], 1)           # continue does not rerun the step

    def test_tc5_escalate_then_the_human_continues(self):
        ld = self.leader({"step-add-limit": [S.LA("escalate", reason="needs-human-decision", recommendation={
            "answer": "continue", "step": None, "note": ""})]})
        self.assertEqual(self.run3(ld, session=self.four()), driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"], st["stop"]["allowed_answers"]),
                         ("step-add-limit", "design", ["continue", "escalate"]))
        self.assertEqual(S.steps_of(st)["implement"], "pending")
        self.ok(self.run3(ld, answer={"answer": "continue"}))
        self.assertEqual(ends(self.state())[3], ("add", "data-review", "declined", "limit"))

    def test_tc8_skip_a_catalog_step(self):
        ld = self.leader({"step-removal-request": [S.LA("skip", reason="other", skip_step="ux-review")]})
        self.ok(self.run3(ld, session=self.sess(
            design=self.design(S.request("ux-review")),
            implement=[{"write": {"src/app.py": "x = 2\n"}, "commit": "feat: x", "structured": S.result(
                requests=[S.request("ux-review", op="skip", trigger="no-user-facing-text", note="no UI")])}])))
        removal = [c["request"].removal for c in ld.calls if c["situation"] == "step-removal-request"]
        self.assertEqual(removal, [{"from_step": "implement", "skippable_steps": ["ux-review"], "requests": [
            {"op": "skip", "step": "ux-review", "trigger": "no-user-facing-text", "note": "no UI"}]}])
        st = self.state()
        s = self.sstep("ux-review")
        self.assertEqual((s["status"], s["reason"], s["detail"], s["latest_attempt"]),
                         ("skipped", "leader-skip", "other", None))
        self.assertEqual(ends(st)[1], ("skip", "ux-review", "skipped", None))
        self.assertEqual(st["revision"], 3)                                    # no structure change
        ans = [l for l in self.log("answer") if l["code"] == "step-removal-request"][0]
        self.assertEqual((ans["who"], ans["data"]["skip_step"]), ("leader", "ux-review"))

    def test_tc7_nothing_to_skip_continue_declines_and_skip_is_refused(self):
        ld = self.leader({"step-removal-request": [S.LA("skip", reason="other", skip_step="ux-design")]})
        self.assertEqual(self.run3(ld, session=self.sess(
            design=self.design(S.request("ux-design", op="remove")))), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual([c["request"].removal["skippable_steps"] for c in ld.calls
                          if c["situation"] == "step-removal-request"], [[]])
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["leader_failed"]["code"]),
                         ("step-removal-request", "output-format"))              # fail-closed: a human
        self.assertEqual(self.run3(ld, answer={"answer": "skip", "step": "implement"}), driver.EXIT_REFUSED)
        self.ok(self.run3(ld, answer={"answer": "continue"}))
        self.assertEqual(ends(self.state()), [("remove", "ux-design", "declined", "refused")])


class MandatoryGate(S.Stage3):
    cfg = S.config(path_rules=[S.TEST_CODE, S.SAFETY_NET,
                               {"kind": "risk", "area": "auth", "globs": ["src/**.py"], "gate": "security-review"}])

    def test_ti5_the_gate_counts_and_cannot_be_skipped(self):
        ld = self.leader({"step-removal-request": [S.LA("continue", reason="other")]})
        self.ok(self.run3(ld, session=self.sess(review=[{"structured": S.result(
            requests=[S.request("security-review", op="skip")])}])))
        st = self.state()
        self.assertEqual([(a["step"], a["source"], a["from_step"]) for a in st["catalog_adds"]],
                         [("security-review", "mandatory-rule", "implement")])
        self.assertEqual(self.log("procedure-written")[2]["data"]["source"], "mandatory-rule")
        self.assertEqual([c["request"].removal["skippable_steps"] for c in ld.calls
                          if c["situation"] == "step-removal-request"], [[]])
        self.assertEqual(S.steps_of(st)["security-review"], "done")


class Pure(unittest.TestCase):
    def proc(self, ids, revision):
        return procmod.Procedure({"format": 1, "issue": 42, "revision": revision,
                                  "origin": {"template": "feature", "version": "1", "start": "1"},
                                  "steps": [{"id": i, "role": "tester", "outputs": []} for i in ids]})

    def test_follow_procedure_only_adds(self):
        st = store.new_state(42, 2, ["a", "b", "c"], "a" * 40)
        st["steps"][0]["status"] = "done"
        new = statemachine.follow_procedure(st, self.proc(["a", "x", "b", "c", "y"], 3))
        self.assertEqual(new, ["x", "y"])
        self.assertEqual([(s["id"], s["status"]) for s in st["steps"]],
                         [("a", "done"), ("x", "pending"), ("b", "pending"), ("c", "pending"), ("y", "pending")])
        self.assertEqual(st["revision"], 3)
        for bad in (["a", "c"], ["b", "a", "c"]):
            with self.assertRaises(statemachine.StateError):
                statemachine.follow_procedure(store.new_state(42, 2, ["a", "b", "c"], "a" * 40), self.proc(bad, 3))

    def test_pending_requests_are_one_step_at_a_time(self):
        def q(step, n, reason):
            return {"from_step": step, "from_attempt": n, "op": "add", "step": "ux-review", "trigger": "other",
                    "note": "", "outcome": "pending", "reason": reason}

        st = {"requests": [q("a", 1, "limit"), q("a", 1, "limit"), q("b", 1, "limit"), q("a", 1, "removal")]}
        self.assertEqual(len(lifecycle.pending_requests(st, "step-add-limit")), 2)
        self.assertEqual(len(lifecycle.pending_requests(st, "step-removal-request")), 1)
        self.assertEqual(lifecycle.pending_requests(st, "blocked"), [])
        self.assertEqual(lifecycle.pending_requests({}, "step-add-limit"), [])

    def test_the_removal_and_limit_situations_have_a_leader_and_are_counted(self):
        for s in ("step-add-limit", "step-removal-request"):
            self.assertIn(s, codes.LEADER_CALL_COUNTED)
        self.assertNotIn("pr-review", codes.LEADER_CALL_COUNTED)


if __name__ == "__main__":
    unittest.main()
