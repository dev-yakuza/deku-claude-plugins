"""Stage 3 Q8 — what the Q7 validation showed (stage3/q7-result.md, "engine improvement candidates").

K8-1  the engine runs a missing role canary itself (canaryrun.ensure_role_canary, driver). Since FC
      decision D (2026-11-28) any CLI version gets that canary — no init lists, no local trust record.
K8-3  close-as-decided at a blocked stop before any developer step (codes, leader, lifecycle, driver).
(K8-2, the base run judged twice: test_runner_stage3.BaseTwice.)

End to end with the real session machinery and the fake claude (GLD_FAKE_CLAUDE_CANARY answers the
canary prompts like a boundary would). No paid call, no real gh.
"""

import fcntl
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from gxengine import (budget, canaryrun, cli, codes, defaults, driver, leader, lifecycle, session, statemachine, store)
from tests import test_canaryrun as TC
from tests import test_leader as TL
from tests import test_leader_stage3 as T3
from tests import z_world as Z
from tests.helpers import fakes

NEW = "2.99.0"                              # a CLI version the engine never saw
OTHER = {"name": "cc-plugin-sec-default", "source": "cc-plugin-sec-default@builtin"}   # the FC account's extra builtin
SR = codes.StopReason
A = codes.LeaderAnswer


def events(log, name):
    return [l for l in log if l["event"] == name]


# --- K8-1: canaryrun ---------------------------------------------------------------------------

class CanaryCase(TC.RoleCanary):
    """The RoleCanary world without re-running its tests."""

    def ensure(self, fake, rc="judge", version="2.1.323", config=None, **kw):
        def run(role_class, *a, **k):
            return canaryrun.run_role_canary(role_class, *a, run_session=fake, **k)
        return canaryrun.ensure_role_canary(rc, self.env, TC.PLUGIN_ROOT, self.eng, config or {"format": 1, "commands": {}},
                                            version, run_canary=run, **kw)

    def trust_files(self):
        d = os.path.join(self.eng, "canary")
        return [n for n in os.listdir(d) if n.startswith("cli-")] if os.path.isdir(d) else []


for _name in [n for n in dir(CanaryCase) if n.startswith("test_")]:
    setattr(CanaryCase, _name, None)


