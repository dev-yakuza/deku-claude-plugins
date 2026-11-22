"""workflows.dev.stages.qa — the `qa` stage as code (C §2.Q; design §3.3 QA/DIRECTIVE, §3.4 PRMATCH/FOLLOWUP).

    Q0  enter (as test, `guild:qa`) → interrupted loop-back → an applied human loop-back answer
        (the answer re-run skips everything else — qa:output is NOT rewritten, its `ran-at:` stays)
    Q2.1 PR lookup FIRST (C-F-4): open PRs whose body has `#N`; strict = closing-keyword regex;
        strict empty ∧ candidates → MJ-PRMATCH (`unsure` → none)
    Q1  the qa role (inputs as files — Issue body, test:output, PR body; roles never read GitHub);
        Q1.5 designer gate when Q-UI-CONVENE (code: ux.md exists ∨ designer cast ∨ the diff
        touches UI globs; no diff known → convene), image list from the test:output ledger
        (M, then A without case, then other A; ≤ 12, `(+k more: …)`); qa committed automated
        tests → the ENGINE pushes (`push` port, §5.5)
    Q2.2 `### PR CI` (code, workflows.dev.ci); Q2.3 habit stop only when
        `engine.qa.stop_on_ci_red` (default false): directives read (H§M) then pause
        `env: ci-blocked` (never started) / `defect: <check> — …` (this PR's red)
    Q2.5 SJ-QA (defects · fixable · checklist · quality bar); hedge words → ONE re-call, then
        stripped by code; `correction` capture per blocking defect (surprise)
    Q2.4 qa:output (replace-in-place, `ran-at:` — C5) → PR body `manual-qa` splice (INV4; an
        unreadable body → pause `PR body unreadable`) → Q2.6 follow-ups (only with design
        artifacts): previous record's declined/filed carried, closed-state mapping in code,
        MJ-FOLLOWUP for open matches; never created unattended — `unfiled` + the PR notice →
        the PR body's unattended-log (C14) re-spliced
    Q3  pass → `guild:qa → guild:done` (never close the Issue) → DONE; blocking defect →
        attended: `loopback-*` lines + ask; unattended: all fixable → the loop-back procedure
        (`from: qa`, shared cap), else pause `defect: QA defect: <line>`.
"""

import fnmatch
import json
import os
import re

from guildcore import checks as CH
from guildcore import state as ST
from guildcore.checks import visual as V
from guildcore.records import followups as FU
from guildcore.records import manual_qa as MQ
from guildcore.records import markers
from guildcore.records import outputs as OUT
from workflows.dev import ci as CI
from workflows.dev import directive as DR
from workflows.dev import judging as JG
from workflows.dev import unattended_log as UL
from workflows.dev.stages import base as B
from workflows.dev.stages import loopback as LP
from workflows.dev.stages import render as R
from workflows.dev.stages.test import apply_answer, ask_loopback, cfg_dict

STAGE = "qa"
NONE_LEFT = "나머지는 자동 테스트로 검증됨 — 사람 확인 불필요"
FOLLOWUP_HEADING = "후속 항목"
DESIGN_ARTIFACTS = ("skeleton.md", "ux.md", "design.md", "notes.md", "leader-arbitration.md")
UI_GLOBS = ("lib/*/widgets/*", "lib/*widgets*", "lib/*screen*", "lib/*page*", "lib/*view*", "lib/ui/*",
            "*.tsx", "*.jsx", "*.vue", "*.svelte", "*.css", "*.scss", "*.html", "*.storyboard", "*.xib")
IMAGES_CAP = 12
_S = {"type": "string"}
# K2-M6: qa:output renders what the role RAN and did NOT run — required, not folded prose
QA_RUN_SCHEMA = {"type": "object", "required": ["plan", "plan_summary", "ran", "not_run", "human_items"],
                 "properties": {"plan": _S, "plan_summary": {"type": "array", "items": _S},
                                "ran": {"type": "array", "items": _S}, "not_run": {"type": "array", "items": _S},
                                "human_items": {"type": "array"}, "followups_path": {"type": ["string", "null"]}}}


