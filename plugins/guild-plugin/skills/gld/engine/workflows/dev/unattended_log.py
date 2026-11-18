"""workflows.dev.unattended_log — C14: the PR body's `## 무인 결정 로그 (GLD_UNATTENDED)` section,
wrapped in `<!-- guild:unattended-log -->` … `<!-- /guild:unattended-log -->` and rendered
deterministically from the decision log (§2.6 CR-M11, R2C-N-M5).

Entries, in decision order: every unattended decision that took a choice for a human —
`decide{assumption}`, HANDOFF `ok_with_assumption`, dismiss/dispute, escalate, and a coerced or
`unsure` SJ decision of test/qa — plus the `가정` (assumption) lines of analyze/design output.
A body that still has the bare 0.101.x heading is migrated ONCE (`prbody.migrate_unattended`:
the span becomes the marker block, every byte outside preserved — INV4); after that only the
inside of the markers is re-spliced, on every new decision once the PR exists. The `dev
unattended-log --issue N` CLI (K5) prints `render(comments)`.
"""

import re

from guildcore.decisions import DecisionLog
from guildcore.records import markers
from guildcore.records import outputs as OUT
from guildcore.records import prbody as PB

ASSUMPTION_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?(가정|assumption)s?(?:\*\*)?\s*[:：]\s*(.+)$", re.I)
SJ_POINTS = ("TEST", "QA", "VIS-ENV", "DIRECTIVE", "HANDOFF", "EX-ARB", "EX-DWC", "DE-ARB", "AN-PO", "STAKES",
             "KICKOFF", "ESCALATE", "SPLIT", "INTEGRATE")


def _worthy(b):
    ch = b.get("choice") or ""
    if b.get("point") in ("dwc-recorded", "local-check", "net-unverified", "legacy-pending-unreadable"):        # K3r2-M1/M2: always to the human
        return True
    if b.get("assumption") or b.get("effective_check") == "bypassed":
        return True
    if "ok_with_assumption" in ch or ch.startswith("decide") or ch.startswith("escalate"):
        return True
    if "dismiss:" in ch or "dispute:" in ch:
        return True
    return b.get("point") in SJ_POINTS and (b.get("unsure") == "true" or b.get("coerced") == "true")


def entries(comments):
    out = []
    for b in DecisionLog.load(markers.trusted(comments)).blocks:
        if b.get("by") == "human" or not _worthy(b):
            continue
        why = b.get("assumption") or b.get("reason") or ""
        if b.get("effective_check") == "bypassed":
            why = "effective_check: bypassed — every new-behaviour AC was unverified (compile error after the revert)"
        flag = []
        if b.get("unsure") == "true":
            flag.append("unsure")
        if b.get("coerced") == "true":
            flag.append("coerced:%s" % (b.get("coerced_by") or "rule"))
        out.append("%s %s → %s%s%s — 사람 확인 요" % (
            b.id, b.get("point"), markers.unescape(b.get("choice") or ""),
            (" (%s)" % ", ".join(flag)) if flag else "", (" — " + markers.unescape(why)) if why else ""))
    for name in ("analyze:output", "design:output"):
        so = OUT.find(markers.trusted(comments), name)
        if so is None:
            continue
        for ln in so.body.split("\n"):
            m = ASSUMPTION_RE.match(markers.clean(ln))
            if m:
                out.append("%s 가정: %s — 사람 확인 요" % (name.split(":")[0], m.group(2).strip()))
    return out


def render(comments):
    return PB.render_unattended(entries(comments))


def splice(writer, gh, issue_n, pr_n):
    """Migrate a bare heading once, then splice the rendered block. Returns changed."""
    block = render(gh.comments(issue_n))

    def fn(body):
        return PB.splice_unattended(body, block)
    return writer.pr_body_edit(pr_n, fn)
