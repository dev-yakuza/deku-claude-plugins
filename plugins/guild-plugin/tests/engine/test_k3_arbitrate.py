"""K3 — execute Step 4 as code (exec_audit): D-4.1–D-4.14, D-5.5, EX-ARB coercions, IDENT, stagnation."""

import unittest

import _util  # noqa: F401

from guildcore.records import audit as AU
from workflows.dev import exec_audit as XA

INV1, INV2 = "2026-11-16T00:00:00Z", "2026-11-17T00:00:00Z"
H1, H2 = "a" * 40, "b" * 40


def rec(*blocks):
    body = "\n".join(["<!-- guild:auditor:execute -->"] + list(blocks) + ["<!-- /guild:auditor:execute -->"])
    return AU.AuditRecord.parse(body)


def cur(sev="BLOCKER", f="lib/a.dart", line=3, text="returns the wrong value"):
    return XA.Cur(sev, "spec", f, line, text, "why")


def arb(record, scan, scan_ran=True, **kw):
    kw.setdefault("unattended", True)
    kw.setdefault("attempt", 1)
    kw.setdefault("attempts_in_invocation", 0)
    return XA.arbitrate(record, scan, scan_ran, **kw)


def toks(a):
    return [(l.token, l.severity, l.fid) for l in a.lines]


class Severity(unittest.TestCase):
    def test_clean_scan_advances_with_findings_none(self):
        a = arb(None, [])
        self.assertEqual(a.kind, "advance")
        blk = a.block(1, INV1, H1)
        self.assertIn("findings: none", blk)
        self.assertEqual(AU.lint_block(blk), [])

    def test_blocker_loops_back_with_an_engine_id(self):
        a = arb(None, [cur()])
        self.assertEqual((a.kind, toks(a)), ("retry", [("looped-back", "BLOCKER", "F1")]))
        self.assertEqual(a.signature, ["F1"])
        self.assertTrue(a.block(1, INV1, H1).split("\n")[-1].endswith("[id:F1]"))

    def test_minor_never_blocks(self):
        a = arb(None, [cur("MINOR")])
        self.assertEqual((a.kind, toks(a)), ("advance", [("recorded", "MINOR", "F1")]))

    def test_major_blocks_once_then_budget_spent_records(self):
        a = arb(None, [cur("MAJOR")])
        self.assertEqual(a.kind, "retry")
        self.assertTrue(a.major_only)
        b = arb(None, [cur("MAJOR")], major_spent=True)
        self.assertEqual((b.kind, toks(b)), ("advance", [("recorded", "MAJOR", "F1")]))

    def test_cap_outranks_major_budget(self):
        a = arb(None, [cur("MAJOR")], attempts_in_invocation=2)
        self.assertEqual((a.kind, toks(a)[0][0]), ("advance", "recorded"))

    def test_blocker_at_cap_exits_recorded(self):
        a = arb(None, [cur()], attempts_in_invocation=2)
        self.assertEqual((a.kind, toks(a)), ("cap", [("recorded", "BLOCKER", "F1")]))

    def test_role_axis_only_loopback_keeps_findings_none(self):
        a = arb(None, [], role_triggers=[("tech-lead", "BLOCKED", "skeleton step 3 missing")])
        blk = a.block(1, INV1, H1)
        self.assertEqual(a.kind, "retry")
        self.assertIn("findings: none", blk)
        self.assertIn("role-axis: tech-lead BLOCKED — skeleton step 3 missing", blk)

    def test_scan_none_block_on_evidence_failure(self):
        a = arb(None, [], scan_ran=False, evidence_reason="suite red — x [E]")
        blk = a.block(1, INV1, H1, scan_none=True)
        self.assertIn("scan: none", blk)
        self.assertNotIn("findings: none", blk)
        self.assertIn("role-axis: verify not-green — suite red — x [E]", blk)

    def test_loopback_number_line(self):
        self.assertIn("loopback: 2", arb(None, []).block(1, INV1, H1, loopback=2))


