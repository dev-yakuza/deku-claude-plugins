"""review-k6-r1 — the fixes, each over every gated group / option where the finding is structural.

M1  a safe answer (`stop`, the group's conservative choice) is never re-judged, retired or re-asked: `stop` holds on
    any run, the conservative choice applies with no judge call (table: every GATED group × its safe answers);
M2  a question at a decision point that already had an answer (`:a<k>` — after an applied or a `stale` answer) is
    never a counted blind judgment (`predict_first_counted: false — after-reveal`), neither `ok` nor candidate
    (table: every GATED group); the DE-ARB stale-then-re-ask case;
M3  the answer applies when the judge now picks the person's option or the one asked about (no re-ask); a clone
    without the tape whose live roles report in other words keeps the answer (the brief is never compared there);
m2  volatile tokens (elapsed times, clocks, temp paths) do not make another run;
m3  "the same answer twice" needs the earlier answer APPLIED and replaced by a rule — not one retired `stale`;
M4  blind labels: asides always cut, heads only when they still tell the options apart (KICKOFF end to end);
M5/m7 the grader: the AC never grounds `ok`; call ① of an analyze decision has no AC;
M6  every §9.5 group has a release path or is exempt with a reason; EX-ARB-dismiss releases on sheet verdicts;
    the conservative source is named as a person can act on it;
m1  no release while a wrong candidate of the group is open; a wrong after the release is still shown;
m4  the dual judgment never doubles a helper judge;
m5  the first-sprint centre asks only non-conservative choices, a group's first `release_after`;
m8  a person's label removal resets the L0-ESCALATE count;
decision 4  the dual judgment is on by default from the first sprint.
"""

import copy
import json
import os
import tempfile
import unittest

import _util  # noqa: F401
import test_k5_r9 as R9
import test_k5_r10 as R10
from _k1 import Clock, tmpdir
from _k2 import role
from test_k2_qa_stage import qa_harness

from guildcore import ask as ASK
from guildcore import config as CFG
from guildcore import journal as J
from guildcore import valves as VALVES
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Decision
from guildcore.records.decisions import DecisionBlock
from workflows.dev import centre as CE
from workflows.dev import conservative as CONS
from workflows.dev import dual as DUAL
from workflows.dev import grade as G
from workflows.dev import grader as GD
from workflows.dev import judging as JG
from workflows.dev import predict as PF
from workflows.dev import unverified as UV
from workflows.dev.stages import base as B
from workflows.dev.stages import qa as Q
from workflows.dev.stages.base import StageResult


def _blocks(h):
    return DecisionLog.load(h.gh.comments(7)).blocks


def _pending(h):
    return [b for b in _blocks(h) if b.get("kind") == CONS.KIND and b.get("status") == "pending-human"]


def _stale(h):
    return [b for b in _blocks(h) if b.get("point") == CONS.STALE]


def _h(case):
    h = qa_harness(case, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 8)
    h.p.git_dir = None
    h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r1-"), 7, h.clock)
    CONS._MEM.clear()
    return h


def _nonsafe(g):
    return [o for o in (R10.SHAPES.get(g) or {}) if o not in CONS.safe_answers(g)]


class _Judge(object):
    """The group's judge: choice `y` with its R10 shape; counts its calls."""

    def __init__(self, g, y):
        self.g, self.y, self.calls = g, y, 0

    def __call__(self, spec):
        self.calls += 1
        return R9.runner_judge(self.g, R10.shape_of(self.g, self.y), self.y)(spec)


def _run(h, g, issue_text, judge, raw="00:03 +12: All tests passed! (1.2s)"):
    """One stage run of the point: a role call whose inputs are the Issue text and a suite output, then the gate."""
    CONS.begin(h.p)
    CONS.role(h.p, B.RoleCall("tester", "verify", "qa", "R1", inputs={"issue.md": issue_text, "raw-output.txt": raw}),
              lambda c: role("DONE", line="ok", plan="qa-report.md", human_items=[], followups=[]))
    return CONS.gate(h.p, JG.spec(h.p, g, [("brief", "brief of " + issue_text)], "qa", "S1"), judge)


