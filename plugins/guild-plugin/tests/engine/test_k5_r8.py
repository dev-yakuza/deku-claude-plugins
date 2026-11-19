"""K5 review r8 — M1 (the QA `:relint` wording re-ask is no decision: never a conservative question, a person's `block`
is never dropped, no predict-first candidate), M2 (the same-run reuse of applied answers stops with the replay: a run
that went live is judged again), and the minors (m2 the qa role's replay signature carries HEAD, m3 descriptive labels
are no fit language, m4 `decided_at` comes from the engine's log only).
"""

import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from _k2 import role
from test_k2_qa_stage import qa_harness

from guildcore import ask as ASK
from guildcore import valves as VALVES
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Decision
from guildcore.records.decisions import DecisionBlock
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import judging as JG
from workflows.dev import predict as PF
from workflows.dev.stages import base as B
from workflows.dev.stages import qa as Q
from workflows.dev.stages.base import StageResult


def _blocks(h):
    return DecisionLog.load(h.gh.comments(7)).blocks


def _pending(h):
    return [b for b in _blocks(h) if b.get("kind") == "group-conservative" and b.get("status") == "pending-human"]


def _unlabel(h):
    iss = h.gh.fx["issues"]["7"]
    iss["labels"] = [lb for lb in iss["labels"] if (lb.get("name") if isinstance(lb, dict) else lb)
                     != "guild:needs-human"]


def _hedging_judge(calls):
    """review-k5-r8 relint_block_ignored.py: both judgments `pass`, only the first one's checklist hedges."""
    def judge(spec):
        calls.append(spec.point)
        cl = ["권장 로그인 확인"] if spec.point == "QA" else ["로그인 확인"]
        return Decision("pass", {"defects": [], "checklist": cl, "quality_bar_met": "yes", "verdict": "pass"},
                        "judge:sonnet", "dg-" + spec.point)
    return judge


def _run(h):
    CONS.begin(h.p)
    try:
        return Q.run(h.p, diff_paths=[])
    except CONS.Ask as a:
        CONS.surface(h.p, "qa", a)
        return _pending(h)[-1]


class M1RelintIsNoDecision(unittest.TestCase):
    def _harness(self, unattended=True):
        calls = []
        h = qa_harness(self, unattended=unattended, roles=[role("DONE", plan="qa-report.md", human_items=[],
                                                                followups=[])] * 6,
                       judges={"QA": _hedging_judge(calls)})
        h.write_file("docs/standards/quality-bar.md", "# bar\n- no crash\n")
        h.p.valves = {"group.QA.conservative": True}
        h.p.git_dir = None
        return h, calls

    def test_repro_one_question_then_done(self):
        h, calls = self._harness()
        pend = _run(h)
        self.assertEqual(pend.get("refs"), "conservative:QA:#7:qa:Q2.5:L0")
        ASK.answer(h.decisions, h.writer, 7, pend.id, "pass")
        _unlabel(h)
        r = _run(h)
        self.assertEqual(getattr(r, "kind", None), StageResult.DONE, r)      # no second (identical) question
        self.assertIn("guild:done", h.labels())
        self.assertEqual(len([b for b in _blocks(h) if b.get("kind") == "group-conservative"
                              and b.get("status")]), 1)
        self.assertFalse([b for b in _blocks(h) if str(b.get("refs") or "").endswith(":relint")])
        rl = [b for b in _blocks(h) if b.get("point") == "QA:relint"][-1]
        self.assertEqual((rl.get("choice"), rl.get("by")), ("checklist", "judge:sonnet"))   # wording only
        qa = [(b.get("choice"), b.get("by")) for b in _blocks(h) if b.get("point") == "QA"]
        self.assertEqual(qa, [("pass", "human")])

    def test_a_block_answer_stands_with_a_hedged_checklist(self):
        h, calls = self._harness()
        pend = _run(h)
        ASK.answer(h.decisions, h.writer, 7, pend.id, "block")
        _unlabel(h)
        r = _run(h)
        self.assertEqual(getattr(r, "kind", None), StageResult.PAUSE, r)
        self.assertNotIn("guild:done", h.labels())
        qa = [b for b in _blocks(h) if b.get("point") == "QA"][-1]
        self.assertEqual((qa.get("choice"), qa.get("by"), qa.get("coerced_by")), ("block", "human", "conservative"))
        self.assertEqual(len(_pending(h)), 1)

    def test_relint_raises_no_predict_first_question_attended(self):
        h, calls = self._harness(unattended=False)
        pend = _run(h)
        ASK.answer(h.decisions, h.writer, 7, pend.id, "pass")
        r = _run(h)
        self.assertEqual(getattr(r, "kind", None), StageResult.DONE, r)
        self.assertEqual([b.get("refs") for b in _blocks(h) if b.get("raised_by") == "confirm"],
                         ["conservative:QA:#7:qa:Q2.5:L0"])

    def test_gate_passes_a_relint_point_straight_to_the_judge(self):
        h, calls = self._harness()
        d = CONS.gate(h.p, JG.spec(h.p, "QA", [("x", "y")], "qa", "Q2.5", point="QA:relint"),
                      lambda s: Decision("pass", {"verdict": "pass", "checklist": ["a"]}, "judge:sonnet", "dg"))
        self.assertEqual((d.choice, d.by), ("pass", "judge:sonnet"))


