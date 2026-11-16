"""K1 — claude adapter (argv, env contract, endpoint guard, processes, stream-json), §5.1 permission
rules, rendered settings, the after-role scope check and the schema validator."""

import json
import os
import signal
import subprocess
import sys
import time
import unittest

import _k1
from _k1 import git, repo, tmpdir

from guildcore import schema as SCH
from guildcore.adapters import claude as C
from guildcore.roles import permissions as P
from guildcore.roles import scope as SC
from guildcore.roles import settings as S

STREAMS = os.path.join(_k1.K1FX, "streams")


class EndpointGuard(unittest.TestCase):
    def test_default_endpoint_passes(self):
        self.assertEqual(C.endpoint_guard({}, {}), C.DEFAULT_ENDPOINT)
        self.assertEqual(C.endpoint_guard({"ANTHROPIC_BASE_URL": "https://api.anthropic.com/"}), C.DEFAULT_ENDPOINT)

    def test_parent_env_override_halts(self):
        with self.assertRaises(C.EnvHalt) as cm:
            C.endpoint_guard({"ANTHROPIC_BASE_URL": "http://127.0.0.1:11434"})
        self.assertEqual(cm.exception.reason, "endpoint")
        self.assertTrue(str(cm.exception).startswith("halted: env endpoint"))

    def test_settings_env_override_halts(self):
        with self.assertRaises(C.EnvHalt):
            C.endpoint_guard({}, {"ANTHROPIC_BASE_URL": "http://10.0.0.1"})

    def test_other_routing_keys_halt(self):
        for k in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_BEDROCK_BASE_URL"):
            with self.assertRaises(C.EnvHalt):
                C.endpoint_guard({k: "1"})

    def test_model_keys_and_default_url_do_not_halt(self):      # K1-m1
        self.assertEqual(C.endpoint_guard({"ANTHROPIC_MODEL": "x", "ANTHROPIC_BASE_URL": C.DEFAULT_ENDPOINT},
                                          {"ANTHROPIC_BASE_URL": C.DEFAULT_ENDPOINT + "/"}), C.DEFAULT_ENDPOINT)
        e = C.child_env({"ANTHROPIC_MODEL": "x", "ANTHROPIC_SMALL_FAST_MODEL": "y"})
        self.assertNotIn("ANTHROPIC_MODEL", e)
        self.assertNotIn("ANTHROPIC_SMALL_FAST_MODEL", e)

    def test_role_env_has_no_github_credentials(self):        # Q23 defence in depth
        d = tmpdir(self)
        e = C.child_env({"GH_TOKEN": "t", "GITHUB_TOKEN": "t", "SSH_AUTH_SOCK": "/s"}, role_dir=d)
        for k in ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK"):
            self.assertNotIn(k, e)
        self.assertTrue(e["GH_CONFIG_DIR"].startswith(d))
        self.assertEqual(os.listdir(e["GH_CONFIG_DIR"]), [])

    def test_allow_local_flag(self):
        self.assertEqual(C.endpoint_guard({"ANTHROPIC_BASE_URL": "http://127.0.0.1:11434"}, allow_local=True),
                         "http://127.0.0.1:11434")

    def test_registered_gateway_only_for_base_url(self):
        e = {"ANTHROPIC_BASE_URL": "https://gw.example.invalid/"}
        self.assertEqual(C.endpoint_guard(e, allowed_endpoints=["https://gw.example.invalid"]),
                         "https://gw.example.invalid")
        with self.assertRaises(C.EnvHalt):
            C.endpoint_guard(dict(e, CLAUDE_CODE_USE_BEDROCK="1"), allowed_endpoints=["https://gw.example.invalid"])


