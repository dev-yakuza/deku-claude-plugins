"""K5 review r4 — "needed before K6" (a) the §9.5 2-call grader and (b) the predict-first count; m5 triggers/evidence.

(b)  predict-first answers are human judgments: blind ∧ revealed ∧ not `stop` → ok (= recommendation) / wrong;
     `predict_first_refused`, `reveal: unavailable`, a non-blind answer and `stop` are never counted. They enter
     grades.jsonl (`predict-first`) once and drive the count rules.
m5   triggers come from the Issue's history (a later pending question / loop-back record / QA fail / timeline
     needs-human / review rejection), not its current label; a KICKOFF whose readiness a person answered is not on
     the sheet; the sheet's evidence column carries PR state, reviews, CI and loop-backs.
(a)  the grader: blind call without the engine's choice, reveal call with it; citations verified against the evidence
     (a failed or missing one → unsure); `ok` without the decision's own object → unsure; TEST effective needs the code
     check and two citations; flagged → the person's sheet; calibration from its `ok`s; the same key is never called
     twice; pass 2 only re-grades pass-1 unsures; its output is revealed on import only. No model is called: the
     judge is a fake.
"""

import csv
import io
import json
import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir
from _k2 import comment, decision
from test_k5_cli import Env

from guildcore.records.decisions import DecisionBlock
from workflows.dev import cli as CLI
from workflows.dev import grade as G
from workflows.dev import grader as GD


def blk(n, **f):
    return DecisionBlock(n, list(f.items()))


def pf_log(pf="high-risk", refused=None, reveal=None, rec="i2", choice="i1", kind="readiness"):
    q = dict(point="ask:%s" % kind, kind=kind, stage="analyze", by="code", status="pending-human")
    if pf:
        q.update(predict_first=pf, recommended_sha="abc")
    if refused:
        q.update(predict_first_refused=refused, recommended=rec)
    r = dict(point="ask:%s" % kind, kind=kind, stage="analyze", by="human", choice=choice, resolves="D1")
    if reveal:
        r["reveal"] = reveal
    elif rec:
        r.update(recommended=rec, nonce="n")
    return [blk(1, **q), blk(2, **r)]


class PredictFirstCount(unittest.TestCase):
    def test_blind_answers_count_ok_and_wrong(self):
        self.assertEqual([(r["group"], r["given_info"]) for r in G.predict_first_judgments(pf_log(), 7)],
                         [("KICKOFF", "wrong")])
        self.assertEqual(G.predict_first_judgments(pf_log(choice="i2"), 7)[0]["given_info"], "ok")

    def test_excluded_answers(self):
        for log in (pf_log(pf=None, refused="question (high-risk)"),        # refused: saw the recommendation
                    pf_log(reveal="unavailable"),                           # could not be revealed
                    pf_log(pf=None, rec="i2"),                              # not blind at all
                    pf_log(choice="stop")):                                  # no judgment
            self.assertEqual(G.predict_first_judgments(log, 7), [])

    def test_counted_once_and_drive_the_count_rules(self):
        common = os.path.join(tmpdir(self), "c")
        rows = G.predict_first_judgments(pf_log(), 7)
        self.assertEqual(G.apply_judgments(common, rows, "o/r", "predict-first")["watch"], ["KICKOFF"])
        self.assertEqual(G.apply_judgments(common, rows, "o/r", "predict-first")["imported"], 0)


class Triggers(unittest.TestCase):
    def test_history_not_the_current_label(self):
        blocks = [blk(1, point="STAKES", stage="analyze", by="judge:opus", choice="low"),
                  blk(2, point="ask:escalation", stage="execute", status="pending-human", by="code"),
                  blk(3, point="TEST", stage="test", by="judge:sonnet", choice="effective:AC #1;uncovered:none"),
                  blk(4, point="QA", stage="qa", by="judge:sonnet", choice="block")]
        later = G.history_triggers(blocks)
        self.assertEqual(later(blocks[0]), "needs-human, qa-fail")           # a later question, label long gone
        self.assertEqual(later(blocks[2]), "qa-fail")
        later = G.history_triggers(blocks, loopbacks=["qa"], review_rejections=1)
        self.assertIn("loop-back", later(blocks[2]))
        self.assertIn("review: changes requested", later(blocks[2]))
        self.assertIsNone(G.history_triggers([blocks[2]])(blocks[2]))

    def test_kickoff_answered_by_a_person_is_not_on_the_sheet(self):
        log = [blk(1, point="KICKOFF", stage="analyze", by="judge:opus", choice="goal=unclear")] + \
            [blk(b.n + 1, **dict(b.fields, **({"resolves": "D2"} if b.get("resolves") else {}))) for b in pf_log()]
        sel = G.select({7: log}, "o/r", True, 0.3, lambda i, b: None)
        self.assertNotIn("D1", [b.id for _i, b, _w in sel])


def _fake(script):
    """A fake judge: `script(spec, call)` → Decision; records every call (no model is ever run)."""
    calls = []

    def judge(spec):
        call = spec.point.rsplit(":", 1)[-1]
        calls.append((spec.point, spec.model, spec.kind, [k for k, _v in spec.brief_parts]))
        return script(spec, call)
    judge.calls = calls
    return judge