def find_pr(p):
    prs = [x for x in p.gh.pr_search(p.issue) if (x.get("state") or "OPEN").upper() == "OPEN"]
    m = ST.match_prs(p.issue, prs)
    if m.strict:
        n = sorted(m.strict, key=lambda x: x.get("number"))[0]["number"]
        return p.gh.pr(n)
    if not m.candidates:
        return None
    d = p.judge(JG.spec(p, "PRMATCH", [("issue", "Issue #%d" % p.issue),
                                       ("candidates", "\n".join("#%s %s (%s)" % (c.get("number"), c.get("title"),
                                                                                 c.get("url")) for c in m.candidates))],
                        STAGE, "Q2.1"))
    if d.choice == "match" and d.fields.get("pr") in [c.get("number") for c in m.candidates]:
        return p.gh.pr(d.fields["pr"])
    return None


def ui_convene(p, cfg, comments, diff_paths):
    """Q-UI-CONVENE (C-F-10, code): ux.md exists, designer in the analyze/design cast, or the
    diff touches a UI path. Unknown diff → convene (H§G:503 tie → convene)."""
    if p.exists("docs/specs/%d/ux.md" % p.issue):
        return True, "ux.md"
    for name in ("analyze:output", "design:output"):
        so = OUT.find(comments, name)
        if so and re.search(r"(?im)^.*cast:.*\bdesigner\b", so.body):
            return True, "designer in cast"
    if diff_paths is None:
        return True, "diff unknown"
    globs = list(p.engine_cfg("ui_globs", None) or UI_GLOBS) + \
        [x.rstrip("/") + "/*" for x in (cfg.get("visual") or {}).get("packages") or []]
    for path in diff_paths:
        if any(fnmatch.fnmatch(path, g) for g in globs):
            return True, "diff touches %s" % path
    return False, "no UI surface in the diff"


def designer_images(ledger):
    if ledger is None or not ledger.rows:
        return "none"
    m = [r.path for r in ledger.of("M")]
    a_nocase = [r.path for r in ledger.of("A") if not r.case]
    a_rest = [r.path for r in ledger.of("A") if r.case]
    allp = m + a_nocase + a_rest
    head = allp[:IMAGES_CAP]
    more = allp[IMAGES_CAP:]
    return "\n".join(head) + ("\n(+%d more: %s)" % (len(more), ", ".join(more)) if more else "") if allp else "none"


def _diff_paths(p):
    if not p.base or not p.root:
        return None
    from guildcore.adapters import git as G
    out = G.run(p.root, "diff", "--name-only", "%s...HEAD" % p.base, check=False).decode()
    return [x for x in out.split("\n") if x]


def _head(p):
    """K5r8-m2: the checkout's HEAD — the qa role reads the code, which `inputs` does not carry (a commit / reset in the
    engine worktree between a conservative question and its answer must not replay the old report; K5r9-m2: the
    engine never fetches, so a person's push to the remote leaves HEAD as it was — the replayed report reads the same
    local code, and the engine's own push after qa then fails as non-fast-forward). None when unknown."""
    if not p.root:
        return None
    from guildcore.adapters import git as G
    try:
        return G.run(p.root, "rev-parse", "HEAD", check=False).decode().strip() or None
    except Exception:                                                      # noqa: BLE001 — unknown: inputs only
        return None