class M2UsedStopsWithTheReplay(unittest.TestCase):
    def _h(self):
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 6)
        h.p.valves = {"group.QA.conservative": True, "group.TEST.conservative": True}
        h.p.git_dir = None
        h.p.journal = None
        return h

    def test_inputs_change_between_the_questions_judges_again(self):
        h = self._h()
        judged = []

        def stage_run(issue):
            CONS.begin(h.p)
            r = CONS.role(h.p, B.RoleCall("qa", "run", "qa", "Q1", inputs={"issue.md": issue}),
                          lambda c: role("DONE", line="qa: CRASH" if "crash" in issue else "qa: green",
                                         plan="qa-report.md", human_items=[], followups=[]))

            def qa_judge(spec):
                judged.append("QA")
                v = "block" if "CRASH" in (r.line or "") else "pass"
                return Decision(v, {"verdict": v}, "judge:sonnet", "dgQ")

            def test_judge(spec):
                judged.append("TEST")
                return Decision("all_effective", {"overall": "all_effective"}, "judge:sonnet", "dgT")
            a = CONS.gate(h.p, JG.spec(h.p, "QA", [("x", "y")], "qa", "Q2.5"), qa_judge)
            t = CONS.gate(h.p, JG.spec(h.p, "TEST", [("x", "y")], "qa", "Q2.6"), test_judge)
            return a, t

        for issue, choice in (("login", "pass"), ("login", "all_effective")):
            try:
                stage_run(issue)
                self.fail("expected a question")
            except CONS.Ask as a:
                CONS.surface(h.p, "qa", a)
            ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, choice)
        # the Issue changed while the second question was open: the qa role goes live and reports a crash
        a, t = stage_run("login — reproduces a crash on login")
        self.assertEqual((a.choice, a.by), ("block", "judge:sonnet"))    # judged again, never the old `pass`
        # K6 (item 40): the TEST answer was given to a run this one no longer is — the point is judged again and the
        # answer applies only because the judge chooses what the person was asked about (all_effective)
        self.assertEqual(judged, ["QA", "TEST", "QA", "TEST"])
        self.assertEqual((t.choice, t.by), ("all_effective", "human"))

    def test_repro_used_leak_through_the_stage(self):
        # review-k5-r8 used_leak.py, with the second conservative point a TEST judgment (relint is no point any more)
        runs, judged = [], []

        def qa_role(call):
            runs.append(1)
            bad = "crash" in (call.inputs.get("issue.md") or "")
            return role("DONE", line=("qa: CRASH on login" if bad else "qa: all green"), plan="qa-report.md",
                        human_items=[], followups=[])

        def judge(spec):
            judged.append(spec.step)
            if "CRASH" in dict(spec.brief_parts).get("qa", ""):
                return Decision("block", {"defects": [{"id": "F1", "blocking": True, "fixable_in_code": "yes",
                                                       "line": "crash"}], "checklist": [], "verdict": "block"},
                                "judge:sonnet", "dgB")
            return Decision("pass", {"defects": [], "checklist": [], "quality_bar_met": "yes", "verdict": "pass"},
                            "judge:sonnet", "dg%d" % len(judged))

        def test_judge(spec):
            judged.append(spec.step)
            return Decision("all_effective", {"overall": "all_effective"}, "judge:sonnet", "dgT")
        h = qa_harness(self, unattended=False, roles=[qa_role] * 6, judges={"QA": judge, "TEST": test_judge})
        h.write_file("docs/standards/quality-bar.md", "# bar\n- no crash\n")
        h.p.valves = {"group.QA.conservative": True, "group.TEST.conservative": True}
        h.p.git_dir = None
        h.p.journal = None
        real = Q._judge

        def judge_then_test(p, *a, **k):
            out = real(p, *a, **k)
            p.judge(JG.spec(p, "TEST", [("x", "y")], "qa", "Q2.6"))
            return out
        Q._judge = judge_then_test
        try:
            p1 = _run(h)
            ASK.answer(h.decisions, h.writer, 7, p1.id, "pass")
            p2 = _run(h)
            self.assertEqual(p2.get("refs"), "conservative:TEST:#7:qa:Q2.6:L0")
            iss = h.gh.fx["issues"]["7"]
            iss["body"] = (iss.get("body") or "") + "\n\nnote: reproduces a crash on login"
            ASK.answer(h.decisions, h.writer, 7, p2.id, "all_effective")
            r = _run(h)
        finally:
            Q._judge = real
        self.assertEqual(len(runs), 2)                                     # run 3 live (run 2 replayed)
        self.assertEqual(judged.count("Q2.5"), 2)                          # run 1 + run 3: judged again
        qa = [b for b in _blocks(h) if b.get("point") == "QA"][-1]
        self.assertEqual((qa.get("choice"), qa.get("by")), ("block", "judge:sonnet"))
        self.assertNotIn("guild:done", h.labels())
        self.assertNotEqual(getattr(r, "kind", None), StageResult.DONE)


