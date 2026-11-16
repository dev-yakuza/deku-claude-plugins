"""K1 — the role runner (§5 contract) and the judge runner (§3.1) against a fake `claude` spawn."""

import json
import os
import unittest

import _k1
from _k1 import FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir

from guildcore import cost as COST
from guildcore import journal as J
from guildcore.adapters import claude as C
from guildcore.judges import runner as JR
from guildcore.roles import result as R
from guildcore.roles import runner as RR

DONE = ">>> RESULT <<<\nDONE: ok"


class Pres(unittest.TestCase):
    def test_contract_shapes(self):
        self.assertEqual(R.parse_pres("narr\n>>> RESULT <<<\nDONE: x at a.md").line, "DONE: x at a.md")
        self.assertEqual(R.parse_pres(">>> RESULT <<<\n\nDONE").status, "DONE")
        self.assertEqual(R.parse_pres("all good").violation, "none")
        self.assertEqual(R.parse_pres(">>> RESULT <<<\nDONE\n>>> RESULT <<<\nDONE").violation, "duplicate")
        self.assertEqual(R.parse_pres(">>> RESULT <<<\nLooks done").violation, "invalid")
        self.assertEqual(R.parse_pres(">>> RESULT <<<\nBLOCKED:").violation, "invalid")
        self.assertEqual(R.parse_pres(">>> RESULT <<<\nFAIL: x", allowed=("DONE",)).violation, "narrowed")

    def test_result_json_file_then_fence(self):
        d = tmpdir(self)
        os.makedirs(os.path.join(d, "out"))
        self.assertEqual(R.read_result_json(d, "```guild-result\n{\"a\": 1}\n```")[:2], ({"a": 1}, "fence"))
        with open(os.path.join(d, "out", "result.json"), "w") as fh:
            fh.write('{"a": 2}')
        self.assertEqual(R.read_result_json(d, "")[:2], ({"a": 2}, "file"))
        with open(os.path.join(d, "out", "result.json"), "w") as fh:
            fh.write("{")
        self.assertIsNotNone(R.read_result_json(d, "")[2])

    def test_blocked_needs_evidence(self):
        self.assertEqual(R.validate({"evidence": "x"}, R.RESULT_SCHEMAS["developer"], "BLOCKED"), [])
        self.assertTrue(R.validate({}, R.RESULT_SCHEMAS["developer"], "BLOCKED"))

    def test_specialist_any_of(self):
        self.assertEqual(R.validate({"none_applicable": True}, R.RESULT_SCHEMAS["specialist"]), [])
        self.assertTrue(R.validate({}, R.RESULT_SCHEMAS["specialist"]))

    def test_repair_instruction(self):
        s = R.repair_instruction(R.parse_pres("x"), ["missing tests"])
        self.assertIn("no `>>> RESULT <<<`", s)
        self.assertIn("missing tests", s)


