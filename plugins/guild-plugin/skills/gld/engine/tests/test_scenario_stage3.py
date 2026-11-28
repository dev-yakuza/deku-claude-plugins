"""V20 — the stage-3 fixed scenarios (stage-3 scope §5.2, the T bundle) as one suite (Q4), and the Q4
coordinator decisions Z1–Z7 pinned by tests.

`SCENARIOS` maps every §5.2 stage-3 id to the tests that assert its expected result (the stage-1 / stage-2
way: test_scenario_stage1.SCENARIOS, test_scenario_stage2.SCENARIOS). `Index` fails on a missing id or a
renamed / deleted test. The end-to-end runs with every stage-3 unit real are tests/test_e2e_stage3.py;
the rest are the sessions' unit / flow tests (B2's flow tests use the doubles of tests/s3_world.py).

Notes on the index (the scope text against what is built):
  - TB4: "fix makes a NEW test file → foreign-output" is the other way round since review-q0 D2 — a work step
    owns the files it really changed, so fix may add another test (OwnedFiles.test_d2_other_tests_are_free);
    changing / deleting the reproduce step's own file is still foreign-output.
  - TF7: an answer over FOLLOWUPS_MAX is refused by the leader check (followup-over-cap); one that reaches the op
    anyway stops it (fail-closed, Q4).
  - TX2: the stage-1 / stage-2 suites themselves run at stage 1 / 2 (D21); the index names their Index tests.

Z decisions (Q4, coordinator):
  Z1 srt temp folder = /tmp/gx-<issue>-<attempt>-<repo hash>-<pid>   Z2 a resumed call's own cost
  Z3 effort-only raise keeps --resume                                  Z4 work-output globs, render boundary
  Z5 an out-of-scope fix leaves state.included_fixes                   Z6 a non-stage-3 analysis → analyze again
  Z7 a result.json lone surrogate is passed on escaped
"""

import inspect
import json
import os
import tempfile
import unittest
from unittest import mock

from gxengine import (acparse, codes, defaults, driver, instructions, ladder, leader, paths as pathsmod, procedure,
                      render, session, store, streamjson)
from tests import a_layout
from tests import z_world as Z
from tests.helpers import fakes

T = "tests."

