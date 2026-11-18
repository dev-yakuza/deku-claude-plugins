"""K5 review r1 — regressions for M1–M5, the cheap minors and the user decisions of 2026-11-18.

M1  one lock discipline: a parent drives (and restart-checks) a child only while holding THAT child's lock;
    the restart check reaps only a crashed run's groups (lock held + journaled owner dead)
M2  `hold` (and any non-DONE child end) stops a split parent — no next child, no integration
M3  the budget answer is acted on: `continue` raises the ceiling once (recorded), `stop` holds; one question per ceiling
M4  setup / restart-check GitHub errors end through the FSM's §2.4 mapping (3 / 75 / env: service / defect / 1)
M5  `--unattended --detach` starts a detached worker and returns; a second call never starts a second writer
decision 2  an unattended unknown create → exit 75 at its settle time; the supervisor's resume re-checks it
m1 title trust · m2 env valves pass the floor · m3 `status running` shows HALT · m4/m5/m9 supervisor exits ·
m6 test isolation (version --active, status --all-repos, claude child) · m8 `--expect-type`
"""

import json
import os
import subprocess
import sys
import time
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from _k4 import decision
from test_k5_cli import Env, FakeDriver

from guildcore import ask as ASK
from guildcore import cost as COST
from guildcore import journal as J
from guildcore import valves as VALVES
from guildcore import worker as W
from guildcore.adapters import claude as C
from guildcore.adapters.gh import GhError, GhWriteError
from guildcore.decisions import DecisionLog, DecisionWriter
from workflows.dev import cli as CLI
from workflows.dev import fsm as F
from workflows.dev.stages import base as B
from workflows.dev.stages.base import StageResult


def kid(n, labels=("guild:child", "guild:analyze")):
    return {"number": n, "title": "[Guild子] k%d" % n, "body": "s\n\nParent Issue: #7\n", "state": "OPEN",
            "labels": [{"name": lb} for lb in labels], "comments": [], "timeline": []}


def child_ports(e, unattended=True):
    h = e.h

    def pf(n, stage, variant=None):
        if n == h.n:
            return h.p
        p = B.Ports(n, h.gh, h.writer, DecisionWriter(h.writer, n, h.clock), h.clock, h.p.config, h.p.root,
                    unattended=unattended, run_role=h.p.run_role, judge=h.p.judge, capture=h.p.capture)
        p.events = h.p.events
        p.git_dir = h.p.git_dir
        return p
    return pf


def real_driver(stages):
    class D(F.Driver):
        def __init__(self, ports_for, unattended=True, plugin=None, events=None, boundary=None):
            F.Driver.__init__(self, ports_for, unattended=unattended, plugin=plugin, stages=stages, events=events,
                              boundary=boundary)
    return D


def sleeper(case):
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    case.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait()))
    return p


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def result(e):
    return json.loads(e.lines()[-1])["result"]


# ---- M1 ------------------------------------------------------------------------------------------------------