class RoleRunner(unittest.TestCase):
    def setUp(self):
        self.wt = repo(self, {"lib/a.dart": "a\n"})
        git(self.wt, "switch", "-q", "-c", "feat")
        self.root = os.path.join(tmpdir(self), "runs")
        self.cd = tmpdir(self)
        self.user = os.path.join(tmpdir(self), "settings.json")
        with open(self.user, "w") as fh:
            json.dump({"permissions": {"deny": ["Bash(cat ~/.ssh/*)"]}, "env": {"DISABLE_TELEMETRY": "1"}}, fh)

    def runner(self, sessions, **kw):
        self.spawn = FakeSpawn(sessions)
        self.j = kw.pop("journal", RecJournal())
        return RR.Runner(journal=self.j, common_dir=self.cd, parent_env={"PATH": os.environ["PATH"], "TMPDIR": "/tmp"},
                         spawn=self.spawn, user_settings=self.user, run_root_dir=self.root, claude="claude", **kw)

    def spec(self, role="reviewer", task=None, **kw):
        kw.setdefault("issue", 7)
        return RR.RoleSpec(role, task, "Do the task.", stage="test", step="T2", worktree=self.wt,
                           model="sonnet", base="HEAD", branch="feat", **kw)

    def run_dir(self, n=1, who="reviewer"):
        return os.path.join(self.root, "%03d-test-%s" % (n, who))

    def test_done_path_and_task_contract(self):
        r = self.runner([{"stream": stream_lines(texts=["work", DONE])}])
        res = r.run_role(self.spec(inputs={"diff.patch": {"text": "d"}}))
        self.assertEqual((res.status, res.line), ("DONE", "DONE: ok"))
        call = self.spawn.calls[0]
        self.assertIn(RR.result_contract(), call["stdin"])
        self.assertTrue(call["stdin"].rstrip().endswith("Write output in en."))
        self.assertIn("BASH_MAX_TIMEOUT_MS", call["stdin"])
        self.assertIn(os.path.join(self.run_dir(), "in", "diff.patch"), call["stdin"])
        self.assertEqual(call["env"]["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"], "0")
        self.assertEqual(call["env"]["DISABLE_TELEMETRY"], "1")
        self.assertEqual(call["cwd"], self.wt)
        self.assertEqual(self.j.pids[0][0], "reviewer")
        rows = COST.rows(self.cd)
        self.assertEqual((rows[0]["who"], rows[0]["issue"], rows[0]["stage"], rows[0]["endpoint"]),
                         ("reviewer", 7, "test", C.DEFAULT_ENDPOINT))
        self.assertEqual(rows[0]["cache_5m_tokens"], 7)

    def test_result_contract_is_byte_identical_to_handoff(self):
        text = open(os.path.join(_k1._util.SKILL, "commands", "atoms", "_handoff.md"), encoding="utf-8").read()
        self.assertIn(RR.result_contract(), text)
        self.assertTrue(RR.result_contract().startswith("<!-- guild:result-contract -->"))

    def test_result_json_validated_and_artifacts_checked(self):
        rd = self.run_dir(who="explorer")
        files = {os.path.join(rd, "out", "result.json"): json.dumps({"evidence_path": "out/evidence.md"}),
                 os.path.join(rd, "out", "evidence.md"): "e"}
        r = self.runner([{"stream": stream_lines(texts=[DONE]), "files": files}])
        res = r.run_role(self.spec("explorer", result_schema=R.RESULT_SCHEMAS["explorer"]))
        self.assertEqual(res.status, "DONE")
        self.assertEqual(res.extras, {"evidence_path": "out/evidence.md"})

    def test_missing_artifact_triggers_repair_then_invalid(self):
        rd = self.run_dir(who="explorer")
        files = {os.path.join(rd, "out", "result.json"): json.dumps({"evidence_path": "out/nope.md"})}
        r = self.runner([{"stream": stream_lines(texts=[DONE]), "files": files},
                         {"stream": stream_lines(texts=[DONE])}])
        res = r.run_role(self.spec("explorer", result_schema=R.RESULT_SCHEMAS["explorer"]))
        self.assertEqual(res.status, "INVALID")
        self.assertIn("returned no valid RESULT line", res.line)
        self.assertIn("--resume", self.spawn.calls[1]["argv"])

    def test_repair_on_same_session(self):
        r = self.runner([{"stream": stream_lines("sid-9", texts=["done, trust me"])},
                         {"stream": stream_lines("sid-9", texts=[DONE])}])
        res = r.run_role(self.spec())
        self.assertEqual(res.status, "DONE")
        self.assertEqual(res.notes, ["repair-resume"])
        a = self.spawn.calls[1]["argv"]
        self.assertEqual(a[a.index("--resume") + 1], "sid-9")
        self.assertIn("no `>>> RESULT <<<`", self.spawn.calls[1]["stdin"])

    def test_repair_fresh_spawn_when_resume_fails(self):
        r = self.runner([{"stream": stream_lines(texts=["no sentinel"])},
                         {"stream": "", "rc": 1},
                         {"stream": stream_lines(texts=[DONE])}])
        res = r.run_role(self.spec())
        self.assertEqual(res.status, "DONE")
        self.assertEqual(res.notes, ["repair-resume", "repair-fresh"])
        self.assertIn("--session-id", self.spawn.calls[2]["argv"])

    def test_permission_resume_with_brief(self):
        tu = [{"id": "t1", "input": {"command": "git push origin HEAD"}}]
        den = [{"tool_use_id": "t1", "decision_reason_type": "subcommandResults", "message": "denied"}]
        r = self.runner([{"stream": stream_lines("s", texts=[">>> RESULT <<<\nBLOCKED: permission — git push"],
                                                 tool_uses=tu, denials=den)},
                         {"stream": stream_lines("s", texts=[DONE])}])
        res = r.run_role(self.spec("developer", "implement"))
        self.assertEqual(res.status, "DONE")
        self.assertEqual(res.denials[0]["class"], "forbidden")
        self.assertEqual(self.j.denials[0][1], "git push origin HEAD")
        brief = self.spawn.calls[1]["stdin"]
        self.assertIn("refused by the permission rules", brief)
        self.assertIn("done by the engine", brief)

    def test_permission_still_blocked(self):
        tu = [{"id": "t1", "input": {"command": "make deploy"}}]
        den = [{"tool_use_id": "t1", "decision_reason_type": "mode"}]
        blocked = ">>> RESULT <<<\nBLOCKED: permission — make deploy"
        r = self.runner([{"stream": stream_lines(texts=[blocked], tool_uses=tu, denials=den)},
                         {"stream": stream_lines(texts=[blocked])}])
        res = r.run_role(self.spec("developer", "implement"))
        self.assertEqual(res.status, "PERMISSION")
        self.assertEqual(res.denials[0]["class"], "other")

    def test_denial_then_done_is_accepted(self):
        tu = [{"id": "t1", "input": {"command": "env"}}]
        r = self.runner([{"stream": stream_lines(texts=[DONE], tool_uses=tu,
                                                 denials=[{"tool_use_id": "t1"}])}])
        res = r.run_role(self.spec())
        self.assertEqual(res.status, "DONE")
        self.assertEqual(len(res.denials), 1)

    def test_timeout_and_halt(self):
        r = self.runner([{"stream": stream_lines(texts=["…"]), "timed_out": True, "rc": -15, "killed_by": "timeout"}])
        self.assertEqual(r.run_role(self.spec()).status, "TIMEOUT")
        r = self.runner([{"stream": stream_lines(texts=["…"]), "rc": -15, "killed_by": "halt"}])
        self.assertEqual(r.run_role(self.spec()).status, "HALTED")

    def test_rate_limited(self):
        r = self.runner([{"stream": stream_lines(texts=["x"], rate_limits=[{"status": "rejected", "resetsAt": 99}],
                                                 result={"is_error": True})}])
        res = r.run_role(self.spec())
        self.assertEqual(res.status, "RATE_LIMITED")
        self.assertEqual(res.rl.resets_at, 99)

    def test_scope_violation_discards(self):
        def touch(argv, env, cwd, stdin):
            with open(os.path.join(cwd, "lib", "a.dart"), "a") as fh:
                fh.write("x")
        r = self.runner([{"stream": stream_lines(texts=[DONE]), "check": touch}])
        res = r.run_role(self.spec())
        self.assertEqual(res.status, "SCOPE")
        self.assertTrue(res.line.startswith("reviewer wrote outside its scope — "))

    def test_endpoint_guard_before_spawn(self):
        r = self.runner([])
        r.parent_env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:11434"
        with self.assertRaises(C.EnvHalt):
            r.run_role(self.spec())
        self.assertEqual(self.spawn.calls, [])
        r.allow_local = True
        self.spawn.sessions = [{"stream": stream_lines(texts=[DONE])}]
        self.assertEqual(r.run_role(self.spec()).status, "DONE")
        self.assertEqual(COST.rows(self.cd)[-1]["endpoint"], "http://127.0.0.1:11434")

    def test_rendered_settings_in_run_dir(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE])}])
        r.run_role(self.spec("developer", "implement", scope_check=False))
        s = json.load(open(os.path.join(self.run_dir(who="developer-implement"), "in", "settings.json")))
        self.assertIn("Bash(cat ~/.ssh/*)", s["permissions"]["deny"])
        a = self.spawn.calls[0]["argv"]
        self.assertEqual(a[a.index("--settings") + 1], os.path.join(self.run_dir(who="developer-implement"), "in", "settings.json"))
        self.assertEqual(a[a.index("--max-budget-usd") + 1], "15")

    def test_denial_class(self):
        self.assertEqual(RR.denial_class("gh api repos/o/r -X POST"), "forbidden")
        self.assertEqual(RR.denial_class("cat ../x"), "C0")
        self.assertEqual(RR.denial_class("git commit -m x"), "C3")
        self.assertEqual(RR.denial_class("git log"), "C1")