SCENARIOS = {
    'TY1': [
        'test_s3_plan.Templates.test_ty1_bug_gets_the_bug_template_only',
        'test_leader_stage3.PlanNarrowing.test_rows',
        'test_contracts.Stage3Tables.test_type_templates',
    ],
    'TY2': [
        'test_s3_plan.Templates.test_ty2_the_safety_net_field_picks_the_refactor_template',
        'test_leader_stage3.PlanNarrowing.test_rows',
        'test_contracts.Stage3Tables.test_type_templates',
    ],
    'TY3': [
        'test_s3_plan.Templates.test_ty3_docs_and_chore_have_no_template',
        'test_leader_stage3.PlanNarrowing.test_no_template_for_type',
        'test_leader_stage3.PlanGate.test_call_docs_has_no_plan',
    ],
    'TY4': [
        'test_s3_plan.Unusable.test_ty4_the_template_is_unusable_and_the_reason_is_shown',
        'test_leader_stage3.PlanNarrowing.test_template_unusable',
        'test_leader_stage3.PlanGate.test_input',
        'test_procedure.Stage3Plan.test_template_problems',
    ],
    'TY5': [
        'test_scenario_stage3.Z6.test_a_stage_2_analysis_is_no_stage_3_analysis',
        'test_s3_plan.Templates.test_an_unreadable_analysis_goes_back_to_analyze_once_z6',
        'test_acparse.SafetyNet.test_needs_type_refactor',
        'test_scripts.AcFormat.test_stage_3_needs_safety_net',
    ],
    'TB1': [
        'test_e2e_stage3.BugEndToEnd.test_tb1_bug_template_from_plan_to_pr',
        'test_s3_plan.BugFlow.test_tb1_path_tokens_evidence_run_and_the_evidence_file',
        'test_runner_stage3.ReproRed.test_tb1_red_twice_on_the_overlay_and_green_on_the_base',
        'test_prbody.Stage3Sections.test_repro_evidence_is_the_latest_facts',
    ],
    'TB2': [
        'test_runner_stage3.ReproRed.test_tb2_a_green_test_is_no_reproduction',
        'test_templates.Stage3Templates.test_bug_shape',
    ],
    'TB3': [
        'test_runner_stage3.ReproRed.test_tb3_a_change_outside_the_globs_is_repro_scope_and_nothing_runs',
        'test_stage3_ownership.OwnedFiles.test_tb3_scope_facts',
    ],
    'TB4': [
        'test_stage3_ownership.OwnedFiles.test_tb4_the_fix_may_not_touch_the_regression_test',
        'test_stage3_ownership.OwnedFiles.test_deleting_the_regression_test_is_foreign',
    ],
    'TB5': [
        'test_e2e_stage3.BlockedReproduceEndToEnd.test_tb5_blocked_reproduce_escalates_and_no_answer_passes_it',
        'test_contracts.Stage3Tables.test_no_red_to_pass_path',
    ],
    'TB6': [
        'test_runner_stage3.ReproRed.test_tb6_a_timeout_is_never_red',
        'test_runner_stage3.ReproRed.test_tb6_base_red_stops',
    ],
    'TR1': [
        'test_e2e_stage3.RefactorEndToEnd.test_tr1_refactor_template_with_a_new_test_file',
        'test_runner_stage3.Frozen.test_tr1_production_changes_and_new_tests_pass',
        'test_templates.Stage3Templates.test_refactor_shapes',
    ],
    'TR2': [
        'test_runner_stage3.Frozen.test_tr2_an_existing_test_changed',
    ],
    'TR3': [
        'test_runner_stage3.Frozen.test_tr3_tg4_golden_and_comparison_config',
    ],
    'TR4': [
        'test_runner_stage3.Frozen.test_tr4_an_exact_rename_passes',
        'test_runner_stage3.Frozen.test_tr4_a_rename_with_changes_fails',
    ],
    'TR5': [
        'test_runner_stage3.SafetyNetProof.test_tr5_green_on_the_base',
        'test_stage3_ownership.OwnedFiles.test_owned_files_are_the_net_files_of_the_attempts',
    ],
    'TR6': [
        'test_runner_stage3.SafetyNetProof.test_tr6_red_on_base',
        'test_templates.Stage3Templates.test_refactor_shapes',
    ],
    'TR7': [
        'test_runner_stage3.SafetyNetProof.test_tr7_a_snapshot_written_by_the_run',
    ],
    'TR8': [
        'test_runner_stage3.SafetyNetProof.test_tr8_an_existing_test_file_changed',
        'test_runner_stage3.SafetyNetExisting.test_deleting_one_is_net_scope_too',
    ],
    'TR9': [
        'test_runner_stage3.NoProductionChange.test_tr9_production',
    ],
    'TC1': [
        'test_s3_requests.Requests.test_tc1_tc3_tc4_tc11_one_revision_for_all_requests_of_one_step',
        'test_catalog.Requests.test_tc1_applied',
        'test_catalog.Position.test_diff_review',
    ],
    'TC2': [
        'test_s3_requests.Requests.test_tc2_a_design_step_after_the_developer_is_declined',
        'test_catalog.Requests.test_tc2_position',
        'test_catalog.Position.test_design_time',
    ],
    'TC3': [
        'test_s3_requests.Requests.test_tc1_tc3_tc4_tc11_one_revision_for_all_requests_of_one_step',
        'test_catalog.Requests.test_tc3_role_unavailable',
    ],
    'TC4': [
        'test_s3_requests.Requests.test_tc1_tc3_tc4_tc11_one_revision_for_all_requests_of_one_step',
        'test_catalog.Requests.test_tc4_noop',
    ],
    'TC5': [
        'test_s3_requests.Requests.test_tc5_tx4_the_fourth_request_is_the_leaders',
        'test_s3_requests.Requests.test_tc5_escalate_then_the_human_continues',
        'test_leader_stage3.StepAddLimit.test_call',
        'test_rules.Stage3Gates.test_the_limit_never_blocks_a_gate',
    ],
    'TC6': [
        'test_catalog.Requests.test_tc6_outside_the_catalog_is_fail_closed',
        'test_results.ResultSchemas.test_tc6_a_request_outside_the_catalog_is_a_schema_error',
        'test_contracts.SchemaShapes.test_stage3_result_refuses_a_step_outside_the_catalog',
    ],
    'TC7': [
        'test_s3_requests.Requests.test_tc7_nothing_to_skip_continue_declines_and_skip_is_refused',
        'test_leader_stage3.StepRemoval.test_template_step_with_a_catalog_id',
        'test_catalog.Requests.test_tc7_tc8_removal',
    ],
    'TC8': [
        'test_s3_requests.Requests.test_tc8_skip_a_catalog_step',
        'test_leader_stage3.StepRemoval.test_only_a_catalog_added_step_is_skippable',
        'test_rules.Stage3Gates.test_a_requested_gate_becomes_mandatory',
        'test_catalog.Skippable.test_template_steps_and_mandatory_gates_never',
    ],
    'TC9': [
        'test_s3_requests.Requests.test_tc9_a_start_step_request_is_for_the_plan_gate',
        'test_s3_plan.PlanAnswer.test_tc9_tc10_adjust_goes_in_with_the_plan',
        'test_catalog.Requests.test_tc9_start_steps_defer',
        'test_leader_stage3.PlanGate.test_call_plan_with_adjust',
    ],
    'TC10': [
        'test_s3_plan.PlanAnswer.test_tc9_tc10_adjust_goes_in_with_the_plan',
        'test_catalog.ExpandInsert.test_propagation',
        'test_procedure.Stage3Plan.test_adjust_in_one_revision',
    ],
    'TC11': [
        'test_s3_requests.Requests.test_tc1_tc3_tc4_tc11_one_revision_for_all_requests_of_one_step',
        'test_catalog.Requests.test_tc10_tc11_one_list_for_every_request',
    ],
    'TF1': [
        'test_s3_discoveries.Blocking.test_tf1_before_the_developer_it_goes_to_the_developer_step',
    ],
    'TF2': [
        'test_s3_discoveries.Blocking.test_tf2_k1_after_the_developer_a_fix_step_goes_in_and_comes_back',
    ],
    'TF3': [
        'test_scenario_stage3.Z5.test_an_out_of_scope_fix_leaves_the_issue_and_its_number_is_not_reused',
        'test_s3_discoveries.Blocking.test_tf3_the_engine_refuses_an_approve_without_every_keep',
        'test_leader_stage3.IncludedFixes.test_rules',
    ],
    'TF4': [
        'test_e2e_stage3.FollowupsEndToEnd.test_tf4_tf6_followup_issue_duplicate_comment_pr_patch_then_done',
        'test_s3_followups.Followups.test_tf4_tf6_tf8_created_commented_and_the_private_security_issue',
        'test_github.Followups.test_tf4_followup_and_duplicate_are_written_neutralised_with_the_marker_first',
        'test_github.Followups.test_secret_stops_before_any_write_in_both_modes',
        'test_prbody.Stage3Body.test_followup_section_after_the_op',
    ],
    'TF5': [
        'test_e2e_stage3.FollowupsEndToEnd.test_tf5_a_resumed_op_finds_the_issue_by_its_marker',
        'test_s3_followups.Followups.test_tf5_tf10_a_failure_stops_infra_and_resume_repeats_nothing',
        'test_github.Followups.test_tf5_a_resume_after_a_crash_does_not_create_twice',
    ],
    'TF6': [
        'test_e2e_stage3.FollowupsEndToEnd.test_tf4_tf6_followup_issue_duplicate_comment_pr_patch_then_done',
        'test_s3_followups.Followups.test_tf4_tf6_tf8_created_commented_and_the_private_security_issue',
        'test_leader_stage3.Dispositions.test_no_candidate_no_duplicate',
        'test_github.Followups.test_a_duplicate_comment_is_not_repeated',
    ],
    'TF7': [
        'test_leader_stage3.Dispositions.test_over_cap',
        'test_s3_followups.Followups.test_an_answer_over_the_cap_creates_nothing',
    ],
    'TF8': [
        'test_s3_followups.Followups.test_tf4_tf6_tf8_created_commented_and_the_private_security_issue',
        'test_github.Followups.test_tf8_private_security_followup_gets_the_security_label',
        'test_prbody.Stage3Body.test_e21_no_security_content_in_any_repository',
        'test_prbody.Stage3Body.test_followup_section_after_the_op',
    ],
    'TF9': [
        'test_s3_followups.Followups.test_tf9_public_repository_nothing_of_a_security_discovery_leaves',
        'test_github.Followups.test_tf9_private_path_writes_nothing_to_github',
        'test_prbody.SummaryStage3.test_public_and_dry_run',
    ],
    'TF10': [
        'test_s3_followups.Followups.test_tf5_tf10_a_failure_stops_infra_and_resume_repeats_nothing',
        'test_github.Followups.test_tf10_a_failed_create_raises_and_keeps_the_rows_before',
    ],
    'TF11': [
        'test_e2e_stage3.DryRunEndToEnd.test_tf11_dry_run_writes_nothing_and_records_what_it_would',
        'test_s3_followups.DryRun.test_tf11_records_only',
        'test_github.Followups.test_tf11_dry_run_records_and_writes_nothing',
        'test_prbody.Stage3Body.test_followup_section_dry_run_and_private_path',
        'test_repoconfig.Stage3Settings.test_dry_run',
    ],
    'TI1': [
        'test_s3_irreversible.Notify.test_ti1_ti4_notify_goes_on_with_the_label_and_the_lowered_level',
        'test_prbody.Stage3Sections.test_irreversible_levels_and_lowered',
    ],
    'TI2': [
        'test_s3_irreversible.HumanDecision.test_ti2_ti6_approve_once_per_path_and_no_leader',
        'test_s3_irreversible.HumanDecision.test_rerun_asks_again_only_while_the_change_is_there',
        'test_cli_stage3.Cli3.test_status_shows_stage3_and_the_human_answers_an_irreversible_stop',
    ],
    'TI3': [
        'test_s3_irreversible.Codes.test_ti3_a_code_of_the_analysis_stops_before_the_plan_gate',
        'test_instructions.Frames.test_stage3_frame_names_every_irreversible_code',
    ],
    'TI4': [
        'test_s3_irreversible.Notify.test_ti1_ti4_notify_goes_on_with_the_label_and_the_lowered_level',
        'test_prbody.Stage3Sections.test_irreversible_levels_and_lowered',
        'test_repoconfig.Stage3Settings.test_levels',
    ],
    'TI5': [
        'test_s3_requests.MandatoryGate.test_ti5_the_gate_counts_and_cannot_be_skipped',
        'test_rules.Stage3Gates.test_gate_after_every_review_is_right_before_the_done_gate',
        'test_rules.Stage3Gates.test_unfillable',
    ],
    'TI6': [
        'test_s3_irreversible.HumanDecision.test_ti2_ti6_approve_once_per_path_and_no_leader',
        'test_s3_irreversible.Pure.test_there_is_no_leader_seat',
        'test_contracts.Stage3Tables.test_stage3_answer_table',
    ],
    'TM1': [
        'test_s3_raise.Raise.test_tm1_tm3_tm4_tm5_two_returns_raise_the_effort_three_the_model',
        'test_ladder.Raised.test_tm1_steps',
        'test_stage3_ownership.Facts.test_tm1_the_escalation_is_carried_into_the_session_facts',
    ],
    'TM2': [
        'test_s3_raise.Raise.test_tm2_the_top_of_the_ladder_goes_on_capped',
        'test_ladder.Raised.test_tm2_capped_goes_on',
    ],
    'TM3': [
        'test_s3_raise.Raise.test_tm1_tm3_tm4_tm5_two_returns_raise_the_effort_three_the_model',
        'test_ladder.Raisable.test_e26_2',
    ],
    'TM4': [
        'test_s3_raise.Raise.test_tm1_tm3_tm4_tm5_two_returns_raise_the_effort_three_the_model',
        'test_ladder.Returns.test_refusals_change_nothing',
    ],
    'TM5': [
        'test_scenario_stage3.Z3.test_tm5_the_real_ladder_keeps_the_resume_for_an_effort_raise',
        'test_s3_raise.Raise.test_tm5_effort_only_keeps_the_session_when_the_ladder_allows_it',
        'test_ladder.Resume.test_tm5',
        'test_ladder.Resume.test_effort_only_change_keeps_the_resume_z3',
        'test_session.Stage3.test_tm5_resume',
    ],
    'TM6': [
        'test_s3_plan.PlanAnswer.test_tm6_models_apply_from_the_first_attempt',
        'test_s3_plan.PlanAnswer.test_models_outside_the_template_or_the_allow_list_are_refused',
        'test_leader_stage3.PlanGate.test_schema',
        'test_ladder.BaseChoice.test_tm6_tm7_an_override_wins',
    ],
    'TM7': [
        'test_s3_raise.Raise.test_tm7_rerun_session_is_the_new_base',
        'test_ladder.Raised.test_tm7_the_raise_starts_from_the_leader_base',
        'test_leader_stage3.RerunSession.test_call',
    ],
    'TM8': [
        'test_s3_raise.OpenLadder.test_tm8_the_repository_opens_max',
        'test_ladder.Raised.test_tm8_the_settings_open_max_and_fable',
    ],
    'TS1': [
        'test_s3_defer.Defer.test_ts1_back_to_analyze_ac_format_followup',
        'test_leader_stage3.Defer.test_call',
        'test_scripts.AcFormat.test_deferred_rows',
        'test_prbody.Deferred.test_pr_section_right_below_the_ac_list',
    ],
    'TS2': [
        'test_s3_defer.Defer.test_ts2_every_row_one_twice_or_an_unknown_one_is_no_answer',
        'test_s3_defer.Defer.test_ts2_only_once_per_issue_and_only_by_replan',
        'test_leader_stage3.Defer.test_rules',
        'test_leader_stage3.Defer.test_used_once',
    ],
    'TS3': [
        'test_acparse.Deferred.test_set_must_match',
        'test_scripts.AcFormat.test_deferred_rows',
        'test_leader_stage3.Defer.test_the_analysis_check_gets_the_deferred_rows',
    ],
    'TP1': [
        'test_e2e_stage3.PrReviewEndToEnd.test_tp1_a_change_request_reruns_fix_and_updates_the_same_pr',
        'test_s3_pr_review.AfterPr.test_tp1_a_change_request_reruns_and_updates_the_same_pr',
        'test_leader_stage3.PrReview.test_calls',
    ],
    'TP2': [
        'test_s3_pr_review.AfterPr.test_tp2_human_commits_are_fast_forwarded_and_verified_again',
        'test_leader_stage3.PrReview.test_only_commits',
        'test_gitops.FastForward.test_remote_ahead_is_fast_forwarded',
    ],
    'TP3': [
        'test_s3_pr_review.AfterPr.test_tp3_a_diverged_branch_stops',
        'test_gitops.FastForward.test_diverged_is_refused',
    ],
    'TP4': [
        'test_s3_pr_review.Dismiss.test_tp4_the_block_is_dismissed_and_changed_code_is_judged_again',
        'test_prbody.DismissedSection.test_section',
    ],
    'TP5': [
        'test_s3_pr_review.Dismiss.test_tp5_nothing_else_can_be_dismissed',
        'test_s3_pr_review.Dismiss.test_tp5_the_leaders_turn_and_a_moved_head_refuse',
        'test_s3_pr_review.DismissRules.test_rules',
        'test_leader_stage3.PrReview.test_rules',
    ],
    'TG1': [
        'test_golden.Golden.test_tg1_a_change_with_its_reason',
        'test_prbody.GoldenLedger.test_table_and_config_row',
    ],
    'TG2': [
        'test_golden.Golden.test_tg2_a_change_without_a_reason',
    ],
    'TG3': [
        'test_golden.Golden.test_tg3_a_comparison_config_row_needs_a_reason_too',
        'test_prbody.GoldenLedger.test_table_and_config_row',
        'test_rules.V1TestChangeReview.test_verification_path_adds_the_check_and_resets_a_done_review',
    ],
    'TG4': [
        'test_runner_stage3.Frozen.test_tr3_tg4_golden_and_comparison_config',
    ],
    'TX1': [
        'test_leader_stage3.Stage3Table.test_free_text_never_changes_the_verdict',
        'test_s3_discoveries.Blocking.test_tx1_the_texts_never_decide',
        'test_catalog.Requests.test_notes_do_not_matter',
        'test_prbody.FollowupItems.test_tx1_free_text_changes_bodies_not_calls',
    ],
    'TX2': [
        'test_scenario_stage3.EngineStage.test_engine_stage_is_3_and_the_earlier_stages_are_passed_explicitly',
        'test_scenario_stage1.Index.test_every_scenario_of_section_5_2_has_tests',
        'test_scenario_stage2.Index.test_every_stage_2_scenario_of_section_5_2_has_tests',
        'test_contracts.Stage3Tables.test_engine_stage_and_earlier_tables_unchanged',
        'test_templates.Stage3Templates.test_stage_1_2_views_are_what_they_were',
    ],
    'TX3': [
        'test_scenario_stage3.Z4.test_a_work_output_glob_grants_no_write_and_the_control_files_stay_denied',
        'test_s3_requests.Requests.test_tc1_tc3_tc4_tc11_one_revision_for_all_requests_of_one_step',
        'test_s3_plan.PlanAnswer.test_one_revision_with_source_and_stage3_state',
        'test_s3_discoveries.Blocking.test_tf2_k1_after_the_developer_a_fix_step_goes_in_and_comes_back',
        'test_procedure.Stage3WorkOutputs.test_globs_that_name_a_control_file_stay_refused',
    ],
    'TX4': [
        'test_s3_requests.Requests.test_tc5_tx4_the_fourth_request_is_the_leaders',
        'test_s3_pr_review.AfterPr.test_tp1_a_change_request_reruns_and_updates_the_same_pr',
        'test_contracts.Stage3Tables.test_stage3_answer_table',
        'test_s3_requests.Pure.test_the_removal_and_limit_situations_have_a_leader_and_are_counted',
    ],
}

