"""K4 — the issue FSM (§2.2 routing, §2.5 resume, §3.6 execute→test + SJ-HANDOFF, exit codes 0/3/6/75,
NEEDS_CONTEXT map, variants) and the children orchestration (2b/2c, G-INTEGRATE)."""

import io
import json
import unittest

import _util  # noqa: F401
from _k4 import (ANALYZE_OUT, CFG, K4, comment, decision, evidence, kickoff, out_role, techlead_ok, tester_ok)

from guildcore import ask as ASK
from guildcore.adapters.gh import GhWriteError
from guildcore.judges.runner import Halted, RateLimited
from workflows.dev import fsm as F
from workflows.dev.stages import base as B
from workflows.dev.stages import children as CH
from workflows.dev.stages.base import StageResult


def driver(h, stages=None, unattended=True):
    def ports_for(n, stage, variant=None):
        if n == h.n:
            p = h.p
        else:
            from guildcore.decisions import DecisionWriter
            p = B.Ports(n, h.gh, h.writer, DecisionWriter(h.writer, n, h.clock), h.clock, h.p.config, h.p.root,
                        unattended=unattended, run_role=h.p.run_role, judge=h.p.judge, capture=h.p.capture)
            p.events = h.p.events
        p.variant_seen = variant
        return p
    return F.Driver(ports_for, unattended=unattended, plugin="0.102.0-k4", stages=stages or {})


def relabel(h, to, frm=None, n=None):
    def fn(p, *a, **k):
        cur = [l["name"] for l in h.gh.fx["issues"][str(n or p.issue)]["labels"]]
        frm_ = frm or next(l for l in cur if l.startswith("guild:") and l not in ("guild:child", "guild:needs-human"))
        p.writer.labels_apply(p.issue, add=["guild:" + to], remove=[frm_])
        return StageResult(StageResult.ADVANCE, nxt=to) if to != "done" else StageResult(StageResult.DONE)
    return fn


EXEC_OK = [comment("<!-- guild:auditor:execute -->\n### audit-record 1\ninvocation: 2026\nhead: abc\nscan: none\n"
                   "findings: none\n<!-- /guild:auditor:execute -->", 40),
           comment("<!-- guild:test-evidence:step-1 -->\nok\n<!-- /guild:test-evidence:step-1 -->", 41)]
NOVIS = dict(CFG, visual={})
PR = {"number": 30, "url": "https://github.com/o/r/pull/30", "state": "OPEN", "title": "t", "body": "Closes #7"}