def _ask(h, g, issue_text, judge):
    try:
        _run(h, g, issue_text, judge)
    except CONS.Ask as a:
        CONS.surface(h.p, "qa", a)
        return a.question
    raise AssertionError("%s: no question" % g)


def _answer(h, choice):
    ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, choice, journal=h.p.journal)


class M1SafeAnswers(unittest.TestCase):
    """Every GATED group × every safe answer: asked on the judge's non-conservative choice, answered safe, the run
    that applies it is ANOTHER run (the Issue text changed) and the judge would now choose otherwise."""

    def test_table(self):
        seen = 0
        for g in CONS.GATED:
            ys = _nonsafe(g)
            self.assertTrue(ys, "%s has no non-conservative option in the R10 shapes" % g)
            for x in sorted(CONS.safe_answers(g)):
                with self.subTest(group=g, answer=x):
                    h = _h(self)
                    h.p.valves = {"group.%s.conservative" % g: True}
                    _ask(h, g, "v1", _Judge(g, ys[0]))
                    _answer(h, x)
                    other = _Judge(g, ys[-1] if len(ys) > 1 else ys[0])
                    try:
                        d = _run(h, g, "v1\ncomment: edited after the answer", other)
                        held = False
                    except CONS.Hold:
                        held, d = True, None
                    self.assertEqual(other.calls, 0, "a safe answer re-judged")
                    self.assertEqual(_stale(h), [])
                    if x == "stop":
                        self.assertTrue(held)
                    else:
                        self.assertFalse(held)
                        self.assertEqual((d.by, d.choice), ("human", x))
                    seen += 1
        self.assertGreaterEqual(seen, len(CONS.GATED))

    def test_safe_answers_are_stop_and_the_unsure_choice(self):
        for g in CONS.GATED:
            want = set(["stop"]) | (set([JG.UNSURE[g]]) if JG.UNSURE.get(g) else set())
            self.assertEqual(set(CONS.safe_answers(g)), want)


class M2AfterReveal(unittest.TestCase):
    def _counted(self, h):
        return G.predict_first_judgments(_blocks(h), 7)

    def test_every_group_reasked_point_is_uncounted(self):
        for g in CONS.GATED:
            y = _nonsafe(g)[0]
            with self.subTest(group=g):
                h = _h(self)
                h.p.valves = {"group.%s.conservative" % g: True}
                q1 = _ask(h, g, "v1", _Judge(g, y))
                self.assertTrue(q1.predict_first)
                _answer(h, y)
                d = _run(h, g, "v1", _Judge(g, y))                      # the same run: applies
                self.assertEqual(d.by, "human")
                CONS.flush(h.p)
                q2 = _ask(h, g, "v1", _Judge(g, y))                     # re-entered: a new point
                self.assertTrue(str(q2.refs).endswith(":a1"))
                self.assertTrue(q2.after_reveal)
                blk = _pending(h)[-1]
                # blind → marked uncounted; or the decision log's earlier answer already refused the blind (open)
                self.assertTrue(str(blk.get("predict_first_counted")).startswith("false — after-reveal")
                                or blk.get("predict_first_refused"), blk.fields)
                _answer(h, y)
                ok, cands = self._counted(h)
                self.assertEqual([r["decision_id"] for r in ok + cands], [_pending(h)[0].id],
                                 "only the first (blind) answer of the point is a §9.5 judgment")

    def test_dearb_stale_then_reask_is_uncounted(self):
        h = _h(self)
        h.p.valves = {"group.DE-ARB.conservative": True}
        _ask(h, "DE-ARB", "v1", _Judge("DE-ARB", "reinvoke"))
        _answer(h, "decide")
        # the Issue changed; the judge now picks neither `decide` nor `reinvoke` → retired, asked again
        with self.assertRaises(CONS.Ask) as cm:
            _run(h, "DE-ARB", "v2 (edited)", _Judge("DE-ARB", "escalate"))
        self.assertEqual(len(_stale(h)), 1)
        CONS.surface(h.p, "qa", cm.exception)
        blk = _pending(h)[-1]
        self.assertTrue(str(blk.get("refs")).endswith(":a1"))
        self.assertTrue(blk.get("recommended_sha"))                      # still blind …
        self.assertTrue(str(blk.get("predict_first_counted")).startswith("false — after-reveal"))   # … never counted
        _answer(h, "reinvoke")                                           # ≠ the hidden `escalate`
        ok, cands = G.predict_first_judgments(_blocks(h), 7)
        self.assertNotIn(blk.id, [r["decision_id"] for r in ok + cands])


