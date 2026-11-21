"""0.102.4 — every developer variant that reports visual baselines is told their format (the debug prompt was not,
so its bare-path declaration was read as undeclared and #1945 looped)."""

import os
import unittest

import _util  # noqa: F401

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "skills", "gld", "engine", "workflows", "dev",
                 "roles", "prompts")


class BaselinesFormat(unittest.TestCase):
    def test_variants_state_the_format(self):
        for v in ("implement", "debug", "refactor"):
            with open(os.path.join(D, "developer-%s.md" % v), encoding="utf-8") as fh:
                self.assertIn("A|M|D|C|P|P-withdrawn <path> — <reason>", fh.read(), v)


if __name__ == "__main__":
    unittest.main()
