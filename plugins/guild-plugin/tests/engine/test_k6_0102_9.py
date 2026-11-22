"""0.102.9 — the review-0102-8 fixes (M1, M2, m1–m5) through the real code paths (the analyze / execute stages, the
Issue-AC parser on the real word_app #1797 body, `grade.posthoc_rows`, the conservative text trigger). The reviewer's
repros (scratchpad `r0102_8/`) are here as the first tests of each class; each failed on 0.102.8 (`2b628e2`).

Lead decisions (k6-notes "0.102.9"):
1. the Issue-AC check is simple and strict: no similarity — an Issue AC is kept only when the reading's AC carries it
   verbatim (whitespace / markdown / numbering may differ); anything else is dropped → no auto-narrow (a person). An
   Issue with an AC section (broad title detection: any heading level, a bold line, a `title:` line; sub-headings
   inside) that the parser reads 0 AC from → no auto-narrow. Only top-level list items are AC (m4);
2. an unverified KICKOFF that runs post hoc never stops on the AC check — the kept / dropped Issue AC goes on its
   grading-sheet row's reason.
Plus the word_app #1797 loop-back-cap failure on 0.102.7 (classes `R1797*`): one id set for the TEST judge, the covers
and the checks (cases folded into the AC they name), an assertion inside a same-file helper (golden tests), an `unsure`
check carrying its reason, and no loop-back that repeats an earlier one without a test change.
"""
import os
import unittest

import _util  # noqa: F401
import test_k3_execute_stage as K3
import test_k6_0102_7 as T7
import test_k6_0102_8 as T8
from _k2 import decision
from _k3 import XHarness, auditor, dev, finding
from _k4 import K4, evidence, kickoff

from guildcore.roles.runner import RoleResult
from workflows.dev import analysis as AN
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev.stages import analyze as A
from workflows.dev.stages import execute as X

# word_app #1797's body as `gh issue view 1797 --json body` returns it (read-only, 2026-11-22) — the same text as the
# live run's `001-analyze-explorer-kickoff/in/issue.md`
with open(os.path.join(_util.FX, "real", "word_app-1797-body.md"), encoding="utf-8") as _fh:
    BODY_1797_REAL = _fh.read()
AC_1797 = ["설정 화면 '퀴즈 화면' 섹션에 '문제 유형' 항목이 보인다.",
           "항목을 탭하면 복습 화면과 같은 섹션·항목 구성의 선택 시트가 열린다.",
           "설정에서 바꾼 선택이 저장되고, 이후 복습 화면의 선택 시트와 실제 출제에 그대로 반영된다. "
           "반대 방향(복습 → 설정 요약)도 반영된다.",
           "앱을 재시작해도 선택이 유지된다.",
           "새 문자열은 지원하는 모든 언어(ko/en/ja 등)에 번역이 있다. 항목에는 접근성 라벨(`Semantics`)이 있다."]
AC3_CUT = ("설정에서 바꾼 선택이 저장되고, 이후 복습 화면의 선택 시트에 그대로 반영된다. "
           "반대 방향(복습 → 설정 요약)도 반영된다.")


def _narrow(acs):
    return T7._nested({"ac": list(acs)})


# ---- M1: the AC section of #1797 itself, broad titles, an unread section --------------------------------------------

BODY_1797 = ("## 배경 (Why)\n\n복습 문제 유형을 설정 화면에서도.\n\n## 기능 설명 (What)\n\n- 설정 화면에 항목 추가\n\n"
             "## 인수 기준 (초안 — analyze에서 확정)\n\n1. the entry point shows the type\n"
             "2. the fix keeps the summary right\n\n## 확인 필요 (analyze에서 검증)\n\n- exampleReading 불일치\n")


