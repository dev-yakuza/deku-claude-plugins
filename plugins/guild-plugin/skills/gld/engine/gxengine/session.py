"""Role session runner (design §6.2, §7.9, I4 I13) — U6.

Launch: render.render(...) → write settings.json into the attempt folder → spawn
`claude` in its own process group (start_new_session) with cwd = the Issue worktree,
stdin /dev/null, stdout → runs/<step>/<attempt>/stream.jsonl, stderr → stderr.log.

The session's `system/init` is NOT compared with any expected list (FC decision D, 2026-11-28 —
the §7.6 init check and its INIT_MISMATCH stop are gone): a CLI version, account or builtin
plugin the engine has not seen before does not stop a session. The launch flags (render) are
unchanged. The init event still gives the session id and the model that really ran.
Limits: --max-budget-usd reached → session-limit; wall clock or no stream event for
SESSION_NO_OUTPUT_S → the engine kills the whole group → infra (I13). At the end the
whole group is killed either way (§6.2).

Resume: only when developer comes back (on_fail / infra resume), at most
defaults.DEVELOPER_RESUME_MAX times; a model change means a new session (§6.2, §7.9).
The CLI is found as `claude` on PATH (tests put tests/fakes/bin first).

U6 decisions (fail-closed; see the P3-A report):

  * Preconditions, checked BEFORE anything is spawned (SessionError — the driver turns it
    into an engine stop, nothing is paid for):
      - the input is a role render; `docs/specs/<N>/` exists in the worktree as a real
        directory (srt cannot create the parent of a write-denied FILE path, so the
        driver must have made it — P2 session 2);
      - `--max-budget-usd` is exactly defaults.SESSION_MAX_BUDGET_USD[<role kind>] (the role
        name without "/phase"; `budget_key=FORMAT_REPAIR_BUDGET_KEY` for a format repair). A
        role missing there gets no session;
      - the CLI's config dir exists (the CLI logs in with it).
    Stage 3 (E17, E27): the budget table and the resume rule are picked by `stage` /
    ladder.may_resume; stages 1–2 keep theirs.
  * Environment: HOME = `paths["home"]` and CLAUDE_CONFIG_DIR = `paths["claude_config_dir"]`
    (the real config dir — the CLI's own login), whatever the caller's env says; then
    render.render_env scrubs it. A fake home (the canary layout, P2 session 2) is simply a
    `paths["home"]` that is not the user's home. NOTE: render derives the home-secret deny
    list from `paths["home"]`; a fake home for a REAL Issue session would leave the real
    ~/.ssh etc. off the deny list — see the report (contract change request).
  * Limits: `limits = {"wall_clock_s", "no_output_s"}`; missing values come from
    defaults.SESSION_WALL_CLOCK_S / SESSION_NO_OUTPUT_S and, while those are unset (I13
    values are still to be derived from data, Q7), from the PROVISIONAL_* values below. The
    no-output limit is never shorter than the Bash tool's own time limit plus a grace
    period (a long foreground test command produces no stream event while it runs).
  * Budget end: result `subtype == "error_max_budget_usd"` or `terminal_reason` in
    BUDGET_TERMINAL_REASONS or an error result whose cost reached the cap. Measured by the
    P4 real canary (CLI 2.1.323): subtype "error_max_budget_usd", is_error true,
    terminal_reason "budget_exhausted", errors ["Reached maximum budget ($…)"], exit 1. Quota: a `rate_limit_event` with status "rejected" → `quota_reset_at` (its
    `resetsAt`), used by results.py for the infra quota wait (§5.1).
"""

import os
import queue
import re
import shutil
import signal
import stat
import selectors
import subprocess
import threading
import time

from . import codes, defaults, fsafe, ladder, render, streamjson

