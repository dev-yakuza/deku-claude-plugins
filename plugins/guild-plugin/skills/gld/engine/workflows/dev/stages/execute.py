"""workflows.dev.stages.execute — the `execute` stage as code: implement / debug / refactor on one spine
(catalog B §2 P0–P6; design §3.3 EX-ARB, §3.4 IDENT/SAMECAUSE/BRANCH/GATECAST/MUTATION, §4.2, §5.1).

    X0  enter (C-F-1) → design input (NEEDS_CONTEXT) → unresolved auditor-violation guard → the
        pending loop-back (latest active block without `consumed:`) → base/branch/worktree
        (`p.prepare`, branching.py) → the gate-config guard (K3 carry-over 2) → RF: net mode,
        previous net block, P0.R2 proof residue on a bound branch → the resume summary
    X1  1L (local model, first spawn only, skip rules) or the developer (attempt 2 = one rung up);
        refactor with a net: P0.R2 cleanup runs inside the role runner BEFORE the scope check
    X2  the ENGINE's suite (after the K1 deps step in the worktree, `p.deps`), raw output wins,
        timeout = not green, the visual ledger, the variant EVIDENCE RULE, the evidence comment
    X3  tech-lead conformance;  X3.5a the auditor with the mutation tripwire (D-M*);  X3.5b gates
    X4  EX-ARB (new BLOCKER/MAJOR, developer BLOCKED/NEEDS_CONTEXT) → `exec_audit.arbitrate` →
        the audit-record block (every attempt that reaches Step 4) → advance | retry | exit
    X5  push (drift check, fixed URL, hooks off) → PR create or marker splice
    X6  the loop-back block `consumed:` (+ `loopback: <n>` on the audit block) → label → ADVANCE
Every needs-human exit unstages the 1L staged tests first (except auditor-violation exits).
"""

import json
import os
import re
import tempfile

from guildcore import ask as ASK
from guildcore import checks as CH
from guildcore.checks import visual as V
from guildcore.records import audit as AU
from guildcore.records import loopback as LB
from guildcore.records import markers
from guildcore.records import outputs as OUT
from guildcore.records import prbody as PB
from guildcore import state as ST
from workflows.dev import exec_audit as XA
from workflows.dev import judging as JG
from workflows.dev import tripwire as TW
from workflows.dev import unattended_log as UL
from workflows.dev import variants as VR
from workflows.dev import vcs as VC
from workflows.dev.stages import base as B
from workflows.dev.variants import refactor_net as RN

STAGE = "execute"
EVIDENCE = "test-evidence:step-1"
CEILING_S = 3600
TIERS = ("haiku", "sonnet", "opus")
GATE_ROLES = ("security", "infra", "designer")
PARTICIPATION = ("i18n", "dba", "analytics", "performance", "tech-writer")
SECURITY_WORDS = re.compile(r"auth|session|token|secret|password|permission|credential", re.I)
DEFAULT_TRIGGERS = {"infra": (".github/**", "**/Dockerfile", "**/*.tf", "fastlane/**", "**/Fastfile",
                              "ios/Podfile", "android/**/build.gradle*", "codemagic.yaml"),
                    "i18n": ("lib/l10n/**", "**/*.arb", "**/locales/**", "**/i18n/**"),
                    "dba": ("**/migrations/**", "**/*.sql", "**/schema*")}
INV2_RE = re.compile(r"^gate INV2 — (.+?)(?: \(subject removed: (.+)\))?$")
TIMEOUT_RE = re.compile(r"suite timed out at")


def tier_up(model, attempt):
    if attempt < 2 or model not in TIERS:
        return model
    return TIERS[min(TIERS.index(model) + 1, len(TIERS) - 1)]


def cfg_dict(p):
    c = p.config
    return getattr(c, "raw", None) or (c if isinstance(c, dict) else {})


class Ctx(object):
    """What one invocation holds (catalog B §1.1 ephemeral variables)."""

    def __init__(self, variant):
        self.variant = variant
        self.stage_start = None
        self.loopback = None              # the pending block (unconsumed) or None
        self.loopback_n = None
        self.fresh = True
        self.resume = "none — fresh branch"
        self.net_mode = "none"
        self.net_prev = None
        self.staged_note = None
        self.staged_tests = []
        self.ran_1l = False
        self.local_job = None
        self.major_spent = False
        self.reinvoked = False
        self.dwc = []                     # DONE_WITH_CONCERNS lines for the PR
        self.ledger = None
        self.withdrawn = []
        self.retry_reason = None
        self.reinvoke_addendum = None
        self.pr_summary_path = None
        self.red = None
        self.net_now = None


# ---- the stage ------------------------------------------------------------------------------------

def run(p, variant):
    if variant not in VR.VARIANTS:
        raise B.StageError("unknown execute variant %r" % variant)
    e = B.enter(p, STAGE)
    if isinstance(e, B.StageResult):
        return e
    cx = Ctx(variant)
    cx.stage_start = getattr(p, "stage_start", None) or p.now()
    comments = B.records(p)
    B.note_untrusted(p, STAGE)
    nc = VR.design_input(p, variant, comments)                                  # P0.2
    if nc:
        return B.StageResult(B.StageResult.FAIL, line=nc, fail_class="needs_context")
    bad = [v for v in AU.violations(comments) if not v.resolved]               # P0.9
    if bad:
        ref = "comment %s" % bad[-1].comment_id
        return nh(p, cx, "#%d's branch still carries unreviewed auditor changes — revert them, then append the "
                  "resolved marker to the auditor-violation note (%s)" % (p.issue, ref),
                  "unresolved auditor violation", unstage=False)
    lb = LB.from_comments(comments)                                             # P0.11
    if lb is not None and lb.not_yet_handled():
        cx.loopback = lb.latest_active()
        cx.loopback_n = int(LB.NUMBERED_RE.match(markers.clean(cx.loopback.heading)).group(1))
    prep = getattr(p, "prepare", None)                                          # P0.10–P0.13
    if prep is not None:
        from workflows.dev import branching as BR
        try:
            got = prep(cx.loopback.get("branch") if cx.loopback else None)
        except BR.BranchProblem as bp:
            if bp.kind in ("base-unusable", "base-missing"):
                return B.fail(p, STAGE, bp.line, "defect")
            short = {"ambiguous": "ambiguous branch for #%d" % p.issue, "blocked": "branch switch blocked"}[bp.kind]
            return nh(p, cx, "#%d %s" % (p.issue, bp.line), short, kind="ambiguity" if bp.kind == "ambiguous" else "defect")
        p.root, p.branch, p.base = got["path"], got["branch"], got["base"]
        cx.fresh = got.get("fresh", True)
        p.vcs = VC.Vcs(p.root) if getattr(p, "vcs", None) is None or getattr(p.vcs, "root", None) != p.root else p.vcs
        if got.get("refused"):
            B.record_code(p, STAGE, "ignored_refused", "refused", reason=", ".join(got["refused"]))
    if not p.branch or not p.base:
        return B.fail(p, STAGE, "could not resolve the base/branch for #%d" % p.issue, "defect")
    if p.vcs.gates_config_changed(p.base):                                      # K3 carry-over 2
        line = "developer wrote outside its scope — .claude/guild/config.json gates (the gate's off-switch)"
        return nh(p, cx, "#%d %s" % (p.issue, line), line)
    if variant == "refactor":                                                   # P0.R
        issue = p.gh.issue(p.issue)
        cx.net_mode = RN.mode(issue.get("body"))
        if cx.net_mode != "none":
            ev = markers.find(comments, EVIDENCE)
            cx.net_prev = RN.parse_block(V.block_text(markers.body_of(ev), V.SAFETY_NET)) if ev else None
            if cx.net_prev is None and _open_pr(p):
                return nh(p, cx, "#%d safety net has no evidence on an open PR" % p.issue,
                          "safety net evidence missing")
            if not cx.fresh:
                res = RN.residue(p.root, p.branch, p.base)
                if res.state == "staged-on-branch":
                    cx.staged_note = "files are staged but not committed — commit them first"
                elif res.state in ("proof-copies", "detached-clean"):
                    why = RN.cleanup(p.root, p.branch, res)
                    if why:
                        return nh(p, cx, "cannot switch to #%d's branch %s — %s" % (p.issue, p.branch, why),
                                  "branch switch blocked")
                elif res.state in ("not-proof",):
                    return nh(p, cx, "#%d left on a detached checkout with staged changes that are not proof "
                              "copies" % p.issue, "proof residue")
    if not cx.fresh:                                                            # P0.14 (B-F-19)
        cx.resume = resume_summary(p, cx)
    pend = gate_inv2_pending(p)                                                 # P4.5-2 re-entry
    if pend and not gate_dismissed(p, pend):
        return nh(p, cx, "gate INV2 — %s: add a dismissal to .claude/guild/gates/dismissed.md or restore the "
                  "test, then continue" % pend, "gate INV2", ask_kind=None)
    return attempts(p, e, cx)


