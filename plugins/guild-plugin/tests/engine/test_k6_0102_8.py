"""0.102.8 — the review-0102-7 fixes (M1–M5, m1–m5) through the real code paths (the analyze / execute stages, the
conservative gate's `posthoc`, the Runner's stream reading, `grade.posthoc_rows`, qa's follow-up list). The reviewer's
repros (scratchpad `r0102_7/`) are here as the first test of each class; each failed on 0.102.7 (`e13835c`).

Lead decisions (k6-notes "0.102.8"):
1. every gated / post-hoc judgment group carries `security_concern` + `security_reason` (missing / invalid → ask);
2. an auditor DONE_WITH_CONCERNS is a clean audit ONLY for the result-file write failure with findings from its own
   fence; any other concern → the auditor once more, then a person;
3. auto-narrow is the interpretation choice only — never over a security concern (STAKES or any judgment), never over
   an `unclear` dimension or one whose question is not the reading choice, never when an Issue AC would be dropped
   (checked by code against the Issue body); what the narrow reading removes is recorded.
"""
import os
import unittest

import _util  # noqa: F401
import test_k3_execute_stage as K3
import test_k6_0102_6 as T6
import test_k6_0102_7 as T7
from _k1 import Clock, FakeSpawn, repo, stream_lines, tmpdir
from _k2 import decision
from _k3 import XHarness, auditor, dev, finding
from _k4 import K4, evidence, stakes

from guildcore.decisions import DecisionLog
from guildcore.roles import runner as RR
from guildcore.roles.runner import RoleResult
from workflows.dev import analysis as AN
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev.stages import analyze as A
from workflows.dev.stages import execute as X
from workflows.dev.stages import qa as Q


def _blocks(h, n=7):
    return DecisionLog.load(h.gh.comments(n)).blocks


def _sec_stakes(concern=True, level="high", reason="더 넓은 해석만 토큰 평문 로그 노출을 고친다"):
    f = {"level": level, "local_reversible_reason": "", "cites": [], CONS.SECURITY_REASON: reason}
    if concern is not None:
        f[CONS.SECURITY_FIELD] = concern
    return decision(level, f, by="judge:opus")


def _analyze(case, k, st=None, body="Issue body", unattended=True):
    h = K4(case, roles=[evidence(case, areas=("lib/app", "lib/settings", "lib/theme"))] * 2, extra_files=T7.EXTRA,
           judges={"KICKOFF": k, "STAKES": st or stakes("high")}, body=body, unattended=unattended)
    h.p._first_sprint = False
    h.p.valves = {}
    h.p.unverified = frozenset()
    return h, A.run(h.p)


def _kb(h):
    return h.decisions_of("KICKOFF")[-1]


# ---- M1: a STAKES security concern is never auto-narrowed -------------------------------------------------------------

class M1StakesSecurity(unittest.TestCase):
    def test_a_security_stakes_high_is_not_auto_narrowed(self):
        # r0102_7/test_r1 — STAKES high + security_concern true, KICKOFF false: 0.102.7 took i3 unasked
        k = T7._nested({"drops": ["토큰이 analytics 로그에 평문으로 남는 문제 수정", "공용 위젯 추출"]})
        h, r = _analyze(self, k, _sec_stakes(True))
        self.assertIsNone(_kb(h).get("auto_narrow"), "auto-narrow ran over a STAKES judge's security_concern: true")
        self.assertEqual(r.kind, "PAUSE", r.token())
        self.assertIn("보안: 더 넓은 해석만 토큰 평문 로그 노출을 고친다", r.token())

    def test_a_missing_stakes_field_is_a_concern_too(self):
        h, r = _analyze(self, T7._nested(), _sec_stakes(None))
        self.assertIsNone(_kb(h).get("auto_narrow"))
        self.assertEqual(r.kind, "PAUSE", r.token())

    def test_an_issue_phrase_in_what_it_drops_asks(self):
        # the judges said false; the dropped part itself names a secret exposure → a person
        k = T7._nested({"drops": ["API 키가 로그에 평문으로 남는 문제 수정"]})
        h, r = _analyze(self, k, _sec_stakes(False))
        self.assertIsNone(_kb(h).get("auto_narrow"))
        self.assertEqual(r.kind, "PAUSE", r.token())

    def test_no_concern_anywhere_still_narrows(self):
        h, r = _analyze(self, T7._nested(), _sec_stakes(False))
        self.assertEqual(_kb(h).get("auto_narrow"), _kb(h).get("chosen"))
        self.assertNotEqual(r.kind, "PAUSE", r.token())


