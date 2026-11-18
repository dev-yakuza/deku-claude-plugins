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
    dev grade --sprint T [--import CSV] [--out DIR]

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
import subprocess
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
        self._ports = None                      # the run's `ports_for` (the boundary's budget ask writes through it)

    # git
    def toplevel(self):
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=self.cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        if out.returncode != 0:
            raise RuntimeError("not inside a git repository")
        return out.stdout.decode().strip()

    def common(self):
        from workflows.status.running import git_common_dir
        return git_common_dir(self.cwd)

    def push_url(self, main):
        p = subprocess.run(["git", "remote", "get-url", "--push", "origin"], cwd=main, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        return p.stdout.decode().strip() or None if p.returncode == 0 else None

    def clock(self):
        from guildcore.adapters.clock import Clock
        return Clock()

    def gh(self):
        from guildcore.adapters.gh import GhCli
        return GhCli(self.env.get("GLD_REPO") or None)

    def gh_write(self, repo):
        from guildcore.adapters.gh import GhWriteCli
        return GhWriteCli(repo)

    def config(self, main):
        from guildcore import config as CF
        try:
            return CF.load(main) if CF.exists(main) else None
        except CF.ConfigError:
            return None

    def runners(self, common, journal, halt_check, version):
        from guildcore.judges.runner import JudgeRunner
        from guildcore.roles.runner import Runner
        r = Runner(journal=journal, common_dir=common, parent_env=self.env, halt_check=halt_check, version=version,
                   clock=self.clock())
        jr = JudgeRunner(journal=journal, common_dir=common, parent_env=self.env, halt_check=halt_check,
                         version=version)
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
            return Outcome(B.StageResult(B.StageResult.DONE, line="held at a step boundary — /gld resume %d" % n),
                           0, "held at a step boundary")
        if budget:
            from guildcore import cost as COST
            st, spent = COST.budget_guard(common, issue_top, budget)
            if st == "warn" and not state["warned"]:
                state["warned"] = True
                _progress(common, issue_top, "budget: $%.2f of $%.2f spent on #%d (80%%)" % (spent, budget, issue_top))
            if st == "over":
                return budget_stop(d, n, spent, budget, attended)
        return None
    return boundary


def budget_stop(d, n, spent, budget, attended):
    """§4.2: the per-Issue budget reached → attended `ask budget`, unattended pause `budget`."""
    from guildcore import ask as ASK
    from workflows.dev.fsm import Outcome
    from workflows.dev.stages import base as B
    p = d._ports(n, None)
    line = "Issue budget reached — $%.2f of $%.2f (config.engine.budget_usd_per_issue)" % (spent, budget)
    q = ASK.Question("budget", line, [{"token": "continue", "label": "raise the budget and continue"},
                                      {"token": "stop", "label": "stop"}])
    r = B.ask(p, "engine", q, line, {"cause_kind": "env", "line": line, "token_cause": "budget — %s" % line,
                                     "env_key": "other"})
    return Outcome(r, 0)


# ---- the restart check (§2.7) ------------------------------------------------------------------------------

def restart_check(d, p, n, reap=True):
    """Reap the journal's live process groups, then verify every intent-only write of #n (and of the children
    its journal created). Returns None or a StageResult (an unknown create → `env: service`, attended FAIL).
    A write that did not land is closed `redo` — the stage that made it re-derives it from GitHub; nothing is
    re-sent from the journal (K4r4-m1, K4r5-m4)."""
    from guildcore.adapters.gh import GhWriteError
    from guildcore.journal import Journal
    from workflows.dev.stages import base as B
    nums = [n] + sorted(set(int(e["number"]) for e in p.writer._ij().own_issues() if e.get("number") is not None))
    for m in nums:
        j = (getattr(p.writer, "journal", None) or p.journal) if m == n else None
        j = j if j is not None else Journal(p.git_dir, m, p.clock)
        if reap and j is not None:
            try:
                W.reap_journaled(j)
            except Exception:                                    # noqa: BLE001 — a reap never blocks the run
                pass
        w = p.writer if m == n else _writer_for(p, j)
        try:
            redo = j.verify_pending(w.verify_intent)
        except GhWriteError as ex:
            if ex.kind in ("auth", "ratelimit"):
                raise
            return B.fail(p, "engine", "restart check #%d — %s" % (m, B.one_line(str(ex), 260)),
                          "transient" if ex.kind in ("transient", "ambiguous") else "defect")
        for it in redo:
            j.done(it, redo=True)
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
        """Unattended: the §2.4 stdout contract. Attended worker: a terminal event (none after an ask — the
        ask event is the driver's cue)."""
        from guildcore import cost as COST
        from workflows.dev.fsm import final_events
        usd = max(0.0, COST.spent(self.common, self.n, kind=None) - cost0)
        _progress(self.common, self.n, "end: exit %d — %s" % (outcome.exit_code, outcome.line))
        if self.attended:
            res = outcome.result
            if res is None or res.kind != "ASK":
                self.events.emit("terminal", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 exit_code=outcome.exit_code, line=emit.one_line(outcome.line),
                                 token=res.token() if res is not None else None, cost_usd=round(usd, 6),
                                 halted=outcome.halted)
        else:
            final_events(outcome, usd, out=self.d.out)
        return outcome.exit_code

    def stop(self, s):
        from workflows.dev.fsm import Outcome
        return self.finish(Outcome(None, s.code, s.line, halted=s.halted))

    def go(self):
        a, d = self.a, self.d
        if self.attended and not a.worker:
            return self.start_attended()
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
            lk.acquire("attended" if self.attended else "unattended")
        except W.Busy as b:
            return self.busy(b.holder)
        try:
            return self.drive(vlabel)
        finally:
            lk.release()

    def busy(self, holder):
        from workflows.dev.fsm import Outcome
        mode = (holder or {}).get("mode")
        if not self.attended and self.a.detach:
            if mode == "unattended":
                return self.attach_wait()
            # R5C-m5: never attach a driver to a person's attended run — one progress line, exit 0
            _progress(self.common, self.n, "attended run in progress — the driver does not attach")
            return self.finish(Outcome(None, 0, "#%d is running attended — not attached" % self.n))
        return self.finish(Outcome(None, EXIT_BUSY, "busy: #%d is held by an %s run" % (self.n, mode or "unknown")))

    def attach_wait(self):
        """`--unattended --detach` (an old supervisor's driver) on an unattended owner: wait for its end."""
        from workflows.dev.fsm import Outcome
        lk = W.IssueLock(self.common, self.n)
        while lk.held_by_other():
            self.d.sleep(5)
        evs = [e for e in self.events.read() if e.get("type") == "terminal"]
        last = evs[-1] if evs else {}
        return self.finish(Outcome(None, int(last.get("exit_code") or 0), last.get("line") or "attached run ended"))

    def start_attended(self):
        lk = W.IssueLock(self.common, self.n)
        if lk.held_by_other():
            try:
                info, ro = W.attach(self.common, self.n, want_control=True)
                _sent(self.d, {"attached": True, "mode": info.get("mode"), "read_only": ro, "issue": self.n})
                return 0
            except LookupError:
                pass
        argv = [W.python(), os.path.join(_engine_dir(), "gld_engine.py"), "dev", "run", "--issue", str(self.n),
                "--attended", "--worker"] + (["--only", self.a.only] if self.a.only else [])
        log = os.path.join(J.issue_dir(self.common, self.n), "worker.log")
        pid = self.d.spawn(argv, self.main, self.d.env, log)
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
        runner, jr = d.runners(self.common, Journal(self.common, self.n, clock), halt_check, vlabel)
        return PO.fsm_factory(self.main, d.config(self.main), clock, gh, d.gh_write(repo), runner, jr,
                              unattended=not self.attended, push_url=d.push_url(self.main), plugin=vlabel,
                              env=d.env, events=self.events if self.attended else None,
                              valves=VALVES.effective(self.common, d.env))

    def drive(self, vlabel):
        from guildcore import cost as COST
        from workflows.dev.fsm import Outcome
        d = self.d
        cost0 = COST.spent(self.common, self.n, kind=None)
        ports_for = self.ports_for(vlabel)
        d._ports = ports_for
        _progress(self.common, self.n, "start: %s run #%d (plugin %s)" % (
            "attended" if self.attended else "unattended", self.n, vlabel))
        p0 = ports_for(self.n, None)
        stop = restart_check(d, p0, self.n)
        if stop is not None:
            return self.finish(Outcome(stop, 0))
        budget = p0.engine_cfg("budget_usd_per_issue", None)
        boundary = make_boundary(d, self.common, self.main, self.attended, self.events, budget, self.n)
        drv = d.driver(ports_for, not self.attended, vlabel, self.events if self.attended else None, boundary)
        out = drv.run(self.n, self.a.only)
        return self.finish(out, cost0)


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


def cmd_answer(d, a):
    from guildcore import ask as ASK
    p = _ports_for_issue(d, int(a.issue))
    login = None
    try:
        login = p.gh.viewer_login() if hasattr(p.gh, "viewer_login") else None
    except Exception:                                            # noqa: BLE001
        login = None
    try:
        did = ASK.answer(p.decisions, p.writer, p.issue, a.qid, a.choice, journal=p.journal, login=login,
                         text=a.text)
    except ValueError as e:
        _sent(d, {"answered": False, "error": str(e)})
        return 64
    _sent(d, {"answered": True, "qid": a.qid, "resolution": did, "choice": a.choice})
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
        _sent(d, {"held": False, "error": "an unattended run owns #%d — hold is attended only" % n})
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
            out += [(int(nm), pg, r) for pg, r in W.reap_journaled(Journal(common, int(nm)))]
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
    d.out.write(UL.render(B.records(p)) if hasattr(UL, "render") else "")
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
    w = sub.add_parser("wait")
    w.add_argument("--issue", required=True, type=int)
    w.add_argument("--max-seconds", type=float, default=540)
    an = sub.add_parser("answer")
    an.add_argument("--issue", required=True, type=int)
    an.add_argument("--qid", required=True)
    an.add_argument("--choice", required=True)
    an.add_argument("--text")
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
    return ap


def _test_guard(d):
    """Under GLD_ENGINE_TEST=1 the engine must never read or write a real config dir (~/.claude*): no isolated
    CLAUDE_CONFIG_DIR → refused before any version check, registry write or GitHub call."""
    if d.env.get("GLD_ENGINE_TEST") != "1":
        return None
    cfg = d.env.get("CLAUDE_CONFIG_DIR") or ""
    home = os.path.realpath(os.path.expanduser("~"))
    real = os.path.realpath(cfg) if cfg else ""
    if not cfg or real == home or os.path.basename(real).startswith(".claude") and os.path.dirname(real) == home:
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