def attempts(p, e, cx):
    record0 = AU.from_comments(B.records(p))
    attempt = 1
    retry_note = None
    while True:
        dev, local_pass = developer_step(p, cx, attempt, retry_note)            # X1
        if isinstance(dev, B.StageResult):
            return dev
        if dev.status == "FAIL":
            return B.fail(p, STAGE, "developer FAIL — %s" % (dev.line or ""), "defect")
        m = INV2_RE.match(dev.line or "") if dev.status == "BLOCKED" else None
        if m:
            return gate_inv2(p, cx, m.group(1), m.group(2))
        ev = evidence_step(p, cx, dev, attempt)                                 # X2
        if isinstance(ev, B.StageResult):
            return ev
        green, reason = ev
        role_triggers, scan, scan_ran, mb, head, untracked = [], [], False, None, None, ()
        dev_route = None
        if dev.status in ("BLOCKED", "NEEDS_CONTEXT") and not TIMEOUT_RE.search(dev.line or ""):
            dev_route = (dev.status, dev.line)
        if green and dev_route is None:
            tl = conformance_step(p, cx, attempt)                               # X3
            if isinstance(tl, B.StageResult):
                return tl
            if tl.status == "FAIL":
                return B.fail(p, STAGE, "tech-lead FAIL — %s" % (tl.line or ""), "defect")
            if tl.status == "BLOCKED":
                role_triggers.append(("tech-lead", "BLOCKED", tl.line or ""))
            elif tl.status == "DONE_WITH_CONCERNS":
                cx.dwc.append("tech-lead: %s" % (tl.line or ""))
            au = auditor_step(p, cx, attempt)                                   # X3.5a
            if isinstance(au, B.StageResult):
                return au
            scan, mb, head, untracked = au
            scan_ran = True
            for role, res in gates_step(p, cx, attempt, mb):                    # X3.5b
                if isinstance(res, B.StageResult):
                    return res
                if res.status == "FAIL":
                    return B.fail(p, STAGE, "%s FAIL — %s" % (role, res.line or ""), "defect")
                if res.status == "BLOCKED":
                    role_triggers.append((role, "BLOCKED", res.line or ""))
                elif res.status == "DONE_WITH_CONCERNS":
                    cx.dwc.append("%s: %s" % (role, res.line or ""))
        elif dev_route is not None:
            role_triggers.append(("developer", dev_route[0], dev_route[1] or ""))
        if dev.status == "DONE_WITH_CONCERNS":
            cx.dwc.append("developer: %s" % (dev.line or ""))
        sp = (dev.extras or {}).get("pr_summary_path")
        if sp:
            rd = getattr(dev, "run_dir", None)
            cands = [sp] if os.path.isabs(sp) else \
                (([os.path.join(rd, "out", sp), os.path.join(rd, sp)] if rd else []) + [os.path.join(p.root, sp)])
            for cand in cands:
                if cand and os.path.exists(cand):
                    cx.pr_summary_path = cand
                    break
        out = arbitrate_step(p, cx, attempt, scan, scan_ran, head, untracked, role_triggers,
                             None if green else reason, local_pass, dev_route, record0)   # X4
        if isinstance(out, B.StageResult):
            return out
        if out == "advance":
            return pr_step(p, e, cx)                                            # X5–X6
        if out == "reinvoke":
            retry_note = cx.reinvoke_addendum
            continue
        if not local_pass:
            attempt += 1
        retry_note = cx.retry_reason


# ---- X0 helpers -----------------------------------------------------------------------------------

def resume_summary(p, cx):
    """P0.14 as code: the branch log, the porcelain status and this Issue's own uncommitted files."""
    log = p.vcs.log("%s..HEAD" % p.base)
    st = p.vcs.status()
    own = []
    for b in [markers.body_of(c) for c in B.records(p)]:
        for ln in b.split("\n"):
            m = re.search(r"unstaged, not committed: (.+)$", ln)
            if m:
                own += [x.strip() for x in m.group(1).split(",")]
    parts = ["commits on the branch:\n%s" % (log or "(none)"), "uncommitted:\n%s" % (st or "(clean)")]
    if own:
        parts.append("this Issue's own uncommitted files (keep and commit them): %s" % ", ".join(own))
    return "\n\n".join(parts)


def gate_inv2_pending(p):
    from guildcore.decisions import DecisionLog
    log = DecisionLog.load(B.records(p))
    for blk in reversed(log.blocks):
        if blk.get("stage") == STAGE and blk.get("point") == "gate-inv2":
            return None if blk.get("choice") == "resolved" else blk.get("refs")
    return None


def gate_dismissed(p, path):
    """P4.5-2: `^[-*+] +`?<path>`?( |—|$)` in the worktree's dismissed.md."""
    text = p.read_file(".claude/guild/gates/dismissed.md") or ""
    rx = re.compile(r"^[-*+] +`?%s`?( |—|$)" % re.escape(path), re.M)
    if rx.search(text):
        B.record_code(p, STAGE, "gate-inv2", "resolved", refs=path)
        return True
    return False


