"""workflows.dev.stages.children — a split parent at `guild:children` (catalog A §2.4–2.5, dev 2b/2c;
design §3.2 G-INTEGRATE).

    2b.1   discover (`guild:child`, body `Parent Issue: #P([^0-9]|$)`, ascending) — none → defect
    2b.1b  a pending child CLOSED by a same-repo MERGED PR → `guild:done` (−its stage, −needs-human) +
           a parent note `자식 #c 는 PR #p 로 머지되어 done 으로 정리함` (T8)
    2b.2   each pending child in ascending order through the issue FSM (`drive(c)`): DONE → next; any
           other end (pause, ask, fail) STOPS the orchestration — later children are never run after a
           pause (J-DEV-09, a hard rule) — with the fixed line on how to continue
    2c     integration: tech-lead conformance view (`coverage.json`) → L0-INTEGRATE (Read/Grep/Glob) →
           integration:output (replace-in-place) → clean: `guild:children → guild:done` (T9) · gap: the
           fixing child's PR path line; a merged one → attended `ask integration-fix-child` (yes →
           T10 fix child, back to 2b) / unattended pause (`defect:`, or `ambiguity:` when the gap
           needs a decision; a `slicing` gap — the split itself — always needs a person, JR-M6)
"""

import hashlib
import json

from guildcore import ask as ASK
from guildcore import state as ST
from guildcore.records import markers
from guildcore.records import outputs as OUT
from workflows.dev import judging as JG
from workflows.dev import roleout as RO
from workflows.dev.stages import base as B

STAGE = "children"
STOP_LINE = "독립이라고 판단한 자식은 /gld dev <c> 로 따로 돌릴 수 있고, 부모 재개는 done 인 자식을 건너뜁니다"
COVERAGE_SCHEMA = {"type": "object", "properties": {"coverage_path": {"type": "string"}}}


def _labels(c):
    return c.get("labels") or []


def _note(p, text):
    body = "%s\n%s" % (markers.open_tag("note"), markers.finish(text))
    return p.writer.create_comment(p.issue, markers.assert_own_markers(body, "note"))


def cleanup(p, kids):
    """2b.1b — returns the numbers cleaned to done."""
    own_repo = p.gh.owner_repo()
    done = []
    for c in kids:
        if "guild:done" in _labels(c) or (c.get("state") or "").upper() != "CLOSED":
            continue
        merged = None
        for ref in p.gh.closed_by_prs(c["number"]):
            if ref.get("repo") != own_repo:
                continue
            try:
                st = p.gh.pr_state(ref["number"])
            except Exception:
                continue
            if (st.get("state") or "").upper() == "MERGED":
                merged = ref["number"]
                break
        if merged is None:
            continue
        stage = [l for l in _labels(c) if l.startswith("guild:") and l not in ST.NON_STAGE]
        p.writer.labels_apply(c["number"], add=["guild:done"], remove=stage + ["guild:needs-human"])
        _note(p, "자식 #%d 는 PR #%d 로 머지되어 done 으로 정리함" % (c["number"], merged))
        done.append(c["number"])
    return done


def _kids(p):
    """K4r3-B1/m1/m5: the parent's own children (journal numbers, read by number), withdrawn (closed as
    not planned — a re-split) left out; two live children with one slice key → a person (never drive the
    same AC twice). (kids, None) or (None, StageResult)."""
    from workflows.dev.stages import design as D
    kids, stop = B.own_children_or_stop(p, STAGE)
    if stop is not None:
        return None, stop
    dups = D.duplicate_keys(kids)
    if dups:
        return None, B.fail(p, STAGE, "duplicate child Issues for one slice key: %s — close the extra one as not "
                            "planned (or duplicate), then /gld resume %d" % ("; ".join("%s → %s" % (k, ", ".join("#%d" % n for n in v))
                                                                       for k, v in sorted(dups.items())), p.issue))
    return kids, None


