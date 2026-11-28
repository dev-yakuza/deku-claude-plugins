"""tools/convert_config.py — 0.98.7 settings → `.claude/guild/` proposal (U16). No network, no paid calls."""

import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from gxengine import instructions, repoconfig, schema
from tests.helpers.gitrepo import GitRepo

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ENGINE, "tests", "fixtures", "config")
NOW = datetime.datetime(2026, 11, 23, 1, 2, 3, tzinfo=datetime.timezone.utc)

_spec = importlib.util.spec_from_file_location("convert_config", os.path.join(ENGINE, "tools", "convert_config.py"))
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class MemSource:
    """A repository as a dict {path: text}; `untracked` is the checkout's untracked/ignored listing."""

    label = "mem"

    def __init__(self, files, untracked=(), dirs=()):
        self._files, self._untracked, self._dirs = dict(files), list(untracked), set(dirs)

    def has_dir(self, rel):
        return rel in self._dirs

    def files(self):
        return sorted(self._files)

    def read(self, path):
        return self._files.get(path)

    def untracked(self):
        return list(self._untracked)


def stable(commands=None, **extra):
    cfg = {"version": "0.102.4", "commands": commands or {}, "engine": {}}
    cfg.update(extra)
    return json.dumps(cfg)


def convert(files, untracked=(), host_os="darwin", template=None, dirs=(), moved=None, decisions=None):
    return cc.build(MemSource(files, untracked, dirs), host_os=host_os, now=NOW, template_text=template,
                    moved_not_local=moved, decisions=decisions)


class YamlSubset(unittest.TestCase):
    def test_workflow_fixture(self):
        doc = cc.parse_yaml(fixture("workflow-quality.yml"))
        self.assertEqual(doc["on"], {"pull_request": {"types": ["labeled"]}})
        self.assertEqual(doc["env"], {"TURBO_TELEMETRY_DISABLED": "1"})
        job = doc["jobs"]["lint"]
        self.assertEqual(job["name"], "Check code format")
        self.assertEqual(job["timeout-minutes"], "40")
        steps = job["steps"]
        self.assertEqual(steps[0], {"uses": "actions/checkout@abc123"})
        self.assertEqual(steps[1]["uses"], "./.github/actions/install_dependencies")

    def test_multiline_plain_and_block_scalars(self):
        steps = cc.parse_yaml(fixture("workflow-quality.yml"))["jobs"]["lint"]["steps"]
        by = {s.get("name"): s for s in steps}
        self.assertEqual(by["Goldens"]["run"], "flutter test --fail-fast --concurrency=$(nproc --all) --tags golden --update-goldens")
        self.assertEqual(by["Test without golden"]["run"].splitlines(), [
            "mkdir -p build",
            "flutter test --exclude-tags golden --file-reporter json:build/ci.json",
            "scripts/verify_test_coverage.sh build/ci.json"])
        self.assertEqual(by["Folded"]["run"], "python3 tool/check.py --strict")
        self.assertEqual(by["Needs secrets"]["env"], {"TOKEN": "${{ secrets.TOKEN }}"})

    def test_scalars_quotes_flow_and_comments(self):
        doc = cc.parse_yaml("a: 'x # not a comment'\nb: \"y: z\"\nc: [1, 'two', three]\nd: {k: v, n: 3}\ne: ~\nf: plain # comment\n")
        self.assertEqual(doc, {"a": "x # not a comment", "b": "y: z", "c": ["1", "two", "three"], "d": {"k": "v", "n": "3"}, "e": None, "f": "plain"})

    def test_sequences_at_key_indent_and_nested(self):
        doc = cc.parse_yaml("k:\n- a\n- b: 1\n  c: 2\nm:\n  - - x\n    - y\n")
        self.assertEqual(doc, {"k": ["a", {"b": "1", "c": "2"}], "m": [["x", "y"]]})

    def test_on_list_and_string(self):
        self.assertEqual(cc.parse_yaml("on: [push, pull_request]\n"), {"on": ["push", "pull_request"]})
        self.assertEqual(cc.parse_yaml("on: push\n"), {"on": "push"})

    def test_unterminated_flow_is_an_error(self):
        with self.assertRaises(cc.YamlError):
            cc.parse_yaml("a: [1, 2\nb: 3\n")


class CommandText(unittest.TestCase):
    def test_keys_ignore_options_and_wrappers(self):
        self.assertEqual(cc.cmd_keys("flutter test --fail-fast"), {("flutter", "test")})
        self.assertEqual(cc.cmd_keys("pnpm lint"), cc.cmd_keys("pnpm run lint"))
        self.assertEqual(cc.cmd_keys("npx cspell '**' --no-progress"), {("cspell", "")})
        self.assertEqual(cc.cmd_keys("bash tool/hooks/with_clean_git_env.sh flutter analyze"), {("flutter", "analyze")})
        self.assertEqual(cc.cmd_keys("A=1 python3 tool/x.py --a"), {("script", "tool/x.py")})
        self.assertEqual(cc.cmd_keys("flutter analyze && npx remark . --quiet"), {("flutter", "analyze"), ("remark", "")})

    def test_names_are_valid_catalog_names(self):
        rx = repoconfig.schema.load_schema("repo-config")["$defs"]["name"]["pattern"]
        import re
        for key, hint in [(("script", "tool/hooks/check_process_meta.sh"), None), (("flutter", "analyze"), None), (("dart", "format"), None),
                          (("pm", "lint"), None), (("x", "y"), "Gate Suite"), (("script", "9tests.sh"), None)]:
            name = cc.name_for(key, hint)
            self.assertTrue(re.match(rx, name), name)
        self.assertEqual(cc.name_for(("script", "tool/hooks/check_process_meta.sh")), "check-process-meta")
        self.assertEqual(cc.name_for(("flutter", "analyze")), "analyze")
        self.assertEqual(cc.name_for(("dart", "format")), "dart-format")

    def test_unwrap_hook(self):
        self.assertEqual(cc.unwrap_hook_command("bash tool/hooks/pre_push_scope.sh test -- bash run.sh"), "bash run.sh")
        self.assertEqual(cc.unwrap_hook_command("flutter analyze"), "flutter analyze")

    def test_classification(self):
        c = cc.classify_command
        self.assertEqual(c("sudo apt-get install -y x")[0], "not-local")
        self.assertEqual(c("python3 x.py --since ${{ github.event.pull_request.base.sha }}")[0], "not-local")
        self.assertEqual(c("echo a >> $GITHUB_OUTPUT")[0], "not-local")
        self.assertEqual(c("git checkout origin/main")[0], "not-local")
        self.assertEqual(c("flutter test --update-goldens")[0], "not-local")
        self.assertEqual(c("npx eslint --fix .")[0], "not-local")
        self.assertEqual(c("cd android && fastlane release")[0], "not-local")
        self.assertEqual(c("flutter build apk --release")[0], "check")
        self.assertEqual(c("pnpm install --frozen-lockfile")[0], "install")
        self.assertEqual(c("flutter pub get")[0], "install")
        self.assertEqual(c("npm install cspell")[0], "install")
        self.assertEqual(c("echo hello")[0], "skip")
        self.assertEqual(c("flutter analyze")[0], "check")

    def test_shell_logic_scripts_are_refused(self):
        lines, why = cc.script_commands("if [ -f x ]; then\n  echo a\nfi\n")
        self.assertIsNone(lines)
        self.assertIn("shell logic", why)
        lines, _ = cc.script_commands("a \\\n  --b\n# comment\n\nc\n")
        self.assertEqual(lines, ["a --b", "c"])

    def test_host_filter(self):
        self.assertEqual(cc.host_filter("flutter build macos && flutter build windows", "darwin"), ("flutter build macos", ["flutter build windows"]))
        self.assertEqual(cc.host_filter("flutter test -d windows", "darwin"), (None, ["flutter test -d windows"]))
        self.assertEqual(cc.host_filter("flutter test", "darwin"), ("flutter test", []))
        self.assertEqual(cc.host_filter("flutter build macos", "linux"), (None, ["flutter build macos"]))


P = cc.FLUTTER_PATH_PREFIX
FLUTTER = {
    ".claude/guild/config.json": stable(  # promote: literal
        {"test": ["flutter test --fail-fast", "scripts/verify.sh r.json"], "lint": ["flutter analyze", "npx cspell '**'"], "typecheck": None,
         "build": ["flutter build macos", "flutter build windows"], "e2e": "flutter test integration_test -d macos", "vrt": None},
        visual={"baselines": ["test/**/goldens/**"], "tests": [], "config_files": ["dart_test.yaml", "has space/x"]},
        engine={"effective": {"copy_ignored": ["lib/env/env.dart", ".claude/x.json", "keys/dev.p12"]}, "irreversible_globs": ["db/**"]}),
    "pubspec.yaml": "name: a\ndependencies:\n  flutter:\n    sdk: flutter\n",
    "pubspec.lock": "# lock\n",
    "package-lock.json": "{}",
    "package.json": "{}",
    ".fvmrc": '{"flutter": "3.47.7"}',
    "dart_test.yaml": "tags: {}\n",
    "test/a_test.dart": "void main() {}\n",
    "test/goldens/x.png": "",
    "scripts/verify.sh": "#!/bin/bash\nbash scripts/helper.sh\n",
    "scripts/helper.sh": "#!/bin/bash\n",
    ".github/workflows/q.yml": fixture("workflow-quality.yml"),
    ".github/actions/install_dependencies/action.yml": fixture("action-install.yml"),
    ".github/workflows/release.yml": "on:\n  push:\n    tags: ['v*']\njobs:\n  r:\n    steps:\n      - run: fastlane release\n",
    "lefthook.yml": fixture("lefthook-prepush.yml"),
    ".claude/agents/qa.md": "# QA\nQA는 결과를 `docs/specs/<issue>/qa-report.md` 파일로 쓴다.\nRead `docs/standards/x.md` only.\n",
    "android/app/build.gradle": "",
    "ios/Podfile": "",
}


