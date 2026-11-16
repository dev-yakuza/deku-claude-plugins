"""Renderers: the engine-written shapes (§6.1 kept, §6.2 C1/C2/C4/C12/C13/C14 changes) are pinned
as golden files under tests/fixtures/engine/rendered, plus the write-side rules (INV4 splice,
INV5 redact, cumulative insertion, rollover)."""

import os
import unittest

import _util
from guildcore.records import answer, audit, decisions, followups, loopback, manual_qa
from guildcore.records import markers, needs_human, outputs, prbody, redact

RENDERED = os.path.join(_util.FX, "rendered")
SECRET = "ghp_" + "A" * 36


def golden(name):
    return _util.read(os.path.join(RENDERED, name))


class RenderedGolden(unittest.TestCase):
    def test_loopback_append_to_real_0987(self):
        body = _util.record("loopback/0.98.7/omc-161.md")
        blk = loopback.render_block(loopback.LoopbackRecord.parse(body).next_n(), "test",
                                    "2026-11-16T01:02:03Z", "feature/511-x",
                                    "  가가  가가\n가가 sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA ",
                                    ["TC-2", "TC-1"])
        out = loopback.append(body, blk)
        self.assertEqual(out, golden("loopback-append-0987.md"))
        # every earlier byte is kept (cumulative, H§B)
        self.assertTrue(out.startswith(body.split("<!-- /guild:loopback -->")[0]))
        r = loopback.LoopbackRecord.parse(out)
        self.assertEqual((len(r.active()), r.latest_active().get("signature")), (3, "TC-1,TC-2"))

    def test_loopback_new_human(self):
        out = loopback.render_new_record(loopback.render_block(
            1, "qa", "2026-11-16T01:02:03Z", "fix/#9-x", "가가", "Q-1", decided="human", override="human"))
        self.assertEqual(out + "\n", golden("loopback-new.md") + "\n")

    def test_needs_human_answer_hint_c13(self):
        out = needs_human.render(
            needs_human.cause_line("ambiguity", "가가 가가 — 가가 가가가"),
            prose="## analyze 일시정지\n가가가.",
            directive_line="사람 지시 확인: 없음 — 읽음: #42 · 트래커 #40 (마커 없는 댓글 0개, 전문)",
            answer=(7, ["loop-back", "stop"]))
        self.assertEqual(out, golden("needs-human-answer.md"))
        p = needs_human.Pause(out)
        self.assertTrue(p.cause_check_ok())
        self.assertIsNotNone(p.directive_line)        # the hint goes AFTER line 3

    def test_audit_c1_c2(self):
        out = audit.render_block(
            3, "2026-11-16T00:00:00Z", "0123456789abcdef0123456789abcdef01234567",
            [audit.render_finding("looped-back", "BLOCKER", "spec", "lib/a.dart:10", "가가 가가", fid="F1"),
             audit.render_finding("dismissed", "MINOR", "standards", "lib/b.dart:3", "가가", "가가 가가", fid="F2")],
            ["role-axis: tech-lead DONE — 가가"])
        self.assertEqual(out + "\n", golden("audit-block-c1c2.md"))
        self.assertEqual(audit.lint_block(out), [])
        rec = audit.AuditRecord.parse("<!-- guild:auditor:execute -->\n" + out + "\n<!-- /guild:auditor:execute -->")
        f = rec.blocks[0].findings
        self.assertEqual([(x.token, x.fid, x.reason) for x in f],
                         [("looped-back", "F1", None), ("dismissed", "F2", "가가 가가")])
        self.assertEqual(rec.blocks[0].head_key, "head")

    def test_audit_id_anywhere(self):
        f = audit.Finding("- fixed · MAJOR · spec · lib/a.dart:1 — x [id:F9] — re-stated")
        self.assertEqual((f.token, f.fid), ("fixed", "F9"))

    def test_decisions_comment_c4(self):
        blocks = [
            decisions.render_block(1, {"point": "engine-start", "stage": "analyze", "by": "code",
                                       "at": "2026-11-16T00:00:00Z", "started_at_stage": "analyze",
                                       "plugin": "0.102.0"}),
            decisions.render_block(2, [("point", "EX-ARB"), ("refs", "J-D1,J-G2"), ("stage", "execute"),
                                       ("by", "judge:opus"), ("at", "2026-11-16T09:12:44Z"),
                                       ("inputs", "3f9a1c2b7e0d"), ("choice", "dismiss:F3,accept:F4"),
                                       ("unsure", False), ("coerced", False),
                                       ("reason", "가가 가가 ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij12")]),
            decisions.render_block(3, {"point": "SJ-QA", "kind": "loopback", "stage": "qa",
                                       "by": "judge:sonnet", "at": "2026-11-16T10:00:00Z",
                                       "recommended": "loop-back", "recommended_by": "judge:sonnet",
                                       "status": "pending-human", "question": "QA 가 가가가 — loop back?",
                                       "options": ["loop-back", "stop"], "future_key": "kept"})]
        out = decisions.render_comment(blocks)
        self.assertEqual(out, golden("decisions-comment.md"))
        dc = decisions.DecisionComment(out)
        self.assertEqual(dc.render(), out)
        self.assertEqual([b.n for b in dc.blocks], [1, 2, 3])
        self.assertEqual(dc.blocks[2].options(), ["loop-back", "stop"])
        self.assertEqual(dc.blocks[2].get("future_key"), "kept")

    def test_decisions_rollover_comment(self):
        out = decisions.render_comment([decisions.render_block(4, {
            "resolves": "D3", "by": "human", "status": "answered", "choice": "loop-back",
            "answered_by": "owner", "answer_comment": 1024})], continued_from=987654)
        self.assertEqual(out, golden("decisions-rollover.md"))
        self.assertEqual(decisions.DecisionComment(out).continued_from, 987654)
        self.assertEqual(markers.first_line_marker(out), "decisions")   # CR-m2

    def test_followups(self):
        out = followups.render("후속 항목", [followups.parse_item("- unfiled — 가가 — docs/specs/42/skeleton.md §5"),
                                          followups.parse_item("- filed #57 — 가가가")])
        self.assertEqual(out, golden("followups-issue.md"))
        self.assertEqual(followups.render_pr_notice(42, ["가가 가가"]), golden("followups-pr-pending.md"))
        self.assertEqual(followups.render_pr_notice(42, []), golden("followups-pr-settled.md"))

    def test_manual_qa_splice_inv4(self):
        pr = _util.record("manual-qa/0.101.0/prose-prbody.md")
        new = manual_qa.render(["가가 — 가가 가가", "가가가 — 가가"])
        out = manual_qa.splice(pr, new)
        self.assertEqual(out, golden("prbody-manualqa-spliced.md"))
        o, c = "<!-- guild:manual-qa -->", "<!-- /guild:manual-qa -->"
        self.assertEqual(out[:out.index(o)], pr[:pr.index(o)])
        self.assertEqual(out[out.index(c):], pr[pr.index(c):])

    def test_unattended_log_migration_c14(self):
        pr = _util.record("manual-qa/0.101.0/prose-prbody.md")
        out = prbody.migrate_unattended(pr)
        self.assertEqual(out, golden("prbody-unattended-migrated.md"))
        self.assertEqual(prbody.migrate_unattended(out), out)                  # idempotent
        self.assertEqual(out.replace("<!-- guild:unattended-log -->\n", "")
                            .replace("<!-- /guild:unattended-log -->\n", ""), pr)
        self.assertIn(prbody.UNATTENDED_HEADING, out)                         # review reads it
        self.assertEqual(prbody.unattended_entries(out), ["가가: 가가 · 가가 가가 · 사람 확인 요"])

    def test_recheck_note_c12(self):
        out = outputs.render_recheck_note("2026-11-16T00:00:00Z", False, "1 failed: login_form_test submit")
        self.assertEqual(out, golden("note-recheck.md").rstrip("\n"))