def gate_inv2(p, cx, path, subject):
    B.record_code(p, STAGE, "gate-inv2", "pending", refs=path,
                  reason="the commit gate refused a test change (INV2)")
    prose = ("커밋 게이트가 테스트 변경을 거부했습니다(INV2): `%s`%s. 테스트를 되돌리거나, 정당한 변경이면 "
             "`.claude/guild/gates/dismissed.md` 에 그 경로를 한 줄로 남긴 뒤 이어서 진행하세요. "
             "작업 트리는 그대로 두었습니다." % (path, (" (subject removed: %s)" % subject) if subject else ""))
    return nh(p, cx, "gate INV2 — %s" % path, "gate INV2 — %s" % path, prose=prose, token="gate INV2")


def _open_pr(p):
    try:
        return bool(p.gh.pr_for_head(p.branch))
    except Exception:
        return False


# ---- X1 developer ---------------------------------------------------------------------------------

def _inputs(p, cx, retry_note):
    n = p.issue
    issue = p.gh.issue(n)
    comments = B.records(p)
    des = OUT.find(comments, "design:output")
    ana = OUT.find(comments, "analyze:output")
    lb = cx.loopback
    ins = {"issue.md": "# %s\n\n%s\n" % (issue.get("title") or "", issue.get("body") or ""),
           "design.md": des.body if des else "(none)",
           "analyze.md": ana.body if ana else "(none)",
           "skeleton-path.txt": "docs/specs/%d/skeleton.md\n" % n,
           "test-cases-path.txt": "docs/specs/%d/test-cases.md\n" % n,
           "resume.md": cx.resume + ("\n\n" + cx.staged_note if cx.staged_note else ""),
           "loopback.md": ("from: %s\nreason: %s\nsignature: %s\n" % (lb.get("from"), markers.unescape(lb.get("reason") or ""),
                                                                    markers.unescape(lb.get("signature") or ""))) if lb else "none",
           "retry.md": retry_note or "none"}
    if cx.variant == "refactor":
        prev = RN.render_block(cx.net_prev) if cx.net_prev else "none"
        ins["net.md"] = ("SAFETY_NET = %s\nearlier net:\n%s\nrunnable here: %s\nmerge base: %s\nbranch: %s\n" % (
            cx.net_mode, prev, (cfg_dict(p).get("commands") or {}).get("test"), p.vcs.merge_base(p.base), p.branch)
            if cx.net_mode != "none" else "SAFETY_NET = none")
    return ins


def developer_step(p, cx, attempt, retry_note):
    """→ (RoleResult-like, local_pass: bool) or a StageResult."""
    if attempt == 1 and not cx.ran_1l and local_eligible(p, cx):
        cx.ran_1l = True
        r = local_step(p, cx)
        if r is not None:
            return r
    model = None
    per = p.config.persona("developer") if hasattr(p.config, "persona") else None
    base_model = (per.model if per else None) or "sonnet"
    if base_model not in TIERS:
        base_model = "sonnet"
    model = tier_up(base_model, attempt)
    pre = None
    if cx.variant == "refactor" and cx.net_mode != "none":
        pre = lambda wt: post_dev_residue(p, wt)                           # noqa: E731 (R7C-M1 order)
    call = B.RoleCall("developer", cx.variant, STAGE, "X1", inputs=_inputs(p, cx, retry_note), attempt=attempt,
                      model=model, pre_check=pre)
    res = p.run_role(call)
    if res.status == "BRANCH":
        short = "wrong branch" if "left the checkout" in (res.line or "") else "proof residue"
        return nh(p, cx, "#%d %s" % (p.issue, res.line), short), False
    o = B.role_outcome(p, STAGE, "developer", res)
    if o is not None:
        return o, False
    if p.vcs.gates_config_changed(p.base):
        line = "developer wrote outside its scope — .claude/guild/config.json gates (the gate's off-switch)"
        return nh(p, cx, "#%d %s" % (p.issue, line), line), False
    return res, False


def post_dev_residue(p, wt):
    """P0.R2 right after the developer: on <branch> + staged → loop back (handled by the caller via a
    retry note); another branch → NH; detached → cleanup/switch or NH."""
    res = RN.residue(wt, p.branch, p.base)
    if res.state == "other-branch":
        return "developer left the checkout on %s" % res.detail
    if res.state == "not-proof":
        return "left on a detached checkout with staged changes that are not proof copies"
    if res.state in ("proof-copies", "detached-clean"):
        why = RN.cleanup(wt, p.branch, res)
        if why:
            return "cannot switch back to %s — %s" % (p.branch, why)
    return None


# ---- 1L (local developer) ---------------------------------------------------------------------------

def local_eligible(p, cx):
    """D-1.2: the six skip rules."""
    if not (cfg_dict(p).get("local_developer") or {}).get("enabled") or getattr(p, "local_dev", None) is None:
        return False
    if cx.loopback is not None or cx.variant == "refactor":
        if cx.loopback is not None:
            _ld(p, ["note", "--issue", str(p.issue), "--event",
                    "loopback-%s: %s" % (cx.loopback.get("from"), markers.unescape(cx.loopback.get("reason") or ""))])
        return False
    tc = p.read_file("docs/specs/%d/test-cases.md" % p.issue) or ""
    if "<!-- guild:visual-cases -->" in tc:
        return False
    sk = p.read_file("docs/specs/%d/skeleton.md" % p.issue)
    if not (sk or "").strip():
        return False
    if not cx.fresh:
        st = _ld(p, ["status", "--issue", str(p.issue)])
        if (st or {}).get("state") in (None, "none"):
            return False
    return True


def _ld(p, args):
    """D-1.3: any local_dev error → `fallback` with `tool error: <line>`."""
    try:
        return p.local_dev(args)
    except Exception as e:                    # noqa: BLE001 — the tool's failure is a fallback
        return {"state": "fallback", "reason": "tool error: %s" % str(e).split("\n")[0]}