class BuildFlutter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rep, _ = convert(FLUTTER, untracked=["android/key.properties", "node_modules/", "build/x/a.pem", "docs/ok.txt"])

    def test_output_is_valid_for_the_engine_loader(self):
        schema.validate(self.cfg, "repo-config")
        repoconfig.RepoConfig(json.loads(json.dumps(self.cfg)))

    def test_stable_commands_are_carried_and_windows_is_dropped(self):
        cmds = self.cfg["commands"]
        self.assertEqual(cmds["test"]["cmd"], P + "flutter test --fail-fast && scripts/verify.sh r.json")
        self.assertEqual(cmds["lint"]["cmd"], P + "flutter analyze && npx cspell '**'")
        self.assertEqual(cmds["build"]["cmd"], P + "flutter build macos")
        self.assertNotIn("typecheck", cmds)
        self.assertNotIn("vrt", cmds)
        names = [e["name"] for e in self.cfg["not_checked_locally"]]
        self.assertIn("build: flutter build windows", names)

    def test_plugin_entries_and_setup(self):
        for p in ("ac-format", "ac-coverage", "verify-gate"):
            self.assertEqual(self.cfg["commands"][p], {"plugin": p})
        self.assertEqual(self.cfg["commands"]["setup"]["cmd"], P + "npm ci && flutter pub get --enforce-lockfile")
        self.assertEqual(list(self.cfg["commands"])[0], "setup")

    def test_ci_and_hook_commands_become_named_commands_once(self):
        cmds = self.cfg["commands"]
        self.assertEqual(cmds["gate-suite"]["cmd"], P + "python3 gates/test_gate.py")    # scope wrapper removed
        self.assertIn("dart format --output=none", cmds["dart-format"]["cmd"])
        self.assertEqual(cmds["check"]["cmd"], P + "python3 tool/check.py --strict")      # from CI, folded scalar
        self.assertEqual(sum(1 for c in cmds.values() if "flutter analyze" in c.get("cmd", "")), 1)   # CI + hook duplicates collapsed
        self.assertNotIn("analyze", cmds)                                                  # ≙ stable lint

    def test_unsafe_ci_steps_are_not_carried(self):
        text = json.dumps(self.cfg)
        self.assertNotIn("update-goldens", text)
        self.assertNotIn("deploy.sh", text)
        self.assertNotIn("fastlane", text)
        nl = {e["name"]: e["note"] for e in self.cfg["not_checked_locally"]}
        self.assertIn("rewrites tracked files", nl["q/lint"])
        self.assertIn("workflow expression", nl["q/lint"])

    def test_non_check_workflows_are_ignored_and_composite_steps_reported(self):
        self.assertTrue(any("release.yml" in w for w in self.rep["ignored_workflows"]))
        self.assertTrue(any("change_project" in s for s in self.rep["prep_steps"]))
        self.assertNotIn("change_project", json.dumps(self.cfg["commands"]))

    def test_toolchain_prepare_and_hosts_and_env(self):
        tp = {e["name"]: e for e in self.cfg["toolchain_prepare"]}
        self.assertEqual(list(tp), ["flutter-sdk", "flutter-precache"])                 # the copy first, then the artifacts of the copy
        # P3-Z decision 4: outside the sandbox only a file copy from the pinned SDK — no command
        self.assertEqual(tp["flutter-sdk"]["sync"], {"from": ["{home}/fvm/versions/3.47.7"], "to": "flutter-sdk"})
        self.assertNotIn("cmd", tp["flutter-sdk"])
        self.assertEqual(tp["flutter-precache"]["cmd"], P + "flutter precache")          # runs inside srt
        self.assertEqual(self.cfg["cache_env"]["GLD_FLUTTER_ROOT"], "{cache}/flutter-sdk")
        self.assertEqual(self.cfg["cache_env"]["GLD_HOME"], "{cache}/home")
        self.assertIn('export HOME="$GLD_HOME"', P)
        self.assertIn("GIT_CONFIG_GLOBAL", P)                                              # git keeps the real user config
        self.assertIn("pub.dev", self.cfg["registry_hosts"])
        self.assertIn("registry.npmjs.org", self.cfg["registry_hosts"])
        self.assertEqual(self.cfg["cache_env"]["PUB_CACHE"], "{cache}/pub")
        self.assertEqual(self.cfg["run_env"]["TURBO_TELEMETRY_DISABLED"], "1")     # job env of an adopted CI command
        self.assertNotIn("TURBO_TELEMETRY_DISABLED", self.cfg["cache_env"])         # cache_env is {cache} paths only (P3-0)
        for v in self.cfg["cache_env"].values():
            self.assertTrue(v.startswith("{cache}"), v)
        self.assertTrue(any(".fvmrc pins Flutter 3.47.7" in d for d in self.rep["decisions"]))

    def test_verification_rules(self):
        rules = [r for r in self.cfg["path_rules"] if r["kind"] == "verification"]
        flat = [g for r in rules for g in r["globs"]]
        self.assertIn("test/**/goldens/**", flat)        # visual.baselines
        self.assertIn("dart_test.yaml", flat)            # visual.config_files
        self.assertNotIn("has space/x", flat)            # not a valid relative glob → refused
        self.assertIn("test/**", flat)                   # by stack, matches a tracked file
        self.assertNotIn("integration_test/**", flat)    # no tracked file matches → not listed
        self.assertIn(".github/workflows/**", flat)
        self.assertIn(".github/actions/**", flat)
        self.assertIn("scripts/verify.sh", flat)         # I11 b: wrapper run by a named command
        self.assertIn("scripts/helper.sh", flat)         # I11 b: and the script it calls
        self.assertIn("pubspec.yaml", flat)
        self.assertFalse([g for g in flat if g.startswith(".claude/")])
        irr = [r for r in self.cfg["path_rules"] if r["kind"] == "irreversible"]
        self.assertEqual(irr[0]["globs"], ["db/**"])

    def test_secrets_and_worktree_prepare(self):
        self.assertTrue(set(["**/.env*", "**/*.pem", ".env*", "*.pem", "*.p12", "*.key"]) <= set(self.cfg["secret_paths"]))
        self.assertIn("**/key.properties", self.cfg["secret_paths"])
        self.assertEqual([e["copy"] for e in self.cfg["worktree_prepare"]], ["lib/env/env.dart", "keys/dev.p12"])
        self.assertTrue(any(".claude/x.json" in w for w in self.rep["warnings"]))     # control-file pattern never copied
        self.assertTrue(any("keys/dev.p12" in w for w in self.rep["warnings"]))       # secret-looking copy flagged
        self.assertNotIn("**/*.pem", self.rep["secrets_found"])                       # build/ is skipped…
        self.assertIn("*.pem", [k for k in self.cfg["secret_paths"]])                 # …but the default stays

    def test_sqlite3_hook_cache_is_copied_only_when_the_checkout_has_it(self):
        files = dict(FLUTTER, **{"pubspec.lock": "packages:\n  sqlite3:\n    dependency: transitive\n"})
        cfg, _, _ = convert(files)
        self.assertNotIn(cc.SQLITE_HOOK_CACHE + "/**", [e["copy"] for e in cfg["worktree_prepare"]])
        cfg, _, _ = convert(files, dirs=[cc.SQLITE_HOOK_CACHE])
        self.assertIn(cc.SQLITE_HOOK_CACHE + "/**", [e["copy"] for e in cfg["worktree_prepare"]])
        cfg, _, _ = convert(dict(FLUTTER, **{"pubspec.lock": "packages:\n  other:\n"}), dirs=[cc.SQLITE_HOOK_CACHE])
        self.assertNotIn(cc.SQLITE_HOOK_CACHE + "/**", [e["copy"] for e in cfg["worktree_prepare"]])

    def test_gradle_hosts_for_android_builds(self):
        cfg, _, _ = convert(dict(FLUTTER, **{".claude/guild/config.json": stable({"build": "flutter build apk"})}))  # promote: literal
        self.assertIn("downloads.gradle.org", cfg["registry_hosts"])

    def test_role_output_candidates(self):
        self.assertEqual(self.rep["role_outputs"], {"qa": ["docs/specs/{issue}/qa-report.md"]})

    def test_deterministic(self):
        again, _, _ = convert(FLUTTER, untracked=["android/key.properties", "node_modules/", "build/x/a.pem", "docs/ok.txt"])
        self.assertEqual(json.dumps(again), json.dumps(self.cfg))
        self.assertEqual(self.cfg["source"]["at"], "2026-11-23T01:02:03Z")


class BuildNode(unittest.TestCase):
    FILES = {
        ".claude/guild/config.json": stable({"test": "pnpm exec turbo run test", "lint": "pnpm lint", "e2e": ["pnpm build:e2e", "pnpm test:e2e"]}),  # promote: literal
        "pnpm-lock.yaml": "", "package.json": "{}", "turbo.json": "{}",
        ".github/workflows/ci.yml": (
            "on:\n  pull_request:\njobs:\n  ci:\n    timeout-minutes: 25\n    env:\n      TURBO_TELEMETRY_DISABLED: \"1\"\n    steps:\n"
            "      - run: pnpm install --frozen-lockfile\n        env:\n          PUPPETEER_SKIP_DOWNLOAD: \"true\"\n"
            "      - run: pnpm exec turbo run test\n      - run: pnpm lint\n      - run: pnpm audit --prod\n"),
    }

    def test_setup_carries_the_ci_install_env(self):
        cfg, rep, _ = convert(self.FILES)
        self.assertEqual(cfg["commands"]["setup"]["cmd"], "export PUPPETEER_SKIP_DOWNLOAD=true; pnpm install --frozen-lockfile")
        self.assertEqual(cfg["registry_hosts"], ["registry.npmjs.org"])
        self.assertNotIn("toolchain_prepare", cfg)
        self.assertEqual(cfg["cache_env"]["npm_config_store_dir"], "{cache}/pnpm-store")

    def test_new_ci_command_gets_a_name_and_timeout(self):
        cfg, _, _ = convert(self.FILES)
        self.assertEqual(cfg["commands"]["audit"]["cmd"], "pnpm audit --prod")
        self.assertNotIn("timeout_min", cfg["commands"]["audit"])        # 25 ≤ default 30
        files = dict(self.FILES, **{".github/workflows/ci.yml": self.FILES[".github/workflows/ci.yml"].replace("25", "45")})
        cfg, _, _ = convert(files)
        self.assertEqual(cfg["commands"]["audit"]["timeout_min"], 45)

    def test_no_lockfile_means_no_setup_and_a_warning(self):
        files = {k: v for k, v in self.FILES.items() if k != "pnpm-lock.yaml"}
        cfg, rep, _ = convert(files)
        self.assertNotIn("setup", cfg["commands"])
        self.assertTrue(any("no lockfile" in w for w in rep["warnings"]))

    def test_missing_stable_config_stops(self):
        with self.assertRaises(SystemExit):
            convert({"package.json": "{}"})

    def test_unparsable_workflow_is_reported_not_guessed(self):
        files = dict(self.FILES, **{".github/workflows/bad.yml": "jobs: [1, 2\n"})
        cfg, rep, _ = convert(files)
        self.assertTrue(any("bad.yml" in w for w in rep["warnings"]))