class Ensure(CanaryCase):
    def test_a_missing_key_runs_the_canary_once(self):
        fake = TC.FakeBoundary()
        got = self.ensure(fake)
        self.assertTrue(got.ok, got.note)
        self.assertEqual(got.key, canaryrun.role_key("2.1.323", "judge", environ=self.env))
        self.assertAlmostEqual(got.ran["cost_usd"], 0.01 * len(fake.calls))
        self.assertTrue(all(c["model"] == "haiku" and c["effort"] == "low" and c["kw"] == {} for c in fake.calls))
        n = len(fake.calls)
        again = self.ensure(fake)
        self.assertTrue(again.ok)
        self.assertIsNone(again.ran)
        self.assertEqual(len(fake.calls), n)
        self.assertEqual(self.snapshot(), self.before, "bait removed")
        self.assertEqual(self.trust_files(), [], "no CLI version trust record (FC decision D)")

    def test_the_work_key_follows_the_repository_settings(self):
        cfg = {"format": 1, "commands": {}, "sandbox_exceptions": {"allow_local_binding": True}}
        got = self.ensure(TC.FakeBoundary(), rc="work", config=cfg)
        self.assertTrue(got.ok, got.note)
        self.assertEqual(got.key, canaryrun.role_key("2.1.323", "work", cfg, environ=self.env))
        self.assertEqual(got.ran["exceptions"], ["allow_local_binding"])
        self.assertTrue(self.ensure(TC.FakeBoundary(), config=cfg).ok, "a judge gets no exceptions")

    def test_a_failing_canary_stops_and_is_never_tried_again_by_itself(self):
        got = self.ensure(TC.FakeBoundary(wrong=["Read:read:home:.ssh"]))
        self.assertFalse(got.ok)
        self.assertIn("Read:read:home:.ssh: expected refused, got allowed", got.note)
        good = TC.FakeBoundary()
        again = self.ensure(good)
        self.assertFalse(again.ok)
        self.assertEqual(good.calls, [], "a human runs `engine.py canary`")
        self.assertIn("engine.py canary", again.note)
        self.run_canary("judge", TC.FakeBoundary())           # what the human does
        self.assertTrue(self.ensure(TC.FakeBoundary()).ok)

    def test_a_record_without_a_session_judged_nothing(self):
        key = canaryrun.role_key("2.1.323", "judge", environ=self.env)
        canaryrun.write_record(self.eng, {"ok": False, "key": key, "sessions": [], "notes": ["leftover"]})
        self.assertTrue(self.ensure(TC.FakeBoundary()).ok)
        canaryrun.write_record(self.eng, {"ok": False, "key": key})          # an unknown shape holds (fail-closed)
        fake = TC.FakeBoundary()
        self.assertFalse(self.ensure(fake).ok)
        self.assertEqual(fake.calls, [])

    def test_the_cost_cap_stops(self):
        fake = TC.FakeBoundary()
        got = self.ensure(fake, rc="work", spent_before=defaults.CANARY_TOTAL_MAX_USD - 1.0)
        self.assertFalse(got.ok)
        self.assertEqual(fake.calls, [], "the first session could already pass the total")
        self.assertIn("would pass", got.note)
        fake = TC.FakeBoundary(cost=4.0)
        got = self.ensure(fake, rc="work")
        self.assertFalse(got.ok)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("stopped before session 2", got.note)
        self.assertFalse(canaryrun.record_ok(self.eng, got.key))

    def test_one_canary_at_a_time(self):
        d = os.path.join(self.eng, "canary")
        os.makedirs(d)
        fd = os.open(os.path.join(d, canaryrun.LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        fake = TC.FakeBoundary()
        with mock.patch.object(canaryrun, "LOCK_POLL_S", 0.02):
            got = self.ensure(fake, lock_wait_s=0.1)
            self.assertFalse(got.ok)
            self.assertIn("another role canary", got.note)
            self.assertEqual(fake.calls, [])
            # the other engine finishes meanwhile: its record is used, no second canary
            self.run_canary("judge", TC.FakeBoundary())
            t = threading.Timer(0.2, fcntl.flock, (fd, fcntl.LOCK_UN))
            key = canaryrun.role_key("2.1.323", "judge", environ=self.env)
            rec =canaryrun.read_record(self.eng, key)
            os.unlink(canaryrun.record_path(os.path.realpath(self.eng), key))
            w = threading.Timer(0.1, canaryrun.write_record, (self.eng, rec))
            w.start()
            t.start()
            got = self.ensure(fake, lock_wait_s=10)
            w.join()
            t.join()
        self.assertTrue(got.ok, got.note)
        self.assertEqual(fake.calls, [])

    def test_a_linked_lock_file_is_refused(self):
        d = os.path.join(self.eng, "canary")
        os.makedirs(d)
        os.symlink("/dev/null", os.path.join(d, canaryrun.LOCK_FILE))
        self.assertFalse(self.ensure(TC.FakeBoundary()).ok)


class NewVersion(CanaryCase):
    """FC decision D: a new CLI version, with whatever init lists, gets the same probe canary."""

    def test_a_new_version_with_other_lists_passes_on_its_probes(self):
        fake = TC.FakeBoundary(init={"plugins": [OTHER], "agents": ["claude", "browser"], "tools": ["Bash"]})
        got = self.ensure(fake, version=NEW)
        self.assertTrue(got.ok, got.note)
        self.assertEqual(got.key, canaryrun.role_key(NEW, "judge", environ=self.env))
        self.assertTrue(all(c["kw"] == {} for c in fake.calls), "no init lists are handed to a session")
        self.assertNotIn("candidate", got.ran)
        self.assertEqual(self.trust_files(), [])
        self.assertIn(OTHER["source"], got.ran["sessions"][0]["init_plugins"])
        work = self.ensure(TC.FakeBoundary(), rc="work", version=NEW)       # the other class: its own canary
        self.assertTrue(work.ok, work.note)

    def test_a_failing_probe_still_fails_a_new_version(self):
        got = self.ensure(TC.FakeBoundary(wrong=["Read:read:home:.ssh"]), version=NEW)
        self.assertFalse(got.ok)
        self.assertIn("Read:read:home:.ssh: expected refused, got allowed", got.note)

    def test_an_earlier_engines_trust_record_is_not_read(self):
        d = os.path.join(self.eng, "canary")
        os.makedirs(d)
        with open(os.path.join(d, f"cli-{NEW}.json"), "w") as f:
            json.dump({"kind": "cli-version", "cli_version": NEW, "root": "2.1.325", "canary_key": "x"}, f)
        fake = TC.FakeBoundary()
        self.assertTrue(self.ensure(fake, version=NEW).ok)
        self.assertTrue(fake.calls, "the key still needs its own canary")


# --- K8-1: the driver, end to end ---------------------------------------------------------------

class Driver(unittest.TestCase):
    """analyze, then the leader escalates at the plan gate — the shortest real stage-3 run."""

    def setUp(self):
        self.tmp = Z.new_tmp()
        self.addCleanup(Z.rmtree, self.tmp)
        self.w = Z.Z3World(self.tmp, cfg=Z.config3())
        self.canary_dir = os.path.join(self.w.engine_home, "canary")
        shutil.rmtree(self.canary_dir)
        self.w.add(Z.role_scenario3("analyze"))
        self.w.add(Z.leader_scenario("plan-gate", Z.envelope(
            "escalate", "needs-human-decision", recommendation={"answer": "rerun", "step": "analyze", "note": "x"},
            requirements=[{"row": "R1", "covered": True}], missing_requirements=[], plan=None, close=None)))
        # what Z.add rebuilds is set again by env()
        self.env()

    def env(self, version="2.1.323", wrong=(), cost=0.01, **init):
        self.w._environ()
        e = self.w.environ
        e["GLD_FAKE_CLAUDE_CANARY"] = json.dumps({"wrong": list(wrong), "cost": cost})
        e["GLD_FAKE_CLAUDE_VERSION"] = f"{version} (Claude Code)"
        e["GLD_FAKE_CLAUDE_INIT"] = json.dumps(dict({"claude_code_version": version}, **init))
        fakes.assert_fakes_first(e)

    def canaries(self):
        return [n for n in os.listdir(self.w.claude_log) if n.startswith("canary-")] if os.path.isdir(
            self.w.claude_log) else []

    def stop(self):
        return self.w.state()["stop"]

    def test_missing_keys_run_the_canary_and_the_issue_goes_on(self):
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.w.out.getvalue())
        self.assertEqual((self.stop()["reason"], self.stop()["step"]), ("plan-gate", "plan"), self.w.out.getvalue()[-3000:])
        self.assertEqual(len(self.w.claude_calls()), 2, "analyze and the leader")
        lines = events(self.w.log(), "canary")
        self.assertEqual([(l["data"]["role_class"], l["data"]["ok"]) for l in lines], [("judge", True), ("work", True)])
        for l in lines:
            self.assertTrue(canaryrun.record_ok(self.w.engine_home, l["data"]["key"]))
            self.assertNotIn("candidate", l["data"])
        spent = sum(l["data"]["cost_usd"] for l in lines)
        self.assertAlmostEqual(spent, 0.01 * len(self.canaries()))
        # before anything else is paid for, and never Issue cost
        log = [l["event"] for l in self.w.log()]
        self.assertLess(log.index("canary"), log.index("attempt-start"))
        st = self.w.state()
        self.assertAlmostEqual(budget.issue_cost(self.w.paths(), st)[0], 1.4)         # analyze 1.0 + the leader 0.4
        n = len(self.canaries())
        # the next engine start finds the records
        self.w.run(answer={"answer": "escalate"})
        self.assertEqual(len(self.canaries()), n)

    def test_a_failing_canary_stops_before_any_session(self):
        self.env(wrong=["Read:read:home:.ssh"])
        self.assertEqual(self.w.run(), driver.EXIT_NEEDS_HUMAN)
        s = self.stop()
        self.assertEqual((s["status"], s["reason"], s["step"]), ("needs_human", "canary-failed", "analyze"))
        self.assertIn("Read:read:home:.ssh: expected refused, got allowed", s["note"])
        self.assertEqual(self.w.claude_calls(), [])
        self.assertEqual([l["data"]["ok"] for l in events(self.w.log(), "canary")], [False])
        n = len(self.canaries())
        # a human's rerun does not retry the boundary until it passes
        self.env()
        self.assertEqual(self.w.run(answer={"answer": "rerun"}), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.stop()["reason"], "canary-failed")
        self.assertIn("engine.py canary", self.stop()["note"])
        self.assertEqual((len(self.canaries()), self.w.claude_calls()), (n, []))

    def test_a_new_version_with_other_lists_goes_on(self):
        """The FC case end to end: another CLI version whose sessions list another builtin plugin, other
        agents, an MCP server — the canaries run on their probes, the role and leader sessions run on."""
        self.env(NEW, plugins=[OTHER], agents=["claude", "browser"], mcp_servers=[{"name": "x", "status": "connected"}])
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.stop()["reason"], "plan-gate", self.w.out.getvalue()[-3000:])
        self.assertEqual([(l["data"]["cli_version"], l["data"]["ok"]) for l in events(self.w.log(), "canary")],
                         [(NEW, True), (NEW, True)])
        self.assertFalse([n for n in os.listdir(self.canary_dir) if n.startswith("cli-")])
        fx = store.read_facts(self.w.paths(), "analyze", 1)
        self.assertEqual(fx["session"]["cli_version"], NEW)
        self.assertNotIn("init", fx["session"])
        lead = store.read_facts(self.w.paths(), "plan", 1)
        self.assertEqual(lead["session"]["cli_version"], NEW)
        self.assertEqual(len(self.w.claude_calls()), 2, "analyze and the leader")

    def test_the_cost_cap_stops(self):
        self.env(cost=4.0)
        self.assertEqual(self.w.run(), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.stop()["reason"], "canary-failed")
        self.assertIn("would pass", self.stop()["note"])
        self.assertEqual(self.w.claude_calls(), [])
        self.assertLessEqual(sum(l["data"]["cost_usd"] for l in events(self.w.log(), "canary")), defaults.CANARY_TOTAL_MAX_USD)

    def test_the_key_is_checked_before_every_session(self):
        """The CLI updates while the engine runs: the leader turn finds no key and runs the canary itself."""
        seen = []
        real = driver.default_canary_ok

        def update(env, role_class, version):
            seen.append((role_class, version))
            return real(env, role_class, version)

        class Updating:
            """session with a CLI that is updated after the first role session."""
            def __getattr__(self, name):
                return getattr(session, name)

            def run_session(s, *a, **kw):
                res = session.run_session(*a, **kw)
                self.w.environ.update({                    # in place: the engine holds this dict
                    "GLD_FAKE_CLAUDE_VERSION": f"{NEW} (Claude Code)", "GLD_FAKE_CLAUDE_INIT": json.dumps(
                        {"claude_code_version": NEW, "plugins": [OTHER]})})
                return res
        self.assertEqual(self.w.run(units=self.w.units(session=Updating(), canary_ok=update)), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(seen[:3], [("judge", "2.1.323"), ("work", "2.1.323"), ("judge", "2.1.323")])
        self.assertEqual(self.stop()["reason"], "plan-gate", self.w.out.getvalue()[-3000:])
        self.assertEqual([(l["data"]["role_class"], l["data"]["cli_version"]) for l in events(self.w.log(), "canary")],
                         [("judge", "2.1.323"), ("work", "2.1.323"), ("judge", NEW)])

    def test_earlier_stages_never_run_it(self):
        env = mock.Mock(stage=2, paths=self.w.paths(), environ=self.w.environ)
        env.config.raw = Z.config3()
        with mock.patch.object(canaryrun, "ensure_role_canary", side_effect=AssertionError("paid")):
            ok, key = driver.default_canary_ok(env, "judge", "2.1.323")
        self.assertFalse(ok)
        self.assertEqual(key, canaryrun.role_key("2.1.323", "judge", Z.config3(), environ=env.environ))

    def test_a_stopped_issue_pays_nothing(self):
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        shutil.rmtree(self.canary_dir)
        n = len(self.canaries())
        self.w.run(answer={"answer": "escalate"})          # still stopped: no session is coming
        self.assertEqual(len(self.canaries()), n)

    def test_the_manual_command_waits_for_the_lock(self):
        os.makedirs(self.canary_dir)
        fd = os.open(os.path.join(self.canary_dir, canaryrun.LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        real = canaryrun.role_canary_lock
        with mock.patch.object(canaryrun, "role_canary_lock", lambda home: real(home, wait_s=0)):
            self.assertEqual(cli.main(["canary", "--no-srt"], environ=self.w.environ, out=self.w.out), cli.EXIT_REFUSED)
        self.assertEqual(self.canaries(), [])


# --- K8-3: the rules ---------------------------------------------------------------------------

BLOCKED = SR.BLOCKED.value
CLOSE = A.CLOSE_AS_DECIDED.value


class Rules(unittest.TestCase):
    def state(self, started=False, **over):
        _, st, _ = TL._cell(BLOCKED, "base")
        if started is not None:
            st["developer_started"] = started
        return dict(st, **over)

    def allowed(self, started=False, mode="attended", stage=3, **kw):
        proc, _, base = TL._cell(BLOCKED, "base")
        base = dict(base, mode=mode, **kw)
        return leader.allowed_answers(BLOCKED, self.state(started), proc, TL.STEP_OF[BLOCKED], stage=stage, **base)

    def test_offered_before_any_developer_step(self):
        al = self.allowed()
        self.assertIn(CLOSE, al.answers)
        self.assertIn(CLOSE, al.human_answers)
        self.assertEqual(al.answers[-1], "escalate")

    def test_not_offered_to_either_seat_after_one(self):
        for started in (True, None):                       # None: an earlier engine's state — not known
            with self.subTest(started=started):
                al = self.allowed(started)
                self.assertNotIn(CLOSE, al.answers)
                self.assertNotIn(CLOSE, al.human_answers)
                self.assertIn(("developer-started", (CLOSE,)), al.narrowed)
                self.assertNotIn(CLOSE, lifecycle.allowed_answers(BLOCKED, self.state(started), 3))
                self.assertFalse(statemachine.close_allowed(self.state(started)))
        self.assertIn(CLOSE, lifecycle.allowed_answers(BLOCKED, self.state(), 3))

    def test_stage_2_is_unchanged(self):
        for st in (1, 2):
            self.assertNotIn(CLOSE, lifecycle.allowed_answers(BLOCKED, self.state(), st))
        self.assertNotIn(CLOSE, self.allowed(stage=2).answers + self.allowed(stage=2).human_answers)

    def test_only_blocked_and_the_plan_gate(self):
        for sit in codes.STAGE3_LEADER_ANSWER_SCHEMAS:
            want = sit in (BLOCKED, SR.PLAN_GATE.value)
            self.assertEqual(CLOSE in lifecycle.allowed_answers(sit, self.state(), 3), want, sit)

    def test_unattended_needs_the_decision_marker(self):
        al = self.allowed(mode="unattended", decision_marker=False)
        self.assertNotIn(CLOSE, al.answers)
        self.assertIn(("unattended-no-decision-marker", (CLOSE,)), al.narrowed)
        self.assertIn(CLOSE, al.human_answers)                                       # D17
        self.assertIn(CLOSE, self.allowed(mode="unattended", decision_marker=True).answers)

    def test_a_risky_analysis_is_a_humans_close(self):
        al = self.allowed(close_risk=True)
        self.assertNotIn(CLOSE, al.answers)
        self.assertIn(("close-risk", (CLOSE,)), al.narrowed)
        self.assertTrue({"rerun", "escalate"} <= set(al.answers), "only the close is taken away")
        self.assertIn(CLOSE, al.human_answers)

    def test_the_stop_record_names_it_only_when_allowed(self):
        for started, want in ((False, True), (True, False), (None, False)):
            st = {"steps": [{"id": "analyze", "status": "running", "latest_attempt": 1}]}
            if started is not None:
                st["developer_started"] = started
            stop = statemachine.stop_record(st, "analyze", BLOCKED, 3)
            self.assertEqual(CLOSE in stop["allowed_answers"], want)


class Answer(T3.Stage3Case):
    def world(self, kind="other", started=False, analysis=True, **an):
        w = T3.stopped_world(self.subdir(), step="design", **an)
        w.state["developer_started"] = started
        w.write_role("design", 1, TL.work_result(status="blocked", blocked_by={"kind": kind, "note": "already done in #7"}))
        return w

    def request(self, w, **over):
        return T3.stopped_request(w, situation=BLOCKED, step="design",
                                  **dict({"issue_md": "Issue 42\n", "decision_marker": False}, **over))

    def close(self, close={"reason": "completed"}, **over):
        return T3.needs(CLOSE, **dict({"reason": "already-decided", "close": close}, **over))

    def test_the_schema_has_close_only_when_offered(self):
        props = self.schema_of(self.request(self.world()))["properties"]
        self.assertEqual(props["close"]["properties"]["reason"]["enum"], ["completed", "not-planned"])
        props = self.schema_of(self.request(self.world(started=True)))["properties"]
        self.assertNotIn("close", props)
        self.assertNotIn(CLOSE, props["answer"]["enum"])

    def test_other_situations_have_no_close_field(self):
        w = self.world()
        for sit in (SR.SESSION_LIMIT.value, SR.OUTPUT_FORMAT_TWICE.value, SR.ON_FAIL_EXCEEDED.value):
            r = T3.stopped_request(w, situation=sit, step="design")
            self.assertNotIn("close", self.schema_of(r)["properties"], sit)

    def test_the_issue_is_given_so_the_claim_can_be_checked(self):
        inp, _ = self.build(self.request(self.world()))
        self.assertIn("issue.md", inp["in_files"])
        inp, _ = self.build(self.request(self.world(started=True)))
        self.assertNotIn("issue.md", inp["in_files"])
        inp, _ = self.build(self.request(self.world("ambiguous", started=True)))
        self.assertIn("issue.md", inp["in_files"])
        with self.assertRaises(leader.LeaderError):
            self.build(self.request(self.world(), issue_md=None))

    def test_close_is_set_exactly_with_the_answer(self):
        r = self.request(self.world())
        self.assertEqual(self.check(r, self.fit(r, self.close())), [])
        self.assertEqual(self.check(r, self.fit(r, self.close(None))), ["close-mismatch"])
        bad = T3.needs("rerun", step="design", reason="other", close={"reason": "completed"})
        self.assertEqual(self.check(r, self.fit(r, bad)), ["close-mismatch"])
        ok = T3.needs("rerun", step="design", reason="other", close=None)
        self.assertEqual(self.check(r, self.fit(r, ok)), [])
        self.assertEqual(self.check(r, self.fit(r, self.close({"reason": "done"}))), ["answer-schema"])

    def test_risk(self):
        for risk, offered in (("low", True), ("high", False)):
            _, al = self.build(self.request(self.world(risk=risk)))
            self.assertEqual(CLOSE in al.answers, offered, risk)
        w = self.world()
        w.commit_file(f"{TL.SPECS}/analysis.md", "# no machine fields\n")      # no risk can be read: a human's close
        self.assertTrue(leader._close_risk(self.request(w)))

    def test_extra(self):
        self.assertEqual(leader._extra(BLOCKED, self.close(), 3)["close"], {"reason": "completed"})
        self.assertEqual(leader._extra(BLOCKED, T3.needs("rerun", step="design"), 3), {"defer": None, "session": None})

    def test_the_task_text_teaches_it_in_stage_3_only(self):
        from gxengine import instructions
        text = instructions.leader_task_text(BLOCKED, stage=3)
        for must in ("`close-as-decided`", "`close.reason` `completed`", "`not-planned`", "`already-decided`",
                     "no developer step"):
            self.assertIn(must, text)
        self.assertNotIn("close-as-decided", instructions.leader_task_text(BLOCKED, stage=2))


# --- K8-3: end to end ----------------------------------------------------------------------------

def blocked_analyze():
    r = Z.work_result3(note="nothing left to do")
    r.update({"status": "blocked", "outputs": [], "blocked_by": {"kind": "other", "note": "already fixed by issue 12"}})
    return Z.role_scenario3("analyze", structured_output=r, actions=[])


class CloseEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Z.new_tmp()
        self.addCleanup(Z.rmtree, self.tmp)
        rules = Z.gh_rules3()
        for reason in ("completed", "not planned"):
            rules["rules"].insert(0, {"args": ["issue", "close", str(Z.ISSUE), "--repo", Z.REPO, "--reason", reason],
                                      "stdout": ""})
        self.w = Z.Z3World(self.tmp, cfg=Z.config3(), gh=rules)

    def closes(self):
        return [c["argv"][-1] for c in self.w.gh_calls() if c["argv"][:2] == ["issue", "close"]]

    def blocked_call(self, answer, reason, **kw):
        self.w.add(Z.leader_scenario("blocked", Z.envelope(answer, reason, session=None, **kw)))

    def test_the_leader_closes_a_blocked_analyze(self):
        self.w.add(blocked_analyze())
        self.blocked_call(CLOSE, "already-decided", note="Met by issue 12: src/app.py line 1.", close={"reason": "completed"})
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue()[-3000:])
        st = self.w.state()
        self.assertEqual(st["closed"]["reason"], "completed")
        self.assertIsNone(st["stop"])
        self.assertEqual({s["id"]: (s["status"], s["reason"]) for s in st["steps"]},
                         {i: ("skipped", "closed-as-decided") for i in ("analyze", "ac-format", "plan")})
        self.assertEqual(self.closes(), ["completed"])
        self.assertEqual([(c["situation"], c["answer"], c["counted"]) for c in st["leader_calls"]], [("blocked", CLOSE, True)])
        calls = self.w.gh_calls()
        rationale = [i for i, c in enumerate(calls) if c["stdin"] and "guild:closed-as-decided" in c["stdin"]]
        self.assertEqual(len(rationale), 1)
        self.assertLess(rationale[0], next(i for i, c in enumerate(calls) if c["argv"][:2] == ["issue", "close"]))
        self.assertIn("Met by issue 12", calls[rationale[0]]["stdin"])
        self.assertFalse([c for c in calls if "pulls" in " ".join(c["argv"])], "no PR")
        self.assertIsNone(self.w.repo.remote_head("gld/42"))
        self.assertEqual(len(events(self.w.log(), "issue-closed")), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.w.paths().leader_dir(1), "in", "issue.md")))
        self.assertIs(st["developer_started"], False)
        # nothing runs on a closed Issue
        n = len(self.w.claude_calls())
        self.assertEqual(self.w.run(), driver.EXIT_OK)
        self.assertEqual((len(self.w.claude_calls()), self.closes()), (n, ["completed"]))

    def test_a_human_may_close_it_too(self):
        self.w.add(blocked_analyze())
        self.blocked_call("escalate", "needs-human-decision", close=None,
                          recommendation={"answer": CLOSE, "step": None, "note": "met by issue 12"})
        self.assertEqual(self.w.run(), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.w.run(answer={"answer": CLOSE, "note": "ok"}), driver.EXIT_REFUSED, "no close reason")
        self.assertEqual(self.closes(), [])
        rc = self.w.run(answer={"answer": CLOSE, "close_reason": "not-planned", "note": "ok"})
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue()[-3000:])
        self.assertEqual(self.closes(), ["not planned"])

    def test_after_a_developer_step_neither_seat_may(self):
        self.w.add(Z.role_scenario3("analyze"))
        self.w.add(Z.leader_scenario("plan-gate", Z.plan3("bug")))
        for s in ("test-cases", "diagnose"):
            self.w.add(Z.role_scenario3(s))
        r = Z.work_result3(note="cannot")
        r.update({"status": "blocked", "blocked_by": {"kind": "other", "note": "repro: it is fixed already"}})
        self.w.add(Z.role_scenario3("reproduce", structured_output=r, actions=[]))
        self.blocked_call("escalate", "needs-human-decision",
                          recommendation={"answer": "rerun", "step": "diagnose", "note": "x"})
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.w.out.getvalue()[-3000:])
        st = self.w.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("blocked", "reproduce"))
        self.assertIs(st["developer_started"], True)
        with open(os.path.join(self.w.paths().leader_dir(1), "brief.json")) as f:
            self.assertNotIn(CLOSE, json.load(f)["leader"]["allowed_answers"])
        self.assertIn("developer-started", self.leader_input())
        rc = self.w.run(answer={"answer": CLOSE, "close_reason": "completed", "note": "x"})
        self.assertEqual(rc, driver.EXIT_REFUSED)
        self.assertEqual(self.closes(), [])

    def leader_input(self):
        with open(os.path.join(self.w.paths().leader_dir(1), "in", "leader-input.json")) as f:
            return f.read()


if __name__ == "__main__":
    unittest.main()
