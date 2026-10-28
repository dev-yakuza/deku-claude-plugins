"""resolve_assets.py <video> [--lang l] · check_scope.py <video> (m1-plan §6.1 · §6.2).

resolve_assets.py exit: 0 every image judged (usable or not — see work/assets.json) · 1 the source copy cannot be read
(record-source first) · 2 setup (no harness, no such video, bad web_roots / source settings).
check_scope.py exit: 0 the source may be used and every image has its scope · 1 refused (not public, internal, or
assets.json missing/stale) · 2 setup · 4 the internal overlay is missing or changed (the person recreates it)."""

import json
import os
import sys

from .. import paths
from ..state import cli as scli, schema, store
from ..state.collect import frozen_copy_path
from ..state.hashes import file_sha
from . import assets, scope


def _err(prog, msg):
    sys.stderr.write("std %s: %s\n" % (prog, msg))


def _video(argv, cwd):
    if len(argv) != 1 or argv[0].startswith("-"):
        raise assets.AssetError(2, "needs one video id")
    try:
        repo, cfg = scli._repo(cwd)
    except scli.Usage as e:
        raise assets.AssetError(2, str(e))
    root = cfg.get("studio_root") or "studio"
    why = paths.local_problem(repo, root)
    if why:
        raise assets.AssetError(2, why)
    try:
        vdir = store.video_dir(repo, root, argv[0])
        state = store.read_state(vdir)
    except schema.SchemaError as e:
        raise assets.AssetError(e.code or 2, str(e))
    if state["source"].get("kind") != "repo-md":
        raise assets.AssetError(2, "source kind %r is not supported yet" % state["source"].get("kind"))
    return repo, cfg, vdir, state


def resolve_main(argv, cwd=None):
    try:
        repo, cfg, vdir, state = _video(argv, cwd or os.getcwd())
        copy = frozen_copy_path(vdir, state["source"])
        data = assets.build(repo, vdir, state["video"], state["source"]["path"], copy, cfg)
        assets.write(vdir, data)
    except assets.AssetError as e:
        _err("resolve_assets", e)
        return e.code
    usable = [i for i in data["images"] if i["status"] == "ok"]
    sys.stdout.write("%d image reference(s): %d usable, %d not usable → work/assets.json\n"
                     % (len(data["images"]), len(usable), len(data["images"]) - len(usable)))
    if data["unparsed"]["count"]:
        sys.stdout.write("%d line(s) look like an image but were not parsed (lines %s) — check them by hand; a script "
                         "may use only usable entries of work/assets.json\n"
                         % (data["unparsed"]["count"], ", ".join(map(str, data["unparsed"]["lines"]))))
    hidden = data["unparsed"].get("hidden_by_comment")
    if hidden:
        sys.stdout.write("%d image-like line(s) hidden by an HTML comment from line %d (it never closes)%s — check "
                         "them by hand\n" % (len(hidden["lines"]), hidden["from"],
                                              ": lines " + ", ".join(map(str, hidden["lines"])) if hidden["lines"]
                                              else ""))
    for i in data["images"]:
        sys.stdout.write("  %s line %d %s: %s%s (floor %s)\n" % (
            i["id"], i["line"], i["ref"] or "(none)", i["status"], " — " + i["reason"] if i["reason"] else "",
            i["floor"]))
    return 0


def _overlay(repo, cfg, env):
    from ..commit.harness import overlay_terms
    st, _terms = overlay_terms(repo, cfg, env)
    data = None
    if st == "ok":
        try:
            with open(os.path.join(repo, ".claude", "studio", "local", "config.internal.json"), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
    return st, data


def scope_main(argv, cwd=None, env=None):
    try:
        repo, cfg, vdir, state = _video(argv, cwd or os.getcwd())
        copy_sha = file_sha(frozen_copy_path(vdir, state["source"]))
        if copy_sha is None:
            raise assets.AssetError(1, "no source copy — run state.py record-source first")
        st, data = _overlay(repo, cfg, dict(os.environ if env is None else env))
        e = dict(os.environ if env is None else env)
        out = scope.check(repo, vdir, state, cfg, copy_sha, st, data, scope.fingerprint(repo, cfg, e))
        assets.write(vdir, out)
    except (assets.AssetError, scope.ScopeError) as e:
        _err("check_scope", e)
        return e.code
    counts = {}
    for i in out["images"]:
        counts[i["scope"]] = counts.get(i["scope"], 0) + 1
    sys.stdout.write("source %s: may be used (%s video); images by scope: %s\n" % (
        state["source"]["path"], state.get("scope"), ", ".join("%s %d" % kv for kv in sorted(counts.items()))
        or "none"))
    if out["scope_check"].get("note"):
        sys.stdout.write("note: %s\n" % out["scope_check"]["note"])
    sys.stdout.write("next: python3 .claude/studio/scripts/state.py record-source %s\n" % state["video"])
    return 0


def resolve_entry():
    from .. import writes
    writes.enable()  # assets.json (P-STATE) is written from this entry
    return resolve_main(sys.argv[1:])


def scope_entry():
    from .. import writes
    writes.enable()
    return scope_main(sys.argv[1:])
