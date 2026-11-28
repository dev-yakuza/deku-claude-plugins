"""The plugin start procedure and the default feature template (U15 — design §2.1, §3.1).

They must pass the template schema and the grammar checks the U3 checker applies
(procedure.py: unique ids, back_to earlier-or-self, run names in the repository settings,
stage-1 ops, judge outputs that do not overlap, `in:` inputs from the allowed set). The U3
checker itself is run too once it exists (these tests skip that part while it is a stub)."""

import re
import unittest

from gxengine import codes, instructions, procedure

# The named commands a repository's settings must define for the plugin default template:
# the repository's own (setup … e2e) plus the plugin commands (codes.PluginCommand).
REPO_COMMANDS = ("setup", "lint", "typecheck", "test", "build", "e2e")
COMMANDS = set(REPO_COMMANDS) | set(codes.PluginCommand.values())

KNOWN_ROLES = {"requirements-engineer", "tester", "tech-lead", "developer", "auditor", "qa"}
STAGE1_JUDGE_REVIEW_CHECKS = set(instructions.CHECK_CATALOG) - set(codes.RequiredCheck.values())


def steps(doc):
    return doc["steps"]


def kind_of(step):
    for k in ("role", "run", "check", "op"):
        if k in step:
            return k
    raise AssertionError(step)


class Both(unittest.TestCase):
    """Start procedure + feature template as the engine copies them into procedure.yaml."""

    @classmethod
    def setUpClass(cls):
        cls.start = instructions.load_start_procedure(stage=1)          # the stage-1 view (ENGINE_STAGE is 3)
        cls.feature = instructions.load_default_template("feature", stage=1)
        cls.all = steps(cls.start) + steps(cls.feature)


class Grammar(Both):
    def test_ids_are_unique_across_both_files(self):
        ids = [s["id"] for s in self.all]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_back_to_names_an_earlier_step_or_itself(self):
        order = {s["id"]: i for i, s in enumerate(self.all)}
        for i, s in enumerate(self.all):
            if "on_fail" in s:
                with self.subTest(step=s["id"]):
                    self.assertIn(s["on_fail"]["back_to"], order)
                    self.assertLessEqual(order[s["on_fail"]["back_to"]], i)

    def test_run_names_are_resolvable(self):
        for s in self.all:
            if "run" in s:
                with self.subTest(step=s["id"]):
                    self.assertIn(s["run"], COMMANDS)

    def test_plugin_commands_are_all_used(self):
        used = {s["run"] for s in self.all if "run" in s}
        # the stage-3 plugin commands belong to the stage-3 templates (session A, V4 / V5)
        self.assertEqual(set(codes.STAGE2_PLUGIN_COMMANDS) - used, set())

    def test_ops_are_stage1_ops(self):
        for s in self.all:
            if "op" in s:
                self.assertIn(s["op"], codes.STAGE1_OPS)
        self.assertEqual([s["op"] for s in self.all if "op" in s], ["create-pr"])
        self.assertEqual(self.all[-1]["op"], "create-pr")

    def test_checks_are_the_stage1_machine_rule_only(self):
        self.assertEqual([s["check"] for s in self.all if "check" in s], ["plan-gate"])

    def test_roles_are_the_known_set(self):
        self.assertEqual({s["role"] for s in self.all if "role" in s}, KNOWN_ROLES)

    def test_no_forbidden_keys(self):
        allowed = {"id", "role", "run", "check", "op", "inputs", "outputs", "on_fail", "checks"}
        for s in self.all:
            self.assertFalse(set(s) - allowed, s)

    def test_on_fail_limits(self):
        for s in self.all:
            if "on_fail" in s:
                self.assertTrue(1 <= s["on_fail"]["max"] <= 10)

    def test_run_steps_have_no_outputs_or_checks(self):
        for s in self.all:
            if "run" in s:
                self.assertFalse({"outputs", "checks"} & set(s), s["id"])

    def test_inputs_in_files_are_the_allowed_set(self):
        allowed = {"in:" + v for v in codes.InFile.values()}
        for s in self.all:
            for i in s.get("inputs", []):
                if i.startswith("in:"):
                    with self.subTest(step=s["id"], input=i):
                        self.assertIn(i, allowed)

    def test_outputs_do_not_overlap_and_live_in_the_specs_folder(self):
        seen = {}
        for s in self.all:
            for o in s.get("outputs", []):
                with self.subTest(step=s["id"], output=o):
                    self.assertNotIn(o, seen)
                    seen[o] = s["id"]
                    self.assertTrue(o.startswith(codes_specs() + "/"), o)

    def test_placeholder_and_path_hygiene(self):
        for s in self.all:
            for p in s.get("inputs", []) + s.get("outputs", []):
                if p.startswith("in:"):
                    continue
                with self.subTest(step=s["id"], path=p):
                    self.assertNotIn("..", p)
                    self.assertFalse(re.search(r"\s", p))
                    self.assertNotIn("{", p.replace("{issue}", ""))

    def test_review_steps_have_known_check_ids_and_no_outputs_except_qa(self):
        for s in self.all:
            if s.get("checks"):
                with self.subTest(step=s["id"]):
                    self.assertEqual(kind_of(s), "role")
                    self.assertTrue(set(s["checks"]) <= STAGE1_JUDGE_REVIEW_CHECKS, s["checks"])
                    self.assertEqual(s["outputs"] == [], s["id"] != "qa")
                    self.assertIn("in:review.diff", s["inputs"])

    def test_the_developer_is_the_only_work_role_and_has_no_declared_outputs(self):
        for s in self.all:
            if s.get("role") == "developer":
                self.assertEqual(s["outputs"], [])
                self.assertEqual(codes.role_class("developer"), "work")
        self.assertEqual({r for r in KNOWN_ROLES if codes.role_class(r) == "work"}, {"developer"})

    def test_failure_summary_goes_to_the_developer_only(self):
        for s in self.all:
            if "in:failure-summary.md" in s.get("inputs", []):
                self.assertEqual(s["role"], "developer")

    def test_data_flow_every_spec_input_is_produced_earlier(self):
        produced = set()
        for s in self.all:
            for i in s.get("inputs", []):
                if i.startswith("in:"):
                    continue
                with self.subTest(step=s["id"], input=i):
                    self.assertIn(i, produced)
            produced.update(s.get("outputs", []))

    def test_every_role_step_has_a_task_and_every_plugin_role_a_default(self):
        for s in self.all:
            if "role" in s:
                self.assertTrue(instructions.task_text(s["id"]), s["id"])
        for role in instructions.PLUGIN_ROLES:
            self.assertTrue(instructions.default_role_file(role))


