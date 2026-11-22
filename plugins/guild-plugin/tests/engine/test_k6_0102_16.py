"""0.102.16 — one-man-company #687 on 0.102.14: the suite was red with 21 env-only failures in test/tool/* (the temp
tree had no `.git`; test helpers that strip every GIT_* spawned git without the engine's GIT_CONFIG_GLOBAL under a
sandbox that denies ~/.gitconfig → `fatal: unable to access '~/.gitconfig': Operation not permitted`, rc 128), the
developer was sent back twice and the execute cap stopped the run ("suite red"). Plus two japanlifeinfo #227 stops on
0.102.15 the lead added (`.git/info/refs` read as drift; a list-valued `commands.e2e` crashing the test render).
No network, no paid call: a fake `flutter` runs shell "test files"; git is the real one.

Lead decisions (k6-notes "0.102.16"):
1  a `git` shim first on PATH of every offline suite run (and of every role): GIT_CONFIG_GLOBAL unset and HOME the
   real home → the engine's rendered config (+ GIT_CONFIG_NOSYSTEM=1); the real git by absolute path, no PATH loop.
2  the suite temp tree is its own git repo: the worktree's tracked files present in the tree, committed once
   (hooks off, no signing, no maintenance), no remote / alternates / commondir / link to the real repo.
3  base-red: a red suite's failures in test files the change did not touch are re-run once on the base in the same
   tree / sandbox / env; red there too → left out (a `base-red` grading row + journal event), only NEW failures count
   and reach the retry note; config `engine.base_red: false` or `group.base-red.conservative` turns it off.
INFO  (#227) `.git/info/` is hashed for `exclude` / `attributes` / `sparse-checkout` only (INTEGRITY_FORMAT 4).
E2E   (#227) a `commands.*` value may be a list — one reader (`config.command_list` / `command_text`).
"""

import json
import os
import subprocess
import unittest

import _util  # noqa: F401
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir
from _k2 import CFG, FLUTTER_GREEN, Harness, decision, fixture, judge_test, role, suite

from guildcore import checks as CH
from guildcore import config as CF
from guildcore import gitshim as GS
from guildcore.decisions import DecisionLog
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from workflows.dev import base_red as BR
from workflows.dev import effective as EFF
from workflows.dev import grade as GR
from workflows.dev import ports as PO
from workflows.dev.stages import test as T

MAC = os.path.exists(CH.SANDBOX_EXEC)
HOME_GITCONFIG = os.path.join(GS.real_home(), ".gitconfig")
DONE = ">>> RESULT <<<\nDONE: ok"


def _w(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, mode)


def _run_dir(case):
    rd = tmpdir(case)
    for d in ("in", "out", "tmp"):
        os.makedirs(os.path.join(rd, d), exist_ok=True)
    _w(os.path.join(rd, "in", "gitconfig"), "[user]\n\tname = engine-test\n")
    return rd


# A fake `flutter test [flags] [files]`: every "test file" is a shell script (exit 0 = pass); the output is flutter's
# expanded reporter (`MM:SS +p -f: <abs path>: t [E]`, `Some tests failed.` / `All tests passed!`).
FAKE_FLUTTER = r"""#!/bin/sh
[ "$1" = test ] || exit 0
shift
files=; skip=
for a do
  if [ -n "$skip" ]; then skip=; continue; fi
  case "$a" in -r|--reporter) skip=1 ;; -*) ;; *) files="$files $a" ;; esac
done
[ -n "$files" ] || files=$(cd "$PWD" && find test -name '*_test.dart' | sort)
p=0; f=0
for t in $files; do
  if sh "$t" > "$TMPDIR/fake-out" 2>&1; then
    p=$((p + 1)); if [ $f -gt 0 ]; then echo "00:00 +$p -$f: $PWD/$t: t"; else echo "00:00 +$p: $PWD/$t: t"; fi
  else
    f=$((f + 1)); echo "00:00 +$p -$f: $PWD/$t: t [E]"; cat "$TMPDIR/fake-out"
  fi
done
if [ $f -gt 0 ]; then echo "00:01 +$p -$f: Some tests failed."; exit 1; fi
echo "00:01 +$p: All tests passed!"
"""


def _fakebin(case):
    d = os.path.join(tmpdir(case), "realbin")
    _w(os.path.join(d, "flutter"), FAKE_FLUTTER, 0o755)
    return d


def _suite_env(case, rd):
    return dict(os.environ, PATH=_fakebin(case) + os.pathsep + os.environ["PATH"],
                GIT_CONFIG_GLOBAL=os.path.join(rd, "in", "gitconfig"), GIT_CONFIG_NOSYSTEM="1")


# ---- 1: the git shim -------------------------------------------------------------------------------------------------

PRINT_ENV = "#!/bin/sh\nprintf 'G=%s\\nN=%s\\nA=%s\\n' \"${GIT_CONFIG_GLOBAL-<unset>}\" " \
            "\"${GIT_CONFIG_NOSYSTEM-<unset>}\" \"$*\"\n"


