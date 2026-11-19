"""K5 review r6 — M1 (the conservative path converges: a question per decision point, the answer applied before any
role runs again, the execute→test hand-over answer consumed at test entry), M2 (the predict-first count: one real
option is no judgment, `stop` is a candidate, evaluative labels are cut or refuse), M3 (a count-rule valve's release
is an event) and the cheap minors (m1 key case, m2 import re-derives group/irreversible, m4 `partial` is `confirm`,
m7 STAKES reason withheld before a blind question, m8 no `recommended_by` on a blind block).
"""

import hashlib
import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from _k2 import role
from _k4 import ANCHOR_OK, K4, decision, evidence, kickoff, stakes
from test_k2_qa_stage import qa_harness
from test_k4_fsm import driver, relabel
from test_k5_r4 import _ask_readiness, _env, _kick
from test_k5_r5 import _answer, _cons

from guildcore import ask as ASK
from guildcore import valves as VALVES
from guildcore.decisions import DecisionLog
from guildcore.judges import runner as JR
from guildcore.judges.runner import Decision
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import predict as PF
from workflows.dev.stages import analyze as A
from workflows.dev.stages import qa as Q
from workflows.dev.stages.base import StageResult


def _pending(h, kind="group-conservative"):
    return [b for b in DecisionLog.load(h.gh.comments(7)).blocks
            if b.get("kind") == kind and b.get("status") == "pending-human"]


