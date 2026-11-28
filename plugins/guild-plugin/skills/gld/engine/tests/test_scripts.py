"""Plugin check scripts (U15): ac-format, ac-coverage, verify-gate — the §2.7 contract.

Real subprocesses (`python3 -I script --issue N`, cwd = a temp tree) and real git; the gate
is the plugin's own gate_precommit.py. Never a paid call, never the user's git config."""

import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from tests.helpers.gitrepo import GitRepo, git_env

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
SCRIPTS = os.path.join(ENGINE, "scripts")
FIX = os.path.join(HERE, "fixtures", "ac")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def run_script(name, cwd, *args, env=None):
    p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, name), *args], cwd=cwd, env=env,
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout.splitlines(), p.stderr


def snapshot(root):
    """{relpath: (kind, size, mtime_ns)} of everything below root — to prove nothing was written."""
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            st = os.lstat(p)
            out[os.path.relpath(p, root)] = (st.st_mode, st.st_size, st.st_mtime_ns)
    return out


class SpecTree(unittest.TestCase):
    ISSUE = 7

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.specs = os.path.join(self.root, "docs", "specs", str(self.ISSUE))
        os.makedirs(self.specs)

    def put(self, name, text):
        with open(os.path.join(self.specs, name), "w", encoding="utf-8") as f:
            f.write(text)

    def run_check(self, script, *args):
        before = snapshot(self.root)
        got = run_script(script, self.root, "--issue", str(self.ISSUE), *args)
        self.assertEqual(snapshot(self.root), before, "a check script wrote something")
        return got


