"""K5 review r7 — M1 (an answer to a conservative decision point is consumed once: a rollback / rerun / resume after
the pause it led to is a new point — judged again, asked again; the loop generation is monotonic), and the minors
(m1 a person's `block` survives a missing quality-bar.md, m2 fit-language labels and indistinct labels, m3 the replay
signature carries the inputs, m4 the X→T `applied` mark follows its effect, m5 a release forgives by decision time,
m6 one `active` predicate).
"""

import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from _k2 import role
from _k4 import K4, decision
from test_k2_qa_stage import qa_harness
from test_k4_fsm import driver, relabel
from test_k5_r4 import _ask_readiness, _env, _kick
from test_k5_r5 import _answer, _cons

from guildcore import ask as ASK
from guildcore import valves as VALVES
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Decision
from guildcore.records import loopback as LB
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


def _qa_judge(calls, verdicts):
    def judge(spec):
        v = verdicts[min(len(calls), len(verdicts) - 1)]
        calls.append(v)
        defects = [] if v == "pass" else [{"id": "F1", "severity": "BLOCKER", "blocking": True,
                                           "fixable_in_code": "yes", "line": "crash on login"}]
        return Decision(v, {"defects": defects, "checklist": [], "quality_bar_met": "yes" if v == "pass" else "no",
                            "verdict": v}, "judge:sonnet", "dg%d" % len(calls))
    return judge


def _ask_and_answer(case, h, choice, diff=()):
    try:
        Q.run(h.p, diff_paths=list(diff))
        case.fail("expected a conservative question")
    except CONS.Ask as a:
        CONS.surface(h.p, "qa", a)
    pend = _pending(h)[-1]
    ASK.answer(h.decisions, h.writer, 7, pend.id, choice)
    CONS.begin(h.p)
    return pend


def _qa(h, diff):
    """A qa stage run as the FSM runs it (K5r9-M2: `applied` is written once the answer's effect is)."""
    return CONS.guarded(h.p, "qa", lambda: Q.run(h.p, diff_paths=list(diff)))


def _back_to_qa(h, reset=False):
    iss = h.gh.fx["issues"]["7"]
    if reset:
        body = LB.render_new_record(LB.render_reset("2026-11-19T01:00:00Z"))
        iss["comments"].append({"id": 990, "body": body, "created_at": "2026-11-19T01:00:00Z",
                                "user": {"login": "owner"}, "author_association": "OWNER"})
    iss["labels"] = [{"name": "guild:qa"}] if iss["labels"] and isinstance(iss["labels"][0], dict) else ["guild:qa"]
    CONS.begin(h.p)