class GitShimUnit(unittest.TestCase):
    def _shim(self):
        real = os.path.join(tmpdir(self), "git")
        _w(real, PRINT_ENV, 0o755)
        d = tmpdir(self)
        _w(os.path.join(d, "git"), GS.text(real, "/cfg/engine gitconfig"), 0o755)
        return os.path.join(d, "git")

    def _run(self, env):
        out = subprocess.run([self._shim(), "status", "-s"], env=env, stdout=subprocess.PIPE).stdout.decode()
        return dict(x.split("=", 1) for x in out.strip().split("\n"))

    def test_reinjects_when_stripped_and_home_is_the_real_home(self):
        got = self._run({"PATH": "/usr/bin:/bin", "HOME": GS.real_home()})
        self.assertEqual(got, {"G": "/cfg/engine gitconfig", "N": "1", "A": "status -s"})

    def test_leaves_a_set_value_alone_even_empty(self):
        for v in ("/x/own", ""):
            got = self._run({"PATH": "/usr/bin:/bin", "HOME": GS.real_home(), "GIT_CONFIG_GLOBAL": v})
            self.assertEqual(got["G"], v)
            self.assertEqual(got["N"], "<unset>")

    def test_leaves_a_moved_home_alone(self):
        got = self._run({"PATH": "/usr/bin:/bin", "HOME": tmpdir(self)})
        self.assertEqual((got["G"], got["N"]), ("<unset>", "<unset>"))

    def test_no_path_loop(self):
        rd = _run_dir(self)
        env, shim = PO.offline_shims(rd, {"PATH": "/usr/bin:/bin"})
        self.assertIn("git", shim.split(","))
        sdir = os.path.join(rd, PO.SHIM_DIR)
        env2, _ = PO.offline_shims(rd, env)                       # a second preparation, the shim dir first on PATH
        text = open(os.path.join(sdir, "git")).read()
        real = text.split("exec ")[1].split(" ")[0].strip("'")
        self.assertTrue(os.path.isabs(real))
        self.assertNotEqual(os.path.realpath(os.path.dirname(real)), os.path.realpath(sdir))
        self.assertEqual(env2["PATH"].split(os.pathsep).count(sdir), 1)
        self.assertIsNone(GS.resolve(sdir, (sdir,)))               # only the shim dir on PATH → no git at all
        self.assertIn("GIT_CONFIG_GLOBAL='%s'" % os.path.join(rd, "in", "gitconfig"), text)

    def test_the_shim_runs_the_real_git(self):
        rd = _run_dir(self)
        env, _ = PO.offline_shims(rd, {"PATH": "/usr/bin:/bin", "HOME": GS.real_home()})
        p = subprocess.run(["git", "--version"], env=env, stdout=subprocess.PIPE)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(p.stdout.startswith(b"git version"))

    def test_role_path_gets_the_shim(self):
        wt = repo(self, {"lib/a.dart": "a\n"})
        git(wt, "switch", "-q", "-c", "fix/1")
        u = tmpdir(self)
        r = RR.Runner(journal=RecJournal(), parent_env={"PATH": os.environ["PATH"], "HOME": GS.real_home()},
                      spawn=FakeSpawn([{"stream": stream_lines(texts=[DONE])}]),
                      user_settings=os.path.join(u, "u"), run_root_dir=os.path.join(u, "runs"), claude="claude",
                      clock=Clock())
        spec = RR.RoleSpec("developer", "implement", "t", issue=1, stage="s", step="x", worktree=wt, model="sonnet",
                           base="main", branch="fix/1", remote_check=False)
        self.assertEqual(r.run_role(spec).status, "DONE")
        envs = [os.path.join(b, f) for b, _d, fs in os.walk(os.path.join(u, "runs")) for f in fs if f == "env.sh"]
        self.assertEqual(len(envs), 1)
        text = open(envs[0]).read()
        run_dir = os.path.dirname(os.path.dirname(envs[0]))
        shim = os.path.join(run_dir, "in", "engine-shim")
        line = [x for x in text.splitlines() if x.startswith("export PATH=")][0]
        self.assertTrue(line.split("=", 1)[1].strip("'").startswith(shim + os.pathsep), line)
        self.assertIn("GIT_CONFIG_GLOBAL='%s'" % os.path.join(run_dir, "in", "gitconfig"),
                      open(os.path.join(shim, "git")).read())


@unittest.skipUnless(MAC and os.path.exists(HOME_GITCONFIG), "sandbox-exec + a real ~/.gitconfig")
class GitShimSandbox(unittest.TestCase):
    """#687 B: under a profile denying ~/.gitconfig, a caller that strips GIT_* runs `git init` — 128 without the
    shim, 0 with it."""

    def _run(self, shimmed):
        rd = _run_dir(self)
        env = {"PATH": "/usr/bin:/bin", "HOME": GS.real_home(), "GIT_CONFIG_GLOBAL": os.path.join(rd, "in", "gitconfig"),
               "GIT_CONFIG_NOSYSTEM": "1"}
        if shimmed:
            env, _ = PO.offline_shims(rd, env)
        tree = tmpdir(self)
        return CH.run_command(['env -u GIT_CONFIG_GLOBAL -u GIT_CONFIG_NOSYSTEM git init -q "$TMPDIR/x"'], 60,
                              cwd=tree, env=env, sandbox={"filesystem": {"allowWrite": [],
                                                                         "denyRead": [HOME_GITCONFIG]}},
                              tmp=os.path.join(rd, "tmp"))

    def test_without_the_shim_128(self):
        r = self._run(False)
        self.assertEqual(r.rc, 128, r.raw)
        self.assertIn(".gitconfig", r.raw)

    def test_with_the_shim_0(self):
        r = self._run(True)
        self.assertEqual(r.rc, 0, r.raw)


# ---- 2: the temp tree's own git repo -----------------------------------------------------------------------------------

