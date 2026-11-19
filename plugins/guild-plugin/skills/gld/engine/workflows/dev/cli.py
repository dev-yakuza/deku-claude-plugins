"""workflows.dev.cli — `gld_engine.py dev <sub>` (design §2.4, §2.5 answer/note, §2.7 restart, §10.3, §10.5).

    dev run --issue N [--attended|--unattended] [--detach] [--only STAGE]
    dev wait --issue N --max-seconds S
    dev answer --issue N --qid D<k> --choice TOKEN [--text …]
    dev note --issue N --text "…" [--stage STAGE]
    dev hold --issue N
    dev valve set KEY VALUE | clear KEY | halt [--now] [--all] | resume [--all] | show
    dev unattended-log --issue N
    dev cost [--by role|who|model|tier|local|arm|kind|stage|endpoint] [--issue N]
    dev health [--first-sprint] [--sprint T]
    dev grade --sprint T [--import CSV] [--out DIR] [--grader [--pass 2]]

`run` (every mode) before any stage: the kill switch (`HALT` → exit 6 `halted: kill-switch`), the ACTIVE
plugin version (§10.3: mismatch → exit 6 `halted: plugin version mismatch`; none listed → exit 6
`halted: env plugin-not-listed` unless `GLD_ENGINE_DEV=1`; CLI unavailable → warning, run goes on), the
config-dir registry entry, the per-Issue lock (busy → exit 4; `--unattended --detach` attaches to an
unattended owner; an attended owner is never attached by a driver — one progress line, exit 0), the
restart check (§2.7: reap journaled process groups, `verify_pending`; an unknown create → `env: service`
pause; a not-landed write is left to the stage that re-derives it — never re-sent from the journal). The
same kill-switch / version / `hold` / budget checks run again before every stage (`Driver.boundary`).

Unattended stdout = machine events ONLY (§2.4): one synthetic `rate_limit_event` then the `result` line.
Progress goes to `<git-common-dir>/guild/engine/<N>/progress.log`; this process's own stderr never says
"rate limit" (the supervisor fence scans wide text). Exit codes: 0 terminal · 3 gh auth · 4 busy · 6
halted · 75 rate limit · 1 crash (126/127 come from the interpreter shim).
Attended: `run --attended` starts a detached worker (`--worker`) that writes `events.jsonl`; `wait` returns
on an `ask` or `terminal` event; `answer` records the person's choice (the driver then runs again).
"""

import argparse
import json
import os
import sys
import time

from guildcore import emit
from guildcore import journal as J
from guildcore import valves as VALVES
from guildcore import version as VERSION
from guildcore import worker as W

EXIT_BUSY = 4
EXIT_HALT = 6
STAGES = ("analyze", "design", "execute", "test", "qa")


# ---- the live dependencies (tests inject fakes through `Deps`) ------------------------------------------

class Deps(object):
    """What `dev` needs from the outside. Every attribute is a factory so tests can replace one."""

    def __init__(self, env=None, cwd=None, out=None, err=None):
        self.env = dict(os.environ if env is None else env)
        self.cwd = cwd or os.getcwd()
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self.version_runner = None             # guildcore.version runner (tests)
        self.sleep = time.sleep
        self.spawn = W.start_detached
        self.driver_cls = None                  # tests: a fake Driver class
        self.ports_for = None                   # tests: a ready `ports_for`
        self.grader_judge = None                # tests: a fake judge for `dev grade --grader` (no model call)
        self._ports = None                      # the run's `ports_for` (the boundary's budget ask writes through it)

    # git
    def toplevel(self):
        from guildcore.adapters import git as G
        out = G.run(self.cwd, "rev-parse", "--show-toplevel", check=False).decode().strip()
        if not out:
            raise RuntimeError("not inside a git repository")
        return out

    def common(self):
        from workflows.status.running import git_common_dir
        return git_common_dir(self.cwd)

    def push_url(self, main):
        from guildcore.adapters import git as G
        return G.run(main, "remote", "get-url", "--push", "origin", check=False).decode().strip() or None

    def clock(self):
        from guildcore.adapters.clock import Clock
        return Clock()

    def _fixture(self):
        """Tests and the local smoke only: `GLD_ENGINE_TEST=1` + `GLD_ENGINE_GH_FIXTURE=<json>` serve a FILE-backed
        fake GitHub (written back at the end of the command) — never honoured outside the test switch."""
        if self.env.get("GLD_ENGINE_TEST") == "1" and self.env.get("GLD_ENGINE_GH_FIXTURE"):
            if getattr(self, "_fake", None) is None:
                from guildcore.adapters.gh import FakeGh
                self._fake = FakeGh(self.env["GLD_ENGINE_GH_FIXTURE"])
            return self._fake
        return None

    def save(self):
        fake = getattr(self, "_fake", None)
        if fake is not None:
            J.atomic_write(self.env["GLD_ENGINE_GH_FIXTURE"], json.dumps(fake.fx, ensure_ascii=False, indent=1))

    def gh(self):
        fake = self._fixture()
        if fake is not None:
            return fake
        from guildcore.adapters.gh import GhCli
        return GhCli(self.env.get("GLD_REPO") or None)

    def gh_write(self, repo):
        fake = self._fixture()
        if fake is not None:
            from guildcore.adapters.gh import FakeGhWrite
            return FakeGhWrite(fake, self.clock())
        from guildcore.adapters.gh import GhWriteCli
        return GhWriteCli(repo)

    def config(self, main):
        from guildcore import config as CF
        try:
            return CF.load(main) if CF.exists(main) else None
        except CF.ConfigError:
            return None

    def runners(self, common, journal, halt_check, version, config=None):
        """The role and judge runners. A non-default model endpoint is allowed only when the repository lists it in
        `config.engine.allowed_endpoints` (§5.1 — a local-model offload or the local smoke)."""
        from guildcore.judges.runner import JudgeRunner
        from guildcore.roles.runner import Runner
        eng = ((getattr(config, "raw", None) or {}).get("engine") or {}) if config is not None else {}
        allowed = list(eng.get("allowed_endpoints") or [])
        r = Runner(journal=journal, common_dir=common, parent_env=self.env, halt_check=halt_check, version=version,
                   clock=self.clock(), allowed_endpoints=allowed)
        jr = JudgeRunner(journal=journal, common_dir=common, parent_env=self.env, halt_check=halt_check,
                         version=version, allowed_endpoints=allowed)
        return r, jr

    def driver(self, ports_for, unattended, plugin, events, boundary):
        from workflows.dev.fsm import Driver
        cls = self.driver_cls or Driver
        return cls(ports_for, unattended=unattended, plugin=plugin, events=events, boundary=boundary)


