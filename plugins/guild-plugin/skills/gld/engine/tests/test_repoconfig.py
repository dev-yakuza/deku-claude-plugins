"""gxengine/repoconfig.py — loading and querying `.claude/guild/config.json` (U16)."""

import copy
import json
import os
import unittest

from gxengine import catalog, codes, defaults, globs, repoconfig
from gxengine.repoconfig import ConfigError, RepoConfig

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ENGINE, "tests", "fixtures", "contracts", "repo-config.example.json")
HOME = "/Users/someone"


def example():
    with open(EXAMPLE, encoding="utf-8") as f:
        return json.load(f)


def load(raw):
    return RepoConfig(raw, home=HOME)


def globs_work():
    try:
        globs.match("a", "a")
    except NotImplementedError:
        return False
    return True


class Loading(unittest.TestCase):
    def test_example_loads(self):
        cfg = load(example())
        self.assertEqual(cfg.command_names(), ["setup", "test", "e2e", "ac-format", "ac-coverage", "verify-gate"])

    def test_from_text(self):
        cfg = RepoConfig.from_text(json.dumps(example()), home=HOME)
        self.assertIn("test", cfg.command_names())

    def test_bad_json_and_non_objects(self):
        for text in ("{", "[]", "null", ""):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                RepoConfig.from_text(text, home=HOME)

    def test_duplicate_keys_are_refused(self):
        with self.assertRaises(ConfigError) as cm:
            RepoConfig.from_text('{"format": 1, "commands": {"a": {"cmd": "x"}, "a": {"cmd": "y"}}}', home=HOME)
        self.assertIn("duplicate", str(cm.exception))

    def test_schema_violations_are_config_errors(self):
        for mutate in (
            lambda c: c.pop("commands"),
            lambda c: c.update(format=2),
            lambda c: c.update(unknown_key=1),
            lambda c: c["commands"].update({"Bad Name": {"cmd": "x"}}),
            lambda c: c["commands"]["test"].update(cmd=""),
            lambda c: c["commands"]["test"].update(timeout_min=0),
            lambda c: c["commands"].update({"x": {"cmd": "a", "plugin": "ac-format"}}),
            lambda c: c.update(registry_hosts=["not a host"]),
            lambda c: c.update(worktree_prepare=[{"copy": "/abs/path"}]),
            lambda c: c.update(worktree_prepare=[{"copy": "../up"}]),
            lambda c: c["path_rules"].append({"kind": "risk", "globs": ["a/**"]}),
        ):
            raw = example()
            mutate(raw)
            with self.subTest(raw=json.dumps(raw)[:80]), self.assertRaises(ConfigError):
                load(raw)

    def test_cache_env_accepts_only_the_cache_placeholder(self):
        raw = example()
        raw["cache_env"]["X"] = "{home}/x"
        with self.assertRaises(ConfigError):
            load(raw)
        raw["cache_env"]["X"] = "{cache}/x/{cache}"
        load(raw)

    def test_empty_allow_lists_are_refused(self):
        for key in ("allowed_models", "allowed_efforts"):
            raw = example()
            raw[key] = []
            with self.subTest(key=key), self.assertRaises(ConfigError):
                load(raw)


def stage3():
    with open(os.path.join(os.path.dirname(EXAMPLE), "repo-config.stage3.example.json"), encoding="utf-8") as f:
        return json.load(f)


class Stage3PathGlobs(unittest.TestCase):
    """E4: what `{path:<kind>}` becomes."""

    def test_globs_of_every_rule_of_the_kind(self):
        raw = stage3()
        raw["path_rules"].append({"kind": "test-code", "globs": ["e2e/**/*.spec.ts", "test/**/*_test.dart"]})
        cfg = load(raw)
        self.assertEqual(cfg.path_globs("test-code"), ["test/**/*_test.dart", "e2e/**/*.spec.ts"])
        self.assertEqual(cfg.path_globs(codes.PathRuleKind.SAFETY_NET), ["test/**/*_safety_net_test.dart"])
        self.assertEqual(load(example()).path_globs("test-code"), [])
        with self.assertRaises(ValueError):
            cfg.path_globs("nonsense")


