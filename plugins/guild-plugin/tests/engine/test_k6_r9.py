"""review-k6-r9 — as table tests over the cases the findings name.

M1  `replay/gate_report.decide` checks its rows against each other before they count:
    (a) a group design §10.2-3 plans no synthetic set for (HANDOFF) has no synthetic path — replay only;
    (b) the replay split unit is the Issue — a held-out decision of an Issue with a tuning row is contaminated;
    (c) a replay id is `issue/D-id` — `12/D2` ≡ `#12/D2`, any other spelling is rejected and reported;
    (d) one held-out decision / scenario counts for one group — an id under two groups is dropped from both, reported;
    (e) an explicit group and a `kind` that disagree reject the row.
m2  (reverted by review-k6-r10 M1) the "latest pass" is gone: the copies of one id count once, their worst verdict,
    whatever `pass` they name — the m2 rows of `TABLE` now expect the worst-of result.
m3  no tuning rows of a source → train = test unchecked → a group passing by that source is not verified (reported).
M2  a `-` / `/`-joined rating compound (`low-risk`, `high-risk`, `risk-free`, `unsafe-only`) rates in a whole label;
    `fail-safe`, `thread-safe`, `read-only` stay descriptive.
M3  (superseded by review-k6-r10 M2) the compound-noun exception is gone — every label with a rating word / stem is
    refused whatever the head noun; `M3_TABLE` now expects a refusal for every row.
m1  `fsafe.symlink` / `fsafe.write_bytes` take a temp name unique per call — threads of one process writing the same
    leaf never collide (the K3 187 / 188 flake: a swallowed `FileExistsError` traceback split a `... ok` line).
"""

import os
import threading
import unittest

import _util  # noqa: F401
from _k1 import tmpdir

from guildcore import fsafe
from workflows.dev import predict as PF
from workflows.dev.replay import gate_report as GR


def rep(group, ids, set_="held-out", agree=True, adv=True, **kw):
    return [dict({"id": i, "group": group, "set": set_, "source": "replay", "agree": agree, "advance_agree": adv},
                 **kw) for i in ids]


def syn(group, verdicts, prefix=None, set_="held-out", **kw):
    return [dict({"id": "%s-%d" % (prefix or "syn-" + group, i), "group": group, "set": set_, "source": "synthetic",
                  "wrong": w}, **kw) for i, w in enumerate(verdicts)]


def issues(lo, n, d="D1", hash_=True):
    return [("#%d/%s" if hash_ else "%d/%s") % (lo + i, d) for i in range(n)]


# one tuning row per source, of an Issue / scenario no case uses (m3: without them nothing verifies)
TUNE = rep("HANDOFF", ["#999999/D1"], "tuning") + syn("SPLIT", [False], prefix="syn-tuning-only", set_="tuning")


def decide(rows, tune=True):
    return GR.decide(list(rows) + (TUNE if tune else []))


