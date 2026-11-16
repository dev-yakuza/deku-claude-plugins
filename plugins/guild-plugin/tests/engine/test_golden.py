"""Golden-fixture round-trip: every record under tests/fixtures/engine/records parses and renders
back byte for byte (§6.1/§6.3), and the parse yields the facts the consumers rely on.

Versions covered: real sprint-log records 0.82.4–0.99.2 (sanitized, MANIFEST.json) and
0.101.0 shapes written from the live prose (the record prose is unchanged 0.99.2 → 0.101.0)."""

import os
import unittest

import _util
from guildcore.records import audit, decisions, followups, loopback, manual_qa, markers
from guildcore.records import needs_human, outputs


def parse_render(kind, body):
    if kind == "loopback":
        return loopback.LoopbackRecord.parse(body).render()
    if kind == "auditor-execute":
        return audit.AuditRecord.parse(body).render()
    if kind == "needs-human":
        return needs_human.Pause(body).render()
    if kind == "followups":
        if body.startswith("<!-- guild:followups:pr:"):
            return followups.PrNotice(body).render()
        return followups.FollowupsRecord(body).render()
    if kind == "manual-qa":
        blk = manual_qa.from_pr_body(body)
        return manual_qa.splice(body, blk.render())
    if kind == "decisions":
        return decisions.DecisionComment(body).render()
    return outputs.StageOutput(kind, {"id": 1, "body": body}).render()


class RoundTrip(unittest.TestCase):
    def test_every_golden_file(self):
        n = 0
        for kind in sorted(os.listdir(_util.RECORDS)):
            if not os.path.isdir(os.path.join(_util.RECORDS, kind)):
                continue
            for ver, name, path in _util.records_of(kind):
                body = _util.read(path)
                with self.subTest(kind=kind, ver=ver, name=name):
                    self.assertTrue(body.startswith("<!-- guild:") or kind == "manual-qa")
                    self.assertEqual(parse_render(kind, body), body)
                n += 1
        self.assertGreaterEqual(n, 34)

    def test_crlf_survives(self):
        body = _util.record("loopback/0.98.7/omc-161.md").replace("\n", "\r\n")
        rec = loopback.LoopbackRecord.parse(body)
        self.assertEqual(rec.render(), body)
        self.assertEqual(rec.summary()["active"], 2)


class LoopbackFacts(unittest.TestCase):
    def rec(self, rel):
        return loopback.LoopbackRecord.parse(_util.record(rel))

    def test_098_single_consumed_spaced_signature(self):
        r = self.rec("loopback/0.98.5/omc-601.md")
        self.assertEqual(r.summary()["active"], 1)
        self.assertFalse(r.not_yet_handled())
        self.assertEqual(loopback.signature_set(r.latest_active().get("signature")),
                         {"D-4", "D-6", "E-1", "E-2", "E-3"})

    def test_098_header_and_blank_lines(self):
        r = self.rec("loopback/0.98.7/omc-161.md")
        s = r.summary()
        self.assertEqual((s["active"], s["latest_from"], s["not_yet_handled"]), (2, "qa", True))
        self.assertEqual(r.next_n(), 3)
        self.assertIn("## 루프백 기록", r.doc.head)

    def test_0101_reset_and_human(self):
        r = self.rec("loopback/0.101.0/prose-reset-human.md")
        self.assertEqual(len(r.numbered()), 3)
        self.assertEqual(len(r.active()), 1)            # the reset retires blocks 1-2
        lat = r.latest_active()
        self.assertEqual((lat.get("from"), lat.get("decided"), lat.get("override")),
                         ("leader", "human", "human"))
        self.assertEqual(r.next_n(), 4)                  # ids count every numbered heading
        self.assertEqual(r.stagnant_with("AC-3", "leader"), 3)
        self.assertIsNone(r.stagnant_with("AC-3", "test"))
        self.assertIsNone(r.stagnant_with("", "leader"))  # empty → judgment, not code
        self.assertFalse(r.cap_reached())


class PauseFacts(unittest.TestCase):
    CASES = {
        "needs-human/0.98.7/jli-114.md": ("env", "other", True, True),
        "needs-human/0.98.5/omc-597.md": ("env", "ci-blocked", False, True),
        "needs-human/0.98.6/wa-1876.md": ("ambiguity", None, False, True),
        "needs-human/0.98.7/omc-161.md": ("defect", None, True, True),
        "needs-human/0.95.0/omc-490.md": (None, None, False, False),
        "needs-human/0.98.6/wa-1833.md": (None, None, False, False),
        "needs-human/0.98.6/omc-619.md": ("env", "other", False, True),
        "needs-human/0.101.0/prose-env-directive.md": ("env", "ci-blocked", True, True),
        "needs-human/0.101.0/prose-applicable-directive.md": ("env", "base-red", True, True),
    }

    def test_cause_lines(self):
        for rel, (kind, key, directive, ok) in self.CASES.items():
            p = needs_human.Pause(_util.record(rel))
            with self.subTest(rel=rel):
                self.assertEqual(p.cause_kind, kind)
                self.assertEqual(p.env_key, key)
                self.assertEqual(p.directive_line is not None, directive)
                self.assertEqual(p.cause_check_ok(), ok)

    def test_heading_fallback(self):
        p = needs_human.Pause(_util.record("needs-human/0.95.0/omc-490.md"))
        self.assertTrue(p.daily_cause().startswith("## ⏸ ambiguity:"))


