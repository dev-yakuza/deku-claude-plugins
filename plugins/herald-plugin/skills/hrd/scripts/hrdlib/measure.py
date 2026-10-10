"""Per-article token and dollar measurement from Claude Code transcripts (plan §3.7).

Transcripts: ~/.claude/projects/<project-key>/<session>.jsonl, subagents under
<session>/subagents/agent-*.jsonl. Assistant events repeat while streaming — dedupe by
message.id or the integral inflates (~1.6x, Guild's measured lesson).
"""

import glob
import json
import os

CACHE_READ, CACHE_WRITE_5M, CACHE_WRITE_1H, OUT_MULT = 0.1, 1.25, 2.0, 5.0


def family(model):
    m = (model or "").lower()
    for f in ("opus", "sonnet", "haiku"):
        if f in m:
            return f
    return "sonnet"


def dollars(usage, model, prices):
    rate = float(prices.get(family(model), prices.get("sonnet", 3.0))) / 1_000_000
    cc = usage.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens")
    w5m = cc.get("ephemeral_5m_input_tokens")
    if w1h is None and w5m is None:
        w5m, w1h = usage.get("cache_creation_input_tokens", 0), 0
    return rate * (usage.get("input_tokens", 0)
                   + usage.get("cache_read_input_tokens", 0) * CACHE_READ
                   + (w5m or 0) * CACHE_WRITE_5M + (w1h or 0) * CACHE_WRITE_1H
                   + usage.get("output_tokens", 0) * OUT_MULT)


def iter_assistant(path):
    seen = set()
    try:
        f = open(path, encoding="utf-8")
    except OSError:
        return
    with f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") != "assistant":
                continue
            msg = o.get("message") or {}
            mid = msg.get("id") or o.get("uuid")
            if mid in seen:
                continue
            seen.add(mid)
            usage = msg.get("usage")
            if usage:
                yield msg.get("model"), usage, o


def tool_stats(path):
    calls = reads = read_bytes = 0
    try:
        f = open(path, encoding="utf-8")
    except OSError:
        return {"tool_calls": 0, "read_calls": 0, "read_bytes": 0}
    with f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            msg = o.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if c.get("type") == "tool_use":
                    calls += 1
                    if c.get("name") == "Read":
                        reads += 1
                if c.get("type") == "tool_result":
                    body = c.get("content")
                    if isinstance(body, list):
                        body = "".join(x.get("text", "") for x in body if isinstance(x, dict))
                    if isinstance(body, str) and body.lstrip().startswith(("1\t", "     1\t", "1→")):
                        read_bytes += len(body.encode("utf-8"))
    return {"tool_calls": calls, "read_calls": reads, "read_bytes": read_bytes}


def summarize_file(path, prices):
    tot = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "usd": 0.0, "turns": 0, "models": {}}
    for model, u, _ in iter_assistant(path):
        tot["input"] += u.get("input_tokens", 0)
        tot["cache_read"] += u.get("cache_read_input_tokens", 0)
        tot["cache_write"] += u.get("cache_creation_input_tokens", 0)
        tot["output"] += u.get("output_tokens", 0)
        usd = dollars(u, model, prices)
        tot["usd"] += usd
        tot["turns"] += 1
        tot["models"][family(model)] = tot["models"].get(family(model), 0.0) + usd
    tot["usd"] = round(tot["usd"], 4)
    tot.update(tool_stats(path))
    return tot


def project_key(root):
    return root.replace("/", "-").replace(".", "-")


def session_files(root, session=None):
    base = os.path.expanduser(os.path.join("~", ".claude", "projects", project_key(root)))
    if session:
        main = os.path.join(base, session + ".jsonl")
        subs = sorted(glob.glob(os.path.join(base, session, "subagents", "*.jsonl")))
        return ([main] if os.path.exists(main) else []), subs
    mains = sorted(glob.glob(os.path.join(base, "*.jsonl")), key=os.path.getmtime)
    if not mains:
        return [], []
    latest = mains[-1]
    sid = os.path.basename(latest)[:-6]
    return [latest], sorted(glob.glob(os.path.join(base, sid, "subagents", "*.jsonl")))


def subagent_label(path):
    """Best-effort role label: the first user prompt line naming a persona file."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                if o.get("type") == "user":
                    content = (o.get("message") or {}).get("content")
                    text = content if isinstance(content, str) else " ".join(
                        c.get("text", "") for c in content or [] if isinstance(c, dict))
                    for role in ("content-strategist", "researcher", "writer", "editor-in-chief", "editor",
                                 "fact-checker", "subject-expert", "search-discovery", "illustrator",
                                 "translator", "auditor"):
                        if role in text:
                            return role
                    return "other"
    except (OSError, ValueError):
        pass
    return "other"


def measure(root, prices, session=None, files=None):
    if files:
        mains, subs = files, []
    else:
        mains, subs = session_files(root, session)
    out = {"main": [summarize_file(p, prices) for p in mains], "roles": {}, "total_usd": 0.0}
    for p in subs:
        s = summarize_file(p, prices)
        label = subagent_label(p)
        agg = out["roles"].setdefault(label, {"usd": 0.0, "spawns": 0, "output": 0, "read_calls": 0, "read_bytes": 0})
        agg["usd"] = round(agg["usd"] + s["usd"], 4)
        agg["spawns"] += 1
        agg["output"] += s["output"]
        agg["read_calls"] += s["read_calls"]
        agg["read_bytes"] += s["read_bytes"]
    out["main_usd"] = round(sum(m["usd"] for m in out["main"]), 4)
    out["subagent_usd"] = round(sum(r["usd"] for r in out["roles"].values()), 4)
    out["total_usd"] = round(out["main_usd"] + out["subagent_usd"], 4)
    return out


def stream_json_usd(path, prices):
    """Running dollar total of a `claude -p --output-format stream-json` log (batch budget)."""
    total = 0.0
    seen = set()
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return 0.0
    with f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            msg = o.get("message") or {}
            if o.get("type") == "assistant" and msg.get("usage"):
                mid = msg.get("id")
                if mid in seen:
                    continue
                seen.add(mid)
                total += dollars(msg["usage"], msg.get("model"), prices)
    return round(total, 4)
