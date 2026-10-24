"""`setup.py update plan|apply` (m1-plan §5.4, D-M1-17): the plugin's scripts copied again and its templates compared
three ways, with installed.json as the base.

- Versions: the repository's copy newer than the plugin → refused (3); the same version → only templates; older → the
  scripts are copied again (exactly the manifest's files) and MANIFEST.sha256 replaced.
- Templates (installed.json `templates`): a guide, format, platform or the charter by file, an agent by its persona
  block. local == base → the new template; new == base → left; both changed → left, listed as a conflict until the
  person chooses (`--take <path>=new|local`, part of the hash the person approves). The protected personas (P-PERS) take
  a new block only when the person chose it.
- The plugin's `s2v.min_version` (config template) higher than the repository's → raised, unless a video is in
  progress (D29: refused, 3).
`update apply` needs the person's `갱신 <h12>` answer; then a harness commit (its question shows what changed)."""

import json
import os
import re

from .. import SCRIPTS_VERSION, manifest
from ..state.hashes import hash_of
from . import render
from .common import REFUSED, USAGE, SetupError, read_config, with_evidence, write_text

VERSION_RE = re.compile(r'^SCRIPTS_VERSION = "(\d+)"\s*$', re.M)
# new: the plugin's template (for an agent: its persona block only — the person's frontmatter and notes stay);
# new-file: the whole new file (an agent's frontmatter too); local: keep the repository's (M1c review P2)
CHOICES = ("new", "new-file", "local")


def repo_scripts_version(top):
    p = os.path.join(top, ".claude", "studio", "scripts", "stdo", "__init__.py")
    try:
        with open(p, encoding="utf-8") as f:
            m = VERSION_RE.search(f.read())
    except OSError:
        return None
    return int(m.group(1)) if m else None


def parse_takes(raw):
    out = {}
    for item in [x for x in (raw or "").split(",") if x]:
        path, sep, choice = item.rpartition("=")
        if not sep or choice not in CHOICES or path not in render.TEMPLATED:
            raise SetupError(USAGE, "--take is <path>=new|new-file|local, comma-separated, for the files the plan "
                             "lists: %r" % item)
        out[path] = choice
    return out


