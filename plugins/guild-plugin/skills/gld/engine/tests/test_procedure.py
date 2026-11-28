"""U3 — procedure grammar and checker (procedure.py, design §3, §4, §6.1, §7.6)."""

import copy
import json
import os
import unittest

from gxengine import catalog as CAT, codes, procedure as PR

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ENGINE, "tests", "fixtures")


def text(*parts):
    with open(os.path.join(FIX, *parts), encoding="utf-8") as f:
        return f.read()


def load(*parts):
    return json.loads(text(*parts))


COMMANDS = load("procedure", "commands.json")


def example():
    return load("contracts", "procedure.example.json")


class Build(unittest.TestCase):
    def build(self, issue=42):
        return PR.build(text("procedure", "start.json"), text("procedure", "feature.json"), issue, COMMANDS)

    def test_build_matches_golden(self):
        proc = self.build()
        self.assertEqual(PR.dump(proc), text("procedure", "feature-42.procedure.json"))

    def test_build_records_origin_and_revision_1(self):
        proc = self.build()
        self.assertEqual(proc.origin, {"template": "feature", "version": "fixture-1", "start": "fixture-1"})
        self.assertEqual((proc.revision, proc.issue, proc.format), (1, 42, 1))
        self.assertEqual(proc.step_ids[:3], ["analyze", "ac-format", "plan"], "start procedure first (§3.1)")
        self.assertEqual(proc.step_ids[-1], "pr")

    def test_issue_substituted_everywhere(self):
        dumped = PR.dump(self.build(7))
        self.assertNotIn("{issue}", dumped)
        self.assertIn("docs/specs/7/design.md", dumped)

    def test_contract_example_is_start_plus_contract_template(self):
        proc = PR.build(text("procedure", "start.json"), load("contracts", "template.example.json"), 42, COMMANDS)
        self.assertEqual(proc.to_json()["steps"], example()["steps"])

    def test_build_checks_run_names(self):
        with self.assertRaises(PR.ProcedureError) as cm:
            PR.build(text("procedure", "start.json"), text("procedure", "feature.json"), 42, ["setup", "test"])
        self.assertTrue(any("ac-format" in e for e in cm.exception.errors))
        self.assertTrue(any("verify-gate" in e for e in cm.exception.errors))

    def test_build_names(self):
        start, feat = load("procedure", "start.json"), load("procedure", "feature.json")
        with self.assertRaises(PR.ProcedureError):
            PR.build(feat, feat, 42, COMMANDS)          # start must be the `start` procedure
        with self.assertRaises(PR.ProcedureError):
            PR.build(start, start, 42, COMMANDS)        # the template must not be
        for bad in (0, True, "42"):
            with self.assertRaises(PR.ProcedureError):
                PR.build(start, feat, bad, COMMANDS)

    def test_build_does_not_modify_inputs(self):
        start, feat = load("procedure", "start.json"), load("procedure", "feature.json")
        s0, f0 = copy.deepcopy(start), copy.deepcopy(feat)
        PR.build(start, feat, 42, COMMANDS)
        self.assertEqual((start, feat), (s0, f0))


class Parse(unittest.TestCase):
    def test_roundtrip(self):
        t = text("procedure", "feature-42.procedure.json")
        proc = PR.parse_procedure(t, COMMANDS)
        self.assertEqual(PR.dump(proc), t)
        self.assertEqual(PR.parse_procedure(PR.dump(proc), COMMANDS), proc)

    def test_example_valid(self):
        self.assertEqual(PR.check(PR.Procedure(example()), COMMANDS), [])

    def test_commands_none_skips_only_run_names(self):
        p = example()
        p["steps"][4]["run"] = "deploy"
        PR.parse_procedure(json.dumps(p))                     # no settings at hand: accepted
        with self.assertRaises(PR.ProcedureError):
            PR.parse_procedure(json.dumps(p), COMMANDS)
        PR.parse_procedure(json.dumps(p), {"deploy": {"cmd": "x"}, "setup": {}, "test": {},
                                           "ac-format": {}, "verify-gate": {}})  # a commands dict

    def test_not_json(self):
        for t in ("format: 1\nissue: 42\n", "", "{", b"\xff", '{"format": 1, "format": 1}',
                  '{"format": NaN}', "[]", None):
            with self.subTest(t=t):
                with self.assertRaises(PR.ProcedureError):
                    PR.parse_procedure(t, COMMANDS)

    def test_bytes_accepted(self):
        PR.parse_procedure(text("procedure", "feature-42.procedure.json").encode(), COMMANDS)


