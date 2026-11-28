"""P2-0 contracts: schema files, examples, enum ↔ schema sync, render fixtures, module boundaries.

These tests keep the parallel sessions (README "Parallel sessions") from drifting apart:
a session that changes a contract changes the schema, codes.py, the examples and the
fixtures together, or these tests fail.
"""

import ast
import copy
import json
import os
import sys
import unittest

from gxengine import codes, defaults, render
from gxengine import schema as S

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ENGINE, "gxengine")
FIX = os.path.join(ENGINE, "tests", "fixtures")


def load(*parts):
    with open(os.path.join(FIX, *parts), encoding="utf-8") as f:
        return json.load(f)


def enum_at(schema, *path):
    node = schema
    for p in path:
        node = node[p]
    return node["enum"]


LEADER_ANSWER_NAMES = ("leader-answer", "leader-answer-plan-gate", "leader-answer-done-gate", "leader-answer-new-comment")
S3_LEADER_ANSWER_NAMES = ("leader-answer-s3", "leader-answer-plan-gate-s3", "leader-answer-done-gate-s3",
                          "leader-answer-step-removal", "leader-answer-pr-review")
S3_RESULT_NAMES = ("result-work-s3", "result-review-s3")
TEMPLATE_NAMES = LEADER_ANSWER_NAMES + S3_LEADER_ANSWER_NAMES + S3_RESULT_NAMES      # enum templates


def filled(name, fill):
    """An enum template (leader answers, stage-3 results) with its tokens filled."""
    return S.fill_enums(S.load_schema(name), fill)


