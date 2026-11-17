#!/usr/bin/env python3
"""replay.execute_replay — the procedure replay for execute (§10.2-2, K3): legacy word_app sprint logs →
the legacy GitHub state at each execute episode → the ENGINE's Step 4 core and recorders → compare
with what the legacy session wrote.

Episodes: an execute wrapper read (`implement|debug|refactor.md`) up to the next wrapper read. Logs of
one Issue are chained in time order (`procedure.episodes` machinery) so the audit record, the
loop-back record and the evidence comment at the episode's start are the ones the logs posted.

What the logs give and what they do not: the auditor's JSON reply is in the transcript for 10 of 217
auditor spawns (the rest ran in the background — the reply reached the leader as a notification the
log does not keep). So the canned scan of an attempt is reconstructed from the legacy block itself:
its finding lines whose token is `looped-back`/`recorded`/`dismissed` (reported in this attempt's
scan), severity and location as written. That makes two honest modes:

* **by construction** — the engine's block renderer over each legacy block's parsed content
  (`head:`, tokens, findings, role axis): measures record-grammar compatibility only (C1 head key,
  C2 ids are the declared differences). Claims nothing about decisions.
* **derived** — teacher-forced per block: the record before the block is the legacy one; the
  engine's `exec_audit.arbitrate` decides from the reconstructed scan, the block's role-axis lines
  (role triggers), `scan: none` (evidence failure) and the injected EX-ARB verdicts (a legacy
  `dismissed` line → `dismiss` with its reason; everything else `accept`; §10.2-2 injects judgment
  values). The engine's tokens and its decision (advance / retry / exit) are compared with the legacy
  block's tokens and with what the legacy session did next (another block in the same invocation →
  retry; a `guild:test` label edit → advance; a needs-human → exit). Severity policy, the MAJOR
  budget, the cap, re-statement and stagnation are the engine's own code here.

    execute_replay.py --logs '<glob>' --out <dir>
"""

import argparse
import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from guildcore.records import audit as AU                       # noqa: E402
from guildcore.records import markers                           # noqa: E402
from workflows.dev import exec_audit as XA                      # noqa: E402
from workflows.dev.replay import procedure as P                 # noqa: E402

EXEC = ("implement", "debug", "refactor")
RESULT_TOKEN_RE = re.compile(r">>> RESULT <<<\s*\n\s*((?:OK (?:ADVANCE|PAUSE)|NEEDS_HUMAN|NEEDS_CONTEXT|FAIL)[^\n]*)")


class XEpisode(object):
    def __init__(self, log, issue, variant):
        self.log, self.issue, self.variant = log, issue, variant
        self.audit_start = None
        self.audit_end = None
        self.labels = []
        self.pauses = []
        self.pr_create = None
        self.token = None
        self.version = None
        self.loopback_start = None
        self.loopback_end = None
        self.evidence = None

    @property
    def key(self):
        return "%s#%s:%s" % (os.path.basename(self.log), self.issue, self.variant)


def episodes(paths):
    by_issue = collections.OrderedDict()
    for p in sorted(paths):
        n = P.issue_of(p)
        if n:
            by_issue.setdefault(n, []).append(p)
    out = []
    for n, logs in sorted(by_issue.items()):
        state = {}
        for log in sorted(logs, key=lambda x: (re.sub(r"-attempt\d+", "", os.path.basename(x)), x)):
            steps = P.steps_of(log)
            files = P.Files()
            ver = P.plugin_version(log)
            cur = None
            for st in steps:
                w = P.wrapper_of(st)
                if w:
                    if cur is not None and cur.variant == w:
                        continue
                    cur = XEpisode(log, n, w) if w in EXEC else None
                    if cur is not None:
                        cur.version = ver
                        cur.audit_start = state.get("auditor:execute")
                        cur.loopback_start = state.get("loopback")
                        out.append(cur)
                    continue
                files.step(st)
                c = st["input"].get("command") or ""
                po = P.post_of(st, files, n)
                if po and po[0] == "issue":
                    m = P.MARK_RE.match(po[2] or "")
                    if m:
                        state[m.group(1)] = po[2]
                        if cur is not None:
                            if m.group(1) == "needs-human":
                                cur.pauses.append(po[2])
                            elif m.group(1) == "auditor:execute":
                                cur.audit_end = po[2]
                            elif m.group(1) == "loopback":
                                cur.loopback_end = po[2]
                            elif m.group(1) == "test-evidence:step-1":
                                cur.evidence = po[2]
                if cur is None:
                    continue
                le = P.label_edit(st, n)
                if le:
                    cur.labels.append(le)
                if st["name"] == "Bash" and "gh pr create" in c:
                    m = P.BODY_FILE_RE.search(c)
                    if m:
                        path = m.group(1)
                        body = files.files.get(path) or next((v for k, v in files.files.items() if k.endswith("/" + path.lstrip("./"))), None)
                        cur.pr_create = body
                for txt in (st.get("result") or "",):
                    pass
            # the return token: the last RESULT block of the session text
        for ep in [e for e in out if e.issue == n]:
            ep.token = _token(ep.log)
    return out


