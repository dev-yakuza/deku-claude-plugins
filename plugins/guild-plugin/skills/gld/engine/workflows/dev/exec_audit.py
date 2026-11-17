"""workflows.dev.exec_audit — execute Step 4 as code: the audit record, dispositions, carry-forward,
re-statement, the MAJOR budget, the cap and the stagnation guard (catalog B P4.2–P4.10, D-4.1–D-4.14,
D-5.5; design §3.3 EX-ARB, §3.4 IDENT/SAMECAUSE, §4.2).

What the judgment layer still owns (and how its answer is bounded here):
* EX-ARB — accept | dismiss | dispute | unsure per NEW BLOCKER/MAJOR finding. `unsure` → accept. A
  dismiss/dispute whose `evidence` quote is not found at the cited file:line ±3 → accept (coerced).
  Unattended, a BLOCKER is never `dismissed`: a dismiss becomes `dispute` → pause `disputed auditor
  BLOCKER` (the human answers dismiss|fix); attended → ask `dismiss-blocker`.
* IDENT — finding identity (J-C1). Code: same id → same; a SAME CANDIDATE = same file ∧ normalized
  text similarity ≥ 0.8; everything else is different. The judge may only DEMOTE a candidate.
* SAMECAUSE — the role axis of the stagnation guard (J-S1); two `suite timed out at` reasons are the
  same by code; unsure → different.
Everything else here is deterministic and unit-tested (tests/engine/test_k3_arbitrate.py).

Identity on the record (C2): every finding line the engine writes ends ` [id:F<k>]`; a legacy line
without one is matched by IDENT and gets the next F id when it is re-stated.
"""

import difflib
import re

from guildcore.records import audit as AU
from guildcore.records import markers

EXECUTE_MAX_ATTEMPTS = 2          # §4.2 (B surprise #1): local-pass blocks excluded
SEVERITIES = ("BLOCKER", "MAJOR", "MINOR")
AXES = ("spec", "standards")
TIMEOUT_PREFIX = "suite timed out at"
SIMILARITY = 0.8


class Cur(object):
    """One finding of THIS attempt's scan (the auditor JSON, schema-checked by the caller)."""

    def __init__(self, severity, axis, file, line, finding, why=""):
        if severity not in SEVERITIES:
            raise ValueError("severity %r" % severity)
        self.severity = severity
        self.axis = axis if axis in AXES else "spec"
        self.file = (file or "").strip()
        self.line = int(line) if str(line or "").isdigit() else 0
        self.finding = " ".join((finding or "").split())
        self.why = " ".join((why or "").split())
        self.fid = None

    @property
    def location(self):
        return "%s:%d" % (self.file, self.line) if self.line else self.file

    @classmethod
    def from_json(cls, obj):
        return cls(obj.get("severity"), obj.get("axis"), obj.get("file"), obj.get("line"),
                   obj.get("finding"), obj.get("why"))

    def as_dict(self):
        return {"id": self.fid, "severity": self.severity, "axis": self.axis, "file": self.file,
                "line": self.line, "finding": self.finding, "why": self.why}


AUDITOR_SCHEMA = {"type": "array", "items": {
    "type": "object", "required": ["severity", "axis", "file", "line", "finding"],
    "properties": {"severity": {"type": "string", "enum": list(SEVERITIES)},
                   "axis": {"type": "string", "enum": list(AXES)},
                   "file": {"type": "string"}, "line": {"type": ["integer", "string"]},
                   "finding": {"type": "string"}, "why": {"type": "string"}}}}


def parse_auditor_reply(text):
    """D-A2: the auditor's reply → list[Cur], or None when unusable (no JSON array, a bad enum, a
    missing key). Only a parsed `[]` is clean. A fenced ```json block or a bare array both count."""
    import json
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", t, re.S)
    cands = [m.group(1)] if m else []
    i = t.find("[")
    if i >= 0:
        cands.append(t[i:t.rfind("]") + 1])
    for c in cands:
        try:
            arr = json.loads(c)
        except ValueError:
            continue
        if not isinstance(arr, list):
            continue
        out = []
        try:
            for o in arr:
                if not isinstance(o, dict) or not all(k in o for k in ("severity", "file", "finding")):
                    raise ValueError("finding shape")
                out.append(Cur.from_json(o))
        except (ValueError, TypeError):
            return None
        return out
    return None


