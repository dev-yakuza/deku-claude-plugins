"""Readiness T2 — init (design/guild/24-redesign/readiness/promote/t2-init.md).

R4-3 / parity P6: which role files init §2 writes — the channel value `writes_role_files` decides (on only in the
stable channel), an existing role file is never written over and its differences are reported. Every rule is tested
with the value on AND off (the table is patched; the shipped table is checked as it is). Real git, no GitHub."""

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from gxengine import channel, cli, initharness
from tests.helpers.gitrepo import GitRepo

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.realpath(os.path.join(ENGINE, "..", "..", ".."))
REPO = "acme/app"


def turned(name, on):
    """Patch this channel's row of the channel value table: `name` on / off."""
    row = dict(channel.VALUES[channel.SELF], **{name: on})
    return mock.patch.dict(channel.VALUES, {channel.SELF: row})


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
        self.environ = dict(self.repo.env, HOME=self.home, GLD_ENGINE_HOME=os.path.join(self.tmp, "gld"),
                            GX_ENGINE_HOME=os.path.join(self.tmp, "gldx"))  # promote: other

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

    def role(self, role, text=None):
        """A role file filled from this plugin's template (placeholders replaced, as init §2 leaves it)."""
        if text is None:
            text = initharness.template_text(PLUGIN_ROOT, role).replace("{{", "<").replace("}}", ">")
        return self.put(f"{initharness.AGENTS_DIR}/{role}.md", text)


class ChannelValues(unittest.TestCase):
    def test_the_shipped_table(self):
        """Keyed by the channel NAME (promote: literal): the development row is off, the stable row is on — the
        promoted tree, whose SELF is the stable name, reads the stable row."""
        self.assertEqual(channel.VALUES["gldx"], {"writes_role_files": False, "writes_knowledge": False})  # promote: literal
        self.assertEqual(channel.VALUES["gld"], {"writes_role_files": True, "writes_knowledge": True})  # promote: literal
        self.assertEqual(set(channel.VALUES), set(channel.CHANNELS))
        self.assertIs(channel.value("writes_role_files"), channel.VALUES[channel.SELF]["writes_role_files"])
        self.assertIs(channel.value("writes_role_files", "gld"), True)  # promote: literal
        with self.assertRaises(KeyError):
            channel.value("writes_everything")

    def test_the_table_lines_are_marked_literal(self):
        with open(channel.__file__, encoding="utf-8") as f:
            lines = [x for x in f if x.lstrip().startswith(('"gldx": {"writes', '"gld": {"writes'))]  # promote: literal
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("promote: literal" in x for x in lines), lines)

    def test_show_names_the_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = channel.verdict(tmp)
        self.assertEqual(v["values"], channel.VALUES[channel.SELF])