class M1IssueAcSection(unittest.TestCase):
    def test_1797_heading_issue_ac_dropped_is_not_auto_narrowed(self):
        # r0102_8/test_r1
        h, r = T8._analyze(self, T7._nested(), body=BODY_1797)
        self.assertIsNone(T8._kb(h).get("auto_narrow"),
                          "auto-narrow dropped the Issue AC 'the fix keeps the summary right' under '## 인수 기준'")
        self.assertEqual(r.kind, "PAUSE", r.token())

    def test_parser_variants(self):
        # r0102_8/test_r1
        rows = {
            "#1797 인수 기준": ("## 인수 기준 (초안)\n1. a 가 보인다\n", ["a 가 보인다"]),
            "bold heading": ("**수용 기준**\n- a 가 보인다\n", ["a 가 보인다"]),
            "완료 기준": ("## 완료 기준\n- a 가 보인다\n", ["a 가 보인다"]),
            "sub-heading": ("## 受け入れ条件\n### 機能\n- 一覧が並ぶ\n", ["一覧が並ぶ"]),
            "colon line": ("受け入れ条件:\n- 一覧が並ぶ\n", ["一覧が並ぶ"]),
            "受け入れ基準": ("### 受け入れ基準\n- 一覧が並ぶ\n", ["一覧が並ぶ"]),
            "Definition of done": ("#### Definition of Done\n* it ships\n", ["it ships"]),
            "인수 조건 bold colon": ("**인수 조건:**\n- a 가 보인다\n", ["a 가 보인다"]),
        }
        for name, (body, want) in rows.items():
            with self.subTest(case=name):
                self.assertEqual(AN.issue_ac_lines(body), want, name)

    def test_the_real_1797_body_is_read(self):
        has, acs = AN.issue_ac_section(BODY_1797_REAL)
        self.assertTrue(has)
        self.assertEqual(acs, AC_1797)

    def test_a_same_level_heading_ends_the_section_a_deeper_one_does_not(self):
        body = ("## 수용 기준\n- a\n### 화면\n- b\n## 메모\n- not an AC\n**완료 기준**\n- c\n## 다음\n- no\n")
        self.assertEqual(AN.issue_ac_lines(body), ["a", "b", "c"])

    def test_an_ac_section_read_as_empty_is_never_auto_narrowed(self):
        for body in ("## 수용 기준\n설정 화면에 항목이 보이고 요약이 맞다.\n",
                     "**Acceptance criteria**\n\nThe entry point shows the type.\n"):
            with self.subTest(body=body[:20]):
                self.assertEqual(AN.issue_ac_section(body), (True, []))
                h, r = T8._analyze(self, T7._nested(), body=body)
                self.assertIsNone(T8._kb(h).get("auto_narrow"), "an unread AC section was taken as nothing dropped")
                self.assertEqual(r.kind, "PAUSE", r.token())

    def test_no_ac_section_at_all_still_narrows(self):
        h, r = T8._analyze(self, T7._nested(), body="설정 화면에 문제 유형 항목을 추가한다.\n\n## 메모\n- x\n")
        self.assertIsNotNone(T8._kb(h).get("auto_narrow"))

    def test_the_real_1797_scope_cut_asks_and_the_verbatim_copy_narrows(self):
        # D5's narrow reading C leaves the exampleReading part out — AC #3's "와 실제 출제" with it
        cut = AC_1797[:2] + [AC3_CUT] + AC_1797[3:]
        h, r = T8._analyze(self, _narrow(cut), body=BODY_1797_REAL)
        self.assertIsNone(T8._kb(h).get("auto_narrow"), "#1797 AC #3 was cut unasked")
        self.assertEqual(r.kind, "PAUSE", r.token())
        # every Issue AC copied (markdown and numbering may differ) — the narrowest reading is taken
        copy = ["AC #%d: %s" % (n + 1, a.replace("`", "")) for n, a in enumerate(AC_1797)]
        h, r = T8._analyze(self, _narrow(copy), body=BODY_1797_REAL)
        self.assertEqual(T8._kb(h).get("auto_narrow"), "i3", r.token())


# ---- M2: verbatim only — no similarity ------------------------------------------------------------------------------