def mutate(fn):
    p = example()
    fn(p)
    return p


# Each case: (name, mutation of the contract example, substring an error must contain).
INVALID = [
    ("when", lambda p: p["steps"][4].update({"when": "ui-change"}), "schema"),
    ("loop", lambda p: p["steps"][4].update({"repeat": 3}), "schema"),
    ("variables", lambda p: p.update({"vars": {"x": 1}}), "schema"),
    ("model", lambda p: p["steps"][3].update({"model": "opus"}), "schema"),
    ("note", lambda p: p["steps"][3].update({"note": "why"}), "schema"),
    ("history", lambda p: p.update({"history": []}), "schema"),
    ("command-string-run", lambda p: p["steps"][4].update({"run": "pnpm install"}), "schema"),
    ("command-string-run-2", lambda p: p["steps"][4].update({"run": "test;rm"}), "schema"),
    ("command-string-output", lambda p: p["steps"][3].update({"outputs": ["docs/x.md; rm -rf ~"]}), "schema"),
    ("command-string-input", lambda p: p["steps"][3].update({"inputs": ["$(curl x)"]}), None),
    ("two-kinds", lambda p: p["steps"][4].update({"role": "developer"}), "schema"),
    ("no-kind", lambda p: p["steps"][4].pop("run"), "schema"),
    ("abs-path", lambda p: p["steps"][3].update({"outputs": ["/etc/passwd"]}), "schema"),
    ("dotdot", lambda p: p["steps"][3].update({"outputs": ["docs/../../x"]}), "schema"),
    ("unknown-in", lambda p: p["steps"][0].update({"inputs": ["in:secrets.txt"]}), "schema"),
    ("in-as-output", lambda p: p["steps"][0].update({"outputs": ["in:issue.md"]}), "schema"),
    ("checks-on-run", lambda p: p["steps"][4].update({"checks": ["diff-review"]}), "schema"),
    ("outputs-on-run", lambda p: p["steps"][4].update({"outputs": ["x.md"]}), "schema"),
    ("on-fail-on-op", lambda p: p["steps"][9].update({"on_fail": {"back_to": "developer", "max": 1}}), "schema"),
    ("on-fail-on-check", lambda p: p["steps"][2].update({"on_fail": {"back_to": "analyze", "max": 1}}), "schema"),
    ("max-zero", lambda p: p["steps"][6]["on_fail"].update({"max": 0}), "schema"),
    ("max-eleven", lambda p: p["steps"][6]["on_fail"].update({"max": 11}), "schema"),
    ("on-fail-extra-key", lambda p: p["steps"][6]["on_fail"].update({"when": "x"}), "schema"),
    ("unknown-check-kind", lambda p: p["steps"][2].update({"check": "is-it-good"}), "schema"),
    ("unknown-op", lambda p: p["steps"][9].update({"op": "merge"}), "schema"),
    ("revision-zero", lambda p: p.update({"revision": 0}), "schema"),
    ("format-2", lambda p: p.update({"format": 2}), "schema"),
    ("no-origin", lambda p: p.pop("origin"), "schema"),
    ("no-steps", lambda p: p.update({"steps": []}), "schema"),
    ("dup-id", lambda p: p["steps"][4].update({"id": "design"}), "duplicate step id"),
    ("back-to-later", lambda p: p["steps"][1]["on_fail"].update({"back_to": "test"}), "later step"),
    ("back-to-unknown", lambda p: p["steps"][6]["on_fail"].update({"back_to": "nope"}), "not a step"),
    ("run-unknown", lambda p: p["steps"][4].update({"run": "deploy"}), "not a named command"),
    ("stage2-op", lambda p: p["steps"][9].update({"op": "create-children"}), "not available in stage 1"),
    ("done-gate", lambda p: p["steps"].insert(9, {"id": "done", "check": "done-gate"}), "done-gate is not available"),
    ("pr-not-last", lambda p: p["steps"].insert(8, {"id": "pr0", "op": "create-pr"}), "create-pr"),
    ("pr-twice", lambda p: p["steps"].append({"id": "pr2", "op": "create-pr"}), "more than once"),
    ("placeholder", lambda p: p["steps"][3].update({"outputs": ["docs/specs/{issue}/design.md"]}), "placeholder"),
    ("other-placeholder", lambda p: p["steps"][3].update({"inputs": ["docs/{branch}/x.md"]}), "placeholder"),
    ("judge-overlap", lambda p: p["steps"][7].update({"outputs": ["docs/specs/42/design.md"]}), "overlap"),
    ("judge-glob-overlap", lambda p: p["steps"][7].update({"outputs": ["docs/specs/42/*.md"]}), "overlap"),
    ("judge-vs-developer", lambda p: p["steps"][5].update({"outputs": ["docs/specs/42/design.md"]}), "overlap"),
    ("control-output", lambda p: p["steps"][3].update({"outputs": [".claude/agents/tech-lead.md"]}), "control file"),
    ("control-output-glob", lambda p: p["steps"][3].update({"outputs": [".claude/**"]}), "control file"),
    ("control-output-case", lambda p: p["steps"][3].update({"outputs": ["src/Claude.md"]}), "control file"),
    ("procedure-output", lambda p: p["steps"][3].update({"outputs": ["docs/specs/42/procedure.yaml"]}), "control file"),
    ("agents-output", lambda p: p["steps"][3].update({"outputs": ["pkg/AGENTS.md"]}), "control file"),
]


