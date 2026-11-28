"""U5 — render: template / substitute (I9), rule lists (§7.6, S1 S2 S4 S7 S8 S9), argv, env,
fail-closed input checks, and the rendered boundary under the REAL srt (no LLM).

The srt tests look for srt in $GLD_TEST_SRT, then <engine home>/srt (the plugin-managed
install, ~/.gld/srt), then PATH. Without srt they skip — set GLD_REQUIRE_SRT=1 to make a
missing srt a failure.
"""

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from gxengine import canary, codes, defaults, render
from gxengine.render import RenderError

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ENGINE, "tests", "fixtures", "render")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def find_srt():
    cands = [os.environ.get("GLD_TEST_SRT"),
             os.path.join(os.path.expanduser(os.environ.get("GLD_ENGINE_HOME", "~/.gld")), "srt",
                          "node_modules", ".bin", "srt"),
             shutil.which("srt")]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


SRT = find_srt()


def need_srt(test):
    if SRT is None and os.environ.get("GLD_REQUIRE_SRT") != "1":
        return unittest.skip("srt not installed (GLD_TEST_SRT / ~/.gld/srt / PATH)")(test)
    return test


def fx_input(name, **changes):
    inp = fixture(name)["input"]
    inp = copy.deepcopy(inp)
    for k, v in changes.items():
        if k.startswith("paths."):
            inp["paths"][k[6:]] = v
        elif k.startswith("config."):
            if v is None:
                inp["config"].pop(k[7:], None)
            else:
                inp["config"][k[7:]] = v
        else:
            inp[k] = v
    return inp


def build(name, **changes):
    return render.RenderInput.from_json(fx_input(name, **changes))


class TemplateAndSubstitute(unittest.TestCase):
    def test_template_is_deterministic_and_path_free(self):
        for rc in ("work", "judge"):
            t = render.template(rc)
            self.assertEqual(render.template_hash(rc), render.template_hash(rc))
            text = json.dumps(t)
            for fixed in sorted(render.SANDBOX_OWN_TMP, key=len, reverse=True):   # the only literal paths
                text = text.replace(fixed, "")
            for real in ("/Users", "/tmp/", "/private", "/var/"):
                self.assertNotIn(real, text, f"the template must only hold placeholders ({rc})")
        hashes = {render.template_hash("work"), render.template_hash("judge"), render.template_hash("work", "run")}
        self.assertEqual(len(hashes), 3)
        with self.assertRaises(RenderError):
            render.template("judge", "run")
        with self.assertRaises(RenderError):
            render.template("leader")

    def test_render_is_substitute_of_template(self):
        """I9: the rendered settings are exactly the template with the paths filled in."""
        for name in ("judge-design.json", "work-developer.json"):
            inp = build(name)
            filled = render.substitute(render.template(inp.role_class), inp.scalars(), inp.lists())
            self.assertEqual(render.render_settings(inp), filled["settings"])
        inp = build("run-test.json")
        filled = render.substitute(render.template("work", "run"), inp.scalars(), inp.lists())
        self.assertEqual(render.render_srt(inp), filled["srt"])

    def test_cross_product_order_and_empty_lists(self):
        got = render.substitute({"x": ["{other_worktrees}/**/{secret_paths}", "{home}"]},
                                {"home": "/h"}, {"other_worktrees": ["/a", "/b"], "secret_paths": ["s1", "s2"]})
        self.assertEqual(got["x"], ["/a/**/s1", "/a/**/s2", "/b/**/s1", "/b/**/s2", "/h"])
        got = render.substitute({"x": ["{outputs}", "keep"]}, {}, {"outputs": []})
        self.assertEqual(got["x"], ["keep"])

    def test_values_are_not_rescanned_and_lists_deduplicated(self):
        got = render.substitute({"x": ["{home}/a", "{home}/a", "{worktree}"]},
                                {"home": "/h", "worktree": "/w/{home}"}, {})
        self.assertEqual(got["x"], ["/h/a", "/w/{home}"])

    def test_placeholder_errors(self):
        with self.assertRaises(RenderError):
            render.substitute({"x": "{nope}"}, {}, {})
        with self.assertRaises(RenderError):
            render.substitute({"x": "{outputs}"}, {}, {"outputs": ["a"]})   # list outside a list
        with self.assertRaises(RenderError):
            render.substitute({"x": ["{in_dir}"]}, {"in_dir": None}, {})
        with self.assertRaises(RenderError):
            render.substitute({"x": ["{outputs}"]}, {}, {})

    def test_brace_text_without_placeholder_survives(self):
        t = render.template("work")
        filled = render.substitute(t, build("work-developer.json").scalars(), build("work-developer.json").lists())
        self.assertIn('{"mcpServers":{}}', filled["claude_flags"])


