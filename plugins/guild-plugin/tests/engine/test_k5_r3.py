"""K5 review r3 — predict-first question text (M1), a child's question on an attended parent's driver (M2), minors.

M1  a predict-first ask is rendered from its neutral wording with its options in the canonical order (never the
    judge's ranking); the one enforcement point (`predict.apply`, called by `B.ask` / `B.pause` only) refuses a blind
    answer — `predict_first_refused`, the recommendation shown openly, never counted by §9.5 — when the question, its
    options, the text going out with it or this stage's decision-log free text (STAKES / KICKOFF `reason`) names
    the recommendation; close-decided states it by being asked (inherent → never blind).
M2  ask / terminal events carry `issue`; the ask `qid` is issue-qualified (`#8/D2`); `dev answer` routes a
    qualified id to its Issue, refuses a bare id that the driver last saw as a child's question (hint names the
    child) and never lands on the parent's question with the same number; the re-run drives the child on; the
    predict-first reveal comes from the child's journal.
"""

import json
import re
import unittest

import _util  # noqa: F401
from _k4 import K4, evidence, kickoff
from test_k5_cli import Env
from test_k5_r1 import child_ports, kid

from guildcore import ask as ASK
from guildcore.decisions import DecisionLog, DecisionWriter
from guildcore.journal import Journal
from workflows.dev import cli as CLI
from workflows.dev import fsm as F
from workflows.dev import predict as PF
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages.base import StageResult

TOK = re.compile(r"(?<![A-Za-z0-9_])i1(?![A-Za-z0-9_])")
TOK2 = re.compile(r"(?<![A-Za-z0-9_])i2(?![A-Za-z0-9_])")


def _msg(e):
    ln = e.lines()[-1]
    return json.loads(ln.split(">>> ENGINE <<<")[-1]) if ">>> ENGINE <<<" in ln else json.loads(ln)