class M1DecisionPoint(unittest.TestCase):
    def test_repro_qa_loop_one_question_one_role_run(self):
        # review-k5-r6 qa_loop.py: every qa run reports a different line → a digest key asked after every answer
        n = [0]

        def qa_role(call):
            n[0] += 1
            return role("DONE", line="qa run %d: all green (took %ds)" % (n[0], 40 + n[0]), plan="qa-report.md",
                        human_items=[], followups=[])

        def judge(spec):                     # the real runner's digest: the assembled brief
            dg = hashlib.sha256(JR.assemble(spec.brief_parts, spec.cap_chars, spec.no_elide).encode()).hexdigest()[:12]
            return Decision("pass", {"defects": [], "checklist": [], "quality_bar_met": "yes", "verdict": "pass"},
                            "judge:sonnet", dg)
        h = qa_harness(self, unattended=False, roles=[qa_role] * 5, judges={"QA": judge})
        h.p.valves = {"group.QA.conservative": True}
        h.p.git_dir = None
        asked, result = [], None
        for _i in range(3):
            try:
                result = Q.run(h.p, diff_paths=[])
                break
            except CONS.Ask as a:
                CONS.surface(h.p, "qa", a)
                pend = _pending(h)[-1]
                asked.append(pend.get("refs"))
                ASK.answer(h.decisions, h.writer, 7, pend.id, "pass")
        self.assertEqual(result.kind, StageResult.DONE)
        self.assertEqual(len(asked), 1)                                    # one question
        self.assertEqual(n[0], 1)                                          # one qa role run
        self.assertEqual(asked[0], "conservative:QA:#7:qa:Q2.5:L0")        # the decision point, not a digest
        qa = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "QA"][-1]
        self.assertEqual((qa.get("by"), qa.get("coerced_by")), ("human", "conservative"))
        self.assertTrue([b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == "applied"])

    def test_resume_through_the_fsm_runs_no_role_again(self):
        h = _cons(K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear"), "STAKES": stakes("low")}),
                  "STAKES")
        h.p.journal = h.journal
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        pend = _pending(h)[0]
        self.assertEqual(pend.get("refs"), "conservative:STAKES:#7:analyze:A1.3:L0")
        _answer(h, "guild-answer: %s high" % pend.id)
        h.judges["KICKOFF"] = kickoff(goal="unclear")                       # (the live runner: a journal-cache hit)
        before = len(h.calls["roles"])
        driver(h).run(7)                                                   # no role queued: a role run would raise
        self.assertEqual(len(h.calls["roles"]), before)
        st = h.decisions_of("STAKES")[-1]
        self.assertEqual((st.get("choice"), st.get("by"), st.get("raw_choice")), ("high", "human", "low"))
        self.assertEqual(len([b for b in DecisionLog.load(h.gh.comments(7)).blocks
                              if b.get("kind") == "group-conservative" and b.get("status") == "pending-human"]), 1)

    def test_handover_answer_is_applied_at_test_entry(self):
        okw = decision("ok_with_assumption", {"verdict": "ok_with_assumption", "line": "evidence is in the PR"})
        h = _cons(K4(self, labels=("guild:execute",), judges={"HANDOFF": [okw]}), "HANDOFF")
        h.p.journal = h.journal
        ran = []

        def test_stage(p, **k):
            ran.append(1)
            return StageResult(StageResult.PAUSE, cause="test ran")
        stages = {"execute": relabel(h, "test"), "test": test_stage}
        out = driver(h, stages).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        pend = _pending(h)[0]
        self.assertEqual((pend.get("stage"), pend.get("refs")), ("test", "conservative:HANDOFF:#7:test:X→T:L0"))
        self.assertIn("guild:test", h.labels())                            # the label already moved
        _answer(h, "guild-answer: %s upstream_gap" % pend.id)
        out = driver(h, stages).run(7)
        self.assertEqual(ran, [])                                          # test never ran past the gap
        self.assertIn("execute→test hand-over gap", out.line or out.result.cause or "")
        ho = h.decisions_of("HANDOFF")[-1]
        self.assertEqual((ho.get("choice"), ho.get("by"), ho.get("raw_choice")),
                         ("upstream_gap", "human", "ok_with_assumption"))
        self.assertEqual(h.judges["HANDOFF"], [])                          # judged once: the taped decision applied

    def test_handover_ok_answer_goes_on_to_test(self):
        okw = decision("ok_with_assumption", {"verdict": "ok_with_assumption", "line": "evidence is in the PR"})
        h = _cons(K4(self, labels=("guild:execute",), judges={"HANDOFF": [okw]}), "HANDOFF")
        h.p.journal = h.journal
        ran = []

        def test_stage(p, **k):
            ran.append(1)
            return StageResult(StageResult.PAUSE, cause="test ran")
        stages = {"execute": relabel(h, "test"), "test": test_stage}
        driver(h, stages).run(7)
        _answer(h, "guild-answer: %s ok_with_assumption" % _pending(h)[0].id)
        driver(h, stages).run(7)
        self.assertEqual(ran, [1])
        self.assertEqual(h.decisions_of("HANDOFF")[-1].get("by"), "human")
        self.assertEqual(len(_pending(h)), 1)                              # not asked again


