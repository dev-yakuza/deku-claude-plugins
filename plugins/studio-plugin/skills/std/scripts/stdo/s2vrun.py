"""run_s2v.py — s2v's render and snapshot as Studio runs them (m1-plan §4.2, D-M1-14 · D-M1-14b).

    run_s2v.py render <video> --output o [--lang l]
    run_s2v.py snapshot <video> --output o [--lang l] [--begin-end]

The wrapper puts the command line together itself (`node <machine.json's s2v>/packages/cli/dist/main.js …`, the
frozen audio, the results folder `<sr>/out/<video>/<lang>/`); the agent chooses nothing in it. The proxy watermark
comes from the state only: it is added when this is a proxy session (the guard's own rule, STUDIO_SANDBOX) or when
any of ①, ② and ③ (this output) has no current record of a person (`approved_by: human`) — ④a's own record is not
looked at, so a person can approve ④a on an unmarked render once ①–③ are theirs (the hand-over, v3 N3 · v4 R5).

render writes its result to `work/<l>/checks/render--<o>.json` (P-STATE; `state.py record-render` reads it): exit
code, the `ok:` / `CHECK FAILED:` and `→ … (Ns)` lines (s2v prints them on stderr), the result file and its sha, the
watermark. `result` is pass only for exit 0 with an `ok:` line and the file present.
snapshot runs `state.py shown <video> 3 --output o --begin`, the snapshot, then `shown … --end` (③'s rules as
they are) and prints the hash12 for the ③ question.

One wrapper at a time per (video, output, language): a second one exits 5.
Exit: 0 ok · 1 s2v failed (the check file says why) · 2 usage/setup · 5 busy."""

import contextlib
import io
import os
import re
import subprocess
import sys
import time

from . import machine, paths, sandbox
from .state import cli as scli, commands, schema, stagechecks, store
from .state.collect import CollectError, Providers

C = commands
OK_RE = re.compile(r"^ok: ")
FAILED_RE = re.compile(r"^CHECK FAILED: ")
ARROW_RE = re.compile(r"^→ (.+\.mp4) \(([0-9.]+)s\)$")
TIMEOUT = 6 * 3600
END_TRIES, END_WAIT = 5, 2.0  # shown --end after the snapshot: about 10 s of retries while the state lock is busy


class Usage(Exception):
    pass


def _err(msg):
    sys.stderr.write("std run_s2v: %s\n" % msg)


def watermark(state, lang, output, env, repo):
    """(add the proxy watermark, why) — from the state and the session only (D-M1-14b)."""
    if sandbox.active(env, repo):
        return True, "a proxy session (STUDIO_SANDBOX): its renders were not seen by a person"
    A = state["langs"][lang]["approved"]
    recs = [("1", A.get("1")), ("2", A.get("2")), ("3", (A.get("3") or {}).get(output))]
    for g, r in recs:
        if not isinstance(r, dict):
            return True, "%s has no approval yet" % g
        if r.get("approved_by") != "human":
            return True, "%s was approved by the proxy mode" % g
    return False, None


def argv_for(s2v_path, mode, script, output, out_dir, mark):
    main_js = os.path.join(s2v_path, "packages", "cli", "dist", "main.js")
    if mode == "render":
        args = ["node", main_js, "render", script, "--output", output, "--frozen-audio", "--out-dir", out_dir]
        if mark:
            args += ["--watermark", "proxy"]
        return args
    return ["node", main_js, "snapshot", script, "--output", output, "--frozen-audio", "--frames", "--out-dir",
            out_dir]


def drop_other_render(out_dir, output, lang, mark):
    """Remove the render under the other name (`.proxy.*` before an unmarked render, the unmarked set before a marked
    one; M1b review Y7): out/ then holds one render of the output, the one the state records."""
    from .state.hashes import RENDER_EXTS
    removed = []
    for ext in RENDER_EXTS:
        n = "%s.%s.%s%s" % (output, lang, "" if mark else "proxy.", ext)
        p = os.path.join(out_dir, n)
        if os.path.isfile(p) and not os.path.islink(p):
            os.remove(p)
            removed.append(n)
    return removed


def _run(argv, env, cwd):
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", "cannot run s2v: %s" % e
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def parse_render(stderr):
    ok = failed = arrow = None
    for line in stderr.splitlines():
        line = line.rstrip("\r")
        if OK_RE.match(line):
            ok = line
        elif FAILED_RE.match(line):
            failed = line
        else:
            m = ARROW_RE.match(line)
            if m:
                arrow = line
    return ok, failed, arrow


def _opts(rest):
    out = {"_": []}
    it = iter(rest)
    for a in it:
        if a in ("--output", "--lang"):
            v = next(it, None)
            if v is None:
                raise Usage("%s needs a value" % a)
            out[a] = v
        elif a.startswith(("--output=", "--lang=")):
            k, v = a.split("=", 1)
            out[k] = v
        elif a == "--begin-end":
            out[a] = True
        elif a.startswith("-"):
            raise Usage("unknown option: %s" % a)
        else:
            out["_"].append(a)
    return out


