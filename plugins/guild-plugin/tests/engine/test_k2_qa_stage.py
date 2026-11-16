"""K2 — the qa stage: PR lookup, PR CI record, SJ-QA, manual-qa splice (INV4), follow-ups, C14, Q3."""

import unittest

from _k2 import Harness, comment, decision, fixture, judge_qa, role
from guildcore.decisions import DecisionLog
from guildcore.records import followups as FU
from guildcore.records import loopback as LB
from guildcore.records import manual_qa as MQ
from guildcore.records import needs_human as NH
from guildcore.records import outputs as OUT
from guildcore.records import prbody as PB
from workflows.dev import ci as CI
from workflows.dev import unattended_log as UL
from workflows.dev.stages import qa as Q

TEST_OUT = ("<!-- guild:test:output -->\n## Test\n- (d) E2E 불요: x\n<!-- guild:visual-baselines -->\nrun: yes\n"
            "M test/goldens/a.png — 색\nP test/goldens/b.png — 재생성\n<!-- /guild:visual-baselines -->\n"
            "<!-- /guild:test:output -->")
PR_BODY = "## 요약\n사람이 쓴 본문\n\nCloses #7\n\n<!-- guild:auditor:pr -->\nx\n<!-- /guild:auditor:pr -->\n"


def pr(body=PR_BODY, n=40, sha="a" * 40):
    return {"number": n, "url": "https://github.com/o/r/pull/%d" % n, "state": "OPEN", "title": "feat: x",
            "body": body, "headRefOid": sha}


def qa_harness(case, prs=(pr(),), judges=None, roles=None, unattended=True, runs=None, comments=(),
               labels=("guild:qa",), design=True):
    fx = fixture(labels=labels, comments=[comment(TEST_OUT, 2)] + list(comments), prs=prs)
    fx["check_runs"]["a" * 40] = runs if runs is not None else [{"id": 1, "name": "ci", "conclusion": "success",
                                                                "annotations": 0}]
    h = Harness(case, fx, unattended=unattended,
                roles=roles or [role("DONE", plan="qa-report.md", human_items=["실기기 확인 — iPhone"],
                                     followups=[{"title": "다음 작업", "rationale": "skeleton.md §9",
                                                 "keywords": "다음 작업"}])],
                judges=judges or {"QA": [judge_qa(checklist=["실기기에서 동기화 확인 — iPhone 15"])]})
    if design:
        h.write_file("docs/specs/7/skeleton.md", "# s\n")
    return h