class Routing(unittest.TestCase):
    def test_engine_start_first_then_full_spine(self):
        seen = []
        h = K4(self, labels=(), comments=EXEC_OK, prs=[PR], config=NOVIS)

        def stage(name, to):
            f = relabel(h, to)

            def fn(p, *a, **k):
                seen.append((name, getattr(p, "variant_seen", None), p.stage_start is not None))
                if name == "analyze":                              # B.enter adds guild:analyze on a fresh Issue (T1)
                    self.assertTrue(h.decisions_of("engine-start"))   # R3C-M5: before any label write
                    p.writer.labels_apply(p.issue, add=["guild:analyze"])
                return f(p)
            return fn
        stages = {"analyze": stage("analyze", "design"), "design": stage("design", "execute"),
                  "execute": stage("execute", "test"), "test": stage("test", "qa"), "qa": stage("qa", "done")}
        out = driver(h, stages).run(7)
        self.assertEqual(out.exit_code, 0)
        self.assertEqual(out.result.kind, StageResult.DONE)
        self.assertEqual([s[0] for s in seen], ["analyze", "design", "execute", "test", "qa"])
        self.assertEqual(seen[2][1], "implement")
        self.assertTrue(all(s[2] for s in seen))
        es = h.decisions_of("engine-start")
        self.assertEqual(len(es), 1)
        self.assertEqual(es[0].get("plugin"), "0.102.0-k4")

    def test_variant_from_type_label(self):
        self.assertEqual(F.variant_of([{"name": "type:bug"}]), "debug")
        self.assertEqual(F.variant_of(["type:refactor"]), "refactor")
        self.assertEqual(F.variant_of([]), "implement")

    def test_sprint_and_pr_are_prevalidate(self):
        h = K4(self, labels=("guild:sprint",))
        out = driver(h).run(7)
        self.assertEqual((out.exit_code, out.result.fail_class), (0, "prevalidate"))
        self.assertEqual(h.w.calls, [])                             # no engine-start, no label

    def test_only_refuses_other_stage(self):
        h = K4(self, labels=("guild:design",))
        out = driver(h).run(7, only="test")
        self.assertIn("runs only at guild:test", out.line)

    def test_done_open_with_closed_as_decided_finishes_close(self):
        cd = comment("<!-- guild:closed-as-decided -->\n결정: «x»\n닫는 이유: 하지 않기로 결정 (not_planned)\n"
                     "<!-- /guild:closed-as-decided -->", 20)
        ao = comment("<!-- guild:analyze:output -->\n## Guild analyze — #7\n\n결정대로 닫음: «x» — 코드 변경 없음\n"
                     "<!-- /guild:analyze:output -->", 19)
        h = K4(self, labels=("guild:done",), comments=[ao, cd])
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.DONE)
        self.assertEqual(h.issue()["state"], "CLOSED")
        self.assertEqual(h.issue()["stateReason"], "NOT_PLANNED")

    def test_uninitialized_is_env_halt(self):
        h = K4(self)
        h.p.config = None
        out = driver(h).run(7)
        self.assertEqual(out.exit_code, 6)
        self.assertEqual(out.line, "halted: env uninitialized")


class ExitCodes(unittest.TestCase):
    def _raise(self, exc):
        def fn(p, *a, **k):
            raise exc
        return fn

    def test_halted_6_rate_limited_75_auth_3(self):
        for exc, code in ((Halted(), 6), (GhWriteError("labels", "HTTP 401", "auth"), 3)):
            h = K4(self)
            self.assertEqual(driver(h, {"analyze": self._raise(exc)}).run(7).exit_code, code)
        from guildcore.ratelimit import Verdict
        h = K4(self)
        rl = RateLimited(Verdict("rejected", 1900000000))
        out = driver(h, {"analyze": self._raise(rl)}).run(7)
        self.assertEqual(out.exit_code, 75)
        buf = io.StringIO()
        F.final_events(out, 0.5, out=buf)
        ev = [json.loads(x) for x in buf.getvalue().strip().split("\n")]
        self.assertEqual(ev[0]["rate_limit_info"], {"status": "rejected", "resetsAt": 1900000000})
        self.assertEqual(ev[1]["type"], "result")
        self.assertEqual(len(ev), 2)

    def test_env_halt_maps_to_6_with_reason(self):
        h = K4(self, labels=("guild:test",))
        out = driver(h, {"test": lambda p, **k: B.env_halt("build-inputs-changed", "x", "pubspec.yaml")}).run(7)
        self.assertEqual(out.exit_code, 6)
        self.assertEqual(out.line, "halted: env build-inputs-changed — pubspec.yaml")

    def test_unexpected_transient_write_pauses_service(self):
        h = K4(self)
        out = driver(h, {"analyze": self._raise(GhWriteError("x", "HTTP 502", "transient"))}).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertIn("guild:needs-human", h.labels())


