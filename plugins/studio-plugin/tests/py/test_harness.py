"""M0a: the test harness itself (isolation, fixtures, s2v detection) and the templates."""

import json
import os
import subprocess
import unittest

import helpers
from helpers import StudioTestCase, git, make_repo
from stdo import paths

REAL_HOME = os.environ.get("STUDIO_TEST_REAL_HOME") or os.path.realpath(os.path.expanduser("~"))


class Isolation(StudioTestCase):
    def test_home_and_user_dirs_are_temporary(self):
        self.assertTrue(os.path.realpath(os.path.expanduser("~")).startswith(self.tmp))
        for name in ("HOME", "S2V_STATE_DIR", "STUDIO_HOME", "CLAUDE_CONFIG_DIR"):
            self.assertTrue(os.environ[name].startswith(self.tmp), name)
        self.assertTrue(paths.user_dir().startswith(self.tmp))
        self.assertNotEqual(os.path.realpath(paths.user_dir()), os.path.join(REAL_HOME, ".claude"))

    def test_leaked_lock_tokens_refuse_the_run(self):
        for name in helpers.LEAK_VARS:
            with self.assertRaises(helpers.LeakedToken):
                helpers.check_no_leaked_tokens({name: "0" * 32})
        helpers.check_no_leaked_tokens({})

    def test_runs_outside_the_real_home(self):
        here = os.path.realpath(os.path.expanduser("~"))
        self.assertNotEqual(here, REAL_HOME)
        self.assertTrue(here.startswith(self.tmp))

    def test_isolated_env_drops_outside_markers(self):
        outside = {"S2V_HEAVY_LOCK_TOKEN": "x", "S2V_TTS_PORT": "1", "S2V_STATE_DIR": "/real",
                   "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s", "STUDIO_SANDBOX": "1",
                   "STUDIO_HOME": "/real", "XDG_CONFIG_HOME": "/real/.config", "PATH": "/bin",
                   "STUDIO_TEST_S2V": "/keep"}
        env = helpers.isolated_env(self.tmp, outside)
        for name in ("S2V_HEAVY_LOCK_TOKEN", "S2V_TTS_PORT", "CLAUDECODE",
                     "CLAUDE_CODE_SESSION_ID", "STUDIO_SANDBOX", "XDG_CONFIG_HOME"):
            self.assertNotIn(name, env)
        self.assertTrue(env["S2V_STATE_DIR"].startswith(self.tmp))
        self.assertTrue(env["STUDIO_HOME"].startswith(self.tmp))
        self.assertEqual(env["STUDIO_TEST_S2V"], "/keep")
        self.assertEqual(env["PATH"], "/bin")

    def test_s2v_env_has_fake_uv_first_and_mock(self):
        env = self.s2v_environ
        self.assertEqual(env["S2V_TTS"], "mock")
        self.assertEqual(env["S2V_NO_OPEN"], "1")
        first = env["PATH"].split(os.pathsep)[0]
        uv = os.path.join(first, "uv")
        self.assertTrue(os.access(uv, os.X_OK))
        out = subprocess.run(["uv", "run", "anything"], env=env, capture_output=True)
        self.assertEqual(out.returncode, helpers.FAKE_UV_EXIT)


class UserDir(unittest.TestCase):
    def test_studio_home_then_config_dir_then_home(self):
        self.assertEqual(paths.user_dir({"STUDIO_HOME": "/a", "CLAUDE_CONFIG_DIR": "/b", "HOME": "/h"}), "/a")
        self.assertEqual(paths.user_dir({"CLAUDE_CONFIG_DIR": "/b", "HOME": "/h"}), "/b")
        self.assertEqual(paths.user_dir({"HOME": "/h"}), "/h/.claude")
        with self.assertRaises(ValueError):
            paths.user_dir({"STUDIO_HOME": "rel"})


