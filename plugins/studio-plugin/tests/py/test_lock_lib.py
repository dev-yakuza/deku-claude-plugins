"""M0c library tests (m0c-plan §9.1): the directory lock, places, formats, the kind table."""

import json
import os
import stat
import subprocess
import sys
import time

import helpers
from helpers import StudioTestCase
from stdo import dirlock, locks, s2vcall

LIVE_START = "Mon Oct 19 20:06:47 2026"


def env_with(alive=None, cannot=False, now=None, hooks=None, platform="darwin"):
    """A LockEnv whose ps says: pids in `alive` run with LIVE_START."""
    alive = set(alive or [])

    def ps(pid):
        if cannot:
            raise dirlock.CannotCheck("no ps")
        return LIVE_START if pid in alive else None

    return dirlock.LockEnv(proc_start=ps, platform=platform, now=now, hooks=hooks, sleep=lambda ms: None)


def owner(lock, pid=4242, start=LIVE_START, token="a" * 32, **extra):
    os.makedirs(lock, exist_ok=True)
    d = {"kind": "tts", "pid": pid, "pid_start": start, "holder": "x", "token": token}
    d.update(extra)
    with open(os.path.join(lock, "owner.json"), "w") as f:
        json.dump(d, f)


class DirLock(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.lock = os.path.join(self.tmp, "state", "heavy.lock.d")

    def test_l1_take_hold_release(self):
        e = env_with(alive={os.getpid()})
        r = dirlock.acquire(self.lock, {"kind": "tts", "pid": os.getpid(), "pid_start": LIVE_START,
                                        "holder": "h"}, env=e)
        self.assertEqual(r.status, "acquired")
        body = open(os.path.join(self.lock, "owner.json")).read()
        self.assertTrue(body.endswith("\n"))
        self.assertEqual(list(json.loads(body)), ["kind", "pid", "pid_start", "holder", "token"])
        self.assertRegex(r.token, r"^[0-9a-f]{32}$")
        r2 = dirlock.acquire(self.lock, {"kind": "tts", "pid": 1, "pid_start": "x", "holder": "h"}, env=e)
        self.assertEqual(r2.status, "held")
        self.assertFalse(dirlock.release(self.lock, "b" * 32))
        self.assertTrue(dirlock.release(self.lock, r.token))
        self.assertFalse(os.path.exists(self.lock))

    def test_l2_rename_onto_an_empty_dir_succeeds(self):
        # why the lock is never taken with mkdir: a rename onto an empty folder wins
        os.makedirs(self.lock)
        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=env_with())
        self.assertEqual(r.status, "acquired")

    def test_l3_unreadable_owner_is_retried_then_broken(self):
        os.makedirs(self.lock)
        with open(os.path.join(self.lock, "owner.json"), "w") as f:
            f.write("{broken")
        reads = []
        e = env_with(hooks={"before_owner_read": lambda: reads.append(1)})
        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=e)
        self.assertEqual(r.status, "acquired")
        self.assertEqual(len(reads), dirlock.UNREADABLE_TRIES + 1)

    def test_l3_owner_appearing_meanwhile_is_not_broken(self):
        os.makedirs(self.lock)
        with open(os.path.join(self.lock, "owner.json"), "w") as f:
            f.write("{being written")
        calls = []

        def fix():
            calls.append(1)
            if len(calls) == 2:
                owner(self.lock, pid=7)

        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"},
                            env=env_with(alive={7}, hooks={"before_owner_read": fix}))
        self.assertEqual(r.status, "held")

    def test_l4_dead_and_live_owners(self):
        owner(self.lock, pid=7)
        self.assertEqual(dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=env_with()).status, "acquired")
        dirlock.release(self.lock, dirlock.read_owner(self.lock)["token"])
        owner(self.lock, pid=7, start="Mon Oct 19 20:06:48 2026")
        self.assertEqual(dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=env_with(alive={7})).status,
                         "acquired")  # same pid, another start time: dead
        dirlock.release(self.lock, dirlock.read_owner(self.lock)["token"])
        owner(self.lock, pid=7)
        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=env_with(cannot=True))
        self.assertEqual((r.status, r.cannot_check), ("held", True))

    def test_l5_lock_replaced_inside_the_mutex_is_not_broken(self):
        owner(self.lock, pid=7, token="1" * 32)

        def replace():
            dirlock.release(self.lock, "1" * 32)
            owner(self.lock, pid=8, token="2" * 32)

        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"},
                            env=env_with(alive={8}, hooks={"in_mutex": replace}))
        self.assertEqual(r.status, "held")
        self.assertEqual(dirlock.read_owner(self.lock)["token"], "2" * 32)

    def test_l5_owner_rewritten_in_place_inside_the_mutex_is_not_moved(self):
        owner(self.lock, pid=7, token="1" * 32)

        def rewrite():  # same folder (same inode), another live owner
            with open(os.path.join(self.lock, "owner.json"), "w") as f:
                json.dump({"pid": 8, "pid_start": LIVE_START, "token": "2" * 32}, f)

        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"},
                            env=env_with(alive={8}, hooks={"in_mutex": rewrite}))
        self.assertEqual(r.status, "held")
        self.assertIsNone(r.note)  # judged again inside the mutex: never moved
        self.assertEqual(dirlock.read_owner(self.lock)["token"], "2" * 32)

    def test_l5_moved_lock_not_the_judged_one_is_put_back(self):
        owner(self.lock, pid=7, token="1" * 32)
        warned = []

        def swap(stale):
            # someone replaced the judged lock just before the rename: what we moved is theirs
            with open(os.path.join(stale, "owner.json"), "w") as f:
                json.dump({"pid": 8, "pid_start": LIVE_START, "token": "3" * 32}, f)

        e = env_with(alive={8}, hooks={"after_break_rename": swap})
        e.warn = warned.append
        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=e)
        self.assertEqual(r.status, "held")
        self.assertIn("put it back", r.note)
        self.assertEqual(dirlock.read_owner(self.lock)["token"], "3" * 32)
        self.assertTrue(warned)

    def test_l6_mutex_rules(self):
        owner(self.lock, pid=7)
        os.mkdir(self.lock + ".break")
        now = time.time() * 1000
        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=env_with(now=lambda: now))
        self.assertEqual(r.status, "breaking")
        for later in (now + 31000, now - 31000):  # stale, or from the future
            r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=env_with(now=lambda: later))
            self.assertEqual(r.status, "acquired")
            dirlock.release(self.lock, r.token)
            owner(self.lock, pid=7)
            os.mkdir(self.lock + ".break")

    def test_l7_contended(self):
        n = []

        def keep_changing():
            n.append(1)
            dirlock.release(self.lock, dirlock.read_owner(self.lock)["token"])
            owner(self.lock, pid=9, token="%032x" % len(n))

        owner(self.lock, pid=9, token="0" * 32)
        # every look finds a new live owner after a failed rename… but alive → held at once;
        # make it dead and changing so every try loops
        e = env_with(hooks={"in_mutex": keep_changing})
        r = dirlock.acquire(self.lock, {"pid": 1, "pid_start": "s"}, env=e)
        self.assertEqual((r.status, r.note), ("held", "contended"))
        self.assertEqual(len(n), dirlock.TRIES)

    def test_l8_leftovers(self):
        parent = os.path.dirname(self.lock)
        os.makedirs(parent)
        names = {"heavy.lock.d.new.0a1b2c3d": True, "heavy.lock.d.stale.ff": True,
                 "heavy.lock.d.gone.12345678": True, "heavy.lock.d.new.0A1B": False,
                 "heavy.lock.d.old.12": False, "heavy.lock.d.break": False,
                 "heavy.lock.d.stale.live0": False}
        for n in names:
            os.makedirs(os.path.join(parent, n))
        owner(os.path.join(parent, "heavy.lock.d.stale.live0"), pid=5)
        old = time.time() - 120
        for n in names:
            os.utime(os.path.join(parent, n), (old, old))
        os.makedirs(os.path.join(parent, "heavy.lock.d.gone.abcd"))  # young
        removed = dirlock.clean_leftovers(self.lock, env_with(alive={5}))
        self.assertEqual(sorted(removed), sorted(n for n, gone in names.items() if gone))
        self.assertTrue(os.path.exists(os.path.join(parent, "heavy.lock.d.gone.abcd")))

    def test_l9_owner_parsing(self):
        cases = [({"pid": True, "pid_start": "s", "token": "t"}, False),
                 ({"pid": "1", "pid_start": "s", "token": "t"}, False),
                 ({"pid": 1, "pid_start": "s"}, False),
                 ({"pid": 4242.0, "pid_start": "s", "token": "t"}, True),
                 ({"pid": 1, "pid_start": "s", "token": "t", "extra": {"k": 1}}, True)]
        for i, (o, ok) in enumerate(cases):
            d = os.path.join(self.tmp, "o%d" % i)
            os.makedirs(d)
            with open(os.path.join(d, "owner.json"), "w") as f:
                json.dump(o, f)
            got = dirlock.read_owner(d)
            self.assertEqual(got is not None, ok, o)
            if ok and "extra" in o:
                self.assertEqual(got["extra"], {"k": 1})
        d = os.path.join(self.tmp, "nan")
        os.makedirs(d)
        with open(os.path.join(d, "owner.json"), "w") as f:
            f.write('{"pid": NaN, "pid_start": "s", "token": "t"}')
        self.assertIsNone(dirlock.read_owner(d))
        for pid in (0, -3, 1.5, 4242.5):
            self.assertIsNone(dirlock.proc_start(pid))
        self.assertTrue(dirlock.liveness({"pid": os.getpid(), "pid_start": dirlock.proc_start(os.getpid())},
                                         dirlock.LockEnv())[0])

    def test_l10_lstart(self):
        self.assertEqual(dirlock.parse_lstart("Mon Oct  5 01:02:03 2026"), 1791162123000)
        self.assertIsNone(dirlock.parse_lstart("Mon Foo  5 01:02:03 2026"))
        self.assertIsNone(dirlock.parse_lstart("Mon Feb 30 01:02:03 2026"))
        self.assertIsNone(dirlock.parse_lstart("Mon Oct ٥ 01:02:03 2026"))  # ASCII digits only
        a = "Mon Oct 19 20:06:47 2026"
        self.assertTrue(dirlock.same_start(a, "Mon Oct 19 20:06:49 2026", "linux"))
        self.assertFalse(dirlock.same_start(a, "Mon Oct 19 20:06:50 2026", "linux"))
        self.assertFalse(dirlock.same_start(a, "Mon Oct 19 20:06:48 2026", "darwin"))