class Stage3Settings(unittest.TestCase):
    """E22 / E24 levels and the A4 dry-run switch."""

    def test_levels(self):
        cfg = load(example())
        self.assertEqual(cfg.irreversible_level("external-side-effect"), ("human-decision", "human-decision", False))
        self.assertEqual(cfg.irreversible_level(codes.IrreversibleCategory.HARD_TO_REVERT), ("notify", "notify", False))
        cfg = load(stage3())                                        # irreversible_levels: human-executed → proceed
        self.assertEqual(cfg.irreversible_level("human-executed"), ("proceed", "notify", True))          # TI4

    def test_a_path_rule_wins(self):
        cfg = load(stage3())
        for cat, level, want in (("human-executed", "notify", ("notify", "notify", False)),
                                 ("human-executed", "human-decision", ("human-decision", "notify", False)),
                                 ("external-side-effect", "notify", ("notify", "human-decision", True)),
                                 ("external-side-effect", None, ("human-decision", "human-decision", False)),
                                 ("human-executed", None, ("proceed", "notify", True))):
            rule = {"kind": "irreversible", "category": cat, "globs": ["x/**"]}
            if level:
                rule["level"] = level
            self.assertEqual(cfg.irreversible_level(cat, rule), want, (cat, level))

    def test_bad_arguments(self):
        cfg = load(stage3())
        with self.assertRaises(ValueError):
            cfg.irreversible_level("other")
        for rule in ({"kind": "irreversible", "category": "hard-to-revert", "globs": []},
                     {"kind": "risk", "category": "human-executed", "globs": []}):
            with self.assertRaises(ValueError):
                cfg.irreversible_level("human-executed", rule)

    def test_dry_run(self):
        self.assertIs(load(example()).followups_dry_run(), False)     # A4: absent = really create
        self.assertIs(load(stage3()).followups_dry_run(), True)
        self.assertIs(load(dict(example(), followups_dry_run=False)).followups_dry_run(), False)


class Stage3Categories(unittest.TestCase):
    """E33: the category of a verification path."""

    def cfg(self, *rules):
        return load(dict(example(), path_rules=[dict({"kind": "verification", "globs": [g]}, **({"category": c} if c else {}))
                                                for g, c in rules]))

    def test_example(self):
        cfg = load(stage3())
        self.assertEqual(cfg.verification_category("test/goldens/a.png"), "golden")
        self.assertEqual(cfg.verification_category("test/a_test.dart"), "test")
        self.assertIsNone(cfg.verification_category("src/a.py"))

    def test_the_ledger_categories_win_in_any_order(self):
        rules = [("test/**", "test"), ("test/goldens/**", "golden"), ("test/*.yaml", "comparison-config"), ("ci/**", "ci")]
        for order in (rules, rules[::-1]):
            cfg = self.cfg(*order)
            self.assertEqual(cfg.verification_category("test/goldens/a.png"), "golden")
            self.assertEqual(cfg.verification_category("test/compare.yaml"), "comparison-config")
            self.assertEqual(cfg.verification_category("test/a.dart"), "test")
            self.assertEqual(cfg.verification_category("ci/x.yml"), "ci")

    def test_no_category(self):
        self.assertIsNone(self.cfg(("test/**", None)).verification_category("test/a"))
        self.assertEqual(self.cfg(("test/**", None), ("test/a", "runner")).verification_category("test/a"), "runner")


class Stage3Gates(unittest.TestCase):
    """E25: a risk rule's gate is a diff-review entry of the step catalog."""

    CATALOG = catalog.load(os.path.join(os.path.dirname(EXAMPLE), os.pardir, "procedure", "catalog.json"))

    def test_gate_must_be_a_diff_review_entry(self):
        raw = stage3()
        self.assertEqual(load(raw).gate_problems(self.CATALOG), [])
        RepoConfig(raw, home=HOME, catalog=self.CATALOG)
        for gate in ("dba-review", "threat-model", "fix-discovery"):
            bad = stage3()
            bad["path_rules"].append({"kind": "risk", "area": "data", "gate": gate, "globs": ["migrations/**"]})
            self.assertIn(gate, load(bad).gate_problems(self.CATALOG)[0])
            with self.assertRaises(ConfigError):
                RepoConfig(bad, home=HOME, catalog=self.CATALOG)
            with self.assertRaises(ConfigError):
                RepoConfig.from_text(json.dumps(bad), home=HOME, catalog=self.CATALOG)
            RepoConfig.from_text(json.dumps(bad), home=HOME)           # earlier stages: not looked at

    def test_an_empty_catalog_refuses_every_gate(self):
        self.assertEqual(len(load(stage3()).gate_problems({})), 1)