def _sent(d, obj):
    emit.engine(obj, out=d.out)


def _progress(common, n, line, now=None):
    """A human progress line → the side file only (never stdout, never this process's stderr)."""
    now = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    J.fsync_append(os.path.join(J.issue_dir(common, n), "progress.log"), "%s %s" % (now, emit.safe_stderr(line)))


# ---- preflight: kill switch, active version, registry ----------------------------------------------------

class Stop(object):
    def __init__(self, code, line, halted=None):
        self.code, self.line, self.halted = code, line, halted


def version_gate(d, main):
    """None (go on) | Stop. `GLD_ENGINE_SKIP_VERSION=1` is honoured only under `GLD_ENGINE_TEST=1`."""
    if d.env.get("GLD_ENGINE_TEST") == "1" and d.env.get("GLD_ENGINE_SKIP_VERSION") == "1":
        return None, "unchecked (test)"
    mine = VERSION.own_version()
    st, detail = VERSION.check(mine, main, d.env, runner=d.version_runner, sleep=d.sleep)
    if st == "ok":
        return None, detail
    if st == "dev":
        return None, "unlisted (dev)"
    if st == "unavailable":
        return None, "unknown (version-check-unavailable: %s)" % emit.safe_stderr(detail or "")[:120]
    if st == "mismatch":
        return Stop(EXIT_HALT, "halted: plugin version mismatch — %s" % detail, "plugin-version-changed"), detail
    return Stop(EXIT_HALT, "halted: env plugin-not-listed — %s" % detail, "engine-env-plugin-not-listed"), detail


def kill_switch(common):
    return Stop(EXIT_HALT, "halted: kill-switch", "engine-kill-switch") if VALVES.halted(common) else None


# ---- the boundary check (every stage) ----------------------------------------------------------------------

def make_boundary(d, common, main, attended, events, budget, issue_top):
    from workflows.dev.fsm import Outcome
    from workflows.dev.stages import base as B
    state = {"warned": False}

    def boundary(n):
        k = kill_switch(common)
        if k is not None:
            return Outcome(None, k.code, k.line, halted=k.halted)
        stop, _v = version_gate(d, main)                # §10.3 R5C-m1: at every stage boundary
        if stop is not None:
            return Outcome(None, stop.code, stop.line, halted=stop.halted)
        if attended and events is not None and events.hold_requested():
            events.clear_hold()
            # K5r1-M2: a hold is never DONE — a parent driving children stops here (no next child, no integration)
            line = "held at a step boundary — /gld resume %d" % issue_top
            return Outcome(B.StageResult(B.StageResult.HOLD, line=line), 0, line)
        if budget:
            return budget_boundary(d, common, issue_top, float(budget), attended, state)
        return None
    return boundary


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def budget_ceiling(p, base):
    """(ceiling, stopped) from the decision log: the committed budget raised by every recorded `continue`
    (`point: budget`, `choice: raise`, `budget_to`), and whether a `stop` was recorded AT that ceiling."""
    from guildcore.decisions import DecisionLog
    from workflows.dev.stages import base as B
    blocks = [b for b in DecisionLog.load(B.records(p)).blocks if b.get("point") == "budget" and b.get("by") == "code"]
    ceiling = max([base] + [_f(b.get("budget_to"), base) for b in blocks if b.get("choice") == "raise"])
    stopped = any(b.get("choice") == "stop" and abs(_f(b.get("budget_at"), -1) - ceiling) < 0.005 for b in blocks)
    return ceiling, stopped


def apply_budget_answer(p, base):
    """K5r1-M3: a member's answer to the `budget` question is ACTED on, once (`point: applied`):
    `continue` → the ceiling is raised by `config.engine.budget_increment_usd` (default: the committed
    budget) — a `point: budget` block `budget_from → budget_to` with who answered, also journaled;
    `stop` → a `point: budget` `stop` block at that ceiling (the run holds; never asked again for it)."""
    from workflows.dev.stages import base as B
    from guildcore.decisions import ENGINE_SCOPE
    q, res = B.pending_answer(p, ENGINE_SCOPE, "budget")
    if res is None:
        return
    cur, _stopped = budget_ceiling(p, base)
    who = res.get("answered_by") or "human"
    if res.get("choice") == "continue":
        inc = _f(p.engine_cfg("budget_increment_usd", None), None) or base
        to = round(cur + inc, 2)
        B.record_code(p, "engine", "budget", "raise", reason="budget raised by %s's answer" % who, refs=res.id,
                      extra={"budget_from": "%.2f" % cur, "budget_to": "%.2f" % to, "answered_by": who})
        if p.journal is not None:
            p.journal.append("event", what="budget-raise", budget_from=cur, budget_to=to, answer=res.id, by=who)
    elif res.get("choice") == "stop":
        B.record_code(p, "engine", "budget", "stop", reason="budget stop answered by %s" % who, refs=res.id,
                      extra={"budget_at": "%.2f" % cur, "answered_by": who})
    B.mark_applied(p, "engine", res)


