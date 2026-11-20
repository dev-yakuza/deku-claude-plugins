"""review-k6-r8 — as table tests over the cases the findings name.

M1  `replay/gate_report.decide` checks its rows before they count: a row needs an `id` (dropped and reported
    without one); a repeated id counts once (its worst verdict); an id held out AND tuned (train = test) makes the
    group unverifiable (`contaminated`); synthetic needs the group's planned held-out count and wrong < n (0 wrong for
    the high-risk groups); a bare `EX-ARB` row counts only for its kind (dismiss / dispute → EX-ARB-dismiss, accept →
    EX-ARB-accept, none → unknown). User decision 1 (2026-11-20, K6 r8): a replay that measured a group (n ≥ 20) and
    failed is never covered by synthetic. User decision 2: OPEN (KICKOFF · STAKES) and INHERENT groups are recorded
    (`would_pass`) but never verified — released only by sheet verdicts; `unverified()` ignores them in `verified`.
M2  a sentence-final full stop is a word boundary for the rating list (`_WORD` / `_UI_VERDICT`): "(all safe.)",
    "Split in two. Safe." refused; `foo.safe` / `safe.dart` stay identifiers.
m1  a list word heading a known compound noun ("safe area insets", "risk register", "dangerous goods", "HIGH / LOW
    contrast", 위험 물품) is descriptive — shown; the r7 refusals stay.
m2  a `-` / `/`-joined rating piece beside a scope word outside a span ("(low-risk only)", "(safe-only)") is refused.
m3  a standing human drop a `dev grade` could not re-check is reported (`human_drops_unchecked`, `dev health`) and
    its `last_check` recorded; every `dev grade` still re-reads it (revocation unchanged), each Issue once per run.
"""

import json
import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from test_k5_cli import Env

from workflows.dev import cli as CLI
from workflows.dev import conservative as CONS
from workflows.dev import grade as G
from workflows.dev import predict as PF
from workflows.dev import unverified as UV
from workflows.dev.replay import gate_report as GR


def rep(group, n, agree, adv, set_="held-out", ids=None, **kw):
    return [dict({"id": ids[i] if ids else "#%s/D%d" % (group, i), "group": group, "set": set_, "source": "replay",
                  "agree": i < agree, "advance_agree": i < adv}, **kw) for i in range(n)]


def syn(group, verdicts, prefix=None, **kw):
    return [dict({"id": "%s-%d" % (prefix or "syn-" + group, i), "group": group, "set": "held-out",
                  "source": "synthetic"}, **(dict(kw, wrong=w) if w is not None else kw))
            for i, w in enumerate(verdicts)]


SHEET_ONLY = sorted(set(PF.OPEN_GROUPS) | set(CONS.INHERENT))