# ---- identity (IDENT) -------------------------------------------------------------------------

def _norm(t):
    t = markers.unescape(t or "").lower()
    t = re.sub(r"`|\*|\[id:F\d+\]", "", t)
    return " ".join(re.findall(r"[\w./-]+", t))


def _path(location):
    return (location or "").split(":")[0].strip("`")


def same_candidate(prev_location, prev_text, cur):
    if _path(prev_location) != cur.file:
        return False
    return difflib.SequenceMatcher(None, _norm(prev_text), _norm(cur.finding)).ratio() >= SIMILARITY


class Prior(object):
    """A finding identity on the record: its latest line, the block it is in, and its key."""

    def __init__(self, key, finding, block):
        self.key = key                     # F<k> or legacy:<block n>:<i>
        self.f = finding                   # guildcore.records.audit.Finding (latest)
        self.block = block                 # AuditBlock of that latest line
        self.first_block = block
        self.first_local_pass = bool(block.local_pass)

    @property
    def fid(self):
        return self.key if self.key.startswith("F") else None


def priors(record):
    """Identity → its latest disposition (a finding's disposition = its most recent block, D-4.6).
    Engine lines carry `[id:F<k>]`; legacy lines are folded by IDENT's code rule against the
    identities seen so far (same file + text similarity)."""
    out = {}
    order = []
    if record is None:
        return out, order
    for b in record.blocks:
        for i, f in enumerate(b.findings):
            if f.severity is None:
                continue
            key = f.fid
            if key is None:
                probe = Cur(f.severity, f.axis or "spec", _path(f.location), 0, f.text)
                key = next((k for k in reversed(order)
                            if same_candidate(out[k].f.location, out[k].f.text, probe)), None) \
                    or "legacy:%d:%d" % (b.n, i)
            if key in out:
                first, flp = out[key].first_block, out[key].first_local_pass
                out[key] = Prior(key, f, b)
                out[key].first_block, out[key].first_local_pass = first, flp
            else:
                out[key] = Prior(key, f, b)
                order.append(key)
    return out, order


def next_fid(record):
    n = 0
    for b in (record.blocks if record else []):
        for f in b.findings:
            if f.fid:
                n = max(n, int(f.fid[1:]))
    return n + 1


def assign_ids(record, cur, prs, ident=None):
    """Each current finding → an identity key (prior or new F<k>). `ident(prior, cur) ->
    'same'|'different'` may only demote a code candidate (JR-M5). Returns {cur index: key}."""
    k = next_fid(record)
    taken, out = set(), {}
    for i, c in enumerate(cur):
        hit = None
        for key, pr in prs.items():
            if key in taken or not same_candidate(pr.f.location, pr.f.text, c):
                continue
            if ident is not None and ident(pr, c) == "different":
                continue
            hit = key
            break
        if hit is None:
            hit = "F%d" % k
            k += 1
        taken.add(hit)
        out[i] = hit
    return out, k


# ---- the block --------------------------------------------------------------------------------

class Line(object):
    def __init__(self, token, severity, axis, location, text, reason=None, fid=None):
        self.token, self.severity, self.axis = token, severity, axis
        self.location, self.text, self.reason, self.fid = location, text, reason, fid

    def render(self):
        return AU.render_finding(self.token, self.severity, self.axis, self.location, self.text,
                                 self.reason, self.fid)


class Arb(object):
    """The Step 4 outcome. kind ∈ advance | retry | stagnant | cap | dispute | ask-dismiss."""

    def __init__(self):
        self.kind = None
        self.lines = []               # finding lines (re-statements first, then this attempt's)
        self.role_axis = []           # `role-axis: <role> <verdict> — <reason>`
        self.signature = []           # auditor axis: ids driving the retry
        self.reasons = []             # every trigger, one line each (pause / loop-back text)
        self.stagnant_reason = None
        self.major_only = False
        self.disputed = []            # (Cur, reason) unattended BLOCKER dismissals → pause
        self.ask = []                 # attended BLOCKER dismissals → ask
        self.dismissed = []           # (fid, reason) — decision-log rows
        self.addressed = []           # prior BLOCKER ids the redo addressed (deferred captures, J-K1)
        self.next_fid = None

    def block(self, n, invocation, head, local_pass=None, scan_none=False, loopback=None):
        return AU.render_block(n, invocation, head, [x.render() for x in self.lines], self.role_axis,
                               local_pass=local_pass, scan_none=scan_none, loopback=loopback)


