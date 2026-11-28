"""U20 — the stage-1 fixed scenarios (scope §5.2) as one suite (P4).

`SCENARIOS` maps every §5.2 id to the tests that assert its expected result (the table in
stage1/p4-scenarios.md is generated from it). `Index` keeps the map honest: every id of
§5.2 is present, every named test exists, and nothing maps to a test that was renamed or
deleted. The end-to-end classes below add the scenarios that had no test through the REAL
engine units yet (driver.Units() defaults, fake claude, fake gh executable, bare remote,
temp repository, real srt): C1 through the whole stack (result thrown away, needs_human,
no on_fail, nothing reverted), S2 through the driver (quota wait ≤ 4 h then the same step,
> 4 h a stop) and S7 for runs (the srt canary gate in front of every run).
"""

import json
import os
import time
import unittest

from gxengine import canaryrun, codes, driver, streamjson
from tests import z_world as Z

T = "tests."

SCENARIOS = {
    # C — control files: security boundary → result thrown away, needs_human, no on_fail, no revert
    "C1": ["test_results.C.test_c1_commit", "test_scenario_stage1.ControlFileE2E.test_c1_developer_commits_a_control_file"],
    "C2": ["test_results.C.test_c2_worktree_only"],
    "C3": ["test_results.C.test_c3_gitignored"],
    "C4": ["test_results.C.test_c4_nested"],
    "C5": ["test_results.C.test_c5_procedure", "test_results.C.test_c5_procedure_reference_is_the_engine_commit"],
    "C6": ["test_results.C.test_c6_revert_passes", "test_results.C.test_c6_partial_revert_fails"],
    "C7": ["test_results.C.test_c7_run_writes_control_file", "test_driver.Lifecycle.test_control_file_stop_on_a_run",
           "test_runner.ControlFilesInRuns.test_tracked_agents_md_is_refused",
           "test_runner.ControlFilesInRuns.test_new_claude_md_in_a_tracked_folder_is_refused"],
    "C8": ["test_results.C.test_c8_reference_is_the_base_blob"],
    "C*": ["test_statemachine.Stops.test_security_boundary_stop", "test_results.C.test_control_beats_everything"],
    # O — output ownership, judge writes
    "O1": ["test_results.O.test_o1_foreign_output", "test_results.O.test_o1_later_owner"],
    "O2": ["test_results.O.test_o2_restored_passes"],
    "O3": ["test_results.O.test_o3_judge_writes_outside"],
    "O4": ["test_results.O.test_o4_symlink_output"],
    "O5": ["test_results.O.test_o5_dirty_tree"],
    "O6": ["test_results.O.test_o6_run_dirty_tree", "test_runner.NamedCommands.test_dirty_tree_is_run_dirty_tree_without_extras"],
    # R — results and reviews
    "R1": ["test_results.ReviewRules.test_r1_block", "test_driver.ResultStops.test_r1_r8_block_goes_back_and_developer_resumes"],
    "R2": ["test_results.ReviewRules.test_r2_pass_with_blocker"],
    "R3": ["test_results.ReviewRules.test_r3_empty_reviewed"],
    "R4": ["test_results.ReviewRules.test_r4_missing_check"],
    "R5": ["test_results.S.test_r5_no_structured_output_twice", "test_statemachine.OutputFormat.test_r5_retry_once_then_needs_human",
           "test_driver.ResultStops.test_r5_output_format_twice_then_needs_human"],
    "R6": ["test_results.ReviewRules.test_r6_blocked_ignores_verdict", "test_statemachine.Stops.test_r6_blocked",
           "test_driver.ResultStops.test_r6_blocked_stops_and_rerun_continues"],
    "R7": ["test_results.ReviewRules.test_r7_reviewed_not_covering", "test_results.ReviewRules.test_r7_required_check_fail_and_na"],
    "R8": ["test_results.ReviewRules.test_r8_block_target_owner", "test_statemachine.OnFail.test_r8_i3_explicit_owner",
           "test_driver.ResultStops.test_r1_r8_block_goes_back_and_developer_resumes",
           "test_e2e.NeedsHumanThenResume.test_review_block_back_to_developer_then_blocked_stop_and_resume"],
    # V — mandatory rules, re-verification
    "V1": ["test_rules.V1TestChangeReview.test_verification_path_adds_the_check_and_resets_a_done_review",
           "test_driver.Rules.test_v1_verification_path_adds_the_check"],
    "V2": ["test_rules.V2RiskGate.test_gate_is_inserted_before_the_pr_with_a_new_revision",
           "test_rules.V2RiskGate.test_gate_without_an_available_role_is_unfillable",
           "test_driver.Rules.test_rule_unfillable_stops_for_a_human"],
    "V3": ["test_statemachine.Reverify.test_v3_code_change_resets_reviews_and_runs",
           "test_driver.Rules.test_v3_e5_change_after_review_reruns_review_and_runs"],
    "V4": ["test_statemachine.Reverify.test_v4_judge_documents_are_exempt",
           "test_statemachine.Reverify.test_v4_other_specs_paths_are_not_exempt",
           "test_driver.Rules.test_v4_judgment_documents_alone_are_exempt"],
    # E — outbound writes and git
    "E1": ["test_github.Writes.test_e1_secret_in_a_comment_stops_before_any_write",
           "test_outbound.Neutralise.test_e1_prepare_text_neutralises_and_scans"],
    "E2": ["test_outbound.PushRange.test_e2_secret_in_the_diff", "test_outbound.PushRange.test_e2_secret_in_a_binary_file",
           "test_outbound.PushRange.test_e2_secret_in_a_commit_message"],
    "E3": ["test_outbound.PushRange.test_e3_close_keyword_in_a_commit_message_names_the_commit"],
    "E4": ["test_outbound.Neutralise.test_e4_mentions_refs_and_same_repo_urls",
           "test_github.Writes.test_e4_summary_created_then_patched_neutralised"],
    "E5": ["test_gitops.Push.test_e5_non_fast_forward_is_remote_diverged_and_never_forced",
           "test_driver.Rules.test_v3_e5_change_after_review_reruns_review_and_runs"],
    "E6": ["test_gitops.CreateAndPin.test_e6_tampered_gitfile_is_refused_before_git_runs",
           "test_gitops.CreateAndPin.test_e6_tampered_commondir_is_refused_before_git_runs",
           "test_gitops.CreateAndPin.test_e6_appeared_worktree_config_is_refused"],
    "E7": ["test_github.Reads.test_e7_issue_md_excludes_engine_and_outsider_comments",
           "test_driver.Comments.test_outsider_and_engine_comments_do_not_stop"],
    "E8": ["test_github.Reads.test_e8_new_collaborator_comments_since_the_watermark",
           "test_driver.Comments.test_e8_new_collaborator_comment_stops_then_continue"],
    "E9": ["test_github.Reads.test_e9_stable_stage_label", "test_driver.Refusals.test_e9_stable_label"],
    # S — state, infra, execution
    "S1": ["test_statemachine.OnFail.test_s1_cap_exceeded_needs_human",
           "test_driver.ResultStops.test_s1_on_fail_exceeded_and_the_one_rerun"],
    "S2": ["test_statemachine.Infra.test_s2_quota_within_4h_waits_then_same_step",
           "test_statemachine.Infra.test_s2_exactly_4h_waits_past_4h_stops",
           "test_session.Limits.test_rate_limit_rejected", "test_results.S.test_quota_wait",
           "test_scenario_stage1.QuotaE2E.test_s2_reset_within_4h_waits_then_the_same_step_reruns",
           "test_scenario_stage1.QuotaE2E.test_s2_reset_past_4h_stops"],
    "S3": ["test_results.S.test_s3_session_limit", "test_statemachine.Stops.test_s3_session_limit",
           "test_session.Limits.test_budget_reached", "test_session.Limits.test_budget_by_cost"],
    "S4": ["test_statemachine.AbsoluteLimits.test_s4_caps", "test_driver.Budget.test_s4_soft_then_absolute",
           "test_e2e.Budget.test_soft_budget_stops_once_then_absolute_stops_for_good"],
    "S5": ["test_results.S.test_s5_missing_boundary_fact_is_infra", "test_results.S.test_s5_git_failure_in_a_boundary_check",
           "test_facts.S5.test_git_failure_is_fact_missing", "test_facts.S5.test_bad_end_is_fact_missing",
           "test_facts.S5.test_measurement_failures_are_warnings"],
    # S6 was "init mismatch → stop"; FC decision D (2026-11-28) removed the init check: other init lists run on
    "S6": ["test_results.S.test_s6_other_init_lists_are_not_a_stop", "test_results.S.test_an_earlier_engines_init_fact_is_not_read",
           "test_session.InitListsDiffer.test_other_tools_skills_plugins_do_not_stop_the_session",
           "test_session.InitListsDiffer.test_another_builtin_plugin_agent_mcp_server_or_permission_mode_runs_on",
           "test_session.InitListsDiffer.test_an_unknown_cli_version_spawns",
           "test_session.InitListsDiffer.test_no_init_event_is_an_ordinary_session",
           "test_canary.NoInitCheck.test_the_launch_flags_that_keep_user_settings_out_stay",
           "test_scenario_stage1.RealCanaryRecording.test_real_init_gives_the_model_and_session"],
    "S7": ["test_canary.Judge.test_no_attempt_record_fails", "test_canary.Judge.test_not_refused_fails",
           "test_canary.Judge.test_other_errors_are_not_refusals", "test_canary.Judge.test_refusal_evidence_kinds",
           "test_canaryrun.RoleCanary.test_a_probe_that_gets_through_fails_the_canary",
           "test_canaryrun.RoleCanary.test_missing_probes_get_one_more_session_then_fail",
           "test_driver.ResultStops.test_canary_record_missing_stops_before_any_session",
           "test_scenario_stage1.RealCanaryRecording.test_the_real_streams_pass_and_one_flipped_result_fails",
           "test_scenario_stage1.SrtCanaryGate.test_a_failing_srt_canary_stops_before_the_first_run"],
    "S8": ["test_lifecycle.Locks.test_s8_live_lock_is_refused", "test_lifecycle.Locks.test_s8_dead_pid_lock_is_released",
           "test_lifecycle.Locks.test_reused_pid_with_another_start_time_is_dead", "test_driver.Refusals.test_s8_live_lock"],
    "S9": ["test_driver.Lifecycle.test_s9_engine_killed_mid_step_then_resume",
           "test_e2e.EngineKilledThenResume.test_sigkill_mid_session_then_cli_resume"],
    "S10": ["test_store.State.test_s10_format_mismatch", "test_driver.Lifecycle.test_s10_format_mismatch_refuses"],
    "S11": ["test_statemachine.Stops.test_s11_engine_error_leaves_steps_untouched",
            "test_driver.Lifecycle.test_s11_engine_error_keeps_the_step_and_resume_recovers"],
    "S12": ["test_fsafe.Refusals.test_parent_symlink", "test_fsafe.Refusals.test_deep_parent_symlink",
            "test_store.State.test_s12_link_in_records_refused"],
    "S13": ["test_acparse.MissCases.test_0102_8_inin_gijun_heading_is_read",
            "test_acparse.MissCases.test_0102_8_a_section_that_is_not_read_is_an_error_not_an_empty_set",
            "test_acparse.MissCases.test_0102_10_bracket_tag_after_the_case_id",
            "test_acparse.MissCases.test_0102_11_heading_list_names_every_ac",
            "test_acparse.MissCases.test_0102_11_an_ac_the_document_never_names_stays_uncovered",
            "test_scripts.AcCoverage.test_miss_cases_through_the_script"],
    "S14": ["test_runner.NamedCommands.test_flaky_is_marked_but_still_red",
            "test_runner.NamedCommands.test_base_red_stops_for_a_human",
            "test_runner.NamedCommands.test_red_has_both_i8_extras_and_stays_red"],
    # N — stage 1 has no leader
    "N1": ["test_statemachine.StageOne.test_n1_no_needs_leader_in_stage_1",
           "test_statemachine.StageOne.test_n1_every_path_of_apply_in_stage_1"],
    "N2": ["test_driver.PlanGate.test_n2_i1_rule_stops_before_design_and_plan_answer_continues"],
}

