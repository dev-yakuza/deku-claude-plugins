"""K5 review r4 — the leak check's aliases (M1), canonical token numbers (m1), fail-closed log read (m2), symmetric
mentions (m6).

M1  the judge writes its OWN ids (`I2`, `B`, `broad`): `coerce_kickoff` rewrites them to the engine tokens in every
    judge text a person sees (`choice_needed`, the surface question, the close line), and `predict.leak` treats the
    engine token, the judge id and the full (untruncated) summary as names of the option — case-insensitive, whole
    word (a one-letter id in its own case: `a` is an article).
m1  `i<n>` numbers follow a canonical content order (normalized summary, then a hash of the judge id) — the same
    interpretations listed in another order get the same tokens; the mapping is journaled (`kickoff-tokens`).
m2  a decision log that cannot be read refuses the blind answer.
(m3 / m4 — test_k5_r4_answer.py)
m6  a text naming every option equally (no preference word) is neutral.
K6 r4: KICKOFF questions are asked openly (`PF.OPEN_GROUPS`) — the leak machinery is exercised here on a blind
(ESCALATE) question carrying a coerced KICKOFF's options and aliases.
"""

import json
import unittest

import _util  # noqa: F401
from _k4 import K4, evidence, kickoff
from test_k5_cli import Env

from guildcore import ask as ASK
from guildcore.decisions import DecisionLog
from guildcore.journal import JournalView
from workflows.dev import analysis as AN
from workflows.dev import predict as PF
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B


def _kick(ids, chosen, choice_needed, summaries=("로그인 화면에만 다크 모드 적용", "앱 전체 화면에 다크 모드 적용")):
    return AN.coerce_kickoff({"interpretations": [{"id": i, "summary": s} for i, s in zip(ids, summaries)],
                              "chosen": chosen,
                              "readiness": {"goal": {"rating": "unclear", "choice_needed": choice_needed}}},
                             ".", {}, [], [], [], ["developer"])


def _env(case):
    e = Env(case, labels=("guild:analyze",), unattended=False,
            config={"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": "off"}})
    p = e.h.p
    p.git_dir, p.valves = e.common, {}
    return e, p


def _ask_readiness(e, p, k):
    """analyze.py's attended readiness ask, built from a coerced KICKOFF (the repro path)."""
    opts = [{"token": i["id"], "label": B.one_line(i["summary"], 80)} for i in k.interpretations] + \
        [{"token": "stop", "label": "stop"}]
    what = "goal unclear — %s" % k.choice_needed["goal"]
    q = ASK.Question("escalation", what, opts, recommended=k.chosen, recommended_by="judge:opus", stakes="high",
                     aliases=k.aliases)
    r = B.ask(p, "analyze", q, what)
    ev = [kw for w, kw in e.h.events if w == "ask"][-1]
    blk = [b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.id == r.qid][0]
    return ev, blk


def _log_refuses(case, k, text):
    """K5r5-M1: the question text is withheld now, so the alias / case / summary knowledge of the leak check guards
    what still goes out BEFORE the answer — this stage's decision-log free text (defence in depth)."""
    e, p = _env(case)
    B.record_code(p, "analyze", "STAKES", "medium", reason=text)
    ev, blk = _ask_readiness(e, p, k)
    return ev, blk