def role_axis_line(role, verdict, reason):
    return "role-axis: %s %s — %s" % (role, verdict, " ".join((reason or "").split()) or "-")


def carry_ok(prior):
    """D-4.4 eligibility by disposition: dismissed (any severity) or recorded MAJOR; a recorded
    BLOCKER re-blocks."""
    t, s = prior.f.token, prior.f.severity
    return t == "dismissed" or (t == "recorded" and s == "MAJOR")


def arbitrate(record, cur, scan_ran, *, unattended, attempt, attempts_in_invocation, cap=EXECUTE_MAX_ATTEMPTS,
              major_spent=False, role_triggers=(), evidence_reason=None, ex_arb=None, unchanged=None,
              untracked=(), ident=None, samecause=None, human=None, local_pass=False):
    """One Step 4 pass.

    record      the canonical AuditRecord (or None)
    cur         list[Cur] of this attempt's scan ([] = clean); ignored when not `scan_ran`
    role_triggers [(role, verdict, reason)] — tech-lead/gate BLOCKED, verify gap, developer route
    evidence_reason  the Step 2 not-green reason (or None)
    ex_arb      {key: {verdict, reason}} — EX-ARB's answer for NEW BLOCKER/MAJOR findings (already
                coerced by the caller: evidence quotes checked, unsure → accept)
    unchanged   (prior, cur) → True when `git diff --name-only <block head> -- <file>` is empty
                (carry-forward); None → never carried
    untracked   paths `??` in the 3.5a status reading (carry → new)
    human       {key: 'dismiss'|'fix'} answers to a pending dispute / dismiss-blocker question
    local_pass  this pass redoes a local-model job (P4.7): not an attempt, no stagnation vote
    """
    a = Arb()
    prs, order = priors(record)
    pending = [k for k in order if prs[k].f.token == "looped-back"]
    ids, a.next_fid = assign_ids(record, cur, prs, ident) if scan_ran else ({}, next_fid(record))
    reported = set(ids.values())
    ex_arb = ex_arb or {}
    human = human or {}

    # 1. this attempt's findings → provisional dispositions
    now = []                             # (key, Cur, token, reason, blocking)
    for i, c in enumerate(cur if scan_ran else []):
        key = ids[i]
        c.fid = key if key.startswith("F") else None
        pr = prs.get(key)
        if pr is not None and pr.f.token in ("dismissed", "recorded") and carry_ok(pr) and \
                c.file not in untracked and unchanged is not None and unchanged(pr, c):
            now.append((key, c, pr.f.token, pr.f.reason, False))          # carried, same reason
            continue
        if c.severity == "MINOR":
            now.append((key, c, "recorded", None, False))
            continue
        h = human.get(key)
        v = (ex_arb.get(key) or {}).get("verdict", "accept")
        reason = (ex_arb.get(key) or {}).get("reason")
        if h == "dismiss":
            now.append((key, c, "dismissed", "human: %s" % (reason or "dismissed by a person"), False))
            continue
        if h == "fix":
            v = "accept"
        if v in ("dismiss", "dispute"):
            if c.severity == "BLOCKER":
                if unattended or v == "dispute":
                    a.disputed.append((c, reason or "disputed"))
                else:
                    a.ask.append((c, reason or "dismissed"))
                now.append((key, c, None, reason, True))
                continue
            now.append((key, c, "dismissed", reason or "dismissed", False))
            a.dismissed.append((key, reason))
            continue
        now.append((key, c, None, None, True))                            # accepted: blocks (for now)

    # 2. which accepted findings block this pass (severity policy, MAJOR budget, cap)
    blockers = [x for x in now if x[4] and x[1].severity == "BLOCKER"]
    majors = [x for x in now if x[4] and x[1].severity == "MAJOR"]
    others = bool(blockers) or bool(role_triggers) or bool(evidence_reason)
    at_cap = attempts_in_invocation >= cap
    major_blocks = bool(majors) and not major_spent and not at_cap
    if majors and not major_blocks:
        now = [(k, c, "recorded" if (b and c.severity == "MAJOR") else t, r, b and c.severity != "MAJOR")
               for (k, c, t, r, b) in now]
        majors = []
    a.major_only = bool(majors) and not others
    driving = [x for x in now if x[4]]

    # 3. the decision (ordered, D-4.1/P4.5): dispute/ask → pause before anything else is consumed
    triggers = []
    for role, verdict, reason in role_triggers:
        a.role_axis.append(role_axis_line(role, verdict, reason))
        triggers.append("%s %s — %s" % (role, verdict, reason))
    if evidence_reason and not any(r[0] == "verify" for r in role_triggers):
        a.role_axis.append(role_axis_line("verify", "not-green", evidence_reason))
        triggers.append(evidence_reason)
    for k, c, _t, _r, _b in driving:
        triggers.append("auditor %s %s — %s" % (c.severity, c.location, c.finding))
    a.reasons = triggers
    if a.disputed or a.ask:
        a.kind = "dispute" if a.disputed else "ask-dismiss"
    elif not triggers:
        a.kind = "advance"
    else:
        a.signature = sorted(k for k, _c, _t, _r, _b in driving)
        stag = None if local_pass else stagnation(record, a.signature, role_triggers, evidence_reason, samecause)
        if stag:
            a.kind, a.stagnant_reason = "stagnant", stag
        elif at_cap:
            a.kind = "cap"
        else:
            a.kind = "retry"
    retrying = a.kind == "retry"

    # 4. re-state every finding the previous block left at looped-back (D-4.6)
    restated = []
    for key in pending:
        pr = prs[key]
        if key in reported:
            continue                                  # stated below with this attempt's disposition
        if scan_ran:
            tok = "fixed"
            if pr.f.severity == "BLOCKER" and not pr.first_local_pass:
                a.addressed.append(key)
        else:
            tok = "looped-back" if retrying else "recorded"    # scan: none never yields `fixed`
        restated.append(Line(tok, pr.f.severity, pr.f.axis or "spec", pr.f.location, pr.f.text,
                             None, key if key.startswith("F") else None))
    # 5. this attempt's lines
    mine = []
    for key, c, tok, reason, blocking in now:
        if blocking:
            tok = "looped-back" if retrying else "recorded"
        if tok == "dismissed" and c.severity == "BLOCKER" and unattended and not (reason or "").startswith("human:"):
            tok = "recorded"                          # D-4.3: never `dismissed` for a BLOCKER unattended
        fid = key if key.startswith("F") else None
        mine.append(Line(tok, c.severity, c.axis, c.location, c.finding, reason if tok == "dismissed" or
                         (tok == "recorded" and reason) else None, fid))
    # legacy keys re-stated by the engine get a real id
    nid = a.next_fid
    for ln in restated + mine:
        if ln.fid is None:
            ln.fid = "F%d" % nid
            nid += 1
    a.next_fid = nid
    a.lines = restated + mine
    return a


