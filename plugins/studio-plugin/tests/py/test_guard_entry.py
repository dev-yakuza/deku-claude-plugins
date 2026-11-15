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


class PerfNoHarness(helpers.StudioTestCase):
    """The cost the README states (m1k-plan item 6): the guard process on a Bash `git status` in a git repository
    without a harness — what every Bash call pays in a project where Studio is enabled but not set up. Temporary
    STUDIO_HOME and CLAUDE_CONFIG_DIR (StudioTestCase), CLAUDE_PLUGIN_DATA set (the bytecode cache warm after the first
    run, which is dropped), then 12 runs. The interpreter is the test's own (sys.executable), not the python3 the hooks
    find on PATH: a slower interpreter or a pyenv/asdf shim adds its own start-up. Target p50 300 ms; the test fails
    above 900 ms (3×) and only prints the max. The numbers it printed on one machine are the README's (Cost per call)."""

    RUNS = 12

    def test_git_status_without_a_harness(self):
        repo = helpers.make_repo(self.tmp, name="plain", harness=False)
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = os.path.join(self.tmp, "plugin-data")
        hook = json.dumps(helpers.hook_input("Bash", {"command": "git status"}, repo))
        times = []
        for i in range(self.RUNS + 1):
            t = time.perf_counter()
            r = subprocess.run([sys.executable, GUARD], input=hook, capture_output=True, text=True, env=env,
                               timeout=60)
            if i:
                times.append(time.perf_counter() - t)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        times.sort()
        p50 = times[len(times) // 2]
        sys.stderr.write("\n[perf] %s: guard.py on `git status` without a harness: p50 %.0f ms, max %.0f ms (%d runs)\n"
                         % (sys.version.split()[0], p50 * 1000, times[-1] * 1000, len(times)))
        self.assertLess(p50, 0.9)


def guard_p50(test, hook, env, runs):
    """p50 and max (s) of `runs` guard.py subprocesses on one hook input (a first run, warming the bytecode cache, is
    dropped); each must pass."""
    times = []
    for i in range(runs + 1):
        t = time.perf_counter()
        r = subprocess.run([sys.executable, GUARD], input=json.dumps(hook), capture_output=True, text=True, env=env,
                           timeout=60)
        if i:
            times.append(time.perf_counter() - t)
        test.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
    times.sort()
    return times[len(times) // 2], times[-1]


def write_perf_snapshots(env, files, **kw):
    import guard_base
    d = os.path.join(env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
    os.makedirs(d, exist_ok=True)
    now = time.time()
    for i in range(files):
        p = os.path.join(d, "snapshot-zsh-%d-p%03d.sh" % (1792000000000 + i, i))
        with open(p, "w") as f:
            f.write(guard_base.perf_snapshot_text(i, path=env.get("PATH", "/usr/bin:/bin"), **kw))
        os.utime(p, (now - 60 * (i + 1), now - 60 * (i + 1)))


class PerfSnapshots(helpers.StudioTestCase):
    """fix-0029 §1.6: the same `git status` call as PerfNoHarness with 13 shell snapshots in CLAUDE_CONFIG_DIR — what
    the snapshot parse adds to every Bash call (Claude Code keeps one file per recent session). Each file is
    guard_base.perf_snapshot_text: ~280 KB, ~10,500 typeset -f lines, 250 alias lines; the texts differ in one
    function-body line, the variant key is the same. The main figure is a guard.py subprocess (it never imports
    guard_base: the original snapshot.load). 0.1.4 (no source: this guard alone, the 0.0.26 guard not loaded): target
    p50 110 ms; fails above 330 ms (3×). Also prints the in-process `judge.decide` (min of 10) with the original load
    set as snapshot.load and no loader passed (production-equal).
    0.1.4 (fix-0104 §1.4d): a call that runs a snapshot function carries the text of every snapshot function — two
    more cases in a Studio repository, each against `git status` there: a 400-function snapshot (the same 13 files
    plus a function that changes nothing) and `nvm_normalize_version 1; git status`, printed, failing above that
    `git status` + 50 ms; four distinct ~470 KB variants (~1.9 MB of function text, no Studio term) and one command
    with 8 snapshot-function calls (the text built and searched once), failing above + 150 ms, under CPU_BUDGET and
    never G-LIMIT."""

    RUNS = 12
    FILES = 13

    def test_git_status_with_13_snapshots(self):
        import guard_base
        from stdo.guard import snapshot as snapmod
        repo = helpers.make_repo(self.tmp, name="plain", harness=False)
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = os.path.join(self.tmp, "plugin-data")
        d = os.path.join(env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d)
        now = time.time()
        for i in range(self.FILES):
            p = os.path.join(d, "snapshot-zsh-%d-p%03d.sh" % (1792000000000 + i, i))
            with open(p, "w") as f:
                f.write(guard_base.perf_snapshot_text(i, path=env.get("PATH", "/usr/bin:/bin")))
            os.utime(p, (now - 60 * (i + 1), now - 60 * (i + 1)))
        hook = helpers.hook_input("Bash", {"command": "git status"}, repo)
        times = []
        for i in range(self.RUNS + 1):
            t = time.perf_counter()
            r = subprocess.run([sys.executable, GUARD], input=json.dumps(hook), capture_output=True, text=True,
                               env=env, timeout=60)
            if i:
                times.append(time.perf_counter() - t)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        times.sort()
        p50 = times[len(times) // 2]
        # in process: the original load as snapshot.load (not the tests' patch, which also loads the 0.0.26 reading
        # and the 0.1.0 reference), no loader passed — `snapshot_loader=` would leave the 0.0.26 guard without one
        patch = snapmod.load
        snapmod.load = guard_base._load_both.__defaults__[-1]
        try:
            snap, _notes = snapmod.load(env)
            self.assertEqual((len(snap.variants), snap.total), (1, self.FILES))
            inproc = []
            for _ in range(11):
                t = time.perf_counter()
                deny, _ctx = judge.decide(hook, env)
                inproc.append(time.perf_counter() - t)
                self.assertIsNone(deny)
        finally:
            snapmod.load = patch
        sys.stderr.write("\n[perf] %s: guard.py on `git status` with %d shell snapshots: p50 %.0f ms, max %.0f ms "
                         "(%d runs); in process judge.decide min %.0f ms\n"
                         % (sys.version.split()[0], self.FILES, p50 * 1000, times[-1] * 1000, len(times),
                            min(inproc[1:]) * 1000))
        self.assertLess(p50, 0.33)

    def studio_env(self, name):
        repo = helpers.make_repo(self.tmp, name=name, harness=True)
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = os.path.join(self.tmp, "plugin-data")
        env["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, name + "-cfg")
        return repo, env

    def test_snapshot_function_call(self):
        nvm = "nvm_normalize_version () {\n\tlocal v=\"${1#v}\"\n\tprint -r -- \"v${v}\"\n}\n"
        repo, env = self.studio_env("studio400")
        write_perf_snapshots(env, self.FILES, extra=nvm)
        base = guard_p50(self, helpers.hook_input("Bash", {"command": "git status"}, repo), env, self.RUNS)
        call = guard_p50(self, helpers.hook_input("Bash", {"command": "nvm_normalize_version 1; git status"}, repo),
                         env, self.RUNS)
        sys.stderr.write("\n[perf] %s: guard.py in a Studio repository, 13 snapshots of 400 functions: `git status` "
                         "p50 %.0f ms, `nvm_normalize_version 1; git status` p50 %.0f ms (+%.0f ms)\n"
                         % (sys.version.split()[0], base[0] * 1000, call[0] * 1000, (call[0] - base[0]) * 1000))
        self.assertLess(call[0], base[0] + 0.05)

    def test_many_function_calls_in_a_large_snapshot(self):
        repo, env = self.studio_env("studio19")
        d = os.path.join(env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d)
        import guard_base
        for v in range(4):  # four distinct variants (other function names): ~1.9 MB of function text in all
            funcs = "".join(guard_base.PERF_FUNC.replace("f_%(n)d", "v%d_%%(n)d" % v) % {"n": n} for n in range(700))
            funcs += "".join("q%d_%d () {\n\tprint -r -- \"q %d\"\n}\n" % (v, k, k) for k in range(8))
            with open(os.path.join(d, "snapshot-zsh-%d-big%d.sh" % (1792000000000 + v, v)), "w") as f:
                f.write(guard_base.snapshot_text(functions=funcs, path=env.get("PATH", "/usr/bin:/bin")))
        from stdo.guard import snapshot as snapmod
        snap = guard_base._load_both.__defaults__[-1](env)[0]
        self.assertEqual(len(snap.variants), 4)
        text = snap.all_function_text()
        self.assertGreater(len(text), 1800 * 1024)
        self.assertNotIn("studio", text)
        cmd = "; ".join("q%d_%d" % (k % 4, k) for k in range(8)) + "; git status"
        base = guard_p50(self, helpers.hook_input("Bash", {"command": "git status"}, repo), env, 6)
        call = guard_p50(self, helpers.hook_input("Bash", {"command": cmd}, repo), env, 6)
        patch = snapmod.load
        snapmod.load = guard_base._load_both.__defaults__[-1]
        try:
            hook = helpers.hook_input("Bash", {"command": cmd}, repo)
            c0 = time.process_time()
            deny, ctx = judge.decide(hook, env)
            cpu = time.process_time() - c0
        finally:
            snapmod.load = patch
        self.assertIsNone(deny, deny and deny.message())
        sys.stderr.write("\n[perf] %s: guard.py in a Studio repository, 4 variants (%.1f MB of function text): `git "
                         "status` p50 %.0f ms, 8 function calls p50 %.0f ms (+%.0f ms); in process %.0f ms CPU\n"
                         % (sys.version.split()[0], len(text) / 1048576.0, base[0] * 1000, call[0] * 1000,
                            (call[0] - base[0]) * 1000, cpu * 1000))
        self.assertLess(call[0], base[0] + 0.15)
        from stdo.guard import limits
        self.assertLess(cpu, limits.CPU_BUDGET)


class PerfSourced(helpers.StudioTestCase):
    """0.1.4: a call with a `source` is judged by both guards (the 0.0.26 one parses the snapshots again) and walks
    the file (a real venv activate): `source .venv/bin/activate; git status` with the 13 PerfSnapshots files, a
    guard.py subprocess — printed, fails above 480 ms."""

    def test_sourced_git_status(self):
        repo = helpers.make_repo(self.tmp, name="plain", harness=False)
        with open(os.path.join(helpers.PLUGIN, "tests", "fixtures", "sourced", "activate-3.12")) as f:
            text = f.read().replace("__VENV__", os.path.join(repo, ".venv"))
        os.makedirs(os.path.join(repo, ".venv", "bin"))
        with open(os.path.join(repo, ".venv", "bin", "activate"), "w") as f:
            f.write(text)
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = os.path.join(self.tmp, "plugin-data")
        write_perf_snapshots(env, PerfSnapshots.FILES)
        p50, mx = guard_p50(self, helpers.hook_input("Bash", {"command": "source .venv/bin/activate; git status"},
                                                     repo), env, PerfSnapshots.RUNS)
        sys.stderr.write("\n[perf] %s: guard.py on `source .venv/bin/activate; git status` with %d shell snapshots: "
                         "p50 %.0f ms, max %.0f ms\n" % (sys.version.split()[0], PerfSnapshots.FILES, p50 * 1000,
                                                       mx * 1000))
        self.assertLess(p50, 0.48)