class Handoff(unittest.TestCase):
    def test_execute_to_test_pass_continues(self):
        h = K4(self, labels=("guild:execute",), comments=EXEC_OK, prs=[PR], config=NOVIS)
        out = driver(h, {"execute": relabel(h, "test"), "test": relabel(h, "qa"), "qa": relabel(h, "done")}).run(7)
        self.assertEqual(out.result.kind, StageResult.DONE)
        self.assertEqual(h.decisions_of("HANDOFF"), [])

    def test_gap_fixable_loops_back_from_leader(self):
        gap = decision("upstream_gap", {"verdict": "upstream_gap", "reason": "no PR", "signature": ["pr"],
                                        "fixable_by_execute": True})
        h = K4(self, labels=("guild:execute",), judges={"HANDOFF": gap})
        runs = []

        def ex(p, v):
            runs.append(1)
            if len(runs) == 2:
                return StageResult(StageResult.PAUSE, cause="stop here")
            return relabel(h, "test")(p)
        out = driver(h, {"execute": ex}).run(7)
        self.assertEqual(len(runs), 2)                                # looped back into execute
        self.assertIn("### loopback 1", h.body_with("loopback"))
        self.assertIn("from: leader", h.body_with("loopback"))
        self.assertEqual(out.result.kind, StageResult.PAUSE)

    def test_gap_not_fixable_pauses(self):
        gap = decision("upstream_gap", {"verdict": "upstream_gap", "reason": "no evidence", "fixable_by_execute": False})
        h = K4(self, labels=("guild:execute",), judges={"HANDOFF": gap})
        out = driver(h, {"execute": relabel(h, "test")}).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertIn("execute→test hand-over gap", out.line)

    def test_ok_with_assumption_continues_and_logs(self):
        ok = decision("ok_with_assumption", {"verdict": "ok_with_assumption", "line": "evidence is in the PR"})
        h = K4(self, labels=("guild:execute",), judges={"HANDOFF": ok})
        out = driver(h, {"execute": relabel(h, "test"), "test": relabel(h, "qa"), "qa": relabel(h, "done")}).run(7)
        self.assertEqual(out.result.kind, StageResult.DONE)
        self.assertEqual(h.decisions_of("HANDOFF")[0].get("assumption"), "evidence is in the PR")


class NeedsContext(unittest.TestCase):
    def test_design_needs_analyze_producer_ran(self):
        h = K4(self, labels=("guild:design",))
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertIn("producing stage (analyze) already ran", out.line)

    def test_unknown_text_is_unknown_state(self):
        self.assertIsNone(F.producer_of("something else"))
        self.assertEqual(F.producer_of("design/skeleton not found for #7"), "design")