def codes_specs():
    from gxengine import defaults
    return defaults.SPECS_DIR


class Shape(Both):
    """The step list a human reviews (scope Q11) — pinned so a change is a visible diff."""

    def test_start_procedure(self):
        self.assertEqual([(kind_of(s), s["id"]) for s in steps(self.start)],
                         [("role", "analyze"), ("run", "ac-format"), ("check", "plan")])
        ac = steps(self.start)[1]
        self.assertEqual(ac["on_fail"], {"back_to": "analyze", "max": 2})       # §3.1, plugin-fixed

    def test_feature_template_order(self):
        self.assertEqual([s["id"] for s in steps(self.feature)], [
            "test-cases", "ac-coverage", "design", "setup", "implement", "lint", "typecheck", "test",
            "build", "e2e", "review-design", "review-tests", "review-audit", "qa", "verify-gate", "pr"])

    def test_the_tester_writes_before_the_skeleton_exists(self):
        """Bias-free test design is structural: no skeleton.md yet when the tester runs."""
        ids = [s["id"] for s in steps(self.feature)]
        self.assertLess(ids.index("test-cases"), ids.index("design"))
        tester = steps(self.feature)[ids.index("test-cases")]
        self.assertFalse([i for i in tester["inputs"] if "skeleton" in i])

    def test_everything_after_implement_returns_to_implement(self):
        ids = [s["id"] for s in steps(self.feature)]
        for s in steps(self.feature)[ids.index("lint"):-1]:
            with self.subTest(step=s["id"]):
                self.assertEqual(s["on_fail"]["back_to"], "implement")

    def test_verify_gate_is_last_before_the_pr_and_after_the_reviews(self):
        ids = [s["id"] for s in steps(self.feature)]
        self.assertEqual(ids[-2:], ["verify-gate", "pr"])
        self.assertLess(ids.index("qa"), ids.index("verify-gate"))

    def test_setup_precedes_every_run_that_needs_the_toolchain(self):
        ids = [s["id"] for s in steps(self.feature)]
        for name in ("lint", "typecheck", "test", "build", "e2e"):
            self.assertLess(ids.index("setup"), ids.index(name))
        self.assertLess(ids.index("setup"), ids.index("implement"))

    def test_the_auditor_reviews_last_of_the_reviews(self):
        ids = [s["id"] for s in steps(self.feature)]
        self.assertLess(ids.index("review-tests"), ids.index("review-audit"))
        self.assertLess(ids.index("review-design"), ids.index("review-audit"))

    def test_qa_outputs_the_checklist_the_pr_step_reads(self):
        qa = next(s for s in steps(self.feature) if s["id"] == "qa")
        pr = next(s for s in steps(self.feature) if s["id"] == "pr")
        self.assertEqual(qa["outputs"], ["docs/specs/{issue}/manual-test-checklist.md"])
        self.assertIn(qa["outputs"][0], pr["inputs"])


