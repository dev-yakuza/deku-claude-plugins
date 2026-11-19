"""K6 item 18 — the tripwire centres recomputed from the replay's recorded decisions (§9.4-6, §10.4 R4J-M4).

* `normal` = the engine's own rates; a lenient metric where the engine is more lenient than legacy takes legacy's;
* `first_sprint` = the same decisions through the first-sprint forcing in code (EX-ARB dismiss → accept, excluded from
  the coercion rate; HANDOFF assumption → pause; unverified groups → their question), no new call;
* `dev health` picks the first-sprint centre with `--first-sprint`; an older flat file is the normal centre.
"""

import unittest

import _util  # noqa: F401

from workflows.dev import centre as CE
from workflows.dev import health as HE


def J(point, choice, stage="execute", **kv):
    b = {"point": point, "choice": choice, "by": "judge:sonnet", "stage": stage, "unsure": "false", "coerced": "false"}
    b.update(kv)
    return b


REPLAY = {
    1: [J("EX-ARB", "F1:dismiss"), J("STAKES", "low", "analyze")],
    2: [J("EX-ARB", "F1:accept"), J("HANDOFF", "ok_with_assumption", "design")],
    3: [J("STAKES", "high", "analyze"), J("QA", "pass", "qa")],
    4: [J("KICKOFF", "clear", "analyze")],
}


class Centre(unittest.TestCase):
    def test_normal_is_the_engines_own(self):
        c = CE.compute(REPLAY)
        self.assertEqual(c["normal"]["exarb_dismiss"], 0.5)
        self.assertEqual(c["normal"]["stakes_low"], 0.5)
        self.assertEqual(c["n"], 4)

    def test_lenient_engine_takes_legacy(self):
        c = CE.compute(REPLAY, legacy={"exarb_dismiss": 0.2, "stakes_low": 0.9})
        self.assertEqual(c["normal"]["exarb_dismiss"], 0.2)          # engine more lenient → legacy
        self.assertEqual(c["normal"]["stakes_low"], 0.5)             # engine stricter → its own

    def test_first_sprint_forcing(self):
        c = CE.compute(REPLAY)
        fs = c["first_sprint"]
        self.assertEqual(fs["exarb_dismiss"], 0.5)                   # would-dismiss counts, as live (raw_choice)
        self.assertEqual(fs["coercion"], 0.0)                        # first-sprint coercions are not counted
        self.assertEqual(fs["pause_issues"], 0.25)                   # the HANDOFF assumption Issue pauses
        self.assertEqual(fs["explained_pause_issues"], 0.25)

    def test_unverified_groups_pause(self):
        c = CE.compute(REPLAY, unverified=("STAKES", "QA"))
        self.assertEqual(c["first_sprint"]["pause_issues"], 0.75)
        self.assertEqual(c["first_sprint"]["explained_pause_issues"], 0.75)

    def test_pick(self):
        c = CE.compute(REPLAY)
        self.assertIs(CE.pick(c, True), c["first_sprint"])
        self.assertIs(CE.pick(c, False), c["normal"])
        self.assertEqual(CE.pick({"pause_issues": 0.1}, True), {"pause_issues": 0.1})

    def test_compare_against_the_first_sprint_centre(self):
        c = CE.compute(REPLAY)
        m = HE.metrics(REPLAY)
        verdict = dict((k, v) for k, _v, _c, v in HE.compare(m, CE.pick(c, True)))
        self.assertEqual(verdict["pause_issues"], "under-warning")   # 0 live vs the 0.25 first-sprint centre
        self.assertEqual(dict((k, v) for k, _v, _c, v in HE.compare(m, CE.pick(c, False)))["pause_issues"], "ok")


if __name__ == "__main__":
    unittest.main()