SECTION_5_2 = ([f"C{i}" for i in range(1, 9)] + [f"O{i}" for i in range(1, 7)] + [f"R{i}" for i in range(1, 9)]
               + [f"V{i}" for i in range(1, 5)] + [f"E{i}" for i in range(1, 10)] + [f"S{i}" for i in range(1, 15)]
               + ["N1", "N2"])


class Index(unittest.TestCase):
    def test_every_scenario_of_section_5_2_has_tests(self):
        self.assertEqual(len(SECTION_5_2), 51)
        for sid in SECTION_5_2:
            with self.subTest(scenario=sid):
                self.assertTrue(SCENARIOS.get(sid), f"{sid} has no test")
        self.assertEqual(set(SCENARIOS) - set(SECTION_5_2), {"C*"})

    def test_every_named_test_exists(self):
        loader = unittest.TestLoader()
        for sid, names in SCENARIOS.items():
            for n in names:
                with self.subTest(scenario=sid, test=n):
                    suite = loader.loadTestsFromName(T + n)
                    self.assertEqual(suite.countTestCases(), 1, n)
                    self.assertNotIn("_FailedTest", type(next(iter(suite))).__name__, n)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Z.new_tmp()
        self.addCleanup(Z.rmtree, self.tmp)
        self.w = Z.ZWorld(self.tmp)

    def out(self):
        return self.w.out.getvalue()

    def step(self, sid):
        return next(s for s in self.w.state()["steps"] if s["id"] == sid)


