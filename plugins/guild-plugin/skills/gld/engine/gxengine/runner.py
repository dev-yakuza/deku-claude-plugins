"""`run` step executor (design §4 run, §4.4-2, §7.1, §7.10, §7.12 S8, I8) — U9.

A run executes ONLY a named command of the repository settings, in the real Issue
worktree, wrapped in `srt` with the developer's rendered boundary (render.render_srt).
srt itself gets a short TMPDIR (/tmp/gx-<id>); the command gets its TMPDIR inside the
`-c` string (F0). Own process group; the whole group is killed at the end or on timeout.
The engine reads only the exit code (and writes run.log): no output parsing, no test
environment reproduction (§7.1).

After the command: a dirty tree (tracked change or untracked non-ignored file) is
check-failed / run-dirty-tree with the file list; the engine does not revert (§4.4-2).
I8 on failure: once more on the same tree (flaky mark) and once on a fresh worktree of
the recorded base (base-red mark) — neither turns red into green; base red → stop
BASE_RED (needs_human, developer skipped).

Plugin commands (ac-format, ac-coverage, verify-gate) run the plugin-install-path script
under the same srt boundary; verify-gate first builds the read-tree temp tree
(gitops.temp_tree_for_gate) outside srt, allows writes only there, and runs only after
the step's control-file check passed (§2.1, F5).
Toolchain prepare (§7.12 S8, P3-Z decision 4): outside srt only a file copy from a trusted
source into the Guild cache (`sync`); its commands (`flutter precache`) run INSIDE srt.

P3-B decisions (stage 1, fail-closed — the report lists them as interpretations):

  * srt's cwd is a fresh EMPTY folder inside the attempt's run tmp (`srt-cwd-<label>`): srt
    puts its own built-in write denies (.git/hooks, .git/config, .idea, .vscode, shell rc
    names, …) on its whole cwd subtree (measured, session 5), so it may be started neither
    in the worktree nor in the run tmp itself. The `-c` string is
    `export TMPDIR=<run tmp>; cd <worktree> && <command>` (render.render_srt_argv).
  * a run must START on a clean tree (I7) — otherwise RunnerError, the step is not run.
    After the run, a dirty tree OR a moved HEAD (a run that commits) is run-dirty-tree.
  * I8 extras run only for a repository command (`{cmd}`) that ended non-zero or timed out
    on a clean, unmoved tree. Plugin check scripts judge this Issue's own documents, so a
    "base" run of them means nothing: no extras for ac-format / ac-coverage / verify-gate.
  * the base run uses a fresh detached worktree of the RECORDED base SHA (not the
    merge-base), gets the optional `prepare_tree` copy hook (worktree_prepare, the
    driver's), runs the repository's `setup` command first when one exists and the step is
    not `setup` itself (a fresh tree has no dependencies), then the command. A red setup
    there makes the base red. The temporary tree is removed afterwards.
  * outcome precedence (outcome_of): base red → stop base-red · run-dirty-tree ·
    run-timeout · run-nonzero · done. A flaky mark never changes the outcome.
  * verify-gate: the temp tree and its TMPDIR live inside the run tmp; the srt boundary is
    the developer's with `worktree` = the temp tree (the Issue worktree becomes an "other
    worktree": its secrets stay read-denied) and allowWrite narrowed to the temp tree, its
    own git admin dir and its TMPDIR. `control_check(head_sha)` is REQUIRED (the engine's
    cumulative control-file comparison, results.check_control_files); not ok → stop
    control-file, the gate never runs.
  * toolchain prepare (P3-Z): see its section — nothing is executed outside srt.
  * stage 3: the evidence runs and the git-fact runs are the last sections.

Stage 4 (H22, VB6): every REPOSITORY command (a run, its rerun and base run, the evidence runs, `setup`,
a toolchain `cmd`, the mutation and base-check runs) takes the machine-wide flock `heavy_lock` for as long
as it runs — plugin checks, git facts and role sessions never do. The wait is outside the command's time
limit and is facts.run.queue_wait_s. The lock belongs to the engine process: it is gone when that dies.
"""

import contextlib
import fcntl
import os
import re
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import threading
import time

from . import codes, defaults, fsafe, gitops, globs, render, repoconfig
from . import procedure as procedure_mod

LOG_MAIN = "run.log"
LOG_RERUN = "run-rerun.log"
LOG_BASE = "run-base.log"
LOG_BASE_RERUN = "run-base-rerun.log"
LOG_BASE_SETUP = "run-base-setup.log"
LOG_BASE_SETUP_RERUN = "run-base-setup-rerun.log"
SRT_FILE = "srt.json"
SRT_BASE_FILE = "srt-base.json"

SRT_CWD_PREFIX = "srt-cwd-"
GATE_TREE = "gate-tree"
GATE_TMP = "gate-tmp"
BASE_TREE = "base-tree"
BASE_TMP = "base-tmp"

SETUP_COMMAND = "setup"
KILL_GRACE_S = 10
SCRIPTS_REL = "skills/gld/engine/scripts"
PLUGIN_SCRIPTS = {
    codes.PluginCommand.AC_FORMAT.value: "ac_format.py",
    codes.PluginCommand.AC_COVERAGE.value: "ac_coverage.py",
    codes.PluginCommand.VERIFY_GATE.value: "verify_gate.py",
}

_LOG_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class RunnerError(Exception):
    """The run could not be started or finished as specified (unknown command, render refused,
    srt missing, dirty start tree, no control check for verify-gate, git failure around a
    temporary tree …). Never a pass: the driver stops the step (infra / engine-error)."""


class TreeError(RunnerError):
    """A temporary git tree could not be made or read (stage 3 evidence runs: infra fact-collection;
    the I8 base run: a RunnerError like any other)."""


class HeavyQueue:
    """The machine-wide queue of repository commands (H22): `path` = the flock file (paths.heavy_run_lock,
    directly in the engine home), `waited` = the seconds every command of this queue object waited so far.

    run_named takes a path or a HeavyQueue; a step uses one object so its waits add up."""

    def __init__(self, path):
        if not isinstance(path, str) or not os.path.isabs(path):
            raise RunnerError(f"heavy_lock must be an absolute path, got {path!r}")
        self.path = path
        self.waited = 0.0

    @classmethod
    def of(cls, value):
        """None / a HeavyQueue as it is; a path → a new HeavyQueue."""
        return value if value is None or isinstance(value, cls) else cls(value)

    @contextlib.contextmanager
    def hold(self):
        """Wait for the lock (no limit: each holder's command has one), hold it, release it. A lock file that
        cannot be opened or locked → RunnerError (the command is not run)."""
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
        except OSError as e:
            raise RunnerError(f"heavy-run lock {self.path} could not be opened: {e}") from e
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RunnerError(f"heavy-run lock {self.path} is not a regular file")
            start = time.monotonic()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError as e:
                raise RunnerError(f"heavy-run lock {self.path} could not be taken: {e}") from e
            finally:
                self.waited += time.monotonic() - start
            yield
        finally:
            os.close(fd)             # closing the only descriptor releases the flock


class RunResult:
    """exit_code (int|None), timed_out (bool), log_file, duration_s."""

    def __init__(self, exit_code, timed_out, log_file, duration_s):
        if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
            raise ValueError(f"exit_code must be an int or None, got {exit_code!r}")
        self.exit_code = exit_code
        self.timed_out = bool(timed_out)
        self.log_file = log_file
        self.duration_s = duration_s

    @property
    def green(self):
        return self.exit_code == 0 and not self.timed_out

    def to_facts(self):
        """The facts.json `rerun` / `base_run` shape (log file name relative to the attempt folder)."""
        return {"exit_code": self.exit_code, "timed_out": self.timed_out,
                "log_file": os.path.basename(self.log_file)}

    def __repr__(self):
        return f"RunResult(exit_code={self.exit_code!r}, timed_out={self.timed_out}, log={os.path.basename(self.log_file)!r})"


class StepRun:
    """What run_step produced.

    run            facts.json `run` object, or None when the command never started
    outcome        the facts.json `outcome` dict of this attempt (outcome_of)
    end_tree       {"clean", "dirty_files"} of the Issue worktree after everything
    start_head / end_head
    duration_s     wall clock of the main command (measurement fact)
    control_files  verify-gate pre-check result (facts `control_files`) or None
    notes          human-readable lines (flaky, base red, …) for the log / failure summary
    """

    def __init__(self, run, outcome, end_tree, start_head, end_head, duration_s, control_files=None, notes=()):
        self.run = run
        self.outcome = outcome
        self.end_tree = end_tree
        self.start_head = start_head
        self.end_head = end_head
        self.duration_s = duration_s
        self.control_files = control_files
        self.notes = list(notes)

    @property
    def flaky(self):
        return is_flaky(self.run)

    def __repr__(self):
        return f"StepRun(run={self.run!r}, outcome={self.outcome!r})"


# --- small helpers --------------------------------------------------------------------

