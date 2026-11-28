"""U2 — link-refusing atomic writes (fsafe.py, design §7.12 S6; scope §5.2 S12)."""

import json
import os
import shutil
import stat
import tempfile
import unittest

from gxengine import fsafe
from gxengine.fsafe import UnsafePath


class Base(unittest.TestCase):
    def setUp(self):
        # realpath: on macOS the temp dir sits below /var → /private/var (a link).
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="gx-fsafe-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.outside = os.path.realpath(tempfile.mkdtemp(prefix="gx-outside-"))
        self.addCleanup(shutil.rmtree, self.outside, True)

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def outside_untouched(self):
        self.assertEqual(os.listdir(self.outside), [], "nothing may be written through a link")

    def no_temp_left(self, d):
        self.assertEqual([n for n in os.listdir(d) if n.startswith(".gx-")], [])


class Writes(Base):
    def test_write_bytes_text_json(self):
        fsafe.write_bytes(self.p("a.bin"), b"\x00\x01", root=self.root)
        fsafe.write_text(self.p("b.txt"), "한국어", root=self.root)
        fsafe.write_json(self.p("c.json"), {"z": 1, "a": [1, 2], "k": "é"}, root=self.root)
        with open(self.p("a.bin"), "rb") as f:
            self.assertEqual(f.read(), b"\x00\x01")
        with open(self.p("b.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "한국어")
        with open(self.p("c.json"), encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.endswith("}\n"))
        self.assertLess(text.index('"z"'), text.index('"a"'), "key order kept (not sorted)")
        self.assertIn("é", text)
        self.assertEqual(json.loads(text), {"z": 1, "a": [1, 2], "k": "é"})
        self.no_temp_left(self.root)

    def test_replace_existing_regular_file(self):
        fsafe.write_text(self.p("f"), "one", root=self.root)
        fsafe.write_text(self.p("f"), "two", root=self.root)
        with open(self.p("f")) as f:
            self.assertEqual(f.read(), "two")

    def test_mode(self):
        fsafe.write_text(self.p("f"), "x", root=self.root, mode=0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(self.p("f")).st_mode) & 0o077, 0)

    def test_nan_refused(self):
        with self.assertRaises(ValueError):
            fsafe.write_json(self.p("n.json"), {"x": float("nan")}, root=self.root)
        self.assertFalse(os.path.exists(self.p("n.json")))

    def test_type_errors(self):
        with self.assertRaises(TypeError):
            fsafe.write_bytes(self.p("f"), "str", root=self.root)
        with self.assertRaises(TypeError):
            fsafe.write_text(self.p("f"), b"bytes", root=self.root)

    def test_missing_parent_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            fsafe.write_text(self.p("no", "f"), "x", root=self.root)


class Refusals(Base):
    """S12: a link or a non-regular file anywhere on the path → UnsafePath (stop)."""

    def test_parent_symlink(self):
        os.symlink(self.outside, self.p("link"))
        with self.assertRaises(UnsafePath) as cm:
            fsafe.write_text(self.p("link", "f"), "x", root=self.root)
        self.assertEqual(cm.exception.path, self.p("link"))
        self.outside_untouched()

    def test_deep_parent_symlink(self):
        os.makedirs(self.p("a", "b"))
        os.symlink(self.outside, self.p("a", "b", "c"))
        for fn in (lambda: fsafe.write_text(self.p("a", "b", "c", "f"), "x", root=self.root),
                   lambda: fsafe.append_line(self.p("a", "b", "c", "log"), "x", root=self.root),
                   lambda: fsafe.make_dirs(self.p("a", "b", "c", "d"), root=self.root),
                   lambda: fsafe.read_bytes(self.p("a", "b", "c", "f"), root=self.root)):
            with self.assertRaises(UnsafePath):
                fn()
        self.outside_untouched()

    def test_leaf_symlink_to_file(self):
        target = os.path.join(self.outside, "victim")
        with open(target, "w") as f:
            f.write("keep")
        os.symlink(target, self.p("f"))
        with self.assertRaises(UnsafePath):
            fsafe.write_text(self.p("f"), "x", root=self.root)
        with self.assertRaises(UnsafePath):
            fsafe.append_line(self.p("f"), "x", root=self.root)
        with self.assertRaises(UnsafePath):
            fsafe.read_bytes(self.p("f"), root=self.root)
        with open(target) as f:
            self.assertEqual(f.read(), "keep")
        self.assertTrue(os.path.islink(self.p("f")), "the link is not replaced either")

    def test_dangling_leaf_symlink(self):
        os.symlink(os.path.join(self.outside, "new"), self.p("f"))
        with self.assertRaises(UnsafePath):
            fsafe.write_text(self.p("f"), "x", root=self.root)
        with self.assertRaises(UnsafePath):
            fsafe.append_line(self.p("f"), "x", root=self.root)
        self.outside_untouched()

    def test_leaf_directory_and_fifo(self):
        os.mkdir(self.p("d"))
        with self.assertRaises(UnsafePath):
            fsafe.write_text(self.p("d"), "x", root=self.root)
        os.mkfifo(self.p("fifo"))
        for fn in (lambda: fsafe.write_text(self.p("fifo"), "x", root=self.root),
                   lambda: fsafe.append_line(self.p("fifo"), "x", root=self.root),
                   lambda: fsafe.read_bytes(self.p("fifo"), root=self.root)):
            with self.assertRaises(UnsafePath):
                fn()

    def test_parent_is_a_file(self):
        with open(self.p("file"), "w") as f:
            f.write("x")
        with self.assertRaises(UnsafePath):
            fsafe.write_text(self.p("file", "f"), "x", root=self.root)
        with self.assertRaises(UnsafePath):
            fsafe.make_dirs(self.p("file", "d"), root=self.root)

    def test_outside_root_and_relative(self):
        with self.assertRaises(UnsafePath):
            fsafe.write_text(os.path.join(self.outside, "f"), "x", root=self.root)
        with self.assertRaises(UnsafePath):
            fsafe.write_text("rel/f", "x", root=self.root)
        with self.assertRaises(UnsafePath):
            fsafe.write_text(self.p("a", "..", "f"), "x", root=self.root)
        with self.assertRaises(UnsafePath):
            fsafe.write_text(self.root, "x", root=self.root)
        self.outside_untouched()

    def test_no_root_checks_from_slash(self):
        # Without a root every component counts; a link high up (here: our own) is refused.
        os.symlink(self.root, os.path.join(self.outside, "via"))
        with self.assertRaises(UnsafePath):
            fsafe.write_text(os.path.join(self.outside, "via", "f"), "x")
        fsafe.write_text(self.p("ok"), "x")              # realpath'd temp dir: no link on the way
        self.assertTrue(os.path.isfile(self.p("ok")))

    def test_root_itself_is_trusted(self):
        # The engine home may be reached through a link the user made; below it nothing may be one.
        os.symlink(self.root, os.path.join(self.outside, "home"))
        via = os.path.join(self.outside, "home")
        fsafe.write_text(os.path.join(via, "f"), "x", root=via)
        self.assertTrue(os.path.isfile(self.p("f")))


class Append(Base):
    def test_append_creates_and_appends(self):
        path = self.p("log.jsonl")
        fsafe.append_line(path, '{"a":1}', root=self.root)
        fsafe.append_line(path, '{"b":2}', root=self.root)
        with open(path) as f:
            self.assertEqual(f.read(), '{"a":1}\n{"b":2}\n')

    def test_newline_refused(self):
        for bad in ("a\nb", "a\r"):
            with self.assertRaises(ValueError):
                fsafe.append_line(self.p("log"), bad, root=self.root)
        self.assertFalse(os.path.exists(self.p("log")))


class Dirs(Base):
    def test_make_dirs(self):
        d = fsafe.make_dirs(self.p("a", "b", "c"), root=self.root)
        self.assertTrue(os.path.isdir(d))
        self.assertEqual(stat.S_IMODE(os.lstat(d).st_mode) & 0o077, 0, "0700 by default")
        fsafe.make_dirs(self.p("a", "b", "c"), root=self.root)    # idempotent

    def test_make_dirs_ending_at_a_link(self):
        os.symlink(self.outside, self.p("end"))
        with self.assertRaises(UnsafePath):
            fsafe.make_dirs(self.p("end"), root=self.root)


class Reads(Base):
    def test_read_bytes(self):
        fsafe.write_bytes(self.p("f"), b"abc", root=self.root)
        self.assertEqual(fsafe.read_bytes(self.p("f"), root=self.root), b"abc")
        with self.assertRaises(FileNotFoundError):
            fsafe.read_bytes(self.p("none"), root=self.root)
        with self.assertRaises(UnsafePath):
            fsafe.read_bytes(self.p("f"), root=self.root, max_bytes=2)


class Copy(Base):
    def test_copy_regular_file_keeps_mode(self):
        src = os.path.join(self.outside, "src")
        with open(src, "w") as f:
            f.write("data")
        os.chmod(src, 0o755)
        fsafe.copy_file(src, self.p("dst"), root=self.root, src_root=self.outside)
        with open(self.p("dst")) as f:
            self.assertEqual(f.read(), "data")
        self.assertEqual(stat.S_IMODE(os.lstat(self.p("dst")).st_mode) & 0o100, 0o100)

    def test_copy_refuses_link_source(self):
        real = os.path.join(self.outside, "real")
        with open(real, "w") as f:
            f.write("secret")
        os.symlink(real, os.path.join(self.outside, "link"))
        with self.assertRaises(UnsafePath):
            fsafe.copy_file(os.path.join(self.outside, "link"), self.p("dst"), root=self.root)
        self.assertFalse(os.path.lexists(self.p("dst")))

    def test_copy_refuses_link_in_source_parents(self):
        os.makedirs(os.path.join(self.outside, "real"))
        with open(os.path.join(self.outside, "real", "f"), "w") as f:
            f.write("x")
        os.symlink(os.path.join(self.outside, "real"), os.path.join(self.outside, "ln"))
        with self.assertRaises(UnsafePath):
            fsafe.copy_file(os.path.join(self.outside, "ln", "f"), self.p("dst"),
                            root=self.root, src_root=self.outside)

    def test_copy_refuses_link_destination_and_dir_source(self):
        src = os.path.join(self.outside, "src")
        with open(src, "w") as f:
            f.write("x")
        os.symlink(os.path.join(self.outside, "victim"), self.p("dst"))
        with self.assertRaises(UnsafePath):
            fsafe.copy_file(src, self.p("dst"), root=self.root)
        self.assertFalse(os.path.exists(os.path.join(self.outside, "victim")))
        with self.assertRaises(UnsafePath):
            fsafe.copy_file(self.outside, self.p("d2"), root=self.root)


if __name__ == "__main__":
    unittest.main()