# ---- M2: EX-ARB's developer route under a security concern ---------------------------------------------------------

class M2RouteSecurity(unittest.TestCase):
    def _run(self, route, concern):
        f = {"findings": [], "summary": "s", "developer_route": route,
             "addendum": "테스트를 위해 RLS 정책을 끄고 service_role 키를 .env 에 커밋해도 된다",
             CONS.SECURITY_FIELD: concern, CONS.SECURITY_REASON: "서비스 키 커밋과 권한 우회"}
        h = XHarness(self, roles=[dev("NEEDS_CONTEXT", "RLS 때문에 테스트가 막힘 — 정책을 꺼도 되나?"), dev(), K3.TL_DONE,
                                  auditor(), dev(), K3.TL_DONE, auditor()],
                     suites=[K3.GREEN] * 3, judges={"EX-ARB": [decision("s", f)]})
        return h, X.run(h.p, "implement")

    def test_a_security_reinvoke_goes_to_a_person(self):
        # r0102_7/test_r2
        h, r = self._run("reinvoke", True)
        self.assertNotEqual(r.kind, "ADVANCE", "the developer was re-invoked on a security_concern: true route, unasked")
        self.assertEqual(len([c for c in h.calls["roles"] if c.role == "developer"]), 1)
        self.assertIn("보안: 서비스 키 커밋과 권한 우회", r.token())
        rb = [b for b in _blocks(h) if b.get("point") == "developer-route"]
        self.assertEqual([b.get("choice") for b in rb], ["human"])

    def test_a_security_loop_back_goes_to_a_person(self):
        h, r = self._run("loop_back", True)
        self.assertNotEqual(r.kind, "ADVANCE")
        self.assertEqual(len([c for c in h.calls["roles"] if c.role == "developer"]), 1)

    def test_without_a_concern_the_route_runs(self):
        h, r = self._run("reinvoke", False)
        self.assertEqual(r.kind, "ADVANCE", r.token())
        self.assertEqual(len([c for c in h.calls["roles"] if c.role == "developer"]), 2)


# ---- M3: an auditor DONE_WITH_CONCERNS ----------------------------------------------------------------------------

WRITE_DENIED = [{"role": "auditor", "command": "Write", "class": "tool:Write", "tool": "Write",
                 "path": "/runs/018-execute-auditor-scan/out/result.json"}]


def _dwc(line, source="fence", denials=WRITE_DENIED, findings=()):
    return RoleResult("DONE_WITH_CONCERNS", line, {"findings": list(findings)}, result_source=source,
                      denials=list(denials))


