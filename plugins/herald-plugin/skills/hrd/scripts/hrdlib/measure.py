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
    import re
    return re.sub(r"[^A-Za-z0-9]", "-", root)


def config_dir():
    """Claude Code's config directory: `CLAUDE_CONFIG_DIR` when set (per-account setups), else
    `~/.claude`."""
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser(os.path.join("~", ".claude"))


def _subagent_files(base, sid):
    """Every subagent transcript of a session, nested ones (`subagents/workflows/…`) included."""
    return sorted(glob.glob(os.path.join(base, sid, "subagents", "**", "agent-*.jsonl"), recursive=True))


def session_files(root, session=None, transcript_dir=None):
    base = transcript_dir or os.path.join(config_dir(), "projects", project_key(root))
    if session:
        main = os.path.join(base, session + ".jsonl")
        return ([main] if os.path.exists(main) else []), _subagent_files(base, session)
    mains = sorted(glob.glob(os.path.join(base, "*.jsonl")), key=os.path.getmtime)
    if not mains:
        return [], []
    latest = mains[-1]
    sid = os.path.basename(latest)[:-6]
    return [latest], _subagent_files(base, sid)


ROLES = ("content-strategist", "researcher", "writer", "editor-in-chief", "editor", "fact-checker", "subject-expert",
         "search-discovery", "illustrator", "translator", "distributor", "auditor")
# built-in agent types say nothing about the Herald role (the auditor spawns as Explore)
BUILTIN_TYPES = ("Explore", "Plan", "general-purpose", "workflow-subagent", "claude", "statusline-setup",
                 "claude-code-guide", "fork")


