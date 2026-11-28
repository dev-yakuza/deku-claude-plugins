"""Stage 4 V1: the call sites and records the branches A and B build on (stage4/interfaces.md).

Two things are pinned here: below stage 4 nothing of it happens (H23), and at stage 4 the driver / cli /
lifecycle hand the branches exactly the arguments of the contract. The features themselves have their
own tests (the branches'); what only holds while a module is a shell is in test_stage4_shells_a.py (branch A)
and test_stage4_shells_b.py (branch B) — the owner removes a test there when the unit replaces its shell.
"""

import io
import os
import re
import tempfile
import time
import unittest

from gxengine import (cli, defaults, driver, github, globs, instructions, leader as leadermod, lifecycle, mutation,
                      paths as pathsmod, statemachine, store, testchange)
from tests import c_world as W
from tests.helpers.defects import fixes_defect
from tests import s3_world as S

SHA = "a" * 40
MUTATIONS = f"{S.SPECS}/mutations.json"
DECLARED = ('{"format": 1, "mutations": [{"acs": [1], "path": "src/app.py", "find": "x = 2", "replace": "", "note": ""}]}\n')


class Runner4(S.FakeRunner):
    """The stage-3 runner double with the stage-4 arguments recorded."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.s4 = []

    def run_step(self, *a, heavy_lock="absent", allowed_test_changes="absent", **kw):
        self.s4.append((heavy_lock, allowed_test_changes))
        return super().run_step(*a, **kw)

    def toolchain_prepare(self, ctx, config, base_env, srt_bin, **kw):
        self.prepare = getattr(self, "prepare", []) + [kw]
        return []


class Prbody4(S.FakePrbody):
    def build(self, *a, **kw):
        self.stage4 = getattr(self, "stage4", []) + [kw.get("stage4", "absent")]
        return super().build(*a, **kw)


class Mutation4:
    """mutation's seams: `prove` records the request and writes the record."""
    ProveRequest = mutation.ProveRequest
    declaration_path = staticmethod(mutation.declaration_path)
    load = staticmethod(mutation.load)
    retryable = staticmethod(mutation.retryable)
    supersede = staticmethod(mutation.supersede)

    def __init__(self, status="killed", raises=None, statuses=None, flaky=False):
        self.status, self.raises, self.requests, self.statuses = status, raises, [], list(statuses or ())
        self.flaky = flaky

    def prove(self, r):
        self.requests.append(r)
        if self.raises:
            raise self.raises
        if self.statuses:
            self.status = self.statuses.pop(0)
        rec = {"format": 1, "issue": r.issue, "head": r.head, "blob": r.blob, "problem": None,
               "control": {"exit_code": 0, "timed_out": False, "log_file": "control.log"},
               "rows": [{"id": "M1", "acs": [1], "path": "src/app.py", "find": "x = 2", "replace": "", "note": "",
                         "status": self.status, "detail": None,
                         "run": {"exit_code": 1, "timed_out": False, "log_file": "m1.log"}, "log_tail": "1 failed"}],
               "at": store.now_ts()}
        if self.flaky:                           # VW2 E1: red, then green; the kill was red twice
            rec["control"].update(exit_code=1, again={"exit_code": 0, "timed_out": False, "log_file": "c2.log"},
                                  flaky=True)
            rec["rows"][0]["again"] = {"exit_code": 1, "timed_out": False, "log_file": "m1.rerun.log"}
        store.write_record(r.engine_paths, r.engine_paths.mutation_record(r.head), rec, "mutation-record")
        return rec


class Stage4World(S.Stage3):
    def setUp(self):
        super().setUp()
        self.runner = Runner4()
        self.prbody = Prbody4()

    def run4(self, leader, answer=None, mode="attended", stage=4, start=None, **over):
        u = self.units(leader, **over)
        return driver.run_issue(W.REPO, W.ISSUE, mode, W.PLUGIN_ROOT, self.w.environ, checkout=self.w.repo.path,
                                units=u, out=self.w.out, answer=answer, stage=stage, start=start)

    def implement(self, **files):
        return [{"write": dict({"src/app.py": "x = 2\n"}, **files), "commit": "feat: quiz type", "structured": S.result()}]


