"""Paid replay finding — `health.metrics` read the engine's KICKOFF choice `goal=clear,constraint=…,success=…` as
never clear, so the LENIENT `kickoff_clear` tripwire and its centre were always 0.
"""

import unittest

import _util  # noqa: F401

from workflows.dev import health as H


def _kick(choice):
    return {"point": "KICKOFF", "choice": choice, "by": "judge:opus"}


class KickoffClear(unittest.TestCase):
    def _rates(self, *choices):
        m = H.metrics({i: [_kick(c)] for i, c in enumerate(choices)})
        return m["kickoff_clear"], m["kickoff_unclear"]

    def test_engine_format_all_clear_counts_clear(self):
        self.assertEqual(self._rates("goal=clear,constraint=clear,success=clear"), (1.0, 0.0))

    def test_engine_format_partial_is_neither(self):
        self.assertEqual(self._rates("goal=clear,constraint=partial,success=clear"), (0.0, 0.0))

    def test_engine_format_unclear_counts_unclear(self):
        self.assertEqual(self._rates("goal=unclear,constraint=clear,success=clear"), (0.0, 1.0))

    def test_mixed_rates(self):
        clear, unclear = self._rates("goal=clear,constraint=clear,success=clear",
                                     "goal=clear,constraint=partial,success=clear",
                                     "goal=unclear,constraint=partial,success=clear",
                                     "goal=clear,constraint=clear,success=clear")
        self.assertEqual((clear, unclear), (0.5, 0.25))

    def test_older_bare_words_still_read(self):
        self.assertEqual(self._rates("clear"), (1.0, 0.0))
        self.assertEqual(self._rates("not_ready"), (0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