class TreeGit(unittest.TestCase):
    def test_the_tree_is_a_repo_of_the_worktrees_tracked_files(self):
        wt = repo(self, {"lib/a.dart": "a\n", "test/a_test.dart": "x\n", ".gitignore": "secret.env\nbuild/\n",
                         "odd name [x].txt": "o\n"})
        _w(os.path.join(wt, "secret.env"), "TOKEN=1\n")             # ignored: never in the tree, never tracked
        _w(os.path.join(wt, "untracked.txt"), "u\n")                 # overlay: in the tree, not tracked
        os.remove(os.path.join(wt, "lib", "a.dart"))                 # deleted in the worktree: not in the tree
        git(wt, "config", "core.hooksPath", ".husky")
        _w(os.path.join(wt, ".husky", "pre-commit"), "#!/bin/sh\necho HOOK > /tmp/never\n", 0o755)
        with EFF.prepared_tree(wt, None, [], None, overlay=True) as (tt, info):
            self.assertTrue(info["tree_git"].startswith("ok("), info["tree_git"])
            gd = os.path.join(tt.path, ".git")
            self.assertTrue(os.path.isdir(gd) and not os.path.islink(gd))
            files = git(tt.path, "ls-files").splitlines()
            want = [f for f in git(wt, "ls-files").splitlines() if os.path.exists(os.path.join(wt, f))]
            self.assertEqual(sorted(files), sorted(want))
            self.assertNotIn("secret.env", files)
            self.assertNotIn("untracked.txt", files)
            self.assertEqual(git(tt.path, "rev-parse", "--is-inside-work-tree"), "true")
            self.assertEqual(os.path.realpath(git(tt.path, "rev-parse", "--show-toplevel")), os.path.realpath(tt.path))
            self.assertEqual(git(tt.path, "remote"), "")
            for x in ("commondir", "objects/info/alternates", "gitdir", "hooks"):
                self.assertFalse(os.path.exists(os.path.join(gd, x)), x)
            cfg = open(os.path.join(gd, "config")).read()
            self.assertIn("hooksPath = /dev/null", cfg)
            self.assertIn("auto = false", cfg)
            self.assertNotIn(wt, cfg)
            self.assertEqual(git(tt.path, "status", "--porcelain", "--untracked-files=no"), "")

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_r687_replay_strip_git_init_and_full_sweep_green(self):
        """#687's two classes in one suite: a helper that strips GIT_* and runs `git init` (B) and a full-sweep scanner
        that needs `git rev-parse --is-inside-work-tree` + `git ls-files` in the tree (A)."""
        wt = repo(self, {
            "tool/run_tests_judged.sh": "#!/usr/bin/env bash\nset -u\nflutter test --concurrency=8\n",
            "lib/a.dart": "int a() => 1;\n",
            "test/tool/secret_path_scan_gate_test.dart":
                'env -u GIT_CONFIG_GLOBAL -u GIT_CONFIG_NOSYSTEM -u GIT_DIR git init -q "$TMPDIR/g$$" || exit 1\n'
                'env -u GIT_CONFIG_GLOBAL -u GIT_CONFIG_NOSYSTEM git -C "$TMPDIR/g$$" status -s || exit 1\n',
            "test/tool/process_meta_token_guard_full_scan_test.dart":
                'git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "outside a git work tree"; exit 2; }\n'
                'git ls-files -z -- "lib/*.dart" "test/*.dart" | tr "\\0" "\\n" | grep -q "^lib/a.dart$" || exit 3\n'})
        rd = _run_dir(self)
        r = PO.suite_in_tree(wt, None, ["bash tool/run_tests_judged.sh"], "developer", 120, rd, _suite_env(self, rd),
                             warm=False)
        self.assertTrue(r.passed, r.raw)
        self.assertIn("All tests passed!", r.raw)
        self.assertEqual(r.missing_ignored, [])
        self.assertTrue((r.tree_git or "").startswith("ok("), r.tree_git)
        self.assertIn("git", (r.offline_shim or "").split(","))

    def test_suite_and_net_trees_get_the_repo_in_prepared_tree(self):
        src = open(EFF.__file__, encoding="utf-8").read()
        body = src[src.index("def prepared_tree("):src.index("# ---- per AC")]
        self.assertIn("tt.make_git()", body)
        self.assertLess(body.index("tt.copy_listed("), body.index("tt.make_git()"))


# ---- 3: base-red -----------------------------------------------------------------------------------------------------

ENV_RED = "exit 1\n"                                              # red in the engine env, whatever the code
REAL_RED = 'grep -q "=> 2" lib/a.dart && { echo "expected 1"; exit 1; }\nexit 0\n'   # red only with the change


def _branch(case, base_files, change):
    wt = repo(case, dict({"tool/run.sh": "#!/usr/bin/env bash\nflutter test\n", "lib/a.dart": "int a() => 1;\n"},
                         **base_files))
    git(wt, "switch", "-q", "-c", "feature/7-x")
    for rel, text in change.items():
        _w(os.path.join(wt, rel), text)
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "--allow-empty", "-m", "change")
    return wt


