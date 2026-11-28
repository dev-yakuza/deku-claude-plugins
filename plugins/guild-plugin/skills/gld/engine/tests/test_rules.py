"""U11 mandatory rules on the actual changed files (scope §5.2 V1, V2 — unit part; V3/V4 in test_driver)."""

import copy
import os
import unittest

from gxengine import catalog, codes, instructions, procedure as procmod, repoconfig, rules, schema, store
from tests import c_world as W

SHA = "b" * 40
ISSUE = 42
SPECS = f"docs/specs/{ISSUE}"


def cfg(path_rules=None, commands=None):
    c = W.config()
    if path_rules is not None:
        c["path_rules"] = path_rules
    if commands is not None:
        c["commands"] = commands
    return repoconfig.RepoConfig(c)


def build(steps=None, config=None):
    config = config or cfg()
    proc = procmod.build(instructions.load_start_procedure(stage=1), W.template(steps), ISSUE, config.command_names())
    state = store.new_state(ISSUE, proc.revision, proc.step_ids, SHA)
    return proc, state, config


def sstep(state, sid):
    return next(s for s in state["steps"] if s["id"] == sid)


RISK = [{"kind": "verification", "globs": ["tests/**"]},
        {"kind": "risk", "area": "auth", "gate": "security-review", "globs": ["src/auth/**"]}]


class Basics(unittest.TestCase):
    def test_is_code_path(self):
        self.assertFalse(rules.is_code_path(f"{SPECS}/analysis.md", ISSUE))
        self.assertTrue(rules.is_code_path("docs/specs/41/analysis.md", ISSUE))
        self.assertTrue(rules.is_code_path("docs/guide.md", ISSUE))
        self.assertTrue(rules.is_code_path(f"{SPECS}x/a", ISSUE))
        with self.assertRaises(ValueError):
            rules.is_code_path("", ISSUE)

    def test_no_code_change_needs_nothing(self):
        proc, state, config = build()
        sup = rules.evaluate(proc, state, config, [f"{SPECS}/analysis.md"], ISSUE)
        self.assertFalse(sup.changes_anything)
        self.assertEqual(sup.unfillable, [])

    def test_clean_code_change_needs_nothing(self):
        proc, state, config = build()
        sup = rules.evaluate(proc, state, config, ["src/app.py"], ISSUE)
        self.assertFalse(sup.changes_anything)
        self.assertEqual(sup.unfillable, [])
        self.assertEqual(sup.changed_verification, [])

    def test_code_change_without_a_verification_run_is_unfillable(self):
        steps = [s for s in W.template()["steps"] if s["id"] != "test"]
        proc, state, config = build(steps)
        sup = rules.evaluate(proc, state, config, ["src/app.py"], ISSUE)
        self.assertEqual(len(sup.unfillable), 1)
        self.assertIn("verification run", sup.unfillable[0])

    def test_plugin_command_runs_do_not_count_as_verification(self):
        steps = [s for s in W.template()["steps"] if s["id"] != "test"]
        steps.insert(1, {"id": "gate", "run": "verify-gate"})
        c = W.config()
        c["commands"]["verify-gate"] = {"plugin": "verify-gate"}
        proc, state, config = build(steps, repoconfig.RepoConfig(c))
        sup = rules.evaluate(proc, state, config, ["src/app.py"], ISSUE)
        self.assertTrue(any("verification run" in u for u in sup.unfillable))

    def test_code_change_without_a_review_is_unfillable(self):
        steps = [s for s in W.template()["steps"] if s["id"] != "review"]
        proc, state, config = build(steps)
        sup = rules.evaluate(proc, state, config, ["src/app.py"], ISSUE)
        self.assertTrue(any("review step" in u for u in sup.unfillable))
        with self.assertRaises(ValueError):
            rules.apply(proc, state, sup)