class Runs(Stage4World):
    def test_stage4_runs_get_the_lock_and_the_allowed_files(self):
        self.ok(self.run4(self.leader()))
        lock = pathsmod.heavy_run_lock(os.path.realpath(self.w.engine_home))
        self.assertEqual(set(self.runner.s4), {(lock, ())})
        self.assertEqual({k.get("heavy_lock") for k in self.runner.prepare}, {lock})
        self.assertEqual(self.prbody.stage4[0], {"stack": None, "allowed_test_changes": [], "mutations": None})

    def test_stage3_gets_none_of_it(self):
        mut = Mutation4()
        self.session = self.sess(implement=self.implement(**{MUTATIONS: DECLARED}))
        self.ok(self.run4(self.leader(), stage=3, mutation=mut))
        self.assertEqual(set(self.runner.s4), {("absent", "absent")})
        self.assertEqual(self.prbody.stage4[0], "absent")
        self.assertEqual(mut.requests, [], "no mutation is run before stage 4")
        self.assertEqual(self.log("mutation-proof"), [])


class MutationProof(Stage4World):
    """VB9: declaration → engine run before the done-gate → the leader and the PR get the record."""

    def test_the_declared_mutations_reach_the_done_gate_and_the_pr(self):
        mut = Mutation4()
        self.session = self.sess(implement=self.implement(**{MUTATIONS: DECLARED}))
        ld = self.leader()
        self.ok(self.run4(ld, mutation=mut))
        self.assertEqual(len(mut.requests), 1, "once per HEAD")
        r = mut.requests[0]
        self.assertEqual((r.issue, r.acs), (W.ISSUE, [1]))
        self.assertEqual(r.heavy_lock, pathsmod.heavy_run_lock(os.path.realpath(self.w.engine_home)))
        self.assertIn("srt_tmpdir", r.render_paths)
        gate = [c["request"] for c in ld.calls if c["situation"] == "done-gate"][0]
        self.assertEqual(gate.mutations["rows"][0]["status"], "killed")
        self.assertEqual(self.prbody.stage4[0]["mutations"]["head"], r.head)
        self.assertEqual(self.log("mutation-proof")[0]["data"]["counts"], {"killed": 1})

    def test_a_survived_mutation_stops_nothing(self):
        """A fact, not a verdict: the leader judges."""
        mut = Mutation4(status="survived")
        self.session = self.sess(implement=self.implement(**{MUTATIONS: DECLARED}))
        ld = self.leader()
        self.ok(self.run4(ld, mutation=mut))
        gate = [c["request"] for c in ld.calls if c["situation"] == "done-gate"][0]
        self.assertEqual(gate.mutations["rows"][0]["status"], "survived")

    def test_nothing_declared_runs_nothing(self):
        mut = Mutation4()
        ld = self.leader()
        self.ok(self.run4(ld, mutation=mut))
        self.assertEqual(mut.requests, [])
        self.assertIsNone([c["request"] for c in ld.calls if c["situation"] == "done-gate"][0].mutations)

    def test_an_error_is_an_engine_error_never_a_pass(self):
        mut = Mutation4(raises=RuntimeError("boom"))
        self.session = self.sess(implement=self.implement(**{MUTATIONS: DECLARED}))
        ld = self.leader()
        self.assertEqual(self.run4(ld, mutation=mut), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.state()["stop"]["reason"], "engine-error")
        self.assertEqual([c for c in ld.calls if c["situation"] == "done-gate"], [])

    def escalated(self, mut):
        """#1938's shape: the leader sees no proof at the done-gate and asks a person."""
        self.session = self.sess(implement=self.implement(**{MUTATIONS: DECLARED}))
        ld = self.leader({"done-gate": [S.LA("escalate", reason="env-problem", recommendation={
            "answer": "rerun", "step": None, "note": ""}), S.approve()]})
        self.assertEqual(self.run4(ld, mutation=mut), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.state()["stop"]["reason"], "done-gate")
        return ld

    def test_a_human_rerun_proves_a_head_without_a_run_fact_again(self):
        """VW2 E1: the not-run record is moved aside; the next done-gate runs the proof on the same HEAD."""
        mut = Mutation4(statuses=["not-run", "killed"])
        ld = self.escalated(mut)
        self.ok(self.run4(ld, mutation=mut, answer={"answer": "rerun"}))
        self.assertEqual([r.head for r in mut.requests], [mut.requests[0].head] * 2, "the same HEAD, twice")
        gates = [c["request"] for c in ld.calls if c["situation"] == "done-gate"]
        self.assertEqual([g.mutations["rows"][0]["status"] for g in gates], ["not-run", "killed"])
        logs = self.log("mutation-proof")
        moved = [l for l in logs if l["data"].get("superseded")]
        self.assertEqual(len(moved), 1)
        self.assertEqual((moved[0]["who"], moved[0]["data"]["record"], moved[0]["data"]["counts"]),
                         ("human", "superseded-1.json", {"not-run": 1}))
        self.assertTrue(os.path.isfile(os.path.join(self.w.paths().mutations_dir(mut.requests[0].head),
                                                    "superseded-1.json")))
        self.assertEqual([l["data"]["counts"] for l in logs if not l["data"].get("superseded")],
                         [{"not-run": 1}, {"killed": 1}])
        self.assertEqual([(l["data"]["reruns"], l["data"]["control_flaky"]) for l in logs
                          if not l["data"].get("superseded")], [([], False)] * 2)

    def test_the_log_and_the_leader_see_a_flaky_control(self):
        mut = Mutation4(flaky=True)
        self.session = self.sess(implement=self.implement(**{MUTATIONS: DECLARED}))
        ld = self.leader()
        self.ok(self.run4(ld, mutation=mut))
        data = self.log("mutation-proof")[0]["data"]
        self.assertEqual((data["reruns"], data["control_flaky"]), (["control", "M1"], True))
        gate = [c["request"] for c in ld.calls if c["situation"] == "done-gate"][0]
        self.assertIs(gate.mutations["control"]["flaky"], True)
        self.assertIs(leadermod._mutations(gate)["control_flaky"], True)

    def test_a_human_rerun_never_replaces_a_run_fact(self):
        mut = Mutation4(status="survived")
        ld = self.escalated(mut)
        self.ok(self.run4(ld, mutation=mut, answer={"answer": "rerun"}))
        self.assertEqual(len(mut.requests), 1, "survived is a fact: running again until a red shows is not allowed")
        self.assertEqual([l for l in self.log("mutation-proof") if l["data"].get("superseded")], [])

    def test_a_human_approve_moves_nothing(self):
        mut = Mutation4(statuses=["not-run"])
        ld = self.escalated(mut)
        self.ok(self.run4(ld, mutation=mut, answer={"answer": "approve"}))
        self.assertEqual(len(mut.requests), 1)

    def test_the_srt_canary_gate_holds_here_too(self):
        mut = Mutation4()
        self.session = self.sess(implement=self.implement(**{MUTATIONS: DECLARED}))
        ok = lambda env, srt, paths: ("mutation-proof" not in paths["run_tmp"], "srt-key")   # noqa: E731
        self.assertEqual(self.run4(self.leader(), mutation=mut, srt_canary_ok=ok), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.state()["stop"]["reason"], "canary-failed")
        self.assertEqual(mut.requests, [])


