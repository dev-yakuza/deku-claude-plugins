"""Current values for the router (m0b1-plan §1, §4): s2v inspect, brief, source, render and copy.
Providers are replaced by tests (import), never by flags or environment variables."""

import json
import os
import subprocess

from . import hashes


class CollectError(Exception):
    def __init__(self, msg, code=1):
        Exception.__init__(self, msg)
        self.code = code


def run_inspect(s2v_path, script, hash_version=None):
    """`s2v inspect <script> --json` (no lock). exit 1: script errors, 2: usage — both fail here."""
    if not s2v_path:
        raise CollectError("config.s2v.path is not set", 2)
    cmd = ["node", os.path.join(s2v_path, "packages", "cli", "dist", "main.js"), "inspect", script, "--json"]
    if hash_version is not None:
        cmd += ["--hash-version", str(hash_version)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CollectError("cannot run s2v inspect: %s" % e)
    err = out.stderr.strip()
    if "Cannot find module" in err or "MODULE_NOT_FOUND" in err:
        raise CollectError("s2v is not built or config.s2v.path is wrong (node: %s)" % err.splitlines()[0])
    if out.returncode == 2:
        raise CollectError("s2v inspect refused (usage): %s" % err)
    if out.returncode == 1 and " error " in err:
        raise CollectError("s2v inspect found errors in the script:\n%s" % err)
    if out.returncode != 0:
        raise CollectError("s2v inspect failed (exit %d): %s" % (out.returncode, err))
    try:
        return json.loads(out.stdout)
    except ValueError as e:
        raise CollectError("s2v inspect printed no JSON: %s" % e)


class Providers(object):
    def __init__(self, inspect=None, source=None):
        self.inspect = inspect or (lambda ctx: run_inspect(ctx["s2v_path"], ctx["script"]))
        self.source = source or default_source

    def collect(self, ctx, state, lang):
        ins = self.inspect(ctx)
        if ins.get("lang") != lang:
            raise CollectError("the script's lang %r is not %r" % (ins.get("lang"), lang))
        names = [o.get("name") for o in ins.get("outputs", [])]
        missing = [o for o in state["brief"]["outputs"] if o not in names]  # the router sends these to script
        h = ins["hashes"]
        live, text = self.source(ctx, state)
        L = state["langs"][lang]
        out_dir = os.path.join(ctx["repo"], ctx["studio_root"], "out", state["video"], lang)
        copy_dir = os.path.join(ctx["repo"], ctx["studio_root"], "copy", state["video"], lang)
        render = {o: hashes.render_sha(out_dir, o, lang, proxy=bool(L["renders"].get(o, {}).get("proxy")))
                  for o in state["brief"]["outputs"]}
        copies = {}
        for p in state["brief"]["platforms"]:
            path = L["copies"].get(p, {}).get("path") or os.path.join(copy_dir, p + ".md")
            copies[p] = hashes.file_sha(path if os.path.isabs(path) else os.path.join(ctx["repo"], path))
        return {
            "s2v_version": ins.get("s2v_version"), "stale_build": ins.get("stale_build"),
            "hash_version": ins.get("hash_version"), "outputs": names,
            "brief_core": state["brief"]["core"], "content": h.get("content"),
            "source_hash": live, "source_live_hash": live, "source_text": text,
            "voice": h.get("voice"), "audio": h.get("audio"), "engine": h.get("engine") or {},
            "presentation": h.get("presentation_by_output") or {}, "reasons": ins.get("reasons") or {},
            "render": render, "copy": copies, "outputs_missing": missing,
        }


def default_source(ctx, state):
    """(live source_hash, the frozen copy's text) for a repository Markdown source."""
    src = state["source"]
    if src.get("kind") != "repo-md":
        raise CollectError("source kind %r is not supported yet" % src.get("kind"))
    live = hashes.source_hash_repo_md(ctx["repo"], src["path"], src.get("images", []))
    if not src.get("frozen_hash"):
        return live, None  # no copy yet: the router sends the work to `source`
    copy = frozen_copy_path(ctx["vdir"], src)
    try:
        with open(copy, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise CollectError("the frozen source copy is missing: %s (%s)" % (copy, e.strerror))
    return live, text


def frozen_copy_path(vdir, src):
    """00-plan §3.5 `work/source/` (the source's pinned copy, never edited): the copied file keeps
    the source's file name. (`work/source.md` is the analysis, not the copy.)"""
    return os.path.join(vdir, "work", "source", os.path.basename(src["path"]))
