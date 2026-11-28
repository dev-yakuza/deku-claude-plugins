"""V13 (stage 2, Q5): the leader answer schemas measured against the REAL Claude Code CLI.

tests/fixtures/claude/leader/real-2.1.323/ holds the normalised recordings of real leader
calls (`leader.call()` with haiku / low, see the README there) and two direct CLI probes.
These tests pin what was measured:

  * the schema the engine renders today is byte-for-byte the schema the CLI accepted (a
    template or render change makes this fail — re-record then, scope §6.3);
  * the real init lists the judge tools plus StructuredOutput (recorded fact — the engine no longer
    compares init, FC decision D);
  * the real answer is at result.structured_output, with integer enums as JSON integers and
    null-able fields as null / objects, and the engine's check_answer accepts it;
  * the CLI itself refuses a schema violation inside the session (StructuredOutput tool
    error) — and the engine's own check refuses the same input (ANSWER_SCHEMA);
  * the recordings replay through the fake claude into the same LeaderResult.
"""

import json
import os
import tempfile
import unittest

from gxengine import canary, codes, defaults, leader, render, streamjson
from tests import test_leader as TL
from tests.helpers import fakes

REAL = os.path.join(fakes.FIXTURES, "claude", "leader", "real-2.1.323")
CALLS = ("plan-gate-rerun", "plan-gate-plan", "plan-gate-escalate", "done-gate-rerun", "done-gate-nodisc-rerun",
         "blocked-escalate", "new-comment-escalate")
PROBES = {"probe-plan-gate": "plan-gate-rerun", "probe-done-gate": "done-gate-rerun"}
SCHEMA_REFUSED = "Output does not match required schema"
SR = codes.StopReason
NEW_COMMENTS = [{"id": 9101, "author_association": "OWNER", "created_at": "2026-11-24T00:00:00Z"},
                {"id": 9102, "author_association": "MEMBER", "created_at": "2026-11-24T00:01:00Z"}]


def _json(name):
    with open(os.path.join(REAL, name), encoding="utf-8") as f:
        return json.load(f)


def _events(name):
    with open(os.path.join(REAL, name + ".jsonl"), encoding="utf-8") as f:
        return list(streamjson.iter_events(f.read().splitlines()))


def _allowed(call):
    a = call["allowed"]
    return leader.Allowed(a["answers"], a["rerun_steps"], a["human_answers"], a["human_rerun_steps"],
                          [(n["reason"], n["removed"]) for n in a["narrowed"]])


def _check(call, answer):
    return leader.check_answer(call["situation"], answer, _allowed(call), call["ids"],
                               checklist_acs=call["checklist_acs"])