class ControlFileE2E(Base):
    def test_c1_developer_commits_a_control_file(self):
        """C1 through the real units: the developer commits .claude/agents/x.md → security
        stop (needs_human, control-file), the result is thrown away (the step is not done, no
        on_fail / back_to), no later step starts and the engine reverts nothing."""
        for st in ["analyze", "test-cases", "design"]:
            self.w.add(Z.role_scenario(st))
        bad = Z.role_scenario("implement")
        bad["actions"] = [{"op": "write", "path": ".claude/agents/x.md", "content": "# planted agent\n"},
                          {"op": "write", "path": "src/app.py", "content": "x = 2\n"},
                          {"op": "git", "args": ["add", "-A"]},
                          {"op": "git", "args": ["commit", "-q", "-m", "feat: x"]}]
        self.w.add(bad)
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"], st["stop"]["step"]),
                         ("needs_human", codes.StopReason.CONTROL_FILE.value, "implement"))
        self.assertNotIn("allowed_answers", st["stop"])
        self.assertEqual(self.step("implement")["status"], "needs_human")
        self.assertEqual(self.step("implement")["latest_attempt"], 1)
        log = self.w.log()
        self.assertFalse([e for e in log if e["event"] == "back-to"], "a security stop never goes to on_fail")
        self.assertEqual(len(self.w.claude_calls()), 4, "no later step started")
        later = ["lint", "typecheck", "test", "build", "e2e", "review-design", "review-tests", "review-audit", "qa"]
        self.assertTrue(all(self.step(s)["status"] == "pending" for s in later))
        # nothing reverted: the planted file is still committed on the Issue branch and in the worktree
        self.assertIn(".claude/agents/x.md", self.w.wt_git("ls-files").split())
        self.assertTrue(os.path.isfile(os.path.join(self.w.worktree, ".claude", "agents", "x.md")))
        fx = Z.store.read_facts(self.w.paths(), "implement", 1)
        self.assertFalse(fx["control_files"]["ok"])
        self.assertIn(".claude/agents/x.md", json.dumps(fx["control_files"]))
        self.assertIsNone(self.w.repo.remote_head("gld/42"), "nothing was pushed")