class M2Verbatim(unittest.TestCase):
    def test_scope_cuts_are_not_covered(self):
        # r0102_8/test_r2
        rows = [(AC_1797[2], AC3_CUT),
                ("When the app language is Korean, every screen shows Korean labels",
                 "When the app language is Korean, the settings screen shows Korean labels"),
                ("Dark mode", "Dark mode is not supported in this change")]
        for a, b in rows:
            with self.subTest(issue_ac=a[:40]):
                self.assertFalse(AN.ac_covered(a, [b]), "a scope-cut AC counted as the Issue AC kept")

    def test_end_to_end_the_cut_ac3_is_not_auto_narrowed(self):
        # r0102_8/test_r2
        k = T7._nested({"ac": ["the entry point shows the type", AC3_CUT]})
        body = "## 수용 기준\n- the entry point shows the type\n- %s\n" % AC_1797[2]
        h, r = T8._analyze(self, k, body=body)
        self.assertIsNone(T8._kb(h).get("auto_narrow"), "AC #3's '실제 출제' was cut unasked")

    def test_only_whitespace_markdown_and_numbering_may_differ(self):
        a = AC_1797[4]
        for same in ("5. " + a, "- [ ] " + a, a.replace("`Semantics`", "**Semantics**"), a.replace(" ", "  "),
                     "**AC #5:** " + a, a.replace(". ", ".\n")):
            with self.subTest(same=same[:30]):
                self.assertTrue(AN.ac_covered(a, [same]))
        for other in (a.rstrip("."), a + " 다크 모드 포함.", a.replace("모든", "주요"), a.upper(),
                      a.replace("(ko/en/ja 등)", "")):
            with self.subTest(other=other[:30]):
                self.assertFalse(AN.ac_covered(a, [other]))

    def test_the_removed_ac_record_is_the_same_strict_check(self):
        # take_narrowest's `dropped_ac`: the judge's chosen AC a light rewording of which the narrow reading carries is
        # recorded as removed
        k = T7._nested({"ac": ["the entry point shows the type", "The fix keeps the summary right."]})
        h, r = T8._analyze(self, k)
        self.assertEqual(T8._kb(h).get("dropped_ac"), "the fix keeps the summary right")


# ---- lead decision 2: an unverified KICKOFF's row names the Issue AC kept / dropped ----------------------------------

class D2UnverifiedKickoffRow(unittest.TestCase):
    def _run(self, acs, body=BODY_1797_REAL):
        k = kickoff(ac=acs)
        h = K4(self, roles=[evidence(self)] * 2, judges={"KICKOFF": k}, body=body)
        h.p._first_sprint = False
        h.p.unverified = frozenset(["KICKOFF"])
        h.p.valves = {}
        r = A.run(h.p)
        kb = h.decisions_of("KICKOFF")[-1]
        rows = [x for x in G.posthoc_rows(T7._blocks(h), 7) if x["decision_id"] == kb.id]
        return h, r, kb, rows

    def test_a_dropped_issue_ac_is_on_the_row_and_never_a_stop(self):
        h, r, kb, rows = self._run(AC_1797[:2] + [AC3_CUT] + AC_1797[3:])
        self.assertNotEqual(r.kind, "PAUSE", r.token())
        self.assertEqual([b for b in T7._blocks(h) if b.get("status") == "pending-human"], [])
        self.assertEqual(kb.get("post_hoc"), "unverified KICKOFF")
        self.assertEqual(len(rows), 1)
        self.assertIn("Issue AC: 4/5 Issue AC kept verbatim; dropped: 설정에서 바꾼 선택이 저장되고, 이후 복습 화면의 "
                      "선택 시트와 실제 출제에", rows[0]["reason"])

    def test_all_kept_and_unread_and_none(self):
        _h, _r, _kb, rows = self._run(AC_1797)
        self.assertIn("Issue AC: 5/5 Issue AC kept verbatim", rows[0]["reason"])
        self.assertNotIn("dropped:", rows[0]["reason"])
        _h, _r, _kb, rows = self._run(("the count shows 3",), body="## 수용 기준\n문단만 있다.\n")
        self.assertIn("Issue AC: the Issue has an AC section but no AC was read", rows[0]["reason"])
        _h, _r, _kb, rows = self._run(("the count shows 3",), body="본문만.\n")
        self.assertIn("Issue AC: the Issue states no AC", rows[0]["reason"])


