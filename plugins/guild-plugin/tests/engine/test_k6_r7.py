"""review-k6-r7 — as table tests over the cases the findings name.

M1  `judge_took`'s prefix rule only for a summary STORED CUT (the capture records `cut: true` — `analysis.was_cut`;
    a pre-r7 capture without the flag: only the two real cut lengths 300 / 120). Nested readings "X" / "X 및 Y" with
    the short one ≥ 120 characters: a verbatim acceptance is taken (ko / en / ja × (a) / (b)); the refutations still
    fire on the real swaps. The pause names WHICH check refused it (`judge_not_taken` → `NOT_TAKEN`).
M2  ONE rating list: `rates()` reads `RATING_WORDS` (`rating_word`), so a clause with a scope word that holds a
    standalone rating word is `scope-rating` (refused) — "(safe only)", "(risky without more info)"; a rating piece
    in a span beside a scope word too. Without a scope word a bare list word stays as r6 read it.
m1  a head-only reading keeps its tail as ancestor directories (`reading-roots-<token>`); `apply_reading` re-lists the
    real directories under them — the superset holds every captured area. No roots (a pre-r7 capture, a lost value) →
    every irreversible / harness directory of the repository joins the superset.
m2  ANY `dev grade` re-reads the logs of the Issues holding a standing human drop: a forced drop's release is revoked
    by a `dev grade` whose scope does not name that Issue; an unreadable log leaves the drop standing.
m3  upper-case verdict stems (`PASS`, `FAIL`, `APPROVED`, `DANGEROUS` …), camelCase rating pieces (`isSafe`,
    `RiskyChoice`), `#safe` / `@safe` / `safe()`, spans joined by separators, rating keys with values (`safety=high`),
    "in scope" / `IN_SCOPE`, 요구사항 범위 — refused; product nouns and identifiers stay shown.
m4  `replay/gate_report.py` — the §10.2-6 verification criteria in code, offline and deterministic.
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
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import predict as PF
from workflows.dev import unverified as UV
from workflows.dev.replay import gate_report as GR
from workflows.dev.stages import analyze as A
from workflows.dev.stages.base import StageResult

PID = AN.PERSON_READING_ID

X = {"ko": "로그인 화면과 회원가입 화면, 비밀번호 재설정 화면에 다크 모드를 적용하고 시스템 설정을 따라 자동 전환하며 사용자가 앱 "
           "설정에서 직접 켜고 끌 수 있는 토글을 추가하고 선택 값을 기기에 저장해 다음 실행에도 유지한다",
     "en": "apply dark mode to the login, sign-up and password reset screens, follow the system setting automatically, "
           "add a toggle in the app settings and persist the choice",
     "ja": "ログイン画面・会員登録画面・パスワード再設定画面にダークモードを適用し、端末の設定に自動で追従し、アプリ設定に手動切替の"
           "トグルを追加して選択を端末に保存し次回起動時も維持する。さらに画面遷移時のちらつきを抑え、起動直後の白い画面の点滅も防いで、"
           "ダイアログとトーストの配色も合わせる"}
Y = {"ko": " 및 나머지 모든 화면에도 같은 다크 모드를 적용", "en": ", and the same on every other screen of the app",
     "ja": "、および他の全画面にも同じダークモードを適用"}


def _f(*pairs, chosen=PID):
    return {"chosen": chosen, "interpretations": [{"id": i, "summary": s} for i, s in pairs]}


class _Interp(object):
    def __init__(self, readings):
        self.interpretations = [{"id": i, "summary": s, "orig": i.upper()} for i, s in readings]
        self.chosen = readings[0][0]
        self.areas, self.ui_surface, self.safety_net_visual, self.work_type = [], False, False, "feature"
        self.cast = {"participation": [], "gates": [], "skipped": []}
        self.po = {"convene": False}
        self.own_footprints = {}


def _capture(person, other):
    """A capture the way the engine writes it (`reading_capture` → `capture_fields` → `captured`)."""
    k = _Interp([("i1", person), ("i2", other)])
    cap = AN.reading_capture(k, tmpdir_root(), [])
    back, why = AN.captured(AN.capture_fields(cap))
    assert why is None
    ent = [e for e in back if e["token"] == "i1"][0]
    return ent, back


_ROOT = []


def tmpdir_root():
    if not _ROOT:
        _ROOT.append(tempfile.mkdtemp(prefix="k6r7-root-"))
    return _ROOT[0]


class M1NestedReadings(unittest.TestCase):
    def test_table(self):
        """ko / en / ja × (a) the person chose "X 및 Y" / (b) the person chose "X" (X ≥ 120 characters, never cut):
        the verbatim acceptance is taken; the swaps of the same pair are refused with their own kind."""
        for lang in X:
            x, xy = X[lang], X[lang] + Y[lang]
            self.assertGreaterEqual(len(x), 120)
            self.assertLessEqual(len(xy), AN.SUMMARY_CAP)
            for person, other, cell in ((xy, x, "a"), (x, xy, "b")):
                ent, cap = _capture(person, other)
                self.assertFalse(ent["cut"])
                cells = {
                    "verbatim, other listed": (_f(("A", other), (PID, person)), None),
                    "verbatim, fixed id only": (_f((PID, person)), None),
                    "swap: other under the fixed id": (_f(("A", person), (PID, other)), "other-text"),
                    "other under the fixed id alone": (_f((PID, other)), "other-text"),
                    "person's text under another id": (_f((PID, "a re-wording"), ("A", person)), "own-elsewhere"),
                    "duplicate listing of the person's text": (_f((PID, person), ("A", person)), None),
                    "another id chosen": (_f(("A", person), (PID, person), chosen="A"), "chosen"),
                }
                for name, (fields, want) in cells.items():
                    with self.subTest(lang=lang, case=cell, cell=name):
                        self.assertEqual(AN.judge_not_taken(fields, ent, cap), want)
                        self.assertEqual(AN.judge_took(fields, ent, cap), want is None)

    def test_the_cut_is_recorded_not_inferred(self):
        long = "앱 전체 다크 모드 " + "그리고 모든 하위 화면 " * 30
        ent, cap = _capture("로그인만", long)
        other = [e for e in cap if e["token"] == "i2"][0]
        self.assertTrue(other["cut"])
        self.assertEqual(len(other["summary"]), AN.SUMMARY_CAP)
        self.assertFalse(AN.judge_took(_f((PID, long)), ent, cap))                # (a) on a cut summary: a prefix
        # a natural 300-character summary is NOT cut: a longer judge text that starts with it is another text
        nat = ("가" * 299) + "나"
        ent, cap = _capture("로그인만", nat)
        self.assertFalse([e for e in cap if e["token"] == "i2"][0]["cut"])
        self.assertTrue(AN.judge_took(_f((PID, nat + " 그리고 설정 화면")), ent, cap))
        self.assertFalse(AN.judge_took(_f((PID, nat)), ent, cap))                 # exact equality still refutes

    def test_the_short_cut_under_reading_cap(self):
        """a reading whose JSON is still over READING_CAP after the areas split keeps a 120-character summary —
        recorded `cut: true`."""
        e = {"token": "i1", "orig": "A", "summary": "s" * 250, "cut": False, "areas": [],
             "skipped": ["x" * 80] * 5, "participation": ["p" * 400] * 4, "gates": [], "ui_surface": True,
             "safety_net_visual": False, "po_convene": False, "work_type": "feature"}
        back, _ = AN.captured(AN.capture_fields([e]))
        self.assertEqual(len(back[0]["summary"]), AN.SUMMARY_SHORT)
        self.assertTrue(back[0]["cut"])
        self.assertTrue(AN.was_cut(back[0]))

    def test_a_pre_r7_capture(self):
        """no `cut` flag: only the real cut lengths are read as cut (r6 captures stay safe)."""
        self.assertTrue(AN.was_cut({"summary": "s" * 300}))
        self.assertTrue(AN.was_cut({"summary": "s" * 120}))
        self.assertFalse(AN.was_cut({"summary": "s" * 121}))
        self.assertFalse(AN.was_cut({"summary": "s" * 299}))
        self.assertFalse(AN.was_cut({"summary": "s" * 300, "cut": False}))

    def _setup(self, summ):
        h = K4(self, unattended=False, roles=[evidence(self, areas=R3.WIDE)] * 4,
               judges={"KICKOFF": R3._kick("A", summ=summ)}, extra_files=R3.EXTRA)
        h.p._first_sprint = True
        h.p.journal = J.Journal(tempfile.mkdtemp(prefix="k6r7-"), 7, h.clock)
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        ASK.answer(h.decisions, h.writer, 7, R3._pending(h)[-1].id, R3._token(summ, "B"), journal=h.p.journal)
        return h

    def test_the_run(self):
        """ko nested pair through the stage: verbatim → ADVANCE; each refusal kind → ASK naming that kind."""
        summ = {"A": X["ko"], "B": X["ko"] + Y["ko"]}
        cases = (
            ([{"id": "A", "summary": summ["A"]}, {"id": PID, "summary": summ["B"]}], PID, None),
            ([{"id": "A", "summary": summ["B"]}, {"id": PID, "summary": summ["A"]}], PID, "other-text"),
            ([{"id": "A", "summary": summ["B"]}, {"id": PID, "summary": "다른 말로 쓴 해석"}], PID, "own-elsewhere"),
            ([{"id": "A", "summary": summ["A"]}, {"id": "B", "summary": summ["B"]}], "B", "chosen"),
        )
        for interps, chosen, kind in cases:
            with self.subTest(kind=kind):
                h = self._setup(summ)
                k2 = kickoff(ui=True, areas=R3.WIDE, ac=("every screen turns dark",))
                k2.fields["interpretations"] = interps
                k2.fields["chosen"] = chosen
                h.judges["KICKOFF"] = k2
                r = A.run(h.p)
                if kind is None:
                    self.assertEqual(r.kind, StageResult.ADVANCE)
                    continue
                self.assertEqual(r.kind, StageResult.ASK)
                q = R3._pending(h)[-1].get("question")
                self.assertIn("따르지 않음", q)
                self.assertIn(AN.NOT_TAKEN[kind][:20], q)
                for other in set(AN.NOT_TAKEN) - {kind}:
                    self.assertNotIn(AN.NOT_TAKEN[other], q)


# review r7 M2: rating words beside a scope word (+ the held-out qwen #2 label)
M2_PAIRS = [("Split in two (safe only)", "Single PR (risky only)"),
            ("Split in two (LGTM except docs)", "Single PR (NG except docs)"),
            ("Split in two (`low-risk` only)", "Single PR (`high-risk` only)"),
            ("Split in two (`is_safe=true` only)", "Single PR (`is_safe=false` only)"),
            ("user profile, done without tests", "billing integration, risky without more info"),
            ("분할 (안전한 범위만)", "단일 PR (위험한 전체)"), ("分割（安全な範囲のみ）", "単一PR（危険な全体）"),
            ("Split in two (good parts only)", "Single PR (bad parts included)"),
            ("Split (OK only)", "Single (OK except docs)")]
M2_SHOWN = ("Login (OK button only)", "결과 (NG 버튼 제외)", "API (HTTP OK response only)", "Form (required fields only)",
            "Export (CSV only)", "Whole app (`low_memory` mode excluded)", "홈 화면 (`SafeArea` 유지)",
            "점수 저장 (`high_score` 테이블만)", "안전망 테스트 추가 (lib/ 만)")


class M2OneRatingList(unittest.TestCase):
    def test_rating_beside_a_scope_word_is_refused(self):
        for a, b in M2_PAIRS:
            with self.subTest(pair=(a, b)):
                got = PF.blind_labels([a, b])
                self.assertTrue(any(x is None for x in got), got)        # the question is refused

    def test_the_scope_clause_itself(self):
        for c in ("safe only", "risky without more info", "LGTM except docs", "NG except docs", "`low-risk` only",
                  "안전한 범위만", "安全な範囲のみ", "good parts only"):
            with self.subTest(clause=c):
                self.assertEqual(PF.clause_kind(c), "scope-rating")

    def test_one_list(self):
        """every standalone word of `RATING_WORDS` (but the UI nouns) rates — `rates()` reads the same list the
        identifier checks read."""
        for w in sorted(PF.RATING_WORDS - PF.RATING_UI_NOUNS):
            with self.subTest(word=w):
                self.assertTrue(PF.rates("x %s y" % w) or PF.rates(w))
                self.assertTrue(PF.rating_word(w.upper() if w.isascii() else w))
        for w in PF.RATING_UI_NOUNS:
            self.assertFalse(PF.rating_word("press %s" % w))

    def test_without_a_scope_word_as_r6(self):
        self.assertEqual(PF.clause_kind("safe"), "other")                 # refused, never cut
        self.assertEqual(PF.clause_kind("risky reading"), "remark")       # a reading remark — cut
        self.assertEqual(PF.blind_labels(["export function, as the request reads", "quiz module: risky interpretation"]),
                         ["export function", "quiz module"])

    def test_product_nouns_stay_shown(self):
        for s in M2_SHOWN:
            with self.subTest(label=s):
                self.assertEqual(PF.neutral_label(s), s)


def _areas_caps(n_read=5, n_areas=200):
    caps, own = [], {}
    for n in range(1, n_read + 1):
        areas = ["lib/r%d/feature_%03d/presentation/widgets" % (n, i) for i in range(n_areas)]
        own["i%d" % n] = areas
        caps.append({"token": "i%d" % n, "orig": "R%d" % n, "summary": "reading %d" % n, "areas": areas, "cut": False,
                     "ui_surface": True, "safety_net_visual": False, "participation": [], "gates": [],
                     "skipped": [], "po_convene": False, "work_type": "feature"})
    return caps, own


class m1TailRoots(unittest.TestCase):
    def _root(self, own, extra=()):
        root = tempfile.mkdtemp(prefix="k6r7-tail-")
        for a in sum(own.values(), []) + list(extra):
            os.makedirs(os.path.join(root, a), exist_ok=True)
        return root

    def _kick(self, areas):
        k = AN.Kickoff()
        k.po = {"convene": False, "reason": ""}
        k.areas = list(areas)
        return k

    def test_the_review_case_loses_nothing(self):
        caps, own = _areas_caps()
        fields = AN.capture_fields(caps)
        back, why = AN.captured(fields)
        self.assertIsNone(why)
        heads = [e for e in back if e.get("more") is True]
        self.assertTrue(heads)
        root = self._root(own)
        for e in heads:
            self.assertTrue(e["tail_roots"])
            k = self._kick(own[e["token"]][:3])
            AN.apply_reading(k, back, e["token"], root, widen=[])
            with self.subTest(token=e["token"]):
                self.assertEqual(sorted(set(own[e["token"]]) - set(k.areas)), [])
                self.assertTrue(any("re-listed" in c for c in k.coerced))

    def test_the_block_stays_bounded(self):
        caps, _own = _areas_caps(n_read=5, n_areas=400)
        fields = AN.capture_fields(caps)
        for kk, v in fields.items():
            if kk.startswith(AN.READING_ROOTS):
                self.assertLessEqual(len(v), AN.ROOTS_CAP)
        block = DREC.render_block(12, dict({"point": "ask:readiness", "kind": "readiness", "status": "pending-human",
                                            "by": "code", "question": "q", "options": "i1|i2|i3|i4|i5|stop"},
                                           **fields))
        self.assertLess(len(block), 50000)
        blk = markers.BlockDoc.parse(block, DREC.HEADING_RE, DREC.TAIL_RE).blocks[0]
        back, why = AN.captured(dict(blk.fields()))
        self.assertIsNone(why)
        self.assertTrue(all(e.get("tail_roots") for e in back if e.get("more") is True))

    def test_tail_roots(self):
        self.assertEqual(AN.tail_roots(["lib/a/x", "lib/a/y", "lib/b/z"]), ["lib/a/x", "lib/a/y", "lib/b/z"])
        many = ["lib/m%03d/deep/widgets" % i for i in range(300)] + ["test/t%03d" % i for i in range(300)]
        r = AN.tail_roots(many)
        self.assertTrue(all(any(a == q or a.startswith(q + "/") for q in r) for a in many))
        self.assertLessEqual(len(json.dumps(r)), AN.ROOTS_CAP)
        self.assertEqual(AN.tail_roots(["x%04d/y" % i for i in range(400)], cap=50), [AN.WHOLE_REPO])

    def test_unknown_tail_adds_every_hot_directory(self):
        caps, own = _areas_caps(n_read=2, n_areas=10)
        root = self._root(own, extra=("db/migrations/v2", ".claude/guild/gates", "lib/plain"))
        for e in caps:
            e["more"] = True                     # a pre-r7 head-only capture: no roots on the block
        k = self._kick([])
        AN.apply_reading(k, caps, "i1", root, widen=[], globs=["**/migrations/**"])
        self.assertIn("db/migrations/v2", k.areas)
        self.assertTrue(any(a.startswith(".claude/guild/gates") or a == ".claude/guild/gates" for a in k.areas))
        self.assertNotIn("lib/plain", k.areas)
        self.assertTrue(any("tail unknown" in c for c in k.coerced))


class m2ForcedDropAnyScope(unittest.TestCase):
    def _env(self):
        e = Env(self, config={"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": "on"}})
        dec = e.h.decisions
        qid = dec.record({"point": "conservative:QA", "kind": CONS.KIND, "group": "QA", "stage": "qa", "by": "code",
                          "status": "pending-human", "question": "q", "options": ["pass", "block", "stop"],
                          "refs": "conservative:QA:#7:qa:S1:L0", "raised_by": "confirm",
                          "predict_first_counted": "false — inherent: x"})
        dec.resolve(qid, {"point": "conservative:QA", "kind": CONS.KIND, "stage": "qa", "by": "human",
                          "choice": "block", "recommended": "pass"})
        e.h.gh.fx["issues"]["8"] = {"number": 8, "title": "other", "body": "b", "state": "OPEN", "labels": [],
                                    "comments": [], "author_association": "OWNER"}
        return e, qid

    def _row(self, i):
        return {"issue": i, "decision_id": "D%d" % i, "group": "QA", "mode": G.INHERENT_MODE, "choice": "pass",
                "given_info": "ok"}

    def _rep(self, common):
        return [r for r in UV.report(common) if r["group"] == "QA"][0]

    def _released_by_force(self, e):
        out = os.path.join(tmpdir(self), "s")
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out], e.d), 0)
        key = self._rep(e.common)["open"][0]
        self.assertTrue(key.startswith("7/"))
        G.apply_judgments(e.common, [self._row(i) for i in range(10, 16)], "o/r", "human")
        self.assertIsNone(self._rep(e.common)["released_at"])
        res = G.drop_candidate(e.common, key, "operator call", force=True)
        self.assertEqual(res.get("unverified_released"), ["QA"])
        self.assertNotIn("QA", UV.pending(e.common))
        return key

    def test_a_dev_grade_of_another_scope_revokes_the_release(self):
        e, _qid = self._env()
        key = self._released_by_force(e)
        e.out.truncate(0)
        e.out.seek(0)
        self.assertEqual(CLI.main(["grade", "--issues", "8", "--out", os.path.join(tmpdir(self), "s2")], e.d), 0)
        res = json.loads(e.lines()[-1])
        self.assertEqual(res["predict_first"]["human_drops_listed_again"], [key])
        self.assertEqual(res["predict_first"]["release_revoked"], ["QA"])
        rep = self._rep(e.common)
        self.assertEqual((rep["open"], rep["released_at"]), ([key], None))
        self.assertEqual(rep["reopened"], [key])
        self.assertIn("QA", UV.pending(e.common))

    def test_an_unreadable_log_leaves_the_drop(self):
        e, _qid = self._env()
        self._released_by_force(e)
        e.h.gh.fx["issues"].pop("7")             # the Issue cannot be read any more
        self.assertEqual(CLI.main(["grade", "--issues", "8", "--out", os.path.join(tmpdir(self), "s2")], e.d), 0)
        self.assertTrue(self._rep(e.common)["released_at"])

    def test_human_dropped(self):
        st = {"unverified": {"QA": {"dropped": [{"key": "7/D3", "by": "human"}, {"key": "9/D1", "why": "gone"}]},
                             "TEST": {"dropped": [{"key": "7/D5", "by": "human", "forced": True}]}}}
        self.assertEqual(UV.human_dropped(st), {7: {"7/D3", "7/D5"}})


M3_REFUSED = [("A (DANGEROUS)", "B (HARMLESS)"), ("A (CONSERVATIVE)", "B (AGGRESSIVE)"), ("A (PASS)", "B (FAIL)"),
              ("A (YES)", "B (NO)"), ("A (`APPROVED`)", "B (`REJECTED`)"), ("A (`STABLE`)", "B (`UNSTABLE`)"),
              ("A (`DEFAULT`)", "B (`ALT`)"), ("A (`isSafe: true`)", "B (`isSafe: false`)"),
              ("A (`SafeChoice`)", "B (`RiskyChoice`)"), ("A (`#safe`)", "B (`#risky`)"), ("A (`@safe`)", "B (`@risky`)"),
              ("A (`safe()`)", "B (`risky()`)"), ("A (`safe`/`ok`)", "B (`risky`/`ng`)"),
              ("A (`safety=high`)", "B (`safety=low`)"), ("A (`confidence: high`)", "B (`confidence: low`)"),
              ("A (`danger: none`)", "B (`danger: high`)"), ("A (`in-scope`)", "B (`out-of-scope`)"),
              ("A (`IN_SCOPE`)", "B (`OUT_OF_SCOPE`)"), ("A (in scope only)", "B (out of scope too)"),
              ("로그인 (요구사항 범위만)", "앱 전체 (요구사항 밖까지)"), ("ログイン（要件の範囲のみ）", "全画面（要件外も）")]
M3_SHOWN = ("Net (`safety_net` only)", "Report (`confidence_interval` only)", "설정 (요구사항 문서 제외)",
            "Home (`SafeArea` kept)", "Quiz (`CorrectAnswer` widget only)", "Shop (`GoodsList` only)",
            "`adb devices`·`pm grant` 만", "Tests (`test_pass_count` only)")


class m3LabelGaps(unittest.TestCase):
    def test_refused(self):
        for a, b in M3_REFUSED:
            with self.subTest(pair=(a, b)):
                self.assertTrue(any(x is None for x in PF.blind_labels([a, b])))

    def test_shown(self):
        for s in M3_SHOWN:
            with self.subTest(label=s):
                self.assertEqual(PF.neutral_label(s), s)

    def test_known_gap(self):
        """approach words are no rating (`minimal-change` / `big-bang`) — shown, a documented gap (k6-notes r7)."""
        self.assertEqual(PF.blind_labels(["A (`minimal-change`)", "B (`big-bang`)"]),
                         ["A (`minimal-change`)", "B (`big-bang`)"])

    def test_upper_case_verdicts_in_a_whole_label_are_descriptive(self):
        """`PASS` in a sentence an AC line states ("스크립트가 PASS 한다") is no rating outside an aside."""
        s = "대상 파일과 전체 스위트가 green 이고 `scripts/verify_test_coverage.sh` 가 PASS 한다."
        self.assertEqual(PF.neutral_label(s), s)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _rows(group, n, agree, adv, source="replay", set_="held-out", **kw):
    # K6 r8 M1: every row carries its decision id (rows without one are dropped)
    out = []
    for i in range(n):
        # K6 r9 M1(c): `issue/D-id` — an Issue range per group and set (disjoint: no train = test)
        base = 1000 * (1 + sum(ord(c) for c in group) % 97) + (500 if set_ != "held-out" else 0)
        out.append(dict({"id": "#%d/D1" % (base + i), "group": group, "set": set_, "source": source,
                         "agree": i < agree, "advance_agree": i < adv}, **kw))
    return out


def _syn(group, verdicts, **kw):
    # K6 r9 M1(d): one scenario id belongs to one group — the kind is part of a bare EX-ARB scenario's id
    return [dict({"id": "syn-%s%s-%d" % (group, "-" + kw["kind"] if "kind" in kw else "", i), "group": group,
                  "set": "held-out", "source": "synthetic"},
                 **(dict(kw, wrong=w) if w is not None else kw)) for i, w in enumerate(verdicts)]


# K6 r9 m3: train = test is checked only beside tuning rows — one per source, of an Issue / scenario no case uses
_TUNE = [{"id": "#999999/D1", "group": "HANDOFF", "set": "tuning", "source": "replay", "agree": True,
          "advance_agree": True},
         {"id": "syn-tuning-only-0", "group": "SPLIT", "set": "tuning", "source": "synthetic", "wrong": False}]


class m4GateReport(unittest.TestCase):
    # K6 r8: rows carry ids (M1), a failed replay is not covered by synthetic (user decision 1), the OPEN / INHERENT
    # groups are recorded but never verified (user decision 2) — the table moved its cases to groups the writer may
    # verify (HANDOFF · DE-ARB · DIRECTIVE · ESCALATE · SPLIT · EX-ARB); the sheet-only cases are `test_k6_r8`'s
    def test_criteria(self):
        rows = (_rows("HANDOFF", 20, 17, 19) + _rows("DIRECTIVE", 19, 19, 19) + _rows("DE-ARB", 20, 16, 20)
                + _syn("DE-ARB", [False] * 3)
                + _rows("ESCALATE", 30, 30, 28) + _rows("EX-ARB:accept", 40, 40, 40, set_="tuning")
                + _syn("SPLIT", [False] * 4)
                + _syn("EX-ARB:dismiss", [False, False]) + _syn("EX-ARB", [True], kind="dispute")
                + _syn("DIRECTIVE", [True, False, False])
                + _syn("EX-ARB", [None] * 3, kind="accept")
                + _rows("QA", 20, 20, 20)
                # K6 r12 M1: an unknown group on a REPLAY row closes every synthetic path — here a synthetic one
                + [{"id": "x", "group": "NOPE", "set": "held-out", "source": "synthetic", "wrong": False}])
        per = GR.decide(rows + _TUNE)
        want = {"HANDOFF": True,         # 17/20 = 85 %, 19/20 = 95 %
                "DE-ARB": False,         # 16/20 = 80 % — and a failed replay is not covered by synthetic (r8 1)
                "ESCALATE": False,       # advance 28/30 < 95 %
                "SPLIT": True,           # synthetic n 4 = planned, wrong 0
                "EX-ARB-dismiss": False,  # high risk: the dispute row is wrong 1 > 0
                "DIRECTIVE": False,      # replay n 19 < 20 — but replayed, so replay only (r11 M1)
                "EX-ARB-accept": False,  # tuning never gates; synthetic rows without a verdict
                "QA": False,             # INHERENT — sheet only (r8 2), recorded as would_pass
                "KICKOFF": False}        # nothing — "no synthetic = not passed"
        for g, v in want.items():
            with self.subTest(group=g):
                self.assertEqual(per[g]["verified"], v, per[g]["why"])
        self.assertTrue(per["QA"]["would_pass"])
        self.assertEqual(per["_unknown_groups"], {"NOPE": 1})

    def test_writer_is_deterministic_and_unverified_reads_it(self):
        d = tmpdir(self)
        src = os.path.join(d, "rows.json")
        with open(src, "w", encoding="utf-8") as fh:
            json.dump({"rows": _rows("HANDOFF", 20, 20, 20) + _TUNE}, fh)
        a, b = os.path.join(d, "a.json"), os.path.join(d, "b.json")
        self.assertEqual(GR.main(["--rows", src, "--out", a, "--replay", "test"]), 0)
        self.assertEqual(GR.main(["--rows", src, "--out", b, "--replay", "test"]), 0)
        self.assertEqual(_read(a), _read(b))
        doc = json.loads(_read(a))
        self.assertEqual(doc["verified"], ["HANDOFF"])
        self.assertEqual(doc["release_after"], 5)
        self.assertNotIn("HANDOFF", UV.unverified(a))
        self.assertIn("TEST", UV.unverified(a))

    def test_the_shipped_file_names_a_real_writer(self):
        about = json.loads(_read(UV.FILE))["about"]
        self.assertIn("replay/gate_report.py", about)
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(UV.FILE), "replay", "gate_report.py")))


if __name__ == "__main__":
    unittest.main()