class LeaderSections(unittest.TestCase):
    def test_the_record_becomes_the_done_gate_section(self):
        class R:
            mutations = None
        self.assertIsNone(leadermod._mutations(R))
        R.mutations = {"problem": None, "rows": [
            {"id": "M1", "acs": [2], "path": "a", "find": "f" * (defaults.LEADER_INPUT_TEXT_MAX + 1), "replace": "", "note": "",
             "status": "killed", "detail": None, "run": {"exit_code": 1}, "log_tail": "x"}]}
        got = leadermod._mutations(R)
        self.assertIs(got["control_flaky"], False, "a record without the VW2 E1 fields: one green control")
        self.assertNotIn("run", got["rows"][0])
        self.assertTrue(got["rows"][0]["find"].endswith(defaults.LEADER_INPUT_TRUNCATION_MARK))
        self.assertEqual(got["rows"][0]["log_excerpt"], "", "a record of an older engine has no excerpt")

    @fixes_defect("E2", "escalate:env-problem @ done-gate")
    def test_the_leader_gets_the_excerpt_and_the_end_of_the_tail(self):
        """VW3 E2: the tail is cut from the FRONT (its end and a not-run reason stay), the excerpt is kept."""
        class R:
            mutations = None
        tail = "".join(f"cleanup line {i}\n" for i in range(800)) + "[gld engine] not run: why"
        excerpt = "[gld engine] m1.log, lines 1-2 of 9: rule\n1| Expected: <1>\n2|   Actual: <2>"
        R.mutations = {"problem": None, "control": {"flaky": True}, "rows": [
            {"id": "M1", "acs": [2], "path": "a", "find": "f", "replace": "", "note": "", "status": "killed",
             "detail": None, "run": {"exit_code": 1}, "log_tail": tail, "log_excerpt": excerpt},
            {"id": "M2", "acs": [2], "path": "a", "find": "g", "replace": "", "note": "", "status": "killed",
             "detail": None, "run": {"exit_code": 1}, "log_tail": "short", "log_excerpt": "e" * 5000}]}
        rows = leadermod._mutations(R)["rows"]
        self.assertEqual(rows[0]["log_excerpt"], excerpt)
        self.assertTrue(rows[0]["log_tail"].startswith(defaults.LEADER_INPUT_TRUNCATION_MARK))
        self.assertTrue(rows[0]["log_tail"].endswith("[gld engine] not run: why"))
        self.assertEqual(len(rows[0]["log_tail"]),
                         defaults.MUTATION_LEADER_TAIL_MAX + len(defaults.LEADER_INPUT_TRUNCATION_MARK))
        self.assertEqual(rows[1]["log_tail"], "short")
        self.assertEqual(len(rows[1]["log_excerpt"]),
                         defaults.MUTATION_EXCERPT_MAX + len(defaults.LEADER_INPUT_TRUNCATION_MARK),
                         "a hand-made record is still held to the bound")
        self.assertLessEqual(defaults.MUTATION_EXCERPT_MAX + defaults.MUTATION_LEADER_TAIL_MAX,
                             defaults.LEADER_INPUT_TEXT_MAX, "no more than the one log_tail of before")

    def test_infra(self):
        ok = leadermod.LeaderResult(situation="blocked", called=True, stop="infra-stop",
                                    infra={"detail": "quota", "reset_at": 5.0})
        self.assertEqual(ok.infra["reset_at"], 5.0)
        for bad in ({"stop": "control-file", "infra": {"detail": "api", "reset_at": None}},
                    {"stop": "infra-stop", "infra": {"detail": "note text", "reset_at": None}},
                    {"stop": "infra-stop", "infra": {"detail": "api"}}):
            with self.assertRaises(ValueError):
                leadermod.LeaderResult(situation="blocked", called=True, **bad)