class QaPass(unittest.TestCase):
    def test_pass_posts_output_splices_checklist_and_moves_to_done(self):
        h = qa_harness(self)
        r = Q.run(h.p, diff_paths=["lib/models/a.dart"])
        self.assertEqual(r.token(), "OK DONE")
        self.assertEqual(h.labels(), ["guild:done"])
        out = h.body_with("qa:output")
        self.assertIn("\n### PR CI\nPR CI: green\n", out)
        self.assertRegex(out, r"\nran-at: 2026-11-16T\d\d:\d\d:\d\dZ\n")
        self.assertEqual(OUT.qa_last_ran(h.gh.comments(7))[:5], "2026-")
        body = h.gh.fx["prs"][0]["body"]
        self.assertTrue(body.startswith(PR_BODY.rstrip("\n")))          # INV4: outside bytes kept
        ck = MQ.from_pr_body(body)
        self.assertEqual([t for _x, t in ck.items][0], "실기기에서 동기화 확인 — iPhone 15")
        self.assertIn("재생성 필요한 기준 이미지 1건", ck.render())        # ledger-derived items
        self.assertIn("갱신·삭제·재생성 1건", ck.render())
        self.assertIn(Q.NONE_LEFT, ck.render())

    def test_followups_unattended_are_unfiled_with_pr_notice(self):
        h = qa_harness(self)
        Q.run(h.p, diff_paths=[])
        rec = FU.from_comments(h.gh.comments(7))
        self.assertEqual([(i.status, i.title) for i in rec.items], [("unfiled", "다음 작업")])
        notice = FU.pr_notices(h.gh.comments(40), 7)
        self.assertEqual(notice[0].titles, ["다음 작업"])
        self.assertTrue(notice[0].render().split("\n")[1].startswith("후속 Issue 등록 필요 1건 — 사람 확인 전"))
        self.assertEqual(h.gh.fx["issues"].keys() - {"7", "40"}, set())   # never created unattended

    def test_followups_carry_declined_and_map_closed(self):
        prev = FU.render("후속 항목", [FU.Item("declined", None, "옛 항목", "이유", None)])
        h = qa_harness(self, comments=[comment(prev, 3)])
        h.gh.fx["issues"]["99"] = {"number": 99, "title": "다음 작업", "body": "", "state": "CLOSED",
                                   "stateReason": "COMPLETED", "labels": []}
        orig = h.gh.issue_search
        h.gh.issue_search = lambda text, limit=50: [dict(orig(text, limit)[0], stateReason="COMPLETED")] \
            if orig(text, limit) else []
        Q.run(h.p, diff_paths=[])
        rec = FU.from_comments(h.gh.comments(7))
        self.assertEqual([(i.status, i.title) for i in rec.items], [("declined", "옛 항목")])
        self.assertIn("항목 없음", h.body_with("qa:output"))

    def test_no_design_artifacts_skips_followups(self):
        h = qa_harness(self, design=False)
        Q.run(h.p, diff_paths=[])
        self.assertIsNone(FU.from_comments(h.gh.comments(7)))

    def test_no_pr_keeps_items_in_output(self):
        h = qa_harness(self, prs=())
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.kind, "DONE")
        out = h.body_with("qa:output")
        self.assertIn("PR CI: 없음", out)
        self.assertIn("PR 을 찾지 못했습니다", out)
        self.assertIn("- [ ] 실기기에서 동기화 확인 — iPhone 15", out)

    def test_prmatch_when_no_closing_reference(self):
        p = pr(body="relates to #7 work")
        h = qa_harness(self, prs=(p,))
        h.judges["PRMATCH"] = decision("match", {"verdict": "match", "pr": 40})
        Q.run(h.p, diff_paths=[])
        self.assertIsNotNone(MQ.from_pr_body(h.gh.fx["prs"][0]["body"]))

    def test_hedges_recall_once_then_stripped(self):
        h = qa_harness(self, judges={"QA": [judge_qa(checklist=["가능하면 실기기 확인 — iPhone"]),
                                            judge_qa(checklist=["권장: 태블릿 확인 — iPad"])]})
        Q.run(h.p, diff_paths=[])
        self.assertEqual(len([j for j in h.calls["judges"] if j.group == "QA"]), 2)
        ck = MQ.from_pr_body(h.gh.fx["prs"][0]["body"]).render()
        self.assertNotIn("권장", ck)
        self.assertIn("태블릿 확인 — iPad", ck)

    def test_designer_convened_on_ui_diff_with_image_order(self):
        h = qa_harness(self)
        h.roles.append(role("DONE"))
        Q.run(h.p, diff_paths=["lib/widgets/card.dart"])
        d = [c for c in h.calls["roles"] if c.role == "designer"][0]
        self.assertEqual(d.inputs["images.txt"], "test/goldens/a.png")
        self.assertIn("designer: DONE", h.body_with("qa:output"))

    def test_unattended_log_spliced_c14(self):
        h = qa_harness(self, judges={"QA": [decision("pass", {"defects": [], "checklist": [], "quality_bar_met": "yes",
                                                               "verdict": "pass"}, unsure=True)]})
        Q.run(h.p, diff_paths=[])
        body = h.gh.fx["prs"][0]["body"]
        self.assertIn(PB.UNATTENDED_HEADING, body)
        self.assertEqual(len(PB.unattended_entries(body)), 1)