IDS = ([f"TY{i}" for i in range(1, 6)] + [f"TB{i}" for i in range(1, 7)] + [f"TR{i}" for i in range(1, 10)]
       + [f"TC{i}" for i in range(1, 12)] + [f"TF{i}" for i in range(1, 12)] + [f"TI{i}" for i in range(1, 7)]
       + [f"TM{i}" for i in range(1, 9)] + [f"TS{i}" for i in range(1, 4)] + [f"TP{i}" for i in range(1, 6)]
       + [f"TG{i}" for i in range(1, 5)] + [f"TX{i}" for i in range(1, 5)])


class Index(unittest.TestCase):
    def test_every_stage_3_scenario_of_section_5_2_has_tests(self):
        self.assertEqual(len(IDS), 72)
        for sid in IDS:
            with self.subTest(scenario=sid):
                self.assertTrue(SCENARIOS.get(sid), f"{sid} has no test")
        self.assertEqual(set(SCENARIOS), set(IDS))

    def test_every_named_test_exists(self):
        loader = unittest.TestLoader()
        for sid, names in SCENARIOS.items():
            for n in names:
                with self.subTest(scenario=sid, test=n):
                    suite = loader.loadTestsFromName(T + n)
                    self.assertEqual(suite.countTestCases(), 1, n)
                    self.assertNotIn("_FailedTest", type(next(iter(suite))).__name__, n)