class M1ChildLock(unittest.TestCase):
    def _parent(self, **kw):
        e = Env(self, labels=("guild:children",), issues={"8": kid(8)}, **kw)
        e.d.ports_for = child_ports(e)
        return e

    def test_other_run_holds_8_parent_neither_kills_nor_drives_it(self):
        """The review's scenario A: a person runs #8 (lock 8, its developer group journaled by that live run)."""
        e = self._parent()
        s = sleeper(self)
        J.Journal(e.h.p.git_dir, 8).record_pid("developer", s.pid, os.getpgid(s.pid), C.process_start(s.pid))
        ran = []

        def an(p, **k):
            ran.append(p.issue)
            return StageResult(StageResult.DONE)
        e.d.driver_cls = real_driver({"analyze": an})
        lk = W.IssueLock(e.common, 8)
        lk.acquire("attended")
        try:
            rc = e.run("--unattended")
        finally:
            lk.release()
        self.assertEqual(rc, 4)                                          # busy: the supervisor waits, then skips
        self.assertIn("busy: child #8 of #7 is held by an attended run", result(e))
        self.assertIsNone(s.poll())                                      # the other run's process lives
        self.assertEqual(ran, [])                                        # #8 never driven by the parent
        self.assertIn("child #8 is held by an attended run", e.progress())

    def test_lock_held_protects_even_a_dead_owner_record(self):
        e = self._parent()
        s = sleeper(self)
        J.Journal(e.h.p.git_dir, 8).append("pid", who="developer", pid=s.pid, pgid=os.getpgid(s.pid),
                                           start_time=C.process_start(s.pid), owner=dead_pid(), owner_start="x")
        e.d.driver_cls = real_driver({})
        lk = W.IssueLock(e.common, 8)
        lk.acquire("unattended")
        try:
            e.run("--unattended")
        finally:
            lk.release()
        self.assertIsNone(s.poll())

    def test_crashed_childs_group_is_reaped_under_its_lock(self):
        e = self._parent()
        s = sleeper(self)
        J.Journal(e.h.p.git_dir, 8).append("pid", who="developer", pid=s.pid, pgid=os.getpgid(s.pid),
                                           start_time=C.process_start(s.pid), owner=dead_pid(), owner_start="x")

        def an(p, **k):
            return StageResult(StageResult.PAUSE, cause="stop here")
        e.d.driver_cls = real_driver({"analyze": an})
        e.run("--unattended")
        s.wait(timeout=10)
        self.assertIsNotNone(s.poll())

    def test_parent_holds_the_childs_lock_while_driving_it(self):
        """Scenario B: while the parent drives #8, a second run on #8 is busy (one writer per Issue)."""
        e = self._parent()
        seen = []

        def an(p, **k):
            other = W.IssueLock(e.common, p.issue)
            try:
                other.acquire("attended")
                seen.append("free")
                other.release()
            except W.Busy:
                seen.append("busy")
            return StageResult(StageResult.PAUSE, cause="x")
        e.d.driver_cls = real_driver({"analyze": an})
        e.run("--unattended")
        self.assertEqual(seen, ["busy"])
        lk = W.IssueLock(e.common, 8)
        lk.acquire("attended")                                           # released after the child ended
        lk.release()


# ---- M2 ------------------------------------------------------------------------------------------------------

class M2HoldStopsTheParent(unittest.TestCase):
    def test_hold_during_children_is_not_done(self):
        e = Env(self, labels=("guild:children",), issues={"8": kid(8), "9": kid(9)}, unattended=False,
                judges={"INTEGRATE": decision("clean", {"verdict": "clean", "coverage": [], "gaps": []})})
        e.d.ports_for = child_ports(e, unattended=False)
        ran = []

        def an(p, **k):
            ran.append(p.issue)
            p.writer.labels_apply(p.issue, add=["guild:done"], remove=["guild:analyze"])
            W.Events(e.common, 7).request_hold()                        # the person pressed Esc meanwhile
            return StageResult(StageResult.DONE)
        e.d.driver_cls = real_driver({"analyze": an})
        self.assertEqual(e.run("--attended", "--worker"), 0)
        term = [x for x in W.Events(e.common, 7).read() if x["type"] == "terminal"][-1]
        self.assertEqual(ran, [8])                                       # #9 never runs
        self.assertTrue(term["token"].startswith("OK HOLD"), term)
        self.assertIn("자식 #9 에서 멈춤 (OK HOLD", " ".join(term["notes"]))       # stopped before #9 ran
        self.assertIn("guild:children", e.h.labels())                    # no integration, no done
        self.assertEqual(e.h.decisions_of("INTEGRATE"), [])

    def test_hold_token_is_never_ok_done(self):
        self.assertEqual(StageResult(StageResult.HOLD, line="held").token(), "OK HOLD: held")


# ---- M3 ------------------------------------------------------------------------------------------------------