def main(argv, providers=None, env=None, cwd=None, runner=None):
    env = dict(os.environ if env is None else env)
    providers = providers or Providers()
    runner = runner or _run
    cwd = cwd or os.getcwd()
    try:
        if not argv or argv[0] not in ("render", "snapshot"):
            raise Usage("run_s2v.py render|snapshot <video> --output o [--lang l]")
        mode = argv[0]
        o = _opts(argv[1:])
        if len(o["_"]) != 1 or not o.get("--output"):
            raise Usage("%s needs a video id and --output" % mode)
        if mode == "render" and o.get("--begin-end"):
            raise Usage("--begin-end is for snapshot")
        try:
            repo, cfg = scli._repo(cwd)
        except scli.Usage as e:
            raise Usage(str(e))
        root = cfg.get("studio_root") or "studio"
        unsafe = paths.local_problem(repo, root)
        if unsafe:
            raise Usage(unsafe)
        vdir = store.video_dir(repo, root, o["_"][0])
        state = store.read_state(vdir)
        lang = o.get("--lang") or state["source_lang"]
        if lang not in state["langs"]:
            raise Usage("no language %s in %s" % (lang, state["video"]))
        output = o["--output"]
        if output not in schema.current_outputs(state, lang):
            raise Usage("output %s is not in the brief" % output)
        s2v_path = machine.s2v_path(repo)
        if s2v_path is None:
            raise Usage(machine.HINT)
        ctx = scli._ctx(repo, cfg, vdir, lang)
        if not os.path.isfile(ctx["script"]):
            raise Usage("no script yet: %s" % os.path.relpath(ctx["script"], repo))
        out_dir = os.path.join(repo, root, "out", state["video"], lang)
        lock_path = os.path.join(vdir, "work", lang, ".run_s2v.%s.lock" % output)
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with store.Lock(lock_path, wait=0.0):
            if mode == "render":
                return _render(repo, vdir, state, lang, output, ctx, out_dir, s2v_path, providers, env, runner)
            return _snapshot(repo, vdir, lang, output, ctx, out_dir, s2v_path, providers, env, runner, cwd)
    except Usage as e:
        _err(str(e))
        return C.USAGE
    except schema.SchemaError as e:
        _err(str(e))
        return e.code
    except CollectError as e:
        _err(str(e))
        return e.code
    except store.Busy:
        _err("another run_s2v.py is working on this output: wait for it")
        return C.BUSY
    except store.Unsupported as e:
        _err(str(e))
        return C.USAGE
    except paths.UnsafeLocal as e:
        _err(str(e))
        return C.USAGE


def _render(repo, vdir, state, lang, output, ctx, out_dir, s2v_path, providers, env, runner):
    mark, why = watermark(state, lang, output, env, repo)
    ver = providers.version(ctx)
    if not isinstance(ver, dict) or not ver.get("id"):
        raise CollectError("s2v --version --json gave no id")
    argv = argv_for(s2v_path, "render", ctx["script"], output, out_dir, mark)
    removed = drop_other_render(out_dir, output, lang, mark)
    code, _stdout, stderr = runner(argv, env, repo)
    ok, failed, arrow = parse_render(stderr)
    mp4 = os.path.join(out_dir, "%s.%s.%smp4" % (output, lang, "proxy." if mark else ""))
    from .state.hashes import file_sha
    sha = file_sha(mp4)
    passed = code == 0 and bool(ok) and not failed and sha is not None
    details = {"exit": code, "ok_line": ok, "check_failed_line": failed, "arrow_line": arrow,
               "mp4": os.path.relpath(mp4, repo).replace(os.sep, "/"), "mp4_sha": sha, "watermark": mark,
               "watermark_why": why, "s2v_id": ver.get("id"), "removed_other_name": removed,
               "stderr_tail": stderr.strip().splitlines()[-20:]}
    inp = stagechecks.Inputs(ctx, state, lang, output, render_proxy=mark)
    stagechecks.write(vdir, lang, "render", output, "pass" if passed else "fail", details,
                      stagechecks.input_sha("render", inp, ver.get("id")))
    sys.stdout.write("%s %s → %s%s\n" % ("rendered" if passed else "render FAILED", output, details["mp4"],
                                         " (proxy watermark: %s)" % why if mark else ""))
    sys.stdout.write("next: python3 .claude/studio/scripts/state.py record-render %s --output %s%s\n"
                     % (state["video"], output, "" if lang == state["source_lang"] else " --lang %s" % lang))
    return C.OK if passed else C.FAIL


def _state_cli(argv, providers, cwd):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = scli.main(argv, providers=providers, cwd=cwd)
    return code, out.getvalue(), err.getvalue()


def _snapshot(repo, vdir, lang, output, ctx, out_dir, s2v_path, providers, env, runner, cwd):
    video = os.path.basename(vdir)
    extra = [] if lang == store.read_state(vdir)["source_lang"] else ["--lang", lang]
    code, out, err = _state_cli(["shown", video, "3", "--output", output, "--begin"] + extra, providers, repo)
    if code != 0:
        sys.stderr.write(err)
        return code
    argv = argv_for(s2v_path, "snapshot", ctx["script"], output, out_dir, False)
    scode, _stdout, stderr = runner(argv, env, repo)
    if scode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-20:])
        _err("s2v snapshot failed (exit %d):\n%s" % (scode, tail))
        return C.FAIL
    for attempt in range(END_TRIES):
        code, out, err = _state_cli(["shown", video, "3", "--output", output, "--end"] + extra, providers, repo)
        if code != C.BUSY:
            break
        # another state.py held the video's lock: the stills are written already, so try --end again (Z5)
        time.sleep(END_WAIT)
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


def entry():
    store.enable_writes()  # this entry runs state.py's shown in-process
    return main(sys.argv[1:])