class Settle(unittest.TestCase):
    B = blk(5, point="EX-ARB", stage="execute", by="judge:opus", refs="F1", choice="F1:accept",
            raw_choice="F1:would-dismiss", coerced="true", coerced_by="first-sprint")

    def test_citations_verified_and_suppression(self):
        base = "review by alice: F1 at lib/a.dart:3 was a real bug, fixed in the PR\nCI green"
        self.assertEqual(GD.settle(self.B, {"given_info": "wrong", "cited_evidence": ["F1 at lib/a.dart:3 was a real bug"]},
                                   base)[0], "wrong")
        gi, why, _c = GD.settle(self.B, {"given_info": "ok", "cited_evidence": ["not in the brief"]}, base)
        self.assertEqual((gi, why[:18]), ("unsure", "citation not found"))
        self.assertEqual(GD.settle(self.B, {"given_info": "ok", "cited_evidence": []}, base)[0], "unsure")
        gi, why, _c = GD.settle(self.B, {"given_info": "ok", "cited_evidence": ["CI green"]}, base)
        self.assertEqual((gi, why), ("unsure", "ok without a citation of the decision's own object"))
        self.assertEqual(GD.settle(self.B, {"given_info": "ok", "cited_evidence": ["F1 at lib/a.dart:3"]}, base)[0], "ok")

    def test_test_effective_needs_the_code_check_and_two_citations(self):
        t = blk(6, point="TEST", stage="test", by="judge:sonnet", choice="effective:AC #1;uncovered:none",
                checks="AC #1:pass")
        base = "AC #1: the count shows 3\nexpect(find.text('3'), findsOneWidget);"
        one = {"given_info": "ok", "cited_evidence": ["AC #1: the count shows 3"]}
        two = dict(one, cited_evidence=["AC #1: the count shows 3", "expect(find.text('3'), findsOneWidget);"])
        self.assertEqual(GD.settle(t, one, base)[0], "unsure")
        self.assertEqual(GD.settle(t, two, base)[0], "ok")
        self.assertEqual(GD.settle(blk(6, **dict(t.fields, checks="AC #1:fail")), two, base)[0], "unsure")

    def test_blind_call_never_sees_the_choice_and_reveal_does(self):
        def script(spec, call):
            if call == "blind":
                brief = "\n".join(v for _k, v in spec.brief_parts)
                self.assertNotIn("would-dismiss", brief)
                self.assertNotIn("F1:accept", brief)
                return decision("accept", {"choice": "F1:accept", "reason": "r", "cited_evidence": ["F1 real bug"]})
            self.assertIn("F1:would-dismiss", "\n".join(v for _k, v in spec.brief_parts))
            return decision("wrong", {"given_info": "wrong", "outcome": "inconsistent", "reason": "r",
                                      "cited_evidence": ["F1 real bug"]})
        j = _fake(script)
        row = GD.grade(j, self.B, 7, "EX-ARB:dismiss", "review: F1 real bug", "opus", "title")
        self.assertEqual((row["given_info"], row["flagged"], row["prosecutor"]), ("wrong", True, True))
        self.assertEqual([c[2] for c in j.calls], ["monitoring", "monitoring"])
        self.assertTrue(row["grader_version"].startswith("g"))