class EngineStage(unittest.TestCase):
    """E36 / Q4: the engine is stage 3; every stage-1 / stage-2 path names its stage, so the stage-3 data and
    texts (the default of instructions.* is defaults.ENGINE_STAGE) never reach an earlier engine."""

    def test_engine_stage_is_3_and_the_earlier_stages_are_passed_explicitly(self):
        self.assertGreaterEqual(defaults.ENGINE_STAGE, 3, "4 since the stage-4 integration (VZ, H23)")
        ops = [s.get("op") for s in instructions.load_default_template("feature")["steps"]]
        self.assertIn(codes.OpKind.CREATE_FOLLOWUPS.value, ops)
        for stage in (1, 2):
            ops = [s.get("op") for s in instructions.load_default_template("feature", stage=stage)["steps"]]
            self.assertNotIn(codes.OpKind.CREATE_FOLLOWUPS.value, ops)
        src = inspect.getsource(driver)
        for call in ("load_start_procedure()", "build_instruction(step, fields, toolchain=_toolchain_hint(env) if "
                                               "work else None)"):
            self.assertNotIn(call, src)
        self.assertIn("stage=r.stage)", inspect.getsource(leader._instruction))


class Q4Wiring(unittest.TestCase):
    def test_every_developer_step_takes_the_pr_review_file(self):
        # E31: after `resume --pr-review` the developer step that reruns gets in/pr-review.md (B2's note to A)
        dev = {"feature": "implement", "bug": "fix", "refactor": "transform", "refactor-net": "transform",
               "safety-net": "safety-net"}
        for name, sid in dev.items():
            with self.subTest(template=name):
                steps = {s["id"]: s for s in instructions.load_default_template(name, stage=3)["steps"]}
                self.assertIn("in:pr-review.md", steps[sid]["inputs"])
        early = instructions.load_default_template("feature", stage=2)["steps"]
        self.assertFalse(any("in:pr-review.md" in s.get("inputs", ()) for s in early))

    def test_an_evidence_template_needs_the_test_command(self):
        from gxengine import repoconfig

        class Env:
            pass
        bug = instructions.load_default_template("bug", stage=3)
        for cfg, want in ((Z.config3(), []), (dict(Z.config3(), commands={k: v for k, v in Z.config3()["commands"].items()
                                                                          if k != "test"}), 1)):
            env = Env()
            env.config = repoconfig.RepoConfig(cfg)
            env.commands = env.config.command_names()
            got = driver._evidence_problems(env, bug)
            self.assertEqual(len(got), 0 if want == [] else 1, got)


