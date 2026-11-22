"""0.102.14 — the one-man-company #687 offline suite stop and the 0.102.13 integrity-format drift question, through the
real code paths (the offline shims `ports.offline_shims`, `checks.run_command` under sandbox-exec, `suite_in_tree`, the
role runner's drift check). No real flutter, no network: a fake `flutter` / `fvm` records its argv.

Lead decisions (k6-notes "0.102.14"):
1  every OFFLINE suite run (main suite + flake re-runs, effective re-runs, refactor net) gets engine-owned `flutter` /
   `fvm` shims first on PATH, in the run dir (fsafe, denyWrite in the sandbox), exec'ing the real binary resolved at
   prep time (absolute): `test` gets `--no-pub` unless `--no-pub` / `--pub` is there, `pub get` / `pub upgrade` get
   `--offline` unless `--offline` / `--no-offline` is there, everything else unchanged. `offline_cmd` stays (no second
   flag). A wrapper script (`bash tool/hooks/run_tests_judged.sh`) is covered.
2  `dart` is not shimmed (the engine never treated it) — follow-up.
3  the check result carries `offline_shim` ("flutter,fvm"), raw.txt a `shim:` line, the TEST decision `suite_shim`.
4  safety_net classification unchanged.
PWD  a sandboxed check's PWD is its cwd and the engine's own PYENV_DIR / OLDPWD do not reach it (pyenv's `python3`
   shim exported PYENV_DIR = the main checkout, denyRead in the sandbox → `pyenv: cannot change working directory`).
FMT  a drift baseline of another integrity-hash format (or none) whose only late items are the git-config hashes is
   re-taken silently (journal `rebaseline-format`) — word_app #1797 / japanlifeinfo #227 resumed under 0.102.13.
"""

import json
import os
import subprocess
import unittest

import _util  # noqa: F401
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir

from guildcore import checks as CH
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from workflows.dev import ports as PO

MAC = os.path.exists(CH.SANDBOX_EXEC)
DONE = ">>> RESULT <<<\nDONE: ok"

FAKE = """#!/bin/sh
printf '%%s\\n' "$@" > "$TMPDIR/argv-%(name)s"
printf 'PWD=%%s\\nPYENV_DIR=%%s\\n' "$PWD" "${PYENV_DIR-<unset>}" > "$TMPDIR/env-%(name)s"
exit 0
"""


def _w(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, mode)


def _fakebin(case, names=("flutter", "fvm")):
    d = os.path.join(tmpdir(case), "realbin")
    for n in names:
        _w(os.path.join(d, n), FAKE % {"name": n}, 0o755)
    return d


def _run_dir(case):
    rd = tmpdir(case)
    for d in ("in", "out", "tmp"):
        os.makedirs(os.path.join(rd, d), exist_ok=True)
    return rd


def _argv(rd, name="flutter"):
    p = os.path.join(rd, "tmp", "argv-%s" % name)
    if not os.path.exists(p):
        return None
    return open(p, encoding="utf-8").read().splitlines()


