"""K5 review r5 — M1 (a blind question evaluates nothing), M2 (wrong candidates), M3 (the count rule reaches the flow),
M4 (the grader's blind call and citations) and the minors (m1 lock wait, m2 shadow log, m3 TEST `=pass`, m4 untrusted
evidence, m5 lowercase one-letter ids, m6 a successful shadow through a resume).

M1  predict-first: everything shown before the answer is engine text (neutral template + option summaries); the
    judge's text is journaled and revealed with the recommendation; the leak check refuses any uneven mention
    (including an elimination that never names the recommendation) or an evaluative even one.
M2  `raised_by` on the pending block; a different blind answer is a sheet candidate, never a wrong by itself.
M3  `group.<g>.conservative` → that group's decision is a person's (ask / pause, blind) through the FSM; `watch` → all
    of the group on the sheet and the grader; the irreversible STAKES class reaches `--import`.
M4  call ① sees an allow-list (+ options), citations never the decision's own text, `ok` needs independent evidence.
"""

import csv
import io
import json
import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from _k2 import comment
from _k3 import XHarness, auditor, dev, finding
from _k4 import K4, decision, evidence, kickoff, out_role, stakes
from test_k3_execute_stage import GREEN, TL_DONE, exarb
from test_k4_fsm import driver
from test_k5_cli import Env
from test_k5_r4 import _ask_readiness, _env, _kick
from test_k5_r4_first_sprint import DISMISS, exarb_blocks

from guildcore import ask as ASK
from guildcore import valves as VALVES
from guildcore import worker as W
from guildcore.decisions import DecisionLog
from guildcore.journal import JournalView
from guildcore.records.decisions import DecisionBlock
from workflows.dev import analysis as AN
from workflows.dev import cli as CLI
from workflows.dev import grade as G
from workflows.dev import grader as GD
from workflows.dev import judging as JG
from workflows.dev import predict as PF
from workflows.dev import unattended_log as UL
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages import execute as X
from workflows.dev.stages.base import StageResult

NEG = ("I1 은 제목('앱')과 맞지 않음", "B안이 아니라면 범위가 너무 넓음")


def blk(n, **f):
    return DecisionBlock(n, list(f.items()))


