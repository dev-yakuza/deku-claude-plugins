"""K1 review r3 regressions (review-k1-r3.md) under the Q24 threat model."""

import importlib.util
import json
import os
import py_compile
import subprocess
import sys
import unittest

import _k1
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir

from guildcore import checks as CH
from guildcore.adapters import git as G
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from guildcore.roles import settings as S

DONE = ">>> RESULT <<<\nDONE: ok"


class M4ScpPush(unittest.TestCase):
    def test_scp_and_ssh_aliases_are_fixed_urls(self):
        r = repo(self)
        git(r, "remote", "add", "origin", "git@github.com:o/r.git")
        for u in ("git@github.com:SafieDev/x.git", "git@personal:deku-word-app/word_app.git",
                  "github.com:o/r.git", "ssh://git@github.com/o/r.git", "https://github.com/o/r.git", "/abs/bare.git"):
            self.assertTrue(G.is_fixed_url(r, u), u)
        for u in ("origin", "", "upstream-name"):
            self.assertFalse(G.is_fixed_url(r, u), u)

    def test_push_to_scp_style_local_alias(self):
        r = repo(self)
        bare = tmpdir(self)
        git(bare, "init", "-q", "--bare")
        G.push(r, bare, "HEAD:refs/heads/x")
        self.assertTrue(git(bare, "rev-parse", "refs/heads/x"))
        with self.assertRaises(G.GitError):
            G.push(r, "origin", "HEAD")


class Base(unittest.TestCase):
    def setUp(self):
        self.wt = repo(self, {"lib/a.dart": "a\n", "docs/specs/7/x.md": "x"})
        git(self.wt, "switch", "-q", "-c", "feat")
        self.user = os.path.join(tmpdir(self), "u.json")

    def runner(self, sessions):
        return RR.Runner(journal=RecJournal(), parent_env={"PATH": os.environ["PATH"]}, spawn=FakeSpawn(sessions),
                         user_settings=self.user, run_root_dir=os.path.join(tmpdir(self), "runs"),
                         claude="claude", clock=Clock())

    def spec(self, role, task=None):
        return RR.RoleSpec(role, task, "t", issue=7, stage="s", step="x", worktree=self.wt, model="sonnet",
                           base="HEAD", branch="feat", remote_check=False)


def write(rel):
    def f(argv, env, cwd, stdin):
        p = os.path.join(cwd, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a") as fh:
            fh.write("x")
    return f


class M1ParallelGroup(Base):
    def test_group_results_do_not_drift_the_next_role(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE])},
                         {"stream": stream_lines(texts=[DONE]), "check": write("docs/specs/7/test-cases.md")},
                         {"stream": stream_lines(texts=[DONE])}])
        self.assertEqual(r.run_role(self.spec("reviewer")).status, "DONE")
        g = r.run_group([self.spec("tester", "cases")])
        self.assertEqual(g[0].status, "DONE")
        self.assertEqual(r.run_role(self.spec("reviewer")).status, "DONE")

    def test_group_union_scope(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE]), "check": write("lib/a.dart")}])
        g = r.run_group([self.spec("tester", "cases")])
        self.assertEqual(g[0].status, "SCOPE")

    def test_unchecked_role_without_rebaseline_is_a_contract_error(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE])}, {"stream": stream_lines(texts=[DONE])}])
        sp = self.spec("reviewer")
        sp.scope_check = False
        r.run_role(sp)
        with self.assertRaises(RR.BaselineContract):
            r.run_role(self.spec("reviewer"))
        r.rebaseline(self.wt, 7)
        self.assertEqual(r.run_role(self.spec("reviewer")).status, "DONE")


