"""VZ — the stage-4 fixed scenarios (stage-4 scope §5.2, the T bundle) as one suite, and what the integration
pinned.

`SCENARIOS` maps every §5.2 stage-4 id to the tests that assert its expected result (the stage-1 to stage-3 way:
test_scenario_stage{1,2,3}.SCENARIOS). `Index` fails on a missing id or a renamed / deleted test. The end to end
run with the real engine as child processes is tests/test_e2e_stage4.py (TX5); the rest are the branches'
unit and flow tests (A: the supervisor with doubles for every seam, the member engine in process; B: init,
the base check, references, E9-2, the heavy-run lock, the PR sections, mutations).

Notes on the index (the scope text against what is built):
  - TD3: "the eight rows of §2.3" — review-q0 D4 fixed one order over this run's outcomes and the GitHub facts;
    test_the_fact_table walks the rows, test_the_order_of_the_rules the order.
  - TS5: U1 = (가) (user decision A14) — a squash-only repository stacks as a draft when the plan says
    `squash-sync` / `human-override`; `dep-unmerged` is left for unknown settings, `merge-commit-forbidden` and
    a plan older than the settings.
  - TL4 / TT1: the label and the allowed-file list are also seen by the real engine in TX5 / test_testchange.
  - TT1: `test-change-review` is added by rules.py for any changed verification path — the allowance only
    narrows `frozen_violations`, so the rules test is the one that shows the check is still there.
  - TX3: the stage-1 to stage-3 suites run at their own stage (D21, E36); their Index tests are named, plus the
    stage-4 tests that show a stage-3 engine does none of it.

VZ decisions (the integration):
  VZ1 member-end data.cost_usd is this run's spend of the member (collect.py adds runs up); sprint.json keeps the
      Issue's total.
  VZ2 from stage 4 a reference may be followed by a letter of another script (`#104이`, `#102~104가`).
  VZ3 the base check keeps its srt canary as a child process (`engine.py canary --srt-only`), no
      ("basecheck", "canaryrun") pair in SAME_LAYER (B's optional request).
"""

import inspect
import os
import re
import unittest

from gxengine import basecheck, codes, defaults
from tests import c_world as W

T = "tests."