class AuditFacts(unittest.TestCase):
    def rec(self, rel):
        return audit.AuditRecord.parse(_util.record(rel))

    def test_0992_head_key(self):
        r = self.rec("auditor-execute/0.99.2/wa-1909.md")
        self.assertEqual(len(r.blocks), 1)
        b = r.blocks[0]
        self.assertEqual((b.head_key, b.head), ("head", "1d0fa9b164e0e810bd5eab855c8ff5be0fdb8cc4"))
        self.assertTrue(b.findings_none)

    def test_0991_upper_head_and_tokens(self):
        r = self.rec("auditor-execute/0.99.1/wa-1823.md")
        self.assertEqual([b.head_key for b in r.blocks], ["HEAD", "HEAD"])
        c = r.counts()
        self.assertEqual((c["records"], c["looped_back"], c["fixed"], c["recorded"]), (2, 1, 1, 1))
        self.assertEqual(len(r.blocks[0].role_axis), 1)

    def test_0987(self):
        c = self.rec("auditor-execute/0.98.7/omc-507.md").counts()
        self.assertEqual((c["records"], c["looped_back"], c["clean"]), (2, 2, 1))
        c = self.rec("auditor-execute/0.98.7/omc-161.md").counts()
        self.assertEqual((c["records"], c["looped_back"]), (1, 2))

    def test_0101_catalog_grammar_bare_sha(self):
        r = self.rec("auditor-execute/0.101.0/prose-catalog-grammar.md")
        self.assertEqual([b.head_key for b in r.blocks], [None, None, None])
        self.assertTrue(all(b.head for b in r.blocks))
        c = r.counts()
        self.assertEqual((c["no_scan"], c["looped_back"], c["dismissed"], c["clean"]), (1, 1, 1, 1))
        self.assertEqual(r.blocks[1].local_pass, "ld-42-1")
        f = r.blocks[1].findings[1]
        self.assertEqual((f.severity, f.axis, f.location, f.reason), ("MINOR", "standards", "lib/b.dart:3", "가가 가가"))

    def test_violation_resolved_by_position(self):
        v = audit.violations([_util.comment(_util.record("auditor-violation/0.82.4/omc.md"))])
        self.assertEqual(len(v), 1)
        self.assertTrue(v[0].resolved)
        quoted = "<!-- guild:auditor-violation -->\nadd `<!-- guild:auditor-violation:resolved -->` below\n<!-- /guild:auditor-violation -->"
        self.assertFalse(audit.violations([_util.comment(quoted)])[0].resolved)


class FollowupFacts(unittest.TestCase):
    def test_issue_records(self):
        r = followups.FollowupsRecord(_util.record("followups/0.99.2/wa-issue.md"))
        self.assertEqual([i.status for i in r.items], ["unfiled", "unfiled"])
        r = followups.FollowupsRecord(_util.record("followups/0.99.1/wa-issue.md"))
        self.assertEqual(len(r.by_status("unfiled")), 4)
        r = followups.FollowupsRecord(_util.record("followups/0.101.0/prose-issue.md"))
        self.assertEqual([(i.status, i.filed) for i in r.items],
                         [("unfiled", None), ("declined", None), ("filed", 57)])
        self.assertEqual(r.items[0].render(), r.items[0].line)

    def test_pr_notices(self):
        n = followups.PrNotice(_util.record("followups/0.99.2/wa-1909-pr.md"))
        self.assertEqual((n.issue, n.settled, len(n.titles)), (1909, False, 1))
        n = followups.PrNotice(_util.record("followups/0.101.0/prose-pr-settled.md"))
        self.assertEqual((n.issue, n.settled), (42, True))


class OutputFacts(unittest.TestCase):
    def test_loopback_lines(self):
        so = outputs.StageOutput("test:output", {"id": 1, "body": _util.record("test-output/0.98.7/jli-98-loopback-lines.md")})
        self.assertEqual(so.loopback_signature, "TC-60,TC-72,TC-74")
        so = outputs.StageOutput("test:output", {"id": 1, "body": _util.record("test-output/0.101.0/prose-attended-fail.md")})
        self.assertEqual(so.loopback_signature, "AC-2,login_form_test.dart:submit")

    def test_manual_qa_items(self):
        c = manual_qa.from_pr_body(_util.record("manual-qa/0.98.0/omc.md"))
        self.assertEqual(len(c.items), 7)
        c = manual_qa.from_pr_body(_util.record("manual-qa/0.101.0/prose-prbody.md"))
        self.assertEqual([d for d, _ in c.items], [False, True])

    def test_first_line_markers(self):
        self.assertEqual(markers.first_line_marker(_util.record("note/0.99.2/wa-1878.md")), "note")
        self.assertEqual(markers.first_line_marker(_util.record("children-output/0.89.11/omc.md")), "children:output")


if __name__ == "__main__":
    unittest.main()
