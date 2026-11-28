"""Readiness T1 R4-14 — one channel per repository: the channel file, the routing / engine-entry verdict, the switch
(unfinished runs of the channel that is not the target, the commit gate of the target). Real git, no GitHub."""

import io
import json
import os
import stat
import subprocess
import tempfile
import unittest

from gxengine import channel, cli, paths as pathsmod, store
from tests.helpers import fakes
from tests.helpers.gitrepo import GitRepo

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.realpath(os.path.join(ENGINE, "..", "..", ".."))
REPO = "acme/app"
SELF, OTHER = channel.SELF, channel.OTHER
SELF_CFG = channel.CONFIG_DIR[SELF] + "/config.json"
OTHER_CFG = channel.CONFIG_DIR[OTHER] + "/config.json"


class Base(unittest.TestCase):
    files = {"README.md": "app\n"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = os.path.realpath(self._tmp.name)
        self.repo = GitRepo.create(self.tmp, name="app", files=dict(self.files))
        self.top = self.repo.path
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        cfg = os.path.join(self.tmp, "gitconfig-hooks")       # the test config without core.hooksPath=/dev/null
        with open(os.path.join(self.tmp, "gitconfig"), encoding="utf-8") as f:
            text = f.read().replace("\thooksPath = /dev/null\n", "")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(text)
        self.environ = dict(self.repo.env, HOME=self.home, GIT_CONFIG_GLOBAL=cfg,
                            GLD_ENGINE_HOME=os.path.join(self.tmp, "gld"), GX_ENGINE_HOME=os.path.join(self.tmp, "gldx"))  # promote: other

    def put(self, rel, text="{}\n"):
        path = os.path.join(self.top, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read(self, rel):
        with open(os.path.join(self.top, rel), encoding="utf-8") as f:
            return f.read()

    def cli(self, *argv):
        out = io.StringIO()
        rc = cli.main(list(argv), environ=self.environ, out=out)
        return rc, out.getvalue()

    def hook(self):
        return subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-commit"],
                              cwd=self.top, capture_output=True, text=True, check=True, env=self.environ).stdout.strip()


class Verdict(Base):
    """The rule of the routing (SKILL.md) and of the engine's write commands."""

    def test_the_file_decides(self):
        self.put(channel.CHANNEL_FILE, SELF + "\n")
        self.put(OTHER_CFG)
        self.assertTrue(channel.verdict(self.top)["allowed"])
        self.put(channel.CHANNEL_FILE, OTHER + "\n")
        v = channel.verdict(self.top)
        self.assertFalse(v["allowed"])
        self.assertEqual(v["message"], f"this repository's active channel is {OTHER} ({channel.CHANNEL_FILE}) — use "
                                       f"/{OTHER}, or switch this repository to {SELF} with /{SELF} channel {SELF}")

    def test_a_file_that_names_neither_refuses(self):
        for text in ("", "both\n", "gldxx\n"):  # promote: literal
            with self.subTest(text=text):
                self.put(channel.CHANNEL_FILE, text)
                v = channel.verdict(self.top)
                self.assertFalse(v["allowed"])
                self.assertIn(f"/{SELF} channel {SELF} or /{SELF} channel {OTHER}", v["message"])

    def test_no_file(self):
        self.assertTrue(channel.verdict(self.top)["allowed"], "nothing set up: a first init")
        self.put(SELF_CFG)
        self.assertTrue(channel.verdict(self.top)["allowed"], "only this channel")
        self.put(channel.CONFIG_DIR[OTHER] + "/harness.json")
        v = channel.verdict(self.top)
        self.assertFalse(v["allowed"], "both channels and no choice")
        self.assertIn("both channels are set up here", v["message"])

    def test_only_the_other_channel_without_a_file_is_allowed(self):
        """A repository of 0.98.7 alone: this channel's first init may run (it writes the file)."""
        self.put(OTHER_CFG)
        self.assertTrue(channel.verdict(self.top)["allowed"])

    def test_a_subfolder_and_no_repository(self):
        self.put(channel.CHANNEL_FILE, OTHER + "\n")
        os.makedirs(os.path.join(self.top, "src"))
        self.assertFalse(channel.verdict(os.path.join(self.top, "src"))["allowed"])
        self.assertTrue(channel.verdict(self.home)["allowed"])

    def test_show_cli(self):
        rc, text = self.cli("channel", "show", "--checkout", self.top)
        self.assertEqual(rc, 0, text)
        self.put(channel.CHANNEL_FILE, OTHER + "\n")
        rc, text = self.cli("channel", "show", "--checkout", self.top)
        self.assertEqual(rc, 4)
        self.assertTrue(text.startswith("refused: this repository's active channel is"))
        rc, text = self.cli("channel", "show", "--checkout", self.top, "--json")
        self.assertEqual((rc, json.loads(text)["file"], json.loads(text)["allowed"]), (4, OTHER, False))

    def test_the_engine_write_commands_refuse_at_their_entry(self):
        self.put(channel.CHANNEL_FILE, OTHER + "\n")
        for argv in (["dev", "--repo", REPO, "--issue", "42", "--checkout", self.top],
                     ["sprint", "run", "--repo", REPO, "--tracker", "700", "--checkout", self.top],
                     ["init", "propose", "--repo", REPO, "--checkout", self.top],
                     ["base-check", "--repo", REPO, "--checkout", self.top]):
            with self.subTest(argv=argv[0]):
                rc, text = self.cli(*argv)
                self.assertEqual(rc, 4, text)
                self.assertIn("this repository's active channel is", text)
        self.assertFalse(os.path.exists(self.environ["GLD_ENGINE_HOME"]), "nothing was started")

    def test_resume_refuses_by_the_recorded_checkout(self):
        paths = pathsmod.EnginePaths(self.environ["GLD_ENGINE_HOME"], REPO, 42)
        with open(fakes.fixture("contracts", "state.stage4.example.json"), encoding="utf-8") as f:
            state = json.load(f)
        state["git"]["main_checkout"] = self.top
        store.save_state(paths, state)
        self.put(channel.CHANNEL_FILE, OTHER + "\n")
        rc, text = self.cli("resume", "--repo", REPO, "--issue", "42")
        self.assertEqual(rc, 4)
        self.assertIn("this repository's active channel is", text)

    def test_read_commands_are_not_refused(self):
        self.put(channel.CHANNEL_FILE, OTHER + "\n")
        rc, text = self.cli("status", "--repo", REPO, "--issue", "42")
        self.assertEqual(rc, 0, text)

    def test_the_file_name_is_no_channel_value(self):
        """Promotion renames the channel names (tools/promote); the shared file must survive it unchanged."""
        for value in (SELF, OTHER, "guild-plugin"):
            self.assertNotIn(value + "/", channel.CHANNEL_FILE + "/")
            self.assertFalse(channel.CHANNEL_FILE.endswith("/" + value))


class Unfinished(Base):
    def record(self, home, issue, **change):
        paths = pathsmod.EnginePaths(home, REPO, issue)
        with open(fakes.fixture("contracts", "state.stage4.example.json"), encoding="utf-8") as f:
            state = json.load(f)
        state["issue"] = issue
        state.update(change)
        store.save_state(paths, state)
        return state

    def test_issues_and_sprints(self):
        home = self.environ["GX_ENGINE_HOME"]  # promote: other
        st = self.record(home, 5)
        self.assertEqual(channel.unfinished_runs(home, REPO)[0]["number"], 5)
        done = dict(st, stop=None, github=dict(st.get("github") or {}, pr_number=9),
                    steps=[dict(s, status="done") for s in st["steps"]])
        self.record(home, 5, **{k: done[k] for k in ("stop", "github", "steps")})
        self.assertEqual(channel.unfinished_runs(home, REPO), [], "finished with a pull request")
        self.record(home, 6, closed={"reason": "completed", "comment_id": 1, "at": "2026-11-27T00:00:00Z"})
        self.assertEqual(channel.unfinished_runs(home, REPO), [], "closed as decided")
        sp = pathsmod.SprintPaths(home, REPO, 700)
        with open(fakes.fixture("contracts", "sprint-state.example.json"), encoding="utf-8") as f:
            sprint = json.load(f)
        sprint.update(repo=REPO, tracker=700, state="running", halt=None)
        store.save_sprint(sp, sprint)
        self.assertEqual(channel.unfinished_runs(home, REPO), [{"kind": "sprint", "number": 700, "why": "running"}])
        self.assertEqual(channel.unfinished_runs(home, "acme/other"), [])

    def test_a_missing_home_has_none(self):
        self.assertEqual(channel.unfinished_runs(os.path.join(self.tmp, "nowhere"), REPO), [])


class Switch(Unfinished):
    files = {"README.md": "app\n", SELF_CFG: "{}\n", channel.gate_path(SELF): "# gate\n",
             channel.gate_path(OTHER): "# stable gate\n"}

    def set(self, target, *extra):
        return self.cli("channel", "set", target, "--repo", REPO, "--checkout", self.top, *extra)

    def test_to_the_other_channel_and_back_with_the_plain_hook(self):
        rc, text = self.set(OTHER)
        self.assertEqual(rc, 0, text)
        self.assertEqual(self.read(channel.CHANNEL_FILE), OTHER + "\n")
        with open(self.hook(), encoding="utf-8") as f:
            shim = f.read()
        self.assertIn(f'GATE="$ROOT/{channel.gate_path(OTHER)}"', shim)
        self.assertNotIn(channel.gate_path(SELF), shim)
        self.assertTrue(os.stat(self.hook()).st_mode & stat.S_IXUSR)
        self.assertIn(f"switched: {channel.CHANNEL_FILE} (none) -> {OTHER}", text)
        rc, text = self.cli("channel", "show", "--checkout", self.top)
        self.assertEqual(rc, 4, "this channel now refuses itself")
        rc, text = self.set(SELF)
        self.assertEqual(rc, 0, text)
        self.assertEqual(self.read(channel.CHANNEL_FILE), SELF + "\n")
        with open(self.hook(), encoding="utf-8") as f:
            self.assertIn(f'GATE="$ROOT/{channel.gate_path(SELF)}"', f.read())

    def test_a_hand_written_hook_is_kept_and_chained(self):
        os.makedirs(os.path.dirname(self.hook()), exist_ok=True)
        with open(self.hook(), "w") as f:
            f.write("#!/bin/sh\necho mine\n")
        rc, text = self.set(OTHER)
        self.assertEqual(rc, 0, text)
        with open(self.hook() + ".local") as f:
            self.assertEqual(f.read(), "#!/bin/sh\necho mine\n")
        with open(self.hook()) as f:
            self.assertIn(channel.gate_path(OTHER), f.read())

    def test_lefthook_gets_the_registered_command_swapped(self):
        yml = ("pre-commit:\n  parallel: true\n  commands:\n    lint:\n      run: make lint\n    guild-gate:\n"
               f"      run: python3 {channel.gate_path(SELF)} --git-hook\n")
        self.put("lefthook.yml", yml)
        os.makedirs(os.path.dirname(self.hook()), exist_ok=True)
        with open(self.hook(), "w") as f:
            f.write("#!/bin/sh\n# lefthook generated\nlefthook run pre-commit\n")
        rc, text = self.set(OTHER, "--dry-run")
        self.assertEqual(rc, 0, text)
        self.assertIn("would switch", text)
        self.assertEqual(self.read("lefthook.yml"), yml, "a dry run writes nothing")
        self.assertFalse(os.path.exists(os.path.join(self.top, channel.CHANNEL_FILE)))
        rc, text = self.set(OTHER)
        self.assertEqual(rc, 0, text)
        self.assertEqual(self.read("lefthook.yml"), yml.replace(channel.gate_path(SELF), channel.gate_path(OTHER)))
        with open(self.hook()) as f:
            self.assertIn("lefthook run", f.read(), "the manager keeps its hook")
        self.assertIn("lefthook.yml: the registered gate command now runs", text)

    def test_a_manager_without_a_registration_is_left_to_the_human(self):
        os.makedirs(os.path.dirname(self.hook()), exist_ok=True)
        with open(self.hook(), "w") as f:
            f.write("#!/bin/sh\nlefthook run pre-commit\n")
        rc, text = self.set(OTHER)
        self.assertEqual(rc, 0, text)
        self.assertIn("no Guild gate command is registered", text)

    def test_unfinished_runs_of_the_channel_that_is_not_the_target_refuse(self):
        self.record(self.environ["GLD_ENGINE_HOME"], 12)
        rc, text = self.set(OTHER)
        self.assertEqual(rc, 4)
        self.assertIn(f"refused: the {SELF} channel still has engine runs of {REPO} on this machine", text)
        self.assertIn("#12 (", text)
        self.assertFalse(os.path.exists(os.path.join(self.top, channel.CHANNEL_FILE)), "nothing written")
        self.assertFalse(os.path.exists(self.hook()))
        rc, text = self.set(SELF)
        self.assertEqual(rc, 0, "the target's own runs do not matter")

    def test_the_other_channels_runs_refuse_the_way_back(self):
        self.record(self.environ["GX_ENGINE_HOME"], 7)  # promote: other
        rc, text = self.set(SELF)
        self.assertEqual(rc, 4)
        self.assertIn(f"the {OTHER} channel still has engine runs", text)

    def test_notes_a_missing_gate_and_unignores_the_file(self):
        """FC M4: app_a's .gitignore has `.claude/*` — the switch adds the exception and says to commit it."""
        os.remove(os.path.join(self.top, channel.gate_path(OTHER)))
        self.put(".gitignore", "build/\n.claude/*\n!.claude/agents/")
        rc, text = self.set(OTHER, "--dry-run")
        self.assertIn(f"the switch adds `!{channel.CHANNEL_FILE}` to .gitignore", text)
        self.assertEqual(self.read(".gitignore"), "build/\n.claude/*\n!.claude/agents/", "a dry run writes nothing")
        rc, text = self.set(OTHER)
        self.assertEqual(rc, 0, text)
        self.assertIn(f"{channel.gate_path(OTHER)} is not in this checkout", text)
        self.assertIn(f"added `!{channel.CHANNEL_FILE}` to .gitignore", text)
        self.assertIn(f"commit {channel.CHANNEL_FILE} and .gitignore", text)
        self.assertEqual(self.read(".gitignore"), f"build/\n.claude/*\n!.claude/agents/\n!{channel.CHANNEL_FILE}\n")
        r = subprocess.run(["git", "check-ignore", "-q", channel.CHANNEL_FILE], cwd=self.top, env=self.environ)
        self.assertEqual(r.returncode, 1, "no longer ignored")
        rc, text = self.set(SELF)                                  # already visible: .gitignore is not touched again
        self.assertEqual(self.read(".gitignore").count(f"!{channel.CHANNEL_FILE}"), 1)

    def test_an_ignored_parent_folder_is_left_to_the_human(self):
        self.put(".gitignore", ".claude/\n")
        rc, text = self.set(OTHER)
        self.assertEqual(rc, 0, text)
        self.assertIn("does not bring it back", text)
        self.assertEqual(self.read(".gitignore"), ".claude/\n", "put back as it was")
        self.assertIn(f"commit {channel.CHANNEL_FILE} (and", text)

    def test_unknown_target_and_no_checkout(self):
        rc, _ = self.cli("channel", "set", "stable", "--repo", REPO, "--checkout", self.top)
        self.assertEqual(rc, 2)
        rc, text = self.cli("channel", "set", OTHER, "--repo", REPO, "--checkout", self.home)
        self.assertEqual(rc, 4)
        self.assertIn("is not a git checkout", text)
