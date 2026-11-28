"""Base check: are the repository's named commands green on a base commit? (stage-4 scope §2.7 H12, VB1)

The one function the sprint supervisor (A) and init (B) share; `tools/base_check.py` and `engine.py
base-check` are thin shells around it. The commands run exactly like an Issue's `run` steps: a fresh
detached worktree of the commit (under the engine home, never in the checkout), worktree_prepare copies,
toolchain prepare, then every named repository command — `setup` first, then file order, plugin checks
not — through runner.run_named (the srt run boundary, the repository's Guild cache, the heavy-run lock).

  * red = non-zero, timed out, or the tree / HEAD changed. Red on a clean tree → the same command once
    more on that tree (the K8-2 rule): green then = flaky (green), red = red. A dirty tree → no second run,
    the tree is put back for the next command.
  * before anything runs, the (free) srt canary of these settings passes — `engine.py canary --srt-only --config`
    as a child (this module imports no canaryrun); it is run every time, a stale record never counts.
  * `setup` red → nothing after it is run. A prepare / worktree / settings / srt-canary / engine failure is a
    `problem`: refused exactly like red.
  * a green record of the same (commit, settings) pair is used again (`force` runs anyway); a red one never.
  * nothing of it is an Issue's: no state, no Issue cost; logs `<record without .json>.logs/run-<n>/`.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys

from . import catalog as catalogmod, defaults, fsafe, gitops, globs, paths as pathsmod, render, repoconfig, runner, store

PROBLEMS = ("worktree", "prepare", "config", "srt-canary", "engine-error")
"""base-green `problem`: a fact that could not be collected, refused like red."""

EXIT_OK = 0
EXIT_REFUSED = 4

ISSUE = 1                       # the render input wants an Issue number; docs/specs/1/procedure.yaml is only a deny path
WORK_DIR = "base-check"         # <home>/tmp/<owner>/<repo>/base-check/<pid>/ (an Issue's folder is a number)
TREE = "tree"
PREPARE_STEP = "prepare"
CANARY_TIMEOUT_S = 1800


class BaseCheckRequest:
    """repo ("owner/name"), checkout (main checkout, only refs / objects are read from it), sha (the base commit, already
    fetched), config_text (the settings to check: a committed blob, or an init draft), engine_home, plugin_root,
    environ, srt (path), user_tmp (or None), force (True = ignore a green record), out (text stream or None)."""

    FIELDS = ("repo", "checkout", "sha", "config_text", "engine_home", "plugin_root", "environ", "srt", "user_tmp",
              "force", "out")

    def __init__(self, **fields):
        if set(fields) != set(self.FIELDS):
            raise TypeError(f"BaseCheckRequest needs exactly {self.FIELDS}")
        for k, v in fields.items():
            setattr(self, k, v)


class BaseCheckResult:
    """ok (bool), red ([command name]), flaky ([command name]), problem (PROBLEMS value or None), record (path of the
    base-green record), reused (True = an existing green record, nothing was run)."""

    def __init__(self, ok, red=(), flaky=(), problem=None, record=None, reused=False):
        if problem is not None and problem not in PROBLEMS:
            raise ValueError(f"unknown base check problem {problem!r}")
        if ok and (red or problem):
            raise ValueError("a green base check has no red command and no problem")
        self.ok, self.red, self.flaky = bool(ok), list(red), list(flaky)
        self.problem, self.record, self.reused = problem, record, bool(reused)


class _Problem(Exception):
    """A fact could not be collected: `.code` (PROBLEMS value)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def config_sha256(config_text):
    """The settings half of the record's pair: the sha256 of the settings text as it is (UTF-8)."""
    return hashlib.sha256(config_text.encode("utf-8", "surrogateescape")).hexdigest()