# ---- m1: the text trigger's false positives / negatives -------------------------------------------------------------

FP = ["Android 카메라 권한 누락으로 촬영 화면이 열리지 않는다", "마이크 권한 확인 없이 녹음 버튼을 누르면 크래시",
      "カメラ権限のチェック漏れでクラッシュする", "비밀번호 입력란에 평문 보기 토글을 추가한다",
      "The password field shows plain text when the eye icon is tapped", "semantic tokens are exposed through ThemeData",
      "컬러 토큰 변경을 커밋한다", "spacing tokens are committed to the design package",
      "Remove hard-coded tokens from the colour palette",
      # 0.102.9: more of the same kinds
      "The camera permission check is missing on Android 14", "位置情報の権限確認なしで地図を開くとクラッシュ",
      "개인정보 처리방침 링크를 설정 화면에 노출한다", "typography tokens are hard-coded in three widgets"]
FN = ["비밀번호를 로그로 출력한다", "パスワードをログ出力している", "API 키가 앱 번들에 포함되어 배포된다",
      "SharedPreferences 에 액세스 토큰을 평문 저장한다", "RLS 정책을 끄면 다른 사용자의 단어장을 읽을 수 있다",
      "他のユーザーのデータが見えてしまう",
      # 0.102.9: personal data to a log, another user's data in English, a missing authorization check still an issue
      "사용자 개인정보를 로그로 출력한다", "個人情報をログに出している", "personal data is printed to the log",
      "a user can read the notes of other users through the API", "API 권한 확인 없이 다른 계정 데이터를 수정할 수 있다",
      "The session token is stored in plain text"]


class m1TextTrigger(unittest.TestCase):
    def test_false_positives(self):
        # r0102_8/test_r3 (+ more of each kind)
        for t in FP:
            with self.subTest(t=t):
                self.assertFalse(CONS.security_text(t))

    def test_false_negatives(self):
        # r0102_8/test_r3 (+ more of each kind)
        for t in FN:
            with self.subTest(t=t):
                self.assertTrue(CONS.security_text(t))


# ---- m2: the auditor's own run dir only ------------------------------------------------------------------------------

RUN = "/Users/x/.cache/guild-engine/h/7/runs/018-execute-auditor-scan"


def _denied(path, tool="Write"):
    return [{"role": "auditor", "command": tool, "class": "tool:%s" % tool, "tool": tool, "path": path}]


class m2AuditorOwnRunDir(unittest.TestCase):
    def test_a_denied_write_elsewhere_with_a_partial_read_is_not_the_write_failure(self):
        # r0102_8/test_r4
        res = RoleResult("DONE_WITH_CONCERNS", "diff.patch 가 커서 앞 2000줄만 읽음 — 나머지 파일은 보지 못함",
                         {"findings": []}, result_source="fence",
                         denials=_denied("/Users/x/projects/.gld-app-7/out/result.json"), run_dir=RUN)
        self.assertIsNone(X.result_write_failed(res), "a partial audit was accepted as the result-write failure")

    def test_only_its_own_run_dirs_result_file(self):
        rows = [(RUN + "/out/result.json", True), (RUN + "/./out/../out/result.json", True),
                (RUN + "/out/result.json", True, "Edit"),
                ("/Users/x/.cache/guild-engine/h/7/runs/017-execute-auditor-scan/out/result.json", False),
                (RUN + "/out/sub/out/result.json", False), (RUN + "/in/out/result.json", False)]
        for row in rows:
            path, ok = row[0], row[1]
            with self.subTest(path=path):
                res = RoleResult("DONE_WITH_CONCERNS", "쓰기 거부", {"findings": []}, result_source="fence",
                                 denials=_denied(path, *(row[2:] or ["Write"])), run_dir=RUN)
                self.assertEqual(bool(X.result_write_failed(res)), ok)
        res = RoleResult("DONE_WITH_CONCERNS", "쓰기 거부", {"findings": []}, result_source="fence",
                         denials=_denied(RUN + "/out/result.json"))
        self.assertIsNone(X.result_write_failed(res), "no run dir known — never accepted")