class M2HeadInTheQaSignature(unittest.TestCase):
    def test_salt_changes_the_signature_and_none_keeps_it(self):
        c0 = B.RoleCall("qa", "run", "qa", "Q1", inputs={"a": "b"})
        c1 = B.RoleCall("qa", "run", "qa", "Q1", inputs={"a": "b"}, replay_salt=lambda: "abc")
        c2 = B.RoleCall("qa", "run", "qa", "Q1", inputs={"a": "b"}, replay_salt=lambda: "def")
        c3 = B.RoleCall("qa", "run", "qa", "Q1", inputs={"a": "b"}, replay_salt=lambda: None)
        self.assertNotEqual(CONS._sig(c1), CONS._sig(c2))
        self.assertNotEqual(CONS._sig(c0), CONS._sig(c1))
        self.assertEqual(CONS._sig(c0), CONS._sig(c3))

    def _flow(self, head_after_question, commit_in_role=None):
        head = ["h1"]
        n = [0]

        def qa_role(call):
            n[0] += 1
            if commit_in_role and n[0] == 1:
                head[0] = commit_in_role                                   # qa's own test commit moves HEAD
            return role("DONE", plan="qa-report.md", human_items=[], followups=[])
        h = qa_harness(self, unattended=False, roles=[qa_role] * 4,
                       judges={"QA": lambda spec: Decision("pass", {"defects": [], "checklist": [],
                                                                    "quality_bar_met": "yes", "verdict": "pass"},
                                                           "judge:sonnet", "dg")})
        h.p.valves = {"group.QA.conservative": True}
        h.p.git_dir = None
        real = Q._head
        Q._head = lambda p: head[0]
        try:
            pend = _run(h)
            if head_after_question:
                head[0] = head_after_question                              # a push between question and answer
            ASK.answer(h.decisions, h.writer, 7, pend.id, "pass")
            r = _run(h)
        finally:
            Q._head = real
        self.assertEqual(getattr(r, "kind", None), StageResult.DONE, r)
        return n[0]

    def test_unchanged_head_replays(self):
        self.assertEqual(self._flow(None), 1)

    def test_a_push_between_question_and_answer_runs_qa_live(self):
        self.assertEqual(self._flow("h2"), 2)

    def test_qa_own_commit_still_replays(self):
        self.assertEqual(self._flow(None, commit_in_role="h1+qa"), 1)