class Resume(unittest.TestCase):
    def _paused(self, unattended=True):
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear"), "STAKES": decision("high", {"level": "high"})},
               unattended=unattended)
        from workflows.dev.stages import analyze as A
        r = A.run(h.p)
        return h, r

    def test_label_still_on_waits(self):
        h, r = self._paused()
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertIn("waiting for a human answer to %s" % r.qid, out.line)

    def test_answer_line_resumes_with_the_human_choice(self):
        h, r = self._paused()
        it = h.issue()
        # K5r4-m1: tokens follow the canonical content order — "hide the count" is i1
        it["comments"].append(dict(comment("guild-answer: %s i1" % r.qid, 900, at="2026-11-16T01:00:00Z"),
                                   user={"login": "owner"}))
        it["labels"] = [l for l in it["labels"] if l["name"] != "guild:needs-human"]
        it["timeline"].append({"id": 5, "event": "unlabeled", "label": {"name": "guild:needs-human"},
                               "created_at": "2026-11-16T01:00:01Z", "actor": {"login": "owner"}})
        h.roles += [evidence(self), out_role(self, "DONE", ac_patch=[])]
        h.judges["KICKOFF"] = kickoff(goal="unclear")
        out = driver(h, {"design": lambda p, **k: StageResult(StageResult.PAUSE, cause="design stub")}).run(7)
        self.assertIn("guild:design", h.labels())
        self.assertIn("- (선택) i1: hide the count", h.body_with("analyze:output"))
        res = [b for b in h.decisions_of("KICKOFF")]
        self.assertEqual(len(res), 2)

    def test_label_removed_without_answer_rejudges(self):
        h, r = self._paused()
        it = h.issue()
        it["labels"] = [l for l in it["labels"] if l["name"] != "guild:needs-human"]
        it["timeline"].append({"id": 5, "event": "unlabeled", "label": {"name": "guild:needs-human"},
                               "created_at": "2026-11-16T01:00:01Z", "actor": {"login": "owner"}})
        h.roles += [evidence(self)]
        h.judges["KICKOFF"] = kickoff()
        out = driver(h, {"design": lambda p, **k: StageResult(StageResult.PAUSE, cause="design stub")}).run(7)
        sup = [b for b in h.decisions_of("ask:readiness") if b.get("status") == "superseded"]
        self.assertTrue(sup)
        self.assertIn("guild:design", h.labels())

    def test_stage_moved_outside_engine_supersedes(self):
        h, r = self._paused()
        it = h.issue()
        it["labels"] = [{"name": "guild:design"}]
        it["timeline"].append({"id": 6, "event": "labeled", "label": {"name": "guild:design"},
                               "created_at": "2026-11-16T02:00:00Z", "actor": {"login": "owner"}})
        out = driver(h, {"design": lambda p, **k: StageResult(StageResult.PAUSE, cause="design stub")}).run(7)
        sup = [b for b in h.decisions_of("ask:readiness") if b.get("status") == "superseded"]
        self.assertIn("stage changed outside engine", sup[0].get("reason"))
        self.assertEqual(out.line, "OK PAUSE: needs-human — design stub")

    def test_interrupted_pause_is_finished_with_its_cause(self):
        h = K4(self)
        q = ASK.Question("readiness", "Goal unclear — x", [{"token": "i1", "label": "a"}, {"token": "stop", "label": "s"}])
        f = q.pending_fields(stage="analyze")
        f["cause"] = "ambiguity: Goal unclear — x"
        h.decisions.record(f)                                         # died before the comment + label
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertIn("guild:needs-human", h.labels())
        self.assertEqual(h.body_with("needs-human").split("\n")[1], "ambiguity: Goal unclear — x")

    def test_attended_reasks_the_stored_question(self):
        h, r = self._paused(unattended=False)
        h.events.clear()
        out = driver(h, unattended=False).run(7)
        self.assertEqual(out.result.kind, StageResult.ASK)
        self.assertEqual(out.result.qid, r.qid)
        self.assertEqual([e[0] for e in h.events], ["ask"])


