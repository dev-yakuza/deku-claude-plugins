"""Regression tests for the K0 adversarial review r3 (design/guild/23-engine/review-k0-r3.md):
private keys are redacted by WHOLE VALUE, never by matching key bodies."""

import unittest

import _util
from guildcore.records import audit, loopback, manual_qa, markers, needs_human, prbody, redact
from guildcore.records import decisions as D

B64 = "MIIEowIBAAKCAQEAuXk1" + "A" * 44
SHAPES = {
    "encrypted-legacy": ("-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,0A1B\n\n"
                         + B64 + "\n" + B64 + "\n-----END RSA PRIVATE KEY-----"),
    "indented": "    -----BEGIN PRIVATE KEY-----\n    " + B64 + "\n    " + B64 + "\n    -----END PRIVATE KEY-----",
    "quoted": "> -----BEGIN OPENSSH PRIVATE KEY-----\n> " + B64 + "\n> -----END OPENSSH PRIVATE KEY-----",
    "trailing-blanks": "-----BEGIN EC PRIVATE KEY-----  \n" + B64 + "   \n" + B64 + " \n-----END EC PRIVATE KEY-----",
    "blank-line-inside": "-----BEGIN PRIVATE KEY-----\n" + B64 + "\n\n" + B64 + "\n-----END PRIVATE KEY-----",
    "encrypted-pkcs8": "-----BEGIN ENCRYPTED PRIVATE KEY-----\n" + B64 + "\n-----END ENCRYPTED PRIVATE KEY-----",
    "putty": "PuTTY-User-Key-File-3: ssh-rsa\nEncryption: none\nPrivate-Lines: 1\n" + B64,
    "pgp": "-----BEGIN PGP PRIVATE KEY BLOCK-----\n\n" + B64 + "\n-----END PGP PRIVATE KEY BLOCK-----",  # K0-m22
}


class M7WholeValue(unittest.TestCase):
    def test_redact_each_shape(self):
        for name, key in SHAPES.items():
            text = "pasted from the log:\n" + key + "\nthanks"
            with self.subTest(shape=name):
                self.assertEqual(redact.redact(text), "[REDACTED]")
                self.assertTrue(redact.has_secret(text))

    def test_pause_prose_never_posts_key_body(self):
        for name, key in SHAPES.items():
            out = needs_human.render(needs_human.cause_line("defect", "a key was pasted"),
                                     prose="before\n" + key + "\nafter", answer=(3, ["stop"]))
            with self.subTest(shape=name):
                self.assertNotIn("AAAAAAAAAA", out)
                self.assertNotIn("uXk1", out)
                p = needs_human.Pause(out)
                self.assertTrue(p.cause_check_ok())
                self.assertIn(needs_human.answer_hint(3, ["stop"]), out)   # structure kept

    def test_block_fields_stay_separate_values(self):
        key = SHAPES["indented"]
        blk = D.render_block(1, {"point": "x", "by": "code", "reason": key, "question": "q?", "status": "answered"})
        b = D.DecisionComment(D.render_comment([blk])).blocks[0]
        self.assertEqual([k for k, _ in b.fields], ["id", "point", "by", "reason", "status", "question"])
        self.assertEqual((b.get("reason"), b.get("question")), ("[REDACTED]", "q?"))
        lb = loopback.LoopbackRecord.parse(loopback.render_new_record(
            loopback.render_block(1, "test", "t", "fix/b", key, "T1", decided="human")))
        self.assertEqual((lb.blocks[0].get("reason"), lb.blocks[0].get("signature")), ("[REDACTED]", "T1"))
        out = audit.render_block(1, "t", "0" * 40, [audit.render_finding("fixed", "MINOR", "spec", "a:1", key, "r")],
                                 ["role-axis: tech-lead DONE — " + key])
        self.assertIn("- fixed · MINOR · spec · a:1 — [REDACTED] — r", out)
        self.assertIn("role-axis: [REDACTED]", out)
        self.assertEqual(manual_qa.render([key, "ok item"]).count("- [ ] "), 2)
        self.assertFalse(any(redact.has_secret(x) for x in (blk, out)))


class M21ShortProseKept(unittest.TestCase):
    def test_no_key_no_erasure(self):
        text = "the file had a key header only\nPlease\nconfirm\nRetry\nthen run /gld resume"
        self.assertEqual(redact.redact(text), text)
        out = needs_human.render(needs_human.cause_line("ambiguity", "x"), prose=text)
        for w in ("Please", "confirm", "Retry", "then run /gld resume"):
            self.assertIn(w, out)


class M20OneAnchorRule(unittest.TestCase):
    BODY = ("intro\n  <!-- guild:manual-qa --> is where the checklist goes\n"
            "> <!-- guild:manual-qa --> quoted too\n"
            "<!-- guild:manual-qa -->\n- [ ] old\n<!-- /guild:manual-qa -->\nend")

    def test_indented_and_quoted_mentions_ignored_by_both(self):
        c = manual_qa.from_pr_body(self.BODY)
        self.assertEqual([t for _, t in c.items], ["old"])
        out = manual_qa.splice(self.BODY, manual_qa.render(["new"]))
        self.assertIn("  <!-- guild:manual-qa --> is where the checklist goes", out)
        self.assertIn("- [ ] new", out)
        self.assertNotIn("- [ ] old", out)
        self.assertTrue(out.endswith("\nend"))
        self.assertEqual(prbody.migrate_unattended(self.BODY), self.BODY)   # no heading → unchanged

    def test_column0_extra_text_refused_by_both(self):
        body = "<!-- guild:manual-qa --> trailing words\n- [ ] x\n<!-- /guild:manual-qa -->"
        with self.assertRaises(ValueError):
            manual_qa.splice(body, manual_qa.render(["n"]))
        with self.assertRaises(ValueError):
            manual_qa.from_pr_body(body)

    def test_only_mentions_appends_and_reads_none(self):
        body = "  <!-- guild:manual-qa --> mention"
        self.assertIsNone(manual_qa.from_pr_body(body))
        self.assertTrue(manual_qa.splice(body, manual_qa.render(["n"])).startswith(body + "\n\n<!-- guild:manual-qa -->"))


if __name__ == "__main__":
    unittest.main()