class M1Withheld(unittest.TestCase):
    def test_repro_elimination_is_never_shown_before_the_answer(self):
        # review-k5-r5 neg_leak: the elimination sentence used to go out as the question, recorded blind
        for text, ids, chosen in ((NEG[0], ["I1", "I2"], "I2"), (NEG[1], ["A", "B"], "A")):
            with self.subTest(text=text):
                k = _kick(ids, chosen, text)
                e, p = _env(self)
                p.journal = e.h.journal
                ev, blk_ = _ask_readiness(e, p, k)
                self.assertTrue(ev["predict_first"])
                self.assertEqual(ev["question"], "#7: readiness — 어느 선택지로 진행할까요?")
                self.assertEqual(ev["context_lines"], [])
                shown = json.dumps([ev["question"], blk_.get("question"), blk_.get("cause")], ensure_ascii=False)
                for w in ("맞지", "아니라면", "i1", "i2"):
                    self.assertNotIn(w, shown)
                # revealed only after the answer, with the recommendation
                did = ASK.answer(p.decisions, p.writer, 7, blk_.id, "i1", journal=p.journal)
                res = [b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.id == did][0]
                self.assertEqual(res.get("recommended"), k.chosen)
                self.assertIn(k.choice_needed["goal"], res.get("revealed_question"))

    def test_elimination_in_text_that_still_goes_out_refuses(self):
        # defence in depth: the decision log is on GitHub before the answer
        for text, ids, chosen in ((NEG[0], ["I1", "I2"], "I2"), (NEG[1], ["A", "B"], "A")):
            with self.subTest(text=text):
                k = _kick(ids, chosen, "범위 선택")
                e, p = _env(self)
                B.record_code(p, "analyze", "STAKES", "medium", reason=AN.to_tokens(text, k.token_map))
                ev, b = _ask_readiness(e, p, k)
                self.assertFalse(ev["predict_first"])
                self.assertTrue(b.get("predict_first_refused").startswith("decision-log"))

    def test_names_rule_any_uneven_or_evaluative_mention(self):
        opts = [{"token": "i1", "label": "login screen only"}, {"token": "i2", "label": "the whole app"},
                {"token": "stop", "label": "stop"}]
        nm = PF._Names(ASK.Question("readiness", "x", opts, recommended="i2"))
        self.assertTrue(nm.names_rec("i1 은 맞지 않음", markers=False))            # recommendation named 0 times
        self.assertTrue(nm.names_rec("i1 seems too narrow", markers=False))
        self.assertTrue(nm.names_rec("i1 vs i2 — i1 is not it", markers=False))   # uneven
        self.assertTrue(nm.names_rec("i1 vs i2 — neither is weak", markers=False))  # even + evaluative
        self.assertFalse(nm.names_rec("범위: i1 vs i2 중 어느 쪽인지 Issue 에 없음", markers=False))
        self.assertFalse(nm.names_rec("goal unclear", markers=False))

    def test_unattended_readiness_pause_shows_engine_text_only(self):
        kk = kickoff(goal="unclear")
        kk.fields["readiness"]["goal"]["choice_needed"] = "A 는 제목과 맞지 않음"
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kk, "STAKES": stakes("high")})
        h.p.journal = h.journal
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        pend = [b for b in h.decisions_of("ask:readiness") if b.get("status") == "pending-human"][0]
        self.assertEqual(pend.get("predict_first"), "high-risk")
        body = [c["body"] for c in h.gh.comments(7) if "guild:needs-human" in c["body"]][-1]
        self.assertNotIn("맞지", body)
        self.assertIn("i1 = hide the count", body)                           # the option summaries stay
        st = h.decisions_of("STAKES")[0]
        self.assertEqual(st.get("question"), "Goal unclear")                  # the engine's words on GitHub
        self.assertNotIn("맞지", r.cause or "")
        ev = [x for x in JournalView.read(h.common, 7).entries if x.get("what") == "predict-first-nonce"][-1]
        self.assertIn("맞지 않음", ev.get("withheld"))


class M2RaisedBy(unittest.TestCase):
    def test_attended_unclear_is_judge_raised(self):
        h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear")})
        A.run(h.p)
        pend = [b for b in h.decisions_of("ask:readiness") if b.get("status") == "pending-human"][0]
        self.assertEqual(pend.get("raised_by"), "judge-unclear")

    def test_first_sprint_confirmation_is_confirm_and_judge_surface_is_not(self):
        for surface, want in ((False, "confirm"), (True, "judge-surface")):
            with self.subTest(surface=surface):
                h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff(surface=surface)})
                h.p._first_sprint = True
                A.run(h.p)
                pend = [b for b in h.decisions_of("ask:interpretation-surface")
                        if b.get("status") == "pending-human"][0]
                self.assertEqual(pend.get("raised_by"), want)

    def test_judge_raised_mismatch_is_no_candidate(self):
        log = [blk(1, point="ask:readiness", kind="readiness", stage="analyze", by="code", status="pending-human",
                   predict_first="high-risk", recommended_sha="x", raised_by="judge-unclear"),
               blk(2, point="ask:readiness", kind="readiness", stage="analyze", by="human", choice="i1",
                   resolves="D1", recommended="i2", nonce="n")]
        self.assertEqual(G.predict_first_judgments(log, 7), ([], []))


def _cons(h, *groups):
    h.p.valves = dict(("group.%s.conservative" % g.replace(":", "-"), True) for g in groups)
    h.p.git_dir = h.common
    return h