def run(p, drive, only=None):
    kids, stop = _kids(p)
    if stop is not None:
        return stop
    if not kids:
        return B.fail(p, STAGE, "parent #%d is at guild:children but this engine's journal holds no live child "
                      "Issue of it (another host or a fresh clone — K5 moves the split record to GitHub)" % p.issue)
    B.note_untrusted(p, STAGE)
    B.register_exact(p)
    from workflows.dev.stages import analyze as A
    try:                                                  # K4r2-m8/M2: the parent's trust, three-valued
        trusted = A.trusted_body(p, p.gh.issue(p.issue))[0]
    except A.TrustUnknown as ex:
        return A.unknown_trust_result(p, STAGE, ex)
    q, res = B.pending_answer(p, STAGE, "integration-fix-child")
    if res is not None:
        if res.get("choice") == "yes":
            stop = fix_child(p, q, trusted)                       # K4r1-m7: create (idempotent by key) BEFORE the
            if stop is not None:                                  # answer is consumed — a crash re-creates nothing
                return stop
            kids, stop = _kids(p)
            if stop is not None:
                return stop
        B.mark_applied(p, STAGE, res)
    cleaned = cleanup(p, kids)
    pending = [c for c in kids if "guild:done" not in _labels(c) and c["number"] not in cleaned]
    for i, c in enumerate(pending):
        if (c.get("state") or "").upper() == "CLOSED":
            line = "자식 #%d 가 done 없이 닫힘 (머지된 PR 없음)" % c["number"]
            if c.get("closed_as"):                         # K4r4-m5: closed as duplicate, not verified
                line += " — closed as %s: reopen it, or close it as not planned to withdraw the slice" % c["closed_as"]
            return B.pause(p, STAGE, "defect", line, line) if p.unattended else \
                B.StageResult(B.StageResult.FAIL, line=line, fail_class="defect")
        if p.events is not None:
            p.events.emit("progress", p.now(), line="child %d of %d: #%d" % (i + 1, len(pending), c["number"]))
        r = drive(c["number"])
        if r.kind == B.StageResult.DONE:
            continue
        rest = ", ".join("#%d" % x["number"] for x in pending[i + 1:]) or "없음"
        note = "자식 #%d 에서 멈춤 (%s) — 남은 자식: %s. %s" % (c["number"], r.token(), rest, STOP_LINE)
        r.notes = list(r.notes) + [note]
        return r
    kids, stop = _kids(p)
    if stop is not None:
        return stop
    return integrate(p, kids, trusted)


def _child_facts(p, c):
    cm = B.records(p, c["number"])
    closed_decided = markers.find(cm, "closed-as-decided") is not None
    so = OUT.find(cm, "test:output")
    prs = ST.match_prs(c["number"], p.gh.pr_search(c["number"])).strict
    test_line = ""
    if so is not None:
        test_line = next((markers.clean(l) for l in so.body.split("\n") if markers.clean(l).startswith("- ")), "")
    flag = "결정대로 닫힘 — 코드 없음" if closed_decided else ("test 출력 없음 — 사람 머지" if so is None else "")
    return {"number": c["number"], "title": c.get("title") or "", "body": (c.get("body") or "")[:3000],
            "prs": prs, "test": test_line, "flag": flag}


