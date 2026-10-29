"""`check_claims.py <video> --narration [--lang l]` (the script stage) · `check_claims.py <video> [--lang l]` (verify)
(m1-plan §7.3 · §7.4). Each writes its stage's check result (`checks/script.json` · `checks/verify-claims.json`);
verify also writes `verify.json` and `verify.md` when it passes (and removes them when it does not).

Exit: 0 pass · 1 fail (the result lists why; for verify: `state.py loop <video> verify`, then the fact-checker again)
· 2 usage or setup (no harness, no such video, no script, no s2v)."""

import json
import os
import sys

from .. import machine, paths, s2vlint, writes
from ..source import assets as assets_mod
from ..state import cli as scli, commands as C, schema, stagechecks, store
from ..state.collect import CollectError, Providers
from . import check


class Usage(Exception):
    pass


def _err(msg):
    sys.stderr.write("std check_claims: %s\n" % msg)


def _opts(argv):
    o = {"_": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--narration":
            o[a] = True
        elif a == "--lang" and i + 1 < len(argv):
            o[a] = argv[i + 1]
            i += 1
        elif a.startswith("--lang="):
            o["--lang"] = a.split("=", 1)[1]
        elif a.startswith("-"):
            raise Usage("unknown option: %s" % a)
        else:
            o["_"].append(a)
        i += 1
    if len(o["_"]) != 1:
        raise Usage("check_claims.py <video> [--narration] [--lang l]")
    return o


def _setup(argv, cwd):
    o = _opts(argv)
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
    ctx = scli._ctx(repo, cfg, vdir, lang)
    if not os.path.isfile(ctx["script"]):
        raise Usage("no script yet: %s" % os.path.relpath(ctx["script"], repo))
    if ctx["s2v_path"] is None:
        raise Usage(machine.HINT)
    return o, repo, vdir, state, lang, ctx


def _report(stage, result, problems, rel):
    if result == "pass":
        sys.stdout.write("%s: pass → %s\n" % (stage, rel))
    else:
        sys.stdout.write("%s: FAIL (%d problem(s)) → %s\n" % (stage, len(problems), rel))
        for p in problems:
            sys.stdout.write("  - %s\n" % p)


def script_check(repo, vdir, state, lang, ctx, providers, env, runner):
    problems = []
    from ..claims.brief import assets_problem
    why = assets_problem(vdir, state)
    if why:
        problems.append(why)
    fail_unread = schema.STAGE_CHECKS["script"]["fail_unread"]
    lint = s2vlint.run(ctx["s2v_path"], ctx["script"], "lint", env=env, runner=runner, lang=lang,
                       fail_unread=fail_unread)
    if not lint.passed:
        problems.append("s2v lint: %s" % (", ".join(sorted(set(d["code"] for d in lint.failures)))
                                          or "exit %d" % lint.code))
    copy = check.copy_text(vdir, state)
    _cm, cm_problems = check.claims_map(vdir, lang, state, copy)
    problems += cm_problems
    ins = providers.inspect(ctx)
    cur = providers.collect(ctx, state, lang, ins=ins)
    sentences = providers.sentences(ctx)
    problems += check.narration_problems(sentences, lang)
    from .. import criteria
    try:
        crit = criteria.read(repo, state.get("kind"))
        with open(ctx["script"], encoding="utf-8") as f:
            problems += check.length_problems(f.read(), schema.current_outputs(state, lang), crit, sentences, lang)
    except criteria.Missing as e:
        problems.append("the format's criteria cannot be read (%s)" % e)
    problems += check.picture_problems(ins, assets_mod.read(vdir))
    details = {"lint": lint.details(), "fail_unread": fail_unread, "problems": problems,
               "screen_text": len(ins.get("screen_text") or []), "sentences": len(sentences or [])}
    result = "fail" if problems else "pass"
    inp = stagechecks.Inputs(ctx, state, lang, None, cur, providers)
    p = stagechecks.write(vdir, lang, "script", None, result, details,
                          stagechecks.input_sha("script", inp, cur.get("s2v_version")))
    _report("script", result, problems, os.path.relpath(p, repo))
    return C.OK if result == "pass" else C.FAIL


def verify_check(repo, vdir, state, lang, ctx, providers):
    w = os.path.join(vdir, "work", lang)
    draft, why = check._read_json(os.path.join(w, "verify.draft.json"), "work/%s/verify.draft.json" % lang)
    copy = check.copy_text(vdir, state)
    cm, problems = check.claims_map(vdir, lang, state, copy)
    if why:
        problems.append(why)
    else:
        ins = providers.inspect(ctx)
        problems += check.draft_problems(draft, cm, copy, providers.sentences(ctx), ins.get("screen_text"),
                                         [x.get("title") for x in ins.get("scenes") or [] if isinstance(x, dict)])
    for name in ("verify.json", "verify.md"):  # a failed or repeated check never leaves the last ones behind
        try:
            os.remove(os.path.join(w, name))
        except OSError:
            pass
    result = "fail" if problems else "pass"
    if result == "pass":
        v = check.verify_json(state, lang, draft, check.file_shas(ctx, vdir, lang, state))
        _atomic(os.path.join(w, "verify.json"), json.dumps(v, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        _atomic(os.path.join(w, "verify.md"), check.verify_md(v))
    inp = stagechecks.Inputs(ctx, state, lang, None)
    p = stagechecks.write(vdir, lang, "verify", None, result, {"problems": problems},
                          stagechecks.input_sha("verify", inp))
    _report("verify", result, problems, os.path.relpath(p, repo))
    if result != "pass":
        sys.stdout.write("next: python3 .claude/studio/scripts/state.py loop %s verify%s, then the fact-checker "
                         "again\n" % (state["video"], "" if lang == state["source_lang"] else " --lang " + lang))
    return C.OK if result == "pass" else C.FAIL


def _atomic(p, text):
    writes.check(os.path.basename(p))
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def main(argv, providers=None, env=None, cwd=None, runner=None):
    providers = providers or Providers()
    env = dict(os.environ if env is None else env)
    try:
        o, repo, vdir, state, lang, ctx = _setup(argv, cwd or os.getcwd())
        if o.get("--narration"):
            return script_check(repo, vdir, state, lang, ctx, providers, env, runner)
        return verify_check(repo, vdir, state, lang, ctx, providers)
    except Usage as e:
        _err(e)
        return C.USAGE
    except schema.SchemaError as e:
        _err(e)
        return e.code or C.USAGE
    except CollectError as e:
        _err(e)
        return e.code
    except paths.UnsafeLocal as e:
        _err(e)
        return C.USAGE


def entry():
    writes.enable()  # the check results, verify.json and verify.md (P-STATE) are written from this entry
    return main(sys.argv[1:])