class StopDetail(unittest.TestCase):
    """H8: the code fields of an infra stop."""

    def state(self):
        return {"format": 1, "issue": 1, "revision": 1, "last_head": SHA,
                "steps": [{"id": "analyze", "status": "running", "latest_attempt": 1}]}

    def stop(self, stage, outcome):
        class P:
            step_ids, revision, steps = ["analyze"], 1, ()

            def step(self, i):
                return None
        st = self.state()
        statemachine.apply(st, P(), "analyze", outcome, stage=stage, now=0.0)
        return st["stop"]

    def test_a_long_quota_wait_keeps_its_reset_time_from_stage_4(self):
        late = defaults.INFRA_WAIT_MAX_S + 60
        out = statemachine.Outcome("failed", code="infra", detail="quota", reset_at=late)
        s = self.stop(4, out)
        self.assertEqual((s["reason"], s["detail"], s["reset_at"]), ("infra-stop", "quota", late))
        s = self.stop(3, out)
        self.assertNotIn("detail", s)
        self.assertNotIn("reset_at", s)

    def test_another_infra_reason_has_no_reset(self):
        s = self.stop(4, statemachine.Outcome("failed", code="infra", detail="api"))
        self.assertEqual((s["detail"], s["reset_at"]), ("api", None))

    def test_unknown_detail(self):
        with self.assertRaises(ValueError):
            statemachine.infra_fields(4, "the note says quota")
        self.assertEqual(statemachine.infra_fields(3, "quota", 5), {})

    def test_a_hand_over_to_a_human_drops_the_infra_detail(self):
        """An escalated stop must never look like a quota stop the sprint may rerun."""
        st = self.state()
        st["steps"][0]["status"] = "needs_leader"
        st["stop"] = statemachine.stop_record(st, "analyze", "blocked", 4, now=0.0)
        st["stop"].update(statemachine.infra_fields(4, "quota", 10.0))
        statemachine.to_human(st, 4, now=1.0)
        self.assertNotIn("detail", st["stop"])


class LeaderQuota(Stage4World):
    def test_a_leader_quota_past_the_limit_is_coded(self):
        late = 1000.0 + defaults.INFRA_WAIT_MAX_S + 60
        ld = self.leader({"plan-gate": [{"quota_reset_at": late}]})
        self.assertEqual(self.run4(ld, now=lambda: 1000.0), driver.EXIT_NEEDS_LEADER)
        s = self.state()["stop"]
        self.assertEqual((s["status"], s["reason"], s["detail"], s["reset_at"]), ("needs_leader", "plan-gate", "quota", late))

    def test_stage_3_keeps_its_stop(self):
        ld = self.leader({"plan-gate": [{"quota_reset_at": 1000.0 + defaults.INFRA_WAIT_MAX_S + 60}]})
        self.assertEqual(self.run4(ld, stage=3, now=lambda: 1000.0), driver.EXIT_NEEDS_LEADER)
        self.assertNotIn("detail", self.state()["stop"])