# (name, group, rows, verified?)
TABLE = [
    # (a) no planned synthetic set → replay only
    ("a: HANDOFF synthetic 2, 1 wrong", "HANDOFF", syn("HANDOFF", [False, True]), False),
    ("a: HANDOFF synthetic 6, 0 wrong", "HANDOFF", syn("HANDOFF", [False] * 6), False),
    ("a: HANDOFF short replay + synthetic", "HANDOFF", rep("HANDOFF", issues(100, 10)) + syn("HANDOFF", [False] * 4),
     False),
    ("a: HANDOFF replay passes", "HANDOFF", rep("HANDOFF", issues(100, 20)), True),
    ("a: DIRECTIVE planned 2", "DIRECTIVE", syn("DIRECTIVE", [False, False]), True),
    ("a: DE-ARB planned 3", "DE-ARB", syn("DE-ARB", [False] * 3), True),
    # (b) the Issue is the split unit
    ("b: other decisions of tuning Issues", "SPLIT",
     rep("SPLIT", issues(1, 20), "tuning") + rep("SPLIT", issues(1, 20, "D2")), False),
    ("b: one held-out decision of a tuning Issue", "SPLIT",
     rep("DE-ARB", ["#7/D1"], "tuning") + rep("SPLIT", issues(200, 19) + ["#7/D4"]), False),
    ("b: disjoint Issues", "SPLIT", rep("SPLIT", issues(1, 20), "tuning") + rep("SPLIT", issues(31, 20)), True),
    # (c) the id spelling
    ("c: '#' dropped, same decision", "SPLIT",
     rep("SPLIT", issues(1, 20, "D2"), "tuning") + rep("SPLIT", issues(1, 20, "D2", hash_=False)), False),
    ("c: '#' dropped in tuning", "SPLIT",
     rep("SPLIT", issues(1, 20, "D2", hash_=False), "tuning") + rep("SPLIT", issues(1, 20, "D2")), False),
    ("c: held-out without '#' counts", "SPLIT", rep("SPLIT", issues(300, 20, hash_=False)), True),
    ("c: '#12/D2' and '12/D2' are one decision", "DE-ARB",
     rep("DE-ARB", issues(300, 10)) + rep("DE-ARB", issues(300, 10, hash_=False)), False),     # n 10
    ("c: leading zeros are one decision", "DE-ARB",
     rep("DE-ARB", issues(300, 19)) + rep("DE-ARB", ["#0300/D1"]), False),                     # n 19
    ("c: malformed ids rejected", "HANDOFF",
     rep("HANDOFF", ["HANDOFF-%d" % i for i in range(20)]), False),
    ("c: malformed ids beside 19 good", "HANDOFF",
     rep("HANDOFF", issues(400, 19) + ["#a/D1", "12/X3", "#12", "12/D", " /D1"]), False),
    # (d) one decision, one group
    ("d: the same 20 under four groups", "DIRECTIVE",
     [r for g in ("SPLIT", "DE-ARB", "DIRECTIVE", "HANDOFF") for r in rep(g, issues(1, 20))], False),
    ("d: a shared id costs both groups", "DE-ARB",
     rep("DE-ARB", issues(500, 20)) + rep("SPLIT", ["#500/D1"]), False),
    ("d: the other group keeps its own ids", "SPLIT",
     rep("DE-ARB", issues(500, 20)) + rep("SPLIT", ["#500/D1"] + issues(600, 20)), True),
    ("d: one scenario under two groups", "DIRECTIVE",
     syn("DIRECTIVE", [False, False], prefix="s") + syn("DE-ARB", [False] * 3, prefix="s"), False),
    # (e) group / kind conflicts
    ("e: EX-ARB:dismiss of kind accept", "EX-ARB-dismiss",
     syn("EX-ARB:dismiss", [False] * 3, kind="accept"), False),
    ("e: EX-ARB:accept of kind dismiss", "EX-ARB-accept",
     syn("EX-ARB:accept", [False] * 3, kind="dismiss"), False),
    ("e: EX-ARB:accept with a dismiss scenario", "EX-ARB-accept",
     syn("EX-ARB:accept", [False] * 3, scenario="blocker-dismiss"), False),
    ("e: EX-ARB:dismiss of kind dismiss", "EX-ARB-dismiss", syn("EX-ARB:dismiss", [False] * 2, kind="dismiss"), True),
    ("e: EX-ARB:dismiss of kind dispute", "EX-ARB-dismiss", syn("EX-ARB:dismiss", [False] * 2, kind="dispute"), True),
    ("e: EX-ARB:dismiss of an unknown kind", "EX-ARB-dismiss", syn("EX-ARB:dismiss", [False] * 2, kind="maybe"),
     False),
    ("e: a kind on a non-EX-ARB group", "SPLIT", syn("SPLIT", [False] * 4, kind="accept"), False),
    ("e: bare EX-ARB still by kind", "EX-ARB-dismiss", syn("EX-ARB", [False] * 2, kind="dismiss"), True),
    # m2 → review-k6-r10 M1: `pass` never counts — the copies of an id, their worst verdict
    ("m2: first pass 6/20 off, final pass 20/20", "SPLIT",
     rep("SPLIT", issues(700, 14), agree=True, **{"pass": 1}) + rep("SPLIT", issues(714, 6), agree=False, **{"pass": 1})
     + rep("SPLIT", issues(700, 20), **{"pass": 2}), False),
    ("m2: first pass fine, final pass 6/20 off", "SPLIT",
     rep("SPLIT", issues(700, 20), **{"pass": 1})
     + rep("SPLIT", issues(700, 14), **{"pass": 2}) + rep("SPLIT", issues(714, 6), agree=False, **{"pass": 2}),
     False),
    ("m2: a final pass of the 6 failures only", "SPLIT",
     rep("SPLIT", issues(700, 14), **{"pass": 1}) + rep("SPLIT", issues(714, 6), agree=False, **{"pass": 1})
     + rep("SPLIT", issues(714, 6), **{"pass": 2}), False),
    ("m2: pass as a string", "SPLIT",
     rep("SPLIT", issues(700, 20), agree=False, **{"pass": "1"}) + rep("SPLIT", issues(700, 20), **{"pass": "2"}),
     False),
    ("m2: some rows without a pass — worst of all", "SPLIT",
     rep("SPLIT", issues(700, 20), agree=False) + rep("SPLIT", issues(700, 20), **{"pass": 2}), False),
    ("m2: no pass anywhere — worst of copies", "SPLIT",
     rep("SPLIT", issues(700, 20), agree=False) + rep("SPLIT", issues(700, 20)), False),
]


