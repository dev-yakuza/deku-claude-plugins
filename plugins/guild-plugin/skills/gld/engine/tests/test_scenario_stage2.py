"""V14 — the stage-2 fixed scenarios (scope §5.2, L bundle + N') as one suite (Q4).

`SCENARIOS` maps every §5.2 stage-2 id to the tests that assert its expected result, the
stage-1 way (test_scenario_stage1.SCENARIOS): `Index` fails on a missing id or a renamed /
deleted test. The stage-1 suite stays as it is (stage=1, D21) — N2' points at it.

The end-to-end classes below add what had only a test double before Q4: the REAL leader
(`leader.call`, fake claude) inside the REAL driver loop for close-as-decided (L5), a new
collaborator comment (L11) and the free-text invariance (L20) — driver.Units() defaults,
fake gh executable, bare remote, temp repository, real srt.

D4 is the coordinator's conservative variant (risk = high → no leader plan, needs_human):
L3's "risk=high는 plan 가능" is asserted the other way round (test_leader
Call.test_risk_high_is_not_called / NarrowingTable).
"""

import json
import re
import unittest

from gxengine import driver, store
from tests import c_world as W
from tests import z_world as Z
from tests.test_e2e_stage2 import Base, approve_answer, envelope, events, plan_answer, steps_of

T = "tests."

