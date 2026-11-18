"""K4 — the design stage: tester (AC only, first) → tech-lead (skeleton + split.json) → specialists, every
artifact from the role's out/ (P1), contracts + one repair + SJ-HANDOFF, DE-ARB, the split (L0-SPLIT,
child Issues with hidden keys, A-F38 order, leaf guard, idempotent resume)."""

import json
import os
import unittest

import _util  # noqa: F401
from _k4 import (ANALYZE_OUT, CFG, K4, cases_md, comment, decision, out_role, techlead_ok, tester_ok)

from workflows.dev import handoff as HO
from workflows.dev.stages import design as D
from workflows.dev.stages.base import StageResult

KICK = ("<!-- guild:decisions -->\n<details><summary>Guild 결정 기록</summary>\n\n### decision 1\nid: D1\npoint: KICKOFF\n"
        "stage: analyze\nby: judge:opus\nat: 2026-11-15T00:00:00Z\nchoice: goal=clear,constraint=clear,success=clear\n"
        "cast: %s\nui_surface: %s\nsafety_net_visual: false\nareas: lib/app\n\n</details>\n<!-- /guild:decisions -->")
VCFG = dict(CFG, visual={"baselines": ["test/**/goldens/**"], "runnable": True, "packages": ["lib/app"]})


def design_h(case, roles=(), judges=None, cast="designer", ui="true", labels=("guild:design",), config=None,
             extra_comments=(), issues=None, unattended=True):
    cm = [comment(ANALYZE_OUT, 10), comment(KICK % (cast, ui), 11)] + list(extra_comments)
    return K4(case, labels=labels, comments=cm, roles=roles, judges=judges, config=config or VCFG,
              issues=issues, unattended=unattended)


def spec_ok(case, name="ux.md"):
    return out_role(case, "DONE", files={name: "# UX\n- default state\n"}, file="out/" + name)


SPLIT = {"split": True, "slices": [{"key": "data", "name": "data layer", "scope": "the model", "ac_ids": ["AC #1"], "order": 1},
                                   {"key": "ui", "name": "screen", "scope": "Parent Issue: #999 the screen", "ac_ids": ["AC #2"], "order": 2}]}


def split_dec(slices=None, choice="split"):
    sl = slices if slices is not None else SPLIT["slices"]
    return decision(choice, {"decision": choice, "slices": sl, "reason": "two PRs"}, by="judge:opus")


class Single(unittest.TestCase):
    def test_single_pr_advances_with_specs_and_output(self):
        h = design_h(self, roles=[tester_ok(self, (1, 2), visual=True), techlead_ok(self), spec_ok(self)])
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.ADVANCE)
        self.assertEqual(r.nxt, "execute")
        self.assertIn("guild:execute", h.labels())
        self.assertEqual(h.specs(), ["skeleton.md", "split.json", "test-cases.md", "ux.md"])
        out = h.body_with("design:output")
        for line in ("분할: 없음 — 단일 PR", "skeleton: docs/specs/7/skeleton.md", "visual: yes", "시각 케이스 1건",
                     "spec: docs/specs/7/ux.md", "- designer (게이트): DONE"):
            self.assertIn(line, out)
        order = [(c.role, c.task) for c in h.calls["roles"]]
        self.assertEqual(order, [("tester", "cases"), ("tech-lead", "design"), ("designer", "design")])
        tin = h.calls["roles"][0].inputs
        self.assertEqual(sorted(tin), ["ac.md", "visual.txt"])                 # the tester sees only the AC
        self.assertIn("VISUAL = yes", tin["visual.txt"]["text"])

    def test_no_ui_surface_no_visual_no_designer(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self)])
        self.assertEqual(D.run(h.p).kind, StageResult.ADVANCE)
        self.assertIn("visual: no", h.body_with("design:output"))
        self.assertEqual(len(h.calls["roles"]), 2)

    def test_needs_context_without_analyze_output(self):
        h = K4(self, labels=("guild:design",))
        r = D.run(h.p)
        self.assertEqual(r.fail_class, "needs_context")
        self.assertEqual(r.token(), "NEEDS_CONTEXT: analyze output not found for #7")
        self.assertIn("guild:design", h.labels())

    def test_visual_outside_packages_is_no(self):
        kick = {"ui_surface": "true", "areas": "lib/other", "safety_net_visual": "false"}

        class B(dict):
            def get(self, k, d=None):
                return dict.get(self, k, d)
        self.assertEqual(D.visual_decision(VCFG, B(kick), [])[0], False)
        self.assertEqual(D.visual_decision(dict(VCFG, visual={"runnable": False}), B(kick), [])[0], False)
        self.assertEqual(D.visual_decision(VCFG, B(dict(kick, safety_net_visual="true")), [])[0], True)