class M1GateRows(unittest.TestCase):
    def test_table(self):
        for name, g, rows, want in TABLE:
            with self.subTest(case=name):
                v = decide(rows)[g]
                self.assertEqual(v["verified"], want, v["why"])

    def test_the_review_repro(self):
        cases = {
            "a": ("HANDOFF", syn("HANDOFF", [False, True])),
            "b": ("SPLIT", rep("SPLIT", issues(1, 20), "tuning") + rep("SPLIT", issues(1, 20, "D2"))),
            "c": ("SPLIT", rep("SPLIT", issues(1, 20, "D2"), "tuning") + rep("SPLIT", issues(1, 20, "D2", False))),
            "d": ("DIRECTIVE", [r for g in ("SPLIT", "DE-ARB", "DIRECTIVE", "HANDOFF") for r in rep(g, issues(1, 20))]),
            "e": ("EX-ARB-dismiss", syn("EX-ARB:dismiss", [False] * 3, kind="accept")),
        }
        for name, (g, rows) in sorted(cases.items()):
            for tune in (False, True):
                with self.subTest(case=name, tuning_rows=tune):
                    self.assertFalse(decide(rows, tune)[g]["verified"])

    def test_reports(self):
        per = decide(syn("HANDOFF", [False] * 3))
        self.assertIn("replay only", per["HANDOFF"]["why"])
        self.assertIn("3 synthetic row(s) not counted", per["HANDOFF"]["why"])
        per = decide(rep("DE-ARB", ["#7/D1"], "tuning") + rep("SPLIT", issues(200, 19) + ["#7/D4"]))
        self.assertEqual(per["SPLIT"]["contaminated"], ["#7/D4"])
        self.assertEqual(per["_split_overlap"], [7])
        self.assertIn("Issue", per["SPLIT"]["why"])
        per = decide(rep("HANDOFF", issues(400, 19) + ["#a/D1", "12/X3", "#12"]) + rep("HANDOFF", [7]))
        self.assertEqual(per["_rows_rejected"], {"replay id is not issue/D-id": 4})
        self.assertEqual(per["HANDOFF"]["replay_n"], 19)
        per = decide(rep("DE-ARB", issues(500, 20)) + rep("SPLIT", ["500/D1"]))
        self.assertEqual(per["_conflicting_groups"], {"replay #500/D1": ["DE-ARB", "SPLIT"]})
        self.assertEqual((per["DE-ARB"]["replay_n"], per["SPLIT"]["replay_n"]), (19, 0))
        per = decide(syn("EX-ARB:dismiss", [False] * 3, kind="accept") + syn("SPLIT", [False], kind="x", prefix="k"))
        self.assertEqual(per["_rows_rejected"], {"kind contradicts group": 4})
        self.assertEqual(per["EX-ARB-dismiss"]["synthetic_n"], 0)

    def test_passes_reported_never_counted(self):
        # review-k6-r10 M1: the passes are reported, never counted — worst verdict of the copies
        per = decide(rep("SPLIT", issues(700, 20), agree=False, **{"pass": 1})
                     + rep("SPLIT", issues(700, 20), **{"pass": 2}))["SPLIT"]
        self.assertEqual(per["passes"], {"replay": [1, 2]})
        self.assertEqual((per["replay_n"], per["replay_agree"], per["duplicates"]), (20, 0, 20))
        per = decide(rep("SPLIT", issues(700, 20), agree=False) + rep("SPLIT", issues(700, 20), **{"pass": 2}))
        self.assertEqual(per["SPLIT"]["passes"], {"replay": [2]})
        self.assertEqual(per["SPLIT"]["replay_agree"], 0)

    def test_no_tuning_rows_cannot_verify(self):
        held = rep("HANDOFF", issues(100, 20)) + syn("DIRECTIVE", [False, False])
        per = decide(held, tune=False)
        self.assertEqual(per["_no_tuning_rows"], ["replay", "synthetic"])
        for g in ("HANDOFF", "DIRECTIVE"):
            with self.subTest(group=g):
                self.assertFalse(per[g]["verified"])
                self.assertIn("unchecked", per[g]["why"])
        # tuning rows of ONE source check only that source
        per = GR.decide(held + rep("HANDOFF", ["#999999/D1"], "tuning"))
        self.assertEqual(per["_no_tuning_rows"], ["synthetic"])
        self.assertTrue(per["HANDOFF"]["verified"])
        self.assertFalse(per["DIRECTIVE"]["verified"])
        per = decide(held)
        self.assertNotIn("_no_tuning_rows", per)
        self.assertTrue(per["HANDOFF"]["verified"] and per["DIRECTIVE"]["verified"])
        # a sheet-only group's would_pass is not claimed unchecked either
        per = decide(rep("QA", issues(900, 20)), tune=False)
        self.assertFalse(per["QA"]["would_pass"])

    def test_report_criteria(self):
        doc = GR.report(rep("HANDOFF", issues(100, 20)) + TUNE)
        self.assertEqual(doc["verified"], ["HANDOFF"])
        c = doc["criteria"]
        self.assertEqual(c["synthetic_unplanned"], "replay only")
        self.assertEqual((c["replay_id"], c["split_unit"]), ("issue/D-id", "issue"))
        self.assertTrue(c["one_group_per_id"] and c["tuning_rows_required"])
        self.assertFalse(c["pass_counted"])                                    # review-k6-r10 M1
        self.assertNotIn("HANDOFF", GR.SYNTH_PLANNED)