def _rate_limited(step, reset_at):
    """A role session that hits the usage limit (the P3-A fixture shape) with a chosen reset time."""
    with open(Z.fakes.scn("a-rate-limit-rejected.json"), encoding="utf-8") as f:
        scn = json.load(f)
    for e in scn["events"]:
        if e.get("type") == "rate_limit_event":
            e["rate_limit_info"]["resetsAt"] = int(reset_at)
    scn["description"] = f"P4 S2: {step} rate-limited"
    return scn


class QuotaE2E(Base):
    def test_s2_reset_within_4h_waits_then_the_same_step_reruns(self):
        for st in ["analyze", "test-cases", "design"]:
            self.w.add(Z.role_scenario(st))
        self.w.add(_rate_limited("implement", time.time() + 3600))
        for st in Z.ROLE_STEPS[3:]:
            self.w.add(Z.role_scenario(st))
        slept = []
        rc = self.w.run(units=self.w.units(sleep=slept.append))
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        self.assertEqual(len(slept), 1)
        self.assertTrue(3500 < slept[0] <= 3600 + 5, slept)
        self.assertEqual(self.step("implement")["latest_attempt"], 2, "the same step, a new attempt")
        self.assertEqual(self.step("design")["latest_attempt"], 1, "nothing before it reran")
        self.assertIsNone(self.w.state()["stop"])

    def test_s2_reset_past_4h_stops(self):
        for st in ["analyze", "test-cases", "design"]:
            self.w.add(Z.role_scenario(st))
        self.w.add(_rate_limited("implement", time.time() + 5 * 3600))
        slept = []
        rc = self.w.run(units=self.w.units(sleep=slept.append))
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        self.assertEqual(slept, [])
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["step"]), ("needs_human", "implement"))
        self.assertEqual(st["stop"]["reason"], codes.StopReason.INFRA_STOP.value)