class ShimRun(unittest.TestCase):
    """The shims as the suite sandbox runs them: `run_command` under sandbox-exec, the env from `offline_shims`."""

    def _run(self, cmd, names=("flutter", "fvm"), env_extra=None, sandbox_fs=None):
        rd = _run_dir(self)
        tree = tmpdir(self)
        _w(os.path.join(tree, "run.sh"), "#!/usr/bin/env bash\nset -u\n%s\n" % cmd, 0o755)
        env = {"PATH": _fakebin(self, names) + os.pathsep + "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/")}
        env.update(env_extra or {})
        env2, shim = PO.offline_shims(rd, env)
        r = CH.run_command(["bash run.sh"], 60, cwd=tree, env=env2,
                           sandbox={"filesystem": dict({"allowWrite": []}, **(sandbox_fs or {}))},
                           tmp=os.path.join(rd, "tmp"))
        return r, rd, tree, shim

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_a_wrapper_script_flutter_test_gets_no_pub(self):
        r, rd, _t, shim = self._run('flutter test --concurrency=8 --file-reporter "json:$TMPDIR/rep.json"')
        self.assertTrue(r.passed, r.raw)
        self.assertEqual(shim, "flutter,fvm")
        a = _argv(rd)
        self.assertEqual(a[:3], ["test", "--no-pub", "--concurrency=8"], a)
        self.assertEqual(a.count("--no-pub"), 1)

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_no_second_flag(self):
        for cmd, want in (("flutter test --no-pub test/a_test.dart", ["test", "--no-pub", "test/a_test.dart"]),
                          ("flutter test --pub test/a_test.dart", ["test", "--pub", "test/a_test.dart"]),
                          (PO.offline_cmd("flutter test test/a_test.dart"), ["test", "--no-pub", "test/a_test.dart"])):
            with self.subTest(cmd=cmd):
                r, rd, _t, _s = self._run(cmd)
                self.assertTrue(r.passed, r.raw)
                self.assertEqual(_argv(rd), want)

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_pub_get_and_upgrade_get_offline(self):
        for cmd, want in (("flutter pub get", ["pub", "get", "--offline"]),
                          ("flutter pub upgrade --major-versions", ["pub", "upgrade", "--offline", "--major-versions"]),
                          ("flutter pub get --offline", ["pub", "get", "--offline"]),
                          ("flutter pub get --no-offline", ["pub", "get", "--no-offline"]),
                          ("flutter --suppress-analytics test x_test.dart",
                           ["--suppress-analytics", "test", "--no-pub", "x_test.dart"])):
            with self.subTest(cmd=cmd):
                r, rd, _t, _s = self._run(cmd)
                self.assertTrue(r.passed, r.raw)
                self.assertEqual(_argv(rd), want)

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_other_subcommands_pass_through_unchanged(self):
        for cmd, want in (("flutter analyze --no-fatal-infos", ["analyze", "--no-fatal-infos"]),
                          ("flutter --version", ["--version"]),
                          ("flutter pub deps --style=compact", ["pub", "deps", "--style=compact"]),
                          ("flutter gen-l10n", ["gen-l10n"]),
                          ("flutter 'a b' test", ["a b", "test"])):
            with self.subTest(cmd=cmd):
                r, rd, _t, _s = self._run(cmd)
                self.assertTrue(r.passed, r.raw)
                self.assertEqual(_argv(rd), want)

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_fvm_flutter_is_rewritten_and_other_fvm_commands_are_not(self):
        for cmd, want in (("fvm flutter test --concurrency=4", ["flutter", "test", "--no-pub", "--concurrency=4"]),
                          ("fvm flutter pub get", ["flutter", "pub", "get", "--offline"]),
                          ("fvm flutter test --no-pub", ["flutter", "test", "--no-pub"]),
                          ("fvm list", ["list"]),
                          ("fvm dart test", ["dart", "test"])):
            with self.subTest(cmd=cmd):
                r, rd, _t, _s = self._run(cmd)
                self.assertTrue(r.passed, r.raw)
                self.assertEqual(_argv(rd, "fvm"), want)

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_pwd_is_the_tree_and_the_engines_pyenv_dir_does_not_reach_the_check(self):
        main = tmpdir(self)                                   # the main checkout the engine was started in (denyRead)
        r, rd, tree, _s = self._run(
            'flutter test\n[ -d "${PYENV_DIR:-$PWD}" ] || { echo "pyenv: cannot change working directory"; exit 3; }',
            env_extra={"PWD": main, "PYENV_DIR": main, "OLDPWD": main},
            sandbox_fs={"denyRead": [os.path.realpath(main) + "/**"]})
        self.assertTrue(r.passed, r.raw)
        env = dict(x.split("=", 1) for x in open(os.path.join(rd, "tmp", "env-flutter")).read().splitlines())
        self.assertEqual(os.path.realpath(env["PWD"]), os.path.realpath(tree))
        self.assertEqual(env["PYENV_DIR"], "<unset>")

    def test_real_binaries_are_absolute_and_the_shim_is_engine_written(self):
        rd = _run_dir(self)
        fb = _fakebin(self, ("flutter",))
        env, shim = PO.offline_shims(rd, {"PATH": fb + ":/usr/bin:/bin"})
        self.assertEqual(shim, "flutter")
        sdir = os.path.join(rd, PO.SHIM_DIR)
        self.assertTrue(env["PATH"].startswith(sdir + os.pathsep))
        text = open(os.path.join(sdir, "flutter")).read()
        self.assertIn("REAL='%s'\n" % os.path.join(os.path.abspath(fb), "flutter"), text)
        self.assertTrue(os.access(os.path.join(sdir, "flutter"), os.X_OK))
        # a second preparation in the same run dir never resolves to its own shim
        env2, _ = PO.offline_shims(rd, env)
        self.assertNotIn(PO.SHIM_DIR, open(os.path.join(sdir, "flutter")).read().split("REAL=")[1].split("\n")[0])
        self.assertEqual(env2["PATH"].split(os.pathsep).count(sdir), 1)

    def test_no_flutter_on_path_no_shim(self):
        rd = _run_dir(self)
        env, shim = PO.offline_shims(rd, {"PATH": "/usr/bin:/bin"})
        self.assertIsNone(shim)
        self.assertEqual(env["PATH"], "/usr/bin:/bin")
        self.assertFalse(os.path.exists(os.path.join(rd, PO.SHIM_DIR)))

    def test_a_link_planted_at_the_shim_dir_is_refused(self):
        rd = _run_dir(self)
        os.symlink(tmpdir(self), os.path.join(rd, PO.SHIM_DIR))
        from guildcore import fsafe as FS
        with self.assertRaises(FS.UnsafePath):
            PO.offline_shims(rd, {"PATH": _fakebin(self, ("flutter",)) + ":/usr/bin:/bin"})