M2_PAIRS = [("Low-risk split in two", "High-risk single PR"),
            ("A low-risk test-quality addition", "A broader refactor"),
            ("Risk-free: two PRs", "One PR"),
            ("Split in two (a low-risk path)", "Single PR"),
            ("Split in two", "A risk-free rewrite"),
            ("A riskier-but-faster path", "The slow path"),
            ("Unsafe-only cleanup", "Full cleanup"),
            ("A low/high-risk mix", "Something else"),
            ("LOW-RISK: split", "single PR"),
            ("A hazardous-looking rename", "A plain rename")]
M2_SHOWN = [("Fail-safe default", "Fail-open default"), ("Read-only view", "Editable view"),
            ("Thread-safe queue", "Lock-free queue"), ("Type-safe API", "Untyped API"),
            ("Sign-in only", "Sign-up only"), ("iOS/Android build", "Web build")]


class M2HyphenRatingInWholeLabels(unittest.TestCase):
    def test_refused(self):
        for a, b in M2_PAIRS:
            with self.subTest(pair=(a, b)):
                self.assertIn(None, PF.blind_labels([a, b]))

    def test_descriptive_hyphens_shown(self):
        for a, b in M2_SHOWN:
            with self.subTest(pair=(a, b)):
                self.assertEqual(PF.blind_labels([a, b]), [a, b])

    def test_rates(self):
        for w in ("low-risk", "high-risk", "risk-free", "unsafe-only", "riskier-path", "safer-by-default"):
            with self.subTest(word=w):
                self.assertTrue(PF.rating_word("a %s change" % w))
        for w in ("fail-safe", "thread-safe", "read-only", "`low-risk`"):
            with self.subTest(word=w):
                self.assertFalse(PF.rating_word("a %s change" % w))