class V1TestChangeReview(unittest.TestCase):
    def test_verification_path_adds_the_check_and_resets_a_done_review(self):
        proc, state, config = build()
        sstep(state, "review")["status"] = "done"
        sup = rules.evaluate(proc, state, config, ["src/app.py", "tests/test_app.py"], ISSUE)
        self.assertEqual(sup.add_checks, {"review": [rules.TEST_CHANGE_REVIEW]})
        self.assertEqual(sup.reset, ["review"])
        self.assertEqual(sup.changed_verification, ["tests/test_app.py"])
        new, events = rules.apply(proc, state, sup)
        self.assertIs(new, proc)                       # no structure change, no new revision
        self.assertEqual(sstep(state, "review")["added_checks"], [rules.TEST_CHANGE_REVIEW])
        self.assertEqual(sstep(state, "review")["status"], "pending")
        self.assertEqual(events[0][0], codes.LogEvent.RULE_SUPPLEMENT.value)
        self.assertIn((codes.LogEvent.STATUS.value), [e for e, _ in events])
        schema.validate(state, "state")            # the state stays schema-valid
        allc, added = rules.step_checks(proc.step("review"), sstep(state, "review"))
        self.assertEqual(allc, ["test-quality", rules.TEST_CHANGE_REVIEW])
        self.assertEqual(added, [rules.TEST_CHANGE_REVIEW])

    def test_idempotent(self):
        proc, state, config = build()
        sstep(state, "review")["status"] = "done"
        sup = rules.evaluate(proc, state, config, ["tests/test_app.py"], ISSUE)
        rules.apply(proc, state, sup)
        sstep(state, "review")["status"] = "done"     # the review ran again with the check
        again = rules.evaluate(proc, state, config, ["tests/test_app.py"], ISSUE)
        self.assertFalse(again.changes_anything)
        self.assertEqual(again.changed_verification, ["tests/test_app.py"])

    def test_pending_review_is_not_reset(self):
        proc, state, config = build()
        sup = rules.evaluate(proc, state, config, ["tests/test_app.py"], ISSUE)
        self.assertEqual(sup.add_checks, {"review": [rules.TEST_CHANGE_REVIEW]})
        self.assertEqual(sup.reset, [])

    def test_the_check_goes_to_the_tester_review_first(self):
        steps = W.template()["steps"]
        lead = {"id": "review-design", "role": "tech-lead", "inputs": ["in:review.diff"], "outputs": [],
                "checks": ["design-conformance"], "on_fail": {"back_to": "implement", "max": 2}}
        steps.insert(2, lead)
        proc, state, config = build(steps)
        sup = rules.evaluate(proc, state, config, ["tests/test_app.py"], ISSUE)
        self.assertEqual(list(sup.add_checks), ["review"])
        no_tester = [s for s in steps if s["id"] != "review"]
        proc, state, config = build(no_tester)
        sup = rules.evaluate(proc, state, config, ["tests/test_app.py"], ISSUE)
        self.assertEqual(list(sup.add_checks), ["review-design"])

    def test_check_already_in_the_template_is_not_added(self):
        steps = W.template()["steps"]
        steps[2]["checks"] = ["test-quality", rules.TEST_CHANGE_REVIEW]
        proc, state, config = build(steps)
        sstep(state, "review")["status"] = "done"
        sup = rules.evaluate(proc, state, config, ["tests/test_app.py"], ISSUE)
        self.assertFalse(sup.changes_anything)


