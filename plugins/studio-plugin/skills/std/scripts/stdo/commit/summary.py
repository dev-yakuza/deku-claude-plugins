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


def protected_keys(old_cfg, new_cfg):
    keys = set(FIXED_PROTECTED)
    for c in (old_cfg, new_cfg):
        more = c.get("protected_keys") if isinstance(c, dict) else None
        keys |= set(k for k in (more or []) if isinstance(k, str))
    return keys


def configs(ctx, studio_paths):
    """(HEAD's config, the index's config) when this commit changes config.json, else ({}, {})."""
    if spaths.CONFIG not in studio_paths:
        return {}, {}
    status = dict((p, st) for st, p in ctx.git.staged(ctx.base))
    old = _cfg(ctx.git.show("%s:%s" % (ctx.head, spaths.CONFIG))) if ctx.head else {}
    new = _cfg(ctx.git.show(":" + spaths.CONFIG)) if status.get(spaths.CONFIG) != "D" else {}
    return old or {}, new or {}


def narrators(ctx, studio_paths):
    """[(id, HEAD status, index status)] of the builtin narrators this commit changes (m1-plan §5.3)."""
    from .. import narrator
    from .harness import narrator_file
    out = []
    for p in sorted(studio_paths):
        nf = narrator_file(ctx, p)
        if nf and nf[1] == "status.json":
            old = narrator.parse(ctx.git.show("%s:%s" % (ctx.head, p))) if ctx.head else None
            out.append((nf[0], old, narrator.parse(ctx.git.show(":" + p))))
    return out


def crit_files(ctx, studio_paths):
    """[(path, HEAD blob or None, index blob or None)] of the criteria files (P-CRIT) this commit changes."""
    from . import values
    status = dict((p, st) for st, p in ctx.git.staged(ctx.base))
    out = []
    for p in sorted(studio_paths):
        if values.is_crit(p):
            old = ctx.git.show("%s:%s" % (ctx.head, p)) if ctx.head else None
            new = ctx.git.show(":" + p) if status.get(p) != "D" else None
            out.append((p, old, new))
    return out


def settings_lines(ctx, studio_paths):
    """The settings part of the value block, from HEAD and the index (the hook recomputes it the same way)."""
    from . import values
    old, new = configs(ctx, studio_paths)
    return values.settings(old, new, protected_keys(old, new), narrators(ctx, studio_paths),
                           crit_files(ctx, studio_paths))[0]


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