# (name, group, rows, verified?) — the review's five paths (a)–(e) with ids, and the passes beside them
TABLE = [
    # (a) thin synthetic: n below the planned held-out count, or every row wrong
    ("a: DIRECTIVE n1 wrong1", "DIRECTIVE", syn("DIRECTIVE", [True]), False),
    ("a: DIRECTIVE n1 right", "DIRECTIVE", syn("DIRECTIVE", [False]), False),            # planned 2
    ("a: DIRECTIVE n2 wrong2", "DIRECTIVE", syn("DIRECTIVE", [True, True]), False),
    ("a: DIRECTIVE n2 wrong1", "DIRECTIVE", syn("DIRECTIVE", [True, False]), True),
    ("a: SPLIT 3 of planned 4", "SPLIT", syn("SPLIT", [False] * 3), False),
    ("a: SPLIT 4 of planned 4", "SPLIT", syn("SPLIT", [False] * 4), True),
    ("a: SPLIT high risk wrong 1", "SPLIT", syn("SPLIT", [False] * 4 + [True]), False),
    ("a: HANDOFF no plan, n1", "HANDOFF", syn("HANDOFF", [False]), False),               # SYNTH_MIN_N 2
    ("a: HANDOFF no plan, n2", "HANDOFF", syn("HANDOFF", [False] * 2), True),
    ("a: synthetic without verdict", "HANDOFF", syn("HANDOFF", [None] * 3), False),
    # (b) the same rows twice — one decision counts once
    ("b: HANDOFF 10 twice", "HANDOFF", rep("HANDOFF", 10, 10, 10) * 2, False),
    ("b: HANDOFF 20 twice", "HANDOFF", rep("HANDOFF", 20, 20, 20) * 2, True),
    ("b: synthetic twice", "SPLIT", syn("SPLIT", [False] * 2) * 2, False),
    ("b: rows without id", "HANDOFF", [dict(r, id=None) for r in rep("HANDOFF", 20, 20, 20)], False),
    # (c) train = test
    ("c: held-out == tuning", "HANDOFF", rep("HANDOFF", 20, 20, 20, "tuning") + rep("HANDOFF", 20, 20, 20), False),
    ("c: one shared id", "HANDOFF", rep("HANDOFF", 1, 1, 1, "tuning") + rep("HANDOFF", 25, 25, 25), False),
    ("c: shared with another group's tuning", "DE-ARB",
     rep("HANDOFF", 1, 1, 1, "tuning", ids=["#9/D1"]) + rep("DE-ARB", 20, 20, 20, ids=["#9/D1"] +
                                                            ["#d/D%d" % i for i in range(19)]), False),
    ("c: synthetic scenario also tuned", "SPLIT",
     [dict(r, set="tuning") for r in syn("SPLIT", [False])]
     + syn("SPLIT", [False] * 4), False),
    ("c: disjoint sets", "HANDOFF", rep("HANDOFF", 20, 20, 20, "tuning", ids=["t%d" % i for i in range(20)])
     + rep("HANDOFF", 20, 20, 20), True),
    # (d) bare EX-ARB by kind
    ("d: accept scenarios never verify dismiss", "EX-ARB-dismiss",
     syn("EX-ARB", [False] * 3, scenario="accept-x"), False),
    ("d: accept scenarios verify accept", "EX-ARB-accept", syn("EX-ARB", [False] * 3, kind="accept"), True),
    ("d: dismiss kind", "EX-ARB-dismiss", syn("EX-ARB", [False] * 2, kind="dismiss"), True),
    ("d: dispute counts for dismiss", "EX-ARB-dismiss",
     syn("EX-ARB", [False], kind="dismiss") + syn("EX-ARB", [False], prefix="d2", kind="dispute"), True),
    ("d: dismiss by scenario word", "EX-ARB-dismiss", syn("EX-ARB", [False] * 2, scenario="blocker-dismiss"), True),
    ("d: no kind", "EX-ARB-dismiss", syn("EX-ARB", [False] * 3), False),
    ("d: both kinds", "EX-ARB-dismiss", syn("EX-ARB", [False] * 3, scenario="dismiss-then-accept"), False),
    ("d: high risk wrong 1", "EX-ARB-dismiss", syn("EX-ARB", [False, False, True], kind="dismiss"), False),
    # (e) + user decision 1: a failed replay is not covered by synthetic
    ("e: HANDOFF replay fails, synthetic", "HANDOFF",
     rep("HANDOFF", 30, 15, 30) + syn("HANDOFF", [True, False]), False),
    ("e: replay fails by advance, perfect synthetic", "DE-ARB",
     rep("DE-ARB", 20, 20, 18) + syn("DE-ARB", [False] * 6), False),
    ("e: replay short (n 19), synthetic passes", "DE-ARB",
     rep("DE-ARB", 19, 0, 0) + syn("DE-ARB", [False] * 3), True),
    ("e: replay passes", "DE-ARB", rep("DE-ARB", 20, 17, 19), True),
]