class M2Count(unittest.TestCase):
    def test_repro_single_option_is_not_counted(self):
        kk = kickoff()
        kk.fields["interpretations"] = [{"id": "A", "summary": "show the count"}]
        h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kk})
        h.p._first_sprint = True
        h.p.journal = h.journal
        A.run(h.p)
        pend = [b for b in h.decisions_of("ask:interpretation-surface") if b.get("status") == "pending-human"][0]
        self.assertEqual((pend.options(), pend.get("raised_by")), (["i1", "stop"], "confirm"))
        self.assertTrue(pend.get("predict_first_counted").startswith("false"))
        ASK.answer(h.decisions, h.writer, 7, pend.id, "i1", journal=h.journal)
        self.assertEqual(G.predict_first_judgments(DecisionLog.load(h.gh.comments(7)).blocks, 7), ([], []))

    def test_stop_on_a_blind_confirm_question_is_a_candidate(self):
        from test_k5_r4_grade import pf_log
        ok, cands = G.predict_first_judgments(pf_log(choice="stop"), 7)
        self.assertEqual(ok, [])
        self.assertEqual([(r["group"], r["given_info"], r["decision_id"]) for r in cands], [("KICKOFF", "", "D1")])
        self.assertIn("stop", cands[0]["reason"])
        # judge-raised: still out either way
        self.assertEqual(G.predict_first_judgments(pf_log(choice="stop", raised_by="judge-unclear"), 7), ([], []))

    def test_repro_evaluative_labels_are_cut(self):
        for sums, want in ((("로그인 화면에만 다크 모드 적용 (Issue 문맥상 가능성 낮음)", "앱 전체 화면에 다크 모드 적용 — 제목과 가장 잘 맞음"),
                            ["로그인 화면에만 다크 모드 적용", "앱 전체 화면에 다크 모드 적용"]),
                           (("Login screen only (unlikely given the title)", "Whole app (most likely intent)"),
                            ["Login screen only", "Whole app"]),
                           (("ログイン画面のみ（可能性は低い）", "アプリ全体 — おすすめ"), ["ログイン画面のみ", "アプリ全体"])):
            with self.subTest(sums=sums):
                k = _kick(["I1", "I2"], "I2", "범위를 정해야 함", summaries=sums)
                e, p = _env(self)
                p.journal = e.h.journal
                ev, blk = _ask_readiness(e, p, k)
                self.assertTrue(ev["predict_first"])
                self.assertEqual(sorted(o["label"] for o in ev["options"] if o["token"] != "stop"), sorted(want))
                did = ASK.answer(p.decisions, p.writer, 7, blk.id, "i1", journal=p.journal)
                res = [b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.id == did][0]
                self.assertIn(sums[0], res.get("revealed_question") or "")       # the cut clause, after the answer

    def test_a_label_that_is_only_evaluation_refuses(self):
        k = _kick(["I1", "I2"], "I2", "범위를 정해야 함", summaries=("가장 자연스러운 해석", "로그인 화면만"))
        e, p = _env(self)
        ev, blk = _ask_readiness(e, p, k)
        self.assertFalse(ev["predict_first"])
        self.assertTrue(blk.get("predict_first_refused").startswith("label-evaluative"))

    def test_plain_negation_is_no_rating(self):
        self.assertEqual(PF.neutral_label("설정 화면은 바꾸지 않는다"), "설정 화면은 바꾸지 않는다")
        self.assertEqual(PF.neutral_label("do not sync to the server"), "do not sync to the server")
        self.assertIsNone(PF.neutral_label("the best reading"))

    def test_blind_block_has_no_recommended_by(self):                      # m8
        k = _kick(["I1", "I2"], "I2", "범위", summaries=("login only", "whole app"))
        e, p = _env(self)
        ev, blk = _ask_readiness(e, p, k)
        self.assertTrue(ev["predict_first"])
        self.assertIsNone(blk.get("recommended_by"))


def _w(d, g="QA", gi="wrong", **kw):
    return dict({"decision_id": d, "issue": 9, "group": g, "given_info": gi}, **kw)


class M3ReleaseIsAnEvent(unittest.TestCase):
    def test_repro_release_then_new_wrongs_set_it_again(self):
        c = os.path.join(tmpdir(self), "c")
        self.assertEqual(G.apply_judgments(c, [_w("D1"), _w("D2")], "o/r", "human")["conservative"], ["QA"])
        VALVES.human_clear(c, "group.QA.conservative", "owner", "reviewed")
        G.on_release(c)
        self.assertIsNone(VALVES.effective(c, {}).get("group.QA.conservative"))
        self.assertNotIn("QA", G.load_state(c)["watch"])                  # forgiven up to the release
        r = G.apply_judgments(c, [_w("D7")], "o/r", "human")              # one new wrong → watch only (rule 1)
        self.assertEqual((r["watch"], r["conservative"]), (["QA"], []))
        r = G.apply_judgments(c, [_w("D8")], "o/r", "human")              # a second while watched → again (rule 2)
        self.assertEqual(r["conservative"], ["QA"])
        self.assertTrue(VALVES.effective(c, {})["group.QA.conservative"])

    def test_release_without_on_release_is_synced_at_the_next_import(self):
        c = os.path.join(tmpdir(self), "c")
        G.apply_judgments(c, [_w("D1"), _w("D2")], "o/r", "human")
        VALVES.human_clear(c, "group.QA.conservative", "owner", "reviewed")
        r = G.apply_judgments(c, [_w("D3")], "o/r", "human")
        self.assertEqual(r["conservative"], [])                           # watch restarted: one wrong = watch

    def test_report_reflects_what_is_in_force(self):
        c = os.path.join(tmpdir(self), "c")
        VALVES.human_set(c, "group.QA.conservative", False, "owner", "hold off")   # a person's explicit off
        r = G.apply_judgments(c, [_w("D1"), _w("D2")], "o/r", "human")
        self.assertEqual(r["conservative"], [])
        self.assertFalse(VALVES.effective(c, {})["group.QA.conservative"])


