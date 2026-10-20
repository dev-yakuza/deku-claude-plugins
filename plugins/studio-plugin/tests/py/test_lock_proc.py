"""M0c process tests (m0c-plan §9.2): lock.py with a fake s2v child, signals, the watcher."""

import glob
import json
import os
import signal
import subprocess
import sys
import time

import helpers
from helpers import StudioTestCase
from stdo import dirlock, locks

DRIVERS = os.path.join(helpers.HERE, "drivers")
DRIVER = os.path.join(DRIVERS, "lock_driver.py")
FAKE = os.path.join(DRIVERS, "fake_s2v.py")
LOCK_PY = os.path.join(helpers.SCRIPTS, "lock.py")


def wait_for(cond, timeout=15.0, step=0.02):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie child of ours still answers: reap check through ps
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")


class LockProc(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.repo = helpers.make_repo(self.tmp)
        self.log = os.path.join(self.tmp, "child.log")
        self.ready = os.path.join(self.tmp, "child.ready")
        self.lock = locks.heavy_lock_path()
        self.procs = []  # wrappers and outer groups: each leads or joins its own group
        self.others = []  # plain processes in the test's own group: killed one by one
        self.addCleanup(self._kill_all)

    def _kill_all(self):
        mine = os.getpgid(0)
        for p in self.procs:
            try:
                g = os.getpgid(p.pid)
                if g != mine:
                    os.killpg(g, signal.SIGKILL)
            except OSError:
                pass
        for p in self.procs + self.others:
            try:
                p.kill()
            except OSError:
                pass
            try:
                p.wait(timeout=5)
            except Exception:
                pass
        for p in self.procs:
            for stream in (p.stdout, p.stderr):
                if stream:
                    stream.close()

    def fake(self, *extra):
        return [sys.executable, "-B", FAKE, "--log", self.log, "--ready", self.ready] + list(extra)

    def start(self, lock_args, as_kind="tts", hook=None, env=None, preexec_fn=None, new_session=True,
              cwd=None, drop_got=False):
        cmd = [sys.executable, "-B", DRIVER, "--as", as_kind]
        if hook:
            cmd += ["--hook", hook]
        if drop_got:
            cmd += ["--drop-got"]
        p = subprocess.Popen(cmd + ["--"] + lock_args, cwd=cwd or self.repo, env=env or dict(os.environ),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                             start_new_session=new_session and preexec_fn is None, preexec_fn=preexec_fn)
        self.procs.append(p)
        return p

    def run_lock(self, *a, **kw):
        p = self.start(*a, **kw)
        out, err = p.communicate(timeout=60)
        return p.returncode, out.decode(), err.decode()

    def events(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(l) for l in f if l.strip()]

    def signals(self):
        return [e["sig"] for e in self.events() if e["event"] == "signal"]

    def child_ready(self):
        self.assertTrue(wait_for(lambda: os.path.exists(self.ready)), "child never started")
        return [e for e in self.events() if e["event"] == "start"][0]

    def live_owner(self, lock, **fields):
        s = subprocess.Popen(["sleep", "60"])
        self.others.append(s)
        d = {"pid": s.pid, "pid_start": dirlock.proc_start(s.pid), "token": "f" * 32}
        d.update(fields)
        os.makedirs(lock, exist_ok=True)
        with open(os.path.join(lock, "owner.json"), "w") as f:
            json.dump(d, f)
        return s

    # P1
    def test_p1_normal_exit_codes_tokens_and_release(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "0.5", "--exit", "3"))
        start = self.child_ready()
        owner = dirlock.read_owner(self.lock)
        self.assertEqual(start["heavy"], owner["token"])
        self.assertIsNone(start["actor"])
        self.assertEqual(start["no_open"], "1")
        self.assertEqual(owner["kind"], "tts")
        self.assertTrue(owner["holder"].startswith("std: "))
        self.assertEqual(owner["pid"], p.pid)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 3)
        self.assertFalse(os.path.exists(self.lock))
        self.assertEqual(self.run_lock(["run", "--kind", "tts", "--"] + self.fake())[0], 0)

    # P2
    def test_p2_one_sigint_reaches_the_child_once(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30"))
        self.child_ready()
        os.kill(p.pid, signal.SIGINT)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 130)
        self.assertEqual(self.signals(), [signal.SIGINT])
        self.assertFalse(os.path.exists(self.lock))

    # P3
    def test_p3_signal_then_nonzero_child_is_128_plus_n(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30", "--on-signal", "exit:1"))
        self.child_ready()
        os.kill(p.pid, signal.SIGTERM)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 143)

    # P4
    def test_p4_second_signal_of_another_kind_forces(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30", "--on-signal", "ignore"))
        start = self.child_ready()
        os.kill(p.pid, signal.SIGTERM)
        self.assertTrue(wait_for(lambda: signal.SIGTERM in self.signals()))
        os.kill(p.pid, signal.SIGINT)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertFalse(alive(start["pid"]))
        self.assertNotIn("exit", [e["event"] for e in self.events()])
        self.assertFalse(os.path.exists(self.lock))

    # P5
    def test_p5_wrapper_sigkill_ends_the_child(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30"))
        start = self.child_ready()
        os.kill(p.pid, signal.SIGKILL)
        p.wait(timeout=5)
        self.assertTrue(wait_for(lambda: not alive(start["pid"]), timeout=3), "child outlived the wrapper")
        self.assertTrue(os.path.exists(self.lock))  # dead owner: broken by the next taker
        self.assertEqual(self.run_lock(["run", "--kind", "tts", "--"] + self.fake())[0], 0)

    def _outer_group(self):
        sleeper = subprocess.Popen([sys.executable, "-B", "-c",
                                    "import signal,time; [signal.signal(s, signal.SIG_IGN) for s in (1,2,15)]; time.sleep(60)"],
                                   preexec_fn=os.setpgrp)  # own group, the test's session
        self.procs.append(sleeper)
        return sleeper

    # P6
    def test_p6_wrapper_sigkill_leaves_the_outer_group_alone(self):
        sleeper = self._outer_group()
        g = sleeper.pid
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30"),
                       preexec_fn=lambda: os.setpgid(0, g))
        start = self.child_ready()
        self.assertEqual(os.getpgid(p.pid), g)
        os.kill(p.pid, signal.SIGKILL)
        p.wait(timeout=5)
        self.assertTrue(wait_for(lambda: not alive(start["pid"]), timeout=3))
        self.assertTrue(alive(sleeper.pid))

    # P7
    def test_p7_outer_group_sigint_reaches_the_child_once(self):
        sleeper = self._outer_group()
        g = sleeper.pid
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30"),
                       preexec_fn=lambda: os.setpgid(0, g))
        self.child_ready()
        os.killpg(g, signal.SIGINT)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 130)
        self.assertEqual(self.signals(), [signal.SIGINT])

    # P8
    def test_p8_watcher_survives_a_group_sigterm(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30"))
        start = self.child_ready()
        os.killpg(start["pgid"], signal.SIGTERM)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 143)  # the child's own code, reported by the watcher
        self.assertEqual(self.signals(), [signal.SIGTERM])
        self.assertNotIn("the watcher ended unexpectedly", p.stderr.read().decode())

    # P9
    def test_p9_watcher_killed_lock_kept_until_the_group_is_empty(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "2"))
        start = self.child_ready()
        os.kill(start["pgid"], signal.SIGKILL)  # the watcher only (it leads the group)
        time.sleep(0.5)
        self.assertTrue(alive(start["pid"]))
        self.assertTrue(os.path.exists(self.lock))
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 1)
        self.assertIn("the watcher ended unexpectedly", p.stderr.read().decode())
        self.assertFalse(os.path.exists(self.lock))

    def test_p9_watcher_killed_then_two_signals_force(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30", "--on-signal", "ignore"))
        start = self.child_ready()
        os.kill(start["pgid"], signal.SIGKILL)
        time.sleep(0.3)
        os.kill(p.pid, signal.SIGTERM)
        time.sleep(0.3)
        self.assertTrue(alive(start["pid"]))
        os.kill(p.pid, signal.SIGHUP)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertFalse(alive(start["pid"]))
        self.assertFalse(os.path.exists(self.lock))

    # P10
    def test_p10_lock_held_until_a_grandchild_ends(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--grandchild", "2"))
        self.assertTrue(wait_for(lambda: "exit" in [e["event"] for e in self.events()]))
        grand = [e for e in self.events() if e["event"] == "grandchild"][0]["pid"]
        time.sleep(0.5)
        self.assertTrue(alive(grand))
        self.assertTrue(os.path.exists(self.lock))
        self.assertIsNone(p.poll())
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 0)
        self.assertFalse(os.path.exists(self.lock))

    # P11
    def test_p11_child_stdin_fds_and_session(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake())
        start = self.child_ready()
        p.wait(timeout=20)
        self.assertEqual(start["stdin"], "")
        self.assertTrue(set(start["fds"]) <= {0, 1, 2, 3}, start["fds"])  # 3: the listing itself
        self.assertEqual(start["sid"], start["pgid"])
        self.assertNotEqual(start["sid"], os.getsid(0))
        self.assertNotEqual(start["sid"], p.pid)

    # P12
    def test_p12_busy_machine_is_73_without_the_token(self):
        s = self.live_owner(self.lock, kind="gen", holder="someone else")
        code, _, err = self.run_lock(["run", "--kind", "tts", "--"] + self.fake())
        self.assertEqual(code, 73)
        line = [l for l in err.splitlines() if l.startswith("busy (")][0]
        self.assertTrue(line.startswith("busy (lock): "))
        self.assertIn("someone else", line)
        self.assertIn(str(s.pid), line)
        self.assertNotIn("f" * 32, err)
        self.assertEqual(self.events(), [])

    # P13
    def test_p13_breaking_is_73_and_74_for_actors(self):
        os.makedirs(self.lock)
        with open(os.path.join(self.lock, "owner.json"), "w") as f:
            json.dump({"pid": 999999, "pid_start": "x", "token": "e" * 32}, f)
        os.mkdir(self.lock + ".break")
        code, _, err = self.run_lock(["run", "--kind", "tts", "--"] + self.fake())
        self.assertEqual(code, 73)
        self.assertIn("busy (breaking): ", err)
        char = os.path.join(self.repo, "studio", "cast", "sora", "character")
        os.makedirs(char)
        al = locks.actor_lock_path(char)
        os.makedirs(al)
        with open(os.path.join(al, "owner.json"), "w") as f:
            json.dump({"pid": 999999, "pid_start": "x", "cmd": "c", "token": "e" * 32}, f)
        os.mkdir(al + ".break")
        code, _, err = self.run_lock(["actor-op", "sora", "--"] + self.fake(), as_kind="actor")
        self.assertEqual(code, 74)
        self.assertIn("actor busy: another s2v is clearing a stale lock of %s; try again"
                      % os.path.realpath(char), err)

    def _actors(self, *ids):
        dirs = []
        for i in ids:
            d = os.path.join(self.repo, "studio", "cast", i, "character")
            os.makedirs(d)
            dirs.append(d)
        return dirs

    # P14
    def test_p14_actor_op_all_or_nothing(self):
        a, b = self._actors("aa", "bb")
        s = self.live_owner(locks.actor_lock_path(b), cmd="s2v character build")
        code, _, err = self.run_lock(["actor-op", "aa", "bb", "--"] + self.fake(), as_kind="actor")
        self.assertEqual(code, 74)
        self.assertIn("actor busy: s2v character build is working on this character (pid %d)" % s.pid, err)
        self.assertFalse(os.path.exists(locks.actor_lock_path(a)))
        with open(os.path.join(a, ".gitignore")) as f:
            self.assertEqual(f.read(), ".work/\n")
        self.assertEqual(self.events(), [])

    # P15
    def test_p15_actor_op_one_token_and_dedup(self):
        a, b = self._actors("aa", "bb")
        p = self.start(["actor-op", "aa", "bb", "aa", "--"] + self.fake("--sleep", "0.5"), as_kind="actor")
        start = self.child_ready()
        ta = dirlock.read_owner(locks.actor_lock_path(a))
        tb = dirlock.read_owner(locks.actor_lock_path(b))
        self.assertEqual(ta["token"], tb["token"])
        self.assertEqual(start["actor"], ta["token"])
        self.assertIsNone(start["heavy"])
        self.assertTrue(ta["cmd"].startswith("std actor-op: "))
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 0)
        self.assertFalse(os.path.exists(locks.actor_lock_path(a)))
        self.assertFalse(os.path.exists(locks.actor_lock_path(b)))

    # P16
    def test_p16_usage_errors_take_no_lock(self):
        fake = self.fake()
        env = dict(os.environ, S2V_HEAVY_LOCK_TOKEN="0" * 32)
        self.assertEqual(self.run_lock(["run", "--kind", "tts", "--"] + fake, env=env)[0], 2)
        env = dict(os.environ, S2V_ACTOR_LOCK_TOKEN="0" * 32)
        self.assertEqual(self.run_lock(["run", "--kind", "tts", "--"] + fake, env=env)[0], 2)
        env = dict(os.environ, S2V_STATE_DIR="relative/state")
        self.assertEqual(self.run_lock(["run", "--kind", "tts", "--"] + fake, env=env)[0], 2)
        self.assertEqual(self.run_lock(["run", "--kind", "tts", "--"] + fake, as_kind="gen")[0], 2)
        self.assertEqual(self.run_lock(["run", "--kind", "tts"] + fake)[0], 2)
        self.assertEqual(self.run_lock(["run", "--kind", "big", "--"] + fake)[0], 2)
        bare = helpers.make_repo(self.tmp, name="bare", harness=False)
        self.assertEqual(self.run_lock(["run", "--kind", "tts", "--"] + fake, cwd=bare)[0], 2)
        # the real lock.py (no injection): a fake child is not an s2v call
        out = subprocess.run([sys.executable, "-B", LOCK_PY, "run", "--kind", "tts", "--"] + fake,
                             cwd=self.repo, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 2)
        self.assertIn("not an s2v command", out.stderr)
        self.assertFalse(os.path.exists(self.lock))
        self.assertEqual(self.events(), [])

    # P17
    def test_p17_signal_before_the_watcher_starts(self):
        code, _, _ = self.run_lock(["run", "--kind", "tts", "--"] + self.fake(), hook="after-acquire")
        self.assertEqual(code, 143)
        self.assertEqual(self.events(), [])
        self.assertFalse(os.path.exists(self.lock))

    def test_p17_signal_before_ready_is_forwarded_after(self):
        code, _, err = self.run_lock(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30"), hook="after-spawn")
        self.assertEqual(code, 143)
        # held until ready: the watcher had its handlers, survived the signal and reported the child
        status = [l for l in err.splitlines() if l.startswith("driver-status: ")][0].split(": ", 1)[1].split("|")
        self.assertEqual(status[0], "ready")
        ends = [x for x in status if not x.startswith("got ")]
        self.assertIn(ends[-1], ("signal 15", "exit 143"))
        self.assertNotIn("exit", [e["event"] for e in self.events()])
        self.assertFalse(os.path.exists(self.lock))

    # P18
    def test_p18_status_json(self):
        def status(*extra):
            out = subprocess.run([sys.executable, "-B", LOCK_PY, "status", "--json"] + list(extra),
                                 cwd=self.repo, capture_output=True, text=True, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertNotIn("f" * 32, out.stdout)
            return json.loads(out.stdout)

        self.assertIsNone(status()["heavy"])
        s = self.live_owner(self.lock, kind="tts", holder="h1")
        h = status()["heavy"]
        self.assertEqual((h["state"], h["kind"], h["holder"], h["pid"], h["alive"]), ("held", "tts", "h1", s.pid, True))
        with open(os.path.join(self.lock, "owner.json"), "w") as f:
            json.dump({"pid": 999999, "pid_start": "x", "token": "f" * 32}, f)
        self.assertEqual(status()["heavy"]["state"], "stale")
        with open(os.path.join(self.lock, "owner.json"), "w") as f:
            f.write("{")
        self.assertEqual(status()["heavy"]["state"], "invalid")
        (a,) = self._actors("aa")
        self.assertEqual(status("--actor", "aa")["actors"], {"aa": None})
        s2 = self.live_owner(locks.actor_lock_path(a), cmd="std actor-op: x")
        r = status("--actor", "aa")["actors"]["aa"]
        self.assertEqual((r["pid"], r["cmd"]), (s2.pid, "std actor-op: x"))

    # P19 (m0-measure X10): Claude Code signals the whole tree
    def test_p19_tree_sigterm_reaches_the_child_once_and_gracefully(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30", "--on-signal", "slow:0.8"))
        start = self.child_ready()
        for pid in (p.pid, start["pgid"], start["pid"]):  # wrapper, watcher, child
            os.kill(pid, signal.SIGTERM)
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertEqual(self.signals(), [signal.SIGTERM])
        self.assertIn("graceful", [e["event"] for e in self.events()])
        status = [l for l in err.decode().splitlines() if l.startswith("driver-status: ")][0]
        self.assertIn("got 15", status)
        self.assertFalse(os.path.exists(self.lock))

    # P20 (m0-measure X10): the same SIGTERM twice at once (group + pid) is one signal
    def test_p20_double_sigterm_is_not_a_second_signal(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30", "--on-signal", "slow:0.8"))
        start = self.child_ready()
        for pid in (p.pid, start["pgid"], start["pid"]):
            os.kill(pid, signal.SIGTERM)
        # the duplicate arrives apart (pending signals of one kind would merge). lock.py does not
        # force on it; the fake child here survives its own duplicate — real s2v would treat a
        # duplicate it receives directly as a second Ctrl-C (s2v follow-up, m0c-plan §16)
        time.sleep(0.15)
        for pid in (p.pid, start["pid"]):
            os.kill(pid, signal.SIGTERM)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertIn("graceful", [e["event"] for e in self.events()])  # not killed
        self.assertFalse(os.path.exists(self.lock))

    # P21: the same signal again after the window forces
    def test_p21_same_signal_after_the_window_forces(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30", "--on-signal", "slow:5"))
        start = self.child_ready()
        os.kill(p.pid, signal.SIGTERM)
        self.assertTrue(wait_for(lambda: signal.SIGTERM in self.signals()))
        time.sleep(0.7)
        os.kill(p.pid, signal.SIGTERM)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertNotIn("graceful", [e["event"] for e in self.events()])
        self.assertFalse(alive(start["pid"]))

    # P9c: the watcher is gone; one signal to the wrapper still reaches the child once
    def test_p9c_watcher_gone_signal_forwarded_after_the_grace(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30", "--on-signal", "slow:0.8"))
        start = self.child_ready()
        os.kill(start["pgid"], signal.SIGKILL)  # the watcher only
        time.sleep(0.3)
        os.kill(p.pid, signal.SIGTERM)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertEqual(self.signals(), [signal.SIGTERM])
        self.assertIn("graceful", [e["event"] for e in self.events()])
        self.assertFalse(os.path.exists(self.lock))

    # P23: with no `got` from the watcher, the first signal is forwarded exactly once
    def test_p23_forwarded_once_without_got(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30", "--on-signal", "slow:0.8"),
                       drop_got=True)
        self.child_ready()
        os.kill(p.pid, signal.SIGTERM)
        p.wait(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertEqual(self.signals(), [signal.SIGTERM])

    # P22 (m0-measure §6-6): wrapper, watcher and child all SIGKILLed: the next taker breaks it
    def test_p22_all_sigkilled_next_taker_breaks(self):
        p = self.start(["run", "--kind", "tts", "--"] + self.fake("--sleep", "30"))
        start = self.child_ready()
        for pid in (p.pid, start["pgid"], start["pid"]):
            os.kill(pid, signal.SIGKILL)
        p.wait(timeout=5)
        self.assertTrue(os.path.exists(self.lock))
        self.assertEqual(self.run_lock(["run", "--kind", "tts", "--"] + self.fake())[0], 0)
        self.assertFalse(os.path.exists(self.lock))

    @classmethod
    def tearDownClass(cls):
        found = glob.glob(os.path.join(helpers.PLUGIN, "**", "__pycache__"), recursive=True)
        assert not found, "__pycache__ left in the plugin: %s" % found