def _read(top, rel):
    try:
        with open(os.path.join(top, rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _installed(top):
    raw = _read(top, render.INSTALLED)
    try:
        data = json.loads(raw) if raw is not None else None
    except ValueError:
        data = None
    return data if isinstance(data, dict) and data.get("schema") == 1 else None


def _values(top, cfg, inst):
    if inst and isinstance(inst.get("values"), dict):
        return dict(inst["values"])
    brand = {}
    try:
        brand = json.loads(_read(top, ".claude/studio/brand.json") or "{}")
    except ValueError:
        pass
    return {"LANGUAGE": cfg.get("language") or "ko", "STUDIO_ROOT": cfg.get("studio_root") or "studio",
            "PROJECT_NAME": brand.get("name") or os.path.basename(top), "PURPOSE": "", "PRIORITIES_BY_KIND": "",
            "CHECKED_DATE": ""}


def _in_progress(top, root):
    out = []
    for base in (os.path.join(top, root, "videos"), os.path.join(top, root, "local", "videos")):
        if not os.path.isdir(base):
            continue
        for v in sorted(os.listdir(base)):
            try:
                with open(os.path.join(base, v, "work", "state.json"), encoding="utf-8") as f:
                    st = json.load(f)
            except (OSError, ValueError):
                continue
            if any(isinstance(L, dict) and L.get("status") == "active" for L in (st.get("langs") or {}).values()):
                out.append(v)
    return out


def _semver(t):
    from ..state.flow import _semver as sv
    return sv(t)


def _template_item(rel, local, base_ent, new_text, take):
    """(state, action, base after) of one three-way file."""
    agent = rel.startswith(".claude/agents/")
    if agent:
        new_part = render.persona_block(new_text)
        local_part = render.persona_block(local) if local is not None else None
        base = (base_ent or {}).get("persona")
    else:
        new_part, local_part, base = new_text, local, (base_ent or {}).get("sha")
    new_sha = render.sha(new_part) if new_part is not None else None
    local_sha = render.sha(local_part) if local_part is not None else None
    if local is None:
        state = "missing"
    elif agent and local_part is None:
        state = "conflict"  # the persona markers are gone: only the person can say what to do
    elif local_sha == new_sha:
        state = "same"
    elif base is None:
        state = "conflict"
    elif local_sha == base:
        state = "protected-needs-choice" if rel in render.PROTECTED_PERSONAS else "update"
    elif new_sha == base:
        state = "keep-local"
    else:
        state = "conflict"
    if agent and take == "new" and local is not None and local_part is None:
        raise SetupError(USAGE, "%s has no persona block to replace — choose new-file (the whole file) or local" % rel)
    if take == "new-file":
        action = "write-new-file"
    elif take == "new":
        action = "write-new"
    elif take == "local":
        action = "keep"
    else:
        action = "write-new" if state == "update" else "keep"
    resolved = state in ("same", "update", "keep-local") or take is not None
    item = {"path": rel, "state": state, "action": action, "take": take, "local_sha": local_sha,
            "new_sha": new_sha, "base_after": new_sha if resolved else base, "resolved": resolved}
    if state != "same":
        item["diff"] = _diff(rel, local_part if agent else local, new_part, local, new_text)
    return item


def _diff(rel, local_part, new_part, local, new_text):
    """What the person looks at (M1c review P1): a unified diff (an agent: of its persona block) and, for a format, its
    criteria old → new."""
    import difflib
    a = (local_part or "").splitlines(True)
    b = (new_part or "").splitlines(True)
    text = "".join(difflib.unified_diff(a, b, "repository/" + rel, "plugin/" + rel))
    out = {"unified": text}
    if rel.startswith(".claude/studio/formats/"):
        from ..commit import values
        lines, _f, _c = values.crit_parts([(rel, local.encode("utf-8") if local is not None else None,
                                             new_text.encode("utf-8"))])
        out["criteria"] = lines
    return out


def plan(top, takes_raw=None):
    cfg = read_config(top)
    root = cfg.get("studio_root") or "studio"
    inst = _installed(top)
    takes = parse_takes(takes_raw)
    have, mine = repo_scripts_version(top), int(SCRIPTS_VERSION)
    out = {"scripts_version": {"repo": have, "plugin": mine}, "refused": None}
    if have is not None and have > mine:
        out["refused"] = ("the repository's scripts (version %d) are newer than this plugin's (%d) — update the "
                          "plugin first" % (have, mine))
    # scripts: what copying the plugin's manifest files changes
    want = {}
    for rel in render.script_files():
        with open(os.path.join(render.SCRIPTS, rel), "rb") as f:
            want[rel] = render.sha(f.read().decode("utf-8", "surrogateescape"))
    dst = os.path.join(top, ".claude", "studio", "scripts")
    cur = {}
    if os.path.isdir(dst):
        for d, _dirs, names in os.walk(dst):
            for n in names:
                p = os.path.join(d, n)
                rel = os.path.relpath(p, dst).replace(os.sep, "/")
                if manifest.skip(rel) and rel != manifest.NAME:
                    continue
                with open(p, "rb") as f:
                    cur[rel] = render.sha(f.read().decode("utf-8", "surrogateescape"))
    out["scripts"] = {"replace": sorted(r for r in want if r in cur and cur[r] != want[r]),
                      "add": sorted(r for r in want if r not in cur),
                      "remove": sorted(r for r in cur if r not in want)}
    # templates, three ways
    vals = _values(top, cfg, inst)
    news = render.templated(vals)
    base_tpl = (inst or {}).get("templates") or {}
    items = [_template_item(rel, _read(top, rel), base_tpl.get(rel), news[rel], takes.get(rel)) for rel in news]
    out["templates"] = items
    out["installed_missing"] = inst is None
    # s2v.min_version
    tpl_cfg = json.loads(render.template("studio/config.json.tmpl", {"LANGUAGE": "ko", "STUDIO_ROOT": "studio"}))
    old_min = (cfg.get("s2v") or {}).get("min_version") if isinstance(cfg.get("s2v"), dict) else None
    new_min = tpl_cfg["s2v"]["min_version"]
    raise_min = _semver(new_min) is not None and (_semver(old_min) is None or _semver(new_min) > _semver(old_min))
    out["min_version"] = {"repo": old_min, "plugin": new_min, "raise": bool(raise_min)}
    if raise_min:
        busy = _in_progress(top, root)
        if busy and not out["refused"]:
            out["refused"] = ("raising s2v.min_version (%s → %s) while videos are in progress (%s) — finish or "
                              "abandon them first (D29)" % (old_min, new_min, ", ".join(busy)))
    core = {"scripts_version": out["scripts_version"], "scripts": out["scripts"],
            "templates": [[i["path"], i["state"], i["action"], i["local_sha"], i["new_sha"]] for i in items],
            "min_version": out["min_version"], "takes": sorted(takes.items())}
    out["h12"] = hash_of(core)[:12]
    out["label"] = "갱신 %s" % out["h12"]
    out["conflicts"] = [i["path"] for i in items if not i["resolved"]]
    out["_values"] = vals
    out["_news"] = news
    out["_installed"] = inst
    return out


def public(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def apply(top, expect, takes_raw, argv, proxy=False):
    if proxy:
        raise SetupError(USAGE, "updating Studio is the person's decision: the proxy mode cannot (--proxy refused)")
    p = plan(top, takes_raw)
    if p["refused"]:
        raise SetupError(REFUSED, p["refused"])
    if expect != p["h12"]:
        if not expect:
            raise SetupError(USAGE, "show the person the plan (update plan) and ask for \"%s\", then run this with "
                                    "--expect %s" % (p["label"], p["h12"]))
        raise SetupError(1, "--expect %s is not this update's hash (%s) — show the plan again" % (expect, p["h12"]))

    def write():
        from .initcmd import copy_scripts
        copy_scripts(top)
        wrote = []
        for i in p["templates"]:
            if i["action"] not in ("write-new", "write-new-file"):
                continue
            rel = i["path"]
            new_text = p["_news"][rel]
            local = _read(top, rel)
            if i["action"] == "write-new" and rel.startswith(".claude/agents/") and local is not None and \
                    render.persona_block(local) is not None:
                text = render.replace_persona(local, render.persona_block(new_text))  # the block only (P2)
            else:
                text = new_text
            write_text(top, rel, text)
            wrote.append(rel)
        if p["min_version"]["raise"]:
            from .configcmd import write_config
            cfg = read_config(top)
            cfg.setdefault("s2v", {})["min_version"] = p["min_version"]["plugin"]
            write_config(top, cfg)
            wrote.append(".claude/studio/config.json")
        inst = render.installed(p["_values"])
        old = (p["_installed"] or {}).get("templates") or {}
        for i in p["templates"]:
            if not i["resolved"]:  # left for the person: offered again next time
                prev = old.get(i["path"])
                if prev is None:
                    del inst["templates"][i["path"]]
                else:
                    inst["templates"][i["path"]] = prev
        write_text(top, render.INSTALLED, render.dump_json(inst))
        wrote.append(render.INSTALLED)
        return wrote
    wrote = with_evidence(top, argv, p["label"], False, write, "update apply")
    return dict(public(p), wrote=wrote, scripts_copied=True)