def run(p, only=None, config_present=True, diff_paths=None):
    e = B.enter(p, STAGE, config_present, only)
    if isinstance(e, B.StageResult):
        return e
    B.note_untrusted(p, STAGE)
    comments = B.records(p)
    cfg = cfg_dict(p)
    blk = LP.interrupted(comments, "guild:qa", e.labels)
    if blk is not None:
        q0, r0 = B.pending_answer(p, STAGE, "loopback", comments)
        if r0 is not None and (blk.get("decided") or "") == "human":
            B.mark_applied(p, STAGE, r0)                  # the answer's block landed before a crash
        return LP.finish_interrupted(p, STAGE, blk)
    q, res = B.pending_answer(p, STAGE, "loopback", comments)
    if res is not None:
        return apply_answer(p, STAGE, R.QA, q, res, comments)

    copy_list = ((cfg.get("engine") or {}).get("effective") or {}).get("copy_ignored") or []
    from guildcore.records import redact as RD
    RD.clear_exact()                  # K2r4-m3: scoped to this Issue's run
    if copy_list:                     # K2r3-M2: the same exact-value redaction as the test stage
        RD.register_exact_from_files(p.root, copy_list)
    issue = p.gh.issue(p.issue)
    from workflows.dev.stages import analyze as A
    try:                                        # K5 (K4r2-m10): issue.md and the QA brief through P2 trust
        issue_md = B.issue_text(p, issue)
        issue_brief = B.issue_text(p, issue, cap=4000)
    except A.TrustUnknown as ex:
        return A.unknown_trust_result(p, STAGE, ex)
    test_out = OUT.find(comments, "test:output")
    ledger = V.visual_ledger(test_out.body) if test_out else None
    pr = find_pr(p)                                                        # Q2.1 first
    pr_body = (pr or {}).get("body")
    diff = diff_paths if diff_paths is not None else _diff_paths(p)

    inputs = {"issue.md": issue_md,
              "test-output.md": test_out.body if test_out else "(none)",
              "pr-body.md": pr_body if pr_body is not None else "(no open PR found)",
              "e2e.txt": str((cfg.get("commands") or {}).get("e2e")),
              "visual-available.txt": "yes" if V.visual_available(cfg) else "no",
              "unattended.txt": "yes — never run a real-dependency smoke" if p.unattended else "no"}
    qres = p.run_role(B.RoleCall("qa", "run", STAGE, "Q1", inputs=inputs, schema=QA_RUN_SCHEMA,
                                 replay_salt=lambda: _head(p)))
    o = B.role_outcome(p, STAGE, "qa", qres)
    if o is not None:
        return o
    pushed_sha = None
    if p.push is not None and qres.status in ("DONE", "DONE_WITH_CONCERNS"):
        try:
            pushed = p.push()                                              # §5.5: qa's test commits
        except Exception as ex:                                            # K2-M4: drift / push failure
            return B.fail(p, STAGE, "engine push after qa failed — %s" % B.one_line(str(ex), 160))
        pushed_sha = pushed if isinstance(pushed, str) else None

    convene, why = ui_convene(p, cfg, comments, diff)                      # Q1.5
    dres = None
    if convene:
        dres = p.run_role(B.RoleCall("designer", "ui-gate", STAGE, "Q1.5",
                                     inputs={"images.txt": designer_images(ledger), "issue.md": inputs["issue.md"]},
                                     allowed_status=("DONE", "DONE_WITH_CONCERNS", "BLOCKED")))
        o = B.role_outcome(p, STAGE, "designer", dres)
        if o is not None:
            return o
    ui_line = ("해당 없음 — %s" % why) if dres is None else \
        "designer: %s" % (dres.line or dres.status)

    ci = CI.record(p.gh, pr, head=pushed_sha)                              # Q2.2
    habit_stop = ci.is_red and (p.engine_cfg("qa", {}) or {}).get("stop_on_ci_red") is True

    prev_qa = _prev_qa(comments)
    d, checklist = _judge(p, cfg, qres, dres, test_out, issue_brief, diff, prev_qa)  # Q2.5
    defects = [x for x in d.fields.get("defects") or [] if x.get("blocking")]
    if dres is not None and dres.status == "BLOCKED" and not any(
            "designer" in (x.get("line") or "") or x.get("id", "").startswith("UX") for x in defects):
        defects.append({"id": "UX-1", "blocking": True, "fixable_in_code": "no",
                        "line": "designer: %s" % (dres.line or "BLOCKED")})
    blocking = bool(defects) or d.choice == "block"
    items = list(checklist) + V.checklist_items(ledger, (cfg.get("visual") or {}).get("env"),
                                                bool(ledger and ledger.of("A")))
    items = [JG.strip_hedges(i) for i in items]

    plan_lines = _plan_lines(qres)
    honesty = honesty_lines(p, cfg, qres, items, ui=convene)
    fu = _followups(p, cfg, qres, comments, pr)                            # computed before the post
    body = R.qa_output(p.issue, plan_lines, ui_line, honesty, ci.line, p.now(), items if pr is None else [],
                       pr.get("number") if pr else None, followups_line=fu["line"])
    p.writer.upsert_comment(p.issue, R.QA, body)                           # Q2.4
    if habit_stop:                                                         # Q2.3 — after the record (K2-m3)
        return _ci_stop(p, ci)
    for x in defects:
        p.capture("correction", STAGE, "designer" if x.get("id", "").startswith("UX") else "qa",
                  x.get("line") or x.get("id"), x.get("evidence") or x.get("line"), "#%d" % p.issue, True)

    if items and pr is not None:                                           # Q2.5 → PR body
        block = MQ.render(items, NONE_LEFT)
        try:
            p.writer.pr_body_splice(pr["number"], MQ.NAME, block)
        except ValueError:
            return _unreadable(p, pr["number"])
    _write_followups(p, fu, pr)                                            # Q2.6
    if pr is not None and p.unattended:
        try:
            UL.splice(p.writer, p.gh, p.issue, pr["number"])               # C14
        except ValueError:
            return _unreadable(p, pr["number"])

    if blocking:                                                           # Q3
        sig = qa_signature(defects, prev_qa) or ["qa:block"]
        line = B.one_line("; ".join(x.get("line") or x.get("id") for x in defects) or
                          d.fields.get("reason") or "quality bar not met", 200)
        if not p.unattended:
            return ask_loopback(p, STAGE, R.QA, line, sig, "QA found %s" % line)
        if defects and all(x.get("fixable_in_code") == "yes" for x in defects):
            return LP.run(p, STAGE, "qa", line, sig)
        return B.pause(p, STAGE, "defect", "QA defect: %s" % line, "QA defect: %s" % line)
    B.transition(p, e, "done")
    return B.StageResult(B.StageResult.DONE)


