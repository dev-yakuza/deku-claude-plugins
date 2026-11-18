"""K5 — `dev grade` (§9.5 human sheet, deterministic selection, import + count rules into the valves' auto
area) and `dev health` (§9.4-6 rates and bands, absolute tripwires, the first-sprint go/no-go draft)."""

import csv
import io
import json
import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from test_k5_cli import Env

from guildcore import valves as VALVES
from guildcore.records.decisions import DecisionBlock
from workflows.dev import cli as CLI
from workflows.dev import grade as G
from workflows.dev import health as H


def blk(n, **f):
    f.setdefault("by", "judge:opus")
    return DecisionBlock(n, list(f.items()))


def sheet(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=G.COLUMNS)
    w.writeheader()
    for r in rows:
        w.writerow(dict((c, r.get(c, "")) for c in G.COLUMNS))
    return buf.getvalue()


class Select(unittest.TestCase):
    def blocks(self):
        return {7: [blk(1, point="KICKOFF", choice="clear"), blk(2, point="STAKES", choice="low"),
                    blk(3, point="TEST", choice="effective"), blk(4, point="TEST", choice="effective"),
                    blk(5, point="TEST", choice="effective"), blk(6, point="QA", choice="pass", unsure="true"),
                    blk(7, point="engine-start", by="code"),
                    blk(8, point="STAKES", choice="high", status="pending-human"),
                    blk(9, point="STAKES", by="human", resolves="D8", choice="go")]}

    def test_first_sprint_all_high_risk_plus_triggered_plus_calibration(self):
        sel = G.select(self.blocks(), "o/r", True, 0.3, lambda i, b: None)
        got = dict((b.id, why) for _i, b, why in sel)
        self.assertEqual(got["D1"], "high-risk sample")
        self.assertEqual(got["D2"], "high-risk sample")
        self.assertEqual(got["D6"], "triggered: unsure")
        self.assertNotIn("D7", got)                                    # code
        self.assertNotIn("D8", got)                                    # a person decided it
        self.assertEqual(sum(1 for w in got.values() if w == "calibration"), 2)    # TEST: 2 in the first sprint

    def test_steady_selection_is_deterministic_and_rate_bound(self):
        many = {n: [blk(1, point="STAKES", choice="low")] for n in range(1, 201)}
        a = G.select(many, "o/r", False, 0.3, lambda i, b: None)
        b = G.select(many, "o/r", False, 0.3, lambda i, b: None)
        self.assertEqual([(i, x.id) for i, x, _w in a], [(i, x.id) for i, x, _w in b])
        self.assertTrue(30 <= len(a) <= 90, len(a))

    def test_sheet_has_no_grader_column_and_the_raw_choice(self):
        sel = [(7, blk(1, point="EX-ARB", choice="accept:F1", raw_choice="dismiss:F1", coerced="true",
                       coerced_by="first-sprint"), "high-risk sample")]
        rows = G.sheet_rows(sel, "first-sprint", lambda i: "url")
        self.assertEqual(rows[0]["choice"], "dismiss:F1")
        self.assertEqual(rows[0]["group"], "EX-ARB:dismiss")
        self.assertEqual(tuple(csv.DictReader(io.StringIO(G.render_csv(rows))).fieldnames), G.COLUMNS)