class Invalid(unittest.TestCase):
    def test_every_invalid_case_is_refused(self):
        for name, fn, want in INVALID:
            with self.subTest(case=name):
                with self.assertRaises(PR.ProcedureError) as cm:
                    PR.parse_procedure(json.dumps(mutate(fn)), COMMANDS)
                if want:
                    self.assertTrue(any(want in e for e in cm.exception.errors), cm.exception.errors)

    def test_check_returns_errors_instead_of_raising(self):
        p = mutate(lambda p: p["steps"][4].update({"id": "design"}))
        errs = PR.check(p, COMMANDS)
        self.assertTrue(errs and any("duplicate" in e for e in errs))
        errs = PR.check(mutate(lambda p: p["steps"][4].update({"when": "x"})), COMMANDS)
        self.assertTrue(errs)

    def test_back_to_self_is_allowed(self):
        p = mutate(lambda p: p["steps"][6]["on_fail"].update({"back_to": "test"}))
        self.assertEqual(PR.check(p, COMMANDS), [])

    def test_stage_2_allows_done_gate_and_epic_ops(self):
        p = mutate(lambda p: p["steps"].insert(9, {"id": "done", "check": "done-gate"}))
        self.assertEqual(PR.check(p, COMMANDS, stage=2), [])


class Stage3Followups(unittest.TestCase):
    """E20: create-followups is the one step that may follow create-pr, and only right after it."""

    TAIL = {"id": "followups", "op": "create-followups"}
    GATE = {"id": "done", "check": "done-gate"}

    def errs(self, fn, stage=3):
        p = example()
        p["steps"].insert(9, dict(self.GATE))
        fn(p["steps"])
        return PR.check(p, COMMANDS, stage=stage)

    def test_position(self):
        self.assertEqual(self.errs(lambda s: None), [], "it is optional")
        self.assertEqual(self.errs(lambda s: s.append(dict(self.TAIL))), [])
        for why, fn in (("before the PR", lambda s: s.insert(5, dict(self.TAIL))),
                        ("between the gate and the PR", lambda s: s.insert(10, dict(self.TAIL))),
                        ("twice", lambda s: s.extend([dict(self.TAIL), dict(self.TAIL, id="f2")])),
                        ("not last", lambda s: s.extend([dict(self.TAIL), {"id": "late", "run": "test"}])),
                        ("not right after", lambda s: s.extend([{"id": "late", "run": "test"}, dict(self.TAIL)])),
                        ("without a PR", lambda s: (s.__delitem__(slice(9, None)), s.append(dict(self.TAIL))))):
            with self.subTest(why=why):
                errs = self.errs(fn)
                self.assertTrue(any("create-followups" in e or "create-pr" in e for e in errs), errs)

    def test_epic_ops_and_earlier_stages(self):
        self.assertTrue(self.errs(lambda s: s.append({"id": "c", "op": "create-children"})))
        for stage in (1, 2):
            self.assertTrue(any("not available" in e for e in self.errs(lambda s: s.append(dict(self.TAIL)), stage)))

    def test_in_a_template(self):
        t = load("procedure", "bug.json")
        t["steps"].pop(3)                      # (without the {path:…} step)
        self.assertEqual(PR.template_errors(dict(t, steps=t["steps"][:2] + t["steps"][5:]), 3), [])
        for bad in (t["steps"][5:-2] + t["steps"][-1:], t["steps"][5:] + [{"id": "late", "run": "test"}, dict(self.TAIL, id="f2")]):
            self.assertTrue(any("create-followups" in e for e in PR.template_errors(dict(t, steps=bad), 3)))


