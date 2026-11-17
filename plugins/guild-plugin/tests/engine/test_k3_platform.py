"""K3 — the platform carry-overs: the gate reads its config (off-switch) from <base>; PGP keys in the
live gate; engine commit/push hooks off; production worktrees outside $TMPDIR with copy_ignored; the
networked steps' read allowlist (copy_ignored originals denied); build*.yaml under build_runner; the
forgery-proof loading-phase detector (flutter's machine report); branch rules (J-B1..B4, D-0.5)."""

import importlib.util
import json
import os
import subprocess
import unittest

import _util
from _k1 import git, repo, tmpdir

from guildcore import checks as CH
from guildcore.adapters import git as G
from guildcore.records import markers
from guildcore.records import redact as RD
from guildcore.roles import settings as S
from workflows.dev import branching as BR
from workflows.dev import effective as EFF
from workflows.dev import ports as PO
from workflows.dev import preflight as PF
from workflows.dev import variants as VR

GATE = os.path.join(_util.SKILL, "gates", "gate_precommit.py")
PGP = "-----BEGIN PGP PRIVATE KEY BLOCK-----\nlQOYBF1...\n-----END PGP PRIVATE KEY BLOCK-----"


def gate_module():
    spec = importlib.util.spec_from_file_location("_gate_k3", GATE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class GateConfigFromBase(unittest.TestCase):
    def test_env_config_wins_over_the_checkout(self):
        g = gate_module()
        r = repo(self, {".claude/guild/config.json": json.dumps({"gates": {"enabled": False}})})
        base_cfg = os.path.join(tmpdir(self), "cfg.json")
        with open(base_cfg, "w") as fh:
            json.dump({"gates": {"enabled": True}}, fh)
        old = os.environ.pop("GUILD_GATE_CONFIG", None)
        try:
            self.assertFalse(g.gates_enabled(r))
            os.environ["GUILD_GATE_CONFIG"] = base_cfg
            self.assertTrue(g.gates_enabled(r))
            os.environ["GUILD_GATE_CONFIG"] = "relative/ignored.json"
            self.assertFalse(g.gates_enabled(r))
        finally:
            os.environ.pop("GUILD_GATE_CONFIG", None)
            if old is not None:
                os.environ["GUILD_GATE_CONFIG"] = old

    def test_export_carries_the_base_config_and_hooks_are_prefixed(self):
        r = repo(self, {".claude/guild/gates/scripts/gate_precommit.py": "print('x')\n",
                        ".claude/guild/config.json": json.dumps({"gates": {"enabled": True}})})
        base = git(r, "rev-parse", "HEAD")
        git(r, "switch", "-q", "-c", "feat")
        with open(os.path.join(r, ".claude/guild/config.json"), "w") as fh:
            json.dump({"gates": {"enabled": False}}, fh)
        dest = os.path.join(tmpdir(self), "g")
        self.assertTrue(S.export_gates(r, base, dest))
        with open(os.path.join(dest, ".config.json")) as fh:
            self.assertEqual(json.load(fh)["gates"]["enabled"], True)
        hooks = {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 \"%s/scripts/gate_precommit.py\"" % dest},
            {"type": "command", "command": "echo unrelated"}]}]}
        out = S.with_gate_config(hooks, dest)
        cmds = [h["command"] for h in out["PreToolUse"][0]["hooks"]]
        self.assertTrue(cmds[0].startswith("GUILD_GATE_CONFIG='%s/.config.json' python3" % dest))
        self.assertEqual(cmds[1], "echo unrelated")


