"""review-k6-r5 — as table tests over the cases the findings name.

M1 + m1  `judge_took` is STRUCTURAL: the brief hands the judge the person's reading under the fixed engine id
         (`analysis.PERSON_READING_ID`) with its exact text; the judge takes it by choosing that id, and the engine then
         runs the STORED reading (summary + footprint) whatever words the judge gives it. No text closeness is evidence:
         an opposite-scope reading (만/제외, only/except, のみ/以外 …) under any other id is never taken (M1), and a
         re-wording under the fixed id always is (m1). Any other id, the id absent or listed twice → pause.
m2       a question raised by a person's `reask` is `raised_by: reask` in the shipped state too (first sprint, KICKOFF
         unverified, the conservative valve on) — never a grading-sheet row nor another decision point.
m3       a capture over the value cap keeps every area (continuation values `reading-areas-<token>-<n>`); a capture
         whose rest is lost (`more: true`) widens to the conservative superset; design never reads a truncated KICKOFF
         `areas` value as "outside visual.packages".
m4       a scope set by the source is refused whatever the source noun: the class is the act of reference (언급된 ·
         명시 안 된 · named · unnamed · listed · 記載された …) plus the source synonyms (타이틀 · 티켓 · OP …).
m5       a code-span-only aside whose span is no identifier (`safe`, `risky`, `high`, `low`, `ok`, `ng`) is read as its
         words — refused like the same words unquoted; identifier spans stay literals.
m6       a judge that takes the person's reading adds its footprint: union of areas / roles, OR of ui / visual / PO.
m7       an open candidate whose Issue log shows no engine block is counted `unread` and shown by `dev health` with the
         way out; `dev grade --drop-candidate <issue/D-id> --reason <why>` (reason required) drops it, logged `by: human`.
"""

import json
import os
import tempfile
import unittest

import _util  # noqa: F401
import test_k6_r3 as R3
from _k1 import tmpdir
from _k4 import K4, evidence, kickoff
from test_k5_cli import Env

from guildcore import ask as ASK
from guildcore import journal as J
from guildcore.records import decisions as DREC
from guildcore.records import markers
from workflows.dev import analysis as AN
from workflows.dev import cli as CLI
from workflows.dev import grade as G
from workflows.dev import predict as PF
from workflows.dev import unverified as UV
from workflows.dev.stages import analyze as A
from workflows.dev.stages import design as DS
from workflows.dev.stages.base import StageResult

SUMM, REWORD, WIDE, EXTRA = R3.SUMM, R3.REWORD, R3.WIDE, R3.EXTRA
_blocks, _pending, _kick, _token, _took = R3._blocks, R3._pending, R3._kick, R3._token, R3._took
PID = AN.PERSON_READING_ID

# (person's reading, the judge's opposite-scope text) — ko / en / ja × {only ↔ except, only ↔ including, except ↔ only}
OPPOSITE = (
    ("로그인 화면만 다크 모드", "로그인 화면 제외 다크 모드"),
    ("로그인 화면 제외 다크 모드", "로그인 화면만 다크 모드"),
    ("설정 화면만 다크 모드", "설정 화면 포함 앱 전체 다크 모드"),
    ("설정 화면 빼고 다크 모드", "설정 화면에만 다크 모드"),
    ("dark mode on the settings screen only", "dark mode everywhere except the settings screen"),
    ("dark mode everywhere except login", "dark mode on login only"),
    ("dark mode on the settings screen only", "dark mode on every screen including settings"),
    ("設定画面のみダークモード", "設定画面以外ダークモード"),
    ("設定画面以外ダークモード", "設定画面のみダークモード"),
    ("ログイン画面だけダークモード", "ログイン画面を含む全画面ダークモード"),
)
# (person's reading, an ordinary re-wording of it)
REWORDINGS = (
    ("설정 화면만 다크 모드", "다크 모드를 설정 페이지에만 적용"),
    ("설정 화면만 다크 모드", "설정 화면 한정 다크 모드"),
    ("앱 전체 다크 모드", "다크 모드를 앱 전체에"),
    ("dark mode on the settings screen only", "only the settings page gets the dark theme"),
    ("dark mode across the whole app", "dark theme on every screen of the app"),
    ("設定画面のみダークモード", "ダークモードを設定画面だけに適用"),
    ("アプリ全体をダークモード", "全画面ダークテーマ"),
    ("설정 화면만 다크 모드", "설정 화면만 다크 모드"),                  # verbatim
)


