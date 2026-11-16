"""K1 review r4 regressions (review-k1-r4.md): real-HOME git, toolchain sandbox, deps step,
sandboxed hooks, run_group cause line."""

import http.client
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import _k1
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir

from guildcore import checks as CH
from guildcore.checks.netproxy import AllowlistProxy
from guildcore.roles import runner as RR
from guildcore.roles import settings as S

DONE = ">>> RESULT <<<\nDONE: ok"


def home_dir(case):
    """A dir OUTSIDE $TMPDIR (sandbox-exec subpaths under /var/folders behave differently)."""
    base = os.path.join(os.path.expanduser("~"), ".cache")
    os.makedirs(base, exist_ok=True)
    d = os.path.realpath(tempfile.mkdtemp(dir=base, prefix="gld-k1-r4-"))
    case.addCleanup(shutil.rmtree, d, True)
    return d


class M1RealHomeGit(unittest.TestCase):
    def test_safe_gitconfig_keys(self):
        r = repo(self)
        dest = os.path.join(tmpdir(self), "gitconfig")
        env = S.render_gitconfig(r, dest)
        self.assertEqual(env, {"GIT_CONFIG_GLOBAL": dest, "GIT_CONFIG_NOSYSTEM": "1"})
        text = open(dest).read()
        self.assertIn("[user]", text)
        for bad in ("credential", "alias", "hookspath", "include", "insteadof", "sshcommand", "gpgsign"):
            self.assertNotIn(bad, text.lower())

    def test_git_works_with_denied_real_style_home(self):
        if not os.path.exists(CH.SANDBOX_EXEC):
            self.skipTest("no sandbox-exec")
        d = home_dir(self)
        home = os.path.join(d, "home")
        os.makedirs(home)
        with open(os.path.join(home, ".gitconfig"), "w") as fh:        # the REAL layout: it exists
            fh.write("[user]\n\tname = h\n\temail = h@example.invalid\n[credential]\n\thelper = osxkeychain\n")
        wt = os.path.join(d, "wt")
        subprocess.run(["git", "init", "-q", wt], check=True)
        blk = {"filesystem": {"allowWrite": [wt + "/**"], "denyRead": [os.path.join(home, ".gitconfig")]}}
        env = dict(os.environ, HOME=home)
        bad = CH.run_command("git status >/dev/null 2>&1; echo rc=$?", 60, cwd=wt, env=env, sandbox=blk,
                             tmp=os.path.join(d, "tmp"))
        self.assertIn("rc=128", bad.raw)                       # the r4-M1 failure, reproduced
        env.update(S.render_gitconfig(wt, os.path.join(d, "gitconfig")))
        ok = CH.run_command("git status >/dev/null 2>&1; echo rc=$?", 60, cwd=wt, env=env, sandbox=blk,
                            tmp=os.path.join(d, "tmp2"))
        self.assertIn("rc=0", ok.raw)

    def test_runner_env_file_carries_git_config(self):
        wt = repo(self)
        spawn = FakeSpawn([{"stream": stream_lines(texts=[DONE])}])
        r = RR.Runner(journal=RecJournal(), parent_env={"PATH": os.environ["PATH"]}, spawn=spawn,
                      user_settings=os.path.join(tmpdir(self), "u"), run_root_dir=os.path.join(tmpdir(self), "runs"),
                      claude="claude", clock=Clock())
        r.run_role(RR.RoleSpec("developer", "implement", "t", issue=1, stage="s", step="x", worktree=wt,
                               model="m", base="HEAD", remote_check=False))
        env = spawn.calls[0]["env"]
        ef = env["CLAUDE_ENV_FILE"]
        text = open(ef).read()
        self.assertIn("export GIT_CONFIG_GLOBAL=", text)
        self.assertIn("export GIT_AUTHOR_NAME=", text)
        self.assertTrue(ef.endswith("/in/env.sh"))
        self.assertFalse(os.access(ef, os.W_OK))


class M2Toolchain(unittest.TestCase):
    def test_flutter_writer_sandbox(self):
        r = repo(self, {"pubspec.yaml": "name: x\n", "package.json": "{}"})
        run = os.path.join(tmpdir(self), "run")
        rd = S.render("developer", "implement", worktree=r, base="HEAD", run_dir=run,
                      user_settings=os.path.join(tmpdir(self), "u"))
        sb = rd.settings["sandbox"]
        home = os.path.expanduser("~")
        for want in (".pub-cache", ".dart-tool", ".config/flutter", ".npm"):
            self.assertIn(os.path.join(home, want) + "/**", sb["filesystem"]["allowWrite"])
        self.assertTrue(sb["network"]["allowLocalBinding"])
        self.assertTrue(sb["enableWeakerNetworkIsolation"])
        self.assertIn("pub.dev", sb["network"]["allowedDomains"])
        self.assertNotIn("api.github.com", sb["network"]["allowedDomains"])

    def test_reader_has_no_network_and_no_weaker_isolation(self):
        r = repo(self, {"pubspec.yaml": "name: x\n"})
        rd = S.render("reviewer", None, worktree=r, base="HEAD", run_dir=os.path.join(tmpdir(self), "run"),
                      user_settings=os.path.join(tmpdir(self), "u"))
        sb = rd.settings["sandbox"]
        self.assertEqual(sb["network"]["allowedDomains"], [])
        self.assertFalse(sb["enableWeakerNetworkIsolation"])

    def test_no_sdk_for_non_flutter_repo(self):
        self.assertIsNone(S.flutter_sdk(repo(self)))

    def test_user_tool_cache_entries_merged_secrets_never(self):
        tw = S.toolchain_writes(None, {"filesystem": {"allowWrite": ["~/.gradle/**", "~/.ssh/**"]}}, home="/h")
        self.assertIn(os.path.expanduser("~/.gradle/**"), tw)
        self.assertFalse([t for t in tw if "/.ssh" in t])