class SchemaFiles(unittest.TestCase):
    EXPECTED = {"brief", "facts", "log-line", "procedure", "repo-config", "result-review", "result-work", "state", "template",
                "leader-input", "catalog", *TEMPLATE_NAMES,
                # stage 4 (V1)
                "sprint-state", "sprint-log-line", "base-green", "init-decisions", "mutations", "mutation-record",
                # readiness R1
                "incident", "fixed-defects"}

    def test_every_schema_present_and_keyword_checked(self):
        self.assertEqual(set(S.schema_names()), self.EXPECTED)
        for name in S.schema_names():
            with self.subTest(name=name):
                sch = S.load_schema(name)
                self.assertEqual(sch["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_every_example_is_valid(self):
        for name in self.EXPECTED:
            with self.subTest(name=name):
                ex = load("contracts", f"{name}.example.json")
                if name in TEMPLATE_NAMES:      # enum templates: the example carries its fill
                    S.validate(ex["answer"], filled(name, ex["fill"]))
                else:
                    S.validate(ex, name)

    def test_extra_examples_are_valid(self):
        """<schema>.<variant>.example.json (e.g. state.stage2) — every file in contracts/ is checked."""
        names = os.listdir(os.path.join(FIX, "contracts"))
        for f in names:
            with self.subTest(f=f):
                self.assertTrue(f.endswith(".example.json"), f)
                base = f[: -len(".example.json")].split(".")[0]
                self.assertIn(base, self.EXPECTED)
                if "." in f[: -len(".example.json")]:
                    S.validate(load("contracts", f), base)


class Negative(unittest.TestCase):
    """Things the grammar must refuse (§4, §4.3, §6.2)."""

    def proc(self):
        return load("contracts", "procedure.example.json")

    def assertInvalid(self, obj, name):
        self.assertFalse(S.is_valid(obj, name), f"{name} accepted: {json.dumps(obj)[:200]}")

    def test_procedure_refuses_when_loops_variables(self):
        for extra in ({"when": "ui"}, {"loop": 2}, {"vars": {}}, {"model": "opus"}, {"note": "why"}):
            p = self.proc()
            p["steps"][3].update(extra)
            with self.subTest(extra=extra):
                self.assertInvalid(p, "procedure")

    def test_procedure_refuses_command_strings(self):
        p = self.proc()
        p["steps"][1]["run"] = "pnpm test -- --ci"
        self.assertInvalid(p, "procedure")
        p = self.proc()
        p["steps"][3]["outputs"] = ["docs/a.md; rm -rf /"]
        self.assertInvalid(p, "procedure")

    def test_procedure_refuses_two_kinds_and_bad_paths(self):
        p = self.proc()
        p["steps"][3]["run"] = "test"           # role + run
        self.assertInvalid(p, "procedure")
        for bad in ("/etc/passwd", "../x", "a/../../x", "in:secrets.txt"):
            p = self.proc()
            p["steps"][3]["inputs"] = [bad]
            with self.subTest(bad=bad):
                self.assertInvalid(p, "procedure")

    def test_run_steps_have_no_outputs_or_checks(self):
        for key, val in (("outputs", ["x.md"]), ("checks", ["diff-review"])):
            p = self.proc()
            p["steps"][1][key] = val
            with self.subTest(key=key):
                self.assertInvalid(p, "procedure")

    def test_state_core_fields_required(self):
        base = load("contracts", "state.example.json")
        for key in ("format", "issue", "revision", "steps", "last_head"):
            s = copy.deepcopy(base)
            del s[key]
            with self.subTest(key=key):
                self.assertInvalid(s, "state")
        for key in ("id", "status", "latest_attempt"):
            s = copy.deepcopy(base)
            del s["steps"][0][key]
            with self.subTest(step_key=key):
                self.assertInvalid(s, "state")
        s = copy.deepcopy(base)
        s["format"] = 2
        self.assertInvalid(s, "state")

    def test_result_status_is_done_or_blocked_only(self):
        r = load("contracts", "result-work.example.json")
        r["status"] = "DONE_WITH_CONCERNS"
        self.assertInvalid(r, "result-work")

    def test_review_result_requires_review_fields(self):
        work = load("contracts", "result-work.example.json")
        self.assertInvalid(work, "result-review")
        r = load("contracts", "result-review.example.json")
        r["checks"][0]["result"] = "skipped"
        self.assertInvalid(r, "result-review")

    def test_facts_judgment_fields_required(self):
        base = load("contracts", "facts.example.json")
        for key in ("exit_code", "changed_files", "start_head", "start_tree", "end_tree", "outputs", "session"):
            f = copy.deepcopy(base)
            del f[key]
            with self.subTest(key=key):
                self.assertInvalid(f, "facts")

    def test_repo_config_refuses_unknown_plugin_and_bad_names(self):
        c = load("contracts", "repo-config.example.json")
        c["commands"]["lint"] = {"plugin": "rm-rf"}
        self.assertInvalid(c, "repo-config")
        c = load("contracts", "repo-config.example.json")
        c["commands"]["Run Tests"] = {"cmd": "x"}
        self.assertInvalid(c, "repo-config")
        c = load("contracts", "repo-config.example.json")
        c["commands"]["x"] = {"cmd": "x", "plugin": "ac-format"}
        self.assertInvalid(c, "repo-config")

    def test_repo_config_allow_write_is_absolute_or_user_tmp(self):
        """P3-0: sandbox_exceptions.allow_write — absolute path or {user_tmp}, no forbidden component."""
        def cfg(path):
            c = load("contracts", "repo-config.example.json")
            c["sandbox_exceptions"] = {"allow_write": [path]}
            return c
        for ok in (defaults.USER_TMP_TOKEN, "/opt/build-out", "/private/var/folders/ab/cd/T", "/Users/u/work/out"):
            with self.subTest(ok=ok):
                S.validate(cfg(ok), "repo-config")
        bad = ["build/out", "", "/", "~/x", "$HOME/x", "{user_tmp}/x", "{cache}", "/a/../b", "/a/./b", "/a//b",
               "/a b", "/tmp/*", "/a/[x]", "/r/.Git/hooks", "/r/.claude", "/r/pkg/.CLAUDE/x", "/r/CLAUDE.md",
               "/u/.ssh", "/u/.config/gh", "/u/.config/gcloud/x", "/u/Library/Keychains", "/u/.npmrc"]
        bad += [f"/u/{c}" for c in defaults.ALLOW_WRITE_FORBIDDEN_COMPONENTS]
        for b in bad:
            with self.subTest(bad=b):
                self.assertInvalid(cfg(b), "repo-config")

    def test_repo_config_exception_flags_are_booleans(self):
        for flag in ("allow_local_binding", "weaker_network_isolation"):
            c = load("contracts", "repo-config.example.json")
            c["sandbox_exceptions"] = {flag: True}
            S.validate(c, "repo-config")
            c["sandbox_exceptions"] = {flag: "yes"}
            self.assertInvalid(c, "repo-config")

    def test_repo_config_run_env_names_and_values(self):
        """P3-0: run_env — literal values, upper-case names, nothing secret-looking or engine-owned."""
        def cfg(name, value="1"):
            c = load("contracts", "repo-config.example.json")
            c["run_env"] = {name: value}
            return c
        for ok in ("TURBO_TELEMETRY_DISABLED", "CI", "_X1", "NEXT_TELEMETRY_DISABLED", "FLUTTER_SUPPRESS_ANALYTICS"):
            with self.subTest(ok=ok):
                S.validate(cfg(ok), "repo-config")
        bad = ["lower", "1X", "A-B", "", "NPM_TOKEN", "MY_SECRET_X", "API_KEY", "KEYCHAIN", "DB_PASSWORD",
               "PASSWD", "AWS_CREDENTIALS", "GIT_DIR", "SSH_AUTH_SOCK", "CLAUDECODE", "CLAUDE_CONFIG_DIR",
               "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "GH_HOST", "GITHUB_ACTIONS", "ANTHROPIC_BASE_URL",
               "GOOGLE_X", "GCLOUD_X", "CLOUDSDK_X", "AZURE_X"]
        bad += list(defaults.RUN_ENV_RESERVED)
        for b in bad:
            with self.subTest(bad=b):
                self.assertInvalid(cfg(b), "repo-config")
        for value in ("{cache}/x", "a\nb", "a\x00", "{user_tmp}"):
            with self.subTest(value=value):
                self.assertInvalid(cfg("CI", value), "repo-config")

    def test_run_env_schema_matches_defaults(self):
        """The schema's run_env name rules cover every defaults list (schema ↔ defaults sync)."""
        import fnmatch
        for word in defaults.RUN_ENV_SECRET_WORDS:
            self.assertFalse(S.is_valid({"format": 1, "commands": {"t": {"cmd": "x"}}, "run_env": {f"A_{word}_B": "1"}}, "repo-config"), word)
        for prefix in defaults.RUN_ENV_RESERVED_PREFIXES:
            self.assertFalse(S.is_valid({"format": 1, "commands": {"t": {"cmd": "x"}}, "run_env": {prefix + "X": "1"}}, "repo-config"), prefix)
        # every scrub pattern is refused as a run_env name
        samples = {p.replace("*", "X") for p in defaults.ENV_SCRUB_PATTERNS}
        for name in samples:
            if any(fnmatch.fnmatchcase(name, p) for p in defaults.ENV_SCRUB_PATTERNS):
                self.assertFalse(S.is_valid({"format": 1, "commands": {"t": {"cmd": "x"}}, "run_env": {name: "1"}}, "repo-config"), name)

    def test_log_line_who(self):
        line = load("contracts", "log-line.example.json")
        for who in ("role:developer", "leader", "human", "sprint"):
            line["who"] = who
            self.assertTrue(S.is_valid(line, "log-line"), who)
        line["who"] = "developer"
        self.assertInvalid(line, "log-line")


class EnumSync(unittest.TestCase):
    """codes.py is the one enum module; the schema files must list exactly the same values."""

    def test_step_status(self):
        want = set(codes.StepStatus.values())
        self.assertEqual(set(enum_at(S.load_schema("state"), "$defs", "status")), want)
        self.assertEqual(set(enum_at(S.load_schema("log-line"), "properties", "to")), want)
        self.assertEqual(set(enum_at(S.load_schema("log-line"), "properties", "from")), want)
        facts = S.load_schema("facts")["properties"]["outcome"]["anyOf"][1]["properties"]
        self.assertEqual(set(facts["status"]["enum"]), want)

    def test_stop_reasons(self):
        self.assertEqual(set(enum_at(S.load_schema("state"), "$defs", "stop_reason")), set(codes.StopReason.values()))
        self.assertTrue(codes.STAGE3_LEADER_SITUATIONS <= set(codes.StopReason.values()))
        self.assertTrue(set(codes.ALLOWED_ANSWERS) <= codes.LEADER_SITUATIONS)
        for answers in codes.ALLOWED_ANSWERS.values():
            self.assertTrue(set(answers) <= set(codes.LeaderAnswer.values()))

    def test_failure_codes(self):
        want = set(codes.FailureCode.values())
        brief = S.load_schema("brief")["properties"]["returned"]["anyOf"][1]["properties"]["code"]["enum"]
        self.assertEqual(set(brief) - {None}, want)      # null: stage 3, a rerun answer without a failed attempt
        facts = S.load_schema("facts")["properties"]["outcome"]["anyOf"][1]["properties"]["code"]["enum"]
        self.assertEqual(set(facts) - {None}, want)

    def test_log_events_and_reasons(self):
        log = S.load_schema("log-line")["properties"]
        self.assertEqual(set(log["event"]["enum"]), set(codes.LogEvent.values()))
        self.assertEqual(set(log["trigger"]["enum"]), set(codes.Trigger.values()))
        self.assertEqual(set(log["reason"]["enum"]), set(codes.LeaderReason.values()))

    def test_step_kinds_checks_ops(self):
        d = S.load_schema("procedure")["$defs"]
        kinds = {k for k in ("role", "run", "check", "op") if k in d[f"{k}_step"]["required"]}
        self.assertEqual(kinds, set(codes.StepKind.values()))
        branches = [b["$ref"].split("/")[-1] for b in d["step"]["oneOf"]]
        self.assertEqual(branches, [f"{k}_step" for k in ("role", "run", "check", "op")])
        self.assertEqual(set(d["check_step"]["properties"]["check"]["enum"]), set(codes.CheckKind.values()))
        self.assertEqual(set(d["op_step"]["properties"]["op"]["enum"]), set(codes.OpKind.values()))
        in_pat = next(b["pattern"] for b in d["input"]["anyOf"] if "pattern" in b)
        for name in codes.InFile.values():
            self.assertIn(name.replace(".", "\\."), in_pat)

    def test_result_enums(self):
        for name in ("result-work", "result-review", *S3_RESULT_NAMES):
            p = S.load_schema(name)["properties"]
            triggers = codes.Trigger.values() if name in S3_RESULT_NAMES else codes.STAGE2_TRIGGERS
            self.assertEqual(set(p["status"]["enum"]), set(codes.ResultStatus.values()))
            self.assertEqual(set(p["requests"]["items"]["properties"]["op"]["enum"]), set(codes.RequestOp.values()))
            self.assertEqual(list(p["requests"]["items"]["properties"]["trigger"]["enum"]), list(triggers))
            self.assertEqual(set(p["blocked_by"]["properties"]["kind"]["enum"]), set(codes.BlockedKind.values()))
            self.assertEqual(set(p["discoveries"]["items"]["properties"]["kind"]["enum"]), set(codes.DiscoveryKind.values()))
        for name in ("result-review", "result-review-s3"):
            r = S.load_schema(name)["properties"]
            self.assertEqual(set(r["verdict"]["enum"]), set(codes.Verdict.values()))
            self.assertEqual(set(r["checks"]["items"]["properties"]["result"]["enum"]), set(codes.CheckResult.values()))
            self.assertEqual(set(r["findings"]["items"]["properties"]["severity"]["enum"]), set(codes.Severity.values()))
        for name in S3_RESULT_NAMES:
            p = S.load_schema(name)["properties"]
            self.assertEqual(p["irreversible"]["items"]["properties"]["code"]["enum"], codes.IrreversibleCode.values())
        w = S.load_schema("result-work-s3")["properties"]
        self.assertEqual(w["golden_reasons"]["items"]["properties"]["reason"]["enum"], codes.GoldenReason.values())

    def test_facts_enums(self):
        f = S.load_schema("facts")["properties"]
        item = f["changed_files"]["items"]["properties"]
        self.assertEqual(set(item["change"]["enum"]), set(codes.FileChange.values()))
        self.assertEqual(set(item["where"]["enum"]), set(codes.ChangeWhere.values()))
        sess = f["session"]["anyOf"][1]["properties"]
        self.assertEqual(set(sess["end"]["enum"]), set(codes.SessionEnd.values()))

    def test_repo_config_enums(self):
        c = S.load_schema("repo-config")
        plugin = c["properties"]["commands"]["additionalProperties"]["oneOf"][1]["properties"]["plugin"]["enum"]
        self.assertEqual(set(plugin), set(codes.PluginCommand.values()))
        kinds = {b["properties"]["kind"]["const"] for b in c["properties"]["path_rules"]["items"]["oneOf"]}
        self.assertEqual(kinds, set(codes.PathRuleKind.values()))
        irr = c["properties"]["path_rules"]["items"]["oneOf"][2]["properties"]
        self.assertEqual(set(irr["level"]["enum"]), set(codes.IrreversibleLevel.values()))
        self.assertEqual(set(irr["category"]["enum"]), set(codes.IrreversibleCategory.values()))
        ver = c["properties"]["path_rules"]["items"]["oneOf"][0]["properties"]
        self.assertEqual(set(ver["category"]["enum"]), set(codes.VerificationCategory.values()))
        lv = c["properties"]["irreversible_levels"]
        self.assertEqual(set(lv["propertyNames"]["enum"]), set(codes.IrreversibleCategory.values()))
        self.assertEqual(set(lv["additionalProperties"]["enum"]), set(codes.IrreversibleLevel.values()))
        self.assertEqual(tuple(c["properties"]["allowed_models"]["items"]["enum"]), defaults.MODEL_LADDER)      # E29
        self.assertEqual(tuple(c["properties"]["allowed_efforts"]["items"]["enum"]), defaults.EFFORT_LADDER)

    def test_mode_and_role_class(self):
        self.assertEqual(set(enum_at(S.load_schema("state"), "properties", "mode")), set(codes.RunMode.values()))
        self.assertEqual(set(enum_at(S.load_schema("brief"), "properties", "role_class")) - {None},
                         set(codes.RoleClass.values()))
        self.assertEqual(codes.role_class("developer"), "work")
        self.assertEqual(codes.role_class("auditor"), "judge")

    # --- stage 2 (V1) ---------------------------------------------------------------

    def test_attempt_kinds_and_in_files(self):
        want = set(codes.AttemptKind.values())
        self.assertEqual(set(enum_at(S.load_schema("brief"), "properties", "kind")), want)
        self.assertEqual(set(enum_at(S.load_schema("facts"), "properties", "kind")), want)
        self.assertEqual(want - {"leader"}, set(codes.StepKind.values()))
        brief_in = S.load_schema("brief")["properties"]["in_files"]["items"]["enum"]
        self.assertEqual(set(brief_in), set(codes.InFile.values()))
        li = S.load_schema("leader-input")["$defs"]
        self.assertEqual(set(li["in_file"]["enum"]), set(codes.InFile.values()) - {codes.InFile.LEADER_INPUT.value},
                         "leader-input.json lists the OTHER in/ files")

    def test_leader_reason_everywhere(self):
        want = set(codes.LeaderReason.values())
        self.assertEqual(len(want), 14, "scope D20")
        for name in LEADER_ANSWER_NAMES + S3_LEADER_ANSWER_NAMES:
            self.assertEqual(set(S.load_schema(name)["properties"]["reason"]["enum"]), want, name)
        self.assertEqual(set(S.load_schema("state")["$defs"]["leader_reason"]["enum"]), want)
        self.assertEqual(set(S.load_schema("leader-input")["$defs"]["leader_reason"]["enum"]), want)
        old = {"real-defect", "high-complexity", "repeated-failure", "other"}
        self.assertTrue(old <= want, "the P2-0 draft codes stay valid (old log lines, resume --reason)")

    def test_answers_and_situations(self):
        answers = set(codes.LeaderAnswer.values())
        self.assertEqual(set(S.load_schema("state")["$defs"]["answer"]["enum"]), answers)
        li = S.load_schema("leader-input")["$defs"]
        self.assertEqual(set(li["answer"]["enum"]), answers)
        self.assertEqual(set(li["situation"]["enum"]), set(codes.STAGE3_LEADER_ANSWER_SCHEMAS))
        self.assertEqual(set(li["narrow_reason"]["enum"]), set(codes.NarrowReason.values()))
        leader = S.load_schema("brief")["properties"]["leader"]["anyOf"][1]["properties"]
        self.assertEqual(set(leader["situation"]["enum"]), set(codes.STAGE3_LEADER_ANSWER_SCHEMAS))
        self.assertEqual(set(leader["schema"]["enum"]), set(codes.LEADER_ANSWER_SCHEMAS.values())
                         | set(codes.STAGE3_LEADER_ANSWER_SCHEMAS.values()))
        self.assertEqual(set(leader["allowed_answers"]["items"]["enum"]), answers)
        stop = S.load_schema("state")["properties"]["stop"]["anyOf"][1]["properties"]
        self.assertEqual(set(stop["leader_failed"]["anyOf"][1]["properties"]["code"]["enum"]), codes.LEADER_FAILED_CODES)
        calls = S.load_schema("state")["properties"]["leader_calls"]["items"]["properties"]
        self.assertEqual(set(calls["kind"]["enum"]), {"check", "leader"})
        self.assertEqual(set(calls["failed"]["anyOf"][1]["enum"]), codes.LEADER_FAILED_CODES)
        closed = S.load_schema("state")["properties"]["closed"]["anyOf"][1]["properties"]
        self.assertEqual(set(closed["reason"]["enum"]), set(codes.CloseReason.values()))

    def test_leader_answer_situation_enums(self):
        pg = S.load_schema("leader-answer-plan-gate")["properties"]
        self.assertEqual(set(pg["close"]["properties"]["reason"]["enum"]), set(codes.CloseReason.values()))
        self.assertEqual(set(codes.GH_CLOSE_REASON), set(codes.CloseReason.values()))
        dg = S.load_schema("leader-answer-done-gate")["properties"]
        self.assertEqual(set(dg["ac_verdicts"]["items"]["properties"]["status"]["enum"]), set(codes.AcVerdict.values()))
        self.assertEqual(tuple(dg["discoveries"]["items"]["properties"]["disposition"]["enum"]), codes.STAGE2_DISPOSITIONS)
        self.assertTrue(set(codes.STAGE2_DISPOSITIONS) < set(codes.DiscoveryDisposition.values()))
        nc = S.load_schema("leader-answer-new-comment")["properties"]
        self.assertEqual(set(nc["comments"]["items"]["properties"]["effect"]["enum"]), set(codes.CommentEffect.values()))

    def test_log_line_stage2_events(self):
        events = set(S.load_schema("log-line")["properties"]["event"]["enum"])
        self.assertTrue({"leader-call", "issue-closed"} <= events)

    # --- stage 3 (V1) ---------------------------------------------------------------

    def test_stage3_leader_answer_enums(self):
        pg = S.load_schema("leader-answer-plan-gate-s3")["properties"]["plan"]["properties"]
        self.assertEqual(pg["adjust"]["items"]["properties"]["op"]["enum"], ["add"], "E12: adding only")
        self.assertEqual(pg["adjust"]["items"]["properties"]["trigger"]["enum"], codes.Trigger.values())
        dg = S.load_schema("leader-answer-done-gate-s3")["properties"]
        self.assertEqual(dg["included_fixes"]["items"]["properties"]["verdict"]["enum"], codes.FixVerdict.values())
        pr = S.load_schema("leader-answer-pr-review")["properties"]
        self.assertEqual(pr["reviews"]["items"]["properties"]["effect"]["enum"], codes.ReviewEffect.values())

    def test_stage3_state_enums(self):
        p = S.load_schema("state")["properties"]
        req = p["requests"]["items"]["properties"]
        self.assertEqual(req["trigger"]["enum"], codes.Trigger.values())
        self.assertEqual(req["op"]["enum"], codes.RequestOp.values())
        self.assertEqual(req["outcome"]["enum"], codes.RequestOutcome.values())
        self.assertEqual(req["reason"]["enum"], codes.RequestReason.values() + [None])
        self.assertEqual(set(p["catalog_adds"]["items"]["properties"]["source"]["enum"]),
                         set(codes.ProcedureSource.values()) - {"start"})
        fix = p["included_fixes"]["items"]["properties"]
        self.assertEqual(fix["verdict"]["enum"], codes.FixVerdict.values() + [None])
        self.assertEqual(set(fix["kind"]["enum"]), set(codes.DiscoveryKind.values()))
        fol = p["followups"]["items"]["properties"]
        self.assertEqual(set(fol["kind"]["enum"]), set(defaults.FOLLOWUP_TYPE_LABELS))
        self.assertTrue(set(fol["disposition"]["enum"]) <= set(codes.DiscoveryDisposition.values()))
        mo = p["model_overrides"]["additionalProperties"]["properties"]
        self.assertEqual((tuple(mo["model"]["enum"]), tuple(mo["effort"]["enum"])), (defaults.MODEL_LADDER, defaults.EFFORT_LADDER))
        self.assertEqual(set(mo["layer"]["enum"]), set(codes.ModelLayer.values()) - {"plugin-default"})
        for part in ("detected", "approved"):
            irr = p["irreversible"]["properties"][part]["items"]["properties"]
            self.assertEqual(irr["category"]["enum"], codes.IrreversibleCategory.values())
            self.assertEqual(irr["code"]["enum"], codes.IrreversibleCode.values() + [None])
        self.assertEqual(p["irreversible"]["properties"]["detected"]["items"]["properties"]["level"]["enum"],
                         codes.IrreversibleLevel.values())
        self.assertEqual(set(p["pr_review"]["properties"]["last_seen_ids"]["properties"]), set(codes.PrReviewKind.values()))
        step = S.load_schema("state")["$defs"]["step"]["properties"]
        self.assertEqual(step["return_sources"]["items"]["properties"]["cause"]["enum"], codes.ReturnCause.values())

    def test_stage3_brief_facts_enums(self):
        brief, facts = S.load_schema("brief"), S.load_schema("facts")
        self.assertEqual(brief["$defs"]["return_source"]["properties"]["cause"]["enum"], codes.ReturnCause.values())
        self.assertEqual(brief["properties"]["run"]["anyOf"][1]["properties"]["plugin"]["enum"], codes.PluginCommand.values() + [None])
        esc = brief["properties"]["session"]["anyOf"][1]["properties"]["escalation"]
        self.assertEqual(esc, facts["properties"]["session"]["anyOf"][1]["properties"]["escalation"], "one escalation object (E26)")
        self.assertEqual(esc["anyOf"][1]["properties"]["base"]["properties"]["layer"]["enum"], codes.ModelLayer.values())
        self.assertEqual(facts["$defs"]["evidence"]["properties"]["kind"]["enum"], sorted(codes.EVIDENCE_COMMANDS))
        self.assertEqual(facts["$defs"]["paths_check"]["properties"]["violations"]["items"]["properties"]["change"]["enum"],
                         codes.FileChange.values())
        g = facts["properties"]["golden"]["items"]["properties"]
        self.assertEqual(g["row"]["enum"], codes.GoldenRow.values())
        self.assertEqual(g["reason"]["enum"], codes.GoldenReason.values() + [None])

    def test_stage3_leader_input_and_catalog_enums(self):
        li = S.load_schema("leader-input")
        self.assertEqual(li["$defs"]["trigger"]["enum"], codes.Trigger.values())
        pg = li["properties"]["plan_gate"]["anyOf"][1]["properties"]
        self.assertEqual(pg["analysis"]["properties"]["safety_net"]["enum"], codes.SafetyNet.values())
        self.assertEqual(pg["catalog"]["items"]["properties"]["class"]["enum"], codes.CatalogClass.values())
        req = li["properties"]["done_gate"]["anyOf"][1]["properties"]["requests"]["items"]["properties"]
        self.assertEqual(req["outcome"]["enum"], codes.RequestOutcome.values())
        self.assertEqual(req["reason"]["enum"], codes.RequestReason.values() + [None])
        al = li["properties"]["allowed"]["properties"]
        self.assertEqual(al["narrowed"]["items"]["properties"]["field"]["enum"], sorted(codes.NARROWING_FIELDS.values()))
        self.assertEqual((tuple(al["models"]["items"]["enum"]), tuple(al["efforts"]["items"]["enum"])),
                         (defaults.MODEL_LADDER, defaults.EFFORT_LADDER))
        rid = li["properties"]["pr_review"]["anyOf"][1]["properties"]["new"]["items"]["properties"]["id"]["pattern"]
        self.assertEqual(rid, "^(" + "|".join(codes.PrReviewKind.values()) + "):[1-9][0-9]*$")
        cat = S.load_schema("catalog")["$defs"]
        self.assertEqual(cat["entry"]["properties"]["class"]["enum"], codes.CatalogClass.values())
        self.assertEqual(cat["entry"]["properties"]["on_fail"]["anyOf"][1]["properties"]["back_to"]["const"],
                         codes.CATALOG_DEVELOPER_TOKEN)
        d = S.load_schema("procedure")["$defs"]
        self.assertEqual(cat["relpath"], d["relpath"])
        self.assertEqual(d["path_token"]["enum"], [codes.path_token(k) for k in codes.TEMPLATE_PATH_KINDS])


class Stage2Tables(unittest.TestCase):
    """The stage-2 answer tables in codes.py (scope §2, D3 D4 D9 D14 D17)."""

    def test_stage1_table_unchanged(self):
        """The stage-1 path must not move: ALLOWED_ANSWERS is still the P2-0 table."""
        self.assertEqual(codes.ALLOWED_ANSWERS["plan-gate"], ("plan", "close-as-decided", "escalate"))
        self.assertNotIn("rule-unfillable", codes.ALLOWED_ANSWERS)
        self.assertNotIn("base-red", codes.ALLOWED_ANSWERS)
        self.assertIs(codes.allowed_answers_table(1), codes.ALLOWED_ANSWERS)
        self.assertIs(codes.allowed_answers_table(2), codes.STAGE2_ALLOWED_ANSWERS)
        for bad in (0, True, "2"):
            with self.assertRaises(ValueError):
                codes.allowed_answers_table(bad)
        for reason, row in codes.ALLOWED_ANSWERS.items():
            self.assertTrue(set(row) <= set(codes.STAGE2_ALLOWED_ANSWERS[reason]), reason)

    def test_stage2_table(self):
        t = codes.STAGE2_ALLOWED_ANSWERS
        self.assertEqual(set(t), codes.LEADER_SITUATIONS)
        for row in t.values():
            self.assertTrue(set(row) <= set(codes.LeaderAnswer.values()))
            self.assertIn("escalate", row)
        self.assertIn("rerun", t["plan-gate"])                                   # D3
        self.assertEqual(t["rule-unfillable"], ("escalate",))                    # D9
        leader_base_red = [a for a in t["base-red"] if a not in codes.LEADER_REMOVED_ANSWERS["base-red"]]
        self.assertEqual(leader_base_red, ["escalate"])                          # D9: leader never called
        self.assertEqual(set(codes.LEADER_ANSWER_SCHEMAS), codes.LEADER_SITUATIONS - {"rule-unfillable", "base-red"})
        self.assertTrue(codes.LEADER_CALL_COUNTED <= set(codes.STAGE3_LEADER_ANSWER_SCHEMAS))
        self.assertEqual(len(codes.LEADER_CALL_COUNTED & set(codes.LEADER_ANSWER_SCHEMAS)), 5, "the stage-2 five")
        self.assertFalse(codes.LEADER_CALL_COUNTED & {"plan-gate", "done-gate", "new-collaborator-comment"})  # D14
        self.assertTrue(codes.LEADER_FAILED_CODES <= set(codes.FailureCode.values()))
        for name in codes.LEADER_ANSWER_SCHEMAS.values():
            self.assertIn(name, S.schema_names())

    def test_no_answer_turns_a_failure_into_a_pass(self):
        """§6.3: no situation reached from a failed review / red run offers approve; approve only at done-gate."""
        for reason, row in codes.STAGE2_ALLOWED_ANSWERS.items():
            if reason != "done-gate":
                self.assertNotIn("approve", row, reason)

    def test_narrowing(self):
        self.assertEqual(set(codes.NARROWING), set(codes.NarrowReason.values()))
        self.assertEqual(set(codes.NARROWING_SITUATIONS), set(codes.NarrowReason.values()))
        for reason, removed in codes.NARROWING.items():
            for sit in codes.NARROWING_SITUATIONS[reason]:
                with self.subTest(reason=reason, situation=sit):
                    self.assertTrue(set(removed) <= set(codes.STAGE3_ALLOWED_ANSWERS[sit]))
                    self.assertIn(sit, codes.STAGE3_LEADER_SITUATIONS)
            self.assertEqual(not removed, reason in codes.NARROWING_FIELDS, reason)
        from gxengine import acparse
        plan_reasons = {acparse.PLAN_REASON_TYPE, acparse.PLAN_REASON_SPLIT, acparse.PLAN_REASON_PREREQUISITE,
                        acparse.PLAN_REASON_RISK}
        self.assertTrue(plan_reasons <= set(codes.NarrowReason.values()), "acparse I1 codes are narrow reasons")
        for r in plan_reasons:
            self.assertIn("plan", codes.NARROWING[r])

    def test_d4_conservative_risk_high_leaves_only_escalate(self):
        """Coordinator memo (pending A2): risk = high at plan-gate → needs_human, the leader cannot plan.

        The narrowing leaves only escalate even in the widest case (attended, decision marker,
        no rerun used), so D9 applies: no leader call."""
        row = codes.STAGE2_ALLOWED_ANSWERS["plan-gate"]
        left = [a for a in row if a not in codes.NARROWING[codes.NarrowReason.RISK_HIGH.value]]
        self.assertEqual(left, ["escalate"])

    def test_tokens(self):
        for name in LEADER_ANSWER_NAMES + S3_LEADER_ANSWER_NAMES:
            toks = S.schema_tokens(S.load_schema(name))
            with self.subTest(name=name):
                self.assertTrue(toks <= set(codes.LEADER_SCHEMA_TOKENS), toks)
                self.assertTrue({"{answers}", "{rerun_steps}", "{human_answers}", "{human_rerun_steps}"} <= toks)
        self.assertEqual(S.schema_tokens(S.load_schema("leader-answer-plan-gate")) - S.schema_tokens(S.load_schema("leader-answer")),
                         {"{requirement_rows}", "{templates}"})
        self.assertEqual(S.schema_tokens(S.load_schema("leader-answer-done-gate")) - S.schema_tokens(S.load_schema("leader-answer")),
                         {"{ac_ids}", "{discovery_ids}"})
        self.assertEqual(S.schema_tokens(S.load_schema("leader-answer-new-comment")) - S.schema_tokens(S.load_schema("leader-answer")),
                         {"{comment_ids}"})

    def test_stage2_defaults(self):
        self.assertGreaterEqual(defaults.ENGINE_STAGE, 2, "flipped to 2 by the stage-2 merge (D21, Q6)")
        self.assertEqual(defaults.MODEL_EFFORT["leader"], ("opus", "high"))                 # D10, §7.9
        self.assertEqual(defaults.SESSION_MAX_BUDGET_USD["leader"], 6.0)                    # D10 provisional
        self.assertEqual(codes.role_class("leader"), "judge")                               # D10: judge boundary
        self.assertEqual((defaults.PLAN_GATE_RERUN_MAX, defaults.DONE_GATE_RERUN_MAX), (2, 2))  # D3, D7
        self.assertEqual(defaults.leader_format_retries("plan-gate"), 2)                    # D12
        self.assertEqual(defaults.leader_format_retries("done-gate"), 1)
        self.assertEqual(defaults.leader_format_retries("blocked"), 1)
        self.assertEqual(defaults.LEADER_CALLS_MAX, 5)                                      # D14
        self.assertTrue(defaults.PLAN_DECISION_MARKER.startswith(defaults.MARKER_PREFIX))
        self.assertTrue(defaults.CLOSED_AS_DECIDED_MARKER.startswith(defaults.MARKER_PREFIX))
        self.assertEqual(codes.STAGE2_OPS, codes.STAGE1_OPS)


class Stage3Tables(unittest.TestCase):
    """The stage-3 tables in codes.py / defaults.py (scope §2.0, E2, E17, E19, E22, E26, E35, E36)."""

    def test_engine_stage_and_earlier_tables_unchanged(self):
        """E36: every stage-3 value is picked by a `stage` argument; stages 1 and 2 keep theirs."""
        self.assertGreaterEqual(defaults.ENGINE_STAGE, 3, "flipped to 3 by the stage-3 integration (Q4, E36)")
        self.assertEqual(codes.STAGE1_OPS, {"create-pr"})
        self.assertEqual([sorted(codes.stage_ops(n)) for n in (1, 2, 3)],
                         [["create-pr"], ["create-pr"], ["create-followups", "create-pr"]])
        self.assertIs(codes.allowed_answers_table(3), codes.STAGE3_ALLOWED_ANSWERS)
        self.assertEqual(codes.leader_situations(2), codes.LEADER_SITUATIONS)
        self.assertEqual(codes.leader_situations(3) - codes.LEADER_SITUATIONS, {"step-add-limit", "step-removal-request", "pr-review"})
        self.assertIs(codes.leader_answer_schemas(2), codes.LEADER_ANSWER_SCHEMAS)
        self.assertIs(codes.leader_answer_schemas(3), codes.STAGE3_LEADER_ANSWER_SCHEMAS)
        self.assertEqual(codes.result_schemas(2), {"work": "result-work", "review": "result-review"})
        self.assertIs(codes.result_schemas(3), codes.STAGE3_RESULT_SCHEMAS)
        self.assertEqual(set(codes.STAGE3_RESULT_SCHEMAS), set(codes.ResultKind.values()))
        with self.assertRaises(ValueError):
            codes.leader_answer_schemas(1)
        for fn in (codes.stage_ops, codes.leader_situations, codes.result_schemas, codes.leader_answer_schemas,
                   defaults.model_effort_table, defaults.session_budget_table):
            for bad in (0, True, "3", None):
                with self.subTest(fn=fn.__name__, bad=bad), self.assertRaises(ValueError):
                    fn(bad)

    def test_stage3_answer_table(self):
        t = codes.STAGE3_ALLOWED_ANSWERS
        for sit, row in codes.STAGE2_ALLOWED_ANSWERS.items():
            self.assertEqual(t[sit], row if sit != "blocked" else ("rerun", "replan", "close-as-decided", "escalate"), sit)
        self.assertEqual([s for s, r in t.items() if "close-as-decided" in r],
                         ["plan-gate", "blocked", "not-reproduced"])                  # K8-3, readiness E4 (a human's)
        self.assertNotIn("close-as-decided", codes.STAGE2_ALLOWED_ANSWERS["blocked"])
        self.assertEqual(set(t) - set(codes.STAGE2_ALLOWED_ANSWERS),
                         {"step-add-limit", "step-removal-request", "pr-review", "irreversible-change", "not-reproduced"})
        self.assertNotIn("replan", t["done-gate"])                                            # E34
        self.assertEqual([s for s, r in t.items() if "skip" in r], ["step-removal-request"])   # E13
        self.assertEqual([s for s, r in t.items() if "approve" in r], ["done-gate"], "§6.3")
        self.assertEqual(t["irreversible-change"], ("continue", "rerun"))                      # E23
        self.assertNotIn("irreversible-change", codes.STAGE3_LEADER_SITUATIONS)                # TI6
        self.assertNotIn("irreversible-change", codes.STAGE3_LEADER_ANSWER_SCHEMAS)
        self.assertEqual(set(codes.STAGE3_LEADER_ANSWER_SCHEMAS), codes.STAGE3_LEADER_SITUATIONS - {"rule-unfillable", "base-red"})
        for sit in codes.STAGE3_LEADER_ANSWER_SCHEMAS:
            self.assertIn("escalate", t[sit], sit)
        for name in codes.STAGE3_LEADER_ANSWER_SCHEMAS.values():
            self.assertIn(name, S.schema_names())
        self.assertTrue({"step-add-limit", "step-removal-request"} <= codes.LEADER_CALL_COUNTED)   # TX4
        self.assertNotIn("pr-review", codes.LEADER_CALL_COUNTED)
        for sit, gone in codes.RECOMMENDATION_REMOVED_ANSWERS.items():
            self.assertTrue(set(gone) < set(t[sit]))

    def test_new_situations_are_mechanical_before_stage_3(self):
        """A stage-2 engine never produces them; if it did, they would stop for a human (fail-closed)."""
        from gxengine import statemachine
        for sit in codes.STAGE3_LEADER_SITUATIONS - codes.LEADER_SITUATIONS | {"irreversible-change"}:
            for stage in (1, 2):
                self.assertEqual(statemachine.stop_status(sit, stage=stage), "needs_human", sit)

    def test_no_red_to_pass_path(self):
        """Principle 6: no stage-3 answer of either seat dismisses a review or a red run."""
        self.assertNotIn("dismiss", codes.LeaderAnswer.values())
        for sit in ("blocked", "on-fail-exceeded", "output-format-twice", "session-limit", "base-red", "rule-unfillable"):
            self.assertFalse({"continue", "skip", "approve", "plan"} & set(codes.STAGE3_ALLOWED_ANSWERS[sit]), sit)

    def test_narrowing_stage3(self):
        N = codes.NARROWING_SITUATIONS
        self.assertIn("pr-review", N["no-rerun-target"])
        self.assertNotIn("irreversible-change", N["no-rerun-target"])
        self.assertEqual(set(N["plan-not-done"]), {s for s, r in codes.STAGE2_ALLOWED_ANSWERS.items() if "replan" in r})
        self.assertEqual(codes.NARROWING["no-template-for-type"], ("plan",))
        self.assertEqual(codes.NARROWING["template-unusable"], ("plan",))
        self.assertEqual(codes.NARROWING["no-skippable-step"], ("skip",))
        for sit in N["defer-used"]:
            self.assertEqual(codes.STAGE3_LEADER_ANSWER_SCHEMAS[sit], "leader-answer-s3")

    def test_type_templates(self):
        """E1 / E2: every (type, safety_net) cell."""
        want = {("feature", "none"): ("feature",), ("bug", "none"): ("bug",), ("refactor", "none"): ("refactor",),
                ("refactor", "with-refactor"): ("refactor-net",), ("refactor", "only"): ("safety-net",)}
        for ty in codes.AnalysisType.values():
            for net in codes.SafetyNet.values():
                self.assertEqual(codes.templates_for(ty, net), want.get((ty, net), ()), (ty, net))
        self.assertEqual(set(codes.STAGE3_TEMPLATES), {x for row in codes.TYPE_TEMPLATES.values() for x in row})

    def test_path_tokens(self):
        self.assertEqual(codes.path_token(codes.PathRuleKind.TEST_CODE), "{path:test-code}")
        with self.assertRaises(ValueError):
            codes.path_token("verification")

    def test_plugin_commands(self):
        new = set(codes.PluginCommand.values()) - set(codes.STAGE2_PLUGIN_COMMANDS)
        self.assertEqual(new, codes.EVIDENCE_COMMANDS | codes.GIT_FACT_COMMANDS)
        self.assertFalse(codes.EVIDENCE_COMMANDS & codes.GIT_FACT_COMMANDS)

    def test_irreversible(self):
        self.assertEqual(set(codes.IRREVERSIBLE_CODE_CATEGORY), set(codes.IrreversibleCode.values()))
        self.assertEqual(len(codes.IrreversibleCode.values()), 11)
        self.assertEqual(set(codes.IRREVERSIBLE_CODE_CATEGORY.values()), set(codes.IrreversibleCategory.values()))
        self.assertEqual(defaults.IRREVERSIBLE_DEFAULT_LEVEL,
                         {"external-side-effect": "human-decision", "hard-to-revert": "notify", "human-executed": "notify"})
        self.assertEqual(set(defaults.IRREVERSIBLE_LEVEL_ORDER), set(codes.IrreversibleLevel.values()))

    def test_stage3_defaults(self):
        self.assertEqual((defaults.CATALOG_ADDS_MAX, defaults.FOLLOWUPS_MAX, defaults.FOLLOWUP_CANDIDATES_MAX, defaults.DEFER_MAX),
                         (3, 5, 30, 1))
        self.assertEqual(defaults.REPRO_RED_RUNS, 2)                          # review-q0 D10
        self.assertIs(defaults.FOLLOWUPS_DRY_RUN_DEFAULT, False)              # A4: the default really creates
        self.assertTrue(defaults.FOLLOWUP_MARKER.startswith(defaults.MARKER_PREFIX))
        self.assertEqual(set(defaults.FOLLOWUP_TYPE_LABELS) - {defaults.DEFERRED_REQUIREMENT_KIND}, set(codes.DiscoveryKind.values()))
        self.assertTrue(set(defaults.ALLOWED_MODELS) < set(defaults.MODEL_LADDER))
        self.assertTrue(set(defaults.ALLOWED_EFFORTS) < set(defaults.EFFORT_LADDER))

    def test_stage3_role_defaults(self):
        """E17 — and stages 1–2 still refuse the conditional specialists."""
        new = {"product-owner", "security", "dba", "i18n", "performance", "infra"}
        b2, b3 = defaults.session_budget_table(2), defaults.session_budget_table(3)
        self.assertIs(b2, defaults.SESSION_MAX_BUDGET_USD)
        self.assertFalse(new & set(b2))
        self.assertEqual({r: b3[r] for r in new}, {r: 8.0 for r in new})
        m2, m3 = defaults.model_effort_table(2), defaults.model_effort_table(3)
        self.assertIs(m2, defaults.MODEL_EFFORT)
        for k, v in m2.items():
            self.assertEqual(m3[k], v, k)
        for k, (model, effort) in m3.items():
            self.assertIn(model, defaults.ALLOWED_MODELS, k)
            self.assertIn(effort, defaults.ALLOWED_EFFORTS, k)
            self.assertIn(k.split("/")[0], b3, f"{k}: a role with a model has a session budget")
        for key in ("tech-lead/diagnose", "developer/reproduce", "security/review", "dba/data-design", "product-owner"):
            self.assertIn(key, m3)

    def test_stubs(self):
        """catalog / ladder are shells until Q3: every public function exists and is not implemented."""
        import inspect
        from gxengine import catalog, ladder
        want = {catalog: {"load", "requestable_ids", "usable_ids", "developer_step", "first_review_index", "position", "expand",
                          "insert", "evaluate_requests", "skippable_steps"},
                ladder: {"effort_ladder", "model_ladder", "raisable", "base_choice", "raised", "count_return", "may_resume"}}
        for mod, names in want.items():
            have = {n for n, f in vars(mod).items() if inspect.isfunction(f) and f.__module__ == mod.__name__ and not n.startswith("_")}
            self.assertTrue(names <= have, (mod.__name__, names - have))
            for n in names:
                self.assertTrue(getattr(mod, n).__doc__, f"{mod.__name__}.{n} has its contract in the docstring")


class Stage4Tables(unittest.TestCase):
    """The stage-4 contract (scope §2.0, §2.13, review-q0 D1–D7, A13, VB9). Nothing of it changes an earlier stage."""

    def test_sprint_state_enums(self):
        p = S.load_schema("sprint-state")["properties"]
        self.assertEqual(p["state"]["enum"], codes.SprintState.values())
        self.assertEqual(p["halt"]["enum"], codes.SprintHalt.values() + [None])
        self.assertEqual(p["stack_reason"]["enum"], codes.StackReason.values() + [None])
        m = p["members"]["items"]["properties"]
        self.assertEqual(m["outcome"]["enum"], codes.MemberOutcome.values() + [None])
        self.assertEqual(m["block"]["enum"], codes.MemberBlock.values() + [None])
        self.assertEqual(m["kind"]["enum"], codes.MemberKind.values() + [None])
        self.assertEqual(set(m["stop_reason"]["enum"]), set(codes.StopReason.values()) | {None})
        self.assertEqual(m["stop_detail"]["enum"], codes.InfraReason.values() + [None])
        self.assertEqual(p["plan_hash"]["pattern"], "^[0-9a-f]{%d}$" % defaults.SPRINT_PLAN_HASH_LEN)

    def test_sprint_log_enums(self):
        p = S.load_schema("sprint-log-line")["properties"]
        self.assertEqual(p["event"]["enum"], codes.SprintEvent.values())
        for key, e in (("outcome", codes.MemberOutcome), ("block", codes.MemberBlock), ("halt", codes.SprintHalt),
                       ("state", codes.SprintState)):
            self.assertEqual(p[key]["enum"], e.values(), key)

    def test_init_and_mutation_enums(self):
        a = S.load_schema("init-decisions")["properties"]["answers"]["items"]["properties"]
        self.assertEqual(a["question"]["enum"], codes.InitQuestion.values())
        self.assertEqual(len(codes.InitQuestion.values()), 11, "§2.9: exactly eleven questions (eight + three by A15, 2026-11-26)")
        rec = S.load_schema("mutation-record")["properties"]
        row = rec["rows"]["items"]["properties"]
        self.assertEqual(row["status"]["enum"], codes.MutationStatus.values())
        for node in (rec["problem"], row["detail"]):
            self.assertEqual(node["enum"], codes.MutationRefusal.values() + [None])
        m = S.load_schema("mutations")["properties"]["mutations"]
        self.assertEqual(m["maxItems"], defaults.MUTATIONS_MAX)
        self.assertEqual(rec["rows"]["maxItems"], defaults.MUTATIONS_MAX)
        li = S.load_schema("leader-input")["properties"]["done_gate"]["anyOf"][1]["properties"]["mutations"]["anyOf"][1]
        self.assertEqual(li["properties"]["problem"]["enum"], codes.MutationRefusal.values() + [None])
        lrow = li["properties"]["rows"]["items"]["properties"]
        self.assertEqual(lrow["status"]["enum"], codes.MutationStatus.values())
        self.assertEqual(set(lrow) | {"run", "again"}, set(row),
                         "the leader gets every field of a row but the runs' log names")
        self.assertEqual(li["required"], ["problem", "control_flaky", "rows"], "VW2 E1: the leader sees a flaky control")
        ctl = rec["control"]["anyOf"][1]
        self.assertEqual((ctl["required"], set(ctl["properties"])),
                         (["exit_code", "timed_out", "log_file"], {"exit_code", "timed_out", "log_file", "again", "flaky"}),
                         "VW2 E1: the second control run is recorded; a record of before it still reads")

    def test_mutations_are_data_never_a_command(self):
        ex = load("contracts", "mutations.example.json")
        for extra in ({"cmd": "rm -rf /"}, {"run": "test"}, {"status": "killed"}):
            bad = copy.deepcopy(ex)
            bad["mutations"][0].update(extra)
            self.assertFalse(S.is_valid(bad, "mutations"), extra)
        for path in ("/etc/passwd", "../x", "a/../b", "a//b", ""):
            bad = copy.deepcopy(ex)
            bad["mutations"][0]["path"] = path
            self.assertFalse(S.is_valid(bad, "mutations"), path)
        bad = copy.deepcopy(ex)
        bad["mutations"] = bad["mutations"] * (defaults.MUTATIONS_MAX + 1)
        self.assertFalse(S.is_valid(bad, "mutations"))

    def test_stop_detail(self):
        stop = S.load_schema("state")["properties"]["stop"]["anyOf"][1]["properties"]
        self.assertEqual(stop["detail"]["enum"], codes.InfraReason.values() + [None])
        self.assertEqual(codes.STOP_DETAILS, set(codes.InfraReason.values()))
        self.assertIn(codes.SPRINT_RERUN_DETAIL, codes.STOP_DETAILS)

    def test_state_core_unchanged_by_stage4(self):
        st = S.load_schema("state")
        for key in ("base_branch", "draft", "sprint", "allowed_test_changes"):
            self.assertIn(key, st["properties"])
            self.assertNotIn(key, st["required"])
        self.assertEqual(st["required"], ["format", "issue", "revision", "steps", "last_head"])

    def test_tables(self):
        self.assertEqual(set(codes.BLOCK_BY_DEP_OUTCOME) | {"done", "closed"}, set(codes.MemberOutcome.values()))
        self.assertTrue(set(codes.BLOCK_BY_DEP_OUTCOME.values()) <= set(codes.MemberBlock.values()))
        self.assertEqual(set(codes.MEMBER_KIND_RANK), set(codes.MemberKind.values()))
        self.assertEqual(codes.BOUNDARY_STOPS, {"canary-failed", "self-check-failed"})     # H11 (init-mismatch: FC decision D)
        self.assertEqual(codes.DRAFT_STACK_REASONS, {"squash-sync", "human-override"})                      # U1
        self.assertEqual((defaults.SPRINT_MARKER_FAILS_MAX, defaults.SPRINT_MARKER_FAILS_MAX_WINDOW), (3, 18))
        self.assertEqual(defaults.SPRINT_REPO_BUSY_MAX_S, defaults.INFRA_WAIT_MAX_S, "H5: no new number")
        for m in (defaults.SPRINT_PLAN_MARKER, defaults.SPRINT_RUN_MARKER, defaults.SPRINT_STACK_MARKER):
            self.assertTrue(m.startswith(defaults.MARKER_PREFIX))
        self.assertEqual(defaults.LABEL_PREFIX + defaults.NEEDS_HUMAN_LABEL_NAME, "guild:needs-human")          # H9

    def test_stop_cause(self):
        """A13: engine / Issue / a human label — and the default is never engine or Issue."""
        for reason in codes.StopReason.values():
            self.assertIn(codes.stop_cause(reason), codes.StopCause.values())
        self.assertEqual(codes.stop_cause(codes.StopReason.ENGINE_ERROR), "engine")
        self.assertEqual(codes.stop_cause("irreversible-change"), "issue")
        for reason in ("done-gate", "blocked", "on-fail-exceeded", "base-red", "plan-gate", "soft-budget"):
            self.assertEqual(codes.stop_cause(reason), "label", reason)
        with self.assertRaises(ValueError):
            codes.stop_cause("no-such-stop")

    def test_earlier_stages_unchanged(self):
        """H23: the stage-4 values touch no stage function of stages 1–3 — and 4 reads stage 3's tables."""
        self.assertIs(codes.allowed_answers_table(4), codes.STAGE3_ALLOWED_ANSWERS)
        self.assertIs(codes.leader_answer_schemas(4), codes.STAGE3_LEADER_ANSWER_SCHEMAS)
        self.assertIs(codes.result_schemas(4), codes.STAGE3_RESULT_SCHEMAS)
        self.assertEqual(codes.stage_ops(4), codes.STAGE3_OPS)
        self.assertEqual(len(codes.StopReason.values()), 31,
                         "no new stop reason but readiness E4's not-reproduced and readiness T1's three; "
                         "init-mismatch removed (FC decision D)")
        self.assertNotIn("init-mismatch", codes.StopReason.values())
        t1 = ("unsupported-epic", "open-closing-pr", "done-unconfirmed")
        for reason in t1:              # T1: start refusals of stage >= 4 — never a leader situation, never answered
            self.assertNotIn(reason, codes.STAGE3_LEADER_SITUATIONS)
            self.assertNotIn(reason, codes.STAGE3_ALLOWED_ANSWERS)
            self.assertEqual(codes.stop_cause(reason), "issue", reason)

    def test_leader_input_stage4_sections(self):
        s4 = load("contracts", "leader-input.stage4-done-gate.example.json")
        for key in ("mutations", "commits"):
            o = copy.deepcopy(s4)
            del o["done_gate"][key]
            self.assertFalse(S.is_valid(o, "leader-input"), key)
            o["stage"] = 3
        o = copy.deepcopy(s4)
        o["done_gate"]["mutations"] = None
        self.assertTrue(S.is_valid(o, "leader-input"), "nothing declared")

    def test_repo_config_refuses_the_llm_settings(self):
        """TX4 / H13: one file, one format — the M1 keys are harness.json's."""
        for key, val in (("sprint", {"capacity": 3}), ("language", "ko"), ("gates", {"enabled": False}), ("visual", {})):
            c = load("contracts", "repo-config.example.json")
            c[key] = val
            self.assertFalse(S.is_valid(c, "repo-config"), key)

    def test_stubs(self):
        """The stage-4 modules: every public name of the contract exists and has its docstring."""
        import inspect
        from gxengine import basecheck, initconfig, issuerefs, mutation, sprint, sprintdag, sprinttracker, testchange
        want = {
            sprintdag: {"parse_table", "stored_plan_hash", "stack_reason_token", "plan_hash", "order", "member_state",
                        "base_for", "effective_stack_reason", "parse_window", "in_window"},
            issuerefs: {"referenced_numbers"},
            sprinttracker: {"read", "write_marker", "merge_settings", "issue_facts", "dep_facts", "remote_state"},
            testchange: {"args_problem", "apply", "allowed"},
            mutation: {"declaration_path", "prove", "load"},
            sprint: {"engine_sha256", "run", "status", "report", "check", "stop"},
            basecheck: {"check", "run_cli"},
            initconfig: {"run"},
        }
        for mod, names in want.items():
            have = {n for n, f in vars(mod).items() if inspect.isfunction(f) and f.__module__ == mod.__name__ and not n.startswith("_")}
            self.assertTrue(names <= have, (mod.__name__, names - have))
            for n in names:
                self.assertTrue(getattr(mod, n).__doc__, f"{mod.__name__}.{n}")
        green = S.load_schema("base-green")["properties"]["problem"]["enum"]
        self.assertEqual(tuple(green[:-1]), basecheck.PROBLEMS)

    def test_tests_of_shells(self):
        """The data classes of the shells work and refuse what the contract refuses."""
        from gxengine import basecheck, sprintdag
        self.assertEqual(sprintdag.Member(101, 100, "goal"), sprintdag.Member(101, 100, "goal"))
        for bad in ((0,), (True,), ("1",), (1, 0), (1, None, "epic")):
            with self.assertRaises(sprintdag.SprintTableError):
                sprintdag.Member(*bad)
        with self.assertRaises(ValueError):
            sprintdag.DepVerdict("blocked")
        with self.assertRaises(ValueError):
            sprintdag.DepVerdict("default", block="upstream")
        with self.assertRaises(ValueError):
            sprintdag.DepVerdict("stack")
        with self.assertRaises(ValueError):
            basecheck.BaseCheckResult(True, red=["test"])
        with self.assertRaises(ValueError):
            basecheck.BaseCheckResult(False, problem="other")


class Stage3Grammar(unittest.TestCase):
    """The stage-3 grammar parts frozen here; the earlier stages keep refusing them."""

    def proc(self, **step):
        p = load("contracts", "procedure.example.json")
        p["steps"][3].update(step)
        return p

    def test_path_token_is_a_whole_item(self):
        for key in ("inputs", "outputs"):
            for ok in ("{path:test-code}", "{path:safety-net}"):
                self.assertTrue(S.is_valid(self.proc(**{key: [ok]}), "procedure"), (key, ok))
            for bad in ("{path:verification}", "x/{path:test-code}", "{path:test-code}/x", "{path:}"):
                self.assertFalse(S.is_valid(self.proc(**{key: [bad]}), "procedure"), (key, bad))

    def test_earlier_stages_refuse_the_stage3_grammar(self):
        from gxengine import procedure
        for step in ({"outputs": ["{path:test-code}"]}, {"inputs": ["in:repro-evidence.md"]},
                     {"inputs": ["in:blocking-discoveries.md"]}, {"inputs": ["in:pr-review.md"]}):
            for stage in (1, 2):
                with self.subTest(step=step, stage=stage):
                    self.assertTrue(procedure.check(self.proc(**step), None, stage=stage))
        tail = {"id": "followups", "op": "create-followups"}
        p = self.proc()
        p["steps"].append(tail)
        for stage in (1, 2):
            self.assertTrue([e for e in procedure.check(p, None, stage=stage) if "create-followups" in e])
        p["steps"][-1] = {"id": "children", "op": "create-children"}
        self.assertTrue([e for e in procedure.check(p, None, stage=3) if "create-children" in e], "epic ops stay refused")

    def test_repo_config_stage3_keys(self):
        base = load("contracts", "repo-config.example.json")

        def ok(**kw):
            c = copy.deepcopy(base)
            c.update(kw)
            return S.is_valid(c, "repo-config")
        self.assertTrue(ok(followups_dry_run=True))
        self.assertFalse(ok(followups_dry_run="yes"))
        self.assertTrue(ok(irreversible_levels={"hard-to-revert": "proceed"}))
        self.assertFalse(ok(irreversible_levels={"other": "proceed"}))
        self.assertFalse(ok(irreversible_levels={"hard-to-revert": "ignore"}))
        self.assertTrue(ok(path_rules=[{"kind": "test-code", "globs": ["test/**"]}]))
        self.assertFalse(ok(path_rules=[{"kind": "test-code", "globs": []}]), "an empty rule would make a template own nothing")
        self.assertFalse(ok(path_rules=[{"kind": "verification", "globs": [], "category": "image"}]))
        self.assertFalse(ok(allowed_models=["gpt"]))
        self.assertFalse(ok(allowed_efforts=["ultra"]))

    def test_leader_input_sections_by_stage(self):
        """Stage 3 needs its sections; a stage-2 object needs none of them."""
        s3 = load("contracts", "leader-input.stage3-done-gate.example.json")
        for key in ("defer", "removal", "add_limit", "pr_review"):
            o = copy.deepcopy(s3)
            del o[key]
            self.assertFalse(S.is_valid(o, "leader-input"), key)
        for key in ("included_fixes", "followup_candidates", "deferred_rows"):
            o = copy.deepcopy(s3)
            del o["done_gate"][key]
            self.assertFalse(S.is_valid(o, "leader-input"), key)
        o = copy.deepcopy(s3)
        del o["done_gate"]["requests"][0]["outcome"]
        self.assertFalse(S.is_valid(o, "leader-input"))
        o = copy.deepcopy(s3)
        del o["allowed"]["narrowed"][0]["field"]
        self.assertFalse(S.is_valid(o, "leader-input"), "a reason that removes nothing names its field")
        pg = load("contracts", "leader-input.stage3-plan-gate.example.json")
        self.assertEqual(pg["plan_gate"]["templates"], [])
        pg["stage"] = 2
        self.assertFalse(S.is_valid(pg, "leader-input"), "stage 2 always has a template")

    def test_facts_evidence(self):
        f = load("contracts", "facts.stage3-repro-red.example.json")
        for key in ("scope", "overlay", "globs", "end_tree"):
            o = copy.deepcopy(f)
            del o["run"]["evidence"][key]
            self.assertFalse(S.is_valid(o, "facts"), key)

    def test_state_core_unchanged(self):
        """Scope V1: no change of a fixed core field (README "Changing a contract" 2)."""
        st = S.load_schema("state")
        self.assertEqual(st["required"], ["format", "issue", "revision", "steps", "last_head"])
        self.assertEqual(st["$defs"]["step"]["required"], ["id", "status", "latest_attempt"])
        self.assertEqual(st["properties"]["format"], {"const": 1})
        core = {k: st["properties"][k] for k in ("format", "issue", "revision", "steps")}
        self.assertEqual(core["steps"], {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/step"}})


class SchemaShapes(unittest.TestCase):
    def test_review_result_extends_work_result_identically(self):
        work, review = S.load_schema("result-work"), S.load_schema("result-review")
        for key, val in work["properties"].items():
            self.assertEqual(review["properties"][key], val, key)
        self.assertEqual(set(review["required"]) - set(work["required"]), {"verdict", "reviewed", "checks", "findings"})

    def test_stage3_results_extend_the_stage2_ones(self):
        work, review = S.load_schema("result-work-s3"), S.load_schema("result-review-s3")
        for key, val in work["properties"].items():
            if key != "golden_reasons":       # E33: work roles only
                self.assertEqual(review["properties"][key], val, key)
        self.assertEqual(set(work["properties"]) - set(review["properties"]), {"golden_reasons"})
        for s3, s2 in ((work, "result-work"), (review, "result-review")):
            old = S.load_schema(s2)
            self.assertEqual(set(s3["required"]), set(s3["properties"]))
            self.assertEqual(S.schema_tokens(s3), set(codes.RESULT_SCHEMA_TOKENS))
            for key, val in old["properties"].items():
                if key != "requests":
                    self.assertEqual(s3["properties"][key], val, key)

    def test_stage3_result_refuses_a_step_outside_the_catalog(self):
        ex = load("contracts", "result-work-s3.example.json")
        for step in ("fix-discovery", "pnpm test", "lint", ""):
            bad = copy.deepcopy(ex["answer"])
            bad["requests"][0]["step"] = step
            self.assertFalse(S.is_valid(bad, filled("result-work-s3", ex["fill"])), step)      # TC6

    def test_result_schemas_stay_in_the_structured_output_subset(self):
        allowed = S.ANNOTATIONS | {"type", "properties", "required", "additionalProperties", "items", "enum"}

        def walk(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("properties",):
                        for pk, pv in v.items():
                            walk(pv, f"{path}/{pk}")
                        continue
                    self.assertIn(k, allowed, f"{path}: {k}")
                    walk(v, f"{path}/{k}")
        for name in ("result-work", "result-review", *TEMPLATE_NAMES):
            walk(S.load_schema(name), name)

    def test_leader_answers_share_the_common_envelope(self):
        common = S.load_schema("leader-answer")
        for name in LEADER_ANSWER_NAMES[1:] + S3_LEADER_ANSWER_NAMES:
            sch = S.load_schema(name)
            with self.subTest(name=name):
                for key, val in common["properties"].items():
                    self.assertEqual(sch["properties"][key], val, key)
                self.assertEqual(sch["required"][:len(common["required"])], common["required"])
                self.assertEqual(set(sch["required"]), set(sch["properties"]), "every field required (§2.0)")
                self.assertFalse(sch["additionalProperties"])

    def test_filled_leader_schema_refuses_answers_outside_the_enum(self):
        ex = load("contracts", "leader-answer-plan-gate.example.json")
        fill = dict(ex["fill"], **{"{answers}": ["rerun", "escalate"]})     # plan narrowed away
        sch = filled("leader-answer-plan-gate", fill)
        self.assertFalse(S.is_valid(ex["answer"], sch))
        bad = copy.deepcopy(ex["answer"])
        bad["requirements"][0]["row"] = "R9"
        self.assertFalse(S.is_valid(bad, filled("leader-answer-plan-gate", ex["fill"])))
        bad = copy.deepcopy(ex["answer"])
        bad["reason"] = "looks-fine"
        self.assertFalse(S.is_valid(bad, filled("leader-answer-plan-gate", ex["fill"])))

    def test_empty_id_list_drops_the_field(self):
        ex = load("contracts", "leader-answer-done-gate.example.json")
        sch = filled("leader-answer-done-gate", dict(ex["fill"], **{"{discovery_ids}": []}))
        self.assertNotIn("discoveries", sch["properties"])
        self.assertNotIn("discoveries", sch["required"])
        ans = {k: v for k, v in ex["answer"].items() if k != "discoveries"}
        S.validate(ans, sch)
        sch = filled("leader-answer", dict(load("contracts", "leader-answer.example.json")["fill"], **{"{rerun_steps}": []}))
        self.assertEqual(sch["properties"]["step"]["enum"], [None], "no rerun target → step can only be null")

    def test_stage3_empty_lists_drop_their_fields(self):
        """No usable template → no `plan`; no rerun / no row → no `session` / `defer`; no F id → no included_fixes."""
        ex = load("contracts", "leader-answer-plan-gate-s3.example.json")
        sch = filled("leader-answer-plan-gate-s3", dict(ex["fill"], **{"{templates}": [], "{answers}": ["rerun", "escalate"]}))
        self.assertNotIn("plan", sch["properties"])
        self.assertNotIn("plan", sch["required"])
        sch = filled("leader-answer-plan-gate-s3", dict(ex["fill"], **{"{catalog_steps}": []}))
        self.assertNotIn("adjust", sch["properties"]["plan"]["properties"])
        self.assertNotIn("adjust", sch["properties"]["plan"]["required"])
        ex = load("contracts", "leader-answer-s3.example.json")
        limit = dict(ex["fill"], **{"{answers}": ["continue", "escalate"], "{rerun_steps}": [], "{human_answers}": ["continue", "escalate"],
                                    "{human_rerun_steps}": [], "{requirement_rows}": [], "{models}": [], "{efforts}": [],
                                    "{close_reasons}": []})
        sch = filled("leader-answer-s3", limit)           # step-add-limit
        self.assertEqual(list(sch["properties"]), ["answer", "reason", "step", "note", "recommendation"])
        self.assertNotIn("close", filled("leader-answer-s3", ex["fill"])["properties"])          # not offered (K8-3)
        sch = filled("leader-answer-s3", dict(ex["fill"], **{"{close_reasons}": codes.CloseReason.values(),
                                                             "{answers}": ["rerun", "close-as-decided", "escalate"]}))
        S.validate(dict(ex["answer"], answer="close-as-decided", reason="already-decided", step=None, session=None,
                        close={"reason": "completed"}), sch)
        self.assertFalse(S.is_valid(ex["answer"], sch), "close is required where it is offered (null otherwise)")
        ex = load("contracts", "leader-answer-done-gate-s3.example.json")
        sch = filled("leader-answer-done-gate-s3", dict(ex["fill"], **{"{fix_ids}": [], "{candidate_issues}": [], "{dispositions}": ["ignore"]}))
        self.assertNotIn("included_fixes", sch["properties"])
        self.assertEqual(sch["properties"]["discoveries"]["items"]["properties"]["duplicate_of"]["enum"], [None])
        ex = load("contracts", "leader-answer-step-removal.example.json")
        sch = filled("leader-answer-step-removal", dict(ex["fill"], **{"{skippable_steps}": [], "{answers}": ["continue", "escalate"]}))
        self.assertEqual(sch["properties"]["skip_step"]["enum"], [None])
        self.assertFalse(S.is_valid(ex["answer"], sch))

    def test_template_and_procedure_share_step_definitions(self):
        self.assertEqual(S.load_schema("template")["$defs"], S.load_schema("procedure")["$defs"])

    def test_state_core_fields_match_store(self):
        from gxengine import store
        st = S.load_schema("state")
        self.assertEqual(set(st["required"]), set(store.STATE_CORE_FIELDS))
        self.assertEqual(set(st["$defs"]["step"]["required"]), set(store.STATE_STEP_CORE_FIELDS))


class RenderFixtures(unittest.TestCase):
    """The example input → output of the render functions (§6.2, §7.6, F1–F3). Frozen keys."""

    NAMES = ("judge-design.json", "work-developer.json", "run-test.json", "work-developer-exceptions.json")
    ROLE_NAMES = ("judge-design.json", "work-developer.json", "work-developer-exceptions.json")

    def fx(self, name):
        return load("render", name)

    def test_fixture_shape(self):
        for name in self.NAMES:
            fx = self.fx(name)
            with self.subTest(name=name):
                self.assertEqual(set(fx), {"format", "description", "input", "base_env", "bins", "files", "expected"})
                kind = fx["input"]["kind"]
                want = {"settings", "argv", "env"} if kind == "role" else {"srt", "argv", "env"}
                self.assertEqual(set(fx["expected"]), want)
                self.assertTrue(set(fx["input"]["paths"]) >= set(render.PLACEHOLDERS) - {"srt_tmpdir", "in_dir"})

    def test_role_argv_contract(self):
        for name in self.ROLE_NAMES:
            fx = self.fx(name)
            argv, inp = fx["expected"]["argv"], fx["input"]
            with self.subTest(name=name):
                self.assertEqual(argv[:3], [fx["bins"]["claude"], "-p", inp["instruction"]])
                self.assertEqual(tuple(argv[3:3 + len(render.CLAUDE_FIXED_FLAGS)]), render.CLAUDE_FIXED_FLAGS)
                for flag in render.FORBIDDEN_FLAGS:
                    self.assertNotIn(flag, argv)

                def val(flag):
                    return argv[argv.index(flag) + 1]
                self.assertEqual(val("--settings"), fx["files"]["settings"])
                self.assertEqual(val("--tools"), ",".join(defaults.TOOLS[inp["role_class"]]))
                self.assertEqual(val("--permission-mode"), "default")
                body = dict(S.load_schema(inp["json_schema"]))
                for k in render.CLI_SCHEMA_DROP:    # P4: the real CLI refuses the 2020-12 meta-schema
                    body.pop(k, None)
                schema_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
                self.assertEqual(val("--json-schema"), schema_text,
                                 "the schema file passed verbatim (compact) without $schema / $id")
                self.assertEqual(val("--append-system-prompt"), inp["system_prompt"])
                self.assertEqual(val("--model"), inp["model"])

    def test_role_settings_contract(self):
        for name in self.ROLE_NAMES:
            fx = self.fx(name)
            st, inp = fx["expected"]["settings"], fx["input"]
            with self.subTest(name=name):
                self.assertEqual(set(st), {"permissions", "sandbox", "hooks"})
                for k, v in defaults.SANDBOX_FIXED.items():
                    self.assertEqual(st["sandbox"][k], v, k)
                self.assertEqual(set(st["sandbox"]["filesystem"]), {"denyRead", "allowRead", "allowWrite", "denyWrite"})
                self.assertEqual(st["sandbox"]["filesystem"]["allowRead"], [inp["paths"]["in_dir"]])
                allow, deny = st["permissions"]["allow"], st["permissions"]["deny"]
                self.assertFalse([r for r in allow if r.startswith("Write(")], "write allows are Edit(...) (F1)")
                self.assertIn(f"Read(/{inp['paths']['in_dir']}/**)", allow)
                for rule in defaults.AUX_BASH_DENY + ("WebFetch", "WebSearch"):
                    self.assertIn(rule, deny)
                wt = inp["paths"]["worktree"]
                self.assertIn(f"Edit(/{wt}/.claude/**)", deny)
                self.assertIn(f"Edit(/{wt}/docs/specs/42/procedure.yaml)", deny)
                self.assertIn(f"Read(/{inp['paths']['home']}/.config/gh/**)", deny)
                self.assertNotIn(f"Read(/{inp['paths']['home']}/.gitconfig)", deny)
                self.assertFalse([r for r in deny if r.startswith("Read(") and r.endswith("/records/**)")],
                                 "a deny on the whole records folder would beat the in/ allow")
                hook = st["hooks"]["PreToolUse"][0]
                self.assertEqual(hook["matcher"], "Bash")
                self.assertIn(inp["paths"]["plugin_root"] + "/skills/gld/gates/gate_precommit.py", hook["hooks"][0]["command"])
                if inp["role_class"] == "judge":
                    self.assertNotIn("Bash", allow)
                    self.assertEqual(st["sandbox"]["network"]["allowedDomains"], [])
                else:
                    self.assertIn("Bash", allow)
                    self.assertEqual(st["sandbox"]["network"]["allowedDomains"], inp["config"]["registry_hosts"])
                # P5 F2: the approved exceptions in Claude Code's own keys — developer only, exactly true
                exc = inp["config"].get("sandbox_exceptions") or {}
                extra_sb = set(st["sandbox"]) - set(defaults.SANDBOX_FIXED) - {"filesystem", "network"}
                extra_net = set(st["sandbox"]["network"]) - {"allowedDomains"}
                self.assertEqual(extra_sb, {"enableWeakerNetworkIsolation"} if exc.get("weaker_network_isolation") else set())
                self.assertEqual(extra_net, {"allowLocalBinding"} if exc.get("allow_local_binding") else set())
                self.assertIn(st["sandbox"].get("enableWeakerNetworkIsolation"), (None, True))
                self.assertIn(st["sandbox"]["network"].get("allowLocalBinding"), (None, True))
                if exc.get("allow_write"):
                    self.assertEqual(inp["role_class"], "work")
                    ut = inp["paths"]["user_tmp"]
                    self.assertIn(ut, st["sandbox"]["filesystem"]["allowWrite"])
                    self.assertIn(f"{ut}/**/.git", st["sandbox"]["filesystem"]["denyWrite"])
                    self.assertIn(f"Edit(/{ut}/**/.git)", deny)
                    self.assertFalse([r for r in allow if ut in r], "Bash only: no Edit allow for an extra root")

    def test_env_contract(self):
        for name in self.NAMES:
            fx = self.fx(name)
            env = fx["expected"]["env"]
            with self.subTest(name=name):
                import fnmatch
                for k in env:
                    if k in defaults.ENV_SESSION_SET:
                        continue
                    self.assertFalse(any(fnmatch.fnmatchcase(k, p) for p in defaults.ENV_SCRUB_PATTERNS), k)
                if fx["input"]["kind"] == "role":
                    for k, v in defaults.ENV_SESSION_SET.items():
                        self.assertEqual(env[k], v)
                    self.assertEqual(env["BASH_MAX_TIMEOUT_MS"], str(fx["input"]["bash_timeout_ms"]))
                    self.assertIn("CLAUDE_CONFIG_DIR", env)
                else:
                    self.assertNotIn("CLAUDE_CONFIG_DIR", env)
                    self.assertTrue(env["TMPDIR"].startswith(defaults.SRT_TMP_PREFIX))

    def test_srt_contract(self):
        fx = self.fx("run-test.json")
        srt, argv, inp = fx["expected"]["srt"], fx["expected"]["argv"], fx["input"]
        self.assertEqual(set(srt["network"]), {"allowedDomains", "deniedDomains"}, "srt refuses a config without deniedDomains (F0)")
        self.assertEqual(set(srt["filesystem"]), {"denyRead", "allowRead", "allowWrite", "denyWrite"})
        self.assertEqual(argv[:4], [fx["bins"]["srt"], "--settings", fx["files"]["srt"], "-c"])
        self.assertTrue(argv[4].startswith("export TMPDIR="), "the command's TMPDIR is set inside -c (F0)")
        self.assertTrue(argv[4].endswith(inp["command"]))
        role = self.fx("work-developer.json")["expected"]["settings"]["sandbox"]["filesystem"]
        self.assertEqual(srt["filesystem"]["denyRead"], role["denyRead"], "a run gets the developer's boundary (§7.1)")
        self.assertEqual(srt["filesystem"]["denyWrite"], role["denyWrite"])

    def test_snapshot_when_implemented(self):
        """U5 acceptance: render(...) reproduces every fixture. Skipped while render is a stub."""
        for name in self.NAMES:
            fx = self.fx(name)
            with self.subTest(name=name):
                try:
                    inp = render.RenderInput.from_json(fx["input"])
                    got = render.render(inp, fx["base_env"], fx["bins"], fx["files"])
                except NotImplementedError:
                    self.skipTest("render is a stub until U5")
                self.assertEqual(got, fx["expected"])


# --- module boundaries ------------------------------------------------------------

LAYERS = {
    # L0 foundation
    "codes": 0, "defaults": 0, "schema": 0, "fsafe": 0, "streamjson": 0, "globs": 0,
    # L1 files and data
    "paths": 1, "store": 1, "procedure": 1, "repoconfig": 1, "acparse": 1,
    "catalog": 1, "ladder": 1,                                                  # stage 3 (V1)
    "sprintdag": 1, "issuerefs": 1,                                             # stage 4 (V1)
    # L2 boundary and the outside world
    "render": 2, "gitops": 2, "outbound": 2, "github": 2, "canary": 2, "instructions": 2,
    "sprinttracker": 2,                                                         # stage 4 (V1)
    # L3 step mechanics
    "statemachine": 3, "facts": 3, "session": 3, "runner": 3, "results": 3, "rules": 3, "budget": 3, "prbody": 3,
    "leader": 3,
    "testchange": 3, "mutation": 3,                                             # stage 4 (V1)
    "incidents": 3,                                                             # readiness R1
    "history": 3,                                                               # readiness E4
    # L4 orchestration
    "lifecycle": 4, "driver": 4, "cli": 4, "canaryrun": 4,
    "sprint": 4, "basecheck": 4, "initconfig": 4,                               # stage 4 (V1)
    "retention": 4,                                                             # readiness R1
    "channel": 4,                                                               # readiness T1 R4-14
    "initharness": 4,                                                           # readiness T2
}
SAME_LAYER = {
    ("defaults", "codes"), ("globs", "codes"), ("globs", "defaults"),
    ("store", "paths"),
    ("procedure", "catalog"),                                                   # stage 3 (V1)
    ("outbound", "gitops"), ("github", "outbound"), ("canary", "render"),
    ("results", "facts"), ("results", "statemachine"), ("rules", "statemachine"), ("prbody", "facts"),
    ("leader", "session"), ("leader", "facts"), ("leader", "statemachine"),     # stage 2 (V1)
    ("driver", "lifecycle"), ("cli", "driver"), ("cli", "lifecycle"),
    ("driver", "canaryrun"), ("cli", "canaryrun"),
    # stage 4 (V1). `sprint` imports no driver (H1): a member is a child process.
    ("sprinttracker", "github"), ("mutation", "runner"),
    ("sprint", "lifecycle"), ("sprint", "basecheck"),
    ("initconfig", "basecheck"), ("initconfig", "canaryrun"),
    ("cli", "sprint"), ("cli", "initconfig"), ("cli", "basecheck"),
    # readiness R1: records cleanup reads the engines' locks
    ("retention", "lifecycle"), ("cli", "retention"),
    # readiness T1 R4-14: the channel switch reads the engines' locks of the other channel
    ("channel", "lifecycle"), ("cli", "channel"),
    # readiness T2: role files, the 0.98.x migration — the channel values decide; init's settings part is shared
    ("initharness", "channel"), ("initharness", "initconfig"), ("cli", "initharness"),
}


def internal_imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    out, ext = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level >= 1:
                if node.module:
                    out.add(node.module.split(".")[0])
                else:
                    out.update(a.name for a in node.names)
            elif node.module and node.module.split(".")[0] == "gxengine":
                rest = node.module.split(".")[1:]
                out.update(rest[:1] or [a.name for a in node.names])
            elif node.module:
                ext.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                if top == "gxengine":
                    out.add(a.name.split(".")[1])
                else:
                    ext.add(top)
    return out, ext


class ModuleBoundaries(unittest.TestCase):
    def test_every_module_has_a_layer(self):
        mods = {f[:-3] for f in os.listdir(PKG) if f.endswith(".py") and f != "__init__.py"}
        self.assertEqual(mods, set(LAYERS), "add new modules to LAYERS here and to the README map")

    def test_dependency_direction(self):
        for mod, layer in LAYERS.items():
            deps, _ = internal_imports(os.path.join(PKG, mod + ".py"))
            for dep in deps:
                with self.subTest(mod=mod, dep=dep):
                    self.assertIn(dep, LAYERS, f"{mod} imports unknown gxengine module {dep}")
                    ok = LAYERS[dep] < layer or (mod, dep) in SAME_LAYER
                    self.assertTrue(ok, f"{mod} (L{layer}) may not import {dep} (L{LAYERS[dep]})")

    def test_the_supervisor_imports_no_driver(self):
        """H1 (stage 4): sprint / basecheck / initconfig never call run_issue — one path for a member."""
        for mod in ("sprint", "basecheck", "initconfig", "sprinttracker", "sprintdag"):
            deps, _ = internal_imports(os.path.join(PKG, mod + ".py"))
            self.assertFalse({"driver", "cli"} & deps, mod)

    def test_standard_library_only(self):
        files = [os.path.join(PKG, f) for f in os.listdir(PKG) if f.endswith(".py")]
        for sub in ("scripts", "tools", os.path.join("tests", "helpers"), os.path.join("tests", "fakes", "bin")):
            d = os.path.join(ENGINE, sub)
            files += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".py") or "bin" in sub]
        files.append(os.path.join(ENGINE, "engine.py"))
        for path in files:
            _, ext = internal_imports(path)
            with self.subTest(path=os.path.relpath(path, ENGINE)):
                self.assertFalse(ext - set(sys.stdlib_module_names) - {"gxengine", "tests"}, ext)

    def test_every_module_imports(self):
        import importlib
        for mod in LAYERS:
            with self.subTest(mod=mod):
                importlib.import_module(f"gxengine.{mod}")


if __name__ == "__main__":
    unittest.main()