class M3AuditorConcern(unittest.TestCase):
    def _run(self, *audits):
        h = XHarness(self, roles=[dev(), K3.TL_DONE] + list(audits), suites=[K3.GREEN])
        r = X.run(h.p, "implement")
        return h, r, [c for c in h.calls["roles"] if c.role == "auditor"]

    def test_a_partial_audit_is_not_a_clean_audit(self):
        # r0102_7/test_r3 — "read only the first 2000 lines" + findings [] advanced as a clean audit on 0.102.7
        part = RoleResult("DONE_WITH_CONCERNS",
                          "diff.patch 가 너무 커서 앞 2000줄만 읽고 감사함 — 나머지 파일은 보지 못함", {"findings": []})
        h, r, audits = self._run(part, auditor())
        self.assertEqual(r.kind, "ADVANCE", r.token())
        self.assertEqual(len(audits), 2, "the partial audit was not dispatched again")
        self.assertEqual([b.get("choice") for b in _blocks(h) if b.get("point") == "auditor-result"], ["redispatch"])

    def test_two_concerned_audits_ask_a_person(self):
        part = RoleResult("DONE_WITH_CONCERNS", "앞부분만 읽음", {"findings": []})
        h, r, audits = self._run(part, part)
        self.assertEqual(r.kind, "PAUSE", r.token())
        self.assertIn("auditor scan concern", r.token())
        self.assertEqual(len(audits), 2)

    def test_the_write_failure_with_fence_findings_is_accepted(self):
        h, r, audits = self._run(_dwc("out/result.json 쓰기 권한이 거부되어 guild-result 블록으로 제출",
                                      findings=[finding("MINOR")]))
        self.assertEqual(r.kind, "ADVANCE", r.token())
        self.assertEqual(len(audits), 1)
        self.assertEqual([b.get("choice") for b in _blocks(h) if b.get("point") == "auditor-result"], ["accepted"])

    def test_either_half_alone_is_not_the_write_failure(self):
        rows = [("findings from a file", _dwc("쓰기 거부", source="file")),
                ("no refused write", _dwc("쓰기 거부", denials=())),
                ("another tool refused", _dwc("쓰기 거부", denials=[dict(WRITE_DENIED[0], tool="Bash",
                                                                         path=None, command="cat x")]))]
        for name, res in rows:
            with self.subTest(case=name):
                h, r, audits = self._run(res, auditor())
                self.assertEqual(len(audits), 2, name)
                self.assertEqual(X.result_write_failed(res), None)

    def test_the_runner_reads_the_refused_write_and_the_fence(self):
        # the #1797 run 018/020 stream: Write of out/result.json refused, the result in a guild-result block
        wt = repo(self, {"lib/a.dart": "a\n"})
        runs = os.path.join(tmpdir(self), "runs")
        text = (">>> RESULT <<<\nDONE_WITH_CONCERNS: out/result.json 쓰기 권한 거부 — guild-result 블록으로 제출\n"
                "```guild-result\n{\"findings\": []}\n```")
        st = stream_lines(texts=[text], tool_uses=[{"id": "t1", "name": "Write",
                                                    "input": {"file_path": runs + "/x/out/result.json",
                                                              "content": "{}"}}],
                          denials=[{"tool_use_id": "t1", "message": "denied"}])
        r = RR.Runner(journal=T6.EvJournal(), parent_env={"PATH": os.environ["PATH"]}, spawn=FakeSpawn([{"stream": st}]),
                      user_settings=os.path.join(tmpdir(self), "u"), run_root_dir=runs, claude="claude", clock=Clock())
        res = r.run_role(RR.RoleSpec("auditor", "scan", "audit", issue=1, stage="execute", step="X3.5a", worktree=wt,
                                     model="sonnet", remote_check=False,
                                     result_schema={"type": "object", "required": ["findings"],
                                                    "properties": {"findings": {"type": "array"}}}))
        self.assertEqual(res.status, "DONE_WITH_CONCERNS", res.line)
        self.assertEqual(res.result_source, "fence")
        self.assertTrue(X.result_write_failed(res), res.denials)


# ---- M4: what auto-narrow removes is on record, and an Issue AC is never dropped ------------------------------------

