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
from workflows.dev import conservative as CONS
from workflows.dev import exec_audit as XA
from workflows.dev import firstsprint as FS
from workflows.dev import judging as JG
from workflows.dev import predict as PF
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
SECURITY_WORDS = frozenset(("auth", "oauth", "session", "sessions", "token", "tokens", "secret", "secrets",
                            "password", "passwords", "permission", "permissions", "credential", "credentials",
                            "jwt", "apikey", "login", "signin"))


def security_hit(text):
    """K3r1-m9: whole identifier words only (`fooSession`, `auth_token`, `api-key` split), never a
    substring (`authorName`, `tokenizer`)."""
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", text or ""):
        for part in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", word):
            if part.lower() in SECURITY_WORDS:
                return True
    return False
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
        self.issue_text = None            # K5: the Issue text through the three-valued trust read
        self.local_job = None
        self.major_spent = False
        self.reinvoked = False
        self.stagnant_retried = False     # 0.102.5: the one automatic re-invoke after a recurring blocker
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
    p._xcx = cx
    cx.stage_start = getattr(p, "stage_start", None) or p.now()
    from guildcore.records import redact as RD
    RD.clear_exact()                      # K3r1-M4: exact values of copy_ignored files, scoped to this run
    if copy_ignored_list(p) and p.root:
        RD.register_exact_from_files(p.root, copy_ignored_list(p))
    comments = B.records(p)
    B.note_untrusted(p, STAGE)
    from workflows.dev.stages import analyze as A
    try:                                                                        # K5 (K4r2-m10): P2 three-valued
        cx.issue_text = B.issue_text(p, p.gh.issue(p.issue))
    except A.TrustUnknown as ex:
        return A.unknown_trust_result(p, STAGE, ex)
    nc = VR.design_input(p, variant, comments)                                  # P0.2
    if nc:
        return B.StageResult(B.StageResult.FAIL, line=nc, fail_class="needs_context")
    bad = [v for v in AU.violations(comments) if not v.resolved]               # P0.9
    if bad:
        ref = "comment %s" % bad[-1].comment_id
        return nh(p, cx, "#%d's branch still carries unreviewed auditor changes — revert them, then append the "
                  "resolved marker to the auditor-violation note (%s)" % (p.issue, ref),
                  "unresolved auditor violation", unstage=False)
    legacy_unreadable(p, comments)
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
            # K4r3-m2: the safety-net marker is a member's control (P2, three-valued like analyze): an
            # outsider's marker is ignored (analyze gave it no net AC); unknown trust stops the stage
            from workflows.dev.stages import analyze as A
            try:
                if not A.trusted_body(p, issue)[0]:
                    cx.net_mode = "none"
            except A.TrustUnknown as ex:
                return A.unknown_trust_result(p, STAGE, ex)
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
    restore_invocation_state(p, cx)                                             # m4
    if getattr(cx, "resume_note", None):
        retry_note, cx.resume_note = cx.resume_note, None                       # 0.102.6 m4: the retry's hint
    while True:
        dev, local_pass = developer_step(p, cx, attempt, retry_note)            # X1
        if isinstance(dev, B.StageResult):
            return dev
        if dev.status == "FAIL":
            return B.fail(p, STAGE, "developer FAIL — %s" % (dev.line or ""), "defect")
        m = INV2_RE.match(dev.line or "") if dev.status == "BLOCKED" else None
        if m:
            return gate_inv2(p, cx, m.group(1), m.group(2))
        x = dev.extras or {}
        cx.dev_tests = list(x.get("tests") or []) + list(x.get("impl_files") or [])        # m6
        cx.impl_files = list(x.get("impl_files") or [])
        ev = evidence_step(p, cx, dev, attempt)                                 # X2
        if isinstance(ev, B.StageResult):
            return ev
        green, reason = ev
        dev_ok = dev.status in ("DONE", "DONE_WITH_CONCERNS")
        role_triggers, scan, scan_ran, mb, head, untracked = [], [], False, None, None, ()
        dwc_now = []                                                            # m13: per attempt
        reviewed = {"tech-lead": False, "auditor": False}
        dev_route = None
        if not dev_ok and not TIMEOUT_RE.search(dev.line or ""):
            dev_route = (dev.status, dev.line)
            role_triggers.append(("developer", dev.status, dev.line or ""))     # K3r1-B2: never advances
        if green and dev_ok:
            tl = conformance_step(p, cx, attempt)                               # X3
            if isinstance(tl, B.StageResult):
                return tl
            reviewed["tech-lead"] = True
            if tl.status == "FAIL":
                return B.fail(p, STAGE, "tech-lead FAIL — %s" % (tl.line or ""), "defect")
            if tl.status == "BLOCKED":
                role_triggers.append(("tech-lead", "BLOCKED", tl.line or ""))
            elif tl.status == "DONE_WITH_CONCERNS":
                dwc_now.append(("tech-lead", tl.line or ""))
            au = auditor_step(p, cx, attempt)                                   # X3.5a
            if isinstance(au, B.StageResult):
                return au
            scan, mb, head, untracked = au
            scan_ran = reviewed["auditor"] = True
            for role, res in gates_step(p, cx, attempt, mb):                    # X3.5b
                if isinstance(res, B.StageResult):
                    return res
                if res.status == "FAIL":
                    return B.fail(p, STAGE, "%s FAIL — %s" % (role, res.line or ""), "defect")
                if res.status == "BLOCKED":
                    role_triggers.append((role, "BLOCKED", res.line or ""))
                elif res.status == "DONE_WITH_CONCERNS":
                    dwc_now.append((role, res.line or ""))
        if dev.status == "DONE_WITH_CONCERNS":
            dwc_now.insert(0, ("developer", dev.line or ""))
        if getattr(cx, "evidence_concern", None):
            dwc_now.append(("developer", cx.evidence_concern))
            cx.evidence_concern = None
        cx.dwc_pending = list(dwc_now) if (green and dev_ok and not role_triggers) else []
        cx.dwc = ["%s: %s" % (r, t) for r, t in dwc_now]
        cx.pr_summary_path = safe_role_path(p, dev, (dev.extras or {}).get("pr_summary_path"))   # K3r1-B1
        out = arbitrate_step(p, cx, attempt, scan, scan_ran, head, untracked, role_triggers,
                             None if green else reason, local_pass, dev_route, record0)   # X4
        if isinstance(out, B.StageResult):
            return out
        if out == "advance":
            # K3r1-B2 invariant: no PR / advance unless the developer is done, the engine's suite is
            # green and the tech-lead AND the auditor ran on this attempt
            if not (dev_ok and green and reviewed["tech-lead"] and reviewed["auditor"]):
                raise B.StageError("advance without review (dev=%s green=%s reviewed=%s)" % (dev.status, green, reviewed))
            return pr_step(p, e, cx)                                            # X5–X6
        if out == "reinvoke":
            retry_note = cx.reinvoke_addendum
            continue
        if not local_pass:
            attempt += 1
        retry_note = cx.retry_reason