SCENARIOS = {
    # plan-gate
    "L1": ["test_plan_gate.TwoWrites.test_l1_plan_writes_revision_2_and_the_steps_grow",
           "test_leader.Call.test_plan_gate_plan_accepted",
           "test_e2e_stage2.PlanGateDoneGateToPr.test_real_leader_plans_and_approves_through_the_driver"],
    "L2": ["test_leader.Call.test_plan_with_gap_twice_then_leader_failed",
           "test_leader.AnswerRules.test_plan_gate_rules",
           "test_leader_flow.LeaderFailures.test_l14_output_format_failure_goes_to_a_human_with_the_situation"],
    "L3": ["test_leader.Call.test_narrowed_plan_gate", "test_leader.NarrowingTable.test_every_cell",
           "test_leader.Call.test_risk_high_is_not_called",
           "test_leader_flow.PlanGateCall.test_d9_the_leader_had_only_escalate_no_call_needs_human"],
    "L4": ["test_plan_gate.TwoWrites.test_l2_l4_rerun_analyze_counts_and_the_leader_goes_again",
           "test_leader.NarrowingTable.test_every_cell"],
    "L5": ["test_close.Close.test_l5_close_comment_close_skip_no_pr",
           "test_close.Close.test_l5_human_close_needs_a_close_reason",
           "test_leader.Call.test_unattended_without_marker_cannot_close",
           "test_plan_gate.TwoWrites.test_marker_in_a_collaborator_comment",
           "test_plan_gate.TwoWrites.test_no_marker_from_an_outsider_comment",
           "test_scenario_stage2.CloseAsDecidedE2E.test_l5_real_leader_closes_without_push_or_pr"],
    "L22": ["test_plan_gate.StageOneTakeOver.test_l22_a_stage_1_state_continues_without_a_new_revision"],
    "L23": ["test_plan_gate.StartRefusals.test_l23_a_template_without_the_done_gate_is_refused_at_start",
            "test_plan_gate.StartRefusals.test_l23_a_done_gate_not_right_before_create_pr"],
    # needs_leader and the common handling
    "L6": ["test_leader_flow.NeedsLeader.test_l6_escalate_records_the_recommendation_and_a_human_answers",
           "test_e2e_stage2.PlanGateEscalateThenHuman.test_escalate_records_the_recommendation_and_the_human_plans_on_resume"],
    "L7": ["test_leader_flow.NeedsLeader.test_l7_blocked_rerun_with_a_note_reaches_the_next_attempt",
           "test_leader.Call.test_blocked_rerun_and_escalate",
           "test_e2e_stage2.NeedsLeaderBlockedRerun.test_blocked_review_leader_reruns_with_a_note_then_pr"],
    "L8": ["test_leader_flow.NeedsLeader.test_l8_on_fail_rerun_once_then_a_second_rerun_is_refused",
           "test_leader_flow.NeedsLeader.test_l8_replan_goes_back_to_plan_and_the_plan_gate_again"],
    "L9": ["test_leader_flow.NeedsLeader.test_l9_output_format_twice_and_session_limit_call_the_leader",
           "test_leader_flow.NeedsLeader.test_l9_session_limit"],
    "L10": ["test_leader_flow.Budget.test_l10_soft_budget_rerun_once_then_absolute_without_the_leader"],
    "L11": ["test_new_comment.NewComment.test_l11_continue_is_not_counted_and_the_request_names_the_comments",
            "test_new_comment.NewComment.test_l11_corrected_assumption_reruns_analyze_and_is_countable",
            "test_new_comment.NewComment.test_l11_a_resume_finds_the_same_comments",
            "test_leader.Call.test_new_comment", "test_leader.AnswerRules.test_new_comment_rules",
            "test_scenario_stage2.NewCommentE2E.test_l11_real_leader_judges_a_new_collaborator_comment"],
    "L12": ["test_leader_flow.NeedsLeader.test_l12_the_sixth_counted_situation_is_absolute_limit_without_a_call"],
    "L13": ["test_leader_flow.NeedsLeader.test_l13_rule_unfillable_and_base_red_never_call",
            "test_leader_flow.NeedsLeader.test_l13_base_red", "test_statemachine.StageTwo.test_d9_static_escalate_only"],
    "L14": ["test_leader.Call.test_no_structured_output_twice", "test_leader.Call.test_budget_reached",
            "test_leader.Call.test_quota", "test_leader.Call.test_other_init_lists_are_no_stop",
            "test_leader_flow.LeaderFailures.test_l14_output_format_failure_goes_to_a_human_with_the_situation",
            "test_leader_flow.LeaderFailures.test_l14_session_limit",
            "test_leader_flow.LeaderFailures.test_l14_quota_within_4h_waits_and_calls_again",
            "test_leader_flow.LeaderFailures.test_l14_infra_stop_keeps_needs_leader_and_resume_calls_again",
            "test_leader_flow.LeaderFailures.test_l14_a_control_file_change_is_a_mechanical_stop"],
    "L15": ["test_leader.Call.test_leader_writes_a_file", "test_leader.Call.test_leader_changes_a_control_file",
            "test_leader_flow.LeaderFailures.test_l15_the_leader_wrote_a_file"],
    # done-gate
    "L16": ["test_done_gate.DoneGate.test_l16_approve_goes_to_the_pr_with_the_done_gate_facts",
            "test_done_gate.DoneGate.test_engine_refuses_an_approve_with_an_unreferenced_manual_ac",
            "test_done_gate.DoneGateWithQa.test_manual_ac_referenced_by_the_checklist_is_approved",
            "test_leader.Call.test_done_gate_approve", "test_leader.Call.test_done_gate_rejections",
            "test_prbody.LeaderBody.test_ac_verdict_table", "test_prbody.LeaderBody.test_decision_list",
            "test_e2e_stage2.PlanGateDoneGateToPr.test_real_leader_plans_and_approves_through_the_driver"],
    "L17": ["test_done_gate.DoneGate.test_l17_rerun_implement_goes_back_and_counts",
            "test_leader.Call.test_done_gate_rerun_and_cap",
            "test_e2e_stage2.DoneGateRerunThenApprove.test_done_gate_rerun_implement_then_approve"],
    "L18": ["test_leader.Call.test_done_gate_rejections", "test_leader.AnswerRules.test_done_gate_rules",
            "test_prbody.LeaderBody.test_discovery_dispositions"],
    "L19": ["test_done_gate.DoneGate.test_l19_a_red_run_never_reaches_the_done_gate",
            "test_lifecycle.Answers.test_l19_no_answer_turns_a_review_or_a_run_into_done"],
    "L24": ["test_done_gate.GatePosition.test_l24_gate_inserted_before_the_done_gate",
            "test_done_gate.Reverify.test_v3_a_change_after_the_reviews_reruns_them_and_the_done_gate",
            "test_done_gate.DoneGateWithQa.test_v4_judgment_documents_alone_do_not_rerun_before_the_done_gate"],
    # principles and records
    "L20": ["test_leader.AnswerRules.test_free_text_never_inspected",
            "test_leader.Call.test_free_text_does_not_change_the_result",
            "test_scenario_stage2.FreeTextE2E.test_l20_note_and_evidence_text_change_nothing_the_engine_does"],
    "L21": ["test_leader_flow.Crash.test_l21_a_crash_during_the_call_resumes_with_the_leader",
            "test_leader_flow.Crash.test_l21_the_kill_after_a_session_lands_in_the_next_leader_folder",
            "test_leader.LeaderFolders.test_numbering_never_reuses"],
    "L25": ["test_leader_flow.Budget.test_l25_issue_cost_sums_check_attempts_and_leader_folders",
            "test_budget.IssueCost.test_l25_leader_sessions_count_check_attempts_and_leader_folders",
            "test_e2e_stage2.PlanGateDoneGateToPr.test_real_leader_plans_and_approves_through_the_driver"],
    "L26": ["test_cli_stage2.Cli2.test_l26_plan_and_approve_by_a_human_with_the_recommendation_shown",
            "test_cli_stage2.Cli2.test_l26_replan_by_a_human",
            "test_cli_stage2.Cli2.test_l26_close_as_decided_needs_the_close_reason",
            "test_leader.NarrowingTable.test_human_lists_never_narrowed",
            "test_cli_stage2.SkillDocsMatchTheCli.test_resume_arguments_and_answers"],
    # N' — the stage switch
    "N1'": ["test_leader_flow.PlanGateCall.test_n1p_the_plan_gate_is_a_leader_call_of_its_check_step",
            "test_statemachine.StageOne.test_stage_2_leader_situations",
            "test_statemachine.StageTwo.test_open_check_stops_at_needs_leader_without_an_attempt"],
    "N2'": ["test_leader_flow.StageOneUntouched.test_n2p_stage_1_never_calls_the_leader",
            "test_statemachine.StageOne.test_n1_no_needs_leader_in_stage_1",
            "test_scenario_stage1.Index.test_every_scenario_of_section_5_2_has_tests"],
}