def budget_boundary(d, common, top, base, attended, state):
    """§4.2 per-Issue budget at a step boundary: 80% → one progress line; ≥ the ceiling → the `budget`
    question ONCE per ceiling (attended ask / unattended pause). The ceiling is the committed budget plus
    every answered `continue`; a `stop` answer holds at that ceiling (K5r1-M3)."""
    from guildcore import cost as COST
    st, spent = COST.budget_guard(common, top, base)
    if st == "ok":
        return None                         # under 80% of the committed budget: no raise can matter
    p = d._ports(top, None)
    apply_budget_answer(p, base)
    ceiling, stopped = budget_ceiling(p, base)
    st, spent = COST.budget_guard(common, top, ceiling)
    if st == "warn" and not state["warned"]:
        state["warned"] = True
        _progress(common, top, "budget: $%.2f of $%.2f spent on #%d (80%%)" % (spent, ceiling, top))
    if st != "over":
        return None
    return budget_stop(d, p, top, spent, ceiling, attended, stopped)


def _budget_hold(p, line, attended):
    """Stop without a new question: attended → HOLD; unattended → `guild:needs-human` stays (a pause comment
    only when the label is not on yet), so the supervisor counts the member paused."""
    from workflows.dev.fsm import Outcome
    from workflows.dev.stages import base as B
    if attended:
        return Outcome(B.StageResult(B.StageResult.HOLD, line=line), 0, line)
    from guildcore import state as ST
    if B.NEEDS_HUMAN in ST.label_names(p.gh.issue(p.issue).get("labels")):
        return Outcome(B.StageResult(B.StageResult.PAUSE, cause="env: other — %s" % line), 0)
    return Outcome(B.pause(p, "engine", "env", line, "env: other — %s" % line, env_key="other"), 0)


def budget_stop(d, p, n, spent, budget, attended, stopped=False):
    """§4.2: the per-Issue budget reached → attended `ask budget`, unattended pause `budget` — once per
    ceiling (`refs: budget:<ceiling>`); an unanswered earlier question for the same ceiling is asked again
    under ITS id (attended) or left waiting (unattended), never a new D-id; a `stop` holds."""
    from guildcore import ask as ASK
    from guildcore.decisions import ENGINE_SCOPE, DecisionLog
    from workflows.dev.fsm import Outcome
    from workflows.dev.stages import base as B
    line = "Issue budget reached — $%.2f of $%.2f (config.engine.budget_usd_per_issue)" % (spent, budget)
    if stopped:
        return _budget_hold(p, "%s — a person answered stop at this ceiling; raise "
                               "config.engine.budget_usd_per_issue to go on" % line, attended)
    ref = "budget:%.2f" % budget
    log = DecisionLog.load(B.records(p))
    # K5r2-M1: only an UNRESOLVED question for this ceiling is asked again under its id / waited on; one a person
    # resolved by removing guild:needs-human without an answer (§2.5 rule 3, `superseded … re-judge`) is asked anew
    done = log.resolved_ids()
    prior = [b for b in log.blocks if b.get("kind") == "budget" and b.get("status") == "pending-human"
             and b.get("refs") == ref and b.id not in done]
    if prior:
        blk = prior[-1]
        if attended and p.events is not None:
            q = ASK.Question("budget", blk.get("question") or line, [{"token": t, "label": t} for t in blk.options()])
            p.events.emit("ask", p.now(), **q.event(blk.id, p.issue))
            return Outcome(B.StageResult(B.StageResult.ASK, line=line, qid=blk.id), 0)
        return _budget_hold(p, "%s — question %s for this ceiling is still unanswered (guild-answer: %s continue|stop)"
                            % (line, blk.id, blk.id), attended)
    q = ASK.Question("budget", line, [{"token": "continue", "label": "raise the budget and continue"},
                                      {"token": "stop", "label": "stop"}], refs=ref)
    r = B.ask(p, ENGINE_SCOPE, q, line, {"cause_kind": "env", "line": line, "token_cause": "budget — %s" % line,
                                     "env_key": "other"})
    return Outcome(r, 0)


# ---- the restart check (§2.7) ------------------------------------------------------------------------------

def restart_check(d, p, n, reap=True, lock_child=None, common=None):
    """Reap the journal's process groups of a CRASHED run, then verify every intent-only write of #n (and of
    the children its journal created). Returns None or a StageResult (an unknown create → `env: service`,
    attended FAIL). A write that did not land is closed `redo` — the stage that made it re-derives it from
    GitHub; nothing is re-sent from the journal (K4r4-m1, K4r5-m4).
    K5r1-M1: the caller holds #n's lock; a child's journal is touched only while `lock_child(m)` holds THAT
    child's lock — a child another run holds is skipped (its own run verifies it), and its processes are never
    killed. `reap_journaled(crashed_only)` also requires the group's journaled owner to be dead.
    K5r1-M4: a GitHub read/write error here is classified like the FSM's: auth / rate limit re-raise (exit 3 /
    75), transient / unknown → `env: service`, else `defect:`."""
    from guildcore.adapters.gh import GhError, GhWriteError, classify_error
    from guildcore.journal import Journal
    from workflows.dev.stages import base as B
    nums = [n] + sorted(set(int(e["number"]) for e in p.writer._ij().own_issues() if e.get("number") is not None))
    for m in nums:
        lock = None
        if m != n and lock_child is not None:
            lock, holder = lock_child(m)
            if lock is None:
                if common is not None:
                    _progress(common, n, "restart check: child #%d is held by an %s run — left to that run"
                              % (m, (holder or {}).get("mode") or "unknown"))
                continue
        try:
            j = (getattr(p.writer, "journal", None) or p.journal) if m == n else None
            j = j if j is not None else Journal(p.git_dir, m, p.clock)
            if reap and j is not None:
                try:
                    W.reap_journaled(j, crashed_only=True)
                except Exception:                                    # noqa: BLE001 — a reap never blocks the run
                    pass
            w = p.writer if m == n else _writer_for(p, j)
            try:
                redo = j.verify_pending(w.verify_intent)
            except (GhWriteError, GhError) as ex:
                kind = ex.kind if isinstance(ex, GhWriteError) else classify_error(str(ex))
                if kind in ("auth", "ratelimit"):
                    raise
                line = "restart check #%d — %s" % (m, B.one_line(str(ex), 260))
                if kind == "ambiguous":
                    return B.unknown_create(p, "engine", line, ex)
                return B.fail(p, "engine", line, "transient" if kind in ("transient", "unknown") else "defect")
            for it in redo:
                j.done(it, redo=True)
        finally:
            if lock is not None:
                lock.release()
    return None