def _answer(h, line, cid=900):
    it = h.issue()
    it["comments"].append(comment(line, cid, at="2026-11-16T01:00:00Z"))
    it["labels"] = [lb for lb in it["labels"] if lb["name"] != "guild:needs-human"]
    it["timeline"].append({"id": cid, "event": "unlabeled", "label": {"name": "guild:needs-human"},
                           "created_at": "2026-11-16T01:00:01Z", "actor": {"login": "owner"}})


DESIGN_STUB = {"design": lambda p, **k: StageResult(StageResult.PAUSE, cause="design stub")}


class M3ConservativePath(unittest.TestCase):
    def test_stakes_conservative_goes_to_a_person_through_the_fsm(self):
        h = _cons(K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear"), "STAKES": stakes("low")}),
                  "STAKES")
        h.p.journal = h.journal
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        pend = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("kind") == "group-conservative"][0]
        self.assertEqual((pend.get("group"), pend.get("raised_by"), pend.get("stage")), ("STAKES", "confirm", "analyze"))
        self.assertTrue(pend.get("predict_first"))                           # the judge's `low` is sealed
        self.assertIsNone(pend.get("recommended"))
        self.assertFalse(h.decisions_of("STAKES"))                           # nothing decided yet
        self.assertIn("guild:needs-human", h.labels())
        body = [c["body"] for c in h.gh.comments(7) if "guild:needs-human" in c["body"]][-1]
        self.assertNotIn("choose goal", body)                                # the judge's text is withheld
        # the person answers `high` (blind) → STAKES high → the readiness question (a person again)
        _answer(h, "guild-answer: %s high" % pend.id)
        h.judges["KICKOFF"] = kickoff(goal="unclear")
        h.roles += [evidence(self)]
        out = driver(h).run(7)
        st = h.decisions_of("STAKES")[-1]
        self.assertEqual((st.get("choice"), st.get("by"), st.get("raw_choice"), st.get("coerced_by")),
                         ("high", "human", "low", "conservative"))
        self.assertTrue([b for b in h.decisions_of("ask:readiness") if b.get("status") == "pending-human"])
        res = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("resolves") == pend.id][0]
        self.assertEqual(res.get("recommended"), "low")                     # revealed after the answer
        # a different blind answer on an engine-raised question → a §9.5 wrong CANDIDATE, nothing counted
        ok, cands = G.predict_first_judgments(DecisionLog.load(h.gh.comments(7)).blocks, 7)
        self.assertEqual(([r["group"] for r in cands], ok), (["STAKES"], []))

    def test_without_the_valve_stakes_low_proceeds(self):
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear"), "STAKES": stakes("low"),
                                                     "HANDOFF": []})
        h.p.valves, h.p._first_sprint = {}, False
        h.roles += [out_role(self, "DONE", ac_patch=[])]
        driver(h, DESIGN_STUB).run(7)
        self.assertEqual(h.decisions_of("STAKES")[-1].get("choice"), "low")
        self.assertFalse([b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("kind") == "group-conservative"])

    def test_conservative_default_choice_needs_no_person(self):
        h = _cons(K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear"), "STAKES": stakes("high")}),
                  "STAKES")
        driver(h).run(7)
        self.assertEqual(h.decisions_of("STAKES")[-1].get("by"), "judge:opus")   # already the safe side
        self.assertFalse([b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("kind") == "group-conservative"])

    def test_attended_any_gated_group_asks_blind_and_takes_the_answer(self):
        seen = []

        def stage(p, **k):
            d = p.judge(JG.spec(p, "QA", [("x", "y")], "analyze", "Q2.5"))
            seen.append((d.choice, d.by))
            return StageResult(StageResult.PAUSE, cause="after QA: %s" % d.choice)
        h = _cons(K4(self, unattended=False, judges={"QA": decision("pass", {"verdict": "pass", "quality_bar_met": "yes"})}), "QA")
        h.p.journal = h.journal
        out = driver(h, {"analyze": stage}, unattended=False).run(7)
        self.assertEqual(out.result.kind, StageResult.ASK)
        ev = [kw for w, kw in h.events if w == "ask"][-1]
        self.assertEqual((ev["kind"], ev["predict_first"]), ("group-conservative", True))
        self.assertNotIn("recommended", ev)
        self.assertEqual([o["token"] for o in ev["options"]], ["block", "pass", "stop"])
        self.assertEqual(seen, [])
        ASK.answer(h.decisions, h.writer, 7, ev["id"], "block", journal=h.journal)
        driver(h, {"analyze": stage}, unattended=False).run(7)
        self.assertEqual(seen, [("block", "human")])

    def test_stop_holds(self):
        h = _cons(K4(self, unattended=False, judges={"QA": decision("pass", {"verdict": "pass", "quality_bar_met": "yes"})}), "QA")
        stage = lambda p, **k: (p.judge(JG.spec(p, "QA", [("x", "y")], "analyze", "Q2.5")),  # noqa: E731
                                StageResult(StageResult.PAUSE, cause="x"))[1]
        driver(h, {"analyze": stage}, unattended=False).run(7)
        ev = [kw for w, kw in h.events if w == "ask"][-1]
        ASK.answer(h.decisions, h.writer, 7, ev["id"], "stop")
        out = driver(h, {"analyze": stage}, unattended=False).run(7)
        self.assertEqual(out.result.kind, StageResult.HOLD)

    def test_shadow_is_never_gated(self):
        h = _cons(K4(self, judges={"HANDOFF": decision("ok", {"verdict": "ok"})}), "HANDOFF")
        spec = JG.spec(h.p, "HANDOFF", [("x", "y")], "analyze", "HO", point="HANDOFF-SHADOW")
        self.assertEqual(h.p.judge(spec).by, "judge:sonnet")

    def test_kickoff_conservative_unattended_confirms_the_interpretation(self):
        h = _cons(K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff()}), "KICKOFF")
        h.p._first_sprint = False
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        pend = [b for b in h.decisions_of("ask:interpretation-surface") if b.get("status") == "pending-human"][0]
        self.assertEqual((pend.get("raised_by"), bool(pend.get("predict_first"))), ("confirm", True))

    def test_exarb_dismiss_conservative_forces_accept_in_both_modes(self):
        for unattended in (True, False):
            with self.subTest(unattended=unattended):
                h = XHarness(self, roles=[dev(), TL_DONE, auditor([finding()]), dev(), TL_DONE, auditor()],
                             suites=[GREEN, GREEN], judges={"EX-ARB": [exarb(**DISMISS)]}, unattended=unattended)
                h.p._first_sprint = False
                h.p.valves = {"group.EX-ARB-dismiss.conservative": True}
                X.run(h.p, "implement")
                b = exarb_blocks(h)[0]
                self.assertEqual((b.get("choice"), b.get("raw_choice"), b.get("coerced_by")),
                                 ("F1:accept", "F1:would-dismiss", "conservative"))

    def test_watch_puts_the_whole_group_on_the_sheet_and_the_grader(self):
        blocks = {7: [blk(i, point="TEST", stage="test", by="judge:sonnet",
                          choice="effective:AC #%d;uncovered:none" % i) for i in range(1, 9)]}
        grader = dict(((7, "D%d" % i), {"flagged": False, "given_info": "ok"}) for i in range(1, 9))
        sel = G.select(blocks, "o/r", False, 0.3, lambda i, b: None, grader=grader, watch={"TEST"})
        self.assertEqual([w for _i, _b, w in sel], ["watch: 100%"] * 8)
        gs = G.grader_select(blocks, "o/r", False, 0.0, lambda i, b: None, watch={"TEST"})
        self.assertEqual(len(gs), 8)

    def test_watch_and_irreversible_through_dev_grade(self):
        e = Env(self, config={"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": "off"}})
        G.apply_judgments(e.common, [{"decision_id": "D90", "issue": 9, "group": "TEST", "given_info": "wrong"}],
                          "o/r", "human")
        rec = e.h.decisions.record
        for i in (1, 2, 3):
            rec({"point": "TEST", "by": "judge:sonnet", "stage": "test", "choice": "effective:AC #%d;uncovered:none" % i})
        e.h.p.unattended = True
        from workflows.dev import arbitration as ARB
        e.h.p.judge = lambda spec: stakes("low")
        ARB.stakes(e.h.p, "analyze", "J-AN-07", "goal partial", [], "x", "", [], ["lib/db/migrations"], "A1.3")
        out = os.path.join(tmpdir(self), "sheet")
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out], e.d), 0)
        rows = list(csv.DictReader(open(os.path.join(out, "issues.csv"))))
        self.assertEqual(sorted(r["evidence"].split(";")[0] for r in rows if r["group"] == "TEST"), ["watch: 100%"] * 3)
        st = [r for r in rows if r["group"] == "STAKES"][0]
        self.assertEqual(st["irreversible"], "true")
        st["given_info"] = "wrong"                         # one confirmed wrong in the irreversible class
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=G.COLUMNS)
        w.writeheader()
        w.writerow(st)
        p = os.path.join(out, "filled.csv")
        with open(p, "w") as fh:
            fh.write(buf.getvalue())
        self.assertEqual(CLI.main(["grade", "--import", p], e.d), 0)
        imp = json.loads(e.lines()[-1].split(">>> ENGINE <<<")[-1])
        self.assertEqual(imp["conservative"], ["STAKES"])
        self.assertTrue(VALVES.load(e.common)["auto"].get("group.STAKES.conservative"))