PROVISIONAL_WALL_CLOCK_S = {codes.RoleClass.WORK.value: 4 * 3600, codes.RoleClass.JUDGE.value: 2 * 3600}
"""I13 wall clock until defaults.SESSION_WALL_CLOCK_S is derived from data (provisional)."""
PROVISIONAL_NO_OUTPUT_S = 15 * 60
"""I13 'N minutes without a stream-json event' until defaults.SESSION_NO_OUTPUT_S is set (provisional)."""
NO_OUTPUT_GRACE_S = 5 * 60
"""Added to BASH_MAX_TIMEOUT_MS: the no-output limit never kills a Bash call that is still allowed to run."""
KILL_GRACE_S = 5.0
EXIT_DRAIN_S = 2.0
"""After the CLI process exits, stdout is drained this long; a stray child that keeps the
pipe open does not keep the session alive (it is killed with the group)."""
VERSION_TIMEOUT_S = 30
_POLL_S = 0.2
_READ_POLL_S = 0.1
"""The stdout reader's wait between checks of its stop flag (bounds the return after the kill)."""
STREAM_CUT_WARNING = ("stream cut: the CLI's stdout was still open {s:g} s after its process group "
                      "was killed (a process outside the group holds it); stream.jsonl ends there")

STREAM_FILE = "stream.jsonl"
STDERR_FILE = "stderr.log"
SETTINGS_FILE = "settings.json"

BUDGET_SUBTYPES = ("error_max_budget_usd",)
BUDGET_TERMINAL_REASONS = ("max_budget_usd", "budget_exhausted")   # the second measured by the P4 canary
_VERSION_RE = re.compile(r"(?<![0-9.])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9.])")
_SESSION_FIELDS = ("exit_code", "end", "structured", "result_event", "stream_file", "stderr_file",
                   "session_id", "cost", "denials", "duration_s", "cli_version", "model", "warnings",
                   "quota_reset_at", "killed")


class SessionError(Exception):
    """A session cannot be started as specified (fail-closed: nothing was spawned)."""


class SessionResult:
    """What one session produced.

    Attributes: exit_code, end (codes.SessionEnd value),
    structured (dict or None), result_event (dict or None), stream_file, stderr_file,
    session_id, cost (streamjson.cost_and_tokens dict), denials, duration_s.

    U6 additions: cli_version, model (the init event's model — the model that really ran),
    warnings (stream lines that were not JSON), quota_reset_at (epoch seconds of a rejected
    rate limit, else None), killed (None, or why the engine killed the group:
    "wall-clock", "no-output", "error").
    """

    def __init__(self, **fields):
        unknown = set(fields) - set(_SESSION_FIELDS)
        if unknown:
            raise TypeError(f"unknown SessionResult fields {sorted(unknown)}")
        end = fields.get("end")
        if end not in codes.SessionEnd.values():
            raise ValueError(f"bad session end {end!r}")
        for k in _SESSION_FIELDS:
            setattr(self, k, fields.get(k))
        self.end = str(end)
        if self.cost is None:
            self.cost = streamjson.cost_and_tokens(None)
        self.denials = list(self.denials or [])
        self.warnings = list(self.warnings or [])

    def __repr__(self):
        return (f"SessionResult(end={self.end!r}, exit_code={self.exit_code!r}, "
                f"structured={'yes' if self.structured is not None else 'no'})")


# --- parameters -------------------------------------------------------------------------

def role_kind(role):
    """The budget key of a role: the role name without a "/phase" suffix (P3-0)."""
    if not isinstance(role, str) or not role:
        raise SessionError(f"bad role {role!r}")
    return role.split("/", 1)[0]


def session_budget(role, budget_key=None, stage=2):
    """`--max-budget-usd` of a session: defaults.session_budget_table(stage)[<role kind>] or
    [budget_key] (FORMAT_REPAIR_BUDGET_KEY). A missing key → SessionError (no default budget)."""
    key = budget_key if budget_key is not None else role_kind(role)
    v = defaults.session_budget_table(stage).get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
        raise SessionError(f"no session budget for {key!r} (defaults.SESSION_MAX_BUDGET_USD) — no session")
    return float(v)