SCENARIOS = {
    # TD — the table and the graph
    "TD1": ["test_sprintdag.Table.test_six_columns", "test_sprintdag.Table.test_the_old_five_columns_are_read_in_number_order",
            "test_sprintdag.Table.test_refused"],
    "TD2": ["test_sprintdag.Parity.test_order", "test_sprintdag.Parity.test_hash",
            "test_sprintdag.Parity.test_the_stored_hash_is_not_part_of_the_hash"],
    "TD3": ["test_sprintdag.DepState.test_the_fact_table", "test_sprintdag.DepState.test_the_order_of_the_rules",
            "test_sprintdag.DepState.test_every_input_has_exactly_one_answer_and_blocked_is_never_startable",
            "test_sprint.Closed.test_a_dependency_that_is_closed_beats_this_runs_outcome"],
    "TD4": ["test_sprint.Round.test_a_stop_blocks_its_dependants_only", "test_sprintdag.DepState.test_the_order_of_the_rules"],
    "TD5": ["test_sprintdag.Table.test_depends_on_lines_mean_nothing"],
    "TD6": ["test_sprintdag.Order.test_a_cycle_is_refused"],
    # TR — one round of the supervisor
    "TR1": ["test_sprint.Round.test_all_done", "test_sprint_cli.Commands.test_run_in_the_foreground"],
    "TR2": ["test_sprint.Round.test_a_stop_blocks_its_dependants_only",
            "test_e2e_stage4.SprintEndToEnd.test_tx5_two_members_stacked_one_stops_a_human_answers_the_next_run_finishes"],
    "TR3": ["test_sprint.Round.test_every_line_of_the_outcome_table"],
    "TR4": ["test_sprint.Round.test_a_run_again_starts_only_what_is_not_done",
            "test_sprint_cli.RealMember.test_a_stop_then_a_human_then_the_next_run",
            "test_e2e_stage4.SprintEndToEnd.test_tx5_two_members_stacked_one_stops_a_human_answers_the_next_run_finishes"],
    "TR5": ["test_sprint.Round.test_a_dead_member_is_failed_and_continued_without_an_answer"],
    "TR6": ["test_sprint.Round.test_a_boundary_stop_halts", "test_sprint.Round.test_a_refused_self_check_halts_by_its_log_code"],
    "TR7": ["test_sprint.Round.test_a_killed_supervisor"],
    "TR8": ["test_sprint.Round.test_term_ends_after_the_running_member", "test_sprint.Window.test_a_signal_while_waiting"],
    "TR9": ["test_sprint.Round.test_three_failed_markers_halt_but_the_member_ends", "test_sprint.Round.test_two_failed_markers_do_not"],
    "TR10": ["test_sprint.Round.test_changed_engine_files_halt", "test_sprint.Small.test_engine_sha256"],
    # TS — base and stack
    "TS1": ["test_sprint_member.StartInput.test_a_stacked_member", "test_sprint_cli.RealMember.test_a_stacked_member_end_to_end",
            "test_prbody.Stage4Sections.test_the_stack_block_comes_first_and_has_the_markers",
            "test_e2e_stage4.SprintEndToEnd.test_tx5_two_members_stacked_one_stops_a_human_answers_the_next_run_finishes"],
    "TS2": ["test_sprint.Base.test_a_merged_dependency",
            "test_sprint_member.StartInput.test_the_default_branch_is_the_remotes_and_no_local_ref_moves"],
    "TS3": ["test_sprint.Base.test_the_head_of_the_pull_request_must_be_what_was_fetched",
            "test_sprint_cli.RealMember.test_a_pushed_commit_the_pull_request_does_not_have_yet"],
    "TS4": ["test_sprint_member.StartInput.test_the_default_branch_is_the_remotes_and_no_local_ref_moves",
            "test_sprint_member.StartInput.test_a_humans_dev_is_unchanged",
            "test_sprint_member.Git.test_fetch_branches_moves_remote_tracking_refs_only"],
    "TS5": ["test_sprint.Base.test_no_stacking_here", "test_sprintdag.Base.test_effective_stack_reason"],
    "TS6": ["test_sprint.Base.test_a_remote_branch", "test_sprint_member.RemoteBranch.test_a_leftover_branch_refuses_before_anything_is_paid",
            "test_sprint_member.RemoteBranch.test_an_open_pull_request_refuses"],
    "TS7": ["test_sprint_member.StartInput.test_control_files_and_specs_of_the_stack_base_are_not_this_issues",
            "test_sprint.Base.test_a_control_file_in_the_stack_base", "test_sprint_cli.RealMember.test_a_control_file_in_the_dependencys_branch"],
    "TS8": ["test_sprint_member.StartInput.test_resume_opens_the_pr_on_the_recorded_branch"],
    "TS9": ["test_sprint_member.StartInput.test_a_start_input_is_refused", "test_stage4_wiring.Start.test_the_options_check_themselves"],
    # TL — locks and the label
    "TL1": ["test_sprint.Locks.test_a_member_a_human_runs", "test_sprint.Locks.test_exit_3_with_this_issues_lock"],
    "TL2": ["test_sprint.Locks.test_another_issue_holds_the_repository", "test_sprint.Locks.test_four_hours_is_repo_busy"],
    "TL3": ["test_sprint.Locks.test_a_second_supervisor", "test_sprint.Locks.test_another_host",
            "test_sprint_member.SprintLock.test_one_supervisor_per_repository"],
    "TL4": ["test_sprint_member.Label.test_on_while_a_human_is_needed_off_when_it_goes_on",
            "test_sprint_member.Label.test_a_failed_write_is_a_warning",
            "test_e2e_stage4.SprintEndToEnd.test_tx5_two_members_stacked_one_stops_a_human_answers_the_next_run_finishes"],
    # TQ — quota
    "TQ1": ["test_sprint.Quota.test_a_member_that_waits_inside_is_done"],
    "TQ2": ["test_sprint.Quota.test_past_four_hours_the_whole_run_waits"],
    "TQ3": ["test_sprint.Quota.test_the_next_run_after_the_reset_reruns_it",
            "test_sprint_member.QuotaRerun.test_after_the_reset_it_reruns_as_the_sprint",
            "test_stage4_wiring.SprintAnswer.test_the_rerun_is_logged_as_the_sprints_and_is_no_return"],
    "TQ4": ["test_sprint.Quota.test_the_next_run_before_the_reset_starts_nothing",
            "test_sprint_member.QuotaRerun.test_before_the_reset_nothing_changes"],
    "TQ5": ["test_sprint.Quota.test_another_stop_is_never_rerun",
            "test_sprint_member.QuotaRerun.test_a_note_that_says_quota_is_no_quota_stop"],
    # TW — the window
    "TW1": ["test_sprintdag.Window.test_format", "test_sprint_cli.Commands.test_refused_before_detaching"],
    "TW2": ["test_sprintdag.Window.test_inside"],
    "TW3": ["test_sprint.Window.test_waits_only_before_a_new_member"],
    "TW4": ["test_sprint.Window.test_a_run_again_inherits_the_window"],
    # TB — the base check
    "TB1": ["test_basecheck.Green.test_tb1_every_repository_command_setup_first_and_a_record",
            "test_basecheck.Green.test_tb1_the_same_pair_is_not_run_again", "test_sprint.BaseCheck.test_the_request_and_the_record",
            "test_e2e_stage4.SprintEndToEnd.test_tx5_two_members_stacked_one_stops_a_human_answers_the_next_run_finishes"],
    "TB2": ["test_basecheck.Red.test_tb2_red_twice", "test_basecheck.Red.test_tb2_red_then_green_is_flaky_and_green",
            "test_sprint.BaseCheck.test_red_starts_nothing", "test_sprint.BaseCheck.test_flaky_goes_on"],
    "TB3": ["test_basecheck.Red.test_tb3_a_dirty_tree_is_red_and_not_run_again"],
    "TB4": ["test_basecheck.Problems.test_tb4_no_worktree", "test_sprint.BaseCheck.test_a_fact_that_could_not_be_collected_is_never_allowed"],
    "TB5": ["test_sprint.BaseCheck.test_a_human_may_allow_a_red_base"],
    # TI — init
    "TI1": ["test_convert_config.InitWithStableSettings.test_ti1_flutter_and_node_shapes",
            "test_convert_config.InitWithStableSettings.test_the_stage_3_conversion_is_untouched"],
    "TI2": ["test_convert_config.InitWithoutStableSettings.test_ti2_node", "test_convert_config.InitWithoutStableSettings.test_ti2_flutter",
            "test_convert_config.InitWithoutStableSettings.test_ti2_python",
            "test_convert_config.InitWithStableSettings.test_every_command_names_its_source"],
    "TI3": ["test_convert_config.InitWithoutStableSettings.test_ti3_no_command_text_from_nowhere"],
    "TI4": ["test_convert_config.InitWithoutStableSettings.test_ti4_an_unreadable_workflow_is_reported_not_guessed"],
    "TI5": ["test_initconfig.Compare.test_ti5_nothing_is_written"],
    "TI6": ["test_initconfig.Propose.test_ti6_the_questions", "test_convert_config.InitWithoutStableSettings.test_ti6_nothing_to_ask",
            "test_initconfig.Contract.test_only_the_eleven_questions_exist"],
    "TI7": ["test_initconfig.Answers.test_ti7_refused_answers_change_nothing"],
    "TI8": ["test_initconfig.Check.test_ti8_red_base_no_canary_no_write", "test_initconfig.Check.test_ti8_a_failing_canary_refuses_write"],
    "TI9": ["test_initconfig.Write.test_ti9_existing_settings_are_never_touched"],
    "TI10": ["test_initconfig.AfterRed.test_only_the_exceptions_that_matter_are_asked",
             "test_initconfig.AfterRed.test_a_rejected_one_stays_out"],
    "TI11": ["test_initconfig.Propose.test_ti11_missing_roles_are_told_and_nothing_is_made",
             "test_convert_config.InitQuestions.test_ti11_roles_are_reported_never_made"],
    # A15 (2026-11-26, VB10): the answers that put a human's judgment back
    "TI12": ["test_initconfig.HumanJudgment.test_a_human_adds_a_rule_line",
             "test_initconfig.HumanJudgment.test_a_rule_line_that_is_not_one_is_refused",
             "test_initconfig.HumanJudgment.test_a_human_narrows_a_test_glob",
             "test_initconfig.HumanJudgment.test_a_wider_or_unproved_glob_is_refused",
             "test_initconfig.HumanJudgment.test_follow_ups_are_really_created_unless_a_human_asks",
             "test_globs.Covers.test_a_proof_is_never_wrong", "test_initconfig.Compare.test_a_wider_test_glob_is_loosened"],
    "TI13": ["test_initconfig.Vw1WordApp.test_the_fixture_asks_what_vw1_was_asked",
             "test_initconfig.Vw1WordApp.test_without_the_new_answers_it_is_looser_as_in_vw1",
             "test_initconfig.Vw1WordApp.test_the_answers_leave_no_difference",
             "test_initconfig.Vw1WordApp.test_one_answer_less_is_one_line_looser"],
    # TF — references
    "TF1": ["test_issuerefs.Ranges.test_tf1_every_written_form", "test_issuerefs.Ranges.test_the_sentence_of_service_123",
            "test_issuerefs.Ranges.test_a_particle_after_a_single_reference"],
    "TF2": ["test_issuerefs.Ranges.test_tf2_anything_else_is_as_before", "test_issuerefs.Ranges.test_below_stage_4_nothing_is_expanded"],
    # TT — E9-2
    "TT1": ["test_testchange.Apply.test_tt1_the_state_and_the_log", "test_testchange.Frozen.test_tt1_an_allowed_content_change_passes",
            "test_rules.V1TestChangeReview.test_verification_path_adds_the_check_and_resets_a_done_review",
            "test_prbody.Stage4Sections.test_allowed_files_are_decisions_to_review",
            "test_stage4_wiring.TestChange.test_the_driver_hands_it_the_resume_and_logs_after_the_answer"],
    "TT2": ["test_testchange.Frozen.test_tt2_another_file_is_still_a_violation", "test_testchange.Frozen.test_tt2_deleted_renamed_retyped_remade"],
    "TT3": ["test_testchange.Args.test_tt3_anything_else_is_refused_before_detaching", "test_testchange.Apply.test_tt3_files_that_cannot_be_allowed",
            "test_testchange.Apply.test_tt3_a_safety_net_file_is_never_allowed", "test_testchange.Apply.test_a_reason_is_needed_here_too"],
    "TT4": ["test_testchange.Args.test_tt4_a_leader_has_no_field_for_it"],
    # TH — the heavy-run lock
    "TH1": ["test_runner.HeavyRuns.test_th1_a_command_waits_for_the_other_engine", "test_runner.HeavyRuns.test_th1_two_commands_never_overlap"],
    "TH2": ["test_runner.HeavyRuns.test_th2_the_wait_is_not_in_the_time_limit"],
    "TH3": ["test_runner.HeavyRuns.test_th3_a_dead_holder_frees_the_lock"],
    "TH4": ["test_runner.HeavyRuns.test_th4_a_plugin_check_does_not_wait"],
    # TX — principles
    "TX1": ["test_sprint_cli.NoBypass.test_no_executed_path_has_the_flag", "test_sprint.Round.test_the_child_command",
            "test_sprint_cli.RealMember.test_a_stacked_member_end_to_end",
            "test_e2e_stage4.SprintEndToEnd.test_tx5_two_members_stacked_one_stops_a_human_answers_the_next_run_finishes"],
    "TX2": ["test_sprint.Round.test_same_facts_other_words_same_run"],
    "TX3": ["test_scenario_stage1.Index.test_every_named_test_exists", "test_scenario_stage2.Index.test_every_named_test_exists",
            "test_scenario_stage3.Index.test_every_named_test_exists",
            "test_scenario_stage4.EngineStage.test_engine_stage_is_4_and_stage_3_has_none_of_it",
            "test_stage4_wiring.Cli.test_every_stage4_command_is_refused_before_stage_4",
            "test_stage4_wiring.Runs.test_stage3_gets_none_of_it", "test_sprint_member.Label.test_stage_3_has_none",
            "test_sprint_member.RemoteBranch.test_stage_3_does_not_look"],
    "TX4": ["test_contracts.Stage4Tables.test_repo_config_refuses_the_llm_settings",
            "test_scenario_stage4.Settings.test_the_engine_never_reads_harness_json"],
    "TX5": ["test_e2e_stage4.SprintEndToEnd.test_tx5_two_members_stacked_one_stops_a_human_answers_the_next_run_finishes"],
}

