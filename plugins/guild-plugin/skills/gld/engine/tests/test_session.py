"""U6 role session runner — fake claude only (never a paid call)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from gxengine import canary, codes, defaults, render, session
from tests import a_layout
from tests.helpers import fakes


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lay = a_layout.Layout(self._tmp.name)
        self.log = os.path.join(self.lay.tmp, "claude-log")

    def tearDown(self):
        self._tmp.cleanup()

    def run_role(self, scenarios, step="design", role="tech-lead", attempt=1, limits=None, **kw):
        inp = self.lay.role_input(step, role, attempt=attempt, **kw)
        env = self.lay.env(scenarios=scenarios, log=self.log)
        return session.run_session(inp, self.lay.attempt_dir(step, attempt), env,
                                   claude_bin=fakes.FAKE_CLAUDE, limits=limits)


class Normal(Base):
    def test_ok_judge(self):
        r = self.run_role(["ok-judge.json"], outputs=["docs/specs/42/design.md"])
        self.assertEqual(r.end, codes.SessionEnd.COMPLETED.value)
        self.assertFalse(hasattr(r, "init"), "no system/init comparison (FC decision D)")
        self.assertEqual(r.exit_code, 0)
        self.assertEqual(r.structured["status"], "done")
        self.assertIsNotNone(r.session_id)
        self.assertEqual(r.cli_version, "2.1.323")
        self.assertIsInstance(r.cost["cost_usd"], float)
        self.assertTrue(os.path.isfile(os.path.join(self.lay.wt, "docs/specs/42/design.md")))
        # the stream is recorded verbatim, settings written, stderr file exists
        d = self.lay.attempt_dir("design", 1)
        self.assertGreater(len(fakes.read_stream(os.path.join(d, "stream.jsonl"))), 5)
        with open(os.path.join(d, "settings.json"), encoding="utf-8") as f:
            st = json.load(f)
        self.assertTrue(st["sandbox"]["enabled"])
        self.assertTrue(os.path.isfile(os.path.join(d, "stderr.log")))

    def test_argv_env_cwd(self):
        self.run_role(["ok-judge.json"], outputs=["docs/specs/42/design.md"])
        call = fakes.claude_calls(self.log)[0]
        argv = call["argv"]
        self.assertEqual(call["cwd"], self.lay.wt)
        self.assertEqual(argv[0], "-p")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "8.0")
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Write")
        self.assertIn("--json-schema", argv)
        self.assertIn("--settings", argv)
        for flag in render.FORBIDDEN_FLAGS:
            self.assertNotIn(flag, argv)
        env = call["env"]
        self.assertEqual(env["HOME"], self.lay.home)                 # (fake) home = paths.home
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], self.lay.config_dir)
        self.assertEqual(env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"], "1")
        self.assertFalse([k for k in env if k.startswith(("GH_", "GITHUB_", "ANTHROPIC_"))])

    def test_home_and_config_dir_come_from_paths_not_the_caller(self):
        inp = self.lay.role_input("design", "tech-lead", outputs=["docs/specs/42/design.md"])
        env = self.lay.env(scenarios=["ok-judge.json"], log=self.log)
        env["HOME"] = "/nonexistent-real-home"
        env["CLAUDE_CONFIG_DIR"] = "/nonexistent-cfg"
        session.run_session(inp, self.lay.attempt_dir("design", 1), env, claude_bin=fakes.FAKE_CLAUDE)
        call = fakes.claude_calls(self.log)[0]
        self.assertEqual(call["env"]["HOME"], self.lay.home)
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], self.lay.config_dir)

    def test_group_killed_at_the_end(self):
        # the session leaves a background child; the engine kills the whole group
        pidfile = os.path.join(self.lay.tmp, "child.pid")
        scn = self.lay.scenario("bg.json", {
            "format": 1, "stream": fakes.scn("../f2/r4.jsonl"), "init_from_argv": True,
            "structured_output": a_layout.work_result(),
            "actions": [{"at": "before_result", "op": "git", "args": ["--version"]}]})
        # spawn a sleeper in the same group via a wrapper claude
        wrapper = os.path.join(self.lay.tmp, "bin", "claude")
        os.makedirs(os.path.dirname(wrapper))
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(f"#!/bin/sh\nif [ \"$1\" = --version ]; then exec {fakes.FAKE_CLAUDE} \"$@\"; fi\n"
                    f"sleep 300 & echo $! > {pidfile}\nexec {fakes.FAKE_CLAUDE} \"$@\"\n")
        os.chmod(wrapper, 0o755)
        inp = self.lay.role_input("design", "tech-lead", outputs=[])
        env = self.lay.env(scenarios=[scn], log=self.log)
        r = session.run_session(inp, self.lay.attempt_dir("design", 1), env, claude_bin=wrapper)
        self.assertEqual(r.end, codes.SessionEnd.COMPLETED.value)
        with open(pidfile, encoding="utf-8") as f:
            pid = int(f.read())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_a_child_outside_the_group_holding_stdout_does_not_keep_the_engine(self):
        # Q6 (the runner defect Q5 measured, same pattern here): a child that leaves the group
        # (setsid) and keeps stdout open used to block the pipe close until it ended. The pid
        # comes back in a file — no machine-wide process search.
        side = os.path.realpath(tempfile.mkdtemp(prefix="gx-escape-"))   # outlives tearDown's cleanup
        self.addCleanup(shutil.rmtree, side, True)
        ready, stop = os.path.join(side, "escaped.pid"), os.path.join(side, "stop")
        self.addCleanup(lambda: open(stop, "w").close())         # lets the escaped child end (runs first)
        escape = ("import os,sys,time\nos.setsid()\nopen(sys.argv[1]+'.tmp','w').write(str(os.getpid()))\n"
                  "os.rename(sys.argv[1]+'.tmp',sys.argv[1])\nend=time.monotonic()+60\n"
                  "while time.monotonic()<end and not os.path.exists(sys.argv[2]): time.sleep(0.05)\n")
        wrapper = os.path.join(self.lay.tmp, "bin", "claude")
        os.makedirs(os.path.dirname(wrapper))
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(f"#!/bin/sh\nif [ \"$1\" = --version ]; then exec {fakes.FAKE_CLAUDE} \"$@\"; fi\n"
                    f"{sys.executable} -I -c \"{escape}\" {ready} {stop} &\n"
                    f"while [ ! -f {ready} ]; do sleep 0.05; done\nexec {fakes.FAKE_CLAUDE} \"$@\"\n")
        os.chmod(wrapper, 0o755)
        scn = self.lay.scenario("escape.json", {"format": 1, "stream": fakes.scn("../f2/r4.jsonl"),
                                                "init_from_argv": True, "structured_output": a_layout.work_result()})
        inp = self.lay.role_input("design", "tech-lead", outputs=[])
        env = self.lay.env(scenarios=[scn], log=self.log)
        old = session.KILL_GRACE_S, session.EXIT_DRAIN_S
        session.KILL_GRACE_S, session.EXIT_DRAIN_S = 1.0, 0.5
        try:
            t = time.monotonic()
            r = session.run_session(inp, self.lay.attempt_dir("design", 1), env, claude_bin=wrapper)
            elapsed = time.monotonic() - t
        finally:
            session.KILL_GRACE_S, session.EXIT_DRAIN_S = old
        self.assertLess(elapsed, 15, "waited for the escaped child")
        with open(ready, encoding="utf-8") as f:
            os.kill(int(f.read()), 0)          # still alive: the pipe really was held open
        self.assertEqual(r.end, codes.SessionEnd.COMPLETED.value)
        self.assertIsNotNone(r.structured)
        self.assertIn(session.STREAM_CUT_WARNING.format(s=1.0), r.warnings)

    def test_resume_argv(self):
        self.run_role(["ok-judge.json"], step="implement", role="developer", resume="abc-123")
        argv = fakes.claude_calls(self.log)[0]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], "abc-123")


class InitListsDiffer(Base):
    """FC decision D (2026-11-28): the init lists are not compared — whatever they say, the session runs."""

    def assertRanOn(self, r):
        self.assertEqual(r.end, codes.SessionEnd.COMPLETED.value)
        self.assertIsNone(r.killed)
        self.assertIsNotNone(r.structured)

    def test_other_tools_skills_plugins_do_not_stop_the_session(self):
        r = self.run_role(["init-lists-differ.json"], outputs=["docs/specs/42/design.md"])
        self.assertRanOn(r)

    def test_another_builtin_plugin_agent_mcp_server_or_permission_mode_runs_on(self):
        """The FC case (another account: CLI 2.1.326 loads cc-plugin-sec-default@builtin) and its kin."""
        for n, init in enumerate(({"plugins": [{"name": "cc-plugin-sec-default", "source": "cc-plugin-sec-default@builtin"}]},
                                  {"agents": ["claude", "browser"]}, {"mcp_servers": [{"name": "x", "status": "connected"}]},
                                  {"permissionMode": "acceptEdits"}, {"claude_code_version": "2.1.326"}), 1):
            with self.subTest(init=init):
                scn = self.lay.scenario(f"other-{n}.json", {"format": 1, "stream": fakes.scn("../f2/r4.jsonl"),
                                                            "init_from_argv": True, "init": init,
                                                            "structured_output": a_layout.work_result()})
                inp = self.lay.role_input("design", "tech-lead", attempt=n)
                env = self.lay.env(scenarios=[scn], log=f"{self.log}-{n}")     # the fake counts calls per log
                r = session.run_session(inp, self.lay.attempt_dir("design", n), env, claude_bin=fakes.FAKE_CLAUDE)
                self.assertRanOn(r)

    def test_an_unknown_cli_version_spawns(self):
        inp = self.lay.role_input("design", "tech-lead", outputs=["docs/specs/42/design.md"])
        env = self.lay.env(scenarios=["ok-judge.json"], log=self.log, version="9.9.9 (Claude Code)")
        r = session.run_session(inp, self.lay.attempt_dir("design", 1), env, claude_bin=fakes.FAKE_CLAUDE)
        self.assertRanOn(r)
        self.assertEqual(r.cli_version, "9.9.9")
        self.assertEqual(len(fakes.claude_calls(self.log)), 1)

    def test_no_init_event_is_an_ordinary_session(self):
        """No init (or an event before it) was an init mismatch; now only the result decides."""
        scn = self.lay.scenario("noinit.json", {"format": 1, "events": [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
            {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.01}]})
        r = self.run_role([scn])
        self.assertEqual(r.end, codes.SessionEnd.COMPLETED.value)
        self.assertIsNone(r.killed)
        self.assertIsNone(r.model)
        scn = self.lay.scenario("empty.json", {"format": 1, "events": []})
        env = self.lay.env(scenarios=[scn], log=self.log + "-2")
        r = session.run_session(self.lay.role_input("design", "tech-lead", attempt=2),
                                self.lay.attempt_dir("design", 2), env, claude_bin=fakes.FAKE_CLAUDE)
        self.assertEqual(r.end, codes.SessionEnd.ERROR.value, "no result event is still an error end")


class Limits(Base):
    def test_no_output_kill(self):
        t = time.monotonic()
        # the floor is bash_timeout + grace; pass a tiny bash timeout through a patched floor
        old = session.NO_OUTPUT_GRACE_S
        session.NO_OUTPUT_GRACE_S = 0
        try:
            inp = self.lay.role_input("design", "tech-lead")
            inp.bash_timeout_ms = 1000
            env = self.lay.env(scenarios=["no-output-hang.json"], log=self.log)
            r = session.run_session(inp, self.lay.attempt_dir("design", 1), env, claude_bin=fakes.FAKE_CLAUDE,
                                    limits={"no_output_s": 1})
        finally:
            session.NO_OUTPUT_GRACE_S = old
        self.assertEqual(r.end, codes.SessionEnd.NO_OUTPUT.value)
        self.assertEqual(r.killed, codes.SessionEnd.NO_OUTPUT.value)
        self.assertLess(time.monotonic() - t, 20)

    def test_wall_clock_kill(self):
        scn = self.lay.scenario("slow.json", {"format": 1, "stream": fakes.scn("../f2/r4.jsonl"),
                                              "init_from_argv": True, "line_delay_s": 0.5})
        r = self.run_role([scn], limits={"wall_clock_s": 1})
        self.assertEqual(r.end, codes.SessionEnd.WALL_CLOCK.value)

    def test_no_output_floor_is_the_bash_timeout(self):
        inp = self.lay.role_input("design", "tech-lead")
        lim = session.session_limits(inp, {"no_output_s": 1})
        self.assertEqual(lim["no_output_s"], 60 + session.NO_OUTPUT_GRACE_S)
        self.assertEqual(session.session_limits(inp)["wall_clock_s"],
                         session.PROVISIONAL_WALL_CLOCK_S[codes.RoleClass.JUDGE.value])
        with self.assertRaises(session.SessionError):
            session.session_limits(inp, {"turns": 3})
        with self.assertRaises(session.SessionError):
            session.session_limits(inp, {"wall_clock_s": 0})

    def test_budget_reached(self):
        r = self.run_role(["budget-reached.json"])
        self.assertEqual(r.end, codes.SessionEnd.BUDGET.value)
        self.assertEqual(r.exit_code, 1)

    def test_budget_by_cost(self):
        scn = self.lay.scenario("cost.json", {"format": 1, "stream": fakes.scn("../f2/r4.jsonl"),
                                              "init_from_argv": True,
                                              "result": {"subtype": "error_other", "is_error": True,
                                                         "total_cost_usd": 8.5}, "exit_code": 1})
        self.assertEqual(self.run_role([scn]).end, codes.SessionEnd.BUDGET.value)

    def test_budget_end_as_the_real_cli_reports_it(self):
        """P4 real canary (CLI 2.1.323): terminal_reason "budget_exhausted" — alone it is a budget end too."""
        scn = self.lay.scenario("bx.json", {"format": 1, "stream": fakes.scn("../f2/r4.jsonl"),
                                            "init_from_argv": True,
                                            "result": {"subtype": "error_during_execution", "is_error": True,
                                                       "terminal_reason": "budget_exhausted", "total_cost_usd": 0.1},
                                            "exit_code": 1})
        self.assertEqual(self.run_role([scn]).end, codes.SessionEnd.BUDGET.value)

    def test_error_exit(self):
        scn = self.lay.scenario("err.json", {"format": 1, "stream": fakes.scn("../f2/r4.jsonl"),
                                             "init_from_argv": True, "exit_code": 2, "stderr": "boom"})
        r = self.run_role([scn])
        self.assertEqual(r.end, codes.SessionEnd.ERROR.value)
        with open(r.stderr_file, encoding="utf-8") as f:
            self.assertEqual(f.read(), "boom")

    def test_rate_limit_rejected(self):
        scn = fakes.scn("a-rate-limit-rejected.json")
        r = self.run_role([scn])
        self.assertEqual(r.end, codes.SessionEnd.ERROR.value)
        self.assertEqual(r.quota_reset_at, 1795407000)


class NoStructured(Base):
    def test_no_structured_output(self):
        r = self.run_role(["no-structured-output.json"])
        self.assertEqual(r.end, codes.SessionEnd.COMPLETED.value)
        self.assertIsNone(r.structured)


class Preconditions(Base):
    def test_specs_dir_required(self):
        os.rmdir(os.path.join(self.lay.wt, "docs/specs/42"))
        with self.assertRaises(session.SessionError) as cm:
            self.run_role(["ok-judge.json"])
        self.assertIn("docs/specs/42", str(cm.exception))
        self.assertEqual(fakes.claude_calls(self.log), [])

    def test_specs_dir_symlink_refused(self):
        os.rmdir(os.path.join(self.lay.wt, "docs/specs/42"))
        os.symlink(self.lay.tmp, os.path.join(self.lay.wt, "docs/specs/42"))
        with self.assertRaises(session.SessionError):
            self.run_role(["ok-judge.json"])

    def test_budget_must_be_the_role_kind_value(self):
        with self.assertRaises(session.SessionError):
            self.run_role(["ok-judge.json"], budget=3.0)
        self.assertEqual(fakes.claude_calls(self.log), [])

    def test_budget_table(self):
        self.assertEqual(session.session_budget("developer"), 15.0)
        self.assertEqual(session.session_budget("tech-lead/review"), 8.0)
        self.assertEqual(session.session_budget("tester", defaults.FORMAT_REPAIR_BUDGET_KEY), 1.0)
        self.assertEqual(session.session_budget("leader"), 6.0)   # stage-2 contract (V1, D10)
        with self.assertRaises(session.SessionError):
            session.session_budget("integration")      # not in the table: no session
        with self.assertRaises(session.SessionError):
            session.session_budget("mystery-role")

    def test_attempt_folder_used_once(self):
        self.run_role(["ok-judge.json"], outputs=["docs/specs/42/design.md"])
        with self.assertRaises(session.SessionError):
            self.run_role(["ok-judge.json", "ok-judge.json"], outputs=["docs/specs/42/design.md"])

    def test_missing_config_dir(self):
        os.rmdir(self.lay.config_dir)
        with self.assertRaises(session.SessionError):
            self.run_role(["ok-judge.json"])

    def test_needs_role_input(self):
        with self.assertRaises(session.SessionError):
            session.run_session(object(), self.lay.tmp, {}, claude_bin=fakes.FAKE_CLAUDE)


class Helpers(unittest.TestCase):
    def test_cli_version(self):
        env = fakes.fake_env()
        self.assertEqual(session.cli_version(fakes.FAKE_CLAUDE, env), "2.1.323")
        env["GLD_FAKE_CLAUDE_VERSION"] = "nonsense"
        with self.assertRaises(session.SessionError):
            session.cli_version(fakes.FAKE_CLAUDE, env)

    def test_choose_resume(self):
        st = {"session_id": "s1", "resume_count": 0}
        self.assertEqual(session.choose_resume("developer", st, "sonnet", "sonnet"), "s1")
        self.assertIsNone(session.choose_resume("developer", st, "opus", "sonnet"))      # model changed
        self.assertIsNone(session.choose_resume("tester", st, "sonnet", "sonnet"))
        self.assertIsNone(session.choose_resume("developer", {"session_id": "s1", "resume_count": 2},
                                                "sonnet", "sonnet"))
        self.assertIsNone(session.choose_resume("developer", {"session_id": None}, "sonnet", "sonnet"))

    def test_kill_group(self):
        p = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"], start_new_session=True)
        session.kill_group(p)
        self.assertIsNotNone(p.returncode)

    def test_session_result_fields(self):
        with self.assertRaises(ValueError):
            session.SessionResult(end="weird")
        with self.assertRaises(TypeError):
            session.SessionResult(end="completed", bogus=1)
        with self.assertRaises(TypeError):
            session.SessionResult(end="completed", init=None)          # FC decision D: no init field


class Stage3(unittest.TestCase):
    """E17 budgets and the E27 resume rule."""

    def test_the_budget_table_of_the_stage(self):
        self.assertEqual(session.session_budget("security/review", stage=3), 8.0)
        self.assertEqual(session.session_budget("developer", stage=3), session.session_budget("developer"))
        for stage in (1, 2):
            with self.assertRaises(session.SessionError):
                session.session_budget("security/review", stage=stage)
        with self.assertRaises(session.SessionError):
            session.session_budget("nobody", stage=3)

    def test_run_session_checks_the_stage_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = a_layout.Layout(tmp)
            inp = lay.role_input("security-review", "security", checks=True, budget=8.0, model="opus", effort="high")
            with self.assertRaises(session.SessionError):
                session.run_session(inp, lay.attempt_dir("security-review", 1), lay.env(scenarios=["ok-judge.json"]),
                                    claude_bin=fakes.FAKE_CLAUDE)
            r = session.run_session(inp, lay.attempt_dir("security-review", 1), lay.env(scenarios=["ok-judge.json"]),
                                    claude_bin=fakes.FAKE_CLAUDE, stage=3)
            self.assertEqual(r.end, "completed")

    def test_tm5_resume(self):
        st = {"session_id": "sid", "resume_count": 0}
        pick = session.choose_resume
        self.assertEqual(pick("developer", st, "sonnet", "sonnet"), "sid")                        # stages 1-2
        self.assertEqual(pick("developer", st, "sonnet", "sonnet", "high", "high"), "sid")
        self.assertIsNone(pick("developer", st, "opus", "sonnet", "high", "high"))
        self.assertEqual(pick("developer", st, "sonnet", "sonnet", "xhigh", "high"), "sid")       # Z3: effort only
        self.assertIsNone(pick("developer", st, "sonnet", "sonnet", "high", None))
        self.assertIsNone(pick("tester", st, "sonnet", "sonnet", "high", "high"))


if __name__ == "__main__":
    unittest.main()