SCHEMA = {"type": "object", "required": ["verdict"],
          "properties": {"verdict": {"type": "string", "enum": ["accept", "dismiss", "unsure"]},
                         "needs_more": {"type": "array", "items": {"type": "string"}}}}


def jresult(obj, cost=0.02):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "",
                       "structured_output": obj, "total_cost_usd": cost, "usage": {}})


class JudgeRunner(unittest.TestCase):
    def setUp(self):
        self.cd = tmpdir(self)
        self.j = J.Journal(tmpdir(self), 3, clock=_k1.Clock())

    def runner(self, sessions):
        self.spawn = FakeSpawn([{"stream": s} for s in sessions])
        return JR.JudgeRunner(journal=self.j, common_dir=self.cd, parent_env={"PATH": "/usr/bin"},
                              spawn=self.spawn, run_root_dir=tmpdir(self), claude="claude",
                              user_settings=os.path.join(tmpdir(self), "none.json"))

    def spec(self, **kw):
        kw.setdefault("choice_key", "verdict")
        kw.setdefault("unsure_default", "accept")
        return JR.JudgeSpec("EX-ARB", "sonnet", SCHEMA, ["rules"], [("brief", "evidence")], issue=3, **kw)

    def test_valid_decision_cached(self):
        r = self.runner([jresult({"verdict": "dismiss"})])
        d = r.judge(self.spec())
        self.assertEqual((d.choice, d.by, d.unsure), ("dismiss", "judge:sonnet", False))
        a = self.spawn.calls[0]["argv"]
        self.assertIn("--json-schema", a)
        self.assertEqual(self.spawn.calls[0]["env"]["DISABLE_PROMPT_CACHING"], "1")
        self.assertEqual(self.spawn.calls[0]["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"], "1")
        d2 = self.runner([]).judge(self.spec())
        self.assertTrue(d2.cached)
        self.assertEqual(d2.choice, "dismiss")
        self.assertEqual(COST.rows(self.cd)[0]["who"], "J:EX-ARB")

    def test_tool_group_uses_repo_cwd_and_5m(self):
        r = self.runner([jresult({"verdict": "accept"})])
        r.judge(self.spec(tools="Read,Grep", cwd="/repo"))
        c = self.spawn.calls[0]
        self.assertEqual(c["cwd"], "/repo")
        self.assertEqual(c["env"]["FORCE_PROMPT_CACHING_5M"], "1")
        self.assertIn("dontAsk", c["argv"])

    def test_schema_retry_then_tier_up_then_fail(self):
        r = self.runner([jresult({"verdict": "maybe"}), jresult({"verdict": "maybe"}),
                         jresult({"verdict": "accept"})])
        d = r.judge(self.spec())
        models = [c["argv"][c["argv"].index("--model") + 1] for c in self.spawn.calls]
        self.assertEqual(models, ["sonnet", "sonnet", "opus"])
        self.assertIn("violated the schema", self.spawn.calls[1]["stdin"])
        self.assertEqual(d.model, "opus")
        r = self.runner([jresult(None)] * 3)
        with self.assertRaises(JR.JudgeFailed):
            r.judge(self.spec(point="other"))

    def test_unsure_maps_to_default(self):
        d = self.runner([jresult({"verdict": "unsure"})]).judge(self.spec())
        self.assertEqual((d.choice, d.unsure, d.raw_choice), ("accept", True, "unsure"))

    def test_coercion_records_raw(self):
        def evidence_rule(f):
            if f["verdict"] == "dismiss":
                return dict(f, verdict="accept"), "rule"
            return f, None
        d = self.runner([jresult({"verdict": "dismiss"})]).judge(self.spec(coercions=[evidence_rule]))
        self.assertEqual((d.choice, d.coerced, d.coerced_by, d.raw_choice), ("accept", True, "rule", "dismiss"))

    def test_needs_more_once(self):
        r = self.runner([jresult({"verdict": "accept", "needs_more": ["a.dart"]}),
                         jresult({"verdict": "dismiss", "needs_more": ["b.dart"]})])
        d = r.judge(self.spec(needs_more_fn=lambda paths: "FILE %s" % ",".join(paths)))
        self.assertEqual(d.choice, "dismiss")
        self.assertEqual(len(self.spawn.calls), 2)
        self.assertIn("FILE a.dart", self.spawn.calls[1]["stdin"])

    def test_brief_elision_and_no_elide(self):
        parts = [("comments", "C" * 5000), ("diff", "D" * 5000)]
        with self.assertRaises(JR.BriefTooLarge):
            JR.assemble(parts, 4000, no_elide=("comments",))
        b = JR.assemble(parts, 8000, no_elide=("comments",))
        self.assertIn("C" * 5000, b)
        self.assertIn("elided", b)
        self.assertLessEqual(len(b), 8000)

    def test_ladders(self):
        self.assertEqual(JR.tier_up("haiku"), "sonnet")
        self.assertEqual(JR.tier_up("claude-opus-4"), "opus")
        self.assertEqual(JR.escalate("SJ"), "L0")
        self.assertEqual(JR.escalate("human"), "human")


if __name__ == "__main__":
    unittest.main()