@unittest.skipUnless(MAC, "sandbox-exec only on macOS")
class BaseRedSuite(unittest.TestCase):
    def _suite(self, wt, **kw):
        rd = _run_dir(self)
        r = PO.suite_in_tree(wt, "main", ["bash tool/run.sh"], "developer", 120, rd, _suite_env(self, rd), warm=False,
                             **kw)
        PO.keep_raw(rd, ["bash tool/run.sh"], r)
        return r, rd

    def test_unchanged_and_red_on_base_is_excluded(self):
        wt = _branch(self, {"test/tool/env_test.dart": ENV_RED, "test/ok_test.dart": "exit 0\n"},
                     {"lib/a.dart": "int a() => 3;\n"})
        r, rd = self._suite(wt)
        self.assertFalse(r.passed)
        br = r.base_red
        self.assertEqual(br["excluded"], ["test/tool/env_test.dart: t"])
        self.assertEqual(br["new"], [])
        self.assertEqual(br["files"], ["test/tool/env_test.dart"])
        self.assertIn("test/tool/env_test.dart", br["cmd"])
        self.assertNotIn("ok_test", br["cmd"])                     # only the failing files run on the base
        self.assertIn("--- base re-run:", open(os.path.join(rd, "out", "raw.txt")).read())

    def test_green_on_base_is_new(self):
        wt = _branch(self, {"test/real_test.dart": REAL_RED}, {"lib/a.dart": "int a() => 2;\n"})
        r, _rd = self._suite(wt)
        self.assertEqual(r.base_red["excluded"], [])
        self.assertEqual(r.base_red["new"], ["test/real_test.dart: t"])

    def test_a_changed_test_file_is_kept_and_never_run_on_base(self):
        wt = _branch(self, {"test/env_test.dart": "exit 0\n"}, {"test/env_test.dart": ENV_RED})
        r, _rd = self._suite(wt)
        self.assertEqual(r.base_red["changed"], ["test/env_test.dart"])
        self.assertEqual(r.base_red["new"], ["test/env_test.dart: t"])
        self.assertIsNone(r.base_red["cmd"])

    def test_mixed_only_the_real_one_is_new(self):
        wt = _branch(self, {"test/tool/env_test.dart": ENV_RED, "test/real_test.dart": REAL_RED},
                     {"lib/a.dart": "int a() => 2;\n"})
        r, _rd = self._suite(wt)
        self.assertEqual(r.base_red["excluded"], ["test/tool/env_test.dart: t"])
        self.assertEqual(r.base_red["new"], ["test/real_test.dart: t"])
        self.assertIn("test/real_test.dart: t", BR.red_reason(r.base_red).split(";")[0])
        self.assertNotIn("env_test.dart: t", BR.red_reason(r.base_red).split(";")[0])

    def test_uncommitted_change_counts_as_changed(self):
        wt = _branch(self, {"test/tool/env_test.dart": ENV_RED, "test/real_test.dart": REAL_RED}, {})
        _w(os.path.join(wt, "lib", "a.dart"), "int a() => 2;\n")    # overlay: uncommitted
        r, _rd = self._suite(wt)
        self.assertEqual(r.base_red["new"], ["test/real_test.dart: t"])
        self.assertEqual(r.base_red["excluded"], ["test/tool/env_test.dart: t"])

    def test_config_off_never_runs_it(self):
        wt = _branch(self, {"test/tool/env_test.dart": ENV_RED}, {"lib/a.dart": "int a() => 3;\n"})
        r, _rd = self._suite(wt, base_red=False)
        self.assertIsNone(r.base_red)

    def test_a_failure_the_names_miss_is_never_excluded(self):
        raw = "00:00 +1 -1: /t/test/a_test.dart: t [E]\n00:01 +1 -2: Some tests failed.\n"
        self.assertEqual(BR.failures(raw, ("/t",)), ("flutter", None))
        raw2 = "00:00 +1 -1: /t/test/a_test.dart: (setUpAll) [E]\n00:01 +1 -1: Some tests failed.\n"
        self.assertEqual(BR.failures(raw2, ("/t",)), ("flutter", [("test/a_test.dart", "(setUpAll)")]))


class BaseRedRaw687(unittest.TestCase):
    def test_the_real_687_output_names_all_21_with_their_files(self):
        p = os.path.expanduser("~/.cache/guild-engine/d1e3d67acdca/687/runs/018-check-developer/out/raw.txt")
        if not os.path.exists(p):
            self.skipTest("the #687 run dir is not on this machine")
        runner, fails = BR.failures(open(p, encoding="utf-8").read(), ("/Users/j-kim/projects/.gld-one-man-company-687",))
        self.assertEqual(runner, "flutter")
        self.assertEqual(len(fails), 21)
        self.assertEqual(sorted(set(f for f, _n in fails)), [
            "test/tool/process_meta_token_guard_full_scan_test.dart", "test/tool/secret_path_scan_gate_test.dart",
            "test/tool/verify_freshness_gate_fence_test.dart", "test/tool/verify_freshness_gate_html_indent_test.dart",
            "test/tool/verify_freshness_gate_scan_test.dart", "test/tool/verify_freshness_gate_test.dart"])


RED_RAW = ("00:00 +1: /wt/test/ok_test.dart: t\n00:00 +1 -1: /wt/test/tool/env_test.dart: t [E]\n"
           "00:00 +1 -2: /wt/test/real_test.dart: t [E]\n00:01 +1 -2: Some tests failed.\n")


def _red(excluded, new):
    r = suite(RED_RAW, passed=False, rc=1)
    r.base_red = {"runner": "flutter", "failures": excluded + new, "changed": [], "files": ["test/tool/env_test.dart"],
                  "cmd": "flutter test --no-pub -r expanded test/tool/env_test.dart", "base_rc": 1,
                  "base_summary": None, "excluded": list(excluded), "new": list(new)}
    return r