def safe_role_path(p, res, rel):
    """P1: a role-supplied path is read only when it is relative, has no `..`, is no symlink on the
    way, and its realpath is inside that role run's `out/`. Anything else → None + decision log."""
    rd = getattr(res, "run_dir", None)
    if not rel:
        return None
    bad = None
    norm = os.path.normpath(rel)
    if os.path.isabs(rel) or norm.startswith("..") or not rd:
        bad = "not a relative path inside the role's out/"
    else:
        out_dir = os.path.realpath(os.path.join(rd, "out"))
        cand = os.path.join(rd, "out", norm[4:] if norm.startswith("out" + os.sep) else norm)
        cur = os.path.join(rd, "out")
        for part in os.path.relpath(cand, os.path.join(rd, "out")).split(os.sep):
            cur = os.path.join(cur, part)
            if os.path.islink(cur):
                bad = "symlink"
                break
        if not bad and not (os.path.realpath(cand).startswith(out_dir + os.sep) and os.path.isfile(cand)):
            bad = "outside the role's out/ or missing"
        if not bad:
            return cand
    B.record_code(p, STAGE, "role-path-refused", "refused", reason="pr_summary_path %s — %s" % (
        markers.value(str(rel))[:200], bad))
    return None


def dwc_judgment(p, cx, attempt, dwc_now):
    """User decision (K3r1 Q1): concerns go to a short SJ call — loop back or proceed. Concerns only
    cost when they exist; unsure → proceed (the concern stays on the PR)."""
    if p.judge is None:
        return []
    from guildcore.records import redact as RD
    parts = [("concerns", "\n".join("%s: %s" % (r, RD.redact(t)) for r, t in dwc_now)),
             ("issue", B.title_text(p, p.gh.issue(p.issue))),            # K5r1-m1: trust-marked title
             ("test_cases", (p.read_file("docs/specs/%d/test-cases.md" % p.issue) or "")[:6000])]
    d = p.judge(JG.spec(p, "EX-DWC", parts, STAGE, "X4"))
    B.record_judgment(p, STAGE, "EX-DWC", ",".join(r for r, _t in dwc_now), d, reason=d.fields.get("reason"))
    if d.choice != "loop_back":
        return []
    return [(r, "DWC", t) for r, t in dwc_now]


