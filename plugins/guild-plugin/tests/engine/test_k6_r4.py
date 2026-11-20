"""review-k6-r4 + the scope reduction (user decision 2026-11-20) — as table tests over the cases the findings name.

Scope  KICKOFF and STAKES leave predict-first blind counting (`predict.OPEN_GROUPS`): their questions are asked with the
       recommendation shown and marked `predict_first_counted: false — open: …`; every engine-raised KICKOFF reading
       question / STAKES gate question is a grading-sheet row (`inherent-gate`, the engine's pick, never the person's
       answer) and 5 person verdicts on those rows release the group (`unverified.OPEN_ASKED`). The sealing machinery
       is gone: the KICKOFF block carries `chosen` and its footprint, the STAKES block its reason and `irreversible`,
       openly — r4 M2 (STAKES irreversible via the gate field / level) and m3 (the close line before a blind reading
       question) have nothing left to leak into;
M1     `judge_took` (K6 r5: by STRUCTURE — the fixed id `person-reading`) — a judge that re-letters its readings and
       keeps its own pick under the person's old id pauses; one that takes the person's reading goes on;
M4     two unapplied reading answers: the answer to the LATEST question is carried, the older one retired with it — no
       permanent pause; the "reading not taken" pause offers `reask` (ask the reading again) besides `stop`;
m1     after `apply_reading` a later capture in the same run pairs each reading with ITS captured footprint;
m2     the conservative superset is a superset: no truncation that drops an irreversible / harness area (the KICKOFF
       block and the capture), an empty / non-existent own `areas` is no footprint, an unknown reading convenes every
       installed gate role, `safety_net_visual` / `po` / `skipped` are captured and applied;
M3     a scope set BY the source ("(제목 범위만)", "(per the title only)", "(requested screen only)") is never shown
       blind (refused) — while the r2 / r3 scope clauses over product nouns still are (table over both sets);
m4     a numeric rating inside a code-span-only aside refuses (`(`90%`)`, `(`p=0.9`)`, `(`0.9`)`); literals stay;
m6     a decision log with NO engine block (not read as trusted) never reconciles a candidate away;
r3 M4  kept: a `.claude/…` directory area is a harness hit.
"""

import json
import os
import tempfile
import unittest

import _util  # noqa: F401
import test_k5_r10 as R10
import test_k6_r1 as R1
import test_k6_r3 as R3
from _k1 import tmpdir
from _k2 import decision
from _k4 import K4, evidence, kickoff, out_role, stakes

from guildcore import ask as ASK
from guildcore import journal as J
from workflows.dev import analysis as AN
from workflows.dev import arbitration as ARB
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import predict as PF
from workflows.dev import unverified as UV
from workflows.dev.replay import label_audit as LA
from workflows.dev.stages import analyze as A
from workflows.dev.stages import design as DS
from workflows.dev.stages.base import StageResult

SUMM, REWORD, WIDE, EXTRA = R3.SUMM, R3.REWORD, R3.WIDE, R3.EXTRA
EXTRA_PO = dict(EXTRA, **{".claude/agents/product-owner.md": "# PO\n"})
_blocks, _pending, _kick, _token, _run1, _took = R3._blocks, R3._pending, R3._kick, R3._token, R3._run1, R3._took


def _applied(h):
    return set(b.get("refs") for b in _blocks(h) if b.get("point") == "applied")