class Contracts(unittest.TestCase):
    def test_missing_ac_repaired_once(self):
        h = design_h(self, cast="", ui="false",
                     roles=[tester_ok(self, (1,)), tester_ok(self, (1, 2)), techlead_ok(self)])
        self.assertEqual(D.run(h.p).kind, StageResult.ADVANCE)
        self.assertIn("does not name AC #2", h.calls["roles"][1].addendum)

    def test_still_failing_goes_to_handoff_then_a_person(self):
        gap = decision("upstream_gap", {"verdict": "upstream_gap", "reason": "AC 2 has no case", "fixable_by_execute": False})
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1,)), tester_ok(self, (1,))],
                     judges={"HANDOFF": gap})
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("design 산출물 간극(tester)", r.cause)
        self.assertEqual(h.decisions_of("HANDOFF")[0].get("boundary"), "design→execute")
        self.assertIn("guild:design", h.labels())

    def test_handoff_ok_with_assumption_records_it(self):
        ok = decision("ok_with_assumption", {"verdict": "ok_with_assumption", "line": "AC 2 is covered by C1"})
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1,)), tester_ok(self, (1,)), techlead_ok(self)],
                     judges={"HANDOFF": ok})
        self.assertEqual(D.run(h.p).kind, StageResult.ADVANCE)
        self.assertIn("- 가정: AC 2 is covered by C1", h.body_with("design:output"))

    def test_artifact_outside_out_refused(self):
        secret = os.path.join(_tmp(self), "s.md")
        with open(secret, "w") as fh:
            fh.write("| C1 | AC #1 |\n| C2 | AC #2 | SECRET\n")
        bad = out_role(self, "DONE", links={"test-cases.md": secret})
        h = design_h(self, cast="", ui="false", roles=[bad, tester_ok(self, (1, 2)), techlead_ok(self)])
        self.assertEqual(D.run(h.p).kind, StageResult.ADVANCE)
        self.assertNotIn("SECRET", h.spec("test-cases.md"))
        self.assertTrue(h.decisions_of("role-path-refused"))

    def test_design_to_execute_contract(self):
        self.assertEqual(HO.design_to_execute("# S\nx", cases_md((1, 2)), [1, 2], False), [])
        self.assertIn("skeleton.md has no section heading", HO.design_to_execute("plain", cases_md((1,)), [1], False))
        self.assertIn("VISUAL=yes but no visual-cases marker", HO.design_to_execute("# S", cases_md((1,)), [1], True))


def _tmp(case):
    from _k1 import tmpdir
    return tmpdir(case)


class Arbitration(unittest.TestCase):
    def test_blocked_tech_lead_reinvoked_once_with_addendum(self):
        arb = decision("reinvoke", {"action": "reinvoke", "role": "tech-lead", "addendum": "use lib/app only"})
        h = design_h(self, cast="", ui="false",
                     roles=[tester_ok(self, (1, 2)), out_role(self, "BLOCKED", "which module?", evidence="none"), techlead_ok(self)],
                     judges={"DE-ARB": arb})
        self.assertEqual(D.run(h.p).kind, StageResult.ADVANCE)
        self.assertEqual(h.calls["roles"][2].addendum, "use lib/app only")

    def test_second_block_after_reinvoke_goes_to_a_person(self):
        arb = decision("reinvoke", {"action": "reinvoke", "role": "tech-lead", "addendum": "x"})
        h = design_h(self, cast="", ui="false",
                     roles=[tester_ok(self, (1, 2)), out_role(self, "BLOCKED", "a", evidence="e"),
                            out_role(self, "BLOCKED", "b", evidence="e")], judges={"DE-ARB": [arb, arb]})
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("설계 막힘(tech-lead)", r.cause)

    def test_decide_unattended_needs_stakes(self):
        arb = decision("decide", {"action": "decide", "assumption": "keep one module"})
        st = decision("high", {"level": "high"})
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), out_role(self, "NEEDS_CONTEXT", "?")],
                     judges={"DE-ARB": arb, "STAKES": st})
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("stakes high", r.cause)

    def test_reinvoke_without_addendum_is_pause(self):
        arb = decision("reinvoke", {"action": "reinvoke", "role": "tech-lead"})
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), out_role(self, "BLOCKED", "?", evidence="e")],
                     judges={"DE-ARB": arb})
        self.assertEqual(D.run(h.p).kind, StageResult.PAUSE)