class M3Budget(unittest.TestCase):
    def _b(self, unattended=False):
        e = Env(self, labels=("guild:design",), unattended=unattended)
        e.d._ports = lambda n, s: e.h.p
        b = CLI.make_boundary(e.d, e.common, e.h.p.root, not unattended, W.Events(e.common, 7), 35.0, 7)
        return e, b

    def _spend(self, e, usd):
        COST.record(e.common, {"issue": 7, "total_cost_usd": usd, "kind": "score", "who": "developer"})

    def _budget_q(self, e):
        return [b for b in DecisionLog.load(e.h.gh.comments(7)).blocks
                if b.get("kind") == "budget" and b.get("status") == "pending-human"]

    def test_continue_raises_once_and_the_same_ceiling_is_never_asked_twice(self):
        e, b = self._b()
        self._spend(e, 36.0)
        o1 = b(7)
        self.assertEqual(o1.result.kind, StageResult.ASK)
        o2 = b(7)                                                        # unanswered: the SAME question again
        self.assertEqual(o2.result.qid, o1.result.qid)
        self.assertEqual(len(self._budget_q(e)), 1)
        ASK.answer(e.h.decisions, e.h.writer, 7, o1.result.qid, "continue", login="owner")
        self.assertIsNone(b(7))                                          # the answer is acted on: ceiling 70
        self.assertIsNone(b(7))
        raises = [x for x in DecisionLog.load(e.h.gh.comments(7)).blocks if x.get("point") == "budget"]
        self.assertEqual([(x.get("choice"), x.get("budget_from"), x.get("budget_to")) for x in raises],
                         [("raise", "35.00", "70.00")])                  # applied ONCE
        self.assertTrue(any(x.get("what") == "budget-raise" for x in e.h.journal.entries))
        self._spend(e, 40.0)                                             # 76 > 70: a NEW ceiling → a new question
        o3 = b(7)
        self.assertEqual(o3.result.kind, StageResult.ASK)
        self.assertNotEqual(o3.result.qid, o1.result.qid)

    def test_stop_holds_and_never_reasks(self):
        e, b = self._b()
        self._spend(e, 36.0)
        q = b(7).result.qid
        ASK.answer(e.h.decisions, e.h.writer, 7, q, "stop", login="owner")
        o = b(7)
        self.assertEqual(o.result.kind, StageResult.HOLD)
        self.assertIn("answered stop", o.line)
        self.assertEqual(b(7).result.kind, StageResult.HOLD)
        self.assertEqual(len(self._budget_q(e)), 1)

    def test_unattended_stop_keeps_the_member_paused_without_new_questions(self):
        e, b = self._b(unattended=True)
        self._spend(e, 36.0)
        o = b(7)
        self.assertEqual(o.result.kind, StageResult.PAUSE)
        ASK.answer(e.h.decisions, e.h.writer, 7, o.result.qid, "stop", login="owner")
        n0 = len(e.h.gh.comments(7))
        o2 = b(7)
        self.assertEqual(o2.result.kind, StageResult.PAUSE)
        self.assertIn("guild:needs-human", e.h.labels())
        self.assertEqual(len(self._budget_q(e)), 1)
        b(7)
        self.assertLessEqual(len(e.h.gh.comments(7)), n0 + 2)            # the stop record + applied; no new asks


# ---- M4 ------------------------------------------------------------------------------------------------------

