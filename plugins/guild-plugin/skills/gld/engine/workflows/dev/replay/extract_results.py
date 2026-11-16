#!/usr/bin/env python3
"""replay.extract_results — canned `result.json` for the procedure replay (§10.2-2, R4F-m4).

The replay feeds the engine canned role results. The new contract's machine fields (developer
`tests/impl_files/baselines/branch/pr_summary_path`, tester `covers`, tech-lead `skeleton/
split_path`, qa `plan/human_items/followups_path`) do not exist in legacy logs; they are derived
ONCE from each role episode (its RESULT line, its last narrative, the files its Edit/Write calls
touched, its Bash commands) and frozen as fixtures:

1. a LOCAL model (Ollama native `/api/chat`, `format` = the field schema, temperature 0) fills
   the fields — zero Claude quota;
2. a deterministic check keeps a field set only when EVERY extracted string value occurs in the
   episode's source text (paths compared after stripping the old worktree prefix); an empty
   list/None is always acceptable;
3. what fails the check is marked `needs: haiku` for the quota stage (≤ $5, §10.2 예산 표) —
   this module never calls Claude.

    extract_results.py --logs '<glob>' --out FILE.jsonl [--limit N] [--model qwen3.8:27b]
"""

import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.request

# loopback only: never route through an http(s)_proxy from the environment
_NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from guildcore import schema as SCH                     # noqa: E402
from guildcore.roles.result import RESULT_SCHEMAS       # noqa: E402
from workflows.dev.replay.permissions_check import role_of   # noqa: E402

TARGET_ROLES = ("developer", "tester", "tech-lead", "qa")
_WT_PREFIX = re.compile(r"/Users/[^/\s]+/projects/(?:\.gld-[^/\s]+/issue-\d+|[^/\s]+)/")
_HANDBACK = re.compile(r"^\s*\[Subagent hand-back\].*?The report follows:\s*", re.S)
SOURCE_CAP = 12000


class Episode(object):
    def __init__(self, log, spawn_id, role, description):
        self.log = log
        self.spawn_id = spawn_id
        self.role = role
        self.description = description
        self.result_text = ""
        self.narrative = []
        self.touched = []
        self.commands = []

    def source(self):
        parts = ["RESULT:\n" + self.result_text, "NARRATIVE:\n" + "\n---\n".join(self.narrative[-3:]),
                 "FILES WRITTEN:\n" + "\n".join(sorted(set(self.touched))),
                 "COMMANDS:\n" + "\n".join(self.commands[-40:])]
        return _WT_PREFIX.sub("", "\n\n".join(parts))[:SOURCE_CAP]


def episodes(path):
    eps = {}
    with open(path, errors="replace") as fh:
        for ln in fh:
            if not ln.startswith("{"):
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            par = e.get("parent_tool_use_id")
            msg = e.get("message") or {}
            content = msg.get("content") if isinstance(msg.get("content"), list) else []
            if e.get("type") == "assistant":
                for c in content:
                    if c.get("type") != "tool_use":
                        if c.get("type") == "text" and par in eps:
                            eps[par].narrative.append(c.get("text") or "")
                        continue
                    if not par and c.get("name") in ("Agent", "Task"):
                        desc = (c.get("input") or {}).get("description") or ""
                        eps[c["id"]] = Episode(path, c["id"], role_of(desc), desc)
                    elif par in eps:
                        inp = c.get("input") or {}
                        if c.get("name") in ("Edit", "Write", "MultiEdit") and inp.get("file_path"):
                            eps[par].touched.append(inp["file_path"])
                        elif c.get("name") == "Bash":
                            eps[par].commands.append((inp.get("command") or "")[:300])
            elif e.get("type") == "user" and not par:
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in eps:
                        cont = c.get("content")
                        txt = cont if isinstance(cont, str) else "\n".join(
                            x.get("text", "") for x in cont or [] if isinstance(x, dict))
                        txt = _HANDBACK.sub("", txt)
                        txt = re.sub(r"\nagentId: .*", "", txt, flags=re.S)
                        eps[c["tool_use_id"]].result_text = txt.strip()
    return [ep for ep in eps.values() if ep.result_text and ">>> RESULT <<<" in ep.result_text]


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            for s in _strings(v):
                yield s
    elif isinstance(obj, list):
        for v in obj:
            for s in _strings(v):
                yield s