def restore_invocation_state(p, cx):
    """K3r1-m4: the MAJOR budget and the one reinvoke are restored from the record of THIS invocation
    (a crash inside the invocation must not hand them out again)."""
    rec = AU.from_comments(B.records(p))
    for b in (rec.blocks if rec else []):
        if b.invocation != cx.stage_start or b.local_pass:
            continue
        lb = [f for f in b.findings if f.token == "looped-back"]
        if lb and all(f.severity == "MAJOR" for f in lb) and not b.role_axis:
            cx.major_spent = True
        if b.role_axis and all(XA._is_dwc(x) for x in b.role_axis) and not lb:
            cx.major_spent = True                                   # K3r3-m5: a DWC loop-back spent it too
    from guildcore.decisions import DecisionLog
    for blk in DecisionLog.load(B.records(p)).blocks:
        if blk.get("stage") == STAGE and blk.get("point") == "reinvoke" and blk.get("refs") == cx.stage_start:
            cx.reinvoked = True
        if blk.get("stage") == STAGE and blk.get("point") == "stagnant-retry" and blk.get("refs") == cx.stage_start:
            cx.stagnant_retried = True                           # 0.102.5: once per invocation, crash-safe
            # 0.102.6 m4: the retry's hint is rebuilt from its block — the next developer call of this invocation
            # (the resumed retry) gets it again
            cause = blk.get("cause") or blk.get("reason") or ""
            cx.resume_note = stagnant_hint(cause, [x for x in (blk.get("details") or "").split(" ;; ") if x])


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
    text = getattr(cx, "issue_text", None)
    if text is None:                    # entered without the stage's trust read (a direct helper call) → read it now
        text = B.issue_text(p, issue)
    ins = {"issue.md": text.rstrip("\n") + "\n",
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
        if isinstance(r, B.StageResult):
            return r, False
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
            ok, line = p.commit_local(st.get("files") or [], cx.staged_tests, cx.variant)
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
    dep_reason = None
    if deps is not None:                                                    # K3 carry-over 3
        cx.pre_deps_status = p.vcs.status()                                  # K3r2-m5: before pub get rewrites a lock
        d = deps()
        if d is not None and not d.passed:
            tail = CH.redact_lines("\n".join((d.raw or "").split("\n")[-4:]))
            kind = deps_failure_kind(p, d)
            if kind == "env":
                return B.build_inputs_changed(["(dependency step: registry unreachable or base fails)"], "execute",
                                              None, tail)
            dep_reason = "dependency step failed — %s" % B.one_line(tail, 240)     # K3r1-M3: the Issue's
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
        return env_pause(p, "테스트 요약 형식을 읽지 못함 — commands.test_summary 를 설정하세요",
                         "테스트 요약 형식을 읽지 못함", "X2.3")
    else:
        green = bool(r.passed and summ.green)
        flake = getattr(r, "flake", None)
        from workflows.dev import flake as FL
        if not green and flake and flake.get("green") and not FL.off(p):
            # 0.102.5: ≤ 2 failing tests passed when re-run alone in the same tree and (0.102.6) the whole suite
            # re-ran green — green, with a flake note (a grading-sheet row)
            FL.record(p, STAGE, flake)
            green, cx.flake_line = True, FL.line(flake)
        if not green:
            reason = ("suite red — %d failed" % summ.failed) if copy_ignored_list(p) else \
                "suite red — %s" % (r.red_line() or ("failed: %s" % ", ".join(summ.failed_names[:3])
                                                      if summ.failed_names else "failed"))
    if dep_reason:
        green, reason = False, dep_reason
    claimed = dev.status in ("DONE", "DONE_WITH_CONCERNS")
    if claimed and not green and not r.timed_out:                           # J-E1 verify gap
        p.capture("verify-gap", STAGE, "developer", "developer reported done; the engine's run is red",
                  CH.redact_lines(r.red_line() or ""), VR.CAPTURE_AREA[cx.variant], True)
    if dev.status in ("BLOCKED", "NEEDS_CONTEXT") and green:
        # K3r1-B2: the engine's green never overrides a developer BLOCKED — a reported timeout is an
        # evidence failure on the verify axis (stagnation compares timeouts), the rest goes to EX-ARB
        green = False
        reason = dev.line if TIMEOUT_RE.search(dev.line or "") else None
    rows, run, notes = [], False, []
    if getattr(cx, "flake_line", None):
        notes.append(cx.flake_line)
        cx.flake_line = None
    if V.ledger_expected(cfg_dict(p)):
        ev = markers.find(B.records(p), EVIDENCE)
        prev = VC.parse_ledger(V.block_text(markers.body_of(ev))) if ev else []
        rows, run, notes = VC.visual_rows(p.vcs, p.base, cfg_dict(p), VC.declared((dev.extras or {}).get("baselines")), prev)
        cases = re.findall(r"\b(V\d+|VC-?\d+)\b", (p.read_file("docs/specs/%d/test-cases.md" % p.issue) or ""))
        und = VC.undeclared(rows, cases)
        if green and und:
            green, reason = False, "undeclared visual change: %s" % ", ".join(und)
            # 0.102.4: a declaration the engine cannot read is named, with the format, so the retry can fix it
            bad = [x for x in ((dev.extras or {}).get("baselines") or [])
                   if (x or "").strip().lower() != "none" and not VC.DECL_RE.match((x or "").strip())]
            if bad:
                reason += " — unreadable baselines line(s) %s; write `<A|M|D|C|P|P-withdrawn> <path> — <reason>`" % \
                    ", ".join(bad)[:300]
        cx.ledger = (rows, run)
    if green:
        met, why, concern = VR.evidence_rule(cx.variant, green, dict(dev.extras or {}, dwc=dev.line if
                                             dev.status == "DONE_WITH_CONCERNS" else ""),
                                             ["%s %s%s" % (c, pth, (" — " + rr) if rr else "") for c, pth, rr in rows],
                                             getattr(cx, "red", None))
        if not met:
            green, reason = False, why
        cx.evidence_concern = concern
    net_block = None
    if cx.variant == "refactor" and cx.net_mode != "none":
        nb = net_from_result(p, cx, dev)
        net_block = RN.render_block(nb)
        cx.net_now = nb
        if green:
            green, reason = engine_net_run(p, cx, dev, nb)                      # K3r2-M3 (P2)
            net_block = RN.render_block(nb)
        if green:
            # K3r1-m12: a VERIFIED net is frozen — its D-R checks still run on every re-entry
            bad = RN.checks(p.root, p.base, p.branch, nb, net_mode=cx.net_mode)
            if bad:
                verified = (cx.net_prev or {}).get("verified") == "yes"
                green, reason = False, ("the verified safety net changed — %s" if verified
                                        else "re-prove the net — %s") % bad[0]
    write_evidence(p, cx, dev, r, summ, green, reason, rows, run, notes, net_block)
    return green, reason


MANIFESTS = ("pubspec.yaml", "pubspec.lock", "package.json", "package-lock.json", "yarn.lock",
             "pubspec_overrides.yaml")


def deps_failure_kind(p, d):
    """K3r1-M3: `env` (sprint-wide halt) only when the registry is unreachable or <base> itself fails
    (the Issue did not touch a manifest); a failing resolution on manifests the branch changed is the
    developer's mistake → a loop-back for this Issue."""
    mb = p.vcs.merge_base(p.base)
    pre = getattr(getattr(p, "_xcx", None), "pre_deps_status", None)
    changed = set(p.vcs.names("%s..HEAD" % mb) if mb else []) | set(
        ln[3:] for ln in ((pre if pre is not None else p.vcs.status()) or "").split("\n") if len(ln) > 3)
    if any(os.path.basename(f) in MANIFESTS for f in changed):
        return "issue"          # even a host the proxy refused: the branch asked for it (a retry that
    return "env"                # still fails goes to stagnation → a person, never a sprint-wide halt)


SNAP_WRITTEN_RE = re.compile(r"\b(\d+ )?snapshots? (written|updated)\b|Writing golden|updated golden", re.I)


def _head_path(p, sha, f):
    if p.vcs.show("HEAD", f) is not None:
        return f
    for st, paths in p.vcs.name_status("%s..HEAD" % sha, renames=True) if hasattr(p.vcs, "name_status") else []:
        if st.startswith("R") and paths[0] == f:
            return paths[-1]
    return None


def engine_net_run(p, cx, dev, nb):
    """K3r2-M3: the net's `run:` lines are the ENGINE's — at the proof (old code + net) and at HEAD.
    The developer's `net_run` text only feeds the mismatch log. Not runnable → `unverified(net)`, and
    `verified: yes` is never written. Returns (green, reason)."""
    nr = getattr(p, "net_run", None)
    files = [f for f in nb.get("net") or [] if f not in [x.split(" @ ")[0] for x in nb.get("post-transform-net") or []]]
    sha = nb.get("sha")
    claim = " ".join((dev.extras or {}).get("net_run") or [])
    cx.net_engine = "unverified(net)"
    if not files or not sha or nr is None:
        why = "no net files" if not files else "no sha" if not sha else "engine cannot run the net here"
        nb["run"] = ["unverified(net): %s" % why]
        net_unverified(p, why)
        return True, None
    old = nr(sha, files)
    if old is None or getattr(old, "env", None):
        why = "no per-file command for this runner" if old is None else "env — %s" % old.env
        nb["run"] = ["unverified(net: %s)" % why]
        net_unverified(p, why)
        return True, None
    red_old = not old.passed or SNAP_WRITTEN_RE.search(old.raw or "")
    heads = [_head_path(p, sha, f) for f in files]
    new = nr("HEAD", [h for h in heads if h]) if all(heads) else None
    nb["run"] = ["engine@%s: %s — %s" % (sha[:12], " ".join(files), "green" if not red_old else "RED"),
                 "engine@HEAD: %s — %s" % (" ".join(h for h in heads if h),
                                          "unrunnable" if new is None else ("green" if new.passed else "RED"))]
    if claim and red_old and "fail" not in claim.lower():
        B.record_code(p, STAGE, "net-claim-mismatch", "mismatch", reason="developer net_run claims green; the engine's "
                      "run at the proof is red")
    if red_old:
        return False, "the safety net is red (or wrote a snapshot) on the unchanged code — engine run at %s" % sha[:12]
    if new is not None and getattr(new, "env", None):
        nb["run"][-1] = "engine@HEAD: unverified(net: env — %s)" % new.env
        net_unverified(p, "env at HEAD — %s" % new.env)
        return True, None
    if new is None or not new.passed:
        return False, "the safety net does not pass at HEAD (engine run)"
    cx.net_engine = "ok"
    return True, None


CC_TYPES = ("feat", "fix", "refactor", "perf", "docs", "test", "tests", "chore", "build", "ci", "style", "revert")
# `fix: …`, `feat(kanji): …`, `refactor!: …` — a Conventional Commits type (any case), never any `Word: …`
# 0.102.8 (review-0102-7 m4): with or without the space after the colon, and the full-width colon (`fix:x`, `fix：…`)
CC_PREFIX_RE = re.compile(r"^\s*(?:%s)(?:\([^)]*\))?!?\s*[:：](?!//)" % "|".join(CC_TYPES), re.I)
PR_TYPE = {"implement": "feat", "debug": "fix", "refactor": "refactor"}


def pr_title(variant, issue_title):
    """0.102.7 (review-0102-6 m3): the PR title — the variant's conventional type before the Issue title, unless the
    Issue title already opens with a conventional-commit prefix (`type:` / `type(scope):` / `type!:`): then the Issue
    title as it is (never `fix: fix: …` — word_app PR #1963)."""
    t = " ".join(str(issue_title or "").split())
    if CC_PREFIX_RE.match(t):
        return t
    return "%s: %s" % (PR_TYPE[variant], t)


def net_unverified(p, why):
    """K3r3-m3: like K2's `unverified` — the outcome stands, the person grades it (§9.5 trigger), and the
    C14 unattended log says so."""
    B.record_code(p, STAGE, "net-unverified", "unverified(net)", reason=why, extra={"grade": "trigger"})


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
    copy_list = copy_ignored_list(p)
    if copy_list:
        # K3r1-M4 (= K2r3-M2): with copy_ignored the raw tail is never posted — a structured summary
        from workflows.dev.stages import test as T
        lines += R.raw_block(T.structured_summary(r, summ, summ.runner if summ else None))
    else:
        lines += R.raw_block(r.raw)
    lines.append("판정: %s%s" % ("green" if green else "not green", (" — " + markers.value(reason)) if reason else ""))
    red = (dev.extras or {}).get("red") or getattr(cx, "red", None)
    if red and copy_list:
        lines += ["", "**재현(red, 수정 전)**: %d줄 (copy_ignored 실행 — 원문 비게시)" % len(red)]
    elif red:
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


def copy_ignored_list(p):
    return ((cfg_dict(p).get("engine") or {}).get("effective") or {}).get("copy_ignored") or []


def net_verify(p, cx, tl_line, findings):
    """P4.11 / J-R2 (code): `verified: yes` iff the checks passed and neither the tech-lead nor the
    auditor named a net file."""
    nb = getattr(cx, "net_now", None)
    if not nb or getattr(cx, "net_engine", None) != "ok":       # K3r2-M3: never `verified: yes` unobserved
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
        if res.status in ("DONE", "DONE_WITH_CONCERNS"):
            # 0.102.7 (word_app #1797): the findings are what counts — schema-checked by the runner from out/result.json
            # or, when the role could not write it, its ```guild-result``` block (`roles.result`).
            found = XA.parse_auditor_reply(json.dumps((res.extras or {}).get("findings")))
            if found is not None and res.status != "DONE":
                # 0.102.8 (review-0102-7 M3, lead decision 2): a DONE_WITH_CONCERNS is a clean audit ONLY when its
                # concern is the result-file write failure — the runner saw the role's Write/Edit of out/result.json
                # refused AND the findings came from the role's own guild-result fence. Any other concern (a partial
                # read, …) is no clean audit: the auditor is dispatched once more, then a person
                why = result_write_failed(res)
                if why:
                    B.record_code(p, STAGE, "auditor-result", "accepted", reason=B.one_line(
                        "auditor %s with schema-valid findings from its guild-result block — %s (%s)" % (
                            res.status, why, res.line or "-"), 300))
                else:
                    B.record_code(p, STAGE, "auditor-result", "redispatch" if shot == 1 else "refused",
                                  reason=B.one_line("auditor %s — the concern is not the result-file write: %s" % (
                                      res.status, res.line or "-"), 300))
                    found = None
                    if shot == 2:
                        return nh(p, cx, "execute-stage auditor returned DONE_WITH_CONCERNS twice for #%d — %s" % (
                            p.issue, B.one_line(res.line or "-", 200)), "auditor scan concern")
        if found is not None:
            return found, mb, before["head"], set(before["untracked"])
        if shot == 2:
            return nh(p, cx, "execute-stage auditor returned no usable findings for #%d" % p.issue, "auditor scan failed")
    return None


def result_write_failed(res):
    """0.102.8: the reason a DONE_WITH_CONCERNS auditor is still a clean audit — or None. Both must hold: the findings
    were read from the role's own ```guild-result``` fence (`RoleResult.result_source == "fence"`, never a file) and
    the stream shows a refused Write/Edit of its run dir's `out/result.json` (`RoleResult.denials`)."""
    if getattr(res, "result_source", None) != "fence":
        return None
    for d in getattr(res, "denials", None) or []:
        tool = str(d.get("tool") or d.get("class") or "")
        path = str(d.get("path") or d.get("command") or "").replace("\\", "/")
        if ("Write" in tool or "Edit" in tool) and path.endswith("out/result.json"):
            return "Write of out/result.json refused"
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
    if any(security_hit(n) for n in residue) or security_hit(added or ""):
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
        asked = set(k for k, _c in new_bm)
        for k in sorted(set(ex) - asked):                           # K3r1-M5: only what was asked
            B.record_code(p, STAGE, "ignored_verdict", (ex[k] or {}).get("verdict"), refs=str(k)[:20],
                          reason="EX-ARB judged an id it was not asked about")
        ex = {k: v for k, v in ex.items() if k in asked}
        route = d.fields.get("developer_route") if dev_route else None
        addendum = d.fields.get("addendum")
        # 0.102.7 (review-0102-6 M1): a security concern (the judge's `security_concern` not false, the security role
        # among the triggers, an issue phrase in the findings) is never dismissed without a person: a BLOCKER's
        # dismiss/dispute is a dispute (a person decides it), a MAJOR's is accepted (fixed, never dropped unasked).
        # 0.102.8 (review-0102-7 m3): read BEFORE the §10.4 / unverified coercion below (which turned every dismiss
        # into accept first, so the rule never fired on a real run) and per finding — only the findings the judge marks
        # `security` (unmarked = security), or whose own text names a security issue; the other BLOCKERs of the batch
        # follow the coercion as before
        sec = []
        sec_on = CONS.security(getattr(cx, "ex_arb_spec", None), d, "EX-ARB")
        if sec_on:
            marks = dict((str(f.get("id")), f.get("security")) for f in d.fields.get("findings") or []
                         if isinstance(f, dict))
            for k, c in new_bm:
                if (ex.get(k) or {}).get("verdict") not in ("dismiss", "dispute"):
                    continue
                if marks.get(str(k)) is False and not CONS.security_text(
                        " ".join(str(x or "") for x in (getattr(c, "finding", ""), getattr(c, "why", "")))):
                    continue
                sec.append(k)
                ex[k] = {"verdict": "dispute" if c.severity == "BLOCKER" else "accept", "security": True,
                         "reason": "security concern — a person decides (%s)" % (ex[k].get("reason") or "-")}
        if sec_on and route in ("reinvoke", "loop_back"):
            # 0.102.8 (review-0102-7 M2): the judge's own route for a BLOCKED / NEEDS_CONTEXT developer under a security
            # concern (re-invoke with its addendum, loop back) is a person's decision, never run unasked
            B.record_code(p, STAGE, "developer-route", "human", refs=cx.stage_start,
                          reason=B.one_line("EX-ARB chose %s under a security concern (%s)" % (
                              route, CONS.security_why(getattr(cx, "ex_arb_spec", None), d, "EX-ARB")), 300))
            cx.route_security = CONS.security_why(getattr(cx, "ex_arb_spec", None), d, "EX-ARB")
            route = "human"
        # §10.4: unattended, a BLOCKER/MAJOR dismiss/dispute is forced to accept in the first sprint (and after the
        # go while the `exarb.no_unattended_dismiss` valve holds) — the judge's own pick stays as `would-dismiss`
        would = []
        why = FS.no_dismiss(p, attended=not p.unattended)
        if why:
            for k, _c in new_bm:
                if k in sec:
                    continue                                    # a security finding stays with a person
                if (ex.get(k) or {}).get("verdict") in ("dismiss", "dispute"):
                    would.append(k)
                    # K6 r1 M6: the conservative source is named as the person can act on it (a valve or the
                    # §10.2-6 unverified state — never a valve that is not set)
                    ex[k] = {"verdict": "accept", "reason": "%s (would-dismiss: %s)" % (
                        {"first-sprint": "first-sprint",
                         "conservative": PF.conservative_label(p, "EX-ARB:dismiss")}.get(
                            why, "exarb.no_unattended_dismiss"),
                        ex[k].get("reason") or "")}
        extra = {"coerced": "true"} if coerced else {}
        if sec:
            extra.update(coerced="true", security="; ".join(sec))
        if would:
            extra.update(coerced="true", coerced_by=why, raw_choice=",".join(
                "%s:%s" % (k, "would-dismiss" if k in would else (ex.get(k) or {}).get("verdict", "accept"))
                for k, _c in new_bm))
        B.record_judgment(p, STAGE, "EX-ARB", ",".join(k for k, _c in new_bm) or "developer", d,
                          choice=",".join("%s:%s" % (k, (ex.get(k) or {}).get("verdict", "accept")) for k, _c in new_bm)
                          or (route or "-"), reason=d.fields.get("summary"), extra=extra or None)
    if dev_route is not None:
        if route == "reinvoke" and not cx.reinvoked:
            cx.reinvoked = True
            B.record_code(p, STAGE, "reinvoke", "developer", refs=cx.stage_start)
            cx.reinvoke_addendum = "context the engine adds: %s" % (addendum or "(none given)")
            return "reinvoke"
        if route not in ("loop_back", "reinvoke"):
            sw = getattr(cx, "route_security", None)
            return nh(p, cx, "developer %s for #%d — %s%s" % (dev_route[0], p.issue, dev_route[1] or "",
                                                             (" (보안: %s)" % sw) if sw else ""),
                      "developer %s%s" % (dev_route[0].lower(), (" (보안: %s)" % B.one_line(sw, 100)) if sw else ""))
    vcs = p.vcs
    n_att = XA.attempts_in_invocation(rec, cx.stage_start) + (0 if local_pass else 1)

    def decide(triggers):
        return XA.arbitrate(rec, scan, scan_ran, unattended=p.unattended, attempt=attempt,
                            attempts_in_invocation=n_att, major_spent=cx.major_spent, role_triggers=triggers,
                            evidence_reason=evidence_reason, ex_arb=ex,
                            unchanged=lambda pr, c: vcs.unchanged(pr.block.head, c.file), untracked=untracked,
                            ident=_ident(p), samecause=_samecause(p), human=human, local_pass=local_pass)
    arb = decide(role_triggers)
    # K3r2-M1: EX-DWC only where it can change the outcome and never into a person — the attempt would
    # ADVANCE, the cap is not reached and the MAJOR budget is unspent; its loop_back SPENDS that budget
    # (legacy: "MAJOR 급 → MAJOR 루프백 1회"), and DWC never votes in the stagnation guard. At the cap or
    # with the budget spent, the concern is recorded (PR + unattended log) and the stage proceeds.
    pend = getattr(cx, "dwc_pending", None) or []
    if arb.kind == "advance" and pend:
        if n_att < XA.EXECUTE_MAX_ATTEMPTS and not cx.major_spent:
            extra = dwc_judgment(p, cx, attempt, pend)
            if extra:
                arb2 = decide(role_triggers + extra)
                if arb2.kind == "retry":
                    arb, cx.major_spent = arb2, True
        else:
            B.record_code(p, STAGE, "dwc-recorded", "recorded", refs=",".join(r for r, _t in pend),
                          reason="concern not retried (%s): %s" % (
                              "attempt cap" if n_att >= XA.EXECUTE_MAX_ATTEMPTS else "MAJOR budget spent",
                              B.one_line("; ".join(t for _r, t in pend), 300)))
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
    if arb.kind == "stagnant" and not getattr(cx, "stagnant_retried", False):
        # 0.102.5 (#1945): before a person, the developer gets ONE more attempt (per invocation, durable in the log)
        # with the exact blocker and how to clear it — #1945 asked a person twice over a bare-path `baselines` line
        cx.stagnant_retried = True
        # 0.102.6 (review-0102-5 m4): the block carries what the hint is made of (the cause and this attempt's
        # reasons) — a crash during the retried developer call resumes with the same hint (`restore_invocation_state`)
        B.record_code(p, STAGE, "stagnant-retry", "developer", refs=cx.stage_start,
                      reason=B.one_line(arb.stagnant_reason, 300),
                      extra={"cause": B.one_line(arb.stagnant_reason, 600),
                             "details": B.one_line(" ;; ".join(B.one_line(x, 400) for x in arb.reasons or () if x),
                                                   1500) or None})
        cx.reinvoke_addendum = stagnant_hint(arb.stagnant_reason, arb.reasons)
        return "reinvoke"
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


def stagnant_hint(reason, details=()):
    """0.102.5: the retry note of the automatic re-invoke after a recurring blocker — the exact cause (and this
    attempt's blocking reasons) and a fix hint the engine can state (no judgment)."""
    r = " ".join([reason or ""] + [d for d in details or () if d])
    out = ["The same blocker came back after the previous attempt — the engine stopped it: %s" % B.one_line(reason, 600)]
    for d in details or ():
        if d and d != reason:
            out.append("- %s" % B.one_line(d, 400))
    if "undeclared visual change" in r:
        out.append("Fix: declare EVERY visual baseline you changed or that must be regenerated in result.json "
                   "`baselines`, one string each, exactly `<A|M|D|C|P|P-withdrawn> <path> — <reason>` (A added, M "
                   "modified, D deleted, C config, P pending regeneration) — e.g. `M %s — <why it changed>`. A bare "
                   "path is not read." % (re.search(r"undeclared visual change: ([^\s,;]+)", r).group(1)
                                           if re.search(r"undeclared visual change: ([^\s,;]+)", r) else "<path>"))
    elif TIMEOUT_RE.search(r):
        out.append("Fix: the suite did not finish inside the ceiling — find the test that hangs (the last running test "
                   "is named above) and make it finish; never weaken or skip it.")
    elif "suite red" in r or "not green" in r:
        out.append("Fix: make the failing test(s) named above pass with the implementation — never by editing or "
                   "skipping the test.")
    out.append("Fix exactly this first. If it cannot be fixed, end with `BLOCKED: <why>` instead of repeating it.")
    return "\n".join(out)


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
    from guildcore.records import redact as RD
    hunks = "\n".join("### %s\n%s" % (c.location, RD.redact(p.vcs.hunk(mb, c.file, c.line))) for _k, c in new_bm[:8]) if mb else ""
    parts = [("findings", findings), ("hunks", hunks),
             ("design", (p.read_file("docs/specs/%d/skeleton.md" % p.issue) or "")[:6000]),
             ("test_cases", (p.read_file("docs/specs/%d/test-cases.md" % p.issue) or "")[:6000]),
             ("roles", "\n".join("%s %s — %s" % t for t in role_triggers) or "none"),
             ("developer", "%s: %s" % dev_route if dev_route else "DONE")]
    model = "opus" if any(c.severity in ("BLOCKER", "MAJOR") for _k, c in new_bm) else None
    spec = JG.spec(p, "EX-ARB", parts, STAGE, "X4", model=model, cwd=p.root)
    cx.ex_arb_spec = spec                               # 0.102.7 M1: the security reading reads its inputs too
    return p.judge(spec)


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
        try:
            push()
        except PushProblem as pp0:
            if pp0.kind != "transient":
                raise
            push()                                                  # K3r1-m7: P5.2 one retry
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
    # K3r1-m2: never a fork's PR that happens to use the same head name
    hits = [h for h in p.gh.pr_for_head(p.branch) if not h.get("isCrossRepository")]
    if hits:
        prn = int(hits[0]["number"])
        try:
            for name, blk in sections:
                if blk is None:
                    p.writer.pr_body_edit(prn, lambda body, n=name: _drop(body, n))
                else:
                    p.writer.pr_body_splice(prn, name, blk)
        except ValueError:
            return env_pause(p, "PR body unreadable", "PR body unreadable", "X5.11")
    else:
        body = pr_body(p, cx, sections, base_note)
        title = pr_title(cx.variant, issue.get("title") or "#%d" % p.issue)
        res = p.writer.pr_create(p.branch, pr_base, title, body, draft=bool(getattr(p, "draft", False)))
        prn = res["number"]
    if p.unattended:
        UL.splice(p.writer, p.gh, p.issue, prn)
    if cx.loopback is not None:                                                 # X6 (P6.2)
        r = consume(p, cx)
        if r is not None:
            return r
    ho = {"impl_files": ",".join(getattr(cx, "impl_files", None) or []) or "-", "base": p.base, "branch": p.branch,
          "head": p.vcs.head() or "-", "push": push_kind(getattr(p, "remote_url", None))}
    B.record_code(p, STAGE, "execute-handoff", "advance", refs="#%d" % p.issue, extra=ho)   # K3r1-M2
    B.transition(p, e, "test")
    r = B.StageResult(B.StageResult.ADVANCE, nxt="test")
    r.handoff = dict(ho, impl_files=getattr(cx, "impl_files", None) or [], push_url=getattr(p, "remote_url", None))
    return r


def push_kind(url):
    """The push target on record: scheme and host only (a URL may embed a credential)."""
    if not url:
        return "-"
    m = re.match(r"^([a-z+]+)://(?:[^@/]*@)?([^/:]+)", url)
    if m:
        return "%s:%s" % (m.group(1), m.group(2))
    m = re.match(r"^(?:[^@/\s]+@)?([^:/\s]+):", url)
    return "ssh:%s" % m.group(1) if m else "path"


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
    lines = ["Closes #%d" % p.issue, "", VR.SUMMARY_HEAD[cx.variant],
             role_text(summ, one_line=False) or "(developer summary missing)"]
    if base_note:
        lines += ["", base_note]
    if cx.dwc:
        lines += ["", "## 리뷰 우려 (DONE_WITH_CONCERNS)"] + ["- %s" % role_text(x) for x in cx.dwc]
    body = "\n".join(lines)
    for name, blk in sections:
        if blk:
            body += "\n\n" + blk
    return body + "\n"


CLOSING_RE = re.compile(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)(\s*:?\s+)(#|[\w.-]+/[\w.-]+#|https?://\S+?/issues/)(\d+)", re.I)


def role_text(text, one_line=True):
    """P1 / K3r1-B1·m3: every role-produced text the engine posts — redact (incl. exact copy_ignored
    values) + marker neutralization, and closing keywords defused (only the engine's own first
    `Closes #N` line may close an Issue)."""
    v = markers.value(text or "", one_line=one_line)
    return CLOSING_RE.sub(lambda m: "%s%s%s\u200b%s" % (m.group(1), m.group(2), m.group(3), m.group(4)), v)


def consume(p, cx):
    """P6.2 / D-6.2: the latest active block without `consumed:` whose `at:` ≤ stage-start gets
    `consumed: <ts>`; verified by re-read, one retry (GhWriter), else NH `defect:`."""
    comments = B.records(p)
    lb = LB.from_comments(comments)
    if lb is None:
        return None
    # K3r1-m5: the block X0 found (by its number) — never a re-pick by the clock at X6
    want = "### loopback %d" % cx.loopback_n
    blk = next((b for b in lb.active() if markers.clean(b.heading) == want), None)
    if blk is None or blk.has("consumed"):
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

def legacy_unreadable(p, comments):
    """K4 carry-over 6: a legacy audit block's free-form `looped-back` lines are NOT read as pending
    (no guessing at a severity/identity from prose — the auditor re-scans the whole diff anyway); each
    such block is put on the record once (`legacy-pending-unreadable`, shown in the C14 PR log) so a
    person sees what the carry-forward could not."""
    from guildcore.decisions import DecisionLog
    rec = AU.from_comments(comments)
    if rec is None:
        return
    seen = set(b.get("refs") for b in DecisionLog.load(comments).blocks if b.get("point") == "legacy-pending-unreadable")
    for blk in rec.blocks:
        if blk.unreadable_pending and ("audit-record %d" % blk.n) not in seen:
            B.record_code(p, STAGE, "legacy-pending-unreadable", "not-carried", refs="audit-record %d" % blk.n,
                          reason=B.one_line(blk.unreadable_pending[0], 200))


def env_pause(p, line, token, step):
    """K3 r1-m8 (K4 carry-over 3): an execute `env:` stop carries the H§M read on its record — code writes
    `사람 지시 확인: 없음 — …` when no person left an unmarked comment (no judgment); otherwise SJ-DIRECTIVE
    reads them (whole) and an applicable one is shown on the line after the cause (conservative: the stop
    is still taken — the engine cannot act on a free-text directive by itself)."""
    from workflows.dev import directive as DR
    try:
        g = DR.gather(p.gh, p.issue, p=p)
    except Exception:                     # noqa: BLE001 — the read never blocks the stop itself
        g = None
    dline = None
    if g is not None:
        kind, dline, dd = DR.judge(p, STAGE, g, line, step)
        if dd is not None:
            B.record_judgment(p, STAGE, "DIRECTIVE", "J-H1", dd, choice=kind)
    return B.pause(p, STAGE, "env", line, token, env_key="other", directive_line=dline)


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
