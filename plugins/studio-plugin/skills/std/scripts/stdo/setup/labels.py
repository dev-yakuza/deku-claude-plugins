"""setup.py's approval labels, shared by setup.py and the guard (pure: no writes, no processes).

    config set <key> <value> --expect <h12>         설정 <h12>  h12 = H(key · old · new) — protected keys, s2v.path
    narrator set <lang> --engine E --style S [--id I] --expect <h12>
                                                    설정 <h12>  h12 = H("narrator" · id · lang · old · new)
    update apply --expect <h12> [--take a=new,b=local]
                                                    갱신 <h12>  h12 = the update plan's (with the choices)

A protected `config set` question must also show the line `설정 <key>: <old> → <new>` (canonical JSON; the guard
reads the old value itself and compares). Everything else of setup.py needs no evidence: `init` (the first harness
commit is the person's check), `config get`, `config set` of other keys, the previews and `update plan`."""

import json

from ..state.argv import canonical
from ..state.hashes import hash_of
from ..state.labels import HASH12, NoLabel, setting, update

NONE = "(없음)"
SPECIAL = ("s2v.path",)  # machine.json: decides which code runs as s2v (m1-plan §3.1)


def parse_value(raw):
    """A value on the command line: JSON when it parses, else the text itself."""
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def setting_hash(key, old, new, old_present=True):
    return hash_of({"key": key, "old": old if old_present else None, "old_present": bool(old_present),
                    "new": new})[:12]


def config_line(key, old, new, old_present=True):
    return "설정 %s: %s → %s" % (key, canon(old) if old_present else NONE, canon(new))


def narrator_hash(nid, lang, old, new):
    return hash_of({"key": "narrator", "id": nid, "lang": lang, "old": old, "new": new})[:12]


def narrator_line(nid, lang, old, new):
    def v(x):
        return "%s %s" % (x[0], json.dumps(x[1], ensure_ascii=False)) if x else NONE
    return "설정 내레이터 %s %s: %s → %s" % (nid, lang, v(old), v(new))


def is_protected(key, protected_keys):
    return key in SPECIAL or key.split(".", 1)[0] in protected_keys


def lookup(cfg, key):
    """(present, value) of a dotted key in a config object."""
    cur = cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def needs_evidence(argv, protected_keys):
    """True when this setup.py command line records a person's decision."""
    if len(argv) < 2:
        return False
    try:
        c = canonical(argv)
    except ValueError:
        return True  # a line the guard cannot read is judged as an approval (closed side)
    pos = [c["cmd"]] + c["pos"]
    if pos[:2] == ["config", "set"]:
        return len(pos) >= 3 and is_protected(pos[2], protected_keys)
    return pos[:2] in (["narrator", "set"], ["update", "apply"])


def expected(argv):
    """(label, h12) of an evidence command (NoLabel when the line has no usable --expect)."""
    try:
        c = canonical(argv)
    except ValueError as e:
        raise NoLabel(str(e))
    expect = c["opt"].get("--expect")
    if not isinstance(expect, str) or not HASH12.match(expect):
        raise NoLabel("--expect must be the 12 lowercase hex characters shown in the question")
    pos = [c["cmd"]] + c["pos"]
    if pos[:2] == ["update", "apply"]:
        return update(expect), expect
    if pos[:2] in (["config", "set"], ["narrator", "set"]):
        return setting(expect), expect
    raise NoLabel("setup.py %s is not an approval command" % " ".join(pos[:2]))