class Import(unittest.TestCase):
    def test_watch_then_conservative_and_released_valve_kept_off(self):
        common = os.path.join(tmpdir(self), "c")
        r = G.import_sheet(common, sheet([{"decision_id": "D1", "issue": 7, "group": "STAKES", "given_info": "wrong"}]), "o/r")
        self.assertEqual((r["watch"], r["conservative"]), (["STAKES"], []))
        self.assertNotIn("group.STAKES.conservative", VALVES.effective(common, {}))
        r = G.import_sheet(common, sheet([{"decision_id": "D2", "issue": 8, "group": "STAKES", "given_info": "wrong"}]), "o/r")
        self.assertEqual(r["conservative"], ["STAKES"])
        self.assertTrue(VALVES.effective(common, {})["group.STAKES.conservative"])
        VALVES.human_clear(common, "group.STAKES.conservative", "op")
        G.import_sheet(common, sheet([{"decision_id": "D3", "issue": 9, "group": "STAKES", "given_info": "wrong"}]), "o/r")
        self.assertNotIn("group.STAKES.conservative", VALVES.effective(common, {}))     # released: never re-applied

    def test_irreversible_class_goes_conservative_at_once_and_reimport_is_idempotent(self):
        common = os.path.join(tmpdir(self), "c")
        s = sheet([{"decision_id": "D4", "issue": 7, "group": "SPLIT", "given_info": "wrong"},
                   {"decision_id": "D5", "issue": 7, "group": "QA", "given_info": ""}])
        self.assertEqual(G.import_sheet(common, s, "o/r")["conservative"], ["SPLIT"])
        self.assertEqual(G.import_sheet(common, s, "o/r")["imported"], 0)
        self.assertEqual(len(G.grades(common)), 1)                    # the blank row is not a grade

    def test_watch_clears_after_ten_ok(self):
        common = os.path.join(tmpdir(self), "c")
        G.import_sheet(common, sheet([{"decision_id": "D1", "issue": 7, "group": "QA", "given_info": "wrong"}]), "o/r")
        G.import_sheet(common, sheet([{"decision_id": "D%d" % k, "issue": 7, "group": "QA", "given_info": "ok"}
                                      for k in range(2, 12)]), "o/r")
        self.assertEqual(G.load_state(common)["watch"], {})


class Health(unittest.TestCase):
    def test_rates_bands_and_centre(self):
        b = {7: [blk(1, point="STAKES", choice="low"), blk(2, point="HANDOFF", choice="ok_with_assumption"),
                 blk(3, point="EX-ARB", choice="dismiss:F1")],
             8: [blk(1, point="STAKES", choice="low", unsure="true")]}
        m = H.metrics(b)
        self.assertEqual(m["stakes_low"], 1.0)
        cmp = dict((k, v) for k, _v, _c, v in H.compare(m, None))
        self.assertEqual(cmp["handoff_ok_with_assumption"], "over")    # 100% > 25% absolute band
        self.assertEqual(cmp["stakes_low"], "centre unset")
        cmp = dict((k, v) for k, _v, _c, v in H.compare(m, {"stakes_low": 0.5, "exarb_dismiss": 0.95}))
        self.assertEqual(cmp["stakes_low"], "over")                     # lenient by +50%p > +15%p
        self.assertEqual(cmp["exarb_dismiss"], "ok")

    def test_absolute_tripwires(self):
        common = os.path.join(tmpdir(self), "c")
        from guildcore import journal as J
        J.fsync_append(os.path.join(J.issue_dir(common, 7), "progress.log"), "t end: exit 1 — x")
        J.fsync_append(os.path.join(J.issue_dir(common, 7), "progress.log"), "t end: exit 1 — y")
        hits = H.absolute_tripwires(common, [7, 8], {7: "", 8: "defect: developer wrote outside its scope — x"})
        self.assertEqual(sorted((k, n) for k, n, _e in hits), [("crash-twice", 7), ("scope-violation", 8)])

    def test_cli_health_first_sprint_draft_and_grade_sheet(self):
        e = Env(self)
        from guildcore.decisions import DecisionWriter
        e.h.decisions.record({"point": "STAKES", "by": "judge:opus", "stage": "analyze", "choice": "low",
                              "reason": "small"})
        self.assertEqual(CLI.main(["health", "--first-sprint", "--issues", "7"], e.d), 0)
        rep = json.loads(e.lines()[-1])
        self.assertIn("go_no_go_draft", rep)
        self.assertTrue(rep["go_no_go_draft"][0].startswith("<!-- guild:note -->"))
        self.assertEqual(rep["issues"], [7])
        out = os.path.join(tmpdir(self), "sheet")
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out], e.d), 0)
        rows = list(csv.DictReader(open(os.path.join(out, "issues.csv"))))
        self.assertEqual([r["group"] for r in rows], ["STAKES"])
        self.assertEqual(rows[0]["given_info"], "")
        rows[0]["given_info"] = "wrong"
        with open(os.path.join(out, "filled.csv"), "w") as fh:
            fh.write(sheet(rows))
        self.assertEqual(CLI.main(["grade", "--import", os.path.join(out, "filled.csv")], e.d), 0)
        self.assertEqual(json.loads(e.lines()[-1])["watch"], ["STAKES"])


if __name__ == "__main__":
    unittest.main()
