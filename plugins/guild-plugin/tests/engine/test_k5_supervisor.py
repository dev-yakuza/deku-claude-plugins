"""K5 — the supervisor and batch call sites (design §2.4 R4C-m1, §10.3): each member is ONE engine run by
absolute path; the engine's exit codes 4 / 6 / 126·127 are handled right after the child — before the
rate-limit fence and before any failure arm, writing no failed.txt — in BOTH copies; the supervisor exports
GLD_SUPERVISOR_VERSION and checks the kill switch and the active version before every pop. (Behaviour is
exercised end to end in tests/sprint_supervisor_test.sh K5a–g.)"""

import json
import os
import re
import subprocess
import sys
import unittest

import _util
from _k1 import tmpdir

ATOMS = os.path.join(_util.SKILL, "commands", "atoms")
TPL = os.path.join(_util.SKILL, "templates", "sprint-supervisor.sh")
BATCH = os.path.join(_util.SKILL, "commands", "batch.md")
PLUGIN_JSON = os.path.join(_util.PLUGIN, ".claude-plugin", "plugin.json")


def render(case):
    human = tmpdir(case)
    p = subprocess.run([sys.executable, os.path.join(ATOMS, "render_supervisor.py"), "--tracker", "9",
                        "--owner-repo", "o/r", "--default-branch", "main", "--container", os.path.join(human, "c"),
                        "--human-repo", human, "--dag-path", os.path.join(ATOMS, "sprint_dag.py"), "--order", "1",
                        "--out", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert p.returncode == 0, p.stderr
    return p.stdout.decode()


def code(text):
    return "\n".join(ln for ln in text.split("\n") if not ln.strip().startswith("#"))


def batch_script():
    src = _util.read(BATCH)
    return re.search(r'```bash\n(#!/usr/bin/env bash.*?)\n```', src, re.S).group(1)


class Supervisor(unittest.TestCase):
    def test_engine_by_absolute_path_and_version_rendered(self):
        s = render(self)
        eng = re.search(r"^ENGINE=(.*)$", s, re.M).group(1).strip("'")
        self.assertTrue(os.path.isabs(eng))
        self.assertTrue(os.path.isfile(eng))
        self.assertTrue(eng.endswith(os.path.join("engine", "gld_engine.py")))
        with open(PLUGIN_JSON) as fh:
            ver = json.load(fh)["version"]
        self.assertEqual(re.search(r"^SUPERVISOR_VERSION=(.*)$", s, re.M).group(1).strip("'"), ver)

    def test_launch_is_the_engine_with_the_supervisor_version(self):
        c = code(render(self))
        self.assertNotIn('"/gld dev $ISSUE"', c)
        launch = c[c.index('( cd "$WT" && GLD_UNATTENDED=1'):]
        launch = launch[:launch.index('|| EXIT_CODE=$?')]
        self.assertIn('GLD_SUPERVISOR_VERSION="$SUPERVISOR_VERSION"', launch)
        self.assertIn('"$PY" "$ENGINE" dev run --issue "$ISSUE" --unattended', launch)
        for g in ("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1", "BASH_DEFAULT_TIMEOUT_MS=600000",
                  "BASH_MAX_TIMEOUT_MS=3600000", "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0"):
            self.assertIn(g, launch)

    def test_exit_4_6_positions(self):
        s = render(self)
        launch = s.index('dev run --issue "$ISSUE" --unattended')
        ex0 = s.index("# <!-- guild:supervisor-core:engineexit -->")
        ex1 = s.index("# <!-- /guild:supervisor-core:engineexit -->")
        fence = s.index("# <!-- guild:supervisor-core:ratelimit -->")
        first_fail = next(i for i in (m.start() for m in re.finditer(r'record_failure "\$ISSUE"', s))
                          if i > launch and not s[s.rindex("\n", 0, i) + 1:i].lstrip().startswith("#"))
        self.assertTrue(launch < ex0 < ex1 < fence < first_fail)
        block = code(s[ex0:ex1])
        self.assertNotIn("record_failure", block)
        self.assertNotIn("failed.txt", block)
        self.assertNotIn("RESUME_TRIES", block)
        self.assertIn('"$EXIT_CODE" -eq 4', block)
        self.assertIn('"$EXIT_CODE" -eq 6', block)
        self.assertIn('"$EXIT_CODE" -eq 126', block)
        self.assertIn('"$EXIT_CODE" -eq 127', block)
        for reason in ("engine-kill-switch", "plugin-version-changed", "engine-env-python", "engine-env-"):
            self.assertIn(reason, block)
        self.assertIn("busy-skipped", block)
        self.assertIn("sleep 300", block)

    def test_gate_before_every_pop(self):
        s = code(render(self))
        loop = s[s.index('while [ ${#QUEUE[@]} -gt 0 ]; do'):]
        self.assertLess(loop.index("if ! engine_gate; then"), loop.index("ISSUE=${QUEUE[0]}"))
        gate = s[s.index("engine_gate() {"):]
        gate = gate[:gate.index("\n}\n")]
        self.assertIn("guild/engine/HALT", gate)
        self.assertIn('"$PY" "$ENGINE" version --active --cwd "$HUMAN_REPO"', gate)

    def test_handoff_enumerates_the_new_halted_reasons(self):
        h = _util.read(os.path.join(ATOMS, "_handoff.md"))
        for r in ("plugin-version-changed", "engine-kill-switch", "engine-env-<reason>", "busy-skipped"):
            self.assertIn(r, h)


class Batch(unittest.TestCase):
    def test_batch_runs_the_engine_and_handles_4_and_6_before_the_fence(self):
        b = batch_script()
        c = code(b)
        self.assertNotIn('"/gld dev $ISSUE"', c)
        self.assertIn('python3 "$ENGINE" dev run --issue "$ISSUE" --unattended', c)
        launch = b.index('dev run --issue "$ISSUE" --unattended')
        e4 = b.index('"$EXIT_CODE" -eq 4', launch)
        e6 = b.index('"$EXIT_CODE" -eq 6', launch)
        fence = b.index("# <!-- guild:supervisor-core:ratelimit -->", launch)
        self.assertTrue(launch < e4 < e6 < fence)
        self.assertIn("busy-skipped", b)
        self.assertIn("ENGINE=<ENGINE_PATH>", b)


class EngineVersionCli(unittest.TestCase):
    def test_version_active_reads_the_isolated_config_dir(self):
        """`gld_engine.py version --active` asks `claude plugin list --json` — here a stub `claude` on PATH."""
        d = tmpdir(self)
        stub = os.path.join(d, "claude")
        with open(stub, "w") as fh:
            fh.write("#!/bin/sh\necho '[{\"id\":\"guild-plugin@m\",\"version\":\"9.9.9\",\"enabled\":true}]'\n")
        os.chmod(stub, 0o755)
        env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"], CLAUDE_CONFIG_DIR=os.path.join(d, "cfg"))
        p = subprocess.run([sys.executable, os.path.join(_util.ENGINE, "gld_engine.py"), "version", "--active",
                            "--cwd", d], stdout=subprocess.PIPE, env=env)
        self.assertEqual(p.stdout.decode().strip(), "9.9.9")


if __name__ == "__main__":
    unittest.main()