class V2RiskGate(unittest.TestCase):
    def test_gate_without_an_available_role_is_unfillable(self):
        proc, state, config = build(config=cfg(RISK))
        sup = rules.evaluate(proc, state, config, ["src/auth/login.py"], ISSUE)
        self.assertEqual(len(sup.unfillable), 1)
        self.assertIn("security-review", sup.unfillable[0])
        self.assertIn("security", sup.unfillable[0])

    def test_unknown_gate_is_unfillable(self):
        r = [{"kind": "risk", "area": "data", "gate": "dba-review", "globs": ["migrations/**"]}]
        proc, state, config = build(config=cfg(r))
        sup = rules.evaluate(proc, state, config, ["migrations/1.sql"], ISSUE, roles_available={"dba"})
        self.assertIn("not a plugin gate definition", sup.unfillable[0])

    def test_gate_is_inserted_before_the_pr_with_a_new_revision(self):
        proc, state, config = build(config=cfg(RISK))
        sup = rules.evaluate(proc, state, config, ["src/auth/login.py"], ISSUE, roles_available={"security"})
        self.assertEqual(sup.unfillable, [])
        self.assertEqual([s["id"] for s in sup.insert_steps], ["security-review"])
        self.assertEqual(sup.insert_steps[0]["on_fail"], {"back_to": "implement", "max": 2})
        new, events = rules.apply(proc, state, sup, commands=config.command_names())
        self.assertEqual(new.revision, proc.revision + 1)
        self.assertEqual(new.step_ids[-2:], ["security-review", "pr"])
        self.assertEqual([s["id"] for s in state["steps"]], new.step_ids)
        self.assertEqual(state["revision"], new.revision)
        self.assertEqual(sstep(state, "security-review")["status"], "pending")
        self.assertEqual(events[0][1]["data"]["revision"], new.revision)
        # a second evaluation against the new procedure inserts nothing
        again = rules.evaluate(new, state, config, ["src/auth/login.py"], ISSUE, roles_available={"security"})
        self.assertFalse(again.changes_anything)

    def test_gate_in_the_template_is_enough(self):
        steps = W.template()["steps"]
        steps.insert(3, {"id": "security-review", "role": "tester", "inputs": ["in:review.diff"], "outputs": [],
                         "checks": ["security"], "on_fail": {"back_to": "implement", "max": 2}})
        proc, state, config = build(steps, cfg(RISK))
        sup = rules.evaluate(proc, state, config, ["src/auth/login.py"], ISSUE)
        self.assertFalse(sup.changes_anything)
        self.assertEqual(sup.unfillable, [])

    def test_judgment_documents_alone_trigger_no_gate(self):
        proc, state, config = build(config=cfg(RISK + [{"kind": "risk", "area": "docs", "gate": "security-review",
                                                        "globs": ["docs/**"]}]))
        sup = rules.evaluate(proc, state, config, [f"{SPECS}/analysis.md"], ISSUE)
        self.assertEqual(sup.unfillable, [])


