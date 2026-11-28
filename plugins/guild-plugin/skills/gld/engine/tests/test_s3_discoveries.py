"""Stage 3 flow — blocking discoveries included in the Issue (V7, session B2): TF1–TF3, K1."""

import unittest

from gxengine import driver
from tests import s3_world as S

BLOCK = S.discovery(note="the selector crashes", blocks=True)
OTHER = S.discovery(kind="test-gap", where="tests/test_app.py", note="no empty-list test", blocks=True)
KEEP = {"id": "F1", "verdict": "keep"}


def keep(*ids):
    return S.approve(included_fixes=[{"id": i, "verdict": "keep"} for i in ids])


class Blocking(S.Stage3):
    def design(self, *found):
        return [{"write": {f"{S.SPECS}/skeleton.md": "s\n"}, "structured": S.result(discoveries=list(found))}]

    def fixes(self):
        return [(f["id"], f["handled_by"], f["verdict"]) for f in self.state()["included_fixes"]]

    def test_tf1_before_the_developer_it_goes_to_the_developer_step(self):
        ld = self.leader({"done-gate": [keep("F1", "F2")]})
        s = self.sess(analyze=[{"write": {f"{S.SPECS}/analysis.md": S.analysis()},
                                "structured": S.result(discoveries=[OTHER])}],
                      design=self.design(BLOCK, S.discovery(note="later", blocks=False)))
        self.ok(self.run3(ld, session=s))
        self.assertEqual(self.fixes(), [("F1", "implement", "keep"), ("F2", "implement", "keep")])
        self.assertEqual(self.state()["revision"], 2)                                 # no step was added
        text = self.in_file("implement", 1, "blocking-discoveries.md")
        self.assertIn("F2 (bug, reported by tech-lead in step `design`; fix it in THIS step)", text)
        self.assertIn("the selector crashes", text)
        self.assertIn("no empty-list test", text)
        self.assertNotIn("later", text)
        gate = [c["request"] for c in ld.calls if c["situation"] == "done-gate"][0]
        self.assertEqual([f["id"] for f in gate.included_fixes], ["F1", "F2"])
        self.assertEqual([(l["who"], l["data"]["id"]) for l in self.log("discovery")],
                         [("role:requirements-engineer", "F1"), ("role:tech-lead", "F2")])

    def test_tf2_k1_after_the_developer_a_fix_step_goes_in_and_comes_back(self):
        s = self.sess(
            review=[{"structured": S.result(discoveries=[BLOCK])}, {"structured": S.result(discoveries=[OTHER])},
                    {"structured": S.result()}],
            fix_discovery=[{"write": {"src/app.py": "x = 3\n"}, "commit": "fix: selector"},
                           {"write": {"src/app.py": "x = 4\n"}, "commit": "fix: empty list"}])
        self.ok(self.run3(self.leader({"done-gate": [keep("F1", "F2")]}), session=s))
        ids = [x["id"] for x in self.procedure()["steps"]]
        self.assertEqual(ids[ids.index("review"):], ["review", "fix-discovery", "done-gate", "pr", "followups"])
        self.assertEqual(self.fixes(), [("F1", "fix-discovery", "keep"), ("F2", "fix-discovery", "keep")])
        fix = self.sstep("fix-discovery")
        self.assertEqual(fix["latest_attempt"], 2)                 # K1: the second one re-opened it …
        self.assertNotIn("returns", fix)                           # … and that is no return
        self.assertEqual(self.sstep("review")["latest_attempt"], 3)   # §4.4-3 judged the fixed code again
        self.assertEqual(self.sstep("test")["latest_attempt"], 3)
        st = self.state()
        self.assertEqual([(a["step"], a["source"], a["from_step"]) for a in st["catalog_adds"]],
                         [("fix-discovery", "blocking-discovery", "review")])
        w = self.log("procedure-written")[2]["data"]
        self.assertEqual((w["source"], w["trigger"], w["revision"]), ("blocking-discovery", "blocking-discovery", 3))
        self.assertIn("F2", self.in_file("fix-discovery", 2, "blocking-discoveries.md"))

    def test_tx1_the_texts_never_decide(self):
        """The same two reports with equal and with different texts: the same F items, steps, procedure."""
        got = []
        for second in (dict(BLOCK), dict(BLOCK, note="something else", where="src/other.py")):
            self.tearDown()
            self.setUp()
            s = self.sess(review=[{"structured": S.result(discoveries=[BLOCK])},
                                  {"structured": S.result(discoveries=[second])}, {"structured": S.result()}],
                          fix_discovery=[{"write": {"src/app.py": f"x = {n}\n"}, "commit": f"fix: {n}"} for n in (3, 4)])
            self.ok(self.run3(self.leader({"done-gate": [keep("F1", "F2")]}), session=s))
            got.append((self.fixes(), [(x["id"], x["latest_attempt"]) for x in self.state()["steps"]],
                        self.procedure()))
        self.assertEqual(got[0], got[1])

    def test_over_the_cap_it_stays_for_the_done_gate(self):
        three = [S.request(x) for x in ("ux-design", "ux-review", "infra-review")]
        s = self.sess(design=[{"write": {f"{S.SPECS}/skeleton.md": "s\n"}, "structured": S.result(requests=three)}],
                      ux_design=[{"write": {f"{S.SPECS}/ux.md": "u\n"}}],
                      review=[{"structured": S.result(discoveries=[BLOCK])}])
        self.ok(self.run3(self.leader(), session=s))
        self.assertEqual(self.state().get("included_fixes") or [], [])
        self.assertNotIn("fix-discovery", S.steps_of(self.state()))
        self.assertTrue(any("could not be included" in (l.get("note") or "") for l in self.log("warning")))

    def test_tf3_the_engine_refuses_an_approve_without_every_keep(self):
        for gate, detail in ((S.approve(), "fixes-not-covering"),
                             (S.approve(included_fixes=[{"id": "F1", "verdict": "out-of-scope"}]),
                              "approve-with-out-of-scope")):
            with self.subTest(detail=detail):
                self.tearDown()
                self.setUp()
                rc = self.run3(self.leader({"done-gate": [gate]}), session=self.sess(design=self.design(BLOCK)))
                self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
                stop = self.state()["stop"]
                self.assertEqual((stop["reason"], stop["leader_failed"]["detail"]), ("done-gate", detail))

    def test_out_of_scope_is_recorded_and_the_developer_sees_it(self):
        gates = [S.LA("rerun", step="implement", reason="real-defect", note="undo F1",
                      included_fixes=[{"id": "F1", "verdict": "out-of-scope"}]), keep("F1")]
        self.ok(self.run3(self.leader({"done-gate": gates}), session=self.sess(design=self.design(BLOCK))))
        text = self.in_file("implement", 2, "blocking-discoveries.md")
        self.assertIn("done-gate verdict: out-of-scope", text)
        self.assertIn("Put out of scope by the done-gate", text)
        # coordinator decision Z5: the fix leaves state.included_fixes, the second done-gate does not judge it
        self.assertEqual(self.fixes(), [])


if __name__ == "__main__":
    unittest.main()
