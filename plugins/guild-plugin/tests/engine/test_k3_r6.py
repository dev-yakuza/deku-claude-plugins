"""K3 review r6 — engine writes into role-shaped trees go through `guildcore.fsafe` (B1): the reviewer's
`.cspell.json` → outside file and `dict/` → outside dir probes, the journal restore, and a lint that no
raw write call remains outside fsafe without an `# fs-ok:` reason."""

import ast
import json
import os
import re
import unittest

import _util
from _k1 import git, repo, tmpdir

from guildcore import fsafe as FS
from workflows.dev import ports as PO

ENGINE = _util.ENGINE
RAW = re.compile(r"open\([^)]*['\"](w|wb|a|ab|x)['\"]|copyfile\(|copy2\(|copytree\(|shutil\.copy\(|_sh\.copy\(|"
                 r"os\.(replace|rename|symlink)\(|write_text\(|write_bytes\(")


class Fsafe(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.out = tmpdir(self)
        with open(os.path.join(self.out, "victim.txt"), "w") as fh:
            fh.write("PRECIOUS")

    def test_refuses_links_absolute_and_dotdot(self):
        os.symlink(os.path.join(self.out, "victim.txt"), os.path.join(self.root, "leaf"))
        os.symlink(self.out, os.path.join(self.root, "dir"))
        for rel in ("leaf", "dir/victim.txt", "dir/new.txt", "/etc/x", "../x", "a/../../x"):
            with self.assertRaises(FS.UnsafePath, msg=rel):
                FS.write_bytes(self.root, rel, b"x")
        self.assertEqual(open(os.path.join(self.out, "victim.txt")).read(), "PRECIOUS")
        self.assertFalse(os.path.exists(os.path.join(self.out, "new.txt")))

    def test_atomic_write_and_link_replace(self):
        FS.write_text(self.root, "a/b.txt", "hi")
        self.assertEqual(open(os.path.join(self.root, "a/b.txt")).read(), "hi")
        os.symlink(os.path.join(self.out, "victim.txt"), os.path.join(self.root, "nm"))
        FS.symlink(self.root, "nm", "/nonexistent/target")             # the LINK is replaced, target untouched
        self.assertEqual(os.readlink(os.path.join(self.root, "nm")), "/nonexistent/target")
        self.assertEqual(open(os.path.join(self.out, "victim.txt")).read(), "PRECIOUS")


class ReviewerProbes(unittest.TestCase):
    def setUp(self):
        self.r = repo(self, {".cspell.json": json.dumps({"words": ["a"], "dictionaryDefinitions": [
            {"name": "p", "path": "./dict/words.txt"}]}), "dict/words.txt": "alpha\n"})
        self.base = git(self.r, "rev-parse", "HEAD")
        self.out = tmpdir(self)
        os.environ["GLD_ENGINE_RUNS"] = tmpdir(self)
        self.addCleanup(os.environ.pop, "GLD_ENGINE_RUNS", None)

    def test_cspell_config_symlink_refuses_and_writes_nothing(self):
        victim = os.path.join(self.out, "victim.txt")
        with open(victim, "w") as fh:
            fh.write("PRECIOUS")
        os.remove(os.path.join(self.r, ".cspell.json"))
        os.symlink(victim, os.path.join(self.r, ".cspell.json"))
        with self.assertRaises(PO.CheckConfigLink):
            PO.base_check_configs(self.r, self.base)
        self.assertEqual(open(victim).read(), "PRECIOUS")
        self.assertTrue(os.path.islink(os.path.join(self.r, ".cspell.json")))

    def test_dict_directory_symlink_refuses(self):
        os.makedirs(os.path.join(self.out, "dictdir"))
        with open(os.path.join(self.out, "dictdir", "words.txt"), "w") as fh:
            fh.write("OUTSIDE\n")
        import shutil
        shutil.rmtree(os.path.join(self.r, "dict"))
        os.symlink(os.path.join(self.out, "dictdir"), os.path.join(self.r, "dict"))
        with self.assertRaises(PO.CheckConfigLink):
            PO.base_check_configs(self.r, self.base)
        self.assertEqual(open(os.path.join(self.out, "dictdir", "words.txt")).read(), "OUTSIDE\n")

    def test_restore_does_not_follow_a_link_planted_after_the_swap(self):
        with open(os.path.join(self.r, ".cspell.json"), "w") as fh:
            json.dump({"words": ["a", "b"]}, fh)
        PO.base_check_configs(self.r, self.base)                         # journaled, swapped … engine dies
        victim = os.path.join(self.out, "victim.txt")
        with open(victim, "w") as fh:
            fh.write("PRECIOUS")
        os.remove(os.path.join(self.r, ".cspell.json"))
        os.symlink(victim, os.path.join(self.r, ".cspell.json"))       # a role plants a link meanwhile
        PO.recover_check_backup(self.r)
        self.assertEqual(open(victim).read(), "PRECIOUS")

    def test_word_list_cap(self):
        with open(os.path.join(self.r, "dict", "words.txt"), "w") as fh:
            fh.write("\n".join("w%d" % i for i in range(PO.WORDLIST_MAX_LINES + 5)))
        restore = PO.base_check_configs(self.r, self.base)
        self.assertEqual(open(os.path.join(self.r, "dict", "words.txt")).read(), "alpha\n\n")
        restore()


class NoRawWrites(unittest.TestCase):
    def test_every_raw_write_is_fsafe_or_justified(self):
        bad = []
        for base, _dirs, files in os.walk(ENGINE):
            if "/replay" in base or "__pycache__" in base:
                continue
            for f in files:
                if not f.endswith(".py") or f == "fsafe.py":
                    continue
                p = os.path.join(base, f)
                for i, ln in enumerate(open(p, encoding="utf-8").read().split("\n"), 1):
                    code = ln.split("#")[0] if "fs-ok" not in ln else ""
                    if RAW.search(code) and "FS." not in code:
                        bad.append("%s:%d" % (os.path.relpath(p, ENGINE), i))
        self.assertEqual(bad, [], "raw engine writes without fsafe or `# fs-ok:`")


if __name__ == "__main__":
    unittest.main()