class AcFormat(SpecTree):
    def test_pass(self):
        self.put("analysis.md", fixture("analysis-ok.md"))
        rc, out, err = self.run_check("ac_format.py")
        self.assertEqual((rc, err), (0, ""), out)
        self.assertTrue(out[0].startswith("ok: 4 AC(s)"))

    def test_stage_3_needs_safety_net(self):
        """E3: the engine passes `--stage 3`; without it the field is not looked at (E36)."""
        text = fixture("analysis-ok.md")
        self.put("analysis.md", text)
        self.assertEqual(self.run_check("ac_format.py", "--stage", "2")[0], 0)
        rc, out, _ = self.run_check("ac_format.py", "--stage", "3")
        self.assertEqual(rc, 1)
        self.assertIn("safety_net", out[0])
        self.put("analysis.md", text.replace("type: feature\n", "type: feature\nsafety_net: none\n"))
        self.assertEqual(self.run_check("ac_format.py", "--stage", "3")[0], 0)
        self.put("analysis.md", text.replace("type: feature\n", "type: feature\nsafety_net: only\n"))     # TY5
        rc, out, _ = self.run_check("ac_format.py", "--stage", "3")
        self.assertEqual((rc, len(out)), (1, 1))
        self.assertIn("needs type: refactor", out[0])
        self.assertEqual(self.run_check("ac_format.py")[0], 0)

    def test_deferred_rows(self):
        """E30 (TS1, TS3) through the script."""
        text = fixture("analysis-ok.md").replace("type: feature\n", "type: feature\nsafety_net: none\n")
        self.put("analysis.md", text + "\n## 미룬 요구\n\n- Export as CSV (deferred R3)\n- Print (deferred R5)\n")
        self.assertEqual(self.run_check("ac_format.py", "--stage", "3", "--deferred", "R3,R5")[0], 0)
        for args in (("--stage", "3"), ("--stage", "3", "--deferred", "R3"), ("--stage", "3", "--deferred", "R3,R5,R6")):
            with self.subTest(args=args):
                rc, out, _ = self.run_check("ac_format.py", *args)
                self.assertEqual(rc, 1)
                self.assertIn("deferred", out[0])
        self.assertEqual(self.run_check("ac_format.py")[0], 0, "stage 2 does not look at the section")

    def test_missing_file_fails(self):
        rc, out, _ = self.run_check("ac_format.py")
        self.assertEqual(rc, 1)
        self.assertEqual(out, ["docs/specs/7/analysis.md not found"])

    def test_malformed_ac_fails_with_the_line(self):
        self.put("analysis.md", fixture("analysis-ok.md").replace("- AC #2:", "- AC #2 is"))
        rc, out, _ = self.run_check("ac_format.py")
        self.assertEqual(rc, 1)
        self.assertRegex(out[0], r"^docs/specs/7/analysis\.md:\d+: line starts with an AC token")

    def test_gap_and_unmapped_requirement_fail_one_reason_per_line(self):
        text = fixture("analysis-ok.md").replace("- AC #3:", "- AC #5:").replace("AC #2, #3", "none")
        self.put("analysis.md", text)
        rc, out, _ = self.run_check("ac_format.py")
        self.assertEqual(rc, 1)
        self.assertGreaterEqual(len(out), 2)
        self.assertTrue(any("without gaps" in ln for ln in out))
        self.assertTrue(any("without an AC" in ln for ln in out))

    def test_symlinked_analysis_cannot_be_judged(self):
        outside = os.path.join(self.root, "outside.md")
        with open(outside, "w") as f:
            f.write(fixture("analysis-ok.md"))
        os.symlink(outside, os.path.join(self.specs, "analysis.md"))
        rc, out, _ = self.run_check("ac_format.py")
        self.assertEqual(rc, 2)
        self.assertIn("symbolic link", out[0])

    def test_bad_arguments(self):
        for args in ([], ["--issue"], ["--issue", "x"], ["--issue", "0"], ["--issue", "7", "--x"], ["7"],
                     ["--stage", "3"], ["--issue", "7", "--stage"], ["--issue", "7", "--stage", "0"],
                     ["--issue", "7", "--stage", "x"], ["--issue", "7", "--issue", "8"], ["--issue", "7", "--x", "1"],
                     ["--issue", "7", "--stage", "3", "--stage", "3"], ["--issue", "7", "--deferred", "R3"],
                     ["--issue", "7", "--stage", "2", "--deferred", "R3"], ["--issue", "7", "--stage", "3", "--deferred", ""],
                     ["--issue", "7", "--stage", "3", "--deferred", "R3,R3"], ["--issue", "7", "--stage", "3", "--deferred", "3"],
                     ["--issue", "7", "--stage", "3", "--deferred", "R3, R5"]):
            with self.subTest(args=args):
                rc, out, err = run_script("ac_format.py", self.root, *args)
                self.assertEqual((rc, out), (2, []))
                self.assertIn("usage", err)