class M4SetupErrors(unittest.TestCase):
    def _e(self, err, times=1):
        e = Env(self, labels=("guild:design",))
        e.h.journal.intent(op="labels", target="7", add=["guild:design"], remove=[], entry_id=None, stage=None,
                           step_id=None, attempt=0)
        orig = e.h.gh.issue
        left = [times]

        def issue(n):
            if left[0] > 0:
                left[0] -= 1
                raise err
            return orig(n)
        e.h.gh.issue = issue
        return e

    def test_502_in_the_restart_check_is_env_service_with_a_result_line(self):
        e = self._e(GhError("HTTP 502: Bad Gateway"))
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(len(e.lines()), 2)
        self.assertIn("guild:needs-human", e.h.labels())
        self.assertIn("env: service", e.h.body_with("needs-human"))
        self.assertEqual(FakeDriver.calls, [])

    def test_auth_in_the_restart_check_is_exit_3(self):
        e = self._e(GhError("HTTP 401: Bad credentials"))
        self.assertEqual(e.run("--unattended"), 3)
        self.assertEqual(json.loads(e.lines()[0])["rate_limit_info"]["status"], "allowed")

    def test_rate_limit_in_the_restart_check_is_exit_75(self):
        e = self._e(GhError("API rate limit exceeded for user"))
        self.assertEqual(e.run("--unattended"), 75)
        self.assertEqual(json.loads(e.lines()[0])["rate_limit_info"]["status"], "rejected")

    def test_a_generic_exception_is_a_defect_pause(self):
        e = self._e(ValueError("boom"))
        self.assertEqual(e.run("--unattended"), 0)
        self.assertIn("defect: engine FAIL — ValueError", e.h.body_with("needs-human"))

    def test_setup_failure_before_ports_is_exit_1_with_a_result_line(self):
        e = Env(self)

        class Broken(object):
            def owner_repo(self):
                raise GhError("HTTP 503: Service Unavailable")
        e.d.ports_for = None
        e.d.gh = lambda: Broken()
        self.assertEqual(e.run("--unattended"), 1)
        ls = e.lines()
        self.assertEqual(len(ls), 2)
        self.assertIn("pause not written", json.loads(ls[1])["result"])

    def test_setup_auth_failure_is_exit_3(self):
        e = Env(self)

        class Broken(object):
            def owner_repo(self):
                raise GhError("HTTP 401: Bad credentials")
        e.d.ports_for = None
        e.d.gh = lambda: Broken()
        self.assertEqual(e.run("--unattended"), 3)


# ---- M5 ------------------------------------------------------------------------------------------------------

class M5Detach(unittest.TestCase):
    def test_detach_starts_a_detached_unattended_worker_and_returns(self):
        e = Env(self)
        self.assertEqual(e.run("--unattended", "--detach"), 0)
        self.assertEqual(len(e.spawned), 1)
        self.assertIn("--unattended", e.spawned[0])
        self.assertIn("--worker", e.spawned[0])
        self.assertNotIn("--detach", e.spawned[0])
        self.assertEqual(FakeDriver.calls, [])
        ls = e.lines()
        self.assertEqual(json.loads(ls[0])["type"], "rate_limit_event")
        self.assertIn("dev wait --issue 7", json.loads(ls[1])["result"])

    def test_a_second_detach_while_the_worker_runs_starts_nothing(self):
        e = Env(self)
        lk = W.IssueLock(e.common, 7)
        lk.acquire("unattended")                                         # the worker started by the first call
        try:
            self.assertEqual(e.run("--unattended", "--detach"), 0)
        finally:
            lk.release()
        self.assertEqual(e.spawned, [])
        self.assertEqual(FakeDriver.calls, [])

    def test_unattended_run_writes_a_terminal_event_for_dev_wait(self):
        e = Env(self)
        self.assertEqual(e.run("--unattended", "--worker"), 0)
        CLI.main(["wait", "--issue", "7", "--max-seconds", "0"], e.d)
        evs = json.loads(e.lines()[-1])["events"]
        self.assertEqual(evs[-1]["type"], "terminal")
        self.assertEqual(evs[-1]["token"], "OK DONE")
        self.assertEqual(evs[-1]["mode"], "unattended")

    def test_a_new_driver_never_takes_an_old_terminal(self):
        e = Env(self)
        W.Events(e.common, 7).emit("terminal", "t", exit_code=0, line="old run")
        e.run("--attended")
        CLI.main(["wait", "--issue", "7", "--max-seconds", "0"], e.d)
        evs = json.loads(e.lines()[-1])["events"]
        self.assertNotIn("old run", [x.get("line") for x in evs])