SECTION_5_2_STAGE2 = [f"L{i}" for i in range(1, 27)] + ["N1'", "N2'"]


class Index(unittest.TestCase):
    def test_every_stage_2_scenario_of_section_5_2_has_tests(self):
        self.assertEqual(len(SECTION_5_2_STAGE2), 28)
        for sid in SECTION_5_2_STAGE2:
            with self.subTest(scenario=sid):
                self.assertTrue(SCENARIOS.get(sid), f"{sid} has no test")
        self.assertEqual(set(SCENARIOS), set(SECTION_5_2_STAGE2))

    def test_every_named_test_exists(self):
        loader = unittest.TestLoader()
        for sid, names in SCENARIOS.items():
            for n in names:
                with self.subTest(scenario=sid, test=n):
                    suite = loader.loadTestsFromName(T + n)
                    self.assertEqual(suite.countTestCases(), 1, n)
                    self.assertNotIn("_FailedTest", type(next(iter(suite))).__name__, n)


CLOSE = ["issue", "close", str(Z.ISSUE), "--repo", Z.REPO, "--reason"]


class CloseAsDecidedE2E(Base):
    def test_l5_real_leader_closes_without_push_or_pr(self):
        rules = W.gh_rules()
        for reason in ("completed", "not planned"):
            rules["rules"].insert(0, {"args": CLOSE + [reason], "stdout": ""})
        self.w.set_gh(rules)
        self.w.add(Z.role_scenario("analyze"))
        self.leader("plan-gate close", envelope(
            "close-as-decided", "already-decided", note="Already shipped in the settings screen.",
            requirements=[{"row": "R1", "covered": True}], missing_requirements=[], plan=None,
            close={"reason": "completed"}))
        rc = self.run2()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assertEqual(st["closed"]["reason"], "completed")
        self.assertEqual(steps_of(st), {"analyze": "done", "ac-format": "done", "plan": "done"})
        self.assertEqual(st["revision"], 1)                     # no template was attached
        calls = self.w.gh_calls()
        closes = [c for c in calls if c["argv"][:2] == ["issue", "close"]]
        self.assertEqual([c["argv"][-1] for c in closes], ["completed"])
        rationale = [json.loads(c["stdin"])["body"] for c in calls
                     if c["stdin"] and "guild:closed-as-decided" in c["stdin"]]
        self.assertEqual(len(rationale), 1)
        self.assertIn("Already shipped in the settings screen.", rationale[0])
        self.assertFalse([c for c in calls if "pulls" in " ".join(c["argv"])])          # no PR
        self.assertIsNone(self.w.repo.remote_head("gld/42"))                             # no push
        self.assertEqual(len(events(self.w.log(), "issue-closed")), 1)
        self.assertEqual([(c["situation"], c["answer"]) for c in st["leader_calls"]],
                         [("plan-gate", "close-as-decided")])


