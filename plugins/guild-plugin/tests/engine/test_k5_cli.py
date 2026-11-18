"""K5 — `gld_engine.py dev`: the run preflight (kill switch, active plugin version, registry, lock, restart
check), the §2.4 stdout contract and exit codes 0/4/6/75, the stage-boundary checks, the attended channel
(wait / answer / note / hold) and `dev valve` (§10.5 write rules: HALT and human areas survive engine writes,
a released valve is never re-applied, concurrent writers lose nothing)."""

import io
import json
import os
import threading
import time
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from _k4 import K4

from guildcore import valves as VALVES
from guildcore import worker as W
from guildcore.ask import Question
from workflows.dev import cli as CLI
from workflows.dev import judging as JG
from workflows.dev.fsm import Outcome
from workflows.dev.stages import base as B


def plugin_list(*entries):
    def runner(argv, cwd, env, timeout):
        assert argv[1:] == ["plugin", "list", "--json"], argv
        assert os.path.isabs(argv[0])
        return json.dumps([{"id": "guild-plugin@%s" % m, "version": v, "enabled": e} for m, v, e in entries])
    return runner


MINE = None


def mine():
    from guildcore.version import own_version
    return own_version()


class FakeDriver(object):
    calls = []
    outcome = None

    def __init__(self, ports_for, unattended=True, plugin=None, events=None, boundary=None):
        self.ports_for, self.unattended, self.boundary = ports_for, unattended, boundary

    def run(self, n, only=None):
        FakeDriver.calls.append((n, only, self.unattended))
        if self.boundary is not None:
            stop = self.boundary(n)
            if stop is not None:
                return stop
        return FakeDriver.outcome or Outcome(B.StageResult(B.StageResult.DONE), 0)


class Env(object):
    """A K4 harness (fake GitHub, real git repo) + `Deps` pointing the CLI at it."""

    def __init__(self, case, version_entries=None, **kw):
        self.h = K4(case, **kw)
        self.cfgdir = os.path.join(tmpdir(case), "cfg")
        env = dict(os.environ, CLAUDE_CONFIG_DIR=self.cfgdir, GLD_ENGINE_TEST="1", PATH=os.environ["PATH"])
        env.pop("GLD_ENGINE_SKIP_VERSION", None)
        env.pop("GLD_ENGINE_DEV", None)
        self.out, self.err = io.StringIO(), io.StringIO()
        d = CLI.Deps(env=env, cwd=self.h.p.root, out=self.out, err=self.err)
        d.version_runner = plugin_list(*(version_entries if version_entries is not None
                                         else [("deku-claude-plugins", mine(), True)]))
        d.sleep = lambda s: None
        d.driver_cls = FakeDriver
        self.h.p.journal = self.h.journal
        d.ports_for = lambda n, stage, variant=None: self.h.p
        d.spawn = lambda argv, cwd, env, log: (self.spawned.append(argv) or 4242)
        self.spawned = []
        self.d = d
        self.common = d.common()
        FakeDriver.calls = []
        FakeDriver.outcome = None

    def run(self, *args):
        return CLI.main(["run", "--issue", "7"] + list(args), self.d)

    def lines(self):
        return [ln for ln in self.out.getvalue().split("\n") if ln.strip()]

    def progress(self):
        try:
            with open(os.path.join(self.common, "guild", "engine", "7", "progress.log")) as fh:
                return fh.read()
        except IOError:
            return ""


class RunContract(unittest.TestCase):
    def test_unattended_stdout_is_machine_events_only(self):
        e = Env(self)
        self.assertEqual(e.run("--unattended"), 0)
        ls = e.lines()
        self.assertEqual(len(ls), 2)
        self.assertEqual(json.loads(ls[0]), {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}})
        res = json.loads(ls[1])
        self.assertEqual(res["type"], "result")
        self.assertFalse(res["is_error"])
        self.assertIn("start: unattended run #7", e.progress())          # progress → side file
        self.assertEqual(e.err.getvalue(), "")
        self.assertEqual(FakeDriver.calls, [(7, None, True)])

    def test_default_mode_is_unattended(self):
        e = Env(self)
        self.assertEqual(e.run(), 0)
        self.assertEqual(FakeDriver.calls, [(7, None, True)])

    def test_rate_limit_exit_75_always_carries_resets_at(self):
        e = Env(self)
        FakeDriver.outcome = Outcome(None, 75, "rate limited")
        self.assertEqual(e.run("--unattended"), 75)
        ev = json.loads(e.lines()[0])
        self.assertEqual(ev["rate_limit_info"]["status"], "rejected")
        self.assertGreater(ev["rate_limit_info"]["resetsAt"], time.time())

    def test_registry_records_the_common_dir(self):
        e = Env(self)
        e.run("--unattended")
        self.assertEqual([k for k, _x in VALVES.registered(e.d.env)], [os.path.realpath(e.common)])
        e.run("--unattended")
        with open(VALVES.registry_path(e.d.env)) as fh:
            self.assertEqual(len(json.load(fh)), 1)

    def test_only_is_passed_to_the_driver(self):
        e = Env(self)
        e.run("--unattended", "--only", "test")
        self.assertEqual(FakeDriver.calls, [(7, "test", True)])