class SprintSeat(unittest.TestCase):
    """D6: the engine checks the sprint's rerun itself."""

    def state(self, **stop):
        return {"stop": dict({"status": "needs_human", "reason": "infra-stop", "step": None, "attempt": None,
                              "at": "2026-11-25T01:02:03Z", "note": "x", "detail": "quota", "reset_at": 100.0}, **stop)}

    def test_only_a_quota_stop_after_its_reset(self):
        self.assertIsNone(lifecycle.sprint_rerun_problem(self.state(), "rerun", 100.0))
        for now, stop, answer in ((99.0, {}, "rerun"), (200.0, {"detail": "api"}, "rerun"), (200.0, {"detail": None, "note": "quota"}, "rerun"),
                                  (200.0, {"reset_at": None}, "rerun"), (200.0, {"reset_at": True}, "rerun"),
                                  (200.0, {"status": "needs_leader"}, "rerun"), (200.0, {"reason": "blocked"}, "rerun"),
                                  (200.0, {}, "escalate"), (200.0, {}, "continue")):
            with self.subTest(now=now, stop=stop, answer=answer):
                self.assertTrue(lifecycle.sprint_rerun_problem(self.state(**stop), answer, now))

    def test_the_seat_exists_from_stage_4_only(self):
        with self.assertRaises(ValueError):
            lifecycle.validate_answer(self.state(), "rerun", procedure=object(), stage=3, who=lifecycle.SPRINT)
        q, reason = lifecycle.validate_answer(self.state(), "rerun", procedure=object(), stage=4, who=lifecycle.SPRINT)
        self.assertEqual((q["reason"], reason), ("infra-stop", "other"))
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.validate_answer(self.state(reset_at=time.time() + 999), "rerun", procedure=object(), stage=4,
                                      who=lifecycle.SPRINT)
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.validate_answer(self.state(), "rerun", step="analyze", procedure=object(), stage=4, who=lifecycle.SPRINT)


class SprintAnswer(Stage4World):
    def test_the_rerun_is_logged_as_the_sprints_and_is_no_return(self):
        res = S.FakeResults({"design": [lambda *a, **k: statemachine.Outcome("failed", code="infra", detail="quota",
                                                                             reset_at=time.time() + defaults.INFRA_WAIT_MAX_S + 60)]})
        ld = self.leader()
        self.assertEqual(self.run4(ld, mode="unattended", results=res), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.state()["stop"]["detail"], "quota")
        answer = {"answer": "rerun", "sprint": 700}
        self.assertEqual(self.run4(ld, answer=answer), driver.EXIT_REFUSED, "the reset has not passed")
        st = self.state()
        st["stop"]["reset_at"] = time.time() - 1
        store.save_state(self.w.paths(), st)
        self.results = S.FakeResults()
        self.ok(self.run4(ld, answer=answer, results=self.results))
        line = [l for l in self.log("answer") if l["who"] == "sprint"][0]
        self.assertEqual((line["code"], line["data"]["answer"]), ("infra-stop", "rerun"))
        self.assertNotIn("returns", self.sstep("design"))


