"""review-k6-r6 — as table tests over the cases the findings name.

M1  `judge_took` keeps the fixed id (r5) and adds two exact-equality refutations — never closeness: (a) the summary under
    `person-reading` IS another captured reading's summary (normalised: whitespace, case, NFKC, a trailing full stop;
    a stored cut summary as a prefix); (b) the person's reading's summary appears under any other id. The review's
    swapped pair × ko / en / ja → pause, never ADVANCE with the other reading's AC.
m1  `dev grade --drop-candidate` drops only a candidate whose log is UNREAD (≥ 1); a readable one needs `--force`
    (recorded). A human-dropped candidate a later `dev grade` lists again is open again, and a release reached after
    the drop is revoked (`release_revoked`) — the group runs the conservative path until it is judged.
m2  one pending block's continuation values stay within `CONTINUATION_BUDGET`; a reading whose rest would pass it is
    carried as a head with `more: true` (the conservative superset) — 400 areas × 5 readings stays under the rollover.
m3  rating words whatever their case (`SAFE`, `LGTM`, `NG`), rating words as pieces of identifier-shaped spans
    (`low-risk`, `risk: low`, `is_safe=true`, `risk_low`), and the act of ASKING as a reference (요구된 · 요구 밖 ·
    依頼外 · 頼まれた · unrequested · out of the request) — refused; identifiers and product nouns stay shown.
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
from workflows.dev.stages.base import StageResult

PID = AN.PERSON_READING_ID

# (the person's reading, the other reading the question offered) — ko / en / ja
SWAPS = (
    ("로그인 화면만 다크 모드", "앱 전체 다크 모드"),
    ("설정 화면 제외 다크 모드", "설정 화면만 다크 모드"),
    ("dark mode on the login screen only", "dark mode across the whole app"),
    ("dark mode everywhere except settings", "dark mode on settings only"),
    ("ログイン画面のみダークモード", "アプリ全体をダークモード"),
    ("設定画面以外ダークモード", "設定画面のみダークモード"),
)


def _f(*pairs, chosen=PID):
    return {"chosen": chosen, "interpretations": [{"id": i, "summary": s} for i, s in pairs]}


def _cap(person, other):
    ent = {"token": "i1", "orig": "B", "summary": person}
    return ent, [ent, {"token": "i2", "orig": "A", "summary": other}]


class M1ExactRefutations(unittest.TestCase):
    def test_table(self):
        """cells: (a)+(b) the review's swap; (a) alone; (b) alone; normalised variants of each; controls taken."""
        for person, other in SWAPS:
            ent, cap = _cap(person, other)
            cells = {
                "swap (a)+(b)": (_f(("A", person), (PID, other)), False),
                "(a) other text under the fixed id": (_f((PID, other), ("C", "something else")), False),
                "(a) alone, no other reading listed": (_f((PID, other)), False),
                "(b) person's text under another id": (_f((PID, "a re-wording"), ("A", person)), False),
                "(a) case / spaces / full stop": (_f((PID, "  %s. " % other.upper())), False),
                "(b) case / spaces": (_f((PID, "x"), ("a", " %s " % person.upper())), False),
                "control: verbatim under the fixed id": (_f(("A", other), (PID, person)), True),
                "control: re-worded, other reading listed": (_f(("A", other), (PID, "re-worded: " + person)), True),
                "control: fixed id only": (_f((PID, person)), True),
            }
            for name, (fields, want) in cells.items():
                with self.subTest(person=person, cell=name):
                    self.assertEqual(AN.judge_took(fields, ent, cap), want)

    def test_nfkc_and_a_cut_summary(self):
        ent, cap = _cap("ログイン画面のみ", "ＡＰＰ全体")
        self.assertFalse(AN.judge_took(_f((PID, "APP全体")), ent, cap))                    # NFKC full width
        long_other = "앱 전체 다크 모드 " + "그리고 모든 하위 화면 " * 30
        ent, cap = _cap("로그인만", long_other[:300])                                       # stored cut at 300
        self.assertFalse(AN.judge_took(_f((PID, long_other)), ent, cap))
        # a SHORT stored summary is never a prefix match (only a cut one is)
        ent, cap = _cap("로그인만", "앱 전체")
        self.assertTrue(AN.judge_took(_f((PID, "앱 전체가 아니라 로그인만")), ent, cap))

    def test_a_capture_with_the_person_s_text_twice_is_no_refutation(self):
        ent = {"token": "i1", "orig": "B", "summary": "로그인만"}
        cap = [ent, {"token": "i2", "orig": "A", "summary": "로그인만"}, {"token": "i3", "orig": "C", "summary": "앱 전체"}]
        self.assertTrue(AN.judge_took(_f((PID, "로그인만"), ("C", "앱 전체")), ent, cap))

    def test_still_no_closeness(self):
        """a re-worded swap (the other reading's meaning under the fixed id in other words) is NOT decidable by
        equality — taken, as r5 (the remaining limit, k6-notes r6: AC fidelity is checked post hoc)."""
        ent, cap = _cap("로그인 화면만 다크 모드", "앱 전체 다크 모드")
        self.assertTrue(AN.judge_took(_f(("A", "로그인 페이지에만 다크 테마"), (PID, "다크 모드를 앱 전체에")), ent, cap))

    def _setup(self, summ):
        h = K4(self, unattended=False, roles=[evidence(self, areas=R3.WIDE)] * 4,
               judges={"KICKOFF": R3._kick("A", summ=summ)}, extra_files=R3.EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r6-"), 7, h.clock)
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        ASK.answer(h.decisions, h.writer, 7, R3._pending(h)[-1].id, R3._token(summ, "B"), journal=h.p.journal)
        return h

    def test_the_review_run_pauses_ko_en_ja(self):
        for summ, ac in (({"A": "앱 전체 다크 모드", "B": "로그인 화면만 다크 모드"}, "every screen of the app turns dark"),
                         ({"A": "dark mode across the whole app", "B": "dark mode on the login screen only"},
                          "every screen turns dark"),
                         ({"A": "アプリ全体をダークモード", "B": "ログイン画面のみダークモード"}, "全画面がダークになる")):
            with self.subTest(lang=summ["A"]):
                h = self._setup(summ)
                k2 = kickoff(ui=True, areas=R3.WIDE, ac=(ac,))
                k2.fields["interpretations"] = [{"id": "A", "summary": summ["B"]}, {"id": PID, "summary": summ["A"]}]
                k2.fields["chosen"] = PID
                h.judges["KICKOFF"] = k2
                r = A.run(h.p)
                self.assertEqual(r.kind, StageResult.ASK)
                self.assertIn("따르지 않음", R3._pending(h)[-1].get("question"))
                self.assertIsNone(h.body_with("analyze:output"))

    def test_a_verbatim_taking_still_advances(self):
        summ = {"A": "앱 전체 다크 모드", "B": "로그인 화면만 다크 모드"}
        h = self._setup(summ)
        k2 = kickoff(ui=True, areas=R3.WIDE, ac=("only the login screen turns dark",))
        k2.fields["interpretations"] = [{"id": "A", "summary": summ["A"]}, {"id": PID, "summary": summ["B"]}]
        k2.fields["chosen"] = PID
        h.judges["KICKOFF"] = k2
        self.assertEqual(A.run(h.p).kind, StageResult.ADVANCE)


class m1DropOnlyUnread(unittest.TestCase):
    def _row(self, i, gi="ok", did=None):
        return {"issue": i, "decision_id": did or "D%d" % i, "group": "KICKOFF", "mode": G.INHERENT_MODE,
                "choice": "i1", "given_info": gi}

    def _rep(self, common):
        return [r for r in UV.report(common) if r["group"] == "KICKOFF"][0]

    def _six_ok_with(self, common, logs):
        cand = self._row(4, gi="", did="D9")
        G.apply_judgments(common, [], "o/r", "predict-first", candidates=[cand], logs=logs)
        G.apply_judgments(common, [self._row(i) for i in range(10, 16)], "o/r", "human")
        return cand

    def test_a_readable_candidate_is_not_dropped(self):
        common = tmpdir(self)
        self._six_ok_with(common, {4: {"D9"}})                         # its log READ — never unread
        out = G.drop_candidate(common, "4/D9", "want the release")
        self.assertIn("error", out)
        self.assertIn("--force", out["error"])
        rep = self._rep(common)
        self.assertEqual((rep["open"], rep["released_at"]), (["4/D9"], None))

    def test_force_drops_and_a_relisted_candidate_revokes_the_release(self):
        common = tmpdir(self)
        cand = self._six_ok_with(common, {4: {"D9"}})
        out = G.drop_candidate(common, "4/D9", "operator call", force=True)
        self.assertTrue(out["forced"])
        self.assertEqual(out.get("unverified_released"), ["KICKOFF"])
        rep = self._rep(common)
        self.assertTrue(rep["released_at"])
        self.assertEqual(rep["after_human_drop"], ["4/D9"])
        self.assertTrue(rep["dropped_by_human"][0]["forced"])
        self.assertNotIn("KICKOFF", UV.pending(common))
        res = G.apply_judgments(common, [], "o/r", "predict-first", candidates=[cand], logs={4: {"D9"}})
        self.assertEqual(res.get("unverified_release_revoked"), ["KICKOFF"])
        rep = self._rep(common)
        self.assertEqual((rep["open"], rep["released_at"]), (["4/D9"], None))
        self.assertEqual(rep["release_revoked"][0]["keys"], ["4/D9"])
        self.assertIn("KICKOFF", UV.pending(common))                  # the conservative path again
        self.assertEqual(rep["dropped_by_human"], [])
        # judged on the sheet → released again (the person's verdict, not a drop)
        G.apply_judgments(common, [self._row(4, did="D9")], "o/r", "human")
        self.assertTrue(self._rep(common)["released_at"])

    def test_an_unread_drop_releases_and_a_relisted_one_revokes(self):
        common = tmpdir(self)
        cand = self._six_ok_with(common, {4: set()})                   # no engine block → unread 1
        self.assertEqual(self._rep(common)["unread"], {"4/D9": 1})
        out = G.drop_candidate(common, "4/D9", "decision log deleted")
        self.assertNotIn("forced", out)
        self.assertEqual(out.get("unverified_released"), ["KICKOFF"])
        res = G.apply_judgments(common, [], "o/r", "predict-first", candidates=[cand], logs={4: {"D9"}})
        self.assertEqual(res.get("unverified_release_revoked"), ["KICKOFF"])
        self.assertIsNone(self._rep(common)["released_at"])

    def test_a_release_before_the_drop_is_not_revoked(self):
        common = tmpdir(self)
        G.apply_judgments(common, [self._row(i) for i in range(10, 16)], "o/r", "human")
        self.assertTrue(self._rep(common)["released_at"])
        cand = self._row(4, gi="", did="D9")
        G.apply_judgments(common, [], "o/r", "predict-first", candidates=[cand], logs={4: set()})
        G.drop_candidate(common, "4/D9", "log deleted")
        res = G.apply_judgments(common, [], "o/r", "predict-first", candidates=[cand], logs={4: {"D9"}})
        self.assertNotIn("unverified_release_revoked", res)
        rep = self._rep(common)
        self.assertTrue(rep["released_at"])
        self.assertEqual(rep["open"], ["4/D9"])                        # still open — a person judges it

    def test_the_cli(self):
        e = Env(self, config={"version": "0.101.0", "language": "ko"})
        G.apply_judgments(e.common, [], "o/r", "predict-first", candidates=[self._row(8, gi="", did="D9")],
                          logs={8: {"D9"}})
        self.assertEqual(CLI.main(["grade", "--drop-candidate", "8/D9", "--reason", "x"], e.d), 64)
        self.assertIn("--force", e.lines()[-1])
        self.assertEqual(CLI.main(["grade", "--drop-candidate", "8/D9", "--reason", "x", "--force"], e.d), 0)
        st = G.load_state(e.common)["unverified"]["KICKOFF"]
        self.assertTrue(st["dropped"][-1]["forced"])


class m2BlockBudget(unittest.TestCase):
    def _cap(self, n_areas=400, n_read=5):
        areas = ["lib/feature_%03d/presentation/widgets" % i for i in range(n_areas)]
        return [{"token": "i%d" % n, "orig": "R%d" % n, "summary": "reading %d" % n, "areas": list(areas),
                 "ui_surface": True, "safety_net_visual": False, "participation": [], "gates": [], "skipped": [],
                 "po_convene": False, "work_type": "feature"} for n in range(1, n_read + 1)], areas

    def test_400_areas_by_5_readings_stays_under_the_rollover(self):
        cap, areas = self._cap()
        fields = AN.capture_fields(cap)
        cont = sum(len(v) for k, v in fields.items() if k.startswith(AN.READING_MORE))
        self.assertLessEqual(cont, AN.CONTINUATION_BUDGET)
        block = DREC.render_block(12, dict({"point": "ask:readiness", "kind": "readiness", "status": "pending-human",
                                            "by": "code", "question": "q", "options": "i1|i2|i3|i4|i5|stop"}, **fields))
        self.assertLess(len(block), DREC.ROLLOVER_CHARS)
        self.assertLess(len(block), 50000)
        blk = markers.BlockDoc.parse(block, DREC.HEADING_RE, DREC.TAIL_RE).blocks[0]
        back, why = AN.captured(dict(blk.fields()))
        self.assertIsNone(why)
        whole = [e for e in back if "more" not in e]
        head = [e for e in back if e.get("more") is True]
        self.assertTrue(whole and head)
        self.assertEqual(len(whole) + len(head), 5)
        for e in whole:
            self.assertEqual(sorted(e["areas"]), sorted(areas))       # carried whole while the budget lasts
        for e in head:
            self.assertLess(len(e["areas"]), len(areas))

    def test_a_head_only_reading_widens_to_the_superset(self):
        cap, areas = self._cap()
        back, _ = AN.captured(AN.capture_fields(cap))
        tok = [e for e in back if e.get("more") is True][0]["token"]
        root = tempfile.mkdtemp(prefix="k6r6-root-")
        for d in areas:
            os.makedirs(os.path.join(root, d))
        k = AN.Kickoff()
        k.po = {"convene": False, "reason": ""}
        AN.apply_reading(k, back, tok, root, widen=areas)
        self.assertEqual(sorted(k.areas), sorted(areas))
        self.assertTrue(any("conservative superset" in c for c in k.coerced))

    def test_a_small_capture_is_unchanged(self):
        cap, areas = self._cap(n_areas=60, n_read=2)
        back, _ = AN.captured(AN.capture_fields(cap))
        self.assertTrue(all("more" not in e and sorted(e["areas"]) == sorted(areas) for e in back))


GAPS = {
    "casing": [("Split in two (SAFE)", "Single PR (RISKY)"), ("Split in two (`SAFE`)", "Single PR (`RISKY`)"),
               ("Split in two (LGTM)", "Single PR (NG)"), ("Split in two (HIGH)", "Single PR (LOW)")],
    "shaped": [("Split in two (`low-risk`)", "Single PR (`high-risk`)"),
               ("Split in two (`risk: low`)", "Single PR (`risk: high`)"),
               ("Split in two (`is_safe=true`)", "Single PR (`is_safe=false`)"),
               ("Split in two (`risk_low`)", "Single PR (`risk_high`)"),
               ("Split in two (risk_low)", "Single PR (risk_high)")],
    "source": [("로그인만 (요구된 화면만)", "앱 전체 (요구 밖 화면 포함)"), ("ログインのみ (依頼どおり)", "全画面 (依頼外も含む)"),
               ("로그인만 (요청받은 화면만)", "앱 전체 (의뢰 외 화면도)"), ("ログインのみ", "全画面 (頼まれていない画面も)"),
               ("Login only", "Whole app (unrequested screens too)"), ("Login only", "Whole app (out of the request)")],
}
SHOWN = ("홈 화면 (`SafeArea` 유지)", "점수 저장 (`high_score` 테이블만)", "장바구니 (주문한 상품만)",
         "Form (required fields only)", "一覧 (依頼一覧のみ)", "Export (CSV only)", "Login only (API v2)",
         "설정 (요구사항 문서 제외)", "Whole app (`low_memory` mode excluded)", "Login (OK button only)")


class m3LabelGaps(unittest.TestCase):
    def test_gaps_are_refused(self):
        for cls, pairs in GAPS.items():
            for a, b in pairs:
                with self.subTest(cls=cls, pair=(a, b)):
                    got = PF.blind_labels([a, b])
                    self.assertFalse(all(x is not None for x in got) and any("(" in x for x in got), got)

    def test_identifiers_and_product_nouns_stay_shown(self):
        for s in SHOWN:
            with self.subTest(label=s):
                self.assertEqual(PF.neutral_label(s), s)

    def test_unit(self):
        self.assertFalse(PF._ident_shaped("SAFE"))
        self.assertFalse(PF._ident_shaped("is_safe=true"))
        self.assertTrue(PF._ident_shaped("SafeArea"))
        self.assertTrue(PF._ident_shaped("high_score"))
        self.assertTrue(PF._ident_shaped("CSV"))


if __name__ == "__main__":
    unittest.main()