class OpenGroups(unittest.TestCase):
    def test_the_groups_and_their_release_path(self):
        self.assertEqual(sorted(PF.OPEN_GROUPS), ["KICKOFF", "STAKES"])
        for g in ("KICKOFF", "STAKES"):
            self.assertNotIn(g, PF.HIGH_RISK)
            self.assertIn(g, UV.SHEET_RELEASED)
            self.assertIn(g, UV.OPEN_ASKED)
            self.assertEqual(UV.report(None)[[r["group"] for r in UV.report(None)].index(g)]["release_by"],
                             "sheet verdicts")

    def test_the_sealing_code_is_gone(self):
        for mod, names in ((PF, ("sealed", "kickoff_chosen_fields", "kickoff_footprint_sealed", "kickoff_readings",
                                 "kickoff_readings_sealed", "earlier_reading", "KICKOFF_FOOTPRINT",
                                 "FOOTPRINT_WITHHELD", "READING_KINDS")),
                           (ASK, ("seal_value", "seal_check", "READINGS_FIELD")),
                           (ARB, ("reveal_sealed_stakes", "withhold_for_next", "IRREVERSIBLE_FIELD", "REVEAL"))):
            for n in names:
                with self.subTest(name=n):
                    self.assertFalse(hasattr(mod, n))
        for form in ("readiness-unclear", "interpretation", "readiness-high", "kickoff-conservative"):
            self.assertNotIn(form, PF.NEUTRAL_FORMS)

    def test_every_kickoff_question_is_open(self):
        """attended confirmation · attended unclear · unattended conservative · unattended STAKES high."""
        cases = (("confirm", False, _kick("A"), {}), ("unclear", False, None, {}),
                 ("conservative", True, _kick("B"), {"group.KICKOFF.conservative": True}))
        for name, unattended, k, valves in cases:
            with self.subTest(case=name):
                if k is None:
                    k = kickoff(goal="unclear")
                h = K4(self, unattended=unattended, roles=[evidence(self, areas=WIDE)] * 2, judges={"KICKOFF": k},
                       extra_files=EXTRA)
                h.p._first_sprint = name == "confirm"
                h.p.valves = valves
                r = A.run(h.p)
                self.assertIn(r.kind, (StageResult.ASK, StageResult.PAUSE))
                q = _pending(h)[-1]
                self.assertIn(q.get("kind"), ("readiness", "interpretation-surface"))
                self.assertFalse(q.get("predict_first"))
                self.assertFalse(q.get("recommended_sha"))
                self.assertTrue(q.get("recommended"))
                self.assertTrue(str(q.get("predict_first_counted")).startswith("false — open: KICKOFF"), q.fields)
                kb = DS.kickoff_block(h.gh.comments(7))
                self.assertEqual(kb.get("chosen"), q.get("recommended"))
                self.assertTrue(kb.get("areas"))                                  # the footprint, openly
                self.assertFalse([kk for b in _blocks(h) for kk, _v in b.fields if kk.endswith("_sha") and
                                  kk != "recommended_sha"])

    def test_stakes_gate_questions_are_open(self):
        n = 0
        for group, x, y in R10.cases():
            if group != "STAKES":
                continue
            with self.subTest(option=x, judge=y):
                o = R10.run_case(self, group, x, y)
                qs = [b for b in o["all"] if b.get("kind") == CONS.KIND and b.get("status") == "pending-human"]
                self.assertTrue(qs)
                for q in qs:
                    n += 1
                    self.assertFalse(q.get("predict_first"))
                    self.assertEqual(q.get("recommended"), y)
                    self.assertTrue(str(q.get("predict_first_counted")).startswith("false — open: STAKES"))
                ok, rows = G.predict_first_judgments(o["all"], 7)
                self.assertEqual(ok, [])
                self.assertTrue(rows and all((r["group"], r["mode"], r["choice"]) == ("STAKES", G.INHERENT_MODE, y)
                                             for r in rows), rows)
                self.assertFalse(any(x in r["reason"] + r["evidence"] for r in rows if x != y))
        self.assertGreaterEqual(n, 4)

    def test_stakes_block_is_written_openly(self):
        """r4 M2 dissolved: the STAKES block and its gate carry `irreversible` and the reason as they are."""
        for pick in ("A", "B"):
            with self.subTest(pick=pick):
                k = kickoff(goal="unclear", areas=(("lib/settings",) if pick == "A" else ("lib/settings", "lib/db/local")))
                k.fields["interpretations"] = [{"id": "A", "summary": "설정 화면에 저장 옵션 추가"},
                                               {"id": "B", "summary": "설정과 함께 로컬 DB 스키마에 저장 옵션 추가"}]
                k.fields["chosen"] = pick
                h = K4(self, unattended=True, roles=[evidence(self, areas=("lib/settings",))] * 2,
                       judges={"KICKOFF": k, "STAKES": stakes("medium", "a settings toggle")}, extra_files=EXTRA)
                h.p.valves = {"group.KICKOFF.conservative": True}
                A.run(h.p)
                st = [b for b in _blocks(h) if b.get("point") == "STAKES"][0]
                self.assertEqual(st.get("reason"), "a settings toggle")
                self.assertEqual(st.get("irreversible"), "true" if pick == "B" else None)
                self.assertEqual(G.block_irreversible(st), pick == "B")
                self.assertIsNone(st.get("reason_sha"))
                self.assertIsNone(st.get("irreversible_sha"))

    def test_kickoff_rows_release_the_group(self):
        h, r = _run1(self, "A")                                   # first sprint → engine-raised confirmation
        q = _pending(h)[-1]
        self.assertEqual(q.get("raised_by"), "confirm")
        ASK.answer(h.decisions, h.writer, 7, q.id, _token(SUMM, "B"), journal=h.p.journal)
        ok, rows = G.predict_first_judgments(_blocks(h), 7)
        self.assertEqual(ok, [])
        self.assertEqual([(r_["group"], r_["mode"], r_["choice"]) for r_ in rows],
                         [("KICKOFF", G.INHERENT_MODE, _token(SUMM, "A"))])
        self.assertIn(SUMM["A"], rows[0]["reason"])                # the engine's reading, by its summary
        self.assertNotIn(SUMM["B"], json.dumps(rows[0], ensure_ascii=False))    # never the person's answer
        fixed, rej = G.verify_rows([dict(rows[0], mode="first-sprint", choice="x", given_info="ok")],
                                   lambda n: _blocks(h))
        self.assertEqual(rej, [])
        self.assertEqual((fixed[0]["mode"], fixed[0]["choice"]), (G.INHERENT_MODE, _token(SUMM, "A")))
        self.assertTrue(UV.counts(fixed[0], "human"))
        self.assertFalse(UV.counts(dict(fixed[0], mode="predict-first"), "predict-first"))
        self.assertFalse(UV.counts(dict(fixed[0], mode="first-sprint"), "human"))       # an ordinary sheet row
        common = tmpdir(self)
        row = lambda i: {"issue": i, "decision_id": "D%d" % i, "group": "KICKOFF", "mode": G.INHERENT_MODE,  # noqa: E731
                         "choice": "i1", "given_info": "ok"}
        G.apply_judgments(common, [], "o/r", "predict-first", candidates=[dict(row(9), given_info="")])
        G.apply_judgments(common, [row(i) for i in range(1, 6)], "o/r", "human")
        self.assertIn("KICKOFF", UV.pending(common))                # an open row still holds it
        out = G.apply_judgments(common, [row(9)], "o/r", "human")
        self.assertEqual(out.get("unverified_released"), ["KICKOFF"])

    def test_a_question_the_judge_raised_is_no_row(self):
        h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear")},
               extra_files=EXTRA)
        h.p._first_sprint = False
        A.run(h.p)
        q = _pending(h)[-1]
        self.assertEqual(q.get("raised_by"), "judge-unclear")
        ASK.answer(h.decisions, h.writer, 7, q.id, "i1")
        self.assertEqual(G.predict_first_judgments(_blocks(h), 7), ([], []))