class _Seen(object):
    def __init__(self):
        self.specs = []

    def __call__(self, spec):
        self.specs.append(spec)
        from guildcore.judges.runner import Decision
        if spec.schema is GD.BLIND_SCHEMA:
            return Decision("x", {"choice": "pass", "reason": "r", "cited_evidence": []}, "g", "d")
        return Decision("ok", {"given_info": "ok", "outcome": "unknown", "reason": "r",
                               "cited_evidence": self.cites}, "g", "d")


class M4Grader(unittest.TestCase):
    CASES = {
        "QA": blk(5, point="QA", refs="Q-DEFECT", stage="qa", by="judge:sonnet", choice="block",
                  reason="dark toggle missing", defects="Q1:true,Q2:false"),
        "TEST": blk(6, point="TEST", refs="T-AC-COVER", stage="test", by="judge:sonnet",
                    choice="effective:AC #1;uncovered:AC #2", checks="AC #1=pass,AC #2=unverified(no test)",
                    unsure_acs="AC #2"),
        "HANDOFF-SHADOW": blk(7, point="HANDOFF-SHADOW", refs="J-DEV-02", stage="design", by="judge:sonnet",
                              choice="upstream_gap", boundary="design→execute", shadow="true", signature="AC #3"),
        "DE-ARB": blk(8, point="DE-ARB", refs="J-DE-03", stage="design", by="judge:sonnet", choice="decide",
                      role="tech-lead", assumption="use local storage"),
    }

    def test_repro_blind_call_sees_an_allow_list_and_the_options(self):
        for name, b in self.CASES.items():
            with self.subTest(name=name):
                j = _Seen()
                j.cites = []
                GD.grade(j, b, 7, name, "post-hoc: none", "opus", "Issue text")
                dec = dict(j.specs[0].brief_parts)["decision"]
                for leak in ("Q1:true", "unsure_acs", "checks", "AC #3", "signature", "local storage", "dark toggle",
                             "block", "upstream_gap", "decide", "effective:AC #1"):
                    if leak in ("block", "upstream_gap", "decide") and "one of:" in dec:
                        dec_wo = dec.split("options:")[0]
                        self.assertNotIn(leak, dec_wo, name)
                        continue
                    self.assertNotIn(leak, dec, name)
                self.assertIn("options:", dec)
                # the reveal call carries the whole block
                self.assertIn(str(b.get("choice")), dict(j.specs[1].brief_parts)["engine_decision"])

    def test_options_by_group(self):
        self.assertIn("pass | block", GD.options_for("QA", self.CASES["QA"]))
        self.assertIn("ok | ok_with_assumption | upstream_gap", GD.options_for("HANDOFF", self.CASES["HANDOFF-SHADOW"]))
        self.assertIn("F1, F2", GD.options_for("EX-ARB:dismiss", blk(1, point="EX-ARB", refs="F1,F2")))
        self.assertIn("effective:", GD.options_for("TEST", self.CASES["TEST"]))

    def test_repro_own_text_citation_is_no_evidence(self):
        j = _Seen()
        j.cites = ["point: QA"]
        row = GD.grade(j, blk(5, point="QA", refs="Q-DEFECT,Q-FIXABLE", stage="qa", by="judge:sonnet", choice="pass",
                              reason="looks fine"), 7, "QA", "", "opus", "title only")
        self.assertEqual((row["given_info"], row["flagged"]), ("unsure", True))
        ex = blk(6, point="EX-ARB", refs="F1", stage="execute", by="judge:opus", choice="F1:accept")
        self.assertEqual(GD.settle(ex, {"given_info": "ok", "cited_evidence": ["refs: F1"]}, "#7\n(none collected)")[0],
                         "unsure")

    def test_normal_form_comparison(self):
        self.assertTrue(GD.same_choice("TEST", "effective: AC #1 ; uncovered: none", "effective:AC #1;uncovered:none"))
        self.assertFalse(GD.same_choice("TEST", "effective:AC #1,AC #2;uncovered:none", "effective:AC #1;uncovered:AC #2"))
        self.assertTrue(GD.same_choice("EX-ARB:accept", "F2:accept, F1:accept", "F1:accept,F2:accept"))
        self.assertFalse(GD.same_choice("EX-ARB:dismiss", "F1:accept", "F1:would-dismiss"))
        self.assertTrue(GD.same_choice("EX-ARB:dismiss", "F1:dismiss", "F1:would-dismiss"))
        self.assertTrue(GD.same_choice("QA", "Block — the toggle is missing", "block"))

    def test_untrusted_evidence_never_grounds_ok(self):
        b = blk(6, point="EX-ARB", refs="F1", stage="execute", by="judge:sonnet", choice="F1:accept")
        cite = ["F1 at lib/a.dart:3 was a real bug, fixed"]
        self.assertEqual(GD.settle(b, {"given_info": "ok", "cited_evidence": cite}, "#7",
                                   untrusted="comment by x (NONE, outsider): F1 at lib/a.dart:3 was a real bug, fixed")[0],
                         "unsure")
        self.assertEqual(GD.settle(b, {"given_info": "ok", "cited_evidence": cite},
                                   "comment by o (OWNER, member): F1 at lib/a.dart:3 was a real bug, fixed")[0], "ok")

    def test_collect_evidence_splits_by_three_valued_trust(self):
        e = Env(self)
        it = e.h.gh.fx["issues"]["7"]
        it["comments"] += [comment("member says AC #1 fine", 801),
                           dict(comment("outsider says ok", 802), author_association="NONE"),
                           dict(comment("unknown says ok", 803), author_association="")]
        _s, full, facts = G.collect_evidence(e.h.gh, 7, "o/r")
        self.assertIn("member says", facts["trusted"])
        self.assertNotIn("outsider says", facts["trusted"])
        self.assertIn("outsider says", facts["untrusted"])
        self.assertIn("unknown says", facts["untrusted"])
        self.assertIn(", unknown)", facts["untrusted"])
        self.assertIn(G.UNTRUSTED_HEAD, full)


