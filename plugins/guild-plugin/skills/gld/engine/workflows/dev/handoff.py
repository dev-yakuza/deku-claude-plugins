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


# ---- K4: the analyze→design and design→execute contracts + SJ-HANDOFF ---------------------------

def analyze_to_design(comments, net_lines=(), unattended=True):
    from workflows.dev.stages import analyze as A
    return A.analyze_to_design(comments, net_lines, unattended)


def skeleton_bad(skeleton):
    if not (skeleton or "").strip():
        return ["skeleton.md empty or missing"]
    if not any(ln.lstrip().startswith("#") for ln in skeleton.split("\n")):
        return ["skeleton.md has no section heading"]
    return []


def cases_bad(test_cases, ac_ids, visual):
    from workflows.dev import analysis as AN
    if not (test_cases or "").strip():
        return ["test-cases.md empty or missing"]
    bad = []
    missing = sorted(set(ac_ids) - AN.ac_ids_in(test_cases))
    if missing:
        bad.append("test-cases.md does not name AC %s" % ", ".join("#%d" % n for n in missing[:8]))
    if visual and "<!-- guild:visual-cases -->" not in test_cases:
        bad.append("VISUAL=yes but no visual-cases marker")
    return bad


def design_to_execute(skeleton, test_cases, ac_ids, visual, split_json=None, specialist_missing=()):
    """§3.6 design→execute: skeleton.md non-empty with a heading; test-cases.md names every AC id;
    VISUAL=yes → the `<!-- guild:visual-cases -->` marker; every DONE specialist's file exists;
    split.json (when given) is valid."""
    bad = skeleton_bad(skeleton) + cases_bad(test_cases, ac_ids, visual)
    for r in specialist_missing:
        bad.append("%s reported DONE without its file" % r)
    if split_json is not None and not isinstance(split_json.get("split"), bool):
        bad.append("split.json has no boolean `split`")
    return bad


CONTRACTS = {
    "analyze→design": "design reads the analysis: a Readiness line, AC #n lines (every safety-net line an AC), "
                      "no unclear dimension unattended",
    "design→execute": "execute reads docs/specs/<N>/skeleton.md (checkable boundaries) and test-cases.md naming "
                      "every AC id (visual-cases marker when VISUAL=yes); specialist files the roles named",
    "execute→test": "test needs an open PR closing the Issue, the latest audit-record block, the execute evidence "
                    "comment (with the ledger when visual config exists), the loop-back consumed",
}


def judge(p, stage, boundary, failed, artifacts, ac_text, issue_summary, step="HO"):
    """SJ-HANDOFF (§3.6) after the contract check failed (and its one repair, where a producer can
    repair) — or at every boundary in `engine.handoff_judge: always`. Returns the Decision; the caller
    acts: ok / ok_with_assumption → go on (the assumption goes to the decision log → C14);
    upstream_gap → by boundary (execute→test fixable at test/qa → loop-back `from: leader`; else a
    person for analyze artifacts, the escalation path for design/execute ones)."""
    from workflows.dev import judging as JG
    from workflows.dev.stages import base as B
    parts = [("boundary", boundary), ("contract", CONTRACTS.get(boundary, "")),
             ("failed", "\n".join("- %s" % x for x in failed) or "(none — always mode)"),
             ("ac", ac_text or "(none)"), ("issue", issue_summary or "")] + list(artifacts)
    d = p.judge(JG.spec(p, "HANDOFF", parts, stage, step))
    B.record_judgment(p, stage, "HANDOFF", "J-DEV-02", d, choice=d.choice,
                      reason=(d.fields.get("line") or d.fields.get("reason") or "")[:300],
                      extra={"boundary": boundary, "failed": "; ".join(failed)[:300] or None,
                             "assumption": d.fields.get("line") if d.choice == "ok_with_assumption" else None,
                             "signature": d.fields.get("signature") or None,
                             "fixable_by_execute": d.fields.get("fixable_by_execute") if d.choice == "upstream_gap" else None})
    return d


def shadow(p, stage, boundary, artifacts, ac_text, issue_summary, step="HO"):
    """§3.6 / §10.4 first-sprint HANDOFF shadow: the same SJ-HANDOFF brief at a boundary whose contract check passed,
    recorded as `HANDOFF-SHADOW` (cost kind `monitoring`, §9.3) and NEVER acted on (no loop-back, no pause, no
    assumption). A shadow that cannot be judged (no judge, a failed call) is skipped with a journal note; a rate limit
    or the kill switch still stops the run. Returns the Decision or None."""
    from workflows.dev import firstsprint as FS
    if getattr(p, "judge", None) is None or not FS.handoff_shadow(p):
        return None
    from guildcore.judges.runner import Halted, RateLimited
    from workflows.dev import judging as JG
    from workflows.dev.stages import base as B
    parts = [("boundary", boundary), ("contract", CONTRACTS.get(boundary, "")),
             ("failed", "(none — shadow: the contract check passed)"),
             ("ac", ac_text or "(none)"), ("issue", issue_summary or "")] + list(artifacts)
    try:
        spec = JG.spec(p, "HANDOFF", parts, stage, step, point="HANDOFF-SHADOW")
        spec.kind = "monitoring"
        d = p.judge(spec)
    except (RateLimited, Halted):
        raise
    except Exception as e:                                       # noqa: BLE001 — a shadow never changes the flow
        if getattr(p, "journal", None) is not None:
            p.journal.append("event", what="handoff-shadow-skipped", boundary=boundary, why=str(e)[:200])
        return None
    B.record_judgment(p, stage, "HANDOFF-SHADOW", "J-DEV-02", d, choice=d.choice,
                      reason=(d.fields.get("line") or d.fields.get("reason") or "")[:300],
                      extra={"boundary": boundary, "shadow": "true",
                             "assumption": d.fields.get("line") if d.choice == "ok_with_assumption" else None,
                             "signature": d.fields.get("signature") or None})
    return d