class QaDefects(unittest.TestCase):
    def defect(self, fixable):
        return judge_qa("block", defects=[{"id": "D1", "blocking": True, "fixable_in_code": fixable,
                                           "line": "저장 후 목록이 갱신되지 않음"}])

    def test_fixable_loops_back_from_qa(self):
        h = qa_harness(self, judges={"QA": [self.defect("yes")]})
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        b = LB.from_comments(h.gh.comments(7)).latest_active()
        self.assertEqual(b.get("from"), "qa")
        self.assertEqual(b.get("signature"), ",".join(Q.qa_signature([{"line": "저장 후 목록이 갱신되지 않음"}], [])))
        self.assertEqual(h.labels(), ["guild:execute"])
        self.assertIn(("correction", "qa", "qa", "저장 후 목록이 갱신되지 않음", True), h.captures)

    def test_not_fixable_pauses_qa_defect(self):
        h = qa_harness(self, judges={"QA": [self.defect("no")]})
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.token(), "OK PAUSE: needs-human — QA defect: 저장 후 목록이 갱신되지 않음")
        self.assertEqual(NH.from_comments(h.gh.comments(7))[-1].cause_line,
                         "defect: QA defect: 저장 후 목록이 갱신되지 않음")
        self.assertEqual(h.labels(), ["guild:needs-human", "guild:qa"])

    def test_fixable_unsure_coerced_to_no(self):
        from workflows.dev import judging as JG
        f, by = JG.coerce_qa({"defects": [{"id": "D", "blocking": True, "fixable_in_code": "unsure"}],
                              "verdict": "pass", "quality_bar_met": "yes"})
        self.assertEqual((f["defects"][0]["fixable_in_code"], f["verdict"], by), ("no", "block", "rule"))

    def test_attended_defect_asks_with_loopback_lines(self):
        h = qa_harness(self, judges={"QA": [self.defect("yes")]}, unattended=False)
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.kind, "ASK")
        self.assertTrue(r.line.startswith("QA found 저장 후 목록이 갱신되지 않음; loop back to execute?"))
        so = OUT.find(h.gh.comments(7), "qa:output")
        self.assertTrue(so.loopback_signature.startswith("qa:"))

    def test_designer_blocked_is_a_blocking_defect(self):
        h = qa_harness(self)
        h.roles.append(role("BLOCKED", "대비 부족 (a11y)"))
        r = Q.run(h.p, diff_paths=["lib/widgets/card.dart"])
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("designer: 대비 부족", r.token())

    def test_unreadable_pr_body_pauses(self):
        bad = PR_BODY + "<!-- guild:manual-qa -->\na\n<!-- guild:manual-qa -->\nb\n<!-- /guild:manual-qa -->\n"
        h = qa_harness(self, prs=(pr(body=bad),))
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.token(), "OK PAUSE: needs-human — PR body unreadable")
        self.assertEqual(h.gh.fx["prs"][0]["body"], bad)

    def test_ci_habit_stop_only_when_configured(self):
        runs = [{"id": 5, "name": "build", "conclusion": "failure", "annotations": 1}]
        cfg = dict(__import__("_k2").CFG, engine={"qa": {"stop_on_ci_red": True}})
        h = qa_harness(self, runs=runs)
        h.p.config = cfg
        h.gh.fx["annotations"]["5"] = ["The job was not started because recent account payments have failed"]
        r = Q.run(h.p, diff_paths=[])
        self.assertEqual(r.token(), "OK PAUSE: needs-human — PR CI not started")
        p = NH.from_comments(h.gh.comments(7))[-1]
        self.assertTrue(p.cause_line.startswith("env: ci-blocked — "))
        self.assertTrue(p.directive_line.startswith("사람 지시 확인: 없음"))

    def test_answer_rerun_does_not_touch_qa_output(self):
        h = qa_harness(self, judges={"QA": [self.defect("yes")]}, unattended=False)
        r = Q.run(h.p, diff_paths=[])
        before = OUT.find(h.gh.comments(7), "qa:output").body
        h.decisions.resolve(r.qid, {"kind": "loopback", "stage": "qa", "by": "human", "choice": "loop-back"})
        r2 = Q.run(h.p, diff_paths=[])
        self.assertEqual(r2.kind, "LOOPBACK")
        self.assertEqual(OUT.find(h.gh.comments(7), "qa:output").body, before)