# ---- user decision 2 -----------------------------------------------------------------------------------------

class Decision2AutoResume(unittest.TestCase):
    def test_fsm_unknown_create_unattended_is_exit_75_at_its_settle_time(self):
        e = Env(self, labels=("guild:design",))

        def de(p, **k):
            ex = GhWriteError("issue:create", "the create of 7-a may have landed — resume after x", "ambiguous")
            ex.retry_at = int(time.time()) + 600
            return B.unknown_create(p, "design", "child creation failed — %s" % ex, ex)
        out = F.Driver(lambda n, s, v=None: e.h.p, unattended=True, stages={"design": de}).run(7)
        self.assertEqual(out.exit_code, 75)
        self.assertGreaterEqual(out.rl.resets_at, int(time.time()) + 590)
        self.assertIn("guild:needs-human", e.h.labels())                # the person still sees why

    def test_attended_unknown_create_stays_a_fail_line(self):
        e = Env(self, labels=("guild:design",), unattended=False)
        ex = GhWriteError("issue:create", "x", "ambiguous")
        r = B.unknown_create(e.h.p, "design", "child creation failed", ex)
        self.assertEqual(r.kind, StageResult.FAIL)
        self.assertIsNone(r.retry_at)

    def test_early_wake_repeats_75_without_touching_github(self):
        e = Env(self)
        J.Journal(e.common, 7).append("event", what="retry-after", at=int(time.time()) + 300)
        n0 = len(e.h.gh.calls)
        self.assertEqual(e.run("--unattended"), 75)
        self.assertEqual(len(e.h.gh.calls), n0)
        self.assertEqual(FakeDriver.calls, [])

    def test_resume_after_the_settle_time_takes_back_needs_human_and_runs(self):
        e = Env(self, labels=("guild:design", "guild:needs-human"))
        J.Journal(e.common, 7).append("event", what="retry-after", at=int(time.time()) - 5)
        self.assertEqual(e.run("--unattended"), 0)
        self.assertNotIn("guild:needs-human", e.h.labels())
        self.assertEqual(FakeDriver.calls, [(7, None, True)])
        self.assertTrue(any(x.get("what") == "retry-cleared" for x in J.Journal(e.common, 7).entries))


# ---- minors ----------------------------------------------------------------------------------------------------

