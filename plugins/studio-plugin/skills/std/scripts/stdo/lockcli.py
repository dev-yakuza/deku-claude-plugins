"""lock.py: run an s2v command under the machine lock or characters' work locks (m0c-plan).

    lock.py run --kind tts|gen [--holder <text>] -- <s2v argv…>
    lock.py actor-op <id> [<id>…] -- <s2v argv…>
    lock.py status [--actor <id>]… [--json]

Exit: the child's code (signal death → 128+n; after a signal, a nonzero child → 128+first signal),
73 machine busy (`busy (<reason>): …`), 74 a character busy (`actor busy: …`), 2 usage or setup,
1 internal (the watcher ended unexpectedly, the own start time unreadable).
"""

import json
import os
import select
import signal
import subprocess
import sys
import time

from . import dirlock, lockargs, locks, s2vcall

WATCHER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watcher.py")
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
NOTICE_EVERY = 30.0
# m0-measure X10: Claude Code signals the whole process tree (the watcher and the child get it
# directly) and may send the same SIGTERM twice at once (group + pid).
FORWARD_GRACE = 0.3  # wait this long for the watcher's `got <n>` before forwarding
DUP_WINDOW = 0.5  # the same signal again within this window is the same signal


def _err(msg):
    sys.stderr.write(msg.rstrip("\n") + "\n")
    sys.stderr.flush()


def _git_top(cwd):
    out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if out.returncode != 0:
        raise locks.UsageError("not inside a git repository: %s" % cwd)
    return out.stdout.strip()


