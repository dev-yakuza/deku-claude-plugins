"""review-k6-r13 — as table tests over the cases the findings name.

m1  the synthetic path presupposes a replay in the SAME input: an input with no replay tuning row verifies no group by
    synthetic (the graded synthetic file alone, replay rows nested per Issue); a row that is not an object is rejected
    (`_rows_rejected`) and closes the synthetic path; `_no_tuning_rows` / `_rows_without_id` / `_split_overlap` are
    on stdout too.
m2  `group` is a §9.5 group name — a judgment / point name (L0-KICKOFF …) is an unknown group, the safe side.
"""

import contextlib
import io
import json
import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir

from workflows.dev.replay import gate_report as GR

TUNE = [{"id": "#999999/D1", "group": "HANDOFF", "set": "tuning", "source": "replay", "agree": True,
         "advance_agree": True},
        {"id": "syn-tuning-only", "group": "DE-ARB", "set": "tuning", "source": "synthetic", "wrong": False}]
PLAN = (("SPLIT", 4), ("DE-ARB", 3), ("DIRECTIVE", 2), ("EX-ARB-dismiss", 2))


def rep(i, ok, g, st="held-out"):
    return {"id": "#%d/D1" % i, "group": g, "set": st, "source": "replay", "agree": ok, "advance_agree": ok}


def syn(i, g, st="held-out"):
    return {"id": "syn-%s-%s-%d" % (g, st, i), "group": g, "set": st, "source": "synthetic", "wrong": False}


SYN = [syn(i, g) for g, n in PLAN for i in range(n)] + [syn(i, g, "tuning") for g, _n in PLAN for i in range(2)]


def by_synthetic(per):
    return sorted(g for g, v in per.items() if isinstance(v, dict) and v.get("by") == "synthetic")


class m1SyntheticNeedsTheReplay(unittest.TestCase):
    def test_control_with_replay_tuning_rows(self):
        self.assertEqual(by_synthetic(GR.decide(SYN + TUNE[:1])), ["DE-ARB", "DIRECTIVE", "EX-ARB-dismiss", "SPLIT"])

    def test_table_no_synthetic_without_a_replay(self):
        nested = [[rep(100 + i, i >= 10, "DIRECTIVE")] for i in range(20)] + [[rep(1, True, "HANDOFF", "tuning")]]
        cases = [("synthetic file only", SYN, None),
                 ("replay rows nested per Issue", nested + SYN, 21),
                 ("one non-object row beside a replay", SYN + TUNE[:1] + ["#5/D1"], 1),
                 ("held-out replay only, no replay tuning", SYN + [rep(7, True, "HANDOFF")], None)]
        for name, rows, not_obj in cases:
            with self.subTest(case=name):
                per = GR.decide(rows)
                self.assertEqual(by_synthetic(per), [])
                self.assertFalse(per["SPLIT"]["verified"], per["SPLIT"]["why"])
                if not_obj:
                    self.assertEqual(per["_rows_rejected"]["row is not an object"], not_obj)
                    self.assertIn("not objects", per["SPLIT"]["why"])
                else:
                    self.assertIn("replay", per["_no_tuning_rows"])
                    self.assertIn("no replay tuning rows", per["SPLIT"]["why"])

    def test_replay_path_unchanged(self):
        good = [rep(300 + i, True, "HANDOFF") for i in range(20)]
        per = GR.decide(good + TUNE[:1] + [42])
        self.assertTrue(per["HANDOFF"]["verified"])

    def test_reports_on_stdout(self):
        d = tmpdir(self)
        src, out = os.path.join(d, "rows.json"), os.path.join(d, "v.json")
        rows = SYN + [{"group": "SPLIT", "set": "tuning", "source": "synthetic"},
                      rep(8, True, "HANDOFF", "tuning"), dict(rep(8, True, "DE-ARB"), id="#8/D2")]
        with open(src, "w", encoding="utf-8") as fh:
            json.dump(rows + [[1]], fh)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(GR.main(["--rows", src, "--out", out]), 0)
        shown = json.loads(buf.getvalue())
        self.assertEqual(shown["verified"], [])
        self.assertEqual(shown["_rows_without_id"], 1)
        self.assertEqual(shown["_split_overlap"], [8])
        self.assertEqual(shown["_rows_rejected"], {"row is not an object": 1})
        os.unlink(src)
        with open(src, "w", encoding="utf-8") as fh:
            json.dump(SYN, fh)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            GR.main(["--rows", src, "--out", out])
        self.assertEqual(json.loads(buf.getvalue())["_no_tuning_rows"], ["replay"])


class m2JudgmentNamesAreUnknownGroups(unittest.TestCase):
    def test_table_point_names_close_the_synthetic_path(self):
        for name in ("L0-KICKOFF", "SJ-STAKES", "KICK-EXPLORE"):
            with self.subTest(group=name):
                per = GR.decide(SYN + TUNE[:1] + [rep(1, True, name)])
                self.assertEqual(by_synthetic(per), [])
                self.assertIn(name, per["_unknown_groups"])

    def test_docstring_states_the_contract(self):
        self.assertIn("§9.5 group name", GR.__doc__)
        self.assertIn("L0-KICKOFF", GR.__doc__)


if __name__ == "__main__":
    unittest.main()