def _fields(chosen, mine_id, mine_text, other_id="A", other_text="앱 전체 다크 모드"):
    return {"chosen": chosen, "interpretations": [{"id": other_id, "summary": other_text},
                                                  {"id": mine_id, "summary": mine_text}]}


class M1Structural(unittest.TestCase):
    def test_opposite_scope_is_never_taken(self):
        """the review's three pairs and more: an opposite-scope text under the person's old id, another letter, or
        the person's exact text under a letter — never taken (only the fixed id is)."""
        for person, opposite in OPPOSITE:
            ent = {"token": "i1", "orig": "B", "summary": person}
            cap = [ent, {"token": "i2", "orig": "A", "summary": "x"}]
            for chosen_id in ("B", "A", "C", "b"):
                for text in (opposite, person):
                    with self.subTest(person=person, chosen=chosen_id, text=text):
                        self.assertFalse(AN.judge_took(_fields(chosen_id, chosen_id, text), ent, cap))

    def test_rewordings_under_the_fixed_id_are_taken(self):
        for person, words in REWORDINGS:
            ent = {"token": "i1", "orig": "B", "summary": person}
            for other in ("앱 전체 다크 모드", "dark theme on every screen of the app", ""):
                with self.subTest(person=person, words=words, other=other):
                    self.assertTrue(AN.judge_took(_fields(PID, PID, words, other_text=other), ent, [ent]))
                    self.assertTrue(AN.judge_took(_fields(" Person-Reading ", PID, words), ent, [ent]))   # case/space

    def test_fixed_id_absent_other_pick_or_twice_pauses(self):
        ent = {"token": "i1", "orig": "B", "summary": "x"}
        self.assertFalse(AN.judge_took({"chosen": PID, "interpretations": [{"id": "A", "summary": "x"}]}, ent))
        self.assertFalse(AN.judge_took(_fields("A", PID, "x"), ent))                  # listed, another chosen
        self.assertFalse(AN.judge_took({"chosen": PID, "interpretations": [{"id": PID, "summary": "x"},
                                                                          {"id": PID, "summary": "y"}]}, ent))
        self.assertFalse(AN.judge_took({}, ent))
        self.assertFalse(AN.judge_took(None, ent))

    def _answered(self, summ=None):
        summ = summ or {"A": "앱 전체 다크 모드", "B": "로그인 화면만 다크 모드"}
        h = K4(self, unattended=False, roles=[evidence(self, areas=WIDE)] * 4, judges={"KICKOFF": _kick("A", summ=summ)},
               extra_files=EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r5-"), 7, h.clock)
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, _token(summ, "B"), journal=h.p.journal)
        return h, summ

    def test_the_review_run_pauses(self):
        """judge A (whole app) → person B (login only) → the judge's `chosen B` = "로그인 화면 제외" → pause."""
        h, summ = self._answered()
        k2 = kickoff(ui=True, areas=WIDE, ac=("every screen but login turns dark",))
        k2.fields["interpretations"] = [{"id": "A", "summary": "앱 전체 다크 모드"},
                                        {"id": "B", "summary": "로그인 화면 제외 다크 모드"}]
        k2.fields["chosen"] = "B"
        h.judges["KICKOFF"] = k2
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.ASK)
        self.assertIn("따르지 않음", _pending(h)[-1].get("question"))
        self.assertIsNone(h.body_with("analyze:output"))

    def test_a_reworded_taking_runs_the_stored_reading(self):
        h, summ = self._answered()
        h.judges["KICKOFF"] = _took("B", summ={"A": "앱의 모든 화면에 다크 모드", "B": "다크 모드를 로그인 페이지에만"})
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.ADVANCE)
        out = h.body_with("analyze:output")
        self.assertIn("- (선택) %s: %s" % (_token(summ, "B"), summ["B"]), out)     # the stored text, not the judge's
        self.assertNotIn("로그인 페이지에만", out.split("(선택)")[1].split("\n")[0])

    def test_the_brief_hands_the_fixed_id_and_the_exact_text(self):
        seen = []

        def judge(spec):
            seen.append(dict(spec.brief_parts).get("human_answers"))
            return _kick("A") if len(seen) == 1 else _took("B")
        h = K4(self, unattended=False, roles=[evidence(self, areas=WIDE)] * 4, judges={"KICKOFF": judge},
               extra_files=EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r5-"), 7, h.clock)
        A.run(h.p)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, _token(SUMM, "B"), journal=h.p.journal)
        A.run(h.p)
        self.assertIn("«%s»" % SUMM["B"], seen[-1])
        self.assertEqual(seen[-1].count("`%s`" % PID), 2)                    # the id and `chosen`
        self.assertNotIn("id B", seen[-1])


