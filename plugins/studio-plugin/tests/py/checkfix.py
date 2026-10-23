"""Check results for tests that drive a video through `stage-done` (m1-plan §4.1, M1b).

The check scripts that write `work/<l>/checks/*.json` arrive with their stages (M1d–M1h). Until then a test that only
moves a video along writes a passing result the way a check script would — the same `stagechecks.input_sha` over the
inputs as they are — so `stage-done` still applies its own rule (pass · this scripts version · the input sha) and a
change after the "check" still refuses the stage. A render is made as run_s2v.py records it (the result file, its
check file) and recorded with the real `state.py record-render`."""

import contextlib
import io
import os

from stdo.state import cli, schema, stagechecks, store


def _opt(argv, name):
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _ctx(repo, vdir, lang):
    return cli._ctx(repo, cli._cfg_of(repo), vdir, lang)


def pass_check(repo, video, stage, providers, output=None, platform=None, lang=None, result="pass", details=None):
    """Write the check result a stage's check script would write now (a test stands in for the script)."""
    root = cli._cfg_of(repo).get("studio_root") or "studio"
    vdir = store.video_dir(repo, root, video)
    state = store.read_state(vdir)
    lang = lang or state["source_lang"]
    scope = stagechecks.scope_of(stage, output, platform)
    ctx = _ctx(repo, vdir, lang)
    cur = providers.collect(ctx, state, lang)
    inp = stagechecks.Inputs(ctx, state, lang, scope, cur, providers)
    sha = stagechecks.input_sha(stage, inp, cur.get("s2v_version"))
    return stagechecks.write(vdir, lang, stage, scope, result, details or {"by": "test"}, sha)


def render(repo, video, output, providers, lang=None, body=None, watermark=False, exit_code=0, ok=True,
           check_failed=False):
    """A render as run_s2v.py leaves it (result file + check file), then the real record-render. Returns its exit."""
    root = cli._cfg_of(repo).get("studio_root") or "studio"
    vdir = store.video_dir(repo, root, video)
    state = store.read_state(vdir)
    lang = lang or state["source_lang"]
    d = os.path.join(repo, root, "out", video, lang)
    os.makedirs(d, exist_ok=True)
    mp4 = os.path.join(d, "%s.%s.%smp4" % (output, lang, "proxy." if watermark else ""))
    if body is not None or not os.path.exists(mp4):
        with open(mp4, "wb") as f:
            f.write(body if body is not None else b"auto-mp4")
    from stdo.state.hashes import file_sha
    sha = file_sha(mp4)
    passed = exit_code == 0 and ok and not check_failed
    details = {"exit": exit_code, "ok_line": "ok: 90/90 frames" if ok else None,
               "check_failed_line": "CHECK FAILED: 87/90 frames" if check_failed else None,
               "arrow_line": "→ %s (0.1s)" % mp4, "mp4": os.path.relpath(mp4, repo), "mp4_sha": sha,
               "watermark": watermark, "s2v_id": None}
    ctx = _ctx(repo, vdir, lang)
    cur = providers.collect(ctx, state, lang)
    inp = stagechecks.Inputs(ctx, state, lang, output, cur, providers, render_proxy=watermark)
    stagechecks.write(vdir, lang, "render", output, "pass" if passed else "fail", details,
                      stagechecks.input_sha("render", inp, cur.get("s2v_version")))
    out, err = io.StringIO(), io.StringIO()
    argv = ["record-render", video, "--output", output] + ([] if lang == state["source_lang"] else ["--lang", lang])
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv, providers=providers, cwd=repo)
    if code not in (0, 4):
        raise AssertionError("record-render: %s" % err.getvalue())
    return code


def before_stage_done(repo, argv, providers):
    """Called by the tests' cli wrappers before `stage-done …`: the stage's check result (and a render record)."""
    if len(argv) < 3 or argv[0] != "stage-done" or argv[2] not in schema.STAGE_CHECKS:
        return
    video, stage = argv[1], argv[2]
    output, platform, lang = _opt(argv, "--output"), _opt(argv, "--platform"), _opt(argv, "--lang")
    try:
        root = cli._cfg_of(repo).get("studio_root") or "studio"
        vdir = store.video_dir(repo, root, video)
        state = store.read_state(vdir)
        if not os.path.exists(_ctx(repo, vdir, lang or state["source_lang"])["script"]):
            return  # stage-done refuses it anyway (no script yet)
        if stage == "render" and output:
            L = state["langs"][lang or state["source_lang"]]
            r = L["renders"].get(output) or {}
            from stdo.state.hashes import file_sha
            same = r.get("file") and file_sha(os.path.join(repo, r["file"])) == r.get("sha")
            if (r.get("result") != "pass" or not same) and not L.get("held"):
                render(repo, video, output, providers, lang=lang)  # the test changed the result: render "again"
            return  # a render's check result is the render's own (run_s2v.py, or render() above)
        pass_check(repo, video, stage, providers, output=output, platform=platform, lang=lang)
    except Exception:  # noqa: BLE001 — the stage-done under test reports the real problem
        return


def fixed_sentences(providers, value=None):
    """Tests without s2v: `s2v sentences --json` answers a fixed list (the tts check's inputs)."""
    providers.sentences = lambda ctx: list(value or [{"id": "s:0:0", "lock": None}])
    return providers