class Disputes(unittest.TestCase):
    def test_unattended_blocker_dismiss_becomes_dispute_recorded(self):
        a = arb(None, [cur()], ex_arb={"F1": {"verdict": "dismiss", "reason": "covered by guard"}})
        self.assertEqual(a.kind, "dispute")
        self.assertEqual(toks(a), [("recorded", "BLOCKER", "F1")])
        self.assertNotIn("dismissed", a.block(1, INV1, H1))

    def test_attended_blocker_dismiss_asks(self):
        a = arb(None, [cur()], unattended=False, ex_arb={"F1": {"verdict": "dismiss", "reason": "r"}})
        self.assertEqual(a.kind, "ask-dismiss")

    def test_major_dismissed_with_reason_both_modes(self):
        for un in (True, False):
            a = arb(None, [cur("MAJOR")], unattended=un, ex_arb={"F1": {"verdict": "dismiss", "reason": "by design"}})
            self.assertEqual(a.kind, "advance")
            self.assertEqual(a.lines[0].render(), "- dismissed · MAJOR · spec · lib/a.dart:3 — returns the wrong value — by design [id:F1]")

    def test_human_dismiss_answer_allows_a_blocker_dismissal(self):
        a = arb(None, [cur()], human={"F1": "dismiss"})
        self.assertEqual((a.kind, toks(a)[0][0]), ("advance", "dismissed"))

    def test_coerce_quotes(self):
        files = {"lib/a.dart": "line1\nline2\nreturn 1; // ok\nline4\n"}
        rd = files.get
        good = {"findings": [{"id": "F1", "verdict": "dismiss", "reason": "r",
                              "evidence": [{"path": "lib/a.dart", "line": 3, "quote": "return 1;"}]}]}
        bad = {"findings": [{"id": "F1", "verdict": "dismiss", "reason": "r",
                             "evidence": [{"path": "lib/a.dart", "line": 3, "quote": "return 2;"}]}]}
        uns = {"findings": [{"id": "F1", "verdict": "unsure"}]}
        self.assertEqual(XA.coerce_ex_arb(good, rd)[0]["F1"]["verdict"], "dismiss")
        self.assertEqual(XA.coerce_ex_arb(bad, rd), ({"F1": {"verdict": "accept", "reason": "r"}}, True))
        self.assertEqual(XA.coerce_ex_arb(uns, rd)[0]["F1"]["verdict"], "accept")
        far = {"findings": [{"id": "F1", "verdict": "dismiss", "evidence": [{"path": "lib/a.dart", "line": 30,
                                                                              "quote": "return 1;"}]}]}
        self.assertEqual(XA.coerce_ex_arb(far, rd)[0]["F1"]["verdict"], "accept")


B1 = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "head: %s" % H1,
                "- looped-back · BLOCKER · spec · lib/a.dart:3 — returns the wrong value [id:F1]"])


class Restatement(unittest.TestCase):
    def test_clean_rescan_settles_fixed(self):
        a = arb(rec(B1), [])
        self.assertEqual((a.kind, toks(a)), ("advance", [("fixed", "BLOCKER", "F1")]))
        self.assertEqual(a.addressed, ["F1"])
        self.assertNotIn("findings: none", a.block(2, INV1, H2))

    def test_scan_none_never_fixed(self):
        a = arb(rec(B1), [], scan_ran=False, evidence_reason="suite red")
        self.assertEqual(toks(a), [("looped-back", "BLOCKER", "F1")])
        b = arb(rec(B1), [], scan_ran=False, evidence_reason="suite red", attempts_in_invocation=2)
        self.assertEqual(toks(b), [("recorded", "BLOCKER", "F1")])

    def test_same_finding_keeps_its_id_and_stagnates(self):
        a = arb(rec(B1), [cur(line=5, text="returns the wrong value!")])
        self.assertEqual(toks(a), [("recorded", "BLOCKER", "F1")])
        self.assertEqual(a.kind, "stagnant")

    def test_new_finding_beside_old_is_progress(self):
        a = arb(rec(B1), [cur(), cur(f="lib/b.dart", text="null deref")], attempts_in_invocation=1)
        self.assertEqual(a.kind, "retry")
        self.assertEqual(sorted(a.signature), ["F1", "F2"])

    def test_ident_judge_can_only_demote(self):
        a = arb(rec(B1), [cur()], ident=lambda pr, c: "different")
        self.assertEqual([l.fid for l in a.lines], ["F1", "F2"])
        self.assertEqual(a.lines[0].token, "fixed")

    def test_legacy_line_without_id_gets_one(self):
        legacy = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "HEAD: %s" % H1,
                            "- looped-back · MAJOR · spec · lib/a.dart:3 — returns the wrong value"])
        a = arb(rec(legacy), [])
        self.assertEqual(toks(a), [("fixed", "MAJOR", "F1")])


class CarryForward(unittest.TestCase):
    D = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "head: %s" % H1,
                   "- dismissed · MAJOR · spec · lib/a.dart:3 — returns the wrong value — by design [id:F1]"])
    R = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "head: %s" % H1,
                   "- recorded · BLOCKER · spec · lib/a.dart:3 — returns the wrong value [id:F1]"])

    def test_dismissed_carried_when_file_unchanged(self):
        a = arb(rec(self.D), [cur("MAJOR")], unchanged=lambda pr, c: True)
        self.assertEqual((a.kind, a.lines[0].render()), ("advance",
                         "- dismissed · MAJOR · spec · lib/a.dart:3 — returns the wrong value — by design [id:F1]"))

    def test_changed_file_is_new(self):
        a = arb(rec(self.D), [cur("MAJOR")], unchanged=lambda pr, c: False)
        self.assertEqual(a.kind, "retry")

    def test_untracked_path_is_new(self):
        a = arb(rec(self.D), [cur("MAJOR")], unchanged=lambda pr, c: True, untracked={"lib/a.dart"})
        self.assertEqual(a.kind, "retry")

    def test_recorded_blocker_reblocks(self):
        a = arb(rec(self.R), [cur()], unchanged=lambda pr, c: True)
        self.assertEqual(a.kind, "retry")


