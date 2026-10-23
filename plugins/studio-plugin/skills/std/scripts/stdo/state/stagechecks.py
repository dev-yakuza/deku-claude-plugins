"""Deterministic check results (m1-plan §4.1, D-M1-12): `work/<l>/checks/<file>[--<scope>].json`.

A stage's check script writes the file (P-STATE: an agent cannot write it); `stage-done` accepts the stage only when
the file says `pass`, was written by this scripts version and its `input_sha` equals the sha of the stage's inputs
recomputed now (`schema.STAGE_CHECKS`). The inputs are files and values; a missing file counts as `null` (so creating
it later is a change too)."""

import datetime
import glob
import json
import os

from .. import SCRIPTS_VERSION, paths as _paths, writes
from . import hashes, schema
from .collect import CollectError, frozen_copy_path

SCHEMA = 1
RESULTS = ("pass", "fail")


class CheckProblem(Exception):
    """The check file does not let the stage finish (exit 1: run the check again)."""


def spec(stage):
    return schema.STAGE_CHECKS.get(stage)


def scope_of(stage, output=None, platform=None):
    s = spec(stage)
    if s is None or s["scope"] is None:
        return None
    return output if s["scope"] == "output" else platform


def name(stage, scope=None):
    return spec(stage)["file"] + ("--%s" % scope if scope else "") + ".json"


def path(vdir, lang, stage, scope=None):
    return os.path.join(vdir, "work", lang, "checks", name(stage, scope))


# ---------- inputs ----------

class Inputs(object):
    """What the input resolvers read: the repository, the video, the language and scope, the current values
    (`collect` — with the files s2v inspect lists) and the providers (s2v sentences)."""

    def __init__(self, ctx, state, lang, scope=None, cur=None, providers=None, render_proxy=None):
        self.ctx, self.state, self.lang, self.scope = ctx, state, lang, scope
        self.cur, self.providers, self.render_proxy = cur or {}, providers, render_proxy

    @property
    def repo(self):
        return self.ctx["repo"]

    @property
    def vdir(self):
        return self.ctx["vdir"]

    def work(self, *parts):
        return os.path.join(self.vdir, "work", self.lang, *parts)

    def rel(self, p):
        try:
            return os.path.relpath(p, self.repo)
        except ValueError:
            return p


def _file(inp, p):
    return [(inp.rel(p), hashes.file_sha(p))]


def _script(inp):
    return _file(inp, inp.ctx["script"])


# the kinds of files `s2v inspect --json` lists (inspect.ts `files.sha(…, kind)`; the fake s2v's shape test pins them)
S2V_FILE_KINDS = ("image", "video", "font", "logo", "thumbnail", "bgm", "character", "recording", "voice")
# a script's and a board's inputs: every file the script shows or plays, not the audio-side ones (M1b review Y6)
NOT_PICTURE_KINDS = ("recording", "voice")


def _script_files(inp):
    files = inp.cur.get("files")
    if not isinstance(files, list):
        return [("files", None)]  # s2v listed no files: the value is "unknown", stable until it is known
    out = []
    for f in files:
        if not isinstance(f, dict):
            continue
        kinds = [k for k in str(f.get("kind") or "").split(",") if k]
        if kinds and all(k in NOT_PICTURE_KINDS for k in kinds):
            continue
        out.append(("file:%s:%s" % (",".join(kinds) or "?", f.get("path")), f.get("sha256")))
    return out or [("files", "none")]