class M1AnswerConsumedOnce(unittest.TestCase):
    def _harness(self, verdicts, unattended=False, bar=True):
        calls = []
        h = qa_harness(self, unattended=unattended, roles=[role("DONE", plan="qa-report.md", human_items=[],
                                                                followups=[])] * 8,
                       judges={"QA": _qa_judge(calls, verdicts)})
        if bar:
            h.write_file("docs/standards/quality-bar.md", "# bar\n- no crash\n")
        h.p.valves = {"group.QA.conservative": True}
        h.p.git_dir = None
        return h, calls

    def test_repro_rollback_judges_again(self):
        # review-k5-r7 rollback_reapply.py: the new code's judgment is `block` — it must be called and stand
        h, calls = self._harness(["pass", "block"])
        pend = _ask_and_answer(self, h, "pass")
        self.assertEqual(pend.get("refs"), "conservative:QA:#7:qa:Q2.5:L0")
        self.assertEqual(_qa(h, []).kind, StageResult.DONE)
        _back_to_qa(h)                                                     # `/gld rollback` — no loop-back block
        _qa(h, ["lib/login.dart"])
        self.assertEqual(len(calls), 2)                                    # judged again on the new code
        qa = [b for b in _blocks(h) if b.get("point") == "QA"][-1]
        self.assertEqual((qa.get("choice"), qa.get("by")), ("block", "judge:sonnet"))
        self.assertNotIn("guild:done", h.labels())

    def test_rollback_asks_a_new_question_when_the_judge_passes_again(self):
        h, calls = self._harness(["pass"])
        _ask_and_answer(self, h, "pass")
        _qa(h, [])
        _back_to_qa(h)
        pend = _ask_and_answer(self, h, "pass")                            # a NEW question
        self.assertEqual(pend.get("refs"), "conservative:QA:#7:qa:Q2.5:L0:a1")
        self.assertEqual(len(calls), 2)

    def test_reset_is_a_new_generation(self):
        h, calls = self._harness(["pass"])
        _ask_and_answer(self, h, "pass")
        _qa(h, [])
        _back_to_qa(h, reset=True)                                         # rollback to design: loopback-reset
        pend = _ask_and_answer(self, h, "pass")
        self.assertEqual(pend.get("refs"), "conservative:QA:#7:qa:Q2.5:L1")   # never back to L0
        self.assertEqual(len(calls), 2)

    def test_repro_block_answer_resume_judges_again(self):
        # review-k5-r7 block_answer_stuck_bar.py: unattended `block` → pause; the person fixes and resumes
        h, calls = self._harness(["pass"], unattended=True)
        _ask_and_answer(self, h, "block")
        r = _qa(h, ["lib/a.dart"])
        self.assertEqual(r.kind, StageResult.PAUSE)                        # the answer applied once
        iss = h.gh.fx["issues"]["7"]
        iss["labels"] = [lb for lb in iss["labels"] if (lb.get("name") if isinstance(lb, dict) else lb)
                         != "guild:needs-human"]
        CONS.begin(h.p)
        pend = _ask_and_answer(self, h, "pass")                            # §2.5 rule 3: judged again → asked anew
        self.assertEqual(pend.get("refs"), "conservative:QA:#7:qa:Q2.5:L0:a1")
        # K6 (item 40): the run that applies `block` sees another diff (lib/a.dart) than the run that asked — the judge
        # is called again first (it still says `pass`, the question the person answered → the answer applies)
        self.assertEqual(len(calls), 3)
        self.assertEqual(_qa(h, ["lib/b.dart"]).kind, StageResult.DONE)   # the next answer is the way out
        qa = [b for b in _blocks(h) if b.get("point") == "QA"]
        self.assertEqual([(b.get("choice"), b.get("by")) for b in qa], [("block", "human"), ("pass", "human")])

    def test_second_point_in_one_run_reuses_the_first_answer(self):
        h = qa_harness(self, roles=[role("DONE", plan="qa-report.md", human_items=[], followups=[])] * 6)
        h.p.valves = {"group.QA.conservative": True, "group.TEST.conservative": True}
        h.p.git_dir = None
        judged = []

        def judge_of(choice, key):
            def j(spec):
                judged.append(spec.group)
                # K5r9-M1: a judge's fields as the runner leaves them (QA `pass` with its quality bar met)
                f = {key: choice, "quality_bar_met": "yes"} if key == "verdict" else {key: choice}
                return Decision(choice, f, "judge:sonnet", "dg-%s" % spec.group)
            return j

        def stage_run():
            CONS.begin(h.p)
            CONS.role(h.p, B.RoleCall("qa", "run", "qa", "Q1", inputs={"issue.md": "x"}),
                      lambda c: role("DONE", plan="qa-report.md", human_items=[], followups=[]))
            a = CONS.gate(h.p, JG.spec(h.p, "QA", [("x", "y")], "qa", "Q2.5"), judge_of("pass", "verdict"))
            t = CONS.gate(h.p, JG.spec(h.p, "TEST", [("x", "y")], "qa", "Q2.6"), judge_of("all_effective", "overall"))
            return a.choice, t.choice

        for choice in ("pass", "all_effective"):
            try:
                stage_run()
                self.fail("expected a question")
            except CONS.Ask as a:
                CONS.surface(h.p, "qa", a)
            ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, choice)
        self.assertEqual(stage_run(), ("pass", "all_effective"))           # QA's answer reused, not asked again
        CONS.flush(h.p)                                                    # the stage's end (the FSM's `guarded`)
        self.assertEqual(len(_pending(h)), 2)
        self.assertEqual(judged, ["QA", "TEST"])
        try:                                                               # a later entry: both consumed → asked anew
            stage_run()
            self.fail("expected a new question")
        except CONS.Ask as a:
            self.assertEqual(a.question.refs, "conservative:QA:#7:qa:Q2.5:L0:a1")

    def test_m1_human_block_survives_a_missing_quality_bar(self):
        h, calls = self._harness(["pass"], unattended=True, bar=False)
        _ask_and_answer(self, h, "block")
        r = _qa(h, [])
        self.assertEqual(r.kind, StageResult.PAUSE)
        qa = [b for b in _blocks(h) if b.get("point") == "QA"][-1]
        self.assertEqual((qa.get("choice"), qa.get("by"), qa.get("coerced_by")), ("block", "human", "conservative"))
        self.assertNotIn("guild:done", h.labels())