class SandboxExceptions(unittest.TestCase):
    def check(self, path, ok):
        raw = example()
        raw["sandbox_exceptions"] = {"allow_write": [path]}
        if ok:
            load(raw)
        else:
            with self.assertRaises(ConfigError, msg=path):
                load(raw)

    def test_home_toolchain_and_cache_paths_are_never_exceptions(self):
        for p in (HOME + "/.pub-cache", HOME + "/.gradle/caches", HOME + "/fvm/versions/3.47.7/bin/cache", HOME + "/.cache/foo",
                  HOME + "/Library/Caches/x", HOME + "/.npm", HOME + "/.ssh", HOME, "/", "~/x", "$HOME/x", "a/../b",
                  "/tmp/claude-502/x", "/private/tmp/claude-502/x", ""):
            with self.subTest(path=p):
                self.check(p, ok=False)

    def test_other_paths_are_accepted(self):
        for p in ("{user_tmp}", "/opt/guild/scratch", HOME + "/projects/x/out"):
            with self.subTest(path=p):
                self.check(p, ok=True)

    def test_home_ancestors_and_home_secrets_are_refused(self):
        """P3-0: an ancestor of home, and anything at / inside defaults.HOME_SECRETS."""
        for p in ("/Users", HOME + "/.config/gh/x", HOME + "/.docker/config.json", HOME + "/.kube/c",
                  HOME + "/.git-credentials", HOME + "/.netrc", HOME + "/.azure"):
            with self.subTest(path=p):
                self.check(p, ok=False)
        # a sibling of a secret name is not a secret
        self.check(HOME + "/.dockerish/out", ok=True)


class RunEnv(unittest.TestCase):
    def with_env(self, run_env, cache_env=None):
        raw = example()
        raw["run_env"] = run_env
        if cache_env is not None:
            raw["cache_env"] = cache_env
        return raw

    def test_query_and_default(self):
        self.assertEqual(load(self.with_env({"TURBO_TELEMETRY_DISABLED": "1"})).run_env(),
                         {"TURBO_TELEMETRY_DISABLED": "1"})
        raw = example()
        raw.pop("run_env", None)
        self.assertEqual(load(raw).run_env(), {})

    def test_same_name_in_cache_env_is_refused(self):
        with self.assertRaises(ConfigError):
            load(self.with_env({"GLD_X": "1"}, cache_env={"GLD_X": "{cache}/x"}))

    def test_schema_refusals_surface_as_config_errors(self):
        for env in ({"PATH": "/x"}, {"MY_TOKEN": "x"}, {"GIT_DIR": "/x"}, {"X": "{cache}"}, {"lower": "1"}):
            with self.subTest(env=env):
                with self.assertRaises(ConfigError):
                    load(self.with_env(env))


