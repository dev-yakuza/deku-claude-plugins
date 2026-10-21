"""INV5 for WebFetch and WebSearch (m0d2-plan §9): internal hosts and terms of the local overlay must not
reach an external service while a video or actor job is open in a harness repository."""

import glob
import hashlib
import json
import os
import re
import urllib.parse

from .. import paths

MIN_TERM = 4
MAX_STATES = 200
DONE = ("done", "aborted", "abandoned")


def overlay(worktree, cfg, env):
    """(state, data): state "none" (the repository needs no overlay) | "ok" | "missing" (absent or its sha
    does not match the per-machine record)."""
    if not isinstance(cfg, dict) or cfg.get("internal_overlay") != "required":
        return "none", None
    p = os.path.join(worktree, ".claude", "studio", "local", "config.internal.json")
    try:
        with open(p, "rb") as f:
            raw = f.read()
    except OSError:
        return "missing", None
    try:
        key = hashlib.sha256(os.path.realpath(worktree).encode("utf-8")).hexdigest()[:16]
        with open(os.path.join(paths.backup_root(env), key, "overlay.sha"), encoding="utf-8") as f:
            want = f.read().strip()
    except (OSError, ValueError):
        return "missing", None
    if hashlib.sha256(raw).hexdigest() != want:
        return "missing", None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return "missing", None
    return "ok", data


def internal_items(data):
    """(hosts, terms, ids) from the overlay's `internal` object (keys read by the guard, m0d2-plan §9.2)."""
    inner = data.get("internal") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
        return set(), [], set()
    hosts = set()
    for h in inner.get("hosts") or []:
        if isinstance(h, str) and h.strip():
            hosts.add(h.strip().lower().rstrip("."))
    for s in inner.get("sources") or []:
        url = s.get("url") if isinstance(s, dict) else None
        if isinstance(url, str):
            h = urllib.parse.urlsplit(url).hostname
            if h:
                hosts.add(h.lower())
    ids = set(x for x in (inner.get("videos") or []) + (inner.get("actors") or []) if isinstance(x, str) and x)
    terms = [t for t in (inner.get("terms") or []) if isinstance(t, str) and len(t.strip()) >= MIN_TERM]
    terms += [t for t in ids if len(t) >= MIN_TERM]
    return hosts, sorted(set(t.strip() for t in terms)), ids


def open_work(worktree, studio_root):
    """Whether any video or actor job is unfinished (too many state files counts as open — closed side)."""
    pats = [os.path.join(worktree, studio_root, "videos", "*", "work", "state.json"),
            os.path.join(worktree, studio_root, "local", "videos", "*", "work", "state.json"),
            os.path.join(worktree, studio_root, "cast", "*", "status.json"),
            os.path.join(worktree, studio_root, "local", "cast", "*", "status.json")]
    files = []
    for p in pats:
        files += glob.glob(p)
        if len(files) > MAX_STATES:
            return True
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return True
        langs = d.get("langs") if isinstance(d, dict) else None
        if isinstance(langs, dict):
            if any(isinstance(L, dict) and L.get("status") not in DONE for L in langs.values()):
                return True
        elif not isinstance(d, dict) or d.get("status") not in DONE:
            return True
    return False


def _host_hit(host, hosts):
    host = (host or "").lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in hosts)


def _term_hit(text, terms):
    low = text.casefold()
    for t in terms:
        tl = t.casefold()
        if re.match(r"^[\x00-\x7f]+$", t):
            if re.search(r"(?<![0-9a-z])%s(?![0-9a-z])" % re.escape(tl), low):
                return t
        elif tl in low:
            return t
    return None


def studio_agent(hook):
    at = hook.get("agent_type")
    if not isinstance(at, str) or not at:
        return False
    return at.rsplit(":", 1)[-1].startswith("std-")


def judge(tool, ti, hook, ri, env):
    """("deny", text) | ("warn", text) | None."""
    st, data = overlay(ri.worktree, ri.config, env)
    if st == "none":
        return None
    active = open_work(ri.worktree, ri.studio_root)
    if st == "missing":
        if active and studio_agent(hook):
            return "deny", ("Studio agents cannot use %s while the internal overlay is missing (INV5) — ask the person "
                            "to recreate it with /std config." % tool)
        return None
    hosts, terms, _ids = internal_items(data)
    public = set(h.lower() for h in (ri.config.get("public_domains") or []) if isinstance(h, str))
    hit = None
    if tool == "WebFetch":
        url = ti.get("url") if isinstance(ti.get("url"), str) else ""
        host = urllib.parse.urlsplit(url).hostname or ""
        if _host_hit(host, hosts) and not _host_hit(host, public):
            hit = "internal host %s" % host
        else:
            t = _term_hit(url + "\n" + str(ti.get("prompt") or ""), terms)
            if t:
                hit = "internal term \"%s…\"" % t[:3]
    else:
        q = ti.get("query") if isinstance(ti.get("query"), str) else ""
        t = _term_hit(q, terms)
        if t:
            hit = "internal term \"%s…\"" % t[:3]
    if not hit:
        return None
    if active:
        return "deny", "%s must not go to an external service (INV5) — the request names an %s." % (tool, hit)
    return "warn", "Studio: this %s names an %s; internal names must not reach external services (INV5)." % (tool, hit)