class M3AnswerStillApplies(unittest.TestCase):
    def test_the_judge_now_agrees_with_the_person(self):
        h = _h(self)
        h.p.valves = {"group.SPLIT.conservative": True}
        _ask(h, "SPLIT", "v1", _Judge("SPLIT", "single"))
        _answer(h, "split")
        j = _Judge("SPLIT", "split")
        d = _run(h, "SPLIT", "v2 (edited)", j)
        self.assertEqual((d.choice, d.by, j.calls), ("split", "human", 1))
        self.assertEqual(_stale(h), [])
        self.assertEqual(len(_pending(h)), 1)

    def test_the_judge_still_says_what_was_asked(self):
        h = _h(self)
        h.p.valves = {"group.STAKES.conservative": True}
        _ask(h, "STAKES", "v1", _Judge("STAKES", "low"))
        _answer(h, "medium")
        d = _run(h, "STAKES", "v2 (edited)", _Judge("STAKES", "low"))   # blind block: `was` from the revealed rec
        self.assertEqual((d.choice, d.by), ("medium", "human"))
        self.assertEqual(_stale(h), [])

    def test_remote_clone_with_live_roles_in_other_words(self):
        judge = lambda s: Decision("pass", {"defects": [], "checklist": [], "verdict": "pass",  # noqa: E731
                                            "quality_bar_met": "yes"}, "judge:sonnet", "dg")
        roles = [role("DONE", line="qa: 12 widget tests green", plan="qa-report.md", human_items=[], followups=[]),
                 role("DONE", line="qa: all 12 widget tests pass", plan="qa-report.md", human_items=[], followups=[])]
        h = qa_harness(self, unattended=False, roles=roles * 3, judges={"QA": judge})
        h.p.valves = {"group.QA.conservative": True}
        h.p.git_dir = None
        h.p.journal = None
        CONS._MEM.clear()
        g = lambda: CONS.guarded(h.p, "qa", lambda: Q.run(h.p, diff_paths=[]))  # noqa: E731
        self.assertEqual(g().kind, StageResult.ASK)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, "pass")
        CONS._MEM.clear()                                                # another clone: only the GitHub block
        self.assertEqual(g().kind, StageResult.DONE)
        self.assertEqual(_stale(h), [])
        self.assertEqual(len(_pending(h)), 1)


class M2VolatileTokens(unittest.TestCase):
    def test_timings_are_not_another_run(self):
        h = _h(self)
        h.p.valves = {"group.TEST.conservative": True}
        CONS.begin(h.p)
        try:
            _run(h, "TEST", "v1", _Judge("TEST", "all_effective"), raw="00:03 +12: All tests passed! (1.2s) /tmp/abc1/x")
        except CONS.Ask as a:
            CONS.surface(h.p, "qa", a)
        _answer(h, "all_effective")
        CONS._MEM.clear()
        later = _Judge("TEST", "all_effective")
        d = _run(h, "TEST", "v1", later, raw="00:07 +12: All tests passed! (2.9s) /tmp/zz9q/x")
        self.assertEqual((d.by, later.calls), ("human", 0))             # remote, roles match → no judge call

    def test_normalise(self):
        a = CONS.normalise("2026-11-19T10:00:01Z 00:03 +12 took 1.25s pid 4242 /private/var/folders/x/y z")
        b = CONS.normalise("2026-11-20T11:30:59Z 01:13 +12 took 13ms pid 77 /tmp/q z")
        self.assertEqual(a, b)
        self.assertNotEqual(CONS.normalise("+12 tests"), CONS.normalise("+13 tests"))