class Z1SrtTempFolder(unittest.TestCase):
    def test_the_folder_names_the_repository_and_the_process(self):
        a = driver.srt_run_id("acme/app", 42, 1, pid=4321)
        self.assertRegex(a, r"^42-1-[0-9a-f]{6}-4321$")
        self.assertNotEqual(a, driver.srt_run_id("acme/other", 42, 1, pid=4321))       # another repository
        self.assertNotEqual(a, driver.srt_run_id("acme/app", 42, 1, pid=4322))         # another engine process
        self.assertEqual(a, driver.srt_run_id("acme/app", 42, 1, pid=4321))            # stable within one run
        self.assertTrue(driver.srt_run_id("acme/app", 42, 1).endswith(f"-{os.getpid()}"))
        for issue, attempt, pid in ((42, 1, 4321), (99999, 999, 4194304)):
            rid = driver.srt_run_id("acme/app", issue, attempt, pid=pid)
            self.assertLessEqual(len(rid), 24)
            t = pathsmod.srt_tmpdir(rid)                    # the paths contract (srt's unix socket stays short)
            self.assertLessEqual(len(t), render.SRT_TMPDIR_MAX)


V18_RESUMED = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0022951900000000003,
               "num_turns": 2, "usage": {"output_tokens": 523},
               "model_usage_since_last_result": {"claude-haiku-5-5": {"outputTokens": 523, "costUSD": 0.00059833}},
               "modelUsage": {"claude-haiku-5-5": {"outputTokens": 1274, "costUSD": 0.0022951900000000003}}}