def _raw_config(config):
    raw = config.raw if isinstance(config, repoconfig.RepoConfig) else config
    if not isinstance(raw, dict):
        raise RunnerError("config: the repository settings (RepoConfig or its dict)")
    return raw


def _repo_config(config):
    if isinstance(config, repoconfig.RepoConfig):
        return config
    try:
        return repoconfig.RepoConfig(config)
    except repoconfig.ConfigError as e:
        raise RunnerError(f"repository settings refused: {e}") from e


def _check_bin(path):
    if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path) \
            or not os.access(path, os.X_OK):
        raise RunnerError(f"srt binary must be an absolute path to an executable, got {path!r}")


def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def _engine_home(paths):
    """The engine home = the parent of engine_records (paths.py layout); the trusted fsafe root."""
    return os.path.dirname(paths["engine_records"])


def _make_dir(path, root):
    """mkdir -p below the trusted `root` without passing through a link (fsafe)."""
    if not _under(path, root):
        raise RunnerError(f"{path} is not under the engine home {root}")
    try:
        fsafe.make_dirs(path, root=root)
    except fsafe.UnsafePath as e:
        raise RunnerError(f"unsafe path while preparing {path}: {e.path} ({e.why})") from e


def _fresh_empty_dir(parent, name, root):
    """A new empty folder `<parent>/<name>` (refused when something already sits there)."""
    _make_dir(parent, root)
    path = os.path.join(parent, name)
    if os.path.lexists(path):
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or os.listdir(path):
            raise RunnerError(f"{path} exists and is not an empty folder — srt must start in an empty one")
        return path
    os.mkdir(path, 0o700)
    return path


def _ensure_srt_tmpdir(path):
    """srt's own short TMPDIR: an existing plain folder of ours, or a new one. → created (bool)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        os.mkdir(path, 0o700)
        return True
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise RunnerError(f"srt TMPDIR {path} exists but is not a folder of this user (a link?)")
    return False


def _open_log(path, records_root):
    """A new log file in the attempt folder (O_EXCL|O_NOFOLLOW — never an existing file / link)."""
    try:
        fsafe.check_parents(path, root=records_root)
        return os.open(path, _LOG_FLAGS, 0o600)
    except FileExistsError as e:
        raise RunnerError(f"log file {path} already exists (an attempt folder is never reused)") from e
    except fsafe.UnsafePath as e:
        raise RunnerError(f"unsafe attempt folder: {e.path} ({e.why})") from e


def kill_group(proc):
    """SIGTERM then SIGKILL the process group of `proc` (§6.2 — no stray children)."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, PermissionError):
                return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass


DRAIN_S = 5.0
"""After the group is killed, the output pipe is drained this long (a child outside the group
that still holds it open does not keep the engine waiting — the copy stops, the log is cut)."""

COPY_POLL_S = 0.1
"""The copier's wait for output between checks of its stop flag (bounds the return after DRAIN_S)."""

OUTPUT_CUT_MARK = ("\n[gld engine] output cut: the run's output pipe was still open {s:g} s after its "
                   "process group ended (a process outside the group holds it); the log ends here.\n")


def _copy_pipe(rfd, fd, stop, eof):
    """Copy the pipe's read end into the log until end of file (sets `eof`) or until `stop` is set.

    Reads the raw fd through a selector with a short timeout, so the copier never blocks
    longer than COPY_POLL_S on a pipe that another process keeps open (Q5: a buffered
    `read1` held the reader's lock, and closing the pipe object then waited for that
    process to end)."""
    sel = selectors.DefaultSelector()
    try:
        sel.register(rfd, selectors.EVENT_READ)
        while not stop.is_set():
            if not sel.select(COPY_POLL_S):
                continue
            chunk = os.read(rfd, 1 << 16)
            if not chunk:
                eof.set()
                return
            view = memoryview(chunk)
            while view:
                view = view[os.write(fd, view):]
    except (OSError, ValueError):
        pass
    finally:
        sel.close()