# ---- m3: a finding marked security is security whatever the top-level field says -----------------------------------

class m3ExArbFindingMark(unittest.TestCase):
    def _run(self, mark, top=False, coerced=False):
        ev = [{"path": "lib/a.dart", "line": 1, "quote": "int a() => 2;"}]
        f = {"findings": [{"id": "F1", "verdict": "dismiss", "reason": "guarded", "evidence": ev, "security": mark}],
             "summary": "s", CONS.SECURITY_FIELD: top, CONS.SECURITY_REASON: "-"}
        scan = [finding("BLOCKER", text="the session cookie lacks the Secure flag")]
        h = XHarness(self, roles=[dev(), K3.TL_DONE, auditor(scan)] + [dev(), K3.TL_DONE, auditor()] * 2,
                     suites=[K3.GREEN] * 6, judges={"EX-ARB": [decision("s", f)]})
        h.p.valves = {}
        h.p.unverified = frozenset(["EX-ARB-dismiss"]) if coerced else frozenset()
        h.p._first_sprint = False
        r = X.run(h.p, "implement")
        return h, r, [b for b in T8._blocks(h) if b.get("point") == "EX-ARB"][0]

    def test_a_finding_marked_security_is_not_dismissed_unasked(self):
        # r0102_8/test_r5
        h, r, ex = self._run(True)
        self.assertNotEqual(ex.get("choice"), "F1:dismiss", "a BLOCKER the judge marked security was dismissed")
        self.assertEqual(ex.get("choice"), "F1:dispute")
        self.assertEqual(ex.get("security"), "F1")
        self.assertEqual(r.cause, "disputed auditor BLOCKER", r.token())

    def test_under_the_coercion_too_and_unmarked_follows_the_top_field(self):
        _h, r, ex = self._run(True, coerced=True)
        self.assertEqual(ex.get("choice"), "F1:dispute")
        _h, r, ex = self._run(False)
        self.assertEqual(ex.get("choice"), "F1:dismiss")      # no concern anywhere, no coercion — the judge's pick
        _h, r, ex = self._run(None)
        self.assertEqual(ex.get("choice"), "F1:dismiss")      # unmarked under a top-level false — the top field rules

    def test_a_marked_finding_sends_the_developer_route_to_a_person(self):
        f = {"findings": [{"id": "F9", "verdict": "accept", "reason": "r", "evidence": [], "security": True}],
             "summary": "s", "developer_route": "reinvoke", "addendum": "정책을 꺼도 된다",
             CONS.SECURITY_FIELD: False, CONS.SECURITY_REASON: "-"}
        h = XHarness(self, roles=[dev("NEEDS_CONTEXT", "RLS 때문에 테스트가 막힘 — 정책을 꺼도 되나?"), dev(), K3.TL_DONE,
                                  auditor(), dev(), K3.TL_DONE, auditor()],
                     suites=[K3.GREEN] * 3, judges={"EX-ARB": [decision("s", f)]})
        r = X.run(h.p, "implement")
        self.assertNotEqual(r.kind, "ADVANCE", r.token())
        self.assertEqual(len([c for c in h.calls["roles"] if c.role == "developer"]), 1)
        self.assertEqual([b.get("choice") for b in T8._blocks(h) if b.get("point") == "developer-route"], ["human"])
        self.assertIn("보안: EX-ARB 가 보안으로 표시한 발견 F9", r.token())


# ---- m4: top-level items only ----------------------------------------------------------------------------------------

