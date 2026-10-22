"""M0d-1b entry point, hook registration, guard-ran record and performance (m0d1b-plan v2 §2, §8, §9, §10.4)."""

import json
import os
import subprocess
import sys
import threading
import time

import helpers
from test_guard_judge import JudgeCase
from stdo.guard import judge, ranlog

GUARD = os.path.join(helpers.SCRIPTS, "guard.py")
HOOKS = os.path.join(helpers.PLUGIN, "hooks", "hooks.json")


class Entry(JudgeCase):
    def run_guard(self, hook, extra_env=None, stdin=None):
        env = dict(self.env)
        env.update(extra_env or {})
        data = stdin if stdin is not None else json.dumps(hook)
        return subprocess.run([sys.executable, GUARD], input=data, capture_output=True, text=True, env=env,
                              timeout=60)

    def test_pass_is_silent(self):
        r = self.run_guard(self.hook("Bash", {"command": "git status"}))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_deny_json(self):
        r = self.run_guard(self.hook("Bash", {"command": "rm -rf studio/local"}))
        self.assertEqual(r.returncode, 0)
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1)
        out = json.loads(lines[0])
        hs = out["hookSpecificOutput"]
        self.assertEqual((hs["hookEventName"], hs["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertTrue(hs["permissionDecisionReason"].startswith("Studio guard [G-DEL]"))
        for word in ('"allow"', '"ask"', '"defer"'):
            self.assertNotIn(word, r.stdout)

    def test_failures_deny(self):
        r = self.run_guard(self.hook("Bash", {"command": "ls"}), extra_env={"STUDIO_TEST_GUARD_RAISE": "1"})
        out = json.loads(r.stdout)
        self.assertIn("G-ERR", out["hookSpecificOutput"]["permissionDecisionReason"])
        r = self.run_guard(None, stdin="{not json")
        self.assertIn("G-ERR", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"])

    def test_stdout_failure_exits_2(self):
        env = dict(self.env, STUDIO_TEST_GUARD_RAISE="1")
        p = subprocess.Popen([sys.executable, GUARD], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env)
        p.stdout.close()
        p.stdin.write(b"{}")
        p.stdin.close()
        rc = p.wait(timeout=30)
        self.assertEqual(rc, 2)

    def test_large_input_denied(self):
        import stdo  # noqa: F401
        src = open(GUARD).read()
        self.assertIn("MAX_INPUT = 64 * 1024 * 1024", src)

    def test_other_tools_pass(self):
        for tool, ti in (("TodoWrite", {"todos": []}), ("Read", {"file_path": "studio/videos/v/work/state.json"}),
                         ("Agent", {"prompt": "rm -rf studio"})):
            r = self.run_guard(self.hook(tool, ti))
            self.assertEqual(r.stdout, "", tool)


class HooksJson(JudgeCase):
    def test_registration(self):
        data = json.load(open(HOOKS))
        pre = data["hooks"]["PreToolUse"]
        self.assertEqual(len(pre), 1)
        # M0d-2 adds WebFetch and WebSearch (INV5)
        self.assertEqual(pre[0]["matcher"], "^(Bash|Write|Edit|MultiEdit|NotebookEdit|WebFetch|WebSearch|mcp__.*)$")
        h = pre[0]["hooks"][0]
        self.assertEqual((h["type"], h["timeout"], h["onFailure"]), ("command", 20, "block"))
        self.assertEqual(h["command"], 'python3 "${CLAUDE_PLUGIN_ROOT}/skills/std/scripts/guard.py"')
        pj = json.load(open(os.path.join(helpers.PLUGIN, ".claude-plugin", "plugin.json")))
        self.assertNotIn("hooks", pj)
        import re
        rx = re.compile(pre[0]["matcher"])
        for t in ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "mcp__fs__write"):
            self.assertTrue(rx.search(t), t)
        for t in ("TodoWrite", "Read", "Agent", "AskUserQuestion", "BashOutput", "WebFetchX"):
            self.assertFalse(rx.search(t), t)


class RanLog(JudgeCase):
    def local(self):
        return os.path.join(self.repo, ".claude", "studio", "local")

    def test_written_after_decisions(self):
        os.makedirs(self.local(), exist_ok=True)
        r = Entry.run_guard(self, self.hook("Bash", {"command": "rm -rf studio/local"}))
        self.assertIn("deny", r.stdout)
        data = json.load(open(os.path.join(self.local(), "guard-ran.json")))
        self.assertIn("sess-1", data["sessions"])
        Entry.run_guard(self, self.hook("Write", {"file_path": "src/a.ts", "content": "x"}))
        self.assertIn("sess-1", json.load(open(os.path.join(self.local(), "guard-ran.json")))["sessions"])

    def test_local_created_only_with_exclude_block(self):
        import shutil
        shutil.rmtree(self.local())  # a fresh clone: no machine.json yet (M1a), so no local/ folder either
        Entry.run_guard(self, self.hook("Bash", {"command": "ls"}))
        self.assertFalse(os.path.exists(self.local()))
        common = helpers.git(self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        os.makedirs(os.path.join(common, "info"), exist_ok=True)
        with open(os.path.join(common, "info", "exclude"), "a") as f:
            f.write("# >>> studio\n/studio/local/\n# <<< studio\n")
        Entry.run_guard(self, self.hook("Bash", {"command": "ls"}))
        self.assertTrue(os.path.exists(os.path.join(self.local(), "guard-ran.json")))

    def test_marker_only_repo_not_written(self):
        r3 = helpers.make_repo(self.tmp, name="m", harness=False, marker=True, local=True)
        Entry.run_guard(self, self.hook("Bash", {"command": "ls"}, cwd=r3))
        self.assertFalse(os.path.exists(os.path.join(r3, ".claude", "studio", "local", "guard-ran.json")))

    def test_prune_broken_and_concurrent(self):
        os.makedirs(self.local(), exist_ok=True)
        p = os.path.join(self.local(), "guard-ran.json")
        with open(p, "w") as f:
            json.dump({"schema": 1, "sessions": {"old": "2020-01-01T00:00:00Z", "recent": "2026-10-19T00:00:00Z"}}, f)
        ranlog.record(self.repo, "s-new", True, now="2026-10-20T00:00:00Z")
        data = json.load(open(p))["sessions"]
        self.assertEqual(sorted(data), ["recent", "s-new"])
        with open(p, "w") as f:
            f.write("{broken")
        self.assertTrue(ranlog.record(self.repo, "s2", True))
        threads = [threading.Thread(target=ranlog.record, args=(self.repo, "t%d" % i, True)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        procs = [subprocess.Popen([sys.executable, "-c", "import sys; sys.path.insert(0, %r); "
                                   "from stdo.guard import ranlog; ranlog.record(%r, 'p%d', True)"
                                   % (helpers.SCRIPTS, self.repo, i)]) for i in range(6)]
        for pr in procs:
            pr.wait(timeout=30)
        data = json.load(open(p))["sessions"]
        self.assertIn("s2", data)
        self.assertGreaterEqual(len([k for k in data if k.startswith(("t", "p"))]), 12)


class Perf(JudgeCase):
    def test_latency(self):
        cmds = ["git status", "ls -la studio", "rm -rf node_modules", "cat studio/videos/v/work/state.json",
                "python3 .claude/studio/scripts/state.py next v", "echo x > notes.md", "npm test", "g st",
                "grep -r foo src", "s2v --version", "find . -name '*.md'", "cp src/a.ts src/b.ts",
                "python3 -c 'print(1)'", "rm -rf studio/local", "echo x > studio/videos/v/work/state.json"] * 2
        times = []
        for c in cmds:
            t = time.perf_counter()
            judge.decide(self.hook("Bash", {"command": c}), self.env, snapshot_loader=self.loader)
            times.append(time.perf_counter() - t)
        times.sort()
        p50, p99 = times[len(times) // 2], times[-1]
        sys.stderr.write("\n[perf] in-process decide p50 %.1f ms, max %.1f ms\n" % (p50 * 1000, p99 * 1000))
        self.assertLess(p99, 1.0)
        t = time.perf_counter()
        for _ in range(5):
            Entry.run_guard(self, self.hook("Bash", {"command": "git status"}))
        per = (time.perf_counter() - t) / 5
        sys.stderr.write("[perf] guard.py process (no snapshot files) %.1f ms per call\n" % (per * 1000))
        self.assertLess(per, 2.0)


class PerfRealistic(JudgeCase):
    def test_process_latency_with_snapshots(self):
        from guard_base import snapshot_text
        funcs = "".join("f%d () {\n\techo %d\n\tif [[ -n $x ]]\n\tthen\n\t\tcommand ls -la ${1+\"$@\"} | head\n\tfi\n}\n"
                        % (i, i) for i in range(3000))
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        aliases = [("al%d" % i, "'git log -%d'" % i) for i in range(245)] + [("g", "git")]
        for i in range(5):
            with open(os.path.join(d, "snapshot-zsh-%d-p.sh" % i), "w") as f:
                f.write(snapshot_text(functions=funcs, aliases=aliases[:240 + i], path=self.env["PATH"]))
        self.env["CLAUDE_PLUGIN_DATA"] = os.path.join(self.tmp, "plugin-data")
        times = {}
        for cmd in ("git status", "rm -rf studio/local", "g st"):
            ts = []
            for _ in range(7):
                t = time.perf_counter()
                Entry.run_guard(self, self.hook("Bash", {"command": cmd}))
                ts.append(time.perf_counter() - t)
            ts.sort()
            times[cmd] = (ts[len(ts) // 2], ts[-1])
        t = time.perf_counter()
        for _ in range(5):
            Entry.run_guard(self, self.hook("Write", {"file_path": "src/a.ts", "content": "x"}))
        w = (time.perf_counter() - t) / 5
        sys.stderr.write("\n[perf] %s: Bash %s; Write %.0f ms\n" % (
            sys.version.split()[0], ", ".join("%s p50 %.0f ms max %.0f ms" % (c, a * 1000, b * 1000)
                                              for c, (a, b) in times.items()), w * 1000))
        for c, (p50, mx) in times.items():
            self.assertLess(mx, 1.0, c)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "plugin-data", "pycache")))
        found = [d for d, _s, _f in os.walk(helpers.PLUGIN) if d.endswith("__pycache__")]
        self.assertEqual(found, [])
