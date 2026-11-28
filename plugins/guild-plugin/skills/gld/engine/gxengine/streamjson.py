"""Reading `claude --output-format stream-json --verbose` output (design §6.2, §7.2-3, §7.6) — U12.

Shapes observed with Claude Code 2.1.323 (tests/fixtures/claude/f1, f2 — recorded in
the stage-1 experiments):

  {"type":"system","subtype":"init", "tools":[…], "mcp_servers":[], "model":…,
   "permissionMode":"default", "slash_commands":[], "claude_code_version":"2.1.323",
   "agents":[…], "skills":[], "plugins":[{"name","path","source"}…], "session_id":…}
  {"type":"system","subtype":"thinking_tokens"|"permission_denied"|"hook_started"|"hook_response", …}
  {"type":"assistant","message":{"content":[{"type":"tool_use","id","name","input"}|{"type":"text"}…]}}
  {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id","content","is_error"}]},
   "tool_result_meta":[{"id", "permission_decision":{"decision":"accept"|"reject", …}}]}
  {"type":"result","subtype":"success"|…, "is_error":bool, "total_cost_usd":…,
   "usage":{"cache_read_input_tokens","cache_creation_input_tokens",…}, "num_turns":…,
   "permission_denials":[{"tool_name","tool_use_id","tool_input"}], "terminal_reason":…,
   "result":"<final text>", "structured_output": {…}  ← with --json-schema (confirmed with
   the real CLI 2.1.323: role results P4 canary, leader answers V13 — the same object as the
   StructuredOutput tool input; `result` then holds its JSON text, never read)}

A line that is not JSON is skipped with a warning, never a crash. Every reader below
accepts the mixed stream `iter_events` yields (event dicts and ("warning", text) tuples)
and ignores what it does not understand — judging what is MISSING is the caller's job
(canary / facts), so a reader never invents a value.
"""

import json

WARNING = "warning"


def iter_events(lines):
    """Yield parsed events from an iterable of text lines (bad lines → ("warning", text)).

    Bytes are decoded as UTF-8 (undecodable bytes replaced). Blank lines are skipped
    silently. A line that parses to something other than an object is a warning too.
    """
    for raw in lines:
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode("utf-8", "replace")
        if not isinstance(raw, str):
            yield (WARNING, f"not a text line: {type(raw).__name__}")
            continue
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            yield (WARNING, line[:200])
            continue
        if not isinstance(obj, dict):
            yield (WARNING, line[:200])
            continue
        yield obj


def read_file(path):
    """All events of a stream.jsonl file (a list, warnings included)."""
    with open(path, "rb") as f:
        return list(iter_events(f))


def _events(events):
    return [e for e in events if isinstance(e, dict)]


def warnings(events):
    """The ("warning", text) entries as a list of texts."""
    return [e[1] for e in events if isinstance(e, tuple) and len(e) == 2 and e[0] == WARNING]


def first_init(events):
    """The first system/init event, or None."""
    for e in _events(events):
        if e.get("type") == "system" and e.get("subtype") == "init":
            return e
    return None


def init_count(events):
    """How many system/init events the stream carries (a second one is suspicious)."""
    return sum(1 for e in _events(events) if e.get("type") == "system" and e.get("subtype") == "init")


def result_event(events):
    """The last `type: result` event, or None."""
    found = None
    for e in _events(events):
        if e.get("type") == "result":
            found = e
    return found


def structured_output(result):
    """The structured output of a result event, or None when absent."""
    if not isinstance(result, dict):
        return None
    v = result.get("structured_output")
    return v if isinstance(v, dict) else None


def _content(message):
    if not isinstance(message, dict):
        return []
    c = message.get("content")
    return c if isinstance(c, list) else []


def tool_uses(events):
    """[{id, name, input}] in order."""
    out = []
    for e in _events(events):
        if e.get("type") != "assistant":
            continue
        for c in _content(e.get("message")):
            if isinstance(c, dict) and c.get("type") == "tool_use":
                inp = c.get("input")
                out.append({"id": c.get("id"), "name": c.get("name"),
                            "input": inp if isinstance(inp, dict) else {}})
    return out


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for x in content:
            if isinstance(x, dict) and isinstance(x.get("text"), str):
                parts.append(x["text"])
            elif isinstance(x, str):
                parts.append(x)
        return "\n".join(parts)
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)


def tool_results(events):
    """{tool_use_id: {"content": str, "is_error": bool}}.

    Also "decision": the CLI's permission decision for that call ("accept" / "reject")
    from `tool_result_meta` when present, else None. A repeated id keeps the last result.
    """
    out = {}
    for e in _events(events):
        if e.get("type") != "user":
            continue
        decisions = {}
        for m in e.get("tool_result_meta") or []:
            if isinstance(m, dict) and isinstance(m.get("permission_decision"), dict):
                decisions[m.get("id")] = m["permission_decision"].get("decision")
        for c in _content(e.get("message")):
            if isinstance(c, dict) and c.get("type") == "tool_result":
                tid = c.get("tool_use_id")
                out[tid] = {"content": _text(c.get("content")),
                            "is_error": c.get("is_error") is True,
                            "decision": decisions.get(tid)}
    return out


def permission_denied_events(events):
    """The system/permission_denied events as [{tool_name, tool_use_id, message}]."""
    out = []
    for e in _events(events):
        if e.get("type") == "system" and e.get("subtype") == "permission_denied":
            out.append({"tool_name": e.get("tool_name"), "tool_use_id": e.get("tool_use_id"),
                        "message": e.get("message")})
    return out


def permission_denials(result):
    """result.permission_denials as [{tool_name, tool_input}] (+ tool_use_id when present)."""
    if not isinstance(result, dict):
        return []
    out = []
    for d in result.get("permission_denials") or []:
        if isinstance(d, dict):
            out.append({"tool_name": d.get("tool_name"), "tool_input": d.get("tool_input"),
                        "tool_use_id": d.get("tool_use_id")})
    return out


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def call_cost(result, resumed=False):
    """The cost of THIS call in USD, or None (coordinator decision Z2, stage3/experiments/V18.md §6).

    A `--resume` call's `total_cost_usd` / `modelUsage` are the whole resumed session's totals; only
    `model_usage_since_last_result` (its `costUSD` per model) is this call's. A new session: total_cost_usd
    (the same value). A resumed call without that object: None - the caller's "session cost not recorded"
    path, never the cumulative value counted again."""
    if not isinstance(result, dict):
        return None
    if not resumed:
        return _num(result.get("total_cost_usd"))
    since = result.get("model_usage_since_last_result")
    if not isinstance(since, dict) or not since:
        return None
    costs = [_num(m.get("costUSD")) if isinstance(m, dict) else None for m in since.values()]
    if any(c is None for c in costs):
        return None
    return round(sum(costs), 10)


def cost_and_tokens(result, resumed=False):
    """{"cost_usd", "cache_read_input_tokens", "cache_creation_input_tokens", "num_turns"} (None where absent).

    `resumed` (a --resume call): cost_usd is this call's cost only (call_cost, Z2); usage / num_turns are
    per call already."""
    if not isinstance(result, dict):
        return {"cost_usd": None, "cache_read_input_tokens": None,
                "cache_creation_input_tokens": None, "num_turns": None}
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return {
        "cost_usd": call_cost(result, resumed),
        "cache_read_input_tokens": _num(usage.get("cache_read_input_tokens")),
        "cache_creation_input_tokens": _num(usage.get("cache_creation_input_tokens")),
        "num_turns": _num(result.get("num_turns")),
    }