class m4TopLevelOnly(unittest.TestCase):
    def test_a_nested_note_is_not_an_issue_ac(self):
        # r0102_8/test_r6
        body = "## 수용 기준\n- the entry point shows the type\n  - 참고: figma 링크 https://example.com/f\n"
        h, r = T8._analyze(self, T7._nested(), body=body)
        self.assertIsNotNone(T8._kb(h).get("auto_narrow"), "a nested note under the AC heading stopped auto-narrow")

    def test_the_parser_takes_the_top_level(self):
        body = ("## Acceptance criteria\n  1. first\n     - note under first\n  2. second\n\t- tab note\n"
                "### Edge\n  - third\n      * deep\n")
        self.assertEqual(AN.issue_ac_lines(body), ["first", "second", "third"])


# ---- m5: the KICKOFF prompt asks for verbatim copies ----------------------------------------------------------------

class m5Prompt(unittest.TestCase):
    def test_the_kickoff_prompt_says_verbatim(self):
        with open(os.path.join(_util.ENGINE, "workflows", "dev", "judges", "KICKOFF.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("VERBATIM (you may change only whitespace, markdown and numbering)", text)
        self.assertIn("copied VERBATIM as its own AC", text)


# ---- word_app #1797 run on 0.102.7: "loop-back cap reached" after two loop-backs ------------------------------------
# D25: C-ids effective, every AC #n uncovered; D26/D40: the golden tests' assertion (in a same-file helper) read as
# "none" (`fail`); D32/D33: every AC #n `unsure` with `check_detail` `AC #n|None|None|None|None` (no cover under the AC
# id — covers were keyed by case id — and the reason not recorded); the loop-backs could not change any of it.

from _k1 import git, repo                                    # noqa: E402
from _k2 import CFG, FLUTTER_GREEN, FLUTTER_RED, Harness, comment, fixture, judge_test, role, suite  # noqa: E402
from guildcore.decisions import DecisionLog                  # noqa: E402
from guildcore.records import loopback as LB                 # noqa: E402
from workflows.dev import cases as CS                        # noqa: E402
from workflows.dev import effective as EFF                   # noqa: E402
from workflows.dev.stages import test as T                   # noqa: E402

with open(os.path.join(_util.FX, "real", "word_app-1797-test-cases.md"), encoding="utf-8") as _fh:
    TC_1797 = _fh.read()
with open(os.path.join(_util.FX, "real", "word_app-1797-golden_test.dart.txt"), encoding="utf-8") as _fh:
    GOLDEN_1797 = _fh.read()
ACS = ["AC #%d" % n for n in range(1, 10)]
TESTFILE = "void main() {\n  testWidgets('t', (tester) async {\n    expect(find.text('a'), findsOneWidget);\n  });\n}\n"


def _case_covers(cases):
    return [{"test": "test/a_test.dart::t", "ac": c, "kind": "guard"} for c in cases]


def _tblocks(h):
    return [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") in ("TEST", "TEST:repair")]


def _stage(case, judges, cases=None, test_cases=TC_1797, more_roles=()):
    cases = ["C%d" % n for n in range(1, 33)] if cases is None else cases
    h = Harness(case, fixture(), roles=[role("DONE", covers=_case_covers(cases), e2e="E2E 불요: 위젯 한정")] +
                list(more_roles),
                judges={"TEST": judges}, suites=[suite(FLUTTER_GREEN)])
    h.write_file("docs/specs/7/test-cases.md", test_cases)
    h.write_file("test/a_test.dart", TESTFILE)
    return h, T.run(h.p)


class R1797aOneIdSet(unittest.TestCase):
    def test_the_real_test_cases_fold_into_their_acs(self):
        units, members, amap = CS.judged_units(TC_1797)
        self.assertEqual(units, ACS)
        self.assertEqual(members["AC #1"], ["C1", "C2"])
        self.assertEqual(members["AC #9"], ["C31", "C32"])
        self.assertEqual(sum(len(v) for v in members.values()), 32)
        cov = CS.rekey_covers([{"test": "x::t", "ac": "C7"}, {"test": "y::u", "ac": "AC3"}], amap)
        self.assertEqual([(c["ac"], c.get("case")) for c in cov], [("AC #3", "C7"), ("AC #3", None)])

    def test_tester_case_covers_and_judge_ac_verdicts_agree(self):
        # D25 shape: the tester maps C-ids, the judge rules on AC ids — no gap, no loop-back
        h, r = _stage(self, [judge_test(ACS)])
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        b = _tblocks(h)[0]
        self.assertEqual(b.get("choice"), "effective:%s;uncovered:none" % ",".join(sorted(ACS)))
        brief = dict(h.calls["judges"][0].brief_parts)
        self.assertIn("Judge exactly these ids (one `ac[]` entry each, no other id): AC #1 (cases C1, C2); ", brief["ac"])
        self.assertIn("AC #1 ← test/a_test.dart::t (guard) [case C1]", brief["covers"])

    def test_a_judge_that_answers_the_cases_is_read_per_ac(self):
        cs = ["C%d" % n for n in range(1, 33)]
        h, r = _stage(self, [judge_test(cs)])
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        self.assertEqual(_tblocks(h)[0].get("choice"), "effective:%s;uncovered:none" % ",".join(sorted(ACS)))

    def test_one_weak_case_makes_its_ac_weak_only(self):
        from _k2 import decision
        f = {"ac": [{"id": "C%d" % n, "covered_by": ["test/a_test.dart::t"], "verdict": "effective", "why": "w"}
                    for n in range(1, 33)], "visual_rows": [], "overall": "gap", "security_concern": False}
        f["ac"][30]["verdict"] = "not_covering"                     # C31 → AC #9
        h, r = _stage(self, [decision("gap", f), judge_test(ACS[:8])],
                      more_roles=[role("DONE", covers=[])])
        weak = [c for c in h.calls["roles"] if c.task == "repair-mapping"]
        self.assertEqual(len(weak), 1)
        self.assertIn("AC #9 (cases C31, C32)", weak[0].inputs["weak-acs.txt"])
        self.assertIn("AC #9", _tblocks(h)[-1].get("choice").split(";uncovered:")[1])

    def test_a_document_without_ac_tags_is_unchanged(self):
        self.assertEqual(CS.judged_units("| C1 | a |\n| C2 | b |\n"), (["C1", "C2"], {}, {}))
        cov = [{"ac": "AC1", "test": "t"}]
        self.assertEqual(CS.rekey_covers(cov, {}), cov)


class R1797bHelperAssertion(unittest.TestCase):
    class _P(object):
        def read_file(self, path):
            return GOLDEN_1797 if path.endswith("golden_test.dart") else None

    def test_the_real_golden_test_is_not_assertion_free(self):
        ref = ("test/features/setting_screen/widgets/setting_in_quiz_screen_section_quiz_type_golden_test.dart::"
               "문제 유형 항목 기준 이미지 요약이 유형 1개 이름이다")
        o, items = EFF.static_check(self._P(), CFG, "AC #1", [{"test": ref, "ac": "AC #1", "kind": "new"}])
        self.assertIsNone(o, o and o.why)
        self.assertEqual(len(items), 1)

    def test_helpers_are_followed_in_the_same_file_only(self):
        code = ("Future<void> _check(WidgetTester t) async {\n  await expectLater(find.byType(A), matchesGoldenFile('a.png'));\n}\n"
                "Future<void> _outer(WidgetTester t) async { await _check(t); }\n"
                "void main() {\n  testWidgets('a', (t) async { await _outer(t); });\n"
                "  testWidgets('b', (t) async { await importedHelper(t); });\n"
                "  testWidgets('c', (t) async { await _noop(t); });\n}\n"
                "Future<void> _noop(WidgetTester t) async { await t.pump(); expect(1, 1); }\n")
        for name, want in (("a", True), ("b", False), ("c", False)):
            with self.subTest(test=name):
                body = EFF.test_body(code, name, "flutter")[0]
                self.assertEqual(EFF.helper_assertion(code, body, "flutter")[0], want)


class R1797cUnsureCarriesItsReason(unittest.TestCase):
    def test_check_detail_names_why(self):
        # AC #9's cases have no cover — the judge (wrongly) says effective; the check is `unsure` WITH its reason
        h, r = _stage(self, [judge_test(ACS)], cases=["C%d" % n for n in range(1, 31)])
        b = _tblocks(h)[0]
        self.assertIn("AC #9|None|None|None|None|no covering test named by the tester", b.get("check_detail"))
        for part in (b.get("check_detail") or "").split(";"):
            self.assertNotEqual(part.split("|")[-1], "None", part)


class R1797dLoopBackWithoutTestChange(unittest.TestCase):
    def _red(self, head_of, extra_commit=None, from_="test", sig="widget shows title,zzz"):
        wt = repo(self, {"lib/a.dart": "a\n", "docs/specs/7/test-cases.md": "| C1 | 제목이 보인다 |\n",
                         "test/a_test.dart": TESTFILE})
        head = git(wt, "rev-parse", "HEAD").strip() if head_of else None
        if extra_commit:
            p = os.path.join(wt, extra_commit)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write("changed\n")
            git(wt, "add", "-A")
            git(wt, "commit", "-qm", "dev")
        blk = LB.render_block(1, from_, "2026-11-15T00:00:00Z", "b", "r", sig, head=head) + \
            "\nconsumed: 2026-11-15T01:00:00Z"
        h = Harness(self, fixture(comments=[comment(LB.render_new_record(blk), 3)]), root=wt, test_cases=None,
                    roles=[role("DONE", covers=_case_covers(["C1"]), e2e="E2E 불요: x")],
                    suites=[suite(FLUTTER_RED, passed=False, rc=1)])
        return h, T.run(h.p)

    def test_the_same_gap_without_a_test_change_stops_with_what_happened(self):
        from guildcore.records import needs_human as NH
        h, r = self._red(True, extra_commit="lib/b.dart")
        self.assertEqual(r.token(), "OK PAUSE: needs-human — loop-back without test change")
        line = NH.from_comments(h.gh.comments(7))[-1].cause_line
        self.assertTrue(line.startswith("defect: loop-back would repeat loop-back 1 — no test file changed since it"),
                        line)

    def test_a_test_change_or_no_recorded_head_is_the_old_path(self):
        _h, r = self._red(True, extra_commit="test/b_test.dart")
        self.assertTrue(r.token().startswith("OK PAUSE: needs-human — stagnant loop-back — "), r.token())
        _h, r = self._red(False)
        self.assertTrue(r.token().startswith("OK PAUSE: needs-human — stagnant loop-back — "), r.token())

    def test_a_new_loop_back_records_its_head(self):
        wt = repo(self, {"lib/a.dart": "a\n", "test/a_test.dart": TESTFILE,
                         "docs/specs/7/test-cases.md": "| C1 | 제목이 보인다 |\n"})
        h = Harness(self, fixture(), root=wt, test_cases=None,
                    roles=[role("DONE", covers=_case_covers(["C1"]), e2e="E2E 불요: x")],
                    suites=[suite(FLUTTER_RED, passed=False, rc=1)])
        r = T.run(h.p)
        self.assertEqual(r.token(), "OK LOOPBACK: execute")
        self.assertEqual(LB.from_comments(h.gh.comments(7)).latest_active().get("head"),
                         git(wt, "rev-parse", "HEAD").strip())

    def test_test_paths(self):
        for x, want in (("test/a_test.dart", True), ("lib/a.dart", False), ("src/a.test.ts", True),
                        ("tests/test_x.py", True), ("docs/specs/7/test-cases.md", True),
                        ("test/features/x/goldens/a.png", True), ("lib/testing_utils.dart", False)):
            with self.subTest(path=x):
                self.assertEqual(T.is_test_path(x), want)


if __name__ == "__main__":
    unittest.main()