class Roles(Base):
    def test_the_roster_is_the_templates(self):
        names = sorted(f[:-3] for f in os.listdir(os.path.join(PLUGIN_ROOT, initharness.TEMPLATES)) if f.endswith(".md"))
        self.assertEqual(sorted(initharness.ROSTER), names)
        self.assertEqual(len(initharness.ROSTER), 16)

    def test_on_writes_the_missing_ones_only(self):
        self.role("leader")
        self.role("developer")
        with turned("writes_role_files", True):
            rep = initharness.roles(self.top, PLUGIN_ROOT)
        self.assertTrue(rep["writes_role_files"])
        self.assertEqual(rep["write"], [r for r in initharness.ROSTER if r not in ("leader", "developer")])
        self.assertNotIn("leader", rep["write"])
        self.assertEqual([e["role"] for e in rep["existing"]], ["leader", "developer"])
        self.assertEqual(rep["roles"], list(initharness.ROSTER))

    def test_off_writes_none(self):
        self.role("leader")
        with turned("writes_role_files", False):
            rep = initharness.roles(self.top, PLUGIN_ROOT)
        self.assertFalse(rep["writes_role_files"])
        self.assertEqual(rep["write"], [])
        self.assertEqual(rep["missing"], [r for r in initharness.ROSTER if r != "leader"])
        self.assertEqual(rep["roles"], ["leader"], "harness.json lists what exists")
        self.assertEqual(rep["existing"][0]["differences"], [], "nothing compared when this channel writes none")
        self.assertIn("writes no role file: the stable channel's init writes them", initharness.format_roles(rep))

    def test_an_existing_file_as_the_template_has_no_difference(self):
        self.role("qa")
        with turned("writes_role_files", True):
            rep = initharness.roles(self.top, PLUGIN_ROOT)
        self.assertEqual(rep["existing"], [{"role": "qa", "path": ".claude/agents/qa.md", "differences": []}])
        self.assertIn("  qa: as the template", initharness.format_roles(rep))

    def test_differences_are_reported_and_the_file_is_kept(self):
        tpl = initharness.template_text(PLUGIN_ROOT, "developer")
        text = (tpl.replace("model: sonnet", "model: opus")
                .replace(initharness.PERSONA_HABITS + "\n", "")
                .replace("최소·명확한 구현.", "최소 구현."))
        path = self.role("developer", text)
        with turned("writes_role_files", True):
            rep = initharness.roles(self.top, PLUGIN_ROOT)
        diff = rep["existing"][0]["differences"]
        self.assertIn("frontmatter model: 'opus' (template 'sonnet')", diff)
        self.assertTrue(any(d.startswith(initharness.PERSONA_HABITS + " appears 0 time(s)") for d in diff), diff)
        self.assertTrue(any(d.startswith("the persona region differs") for d in diff), diff)
        self.assertIn("a `{{…}}` placeholder is left in the file", diff)
        self.assertNotIn("developer", rep["write"])
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), text, "the engine wrote nothing")

    def test_a_file_of_the_other_channel_lacks_this_channels_markers(self):
        """A role file whose markers are not this channel's (a 0.98.7 file in the development channel) is kept and
        named — `update` keys on this channel's markers."""
        tpl = initharness.template_text(PLUGIN_ROOT, "tester").replace(channel.SELF, "x")
        text = tpl.replace(initharness.PERSONA_START, "<!-- other:persona:start -->")
        self.role("tester", text)
        with turned("writes_role_files", True):
            rep = initharness.roles(self.top, PLUGIN_ROOT)
        self.assertTrue(any("appears 0 time(s)" in d for d in rep["existing"][0]["differences"]))

    def test_other_role_files_are_kept_and_listed(self):
        self.role("leader")
        self.put(".claude/agents/mobile.md", "---\nname: mobile\n---\n")
        for on in (True, False):
            with self.subTest(on=on), turned("writes_role_files", on):
                rep = initharness.roles(self.top, PLUGIN_ROOT)
                self.assertEqual(rep["others"], ["mobile"])
                self.assertEqual(rep["roles"][-1], "mobile")
                self.assertNotIn("mobile", rep["write"])

    def test_a_linked_folder_is_refused(self):
        os.makedirs(os.path.join(self.tmp, "elsewhere"))
        os.makedirs(os.path.join(self.top, ".claude"))
        os.symlink(os.path.join(self.tmp, "elsewhere"), os.path.join(self.top, initharness.AGENTS_DIR))
        with self.assertRaises(initharness.Refused):
            initharness.roles(self.top, PLUGIN_ROOT)
        rc, text = self.cli("init", "roles", "--repo", REPO, "--checkout", self.top)
        self.assertEqual(rc, 4)
        self.assertIn("is not a plain folder", text)

    def test_cli(self):
        self.role("leader")
        for on in (True, False):
            with self.subTest(on=on), turned("writes_role_files", on):
                rc, text = self.cli("init", "roles", "--repo", REPO, "--checkout", self.top, "--json")
                self.assertEqual(rc, 0, text)
                rep = json.loads(text)
                self.assertEqual(rep["writes_role_files"], on)
                self.assertEqual(len(rep["write"]), 15 if on else 0)
                rc, text = self.cli("init", "roles", "--repo", REPO, "--checkout", self.top)
                self.assertEqual(rc, 0)
                self.assertTrue(text.startswith("role files (.claude/agents/): 1 of 16 exist"), text)
                self.assertEqual("write (missing): " in text, on)

    def test_not_a_checkout(self):
        rc, text = self.cli("init", "roles", "--repo", REPO, "--checkout", self.home)
        self.assertEqual(rc, 4)
        self.assertIn("is not a git checkout", text)

    def test_refused_by_the_other_channel(self):
        self.put(channel.CHANNEL_FILE, channel.OTHER + "\n")
        rc, text = self.cli("init", "roles", "--repo", REPO, "--checkout", self.top)
        self.assertEqual(rc, 4)
        self.assertIn("active channel is", text)


