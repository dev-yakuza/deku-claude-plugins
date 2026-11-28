"""U12 — stream-json reading on the recorded Claude Code 2.1.323 streams (F1, F2)."""

import json
import os
import unittest

from gxengine import streamjson as sj

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "claude")


def rec(*parts):
    return sj.read_file(os.path.join(FIX, *parts))


class IterEvents(unittest.TestCase):
    def test_bad_lines_become_warnings_never_a_crash(self):
        lines = ['{"type":"system","subtype":"init"}', "not json", "", "  ", "[1,2]", "42",
                 b'{"type":"result","is_error":false}', b"\xff\xfe broken", None]
        evs = list(sj.iter_events(lines))
        dicts = [e for e in evs if isinstance(e, dict)]
        self.assertEqual([d["type"] for d in dicts], ["system", "result"])
        self.assertEqual(len(sj.warnings(evs)), 5)   # not json, [1,2], 42, broken bytes, None

    def test_readers_ignore_warnings(self):
        evs = list(sj.iter_events(["oops", '{"type":"result","total_cost_usd":0.5}']))
        self.assertIsNone(sj.first_init(evs))
        self.assertEqual(sj.result_event(evs)["total_cost_usd"], 0.5)
        self.assertEqual(sj.tool_uses(evs), [])


class Recorded(unittest.TestCase):
    def test_init_of_f2_r4(self):
        evs = rec("f2", "r4.jsonl")
        init = sj.first_init(evs)
        self.assertEqual(init["claude_code_version"], "2.1.323")
        self.assertEqual(init["permissionMode"], "default")
        self.assertEqual(init["skills"], [])
        self.assertEqual(sj.init_count(evs), 1)

    def test_tool_uses_and_results_f2_r4(self):
        evs = rec("f2", "r4.jsonl")
        uses = sj.tool_uses(evs)
        self.assertEqual([u["name"] for u in uses], ["Read", "Edit", "Bash", "Bash"])
        res = sj.tool_results(evs)
        commit = uses[3]
        self.assertEqual(commit["input"]["command"], "git commit -n -m x")
        self.assertTrue(res[commit["id"]]["is_error"])
        self.assertIn("blocked by gx gate", res[commit["id"]]["content"])
        self.assertFalse(res[uses[0]["id"]]["is_error"], "an absent is_error is False")
        denials = sj.permission_denials(sj.result_event(evs))
        self.assertEqual([d["tool_use_id"] for d in denials], [commit["id"]])

    def test_permission_denials_f1_b(self):
        evs = rec("f1", "B.jsonl")
        r = sj.result_event(evs)
        self.assertEqual([d["tool_name"] for d in sj.permission_denials(r)], ["Write", "Read"])
        ev = sj.permission_denied_events(evs)
        self.assertEqual({e["tool_use_id"] for e in ev}, {d["tool_use_id"] for d in sj.permission_denials(r)})
        c = sj.cost_and_tokens(r)
        self.assertAlmostEqual(c["cost_usd"], 0.00181912)
        self.assertEqual(c["num_turns"], 6)
        self.assertIsInstance(c["cache_read_input_tokens"], int)

    def test_every_recording_parses_without_warnings(self):
        for d in ("f1", "f2"):
            for name in sorted(os.listdir(os.path.join(FIX, d))):
                with self.subTest(f=f"{d}/{name}"):
                    evs = rec(d, name)
                    self.assertEqual(sj.warnings(evs), [])
                    self.assertIsNotNone(sj.first_init(evs))
                    self.assertIsNotNone(sj.result_event(evs))


class Shapes(unittest.TestCase):
    def test_tool_result_meta_decision_and_list_content(self):
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/x"}},
                {"type": "text", "text": "hi"}]}}),
            json.dumps({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                 "content": [{"type": "text", "text": "File is in a directory that is denied"}]}]},
                "tool_result_meta": [{"id": "t1", "permission_decision": {"decision": "reject"}}]}),
        ]
        res = sj.tool_results(list(sj.iter_events(lines)))
        self.assertEqual(res["t1"], {"content": "File is in a directory that is denied", "is_error": True,
                                     "decision": "reject"})

    def test_structured_output_and_last_result(self):
        evs = list(sj.iter_events([json.dumps({"type": "result", "n": 1}),
                                   json.dumps({"type": "result", "n": 2, "structured_output": {"status": "done"}})]))
        r = sj.result_event(evs)
        self.assertEqual(r["n"], 2)
        self.assertEqual(sj.structured_output(r), {"status": "done"})
        self.assertIsNone(sj.structured_output({"structured_output": "text"}))
        self.assertIsNone(sj.structured_output(None))

    def test_cost_absent_is_none_not_zero(self):
        self.assertEqual(sj.cost_and_tokens({"type": "result"}),
                         {"cost_usd": None, "cache_read_input_tokens": None,
                          "cache_creation_input_tokens": None, "num_turns": None})
        self.assertIsNone(sj.cost_and_tokens({"total_cost_usd": True})["cost_usd"])
        self.assertEqual(sj.cost_and_tokens(None)["cost_usd"], None)


if __name__ == "__main__":
    unittest.main()
