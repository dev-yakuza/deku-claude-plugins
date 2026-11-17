"""workflows.dev.handoff — the between-stage contract checks (§3.6, replaces J-DEV-02/03).

    execute→test   an open PR matched to the Issue; the latest audit-record block exists; the
                   execute evidence comment exists (with its ledger when the repo has visual
                   config); the latest active loop-back block (if any) is `consumed:`
    test→qa        test:output present; its **검증 범위** block has (a)–(d); (d) is one of the
                   two E2E literals; the ledger / safety-net blocks are byte-identical copies of
                   the execute evidence's
Each returns a list of failed items (empty = pass). A failure → the producing role repairs once
(same stage) → still failing → SJ-HANDOFF (K4 wires the judge; for test→qa the producer is the
engine's own renderer, so a failure there is an engine defect).
"""

from guildcore import state as ST
from guildcore.checks import visual as V
from guildcore.records import audit as AU
from guildcore.records import loopback as LB
from guildcore.records import markers
from guildcore.records import outputs as OUT
from workflows.dev.stages import render as R

EVIDENCE = "test-evidence:step-1"


def execute_to_test(comments, prs, issue_n, cfg):
    bad = []
    m = ST.match_prs(issue_n, [x for x in prs if (x.get("state") or "OPEN").upper() == "OPEN"])
    if not m.strict:
        bad.append("no open PR closes #%d" % issue_n)
    rec = AU.from_comments(comments)
    if rec is None or not rec.blocks:
        bad.append("no audit-record block")
    ev = markers.find(comments, EVIDENCE)
    if ev is None:
        bad.append("no execute evidence comment")
    elif V.ledger_expected(cfg) and V.block_text(markers.body_of(ev)) is None:
        bad.append("execute evidence has no visual-baselines ledger")
    lb = LB.from_comments(comments)
    if lb is not None and lb.not_yet_handled():
        bad.append("latest loop-back block not consumed")
    return bad


def test_to_qa(comments, cfg=None):
    bad = []
    so = OUT.find(comments, "test:output")
    if so is None:
        return ["no test:output"]
    lines = [markers.clean(x) for x in so.body.split("\n")]
    if "### 검증 범위" not in lines:
        bad.append("no 검증 범위 block")
    for k in ("(a)", "(b)", "(c)", "(d)"):
        if not any(l.startswith("- %s " % k) for l in lines):
            bad.append("검증 범위 %s missing" % k)
    d = [l for l in lines if l.startswith("- (d) ")]
    if d and not (d[0][6:].startswith(R.E2E_SKIP) or d[0][6:].startswith(R.E2E_RUN)):
        bad.append("(d) is not one of the two E2E literals")
    ev = markers.find(comments, EVIDENCE)
    if ev is not None:
        for name in (V.NAME, V.SAFETY_NET):
            src = V.block_text(markers.body_of(ev), name)
            if src is not None and src not in so.body:
                bad.append("%s block not copied verbatim" % name)
    return bad


HANDOFF_POINT = "execute-handoff"


def fill_from_execute(p):
    """K3r1-M2: the execute→test hand-over is DURABLE — execute's `point: execute-handoff` decision
    block carries impl_files, base, branch, head and the push target's host; test fills whatever its
    Ports lack (a fresh process after a restart included). Returns the block's fields or None."""
    from guildcore.decisions import DecisionLog
    from workflows.dev.stages import base as B
    blk = None
    for b in DecisionLog.load(B.records(p)).blocks:
        if b.get("point") == HANDOFF_POINT and b.get("stage") == "execute":
            blk = b
    if blk is None:
        return None
    impl = [x for x in (blk.get("impl_files") or "").split(",") if x and x != "-"]
    if p.impl_files is None:
        p.impl_files = impl
    if not p.base and blk.get("base"):
        p.base = blk.get("base")
    if not p.branch and blk.get("branch"):
        p.branch = blk.get("branch")
    p.pushed_head = blk.get("head")
    return {"impl_files": impl, "base": blk.get("base"), "branch": blk.get("branch"),
            "head": blk.get("head"), "push": blk.get("push")}
