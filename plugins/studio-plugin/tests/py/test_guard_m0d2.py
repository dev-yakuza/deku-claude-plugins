"""M0d-2 §8–§11: INV5 (WebFetch/WebSearch), the scripts version check (D-M0-3), the new protected files
(transcripts, git settings), the allow-leak check over M0d-1b's must-pass and must-deny lists, warnings
without a decision, and the guard process output (allow / warning JSON)."""

import hashlib
import json
import os
import subprocess
import sys
import time

import helpers
import transcripts as TR
from stdo import SCRIPTS_VERSION, paths
from stdo.guard import judge, transcript
from test_guard_judge import JudgeCase

GUARD = os.path.join(helpers.SCRIPTS, "guard.py")


class Web(JudgeCase):
    def overlay(self, data, wrong=False):
        p = os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        raw = json.dumps(data).encode()
        with open(p, "wb") as f:
            f.write(raw)
        d = os.path.join(paths.backup_root(self.env), paths.repo_key(self.repo))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "overlay.sha"), "w") as f:
            f.write(("0" * 64 if wrong else hashlib.sha256(raw).hexdigest()) + "\n")

    def active(self, on=True):
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump({"video": "v", "langs": {"ko": {"status": "active" if on else "done"}}}, f)

    def web(self, tool, ti, agent=None):
        hook = {"tool_name": tool, "tool_input": ti, "cwd": self.repo, "session_id": "s", "transcript_path": None,
                "permission_mode": "default", "tool_use_id": "t"}
        if agent:
            hook.update({"agent_id": "a1", "agent_type": agent})
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    DATA = {"internal": {"hosts": ["wiki.corp.example"], "sources": [{"url": "https://intra.example.net/doc/1"}],
                         "terms": ["Project Kestrel", "abc"], "videos": ["onboard-x"]}}

    def test_three_rules(self):
        self.overlay(self.DATA)
        self.active()
        # (1) overlay present, work open: internal hosts and terms are denied, public ones pass
        for tool, ti in (("WebFetch", {"url": "https://wiki.corp.example/page", "prompt": "summarize"}),
                         ("WebFetch", {"url": "https://docs.wiki.corp.example/x", "prompt": "x"}),
                         ("WebFetch", {"url": "https://intra.example.net/doc/2", "prompt": "x"}),
                         ("WebFetch", {"url": "https://example.com", "prompt": "what is project kestrel"}),
                         ("WebSearch", {"query": "Project Kestrel release notes"}),
                         ("WebSearch", {"query": "onboard-x youtube"})):
            deny, _ = self.web(tool, ti)
            self.assertIsNotNone(deny, ti)
            self.assertEqual(deny.rule, "G-WEB")
            self.assertNotIn("Kestrel", deny.message())  # the term itself is not repeated
        for tool, ti in (("WebFetch", {"url": "https://example.com", "prompt": "summarize"}),
                         ("WebSearch", {"query": "YouTube Shorts title length"}),
                         ("WebSearch", {"query": "abc news"})):  # under 4 characters: not a term
            deny, ctx = self.web(tool, ti)
            self.assertIsNone(deny, ti)
            self.assertEqual(ctx.warnings, [])
        # (2) no open work: a warning only
        self.active(False)
        deny, ctx = self.web("WebSearch", {"query": "Project Kestrel"})
        self.assertIsNone(deny)
        self.assertTrue(ctx.warnings and "INV5" in ctx.warnings[0])
        # (3) overlay missing or not matching: Studio agents only, while work is open
        self.active(True)
        self.overlay(self.DATA, wrong=True)
        deny, _ = self.web("WebFetch", {"url": "https://example.com", "prompt": "x"}, agent="std-fact-checker")
        self.assertEqual(deny.rule, "G-WEB")
        deny, _ = self.web("WebFetch", {"url": "https://example.com", "prompt": "x"}, agent="studio-plugin:std-writer")
        self.assertEqual(deny.rule, "G-WEB")
        self.assertIsNone(self.web("WebFetch", {"url": "https://wiki.corp.example", "prompt": "x"})[0])
        self.assertIsNone(self.web("WebFetch", {"url": "https://example.com", "prompt": "x"},
                                   agent="general-purpose")[0])
        self.active(False)
        self.assertIsNone(self.web("WebFetch", {"url": "https://example.com", "prompt": "x"}, agent="std-writer")[0])

    def test_non_studio_repo_and_many_states(self):
        plain = helpers.make_repo(self.tmp, name="plain", harness=False)
        hook = {"tool_name": "WebSearch", "tool_input": {"query": "Project Kestrel"}, "cwd": plain, "session_id": "s",
                "transcript_path": None, "tool_use_id": "t"}
        self.assertIsNone(judge.decide(hook, self.env, snapshot_loader=self.loader)[0])
        self.overlay(self.DATA)
        for i in range(205):
            d = os.path.join(self.repo, "studio", "videos", "x%03d" % i, "work")
            os.makedirs(d)
            with open(os.path.join(d, "state.json"), "w") as f:
                json.dump({"langs": {"ko": {"status": "done"}}}, f)
        self.assertEqual(self.web("WebSearch", {"query": "Project Kestrel"})[0].rule, "G-WEB")