class M3ReplayInputs(unittest.TestCase):
    def test_changed_inputs_run_the_role_live(self):
        n = [0]

        def qa_role(call):
            n[0] += 1
            return role("DONE", plan="qa-report.md", human_items=[], followups=[])
        h = qa_harness(self, unattended=False, roles=[qa_role] * 4,
                       judges={"QA": lambda spec: Decision("pass", {"defects": [], "checklist": [],
                                                                    "quality_bar_met": "yes", "verdict": "pass"},
                                                           "judge:sonnet", "dg")})
        h.p.valves = {"group.QA.conservative": True}
        h.p.git_dir = None
        _ask_and_answer(self, h, "pass")
        h.gh.fx["issues"]["7"]["body"] = (h.gh.fx["issues"]["7"].get("body") or "") + "\n\n(edited: also iPad)"
        self.assertEqual(Q.run(h.p, diff_paths=[]).kind, StageResult.DONE)
        self.assertEqual(n[0], 2)                                          # not a replay of the old reading

    def test_an_answer_only_comment_is_no_new_input(self):
        call = B.RoleCall("explorer", "kickoff", "analyze", "A2", inputs={"comments.md": {"text": "comment 1 by o:\nhi"}})
        call2 = B.RoleCall("explorer", "kickoff", "analyze", "A2", inputs={"comments.md": {
            "text": "comment 1 by o:\nhi\n\ncomment 900 by owner:\nguild-answer: D1 high"}})
        call3 = B.RoleCall("explorer", "kickoff", "analyze", "A2", inputs={"comments.md": {
            "text": "comment 1 by o:\nhi\n\ncomment 900 by owner:\nguild-answer: D1 high\nalso iPad"}})
        self.assertEqual(CONS._sig(call), CONS._sig(call2))
        self.assertNotEqual(CONS._sig(call), CONS._sig(call3))


class M4HandoverAppliedAfterEffect(unittest.TestCase):
    def test_failed_effect_leaves_the_answer_unapplied(self):
        okw = decision("ok_with_assumption", {"verdict": "ok_with_assumption", "line": "evidence is in the PR"})
        h = _cons(K4(self, labels=("guild:execute",), judges={"HANDOFF": [okw]}), "HANDOFF")
        h.p.journal = h.journal
        ran = []

        def test_stage(p, **k):
            ran.append(1)
            return StageResult(StageResult.PAUSE, cause="test ran")
        stages = {"execute": relabel(h, "test"), "test": test_stage}
        driver(h, stages).run(7)
        _answer(h, "guild-answer: %s upstream_gap" % _pending(h)[0].id)
        real = B.pause
        try:
            def boom(*a, **k):
                raise RuntimeError("GitHub write failed")
            B.pause = boom
            try:
                out = driver(h, stages).run(7)
                self.assertTrue(out.result is None or out.result.kind == StageResult.FAIL, out.line)
            except RuntimeError:
                pass
        finally:
            B.pause = real
        self.assertFalse([b for b in _blocks(h) if b.get("point") == "applied"])
        p = h.p
        CONS.begin(p)
        self.assertTrue(CONS.answered_unapplied(p, "HANDOFF", "test", "X→T"))
        out = driver(h, stages).run(7)                                     # the gap is still applied, test never ran
        self.assertEqual(ran, [])
        self.assertIn("execute→test hand-over gap", out.line or out.result.cause or "")
        self.assertTrue([b for b in _blocks(h) if b.get("point") == "applied"])


