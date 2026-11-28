"""Stage 2 — `/gld resume` and `status` (scope §2.7, D17, D24, V9: L26, the skill docs ↔ CLI).

The human answers in the leader's seat through the CLI (foreground, stage 2): approve,
replan, plan, close-as-decided with --close-reason; no D4 narrowing for the human; a
needs_leader stop takes no answer (resume calls the leader again). `status` shows the leader
recommendation / failure and the leader decisions. The skill documents name every CLI
argument and answer they tell the conversation to use.
"""

import io
import json
import os
import re
import tempfile
import unittest

from gxengine import cli, codes
from tests import c_world as W
from tests.test_close import CLOSE
from tests.test_leader_flow import LA, plan_ok

SKILL = os.path.realpath(os.path.join(W.ENGINE, ".."))
REC_PLAN = {"answer": "plan", "step": None, "note": "fits the template"}


def escalate(rec):
    return LA("escalate", reason="needs-human-decision", note="ask", recommendation=rec)


class Cli2(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.w = W.World(self._tmp.name, steps=W.stage2_steps())
        rules = W.gh_rules()
        for reason in ("completed", "not planned"):
            rules["rules"].insert(0, {"args": CLOSE + [reason], "stdout": ""})
        self.w.set_gh(rules)

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *argv, leader=None, **units):
        out = io.StringIO()
        u = W.units(self.w, leader=leader, **units) if leader is not None else None
        rc = cli.main(list(argv), environ=self.w.environ, out=out, units=u, stage=2)
        return rc, out.getvalue()

    def common(self):
        return ["--repo", W.REPO, "--issue", str(W.ISSUE)]

    def dev(self, leader, **units):
        return self.cli("dev", *self.common(), "--checkout", self.w.repo.path, "--foreground", leader=leader, **units)

    def resume(self, *extra, leader=None, **units):
        return self.cli("resume", *self.common(), *extra, *(["--foreground"] if leader is not None else []),
                        leader=leader, **units)

    def note(self, text):
        p = os.path.join(self.w.tmp, "note.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_l26_plan_and_approve_by_a_human_with_the_recommendation_shown(self):
        ld = W.FakeLeader(self.w, {"plan-gate": [escalate(REC_PLAN)],
                                   "done-gate": [escalate({"answer": "approve", "step": None, "note": "ok"})]})
        rc, out = self.dev(ld)
        self.assertEqual(rc, cli.EXIT_NEEDS_HUMAN, out)
        rc, out = self.cli("status", *self.common())
        self.assertIn("leader recommendation: plan", out)
        self.assertIn("answers: plan, rerun, close-as-decided, escalate", out)
        rep = json.loads(self.cli("status", *self.common(), "--json")[1])
        self.assertEqual(rep["question"]["recommendation"]["answer"], "plan")
        rc, out = self.resume("--answer", "plan", "--note-file", self.note("go"), leader=ld)
        self.assertEqual(rc, cli.EXIT_NEEDS_HUMAN, out)                   # now the done-gate escalates
        self.assertEqual(self.w.state()["revision"], 2)
        rc, out = self.resume("--answer", "approve", leader=ld)
        self.assertEqual(rc, cli.EXIT_OK, out)
        rc, out = self.cli("status", *self.common())
        self.assertIn("pull request 77", out)
        self.assertIn("leader decisions", out)

    def test_l26_close_as_decided_needs_the_close_reason(self):
        ld = W.FakeLeader(self.w, {"plan-gate": [escalate({"answer": "close-as-decided", "step": None,
                                                           "note": "decided"})]})
        self.assertEqual(self.dev(ld)[0], cli.EXIT_NEEDS_HUMAN)
        rc, out = self.resume("--answer", "close-as-decided")                       # checked before detaching
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("--close-reason", out)
        rc, out = self.resume("--answer", "rerun", "--close-reason", "completed")
        self.assertEqual(rc, cli.EXIT_REFUSED)
        rc, out = self.resume("--answer", "close-as-decided", "--close-reason", "completed",
                              "--note-file", self.note("Shipped in the last release."), leader=ld)
        self.assertEqual(rc, cli.EXIT_OK, out)
        self.assertEqual(self.w.state()["closed"]["reason"], "completed")
        self.assertIn("closed as decided", self.cli("status", *self.common())[1])

    def test_l26_replan_by_a_human(self):
        res = W.FakeResults({"review": [W.blocked, W.done]})
        ld = W.FakeLeader(self.w, {"plan-gate": [plan_ok()], "blocked": [escalate(
            {"answer": "replan", "step": None, "note": "plan again"})],
            "done-gate": [LA("approve", reason="acceptance-met")]})
        self.assertEqual(self.dev(ld, results=res)[0], cli.EXIT_NEEDS_HUMAN)
        rc, out = self.cli("status", *self.common())
        self.assertIn("answers: rerun, replan, escalate", out)
        rc, out = self.resume("--answer", "replan", leader=ld, results=res)
        self.assertEqual(rc, cli.EXIT_OK, out)
        self.assertEqual([c["situation"] for c in ld.calls].count("plan-gate"), 2)

    def test_d24_a_needs_leader_stop_takes_no_answer(self):
        ld = W.FakeLeader(self.w, {"plan-gate": [{"stop": "infra-stop"}, plan_ok()],
                                   "done-gate": [LA("approve", reason="acceptance-met")]})
        self.assertEqual(self.dev(ld)[0], cli.EXIT_NEEDS_LEADER)
        rc, out = self.cli("status", *self.common())
        self.assertIn("waiting for the leader", out)
        rc, out = self.resume("--answer", "plan")
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("leader", out)
        rc, out = self.resume(leader=ld)
        self.assertEqual(rc, cli.EXIT_OK, out)


class SkillDocsMatchTheCli(unittest.TestCase):
    """V9: every `engine.py resume` argument and answer the skill docs use exists in the CLI."""

    def test_resume_arguments_and_answers(self):
        p = cli.build_parser()
        sub = next(a for a in p._actions if a.dest == "command").choices["resume"]
        flags = {o for a in sub._actions for o in a.option_strings}
        answers = set(next(a for a in sub._actions if a.dest == "answer").choices)
        close = set(next(a for a in sub._actions if a.dest == "close_reason").choices)
        self.assertEqual(close, set(codes.CloseReason.values()))
        for rel in ("commands/engine/dev.md", "commands/engine/resume.md", "SKILL.md"):
            with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
                text = f.read()
            # the flags of every `engine.py resume` line, and every backticked flag of the
            # engine command docs (the prose that tells the conversation what to add)
            used = set()
            for line in text.splitlines():
                if "engine.py resume" in line:
                    used |= set(re.findall(r"(--[a-z][a-z-]+)", line))
            if rel.startswith("commands/engine/"):
                used |= set(re.findall(r"`(--[a-z][a-z-]+)", text))
            used -= {"--wait", "--json", "--mode", "--checkout"}      # status / dev flags
            if rel.startswith("commands/engine/"):
                self.assertTrue(used, rel)
            for flag in used:
                with self.subTest(doc=rel, flag=flag):
                    self.assertIn(flag, flags)
            for ans in re.findall(r"- `([a-z-]+)` — ", text):
                with self.subTest(doc=rel, answer=ans):
                    self.assertIn(ans, answers)
        with open(os.path.join(SKILL, "commands/engine/dev.md"), encoding="utf-8") as f:
            dev = f.read()
        for code in codes.LeaderReason.values():
            with self.subTest(reason=code):
                self.assertIn(f"`{code}`", dev)
        for code in ("0", "4", "10", "11"):
            self.assertIn(f"| {code} ", dev)


if __name__ == "__main__":
    unittest.main()