def session_limits(inp, limits=None):
    """{"wall_clock_s", "no_output_s"} for a role render input (I13, see the module docstring)."""
    limits = dict(limits or {})
    unknown = set(limits) - {"wall_clock_s", "no_output_s"}
    if unknown:
        raise SessionError(f"unknown session limits {sorted(unknown)}")
    wall = limits.get("wall_clock_s")
    if wall is None:
        wall = defaults.SESSION_WALL_CLOCK_S.get(role_kind(inp.role))
    if wall is None:
        wall = PROVISIONAL_WALL_CLOCK_S[inp.role_class]
    quiet = limits.get("no_output_s")
    if quiet is None:
        quiet = defaults.SESSION_NO_OUTPUT_S
    if quiet is None:
        quiet = PROVISIONAL_NO_OUTPUT_S
    floor = int(inp.bash_timeout_ms) // 1000 + NO_OUTPUT_GRACE_S
    for name, v in (("wall_clock_s", wall), ("no_output_s", quiet)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
            raise SessionError(f"session limit {name} must be a positive number, got {v!r}")
    return {"wall_clock_s": float(wall), "no_output_s": float(max(quiet, floor))}


def choose_resume(role, step_state, model, previous_model, effort=None, previous_effort=None):
    """The session id a returning developer resumes, or None (§6.2: developer only, at most
    defaults.DEVELOPER_RESUME_MAX times, a model change → a new session). `step_state` is the
    state.json step dict (session_id, resume_count). The caller counts the use.

    Stage 3 (E27): give `effort` and `previous_effort` (both) — ladder.may_resume then decides an
    effort change too. An effort that is known on one side only → a new session."""
    if role != "developer" or not isinstance(step_state, dict):
        return None
    sid = step_state.get("session_id")
    if not sid or step_state.get("resume_count", 0) >= defaults.DEVELOPER_RESUME_MAX:
        return None
    if previous_model is None or model != previous_model:
        return None
    if effort is not None or previous_effort is not None:
        if not ladder.may_resume({"model": previous_model, "effort": previous_effort},
                                 {"model": model, "effort": effort}):
            return None
    return sid


def _resolve_bin(claude_bin, env):
    if os.path.isabs(claude_bin):
        path = claude_bin
    else:
        path = shutil.which(claude_bin, path=env.get("PATH", ""))
        if path is None:
            raise SessionError(f"{claude_bin!r} is not on PATH")
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        raise SessionError(f"{path!r} is not an executable")
    return os.path.abspath(path)


def cli_version(claude_bin="claude", env=None):
    """`claude --version` → "2.1.323" (canary key part, init expectation)."""
    env = dict(os.environ if env is None else env)
    path = _resolve_bin(claude_bin, env)
    try:
        p = subprocess.run([path, "--version"], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=VERSION_TIMEOUT_S, start_new_session=True)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SessionError(f"`{path} --version` failed: {e}") from None
    out = p.stdout.decode("utf-8", "replace")
    m = _VERSION_RE.search(out)
    if p.returncode != 0 or m is None:
        raise SessionError(f"`{path} --version` gave rc={p.returncode} {out.strip()[:200]!r}")
    return m.group(1)


def kill_group(proc):
    """SIGTERM then SIGKILL the process group of `proc` (§6.2 — no stray children)."""
    pgid = proc.pid       # start_new_session=True: the child leads its own group
    # macOS answers EPERM (not ESRCH) for a group whose only member is the zombie leader:
    # nothing signalable is left, so EPERM counts as "gone" (same-user children would be
    # signalable and make killpg succeed).

    def alive():
        try:
            os.killpg(pgid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def signal_group(sig):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    signal_group(signal.SIGTERM)
    deadline = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < deadline:
        if proc.poll() is not None and not alive():
            break
        time.sleep(0.05)
    signal_group(signal.SIGKILL)
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass


# --- launch ----------------------------------------------------------------------------

def _check_specs_dir(inp):
    wt = inp.paths["worktree"]
    rel = defaults.SPECS_DIR.replace("{issue}", str(inp.issue))
    cur = wt
    for part in rel.split("/"):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            raise SessionError(f"{rel}/ does not exist in the worktree — the driver creates it before a "
                               "role starts (srt cannot create the parent of a denied file)") from None
        if not stat.S_ISDIR(st.st_mode):
            raise SessionError(f"{cur!r} is not a real directory")


def _session_env(inp, base_env):
    env = dict(base_env)
    env["HOME"] = inp.paths["home"]
    env["CLAUDE_CONFIG_DIR"] = inp.paths["claude_config_dir"]
    return env


def _reader(rfd, out_fd, q, stop, eof):
    """Copy stdout verbatim into stream.jsonl and signal each line, until end of file (sets
    `eof`) or until `stop` is set.

    Reads the raw fd through a selector with a short timeout (Q6): a buffered `readline`
    held the reader's lock, so closing the pipe object waited for a process outside the
    session's group (setsid) that still held the pipe — the engine did not return."""
    sel = selectors.DefaultSelector()
    pending = b""
    try:
        sel.register(rfd, selectors.EVENT_READ)
        while not stop.is_set():
            if not sel.select(_READ_POLL_S):
                continue
            chunk = os.read(rfd, 1 << 16)
            if not chunk:
                if pending:
                    q.put(("line", pending))
                eof.set()
                return
            view = memoryview(chunk)
            while view:
                n = os.write(out_fd, view)
                view = view[n:]
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()
            for raw in lines:
                q.put(("line", raw + b"\n"))
    except Exception as e:    # surfaced as an error end; the session is killed
        q.put(("error", repr(e)))
    finally:
        sel.close()
        q.put(("eof", None))


def _open_new(path, root):
    """Create `path` (must not exist) without following links; return a write fd."""
    fsafe.check_parents(path, root)
    if os.path.lexists(path):
        raise SessionError(f"{path!r} already exists — an attempt folder is used once")
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)


def run_session(inp, attempt_dir, base_env, claude_bin="claude", limits=None, version=None, budget_key=None,
                stage=2):
    """Render, launch, watch, kill the group, and return a SessionResult (§6.2).

    `version`: the CLI version if the caller already has it (else `claude --version`) — recorded
    (facts `session.cli_version`), never compared with a list of known versions.
    `budget_key`: FORMAT_REPAIR_BUDGET_KEY for a format repair session, else None (the role kind).
    `stage`: which budget table the cap must come from (E17).
    Raises SessionError (nothing spawned) or render.RenderError for a bad input.
    """
    if not isinstance(inp, render.RenderInput) or inp.kind != "role":
        raise SessionError("run_session needs a role RenderInput")
    want = session_budget(inp.role, budget_key, stage)
    if float(inp.max_budget_usd) != want:
        raise SessionError(f"--max-budget-usd {inp.max_budget_usd!r} != the {role_kind(inp.role)!r} budget "
                           f"{want} (defaults.SESSION_MAX_BUDGET_USD)")
    _check_specs_dir(inp)
    if not os.path.isdir(inp.paths["claude_config_dir"]):
        raise SessionError(f"the CLI config dir {inp.paths['claude_config_dir']!r} does not exist")
    attempt_dir = os.path.realpath(attempt_dir)
    if not os.path.isdir(attempt_dir):
        raise SessionError(f"attempt folder {attempt_dir!r} does not exist")
    env0 = _session_env(inp, base_env)
    claude_abs = _resolve_bin(claude_bin, env0)
    lim = session_limits(inp, limits)
    if version is None:
        version = cli_version(claude_abs, env0)

    settings_path = os.path.join(attempt_dir, SETTINGS_FILE)
    stream_path = os.path.join(attempt_dir, STREAM_FILE)
    stderr_path = os.path.join(attempt_dir, STDERR_FILE)
    for p in (settings_path, stream_path, stderr_path):
        if os.path.lexists(p):
            raise SessionError(f"{p!r} already exists — an attempt folder is used once")
    out = render.render(inp, env0, {"claude": claude_abs, "srt": "/nonexistent-srt"},
                        {"settings": settings_path, "srt": os.path.join(attempt_dir, "srt.json")})
    fsafe.write_json(settings_path, out["settings"], root=attempt_dir)
    out_fd = _open_new(stream_path, attempt_dir)
    try:
        err_fd = _open_new(stderr_path, attempt_dir)
    except BaseException:
        os.close(out_fd)
        raise

    t0 = time.monotonic()
    try:
        rfd, wfd = os.pipe()       # both ends non-inheritable (PEP 446); Popen dups wfd onto 1
    except OSError as e:
        os.close(out_fd)
        os.close(err_fd)
        raise SessionError(f"claude could not start: {e}") from None
    try:
        proc = subprocess.Popen(out["argv"], cwd=inp.paths["worktree"], env=out["env"],
                                stdin=subprocess.DEVNULL, stdout=wfd, stderr=err_fd,
                                start_new_session=True, close_fds=True)
    except OSError as e:
        os.close(out_fd)
        os.close(rfd)
        raise SessionError(f"claude could not start: {e}") from None
    finally:
        os.close(err_fd)
        os.close(wfd)              # only the child's copy keeps the write end open

    q = queue.Queue()
    stop_reader, stream_eof = threading.Event(), threading.Event()
    th = threading.Thread(target=_reader, args=(rfd, out_fd, q, stop_reader, stream_eof), daemon=True)
    th.start()
    killed = None
    reader_error = None
    last = time.monotonic()
    eof = False
    exited_at = None
    try:
        while not eof:
            now = time.monotonic()
            if exited_at is None and proc.poll() is not None:
                exited_at = now
            if exited_at is not None and now - exited_at > EXIT_DRAIN_S:
                break         # the CLI exited; a stray child still holds stdout — killed below
            if now - t0 > lim["wall_clock_s"]:
                killed = codes.SessionEnd.WALL_CLOCK.value
                break
            if now - last > lim["no_output_s"]:
                killed = codes.SessionEnd.NO_OUTPUT.value
                break
            try:
                kind, raw = q.get(timeout=_POLL_S)
            except queue.Empty:
                continue
            if kind == "eof":
                eof = True
                continue
            if kind == "error":
                reader_error = raw
                killed = "error"
                break
            last = time.monotonic()
    finally:
        try:
            kill_group(proc)
            th.join(timeout=KILL_GRACE_S)
        finally:
            stop_reader.set()
            th.join()              # the reader sees the stop within _READ_POLL_S (+ one write)
            os.close(rfd)
            os.close(out_fd)
    stream_cut = not stream_eof.is_set()
    duration = time.monotonic() - t0
    rc = proc.returncode

    events = streamjson.read_file(stream_path)
    result =streamjson.result_event(events)
    structured = streamjson.structured_output(result)
    cost = streamjson.cost_and_tokens(result, resumed=bool(inp.resume))     # Z2: this call only
    init_ev = streamjson.first_init(events)
    session_id = None
    for src in (result, init_ev):
        if isinstance(src, dict) and isinstance(src.get("session_id"), str):
            session_id = src["session_id"]
            break
    quota = None
    for e in events:
        if isinstance(e, dict) and e.get("type") == "rate_limit_event":
            info = e.get("rate_limit_info") if isinstance(e.get("rate_limit_info"), dict) else {}
            ra = info.get("resetsAt")
            if info.get("status") == "rejected" and isinstance(ra, (int, float)) and not isinstance(ra, bool):
                quota = ra
    warns = streamjson.warnings(events)
    if reader_error:
        warns.append(f"stream reader failed: {reader_error}")
    elif stream_cut:
        warns.append(STREAM_CUT_WARNING.format(s=KILL_GRACE_S))

    if killed in (codes.SessionEnd.WALL_CLOCK.value, codes.SessionEnd.NO_OUTPUT.value):
        end = killed
    elif killed is not None:
        end = codes.SessionEnd.ERROR.value
    elif _budget_reached(result, inp.max_budget_usd, resumed=bool(inp.resume)):
        end = codes.SessionEnd.BUDGET.value
    elif rc == 0 and isinstance(result, dict) and result.get("is_error") is not True:
        end = codes.SessionEnd.COMPLETED.value
    else:
        end = codes.SessionEnd.ERROR.value
    model = init_ev.get("model") if isinstance(init_ev, dict) and isinstance(init_ev.get("model"), str) else None
    return SessionResult(
        exit_code=rc, end=end, structured=structured, result_event=result,
        stream_file=stream_path, stderr_file=stderr_path, session_id=session_id, cost=cost,
        denials=streamjson.permission_denials(result), duration_s=duration, cli_version=version,
        model=model, warnings=warns, quota_reset_at=quota, killed=killed)


def _budget_reached(result, cap, resumed=False):
    """The CLI's own budget end, or an error whose cost reached `cap`. --max-budget-usd is per call (V18 §6):
    a resumed call compares its own cost (streamjson.call_cost, Z2), never the session's cumulative total."""
    if not isinstance(result, dict):
        return False
    if result.get("subtype") in BUDGET_SUBTYPES or result.get("terminal_reason") in BUDGET_TERMINAL_REASONS:
        return True
    cost = streamjson.call_cost(result, resumed)
    return (result.get("is_error") is True and isinstance(cost, (int, float)) and not isinstance(cost, bool)
            and cost >= float(cap))
