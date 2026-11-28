"""P4 canary commands (canaryrun): the role canary's plumbing with a fake boundary (no paid call),
real-home bait (planted, never shown, always removed), the free srt canary under real srt, the
driver's srt-canary check, and `engine.py canary` exit codes."""

import io
import json
import os
import re
import shutil
import tempfile
import unittest

from gxengine import canary, canaryrun, cli, codes, defaults, render, session, streamjson
from tests.helpers import fakes

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(ENGINE)))
SAMPLE = os.path.join(ENGINE, "tests", "fixtures", "claude", "canary", "sample.jsonl")
STEP = re.compile(r"^(\d+)\. (\w+) tool: (.*)$")


def _srt():
    from gxengine import driver, paths as pathsmod
    env = dict(os.environ)
    if os.environ.get("GLD_TEST_SRT"):
        env["GLD_SRT_BIN"] = os.environ["GLD_TEST_SRT"]
    return driver.default_srt_bin(pathsmod.EnginePaths(os.path.expanduser("~/.gld"), "gld/t", 1), env)


def _init_event(tools, cwd):
    with open(SAMPLE, encoding="utf-8") as f:
        init = json.loads(f.readline())
    init.update({"tools": list(tools), "cwd": cwd})
    return init


def _parse_steps(prompt):
    out = []
    for line in prompt.splitlines():
        m = STEP.match(line)
        if m:
            params = {}
            for part in re.finditer(r'(\w+) = ("(?:[^"\\]|\\.)*")', m.group(3)):
                params[part.group(1)] = json.loads(part.group(2))
            out.append((m.group(2), params))
    return out


class FakeBoundary:
    """A run_session stand-in: answers every numbered probe like a correct boundary would
    (refusal text for an expected refusal, the bait token for an allowed read), records what
    it saw. `wrong` = item ids answered the opposite way; `skip` = (attempt, count) — that
    session leaves its last `count` probes out; `structured` = False → no structured output; `init` =
    fields merged into the session's system/init (other lists — never compared, FC decision D)."""

    def __init__(self, wrong=(), skip=None, structured=True, init=None, cost=0.01):
        self.wrong, self.skip, self.structured = set(wrong), skip, structured
        self.init, self.cost = dict(init or {}), cost
        self.calls = []

    def __call__(self, inp, attempt_dir, base_env, claude_bin="claude", limits=None, version=None, budget_key=None,
                 **kw):
        self.calls.append({"attempt": inp.attempt, "budget_key": budget_key, "model": inp.model, "kw": kw,
                           "effort": inp.effort, "home": base_env.get("HOME"), "max": inp.max_budget_usd})
        items = canary.canary_items(inp.paths, inp.config, inp.tools, outputs=inp.outputs, real_home=True)
        steps = _parse_steps(inp.instruction)
        if self.skip and self.skip[0] == inp.attempt:
            steps = steps[:-self.skip[1]]
        tools = list(inp.tools) + ["StructuredOutput"]      # the real CLI with --json-schema (P4)
        ev = [dict(_init_event(tools, inp.paths["worktree"]), claude_code_version=version, **self.init)]
        for n, (tool, params) in enumerate(steps):
            tid = f"toolu_{inp.attempt}_{n}"
            ev.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": tid, "name": tool, "input": params}]}})
            probe = canary.CanaryItem("x", tool, params.get("file_path") or params.get("path") or "/", "refused",
                                      "read" if tool != "Write" else "write",
                                      cmd=params.get("command") if tool == "Bash" else None)
            hit = [i for i in items if i.matches({"name": tool, "input": params})]
            want = hit[0].expect if hit else "refused"
            if hit and hit[0].id in self.wrong:
                want = "allowed" if want == "refused" else "refused"
            if want == "refused":
                res = {"type": "tool_result", "tool_use_id": tid, "is_error": True,
                       "content": "Operation not permitted"}
            else:
                tok = hit[0].token if hit and hit[0].token else ""
                res = {"type": "tool_result", "tool_use_id": tid, "is_error": False, "content": f"ok {tok}"}
            del probe
            ev.append({"type": "user", "message": {"content": [res]}})
        result = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": self.cost,
                  "session_id": "s"}
        if self.structured:
            result["structured_output"] = {"status": "done", "outputs": [], "requests": [], "blocked_by": None,
                                           "discoveries": [], "note": "canary"}
        ev.append(result)
        stream = os.path.join(attempt_dir, "stream.jsonl")
        with open(stream, "w", encoding="utf-8") as f:
            for e in ev:
                f.write(json.dumps(e) + "\n")
        with open(os.path.join(attempt_dir, "stderr.log"), "w") as f:
            f.write("")
        events = streamjson.read_file(stream)
        res = streamjson.result_event(events)
        return session.SessionResult(exit_code=0, end=codes.SessionEnd.COMPLETED.value,
                                     structured=streamjson.structured_output(res), result_event=res,
                                     stream_file=stream, stderr_file=os.path.join(attempt_dir, "stderr.log"),
                                     session_id="s", cost=streamjson.cost_and_tokens(res), denials=[],
                                     duration_s=0.1, cli_version=version, model="claude-haiku", warnings=[],
                                     quota_reset_at=None, killed=None)