class M1NeutralText(unittest.TestCase):
    def _surface(self, **kk):
        cfg = {"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": "off",
                                                                   "attended_confirm_interpretation": True}}
        h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff(**kk)}, config=cfg)
        h.p.journal = h.journal
        return h, A.run(h.p)

    def test_surface_fallback_is_neutral_canonical_and_blind(self):
        h, r = self._surface()                                         # no judge question → the old fallback
        self.assertEqual(r.kind, StageResult.ASK)
        ask = [kw for w, kw in h.events if w == "ask"][-1]
        self.assertEqual(ask["kind"], "interpretation-surface")
        self.assertTrue(ask["predict_first"])
        self.assertNotIn("recommended", ask)
        # the chosen one is "show the count" (the judge's first) — K5r4-m1: tokens are numbered in the canonical
        # content order, so it is i2 ("hide …" < "show …"); nothing that goes out names it
        rendered = json.dumps(dict(ask, options=[o["label"] for o in ask["options"]]), ensure_ascii=False)
        self.assertIsNone(TOK2.search(rendered), rendered)
        self.assertNotIn("show the count", ask["question"])
        # canonical order: by label, stop last — not the judge's ranking (recommended-first)
        self.assertEqual([(o["token"], o["label"]) for o in ask["options"]],
                         [("i1", "hide the count"), ("i2", "show the count"), ("stop", "stop")])
        pend = [b for b in h.decisions_of("ask:interpretation-surface") if b.get("status") == "pending-human"][0]
        self.assertEqual(pend.get("predict_first"), "high-risk")
        self.assertIsNone(pend.get("predict_first_refused"))
        for f in ("question", "cause", "reason"):
            self.assertIsNone(TOK2.search(str(pend.get(f) or "")), f)
        self.assertIsNone(TOK2.search(r.line or ""))

    def test_leaky_question_is_withheld_not_shown(self):
        # the r3 repro: a question that names the hidden token — K5r5-M1: the judge's text is WITHHELD (the person
        # sees the engine's wording only) and revealed with the recommendation after the answer
        e = Env(self, labels=("guild:analyze",), unattended=False,
                config={"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": "off"}})
        p = e.h.p
        p.git_dir, p.valves, p.journal = e.common, {}, e.h.journal
        opts = [{"token": "i1", "label": "A reading"}, {"token": "i2", "label": "B reading"},
                {"token": "stop", "label": "stop"}]
        q = ASK.Question("interpretation-surface", "해석 확인: i2", opts, recommended="i2", recommended_by="judge:opus")
        r = B.ask(p, "analyze", q, "해석 확인: i2")
        ev = [kw for w, kw in e.h.events if w == "ask"][-1]
        self.assertTrue(ev["predict_first"])
        self.assertNotIn("recommended", ev)
        self.assertNotIn("i2", ev["question"])
        blk = [b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.id == r.qid][0]
        self.assertEqual(blk.get("predict_first"), "high-risk")
        self.assertIsNone(blk.get("recommended"))
        self.assertNotIn("i2", blk.get("question"))
        self.assertNotIn("i2", blk.get("cause") or "")
        did = ASK.answer(p.decisions, p.writer, 7, r.qid, "i1", journal=p.journal)
        res = [b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.id == did][0]
        self.assertEqual(res.get("recommended"), "i2")
        self.assertIn("해석 확인: i2", res.get("revealed_question"))

    def test_label_marker_and_reason_text_refuse(self):
        e = Env(self, labels=("guild:execute",), unattended=False)
        p = e.h.p
        p.git_dir, p.valves = e.common, {}
        mk = lambda labels: ASK.Question("escalation", "which way?", [{"token": "go", "label": labels[0]},  # noqa: E731
                                                                     {"token": "back", "label": labels[1]},
                                                                     {"token": "stop", "label": "stop"}],
                                         recommended="go", recommended_by="judge:sonnet")
        q1 = PF.apply(p, mk(["go on (권장)", "go back"]), "execute")
        self.assertFalse(q1.predict_first)
        self.assertTrue(q1.blind_refused.startswith("options"))
        # K5r5-M1: a text that goes out with the question is the judge's — withheld, so the answer stays blind
        q2 = PF.apply(p, mk(["proceed", "revert"]), "execute", texts=("the judge leans to go",))
        self.assertTrue(q2.predict_first)
        self.assertIn("the judge leans to go", PF.withheld_text(q2))
        q3 = PF.apply(p, mk(["proceed", "revert"]), "execute", texts=("choose: go = proceed | back = revert",))
        self.assertTrue(q3.predict_first)                                # an enumeration of EVERY option is neutral
        q4 = PF.apply(p, mk(["proceed unlike back", "revert"]), "execute")
        self.assertTrue(q4.blind_refused.startswith("options"))         # a label comparing with another option
        # K6 r1 M4 → K6 r2 M3: the same comparison as a dash ASIDE is never shown blind — and never dropped silently
        # either (not a remark, not a scope): the blind answer is refused (shown openly, never counted), no leak
        q5 = PF.apply(p, mk(["proceed — unlike back", "revert"]), "execute")
        self.assertFalse(q5.predict_first)
        self.assertTrue(q5.blind_refused.startswith("label-evaluative"), q5.blind_refused)
        # a remark aside (about the request) is still cut and the answer stays blind
        q6 = PF.apply(p, mk(["proceed — as the request asks", "revert"]), "execute")
        self.assertTrue(q6.predict_first)
        self.assertEqual(sorted(o["label"] for o in q6.options if o["token"] != "stop"), ["proceed", "revert"])

    def test_stakes_reason_naming_the_chosen_refuses_the_pause(self):
        # r3-m1/m2: free text this Issue's decision log already shows for the stage (STAKES / KICKOFF reason)
        e = Env(self, labels=("guild:analyze",))
        p = e.h.p
        p.git_dir, p.valves = e.common, {}
        B.record_code(p, "analyze", "STAKES", "medium", reason="local: taking i1 only touches one widget")
        opts = [{"token": "i1", "label": "show the count"}, {"token": "i2", "label": "hide the count"},
                {"token": "stop", "label": "stop"}]
        q = ASK.Question("readiness", "goal partial — choose", opts, recommended="i1", recommended_by="judge:opus")
        r = B.pause(p, "analyze", "ambiguity", "goal partial", "ambiguity: goal partial", question=q)
        blk = [b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.id == r.qid][0]
        self.assertIsNone(blk.get("predict_first"))
        self.assertTrue(blk.get("predict_first_refused").startswith("decision-log"))

    def test_unattended_readiness_pause_enumerates_in_canonical_order_and_stays_blind(self):
        from _k4 import stakes
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="partial"), "STAKES": stakes("high")})
        h.p.journal = h.journal
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        pend = [b for b in h.decisions_of("ask:readiness") if b.get("status") == "pending-human"][0]
        self.assertEqual(pend.get("predict_first"), "high-risk")
        body = [c["body"] for c in h.gh.comments(7) if "guild:needs-human" in c["body"]][-1]
        self.assertLess(body.index("i1 = hide the count"), body.index("i2 = show the count"))

    def test_close_decided_is_never_blind(self):
        h, r = self._surface(close={"decide": "completed", "line": "already shipped in #3"})
        ask = [kw for w, kw in h.events if w == "ask"][-1]
        self.assertEqual(ask["kind"], "close-decided")
        self.assertFalse(ask["predict_first"])
        pend = [b for b in h.decisions_of("ask:close-decided") if b.get("status") == "pending-human"][0]
        self.assertIsNone(pend.get("predict_first"))
        self.assertTrue(pend.get("predict_first_refused").startswith("inherent"))