class KillSwitchAndVersion(unittest.TestCase):
    def test_halt_exits_6_before_any_stage(self):
        e = Env(self)
        VALVES.halt(e.common, "op")
        self.assertEqual(e.run("--unattended"), 6)
        self.assertEqual(json.loads(e.lines()[1])["result"], "halted: kill-switch")
        self.assertEqual(FakeDriver.calls, [])

    def test_version_mismatch_halts(self):
        e = Env(self, version_entries=[("deku-claude-plugins", "0.101.3", True)])
        self.assertEqual(e.run("--unattended"), 6)
        self.assertIn("halted: plugin version mismatch", json.loads(e.lines()[1])["result"])
        self.assertEqual(FakeDriver.calls, [])

    def test_two_enabled_entries_halt(self):
        e = Env(self, version_entries=[("deku-claude-plugins", mine(), True), ("deku-guild-pin", "0.101.3", True)])
        self.assertEqual(e.run("--unattended"), 6)

    def test_disabled_entry_does_not_count(self):
        e = Env(self, version_entries=[("deku-claude-plugins", mine(), True), ("deku-guild-pin", "0.101.3", False)])
        self.assertEqual(e.run("--unattended"), 0)

    def test_not_listed_halts_unless_dev(self):
        e = Env(self, version_entries=[])
        self.assertEqual(e.run("--unattended"), 6)
        self.assertIn("halted: env plugin-not-listed", json.loads(e.lines()[1])["result"])
        e2 = Env(self, version_entries=[])
        e2.d.env["GLD_ENGINE_DEV"] = "1"
        self.assertEqual(e2.run("--unattended"), 0)

    def test_unavailable_cli_warns_and_goes_on(self):
        e = Env(self)
        tries = []

        def broken(argv, cwd, env, timeout):
            tries.append(1)
            raise OSError("timed out")
        e.d.version_runner = broken
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(len(tries), 4)                    # one retry at the start, one at the stage boundary
        self.assertIn("version-check-unavailable", e.progress())
        self.assertNotIn("rate", e.progress().lower().replace("rate_limit", ""))

    def test_boundary_sees_a_halt_written_mid_run(self):
        e = Env(self)
        orig = FakeDriver.run

        def run(self_, n, only=None):
            VALVES.halt(e.common, "op")
            return orig(self_, n, only)
        FakeDriver.run = run
        try:
            self.assertEqual(e.run("--unattended"), 6)
        finally:
            FakeDriver.run = orig

    def test_boundary_sees_a_downgrade_mid_run(self):
        e = Env(self)
        n = []

        def flips(argv, cwd, env, timeout):
            n.append(1)
            v = mine() if len(n) == 1 else "0.101.3"
            return json.dumps([{"id": "guild-plugin@deku-claude-plugins", "version": v, "enabled": True}])
        e.d.version_runner = flips
        self.assertEqual(e.run("--unattended"), 6)


class Busy(unittest.TestCase):
    def test_busy_unattended_exit_4(self):
        e = Env(self)
        lk = W.IssueLock(e.common, 7)
        lk.acquire("unattended")
        try:
            self.assertEqual(e.run("--unattended"), 4)
            self.assertIn("busy", json.loads(e.lines()[1])["result"])
        finally:
            lk.release()
        self.assertEqual(FakeDriver.calls, [])

    def test_detach_never_attaches_to_an_attended_owner(self):
        e = Env(self)
        lk = W.IssueLock(e.common, 7)
        lk.acquire("attended")
        try:
            self.assertEqual(e.run("--unattended", "--detach"), 0)
            self.assertIn("running attended", json.loads(e.lines()[1])["result"])
        finally:
            lk.release()

    def test_detach_attaches_to_an_unattended_owner_and_takes_its_end(self):
        e = Env(self)
        lk = W.IssueLock(e.common, 7)
        lk.acquire("unattended")
        W.Events(e.common, 7).emit("terminal", "2026-11-18T00:00:00Z", exit_code=75, line="rate limited")
        e.d.sleep = lambda s: time.sleep(0.05)
        t = threading.Timer(0.3, lk.release)
        t.start()
        self.assertEqual(e.run("--unattended", "--detach"), 75)
        t.join()