class M1JudgeTookByContent(unittest.TestCase):
    CAP = [{"token": "i1", "orig": "B", "summary": SUMM["B"]}, {"token": "i2", "orig": "A", "summary": SUMM["A"]}]

    def test_table(self):
        """re-lettering × the pick it keeps × verbatim / re-worded summaries. K6 r5 M1: taking is STRUCTURAL — only
        `chosen` = the fixed engine id counts; the person's summary verbatim under any letter is no evidence."""
        ent = self.CAP[0]                                   # the person's reading: B = 앱 전체
        # K6 r6 M1: + "fixed-other-text" — the fixed id over the OTHER reading's text, the person's text under `A`
        # (verbatim: refuted by exact equality; re-worded: no equality to see — taken, as any re-wording is)
        for letters in ("same", "swapped", "fixed", "fixed-other-text"):
            for words in (SUMM, REWORD):
                for takes in (True, False):
                    ids = {"A": "A", "B": "B"} if letters == "same" else {"A": "B", "B": "A"} \
                        if letters == "swapped" else {"A": "A", "B": AN.PERSON_READING_ID}
                    texts = dict(words)
                    if letters == "fixed-other-text":
                        texts = {"A": words["B"], "B": words["A"]}
                    interps = [{"id": ids[r], "summary": texts[r]} for r in ("A", "B")]
                    chosen = ids["B"] if takes else ids["A"]
                    got = AN.judge_took({"chosen": chosen, "interpretations": interps}, ent, self.CAP)
                    want = takes and (letters == "fixed" or (letters == "fixed-other-text" and words is REWORD))
                    with self.subTest(letters=letters, reworded=words is REWORD, takes=takes):
                        self.assertEqual(got, want)

    def test_the_review_repro_unit(self):
        fields = {"chosen": "B", "interpretations": [{"id": "A", "summary": "앱 전체 다크 모드"},
                                                     {"id": "B", "summary": "설정 화면만 다크 모드"}]}
        self.assertFalse(AN.judge_took(fields, {"orig": "B", "summary": "앱 전체 다크 모드"}))

    def test_relettered_judge_keeping_its_pick_pauses(self):
        h, r = _run1(self, "A")
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, _token(SUMM, "B"), journal=h.p.journal)
        k2 = kickoff(ui=False, areas=("lib/settings",), ac=("only the settings screen turns dark",))
        k2.fields["interpretations"] = [{"id": "A", "summary": SUMM["B"]}, {"id": "B", "summary": SUMM["A"]}]
        k2.fields["chosen"] = "B"
        h.judges["KICKOFF"] = k2
        r2 = A.run(h.p)
        self.assertEqual(r2.kind, StageResult.ASK)
        self.assertIn("따르지 않음", _pending(h)[-1].get("question"))
        self.assertIsNone(h.body_with("analyze:output"))