def plugin_version(plugin_root):
    """`version` of the plugin manifest, or "unknown"."""
    try:
        with open(os.path.join(plugin_root, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            v = json.load(f).get("version")
    except (OSError, ValueError, AttributeError):
        v = None
    return v if isinstance(v, str) and v else "unknown"


# --- one check -----------------------------------------------------------------------------------

def _load_config(text):
    try:
        cfg = repoconfig.RepoConfig.from_text(text, catalog=catalogmod.load())
    except repoconfig.ConfigError as e:
        raise _Problem("config", str(e)) from e
    if not command_order(cfg):
        raise _Problem("config", "the settings have no repository command — there is nothing to check")
    return cfg


def command_order(cfg):
    """The repository commands in run order: `setup` first, then file order (plugin checks are not run)."""
    names = [n for n in cfg.command_names() if cfg.command(n)["cmd"]]
    return [n for n in names if n == runner.SETUP_COMMAND] + [n for n in names if n != runner.SETUP_COMMAND]


def _srt_canary(request, root):
    """_Problem unless the srt canary passes now for these settings (a child of this engine; free, no LLM)."""
    engine = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "engine.py")
    folder = os.path.join(root, "tmp", "base-check-canary")
    fsafe.make_dirs(folder, root=root)
    config = os.path.join(folder, f"{os.getpid()}.json")
    fsafe.write_text(config, request.config_text, root=root)
    env = dict(request.environ, GLD_ENGINE_HOME=root, GLD_SRT_BIN=request.srt)
    try:
        p = subprocess.run([sys.executable, "-I", "-B", engine, "canary", "--srt-only", "--config", config], env=env,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=CANARY_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise _Problem("srt-canary", f"the srt canary could not be run: {e}") from e
    finally:
        try:
            os.unlink(config)
        except OSError:
            pass
    if p.returncode != 0:
        raise _Problem("srt-canary", "the srt canary failed:\n" + p.stdout.decode("utf-8", "replace")[-2000:])


def _context(request):
    main = os.path.realpath(request.checkout)
    git_dir = os.path.join(main, ".git")
    try:
        if not stat.S_ISDIR(os.lstat(git_dir).st_mode):
            raise OSError("not a folder")
    except OSError as e:
        raise _Problem("worktree", f"{main} is not a main checkout ({git_dir}: {e})") from e
    try:
        ctx = gitops.GitContext(git_dir, git_dir, main, main, request.sha, None, None, base_env=request.environ)
        got = gitops.git(ctx, "rev-parse", "--verify", "--quiet", request.sha + "^{commit}").strip()
    except gitops.GitError as e:
        raise _Problem("worktree", f"{request.sha} is not a commit of {main}: {e}") from e
    if got != request.sha:
        raise _Problem("worktree", f"{request.sha} is not a commit of {main}")
    return ctx


def _force_rmtree(path):
    """Remove a tree of ours whose folders may be read-only (a toolchain copies modes). Links are not followed."""
    for dirpath, dirnames, _files in os.walk(path):
        for d in dirnames:
            full = os.path.join(dirpath, d)
            if not os.path.islink(full):
                try:
                    os.chmod(full, 0o700)
                except OSError:
                    pass
    shutil.rmtree(path, ignore_errors=True)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _clean_dead(ctx, parent):
    """Work folders of checks whose process is gone (their worktrees are unregistered first)."""
    try:
        names = os.listdir(parent)
    except OSError:
        return
    for n in names:
        if n.isdigit() and int(n) != os.getpid() and not _alive(int(n)):
            gitops.git(ctx, "worktree", "remove", "--force", "--force", os.path.join(parent, n, TREE), check=False)
            _force_rmtree(os.path.join(parent, n))
    gitops.git(ctx, "worktree", "prune", check=False)


def prepare_tree(source, dest, cfg):
    """worktree_prepare (§7.3) as the engine does it for an Issue: regular files only, never a control file, a secret
    path or an existing file, never through a link. → the copied paths."""
    entries = cfg.worktree_prepare()
    copied = []
    if not entries:
        return copied
    secrets = cfg.secret_paths()
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [d for d in dirnames if d != ".git" and not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, source)
            if not any(globs.match(e["copy"], rel) for e in entries) or os.path.islink(full) or not os.path.isfile(full):
                continue
            if globs.is_control_file(rel, ISSUE) or globs.match_any(secrets, rel) is not None:
                continue
            dst = os.path.join(dest, rel)
            if os.path.lexists(dst):
                continue
            fsafe.make_dirs(os.path.dirname(dst), root=dest, mode=0o755)
            fsafe.copy_file(full, dst, root=dest, src_root=source)
            copied.append(rel)
    return sorted(copied)


def _other_worktrees(ctx, own):
    out = set()
    for line in gitops.git(ctx, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            out.add(os.path.realpath(line[len("worktree "):]))
    return sorted(out - own)


class _Check:
    """The run of one check: a worktree, one log folder, the results so far."""

    def __init__(self, request, cfg, ctx, record, prepare_from):
        self.r, self.cfg, self.ctx, self.record_path = request, cfg, ctx, record
        self.prepare_from = os.path.realpath(prepare_from) if prepare_from else ctx.main_checkout
        self.ep = pathsmod.EnginePaths(request.engine_home, request.repo, ISSUE)
        self.home = self.ep.engine_home
        self.commands, self.red, self.flaky = [], [], []
        self.heavy = pathsmod.heavy_run_lock(self.home)
        self.parent = os.path.join(self.home, "tmp", self.ep.owner, self.ep.name, WORK_DIR)
        self.work = os.path.join(self.parent, str(os.getpid()))
        self.tctx = None

    def say(self, text):
        if self.r.out is not None:
            self.r.out.write(text + "\n")
            self.r.out.flush()

    def open(self):
        fsafe.make_dirs(self.parent, root=self.home)
        fsafe.make_dirs(self.ep.cache, root=self.home)
        _clean_dead(self.ctx, self.parent)
        tree = os.path.join(self.work, TREE)
        if os.path.lexists(self.work):           # this pid, an earlier check of it that could not clean up
            gitops.git(self.ctx, "worktree", "remove", "--force", "--force", tree, check=False)
            _force_rmtree(self.work)
        fsafe.make_dirs(self.work, root=self.home)
        base = self.record_path[:-len(".json")] + ".logs"
        n = 1
        while os.path.lexists(os.path.join(base, f"run-{n}")):
            n += 1
        self.logs = os.path.join(base, f"run-{n}")
        fsafe.make_dirs(self.logs, root=self.home)
        try:
            self.tctx = gitops.detached_worktree(self.ctx, tree, self.r.sha)
            prepare_tree(self.prepare_from, self.tctx.work_tree, self.cfg)
            self.others = _other_worktrees(self.ctx, {self.tctx.work_tree, self.ctx.main_checkout})
        except (gitops.GitError, fsafe.UnsafePath, OSError) as e:
            raise _Problem("worktree", f"the base worktree could not be made: {e}") from e

    def close(self):
        if self.tctx is not None:
            try:
                gitops.remove_worktree(self.ctx, self.tctx.work_tree)
            except gitops.GitError:
                pass                             # the next check removes what a dead process left
        _force_rmtree(self.work)
        gitops.git(self.ctx, "worktree", "prune", check=False)

    def paths(self, label):
        home = os.path.realpath(self.r.environ.get("HOME") or os.path.expanduser("~"))
        ccd = self.r.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
        run_tmp = os.path.join(self.work, "run", label)
        fsafe.make_dirs(run_tmp, root=self.home)
        p = {"home": home, "claude_config_dir": os.path.realpath(ccd), "worktree": self.tctx.work_tree,
             "main_checkout": self.ctx.main_checkout, "git_common_dir": self.ctx.common_dir, "own_worktree": self.tctx.git_dir,
             "engine_records": self.ep.records, "run_tmp": run_tmp, "cache": self.ep.cache, "plugin_root": self.r.plugin_root,
             "issue": ISSUE, "srt_tmpdir": pathsmod.srt_tmpdir(f"bc-{os.getpid()}"[:24]), "other_worktrees": self.others,
             "other_repo_roots": []}
        if self.r.user_tmp and defaults.USER_TMP_TOKEN in (self.cfg.sandbox_exceptions().get("allow_write") or []):
            p["user_tmp"] = self.r.user_tmp
        return p

    def toolchain(self):
        if not self.cfg.toolchain_prepare():
            return
        try:
            done = runner.toolchain_prepare(self.tctx, self.cfg, self.r.environ, self.r.srt, paths=self.paths(PREPARE_STEP),
                                            attempt_dir=os.path.join(self.logs, PREPARE_STEP), step_id=PREPARE_STEP,
                                            attempt=1, issue=ISSUE, heavy_lock=self.heavy)
        except runner.RunnerError as e:
            raise _Problem("prepare", str(e)) from e
        for e in done:
            self.say(f"toolchain prepare {e['kind']} {e['name']}: {'ok' if e['ok'] else 'FAILED'} {e.get('note') or ''}".rstrip())
        bad = [e for e in done if not e["ok"]]
        if bad:
            raise _Problem("prepare", f"toolchain prepare {bad[0]['name']} failed: {bad[0].get('note')}")

    def _once(self, name, n):
        c = self.cfg.command(name)
        label = name if n == 1 else f"{name}.rerun"       # no command name has a dot
        inp = runner._run_input(self.cfg.raw, name, n, ISSUE, runner._with_dirs(self.paths(name), self.tctx), c["cmd"],
                                c["timeout_s"])
        return runner.run_named(inp, self.logs, self.r.environ, self.r.srt, c["timeout_s"], log_name=label + ".log",
                                srt_name=f"srt-{label}.json", label=label, heavy_lock=self.heavy)

    def _dirty(self):
        if gitops.head(self.tctx) != self.r.sha:
            return ["HEAD moved"]
        return gitops.tree_state(self.tctx)["dirty_files"]

    def _restore(self):
        gitops.git(self.tctx, "checkout", "-q", "--detach", "--force", self.r.sha)
        gitops.git(self.tctx, "clean", "-fdq")
        left = self._dirty()
        if left:
            raise _Problem("engine-error", "the base worktree could not be put back: " + ", ".join(left[:5]))

    def command(self, name):
        """Run one command (twice when red on a clean tree); → green?"""
        runs, dirty, green = [], [], False
        for n in (1, 2):
            res = self._once(name, n)
            runs.append({"exit_code": res.exit_code, "timed_out": res.timed_out, "duration_s": res.duration_s,
                         "log_file": os.path.basename(self.logs) + "/" + os.path.basename(res.log_file)})
            dirty = self._dirty()
            green = res.green and not dirty
            if green or dirty:
                break
        if dirty:
            self._restore()
        elif green and len(runs) == 2:
            self.flaky.append(name)
        if not green:
            self.red.append(name)
        self.commands.append({"name": name, "ok": green, "runs": runs, "dirty_files": sorted(dirty)[:50]})
        self.say(f"{name}: {'green' if green else 'RED'}" + (" (flaky: red, then green)" if green and len(runs) == 2 else "")
                 + (f" (left changes: {', '.join(sorted(dirty)[:5])})" if dirty else ""))
        return green

    def run(self, only=None):
        self.toolchain()
        order = [n for n in command_order(self.cfg) if only is None or n in only or n == runner.SETUP_COMMAND]
        stopped = False
        for name in order:
            if stopped:
                self.commands.append({"name": name, "ok": False, "runs": [], "dirty_files": []})
            elif not self.command(name) and name == runner.SETUP_COMMAND:
                stopped = True


def _run(request, record, prepare_from=None, only=None):
    """(_Check or None, problem code or None). Never raises for a red or uncollectable base."""
    chk, problem, note = None, None, None
    try:
        cfg = _load_config(request.config_text)
        ctx = _context(request)
        if not request.srt:
            raise _Problem("srt-canary", "srt is not installed")
        root = store._root(pathsmod.EnginePaths(request.engine_home, request.repo, ISSUE))
        _srt_canary(request, root)
        chk = _Check(request, cfg, ctx, record, prepare_from)
        try:
            chk.open()
            chk.run(only)
        finally:
            chk.close()
    except _Problem as e:
        problem, note = e.code, str(e)
    except (runner.RunnerError, render.RenderError, gitops.GitError, fsafe.UnsafePath, OSError, ValueError) as e:
        problem, note = "engine-error", f"{type(e).__name__}: {e}"
    if problem is not None and request.out is not None:
        request.out.write(f"base check {problem}: {note}\n")
    return chk, problem


def check(request, prepare_from=None):
    """BaseCheckResult of the request (§2.7): a fresh detached worktree of sha, worktree_prepare, toolchain prepare,
    every named command but the plugin checks, in srt through the engine's run path and the heavy-run lock. Red →
    once more on the same tree when it is clean; both red = red. Writes schemas/base-green. Never raises for a red
    or uncollectable base (problem says which). `prepare_from` (tools/base_check.py): where worktree_prepare copies
    come from when the checkout is a scratch clone."""
    ep = pathsmod.EnginePaths(request.engine_home, request.repo, ISSUE)
    digest = config_sha256(request.config_text)
    record = pathsmod.base_green_record(ep.engine_home, request.repo, request.sha, digest)
    if not request.force:
        old = read_green(ep, record, request.sha, digest)
        if old is not None:
            if request.out is not None:
                request.out.write(f"base {request.sha[:12]}: green record of {old['at']} — not run again\n")
            return BaseCheckResult(True, flaky=old["flaky"], record=record, reused=True)
    chk, problem = _run(request, record, prepare_from)
    red, flaky = (chk.red, chk.flaky) if chk is not None else ([], [])
    commands = chk.commands if chk is not None else []
    ok = problem is None and not red and bool(commands) and all(c["ok"] for c in commands)
    if problem is None and not ok and not red:
        problem = "engine-error"                 # never green, never silently red
    store.write_record(ep, record, {
        "format": 1, "repo": ep.repo, "sha": request.sha, "config_sha256": digest, "ok": ok, "commands": commands,
        "red": list(red), "flaky": list(flaky), "problem": problem, "plugin_version": plugin_version(request.plugin_root),
        "at": store.now_ts()}, "base-green")
    return BaseCheckResult(ok, red=red, flaky=flaky, problem=problem, record=record)


def read_green(paths, record, sha, digest):
    """The record when it is green for exactly this pair, else None (unreadable = none: it is run again)."""
    try:
        old = store.read_record(paths, record, "base-green")
    except (store.CorruptFile, store.FormatMismatch):
        return None
    if old is None or old["ok"] is not True or old["red"] or old["problem"] is not None:
        return None
    return old if (old["sha"], old["config_sha256"], old["repo"]) == (sha, digest, paths.repo) else None


def measure(request, names):
    """Init (§2.9 sandbox-exception): which of the commands `names` are green on the base under the settings of the
    request (a draft plus ONE candidate exception)? `setup` runs first. → the green names; nothing is recorded —
    a measurement for a human's question, never a base check."""
    ep = pathsmod.EnginePaths(request.engine_home, request.repo, ISSUE)
    record = pathsmod.base_green_record(ep.engine_home, request.repo, request.sha, config_sha256(request.config_text))
    chk, problem = _run(request, record[:-len(".json")] + "-measure.json", only=set(names))
    if problem is not None or chk is None:
        return []
    return [c["name"] for c in chk.commands if c["ok"] and c["name"] in names]


# --- engine.py base-check ---------------------------------------------------------------------------

def committed_config(checkout, sha, environ):
    """The settings text committed at `sha` (a regular file), or None."""
    main = os.path.realpath(checkout)
    git_dir = os.path.join(main, ".git")
    ctx = gitops.GitContext(git_dir, git_dir, main, main, sha, None, None, base_env=environ)
    got = gitops.blob(ctx, sha, defaults.ENGINE_SETTINGS)
    if got is None or got[2] is None or not gitops.is_regular_mode(got[0]):
        return None
    return got[2].decode("utf-8")


def head_sha(checkout, environ):
    """The checkout's HEAD commit."""
    return gitops._plain_git(os.path.realpath(checkout), ["rev-parse", "--verify", "HEAD^{commit}"], environ)


def result_json(res, record):
    return {"ok": res.ok, "red": res.red, "flaky": res.flaky, "problem": res.problem, "reused": res.reused,
            "record": res.record, "commands": (record or {}).get("commands", [])}


def run_cli(args, environ, out, *, plugin_root, srt, user_tmp):
    """`engine.py base-check` (cli.py parses and passes the argparse namespace: repo, checkout, sha, config, force,
    json). Exit code 0 green, 4 red / refused."""
    checkout = os.path.realpath(args.checkout or os.getcwd())
    try:
        sha = args.sha or head_sha(checkout, environ)
        if args.config:
            with open(args.config, "rb") as f:
                text = f.read().decode("utf-8")
        else:
            text = committed_config(checkout, sha, environ)
    except (gitops.GitError, OSError, UnicodeDecodeError) as e:
        out.write(f"refused: {e}\n")
        return EXIT_REFUSED
    if text is None:
        out.write(f"refused: {defaults.ENGINE_SETTINGS} is not committed at {sha[:12]} (use --config FILE)\n")
        return EXIT_REFUSED
    home = pathsmod.engine_home(environ)
    res = check(BaseCheckRequest(repo=args.repo, checkout=checkout, sha=sha, config_text=text, engine_home=home,
                                 plugin_root=plugin_root, environ=environ, srt=srt, user_tmp=user_tmp, force=args.force,
                                 out=None if args.json else out))
    if args.json:
        rec = store.read_record(pathsmod.EnginePaths(home, args.repo, ISSUE), res.record, "base-green")
        out.write(json.dumps(result_json(res, rec), ensure_ascii=False, indent=2) + "\n")
    else:
        what = "green" if res.ok else (f"refused ({res.problem})" if res.problem else "RED: " + ", ".join(res.red))
        out.write(f"base {sha[:12]}: {what}" + (f" — flaky: {', '.join(res.flaky)}" if res.flaky else "") + "\n")
    return EXIT_OK if res.ok else EXIT_REFUSED