class M1GateReportRows(unittest.TestCase):
    def test_table(self):
        for name, g, rows, want in TABLE:
            with self.subTest(case=name):
                v = GR.decide(rows)[g]
                self.assertEqual(v["verified"], want, v["why"])

    def test_the_review_repro_cases(self):
        def r(group, n, agree, adv, set_="held-out", ids=None):
            return [{"group": group, "set": set_, "source": "replay", "agree": i < agree, "advance_agree": i < adv,
                     "id": (ids[i] if ids else None)} for i in range(n)]
        cases = {"a": ("AN-PO", [{"group": "AN-PO", "set": "held-out", "source": "synthetic", "wrong": True}]),
                 "b": ("QA", r("QA", 10, 10, 10) * 2),
                 "c": ("TEST", r("TEST", 20, 20, 20, "tuning", ["#%d/D1" % i for i in range(20)])
                       + r("TEST", 20, 20, 20, "held-out", ["#%d/D1" % i for i in range(20)])),
                 "d": ("EX-ARB-dismiss", [{"group": "EX-ARB", "set": "held-out", "source": "synthetic",
                                           "wrong": False, "scenario": "accept-%d" % i} for i in range(3)]),
                 "e": ("HANDOFF", r("HANDOFF", 30, 15, 30) + [{"group": "HANDOFF", "set": "held-out",
                                                                "source": "synthetic", "wrong": w}
                                                               for w in (True, False)])}
        for name, (g, rows) in sorted(cases.items()):
            with self.subTest(case=name):
                self.assertFalse(GR.decide(rows)[g]["verified"])

    def test_reports_why(self):
        per = GR.decide(rep("HANDOFF", 10, 10, 10) * 2 + [{"group": "HANDOFF", "set": "held-out"}])
        self.assertEqual(per["HANDOFF"]["duplicates"], 10)
        self.assertEqual(per["HANDOFF"]["replay_n"], 10)
        self.assertEqual(per["_rows_without_id"], 1)
        per = GR.decide(rep("HANDOFF", 20, 20, 20, "tuning") + rep("HANDOFF", 20, 20, 20))
        self.assertEqual(len(per["HANDOFF"]["contaminated"]), 20)
        self.assertIn("train = test", per["HANDOFF"]["why"])
        per = GR.decide(rep("HANDOFF", 30, 15, 30) + syn("HANDOFF", [False] * 3))
        self.assertIn("user decision 1", per["HANDOFF"]["why"])
        per = GR.decide(syn("SPLIT", [False] * 3))
        self.assertIn("< planned 4", per["SPLIT"]["why"])
        per = GR.decide(syn("EX-ARB", [False] * 2))
        self.assertEqual(per["_unknown_groups"], {"EX-ARB?": 2})

    def test_a_duplicate_counts_its_worst_verdict(self):
        rows = rep("HANDOFF", 20, 20, 20) + [dict(rep("HANDOFF", 1, 0, 0)[0])] * 3   # #HANDOFF/D0 disagrees too
        per = GR.decide(rows)["HANDOFF"]
        self.assertEqual((per["replay_n"], per["replay_agree"]), (20, 19))
        self.assertTrue(per["verified"])                     # 19/20 = 95 % agreement, advance 19/20 = 95 %
        rows = syn("SPLIT", [False] * 4) + syn("SPLIT", [True])
        self.assertFalse(GR.decide(rows)["SPLIT"]["verified"])      # syn-SPLIT-0 again, wrong: worst = wrong


class UserDecision1(unittest.TestCase):
    def test_synthetic_only_for_a_short_replay(self):
        for n in (0, 5, 19):
            with self.subTest(replay_n=n):
                self.assertTrue(GR.decide(rep("HANDOFF", n, 0, 0) + syn("HANDOFF", [False] * 2))["HANDOFF"]
                                ["verified"])
        for agree, adv in ((16, 20), (20, 18), (0, 0)):
            with self.subTest(agree=agree, adv=adv):
                v = GR.decide(rep("HANDOFF", 20, agree, adv) + syn("HANDOFF", [False] * 5))["HANDOFF"]
                self.assertFalse(v["verified"])
                self.assertIsNone(v["by"])


