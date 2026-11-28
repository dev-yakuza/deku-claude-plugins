"""Stage 3 flow — replan with deferred requirement rows (V12 [P2], session B2): TS1, TS2."""

import unittest

from gxengine import driver
from tests import c_world as W
from tests import s3_world as S

ROWS = {"defer": {"requirement_rows": [{"row": "R1", "requirement": "Show the quiz type", "acs": [1]},
                                       {"row": "R2", "requirement": "Keep it after a restart", "acs": [2]}],
                  "deferred": []}}


def replan(*rows):
    a = S.LA("replan", reason="needs-human-decision", note="too large", defer=list(rows), session=None)
    a["input"] = ROWS
    return a


class Defer(S.Stage3):
    def run_defer(self, *answers, results=None, **script):
        self.ld = self.leader(dict({"blocked": list(answers)}, **script))
        return self.run3(self.ld, results=results or S.FakeResults({"implement": [W.blocked, W.done]}))

    def test_ts1_back_to_analyze_ac_format_followup(self):
        self.ok(self.run_defer(replan("R2")))
        st = self.state()
        self.assertEqual([(r["row"], r["text"]) for r in st["deferred_rows"]], [("R2", "Keep it after a restart")])
        self.assertEqual(self.sstep("analyze")["latest_attempt"], 2)
        self.assertNotIn("returns", self.sstep("analyze"))                     # a replan is no rerun
        decision = self.in_file("analyze", 2, "leader-decision.md")
        self.assertIn("(deferred R2)", decision)
        self.assertIn("Keep it after a restart", decision)
        args = [c["plugin_args"] for c in self.runner.s3 if c["step"] == "ac-format"]
        self.assertEqual(args[0], ["--stage", "3"])
        self.assertEqual(args[1], ["--stage", "3", "--deferred", "R2"])
        self.assertEqual([c["situation"] for c in self.ld.calls],
                         ["plan-gate", "blocked", "plan-gate", "done-gate"])
        self.assertEqual(st["revision"], 2)                                    # L22: no new revision
        self.assertEqual([r["row"] for r in self.ld.calls[-1]["request"].deferred_rows], ["R2"])
        issue = self.gh.issues[900]
        self.assertEqual(issue["labels"], ["guild:followup", "type:feature"])
        self.assertIn("Keep it after a restart", issue["body"])
        self.assertRegex(st["followups"][0]["key"], r"^deferred:[0-9a-f]{8}$")
        ans = [l for l in self.log("answer") if l["code"] == "blocked"][0]
        self.assertEqual((ans["data"]["defer"], ans["data"]["target"]), (["R2"], "analyze"))

    def test_ts2_every_row_one_twice_or_an_unknown_one_is_no_answer(self):
        for rows in (["R1", "R2"], ["R2", "R2"], ["R9"]):
            with self.subTest(rows=rows):
                self.tearDown()
                self.setUp()
                self.assertEqual(self.run_defer(replan(*rows)), driver.EXIT_NEEDS_HUMAN)
                st = self.state()
                self.assertEqual((st["stop"]["reason"], st["stop"]["leader_failed"]["code"]), ("blocked", "output-format"))
                self.assertNotIn("deferred_rows", st)

    def test_ts2_only_once_per_issue_and_only_by_replan(self):
        res = S.FakeResults({"implement": [W.blocked, W.blocked, W.done]})
        self.assertEqual(self.run_defer(replan("R2"), replan("R1"), results=res), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual([r["row"] for r in self.state()["deferred_rows"]], ["R2"])
        self.assertIn("once per Issue", self.state()["stop"]["note"])


if __name__ == "__main__":
    unittest.main()