class RoleCanary(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-crt-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp + "/home"
        self.cfg = self.home + "/.claude-acct"
        os.makedirs(self.cfg)
        os.makedirs(self.home + "/.ssh")
        with open(self.home + "/.npmrc", "w") as f:
            f.write("//registry.example/:_authToken=REAL-SECRET\n")
        self.before = self.snapshot()
        self.eng = self.tmp + "/gld"
        self.env = {"HOME": self.home, "CLAUDE_CONFIG_DIR": self.cfg, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def snapshot(self):
        out = {}
        for d, dirs, files in os.walk(self.home):
            for n in dirs + files:
                p = os.path.join(d, n)
                with open(p, "rb") if os.path.isfile(p) else open(os.devnull, "rb") as f:
                    out[os.path.relpath(p, self.home)] = f.read()
        return out

    def run_canary(self, rc, fake, **kw):
        return canaryrun.run_role_canary(rc, self.env, PLUGIN_ROOT, self.eng, run_session=fake, version="2.1.323",
                                         **kw)

    def test_correct_boundary_passes_and_the_record_opens_the_driver_check(self):
        for rc in ("work", "judge"):
            with self.subTest(role_class=rc):
                fake = FakeBoundary()
                rec = self.run_canary(rc, fake)
                self.assertTrue(rec["ok"], (rec["failed"], rec["notes"]))
                self.assertEqual(rec["key"], canary.canary_key("2.1.323", render.template_hash(rc), rc,
                                                               canary.account_tag(self.cfg)))
                self.assertTrue(canaryrun.record_ok(self.eng, rec["key"]))
                self.assertEqual(self.snapshot(), self.before, "real-home bait removed, nothing else touched")
                self.assertTrue(all(c["budget_key"] == defaults.CANARY_BUDGET_KEY and c["model"] == "haiku"
                                    and c["effort"] == "low" and c["home"] == self.home for c in fake.calls))
                n = len(rec["outcomes"])
                self.assertEqual(len(fake.calls), -(-n // canaryrun.BATCH_SIZE))
                self.assertTrue(os.path.isfile(os.path.join(rec["evidence"], "items.json")))
                self.assertEqual(rec["checks"], {"structured_output": True, "probes": True})
                self.assertTrue(rec["sessions"][0]["init_plugins"], "what init said is recorded")

    def test_work_canary_with_the_repository_exceptions_has_their_key(self):
        """P5 F2: the developer renders with the repository's exceptions, so its canary key
        does too (role_key = what the driver looks up); a judge never takes them."""
        exc = {"allow_local_binding": True, "weaker_network_isolation": True, "allow_write": ["{user_tmp}"]}
        ut = os.path.realpath(tempfile.mkdtemp(prefix="gx-crt-ut-"))
        self.addCleanup(shutil.rmtree, ut, True)
        fake = FakeBoundary()
        rec = self.run_canary("work", fake, sandbox_exceptions=exc, user_tmp=ut)
        self.assertTrue(rec["ok"], (rec["failed"], rec["notes"]))
        cfg = {"format": 1, "commands": {}, "sandbox_exceptions": exc}
        self.assertEqual(rec["key"], canaryrun.role_key("2.1.323", "work", cfg, environ=self.env))
        self.assertNotEqual(rec["key"], canaryrun.role_key("2.1.323", "work", None, environ=self.env))
        self.assertEqual(rec["exceptions"], ["allow_local_binding", "allow_write", "weaker_network_isolation"])
        self.assertEqual(canaryrun.role_key("2.1.323", "judge", cfg, environ=self.env),
                         canaryrun.role_key("2.1.323", "judge", None, environ=self.env))
        no_ut = self.run_canary("work", FakeBoundary(), sandbox_exceptions=exc)
        self.assertFalse(no_ut["ok"], "allow_write {user_tmp} without user_tmp is refused (fail-closed)")
        with self.assertRaises(canaryrun.CanaryRunError):
            self.run_canary("judge", FakeBoundary(), sandbox_exceptions=exc)

    def test_an_existing_real_secret_is_never_shown(self):
        fake = FakeBoundary()
        rec = self.run_canary("work", fake)
        self.assertIn("Read:read:home:.npmrc", rec["unprobed"])
        self.assertEqual(rec["outcomes"].get("Bash:read:home:.npmrc"), "refused")
        with open(os.path.join(rec["evidence"], "items.json")) as f:
            items = {i["id"]: i for i in json.load(f)}
        self.assertEqual(items["Bash:read:home:.npmrc"]["input"]["command"],
                         f"cat -- {self.home}/.npmrc >/dev/null")
        self.assertNotIn("Read:read:home:.npmrc", items)
        self.assertTrue(rec["ok"])

    def test_a_probe_that_gets_through_fails_the_canary(self):
        for wrong in ("Read:read:home:.ssh", "Bash:write:wt-claude-dir", "Bash:net:api.github.com",
                      "Read:read:other-attempt-in", "Read:read:main-secret:.env*", "Bash:read-ok:stdio"):
            with self.subTest(wrong=wrong):
                rec = self.run_canary("work", FakeBoundary(wrong=[wrong]))
                self.assertFalse(rec["ok"])
                self.assertEqual(list(rec["failed"]), [wrong])
                self.assertFalse(canaryrun.record_ok(self.eng, rec["key"]))
                self.assertEqual(self.snapshot(), self.before)

    def test_missing_probes_get_one_more_session_then_fail(self):
        rec = self.run_canary("judge", FakeBoundary(skip=(1, 3)))
        self.assertTrue(rec["ok"], rec["failed"])
        self.assertEqual(rec["sessions"][-1]["attempt"], len(rec["sessions"]))
        self.assertEqual(len(rec["sessions"][-1]["items"]), 3)

        class AlwaysSkip(FakeBoundary):
            def __call__(self, inp, *a, **k):
                self.skip = (inp.attempt, 1)
                return super().__call__(inp, *a, **k)
        rec = self.run_canary("judge", AlwaysSkip())
        self.assertFalse(rec["ok"])
        self.assertTrue(all(v == ["refused", "missing"] or v == ["allowed", "missing"] for v in rec["failed"].values()))

    def test_two_accounts_keep_their_own_records(self):
        """FC F2: the account (CLI config dir) is part of the key. Account A's failure does not overwrite B's
        pass, and B never accepts A's record (FC: a current-account FAIL had replaced a personal-account PASS)."""
        cfg_b = self.home + "/.claude-b"
        os.makedirs(cfg_b)
        env_a, env_b = self.env, dict(self.env, CLAUDE_CONFIG_DIR=cfg_b)
        b = canaryrun.run_role_canary("judge", env_b, PLUGIN_ROOT, self.eng, run_session=FakeBoundary(), version="2.1.323")
        self.assertTrue(b["ok"], (b["failed"], b["notes"]))
        a = canaryrun.run_role_canary("judge", env_a, PLUGIN_ROOT, self.eng, run_session=FakeBoundary(
            wrong=["Read:read:home:.ssh"]), version="2.1.323")
        self.assertFalse(a["ok"])
        self.assertNotEqual(a["key"], b["key"])
        self.assertEqual((a["account"], b["account"]), (canary.account_tag(self.cfg), canary.account_tag(cfg_b)))
        self.assertTrue(canaryrun.record_ok(self.eng, b["key"]), "A's failure left B's pass alone")
        self.assertEqual(canaryrun.read_record(self.eng, a["key"])["claude_config_dir"], self.cfg)
        self.assertEqual(b["key"], canaryrun.role_key("2.1.323", "judge", environ=env_b))
        self.assertEqual(a["key"], canaryrun.role_key("2.1.323", "judge", environ=env_a))
        self.assertNotIn(self.home, a["key"] + b["key"], "no local path in a key")

    def test_another_accounts_pass_is_not_taken(self):
        cfg_b = self.home + "/.claude-b"
        os.makedirs(cfg_b)
        env_b = dict(self.env, CLAUDE_CONFIG_DIR=cfg_b)
        self.assertTrue(self.run_canary("judge", FakeBoundary())["ok"])          # account A passes
        fake = FakeBoundary()
        got = canaryrun.ensure_role_canary("judge", env_b, PLUGIN_ROOT, self.eng, {"format": 1, "commands": {}},
                                           "2.1.323", run_canary=lambda rc, *a, **k: canaryrun.run_role_canary(
                                               rc, *a, run_session=fake, **k))
        self.assertTrue(got.ok, got.note)
        self.assertTrue(fake.calls, "account B runs its own canary")
        self.assertEqual(got.key, canaryrun.role_key("2.1.323", "judge", environ=env_b))

    def test_a_record_of_the_key_without_an_account_is_not_read(self):
        """A record an earlier engine wrote (key `<cli>:<template>:<class>`, FC) is never taken — fail-closed:
        the canary runs again under the new key."""
        old_key = f"2.1.323:{render.template_hash('judge')}:judge"
        canaryrun.write_record(self.eng, {"ok": True, "key": old_key, "sessions": [{}]})
        fake = FakeBoundary()
        got = canaryrun.ensure_role_canary("judge", self.env, PLUGIN_ROOT, self.eng, {"format": 1, "commands": {}},
                                           "2.1.323", run_canary=lambda rc, *a, **k: canaryrun.run_role_canary(
                                               rc, *a, run_session=fake, **k))
        self.assertTrue(got.ok)
        self.assertTrue(fake.calls)
        self.assertNotEqual(got.key, old_key)
        canaryrun.write_record(self.eng, {"ok": False, "key": old_key, "sessions": [{}]})    # an old FAIL holds nothing
        shutil.rmtree(os.path.join(self.eng, "canary", "runs"))
        os.unlink(canaryrun.record_path(os.path.realpath(self.eng), got.key))
        self.assertTrue(canaryrun.ensure_role_canary("judge", self.env, PLUGIN_ROOT, self.eng, {"format": 1, "commands": {}},
                                                     "2.1.323", run_canary=lambda rc, *a, **k: canaryrun.run_role_canary(
                                                         rc, *a, run_session=FakeBoundary(), **k)).ok)

    def test_no_structured_output_fails(self):
        rec = self.run_canary("judge", FakeBoundary(structured=False))
        self.assertFalse(rec["ok"])
        self.assertFalse(rec["checks"]["structured_output"])

    def test_other_init_lists_do_not_fail_the_canary(self):
        """FC decision D: the FC account's extra builtin plugin, other tools, agents, MCP servers, permission
        mode — the canary judges its probes only; the init lists are recorded, never compared."""
        sec = {"name": "cc-plugin-sec-default", "source": "cc-plugin-sec-default@builtin"}
        for init in ({"plugins": [sec]}, {"tools": ["Bash"]}, {"agents": ["browser"]},
                     {"mcp_servers": [{"name": "x"}]}, {"permissionMode": "acceptEdits"}, {"skills": ["x"]}):
            with self.subTest(init=init):
                fake = FakeBoundary(init=init)
                rec = self.run_canary("judge", fake)
                self.assertTrue(rec["ok"], (rec["failed"], rec["notes"]))
                self.assertNotIn("init_differences", rec)
                self.assertEqual(len(fake.calls), len(rec["sessions"]))
        self.assertIn("cc-plugin-sec-default@builtin",
                      self.run_canary("work", FakeBoundary(init={"plugins": [sec]}))["sessions"][0]["init_plugins"])

    def test_total_cap_stops_before_a_session(self):
        fake = FakeBoundary()
        rec = self.run_canary("work", fake, max_total_usd=defaults.SESSION_MAX_BUDGET_USD[defaults.CANARY_BUDGET_KEY]
                              + 0.005)
        self.assertFalse(rec["ok"])
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(any("stopped before session 2" in n for n in rec["notes"]))
        self.assertEqual(self.snapshot(), self.before)

    def test_any_cli_version_gets_the_same_canary(self):
        """FC decision D: no list of known CLI versions — an old, new or never seen version is just a key part."""
        for version in ("0.0.1", "2.1.326", "9.9.9"):
            with self.subTest(version=version):
                fake = FakeBoundary()
                rec = canaryrun.run_role_canary("judge", self.env, PLUGIN_ROOT, self.eng, run_session=fake, version=version)
                self.assertTrue(rec["ok"], (rec["failed"], rec["notes"]))
                self.assertTrue(fake.calls)
                self.assertTrue(rec["key"].startswith(version + ":"))
                self.assertNotIn("candidate", rec)
        self.assertEqual([n for n in os.listdir(os.path.join(self.eng, "canary")) if n.startswith("cli-")], [],
                         "no local CLI version trust record")

    def test_a_leftover_write_target_refuses(self):
        for rc, name in (("judge", "gx-canary-outside.txt-write"), ("work", "gx-canary-outside.txt")):
            with self.subTest(role_class=rc):
                left = os.path.join(self.home, name)
                with open(left, "w") as f:
                    f.write("left over\n")
                rec = self.run_canary(rc, FakeBoundary())
                self.assertFalse(rec["ok"])
                self.assertTrue(any("already exists" in n for n in rec["notes"]))
                self.assertTrue(os.path.exists(left), "never removes what it did not make")
                os.unlink(left)

    def test_write_tool_targets_are_never_planted(self):
        """P4 real canary: an existing file makes the Write tool answer "not read yet" before
        the allow rules — a canary-named Write target is a fresh path no bait is planted at."""
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-wt-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        paths, config = canary.canary_layout(tmp + "/l")
        self.addCleanup(shutil.rmtree, paths["srt_tmpdir"], True)
        items = canary.canary_items(paths, config, list(defaults.TOOLS["work"]))
        canary.plant_bait(items, tmp + "/l")
        for i in items:
            if i.tool == "Write" and i.expect == "refused" and os.path.basename(i.target).startswith("gx-canary"):
                with self.subTest(item=i.id):
                    self.assertFalse(os.path.exists(i.target))
                    self.assertIsNone(i.bait)


class PrepareRealHome(unittest.TestCase):
    def test_plants_only_new_files_and_removes_them(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-prh-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        home, root = tmp + "/home", tmp + "/root"
        os.makedirs(home + "/.ssh")
        os.makedirs(root)
        with open(home + "/.netrc", "w") as f:
            f.write("machine x login y password z\n")
        items = [canary.CanaryItem("Read:read:a", "Read", home + "/.ssh/gx-canary", "refused", bait="T1"),
                 canary.CanaryItem("Bash:read:a", "Bash", home + "/.ssh/gx-canary", "refused", bait="T1"),
                 canary.CanaryItem("Read:read:b", "Read", home + "/.aws/gx-canary", "refused", bait="T2"),
                 canary.CanaryItem("Read:read:n", "Read", home + "/.netrc", "refused", bait="T3"),
                 canary.CanaryItem("Bash:read:n", "Bash", home + "/.netrc", "refused", bait="T3"),
                 canary.CanaryItem("Write:write:w", "Write", home + "/gx-canary-w", "refused", "write"),
                 canary.CanaryItem("Read:read:in-root", "Read", root + "/x", "refused", bait="T4")]
        out, bait = canary.prepare_real_home(items, home, home + "/.cfg", root)
        ids = [i.id for i in out]
        self.assertNotIn("Read:read:n", ids)
        self.assertEqual(next(i for i in out if i.id == "Bash:read:n").command, f"cat -- {home}/.netrc >/dev/null")
        with open(home + "/.ssh/gx-canary") as f:
            self.assertEqual(f.read(), "# T1\n")
        self.assertTrue(os.path.isfile(home + "/.aws/gx-canary"))
        self.assertFalse(os.path.exists(root + "/x"), "the layout's own bait is plant_bait's job")
        with open(home + "/gx-canary-w", "w") as f:       # a probe that got through
            f.write("x")
        self.assertEqual(bait.cleanup(), [])
        self.assertEqual(sorted(os.listdir(home)), [".netrc", ".ssh"])
        self.assertEqual(os.listdir(home + "/.ssh"), [])
        with open(home + "/.netrc") as f:
            self.assertEqual(f.read(), "machine x login y password z\n")


@unittest.skipIf(_srt() is None, "srt not installed (scope §6.2: required for stage 1)")
class SrtCanary(unittest.TestCase):
    def setUp(self):
        self.eng = os.path.realpath(tempfile.mkdtemp(prefix="gx-src-"))
        self.addCleanup(shutil.rmtree, self.eng, True)
        self.srt = _srt()

    def test_default_run_template_passes_and_is_recorded(self):
        rec = canaryrun.run_srt_canary(self.srt, self.eng)
        self.assertTrue(rec["ok"], (rec["failed"], rec["notes"]))
        self.assertEqual(rec["key"], canaryrun.srt_key(self.srt))
        ok, key = canaryrun.ensure_srt_canary(self.srt, self.eng, {"format": 1, "commands": {}})
        self.assertEqual((ok, key), (True, rec["key"]))

    def test_exceptions_change_the_key_and_are_run_for(self):
        cfg = {"format": 1, "commands": {}, "sandbox_exceptions": {"allow_local_binding": True}}
        ok, key = canaryrun.ensure_srt_canary(self.srt, self.eng, cfg)
        self.assertTrue(ok, canaryrun.read_record(self.eng, key))
        self.assertNotEqual(key, canaryrun.srt_key(self.srt))
        self.assertEqual(canaryrun.read_record(self.eng, key)["exceptions"], ["allow_local_binding"])

    def test_a_failing_record_is_not_accepted(self):
        key = canaryrun.srt_key(self.srt)
        canaryrun.write_record(self.eng, {"ok": False, "key": key})
        self.assertFalse(canaryrun.record_ok(self.eng, key))
        canaryrun.write_record(self.eng, {"ok": True, "key": "other"})
        self.assertFalse(canaryrun.record_ok(self.eng, "other-than-that"))


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-ccli-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, argv, environ):
        out = io.StringIO()
        return cli.main(argv, environ=environ, out=out), out.getvalue()

    @unittest.skipIf(_srt() is None, "srt not installed")
    def test_srt_only(self):
        env = {"HOME": self.tmp, "GLD_ENGINE_HOME": self.tmp + "/gld", "GLD_SRT_BIN": _srt(),
               "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        rc, out = self.run_cli(["canary", "--srt-only"], env)
        self.assertEqual(rc, cli.EXIT_OK, out)
        self.assertIn("srt canary srt-", out)
        self.assertIn("PASS", out)

    def test_role_canary_with_the_fake_claude_fails_closed(self):
        """The fake claude plays no canary: no attempt record → FAIL, exit 4 — and no paid call."""
        home = self.tmp + "/home"
        os.makedirs(home + "/.cfg")
        env = fakes.fake_env(base={"HOME": home, "CLAUDE_CONFIG_DIR": home + "/.cfg",
                                   "GLD_ENGINE_HOME": self.tmp + "/gld",
                                   "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                             claude_scenarios=[fakes.scn("ok-judge.json")] * 4)
        fakes.assert_fakes_first(env)
        rc, out = self.run_cli(["canary", "--role-class", "judge", "--no-srt"], env)
        self.assertEqual(rc, cli.EXIT_REFUSED, out)
        self.assertIn("role canary 2.1.323:", out)
        self.assertIn("FAIL", out)
        self.assertEqual(sorted(os.listdir(home)), [".cfg"], "real-home bait removed")
        self.assertEqual(os.listdir(home + "/.cfg"), [])


if __name__ == "__main__":
    unittest.main()