def _cycle(case, unattended, valves=None, first=False, unverified=True):
    """judge A → person B → the judge keeps A ("not taken") → `reask` → the reading asked again → answered."""
    h = K4(case, unattended=unattended, roles=[evidence(case, areas=WIDE)] * 8, judges={"KICKOFF": _kick("A")},
           extra_files=EXTRA)
    h.p._first_sprint = first
    if unverified:
        h.p.unverified = frozenset(["KICKOFF"])
    h.p.valves = dict(valves or {})
    h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r5-"), 7, h.clock)
    A.run(h.p)
    q1 = _pending(h)[-1]
    ASK.answer(h.decisions, h.writer, 7, q1.id, _token(SUMM, "B"), journal=h.p.journal)
    h.judges["KICKOFF"] = _kick("A", summ=REWORD)
    A.run(h.p)
    stop_q = _pending(h)[-1]
    assert stop_q.get("point") == A.READING_STOP_POINT, stop_q.get("point")
    ASK.answer(h.decisions, h.writer, 7, stop_q.id, "reask", journal=h.p.journal)
    A.run(h.p)
    again = _pending(h)[-1]
    ASK.answer(h.decisions, h.writer, 7, again.id, again.get("recommended") or _token(REWORD, "A"), journal=h.p.journal)
    return h, q1, again


class m2ReaskNoRow(unittest.TestCase):
    def test_reask_questions_are_never_rows_in_the_shipped_state(self):
        cases = (("attended, KICKOFF unverified", False, None, False),
                 ("attended, first sprint", False, None, True),
                 ("unattended, KICKOFF unverified", True, None, False),
                 ("unattended, conservative valve on", True, {"group.KICKOFF.conservative": True}, False),
                 ("unattended, valve on + first sprint", True, {"group.KICKOFF.conservative": True}, True))
        for name, unattended, valves, first in cases:
            with self.subTest(case=name):
                h, q1, again = _cycle(self, unattended, valves, first)
                self.assertNotEqual(again.id, q1.id)
                self.assertEqual(again.get("raised_by"), "reask")
                self.assertEqual(q1.get("raised_by"), "confirm")
                _ok, rows = G.predict_first_judgments(_blocks(h), 7)
                self.assertEqual([r["decision_id"] for r in rows], [q1.id])        # one row: the first question
                fixed, _rej = G.verify_rows([dict(r, given_info="ok") for r in rows], lambda n: _blocks(h))
                self.assertEqual(sorted(set(r["point_key"] for r in fixed if UV.counts(r, "human"))),
                                 ["7/%s" % q1.id])