class M4TwoAnswers(unittest.TestCase):
    def _two(self):
        def role(call):
            if call.role == "product-owner":
                return out_role(self, "DONE_WITH_CONCERNS", "success is vague", ac_patch=[])
            return evidence(self, areas=WIDE)
        an_po = decision("rerate_success", {"action": "rerate_success", "rating": "unclear", "reason": "vague"})
        kb = _kick("B")
        h = K4(self, unattended=False, roles=[role] * 10, judges={"KICKOFF": kb, "AN-PO": an_po}, extra_files=EXTRA_PO)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r4-"), 7, h.clock)
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        first = _pending(h)[-1]
        ASK.answer(h.decisions, h.writer, 7, first.id, _token(SUMM, "A"), journal=h.p.journal)
        k2 = _took("A", summ=REWORD)
        k2.fields["po"] = {"convene": True, "reason": "r"}
        h.judges["KICKOFF"] = k2
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)                       # AN-PO re-asks readiness
        second = _pending(h)[-1]
        self.assertEqual(second.get("kind"), "readiness")
        self.assertTrue(second.get("reading_i1"))
        ASK.answer(h.decisions, h.writer, 7, second.id, _token(SUMM, "B"), journal=h.p.journal)   # latest: B
        h.judges["AN-PO"] = decision("record", {"action": "record", "reason": "ok"})
        return h, first, second

    def test_the_latest_answer_is_carried(self):
        for pick, want in (("B", StageResult.ADVANCE), ("A", StageResult.ASK)):
            with self.subTest(judge=pick):
                h, first, second = self._two()
                # B: the judge takes the LATEST reading (handed under the fixed id); A: it keeps the older one
                h.judges["KICKOFF"] = _took("B", summ=REWORD) if pick == "B" else _kick("A", summ=REWORD)
                r = A.run(h.p)
                self.assertEqual(r.kind, want)
                if want == StageResult.ADVANCE:
                    self.assertIn("- (선택) %s: %s" % (_token(SUMM, "B"), SUMM["B"]), h.body_with("analyze:output"))
                    res = [b.id for b in _blocks(h) if b.get("by") == "human" and b.get("resolves") in
                           (first.id, second.id)]
                    self.assertTrue(set(res) <= _applied(h))                    # the older answer retired with it
                else:
                    self.assertIn("«%s»" % SUMM["B"], _pending(h)[-1].get("question"))   # the LATEST reading

    def test_reask_is_a_way_forward(self):
        h = K4(self, unattended=False, roles=[evidence(self, areas=WIDE)] * 6, judges={"KICKOFF": _kick("A")},
               extra_files=EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r4-"), 7, h.clock)
        A.run(h.p)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, _token(SUMM, "B"), journal=h.p.journal)
        h.judges["KICKOFF"] = _kick("A", summ=REWORD)               # the judge keeps its own pick
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        stop_q = _pending(h)[-1]
        self.assertEqual((stop_q.get("point"), stop_q.options()), (A.READING_STOP_POINT, ["reask", "stop"]))
        ASK.answer(h.decisions, h.writer, 7, stop_q.id, "reask", journal=h.p.journal)
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)            # the reading is asked again, openly
        again = _pending(h)[-1]
        self.assertEqual(again.get("kind"), "interpretation-surface")
        self.assertFalse(again.get("predict_first"))
        spent = [b.id for b in _blocks(h) if b.get("by") == "human" and b.get("resolves")]
        self.assertTrue(set(spent) <= _applied(h), (spent, _applied(h)))
        ASK.answer(h.decisions, h.writer, 7, again.id, again.get("recommended"), journal=h.p.journal)
        h.judges["KICKOFF"] = _took("A", summ=REWORD)                # takes the reading the person chose now
        self.assertEqual(A.run(h.p).kind, StageResult.ADVANCE)

    def test_reask_when_unattended(self):
        h = K4(self, unattended=True, roles=[evidence(self, areas=WIDE)] * 6, judges={"KICKOFF": _kick("A")},
               extra_files=EXTRA)
        h.p.valves = {"group.KICKOFF.conservative": True}
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r4-"), 7, h.clock)
        A.run(h.p)
        q = _pending(h)[-1]
        ASK.answer(h.decisions, h.writer, 7, q.id, _token(SUMM, "B"), journal=h.p.journal)
        h.judges["KICKOFF"] = _kick("A", summ=REWORD)
        h.p.valves = {}
        A.run(h.p)
        stop_q = _pending(h)[-1]
        ASK.answer(h.decisions, h.writer, 7, stop_q.id, "reask", journal=h.p.journal)
        self.assertEqual(A.run(h.p).kind, StageResult.PAUSE)
        again = _pending(h)[-1]
        self.assertEqual((again.get("kind"), again.get("raised_by")), ("interpretation-surface", "reask"))
        self.assertEqual(G.predict_first_judgments(_blocks(h), 7)[1][-1]["decision_id"], q.id)   # only the confirm one