class M4NarrowRecord(unittest.TestCase):
    def test_the_removed_ac_is_recorded_and_the_row_names_the_reading(self):
        # r0102_7/test_r6
        h, r = _analyze(self, T7._nested())
        kb = _kb(h)
        self.assertIsNotNone(kb.get("auto_narrow"))
        self.assertEqual(kb.get("dropped_ac"), "the fix keeps the summary right")
        self.assertTrue(kb.get("judge_chosen"))
        self.assertNotEqual(kb.get("judge_chosen"), kb.get("auto_narrow"))
        out = h.body_with("analyze:output")
        self.assertIn("### 후속 Issue 후보", out)
        self.assertIn("(빠진 AC) the fix keeps the summary right", out)
        row = [x for x in G.posthoc_rows(T7._blocks(h), 7) if x["decision_id"] == kb.id][0]
        self.assertIn("took reading %s" % kb.get("auto_narrow"), row["reason"])
        self.assertIn("judge chose %s" % kb.get("judge_chosen"), row["reason"])
        self.assertIn("dropped AC: the fix keeps the summary right", row["reason"])
        self.assertIn("exampleReading 불일치 수정", row["reason"])

    def test_an_issue_ac_the_narrow_reading_drops_asks(self):
        body = ("설정 화면에 문제 유형 항목\n\n## Acceptance criteria\n- [ ] The entry point shows the type.\n"
                "- [ ] the fix keeps the summary right\n\n## Notes\n- not an AC\n")
        h, r = _analyze(self, T7._nested(), body=body)
        self.assertIsNone(_kb(h).get("auto_narrow"), "an AC the Issue states was dropped unasked")
        self.assertEqual(r.kind, "PAUSE", r.token())

    def test_the_judges_keeps_issue_ac_alone_is_not_trusted(self):
        body = "AC #1: the entry point shows the type\nAC #2: 요약이 정확히 유지된다\n"
        h, r = _analyze(self, T7._nested({"keeps_issue_ac": True}), body=body)
        self.assertIsNone(_kb(h).get("auto_narrow"))

    def test_issue_acs_the_narrow_reading_keeps_go_on(self):
        body = "## 수용 기준\n- the entry point shows the type\n\n## 메모\n- the fix keeps the summary right\n"
        h, r = _analyze(self, T7._nested(), body=body)
        self.assertIsNotNone(_kb(h).get("auto_narrow"))

    def test_issue_ac_lines(self):
        body = ("> ## Acceptance criteria\n> - quoted\n\n### 受け入れ条件\n1. 一覧に表示される\n- [x] 保存できる\n"
                "### 背景\n- no\nAC #3: last one\n")
        self.assertEqual(AN.issue_ac_lines(body), ["一覧に表示される", "保存できる", "last one"])
        self.assertTrue(AN.ac_covered("The entry point shows the type.", ["the entry point shows the type"]))
        self.assertFalse(AN.ac_covered("the fix keeps the summary right", ["the entry point shows the type"]))


# ---- M5: only the reading choice is auto-narrowed ------------------------------------------------------------------

class M5ReadingChoiceOnly(unittest.TestCase):
    def test_an_unclear_dimension_is_not_auto_narrowed(self):
        # r0102_7/test_r7
        k = T7._nested()
        k.fields["readiness"]["constraint"]["rating"] = "unclear"
        h, r = _analyze(self, k)
        kb = _kb(h)
        self.assertIn("constraint=unclear", kb.get("choice") or "")
        self.assertIsNone(kb.get("auto_narrow"), "an unclear dimension was auto-narrowed unattended")
        self.assertEqual(r.kind, "PAUSE", r.token())

    def test_a_dimension_whose_question_is_not_the_reading_asks(self):
        k = T7._nested()
        k.fields["readiness"]["constraint"]["about_readings"] = False
        h, r = _analyze(self, k)
        self.assertIsNone(_kb(h).get("auto_narrow"))
        self.assertEqual(r.kind, "PAUSE", r.token())
        k = T7._nested()
        k.fields["readiness"]["constraint"].pop("about_readings")
        h, r = _analyze(self, k)
        self.assertIsNone(_kb(h).get("auto_narrow"))

    def test_the_stakes_level_stays_on_its_block(self):
        h, r = _analyze(self, T7._nested(), _sec_stakes(False))
        self.assertEqual([b.get("choice") for b in h.decisions_of("STAKES")], ["high"])
        self.assertIn("stakes high → auto-narrow", h.body_with("analyze:output"))