class m3NothingLost(unittest.TestCase):
    def _root(self, n=60):
        root = tempfile.mkdtemp(prefix="k6r5-root-")
        dirs = ["lib/features/feature_%02d/presentation" % i for i in range(n)] + ["supabase/migrations"]
        for d in dirs:
            os.makedirs(os.path.join(root, d))
        return root, dirs

    def _cap(self, root, dirs):
        k = AN.Kickoff()
        k.interpretations = [{"id": "i1", "summary": "설정 화면만 다크 모드", "orig": "A"},
                             {"id": "i2", "summary": "앱 전체 다크 모드", "orig": "B"}]
        k.chosen, k.areas = "i1", ["lib/features/feature_00/presentation"]
        return AN.reading_capture(k, root, [], extra_areas=dirs)

    def _fresh(self):
        k = AN.Kickoff()
        k.po = {"convene": False, "reason": ""}
        return k

    def test_a_long_reading_round_trips_through_a_rendered_block(self):
        for n in (60, 150):
            with self.subTest(areas=n):
                root, dirs = self._root(n)
                cap = self._cap(root, dirs)
                full = [e for e in cap if e["token"] == "i2"][0]["areas"]
                self.assertEqual(len(full), n + 1)
                fields = AN.capture_fields(cap)
                self.assertTrue(any(k.startswith(AN.READING_MORE) for k in fields))
                self.assertTrue(all(len(v) <= AN.READING_CAP for v in fields.values()))
                txt = DREC.render_block(3, dict(fields, kind="interpretation-surface", status="pending-human"))
                blk = markers.BlockDoc.parse(txt, DREC.HEADING_RE, DREC.TAIL_RE).blocks[0]
                back, why = AN.captured(dict(blk.fields()))
                self.assertIsNone(why)
                ent = [e for e in back if e["token"] == "i2"][0]
                self.assertNotIn("more", ent)
                self.assertEqual(ent["areas"], full)
                self.assertEqual(ent["areas"][0], "supabase/migrations")          # irreversible first
                k = self._fresh()
                AN.apply_reading(k, back, "i2", root)
                self.assertEqual(sorted(k.areas), sorted(full))

    def test_a_lost_rest_widens_to_the_superset(self):
        root, dirs = self._root(60)
        fields = AN.capture_fields(self._cap(root, dirs))
        for drop in ("missing", "broken", "legacy-true"):
            with self.subTest(case=drop):
                f = dict(fields)
                if drop == "missing":
                    f.pop("%si2-1" % AN.READING_MORE)
                elif drop == "broken":
                    f["%si2-1" % AN.READING_MORE] = "[not json"
                else:                                   # an r4 capture: the rest dropped, `more: true`
                    e = json.loads(f["reading_i2"])
                    e["more"] = True
                    f = dict((k, v) for k, v in f.items() if not k.startswith(AN.READING_MORE))
                    f["reading_i2"] = json.dumps(e)
                back, why = AN.captured(f)
                self.assertIsNone(why)
                ent = [e for e in back if e["token"] == "i2"][0]
                self.assertIs(ent.get("more"), True)
                self.assertLess(len(ent["areas"]), 61)
                k = self._fresh()
                k.areas = ["lib/features/feature_59/presentation"]        # this run's judge
                AN.apply_reading(k, back, "i2", root, widen=dirs)
                self.assertEqual(sorted(k.areas), sorted(dirs))
                self.assertTrue(any("conservative superset" in c for c in k.coerced))

    def test_design_never_narrows_on_a_truncated_areas_value(self):
        cfg = {"visual": {"available": True, "packages": ["lib/ui"]}}
        orig = DS.V.visual_available
        DS.V.visual_available = lambda c: True
        try:
            cut = ",".join("lib/x%03d" % i for i in range(300))[:DREC.VALUE_CAP - len(DREC.TRUNCATED)] + DREC.TRUNCATED
            self.assertEqual(DS.visual_decision(cfg, {"ui_surface": "true", "areas": cut}, [])[0], True)
            self.assertEqual(DS.visual_decision(cfg, {"ui_surface": "true", "areas": "lib/x001"}, []),
                             (False, "UI surface outside visual.packages"))
        finally:
            DS.V.visual_available = orig


