#!/usr/bin/env python3
"""replay.tmp_rule — how often would the logged roles hit the `/tmp` rule? (K2 measurement, report only)

Q23 role sandbox: writes under `/tmp` (= `/private/tmp`) outside `/tmp/claude-<uid>/` fail with
EPERM; task.md now says "Temporary files go under $TMPDIR, never /tmp". This counts, over the
role (sub-agent) tool calls of the sprint logs, the calls that WRITE to such a path — Write/Edit
`file_path`, Bash redirections (`>`, `>>`, `tee`), `-o`/`--output`, `cp`/`mv`/`mkdir`/`touch`
targets, `mktemp /tmp/…`, `json:/tmp/…` reporters. Reads of /tmp are not counted (allowed).

    tmp_rule.py --logs '<glob>' [--out FILE.json]
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from workflows.dev.replay.permissions_check import role_of     # noqa: E402

TMP = r"(?:/private)?/tmp/(?!claude-\d+/)"
BASH_WRITE_RES = (
    re.compile(r"(?:^|[\s;&|(])\d?>>?\s*['\"]?" + TMP),
    re.compile(r"\btee\s+(?:-a\s+)?['\"]?" + TMP),
    re.compile(r"(?:\s-o\s*|--output[= ]|--out[= ]|json:)['\"]?" + TMP),
    re.compile(r"\b(?:cp|mv|rsync)\b[^;&|]*\s['\"]?" + TMP + r"[^\s;&|]*['\"]?\s*(?:$|[;&|])"),
    re.compile(r"\b(?:mkdir|touch)\b[^;&|]*\s['\"]?" + TMP),
    re.compile(r"\bmktemp\b[^;&|]*\s['\"]?" + TMP),
    re.compile(r"\bgit\s+worktree\s+add\s+['\"]?" + TMP),
)
FILE_RE = re.compile(r"^" + TMP)


def writes_tmp(name, inp):
    if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return bool(FILE_RE.match(inp.get("file_path") or ""))
    if name == "Bash":
        c = inp.get("command") or ""
        return any(rx.search(c) for rx in BASH_WRITE_RES)
    return False


def measure(paths):
    roles = {}
    for p in sorted(paths):
        spawn = {}
        with open(p, errors="replace") as fh:
            for ln in fh:
                if not ln.startswith("{"):
                    continue
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                par = e.get("parent_tool_use_id")
                for c in (e.get("message") or {}).get("content") or []:
                    if c.get("type") != "tool_use":
                        continue
                    if not par and c.get("name") in ("Agent", "Task"):
                        spawn[c["id"]] = role_of((c.get("input") or {}).get("description") or "")
                        continue
                    if par not in spawn:
                        continue
                    r = roles.setdefault(spawn[par], {"calls": 0, "tmp_writes": 0, "sessions": set(),
                                                      "sessions_hit": set(), "examples": []})
                    r["calls"] += 1
                    r["sessions"].add((p, par))
                    if writes_tmp(c.get("name"), c.get("input") or {}):
                        r["tmp_writes"] += 1
                        r["sessions_hit"].add((p, par))
                        if len(r["examples"]) < 3:
                            inp = c.get("input") or {}
                            r["examples"].append((inp.get("command") or inp.get("file_path") or "")[:160])
    out = {}
    tot_c = tot_w = tot_s = tot_h = 0
    for k, r in sorted(roles.items()):
        out[k] = {"calls": r["calls"], "tmp_writes": r["tmp_writes"],
                  "pct_calls": round(100.0 * r["tmp_writes"] / r["calls"], 2) if r["calls"] else 0,
                  "sessions": len(r["sessions"]), "sessions_hit": len(r["sessions_hit"]),
                  "pct_sessions": round(100.0 * len(r["sessions_hit"]) / len(r["sessions"]), 1) if r["sessions"] else 0,
                  "examples": r["examples"]}
        tot_c += r["calls"]
        tot_w += r["tmp_writes"]
        tot_s += len(r["sessions"])
        tot_h += len(r["sessions_hit"])
    out["_all"] = {"calls": tot_c, "tmp_writes": tot_w, "pct_calls": round(100.0 * tot_w / tot_c, 2) if tot_c else 0,
                   "sessions": tot_s, "sessions_hit": tot_h,
                   "pct_sessions": round(100.0 * tot_h / tot_s, 1) if tot_s else 0}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res = measure(glob.glob(a.logs))
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