class M2ChildAsk(unittest.TestCase):
    def _env(self, rec=None):
        e = Env(self, labels=("guild:children",), issues={"8": kid(8)}, unattended=False)
        e.h.p.git_dir = e.common
        e.h.p.journal = e.h.journal
        base = child_ports(e, unattended=False)
        kids = {}

        def pf(n, stage, variant=None):
            if n == e.h.n:
                return e.h.p
            if n not in kids:
                c = base(n, stage, variant)
                c.journal = Journal(e.common, n, e.h.clock)
                c.valves = {}
                kids[n] = c
            return kids[n]
        e.d.ports_for = pf
        self.seen = []

        def an(p, **k):
            blk, res = B.pending_answer(p, "analyze", "escalation")
            if res is not None:
                self.seen.append((p.issue, res.get("choice")))
                return StageResult(StageResult.HOLD, line="child #%d answered" % p.issue)
            q = ASK.Question("escalation", "child #%d: which way?" % p.issue,
                             [{"token": "go", "label": "go"}, {"token": "stop", "label": "stop"}],
                             recommended=rec, recommended_by="judge:sonnet" if rec else None)
            return B.ask(p, "analyze", q, "which way?")
        self.drive = lambda: F.Driver(pf, unattended=False, stages={"analyze": an}, events=e.h.p.events).run(7)
        return e

    def test_event_names_the_child_and_a_bare_id_never_lands_on_the_parent(self):
        e = self._env()
        out = self.drive()
        self.assertEqual(out.result.kind, "ASK")
        ask = [kw for w, kw in e.h.events if w == "ask"][-1]
        bare = ask["id"]
        self.assertEqual((ask["issue"], ask["qid"]), (8, "#8/%s" % bare))
        # the parent gets a pending question with the SAME D-number — the trap
        while True:
            pid = e.h.decisions.record(ASK.Question("escalation", "parent?", [{"token": "go", "label": "go"},
                                                    {"token": "stop", "label": "stop"}]).pending_fields(stage="children"))
            if pid == bare or int(pid[1:]) > int(bare[1:]):
                break
        # the ask event lives on #7's stream (the real worker's Events) — the CLI reads it there
        from guildcore import worker as W
        W.Events(e.common, 7).emit("ask", "t", **{k: v for k, v in ask.items() if k not in ("seq", "t", "type")})
        self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", bare, "--choice", "go"], e.d), 64)
        msg = _msg(e)
        self.assertEqual(msg["child"], 8)
        self.assertIn("--issue 8 --qid #8/%s" % bare, msg["error"])
        log7 = DecisionLog.load(e.h.gh.comments(7))
        self.assertFalse([b for b in log7.blocks if b.get("resolves") == bare])          # parent untouched
        # a qualified id of another Issue is never applied to #7 even when sent with --issue 7 … it is routed
        self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", ask["qid"], "--choice", "go"], e.d), 0)
        msg = _msg(e)
        self.assertEqual((msg["routed_to"], msg["qid"]), (8, ask["qid"]))
        self.assertFalse([b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.get("resolves") == bare])
        log8 = DecisionLog.load(e.h.gh.comments(8))
        self.assertEqual([b.get("choice") for b in log8.blocks if b.get("resolves") == bare], ["go"])

    def test_driver_path_answers_on_the_child_and_reveals_from_its_journal(self):
        e = self._env(rec="go")
        self.drive()
        ask = [kw for w, kw in e.h.events if w == "ask"][-1]
        self.assertTrue(ask["predict_first"])                            # escalation = high-risk
        self.assertNotIn("recommended", ask)
        # dev.md: --issue <the event's issue> --qid <the event's qid>
        rc = CLI.main(["answer", "--issue", str(ask["issue"]), "--qid", ask["qid"], "--choice", "go"], e.d)
        self.assertEqual(rc, 0, e.out.getvalue())
        self.assertEqual(_msg(e)["revealed"]["recommended"], "go")
        self.assertNotIn("routed_to", _msg(e))
        # the re-run (dev.md step 1 on #7) drives the child on with the answer — no new question
        n_asks = len([1 for w, _k in e.h.events if w == "ask"])
        self.drive()
        self.assertEqual(self.seen, [(8, "go")])
        self.assertEqual(len([1 for w, _k in e.h.events if w == "ask"]), n_asks)

    def test_ask_and_answer_reject_a_mismatched_or_malformed_id(self):
        e = self._env()
        self.assertEqual(CLI.main(["answer", "--issue", "7", "--qid", "#8/X2", "--choice", "go"], e.d), 64)
        dw = DecisionWriter(e.h.writer, 7, e.h.clock)
        with self.assertRaises(ValueError):
            ASK.answer(dw, e.h.writer, 7, "#8/D1", "go")

    def test_driven_child_hint_names_the_qualified_answer(self):
        from guildcore import worker as W
        e = self._env()
        lk = W.IssueLock(e.common, 8)
        self.assertTrue(lk.acquire("attended", driven_by=7))
        self.addCleanup(lk.release)
        self.assertEqual(CLI.main(["run", "--issue", "8", "--attended"], e.d), 0)
        hint = _msg(e)["hint"]
        self.assertIn("dev answer --issue 8 --qid #8/D<n>", hint)