class PgpKeys(unittest.TestCase):
    def test_gate_and_redaction_catch_pgp(self):
        g = gate_module()
        self.assertTrue(any(rx.search(PGP) for rx in g.INLINE_SECRET_RES))
        self.assertTrue(RD.has_secret(PGP))
        self.assertEqual(markers.value("key: " + PGP), RD.REPLACEMENT)
        p = subprocess.run(["python3", GATE, "--scan-text", "--stdin"], input=("x\n" + PGP + "\n").encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertIn(b"SECRET-TEXT 2", p.stdout)


class EngineGitHooksOff(unittest.TestCase):
    def test_push_runs_no_hook(self):
        remote = tmpdir(self)
        git(remote, "init", "-q", "--bare")
        r = repo(self, {"a.txt": "a", ".githooks/pre-push": "#!/bin/sh\necho ran > hook-ran.txt\nexit 1\n"})
        os.chmod(os.path.join(r, ".githooks/pre-push"), 0o755)
        git(r, "config", "core.hooksPath", ".githooks")
        G.push(r, remote, "refs/heads/main:refs/heads/main")
        self.assertFalse(os.path.exists(os.path.join(r, "hook-ran.txt")))
        self.assertEqual(git(remote, "rev-parse", "main"), git(r, "rev-parse", "HEAD"))

    def test_push_refuses_a_remote_name(self):
        r = repo(self)
        git(r, "remote", "add", "origin", "/x")
        with self.assertRaises(G.GitError):
            G.push(r, "origin", "refs/heads/main:refs/heads/main")


class Worktrees(unittest.TestCase):
    def test_outside_tmpdir_only(self):
        with self.assertRaises(BR.BranchProblem):
            BR.assert_outside_tmp(os.path.join(os.environ.get("TMPDIR", "/tmp"), "x", ".gld-r-7"))
        with self.assertRaises(BR.BranchProblem):
            BR.assert_outside_tmp("/private/tmp/.gld-r-7")
        BR.assert_outside_tmp(os.path.expanduser("~/projects/.gld-r-7"))

    def test_prepare_copies_listed_ignored_files_only(self):
        r = repo(self, {".gitignore": "lib/env/\nsecret.txt\n", "lib/a.dart": "a"})
        os.makedirs(os.path.join(r, "lib/env"))
        for rel, t in (("lib/env/env.dart", "const k = 'x';"), ("secret.txt", "s"), ("lib/a.dart", "a")):
            with open(os.path.join(r, rel), "w") as fh:
                fh.write(t)
        os.symlink(os.path.join(r, "secret.txt"), os.path.join(r, "lib/env/link.dart"))
        dest = os.path.join(tmpdir(self), "wt")
        BR.TMP_ROOTS = ()                       # the test's temp root stands in for ~/projects
        try:
            old = os.environ.pop("TMPDIR", None)
            got = BR.prepare(r, dest, "feature/#7-x", "main", True,
                             ["lib/env/env.dart", "lib/a.dart", "../x", "lib/*.dart", "lib/env/link.dart"])
        finally:
            BR.TMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
            if old is not None:
                os.environ["TMPDIR"] = old
        self.assertEqual(got["copied"], ["lib/env/env.dart"])
        self.assertEqual(sorted(got["refused"]), sorted(["lib/a.dart", "../x", "lib/*.dart", "lib/env/link.dart"]))
        self.assertTrue(os.path.exists(os.path.join(dest, "lib/env/env.dart")))
        self.assertEqual(git(dest, "rev-parse", "--abbrev-ref", "HEAD"), "feature/#7-x")
        self.assertFalse(os.path.exists(os.path.join(dest, "secret.txt")))


class Branches(unittest.TestCase):
    def test_name_template_keeps_the_issue_token(self):
        self.assertEqual(VR.branch_name("debug", 7, "Fix: the Crash!"), "fix/#7-fix-the-crash")
        self.assertEqual(VR.branch_name("implement", 7, "x", "{prefix}{slug}"), "feature/#7-x")

    def test_candidates_and_decide(self):
        r = repo(self)
        for b in ("feature/#7-a", "fix/17-b", "release/7.1", "feature/#7-empty"):
            git(r, "branch", b)
        git(r, "switch", "-q", "feature/#7-a")
        with open(os.path.join(r, "x"), "w") as fh:
            fh.write("x")
        git(r, "add", "x")
        git(r, "commit", "-qm", "work")
        git(r, "switch", "-q", "main")
        self.assertEqual(BR.candidates(r, 7, "main", "main", lambda b, log: "related"), ["feature/#7-a"])
        self.assertEqual(BR.candidates(r, 7, "main", "main", lambda b, log: "unrelated"), [])
        self.assertEqual(BR.decide(["a", "b"], "b", None), "b")
        with self.assertRaises(BR.BranchProblem):
            BR.decide(["a", "b"], None, None)

    def test_injected_base(self):
        r = repo(self)
        git(r, "branch", "feature/#12-lower")
        git(r, "branch", "release/1.2")
        self.assertEqual(BR.resolve_base(r, "feature/#12-lower", "origin/main", 7), "feature/#12-lower")
        for bad in ("release/1.2", "nope", "main"):
            with self.assertRaises(BR.BranchProblem):
                BR.resolve_base(r, bad, "origin/main", 7)
        with self.assertRaises(BR.BranchProblem):
            BR.resolve_base(r, None, None, 7)


class ReadAllowlist(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(CH.SANDBOX_EXEC), "no sandbox-exec")
    def test_deps_sandbox_reads_tree_not_originals_or_elsewhere(self):
        tree = repo(self, {".gitignore": "lib/env/\n", "lib/a.dart": "tree-ok\n"})
        os.makedirs(os.path.join(tree, "lib/env"))
        with open(os.path.join(tree, "lib/env/env.dart"), "w") as fh:
            fh.write("SECRET\n")
        outside = os.path.join(tmpdir(self), "elsewhere.txt")
        with open(outside, "w") as fh:
            fh.write("ELSEWHERE\n")
        run = tmpdir(self)
        sb = PO.deps_sandbox(tree, run, tree, ["lib/env/env.dart"], 7)
        tmp = os.path.join(run, "tmp")
        r = CH.run_command(["cat lib/a.dart"], 60, cwd=tree, sandbox=sb, tmp=tmp)
        self.assertEqual((r.passed, r.raw.strip()), (True, "tree-ok"))
        r = CH.run_command(["cat lib/env/env.dart"], 60, cwd=tree, sandbox=sb, tmp=tmp)
        self.assertFalse(r.passed)
        self.assertNotIn("SECRET", r.raw)
        r = CH.run_command(["cat %s" % outside], 60, cwd=tree, sandbox=sb, tmp=tmp)
        self.assertFalse(r.passed)
        self.assertNotIn("ELSEWHERE", r.raw)

    def test_profile_order(self):
        tree = repo(self)
        run = tmpdir(self)
        prof = CH.sandbox_profile(PO.deps_sandbox(tree, run, tree, ["lib/env/env.dart"], 7))
        i_deny = prof.index('(deny file-read* (subpath "/Users"))')
        i_allow = prof.index('(allow file-read* (subpath "%s"))' % os.path.realpath(tree))
        i_orig = prof.rindex("lib/env/env.dart")
        self.assertLess(i_deny, i_allow)
        self.assertLess(i_allow, i_orig)


class BuildRunner(unittest.TestCase):
    def test_build_yaml_is_a_build_input_only_under_build_runner(self):
        r = repo(self, {"pubspec.yaml": "name: x\n", "build.yaml": "a: 1\n"})
        git(r, "switch", "-q", "-c", "feat")
        with open(os.path.join(r, "build.yaml"), "w") as fh:
            fh.write("a: 2\n")
        git(r, "commit", "-qam", "b")
        self.assertEqual(EFF.build_inputs(r, "main"), ("none", []))
        self.assertEqual(EFF.build_inputs(r, "main", build_runner=True), ("other", ["build.yaml"]))
        self.assertTrue(EFF.uses_build_runner(["dart run build_runner build && flutter test"]))
        self.assertFalse(EFF.uses_build_runner("flutter test"))


class LoadPhaseFromReport(unittest.TestCase):
    """K2r8-m1: a test body that prints a fake `loading … [E]` + a dependency signature no longer
    halts — the machine report decides; a real loader error still does."""
    FAKE_STDOUT = ("00:00 +0: loading /t/test/a_test.dart\n00:01 +0: a\n00:01 +0 -1: loading /t/test/x [E]\n"
                   "  Failed host lookup: 'pub.dev'\n00:02 +0 -1: Some tests failed.\n")
    REPORT_BODY = "\n".join(json.dumps(e) for e in [
        {"type": "testStart", "test": {"id": 1, "name": "loading /t/test/a_test.dart", "line": None, "url": None}},
        {"type": "testDone", "testID": 1, "result": "success"},
        {"type": "testStart", "test": {"id": 3, "name": "loading /t/test/x", "line": 4, "url": "file:///t/test/a_test.dart"}},
        {"type": "error", "testID": 3, "error": "Failed host lookup: 'pub.dev'", "stackTrace": ""}])
    REPORT_LOAD = "\n".join(json.dumps(e) for e in [
        {"type": "testStart", "test": {"id": 1, "name": "loading /t/test/a_test.dart", "line": None, "url": None}},
        {"type": "error", "testID": 1, "error": "Building native assets failed. Failed host lookup: 'github.com'",
         "stackTrace": ""}])

    def test_text_heuristic_was_fooled(self):
        self.assertTrue(PF.dependency_failure(self.FAKE_STDOUT, 1, load_only=True))

    def test_report_is_not(self):
        self.assertFalse(PF.dependency_failure(self.FAKE_STDOUT, 1, load_only=True, report=self.REPORT_BODY))
        self.assertTrue(PF.dependency_failure("", 1, load_only=True, report=self.REPORT_LOAD))
        self.assertIsNone(PF.json_load_errors(None))

    def test_missing_report_counts_only_pre_test_text(self):
        # a test deleted/never got its report: the forgeable `loading … [E]` blocks no longer count …
        self.assertFalse(PF.dependency_failure(self.FAKE_STDOUT, 1, load_only=True, expect_report=True))
        # … but a tool failure before any test ran still does (measured shape, K3 m3: sqlite3 hook offline)
        real = ("Running build hooks...\nSocketException: Failed host lookup: 'github.com'\n"
                "Building native assets failed. See the logs for more details.\n")
        self.assertTrue(PF.dependency_failure(real, 1, load_only=True, expect_report=True))

    def test_flutter_commands_get_the_machine_reporter(self):
        self.assertEqual(PO.with_json_report("fvm flutter test --no-pub", "/r/x.jsonl"),
                         "fvm flutter test --file-reporter json:/r/x.jsonl --no-pub")
        self.assertEqual(PO.with_json_report("npm test", "/r/x.jsonl"), "npm test")


if __name__ == "__main__":
    unittest.main()
