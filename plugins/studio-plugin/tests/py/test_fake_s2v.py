"""The fake s2v CLI (m1-plan §4.3, D-M1-8): s2v's contract as Studio reads it — stdout JSON only, people's lines on
stderr, exit codes, file names, the keys of its JSON (plus one Studio must ignore), determinism. Node only, no servers.
The comparison with real s2v (the inspect table, key sets) is M1j's (§12.3)."""

import json
import os
import shutil
import subprocess
import unittest

import helpers
from helpers import StudioTestCase
from stdo.state import collect

FAKE_ROOT = os.path.join(helpers.HERE, "drivers", "fake_s2v_cli")
MAIN = os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js")
SENTENCE_KEYS = {"id", "text", "cast", "recorded", "lockKey", "pickKey", "acting", "pick", "error", "lock"}
LOCK_KEYS = {"attempt", "wavSha256", "checks", "asr", "cer", "heard"}
SCRIPT = """---
title: 공항 단어
lang: ko
cast:
  narrator: { voice: "qwen:Sohee", style: "차분하게" }
outputs:
  youtube: { aspect: "16:9" }
  shorts: { aspect: "9:16" }
---

# 시작 {#intro}

narrator: 안녕하세요. 오늘은 공항 단어를 배워요.

:::quote
空港
:::

# 끝 {#end}

narrator: 고마워요!
"""