class CiRecord(unittest.TestCase):
    def cls(self, runs, ann=None):
        return CI.classify(runs, lambda rid: (ann or {}).get(rid, [])).line

    def test_table(self):
        self.assertEqual(self.cls([]), "PR CI: 없음(check-run 없음 — commit status 는 보지 않음)")
        self.assertEqual(CI.record(None, None).line, "PR CI: 없음")
        self.assertEqual(self.cls([{"id": 1, "name": "a", "conclusion": "success"},
                                   {"id": 2, "name": "b", "conclusion": "skipped"},
                                   {"id": 3, "name": "c", "conclusion": "neutral"}]), "PR CI: green")
        self.assertEqual(self.cls([{"id": 1, "name": "a", "conclusion": None}]), "PR CI: 진행 중")
        self.assertEqual(self.cls([{"id": 1, "name": "a", "conclusion": "timed_out"},
                                   {"id": 2, "name": "b", "conclusion": None}]), "PR CI: red a")
        self.assertEqual(self.cls([{"id": 1, "name": "a", "conclusion": "failure", "annotations": 1},
                                   {"id": 2, "name": "b", "conclusion": "cancelled"}],
                                  {1: ["The job was not started because …"]}),
                         "PR CI: red b · 시작되지 않음 a (env: ci-blocked)")

    def test_at_most_three_annotation_reads(self):
        seen = []
        runs = [{"id": i, "name": "r%d" % i, "conclusion": "failure", "annotations": 2} for i in range(5)]
        CI.classify(runs, lambda rid: seen.append(rid) or [])
        self.assertEqual(seen, [0, 1, 2])


class UnattendedLog(unittest.TestCase):
    def test_bare_heading_migrated_once_outside_preserved(self):
        body = "intro\n\n%s\n- old line\n\n## 다음 절\n사람\n" % PB.UNATTENDED_HEADING
        h = Harness(self, fixture(prs=[pr(body=body)]))
        h.decisions.record({"point": "TEST", "stage": "test", "by": "judge:sonnet", "choice": "gap",
                            "unsure": "true", "coerced": "false"})
        self.assertTrue(UL.splice(h.writer, h.gh, 7, 40))
        new = h.gh.fx["prs"][0]["body"]
        self.assertTrue(new.startswith("intro\n\n<!-- guild:unattended-log -->\n%s\n" % PB.UNATTENDED_HEADING))
        self.assertTrue(new.endswith("<!-- /guild:unattended-log -->\n\n## 다음 절\n사람\n"))
        self.assertEqual(new.count(PB.UNATTENDED_HEADING), 1)
        self.assertFalse(UL.splice(h.writer, h.gh, 7, 40))      # idempotent

    def test_entries_skip_human_and_plain_code(self):
        h = Harness(self, fixture())
        h.decisions.record({"point": "applied", "stage": "test", "by": "code", "choice": "x"})
        h.decisions.record({"point": "QA", "stage": "qa", "by": "judge:sonnet", "choice": "block",
                            "coerced": "true", "coerced_by": "rule", "unsure": "false"})
        e = UL.entries(h.gh.comments(7))
        self.assertEqual(len(e), 1)
        self.assertIn("QA → block (coerced:rule)", e[0])


if __name__ == "__main__":
    unittest.main()