# ---- m1: every post-hoc group reads the field ----------------------------------------------------------------------

class _P(object):
    valves = {}
    unverified = frozenset(CONS.GATED)


class _S(object):
    def __init__(self, group, parts):
        self.group, self.brief_parts, self.point = group, parts, group


ISSUE = "로그인 요청이 비밀번호를 평문으로 서버 로그에 남긴다 (보안 문제) — 고칠 것"


class m1EveryGroup(unittest.TestCase):
    def test_the_same_security_text_asks_in_every_post_hoc_group(self):
        # r0102_7/test_r4 — HANDOFF / INTEGRATE had no field: they ran post hoc
        qa = _S("QA", [("qa", "QA report: " + ISSUE), ("candidates", "-")])
        self.assertFalse(CONS.posthoc(_P(), "QA", qa))
        for g, parts, ch in (("HANDOFF", [("boundary", "design→execute"), ("issue", ISSUE)], "ok_with_assumption"),
                             ("INTEGRATE", [("issue", ISSUE)], "clean")):
            with self.subTest(group=g):
                self.assertFalse(CONS.posthoc(_P(), g, _S(g, parts), decision=decision(ch, {"verdict": ch})))

    def test_every_gated_group_true_missing_invalid_false(self):
        for g in CONS.GATED:
            with self.subTest(group=g):
                s = _S(g, [])
                for val, want in ((True, False), (None, False), ("false", False), (False, True)):
                    f = {} if val is None else {CONS.SECURITY_FIELD: val}
                    self.assertEqual(CONS.posthoc(_P(), g, s, decision=decision("x", f)), want, (g, val))
        self.assertEqual(set(CONS.SECURITY_FIELD_GROUPS), set(CONS.GATED) | {"KICKOFF", "EX-ARB"})


# ---- m2: the text trigger and the reason on the question -----------------------------------------------------------

FP = ["render the description as plain text instead of HTML", "마크다운 대신 평문으로 표시",
      "네트워크가 취약한 환경에서 재시도", "脆弱なテストを安定化する", "the design tokens are exposed through ThemeData",
      "디자인 토큰 변경을 커밋", "the token count is logged for debugging"]
FN = ["SQLインジェクションの恐れがある", "검색어가 SQL 인젝션에 열려 있다", "他人の注文を閲覧できる認可漏れ",
      "권한 검사 누락으로 다른 사용자 데이터 조회 가능", "path traversal in the upload handler",
      "IDOR: any user can read another user's orders", "open redirect after login",
      "remote code execution via eval of user input"]


class m2TextTrigger(unittest.TestCase):
    def test_false_positives(self):
        # r0102_7/test_r5
        self.assertEqual([t for t in FP if CONS.security_text(t)], [])

    def test_false_negatives(self):
        self.assertEqual([t for t in FN if not CONS.security_text(t)], [])

    def test_the_reason_comes_from_what_triggered(self):
        spec = _S("QA", [("qa", "QA report: API 키가 로그에 평문으로 기록됨"), ("candidates", "-")])
        quiet = decision("pass", {CONS.SECURITY_FIELD: False, CONS.SECURITY_REASON: "해당 없음"})
        self.assertTrue(CONS.security(spec, quiet))
        self.assertEqual(CONS.security_why(spec, quiet), "입력에 보안 사안")
        loud = decision("pass", {CONS.SECURITY_FIELD: True, CONS.SECURITY_REASON: "키 노출"})
        self.assertEqual(CONS.security_why(spec, loud), "키 노출")


# ---- m3: the EX-ARB security BLOCKER rule under the unverified coercion ---------------------------------------------