class m1CaptureRekeyed(unittest.TestCase):
    def test_a_later_capture_keeps_each_reading_s_footprint(self):
        def role(call):
            if call.role == "product-owner":
                return out_role(self, "DONE_WITH_CONCERNS", "success is vague", ac_patch=[])
            return evidence(self, areas=WIDE)
        an_po = decision("rerate_success", {"action": "rerate_success", "rating": "unclear", "reason": "vague"})
        own_b = {"B": {"areas": ["lib/theme", "lib/app"], "ui_surface": True, "cast": {"participation": [], "gates": []}}}
        h = K4(self, unattended=False, roles=[role] * 8, judges={"KICKOFF": _kick("B", own=own_b), "AN-PO": an_po},
               extra_files=EXTRA_PO)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r4-"), 7, h.clock)
        A.run(h.p)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, _token(SUMM, "A"), journal=h.p.journal)
        own = {"A": {"areas": ["lib/settings"], "ui_surface": False, "cast": {"participation": [], "gates": []}}}
        k2 = _took("A", summ=REWORD, own=own)                      # re-worded: the canonical order flips
        k2.fields["po"] = {"convene": True, "reason": "r"}
        h.judges["KICKOFF"] = k2
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        cap, why = AN.captured(_pending(h)[-1])
        self.assertIsNone(why)
        by = dict((e["summary"], e) for e in cap)
        # B (the run-1 judge's pick) keeps the footprint captured at question 1 — never A's own (settings only)
        self.assertEqual(by[SUMM["B"]]["areas"], sorted(WIDE))
        self.assertTrue(by[SUMM["B"]]["ui_surface"])
        # A (the person's) — its question-1 capture: no own footprint then → the superset (run 2's own is not read)
        self.assertEqual(by[SUMM["A"]]["areas"], sorted(WIDE))


