"""guildcore.roles.result — P-RES (Section C) and the machine fields `out/result.json` (§5.2).

P-RES, as `_handoff.md` Section C states it: a reply carries EXACTLY ONE `>>> RESULT <<<` line and
the next non-empty line is one status of the enum (`DONE`, `DONE_WITH_CONCERNS: …`,
`BLOCKED: …`, `NEEDS_CONTEXT: …`, `FAIL: …`). No sentinel, two sentinels, or a non-enum line is
a contract violation — never inferred from prose. A task may narrow the enum (`allowed=`).

result.json: read from `<run>/out/result.json`; when the file route is unavailable (§5.1
fallback) the last message's ```` ```guild-result ```` fenced block is used instead. Validated
against the task's schema; a BLOCKED status needs `evidence` (A-F27). DONE names artifacts —
their existence is checked (A S0.8).
"""

import json
import os
import re

from guildcore import schema as S

SENTINEL = ">>> RESULT <<<"
STATUSES = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT", "FAIL")
_STATUS_RE = re.compile(r"^(DONE)(?::\s*(.*))?$|^(DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT|FAIL):\s*(\S.*)$")
FENCE_RE = re.compile(r"```guild-result[ \t]*\n(.*?)\n```", re.S)

_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}
# §5.2 role → result.json schema (task-specific narrowing is the caller's)
RESULT_SCHEMAS = {
    "developer": {"type": "object", "required": ["tests", "impl_files", "baselines", "branch",
                                                 "pr_summary_path"],
                  "properties": {"tests": _STRS, "impl_files": _STRS, "red": _STRS,
                                 "root_cause": _STR, "baselines": _STRS, "branch": _STR,
                                 "pr_summary_path": _STR}},
    "tester": {"type": "object", "required": ["covers"],
               "properties": {"covers": {"type": "array", "items": {
                   "type": "object", "required": ["test", "ac", "kind"],
                   "properties": {"test": _STR, "ac": _STR,
                                  "kind": {"type": "string", "enum": ["new", "guard"]}}}},
                   "e2e": {"type": ["string", "boolean", "null", "array"]}}},
    "tech-lead": {"type": "object", "required": ["skeleton"],
                  "properties": {"skeleton": _STR, "split_path": {"type": ["string", "null"]}}},
    "qa": {"type": "object", "required": ["plan", "human_items"],
           "properties": {"plan": _STR, "human_items": {"type": "array"},
                          "followups_path": {"type": ["string", "null"]}}},
    "specialist": {"type": "object", "properties": {"file": _STR, "none_applicable": {"type": "boolean"}},
                   "anyOf": [{"type": "object", "required": ["file"]},
                             {"type": "object", "required": ["none_applicable"]}]},
    "explorer": {"type": "object", "required": ["evidence_path"],
                 "properties": {"evidence_path": _STR}},
    "blocked": {"type": "object", "required": ["evidence"], "properties": {"evidence": _STR}},
}


class Pres(object):
    def __init__(self, ok, status=None, text=None, violation=None):
        self.ok = ok
        self.status = status
        self.text = text            # the one-line remainder after `STATUS:`
        self.violation = violation  # none | duplicate | invalid | narrowed

    @property
    def line(self):
        if not self.ok:
            return None
        return self.status + (": " + self.text if self.text else "")


def parse_pres(reply, allowed=STATUSES):
    lines = (reply or "").split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.strip() == SENTINEL]
    if not idx:
        return Pres(False, violation="none")
    if len(idx) > 1:
        return Pres(False, violation="duplicate")
    rest = [ln.strip() for ln in lines[idx[0] + 1:] if ln.strip()]
    if not rest:
        return Pres(False, violation="invalid")
    m = _STATUS_RE.match(rest[0])
    if not m:
        return Pres(False, violation="invalid")
    status = m.group(1) or m.group(3)
    text = (m.group(2) if m.group(1) else m.group(4)) or None
    if status not in allowed:
        return Pres(False, status=status, violation="narrowed")
    return Pres(True, status, text)


REPAIR_LINE = ("Your previous reply had %s `>>> RESULT <<<` — return EXACTLY one sentinel and one "
               "status from the enum (DONE / DONE_WITH_CONCERNS: … / BLOCKED: … / NEEDS_CONTEXT: … "
               "/ FAIL: …). Do not redo the work.")
_VIOLATION_WORD = {"none": "no", "duplicate": "duplicate", "invalid": "an invalid", "narrowed": "a disallowed"}


def repair_instruction(pres=None, result_errors=None):
    parts = []
    if pres is not None and not pres.ok:
        parts.append(REPAIR_LINE % _VIOLATION_WORD.get(pres.violation, "an invalid"))
    if result_errors:
        parts.append("Your out/result.json is invalid (%s) — rewrite it to the schema in the task; "
                     "do not redo the work." % "; ".join(result_errors[:5]))
    return " ".join(parts)


def read_result_json(run_dir, last_text=""):
    """(obj|None, source, error). Prefers the file; falls back to a guild-result fence."""
    p = os.path.join(run_dir, "out", "result.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh), "file", None
        except (IOError, ValueError) as e:
            return None, "file", "result.json is not valid JSON: %s" % e
    m = FENCE_RE.findall(last_text or "")
    if m:
        try:
            return json.loads(m[-1]), "fence", None
        except ValueError as e:
            return None, "fence", "guild-result block is not valid JSON: %s" % e
    return None, None, "no out/result.json and no guild-result block"


def validate(obj, schema, status=None):
    if status == "BLOCKED":
        schema = RESULT_SCHEMAS["blocked"]
    if obj is None:
        return ["missing"]
    return S.errors(obj, schema)


def missing_artifacts(obj, worktree, run_dir, keys=("skeleton", "split_path", "pr_summary_path",
                                                     "evidence_path", "file", "plan",
                                                     "followups_path")):
    """Named artifact paths that do not exist (relative to worktree, then run/out)."""
    out = []
    for k in keys:
        v = (obj or {}).get(k)
        if not isinstance(v, str) or not v:
            continue
        cands = [v] if os.path.isabs(v) else [os.path.join(worktree or "", v),
                                               os.path.join(run_dir or "", v),
                                               os.path.join(run_dir or "", "out", v)]
        if not any(os.path.exists(c) for c in cands):
            out.append("%s=%s" % (k, v))
    return out
