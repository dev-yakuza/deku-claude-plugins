#!/usr/bin/env python3
"""Write skills/std/scripts/MANIFEST.sha256 (run after changing Studio's scripts; structure_test.sh checks it)."""
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "skills", "std", "scripts"))
sys.path.insert(0, SCRIPTS)
from stdo import SCRIPTS_VERSION, manifest  # noqa: E402

text = manifest.render(SCRIPTS, SCRIPTS_VERSION)
p = os.path.join(SCRIPTS, manifest.NAME)
if "--check" in sys.argv:
    cur = open(p).read() if os.path.exists(p) else ""
    sys.exit(0 if cur == text else 1)
with open(p, "w") as f:
    f.write(text)
print("wrote %s (%d files)" % (p, text.count("\n") - 1))