class TemplateAdaptation(unittest.TestCase):
    TEMPLATE = json.dumps({"format": 1, "template": "feature", "version": "t1", "steps": [
        {"id": "design", "role": "tech-lead", "outputs": ["docs/specs/{issue}/design.md"]},
        {"id": "setup", "run": "setup"},
        {"id": "developer", "role": "developer"},
        {"id": "test", "run": "test", "on_fail": {"back_to": "developer", "max": 3}},
        {"id": "review", "role": "auditor", "outputs": ["docs/specs/{issue}/review.md"]},
        {"id": "typecheck", "run": "typecheck"},
    ]})

    @staticmethod
    def _read(*parts):
        with open(os.path.join(ENGINE, *parts), encoding="utf-8") as f:
            return f.read()

    @property
    def PLUGIN_TEMPLATE(self):
        # the stage-2 view (the data file is also the stage-3 source, instructions.load_default_template)
        from gxengine import instructions
        return json.dumps(instructions.load_default_template("feature", stage=2), indent=2)

    def test_the_raw_stage3_file_is_refused_for_the_stage2_proposal(self):
        """V4 made data/templates/feature.json the stage-3 source too: read raw, a stage-2 check refuses it."""
        _, rep, tpl = convert(FLUTTER, template=self._read("data", "templates", "feature.json"))
        self.assertIsNone(tpl)
        self.assertTrue(any("create-followups" in w for w in rep["warnings"]))

    def test_the_plugin_template_is_adapted_per_repository(self):
        cfg, rep, tpl = convert(FLUTTER, template=self.PLUGIN_TEMPLATE)
        ids = [s["id"] for s in tpl["steps"]]
        runs = [s["run"] for s in tpl["steps"] if "run" in s]
        self.assertNotIn("typecheck", ids, "the repository has no typecheck command → the step is removed")
        self.assertTrue(any("`typecheck`" in d and "removed" in d for d in rep["decisions"]))
        self.assertTrue(set(runs) <= set(cfg["commands"]), "every run name is a named command (U15)")
        i = ids.index("e2e")
        extra = [n for n in cfg["commands"] if n not in runs and n not in ("ac-format",)]
        self.assertEqual(extra, [], "every verification command has a run step")
        self.assertIn("gate-suite", ids[i + 1:ids.index("review-design")])      # CI-derived checks after the runs
        self.assertEqual(tpl["steps"][ids.index("gate-suite")]["on_fail"], {"back_to": "implement", "max": 2})
        self.assertEqual(ids[-3:], ["verify-gate", "done-gate", "pr"])
        from gxengine import procedure as PR
        PR.build(PR.parse_template(json.dumps(instructions.load_start_procedure(stage=2)), stage=2),
                 PR.parse_template(json.dumps(tpl), stage=2), 42, list(cfg["commands"]), stage=2)

    def test_moved_commands_leave_commands_and_template(self):
        cfg, rep, tpl = convert(FLUTTER, template=self.PLUGIN_TEMPLATE,
                                moved={"build": "Xcode cannot reach XPC services in srt", "e2e": "needs a device"})
        self.assertNotIn("build", cfg["commands"])
        self.assertNotIn("e2e", cfg["commands"])
        self.assertNotIn("build", [s["id"] for s in tpl["steps"]])
        nl = {e["name"]: e["note"] for e in cfg["not_checked_locally"]}
        self.assertIn("Xcode cannot reach XPC services in srt", nl["build"])
        self.assertIn("human decision", nl["e2e"])
        self.assertTrue(any("moved to not_checked_locally" in d for d in rep["decisions"]))
        flat = [g for r in cfg["path_rules"] if r["kind"] == "verification" for g in r["globs"]]
        self.assertIn("pubspec.yaml", flat)
        with self.assertRaises(SystemExit):
            convert(FLUTTER, moved={"nope": "x"})
        with self.assertRaises(SystemExit):
            convert(FLUTTER, moved={"verify-gate": "x"})

    def test_a_template_the_engine_refuses_is_not_proposed(self):
        _, rep, tpl = convert(FLUTTER, template=self.TEMPLATE)    # no create-pr, judge outputs etc.
        self.assertIsNone(tpl)
        self.assertTrue(any("refused by the engine's checker" in w for w in rep["warnings"]))

    def test_no_template_no_procedure(self):
        _, _, tpl = convert(FLUTTER)
        self.assertIsNone(tpl)


@unittest.skipUnless(os.path.isdir(os.path.join(ENGINE, "tools", "out")),
                     "tools/out holds the development channel's validation records — a promoted tree leaves them out (R4-6)")
class Proposals(unittest.TestCase):
    """tools/out/<repo>/: the three proposals load, render and build into a stage-2 procedure (U15/U16, V10)."""

    OUT = os.path.join(ENGINE, "tools", "out")

    def repos(self):
        return sorted(d for d in os.listdir(self.OUT) if os.path.isfile(os.path.join(self.OUT, d, "config.json")))

    def load(self, *parts):
        with open(os.path.join(self.OUT, *parts), encoding="utf-8") as f:
            return f.read()

    def test_three_proposals(self):
        self.assertEqual(self.repos(), ["app-b", "app-c", "app_a"])         # the three validation repositories, renamed (R4-6)

    def test_every_template_run_is_a_named_command_and_the_procedure_builds(self):
        from gxengine import procedure as PR
        start = json.dumps(instructions.load_start_procedure(stage=2))     # the stage-2 view (readiness E4)
        for repo in self.repos():
            with self.subTest(repo=repo):
                cfg = repoconfig.RepoConfig.from_text(self.load(repo, "config.json"))
                tpl = self.load(repo, "procedures", "feature.yaml")
                runs = [s["run"] for s in json.loads(tpl)["steps"] if "run" in s]
                self.assertTrue(set(runs) <= set(cfg.command_names()))
                verification = [n for n in cfg.command_names() if n not in ("ac-format",)]
                self.assertEqual(sorted(set(verification) - set(runs)), [], "a named command without a run step")
                # stage 2: the repository copy ends with the leader's done-gate right before the PR (D19);
                # dicts, not text — build parses text at stage 1
                tpl_raw = PR.parse_template(tpl, stage=2)
                PR.build(PR.parse_template(start, stage=2), tpl_raw, 42, cfg.command_names(), stage=2)
                ids = [s["id"] for s in tpl_raw["steps"]]
                self.assertEqual(ids[-3:], ["verify-gate", "done-gate", "pr"])
                for v in (cfg.raw.get("cache_env") or {}).values():
                    self.assertTrue(v.startswith("{cache}"), (repo, v))

    def test_candidate_copies_use_the_token_and_render(self):
        from gxengine import canary, render
        import tempfile as _t
        for repo, name in [(r, n) for r in self.repos()
                           for n in ("config.json", "config.with-candidate-exceptions.json")]:
            path = os.path.join(self.OUT, repo, name)
            if not os.path.exists(path):
                continue
            with self.subTest(repo=repo, file=name):
                text = self.load(repo, name)
                self.assertNotIn("/var/folders", text)
                raw = json.loads(text)
                repoconfig.RepoConfig(raw)
                root = os.path.realpath(_t.mkdtemp(prefix="gx-cc-", dir="/tmp"))
                try:
                    paths, _ = canary.canary_layout(root + "/l")
                    os.makedirs(root + "/ut")
                    paths.pop("in_dir")
                    inp = render.RenderInput(kind="run", role="developer", role_class="work", step="test", attempt=1,
                                             issue=1, outputs=[], paths=dict(paths, user_tmp=root + "/ut"), config=raw,
                                             command=raw["commands"]["test"]["cmd"], bash_timeout_ms=1800000)
                    srt = render.render_srt(inp)
                    render.render_env(inp, {"PATH": "/usr/bin:/bin", "HOME": paths["home"]})
                    exc = raw.get("sandbox_exceptions") or {}
                    if exc.get("allow_local_binding"):
                        self.assertIs(srt["network"]["allowLocalBinding"], True)
                    else:
                        self.assertNotIn("allowLocalBinding", srt["network"])
                    if "{user_tmp}" in exc.get("allow_write", []):
                        self.assertIn(root + "/ut", srt["filesystem"]["allowWrite"])
                finally:
                    import shutil as _s
                    _s.rmtree(root, True)
                    _s.rmtree(paths["srt_tmpdir"], True)

    def test_final_commit_trees(self):
        """CFG: the tree a human copies (commit/.claude/guild/) is the proposal itself; approved
        exceptions only with a note; every quarantined test is excluded by a command; no secrets."""
        secretish = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|sk-ant-|AKIA[0-9A-Z]{16}|-----BEGIN|xox[bap]-|AIza[0-9A-Za-z_-]{30,})")
        for repo in self.repos():
            with self.subTest(repo=repo):
                commit = os.path.join(repo, "commit", ".claude", "guild")
                self.assertEqual(self.load(commit, "config.json"), self.load(repo, "config.json"))
                self.assertEqual(self.load(commit, "procedures", "feature.yaml"), self.load(repo, "procedures", "feature.yaml"))
                files = sorted(os.path.relpath(os.path.join(d, f), os.path.join(self.OUT, repo, "commit"))
                               for d, _, fs in os.walk(os.path.join(self.OUT, repo, "commit")) for f in fs)
                self.assertEqual(files, [".claude/guild/config.json", ".claude/guild/procedures/feature.yaml",
                                         ".claude/guild/roles/leader.md"])
                from gxengine import instructions
                self.assertEqual(self.load(commit, "roles", "leader.md"), instructions.default_role_file("leader"))
                self.assertFalse(os.path.exists(os.path.join(self.OUT, repo, cc.CANDIDATE_OUT)), "what-if copies are gone")
                text = self.load(repo, "config.json")
                self.assertIsNone(secretish.search(text))
                self.assertNotIn("/var/folders", text)
                raw = json.loads(text)
                exc = raw.get("sandbox_exceptions")
                if exc:
                    self.assertTrue(exc["note"].startswith("approved 2026-11-23"), exc["note"])
                cmds = "\n".join(c.get("cmd", "") for c in raw["commands"].values())
                for q in raw.get("quarantine", []):
                    self.assertIn(q["test"], cmds)
                    self.assertEqual(set(q), {"test", "note", "added"})
                with open(os.path.join(ENGINE, "tools", "decisions", repo + ".json"), encoding="utf-8") as f:
                    d = cc.load_decisions(f.read())
                self.assertEqual(raw.get("sandbox_exceptions"), d.get("sandbox_exceptions"))
                self.assertEqual(raw.get("quarantine"), d.get("quarantine"))
                for name in d.get("not_checked_locally") or {}:
                    self.assertNotIn(name, raw["commands"])
                runs = [s["run"] for s in json.loads(self.load(repo, "procedures", "feature.yaml"))["steps"] if "run" in s]
                self.assertFalse(set(d.get("not_checked_locally") or {}) & set(runs))

    def test_final_base_green_records_are_of_these_exact_files(self):
        """CFG 5: base-check-final ran THIS config.json (sha256), without what-if, and every command is green."""
        import hashlib
        for repo in self.repos():
            with self.subTest(repo=repo):
                rec = json.loads(self.load(repo, "base-check-final", "base-check.json"))
                with open(os.path.join(self.OUT, repo, "config.json"), "rb") as f:
                    self.assertEqual(rec["config_sha256"], hashlib.sha256(f.read()).hexdigest())
                self.assertIs(rec["what_if"], False)
                raw = json.loads(self.load(repo, "config.json"))
                ran = {r["name"]: r for r in rec["results"] if "skipped" not in r}
                want = {n for n, c in raw["commands"].items() if "cmd" in c}
                self.assertEqual(want - set(ran), set(), "a command the final check did not run")
                self.assertEqual([n for n, r in ran.items() if not r["ok"]], [])


class CandidateExceptions(unittest.TestCase):
    def test_user_tmp_is_the_token_and_the_copy_validates(self):
        cfg, _, _ = convert(FLUTTER)
        cand = cc.candidate_config(cfg, ["local-binding", "weaker-network", "user-tmp"])
        exc = cand["sandbox_exceptions"]
        self.assertEqual(exc["allow_write"], ["{user_tmp}"])
        self.assertIs(exc["allow_local_binding"], True)
        self.assertIs(exc["weaker_network_isolation"], True)
        self.assertNotIn("/var/folders", json.dumps(cand))
        self.assertNotIn("sandbox_exceptions", cfg, "the strict proposal stays without exceptions")
        with self.assertRaises(SystemExit):
            cc.candidate_config(cfg, ["open-everything"])

    def test_run_env_refusals(self):
        self.assertIsNone(cc.run_env_refusal("TURBO_TELEMETRY_DISABLED", "1"))
        for name, value in (("NPM_TOKEN", "x"), ("PATH", "/x"), ("GITHUB_SHA", "x"), ("lower", "1"),
                            ("CACHE_DIR", "/Users/x/.cache"), ("X", "$HOME/x"), ("Y", "{cache}")):
            with self.subTest(name=name):
                self.assertIsNotNone(cc.run_env_refusal(name, value))


