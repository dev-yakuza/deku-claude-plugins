"""M1j carry-overs from the M1i review: base-voice deletions (Z1), the racy-git stat cache, NFC keys in the
pronounce merge, the video kind's allow-list limited to its target, and staging edge cases."""

import contextlib
import io
import os
import subprocess
import time

import helpers
from helpers import StudioTestCase
from stdo.commit import checks, gitx, kinds, video as video_kind
from test_m1i import CommitCase


class Z1(CommitCase):
    def test_deleted_shared_voice_is_refused(self):
        self.assertEqual(self.cc("--stage", "video", "v1"), 0, self.err + self.out)
        voices = [p for p in self.staged() if p.startswith("studio/voices/_qwen/")]
        self.assertTrue(voices)
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "v1 with its voices")
        os.remove(os.path.join(self.repo, voices[0]))
        with open(os.path.join(self.repo, "studio", "videos", "v1", "CREDITS.yaml"), "a") as f:
            f.write("")
        self.assertEqual(self.cc("--stage", "video", "v1"), 1)
        self.assertIn("base voices HEAD has are deleted in the work tree: %s" % voices[0], self.err)
        self.assertIn("git checkout --", self.err)
        self.assertNotIn(voices[0], self.staged())


class Staging(CommitCase):
    def test_pre_staged_file_is_refused(self):
        with open(os.path.join(self.repo, "README.md"), "a") as f:
            f.write("x\n")
        helpers.git(self.repo, "add", "README.md")
        self.assertEqual(self.cc("--stage", "video", "v1"), 1)
        self.assertIn("other changes are already staged (README.md)", self.err)

    def test_file_added_after_stage_is_a_tree_mismatch(self):
        self.assertEqual(self.cc("--stage", "video", "v1"), 0, self.err + self.out)
        with open(os.path.join(self.vdir, "CREDITS.yaml"), "a") as f:
            f.write(" ")
        helpers.git(self.repo, "add", "studio/videos/v1/CREDITS.yaml")
        self.assertEqual(self.cc("--staged"), 1)
        self.assertIn("is not the one Studio prepared", self.err)

    def test_allow_list_is_the_target_only(self):
        self.assertEqual(self.cc("--stage", "video", "v1"), 0, self.err + self.out)
        d = os.path.join(self.repo, "studio", "videos", "v2")
        os.makedirs(d)
        with open(os.path.join(d, "script.ko.md"), "w") as f:
            f.write("# other\n")
        helpers.git(self.repo, "add", "studio/videos/v2/script.ko.md")
        self.assertNotEqual(self.cc("--staged"), 0)
        self.assertIn("studio/videos/v2/script.ko.md is outside the allow-list of a video commit", self.err)


class Racy(StudioTestCase):
    def test_same_size_same_mtime_rewrite_is_seen(self):
        """The index's stat cache misses a same-size rewrite with the same mtime; the video kind compares content."""
        repo = helpers.make_repo(self.tmp)
        p = os.path.join(repo, "a.txt")
        with open(p, "w") as f:
            f.write("aaaa\n")
        old = time.time() - 3600
        os.utime(p, (old, old))  # an mtime well before the index is written: the entry is not "racily clean"
        helpers.git(repo, "add", "a.txt")
        helpers.git(repo, "commit", "-q", "-m", "a")
        helpers.git(repo, "config", "core.trustctime", "false")  # as on file systems whose ctime git cannot trust
        st = os.stat(p)
        with open(p, "w") as f:
            f.write("bbbb\n")
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        # the stat cache still says "unchanged" (git cannot tell without reading the file)
        listed = subprocess.run(["git", "-C", repo, "ls-files", "--modified"], capture_output=True, text=True).stdout
        git = gitx.Git(repo, dict(os.environ))
        ctx = checks.Ctx(git, dict(os.environ), kinds.registry(dict(os.environ)))
        self.assertEqual(video_kind.state_of(ctx, "a.txt"), "changed")
        self.assertEqual(video_kind.state_of(ctx, "none.txt"), "absent")
        os.remove(p)
        self.assertEqual(video_kind.state_of(ctx, "a.txt"), "deleted")
        self.assertNotIn("a.txt", listed)  # what made the old `ls-files --modified` collector miss it


class MergeNfc(StudioTestCase):
    def test_nfd_twin_is_a_conflict_not_an_addition(self):
        import unicodedata
        nfd = unicodedata.normalize("NFD", "카드")
        text, skipped = video_kind.merge('{\n  "%s": "a"\n}\n' % nfd, {"카드": "b"})
        self.assertEqual((text, skipped), (None, ["카드"]))
        self.assertEqual(video_kind.merge('{\n  "%s": "a"\n}\n' % nfd, {"카드": "a"}), (None, []))
        text, _s = video_kind.merge("{}", {nfd: "x"})
        self.assertIn('"카드": "x"', text)  # an added key is written in NFC


class FakeTable(StudioTestCase):
    """§12.3 (--full): real s2v `inspect --json` (S2V_TTS=mock, an isolated HOME) changes the hashes the checked-in
    table says, and the fake s2v changes the same ones; the JSON keys Studio reads exist on both sides."""

    def setUp(self):
        super().setUp()
        self.real = helpers.s2v_path(self)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "fake_table", os.path.join(helpers.PLUGIN, "tests", "tools", "fake_table.py"))
        self.ft = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ft)

    def test_the_table_is_real_s2v_and_the_fake_follows_it(self):
        import json
        real = self.ft.measure(self.real, work=os.path.join(self.tmp, "real"))
        fake = self.ft.measure(self.ft.FAKE, work=os.path.join(self.tmp, "fake"))
        self.assertEqual(fake, real)
        with open(self.ft.TABLE, encoding="utf-8") as f:
            checked_in = json.load(f)
        want = self.ft.table(real, checked_in)
        for k in ("frontmatter", "output_attrs_ignored", "body", "unknown_keys_refused"):
            self.assertEqual(checked_in.get(k), want.get(k), k)

    def test_keys_studio_reads(self):
        work = os.path.join(self.tmp, "keys")
        env = self.ft.isolated_env(os.path.join(work, "home"))
        os.makedirs(env["HOME"])
        repo = os.path.join(work, "repo")
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir)
        os.makedirs(os.path.join(repo, "studio", "voices"))
        subprocess.run(["git", "init", "-q", repo], check=True)
        script = os.path.join(vdir, "script.ko.md")
        with open(script, "w") as f:
            f.write(self.ft.BASE)
        with open(os.path.join(vdir, "a.png"), "wb") as f:
            f.write(self.ft.PNG)
        keys = {}
        for side, root in (("real", self.real), ("fake", self.ft.FAKE)):
            main = os.path.join(root, "packages", "cli", "dist", "main.js")
            ins = subprocess.run(["node", main, "inspect", script, "--json"], capture_output=True, text=True, env=env)
            sen = subprocess.run(["node", main, "sentences", script, "--json"], capture_output=True, text=True, env=env)
            import json
            d = json.loads(ins.stdout)
            s = json.loads(sen.stdout)
            keys[side] = (set(d), set(d["hashes"]), set(s[0]))
        studio_reads = ({"s2v_version", "stale_build", "hash_version", "lang", "hashes", "reasons", "outputs",
                         "files", "screen_text", "scenes"},
                        {"content", "voice", "audio", "presentation_by_output", "engine"},
                        {"id", "text", "cast", "recorded", "lockKey", "lock"})
        for side in ("real", "fake"):
            for want, have in zip(studio_reads, keys[side]):
                self.assertTrue(want <= have, "%s lacks %s" % (side, sorted(want - have)))