class m2Superset(unittest.TestCase):
    def _root(self, dirs):
        root = tempfile.mkdtemp(prefix="k6r4-root-")
        for d in dirs:
            os.makedirs(os.path.join(root, d))
        return root

    def _k(self, own=None):
        k = AN.Kickoff()
        k.interpretations = [{"id": "i1", "summary": "settings only", "orig": "A"},
                             {"id": "i2", "summary": "settings + sync storage", "orig": "B"}]
        k.chosen = "i1"
        k.areas = ["lib/a00"]
        k.cast = {"participation": ["i18n"], "gates": [], "skipped": ["designer: no UI"]}
        k.own_footprints = {"i2": own or {}}
        return k

    def test_no_truncation_drops_an_irreversible_area(self):
        dirs = ["lib/a%02d" % i for i in range(30)] + ["supabase/migrations", ".claude/guild/gates"]
        root = self._root(dirs)
        cap = AN.reading_capture(self._k(), root, [], extra_areas=dirs)
        other = [e for e in cap if e["token"] == "i2"][0]
        self.assertEqual(sorted(other["areas"]), sorted(dirs))
        self.assertEqual(other["areas"][:2], [".claude/guild/gates", "supabase/migrations"])
        # the pending-block value cap: whatever must go is a trailing (plain) area, flagged
        big = dict(other, areas=[".claude/guild/gates", "supabase/migrations"] + ["lib/%s" % ("x" * 60 + str(i))
                                                                               for i in range(40)])
        f = AN.capture_fields([big])["reading_i2"]
        self.assertLessEqual(len(f), AN.READING_CAP)
        back = json.loads(f)
        self.assertTrue(back["more"])
        self.assertEqual(back["areas"][:2], [".claude/guild/gates", "supabase/migrations"])
        self.assertEqual(AN.order_areas(["lib/b", "lib/db", "a"]), ["lib/db", "a", "lib/b"])

    def test_kickoff_block_areas_are_never_cut(self):
        dirs = ["lib/a%02d" % i for i in range(11)] + ["supabase/migrations"]
        files = dict(("%s/x.dart" % d, "int x;\n") for d in dirs)
        k = kickoff(areas=tuple(dirs))
        h = K4(self, unattended=False, roles=[evidence(self, areas=dirs)], judges={"KICKOFF": k}, extra_files=files)
        h.p._first_sprint = False
        A.run(h.p)
        areas = DS.kickoff_block(h.gh.comments(7)).get("areas").split(",")
        self.assertEqual(areas[0], "supabase/migrations")
        self.assertEqual(sorted(areas), sorted(dirs))
        self.assertEqual(AN.irreversible(areas), ["supabase/migrations"])

    def test_empty_or_missing_own_areas_are_no_footprint(self):
        root = self._root(["lib/a00", "lib/sync"])
        for own in ({"areas": []}, {"areas": ["no/such/dir"]}):
            with self.subTest(own=own):
                cap = AN.reading_capture(self._k(own), root, [], extra_areas=["lib/sync"])
                self.assertEqual(sorted(cap[1]["areas"]), ["lib/a00", "lib/sync"])

    def test_unknown_reading_roles_visual_po(self):
        root = self._root(["lib/a00"])
        ros = ["designer", "security", "i18n", "product-owner"]
        cap = AN.reading_capture(self._k(), root, ros, net=True)
        other = cap[1]
        self.assertEqual(other["gates"], ["designer", "security"])            # every installed gate role
        self.assertEqual(other["participation"], ["i18n"])
        self.assertTrue(other["ui_surface"] and other["safety_net_visual"] and other["po_convene"])
        self.assertEqual(other["skipped"], [])
        mine = cap[0]
        self.assertEqual((mine["skipped"], mine["po_convene"], mine["safety_net_visual"]), (["designer: no UI"], False,
                                                                                            False))
        known = AN.reading_capture(self._k({"cast": {"participation": [], "gates": ["security"]},
                                            "safety_net_visual": False, "po": {"convene": False}}), root, ros, net=True)
        self.assertEqual((known[1]["gates"], known[1]["safety_net_visual"], known[1]["po_convene"]),
                         (["security"], False, False))

    def test_apply_reading_takes_visual_po_skipped(self):
        k = self._k()
        k.safety_net_visual_possible = True
        cap = [{"token": "i1", "orig": "A", "summary": "a", "areas": [], "ui_surface": False, "safety_net_visual": False,
                "participation": [], "gates": [], "skipped": [], "po_convene": False, "work_type": "feature"},
               {"token": "i2", "orig": "B", "summary": "b", "areas": [], "ui_surface": True, "safety_net_visual": True,
                "participation": ["i18n"], "gates": ["designer"], "skipped": ["dba: none"], "po_convene": True,
                "work_type": "bug"}]
        AN.apply_reading(k, cap, "i2", tempfile.mkdtemp())
        self.assertEqual((k.safety_net_visual, k.po["convene"], k.cast["skipped"], k.work_type),
                         (True, True, ["dba: none"], "bug"))
        self.assertEqual(k.own_footprints["i1"]["areas"], [])