class Split(unittest.TestCase):
    def test_split_creates_children_then_flips_then_roster(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.SPLIT)
        self.assertEqual(r.token(), "OK SPLIT: 2 children")
        self.assertIn("guild:children", h.labels())
        self.assertNotIn("guild:design", h.labels())
        kids = [h.gh.fx["issues"][k] for k in sorted(h.gh.fx["issues"], key=int) if int(k) > 7]
        self.assertEqual([k["title"] for k in kids], ["[Guild子] data layer", "[Guild子] screen"])
        self.assertEqual(sorted(l["name"] for l in kids[0]["labels"]), ["guild:analyze", "guild:child"])
        self.assertIn("Parent Issue: #7", kids[1]["body"])
        self.assertNotIn("Parent Issue: #999", kids[1]["body"])            # the scope cannot add a parent
        self.assertIn("<!-- guild:slice-key 7-ui -->", kids[1]["body"])
        self.assertIn("- AC #2: settings stay", kids[1]["body"])
        ops = [c[0] for c in h.w.calls]
        flip = [i for i, c in enumerate(h.w.calls) if c[0] == "edit_labels" and "guild:children" in c[2]][0]
        creates = [i for i, o in enumerate(ops) if o == "create_issue"]
        self.assertLess(max(creates), flip)
        design_out = [i for i, c in enumerate(h.w.calls) if c[0] == "create_comment"]
        self.assertTrue(h.body_with("children:output"))
        self.assertIn("분할: 2개 자식 — #8, #9", h.body_with("design:output"))

    def test_resume_creates_only_missing_keys(self):
        existing = {"8": {"number": 8, "title": "[Guild子] data layer", "state": "OPEN",
                          "body": "x\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-data -->\n",
                          "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}], "comments": []}}
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()}, issues=existing)
        r = D.run(h.p)
        self.assertEqual(r.token(), "OK SPLIT: 2 children")
        self.assertEqual([c for c in h.w.calls if c[0] == "create_issue"], [("create_issue", "[Guild子] screen")])
        self.assertIn("existing-children.md", h.calls["roles"][1].inputs)
        self.assertIn("#8 [Guild子] data layer", h.calls["roles"][1].inputs["existing-children.md"]["text"])

    def test_leaf_cannot_resplit(self):
        h = design_h(self, cast="", ui="false", labels=("guild:design", "guild:child"),
                     roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)], judges={"SPLIT": split_dec()})
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("child #7 cannot be re-split", r.cause)
        self.assertEqual([c for c in h.w.calls if c[0] == "create_issue"], [])

    def test_slices_must_cover_every_ac(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec(SPLIT["slices"][:1] + [dict(SPLIT["slices"][1], ac_ids=[])])})
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("분할 판단 불확실", r.cause)

    def test_split_judge_single_overrides_role(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec([], "single")})
        self.assertEqual(D.run(h.p).kind, StageResult.ADVANCE)
        self.assertIn("guild:execute", h.labels())

    def test_child_creation_failure_stops_before_flip(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        orig = h.w.create_issue
        calls = {"n": 0}

        def flaky(title, body, labels=()):
            calls["n"] += 1
            if calls["n"] == 2:
                from guildcore.adapters.gh import GhError
                raise GhError("HTTP 422: Validation Failed")
            return orig(title, body, labels)
        h.w.create_issue = flaky
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.FAIL)
        self.assertIn("child creation failed after 1/2", r.line)
        self.assertIn("guild:design", h.labels())
        self.assertIsNone(h.body_with("children:output"))


if __name__ == "__main__":
    unittest.main()
