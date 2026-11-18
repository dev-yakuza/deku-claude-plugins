"""workflows.dev.grader — the §9.5 grader: two calls per decision, blind then reveal (R4J-B1, R4J-m3, R4J-M1).

    grade(judge, block, issue, evidence, tier, issue_text="") -> row (for grades.jsonl)

* system = `graders/_core.md` + `graders/<group>.md` (when present) + `graders/prosecutor.md` when the decision was
  made by the grader's own tier (opus grading opus) — never the judge rules, habits, `leader-core.md` or the
  project section; the judge runner's §5.1 env contract and `--tools ""` (a JudgeSpec with no tools).
* call ① BLIND: what the decision was about (its point, stage, refs, question/options — never its choice, reason or
  assumption) + the Issue + the post-hoc evidence → `{choice, reason, cited_evidence[]}`.
* call ② REVEAL: the same brief + ①'s answer + the engine's choice (`raw_choice` when coerced) and its reason →
  `{given_info: ok|wrong|unsure, outcome, better_choice?, reason, cited_evidence[]}`. ② is a second single-shot call
  carrying ①'s brief and answer — the judge runner keeps `--no-session-persistence` (§3.1), so `--resume` (a cache
  read) is not used: same information, ② pays its brief again (K6 measures the cost).
* the engine checks every citation: a verbatim (whitespace-normalized, case-insensitive) substring of the EVIDENCE
  part of the brief (the decision, the Issue, the post-hoc evidence — not the reveal, not ①'s own answer). Any
  citation that fails, or none at all → `unsure` (R4C-m7).
* suppression (R4J-M1): `ok` needs a verified citation naming the decision's own object (a finding id, an AC id,
  a `path:line`, the assumption sentence); general signals only (approved, merged, green) → `unsure`.
  TEST `effective` (R6J-M2): `ok` only when the engine's code check passed (`checks` has no fail) and two verified
  citations (the AC sentence and the assertion line).
* flagged = `wrong` · `unsure` · the blind choice differs from the engine's.
* `grader_version` = sha(graders/*.md + both schemas + tier) — a revision re-grades; the same key is never re-called.
No GitHub access here (the caller collects evidence); no output is shown before the person's import (R4J-m4).
"""

import glob
import hashlib
import json
import os
import re

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graders")
BLIND_SCHEMA = {"type": "object", "required": ["choice", "reason", "cited_evidence"],
                "properties": {"choice": {"type": "string"}, "reason": {"type": "string"},
                               "cited_evidence": {"type": "array", "items": {"type": "string"}}}}
REVEAL_SCHEMA = {"type": "object", "required": ["given_info", "outcome", "reason", "cited_evidence"],
                 "properties": {"given_info": {"type": "string", "enum": ["ok", "wrong", "unsure"]},
                                "outcome": {"type": "string", "enum": ["consistent", "inconsistent", "unknown"]},
                                "better_choice": {"type": "string"}, "reason": {"type": "string"},
                                "cited_evidence": {"type": "array", "items": {"type": "string"}}}}
HIDDEN = ("choice", "raw_choice", "reason", "chosen", "chosen_sha", "recommended", "recommended_sha", "assumption",
          "coerced", "coerced_by", "unsure", "inputs", "by", "at", "nonce", "line")
GENERIC = re.compile(r"^\W*(approved?|lgtm|merged|green|passed|pass|all (checks|tests) (passed|green)|ci (green|passed)|"
                     r"ok|success(ful)?|looks good)\W*$", re.I)
TARGET_RE = re.compile(r"\bF\d+\b|\bAC #\d+\b|[\w./-]+\.\w+:\d+")
DEFAULT_TIER = "opus"


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def version(tier):
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(HERE, "*.md"))):
        h.update(os.path.basename(p).encode("utf-8"))
        with open(p, "rb") as fh:
            h.update(fh.read())
    h.update(json.dumps([BLIND_SCHEMA, REVEAL_SCHEMA], sort_keys=True).encode("utf-8"))
    h.update(str(tier).encode("utf-8"))
    return "g" + h.hexdigest()[:12]


def base_group(group):
    return (group or "").split(":")[0]


def system(group, prosecutor):
    parts = [_read("_core.md")]
    g = base_group(group)
    if g and os.path.exists(os.path.join(HERE, "%s.md" % g)):
        parts.append(_read("%s.md" % g))
    if prosecutor:
        parts.append(_read("prosecutor.md"))
    return parts


def _norm(s):
    return " ".join(str(s or "").split()).casefold()


def decision_text(block):
    keep = [(k, v) for k, v in (getattr(block, "fields", None) or [])
            if k not in HIDDEN and k not in ("point", "stage", "id") and v not in (None, "")]
    return "\n".join("%s: %s" % (k, v) for k, v in keep)