def _spawn_group(argv, cwd, env, timeout_s, log_path, records_root):
    """Run `argv` in its own process group, stdout+stderr → log. → (exit_code|None, timed_out, seconds).

    The output goes through a PIPE that the engine copies into the log (P3-Z, measured with
    srt 0.0.83 in the base-green re-check): the log lives in the engine records, which the
    run boundary read-denies, and a process whose stdout is a file in a read-denied folder
    cannot even fstat it — node aborts at start-up (`pnpm install`, every JS tool).

    Returns at most DRAIN_S (+ COPY_POLL_S) after the group is killed, also when a process
    outside the group (setsid) still holds the pipe: the copy stops, the log keeps what was
    read so far and ends with OUTPUT_CUT_MARK (Q6). The exit code is the group leader's either way."""
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
        raise RunnerError(f"time limit must be positive seconds, got {timeout_s!r}")
    fd = _open_log(log_path, records_root)
    start = time.monotonic()
    rfd = None
    try:
        rfd, wfd = os.pipe()               # both ends non-inheritable (PEP 446); Popen dups wfd onto 1 and 2
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=wfd,
                                    stderr=wfd, start_new_session=True)
        except OSError as e:
            raise RunnerError(f"could not start {argv[0]}: {e}") from e
        finally:
            os.close(wfd)                  # only the child's copies keep the write end open
        stop, eof = threading.Event(), threading.Event()
        th = threading.Thread(target=_copy_pipe, args=(rfd, fd, stop, eof), daemon=True)
        th.start()
        try:
            rc = proc.wait(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            rc, timed_out = None, True
        finally:
            try:
                kill_group(proc)   # the leader may be gone; its group (background children) is not
                th.join(timeout=DRAIN_S)
            finally:
                stop.set()
                th.join()          # the copier sees `stop` within COPY_POLL_S (+ one write to the log)
        if not eof.is_set():
            data = memoryview(OUTPUT_CUT_MARK.format(s=DRAIN_S).encode())
            try:
                while data:
                    data = data[os.write(fd, data):]
            except OSError:
                pass                       # as for the copy itself: a log write error never fails the run
    finally:
        if rfd is not None:
            os.close(rfd)
        os.close(fd)
    return rc, timed_out, time.monotonic() - start


def _input_fields(inp):
    fields = {k: getattr(inp, k) for k in render.RenderInput.COMMON + render.RenderInput.RUN_FIELDS}
    fields["paths"] = dict(inp.paths)
    fields["config"] = dict(inp.config)
    return fields


def _with(inp, command=None, paths=None):
    """A copy of a run RenderInput with another command and/or paths (validated again)."""
    fields = _input_fields(inp)
    if command is not None:
        fields["command"] = command
    if paths is not None:
        fields["paths"] = paths
    try:
        return render.RenderInput(**fields)
    except render.RenderError as e:
        raise RunnerError(f"render refused the run input: {e}") from e


# --- one srt invocation ----------------------------------------------------------------

def run_named(inp, attempt_dir, base_env, srt_bin, timeout_s, log_name=LOG_MAIN, srt_name=SRT_FILE,
              label="main", narrow_writes=None, heavy_lock=None):
    """Run one named command under srt; return RunResult.

    `heavy_lock` (stage 4, H22): path of the machine-wide flock (or a HeavyQueue) a REPOSITORY command
    waits for before it starts; None = no lock (a plugin check, every earlier stage). The wait is outside
    `timeout_s`.

    `inp` is a run render.RenderInput (command = the named command string). Writes the
    rendered srt settings (`srt_name`) and the merged output (`log_name`) into the attempt
    folder; srt starts in a fresh empty folder `<run_tmp>/srt-cwd-<label>`.
    `narrow_writes` (verify-gate) = the only allowWrite entries kept.
    """
    if not isinstance(inp, render.RenderInput) or inp.kind != "run":
        raise RunnerError("run_named needs a run RenderInput")
    _check_bin(srt_bin)
    records = inp.paths["engine_records"]
    attempt_dir = os.path.normpath(attempt_dir)
    if not _under(attempt_dir, records) or attempt_dir == records:
        raise RunnerError(f"attempt folder {attempt_dir} is not under the engine records {records}")
    srt_path = os.path.join(attempt_dir, srt_name)
    try:
        settings = render.render_srt(inp)
        if narrow_writes is not None:
            keep = list(narrow_writes)
            settings["filesystem"]["allowWrite"] = [p for p in settings["filesystem"]["allowWrite"] if p in keep]
            missing = [p for p in keep if p not in settings["filesystem"]["allowWrite"]]
            if missing:
                raise RunnerError(f"narrowed write roots are not in the rendered boundary: {missing}")
            render.check_srt_settings(settings)
        argv = render.render_srt_argv(inp, srt_bin, srt_path)
        env = render.render_env(inp, base_env)
    except render.RenderError as e:
        raise RunnerError(f"render refused the run: {e}") from e
    home = _engine_home(inp.paths)
    _make_dir(attempt_dir, records)
    try:
        fsafe.write_json(srt_path, settings, root=records)
    except fsafe.UnsafePath as e:
        raise RunnerError(f"unsafe attempt folder: {e.path} ({e.why})") from e
    cwd = _fresh_empty_dir(inp.paths["run_tmp"], SRT_CWD_PREFIX + label, home)
    _make_dir(inp.paths["run_tmp"], home)
    srt_tmp = inp.paths["srt_tmpdir"]
    queue = HeavyQueue.of(heavy_lock)
    with contextlib.nullcontext() if queue is None else queue.hold():
        created = _ensure_srt_tmpdir(srt_tmp)
        try:
            rc, timed_out, secs = _spawn_group(argv, cwd, env, timeout_s, os.path.join(attempt_dir, log_name), records)
        finally:
            if created:
                shutil.rmtree(srt_tmp, ignore_errors=True)
    return RunResult(rc, timed_out, os.path.join(attempt_dir, log_name), round(secs, 3))


_PLUGIN_ARG = re.compile(r"\A(--[a-z]+(-[a-z]+)*|[A-Za-z0-9][A-Za-z0-9,._-]*)\Z")


def plugin_args_for(name, stage, args=()):
    """The extra arguments of a plugin check script: from stage 3 ac-format always gets `--stage`
    (the safety_net field is checked there, E3) and the caller's `args` (E30: `--deferred R3,R5`).
    Any other use of `args`, or a value that is not a plain token → RunnerError."""
    args = list(args)
    ok = name == codes.PluginCommand.AC_FORMAT.value and stage >= 3
    if args and not ok:
        raise RunnerError(f"{name}: plugin arguments are only for ac-format from stage 3")
    for a in args:
        if not isinstance(a, str) or not _PLUGIN_ARG.match(a):
            raise RunnerError(f"{name}: not a plain plugin argument: {a!r}")
    if not ok:
        return []
    return ([] if "--stage" in args else ["--stage", str(stage)]) + args


def plugin_command_line(name, plugin_root, issue, args=()):
    """`python3 -I <plugin root>/skills/gld/engine/scripts/<script> --issue <N> [args]` (interfaces §2.7)."""
    if name not in PLUGIN_SCRIPTS:
        raise RunnerError(f"{name!r} is not a plugin check command ({sorted(PLUGIN_SCRIPTS)})")
    if not isinstance(plugin_root, str) or not os.path.isabs(plugin_root):
        raise RunnerError(f"plugin_root must be an absolute path, got {plugin_root!r}")
    script = os.path.join(plugin_root, SCRIPTS_REL, PLUGIN_SCRIPTS[name])
    if not os.path.isfile(script) or os.path.islink(script):
        raise RunnerError(f"plugin check script missing: {script}")
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
        raise RunnerError(f"bad issue number {issue!r}")
    return " ".join([f"python3 -I {shlex.quote(script)} --issue {issue}"] + [shlex.quote(a) for a in args])


def run_plugin_command(name, inp, attempt_dir, base_env, srt_bin, timeout_s, plugin_root, args=(), **kw):
    """Run a plugin check script (codes.PluginCommand value) under srt; return RunResult.

    The script comes from the plugin install path (never the worktree's copy); the run
    boundary re-opens that path for reading (render allowRead), so `paths.plugin_root` must
    be the same folder. Extra keywords go to run_named (log_name, srt_name, label, narrow_writes).
    """
    if os.path.normpath(plugin_root) != inp.paths["plugin_root"]:
        raise RunnerError("plugin_root differs from the rendered paths.plugin_root (the script would be unreadable)")
    return run_named(_with(inp, command=plugin_command_line(name, plugin_root, inp.issue, args)), attempt_dir,
                     base_env, srt_bin, timeout_s, **kw)


# --- judgment of a run attempt -----------------------------------------------------------

def is_red(r):
    """A facts `run`/`rerun`/`base_run` object (or RunResult) that is not a clean exit 0."""
    if r is None:
        return False
    if isinstance(r, RunResult):
        return not r.green
    return r.get("exit_code") != 0 or bool(r.get("timed_out"))


def is_flaky(run):
    """I8 flaky mark: the main run was red and the same-tree rerun was green."""
    if not run or not run.get("rerun"):
        return False
    return is_red(run) and not is_red(run["rerun"])


def is_base_red(run):
    """I8 base-red mark: the recorded base was red too. An evidence run judges a red (or timed
    out) base twice on the same base tree (K8-2, symmetric to D10): base-red only when both
    were; without a second run the first alone decides."""
    if not run or run.get("base_run") is None or not is_red(run["base_run"]):
        return False
    return run.get("base_rerun") is None or is_red(run["base_rerun"])


def outcome_of(run, end_tree, head_moved=False):
    """The facts.json `outcome` of a run attempt from its facts (I8: never red → green).

    base red → {needs_human, stop base-red} (developer skipped); dirty tree / moved HEAD →
    {failed, check-failed, run-dirty-tree}; timeout → run-timeout; non-zero → run-nonzero;
    else {done}. A plain dict because runner may not import statemachine (same layer, L3):
    the driver turns it into statemachine.Outcome — `stop` set → Outcome("stop", stop=…),
    status failed → Outcome("failed", code=…, detail=…), done → Outcome("done") (to_outcome_args).
    """
    if run is None:
        raise RunnerError("no run facts to judge")
    cf = codes.FailureCode.CHECK_FAILED.value
    if is_base_red(run):
        return _outcome("needs_human", stop=codes.StopReason.BASE_RED.value)
    if head_moved or not end_tree.get("clean", False):
        return _outcome("failed", cf, codes.CheckFailedReason.RUN_DIRTY_TREE.value)
    if run.get("timed_out"):
        return _outcome("failed", cf, codes.CheckFailedReason.RUN_TIMEOUT.value)
    if run.get("exit_code") != 0:
        return _outcome("failed", cf, codes.CheckFailedReason.RUN_NONZERO.value)
    return _outcome("done")


def _outcome(status, code=None, detail=None, stop=None):
    return {"status": status, "code": code, "detail": detail, "stop": stop}


def to_outcome_args(outcome):
    """(args, kwargs) for statemachine.Outcome from an outcome_of dict (the driver's adapter)."""
    if outcome.get("stop"):
        return ("stop",), {"stop": outcome["stop"]}
    if outcome["status"] == "failed":
        return ("failed",), {"code": outcome["code"], "detail": outcome["detail"]}
    if outcome["status"] == "done":
        return ("done",), {}
    raise ValueError(f"not a run outcome: {outcome!r}")


# --- the full step -----------------------------------------------------------------------

def _run_input(config_raw, step_id, attempt, issue, paths, command, timeout_s):
    try:
        return render.RenderInput(kind="run", role="developer", role_class=codes.RoleClass.WORK.value,
                                  step=step_id, attempt=attempt, issue=issue, outputs=[], paths=paths,
                                  config=config_raw, command=command, bash_timeout_ms=int(timeout_s * 1000))
    except render.RenderError as e:
        raise RunnerError(f"render refused the run input: {e}") from e


def _tree(ctx):
    try:
        return gitops.tree_state(ctx)
    except gitops.GitError as e:
        raise RunnerError(f"tree state could not be read: {e}") from e


def _head(ctx):
    try:
        return gitops.head(ctx)
    except gitops.GitError as e:
        raise RunnerError(f"HEAD could not be read: {e}") from e


_SAFE_SEG = re.compile(r"^[A-Za-z0-9._@+-]+$")


def unignored_dirs(tctx):
    """render `paths.worktree_dirs` of a work tree (P3-Z decision 6a): the tree itself and every
    folder holding a tracked or untracked-but-not-ignored file (`git ls-files -co
    --exclude-standard`). A folder whose name render cannot express becomes `<parent>/**`
    (its whole subtree stays denied). New folders a run creates are not listed: a control
    file written there is caught by the cumulative control-file check afterwards."""
    try:
        raw = gitops.git(tctx, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    except gitops.GitError as e:
        raise RunnerError(f"the worktree folders could not be listed: {e}") from e
    root = tctx.work_tree
    out = {root}
    for rel in raw.split("\0"):
        if not rel:
            continue
        cur = root
        for seg in rel.split("/")[:-1]:
            if not _SAFE_SEG.match(seg) or seg in (".", ".."):
                out.add(cur + "/**")
                break
            cur = cur + "/" + seg
            out.add(cur)
    # a folder already covered by an ancestor's `/**` adds nothing
    globbed = [d[:-3] for d in out if d.endswith("/**")]
    return sorted(d for d in out if d.endswith("/**") or not any(_under(d, g) and d != g for g in globbed))


def _with_dirs(paths, tctx):
    p = dict(paths)
    p["worktree_dirs"] = unignored_dirs(tctx)
    return p


def _temp_paths(paths, tctx, issue_worktree, tmp):
    """Render paths for a temporary tree: worktree / own admin dir / TMPDIR replaced, the Issue
    worktree listed as another worktree (its repository secrets stay read-denied)."""
    p = dict(paths)
    p["worktree"] = tctx.work_tree
    p["own_worktree"] = tctx.git_dir
    p["run_tmp"] = tmp
    p["other_worktrees"] = list(paths.get("other_worktrees", [])) + [issue_worktree]
    p.pop("in_dir", None)
    p.pop("worktree_dirs", None)      # recomputed for the temp tree (base run) or the glob kept (gate)
    return p


def _remove_tree(ctx, path, notes):
    try:
        gitops.remove_worktree(ctx, path)
    except gitops.GitError as e:
        notes.append(f"temporary worktree {path} could not be removed: {e}")
        raise RunnerError(f"temporary worktree {path} could not be removed: {e}") from e


def _tree_command(cfg, raw, step_id, attempt, issue, tpaths, name, attempt_dir, base_env, srt_bin, *, log_name,
                  srt_name, label, heavy=None):
    """One named repository command inside a temporary tree (`tpaths` = _temp_paths). → RunResult."""
    c = cfg.command(name)
    inp = _run_input(raw, step_id, attempt, issue, tpaths, c["cmd"], c["timeout_s"])
    return run_named(inp, attempt_dir, base_env, srt_bin, c["timeout_s"], log_name=log_name, srt_name=srt_name,
                     label=label, heavy_lock=heavy)


def _tree_setup(cfg, raw, step_id, attempt, issue, tpaths, attempt_dir, base_env, srt_bin, *, log_name, srt_name,
                label, heavy=None):
    """The repository's `setup` command in a fresh temporary tree (it has no dependencies), or None."""
    if SETUP_COMMAND not in cfg.command_names() or not cfg.command(SETUP_COMMAND)["cmd"]:
        return None
    return _tree_command(cfg, raw, step_id, attempt, issue, tpaths, SETUP_COMMAND, attempt_dir, base_env, srt_bin,
                         log_name=log_name, srt_name=srt_name, label=label, heavy=heavy)


def _base_run(ctx, cfg, raw, step_id, attempt, issue, paths, name, attempt_dir, base_env, srt_bin,
              prepare_tree, notes, heavy=None):
    """I8: the command once on a fresh worktree of the recorded base SHA. → RunResult."""
    return _base_runs(ctx, cfg, raw, step_id, attempt, issue, paths, name, attempt_dir, base_env, srt_bin,
                      prepare_tree, notes, twice=False, heavy=heavy)[0]


def _base_runs(ctx, cfg, raw, step_id, attempt, issue, paths, name, attempt_dir, base_env, srt_bin,
               prepare_tree, notes, twice, heavy=None):
    """The command on a fresh worktree of the recorded base SHA → (RunResult, second RunResult or None).

    `twice` (evidence runs, K8-2): red or timed out → once more on the SAME base tree, unless the
    first run left that tree dirty (the second would not judge the recorded base any more; the
    first result stands). A run = `setup` while it has not been green yet, then the command."""
    home = _engine_home(paths)
    tree = os.path.join(paths["run_tmp"], BASE_TREE)
    _make_dir(paths["run_tmp"], home)
    try:
        bctx = gitops.detached_worktree(ctx, tree, ctx.base_sha)
    except gitops.GitError as e:
        raise TreeError(f"base worktree could not be made: {e}") from e
    try:
        if prepare_tree is not None:
            prepare_tree(bctx.work_tree)
        tmp = os.path.join(paths["run_tmp"], BASE_TMP)
        _make_dir(tmp, home)
        bpaths = _with_dirs(_temp_paths(paths, bctx, ctx.work_tree, tmp), bctx)
        ready = name == SETUP_COMMAND

        def srt_name():
            names = [SRT_BASE_FILE] + [f"srt-base-{n}.json" for n in range(2, 5)]      # at most setup + command, twice
            return next(n for n in names if not os.path.lexists(os.path.join(attempt_dir, n)))

        def once(setup_log, log_name, label):
            nonlocal ready
            if not ready:
                sres = _tree_setup(cfg, raw, step_id, attempt, issue, bpaths, attempt_dir, base_env, srt_bin,
                                   log_name=setup_log, srt_name=srt_name(), label=label + "-setup", heavy=heavy)
                if sres is not None and not sres.green:
                    notes.append(f"{label} run: `{SETUP_COMMAND}` was red on the recorded base "
                                 f"(exit {sres.exit_code}, timed out {sres.timed_out}) — base counted red")
                    return sres
                ready = True
            return _tree_command(cfg, raw, step_id, attempt, issue, bpaths, name, attempt_dir, base_env, srt_bin,
                                 log_name=log_name, srt_name=srt_name(), label=label, heavy=heavy)

        first = once(LOG_BASE_SETUP, LOG_BASE, "base")
        if not twice or first.green:
            return first, None
        try:
            state = gitops.tree_state(bctx)
        except gitops.UnsafePath:
            raise
        except gitops.GitError as e:
            raise TreeError(f"the base tree state could not be read: {e}") from e
        if not state["clean"]:
            notes.append("base run: red and left the base tree dirty — not run again: "
                         + ", ".join(state["dirty_files"][:20]))
            return first, None
        second = once(LOG_BASE_SETUP_RERUN, LOG_BASE_RERUN, "base-rerun")
        if second.green:
            notes.append(f"base flaky: `{name}` was red, then green on the same tree of the recorded base — base green")
        return first, second
    finally:
        _remove_tree(ctx, bctx.work_tree, notes)


def _verify_gate(ctx, raw, step_id, attempt, issue, paths, attempt_dir, base_env, srt_bin, plugin_root,
                 timeout_s, head_sha):
    """verify-gate (§2.1, F5): read-tree temp tree → the gate under srt, writes only in the temp tree."""
    home = _engine_home(paths)
    tree = os.path.join(paths["run_tmp"], GATE_TREE)
    _make_dir(paths["run_tmp"], home)
    try:
        tctx = gitops.temp_tree_for_gate(ctx, head_sha, tree)
    except gitops.GitError as e:
        raise RunnerError(f"verify-gate temp tree could not be made: {e}") from e
    try:
        tmp = os.path.join(paths["run_tmp"], GATE_TMP)
        _make_dir(tmp, home)
        gpaths = _temp_paths(paths, tctx, ctx.work_tree, tmp)
        cmd = plugin_command_line(codes.PluginCommand.VERIFY_GATE.value, plugin_root, issue)
        inp = _run_input(raw, step_id, attempt, issue, gpaths, cmd, timeout_s)
        return run_named(inp, attempt_dir, base_env, srt_bin, timeout_s, label="gate",
                         narrow_writes=[tctx.work_tree, tctx.git_dir, tmp])
    finally:
        notes = []
        _remove_tree(ctx, tctx.work_tree, notes)


def run_step(ctx, config, procedure, step, attempt_dir, base_env, srt_bin, plugin_root, *,
             issue, attempt, paths, prepare_tree=None, control_check=None, stage=2, step_files=None,
             path_globs=None, plugin_args=(), heavy_lock=None, allowed_test_changes=()):
    """The full run step: command, tree check, I8 extras → StepRun (facts.json `run` object + Outcome).

    ctx            gitops.GitContext of the Issue worktree
    config         RepoConfig (or its dict) — read from the recorded base blob by the caller
    procedure      the parsed procedure; `step` (Step or step dict) must be one of its run steps
    paths          the run's render paths (render.RenderInput `paths`: home, claude_config_dir,
                   worktree = ctx.work_tree, main_checkout, git_common_dir, own_worktree,
                   engine_records, run_tmp, cache, plugin_root, issue, srt_tmpdir, lists;
                   `user_tmp` when an allow_write exception uses the token)
    prepare_tree   optional callable(path) — worktree_prepare copies into the I8 base tree
    control_check  verify-gate only, REQUIRED: callable(head_sha) → facts `control_files`
                   dict {"ok", "changed"} (results.check_control_files)
    stage          the engine stage; the stage-3 plugin commands are refused before 3
    step_files     evidence runs only, REQUIRED: facts.step_files of the authoring step
                   (evidence_author) with the same globs
    path_globs     the globs that bound the run: a list, {path rule kind: list}, or None = the
                   settings' rules of the command's kind (PATH_KINDS)
    plugin_args    ac-format only, from stage 3: extra arguments (E30: `--deferred R3,R5`)
    heavy_lock     stage 4 (H22): the flock every repository command of this step waits for; the
                   summed wait is facts.run.queue_wait_s. Plugin checks and git-fact runs never wait
    allowed_test_changes   stage 4 (H21): testchange.allowed(state) — frozen_violations `allowed`
    Raises RunnerError when the run cannot be carried out as specified (never a pass).
    """
    st = procedure_mod.Step(step)
    if procedure is not None:
        try:
            if procedure.step(st.id) != st:
                raise RunnerError(f"step {st.id!r} differs from the procedure's")
        except KeyError as e:
            raise RunnerError(str(e)) from e
    if st.kind != codes.StepKind.RUN.value:
        raise RunnerError(f"step {st.id!r} is not a run step")
    raw = _raw_config(config)
    cfg = _repo_config(config)
    if st.name not in cfg.command_names():
        raise RunnerError(f"run {st.name!r} is not a named command of the repository settings (§7.10)")
    entry = cfg.command(st.name)
    if paths.get("worktree") != ctx.work_tree:
        raise RunnerError("paths.worktree is not the Issue worktree of the git context")
    if entry["plugin"] and entry["plugin"] not in codes.STAGE2_PLUGIN_COMMANDS and stage < 3:
        raise RunnerError(f"plugin command {entry['plugin']!r} is not available in stage {stage}")
    extra = plugin_args_for(entry["plugin"], stage, plugin_args)
    start_head = _head(ctx)
    start_tree = _tree(ctx)
    if not start_tree["clean"]:
        raise RunnerError(f"a run starts only on a clean tree (I7): {start_tree['dirty_files'][:10]}")
    notes, control = [], None
    heavy = HeavyQueue.of(heavy_lock)
    timeout_s = entry["timeout_s"]
    paths = _with_dirs(paths, ctx)

    if entry["plugin"] in codes.EVIDENCE_COMMANDS:
        return _evidence_run(ctx, cfg, raw, st, entry["plugin"], procedure, attempt, issue, paths, attempt_dir,
                             base_env, srt_bin, prepare_tree, step_files, path_globs, start_head, start_tree, notes,
                             heavy)
    if entry["plugin"] in codes.GIT_FACT_COMMANDS:
        return _git_fact_run(ctx, cfg, st, entry["plugin"], issue, paths, attempt_dir, path_globs, start_head,
                             start_tree, notes, allowed_test_changes)
    if entry["plugin"] == codes.PluginCommand.VERIFY_GATE.value:
        if control_check is None:
            raise RunnerError("verify-gate needs the control-file check first (§2.1, F5) — no control_check given")
        control = control_check(start_head)
        if not isinstance(control, dict) or control.get("ok") is not True:
            notes.append("verify-gate not run: the control-file check did not pass")
            return StepRun(None, _outcome("needs_human", stop=codes.StopReason.CONTROL_FILE.value),
                           start_tree, start_head, start_head, None, control_files=control, notes=notes)
        main = _verify_gate(ctx, raw, st.id, attempt, issue, paths, attempt_dir, base_env, srt_bin,
                            plugin_root, timeout_s, start_head)
    elif entry["plugin"]:
        inp = _run_input(raw, st.id, attempt, issue, paths, "true", timeout_s)
        main = run_plugin_command(entry["plugin"], inp, attempt_dir, base_env, srt_bin, timeout_s, plugin_root,
                                  args=extra)
    else:
        inp = _run_input(raw, st.id, attempt, issue, paths, entry["cmd"], timeout_s)
        main = run_named(inp, attempt_dir, base_env, srt_bin, timeout_s, heavy_lock=heavy)

    run = {"name": st.name, "exit_code": main.exit_code, "timed_out": main.timed_out,
           "log_file": os.path.basename(main.log_file), "rerun": None, "base_run": None}
    end_tree, end_head = _tree(ctx), _head(ctx)
    moved = end_head != start_head

    if not main.green and end_tree["clean"] and not moved and not entry["plugin"]:
        rerun = run_named(inp, attempt_dir, base_env, srt_bin, timeout_s, log_name=LOG_RERUN, label="rerun",
                          heavy_lock=heavy)
        run["rerun"] = rerun.to_facts()
        if rerun.green:
            notes.append(f"flaky: `{st.name}` was red, then green once on the same tree (I8) — still red")
        base = _base_run(ctx, cfg, raw, st.id, attempt, issue, paths, st.name, attempt_dir, base_env, srt_bin,
                         prepare_tree, notes, heavy)
        run["base_run"] = base.to_facts()
        if not base.green:
            notes.append(f"base red: `{st.name}` is red on the recorded base {ctx.base_sha[:12]} too (I8)")
        end_tree, end_head = _tree(ctx), _head(ctx)
        moved = end_head != start_head
    if moved:
        notes.append(f"HEAD moved during the run ({start_head[:12]} → {end_head[:12]}) — run-dirty-tree")
    if not end_tree["clean"]:
        notes.append("the run left the tree dirty: " + ", ".join(end_tree["dirty_files"][:20]))
    if heavy is not None and not entry["plugin"]:
        run["queue_wait_s"] = round(heavy.waited, 3)
    return StepRun(run, outcome_of(run, end_tree, moved), end_tree, start_head, end_head, main.duration_s,
                   control_files=control, notes=notes)


# --- toolchain prepare (§7.12 S8, P3-Z human decision 4) -----------------------------------
#
# Outside the sandbox the engine only COPIES files: from a trusted, read-only source (the
# user's SDK) into the repository's Guild cache. It never executes anything a role or a run
# can write (the cache is role-writable: a binary planted there by an earlier Issue would
# otherwise run unsandboxed). The copy is re-made at every engine start: a file that differs
# from the source is rewritten, an entry the source lacks is removed, links are copied as
# links and never followed (neither in the source nor in the destination). Every `cmd` entry
# (e.g. `flutter precache`) runs INSIDE srt with the run boundary, like a named command.

_COPY_CHUNK = 1 << 20
_RD_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_WR_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _remove_entry(path):
    """Remove `path` (file, link or real folder tree) without ever following a link."""
    st = os.lstat(path)
    if stat.S_ISDIR(st.st_mode):
        for e in os.scandir(path):
            _remove_entry(e.path)
        os.rmdir(path)
    else:
        os.unlink(path)


def _same_file(src, dst, sst, dstat):
    if sst.st_size != dstat.st_size or (sst.st_mode & 0o7777) != (dstat.st_mode & 0o7777):
        return False
    fs = os.open(src, _RD_FLAGS)
    try:
        fd = os.open(dst, _RD_FLAGS)
    except OSError:
        os.close(fs)
        return False
    try:
        while True:
            a = os.read(fs, _COPY_CHUNK)
            b = os.read(fd, _COPY_CHUNK)
            if a != b:
                return False
            if not a:
                return True
    finally:
        os.close(fs)
        os.close(fd)


def _copy_file(src, dst, mode):
    fs = os.open(src, _RD_FLAGS)
    try:
        fd = os.open(dst, _WR_FLAGS, 0o600)
        try:
            while True:
                buf = os.read(fs, _COPY_CHUNK)
                if not buf:
                    break
                view = memoryview(buf)
                while view:
                    view = view[os.write(fd, view):]
            os.fchmod(fd, mode & 0o7777 & ~0o6000)     # never setuid/setgid
        finally:
            os.close(fd)
    finally:
        os.close(fs)


def _mirror(src, dst, stats):
    """Make the real folder `dst` an exact copy of the real folder `src` (see above)."""
    have = {e.name: e for e in os.scandir(dst)}
    for e in sorted(os.scandir(src), key=lambda x: x.name):
        s = e.path
        d = os.path.join(dst, e.name)
        sst = os.lstat(s)
        cur = have.pop(e.name, None)
        dstat = os.lstat(d) if cur is not None else None
        if stat.S_ISLNK(sst.st_mode):
            target = os.readlink(s)
            if dstat is not None and stat.S_ISLNK(dstat.st_mode) and os.readlink(d) == target:
                continue
            if dstat is not None:
                _remove_entry(d)
            os.symlink(target, d)
            stats["written"] += 1
        elif stat.S_ISDIR(sst.st_mode):
            if dstat is not None and not stat.S_ISDIR(dstat.st_mode):
                _remove_entry(d)
                dstat = None
            if dstat is None:
                os.mkdir(d, 0o755)
                stats["written"] += 1
            os.chmod(d, (sst.st_mode & 0o777) | 0o700)
            _mirror(s, d, stats)
        elif stat.S_ISREG(sst.st_mode):
            if dstat is not None and stat.S_ISREG(dstat.st_mode) and _same_file(s, d, sst, dstat):
                stats["same"] += 1
                continue
            if dstat is not None:
                _remove_entry(d)
            _copy_file(s, d, sst.st_mode)
            stats["written"] += 1
        else:
            if dstat is not None:          # fifo / socket / device: never copied
                _remove_entry(d)
            stats["skipped"] += 1
    for name in sorted(have):
        _remove_entry(os.path.join(dst, name))
        stats["removed"] += 1


def _writable_roots(paths):
    """Folders a role or a run may write (the source of a sync may be neither in nor above them)."""
    roots = [paths["worktree"], os.path.dirname(paths["run_tmp"]), paths["cache"], paths["own_worktree"],
             paths["git_common_dir"], _engine_home(paths), paths["main_checkout"]]
    roots += list(paths.get("other_worktrees") or [])
    if paths.get("user_tmp"):
        roots.append(paths["user_tmp"])
    roots += list(repoconfig.TEMP_AREAS)
    return [os.path.realpath(r) for r in roots if r]


def sync_source(candidates, paths):
    """The first candidate that is an existing real folder (realpath), checked against every
    writable location (in it or containing it → RunnerError). None when no candidate exists."""
    home = paths["home"]
    roots = _writable_roots(paths)
    for c in candidates:
        p = repoconfig.resolve_home(c, home)
        if not os.path.isabs(p):
            raise RunnerError(f"toolchain sync source {c!r} is not absolute")
        try:
            real = os.path.realpath(p)
            if not stat.S_ISDIR(os.stat(real).st_mode):
                continue
        except OSError:
            continue
        for r in roots:
            if _under(real, r) or _under(r, real):
                raise RunnerError(f"toolchain sync source {real} is inside or above the writable folder {r} — "
                                  "refused (a role or a run could change what is copied)")
        return real
    return None


def sync_tree(source, cache, to, home_root):
    """Mirror the trusted folder `source` into `<cache>/<to>` (outside the sandbox — copy only).

    `home_root` = the engine home (the destination path must not pass through a link from
    there). Returns {"written", "same", "removed", "skipped"}. Raises RunnerError."""
    dst = os.path.join(cache, to)
    if not _under(os.path.normpath(dst), cache) or os.path.normpath(dst) == cache:
        raise RunnerError(f"sync destination {to!r} is not inside the Guild cache")
    _make_dir(os.path.dirname(dst), home_root)
    try:
        st = os.lstat(dst)
        if not stat.S_ISDIR(st.st_mode):
            _remove_entry(dst)
            raise FileNotFoundError
    except FileNotFoundError:
        os.mkdir(dst, 0o755)
    stats = {"written": 0, "same": 0, "removed": 0, "skipped": 0}
    try:
        _mirror(source, dst, stats)
    except OSError as e:
        raise RunnerError(f"toolchain sync {source} → {dst} failed: {e}") from e
    return stats


def toolchain_prepare(ctx, config, base_env, srt_bin, *, paths, attempt_dir, step_id, attempt, issue, heavy_lock=None):
    """Every toolchain_prepare entry in file order; stops at the first failure. → [entry result].

    `sync` entries: sync_source + sync_tree (files only, outside the sandbox). `cmd` entries:
    under srt with the run boundary of `paths` (the run render paths of the attempt that
    triggers the prepare), logs `prepare-<name>.log` in `attempt_dir`; the Issue worktree must
    stay clean and HEAD unmoved. Each result = {"name", "kind": "sync"|"cmd", "ok", "rc",
    "timed_out", "note"}. Raises RunnerError when an entry cannot be carried out as specified.
    `heavy_lock` (stage 4, H22): the flock every `cmd` entry waits for (a `sync` copy does not).
    """
    cfg = _repo_config(config)
    raw = _raw_config(config)
    out = []
    for e in cfg.toolchain_prepare():
        if e["sync"] is not None:
            src = sync_source(e["sync"]["from"], paths)
            if src is None:
                out.append({"name": e["name"], "kind": "sync", "ok": False, "rc": None, "timed_out": False,
                            "note": "no source folder exists: " + ", ".join(e["sync"]["from"])})
                break
            stats = sync_tree(src, paths["cache"], e["sync"]["to"], _engine_home(paths))
            out.append({"name": e["name"], "kind": "sync", "ok": True, "rc": 0, "timed_out": False,
                        "note": f"{src} → {{cache}}/{e['sync']['to']}: " +
                                ", ".join(f"{k} {v}" for k, v in stats.items())})
            continue
        head, tree = _head(ctx), _tree(ctx)
        inp = _run_input(raw, step_id, attempt, issue, _with_dirs(paths, ctx), e["cmd"], e["timeout_s"])
        r = run_named(inp, attempt_dir, base_env, srt_bin, e["timeout_s"], log_name=f"prepare-{e['name']}.log",
                      srt_name=f"srt-prepare-{e['name']}.json", label=f"prepare-{e['name']}", heavy_lock=heavy_lock)
        after, moved = _tree(ctx), _head(ctx) != head
        ok = r.green and after["clean"] == tree["clean"] and not moved
        note = "" if ok else ("the worktree changed" if r.green else "red")
        out.append({"name": e["name"], "kind": "cmd", "ok": ok, "rc": r.exit_code, "timed_out": r.timed_out,
                    "note": note})
        if not ok:
            break
    return out


# --- stage 3: repro-red (E6) and the overlay tree (review-q0 D1, D10) -------------------------
#
# An evidence run never judges the HEAD tree: the fix commit would change the verdict when
# §4.4-3, I3 or a rerun runs the step again. It judges the OVERLAY tree = a fresh worktree of
# the recorded base + the HEAD blobs of the files the authoring step (reproduce / safety-net)
# owns. Nothing else of the branch is in it, so a red overlay over a green base is red because
# of those files alone. The overlay is staged, not committed: HEAD stays the recorded base.

TEST_COMMAND = "test"
OVERLAY_TREE = "overlay-tree"
OVERLAY_TMP = "overlay-tmp"
LOG_HEAD = "run-head.log"
LOG_HEAD_RERUN = "run-head-rerun.log"
LOG_HEAD_SETUP = "run-head-setup.log"
LOG_HEAD_SETUP_RERUN = "run-head-setup-rerun.log"
SRT_HEAD_FILE = "srt-head.json"
SRT_HEAD_RERUN_FILE = "srt-head-2.json"
SRT_HEAD_SETUP_FILE = "srt-head-setup.json"
SRT_HEAD_SETUP_RERUN_FILE = "srt-head-setup-2.json"
LOG_TAIL_LINES = 120
LOG_TAIL_BYTES = 16000
"""What run.log (the failure summary's source) repeats of the decisive command's log; the
engine's own lines come after it, so the driver's cut of the last lines never loses them."""
LOG_LIST_MAX = 100
_GIT_CHUNK = 200

PATH_KINDS = {
    codes.PluginCommand.REPRO_RED.value: codes.PathRuleKind.TEST_CODE.value,
    codes.PluginCommand.SAFETY_NET_PROOF.value: codes.PathRuleKind.SAFETY_NET.value,
    codes.PluginCommand.NO_PRODUCTION_CHANGE.value: codes.PathRuleKind.SAFETY_NET.value,
}
"""The path rule kind that bounds each command (E4)."""


def evidence_author(procedure, step_id):
    """The authoring step of an evidence run: the last work-role step before it that declares
    outputs (bug: reproduce, refactor-net / safety-net: safety-net). RunnerError when none."""
    best = None
    for s in procedure.steps[:procedure.index(step_id)]:
        if s.role_class == codes.RoleClass.WORK.value and s.outputs:
            best = s.id
    if best is None:
        raise RunnerError(f"step {step_id!r}: no work step with outputs comes before it — nothing to prove")
    return best


def _kind_globs(cfg, command, path_globs):
    """The globs that bound `command`: `path_globs` (a list, or {kind: list}), else the settings."""
    kind = PATH_KINDS[command]
    if path_globs is None:
        out = [g for r in cfg.path_rules(kind) for g in r["globs"]]
    elif isinstance(path_globs, dict):
        out = list(path_globs.get(kind) or [])
    else:
        out = list(path_globs)
    if not out:
        raise RunnerError(f"{command}: the repository settings have no {kind!r} path rule (E4)")
    return out


def _entries(ctx, sha):
    """{path: (mode, blob)} of a commit's tree (recursive)."""
    out = {}
    for e in gitops.git(ctx, "ls-tree", "-r", "-z", "--full-tree", sha).split("\0"):
        if not e:
            continue
        meta, _, name = e.partition("\t")
        mode, _typ, obj = meta.split()
        out[name] = (mode, obj)
    return out


def _matches(patterns, path):
    try:
        return globs.match_any(patterns, path) is not None
    except ValueError:
        return False          # a path the dialect cannot express matches nothing (fail-closed here)


def _engine_run(name, exit_code, **over):
    run = {"name": name, "exit_code": exit_code, "timed_out": False, "log_file": LOG_MAIN, "rerun": None,
           "base_run": None, "base_rerun": None, "head": None, "head_rerun": None, "evidence": None,
           "paths_check": None}
    run.update(over)
    return run


def _infra_run(name, start_tree, start_head, notes, note):
    """A git fact of the run could not be collected (§2.0): infra fact-collection, never a pass."""
    notes.append(note)
    return StepRun(_engine_run(name, None), _outcome("failed", codes.FailureCode.INFRA.value,
                                                     codes.InfraReason.FACT_COLLECTION.value),
                   start_tree, start_head, start_head, None, notes=notes)


def _log_tail(path):
    """The last lines of a command log, as text (passed through, never interpreted)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - LOG_TAIL_BYTES))
            data = f.read()
    except OSError:
        return ""
    return "\n".join(data.decode("utf-8", "replace").splitlines()[-LOG_TAIL_LINES:])


def _write_engine_log(attempt_dir, records, text):
    _make_dir(attempt_dir, records)
    fd = _open_log(os.path.join(attempt_dir, LOG_MAIN), records)
    try:
        view = memoryview(text.encode("utf-8", "backslashreplace"))
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)


def _listed(items):
    items = list(items)
    out = [f"  - {x}" for x in items[:LOG_LIST_MAX]]
    if len(items) > LOG_LIST_MAX:
        out.append(f"  … and {len(items) - LOG_LIST_MAX} more (facts.json has all)")
    return out


def _check_step_files(step_files, name):
    if not isinstance(step_files, dict) or not {"attempts", "net", "owned", "outside"} <= set(step_files):
        raise RunnerError(f"{name}: needs step_files (facts.step_files of the authoring step)")
    return step_files


def _overlay_apply(octx, head_sha, files):
    """Put the owned files of `head_sha` into the base worktree (index + files); → its tree id."""
    put = [f["path"] for f in files if f["blob"] is not None]
    drop = [f["path"] for f in files if f["blob"] is None and f["base_blob"] is not None]
    for i in range(0, len(put), _GIT_CHUNK):
        gitops.git(octx, "--literal-pathspecs", "checkout", "-q", head_sha, "--", *put[i:i + _GIT_CHUNK])
    for i in range(0, len(drop), _GIT_CHUNK):
        gitops.git(octx, "--literal-pathspecs", "rm", "-q", "--force", "--", *drop[i:i + _GIT_CHUNK])
    return gitops.git(octx, "write-tree").strip()


def _overlay_state(octx, tree_id):
    """{"clean", "dirty_files"} of the overlay tree against what the engine put there (so the
    overlay files themselves do not count, but a run that rewrites one of them does)."""
    changed = gitops.git(octx, "diff", "--name-only", "-z", "--no-ext-diff", "--no-textconv", "--no-renames",
                         "--ignore-submodules=none", tree_id)
    new = gitops.git(octx, "ls-files", "-z", "--others", "--exclude-standard")
    files = sorted({p for p in (changed + "\0" + new).split("\0") if p})
    return {"clean": not files, "dirty_files": files}


AGAIN_RED = "red"                  # repro-red (D10): a red `test` once more — a timeout is never red
AGAIN_NOT_GREEN = "not-green"      # safety-net-proof (VW4 O1, K8-2): red or timed out, `setup` included


def _overlay_runs(ctx, cfg, raw, st, attempt, issue, paths, attempt_dir, base_env, srt_bin, prepare_tree, ev,
                  again, notes, heavy=None):
    """`setup` + `test` on the overlay tree, once more on the SAME tree when `again` says so and the first
    run left it clean. A run = `setup` while it has not been green yet, then `test` (as _base_runs).
    `again`: AGAIN_RED — only a red `test` (repro-red, D10: both must be red); AGAIN_NOT_GREEN — any run
    that was not green, a timeout and a red `setup` included (safety-net-proof, VW4 O1: K8-2's rule).
    → (first RunResult, second RunResult or None, (command of the first, command of the second or None))."""
    home = _engine_home(paths)
    path = os.path.join(paths["run_tmp"], OVERLAY_TREE)
    _make_dir(paths["run_tmp"], home)
    try:
        octx = gitops.detached_worktree(ctx, path, ctx.base_sha)
    except gitops.UnsafePath:
        raise
    except gitops.GitError as e:
        raise TreeError(f"overlay worktree could not be made: {e}") from e
    try:
        if prepare_tree is not None:
            prepare_tree(octx.work_tree)
        try:
            tree_id = _overlay_apply(octx, ev["overlay"]["head_sha"], ev["overlay"]["files"])
        except gitops.UnsafePath:
            raise
        except gitops.GitError as e:
            raise TreeError(f"the overlay files could not be placed: {e}") from e
        tmp = os.path.join(paths["run_tmp"], OVERLAY_TMP)
        _make_dir(tmp, home)
        opaths = _with_dirs(_temp_paths(paths, octx, ctx.work_tree, tmp), octx)

        def state():
            try:
                ev["end_tree"] = _overlay_state(octx, tree_id)
            except gitops.UnsafePath:
                raise
            except gitops.GitError as e:
                raise TreeError(f"the overlay tree state could not be read: {e}") from e
            return ev["end_tree"]["clean"]

        ready = False

        def once(setup_log, setup_srt, log_name, srt_name, label):
            nonlocal ready
            if not ready:
                setup = _tree_setup(cfg, raw, st.id, attempt, issue, opaths, attempt_dir, base_env, srt_bin,
                                    log_name=setup_log, srt_name=setup_srt, label=label + "-setup", heavy=heavy)
                if setup is not None and not setup.green:
                    notes.append(f"{label} tree: `{SETUP_COMMAND}` was red (exit {setup.exit_code}, timed out "
                                 f"{setup.timed_out}) — `{TEST_COMMAND}` was not run")
                    return setup, SETUP_COMMAND
                ready = True
            return _tree_command(cfg, raw, st.id, attempt, issue, opaths, TEST_COMMAND, attempt_dir, base_env,
                                 srt_bin, log_name=log_name, srt_name=srt_name, label=label, heavy=heavy), TEST_COMMAND

        first, name = once(LOG_HEAD_SETUP, SRT_HEAD_SETUP_FILE, LOG_HEAD, SRT_HEAD_FILE, "overlay")
        clean = state()
        if again == AGAIN_RED:
            want = name == TEST_COMMAND and not first.green and not first.timed_out
        else:
            want = again == AGAIN_NOT_GREEN and not first.green
        if not (want and clean):
            if want:
                notes.append("overlay run: not green and left the overlay tree dirty — not run again")
            return first, None, (name, None)
        second, name2 = once(LOG_HEAD_SETUP_RERUN, SRT_HEAD_SETUP_RERUN_FILE, LOG_HEAD_RERUN, SRT_HEAD_RERUN_FILE,
                             "overlay-rerun")
        state()
        return first, second, (name, name2)
    finally:
        _remove_tree(ctx, octx.work_tree, notes)


def _evidence_run(ctx, cfg, raw, st, command, procedure, attempt, issue, paths, attempt_dir, base_env, srt_bin,
                  prepare_tree, step_files, path_globs, start_head, start_tree, notes, heavy=None):
    """repro-red / safety-net-proof → StepRun (interfaces §2.4; K3: a red overlay also runs the base)."""
    C = codes.CheckFailedReason
    repro = command == codes.PluginCommand.REPRO_RED.value
    patterns = _kind_globs(cfg, command, path_globs)
    sf = _check_step_files(step_files, st.name)
    author = sf.get("step") or evidence_author(procedure, st.id)
    if TEST_COMMAND not in cfg.command_names() or not cfg.command(TEST_COMMAND)["cmd"]:
        raise RunnerError(f"{st.name}: the repository settings have no {TEST_COMMAND!r} command")
    t0 = time.monotonic()
    try:
        base, head = _entries(ctx, ctx.base_sha), _entries(ctx, start_head)
    except gitops.UnsafePath:
        raise
    except gitops.GitError as e:
        return _infra_run(st.name, start_tree, start_head, notes, f"the trees could not be read: {e}")
    outside = set(sf["outside"])
    files = []
    for p in sorted(sf["owned"]):
        h, b = head.get(p), base.get(p)
        if not _matches(patterns, p) or (h is not None and not gitops.is_regular_mode(h[0])):
            outside.add(p)             # never overlaid: not bounded by the rule, or not a plain file
            continue
        files.append({"path": p, "blob": h[1] if h else None, "base_blob": b[1] if b else None})
    existed = [] if repro else sorted(f["path"] for f in files if f["base_blob"] is not None)
    ev = {"kind": command, "globs": patterns,
          "scope": {"ok": not outside, "step": author, "attempts": sorted(sf["attempts"]), "outside": sorted(outside)},
          "overlay": {"base_sha": ctx.base_sha, "head_sha": start_head, "files": files, "existed": existed},
          "end_tree": None}
    run = _engine_run(st.name, 1, evidence=ev, head_flaky=False)
    log, decisive, stop, detail = [], None, None, None
    if outside:
        detail = C.REPRO_SCOPE.value if repro else C.NET_SCOPE.value
        log += [f"`{author}` changed paths outside {patterns}:"] + _listed(sorted(outside))
    elif existed:
        detail = C.NET_SCOPE.value
        log += ["a safety net lives in NEW files only; these exist on the recorded base:"] + _listed(existed)
    elif not files:
        detail = C.REPRO_NOT_RED.value if repro else C.NET_SCOPE.value
        log.append(f"`{author}` left no file of its own inside {patterns} — there is nothing to run")
    else:
        try:
            first, second, names = _overlay_runs(ctx, cfg, raw, st, attempt, issue, paths, attempt_dir, base_env,
                                                 srt_bin, prepare_tree, ev, AGAIN_RED if repro else AGAIN_NOT_GREEN,
                                                 notes, heavy)
            run["head"] = first.to_facts()
            run["head_rerun"] = second.to_facts() if second is not None else None
            decisive = second if second is not None and not second.green else first
            clean = ev["end_tree"]["clean"]
            red = not first.green and (second is None or not second.green)
            setup_red = names[0] == SETUP_COMMAND
            # VW4 O1: a net run that was not green, then green on the same clean overlay tree, passes (K8-2's
            # rule, as the mutation control, E1). The mark stays in the facts; the first log is the one shown.
            run["head_flaky"] = not repro and second is not None and not red
            if run["head_flaky"]:
                notes.append(f"safety net flaky: `{names[0]}` on the overlay tree was "
                             f"{'timed out' if first.timed_out else f'red (exit {first.exit_code})'}, then green on "
                             f"the same tree — passed (VW4 O1, K8-2); first log {os.path.basename(first.log_file)}")
            if red and clean:
                b, again = _base_runs(ctx, cfg, raw, st.id, attempt, issue, paths, TEST_COMMAND, attempt_dir,
                                      base_env, srt_bin, prepare_tree, notes, twice=True, heavy=heavy)
                run["base_run"] = b.to_facts()
                run["base_rerun"] = again.to_facts() if again is not None else None
        except TreeError as e:
            return _infra_run(st.name, start_tree, start_head, notes, str(e))
        # a flaky net run passed: its first timeout does not decide (the green second run does)
        run["timed_out"] = not run["head_flaky"] and (first.timed_out or bool(second and second.timed_out))
        log.append(f"overlay tree = recorded base {ctx.base_sha[:12]} + {len(files)} file(s) of `{author}`: "
                   + ", ".join(f"`{n}` exit {r.exit_code}{' (timed out)' if r.timed_out else ''}" for n, r in (
                       (names[0], first), (f"{names[1]} again", second))
                       if r is not None))
        if run["head_flaky"]:
            log.append(f"flaky: not green, then green on the same overlay tree — passed (VW4 O1, K8-2); the "
                       f"first run's log is {os.path.basename(first.log_file)}")
        if run["base_run"] is not None:
            log.append(f"recorded base alone: `{TEST_COMMAND}` " + ", again ".join(
                f"exit {r['exit_code']}{' (timed out)' if r['timed_out'] else ''}"
                for r in (run["base_run"], run["base_rerun"]) if r is not None))
        if is_base_red(run):
            stop = codes.StopReason.BASE_RED.value
            notes.append(f"base red: `{TEST_COMMAND}` is red on the recorded base {ctx.base_sha[:12]}"
                         f"{' twice' if run['base_rerun'] is not None else ''} (I8, K3, K8-2)")
        elif not clean:
            detail = C.RUN_DIRTY_TREE.value
            log += ["the run left the overlay tree dirty:"] + _listed(ev["end_tree"]["dirty_files"])
        elif run["timed_out"]:
            detail = C.RUN_TIMEOUT.value
        elif repro and (setup_red or not red):
            detail = C.REPRO_NOT_RED.value
        elif not repro and red:
            detail = C.NET_RED_ON_BASE.value
    end_tree, end_head = _tree(ctx), _head(ctx)
    moved = end_head != start_head
    if stop is None and (moved or not end_tree["clean"]):
        detail = C.RUN_DIRTY_TREE.value
        log.append("the run changed the Issue worktree")
    if stop is not None:
        outcome = _outcome("needs_human", stop=stop)
    elif detail is not None:
        outcome = _outcome("failed", codes.FailureCode.CHECK_FAILED.value, detail)
    else:
        outcome, run["exit_code"] = _outcome("done"), 0
    if heavy is not None:
        run["queue_wait_s"] = round(heavy.waited, 3)
    tail = _log_tail(decisive.log_file) if decisive is not None else ""
    text = (f"--- last lines of {os.path.basename(decisive.log_file)} ---\n{tail}\n\n" if tail else "")
    text += "\n".join([f"[gld engine] {st.name}: {stop or detail or 'ok'}"] + log) + "\n"
    _write_engine_log(attempt_dir, paths["engine_records"], text)
    return StepRun(run, outcome, end_tree, start_head, end_head, round(time.monotonic() - t0, 3), notes=notes)


# --- stage 3: verification-frozen (E9) and no-production-change (E11) -------------------------
#
# Git facts only: no process, no diff text, no output. Both judge HEAD (a run starts on a clean
# tree) against the recorded base.

def frozen_violations(ctx, config, head_sha, allowed=()):
    """E9: base files under a `verification` path rule that HEAD does not hold unchanged.

    Unchanged = the same path with the same mode and blob, or an EXACT rename: the same mode and
    blob at a path that base did not have and that one of the same rules covers (a test moved out
    of every verification path is no longer a test). Each new path stands in for one base file
    only. New files are fine. → [{"path", "change", "from"}] (empty = frozen).
    `allowed` (stage 4, H21): paths a human allowed; a change of their CONTENT alone (same path, same mode)
    is no violation — deleted, renamed, another type or mode still is.
    Raises RunnerError without any verification rule — there would be nothing to prove."""
    rules = [r["globs"] for r in _repo_config(config).path_rules(codes.PathRuleKind.VERIFICATION.value)]
    if not any(rules):
        raise RunnerError("verification-frozen: the repository settings have no 'verification' path rule")
    base, head = _entries(ctx, ctx.base_sha), _entries(ctx, head_sha)

    def covered(path):
        return {i for i, patterns in enumerate(rules) if _matches(patterns, path)}

    renamed = {c["from"]: c["path"] for c in gitops.changed_files(ctx, head_sha)
               if c["where"] == "committed" and c["change"] == "renamed"}
    new_paths = {}
    for p in sorted(set(head) - set(base)):
        new_paths.setdefault(head[p], []).append(p)
    out = []
    for p in sorted(base):
        own = covered(p)
        if not own or head.get(p) == base[p]:
            continue
        if p in head:
            if p in allowed and base[p][0] == head[p][0] and gitops.is_regular_mode(head[p][0]):
                continue
            same_type = base[p][0][:3] == head[p][0][:3]
            out.append({"path": p, "change": "modified" if same_type else "type-changed", "from": None})
            continue
        pool = new_paths.get(base[p], [])
        target = next((q for q in pool if covered(q) & own), None)
        if target is not None:
            pool.remove(target)
        elif p in renamed:
            out.append({"path": renamed[p], "change": "renamed", "from": p})
        else:
            out.append({"path": p, "change": "deleted", "from": None})
    return out


def production_violations(ctx, issue, head_sha, patterns):
    """E11: every change of merge-base..HEAD outside docs/specs/<N>/ that is not a NEW plain file
    inside `patterns` (the safety-net globs). → [{"path", "change", "from"}]."""
    specs = defaults.SPECS_DIR.replace("{issue}", str(issue)) + "/"
    head = _entries(ctx, head_sha)
    out = []
    for c in gitops.changed_files(ctx, head_sha):
        if c["path"].startswith(specs) and (c["from"] is None or c["from"].startswith(specs)):
            continue
        entry = head.get(c["path"])
        if c["change"] == "added" and _matches(patterns, c["path"]) and entry is not None \
                and gitops.is_regular_mode(entry[0]):
            continue
        out.append({"path": c["path"], "change": c["change"], "from": c["from"]})
    return out


def _git_fact_run(ctx, cfg, st, command, issue, paths, attempt_dir, path_globs, start_head, start_tree, notes,
                  allowed_test_changes=()):
    """verification-frozen / no-production-change → StepRun (facts.run.paths_check, exit code 0 / 1)."""
    C = codes.CheckFailedReason
    t0 = time.monotonic()
    frozen = command == codes.PluginCommand.VERIFICATION_FROZEN.value
    patterns = None if frozen else _kind_globs(cfg, command, path_globs)
    try:
        bad = frozen_violations(ctx, cfg, start_head, allowed=allowed_test_changes) if frozen \
            else production_violations(ctx, issue, start_head, patterns)
    except gitops.UnsafePath:
        raise
    except gitops.GitError as e:
        return _infra_run(st.name, start_tree, start_head, notes, f"{command}: {e}")
    detail = None
    if bad:
        detail = C.VERIFICATION_CHANGED.value if frozen else C.PRODUCTION_CHANGED.value
    run = _engine_run(st.name, 1 if bad else 0, paths_check={"ok": not bad, "violations": bad})
    head_line = f"[gld engine] {st.name}: {detail or 'ok'}"
    what = ("verification files of the recorded base that changed (only an exact rename inside the same rule is "
            "allowed):" if frozen else f"changes that are not a new file inside {patterns}:")
    lines = [head_line] + ([what] + _listed(
        f"{v['change']}: {v['path']}" + (f" (from {v['from']})" if v["from"] else "") for v in bad) if bad else [])
    if frozen and allowed_test_changes:
        lines += ["content changes a human allowed (E9-2):"] + _listed(sorted(allowed_test_changes))
    _write_engine_log(attempt_dir, paths["engine_records"], "\n".join(lines) + "\n")
    outcome = _outcome("failed", codes.FailureCode.CHECK_FAILED.value, detail) if bad else _outcome("done")
    return StepRun(run, outcome, start_tree, start_head, start_head, round(time.monotonic() - t0, 3), notes=notes)