class M2WatchFiles(Base):
    def test_human_settings_edit_does_not_void_the_role(self):
        main_local = os.path.join(self.wt, ".claude", "settings.local.json")
        os.makedirs(os.path.dirname(main_local), exist_ok=True)
        with open(main_local, "w") as fh:
            fh.write("{}")

        def human(argv, env, cwd, stdin):
            with open(main_local, "w") as fh:
                fh.write('{"permissions": {"allow": ["Bash(ls:*)"]}}')
        r = self.runner([{"stream": stream_lines(texts=[DONE]), "check": human}])
        res = r.run_role(self.spec("developer", "implement"))
        self.assertEqual(res.status, "DONE")
        self.assertTrue(any("settings.local.json changed" in n for n in res.notes), res.notes)


class M3PersistedBaseline(Base):
    def test_restart_keeps_the_baseline(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE])}])
        r.run_role(self.spec("developer", "implement"))
        with open(os.path.join(self.wt, "lib", "late.dart"), "w") as fh:     # while "paused"
            fh.write("late")
        r2 = self.runner([{"stream": stream_lines(texts=[DONE])}])
        res = r2.run_role(self.spec("developer", "implement"))
        self.assertEqual(res.status, "DRIFT")
        self.assertEqual(r2.drift_check(self.wt, 7), ["path lib/late.dart"])
        r2.rebaseline(self.wt, 7)                           # the human accepted the edit
        self.assertEqual(r2.drift_check(self.wt, 7), [])

    def test_baseline_file_in_engine_home(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE])}])
        r.run_role(self.spec("reviewer"))
        p = r._baseline_path(self.wt, 7)
        self.assertTrue(p.startswith(os.path.join(self.wt, ".git", "guild", "engine")))
        self.assertTrue(os.path.exists(p))


class B2BaseOnlyHooks(unittest.TestCase):
    def test_every_hook_runs_a_base_copy_or_is_dropped(self):
        r = repo(self, {".claude/settings.json": {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "sh \"${CLAUDE_PROJECT_DIR}/scripts/fmt.sh\""},
            {"type": "command", "command": "npx prettier --check ."},
            {"type": "command", "command": "./scripts/fmt.sh"}]}],
            "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "npm run format"}]}]}},
            "scripts/fmt.sh": "echo base\n"})
        with open(os.path.join(r, "scripts", "fmt.sh"), "w") as fh:          # a role's later edit
            fh.write("echo evil\n")
        rd = S.render("developer", "implement", worktree=r, base="HEAD",
                      run_dir=os.path.join(tmpdir(self), "run"), user_settings=os.path.join(tmpdir(self), "u"))
        cmds = [h["command"] for g in rd.settings["hooks"].get("PreToolUse", []) for h in g["hooks"]]
        base_cmds = [c for c in cmds if "sandbox-exec" not in c]
        self.assertEqual(len(base_cmds), 1)
        # K1r4 (a): the worktree-running hooks are wrapped in the role sandbox, not dropped
        self.assertEqual(len([c for c in cmds if "sandbox-exec" in c]), 2)
        post = [h["command"] for g in rd.settings["hooks"].get("PostToolUse", []) for h in g["hooks"]]
        self.assertTrue(post and all(c.startswith("/usr/bin/sandbox-exec -f ") for c in post))
        path = base_cmds[0].split('"')[1]
        self.assertTrue(path.startswith(os.path.join(r, ".git", "guild", "engine", "hooks")))
        self.assertEqual(open(path).read(), "echo base\n")
        self.assertFalse(os.access(path, os.W_OK))
        self.assertEqual(sorted(rd.meta["hooks_sandboxed"]),
                         sorted(["npx prettier --check .", "./scripts/fmt.sh", "npm run format"]))
        self.assertEqual(rd.meta["hooks_skipped"], [])
        fs = rd.settings["sandbox"]["filesystem"]
        self.assertTrue(any(path.startswith(d[:-3]) for d in fs["denyWrite"] if d.endswith("/**")))