def local_step(p, cx):
    """1L-1..1L-5 → None (go to Step 1), (result, True) for a local pass, or a StageResult."""
    st = _ld(p, ["status", "--issue", str(p.issue)])
    state = (st or {}).get("state")
    if state in (None, "none"):
        call = B.RoleCall("developer", "tests", STAGE, "X1L", inputs=_inputs(p, cx, None))
        r = p.run_role(call)
        o = B.role_outcome(p, STAGE, "developer", r)
        if o is not None:
            return o, False
        if r.status in ("BLOCKED", "NEEDS_CONTEXT", "FAIL"):
            return r, False                                        # this IS attempt 1 (S:253)
        x = r.extras or {}
        if r.status != "DONE" or not x.get("tests") or not x.get("impl_files"):
            return None                                            # local-ineligible → Step 1
        cx.staged_tests = list(x["tests"])
        args = ["start", "--issue", str(p.issue), "--base", p.base, "--files"] + list(x["impl_files"]) + \
            ["--tests"] + list(x["tests"])
        if x.get("root_cause"):
            args += ["--note", x["root_cause"]]
        if not p.unattended:
            args.append("--attended")
        st = _ld(p, args)
        cx.red = x.get("red") or []
        state = (st or {}).get("state")
    ceiling = int(os.environ.get("BASH_MAX_TIMEOUT_MS") or 600000)
    guard = 0
    while state in ("queued", "running") and guard < 200:                  # 1L-4
        st = _ld(p, ["wait", "--issue", str(p.issue), "--max-seconds", str(max(1, ceiling // 1000 - 60))])
        state = (st or {}).get("state")
        guard += 1
    if state == "local_pass":                                               # 1L-5
        cx.local_job = st.get("job_id")
        if st.get("tree") == "uncommitted":
            ok, line = p.commit_local(st.get("files") or [], cx.staged_tests)
            if not ok:
                rv = _ld(p, ["revert", "--issue", str(p.issue)])
                if (rv or {}).get("reason") == "restore_failed":
                    _ld(p, ["ack", "--issue", str(p.issue)])
                    return nh(p, cx, "#%d after the local model's job, %s need a human look — restore or keep each "
                              "by hand" % (p.issue, ", ".join(st.get("files") or [])), "local developer left files to check")
                _ld(p, ["note", "--issue", str(p.issue), "--event", "commit-refused: %s" % line])
                return None
        if st.get("tree") == "restored":
            return None
        _ld(p, ["ack", "--issue", str(p.issue)])
        from guildcore.roles.runner import RoleResult
        return RoleResult("DONE", None, {"tests": cx.staged_tests, "impl_files": st.get("files") or [],
                                         "red": cx.red or [], "local_job": cx.local_job,
                                         "local_author": "%s (attempts %s)" % (st.get("model") or "local model",
                                                                               st.get("attempt_count"))}), True
    if state == "fallback" and st.get("reason") == "restore_failed":
        _ld(p, ["ack", "--issue", str(p.issue)])
        return nh(p, cx, "#%d after the local model's job, %s need a human look — restore or keep each by hand"
                  % (p.issue, ", ".join(st.get("files") or [])), "local developer left files to check")
    if state == "fallback" and not str(st.get("reason") or "").startswith("tool error"):
        _ld(p, ["ack", "--issue", str(p.issue)])
    return None


# ---- X2 evidence ------------------------------------------------------------------------------------

def suite_cmds(p):
    cmds = (cfg_dict(p).get("commands") or {}).get("test")
    return list(cmds) if isinstance(cmds, (list, tuple)) else ([cmds] if cmds else [])


def evidence_step(p, cx, dev, attempt):
    """→ (green, reason) or a StageResult (env halts, runner pause)."""
    cmds = suite_cmds(p)
    if not cmds:
        return B.fail(p, STAGE, "commands.test is not configured", "defect")
    deps = getattr(p, "deps", None)
    if deps is not None:                                                    # K3 carry-over 3
        d = deps()
        if d is not None and not d.passed:
            return B.build_inputs_changed(["(dependency step in the worktree)"], "execute",
                                          getattr(d, "warm", None), CH.redact_lines("\n".join((d.raw or "").split("\n")[-4:])))
    r = p.suite(cmds, "developer", CEILING_S)
    if getattr(r, "missing_ignored", None):
        return B.ignored_missing(r.missing_ignored, "execute")
    if getattr(r, "build_inputs_changed", None):
        return B.build_inputs_changed(r.build_inputs_changed, "execute", getattr(r, "warm", None),
                                      getattr(r, "warm_detail", None))
    summ = CH.parse_summary(r.raw, config=cfg_dict(p))
    reason = None
    if r.timed_out:
        reason = "suite timed out at %d ms — last running: %s" % (r.ceiling_s * 1000, r.last_running or "?")
        green = False
    elif summ is None:
        return B.pause(p, STAGE, "env", "테스트 요약 형식을 읽지 못함 — commands.test_summary 를 설정하세요",
                       "테스트 요약 형식을 읽지 못함", env_key="other")
    else:
        green = bool(r.passed and summ.green)
        if not green:
            reason = "suite red — %s" % (r.red_line() or "failed")
    claimed = dev.status in ("DONE", "DONE_WITH_CONCERNS")
    if claimed and not green and not r.timed_out:                           # J-E1 verify gap
        p.capture("verify-gap", STAGE, "developer", "developer reported done; the engine's run is red",
                  CH.redact_lines(r.red_line() or ""), VR.CAPTURE_AREA[cx.variant], True)
    if dev.status in ("BLOCKED", "NEEDS_CONTEXT") and green:
        green = False
        reason = None
    rows, run, notes = [], False, []
    if V.ledger_expected(cfg_dict(p)):
        ev = markers.find(B.records(p), EVIDENCE)
        prev = VC.parse_ledger(V.block_text(markers.body_of(ev))) if ev else []
        rows, run, notes = VC.visual_rows(p.vcs, p.base, cfg_dict(p), VC.declared((dev.extras or {}).get("baselines")), prev)
        cases = re.findall(r"\b(V\d+|VC-?\d+)\b", (p.read_file("docs/specs/%d/test-cases.md" % p.issue) or ""))
        und = VC.undeclared(rows, cases)
        if green and und:
            green, reason = False, "undeclared visual change: %s" % ", ".join(und)
        cx.ledger = (rows, run)
    if green:
        met, why, concern = VR.evidence_rule(cx.variant, green, dict(dev.extras or {}, dwc=dev.line if
                                             dev.status == "DONE_WITH_CONCERNS" else ""),
                                             ["%s %s%s" % (c, pth, (" — " + rr) if rr else "") for c, pth, rr in rows],
                                             getattr(cx, "red", None))
        if not met:
            green, reason = False, why
        if concern:
            cx.dwc.append("developer: %s" % concern)
    net_block = None
    if cx.variant == "refactor" and cx.net_mode != "none":
        nb = net_from_result(p, cx, dev)
        net_block = RN.render_block(nb)
        cx.net_now = nb
        if green and (cx.net_prev or {}).get("verified") != "yes":
            bad = RN.checks(p.root, p.base, p.branch, nb, net_mode=cx.net_mode)
            if bad:
                green, reason = False, "re-prove the net — %s" % bad[0]
    write_evidence(p, cx, dev, r, summ, green, reason, rows, run, notes, net_block)
    return green, reason


def net_from_result(p, cx, dev):
    x = dev.extras or {}
    prev = cx.net_prev or {}
    nb = {"verified": "no", "sha": x.get("safety_net") or prev.get("sha"), "run": x.get("net_run") or prev.get("run") or [],
          "net": x.get("net") or prev.get("net") or [], "deferred": x.get("deferred") or prev.get("deferred") or [],
          "post-transform-net": x.get("post_transform_net") or prev.get("post-transform-net") or [],
          "leftover": RN.untracked_leftovers(p.root)}
    if nb["sha"] == "existing":
        nb["sha"] = prev.get("sha")
    return nb


def write_evidence(p, cx, dev, r, summ, green, reason, rows, run, notes, net_block):
    from workflows.dev.stages import render as R
    lines = [markers.open_tag(EVIDENCE), "## execute 증거 (%s) — #%d" % (cx.variant, p.issue), "",
             "브랜치 `%s` · 커밋 `%s`" % (markers.value(p.branch), (p.vcs.head() or "")[:9]), "",
             "**전체 스위트 — 엔진 직접 실행 원문**"]
    lines += R.raw_block(r.raw)
    lines.append("판정: %s%s" % ("green" if green else "not green", (" — " + markers.value(reason)) if reason else ""))
    red = (dev.extras or {}).get("red") or getattr(cx, "red", None)
    if red:
        lines += ["", "**재현(red, 수정 전)**"] + R.raw_block("\n".join(red))
    if (dev.extras or {}).get("local_author"):
        lines += ["", "작성: %s" % markers.value(dev.extras["local_author"])]
    for n in notes:
        lines.append(markers.value(n))
    body = "\n".join(lines)
    if V.ledger_expected(cfg_dict(p)):
        body += "\n\n" + VC.render_ledger(rows, run)
    if net_block:
        body += "\n\n" + net_block
    body += "\n" + markers.close_tag(EVIDENCE)
    p.writer.upsert_comment(p.issue, EVIDENCE, body)


def net_verify(p, cx, tl_line, findings):
    """P4.11 / J-R2 (code): `verified: yes` iff the checks passed and neither the tech-lead nor the
    auditor named a net file."""
    nb = getattr(cx, "net_now", None)
    if not nb:
        return
    named = any(any(n and n in (tl_line or "") for n in nb["net"]) for _ in [0]) or \
        any(f.file in nb["net"] for f in findings)
    if named or RN.checks(p.root, p.base, p.branch, nb, net_mode=cx.net_mode):
        return
    nb = dict(nb, verified="yes")
    ev = markers.find(B.records(p), EVIDENCE)
    if ev is None:
        return
    body = markers.body_of(ev)
    old = V.block_text(body, V.SAFETY_NET)
    if old is None:
        return
    p.writer.upsert_comment(p.issue, EVIDENCE, body.replace(old, RN.render_block(nb)))


# ---- X3 / X3.5a / X3.5b -------------------------------------------------------------------------------

def _tier(p, role, attempt, default="sonnet"):
    per = p.config.persona(role) if hasattr(p.config, "persona") else None
    m = (per.model if per else None) or default
    return tier_up(m if m in TIERS else "sonnet", attempt)


def conformance_step(p, cx, attempt):
    mb = p.vcs.merge_base(p.base)
    checks = {"implement": "Does the change implement the skeleton and every test case?",
              "debug": "Is the fix at the root cause, with a regression test that failed before it?",
              "refactor": "Is the structure genuinely improved toward the target, behavior preserved, no test weakened?"
                          + (" Safety net mode: %s." % cx.net_mode if cx.net_mode != "none" else "")}[cx.variant]
    ins = dict(_inputs(p, cx, None), **{"diff.patch": p.vcs.diff("%s..HEAD" % mb, ".") if mb else "",
                                        "checks.md": checks})
    res = p.run_role(B.RoleCall("tech-lead", "conformance", STAGE, "X3", inputs=ins, attempt=attempt,
                                model=_tier(p, "tech-lead", attempt),
                                allowed_status=("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL")))
    o = B.role_outcome(p, STAGE, "tech-lead", res)
    return o if o is not None else res


def auditor_step(p, cx, attempt):
    """→ (findings, mb, head, untracked) or a StageResult."""
    mb = p.vcs.merge_base(p.base)
    if not mb:
        return B.fail(p, STAGE, "cannot resolve the merge base of #%d's branch and %s — the execute-stage audit "
                      "could not run" % (p.issue, p.base), "defect")
    own_specs = [f for f in (getattr(cx, "dev_tests", []) or []) if f.startswith("docs/specs/")]
    for shot in (1, 2):
        tmp = (p.run_tmp("auditor") if getattr(p, "run_tmp", None) else tempfile.mkdtemp())
        before_path = os.path.join(tmp, "mutation-before.json")
        before = p.vcs.readings(mb)
        TW.save(before_path, before)
        keep, _disc, unclear = TW.audited_remainder(before, p.issue, own_specs)
        if not keep:
            return B.fail(p, STAGE, "#%d's branch has no changes against %s — nothing to audit" % (p.issue, p.base),
                          "defect")
        if unclear:
            B.record_code(p, STAGE, "provenance", "unresolved", reason=", ".join(unclear[:5]))
        spec_line = ("docs/specs/%d/ IS this Issue's deliverable — review it as the change" % p.issue
                     if any(x.startswith("docs/specs/%d/" % p.issue) for x in keep) else "docs/specs/ is intent only")
        ins = {"diff.patch": p.vcs.diff(mb, "."), "mb.txt": mb + "\n",
               "untracked.txt": "\n".join(before["untracked"]) or "none", "spec-line.txt": spec_line + "\n"}
        res = p.run_role(B.RoleCall("auditor", "scan", STAGE, "X3.5a", inputs=ins, attempt=attempt,
                                    model=tier_up("sonnet", attempt), schema={"type": "object", "required": ["findings"],
                                                                                "properties": {"findings": XA.AUDITOR_SCHEMA}}))
        after = p.vcs.readings(mb)
        cmp = TW.compare(TW.load(before_path), after)
        if cmp["verdict"] == "attribute":
            after = p.vcs.readings(mb)                                          # D-M7 re-take once
            cmp = TW.compare(TW.load(before_path), after)
        if cmp["verdict"] == "attribute":
            v = mutation_judge(p, mb, cmp["residue"])
            cmp["verdict"] = "formatter" if v in ("formatter", "artifact") else "mutation"
        if cmp["verdict"] == "mutation":
            return violation(p, cx, before, after, cmp)
        if cmp["verdict"] in ("formatter", "artifact", "benign"):
            B.record_code(p, STAGE, "tripwire", cmp["verdict"], reason=", ".join(cmp["paths"][:5]))
        o = B.role_outcome(p, STAGE, "auditor", res) if res.status not in ("DONE", "INVALID") else None
        if o is not None:
            return o
        found = None
        if res.status == "DONE":
            found = XA.parse_auditor_reply(json.dumps((res.extras or {}).get("findings")))
        if found is not None:
            return found, mb, before["head"], set(before["untracked"])
        if shot == 2:
            return nh(p, cx, "execute-stage auditor returned no usable findings for #%d" % p.issue, "auditor scan failed")
    return None


def mutation_judge(p, mb, paths):
    if p.judge is None:
        return "mutation"
    diffs = "\n".join(p.vcs.diff(mb, x)[:3000] for x in paths[:8])
    d = p.judge(JG.spec(p, "MUTATION", [("paths", "\n".join(paths)), ("diffs", diffs)], STAGE, "X3.5a"))
    return d.choice


def violation(p, cx, before, after, cmp):
    """P35a.9: discard, touch nothing, a NEW violation note, then NH (no unstaging)."""
    note = TW.violation_note(p.issue, before, after, cmp, before["head"], p.language)
    c = p.writer.create_comment(p.issue, note)
    return nh(p, cx, "execute-stage auditor modified the repo — the working tree changed during the scan — the "
              "auditor or a repo hook (note: comment %s)" % c.get("id"), "auditor violated read-only", unstage=False)


def gate_cast(p, mb):
    """J-G1: config `engine.gate_triggers` globs (+ defaults), security on keyword hits in unclassified
    paths or added lines; the residue goes to MJ-GATECAST when roles exist. Returns [role]."""
    import fnmatch
    names = p.vcs.names("%s..HEAD" % mb) if mb else []
    trig = dict(DEFAULT_TRIGGERS)
    trig.update(p.engine_cfg("gate_triggers", {}) or {})
    roles, classified = [], set()
    for role, globs in trig.items():
        hit = [n for n in names if any(fnmatch.fnmatch(n, g) for g in globs)]
        if hit:
            roles.append(role)
            classified.update(hit)
    residue = [n for n in names if n not in classified]
    added = "\n".join(l[1:] for l in p.vcs.diff("%s..HEAD" % mb, ".").split("\n") if l.startswith("+") and not l.startswith("+++")) if mb else ""
    if any(SECURITY_WORDS.search(n) for n in residue) or SECURITY_WORDS.search(added or ""):
        roles.append("security")
    avail = [r for r in GATE_ROLES + PARTICIPATION if p.exists(".claude/agents/%s.md" % r)]
    roles = [r for r in dict.fromkeys(roles) if r in avail]
    rest = [r for r in avail if r not in roles]
    if residue and rest and p.judge is not None:
        d = p.judge(JG.spec(p, "GATECAST", [("candidates", "\n".join(rest)), ("paths", "\n".join(residue[:80])),
                                            ("added", (added or "")[:8000])], STAGE, "X3.5b"))
        pick = d.fields.get("roles") or []
        if d.unsure:
            pick = [r for r in rest if r in GATE_ROLES]
        roles += [r for r in pick if r in rest]
    return roles


def gates_step(p, cx, attempt, mb):
    out = []
    for role in gate_cast(p, mb):
        ins = dict(_inputs(p, cx, None), **{"diff.patch": p.vcs.diff("%s..HEAD" % mb, ".")})
        res = p.run_role(B.RoleCall(role, "review", STAGE, "X3.5b", inputs=ins, attempt=attempt,
                                    model=_tier(p, role, attempt), schema_role="specialist",
                                    allowed_status=("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL")))
        o = B.role_outcome(p, STAGE, role, res)
        out.append((role, o if o is not None else res))
    return out


# ---- X4 arbitrate -----------------------------------------------------------------------------------

def arbitrate_step(p, cx, attempt, scan, scan_ran, head, untracked, role_triggers, evidence_reason,
                   local_pass, dev_route, record0):
    comments = B.records(p)
    rec = AU.from_comments(comments)
    prs, _order = XA.priors(rec)
    ids, _k = XA.assign_ids(rec, scan, prs, _ident(p)) if scan_ran else ({}, 0)
    # NEW = not already accepted and under retry (`looped-back`) and not carried forward unchanged
    vcs0 = p.vcs
    new_bm = [(ids[i], c) for i, c in enumerate(scan) if c.severity in ("BLOCKER", "MAJOR") and not (
        ids[i] in prs and (prs[ids[i]].f.token == "looped-back" or (
            XA.carry_ok(prs[ids[i]]) and c.file not in untracked and vcs0.unchanged(prs[ids[i]].block.head, c.file))))]
    for i, c in enumerate(scan):
        c.fid = ids.get(i)
    ex, route, addendum = {}, None, None
    human = human_answers(p)
    if (new_bm or dev_route) and p.judge is not None:
        d = ex_arb(p, cx, new_bm, dev_route, role_triggers, scan)
        ex, coerced = XA.coerce_ex_arb(d.fields, p.read_file)
        route = d.fields.get("developer_route") if dev_route else None
        addendum = d.fields.get("addendum")
        B.record_judgment(p, STAGE, "EX-ARB", ",".join(k for k, _c in new_bm) or "developer", d,
                          choice=",".join("%s:%s" % (k, (ex.get(k) or {}).get("verdict", "accept")) for k, _c in new_bm)
                          or (route or "-"), reason=d.fields.get("summary"),
                          extra={"coerced": "true"} if coerced else None)
    if dev_route is not None:
        if route == "reinvoke" and not cx.reinvoked:
            cx.reinvoked = True
            cx.reinvoke_addendum = "context the engine adds: %s" % (addendum or "(none given)")
            return "reinvoke"
        if route not in ("loop_back", "reinvoke"):
            return nh(p, cx, "developer %s for #%d — %s" % (dev_route[0], p.issue, dev_route[1] or ""),
                      "developer %s" % dev_route[0].lower())
    vcs = p.vcs
    arb = XA.arbitrate(rec, scan, scan_ran, unattended=p.unattended, attempt=attempt,
                       attempts_in_invocation=XA.attempts_in_invocation(rec, cx.stage_start) + (0 if local_pass else 1),
                       major_spent=cx.major_spent, role_triggers=role_triggers, evidence_reason=evidence_reason,
                       ex_arb=ex, unchanged=lambda pr, c: vcs.unchanged(pr.block.head, c.file),
                       untracked=untracked, ident=_ident(p), samecause=_samecause(p), human=human,
                       local_pass=local_pass)
    head = head or vcs.head()
    n = rec.next_n() if rec else 1
    block = arb.block(n, cx.stage_start, head, local_pass=cx.local_job if local_pass and arb.kind != "advance" else None,
                      scan_none=not scan_ran, loopback=cx.loopback_n)
    lint = AU.lint_block(block)
    if lint:
        raise B.StageError("audit block failed its own lint: %s" % lint[0])
    write_audit(p, block)
    for key, reason in arb.dismissed:
        B.record_code(p, STAGE, "dismissed", key, reason=reason)
    if cx.variant == "refactor" and cx.net_mode != "none":
        net_verify(p, cx, " ".join(r for _r, _v, r in role_triggers), scan if scan_ran else [])
    # captures at the decision (C-F-22)
    for key in arb.addressed:
        pr = prs.get(key)
        if pr and vcs.changed_since(pr.block.head, XA._path(pr.f.location)):
            p.capture("correction", STAGE, "auditor", "redo addressed auditor BLOCKER %s" % key,
                      "%s — %s" % (pr.f.location, pr.f.text), XA._path(pr.f.location), True)
    if arb.kind == "advance":
        return "advance"
    if arb.kind == "dispute":
        c, why = arb.disputed[0]
        q = ASK.Question("disputed-blocker", "auditor BLOCKER %s at %s is disputed: %s" % (c.fid, c.location, why),
                         [{"token": "dismiss", "label": "dismiss it"}, {"token": "fix", "label": "fix it"}], refs=c.fid)
        return nh(p, cx, "disputed auditor BLOCKER — %s %s: %s" % (c.fid, c.location, c.finding),
                  "disputed auditor BLOCKER", question=q,
                  prose="감사자 BLOCKER `%s` (%s): %s\n판단 측 이의: %s" % (c.fid, c.location, c.finding, why))
    if arb.kind == "ask-dismiss":
        c, why = arb.ask[0]
        q = ASK.Question("dismiss-blocker", "dismiss auditor BLOCKER %s at %s? (%s)" % (c.fid, c.location, why),
                         [{"token": "dismiss", "label": "dismiss"}, {"token": "fix", "label": "fix"}], refs=c.fid)
        return B.ask(p, STAGE, q, "dismiss auditor BLOCKER %s — %s" % (c.fid, why))
    if arb.kind == "stagnant":
        p.capture("stagnation", STAGE, "auditor" if not role_triggers and not evidence_reason else
                  (role_triggers[0][0] if role_triggers else "developer"), "stagnant loop-back",
                  arb.stagnant_reason, VR.CAPTURE_AREA[cx.variant], True)
        prose = None
        if TIMEOUT_RE.search(arb.stagnant_reason or ""):
            prose = "스위트가 상한 안에 끝나지 않습니다 — 세션 시작 전에 BASH_MAX_TIMEOUT_MS 를 늘리거나 스위트를 나누세요."
        return nh(p, cx, "same blocker recurred after loop-back — %s; retrying is unlikely to resolve it without a "
                  "different approach" % arb.stagnant_reason, "stagnant loop-back — %s" % B.one_line(arb.stagnant_reason, 120),
                  prose=prose)
    if arb.kind == "cap":
        line = B.one_line("; ".join(arb.reasons), 200)
        return nh(p, cx, "execute retries exhausted for #%d — %s" % (p.issue, line), line)
    # retry
    if arb.major_only:
        cx.major_spent = True
    for role, verdict, why in role_triggers:
        if verdict == "BLOCKED" and role != "developer":
            p.capture("correction", STAGE, role, "%s blocked the developer's work" % role, why,
                      VR.CAPTURE_AREA[cx.variant], True)
    cx.retry_reason = "attempt %d was sent back — %s" % (attempt, "; ".join(arb.reasons))
    if local_pass and cx.local_job:
        _ld(p, ["note", "--issue", str(p.issue), "--event", "not-green: %s" % B.one_line("; ".join(arb.reasons), 200)])
    return "retry"


def write_audit(p, block):
    p.writer.append_block(
        p.issue, AU.NAME, insert=lambda body: _insert(body, block), present=lambda body: block in body,
        new_comment=lambda: "\n".join([markers.open_tag(AU.NAME), block, markers.close_tag(AU.NAME)]),
        count=lambda body: len(AU.AuditRecord.parse(body).blocks))


def _insert(body, block):
    rec = AU.AuditRecord.parse(body)
    if not rec.doc.tail:
        raise ValueError("auditor record has no closing marker")
    rec.doc.insert(block)
    return rec.render()


def _ident(p):
    if p.judge is None:
        return None

    def ident(prior, cur):
        d = p.judge(JG.spec(p, "IDENT", [("prior", "%s — %s" % (prior.f.location, prior.f.text)),
                                         ("current", "%s — %s" % (cur.location, cur.finding))], STAGE, "X4"))
        return d.choice
    return ident


def _samecause(p):
    if p.judge is None:
        return None

    def same(a, b):
        return p.judge(JG.spec(p, "SAMECAUSE", [("prior", a), ("current", b)], STAGE, "X4")).choice
    return same


def ex_arb(p, cx, new_bm, dev_route, role_triggers, scan):
    mb = p.vcs.merge_base(p.base)
    findings = json.dumps([dict(c.as_dict(), id=k) for k, c in new_bm], ensure_ascii=False, indent=1)
    hunks = "\n".join("### %s\n%s" % (c.location, p.vcs.hunk(mb, c.file, c.line)) for _k, c in new_bm[:8]) if mb else ""
    parts = [("findings", findings), ("hunks", hunks),
             ("design", (p.read_file("docs/specs/%d/skeleton.md" % p.issue) or "")[:6000]),
             ("test_cases", (p.read_file("docs/specs/%d/test-cases.md" % p.issue) or "")[:6000]),
             ("roles", "\n".join("%s %s — %s" % t for t in role_triggers) or "none"),
             ("developer", "%s: %s" % dev_route if dev_route else "DONE")]
    model = "opus" if any(c.severity in ("BLOCKER", "MAJOR") for _k, c in new_bm) else None
    return p.judge(JG.spec(p, "EX-ARB", parts, STAGE, "X4", model=model, cwd=p.root))


def human_answers(p):
    """An applied person's answer to a disputed / dismiss-blocker question → {F<k>: dismiss|fix}."""
    out = {}
    for kind in ("disputed-blocker", "dismiss-blocker"):
        q, res = B.pending_answer(p, STAGE, kind)
        if q is None:
            continue
        fid = q.get("refs") or ""
        if re.match(r"^F\d+$", fid):
            out[fid] = res.get("choice")
            B.mark_applied(p, STAGE, res)
    return out


# ---- X5 / X6 PR + transition --------------------------------------------------------------------------

def pr_step(p, e, cx):
    push = getattr(p, "push_branch", None)
    if push is None or not getattr(p, "remote_url", None):
        return B.fail(p, STAGE, "no git remote — the PR step requires one; the work is committed on branch %s"
                      % p.branch, "defect")
    try:
        push()
    except PushProblem as pp:
        if pp.kind == "diverged":
            return nh(p, cx, "branch %s diverged from origin — resolve before the PR" % p.branch,
                      "branch diverged from origin")
        return B.fail(p, STAGE, pp.line, "defect" if pp.kind != "transient" else "transient")
    base_name = p.base[len("origin/"):] if p.base.startswith("origin/") else p.base
    pr_base, base_note = base_name, None
    rh = getattr(p, "remote_has_branch", None)
    if rh is not None:
        has = rh(base_name)
        if has is False:
            pr_base = getattr(p, "default_branch", None) or base_name
            base_note = "base `%s` 가 원격에 없어 기본 브랜치 `%s` 로 열었습니다" % (base_name, pr_base)
    sections = pr_sections(p, cx)
    issue = p.gh.issue(p.issue)
    hits = p.gh.pr_for_head(p.branch)
    if hits:
        prn = int(hits[0]["number"])
        try:
            for name, blk in sections:
                if blk is None:
                    p.writer.pr_body_edit(prn, lambda body, n=name: _drop(body, n))
                else:
                    p.writer.pr_body_splice(prn, name, blk)
        except ValueError:
            return B.pause(p, STAGE, "env", "PR body unreadable", "PR body unreadable", env_key="other")
    else:
        body = pr_body(p, cx, sections, base_note)
        title = "%s: %s" % ({"implement": "feat", "debug": "fix", "refactor": "refactor"}[cx.variant],
                            issue.get("title") or "#%d" % p.issue)
        res = p.writer.pr_create(p.branch, pr_base, title, body, draft=bool(getattr(p, "draft", False)))
        prn = res["number"]
    if p.unattended:
        UL.splice(p.writer, p.gh, p.issue, prn)
    if cx.loopback is not None:                                                 # X6 (P6.2)
        r = consume(p, cx)
        if r is not None:
            return r
    B.transition(p, e, "test")
    return B.StageResult(B.StageResult.ADVANCE, nxt="test")


class PushProblem(Exception):
    def __init__(self, kind, line):
        Exception.__init__(self, line)
        self.kind, self.line = kind, line


def _drop(body, name):
    try:
        s = markers.marker_span(body, name)
    except ValueError:
        raise
    if s is None:
        return body
    a, b = s
    return (body[:a].rstrip("\n") + "\n" + body[b:].lstrip("\n")) if a else body[b:].lstrip("\n")


def pr_sections(p, cx):
    """[(marker name, block or None to remove)] in the spine's order."""
    rec = AU.from_comments(B.records(p))
    out = [("auditor:pr", XA.pr_section(rec, p.language))]
    if cx.ledger is not None:
        rows, _run = cx.ledger
        out.append(("visual-changes", visual_section(rows, cfg_dict(p)) if rows else None))
    mb = p.vcs.merge_base(p.base)
    cen = p.vcs.central_owned(mb)
    if cen is None:
        out.append(("central-owned", "\n".join([markers.open_tag("central-owned"),
                                                 "중앙 관리 파일 점검 불가(merge-base 없음)", markers.close_tag("central-owned")])))
    elif cen:
        out.append(("central-owned", "\n".join([markers.open_tag("central-owned"), "### 중앙 관리 파일 변경"] +
                                                ["- `%s` — `/gld update` 가 덮어쓰는 파일입니다. 플러그인 쪽으로 옮기세요." % c
                                                 for c in cen] + [markers.close_tag("central-owned")])))
    stack = getattr(p, "stack", None)
    if stack and (stack.get("base") or getattr(p, "draft", False)):
        out.append(("sprint:stack", "\n".join([markers.open_tag("sprint:stack"),
                                               "스프린트 #%s 의 스택 %s/%s — 아래 PR #%s 위에 쌓였습니다." % (
                                                   stack.get("tracker"), stack.get("position"), stack.get("depth"),
                                                   stack.get("lower_pr")), markers.close_tag("sprint:stack")])))
    return out


VIS_TPL = {"C": "비교 설정 변경 — %s", "M": "기준 이미지 갱신 — %s", "D": "기준 이미지 삭제 — %s",
           "A": "새 기준 이미지 — %s", "R": "이동(변경 없음) — %s", "P": "재생성 필요 — %s"}


def visual_section(rows, cfg):
    order = {"C": 0, "M": 1, "D": 1, "A": 3, "R": 4, "P": 5}
    lines = [markers.open_tag("visual-changes"), "### 시각 변경"]
    for c, path, r in sorted(rows, key=lambda x: (order.get(x[0], 9) if not (x[0] == "A" and "replaces" in (x[2] or ""))
                                                   else 2, x[1])):
        lines.append("- %s `%s`%s" % (VIS_TPL.get(c, "%s") % "", markers.value(path), (" — " + markers.value(r)) if r else ""))
    lines.append(markers.close_tag("visual-changes"))
    return "\n".join(lines)


def pr_body(p, cx, sections, base_note):
    summ = ""
    sp = getattr(cx, "pr_summary_path", None)
    if sp and os.path.exists(sp):
        with open(sp, encoding="utf-8", errors="replace") as fh:
            summ = fh.read().strip()
    lines = ["Closes #%d" % p.issue, "", VR.SUMMARY_HEAD[cx.variant], markers.neutralize(summ) or "(developer summary missing)"]
    if base_note:
        lines += ["", base_note]
    if cx.dwc:
        lines += ["", "## 리뷰 우려 (DONE_WITH_CONCERNS)"] + ["- %s" % markers.value(x) for x in cx.dwc]
    body = "\n".join(lines)
    for name, blk in sections:
        if blk:
            body += "\n\n" + blk
    return body + "\n"


def consume(p, cx):
    """P6.2 / D-6.2: the latest active block without `consumed:` whose `at:` ≤ stage-start gets
    `consumed: <ts>`; verified by re-read, one retry (GhWriter), else NH `defect:`."""
    comments = B.records(p)
    lb = LB.from_comments(comments)
    if lb is None or not lb.not_yet_handled():
        return None
    blk = lb.latest_active()
    if (blk.get("at") or "") > cx.stage_start:
        return None
    ts = p.now()
    heading = markers.clean(blk.heading)

    def ins(body):
        rec = LB.LoopbackRecord.parse(body)
        for b in rec.blocks:
            if markers.clean(b.heading) == heading and not b.has("consumed"):
                b.lines.append("consumed: %s" % ts)
        return rec.render()

    def present(body):
        rec = LB.LoopbackRecord.parse(body)
        return any(markers.clean(b.heading) == heading and b.has("consumed") for b in rec.blocks)
    from guildcore.adapters.gh import GhWriteError
    try:
        p.writer.append_block(p.issue, LB.NAME, insert=ins, present=present,
                              count=lambda body: len(LB.LoopbackRecord.parse(body).numbered()))
    except GhWriteError as e:
        if e.kind == "auth":
            raise
        return nh(p, cx, "loop-back record for #%d could not be marked handled" % p.issue, "loop-back record not updated")
    return None


# ---- needs-human -----------------------------------------------------------------------------------------

def nh(p, cx, attended_line, pause_text, kind="defect", unstage=True, prose="", question=None, ask_kind="escalation",
       token=None):
    """The standard NH emission: unstage the 1L staged tests first (D-1.6), then attended ask /
    unattended pause."""
    if unstage and cx is not None and cx.ran_1l and getattr(p, "vcs", None) is not None:
        staged = p.vcs.staged(cx.staged_tests) if cx.staged_tests else []
        if staged:
            p.vcs.unstage(staged)
            prose = (prose + "\n" if prose else "") + "unstaged, not committed: %s" % ", ".join(staged)
    if not p.unattended:
        q = question or ASK.Question(ask_kind or "escalation", attended_line,
                                     [{"token": "continue", "label": "continue"}, {"token": "stop", "label": "stop"}])
        return B.ask(p, STAGE, q, attended_line)
    return B.pause(p, STAGE, kind, pause_text, token or pause_text, prose=prose, question=question)