class Stage3Gates(unittest.TestCase):
    """E14 · E15 · E25: the gates come from the step catalog and take its positions (TI5)."""

    RISK3 = RISK + [{"kind": "risk", "area": "data", "gate": "data-review", "globs": ["migrations/**"]}]

    def setUp(self):
        self.cat = catalog.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "procedure", "catalog.json"))
        c = W.config({"path_rules": self.RISK3})
        self.config = repoconfig.RepoConfig(c)
        self.cmds = self.config.command_names()
        # the stage-2 view of the start procedure: test_earlier_stages_keep_their_gate_table applies it at stage 2
        start = procmod.build_start(instructions.load_start_procedure(stage=2), ISSUE, self.cmds, stage=3)
        self.proc = procmod.attach_template(start, W.template(self.steps()), self.cmds, stage=3)
        self.state = store.new_state(ISSUE, self.proc.revision, self.proc.step_ids, SHA)
        self.done("implement")

    def steps(self):
        steps = W.stage2_steps()
        steps.insert(3, {"id": "review-audit", "role": "auditor", "inputs": ["in:review.diff"], "outputs": [],
                         "checks": ["diff-review"], "on_fail": {"back_to": "implement", "max": 2}})
        return steps

    def done(self, sid):
        for s in self.state["steps"]:
            s["status"] = "done"
            if s["id"] == sid:
                return

    def evaluate(self, paths, roles=("security", "dba"), proc=None):
        return rules.evaluate(proc or self.proc, self.state, self.config, paths, ISSUE, set(roles), stage=3, catalog=self.cat)

    def apply(self, sup):
        new, events = rules.apply(self.proc, self.state, sup, commands=self.cmds, stage=3)
        schema.validate(dict(self.state), "state")
        return new, events

    def test_gate_goes_before_the_first_review_after_the_developer(self):
        sup = self.evaluate(["src/auth/login.py"])
        self.assertEqual(sup.unfillable, [])
        new, events = self.apply(sup)
        ids = new.step_ids
        self.assertEqual(ids[ids.index("security-review") + 1], "review")
        self.assertEqual([s["id"] for s in self.state["steps"]], ids)
        self.assertEqual(new.step("security-review").on_fail, {"back_to": "implement", "max": 2})
        self.assertEqual(self.state["catalog_adds"],
                         [{"step": "security-review", "source": "mandatory-rule", "from_step": None, "revision": new.revision}])
        self.assertEqual(events[0][1]["data"]["insert_at"], sup.insert_at)
        self.assertFalse(self.evaluate(["src/auth/login.py"], proc=new).changes_anything, "idempotent")

    def test_gate_after_every_review_is_right_before_the_done_gate(self):
        self.done("review-audit")
        new, _ = self.apply(self.evaluate(["src/auth/login.py"]))
        ids = new.step_ids
        self.assertEqual(ids[ids.index("security-review") + 1], "done-gate")
        # the done-gate itself already open: still in front of it
        self.assertEqual(sstep(self.state, "security-review")["status"], "pending")

    def test_open_done_gate(self):
        self.done("done-gate")
        new, _ = self.apply(self.evaluate(["src/auth/login.py"]))
        self.assertLess(new.index("security-review"), new.index("done-gate"))

    def test_two_gates_one_revision_rule_order(self):
        sup = self.evaluate(["migrations/1.sql", "src/auth/login.py"])
        new, _ = self.apply(sup)
        self.assertEqual(new.revision, self.proc.revision + 1)
        i = new.index("security-review")
        self.assertEqual(new.step_ids[i:i + 2], ["security-review", "data-review"])
        self.assertEqual(len(self.state["catalog_adds"]), 2)

    def test_the_limit_never_blocks_a_gate(self):
        self.state["catalog_adds"] = [{"step": f"x{n}", "source": "role-request", "from_step": "design", "revision": 2}
                                      for n in range(5)]
        self.assertEqual([s["id"] for s in self.evaluate(["src/auth/a.py"]).insert_steps], ["security-review"])

    def test_a_requested_gate_becomes_mandatory(self):
        """TC8 · §7: the leader may have added the gate, and even skipped it — the rule stands."""
        i = self.proc.index("review")
        raw = catalog.insert(self.proc, [(i, catalog.expand(self.cat["security-review"], ISSUE, "implement"),
                                          self.cat["security-review"])])
        self.proc = procmod.with_revision(self.proc, raw)
        self.state = store.new_state(ISSUE, self.proc.revision, self.proc.step_ids, SHA)
        self.done("implement")
        for status in ("pending", "skipped"):
            with self.subTest(status=status):
                self.state["catalog_adds"] = [{"step": "security-review", "source": "role-request", "from_step": "implement",
                                               "revision": 3}]
                sstep(self.state, "security-review").update(status=status, reason="leader-skip" if status == "skipped" else None)
                self.assertFalse(self.evaluate(["src/app.py"]).changes_anything, "no risk path: the skip holds")
                sup = self.evaluate(["src/auth/a.py"])
                self.assertEqual((sup.pin, sup.insert_steps, sup.unfillable), (["security-review"], [], []))
                self.assertEqual(sup.reset, ["security-review"] if status == "skipped" else [])
                new, events = self.apply(sup)
                self.assertIs(new, self.proc)
                self.assertEqual(self.state["catalog_adds"][0]["source"], "mandatory-rule")
                self.assertEqual(sstep(self.state, "security-review")["status"], "pending")
                self.assertIsNone(sstep(self.state, "security-review")["reason"])
                self.assertEqual(catalog.skippable_steps(new, {}, self.state["catalog_adds"],
                                                         [{"op": "skip", "step": "security-review"}]), [])
                self.assertFalse(self.evaluate(["src/auth/a.py"]).changes_anything, "idempotent")
        # a template step with a catalog id is simply there (K4)
        self.state["catalog_adds"] = []
        self.assertFalse(self.evaluate(["src/auth/a.py"]).changes_anything)

    def test_unfillable(self):
        self.assertIn("needs role", self.evaluate(["src/auth/a.py"], roles=()).unfillable[0])
        only_fix = dict(self.cat)
        only_fix["security-review"] = self.cat["fix-discovery"]           # not a diff-review entry
        sup = rules.evaluate(self.proc, self.state, self.config, ["src/auth/a.py"], ISSUE, {"security", "developer"},
                             stage=3, catalog=only_fix)
        self.assertIn("not a plugin gate definition", sup.unfillable[0])
        del only_fix["security-review"]
        sup = rules.evaluate(self.proc, self.state, self.config, ["src/auth/a.py"], ISSUE, {"security"}, stage=3, catalog=only_fix)
        self.assertIn("not a plugin gate definition", sup.unfillable[0])

    def test_developer_step_ignores_catalog_steps(self):
        """D4: with fix-discovery in front of the review the gate still goes back to implement."""
        i = self.proc.index("implement") + 1
        raw = catalog.insert(self.proc, [(i, catalog.expand(self.cat["fix-discovery"], ISSUE, "implement"), self.cat["fix-discovery"])])
        self.proc = procmod.with_revision(self.proc, raw)
        self.state = store.new_state(ISSUE, self.proc.revision, self.proc.step_ids, SHA)
        self.state["catalog_adds"] = [{"step": "fix-discovery", "source": "blocking-discovery", "from_step": "implement", "revision": 3}]
        self.done("fix-discovery")
        self.assertEqual(self.evaluate(["src/auth/a.py"]).insert_steps[0]["on_fail"]["back_to"], "implement")

    def test_catalog_reviews_do_not_fill_the_review_rules(self):
        """A leader may skip a catalog review (E13), so it never carries a mandatory rule alone."""
        i = self.proc.index("review")
        raw = catalog.insert(self.proc, [(i, catalog.expand(self.cat["ux-review"], ISSUE, "implement"), self.cat["ux-review"])])
        raw = [s for s in raw if s["id"] not in ("review", "review-audit")]
        self.proc = procmod.with_revision(self.proc, raw)
        self.state = store.new_state(ISSUE, self.proc.revision, self.proc.step_ids, SHA)
        self.state["catalog_adds"] = [{"step": "ux-review", "source": "role-request", "from_step": "implement", "revision": 3}]
        self.done("implement")
        sup = self.evaluate(["src/app.py", "tests/a.py"])
        self.assertTrue(any("no review step" in u for u in sup.unfillable))
        self.assertEqual(sup.add_checks, {})

    def test_earlier_stages_keep_their_gate_table(self):
        state = copy.deepcopy(self.state)
        sup = rules.evaluate(self.proc, state, self.config, ["migrations/1.sql"], ISSUE, {"dba"}, stage=2)
        self.assertIn("not a plugin gate definition", sup.unfillable[0])
        sup = rules.evaluate(self.proc, state, self.config, ["src/auth/a.py"], ISSUE, {"security"}, stage=2)
        self.assertNotIn("insert_at", sup.to_json())
        new, _ = rules.apply(self.proc, state, sup, commands=self.cmds, stage=2)
        self.assertEqual(new.step_ids[new.index("security-review") + 1], "done-gate")
        self.assertNotIn("catalog_adds", state)
        for bad in (0, True, "3"):
            with self.assertRaises(ValueError):
                rules.evaluate(self.proc, state, self.config, [], ISSUE, stage=bad)


if __name__ == "__main__":
    unittest.main()