def integrate(p, kids, trusted=True):
    comments = B.records(p)
    an = OUT.find(comments, "analyze:output")
    de = OUT.find(comments, "design:output")
    facts = [_child_facts(p, c) for c in kids]
    from workflows.dev.stages import analyze as A
    for f in facts:
        # K4r2-m8: a child body carrying an outsider's AC text is marked untrusted for the tech-lead
        # and L0-INTEGRATE, exactly like the parent's body in STAKES / AN-PO / DE-ARB (r1-m10)
        if not trusted or A.UNTRUSTED_ORIGIN in f["body"]:
            f["body"] = A.OUTSIDER_PREFACE + f["body"]
    children_md = "\n\n".join("#%d %s\nPR: %s\ntest: %s\n%s\n%s" % (
        f["number"], f["title"], ", ".join("#%s %s" % (x["number"], x.get("state")) for x in f["prs"]) or "none",
        f["test"] or "-", f["flag"], f["body"]) for f in facts)
    res = p.run_role(B.RoleCall("tech-lead", "integration", STAGE, "2c.1", schema=COVERAGE_SCHEMA, inputs={
        "parent-analyze.md": {"text": an.body if an else ""}, "parent-design.md": {"text": de.body if de else ""},
        "children.md": {"text": children_md}}))
    r = B.role_outcome(p, STAGE, "tech-lead", res)
    if r is not None:
        return r
    cov = {}
    if res.status in ("DONE", "DONE_WITH_CONCERNS"):
        cov = RO.json_out(p, STAGE, res, (res.extras or {}).get("coverage_path") or "out/coverage.json") or {}
    brief = [("parent_analyze", an.body if an else ""), ("parent_design", (de.body if de else "")[:8000]),
             ("children", children_md), ("coverage_json", json.dumps(cov, ensure_ascii=False)[:12000]),
             ("tech_lead", "%s %s" % (res.status, res.line or ""))]
    d = p.judge(JG.spec(p, "INTEGRATE", brief, STAGE, "2c.2", cwd=p.root))
    gaps = [g for g in d.fields.get("gaps") or [] if isinstance(g, dict)]
    for g in gaps:
        if g.get("kind") == "slicing":
            g["needs_decision"] = True                  # JR-M6: never judged by the split's own judge
    verdict = "clean" if d.choice == "clean" and not gaps else "gap"
    B.record_judgment(p, STAGE, "INTEGRATE", "J-DEV-07,J-DEV-08", d, choice=verdict,
                      reason="; ".join(B.one_line(g.get("line") or "", 100) for g in gaps)[:300] or None)
    nums = set(f["number"] for f in facts)
    lines = [markers.open_tag("integration:output"), "## 통합 검사 — #%d" % p.issue, "",
             "verdict: %s" % verdict, "", "### 커버리지"]
    for c in d.fields.get("coverage") or []:
        lines.append("- %s → %s" % (markers.value(str(c.get("ac"))), markers.value(str(c.get("by")))))
    if gaps:
        lines += ["", "### 간극"]
        for g in gaps:
            fix = g.get("child_to_fix")
            lines.append("- %s%s: %s" % (g.get("kind"), (" (#%d)" % fix) if isinstance(fix, int) and fix in nums else "",
                                         markers.value(g.get("line") or "")))
    lines += ["", "자식: %s" % ", ".join("#%d" % f["number"] for f in facts), markers.close_tag("integration:output")]
    p.writer.upsert_comment(p.issue, "integration:output", markers.assert_own_markers("\n".join(lines), "integration:output"))
    if verdict == "clean":
        p.writer.labels_apply(p.issue, add=["guild:done"], remove=["guild:children", "guild:needs-human"])
        return B.StageResult(B.StageResult.DONE)
    g = gaps[0]
    fix = g.get("child_to_fix") if isinstance(g.get("child_to_fix"), int) and g.get("child_to_fix") in nums else None
    decision = bool(g.get("needs_decision")) or fix is None
    gap_line = "integration gap — %s" % B.one_line(g.get("line") or "", 200)
    path = "통합 수정 자식을 만들거나(/gld dev %d 가 묻습니다) 직접 고친 뒤 /gld resume %d" % (p.issue, p.issue)
    merged = False
    if fix is not None:
        f = next(x for x in facts if x["number"] == fix)
        open_pr = [x for x in f["prs"] if (x.get("state") or "").upper() == "OPEN"]
        if open_pr:
            order = ", ".join("#%d" % x for x in (d.fields.get("merge_order") or []) if isinstance(x, int)) or "-"
            path = '#%d 의 PR #%s 에서 고칩니다: /gld review %s 후 "고쳐 주세요", 또는 직접 수정. 머지 순서: %s. 머지 뒤 /gld resume %d' % (
                fix, open_pr[0]["number"], open_pr[0]["number"], order, p.issue)
        else:
            merged = True
    if merged and not p.unattended and g.get("kind") != "slicing":
        q = ASK.Question("integration-fix-child", "통합 수정 자식 이슈를 만들까요? — %s통합 수정 — %s (Parent Issue: #%d)" % (
            "[Guild子] ", B.one_line(g.get("line") or "", 120), p.issue),
            [{"token": "yes", "label": "만든다"}, {"token": "no", "label": "만들지 않음"}], refs=g.get("line", "")[:200])
        return B.ask(p, STAGE, q, gap_line)
    if not p.unattended:
        q = ASK.Question("integration-gap", "%s — %s" % (gap_line, path), [{"token": "stop", "label": "stop"}])
        return B.ask(p, STAGE, q, "%s — %s" % (gap_line, path))
    kind = "ambiguity" if decision else "defect"
    return B.pause(p, STAGE, kind, gap_line, "%s: %s" % (kind, gap_line), prose=path)


def fix_child(p, q, trusted=True):
    line = (q.get("refs") or "integration fix") if q is not None else "integration fix"
    key = "%d-fix-%s" % (p.issue, hashlib.sha1(line.encode("utf-8")).hexdigest()[:8])
    import re
    body = re.sub(r"Parent Issue:\s*#", "Parent Issue #", markers.value(line))
    if not trusted:
        from workflows.dev.stages import analyze as A
        body += "\n\n" + A.UNTRUSTED_ORIGIN                # K4r2-m8: inherits the outsider parent's untrust
    body = "%s\n\nParent Issue: #%d" % (body, p.issue)
    from guildcore.adapters.gh import GhWriteError
    try:
        p.writer.issue_create("[Guild子] 통합 수정 — %s" % markers.value(line)[:80], body,
                              labels=["guild:child", "guild:analyze"], key=key)
    except GhWriteError as ex:
        # K4r4-m3: the same classes as make_children — an unknown create is `env: service`, not an engine defect
        if ex.kind in ("auth", "ratelimit"):
            raise
        line = "integration fix child creation failed — %s" % B.one_line(str(ex), 320)
        if ex.kind == "ambiguous":
            return B.unknown_create(p, STAGE, line, ex)
        return B.fail(p, STAGE, line, "transient" if ex.kind == "transient" else "defect")
    return None