class UserDecision2(unittest.TestCase):
    def test_open_and_inherent_groups_are_recorded_never_verified(self):
        self.assertEqual(SHEET_ONLY, sorted(["KICKOFF", "STAKES", "INTEGRATE", "TEST", "QA", "AN-PO", "VIS-ENV",
                                             "EX-DWC"]))
        for g in SHEET_ONLY:
            with self.subTest(group=g):
                per = GR.decide(rep(g, 30, 30, 30) + syn(g, [False] * 6))[g]
                self.assertFalse(per["verified"])
                self.assertTrue(per["sheet_only"])
                self.assertTrue(per["would_pass"])            # the replay result is kept
                self.assertEqual(per["replay_n"], 30)
                self.assertIn("user decision 2", per["why"])
                failed = GR.decide(rep(g, 30, 10, 30))[g]
                self.assertFalse(failed["would_pass"])

    def test_the_report_and_unverified(self):
        rows = []
        for g in SHEET_ONLY + ["HANDOFF"]:
            rows += rep(g, 20, 20, 20)
        doc = GR.report(rows)
        self.assertEqual(doc["verified"], ["HANDOFF"])
        self.assertEqual(doc["criteria"]["sheet_only"], SHEET_ONLY)
        # a hand-edited verification.json naming them is ignored: they stay unverified until the sheet releases them
        d = tmpdir(self)
        path = os.path.join(d, "v.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"verified": SHEET_ONLY + ["HANDOFF", "EX-ARB:dismiss"], "release_after": 5}, fh)
        unv = UV.unverified(path)
        for g in SHEET_ONLY:
            self.assertIn(g, unv)
        self.assertNotIn("HANDOFF", unv)
        self.assertNotIn("EX-ARB-dismiss", unv)
        self.assertEqual(UV.SHEET_ONLY, frozenset(SHEET_ONLY))


M2_PAIRS = [("Split in two (all safe.)", "Single PR (all risky.)"),
            ("Split in two (only the safe.)", "Single PR (only the risky.)"),
            ("Split in two, only safe.", "Single PR, only risky."),
            ("Split in two. Safe.", "Single PR. Risky."),
            ("Split in two (except docs, LGTM.)", "Single PR (except docs, NG.)"),
            ("calendar sync only", "billing integration, without more info risky.")]


class M2SentenceFinalStop(unittest.TestCase):
    def test_the_six_pairs_are_refused(self):
        for a, b in M2_PAIRS:
            with self.subTest(pair=(a, b)):
                self.assertTrue(any(x is None for x in PF.blind_labels([a, b])))

    def test_words(self):
        for t in ("safe.", "it is safe.", "Risky.", "(only the risky.)", "LGTM."):
            with self.subTest(text=t):
                self.assertTrue(PF.rating_word(t))
        for t in ("use foo.safe here", "open safe.dart", "the a.risky.b key"):
            with self.subTest(text=t):
                self.assertFalse(PF.rating_word(t))
        self.assertTrue(PF._UI_VERDICT.search("(except docs, NG.)"))
        self.assertFalse(PF._UI_VERDICT.search("(see ng.module only)"))

    def test_identifiers_stay_shown(self):
        # (`` `safe.dart` `` in a span is a rating piece since r6 m3 — unchanged)
        for a, b in (("Split (lib/safe.dart only)", "Single PR"), ("Split (see foo.safe only)", "Single PR"),
                     ("Use foo.safe", "Use bar")):
            with self.subTest(pair=(a, b)):
                self.assertEqual(PF.blind_labels([a, b]), [a, b])


M1_SHOWN = [("Use the safe area insets on iOS", "Use fixed padding"), ("Add a risk register doc", "Skip the doc"),
            ("Show HIGH / LOW contrast toggle", "No toggle"), ("Dangerous goods label on items", "Plain label"),
            ("위험 물품 목록 화면 추가", "목록 화면 그대로"), ("Enable safe mode on crash", "Restart"),
            ("危険物リスト追加", "そのまま"), ("안전 장치 설정 추가", "그대로"), ("Split (safe area only)", "Single PR")]
M1_REFUSED = [("Split in two (safe only)", "Single PR (risky only)"), ("Split in two. Safe.", "Single PR"),
              ("Split (risky area only)", "Single PR"), ("Show HIGH / SAFE contrast", "No toggle"),
              ("Use safe defaults", "Use fast defaults"), ("A risky register change", "No change"),
              ("Split (위험만)", "Single PR"), ("안전하게 분할", "한 번에"), ("危険な変更", "そのまま"),
              ("Hazardous migration", "Plain migration"), ("Split (HIGH contrast)", "Single PR (LOW)")]


class m1CompoundNouns(unittest.TestCase):
    def test_descriptive_compounds_are_shown(self):
        for a, b in M1_SHOWN:
            with self.subTest(pair=(a, b)):
                self.assertEqual(PF.blind_labels([a, b]), [a, b])

    def test_ratings_stay_refused(self):
        for a, b in M1_REFUSED:
            with self.subTest(pair=(a, b)):
                self.assertTrue(any(x is None for x in PF.blind_labels([a, b])))


M2H_REFUSED = [("Split in two (low-risk only)", "Single PR (high-risk only)"),
               ("Split in two (safe-only)", "Single PR (risky-only)"),
               ("Split in two (safe/only)", "Single PR (risky/only)"),
               ("Split (except low-risk files)", "Single PR"), ("분할 (low-risk 만)", "단일 PR")]
M2H_SHOWN = [("Split (iOS/Android only)", "Single PR"), ("Split (read-only)", "Single PR"),
             ("Split (sign-in only)", "Single PR"), ("Split (OK/Cancel only)", "Single PR"),
             ("Split (x-y only)", "Single PR")]


class m2HyphenOutsideSpans(unittest.TestCase):
    def test_refused(self):
        for a, b in M2H_REFUSED:
            with self.subTest(pair=(a, b)):
                self.assertTrue(any(x is None for x in PF.blind_labels([a, b])))

    def test_shown(self):
        for a, b in M2H_SHOWN:
            with self.subTest(pair=(a, b)):
                self.assertEqual(PF.blind_labels([a, b]), [a, b])


class m3RecheckReported(unittest.TestCase):
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
        out = os.path.join(tmpdir(self), "s")
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out], e.d), 0)
        key = self._rep(e.common)["open"][0]
        G.drop_candidate(e.common, key, "operator call", force=True)
        return e, key

    def _rep(self, common):
        return [r for r in UV.report(common) if r["group"] == "QA"][0]

    def _grade(self, e, issues="8"):
        e.out.truncate(0)
        e.out.seek(0)
        self.assertEqual(CLI.main(["grade", "--issues", issues, "--out", os.path.join(tmpdir(self), "s2")], e.d), 0)
        return json.loads(e.lines()[-1])["predict_first"]

    def test_an_unreadable_log_is_reported(self):
        e, key = self._env()
        e.h.gh.fx["issues"].pop("7")
        pf = self._grade(e)
        self.assertEqual([x["key"] for x in pf["human_drops_unchecked"]], [key])
        self.assertIn("unreadable", pf["human_drops_unchecked"][0]["why"])
        rep = self._rep(e.common)
        self.assertEqual(rep["human_drops_unchecked"], [key])
        d = rep["dropped_by_human"][0]
        self.assertEqual((d["last_check"]["result"], d["check_failures"]), ("unreadable", 1))
        self._grade(e)
        self.assertEqual(self._rep(e.common)["dropped_by_human"][0]["check_failures"], 2)
        self.assertEqual(rep["open"], [])                 # the drop stands (as r7)

    def test_a_log_without_engine_blocks_is_reported(self):
        e, key = self._env()
        e.h.gh.fx["issues"]["7"]["comments"] = []
        pf = self._grade(e)
        self.assertEqual([x["key"] for x in pf["human_drops_unchecked"]], [key])
        self.assertEqual(self._rep(e.common)["dropped_by_human"][0]["last_check"]["result"], "no-engine-block")

    def test_a_successful_check_resets_and_is_recorded(self):
        e, key = self._env()
        saved = list(e.h.gh.fx["issues"]["7"]["comments"])
        e.h.gh.fx["issues"]["7"]["comments"] = []
        self._grade(e)
        e.h.gh.fx["issues"]["7"]["comments"] = saved
        pf = self._grade(e)                      # readable again: listed again → open, as r7 (revocation intact)
        self.assertEqual(pf["human_drops_listed_again"], [key])
        self.assertEqual(pf["human_drops_unchecked"], [])
        self.assertEqual(self._rep(e.common)["open"], [key])

    def test_each_issue_is_read_once_per_run(self):
        e, key = self._env()
        e.h.gh.fx["issues"]["7"]["comments"] = []        # the drop stands (unchecked) across runs
        for _ in range(2):
            e.h.gh.calls[:] = []
            self._grade(e)                                # out of scope: read for the drop, once per run
            self.assertEqual(e.h.gh.calls.count(("comments", 7)), 1)   # and every dev grade re-reads (revocation)
        e.h.gh.calls[:] = []
        self._grade(e, "7")
        in_scope = e.h.gh.calls.count(("comments", 7))
        e.h.gh.calls[:] = []
        self._grade(e, "7,8")
        self.assertEqual(e.h.gh.calls.count(("comments", 7)), in_scope)   # no extra read for the drop

if __name__ == "__main__":
    unittest.main()