class RestartCheck(unittest.TestCase):
    def test_unknown_create_at_restart_is_env_service_not_a_resend(self):
        e = Env(self, labels=("guild:design",))
        j = e.h.journal
        j.intent(op="issue:create", target="7-a tok", key="7-a", token="tok", find_label="guild:child",
                 since="2026-11-15T23:00:00Z", entry_id=None, stage=None, step_id=None, attempt=0)
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(FakeDriver.calls, [])                            # no stage ran
        self.assertIn("guild:needs-human", e.h.labels())
        nh = [c["body"] for c in e.h.gh.fx["issues"]["7"]["comments"] if "guild:needs-human" in c["body"]]
        self.assertIn("env: service — restart check #7", nh[-1])
        self.assertIn("resume after", nh[-1])
        self.assertEqual([c for c in e.h.w.calls if c[0] == "create_issue"], [])

    def test_not_landed_label_write_is_closed_redo(self):
        e = Env(self)
        j = e.h.journal
        j.intent(op="labels", target="7", add=["guild:design"], remove=[], entry_id=None, stage=None, step_id=None,
                 attempt=0)
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(j.intent_only(), [])
        self.assertTrue(any(x.get("redo") for x in j.entries if x.get("kind") == "done"))


class Attended(unittest.TestCase):
    def test_run_attended_starts_a_detached_worker(self):
        e = Env(self)
        self.assertEqual(e.run("--attended"), 0)
        self.assertIn("--worker", e.spawned[0])
        self.assertTrue(json.loads(e.lines()[1])["started"])

    def test_worker_emits_terminal_event_not_stdout_contract(self):
        e = Env(self)
        self.assertEqual(e.run("--attended", "--worker"), 0)
        evs = W.Events(e.common, 7).read()
        self.assertEqual(evs[-1]["type"], "terminal")
        self.assertEqual(evs[-1]["token"], "OK DONE")
        self.assertEqual(e.lines(), [])

    def test_worker_after_an_ask_emits_no_terminal(self):
        e = Env(self)
        FakeDriver.outcome = Outcome(B.StageResult(B.StageResult.ASK, line="q", qid="D1"), 0)
        e.run("--attended", "--worker")
        self.assertEqual([x for x in W.Events(e.common, 7).read() if x["type"] == "terminal"], [])

    def test_wait_returns_on_ask(self):
        e = Env(self)
        W.Events(e.common, 7).emit("progress", "t", line="analyze")
        W.Events(e.common, 7).emit("ask", "t", qid="D3", kind="readiness", question="go?", options=[])
        self.assertEqual(CLI.main(["wait", "--issue", "7", "--max-seconds", "1"], e.d), 0)
        got = json.loads(e.lines()[1])
        self.assertEqual([x["type"] for x in got["events"]], ["progress", "ask"])

    def test_wait_reports_a_dead_worker(self):
        e = Env(self)
        CLI.main(["wait", "--issue", "7", "--max-seconds", "0"], e.d)
        got = json.loads(e.lines()[1])
        self.assertEqual(got["events"][-1]["type"], "terminal")
        self.assertIn("not running", got["events"][-1]["line"])

    def test_answer_resolves_the_pending_question(self):
        e = Env(self)
        e.h.p.unattended = False
        q = Question("readiness", "go?", [{"token": "go", "label": "go"}, {"token": "stop", "label": "stop"}])
        r = B.ask(e.h.p, "analyze", q, "go?")
        self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", r.qid, "--choice", "go"], e.d), 0)
        self.assertTrue(json.loads(e.lines()[1])["answered"])
        self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", r.qid, "--choice", "go"], e.d), 64)

    def test_note_is_a_human_directive_in_every_judge_brief_of_the_stage(self):
        e = Env(self)
        self.assertEqual(CLI.main(["note", "--issue", "7", "--text", "keep the old API", "--stage", "design"], e.d), 0)
        from workflows.dev import ports as PO
        ds = PO.directives_of(e.h.p, "design")
        self.assertEqual([d["text"] for d in ds], ["keep the old API"])
        e.h.p.directives = ds
        sp = JG.spec(e.h.p, "SPLIT", [("x", "y")], "design", "E2")
        self.assertIn("keep the old API", str(sp.brief_parts))
        self.assertEqual(PO.directives_of(e.h.p, "qa"), [])

    def test_note_and_hold_are_refused_on_an_unattended_owner(self):
        e = Env(self)
        lk = W.IssueLock(e.common, 7)
        lk.acquire("unattended")
        try:
            self.assertEqual(CLI.main(["hold", "--issue", "7"], e.d), 4)
            self.assertEqual(CLI.main(["note", "--issue", "7", "--text", "x"], e.d), 4)
        finally:
            lk.release()

    def test_hold_stops_an_attended_run_at_the_boundary(self):
        e = Env(self)
        lk = W.IssueLock(e.common, 7)
        lk.acquire("attended")
        try:
            self.assertEqual(CLI.main(["hold", "--issue", "7"], e.d), 0)
        finally:
            lk.release()
        e.run("--attended", "--worker")
        evs = W.Events(e.common, 7).read()
        self.assertIn("held", evs[-1]["line"])