class Stagnation(unittest.TestCase):
    def test_role_axis_samecause(self):
        b = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "head: %s" % H1, "findings: none",
                       "role-axis: tech-lead BLOCKED — missing step 3"])
        a = arb(rec(b), [], role_triggers=[("tech-lead", "BLOCKED", "step 3 still missing")],
                samecause=lambda x, y: "same", attempts_in_invocation=1)
        self.assertEqual(a.kind, "stagnant")
        c = arb(rec(b), [], role_triggers=[("tech-lead", "BLOCKED", "step 3 still missing")],
                samecause=lambda x, y: "different", attempts_in_invocation=1)
        self.assertEqual(c.kind, "retry")

    def test_timeouts_match_by_code(self):
        b = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "head: %s" % H1, "scan: none",
                       "role-axis: verify not-green — suite timed out at 3600000 ms — last running: x_test.dart"])
        a = arb(rec(b), [], scan_ran=False, evidence_reason="suite timed out at 3600000 ms — last running: y_test.dart",
                attempts_in_invocation=1)
        self.assertEqual(a.kind, "stagnant")

    def test_local_pass_blocks_do_not_vote_or_count(self):
        b = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "head: %s" % H1, "local-pass: j1",
                       "- looped-back · BLOCKER · spec · lib/a.dart:3 — returns the wrong value [id:F1]"])
        r = rec(b)
        self.assertEqual(XA.attempts_in_invocation(r, INV1), 0)
        self.assertIsNone(XA.stagnation(r, ["F1"], [], None))

    def test_containment_not_intersection(self):
        b = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "head: %s" % H1,
                       "- looped-back · BLOCKER · spec · lib/a.dart:3 — x [id:F1]",
                       "- looped-back · BLOCKER · spec · lib/b.dart:3 — y [id:F2]"])
        self.assertTrue(XA.stagnation(rec(b), ["F1"], [], None))
        self.assertIsNone(XA.stagnation(rec(b), ["F1", "F3"], [], None))


class PrSection(unittest.TestCase):
    def test_omitted_without_any_finding(self):
        clean = "\n".join(["### audit-record 1", "invocation: %s" % INV1, "head: %s" % H1, "findings: none"])
        self.assertIsNone(XA.pr_section(rec(clean)))
        self.assertIsNone(XA.pr_section(None))

    def test_fixed_aggregate_and_individual_rest(self):
        b2 = "\n".join(["### audit-record 2", "invocation: %s" % INV1, "head: %s" % H2,
                        "- fixed · BLOCKER · spec · lib/a.dart:3 — returns the wrong value [id:F1]",
                        "- recorded · MINOR · standards · lib/c.dart:1 — naming [id:F2]"])
        s = XA.pr_section(rec(B1, b2))
        self.assertIn("- 수정됨: BLOCKER 1 · MAJOR 0 · MINOR 0", s)
        self.assertIn("- recorded · MINOR · lib/c.dart:1 — naming", s)
        self.assertTrue(s.startswith("<!-- guild:auditor:pr -->") and s.endswith("<!-- /guild:auditor:pr -->"))


class AuditorReply(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(XA.parse_auditor_reply("[]"), [])
        self.assertIsNone(XA.parse_auditor_reply("no findings, all good"))
        self.assertIsNone(XA.parse_auditor_reply('[{"severity": "HUGE", "file": "a", "finding": "x"}]'))
        got = XA.parse_auditor_reply('```json\n[{"severity": "MAJOR", "axis": "standards", "file": "a.dart", '
                                     '"line": 4, "finding": "x", "why": "y"}]\n```')
        self.assertEqual((got[0].severity, got[0].location), ("MAJOR", "a.dart:4"))


class RetroCounts(unittest.TestCase):
    def test_engine_lines_count_like_retro(self):
        a = arb(rec(B1), [cur(f="lib/b.dart", text="other")], attempts_in_invocation=1)
        r = rec(B1, a.block(2, INV1, H2, loopback=1))
        c = r.counts()
        self.assertEqual((c["records"], c["looped_back"], c["fixed"]), (2, 2, 1))
        self.assertEqual(r.blocks[1].loopback, "1")


if __name__ == "__main__":
    unittest.main()
