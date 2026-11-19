"""K6 item 14 — the L0-ESCALATE cap (3 / Issue, reset by every human decision) and the repeat rule (§4.2, §4.3).

No G-ESCALATE judge is wired: every unknown state / engine FAIL pauses. The cap and the repeat rule still hold on the
record (`mj point: G-ESCALATE`), and the FSM's engine-FAIL pause carries them.
"""

import unittest

import _util  # noqa: F401
from _k1 import Clock, tmpdir

from guildcore import journal as J
from workflows.dev import conservative as CONS
from workflows.dev import escalation as ESC


class Cap(unittest.TestCase):
    def setUp(self):
        self.j = J.Journal(tmpdir(self), 7, clock=Clock())

    def test_fourth_in_one_epoch_is_the_cap(self):
        lines = [ESC.note(self.j, "engine:KeyError", "KeyError — 'x%d'" % i) for i in range(4)]
        self.assertFalse(any("cap reached" in x for x in lines[:3]))
        self.assertTrue(lines[3].startswith("escalation cap reached (4 this epoch)"))
        self.assertEqual(self.j.escalations_this_epoch(), 4)
        self.assertFalse(ESC.allowed(self.j))

    def test_a_human_decision_resets(self):
        for i in range(3):
            ESC.note(self.j, "s", "state %s" % ("abc"[i]))
        self.j.bump_epoch("answer D3")
        self.assertTrue(ESC.allowed(self.j))
        self.assertNotIn("cap reached", ESC.note(self.j, "s", "state d"))

    def test_repeat_is_marked(self):
        ESC.note(self.j, "engine:KeyError", "KeyError — 'x' at 0x1a2b3c4d")
        again = ESC.note(self.j, "engine:KeyError", "KeyError — 'x' at 0x9f8e7d6c")
        self.assertIn("repeated", again)
        self.assertNotIn("repeated", ESC.note(self.j, "engine:KeyError", "KeyError — 'y'"))

    def test_no_journal_is_a_plain_line(self):
        self.assertEqual(ESC.note(None, "s", "x"), "x")

    def test_escalate_is_not_gated_and_says_why(self):
        self.assertIn("ESCALATE", CONS.NOT_GATED)
        self.assertIn("unknown state", CONS.NOT_GATED["ESCALATE"])


if __name__ == "__main__":
    unittest.main()