TEST_GLOBS = ["test/**/*_test.dart", "integration_test/**/*_test.dart"]
S3_COMMANDS = list(COMMANDS) + ["repro-red"]


def start_proc():
    return PR.build_start(load("procedure", "start.json"), 42, S3_COMMANDS, stage=3)


class Stage3Paths(unittest.TestCase):
    """E4: `{path:<kind>}` of a template becomes the globs of the repository's path rules."""

    def test_expand(self):
        t = load("procedure", "bug.json")
        t["steps"][5]["inputs"].append("{path:test-code}")
        before = copy.deepcopy(t)
        got = PR.expand_paths(t, {"test-code": TEST_GLOBS})
        self.assertEqual(t, before)
        by = {s["id"]: s for s in got["steps"]}
        self.assertEqual(by["reproduce"]["outputs"], TEST_GLOBS)
        self.assertEqual(by["fix"]["inputs"][-2:], TEST_GLOBS)
        self.assertEqual(by["fix"]["inputs"][:-2], before["steps"][5]["inputs"][:-1])
        self.assertEqual(by["repro-red"], before["steps"][4])

    def test_a_function_and_no_repeats(self):
        t = load("procedure", "bug.json")
        t["steps"][3]["outputs"] = [TEST_GLOBS[0], "{path:test-code}", "{path:safety-net}"]
        kinds = {"test-code": TEST_GLOBS, "safety-net": [TEST_GLOBS[1], "x/*_net.dart"]}
        self.assertEqual(PR.expand_paths(t, kinds.get)["steps"][3]["outputs"], TEST_GLOBS + ["x/*_net.dart"])

    def test_missing_kind(self):
        for globs in (None, {}, {"test-code": []}, {"safety-net": TEST_GLOBS}, lambda kind: []):
            with self.subTest(globs=globs), self.assertRaises(PR.ProcedureError) as cm:
                PR.expand_paths(load("procedure", "bug.json"), globs)
            self.assertIn("test-code", cm.exception.errors[0])
        feat = load("procedure", "feature.json")
        self.assertEqual(PR.expand_paths(feat, None), feat, "a template without a placeholder needs no rule")

    def test_the_placeholder_is_stage_3_only(self):
        PR.parse_template(text("procedure", "bug.json"), stage=3)
        PR.parse_template(text("contracts", "template.stage3.example.json"), stage=3)
        for stage in (1, 2):
            with self.assertRaises(PR.ProcedureError):
                PR.parse_template(text("procedure", "bug.json"), stage=stage)
        p = example()
        p["steps"][5]["outputs"] = ["{path:test-code}"]
        self.assertTrue(any("placeholder" in e for e in PR.check(p, COMMANDS, stage=3)), "never left in a procedure")


