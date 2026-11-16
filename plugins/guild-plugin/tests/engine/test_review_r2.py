"""Regression tests for the K0 adversarial review r2 (design/guild/23-engine/review-k0-r2.md)."""

import json
import os
import tempfile
import time
import unittest

import _util
from guildcore import decisions as dec
from guildcore import state
from guildcore.adapters.gh import FakeGh
from guildcore.records import audit, loopback, markers, needs_human, outputs, redact
from guildcore.records import decisions as D
from workflows.status import route, running

UNTERMINATED = "config/dev.pem starts with -----BEGIN RSA PRIVATE KEY----- (placeholder, no body)"


def pending(**kw):
    b = {"point": "T-ARB", "by": "judge:sonnet", "stage": "test", "at": "2026-11-16T09:00:00Z",
         "status": "pending-human", "question": "q", "options": "loop-back|stop", "kind": "escalation"}
    b.update(kw)
    return b


class B2PemKeepsStructure(unittest.TestCase):
    def test_decision_block_keeps_every_key(self):
        blk = D.render_block(1, pending(reason=UNTERMINATED))
        dc = D.DecisionComment(D.render_comment([blk]))
        b = dc.blocks[0]
        self.assertEqual(b.get("reason"), "config/dev.pem starts with [REDACTED]")
        self.assertEqual((b.get("status"), b.get("question"), b.options()), ("pending-human", "q", ["loop-back", "stop"]))
        self.assertEqual(len(dec.DecisionLog.load([_util.comment(dc.render())]).pending_human()), 1)

    def test_loopback_block_keeps_signature_and_decided(self):
        blk = loopback.render_block(1, "test", "t", "fix/b", UNTERMINATED, "T1", decided="human")
        rec = loopback.LoopbackRecord.parse(loopback.render_new_record(blk))
        b = rec.blocks[0]
        self.assertEqual((b.get("signature"), b.get("decided")), ("T1", "human"))

    def test_audit_block_keeps_findings(self):
        out = audit.render_block(1, "t", "0" * 40, [
            audit.render_finding("looped-back", "MAJOR", "spec", "a:1", UNTERMINATED),
            audit.render_finding("dismissed", "MINOR", "spec", "b:2", "x", "y")], ["role-axis: tech-lead DONE — z"])
        r = audit.AuditRecord.parse("<!-- guild:auditor:execute -->\n" + out + "\n<!-- /guild:auditor:execute -->")
        c = r.counts()
        self.assertEqual((c["looped_back"], c["dismissed"], len(r.blocks[0].role_axis)), (1, 1, 1))

    def test_multiline_pem_in_pause_prose(self):
        key = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(["QUJD" * 16] * 3) + "\nQUJDRA=="
        out = needs_human.render(needs_human.cause_line("defect", "key leaked"), prose="before\n" + key + "\nafter text here")
        self.assertNotIn("QUJD", out)
        self.assertIn("after text here", out)
        self.assertFalse(redact.has_secret(out))

    def test_structural_check_guards(self):
        # a redaction pattern that would eat a record line is refused by finish()
        import re
        old = list(redact.REDACT_EXTRA)
        redact.REDACT_EXTRA.append(re.compile(r"SWALLOW[\s\S]*"))
        try:
            with self.assertRaises(ValueError):
                markers.finish("reason: SWALLOW\nstatus: pending-human")
        finally:
            redact.REDACT_EXTRA[:] = old


class M14MarkerLineWhitespace(unittest.TestCase):
    def test_trailing_blank(self):
        body = "<!-- guild:manual-qa --> \n- [ ] old\n<!-- /guild:manual-qa -->"
        out = markers.splice(body, "manual-qa", "<!-- guild:manual-qa -->\nNEW\n<!-- /guild:manual-qa -->")
        self.assertEqual(out.count("<!-- guild:manual-qa -->"), 1)
        self.assertIn("NEW", out)
        self.assertNotIn("old", out)

    def test_open_and_close_on_one_line_refused(self):
        with self.assertRaises(ValueError):
            markers.splice("x\n<!-- guild:manual-qa --><!-- /guild:manual-qa -->", "manual-qa", "B")