class M1Aliases(unittest.TestCase):
    def test_repro_judge_ids_are_rewritten_and_the_preference_refused(self):
        # review-k5-r4 repro: `chosen: I2`, choice_needed "범위: I1 vs I2 — … I2 가 맞아 보임"
        k = _kick(["I1", "I2"], "I2", "범위: I1 vs I2 — 제목이 '앱' 이라 I2 가 맞아 보임")
        app = [i["id"] for i in k.interpretations if i["summary"].startswith("앱")][0]
        login = [i["id"] for i in k.interpretations if i["summary"].startswith("로그인")][0]
        self.assertEqual(k.chosen, app)
        # the person sees the SAME names as the options (engine tokens), never the judge's
        self.assertEqual(k.choice_needed["goal"], "범위: %s vs %s — 제목이 '앱' 이라 %s 가 맞아 보임" % (login, app, app))
        # K5r5-M1: as the question it is WITHHELD — the ask is blind and shows only the engine's wording
        e, p = _env(self)
        ev, blk = _ask_readiness(e, p, k)
        self.assertTrue(ev["predict_first"])
        self.assertNotIn("맞아", ev["question"])
        self.assertNotIn(app, ev["question"])
        self.assertTrue(blk.get("recommended_sha"))
        # the same sentence anywhere that still goes out (the decision log) refuses the blind answer
        ev, blk = _log_refuses(self, k, k.choice_needed["goal"])
        self.assertFalse(ev["predict_first"])                     # never a blind human judgment
        self.assertEqual(ev["recommended"], app)                  # shown openly
        self.assertIsNone(blk.get("predict_first"))
        self.assertIsNone(blk.get("recommended_sha"))
        self.assertTrue(blk.get("predict_first_refused").startswith("decision-log"), blk.get("predict_first_refused"))

    def test_three_id_styles_with_a_preference_are_refused(self):
        for ids, chosen, text in ((["I1", "I2"], "I2", "I2 가 맞아 보임"),
                                  (["A", "B"], "B", "범위가 애매함 — B안이 적절해 보임"),
                                  (["narrow", "broad"], "broad", "Broad seems right given the title")):
            with self.subTest(ids=ids):
                k = _kick(ids, chosen, text)
                ev, blk = _log_refuses(self, k, k.choice_needed["goal"])
                self.assertFalse(ev["predict_first"], ev["question"])
                self.assertTrue(blk.get("predict_first_refused"))

    def test_judge_id_alias_without_rewrite_is_still_caught(self):
        # the leak check itself knows the judge id (a text the coercion did not rewrite)
        k = _kick(["I1", "I2"], "I2", "범위 선택")
        orig = [i["orig"] for i in k.interpretations if i["id"] == k.chosen][0]
        ev, blk = _log_refuses(self, k, "판단 메모: %s 쪽" % orig.lower())
        self.assertFalse(ev["predict_first"])
        self.assertTrue(blk.get("predict_first_refused").startswith("decision-log"))

    def test_full_summary_beyond_the_label_cut_is_caught(self):
        long_a = "앱 전체 화면에 다크 모드를 적용하고 설정 화면에서 사용자가 시스템 테마를 따를지 직접 고를지 선택할 수 있게 하며 저장은 기기 로컬 저장소에만 하고 서버 동기화는 하지 않는다"
        # K6 r2 M3: no dash aside — the one-line cap would cut an aside mid-clause, which refuses at the label
        # (before the decision-log check this test is about)
        long_b = "로그인 화면에만 다크 모드를 적용하고 나머지 화면은 지금의 밝은 테마를 유지하며 설정 화면은 바꾸지 않고 범위를 최소화해 이번 스프린트 안에 끝낼 수 있게 한다"
        k = _kick(["I1", "I2"], "I1", "범위 선택", summaries=(long_a, long_b))
        rec = [i for i in k.interpretations if i["id"] == k.chosen][0]
        opts = [{"token": i["id"], "label": B.one_line(i["summary"], 80)} for i in k.interpretations] + \
            [{"token": "stop", "label": "stop"}]
        self.assertTrue(any(o["label"].endswith("…") for o in opts))  # the label is cut
        q = ASK.Question("readiness", "x", opts, recommended=k.chosen, aliases=k.aliases)
        self.assertTrue(PF._Names(q).names_rec("판단은 '%s' 로 읽음" % rec["summary"], markers=False))
        ev, blk = _log_refuses(self, k, "판단은 '%s' 로 읽음" % rec["summary"])
        self.assertTrue(blk.get("predict_first_refused").startswith("decision-log"))

    def test_token_match_is_case_insensitive(self):
        opts = [{"token": "i1", "label": "narrow reading"}, {"token": "i2", "label": "broad reading"},
                {"token": "stop", "label": "stop"}]
        q = ASK.Question("escalation", "x", opts, recommended="i2")
        self.assertTrue(PF._Names(q).names_rec("goal unclear — I2 looks right", markers=False))
        e, p = _env(self)
        B.record_code(p, "analyze", "STAKES", "medium", reason="goal unclear — I2 looks right")
        PF.apply(p, q, "analyze")
        self.assertFalse(q.predict_first)

    def test_one_letter_id_is_not_an_article(self):
        k = _kick(["A", "B"], "A", "whether a user can pick a theme")
        self.assertEqual(k.choice_needed["goal"], "whether a user can pick a theme")   # `a` is not rewritten
        e, p = _env(self)
        ev, blk = _ask_readiness(e, p, k)
        self.assertTrue(ev["predict_first"], blk.get("predict_first_refused"))
        self.assertEqual(blk.get("predict_first"), "high-risk")

    def test_a_judge_id_spelling_another_token_never_chains(self):
        # the judge called its interpretations i1/i2 in the OTHER order than the canonical numbering
        k = _kick(["i1", "i2"], "i1", "i1 vs i2", summaries=("zz last by content", "aa first by content"))
        by_sum = dict((i["summary"], i["id"]) for i in k.interpretations)
        self.assertEqual(by_sum, {"aa first by content": "i1", "zz last by content": "i2"})
        self.assertEqual(k.choice_needed["goal"], "i2 vs i1")     # judge i1 = engine i2, simultaneously swapped
        self.assertEqual(k.chosen, "i2")