# (labels, refused?) — en / ko / ja
M3_TABLE = [
    (("Split in two (safe mode only)", "Single PR (unsafe mode only)"), True),
    (("Split in two. Safe mode.", "Single PR. Unsafe mode."), True),
    (("Split in two (safe zone only)", "Single PR (unsafe zone only)"), True),
    (("분할 (안전 구역만)", "단일 PR (위험 구역만)"), True),
    (("分割（安全地帯のみ）", "単一PR（危険地帯のみ）"), True),
    (("Use safe area insets", "Use unsafe area insets"), True),
    (("Show HIGH contrast toggle", "Show LOW contrast toggle"), True),
    (("Show HIGH / LOW contrast toggle", "Show HIGH contrast toggle"), True),
    (("분할 (위험 관리만)", "단일 PR (안전 관리만)"), True),
    (("分割（危険区域のみ）", "単一PR（安全区域のみ）"), True),
    # r8 m1 kept these shown — review-k6-r10 M2: refused (a rating word refuses whatever the head)
    (("Use the safe area insets on iOS", "Use fixed padding"), True),
    (("Add a risk register doc", "Add a README section"), True),
    (("Show HIGH / LOW contrast toggle", "Show a theme picker"), True),
    (("Split in two (safe mode only)", "Single PR (safe mode only)"), True),
    (("분할 (안전 장치 포함)", "단일 PR (안전 장치 포함)"), True),
    (("위험 구역 정리", "위험 구역 유지"), True),
    (("分割（安全装置のみ）", "単一PR（安全装置のみ）"), True),
]


class M3CompoundHeadContrast(unittest.TestCase):
    def test_table(self):
        for labels, refused in M3_TABLE:
            with self.subTest(labels=labels):
                out = PF.blind_labels(list(labels))
                if refused:
                    self.assertIn(None, out)
                else:
                    self.assertEqual(out, list(labels))

    def test_three_options(self):
        self.assertEqual(PF.blind_labels(["A (safe mode only)", "B", "C (unsafe mode only)"]), [None, "B", None])
        # review-k6-r10 M2: alike modifiers no longer shown either
        self.assertEqual(PF.blind_labels(["A (safe mode only)", "B", "C (safe mode only)"]), [None, "B", None])


class m1FsafeTempNames(unittest.TestCase):
    def _hammer(self, fn):
        root = tmpdir(self)
        errors = []

        def run(k):
            try:
                for i in range(30):
                    fn(root, k, i)
            except BaseException as e:
                errors.append(repr(e))
        ths = [threading.Thread(target=run, args=(k,)) for k in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(os.listdir(root)), ["leaf"])                 # no temp name left behind
        return root

    def test_symlink_from_threads(self):
        root = self._hammer(lambda root, k, i: fsafe.symlink(root, "leaf", "/nonexistent/%d-%d" % (k, i)))
        self.assertTrue(os.path.islink(os.path.join(root, "leaf")))

    def test_write_bytes_from_threads(self):
        root = self._hammer(lambda root, k, i: fsafe.write_bytes(root, "leaf", b"%d-%d" % (k, i)))
        with open(os.path.join(root, "leaf"), "rb") as fh:
            self.assertRegex(fh.read().decode(), r"^\d+-29$")

    def test_temp_names_differ_per_call(self):
        t = os.path.join(tmpdir(self), "x")
        names = set(fsafe.tmp_name(t, "-link") for _ in range(50))
        self.assertEqual(len(names), 50)
        self.assertTrue(all(os.path.dirname(n) == os.path.dirname(t) for n in names))   # same directory: atomic
        # review-k6-r10 m2: short, the leaf not in it
        self.assertTrue(all(os.path.basename(n).startswith(".engine-link-%d-" % os.getpid()) for n in names))

    def test_a_link_leaf_on_the_way_is_still_refused(self):
        root = tmpdir(self)
        os.symlink(tmpdir(self), os.path.join(root, "d"))
        with self.assertRaises(fsafe.UnsafePath):
            fsafe.symlink(root, "d/leaf", "x")
        with self.assertRaises(fsafe.UnsafePath):
            fsafe.write_bytes(root, "d/leaf", b"x")


if __name__ == "__main__":
    unittest.main()