def _writer_for(p, journal):
    from guildcore.records.write import GhWriter
    return GhWriter(p.gh, p.writer.write, journal=journal, clock=p.clock)


# ---- run -----------------------------------------------------------------------------------------------------

class Run(object):
    def __init__(self, d, a):
        self.d, self.a = d, a
        self.n = int(a.issue)
        self.attended = bool(a.attended)
        self.main = d.toplevel()
        self.common = d.common()
        self.events = W.Events(self.common, self.n)

    def finish(self, outcome, cost0=0.0):
        """Unattended: the §2.4 stdout contract, and (K5r1-M5) a `terminal` event too, so `dev wait` and an
        attach see how a detached or foreground unattended run ended. Attended worker: a terminal event (none
        after an ask — the ask event is the driver's cue)."""
        from guildcore import cost as COST
        from workflows.dev.fsm import final_events
        usd = max(0.0, COST.spent(self.common, self.n, kind=None) - cost0)
        self.d.save()
        _progress(self.common, self.n, "end: exit %d — %s" % (outcome.exit_code, outcome.line))
        res = outcome.result
        if not self.attended or res is None or res.kind != "ASK":
            self.events.emit("terminal", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), issue=self.n,
                             exit_code=outcome.exit_code, line=emit.one_line(outcome.line),
                             token=res.token() if res is not None else None, cost_usd=round(usd, 6),
                             halted=outcome.halted, mode="attended" if self.attended else "unattended",
                             notes=[emit.one_line(x) for x in (res.notes if res is not None else [])][:4])
        if not self.attended:
            final_events(outcome, usd, out=self.d.out)
        return outcome.exit_code

    def stop(self, s):
        from workflows.dev.fsm import Outcome
        return self.finish(Outcome(None, s.code, s.line, halted=s.halted))

    def go(self):
        a, d = self.a, self.d
        if self.attended and not a.worker:
            return self.start_attended()
        if not self.attended and a.detach and not a.worker:
            return self.start_unattended_detached()
        k = kill_switch(self.common)
        if k is not None:
            return self.stop(k)
        vstop, vlabel = version_gate(d, self.main)
        if vstop is not None:
            return self.stop(vstop)
        if vlabel and vlabel.startswith("unknown"):
            _progress(self.common, self.n, "warning: version-check-unavailable — version: unknown")
        VALVES.register(self.common, d.env)
        lk = W.IssueLock(self.common, self.n)
        try:
            lk.acquire(self.mode())
        except W.Busy as b:
            return self.busy(b.holder)
        try:
            return self.drive(vlabel)
        finally:
            lk.release()

    def mode(self):
        return "attended" if self.attended else "unattended"

    def child_lock(self, c):
        """K5r1-M1: the lock a parent takes on a child before driving it or touching its journal."""
        lk = W.IssueLock(self.common, c)
        try:
            lk.acquire(self.mode(), driven_by=self.n)
        except W.Busy as b:
            return None, b.holder
        return lk, None

    def busy(self, holder):
        from workflows.dev.fsm import Outcome
        mode = (holder or {}).get("mode")
        return self.finish(Outcome(None, EXIT_BUSY, "busy: #%d is held by an %s run" % (self.n, mode or "unknown")))

    def _pass_args(self):
        return (["--only", self.a.only] if self.a.only else []) + \
            (["--expect-type", self.a.expect_type] if getattr(self.a, "expect_type", None) else [])

    def _fresh_cursor(self):
        """m7: a new driver never takes an earlier run's unconsumed `terminal` for its own."""
        evs = self.events.read()
        self.events.set_cursor(evs[-1]["seq"] if evs else 0)

    def _await_lock(self, lk):
        """The spawned worker takes the lock itself; wait (≤ ~10 s) until it holds it, so a `dev wait` right
        after this call never mistakes a worker that is still starting for a dead one."""
        for _ in range(40):
            if lk.held_by_other():
                return True
            self.d.sleep(0.25)
        return lk.held_by_other()

    def start_unattended_detached(self):
        """K5r1-M5 — `--unattended --detach` (an old 0.101.x supervisor's `/gld dev` session): start a DETACHED
        unattended worker and return at once with the §2.4 lines; the driver then waits with `dev wait` (the
        worker writes a `terminal` event). The lock is the worker's: a second `--detach` (e.g. after the session's
        60-min Bash timeout) finds it held and only reports it — it never starts a second writer, and no restart
        check runs against a live run."""
        from workflows.dev.fsm import Outcome, final_events
        lk = W.IssueLock(self.common, self.n)
        if lk.held_by_other():
            info = lk.holder() or {}
            mode = info.get("mode") or "unknown"
            line = ("#%d is running %s (pid %s) — not started again; wait with `dev wait --issue %d`"
                    % (self.n, mode, info.get("pid"), self.n))
            _progress(self.common, self.n, line)
            final_events(Outcome(None, 0, line), 0.0, out=self.d.out)
            return 0
        self._fresh_cursor()
        argv = [W.python(), os.path.join(_engine_dir(), "gld_engine.py"), "dev", "run", "--issue", str(self.n),
                "--unattended", "--worker"] + self._pass_args()
        log = os.path.join(J.issue_dir(self.common, self.n), "worker.log")
        pid = self.d.spawn(argv, self.main, self.d.env, log)
        held = self._await_lock(lk)
        line = "started a detached unattended run of #%d (pid %s%s) — wait with `dev wait --issue %d`" % (
            self.n, pid, "" if held else ", lock not seen yet", self.n)
        _progress(self.common, self.n, line)
        final_events(Outcome(None, 0, line), 0.0, out=self.d.out)
        return 0

    def start_attended(self):
        lk = W.IssueLock(self.common, self.n)
        if lk.held_by_other():
            try:
                info, ro = W.attach(self.common, self.n, want_control=True)
                msg = {"attached": True, "mode": info.get("mode"), "read_only": ro, "issue": self.n}
                if info.get("driven_by") is not None:
                    # K5r2-m4: the parent's run drives this child — its asks / terminal arrive on the PARENT's events
                    msg["driven_by"] = info["driven_by"]
                    # K5r3-M2: its questions are issue-qualified there (`#<child>/D<n>`) and answered on the child
                    par = info["driven_by"]
                    msg["hint"] = ("#%d is driven by #%d's run — wait / hold / note on #%d; #%d's questions arrive "
                                   "there as `#%d/D<n>` — answer them with `dev answer --issue %d --qid #%d/D<n>`"
                                   % (self.n, par, par, self.n, self.n, self.n, self.n))
                _sent(self.d, msg)
                return 0
            except LookupError:
                pass
        self._fresh_cursor()
        argv = [W.python(), os.path.join(_engine_dir(), "gld_engine.py"), "dev", "run", "--issue", str(self.n),
                "--attended", "--worker"] + self._pass_args()
        log = os.path.join(J.issue_dir(self.common, self.n), "worker.log")
        pid = self.d.spawn(argv, self.main, self.d.env, log)
        self._await_lock(lk)
        _sent(self.d, {"started": True, "pid": pid, "issue": self.n, "log": log})
        return 0

    def ports_for(self, vlabel):
        d = self.d
        if d.ports_for is not None:
            return d.ports_for
        from guildcore.journal import Journal
        from workflows.dev import ports as PO
        gh = d.gh()
        repo = gh.owner_repo()
        clock = d.clock()
        halt_check = lambda: VALVES.halted(self.common)          # noqa: E731
        cfg = d.config(self.main)
        self.run_journal = Journal(self.common, self.n, clock)
        runner, jr = d.runners(self.common, self.run_journal, halt_check, vlabel, cfg)
        return PO.fsm_factory(self.main, cfg, clock, gh, d.gh_write(repo), runner, jr,
                              unattended=not self.attended, push_url=d.push_url(self.main), plugin=vlabel,
                              env=d.env, events=self.events if self.attended else None,
                              valves=VALVES.effective(self.common, d.env))

    def pending_retry(self):
        """Decision 2: an earlier unattended run ended on an unknown create with `retry_at` still ahead → the
        same exit 75 again without touching GitHub (a supervisor that woke early never doubles the pause)."""
        if self.attended:
            return None
        j = J.Journal(self.common, self.n)
        at = [e.get("at") for e in j.entries if e.get("kind") == "event" and e.get("what") == "retry-after"]
        if at and int(at[-1] or 0) > int(time.time()):
            from workflows.dev.fsm import retry_outcome
            return retry_outcome(None, int(at[-1]))
        return None

    def drive(self, vlabel):
        """K5r1-M4: setup (`ports_for` — `gh repo view` …) and the restart check run under the SAME §2.4 end
        mapping as the FSM (`fsm.end_of`): auth → 3, rate limit → 75, transient / unknown → `env: service`
        pause, anything else → `defect:` pause; exit 1 only when even that pause cannot be written."""
        from guildcore import cost as COST
        from workflows.dev import fsm as F
        d = self.d
        cost0 = COST.spent(self.common, self.n, kind=None)
        early = self.pending_retry()
        if early is not None:
            return self.finish(early, cost0)
        holder = {"ports_for": None}
        try:
            ports_for = self.ports_for(vlabel)
            holder["ports_for"] = ports_for
            d._ports = ports_for
            _progress(self.common, self.n, "start: %s run #%d (plugin %s)" % (self.mode(), self.n, vlabel))
            p0 = ports_for(self.n, None)
            want = getattr(self.a, "expect_type", None)
            if want:
                from guildcore import state as ST
                from workflows.dev.stages import base as B
                if "type:%s" % want not in ST.label_names(p0.gh.issue(self.n).get("labels")):
                    line = ("#%d has no `type:%s` label — /gld %s runs only on it (add the label, or use /gld implement)"
                            % (self.n, want, "debug" if want == "bug" else "refactor"))
                    return self.finish(F.Outcome(B.StageResult(B.StageResult.FAIL, line=line, fail_class="prevalidate"), 0), cost0)
            stop = restart_check(d, p0, self.n, lock_child=self.child_lock, common=self.common)
            if stop is not None:
                out = F.Outcome(stop, 0)
                if not self.attended and getattr(stop, "retry_at", None):
                    out = F.retry_outcome(stop, stop.retry_at)
                return self.finish(self._note_retry(out), cost0)
            kept = self.clear_retry(p0)
            if kept is not None:
                return self.finish(kept, cost0)
            budget = p0.engine_cfg("budget_usd_per_issue", None)
        except Exception as ex:                                   # noqa: BLE001 — §2.4: every end has a result line
            drv0 = F.Driver(holder["ports_for"], unattended=not self.attended)
            out = drv0.retry_after(F.end_of(ex, lambda reason, cls: drv0._defect(self.n, reason, cls)))
            return self.finish(self._note_retry(out), cost0)
        boundary = make_boundary(d, self.common, self.main, self.attended, self.events, budget, self.n)
        drv = d.driver(ports_for, not self.attended, vlabel, self.events if self.attended else None, boundary)
        drv.child_lock = self.child_lock
        if getattr(self, "run_journal", None) is None:          # injected ports (tests): the ports' journal
            self.run_journal = getattr(ports_for(self.n, None), "journal", None)
        drv.on_active = self.mirror_pids
        out = drv.run(self.n, self.a.only)
        return self.finish(self._note_retry(out), cost0)

    def mirror_pids(self, n):
        """K5r2-m1: while the parent drives child #n, every role / judge pid record also lands in J<n> (the
        child's own journal) — the child's restart check (under ITS lock) then sees a crashed parent's orphan."""
        j = getattr(self, "run_journal", None)
        if j is None:
            return
        j.pid_mirror = None if (n is None or int(n) == self.n) else J.Journal(self.common, int(n), j.clock)

    def clear_retry(self, p0):
        """Decision 2: the supervisor's own resume after `retry_at` — the restart check has just settled the
        unknown create (found → recorded, absent → never landed, created again by its stage) — takes back the
        `guild:needs-human` that pause put on, once (`retry-cleared`)."""
        if self.attended:
            return None
        j = J.Journal(self.common, self.n)
        ev = [e for e in j.entries if e.get("kind") == "event" and e.get("what") in ("retry-after", "retry-cleared")]
        if not ev or ev[-1].get("what") != "retry-after":
            return None
        from guildcore import state as ST
        from workflows.dev.fsm import Outcome
        from workflows.dev.stages import base as B
        if B.NEEDS_HUMAN in ST.label_names(p0.gh.issue(self.n).get("labels")):
            # K5r2-m7: take back ONLY the engine's own label — the LAST `labeled guild:needs-human` must be a write the
            # engine journaled (server event id); a person who put it back (or a label nobody can attribute) keeps it
            adds = [ev for ev in (p0.gh.timeline(self.n) or []) if ev.get("event") == "labeled"
                    and ((ev.get("label") or {}).get("name") if isinstance(ev.get("label"), dict) else ev.get("label"))
                    == B.NEEDS_HUMAN]
            if not adds or adds[-1].get("id") is None or adds[-1].get("id") not in set(j.own_label_writes()):
                j.append("event", what="retry-cleared", kept="needs-human")
                line = ("guild:needs-human was put on by someone other than the engine during the settle wait — "
                        "left to them (the unknown create is re-checked when they remove it)")
                _progress(self.common, self.n, line)
                return Outcome(B.StageResult(B.StageResult.PAUSE, cause=line), 0)
            p0.writer.labels_apply(self.n, remove=[B.NEEDS_HUMAN])
        j.append("event", what="retry-cleared")
        _progress(self.common, self.n, "auto-resume after the unknown create's settle time — needs-human taken back")
        return None

    def _note_retry(self, out):
        at = getattr(out, "retry_at", None)
        if at:
            J.Journal(self.common, self.n).append("event", what="retry-after", at=int(at))
        return out