class M3DescriptiveLabels(unittest.TestCase):
    DESCRIPTIVE = ("근거 자료 링크 추가", "本文 그대로 표시", "본문 그대로 표시", "根拠リンクを追加", "タイトル通りに表示",
                   "Typical flow only", "Literal string search", "Match title case in headers",
                   "Header follows the title style")

    def test_repro_descriptive_labels_are_kept(self):
        for lb in self.DESCRIPTIVE:
            self.assertEqual(PF.neutral_label(lb), lb, lb)
            self.assertFalse(PF.evaluative(lb), lb)

    def test_fit_language_is_still_cut(self):
        for raw, want in (("로그인 화면만 (근거 없음)", "로그인 화면만"),
                          ("다크 모드 (제목에 근거)", "다크 모드"),
                          ("ログイン画面のみ（根拠が薄い）", "ログイン画面のみ"),
                          ("アプリ全体（タイトル通り）", "アプリ全体"),
                          ("ログイン画面のみ（素直な解釈）", "ログイン画面のみ"),
                          ("앱 전체 (제목 그대로)", "앱 전체"),
                          ("Login only (the typical reading)", "Login only"),
                          ("Whole app (read literally)", "Whole app"),
                          ("Login (follows the title)", "Login"),
                          ("Whole app (matches the title)", "Whole app")):
            self.assertEqual(PF.neutral_label(raw), want, raw)


def _row_sheet(at_col):
    return ("decision_id,issue,stage,group,mode,choice,reason,coerced,coerced_by,unsure,irreversible,evidence,"
            "given_info,outcome,note,decided_at\n"
            "D4,9,qa,QA,sample,pass,,false,,false,,,wrong,,,%s\n" % at_col)


class M4DecidedAtFromTheLog(unittest.TestCase):
    def _released(self):
        c = os.path.join(tmpdir(self), "c")
        G.apply_judgments(c, [{"decision_id": "D1", "issue": "7", "group": "QA", "given_info": "wrong",
                               "decided_at": "2026-11-01T00:00:00Z"}], "o/r", "human")
        VALVES.human_clear(c, "group.QA.conservative", "owner", "reviewed")
        G.on_release(c)
        return c

    def test_no_time_in_the_log_is_no_forgiveness(self):
        c = self._released()
        log = {9: [DecisionBlock(4, [("point", "QA"), ("stage", "qa"), ("by", "judge:sonnet"), ("choice", "pass")])]}
        r = G.import_sheet(c, _row_sheet("2000-01-01T00:00:00Z"), "o/r", blocks_of=lambda n: log.get(n, []))
        self.assertEqual((r["watch"], r.get("forgiven_by_release") or []), (["QA"], []))

    def test_the_log_time_forgives(self):
        c = self._released()
        log = {9: [DecisionBlock(4, [("point", "QA"), ("stage", "qa"), ("by", "judge:sonnet"), ("choice", "pass"),
                                     ("at", "2026-11-01T00:00:01Z")])]}
        r = G.import_sheet(c, _row_sheet("2099-01-01T00:00:00Z"), "o/r", blocks_of=lambda n: log.get(n, []))
        self.assertEqual((r["watch"], r.get("forgiven_by_release")), ([], ["D4"]))

    def test_a_sheet_without_a_log_check_is_not_trusted(self):
        c = self._released()
        r = G.import_sheet(c, _row_sheet("2000-01-01T00:00:00Z"), "o/r")
        self.assertEqual((r["watch"], r.get("forgiven_by_release") or []), (["QA"], []))


if __name__ == "__main__":
    unittest.main()