class M5DenyRead(unittest.TestCase):
    def test_extended_secret_paths(self):
        sb = S.role_sandbox("reviewer", None, "/r", homes=["/h"])
        dr = sb["filesystem"]["denyRead"]
        for rel in (".zsh_history", ".bash_history", ".zshrc", ".gitconfig", "Library/Application Support",
                    ".netrc", ".npmrc", ".pub-cache/credentials.json", "Library/Cookies"):
            self.assertIn(os.path.join("/h", rel), dr)
            self.assertIn(os.path.join(os.path.expanduser("~"), rel), dr)

    def test_commit_identity_from_the_engine(self):
        r = repo(self)
        ident = RR.git_identity(r)
        self.assertEqual((ident["GIT_AUTHOR_NAME"], ident["GIT_COMMITTER_EMAIL"]), ("t", "t@example.invalid"))


class B1SandboxedChecks(unittest.TestCase):
    def setUp(self):
        if not os.path.exists(CH.SANDBOX_EXEC):
            self.skipTest("no sandbox-exec on this host")
        base = os.path.join(os.path.expanduser("~"), ".cache")
        os.makedirs(base, exist_ok=True)
        import tempfile, shutil
        self.d = os.path.realpath(tempfile.mkdtemp(dir=base, prefix="gld-k1-checks-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.wt = os.path.join(self.d, "wt")
        os.makedirs(self.wt)
        self.tmp = os.path.join(self.d, "tmp")

    def test_checks_honour_the_role_sandbox(self):
        out = os.path.join(self.d, "out")
        os.makedirs(out)
        blk = {"filesystem": {"allowWrite": [out + "/**"], "denyWrite": [self.wt + "/**"],
                              "denyRead": [os.path.join(self.d, "secret")]}}
        with open(os.path.join(self.d, "secret"), "w") as fh:
            fh.write("s")
        r = CH.run_command(["echo ok > %s/f; echo w=$?" % out, "echo x > a.txt; echo wt=$?",
                            "cat %s/secret >/dev/null 2>&1; echo rd=$?" % self.d,
                            "/usr/bin/curl -s -m 3 https://api.github.com/zen >/dev/null; echo net=$?",
                            "cat <<EOF\nheredoc-ok\nEOF"],
                           60, cwd=self.wt, sandbox=blk, tmp=self.tmp)
        self.assertIn("w=0", r.raw)
        self.assertNotIn("wt=0", r.raw)
        self.assertNotIn("rd=0", r.raw)
        self.assertNotIn("net=0", r.raw)
        self.assertIn("heredoc-ok", r.raw)

    def test_untracked_pyc_is_not_executed(self):
        with open(os.path.join(self.wt, "mod.py"), "w") as fh:
            fh.write("print('mod: genuine')\n")
        evil_src = os.path.join(self.d, "evil.py")
        flag = os.path.join(self.d, "pwned.txt")
        with open(evil_src, "w") as fh:
            fh.write("open(%r, 'w').write('x')\nprint('mod: genuine')\n" % flag)
        tag = sys.implementation.cache_tag
        pyc = os.path.join(self.wt, "__pycache__", "mod.%s.pyc" % tag)
        os.makedirs(os.path.dirname(pyc))
        py_compile.compile(evil_src, cfile=pyc, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        r = CH.run_command("%s -c 'import mod'" % sys.executable, 60, cwd=self.wt,
                           sandbox={"filesystem": {"allowWrite": []}}, tmp=self.tmp)
        self.assertIn("mod: genuine", r.raw)
        self.assertFalse(os.path.exists(flag))

    def test_sandboxed_check_needs_private_tmp(self):
        with self.assertRaises(ValueError):
            CH.run_command("true", 10, cwd=self.wt, sandbox={})


class TmpRule(unittest.TestCase):
    def test_task_says_tmpdir_not_tmp(self):
        spec = RR.RoleSpec("developer", "implement", "t", issue=1, stage="s", step="x", worktree=repo(self), model="m")
        self.assertIn("Temporary files go under $TMPDIR, never /tmp", RR.render_task(spec, "/r", {}))


if __name__ == "__main__":
    unittest.main()