class M3GroundsTwice(unittest.TestCase):
    def test_previous_answer_retired_stale_is_not_the_same_answer_twice(self):
        h = _h(self)
        h.p.valves = {"group.DE-ARB.conservative": True}
        no_assumption = lambda c: {"assumption": ""}                    # noqa: E731
        reinvoke = lambda: R9.runner_judge("DE-ARB", R10.shape_of("DE-ARB", "reinvoke"), "reinvoke")  # noqa: E731
        _ask(h, "DE-ARB", "v1", reinvoke())
        _answer(h, "decide")
        with self.assertRaises(CONS.Ask) as cm:                         # retired stale (never applied), asked again
            _run(h, "DE-ARB", "v2", _Judge("DE-ARB", "escalate"))
        CONS.surface(h.p, "qa", cm.exception)
        _answer(h, "decide")
        d = _run(h, "DE-ARB", "v2", R9.runner_judge("DE-ARB", no_assumption, "escalate"))
        self.assertEqual((d.by, getattr(d, "human_choice", None)), ("human", "decide"))   # coerced, no NeedGrounds

    def test_applied_block_records_the_rule(self):
        h = _h(self)
        h.p.valves = {"group.DE-ARB.conservative": True}
        _ask(h, "DE-ARB", "v1", _Judge("DE-ARB", "reinvoke"))
        _answer(h, "decide")
        d = _run(h, "DE-ARB", "v1", _Judge("DE-ARB", "reinvoke"))     # the same run: the taped reinvoke fields
        self.assertEqual(getattr(d, "human_choice", None), "decide")
        CONS.flush(h.p)
        ap = [b for b in _blocks(h) if b.get("point") == "applied"]
        self.assertEqual(len(ap), 1)
        self.assertTrue(str(ap[0].get("coerced_to")).startswith(d.choice))
        self.assertTrue(CONS._applied_coerced(h.p, "conservative:DE-ARB:#7:qa:S1:L0"))


HELD_OUT_R1 = (   # review-k6-r1 heldout_labels.py — a regression set (never used to tune a word list)
    "로그인만 (제목이 말하는 범위)", "앱 전체 (설명이 뜻하는 바)", "로그인만 (요청자가 원한 것)", "앱 전체 (이슈 의도에 가까움)",
    "로그인만 (제목과 들어맞음)", "앱 전체 (본문과 거리가 있음)", "로그인만 (요청 범위 안)", "앱 전체 (요청 범위 밖)",
    "로그인만 (제목 문구대로)", "앱 전체 (과한 해석)", "로그인만 (자연스러운 해석)", "앱 전체 (억지스러운 해석)",
    "ログインのみ（タイトルが示す範囲）", "アプリ全体（依頼の意図に近い）", "ログインのみ（本文の趣旨どおり）", "アプリ全体（拡大解釈）",
    "ログインのみ（依頼者の求めるもの）", "アプリ全体（説明とずれる）", "ログインのみ（自然な読み）", "アプリ全体（やりすぎ）",
    "Login only (what the title says)", "Whole app (what the reporter meant)", "Login only (closer to the intent)",
    "Whole app (overreaches the request)", "Login only (within the requested scope)", "Whole app (outside what was asked)",
    "Login only (the natural reading)", "Whole app (a stretched reading)", "Login only (as the title states)",
    "Whole app (reads more into it than written)", "Login only (narrow but safe)", "Whole app (more than needed)",
)