class Z2ResumedCost(unittest.TestCase):
    """V18 §6: a --resume call's total_cost_usd / modelUsage are the session's cumulative totals."""

    def test_a_resumed_call_counts_only_its_own_cost(self):
        self.assertAlmostEqual(streamjson.call_cost(V18_RESUMED, resumed=True), 0.00059833)
        self.assertAlmostEqual(streamjson.cost_and_tokens(V18_RESUMED, resumed=True)["cost_usd"], 0.00059833)
        self.assertAlmostEqual(streamjson.call_cost(V18_RESUMED), 0.0022951900000000003)     # a new session
        two = dict(V18_RESUMED, model_usage_since_last_result={"a": {"costUSD": 0.25}, "b": {"costUSD": 0.5}})
        self.assertAlmostEqual(streamjson.call_cost(two, resumed=True), 0.75)
        for since in (None, {}, {"a": {"outputTokens": 1}}, {"a": {"costUSD": "1"}}):
            with self.subTest(since=since):
                # never the cumulative value counted again: unknown → None ("session cost not recorded")
                self.assertIsNone(streamjson.call_cost(dict(V18_RESUMED, model_usage_since_last_result=since),
                                                       resumed=True))

    def test_the_budget_end_of_a_resumed_error_is_its_own_cost(self):
        err = dict(V18_RESUMED, subtype="error_during_execution", is_error=True, total_cost_usd=9.0)
        self.assertTrue(session._budget_reached(err, 5.0))                     # a new session: its total
        self.assertFalse(session._budget_reached(err, 5.0, resumed=True))      # resumed: only this call's $0.0006

    def test_run_session_of_a_resumed_developer(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = a_layout.Layout(tmp)
            scn = lay.scenario("resumed.json", {
                "format": 1, "description": "a resumed developer", "stream": Z.STREAM, "init_from_argv": True,
                "structured_output": Z.work_result(), "actions": [],
                "result": {k: V18_RESUMED[k] for k in ("total_cost_usd", "model_usage_since_last_result",
                                                       "modelUsage")}})
            for resume, want in (("abc-123", 0.00059833), (None, 0.0022951900000000003)):
                with self.subTest(resume=resume):
                    inp = lay.role_input("implement", "developer", resume=resume)
                    r = session.run_session(inp, lay.attempt_dir("implement", 1 if resume is None else 2),
                                            lay.env(scenarios=[scn]), claude_bin=fakes.FAKE_CLAUDE)
                    self.assertAlmostEqual(r.cost["cost_usd"], want)


class Z3(unittest.TestCase):
    def test_tm5_the_real_ladder_keeps_the_resume_for_an_effort_raise(self):
        self.assertIs(ladder.EFFORT_CHANGE_RESUMES, True)
        step = procedure.Step({"id": "fix", "role": "developer", "inputs": [], "outputs": []})
        base = ladder.base_choice(step, 3, {})
        models, efforts = defaults.ALLOWED_MODELS, defaults.ALLOWED_EFFORTS
        effort_only = ladder.raised(base, defaults.RAISE_EFFORT_AT, models, efforts)
        self.assertTrue(effort_only["escalation"]["raised"]["effort"])
        self.assertFalse(effort_only["escalation"]["raised"]["model"])
        self.assertTrue(ladder.may_resume(base, effort_only))                   # Z3: --resume stays
        model_too = ladder.raised(base, defaults.RAISE_MODEL_AT, models, efforts)
        if model_too["model"] != base["model"]:
            self.assertFalse(ladder.may_resume(base, model_too))                # another model: a new session
        st = {"session_id": "sid", "resume_count": 0}
        self.assertEqual(session.choose_resume("developer", st, base["model"], base["model"],
                                               effort_only["effort"], base["effort"]), "sid")


class Z4(unittest.TestCase):
    """B1's narrowing (stage ≥ 3): a WORK step's output glob may have `*` / `**` folder segments. It is safe
    because a work role's outputs never widen its writes: the rendered sandbox / permissions are the same with
    or without them, and the control-file denies are in both (the security boundary is the render)."""

    def test_a_work_output_glob_grants_no_write_and_the_control_files_stay_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = a_layout.Layout(tmp)
            plain = render.render_settings(lay.role_input("reproduce", "developer", outputs=[]))
            globbed = render.render_settings(lay.role_input("reproduce", "developer",
                                                            outputs=["tests/**/test_*.py", "test/**/*_test.dart"]))
            self.assertEqual(plain, globbed)
            deny = globbed["sandbox"]["filesystem"]["denyWrite"]
            wt = lay.wt
            for g in ("CLAUDE.md", ".claude", "AGENTS.md", "docs/specs/42/procedure.yaml"):
                self.assertTrue(any(d.startswith(wt) and g in d for d in deny), g)
            perms = json.dumps(globbed["permissions"]["deny"])
            self.assertIn("CLAUDE.md", perms)
            # a judge's outputs ARE its write scope: the old rule stays there
            judge = render.render_settings(lay.role_input("design", "tech-lead", outputs=["docs/specs/42/design.md"]))
            self.assertIn(os.path.join(wt, "docs/specs/42/design.md"), judge["sandbox"]["filesystem"]["allowWrite"])
        # the grammar side (B1, procedure.template_problems — what the engine and the conversion tool use): such
        # a test-code glob is fine for the work step of the bug template, a control file or folder never is
        start = instructions.load_start_procedure(3)
        bug = instructions.load_default_template("bug", stage=3)
        names = list(Z.config3()["commands"])

        def problems(test_code):
            globs = {"test-code": test_code, "safety-net": ["tests/test_safety_net_*.py"]}
            return [p for p in procedure.template_problems(start, bug, 42, names, globs, stage=3) if "control file" in p]
        self.assertEqual(problems(["tests/**/test_*.py", "test/**/*_test.dart"]), [])
        for bad in ("test/**", "**/*.md", ".claude/**/*.py", "test/**/CLAUDE.md", "docs/specs/42/*.yaml"):
            with self.subTest(bad=bad):
                self.assertTrue(problems([bad]), bad)


def _env_stub(tmp, stage=3):
    class Env:
        pass
    env = Env()
    env.stage = stage
    env.paths = pathsmod.EnginePaths(os.path.join(tmp, "gld"), "acme/app", 42)
    store._root(env.paths)
    env.state = {"included_fixes": []}
    env.log = lambda event, **f: store.append_log(env.paths, event, **f)
    return env


def _fix(n, step="design"):
    return {"id": f"F{n}", "from_step": step, "from_attempt": 1, "role": "tech-lead", "kind": "bug",
            "where": f"src/f{n}.py", "note": f"fix {n}", "handled_by": "implement", "verdict": None}


class Z5(unittest.TestCase):
    def test_an_out_of_scope_fix_leaves_the_issue_and_its_number_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env_stub(tmp)
            env.state["included_fixes"] = [_fix(1), _fix(2)]
            for f in env.state["included_fixes"]:
                env.log(codes.LogEvent.DISCOVERY.value, data={"id": f["id"], "kind": f["kind"]})
            res = leader.LeaderResult(called=True, answer="rerun", step="implement", reason="real-defect", note="undo F2",
                                      extra={"included_fixes": [{"id": "F1", "verdict": "keep"},
                                                                {"id": "F2", "verdict": "out-of-scope"}]})
            self.assertTrue(driver._record_fix_verdicts(env, res))
            self.assertEqual([(f["id"], f["verdict"]) for f in env.state["included_fixes"]], [("F1", "keep")])
            self.assertEqual([f["id"] for f in driver._excluded_fixes(env)], ["F2"])
            self.assertEqual(driver._last_fix_number(env), 2)                  # the next one is F3, never F2
            text = driver._blocking_discoveries(env, "implement")
            self.assertIn("Put out of scope by the done-gate", text)
            self.assertIn("F2 (bug", text)
            # the next done-gate judges F1 only: an approve that keeps it is an approval
            ok = leader.LeaderResult(called=True, answer="approve", step=None, reason="acceptance-met", note="",
                                     extra={"included_fixes": [{"id": "F1", "verdict": "keep"}]})
            self.assertTrue(driver._record_fix_verdicts(env, ok))


class Z6(unittest.TestCase):
    def test_a_stage_2_analysis_is_no_stage_3_analysis(self):
        # the precondition of Z6 (test_s3_plan…test_an_unreadable_analysis_goes_back_to_analyze_once_z6): an
        # analysis.md written by a stage-2 engine has no safety_net field
        text = Z.W.ANALYSIS
        self.assertEqual(acparse.parse_analysis(text, stage=2)["safety_net"], "none")
        with self.assertRaises(acparse.AcError):
            acparse.parse_analysis(text, stage=3)
        self.assertIsNone(acparse.parse_analysis(Z.analysis3("feature"), stage=3).get("missing"))


class Z7(unittest.TestCase):
    def test_a_lone_surrogate_in_result_json_is_passed_on_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env_stub(tmp)

            class Proc:
                step_ids = ["review-audit"]

                def step(self, sid):
                    return procedure.Step({"id": sid, "role": "auditor", "inputs": [], "outputs": [],
                                           "checks": ["diff-review"]})
            env.proc = Proc()
            store.write_result(env.paths, "review-audit", 1, {
                "verdict": "block", "findings": [{"severity": "blocker", "file": "src/a.py", "line": 1,
                                                  "text": "bad \ud800 byte"}]})
            text = driver._role_findings(env, "review-audit", 1)
            self.assertIn("\\ud800", text)
            text.encode("utf-8")                                   # nothing left that cannot be written


if __name__ == "__main__":
    unittest.main()