class RuleLists(unittest.TestCase):
    def setUp(self):
        self.dev = build("work-developer.json")
        self.judge = build("judge-design.json")
        self.run = build("run-test.json")
        self.sd = render.render_settings(self.dev)
        self.sj = render.render_settings(self.judge)
        self.srt = render.render_srt(self.run)

    def test_s1_every_sandbox_deny_is_also_a_permission_deny(self):
        for st in (self.sd, self.sj):
            fs, deny = st["sandbox"]["filesystem"], set(st["permissions"]["deny"])
            records = self.dev.paths["engine_records"]
            for p in fs["denyRead"]:
                if p == records:
                    continue   # per file name in the permission layer (interfaces 해석 20)
                for t in ("Read", "Grep", "Glob"):
                    self.assertIn(f"{t}(/{p})", deny)
                    self.assertIn(f"{t}(/{p}/**)", deny)
            for p in fs["denyWrite"]:
                self.assertIn(f"Edit(/{p})", deny)
                self.assertIn(f"Edit(/{p}/**)", deny)
            for f in render.RECORD_FILES:
                self.assertIn(f"Read(/{records}/**/{f})", deny)

    def test_s2_control_files_denied_in_worktree_and_main_checkout(self):
        fs = self.sd["sandbox"]["filesystem"]
        for root in (self.dev.paths["worktree"], self.dev.paths["main_checkout"]):
            for g in ("/.claude", "/**/CLAUDE.md", "/**/CLAUDE.local.md", "/**/AGENTS.md", "/docs/specs/42/procedure.yaml"):
                self.assertIn(root + g, fs["denyWrite"])

    def test_s4_git_paths(self):
        p = self.dev.paths
        fs = self.sd["sandbox"]["filesystem"]
        for x in ("hooks", "config", "info", "objects/info/alternates"):
            self.assertIn(f"{p['git_common_dir']}/{x}", fs["denyWrite"])
        for x in ("commondir", "gitdir", "config.worktree"):
            self.assertIn(f"{p['own_worktree']}/{x}", fs["denyWrite"])
        self.assertIn(p["worktree"] + "/.git", fs["denyWrite"])
        for x in ("objects", "refs/heads", "logs", "packed-refs", "packed-refs.lock"):
            self.assertIn(f"{p['git_common_dir']}/{x}", fs["allowWrite"])
        self.assertIn(p["own_worktree"], fs["allowWrite"])

    def test_gate_escape_guard_nested_git_and_claude_denied_in_every_write_root(self):
        p, fs = self.dev.paths, self.sd["sandbox"]["filesystem"]
        issue_tmp = os.path.dirname(p["run_tmp"])
        for root in (p["worktree"], issue_tmp, p["cache"], p["own_worktree"]) + render.SANDBOX_OWN_TMP:
            self.assertIn(root + "/**/.git", fs["denyWrite"])
            self.assertIn(root + "/**/.claude", fs["denyWrite"])
        for w in fs["allowWrite"]:
            if w.endswith("packed-refs") or w.endswith("packed-refs.lock"):
                continue
            covered = any(w == r or w.startswith(r + "/") for r in
                          (p["worktree"], issue_tmp, p["cache"], p["own_worktree"],
                           p["git_common_dir"] + "/objects", p["git_common_dir"] + "/refs/heads",
                           p["git_common_dir"] + "/logs"))
            self.assertTrue(covered, f"write root {w} has no nested .git/.claude deny")

    def test_reads_allowed_by_default_except_the_list(self):
        home = self.dev.paths["home"]
        deny = " ".join(self.sd["permissions"]["deny"] + self.sd["sandbox"]["filesystem"]["denyRead"])
        for ok in defaults.HOME_READ_ALLOWED:
            self.assertNotIn(f"{home}/{ok})", deny)
            self.assertNotIn(f"{home}/{ok}/**", deny)
            self.assertNotIn(f'"{home}/{ok}"', json.dumps(self.sd["sandbox"]["filesystem"]["denyRead"]))
        self.assertNotIn(home, self.sd["sandbox"]["filesystem"]["denyRead"], "not a home-wide read deny (F3)")
        self.assertIn(home + "/.config/gh", self.sd["sandbox"]["filesystem"]["denyRead"])
        self.assertIn(self.dev.paths["claude_config_dir"], self.sd["sandbox"]["filesystem"]["denyRead"])

    def test_s7_only_own_in_is_reopened(self):
        p = self.dev.paths
        self.assertEqual(self.sd["sandbox"]["filesystem"]["allowRead"], [p["in_dir"]])
        self.assertIn(p["engine_records"], self.sd["sandbox"]["filesystem"]["denyRead"])
        self.assertIn(p["engine_records"], self.sd["sandbox"]["filesystem"]["denyWrite"])
        self.assertIn(f"Read(/{p['in_dir']}/**)", self.sd["permissions"]["allow"])
        self.assertFalse([r for r in self.sd["permissions"]["deny"] if r.startswith("Read(") and
                          r.endswith(p["engine_records"] + "/**)")])

    def test_run_gets_the_developer_boundary(self):
        """§7.1: same deny lists although the run's temp dir differs (issue_tmp rule)."""
        fs = self.sd["sandbox"]["filesystem"]
        self.assertEqual(self.srt["filesystem"]["denyRead"], fs["denyRead"])
        self.assertEqual(self.srt["filesystem"]["denyWrite"], fs["denyWrite"])
        self.assertNotEqual(self.run.paths["run_tmp"], self.dev.paths["run_tmp"])
        self.assertEqual(self.srt["filesystem"]["allowRead"], [self.run.paths["plugin_root"]])
        self.assertEqual(self.srt["network"]["deniedDomains"], [])
        self.assertEqual(self.srt["network"]["allowedDomains"], ["registry.npmjs.org"])

    def test_judge_writes_only_outputs_and_has_no_network(self):
        p = self.judge.paths
        self.assertEqual(self.sj["permissions"]["allow"],
                         [f"Read(/{p['in_dir']}/**)", f"Edit(/{p['worktree']}/docs/specs/42/design.md)"])
        self.assertEqual(self.sj["sandbox"]["filesystem"]["allowWrite"],
                         [p["worktree"] + "/docs/specs/42/design.md", p["run_tmp"]])
        self.assertEqual(self.sj["sandbox"]["network"]["allowedDomains"], [])
        self.assertNotIn("Bash", self.sj["permissions"]["allow"])
        self.assertEqual(self.sj["permissions"]["deny"], self.sd["permissions"]["deny"], "same deny list (S1)")
        judge2 = build("judge-design.json", outputs=["docs/specs/42/a.md", "release_notes/*.txt"])
        allow = render.render_settings(judge2)["permissions"]["allow"]
        self.assertIn(f"Edit(/{p['worktree']}/release_notes/*.txt)", allow)

    def test_s9_hook_and_aux_denies(self):
        for st, inp in ((self.sd, self.dev), (self.sj, self.judge)):
            cmd = st["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            self.assertEqual(cmd, f"python3 -I {inp.paths['plugin_root']}/skills/gld/gates/gate_precommit.py --no-records")
            for r in defaults.AUX_BASH_DENY + ("WebFetch", "WebSearch"):
                self.assertIn(r, st["permissions"]["deny"])

    def test_gate_hook_writes_no_ledger_with_no_records(self):
        """P5 real run: the hook wrote .claude/guild/gates/findings.json into the worktree
        (a control file) and stopped the Issue. With --no-records it judges but writes nothing."""
        gate = os.path.join(os.path.dirname(ENGINE), "gates", "gate_precommit.py")
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": d})
            env = dict(os.environ, CLAUDE_PROJECT_DIR=d)
            for extra, expect_ledger in ((["--no-records"], False), ([], True)):
                shutil.rmtree(os.path.join(d, ".claude"), ignore_errors=True)
                subprocess.run(["python3", "-I", gate] + extra, input=ev, text=True, cwd=d, env=env,
                               capture_output=True, timeout=60)
                found = os.path.exists(os.path.join(d, ".claude", "guild", "gates", "findings.json"))
                self.assertEqual(found, expect_ledger, extra)

    def test_sandbox_exception_hosts(self):
        exc = {"allow_hosts": ["pub.dev"], "note": "approved"}
        dev = render.render_settings(build("work-developer.json", **{"config.sandbox_exceptions": exc}))
        self.assertEqual(dev["sandbox"]["network"]["allowedDomains"], ["registry.npmjs.org", "pub.dev"])
        judge = render.render_settings(build("judge-design.json", **{"config.sandbox_exceptions": exc}))
        self.assertEqual(judge["sandbox"]["network"]["allowedDomains"], [])
        run = render.render_srt(build("run-test.json", **{"config.sandbox_exceptions": exc}))
        self.assertEqual(run["network"]["allowedDomains"], ["registry.npmjs.org", "pub.dev"])

    def test_secret_defaults_when_unset(self):
        st = render.render_settings(build("work-developer.json", **{"config.secret_paths": None}))
        wt = self.dev.paths["worktree"]
        for g in defaults.REPO_SECRET_DEFAULTS:
            self.assertIn(f"{wt}/**/{g}", st["sandbox"]["filesystem"]["denyRead"])


class SandboxExceptions(unittest.TestCase):
    """P3-0 keys: allow_local_binding / weaker_network_isolation / allow_write ({user_tmp}) and run_env."""

    ALL = {"allow_local_binding": True, "weaker_network_isolation": True, "allow_write": ["{user_tmp}", "/opt/gx-out"]}
    UT = "/private/var/folders/xx/abc/T"

    def run_inp(self, exc=None, **changes):
        ch = {"config.sandbox_exceptions": exc or self.ALL, "paths.user_tmp": self.UT}
        ch.update(changes)
        return build("run-test.json", **ch)

    def test_flags_render_into_srt_only_when_approved(self):
        default = render.render_srt(build("run-test.json"))
        self.assertNotIn("enableWeakerNetworkIsolation", default)
        self.assertNotIn("allowLocalBinding", default["network"])
        s = render.render_srt(self.run_inp())
        self.assertIs(s["enableWeakerNetworkIsolation"], True)
        self.assertIs(s["network"]["allowLocalBinding"], True)
        for root in (self.UT, "/opt/gx-out"):
            self.assertIn(root, s["filesystem"]["allowWrite"])
            for n in (".git", ".claude"):
                self.assertIn(f"{root}/**/{n}", s["filesystem"]["denyWrite"], "gate escape guard on extra roots")
        self.assertNotIn("{user_tmp}", json.dumps(s))
        off = render.render_srt(self.run_inp({"allow_local_binding": False, "weaker_network_isolation": False}))
        self.assertEqual(off, default)

    def test_exceptions_change_the_run_template_hash(self):
        base = render.template_hash("work", "run")
        self.assertEqual(render.input_template_hash(build("run-test.json")), base)
        hashes = {base}
        for exc in ({"allow_local_binding": True}, {"weaker_network_isolation": True}, {"allow_write": ["/opt/gx-out"]}):
            h = render.input_template_hash(self.run_inp(exc))
            self.assertNotIn(h, hashes, exc)
            hashes.add(h)
        with self.assertRaises(RenderError):
            render.template("judge", "role", {"allow_local_binding": True})
        with self.assertRaises(RenderError):
            render.template("work", "run", {"bogus": True})

    def test_exceptions_change_the_work_role_template_hash_only(self):
        """P5 F2: the developer's template (canary key, I9) follows the exceptions; a judge's never does."""
        base = render.template_hash("work")
        hashes = {base}
        for exc in ({"allow_local_binding": True}, {"weaker_network_isolation": True}, {"allow_write": ["/opt/gx-out"]}):
            h = render.input_template_hash(self.dev_inp(exc))
            self.assertNotIn(h, hashes, exc)
            hashes.add(h)
        judge = build("judge-design.json", **{"config.sandbox_exceptions": self.ALL, "paths.user_tmp": self.UT})
        self.assertEqual(judge.exception_flags(), {})
        self.assertEqual(render.input_template_hash(judge), render.template_hash("judge"))

    def dev_inp(self, exc=None, **changes):
        ch = {"config.sandbox_exceptions": exc or self.ALL, "paths.user_tmp": self.UT}
        ch.update(changes)
        return build("work-developer.json", **ch)

    def test_developer_gets_the_exceptions_in_claude_settings_keys(self):
        """P5 F2: Claude Code's own keys — sandbox.network.allowLocalBinding,
        sandbox.enableWeakerNetworkIsolation, sandbox.filesystem.allowWrite — plus the nested
        .git / .claude deny on the extra roots in BOTH layers (S1); Bash only (no Edit allow)."""
        default = render.render_settings(build("work-developer.json"))
        self.assertNotIn("enableWeakerNetworkIsolation", default["sandbox"])
        self.assertNotIn("allowLocalBinding", default["sandbox"]["network"])
        st = render.render_settings(self.dev_inp())
        sb = st["sandbox"]
        self.assertIs(sb["enableWeakerNetworkIsolation"], True)
        self.assertIs(sb["network"]["allowLocalBinding"], True)
        for root in (self.UT, "/opt/gx-out"):
            self.assertIn(root, sb["filesystem"]["allowWrite"])
            self.assertFalse([r for r in st["permissions"]["allow"] if root in r], "no Edit allow for an extra root")
            for n in (".git", ".claude"):
                self.assertIn(f"{root}/**/{n}", sb["filesystem"]["denyWrite"], "gate escape guard on extra roots")
                for t in ("Edit", "Write"):
                    self.assertIn(f"{t}(/{root}/**/{n})", st["permissions"]["deny"])
        self.assertNotIn("{user_tmp}", json.dumps(st))
        off = render.render_settings(self.dev_inp({"allow_local_binding": False, "weaker_network_isolation": False}))
        self.assertEqual(off, default)
        # the srt form of the developer's sandbox carries the same exceptions
        s = render.role_sandbox_as_srt(st)
        self.assertIs(s["enableWeakerNetworkIsolation"], True)
        self.assertIs(s["network"]["allowLocalBinding"], True)

    def test_judge_sessions_never_get_the_exceptions(self):
        exc = dict(self.ALL, allow_hosts=["pub.dev"])
        st = render.render_settings(build("judge-design.json", **{"config.sandbox_exceptions": exc,
                                                                    "paths.user_tmp": self.UT}))
        self.assertEqual(st, render.render_settings(build("judge-design.json")))
        self.assertNotIn(self.UT, json.dumps(st))
        env = render.render_env(build("judge-design.json", **{"config.sandbox_exceptions": exc, "paths.user_tmp": self.UT,
                                                                "config.run_env": {"CI": "true"}}),
                                {"PATH": f"{self.UT}/bin:/usr/bin", "HOME": "/Users/u",
                                 "CLAUDE_CONFIG_DIR": "/Users/u/.claude-personal"})
        self.assertNotIn("CI", env)

    def test_developer_needs_user_tmp_when_the_token_is_used(self):
        with self.assertRaises(RenderError):
            build("work-developer.json", **{"config.sandbox_exceptions": {"allow_write": ["{user_tmp}"]}})

    def test_user_tmp_must_be_given_and_canonical(self):
        with self.assertRaises(RenderError):
            build("run-test.json", **{"config.sandbox_exceptions": {"allow_write": ["{user_tmp}"]}})
        with self.assertRaises(RenderError):
            self.run_inp(**{"paths.user_tmp": "relative/T"})
        d = os.path.realpath(tempfile.mkdtemp(prefix="gx-rt-"))
        self.addCleanup(shutil.rmtree, d, True)
        os.symlink(d, d + "-link")
        self.addCleanup(os.unlink, d + "-link")
        with self.assertRaises(RenderError):
            self.run_inp(**{"paths.user_tmp": d + "-link"})

    def test_run_env_goes_into_the_run_and_developer_env(self):
        cfg_env = {"TURBO_TELEMETRY_DISABLED": "1", "CI": "true"}
        base = {"PATH": "/usr/bin:/bin", "HOME": "/Users/u", "CLAUDE_CONFIG_DIR": "/Users/u/.claude-personal"}
        run = render.render_env(build("run-test.json", **{"config.run_env": cfg_env}), base)
        self.assertEqual({k: run[k] for k in cfg_env}, cfg_env)
        dev = render.render_env(build("work-developer.json", **{"config.run_env": cfg_env}), base)
        self.assertEqual({k: dev[k] for k in cfg_env}, cfg_env)                 # P5 F2
        self.assertEqual(dev["npm_config_cache"], "/Users/u/.gld/cache/acme/app/npm")
        for k, v in defaults.ENV_SESSION_SET.items():
            self.assertEqual(dev[k], v, "the session set still wins")
        judge = render.render_env(build("judge-design.json", **{"config.run_env": cfg_env}), base)
        self.assertNotIn("TURBO_TELEMETRY_DISABLED", judge)

    def test_allow_write_roots_leave_path(self):
        base = {"PATH": f"/opt/gx-out/bin:{self.UT}/bin:/usr/bin", "HOME": "/Users/u"}
        env = render.render_env(self.run_inp(), base)
        self.assertEqual(env["PATH"], "/usr/bin")
        dev = render.render_env(self.dev_inp(), dict(base, CLAUDE_CONFIG_DIR="/Users/u/.claude-personal"))
        self.assertEqual(dev["PATH"], "/usr/bin", "the gate hook runs outside the sandbox with this PATH")

    def test_developer_path_never_gets_the_guild_toolchain(self):
        """The cache (GLD_FLUTTER_ROOT etc.) is role-writable: it stays out of the session PATH."""
        cache = "/Users/u/.gld/cache/acme/app"
        base = {"PATH": f"{cache}/flutter-sdk/bin:/usr/bin", "HOME": "/Users/u",
                "CLAUDE_CONFIG_DIR": "/Users/u/.claude-personal"}
        dev = render.render_env(self.dev_inp(**{"config.cache_env": {"GLD_FLUTTER_ROOT": "{cache}/flutter-sdk"}}), base)
        self.assertEqual(dev["PATH"], "/usr/bin")
        self.assertEqual(dev["GLD_FLUTTER_ROOT"], cache + "/flutter-sdk")
        self.assertEqual(dev["HOME"], "/Users/u")


class Argv(unittest.TestCase):
    def test_resume_only_for_developer(self):
        fx = fixture("work-developer.json")
        inp = build("work-developer.json", resume="0b5c1d2e-aaaa-bbbb-cccc-1234567890ab")
        argv = render.render_claude_argv(inp, fx["bins"]["claude"], fx["files"]["settings"])
        self.assertEqual(argv[-2:], ["--resume", "0b5c1d2e-aaaa-bbbb-cccc-1234567890ab"])
        with self.assertRaises(RenderError):
            build("judge-design.json", resume="abc")
        with self.assertRaises(RenderError):
            build("work-developer.json", resume="--dangerously-skip-permissions")

    def test_instruction_cannot_become_a_flag(self):
        for bad in ("--dangerously-skip-permissions", "-x", "", "   "):
            with self.assertRaises(RenderError):
                build("work-developer.json", instruction=bad)

    def test_review_schema_by_name(self):
        from gxengine import schema as S
        inp = build("judge-design.json", json_schema="result-review")
        argv = render.render_claude_argv(inp, "/usr/local/bin/claude", "/s.json")
        want = dict(S.load_schema("result-review"))
        for k in render.CLI_SCHEMA_DROP:     # P4: the real CLI refuses the 2020-12 meta-schema reference
            want.pop(k)
        got = argv[argv.index("--json-schema") + 1]
        self.assertEqual(got, json.dumps(want, separators=(",", ":"), ensure_ascii=False))
        self.assertNotIn('"$schema"', got)
        self.assertNotIn('"$id"', got)
        with self.assertRaises(RenderError):
            build("judge-design.json", json_schema="procedure")

    def test_srt_argv_quotes_tmpdir_cds_into_the_worktree_and_keeps_command(self):
        inp = build("run-test.json", command="pnpm test -- --ci && echo 'done'")
        argv = render.render_srt_argv(inp, "/s/srt", "/r/srt.json")
        self.assertEqual(argv[4], f"export TMPDIR={inp.paths['run_tmp']}; cd {inp.paths['worktree']} && "
                                  "pnpm test -- --ci && echo 'done'")
        with self.assertRaises(RenderError):
            render.render_srt_argv(inp, "srt", "/r/srt.json")


class Env(unittest.TestCase):
    BASE = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "HOME": "/Users/u", "CLAUDE_CONFIG_DIR": "/Users/u/.claude-personal"}

    def env(self, name, extra=None, **changes):
        base = dict(self.BASE, **(extra or {}))
        return render.render_env(build(name, **changes), base)

    def test_extra_scrub(self):
        extra = {"GIT_DIR": "/x", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
                 "npm_config_userconfig": "/Users/u/.npmrc", "BASH_ENV": "/x/rc", "MY_SECRET": "s",
                 "DB_PASSWORD": "p", "OPENAI_API_KEY": "k", "DYLD_INSERT_LIBRARIES": "/x.dylib",
                 "GH_TOKEN": "t", "CLAUDE_CODE_OAUTH_TOKEN": "t", "LANG": "C"}
        for name in ("work-developer.json", "run-test.json", "judge-design.json"):
            env = self.env(name, extra)
            for k in extra:
                if k == "LANG":
                    continue
                if k in defaults.ENV_SESSION_SET and not name.startswith("run-"):
                    # a role gets the engine's own value (P5: repo git hooks off), never the inherited one
                    self.assertEqual(env[k], defaults.ENV_SESSION_SET[k], f"{name}: {k}")
                else:
                    self.assertNotIn(k, env, f"{name}: {k}")
            self.assertEqual(env["LANG"], "C")

    def test_path_loses_relative_and_role_writable_entries(self):
        wt = "/Users/u/projects/.gld-app-42"
        path = f".:{wt}/node_modules/.bin:/opt/homebrew/bin::/usr/bin:/Users/u/.gld/cache/acme/app/bin:bin:/bin"
        env = self.env("work-developer.json", {"PATH": path})
        self.assertEqual(env["PATH"], "/opt/homebrew/bin:/usr/bin:/bin")
        env = self.env("run-test.json", {"PATH": ""})
        self.assertEqual(env["PATH"], render.DEFAULT_PATH)

    def test_home_and_config_dir_must_match_the_paths(self):
        with self.assertRaises(RenderError):
            self.env("work-developer.json", {"HOME": "/Users/other"})
        with self.assertRaises(RenderError):
            self.env("judge-design.json", {"CLAUDE_CONFIG_DIR": "/Users/u/.claude"})
        base = dict(self.BASE)
        del base["CLAUDE_CONFIG_DIR"]
        with self.assertRaises(RenderError):   # the CLI would use ~/.claude, paths say .claude-personal
            render.render_env(build("work-developer.json"), base)
        env = render.render_env(build("run-test.json"), base)   # a run never logs in
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)

    def test_cache_env_must_point_into_the_guild_cache(self):
        for bad in ({"PUB_CACHE": "/Users/u/.pub-cache"}, {"X": "{cache}/../escape"}, {"PATH": "{cache}/bin"},
                    {"GH_CACHE": "{cache}/gh"}, {"TMPDIR": "{cache}"}, {"Y": "{cache}/a*"}):
            with self.subTest(bad=bad):
                with self.assertRaises(RenderError):
                    build("work-developer.json", **{"config.cache_env": bad})
        env = self.env("work-developer.json", **{"config.cache_env": {"PUB_CACHE": "{cache}/pub", "GRADLE_USER_HOME": "{cache}"}})
        self.assertEqual(env["PUB_CACHE"], "/Users/u/.gld/cache/acme/app/pub")
        self.assertEqual(env["GRADLE_USER_HOME"], "/Users/u/.gld/cache/acme/app")


