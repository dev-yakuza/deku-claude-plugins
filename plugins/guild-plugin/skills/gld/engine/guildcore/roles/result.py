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
# 0.102.12 (one-man-company #687 / every real run since 0.101): the separators models actually write after a status —
# `DONE — out/test-cases.md`, `DONE (out/i18n.md)`, `DONE - …`, a full-width colon, a bold / code-span status — 14
# repair sessions in the real runs were for these alone. Read as `STATUS: text`.
_LOOSE_RE = re.compile(r"^[*`_]{0,3}(DONE_WITH_CONCERNS|DONE|BLOCKED|NEEDS_CONTEXT|FAIL)[*`_]{0,3}"
                       r"(?:\s*(?:[:：]|—|–|-{1,2}(?=\s))\s*(.*)|\s*\((.*)\)\s*(.*)|\s*)$")
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
    status, text = _status_of(rest[0])
    if status is None:
        return Pres(False, violation="invalid")
    if status not in allowed:
        p = Pres(False, status=status, violation="narrowed")
        p.text = text
        return p
    return Pres(True, status, text)


def _status_of(line):
    """(status, text) of one status line — the strict form, else the separators models write (`_LOOSE_RE`); a status
    other than DONE still needs its one-line text — except a BLOCKED / FAIL / NEEDS_CONTEXT line in any case or form
    (`blocked: …`, `Status: BLOCKED — …`, `BLOCKED.`, a bare `BLOCKED`), which is that status, never DONE (0.102.13
    B1). (None, None) when it is no status line."""
    m = _STATUS_RE.match(line)
    if m:
        return m.group(1) or m.group(3), (m.group(2) if m.group(1) else m.group(4)) or None
    m = _LOOSE_RE.match(line)
    if m:
        status = m.group(1)
        if m.group(3) is not None:
            text = ("%s %s" % (m.group(3).strip(), (m.group(4) or "").strip())).strip()
        else:
            text = (m.group(2) or "").strip()
        text = text or None
        if status != "DONE" and not text:
            m = None
        else:
            return status, text
    m = _BLOCKING_LINE_RE.match(line)
    if m:
        word = m.group(1).lower()
        status = "BLOCKED" if word == "blocked" else "NEEDS_CONTEXT" if word.startswith("needs") else "FAIL"
        return status, (m.group(2) or "").strip() or None
    return None, None


# 0.102.13 (review-0102-12 B1): a status line that says BLOCKED / FAIL / NEEDS_CONTEXT in a form the strict and loose
# readers do not take — lowercase, `Status: BLOCKED`, `BLOCKED.`, `BLOCKED → …`, bare — is read as that status.
_BLOCKING_LINE_RE = re.compile(r"^[*`_\s]*(?:status\s*[:：=]?\s*)?[*`_]*(blocked|fail(?:ed)?|needs[_ -]?context)\b"
                               r"[*`_]*[\s:：.,;!→>=\-–—]*(.*)$", re.I)
# 0.102.15 (review-0102-13 B1 — lead decision 1): the structured result stands in for the status line by an ALLOW shape
# only — the line after the one RESULT marker starts with the word `done` (any case, markdown marks allowed: `Done.`,
# `done — …`, `**done**`), never `done_with_concerns`. A deny-list of blocking words (0.102.13) leaves every other
# spelling of a refusal (`REJECTED: …`, `CHANGES_REQUESTED`, a Japanese refusal, no marker at all) open.
_DONE_WORD_RE = re.compile(r"^[*`_\s]*done(?![A-Za-z0-9_])", re.I)


def _filled(v):
    return v is not None and v != "" and v != [] and v != {} and not (isinstance(v, str) and not v.strip())


