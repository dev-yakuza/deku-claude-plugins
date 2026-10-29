"""Pronunciation records (m1-plan §8, open item (a) of §23.2): every one is a flat JSON object, written form →
reading — `.claude/studio/pronounce.json` (shared, committed), a script's frontmatter `pronounce`, the cast stage's
`work/<l>/pronounce-changes.json` (what the script adds or changes against HEAD's pronounce.json) and
`work/<l>/pronounce-approved.json` (written by ② with its sha in the ② record, v5.1 T1).

Conflicts (v5 S1) are informational: a written form whose reading here differs from HEAD's or from the valid
pronounce-approved.json of another video in progress. They block nothing and are not part of any hash."""

import json
import os
import subprocess

from .. import paths
from . import frontmatter

SHARED = ".claude/studio/pronounce.json"


def parse(data):
    """A flat {str: str} object, or None."""
    try:
        v = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except (ValueError, UnicodeDecodeError, AttributeError, TypeError):
        return None
    if not isinstance(v, dict) or not all(isinstance(k, str) and isinstance(x, str) and k and x for k, x in v.items()):
        return None
    return v


def read(path):
    """(object or None, why)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None, "missing"
    v = parse(data)
    return (v, None) if v is not None else (None, "not a flat object of written form → reading")


def head_shared(repo):
    """HEAD's pronounce.json ({} when it has none; None when it is not a flat object)."""
    out = subprocess.run(["git", "-C", repo, "show", "HEAD:" + SHARED], capture_output=True, env=paths.git_env())
    if out.returncode != 0:
        return {}
    return parse(out.stdout)


def of_script(text):
    """The script's frontmatter `pronounce` as a flat object ({} without one; None when it is not flat)."""
    b = frontmatter.block(text, "pronounce")
    if b is None:
        return {}
    if not all(isinstance(v, str) and v for v in b.values()):
        return None
    return b


def changes(script_map, shared):
    """What the script adds or changes against the shared dictionary."""
    return {k: v for k, v in sorted(script_map.items()) if shared.get(k) != v}


def conflicts(repo, root, video, chg, shared, providers=None, ctx_of=None):
    """[{"key", "value", "others": [{"video": "HEAD" | id, "value"}]}] — readings elsewhere that differ."""
    from ..state import harnessgate
    per = {}
    try:
        harnessgate.approved_additions(repo, root, providers, ctx_of, per_video=per)
    except Exception:  # noqa: BLE001 — informational only: a failure shows no conflicts from other videos
        per = {}
    out = []
    for k, v in sorted((chg or {}).items()):
        others = []
        if k in (shared or {}) and shared[k] != v:
            others.append({"video": "HEAD", "value": shared[k]})
        for vid, data in sorted(per.items()):
            if vid != video and k in data and data[k] != v:
                others.append({"video": vid, "value": data[k]})
        if others:
            out.append({"key": k, "value": v, "others": others})
    return out


def conflict_lines(items):
    """`空港: 이 영상 구우코우 / HEAD 쿠우코오 — 공유 사전에는 먼저 커밋된 쪽이 남는다` (the ② question shows them)."""
    return ["%s: 이 영상 %s / %s — 공유 사전에는 먼저 커밋된 쪽이 남는다" % (
        c["key"], c["value"], " / ".join("%s %s" % (o["video"], o["value"]) for o in c["others"])) for c in items]


def path_changes(vdir, lang):
    return os.path.join(vdir, "work", lang, "pronounce-changes.json")


def path_approved(vdir, lang):
    return os.path.join(vdir, "work", lang, "pronounce-approved.json")