class Places(StudioTestCase):
    def test_l11_gitignore(self):
        d = os.path.join(self.tmp, "c")
        os.makedirs(d)
        cases = [(None, ".work/\n"), ("", ".work/\n"), ("a", "a\n.work/\n"), ("a\n", "a\n.work/\n"),
                 ("x\r\n", "x\r\n.work/\n")]
        cases += [(v + "\n", v + "\n") for v in (".work", ".work/", "/.work", "/.work/")]
        cases += [("a\r\n/.work\r\n", "a\r\n/.work\r\n")]
        for before, after in cases:
            f = os.path.join(d, ".gitignore")
            if os.path.exists(f):
                os.remove(f)
            if before is not None:
                with open(f, "w", newline="") as h:
                    h.write(before)
            locks.ensure_gitignore(d)
            with open(f, newline="") as h:
                self.assertEqual(h.read(), after, repr(before))

    def test_l12_state_dir(self):
        with self.assertRaises(locks.UsageError):
            locks.state_dir({"S2V_STATE_DIR": "rel", "HOME": "/h"})
        self.assertEqual(locks.state_dir({"S2V_STATE_DIR": "", "HOME": "/h"}), "/h/.s2v")
        fresh = os.path.join(self.tmp, "fresh-state")
        locks.ensure_state_dir({"S2V_STATE_DIR": fresh})
        self.assertEqual(stat.S_IMODE(os.stat(fresh).st_mode), 0o700)
        kept = os.path.join(self.tmp, "kept-state")
        os.makedirs(kept, mode=0o755)
        os.chmod(kept, 0o755)
        locks.ensure_state_dir({"S2V_STATE_DIR": kept})
        self.assertEqual(stat.S_IMODE(os.stat(kept).st_mode), 0o755)

    def test_l13_group_gone(self):
        self.assertTrue(locks.group_gone(5, kill0=lambda g: True))
        self.assertTrue(locks.group_gone(5, ps=lambda: "  5 Z+\n  6 S\n", kill0=lambda g: False))
        self.assertFalse(locks.group_gone(5, ps=lambda: "  5 Z\n  5 S+\n", kill0=lambda g: False))

        def fail():
            raise OSError("no ps")

        self.assertFalse(locks.group_gone(5, ps=fail, kill0=lambda g: False))
        g = subprocess.Popen(["sleep", "5"], start_new_session=True)
        try:
            self.assertFalse(locks.group_gone(g.pid))
        finally:
            g.kill()
            g.wait()
        self.assertTrue(locks.group_gone(g.pid))

    def test_l16_actor_dirs(self):
        repo = helpers.make_repo(self.tmp)
        pub = os.path.join(repo, "studio", "cast", "sora", "character")
        loc = os.path.join(repo, "studio", "local", "cast", "kai", "character")
        os.makedirs(pub)
        os.makedirs(loc)
        self.assertEqual(locks.actor_dir(repo, "studio", "sora"), pub)
        self.assertEqual(locks.actor_dir(repo, "studio", "kai"), loc)
        os.makedirs(os.path.join(repo, "studio", "local", "cast", "sora", "character"))
        for bad in ("sora", "nobody", "Bad", "../x", ""):
            with self.assertRaises(locks.UsageError):
                locks.actor_dir(repo, "studio", bad)