FIT = (                               # review-k6-r4 M3 — a scope set by the source
    ("로그인만 (제목 범위만)", "앱 전체"), ("로그인만 (요청 범위 내로 한정)", "앱 전체 (요청 범위 밖 포함)"),
    ("Login only (title scope only)", "Whole app"), ("Login only (only what the title names)", "Whole app (beyond the title)"),
    ("Login only (requested screen only)", "Whole app (all screens, not just the requested one)"),
    ("ログインのみ（タイトルの範囲のみ）", "アプリ全体"), ("Login only (per the title only)", "Whole app"),
    ("로그인만 (제목에 있는 것만)", "앱 전체 (제목에 없는 화면 포함)"),
)
FIT_WORDS = ("제목", "요청", "title", "request", "タイトル")


class M3SourceScope(unittest.TestCase):
    def test_table_over_both_sets(self):
        for pair in FIT:
            with self.subTest(fit=pair[0]):
                shown = LA.blind_question(list(pair))
                self.assertTrue(shown is None or not any(w in x for x in shown for w in FIT_WORDS), shown)
        for pair, scope in R3.SCOPE_PAIRS:                         # r3 M3: product nouns in a scope clause
            with self.subTest(scope=pair[0]):
                shown = LA.blind_question(list(pair))
                self.assertIsNotNone(shown)
                self.assertIn(scope, shown[0])
        import test_k6_r2 as R2
        for a, b, qual in R2.SCOPE_PAIRS:                          # r2 M3: scope asides
            with self.subTest(r2=a):
                shown = PF.blind_labels([a, b])
                self.assertTrue(shown[0] is not None and qual in shown[0], shown)

    def test_clause_kinds(self):
        for t, k in (("제목 범위만", "other"), ("per the title only", "other"), ("requested screen only", "other"),
                     ("title scope only", "other"), ("제목에 있는 것만", "other"),
                     ("except the issue body", "scope"), ("title only", "scope"), ("write requests only", "scope"),
                     ("본문에 있는 이미지만", "scope"), ("제목이 말하는 범위", "remark")):
            with self.subTest(clause=t):
                self.assertEqual(PF.clause_kind(t), k)