class Minors(unittest.TestCase):
    def test_m1_answer_waits_for_the_lock_instead_of_the_event_stream(self):
        e, p = _env(self)
        q = ASK.Question("escalation", "which way?", [{"token": "go", "label": "go"}, {"token": "stop", "label": "stop"}])
        r = B.ask(p, "analyze", q, "which way?")
        lk = W.IssueLock(e.common, 7)
        lk.acquire("unattended")
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            if len(sleeps) == 2:
                lk.release()                     # the worker ends a moment later
        e.d.sleep = sleep
        self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", r.qid, "--choice", "go", "--wait-lock", "20"],
                                  e.d), 0)
        self.assertEqual(sleeps, [CLI.LOCK_POLL_S] * 2)
        self.assertTrue([b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.get("resolves") == r.qid])

    def test_m1_wait_lock_is_bounded(self):
        e, p = _env(self)
        q = ASK.Question("escalation", "which way?", [{"token": "go", "label": "go"}, {"token": "stop", "label": "stop"}])
        r = B.ask(p, "analyze", q, "which way?")
        lk = W.IssueLock(e.common, 7)
        lk.acquire("unattended")
        try:
            e.d.sleep = lambda s: None
            self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", r.qid, "--choice", "go", "--wait-lock", "6"],
                                      e.d), CLI.EXIT_BUSY)
        finally:
            lk.release()

    def test_m2_shadow_assumption_is_not_in_the_unattended_log(self):
        sh = blk(3, point="HANDOFF-SHADOW", stage="design", by="judge:sonnet", choice="ok_with_assumption",
                 shadow="true", assumption="AC 2 is covered by C1")
        live = blk(4, point="HANDOFF", stage="design", by="judge:sonnet", choice="ok_with_assumption",
                   assumption="AC 2 is covered by C1")
        self.assertFalse(UL._worthy(sh))
        self.assertTrue(UL._worthy(live))

    def test_m5_lowercase_one_letter_id_before_hangul(self):
        tm = [{"token": "i1", "orig": "A"}, {"token": "i2", "orig": "B"}]
        self.assertEqual(AN.to_tokens("b안이 아니라면, a plan; a는 좁음; A-F13", tm), "i2안이 아니라면, a plan; i1는 좁음; A-F13")
        self.assertTrue(AN.id_regex("B").search("b가 맞음"))
        self.assertFalse(AN.id_regex("A").search("a plan"))

    def test_m6_first_sprint_shadow_ok_survives_a_resume(self):
        # K4 FSM resume (answer line → design) with first-sprint ON and a HANDOFF `ok` answer: the successful shadow
        # block sits in the log next to the answered readiness question and the resume still reads the answer
        ok = decision("ok", {"verdict": "ok"})
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear"),
                                                     "STAKES": decision("high", {"level": "high"}), "HANDOFF": ok})
        h.p._first_sprint = True
        h.p.journal = h.journal
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        _answer(h, "guild-answer: %s i1" % r.qid)
        h.roles += [evidence(self), out_role(self, "DONE", ac_patch=[])]
        h.judges["KICKOFF"] = kickoff(goal="unclear")
        h.judges["KICKOFF"].fields["chosen"] = "B"         # K6 r3 M1: the judge takes the person's reading (B = i1)
        driver(h, DESIGN_STUB).run(7)
        self.assertIn("guild:design", h.labels())
        self.assertIn("- (선택) i1: hide the count", h.body_with("analyze:output"))
        sh = h.decisions_of("HANDOFF-SHADOW")
        self.assertEqual([(b.get("choice"), b.get("shadow")) for b in sh], [("ok", "true")])
        # the shadow block never answers or supersedes the question, and is off the PR's decision log
        res = [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("resolves") == r.qid]
        self.assertEqual([b.get("by") for b in res], ["human"])
        self.assertFalse(UL._worthy(sh[0]))


if __name__ == "__main__":
    unittest.main()