IDS = ([f"TD{i}" for i in range(1, 7)] + [f"TR{i}" for i in range(1, 11)] + [f"TS{i}" for i in range(1, 10)]
       + [f"TL{i}" for i in range(1, 5)] + [f"TQ{i}" for i in range(1, 6)] + [f"TW{i}" for i in range(1, 5)]
       + [f"TB{i}" for i in range(1, 6)] + [f"TI{i}" for i in range(1, 14)] + [f"TF{i}" for i in range(1, 3)]
       + [f"TT{i}" for i in range(1, 5)] + [f"TH{i}" for i in range(1, 5)] + [f"TX{i}" for i in range(1, 6)])


class Index(unittest.TestCase):
    def test_every_stage_4_scenario_of_section_5_2_has_tests(self):
        self.assertEqual(len(IDS), 71)          # 69 + TI12 · TI13 (A15, VB10)
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
    """H23 / VZ: the engine is stage 4; a stage-3 engine refuses every stage-4 command and argument."""

    def test_engine_stage_is_4_and_stage_3_has_none_of_it(self):
        import io
        from gxengine import cli
        self.assertEqual(defaults.ENGINE_STAGE, codes.STAGE4)
        for argv in (["sprint", "status", "--repo", "o/n", "--tracker", "7"], ["init", "doctor", "--repo", "o/n"],
                     ["base-check", "--repo", "o/n"]):
            out = io.StringIO()
            with self.subTest(argv=argv[0]):
                self.assertEqual(cli.main(argv, environ={"GLD_ENGINE_HOME": "/nonexistent-gx"}, out=out, stage=3), 4)
                self.assertIn("exists from stage 4", out.getvalue())