def _engine_dir():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


# ---- wait / answer / note / hold -------------------------------------------------------------------------------

def cmd_wait(d, a):
    common = d.common()
    ev = W.Events(common, int(a.issue))
    evs = ev.wait(float(a.max_seconds), sleep=d.sleep)
    lk = W.IssueLock(common, int(a.issue))
    if not any(e.get("type") in ("ask", "terminal") for e in evs) and not lk.held_by_other():
        evs.append({"type": "terminal", "exit_code": 1, "line": "the worker is not running and left no terminal "
                    "event — see %s" % os.path.join(J.issue_dir(common, int(a.issue)), "worker.log")})
    _sent(d, {"issue": int(a.issue), "events": evs})
    return 0


def _ports_for_issue(d, n, attended=True):
    if d.ports_for is not None:
        return d.ports_for(n, None)
    from guildcore.adapters.gh import GhCli
    from guildcore.decisions import DecisionWriter
    from guildcore.journal import Journal
    from guildcore.records.write import GhWriter
    from workflows.dev.stages.base import Ports
    common = d.common()
    gh = d.gh()
    clock = d.clock()
    j = Journal(common, n, clock)
    w = GhWriter(gh, d.gh_write(gh.owner_repo()), journal=j, clock=clock)
    main = d.toplevel()
    return Ports(n, gh, w, DecisionWriter(w, n, clock), clock, d.config(main), main, unattended=not attended,
                 journal=j, git_dir=common)