class Stage3WorkOutputs(unittest.TestCase):
    """A work role's output globs (the expanded test-code rules) and the files it owns (D2, K2)."""

    def errs(self, step, outputs, stage=3):
        p = example()
        p["steps"][step]["outputs"] = outputs
        return PR.check(p, COMMANDS, stage=stage)

    def test_test_globs_of_a_work_role(self):
        for ok in (TEST_GLOBS, ["**/*_test.py"], ["apps/*/src/**/*.test.ts"], ["e2e/x.spec.ts"]):
            self.assertEqual(self.errs(5, ok), [], ok)
        for stage in (1, 2):
            self.assertTrue(self.errs(5, TEST_GLOBS, stage), "earlier stages keep the strict rule")
        self.assertTrue(self.errs(3, TEST_GLOBS), "a judge's outputs are its write scope")

    def test_globs_that_name_a_control_file_stay_refused(self):
        for bad in (".claude/**/*.py", "test/.claude/*.py", "test/.c*/a.py", "test/**", "test/", "test/**/*", "**/*.md",
                    "test/**/CLAUDE.md", "test/CLAUDE.md", "test/**/AGENTS*", "docs/specs/42/*.yaml", "**/procedure.yaml",
                    "**/.claude", "./test/*_test.py"):
            self.assertTrue(self.errs(5, [bad]), bad)

    def test_owner_of_by_files(self):
        p = example()
        p["steps"][5]["outputs"] = TEST_GLOBS
        proc = PR.Procedure(p)
        dev = proc.steps[5].id
        self.assertEqual(proc.file_owned_steps(), [dev])
        self.assertEqual(proc.owner_of("test/a_test.dart"), dev, "without facts: the globs")
        owned = {dev: ["test/new_test.dart"]}
        self.assertEqual(proc.owner_of("test/new_test.dart", owned), dev)
        self.assertIsNone(proc.owner_of("test/a_test.dart", owned), "another test of the same glob is nobody's (K2)")
        self.assertIsNone(proc.owner_of("test/a_test.dart", {dev: []}))
        self.assertEqual(proc.owner_of("docs/specs/42/analysis.md", owned), "analyze")
        self.assertEqual(PR.Procedure(example()).file_owned_steps(), [])