class M4Labels(unittest.TestCase):
    def test_asides_never_shown(self):
        for s in HELD_OUT_R1:
            with self.subTest(label=s):
                self.assertIn(PF.neutral_label(s), ("로그인만", "앱 전체", "ログインのみ", "アプリ全体", "Login only", "Whole app"))

    def test_heads_when_they_tell_options_apart(self):
        self.assertEqual(PF.blind_labels(["export function, safe choice", "quiz module: risky interpretation"]),
                         ["export function", "quiz module"])
        # the heads collide → the per-label form (tails that do not rate are kept)
        self.assertEqual(PF.blind_labels(["알림, 푸시만", "알림, 이메일만"]), ["알림, 푸시만", "알림, 이메일만"])
        # an unclosed aside (the one-line cap cut it) goes too
        self.assertEqual(PF.neutral_label("앱 전체 (설명이 뜻하는…"), "앱 전체")

    def test_same_head_different_asides_refuse_blind(self):
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])])
        h.p._first_sprint = False
        q = ASK.Question("interpretation-surface", "어느 해석?", [{"token": "i1", "label": "알림 (푸시)"},
                                                             {"token": "i2", "label": "알림 (이메일)"},
                                                             {"token": "stop", "label": "stop"}],
                         recommended="i1", recommended_by="judge:opus", raised_by="confirm",
                         neutral=PF.neutral_text("interpretation", 7))
        PF.apply(h.p, q, "analyze")
        self.assertFalse(q.neutralized)                                   # refused: never a counted blind answer
        self.assertTrue(q.blind_refused)

    def test_kickoff_pairs_go_out_without_the_remark(self):
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])])
        h.p._first_sprint = False
        for a, b in (("로그인만 (자연스러운 해석)", "앱 전체 (과한 해석)"),
                     ("ログインのみ（本文の趣旨どおり）", "アプリ全体（拡大解釈）"),
                     ("Login only (within the requested scope)", "Whole app (overreaches the request)"),
                     ("login screen only, as it is the minimal viable interpretation", "the whole app, being far more than asked for")):
            q = ASK.Question("interpretation-surface", "어느 해석?", [{"token": "i1", "label": a}, {"token": "i2", "label": b},
                                                                 {"token": "stop", "label": "stop"}],
                             recommended="i1", recommended_by="judge:opus", raised_by="confirm",
                             neutral=PF.neutral_text("interpretation", 7))
            PF.apply(h.p, q, "analyze")
            shown = dict((o["token"], o["label"]) for o in q.options)
            with self.subTest(pair=(a, b)):
                self.assertTrue(q.neutralized)
                for full, s in ((a, shown["i1"]), (b, shown["i2"])):
                    self.assertTrue(len(s) < len(full) and full.startswith(s), (full, s))

    def test_kickoff_schema_has_a_rationale(self):
        sch = JG.schema("KICKOFF")
        item = sch["properties"]["interpretations"]["items"]
        self.assertIn("rationale", item["properties"])
        self.assertNotIn("rationale", item.get("required", []))


AC = "AC #1: 설정 화면의 다크 모드 토글이 앱 재시작 후에도 유지된다\nAC #2: 토글 변경 즉시 모든 화면 색이 바뀐다"


class M5Grader(unittest.TestCase):
    def _grade(self, cites, group="QA", block=None, ac=AC, evidence="(none collected)"):
        seen = []

        def judge(spec):
            seen.append(dict(spec.brief_parts))
            if spec.choice_key == "choice":
                return Decision("pass", {"choice": "pass", "reason": "r", "cited_evidence": []}, "judge:opus", "g1")
            return Decision("ok", {"given_info": "ok", "outcome": "consistent", "reason": "r",
                                   "cited_evidence": cites}, "judge:opus", "g2")
        blk = DecisionBlock(3, list((block or {"point": group, "stage": "qa", "by": "judge:sonnet", "choice": "pass",
                                                "refs": "Q2.5"}).items()))
        return GD.grade(judge, blk, 7, group, evidence, issue_text="다크 모드", ac=ac), seen

    def test_ac_alone_never_grounds_ok(self):
        row, _s = self._grade(["AC #1: 설정 화면의 다크 모드 토글이 앱 재시작 후에도 유지된다"])
        self.assertEqual(row["given_info"], "unsure")
        self.assertTrue(row["flagged"])

    def test_post_hoc_evidence_still_grounds_ok(self):
        ev = "review: 재시작 후 다크 모드 토글 유지 확인 — settings_test.dart:42 expect(theme, dark)"
        row, _s = self._grade(["재시작 후 다크 모드 토글 유지 확인 — settings_test.dart:42 expect(theme, dark)"], evidence=ev)
        self.assertEqual(row["given_info"], "ok")

    def test_analyze_decisions_get_no_ac_in_call_one(self):
        for g, stage in (("KICKOFF", "analyze"), ("AN-PO", "analyze"), ("STAKES", "analyze")):
            with self.subTest(group=g):
                _row, seen = self._grade([], group=g, block={"point": g, "stage": stage, "by": "judge:opus",
                                                             "choice": "i1"})
                self.assertNotIn("acceptance_criteria", seen[0])
                self.assertIn("acceptance_criteria", seen[1])            # ② may see it
        _row, seen = self._grade([], group="QA")
        self.assertIn("acceptance_criteria", seen[0])