SKILL = os.path.join(PLUGIN_ROOT, "skills", channel.SELF)


class Knowledge(unittest.TestCase):
    """R4-13 K2: ⑥ knowledge is one folder both channels read; only the stable channel writes it."""

    def test_the_path_is_shared_and_marked_literal(self):
        from gxengine import defaults
        self.assertEqual(defaults.KNOWLEDGE_DIR, ".claude/" + "guild" + "/knowledge")
        self.assertFalse(defaults.KNOWLEDGE_DIR.startswith(channel.CONFIG_DIR[channel.SELF] + "/")
                         and channel.SELF != "gld", "the development channel reads it outside its own folder")  # promote: literal
        with open(defaults.__file__, encoding="utf-8") as f:
            line = next(x for x in f if x.startswith("KNOWLEDGE_DIR ="))
        self.assertIn("promote: literal", line)
        self.assertIn("rename" + "-exception", line)               # (split: this file is no tagged file itself)

    def test_the_role_frames_read_it(self):
        from gxengine import defaults, instructions, codes
        texts = {"work": instructions.frame("work", "developer", codes.RoleClass.WORK.value),
                 "judge": instructions.frame("review", "qa", codes.RoleClass.JUDGE.value),
                 "leader": instructions.leader_frame()}
        for kind, text in texts.items():
            with self.subTest(kind=kind):
                self.assertIn(f"If `{defaults.KNOWLEDGE_DIR}/index.md` exists, read it", text)
                self.assertNotIn(instructions.KNOWLEDGE_TOKEN, text)
                if channel.CONFIG_DIR[channel.SELF] + "/knowledge" != defaults.KNOWLEDGE_DIR:   # the stable channel: the same
                    self.assertNotIn(channel.CONFIG_DIR[channel.SELF] + "/knowledge", text)

    def test_the_value_decides_who_writes(self):
        for on in (True, False):
            with self.subTest(on=on), turned("writes_knowledge", on), tempfile.TemporaryDirectory() as tmp:
                v = channel.verdict(tmp)
                self.assertIs(v["values"]["writes_knowledge"], on)
                self.assertEqual(v["knowledge_dir"], ".claude/" + "guild" + "/knowledge")
        self.assertIs(channel.value("writes_knowledge", "gldx"), False)  # promote: literal
        self.assertIs(channel.value("writes_knowledge", "gld"), True)  # promote: literal

    def test_the_commands_name_the_shared_folder_and_the_value(self):
        """Every LLM command line that names ⑥ names the shared folder (none names this channel's own); the two
        writers (init's seed, evolve's ⑥ items) ask the channel value first."""
        from gxengine import defaults
        own = channel.CONFIG_DIR[channel.SELF] + "/knowledge"
        for folder in ("commands", "templates"):
            for dirpath, _, names in os.walk(os.path.join(SKILL, folder)):
                for n in names:
                    if not n.endswith((".md", ".py", ".tmpl")):
                        continue
                    with open(os.path.join(dirpath, n), encoding="utf-8") as f:
                        for i, line in enumerate(f, 1):
                            if own in line and channel.SELF != "gld":  # promote: literal
                                self.fail(f"{n}:{i} names {own}")
                            if defaults.KNOWLEDGE_DIR in line and n.endswith(".md"):
                                # tagged with its reason; the promote tool keeps the path itself (a global literal)
                                self.assertIn("K2 shared knowledge", line, f"{n}:{i}")
        for rel in ("commands/init.md", "commands/evolve.md", "commands/atoms/_knowledge.md"):
            with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
                self.assertIn("writes_knowledge", f.read(), rel)

    def test_harness_size_measures_the_shared_folder(self):
        import importlib.util
        from gxengine import defaults
        spec = importlib.util.spec_from_file_location("harness_size", os.path.join(SKILL, "commands", "atoms",
                                                                                   "harness_size.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.KNOWLEDGE, defaults.KNOWLEDGE_DIR)


if __name__ == "__main__":
    unittest.main()