class Children(unittest.TestCase):
    def kid(self, n, labels=("guild:child", "guild:analyze"), state="OPEN", **kw):
        it = {"number": n, "title": "[Guild子] k%d" % n, "body": "s\n\nParent Issue: #7\n", "state": state,
              "labels": [{"name": l} for l in labels], "comments": [], "timeline": []}
        it.update(kw)
        return it

    def test_children_driven_in_order_then_integration_clean(self):
        kids = {"8": self.kid(8), "9": self.kid(9)}
        clean = decision("clean", {"verdict": "clean", "coverage": [{"ac": "AC #1", "by": "#8"}], "gaps": []})
        h = K4(self, labels=("guild:children",), comments=[comment(ANALYZE_OUT, 10)], issues=kids,
               roles=[out_role(self, "DONE", files={"coverage.json": {"coverage": []}}, coverage_path="out/coverage.json")],
               judges={"INTEGRATE": clean})
        order = []

        def an(p, **k):
            order.append(p.issue)
            p.writer.labels_apply(p.issue, add=["guild:done"], remove=["guild:analyze"])
            return StageResult(StageResult.DONE)
        out = driver(h, {"analyze": an}).run(7)
        self.assertEqual(order, [8, 9])
        self.assertEqual(out.result.kind, StageResult.DONE)
        self.assertIn("guild:done", h.labels())
        self.assertNotIn("guild:children", h.labels())
        self.assertIn("verdict: clean", h.body_with("integration:output"))

    def test_a_paused_child_stops_orchestration(self):
        kids = {"8": self.kid(8), "9": self.kid(9)}
        h = K4(self, labels=("guild:children",), issues=kids)
        order = []

        def an(p, **k):
            order.append(p.issue)
            return StageResult(StageResult.PAUSE, cause="child needs a person")
        out = driver(h, {"analyze": an}).run(7)
        self.assertEqual(order, [8])                                   # J-DEV-09: #9 never runs
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertIn("남은 자식: #9", out.result.notes[-1])

    def test_human_merged_child_cleaned_up(self):
        kids = {"8": self.kid(8, labels=("guild:child", "guild:execute"), state="CLOSED",
                              closed_by_prs=[{"number": 31, "repo": "o/r"}])}
        h = K4(self, labels=("guild:children",), issues=kids, prs=[{"number": 31, "state": "MERGED", "body": "", "url": "u"}],
               roles=[out_role(self, "FAIL", "x")],
               judges={"INTEGRATE": decision("clean", {"verdict": "clean", "coverage": [], "gaps": []})})
        out = driver(h).run(7)
        k8 = sorted(l["name"] for l in h.gh.fx["issues"]["8"]["labels"])
        self.assertEqual(k8, ["guild:child", "guild:done"])
        self.assertIn("자식 #8 는 PR #31 로 머지되어 done 으로 정리함", "\n".join(h.bodies()))
        self.assertEqual(out.result.kind, StageResult.DONE)

    def test_gap_with_open_pr_pauses_with_path(self):
        kids = {"8": self.kid(8, labels=("guild:child", "guild:done"))}
        gap = decision("gap", {"verdict": "gap", "coverage": [], "gaps": [{"kind": "coverage", "child_to_fix": 8,
                                                                            "needs_decision": False, "line": "AC 2 missing"}]})
        h = K4(self, labels=("guild:children",), issues=kids, prs=[{"number": 32, "state": "OPEN", "body": "Closes #8", "url": "u"}],
               roles=[out_role(self, "DONE", files={"coverage.json": {}}, coverage_path="out/coverage.json")],
               judges={"INTEGRATE": gap})
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertIn("defect: integration gap — AC 2 missing", out.line)
        self.assertIn("#8 의 PR #32 에서 고칩니다", h.body_with("needs-human"))
        self.assertIn("guild:children", h.labels())

    def test_slicing_gap_always_needs_a_person(self):
        kids = {"8": self.kid(8, labels=("guild:child", "guild:done"))}
        gap = decision("gap", {"verdict": "gap", "coverage": [], "gaps": [{"kind": "slicing", "child_to_fix": 8,
                                                                            "needs_decision": False, "line": "split wrong"}]})
        h = K4(self, labels=("guild:children",), issues=kids, roles=[out_role(self, "DONE", coverage_path="out/coverage.json")],
               judges={"INTEGRATE": gap})
        out = driver(h).run(7)
        self.assertIn("ambiguity: integration gap", out.line)

    def test_attended_merged_gap_asks_and_yes_creates_fix_child(self):
        kids = {"8": self.kid(8, labels=("guild:child", "guild:done"))}
        gap = decision("gap", {"verdict": "gap", "coverage": [], "gaps": [{"kind": "consistency", "child_to_fix": 8,
                                                                            "needs_decision": False, "line": "seam differs"}]})
        h = K4(self, labels=("guild:children",), issues=kids, unattended=False,
               roles=[out_role(self, "DONE", coverage_path="out/coverage.json")], judges={"INTEGRATE": gap})
        out = driver(h, unattended=False).run(7)
        self.assertEqual(out.result.kind, StageResult.ASK)
        ASK.answer(h.decisions, h.writer, 7, out.result.qid, "yes")

        def an(p, **k):
            return StageResult(StageResult.PAUSE, cause="fix child stub")
        out2 = driver(h, {"analyze": an}, unattended=False).run(7)
        fix = [it for it in h.gh.fx["issues"].values() if (it.get("title") or "").startswith("[Guild子] 통합 수정")]
        self.assertEqual(len(fix), 1)
        self.assertIn("Parent Issue: #7", fix[0]["body"])
        self.assertEqual(out2.result.kind, StageResult.PAUSE)

    def test_no_children_is_defect(self):
        h = K4(self, labels=("guild:children",))
        out = driver(h).run(7)
        self.assertIn("holds no live child Issue of it", out.line)


if __name__ == "__main__":
    unittest.main()