class KindTable(StudioTestCase):
    def test_l14_kinds(self):
        k = s2vcall.lock_kind
        for args, want in [
            (["tts", "s.md"], "tts"), (["say", "hi"], "tts"), (["voice", "train", "v.yaml"], "tts"),
            (["voice", "create", "v.yaml", "--candidates=3"], "tts"), (["import-recording", "x"], "tts"),
            (["render", "s.md"], "tts"), (["render", "s.md", "--frozen-audio"], None),
            (["render", "s.md", "--frozen-audio=true"], None), (["snapshot", "s.md"], "tts"),
            (["audio", "prune", "s.md"], "tts"), (["character", "setup"], "gen"),
            (["character", "create", "d"], "gen"), (["character", "build", "d"], "gen"),
            (["character", "build", "d", "--dry-run", "--json"], None),
            (["character", "build", "d", "--layers-only"], "actor"),
            (["character", "approve", "d", "--all"], "actor"), (["character", "redo", "d", "x"], "actor"),
            (["character", "pick", "d", "2"], "actor"), (["character", "review", "d", "--json"], "actor"),
            (["character", "review", "d", "--json", "--no-check"], None),
            (["character", "missing", "s.md", "--apply"], "actor"), (["character", "missing", "s.md"], None),
            (["services", "status", "--json"], None), (["lint", "s.md"], None),
            (["say", "--", "--frozen-audio"], "tts"), (["render", "s.md", "--", "--frozen-audio"], "tts"),
        ]:
            self.assertEqual(k(args), want, args)

    def test_l15_call_forms(self):
        p = os.path.join(self.tmp, "s2v")
        os.makedirs(os.path.join(p, "packages", "cli", "dist"))
        os.makedirs(os.path.join(p, "packages", "cli", "src"))
        other = self.tmp
        f = s2vcall.s2v_args
        self.assertEqual(f(["s2v", "tts", "a"], p, other), ["tts", "a"])
        self.assertEqual(f(["node", p + "/packages/cli/dist/main.js", "tts"], p, other), ["tts"])
        self.assertEqual(f(["/usr/local/bin/node", p + "/packages/cli/dist/main.js", "tts"], p, other), ["tts"])
        self.assertEqual(f(["yarn", "--cwd", p, "s2v", "tts"], p, other), ["tts"])
        self.assertEqual(f(["yarn", "s2v", "tts"], p, p), ["tts"])
        self.assertEqual(f(["npx", "s2v", "tts"], p, p), ["tts"])
        self.assertEqual(f(["tsx", p + "/packages/cli/src/main.ts", "tts"], p, other), ["tts"])
        for bad, cwd in [(["npx", "s2v", "tts"], other), (["yarn", "s2v", "tts"], other),
                         (["bash", "-c", "s2v tts"], other), (["python3", "x.py"], other),
                         (["node", other + "/main.js", "tts"], other), (["cp", "a", "b"], other)]:
            self.assertIsNone(f(bad, p, cwd), bad)