class FakeCase(StudioTestCase):
    def setUp(self):
        if not shutil.which("node"):
            if helpers.full_mode():
                raise AssertionError("--full needs node for the fake s2v CLI")
            raise unittest.SkipTest("needs node (the fake s2v CLI)")
        super().setUp()
        self.repo = helpers.make_repo(self.tmp)
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        os.makedirs(self.vdir)
        self.script = self.write_script(SCRIPT)
        self.out = os.path.join(self.repo, "studio", "out", "v1", "ko")
        self.scen = os.path.join(self.tmp, "scenario.json")
        self.scenario({})

    def write_script(self, text, vdir=None):
        p = os.path.join(vdir or self.vdir, "script.ko.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def scenario(self, data):
        with open(self.scen, "w") as f:
            json.dump(data, f)

    def s2v(self, *args, env=None):
        e = dict(os.environ, STUDIO_TEST_FAKE_S2V_SCENARIO=self.scen)
        e.update(env or {})
        return subprocess.run(["node", MAIN] + list(args), capture_output=True, text=True, env=e, cwd=self.repo)

    def json_of(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def calls(self):
        with open(os.path.join(self.tmp, "calls.log")) as f:
            return [json.loads(l) for l in f]


class Basics(FakeCase):
    def test_version_and_unknown_keys(self):
        v = self.json_of(self.s2v("--version", "--json"))
        self.assertTrue({"version", "code", "id", "commit", "dirty", "stale_build", "stale_packages"} <= set(v))
        self.assertEqual(v["id"], "%s+%s" % (v["version"], v["code"]))
        self.assertIn("fake_unknown", v)
        self.scenario({"version": {"stale_build": True, "commit": None, "dirty": None}})
        v = self.json_of(self.s2v("--version", "--json"))
        self.assertEqual((v["stale_build"], v["commit"]), (True, None))
        self.assertEqual(self.s2v("--version", "--bogus").returncode, 2)

    def test_usage_errors_print_no_json(self):
        for args in (["render", self.script, "--bogus"], ["render", self.script, "--output", "tiktok", "--frozen-audio",
                                                           "--out-dir", self.out],
                     ["lint", self.script, "--json"], ["nothing"], ["inspect", self.script]):
            r = self.s2v(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertEqual(r.stdout, "", args)
            self.assertIn("usage", r.stderr)

    def test_calls_log(self):
        self.s2v("lint", self.script, env={"S2V_HEAVY_LOCK_TOKEN": "t", "S2V_NO_OPEN": "1"})
        c = self.calls()[-1]
        self.assertEqual((c["argv"], c["heavy_token"], c["no_open"]), (["lint", self.script], True, "1"))

    def test_services_status(self):
        st = self.json_of(self.s2v("services", "status", "--json"))
        self.assertEqual((st["version"], st["state_dir"], st["busy"]["tts"]), (1, os.environ["S2V_STATE_DIR"], None))
        self.scenario({"services": {"busy_tts": "lock"}})
        self.assertEqual(self.json_of(self.s2v("services", "status", "--json"))["busy"]["tts"], {"reason": "lock"})

    def test_doctor_lint_check(self):
        self.assertEqual(self.s2v("doctor").returncode, 0)
        self.scenario({"doctor": {"fail": True}})
        self.assertEqual(self.s2v("doctor").returncode, 1)
        self.scenario({})
        r = self.s2v("lint", self.script)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        bad = self.write_script(SCRIPT.replace("narrator: 고마워요!", "guest: 고마워요!\n\n![x](missing.png)"))
        r = self.s2v("lint", bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("error [cast]", r.stderr)
        self.assertIn("error [asset-missing]", r.stderr)
        self.write_script(SCRIPT)
        self.scenario({"check": {"overflow": True}})
        r = self.s2v("check", self.script)
        self.assertEqual(r.returncode, 1)
        self.assertIn("error [subtitle-overflow]", r.stderr)


class Inspect(FakeCase):
    def inspect(self, path=None):
        return self.json_of(self.s2v("inspect", path or self.script, "--json"))

    def test_shape_and_studio_reads_it(self):
        d = self.inspect()
        self.assertTrue({"s2v_version", "stale_build", "hash_version", "script", "lang", "hashes", "reasons", "engine",
                         "outputs", "scenes", "screen_text", "voices", "characters", "faces", "files",
                         "fake_unknown"} <= set(d))
        self.assertIsNone(d["hashes"]["audio"])  # nothing synthesized: null with its reason
        self.assertIn("not synthesized", d["reasons"]["audio"][0])
        self.assertEqual(set(d["hashes"]["presentation_by_output"]), {"youtube", "shorts"})
        self.assertEqual(set(d["hashes"]["engine"]), {"tts", "templates", "defaults_voice", "composer", "renderer",
                                                      "ffmpeg", "defaults_presentation"})
        self.assertEqual(self.inspect(), d)  # deterministic
        # Studio's own reader takes it (the unknown key is ignored)
        self.assertEqual(collect.run_inspect(FAKE_ROOT, self.script)["hashes"], d["hashes"])
        self.assertEqual(self.s2v("inspect", self.script, "--json", "--hash-version", "2").returncode, 2)

    def test_hashes_follow_the_table(self):
        base = self.inspect()["hashes"]

        def changed(text):
            self.write_script(text)
            h = self.inspect()["hashes"]
            self.write_script(SCRIPT)
            out = set()
            for k in ("content", "voice"):
                if h[k] != base[k]:
                    out.add(k)
            for o, v in h["presentation_by_output"].items():
                if v != base["presentation_by_output"][o]:
                    out.add("presentation")
            return out
        self.assertEqual(changed(SCRIPT.replace("오늘은 공항", "오늘도 공항")), {"content", "presentation"})
        self.assertEqual(changed(SCRIPT.replace("차분하게", "밝게")), {"voice", "presentation"})
        self.assertEqual(changed(SCRIPT.replace("---\n\n#", "pronounce:\n  空港: 쿠우코오\n---\n\n#", 1)), {"voice"})
        self.assertEqual(changed(SCRIPT.replace('youtube: { aspect: "16:9" }',
                                                'youtube: { aspect: "16:9", maxDuration: 300 }')), set())
        self.assertEqual(changed(SCRIPT.replace("---\n\n#", "unknownKey: 1\n---\n\n#", 1)), set())
        self.assertEqual(changed(SCRIPT.replace("---\n\n#", "theme: dark\n---\n\n#", 1)), {"presentation"})

    def test_videos_differ_and_same_text_matches(self):
        other = os.path.join(self.repo, "studio", "videos", "v2")
        p2 = self.write_script(SCRIPT.replace("안녕하세요", "반가워요"), vdir=other)
        self.assertNotEqual(self.inspect()["hashes"]["content"], self.inspect(p2)["hashes"]["content"])
        p3 = self.write_script(SCRIPT, vdir=os.path.join(self.repo, "studio", "videos", "v3"))
        self.assertEqual(self.inspect()["hashes"]["content"], self.inspect(p3)["hashes"]["content"])

    def test_file_kinds(self):
        """Y6: the fake lists s2v's kinds of files (inspect.ts), within the kinds Studio's check inputs know."""
        from stdo.state import stagechecks
        for n, body in (("a.png", b"\x89PNG"), ("t.png", b"\x89PNG"), ("v.mp4", b"mp4"), ("logo.png", b"\x89PNG"),
                        ("m.mp3", b"mp3"), ("f.ttf", b"ttf")):
            with open(os.path.join(self.vdir, n), "wb") as f:
                f.write(body)
        text = SCRIPT.replace("---\n\n#", 'logo: { src: "logo.png" }\nbgm: { src: "m.mp3" }\n'
                              'subtitleStyle: { font: "f.ttf" }\n---\n\n#', 1)
        text = text.replace(":::quote", '![a](a.png)\n\n::video{src="v.mp4"}\n\n::thumbnail{src="t.png"}\n\n:::quote')
        self.write_script(text)
        kinds = {f["path"]: f["kind"] for f in self.inspect()["files"]}
        self.assertEqual(kinds, {"a.png": "image", "t.png": "thumbnail", "v.mp4": "video", "logo.png": "logo",
                                 "m.mp3": "bgm", "f.ttf": "font"})
        self.assertTrue(set(kinds.values()) <= set(stagechecks.S2V_FILE_KINDS))

    def test_missing_image_presentation_null(self):
        self.write_script(SCRIPT.replace(":::quote", "![a](a.png)\n\n:::quote"))
        d = self.inspect()
        self.assertIsNone(d["hashes"]["presentation_by_output"]["youtube"])
        self.assertIn("missing file(s): a.png", d["reasons"]["presentation.youtube"][0])
        self.assertEqual(self.s2v("lint", self.script).returncode, 1)  # lint says it is an error
        with open(os.path.join(self.vdir, "a.png"), "wb") as f:
            f.write(b"\x89PNG")
        d = self.inspect()
        self.assertEqual([(f["path"], f["kind"]) for f in d["files"]], [("a.png", "image")])
        h1 = d["hashes"]["presentation_by_output"]["youtube"]
        self.assertIsNotNone(h1)
        with open(os.path.join(self.vdir, "a.png"), "wb") as f:
            f.write(b"\x89PNG2")
        self.assertNotEqual(self.inspect()["hashes"]["presentation_by_output"]["youtube"], h1)


class Audio(FakeCase):
    def sentences(self):
        r = self.s2v("sentences", self.script, "--json")
        return r.returncode, json.loads(r.stdout)

    def test_tts_sentences_and_base_voice(self):
        r = self.s2v("tts", self.script)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertIn("synthesized 3, reused 0", r.stderr)
        base = os.path.join(self.repo, "studio", "voices", "_qwen", "Sohee")
        self.assertEqual(sorted(os.path.splitext(n)[1] for n in os.listdir(base)), [".json", ".wav"])
        self.assertFalse(os.path.exists(os.path.join(self.repo, "voices")))
        code, rows = self.sentences()
        self.assertEqual(code, 0)
        for row in rows:
            self.assertEqual(set(row) - {"fake_unknown"}, SENTENCE_KEYS)
            self.assertEqual(set(row["lock"]), LOCK_KEYS)
            self.assertNotIn("model", row)
        self.assertEqual([r_["id"] for r_ in rows], ["intro:0:0", "intro:0:1", "end:0:0"])
        with open(os.path.join(self.vdir, "audio", "ko", "manifest.json")) as f:
            self.assertTrue(json.load(f)["entries"])
        self.assertIsNotNone(json.loads(self.s2v("inspect", self.script, "--json").stdout)["hashes"]["audio"])
        r = self.s2v("tts", self.script)
        self.assertIn("synthesized 0, reused 3", r.stderr)

    def test_without_voices_folder_s2v_makes_one_at_the_root(self):
        shutil.rmtree(os.path.join(self.repo, "studio", "voices"))
        self.assertEqual(self.s2v("tts", self.script).returncode, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.repo, "voices", "_qwen", "Sohee")))  # why begin makes one (S7)

    def test_scenarios(self):
        self.scenario({"sentences": {"intro:0:0": {"cer": [0.4, 0.02]}, "intro:0:1": {"asr": [False]},
                                     "end:0:0": {"heard": ["고마워요 3번!"]}}})
        self.s2v("tts", self.script)
        _, rows = self.sentences()
        by = {r["id"]: r["lock"] for r in rows}
        self.assertEqual(by["intro:0:0"]["cer"], 0.4)
        self.assertEqual((by["intro:0:1"]["asr"], by["intro:0:1"]["cer"], by["intro:0:1"]["heard"]), (False, None, ""))
        self.assertEqual(by["end:0:0"]["heard"], "고마워요 3번!")
        r = self.s2v("tts", self.script, "--retry", "intro:0:0")
        self.assertIn("synthesized 1, reused 2", r.stderr)
        _, rows = self.sentences()
        self.assertEqual(({r["id"]: r["lock"] for r in rows})["intro:0:0"]["attempt"], 2)
        self.assertEqual(({r["id"]: r["lock"] for r in rows})["intro:0:0"]["cer"], 0.02)

    def test_busy_and_signal(self):
        self.scenario({"tts": {"busy": "lock"}})
        r = self.s2v("tts", self.script)
        self.assertEqual((r.returncode, r.stdout), (73, ""))
        lines = r.stderr.strip().splitlines()
        i = [n for n, l in enumerate(lines) if l.startswith("busy (lock): ")]
        self.assertTrue(i and 0 < i[0] < len(lines) - 1, lines)  # between other lines
        self.assertFalse(os.path.exists(os.path.join(self.vdir, "audio")))
        self.scenario({"tts": {"signal": 15, "signal_after": 1}})
        self.assertEqual(self.s2v("tts", self.script).returncode, 143)
        self.scenario({})
        self.assertIn("synthesized 2, reused 1", self.s2v("tts", self.script).stderr)

    def test_sentences_json_even_with_lint_errors(self):
        self.write_script(SCRIPT.replace("narrator: 고마워요!", "guest: 고마워요!"))
        r = self.s2v("sentences", self.script, "--json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(json.loads(r.stdout)), 3)
        self.assertIn("error [cast]", r.stderr)

    def test_recorded_line(self):
        self.write_script(SCRIPT.replace("narrator: 고마워요!", 'narrator: :audio{src="rec/a.wav"}고마워요!'))
        self.s2v("tts", self.script)
        _, rows = self.sentences()
        self.assertEqual([(r["id"], r["recorded"], r["lock"]) for r in rows if r["recorded"]],
                         [("end:0:0", True, None)])


class Pictures(FakeCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.s2v("tts", self.script).returncode, 0)

    def render(self, *extra, output="youtube"):
        return self.s2v("render", self.script, "--output", output, "--frozen-audio", "--out-dir", self.out, *extra)

    def test_render_names_and_lines(self):
        r = self.render()
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertTrue(any(l.startswith("ok: ") for l in r.stderr.splitlines()))
        self.assertTrue(any(l.startswith("→ ") and l.endswith(".mp4 (0.1s)") for l in r.stderr.splitlines()))
        self.assertEqual(sorted(os.listdir(self.out)), sorted("youtube.ko.%s" % e for e in (
            "mp4", "srt", "vtt", "description.md", "chapters.txt", "thumbnail.png")))
        self.assertEqual(self.render("--watermark", "proxy").returncode, 0)
        self.assertIn("youtube.ko.proxy.mp4", os.listdir(self.out))
        self.assertEqual(self.render("--watermark", "other").returncode, 2)
        # a portrait output makes no thumbnail and no chapters: last run's are removed
        for n in ("shorts.ko.thumbnail.png", "shorts.ko.chapters.txt"):
            with open(os.path.join(self.out, n), "w") as f:
                f.write("old")
        self.assertEqual(self.render(output="shorts").returncode, 0)
        self.assertNotIn("shorts.ko.thumbnail.png", os.listdir(self.out))
        self.assertNotIn("shorts.ko.chapters.txt", os.listdir(self.out))

    def test_render_failures(self):
        self.scenario({"render": {"check_failed": True}})
        r = self.render()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any(l.startswith("CHECK FAILED: ") for l in r.stderr.splitlines()))
        self.assertIn("youtube.ko.mp4", os.listdir(self.out))  # written, then 1
        self.scenario({"render": {"exit_after_write": 1, "tmp_leftover": True}})
        r = self.render()
        self.assertEqual(r.returncode, 1)
        self.assertTrue([n for n in os.listdir(self.out) if ".tmp." in n])
        self.scenario({})
        self.assertEqual(self.s2v("render", self.script, "--output", "youtube", "--out-dir", self.out).returncode, 1)

    def test_frozen_needs_the_lock(self):
        shutil.rmtree(os.path.join(self.vdir, "audio"))
        r = self.render()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not in the audio lock", r.stderr)

    def snapshot(self):
        return self.s2v("snapshot", self.script, "--output", "youtube", "--frozen-audio", "--frames", "--out-dir",
                        self.out)

    def test_snapshot(self):
        r = self.snapshot()
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        idx = os.path.join(self.out, "youtube.ko.frames", "index.json")
        with open(idx) as f:
            data = json.load(f)
        self.assertTrue({"output", "lang", "draft", "fps", "s2v_version", "script_sha256", "scale", "scenes"}
                        <= set(data))
        self.assertEqual([s["id"] for s in data["scenes"]], ["intro", "end"])
        ino = os.stat(idx).st_ino
        with open(os.path.join(self.out, "youtube.ko.frames", "stale.png"), "w") as f:
            f.write("old")
        self.assertEqual(self.snapshot().returncode, 0)
        self.assertNotIn("stale.png", os.listdir(os.path.join(self.out, "youtube.ko.frames")))  # last run's go first
        self.assertNotEqual(os.stat(idx).st_ino, ino)
        self.scenario({"snapshot": {"interrupt": True}})
        self.assertEqual(self.snapshot().returncode, 130)
        self.assertIn("youtube.ko.frames.tmp", os.listdir(self.out))
        self.assertNotIn("youtube.ko.frames", os.listdir(self.out))
        self.assertNotIn("youtube.ko.snapshot.png", os.listdir(self.out))