def _token(log):
    last = None
    with open(log, errors="replace") as fh:
        for ln in fh:
            if '"type":"assistant"' not in ln.replace(" ", "") or "RESULT" not in ln:
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if e.get("parent_tool_use_id"):
                continue
            for c in (e.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    m = RESULT_TOKEN_RE.search(c.get("text") or "")
                    if m:
                        last = m.group(1).strip()
    return last


def _record(body):
    if not body:
        return None
    try:
        return AU.AuditRecord.parse(markers.body_of({"body": body}))
    except ValueError:
        return None


def new_blocks(ep):
    a, b = _record(ep.audit_start), _record(ep.audit_end)
    if b is None:
        return [], a
    n0 = len(a.blocks) if a else 0
    return b.blocks[n0:], b


# ---- loose reading of legacy blocks (replay only — the engine parser stays strict) -------------------

TOK = r"(looped-back|fixed|recorded|dismissed)"
SEV = re.compile(r"\b(BLOCKER|MAJOR|MINOR)\b")
TOKS = re.compile(r"(?<![\w-])" + TOK + r"(?![\w-])")
LOC = re.compile(r"`?([\w./-]+\.[A-Za-z]{1,6}(?::\d+(?:[-–]\d+)?)?)`?")
AXIS = re.compile(r"\b(spec|standards)\b")
ROLES = ("tech-lead", "security", "infra", "i18n", "dba", "analytics", "performance", "tech-writer", "designer",
         "developer", "verify")
ROLE_LOOSE = re.compile(r"(role[- ]axis|역할 ?축|role ?축)", re.I)


class LooseF(object):
    def __init__(self, token, severity, axis, location, text, reason=None, strict=False):
        self.token, self.severity, self.axis = token, severity, axis or "spec"
        self.location, self.text, self.reason, self.strict = location, text, reason, strict


def candidate(ln):
    """A legacy finding line in ANY shape: a severity word and a disposition token on one line
    (token first, token last, `disposition:`, bold, backticks, parenthesized axis, 4/5-column tables)."""
    # a location (file path) is required: a summary sentence ("미기각 BLOCKER 0건 … recorded") is no finding
    return bool(SEV.search(ln)) and bool(TOKS.search(ln)) and bool(LOC.search(ln)) and \
        not AU.ROLE_AXIS_RE.match(ln.lstrip("- "))


def loose_findings(block):
    out = []
    for raw in block.block.lines:
        ln = markers.clean(raw).strip()
        f = AU.Finding(ln)
        if f.token and f.severity:
            out.append(LooseF(f.token, f.severity, f.axis, f.location, f.text, f.reason, True))
            continue
        if not candidate(ln):
            continue
        sev = SEV.search(ln).group(1)
        tok = TOKS.findall(ln)[-1]
        loc = LOC.search(ln)
        ax = AXIS.search(ln)
        text = re.sub(r"[`*|]", " ", ln)
        out.append(LooseF(tok, sev, ax.group(1) if ax else "spec", loc.group(1) if loc else "-",
                          " ".join(text.split())[:200]))
    return out


def blocked_lines(block):
    """Lines that state a role BLOCKED (any shape) — not a resolved/earlier one, not a DONE verdict."""
    out = []
    for raw in block.block.lines:
        ln = markers.clean(raw).strip()
        if not re.search(r"\bBLOCKED\b", ln) or candidate(ln):
            continue
        if re.search(r"해소|이전 BLOCKED|was BLOCKED|previous|BLOCKED`?\**\s*0\s*건|no BLOCKED|BLOCKED`? 없", ln):
            continue
        if re.search(r"(?<![\w_])DONE(?![\w_])", ln.replace("DONE_WITH_CONCERNS", "")):
            continue
        out.append(ln)
    return out


def loose_roles(block):
    """role-axis triggers: strict `role-axis: <role> <BLOCKED|…>` lines, or any BLOCKED statement."""
    out = []
    for raw in block.block.lines:
        st = markers.clean(raw).strip().lstrip("- ")
        m = re.match(r"^role-axis:\s*(\S+)\s+`?([A-Za-z_-]+)`?", st)
        if m:
            if m.group(2) in ("BLOCKED", "NEEDS_CONTEXT", "FAIL", "not-green", "red"):
                out.append(st)
    if out:
        return out
    for ln in blocked_lines(block):
        role = next((r for r in ROLES if r in ln), "role")
        out.append("role-axis: %s BLOCKED — %s" % (role, ln[:200]))
    return out


def reader_complete(block):
    """K3r1-M7: a block is machine-readable for the derived mode only when every candidate finding
    line was read AND every BLOCKED statement became a role trigger (an empty block is complete)."""
    lines = [markers.clean(x).strip() for x in block.block.lines]
    cands = sum(1 for ln in lines if candidate(ln) or (AU.Finding(ln).token and AU.Finding(ln).severity))
    return cands == len(loose_findings(block)) and (not blocked_lines(block) or bool(loose_roles(block)))


# ---- by construction ---------------------------------------------------------------------------

def skeleton(lines):
    """The machine skeleton of a block: heading, keys, tokens, severity/axis, location, role-axis head."""
    out = []
    for raw in lines:
        ln = markers.clean(raw).rstrip()
        if not ln.strip():
            continue
        if ln.startswith("### audit-record"):
            out.append("H")
        elif re.match(r"^(invocation|head|HEAD|local-pass|loopback): ", ln) or AU.SHA_RE.match(ln):
            out.append("K:" + ("head" if AU.SHA_RE.match(ln) else ln.split(":")[0].lower()))
        elif ln in ("scan: none", "findings: none"):
            out.append(ln)
        elif AU.ROLE_AXIS_RE.match(ln):
            out.append("role-axis")
        else:
            f = AU.Finding(ln)
            if f.token:
                out.append("F:%s:%s:%s" % (f.token, f.severity, f.axis))
            else:
                out.append("prose")
    return out


def construct(block):
    """The engine's rendering of a legacy block's content."""
    lines = [XA.Line(f.token, f.severity, f.axis, f.location or "-", f.text or "-", f.reason)
             for f in loose_findings(block)]
    head = block.head or ("0" * 40)
    try:
        return AU.render_block(block.n, block.invocation or "-", head, [x.render() for x in lines],
                               block.role_axis, local_pass=block.local_pass,
                               scan_none=block.scan_none).split("\n")
    except ValueError:
        return None


def classify_construct(leg, eng):
    """Element differences → intentional (C1 head key, C2 ids) | drift (legacy prose lines the engine
    does not write, B-F-18) | defect."""
    out = collections.Counter()
    la = [x for x in leg if x != "prose"]
    prose = sum(1 for x in leg if x == "prose")
    if prose:
        out["intentional:§7 B-F-18 (legacy free-prose line)"] += prose
    ca, ce = collections.Counter(la), collections.Counter(eng)
    # the legacy `disposition: <token>` form (retro's `$d`) is normalized to the token-first line
    for el in [e for e in list(ca) if e.startswith("F:") and e.endswith(":None:None")]:
        tok = el.split(":")[1]
        for e2 in [x for x in ce if x.startswith("F:%s:" % tok) and ce[x] > ca.get(x, 0)]:
            k = min(ca[el], ce[e2] - ca.get(e2, 0))
            if k > 0:
                ca[el] -= k
                ca[e2] = ca.get(e2, 0) + k
                out["intentional:§7 B-F-18 (legacy `disposition:` form normalized)"] += k
        if ca[el] <= 0:
            del ca[el]
    bad = 0
    for el, n in ca.items():                     # a machine element the legacy wrote, missing in the engine's
        miss = max(0, n - ce.get(el, 0))
        bad += miss
    for el, n in ce.items():                     # what the engine adds that the legacy omitted
        extra = max(0, n - ca.get(el, 0))
        if extra:
            out["intentional:§7 B-F-18 (legacy omitted a required machine line: %s)" % el.split(":")[0]] += extra
    if bad:
        out["defect"] += bad
    return out, bad


# ---- derived ---------------------------------------------------------------------------------------

def prefix_record(rec, k):
    """The legacy record holding blocks [0, k)."""
    body = rec.render()
    doc = AU.AuditRecord.parse(body)
    doc.doc.blocks = doc.doc.blocks[:k]
    return AU.AuditRecord(doc.doc)


def derive(rec, k, block, unattended=True):
    """Teacher-forced: the engine's decision for legacy block index k."""
    before = prefix_record(rec, k)
    prs, _ = XA.priors(before)
    scan, ex = [], {}
    for f in loose_findings(block):
        if f.token == "fixed":
            continue
        loc = f.location or "-"
        path, _, line = loc.partition(":")
        c = XA.Cur(f.severity, f.axis or "spec", path.strip("`"), line if line.isdigit() else 0, f.text or "-")
        scan.append((c, f))
    curs = [c for c, _ in scan]
    ids, _n = XA.assign_ids(before, curs, prs, None)
    for i, (c, f) in enumerate(scan):
        if f.token == "dismissed":
            ex[ids[i]] = {"verdict": "dismiss", "reason": f.reason or "dismissed"}
    roles = []
    evidence = None
    for ra in loose_roles(block):
        role, reason = XA._role_reason(ra)
        if role in ("verify",) or "verify" in (role or "") or re.search(r"suite|red|스위트", reason or ""):
            evidence = reason
        else:
            roles.append((role or "role", "BLOCKED", reason))
    if block.scan_none and not evidence:
        evidence = "evidence not green (legacy scan: none)"
    inv = block.invocation
    att = XA.attempts_in_invocation(before, inv) + (0 if block.local_pass else 1)
    major_spent = False
    for b in before.blocks:
        if b.invocation == inv and any(f.token == "looped-back" and f.severity == "MAJOR" for f in b.findings) and \
                not any(f.token == "looped-back" and f.severity == "BLOCKER" for f in b.findings) and not b.role_axis:
            major_spent = True
    a = XA.arbitrate(before, curs, not block.scan_none, unattended=unattended, attempt=att,
                     attempts_in_invocation=att, major_spent=major_spent, role_triggers=roles,
                     evidence_reason=evidence, ex_arb=ex, unchanged=lambda pr, c: True,
                     untracked=(), human=None, local_pass=bool(block.local_pass),
                     samecause=lambda x, y: "same" if markers.unescape(x).strip() == markers.unescape(y).strip() else "different")
    return a


def legacy_next(blocks_all, k, ep):
    """What the legacy session did after block k: retry | advance | exit."""
    b = blocks_all[k]
    if k + 1 < len(blocks_all) and blocks_all[k + 1].invocation == b.invocation:
        return "retry"
    adds = [a for adds, _r in ep.labels for a in adds]
    if "guild:test" in adds:
        return "advance"
    if ep.pauses or "guild:needs-human" in adds or (ep.token or "").startswith(("OK PAUSE", "NEEDS_HUMAN", "FAIL")):
        return "exit"
    if (ep.token or "").startswith("OK ADVANCE"):
        return "advance"
    return "unknown"


def why_mismatch(blk, nxt, ekind, ep):
    """Classify a derived decision mismatch: READER (the replay could not read the legacy block),
    LEGACY (the legacy session broke a spine rule or wrote no reason), ENGINE (everything else)."""
    lines = [markers.clean(x) for x in blk.block.lines]
    if not reader_complete(blk):
        return "READER: legacy finding/BLOCKED line the replay reader did not read"
    dwc = any("DONE_WITH_CONCERNS" in x for x in lines)
    if nxt == "retry" and ekind == "advance":
        if dwc:
            return "LEGACY: leader looped back on a DONE_WITH_CONCERNS (spine: DWC never blocks; user decision: now EX-DWC)"
        return "LEGACY: loop-back reason not on the record (role-axis rule not followed — B-F-18)"
    if nxt == "exit" and ekind == "advance":
        causes = [(markers.clean(b.split("\n")[1]) if len(b.split("\n")) > 1 else "") for b in ep.pauses]
        return "LEGACY: exited after the block for a non-Step-4 reason (%s)" % (
            ", ".join(sorted(set(c.split(" — ")[0][:40] for c in causes if c))) or "no needs-human comment in the log")
    if nxt == "advance" and ekind == "retry" and any(f.token == "looped-back" for f in loose_findings(blk)):
        return "LEGACY: wrote looped-back but no retry block followed in the session"
    if nxt == "advance" and ekind == "retry":
        return "ENGINE: blocks where legacy advanced"
    return "ENGINE: %s vs %s" % (nxt, ekind)


def before_unreadable(rec, k):
    """Pending legacy findings the ENGINE's strict parser cannot see in the blocks before k (the
    engine reads the live record with that parser — retro too)."""
    n = 0
    for b in rec.blocks[:k]:
        n += sum(1 for f in loose_findings(b) if not f.strict and f.token == "looped-back")
    return n


def token_mismatch(ltoks, etoks, unreadable_prior):
    out = []
    lc, ec = collections.Counter(ltoks), collections.Counter(etoks)
    for (tok, sev), n in (lc - ec).items():
        if tok == "looped-back" and sev == "MINOR":
            out += ["LEGACY: looped back on a MINOR (spine: MINOR never blocks)"] * n
        elif tok == "dismissed" and sev == "MINOR":
            out += ["LEGACY: dismissed a MINOR (spine: MINOR is recorded verbatim)"] * n
        elif tok == "fixed" and unreadable_prior:
            out += ["LEGACY: prior pending line in a non-canonical shape (the engine and retro cannot read it)"] * n
        elif tok == "fixed":
            out += ["ENGINE: fixed re-statement not reproduced"] * n
        else:
            out += ["ENGINE: legacy %s/%s not reproduced" % (tok, sev)] * n
    return out


ENGINE_KIND = {"advance": "advance", "retry": "retry", "stagnant": "exit", "cap": "exit", "dispute": "exit",
               "ask-dismiss": "exit"}


def run(paths, out_dir, limit=None):
    eps = episodes(paths)
    rows = []
    agg = {"by_construction": collections.Counter(), "derived": collections.Counter(), "episode": collections.Counter()}
    for ep in eps[:limit] if limit else eps:
        blocks, rec = new_blocks(ep)
        row = {"key": ep.key, "variant": ep.variant, "version": ep.version, "blocks": len(blocks),
               "token": ep.token, "labels": ep.labels, "pauses": len(ep.pauses), "pr_create": bool(ep.pr_create)}
        if not blocks:
            row["skip"] = "no audit block posted in the episode (replay-gap: script edit / session cut / no Step 4)"
            rows.append(row)
            agg["by_construction"]["episodes_without_block"] += 1
            continue
        allb = rec.blocks
        k0 = len(allb) - len(blocks)
        bc, dv = [], []
        for i, blk in enumerate(blocks):
            leg_sk = skeleton(blk.block.lines and [blk.block.heading] + blk.block.lines)
            eng = construct(blk)
            if eng is None:
                bc.append({"n": blk.n, "result": "unrenderable (legacy head missing or malformed)"})
                agg["by_construction"]["unrenderable"] += 1
                continue
            eng_sk = skeleton(eng)
            cls, bad = classify_construct(leg_sk, eng_sk)
            agg["by_construction"]["blocks"] += 1
            agg["by_construction"]["elements"] += len([x for x in leg_sk if x != "prose"])
            agg["by_construction"]["defect_elements"] += bad
            if blk.head_key in (None, "HEAD"):
                agg["by_construction"]["intentional:C1 head key"] += 1
            for kx, v in cls.items():
                agg["by_construction"][kx] += v
            bc.append({"n": blk.n, "defect_elements": bad, "classes": dict(cls)})
            # derived
            a = derive(rec, k0 + i, blk)
            lf = loose_findings(blk)
            ltoks = [(f.token, f.severity) for f in lf]
            complete = reader_complete(blk)
            readable = complete and all(f.strict for f in lf) and all(
                AU.ROLE_AXIS_RE.match(markers.clean(x).strip().lstrip("- ")) or "BLOCKED" not in x
                for x in blk.block.lines)
            if not complete:
                agg["derived"]["blocks_reader_incomplete"] += 1
            agg["derived"]["blocks_machine_readable" if readable else "blocks_loose_read"] += 1
            etoks = [(x.token, x.severity) for x in a.lines]
            nxt = legacy_next(allb, k0 + i, ep)
            ekind = ENGINE_KIND.get(a.kind)
            agg["derived"]["blocks"] += 1
            agg["derived"]["findings_legacy"] += len(ltoks)
            match = sum(min(collections.Counter(ltoks)[t], collections.Counter(etoks)[t]) for t in set(ltoks))
            agg["derived"]["findings_token_match"] += match
            agg["derived"]["findings_engine"] += len(etoks)
            if nxt != "unknown" and nxt != ekind:
                agg["derived"]["mismatch:" + why_mismatch(blk, nxt, ekind, ep)] += 1
            if nxt != "unknown":
                tag = "strict" if readable else "loose"
                agg["derived"]["decisions_" + tag] += 1
                agg["derived"]["decision_match_" + tag] += int(nxt == ekind)
                agg["derived"]["%s:%s_vs_%s" % (tag, nxt, ekind)] += 1
            if collections.Counter(ltoks) != collections.Counter(etoks):
                for cls in token_mismatch(ltoks, etoks, before_unreadable(rec, k0 + i)):
                    agg["derived"]["token_mismatch:" + cls] += 1
            dv.append({"n": blk.n, "legacy_tokens": ltoks, "engine_tokens": etoks, "legacy_next": nxt,
                       "engine": a.kind, "readable": readable, "reasons": a.reasons[:3]})
        row["by_construction"], row["derived"] = bc, dv
        # episode level: the label edits and the PR the engine would write for the LAST block's outcome
        last = dv[-1]["engine"] if dv else None
        adds = [a for a_, _r in ep.labels for a in a_]
        if last == "advance":
            agg["episode"]["engine_advance"] += 1
            if not adds and not ep.token and not ep.pauses:
                agg["episode"]["replay-gap: session cut before Step 6 (the next attempt log continues)"] += 1
            else:
                agg["episode"]["labels_match" if "guild:test" in adds else "labels_differ"] += 1
            if ep.pr_create is not None:
                agg["episode"]["pr_created_by_legacy"] += 1
                agg["episode"]["pr_closes_line_in_legacy"] += int(("Closes #%d" % ep.issue) in ep.pr_create)
        elif last in ("stagnant", "cap", "dispute"):
            agg["episode"]["engine_exit"] += 1
            agg["episode"]["labels_match" if ("guild:needs-human" in adds or ep.pauses) else "labels_differ"] += 1
        if ep.loopback_start and "consumed:" in (ep.loopback_end or "") and "consumed:" not in ep.loopback_start:
            agg["episode"]["legacy_wrote_consumed"] += 1
        rows.append(row)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "execute_episodes.json"), "w") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    s = summarize(rows, agg, len(eps))
    with open(os.path.join(out_dir, "execute_summary.json"), "w") as fh:
        json.dump(s, fh, ensure_ascii=False, indent=1)
    return s