class M2Labels(unittest.TestCase):
    def test_repro_fit_language_is_cut(self):
        for raw, want in (("Whole app (matches the title)", "Whole app"),
                          ("Login screen only (the title does not mention login)", "Login screen only"),
                          ("로그인 화면만 (제목과 어울리지 않음)", "로그인 화면만"),
                          ("앱 전체 (제목과 일치)", "앱 전체"),
                          ("로그인 화면만 (억지 해석)", "로그인 화면만"),
                          ("ログイン画面のみ（根拠が薄い）", "ログイン画面のみ"),
                          ("アプリ全体（タイトル通り）", "アプリ全体"),
                          ("Login screen only (a stretch)", "Login screen only"),
                          ("다크 모드 (앱 전체, 가능성 높음)", "다크 모드 (앱 전체)")):
            self.assertEqual(PF.neutral_label(raw), want, raw)

    def test_descriptive_labels_are_kept(self):
        for lb in ("Match system theme", "Resize to fit the screen", "비밀번호 일치 확인", "로그인 화면에만 다크 모드 적용",
                   "narrow reading", "設定画面は変えない"):
            self.assertEqual(PF.neutral_label(lb), lb)

    def test_identical_labels_after_the_cut_refuse(self):
        e, p = _env(self)
        q = ASK.Question("readiness", "goal unclear — choose", [{"token": "i1", "label": "다크 모드 (가능성 낮음)"},
                                                                 {"token": "i2", "label": "다크 모드 (가능성 높음)"},
                                                                 {"token": "stop", "label": "stop"}],
                         recommended="i2", recommended_by="judge:opus")
        PF.apply(p, q, "analyze")
        self.assertFalse(q.predict_first)
        self.assertTrue(q.blind_refused.startswith("label-indistinct"), q.blind_refused)

    def test_repro_label_leak_r7_through_the_stage(self):
        k = _kick(["I1", "I2"], "I2", "범위를 정해야 함",
                  summaries=("다크 모드 (로그인만, 가능성 낮음)", "다크 모드 (앱 전체, 가능성 높음)"))
        e, p = _env(self)
        ev, blk = _ask_readiness(e, p, k)
        self.assertTrue(ev["predict_first"])
        self.assertEqual(sorted(o["label"] for o in ev["options"] if o["token"] != "stop"),
                         ["다크 모드 (로그인만)", "다크 모드 (앱 전체)"])


def _w(did, at):
    return {"decision_id": did, "issue": "7", "group": "QA", "given_info": "wrong", "decided_at": at}


class M5ForgivenByDecisionTime(unittest.TestCase):
    def test_a_wrong_decided_before_the_release_is_forgiven(self):
        c = os.path.join(tmpdir(self), "c")
        G.apply_judgments(c, [_w("D1", "2026-11-01T00:00:00Z"), _w("D2", "2026-11-01T00:00:01Z")], "o/r", "human")
        VALVES.human_clear(c, "group.QA.conservative", "owner", "reviewed")
        G.on_release(c)
        r = G.apply_judgments(c, [_w("D3", "2026-11-01T00:00:02Z")], "o/r", "human")   # late-filled, decided before
        self.assertEqual((r["watch"], r["conservative"], r.get("forgiven_by_release")), ([], [], ["D3"]))
        self.assertEqual(len([g for g in G.grades(c) if g.get("decision_id") == "D3"]), 1)   # still recorded
        r = G.apply_judgments(c, [_w("D9", "2099-01-01T00:00:00Z")], "o/r", "human")
        self.assertEqual(r["watch"], ["QA"])                               # a wrong after the release counts


class M6OnePredicate(unittest.TestCase):
    def test_any_active_follows_active(self):
        class P(object):
            valves = {"group.NOPE.conservative": True}
        self.assertFalse(CONS.any_active(P()))                             # not a gated group: nothing is gated
        real = PF.conservative
        try:
            PF.conservative = lambda p, g: g == "QA"                       # e.g. the K6 `conservative.active` list
            P.valves = {}
            self.assertTrue(CONS.any_active(P()))
        finally:
            PF.conservative = real


if __name__ == "__main__":
    unittest.main()