class EvJournal(RecJournal):
    def __init__(self):
        RecJournal.__init__(self)
        self.events = []

    def own_comment_ids(self):
        return ()

    def append(self, kind, **f):
        self.events.append(dict(f, kind=kind))


def _blocks(h, point):
    return [b for b in DecisionLog.load(h.gh.comments(7)).blocks if b.get("point") == point]


class BaseRedExecute(unittest.TestCase):
    def test_all_excluded_advances_with_a_grading_row(self):
        from _k3 import XHarness, auditor, dev
        from test_k3_execute_stage import TL_DONE
        from workflows.dev.stages import execute as X
        h = XHarness(self, roles=[dev(), TL_DONE, auditor()],
                     suites=[_red(["test/tool/env_test.dart: t", "test/real_test.dart: t"], [])])
        h.p.journal = EvJournal()
        self.assertEqual(X.run(h.p, "implement").token(), "OK ADVANCE: test")
        rows = _blocks(h, "base-red")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].get("by"), rows[0].get("grade")), ("code", "trigger"))
        self.assertTrue(GR.code_trigger_row(rows[0]))
        self.assertEqual(GR.group_of(rows[0]), GR.BASE_RED_GROUP)
        self.assertIn("red on the base too", h.body_with("test-evidence:step-1"))
        self.assertTrue(any(e.get("what") == "base-red" for e in h.p.journal.events))

    def test_mixed_retry_note_names_only_the_new_failure(self):
        from _k3 import XHarness, dev
        from workflows.dev.stages import execute as X
        mixed = _red(["test/tool/env_test.dart: t"], ["test/real_test.dart: t"])
        h = XHarness(self, roles=[dev(), dev()], suites=[mixed, _red(["test/tool/env_test.dart: t"],
                                                                      ["test/real_test.dart: t"])],
                     judges={"SAMECAUSE": decision("different", {"verdict": "different"})})
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        devs = [c for c in h.calls["roles"] if c.role == "developer"]
        note = devs[1].inputs["retry.md"]
        head = note.split("red on the base too")[0]
        self.assertIn("test/real_test.dart: t", head)
        self.assertNotIn("env_test.dart", head)

    def test_the_valve_keeps_red_red(self):
        from _k3 import XHarness, dev
        from workflows.dev.stages import execute as X
        h = XHarness(self, roles=[dev(), dev()], suites=[_red(["test/tool/env_test.dart: t"], [])] * 2,
                     judges={"SAMECAUSE": decision("different", {"verdict": "different"})})
        h.p.valves = {BR.VALVE: True}
        self.assertEqual(X.run(h.p, "implement").kind, "PAUSE")
        self.assertEqual(_blocks(h, "base-red"), [])

    def test_config_off(self):
        self.assertFalse(BR.enabled({"engine": {"base_red": False}}))
        self.assertTrue(BR.enabled({"engine": {}}))
        self.assertTrue(BR.off(object(), {"engine": {"base_red": False}}))


def _tstage(case, s, cfg=None):
    covers = [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "guard"}]
    h = Harness(case, fixture(), roles=[role("DONE", covers=covers, e2e="E2E 불요: 위젯 한정")],
                judges={"TEST": [judge_test(["C1"])]}, suites=[s], config=cfg, test_cases="| C1 | a |\n")
    h.write_file("test/a_test.dart", "void main() {\n  testWidgets('t', (tester) async {\n"
                                     "    expect(find.text('a'), findsOneWidget);\n  });\n}\n")
    return h, T.run(h.p)


class BaseRedTestStage(unittest.TestCase):
    def test_all_excluded_is_green_with_a_row(self):
        h, r = _tstage(self, _red(["test/tool/env_test.dart: t", "test/real_test.dart: t"], []))
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        self.assertEqual(len(_blocks(h, "base-red")), 1)

    def test_new_failures_still_loop_back(self):
        _h, r = _tstage(self, _red(["test/tool/env_test.dart: t"], ["test/real_test.dart: t"]))
        self.assertNotEqual(r.token(), "OK ADVANCE: qa")


class BaseRedGrade(unittest.TestCase):
    def test_a_wrong_on_a_base_red_row_sets_the_valve_path(self):
        src = open(GR.__file__, encoding="utf-8").read()
        self.assertIn("if g in (FLAKE_GROUP, BASE_RED_GROUP):", src)
        self.assertEqual(BR.VALVE, "group.%s.conservative" % GR.BASE_RED_GROUP)


# ---- INFO (#227 on 0.102.15): .git/info bookkeeping is no drift ------------------------------------------------------

class InfoHash(unittest.TestCase):
    def setUp(self):
        self.wt = repo(self, {"a.txt": "a\n"})
        self.info = os.path.join(self.wt, ".git", "info")
        os.makedirs(self.info, exist_ok=True)
        _w(os.path.join(self.info, "exclude"), "# e\n")

    def test_refs_and_packs_are_no_drift(self):
        b = SC.integrity(self.wt)
        _w(os.path.join(self.info, "refs"), "abc\trefs/heads/main\n")
        _w(os.path.join(self.info, "packs"), "P pack-1.pack\n")
        self.assertEqual(SC.integrity(self.wt), b)

    def test_exclude_attributes_sparse_checkout_are_drift(self):
        for f in ("exclude", "attributes", "sparse-checkout"):
            with self.subTest(f=f):
                b = SC.integrity(self.wt)
                _w(os.path.join(self.info, f), "changed %s\n" % f)
                self.assertNotEqual(SC.integrity(self.wt), b)

    def test_the_format_moved_and_an_info_item_is_format_only(self):
        self.assertEqual(SC.INTEGRITY_FORMAT, 4)
        self.assertTrue(SC.config_format_only({"integrity_format": 3}, ["info /x/.git"]))
        self.assertFalse(SC.config_format_only({"integrity_format": 4}, ["info /x/.git"]))
        self.assertFalse(SC.config_format_only({"integrity_format": 3}, ["info /x/.git", "path a.txt"]))