class TestChange(Stage4World):
    def test_the_driver_hands_it_the_resume_and_logs_after_the_answer(self):
        res = S.FakeResults({"design": [W.blocked, W.done]})
        esc = W.leader_answer("escalate", recommendation={"answer": "rerun", "step": "design", "note": ""})
        ld = self.leader({"blocked": [esc]})
        self.assertEqual(self.run4(ld, results=res), driver.EXIT_NEEDS_HUMAN)
        seen = []

        class Double:
            @staticmethod
            def allowed(state):
                return [x["path"] for x in state.get("allowed_test_changes") or ()]

            @staticmethod
            def apply(state, paths, note, **kw):
                seen.append((paths, note, sorted(kw)))
                if note == "no":
                    raise testchange.Refused("not this file")
                state["allowed_test_changes"] = [{"path": p, "at": kw["now"], "note_sha256": "e" * 64} for p in paths]
                return [("test-change-allowed", {"who": "human", "data": {"paths": paths}})]
        answer = {"answer": "rerun", "step": "design", "note": "no", "allow_test_change": ["test/a_test.py"]}
        self.assertEqual(self.run4(ld, answer=answer, results=res, testchange=Double), driver.EXIT_REFUSED)
        self.assertNotIn("allowed_test_changes", self.state())
        self.assertEqual(self.state()["stop"]["reason"], "blocked")
        answer["note"] = "the signature changed"
        self.ok(self.run4(ld, answer=answer, results=res, testchange=Double))
        self.assertEqual(seen[-1], (["test/a_test.py"], "the signature changed",
                                    ["config", "ctx", "now", "owned", "procedure", "step"]))
        self.assertEqual(self.state()["allowed_test_changes"][0]["path"], "test/a_test.py")
        self.assertEqual(self.log("test-change-allowed")[0]["who"], "human")
        self.assertIn(("test/a_test.py",), [a for _, a in self.runner.s4])
        self.assertEqual(self.prbody.stage4[-1]["allowed_test_changes"], ["test/a_test.py"])

    def test_refused_before_stage_4(self):
        res = S.FakeResults({"design": [W.blocked, W.done]})
        ld = self.leader({"blocked": [W.leader_answer("escalate", recommendation={"answer": "rerun", "step": "design", "note": ""})]})
        self.run4(ld, results=res, stage=3)
        answer = {"answer": "rerun", "step": "design", "note": "x", "allow_test_change": ["a"]}
        self.assertEqual(self.run4(ld, answer=answer, results=res, stage=3), driver.EXIT_REFUSED)


class Start(Stage4World):
    def test_the_options_check_themselves(self):
        ok = driver.StartOptions(SHA, "gld/101", True, 700)
        self.assertIsNone(ok.problem("unattended", 4))
        self.assertTrue(ok.problem("attended", 4))                                   # TS9
        self.assertTrue(ok.problem("unattended", 3))
        for bad in (driver.StartOptions("main", "main", sprint=700), driver.StartOptions(SHA, "-x", sprint=700),
                    driver.StartOptions(SHA, None, sprint=700), driver.StartOptions(SHA, "main")):
            self.assertTrue(bad.problem("unattended", 4))

    def test_the_stack_comes_from_the_state(self):
        class E:
            state = {"base_branch": "gld/101", "draft": True, "sprint": 700}
        self.assertEqual(driver._stack(E), {"issue": 101, "tracker": 700, "draft": True})
        E.state = {"base_branch": "main"}
        self.assertIsNone(driver._stack(E))
        E.state = {}
        self.assertIsNone(driver._stack(E))


class References(unittest.TestCase):
    def test_the_rule_is_todays_at_every_stage_until_vb4(self):
        for stage in (1, 3):
            self.assertEqual(github.referenced_numbers("see #102~#104, acme/x#9, &#7; #5", own=5, stage=stage), [102, 104])
        self.assertIn("stage", github.build_issue_md.__code__.co_varnames)
        self.assertIn("stage", github.referenced_issue_states.__code__.co_varnames)


class Instructions(unittest.TestCase):
    def test_stage_4_texts_are_additions_only(self):
        """The overlays are read from stage 4 only; without their files stage 4 says what stage 3 says."""
        for stage in (1, 2, 3):
            self.assertNotIn("mutations.json", instructions.frame("work", "developer", "work", stage))
        data = instructions.DATA_DIR
        if not os.path.exists(os.path.join(data, instructions.STAGE4_WORK_FRAME)):
            self.assertEqual(instructions.frame("work", "developer", "work", 4), instructions.frame("work", "developer", "work", 3))
        if not os.path.exists(os.path.join(data, instructions.LEADER_STAGE4_DIR, "done-gate.md")):
            self.assertEqual(instructions.leader_task_text("done-gate", 4), instructions.leader_task_text("done-gate", 3))
        for step in ("safety-net", "implement", "analyze"):
            self.assertTrue(instructions.task_text(step, 4).startswith(instructions.task_text(step, 3).rstrip("\n")))