class RunControlDenyPerFolder(unittest.TestCase):
    """P3-Z decision 6a: a run's control-NAME denies are per folder git does not ignore."""
    WT = "/Users/u/projects/.gld-app-42"

    def test_per_folder_when_given(self):
        srt = render.render_srt(build("run-test.json", **{"paths.worktree_dirs": [self.WT, self.WT + "/lib",
                                                                                  self.WT + "/odd/**"]}))
        deny = srt["filesystem"]["denyWrite"]
        for d in (self.WT, self.WT + "/lib", self.WT + "/odd/**"):
            for n in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"):
                self.assertIn(f"{d}/{n}", deny)
        self.assertNotIn(self.WT + "/**/AGENTS.md", deny)
        self.assertIn(self.WT + "/**/.claude", deny)                       # .claude everywhere
        self.assertIn(self.WT + "/docs/specs/42/procedure.yaml", deny)
        self.assertIn("/Users/u/projects/app/**/AGENTS.md", deny)          # main checkout: glob kept

    def test_without_the_list_the_glob_stays(self):
        deny = render.render_srt(build("run-test.json"))["filesystem"]["denyWrite"]
        for n in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"):
            self.assertIn(f"{self.WT}/**/{n}", deny)

    def test_role_settings_never_use_it(self):
        with self.assertRaises(RenderError):
            build("work-developer.json", **{"paths.worktree_dirs": [self.WT]})
        deny = render.render_settings(build("work-developer.json"))["sandbox"]["filesystem"]["denyWrite"]
        self.assertIn(f"{self.WT}/**/AGENTS.md", deny)

    def test_bad_lists_are_refused(self):
        for v in ([], ["/Users/u/projects/app"], [self.WT + "/../x"], [self.WT + "/a b"], "x", [self.WT + "/*"]):
            with self.subTest(v=v), self.assertRaises(RenderError):
                build("run-test.json", **{"paths.worktree_dirs": v})


