"""Regression tests for the K0 adversarial review r1 (design/guild/23-engine/review-k0-r1.md).
One class per finding; each reproduces the review's probe (scratchpad k0-probe/*.py)."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import _util
from guildcore import decisions as dec
from guildcore import state
from guildcore.adapters.gh import FakeGh, GhCli
from guildcore.records import answer, audit, followups, loopback, manual_qa, markers, needs_human
from guildcore.records import decisions as D
from guildcore.records import outputs, prbody, redact
from workflows.status import board, cli, route, running, show

QUOTE = "see the <!-- guild:loopback --> record and <!-- guild:needs-human --> and guild:qa:output"
AT = "2026-11-16T00:00:00Z"


def fx(issues, prs=()):
    return FakeGh({"repo": "o/r", "issues": issues, "prs": list(prs)})


def pending(**kw):
    b = {"point": "T-ARB", "by": "judge:sonnet", "stage": "test", "at": "2026-11-16T09:00:00Z",
         "status": "pending-human", "question": "q", "options": "loop-back|stop", "kind": "loopback"}
    b.update(kw)
    return b


class B1MarkerNeutralization(unittest.TestCase):
    def setUp(self):
        self.dlog = D.render_comment([D.render_block(1, pending(reason=QUOTE, question="loop back? <!-- /guild:decisions -->"))])
        self.lb = loopback.render_new_record(loopback.render_block(1, "test", "2026-11-16T00:00:01Z", "b", "r", "T1"))
        self.comments = [{"id": 5, "body": self.dlog}, {"id": 9, "body": self.lb}]

    def test_only_own_markers_survive(self):
        self.assertEqual(self.dlog.count("<!-- guild:"), 1)
        self.assertEqual(self.dlog.count("<!-- /guild:"), 1)
        self.assertEqual(D.DecisionComment(self.dlog).blocks[0].get("reason").count(markers.ZWSP), 3)

    def test_engine_readers(self):
        self.assertEqual(loopback.from_comments(self.comments).comment_id, 9)
        self.assertEqual(needs_human.from_comments(self.comments), [])
        self.assertFalse(outputs.presence(self.comments)["qa"])
        gh = fx({"1": {"title": "t", "labels": [{"name": "guild:test"}], "comments": self.comments}})
        self.assertIn("Loop-backs: 1/2", show.show(gh, 1))

    def test_live_jq_readers(self):
        _util.need_jq(self)
        h = _util.read(os.path.join(_util.SKILL, "commands", "atoms", "_handoff.md"))
        import re
        lb_expr = re.search(r"gh api --paginate repos/<owner>/<repo>/issues/<N>/comments\s+--jq '([^']+)'", h)
        expr = lb_expr.group(1) if lb_expr else '.[] | select((.body // "") | contains("<!-- guild:loopback -->")) | {id, body}'
        ids = [json.loads(l)["id"] for l in _util.jq(expr, self.comments, raw=False).split("\n") if l.strip()]
        self.assertEqual(ids, [9])
        st = _util.jq('[.[] | .body // ""] | join("\\n") | test("guild:qa:output")', self.comments)
        self.assertEqual(st.strip(), "false")
        daily = _util.jq('.[] | select((.body // "") | contains("<!-- guild:needs-human -->")) | .id', self.comments)
        self.assertEqual(daily.strip(), "")

    def test_every_renderer_neutralizes(self):
        outs = [
            loopback.render_block(1, "test", AT, "fix/b", QUOTE, QUOTE),
            needs_human.render(needs_human.cause_line("defect", QUOTE), prose=QUOTE),
            followups.render(QUOTE, [followups.parse_item("- unfiled — %s — x" % QUOTE)]),
            followups.render_pr_notice(3, [QUOTE]),
            manual_qa.render([QUOTE]),
            audit.render_block(1, AT, "0" * 40, [audit.render_finding("fixed", "MINOR", "spec", "a:1", QUOTE)], ["role-axis: " + QUOTE]),
            prbody.render_unattended([QUOTE]),
            outputs.render_recheck_note(AT, True, QUOTE),
            outputs.render_loopback_lines(QUOTE, "x"),
        ]
        for o in outs:
            self.assertNotIn("<!-- guild:loopback -->", o)
            self.assertNotIn("<!-- guild:needs-human -->\n", o[1:])
            self.assertNotIn("guild:qa:output", o)

    def test_assertion_guards_raw_blocks(self):
        with self.assertRaises(ValueError):
            markers.assert_own_markers("x <!-- guild:loopback --> y")
        with self.assertRaises(ValueError):
            markers.assert_own_markers("<!-- guild:note -->\n<!-- guild:qa:output -->", "note")


class M1Redaction(unittest.TestCase):
    PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAsecretbodyAAAA\n-----END RSA PRIVATE KEY-----"

    def test_pem_body(self):
        self.assertEqual(redact.redact(self.PEM), "[REDACTED]")
        # r3 rule: a key anywhere in a value replaces the whole value
        self.assertEqual(redact.redact("a\n-----BEGIN PRIVATE KEY-----\nMIIsecret"), "[REDACTED]")

    def test_every_decision_field(self):
        blk = D.render_block(3, {"point": "EX-ARB", "by": "judge:opus", "raw_choice": "use ghp_" + "a" * 36,
                                 "choice": "key AKIA" + "A" * 16, "evidence": "token sk-ant-" + "x" * 30,
                                 "reason": self.PEM})
        self.assertFalse(redact.has_secret(blk))
        self.assertNotIn("secretbody", blk)

    def test_loopback_branch_and_signature(self):
        blk = loopback.render_block(1, "test", AT, "fix/ghp_" + "b" * 36, "r", "AKIA" + "B" * 16)
        self.assertFalse(redact.has_secret(blk))


class M2LineAnchoredSplice(unittest.TestCase):
    def test_inline_quote_is_not_a_marker(self):
        body = "see `<!-- guild:manual-qa -->` in docs\n## x\n<!-- guild:manual-qa -->\nreal\n<!-- /guild:manual-qa -->"
        out = markers.splice(body, "manual-qa", "<!-- guild:manual-qa -->\nNEW\n<!-- /guild:manual-qa -->")
        self.assertEqual(out, "see `<!-- guild:manual-qa -->` in docs\n## x\n<!-- guild:manual-qa -->\nNEW\n<!-- /guild:manual-qa -->")
        self.assertEqual(manual_qa.from_pr_body(body).render(), "<!-- guild:manual-qa -->\nreal\n<!-- /guild:manual-qa -->")

    def test_only_inline_mention_appends(self):
        body = "mentions `<!-- guild:manual-qa -->` only"
        self.assertEqual(markers.splice(body, "manual-qa", "B"), body + "\n\nB")

    def test_two_blocks_refused(self):   # K0-m8
        body = ("<!-- guild:manual-qa -->\nold\n<!-- /guild:manual-qa -->\n"
                "<!-- guild:manual-qa -->\nold2\n<!-- /guild:manual-qa -->")
        with self.assertRaises(ValueError):
            markers.splice(body, "manual-qa", "B")
        with self.assertRaises(ValueError):          # the same verdict as splice (K0-m20)
            manual_qa.from_pr_body(body)

    def test_crlf_marker_lines(self):
        body = "a\r\n<!-- guild:manual-qa -->\r\nold\r\n<!-- /guild:manual-qa -->\r\nz"
        out = markers.splice(body, "manual-qa", "<!-- guild:manual-qa -->\nN\n<!-- /guild:manual-qa -->")
        self.assertTrue(out.startswith("a\r\n") and out.endswith("\r\nz"))


class M3GateFailsClosed(unittest.TestCase):
    def block(self, **kw):
        body = D.render_comment([D.render_block(7, pending(**kw))]) if "kind" not in kw or kw["kind"] else None
        if body is None:   # a hand-edited block without kind: (cannot be rendered — built raw)
            body = D.render_comment([D.render_block(7, pending(status="answered"))]).replace(
                "kind: loopback\n", "").replace("status: answered", "status: pending-human")
        return dec.DecisionLog.load([_util.comment(body, 3)]).pending_human()[0]

    def run_case(self, blk):
        tl = [{"event": "unlabeled", "label": {"name": "guild:needs-human"}, "created_at": "2026-11-16T10:00:00Z",
               "actor": {"login": "alice"}}]
        c = _util.comment("guild-answer: D7 stop", 20, "2026-11-16T10:01:00Z", "MEMBER", "bob")
        return dec.accepted_answer(blk, [c], tl)[1:]

    def test_missing_kind_is_a_gate(self):
        a, rej = self.run_case(self.block(kind=None))
        self.assertIsNone(a)
        self.assertIn("label remover", rej[0][1])

    def test_stakes_high_is_a_gate(self):
        a, _ = self.run_case(self.block(kind="escalation", stakes="high"))
        self.assertIsNone(a)
        a, _ = self.run_case(self.block(kind="escalation"))
        self.assertEqual(a.token, "stop")                    # a non-gate kind needs no remover match

    def test_render_requires_kind_and_token_options(self):
        with self.assertRaises(ValueError):
            D.render_block(1, pending(kind="whatever"))
        with self.assertRaises(ValueError):
            D.render_block(1, pending(options="Loop back|stop (recommended)"))


class M4ConflictingAnswers(unittest.TestCase):
    def setUp(self):
        body = D.render_comment([D.render_block(7, pending(kind="premise", at="2026-11-16T09:00:00Z"))])
        self.blk = dec.DecisionLog.load([_util.comment(body, 3)]).pending_human()[0]
        self.tl = [{"event": "unlabeled", "label": {"name": "guild:needs-human"}, "created_at": "2026-11-16T10:05:00Z",
                    "actor": {"login": "alice"}}]

    def test_same_author_correction_latest_wins(self):
        cs = [_util.comment("guild-answer: D7 stop", 50, "2026-11-16T10:00:00Z", "OWNER", "alice"),
              _util.comment("sorry, wrong one\nguild-answer: D7 loop-back", 51, "2026-11-16T10:04:00Z", "OWNER", "alice")]
        _st, a, rej = dec.accepted_answer(self.blk, cs, self.tl)
        self.assertEqual((a.token, a.comment_id), ("loop-back", 51))
        self.assertEqual([(r[0].comment_id, r[1]) for r in rej], [(50, "superseded by a later answer")])

    def test_different_authors_conflict_surfaces(self):
        blk = self.blk
        tl = self.tl + [dict(self.tl[0], actor={"login": "bob"})]
        cs = [_util.comment("guild-answer: D7 stop", 50, "2026-11-16T10:00:00Z", "OWNER", "alice"),
              _util.comment("guild-answer: D7 loop-back", 51, "2026-11-16T10:04:00Z", "MEMBER", "bob")]
        _st, a, rej = dec.accepted_answer(blk, cs, tl)
        self.assertIsNone(a)
        self.assertEqual(sorted(r[1] for r in rej), ["conflicting answers"] * 2)


class M5UnknownStageLabel(unittest.TestCase):
    def setUp(self):
        self.gh = fx({"1": {"title": "t", "labels": [{"name": "guild:blocked"}], "comments": []},
                      "2": {"title": "p", "labels": [{"name": "guild:children"}], "comments": []},
                      "3": {"title": "c", "labels": [{"name": "guild:child"}, {"name": "guild:wip"}], "body": "Parent Issue: #2"}})

    def test_show_reports_as_is(self):
        out = show.show(self.gh, 1)
        self.assertIn("Stage: guild:blocked (unknown stage label — reported as-is)", out)
        self.assertIn("#3 c — guild:wip (unknown stage label", show.show(self.gh, 2))

    def test_route_and_board(self):
        r = route.route_snapshot(self.gh, state.IssueSnapshot(1, self.gh.issue(1), [], []))
        self.assertEqual((r.action, r.reason), ("stop", "unknown"))
        self.assertEqual(board.gather_work(self.gh)["buckets"].get("other"), 2)


class M6RunningNeverLies(unittest.TestCase):
    def test_outside_git_is_an_error(self):
        d = tempfile.mkdtemp()
        with self.assertRaises(running.RunningError):
            running.git_common_dir(d)
        err = io.StringIO()
        rc = cli.main(["running", "--root", d], out=io.StringIO(), err=err)
        self.assertEqual(rc, 1)
        self.assertIn("cannot resolve git common dir", err.getvalue())

    def test_old_git_fallback(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        shim = tempfile.mkdtemp()
        real = subprocess.run(["which", "git"], stdout=subprocess.PIPE).stdout.decode().strip()
        with open(os.path.join(shim, "git"), "w") as fh:
            fh.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = "--path-format=absolute" ] && { echo "--path-format=absolute"; exit 0; }; done\nexec %s "$@"\n' % real)
        os.chmod(os.path.join(shim, "git"), 0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = shim + os.pathsep + old
        try:
            cd = running.git_common_dir(d)
        finally:
            os.environ["PATH"] = old
        self.assertEqual(os.path.realpath(cd), os.path.realpath(os.path.join(d, ".git")))

    def test_live_and_dead_and_pidless_locks(self):   # K0-m5: judged without taking the lock
        cd = tempfile.mkdtemp()
        os.makedirs(os.path.join(cd, "guild", "engine"))
        for n, info in ((1, {"mode": "unattended", "pid": os.getpid()}), (2, {"mode": "attended", "pid": 999999}), (3, None)):
            with open(os.path.join(cd, "guild", "engine", "%d.lock" % n), "w") as fh:
                fh.write(json.dumps(info) if info else "")
        rows, _ = running.running([cd])
        self.assertEqual([(r["issue"], r["mode"]) for r in rows], [(1, "unattended"), (3, "unknown-holder")])


class MinorFixes(unittest.TestCase):
    def test_m1_unicode_line_separators(self):
        line = json.dumps({"id": 1, "body": "x y\u0085z"}, ensure_ascii=False)
        g = GhCli("o/r", runner=lambda a: line + "\n")
        self.assertEqual(g.comments(1)[0]["body"], "x y\u0085z")

    def test_m2_real_adapter_budget(self):
        calls = []
        issue = json.dumps({"number": 1, "title": "t", "url": "https://github.com/o/r/issues/1", "labels": []})

        def runner(argv):
            calls.append(" ".join(argv[:3]))
            return issue if argv[1] == "issue" else ("" if argv[1] == "api" else "[]")
        state.snapshot(GhCli(None, runner=runner), 1)
        self.assertEqual(len(calls), 3)
        self.assertNotIn("gh repo view", calls)

    def test_m3_decision_heading_trailing_blank_and_crlf_insert(self):
        body = D.render_comment([D.render_block(7, pending())]).replace("### decision 7\n", "### decision 7 \n")
        self.assertEqual([b.id for b in dec.DecisionLog.load([_util.comment(body)]).pending_human()], ["D7"])
        crlf = D.render_comment([D.render_block(1, {"by": "code"})]).replace("\n", "\r\n")
        out = D.insert(crlf, D.render_block(2, {"by": "code"}))
        self.assertNotIn("\n", out.replace("\r\n", ""))
        self.assertLess(len(D.render_block(1, {"by": "code", "reason": "x" * 70000})), 3000)

    def test_m4_answer_line_strictness(self):
        cases = {"guild-answer: D7 stop? actually no": [], "```\nguild-answer: D7 stop\n```": [],
                 "> guild-answer: D7 stop": [], "quote <!-- guild:note -->\nguild-answer: D7 stop": [],
                 "ok\nguild-answer: D7 stop  ": [(7, "stop")]}
        for body, want in cases.items():
            with self.subTest(body=body):
                self.assertEqual([(a.k, a.token) for a in answer.parse(_util.comment(body))], want)

    def test_m6_retro_view_and_interrupted(self):
        r1 = "<!-- guild:auditor:execute -->\n### audit-record 1\ninvocation: 2026-11-10T00:00:00Z\nfindings: none\n<!-- /guild:auditor:execute -->"
        r2 = "<!-- guild:auditor:execute -->\n### audit-record 1\ninvocation: 2026-11-16T00:00:00Z\n- looped-back · MAJOR · spec · a:1 — x\n<!-- /guild:auditor:execute -->"
        cs = [_util.comment(r1, 1), _util.comment(r2, 2)]
        self.assertEqual((audit.counts_all(cs)["records"], audit.counts_all(cs)["looped_back"]), (2, 1))
        _util.need_jq(self)
        lb = loopback.render_new_record(loopback.render_block(1, "test", "2026-11-12T00:00:00Z", "b", "r", "T"))
        gh = fx({"1": {"title": "t", "labels": [{"name": "guild:test"}], "comments": cs + [_util.comment(lb, 3)]}})
        r = route.route_snapshot(gh, state.snapshot(gh, 1))
        self.assertFalse(r.interrupted_loopback)       # the 2nd comment's invocation is ≥ at

    def test_m7_fenced_heading(self):
        body = "## 무인 결정 로그 (GLD_UNATTENDED)\n- a\n```\n## not a heading\n```\n- b\n## next"
        out = prbody.migrate_unattended(body)
        self.assertEqual(prbody.unattended_entries(out), ["a", "b"])
        self.assertTrue(out.endswith("<!-- /guild:unattended-log -->\n## next"))

    def test_m12_fixture_needs_test_flag(self):
        env = dict(os.environ)
        env.pop("GLD_ENGINE_TEST", None)
        env["GLD_ENGINE_GH_FIXTURE"] = _util.GH_STATUS
        p = subprocess.run([sys.executable, os.path.join(_util.ENGINE, "gld_engine.py"), "status", "show", "--issue", "101"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=tempfile.mkdtemp())
        self.assertEqual(p.returncode, 1)              # real (blocked) gh, not the fixture

    def test_m13_done_open_decided(self):
        gh = fx({"1": {"title": "t", "state": "OPEN", "labels": [{"name": "guild:done"}],
                       "comments": [_util.comment(_util.record("closed-as-decided/0.101.0/prose.md"))]}})
        r = route.route_snapshot(gh, state.snapshot(gh, 1))
        self.assertEqual((r.action, r.reason), ("stop", "done_open_decided"))


if __name__ == "__main__":
    unittest.main()
