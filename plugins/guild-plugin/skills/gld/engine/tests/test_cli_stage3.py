"""Stage 3 — `/gld resume` and `status` (scope §2.12, V15) and the skill docs ↔ CLI check."""

import io
import json
import os
import re
import unittest

from gxengine import cli, codes
from tests import c_world as W
from tests import s3_world as S
from tests.test_s3_followups import D1, D3, disp, inp

SKILL = os.path.realpath(os.path.join(W.ENGINE, ".."))


class Cli3(S.Stage3):
    cfg = S.config(path_rules=[S.TEST_CODE, S.SAFETY_NET, {"kind": "irreversible", "category": "external-side-effect",
                                                           "globs": ["deploy/*"], "note": "n"}])

    def cli(self, *argv, leader=None, stage=3):
        out = io.StringIO()
        rc = cli.main(list(argv), environ=self.w.environ, out=out, stage=stage,
                      units=self.units(leader) if leader is not None else None)
        return rc, out.getvalue()

    def common(self):
        return ["--repo", W.REPO, "--issue", str(W.ISSUE)]

    def dev(self, leader):
        return self.cli("dev", *self.common(), "--checkout", self.w.repo.path, "--foreground", leader=leader)

    def resume(self, *extra, leader=None, stage=3):
        return self.cli("resume", *self.common(), *extra, *(["--foreground"] if leader is not None else []),
                        leader=leader, stage=stage)

    def test_status_shows_stage3_and_the_human_answers_an_irreversible_stop(self):
        self.gh.private = False
        self.results = S.FakeResults({"review": [W.check_failed, W.check_failed, W.done]})
        self.session = self.sess(
            design=[{"write": {f"{S.SPECS}/skeleton.md": "s\n"}, "structured": S.result(
                requests=[S.request("ux-review"), S.request("i18n-review", trigger="user-facing-text")],
                discoveries=[S.discovery(note="crash", blocks=True)])}],
            implement=[{"write": {"deploy/a.yml": "x\n"}, "commit": "feat: a"},
                       {"write": {"src/app.py": "x = 2\n"}, "commit": "fix: b"},
                       {"write": {"src/app.py": "x = 3\n"}, "commit": "fix: c"}])
        ld = self.leader({"done-gate": [S.approve([disp(D1, "followup", "Merge"), disp(D3, "ignore")],
                                                  [{"id": "F1", "verdict": "keep"}], inp=inp(D1, D3))]})
        rc, out = self.dev(ld)
        self.assertEqual(rc, cli.EXIT_NEEDS_HUMAN, out)
        rc, out = self.cli("status", *self.common())
        self.assertIn("answers: continue, rerun", out)
        self.assertIn("external-side-effect   deploy/a.yml (step implement): WAITING for a human", out)
        self.assertIn("add ux-review (ui-change): applied", out)
        self.assertIn("add i18n-review (user-facing-text): declined (role-unavailable)", out)
        self.assertIn("F1   bug at src/app.py - handled by implement, not judged yet", out)
        # checked before detaching: an answer outside the row
        rc, out = self.resume("--answer", "approve")
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("continue, rerun", out)
        rc, out = self.resume("--answer", "continue", leader=ld)
        self.assertEqual(rc, cli.EXIT_OK, out)
        rc, out = self.cli("status", *self.common())
        self.assertIn("(step implement): human-decision", out)
        self.assertIn("implement        attempt 3: effort high -> xhigh", out)
        self.assertIn("debt followup: issue 900", out)
        self.assertIn("security findings (engine-local", out)
        self.assertIn("raw exception text is shown", out)
        rep = json.loads(self.cli("status", *self.common(), "--json")[1])
        self.assertEqual((len(rep["requests"]), len(rep["raised"]), rep["irreversible"]["waiting"]), (2, 1, []))

    def test_plan_template_and_skip_arguments(self):
        ld = self.leader({"plan-gate": [{"called": False}]})
        self.assertEqual(self.dev(ld)[0], cli.EXIT_NEEDS_HUMAN)
        for args, stage in ((["--answer", "rerun", "--template", "bug"], 3), (["--answer", "plan", "--template", "bug"], 2)):
            rc, out = self.resume(*args, stage=stage)
            self.assertEqual(rc, cli.EXIT_REFUSED)
            self.assertIn("--template", out)
        rc, out = self.resume("--answer", "rerun", "--template", "bug", leader=ld)
        self.assertEqual(rc, cli.EXIT_REFUSED)
        rc, out = self.resume("--answer", "plan", "--template", "refactor", leader=self.leader())
        self.assertEqual(self.procedure()["origin"]["template"], "refactor")


class SkillDocs(unittest.TestCase):
    def test_the_stage3_flow_names_only_real_arguments_answers_and_stops(self):
        p = cli.build_parser()
        sub = next(a for a in p._actions if a.dest == "command").choices["resume"]
        flags = {o for a in sub._actions for o in a.option_strings}
        with open(os.path.join(SKILL, "commands/engine/dev.md"), encoding="utf-8") as f:
            dev = f.read()
        part = dev.split("**Stage 3**", 1)[1].split("Write the human's note", 1)[0]
        for flag in set(re.findall(r"`(--[a-z][a-z-]+)", part)):
            self.assertIn(flag, flags)
        for stop in ("irreversible-change", "step-add-limit", "step-removal-request"):
            self.assertIn(f"`{stop}`", part)
            self.assertIn(stop, codes.StopReason.values())
        for name in codes.STAGE3_TEMPLATES:
            self.assertIn(f"`{name}`", part)
        self.assertEqual(set(next(a for a in sub._actions if a.dest == "template").choices),
                         set(codes.STAGE3_TEMPLATES))
        with open(os.path.join(SKILL, "commands/engine/resume.md"), encoding="utf-8") as f:
            self.assertIn("`--template`", f.read())


if __name__ == "__main__":
    unittest.main()
