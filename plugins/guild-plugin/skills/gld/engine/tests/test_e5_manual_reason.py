"""E5 (R2 #1939): a `manual` done-gate verdict says why no automated check proves it.

#1939: the design (skeleton §7) proposed a source-text guard for the `main` wiring ACs #2 / #7 and left its adoption
"to the tester"; nobody took it and the done-gate approved both as `manual` — the Issue's main purpose stayed a human
check. The rule, split by what a machine can decide:

  * mechanical (engine): every `manual` verdict carries a non-blank `why_not_automated`, every `met` / `unmet` one
    null — the leader's check (format retry, then a human) and the driver again before an approve is applied;
  * judgement (leader, tasks/leader-stage3/done-gate.md): whether the design documents proposed a check for that
    criterion and whether the reason holds — discretion alone ("left to the tester") is `rerun test-cases`.
    The reason is free text the engine never reads (L20); the human reads it in the PR next to the verdict.

Stage 2 is unchanged (its schema has no such field). No paid call, no GitHub call.
"""

import copy
import unittest
from unittest import mock

from gxengine import codes, driver, instructions, leader, prbody, schema
from tests import s3_world as S
from tests import test_leader_stage3 as L3
from tests import test_prbody as TP

F = codes.LeaderFormatReason
MISMATCH = F.MANUAL_REASON_MISMATCH.value
WHY = "the colour is judged on a device screen; the design documents proposed no automated check"


def verdicts(manual_why=WHY, met_why=None):
    return [{"ac": 1, "status": "met", "evidence": "test/a_test.dart 'x'", "why_not_automated": met_why},
            {"ac": 2, "status": "manual", "evidence": "manual-test-checklist.md item 1", "why_not_automated": manual_why}]


class LeaderCheck(L3.Stage3Case):
    def setUp(self):
        super().setUp()
        self.req = L3.dg_request(L3.dg_world(self.tmp))

    def test_a_manual_verdict_needs_a_reason(self):
        self.assertEqual(self.check(self.req, L3.dg(ac_verdicts=verdicts())), [])
        for why in (None, "", "  \n\t"):
            with self.subTest(why=why):
                self.assertEqual(self.check(self.req, L3.dg(ac_verdicts=verdicts(manual_why=why))), [MISMATCH])

    def test_a_met_or_unmet_verdict_has_none(self):
        self.assertEqual(self.check(self.req, L3.dg(ac_verdicts=verdicts(met_why="x"))), [MISMATCH])
        unmet = [dict(v, status="unmet", why_not_automated="x") for v in verdicts()]
        self.assertIn(MISMATCH, self.check(self.req, L3.dg(answer="rerun", step="implement", ac_verdicts=unmet)))

    def test_every_answer_not_only_approve(self):
        """An escalated answer's table still reaches the PR when a human approves (D17)."""
        bad = verdicts(manual_why=None)
        self.assertEqual(self.check(self.req, L3.dg(answer="rerun", step="test-cases", reason="upstream-gap",
                                                    ac_verdicts=bad)), [MISMATCH])
        self.assertEqual(self.check(self.req, L3.dg(answer="escalate", reason="needs-human-decision", ac_verdicts=bad,
                                                    recommendation=L3.rec("approve"))), [MISMATCH])

    def test_the_field_is_required_by_the_schema(self):
        rendered = self.schema_of(self.req)["properties"]["ac_verdicts"]["items"]
        self.assertIn("why_not_automated", rendered["required"])
        answer = L3.dg(ac_verdicts=verdicts())
        del answer["ac_verdicts"][0]["why_not_automated"]
        self.assertEqual(set(self.check(self.req, answer)), {F.ANSWER_SCHEMA.value})

    def test_the_reason_is_presence_only(self):
        """Whether "left to the tester" holds is the leader's judgement — the engine never reads the text (L20)."""
        self.assertEqual(self.check(self.req, L3.dg(ac_verdicts=verdicts(manual_why="도입 여부는 tester 재량"))), [])
        self.assertEqual(leader.manual_reason_problems(verdicts(manual_why="optional")), [])
        self.assertEqual(leader.manual_reason_problems(verdicts(manual_why=" ")), [2])
        self.assertEqual(leader.manual_reason_problems([{"ac": 3, "status": "met"}]), [])     # absent = null

    def test_stage_2_is_unchanged(self):
        two = schema.load_schema("leader-answer-done-gate")
        self.assertNotIn("why_not_automated", two["properties"]["ac_verdicts"]["items"]["properties"])
        self.assertNotIn(MISMATCH, {r for r in F.values()} - codes.STAGE3_LEADER_FORMAT_REASONS)


class TaskText(unittest.TestCase):
    def test_the_rule_is_in_the_done_gate_task_from_stage_3(self):
        for stage in (3, 4):
            text = instructions.leader_task_text("done-gate", stage)
            self.assertIn("`why_not_automated`", text)
            self.assertIn("left to the tester", text)
            self.assertIn("Answer `rerun` with `test-cases`", text)
            self.assertIn("The engine checks only that `why_not_automated` is filled", text)
        self.assertNotIn("why_not_automated", instructions.leader_task_text("done-gate", 2))


class EngineSide(S.Stage3):
    """The driver checks again before an approve is applied (fail-closed, like D6). The checklist reference
    (D6) is not this test's: it is held at "referenced"."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(driver, "_manual_acs_unreferenced", return_value=[])
        patch.start()
        self.addCleanup(patch.stop)

    def gate(self, why):
        return S.LA("approve", reason="acceptance-met", ac_verdicts=verdicts(manual_why=why), discoveries=[],
                    included_fixes=[])

    def test_an_approve_with_an_unreasoned_manual_ac_goes_to_a_human(self):
        """Stage ≥ 3 (`env.stage >= 3`; this world is a stage-3 one), both modes."""
        for mode in ("unattended", "attended"):
            with self.subTest(mode=mode):
                self.tearDown()
                self.setUp()
                rc = self.run3(self.leader({"done-gate": [self.gate("  ")]}), mode=mode)
                self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.w.out.getvalue())
                stop = self.state()["stop"]
                self.assertEqual((stop["reason"], stop["status"]), ("done-gate", "needs_human"))
                self.assertEqual(stop["leader_failed"], {"code": "output-format", "detail": MISMATCH})
                self.assertIn("why_not_automated of AC(s) [2]", stop.get("note") or "")
                self.assertIsNone(self.state()["github"].get("pr_number"))

    def test_with_a_reason_the_approve_goes_on(self):
        self.ok(self.run3(self.leader({"done-gate": [self.gate(WHY)]})))
        self.assertTrue(self.state()["github"].get("pr_number"))


class PrBody(unittest.TestCase):
    def body(self, why):
        proc, state, fb, results, cfg, qa, analysis, lead = TP.scenario_bug()
        for v in results["done-gate"]["ac_verdicts"]:
            if v["status"] == "manual":
                v["why_not_automated"] = why
        return prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                            stage3={"is_private": True, "dry_run": False, "followups": None})

    def test_the_reason_follows_the_evidence(self):
        b = self.body("needs a | real device")
        self.assertIn("— 자동 검사를 두지 않은 이유: needs a \\| real device |", b)
        self.assertIn("`manual` AC의 자동화하지 않은 이유 유무만 확인했습니다", b)

    def test_without_a_reason_the_table_is_as_before(self):
        self.assertEqual(self.body(None), self.body("  "))
        self.assertNotIn("자동 검사를 두지 않은 이유", self.body(None))
        self.assertNotIn("자동화하지 않은 이유 유무", self.body(None))


if __name__ == "__main__":
    unittest.main()