class Stage3Plan(unittest.TestCase):
    """E2 template-unusable and the plan answer's revision (E12)."""

    GLOBS = {"test-code": TEST_GLOBS}

    def setUp(self):
        self.cat = CAT.load(os.path.join(FIX, "procedure", "catalog.json"))

    def problems(self, template=None, commands=S3_COMMANDS, globs=None):
        return PR.template_problems(load("procedure", "start.json"), template or load("procedure", "bug.json"), 42, commands,
                                    self.GLOBS if globs is None else globs)

    def plan(self, *steps, candidate=False, template=None, catalog=None):
        return PR.attach_plan(start_proc(), template or load("procedure", "bug.json"), S3_COMMANDS, path_globs=self.GLOBS,
                              catalog=self.cat if catalog is None else catalog, candidate=candidate,
                              adjust=[{"op": "add", "step": s, "trigger": "other", "note": "n"} for s in steps])

    def test_template_problems(self):
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.problems(template=text("procedure", "bug.json")), [])
        self.assertTrue(any("test-code" in e for e in self.problems(globs={})))                        # TY4
        self.assertTrue(any("repro-red" in e for e in self.problems(commands=COMMANDS)))
        self.assertTrue(any("control file" in e for e in self.problems(globs={"test-code": ["test/**"]})))
        for bad in ({"test-code": ["test/*.{ts,tsx}"]}, {"test-code": ["test/{issue}_test.py"]}):
            self.assertTrue(any("placeholder" in e for e in self.problems(globs=bad)))
        t = load("procedure", "bug.json")
        t["steps"] = [s for s in t["steps"] if s["id"] != "done-gate"]
        self.assertTrue(any("done-gate" in e for e in self.problems(template=t)))
        self.assertTrue(self.problems(template="{"))
        self.assertTrue(self.problems(template=load("procedure", "start.json")))

    def test_no_adjust(self):
        p, ids = self.plan()
        self.assertEqual((ids, p.revision, p.origin["template"]), ([], 2, "bug"))
        self.assertNotIn("new_template_candidate", p.to_json())
        self.assertEqual(p.step("reproduce").outputs, TEST_GLOBS)
        self.assertNotIn("{", json.dumps(p.step("reproduce").to_json()["outputs"]))
        self.assertEqual(PR.parse_procedure(PR.dump(p), S3_COMMANDS, stage=3), p)

    def test_same_as_attach_template_without_placeholders(self):
        feat = load("procedure", "feature.json")
        feat["steps"].insert(len(feat["steps"]) - 1, {"id": "done", "check": "done-gate"})
        start = start_proc()
        self.assertEqual(PR.attach_plan(start, feat, S3_COMMANDS, path_globs=None, catalog={})[0],
                         PR.attach_template(start, feat, S3_COMMANDS, stage=3))

    def test_adjust_in_one_revision(self):
        """TC9: design-time right after plan (its document reaches every later role), a review
        before the first review."""
        p, ids = self.plan("product-review", "i18n-review")
        self.assertEqual((ids, p.revision), (["product-review", "i18n-review"], 2))
        self.assertEqual(p.step_ids[p.index("plan") + 1], "product-review")
        self.assertEqual(p.step_ids[p.index("i18n-review") + 1], "review-tests")
        self.assertEqual(p.step("i18n-review").on_fail["back_to"], "fix")                              # E5
        for sid in ("test-cases", "reproduce", "fix", "i18n-review", "review-audit"):
            self.assertIn("docs/specs/42/product.md", p.step(sid).inputs)
        self.assertNotIn("docs/specs/42/product.md", p.step("analyze").inputs)
        self.assertIs(p.new_template_candidate, True, "two adds = a candidate")

    def test_candidate(self):
        self.assertIsNone(self.plan("ux-review")[0].new_template_candidate)
        self.assertIs(self.plan("ux-review", candidate=True)[0].new_template_candidate, True)
        self.assertIs(self.plan(candidate=True)[0].new_template_candidate, True)

    def test_a_step_the_template_has_is_not_added_again(self):
        t = load("procedure", "bug.json")
        t["steps"].insert(8, {"id": "ux-review", "role": "tester", "outputs": [], "checks": ["x"]})
        p, ids = self.plan("ux-review", "i18n-review", template=t)
        self.assertEqual(ids, ["i18n-review"])
        self.assertEqual(p.step_ids.count("ux-review"), 1)

    def test_refusals(self):
        for why, steps in (("unknown", ["nope"]), ("fix class", ["fix-discovery"]), ("twice", ["ux-review", "ux-review"]),
                           ("over the cap", ["ux-review", "i18n-review", "data-review", "security-review"])):
            with self.subTest(why=why), self.assertRaises(PR.ProcedureError):
                self.plan(*steps)
        with self.assertRaises(PR.ProcedureError):
            PR.attach_plan(start_proc(), load("procedure", "bug.json"), S3_COMMANDS, path_globs=self.GLOBS, catalog=self.cat,
                           adjust=[{"op": "remove", "step": "ux-review"}])
        with self.assertRaises(PR.ProcedureError):
            PR.attach_plan(self.plan()[0], load("procedure", "bug.json"), S3_COMMANDS, path_globs=self.GLOBS, catalog=self.cat)
        t = load("procedure", "bug.json")
        t["steps"] = [s for s in t["steps"] if s["id"] not in ("reproduce", "repro-red", "fix", "test", "review-tests", "review-audit")]
        with self.assertRaises(PR.ProcedureError) as cm:
            self.plan("ux-design", template=t)
        self.assertIn("no position", cm.exception.errors[0])

    def test_every_shipped_template_name_is_known(self):
        self.assertIn("bug", codes.STAGE3_TEMPLATES)


class Template(unittest.TestCase):
    def test_templates_parse(self):
        for name in ("start.json", "feature.json"):
            with self.subTest(name=name):
                raw = PR.parse_template(text("procedure", name))
                self.assertIn("{issue}", json.dumps(raw))
        PR.parse_template(text("contracts", "template.example.json"))

    def test_template_refusals(self):
        feat = load("procedure", "feature.json")
        cases = [
            ("other placeholder", lambda t: t["steps"][0].update({"outputs": ["docs/{n}/x.md"]})),
            ("dup", lambda t: t["steps"][1].update({"id": "design"})),
            ("back_to later in template", lambda t: t["steps"][4]["on_fail"].update({"back_to": "review"})),
            ("stage 2 op", lambda t: t["steps"][-1].update({"op": "run-children"})),
            ("when", lambda t: t["steps"][0].update({"when": "x"})),
            ("procedure fields", lambda t: t.update({"revision": 1})),
        ]
        for why, fn in cases:
            t = copy.deepcopy(feat)
            fn(t)
            with self.subTest(why=why):
                with self.assertRaises(PR.ProcedureError):
                    PR.parse_template(json.dumps(t))

    def test_template_back_to_outside_is_resolved_at_build(self):
        feat = load("procedure", "feature.json")
        feat["steps"][4]["on_fail"]["back_to"] = "analyze"      # a start-procedure step
        PR.parse_template(json.dumps(feat))
        PR.build(text("procedure", "start.json"), feat, 42, COMMANDS)
        feat["steps"][4]["on_fail"]["back_to"] = "nowhere"
        PR.parse_template(json.dumps(feat))
        with self.assertRaises(PR.ProcedureError):
            PR.build(text("procedure", "start.json"), feat, 42, COMMANDS)