class Minors(unittest.TestCase):
    def test_m7_go_predicate_is_line_anchored(self):
        head = "<!-- guild:note -->\nfirst-sprint go/no-go\n"
        self.assertTrue(PF.is_go_note(head + "result: go\n"))
        self.assertTrue(PF.is_go_note(head + "result: go\r\nwhy: ok"))
        for bad in ("result: go-later\n", "result: no-go\n", "note that result: go is premature\n"):
            self.assertFalse(PF.is_go_note(head + bad), bad)
        self.assertFalse(PF.is_go_note("first-sprint go/no-go\nresult: go\n"))       # not a guild note

    def test_m4_reveal_unavailable_is_marked(self):
        e = Env(self, labels=("guild:execute",), unattended=False)
        p = e.h.p
        p.git_dir, p.valves = e.common, {}
        q = ASK.Question("escalation", "which way?", [{"token": "go", "label": "proceed"},
                                                      {"token": "stop", "label": "stop"}],
                         recommended="go", recommended_by="judge:sonnet")
        r = B.ask(p, "execute", q, "which way?")
        other = Journal(e.common, 99, e.h.clock)                         # another clone: no nonce here
        did = ASK.answer(p.decisions, p.writer, 7, r.qid, "stop", journal=other)
        res = [b for b in DecisionLog.load(e.h.gh.comments(7)).blocks if b.id == did][0]
        self.assertEqual(res.get("reveal"), "unavailable")
        self.assertIsNone(res.get("recommended"))


if __name__ == "__main__":
    unittest.main()