class M6ReleasePaths(unittest.TestCase):
    def test_every_group_has_a_release_path_or_a_reason(self):
        for g in VALVES.GROUPS:
            with self.subTest(group=g):
                paths = [g in CONS.GATED, g == "KICKOFF", g in UV.SHEET_RELEASED, g in UV.EXEMPT]
                self.assertEqual(sum(paths), 1, paths)
        for g, why in list(UV.EXEMPT.items()) + list(UV.SHEET_RELEASED.items()):
            self.assertTrue(len(why) > 20, g)
        self.assertEqual(set(UV.unverified()), set(VALVES.GROUPS) - set(UV.EXEMPT))

    def test_exarb_dismiss_releases_on_sheet_verdicts(self):
        common = tmpdir(self)
        rows = [{"issue": i, "decision_id": "D%d" % i, "group": "EX-ARB:dismiss", "given_info": "ok",
                 "mode": "first-sprint"} for i in range(1, 6)]
        G.apply_judgments(common, rows[:4], "o/r", "human")
        self.assertIn("EX-ARB-dismiss", UV.pending(common))
        out = G.apply_judgments(common, rows[4:], "o/r", "human")
        self.assertEqual(out.get("unverified_released"), ["EX-ARB-dismiss"])
        # a sheet row never counts for a group released by blind answers
        G.apply_judgments(common, [dict(r, group="QA") for r in rows], "o/r", "human")
        self.assertIn("QA", UV.pending(common))

    def test_grader_rows_never_count(self):
        common = tmpdir(self)
        rows = [{"issue": i, "decision_id": "D%d" % i, "group": "EX-ARB:dismiss", "given_info": "ok",
                 "mode": "first-sprint"} for i in range(1, 9)]
        G.apply_judgments(common, rows, "o/r", "gabc123")                 # not the person's import
        self.assertIn("EX-ARB-dismiss", UV.pending(common))

    def test_source_is_named_as_it_can_be_acted_on(self):
        class P(object):
            valves = {}
            unverified = frozenset(["EX-ARB-dismiss", "KICKOFF", "QA"])
        self.assertIn("unverified EX-ARB-dismiss", PF.conservative_label(P(), "EX-ARB:dismiss"))
        self.assertNotIn("group.", PF.conservative_label(P(), "KICKOFF"))
        P.valves = {"group.QA.conservative": True}
        self.assertEqual(PF.conservative_label(P(), "QA"), "group.QA.conservative")
        self.assertNotIn("group.KICKOFF.conservative", PF.neutral_text("kickoff-conservative", 7))

    def test_gate_line_names_the_unverified_source(self):
        h = _h(self)
        h.p.valves = {}
        h.p.unverified = frozenset(["QA"])
        q = _ask(h, "QA", "v1", _Judge("QA", "pass"))
        self.assertIn("unverified QA", q.original or q.text)
        self.assertNotIn("group.QA.conservative", q.original or q.text)


class M1ReleaseCandidates(unittest.TestCase):
    def _pf(self, i, gi):
        return {"issue": i, "decision_id": "D%d" % i, "group": "SPLIT", "given_info": gi, "mode": "predict-first"}

    def test_open_candidates_hold_the_release(self):
        common = tmpdir(self)
        cands = [dict(self._pf(i, ""), reason="wrong candidate") for i in range(6, 8)]
        out = G.apply_judgments(common, [self._pf(i, "ok") for i in range(1, 6)], "o/r", "predict-first",
                                candidates=cands)
        self.assertNotIn("unverified_released", out)
        self.assertIn("SPLIT", UV.pending(common))
        rep = dict((r["group"], r) for r in UV.report(common))["SPLIT"]
        self.assertEqual((rep["counted"], rep["open_candidates"]), (5, 2))
        G.apply_judgments(common, [self._pf(6, "ok")], "o/r", "human")
        self.assertIn("SPLIT", UV.pending(common))                        # one still open
        out = G.apply_judgments(common, [self._pf(7, "wrong")], "o/r", "human")
        self.assertIn("SPLIT", UV.pending(common))                        # the last one was a wrong
        self.assertNotIn("unverified_released", out)

    def test_all_candidates_ok_releases(self):
        common = tmpdir(self)
        G.apply_judgments(common, [self._pf(i, "ok") for i in range(1, 6)], "o/r", "predict-first",
                          candidates=[dict(self._pf(6, ""))])
        out = G.apply_judgments(common, [self._pf(6, "ok")], "o/r", "human")
        self.assertEqual(out.get("unverified_released"), ["SPLIT"])

    def test_a_wrong_after_the_release_is_shown(self):
        common = tmpdir(self)
        G.apply_judgments(common, [self._pf(i, "ok") for i in range(1, 6)], "o/r", "predict-first", candidates=[])
        self.assertNotIn("SPLIT", UV.pending(common))
        G.apply_judgments(common, [self._pf(9, "wrong")], "o/r", "human")
        rep = dict((r["group"], r) for r in UV.report(common))["SPLIT"]
        self.assertEqual((rep["wrong"], rep["wrong_after_release"]), (1, 1))