class m4m5Labels(unittest.TestCase):
    SOURCE = (("로그인만 (타이틀 범위만)", "앱 전체 (타이틀 범위 밖 포함)"),
              ("로그인만 (언급된 화면만)", "앱 전체 (언급 안 된 화면 포함)"),
              ("로그인만 (명시된 화면만)", "앱 전체 (명시 안 된 화면도)"),
              ("로그인만 (티켓에 적힌 화면만)", "앱 전체 (티켓 밖 화면 포함)"),
              ("Login only (named screen only)", "Whole app (unnamed screens too)"),
              ("Login only (the listed screens only)", "Whole app (screens not mentioned included)"),
              ("Login only (stated scope only)", "Whole app (beyond the OP)"),
              ("ログインのみ（記載された画面のみ）", "アプリ全体（記載のない画面も含む）"),
              ("ログインのみ（挙げられた画面だけ）", "アプリ全体（チケット外も含む）"))
    SPAN = (("Split in two (`safe`)", "Single PR (`risky`)"), ("Split in two (`high`)", "Single PR (`low`)"),
            ("Split in two (`ok`)", "Single PR (`ng`)"), ("Split in two (`best`)", "Single PR (`worse`)"),
            ("Split in two (`안전`)", "Single PR (`위험`)"))
    SHOWN = (("Login (`Get.back()`)", "Whole (`CSV`)"), ("Login (`iOS`)", "Whole (`snake_case`)"),
             ("Login (`:3180-3218`)", "Whole (`lib/app`)"), ("Login (`null`)", "Whole (`,`)"),
             ("Login (`Single PR`)", "Whole (`수렴 뒤 진행`)"), ("로그인 (본문 편집기 제외)", "앱 전체 (모든 화면)"),
             ("Login (write requests only)", "Whole app (every screen)"), ("ログイン（本文編集のみ）", "全体（設定画面以外）"))

    def test_source_scope_is_refused_whatever_the_noun(self):
        for a, b in self.SOURCE:
            with self.subTest(pair=(a, b)):
                got = PF.blind_labels([a, b])
                self.assertIn(None, got)                                      # the question is not blind
                for x, src in zip(got, (a, b)):
                    if x is not None:
                        self.assertNotIn("(", x.replace("（", "("))         # never an aside shown

    def test_rating_words_in_code_spans_are_refused(self):
        for a, b in self.SPAN:
            with self.subTest(pair=(a, b)):
                got = PF.blind_labels([a, b])
                # exactly as the same words unquoted: refused, or (a rating word: a remark) cut — never shown
                self.assertEqual(got, PF.blind_labels([a.replace("`", ""), b.replace("`", "")]))
                self.assertFalse([x for x in got if x is not None and "`" in x])
                if "best" not in a:
                    self.assertEqual(got, [None, None])

    def test_identifier_spans_and_product_scopes_stay_shown(self):
        for a, b in self.SHOWN:
            with self.subTest(pair=(a, b)):
                self.assertEqual(PF.blind_labels([a, b]), [a, b])