def _config(repo):
    p = os.path.join(repo, ".claude", "studio", "config.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        raise locks.UsageError("no Studio harness here (%s is missing)" % p)
    except ValueError as e:
        raise locks.UsageError("%s is not valid JSON: %s" % (p, e))


def _show_argv(argv, cwd):
    return " ".join(os.path.abspath(os.path.join(cwd, a)) if not a.startswith("-") and not os.path.isabs(a)
                    and os.path.exists(os.path.join(cwd, a)) else a for a in argv)


_parse = lockargs.parse  # shared with the guard (M0d-1a): one reading of lock.py arguments


class Wrapper(object):
    """Signals and the watcher (m0c-plan §5, §14)."""

    def __init__(self):
        self.first = None
        self.t_first = None
        self.force = False
        self.pgid = None
        self.ready = False
        self.t_ready = None
        self.forwarded = False
        self.suppressed = False
        self.killed = False
        self.watcher_got = {}  # signal -> when the watcher's `got` arrived (after `ready` only)
        self.clock = time.monotonic
        self._killpg_impl = os.killpg
        self._old = {}

    def install(self):
        for s in SIGNALS:
            self._old[s] = signal.signal(s, self._on_signal)

    def restore(self):
        for s, h in self._old.items():
            signal.signal(s, h)

    def _on_signal(self, signum, frame):
        now = self.clock()
        if self.first is None:
            self.first, self.t_first = signum, now
        elif signum != self.first or now - self.t_first >= DUP_WINDOW:
            self.force = True  # a second signal (a duplicate within DUP_WINDOW is not one)
        self.act()

    def act(self):
        """A second signal kills a started group at once."""
        if self.pgid is not None and self.force and not self.killed:
            self._killpg(signal.SIGKILL)
            self.killed = True

    def mark_ready(self):
        self.ready, self.t_ready = True, self.clock()
        self.act()

    def watcher_reported(self, signum):
        """The watcher got `signum` directly. Before `ready` the child may not have been exec'd
        yet (it may have missed the signal): such a report does not count."""
        if self.ready:
            self.watcher_got[int(signum)] = self.clock()

    def poll(self):
        """Forward the first signal once the watcher is ready — unless the watcher reports it got
        that signal directly (a tree-wide signal: the child got it too) within FORWARD_GRACE."""
        if not self.ready or self.first is None or self.forwarded or self.killed:
            return
        got = self.watcher_got.get(int(self.first))
        if got is not None and got >= self.t_first - DUP_WINDOW:  # near the first signal only
            self.forwarded, self.suppressed = True, True
            return
        if self.clock() - max(self.t_first, self.t_ready) >= FORWARD_GRACE:
            self._killpg(self.first)
            self.forwarded = True

    def _killpg(self, sig):
        try:
            self._killpg_impl(self.pgid, sig)
        except OSError:
            pass


def _exit_code(w, child):
    """child: ('exit', code) | ('signal', n) | None."""
    if child is None:
        if w.first is not None:
            return 128 + int(w.first)
        _err("std lock: the watcher ended unexpectedly; the lock was kept until its group was empty")
        return 1
    kind, n = child
    code = 128 + n if kind == "signal" else n
    if w.first is not None and code != 0:
        return 128 + int(w.first)
    return code


def _supervise(w, argv, env, hooks):
    """Start the watcher and wait until its group is empty. Returns the child's result or None."""
    lr, lw = os.pipe()
    sr, sw = os.pipe()
    try:
        proc = subprocess.Popen([sys.executable, "-B", WATCHER, "--lifeline-fd", str(lr),
                                 "--status-fd", str(sw), "--"] + list(argv),
                                start_new_session=True, pass_fds=(lr, sw), stdin=subprocess.DEVNULL,
                                env=env)
    except OSError as e:
        os.close(lr), os.close(lw), os.close(sr), os.close(sw)
        _err("std lock: cannot start the watcher: %s" % e)
        return None
    os.close(lr)
    os.close(sw)
    w.pgid = proc.pid
    hooks.get("after_spawn", lambda pgid: None)(w.pgid)
    w.act()  # a second signal during Popen kills the group now
    buf = b""
    child = None
    while True:
        w.poll()
        try:
            r, _, _ = select.select([sr], [], [], 0.05)
        except InterruptedError:
            r = []
        if not r:
            continue
        data = os.read(sr, 4096)
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            parts = line.decode("ascii", "replace").split()
            if not hooks.get("keep_status", lambda l: True)(" ".join(parts)):
                continue  # tests: drop lines (e.g. `got`) to reach otherwise rare paths
            hooks.get("status_line", lambda l: None)(" ".join(parts))
            if parts == ["ready"]:
                w.mark_ready()  # signals held until the watcher's handlers and the child are in place
            elif len(parts) == 2 and parts[0] == "got" and parts[1].isdigit():
                w.watcher_reported(int(parts[1]))
                w.poll()
            elif len(parts) == 2 and parts[0] in ("exit", "signal") and parts[1].isdigit():
                child = (parts[0], int(parts[1]))
    os.close(sr)
    proc.wait()
    # the lock stays until nothing of the group runs (a grandchild may still use memory)
    last = time.time()
    while not locks.group_gone(w.pgid):
        w.poll()  # the watcher may be gone: a first signal is still forwarded after the grace
        if time.time() - last >= NOTICE_EVERY:
            _err("std lock: waiting for processes still in the group: %s"
                 % " ".join(map(str, locks.group_members(w.pgid))))
            last = time.time()
        time.sleep(0.1)
    os.close(lw)
    return child


def _child_env(token_env, token):
    env = dict(os.environ)
    env.pop(locks.HEAVY_TOKEN_ENV, None)
    env.pop(locks.ACTOR_TOKEN_ENV, None)
    env[token_env] = token
    env["S2V_NO_OPEN"] = "1"
    return env


def main(argv, child_kind=None, hooks=None, lock_env=None, cwd=None):
    """child_kind(argv, s2v_path, cwd) -> 'tts'|'gen'|'actor'|None (tests inject a fake s2v)."""
    hooks = hooks or {}
    cwd = cwd or os.getcwd()
    lock_env = lock_env or dirlock.LockEnv(warn=_err)
    w = Wrapper()
    w.install()
    try:
        try:
            opts = _parse(argv)
            if opts["cmd"] == "status":
                return _status(opts, cwd, lock_env)
            for name in (locks.HEAVY_TOKEN_ENV, locks.ACTOR_TOKEN_ENV):
                if os.environ.get(name):
                    raise locks.UsageError("lock.py does not run under another lock (%s is set)" % name)
            locks.state_dir()
            repo = _git_top(cwd)
            cfg = _config(repo)
            s2v_path = (cfg.get("s2v") or {}).get("path")
            studio_root = cfg.get("studio_root") or "studio"
            if child_kind is None:
                args = s2vcall.s2v_args(opts["child"], s2v_path, cwd)
                if args is None:
                    raise locks.UsageError("not an s2v command: %s" % " ".join(opts["child"][:3]))
                kind = s2vcall.lock_kind(args)
            else:
                kind = child_kind(opts["child"], s2v_path, cwd)
            want = opts["kind"] if opts["cmd"] == "run" else "actor"
            if kind != want:
                raise locks.UsageError("%s does not need the %s lock (it needs: %s)" % (
                    " ".join(opts["child"][:4]), want, kind or "no lock"))
            dirs = []
            if opts["cmd"] == "actor-op":
                seen = set()
                for i in opts["ids"]:
                    d = os.path.realpath(locks.actor_dir(repo, studio_root, i))
                    if d not in seen:
                        seen.add(d)
                        dirs.append(d)
        except locks.UsageError as e:
            _err("std lock: %s" % e)
            return locks.EXIT_USAGE
        own_start = dirlock.proc_start(os.getpid())
        if not own_start:
            _err("std lock: cannot read this process start time (ps)")
            return 1
        shown = _show_argv(opts["child"], cwd)
        if opts["cmd"] == "run":
            return _run_heavy(w, opts, shown, own_start, lock_env, hooks)
        return _run_actors(w, opts, dirs, shown, own_start, lock_env, hooks)
    finally:
        w.restore()


def _after_acquire(w, hooks):
    hooks.get("after_acquire", lambda: None)()
    return w.first is not None


def _run_heavy(w, opts, shown, own_start, lock_env, hooks):
    locks.ensure_state_dir()
    lock = locks.heavy_lock_path()
    holder = dirlock.display_text(opts["holder"] or ("std: " + shown))
    r = dirlock.acquire(lock, {"kind": opts["kind"], "pid": os.getpid(), "pid_start": own_start,
                               "holder": holder}, env=lock_env)
    if r.status != "acquired":
        _err(locks.heavy_busy_line(r))
        return locks.EXIT_BUSY
    try:
        dirlock.clean_leftovers(lock, lock_env)
        if _after_acquire(w, hooks):
            return 128 + int(w.first)
        child = _supervise(w, opts["child"], _child_env(locks.HEAVY_TOKEN_ENV, r.token), hooks)
        return _exit_code(w, child)
    finally:
        if not dirlock.release(lock, r.token):
            _err("warning: the machine lock was no longer ours when releasing it")


def _run_actors(w, opts, dirs, shown, own_start, lock_env, hooks):
    token = dirlock.new_token()
    cmd = dirlock.display_text("std actor-op: " + shown)
    taken = []
    try:
        for d in dirs:
            lock = locks.actor_lock_path(d)
            r = dirlock.acquire(lock, {"pid": os.getpid(), "pid_start": own_start, "cmd": cmd},
                                token=token, env=lock_env)
            if r.status != "acquired":
                _err(locks.actor_busy_line(r, d))
                return locks.EXIT_ACTOR_BUSY  # the finally below releases the ones taken
            taken.append(d)
            locks.ensure_gitignore(d)
            dirlock.clean_leftovers(lock, lock_env)
        if _after_acquire(w, hooks):
            return 128 + int(w.first)
        child = _supervise(w, opts["child"], _child_env(locks.ACTOR_TOKEN_ENV, token), hooks)
        return _exit_code(w, child)
    finally:
        for t in taken:
            if not dirlock.release(locks.actor_lock_path(t), token):
                _err("warning: the work lock of %s was no longer ours when releasing it" % t)


def _status(opts, cwd, lock_env):
    out = {"state_dir": locks.state_dir(), "heavy": locks.heavy_state(lock_env=lock_env), "actors": {}}
    if opts["actors"]:
        repo = _git_top(cwd)
        cfg = _config(repo)
        root = cfg.get("studio_root") or "studio"
        for i in opts["actors"]:
            out["actors"][i] = locks.running(locks.actor_dir(repo, root, i), lock_env)
    if opts["json"]:
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    else:
        h = out["heavy"]
        sys.stdout.write("machine lock: %s\n" % ("free" if not h else "%s %s — %s (pid %s)" % (
            h["state"], h["kind"], h["holder"], h["pid"])))
        for i, r in out["actors"].items():
            sys.stdout.write("actor %s: %s\n" % (i, "free" if not r else "%s (pid %s)" % (r["cmd"], r["pid"])))
    return 0