class SuiteInTree(unittest.TestCase):
    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_r687_wrapper_suite_gets_no_pub_and_records_the_shim(self):
        wrapper = "#!/usr/bin/env bash\nset -u\nflutter test --concurrency=8 --file-reporter \"json:$(mktemp)\"\n"
        r = repo(self, {"tool/hooks/run_tests_judged.sh": wrapper})
        run_dir = _run_dir(self)
        env = dict(os.environ, PATH=_fakebin(self) + os.pathsep + os.environ["PATH"], PYENV_DIR=r, PWD=r)
        res = PO.suite_in_tree(r, None, ["bash tool/hooks/run_tests_judged.sh"], "developer", 60, run_dir, env,
                               warm=False)
        self.assertTrue(res.passed, res.raw)
        self.assertEqual(res.offline_shim, "flutter,fvm")
        a = _argv(run_dir)
        self.assertEqual(a[:3], ["test", "--no-pub", "--concurrency=8"])
        env_seen = open(os.path.join(run_dir, "tmp", "env-flutter")).read()
        self.assertNotIn("PWD=%s\n" % r, env_seen)
        self.assertIn("PYENV_DIR=<unset>", env_seen)
        PO.keep_raw(run_dir, ["bash tool/hooks/run_tests_judged.sh"], res)
        raw = open(os.path.join(run_dir, "out", "raw.txt")).read()
        self.assertIn("\nshim: flutter,fvm\nrc: 0", raw)

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_the_suite_cannot_rewrite_the_shim(self):
        r = repo(self, {"t.sh": "echo 'exit 0' > \"$1\" && echo WROTE\n"})
        run_dir = _run_dir(self)
        env = dict(os.environ, PATH=_fakebin(self) + os.pathsep + os.environ["PATH"])
        shim = os.path.join(run_dir, PO.SHIM_DIR, "flutter")
        res = PO.suite_in_tree(r, None, ["sh t.sh %s" % shim], "developer", 60, run_dir, env, warm=False)
        self.assertNotIn("WROTE", res.raw)
        self.assertIn("--no-pub", open(shim).read())

    def test_the_tree_sandbox_denies_writes_to_the_shim_dir(self):
        r = repo(self, {"a.txt": "a\n"})
        rd = _run_dir(self)
        sb = PO.tree_sandbox(tmpdir(self), rd, r)
        self.assertIn(os.path.join(os.path.abspath(rd), PO.SHIM_DIR) + "/**", sb["filesystem"]["denyWrite"])

    def test_every_offline_suite_path_uses_the_shims(self):
        src = open(PO.__file__, encoding="utf-8").read()
        for fn, nxt in (("def suite_in_tree(", "\n# K3 (K2r6-m4)"), ("def net_in_tree(", "def net_env("),
                        ("    def _tree_run(", "    def _copy_list(")):
            body = src[src.index(fn):src.index(nxt, src.index(fn))]
            self.assertIn("offline_shims(", body, fn)

    def test_the_networked_warm_up_has_no_shim(self):
        src = open(PO.__file__, encoding="utf-8").read()
        body = src[src.index("def warm_in_place("):src.index("def safety_net(")]
        self.assertNotIn("offline_shims(", body)