# ---- stagnation (D-4.12, ST A–C) --------------------------------------------------------------

def _is_timeout(reason):
    return TIMEOUT_PREFIX in (reason or "")


def prior_block(record, axis):
    """The most recent block carrying a loop-back reason on `axis` (role | auditor). Skips
    local-pass blocks, `findings: none` blocks with no role axis (advancing/clean) and settle-only
    blocks; `scan: none` blocks count on the role axis only."""
    for b in reversed(record.blocks if record else []):
        if b.local_pass:
            continue
        if axis == "role":
            if b.role_axis:
                return b
        else:
            if b.scan_none:
                continue
            if any(f.token == "looped-back" for f in b.findings):
                return b
    return None


def _role_reason(line):
    m = re.match(r"^(?:- )?role-axis: (\S+) (\S+) — (.*)$", markers.clean(line))
    return (m.group(1), m.group(3)) if m else (None, markers.clean(line))


def stagnation(record, signature, role_triggers, evidence_reason, samecause=None):
    """Any VOTING axis fires → the stagnation reason, else None. The role axis votes iff a role /
    verify reason triggers now; the auditor axis iff a finding does (non-empty signature)."""
    cur_roles = [(r, why) for r, _v, why in role_triggers]
    if evidence_reason:
        cur_roles.append(("verify", evidence_reason))
    if cur_roles:
        pb = prior_block(record, "role")
        if pb is not None:
            prev = [_role_reason(x) for x in pb.role_axis]
            for role, why in cur_roles:
                for prole, pwhy in prev:
                    if _is_timeout(why) and _is_timeout(pwhy):
                        return why
                    if prole != role:
                        continue
                    if samecause is not None and samecause(pwhy, why) == "same":
                        return why
    if signature:
        pb = prior_block(record, "auditor")
        if pb is not None:
            prev = set(f.fid for f in pb.findings if f.token == "looped-back" and f.fid)
            if prev and set(signature) <= prev:
                return "auditor findings %s survived the redo" % ", ".join(sorted(signature))
    return None