class M4DualHelpers(unittest.TestCase):
    def test_only_decision_groups(self):
        for g in VALVES.GROUPS:
            self.assertTrue(DUAL.decision_group(g.replace("-dismiss", "").replace("-accept", "")), g)
        for g in ("IDENT", "SAMECAUSE", "PRMATCH", "RUNNER", "FOLLOWUP", "MUTATION", "GATECAST", "DWC", "BRANCH"):
            self.assertFalse(DUAL.decision_group(g), g)

    def test_a_selected_helper_is_called_once(self):
        calls = []

        def ident(spec):
            calls.append(spec.model)
            return Decision("same", {"verdict": "same"}, "judge:%s" % spec.model, "dg")
        h = qa_harness(self, roles=[role("DONE")], judges={"IDENT": ident})
        for n in range(1, 400):
            h.p.issue = n
            if DUAL.selected(h.p, JG.spec(h.p, "IDENT", [("x", "y")], "execute", "X4"), 0.10):
                break
        h.p.dual_rate = 0.10
        h.p.judge(JG.spec(h.p, "IDENT", [("prior", "a"), ("current", "b")], "execute", "X4"))
        self.assertEqual(len(calls), 1)


class M5Centre(unittest.TestCase):
    def J(self, point, choice, stage="qa"):
        return {"point": point, "choice": choice, "by": "judge:sonnet", "stage": stage, "unsure": "false",
                "coerced": "false"}

    def test_conservative_choice_and_release_after(self):
        replay = dict((i, [self.J("QA", "block")]) for i in range(1, 4))
        self.assertEqual(CE.compute(replay, unverified=("QA",))["first_sprint"]["pause_issues"], 0.0)
        replay = dict((i, [self.J("QA", "pass")]) for i in range(1, 11))
        fs = CE.compute(replay, unverified=("QA",))["first_sprint"]
        self.assertEqual(fs["pause_issues"], 0.5)                        # the first 5 of 10 only


class M8LabelRemovalResets(unittest.TestCase):
    def test_unlabel_bumps_the_epoch(self):
        from test_k4_fsm import driver
        from guildcore import state as ST
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 4)
        h.p.journal = J.Journal(tmpdir(self), 7, clock=Clock())
        h.decisions.record({"point": "escalation", "kind": "escalation", "stage": "qa", "by": "code",
                            "status": "pending-human", "question": "engine FAIL — KeyError", "options": ["stop"],
                            "cause": "defect: engine FAIL — KeyError 'x'"})
        iss = h.gh.fx["issues"]["7"]
        iss["labels"] = [lb for lb in iss["labels"] if (lb.get("name") if isinstance(lb, dict) else lb)
                         != "guild:needs-human"]
        iss.setdefault("timeline", []).append({"id": 99001, "event": "unlabeled", "label": {"name": "guild:needs-human"},
                                               "created_at": "2099-01-01T00:00:00Z", "actor": {"login": "owner"}})
        e0 = h.p.journal.epoch()
        drv = driver(h, unattended=True)
        drv.resume(h.p, 7, ST.derive(h.gh.issue(7).get("labels")))
        self.assertEqual(h.p.journal.epoch(), e0 + 1)


