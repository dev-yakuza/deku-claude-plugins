"""The sprint supervisor (stage-4 scope §2.1, §2.2, §2.5–§2.8, VA4) — owner: branch A.

Fixed engine code, no LLM: one member after the other, each in a CHILD engine process
(`engine.py dev --foreground --mode unattended …`, H1), judged by exit code, that Issue's state.json, the
named codes of its log and the lock file (D3). It imports no driver module on purpose.

One run looks at every member once, in the order of the member table (sprintdag.order). sprint.json is what this
run saw; a re-run decides again from the Issues' state.json and GitHub (only the window is inherited). Nothing here
branches on free text: outcomes, blocks, halts and stops are codes.

  - Locks (H4): the sprint locks for the whole run, never the engines' repository lock — a human may `dev` or
    `resume` between two members. A member whose lock a human's engine holds is `skipped-locked`; another Issue of
    the repository is waited for (H5).
  - Signals: TERM / HUP end the run after the running member. A running member is never killed (its process is in
    its own session, D5).
  - A marker that cannot be written, or a changed engine (R8), ends the run before the next member.
"""

import hashlib
import json
import os
import signal
import socket
import subprocess
import threading
import time
import traceback

from . import (basecheck, codes, defaults, fsafe, github, gitops, incidents, lifecycle, outbound, paths as pathsmod,
               repoconfig, sprintdag, sprinttracker, store)

EXIT_OK, EXIT_LOCKED, EXIT_REFUSED = 0, 3, 4
MEMBER_OK, MEMBER_LOCKED, MEMBER_REFUSED, MEMBER_STOPPED = 0, 3, 4, (10, 11)      # driver.EXIT_* of a member engine
UNIT_NAMES = ("spawn_member", "base_check", "tracker", "git", "self_check", "now", "sleep")
CODE_ROOTS = (os.path.join("skills", "gld", "engine"), os.path.join("skills", "gld", "gates"), ".claude-plugin")
CODE_SKIP = ("tests", "__pycache__", "out")

O, B, H, S, EV = codes.MemberOutcome, codes.MemberBlock, codes.SprintHalt, codes.SprintState, codes.SprintEvent
DONE_STATUSES = (codes.StepStatus.DONE.value, codes.StepStatus.SKIPPED.value)
UNREADABLE = (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath)
MARKER_ERRORS = (github.GhError, outbound.ScanError, outbound.SecretDetected)


class SprintOptions:
    """repo, tracker, checkout, plugin_root, engine_home, environ, out; window (text or None = not given),
    allow_red_base, take_over, srt (path), user_tmp (or None), stage."""

    FIELDS = ("repo", "tracker", "checkout", "plugin_root", "engine_home", "environ", "out", "window",
              "allow_red_base", "take_over", "srt", "user_tmp", "stage")

    def __init__(self, **fields):
        if set(fields) != set(self.FIELDS):
            raise TypeError(f"SprintOptions needs exactly {self.FIELDS}")
        for k, v in fields.items():
            setattr(self, k, v)


class SprintUnits:
    """The seams of the supervisor; tests pass doubles for all of them (§6.3).

    spawn_member(argv, *, log_file, rc_file, env, cwd, on_tick) → exit code. Runs one member engine in its own
                  session, its output appended to the Issue's engine.log, engine.rc removed before and
                  written after (D5); `on_tick` is called at least every SPRINT_MARKER_EVERY_S.
    base_check(BaseCheckRequest) → BaseCheckResult            (basecheck.check)
    tracker       the sprinttracker module (read, write_marker, merge_settings, issue_facts, dep_facts, remote_state,
                  default_branch, base_red_comment)
    git           the gitops functions of VA3 (main_context, fetch_branches, control_changes, blob, is_regular_mode)
    self_check()  → (ok, message): srt + gate hook once before the first member (D3)
    now() / sleep(seconds)"""

    def __init__(self, **units):
        if set(units) != set(UNIT_NAMES):
            raise TypeError(f"SprintUnits needs exactly {UNIT_NAMES}")
        for k, v in units.items():
            setattr(self, k, v)


def default_units(self_check):
    """The real units; `self_check` is the caller's (it belongs to the driver, which this module never imports)."""
    return SprintUnits(spawn_member=spawn_member, base_check=basecheck.check, tracker=sprinttracker, git=gitops,
                       self_check=self_check, now=time.time, sleep=time.sleep)


class _Halt(Exception):
    """The run ends before its last member: codes.SprintHalt value + a text for the supervisor's log."""

    def __init__(self, halt, note=""):
        self.halt, self.note = halt.value, note
        super().__init__(f"{self.halt}: {note}")


class _Refused(Exception):
    """Nothing is started and nothing is written but the output line (exit 4)."""


# --- small pieces ---------------------------------------------------------------------------------------

def engine_sha256(plugin_root):
    """R8: sha256 over the engine's code files (sorted relative paths + contents) of the plugin root."""
    files = []
    for base in CODE_ROOTS:
        for d, dirs, names in os.walk(os.path.join(plugin_root, base)):
            dirs[:] = [x for x in dirs if x not in CODE_SKIP]
            files += [os.path.join(d, n) for n in names if not n.endswith(".pyc")]
    if not files:
        raise ValueError(f"no engine files under {plugin_root!r}")
    h = hashlib.sha256()
    for path in sorted(files):
        rel = os.path.relpath(path, plugin_root).encode("utf-8", "surrogateescape")
        if os.path.islink(path):
            data = b"-> " + os.fsencode(os.readlink(path))
        else:
            with open(path, "rb") as f:
                data = f.read()
        h.update(b"%d:%s%d:" % (len(rel), rel, len(data)))
        h.update(data)
    return h.hexdigest()