EXC = {"weaker_network_isolation": True, "allow_local_binding": True, "allow_write": ["{user_tmp}"],
       "note": "approved 2026-11-23: measured need, BASE_GREEN.md"}
QCMD = "flutter test --fail-fast $(find test -name '*_test.dart' ! -path test/a_test.dart | sort)"


def decisions(**over):
    d = {"repo": "repo", "sandbox_exceptions": EXC, "not_checked_locally": {"build": "Xcode in srt"},
         "commands": {"test": {"cmd": QCMD, "why": "quarantine exclusion"}},
         "quarantine": [{"test": "test/a_test.dart", "note": "sandbox only", "added": "2026-11-23"}]}
    d.update(over)
    return d


class HumanDecisions(unittest.TestCase):
    """--decisions (CFG): approved exceptions, moved commands, command texts, quarantine — fail-closed."""

    def build(self, **over):
        d = cc.load_decisions(json.dumps(decisions(**over)))
        return convert(FLUTTER, moved=d["not_checked_locally"], decisions=d)

    def test_applied(self):
        cfg, rep, _ = self.build()
        self.assertEqual(cfg["sandbox_exceptions"], EXC)
        self.assertEqual(cfg["commands"]["test"]["cmd"], P + QCMD, "a human command text also gets the Flutter prefix")
        self.assertIn("human decision: quarantine exclusion", cfg["commands"]["test"]["description"])
        self.assertEqual(cfg["quarantine"], [{"test": "test/a_test.dart", "note": "sandbox only", "added": "2026-11-23"}])
        self.assertNotIn("build", cfg["commands"])
        repoconfig.RepoConfig(json.loads(json.dumps(cfg)))
        self.assertTrue(any("approved sandbox exceptions" in x for x in rep["decisions"]))

    def test_quarantine_must_be_excluded_by_a_command_and_tracked(self):
        with self.assertRaises(SystemExit):
            self.build(commands={})                                     # no command names the test
        with self.assertRaises(SystemExit):
            self.build(quarantine=[{"test": "test/gone_test.dart", "note": "n", "added": "2026-11-23"}],
                       commands={"test": {"cmd": "flutter test ! -path test/gone_test.dart", "why": "w"}})

    def test_unknown_command_is_refused(self):
        with self.assertRaises(SystemExit):
            self.build(commands={"nope": {"cmd": "x", "why": "y"}})
        with self.assertRaises(SystemExit):
            self.build(commands={"verify-gate": {"cmd": "x", "why": "y"}})

    def test_loader_refusals(self):
        bad = [{"extra": 1}, {"sandbox_exceptions": {"allow_local_binding": True}},
               {"not_checked_locally": {"e2e": " "}}, {"commands": {"test": {"cmd": "x"}}},
               {"quarantine": [{"test": "t", "note": "n"}]},
               {"sandbox_exceptions": {"allow_write": ["/private/var/folders/ab/T"], "note": "n"}}]
        for d in bad:
            with self.subTest(d=d), self.assertRaises(SystemExit):
                cc.load_decisions(json.dumps(d))
        with self.assertRaises(SystemExit):
            cc.load_decisions("{not json")

    def test_command_line_writes_the_commit_tree_and_drops_a_stale_candidate_copy(self):
        import contextlib, io
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            for rel, text in FLUTTER.items():
                full = os.path.join(repo, rel)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(text)
            dpath, out = os.path.join(tmp, "d.json"), os.path.join(tmp, "out")
            with open(dpath, "w", encoding="utf-8") as f:
                json.dump(decisions(), f)
            os.makedirs(os.path.join(out, "commit", "stale"))
            with open(os.path.join(out, cc.CANDIDATE_OUT), "w") as f:
                f.write("{}")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cc.main(["--repo-root", repo, "--out", out, "--host-os", "darwin", "--decisions", dpath]), 0)
            def read(*p):
                with open(os.path.join(out, *p), encoding="utf-8") as f:
                    return f.read()
            self.assertEqual(read("commit", ".claude", "guild", "config.json"), read("config.json"))
            self.assertEqual(read("commit", ".claude", "guild", "procedures", "feature.yaml"), read("procedures", "feature.yaml"))
            self.assertEqual(sorted(os.listdir(os.path.join(out, "commit"))), [".claude"], "the commit tree is re-made")
            self.assertFalse(os.path.exists(os.path.join(out, cc.CANDIDATE_OUT)))
            self.assertIn("## Quarantine", read("report.md"))
            self.assertIn("test/a_test.dart", read("report.md"))
            with open(dpath, "w", encoding="utf-8") as f:
                json.dump(decisions(repo="other"), f)
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                cc.main(["--repo-root", repo, "--out", out, "--host-os", "darwin", "--decisions", dpath])


class CommandLine(unittest.TestCase):
    def test_writes_only_to_out_and_never_into_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            for rel, text in FLUTTER.items():
                full = os.path.join(repo, rel)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(text)
            before = sorted(cc.FsSource(repo).files())
            out = os.path.join(tmp, "out")
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cc.main(["--repo-root", repo, "--out", out, "--host-os", "darwin"]), 0)
            self.assertEqual(sorted(cc.FsSource(repo).files()), before)
            with open(os.path.join(out, "config.json"), encoding="utf-8") as f:
                schema.validate(json.load(f), "repo-config")
            self.assertTrue(os.path.isfile(os.path.join(out, "report.md")))

    def test_refuses_the_stable_folder_and_git_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in (".claude/guild", ".claude/guild/sub", ".git/x"):  # promote: literal
                with self.assertRaises(SystemExit, msg=bad):
                    cc.refuse_unsafe_out(tmp, os.path.join(tmp, bad))
            own = os.path.join(tmp, ".claude", "guild")                            # this channel's settings folder
            if own == os.path.join(tmp, ".claude", "guild"):  # promote: literal — the stable channel: the 0.98.x folder itself
                with self.assertRaises(SystemExit):
                    cc.refuse_unsafe_out(tmp, own)
            else:
                cc.refuse_unsafe_out(tmp, own)                                          # the new edition's folder is fine

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(os.path.join(repo, ".claude", "guild"))  # promote: literal
            with open(os.path.join(repo, ".claude", "guild", "config.json"), "w", encoding="utf-8") as f:  # promote: literal
                f.write(stable({"test": "make test"}))
            out = os.path.join(tmp, "out")
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                cc.main(["--repo-root", repo, "--out", out, "--dry-run"])
            self.assertFalse(os.path.exists(out))
            self.assertIn('"make test"', buf.getvalue())


class FromGitRevision(unittest.TestCase):
    def test_ignored_generated_files_of_the_main_checkout_are_seen(self):
        files = {".claude/guild/config.json": stable({"test": "flutter test"}), "pubspec.yaml": "dependencies:\n  flutter:\n    sdk: flutter\n",  # promote: literal
                 "pubspec.lock": "packages:\n  sqlite3:\n    dependency: transitive\n", ".gitignore": ".dart_tool/\n"}
        with tempfile.TemporaryDirectory() as tmp:
            repo = GitRepo.create(tmp, files=files, with_remote=False)
            repo.write(cc.SQLITE_HOOK_CACHE + "/build/download-1/libsqlite3.dylib", "bin")
            cfg, _, _ = cc.build(cc.GitSource(repo.path, "main"), host_os="darwin", now=NOW)
        self.assertIn(cc.SQLITE_HOOK_CACHE + "/**", [e["copy"] for e in cfg["worktree_prepare"]])

    def test_reads_the_revision_blobs_not_the_working_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = GitRepo.create(tmp, files={".claude/guild/config.json": stable({"test": "make base"}), "Makefile": "test:\n"}, with_remote=False)  # promote: literal
            repo.write(".claude/guild/config.json", stable({"test": "make dirty"}))            # uncommitted edit  # promote: literal
            repo.write("android/key.properties", "x=1\n")                                       # untracked credential
            src = cc.GitSource(repo.path, "main")
            cfg, _, _ = cc.build(src, host_os="darwin", now=NOW)
            self.assertEqual(cfg["commands"]["test"]["cmd"], "make base")
            self.assertIn("**/key.properties", cfg["secret_paths"])
            self.assertIn("main", cfg["source"]["converted_from"])
            self.assertEqual(repo.git("status", "--porcelain", "--untracked-files=all").count("\n") + 1, 2)   # repo untouched by the run


_bc_spec = importlib.util.spec_from_file_location("base_check", os.path.join(ENGINE, "tools", "base_check.py"))
bc = importlib.util.module_from_spec(_bc_spec)
_bc_spec.loader.exec_module(bc)