class FailClosedInput(unittest.TestCase):
    def bad(self, name, **changes):
        with self.assertRaises(RenderError, msg=str(changes)):
            build(name, **changes)

    def test_unsafe_paths(self):
        self.bad("work-developer.json", **{"paths.worktree": "/Users/u/my repo"})
        self.bad("work-developer.json", **{"paths.worktree": "relative/wt"})
        self.bad("work-developer.json", **{"paths.worktree": "/Users/u/projects/../x"})
        self.bad("work-developer.json", **{"paths.worktree": "/Users/u/projects/*"})
        self.bad("work-developer.json", **{"paths.home": "/Users/u/"})
        self.bad("judge-design.json", **{"paths.other_repo_roots": ["/Users/u/o(x)"]})

    def test_symlinked_path_refused(self):
        d = os.path.realpath(tempfile.mkdtemp(prefix="gx-rt-"))
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(d + "/real")
        os.symlink(d + "/real", d + "/link")
        self.bad("work-developer.json", **{"paths.worktree": d + "/link"})

    def test_write_roots_never_contain_protected_paths(self):
        self.bad("work-developer.json", **{"paths.worktree": "/Users/u"})
        self.bad("work-developer.json", **{"paths.run_tmp": "/Users/u/.gld"})
        self.bad("work-developer.json", **{"paths.cache": "/Users/u/.claude-personal/cache"})
        self.bad("work-developer.json", **{"paths.run_tmp": "/Users/u/.gld/records/tmp/x"})
        self.bad("work-developer.json", **{"paths.worktree": "/Users/u/projects/app"})
        self.bad("work-developer.json", **{"paths.worktree": "/Users/u/projects"})
        self.bad("work-developer.json", **{"paths.run_tmp": "/x"})   # issue_tmp would be /

    def test_engine_files_never_under_the_claude_sandbox_tmp(self):
        self.bad("work-developer.json", **{"paths.engine_records": "/tmp/claude-502/records",
                                           "paths.in_dir": "/tmp/claude-502/records/a/in"})
        self.bad("work-developer.json", **{"paths.run_tmp": "/private/tmp/claude-502/t/x"})

    def test_in_dir_must_be_an_attempt_in_under_records(self):
        self.bad("work-developer.json", **{"paths.in_dir": "/Users/u/projects/.gld-app-42/in"})
        self.bad("work-developer.json", **{"paths.in_dir": "/Users/u/.gld/records/acme/app/42/runs/developer/1"})
        self.bad("work-developer.json", **{"paths.in_dir": None})
        self.bad("work-developer.json", **{"paths.own_worktree": "/Users/u/projects/app/.git"})

    def test_srt_tmpdir_short(self):
        self.bad("run-test.json", **{"paths.srt_tmpdir": "/tmp/gx-" + "a" * 60})
        self.bad("run-test.json", **{"paths.srt_tmpdir": "/var/folders/xx/gx-1"})
        self.bad("run-test.json", **{"paths.srt_tmpdir": None})

    def test_role_class_and_tools(self):
        self.bad("judge-design.json", role_class="work")
        self.bad("work-developer.json", role="tester")
        self.bad("judge-design.json", tools=["Read", "Write", "Bash"])
        self.bad("judge-design.json", tools=["Read", "WebFetch"])
        self.bad("work-developer.json", tools=[])
        self.bad("work-developer.json", tools=["Bash", "Bash"])
        self.bad("run-test.json", role="tester", role_class="judge")

    def test_allow_lists_and_budget(self):
        self.bad("work-developer.json", model="fable")
        self.bad("work-developer.json", effort="max")
        for b in (None, 0, -1, True, float("nan"), float("inf"), "6"):
            self.bad("work-developer.json", max_budget_usd=b)
        build("work-developer.json", model="fable", **{"config.allowed_models": ["fable", "sonnet"]})

    def test_an_unfilled_result_schema_is_refused(self):
        """Stage 3 (E16): the result schemas are enum templates — only a filled one reaches the CLI."""
        from gxengine import schema as S
        for name in codes.STAGE3_RESULT_SCHEMAS.values():
            self.bad("work-developer.json", json_schema=name)
            self.bad("work-developer.json", json_schema=S.load_schema(name))
            filled = S.fill_enums(S.load_schema(name), {"{catalog_steps}": ["ux-review"]})
            text = build("work-developer.json", json_schema=filled).json_schema_text()
            self.assertIn('"enum":["ux-review"]', text)

    def test_bad_exceptions_and_bad_config(self):
        self.bad("run-test.json", **{"config.sandbox_exceptions": {"allow_write": ["{user_tmp}"]}})  # no paths.user_tmp
        self.bad("run-test.json", **{"config.sandbox_exceptions": {"allow_write": ["/Users"]}})       # contains home
        self.bad("run-test.json", **{"config.sandbox_exceptions": {"allow_write": ["/Users/u/projects"]}})  # contains wt
        self.bad("run-test.json", **{"config.sandbox_exceptions": {"allow_write": ["/Users/u/projects/app/x"]}})
        self.bad("run-test.json", **{"config.sandbox_exceptions": {"allow_write": ["/Users/u/.gld"]}})
        self.bad("run-test.json", **{"config.sandbox_exceptions": {"allow_write": ["/opt/a b"]}})
        self.bad("run-test.json", **{"config.run_env": {"PATH": "/x"}})
        self.bad("run-test.json", **{"config.run_env": {"GLD_SAME": "1"},
                                     "config.cache_env": {"GLD_SAME": "{cache}/x"}})
        self.bad("work-developer.json", **{"config.secret_paths": ["/abs"]})
        self.bad("work-developer.json", **{"config.secret_paths": ["{home}"]})
        self.bad("work-developer.json", **{"config.secret_paths": ["a b"]})
        self.bad("work-developer.json", **{"config.registry_hosts": ["bad host"]})
        self.bad("work-developer.json", **{"config.unknown": 1})
        self.bad("judge-design.json", outputs=["../escape.md"])
        self.bad("judge-design.json", outputs=["/abs.md"])
        self.bad("judge-design.json", outputs=["docs/{issue}/x.md"])

    def test_wrong_fields_for_the_kind(self):
        self.bad("run-test.json", model="sonnet")
        self.bad("work-developer.json", command="rm -rf /")
        self.bad("work-developer.json", extra_field=1)
        self.bad("work-developer.json", issue=0)
        self.bad("work-developer.json", issue=True)
        self.bad("work-developer.json", step="Bad Step")