class Version(JudgeCase):
    def set_copy(self, v):
        p = os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "__init__.py")
        with open(p, "w") as f:
            f.write('SCRIPTS_VERSION = "%s"\n' % v if v is not None else "# nothing\n")

    def test_mismatch(self):
        mine = int(SCRIPTS_VERSION)
        cmds = ("python3 .claude/studio/scripts/state.py next v", "python3 .claude/studio/scripts/lock.py status",
                "python3 .claude/studio/scripts/check_commit.py --staged")
        for v, word in ((mine - 1, "/std update"), (mine + 1, "update the plugin"), (None, "readable")):
            self.set_copy(v)
            for c in cmds:
                d = self.assertDeny(c, "G-VERSION")
                self.assertIn(word, d.message())
            self.assertPass("git status")
            self.assertPass("ls studio")
        self.set_copy(mine)
        for c in cmds:
            self.assertPass(c)


class Protected(JudgeCase):
    def test_transcripts(self):
        proj = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "projects", "-repo")
        os.makedirs(os.path.join(proj, "memory"), exist_ok=True)
        t = os.path.join(proj, "sess-1.jsonl")
        open(t, "w").close()
        for cmd in ("echo '{}' >> %s" % t, "rm %s" % t, "cp /dev/null %s" % t, "rm -rf %s" % proj,
                    "mv %s /tmp/x" % t, "echo x > %s" % os.path.join(proj, "sess-1", "subagents", "agent-a.jsonl")):
            self.assertDeny(cmd, "G-OUT")
        d = self.decide("Write", {"file_path": t, "content": "{}"})
        self.assertEqual(d.rule, "G-OUT")
        self.assertPass("cat %s" % t)
        self.assertPass("echo x > %s" % os.path.join(proj, "memory", "note.md"))
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(proj, "memory", "n.md"), "content": "x"}))

    def test_git_config_file(self):
        cfg = os.path.join(self.repo, ".git", "config")
        self.assertDeny("echo '[core]' >> .git/config", "G-HOOKOFF")
        self.assertDeny("sed -i '' s/a/b/ .git/config", "G-HOOKOFF")
        self.assertEqual(self.decide("Edit", {"file_path": cfg, "old_string": "a", "new_string": "b"}).rule,
                         "G-HOOKOFF")
        self.assertPass("cat .git/config")
        plain = helpers.make_repo(self.tmp, name="plain", harness=False)
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(plain, ".git", "config"), "content": "x"},
                                      cwd=plain))


class AllowLeak(JudgeCase):
    """allow comes only from approval commands and Studio commits with evidence: never from M0d-1b's lists."""

    MUST_PASS = ["git status", "git diff", "git log --oneline -5", "git add src/x.ts", "git add -A",
                 'git commit -m "fix: x"', "git push", "git pull --rebase", "git checkout -b feat/x", "git switch main",
                 "git stash", "git stash pop", "git clean -n", "git clean -fd src/", "git fetch", "gh pr create --fill",
                 "gh pr view 12", "npm test", "yarn build", "pnpm lint", "make", "npx tsc --noEmit",
                 "python3 -m pytest", "node scripts/build.js", "ls -la studio", "cat studio/videos/v/work/state.json",
                 "grep -r foo studio", "find . -name '*.md'", "cp src/a.ts src/b.ts", "mkdir -p src/x",
                 "rm -rf node_modules dist", "mv a.txt b.txt", "echo x > notes.md", "python3 -c 'print(1)'",
                 "git config user.name x", "gh api repos/o/r/pulls", "python3 .claude/studio/scripts/state.py next v",
                 "python3 .claude/studio/scripts/check_commit.py --stage test v"]
    MUST_DENY = ["rm -rf studio/local", "echo x > studio/videos/v/work/state.json", "git stash -a",
                 "python3 .claude/studio/scripts/state.py approve v 1 --expect 000000000000",
                 "S2V_TTS_PORT=1 s2v tts v.md", "STUDIO_SANDBOX=1 s2v x", "HUSKY=0 git commit -m x",
                 "git -c core.hooksPath=/dev/null commit -m x", "git update-ref refs/heads/main HEAD"]

    def test_no_allow(self):
        # a valid answer exists in the transcript the whole time: it must not leak into other commands
        tpath = TR.transcript_path(self.env)
        t = TR.approval_turn(TR.T(), "승인 3f2a9c0d1e4b")
        t.write(tpath)
        transcript.STATS.opened = 0
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in self.MUST_PASS + self.MUST_DENY:
                hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                        "transcript_path": tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                        "prompt_id": t.prompt}
                deny, ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
                self.assertIsNone(ctx.allow, cmd)
                if cmd in self.MUST_DENY:
                    self.assertIsNotNone(deny, cmd)
                elif mode == "with":
                    self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
        # the transcript is opened only for the approval command (once per mode)
        self.assertEqual(transcript.STATS.opened, 2)

    def test_only_one_place_says_allow(self):
        import glob
        gdir = os.path.join(helpers.SCRIPTS, "stdo", "guard")
        hits = []
        for p in sorted(glob.glob(os.path.join(gdir, "*.py"))):
            for i, line in enumerate(open(p), 1):
                if "ctx.allow =" in line or '"allow"' in line:
                    hits.append("%s:%d" % (os.path.basename(p), i))
        self.assertEqual([h.split(":")[0] for h in hits], ["judge.py"], hits)
        body = open(GUARD).read()
        self.assertEqual(body.count('"permissionDecision": "allow"'), 1)