class WriteRules(unittest.TestCase):
    def test_splice_append_remove(self):
        self.assertEqual(markers.splice("body", "x", "<!-- guild:x -->\na\n<!-- /guild:x -->"),
                         "body\n\n<!-- guild:x -->\na\n<!-- /guild:x -->")
        self.assertEqual(markers.splice("body\n", "x", "B"), "body\n\nB")
        s = "pre\n<!-- guild:x -->\na\n<!-- /guild:x -->\npost"
        self.assertEqual(markers.splice(s, "x", None), "pre\npost")
        with self.assertRaises(ValueError):
            markers.splice("<!-- guild:x -->\ntruncated", "x", "B")

    def test_redact_uses_gate_patterns(self):
        self.assertGreaterEqual(len(redact.patterns()), 12)
        self.assertEqual(redact.redact("token " + SECRET), "token [REDACTED]")
        for fn in (lambda: loopback.render_block(1, "test", "t", "b", SECRET, "s"),
                   lambda: needs_human.render("defect: " + SECRET),
                   lambda: manual_qa.render([SECRET]),
                   lambda: followups.render_pr_notice(1, [SECRET]),
                   lambda: decisions.render_block(1, {"by": "code", "reason": SECRET}),
                   lambda: audit.render_block(1, "t", "0" * 40, [audit.render_finding("fixed", "MINOR", "spec", "a:1", SECRET)])):
            self.assertNotIn(SECRET, fn())

    def test_needs_human_cause_validation(self):
        with self.assertRaises(ValueError):
            needs_human.cause_line("env", "x", "billing")
        with self.assertRaises(ValueError):
            needs_human.render("## heading first")
        self.assertEqual(needs_human.cause_line("env", "a  b", "service"), "env: service — a b")

    def test_loopback_from_must_be_known(self):
        with self.assertRaises(ValueError):
            loopback.render_block(1, "human", "t", "b", "r", "s")

    def test_decisions_insert_and_rollover(self):
        body = decisions.render_comment([decisions.render_block(1, {"by": "code", "point": "x"})])
        out = decisions.insert(body, decisions.render_block(2, {"by": "human", "point": "directive"}))
        dc = decisions.DecisionComment(out)
        self.assertEqual([b.n for b in dc.blocks], [1, 2])
        self.assertTrue(out.endswith("</details>\n<!-- /guild:decisions -->"))
        with self.assertRaises(ValueError):
            decisions.insert(body, decisions.render_block(2, {"by": "code", "reason": "가" * 61000}))
        with self.assertRaises(ValueError):
            decisions.render_block(3, {"by": "robot"})

    def test_answer_lines(self):
        c = _util.comment("thanks\nguild-answer: D7 loop-back\nguild-answer: D8 Stop")
        got = answer.parse(c)
        self.assertEqual([(a.k, a.token) for a in got], [(7, "loop-back")])   # tokens are lower-case
        self.assertEqual(answer.parse(_util.comment("<!-- guild:note -->\nguild-answer: D7 stop")), [])

    def test_audit_lint_flags_legacy_shapes(self):
        self.assertEqual(len(audit.lint_block("- MAJOR · spec · a — x\n- x disposition: fixed")), 2)


if __name__ == "__main__":
    unittest.main()