def _structured_tool_uses(events):
    """[(input, tool_result content, is_error)] of every StructuredOutput call, in order."""
    uses = [u for u in streamjson.tool_uses(events) if u.get("name") == "StructuredOutput"]
    results = {}
    for e in events:
        if isinstance(e, dict) and e.get("type") == "user":
            for c in (e.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    results[c.get("tool_use_id")] = (c.get("content"), bool(c.get("is_error")))
    return [(u["input"], *results[u["id"]]) for u in uses]


class RealLeaderSchemas(unittest.TestCase):
    def test_recordings_present(self):
        for name in CALLS:
            for ext in (".jsonl", ".schema.json", ".call.json"):
                self.assertTrue(os.path.isfile(os.path.join(REAL, name + ext)), name + ext)
        situations = {_json(n + ".call.json")["situation"] for n in CALLS}
        self.assertEqual(situations, {SR.PLAN_GATE.value, SR.DONE_GATE.value, SR.BLOCKED.value, SR.NEW_COMMENT.value})

    def test_the_engine_renders_the_schema_the_cli_accepted(self):
        for name in CALLS:
            with self.subTest(recording=name):
                call = _json(name + ".call.json")
                rendered = leader.render_answer_schema(call["situation"], _allowed(call), call["ids"])
                sent = {k: v for k, v in rendered.items() if k not in render.CLI_SCHEMA_DROP}
                self.assertEqual(sent, _json(name + ".schema.json"),
                                 "the answer schema changed since V13 — re-record (stage-2 scope §6.3)")

    def test_the_recorded_argv_is_the_leader_render(self):
        for name in CALLS:
            with self.subTest(recording=name):
                call = _json(name + ".call.json")
                self.assertEqual(call["model_effort"], ["haiku", "low"])          # V13 only; engine: opus / high
                flags = [f for f in call["argv_flags"] if f not in ("--model", "--effort", "--max-budget-usd")]
                want = [f for f in render.CLAUDE_FIXED_FLAGS if f.startswith("--")]
                want += ["--settings", "--tools", "--json-schema", "--append-system-prompt"]
                self.assertEqual(flags, want)

    def test_the_real_init_has_the_judge_tools(self):
        for name in CALLS:
            with self.subTest(recording=name):
                init = streamjson.first_init(_events(name))
                tools = list(defaults.TOOLS[codes.RoleClass.JUDGE.value])
                self.assertEqual(sorted(init["tools"]), sorted(tools + ["StructuredOutput"]))
                self.assertEqual(init["claude_code_version"], "2.1.323")

    def test_the_real_answer_is_accepted(self):
        for name in CALLS:
            with self.subTest(recording=name):
                call = _json(name + ".call.json")
                res = streamjson.result_event(_events(name))
                self.assertEqual((res["subtype"], res["terminal_reason"]), ("success", "completed"))
                so = streamjson.structured_output(res)
                self.assertIsNotNone(so, "the answer arrives as result.structured_output")
                self.assertEqual(_check(call, so), [])
                self.assertEqual((so["answer"], so["step"], so["reason"]),
                                 (call["engine"]["answer"], call["engine"]["step"], call["engine"]["reason"]))
                # the StructuredOutput tool input is the same object
                self.assertEqual(_structured_tool_uses(_events(name))[-1][0], so)

    def test_integer_enums_and_nulls_come_back_typed(self):
        dg = streamjson.structured_output(streamjson.result_event(_events("done-gate-rerun")))
        self.assertEqual([v["ac"] for v in dg["ac_verdicts"]], [1, 2])
        self.assertTrue(all(type(v["ac"]) is int for v in dg["ac_verdicts"]))
        self.assertIsNone(dg["recommendation"])
        nc = streamjson.structured_output(streamjson.result_event(_events("new-comment-escalate")))
        self.assertEqual([c["id"] for c in nc["comments"]], [9101, 9102])
        self.assertTrue(all(type(c["id"]) is int for c in nc["comments"]))
        self.assertIsNone(nc["step"])
        self.assertIsInstance(nc["recommendation"], dict)                       # object side of object | null
        pg = streamjson.structured_output(streamjson.result_event(_events("plan-gate-plan")))
        self.assertEqual((pg["plan"], pg["close"], pg["step"]), ({"template": "feature"}, None, None))
        nd = streamjson.structured_output(streamjson.result_event(_events("done-gate-nodisc-rerun")))
        self.assertNotIn("discoveries", nd)                                    # an empty id list drops the field
        self.assertNotIn("discoveries", _json("done-gate-nodisc-rerun.schema.json")["required"])


class RealCliEnforcesTheSchema(unittest.TestCase):
    def test_a_violation_is_refused_inside_the_session(self):
        for probe, source in PROBES.items():
            with self.subTest(probe=probe):
                call = _json(source + ".call.json")
                self.assertEqual(_json(probe + ".schema.json"), _json(source + ".schema.json"))
                uses = _structured_tool_uses(_events(probe))
                self.assertEqual(len(uses), 2)
                (bad, bad_text, bad_err), (good, good_text, good_err) = uses
                self.assertTrue(bad_err)
                self.assertIn(SCHEMA_REFUSED, json.dumps(bad_text))
                self.assertFalse(good_err)
                # the engine refuses what the CLI refused, for the same reason class
                self.assertEqual({c for c, _ in _check(call, bad)}, {codes.LeaderFormatReason.ANSWER_SCHEMA.value})
                so = streamjson.structured_output(streamjson.result_event(_events(probe)))
                self.assertEqual(so, good, "only the accepted call reaches result.structured_output")
                self.assertEqual(_check(call, so), [])

    def test_what_the_cli_named(self):
        text = {p: json.dumps(_structured_tool_uses(_events(p))[0][1]) for p in PROBES}
        self.assertIn("/answer: must be equal to one of the allowed values", text["probe-plan-gate"])
        self.assertIn("/requirements/0/row: must be equal to one of the allowed values", text["probe-plan-gate"])
        self.assertIn("/ac_verdicts/0/ac: must be integer", text["probe-done-gate"])
        self.assertIn("/ac_verdicts/1/ac: must be equal to one of the allowed values: [1,2]", text["probe-done-gate"])
        close = streamjson.structured_output(streamjson.result_event(_events("probe-plan-gate")))
        self.assertEqual(close["close"], {"reason": "not-planned"})             # object side of close | null


class RealRecordingReplays(unittest.TestCase):
    """Each recording, replayed unchanged by the fake claude, gives leader.call() the recorded answer."""

    def world(self, name, tmp):
        if name.startswith("plan-gate"):
            over = {}
            if name == "plan-gate-plan":
                over["issue_md"] = ("# Issue 42\n\nLet users choose the review question types in Settings. The "
                                    "choice must be kept after an app restart. Reuse the existing review-type "
                                    "preference key.\n")
            return TL.plan_world(tmp), (SR.PLAN_GATE.value, "check", "plan"), over
        if name.startswith("done-gate"):
            return (TL.done_gate_world(tmp, discoveries="nodisc" not in name), (SR.DONE_GATE.value, "check", "done"),
                    {})
        w = TL.blocked_world(tmp)
        if name.startswith("blocked"):
            return w, (SR.BLOCKED.value, "leader", "design"), {}
        w.set("design", "pending")
        return w, (SR.NEW_COMMENT.value, "leader", "design"), {"new_comments": NEW_COMMENTS}

    def test_replay(self):
        for name in CALLS:
            with self.subTest(recording=name), tempfile.TemporaryDirectory() as tmp:
                w, (sit, kind, step), over = self.world(name, tmp)
                scn = w.lay.scenario("real.json", {"format": 1, "stream": os.path.join(REAL, name + ".jsonl"),
                                                   "init_from_argv": True})
                res = leader.call(w.request(sit, kind, step, scenarios=[scn], **over))
                call = _json(name + ".call.json")
                self.assertEqual((res.answer, res.step, res.reason, res.failed, res.stop),
                                 tuple(call["engine"][k] for k in ("answer", "step", "reason", "failed", "stop")))
                self.assertEqual(res.allowed.to_json(), call["allowed"])
                self.assertEqual(res.cost_usd, call["engine"]["cost_usd"])
                self.assertEqual(w.call_schema(), _json(name + ".schema.json"))


if __name__ == "__main__":
    unittest.main()
