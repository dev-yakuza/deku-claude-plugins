"""`setup.py config get|preview|set` and `narrator preview|set` (m1-plan §5.3 · §5.4, D-M1-5).

The guard lets Studio's scripts write protected files, so the evidence is required here: a protected key of
config.json (the template's `protected_keys` and the fixed list), `s2v.path` (this machine's machine.json) and the
narrator need the person's `설정 <h12>` answer — h12 binds the key, the old and the new value. Other keys are set
without evidence. Every change to a committed file then goes through a harness commit (whose question shows the values).
`studio_root` is refused (moving Studio's folder is `move`, not part of M1). `--proxy` is refused."""

import copy
import json
import os

from .. import machine, narrator
from ..commit.summary import FIXED_PROTECTED
from . import labels as L
from .common import REFUSED, USAGE, SetupError, read_config, with_evidence, write_text

CONFIG_REL = ".claude/studio/config.json"


def protected_keys(cfg):
    more = cfg.get("protected_keys") if isinstance(cfg, dict) else None
    return set(FIXED_PROTECTED) | set(k for k in (more or []) if isinstance(k, str))


def _known_top(cfg):
    """The keys a config may have: the template's (and the ones it already has)."""
    from .render import template
    tpl = json.loads(template("studio/config.json.tmpl", {"LANGUAGE": "ko", "STUDIO_ROOT": "studio"}))
    return set(tpl) | set(cfg)


def _expect_problem(expect, p):
    if not expect:
        return SetupError(USAGE, "this needs the person's answer: show them `%s`, ask for the option \"%s\", then "
                                 "run this again with --expect %s" % (p["line"], p["label"], p["h12"]))
    return SetupError(1, "--expect %s does not match this change (%s) — show it to the person again" % (
        expect, p["h12"]))


def get(top, key=None):
    cfg = read_config(top)
    if key is None:
        return cfg
    if key == "s2v.path":
        return machine.s2v_path(top)
    present, v = L.lookup(cfg, key)
    if not present:
        raise SetupError(USAGE, "config.json has no %s" % key)
    return v


def _old_new(top, cfg, key, raw):
    if key in ("studio_root",) or key.startswith("studio_root."):
        raise SetupError(USAGE, "studio_root is not changed by config (moving Studio's folder is `move`, later)")
    new = L.parse_value(raw)
    if key.startswith("s2v.path") and key != "s2v.path":
        raise SetupError(USAGE, "%s is not a setting: this machine's s2v path is exactly s2v.path (M1c review P6)"
                         % key)
    if key == "s2v.path":
        if not isinstance(new, str) or not os.path.isabs(new):
            raise SetupError(USAGE, "s2v.path is the absolute path of this machine's script2video checkout")
        if not os.path.isfile(os.path.join(new, "packages", "cli", "dist", "main.js")):
            raise SetupError(USAGE, "%s has no packages/cli/dist/main.js (build s2v there first)" % new)
        old = machine.s2v_path(top)
        return old is not None, old, os.path.normpath(new)
    top_key = key.split(".", 1)[0]
    if key == "s2v" and isinstance(new, dict) and "path" in new:
        raise SetupError(USAGE, "this machine's s2v path is not in config.json (the old format) — set it with "
                                "config set s2v.path <absolute path> (machine.json, M1a)")
    if top_key not in _known_top(cfg):
        raise SetupError(USAGE, "%s is not a Studio setting (config.json keys: %s)"
                         % (top_key, ", ".join(sorted(_known_top(cfg)))))
    present, old = L.lookup(cfg, key)
    return present, old, new


def preview(top, key, raw):
    """What `config set` would change, its label and the line the question shows (no writes)."""
    cfg = read_config(top)
    present, old, new = _old_new(top, cfg, key, raw)
    prot = L.is_protected(key, protected_keys(cfg))
    out = {"key": key, "old": old if present else None, "old_present": present, "new": new, "protected": prot,
           "changes": not present or old != new}
    if prot:
        h = L.setting_hash(key, old, new, present)
        out.update(h12=h, label="설정 %s" % h, line=L.config_line(key, old, new, present))
    return out