def pct(a, b):
    return round(100.0 * a / b, 2) if b else None


def summarize(rows, agg, n):
    bc, dv = agg["by_construction"], agg["derived"]
    variants = collections.Counter(r["variant"] for r in rows)
    return {
        "episode_level": dict(agg["episode"]),
        "episodes": n, "variants": dict(variants),
        "with_audit_blocks": sum(1 for r in rows if r.get("blocks")),
        "by_construction": dict(bc, element_match_pct=pct(bc["elements"] - bc["defect_elements"], bc["elements"])),
        "derived": dict(dv, token_match_pct=pct(dv["findings_token_match"], dv["findings_legacy"]),
                        decision_match_pct_strict=pct(dv["decision_match_strict"], dv["decisions_strict"]),
                        decision_match_pct_loose=pct(dv["decision_match_loose"], dv["decisions_loose"])),
        "note": ("by_construction = the engine's block renderer over the legacy block content (grammar only); "
                 "derived = teacher-forced exec_audit.arbitrate over the reconstructed scan + role axis + "
                 "injected EX-ARB dismissals — the engine's own severity policy / budget / cap / re-statement "
                 "/ stagnation decide; NOT evidence for judgment quality (EX-ARB/IDENT/SAMECAUSE are injected "
                 "or code-approximated)."),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    s = run(glob.glob(a.logs), a.out, a.limit)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
