"""instructions (U15): the work-instruction frames, the system prompt, the data loaders.

Also pins the formats the role files and task texts prescribe to the parser that reads them
(`acparse`): what the requirements-engineer is told to write must parse, what the tester is
told to write must be counted."""

import re
import unittest

from gxengine import acparse, codes, defaults, instructions


def fenced_blocks(text):
    return re.findall(r"```[a-z]*\n(.*?)```", text, re.S)


def role_step(step_id="design", role="tech-lead", **kw):
    d = {"id": step_id, "kind": "role", "name": role, "checks": []}
    d.update(kw)
    return d


def fields(**kw):
    d = {"issue": 7, "attempt": 1, "role": "tech-lead", "inputs": ["docs/specs/7/analysis.md"],
         "in_dir": None, "in_files": [], "outputs": ["docs/specs/7/skeleton.md"], "checks": [],
         "rule_checks": [], "facts": {}, "returned": None, "reentry": None}
    d.update(kw)
    return d


class Frames(unittest.TestCase):
    def test_every_kind_has_the_common_rules(self):
        for kind, cls in (("work", "work"), ("judge", "judge"), ("review", "judge")):
            with self.subTest(kind=kind):
                text = instructions.frame(kind, "developer" if kind == "work" else "tester", cls)
                self.assertIn("These rules win over your role file", text)          # I4
                self.assertIn("status lines", text)
                self.assertIn("Leave no background process", text)
                self.assertIn("Do not merge the base branch and do not rewrite pushed history", text)   # I7
                self.assertIn("`docs/standards/`", text)                             # preflight
                self.assertIn("status:", text)
                self.assertIn("index.md", text)
                self.assertIn("Inputs are paths", text)
                self.assertTrue(text.endswith("\n"))

    def test_stage3_frame_rules(self):
        """E16 (V6): from stage 3 the frame says requests name catalog steps and lists them; before, nothing changes."""
        for kind, role, cls in (("work", "developer", "work"), ("judge", "tester", "judge"), ("review", "tester", "judge")):
            with self.subTest(kind=kind):
                two, three = (instructions.frame(kind, role, cls, stage=s) for s in (2, 3))
                self.assertEqual(two, instructions.frame(kind, role, cls, stage=1))
                self.assertNotIn("Stage-3", two)
                self.assertIn("10. **Step requests.**", three)
                self.assertNotIn("{catalog}", three)
                for e in instructions.load_catalog_data()["entries"]:
                    if e["class"] == "fix":
                        self.assertNotIn(f"`{e['id']}`", three)
                    else:
                        self.assertIn(f"`{e['id']}` ({e['role']}, {e['class']})", three)
                self.assertTrue(three.startswith(instructions.frame(kind, role, cls, stage=2).split("\n\n## ")[0]))
                acparse.parse_test_case_refs(three)
        self.assertEqual(instructions.frame("work", "developer", "work"),
                         instructions.frame("work", "developer", "work", stage=defaults.ENGINE_STAGE))
        step = role_step("design", "tech-lead")
        self.assertIn("10. **Step requests.**", instructions.build_instruction(step, fields(), stage=3))
        self.assertNotIn("10. **Step requests.**", instructions.build_instruction(step, fields(), stage=2))
        self.assertIn("plan gate decides", instructions.default_role_file("requirements-engineer"))

    def test_stage3_frame_names_every_irreversible_code(self):
        """E22 (V9): the codes a role reports, grouped as the categories they map to; the analysis reports too."""
        three = instructions.frame("judge", "requirements-engineer", "judge", stage=3)
        rule = three.split("13. **Irreversible changes.**")[1]
        for code, category in codes.IRREVERSIBLE_CODE_CATEGORY.items():
            self.assertIn(f"`{code}`", rule)
        self.assertNotIn("Irreversible", instructions.frame("judge", "requirements-engineer", "judge", stage=2))
        body = instructions.default_role_file("requirements-engineer")
        self.assertIn("`irreversible`", body)
        self.assertIn("before any work starts", body)                    # TI3: analyze stops before the plan gate

    def test_stage3_work_frame_golden_reasons(self):
        """E33 (V14, P2): only the work frame of stage 3 asks for golden_reasons, with every reason code."""
        three = instructions.frame("work", "developer", "work", stage=3)
        self.assertIn("**Golden reasons.**", three)
        for v in codes.GoldenReason.values():
            self.assertIn(f"`{v}`", three)
        self.assertLess(three.index(instructions.SANDBOX_LIMITS_RULE), three.index("**Golden reasons.**"))
        self.assertNotIn("Golden reasons", instructions.frame("work", "developer", "work", stage=2))
        for kind, role in (("judge", "tester"), ("review", "tester")):
            self.assertNotIn("Golden reasons", instructions.frame(kind, role, "judge", stage=3))

    def test_work_frame_has_the_developer_rules(self):
        text = instructions.frame("work", "developer", "work")
        self.assertIn("full suite is run by the engine's `run` steps", text)        # I13
        self.assertIn("Golden rule", text)                                           # §2.1
        self.assertIn("Never weaken verification", text)
        self.assertNotIn("Golden rule", instructions.frame("judge", "tester", "judge"))

    def test_work_frame_forbids_issue_references_in_commit_messages(self):
        # P3-A (P2 session 3): the push-range close-keyword check stops even on `fix: x (#42)`
        text = instructions.frame("work", "developer", "work")
        self.assertIn(instructions.COMMIT_MESSAGE_RULE, text)
        self.assertIn("`fix: x (#42)`", text)
        self.assertIn("closing keyword", text)
        for kind, role, cls in (("judge", "tester", "judge"), ("review", "tester", "judge")):
            self.assertNotIn(instructions.COMMIT_MESSAGE_RULE, instructions.frame(kind, role, cls))

    def test_review_frame_has_the_severity_core_and_the_result_rules(self):
        text = instructions.frame("review", "tester", "judge")
        for must in ("blocker", "major", "minor", "`reviewed`", "`checks`", "`verdict`",
                     "weakening verification", "may not be `n/a`", "rejected"):
            self.assertIn(must, text)

    def test_frame_is_deterministic(self):
        self.assertEqual(instructions.frame("work", "developer", "work"), instructions.frame("work", "developer", "work"))

    def test_bad_arguments_fail_closed(self):
        for args in (("nope", "tester", "judge"), ("work", "tester", "judge"), ("judge", "developer", "work"),
                     ("review", "tester", "weird"), ("review", "Tester!", "judge")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                instructions.frame(*args)


class TaskTexts(unittest.TestCase):
    def test_every_role_step_of_the_data_files_has_a_task(self):
        steps = instructions.load_start_procedure()["steps"] + instructions.load_default_template("feature")["steps"]
        for s in steps:
            if "role" in s:
                with self.subTest(step=s["id"]):
                    self.assertTrue(instructions.task_text(s["id"]).strip())

    def test_stage3_texts_are_read_from_stage_3_only(self):
        """E36: the stage-3 part (tasks/stage3/) never reaches a stage 1–2 session."""
        for step in ("analyze", "test-cases", "design", "implement", "review-design", "review-tests",
                     "review-audit", "qa"):
            with self.subTest(step=step):
                self.assertEqual(instructions.task_text(step, stage=1), instructions.task_text(step, stage=2))
                self.assertTrue(instructions.task_text(step, stage=3).startswith(instructions.task_text(step, stage=2).rstrip()))
        self.assertEqual(instructions.task_text("security-review", stage=2), "")      # the stage-2 gate had no task
        self.assertIn("`security-review`", instructions.task_text("security-review", stage=3))
        self.assertEqual(instructions.task_text("analyze"), instructions.task_text("analyze", stage=defaults.ENGINE_STAGE))
        for bad in (0, "3", True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                instructions.task_text("analyze", stage=bad)

    def test_stage3_template_step_texts(self):
        """V4 / V5: the new steps exist from stage 3 only, follow the document rules and parse."""
        new = {"diagnose": ("diagnosis.md", "Reproduction", "Root cause", "Blast radius", "square brackets"),
               "reproduce": ("repro-scope", "twice", "`repro:`", "blocked_by.kind: other", "`fix` step may not change"),
               "fix": ("repro-evidence.md", "root-cause-addressed", "Never change, move or delete a file the reproduce step wrote",
                       "blocking-discoveries.md"),
               "transform": ("verification-frozen", "Never touch an existing verification file", "Safety-net files are frozen",
                             "blocked_by.kind: other", "skeleton.md"),
               "safety-net": ("New files only", "net-scope", "must not write a snapshot", "Public behaviour only",
                              "`kind: bug`", "Frozen afterwards", "`(safety net)`")}
        for step, musts in new.items():
            with self.subTest(step=step):
                self.assertEqual(instructions.task_text(step, stage=2), "")
                text = instructions.task_text(step, stage=3)
                for m in musts:
                    self.assertIn(m, text)
                self.assertIsNone(re.search(r"\[(?:AC[ #]|must\]|should\])", text, re.I))
                acparse.parse_test_case_refs(text)
        tc = instructions.task_text("test-cases", stage=3)
        example = re.search(r"`(- C1: [^`]*\(regression\) \(AC #1\))`", tc).group(1)
        self.assertEqual(acparse.parse_test_case_refs(example), {1})              # the tag form still counts
        self.assertIn("blocking-discoveries.md", instructions.task_text("implement", stage=3))
        self.assertIn("**Refactor Issues**", tc)
        for step, check in (("review-design", "root-cause-addressed"), ("review-tests", "regression-proof"),
                            ("review-design", "structure-improved"), ("review-design", "behavior-preserved"),
                            ("review-tests", "net-public-behavior")):
            self.assertIn(f"`{check}`", instructions.task_text(step, stage=3))
            self.assertIn(check, instructions.CHECK_CATALOG)
            self.assertFalse(instructions.CHECK_CATALOG[check]["covers_diff"])

    def test_build_instruction_passes_the_stage(self):
        step = role_step("security-review", "security", checks=["security-review"])
        f = fields(role="security", outputs=[], checks=["security-review"], inputs=["in:review.diff"])
        two, three = (instructions.build_instruction(step, f, stage=s) for s in (2, 3))
        self.assertNotIn("## Task — step `security-review`", two)
        self.assertIn("## Task — step `security-review`", three)
        self.assertEqual(instructions.build_instruction(step, f), instructions.build_instruction(step, f, stage=defaults.ENGINE_STAGE))

    def test_unknown_step_has_no_task_and_bad_ids_raise(self):
        self.assertEqual(instructions.task_text("custom-step"), "")
        for bad in ("../x", "A", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                instructions.task_text(bad)

    def test_tester_reference_form_is_counted_by_the_parser(self):
        """The reference form the test-cases task fixes (I6) is exactly what ac-coverage reads."""
        task = instructions.task_text("test-cases")
        examples = re.findall(r"`((?:(?:[-|]|#{1,6}) [^`\n]*)?\(AC #[^`\n]*\)[^`\n]*)`", task)
        self.assertGreaterEqual(len(examples), 4, examples)
        for ex in examples:
            with self.subTest(example=ex):
                self.assertTrue(acparse.parse_test_case_refs(ex if ex.startswith(("-", "#", "|")) else "- case " + ex),
                                ex)
        self.assertEqual(acparse.parse_test_case_refs("- C3: tapping the row opens the sheet. (AC #2)"), {2})
        self.assertEqual(acparse.parse_test_case_refs("- c (AC #2, #5)"), {2, 5})
        # the prose-mention advice of the same text is indeed not counted
        self.assertEqual(acparse.parse_test_case_refs("- C9: same limit as AC #4 here."), set())

    def test_written_forms_carry_no_square_bracket_tags(self):
        """P5 (app_a #1964): `[AC #2]` / `[must]` are undefined references to markdown lint
        (remark-lint-no-undefined-references) and the repository lint failed on the spec
        files. The texts that tell roles how to write them use parentheses only."""
        texts = {"role requirements-engineer": instructions.default_role_file("requirements-engineer")}
        for step in ("analyze", "test-cases", "design", "implement", "review-design", "review-tests",
                     "review-audit", "qa"):
            texts["task " + step] = instructions.task_text(step)
        for name, text in texts.items():
            with self.subTest(text=name):
                self.assertIsNone(re.search(r"\[(?:AC[ #]|must\]|should\])", text, re.I), name)
        role = texts["role requirements-engineer"]
        self.assertIn("(must)", role)
        self.assertIn("(should)", role)

    def test_task_texts_do_not_carry_unparseable_ac_tokens(self):
        """A model copying an example from a task text must not produce a token the parser rejects."""
        for step in ("analyze", "test-cases", "design", "implement", "review-design", "review-tests",
                     "review-audit", "qa"):
            with self.subTest(step=step):
                acparse.parse_test_case_refs(instructions.task_text(step))


class RoleFiles(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(instructions.role_file_path("requirements-engineer"), ".claude/guild/roles/requirements-engineer.md")
        self.assertEqual(instructions.role_file_path("auditor"), ".claude/guild/roles/auditor.md")
        self.assertEqual(instructions.role_file_path("tech-lead"), ".claude/agents/tech-lead.md")
        for bad in ("../x", "Tech", "", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                instructions.role_file_path(bad)

    def test_default_role_files(self):
        for role in instructions.PLUGIN_ROLES:
            with self.subTest(role=role):
                text = instructions.default_role_file(role)
                self.assertTrue(text.startswith("---\n"))
                body = instructions.strip_frontmatter(text)
                self.assertNotIn("name:", body.split("\n", 1)[0])
                self.assertNotIn("{{", text, "an unfilled placeholder would reach the model")
                self.assertIn("guild:persona:start", body)
        with self.assertRaises(KeyError):
            instructions.default_role_file("tech-lead")

    def test_requirements_engineer_example_parses(self):
        """The analysis.md shape the role file prescribes is the shape the parser accepts."""
        body = instructions.default_role_file("requirements-engineer")
        block = next(b for b in fenced_blocks(body) if "## Acceptance criteria" in b)
        a = acparse.parse_analysis(block.replace("#<issue>", "#5"))
        self.assertEqual(a["acs"], [1, 2])
        self.assertEqual(a["requirement_map"][0][1], [1, 2])
        self.assertEqual(acparse.check_analysis(a), [])
        self.assertEqual(len(a["assumptions"]), 1)

    def test_requirements_engineer_names_every_machine_field_value(self):
        body = instructions.default_role_file("requirements-engineer")
        for value in (codes.AnalysisType.values() + codes.Size.values() + codes.Risk.values()
                      + list(acparse.SPLIT_VALUES) + list(acparse.PREREQUISITE_VALUES)):
            self.assertIn(value, body)
        for hard in ("Depends on", "prerequisite: open", "ambiguous", "narrowest", "<!-- guild:plan-decision -->"):
            self.assertIn(hard, body)

    def test_requirements_engineer_writes_safety_net(self):
        """V3 (E3): the stage-3 machine field, its markers (gx and stable forms) and the refactor-only rule."""
        import inspect
        body = instructions.default_role_file("requirements-engineer")
        for value in codes.SafetyNet.values():
            self.assertIn(value, body)
        for marker in ("<!-- guild:safety-net -->", "<!-- guild:safety-net-only -->", "<!-- gx:safety-net -->",  # promote: other
                       "<!-- gx:safety-net-only -->", "only with `type: refactor`"):  # promote: other
            self.assertIn(marker, body)
        block = next(b for b in fenced_blocks(body) if "## Acceptance criteria" in b)
        self.assertIn("\nsafety_net: none\n", block)
        a = acparse.parse_analysis(block.replace("#<issue>", "#5"))          # a stage-2 reader ignores the line
        self.assertEqual(acparse.check_analysis(a), [])
        if "stage" in inspect.signature(acparse.parse_analysis).parameters:   # session B1 (V3)
            a3 = acparse.parse_analysis(block.replace("#<issue>", "#5"), stage=3)
            self.assertEqual(a3["safety_net"], "none")
            self.assertEqual(acparse.check_analysis(a3, stage=3), [])

    def test_auditor_carries_the_severity_core_and_the_reading_discipline(self):
        body = instructions.default_role_file("auditor")
        for must in ("blocker", "major", "minor", "[spec]", "[standards]", "weakened or vacuous tests",
                     "2000 lines", "reviewed", "test-change-review", "read-only", "blast radius"):
            self.assertIn(must, body)


LEADER_INPUT_SECTIONS = {"plan-gate": "plan_gate", "done-gate": "done_gate", "blocked": "stopped",
                         "output-format-twice": "stopped", "session-limit": "stopped",
                         "on-fail-exceeded": "stopped", "soft-budget": "budget",
                         "new-collaborator-comment": "comments"}
NEEDS_LEADER_SITUATIONS = [s for s in LEADER_INPUT_SECTIONS if s not in ("plan-gate", "done-gate")]


class LeaderFiles(unittest.TestCase):
    """Stage 2 V10: the leader role file, the frame and the three task files."""

    def test_the_leader_is_a_plugin_role_read_from_guild_exp_roles(self):
        self.assertIn("leader", instructions.PLUGIN_ROLES)
        self.assertEqual(instructions.role_file_path("leader"), ".claude/guild/roles/leader.md")
        self.assertEqual(codes.role_class("leader"), "judge")           # D10: the judge canary key and tools

    def test_role_file_shape(self):
        text = instructions.default_role_file("leader")
        body = instructions.strip_frontmatter(text)
        self.assertTrue(text.startswith("---\n"))
        self.assertNotIn("{{", text)
        self.assertIn("guild:persona:start", body)
        self.assertIn("guild:persona:end", body)
        self.assertNotIn(">>> RESULT", body)

    def test_role_file_says_the_engine_branches_on_enum_fields_only(self):
        body = instructions.default_role_file("leader")
        for must in ("branches only on the enum and boolean fields", "`note`", "`evidence`",
                     "never reads them to decide", "Binary, not hedged", "guild:plan-decision",
                     "CLOSED", "COMPLETED", "`partial`", "`unclear`", "blocker", "mandatory rule",
                     "`completed`", "`not-planned`", "no memory of earlier calls"):
            with self.subTest(must=must):
                self.assertIn(must, body)

    def test_frame_rules(self):
        frame = instructions.leader_frame()
        self.assertEqual(frame, instructions.leader_frame())
        for must in ("leader-input.json", "enum and boolean fields only", "read-only view", "no shell",
                     "`confirmed` standards bind", "2000 lines", "Untrusted text", "no secrets"):
            with self.subTest(must=must):
                self.assertIn(must, frame)
        self.assertNotIn("discoveries", frame, "the leader has no work-result fields")

    def test_every_situation_has_a_task_and_the_d9_ones_do_not(self):
        for situation in codes.LEADER_ANSWER_SCHEMAS:
            with self.subTest(situation=situation):
                self.assertTrue(instructions.leader_task_text(situation).strip())
        self.assertEqual(set(LEADER_INPUT_SECTIONS), set(codes.LEADER_ANSWER_SCHEMAS))
        for none in (codes.StopReason.RULE_UNFILLABLE.value, codes.StopReason.BASE_RED.value, "control-file", "x"):
            with self.subTest(none=none), self.assertRaises(ValueError):
                instructions.leader_task_text(none)

    def test_needs_leader_tasks_carry_the_common_part_and_only_their_own_situation(self):
        for s in NEEDS_LEADER_SITUATIONS:
            with self.subTest(situation=s):
                text = instructions.leader_task_text(s)
                self.assertIn("**Reason codes**", text)
                self.assertEqual(text.count("## Situation: "), 1)
                self.assertIn("## Situation: " + s, text)

    def test_tasks_name_the_leader_input_sections_that_exist(self):
        import json, os
        with open(os.path.join(os.path.dirname(instructions.DATA_DIR), "schemas", "leader-input.schema.json")) as f:
            props = json.load(f)["properties"]
        for situation, key in LEADER_INPUT_SECTIONS.items():
            with self.subTest(situation=situation):
                self.assertIn(key, props)
                self.assertIn(f"`{key}`", instructions.leader_task_text(situation))

    def test_reason_codes_in_the_needs_leader_table_are_real(self):
        table = instructions.leader_task_text("blocked").split("**Reason codes**")[1].split("The engine allows")[0]
        found = re.findall(r"`([a-z]+(?:-[a-z]+)+|other)`", table)
        self.assertTrue(found)
        for tok in found:
            self.assertIn(tok, codes.LeaderReason.values())

    def test_tasks_teach_only_answers_of_their_row(self):
        for situation in codes.LEADER_ANSWER_SCHEMAS:
            row = set(codes.STAGE2_ALLOWED_ANSWERS[situation])
            text = instructions.leader_task_text(situation)
            if situation in ("plan-gate", "done-gate"):
                taught = set(re.findall(r"^- `([a-z-]+)`", text, re.M)) & set(codes.LeaderAnswer.values())
                with self.subTest(situation=situation):
                    self.assertEqual(taught, row)

    def test_plan_gate_leaves_risk_to_the_engine_and_asks_for_the_row_check(self):
        text = instructions.leader_task_text("plan-gate")
        self.assertIn("never reaches you", text)                      # D4 conservative: risk high goes to a human
        self.assertIn("<!-- guild:plan-decision -->", text)
        for must in ("missing_requirements", "requirements", "covered", "analyze", "close.reason", "prerequisite"):
            self.assertIn(must, text)

    def test_done_gate_teaches_the_ac_and_discovery_codes(self):
        text = instructions.leader_task_text("done-gate")
        for v in codes.AcVerdict.values() + list(codes.STAGE2_DISPOSITIONS):      # `duplicate`: session A (E19)
            self.assertIn(f"`{v}`", text)
        self.assertIn("manual-test-checklist.md", text)

    def test_new_comment_task_teaches_every_effect(self):
        text = instructions.leader_task_text("new-collaborator-comment")
        for v in codes.CommentEffect.values():
            self.assertIn(f"`{v}`", text)

    def test_leader_texts_do_not_carry_unparseable_ac_tokens(self):
        for situation in codes.LEADER_ANSWER_SCHEMAS:
            with self.subTest(situation=situation):
                acparse.parse_test_case_refs(instructions.leader_task_text(situation))

    def test_leader_instruction(self):
        f = {"issue": 7, "step": "plan", "attempt": 1, "in_dir": "/h/in", "docs": ["docs/specs/7/analysis.md"],
             "in_files": ["leader-input.json", "issue.md"], "format_retry": 0, "errors": []}
        text = instructions.build_leader_instruction("plan-gate", f)
        self.assertTrue(text.startswith(instructions.leader_frame().rstrip()))
        self.assertLess(text.index("## Task — situation `plan-gate`"), text.index("## This call"))
        self.assertIn("Issue #7 · situation `plan-gate` · step `plan` · call 1 · role `leader`", text)
        self.assertIn("- `leader-input.json`", text)
        self.assertIn("- `docs/specs/7/analysis.md`", text)
        self.assertNotIn("rejected", text)
        self.assertEqual(text, instructions.build_leader_instruction("plan-gate", dict(f)))
        again = instructions.build_leader_instruction(
            "plan-gate", dict(f, format_retry=1, errors=["requirements-not-covering: R2 is missing"]))
        self.assertIn("Your previous answer was rejected", again)
        self.assertIn("- requirements-not-covering: R2 is missing", again)
        with self.assertRaises(ValueError):
            instructions.build_leader_instruction("base-red", f)

    def test_stage3_leader_texts_never_reach_a_stage2_call(self):
        """E36: below stage 3 the leader texts are the stage-2 files, byte for byte."""
        import os
        for situation in codes.LEADER_ANSWER_SCHEMAS:
            with self.subTest(situation=situation):
                self.assertEqual(instructions.leader_task_text(situation, stage=2),
                                 instructions.leader_task_text(situation, stage=1))
        with open(os.path.join(instructions.DATA_DIR, "tasks", "plan-gate.md"), encoding="utf-8") as f:
            self.assertEqual(instructions.leader_task_text("plan-gate", stage=2), f.read().rstrip() + "\n")
        self.assertEqual(instructions.leader_task_text("plan-gate"), instructions.leader_task_text("plan-gate", stage=defaults.ENGINE_STAGE))
        for s3 in sorted(set(codes.STAGE3_LEADER_ANSWER_SCHEMAS) - set(codes.LEADER_ANSWER_SCHEMAS)):
            with self.subTest(stage3_situation=s3), self.assertRaises(ValueError):
                instructions.leader_task_text(s3, stage=2)
        for none in ("irreversible-change", "rule-unfillable", "base-red"):
            with self.subTest(none=none), self.assertRaises(ValueError):
                instructions.leader_task_text(none, stage=3)
        f = {"issue": 7, "step": "plan", "attempt": 1}
        self.assertNotEqual(instructions.build_leader_instruction("plan-gate", f, stage=3),
                            instructions.build_leader_instruction("plan-gate", f, stage=2))

    def test_stage3_needs_leader_texts(self):
        """The stage-3 needs-leader file: one common addition, situation sections replace / add (E7)."""
        for s in NEEDS_LEADER_SITUATIONS:
            with self.subTest(situation=s):
                three = instructions.leader_task_text(s, stage=3)
                self.assertEqual(three.count("## Situation: "), 1)
                self.assertIn("## Situation: " + s, three)
                self.assertIn("**Reason codes**", three)
                self.assertIn("**Stage 3 additions**", three)
                self.assertNotIn("**Stage 3 additions**", instructions.leader_task_text(s, stage=2))
                acparse.parse_test_case_refs(three)
        blocked = instructions.leader_task_text("blocked", stage=3)
        for must in ("`repro:`", "rerun reproduce", "rerun diagnose", "`replan`", "`fix`", "`implement`", "`transform`"):
            self.assertIn(must, blocked)
        table = blocked.split("**Reason codes**")[1].split("The engine allows")[0]
        for tok in re.findall(r"`([a-z]+(?:-[a-z]+)+|other)`", table):
            self.assertIn(tok, codes.LeaderReason.values())

    def test_stage3_done_gate(self):
        """E18 (V7), E19–E21 (V8): the stage-3 done-gate text replaces the stage-2 one from stage 3."""
        import json, os
        text = instructions.leader_task_text("done-gate", stage=3)
        self.assertNotEqual(text, instructions.leader_task_text("done-gate", stage=2))
        for must in ("`included_fixes`", "`F1 … Fn`", "`keep`", "`out-of-scope`", "every included fix is `keep`",
                     "There is no `replan` here", "`blocks_current_ac`", "manual-test-checklist.md"):
            with self.subTest(must=must):
                self.assertIn(must, text)
        for v in codes.AcVerdict.values() + list(codes.DiscoveryDisposition.values()) + list(codes.FixVerdict.values()):
            if v in codes.STAGE2_DISPOSITIONS or v in codes.FixVerdict.values() or v in codes.AcVerdict.values():
                self.assertIn(f"`{v}`", text)
        taught = set(re.findall(r"^- `([a-z-]+)`", text.split("**Choosing the answer**")[1], re.M)) & set(codes.LeaderAnswer.values())
        self.assertEqual(taught, set(codes.STAGE3_ALLOWED_ANSWERS["done-gate"]))
        with open(os.path.join(os.path.dirname(instructions.DATA_DIR), "schemas", "leader-input.schema.json")) as fh:
            done = next(a for a in json.load(fh)["properties"]["done_gate"]["anyOf"] if a.get("type") == "object")
        for key in ("included_fixes", "discoveries", "requests", "runs", "reviews"):
            self.assertIn(key, done["properties"])
            self.assertIn(f"`{key}`", text)
        acparse.parse_test_case_refs(text)
        frame = instructions.frame("review", "tester", "judge", stage=3)
        self.assertIn("11. **Blocking discoveries.**", frame)

    def test_stage3_done_gate_followups(self):
        """E19–E21 (V8): four dispositions with title / duplicate_of, the candidates, the security path."""
        text = instructions.leader_task_text("done-gate", stage=3)
        for v in codes.DiscoveryDisposition.values():
            self.assertIn(f"`{v}`", text)
        for must in ("`title`", "`duplicate_of`", "`followup_candidates`", "At most five", "Offered only when there are candidates",
                     "`security` discovery is never written into the pull request", "`ignore`, with the Issue number"):
            with self.subTest(must=must):
                self.assertIn(must, text)
        import json, os
        with open(os.path.join(os.path.dirname(instructions.DATA_DIR), "schemas", "leader-input.schema.json")) as fh:
            done = next(a for a in json.load(fh)["properties"]["done_gate"]["anyOf"] if a.get("type") == "object")
        self.assertIn("followup_candidates", done["properties"])
        self.assertIn("12. **Security discoveries.**", instructions.frame("work", "developer", "work", stage=3))

    def test_stage3_rerun_session(self):
        """E28 (V11): layer 5 — `session` with rerun, its reason codes, the allowed lists."""
        text = instructions.leader_task_text("on-fail-exceeded", stage=3)
        for must in ("`session`", "allowed.models", "allowed.efforts", "`high-complexity`", "`repeated-failure`", "`other`"):
            self.assertIn(must, text)
        self.assertNotIn("`session`", instructions.leader_task_text("on-fail-exceeded", stage=2))

    def test_stage3_replan_defer(self):
        """E30 (V12, P2): `defer` with replan, its limits; the analysis' deferred section."""
        import json, os
        for s in ("blocked", "on-fail-exceeded", "soft-budget", "session-limit", "output-format-twice"):
            with self.subTest(situation=s):
                text = instructions.leader_task_text(s, stage=3)
                for must in ("`defer`", "`defer.requirement_rows`", "never every row", "once per Issue", "back to `analyze`"):
                    self.assertIn(must, text)
                self.assertNotIn("`defer`", instructions.leader_task_text(s, stage=2))
        with open(os.path.join(os.path.dirname(instructions.DATA_DIR), "schemas", "leader-input.schema.json")) as fh:
            defer = next(a for a in json.load(fh)["properties"]["defer"]["anyOf"] if a.get("type") == "object")
        self.assertIn("requirement_rows", defer["properties"])
        body = instructions.default_role_file("requirements-engineer")
        self.assertIn("## Deferred requirements", body)
        self.assertIn("(deferred R3)", body)

    def test_stage3_situations_have_their_tasks(self):
        """E13, E15 (V6): step-add-limit / step-removal-request — their leader-input section and only their row's answers."""
        import json, os
        with open(os.path.join(os.path.dirname(instructions.DATA_DIR), "schemas", "leader-input.schema.json")) as fh:
            props = json.load(fh)["properties"]
        for situation, section in (("step-add-limit", "add_limit"), ("step-removal-request", "removal")):
            with self.subTest(situation=situation):
                text = instructions.leader_task_text(situation, stage=3)
                self.assertIn(section, props)
                self.assertIn(f"`{section}`", text)
                self.assertEqual(text.count("## Situation: "), 1)
                own = text.split("## Situation: " + situation)[1]
                taught = set(re.findall(r"^- `([a-z-]+)`", own, re.M)) & set(codes.LeaderAnswer.values())
                self.assertEqual(taught, set(codes.STAGE3_ALLOWED_ANSWERS[situation]))
                acparse.parse_test_case_refs(text)
        self.assertIn("`skip_step`", instructions.leader_task_text("step-removal-request", stage=3))

    def test_every_stage3_situation_has_a_task(self):
        """With V13 every leader situation of stage 3 has its text; the human-only and D9 ones have none."""
        for situation in codes.STAGE3_LEADER_ANSWER_SCHEMAS:
            with self.subTest(situation=situation):
                self.assertTrue(instructions.leader_task_text(situation, stage=3).strip())
                instructions.build_leader_instruction(situation, {"issue": 3, "step": "pr", "attempt": 1}, stage=3)
        text = instructions.leader_task_text("pr-review", stage=3)
        self.assertIn("`pr_review`", text)
        self.assertIn("pr-review.md", text)
        for v in codes.ReviewEffect.values():
            self.assertIn(f"`{v}`", text)
        own = text.split("## Situation: pr-review")[1]
        taught = set(re.findall(r"^- `([a-z-]+)`", own, re.M)) & set(codes.LeaderAnswer.values())
        self.assertEqual(taught, set(codes.STAGE3_ALLOWED_ANSWERS["pr-review"]))
        for tok in re.findall(r"`(comment-no-effect|real-defect|upstream-gap|analysis-gap|needs-human-decision)`", own):
            self.assertIn(tok, codes.LeaderReason.values())
        self.assertIn("`skippable_steps`", instructions.leader_task_text("step-removal-request", stage=3))

    def test_stage3_plan_gate_teaches_templates_adjust_and_models(self):
        """V3 (E1–E4, E12, E28): the stage-3 plan-gate text names the answer's new fields and inputs."""
        import json, os
        text = instructions.leader_task_text("plan-gate", stage=3)
        for must in ("`adjust`", "`models`", "`new_template_candidate`", "`requested_steps`", "`templates_unusable`",
                     "`catalog`", "`safety_net`", "allowed.models", "allowed.efforts", "catalog_adds_max",
                     "never reaches you", "<!-- guild:plan-decision -->", "missing_requirements"):
            with self.subTest(must=must):
                self.assertIn(must, text)
        for name in codes.STAGE3_TEMPLATES:
            self.assertIn(f"`{name}`", text)
        for (typ, net), names in codes.TYPE_TEMPLATES.items():
            self.assertIn(f"`{typ}`", text)
        for value in ("`safety_net: none`", "`with-refactor`", "`only`"):
            self.assertIn(value, text)
        taught = set(re.findall(r"^- `([a-z-]+)`", text, re.M)) & set(codes.LeaderAnswer.values())
        self.assertEqual(taught, set(codes.STAGE3_ALLOWED_ANSWERS["plan-gate"]))
        with open(os.path.join(os.path.dirname(instructions.DATA_DIR), "schemas", "leader-input.schema.json")) as fh:
            plan_gate = next(a for a in json.load(fh)["properties"]["plan_gate"]["anyOf"] if a.get("type") == "object")
        for key in ("requested_steps", "catalog", "templates_unusable", "templates"):
            self.assertIn(key, plan_gate["properties"])
        for e in instructions.load_catalog_data()["entries"]:
            if e["class"] != "fix":
                self.assertIn(f"`{e['id']}`", text)
        acparse.parse_test_case_refs(text)

    def test_leader_instruction_for_a_needs_leader_call_has_no_other_situation(self):
        text = instructions.build_leader_instruction("soft-budget", {"issue": 3, "step": "test", "attempt": 2})
        self.assertIn("## Situation: soft-budget", text)
        self.assertNotIn("## Situation: blocked", text)
        self.assertIn("(none)", text)


class Instruction(unittest.TestCase):
    def test_judge_instruction(self):
        text = instructions.build_instruction(role_step(), fields(in_files=["issue.md"], in_dir="/h/in"))
        self.assertIn("Judge step rules", text)
        self.assertIn("## Task — step `design`", text)
        self.assertIn("Issue #7 · step `design` · attempt 1 · role `tech-lead`", text)
        self.assertIn("- `docs/specs/7/analysis.md`", text)
        self.assertIn("### Outputs — write exactly these paths and nothing else", text)
        self.assertIn("- `docs/specs/7/skeleton.md`", text)
        self.assertIn("`/h/in`", text)
        self.assertNotIn("Required checks", text)
        self.assertLess(text.index("Judge step rules"), text.index("## Task"))      # variable part last
        self.assertLess(text.index("## Task"), text.index("## This attempt"))

    def test_review_instruction_lists_checks_and_rule_marks(self):
        checks = ["diff-review", "test-change-review"]
        text = instructions.build_instruction(
            role_step("review-audit", "auditor", checks=checks),
            fields(role="auditor", checks=checks, rule_checks=["test-change-review"], outputs=[],
                   inputs=["in:review.diff"], in_files=["review.diff"], in_dir="/h/in"))
        self.assertIn("Review step rules", text)
        self.assertIn("### Required checks", text)
        self.assertIn("`diff-review`", text)
        self.assertIn("`reviewed` must cover every changed file", text)
        self.assertRegex(text, r"(?m)^- `test-change-review`[^\n]*may not be `n/a`")
        self.assertNotRegex(text, r"(?m)^- `diff-review`[^\n]*may not be `n/a`")
        self.assertIn("None: you write no file.", text)
        self.assertNotIn("in:review.diff", text)                       # engine files are not repo paths

    def test_work_instruction(self):
        text = instructions.build_instruction(
            role_step("implement", "developer"),
            fields(role="developer", outputs=[], inputs=["docs/specs/7/skeleton.md"]))
        self.assertIn("Work step rules (developer)", text)
        self.assertIn("the committed change on this branch", text)
        self.assertIn("Sandbox and toolchain", text)
        self.assertNotIn("### Repository commands", text)

    def test_work_instruction_shows_the_repository_toolchain(self):
        """P5 F2: the developer sees the named commands' text (their PATH / HOME prefix) and
        the variable names the engine set; a judge never gets the section."""
        cmd = 'export PATH="$GLD_FLUTTER_ROOT/bin:$PATH"; export HOME="$GLD_HOME"; flutter test'
        tc = {"commands": {"test": cmd, "lint": "flutter analyze"}, "env_names": ["GLD_FLUTTER_ROOT", "GLD_HOME"]}
        text = instructions.build_instruction(role_step("implement", "developer"),
                                              fields(role="developer", outputs=[]), toolchain=tc)
        self.assertIn("### Repository commands", text)
        self.assertIn(cmd, text)
        self.assertIn("`GLD_FLUTTER_ROOT`, `GLD_HOME`", text)
        self.assertLess(text.index("Sandbox and toolchain"), text.index("### Repository commands"))
        with self.assertRaises(ValueError):
            instructions.build_instruction(role_step(), fields(), toolchain=tc)
        self.assertEqual(instructions.toolchain_section({"commands": {}, "env_names": []}), "")

    def test_returned_and_reentry_and_facts(self):
        text = instructions.build_instruction(
            role_step("implement", "developer"),
            fields(role="developer", outputs=[], facts={"b": 2, "a": "x" * 5000, "flaky": ["test"]},
                   returned={"from_step": "test", "from_attempt": 1, "code": "check-failed",
                             "detail": "run-nonzero", "errors": ["e1", "e2"]},
                   reentry={"forward_only": False, "dirty_files": ["src/a.py", "src/b.py"]}))
        self.assertIn("comes back from step `test` (attempt 1), failure code `check-failed`", text)
        self.assertIn("- e1\n- e2", text)
        self.assertIn("NO — check the history", text)
        self.assertIn("- `src/a.py`\n- `src/b.py`", text)
        self.assertLess(text.index("- a:"), text.index("- b:"))        # sorted facts
        self.assertIn("more characters]", text)                          # long facts are clipped
        self.assertIn('- flaky: ["test"]', text)

    def test_clean_reentry(self):
        text = instructions.build_instruction(
            role_step("implement", "developer"),
            fields(role="developer", outputs=[], reentry={"forward_only": True, "dirty_files": []}))
        self.assertIn("The tree was clean when this attempt started.", text)

    def test_deterministic(self):
        a = instructions.build_instruction(role_step(), fields(facts={"x": 1, "y": 2}))
        b = instructions.build_instruction(role_step(), fields(facts={"y": 2, "x": 1}))
        self.assertEqual(a, b)

    def test_custom_step_without_a_task_still_gets_the_frame(self):
        text = instructions.build_instruction(role_step("custom-step"), fields(step="custom-step"))
        self.assertIn("These rules win over your role file", text)
        self.assertNotIn("## Task", text)

    def test_only_role_steps_and_valid_roles(self):
        with self.assertRaises(ValueError):
            instructions.build_instruction({"id": "test", "kind": "run", "name": "test"}, fields())
        with self.assertRaises(ValueError):
            instructions.build_instruction({"id": "x", "kind": "role"}, fields(role=None))

    def test_accepts_objects_with_attributes(self):
        class S:
            id = "design"
            kind = "role"
            name = "tech-lead"
            checks = []
        self.assertIn("step `design`", instructions.build_instruction(S(), fields()))


class SystemPrompt(unittest.TestCase):
    def test_order_and_frontmatter(self):
        text = instructions.system_prompt("ROOT", "DOT", "---\nname: x\n---\nBODY")
        self.assertLess(text.index("ROOT"), text.index("DOT"))
        self.assertLess(text.index("DOT"), text.index("BODY"))
        self.assertNotIn("name: x", text)
        self.assertIn("# Repository instructions — CLAUDE.md", text)
        self.assertIn("# Your role file", text)

    def test_missing_parts_are_skipped(self):
        self.assertEqual(instructions.system_prompt(None, "", "BODY"), "# Your role file\n\nBODY\n")
        self.assertEqual(instructions.system_prompt("ROOT", None, None), "# Repository instructions — CLAUDE.md\n\nROOT\n")
        self.assertEqual(instructions.system_prompt(None, None, None), "")
        self.assertEqual(instructions.system_prompt("  \n", "", ""), "")

    def test_claude_md_is_not_frontmatter_stripped(self):
        self.assertIn("---\nkeep: me\n---", instructions.system_prompt("---\nkeep: me\n---\nrules", None, "B"))

    def test_strip_frontmatter(self):
        s = instructions.strip_frontmatter
        self.assertEqual(s("---\na: b\n---\nbody\n"), "body\n")
        self.assertEqual(s("---\r\na: b\r\n---\r\n\r\nbody"), "body")
        self.assertEqual(s("﻿---\na: 1\n...\nbody"), "body")
        self.assertEqual(s("no frontmatter\n---\nrule\n"), "no frontmatter\n---\nrule\n")
        self.assertEqual(s("---\n---\nempty header"), "empty header")
        with self.assertRaises(ValueError):
            s("---\na: b\nnever closed")


class DataLoaders(unittest.TestCase):
    def test_start_procedure_and_templates_load(self):
        start = instructions.load_start_procedure()
        self.assertEqual([s["id"] for s in start["steps"]], ["analyze", "ac-format", "plan"])
        # the default is defaults.ENGINE_STAGE (3 since Q4): every template; stages 1-2 know only feature
        self.assertEqual(instructions.default_template_names(), sorted(codes.STAGE3_TEMPLATES))
        self.assertEqual(instructions.load_default_template("bug")["template"], "bug")
        for stage in (1, 2):
            self.assertEqual(instructions.default_template_names(stage), ["feature"])
            self.assertEqual(instructions.load_default_template("feature", stage)["template"], "feature")
            with self.assertRaises(KeyError):
                instructions.load_default_template("bug", stage)
        with self.assertRaises(KeyError):
            instructions.load_default_template("../start")

    def test_catalog_has_every_required_check(self):
        for rc in codes.RequiredCheck.values():
            self.assertIn(rc, instructions.CHECK_CATALOG)

    def test_every_template_role_has_model_and_effort_defaults(self):
        steps = instructions.load_start_procedure()["steps"] + instructions.load_default_template("feature")["steps"]
        for s in steps:
            role = s.get("role")
            if role:
                with self.subTest(role=role):
                    self.assertTrue(role in defaults.MODEL_EFFORT or any(k.startswith(role + "/") for k in defaults.MODEL_EFFORT))


if __name__ == "__main__":
    unittest.main()