class M15ConflictIsNotNone(unittest.TestCase):
    def test_status_and_route(self):
        body = D.render_comment([D.render_block(7, pending(stage="test"))])
        tl = [{"event": "unlabeled", "label": {"name": "guild:needs-human"}, "created_at": "2026-11-16T10:05:00Z",
               "actor": {"login": "alice"}}]
        cs = [_util.comment(body, 3), _util.comment("guild-answer: D7 stop", 50, "2026-11-16T10:00:00Z", "OWNER", "alice"),
              _util.comment("guild-answer: D7 loop-back", 51, "2026-11-16T10:04:00Z", "MEMBER", "bob")]
        blk = dec.DecisionLog.load(cs).pending_human()[0]
        st, a, _ = dec.accepted_answer(blk, cs, tl)
        self.assertEqual((st, a), ("conflict", None))
        self.assertEqual(dec.accepted_answer(blk, cs[:1], tl)[0], "none")
        gh = FakeGh({"repo": "o/r", "issues": {"1": {"title": "t", "labels": [{"name": "guild:test"}],
                                                     "comments": cs, "timeline": tl}}})
        r = route.route_snapshot(gh, state.snapshot(gh, 1))
        p = r.pending[0]
        self.assertEqual((p["answer_status"], p["conflict"], p["answer"]), ("conflict", True, None))
        self.assertIn("conflicting answers: #50 stop (alice), #51 loop-back (bob)", r.text())


class M16RedactBeforeCap(unittest.TestCase):
    def test_truncated_secret_never_leaks(self):
        v = "x" * 1958 + " ghp_" + "Z" * 40
        blk = D.render_block(1, {"by": "code", "reason": v})
        self.assertNotIn("ZZZZZZZZZZ", blk)
        self.assertFalse(redact.has_secret(blk))


class M17MachineFields(unittest.TestCase):
    def test_signature_stagnation_survives_neutralization(self):
        sig = "status shows guild:qa:output,T2"
        rec = loopback.LoopbackRecord.parse(loopback.render_new_record(
            loopback.render_block(1, "test", "t", "fix/b", "r", sig)))
        self.assertIn(markers.ZWSP, rec.blocks[0].get("signature"))     # B1 still holds
        self.assertEqual(rec.stagnant_with(sig, "test"), 1)

    def test_branch_and_options_refuse_marker_text(self):
        with self.assertRaises(ValueError):
            loopback.render_block(1, "test", "t", "<!-- guild:x -->", "r", "s")
        with self.assertRaises(ValueError):
            D.render_block(1, pending(options="guild:qa:output|stop"))

    def test_loopback_lines_signature(self):
        out = outputs.render_loopback_lines("r", "guild:qa:output,T2")
        so = outputs.StageOutput("test:output", {"id": 1, "body": out})
        self.assertEqual(loopback.signature_set(so.loopback_signature), {"guild:qa:output", "T2"})


class M18UnreadableLock(unittest.TestCase):
    def test_unreadable_and_stale(self):
        cd = tempfile.mkdtemp()
        d = os.path.join(cd, "guild", "engine")
        os.makedirs(d)
        p44 = os.path.join(d, "44.lock")
        with open(p44, "w") as fh:
            fh.write(json.dumps({"pid": os.getpid()}))
        os.chmod(p44, 0)
        p43 = os.path.join(d, "43.lock")
        open(p43, "w").close()
        old = time.time() - 3600
        os.utime(p43, (old, old))
        try:
            rows, _ = running.running([cd])
        finally:
            os.chmod(p44, 0o644)
        modes = dict((r["issue"], r["mode"]) for r in rows)
        if os.geteuid() != 0:
            self.assertEqual(modes.get(44), "unreadable-lock")
        self.assertEqual(modes.get(43), "stale-unknown")


class M19DetailsTrailingBlank(unittest.TestCase):
    def test_insert_after_human_edit(self):
        body = D.render_comment([D.render_block(1, {"by": "code"})]).replace("</details>", "</details> ")
        out = D.insert(body, D.render_block(2, {"by": "code"}))
        self.assertEqual([b.n for b in D.DecisionComment(out).blocks], [1, 2])


if __name__ == "__main__":
    unittest.main()