class Stage2(Both):
    """The stage-2 view: the leader's done-gate right before the PR (scope D19, V8 template side)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.feature2 = instructions.load_default_template("feature", stage=2)
        cls.all2 = steps(cls.start) + steps(cls.feature2)

    def test_stage_one_view_is_the_stage_two_view_without_the_done_gate(self):
        self.assertEqual([s for s in steps(self.feature2) if s.get("check") != "done-gate"], steps(self.feature))
        self.assertEqual(self.feature["version"], self.feature2["version"])

    def test_default_stage_follows_the_engine_stage(self):
        from gxengine import defaults
        want = {1: self.feature, 2: self.feature2}.get(defaults.ENGINE_STAGE) or \
            instructions.load_default_template("feature", stage=defaults.ENGINE_STAGE)
        self.assertEqual(instructions.load_default_template("feature"), want)
        self.assertNotEqual(instructions.load_default_template("feature"), self.feature2)   # Q4: stage 3

    def test_one_done_gate_right_before_create_pr(self):
        ids = [s["id"] for s in steps(self.feature2)]
        self.assertEqual(ids[-3:], ["verify-gate", "done-gate", "pr"])
        gates = [s for s in steps(self.feature2) if s.get("check") == "done-gate"]
        self.assertEqual(len(gates), 1)
        self.assertEqual(steps(self.feature2)[-1].get("op"), "create-pr")
        self.assertEqual(steps(self.feature2)[-2]["check"], "done-gate")

    def test_checks_are_the_plan_gate_and_the_done_gate(self):
        self.assertEqual([s["check"] for s in self.all2 if "check" in s], ["plan-gate", "done-gate"])

    def test_done_gate_reads_what_the_leader_judges_and_writes_nothing(self):
        gate = next(s for s in steps(self.feature2) if s["id"] == "done-gate")
        self.assertEqual(set(gate) - {"id", "check", "inputs"}, set(), "no outputs, no on_fail: it writes no file (D26)")
        self.assertEqual(sorted(gate["inputs"]), sorted([
            "docs/specs/{issue}/analysis.md", "docs/specs/{issue}/test-cases.md",
            "docs/specs/{issue}/skeleton.md", "docs/specs/{issue}/manual-test-checklist.md",
            "in:review.diff", "in:leader-decision.md"]))

    def test_every_spec_input_is_produced_earlier_in_stage_two_too(self):
        produced = set()
        for s in self.all2:
            for i in s.get("inputs", []):
                if not i.startswith("in:"):
                    with self.subTest(step=s["id"], input=i):
                        self.assertIn(i, produced)
            produced.update(s.get("outputs", []))

    def test_the_run_names_are_the_stage_one_ones(self):
        self.assertEqual({s["run"] for s in steps(self.feature2) if "run" in s},
                         {s["run"] for s in steps(self.feature) if "run" in s})

    def test_stage_two_with_the_checker(self):
        import json
        try:
            procedure.parse_template("{}")
        except NotImplementedError:
            self.skipTest("procedure.py is still a stub (U3)")
        except Exception:
            pass
        procedure.parse_template(json.dumps(self.feature2), stage=2)
        p = procedure.build(self.start, self.feature2, 7, sorted(COMMANDS), stage=2)
        self.assertEqual(procedure.check(p, sorted(COMMANDS), stage=2), [])
        with self.assertRaises(procedure.ProcedureError):       # a stage-1 engine refuses it
            procedure.parse_template(json.dumps(self.feature2), stage=1)


class WithTheU3Checker(Both):
    """The real checker, when U3 has landed (skipped while procedure.py is a stub)."""

    def need_u3(self):
        try:
            procedure.parse_template("{}")
        except NotImplementedError:
            self.skipTest("procedure.py is still a stub (U3)")
        except Exception:
            pass

    def test_templates_parse(self):
        self.need_u3()
        import json
        for doc in (self.start, self.feature):
            procedure.parse_template(json.dumps(doc))

    def test_build_and_check(self):
        self.need_u3()
        p = procedure.build(self.start, self.feature, 7, sorted(COMMANDS))
        self.assertEqual(procedure.check(p, sorted(COMMANDS)), [])
        self.assertEqual(p.revision, 1)
        missing = procedure.check(p, [c for c in sorted(COMMANDS) if c != "e2e"])
        self.assertTrue(missing, "a repository without `e2e` must be told")


SPECS = "docs/specs/{issue}/"


def developer_index(steps):
    """E5 (+ D4 — a template has no catalog step): the last work-role step before the first review step."""
    first_review = next((i for i, s in enumerate(steps) if s.get("role") and s.get("checks")), len(steps))
    work = [i for i, s in enumerate(steps[:first_review]) if s.get("role") and codes.role_class(s["role"]) == "work"]
    return work[-1] if work else None


SAMPLE_PATH_GLOBS = {"test-code": ["test/**/*_test.dart", "integration_test/**/*_test.dart"],
                     "safety-net": ["test/**/*_safety_net_test.dart"]}


def expanded(doc, path_globs=SAMPLE_PATH_GLOBS):
    """`{path:<kind>}` items replaced as procedure.expand_paths does (session B1; its own once it exists)."""
    if hasattr(procedure, "expand_paths"):
        return procedure.expand_paths(doc, path_globs)
    import copy
    doc = copy.deepcopy(doc)
    for s in doc["steps"]:
        for key in ("inputs", "outputs"):
            if key in s:
                out = []
                for item in s[key]:
                    kind = next((k for k in codes.TEMPLATE_PATH_KINDS if item == codes.path_token(k)), None)
                    out += path_globs[kind] if kind else [item]
                s[key] = out
    return doc


PENDING_B1 = ("op create-pr must be the last step",)
"""procedure.check before session B1 adds the create-followups rule (V3): a stage-3 procedure ends with
create-followups, so this one error is expected until then."""


def pending_b1(error, doc):
    """True for an error the stage-3 procedure check (session B1) still has to settle:
      - PENDING_B1;
      - "output '<glob>' is a control file" for a glob that came from a `{path:<kind>}` item of a work
        step: globs.names_control_file refuses every glob with a `**` segment (it may be `.claude`), and
        a repository's test-code globs have one. The work step's outputs only fix ownership (E6, D2);
        its writes are bounded by the rendered boundary, which denies control files anyway. B1 decides
        (README "Stage 3 sessions", reported by session A)."""
    if error in PENDING_B1:
        return True
    expanded_globs = {g for gs in SAMPLE_PATH_GLOBS.values() for g in gs}
    return any(error == f"step {s['id']!r}: output {g!r} is a control file (§7.6)"
               for s in steps(doc) if codes.role_class(s.get("role") or "") == "work" for g in expanded_globs)


class Stage3Templates(unittest.TestCase):
    """The stage-3 view of the plugin templates (scope §2.2, §2.3, E1, E5, E20, Q8 carry-over ①)."""

    @classmethod
    def setUpClass(cls):
        cls.start = instructions.load_start_procedure(stage=3)
        cls.names = instructions.default_template_names(stage=3)
        cls.templates = {n: instructions.load_default_template(n, stage=3) for n in cls.names}

    def each(self):
        for name, doc in self.templates.items():
            with self.subTest(template=name):
                yield name, steps(doc), steps(self.start) + steps(doc)

    def test_names(self):
        self.assertTrue(set(self.names) <= set(codes.STAGE3_TEMPLATES))
        self.assertIn("feature", self.names)
        self.assertIn("bug", self.names)
        self.assertEqual(instructions.default_template_names(stage=2), ["feature"])
        for name in set(self.names) - {"feature"}:
            with self.assertRaises(KeyError):
                instructions.load_default_template(name, stage=2)

    def test_stage_1_2_views_are_what_they_were(self):
        """E36: an engine before stage 3 reads exactly the stage-2 files (Q8 ① only from stage 3)."""
        start2 = instructions.load_start_procedure(stage=2)
        self.assertEqual(steps(start2)[0]["inputs"], ["in:issue.md", "in:leader-decision.md"])
        self.assertEqual(instructions.load_start_procedure(stage=1), start2)
        f2 = {s["id"]: s for s in steps(instructions.load_default_template("feature", stage=2))}
        self.assertNotIn("followups", f2)
        self.assertEqual(f2["test-cases"]["inputs"], [SPECS + "analysis.md", "in:leader-decision.md"])
        self.assertEqual(f2["design"]["inputs"], [SPECS + "analysis.md", SPECS + "test-cases.md", "in:leader-decision.md"])
        self.assertEqual(f2["implement"]["inputs"], [SPECS + "analysis.md", SPECS + "skeleton.md", SPECS + "test-cases.md",
                                                     "in:failure-summary.md", "in:leader-decision.md"])
        self.assertEqual(instructions.load_start_procedure(), instructions.load_start_procedure(stage=defaults_stage()))

    def test_start_procedure_analyze_reads_the_failure_summary(self):
        self.assertEqual(steps(self.start)[0]["inputs"], ["in:issue.md", "in:git-history.md", "in:failure-summary.md",
                                                          "in:leader-decision.md"])           # readiness E4

    def test_ids_back_to_runs_ops(self):
        for name, own, everything in self.each():
            ids = [s["id"] for s in everything]
            self.assertEqual(len(ids), len(set(ids)))
            order = {i: n for n, i in enumerate(ids)}
            for i, s in enumerate(everything):
                if "on_fail" in s:
                    self.assertLessEqual(order[s["on_fail"]["back_to"]], i, s["id"])
                    self.assertTrue(1 <= s["on_fail"]["max"] <= 10)
                if "run" in s:
                    self.assertIn(s["run"], COMMANDS)
                    self.assertFalse({"outputs", "checks"} & set(s))
            self.assertEqual([(s["id"], s.get("op")) for s in own[-2:]], [("pr", "create-pr"), ("followups", "create-followups")])
            self.assertEqual(own[-3].get("check"), "done-gate")
            self.assertEqual([s["check"] for s in everything if "check" in s], ["plan-gate", "done-gate"])
            self.assertEqual([s["op"] for s in own if "op" in s], ["create-pr", "create-followups"])

    def test_role_steps(self):
        from gxengine import defaults
        me, budget = defaults.model_effort_table(3), defaults.session_budget_table(3)
        allowed_in = {"in:" + v for v in codes.InFile.values()}
        for name, own, everything in self.each():
            dev = developer_index(own)
            self.assertIsNotNone(dev)
            for i, s in enumerate(everything):
                if "role" not in s:
                    continue
                self.assertTrue(instructions.task_text(s["id"], stage=3).strip(), s["id"])
                self.assertIn("in:leader-decision.md", s["inputs"], s["id"])                 # §2.2 common rule
                key = f"{s['role']}/review" if s.get("checks") else f"{s['role']}/{s['id']}"
                self.assertTrue(key in me or s["role"] in me, key)
                self.assertIn(s["role"], budget)
                for i_ in s["inputs"]:
                    if i_.startswith("in:"):
                        self.assertIn(i_, allowed_in)
                if s.get("checks"):
                    self.assertIn("in:review.diff", s["inputs"])
                    self.assertTrue(set(s["checks"]) <= set(instructions.CHECK_CATALOG), s["checks"])
                    self.assertEqual(s["outputs"] == [], s["id"] != "qa")
                else:   # a writing step: a return or a rerun can target it (Q8 carry-over ①)
                    self.assertIn("in:failure-summary.md", s["inputs"], s["id"])
                if codes.role_class(s["role"]) == "work":
                    self.assertTrue(all(o.startswith("{path:") for o in s["outputs"]), s["id"])
                else:
                    self.assertTrue(all(o.startswith(SPECS) for o in s["outputs"]), s["id"])
            holders = [s["id"] for s in own if "in:blocking-discoveries.md" in s.get("inputs", [])]
            self.assertEqual(holders, [own[dev]["id"]], "E18: the developer step (E5) reads the blocking discoveries")
            for s in own[dev + 1:]:
                if "on_fail" in s and ("run" in s or s.get("checks")):
                    self.assertIn(s["on_fail"]["back_to"], [x["id"] for x in own[:dev + 1]], s["id"])

    def test_data_flow(self):
        for name, own, everything in self.each():
            produced = set()
            for s in everything:
                for i in s.get("inputs", []):
                    if not i.startswith("in:"):
                        self.assertIn(i, produced, (s["id"], i))
                produced.update(s.get("outputs", []))

    def test_with_the_checker(self):
        import json
        names = sorted(COMMANDS)
        for name, own, everything in self.each():
            doc = expanded(self.templates[name])
            procedure.parse_template(json.dumps(doc), stage=3)
            try:
                p = procedure.build(self.start, doc, 7, names, stage=3)
            except procedure.ProcedureError as e:
                self.assertEqual([x for x in e.errors if not pending_b1(x, doc)], [])
            else:
                self.assertEqual(procedure.check(p, names, stage=3), [])

    def test_bug_shape(self):
        """§2.2 table."""
        bug = {s["id"]: s for s in steps(self.templates["bug"])}
        self.assertEqual([s["id"] for s in steps(self.templates["bug"])], [
            "test-cases", "ac-coverage", "diagnose", "setup", "reproduce", "repro-red", "fix", "lint", "typecheck",
            "test", "build", "e2e", "review-design", "review-tests", "review-audit", "qa", "verify-gate", "done-gate",
            "pr", "followups"])
        self.assertEqual(developer_index(steps(self.templates["bug"])), 6)                    # fix (E5)
        self.assertEqual(bug["reproduce"]["outputs"], [codes.path_token("test-code")])        # E6: owned test code
        self.assertEqual(bug["reproduce"]["role"], "developer")
        self.assertEqual(bug["repro-red"]["on_fail"], {"back_to": "reproduce", "max": 2})
        self.assertEqual(bug["fix"]["outputs"], [])
        for s in ("fix", "review-design", "review-tests", "done-gate"):
            self.assertIn("in:repro-evidence.md", bug[s]["inputs"], s)                      # E8
        self.assertEqual(bug["review-design"]["checks"], ["root-cause-addressed"])
        self.assertEqual(bug["review-tests"]["checks"], ["test-quality", "regression-proof"])
        self.assertEqual(bug["diagnose"]["outputs"], [SPECS + "diagnosis.md"])
        for s in ("lint", "typecheck", "test", "build", "e2e", "verify-gate", "review-audit", "qa"):
            self.assertEqual(bug[s]["on_fail"]["back_to"], "fix", s)

    def test_refactor_shapes(self):
        """§2.3: refactor / refactor-net / safety-net, E9–E11."""
        runs = ["lint", "typecheck", "test", "build", "e2e"]
        tail = ["review-design", "review-tests", "review-audit", "qa", "verify-gate", "done-gate", "pr", "followups"]
        head = ["test-cases", "ac-coverage", "design", "setup"]
        want = {
            "refactor": (head + ["transform", "verification-frozen"] + runs + tail, "transform"),
            "refactor-net": (head + ["safety-net", "safety-net-proof", "transform", "verification-frozen"] + runs + tail,
                             "transform"),
            "safety-net": (["test-cases", "ac-coverage", "setup", "safety-net", "safety-net-proof", "no-production-change",
                            "test", "review-tests", "review-audit", "verify-gate", "done-gate", "pr", "followups"],
                           "safety-net"),
        }
        for name, (ids, dev) in want.items():
            with self.subTest(template=name):
                own = steps(self.templates[name])
                by = {s["id"]: s for s in own}
                self.assertEqual([s["id"] for s in own], ids)
                self.assertEqual(own[developer_index(own)]["id"], dev)                       # E5
                for s in own[developer_index(own) + 1:]:
                    if "on_fail" in s:
                        self.assertEqual(s["on_fail"]["back_to"], dev, s["id"])
                if "safety-net" in by:
                    self.assertEqual(by["safety-net"]["outputs"], [codes.path_token("safety-net")])   # E10: owned, frozen
                    self.assertEqual(by["safety-net-proof"]["on_fail"], {"back_to": "safety-net", "max": 2})
                    self.assertIn("net-public-behavior", by["review-tests"]["checks"])
                if "transform" in by:
                    self.assertEqual(by["transform"]["outputs"], [])
                    self.assertEqual(by["review-design"]["checks"], ["structure-improved", "behavior-preserved"])
                    self.assertEqual(by["verification-frozen"]["on_fail"]["back_to"], "transform")
                    self.assertEqual(by["design"]["outputs"], [SPECS + "skeleton.md"])
        sn = {s["id"]: s for s in steps(self.templates["safety-net"])}
        self.assertEqual(sn["no-production-change"]["run"], "no-production-change")       # E11
        self.assertNotIn("qa", sn)
        self.assertEqual(sn["pr"]["inputs"], [SPECS + "analysis.md"])
        used = {s["run"] for doc in [self.start] + list(self.templates.values()) for s in steps(doc) if "run" in s}
        self.assertEqual(set(codes.PluginCommand.values()) - used, set(), "every plugin command has a template")

    def test_feature_stage3_additions(self):
        f = {s["id"]: s for s in steps(self.templates["feature"])}
        self.assertEqual([s["id"] for s in steps(self.templates["feature"])][-3:], ["done-gate", "pr", "followups"])
        self.assertIn("in:blocking-discoveries.md", f["implement"]["inputs"])
        for s in ("test-cases", "design", "implement"):
            self.assertIn("in:failure-summary.md", f[s]["inputs"])


def defaults_stage():
    from gxengine import defaults
    return defaults.ENGINE_STAGE


class Catalog(unittest.TestCase):
    """data/catalog.json — the plugin step catalog (stage 3, scope §2.4 E14, E17, E25; session A).

    The rules beyond the schema are catalog.load's (session B1); they are repeated here so the data
    file is checked before that reader exists, and compared with it once it does."""

    # E14 table: id → (role, class, outputs, checks)
    TABLE = {
        "product-review": ("product-owner", "design-time", ["docs/specs/{issue}/product.md"], []),
        "ux-design": ("designer", "design-time", ["docs/specs/{issue}/ux.md"], []),
        "threat-model": ("security", "design-time", ["docs/specs/{issue}/threat-model.md"], []),
        "data-design": ("dba", "design-time", ["docs/specs/{issue}/data.md"], []),
        "i18n-plan": ("i18n", "design-time", ["docs/specs/{issue}/i18n.md"], []),
        "ux-review": ("designer", "diff-review", [], ["ux-conformance"]),
        "security-review": ("security", "diff-review", [], ["security-review"]),
        "data-review": ("dba", "diff-review", [], ["data-integrity"]),
        "i18n-review": ("i18n", "diff-review", [], ["i18n-completeness"]),
        "performance-review": ("performance", "diff-review", [], ["performance-regression"]),
        "infra-review": ("infra", "diff-review", [], ["infra-safety"]),
        "fix-discovery": ("developer", "fix", [], []),
    }

    @classmethod
    def setUpClass(cls):
        cls.data = instructions.load_catalog_data()
        cls.entries = cls.data["entries"]
        cls.by_id = {e["id"]: e for e in cls.entries}

    def test_schema_and_the_e14_table(self):
        from gxengine import schema
        schema.validate(self.data, "catalog")
        ids = [e["id"] for e in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, list(self.TABLE))
        for e in self.entries:
            with self.subTest(entry=e["id"]):
                self.assertEqual((e["role"], e["class"], e["outputs"], e["checks"]), self.TABLE[e["id"]])
                self.assertTrue(e["summary"].strip())

    def test_class_rules(self):
        for e in self.entries:
            with self.subTest(entry=e["id"]):
                if e["class"] == "design-time":
                    self.assertTrue(e["outputs"])
                    self.assertEqual((e["checks"], e["on_fail"]), ([], None))
                elif e["class"] == "diff-review":
                    self.assertTrue(e["checks"])
                    self.assertEqual(e["outputs"], [])
                    self.assertEqual(e["on_fail"], {"back_to": codes.CATALOG_DEVELOPER_TOKEN, "max": 2})
                    self.assertIn("in:review.diff", e["inputs"])
                else:
                    self.assertEqual(e["class"], "fix")
                    self.assertEqual(codes.role_class(e["role"]), "work")
                    self.assertEqual((e["outputs"], e["checks"], e["on_fail"]), ([], [], None))
                if e["role"] != "developer":
                    self.assertEqual(codes.role_class(e["role"]), "judge")       # E17: every specialist judges

    def test_fix_discovery_reads_the_blocking_discoveries(self):
        e = self.by_id["fix-discovery"]
        for i in ("in:blocking-discoveries.md", "docs/specs/{issue}/analysis.md"):      # E18
            self.assertIn(i, e["inputs"])
        self.assertIn("in:failure-summary.md", e["inputs"])                               # a developer step (§2.2)

    def test_paths(self):
        from gxengine import defaults, globs
        allowed_in = {"in:" + v for v in codes.InFile.values()}
        for e in self.entries:
            for o in e["outputs"]:
                with self.subTest(entry=e["id"], output=o):
                    self.assertTrue(o.startswith(defaults.SPECS_DIR + "/"))
                    self.assertFalse(globs.names_control_file(o.replace("{issue}", "7"), 7))
            for i in e["inputs"]:
                with self.subTest(entry=e["id"], input=i):
                    if i.startswith("in:"):
                        self.assertIn(i, allowed_in)
                    else:   # only what exists right after the plan step (a design-time entry may go there)
                        self.assertEqual(i, "docs/specs/{issue}/analysis.md")
            self.assertIn("in:leader-decision.md", e["inputs"])                 # every role step (§2.2)
        outs = [o for e in self.entries for o in e["outputs"]]
        self.assertEqual(len(outs), len(set(outs)), "a judge step's outputs are its own (§7.6)")

    def test_ids_are_neither_reserved_nor_start_steps_nor_template_steps(self):
        start = {s["id"] for s in instructions.load_start_procedure()["steps"]}
        for e in self.entries:
            self.assertNotEqual(e["id"], "leader")
            self.assertNotIn(e["id"], start)
        for name in instructions.default_template_names():
            ids = {s["id"] for s in instructions.load_default_template(name, stage=3)["steps"]}
            self.assertFalse(ids & set(self.by_id), name)

    def test_every_check_is_in_the_check_catalog(self):
        for e in self.entries:
            for c in e["checks"]:
                with self.subTest(check=c):
                    self.assertIn(c, instructions.CHECK_CATALOG)
                    self.assertFalse(instructions.CHECK_CATALOG[c]["covers_diff"])

    def test_every_entry_has_a_stage3_task_and_none_before(self):
        for e in self.entries:
            with self.subTest(entry=e["id"]):
                self.assertTrue(instructions.task_text(e["id"], stage=3).strip())
                self.assertEqual(instructions.task_text(e["id"], stage=2), "", "stage 1–2 texts stay as they were")

    def test_the_tasks_follow_the_document_rules(self):
        for e in self.entries:
            text = instructions.task_text(e["id"], stage=3)
            with self.subTest(entry=e["id"]):
                self.assertIsNone(re.search(r"\[(?:AC[ #]|must\]|should\])", text, re.I))
                if e["class"] == "design-time":
                    self.assertIn("square brackets", text)                         # P5 bug 7, R10
                    self.assertIn(e["outputs"][0].replace("{issue}", "<issue>"), text)
                for c in e["checks"]:
                    self.assertIn(f"`{c}`", text)

    def test_every_role_has_layer1_defaults_and_a_budget_in_stage3(self):
        from gxengine import defaults
        me, budget = defaults.model_effort_table(3), defaults.session_budget_table(3)
        for e in self.entries:
            with self.subTest(entry=e["id"]):
                key = f"{e['role']}/review" if e["checks"] else f"{e['role']}/{e['id']}"
                self.assertTrue(key in me or e["role"] in me, key)                 # driver._model_effort's lookup
                self.assertIn(e["role"], budget)

    def test_security_review_is_the_stage_1_2_gate(self):
        """E14: rules.GATE_CATALOG moves into the catalog — same role, inputs, checks and max."""
        from gxengine import rules
        gate, e = rules.GATE_CATALOG["security-review"], self.by_id["security-review"]
        self.assertEqual((e["role"], e["inputs"], e["outputs"], e["checks"], e["on_fail"]["max"]),
                         (gate["role"], gate["inputs"], gate["outputs"], gate["checks"], gate["max"]))

    def test_the_engine_reader_agrees(self):
        from gxengine import catalog
        try:
            loaded = catalog.load()
        except NotImplementedError:
            self.skipTest("catalog.load is session B1's (V2)")
        self.assertEqual(list(loaded), list(self.by_id))
        self.assertEqual(catalog.requestable_ids(loaded), [i for i in self.by_id if i != "fix-discovery"])


if __name__ == "__main__":
    unittest.main()