class Cli(unittest.TestCase):
    def _env(self):
        e = Env(self, config={"version": "0.101.0", "language": "ko", "engine": {"first_sprint_mode": "on"}})
        rec = e.h.decisions.record
        rec({"point": "STAKES", "by": "judge:opus", "stage": "analyze", "choice": "low", "reason": "local AC #1"})
        rec({"point": "TEST", "by": "judge:sonnet", "stage": "test", "choice": "effective:AC #1;uncovered:none",
             "checks": "AC #1:pass"})
        rec({"point": "QA", "by": "judge:sonnet", "stage": "qa", "choice": "pass"})
        rec({"point": "KICKOFF", "by": "judge:opus", "stage": "analyze", "choice": "goal=clear"})
        it = e.h.gh.fx["issues"]["7"]
        it["closed_by_prs"] = [{"number": 31, "repo": "o/r"}]
        it["comments"].append(comment("looks right to me — AC #1 shown", 777))
        e.h.gh.fx.setdefault("prs", []).append({"number": 31, "state": "MERGED", "mergedAt": "2026-11-17T00:00:00Z",
                                                 "headRefOid": "abc1234", "url": "u", "body": "Closes #7"})
        e.h.gh.fx["reviews"] = {"31": [{"state": "APPROVED", "body": "AC #1 verified", "user": {"login": "rev"}}]}
        e.h.gh.fx["check_runs"] = {"abc1234": [{"id": 1, "name": "ci", "conclusion": "success"}]}
        e.h.gh.fx["diffs"] = {"31": "+ Text('3')"}
        return e

    def test_grader_pass_flags_sheet_and_reveal_on_import(self):
        e = self._env()

        def script(spec, call):
            grp = spec.point.split(":")[1]
            if call == "blind":
                return decision("x", {"choice": "low" if grp == "STAKES" else "pass", "reason": "r",
                                      "cited_evidence": ["AC #1 verified"]})
            gi = {"STAKES": "ok", "TEST": "unsure", "QA": "ok"}[grp]
            return decision(gi, {"given_info": gi, "outcome": "consistent", "reason": "r",
                                 "cited_evidence": ["AC #1 verified"]})
        j = _fake(script)
        e.d.grader_judge = j
        out = os.path.join(tmpdir(self), "sheet")
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out, "--grader"], e.d), 0)
        res = json.loads(e.lines()[-1].split(">>> ENGINE <<<")[-1])
        groups = sorted(c[0].split(":")[1] for c in j.calls if c[0].endswith(":blind"))
        self.assertEqual(groups, ["QA", "STAKES", "TEST"])                    # never KICKOFF
        self.assertEqual(res["graded"], 3)
        self.assertTrue(all(c[1] == "opus" for c in j.calls))
        rows = list(csv.DictReader(open(os.path.join(out, "issues.csv"))))
        self.assertNotIn("given_info_grader", rows[0])
        why = dict((r["decision_id"], r["evidence"]) for r in rows)
        self.assertTrue(any("grader flagged" in w for w in why.values()))    # TEST unsure → the person
        self.assertTrue(any("PR #31 merged" in w and "reviews 1" in w and "CI 1/1 ok" in w for w in why.values()))
        # the same keys are never called again
        n = len(j.calls)
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out, "--grader"], e.d), 0)
        self.assertEqual(len(j.calls), n)
        # pass 2: only the pass-1 unsure (TEST)
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out, "--grader", "--pass", "2"], e.d), 0)
        self.assertEqual(sorted(set(c[0].split(":")[1] for c in j.calls[n:])), ["TEST"])
        # import reveals the grader's output for the imported rows only now
        rows[0]["given_info"] = "ok"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=G.COLUMNS)
        w.writeheader()
        w.writerow(rows[0])
        p = os.path.join(out, "filled.csv")
        with open(p, "w") as fh:
            fh.write(buf.getvalue())
        self.assertEqual(CLI.main(["grade", "--import", p], e.d), 0)
        imp = json.loads(e.lines()[-1].split(">>> ENGINE <<<")[-1])
        self.assertEqual([x["decision_id"] for x in imp["grader"]], [rows[0]["decision_id"]])

    def test_grader_tier_comes_from_config(self):
        e = Env(self, config={"version": "0.101.0", "language": "ko",
                              "engine": {"first_sprint_mode": "on", "grading": {"grader_model": "sonnet"}}})
        cfg = os.path.join(e.h.p.root, ".claude", "guild", "config.json")
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        with open(cfg, "w") as fh:                                 # `dev grade` reads the committed config
            json.dump({"version": "0.101.0", "language": "ko", "roles": [],
                       "engine": {"first_sprint_mode": "on", "grading": {"grader_model": "sonnet"}}}, fh)
        e.h.decisions.record({"point": "STAKES", "by": "judge:opus", "stage": "analyze", "choice": "low"})
        j = _fake(lambda spec, call: decision("x", {"choice": "low", "given_info": "unsure", "outcome": "unknown",
                                                    "reason": "r", "cited_evidence": []}))
        e.d.grader_judge = j
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", os.path.join(tmpdir(self), "s"), "--grader"],
                                  e.d), 0)
        self.assertEqual(set(c[1] for c in j.calls), {"sonnet"})
        self.assertEqual(G.grades(e.common)[-1]["grader_version"], GD.version("sonnet"))

    def test_without_the_grader_no_model_and_predict_first_counted(self):
        e = self._env()
        from guildcore import ask as ASK
        q = ASK.Question("readiness", "goal unclear — 범위", [{"token": "i1", "label": "a reading"},
                                                             {"token": "i2", "label": "b reading"},
                                                             {"token": "stop", "label": "stop"}],
                         recommended="i2", recommended_by="judge:opus", predict_first=True)
        q.pf_why = "high-risk"
        e.h.p.journal = e.h.journal
        tok = ASK.journal_nonce(e.h.journal, q)
        qid = e.h.decisions.record(q.pending_fields(stage="analyze"))
        ASK.journal_qid(e.h.journal, tok, qid)
        ASK.answer(e.h.decisions, e.h.writer, 7, qid, "i1", journal=e.h.journal)
        e.d.grader_judge = _fake(lambda spec, call: self.fail("no grader without --grader"))
        out = os.path.join(tmpdir(self), "sheet")
        self.assertEqual(CLI.main(["grade", "--issues", "7", "--out", out], e.d), 0)
        res = json.loads(e.lines()[-1].split(">>> ENGINE <<<")[-1])
        self.assertEqual(res["predict_first"]["judgments"], 1)
        self.assertEqual(res["predict_first"]["watch"], ["KICKOFF"])
        self.assertEqual(res["graded"], 0)
        rows = list(csv.DictReader(open(os.path.join(out, "issues.csv"))))
        self.assertNotIn("KICKOFF", [r["group"] for r in rows])              # a person judged that KICKOFF


if __name__ == "__main__":
    unittest.main()