class BaseCheckShell(unittest.TestCase):
    """tools/base_check.py is a thin shell around gxengine.basecheck (VB1, tests/test_basecheck.py)."""

    def args(self, root, **over):
        return argparse.Namespace(**dict(dict(repo_root=root, rev="main", config=os.path.join(root, "c.json"), srt="/x/srt",
                                              work=os.path.join(os.path.expanduser("~"), "gx-none"), out=os.path.join(root, "out"),
                                              name="r", prepare_from=None, override=None, exception=None, keep_cache=False), **over))

    def test_work_folder_under_a_temp_area_is_refused(self):
        for work in ("/private/tmp/base", "/tmp/base", "/var/folders/x/base"):
            with self.assertRaises(SystemExit):
                bc.check(self.args("/x", work=work))

    def test_what_if(self):
        raw = {"format": 1, "commands": {"test": {"cmd": "a"}, "verify-gate": {"plugin": "verify-gate"}}}
        got, notes = bc.what_if(raw, ["test=b"], ["local-binding", "user-tmp", "host:x.example"])
        self.assertEqual(got["commands"]["test"]["cmd"], "b")
        self.assertEqual(got["sandbox_exceptions"], {"allow_local_binding": True, "allow_write": ["{user_tmp}"],
                                                     "allow_hosts": ["x.example"]})
        self.assertEqual((len(notes), raw["commands"]["test"]["cmd"]), (4, "a"))
        for ov, ex in ((["none=x"], None), (["test="], None), (["verify-gate=x"], None), (None, ["no-sandbox"])):
            with self.assertRaises(SystemExit):
                bc.what_if(raw, ov, ex)

    def test_it_runs_the_engines_check_in_a_scratch_home_and_reports(self):
        from gxengine import basecheck
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="gx-bct-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = GitRepo.create(tmp, name="r", with_remote=False)
        cfg = {"format": 1, "commands": {"test": {"cmd": "make test"}, "lint": {"cmd": "make lint"}}}
        with open(os.path.join(repo.path, "c.json"), "w") as f:
            json.dump(cfg, f)
        seen = []

        def run(request, record, prepare_from=None, only=None):
            seen.append((request, prepare_from))
            logs = record[:-len(".json")] + ".logs/run-1"
            os.makedirs(logs)
            with open(os.path.join(logs, "test.log"), "w") as f:
                f.write("boom\n")

            class Chk:
                red, flaky = ["test"], []
                commands = [{"name": "test", "ok": False, "dirty_files": [], "runs": [
                    {"exit_code": 2, "timed_out": False, "duration_s": 1.5, "log_file": "run-1/test.log"}]},
                            {"name": "lint", "ok": True, "dirty_files": [], "runs": [
                                {"exit_code": 0, "timed_out": False, "duration_s": 1, "log_file": "run-1/lint.log"}]}]
            return Chk, None
        with mock.patch.object(basecheck, "_run", run), mock.patch.object(bc, "refuse_work"), mock.patch("builtins.print"):
            s = bc.check(self.args(repo.path, work=os.path.join(tmp, "work"), prepare_from="/somewhere"))
        req, prep = seen[0]
        self.assertEqual((req.sha, req.force, prep), (repo.head(), True, "/somewhere"))
        self.assertEqual(req.engine_home, os.path.join(tmp, "work", "r", "engine"))
        self.assertFalse(os.path.exists(os.path.join(tmp, "work", "r")), "the scratch home is removed")
        self.assertEqual((s["ok"], s["red"], s["what_if"]), (False, ["test"], False))
        with open(os.path.join(repo.path, "out", "base-check.md")) as f:
            md = f.read()
        self.assertIn("| `test` | **RED (rc=2)** | 1.5 |", md)
        self.assertIn("boom", md)
        with open(os.path.join(repo.path, "out", "logs", "test.log")) as f:
            self.assertEqual(f.read(), "boom\n")

    def test_report_marks_red_green_dirty_flaky_and_problem(self):
        md = bc.render_md({"repo": "r", "base": "a" * 40, "rev": "main", "srt": "srt", "host": "darwin", "seconds": 1.0, "notes": ["n1"],
                           "problem": "prepare", "results": [
                               {"name": "setup", "cmd": "x", "rc": 0, "seconds": 2, "timed_out": False, "dirty": [], "ok": True, "flaky": True, "tail": "t"},
                               {"name": "test", "cmd": "y", "rc": 1, "seconds": 3, "timed_out": False, "dirty": ["a"], "ok": False, "flaky": False, "tail": "boom"},
                               {"name": "lint", "cmd": "z", "skipped": "not run (setup was red)"}]})
        self.assertIn("**green** | 2 | flaky", md)
        self.assertIn("**RED (rc=1)** + run-dirty-tree", md)
        self.assertIn("| `lint` | skipped", md)
        self.assertIn("`prepare`", md)
        self.assertIn("n1", md)


if __name__ == "__main__":
    unittest.main()


# --- stage 3 (V19) -------------------------------------------------------------------------

FLUTTER3 = dict(FLUTTER, **{
    "test/helpers/fake_clock.dart": "class FakeClock {}\n",
    "integration_test/app_test.dart": "void main() {}\n",
    "lib/auth/session_store.dart": "class S {}\n",
    "lib/services/google_sign_in_button.dart": "class B {}\n",
    "lib/db/schema.dart": "class Schema {}\n",
    "supabase/migrations/0001_init.sql": "create table x();\n",
    "lib/author_name.dart": "class A {}\n",
    ".claude/agents/designer.md": "# d\n", ".claude/agents/security.md": "# s\n",
})


def convert3(files, decisions=None, moved=None):
    return cc.build(MemSource(files), host_os="darwin", now=NOW, moved_not_local=moved, decisions=decisions, stage=3)