class SrtCanaryGate(Base):
    def test_a_failing_srt_canary_stops_before_the_first_run(self):
        """S7 for runs (P4): the driver checks the srt canary of the run template before a run;
        a failing record → canary-failed, and the run never starts."""
        key = canaryrun.srt_key(self.w.srt, canaryrun.exception_flags(Z.config()))
        canaryrun.write_record(self.w.engine_home, {"ok": False, "key": key, "kind": "srt"})
        real_ensure = canaryrun.ensure_srt_canary
        calls = []

        def no_rerun(srt, home, config, user_tmp=None, base_env=None):
            calls.append(srt)
            return canaryrun.record_ok(home, key), key      # do not re-run: keep the failing record
        self.w.add(Z.role_scenario("analyze"))
        rc = self.w.run(units=self.w.units(srt_canary_ok=lambda env, srt, paths: no_rerun(
            srt, env.paths.engine_home, env.config.raw, paths.get("user_tmp"), env.environ)))
        self.assertIs(canaryrun.ensure_srt_canary, real_ensure)
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), (codes.StopReason.CANARY_FAILED.value, "ac-format"))
        self.assertEqual(calls, [self.w.srt])
        self.assertFalse(os.path.exists(os.path.join(self.w.paths().attempt_dir("ac-format", 1), "run.log")))

    def test_the_real_srt_canary_runs_once_per_key_and_opens_the_runs(self):
        self.w.add(Z.role_scenario("analyze"))          # then no scenario: the next session ends the run
        self.w.run()
        key = canaryrun.srt_key(self.w.srt, canaryrun.exception_flags(Z.config()))
        rec = canaryrun.read_record(self.w.engine_home, key)
        self.assertTrue(rec and rec["ok"], rec)
        self.assertEqual(rec["kind"], "srt")
        self.assertEqual(self.step("ac-format")["status"], "done", "the run started after the srt canary passed")
        path = canaryrun.record_path(self.w.engine_home, key)
        before = os.stat(path).st_mtime_ns
        self.assertEqual(canaryrun.ensure_srt_canary(self.w.srt, self.w.engine_home, Z.config()), (True, key))
        self.assertEqual(os.stat(path).st_mtime_ns, before, "a passing record is reused, not re-run")


REAL = os.path.join(Z.fakes.FIXTURES, "claude", "canary", "real-2.1.323")