def attempts_in_invocation(record, invocation):
    """D-4.10: blocks of this invocation, minus local-pass blocks."""
    return sum(1 for b in (record.blocks if record else []) if b.invocation == invocation and not b.local_pass)


# ---- PR section (D-5.5) -----------------------------------------------------------------------

def latest_dispositions(record):
    prs, order = priors(record)
    return [prs[k] for k in order]


def pr_section(record, language="ko"):
    """`<!-- guild:auditor:pr -->` body — None when no block ever recorded a finding (every block
    `findings: none` / `scan: none`, or no record). One aggregate line for the latest-`fixed`, each
    latest `recorded`/`dismissed` individually."""
    if record is None:
        return None
    latest = latest_dispositions(record)
    if not latest:
        return None
    fixed = [p for p in latest if p.f.token == "fixed"]
    rest = [p for p in latest if p.f.token in ("recorded", "dismissed")]
    stuck = [p for p in latest if p.f.token == "looped-back"]
    head = "### 외부 감사자 지적" if language == "ko" else "### External auditor findings"
    lines = [markers.open_tag("auditor:pr"), head]
    if fixed:
        b = sum(1 for p in fixed if p.f.severity == "BLOCKER")
        m = sum(1 for p in fixed if p.f.severity == "MAJOR")
        n = len(fixed) - b - m
        if language == "ko":
            lines.append("- 수정됨: BLOCKER %d · MAJOR %d · MINOR %d — 이 PR 의 재시도에서 고쳐짐" % (b, m, n))
        else:
            lines.append("- fixed: BLOCKER %d · MAJOR %d · MINOR %d — addressed by a retry in this PR" % (b, m, n))
    for p in rest + stuck:
        f = p.f
        s = "- %s · %s · %s — %s" % (f.token, f.severity, markers.value(f.location or "-"), markers.value(f.text))
        if f.reason:
            s += " — " + markers.value(f.reason)
        lines.append(s)
    inner = markers.finish("\n".join(lines[1:]), structural=False)
    return markers.assert_own_markers("\n".join([lines[0], inner, markers.close_tag("auditor:pr")]), "auditor:pr")


# ---- EX-ARB coercions (§3.3) ------------------------------------------------------------------

def quote_ok(read_file, ev):
    """A dismiss/dispute evidence quote must appear at the cited file:line ±3."""
    path, line, quote = ev.get("path"), ev.get("line"), " ".join((ev.get("quote") or "").split())
    if not path or not quote:
        return False
    text = read_file(path)
    if text is None:
        return False
    ls = text.split("\n")
    try:
        n = int(line)
    except (TypeError, ValueError):
        return False
    lo, hi = max(0, n - 4), min(len(ls), n + 3)
    window = " ".join(" ".join(ls[lo:hi]).split())
    return quote in window


def coerce_ex_arb(fields, read_file):
    """EX-ARB's per-finding verdicts after the code rules: unsure → accept; a dismiss/dispute
    without a quote that matches the file → accept. Returns ({key: {verdict, reason}}, coerced)."""
    out, coerced = {}, False
    for f in fields.get("findings") or []:
        v = f.get("verdict")
        if v == "unsure":
            v, coerced = "accept", True
        if v in ("dismiss", "dispute"):
            evs = f.get("evidence") or []
            if not evs or not all(quote_ok(read_file, e) for e in evs):
                v, coerced = "accept", True
        out[f.get("id")] = {"verdict": v, "reason": " ".join((f.get("reason") or "").split())}
    return out, coerced