class OutputChecks(unittest.TestCase):
    def good(self):
        return render.render_srt(build("run-test.json"))

    def test_srt_settings_shape_is_enforced(self):
        s = self.good()
        render.check_srt_settings(s)
        for mutate in (lambda x: x["network"].pop("deniedDomains"),
                       lambda x: x.__setitem__("bogus", 1),
                       lambda x: x["filesystem"].__setitem__("denyWrites", []),
                       lambda x: x["filesystem"]["denyWrite"].append("relative/p"),
                       lambda x: x["filesystem"]["allowRead"].append("/a/*"),
                       lambda x: x["filesystem"].__setitem__("denyRead", []),
                       lambda x: x["filesystem"]["denyWrite"].append("{worktree}/x")):
            bad = copy.deepcopy(s)
            mutate(bad)
            with self.assertRaises(RenderError):
                render.check_srt_settings(bad)

    def test_role_settings_shape_is_enforced(self):
        st = render.render_settings(build("work-developer.json"))
        render.check_role_settings(st)
        for mutate in (lambda x: x["sandbox"].__setitem__("allowUnsandboxedCommands", True),
                       lambda x: x["sandbox"].__setitem__("excludedCommands", ["*"]),
                       lambda x: x["permissions"]["deny"].remove("WebFetch"),
                       lambda x: x["permissions"]["allow"].append("Write(//x)"),
                       lambda x: x.pop("hooks"),
                       lambda x: x["sandbox"]["network"].__setitem__("deniedDomains", []),
                       lambda x: x["sandbox"]["network"].__setitem__("allowLocalBinding", False),
                       lambda x: x["sandbox"].__setitem__("enableWeakerNetworkIsolation", "yes"),
                       lambda x: x["sandbox"].__setitem__("enableWeakerNestedSandbox", True)):
            bad = copy.deepcopy(st)
            mutate(bad)
            with self.assertRaises(RenderError):
                render.check_role_settings(bad)

    def test_exception_keys_only_with_bash(self):
        """P5 F2: the optional exception keys pass for the developer, never for a judge."""
        dev = render.render_settings(build("work-developer.json"))
        for add in (lambda x: x["sandbox"]["network"].__setitem__("allowLocalBinding", True),
                    lambda x: x["sandbox"].__setitem__("enableWeakerNetworkIsolation", True)):
            ok = copy.deepcopy(dev)
            add(ok)
            render.check_role_settings(ok)
            judge = render.render_settings(build("judge-design.json"))
            add(judge)
            with self.assertRaises(RenderError):
                render.check_role_settings(judge)