def _child_of_bare(common, n, bare):
    """K5r3-M2: the Issue whose question a bare `D<k>` answered on #n's driver most recently asked — #n's own, or a
    child #n's attended run drove (its ask arrived on #n's event stream)."""
    from guildcore import ask as ASK
    for e in reversed(W.Events(common, n).read()):
        if e.get("type") != "ask":
            continue
        try:
            qi, b = ASK.parse_qid(e.get("qid"))
        except ValueError:
            continue
        qi = e.get("issue") if e.get("issue") is not None else qi
        if b == bare:
            return int(qi) if qi is not None else n
    return n


LOCK_POLL_S = 2.0


def cmd_answer(d, a):
    """`dev answer --issue N --qid <qid>`. K5r3-M2: `qid` is issue-qualified as the ask event gave it (`#8/D2`) —
    a child's question asked on its parent's driver is answered on the CHILD (routed, `routed_to`); a bare `D<k>`
    that #N's driver last saw as a child's question is refused with a hint naming the child — it never lands on a
    question of #N with the same number."""
    from guildcore import ask as ASK
    try:
        qi, bare = ASK.parse_qid(a.qid)
    except ValueError as e:
        _sent(d, {"answered": False, "error": str(e)})
        return 64
    n = int(a.issue)
    if qi is None:
        owner = _child_of_bare(d.common(), n, bare)
        if owner != n:
            _sent(d, {"answered": False, "child": owner,
                      "error": "%s on #%d's driver is child #%d's question — answer it with "
                               "`dev answer --issue %d --qid #%d/%s`" % (bare, n, owner, owner, owner, bare)})
            return 64
    target = qi if qi is not None else n
    # K5r4-m3 (r1-M1 "only the lock holder writes that Issue"): the answer writes the target's decision log, labels
    # and journal epoch — so it holds the target's IssueLock while it does; a live run holding it (an unattended
    # run, a parent driving it, a worker not yet ended) → busy, nothing written
    lk = W.IssueLock(d.common(), target)
    polls = int(max(0.0, float(getattr(a, "wait_lock", 0.0) or 0.0)) // LOCK_POLL_S)
    while True:
        try:
            lk.acquire("attended")
            busy = None
            break
        except W.Busy as b:
            busy = b
            if polls <= 0:                   # K5r5-m1: poll the LOCK, never the event stream (no ask comes again)
                break
            polls -= 1
            d.sleep(LOCK_POLL_S)
    if busy is not None:
        b = busy
        info = b.holder or {}
        why = ("#%d is driven by #%d's run" % (target, info["driven_by"]) if info.get("driven_by") is not None
               else "an %s run holds #%d" % (info.get("mode") or "engine", target))
        _sent(d, {"answered": False, "busy": True,
                  "error": "%s — answer once it stops (`dev answer … --wait-lock 120`)" % why})
        return EXIT_BUSY
    try:
        p = _ports_for_issue(d, target)
        login = None
        try:
            login = p.gh.viewer_login() if hasattr(p.gh, "viewer_login") else None
        except Exception:                                            # noqa: BLE001
            login = None
        try:
            did = ASK.answer(p.decisions, p.writer, p.issue, bare, a.choice, journal=p.journal, login=login,
                             text=a.text)
        except ValueError as e:
            _sent(d, {"answered": False, "error": str(e)})
            return 64
        d.save()
    finally:
        lk.release()
    out = {"answered": True, "qid": ASK.qualify(target, bare), "issue": target, "resolution": did,
           "choice": a.choice}
    if target != n:
        out["routed_to"] = target
    try:                                    # K6 predict-first: the recommendation is revealed only now, after the answer
        res = p.decisions._log().by_id(did)
        if res is not None and res.get("recommended") is not None:
            out["revealed"] = {"recommended": res.get("recommended"), "recommended_by": res.get("recommended_by")}
            if res.get("revealed_question"):                 # K5r5-M1: the judge's withheld text, now
                out["revealed"]["question"] = res.get("revealed_question")
    except Exception:                       # noqa: BLE001 — the answer landed; the reveal line is a courtesy
        pass
    _sent(d, out)
    return 0


def cmd_note(d, a):
    """§2.6: an attended directive → a `by: human`, `point: directive` block (redacted); the stages read it at
    their next boundary (`ports.directives_of` → every judge brief of that stage). Refused on an unattended-owned
    run (read-only attach, R2C-n6)."""
    from guildcore.records import markers
    common = d.common()
    n = int(a.issue)
    try:
        _info, ro = W.attach(common, n, want_control=True)
        if ro:
            _sent(d, {"noted": False, "error": "an unattended run owns #%d — notes are attended only" % n})
            return EXIT_BUSY
    except LookupError:
        pass
    p = _ports_for_issue(d, n)
    did = p.decisions.record({"point": "directive", "by": "human", "stage": a.stage,
                              "reason": markers.value(a.text)[:2000]})
    d.save()
    _sent(d, {"noted": True, "id": did})
    return 0


def cmd_hold(d, a):
    common = d.common()
    n = int(a.issue)
    try:
        _info, ro = W.attach(common, n, want_control=True)
    except LookupError:
        _sent(d, {"held": False, "error": "no running worker for #%d" % n})
        return 0
    if ro:
        why = ("#%d is driven by #%d's run — hold #%d" % (n, _info["driven_by"], _info["driven_by"])
               if _info.get("driven_by") is not None else "an unattended run owns #%d — hold is attended only" % n)
        _sent(d, {"held": False, "error": why})
        return EXIT_BUSY
    W.Events(common, n).request_hold()
    _sent(d, {"held": True, "issue": n})
    return 0


# ---- valve ---------------------------------------------------------------------------------------------------

def _who(d):
    return d.env.get("GLD_VALVE_WHO") or d.env.get("USER") or "human"


def _targets(d, all_repos):
    if not all_repos:
        return [(d.common(), True)]
    return VALVES.registered(d.env)


def kill_now(common):
    """`halt --now`: every journaled process group still alive gets the §2.7 safe kill (start time + session
    checked; unrelated processes untouched). Local jobs are not killed (local_dev.py has no stop)."""
    from guildcore.journal import Journal
    out = []
    edir = J.engine_dir(common)
    try:
        names = sorted(os.listdir(edir))
    except OSError:
        return out
    for nm in names:
        if nm.isdigit() and os.path.isdir(os.path.join(edir, nm)):
            out += [(int(nm), pg, r) for pg, r in W.reap_journaled(Journal(common, int(nm)), crashed_only=False)]
    return out


def cmd_valve(d, a):
    who = _who(d)
    if a.op == "show":
        common = d.common()
        _sent(d, {"halted": VALVES.halted(common), "overrides": VALVES.load(common),
                  "effective": VALVES.effective(common, d.env)})
        return 0
    if a.op in ("set", "clear"):
        common = d.common()
        try:
            if a.op == "set":
                VALVES.human_set(common, a.key, VALVES.parse_value(a.value), who, a.reason or "")
            else:
                VALVES.human_clear(common, a.key, who, a.reason or "")
        except VALVES.ValveError as e:
            _sent(d, {"ok": False, "error": str(e)})
            return 64
        _sent(d, {"ok": True, "op": a.op, "key": a.key, "effective": VALVES.effective(common, d.env)})
        return 0
    rep = []
    for common, exists in _targets(d, a.all):
        if not exists:
            rep.append({"repo": common, "skipped": "missing"})
            continue
        if a.op == "halt":
            VALVES.halt(common, who, a.reason or "")
            killed = kill_now(common) if a.now else []
            rep.append({"repo": common, "halted": True, "killed": [[n, pg, r] for n, pg, r in killed]})
        else:
            rep.append({"repo": common, "resumed": VALVES.resume(common, who, a.reason or "")})
    _sent(d, {"op": a.op, "repos": rep})
    return 0


# ---- unattended-log / cost ---------------------------------------------------------------------------------------

def cmd_unattended_log(d, a):
    from workflows.dev import unattended_log as UL
    p = _ports_for_issue(d, int(a.issue), attended=False)
    from workflows.dev.stages import base as B
    d.out.write(UL.render(B.records(p)))
    return 0


def cmd_cost(d, a):
    from guildcore import cost as COST
    common = d.common()
    try:
        rows = COST.summary(common, by=a.by, issue=int(a.issue) if a.issue else None)
    except ValueError as e:
        _sent(d, {"error": str(e)})
        return 64
    _sent(d, {"by": a.by, "rows": [{"key": k, "n": n, "usd": u} for k, n, u in rows],
              "total_usd": round(sum(u for _k, _n, u in rows), 6)})
    return 0


def cmd_health(d, a):
    from workflows.dev import health as H
    return H.main(d, a)


def cmd_grade(d, a):
    from workflows.dev import grade as G
    return G.main(d, a)


# ---- argv ----------------------------------------------------------------------------------------------------

def parser():
    ap = argparse.ArgumentParser(prog="gld_engine.py dev")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--issue", required=True, type=int)
    m = r.add_mutually_exclusive_group()
    m.add_argument("--attended", action="store_true")
    m.add_argument("--unattended", action="store_true")
    r.add_argument("--detach", action="store_true")
    r.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    r.add_argument("--only", choices=STAGES)
    r.add_argument("--expect-type", choices=("bug", "refactor"))     # K5r1-m8: /gld debug|refactor
    w = sub.add_parser("wait")
    w.add_argument("--issue", required=True, type=int)
    w.add_argument("--max-seconds", type=float, default=540)
    an = sub.add_parser("answer")
    an.add_argument("--issue", required=True, type=int)
    an.add_argument("--qid", required=True)
    an.add_argument("--choice", required=True)
    an.add_argument("--text")
    # K5r5-m1: a busy Issue (the worker still ending, a parent driving it) — poll its lock this long, then answer
    an.add_argument("--wait-lock", type=float, default=0.0, dest="wait_lock")
    no = sub.add_parser("note")
    no.add_argument("--issue", required=True, type=int)
    no.add_argument("--text", required=True)
    no.add_argument("--stage", choices=STAGES)
    ho = sub.add_parser("hold")
    ho.add_argument("--issue", required=True, type=int)
    v = sub.add_parser("valve")
    v.add_argument("op", choices=("set", "clear", "halt", "resume", "show"))
    v.add_argument("key", nargs="?")
    v.add_argument("value", nargs="?")
    v.add_argument("--now", action="store_true")
    v.add_argument("--all", action="store_true")
    v.add_argument("--reason")
    ul = sub.add_parser("unattended-log")
    ul.add_argument("--issue", required=True, type=int)
    c = sub.add_parser("cost")
    c.add_argument("--by", default="who")
    c.add_argument("--issue", type=int)
    he = sub.add_parser("health")
    he.add_argument("--first-sprint", action="store_true")
    he.add_argument("--sprint", type=int)
    he.add_argument("--issues")
    g = sub.add_parser("grade")
    g.add_argument("--sprint", type=int)
    g.add_argument("--issues")
    g.add_argument("--import", dest="import_csv")
    g.add_argument("--out")
    g.add_argument("--grader", action="store_true")              # §9.5 the 2-call grader (K5r4)
    g.add_argument("--pass", dest="pass_no", type=int, choices=(1, 2), default=1)
    return ap


def _test_guard(d):
    """Under GLD_ENGINE_TEST=1 the engine must never read or write a real config dir (~/.claude*): no isolated
    CLAUDE_CONFIG_DIR → refused before any version check, registry write or GitHub call."""
    return test_guard(d.env)


def test_guard(env):
    """K5r1-m6: shared by `dev`, `version --active` and `status … --all-repos` (gld_engine.py)."""
    if env.get("GLD_ENGINE_TEST") != "1":
        return None
    from guildcore.adapters.claude import isolated_config_dir
    if not isolated_config_dir(env.get("CLAUDE_CONFIG_DIR") or ""):
        return "GLD_ENGINE_TEST=1 needs an isolated CLAUDE_CONFIG_DIR (never ~/.claude*)"
    return None


def main(argv, deps=None):
    d = deps or Deps()
    bad = _test_guard(d)
    if bad:
        _sent(d, {"error": bad})
        return 64
    a = parser().parse_args(argv)
    if a.cmd is None:
        parser().print_help(d.err)
        return 64
    if a.cmd == "run":
        if a.attended and a.detach:
            _sent(d, {"error": "--detach is the old supervisor's unattended path (§10.3)"})
            return 64
        if not a.attended and not a.unattended:
            a.unattended = True                      # §2.4: run defaults to the unattended foreground
        return Run(d, a).go()
    if a.cmd == "valve" and a.op in ("set",) and (a.key is None or a.value is None):
        _sent(d, {"error": "valve set KEY VALUE"})
        return 64
    if a.cmd == "valve" and a.op == "clear" and a.key is None:
        _sent(d, {"error": "valve clear KEY"})
        return 64
    fn = {"wait": cmd_wait, "answer": cmd_answer, "note": cmd_note, "hold": cmd_hold, "valve": cmd_valve,
          "unattended-log": cmd_unattended_log, "cost": cmd_cost, "health": cmd_health, "grade": cmd_grade}[a.cmd]
    return fn(d, a)