def targets(block):
    out = set()
    for f in ("refs", "reason", "choice", "raw_choice", "failed", "question", "signature"):
        out.update(TARGET_RE.findall(str(block.get(f) or "")))
    a = block.get("assumption")
    if a:
        out.add(str(a)[:80])
    return [t for t in out if t]


def verify(cites, base):
    """(verified, failed) — each citation a verbatim substring of `base` (normalized)."""
    b = _norm(base)
    ok, bad = [], []
    for c in cites or []:
        (ok if _norm(c) and _norm(c) in b else bad).append(c)
    return ok, bad


def _test_effective(block):
    ch = str(block.get("raw_choice") or block.get("choice") or "")
    return base_group(block.get("point")) == "TEST" and ch.startswith("effective:") and \
        not ch.startswith("effective:none")


def settle(block, fields, base):
    """The engine's checks on call ②'s answer → (given_info, why demoted | None, verified cites)."""
    gi = fields.get("given_info") or "unsure"
    ok, bad = verify(fields.get("cited_evidence"), base)
    if bad or not ok:
        return "unsure", ("citation not found: %s" % bad[0][:80]) if bad else "no citation", ok
    if gi != "ok":
        return gi, None, ok
    if _test_effective(block):
        checks = str(block.get("checks") or "")
        if not checks or "fail" in checks.lower() or len(ok) < 2:
            return "unsure", "TEST effective: needs the code check passed and the AC + assertion cited", ok
        return "ok", None, ok
    tg = targets(block)
    if tg:
        if not any(_norm(t) in _norm(c) for c in ok for t in tg):
            return "unsure", "ok without a citation of the decision's own object", ok
    elif all(GENERIC.match(c.strip()) for c in ok):
        return "unsure", "ok on general signals only", ok
    return "ok", None, ok


def _spec(group, tier, schema, sys_parts, parts, issue, did, call, choice_key):
    from guildcore.judges.runner import JudgeSpec
    s = JudgeSpec("GRADER", tier, schema, sys_parts, parts, point="GRADER:%s:%s:%s:%s" % (base_group(group), issue,
                                                                                            did, call),
                  choice_key=choice_key, budget_usd=1.0, cap_chars=40000, issue=issue, stage="grade",
                  step="grade-%s" % call, kind="monitoring")
    return s


def grade(judge, block, issue, group, evidence, tier=DEFAULT_TIER, issue_text="", gv=None, pass_no=1):
    """Two grader calls for one decision block → the grades.jsonl row (grader output; never on the sheet)."""
    did = block.id
    ev_parts = [("decision", "point: %s\nstage: %s\n%s" % (block.get("point"), block.get("stage"),
                                                         decision_text(block))),
                ("issue", issue_text or "#%d" % int(issue)), ("post_hoc_evidence", evidence or "(none collected)")]
    if _test_effective(block):
        ev_parts.append(("checks", "engine code check: %s" % (block.get("checks") or "(none)")))
    base = "\n".join(v for _k, v in ev_parts)
    prosecutor = str(block.get("by") or "") == "judge:%s" % tier
    sysp = system(group, prosecutor)
    d1 = judge(_spec(group, tier, BLIND_SCHEMA, sysp, ev_parts, issue, did, "blind", "choice"))
    f1 = dict(d1.fields or {})
    orig = block.get("raw_choice") or block.get("choice") or ""
    reveal = ev_parts + [("your_blind_answer", json.dumps(f1, ensure_ascii=False)),
                         ("engine_choice", "choice: %s%s\nreason: %s" % (
                             orig, (" (coerced by %s to %s)" % (block.get("coerced_by"), block.get("choice"))
                                    if block.get("raw_choice") else ""), block.get("reason") or "-"))]
    d2 = judge(_spec(group, tier, REVEAL_SCHEMA, sysp, reveal, issue, did, "reveal", "given_info"))
    f2 = dict(d2.fields or {})
    gi, why, cites = settle(block, f2, base)
    blind = str(f1.get("choice") or "")
    flagged = gi in ("wrong", "unsure") or _norm(blind) != _norm(orig)
    return {"issue": int(issue), "decision_id": did, "group": group, "grader_version": gv or version(tier),
            "pass": pass_no, "tier": tier, "prosecutor": prosecutor, "blind_choice": blind,
            "original_choice": orig, "given_info": gi, "raw_given_info": f2.get("given_info"), "demoted": why,
            "outcome": f2.get("outcome"), "better_choice": f2.get("better_choice"),
            "reason": " ".join(str(f2.get("reason") or "").split())[:500], "cited_evidence": cites[:8],
            "flagged": flagged}