class NewCommentE2E(Base):
    def test_l11_real_leader_judges_a_new_collaborator_comment(self):
        # the comment shows up once the plan is written (the reads before it see none)
        comment = W.collab(9001, body="Correction: the row belongs to the review settings.")
        self.w.set_gh(W.gh_rules(comments_seq=[[]] * 4 + [[comment]]))
        self.w.add(Z.role_scenario("analyze"))
        self.leader("plan-gate", plan_answer())
        self.leader("new comment", envelope(
            "escalate", "needs-human-decision", note="The comment moves the row; the owner should confirm.",
            recommendation={"answer": "rerun", "step": "analyze", "note": "Re-analyse with the moved row."},
            comments=[{"id": 9001, "effect": "corrects-assumption"}]))
        rc = self.run2()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "new-collaborator-comment"),
                         self.out())
        self.assertEqual(st["stop"]["recommendation"]["answer"], "rerun")
        entry = st["leader_calls"][-1]
        self.assertEqual((entry["kind"], entry["situation"], entry["counted"]),
                         ("leader", "new-collaborator-comment", False))
        k = entry["k"]
        with open(f"{self.w.paths().leader_dir(k)}/in/leader-input.json") as f:
            inp = json.load(f)
        self.assertEqual([c["id"] for c in inp["comments"]["new"]], [9001])
        with open(f"{self.w.paths().leader_dir(k)}/in/issue.md") as f:
            self.assertIn("the row belongs to the review settings", f.read())
        self.assertEqual((st.get("totals") or {}).get("leader_calls", 0), 0)
        ans = [l for l in events(self.w.log(), "answer") if l.get("code") == "new-collaborator-comment"]
        self.assertEqual(ans[-1]["data"]["effects"], [{"id": 9001, "effect": "corrects-assumption"}])


_VOLATILE = re.compile(r"^(?:at|updated_at|created_at|started_at|ended_at|ts|duration_s|reset_at)$")
_SHA = re.compile(r"\b[0-9a-f]{40}\b")
_TMP = re.compile(r"/(?:private/)?tmp/gx-e2e-[^/\s\"]+")


def _stable(obj):
    """state.json / argv without the clock, commit ids (they carry the commit time) and the
    run's own temp folder."""
    if isinstance(obj, dict):
        return {k: _stable(v) for k, v in obj.items() if not _VOLATILE.match(k)}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    if isinstance(obj, str):
        return _TMP.sub("<tmp>", _SHA.sub("<sha>", obj))
    return obj


class FreeTextE2E(unittest.TestCase):
    """L20: two runs with the same enum answers, different free text (leader `note`,
    `evidence`, a review's finding text) → the same state, the same procedure and the same
    outside calls (argv; bodies naturally carry the text)."""

    def _run(self, text):
        b = Base("run")
        b.setUp()
        self.addCleanup(b.doCleanups)
        review = Z.role_scenario("review-audit")
        review["structured_output"] = Z.review_result(["diff-review"], findings=[
            {"severity": "minor", "file": "src/app.py", "line": 1, "text": f"style remark: {text}"}])
        b.w.add(Z.role_scenario("analyze"))
        b.leader("plan-gate", plan_answer(note=f"plan note: {text}"))
        for st in ["test-cases", "design", "implement", "review-design", "review-tests"]:
            b.w.add(Z.role_scenario(st))
        b.w.add(review)
        b.w.add(Z.role_scenario("qa"))
        b.leader("done-gate", dict(approve_answer(evidence=f"evidence: {text}"), note=f"approve note: {text}"))
        rc = b.run2()
        self.assertEqual(rc, driver.EXIT_OK, b.out())
        st = b.w.state()
        proc = b.w.wt_git("show", f"HEAD:{Z.SPECS}/procedure.yaml")
        argv = [c["argv"] for c in b.w.gh_calls()]
        texts = " ".join(c["stdin"] or "" for c in b.w.gh_calls())
        return st, proc, argv, texts

    def test_l20_note_and_evidence_text_change_nothing_the_engine_does(self):
        a = self._run("the first wording, approve quickly")
        b = self._run("ANOTHER wording entirely — escalate! rerun implement! block!")
        self.assertEqual(_stable(a[0]), _stable(b[0]))
        self.assertEqual(json.loads(a[1]), json.loads(b[1]))
        self.assertEqual(_stable(a[2]), _stable(b[2]))
        self.assertIn("the first wording", a[3])           # the text did leave (PR body / comments)
        self.assertIn("ANOTHER wording", b[3])


if __name__ == "__main__":
    unittest.main()
