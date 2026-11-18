"""K5 — the command layer (design §2.4 attended driver, §10.3 old-supervisor path, stage stubs, /gld update):
dev.md's engine driver is the operative section and every CLI verb it names exists; the stage commands run
`dev run --only <stage>`; status / resume route through the engine; /gld update adopts the gate first."""

import os
import re
import unittest

import _util
from workflows.dev import cli as CLI

CMDS = os.path.join(_util.SKILL, "commands")


def cmd(name):
    return _util.read(os.path.join(CMDS, name))


def driver():
    s = cmd("dev.md")
    return s[s.index("## Engine driver (0.102)"):s.index("\n## Legacy spine (0.101.x reference)")]


class DevDriver(unittest.TestCase):
    def test_driver_comes_first_and_is_short(self):
        s = cmd("dev.md")
        self.assertLess(s.index("## Engine driver (0.102)"), s.index("## Phase 0 — Setup"))
        self.assertLess(len(driver().split("\n")), 40)

    def test_every_verb_the_driver_names_is_a_cli_subcommand(self):
        verbs = set(re.findall(r"`E dev ([a-z-]+)", driver()))
        self.assertEqual(verbs, {"run", "wait", "answer", "hold", "note"})
        sub = CLI.parser()._subparsers._group_actions[0].choices
        for v in verbs:
            self.assertIn(v, sub)

    def test_old_supervisor_path_and_mode_checks(self):
        d = driver()
        self.assertIn("printenv GLD_UNATTENDED", d)
        self.assertIn("printenv GLD_SUPERVISOR_VERSION", d)
        self.assertIn("E dev run --issue $1 --unattended --detach", d)
        self.assertIn("predict_first", d)
        self.assertIn("AskUserQuestion", d)
        self.assertNotIn("printenv GLD_UNATTENDED GLD_SUPERVISOR_VERSION", d)       # one variable per call

    def test_wait_matches_the_event_kinds_the_worker_writes(self):
        d = driver()
        for k in ("`progress`", "`ask`", "`terminal`"):
            self.assertIn(k, d)
        self.assertIn("--max-seconds 540", d)


class StageStubs(unittest.TestCase):
    def test_each_stage_command_runs_only_its_stage(self):
        want = {"analyze.md": "analyze", "design.md": "design", "test.md": "test", "qa.md": "qa",
                "implement.md": "execute", "debug.md": "execute", "refactor.md": "execute"}
        for f, stage in want.items():
            head = cmd(f)[:1500]
            self.assertIn("> **0.102 (engine)**", head, f)
            self.assertIn("`--only %s`" % stage, head, f)
            self.assertIn("*Engine driver*", head, f)

    def test_only_choices_match_the_stubs(self):
        r = [a for a in CLI.parser()._subparsers._group_actions[0].choices["run"]._actions if a.dest == "only"][0]
        self.assertEqual(set(r.choices), {"analyze", "design", "execute", "test", "qa"})

    def test_status_and_resume_route_through_the_engine(self):
        self.assertIn("gld_engine.py status show --issue $1", cmd("status.md")[:1200])
        self.assertIn("gld_engine.py status route --issue $1", cmd("resume.md")[:1200])


class Update(unittest.TestCase):
    def test_gate_first_ordering(self):
        u = cmd("update.md")
        i = u.index("**0.102 ordering — the gate FIRST**")
        self.assertLess(i, u.index("- **Gate script** →"))
        self.assertIn("merge that commit into the default branch **before** running the engine", u)
        self.assertIn("GUILD_GATE_CONFIG", u[i:i + 1500])

    def test_engine_defaults_listed_are_real(self):
        from guildcore.config import ENGINE_DEFAULTS
        u = cmd("update.md")
        blk = u[u.index("**0.102 config and habits**"):]
        blk = blk[:blk.index("- **`sprint.stage_groups`**")]
        for k in re.findall(r"`([a-z_]+)(?::|`)", blk):
            if k in ("engine", "commands", "test_one", "effective", "copy_ignored"):
                continue
            self.assertIn(k, ENGINE_DEFAULTS, k)

    def test_stage_groups_kept_for_the_downgrade(self):
        self.assertIn("**keep it**", cmd("update.md"))


if __name__ == "__main__":
    unittest.main()
