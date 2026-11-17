"""K3 — the execute procedure replay's comparison harness on synthetic legacy blocks (the real-log run
is `replay/execute_replay.py`, evidence in design/guild/measure/k3-replay/)."""

import unittest

import _util  # noqa: F401

from guildcore.records import audit as AU
from workflows.dev.replay import execute_replay as E

INV = "2026-11-03T21:53:36Z"
LEGACY = "\n".join([
    "<!-- guild:auditor:execute -->", "## 외부 감사자 기록 (execute) — #9", "",
    "### audit-record 1", "invocation: %s" % INV, "HEAD: %s" % ("a" * 40),
    "- MAJOR · spec · `lib/a.dart:3` — the wrong value — looped-back",
    "role-axis: tech-lead BLOCKED — step 3 missing",
    "참고: 첫 스캔은 산문이었다",
    "### audit-record 2", "invocation: %s" % INV, "head: %s" % ("b" * 40),
    "- fixed · MAJOR · spec · lib/a.dart:3 — the wrong value",
    "role-axis: tech-lead DONE — fine",
    "<!-- /guild:auditor:execute -->"])


class Harness(unittest.TestCase):
    def setUp(self):
        self.rec = AU.AuditRecord.parse(LEGACY)

    def test_loose_reading_of_a_token_last_line(self):
        f = E.loose_findings(self.rec.blocks[0])
        self.assertEqual([(x.token, x.severity, x.strict) for x in f], [("looped-back", "MAJOR", False)])
        self.assertEqual(E.loose_roles(self.rec.blocks[0]), ["role-axis: tech-lead BLOCKED — step 3 missing"])
        self.assertEqual(E.loose_roles(self.rec.blocks[1]), [])           # a DONE role line is not a trigger

    def test_by_construction_classifies_prose_and_omissions(self):
        b = self.rec.blocks[0]
        leg = E.skeleton([b.block.heading] + b.block.lines)
        eng = E.skeleton(E.construct(b))
        cls, bad = E.classify_construct(leg, eng)
        self.assertEqual(bad, 0)
        # the token-last legacy line is not a retro-countable finding line: the engine writes the canonical one
        self.assertEqual(cls["intentional:§7 B-F-18 (legacy omitted a required machine line: F)"], 1)
        self.assertEqual(cls["intentional:§7 B-F-18 (legacy free-prose line)"], 2)

    def test_derived_teacher_forced(self):
        a1 = E.derive(self.rec, 0, self.rec.blocks[0])
        self.assertEqual(a1.kind, "retry")
        self.assertEqual([(x.token, x.severity) for x in a1.lines], [("looped-back", "MAJOR")])
        a2 = E.derive(self.rec, 1, self.rec.blocks[1])
        self.assertEqual(a2.kind, "advance")

    def test_token_mismatch_classes(self):
        self.assertEqual(E.token_mismatch([("looped-back", "MINOR")], [("recorded", "MINOR")], 0),
                         ["legacy looped back on a MINOR (spine: MINOR never blocks)"])
        self.assertEqual(E.token_mismatch([("fixed", "MAJOR")], [], 1),
                         ["legacy prior pending line not machine-readable (retro cannot count it either)"])


if __name__ == "__main__":
    unittest.main()