def _set_dotted(cfg, key, value):
    cur = cfg
    parts = key.split(".")
    for part in parts[:-1]:
        nxt = cur.get(part)
        if nxt is None:
            nxt = cur[part] = {}
        if not isinstance(nxt, dict):
            raise SetupError(USAGE, "%s is not an object in config.json" % part)
        cur = nxt
    cur[parts[-1]] = value


def write_config(top, cfg):
    write_text(top, CONFIG_REL, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def set_(top, key, raw, expect, argv, proxy=False):
    if proxy:
        raise SetupError(USAGE, "config set records the person's settings: the proxy mode cannot (--proxy refused)")
    p = preview(top, key, raw)
    if not p["changes"]:
        raise SetupError(REFUSED, "%s is already %s" % (key, L.canon(p["new"])))

    def write():
        if key == "s2v.path":
            machine.write(top, p["new"])
            return "machine.json"
        cfg = read_config(top)
        new_cfg = copy.deepcopy(cfg)
        _set_dotted(new_cfg, key, p["new"])
        write_config(top, new_cfg)
        return CONFIG_REL
    if not p["protected"]:
        if expect:
            raise SetupError(USAGE, "%s is not protected: set it without --expect" % key)
        return dict(p, wrote=write())
    if expect != p["h12"]:
        raise _expect_problem(expect, p)
    return dict(p, wrote=with_evidence(top, argv, p["label"], False, write, "config set"))


# ---------- the narrator ----------

def _narrator_paths(top, root, nid):
    base = os.path.join(top, root, "cast", nid)
    return base, os.path.join(base, "status.json")


def narrator_preview(top, lang, engine, style, nid="narrator"):
    cfg = read_config(top)
    root = cfg.get("studio_root") or "studio"
    if lang not in narrator.LANGS:
        raise SetupError(USAGE, "the language must be one of %s" % ", ".join(narrator.LANGS))
    if not narrator.ID.match(nid or ""):
        raise SetupError(USAGE, "the narrator id is lowercase letters, digits and -")
    if not narrator.engine_ok(engine):
        raise SetupError(USAGE, "the engine must be qwen:<built-in speaker> (%s)" % ", ".join(sorted(
            narrator.QWEN_SPEAKERS)))
    if not isinstance(style, str) or len(style) > narrator.STYLE_MAX or "\n" in style:
        raise SetupError(USAGE, "the style is one line of at most %d characters" % narrator.STYLE_MAX)
    _base, sp = _narrator_paths(top, root, nid)
    try:
        with open(sp, "rb") as f:
            status = narrator.parse(f.read())
    except OSError:
        status = None
    if status is not None and not narrator.is_builtin(status):
        raise SetupError(REFUSED, "%s/cast/%s is not a builtin narrator (an actor: M3)" % (root, nid))
    old = narrator._voice(status, lang) if status else None
    new = (engine, style)
    h = L.narrator_hash(nid, lang, list(old) if old else None, list(new))
    return {"id": nid, "lang": lang, "old": list(old) if old else None, "new": list(new), "changes": old != new,
            "h12": h, "label": "설정 %s" % h, "line": L.narrator_line(nid, lang, old, new), "root": root,
            "status": status}


def narrator_set(top, lang, engine, style, expect, argv, nid="narrator", proxy=False):
    if proxy:
        raise SetupError(USAGE, "the narrator is the person's choice: the proxy mode cannot (--proxy refused)")
    p = narrator_preview(top, lang, engine, style, nid)
    if not p["changes"]:
        raise SetupError(REFUSED, "the narrator %s %s is already %s" % (nid, lang, " ".join(p["new"])))
    if expect != p["h12"]:
        raise _expect_problem(expect, p)

    def write():
        status = copy.deepcopy(p["status"]) or narrator.record(nid, {})
        status.setdefault("voice", {})[lang] = {"engine": engine, "style": style, "state": "ready"}
        rel_base = "%s/cast/%s" % (p["root"], nid)
        write_text(top, rel_base + "/status.json", narrator.dumps(status))
        if not os.path.exists(os.path.join(top, rel_base, "profile.md")):
            from .render import template
            write_text(top, rel_base + "/profile.md", template("cast/profile.md.tmpl", {"NARRATOR_ID": nid}))
        return rel_base + "/status.json"
    out = dict(p, wrote=with_evidence(top, argv, p["label"], False, write, "narrator set"))
    out.pop("status", None)
    return out