# ---- E2E (#227 on 0.102.15): a list-valued commands.* -----------------------------------------------------------------

E2E_LIST = ["pnpm build:e2e", "pnpm --filter visa-home test:e2e"]


class CommandLists(unittest.TestCase):
    def test_the_reader(self):
        self.assertEqual(CF.command_list(E2E_LIST), E2E_LIST)
        self.assertEqual(CF.command_list("a b"), ["a b"])
        self.assertEqual(CF.command_list(None), [])
        self.assertEqual(CF.command_text(E2E_LIST), "pnpm build:e2e && pnpm --filter visa-home test:e2e")
        self.assertIsNone(CF.command_text([]))

    def test_r227_list_e2e_through_the_test_stage_render(self):
        cfg = dict(CFG, commands=dict(CFG["commands"], e2e=E2E_LIST, vrt=["a", "b"]))
        h, r = _tstage(self, suite(FLUTTER_GREEN), cfg=cfg)
        self.assertEqual(r.token(), "OK ADVANCE: qa")
        body = h.body_with("test:output")
        self.assertIn("pnpm build:e2e && pnpm --filter visa-home test:e2e", body)

    def test_qa_honesty_lines_read_a_list(self):
        from guildcore.roles.runner import RoleResult
        from workflows.dev.stages import qa as Q

        class P(object):
            unattended = False
        q = RoleResult("DONE", None, {"ran": ["pnpm build:e2e", "pnpm --filter visa-home test:e2e ok"], "not_run": []})
        lines = Q.honesty_lines(P(), {"commands": {"e2e": E2E_LIST}}, q, [], ui=False)
        self.assertNotIn("commands.e2e", lines[1])
        q2 = RoleResult("DONE", None, {"ran": ["pnpm build:e2e"], "not_run": []})
        lines = Q.honesty_lines(P(), {"commands": {"e2e": E2E_LIST}}, q2, [], ui=False)
        self.assertIn("`commands.e2e`(pnpm build:e2e && pnpm --filter visa-home test:e2e)", lines[1])


# ---- review-0102-15 (the reviewer's 7 failing repros, adapted to the lead's decisions) ---------------------------------

from guildcore.checks import pmcache as PMC                    # noqa: E402
from guildcore.roles import result as R                        # noqa: E402
from guildcore.roles import settings as ST                     # noqa: E402
from workflows.dev import preflight as PF                      # noqa: E402
import shutil                                                  # noqa: E402

GATE = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL")


class RB1DoneButBlocked(unittest.TestCase):
    def _alt(self, line, schema=None, obj=None):
        reply = "review written to out/security-review.md\n>>> RESULT <<<\n" + line
        pres = R.parse_pres(reply, GATE)
        return R.structured_pres(pres, obj or {"file": "out/security-review.md"}, GATE, reply,
                                 schema or R.RESULT_SCHEMAS["specialist"])

    def test_an_enum_blocking_word_after_done_is_never_done(self):
        tl = {"type": "object", "required": ["skeleton"]}
        for line in ("done — BLOCKED: secrets committed in config/prod.env", "Done. BLOCKED: token logged in plain text",
                     "Done, but FAIL: the auth tests are red", "DONE reviewing; verdict BLOCKED (SQL injection)"):
            self.assertIsNone(self._alt(line), line)
            self.assertIsNone(self._alt(line, tl, {"skeleton": "s.md"}), line)     # any schema: another status word

    def test_a_reviewers_refusal_after_done_is_never_done(self):
        for line in ("Done reviewing — REJECTED: SQL injection in api/login",
                     "Done — 承認できません（SQL injection）", "done: NOT approved — CHANGES_REQUESTED"):
            self.assertIsNone(self._alt(line), line)

    def test_the_loose_reader_never_takes_done_then_a_status(self):
        for line in ("DONE — BLOCKED: x", "DONE: BLOCKED: x", "**DONE** - FAIL: y"):
            p = R.parse_pres(">>> RESULT <<<\n" + line, GATE)
            self.assertFalse(p.ok and p.status == "DONE", line)
        p = R.parse_pres(">>> RESULT <<<\nDONE: Fail-safe handling added", GATE)
        self.assertEqual((p.ok, p.status), (True, "DONE"))                  # prose, not the enum word

    def test_control_plain_done_one_session_for_other_roles(self):
        tl = {"type": "object", "required": ["skeleton"]}
        for line in ("Done.", "done", "**Done**"):
            self.assertEqual(self._alt(line, tl, {"skeleton": "s.md"}).status, "DONE")
            self.assertIsNone(self._alt(line))                               # never for a gate reviewer


