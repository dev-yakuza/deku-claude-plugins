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


def run(p, only=None, config_present=True, diff_paths=None):
    e = B.enter(p, STAGE, config_present, only)
    if isinstance(e, B.StageResult):
        return e
    comments = p.gh.comments(p.issue)
    cfg = cfg_dict(p)
    blk = LP.interrupted(comments, "guild:qa", e.labels)
    if blk is not None:
        return LP.finish_interrupted(p, STAGE, blk)
    q, res = B.pending_answer(p, STAGE, "loopback", comments)
    if res is not None:
        return apply_answer(p, STAGE, R.QA, q, res, comments)

    issue = p.gh.issue(p.issue)
    test_out = OUT.find(comments, "test:output")
    ledger = V.visual_ledger(test_out.body) if test_out else None
    pr = find_pr(p)                                                        # Q2.1 first
    pr_body = (pr or {}).get("body")
    diff = diff_paths if diff_paths is not None else _diff_paths(p)

    inputs = {"issue.md": "# %s\n\n%s" % (issue.get("title") or "", issue.get("body") or ""),
              "test-output.md": test_out.body if test_out else "(none)",
              "pr-body.md": pr_body if pr_body is not None else "(no open PR found)",
              "e2e.txt": str((cfg.get("commands") or {}).get("e2e")),
              "visual-available.txt": "yes" if V.visual_available(cfg) else "no",
              "unattended.txt": "yes — never run a real-dependency smoke" if p.unattended else "no"}
    qres = p.run_role(B.RoleCall("qa", "run", STAGE, "Q1", inputs=inputs))
    o = B.role_outcome(p, STAGE, "qa", qres)
    if o is not None:
        return o
    if p.push is not None and qres.status in ("DONE", "DONE_WITH_CONCERNS"):
        p.push()                                                           # §5.5: qa's test commits

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

    ci = CI.record(p.gh, pr)                                               # Q2.2
    if ci.is_red and p.engine_cfg("qa", {}).get("stop_on_ci_red") is True:   # Q2.3 habit stop
        return _ci_stop(p, ci)

    d, checklist = _judge(p, cfg, qres, dres, test_out, issue, diff)       # Q2.5
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
    honesty = ["자동·에이전트 확인: test 단계 원문 + qa 실행 항목(위)",
               "사람 확인 필요: %d건" % len(items) if items else "사람 확인 필요: 없음 — " + NONE_LEFT]
    fu = _followups(p, cfg, qres, comments, pr)                            # computed before the post
    body = R.qa_output(p.issue, plan_lines, ui_line, honesty, ci.line, p.now(), items if pr is None else [],
                       pr.get("number") if pr else None, followups_line=fu["line"])
    p.writer.upsert_comment(p.issue, R.QA, body)                           # Q2.4
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
        sig = sorted(set(x.get("id") for x in defects if x.get("id"))) or ["qa:block"]
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
    out = []
    plan = qres.extras.get("plan")
    if isinstance(plan, str) and plan.strip():
        txt = _read_any(plan)
        out.append("계획·결과: %s" % (plan if txt is None else B.one_line(txt, 400)))
    for h in qres.extras.get("ran") or []:
        out.append("실행: %s" % h)
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


def _judge(p, cfg, qres, dres, test_out, issue, diff):
    qb = p.read_file("docs/standards/quality-bar.md") or "(no quality-bar.md)"
    brief = [("qa", "QA report:\nRESULT: %s\n%s" % (qres.line or qres.status, json.dumps(qres.extras, ensure_ascii=False)[:6000])),
             ("designer", "Designer: %s" % ((dres.line or dres.status) if dres else "not convened")),
             ("bar", "Quality bar:\n" + qb[:4000]),
             ("issue", "Issue:\n%s\n%s" % (issue.get("title") or "", (issue.get("body") or "")[:4000])),
             ("test", "test:output:\n" + ((test_out.body if test_out else "")[:5000])),
             ("diff", "Changed files:\n" + "\n".join(diff or ["(unknown)"])),
             ("candidates", "Human-QA candidates from qa:\n" + "\n".join(str(x) for x in qres.extras.get("human_items") or []))]
    d = p.judge(JG.spec(p, "QA", brief, STAGE, "Q2.5"))
    bad = JG.hedged(d.fields.get("checklist"))
    if bad:
        brief.append(("lint", "Your checklist used banned hedge words in: %s. Rephrase each as an "
                              "instruction (no 권장/가능하면/여유되면/미검증(참고))." % "; ".join(bad)))
        d = p.judge(JG.spec(p, "QA", brief, STAGE, "Q2.5", point="QA:relint"))
    B.record_judgment(p, STAGE, "QA", "Q-DEFECT,Q-FIXABLE,Q-PASS,Q-CHECKLIST", d,
                      reason=d.fields.get("reason"),
                      extra={"defects": ",".join("%s:%s" % (x.get("id"), x.get("fixable_in_code"))
                                                 for x in d.fields.get("defects") or [] if x.get("blocking")) or None})
    return d, [x for x in d.fields.get("checklist") or [] if x.strip()]


def _ci_stop(p, ci):
    g = DR.gather(p.gh, p.issue)
    kind, dline, _d = DR.judge(p, STAGE, g, ci.line, "Q2.3")
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
    if not has_design:
        return {"run": False, "items": [], "carried": carried, "line": None, "prev": prev}
    seen = set(i.title for i in carried)
    unfiled, skipped = [], []
    for it in _followup_items(qres):
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
    have = markers.find(p.gh.comments(pr["number"]), name)
    if fu["items"] or have is not None:
        notice = FU.render_pr_notice(p.issue, [i.title for i in fu["items"]])
        p.writer.upsert_comment(pr["number"], name, notice)