class AcCoverage(SpecTree):
    def setUp(self):
        super().setUp()
        self.put("analysis.md", fixture("analysis-ok.md"))

    def test_pass(self):
        self.put("test-cases.md", fixture("test-cases-ok.md"))
        rc, out, err = self.run_check("ac_coverage.py")
        self.assertEqual((rc, err), (0, ""), out)
        self.assertEqual(out, ["ok: all 4 AC(s) are referenced"])

    def test_uncovered_ac_fails(self):
        self.put("test-cases.md", fixture("test-cases-ok.md").replace("(AC #3, #4)", "(AC #4)")
                 .replace("| C5 | AC #3 |", "| C5 | — |").replace("| C6 | AC #3 |", "| C6 | — |"))
        rc, out, _ = self.run_check("ac_coverage.py")
        self.assertEqual(rc, 1)
        self.assertEqual(out, ["AC #3: not referenced in docs/specs/7/test-cases.md"])

    def test_unknown_reference_fails(self):
        self.put("test-cases.md", fixture("test-cases-ok.md") + "\n- C8 [AC #12]: a stray reference\n")
        rc, out, _ = self.run_check("ac_coverage.py")
        self.assertEqual(rc, 1)
        self.assertEqual(out, ["docs/specs/7/test-cases.md references AC #12, which analysis.md does not define"])

    def test_unparseable_token_fails_closed(self):
        self.put("test-cases.md", fixture("test-cases-ok.md") + "\n- C8 [AC #1-3]: a range\n")
        rc, out, _ = self.run_check("ac_coverage.py")
        self.assertEqual(rc, 1)
        self.assertRegex(out[0], r"test-cases\.md:\d+: unparseable AC token")

    def test_miss_cases_through_the_script(self):
        """S13 end to end: bracket tag (0.102.10) and heading list (0.102.11) cover their ACs."""
        self.put("test-cases.md", "### Row and sheet (AC #1, #2)\n- E4 [AC #3] summary\n- E5 [AC #4] restart\n")
        rc, out, _ = self.run_check("ac_coverage.py")
        self.assertEqual((rc, out), (0, ["ok: all 4 AC(s) are referenced"]))

    def test_written_paren_form_passes(self):
        """P5: the parenthesised form the role and task texts now prescribe."""
        self.put("analysis.md", fixture("analysis-paren.md"))
        self.put("test-cases.md", fixture("test-cases-paren.md"))
        self.assertEqual(self.run_check("ac_format.py")[:2], (0, ["ok: 4 AC(s), type feature, risk low"]))
        self.assertEqual(self.run_check("ac_coverage.py")[:2], (0, ["ok: all 4 AC(s) are referenced"]))

    def test_prose_mention_only_fails_with_a_hint(self):
        """An AC named only inside a sentence is not covered; the reason says how to tag it."""
        self.put("test-cases.md", "## Cases (AC #1, #2)\n\n- C3: the summary updates (AC #3 의 정의대로).\n"
                                  "- C4: restart keeps it. (AC #4)\n")
        rc, out, _ = self.run_check("ac_coverage.py")
        self.assertEqual(rc, 1)
        self.assertEqual(out, ["AC #3: not referenced in docs/specs/7/test-cases.md (line 3 mentions it in "
                               "prose, which does not count — end the case's line with the tag `(AC #3)`)"])

    def test_missing_test_cases_fails(self):
        rc, out, _ = self.run_check("ac_coverage.py")
        self.assertEqual((rc, out), (1, ["docs/specs/7/test-cases.md not found"]))

    def test_bad_analysis_fails_with_its_reason(self):
        self.put("analysis.md", "nothing useful\n")
        self.put("test-cases.md", fixture("test-cases-ok.md"))
        rc, out, _ = self.run_check("ac_coverage.py")
        self.assertEqual(rc, 1)
        self.assertIn("docs/specs/7/analysis.md", out[0])

    def test_directory_instead_of_file_cannot_be_judged(self):
        os.makedirs(os.path.join(self.specs, "test-cases.md"))
        rc, out, _ = self.run_check("ac_coverage.py")
        self.assertEqual(rc, 2)
        self.assertIn("not a regular file", out[0])