def subagent_meta(path):
    try:
        with open(path[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def subagent_task(path):
    """(role, task) — the spawn's `description` `Herald: <role> — <task>` (0.13.0 spawns), else the
    agent type unless it is a built-in one, else a guess from the first prompt."""
    import re

    meta = subagent_meta(path)
    m = re.match(r"^Herald:\s*(\S+)(?:\s+[—-]\s+(.+))?$", str(meta.get("description") or "").strip())
    if m:
        return m.group(1), (m.group(2) or "").strip() or None
    t = meta.get("agentType")
    if t and t not in BUILTIN_TYPES:
        return t, None
    return _guess_label(path), None


def _guess_label(path):
    """Best-effort role label: the first user prompt line naming a persona file."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                if o.get("type") == "user":
                    content = (o.get("message") or {}).get("content")
                    text = content if isinstance(content, str) else " ".join(
                        c.get("text", "") for c in content or [] if isinstance(c, dict))
                    for role in ROLES:
                        if role in text:
                            return role
                    return "other"
    except (OSError, ValueError):
        pass
    return "other"


def subagent_label(path):
    return subagent_task(path)[0]


def measure(root, prices, session=None, files=None, detail=False, transcript_dir=None):
    if files:
        mains, subs = files, []
    else:
        mains, subs = session_files(root, session, transcript_dir)
    out = {"main": [summarize_file(p, prices) for p in mains], "roles": {}, "total_usd": 0.0,
           "session": os.path.basename(mains[0])[:-len(".jsonl")] if mains and not files else None,
           "found": bool(mains)}  # false: no transcript to measure (wrong session id or project key)
    labels = {}
    for p in subs:
        s = summarize_file(p, prices)
        label, task = subagent_task(p)
        meta = subagent_meta(p)
        if meta.get("toolUseId"):
            labels[meta["toolUseId"]] = "%s — %s" % (label, task) if task else label
        labels[os.path.basename(p)[len("agent-"):-len(".jsonl")]] = labels.get(meta.get("toolUseId"), label)
        agg = out["roles"].setdefault(label, {"usd": 0.0, "spawns": 0, "output": 0, "read_calls": 0, "read_bytes": 0})
        agg["usd"] = round(agg["usd"] + s["usd"], 4)
        agg["spawns"] += 1
        agg["output"] += s["output"]
        agg["read_calls"] += s["read_calls"]
        agg["read_bytes"] += s["read_bytes"]
        if detail:
            t = out.setdefault("detail", {}).setdefault("tasks", {})
            key = "%s — %s" % (label, task) if task else label
            if meta.get("parentAgentId"):  # spawned by a sub-agent: its own row, marked as nested
                key += " (nested)"
            agg2 = t.setdefault(key, {"usd": 0.0, "spawns": 0})
            agg2["usd"] = round(agg2["usd"] + s["usd"], 4)
            agg2["spawns"] += 1
    out["main_usd"] = round(sum(m["usd"] for m in out["main"]), 4)
    out["subagent_usd"] = round(sum(r["usd"] for r in out["roles"].values()), 4)
    out["total_usd"] = round(out["main_usd"] + out["subagent_usd"], 4)
    if detail and mains and not files:
        out.setdefault("detail", {})["main"] = main_detail(mains[0], labels)
        out["detail"]["config_dir"] = transcript_dir or config_dir()
    return out


# --- where the main session's context comes from (design/herald/04-token-optimization.md §2.1) ----

def _att_text(a):
    """The model-visible text of an attachment, or None for types that only record state."""
    t = a.get("type")

    def join(items, key):
        return "\n".join(str(i.get(key) or "") for i in items or [] if isinstance(i, dict))

    table = {
        "edited_text_file": lambda: a.get("snippet"),
        "queued_command": lambda: a.get("prompt"),
        "skill_listing": lambda: a.get("content"),
        "total_tokens_reminder": lambda: a.get("text"),
        "silent_turn_reminder": lambda: a.get("text"),
        "task_status": lambda: a.get("deltaSummary"),
        "file": lambda: a.get("content") if isinstance(a.get("content"), str) else json.dumps(a.get("content")),
        "directory": lambda: a.get("content"),
        "selected_lines_in_ide": lambda: a.get("content"),
        "model": lambda: a.get("text"),
        "date": lambda: a.get("date"),
        "date_change": lambda: a.get("newDate"),
        "session_context": lambda: a.get("context") if isinstance(a.get("context"), str) else json.dumps(a.get("context")),
        "instructions": lambda: join(a.get("files"), "content"),
        "invoked_skills": lambda: join(a.get("skills"), "content"),
        "read_truncation_notice": lambda: a.get("banner"),
        "deferred_tools_delta": lambda: json.dumps([a.get("addedLines"), a.get("surfacedDefinitions")]),
        "mcp_instructions_delta": lambda: json.dumps(a.get("addedBlocks")),
        "agent_listing_delta": lambda: json.dumps(a.get("addedLines")),
        "environment": lambda: json.dumps([a.get("snapshot"), a.get("changes")]),  # structured: bytes approximate
        # hook output the model sees: added context from these events; never PreToolUse (the guard's
        # answer) or Stop
        "hook_success": lambda: (a.get("content") or a.get("additionalContext") or None)
        if a.get("hookEvent") in ("UserPromptSubmit", "SessionStart", "PostToolUse") else None,
    }
    f = table.get(t)
    if f is None:
        return None
    v = f()
    if t == "hook_success" and not v:
        return None  # a hook whose output the model never sees (the guard's PreToolUse answer)
    return v if isinstance(v, str) else ""


def _est_tokens(text):
    """Rough tokens: ASCII ~4 bytes per token, other characters ~1 token each."""
    ascii_ = sum(1 for c in text if ord(c) < 128)
    return int(ascii_ / 4 + (len(text) - ascii_))


def _bash_source(cmd):
    import re

    m = re.search(r"(?:^|[\s/])hrd\.py\s+([a-z-]+)(?:\s+([a-z-]+)(?=\s|$))?", cmd)
    if m:  # the action word only for groups that have actions (never a slug or topic id)
        two = m.group(1) in ("lock", "stage", "social", "ledger", "topics", "translate", "reverts", "trim")
        return "hrd " + m.group(1) + (" " + m.group(2) if two and m.group(2) else "")
    # prompt files read through the shell (`cat <plugin cache>/skills/hrd/commands/x.md`)
    files = re.findall(r"/skills/hrd/([\w./-]+\.md)", cmd)
    if files and re.match(r"\s*(?:cd [^;&]+[;&]+\s*)?(?:[A-Z_]+=\S+\s*[;&]*\s*)?(cat|head|sed|less|tail)\b", cmd):
        return "skill " + files[0] + (" +%d" % (len(files) - 1) if len(files) > 1 else "")
    for script in ("measure.py", "gsc.py", "integrity.py", "validate_content.py", "batch_runner.py"):
        if script in cmd:
            return script
    first = (cmd.strip().split() or ["?"])[0]
    return "bash " + os.path.basename(first)


def _read_source(path, cwd):
    if not path:
        return "read ?"
    p = path.replace(os.sep, "/")
    if "/skills/hrd/" in p:
        return "skill " + p.split("/skills/hrd/", 1)[1]
    if cwd and p.startswith(cwd.rstrip("/") + "/"):
        return "read " + p[len(cwd.rstrip("/")) + 1:]
    return "read " + os.path.basename(p)


def _notification_source(text, labels, tools):
    """The agent (or background tool) a `task-notification` reports for."""
    import re

    tid = re.search(r"<tool-use-id>([^<]+)</tool-use-id>", text)
    task = re.search(r"<task-id>([^<]+)</task-id>", text)
    for key in [tid.group(1).strip() if tid else None, task.group(1).strip() if task else None]:
        if key and key in labels:
            return "agent " + labels[key]
    if tid and tid.group(1).strip() in tools:
        name, inp, cwd = tools[tid.group(1).strip()]
        return _tool_source(name, inp, cwd, labels, tid.group(1).strip())
    return "agent ?"


def _tool_source(name, inp, cwd, labels, tool_use_id):
    if name == "Read":
        return _read_source(inp.get("file_path"), cwd)
    if name == "Bash":
        return _bash_source(str(inp.get("command") or ""))
    if name in ("Agent", "Task"):
        label = labels.get(tool_use_id)
        if not label:
            import re

            m = re.match(r"^Herald:\s*(\S+)(?:\s+[—-]\s+(.+))?$", str(inp.get("description") or "").strip())
            label = ("%s — %s" % (m.group(1), m.group(2)) if m and m.group(2) else m.group(1)) if m else "?"
        return "agent " + label
    return "tool " + str(name)


SKILL_INJECTION = "Base directory for this skill:"


def main_detail(path, labels=None):
    """Attribute the main session's per-turn prefix growth to what entered between turns.

    Turns are assistant messages with real usage (synthetic/API-error messages are skipped). Each
    turn's growth beyond the previous turn's output is split over the inputs that arrived in
    between, by estimated tokens; what the estimates miss is `residual_tokens`. A source's
    integral counts it until the next compaction (it leaves the context there)."""
    labels = labels or {}
    tools, turns, pending, excluded, skill_dirs = {}, [], [], {}, []
    seen, compact = set(), False
    measure = {"calls": 0, "result_bytes": 0, "integral": 0}

    def user_text(text, is_meta):
        if is_meta and text.startswith(SKILL_INJECTION):
            skill_dirs.append(text.split("\n", 1)[0][len(SKILL_INJECTION):].strip())
            return "skill", text
        if "<task-notification>" in text:
            return _notification_source(text, labels, tools), text
        return ("harness notice" if is_meta else "human"), text

    try:
        f = open(path, encoding="utf-8")
    except OSError:
        return {}
    with f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = o.get("type")
            msg = o.get("message") or {}
            if t == "assistant":
                for c in msg.get("content") or []:  # every streamed event: one event per content block
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        tools[c.get("id")] = (c.get("name"), c.get("input") or {}, o.get("cwd"))
                mid = msg.get("id") or o.get("uuid")
                u = msg.get("usage") or {}
                prefix = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                if mid in seen or not prefix or msg.get("model") == "<synthetic>" or o.get("isApiErrorMessage"):
                    continue  # a duplicate event, or an error turn the model never ran (inputs carry over)
                seen.add(mid)
                if turns and not compact and prefix < 0.5 * turns[-1]["prefix"]:
                    compact = True  # context cleared without a boundary line
                turns.append({"prefix": prefix, "output": u.get("output_tokens", 0), "inputs": pending,
                              "cache_write": u.get("cache_creation_input_tokens", 0), "compact": compact})
                pending, compact = [], False
            elif t == "user":
                if o.get("isCompactSummary"):
                    compact = True
                content = msg.get("content")
                if isinstance(content, str):
                    pending.append(user_text(content, o.get("isMeta")))
                    continue
                for c in content or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_result":
                        body = c.get("content")
                        if isinstance(body, list):
                            body = "".join(x.get("text", "") for x in body if isinstance(x, dict))
                        name, inp, cwd = tools.get(c.get("tool_use_id"), (None, {}, None))
                        src = _tool_source(name, inp, cwd, labels, c.get("tool_use_id"))
                        status = (o.get("toolUseResult") or {}).get("status") if isinstance(o.get("toolUseResult"), dict) else None
                        if name in ("Agent", "Task") and status in ("async_launched", "forked"):
                            src += " (launch)"  # the stub; the report arrives later as a notification
                        pending.append((src, str(body or "")))
                        if src == "measure.py":  # counted here: a result can land in a compaction turn
                            measure["calls"] += 1
                            measure["result_bytes"] += len(str(body or "").encode("utf-8"))
                    elif c.get("type") == "text":
                        pending.append(user_text(c.get("text") or "", o.get("isMeta")))
            elif t == "attachment":
                a = o.get("attachment") or {}
                text = _att_text(a)
                if text is None:
                    excluded[a.get("type") or "?"] = excluded.get(a.get("type") or "?", 0) + len(json.dumps(a))
                    continue
                if a.get("type") == "queued_command" and "<task-notification>" in text:
                    pending.append((_notification_source(text, labels, tools), text))
                elif a.get("type") == "queued_command":
                    pending.append(("human", text))
                elif a.get("type") == "edited_text_file":
                    pending.append(("edited " + os.path.basename(str(a.get("filename") or "?")), text))
                else:
                    pending.append(("attachment " + str(a.get("type")), text))
            elif t == "system" and o.get("subtype") == "compact_boundary":
                compact = True
    n = len(turns)
    ends, end = [n] * n, n  # each turn's segment ends at the next compaction
    for i in range(n - 1, -1, -1):
        ends[i] = end
        if turns[i]["compact"]:
            end = i
    sources, residual, negative, compactions = {}, 0, 0, 0

    def add(src, b, e, i):
        agg = sources.setdefault(src, {"bytes": 0, "est_tokens": 0, "integral": 0, "count": 0})
        agg["bytes"] += b
        agg["est_tokens"] += int(e)
        agg["integral"] += int(e) * (ends[i] - i)
        agg["count"] += 1

    for i, turn in enumerate(turns):
        if i == 0 or turn["compact"]:
            compactions += 1 if turn["compact"] else 0
            add("base", 0, turn["prefix"], i)
            continue
        delta = turn["prefix"] - turns[i - 1]["prefix"] - turns[i - 1]["output"]
        if turn["prefix"] < turns[i - 1]["prefix"]:
            negative += 1
        ests = [(src, len(text.encode("utf-8")), _est_tokens(text)) for src, text in turn["inputs"]]
        total = sum(e for _, _, e in ests)
        if len({src for src, _, _ in ests}) == 1 and delta > 0 and total > 0:
            ests = [(src, b, delta * e / total) for src, b, e in ests]  # one source: it owns the growth
        else:
            residual += delta - total
        for src, b, e in ests:
            add(src, b, e, i)
            if src == "measure.py":
                measure["integral"] += int(e) * (ends[i] - i)
    total_prefix = sum(t["prefix"] for t in turns) or 1
    top = dict(sorted(sources.items(), key=lambda kv: -kv[1]["integral"])[:40])
    return {"turns": n, "sources": top, "sources_total": len(sources), "residual_tokens": int(residual),
            "negative_deltas": negative, "compactions": compactions, "excluded_bytes": dict(sorted(excluded.items())),
            "cache": {"write_share": round(sum(t["cache_write"] for t in turns) / total_prefix, 4),
                      "creation_spikes": sum(1 for i, t in enumerate(turns) if i and t["cache_write"] > 0.5 * t["prefix"])},
            "skill_dirs": sorted(set(skill_dirs)),
            # the budget check's own measure.py calls (write/translate run it per stage): reported apart so
            # a comparison across versions can take them out
            "measure": measure,
            "integral_total": sum(t["prefix"] for t in turns)}


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