class Minors(unittest.TestCase):
    def test_m1_lowercase_env_key_reaches_the_flow(self):
        c = os.path.join(tmpdir(self), "c")
        eff = VALVES.effective(c, {"GLD_ENGINE_VALVE_GROUP__QA__CONSERVATIVE": "true"})
        self.assertTrue(eff.get("group.QA.conservative"))
        VALVES.human_set(c, "group.stakes.conservative", True, "owner")
        self.assertTrue(VALVES.effective(c, {}).get("group.STAKES.conservative"))

    def test_m2_import_rederives_group_and_irreversible(self):
        from guildcore.records.decisions import DecisionBlock
        c = os.path.join(tmpdir(self), "c")
        log = {9: [DecisionBlock(4, [("point", "QA"), ("stage", "qa"), ("by", "judge:sonnet"), ("choice", "pass")])]}
        text = ("decision_id,issue,stage,group,mode,choice,reason,coerced,coerced_by,unsure,irreversible,evidence,"
                "given_info,outcome,note\n"
                "D4,9,qa,SPLIT,sample,pass,,false,,false,true,,wrong,,\n"
                "D99,9,qa,QA,sample,pass,,false,,false,,,wrong,,\n")
        r = G.import_sheet(c, text, "o/r", blocks_of=lambda n: log.get(n, []))
        self.assertEqual((r["imported"], r["watch"], r["conservative"]), (1, ["QA"], []))   # not SPLIT/irreversible
        self.assertEqual([x["decision_id"] for x in r["rejected"]], ["D99"])

    def test_m4_partial_with_stakes_high_is_confirm(self):
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="partial", anchors={"goal": ANCHOR_OK}),
                                                     "STAKES": stakes("high")})
        h.p.journal = h.journal
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        pend = [b for b in h.decisions_of("ask:readiness") if b.get("status") == "pending-human"][0]
        self.assertEqual(pend.get("raised_by"), "confirm")

    def test_m7_stakes_reason_is_withheld_before_a_blind_question(self):
        h = _cons(K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="partial", anchors={"goal": ANCHOR_OK}),
                                                           "STAKES": stakes("low", reason="only the login widget moves")}),
                  "KICKOFF")
        h.p.journal = h.journal
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        st = h.decisions_of("STAKES")[-1]
        self.assertNotIn("login widget", st.get("reason"))
        self.assertTrue(st.get("reason_sha"))
        pend = [b for b in DecisionLog.load(h.gh.comments(7)).blocks
                if b.get("status") == "pending-human" and b.get("raised_by") == "confirm"][0]
        did = ASK.answer(h.decisions, h.writer, 7, pend.id, "i1", journal=h.journal)
        res = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.id == did][0]
        self.assertIn("only the login widget moves", res.get("revealed_question") or "")

    def test_m7_no_blind_question_keeps_the_reason(self):
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="partial", anchors={"goal": ANCHOR_OK}),
                                                     "STAKES": stakes("low", reason="only the login widget moves")})
        h.p.valves, h.p._first_sprint = {}, False
        h.p.journal = h.journal
        try:
            A.run(h.p)
        except AssertionError:
            pass                                                           # later roles are not this test's
        self.assertEqual(h.decisions_of("STAKES")[-1].get("reason"), "only the login widget moves")


if __name__ == "__main__":
    unittest.main()