class Cli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"HOME": self._tmp.name, "PATH": os.environ.get("PATH", ""), "GLD_ENGINE_HOME": os.path.join(self._tmp.name, "eng")}

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *argv, stage=4):
        out = io.StringIO()
        return cli.main(list(argv), environ=self.env, out=out, stage=stage), out.getvalue()

    COMMANDS = (("sprint", "run", "--repo", "o/n", "--tracker", "700", "--checkout", "/x"),
                ("sprint", "status", "--repo", "o/n", "--tracker", "700"),
                ("sprint", "report", "--repo", "o/n", "--tracker", "700", "--json"),
                ("sprint", "stop", "--repo", "o/n", "--tracker", "700"),
                ("init", "doctor", "--repo", "o/n"), ("init", "propose", "--repo", "o/n", "--compare"),
                ("init", "answer", "--repo", "o/n", "--question", "test-command", "--answer", "make test", "--note", "me"),
                ("init", "check", "--repo", "o/n"), ("init", "write", "--repo", "o/n"),
                ("base-check", "--repo", "o/n"))

    def test_every_stage4_command_is_refused_before_stage_4(self):
        for argv in self.COMMANDS + (("sprint", "check", "--repo", "o/n", "--tracker", "700"),):
            rc, out = self.cli(*argv, stage=3)
            self.assertEqual(rc, cli.EXIT_REFUSED, argv)
            self.assertIn("exists from stage 4", out)
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "eng")), "nothing was written")

    def test_allow_test_change_is_stage_4(self):
        self.assertIn("stage 4", self.cli("resume", "--repo", "o/n", "--issue", "7", "--answer", "rerun", "--step", "x",
                                          "--allow-test-change", "test/a", stage=3)[1])

    def test_unknown_and_left_over_arguments_are_refused(self):
        for argv in (("sprint", "run", "--repo", "o/n", "--tracker", "700"),                      # no checkout
                     self.COMMANDS[0] + ("--duration", "3h"), self.COMMANDS[0] + ("101",),
                     self.COMMANDS[0] + ("--win", "22:00-10:00"),                                  # no abbreviation
                     ("sprint", "report", "--repo", "o/n", "--tracker", "700"), ("sprint",), ("init",),
                     ("init", "answer", "--repo", "o/n", "--question", "which-color", "--answer", "x", "--note", "me"),
                     ("init", "answer", "--repo", "o/n", "--question", "toolchain", "--note", "me"),
                     ("base-check", "--repo", "o/n", "--sha", "HEAD")):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli(*argv)[0], cli.EXIT_USAGE)

    def test_the_sprint_arguments_of_dev_and_resume(self):
        dev = ("dev", "--repo", "o/n", "--issue", "7", "--base-sha", SHA, "--base-branch", "main", "--sprint", "700")
        self.assertIn("unattended", self.cli(*dev)[1])                                        # TS9
        rc, out = self.cli(*dev, "--mode", "unattended")
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("foreground", out)
        rc, out = self.cli(*dev, "--mode", "unattended", "--foreground", stage=3)
        self.assertIn("stage 4", out)
        res = ("resume", "--repo", "o/n", "--issue", "7", "--sprint", "700")
        for extra in ((), ("--answer", "rerun"), ("--foreground", "--answer", "escalate"),
                      ("--foreground", "--answer", "rerun", "--step", "analyze")):
            self.assertEqual(self.cli(*res, *extra)[0], cli.EXIT_REFUSED, extra)
        self.assertIn("stage 4", self.cli(*res, "--foreground", "--answer", "rerun", stage=3)[1])


