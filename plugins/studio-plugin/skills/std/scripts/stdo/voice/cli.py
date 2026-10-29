"""check_assets.py <video> --actors | --output <o> [--lang l] · check_tts.py <video> [--lang l] · audition.py <video> [--lang l]
(m1-plan §8). Each writes its stage's check result (`checks/cast.json` · `checks/tts.json` · `checks/audition.json`).

Exit: 0 pass · 1 fail (the result lists why; check_tts names the lines to retry) · 2 usage or setup (no harness, no
video, no script, no s2v; check_assets without --actors or --output; audition without ffmpeg)."""

import json
import os
import shutil
import subprocess
import sys

from .. import criteria, paths, writes
from ..claims import cli as ccli
from ..state import cli as scli, commands as C, schema, stagechecks, store
from ..state.collect import CollectError, Providers
from . import audition as aud, cast, pronounce, tts


def _err(prog, msg):
    sys.stderr.write("std %s: %s\n" % (prog, msg))


def _opts(argv, flags=()):
    o = {"_": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in flags:
            o[a] = True
        elif a == "--lang" and i + 1 < len(argv):
            o[a] = argv[i + 1]
            i += 1
        elif a.startswith("--lang="):
            o["--lang"] = a.split("=", 1)[1]
        elif a.startswith("-"):
            raise ccli.Usage("unknown option: %s" % a)
        else:
            o["_"].append(a)
        i += 1
    if len(o["_"]) != 1:
        raise ccli.Usage("needs one video id")
    return o


def _setup(argv, cwd, flags=()):
    o = _opts(argv, flags)
    _o, repo, vdir, state, lang, ctx = ccli._setup([o["_"][0]] + (["--lang", o["--lang"]] if o.get("--lang") else []),
                                                   cwd)
    root = scli._cfg_of(repo).get("studio_root") or "studio"
    return o, repo, root, vdir, state, lang, ctx


def _write(prog, stage, repo, vdir, state, lang, ctx, providers, result, details, cur=None):
    inp = stagechecks.Inputs(ctx, state, lang, None, cur or {}, providers)
    s2v_id = (cur or {}).get("s2v_version") if schema.STAGE_CHECKS[stage]["s2v"] else None
    p = stagechecks.write(vdir, lang, stage, None, result, details, stagechecks.input_sha(stage, inp, s2v_id))
    ccli._report(stage, result, details.get("problems") or [], os.path.relpath(p, repo))
    return C.OK if result == "pass" else C.FAIL


def _ctx_of(repo):
    cfg = scli._cfg_of(repo)
    return lambda vd, lg: scli._ctx(repo, cfg, vd, lg)


def _run(prog, fn, argv, cwd, *a):
    try:
        return fn(argv, cwd or os.getcwd(), *a)
    except ccli.Usage as e:
        _err(prog, e)
        return C.USAGE
    except schema.SchemaError as e:
        _err(prog, e)
        return e.code or C.USAGE
    except CollectError as e:
        _err(prog, e)
        return e.code
    except paths.UnsafeLocal as e:
        _err(prog, e)
        return C.USAGE
    except store.Busy:
        _err(prog, "the video's state is busy (another Studio command): wait and run it again")
        return C.BUSY


# ---------- cast ----------

def _assets(argv, cwd, providers, env, runner):
    out_opt = None
    if "--output" in argv:  # the board check (M1g): check_assets.py <video> --output <o>
        i = argv.index("--output")
        if i + 1 >= len(argv):
            raise ccli.Usage("--output needs an output name")
        out_opt, argv = argv[i + 1], argv[:i] + argv[i + 2:]
    o, repo, root, vdir, state, lang, ctx = _setup(argv, cwd, ("--actors",))
    if bool(o.get("--actors")) == bool(out_opt):
        raise ccli.Usage("check_assets.py <video> --actors (cast) | --output <o> (board)")
    if out_opt:
        if out_opt not in schema.current_outputs(state, lang):
            raise ccli.Usage("output %s is not in the brief" % out_opt)
        from .. import board
        result, details, cur = board.check(repo, vdir, state, lang, ctx, out_opt, providers, env, runner)
        inp = stagechecks.Inputs(ctx, state, lang, out_opt, cur, providers)
        p = stagechecks.write(vdir, lang, "board", out_opt, result, details,
                              stagechecks.input_sha("board", inp, cur.get("s2v_version")))
        ccli._report("board", result, details["problems"], os.path.relpath(p, repo))
        return C.OK if result == "pass" else C.FAIL
    result, details, cur = cast.check(repo, root, vdir, state, lang, ctx, providers, env, runner, _ctx_of(repo))
    for line in pronounce.conflict_lines(details["conflicts"]):
        sys.stdout.write("reading elsewhere: %s\n" % line)
    return _write("check_assets", "cast", repo, vdir, state, lang, ctx, providers, result, details, cur)


def assets_main(argv, providers=None, env=None, cwd=None, runner=None):
    return _run("check_assets", _assets, argv, cwd, providers or Providers(), dict(os.environ if env is None else env),
                runner)


# ---------- tts ----------

def _manifest(vdir, lang):
    try:
        with open(os.path.join(vdir, "audio", lang, "manifest.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _tts(argv, cwd, providers):
    o, repo, root, vdir, state, lang, ctx = _setup(argv, cwd)
    problems = []
    try:
        crit = criteria.read(repo, state.get("kind"))
        cer_max = crit["cer_max"].get(lang)
    except criteria.Missing as e:
        crit, cer_max = None, None
        problems.append("the format's criteria cannot be read (%s)" % e)
    sentences = providers.sentences(ctx)
    ins = providers.inspect(ctx)
    cur = providers.collect(ctx, state, lang, ins=ins)
    retry, exempt, warning = [], [], None
    if cer_max is None and crit is not None:
        problems.append("the format gives no cer_max for %s" % lang)
    if crit is not None and cer_max is not None:
        old = state["langs"][lang].get("tts_retries") or {}
        p, retry, exempt, new = tts.judge(sentences, cer_max, lang, old, _manifest(vdir, lang))
        problems += p
        if new != old:
            _record_retries(vdir, lang, new)
        warning = tts.length_warning(tts.seconds(_manifest(vdir, lang), sentences), crit["length_seconds"])
    if cur.get("audio") is None:
        problems.append("the audio hash cannot be computed: %s" % "; ".join((cur.get("reasons") or {}).get(
            "audio") or ["no reason given"]))
    ccli._atomic(tts.exemptions_path(vdir, lang), tts.exemptions_text(exempt))
    details = {"problems": problems, "retry": retry, "exempted": [e["id"] for e in exempt], "length_warning": warning}
    code = _write("check_tts", "tts", repo, vdir, state, lang, ctx, providers, "fail" if problems else "pass",
                  details, cur)
    if retry:
        sys.stdout.write("retry: python3 .claude/studio/scripts/lock.py run --kind tts -- node %s tts %s %s\n" % (
            os.path.join(ctx["s2v_path"], "packages", "cli", "dist", "main.js"),
            os.path.relpath(ctx["script"], repo), " ".join("--retry %s" % r for r in retry)))
    if exempt:
        sys.stdout.write("exempted (shown at ②): %s\n" % ", ".join(e["id"] for e in exempt))
    if warning:
        sys.stdout.write("warning: %s\n" % warning)
    return code


def _record_retries(vdir, lang, new):
    """The per-sentence retry records go into the language state (the guard protects it; V2)."""
    from ..state import store

    def change(s):
        s["langs"][lang]["tts_retries"] = new
    store.write(vdir, {"event": "tts-retries", "lang": lang, "retries": new}, change)


def tts_main(argv, providers=None, cwd=None):
    return _run("check_tts", _tts, argv, cwd, providers or Providers())


# ---------- audition ----------

def _ffmpeg(argv):
    try:
        return subprocess.run(argv, capture_output=True, timeout=600).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 127


def out_dir(repo, root, state, lang):
    return os.path.join(repo, root, "out", state["video"], lang, "audition")


def _audition(argv, cwd, providers, runner):
    o, repo, root, vdir, state, lang, ctx = _setup(argv, cwd)
    if runner is None and shutil.which("ffmpeg") is None:
        raise ccli.Usage("ffmpeg is not on PATH (the audition is joined with it)")
    sentences = providers.sentences(ctx)
    manifest = _manifest(vdir, lang) or {}
    rec2 = state["langs"][lang]["approved"].get("2")
    previous = rec2.get("sentences") if isinstance(rec2, dict) else None
    try:
        with open(tts.exemptions_path(vdir, lang), encoding="utf-8") as f:
            exempt = (json.load(f) or {}).get("lines") or []
    except (OSError, ValueError, AttributeError):
        exempt = []
    chg, _why = pronounce.read(pronounce.path_changes(vdir, lang))
    clips = aud.pick(sentences, previous, exempt, sorted(chg or {}))
    problems, wavs = [], []
    for s, _w in clips:
        e = (manifest.get("entries") or {}).get(s.get("lockKey"))
        wav = os.path.join(vdir, "audio", lang, e["src"]) if isinstance(e, dict) and e.get("src") else None
        if not wav or not os.path.isfile(wav):
            problems.append("%s has no audio file in the lock" % s.get("id"))
        else:
            wavs.append(wav)
    d = out_dir(repo, root, state, lang)
    out = os.path.join(d, "narrator.wav")
    if not clips:
        problems.append("nothing to audition (no synthesized sentence)")
    elif not problems:
        code = aud.assemble(wavs, out, runner or _ffmpeg)
        if code != 0:
            problems.append("ffmpeg could not join the clips (exit %d)" % code)
    shared = pronounce.head_shared(repo) or {}
    lines = pronounce.conflict_lines(pronounce.conflicts(repo, root, state["video"], chg or {}, shared, providers,
                                                         _ctx_of(repo)))
    os.makedirs(d, exist_ok=True)
    md = aud.markdown(state["video"], lang, clips, lines, changes=chg or {})
    _plain_write(os.path.join(d, "audition.md"), md)  # out/ is not a protected record (its sha is in the check)
    details = {"problems": problems, "clips": [[s.get("id"), w] for s, w in clips],
               "narrator_wav": os.path.relpath(out, repo)}
    code = _write("audition", "audition", repo, vdir, state, lang, ctx, providers, "fail" if problems else "pass",
                  details)
    if code == C.OK:
        sys.stdout.write("listen: %s · read: %s\n" % (os.path.relpath(out, repo),
                                                     os.path.relpath(os.path.join(d, "audition.md"), repo)))
    return code


def _plain_write(p, text):
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)


def audition_main(argv, providers=None, cwd=None, runner=None):
    return _run("audition", _audition, argv, cwd, providers or Providers(), runner)


def assets_entry():
    writes.enable()  # the check result (P-STATE) is written from this entry
    return assets_main(sys.argv[1:])


def tts_entry():
    writes.enable()  # the check result and exemptions.json (P-STATE)
    return tts_main(sys.argv[1:])


def audition_entry():
    writes.enable()
    return audition_main(sys.argv[1:])
