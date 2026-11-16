"""workflows.status.board — `/gld monitoring` as code: `status board [section] [--html]`.

Read-only snapshot (monitoring.md): git-local files + one `list_snapshots` read (+ one sprint
list). Actionable-first order is fixed in code: needs-human pauses, open gate violations, then
the static sections. The one write is the optional `--html` artifact under
`.claude/guild/memory/monitoring.html` (the gitignored path monitoring.md names).
"""

import glob
import html
import json
import os
import re
import subprocess

from guildcore.state import list_snapshots
from workflows.status import render as R

LEDGER = os.path.join(os.path.dirname(__file__), "..", "..", "..", "commands", "atoms", "ledger.py")
BOILERPLATE_RE = re.compile(r"\((미정 — 추후 확정|TBD)\)")
BUCKET_ORDER = ("analyze", "design", "execute", "test", "qa", "done", "children", "none")


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (IOError, UnicodeDecodeError):
        return None


def run_ledger(root):
    try:
        p = subprocess.run(["python3", os.path.abspath(LEDGER), "status", "--root", root],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace").strip().split("\n")[0] or None


def gather_org(root, cfg):
    roles = list(cfg.roles)
    stale = []
    for r in roles:
        text = _read(os.path.join(root, ".claude", "agents", r + ".md"))
        if text is None:
            continue
        spec = text.split("<!-- guild:persona:habits -->", 1)[0]
        i = spec.find("## 프로젝트 특화")
        if i >= 0 and BOILERPLATE_RE.search(spec[i:]):
            stale.append(r)
    return {"roles": roles, "boilerplate": stale}


def gather_knowledge(root):
    idx = _read(os.path.join(root, ".claude", "guild", "knowledge", "index.md"))
    gt = _read(os.path.join(root, ".claude", "guild", "memory", "ground-truth.jsonl"))
    return {"index_lines": None if idx is None else sum(1 for l in idx.split("\n") if l.startswith("- ")),
            "ground_truth": None if gt is None else sum(1 for l in gt.split("\n") if l.strip())}


def gather_gates(root, cfg):
    f = _read(os.path.join(root, ".claude", "guild", "gates", "findings.json"))
    open_n = None
    if f is not None:
        try:
            open_n = len((json.loads(f) or {}).get("open") or [])
        except ValueError:
            open_n = None
    d = _read(os.path.join(root, ".claude", "guild", "gates", "dismissed.md"))
    dismissed = None
    if d is not None:
        dismissed = sum(1 for l in d.split("\n") if l.startswith("- `"))
    return {"open": open_n, "enabled": bool(cfg.get("gates.enabled", False)), "dismissed": dismissed}


def gather_standards(root):
    d = c = 0
    for p in sorted(glob.glob(os.path.join(root, "docs", "standards", "*.md"))):
        m = re.search(r"^status:\s*(\w+)", _read(p) or "", re.M)
        if m and m.group(1) == "confirmed":
            c += 1
        elif m:
            d += 1
    return {"draft": d, "confirmed": c}


def gather_work(gh):
    rows = list_snapshots(gh, state="open")
    buckets = {}
    paused = []
    for r in rows:
        st = r["derived"]
        if st.sprint:
            continue
        key = st.stage if st.stage != "done" else "done"
        buckets[key] = buckets.get(key, 0) + 1
        if st.paused:
            paused.append(r["number"])
    sprints = [r["number"] for r in list_snapshots(gh, state="open", label="guild:sprint")]
    return {"buckets": buckets, "paused": paused, "sprints": sprints}


def gather(root, cfg, gh, section=None, ledger=run_ledger):
    want = [section] if section in R.SECTIONS else list(R.SECTIONS)
    data = {}
    if "org" in want:
        data["org"] = gather_org(root, cfg)
    if "knowledge" in want:
        data["knowledge"] = gather_knowledge(root)
    if "evolution" in want:
        data["evolution"] = {"ledger": ledger(root)}
    if "gates" in want:
        data["gates"] = gather_gates(root, cfg)
    if "standards" in want:
        data["standards"] = gather_standards(root)
    if "work" in want:
        data["work"] = gather_work(gh)
    return data


def _f(T, key, v):
    """A counted phrase, or the bare "none" word when the source is missing (monitoring.md:
    a missing source renders "없음", never an error)."""
    return T["none"] if v is None else T[key].format(k=v)


def render_text(data, language, ts, section=None, invalid=None):
    T = R.board_text(language)
    out = []
    if invalid:
        out.append(T["invalid"].format(s=invalid))
    out.append(T["focus"].format(section=section) if section else T["title"])
    # actionable first (monitoring.md Hard rules)
    w, g = data.get("work"), data.get("gates")
    if w and w["paused"]:
        out.append("▲ " + T["paused"].format(k=len(w["paused"])) + " — " +
                   ", ".join("#%d" % n for n in w["paused"]))
    if g and g["open"]:
        out.append("▲ " + T["gates"] + ": " + T["findings"].format(k=g["open"]))
    if "org" in data:
        o = data["org"]
        line = "%s — %s" % (T["org"], T["roles"].format(k=len(o["roles"])))
        if o["boilerplate"]:
            line += " · " + T["boilerplate"].format(names=", ".join(o["boilerplate"]))
        out.append(line)
    if "knowledge" in data:
        k = data["knowledge"]
        out.append("%s — %s · %s" % (T["knowledge"], _f(T, "slices", k["index_lines"]),
                                     _f(T, "gt", k["ground_truth"])))
    if "evolution" in data:
        out.append("%s — %s" % (T["evolution"], data["evolution"]["ledger"] or T["none"]))
    if g:
        out.append("%s — %s · %s · %s" % (T["gates"], T["enabled"].format(state=T["on"] if g["enabled"] else T["off"]),
                                          _f(T, "findings", g["open"]),
                                          _f(T, "dismissed", g["dismissed"])))
    if "standards" in data:
        s = data["standards"]
        out.append("%s — %s" % (T["standards"], T["std"].format(d=s["draft"], c=s["confirmed"])))
    if w:
        parts = [T["bucket"].format(stage=b, k=w["buckets"][b]) for b in BUCKET_ORDER if b in w["buckets"]]
        out.append("%s — %s" % (T["work"], " · ".join(parts) if parts else T["none"]))
        if w["sprints"]:
            out.append("  " + T["sprint"].format(k=len(w["sprints"]),
                                                 nums=", ".join("#%d" % n for n in w["sprints"])))
    out.append(T["snapshot"].format(ts=ts))
    return "\n".join(out) + "\n"


def render_html(text, title):
    rows = "".join("<li>%s</li>" % html.escape(l) for l in text.rstrip("\n").split("\n")[1:])
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><title>%s</title>"
            "<style>body{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#fff;color:#111}"
            "li{margin:4px 0}</style></head><body><h1>%s</h1><ul>%s</ul></body></html>\n"
            % (html.escape(title), html.escape(title), rows))


def html_path(root):
    return os.path.join(root, ".claude", "guild", "memory", "monitoring.html")
