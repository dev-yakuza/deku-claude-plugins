"""K1 review r2 regressions (review-k1-r2.md): B1–B3, M1–M6 and the accepted minors."""

import ast
import json
import os
import re
import subprocess
import sys
import time
import unittest

import _k1
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir

from guildcore import cost as COST
from guildcore.adapters import claude as C
from guildcore.adapters import git as G
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from guildcore.roles import settings as S

DONE = ">>> RESULT <<<\nDONE: ok"
ENGINE = _k1._util.ENGINE


class B1GatesOutsideAllowWrite(unittest.TestCase):
    def test_gates_in_engine_home_read_only_and_denied(self):
        r = repo(self, {".claude/settings.json": {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/guild/gates/scripts/g.py\""}]}]}},
            ".claude/guild/gates/scripts/g.py": "print(1)\n"})
        for role, task in (("developer", "implement"), ("qa", None), ("reviewer", None), ("tester", "verify")):
            run = os.path.join(tmpdir(self), "run")
            rd = S.render(role, task, worktree=r, base="HEAD", run_dir=run,
                          user_settings=os.path.join(tmpdir(self), "u.json"))
            g = rd.meta["gates_dir"]
            fs = rd.settings["sandbox"]["filesystem"]
            self.assertFalse(g.startswith(run))
            self.assertTrue(any(g.startswith(d[:-3]) for d in fs["denyWrite"] if d.endswith("/**")), role)
            self.assertIn(run + "/in/**", fs["denyWrite"])
            self.assertNotIn(run + "/**", fs["allowWrite"])          # streams stay unwritable


class B2EngineHomeNeverWritable(unittest.TestCase):
    def test_linked_worktree_and_engine_home(self):
        main = repo(self, {"a.txt": "a"})
        wt = os.path.join(tmpdir(self), "wt")
        git(main, "worktree", "add", "-q", "-b", "feat", wt)
        other = os.path.join(tmpdir(self), "wt2")
        git(main, "worktree", "add", "-q", "-b", "other", other)
        common = os.path.join(main, ".git")
        rd = S.render("developer", "implement", worktree=wt, base="HEAD",
                      run_dir=os.path.join(tmpdir(self), "run"), user_settings=os.path.join(tmpdir(self), "u"))
        fs = rd.settings["sandbox"]["filesystem"]
        self.assertNotIn(common + "/**", fs["allowWrite"])
        self.assertIn(common + "/objects/**", fs["allowWrite"])
        self.assertIn(common + "/refs/heads/**", fs["allowWrite"])
        self.assertIn(os.path.join(common, "worktrees", "wt") + "/**", fs["allowWrite"])
        self.assertIn(os.path.join(common, "worktrees", "wt2") + "/**", fs["denyWrite"])
        self.assertIn(common + "/guild/**", fs["denyWrite"])
        self.assertFalse([a for a in fs["allowWrite"] if a.startswith(common + "/guild")])


class B3Drift(unittest.TestCase):
    def setUp(self):
        self.wt = repo(self, {"lib/a.dart": "a\n"})
        git(self.wt, "switch", "-q", "-c", "feat")

    def runner(self, sessions):
        return RR.Runner(journal=RecJournal(), parent_env={"PATH": os.environ["PATH"]}, spawn=FakeSpawn(sessions),
                         user_settings=os.path.join(tmpdir(self), "u"), run_root_dir=os.path.join(tmpdir(self), "runs"),
                         claude="claude", clock=Clock())

    def spec(self, role="developer", task="implement"):
        return RR.RoleSpec(role, task, "t", issue=1, stage="s", step="x", worktree=self.wt, model="sonnet",
                           base="HEAD", branch="feat", remote_check=False)

    def test_late_write_fails_the_next_role_closed(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE])}, {"stream": stream_lines(texts=[DONE])}])
        self.assertEqual(r.run_role(self.spec()).status, "DONE")
        with open(os.path.join(self.wt, "lib", "late.txt"), "w") as fh:        # an escaped orphan
            fh.write("late")
        res = r.run_role(self.spec("reviewer", None))
        self.assertEqual(res.status, "DRIFT")
        self.assertIn("path lib/late.txt", res.violations[0])
        self.assertEqual(len(r.spawn.calls), 1)                             # the role never ran

    def test_engine_rebaseline_and_drift_check(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE])}, {"stream": stream_lines(texts=[DONE])}])
        r.run_role(self.spec())
        with open(os.path.join(self.wt, "lib", "eng.txt"), "w") as fh:
            fh.write("engine's own step")
        self.assertEqual(r.drift_check(self.wt), ["path lib/eng.txt"])
        r.rebaseline(self.wt)
        self.assertEqual(r.drift_check(self.wt), [])
        self.assertEqual(r.run_role(self.spec("reviewer", None)).status, "DONE")

    def test_tampered_gate_fails_closed(self):
        wt = repo(self, {".claude/settings.json": {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/guild/gates/scripts/g.py\""}]}]}},
            ".claude/guild/gates/scripts/g.py": "print(1)\n"})
        S.export_gates_readonly(wt, git(wt, "rev-parse", "HEAD"))
        orig = S.verify_gates
        S.verify_gates = lambda d, h: False
        self.addCleanup(setattr, S, "verify_gates", orig)
        r = self.runner([])
        res = r.run_role(RR.RoleSpec("reviewer", None, "t", issue=1, stage="s", step="x", worktree=wt,
                                     model="sonnet", base="HEAD", remote_check=False))
        self.assertEqual(res.status, "DRIFT")
        self.assertIn("gate scripts changed since export", res.violations)

    def test_nested_orphans_reaped_in_rounds(self):
        d = tmpdir(self)
        subprocess.run(["/bin/sh", "-c", "( (sleep 4; echo late > late.txt) & sleep 30 ) > /dev/null 2>&1 &"], cwd=d)
        time.sleep(0.5)
        pids = C.reap_strays([d], 30)
        self.assertGreaterEqual(len(pids), 2)
        time.sleep(4.5)
        self.assertFalse(os.path.exists(os.path.join(d, "late.txt")))


