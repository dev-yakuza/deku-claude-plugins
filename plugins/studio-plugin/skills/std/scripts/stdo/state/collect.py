"""Current values for the router (m0b1-plan §1, §4): s2v inspect, brief, source, render and copy.
Providers are replaced by tests (import), never by flags or environment variables."""

import json
import os
import subprocess

from .. import machine
from . import hashes, schema


class CollectError(Exception):
    def __init__(self, msg, code=1):
        Exception.__init__(self, msg)
        self.code = code


def run_inspect(s2v_path, script, hash_version=None):
    """`s2v inspect <script> --json` (no lock). exit 1: script errors, 2: usage — both fail here."""
    if not s2v_path:
        raise CollectError(machine.HINT, 2)
    cmd = ["node", os.path.join(s2v_path, "packages", "cli", "dist", "main.js"), "inspect", script, "--json"]
    if hash_version is not None:
        cmd += ["--hash-version", str(hash_version)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CollectError("cannot run s2v inspect: %s" % e)
    err = out.stderr.strip()
    if "Cannot find module" in err or "MODULE_NOT_FOUND" in err:
        raise CollectError("s2v is not built or this machine's s2v path (.claude/studio/local/machine.json) is "
                           "wrong (node: %s)" % err.splitlines()[0])
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


def run_version(s2v_path):
    """`s2v --version --json` (id, version, commit, dirty, stale_build)."""
    if not s2v_path:
        raise CollectError(machine.HINT, 2)
    cmd = ["node", os.path.join(s2v_path, "packages", "cli", "dist", "main.js"), "--version", "--json"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return json.loads(out.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        raise CollectError("cannot read the s2v version: %s" % e)


def _main_js(s2v_path):
    if not s2v_path:
        raise CollectError(machine.HINT, 2)
    return os.path.join(s2v_path, "packages", "cli", "dist", "main.js")


def _json_call(s2v_path, args, what, ok=(0,), timeout=300):
    cmd = ["node", _main_js(s2v_path)] + list(args)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CollectError("cannot run s2v %s: %s" % (what, e))
    if out.returncode not in ok:
        raise CollectError("s2v %s failed (exit %d): %s" % (what, out.returncode, out.stderr.strip()[-2000:]))
    try:
        return json.loads(out.stdout)
    except ValueError as e:
        raise CollectError("s2v %s printed no JSON: %s" % (what, e))


def run_sentences(s2v_path, script):
    """`s2v sentences <script> --json` (no lock). The JSON comes even when lint finds errors (exit 1, as s2v
    prints it); exit 2 is a usage error."""
    return _json_call(s2v_path, ["sentences", script, "--json"], "sentences", ok=(0, 1))


def run_services_status(s2v_path):
    """`s2v services status --json`: the machine lock as s2v sees it (version 1, state_dir, busy)."""
    data = _json_call(s2v_path, ["services", "status", "--json"], "services status", timeout=120)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise CollectError("s2v services status --json is not version 1")
    return data


class Providers(object):
    def __init__(self, inspect=None, source=None, inspect_at=None, version=None, sentences=None, services=None):
        self.inspect = inspect or (lambda ctx: run_inspect(ctx["s2v_path"], ctx["script"]))
        self.source = source or default_source
        self.inspect_at = inspect_at or (lambda ctx, hv: run_inspect(ctx["s2v_path"], ctx["script"], hash_version=hv))
        self.version = version or (lambda ctx: run_version(ctx["s2v_path"]))
        self.sentences = sentences or (lambda ctx: run_sentences(ctx["s2v_path"], ctx["script"]))
        self.services = services or (lambda ctx: run_services_status(ctx["s2v_path"]))

    def collect(self, ctx, state, lang, ins=None):
        ins = ins if ins is not None else self.inspect(ctx)
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
            if not schema.platform_ok(p):
                copies[p] = None  # a name that is not a platform name never becomes a path (M1h review Y1)
                continue
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
            "credits": hashes.file_sha(os.path.join(ctx["vdir"], "CREDITS.yaml")),
            "proxy_credits": proxy_credits(state, ctx["repo"]),
            # the files the script refers to (s2v lists them with their sha256): inputs of the check results
            "files": ins.get("files") if isinstance(ins.get("files"), list) else None,
        }


def proxy_credits(state, repo, env=None):
    """"<proxy|person> <path> …" for the credits approved in the proxy mode, with the mode of this session — None when
    every credit is a person's (0.0.21, J173). In ③'s tuple and the board check's inputs: after the hand-over the
    person's session sees another value, so the router sends the work back to board, which asks for the person's
    credit before ③ (not only the video commit, J131)."""
    proxied = sorted(p for p, r in (state.get("credits") or {}).items()
                     if isinstance(r, dict) and r.get("approved_by") != "human")
    if not proxied:
        return None
    from .. import sandbox
    mode = "proxy" if sandbox.active(dict(os.environ) if env is None else env, repo) else "person"
    return "%s %s" % (mode, " ".join(proxied))


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