class RS1StoreWritable(unittest.TestCase):
    def test_the_user_store_is_never_a_toolchain_write_and_every_store_is_denied(self):
        home = tmpdir(self)
        os.makedirs(home + "/Library/pnpm/store/v3")
        tree, rp, rd = tmpdir(self), tmpdir(self), _run_dir(self)
        subprocess.run(["git", "init", "-q", rp])
        for d in (tree, rp):
            _w(d + "/package.json", '{"packageManager":"pnpm@8.15.0"}')
        self.assertNotIn(home + "/Library/pnpm/**", ST.toolchain_writes(tree, home=home))
        old = os.environ.get("HOME")
        os.environ["HOME"] = home
        os.environ["GLD_ENGINE_PNPM_STORE"] = home + "/Library/pnpm/store/v3"       # a user store: ignored
        try:
            store = PMC.pnpm_store()
            self.assertFalse(store.startswith(home + "/Library/pnpm"), store)
            fs = PO.tree_sandbox(tree, rd, rp, 1)["filesystem"]
            role = ST.role_sandbox("developer", None, rd, 1, toolchain=True)["filesystem"]
        finally:
            os.environ["HOME"] = old
            os.environ.pop("GLD_ENGINE_PNPM_STORE", None)
        for f in (fs, role):
            self.assertIn(store + "/**", f["denyWrite"])
            self.assertIn(home + "/Library/pnpm/store/**", f["denyWrite"])

    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_the_suite_cannot_write_the_engine_store(self):
        wt = repo(self, {"a.txt": "a\n"})
        store = os.path.join(tmpdir(self), "store")
        os.makedirs(store)
        os.environ["GLD_ENGINE_PNPM_STORE"] = store
        self.addCleanup(os.environ.pop, "GLD_ENGINE_PNPM_STORE", None)
        rd = _run_dir(self)
        r = PO.suite_in_tree(wt, None, ["echo poisoned > %s/PLANTED; true" % store], "developer", 60, rd,
                             dict(os.environ), warm=False)
        self.assertFalse(os.path.exists(store + "/PLANTED"), r.raw[-400:])

    def test_seed_clones_the_user_store_once_read_only(self):
        home = tmpdir(self)
        src = os.path.join(home, "Library", "pnpm", "store", "v3", "files", "aa")
        _w(os.path.join(src, "x"), "content\n")
        store = os.path.join(tmpdir(self), "engine-store")
        note = PMC.seed_pnpm_store(user_home=home, store=store)
        self.assertIn("seeded the engine store", note)
        self.assertEqual(open(os.path.join(store, "v3", "files", "aa", "x")).read(), "content\n")
        self.assertEqual(open(os.path.join(src, "x")).read(), "content\n")
        self.assertIsNone(PMC.seed_pnpm_store(user_home=home, store=store))     # not empty any more: no second seed