class Minors(unittest.TestCase):
    def test_m1_outsider_title_is_marked(self):
        from workflows.dev.stages import analyze as A
        e = Env(self, author="NONE")
        self.assertTrue(B.title_text(e.h.p, e.h.gh.issue(7)).startswith(A.OUTSIDER_PREFACE))
        e2 = Env(self, author="OWNER")
        self.assertEqual(B.title_text(e2.h.p, e2.h.gh.issue(7)), "#7 %s" % e2.h.gh.issue(7).get("title"))

    def test_m2_env_valves_pass_the_floor_and_never_set_grading(self):
        c = tmpdir(self)
        eff = VALVES.effective(c, {"GLD_ENGINE_VALVE_GRADING__HIGHRISK_HUMAN_RATE": "0",
                                   "GLD_ENGINE_VALVE_GRADING__GRADER_RATE": "0.2",
                                   "GLD_ENGINE_VALVE_HANDOFF_JUDGE": "sometimes",
                                   "GLD_ENGINE_VALVE_SPLIT__REQUIRE_HUMAN": "true"})
        self.assertNotIn("grading.highrisk_human_rate", eff)
        self.assertNotIn("grading.grader_rate", eff)
        self.assertNotIn("handoff_judge", eff)
        self.assertTrue(eff["split.require_human"])

    def test_m3_status_running_shows_halt(self):
        from workflows.status import running as R
        e = Env(self)
        VALVES.halt(e.common, "op")
        halts = []
        rows, missing = R.running([e.common], halts)
        text = R.render_running(rows, missing, halts)
        self.assertIn("HALT  %s" % e.common, text)
        VALVES.resume(e.common, "op")
        halts = []
        rows, missing = R.running([e.common], halts)
        self.assertTrue(R.render_running(rows, missing, halts).startswith("HALT: none"))

    def test_m4_m5_supervisor_and_batch_stop_on_auth_and_a_missing_engine(self):
        from test_k5_supervisor import batch_script, code, render
        s = code(render(self))
        gate = s[s.index("engine_gate() {"):]
        gate = gate[:gate.index("\n}\n")]
        self.assertIn('[ ! -f "$ENGINE" ]', gate)
        self.assertIn("engine-env-missing", gate)
        block = s[s.index('dev run --issue "$ISSUE" --unattended'):s.index("RL_LAST=")]
        self.assertIn('[ "$EXIT_CODE" -eq 2 ] && [ ! -f "$ENGINE" ]', block)
        self.assertIn("engine-gh-auth", block)
        b = code(batch_script())
        self.assertIn('"$EXIT_CODE" -eq 3', b)
        self.assertIn('[ "$EXIT_CODE" -eq 2 ] && [ ! -f "$ENGINE" ]', b)
        self.assertNotIn("sleep 300", b)

    def test_m6_version_active_and_all_repos_need_an_isolated_config(self):
        import gld_engine
        saved = os.environ.pop("CLAUDE_CONFIG_DIR", None)
        try:
            self.assertEqual(gld_engine.main(["version", "--active"]), 64)
            self.assertEqual(gld_engine.main(["status", "running", "--all-repos"]), 64)
            os.environ["CLAUDE_CONFIG_DIR"] = os.path.expanduser("~/.claude")
            self.assertEqual(gld_engine.main(["version", "--active"]), 64)
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = saved

    def test_m6_a_claude_child_needs_isolation_and_a_local_endpoint(self):
        iso = tmpdir(self)
        base = {"GLD_ENGINE_TEST": "1", "CLAUDE_CONFIG_DIR": iso}
        for env in (base, dict(base, ANTHROPIC_BASE_URL="https://api.anthropic.com"),
                    dict(base, ANTHROPIC_BASE_URL="http://127.0.0.1:8080", CLAUDE_CONFIG_DIR=os.path.expanduser("~/.claude")),
                    {"GLD_ENGINE_TEST": "1", "ANTHROPIC_BASE_URL": "http://localhost:9"}):
            with self.assertRaises(C.TestIsolation, msg=env):
                C.run_process(["/usr/bin/claude", "-p"], env, iso, "x", os.path.join(iso, "o"), os.path.join(iso, "e"), 5)
        C.test_isolation_guard(["/x/claude"], dict(base, ANTHROPIC_BASE_URL="http://127.0.0.1:8080"))
        C.test_isolation_guard(["/bin/sh"], {"GLD_ENGINE_TEST": "1"})            # not a claude child

    def test_m8_expect_type_refuses_without_the_label(self):
        e = Env(self, labels=("guild:execute",))
        self.assertEqual(e.run("--unattended", "--only", "execute", "--expect-type", "bug"), 0)
        self.assertIn("has no `type:bug` label", result(e))
        self.assertEqual(FakeDriver.calls, [])
        e2 = Env(self, labels=("guild:execute", "type:bug"))
        e2.run("--unattended", "--only", "execute", "--expect-type", "bug")
        self.assertEqual(FakeDriver.calls, [(7, "execute", True)])

    def test_m8_worker_argv_carries_the_expected_type(self):
        e = Env(self)
        e.run("--attended", "--only", "execute", "--expect-type", "refactor")
        self.assertEqual(e.spawned[0][-2:], ["--expect-type", "refactor"])


if __name__ == "__main__":
    unittest.main()