def _config(inp):
    try:
        with open(os.path.join(inp.repo, ".claude", "studio", "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = None
    cfg = cfg if isinstance(cfg, dict) else {}
    return [("config:protected", hashes.hash_of({"visibility": cfg.get("visibility"),
                                                 "web_roots": cfg.get("web_roots")}))]


def _overlay(inp):
    try:
        with open(os.path.join(_paths.backup_root(), _paths.repo_key(inp.repo), "overlay.sha"),
                  encoding="utf-8") as f:
            return [("overlay.sha", f.read().strip() or None)]
    except (OSError, RuntimeError, ValueError):
        return [("overlay.sha", None)]


def _out_dir(inp):
    return os.path.join(inp.repo, inp.ctx["studio_root"], "out", inp.state["video"], inp.lang)


def _render_result(inp):
    o = inp.scope
    proxy = inp.render_proxy
    if proxy is None:
        proxy = bool(inp.state["langs"][inp.lang]["renders"].get(o, {}).get("proxy"))
    return [("render:%s" % o, hashes.render_sha(_out_dir(inp), o, inp.lang, proxy=bool(proxy)))]


def _chapters(inp):
    L = inp.state["langs"][inp.lang]
    outs = [o for o in inp.state["brief"]["platforms"].get(inp.scope, []) if o in schema.current_outputs(inp.state,
                                                                                                         inp.lang)]
    out = []
    for o in sorted(outs):
        proxy = bool(L["renders"].get(o, {}).get("proxy"))
        p = os.path.join(_out_dir(inp), "%s.%s.%schapters.txt" % (o, inp.lang, "proxy." if proxy else ""))
        out += _file(inp, p)
    return out or [("chapters", "none")]


def _copy_text(inp):
    L = inp.state["langs"][inp.lang]
    p = L["copies"].get(inp.scope, {}).get("path") or os.path.join(
        inp.ctx["studio_root"], "copy", inp.state["video"], inp.lang, inp.scope + ".md")
    return _file(inp, p if os.path.isabs(p) else os.path.join(inp.repo, p))


def _sentences(inp):
    if inp.providers is None or getattr(inp.providers, "sentences", None) is None:
        raise CollectError("s2v sentences is needed for the tts check's inputs")
    data = inp.providers.sentences(inp.ctx)
    return [("s2v:sentences", hashes.hash_of(data))]


def _cast_roster(inp):
    files = sorted(glob.glob(os.path.join(inp.repo, glob.escape(inp.ctx["studio_root"]), "cast", "*", "status.json")))
    out = []
    for p in files:
        out += _file(inp, p)
    return out or [("cast:status", "none")]


RESOLVERS = {
    "script": _script,
    "claims_map": lambda i: _file(i, i.work("claims-map.json")),
    "format": lambda i: _file(i, os.path.join(i.repo, ".claude", "studio", "formats", "%s.md" % i.state.get("kind"))),
    "assets_json": lambda i: _file(i, os.path.join(i.vdir, "work", "assets.json")),
    "script_files": _script_files,
    "verify_draft": lambda i: _file(i, i.work("verify.draft.json")),
    "source_copy": lambda i: _file(i, frozen_copy_path(i.vdir, i.state["source"])),
    "cast_roster": _cast_roster,
    "lock_manifest": lambda i: _file(i, os.path.join(i.vdir, "audio", i.lang, "manifest.json")),
    "sentences": _sentences,
    "approved_2": lambda i: [("approved:2", hashes.hash_of(i.state["langs"][i.lang]["approved"].get("2")))],
    "exemptions": lambda i: _file(i, i.work("exemptions.json")),
    "pronounce_changes": lambda i: _file(i, i.work("pronounce-changes.json")),
    "audition_out": lambda i: (_file(i, os.path.join(_out_dir(i), "audition", "narrator.wav"))
                               + _file(i, os.path.join(_out_dir(i), "audition", "audition.md"))),
    "credits": lambda i: _file(i, os.path.join(i.vdir, "CREDITS.yaml")),
    "config_protected": _config,
    "overlay_sha": _overlay,
    "credit_approvals": lambda i: [("state:credits", hashes.hash_of(i.state.get("credits")))],
    "render_result": _render_result,
    "copy_text": _copy_text,
    "platform_rules": lambda i: _file(i, os.path.join(i.repo, ".claude", "studio", "platforms", "%s.md" % i.scope)),
    "chapters": _chapters,
}


def inputs(stage, inp):
    """[(name, sha)] sorted: the stage's input set now."""
    out = []
    for key in spec(stage)["inputs"]:
        out += [(n, v) for n, v in RESOLVERS[key](inp)]
    return sorted(out, key=lambda x: (x[0], str(x[1])))


def input_sha(stage, inp, s2v_id=None):
    s = spec(stage)
    value = {"stage": stage, "scope": inp.scope, "inputs": [list(x) for x in inputs(stage, inp)]}
    if s["s2v"]:
        value["s2v"] = s2v_id
    return hashes.hash_of(value)


# ---------- the file ----------

def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(vdir, lang, stage, scope, result, details, sha):
    """Write the check file atomically (check scripts only: the guard protects it as P-STATE)."""
    writes.check("a check result")
    if result not in RESULTS:
        raise ValueError("result is pass or fail: %r" % (result,))
    s = spec(stage)
    p = path(vdir, lang, stage, scope)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = {"schema": SCHEMA, "stage": stage, "scope": scope, "script": s["script"],
            "scripts_version": SCRIPTS_VERSION, "input_sha": sha, "result": result, "details": details,
            "written_at": _now()}
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return p


def read(vdir, lang, stage, scope=None):
    p = path(vdir, lang, stage, scope)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return None
    except ValueError:
        return {"_unreadable": True}
    return data if isinstance(data, dict) else {"_unreadable": True}


def verify(stage, inp, s2v_id=None):
    """Raise CheckProblem unless the stage's check file lets it finish now (m1-plan §4.1 v3 N2: result, version and
    input sha, all three)."""
    if spec(stage) is None:
        return
    rel = os.path.relpath(path(inp.vdir, inp.lang, stage, inp.scope), inp.repo)
    data = read(inp.vdir, inp.lang, stage, inp.scope)
    if data is None:
        raise CheckProblem("%s has no check result (%s) — run the stage's check (%s)" % (
            stage, rel, spec(stage)["script"]))
    if data.get("_unreadable") or data.get("schema") != SCHEMA:
        raise CheckProblem("%s is unreadable or of another format — run the check again" % rel)
    if data.get("stage") != stage or data.get("scope") != inp.scope or data.get("script") != spec(stage)["script"]:
        raise CheckProblem("%s is not the check result of %s%s" % (rel, stage, " " + inp.scope if inp.scope else ""))
    if data.get("result") != "pass":
        raise CheckProblem("%s: the check failed — fix what it lists and run it again" % rel)
    if data.get("scripts_version") != SCRIPTS_VERSION:
        raise CheckProblem("%s was written by Studio scripts version %s (now %s) — run the check again" % (
            rel, data.get("scripts_version"), SCRIPTS_VERSION))
    if data.get("input_sha") != input_sha(stage, inp, s2v_id):
        raise CheckProblem("%s was checked on other inputs (something it reads changed since) — run the check again"
                           % rel)