class Process(JudgeCase):
    """guard.py as Claude Code runs it: allow JSON, warning JSON (no decision), deny JSON."""

    def run_guard(self, hook):
        env = dict(self.env)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        out = subprocess.run([sys.executable, "-B", GUARD], input=json.dumps(hook), capture_output=True, text=True,
                             env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if out.stdout.strip() else None

    def test_outputs(self):
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        tpath = TR.transcript_path(self.env)
        t = TR.approval_turn(TR.T(), "승인 3f2a9c0d1e4b")
        t.write(tpath)
        base = {"tool_name": "Bash", "cwd": self.repo, "session_id": "sess-1", "transcript_path": tpath,
                "permission_mode": "default", "tool_use_id": "toolu_cmd1", "prompt_id": t.prompt,
                "hook_event_name": "PreToolUse"}
        start = time.monotonic()
        out = self.run_guard(dict(base, tool_input={"command": "python3 .claude/studio/scripts/state.py approve v 1 "
                                                                "--expect 3f2a9c0d1e4b"}))
        took = time.monotonic() - start
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "allow", out)
        print("\n[perf] guard.py process, approval with evidence: %.0f ms" % (took * 1000))
        self.assertIsNone(self.run_guard(dict(base, tool_input={"command": "git status"})))
        out = self.run_guard(dict(base, tool_input={"command": "rm -rf studio/local"}))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        # a warning: no decision, a system message and context for the model
        self.overlay_and_warn(base)

    def overlay_and_warn(self, base):
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump({"video": "v", "langs": {"ko": {"status": "done"}}}, f)
        p = os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json")
        raw = json.dumps({"internal": {"terms": ["Project Kestrel"]}}).encode()
        with open(p, "wb") as f:
            f.write(raw)
        d = os.path.join(paths.backup_root(self.env), paths.repo_key(self.repo))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "overlay.sha"), "w") as f:
            f.write(hashlib.sha256(raw).hexdigest())
        out = self.run_guard(dict(base, tool_name="WebSearch", tool_input={"query": "Project Kestrel"}))
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("INV5", out["systemMessage"])
        self.assertIn("INV5", out["hookSpecificOutput"]["additionalContext"])


class Perf(JudgeCase):
    def test_approval_path(self):
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        tpath = TR.transcript_path(self.env)
        t = TR.T()
        for i in range(25):
            t.user_prompt("old %d" % i)
            t.tool_use("Bash", "toolu_o%d" % i)
            t.tool_result("toolu_o%d" % i, "z" * 200000)
        TR.approval_turn(t, "승인 3f2a9c0d1e4b")
        t.write(tpath)
        cmd = "python3 .claude/studio/scripts/state.py approve v 1 --expect 3f2a9c0d1e4b"
        times, base = [], []
        for _ in range(15):
            hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                    "transcript_path": tpath, "tool_use_id": "toolu_cmd1", "prompt_id": t.prompt}
            s = time.monotonic()
            deny, ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
            times.append(time.monotonic() - s)
            self.assertTrue(ctx.allow)
            hook["tool_input"] = {"command": "git status"}
            s = time.monotonic()
            judge.decide(hook, self.env, snapshot_loader=self.loader)
            base.append(time.monotonic() - s)
        times.sort()
        base.sort()
        print("\n[perf] %s: approval with evidence (5 MB transcript) p50 %.1f ms max %.1f ms; git status p50 %.1f ms"
              % (sys.version.split()[0], times[7] * 1000, times[-1] * 1000, base[7] * 1000))
        self.assertLess(times[7], 0.25)
