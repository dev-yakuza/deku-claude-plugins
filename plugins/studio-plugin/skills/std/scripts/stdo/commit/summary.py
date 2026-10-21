"""The one-line summary of a Studio commit (m0f-plan v4 §2.4): printed by `--stage`, kept in commit-ok.json,
shown verbatim in the person's question and found there by the guard. ASCII separators:

    커밋 <tree12> | 변경 <N> | 삭제 <M> | 보호 키: <k1, k2 | 없음>[ | 삭제된 에이전트: std-a, std-b]
"""

import hashlib
import json
import re
import unicodedata

from . import okfile, spaths

# protected keys of config.json (00-plan §3.4 설정 행; the guard's RepoInfo.protected_keys has the same list)
FIXED_PROTECTED = ("visibility", "internal_overlay", "public_domains", "web_roots", "allow_internal_commits", "s2v",
                   "models", "gates", "roles", "studio_root", "protected_keys")
AGENT_PREFIX = ".claude/agents/"


def _cfg(data):
    if data is None:
        return {}
    try:
        v = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except (ValueError, UnicodeDecodeError):
        return None
    return v if isinstance(v, dict) else None


def _h(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def protected_changes(old_cfg, new_cfg):
    """[{key, old, new}] (value hashes; None when absent) of the protected keys that differ."""
    keys = set(FIXED_PROTECTED)
    for c in (old_cfg, new_cfg):
        more = c.get("protected_keys") if isinstance(c, dict) else None
        keys |= set(k for k in (more or []) if isinstance(k, str))
    out = []
    for k in sorted(keys):
        a = old_cfg.get(k) if isinstance(old_cfg, dict) and k in old_cfg else None
        b = new_cfg.get(k) if isinstance(new_cfg, dict) and k in new_cfg else None
        ina = isinstance(old_cfg, dict) and k in old_cfg
        inb = isinstance(new_cfg, dict) and k in new_cfg
        if ina != inb or a != b:
            out.append({"key": k, "old": _h(a) if ina else None, "new": _h(b) if inb else None})
    return out


def compute(ctx, studio_paths, tree):
    """(summary line, protected_changes, deleted agent names)."""
    status = dict((p, st) for st, p in ctx.git.staged(ctx.base))
    deleted = sorted(p for p in studio_paths if status.get(p) == "D")
    changed = len(studio_paths) - len(deleted)
    prot = []
    if spaths.CONFIG in studio_paths:
        old = _cfg(ctx.git.show("%s:%s" % (ctx.head, spaths.CONFIG))) if ctx.head else {}
        new = _cfg(ctx.git.show(":" + spaths.CONFIG)) if status.get(spaths.CONFIG) != "D" else {}
        prot = protected_changes(old or {}, new or {})
    agents = sorted(p[len(AGENT_PREFIX):-3] for p in deleted
                    if p.startswith(AGENT_PREFIX + "std-") and p.endswith(".md"))
    line = "%s | 변경 %d | 삭제 %d | 보호 키: %s" % (okfile.LABEL % tree[:12], changed, len(deleted),
                                                ", ".join(c["key"] for c in prot) if prot else "없음")
    if agents:
        line += " | 삭제된 에이전트: %s" % ", ".join(agents)
    return line, prot, agents


def norm(text):
    """NFC and runs of whitespace as one space (the guard compares the question text this way)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def shown_in(summary, question):
    return bool(summary) and norm(summary) in norm(question)