class Model(unittest.TestCase):
    def setUp(self):
        self.proc = PR.Procedure(example())

    def test_step_attributes(self):
        review = self.proc.step("review")
        self.assertEqual((review.kind, review.name), ("role", "auditor"))
        self.assertTrue(review.is_review)
        self.assertTrue(review.is_judge)
        self.assertEqual(review.engine_inputs(), ["review.diff"])
        self.assertEqual(review.on_fail, {"back_to": "developer", "max": 2})
        dev = self.proc.step("developer")
        self.assertFalse(dev.is_review)
        self.assertFalse(dev.is_judge)
        self.assertEqual(self.proc.step("test").kind, "run")
        self.assertIsNone(self.proc.step("test").role_class)
        self.assertEqual(self.proc.index("pr"), 9)
        with self.assertRaises(KeyError):
            self.proc.step("nope")
        with self.assertRaises(KeyError):
            self.proc.index("nope")

    def test_owner_of(self):
        self.assertEqual(self.proc.owner_of("docs/specs/42/analysis.md"), "analyze")
        self.assertEqual(self.proc.owner_of("docs/specs/42/review-auditor.md"), "review")
        self.assertIsNone(self.proc.owner_of("src/a.py"))

    def test_step_to_json_roundtrip(self):
        for raw in example()["steps"]:
            with self.subTest(step=raw["id"]):
                self.assertEqual(PR.Step(raw).to_json(), raw)

    def test_step_refuses_unknown_keys_and_two_kinds(self):
        with self.assertRaises(PR.ProcedureError):
            PR.Step({"id": "x", "run": "test", "when": "y"})
        with self.assertRaises(PR.ProcedureError):
            PR.Step({"id": "x", "run": "test", "op": "create-pr"})

    def test_constructor_validates_schema(self):
        with self.assertRaises(PR.ProcedureError):
            PR.Procedure(mutate(lambda p: p["steps"][4].update({"when": "x"})))


class Revision(unittest.TestCase):
    def test_revision_increments_on_structure_change(self):
        proc = PR.Procedure(example())
        steps = [s.to_json() for s in proc.steps]
        steps.insert(8, {"id": "e2e", "run": "e2e", "on_fail": {"back_to": "developer", "max": 2}})
        new = PR.with_revision(proc, steps)
        self.assertEqual(new.revision, 2)
        self.assertEqual(proc.revision, 1, "the original is not changed")
        self.assertEqual(new.origin, proc.origin)
        self.assertEqual(PR.check(new, COMMANDS), [])

    def test_same_steps_keep_the_revision(self):
        proc = PR.Procedure(example())
        with self.assertRaises(ValueError):
            PR.with_revision(proc, proc.steps)

    def test_new_steps_validated(self):
        proc = PR.Procedure(example())
        steps = [s.to_json() for s in proc.steps]
        steps[4]["when"] = "x"
        with self.assertRaises(PR.ProcedureError):
            PR.with_revision(proc, steps)


class ReservedStepId(unittest.TestCase):
    """Q4: from stage 2 the step id `leader` is the needs_leader calls' (tmp/…/leader-<k>)."""

    def test_leader_step_id_refused_from_stage_2_only(self):
        steps = [PR.Step({"id": "leader", "run": "test"})]
        self.assertEqual(PR._step_errors(steps, 1, template=True), [])
        errs = PR._step_errors(steps, 2, template=True)
        self.assertTrue(any("reserved" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