def _plan_lines(qres):
    out = ["계획: %s" % x for x in qres.extras.get("plan_summary") or []]
    plan = qres.extras.get("plan")
    if isinstance(plan, str) and plan.strip():
        txt = _read_any(plan)
        out.append("계획·결과: %s" % (plan if txt is None else B.one_line(txt, 400)))
    if qres.line:
        out.append("qa 결과: %s" % qres.line)
    return out


def _read_any(path):
    try:
        if os.path.isabs(path) and os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    except OSError:
        pass
    return None


def _prev_qa(comments):
    """Earlier active `from: qa` loop-back blocks: [(reason, {signature elements})]."""
    from guildcore.records import loopback as LBR
    rec = LBR.from_comments(comments)
    if rec is None:
        return []
    return [(markers.unescape(b.get("reason") or ""), LBR.signature_set(b.get("signature") or ""))
            for b in rec.active() if b.get("from") == "qa"]


PATH_TOK = re.compile(r"[\w./-]+\.(?:dart|py|go|[jt]sx?|kt|swift|rb|java|md|ya?ml|json|png)\b")
AC_TOK = re.compile(r"\b(?:AC ?#?\d+|TC-?[A-Z]{0,3}\d+)\b")


def qa_signature(defects, prev):
    """K2-M1: content-based, stable across SJ-QA calls. Per defect: a `same_as` that names an
    element of an earlier qa loop-back's signature (the judge saw them in its brief) is reused;
    else the evidence's file paths / AC ids; else `qa:<sha8(normalised line)>`."""
    import hashlib
    known = set().union(*[s for _r, s in prev]) if prev else set()
    out = set()
    for d in defects:
        same = (d.get("same_as") or "").strip()
        if same and same in known:
            out.add(same)
            continue
        text = " ".join([d.get("evidence") or "", d.get("line") or ""])
        toks = sorted(set(PATH_TOK.findall(text)) | set(" ".join(a.split()) for a in AC_TOK.findall(text)))
        acs = [t for t in toks if AC_TOK.fullmatch(t)]
        if toks and not acs:
            # a file path alone is shared by different defects of one screen (K2r2-m1): the
            # normalised defect sentence's hash rides along
            norm = " ".join((d.get("line") or "").lower().split())
            out.add("+".join(toks) + "#" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:6])
        elif toks:
            out.add("+".join(toks))
        else:
            norm = " ".join((d.get("line") or d.get("id") or "").lower().split())
            out.add("qa:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8])
    return sorted(out)


def honesty_lines(p, cfg, qres, items, ui=True):
    """K2-M6: (a) what ran (the qa role's `ran[]`), (b) what did NOT — the role's `not_run[]` plus
    code-known facts: `commands.e2e` when qa did not run it, the real-dependency smoke when
    unattended, the human's visual judgment; then the human-QA count."""
    ran = [str(x) for x in qres.extras.get("ran") or []]
    not_run = [str(x) for x in qres.extras.get("not_run") or []]
    e2e = (cfg.get("commands") or {}).get("e2e")
    if e2e and not any(str(e2e) in r for r in ran):
        not_run.append("`commands.e2e`(%s)" % e2e)
    if p.unattended:
        not_run.append("실의존 스모크 — 무인 실행이라 수행 안 함")
    if ui:
        not_run.append("사람의 시각 판단")
    out = ["(a) 실행함(증거 있음): %s" % ("; ".join(ran) if ran else "qa 실행 항목 없음 — test 단계 원문에 의존"),
           "(b) 실행 안 함: %s" % "; ".join(dict.fromkeys(not_run))]
    out.append("사람 확인 필요: %d건" % len(items) if items else "사람 확인 필요: 없음 — " + NONE_LEFT)
    return out


def _judge(p, cfg, qres, dres, test_out, issue, diff, prev_qa=()):
    qb_text = p.read_file("docs/standards/quality-bar.md")
    qb = qb_text if qb_text is not None else "(no quality-bar.md — no bar: treat it as met)"
    brief = [("qa", "QA report:\nRESULT: %s\n%s" % (qres.line or qres.status, json.dumps(qres.extras, ensure_ascii=False)[:6000])),
             ("designer", "Designer: %s" % ((dres.line or dres.status) if dres else "not convened")),
             ("bar", "Quality bar:\n" + qb[:4000]),
             ("issue", "Issue:\n%s" % issue),             # K5: the trust-read text (issue_text, capped)
             ("test", "test:output:\n" + ((test_out.body if test_out else "")[:5000])),
             ("diff", "Changed files:\n" + "\n".join(diff or ["(unknown)"])),
             ("candidates", "Human-QA candidates from qa:\n" + "\n".join(str(x) for x in qres.extras.get("human_items") or [])),
             ("prior", "Earlier QA loop-backs on this Issue (set `same_as` to one of these signature elements "
                       "when a defect is the SAME one):\n" + ("\n".join("- %s — signature: %s" % (r, ",".join(sorted(s)))
                                                               for r, s in prev_qa) or "none"))]
    d = p.judge(JG.spec(p, "QA", brief, STAGE, "Q2.5"))
    extra = {}
    # K5r7-m1: never over a PERSON's decision (a conservative-path `block` answer stays `block`)
    if qb_text is None and d.by != "human" and d.fields.get("verdict") == "block" and not any(
            x.get("blocking") for x in d.fields.get("defects") or []):
        d.fields["verdict"], d.choice = "pass", "pass"                  # K2-m9: no bar file = bar met
        d.coerced, d.coerced_by = True, "rule"
        extra["quality_bar"] = "absent"
    B.record_judgment(p, STAGE, "QA", "Q-DEFECT,Q-FIXABLE,Q-PASS,Q-CHECKLIST", d,
                      reason=d.fields.get("reason"),
                      extra=dict(extra, defects=",".join("%s:%s" % (x.get("id"), x.get("fixable_in_code"))
                                                         for x in d.fields.get("defects") or [] if x.get("blocking")) or None))
    checklist = [x for x in d.fields.get("checklist") or [] if x.strip()]
    if JG.hedged(checklist):                                           # K2-M3: re-ask the WORDING only
        brief.append(("lint", "Your checklist used banned hedge words in: %s. Rephrase each as an "
                              "instruction (no 권장/가능하면/여유되면/미검증(참고))." % "; ".join(JG.hedged(checklist))))
        d2 = p.judge(JG.spec(p, "QA", brief, STAGE, "Q2.5", point="QA:relint"))
        B.record_judgment(p, STAGE, "QA:relint", "Q-CHECKLIST", d2, choice="checklist",
                          reason="wording only — verdict and defects stay with the first decision")
        checklist = [x for x in d2.fields.get("checklist") or [] if x.strip()]
    return d, checklist


def _ci_stop(p, ci):
    g = DR.gather(p.gh, p.issue, p=p)
    kind, dline, dd = DR.judge(p, STAGE, g, ci.line, "Q2.3")
    if dd is not None:
        B.record_judgment(p, STAGE, "DIRECTIVE", "J-H1,Q-DIRECTIVE,Q-CI-HABIT", dd, reason=dline)
    if ci.never_started and not ci.red:
        return B.pause(p, STAGE, "env", "PR CI 시작되지 않음 %s" % " ".join(ci.never_started),
                       "PR CI not started", env_key="ci-blocked", directive_line=dline)
    line = "%s — PR CI red" % " ".join(ci.red or ci.never_started)
    return B.pause(p, STAGE, "defect", line, "PR CI red — %s" % line, directive_line=dline)


def _unreadable(p, n):
    from guildcore import ask as ASK
    text = "could not read PR #%d's body in full" % n
    q = ASK.Question("pr-body-unreadable", text, [{"token": "retry", "label": "retry"}, {"token": "stop", "label": "stop"}])
    return B.ask(p, STAGE, q, text, {"cause_kind": "env", "env_key": "other", "line": "PR body unreadable — %s" % text,
                                      "token_cause": "PR body unreadable"})


# ---- follow-ups (Q2.6) -------------------------------------------------------------------------

def _followup_items(qres):
    items = qres.extras.get("followups")
    if items is None and qres.extras.get("followups_path"):
        txt = _read_any(qres.extras["followups_path"])
        try:
            items = json.loads(txt) if txt else []
        except ValueError:
            items = []
    out = []
    for it in items or []:
        if isinstance(it, str):
            out.append({"title": it, "rationale": None, "keywords": it})
        elif isinstance(it, dict) and it.get("title"):
            out.append({"title": it["title"], "rationale": it.get("rationale") or it.get("근거"),
                        "keywords": it.get("keywords") or it["title"]})
    return out


def narrowed_followups(comments):
    """0.102.7 (review-0102-6 m5): the broader parts the analyze stage dropped when it took the narrowest of nested
    readings (`follow_ups` on the KICKOFF block with `auto_narrow`) — follow-up candidates like the qa role's own."""
    from guildcore.decisions import DecisionLog
    try:
        blocks = DecisionLog.load(comments or []).blocks
    except Exception:                                  # noqa: BLE001 — an unreadable log adds nothing
        return []
    out, seen = [], set()
    for b in blocks:
        if b.get("point") != "KICKOFF" or not b.get("auto_narrow"):
            continue
        for t in str(b.get("follow_ups") or "").split(" ;; "):
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                out.append({"title": t, "rationale": "analyze 가 겹친 해석 중 가장 좁은 해석(%s, %s)을 골라 뺀 부분" % (
                    b.get("auto_narrow"), b.id), "keywords": t})
        for t in str(b.get("dropped_ac") or "").split(" ;; "):
            # 0.102.8 (review-0102-7 M4): the AC the narrow reading removed (the judge's chosen reading's)
            t = t.strip()
            if t and ("AC: " + t) not in seen:
                seen.add("AC: " + t)
                out.append({"title": "AC: " + t, "rationale": "analyze 가 가장 좁은 해석(%s, %s)을 골라 뺀 AC" % (
                    b.get("auto_narrow"), b.id), "keywords": t})
    return out


def _dedup(p, item, pr_n):
    rows = [r for r in p.gh.issue_search(item["keywords"], limit=10)
            if int(r.get("number")) not in (p.issue, pr_n or -1)]
    for r in rows:
        st = (r.get("state") or "").upper()
        reason = (r.get("stateReason") or "").upper()
        if st == "CLOSED" and reason == "COMPLETED" and item["title"] in (r.get("title") or ""):
            return "등록 불필요 — #%d에서 완료됨" % r["number"]
        if st == "CLOSED" and reason == "NOT_PLANNED" and item["title"] in (r.get("title") or ""):
            return "등록 불필요 — #%d 미계획으로 닫힘" % r["number"]
    open_rows = [r for r in rows if (r.get("state") or "OPEN").upper() == "OPEN"]
    if not open_rows:
        return None
    d = p.judge(JG.spec(p, "FOLLOWUP", [("item", "Follow-up: %s" % item["title"]),
                                        ("open", "\n".join("#%s %s" % (r["number"], r.get("title")) for r in open_rows))],
                        STAGE, "Q2.6"))
    if d.choice == "covered" and d.fields.get("issue") in [r["number"] for r in open_rows]:
        return "등록 불필요 — #%d 이 덮음" % d.fields["issue"]
    return None


def _followups(p, cfg, qres, comments, pr):
    has_design = any(p.exists("docs/specs/%d/%s" % (p.issue, f)) for f in DESIGN_ARTIFACTS)
    prev = FU.from_comments(comments)
    carried = [i for i in (prev.items if prev else []) if i.status in ("declined", "filed")]
    narrowed = narrowed_followups(comments)
    if not has_design and not narrowed:
        return {"run": False, "items": [], "carried": carried, "line": None, "prev": prev}
    seen = set(i.title for i in carried)
    unfiled, skipped = [], []
    # 0.102.8 (review-0102-7 m5): an auto-narrowed reading's follow-ups are listed even without design output
    for it in (_followup_items(qres) if has_design else []) + narrowed:
        if it["title"] in seen:
            continue
        verdict = _dedup(p, it, pr.get("number") if pr else None)
        if verdict:
            skipped.append("%s — %s" % (it["title"], verdict))
            continue
        unfiled.append(FU.Item("unfiled", None, it["title"], it["rationale"], None))
    if unfiled:
        line = "후속 Issue 등록 필요 %d건 — %s" % (len(unfiled), "기록 코멘트 참조 (자동 생성 안 함)")
    else:
        line = "후속 Issue 등록 필요 항목 없음"
    return {"run": True, "items": unfiled, "carried": carried, "skipped": skipped, "line": line, "prev": prev}


def _write_followups(p, fu, pr):
    if not fu["run"]:
        return
    items = fu["items"] + fu["carried"]
    if items or fu["prev"] is not None:
        body = FU.render(FOLLOWUP_HEADING, items)
        p.writer.upsert_comment(p.issue, FU.NAME, body, pick="latest")
    if pr is None:
        return
    name = FU.pr_notice_name(p.issue)
    have = markers.find(B.records(p, pr["number"]), name)
    if fu["items"] or have is not None:
        notice = FU.render_pr_notice(p.issue, [i.title for i in fu["items"]])
        p.writer.upsert_comment(pr["number"], name, notice)