@unittest.skipUnless(os.path.isdir(REAL), "the real canary recording is not in the fixtures")
class RealCanaryRecording(unittest.TestCase):
    """The P4 paid canary, recorded (normalised) — the judge and the init check on REAL CLI output."""

    def load(self, cls):
        from gxengine import canary
        with open(os.path.join(REAL, f"{cls}-items.json"), encoding="utf-8") as f:
            raw = json.load(f)
        items = [canary.CanaryItem(i["id"], i["tool"], i["target"], i["expect"], i["action"], token=i.get("token"),
                                   label=i.get("label", ""), cmd=i.get("cmd")) for i in raw]
        streams = sorted(p for p in os.listdir(REAL) if p.startswith(f"{cls}-") and p.endswith(".jsonl"))
        return items, [os.path.join(REAL, s) for s in streams]

    @staticmethod
    def for_session(item, stream):
        """The own in/ probes name the attempt's own in/ folder (session n = attempt n)."""
        from gxengine import canary
        if "own-in" not in item.id:
            return item
        n = os.path.basename(stream).rsplit("-", 1)[1].split(".")[0]
        fix = (lambda v: v.replace("/runs/canary/1/in/", f"/runs/canary/{n}/in/") if v else v)
        return canary.CanaryItem(item.id, item.tool, fix(item.target), item.expect, item.action, token=item.token,
                                 label=item.label, cmd=fix(item.cmd))

    def test_the_real_streams_pass_and_one_flipped_result_fails(self):
        from gxengine import canary
        for cls in ("work", "judge"):
            items, streams = self.load(cls)
            by_id = {i.id: i for i in items}
            outcomes = {}
            for s in streams:
                with open(s, encoding="utf-8") as f:
                    lines = f.read().splitlines()
                with open(s[:-len(".jsonl")] + ".ids", encoding="utf-8") as f:
                    ids = f.read().split()
                j = canary.judge_canary(lines, [self.for_session(by_id[i], s) for i in ids])
                outcomes.update({k: v for k, v in j["outcomes"].items() if v != "missing"})
            with self.subTest(role_class=cls):
                wrong = {k: (by_id[k].expect, v) for k, v in outcomes.items() if v != by_id[k].expect}
                self.assertEqual(wrong, {})
                self.assertEqual(set(outcomes), set(by_id), "every probe has an attempt record")
                self.assertTrue(any(v == "refused" for v in outcomes.values()))
            # one refusal turned into a success → the judge sees an allowed probe
            with open(streams[0], encoding="utf-8") as f:
                evs = [json.loads(l) for l in f.read().splitlines() if l.strip()]
            with open(streams[0][:-len(".jsonl")] + ".ids", encoding="utf-8") as f:
                ids = f.read().split()
            batch = [by_id[i] for i in ids]
            uses = streamjson.tool_uses(evs)
            target = next(u for u in uses if any(i.matches(u) and i.expect == "refused" for i in batch))
            for e in evs:
                if e.get("type") == "user":
                    for c in (e.get("message") or {}).get("content") or []:
                        if isinstance(c, dict) and c.get("tool_use_id") == target["id"]:
                            c["is_error"], c["content"] = False, "secret content"
                    e.pop("tool_result_meta", None)
                if e.get("type") == "result":
                    e["permission_denials"] = [d for d in e.get("permission_denials") or []
                                               if d.get("tool_use_id") != target["id"]]
            evs = [e for e in evs if not (e.get("type") == "system" and e.get("subtype") == "permission_denied"
                                          and e.get("tool_use_id") == target["id"])]
            j = canary.judge_canary([json.dumps(e) for e in evs], batch)
            with self.subTest(role_class=cls, flipped=target["id"]):
                self.assertFalse(j["ok"])

    def test_real_init_gives_the_model_and_session(self):
        """What the engine still reads from a real init (FC decision D: no list comparison)."""
        for cls in ("work", "judge"):
            _, streams = self.load(cls)
            with open(streams[0], encoding="utf-8") as f:
                init = streamjson.first_init(list(streamjson.iter_events(f.read().splitlines())))
            with self.subTest(role_class=cls):
                self.assertIsInstance(init.get("model"), str)
                self.assertIsInstance(init.get("session_id"), str)

    def test_real_result_carries_the_structured_output(self):
        from gxengine import schema
        for cls in ("work", "judge"):
            _, streams = self.load(cls)
            for s in streams:
                with self.subTest(stream=os.path.basename(s)):
                    with open(s, encoding="utf-8") as f:
                        res = streamjson.result_event(list(streamjson.iter_events(f.read().splitlines())))
                    so = streamjson.structured_output(res)
                    self.assertIsNotNone(so, "--json-schema output arrives as result.structured_output")
                    self.assertEqual(schema.errors(so, schema.load_schema("result-work")), [])


if __name__ == "__main__":
    unittest.main()