class Decision4DualOn(unittest.TestCase):
    def test_default_rate_and_first_sprint(self):
        self.assertEqual(CFG.ENGINE_DEFAULTS["dual_judge_rate"], 0.10)
        self.assertEqual(DUAL.DEFAULT_RATE, 0.10)
        src = open(os.path.join(os.path.dirname(DUAL.__file__), "dual.py"), encoding="utf-8").read()
        self.assertNotIn("first_sprint", src)                             # first-sprint mode never turns it off


SUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "skills", "gld", "templates",
                   "sprint-supervisor.sh")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
OLD = "4b7d49c"                                                      # 0.101.3 — the rollback target


def _sup():
    with open(SUP, encoding="utf-8") as fh:
        return fh.read()


class Decision2Folds(unittest.TestCase):
    """User decision 2 (0.102 에서 접어 쓰기) + r1 m6: every token the 0.102 supervisor writes where 0.101.3 reads is,
    after `compat_fold`, one 0.101.3 documents; the precise token rides beside it."""

    def setUp(self):
        from workflows.dev.replay import k6_downgrade_drill as DR
        self.DR = DR
        if DR.show(REPO, OLD, DR.P + "commands/sprint/run.md") is None:
            self.skipTest("0.101.3 (%s) not in this clone" % OLD)

    def test_every_written_token_is_documented_after_the_fold(self):
        rows = self.DR.fold_check(REPO, OLD, "HEAD", sup=_sup())
        toks = dict((r["token"], r) for r in rows)
        for t in ("halted:engine-gh-auth", "halted:engine-env-ignored-missing", "halted:engine-env-build-inputs-changed",
                  "halted:engine-env-missing", "halted:engine-env-unknown", "create-settle-wait", "create-unsettled",
                  "gh-service-wait", "gh-unavailable", "create-settle-until-1790000000", "gh-service-until-1790000000",
                  "board:gh-unavailable", "board:create-unsettled"):
            self.assertIn(t, toks)
            self.assertNotEqual(toks[t]["folded"], t, t)
        bad = [r["token"] for r in rows if not r["documented_0_101_3"]]
        self.assertEqual(bad, [])
        self.assertIn("gh auth login", toks["halted:engine-gh-auth"].get("note", ""))

    def _bash(self, script, env):
        import subprocess
        funcs = "".join(self.DR._fn(_sup(), f) for f in ("compat_fold", "compat_note", "ledger_set", "_record",
                                                        "marker_write"))
        e = dict(os.environ, **env)
        return subprocess.run(["bash", "-c", funcs + "\n" + script], env=e, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)

    def test_event_class_folded_with_the_exact_class(self):
        d = tmpdir(self)
        ev = os.path.join(d, "failures.jsonl")
        self._bash('_record 7 gh-unavailable "GitHub down after 6 waits" ""; _record 8 busy "held" ""',
                   {"EVENTS": ev, "TRACKER": "3", "TIMESTAMP": "t1", "PY": "python3"})
        with open(ev) as fh:
            rows = [json.loads(x) for x in fh.read().splitlines()]
        self.assertEqual((rows[0]["class"], rows[0]["class_exact"]), ("busy-skipped", "gh-unavailable"))
        self.assertEqual(rows[1]["class"], "busy")
        self.assertNotIn("class_exact", rows[1])

    def test_halted_state_folded_in_the_ledger_before_gh(self):
        d = tmpdir(self)
        led = os.path.join(d, "ledger.json")
        with open(led, "w") as fh:
            json.dump({"state": "running"}, fh)
        # gh fails (auth): the local ledger already carries the fold, the precise reason and the re-auth line
        r = self._bash('gh() { return 1; }; marker_write "halted:engine-gh-auth"',
                       {"LEDGER": led, "D": d, "PY": "python3", "OWNER_REPO": "o/r", "TRACKER": "3"})
        self.assertNotEqual(r.returncode, 0)
        with open(led) as fh:
            st = json.load(fh)
        self.assertEqual(st["state"], "halted:marker-unwritable")
        self.assertEqual(st["halt_reason"], "engine-gh-auth")
        self.assertIn("gh auth login", st["halt_note"])


if __name__ == "__main__":
    unittest.main()