class m6Union(unittest.TestCase):
    def test_the_taking_judge_s_footprint_is_joined(self):
        own = {"B": {"areas": ["lib/theme"], "ui_surface": False, "cast": {"participation": [], "gates": []}}}
        h = K4(self, unattended=False, roles=[evidence(self, areas=WIDE)] * 4,
               judges={"KICKOFF": _kick("A", own=own)}, extra_files=EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r5-"), 7, h.clock)
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, _token(SUMM, "B"), journal=h.p.journal)
        h.judges["KICKOFF"] = _took("B", areas=WIDE, ui=True)               # its footprint FOR the person's reading
        self.assertEqual(A.run(h.p).kind, StageResult.ADVANCE)
        kb = DS.kickoff_block(h.gh.comments(7))
        self.assertEqual(sorted((kb.get("areas") or "").split(",")), sorted(WIDE))
        self.assertEqual(kb.get("ui_surface"), "true")                       # OR: the capture said no UI

    def test_a_judge_that_does_not_take_adds_nothing(self):
        own = {"B": {"areas": ["lib/theme"], "ui_surface": False, "cast": {"participation": [], "gates": []}}}
        h = K4(self, unattended=False, roles=[evidence(self, areas=WIDE)] * 4,
               judges={"KICKOFF": _kick("A", own=own)}, extra_files=EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r5-"), 7, h.clock)
        A.run(h.p)
        ASK.answer(h.decisions, h.writer, 7, _pending(h)[-1].id, _token(SUMM, "B"), journal=h.p.journal)
        h.judges["KICKOFF"] = _kick("A", areas=("lib/settings",))
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        kb = DS.kickoff_block(h.gh.comments(7))
        self.assertEqual(kb.get("areas"), "lib/theme")

    def test_widen_unit(self):
        k = AN.Kickoff()
        k.safety_net_visual_possible = True
        k.areas, k.ui_surface = ["lib/a"], False
        k.cast = {"participation": ["i18n"], "gates": [], "skipped": ["designer: no screen"]}
        AN.widen_reading(k, {"areas": ["lib/b"], "ui_surface": True, "safety_net_visual": True,
                             "participation": ["dba"], "gates": ["designer"], "po_convene": True})
        self.assertEqual(k.areas, ["lib/a", "lib/b"])
        self.assertTrue(k.ui_surface and k.safety_net_visual and k.po["convene"])
        self.assertEqual(k.cast, {"participation": ["dba", "i18n"], "gates": ["designer"], "skipped": []})


class m7WayOut(unittest.TestCase):
    def _row(self, i, gi="ok"):
        return {"issue": i, "decision_id": "D%d" % i, "group": "KICKOFF", "mode": G.INHERENT_MODE, "choice": "i1",
                "given_info": gi}

    def test_an_unreadable_log_is_shown_and_the_person_drops_it(self):
        common = tmpdir(self)
        G.apply_judgments(common, [], "o/r", "predict-first", candidates=[dict(self._row(4), decision_id="D9",
                                                                              given_info="")])
        # the person fills the row but the Issue's log shows no engine block (deleted comments)
        csv = "decision_id,issue,group,mode,choice,given_info\nD9,4,KICKOFF,%s,i1,ok\n" % G.INHERENT_MODE
        res = G.import_sheet(common, csv, "o/r", blocks_of=lambda n: [])
        self.assertTrue(res["rejected"][0]["unread"])
        self.assertEqual(res.get("candidates_unread"), ["4/D9"])
        G.apply_judgments(common, [], "o/r", "predict-first", logs={4: set()})        # a `dev grade` of its scope
        G.apply_judgments(common, [self._row(i) for i in range(10, 16)], "o/r", "human")
        rep = [r for r in UV.report(common) if r["group"] == "KICKOFF"][0]
        self.assertIsNone(rep["released_at"])                                        # never dropped silently
        self.assertEqual((rep["open"], rep["unread"]), (["4/D9"], {"4/D9": 2}))
        self.assertIn("--drop-candidate", rep["way_out"])
        self.assertIn("error", G.drop_candidate(common, "4/D9", "  "))              # a reason is required
        self.assertIn("error", G.drop_candidate(common, "4/D8", "gone"))            # not open
        self.assertIn("error", G.drop_candidate(common, "D9", "gone"))              # not <issue>/<D-id>
        out = G.drop_candidate(common, "4/D9", "decision log comment deleted by the reporter")
        self.assertEqual(out["candidates_dropped"], [{"group": "KICKOFF", "key": "4/D9"}])
        self.assertEqual(out.get("unverified_released"), ["KICKOFF"])
        rep = [r for r in UV.report(common) if r["group"] == "KICKOFF"][0]
        self.assertTrue(rep["released_at"])
        self.assertEqual(rep["dropped_by_human"][0]["key"], "4/D9")
        self.assertIn("deleted", rep["dropped_by_human"][0]["reason"])
        self.assertEqual((rep["unread"], rep["way_out"]), ({}, None))

    def test_a_read_log_resets_unread(self):
        common = tmpdir(self)
        G.apply_judgments(common, [], "o/r", "predict-first", candidates=[dict(self._row(4), decision_id="D9",
                                                                              given_info="")])
        G.apply_judgments(common, [], "o/r", "predict-first", logs={4: set()})
        G.apply_judgments(common, [], "o/r", "predict-first", logs={4: {"D9"}})
        rep = [r for r in UV.report(common) if r["group"] == "KICKOFF"][0]
        self.assertEqual((rep["open"], rep["unread"], rep["way_out"]), (["4/D9"], {}, None))

    def test_the_cli(self):
        e = Env(self, config={"version": "0.101.0", "language": "ko"})
        G.apply_judgments(e.common, [], "o/r", "predict-first", candidates=[dict(self._row(8), decision_id="D9",
                                                                                given_info="")])
        self.assertEqual(CLI.main(["grade", "--drop-candidate", "8/D9"], e.d), 64)
        self.assertIn("--reason", e.lines()[-1])
        self.assertEqual(CLI.main(["grade", "--drop-candidate", "8/D9", "--reason", "log deleted"], e.d), 0)
        res = json.loads(e.lines()[-1].split(">>> ENGINE <<<")[-1])
        self.assertEqual((res["by"], res["candidates_dropped"][0]["key"]), ("human", "8/D9"))
        st = G.load_state(e.common)["unverified"]["KICKOFF"]
        self.assertEqual(st["dropped"][-1]["by"], "human")


if __name__ == "__main__":
    unittest.main()