# --- the real srt ------------------------------------------------------------------

class _Layout:
    """A synthetic layout + rendered run / developer boundaries (no LLM)."""

    def __init__(self, test):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="gx-rt-", dir="/tmp"))
        test.addCleanup(shutil.rmtree, self.root, True)
        self.paths, self.config = canary.canary_layout(self.root + "/l")
        test.addCleanup(shutil.rmtree, self.paths["srt_tmpdir"], True)
        common = dict(role="developer", role_class="work", step="canary", attempt=1, issue=1, outputs=[],
                      paths=self.paths, config=self.config, bash_timeout_ms=60000)
        self.run = render.RenderInput(kind="run", command="true", **common)
        self.dev = render.RenderInput(kind="role", model="sonnet", effort="high", tools=["Bash", "Read", "Edit", "Write"],
                                      max_budget_usd=1.0, json_schema="result-work", instruction="x",
                                      system_prompt="y", resume=None, **common)
        base = {"PATH": os.environ.get("PATH", render.DEFAULT_PATH), "HOME": self.paths["home"], "LANG": "en_US.UTF-8"}
        self.run_env = render.render_env(self.run, base)
        self.dev_env = render.render_env(self.dev, dict(base, CLAUDE_CONFIG_DIR=self.paths["claude_config_dir"]))
        self.dev_env["TMPDIR"] = self.paths["srt_tmpdir"]   # srt itself needs the short TMPDIR (F0)

    def write(self, name, obj):
        p = os.path.join(self.root, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return p

    def sh(self, settings_path, command, env=None, cwd=None):
        return subprocess.run([SRT, "--settings", settings_path, "-c", command], cwd=cwd or self.paths["worktree"],
                              env=env or self.run_env, capture_output=True, text=True, timeout=120)


@need_srt
class RealSrt(unittest.TestCase):
    def setUp(self):
        if SRT is None:
            self.fail("GLD_REQUIRE_SRT=1 but srt was not found")
        self.L = _Layout(self)

    def test_run_boundary_passes_the_srt_canary(self):
        L = self.L
        sp = L.write("srt.json", render.render_srt(L.run))
        items = canary.srt_canary_items(L.paths, L.config)
        self.assertEqual(canary.plant_bait(items, L.root), [])
        res = canary.run_srt_canary(SRT, sp, items, cwd=L.paths["worktree"], env=L.run_env)
        v = canary.judge_srt_canary(res, items)
        bad = {k: (o, res[k]) for k, o in v["outcomes"].items() if o != {i.id: i.expect for i in items}[k]}
        self.assertTrue(v["ok"], bad)

    def test_developer_sandbox_rules_hold_for_bash_under_srt(self):
        """The role's sandbox block is sandbox-runtime config too (S1): its Bash probes hold."""
        L = self.L
        sp = L.write("dev-srt.json", render.role_sandbox_as_srt(render.render_settings(L.dev)))
        items = [i for i in canary.canary_items(L.paths, L.config, ["Bash", "Read", "Edit", "Write"]) if i.tool == "Bash"]
        canary.plant_bait(items, L.root)
        res = canary.run_srt_canary(SRT, sp, items, cwd=L.paths["worktree"], env=L.dev_env)
        v = canary.judge_srt_canary(res, items)
        bad = {k: (o, res[k]) for k, o in v["outcomes"].items() if o != {i.id: i.expect for i in items}[k]}
        self.assertTrue(v["ok"], bad)

    def test_batch_and_one_srt_per_probe_agree(self):
        L = self.L
        sp = L.write("srt.json", render.render_srt(L.run))
        items = canary.srt_canary_items(L.paths, L.config)
        canary.plant_bait(items, L.root)
        pick = [i for i in items if i.id in ("srt:read:home:.ssh", "srt:read-ok:worktree-file", "srt:write:wt-claude-dir",
                                             "srt:write-ok:run-tmp", "srt:net:example.com", "srt:read-ok:gitconfig")]
        self.assertEqual(len(pick), 6)
        one = canary.judge_srt_canary(canary.run_srt_canary(SRT, sp, pick, L.paths["worktree"], L.run_env, batch=False), pick)
        many = canary.judge_srt_canary(canary.run_srt_canary(SRT, sp, pick, L.paths["worktree"], L.run_env), pick)
        self.assertEqual(one, many)
        self.assertTrue(one["ok"], one)

    def test_canary_catches_a_missing_rule(self):
        """Drop one read deny and the nested .git deny: the canary must fail on exactly those."""
        L = self.L
        s = render.render_srt(L.run)
        s["filesystem"]["denyRead"].remove(L.paths["home"] + "/.ssh")
        s["filesystem"]["denyWrite"] = [p for p in s["filesystem"]["denyWrite"]
                                        if not p.endswith("/**/.git") or p.startswith(render.SANDBOX_OWN_TMP[0][:-1])
                                        or p.startswith(render.SANDBOX_OWN_TMP[1][:-1])]
        sp = L.write("weak.json", s)
        items = canary.srt_canary_items(L.paths, L.config)
        canary.plant_bait(items, L.root)
        res = canary.run_srt_canary(SRT, sp, items, cwd=L.paths["worktree"], env=L.run_env)
        v = canary.judge_srt_canary(res, items)
        self.assertFalse(v["ok"])
        self.assertEqual(v["outcomes"]["srt:read:home:.ssh"], "allowed")
        self.assertEqual(v["outcomes"]["srt:write:tmp-nested-git"], "allowed")
        wrong = sorted(k for k, o in v["outcomes"].items() if o != {i.id: i.expect for i in items}[k])
        self.assertEqual(wrong, ["srt:read:home:.ssh", "srt:write:tmp-nested-git"])

    def test_canary_catches_a_repository_in_the_sandbox_temp_dir(self):
        """srt keeps /tmp/claude writable for every command; only the nested deny stops a repo there."""
        L = self.L
        s = render.render_srt(L.run)
        s["filesystem"]["denyWrite"] = [p for p in s["filesystem"]["denyWrite"]
                                        if not p.startswith(render.SANDBOX_OWN_TMP)]
        sp = L.write("weak.json", s)
        items = [i for i in canary.srt_canary_items(L.paths, L.config) if i.id == "srt:write:sandbox-tmp-repo"]
        weak = canary.judge_srt_canary(canary.run_srt_canary(SRT, sp, items, L.paths["worktree"], L.run_env), items)
        self.assertEqual(weak["outcomes"]["srt:write:sandbox-tmp-repo"], "allowed")
        sp = L.write("srt.json", render.render_srt(L.run))
        good = canary.judge_srt_canary(canary.run_srt_canary(SRT, sp, items, L.paths["worktree"], L.run_env), items)
        self.assertTrue(good["ok"], good)
        self.assertFalse(os.path.exists(canary.SANDBOX_TMP_REPO), "the probe cleans up after itself")

    def test_gate_escape_guard_refuses_repositories_in_write_roots(self):
        """`git -C <dir>` makes the out-of-sandbox gate use <dir> — no repo / .claude can be made there."""
        L = self.L
        sp = L.write("srt.json", render.render_srt(L.run))
        rt, cache, wt = L.paths["run_tmp"], L.paths["cache"], L.paths["worktree"]
        for cmd in (f"git init -q {rt}/r1", f"mkdir -p {rt}/r2 && printf 'gitdir: /tmp' > {rt}/r2/.git",
                    f"mkdir -p {rt}/r3 && ln -s {rt} {rt}/r3/.git", f"mkdir -p {rt}/r4/x && mv {rt}/r4/x {rt}/r4/.git",
                    f"mkdir -p {cache}/c/.claude", f"mkdir -p {rt}/c2 && ln -s {rt} {rt}/c2/.claude",
                    f"mkdir -p {wt}/sub && git init -q {wt}/sub", f"mkdir -p {rt}/c3/.Claude",
                    "git init -q /tmp/claude/gx-rt-escape-probe", "mkdir -p /tmp/claude/gx-rt-escape-probe2/.claude"):
            with self.subTest(cmd=cmd):
                r = L.sh(sp, cmd)
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("Operation not permitted", r.stderr)
        r = L.sh(sp, f"mkdir -p {rt}/plain/dir && echo ok")
        self.assertEqual(r.stdout.strip(), "ok", r.stderr)
        L.sh(sp, "rmdir /tmp/claude/gx-rt-escape-probe /tmp/claude/gx-rt-escape-probe2 2>/dev/null; true")

    def test_run_command_gets_its_tmpdir_inside_and_srt_the_short_one(self):
        L = self.L
        sp = L.write("srt.json", render.render_srt(L.run))
        inp = render.RenderInput(kind="run", role="developer", role_class="work", step="canary", attempt=1, issue=1,
                                 outputs=[], paths=L.paths, config=L.config, bash_timeout_ms=60000,
                                 command='echo "$TMPDIR" && touch "$TMPDIR/probe" && echo wrote')
        argv = render.render_srt_argv(inp, SRT, sp)
        r = subprocess.run(argv, cwd=L.paths["worktree"], env=L.run_env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.stdout.split(), [L.paths["run_tmp"], "wrote"], r.stderr)
        self.assertTrue(os.path.isfile(L.paths["run_tmp"] + "/probe"))
        self.assertTrue(L.run_env["TMPDIR"].startswith(defaults.SRT_TMP_PREFIX))

    def test_exceptions_under_the_real_srt(self):
        """srt 0.0.83 accepts the rendered exception keys; local binding is refused without the
        exception and allowed with it; an extra write root is writable, its nested .git is not."""
        L = self.L
        extra = os.path.realpath(tempfile.mkdtemp(prefix="gx-rt-aw-", dir=self.L.root))
        bind = ("python3 -I -c \"import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); "
                "s.listen(1); print('bound')\"")
        common = dict(role="developer", role_class="work", step="canary", attempt=1, issue=1, outputs=[],
                      paths=dict(L.paths, user_tmp=extra), bash_timeout_ms=60000, command="true")
        strict = L.write("strict.json", render.render_srt(L.run))
        r = L.sh(strict, bind)
        self.assertNotIn("bound", r.stdout, "local binding must be refused by default")
        cfg = dict(L.config, sandbox_exceptions={"allow_local_binding": True, "weaker_network_isolation": True,
                                                 "allow_write": ["{user_tmp}"]})
        inp = render.RenderInput(kind="run", config=cfg, **common)
        loose = L.write("loose.json", render.render_srt(inp))
        r = L.sh(loose, bind)
        self.assertEqual(r.stdout.strip(), "bound", r.stderr)
        r = L.sh(loose, f"touch {extra}/ok && echo wrote")
        self.assertEqual(r.stdout.strip(), "wrote", r.stderr)
        r = L.sh(loose, f"git init -q {extra}/repo")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Operation not permitted", r.stderr)
        r = L.sh(strict, f"touch {extra}/no")
        self.assertNotEqual(r.returncode, 0)

    def test_developer_exceptions_under_the_real_srt(self):
        """P5 F2: the developer's rendered sandbox (as srt config — Claude Code's sandbox is
        sandbox-runtime) with the repository's exceptions: local binding works, the extra write
        root is writable and its nested .git is not, and every Bash boundary probe still holds."""
        L = self.L
        extra = os.path.realpath(tempfile.mkdtemp(prefix="gx-rt-dw-", dir=self.L.root))
        bind = ("python3 -I -c \"import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); "
                "s.listen(1); print('bound')\"")
        cfg = dict(L.config, sandbox_exceptions={"allow_local_binding": True, "weaker_network_isolation": True,
                                                 "allow_write": ["{user_tmp}"]})
        dev = render.RenderInput(kind="role", role="developer", role_class="work", step="canary", attempt=1, issue=1,
                                 outputs=[], paths=dict(L.paths, user_tmp=extra), config=cfg, bash_timeout_ms=60000,
                                 model="sonnet", effort="high", tools=["Bash", "Read", "Edit", "Write"],
                                 max_budget_usd=1.0, json_schema="result-work", instruction="x", system_prompt="y")
        strict = L.write("dev-strict.json", render.role_sandbox_as_srt(render.render_settings(L.dev)))
        loose = L.write("dev-loose.json", render.role_sandbox_as_srt(render.render_settings(dev)))
        env = L.dev_env
        r = L.sh(strict, bind, env=env)
        self.assertNotIn("bound", r.stdout, "local binding is refused without the exception")
        r = L.sh(loose, bind, env=env)
        self.assertEqual(r.stdout.strip(), "bound", r.stderr)
        r = L.sh(loose, f"touch {extra}/ok && echo wrote", env=env)
        self.assertEqual(r.stdout.strip(), "wrote", r.stderr)
        for cmd in (f"git init -q {extra}/repo", f"mkdir -p {extra}/c/.claude"):
            r = L.sh(loose, cmd, env=env)
            self.assertNotEqual(r.returncode, 0, cmd)
            self.assertIn("Operation not permitted", r.stderr)
        r = L.sh(strict, f"touch {extra}/no", env=env)
        self.assertNotEqual(r.returncode, 0)
        items = [i for i in canary.canary_items(L.paths, cfg, ["Bash", "Read", "Edit", "Write"]) if i.tool == "Bash"]
        canary.plant_bait(items, L.root)
        res = canary.run_srt_canary(SRT, loose, items, cwd=L.paths["worktree"], env=env)
        v = canary.judge_srt_canary(res, items)
        bad = {k: (o, res[k]) for k, o in v["outcomes"].items() if o != {i.id: i.expect for i in items}[k]}
        self.assertTrue(v["ok"], bad)

    def test_srt_refuses_a_config_without_required_keys(self):
        """F0: srt itself is fail-closed on a missing required key (and render never emits one)."""
        L = self.L
        s = render.render_srt(L.run)
        del s["network"]["deniedDomains"]
        sp = L.write("broken.json", s)
        ok, err = canary.self_check(SRT, sp, L.paths["srt_tmpdir"])
        self.assertFalse(ok)
        self.assertIn("deniedDomains", err)

    def test_secret_globs_hold_for_files_dirs_and_case(self):
        L = self.L
        wt = L.paths["worktree"]
        os.makedirs(wt + "/deep/er/.env.d")
        for rel in ("deep/er/.env.local", "deep/er/.env.d/inner", "x.PEM", "cert.p12", "k.key"):
            with open(f"{wt}/{rel}", "w") as f:
                f.write("SECRET\n")
        sp = L.write("srt.json", render.render_srt(L.run))
        for rel in ("deep/er/.env.local", "deep/er/.env.d/inner", "x.PEM", "cert.p12", "k.key", ".ENV-x"):
            with self.subTest(rel=rel):
                if rel == ".ENV-x":
                    with open(f"{wt}/.env-x", "w") as f:
                        f.write("SECRET\n")
                r = L.sh(sp, f"cat {rel}")
                self.assertNotIn("SECRET", r.stdout)
                self.assertIn("Operation not permitted", r.stderr)


if __name__ == "__main__":
    unittest.main()
