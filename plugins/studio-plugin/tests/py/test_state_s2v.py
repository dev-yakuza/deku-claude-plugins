"""M0b-1 with the real script2video inspect (m0b1-plan §7.4; --full). Isolated: temporary state
folder, fake uv, mock TTS — inspect takes no lock and starts nothing."""

import contextlib
import io
import json
import os

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo.state import cli, store
from stdo.state.collect import CollectError, Providers, run_inspect

SCRIPT = ("---\ntitle: Test\nlang: en\noutputs:\n  youtube: { aspect: \"16:9\" }\n"
          "  shorts: { aspect: \"9:16\" }\n%s---\n\n# Intro {#intro}\n\n%s\n")


class RealInspect(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.s2v = helpers.s2v_path(self)
        os.environ.update(self.s2v_environ)
        self.script = os.path.join(self.tmp, "script.en.md")
        self.write()

    def write(self, text="Hello there.", extra=""):
        with open(self.script, "w") as f:
            f.write(SCRIPT % (extra, text))

    def inspect(self, **kw):
        return run_inspect(self.s2v, self.script, **kw)

    def test_s1_format(self):
        d = self.inspect()
        self.assertEqual(sorted(d["hashes"]["engine"]),
                         sorted(["tts", "templates", "composer", "renderer", "ffmpeg", "defaults_voice",
                                 "defaults_presentation"]))
        self.assertEqual(sorted(d["hashes"]["presentation_by_output"]), ["shorts", "youtube"])
        self.assertIsNone(d["hashes"]["audio"])  # nothing synthesized: no audio lock
        self.assertTrue(d["reasons"]["audio"])
        self.assertIsInstance(d["hashes"]["content"], str)
        self.assertIn(d["stale_build"], (False,))

    def test_s2_which_hashes_move(self):
        a = self.inspect()["hashes"]
        self.write(text="Hello there, friends.")
        b = self.inspect()["hashes"]
        self.assertNotEqual(a["content"], b["content"])
        self.assertNotEqual(a["voice"], b["voice"])  # the sentence text is synthesized: voice moves too
        self.write(extra="transition: fade\n")
        c = self.inspect()["hashes"]
        self.assertEqual((a["content"], a["voice"]), (c["content"], c["voice"]))
        self.assertNotEqual(a["presentation_by_output"]["youtube"], c["presentation_by_output"]["youtube"])

    def test_s3_removing_an_output_keeps_the_other(self):
        a = self.inspect()["hashes"]["presentation_by_output"]
        with open(self.script, "w") as f:
            f.write("---\ntitle: Test\nlang: en\noutputs:\n  youtube: { aspect: \"16:9\" }\n---\n\n"
                    "# Intro {#intro}\n\nHello there.\n")
        b = self.inspect()["hashes"]["presentation_by_output"]
        self.assertEqual(a["youtube"], b["youtube"])

    def test_s4_script_error_is_exit_1_with_the_line(self):
        self.write(text="Hello.\n\n::nonsense[x]")
        repo = helpers.make_repo(self.tmp, s2v=self.s2v)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir)
        store.enable_writes()
        st = F.state()
        st["source_lang"] = "en"
        st["langs"] = {"en": st["langs"]["ko"]}
        store.create(vdir, st)
        with open(self.script) as src, open(os.path.join(vdir, "script.en.md"), "w") as dst:
            dst.write(src.read())
        p = Providers(source=lambda ctx, s: ("src1", ""))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["next", "v1"], providers=p, cwd=repo)
        self.assertEqual(code, 1)
        self.assertIn("error unknown-directive", err.getvalue())

    def test_s5_unsupported_hash_version(self):
        with self.assertRaises(CollectError) as e:
            self.inspect(hash_version=2)
        self.assertIn("usage", str(e.exception))

    def test_s6_inspect_version_is_the_version_id(self):
        out = helpers.run_s2v(self, ["--version", "--json"])
        self.assertEqual(json.loads(out.stdout)["id"], self.inspect()["s2v_version"])


class RealNoScript(StudioTestCase):
    """MJ-1: before the script exists `next` judges only source → brief → script (no inspect);
    once it exists the real inspect is used."""

    def test_no_script_then_script(self):
        s2v = helpers.s2v_path(self)
        os.environ.update(self.s2v_environ)
        repo = helpers.make_repo(self.tmp, s2v=s2v)
        os.makedirs(os.path.join(repo, "docs"))
        with open(os.path.join(repo, "docs", "a.md"), "w") as f:
            f.write("# A\n\nHello there.\n")
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(os.path.join(vdir, "work", "source"))
        with open(os.path.join(vdir, "work", "source", "a.md"), "w") as f:
            f.write("# A\n\nHello there.\n")
        store.enable_writes()
        st = F.state()
        st["source_lang"] = "en"
        st["langs"] = {"en": st["langs"]["ko"]}
        st["s2v"]["id"] = json.loads(helpers.run_s2v(self, ["--version", "--json"]).stdout)["id"]
        store.create(vdir, st)

        def run(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(list(argv), cwd=repo)
            return code, out.getvalue()

        code, out = run("next", "v1", "--json")
        self.assertEqual((code, json.loads(out)["redo"]["stage"]), (0, "script"))
        self.assertEqual(run("next", "v1", "--enter", "cast")[0], 3)
        with open(os.path.join(vdir, "script.en.md"), "w") as f:
            f.write(SCRIPT % ("", "Hello there."))
        code, out = run("next", "v1", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["redo"]["stage"], "script")  # ① not approved yet