def load_verify_gate():
    spec = importlib.util.spec_from_file_location("verify_gate_under_test", os.path.join(SCRIPTS, "verify_gate.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VerifyGateJudgement(unittest.TestCase):
    """The mapping of the gate's result to the script contract, without running the gate."""

    def setUp(self):
        self.vg = load_verify_gate()

    def test_pass_block_and_other_codes(self):
        self.assertEqual(self.vg.judge(0, "", "warn: x\n"), (0, ["warn: x"]))
        self.assertEqual(self.vg.judge(0, "", ""), (0, ["ok: the gate allowed the range"]))
        self.assertEqual(self.vg.judge(1, "", "blocked: a\nblocked: b\n"), (1, ["blocked: a", "blocked: b"]))
        code, lines = self.vg.judge(1, "", "")
        self.assertEqual(code, 1)
        self.assertIn("no message", lines[0])
        for rc in (2, 64, 137, -9):
            with self.subTest(rc=rc):
                self.assertEqual(self.vg.judge(rc, "", "boom\n")[0], 2)

    def test_timeout_is_not_judged(self):
        self.assertEqual(self.vg.judge(None, "", "")[0], 2)

    def test_the_gates_fail_open_crash_is_not_a_pass(self):
        code, lines = self.vg.judge(0, "", "guild gate: internal error, allowing commit (boom)\n")
        self.assertEqual(code, 2)
        self.assertIn("NOT judged", lines[0])

    def test_missing_gate_and_non_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd, old_gate = os.getcwd(), self.vg.GATE
            os.chdir(tmp)
            try:
                self.vg.GATE = os.path.join(tmp, "nope.py")
                buf = io.StringIO()
                with redirect_stdout(buf):
                    self.assertEqual(self.vg.main(["--issue", "1"]), 2)
                self.assertIn("gate script is missing", buf.getvalue())
                self.vg.GATE = old_gate
                buf = io.StringIO()
                with redirect_stdout(buf):
                    self.assertEqual(self.vg.main(["--issue", "1"]), 2)
                self.assertIn("not a git work tree", buf.getvalue())
            finally:
                self.vg.GATE = old_gate
                os.chdir(old_cwd)

    def test_bad_arguments(self):
        for args in ([], ["--issue"], ["--issue", "x"], ["1"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                self.assertEqual(self.vg.main(args), 2)


class VerifyGateRealGate(unittest.TestCase):
    """The plugin's own gate over base..HEAD in a read-tree temp tree (F5), through the script."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = GitRepo.create(self.tmp.name, files={
            "src/app.py": "def f():\n    return 1\n",
            "tests/test_app.py": "def test_f():\n    assert f() == 1\n    assert f() != 2\n",
        })
        self.base = self.repo.head()
        self.env = git_env(self.tmp.name)

    def temp_tree(self, head):
        """What the engine does outside srt (gitops.temp_tree_for_gate): detached base worktree +
        `read-tree -m -u base head`, so the index / tree show head's content while HEAD stays base."""
        tree = os.path.join(self.tmp.name, "gate-tree")
        self.repo.git("worktree", "add", "--detach", "-q", tree, self.base)
        self.repo.git("read-tree", "-m", "-u", self.base, head, cwd=tree)
        self.assertEqual(self.repo.head(cwd=tree), self.base)
        return tree

    def gate(self, tree):
        return run_script("verify_gate.py", tree, "--issue", "7", env=self.env)

    def test_clean_range_passes(self):
        self.repo.write("src/more.py", "X = 1\n")
        head = self.repo.commit("add a module")
        rc, out, err = self.gate(self.temp_tree(head))
        self.assertEqual(rc, 0, (out, err))

    def test_deleted_test_file_is_blocked(self):
        os.remove(os.path.join(self.repo.path, "tests", "test_app.py"))
        head = self.repo.commit("drop a test")
        rc, out, err = self.gate(self.temp_tree(head))
        self.assertEqual(rc, 1, (out, err))
        self.assertTrue(any("tests/test_app.py" in ln for ln in out), out)

    def test_a_secret_in_the_range_is_blocked(self):
        self.repo.write("deploy/.env", "API_KEY=abc\n")
        head = self.repo.commit("oops")
        rc, out, err = self.gate(self.temp_tree(head))
        self.assertEqual(rc, 1, (out, err))

    def test_range_not_the_working_tree_decides(self):
        """The read-tree tree shows base..head: a violation committed and reverted inside the
        range cancels out (nothing in base..head), exactly as the commit gate would see it."""
        self.repo.write("deploy/.env", "API_KEY=abc\n")
        self.repo.commit("oops")
        os.remove(os.path.join(self.repo.path, "deploy", ".env"))
        head = self.repo.commit("fix")
        rc, out, err = self.gate(self.temp_tree(head))
        self.assertEqual(rc, 0, (out, err))


if __name__ == "__main__":
    unittest.main()