class DepsStep(unittest.TestCase):
    def test_allowlist_proxy(self):
        with AllowlistProxy(["pub.dev"]) as px:
            host, port = px.url.split("//")[1].split(":")
            c = http.client.HTTPConnection(host, int(port), timeout=5)
            c.request("CONNECT", "api.github.com:443")
            self.assertEqual(c.getresponse().status, 403)
            self.assertEqual(px.summary(), {"api.github.com:443 DENIED": 1})
            self.assertIn("127.0.0.1", px.env()["NO_PROXY"])

    def test_hosts_from_manifests(self):
        r = repo(self, {"pubspec.yaml": "name: x\n"})
        h = CH.deps_hosts(r)
        self.assertIn("pub.dev", h)
        self.assertIn("release-assets.githubusercontent.com", h)
        self.assertNotIn("api.github.com", h)

    def test_deps_step_runs_sandboxed_through_the_proxy(self):
        if not os.path.exists(CH.SANDBOX_EXEC):
            self.skipTest("no sandbox-exec")
        d = home_dir(self)
        wt = os.path.join(d, "wt")
        os.makedirs(wt)
        r, summary = CH.deps_step("echo P=$HTTPS_PROXY; /usr/bin/curl -s -m 5 -o /dev/null https://api.github.com/zen; echo rc=$?",
                                  wt, {"filesystem": {"allowWrite": [wt + "/**"]}}, os.path.join(d, "tmp"),
                                  hosts=["pub.dev"])
        self.assertIn("P=http://127.0.0.1:", r.raw)
        self.assertNotIn("rc=0", r.raw)
        self.assertEqual(summary, {"api.github.com:443 DENIED": 1})


class SandboxedHooks(unittest.TestCase):
    def test_worktree_hook_runs_inside_the_role_sandbox(self):
        if not os.path.exists(CH.SANDBOX_EXEC):
            self.skipTest("no sandbox-exec")
        d = home_dir(self)
        wt = os.path.join(d, "wt")
        subprocess.run(["git", "init", "-q", "-b", "main", wt], check=True)
        outside = os.path.join(d, "outside.txt")
        os.makedirs(os.path.join(wt, ".claude"))
        with open(os.path.join(wt, ".claude", "settings.json"), "w") as fh:
            json.dump({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "echo x > %s; echo hook-rc=$?" % outside}]}]}}, fh)
        for k, v in (("user.name", "t"), ("user.email", "t@example.invalid")):
            subprocess.run(["git", "config", k, v], cwd=wt)
        subprocess.run(["git", "add", "-A"], cwd=wt)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=wt)
        run = os.path.join(d, "run")
        rd = S.render("developer", "implement", worktree=wt, base="HEAD", run_dir=run,
                      user_settings=os.path.join(d, "u.json"))
        cmd = rd.settings["hooks"]["PreToolUse"][-1]["hooks"][0]["command"]
        self.assertTrue(cmd.startswith(CH.SANDBOX_EXEC))
        p = subprocess.run(["/bin/sh", "-c", cmd], cwd=wt, input=b"{}", stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        self.assertFalse(os.path.exists(outside))               # the hook ran, confined
        self.assertIn(b"hook-rc=", p.stdout)
        self.assertEqual(rd.meta["hooks_skipped"], [])


class GroupCauseLine(unittest.TestCase):
    def test_role_names_not_status_in_the_pause_line(self):
        wt = repo(self, {"lib/a.dart": "a"})
        git(wt, "switch", "-q", "-c", "feat")

        def touch(argv, env, cwd, stdin):
            with open(os.path.join(cwd, "lib", "a.dart"), "a") as fh:
                fh.write("x")
        r = RR.Runner(journal=RecJournal(), parent_env={"PATH": os.environ["PATH"]},
                      spawn=FakeSpawn([{"stream": stream_lines(texts=[DONE]), "check": touch},
                                       {"stream": stream_lines(texts=[DONE])}]),
                      user_settings=os.path.join(tmpdir(self), "u"), run_root_dir=os.path.join(tmpdir(self), "runs"),
                      claude="claude", clock=Clock())
        sp = [RR.RoleSpec(role, task, "t", issue=7, stage="s", step="x", worktree=wt, model="m", base="HEAD",
                          branch="feat", remote_check=False) for role, task in (("tech-lead", "design"), ("tester", "cases"))]
        res = r.run_group(sp)
        self.assertTrue(res[0].line.startswith("one of tech-lead-design,tester-cases wrote outside its scope — "),
                        res[0].line)


if __name__ == "__main__":
    unittest.main()