class m3ExArbUnderCoercion(unittest.TestCase):
    def _run(self, concern, sec_mark=True):
        ev = [{"path": "lib/a.dart", "line": 1, "quote": "int a() => 2;"}]
        f = {"findings": [{"id": "F1", "verdict": "dismiss", "reason": "guarded", "evidence": ev, "security": sec_mark},
                          {"id": "F2", "verdict": "dismiss", "reason": "fine", "evidence": ev, "security": False}],
             "summary": "s", CONS.SECURITY_FIELD: concern, CONS.SECURITY_REASON: "API 키 로그 노출"}
        scan = [finding("BLOCKER", text="the API key is written to the log"),
                finding("BLOCKER", line=2, text="returns the wrong value")]
        h = XHarness(self, roles=[dev(), K3.TL_DONE, auditor(scan)] + [dev(), K3.TL_DONE, auditor()] * 2,
                     suites=[K3.GREEN] * 6, judges={"EX-ARB": [decision("s", f)]})
        h.p.valves = {}
        h.p.unverified = frozenset(["EX-ARB-dismiss"])
        return h, X.run(h.p, "implement")

    def test_a_security_blocker_goes_to_a_person_and_the_others_follow_the_coercion(self):
        h, r = self._run(True)
        self.assertEqual(r.cause, "disputed auditor BLOCKER", r.token())
        ex = [b for b in _blocks(h) if b.get("point") == "EX-ARB"][0]
        self.assertEqual(ex.get("choice"), "F1:dispute,F2:accept")
        self.assertEqual(ex.get("security"), "F1")

    def test_an_unmarked_finding_counts_as_security(self):
        h, r = self._run(True, sec_mark=None)
        self.assertEqual(r.cause, "disputed auditor BLOCKER", r.token())

    def test_without_a_concern_every_dismiss_is_coerced_to_accept(self):
        h, r = self._run(False)
        ex = [b for b in _blocks(h) if b.get("point") == "EX-ARB"][0]
        self.assertEqual(ex.get("choice"), "F1:accept,F2:accept")
        self.assertIsNone(ex.get("security"))


# ---- m4: the PR title prefix ---------------------------------------------------------------------------------------

class m4PrTitle(unittest.TestCase):
    def test_no_space_and_the_full_width_colon(self):
        for t, want in (("fix:missing space", "fix:missing space"), ("fix：全角", "fix：全角"),
                        ("feat(kanji)：획순", "feat(kanji)：획순"), ("fix : spaced", "fix : spaced"),
                        ("Note: a", "feat: Note: a"), ("fixes: a", "feat: fixes: a"),
                        ("fix://not a prefix", "feat: fix://not a prefix")):
            self.assertEqual(X.pr_title("implement", t), want, t)
        self.assertEqual(X.pr_title("debug", "feat: x"), "feat: x")   # recorded: the Issue's own type is kept


# ---- m5: follow-ups recorded without design output -----------------------------------------------------------------

class m5FollowUps(unittest.TestCase):
    def test_narrowed_follow_ups_are_listed_without_design_output(self):
        k = T7._nested({"drops": ["exampleReading 불일치 수정 ;; 같은 줄", "공용 위젯 추출"]})
        h, r = _analyze(self, k)
        self.assertIsNotNone(_kb(h).get("auto_narrow"))
        self.assertFalse(any(h.p.exists("docs/specs/7/%s" % f) for f in Q.DESIGN_ARTIFACTS))
        h.gh.issue_search = lambda *a, **kw: []
        fu = Q._followups(h.p, {}, RoleResult("DONE", "x", {}), h.gh.comments(7), None)
        self.assertTrue(fu["run"])
        self.assertEqual([i.title for i in fu["items"]], ["exampleReading 불일치 수정 ; 같은 줄", "공용 위젯 추출",
                                                         "AC: the fix keeps the summary right"])


if __name__ == "__main__":
    unittest.main()