ENUM_VALUES = ("new", "guard")


def verify(obj, source):
    """Strings of `obj` that do not occur in `source` (after the worktree prefix is stripped)."""
    bad = []
    for s in _strings(obj):
        t = _WT_PREFIX.sub("", s).strip()
        if not t or t in ENUM_VALUES:
            continue
        if t not in source and os.path.basename(t) not in source:
            bad.append(s)
    return bad


def parse_json_text(text):
    """The first JSON object in a model reply (a ```json fence or bare braces)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cand = m.group(1) if m else text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""
    return json.loads(cand) if cand else None


PROMPT = ("You convert a finished software-role episode into JSON machine fields. Use ONLY strings "
          "that appear verbatim in the record (file paths exactly as written, test names exactly as "
          "written). If the record does not state a field, use an empty list, an empty string or "
          "null. Do not invent anything. Reply with ONLY one JSON object.\n\nRole: {role}\nFields (JSON schema):\n{schema}\n\n"
          "RECORD:\n{source}\n")


def ollama_model(model="qwen3.8:27b", url="http://127.0.0.1:11434", timeout=900):
    def call(role, schema, source):
        # this Ollama build refuses `format` (schema or "json"): "structured output is
        # unavailable" (HTTP 501) — the JSON is asked for in the prompt and parsed from the text;
        # the engine's schema check below is the gate either way
        body = {"model": model, "stream": False, "think": False,
                "options": {"temperature": 0, "num_ctx": 16384},
                "messages": [{"role": "user", "content": PROMPT.format(
                    role=role, schema=json.dumps(schema), source=source)}]}
        req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json"})
        with _NOPROXY.open(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
        return parse_json_text((out.get("message") or {}).get("content") or "")
    return call


def extract(ep, model_fn):
    schema = RESULT_SCHEMAS[ep.role if ep.role in RESULT_SCHEMAS else "specialist"]
    src = ep.source()
    t0 = time.time()
    try:
        obj = model_fn(ep.role, schema, src)
        err = None
    except Exception as e:                      # a model/transport failure is a fixture row too
        obj, err = None, "%s: %s" % (type(e).__name__, e)
    schema_errs = SCH.errors(obj, schema) if obj is not None else ["no output"]
    bad = verify(obj, src) if obj is not None else []
    ok = obj is not None and not schema_errs and not bad
    return {"log": os.path.relpath(ep.log, os.path.dirname(os.path.dirname(ep.log))),
            "spawn_id": ep.spawn_id, "role": ep.role, "description": ep.description,
            "result_line": ep.result_text.strip().split("\n")[-1][:300],
            "extracted": obj, "schema_errors": schema_errs, "not_in_source": bad,
            "verified": ok, "needs": None if ok else "haiku", "error": err,
            "secs": round(time.time() - t0, 1)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--model", default="qwen3.8:27b")
    a = ap.parse_args(argv)
    eps = []
    for p in sorted(glob.glob(a.logs)):
        eps += [e for e in episodes(p) if e.role in TARGET_ROLES]
    # spread across roles
    by = {}
    for e in eps:
        by.setdefault(e.role, []).append(e)
    pick = []
    while len(pick) < a.limit and any(by.values()):
        for r in TARGET_ROLES:
            if by.get(r) and len(pick) < a.limit:
                pick.append(by[r].pop(len(by[r]) // 2))
    fn = ollama_model(a.model)
    n_ok = 0
    with open(a.out, "w", encoding="utf-8") as fh:
        for ep in pick:
            row = extract(ep, fn)
            n_ok += row["verified"]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            sys.stdout.write("%s %s verified=%s %.0fs\n" % (ep.role, ep.spawn_id[-8:], row["verified"], row["secs"]))
            sys.stdout.flush()
    sys.stdout.write(json.dumps({"episodes_total": len(eps), "sampled": len(pick), "verified": n_ok}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