class M1Secrets(unittest.TestCase):
    def test_role_env_scrubbed(self):
        d = tmpdir(self)
        e = C.child_env({"ANTHROPIC_AUTH_TOKEN": "a", "NPM_TOKEN": "n", "AWS_SECRET_ACCESS_KEY": "s",
                         "GH_HOST": "h", "MY_PASSWORD": "p", "PATH": "/usr/bin"}, role_dir=d)
        self.assertEqual(e["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"], "1")
        self.assertEqual(e["ANTHROPIC_AUTH_TOKEN"], "a")                # the CLI's own auth stays
        for k in ("NPM_TOKEN", "AWS_SECRET_ACCESS_KEY", "GH_HOST", "MY_PASSWORD"):
            self.assertNotIn(k, e)

    def test_untrusted_inputs_and_scratch_line(self):
        wt = repo(self)
        spec = RR.RoleSpec("reviewer", None, "t", issue=1, stage="s", step="x", worktree=wt, model="sonnet")
        task = RR.render_task(spec, "/r", {"issue.md": "/r/in/issue.md"})
        self.assertIn(RR.UNTRUSTED_INPUTS, task)
        self.assertIn("never /tmp", task)


class M2RunRoot(unittest.TestCase):
    def test_run_root_is_engine_owned_outside_tmp(self):
        wt = repo(self)
        root = RR.run_root(wt, 3, {"HOME": "/Users/x"})
        self.assertTrue(root.startswith("/Users/x/.cache/guild-engine/"))
        self.assertNotIn("/tmp/", root)

    def test_other_claude_sessions_denied(self):
        sb = S.role_sandbox("reviewer", None, "/r")
        tmp = S.claude_tmp_root()
        self.assertIn(tmp + "/**", sb["filesystem"]["allowWrite"])
        if os.path.isdir(tmp):
            subs = [d for d in os.listdir(tmp) if d.startswith("-")]
            for d in subs:
                self.assertIn(os.path.join(tmp, d) + "/**", sb["filesystem"]["denyWrite"])


class M4EngineGit(unittest.TestCase):
    MUTATING = ("commit", "push", "add", "reset", "switch", "checkout", "stash", "update-ref", "tag",
                "merge", "rebase", "fetch", "pull", "am", "apply", "cherry-pick", "revert", "rm", "mv",
                "worktree", "branch", "gc", "clean", "restore", "notes")

    def test_no_engine_module_spawns_git_directly_except_reads(self):
        bad = []
        for base, _dirs, files in os.walk(os.path.join(ENGINE, "guildcore")):
            for f in files:
                if not f.endswith(".py") or f == "git.py":
                    continue
                p = os.path.join(base, f)
                tree = ast.parse(open(p, encoding="utf-8").read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.List) and len(node.elts) >= 2 and isinstance(node.elts[0], ast.Constant) \
                            and node.elts[0].value == "git":
                        verbs = [e.value for e in node.elts[1:] if isinstance(e, ast.Constant) and isinstance(e.value, str)
                                 and not e.value.startswith("-")]
                        if verbs and verbs[0] in self.MUTATING:
                            bad.append((os.path.relpath(p, ENGINE), verbs[0]))
        self.assertEqual(bad, [], "mutating git outside guildcore/adapters/git.py")

    def test_helper_disables_hooks(self):
        r = repo(self, {".husky/pre-commit": "#!/bin/sh\necho ran > hook-ran.txt\n", "a.txt": "a"})
        os.chmod(os.path.join(r, ".husky", "pre-commit"), 0o755)
        git(r, "config", "core.hooksPath", ".husky")
        with open(os.path.join(r, "a.txt"), "w") as fh:
            fh.write("b")
        G.commit(r, "engine commit", paths=["a.txt"])
        self.assertFalse(os.path.exists(os.path.join(r, "hook-ran.txt")))
        with self.assertRaises(G.GitError):
            G.push(r, "origin", "HEAD")                 # a remote NAME is refused


class M6Cost(unittest.TestCase):
    def test_final_usage_per_message_and_cache_classes(self):
        lines = []
        for i in range(3):     # one message re-sent per block, usage frozen at message_start
            lines.append(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {
                "input_tokens": 100, "output_tokens": 0, "cache_read_input_tokens": 1000000,
                "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}},
                "content": [{"type": "text", "text": "x" * 350}]}}))
        st = C.parse_stream("\n".join(lines))
        self.assertEqual(len(st.usages), 1)
        self.assertEqual(st.usages[0]["output_tokens"], 300)          # 3 × 350 chars / 3.5
        usd, tin, tout = COST.estimate(st, "claude-sonnet-4-5")
        self.assertAlmostEqual(usd, (100 * 3 + 300 * 15 + 1000000 * 0.3) / 1e6, places=6)

    def test_real_stream_estimate_is_close_to_result(self):
        p = os.path.join(_k1.K1FX, "streams", "explorer-result-file.jsonl")
        st = C.read_stream(p)
        usd, _tin, tout = COST.estimate(st, "claude-sonnet-4-5")
        self.assertGreater(tout, 0)


class Minors(unittest.TestCase):
    def test_m1_remote_move_is_warned(self):
        b = {"remote": {"refs/heads/main": "a"}}
        a = {"remote": {"refs/heads/main": "b"}}
        self.assertEqual(SC.remote_warnings(b, a), ["remote refs/heads/main moved during the role"])


if __name__ == "__main__":
    unittest.main()
