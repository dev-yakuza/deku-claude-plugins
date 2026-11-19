"""K6 items 27 + 43 — the gated groups come from the §9.5 table, and every question of the r10 X ≠ Y table is blind.

27: `conservative.GATED` is derived from `valves.GROUPS` (the §9.5 group list) minus `NOT_GATED` (groups with their own
conservative side, each with a reason) — a new §9.5 group is gated by default; the r9 / r10 / r11 tables already fail
until such a group has a scenario, its output shapes, its expectations and its confirm rows.
43: in the r10 table (a person answers X over a judge's Y ≠ X, every gated group and option), EVERY conservative
question the case raises — the first and any later one (the next entry, a repair question) — is blind: a
`recommended_sha`, no open `recommended`, no `predict_first_refused`.
"""

import unittest
from unittest import mock

import _util  # noqa: F401
import test_k5_r10 as R10

from guildcore import valves as VALVES
from workflows.dev import conservative as CONS


class Derived(unittest.TestCase):
    def test_every_section_95_group_is_gated_or_named(self):
        for g in VALVES.GROUPS:
            self.assertTrue((g in CONS.GATED) != (g in CONS.NOT_GATED), g)
        for g, why in CONS.NOT_GATED.items():
            self.assertIn(g, VALVES.GROUPS)
            self.assertTrue(len(why) > 20, g)

    def test_a_new_group_is_gated_by_default(self):
        with mock.patch.object(VALVES, "GROUPS", VALVES.GROUPS + ("NEWGROUP",)):
            self.assertIn("NEWGROUP", CONS._gated())

    def test_the_tables_cover_every_gated_group(self):
        self.assertEqual(sorted(R10.SHAPES), sorted(CONS.GATED))


class EveryQuestionBlind(unittest.TestCase):
    def test_x_over_y_questions_are_blind(self):
        n = 0
        for group, x, y in R10.cases():
            with self.subTest(group=group, option=x, judge=y):
                o = R10.run_case(self, group, x, y)
                qs = [b for b in o["all"] if b.get("kind") == CONS.KIND and b.get("status") == "pending-human"]
                self.assertTrue(qs)
                for q in qs:
                    n += 1
                    self.assertTrue(q.get("recommended_sha"), (group, x, y, q.id))
                    self.assertIsNone(q.get("recommended"), (group, x, y, q.id))
                    self.assertIsNone(q.get("predict_first_refused"), (group, x, y, q.id, q.get("question")))
        self.assertGreaterEqual(n, 35)


if __name__ == "__main__":
    unittest.main()