def required_filled(obj, schema):
    """True when `schema` has required fields and `obj` carries every one non-empty (one `anyOf` / `oneOf` branch's
    required set suffices). A schema with no required field never is (0.102.13 B1 condition c)."""
    if not isinstance(obj, dict) or not isinstance(schema, dict):
        return False
    req = schema.get("required") or []
    if req:
        return all(_filled(obj.get(k)) for k in req)
    for k in ("anyOf", "oneOf"):
        alts = [b.get("required") or [] for b in schema.get(k) or [] if isinstance(b, dict)]
        if any(r and all(_filled(obj.get(x)) for x in r) for r in alts):
            return True
    return False


def structured_pres(pres, obj, allowed=STATUSES, reply="", schema=None):
    """0.102.12 (one-man-company #687: tech-lead design wrote skeleton.md, split.json and a valid result.json, ended
    `DONE_WITH_CONCERNS: …` where the task allows DONE / BLOCKED / NEEDS_CONTEXT / FAIL — three sessions, then a
    pause): the status line could not be used but `out/result.json` validated — the structured result decides.
    0.102.15 (review-0102-13 B1 — lead decision 1, an allow shape): ONLY for
      (a) a narrowed DONE_WITH_CONCERNS line where DONE is allowed (#687) → `DONE: concerns — …`, and
      (b) one RESULT marker whose next non-empty line starts with the word `done` (any case) → DONE (a result.json
          `status` other than DONE contradicts the line → repair),
    each with the schema's required fields all present and non-empty (0.102.13 condition c). Every other unusable
    line — no marker, two markers, `REJECTED: …`, a refusal in any language, a narrowed FAIL — returns None: the
    repair session (once, then INVALID). No whole-reply word scan any more (review-0102-13 m1)."""
    if pres is None or pres.ok:
        return None
    if (reply or "").count(SENTINEL) != 1 or pres.violation not in ("narrowed", "invalid"):
        return None
    if not required_filled(obj, schema):
        return None
    if pres.violation == "narrowed":
        if pres.status == "DONE_WITH_CONCERNS" and "DONE" in allowed:
            return Pres(True, "DONE", "concerns — %s" % (pres.text or "-"))
        return None
    if "DONE" not in allowed or not _DONE_WORD_RE.match(_after_sentinel(reply)):
        return None
    st = obj.get("status")
    if isinstance(st, str) and st.strip() and st.strip().upper() != "DONE":
        return None
    return Pres(True, "DONE", "status from out/result.json (the RESULT line was %r)" % _after_sentinel(reply)[:80])


def _after_sentinel(reply):
    lines = [ln.strip() for ln in (reply or "").split("\n")]
    if SENTINEL not in lines:
        return ""
    rest = [ln for ln in lines[lines.index(SENTINEL) + 1:] if ln]
    return rest[0] if rest else ""


REPAIR_LINE = ("Your previous reply had %s `>>> RESULT <<<` — return EXACTLY one sentinel and one "
               "status from the enum (DONE / DONE_WITH_CONCERNS: … / BLOCKED: … / NEEDS_CONTEXT: … "
               "/ FAIL: …). Do not redo the work.")
_VIOLATION_WORD = {"none": "no", "duplicate": "duplicate", "invalid": "an invalid", "narrowed": "a disallowed"}


def repair_instruction(pres=None, result_errors=None, allowed=None):
    parts = []
    if pres is not None and not pres.ok:
        parts.append(REPAIR_LINE % _VIOLATION_WORD.get(pres.violation, "an invalid"))
        if allowed and tuple(allowed) != STATUSES:
            # 0.102.12 (#687): a narrowed task names ITS statuses — the general enum above lists all five
            parts.append("This task allows only: %s." % " / ".join(allowed))
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


def retire_result_json(run_dir, tag):
    """Move an earlier session's out/result.json aside before a fresh spawn (K1-m2)."""
    p = os.path.join(run_dir, "out", "result.json")
    if os.path.exists(p):
        os.replace(p, p + "." + tag)  # fs-ok: renames the role out/ entry itself (a link is renamed, never followed)