class Valves(unittest.TestCase):
    def _e(self):
        return Env(self)

    def test_set_clear_and_effective_order(self):
        e = self._e()
        c = e.common
        VALVES.auto_set(c, "group.STAKES.conservative", True, "tripwire")
        self.assertEqual(VALVES.effective(c, {})["group.STAKES.conservative"], True)
        CLI.main(["valve", "set", "group.STAKES.conservative", "false"], e.d)
        self.assertEqual(VALVES.effective(c, {})["group.STAKES.conservative"], False)    # human beats auto
        CLI.main(["valve", "clear", "group.STAKES.conservative"], e.d)
        self.assertNotIn("group.STAKES.conservative", VALVES.effective(c, {}))
        self.assertFalse(VALVES.auto_set(c, "group.STAKES.conservative", True, "again"))  # released: alarm only
        self.assertNotIn("group.STAKES.conservative", VALVES.effective(c, {}))
        with open(VALVES.paths(c)["log"]) as fh:
            self.assertIn('"op": "alarm"', fh.read())

    def test_values_are_checked(self):
        e = self._e()
        self.assertEqual(CLI.main(["valve", "set", "grading.grader_rate", "0.01"], e.d), 64)   # below the floor
        self.assertEqual(CLI.main(["valve", "set", "nonsense.key", "1"], e.d), 64)
        self.assertEqual(CLI.main(["valve", "set", "judges.STAKES.model", "opus"], e.d), 0)
        with self.assertRaises(VALVES.ValveError):
            VALVES.auto_set(e.common, "grading.grader_rate", 0.5)                            # human area only

    def test_valve_reaches_engine_cfg_and_judge_tier(self):
        e = self._e()
        CLI.main(["valve", "set", "handoff_judge", "always"], e.d)
        CLI.main(["valve", "set", "judges.STAKES.model", "opus"], e.d)
        e.h.p.valves = VALVES.effective(e.common, {})
        self.assertEqual(e.h.p.engine_cfg("handoff_judge"), "always")
        sp = JG.spec(e.h.p, "STAKES", [("x", "y")], "analyze", "A6")
        self.assertEqual(sp.model, "opus")
        self.assertEqual(sp.valves.get("judges.STAKES.model"), "opus")          # in the judge cache key

    def test_halt_resume_all_walks_the_registry(self):
        e = self._e()
        e.run("--unattended")
        other = os.path.join(tmpdir(self), "gone", ".git")
        VALVES.register(other, e.d.env)
        CLI.main(["valve", "halt", "--all"], e.d)
        rep = json.loads(e.lines()[-1])
        self.assertEqual(sorted(r.get("skipped", "halted") for r in rep["repos"]), ["halted", "missing"])
        self.assertTrue(VALVES.halted(e.common))
        CLI.main(["valve", "resume", "--all"], e.d)
        self.assertFalse(VALVES.halted(e.common))

    def test_concurrent_engine_and_human_writes_lose_nothing(self):
        e = self._e()
        c = e.common

        def engine():
            for i in range(30):
                VALVES.auto_set(c, "group.G%d.conservative" % i, True, "tripwire")

        def human():
            for i in range(30):
                VALVES.human_set(c, "group.H%d.conservative" % i, True, "op")
            VALVES.halt(c, "op")
        ts = [threading.Thread(target=engine), threading.Thread(target=human)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        data = VALVES.load(c)
        self.assertEqual(len(data["auto"]), 30)
        self.assertEqual(len(data["human"]["set"]), 30)
        self.assertTrue(VALVES.halted(c))

    def test_worktree_b_sees_a_valve_written_in_worktree_a(self):
        e = self._e()
        import subprocess
        wt = os.path.join(tmpdir(self), "wtB")
        subprocess.run(["git", "worktree", "add", "-q", "-b", "b", wt], cwd=e.h.p.root, check=True)
        CLI.main(["valve", "set", "split.require_human", "true"], e.d)
        d2 = CLI.Deps(env=e.d.env, cwd=wt, out=io.StringIO())
        self.assertEqual(os.path.realpath(d2.common()), os.path.realpath(e.common))
        self.assertTrue(VALVES.effective(d2.common(), {})["split.require_human"])


if __name__ == "__main__":
    unittest.main()