class Stage3(unittest.TestCase):
    """V19 (stage-3 scope §3): `--stage 3` proposes the stage-3 settings; stage 2 is unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rep, _ = convert3(FLUTTER3, decisions={"stage3": {"note": "test", "followups_dry_run": True,
                                                                        "safety_net_globs": ["test/tool/ci_*_wiring_test.dart"]}})
        cls.rules = {}
        for r in cls.cfg["path_rules"]:
            cls.rules.setdefault(r["kind"], []).append(r)

    def test_valid_for_the_engine_loader(self):
        repoconfig.RepoConfig(json.loads(json.dumps(self.cfg)))
        schema.validate(self.cfg, "repo-config")

    def test_stage2_output_is_unchanged(self):
        two, rep2, _ = convert(FLUTTER3)
        self.assertEqual([n for n in two["commands"] if "plugin" in two["commands"][n]], list(cc.PLUGIN_COMMANDS))
        self.assertEqual({r["kind"] for r in two["path_rules"]}, {"verification", "irreversible"})
        self.assertFalse(any("category" in r for r in two["path_rules"] if r["kind"] == "verification"))
        self.assertNotIn("followups_dry_run", two)
        self.assertNotIn("stage3", rep2)
        self.assertTrue(any("stage 3" in d for d in rep2["decisions"]))

    def test_plugin_commands_of_stage3(self):
        plugins = [n for n, c in self.cfg["commands"].items() if "plugin" in c]
        self.assertEqual(plugins, list(cc.PLUGIN_COMMANDS + cc.STAGE3_PLUGIN_COMMANDS))
        for n in cc.STAGE3_PLUGIN_COMMANDS:
            self.assertEqual(self.cfg["commands"][n], {"plugin": n})

    def test_verification_categories(self):
        cats = {r["category"]: r["globs"] for r in self.rules["verification"]}
        self.assertTrue(all("category" in r for r in self.rules["verification"]))
        self.assertEqual(cats["golden"], ["test/**/goldens/**"])                       # visual.baselines
        self.assertEqual(cats["comparison-config"], ["dart_test.yaml"])                 # visual.config_files (bad glob dropped)
        self.assertIn(".github/workflows/**", cats["ci"])
        self.assertIn("test/**", cats["test"])
        self.assertIn("scripts/verify.sh", cats["runner"])

    def test_test_code_is_test_source_only(self):
        (rule,) = self.rules["test-code"]
        self.assertEqual(rule["globs"], ["**/*_test.dart", "integration_test/**/*.dart", "test/**/*.dart"])
        from gxengine import globs as G
        self.assertFalse(any(G.match(g, "test/goldens/x.png") for g in rule["globs"]), "never a golden")
        self.assertTrue(any(G.match(g, "test/helpers/fake_clock.dart") for g in rule["globs"]))

    def test_safety_net_names_and_the_decision(self):
        (rule,) = self.rules["safety-net"]
        self.assertEqual(rule["globs"], ["**/*_safety_net_test.dart", "test/tool/ci_*_wiring_test.dart"])
        self.assertIn("decision: test", rule["note"])

    def test_risk_candidates(self):
        by_area = {r["area"]: r for r in self.rules["risk"]}
        self.assertEqual(by_area["security"]["gate"], "security-review")
        self.assertEqual(by_area["security"]["globs"], ["lib/auth/**", "lib/services/google_sign_in_button.dart"])
        self.assertNotIn("lib/author_name.dart", by_area["security"]["globs"], "whole tokens only")
        self.assertEqual(by_area["data-migration"]["gate"], "data-review")
        self.assertEqual(by_area["data-migration"]["globs"], ["lib/db/schema.dart", "supabase/migrations/**"])
        for r in self.rules["risk"]:
            self.assertTrue(r["note"].startswith("CANDIDATE"))
            self.assertFalse([g for g in r["globs"] if g.startswith(("test/", "docs/", ".claude/"))])

    def test_irreversible_candidates(self):
        by_cat = {}
        for r in self.rules["irreversible"]:
            by_cat.setdefault(r["category"], []).extend(r["globs"])
        self.assertEqual(by_cat["hard-to-revert"], ["db/**", "lib/db/schema.dart"])     # 0.98.7 + schema code
        self.assertIn(".github/workflows/release.yml", by_cat["external-side-effect"])
        self.assertNotIn(".github/workflows/q.yml", by_cat["external-side-effect"])
        self.assertEqual(by_cat["human-executed"], ["supabase/migrations/**"])

    def test_dry_run_switch_and_catalog_roles(self):
        self.assertIs(self.cfg["followups_dry_run"], True)
        no, _, _ = convert3(FLUTTER3)
        self.assertNotIn("followups_dry_run", no, "absent = real follow-ups (A4 default)")
        roles = self.rep["catalog_roles"]
        self.assertEqual(roles["designer"], True)
        self.assertEqual(roles["product-owner"], False)
        self.assertTrue(any("product-owner" in w for w in self.rep["warnings"]))
        self.assertNotIn("developer", roles)

    def test_decision_refusals(self):
        for bad in ({"stage3": {"followups_dry_run": True}},                       # no note
                    {"stage3": {"note": "x", "other": 1}},
                    {"stage3": {"note": "x", "followups_dry_run": "yes"}},
                    {"stage3": {"note": "x", "safety_net_globs": ["/abs"]}}):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                cc.load_decisions(json.dumps(bad))
        cc.load_decisions(json.dumps({"stage3": {"note": "x", "followups_dry_run": False, "safety_net_globs": []}}))


FLUTTER3R = dict(FLUTTER3, **{
    "lib/env/env_test.dart": "class ENV {}\n",                     # a production file with a test-like name
    "lib/services/api_service.dart": "class Api {}\n",
    "android/fastlane/Fastfile": "lane :release do\nend\n",
    "test/fixtures/list-baseline.json": "{}\n",
})


def _review(**fields):
    return {"stage3": {"note": "test", "review": dict({"note": "reviewer, 2026-11-25"}, **fields)}}


class Stage3Review(unittest.TestCase):
    """V19 Q5: decisions `stage3.review` — a human judges every stage-3 candidate (exclude / kept / include)."""

    FULL = _review(
        exclude=[{"kind": "risk", "area": "security", "glob": "lib/services/google_sign_in_button.dart", "why": "UI only"},
                 {"kind": "test-code", "glob": "**/*_test.dart", "why": "matches lib/env/env_test.dart"},
                 {"kind": "safety-net", "glob": "**/*_safety_net_test.dart", "why": "outside test/ never runs"}],
        kept=[{"kind": "risk", "area": "security", "glob": "lib/auth/**", "why": "session store"},
              {"kind": "risk", "area": "data-migration", "glob": "lib/db/schema.dart", "why": "schema"},
              {"kind": "risk", "area": "data-migration", "glob": "supabase/migrations/**", "why": "migrations"},
              {"kind": "irreversible", "category": "external-side-effect", "glob": ".github/workflows/release.yml", "why": "tag release"},
              {"kind": "irreversible", "category": "human-executed", "glob": "supabase/migrations/**", "why": "run by hand"},
              {"kind": "irreversible", "category": "hard-to-revert", "glob": "lib/db/schema.dart", "why": "schema"},
              {"kind": "test-code", "glob": "integration_test/**/*.dart", "why": "tests"},
              {"kind": "test-code", "glob": "test/**/*.dart", "why": "tests and helpers"}],
        include=[{"kind": "risk", "area": "security", "glob": "lib/services/api_service.dart", "why": "API key"},
                 {"kind": "irreversible", "category": "external-side-effect", "glob": "android/fastlane/**", "why": "store upload"},
                 {"kind": "safety-net", "glob": "test/**/*_safety_net_test.dart", "why": "inside test/"},
                 {"kind": "verification", "category": "golden", "glob": "test/fixtures/*-baseline.json", "why": "structure baseline"}])

    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.rep, _ = convert3(FLUTTER3R, decisions=cls.FULL)
        cls.rules = {}
        for r in cls.cfg["path_rules"]:
            cls.rules.setdefault((r["kind"], r.get("area") or r.get("category")), []).append(r)

    def globs(self, kind, label=None):
        return [g for r in self.rules.get((kind, label), []) for g in r["globs"]]

    def test_valid_for_the_engine_loader(self):
        repoconfig.RepoConfig(json.loads(json.dumps(self.cfg)))
        schema.validate(self.cfg, "repo-config")

    def test_exclude_kept_include(self):
        self.assertEqual(self.globs("risk", "security"), ["lib/auth/**", "lib/services/api_service.dart"])
        self.assertEqual(self.globs("irreversible", "external-side-effect"), [".github/workflows/release.yml", "android/fastlane/**"])
        self.assertEqual(self.globs("test-code"), ["integration_test/**/*.dart", "test/**/*.dart"])
        self.assertNotIn("**/*_test.dart", self.globs("test-code"))
        self.assertEqual(self.globs("safety-net"), ["test/**/*_safety_net_test.dart"],
                         "a derived name is judged even when the test-code glob it follows is excluded")
        for r in self.cfg["path_rules"]:
            if r["kind"] in ("risk", "irreversible") and r.get("note") != "0.98.7 engine.irreversible_globs":
                self.assertTrue(r["note"].startswith("REVIEWED"), r)
        self.assertEqual(self.rep["stage3"]["review"]["unreviewed"], [])
        verdicts = {(r["kind"], r["glob"]): r["verdict"] for r in self.rep["stage3"]["review"]["rows"]}
        self.assertEqual(verdicts[("risk", "lib/services/google_sign_in_button.dart")], "excluded")
        self.assertEqual(verdicts[("risk", "lib/auth/**")], "kept")
        self.assertEqual(verdicts[("risk", "lib/services/api_service.dart")], "included")

    def test_verification_include_is_a_categorised_rule(self):
        (rule,) = self.rules[("verification", "golden")][1:]
        self.assertEqual(rule["globs"], ["test/fixtures/*-baseline.json"])
        cfg = repoconfig.RepoConfig(json.loads(json.dumps(self.cfg)))
        self.assertEqual(cfg.verification_category("test/fixtures/list-baseline.json"), "golden")

    def test_report_lists_every_judgment(self):
        md = cc.render_report_stage3("x", self.cfg, self.rep, "src", cc.stage3_templates(self.cfg, self.rep))
        self.assertIn("### Human review of the stage-3 rules", md)
        self.assertIn("| risk | security | `lib/services/google_sign_in_button.dart` | excluded | UI only |", md)
        self.assertIn("| verification | golden | `test/fixtures/*-baseline.json` | included | structure baseline |", md)
        self.assertNotIn("did not judge", md)

    def test_an_unjudged_candidate_stays_in_and_is_reported(self):
        dec = _review(kept=[{"kind": "risk", "area": "security", "glob": "lib/auth/**", "why": "x"}])
        cfg, rep, _ = convert3(FLUTTER3, decisions=dec)
        sec = [g for r in cfg["path_rules"] if r.get("area") == "security" for g in r["globs"]]
        self.assertIn("lib/services/google_sign_in_button.dart", sec, "fail-closed: unjudged = kept")
        self.assertTrue(any("google_sign_in_button.dart" in w and "not judged" in w for w in rep["warnings"]))
        md = cc.render_report_stage3("x", cfg, rep, "src", {})
        self.assertIn("did not judge", md)

    def test_without_a_review_the_candidates_are_as_before(self):
        cfg, rep, _ = convert3(FLUTTER3, decisions={"stage3": {"note": "t"}})
        self.assertIsNone(rep["stage3"]["review"])
        self.assertTrue(all(r["note"].startswith("CANDIDATE") for r in cfg["path_rules"] if r["kind"] == "risk"))

    def test_refused_reviews(self):
        bad = (
            ("stale exclude", dict(exclude=[{"kind": "risk", "area": "security", "glob": "lib/nothing.dart", "why": "x"}])),
            ("stale kept", dict(kept=[{"kind": "test-code", "glob": "spec/**", "why": "x"}])),
            ("wrong area of a candidate", dict(exclude=[{"kind": "risk", "area": "data-migration", "glob": "lib/auth/**", "why": "x"}])),
            ("include matching nothing", dict(include=[{"kind": "risk", "area": "security", "glob": "lib/none/**", "why": "x"}])),
            ("include already a candidate", dict(include=[{"kind": "risk", "area": "security", "glob": "lib/auth/**", "why": "x"}])),
            ("test-code over a golden", dict(include=[{"kind": "test-code", "glob": "test/goldens/**", "why": "x"}])),
            ("verification include matching nothing", dict(include=[{"kind": "verification", "category": "runner", "glob": "no/such", "why": "x"}])),
        )
        for label, fields in bad:
            with self.subTest(label), self.assertRaises(SystemExit):
                convert3(FLUTTER3, decisions=cc.load_decisions(json.dumps(_review(**fields))))

    def test_refused_decision_shapes(self):
        for fields in (dict(exclude=[{"kind": "risk", "area": "security", "glob": "x"}]),                        # no why
                       dict(exclude=[{"kind": "verification", "category": "test", "glob": "x", "why": "y"}]),     # stage-2 rules only grow
                       dict(include=[{"kind": "risk", "area": "payments", "glob": "x", "why": "y"}]),             # no such area
                       dict(include=[{"kind": "irreversible", "category": "later", "glob": "x", "why": "y"}]),
                       dict(include=[{"kind": "risk", "glob": "x", "why": "y"}]),                                 # area missing
                       dict(include=[{"kind": "test-code", "glob": "/abs/**", "why": "y"}]),
                       dict(exclude=[{"kind": "test-code", "glob": "a/**", "why": "y"}], kept=[{"kind": "test-code", "glob": "a/**", "why": "y"}]),
                       dict(other=[])):
            with self.subTest(fields=fields), self.assertRaises(SystemExit):
                cc.load_decisions(json.dumps(_review(**fields)))
        with self.assertRaises(SystemExit):
            cc.load_decisions(json.dumps({"stage3": {"note": "t", "review": {"exclude": []}}}))          # review needs a note
        cc.load_decisions(json.dumps(self.FULL))


class Stage3Templates(unittest.TestCase):
    def test_every_stage3_template_is_adapted(self):
        cfg, rep, _ = convert3(FLUTTER3)
        tpls = cc.stage3_templates(cfg, rep)
        from gxengine import codes
        self.assertEqual(sorted(tpls), sorted(codes.STAGE3_TEMPLATES))
        self.assertEqual(rep["templates_unusable"], {})
        for name, tpl in tpls.items():
            with self.subTest(template=name):
                runs = [s["run"] for s in tpl["steps"] if "run" in s]
                self.assertTrue(set(runs) <= set(cfg["commands"]))
                self.assertEqual([s["id"] for s in tpl["steps"]][-2:], ["pr", "followups"])
                self.assertNotIn("typecheck", runs)                                    # no such command
                self.assertEqual(cc.check_stage3_template(tpl, json.dumps(
                    __import__("gxengine.instructions", fromlist=["x"]).load_start_procedure(stage=3)), cfg), [])

    def test_extra_runs_go_after_the_e5_developer_step(self):
        cfg, rep, _ = convert3(FLUTTER3)
        tpls = cc.stage3_templates(cfg, rep)
        for name, dev in (("bug", "fix"), ("refactor", "transform"), ("refactor-net", "transform"),
                          ("safety-net", "safety-net"), ("feature", "implement")):
            with self.subTest(template=name):
                steps = tpls[name]["steps"]
                ids = [s["id"] for s in steps]
                self.assertEqual(ids[cc.developer_index(steps)], dev)
                extra = steps[ids.index("gate-suite")]
                self.assertGreater(ids.index("gate-suite"), ids.index(dev))
                self.assertEqual(extra["on_fail"]["back_to"], dev)
        self.assertTrue(any("template `bug`: inserted" in d for d in rep["decisions"]))

    def test_without_test_code_the_bug_template_is_unusable(self):
        files = {k: v for k, v in FLUTTER3.items() if not k.endswith(".dart") or k.startswith("lib/")}
        cfg, rep, _ = convert3(files)
        self.assertNotIn("test-code", {r["kind"] for r in cfg["path_rules"]})
        tpls = cc.stage3_templates(cfg, rep)
        self.assertNotIn("bug", tpls)
        self.assertTrue(any("test-code" in w for w in rep["templates_unusable"]["bug"]))
        self.assertIn("feature", tpls)

    def test_expand_path_tokens(self):
        tpl = {"steps": [{"id": "r", "role": "developer", "outputs": ["{path:test-code}"], "inputs": ["a.md"]}]}
        out = cc.expand_path_tokens(tpl, {"test-code": ["test/**", "**/*_test.dart"]})
        self.assertEqual(out["steps"][0]["outputs"], ["test/**", "**/*_test.dart"])
        self.assertEqual(tpl["steps"][0]["outputs"], ["{path:test-code}"], "the input is not changed")
        with self.assertRaises(ValueError):
            cc.expand_path_tokens(tpl, {})


@unittest.skipUnless(os.path.isdir(os.path.join(ENGINE, "tools", "out")),
                     "tools/out holds the development channel's validation records — a promoted tree leaves them out (R4-6)")
class Stage3Proposals(unittest.TestCase):
    """tools/out/<repo>/stage3/: the three stage-3 proposals (V19) — files only, never written to a repository."""

    OUT = Proposals.OUT

    def load(self, *parts):
        with open(os.path.join(self.OUT, *parts), encoding="utf-8") as f:
            return f.read()

    def repos(self):
        return sorted(d for d in os.listdir(self.OUT) if os.path.isfile(os.path.join(self.OUT, d, "stage3", "config.json")))

    def test_three(self):
        self.assertEqual(self.repos(), ["app-b", "app-c", "app_a"])         # the three validation repositories, renamed (R4-6)

    def test_each_proposal(self):
        from gxengine import codes, instructions
        start = json.dumps(instructions.load_start_procedure(stage=3))
        for repo in self.repos():
            with self.subTest(repo=repo):
                text = self.load(repo, "stage3", "config.json")
                raw = json.loads(text)
                cfg = repoconfig.RepoConfig(raw)
                self.assertIs(raw.get("followups_dry_run"), True, "A4: dry-run in the validation repositories")
                for n in cc.STAGE3_PLUGIN_COMMANDS:
                    self.assertEqual(raw["commands"][n], {"plugin": n})
                kinds = {r["kind"] for r in raw["path_rules"]}
                self.assertTrue({"verification", "test-code", "safety-net"} <= kinds)
                self.assertTrue(all("category" in r for r in raw["path_rules"] if r["kind"] == "verification"))
                procs = sorted(os.listdir(os.path.join(self.OUT, repo, "stage3", "procedures")))
                self.assertEqual(procs, sorted(n + ".yaml" for n in codes.STAGE3_TEMPLATES), "every template usable")
                for p in procs:
                    tpl = json.loads(self.load(repo, "stage3", "procedures", p))
                    self.assertTrue({s["run"] for s in tpl["steps"] if "run" in s} <= set(cfg.command_names()))
                    self.assertEqual(cc.check_stage3_template(tpl, start, raw), [], (repo, p))
                    self.assertEqual(self.load(repo, "stage3", "commit", ".claude", "guild", "procedures", p),
                                     self.load(repo, "stage3", "procedures", p))
                self.assertEqual(self.load(repo, "stage3", "commit", ".claude", "guild", "config.json"), text)
                self.assertEqual(self.load(repo, "stage3", "commit", ".claude", "guild", "roles", "leader.md"),
                                 instructions.default_role_file("leader"))
                # the stage-2 parts of the proposal are the stage-2 proposal's (only the stage-3 additions differ)
                two = json.loads(self.load(repo, "config.json"))
                for key in ("cache_env", "run_env", "secret_paths", "registry_hosts", "sandbox_exceptions", "quarantine",
                            "not_checked_locally", "toolchain_prepare", "worktree_prepare", "run_timeout_min"):
                    self.assertEqual(raw.get(key), two.get(key), key)
                self.assertEqual({n: c for n, c in raw["commands"].items() if n not in cc.STAGE3_PLUGIN_COMMANDS},
                                 two["commands"])
                report = self.load(repo, "stage3", "report.md")
                self.assertIn("## Stage 3 (V19)", report)

    def test_app_b_safety_net_names_are_the_issues(self):
        raw = json.loads(self.load("app-b", "stage3", "config.json"))
        (net,) = [r for r in raw["path_rules"] if r["kind"] == "safety-net"]
        self.assertIn("test/tool/ci_*_wiring_test.dart", net["globs"])                # review-q0 D3 (#698)

    def test_every_candidate_was_judged_by_the_q5_review(self):
        """Q5: the three proposals carry a human review — no unjudged candidate, risk / irreversible rules REVIEWED."""
        for repo in self.repos():
            with self.subTest(repo=repo):
                raw = json.loads(self.load(repo, "stage3", "config.json"))
                report = self.load(repo, "stage3", "report.md")
                self.assertIn("### Human review of the stage-3 rules", report)
                self.assertNotIn("did not judge", report)
                self.assertNotIn("was not judged by the human review", report)
                for r in raw["path_rules"]:
                    if r["kind"] in ("risk", "irreversible"):
                        self.assertTrue(r["note"].startswith("REVIEWED"), (repo, r))
                ext = [g for r in raw["path_rules"] if r.get("category") == "external-side-effect" for g in r["globs"]]
                for f in ext:
                    self.assertNotIn(f, [g for r in raw["path_rules"] if r.get("category") in ("hard-to-revert", "human-executed")
                                         for g in r["globs"]], "a release path is never lowered")

    def test_stage3_base_green_records_are_of_these_exact_files(self):
        """Q5 (§7.10): stage3/base-check ran THIS commit config.json (sha256), without what-if, every `cmd` green."""
        import hashlib
        for repo in self.repos():
            with self.subTest(repo=repo):
                rec = json.loads(self.load(repo, "stage3", "base-check", "base-check.json"))
                with open(os.path.join(self.OUT, repo, "stage3", "commit", ".claude", "guild", "config.json"), "rb") as f:
                    self.assertEqual(rec["config_sha256"], hashlib.sha256(f.read()).hexdigest())
                self.assertIs(rec["what_if"], False)
                raw = json.loads(self.load(repo, "stage3", "config.json"))
                ran = {r["name"]: r for r in rec["results"] if "skipped" not in r}
                want = {n for n, c in raw["commands"].items() if "cmd" in c}
                self.assertEqual(want - set(ran), set(), "a command the check did not run")
                self.assertEqual([n for n, r in ran.items() if not r["ok"]], [])

    def test_q5_review_narrowings(self):
        from gxengine import globs as G
        wa = json.loads(self.load("app_a", "stage3", "config.json"))
        rules = {(r["kind"], r.get("area") or r.get("category")): r["globs"] for r in wa["path_rules"]}
        self.assertFalse(any(G.match(g, "lib/env/env_test.dart") for g in rules[("test-code", None)]),
                         "a production env file is no test code")
        self.assertNotIn("lib/features/kanji_detail_modal/widgets/subscription_panel.dart", rules[("risk", "security")])
        self.assertEqual(rules[("irreversible", "external-side-effect")][:4], [
            ".github/workflows/publish_release_notes.yml", ".github/workflows/release_android.yml",
            ".github/workflows/release_ios.yml", ".github/workflows/update_release_notes_draft.yml"])
        for repo in ("app_a", "app-b"):
            raw = json.loads(self.load(repo, "stage3", "config.json"))
            (net,) = [r["globs"] for r in raw["path_rules"] if r["kind"] == "safety-net"]
            self.assertTrue(all(g.startswith("test/") for g in net), (repo, net))   # the test command runs test/ only


# --- init (stage 4, VB2) -----------------------------------------------------------------------

NODE_NEW = {
    "package.json": json.dumps({"scripts": {"test": "vitest run", "lint": "eslint . --fix", "typecheck": "tsc --noEmit",
                                             "deploy": "wrangler deploy", "format": "prettier ."}}),
    "pnpm-lock.yaml": "lockfileVersion: 9\n  resolution: {tarball: https://codeload.github.com/x/y/tar.gz/abc}\n",
    "src/index.ts": "export {}\n", "src/index.test.ts": "test()\n",
}
PY_NEW = {
    "pyproject.toml": "[project]\nname='a'\n", "src/a.py": "x = 1\n", "tests/test_a.py": "def test_a(): pass\n",
    ".github/workflows/ci.yml": "on: [push]\njobs:\n  t:\n    steps:\n      - name: Tests\n        run: python -m pytest -q\n"
                                "      - run: ruff check .\n      - run: ./deploy.sh ${{ secrets.TOKEN }}\n",
}
FLUTTER_NEW = {k: v for k, v in FLUTTER.items() if k != ".claude/guild/config.json"}  # promote: literal


def init_draft(files, decisions=None, exists=lambda p: True, host_os="darwin"):
    return cc.propose(MemSource(files), decisions, host_os=host_os, now=NOW, exists=exists)


def asked(draft, question=None):
    return [(q["question"], q["item"]) for q in draft["questions"] if question in (None, q["question"])]


class InitWithStableSettings(unittest.TestCase):
    """TI1: the same draft as the stage-3 conversion; only the descriptions name their source."""

    def same(self, files):
        old, _, _ = convert3(files)
        new = init_draft(files)["config"]
        for c in (old, new):
            c.pop("source")
            for e in c["commands"].values():
                e.pop("description", None)
        self.assertEqual(new, old)

    def test_ti1_flutter_and_node_shapes(self):
        self.same(FLUTTER)
        self.same(FLUTTER3)
        self.same(dict(FLUTTER3, **{".github/workflows/q2.yml": "on: [pull_request]\njobs:\n  a:\n    steps:\n      - run: pnpm lint\n"}))
        self.same({".claude/guild/config.json": stable({"test": "pnpm test", "lint": ["pnpm lint", "pnpm cspell"]}),  # promote: literal
                   "package.json": '{"scripts": {"typecheck": "tsc"}}', "pnpm-lock.yaml": "", "turbo.json": "{}", "a.test.ts": ""})

    def test_every_command_names_its_source(self):
        d = init_draft(FLUTTER)["config"]["commands"]
        self.assertTrue(d["test"]["description"].startswith("stable-config: .claude/guild/config.json:"), d["test"])  # promote: literal
        for name, e in d.items():
            if "cmd" in e:
                self.assertIn(e["description"].split(":")[0], ("stable-config", "ci", "lefthook", "manifest", "human"), name)
        self.assertEqual(d["dart-format"]["description"].split(" ")[:2], ["lefthook:", "lefthook.yml:9"])
        self.assertRegex(d["check"]["description"], r"^ci: \.github/workflows/q\.yml:\d+ ")

    def test_a_ci_command_that_runs_something_else_is_a_conflict(self):
        d = init_draft(FLUTTER)
        self.assertIn(("command-conflict", "test"), asked(d))
        ids = d["choices"]["test"]
        self.assertIn("flutter test --exclude-tags golden --file-reporter json:build/ci.json", ids.values())
        self.assertNotIn(("command-conflict", "lint"), asked(d), "the same command is no conflict")

    def test_the_stage_3_conversion_is_untouched(self):
        cfg, _, _ = convert3(FLUTTER)
        self.assertEqual(cfg["commands"]["test"]["description"], "0.98.7 commands.test")
        with self.assertRaises(SystemExit):
            convert3(NODE_NEW)


class InitWithoutStableSettings(unittest.TestCase):
    """TI2–TI4: H14."""

    def test_ti2_node(self):
        d = init_draft(NODE_NEW)
        cmds = {n: e["cmd"] for n, e in d["config"]["commands"].items() if "cmd" in e}
        self.assertEqual(cmds, {"setup": "pnpm install --frozen-lockfile", "test": "pnpm run test", "typecheck": "pnpm run typecheck"})
        self.assertEqual(d["config"]["commands"]["test"]["description"], "manifest: package.json" + ":1 (package.json `test`)")
        self.assertTrue(any("`lint`: not carried" in w for w in d["warnings"]), d["warnings"])
        self.assertIn(("registry-host", "codeload.github.com"), asked(d))
        repoconfig.RepoConfig(json.loads(json.dumps(d["config"])))

    def test_ti2_flutter(self):
        d = init_draft(FLUTTER_NEW)
        c = d["config"]["commands"]
        self.assertIn("flutter test --exclude-tags golden", c["test"]["cmd"])
        self.assertTrue(c["test"]["description"].startswith("ci: .github/workflows/q.yml:"))
        self.assertIn("flutter analyze", c["lint"]["cmd"])
        self.assertEqual(d["config"]["toolchain_prepare"][0]["sync"]["from"], ["{home}/fvm/versions/3.47.7"])
        self.assertEqual(asked(d, "toolchain"), [])

    def test_ti2_python(self):
        d = init_draft(PY_NEW)
        c = {n: e["cmd"] for n, e in d["config"]["commands"].items() if "cmd" in e}
        self.assertEqual(c, {"test": "python -m pytest -q", "lint": "ruff check ."})
        self.assertEqual(d["config"]["commands"]["test"]["description"], "ci: .github/workflows/ci.yml:6 (CI ci/t › Tests)")
        self.assertIn(("not-local", "ci/t"), asked(d))

    def test_makefile_targets(self):
        d = init_draft({"Makefile": "test: build\n\tgo test ./...\nVERSION := 1\ndeploy:\n\t./d.sh\n", "main.go": ""})
        self.assertEqual({n: e["cmd"] for n, e in d["config"]["commands"].items() if "cmd" in e}, {"test": "make test"})

    def test_ti3_no_command_text_from_nowhere(self):
        """Every text is literally in a file, is `<package manager> run <name>` of a defined script, is the lockfile
        install — or a human wrote it."""
        for files in (NODE_NEW, FLUTTER_NEW, PY_NEW, FLUTTER, FLUTTER3):
            text = "\n".join(v for k, v in files.items() if isinstance(v, str))
            for name, e in init_draft(files)["config"]["commands"].items():
                if "cmd" not in e or name == "setup":
                    continue
                for seg in e["cmd"].replace(P, "").split(" && "):
                    ok = " ".join(seg.split()) in " ".join(text.split()) or json.dumps(seg)[1:-1] in text \
                        or any(seg == r["cmd"].replace("{name}", name) for m in cc.TABLES["manifests"] for r in m["runners"])
                    self.assertTrue(ok, (name, seg))

    def test_no_test_anywhere_is_a_question_and_only_a_human_answers_it(self):
        files = {"README.md": "x", "src/a.py": "x"}
        d = init_draft(files)
        self.assertEqual(asked(d, "test-command"), [("test-command", None)])
        self.assertNotIn("test", d["config"]["commands"])
        dec = cc.load_decisions(json.dumps({"add_commands": {"test": {"cmd": "python3 -m unittest", "why": "JK"}}}), init=True)
        d = init_draft(files, dec)
        self.assertEqual(d["config"]["commands"]["test"], {"cmd": "python3 -m unittest", "description": "human: JK"})
        self.assertEqual(asked(d, "test-command"), [("test-command", None)], "the questions never move with an answer")
        with self.assertRaises(SystemExit):
            init_draft(NODE_NEW, dec)                             # there is a test command: nothing to add

    def test_the_placeholder_script_and_an_unknown_package_manager_are_no_commands(self):
        d = init_draft({"package.json": json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1', "build": "tsc -b"}})})
        self.assertEqual([n for n, e in d["config"]["commands"].items() if "cmd" in e], [])
        self.assertTrue(any("no lockfile" in w for w in d["warnings"]))

    def test_two_ci_commands_of_one_name_are_a_question_never_a_silent_loss(self):
        files = dict(PY_NEW, **{".github/workflows/b.yml": "on: [push]\njobs:\n  t:\n    steps:\n      - run: python -m pytest -q --slow\n"})
        d = init_draft(files)
        self.assertEqual(len(d["choices"]["test"]), 2)
        other = {n: e["cmd"] for n, e in d["config"]["commands"].items() if "cmd" in e}
        self.assertEqual(sorted(other.values()), ["python -m pytest -q", "python -m pytest -q --slow", "ruff check ."],
                         "both CI steps stay checks")
        cid = next(i for i, c in d["choices"]["test"].items() if "--slow" in c)
        dec = {"commands": {"test": {"cmd": d["choices"]["test"][cid], "why": "JK: the slow ones too"}}}
        cmds = init_draft(files, dec)["config"]["commands"]
        self.assertEqual(sorted(e["cmd"] for e in cmds.values() if "cmd" in e), sorted(other.values()), "they change places")
        got = cmds["test"]
        self.assertEqual(got["cmd"], "python -m pytest -q --slow")
        self.assertTrue(got["description"].startswith("ci: .github/workflows/b.yml:5 "), got)
        self.assertIn("chosen by a human: JK", got["description"])

    def test_ti4_an_unreadable_workflow_is_reported_not_guessed(self):
        files = {".github/workflows/x.yml": "on: [push]\njobs: {t: [1, 2\n", "README.md": "x"}
        d = init_draft(files)
        self.assertTrue(any("x.yml" in w and "not parsed" in w for w in d["warnings"]), d["warnings"])
        self.assertEqual([n for n, e in d["config"]["commands"].items() if "cmd" in e], [])
        self.assertEqual(asked(d, "test-command"), [("test-command", None)])

    def test_an_unreadable_stable_config_still_stops(self):
        with self.assertRaises(SystemExit):
            init_draft({".claude/guild/config.json": "{"})  # promote: literal

    def test_ti6_nothing_to_ask(self):
        """Without a condition only the two questions every draft has (A15, 2026-11-26), both optional: a rule line a
        human may add, and whether follow-ups are only recorded (Q11, 2026-11-28: never asked — no answer = create)."""
        d = init_draft({"Makefile": "test:\n\ttrue\n", "README.md": "x"})
        self.assertEqual([(q["question"], q["item"], q["required"]) for q in d["questions"]],
                         [("risk-add", None, False), ("followups-dry-run", None, False)])
        self.assertNotIn("followups_dry_run", d["config"], "no answer = really create (defaults.FOLLOWUPS_DRY_RUN_DEFAULT)")


class InitQuestions(unittest.TestCase):
    def test_only_the_questions_of_the_contract(self):
        kinds = set()
        for files in (NODE_NEW, FLUTTER_NEW, PY_NEW, FLUTTER, FLUTTER3, {"a": ""}):
            for q in init_draft(files, exists=lambda p: False)["questions"]:
                self.assertEqual(set(q), {"question", "item", "required", "text", "choices"})
                kinds.add(q["question"])
        from gxengine import codes
        self.assertLessEqual(kinds, set(codes.InitQuestion.values()))

    def test_toolchain(self):
        none = init_draft(FLUTTER_NEW, exists=lambda p: False)
        self.assertEqual(asked(none, "toolchain"), [("toolchain", "flutter-sdk")])
        self.assertNotIn("toolchain_prepare", none["config"])
        self.assertNotIn("GLD_FLUTTER_ROOT", none["config"]["cache_env"])
        self.assertFalse(any(P in e.get("cmd", "") for e in none["config"]["commands"].values()))
        unpinned = {k: v for k, v in FLUTTER_NEW.items() if k != ".fvmrc"}
        two = init_draft(unpinned, exists=lambda p: p.startswith("{home}"))
        q = [x for x in two["questions"] if x["question"] == "toolchain"][0]
        self.assertEqual(len(q["choices"]), 3)
        dec = {"toolchain": {"flutter-sdk": {"from": "{home}/flutter", "why": "JK"}}}
        got = init_draft(unpinned, dec, exists=lambda p: p.startswith("{home}"))
        self.assertEqual(got["config"]["toolchain_prepare"][0]["sync"]["from"], ["{home}/flutter"])
        one = init_draft(unpinned, exists=lambda p: p == "{home}/flutter")
        self.assertEqual((asked(one, "toolchain"), one["config"]["toolchain_prepare"][0]["sync"]["from"]), ([], ["{home}/flutter"]))

    def test_risk_lines_are_optional_one_by_one(self):
        d = init_draft(FLUTTER3)
        items = [i for _, i in asked(d, "risk-rules")]
        self.assertIn("risk:security:lib/auth/**", items)
        self.assertTrue(all(not q["required"] for q in d["questions"] if q["question"] == "risk-rules"))
        dec = {"stage3": {"note": "JK", "review": {"note": "JK", "exclude": [
            {"kind": "risk", "area": "security", "glob": "lib/auth/**", "why": "JK"}]}}}
        got = init_draft(FLUTTER3, dec)
        self.assertNotIn("lib/auth/**", [g for r in got["config"]["path_rules"] if r["kind"] == "risk" for g in r["globs"]])
        self.assertEqual([i for _, i in asked(got, "risk-rules")], items)

    def test_an_approved_host_is_in_the_settings_and_a_rejected_one_is_not(self):
        self.assertNotIn("codeload.github.com", init_draft(NODE_NEW)["config"]["registry_hosts"])
        got = init_draft(NODE_NEW, {"registry_hosts": {"codeload.github.com": "JK"}})
        self.assertIn("codeload.github.com", got["config"]["registry_hosts"])

    def test_ti11_roles_are_reported_never_made(self):
        d = init_draft(NODE_NEW)
        self.assertIn("developer", d["roles_missing"])
        self.assertIn("tech-lead", d["roles_missing"])
        self.assertNotIn("auditor", d["roles_missing"], "the plugin ships it")
        self.assertNotIn("designer", init_draft(FLUTTER3)["roles_missing"])

    def test_decision_shapes_of_init(self):
        ok = {"add_commands": {"test": {"cmd": "x", "why": "y"}}, "registry_hosts": {"a.example": "y"},
              "toolchain": {"flutter-sdk": {"from": None, "why": "y"}}}
        self.assertEqual(cc.load_decisions(json.dumps(ok), init=True), ok)
        with self.assertRaises(SystemExit):
            cc.load_decisions(json.dumps(ok))                      # stage 2 / 3 decisions never have them
        for bad in ({"add_commands": {"lint": {"cmd": "x", "why": "y"}}}, {"add_commands": {"test": "x"}}, {"add_commands": []},
                    {"add_commands": {"test": {"cmd": "a\nb", "why": "y"}}}, {"registry_hosts": {"*": "y"}}, {"registry_hosts": {"a.b": ""}},
                    {"toolchain": {"node": {"from": None, "why": "y"}}}, {"toolchain": {"flutter-sdk": {"from": "rel", "why": "y"}}}):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                cc.load_decisions(json.dumps(bad), init=True)


class InitTables(unittest.TestCase):
    """D10: the tables are data by ecosystem — no repository, no project path."""

    def test_names_no_repository(self):
        text = fixture_file(cc.TABLES_FILE)
        for word in ("word_app", "one-man-company", "japanlifeinfo", "poc-service", "dev-yakuza", "j-kim", "/Users/", "projects/"):
            self.assertNotIn(word, text)

    def test_shape(self):
        t = cc.TABLES
        self.assertEqual(t["manifest_names"], ["test", "lint", "typecheck", "build"])
        self.assertLessEqual(set(t["program_names"]), set(t["manifest_names"]))
        for m in t["manifests"]:
            for r in m["runners"]:
                self.assertIn("{name}", r["cmd"])
                self.assertEqual(cc.classify_command(r["cmd"].replace("{name}", "test")), ("check", None))
        for h in t["host_patterns"]:
            self.assertEqual(re.compile(h["pattern"]).groups, 1)
        for c in t["toolchains"]:
            for p in c["sources"] + c["pinned"]:
                self.assertTrue(p.startswith(("{home}/", "/")))

    def test_funding_links_are_no_hosts(self):
        src = MemSource({"package-lock.json": '{"a": {"resolved": "https://registry.npmjs.org/a.tgz", "funding": {"url": "https://opencollective.com/x"}}}'})
        self.assertEqual(list(cc.lock_hosts(src)), ["registry.npmjs.org"])


def fixture_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class InitCommandLine(unittest.TestCase):
    def test_json_of_a_revision_and_nothing_written(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            repo = GitRepo.create(tmp, files=dict(PY_NEW), with_remote=False)
            repo.write("src/a.py", "changed after the commit\n")
            before = repo.git("status", "--porcelain")
            argv = [sys.executable, "-I", "-B", os.path.join(ENGINE, "tools", "convert_config.py"), "--repo-root", repo.path,
                    "--rev", repo.head(), "--init"]
            one = subprocess.run(argv, capture_output=True, text=True, env=repo.env)
            self.assertEqual(one.returncode, 0, one.stderr)
            d = json.loads(one.stdout)
            self.assertEqual((d["sha"], json.loads(d["config_text"])), (repo.head(), d["config"]))
            self.assertNotIn(repo.path, d["config_text"], "no path of this machine is in the settings")
            self.assertEqual(subprocess.run(argv, capture_output=True, text=True, env=repo.env).stdout, one.stdout, "the same commit, the same text")
            self.assertEqual(repo.git("status", "--porcelain"), before)
            bad = subprocess.run(argv[:-3] + ["--init"], capture_output=True, text=True, env=repo.env)
            self.assertNotEqual(bad.returncode, 0)