class Queries(unittest.TestCase):
    def setUp(self):
        self.cfg = load(example())

    def test_command_lookup(self):
        t = self.cfg.command("test")
        self.assertEqual(t, {"cmd": "pnpm test -- --ci", "plugin": None, "timeout_s": 30 * 60})
        self.assertEqual(self.cfg.command("e2e")["timeout_s"], 45 * 60)
        self.assertEqual(self.cfg.command("ac-format"), {"cmd": None, "plugin": "ac-format", "timeout_s": 30 * 60})
        with self.assertRaises(KeyError):
            self.cfg.command("nope")

    def test_default_timeout_is_the_plugin_default(self):
        raw = example()
        del raw["run_timeout_min"]
        self.assertEqual(load(raw).command("setup")["timeout_s"], defaults.RUN_TIMEOUT_MIN * 60)
        raw["run_timeout_min"] = 7
        self.assertEqual(load(raw).command("setup")["timeout_s"], 7 * 60)
        self.assertEqual(load(raw).command("test")["timeout_s"], 30 * 60)       # the command's own limit wins

    def test_path_rules(self):
        self.assertEqual([r["kind"] for r in self.cfg.path_rules("verification")], ["verification"])
        self.assertEqual(self.cfg.path_rules(codes.PathRuleKind.RISK)[0]["area"], "auth")
        self.assertEqual(self.cfg.path_rules("irreversible")[0]["category"], "hard-to-revert")
        with self.assertRaises(ValueError):
            self.cfg.path_rules("nonsense")

    def test_path_rules_are_copies(self):
        self.cfg.path_rules("verification")[0]["globs"].append("x")
        self.assertNotIn("x", self.cfg.path_rules("verification")[0]["globs"])

    def test_matches(self):
        if not globs_work():
            self.skipTest("gxengine.globs is still a stub (U3, session 1)")
        self.assertEqual([r["kind"] for r in self.cfg.matches("verification", "test/a/b.dart")], ["verification"])
        self.assertEqual(self.cfg.matches("verification", "lib/x.dart"), [])
        self.assertEqual(self.cfg.matches("risk", "src/auth/login.ts")[0]["area"], "auth")

    def test_cache_env_fills_the_placeholder(self):
        env = self.cfg.cache_env("/home/u/.gld/cache/o/r")
        self.assertEqual(env, {"npm_config_cache": "/home/u/.gld/cache/o/r/npm", "COREPACK_HOME": "/home/u/.gld/cache/o/r/corepack"})
        self.assertEqual(example()["cache_env"]["COREPACK_HOME"], "{cache}/corepack")      # the file is not modified

    def test_secret_paths_default_when_absent_or_empty(self):
        self.assertEqual(self.cfg.secret_paths(), [".env*", "*.pem", "*.p12"])
        for variant in (lambda c: c.pop("secret_paths"), lambda c: c.update(secret_paths=[])):
            raw = example()
            variant(raw)
            self.assertEqual(load(raw).secret_paths(), list(defaults.REPO_SECRET_DEFAULTS))

    def test_default_secret_paths_reach_nested_folders(self):
        for path in (".env", "app/.env.local", "a/b/server.pem", "k.p12", "keys/x.key"):
            with self.subTest(path=path):
                self.assertTrue(any(globs.match(g, path) for g in defaults.REPO_SECRET_DEFAULTS))

    def test_lists_and_dicts(self):
        self.assertEqual(self.cfg.registry_hosts(), ["registry.npmjs.org", "repo.yarnpkg.com"])
        self.assertEqual(self.cfg.toolchain_prepare(), [
            {"name": "flutter-sdk", "cmd": None, "sync": {"from": ["{home}/fvm/versions/3.47.7", "/opt/flutter"],
                                                         "to": "flutter-sdk"}, "timeout_s": 30 * 60},
            {"name": "flutter-precache", "cmd": "flutter precache", "sync": None, "timeout_s": 30 * 60}])

    def test_toolchain_sync_sources_and_destinations_are_checked(self):
        """P3-Z decision 4: a sync source is a canonical folder outside the temp areas; names and
        destinations are unique and never overlap."""
        bad = [
            {"name": "a", "sync": {"from": ["/tmp/sdk"], "to": "a"}},
            {"name": "a", "sync": {"from": ["/private/var/folders/x/sdk"], "to": "a"}},
            {"name": "a", "sync": {"from": ["/opt/sdk/"], "to": "a"}},
            {"name": "a", "sync": {"from": ["{home}/../x"], "to": "a"}},
            {"name": "a", "sync": {"from": ["~/sdk"], "to": "a"}},
            {"name": "a", "sync": {"from": ["/opt/sdk"], "to": "../a"}},
            {"name": "a", "sync": {"from": ["/opt/sdk"], "to": "x/.git"}},
            {"name": "a", "cmd": "x", "sync": {"from": ["/opt/sdk"], "to": "a"}},
        ]
        for e in bad:
            raw = example()
            raw["toolchain_prepare"] = [e]
            with self.subTest(e=e), self.assertRaises(repoconfig.ConfigError):
                load(raw)
        for pair in ([{"name": "a", "cmd": "x"}, {"name": "a", "cmd": "y"}],
                     [{"name": "a", "sync": {"from": ["/opt/s"], "to": "sdk"}},
                      {"name": "b", "sync": {"from": ["/opt/t"], "to": "sdk/sub"}}]):
            raw = example()
            raw["toolchain_prepare"] = pair
            with self.subTest(pair=pair), self.assertRaises(repoconfig.ConfigError):
                load(raw)
        self.assertEqual(self.cfg.worktree_prepare(), [{"copy": "lib/generated/**", "note": "ignored codegen output"}])
        self.assertEqual(self.cfg.sandbox_exceptions(), {"allow_local_binding": False})
        self.assertEqual(self.cfg.not_checked_locally(), [{"name": "deploy-preview", "note": "needs secrets"}])
        self.assertEqual(self.cfg.quarantine()[0]["test"], "test/flaky_clock_test.dart")

    def test_absent_optional_parts_are_empty(self):
        cfg = load({"format": 1, "commands": {"test": {"cmd": "make test"}}})
        self.assertEqual((cfg.registry_hosts(), cfg.toolchain_prepare(), cfg.worktree_prepare(), cfg.not_checked_locally(), cfg.quarantine()),
                         ([], [], [], [], []))
        self.assertEqual(cfg.sandbox_exceptions(), {})
        self.assertEqual(cfg.path_rules("verification"), [])
        self.assertEqual(cfg.cache_env("/c"), {})
        self.assertEqual(cfg.allowed_models(), list(defaults.ALLOWED_MODELS))
        self.assertEqual(cfg.allowed_efforts(), list(defaults.ALLOWED_EFFORTS))

    def test_allow_list_overrides(self):
        raw = example()
        raw["allowed_models"] = ["opus", "sonnet", "fable"]
        self.assertEqual(load(raw).allowed_models(), ["opus", "sonnet", "fable"])

    def test_loading_does_not_mutate_the_input(self):
        raw = example()
        snapshot = copy.deepcopy(raw)
        cfg = load(raw)
        cfg.path_rules("verification")
        cfg.cache_env("/x")
        self.assertEqual(raw, snapshot)

    def test_module_constants(self):
        self.assertEqual(repoconfig.CONFIG_PATH, ".claude/guild/config.json")


if __name__ == "__main__":
    unittest.main()
