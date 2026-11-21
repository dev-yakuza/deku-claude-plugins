"""0.102.1 — stage_inputs: a bare string is the input's text (execute/test/qa pass strings), {"path": …} copies."""

import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir

from guildcore.roles.runner import stage_inputs


class StageInputs(unittest.TestCase):
    def test_text_forms(self):
        d = tmpdir(self)
        if True:
            out = stage_inputs(d, {"a.md": "plain text", "b.md": {"text": "wrapped"}, "c.txt": "", "d.md": "README.md"})
            self.assertEqual(open(out["a.md"]).read(), "plain text")
            self.assertEqual(open(out["b.md"]).read(), "wrapped")
            self.assertEqual(open(out["c.txt"]).read(), "")
            self.assertEqual(open(out["d.md"]).read(), "README.md")   # a string that names a file is still text

    def test_explicit_path_copies(self):
        d = tmpdir(self)
        if True:
            src = os.path.join(d, "src.txt")
            with open(src, "w") as fh:
                fh.write("from file")
            run = os.path.join(d, "run")
            out = stage_inputs(run, {"x.txt": {"path": src}})
            self.assertEqual(open(out["x.txt"]).read(), "from file")


if __name__ == "__main__":
    unittest.main()