class EnvContract(unittest.TestCase):
    def test_contract_wins_over_parent_and_settings(self):
        env = C.child_env({"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "600000", "X": "1"},
                          {"BASH_DEFAULT_TIMEOUT_MS": "1", "DISABLE_TELEMETRY": "1"})
        for k, v in C.ENV_CONTRACT.items():
            self.assertEqual(env[k], v)
        self.assertEqual(env["X"], "1")
        self.assertEqual(env["DISABLE_TELEMETRY"], "1")

    def test_cache_modes(self):
        self.assertEqual(C.child_env({}, cache="5m")["FORCE_PROMPT_CACHING_5M"], "1")
        e = C.child_env({"FORCE_PROMPT_CACHING_5M": "1", "ENABLE_PROMPT_CACHING_1H": "1"}, cache="off")
        self.assertEqual(e["DISABLE_PROMPT_CACHING"], "1")
        self.assertNotIn("FORCE_PROMPT_CACHING_5M", e)
        self.assertNotIn("ENABLE_PROMPT_CACHING_1H", e)

    def test_judge_env(self):
        e = C.child_env({}, judge=True, cache="off")
        self.assertEqual(e["CLAUDE_CODE_DISABLE_CLAUDE_MDS"], "1")
        self.assertEqual(e["CLAUDE_CODE_DISABLE_AUTO_MEMORY"], "1")

    def test_suite_ceiling(self):
        self.assertEqual(C.child_env({}, suite_ceiling_ms=7200000)["BASH_MAX_TIMEOUT_MS"], "7200000")


class Argv(unittest.TestCase):
    def test_role_argv_contract(self):
        a = C.role_argv("sonnet", "persona", ["Bash(ls:*)"], ["Agent"], "/r", "/r/in/settings.json",
                        session_id="u-1")
        for f in ("--permission-mode", "dontAsk", "--setting-sources", "", "--strict-mcp-config",
                  "--add-dir", "--append-system-prompt", "--session-id", "--output-format", "stream-json"):
            self.assertIn(f, a)
        self.assertEqual(a[a.index("--model") + 1], "sonnet")
        self.assertNotIn("--dangerously-skip-permissions", a)

    def test_resume_replaces_session_id(self):
        a = C.role_argv("sonnet", "", [], [], None, "/s.json", session_id="u", resume="u")
        self.assertIn("--resume", a)
        self.assertNotIn("--session-id", a)

    def test_judge_argv_inline_schema(self):
        a = C.judge_argv("haiku", "sys", {"type": "object"}, "/s.json")
        self.assertEqual(a[a.index("--json-schema") + 1], '{"type":"object"}')
        self.assertEqual(a[a.index("--tools") + 1], "")
        for f in ("--no-session-persistence", "--disable-slash-commands", "--system-prompt"):
            self.assertIn(f, a)

    def test_forbidden_flags_refused(self):
        for f in C.FORBIDDEN_FLAGS:
            with self.assertRaises(ValueError):
                C.check_argv(["claude", "-p", "--model", "x", "--setting-sources", "", "--settings", "s", f])
        with self.assertRaises(ValueError):
            C.check_argv(["claude", "-p", "--model", "x"])


class Processes(unittest.TestCase):
    def test_timeout_kills_the_group(self):
        d = tmpdir(self)
        script = "import subprocess,time; subprocess.Popen(['sleep','60']); time.sleep(60)"
        rec = {}
        p = C.run_process([sys.executable, "-c", script], dict(os.environ), d, "", os.path.join(d, "o"),
                          os.path.join(d, "e"), 1.5, on_start=lambda r: rec.update(r), poll_s=0.1)
        self.assertTrue(p.timed_out)
        self.assertEqual(p.killed_by, "timeout")
        with self.assertRaises(OSError):
            os.killpg(rec["pgid"], 0)

    def test_halt_check_kills(self):
        d = tmpdir(self)
        p = C.run_process([sys.executable, "-c", "import time; time.sleep(30)"], dict(os.environ), d, "",
                          os.path.join(d, "o"), os.path.join(d, "e"), 60, halt_check=lambda: True, poll_s=0.1)
        self.assertEqual(p.killed_by, "halt")

    def test_safe_kill_refuses_on_mismatch(self):
        p = subprocess.Popen(["sleep", "30"], start_new_session=True)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        rec = {"pid": p.pid, "pgid": os.getpgid(p.pid), "start_time": "Mon Jan  1 00:00:00 2001"}
        self.assertEqual(C.safe_kill_group(rec), "mismatch")
        rec2 = dict(rec, start_time=C.process_start(p.pid), session_id="not-in-cmdline")
        self.assertEqual(C.safe_kill_group(rec2), "mismatch")
        self.assertIsNone(p.poll())
        rec3 = dict(rec, start_time=C.process_start(p.pid))
        self.assertEqual(C.safe_kill_group(rec3, grace_s=2), "killed")

    def test_gone_process(self):
        self.assertEqual(C.safe_kill_group({"pid": 999999, "pgid": 999999, "start_time": "x"}), "gone")


class Streams(unittest.TestCase):
    def test_real_result_file_stream(self):
        st = C.read_stream(os.path.join(STREAMS, "explorer-result-file.jsonl"))
        self.assertIsNotNone(st.init)
        self.assertTrue(st.session_id)
        self.assertEqual([t["name"] for t in st.tool_uses], ["Read", "Write", "Write"])
        self.assertTrue(all(d["decision"] == "accept" for d in st.decisions.values()))
        self.assertIn(">>> RESULT <<<", st.last_text)
        self.assertEqual(st.result["subtype"], "success")

    def test_real_denial_stream(self):
        st = C.read_stream(os.path.join(STREAMS, "developer-push-denied.jsonl"))
        ds = st.denial_records()
        self.assertEqual(len(ds), 1)
        self.assertEqual(ds[0]["command"], "git push origin HEAD")
        self.assertEqual(ds[0]["reason_type"], "subcommandResults")

    def test_torn_lines_counted(self):
        st = C.parse_stream('{"type":"result","result":"x"}\n{"type":"assi')
        self.assertEqual(st.torn, 1)
        self.assertEqual(st.last_text, "x")

    def test_permission_denials_fallback(self):
        st = C.parse_stream(json.dumps({"type": "result", "permission_denials": [
            {"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "env"}}]}))
        self.assertEqual(st.denial_records()[0]["command"], "env")

    def test_missing_file(self):
        self.assertEqual(C.read_stream("/nonexistent/x").events, 0)


class Permissions(unittest.TestCase):
    def test_always_deny_everywhere(self):
        for role, task in (("developer", "implement"), ("qa", None), ("explorer", None),
                           ("tester", "verify"), ("auditor", None)):
            allow, deny = P.role_rules(role, task)
            for d in P.ALWAYS_DENY:
                self.assertIn(d, deny, (role, d))

    def test_gh_api_not_in_c2(self):
        allow, deny = P.role_rules("developer", "implement")
        self.assertFalse([a for a in allow if a.startswith("Bash(gh api")])
        self.assertIn("Bash(gh api -X*)", deny)
        self.assertIn("Bash(gh api * --method*)", deny)

    def test_developer_paths_scoped(self):
        allow, _ = P.role_rules("developer", "implement", worktree="/w", run_dir="/r")
        self.assertIn("Write(//w/**)", allow)
        self.assertIn("Edit(//w/**)", allow)
        self.assertNotIn("Write", allow)
        self.assertIn("Read(//r/in/**)", allow)
        self.assertIn("Write(//r/out/**)", allow)

    def test_readers_cannot_sed_in_place(self):
        _, deny = P.role_rules("tester", "verify")
        self.assertIn("Bash(sed -i:*)", deny)
        allow, _ = P.role_rules("tester", "verify")
        self.assertNotIn("Bash(mkdir:*)", allow)

    def test_scopes(self):
        a, _ = P.role_rules("tester", "cases", worktree="/w", issue=12)
        self.assertIn("Write(//w/docs/specs/12/test-cases.md)", a)
        a, _ = P.role_rules("qa", None, worktree="/w")
        self.assertIn("Write(//w/test/**)", a)
        a, _ = P.role_rules("auditor", None, run_dir="/r")
        self.assertEqual(a, ["Read", "Grep", "Glob", "Read(//r/in/**)"])

    def test_toolchain(self):
        d = repo(self, {"pubspec.yaml": "name: x\n", "scripts/run.sh": "#!/bin/sh\n", "package.json": "{}"})
        os.chmod(os.path.join(d, "scripts", "run.sh"), 0o755)
        t = P.toolchain_prefixes(d, {"test": ["flutter test --x", "npx cspell '**' --x"]}, {"lint_cmd": "flutter analyze"},
                                 git(d, "ls-files").split("\n"))
        for want in ("flutter test", "npx cspell", "flutter analyze", "flutter", "dart", "npm",
                     "scripts/run.sh", "./scripts/run.sh", "timeout"):
            self.assertIn(want, t)

    def test_role_key(self):
        self.assertEqual(P.role_key("tech-lead", "conformance"), "tech-lead-review")
        self.assertEqual(P.role_key("security", None), "reviewer")

    def test_summary_mentions_limits(self):
        s = P.summary("developer", "implement", ["flutter test"])
        self.assertIn("Never push", s)
        self.assertIn("BLOCKED: permission", s)
        self.assertIn("Read, Grep and Glob", P.summary("auditor"))


class Q22Rules(unittest.TestCase):
    """User decision Q22: bare `Bash` + always-deny + read-only denies + post-role checks."""

    def test_bare_bash_for_shell_roles_only(self):
        for role, task in (("developer", "implement"), ("tester", "verify"), ("explorer", None), ("qa", None)):
            self.assertEqual(P.role_rules(role, task)[0][0], "Bash")
        self.assertNotIn("Bash", P.role_rules("auditor")[0])
        self.assertFalse([a for a in P.role_rules("developer", "implement")[0] if a.startswith("Bash(")])

    def test_always_deny_superset_and_readonly(self):
        _, dev = P.role_rules("developer", "implement")
        _, rd = P.role_rules("tester", "verify")
        for d in P.ALWAYS_DENY + P.ALWAYS_DENY_Q22:
            self.assertIn(d, dev)
            self.assertIn(d, rd)
        for d in P.READONLY_DENY:
            self.assertIn(d, rd)
        self.assertNotIn("Bash(git commit:*)", dev)
        for want in ("Bash(gh pr review:*)", "Bash(gh pr ready:*)", "Bash(gh release:*)",
                     "Bash(gh workflow run:*)", "Bash(gh api -X*)", "Bash(gh api * --method*)",
                     "Bash(gh -R *)", "Bash(bash -c:*)", "Bash(eval:*)"):
            self.assertIn(want, dev)

    def test_allowlist_model_kept_for_the_record(self):
        allow, _ = P.role_rules("developer", "implement", allowlist=True)
        self.assertIn("Bash(ls:*)", allow)
        self.assertNotIn("Bash", allow)

    def test_bypass_predictions(self):
        from workflows.dev.replay import permissions_check as PC
        a, d = P.role_rules("developer", "implement")
        for c in ("git push", "env -u X git push", "GIT_X=1 git push", "echo $(git push)", "echo `git push`",
                  "command git push", "/usr/bin/git push", "timeout 5 git push", "{ git push; }",
                  "git -C . push", "bash -c 'git push'", "gh api -XPOST r", "gh api r --method=PATCH",
                  "gh api r -fa=b", "gh -R o/r pr merge 1", "\\git push", "gh pr -R o/r merge 1",
                  "gh api x -iX PUT", "gh pr update-branch 1", "git --no-pager push", "git -P push origin HEAD",
                  "git send-pack origin x", "git config --local alias.p push", "git config set alias.q push",
                  "git -c alias.z=push z", "git config core.hooksPath /tmp", "git fetch origin"):
            self.assertEqual(PC.predict(c, a, d)[0], "deny", c)
        for c in ("echo $(ls) > out.txt", "cd lib && ls | head", "X=1 flutter test", "git log | xargs git show",
                  "cat /etc/hosts"):
            self.assertEqual(PC.predict(c, a, d)[0], "allow", c)
        a, d = P.role_rules("tester", "verify")
        self.assertEqual(PC.predict("git -C . commit -m x", a, d)[0], "deny")
        self.assertEqual(PC.predict("git log --oneline", a, d)[0], "allow")
        for c in ("git --no-pager commit -m x", "git -P tag v9", "git branch -f p HEAD", "git checkout HEAD~1",
                  "git symbolic-ref HEAD refs/heads/x", "git update-index --assume-unchanged f", "gh pr view 1"):
            self.assertEqual(PC.predict(c, a, d)[0], "deny", c)

    def test_summary_names_the_limits(self):
        s = P.summary("tester", "verify")
        self.assertIn("Do not commit", s)
        self.assertIn("bash -c", s)
        self.assertNotIn("Do not commit", P.summary("developer", "implement"))


class DenialLearning(unittest.TestCase):
    def test_suggestion_needs_two_issues_three_times(self):
        ds = [{"issue": 1, "role": "tester-verify", "command": "make check x", "cls": "other"},
              {"issue": 1, "role": "tester-verify", "command": "FOO=1 make check y", "cls": "other"},
              {"issue": 2, "role": "tester-verify", "command": "make check", "cls": "other"},
              {"issue": 2, "role": "tester-verify", "command": "git push", "cls": "forbidden"},
              {"issue": 3, "role": "tester-verify", "command": "git push", "cls": "forbidden"},
              {"issue": 4, "role": "tester-verify", "command": "git push", "cls": "forbidden"}]
        self.assertEqual(P.suggest_role_allow(ds), [{"role": "tester-verify", "pattern": "Bash(make check:*)",
                                                     "count": 3, "issues": 2}])
        self.assertEqual(P.suggest_role_allow(ds[:2]), [])


class RenderedSettings(unittest.TestCase):
    def setUp(self):
        self.r = repo(self, {".claude/settings.json": {
            "permissions": {"allow": ["Bash(git:*)"], "deny": ["Bash(rm -rf .git:*)"]},
            "env": {"PROJ": "1", "PATH": "/evil"},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
                      "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/guild/gates/scripts/g.py\""}]}]}},
            ".claude/guild/gates/scripts/g.py": "print(1)\n"})
        self.base = git(self.r, "rev-parse", "HEAD")
        self.user = os.path.join(tmpdir(self), "settings.json")
        with open(self.user, "w") as fh:
            json.dump({"permissions": {"allow": ["Bash(*)"], "deny": ["Bash(cat ~/.ssh/*)"]},
                       "env": {"DISABLE_TELEMETRY": "1"},
                       "sandbox": {"filesystem": {"allowWrite": ["/a/**"]}},
                       "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]}}, fh)
        with open(os.path.join(self.r, ".claude", "settings.local.json"), "w") as fh:
            json.dump({"permissions": {"deny": ["Bash(sudo:*)"], "allow": ["Bash(x:*)"]},
                       "sandbox": {"enabled": False, "filesystem": {"allowWrite": ["/b/**"]}}}, fh)

    def render(self, **kw):
        run = os.path.join(tmpdir(self), "run")
        return S.render("developer", "implement", worktree=self.r, base=self.base, run_dir=run,
                        user_settings=self.user, **kw), run

    def test_deny_union_allow_not_carried(self):
        rd, _ = self.render()
        deny, allow = rd.settings["permissions"]["deny"], rd.settings["permissions"]["allow"]
        for d in ("Bash(cat ~/.ssh/*)", "Bash(rm -rf .git:*)", "Bash(sudo:*)", "Bash(git push:*)"):
            self.assertIn(d, deny)
        for a in ("Bash(*)", "Bash(git:*)", "Bash(x:*)"):
            self.assertNotIn(a, allow)

    def test_env_returned_not_written(self):
        rd, run = self.render()
        self.assertEqual(rd.env["DISABLE_TELEMETRY"], "1")
        self.assertEqual(rd.env["PROJ"], "1")
        on_disk = json.load(open(os.path.join(run, "in", "settings.json")))
        self.assertNotIn("env", on_disk)

    def test_role_sandbox_forced(self):                       # Q23 + K1r2-B2/M1
        rd, run = self.render()
        sb = rd.settings["sandbox"]
        fs = sb["filesystem"]
        self.assertEqual((sb["enabled"], sb["allowUnsandboxedCommands"], sb["excludedCommands"]), (True, False, []))
        self.assertIn(self.r + "/**", fs["allowWrite"])
        self.assertIn(run + "/out/**", fs["allowWrite"])
        self.assertNotIn(run + "/**", fs["allowWrite"])
        self.assertNotIn("/a/**", fs["allowWrite"])            # user/local cannot widen
        common = os.path.join(self.r, ".git")
        self.assertNotIn(common + "/**", fs["allowWrite"])
        self.assertFalse([a for a in fs["allowWrite"] if a.startswith(common + "/guild")])
        for want in (common + "/hooks/**", common + "/config", self.r + "/.claude/**",
                     common + "/guild/engine/**", common + "/guild/**"):
            self.assertIn(want, fs["denyWrite"])
        home = os.path.expanduser("~")
        for want in (".ssh", ".config/gh", ".claude", "Library/Keychains", ".aws"):
            self.assertIn(os.path.join(home, want), fs["denyRead"])
        self.assertFalse([d for d in sb["network"]["allowedDomains"] if "github" in d])

    def test_reader_sandbox_writes_run_dir_only(self):
        run = os.path.join(tmpdir(self), "run")
        rd = S.render("reviewer", None, worktree=self.r, base=self.base, run_dir=run, user_settings=self.user)
        fs = rd.settings["sandbox"]["filesystem"]
        self.assertEqual(fs["allowWrite"][:2], [run + "/out/**", run + "/tmp/**"])
        self.assertFalse([a for a in fs["allowWrite"] if a.startswith(self.r)])
        for top in (self.r + "/.claude/**", self.r + "/.claude/**"):
            self.assertIn(top, fs["denyWrite"])         # every tracked top-level path
        self.assertEqual(rd.settings["sandbox"]["network"]["allowedDomains"], [])

    def test_toolchain_reader_gets_build_dirs_not_sources(self):   # K1r2-M3
        run = os.path.join(tmpdir(self), "run")
        rd = S.render("tester", "verify", worktree=self.r, base=self.base, run_dir=run, user_settings=self.user)
        fs = rd.settings["sandbox"]["filesystem"]
        self.assertIn(self.r + "/.dart_tool/**", fs["allowWrite"])
        self.assertIn(self.r + "/build/**", fs["allowWrite"])
        self.assertIn(self.r + "/.claude/**", fs["denyWrite"])
        self.assertNotIn(self.r + "/**", fs["denyWrite"])      # the cwd root itself: heredocs need it

    def test_registries_from_manifests(self):
        with open(os.path.join(self.r, "pubspec.yaml"), "w") as fh:
            fh.write("name: x\n")
        self.assertIn("pub.dev", S.registry_domains(self.r))

    def test_judge_keeps_merged_sandbox(self):
        rd = S.render("judge", None, user_settings=self.user, hooks=False)
        self.assertEqual(rd.settings["sandbox"], {"filesystem": {"allowWrite": ["/a/**"]}})

    def test_ask_rules_become_denies(self):                   # K1-M5
        with open(self.user, "w") as fh:
            json.dump({"permissions": {"ask": ["Bash(git clean:*)"]}}, fh)
        rd, _ = self.render()
        self.assertIn("Bash(git clean:*)", rd.settings["permissions"]["deny"])

    def test_sources_read_once(self):                         # K1-B2
        src = S.Sources(self.user, self.r)
        with open(os.path.join(self.r, ".claude", "settings.local.json"), "w") as fh:
            json.dump({"env": {"NODE_OPTIONS": "--require /evil.js"}}, fh)
        rd = S.render("developer", "implement", worktree=self.r, base=self.base, sources=src)
        self.assertNotIn("NODE_OPTIONS", rd.env)

    def test_hooks_from_base_with_exported_gates(self):
        # a branch commit that changes the hook must not reach the rendered settings
        sp = os.path.join(self.r, ".claude", "settings.json")
        cur = json.load(open(sp))
        cur["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "echo branch"
        json.dump(cur, open(sp, "w"))
        git(self.r, "commit", "-qam", "branch hook")
        rd, run = self.render()
        cmd = rd.settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        gdir = rd.meta["gates_dir"]
        self.assertTrue(gdir.startswith(os.path.join(self.r, ".git", "guild", "engine", "gates", self.base)))
        self.assertIn(gdir + "/scripts/g.py", cmd)
        self.assertNotIn("CLAUDE_PROJECT_DIR", cmd)
        self.assertFalse(os.access(os.path.join(gdir, "scripts", "g.py"), os.W_OK))      # read-only
        self.assertTrue(S.verify_gates(gdir, rd.meta["gates_digest"]))
        self.assertNotIn("Stop", rd.settings["hooks"])        # user hooks are never carried
        self.assertEqual(rd.meta["project_base_sha"], self.base)

    def test_hook_scripts_outside_every_allow_write(self):     # K1r2-B1
        rd, run = self.render()
        sb = rd.settings["sandbox"]["filesystem"]
        cmd = rd.settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        script = cmd.split('"')[1]
        import fnmatch
        allowed = [a for a in sb["allowWrite"] if fnmatch.fnmatch(script, a) or script.startswith(a.rstrip("*").rstrip("/") + "/")]
        denied = [d for d in sb["denyWrite"] if script.startswith(d.rstrip("*").rstrip("/") + "/")]
        self.assertTrue(denied, "gate script must be under a denyWrite")
        # an allowWrite match (the developer's worktree glob is not one: .git/guild is outside it)
        self.assertFalse([a for a in allowed if not a.startswith(self.r + "/**")], allowed)
        self.assertIn(run + "/in/**", sb["denyWrite"])

    def test_tampered_gates_are_detected(self):
        rd, _ = self.render()
        g = os.path.join(rd.meta["gates_dir"], "scripts", "g.py")
        os.chmod(g, 0o644)
        with open(g, "w") as fh:
            fh.write("evil")
        self.assertFalse(S.verify_gates(rd.meta["gates_dir"], rd.meta["gates_digest"]))
        rd2, _ = self.render()                                  # re-export restores the base bytes
        self.assertTrue(S.verify_gates(rd2.meta["gates_dir"], rd2.meta["gates_digest"]))

    def test_no_hooks_for_judges(self):
        rd, _ = self.render(hooks=False)
        self.assertNotIn("hooks", rd.settings)

    def test_routing_keys_reported(self):
        with open(self.user, "w") as fh:
            json.dump({"env": {"ANTHROPIC_BASE_URL": "http://x"}}, fh)
        rd, _ = self.render()
        self.assertEqual(rd.meta["routing_in_settings_env"], ["ANTHROPIC_BASE_URL"])

    def test_unknown_base(self):
        with self.assertRaises(S.SettingsError):
            S.render("developer", "implement", worktree=self.r, base="nope", user_settings=self.user)

    def test_extra_hooks(self):
        rd, _ = self.render(extra_hooks={"PermissionDenied": [{"matcher": "*", "hooks": []}]})
        self.assertIn("PermissionDenied", rd.settings["hooks"])


class Scope(unittest.TestCase):
    def setUp(self):
        self.r = repo(self, {"lib/a.dart": "a\n", "docs/specs/7/test-cases.md": "x\n", "test/a_test.dart": "t\n"})
        git(self.r, "switch", "-q", "-c", "feat")

    def snap(self):
        return SC.snapshot(self.r)

    def write(self, rel, text="z\n"):
        p = os.path.join(self.r, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a") as fh:
            fh.write(text)

    def test_reader_writing_is_a_violation(self):
        b = self.snap()
        self.write("lib/a.dart")
        v = SC.check(self.r, b, self.snap(), ["reviewer"])
        self.assertTrue(v and "lib/a.dart" in v[0])

    def test_second_edit_of_dirty_file_seen(self):
        self.write("lib/a.dart")
        b = self.snap()
        self.write("lib/a.dart", "again\n")
        self.assertEqual(SC.changed_paths(b, self.snap()), ["lib/a.dart"])

    def test_tester_cases_scope(self):
        b = self.snap()
        self.write("docs/specs/7/test-cases.md")
        self.assertEqual(SC.check(self.r, b, self.snap(), ["tester-cases"], issue=7), [])

    def test_parallel_union_and_attribution(self):
        b = self.snap()
        self.write("docs/specs/7/test-cases.md")
        self.write("lib/a.dart")
        v = SC.check(self.r, b, self.snap(), ["tester-cases", "tech-writer", "reviewer"], issue=7)
        self.assertEqual(len(v), 1)
        self.assertIn("one of tester-cases,tech-writer,reviewer wrote lib/a.dart", v[0])

    def test_protected_paths_for_everyone(self):
        b = self.snap()
        self.write(".claude/settings.json", "{}")
        v = SC.check(self.r, b, self.snap(), ["developer"], branch="feat")
        self.assertTrue(any("protected" in x for x in v))

    def test_developer_ff_commit_ok(self):
        b = self.snap()
        self.write("lib/a.dart")
        git(self.r, "commit", "-qam", "dev")
        self.assertEqual(SC.check(self.r, b, self.snap(), ["developer"], branch="feat"), [])

    def test_qa_commit_outside_scope(self):
        b = self.snap()
        self.write("lib/a.dart")
        git(self.r, "commit", "-qam", "qa")
        v = SC.check(self.r, b, self.snap(), ["qa"], branch="feat")
        self.assertTrue(any("lib/a.dart" in x for x in v))

    def test_reader_commit_and_branch_creation(self):
        b = self.snap()
        git(self.r, "branch", "side")
        v = SC.check(self.r, b, self.snap(), ["explorer"])
        self.assertTrue(any("refs/heads/side created" in x for x in v))

    def test_developer_left_detached(self):
        b = self.snap()
        git(self.r, "switch", "-q", "--detach")
        v = SC.check(self.r, b, self.snap(), ["developer"], branch="feat")
        self.assertTrue(any("HEAD is" in x for x in v))

    def test_non_ff_move(self):
        b = self.snap()
        git(self.r, "commit", "-q", "--amend", "-m", "rewritten")
        v = SC.check(self.r, b, self.snap(), ["developer"], branch="feat")
        self.assertTrue(any("non-fast-forward" in x for x in v))

    def test_remote_push_tripwire(self):
        bare = tmpdir(self)
        git(bare, "init", "-q", "--bare")
        git(self.r, "remote", "add", "origin", bare)
        git(self.r, "push", "-q", "origin", "feat")
        url = SC.remote_url(self.r)
        b = SC.snapshot(self.r, remote=url)
        self.write("lib/a.dart")
        git(self.r, "commit", "-qam", "x")
        git(self.r, "push", "-q", bare, "feat")               # explicit-URL push: no tracking ref moves
        git(self.r, "config", "remote.origin.url", "/nonexistent")     # B3: redirecting the remote
        v = SC.check(self.r, b, SC.snapshot(self.r, remote=url), ["developer"], branch="feat")
        self.assertTrue(any("remote refs/heads/feat moved to a local commit" in x for x in v), v)
        self.assertTrue(any("git config --local changed" in x for x in v), v)

    def test_remote_fail_closed_and_deletion(self):            # K1-B3
        bare = tmpdir(self)
        git(bare, "init", "-q", "--bare")
        git(self.r, "remote", "add", "origin", bare)
        git(self.r, "push", "-q", "origin", "feat", "feat:other")
        url = SC.remote_url(self.r)
        b = SC.snapshot(self.r, remote=url)
        git(self.r, "push", "-q", "origin", ":other")
        v = SC.check(self.r, b, SC.snapshot(self.r, remote=url), ["reviewer"])
        self.assertTrue(any("remote refs/heads/other deleted" in x for x in v), v)
        gone = dict(b, remote=None)
        self.assertTrue(any("remote unverifiable" in x for x in SC.check(self.r, gone, b, ["reviewer"])))

    def test_fetched_human_push_is_not_a_violation(self):      # K1-M6
        bare = tmpdir(self)
        git(bare, "init", "-q", "--bare")
        git(self.r, "remote", "add", "origin", bare)
        git(self.r, "push", "-q", "origin", "feat")
        other = tmpdir(self)
        git(other, "clone", "-q", bare, "c")
        c = os.path.join(other, "c")
        git(c, "config", "user.name", "h"); git(c, "config", "user.email", "h@example.invalid")
        git(c, "switch", "-q", "-c", "feature-x")
        with open(os.path.join(c, "h.txt"), "w") as fh:
            fh.write("h")
        git(c, "add", "h.txt"); git(c, "commit", "-qm", "h")
        url = SC.remote_url(self.r)
        b = SC.snapshot(self.r, remote=url)
        git(c, "push", "-q", "origin", "feature-x")
        git(self.r, "fetch", "-q", "origin")
        self.assertEqual(SC.check(self.r, b, SC.snapshot(self.r, remote=url), ["reviewer"]), [])

    def test_hooks_and_watched_files(self):                   # K1-B2
        watch = os.path.join(tmpdir(self), "settings.local.json")
        with open(watch, "w") as fh:
            fh.write("{}")
        b = SC.snapshot(self.r, watch_files=[watch])
        with open(os.path.join(self.r, ".git", "hooks", "pre-push"), "w") as fh:
            fh.write("#!/bin/sh\n")
        git(self.r, "config", "core.hooksPath", "/tmp")
        with open(watch, "w") as fh:
            fh.write('{"env": {"PATH": "/evil"}}')
        v = SC.check(self.r, b, SC.snapshot(self.r, watch_files=[watch]), ["reviewer"])
        self.assertTrue(any(x.startswith("hooks ") for x in v), v)
        self.assertTrue(any("git config --local changed" in x for x in v), v)
        self.assertFalse(any(x.startswith("file " + watch) for x in v), v)     # K1r3-M2: a human's edit
        self.assertTrue(SC.watch_warnings(b, SC.snapshot(self.r, watch_files=[watch])))

    def test_paths_with_spaces(self):                         # K1-m7
        b = self.snap()
        self.write("lib/a b.dart")
        git(self.r, "add", "-A"); git(self.r, "commit", "-qm", "sp")
        v = SC.check(self.r, b, self.snap(), ["qa"], branch="feat")
        self.assertTrue(any("lib/a b.dart" in x for x in v), v)

    def test_remote_tracking_ref_push(self):
        bare = tmpdir(self)
        git(bare, "init", "-q", "--bare")
        git(self.r, "remote", "add", "origin", bare)
        b = SC.snapshot(self.r)
        git(self.r, "push", "-q", "origin", "feat")
        v = SC.check(self.r, b, SC.snapshot(self.r), ["reviewer"])
        self.assertTrue(any("refs/remotes/origin/feat moved to a local commit" in x for x in v), v)

    def test_pause_line(self):
        self.assertTrue(SC.render_pause_line("qa", ["qa wrote lib/a.dart"]).startswith("qa wrote outside its scope — "))


class Schema(unittest.TestCase):
    S1 = {"type": "object", "required": ["a"], "additionalProperties": False,
          "properties": {"a": {"type": "string", "enum": ["x", "unsure"]},
                         "b": {"type": "array", "items": {"type": "integer"}, "minItems": 1}}}

    def test_valid(self):
        self.assertTrue(SCH.valid({"a": "x", "b": [1]}, self.S1))

    def test_errors(self):
        e = SCH.errors({"a": "y", "b": ["1"], "c": 1}, self.S1)
        self.assertTrue(any("not in" in x for x in e))
        self.assertTrue(any("$.b[0]" in x for x in e))
        self.assertTrue(any("unexpected key c" in x for x in e))
        self.assertTrue(SCH.errors({}, self.S1))

    def test_bool_is_not_integer(self):
        self.assertTrue(SCH.errors(True, {"type": "integer"}))

    def test_anyof_oneof(self):
        s = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        self.assertTrue(SCH.valid(None, s))
        self.assertFalse(SCH.valid(1, s))
        self.assertFalse(SCH.valid(1, {"oneOf": [{"type": "integer"}, {"type": "number"}]}))

    def test_unknown_keyword_is_a_schema_error(self):
        with self.assertRaises(SCH.SchemaError):
            SCH.check_schema({"type": "object", "if": {}})


if __name__ == "__main__":
    unittest.main()
