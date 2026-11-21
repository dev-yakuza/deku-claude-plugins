"""K6 item 22 — `grade_replay.py --judge claude`: the paid grader run goes through the grader's own JudgeRunner.

No test calls `claude`: the runner is injected (a fake with the JudgeRunner `judge(spec)` shape and a per-decision cost).
"""

import json
import os
import unittest

import _util  # noqa: F401
from _k1 import tmpdir

from guildcore.judges.runner import Decision
from workflows.dev.replay import grade_replay as GR


class FakeRunner(object):
    def __init__(self):
        self.specs = []

    def judge(self, spec):
        self.specs.append(spec)
        if spec.choice_key == "choice":
            return Decision("ok-choice", {"choice": "ok-choice", "reason": "r", "cited_evidence": []},
                            "judge:opus", "c1", cost=0.25)
        return Decision("ok", {"given_info": "ok", "outcome": "consistent", "reason": "r", "cited_evidence": []},
                        "judge:opus", "c2", cost=0.5)


ITEM = {"id": "#12/D3", "group": "QA", "block": {"point": "QA", "stage": "qa", "choice": "pass", "by": "judge:sonnet"},
        "issue_text": "#12 t", "ac": "", "brief": "b", "evidence": "nothing happened afterwards at all", "untrusted": "",
        "expect": {"given_info": "ok", "blind": "pass"}}


class ClaudeJudge(unittest.TestCase):
    def test_runner_is_called_twice_per_decision_and_cost_is_summed(self):
        fr = FakeRunner()
        d = tmpdir(self)
        rep = GR.run([ITEM, dict(ITEM, id="#12/D4")], "claude", d, runner=fr)
        self.assertTrue(os.path.exists(os.path.join(d, "grade_replay_claude.json")))
        self.assertEqual(len(fr.specs), 4)
        self.assertTrue(all(s.model == "opus" for s in fr.specs))
        self.assertAlmostEqual(rep["totals"]["cost_usd"], 1.5)
        self.assertAlmostEqual(rep["totals"]["cost_per_decision"], 0.75)
        self.assertEqual([r["cost_usd"] for r in rep["rows"]], [0.75, 0.75])
        self.assertEqual(rep["totals"]["errors"], 0)

    def test_main_refuses_without_an_explicit_config_dir(self):
        old = os.environ.pop("CLAUDE_CONFIG_DIR", None)
        try:
            d = tmpdir(self)
            p = os.path.join(d, "c.json")
            with open(p, "w") as fh:
                json.dump([ITEM], fh)
            self.assertEqual(GR.main(["--corpus", p, "--judge", "claude", "--out", d]), 64)
        finally:
            if old is not None:
                os.environ["CLAUDE_CONFIG_DIR"] = old


if __name__ == "__main__":
    unittest.main()