class Ownership(unittest.TestCase):
    """README "Stage 4 sessions (Q3)": no path in both rows (stage-4 scope §6.2)."""

    PLUGIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

    def rows(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md"), encoding="utf-8") as f:
            text = f.read()
        sec = text[text.index("## Stage 4 sessions (Q3)"):text.index("## Integration (P3-Z)")]
        out = {}
        for line in sec.splitlines():
            for key, start in (("A", "| A sprint |"), ("B", "| B init "), ("frozen", "| frozen |")):
                if line.startswith(start):
                    out[key] = self.expand(re.findall(r"`([^`]+)`", line.split("|")[3]))
        return out

    def expand(self, tokens):
        out = set()
        for t in tokens:
            t = t.replace("E/", "skills/gld/engine/", 1) if t.startswith("E/") else t
            t = t.replace("C/", "skills/gld/commands/", 1) if t.startswith("C/") else t
            m = re.search(r"\{([^}]*)\}", t)
            out |= {t[:m.start()] + x + t[m.end():] for x in m.group(1).split(",")} if m else {t}
        return out

    def files(self):
        out = []
        for d, dirs, files in os.walk(self.PLUGIN):
            dirs[:] = [x for x in dirs if x not in (".git", "__pycache__")]
            out += [os.path.relpath(os.path.join(d, f), self.PLUGIN) for f in files]
        return out

    def test_no_file_is_in_both_rows(self):
        rows = self.rows()
        self.assertEqual(set(rows), {"A", "B", "frozen"})
        self.assertGreater(min(len(rows["A"]), len(rows["B"])), 20)
        names = set(self.files()) | {x for r in ("A", "B") for x in rows[r] if "*" not in x}
        own = {k: {n for n in names if globs.match_any(sorted(pats), n) is not None} for k, pats in rows.items()}
        self.assertEqual(own["A"] & own["B"], set())
        self.assertTrue(own["A"] and own["B"])
        self.assertEqual((own["A"] | own["B"]) & (own["frozen"] - {"skills/gld/engine/README.md"}), set())

    def test_every_stage4_module_has_an_owner(self):
        rows = self.rows()
        for mod, who in (("sprint", "A"), ("sprintdag", "A"), ("sprinttracker", "A"), ("basecheck", "B"), ("initconfig", "B"),
                         ("issuerefs", "B"), ("testchange", "B"), ("mutation", "B")):
            self.assertIn(f"skills/gld/engine/gxengine/{mod}.py", rows[who])


class Records(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._tmp.name)
        self.sp = pathsmod.SprintPaths(self.home, "acme/app", 700)

    def tearDown(self):
        self._tmp.cleanup()

    def example(self, name):
        import json
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "contracts", name + ".example.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_paths(self):
        root = os.path.join(self.home, "records", "acme", "app")
        self.assertEqual(self.sp.state, os.path.join(root, "sprints", "700", "sprint.json"))
        self.assertEqual(self.sp.repo_lock, os.path.join(root, "sprint.lock"))
        self.assertEqual(pathsmod.base_green_record(self.home, "acme/app", SHA, "d" * 64),
                         os.path.join(root, "base-green", SHA + "-" + "d" * 16 + ".json"))
        ep = pathsmod.EnginePaths(self.home, "acme/app", 42)
        self.assertEqual(ep.mutation_record(SHA), os.path.join(root, "42", "mutations", SHA, "record.json"))
        for bad in ("main", "../x", ""):
            with self.assertRaises(ValueError):
                ep.mutations_dir(bad)
            with self.assertRaises(ValueError):
                pathsmod.base_green_record(self.home, "acme/app", bad, "d" * 64)
        with self.assertRaises(ValueError):
            pathsmod.SprintPaths(self.home, "acme/app", 0)
        with self.assertRaises(ValueError):
            pathsmod.init_dir(self.home, "acme/..")

    def test_sprint_json(self):
        self.assertIsNone(store.load_sprint(self.sp))
        ex = self.example("sprint-state")
        store.save_sprint(self.sp, ex)
        self.assertEqual(store.load_sprint(self.sp), ex)
        for over in ({"state": "halted"}, {"halt": "signal"}, {"tracker": 701}, {"repo": "acme/other"}):
            with self.subTest(over=over), self.assertRaises(ValueError):
                store.save_sprint(self.sp, dict(ex, **over))
        bad = self.example("sprint-state")
        bad["members"][0]["block"] = "upstream"
        with self.assertRaises(ValueError):
            store.save_sprint(self.sp, bad)

    def test_sprint_log(self):
        self.assertEqual(store.read_sprint_log(self.sp), [])
        store.append_sprint_log(self.sp, 1, "member-blocked", issue=103, outcome="blocked", block="upstream", cause=102, note=None)
        line = store.read_sprint_log(self.sp)[0]
        self.assertEqual((line["tracker"], line["block"], "note" in line), (700, "upstream", False))
        with self.assertRaises(ValueError):
            store.append_sprint_log(self.sp, 1, "no-such-event")
        with self.assertRaises(ValueError):
            store.append_sprint_log(self.sp, 1, "wait", tracker=1)

    def test_records(self):
        p = pathsmod.base_green_record(self.home, "acme/app", SHA, "d" * 64)
        self.assertIsNone(store.read_record(self.sp, p, "base-green"))
        ex = self.example("base-green")
        store.write_record(self.sp, p, ex, "base-green")
        self.assertEqual(store.read_record(self.sp, p, "base-green"), ex)
        with open(p, "w") as f:
            f.write("{}")
        with self.assertRaises((store.CorruptFile, store.FormatMismatch)):
            store.read_record(self.sp, p, "base-green")


if __name__ == "__main__":
    unittest.main()