class Repos(StudioTestCase):
    def test_harness_repo(self):
        repo = make_repo(self.tmp)
        cfg = json.load(open(os.path.join(repo, ".claude", "studio", "config.json")))
        for key in ("language", "s2v", "visibility", "internal_overlay", "public_domains",
                    "web_roots", "allow_internal_commits", "roles", "models", "gates",
                    "commit_audio", "character_generation", "studio_root", "protected_keys"):
            self.assertIn(key, cfg)
        self.assertEqual(cfg["s2v"]["min_version"], "0.12.1")
        for key in ("visibility", "internal_overlay", "public_domains", "web_roots",
                    "allow_internal_commits", "s2v", "models", "gates", "roles"):
            self.assertIn(key, cfg["protected_keys"])
        self.assertNotIn("sandbox_root", cfg)  # per machine: ~/.claude/studio-sandbox.json
        self.assertEqual(git(repo, "status", "--porcelain").stdout, "")

    def test_gitignore_block(self):
        repo = make_repo(self.tmp, local=True)
        ignored = ["studio/local/x", ".claude/studio/local/x", "studio/out/v/ko/a.mp4",
                   "studio/copy/v/ko/youtube.md", "studio/videos/v/work/state.json",
                   "studio/videos/v/audio/ko/manifest.json", "studio/videos/v/audio/ko/a.wav",
                   "studio/cast/a/work/x", "studio/voices/a/candidates/1.wav"]
        kept = ["studio/videos/v/audio/ko/picks.json", "studio/videos/v/script.ko.md",
                "studio/cast/a/character/character.yaml", "studio/voices/a/ko.wav"]
        for p in ignored:
            self.assertEqual(git(repo, "check-ignore", "-q", p, check=False).returncode, 0, p)
        for p in kept:
            self.assertEqual(git(repo, "check-ignore", "-q", p, check=False).returncode, 1, p)

    def test_custom_studio_root_agrees_in_config_and_gitignore(self):
        repo = make_repo(self.tmp, studio_root="video-studio")
        cfg = json.load(open(os.path.join(repo, ".claude", "studio", "config.json")))
        self.assertEqual(cfg["studio_root"], "video-studio")
        self.assertIn("studio_root", cfg["protected_keys"])
        self.assertTrue(os.path.isdir(os.path.join(repo, "video-studio", "voices")))
        for p in ("video-studio/local/x", "video-studio/out/v/ko/a.mp4"):
            self.assertEqual(git(repo, "check-ignore", "-q", p, check=False).returncode, 0, p)
        self.assertEqual(git(repo, "check-ignore", "-q", "studio/out/x", check=False).returncode, 1)

    def test_no_harness_repo(self):
        repo = make_repo(self.tmp, harness=False)
        self.assertFalse(os.path.exists(os.path.join(repo, ".claude", "studio")))

    def test_marker_lives_under_studio_home_and_is_shared_by_worktrees(self):
        repo = make_repo(self.tmp, marker=True)
        m = paths.marker_path(repo)
        self.assertTrue(m.startswith(os.environ["STUDIO_HOME"]))
        self.assertEqual(json.load(open(m)), {"studio_root": "studio"})
        wt = os.path.join(self.tmp, "wt")
        git(repo, "worktree", "add", "-q", wt)
        self.assertEqual(paths.common_key(wt), paths.common_key(repo))
        self.assertNotEqual(paths.repo_key(wt), paths.repo_key(repo))
        self.assertEqual(paths.marker_path(wt), m)

    def test_template_placeholders_must_all_be_filled(self):
        with self.assertRaises(ValueError):
            helpers.render_template("a {{X}} {{Y}}", {"X": "1"})


class HookInputs(StudioTestCase):
    def test_hook_input_and_transcript(self):
        t = helpers.fake_transcript(os.path.join(self.tmp, "t.jsonl"), [{"type": "user", "n": 1}])
        h = helpers.hook_input("Bash", {"command": "ls"}, self.tmp, transcript=t)
        self.assertEqual(h["hook_event_name"], "PreToolUse")
        self.assertEqual(json.loads(json.dumps(h))["tool_input"], {"command": "ls"})
        self.assertEqual([json.loads(l) for l in open(t)], [{"type": "user", "n": 1}])


class S2VDetection(unittest.TestCase):
    def test_missing_env_names_the_variable(self):
        path, why = helpers.resolve_s2v({})
        self.assertIsNone(path)
        self.assertIn("STUDIO_TEST_S2V", why)
        self.assertIn("--full", why)

    def test_set_but_unusable_fails_even_in_default_mode(self):
        saved = dict(os.environ), dict(helpers._s2v_cache)
        try:
            os.environ["STUDIO_TEST_S2V"] = "/nonexistent-s2v"
            os.environ["STUDIO_TEST_FULL"] = "0"
            helpers._s2v_cache.clear()
            with self.assertRaises(AssertionError):
                helpers.s2v_path()
            os.environ.pop("STUDIO_TEST_S2V")
            helpers._s2v_cache.clear()
            with self.assertRaises(unittest.SkipTest):
                helpers.s2v_path()
        finally:
            os.environ.clear()
            os.environ.update(saved[0])
            helpers._s2v_cache.clear()
            helpers._s2v_cache.update(saved[1])

    def test_relative_or_unbuilt_path(self):
        self.assertIn("absolute", helpers.resolve_s2v({"STUDIO_TEST_S2V": "rel"})[1])
        self.assertIn("dist/main.js", helpers.resolve_s2v({"STUDIO_TEST_S2V": "/nonexistent"})[1])

    def test_version_rules(self):
        ok = {"version": "0.12.1", "id": "0.12.1+abc", "stale_build": False}
        self.assertEqual(helpers.check_version_info(ok), [])
        self.assertTrue(helpers.check_version_info(dict(ok, version="0.12.0")))
        self.assertTrue(helpers.check_version_info(dict(ok, stale_build=True)))
        self.assertTrue(helpers.check_version_info(dict(ok, version="x")))
        self.assertEqual(helpers.check_version_info(dict(ok, version="0.13.0")), [])


class RealS2V(StudioTestCase):
    """Needs STUDIO_TEST_S2V (skipped by default, required by --full)."""

    def test_version_under_isolation(self):
        out = helpers.run_s2v(self, ["--version", "--json"])
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(helpers.check_version_info(json.loads(out.stdout)), [])

    def test_state_dir_is_the_isolated_one(self):
        out = helpers.run_s2v(self, ["services", "status", "--json"])
        self.assertEqual(out.returncode, 0, out.stderr)
        status = json.loads(out.stdout)
        self.assertEqual(os.path.realpath(status["state_dir"]),
                         os.path.realpath(self.s2v_environ["S2V_STATE_DIR"]))


class Npx(unittest.TestCase):
    """npx is needed by the hook-manager tests (M0e); skipped by default, required by --full."""

    def test_npx_runs(self):
        if not helpers.full_mode():
            raise unittest.SkipTest("needs npx: run with run_tests.sh --full")
        out = subprocess.run(["npx", "--version"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