class Settings(unittest.TestCase):
    def test_the_engine_never_reads_harness_json(self):
        """TX4 / H13: the LLM commands' settings file is named once (defaults), and no engine module reads it."""
        pkg = os.path.join(W.ENGINE, "gxengine")
        hits = []
        for f in sorted(os.listdir(pkg)):
            if f.endswith(".py"):
                with open(os.path.join(pkg, f), encoding="utf-8") as fh:
                    text = fh.read()
                if re.search(r"harness\.json|HARNESS_SETTINGS", text):
                    hits.append(f)
        # readiness T1 R4-14: channel.py names it once, for whether a channel is set up (os.path.isfile, never read)
        # readiness T2 P4: initharness WRITES it once (init migrate, from 0.98.x settings) and asks only whether it is
        # there (os.path.lexists) — never reads it
        self.assertEqual(hits, ["channel.py", "defaults.py", "initharness.py"])
        with open(os.path.join(pkg, "initharness.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertFalse(re.search(r"(read\w*|open|load\w*)\([^)]*HARNESS_SETTINGS", text), "initharness reads harness.json")
        with open(os.path.join(pkg, "channel.py"), encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if re.search(r"harness\.json|HARNESS_SETTINGS", ln)]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("SETTINGS_FILES = "), lines)
        self.assertNotEqual(defaults.HARNESS_SETTINGS, defaults.ENGINE_SETTINGS)


class Vz3(unittest.TestCase):
    def test_the_base_check_runs_its_srt_canary_as_a_child(self):
        """VZ3: no canaryrun import in basecheck — the free canary is `engine.py canary --srt-only`, the human's path."""
        from tests.test_contracts import internal_imports
        deps, _ = internal_imports(inspect.getsourcefile(basecheck))
        self.assertNotIn("canaryrun", deps)
        self.assertIn('"--srt-only"', inspect.getsource(basecheck._srt_canary))


if __name__ == "__main__":
    unittest.main()