def _pnpm_repo(case):
    from test_k6_0102_15 import _pnpm_env
    root = repo(case, {".gitignore": "node_modules/\n",
                       "package.json": json.dumps({"name": "root", "private": True, "packageManager": "pnpm@8.15.0",
                                                   "dependencies": {"dep": "file:vendor/dep-1.0.0.tgz"}}),
                       "vendor/package/package.json": '{"name":"dep","version":"1.0.0","main":"index.js"}',
                       "vendor/package/index.js": "module.exports = 42\n"})
    subprocess.run("tar czf dep-1.0.0.tgz package && rm -rf package", shell=True, cwd=os.path.join(root, "vendor"),
                   check=True)
    p = subprocess.run("pnpm install --lockfile-only --offline --ignore-pnpmfile --store-dir %s" %
                       os.path.join(tmpdir(case), "lockstore"), shell=True, cwd=root, env=_pnpm_env(),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    case.assertEqual(p.returncode, 0, p.stdout.decode())
    git(root, "add", "-A")
    git(root, "commit", "-qm", "lock")
    return root


def _pnpm_ok():
    try:
        from test_k6_0102_15 import _pnpm_ok as ok
        return ok()
    except Exception:                                  # noqa: BLE001
        return False


@unittest.skipUnless(_pnpm_ok(), "needs macOS sandbox-exec and pnpm@8.15.0 in the engine's Corepack home")
class RF1FetchLocalDep(unittest.TestCase):
    def test_a_fetch_failure_is_a_note_and_never_fails_the_deps_step(self):
        from test_k6_0102_15 import _pnpm_env
        root = _pnpm_repo(self)
        os.environ["GLD_ENGINE_PNPM_STORE"] = os.path.join(tmpdir(self), "fetch-store")
        self.addCleanup(os.environ.pop, "GLD_ENGINE_PNPM_STORE", None)
        rd = _run_dir(self)
        r = PO.deps_main(root, rd, PO.check_env(_pnpm_env(), root, rd), tools=None)
        self.assertTrue(r.passed, r.raw[-300:])
        self.assertTrue(any("failed (a note — the offline install decides)" in n or n.endswith("— ok")
                            for n in r.notes), r.notes)

    def test_the_fetch_takes_the_base_workspace_file_and_ignores_the_pnpmfile(self):
        self.assertIn("--ignore-pnpmfile", PO.PNPM_FETCH)
        src = open(PO.__file__, encoding="utf-8").read()
        body = src[src.index("def pnpm_fetch("):src.index("def _user_pnpm_store_path(")]
        self.assertIn('"%s:pnpm-workspace.yaml" % base', body)
        self.assertNotIn("PNPM_INPUTS", body)


class RM1AbsolutePathMention(unittest.TestCase):
    def test_an_absolute_temp_path_is_no_mention_of_the_ignored_tmp_dir(self):
        root = tmpdir(self)
        subprocess.run("git init -q && printf 'tmp/\\n' > .gitignore && mkdir tmp && echo x > tmp/cache.txt",
                       shell=True, cwd=root, check=True)
        tree = tmpdir(self)
        raw = ("FAIL  src/a.test.ts > adds\nAssertionError: expected 3 to be 4\n"
               " ❯ /private/tmp/claude-502/tmpk2l1/src/a.test.ts:5:13\n Tests  1 failed (1)\n")
        self.assertEqual(PF.missing_ignored(raw, root, ["tmp/"], tree), [])
        # the tree's own prefix still names it
        self.assertEqual(PF.missing_ignored("ENOENT: %s/tmp/cache.txt\n" % tree, root, ["tmp/"], tree), ["tmp"])


class Rm3CliAuthInSuite(unittest.TestCase):
    def test_the_suite_env_has_no_cli_credentials(self):
        rd = _run_dir(self)
        e = PO.check_env({"PATH": "/usr/bin", "HOME": os.environ["HOME"], "ANTHROPIC_API_KEY": "sk-ant-x",
                          "CLAUDE_CODE_OAUTH_TOKEN": "oat-x", "ANTHROPIC_AUTH_TOKEN": "t"}, tmpdir(self), rd)
        e = CH.check_env(e, os.path.join(rd, "tmp"))
        for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN"):
            self.assertIsNone(e.get(k), k)


class Rm2UnlinkRechecksParents(unittest.TestCase):
    def test_a_parent_turned_link_before_the_unlink_is_left(self):
        wt = tmpdir(self)
        outside = tmpdir(self)
        _w(os.path.join(outside, "f.txt"), "keep\n")
        os.makedirs(os.path.join(wt, "pkg"))
        _w(os.path.join(wt, "pkg", "f.txt"), "role\n")
        shutil.rmtree(os.path.join(wt, "pkg"))
        os.symlink(outside, os.path.join(wt, "pkg"))          # the parent became a link after the first pass
        row = {}
        SC._unlink_as(os.path.join(wt, "pkg", "f.txt"), "file", row, wt, "pkg/f.txt")
        self.assertTrue(os.path.exists(os.path.join(outside, "f.txt")))
        self.assertIn("behind the symlink", row.get("unlink", ""))


class Rm5RunnerMissing(unittest.TestCase):
    RAW = "> x@1 test\n> vitestt run\n\nsh: vitestt: command not found\n"

    def test_a_changed_package_json_is_the_developers(self):
        from _k3 import XHarness, dev
        from workflows.dev.stages import execute as X
        from workflows.dev.stages import base as B
        h = XHarness(self, roles=[dev(), dev()], suites=[suite(self.RAW, passed=False, rc=127)] * 2,
                     judges={"SAMECAUSE": decision("different", {"verdict": "different"})})
        _w(os.path.join(h.p.root, "package.json"), '{"scripts":{"test":"vitestt run"}}')
        git(h.p.root, "add", "-A")
        git(h.p.root, "commit", "-qm", "typo")
        self.assertEqual(B.runner_inputs_changed(h.p), ["package.json"])
        r = X.run(h.p, "implement")
        self.assertNotIn("engine-env-deps-missing", r.cause or "")
        devs = [c for c in h.calls["roles"] if c.role == "developer"]
        self.assertEqual(len(devs), 2)
        self.assertIn("vitestt: command not found", devs[1].inputs["retry.md"])

    def test_unchanged_manifests_stay_an_env_stop(self):
        from _k3 import XHarness, dev
        from workflows.dev.stages import execute as X
        h = XHarness(self, roles=[dev()], suites=[suite(self.RAW, passed=False, rc=127)])
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        self.assertIn("engine-env-deps-missing", h.body_with("needs-human"))


# ---- word_app #1797 on 0.102.15: PWD is the realpath (a 0.102.14 regression) ------------------------------------------

class PwdRealpath(unittest.TestCase):
    @unittest.skipUnless(MAC, "sandbox-exec only on macOS")
    def test_pwd_matches_realpaths_under_a_var_temp_dir(self):
        import tempfile
        d = tempfile.mkdtemp(dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
        self.addCleanup(shutil.rmtree, d, True)
        self.assertNotEqual(d, os.path.realpath(d))          # /var → /private/var
        rd = _run_dir(self)
        script = 'root="$(pwd)"; real="$(cd "$(pwd -P)" && pwd)"; [ "$root" = "$real" ] && [ "$PWD" = "$real" ] ' \
                 '&& echo SAME || { echo "DIFF $root $real"; exit 1; }'
        r = CH.run_command([script], 30, cwd=d, env=dict(os.environ), sandbox={"filesystem": {"allowWrite": []}},
                           tmp=os.path.join(rd, "tmp"))
        self.assertTrue(r.passed, r.raw)
        self.assertIn("SAME", r.raw)

    def test_zero_failed_with_rc_names_how_it_ended(self):
        from _k3 import XHarness, dev
        from workflows.dev.stages import execute as X
        raw = "00:01 +421: All tests passed!\nFAIL: missing from run: test/a_test.dart\n" \
              "RESULT: FAIL (421 of 421 test files missing from run)\n"
        h = XHarness(self, roles=[dev(), dev()], suites=[suite(raw, passed=False, rc=1)] * 2,
                     judges={"SAMECAUSE": decision("different", {"verdict": "different"})})
        X.run(h.p, "implement")
        devs = [c for c in h.calls["roles"] if c.role == "developer"]
        note = devs[1].inputs["retry.md"]
        self.assertIn("RESULT: FAIL (421 of 421 test files missing from run)", note)
        self.assertNotIn("0 failed", note)


if __name__ == "__main__":
    unittest.main()