class M6Symmetric(unittest.TestCase):
    def test_symmetric_mention_stays_blind(self):
        k = _kick(["I1", "I2"], "I2", "범위: I1 vs I2 중 어느 쪽인지 Issue 에 없음")
        ev, blk = _log_refuses(self, k, k.choice_needed["goal"])        # an even, plain mention goes out freely
        self.assertTrue(ev["predict_first"], blk.get("predict_first_refused"))
        self.assertNotIn("recommended", ev)

    def test_symmetric_mention_with_a_preference_word_is_refused(self):
        k = _kick(["I1", "I2"], "I2", "I1 은 좁고 I2 가 맞아 보임")
        ev, blk = _log_refuses(self, k, k.choice_needed["goal"])
        self.assertFalse(ev["predict_first"])
        self.assertTrue(blk.get("predict_first_refused"))


class M1TokenOrder(unittest.TestCase):
    def test_tokens_do_not_follow_the_judges_order(self):
        a = _kick(["X", "Y"], "X", "-", summaries=("show the count", "hide the count"))
        b = _kick(["Y", "X"], "X", "-", summaries=("hide the count", "show the count"))
        for k in (a, b):
            self.assertEqual([(i["id"], i["summary"]) for i in k.interpretations],
                             [("i1", "hide the count"), ("i2", "show the count")])
            self.assertEqual(k.chosen, "i2")
        # the judge's FIRST listed one is not i1 merely by being first
        self.assertEqual(a.token_map, [{"token": "i1", "orig": "Y"}, {"token": "i2", "orig": "X"}])

    def test_fallback_chosen_is_the_judges_first_listed_not_i1(self):
        k = _kick(["X", "Y"], "nope", "-", summaries=("show the count", "hide the count"))
        self.assertEqual(k.chosen, "i2")                          # "show" — the judge listed it first
        self.assertIn("chosen not among interpretations → i2", k.coerced)

    def test_stage_journals_the_mapping(self):
        h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear")})
        h.p.journal = h.journal
        A.run(h.p)
        ev = [x for x in JournalView.read(h.common, 7).entries if x.get("what") == "kickoff-tokens"]
        self.assertEqual(ev[-1]["map"], [{"token": "i1", "orig": "B"}, {"token": "i2", "orig": "A"}])
        self.assertEqual(ev[-1]["order"], "canonical")


class M2FailClosed(unittest.TestCase):
    def test_unreadable_decision_log_refuses_the_blind_answer(self):
        e, p = _env(self)

        class Broken(object):
            def _log(self):
                raise RuntimeError("502 Bad Gateway")
        p.decisions = Broken()
        q = ASK.Question("escalation", "goal unclear — choose", [{"token": "i1", "label": "narrow reading"},
                                                                 {"token": "i2", "label": "broad reading"},
                                                                 {"token": "stop", "label": "stop"}],
                         recommended="i2", recommended_by="judge:opus")
        PF.apply(p, q, "analyze")
        self.assertFalse(q.predict_first)
        self.assertTrue(q.blind_refused.startswith("decision-log unreadable"), q.blind_refused)


if __name__ == "__main__":
    unittest.main()