def plugin_version(plugin_root):
    try:
        with open(os.path.join(plugin_root, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            v = json.load(f).get("version")
    except (OSError, ValueError, AttributeError):
        v = None
    return v if isinstance(v, str) and v else "unknown"


def host_name():
    """This machine's name as it is written to the marker (no character the outgoing text layer would change)."""
    name = "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "-" for c in socket.gethostname())
    return name or "unknown-host"


def spawn_member(argv, *, log_file, rc_file, env, cwd, on_tick):
    """SprintUnits.spawn_member (D5)."""
    try:
        os.unlink(rc_file)
    except FileNotFoundError:
        pass
    log = lifecycle._open_log(log_file)
    try:
        try:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=dict(env), cwd=cwd,
                                 close_fds=True, start_new_session=True)
        except OSError as e:
            os.write(log, f"engine could not start: {e}\n".encode())
            rc = 127
        else:
            while True:
                try:
                    rc = p.wait(timeout=defaults.SPRINT_POLL_S)
                    break
                except subprocess.TimeoutExpired:
                    on_tick()
    finally:
        os.close(log)
    fsafe.write_text(rc_file, f"{rc}\n", root=os.path.dirname(rc_file), mode=0o600)
    return rc


def finished(state):
    """Every step of the Issue is done (or skipped), nothing waits, and its pull request exists."""
    return (state is not None and not state.get("stop") and not state.get("closed")
            and all(s["status"] in DONE_STATUSES for s in state["steps"])
            and bool((state.get("github") or {}).get("pr_number")))


def _total_cost(state):
    """totals.cost_usd of a state.json object, or None."""
    cost = ((state or {}).get("totals") or {}).get("cost_usd")
    return cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None


def local_facts(state):
    """sprintdag.DepFacts.local of a state.json object (None = there is none on this machine)."""
    if state is None:
        return None
    return {"finished": finished(state), "stopped": bool(state.get("stop")),
            "pr_number": (state.get("github") or {}).get("pr_number")}


def judge(rc, state):
    """(MemberOutcome value, MemberBlock value or None) of a member engine's exit code and the state.json it left
    (§2.2; exit 3 is not judged here). Anything that does not fit is `failed` — never a pass."""
    stop = (state or {}).get("stop")
    if rc == MEMBER_OK and state is not None and not stop:
        if state.get("closed"):
            return O.CLOSED.value, None
        if finished(state):
            return O.DONE.value, None
    if rc in MEMBER_STOPPED and stop:
        if stop.get("detail") == codes.SPRINT_RERUN_DETAIL:
            return O.BLOCKED.value, B.QUOTA.value
        return O.STOPPED.value, None
    if rc == MEMBER_REFUSED:
        return O.REFUSED.value, None
    return O.FAILED.value, None


def _refused_code(lines):
    """The StopReason code of the last `data.refused` log line (D3), or None."""
    code = None
    for line in lines:
        if (line.get("data") or {}).get("refused") is True:
            code = line.get("code")
    return code if code in codes.StopReason.values() else None


def _marker_running(run):
    """The tracker's run marker (Tracker.run) says a run has not ended — an unreadable one counts as running."""
    if run is None:
        return False
    state = (run["data"] or {}).get("state")
    return not (isinstance(state, str) and state.split(":", 1)[0] in codes.SPRINT_ENDED)


# --- the run ----------------------------------------------------------------------------------------------

class _Run:
    def __init__(self, options, units):
        self.o, self.u = options, units
        self.sp = pathsmod.SprintPaths(options.engine_home, options.repo, options.tracker)
        self.gh = github.Gh(options.repo, env=options.environ, plugin_root=options.plugin_root)
        self.s = None                    # the sprint.json object
        self.comment_id = None
        self.marker_fails, self.marker_max = 0, defaults.SPRINT_MARKER_FAILS_MAX
        self.last_beat = None
        self.pending = None              # a _Halt that waits for the running member to end
        self.quota_unknown = False       # a quota stop without a reset time
        self.ctx = None
        self.default_branch = None
        self.spent = {}                  # issue → what its child engines of this run cost (member-end data.cost_usd)

    # -- output and records --
    def say(self, text):
        self.o.out.write(f"[{store.now_ts()}] {text}\n")
        self.o.out.flush()

    def log(self, event, **fields):
        store.append_sprint_log(self.sp, self.s["run"], event.value, **fields)

    def warn(self, text):
        self.say("warning: " + text)
        self.log(EV.WARNING, note=text[:1000])

    def save(self):
        store.save_sprint(self.sp, self.s)

    def set_state(self, state, halt=None):
        self.s["state"], self.s["halt"] = state.value, halt
        self.save()
        self.beat(force=True)

    def beat(self, force=False):
        """Refresh the tracker marker (at least every SPRINT_MARKER_EVERY_S). Never raises: too many failures in a row
        end the run at the next check() — a running member is not left behind (§2.2)."""
        now = self.u.now()
        if not force and self.last_beat is not None and now - self.last_beat < defaults.SPRINT_MARKER_EVERY_S:
            return
        self.last_beat = now
        try:
            self.comment_id = self.u.tracker.write_marker(self.gh, self.o.tracker, self.comment_id, self.s)
            self.marker_fails = 0
        except MARKER_ERRORS as e:
            self.marker_fails += 1
            self.warn(f"run marker not written ({self.marker_fails}): {e}")
            if self.marker_fails >= self.marker_max and self.pending is None:
                self.pending = _Halt(H.MARKER_UNWRITABLE, f"{self.marker_fails} failed writes in a row")

    def on_signal(self, signum, frame):
        if self.pending is None:
            self.pending = _Halt(H.SIGNAL, f"signal {signum}")

    def check(self):
        if self.pending is not None:
            raise self.pending

    def sleep(self):
        self.check()
        self.u.sleep(defaults.SPRINT_POLL_S)
        self.beat()
        self.check()

    # -- before the first member --
    def prepare(self):
        """The tracker, the table, the previous run → self.s. _Refused = nothing of this run is recorded."""
        o = self.o
        try:
            given = None if o.window is None else sprintdag.parse_window(o.window)
            prev = store.load_sprint(self.sp)
        except (ValueError, *UNREADABLE) as e:
            raise _Refused(str(e)) from None
        try:
            tracker = self.u.tracker.read(self.gh, o.tracker)
            members = sprintdag.parse_table(tracker.body)
            order, warnings = sprintdag.order(members)
            stored, now_hash = sprintdag.stored_plan_hash(tracker.body), sprintdag.plan_hash(tracker.body)
        except (github.GhError, sprintdag.SprintTableError) as e:
            raise _Refused(str(e)) from None
        if tracker.state != "OPEN":
            raise _Refused(f"the tracking Issue {o.tracker} is {tracker.state}, not open")
        window = given if o.window is not None else (prev or {}).get("window")
        self.members = {m.issue: m for m in members}
        self.deps = sprintdag.effective_deps(members)[0]
        self.token = sprintdag.stack_reason_token(tracker.body)
        self.comment_id = tracker.run["id"] if tracker.run else None
        self.s = {
            "format": defaults.FORMAT, "repo": o.repo, "tracker": o.tracker, "run": (prev or {}).get("run", 0) + 1,
            "plan_hash": now_hash, "state": S.STARTING.value, "halt": None, "plugin_version": plugin_version(o.plugin_root),
            "engine_sha256": engine_sha256(o.plugin_root), "host": host_name(), "pid": os.getpid(),
            "started": store.now_ts(), "ended": None, "window": window, "allow_red_base": bool(o.allow_red_base),
            "stack_reason": None, "base_check": None, "quota_reset_at": None, "order": order,
            "members": [self.new_row(self.members[n]) for n in order]}
        self.rows = {r["issue"]: r for r in self.s["members"]}
        other = tracker.run is not None and (tracker.run["data"] or {}).get("host") != self.s["host"]
        if other and _marker_running(tracker.run) and not o.take_over:
            self.comment_id = None                         # that marker is the other run's
            self.save()
            raise _Halt(H.OTHER_HOST, "another machine's run has not ended (--take-over after a human checked it)")
        self.save()
        self.log(EV.SPRINT_START, state=S.STARTING.value, data={
            "order": order, "plan_hash": now_hash, "window": window, "allow_red_base": self.s["allow_red_base"],
            "take_over": bool(o.take_over), "plugin_version": self.s["plugin_version"]})
        for w in warnings:
            self.warn(w)
        self.beat(force=True)
        if stored != now_hash:
            raise _Halt(H.PLAN_HASH_MISMATCH, f"the tracker says {stored}, its plan block is {now_hash} — run sprint plan again")

    def new_row(self, m):
        return {"issue": m.issue, "base_dep": m.base_dep, "kind": m.kind, "outcome": None, "block": None, "cause": None,
                "stop_reason": None, "stop_detail": None, "base": None, "pr": None, "draft": False, "rc": None,
                "started": None, "ended": None, "cost_usd": None}

    def boundary(self):
        """D3: srt and the gate hook, once — the next member would fail at the same place."""
        ok, message = self.u.self_check()
        if not ok:
            raise _Halt(H.BOUNDARY, message)

    def base_check(self):
        """§2.7 (H12): the named commands of the fetched default branch are green — before any member and any wait."""
        o = self.o
        self.set_state(S.CHECKING_BASE)
        try:
            self.default_branch = self.u.tracker.default_branch(self.gh)
            self.ctx = self.u.git.main_context(o.checkout, base_env=o.environ)
            sha = self.u.git.fetch_branches(self.ctx, [self.default_branch])[self.default_branch]
            got = self.u.git.blob(self.ctx, sha, repoconfig.CONFIG_PATH)
        except (github.GhError, gitops.GitError, OSError) as e:
            raise _Halt(H.BASE_RED, f"the base could not be read: {e}") from None
        self.s["stack_reason"] = sprintdag.effective_stack_reason(self.token, self.u.tracker.merge_settings(self.gh))
        red, problem, res = [], None, None
        if got is None or not self.u.git.is_regular_mode(got[0]) or got[2] is None:
            problem = "config"
        else:
            res = self.in_thread(lambda: self.u.base_check(basecheck.BaseCheckRequest(
                repo=o.repo, checkout=o.checkout, sha=sha, config_text=got[2].decode("utf-8", "surrogateescape"),
                engine_home=o.engine_home, plugin_root=o.plugin_root, environ=o.environ, srt=o.srt, user_tmp=o.user_tmp,
                force=False, out=o.out)))
            red, problem = list(res.red), res.problem
            self.s["base_check"] = {"sha": sha, "config_sha256": hashlib.sha256(got[2]).hexdigest(), "ok": res.ok,
                                    "record": os.path.basename(res.record or "")}
            self.save()
        ok = res is not None and res.ok
        self.log(EV.BASE_CHECK, data={"sha": sha, "ok": ok, "red": red, "flaky": list(res.flaky) if res else []},
                 note=problem)
        self.say(f"base check {sha[:12]}: {'green' if ok else 'red ' + ', '.join(red)}{' ' + problem if problem else ''}")
        if ok:
            return
        if problem == "srt-canary":
            raise _Halt(H.BOUNDARY, "base check: the srt canary failed")
        if problem is None and self.s["allow_red_base"]:
            self.warn(f"red base allowed by a human: {', '.join(red)}")
            return
        try:
            self.u.tracker.base_red_comment(self.gh, o.tracker, sha, red, problem)
        except MARKER_ERRORS as e:
            self.warn(f"base-red comment not posted: {e}")
        raise _Halt(H.BASE_RED, f"red: {', '.join(red) or '—'}; problem: {problem or '—'}")

    def in_thread(self, fn):
        """Run `fn` beside the heartbeat. A signal waits for its end (nothing is killed)."""
        box = {}

        def body():
            try:
                box["value"] = fn()
            except BaseException as e:  # noqa: BLE001 — re-raised in the caller
                box["error"] = e
        t = threading.Thread(target=body, daemon=True)
        t.start()
        while t.is_alive():
            t.join(timeout=defaults.SPRINT_POLL_S)
            self.beat()
        if "error" in box:
            raise box["error"]
        return box["value"]

    # -- the window --
    def clock(self):
        return time.strftime("%H:%M", time.localtime(self.u.now()))

    def wait_window(self):
        """§2.6: only before a new member. A member that runs is never cut."""
        window = self.s["window"]
        if sprintdag.in_window(window, self.clock()):
            return
        self.say(f"outside the window {window} — waiting")
        self.log(EV.WAIT, data={"for": "window", "until": window[:5]})
        self.marker_fails, self.marker_max = 0, defaults.SPRINT_MARKER_FAILS_MAX_WINDOW
        self.set_state(S.WAITING_FOR_WINDOW)
        while not sprintdag.in_window(window, self.clock()):
            self.sleep()
        self.check()
        self.marker_fails, self.marker_max = 0, defaults.SPRINT_MARKER_FAILS_MAX
        self.set_state(S.RUNNING)

    # -- one member --
    def paths(self, issue):
        return pathsmod.EnginePaths(self.o.engine_home, self.o.repo, issue)

    def state(self, issue):
        return store.load_state(self.paths(issue))

    def end(self, row, outcome, block=None, cause=None, stop_reason=None, stop_detail=None):
        row.update(outcome=outcome.value, block=block, cause=cause, stop_reason=stop_reason, stop_detail=stop_detail)
        return True

    def blocked(self, row, block, cause=None):
        return self.end(row, O.BLOCKED, getattr(block, "value", block), cause)

    def fill(self, row, state):
        """The facts of the Issue's state.json that belong to its row."""
        if state is None:
            return
        row["pr"] = (state.get("github") or {}).get("pr_number")
        row["cost_usd"] = _total_cost(state)
        row["draft"] = bool(state.get("draft"))
        branch, sha = state.get("base_branch") or self.default_branch, state.get("base_sha")
        if branch and sha:
            num = branch[len(sprinttracker.BRANCH_PREFIX):] if branch.startswith(sprinttracker.BRANCH_PREFIX) else ""
            row["base"] = {"branch": branch, "sha": sha, "stacked_on": int(num) if num.isdigit() else None}

    def member(self, issue):
        """Look at one member once (§2.2). Waits (H5) start over from fresh facts."""
        row, deadline, quick = self.rows[issue], None, False
        while True:
            try:
                got = self.attempt(row)
            except UNREADABLE as e:
                self.warn(f"#{issue}: {type(e).__name__}: {e}")
                got = self.end(row, O.FAILED)
            if got is True:
                break
            # the repository lock of another Issue's engine (H5); got = its live holder, or None (already gone)
            now = self.u.now()
            if deadline is None:
                deadline = now + defaults.SPRINT_REPO_BUSY_MAX_S
                self.say(f"#{issue}: another engine works on the repository — waiting")
                self.log(EV.WAIT, issue=issue, data={"for": "repo-lock", "until": store.now_ts(deadline)})
            if now >= deadline:
                self.blocked(row, B.REPO_BUSY)
                break
            if got is not None or quick:
                self.sleep()
            quick = got is None
        self.record(row)

    def record(self, row):
        row["ended"] = store.now_ts() if row["started"] else None
        self.save()
        data = {"rc": row["rc"], "cost_usd": self.spent.get(row["issue"]), "pr": row["pr"], "stop_reason": row["stop_reason"],
                "stop_detail": row["stop_detail"], "log_code": row["stop_reason"] if row["outcome"] == O.REFUSED.value else None}
        if row["outcome"] == O.BLOCKED.value:
            self.log(EV.MEMBER_BLOCKED, issue=row["issue"], outcome=row["outcome"], block=row["block"], cause=row["cause"],
                     data=data)
        else:
            self.log(EV.MEMBER_END, issue=row["issue"], outcome=row["outcome"], data=data)
        self.say(f"#{row['issue']}: {row['outcome']}" + (f" ({row['block']})" if row["block"] else "")
                 + (f" ({row['stop_reason']})" if row["stop_reason"] else ""))
        self.beat(force=True)
        if row["started"] and row["stop_reason"] in codes.BOUNDARY_STOPS:                          # H11, D3
            raise _Halt(H.BOUNDARY, f"#{row['issue']} {row['outcome']}: {row['stop_reason']}")

    def attempt(self, row):
        """True = the row has its outcome; else the live holder of the repository lock (None: it is free again)."""
        issue = row["issue"]
        paths = self.paths(issue)
        try:
            facts = self.u.tracker.issue_facts(self.gh, issue)
        except github.GhError as e:
            self.warn(f"#{issue}: {e}")
            return self.blocked(row, B.BASE_UNRESOLVED)
        if facts["state"] == "CLOSED" and facts["state_reason"] != "COMPLETED":
            return self.end(row, O.REFUSED)
        holder = lifecycle.lock_holder(paths)
        if holder is not None and holder.get("issue") == issue:
            return self.end(row, O.SKIPPED_LOCKED)
        state = self.state(issue)
        self.fill(row, state)
        if finished(state):
            return self.end(row, O.DONE)
        if facts["state"] == "CLOSED":
            return self.end(row, O.CLOSED)
        if defaults.LABEL_PREFIX + defaults.EPIC_LABEL_NAME in facts["labels"]:
            return self.blocked(row, B.UNSUPPORTED_EPIC)
        if state is not None and state.get("mode") == codes.RunMode.ATTENDED.value:
            return self.blocked(row, B.ATTENDED_RUN)
        verdict = None
        dep = self.deps[issue]
        if dep is not None:
            try:
                verdict = sprintdag.member_state(self.u.tracker.dep_facts(
                    self.gh, dep, local_facts(self.state(dep)), outcome=self.rows[dep]["outcome"]))
            except (github.GhError, *UNREADABLE) as e:
                self.warn(f"#{issue}: dependency #{dep}: {type(e).__name__}: {e}")
                return self.blocked(row, B.BASE_UNRESOLVED, dep)
            if verdict.block is not None:
                root = self.rows[dep]["cause"] if verdict.block == B.UPSTREAM.value else None
                return self.blocked(row, verdict.block, root or dep)
        argv, extra = None, {}
        if state is not None:
            argv = self.continue_argv(row, state)
            if argv is None:
                return True
            extra = {"resumed": True, "rerun": argv[0] == "resume"}
        if self.quota_waits():
            return self.blocked(row, B.QUOTA)
        if holder is not None:
            return holder
        if argv is None:
            argv = self.start_argv(row, verdict, dep)
            if argv is None:
                return True
            extra = {"resumed": False, "rerun": False}
        return self.run_member(row, paths, argv, extra)

    def quota_waits(self):
        """§2.5: the whole account waits — no new member before the reset (or, unknown, in this run)."""
        reset = self.s["quota_reset_at"]
        return self.quota_unknown or (reset is not None and self.u.now() < reset)

    def note_quota(self, stop):
        reset = stop.get("reset_at")
        if isinstance(reset, (int, float)) and not isinstance(reset, bool):
            self.s["quota_reset_at"] = max(self.s["quota_reset_at"] or 0, reset)
        else:
            self.quota_unknown = True

    def continue_argv(self, row, state):
        """The command that continues an Issue with engine state, or None (the row has its outcome)."""
        issue, stop = row["issue"], state.get("stop")
        if stop and stop.get("detail") == codes.SPRINT_RERUN_DETAIL:
            reset = stop.get("reset_at")
            if isinstance(reset, (int, float)) and self.u.now() < reset:                                 # TQ4
                self.note_quota(stop)
                self.blocked(row, B.QUOTA)
                row.update(stop_reason=stop["reason"], stop_detail=stop["detail"])
                return None
        if stop and stop["status"] == codes.StepStatus.NEEDS_HUMAN.value:
            if lifecycle.sprint_rerun_problem(state, codes.LeaderAnswer.RERUN.value, self.u.now()) is None:
                return ["resume", "--repo", self.o.repo, "--issue", str(issue), "--foreground",
                        "--answer", codes.LeaderAnswer.RERUN.value, "--sprint", str(self.o.tracker)]     # H8, D6
            self.end(row, O.STOPPED, stop_reason=stop["reason"], stop_detail=stop.get("detail"))
            return None
        return self.dev_argv(issue)           # crashed mid-step (S9), or the leader is called again (D24)

    def dev_argv(self, issue):
        return ["dev", "--repo", self.o.repo, "--issue", str(issue), "--mode", codes.RunMode.UNATTENDED.value,
                "--checkout", self.o.checkout, "--foreground"]

    def start_argv(self, row, verdict, dep):
        """The command that starts a new Issue on its base (§2.4), or None (the row has its outcome)."""
        issue, u = row["issue"], self.u
        choice = sprintdag.base_for(verdict, self.default_branch, dep, self.s["stack_reason"])
        if not isinstance(choice, sprintdag.BaseChoice):
            self.blocked(row, choice, dep)
            return None
        try:
            remote = u.tracker.remote_state(self.gh, issue)                                              # H10
            if remote["branch"] or remote["open_pr"] is not None:
                self.blocked(row, B.REMOTE_BRANCH_EXISTS)
                return None
            got = u.git.fetch_branches(self.ctx, sorted({self.default_branch, choice.branch}))           # H6
            sha = got[choice.branch]
            if choice.stacked_on is not None:
                if sha != verdict.pr["head_sha"]:                                                        # TS3
                    raise gitops.GitError(f"{choice.branch} is {sha[:12]}, its pull request says {verdict.pr['head_sha'][:12]}")
                moved = u.git.control_changes(self.ctx, got[self.default_branch], sha, issue)            # D1
                if moved:
                    raise gitops.GitError(f"{choice.branch} changes control files: {', '.join(moved)}")
        except (github.GhError, gitops.GitError, OSError) as e:
            self.warn(f"#{issue}: {e}")
            self.blocked(row, B.BASE_UNRESOLVED, dep)
            return None
        row["base"] = {"branch": choice.branch, "sha": sha, "stacked_on": choice.stacked_on}
        row["draft"] = choice.draft
        return (self.dev_argv(issue) + ["--base-sha", sha, "--base-branch", choice.branch]
                + (["--draft"] if choice.draft else []) + ["--sprint", str(self.o.tracker)])

    def run_member(self, row, paths, argv, extra):
        self.check()
        if engine_sha256(self.o.plugin_root) != self.s["engine_sha256"]:                                 # R8
            raise _Halt(H.ENGINE_ERROR, "the engine's files changed during the run")
        issue, first = row["issue"], row["started"] is None
        if first:
            row["started"] = store.now_ts()
            self.save()
        base = row["base"]
        self.log(EV.MEMBER_START, issue=issue, data=dict(
            {"base": None if base is None else dict(base), "draft": row["draft"]}, **extra))
        self.say(f"#{issue}: {argv[0]}" + (f" on {base['branch']}@{base['sha'][:12]}" if base else ""))
        self.beat(force=first)
        fsafe.make_dirs(paths.issue_dir, root=store._root(paths))
        seen = sum(1 for _ in store.read_log(paths))
        before = _total_cost(self.state(issue)) or 0.0
        rc = self.u.spawn_member(lifecycle.engine_argv(self.o.plugin_root, argv), log_file=paths.engine_log,
                                 rc_file=paths.engine_rc, env=self.o.environ, cwd=self.o.checkout,
                                 on_tick=lambda: self.tick(paths))
        if self.s["state"] == S.WAITING_FOR_QUOTA.value:
            self.set_state(S.RUNNING)
        if rc == MEMBER_LOCKED:
            holder = lifecycle.lock_holder(paths)
            if holder is not None and holder.get("issue") == issue:
                row["started"] = None
                return self.end(row, O.SKIPPED_LOCKED)
            row["started"] = None                          # nothing ran: the attempt starts over (H5)
            return holder
        row["rc"] = rc
        state = self.state(issue)
        self.fill(row, state)
        after = _total_cost(state)
        if after is not None:                  # this run's spend only: a re-run never counts an earlier run again
            self.spent[issue] = round((self.spent.get(issue) or 0.0) + max(0.0, after - before), 6)
        outcome, block = judge(rc, state)
        stop = (state or {}).get("stop") or {}
        code, detail = None, None
        if outcome == O.STOPPED.value or block == B.QUOTA.value:
            code, detail = stop.get("reason"), stop.get("detail")
        elif outcome == O.REFUSED.value:
            code = _refused_code(list(store.read_log(paths))[seen:])
        if block == B.QUOTA.value:
            self.note_quota(stop)
        return self.end(row, O(outcome), block, stop_reason=code, stop_detail=detail)

    def tick(self, paths):
        """While a member runs: the heartbeat; `waiting-for-quota` is shown while its last log line is a wait."""
        try:
            last = None
            for last in store.read_log(paths):
                pass
            waiting = last is not None and last.get("event") == codes.LogEvent.WAIT.value
            want = S.WAITING_FOR_QUOTA if waiting else S.RUNNING
            if self.s["state"] != want.value:
                self.s["state"] = want.value
                self.save()
        except UNREADABLE + (OSError,):
            pass                                            # a line being written; the next tick sees it
        self.beat()

    # -- the end --
    def finish(self, halt=None):
        if halt is not None:
            self.log(EV.HALT, halt=halt.halt, note=halt.note[:1000] or None)
            self.say(f"halted: {halt.halt} — {halt.note}")
        self.s["ended"] = store.now_ts()
        self.s["state"], self.s["halt"] = (S.FINISHED.value, None) if halt is None else (S.HALTED.value, halt.halt)
        self.save()
        counts = {}
        for r in self.s["members"]:
            key = r["outcome"] or "not-started"
            counts[key] = counts.get(key, 0) + 1
        self.log(EV.SPRINT_END, state=self.s["state"], halt=self.s["halt"], data={"counts": counts})
        self.say(f"sprint {self.s['state']}: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())))
        if halt is None or halt.halt != H.OTHER_HOST.value:
            self.beat(force=True)
        return EXIT_OK if halt is None else EXIT_REFUSED

    def go(self):
        try:
            try:
                self.prepare()
                self.check()
                self.boundary()
                self.base_check()
                self.check()
                self.set_state(S.RUNNING)
                for issue in self.s["order"]:
                    self.check()
                    if not self.quota_waits():           # nothing more starts in this run: no reason to wait
                        self.wait_window()
                    self.member(issue)
                self.check()
            except _Halt as e:
                return self.finish(e)
            return self.finish()
        except _Refused as e:
            self.o.out.write(f"refused: {e}\n")
            return EXIT_REFUSED
        except Exception as e:  # noqa: BLE001 — §2.0: an uncaught exception ends the run, never the member
            tb = traceback.format_exc()
            self.o.out.write(tb)
            if self.s is None:
                return EXIT_REFUSED
            try:
                return self.finish(_Halt(H.ENGINE_ERROR, f"{type(e).__name__}: {e}"))
            except Exception:  # noqa: BLE001
                self.o.out.write("the halt could not be recorded:\n" + traceback.format_exc())
                return EXIT_REFUSED
            finally:
                self.incident(tb, f"{type(e).__name__}: {e}")

    def incident(self, tb, note):
        """Readiness R1: the uncaught exception becomes a defect incident; a failure here changes nothing."""
        try:
            sl = incidents.record_sprint_halt(self.sp, tb, note, plugin_root=self.o.plugin_root, environ=self.o.environ)
            if sl:
                self.say(f"engine incident recorded: {sl}")
        except Exception as e:  # noqa: BLE001
            try:
                self.o.out.write(f"engine incident not recorded: {type(e).__name__}: {e}\n"[:1000])
            except Exception:  # noqa: BLE001
                pass


def run(options, units):
    """`engine.py sprint run` in the foreground (the detached supervisor's body). Exit 0 finished, 3 a lock is
    held, 4 refused / halted."""
    if options.stage < codes.STAGE4:
        options.out.write("refused: a sprint runs from stage 4\n")
        return EXIT_REFUSED
    try:
        r = _Run(options, units)
    except (github.GhError, ValueError) as e:
        options.out.write(f"refused: {e}\n")
        return EXIT_REFUSED
    try:
        lifecycle.acquire_sprint_lock(r.sp)
    except lifecycle.LockHeld as e:
        options.out.write(f"locked: {e}\n")
        return EXIT_LOCKED
    old = {}
    try:
        if threading.current_thread() is threading.main_thread():
            old = {s: signal.signal(s, r.on_signal) for s in (signal.SIGTERM, signal.SIGHUP)}
        return r.go()
    finally:
        for s, h in old.items():
            signal.signal(s, h)
        lifecycle.release_sprint_lock(r.sp)


# --- status, report, check, stop --------------------------------------------------------------------------

def read_rc(sp):
    """The supervisor's exit code from supervisor.rc, or None (none, or still running)."""
    try:
        return int(fsafe.read_bytes(sp.supervisor_rc, root=store._root(sp), max_bytes=64).decode().strip())
    except (FileNotFoundError, ValueError):
        return None


def _member_view(sp, issue):
    """{engine: …} of one member's state.json on this machine (None = none, unreadable → its problem)."""
    paths = pathsmod.EnginePaths(sp.engine_home, sp.repo, issue)
    try:
        state = store.load_state(paths)
    except UNREADABLE as e:
        return paths, None, f"{type(e).__name__}"
    return paths, state, None


def status_report(sp):
    """{running, pid, rc, sprint (sprint.json or None), members [{issue, outcome, block, …, engine}]}."""
    sprint = store.load_sprint(sp)
    holder = lifecycle.sprint_lock_holder(sp)
    running = holder is not None and holder.get("issue") == sp.tracker
    out = {"repo": sp.repo, "tracker": sp.tracker, "records": sp.dir, "running": running,
           "pid": holder.get("pid") if running else None, "rc": read_rc(sp), "sprint": sprint, "members": []}
    for row in (sprint or {}).get("members") or ():
        paths, state, problem = _member_view(sp, row["issue"])
        engine = None
        if state is not None:
            stop = state.get("stop")
            current = next((s["id"] for s in state["steps"] if s["status"] not in DONE_STATUSES), None)
            lock = lifecycle.lock_holder(paths)
            engine = {"finished": finished(state), "closed": bool(state.get("closed")), "step": current,
                      "running": lock is not None and lock.get("issue") == row["issue"],
                      "stop": None if not stop else {k: stop.get(k) for k in ("status", "reason", "detail", "step")}}
        out["members"].append(dict(row, engine=engine, engine_problem=problem))
    try:                                         # readiness R1: what daily shows under "엔진 결함 의심", as it is
        out["incidents"], out["incidents_problem"] = incidents.summaries(sp.engine_home), None
    except (ValueError, OSError, fsafe.UnsafePath) as e:
        out["incidents"], out["incidents_problem"] = [], f"{type(e).__name__}: {e}"[:300]
    return out


def _status_text(rep):
    s = rep["sprint"]
    lines = [f"Sprint {rep['repo']}#{rep['tracker']}"]
    if s is None:
        lines.append("- supervisor running" if rep["running"] else "- not run on this machine")
    else:
        head = f"- run {s['run']}: {s['state']}" + (f" ({s['halt']})" if s["halt"] else "")
        if rep["running"]:
            head += f" — supervisor running (pid {rep['pid']})"
        elif s["state"] not in codes.SPRINT_ENDED:
            head += " — the supervisor died; `sprint run` again continues from the facts"
        lines.append(head)
        lines.append(f"- started {s['started']}" + (f", ended {s['ended']}" if s["ended"] else "")
                     + (f", window {s['window']}" if s["window"] else ""))
        if s["base_check"] is not None:
            lines.append(f"- base {s['base_check']['sha'][:12]}: {'green' if s['base_check']['ok'] else 'red'}"
                         + (" (allowed)" if s["allow_red_base"] else ""))
        for m in rep["members"]:
            e = m["engine"] or {}
            what = m["outcome"] or ("running" if e.get("running") else "waiting")
            if m["block"]:
                what += f" ({m['block']}" + (f" by #{m['cause']}" if m["cause"] else "") + ")"
            if m["stop_reason"]:
                what += f" — {m['stop_reason']}" + (f" / {m['stop_detail']}" if m["stop_detail"] else "")
            elif e.get("stop"):
                what += f" — stopped: {e['stop']['reason']}"
            elif e.get("running") and e.get("step"):
                what += f" — step {e['step']}"
            lines.append(f"  #{m['issue']:<6} {what}" + (f"  PR {m['pr']}" if m["pr"] else "") + (" (draft)" if m["draft"] else "")
                         + (f"  ${m['cost_usd']:.2f}" if m["cost_usd"] is not None else ""))
    inc = rep.get("incidents") or []
    if inc:
        kinds = {k: sum(1 for i in inc if i.get("kind") == k) for k in incidents.KINDS}
        lines.append(f"- engine incidents: {len(inc)} (defect {kinds['defect']} · suspect {kinds['suspect']}) — "
                     "engine.py incidents list")
    lines.append(f"- records: {rep['records']}")
    return "\n".join(lines) + "\n"


def status(sp, out, as_json=False):
    """`engine.py sprint status`: sprint.json + the members' states. Exit code."""
    rep = status_report(sp)
    out.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n" if as_json else _status_text(rep))
    if rep["running"]:
        return EXIT_OK
    if rep["rc"] in (EXIT_LOCKED, EXIT_REFUSED):
        return rep["rc"]                       # also a later start that was refused before it recorded anything
    s = rep["sprint"]                          # an exit 0 alone proves nothing (a wrapper may lose the real code)
    return EXIT_OK if s is None or s["state"] == S.FINISHED.value else EXIT_REFUSED


def _folder_bytes(path):
    try:
        p = subprocess.run(["du", "-sk", path], capture_output=True, text=True, timeout=300,
                           env={"PATH": "/bin:/usr/bin", "LC_ALL": "C"})
        return int(p.stdout.split()[0]) * 1024
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def _facts_files(paths):
    """Every facts.json of the Issue (attempts and leader calls), sorted."""
    out = []
    for d, dirs, names in os.walk(paths.issue_dir):
        dirs[:] = sorted(x for x in dirs if not os.path.islink(os.path.join(d, x)))
        if "facts.json" in names:
            out.append(os.path.join(d, "facts.json"))
    return sorted(out)


def report_object(sp):
    """`sprint report --json` (the retro's and evolve's input, §2.1): None when the sprint was not run here."""
    sprint = store.load_sprint(sp)
    if sprint is None:
        return None
    members, causes, total = [], {c: 0 for c in codes.StopCause.values()}, 0.0
    for row in sprint["members"]:
        paths, state, problem = _member_view(sp, row["issue"])
        stop, work = (state or {}).get("stop"), ((state or {}).get("git") or {}).get("work_tree")
        kept = work if work and os.path.isdir(work) else None
        proc = ((state or {}).get("procedure") or {}).get("path")
        reason = row["stop_reason"] or (stop or {}).get("reason")
        cause = codes.stop_cause(reason) if reason else None
        if cause:
            causes[cause] += 1
        total += row["cost_usd"] or 0.0
        members.append(dict(row, state_problem=problem, stop=None if not stop else {
            "status": stop["status"], "reason": stop["reason"], "detail": stop.get("detail"), "step": stop.get("step"),
            "at": stop.get("at"), "cause": codes.stop_cause(stop["reason"])}, stop_cause=cause, leader_calls=[
                {k: c.get(k) for k in ("situation", "answer", "step", "reason", "failed", "cost_usd")}
                for c in (state or {}).get("leader_calls") or ()],
            paths={"records": paths.issue_dir, "log": paths.log, "state": paths.state,
                   "procedure": os.path.join(kept, proc) if kept and proc else None, "facts": _facts_files(paths)},
            worktree=None if kept is None else {"path": kept, "bytes": _folder_bytes(kept)}))
    counts = {}
    for r in sprint["members"]:
        counts[r["outcome"] or "not-started"] = counts.get(r["outcome"] or "not-started", 0) + 1
    return {"repo": sp.repo, "tracker": sp.tracker, "sprint": {k: v for k, v in sprint.items() if k != "members"},
            "log": sp.log, "counts": counts, "cost_usd": round(total, 6), "stop_causes": causes, "members": members}


def report(sp, out, as_json=True):
    """`engine.py sprint report --json`: per member outcome, cost, stop (codes.stop_cause), leader decisions, the paths of
    its procedure, log and facts, the kept worktrees. Exit code."""
    obj = report_object(sp)
    if obj is None:
        out.write("refused: this sprint was not run on this machine\n")
        return EXIT_REFUSED
    out.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return EXIT_OK


def _has_engine_record(home, repo, issue):
    """This machine's engine has a state.json of the Issue (an unreadable one counts: it is the engine's)."""
    paths = pathsmod.EnginePaths(home, repo, issue)
    if not os.path.lexists(paths.state):
        return False                                     # looked at without creating the engine home (a read)
    try:
        return store.load_state(paths) is not None
    except (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath):
        return True


def member_blocks(gh, issues, home):
    """Readiness T1 P7: what `run` would do to members before it starts them — [(issue, blocking, text)].
    Blocking: an epic (unsupported-epic); without engine records here, an open pull request on any branch that closes
    it (open-closing-pr), its gld/<N> left on the remote (remote-branch-exists) or guild:done on the open Issue
    (done-unconfirmed). Not blocking: a child of an epic (it runs alone). A closed member is the run's own case.
    Reads: each member's Issue, one pull-request list, one engine-branch list. GhError when GitHub does not answer."""
    closing, branches = github.open_closing_map(gh), set(sprinttracker.engine_branches(gh))
    out = []
    for issue in issues:
        facts = sprinttracker.issue_facts(gh, issue)
        if facts["state"] == "CLOSED":
            continue
        has = lambda name: github.has_label(facts, name)                                  # noqa: E731
        if has(github.EPIC_LABEL):
            out.append((issue, True, f"an epic ({github.EPIC_LABEL}) — run blocks it ({B.UNSUPPORTED_EPIC.value}): "
                                     "plan its children instead"))
        if has(github.CHILD_LABEL):
            out.append((issue, False, f"a child of an epic ({github.CHILD_LABEL}) — it runs as a single Issue"))
        if home is None or _has_engine_record(home, gh.repo, issue):
            continue
        prs = closing.get(issue)
        if prs:
            out.append((issue, True, "open pull request " + ", ".join(f"#{p['number']} ({p['head']})" for p in prs)
                        + f" closes it — run refuses it ({codes.StopReason.OPEN_CLOSING_PR.value})"))
        if issue in branches:
            out.append((issue, True, f"{sprinttracker.BRANCH_PREFIX}{issue} is on the remote without engine records "
                                     f"here — run blocks it ({B.REMOTE_BRANCH_EXISTS.value})"))
        if has(github.DONE_LABEL) and not prs:
            out.append((issue, True, f"{github.DONE_LABEL} on the open Issue — run refuses it "
                                     f"({codes.StopReason.DONE_UNCONFIRMED.value})"))
    return out


def check(gh, tracker, out, home=None):
    """`engine.py sprint check`: member table, hash, order — no write. Exit 0 / 4.
    Readiness T1 P7: also what `run` would block or refuse among the members (member_blocks; `home` = this machine's
    engine home, whose records make an open pull request / a remote branch a member's own) — one of them → exit 4."""
    try:
        t = sprinttracker.read(gh, tracker)
        members = sprintdag.parse_table(t.body)
        order, warnings = sprintdag.order(members)
        stored, now = sprintdag.stored_plan_hash(t.body), sprintdag.plan_hash(t.body)
        blocks = member_blocks(gh, order, home)
    except (github.GhError, sprintdag.SprintTableError) as e:
        out.write(f"refused: {e}\n")
        return EXIT_REFUSED
    by = {m.issue: m for m in members}
    out.write(f"sprint {gh.repo}#{tracker}: {len(members)} members, plan-hash {now}, "
              f"stack reason {sprintdag.stack_reason_token(t.body) or '—'}\n")
    for w in warnings:
        out.write(f"warning: {w}\n")
    for n, issue in enumerate(order, 1):
        m = by[issue]
        out.write(f"  {n}. #{issue}" + (f" on #{m.base_dep}" if m.base_dep else "") + (f" [{m.kind}]" if m.kind else "") + "\n")
    for issue, blocking, text in blocks:
        out.write(f"{'blocked' if blocking else 'note'}: #{issue}: {text}\n")
    if stored != now:
        out.write(f"refused: plan-hash mismatch (the tracker says {stored or 'nothing'})\n")
        return EXIT_REFUSED
    if any(blocking for _, blocking, _ in blocks):
        out.write("refused: members the run would not start — plan the sprint again without them "
                  "(/gld sprint plan)\n")
        return EXIT_REFUSED
    return EXIT_OK


def stop(sp, out):
    """`engine.py sprint stop`: TERM to the live supervisor (members run to their end). Exit code."""
    holder = lifecycle.sprint_lock_holder(sp)
    if holder is None or holder.get("issue") != sp.tracker or not isinstance(holder.get("pid"), int):
        out.write("refused: no supervisor of this sprint is running on this machine\n")
        return EXIT_REFUSED
    os.kill(holder["pid"], signal.SIGTERM)
    out.write(f"stop asked (pid {holder['pid']}): a waiting supervisor ends within {defaults.SPRINT_POLL_S} s, a running "
              "member is finished first\n")
    return EXIT_OK
