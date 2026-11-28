"""The test tools themselves: fake claude (F1/F2 replay + scenarios), fake gh, git repo helper."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

from tests.helpers import fakes
from tests.helpers.gitrepo import GitRepo

F1 = ("A", "A2", "A3", "B", "Bm", "Bw", "C", "Cw", "De", "Dw")
F2 = ("r1", "r2", "r3", "r4", "r5ctl")


def run(argv, env, cwd, timeout=20, **kw):
    """Run a fake by ABSOLUTE path, after checking the env cannot reach the real tools."""
    fakes.assert_fakes_first(env)
    exe = {"claude": fakes.FAKE_CLAUDE, "gh": fakes.FAKE_GH}[argv[0]]
    return subprocess.run([exe, *argv[1:]], env=env, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=timeout, **kw)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def events(stdout):
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


class RecordedFixtures(unittest.TestCase):
    """The F1/F2 recordings copied as default fixtures (Claude Code 2.1.323)."""

    def test_every_recording_is_a_full_session(self):
        for d, names in (("f1", F1), ("f2", F2)):
            for n in names:
                with self.subTest(fixture=f"{d}/{n}"):
                    ev = fakes.read_stream(fakes.fixture("claude", d, n + ".jsonl"))
                    self.assertEqual((ev[0]["type"], ev[0]["subtype"]), ("system", "init"))
                    self.assertEqual(ev[-1]["type"], "result")
                    self.assertEqual(ev[0]["claude_code_version"], "2.1.323")

    def test_recorded_init_matches_the_design_facts(self):
        """§7.6 / F1 / F2: permissionMode default, builtin plugins/agents, no Grep/Glob tool."""
        ev = fakes.read_stream(fakes.fixture("claude", "f2", "r4.jsonl"))
        init = ev[0]
        self.assertEqual(init["permissionMode"], "default")
        self.assertEqual(init["skills"], [])
        self.assertEqual(init["slash_commands"], [])
        self.assertEqual(init["mcp_servers"], [])
        from gxengine import defaults
        # the recorded F2 builtins of CLI 2.1.323 (the engine no longer compares them — FC decision D)
        self.assertEqual(tuple(p["source"] for p in init["plugins"]),
                         ("cc-plugin-agents-md@builtin", "cc-plugin-privacy@builtin", "cc-plugin-plugin-authoring@builtin"))
        self.assertEqual(tuple(init["agents"]), ("claude", "Explore", "general-purpose", "Plan", "statusline-setup"))
        self.assertNotIn("Grep", init["tools"])
        self.assertNotIn("Glob", init["tools"])
        r1 = fakes.read_stream(fakes.fixture("claude", "f2", "r1.jsonl"))[0]
        self.assertTrue(r1["skills"], "without --disable-slash-commands the builtin skills load (F2)")
        ctl = fakes.read_stream(fakes.fixture("claude", "f2", "r5ctl.jsonl"))[0]
        self.assertGreater(len(ctl["plugins"]), 3, "control run with setting sources loads user plugins")

    def test_hook_block_recorded(self):
        """F2 r4: the rendered PreToolUse hook blocked `git commit -n` (exit 2, S9)."""
        ev = fakes.read_stream(fakes.fixture("claude", "f2", "r4.jsonl"))
        denials = ev[-1]["permission_denials"]
        self.assertTrue(any("commit -n" in d["tool_input"].get("command", "") for d in denials))

    def test_recordings_are_redacted(self):
        for d, names in (("f1", F1), ("f2", F2)):
            for n in names:
                text = read(fakes.fixture("claude", d, n + ".jsonl"))
                with self.subTest(fixture=f"{d}/{n}"):
                    self.assertNotIn("/Users/j-", text)
                    self.assertNotIn("MESSAGING_TOKEN=", text.replace("MESSAGING_TOKEN=<redacted>", ""))
        b = read(fakes.fixture("claude", "f1", "C.jsonl"))
        self.assertIn("CLAUDE_CODE_MESSAGING_TOKEN=<redacted>", b)
        self.assertIn("PATH=<redacted>", b)


class FakeClaude(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-fake-"))
        self.log = os.path.join(self.tmp, "log")
        self.wt = os.path.join(self.tmp, "wt")
        os.makedirs(self.wt)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, *scenarios, **kw):
        return fakes.fake_env(claude_scenarios=[fakes.scn(s) if not os.path.isabs(s) else s for s in scenarios],
                              claude_log=self.log, **kw)

    def scenario(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(body, f)
        return path

    def test_is_found_on_path(self):
        env = self.env()
        self.assertEqual(shutil.which("claude", path=env["PATH"]), os.path.join(fakes.FAKE_BIN, "claude"))

    def test_version(self):
        p = run(["claude", "--version"], self.env(), self.wt)
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "2.1.323 (Claude Code)"))
        p = run(["claude", "--version"], self.env(claude_version="9.9.9 (Claude Code)"), self.wt)
        self.assertEqual(p.stdout.strip(), "9.9.9 (Claude Code)")

    def test_replays_a_recording_verbatim(self):
        for d, n in (("f1", "B"), ("f2", "r4")):
            src = fakes.fixture("claude", d, n + ".jsonl")
            scn = self.scenario(f"{n}.json", {"stream": src})
            shutil.rmtree(self.log, ignore_errors=True)
            p = run(["claude", "-p", "x"], self.env(scn), self.wt)
            with self.subTest(fixture=n):
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(events(p.stdout), fakes.read_stream(src))

    def test_json_schema_with_the_2020_12_meta_schema_is_refused_like_the_real_cli(self):
        argv = ["claude", "-p", "x", "--json-schema", '{"$schema":"https://json-schema.org/draft/2020-12/schema"}']
        p = run(argv, self.env("ok-judge.json"), self.wt)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, "")
        self.assertIn("--json-schema is not a valid JSON Schema", p.stderr)

    def test_ok_judge_scenario(self):
        argv = ["claude", "-p", "do it", "--output-format", "stream-json", "--verbose", "--tools", "Read,Write",
                "--model", "sonnet", "--json-schema", "{}"]
        p = run(argv, self.env("ok-judge.json"), self.wt)
        self.assertEqual(p.returncode, 0, p.stderr)
        ev = events(p.stdout)
        init, result = ev[0], ev[-1]
        # init_from_argv takes --tools; with --json-schema the real CLI 2.1.323 adds StructuredOutput (P4)
        self.assertEqual(init["tools"], ["Read", "StructuredOutput", "Write"])
        self.assertEqual(init["cwd"], self.wt)
        self.assertEqual(init["model"], "sonnet")
        self.assertEqual(result["structured_output"]["status"], "done")
        from gxengine import schema as S
        S.validate(result["structured_output"], "result-work")
        self.assertEqual(read(os.path.join(self.wt, "docs/specs/42/design.md")), "# design\n")
        calls = fakes.claude_calls(self.log)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["argv"], argv[1:])
        self.assertEqual(calls[0]["cwd"], self.wt)
        self.assertIn("PATH", calls[0]["env"])

    def test_leader_scenarios(self):
        """Stage 2 `l-*` scenarios: each names its contract example (whose fill renders the answer
        schema) and the expected engine verdict; the structured output fits that filled schema."""
        from gxengine import codes, leader
        from gxengine import schema as S
        d = os.path.join(fakes.FIXTURES, "claude", "scenarios")
        names = sorted(f for f in os.listdir(d) if f.startswith("l-"))
        self.assertGreaterEqual(len(names), 9)
        expects = {"accepted", "session-limit", *codes.LeaderFormatReason.values(), *codes.StopReason.values()}
        for name in names:
            with self.subTest(name=name):
                body = json.loads(read(os.path.join(d, name)))
                meta = body["leader"]
                self.assertIn(meta["expect"], expects)
                if meta["example"] is None:
                    self.assertNotIn("structured_output", body)
                    continue
                ex = json.loads(read(os.path.join(fakes.FIXTURES, "contracts", meta["example"] + ".example.json")))
                S.validate(body["structured_output"], S.fill_enums(S.load_schema(meta["example"]), ex["fill"]))
        # one replays end to end with the judge tool set and a filled leader schema
        ex = json.loads(read(os.path.join(fakes.FIXTURES, "contracts", "leader-answer-plan-gate.example.json")))
        sch = S.fill_enums(S.load_schema("leader-answer-plan-gate"), ex["fill"])
        sch = {k: v for k, v in sch.items() if k not in ("$schema", "$id")}
        argv = ["claude", "-p", "decide", "--tools", "Read,Write", "--model", "opus",
                "--json-schema", json.dumps(sch, separators=(",", ":"))]
        p = run(argv, self.env("l-plan-gate-plan.json"), self.wt)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = events(p.stdout)[-1]["structured_output"]
        S.validate(out, sch)
        self.assertEqual((out["answer"], out["plan"]), ("plan", {"template": "feature"}))
        self.assertEqual(leader.LEADER_ROLE, "leader")

    def test_stage3_scenarios(self):
        """Stage 3 `t-*`: each names its contract example (`role` or `leader`), whose fill renders the
        schema the structured output fits, and the engine verdict the owning session asserts."""
        from gxengine import codes
        from gxengine import schema as S
        d = os.path.join(fakes.FIXTURES, "claude", "scenarios")
        names = sorted(f for f in os.listdir(d) if f.startswith("t-"))
        role_expects = {"done", "blocked", *codes.CheckFailedReason.values(), *codes.OutputFormatReason.values(),
                        *codes.StopReason.values()}
        leader_expects = {"accepted", *codes.LeaderFormatReason.values()}
        seen = set()
        for name in names:
            with self.subTest(name=name):
                body = json.loads(read(os.path.join(d, name)))
                kind = "leader" if name.startswith("t-l-") else "role"
                meta = body[kind]
                self.assertIn(meta["expect"], leader_expects if kind == "leader" else role_expects)
                self.assertTrue(os.path.isfile(os.path.join(d, body["stream"])), body["stream"])
                ex = json.loads(read(os.path.join(fakes.FIXTURES, "contracts", meta["example"] + ".example.json")))
                S.validate(body["structured_output"], S.fill_enums(S.load_schema(meta["example"]), ex["fill"]))
                seen.add(meta["example"])
        self.assertEqual(seen, {"result-work-s3", "result-review-s3"} | (
            set(codes.STAGE3_LEADER_ANSWER_SCHEMAS.values()) - set(codes.LEADER_ANSWER_SCHEMAS.values())))

    def test_a_lone_surrogate_leaves_as_an_escape(self):
        """review-q0 D9: the stream stays valid UTF-8 and the parsed result holds the lone surrogate."""
        from gxengine import schema as S
        p = run(["claude", "-p", "x", "--tools", "Read,Write"], self.env("t-result-surrogate.json"), self.wt)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("\\ud800", p.stdout)
        out = events(p.stdout)[-1]["structured_output"]
        self.assertEqual(S.surrogate_errors(out), ["$/note: a lone surrogate (not valid Unicode text)"])

    def test_review_block_scenario_is_a_valid_review_result(self):
        p = run(["claude", "-p", "x", "--tools", "Read,Write"], self.env("review-block.json"), self.wt)
        from gxengine import schema as S
        S.validate(events(p.stdout)[-1]["structured_output"], "result-review")

    def test_scenarios_play_in_call_order(self):
        env = self.env("no-structured-output.json", "init-lists-differ.json")
        first = events(run(["claude", "-p", "a", "--tools", "Read"], env, self.wt).stdout)
        second = events(run(["claude", "-p", "b", "--tools", "Read"], env, self.wt).stdout)
        self.assertNotIn("structured_output", first[-1])
        self.assertEqual(first[0]["tools"], ["Read"])
        self.assertIn("Task", second[0]["tools"], "raw recording: the default tool set")
        third = run(["claude", "-p", "c"], env, self.wt)
        self.assertEqual(third.returncode, 97, "no scenario left → fail closed")
        self.assertEqual([c["argv"][1] for c in fakes.claude_calls(self.log)], ["a", "b", "c"])

    def test_no_scenario_fails_closed(self):
        p = run(["claude", "-p", "x"], fakes.fake_env(claude_log=self.log), self.wt)
        self.assertEqual(p.returncode, 97)

    def test_patches_drop_truncate_exit(self):
        scn = self.scenario("s.json", {"stream": fakes.fixture("claude", "f2", "r4.jsonl"),
                                       "init": {"permissionMode": "acceptEdits"}, "result": {"total_cost_usd": 1.5},
                                       "stderr": "boom\n", "exit_code": 3})
        p = run(["claude", "-p", "x"], self.env(scn), self.wt)
        ev = events(p.stdout)
        self.assertEqual(ev[0]["permissionMode"], "acceptEdits")
        self.assertEqual(ev[-1]["total_cost_usd"], 1.5)
        self.assertEqual((p.returncode, p.stderr), (3, "boom\n"))
        scn = self.scenario("d.json", {"stream": fakes.fixture("claude", "f2", "r4.jsonl"), "drop_result": True})
        shutil.rmtree(self.log)
        self.assertNotIn("result", [e["type"] for e in events(run(["claude", "-p", "x"], self.env(scn), self.wt).stdout)])
        scn = self.scenario("t.json", {"events": [{"type": "system", "subtype": "init"}, {"type": "result"}], "truncate_after": 1})
        shutil.rmtree(self.log)
        self.assertEqual(len(events(run(["claude", "-p", "x"], self.env(scn), self.wt).stdout)), 1)

    def test_actions_write_symlink_delete_and_git(self):
        repo = GitRepo.create(self.tmp, name="r", with_remote=False)
        env = self.env("developer-commits-control-file.json")
        env.update({k: v for k, v in repo.env.items() if k.startswith("GIT_")})   # never PATH
        p = run(["claude", "-p", "x"], env, repo.path)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(repo.git("log", "-1", "--format=%s"), "change role file")
        self.assertIn(".claude/agents/x.md", repo.git("show", "--name-only", "--format="))
        scn = self.scenario("a.json", {"events": [{"type": "result"}], "actions": [
            {"at": "start", "op": "write", "path": "a.txt", "content": "1"},
            {"op": "symlink", "path": "link", "target": "/etc/hosts"},
            {"op": "append", "path": "a.txt", "content": "2"},
            {"at": "end", "op": "delete", "path": "gone.txt"},
            {"op": "mkdir", "path": "d/e"}]})
        open(os.path.join(self.wt, "gone.txt"), "w").close()
        shutil.rmtree(self.log)
        run(["claude", "-p", "x"], self.env(scn), self.wt)
        self.assertEqual(read(os.path.join(self.wt, "a.txt")), "12")
        self.assertTrue(os.path.islink(os.path.join(self.wt, "link")))
        self.assertFalse(os.path.exists(os.path.join(self.wt, "gone.txt")))
        self.assertTrue(os.path.isdir(os.path.join(self.wt, "d/e")))

    def test_hang_produces_no_output_until_killed(self):
        env = self.env("no-output-hang.json")
        fakes.assert_fakes_first(env)
        proc = subprocess.Popen([fakes.FAKE_CLAUDE, "-p", "x", "--tools", "Read"], env=env, cwd=self.wt,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                                start_new_session=True)
        first = proc.stdout.readline()
        self.assertEqual(json.loads(first)["subtype"], "init")
        t0 = time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            proc.wait(timeout=1)
        os.killpg(proc.pid, 9)
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()
        self.assertLess(time.time() - t0, 10)


class FakeGh(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-gh-"))
        self.log = os.path.join(self.tmp, "log")
        self.env = fakes.fake_env(gh_fixtures=fakes.gh_fixture("issue-42.json"), gh_log=self.log)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def gh(self, *args, input=None):
        fakes.assert_fakes_first(self.env)
        return subprocess.run([fakes.FAKE_GH, *args], env=self.env, cwd=self.tmp, text=True, input=input,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=None if input is not None else subprocess.DEVNULL, timeout=20)

    def test_is_found_on_path(self):
        self.assertEqual(shutil.which("gh", path=self.env["PATH"]), os.path.join(fakes.FAKE_BIN, "gh"))

    def test_json_reply_with_glob_match(self):
        p = self.gh("issue", "view", "42", "--repo", "acme/app", "--json", "title,body,labels")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["number"], 42)
        comments = json.loads(self.gh("api", "repos/acme/app/issues/42/comments", "--paginate").stdout)
        self.assertEqual([c["author_association"] for c in comments], ["OWNER", "OWNER", "NONE"])

    def test_times_and_stdin_and_log(self):
        body = json.dumps({"body": "<!-- guild:summary -->\nnew"})
        first = self.gh("api", "-X", "PATCH", "repos/acme/app/issues/comments/900", "--input", "-", input=body)
        second = self.gh("api", "-X", "PATCH", "repos/acme/app/issues/comments/900", "--input", "-", input=body)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 1, "times: 1 — the next call falls through to the 404 rule")
        self.assertIn("404", second.stderr)
        calls = fakes.gh_calls(self.log)
        self.assertEqual([c["rule"] for c in calls], [2, 3])
        self.assertEqual(calls[0]["stdin"], body)

    def test_stage3_rules(self):
        """Stage 3 gh rules: candidates, marker search, creation, PR reviews; nothing else answers."""
        self.env = fakes.fake_env(gh_fixtures=fakes.gh_fixture("issue-42-stage3.json"), gh_log=self.log)
        q = "repos/acme/app/"
        search = ("api", q + "issues?labels=guild%3Afollowup&state=all&per_page=100", "--paginate")
        self.assertEqual([r["number"] for r in json.loads(self.gh(*search).stdout)], [77])
        made = self.gh("api", "-X", "POST", q + "issues", "--input", "-", input="{}")
        self.assertEqual(json.loads(made.stdout)["number"], 90)
        again = json.loads(self.gh(*search).stdout)
        self.assertIn("<!-- guild:followup origin=42 key=D1:0a1b2c3d -->", [r["body"] for r in again], "a resume finds the marker (TF5)")
        rev = json.loads(self.gh("api", q + "pulls/7/reviews", "--paginate").stdout)
        self.assertEqual([r["author_association"] for r in rev], ["OWNER", "NONE"])
        self.assertEqual(self.gh("api", "-X", "POST", q + "pulls", "--input", "-", input="{}").returncode, 1, "no new PR (TP1)")
        self.env = fakes.fake_env(gh_fixtures=fakes.gh_fixture("issue-42-stage3-create-fails.json"), gh_log=self.log + "2")
        self.assertEqual(self.gh("api", "-X", "POST", q + "issues", "--input", "-", input="{}").returncode, 1)

    def test_stage4_sprint_rules(self):
        """Stage 4 gh rules: tracker, marker comment, merge settings, PR states, the needs-human label."""
        self.env = fakes.fake_env(gh_fixtures=fakes.gh_fixture("sprint-700.json"), gh_log=self.log)
        q = "repos/acme/app/"
        t = json.loads(self.gh("issue", "view", "700", "--repo", "acme/app", "--json",
                               "number,title,body,labels,state,stateReason,createdAt").stdout)
        self.assertIn("<!-- guild:sprint:plan -->", t["body"])
        comments = ("api", q + "issues/700/comments", "--paginate")
        self.assertEqual(json.loads(self.gh(*comments).stdout), [], "no run marker yet")
        self.assertEqual(json.loads(self.gh("api", "-X", "POST", q + "issues/700/comments", "--input", "-", input="{}").stdout)["id"], 7001)
        self.assertIn("guild:sprint:run", json.loads(self.gh(*comments).stdout)[0]["body"])
        pulls = json.loads(self.gh("api", q + "pulls?head=acme%3Agld%2F103&state=all").stdout)
        self.assertTrue(pulls[0]["merged_at"])
        self.assertEqual(self.gh("api", q + "labels/guild%3Aneeds-human").returncode, 1)
        self.assertEqual(self.gh("api", "-X", "PUT", q + "pulls/900/merge").returncode, 1, "a merge is a human's")

    def test_unknown_call_fails_closed(self):
        p = self.gh("pr", "create", "--title", "x")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no fixture rule matches", p.stderr)
        self.assertIsNone(fakes.gh_calls(self.log)[-1]["rule"])

    def test_prefix_rule(self):
        fx = os.path.join(self.tmp, "fx.json")
        with open(fx, "w") as f:
            json.dump({"rules": [{"args": ["label", "create"], "prefix": True, "stdout": "ok\n"}]}, f)
        env = fakes.fake_env(gh_fixtures=fx, gh_log=self.log)
        p = run(["gh", "label", "create", "guild:design", "--force"], env, self.tmp)
        self.assertEqual((p.returncode, p.stdout), (0, "ok\n"))

    def test_guard_refuses_an_env_that_reaches_the_real_tools(self):
        env = dict(os.environ, PATH="/usr/bin:/bin")
        with self.assertRaises(AssertionError):
            fakes.assert_fakes_first(env)


class GitRepoHelper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gx-git-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_repo_remote_worktree_and_non_fast_forward(self):
        repo = GitRepo.create(self.tmp, files={"README.md": "hi\n", "src/a.py": "x = 1\n"})
        base = repo.head()
        self.assertEqual(repo.remote_head("main"), base)
        wt = repo.add_worktree(os.path.join(repo.tmp, ".gld-repo-42"), "gld/42")
        self.assertEqual(repo.head(cwd=wt), base)
        self.assertTrue(os.path.isfile(os.path.join(wt, ".git")), "a linked worktree has a gitfile")
        repo.write("src/b.py", "y = 2\n", cwd=wt)
        self.assertEqual(repo.status(cwd=wt), ["?? src/b.py"])
        sha = repo.commit("add b", cwd=wt)
        self.assertEqual(repo.status(cwd=wt), [])
        repo.push("gld/42", cwd=wt)
        self.assertEqual(repo.remote_head("gld/42"), sha)
        other = repo.diverge_remote("gld/42", "c.txt", "c\n")
        self.assertNotEqual(other, sha)
        repo.write("src/d.py", "z\n", cwd=wt)
        mine = repo.commit("add d", cwd=wt)
        rc, err = repo.try_push(f"{mine}:refs/heads/gld/42", cwd=wt)
        self.assertNotEqual(rc, 0)
        self.assertRegex(err, r"non-fast-forward|fetch first|rejected")
        self.assertEqual(repo.remote_head("gld/42"), other)

    def test_isolated_from_user_config(self):
        repo = GitRepo.create(self.tmp, with_remote=False)
        self.assertEqual(repo.git("config", "user.email"), "engine-test@example.invalid")
        self.assertEqual(repo.git("config", "core.hooksPath"), "/dev/null")
        self.assertEqual(repo.git("rev-parse", "--abbrev-ref", "HEAD"), "main")


if __name__ == "__main__":
    unittest.main()