class FormatDrift(unittest.TestCase):
    """FMT: a baseline written by an older engine (another integrity hash format) — no drift question."""

    def _runner(self, j=None):
        return RR.Runner(journal=j or EvJournal(), parent_env={"PATH": os.environ["PATH"]},
                         spawn=FakeSpawn([{"stream": stream_lines(texts=[DONE])}] * 3),
                         user_settings=os.path.join(self.u, "u"), run_root_dir=os.path.join(self.u, "runs"),
                         claude="claude", clock=Clock())

    def setUp(self):
        self.wt = repo(self, {"lib/a.dart": "a\n"})
        git(self.wt, "switch", "-q", "-c", "fix/1")
        self.u = tmpdir(self)
        r = self._runner()
        spec = RR.RoleSpec("developer", "implement", "t", issue=1, stage="s", step="x", worktree=self.wt,
                           model="sonnet", base="main", branch="fix/1", remote_check=False)
        self.assertEqual(r.run_role(spec).status, "DONE")
        self.path = r._baseline_path(self.wt, 1)

    def _age(self, fmt=None, config=True):
        """The stored baseline as an older engine wrote it: no (or another) format, other config hashes."""
        b = json.load(open(self.path))
        b.pop("integrity_format", None)
        if fmt is not None:
            b["integrity_format"] = fmt
        if config:
            for k in b["integrity"]:
                if k.startswith(("git config --local", "config file ")):
                    b["integrity"][k] = "0" * 40
        json.dump(b, open(self.path, "w"))

    def test_r1797_old_format_baseline_no_drift_question(self):
        self.assertEqual(json.load(open(self.path)).get("integrity_format"), SC.INTEGRITY_FORMAT)
        self._age()
        j = EvJournal()
        r = self._runner(j)                                   # a resume: a new engine process reads the file
        self.assertEqual(r.drift_check(self.wt, 1, "fix/1", "main"), [])
        ev = [e for e in j.events if e.get("what") == "rebaseline-format"]
        self.assertEqual(len(ev), 1)
        self.assertTrue(all(x.startswith(("git config ", "config file ")) for x in ev[0]["items"]))
        self.assertEqual(json.load(open(self.path)).get("integrity_format"), SC.INTEGRITY_FORMAT)
        self.assertEqual(self._runner().drift_check(self.wt, 1, "fix/1", "main"), [])

    def test_another_format_number_is_handled_the_same(self):
        self._age(fmt=1)
        self.assertEqual(self._runner().drift_check(self.wt, 1, "fix/1", "main"), [])

    def test_something_else_late_is_still_asked_with_the_config_items(self):
        self._age()
        with open(os.path.join(self.wt, "lib/a.dart"), "w") as fh:
            fh.write("a person's edit\n")
        late = self._runner().drift_check(self.wt, 1, "fix/1", "main")
        self.assertIn("path lib/a.dart", late)
        self.assertTrue(any(x.startswith("git config --local") for x in late))

    def test_a_current_format_baseline_still_reports_a_config_change(self):
        git(self.wt, "config", "core.hooksPath", "/tmp/evil-hooks")
        late = self._runner().drift_check(self.wt, 1, "fix/1", "main")
        self.assertTrue(any(x.startswith("git config --local") for x in late), late)

    def test_snapshots_carry_the_format(self):
        self.assertEqual(SC.snapshot(self.wt).get("integrity_format"), SC.INTEGRITY_FORMAT)


class EvJournal(RecJournal):
    def __init__(self):
        RecJournal.__init__(self)
        self.events = []

    def append(self, kind, **f):
        self.events.append(dict(f, kind=kind))


if __name__ == "__main__":
    unittest.main()
