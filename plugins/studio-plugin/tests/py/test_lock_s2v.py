"""M0c interop with script2video (m0c-plan §9.3, §14): needs STUDIO_TEST_S2V (run_tests.sh --full).
Every s2v call runs isolated (temporary state folder, fake uv, mock TTS): no server, no model."""

import json
import os
import re
import subprocess
import sys
import time

import helpers
from helpers import StudioTestCase
from stdo import dirlock, locks

DRIVERS = os.path.join(helpers.HERE, "drivers")
FAKE = os.path.join(DRIVERS, "fake_s2v.py")
LOCK_DRIVER = os.path.join(DRIVERS, "lock_driver.py")
LOCK_PY = os.path.join(helpers.SCRIPTS, "lock.py")
SCRIPT = "---\ntitle: Lock test\nlang: en\n---\n\n# Intro {#intro}\n\nHello there.\n"
MANIFEST = {"version": 1, "lang": "en", "entries": {}, "sentences": {}, "env": {}}


class WithS2V(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.s2v = helpers.s2v_path(self)
        self.fixtures = os.path.join(self.s2v, "packages", "cli", "test", "fixtures", "heavy-lock")
        os.environ.update(self.s2v_environ)  # lock.py and the drivers see the same state folder
        self.lock = locks.heavy_lock_path()
        self.kids = []
        self.addCleanup(self._reap)

    def _reap(self):
        for p in self.kids:
            try:
                p.kill()
            except OSError:
                pass
            try:
                p.wait(timeout=5)
            except Exception:
                pass
            for s in (p.stdout, p.stderr):
                if s:
                    s.close()

    def node(self, *args, **kw):
        return subprocess.run(["node"] + list(args), capture_output=True, text=True, timeout=120, **kw)

    def video(self):
        repo = helpers.make_repo(self.tmp, s2v=self.s2v)
        v = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(os.path.join(v, "audio", "en"))
        with open(os.path.join(v, "script.en.md"), "w") as f:
            f.write(SCRIPT)
        with open(os.path.join(v, "audio", "en", "manifest.json"), "w") as f:
            json.dump(MANIFEST, f)
        return repo, os.path.join(v, "script.en.md")

    def s2v_cmd(self, *args):
        return ["node", helpers.s2v_main(self.s2v)] + list(args)


class Fixtures(WithS2V):
    # I1
    def test_i1_owner_and_lstart_fixtures(self):
        def at(name):
            return dirlock.read_owner(self._as_lock(name))

        self.assertEqual(at("owner-tts.json")["kind"], "tts")
        self.assertEqual(at("owner-gen.json")["kind"], "gen")
        self.assertEqual(at("owner-extra-keys.json")["version"], 2)
        self.assertEqual(at("owner-unknown-kind.json")["kind"], "render")
        self.assertIsNone(at("owner-broken.txt"))
        self.assertRegex(at("actor-owner.json")["cmd"], r"character build")
        with open(os.path.join(self.fixtures, "resident.json")) as f:
            self.assertIn("pid_start", json.load(f))
        with open(os.path.join(self.fixtures, "lstart-cases.json")) as f:
            cases = json.load(f)["cases"]
        self.assertTrue(cases)
        for c in cases:
            self.assertEqual(dirlock.same_start(c["a"], c["b"], "darwin"), c["macos"], c)
            self.assertEqual(dirlock.same_start(c["a"], c["b"], "linux"), c["linux"], c)
            self.assertEqual(dirlock.parse_lstart(c["a"]), c["epoch"], c)

    def _as_lock(self, name):
        d = os.path.join(self.tmp, "fx-" + name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(self.fixtures, name), "rb") as src, open(os.path.join(d, "owner.json"), "wb") as dst:
            dst.write(src.read())
        return d


class Race(WithS2V):
    def _race(self, n_py, n_js, loops, hold):
        barrier = os.path.join(self.tmp, "go")
        log = os.path.join(self.tmp, "race.log")
        for _ in range(n_py):
            self.kids.append(subprocess.Popen([sys.executable, "-B", os.path.join(DRIVERS, "race_py.py"),
                                               self.lock, barrier, log, str(loops), str(hold)]))
        for _ in range(n_js):
            self.kids.append(subprocess.Popen(["node", os.path.join(DRIVERS, "race_node.mjs"), self.s2v,
                                               self.lock, barrier, log, str(loops), str(hold)]))
        n = n_py + n_js
        end = time.time() + 30
        while time.time() < end:
            if os.path.exists(log):
                with open(log) as f:
                    if f.read().count("ready ") == n:
                        break
            time.sleep(0.02)
        open(barrier, "w").close()
        for p in self.kids:
            p.wait(timeout=120)
        with open(log) as f:
            return f.read().splitlines()

    # I2
    def test_i2_mixed_race_no_overlap(self):
        os.makedirs(os.path.dirname(self.lock), exist_ok=True)
        lines = self._race(4, 4, 5, 50)
        inside = 0
        got = {}
        for l in lines:
            if l.startswith("enter "):
                inside += 1
                self.assertEqual(inside, 1, "two holders at once")
                got[l.split()[1]] = got.get(l.split()[1], 0) + 1
            elif l.startswith("exit "):
                self.assertTrue(l.endswith("stillmine=True") or l.endswith("stillmine=true"), l)
                inside -= 1
        self.assertEqual(len(got), 8, got)
        self.assertTrue(all(v >= 1 for v in got.values()))
        self.assertTrue(any(k.startswith("py") for k in got) and any(k.startswith("js") for k in got))

    # I3
    def test_i3_breaking_a_dead_holder_once(self):
        for _ in range(20):
            os.makedirs(self.lock, exist_ok=True)
            with open(os.path.join(self.lock, "owner.json"), "w") as f:
                json.dump({"kind": "tts", "pid": 999999, "pid_start": "Mon Oct 19 20:06:47 2026",
                           "holder": "dead", "token": "d" * 32}, f)
            log = os.path.join(self.tmp, "race.log")
            if os.path.exists(log):
                os.remove(log)
            if os.path.exists(os.path.join(self.tmp, "go")):
                os.remove(os.path.join(self.tmp, "go"))
            self.kids = []
            lines = self._race(2, 2, 1, 1500)
            results = [l.split()[2] for l in lines if l.startswith("result ")]
            self.assertEqual(results.count("acquired"), 1, lines)
            self.assertFalse(os.path.exists(self.lock))


class WithWrapper(WithS2V):
    # I4a
    def test_i4a_wrapper_holds_and_real_s2v_gets_73(self):
        repo, script = self.video()
        ready = os.path.join(self.tmp, "ready")
        w = subprocess.Popen([sys.executable, "-B", LOCK_DRIVER, "--as", "tts", "--", "run", "--kind", "tts",
                              "--holder", "std: holding for I4a", "--",
                              sys.executable, "-B", FAKE, "--log", os.path.join(self.tmp, "c.log"),
                              "--ready", ready, "--sleep", "20"],
                             cwd=repo, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.kids.append(w)
        self.assertTrue(_wait(lambda: os.path.exists(ready)))
        out = subprocess.run(self.s2v_cmd("audio", "prune", script), cwd=repo, capture_output=True,
                             text=True, env=self.s2v_environ, timeout=120)
        self.assertEqual(out.returncode, 73, out.stderr)
        line = [l for l in out.stderr.splitlines() if l.startswith("busy (")][0]
        self.assertTrue(line.startswith("busy (lock): "))
        self.assertIn("std: holding for I4a", line)
        os.killpg(w.pid, 15)
        w.wait(timeout=20)

    # I4b
    def test_i4b_real_prune_under_the_wrapper(self):
        repo, script = self.video()
        out = subprocess.run([sys.executable, "-B", LOCK_PY, "run", "--kind", "tts", "--"] +
                             self.s2v_cmd("audio", "prune", script),
                             cwd=repo, capture_output=True, text=True, env=os.environ, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("removed 0 unused entries", out.stderr)
        self.assertFalse(os.path.exists(self.lock))

    # I5
    def test_i5_token_of_the_other_kind_is_exit_2(self):
        repo, script = self.video()
        locks.ensure_state_dir()
        r = dirlock.acquire(self.lock, {"kind": "gen", "pid": os.getpid(),
                                        "pid_start": dirlock.proc_start(os.getpid()), "holder": "t"})
        try:
            env = dict(self.s2v_environ, S2V_HEAVY_LOCK_TOKEN=r.token)
            out = subprocess.run(self.s2v_cmd("audio", "prune", script), cwd=repo, capture_output=True,
                                 text=True, env=env, timeout=120)
            self.assertEqual(out.returncode, 2, out.stderr)
        finally:
            dirlock.release(self.lock, r.token)

    # I6
    def test_i6_gitignore_same_bytes_as_s2v(self):
        for i, before in enumerate([None, "", "a", "a\n", "x\r\n", ".work\n", "/.work/\n", "a\r\n/.work\r\n"]):
            a, b = os.path.join(self.tmp, "a%d" % i), os.path.join(self.tmp, "b%d" % i)
            for d in (a, b):
                os.makedirs(d)
                if before is not None:
                    with open(os.path.join(d, ".gitignore"), "w", newline="") as f:
                        f.write(before)
            out = self.node(os.path.join(DRIVERS, "s2v_fn.mjs"), self.s2v, "gitignore", a)
            self.assertEqual(out.returncode, 0, out.stderr)
            locks.ensure_gitignore(b)
            with open(os.path.join(a, ".gitignore"), "rb") as x, open(os.path.join(b, ".gitignore"), "rb") as y:
                self.assertEqual(x.read(), y.read(), repr(before))

    # I7
    def test_i7_actor_lock_format_both_ways(self):
        repo = helpers.make_repo(self.tmp, s2v=self.s2v)
        char = os.path.join(repo, "studio", "cast", "sora", "character")
        os.makedirs(char)
        lock = locks.actor_lock_path(char)
        stop = os.path.join(self.tmp, "stop")
        h = subprocess.Popen(["node", os.path.join(DRIVERS, "s2v_fn.mjs"), self.s2v, "actor-hold", lock, stop],
                             stdout=subprocess.PIPE, text=True)
        self.kids.append(h)
        self.assertEqual(json.loads(h.stdout.readline())["status"], "acquired")
        out = subprocess.run([sys.executable, "-B", LOCK_DRIVER, "--as", "actor", "--", "actor-op", "sora", "--",
                              sys.executable, "-B", FAKE, "--log", os.path.join(self.tmp, "c.log")],
                             cwd=repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 74, out.stderr)
        self.assertIn("actor busy: node race is working on this character", out.stderr)
        open(stop, "w").close()
        h.wait(timeout=20)
        # lock.py holds; Node sees it held, and re-enters with the token
        ready = os.path.join(self.tmp, "ready")
        w = subprocess.Popen([sys.executable, "-B", LOCK_DRIVER, "--as", "actor", "--", "actor-op", "sora", "--",
                              sys.executable, "-B", FAKE, "--log", os.path.join(self.tmp, "c2.log"),
                              "--ready", ready, "--sleep", "20"],
                             cwd=repo, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.kids.append(w)
        self.assertTrue(_wait(lambda: os.path.exists(ready)))
        token = dirlock.read_owner(lock)["token"]
        held = self.node(os.path.join(DRIVERS, "s2v_fn.mjs"), self.s2v, "actor-try", lock)
        self.assertEqual(json.loads(held.stdout)["status"], "held")
        re_ = self.node(os.path.join(DRIVERS, "s2v_fn.mjs"), self.s2v, "actor-try", lock, token)
        self.assertEqual(json.loads(re_.stdout)["status"], "reentered")
        os.killpg(w.pid, 15)
        w.wait(timeout=20)

    # I8
    def test_i8_status_agrees_with_services_status(self):
        repo, _ = self.video()
        ready = os.path.join(self.tmp, "ready")
        w = subprocess.Popen([sys.executable, "-B", LOCK_DRIVER, "--as", "gen", "--", "run", "--kind", "gen", "--",
                              sys.executable, "-B", FAKE, "--log", os.path.join(self.tmp, "c.log"),
                              "--ready", ready, "--sleep", "20"],
                             cwd=repo, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.kids.append(w)
        self.assertTrue(_wait(lambda: os.path.exists(ready)))
        mine = json.loads(subprocess.run([sys.executable, "-B", LOCK_PY, "status", "--json"], cwd=repo,
                                         capture_output=True, text=True, timeout=30).stdout)["heavy"]
        theirs = json.loads(subprocess.run(self.s2v_cmd("services", "status", "--json"), cwd=repo,
                                           capture_output=True, text=True, env=self.s2v_environ,
                                           timeout=120).stdout)["lock"]
        for k in ("kind", "pid", "pid_start", "holder", "alive", "state"):
            self.assertEqual(mine[k], theirs[k], k)
        self.assertTrue(theirs["holder"].startswith("std: "))
        os.killpg(w.pid, 15)
        w.wait(timeout=20)


def _wait(cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False