class m4CodeSpanRatings(unittest.TestCase):
    def test_numbers_in_code_spans_refuse(self):
        for lb in ("앱 전체 다크 모드 (`90%`)", "설정 화면만 (`10%`)", "Whole app (`p=0.9`)", "Whole app (`0.9`)",
                   "Login (`9/10`)", "Whole app (`score: 8`)", "Login only (`2`)"):
            with self.subTest(label=lb):
                self.assertIsNone(PF.neutral_label(lb))

    def test_literals_stay(self):
        for lb in ("dashboard (`AdminView`)", "설정 (`Get.back()` 만)", "auth (`status: 401`)", "API (`v2`)",
                   "401 재시도 소진 테스트 (`:3180-3218`)"):            # a line reference (real AC) is a literal
            with self.subTest(label=lb):
                self.assertEqual(PF.neutral_label(lb), lb)


class m6NotTrustedIsNotGone(unittest.TestCase):
    def _open(self, common):
        cand = {"decision_id": "D9", "issue": 4, "group": "SPLIT", "mode": "predict-first candidate", "choice": "split"}
        G.apply_judgments(common, [], "o/r", "predict-first", candidates=[cand])
        return "decision_id,issue,group,mode,choice,given_info\nD9,4,SPLIT,predict-first candidate,split,unsure\n"

    def test_import_with_no_engine_block_keeps_the_candidate(self):
        common = tmpdir(self)
        res = G.import_sheet(common, self._open(common), "o/r", blocks_of=lambda n: [])
        self.assertFalse(res.get("candidates_dropped"))
        self.assertIn("no engine block", res["rejected"][0]["why"])
        self.assertFalse(res["rejected"][0]["gone"])
        self.assertEqual([r for r in UV.report(common) if r["group"] == "SPLIT"][0]["open"], ["4/D9"])

    def test_dev_grade_scope_with_an_empty_log_keeps_it(self):
        common = tmpdir(self)
        self._open(common)
        out = G.apply_judgments(common, [], "o/r", "predict-first", logs={4: set()})
        self.assertFalse(out.get("candidates_dropped"))
        self.assertEqual(UV.reconcile({}, 4, set(), "t"), [])


class r3M4Kept(unittest.TestCase):
    def test_dot_claude_areas_hit_the_harness(self):
        self.assertEqual(AN.harness_hit([".claude/guild/gates", ".claude/settings.json", "lib/app"]),
                         [".claude/guild/gates", ".claude/settings.json"])
        self.assertEqual(AN.irreversible(["supabase/migrations", "lib/db"]), ["lib/db", "supabase/migrations"])


if __name__ == "__main__":
    unittest.main()
