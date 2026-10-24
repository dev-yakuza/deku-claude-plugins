"""M1d (m1-plan §6): resolve_assets.py (references, resolution, formats by bytes, the floor, script_src), check_scope.py
(public source, overlay, analyst classes never below the floor), record-source recording the checked images, the
guard protecting assets.json and the source copy, and the M1c re-review NIT P6."""

import contextlib
import io
import json
import os
import struct
import subprocess
import sys

import helpers
from helpers import StudioTestCase
from stdo.source import assets, cli as scli_src, imgformat, refs
from stdo.state import cli, store
from stdo.state.collect import Providers
from stdo.state.hashes import source_hash_repo_md
from test_guard_judge import JudgeCase

sys.path.insert(0, os.path.join(helpers.HERE, "drivers"))
import make_harness  # noqa: E402

VER = {"id": "0.12.2+x", "version": "0.12.2", "commit": "c" * 40, "dirty": False, "stale_build": False}


def png(w=4, h=3):
    return imgformat.PNG_SIG + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00" + \
        b"\x00\x00\x00\x00"


def jpeg(w=5, h=7, sof=0xC0):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = b"\xff" + bytes([sof]) + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + frame + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00" + b"\xff\xd9"


def jpeg_dht_only():
    return b"\xff\xd8" + b"\xff\xc4" + struct.pack(">H", 5) + b"\x00\x00\x00" + b"\xff\xda" + struct.pack(">H", 2) + \
        b"\xff\xd9"


WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8
AVIF = b"\x00\x00\x00\x1cftypavif" + b"\x00" * 16

ARTICLE = """---
title: 공항에서 쓰는 단어
heroImage: /blog-images/airport/a.png
---

# 공항(くうこう)에서 쓰는 단어

공항(<ruby>空港<rp>(</rp><rt>くうこう</rt><rp>)</rp></ruby>)에 가면 먼저 체크인 카운터를 찾습니다.

![탑승구](/blog-images/airport/a.png)

![사진](../../../public/blog-images/airport/b.jpg "photo")

![webp](/blog-images/airport/a.webp)

<img src="/blog-images/airport/a.avif" alt="avif">

<picture><source srcset="/blog-images/airport/a.webp 1x" type="image/webp"><img src="/blog-images/airport/a.png" alt="pic"></picture>

![ext](/blog-images/airport/c.png)

![sof](/blog-images/airport/d.jpg)

![url](https://example.com/a.png)

![data](data:image/png;base64,AAAA)

![missing](/blog-images/airport/none.png)

![escape](/blog-images/../../README.md)

![link](/blog-images/airport/link.png)

![case](/blog-images/airport/A.PNG)

![pct](/blog-images/airport/space%20name.png?v=2#frag)

![credit](/blog-images/airport/b.jpg)
© 2020 Someone Else

![other](/other/x.png)

![ref][gate]

```markdown
![in code](/blog-images/airport/a.png)
```

[gate]: /blog-images/airport/a.png "Gate"
"""
EXPECT = [  # (kind, status, reason, floor)
    ("frontmatter", "ok", None, "public"),
    ("markdown", "ok", None, "public"),
    ("markdown", "ok", None, "public"),
    ("markdown", "unusable", "format", "public"),
    ("html", "unusable", "format", "public"),
    ("picture", "ok", None, "public"),
    ("markdown", "unusable", "ext-mismatch", "public"),
    ("markdown", "unusable", "format", "public"),
    ("markdown", "unusable", "url", "unknown"),
    ("markdown", "unusable", "data", "unknown"),
    ("markdown", "unusable", "not-found", "unknown"),
    ("markdown", "unusable", "outside-root", "unknown"),
    ("markdown", "unusable", "outside-root", "unknown"),
    ("markdown", "unusable", "case-mismatch", "unknown"),
    ("markdown", "ok", None, "public"),
    ("markdown", "ok", None, "third-party"),
    ("markdown", "ok", None, "unknown"),
    ("reference", "ok", None, "public"),
]


class SourceCase(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_harness.make(os.path.join(self.tmp, "site"), s2v="/abs/s2v")
        img = os.path.join(self.repo, "public", "blog-images", "airport")
        os.makedirs(img)
        files = {"a.png": png(), "b.jpg": jpeg(), "a.webp": WEBP, "a.avif": AVIF, "c.png": jpeg(),
                 "d.jpg": jpeg_dht_only(), "space name.png": png(8, 8)}
        for n, b in files.items():
            with open(os.path.join(img, n), "wb") as f:
                f.write(b)
        os.makedirs(os.path.join(self.repo, "public", "other"))
        with open(os.path.join(self.repo, "public", "other", "x.png"), "wb") as f:
            f.write(png())
        with open(os.path.join(self.tmp, "secret.png"), "wb") as f:
            f.write(png())
        os.symlink(os.path.join(self.tmp, "secret.png"), os.path.join(img, "link.png"))
        art = os.path.join(self.repo, "src", "content", "blog")
        os.makedirs(art)
        with open(os.path.join(art, "airport.md"), "w") as f:
            f.write(ARTICLE)
        self.config(visibility={"default": "unknown", "public": ["src/content/blog/**", "public/blog-images/**"]},
                    web_roots={"/": "public/"})
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "site")
        self.providers = Providers(version=lambda ctx: dict(VER))
        store.enable_writes()
        self.assertEqual(self.state("begin", "v1", "--source", "src/content/blog/airport.md", "--kind", "youtube"),
                         0, self.err)
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)

    def config(self, **kw):
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(p) as f:
            cfg = json.load(f)
        cfg.update(kw)
        with open(p, "w") as f:
            json.dump(cfg, f, indent=2)

    def cfg(self):
        with open(os.path.join(self.repo, ".claude", "studio", "config.json")) as f:
            return json.load(f)

    def state(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), providers=self.providers, cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def run_src(self, fn, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fn(list(argv), cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def resolve(self):
        self.assertEqual(self.run_src(scli_src.resolve_main, "v1"), 0, self.err)
        return assets.read(self.vdir)

    def classes(self, mapping):
        with open(os.path.join(self.vdir, "work", "source.md"), "w") as f:
            f.write("# Source\n\n<!-- studio:images -->\n```json\n%s\n```\n<!-- /studio:images -->\n"
                    % json.dumps(mapping))

    def scope(self):
        return self.run_src(scli_src.scope_main, "v1")


class Resolve(SourceCase):
    def test_every_reference(self):
        data = self.resolve()
        got = [(i["kind"], i["status"], i["reason"], i["floor"]) for i in data["images"]]
        if got[13][2] == "not-found":  # a case-sensitive disk does not find A.PNG at all
            got[13] = (got[13][0], got[13][1], "case-mismatch", got[13][3])
        self.assertEqual(got, EXPECT)
        first = data["images"][0]
        self.assertEqual((first["resolved"], first["format"], first["width"], first["height"]),
                         ("public/blog-images/airport/a.png", "png", 4, 3))
        self.assertEqual(data["images"][2]["resolved"], "public/blog-images/airport/b.jpg")
        self.assertEqual((data["images"][2]["width"], data["images"][2]["height"]), (5, 7))
        # the script lives in the video folder: script_src is relative to it
        self.assertEqual(first["script_src"], "../../../public/blog-images/airport/a.png")
        self.assertTrue(os.path.isfile(os.path.normpath(os.path.join(self.vdir, first["script_src"]))))
        pic = data["images"][5]
        self.assertEqual([c["reason"] for c in pic["candidates"]], ["format", None])
        self.assertEqual(pic["ref"], "/blog-images/airport/a.png")
        self.assertEqual(data["images"][14]["resolved"], "public/blog-images/airport/space name.png")
        self.assertEqual(data["images"][17]["title"], "Gate")
        self.assertNotIn("in code", [i["alt"] for i in data["images"]])
        self.assertEqual(data["source_copy_sha"],
                         __import__("hashlib").sha256(ARTICLE.encode()).hexdigest())

    def test_deterministic_and_protected_by_scripts_only(self):
        a = self.resolve()
        b = self.resolve()
        self.assertEqual(a, b)
        r = subprocess.run([sys.executable, "-B", "-c", "import sys; sys.path.insert(0, %r); "
                            "from stdo.source import assets; assets.write(%r, {})" % (helpers.SCRIPTS, self.vdir)],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)  # only an entry script writes it (writes flag)
        self.assertIn("entry scripts", r.stderr)

    def test_web_roots(self):
        os.makedirs(os.path.join(self.repo, "static", "assets"))
        with open(os.path.join(self.repo, "static", "assets", "s.png"), "wb") as f:
            f.write(png())
        top, src = self.repo, "src/content/blog/airport.md"
        wr = {"/": "public/", "/assets/": "static/assets/"}
        self.assertEqual(assets.resolve(top, src, "/assets/s.png", wr), ("ok", None, "static/assets/s.png"))
        self.assertEqual(assets.resolve(top, src, "/blog-images/airport/a.png", wr)[2],
                         "public/blog-images/airport/a.png")
        self.assertEqual(assets.resolve(top, src, "/x.png", {})[1], "no-web-root")
        self.assertEqual(assets.resolve(top, src, "/assets/../../../README.md", wr)[1], "outside-root")
        self.config(web_roots={"/": "/abs"})
        self.assertEqual(self.run_src(scli_src.resolve_main, "v1"), 2)

    def test_no_copy_yet(self):
        os.remove(os.path.join(self.vdir, "work", "source", "airport.md"))
        self.assertEqual(self.run_src(scli_src.resolve_main, "v1"), 1)
        self.assertIn("record-source", self.err)

    def test_formats_by_bytes(self):
        self.assertEqual(imgformat.detect(png(9, 2)), ("png", 9, 2))
        self.assertEqual(imgformat.detect(jpeg(3, 4)), ("jpeg", 3, 4))
        for sof in (0xC1, 0xC2, 0xCF):
            self.assertEqual(imgformat.detect(jpeg(sof=sof))[0], "jpeg")
        for sof in (0xC4, 0xC8, 0xCC):
            self.assertEqual(imgformat.detect(jpeg(sof=sof))[0], "unknown", hex(sof))
        self.assertEqual(imgformat.detect(jpeg_dht_only())[0], "unknown")
        # a frame header only after the scan starts is no frame (the scan's data could hold any bytes)
        late = b"\xff\xd8" + b"\xff\xda" + struct.pack(">H", 2) + jpeg()[2 + 18:]
        self.assertEqual(imgformat.detect(late)[0], "unknown")
        self.assertEqual(imgformat.detect(WEBP)[0], "webp")
        self.assertEqual(imgformat.detect(AVIF)[0], "avif")
        self.assertEqual(imgformat.detect(b"GIF89a....")[0], "gif")
        self.assertEqual(imgformat.detect(b'<?xml version="1.0"?><svg/>')[0], "svg")
        self.assertEqual(imgformat.detect(b"\xff\xd8\xff")[0], "unknown")  # cut short

    def test_floor_marks_and_settings(self):
        for mark in ("©", "(C)", "(c)", "Copyright", "出典", "출처"):
            r = refs.Ref("markdown", "a.png", 1, alt="x %s y" % mark)
            self.assertEqual(assets.floor(r, "public/blog-images/a.png", self.cfg(), list(assets.CREDIT_MARKS))[0],
                             "third-party", mark)
        r = refs.Ref("markdown", "a.png", 1, title="from the agency")
        self.assertEqual(assets.floor(r, "public/blog-images/a.png", self.cfg(), ["agency"])[0], "third-party")
        self.config(source={"image_keys": [], "credit_marks": ["Someone"]})
        data = self.resolve()
        self.assertEqual(data["images"][0]["kind"], "markdown")  # no frontmatter key any more
        with self.assertRaises(assets.AssetError):
            assets.settings({"source": {"image_keys": "image"}})

    def test_refs_details(self):
        rs = refs.extract("![a](<x y.png>)\n![b][Lbl]\n\n[lbl]: <z.png> 'T'\n", ())
        self.assertEqual([(r.kind, r.src, r.title) for r in rs], [("markdown", "x y.png", ""),
                                                                    ("reference", "z.png", "T")])
        self.assertEqual(refs.srcset("a.webp 1x, b.png 2x"), ["a.webp", "b.png"])
        self.assertEqual(assets._clean("a%C3%A9.png?x=1#y"), "aé.png")
        self.assertEqual(assets._clean("é.png"), "é.png")  # NFD → NFC


class Scope(SourceCase):
    def test_scope_never_below_the_floor(self):
        self.resolve()
        self.classes({"img-01": {"class": "photo", "reason": "mine"},
                      "img-16": {"class": "diagram", "reason": "claimed own"},  # © caption: stays third-party
                      "img-17": {"class": "photo"},  # outside the public glob: stays unknown
                      "img-03": {"class": "public"}})  # not a class: unknown
        self.assertEqual(self.scope(), 0, self.err)
        out = {i["id"]: i for i in assets.read(self.vdir)["images"]}
        self.assertEqual(out["img-01"]["scope"], "public")
        self.assertEqual(out["img-16"]["scope"], "third-party")
        self.assertEqual(out["img-17"]["scope"], "unknown")
        self.assertEqual((out["img-03"]["scope"], out["img-03"]["analyst_class"]), ("unknown", None))
        self.assertEqual(out["img-15"]["scope"], "unknown")  # not classified
        sc = assets.read(self.vdir)["scope_check"]
        self.assertEqual((sc["result"], sc["video_scope"]), ("pass", "public"))

    def test_no_classes(self):
        self.resolve()
        self.assertEqual(self.scope(), 0, self.err)
        self.assertIn("source.md is missing", self.out)
        self.assertEqual({i["scope"] for i in assets.read(self.vdir)["images"]}, {"unknown", "third-party"})

    def test_source_must_be_public_and_not_internal(self):
        self.resolve()
        self.config(visibility={"default": "unknown", "public": ["public/blog-images/**"]})
        self.assertEqual(self.scope(), 1)
        self.assertIn("not in visibility.public", self.err)
        self.config(visibility={"default": "unknown", "public": ["src/content/blog/**", "public/blog-images/**"]})
        make_harness.write_overlay(self.repo, {"internal": {"sources": [{"url": "x", "path": "src/content/**"}]}})
        self.assertEqual(self.scope(), 1)
        self.assertIn("internal source", self.err)
        make_harness.write_overlay(self.repo, {"internal": {}})
        self.assertEqual(self.scope(), 0, self.err)

    def test_overlay_missing(self):
        self.resolve()
        with open(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"), "a") as f:
            f.write(" ")
        self.assertEqual(self.scope(), 4)

    def test_stale_assets(self):
        self.assertEqual(self.scope(), 1)  # no assets.json yet
        self.resolve()
        with open(os.path.join(self.repo, "src", "content", "blog", "airport.md"), "a") as f:
            f.write("\nmore\n")
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        self.assertEqual(self.scope(), 1)
        self.assertIn("another copy", self.err)


class Record(SourceCase):
    def test_record_source_takes_checked_images_only(self):
        st = store.read_state(self.vdir)
        self.assertEqual((st["source"]["images"], st["source"]["assets_sha"]), ([], None))
        self.resolve()
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        self.assertIn("not checked for this copy", self.out)
        self.assertIsNone(store.read_state(self.vdir)["source"]["assets_sha"])
        self.assertEqual(self.scope(), 0, self.err)
        # only a passed check counts (the file is P-STATE; this stands for any other result)
        good = assets.read(self.vdir)
        bad = dict(good, scope_check=dict(good["scope_check"], result="fail"))
        store_write = assets.write
        store_write(self.vdir, bad)
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        self.assertIsNone(store.read_state(self.vdir)["source"]["assets_sha"])
        store_write(self.vdir, good)
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        st = store.read_state(self.vdir)
        self.assertEqual(st["source"]["assets_sha"],
                         __import__("hashlib").sha256(open(assets.path(self.vdir), "rb").read()).hexdigest())
        self.assertIn("public/blog-images/airport/a.png", st["source"]["images"])
        self.assertIn("public/other/x.png", st["source"]["images"])
        self.assertNotIn("public/blog-images/airport/a.webp", st["source"]["images"])
        frozen = st["source"]["frozen_hash"]
        self.assertEqual(frozen, source_hash_repo_md(self.repo, "src/content/blog/airport.md", st["source"]["images"]))
        # an image's bytes are part of the source hash: changing one changes the live hash (the router sends to source)
        with open(os.path.join(self.repo, "public", "blog-images", "airport", "a.png"), "ab") as f:
            f.write(b"\x00")
        self.assertNotEqual(source_hash_repo_md(self.repo, "src/content/blog/airport.md", st["source"]["images"]),
                            frozen)


FIGURE_ARTICLE = """---
title: figure
heroImage:
  src: /blog-images/airport/a.png
  alt: 출처 Agency
images:
  - /blog-images/airport/b.jpg
  - src: /blog-images/airport/a.png
    credit: someone
og: /blog-images/airport/c.png
---

<figure>
<img src="/blog-images/airport/a.png" alt="gate">
<p>a long story</p>



<figcaption>COURTESY OF the airport</figcaption>
</figure>

![a [nested] alt](/blog-images/airport/b.jpg)

<div style="background: url('/blog-images/airport/a.png')"></div>
<img data-src="/blog-images/airport/lazy.png">
<!-- ![hidden](/blog-images/airport/b.jpg) -->
"""


def floor_of(text, keys=(), marks=None, cfg=None):
    cfg = cfg or {"visibility": {"public": ["**"]}}
    return [assets.floor(r, "public/x.png", cfg, list(marks or assets.CREDIT_MARKS))[0]
            for r in refs.extract(text, keys)]


class FollowUps(SourceCase):
    """M1d review Q1–Q6."""

    def test_q1_marks_ignore_case(self):
        for mark in assets.CREDIT_MARKS:
            for m in (mark, mark.upper(), mark.title()):
                r = refs.Ref("markdown", "a.png", 1, alt="photo %s someone" % m)
                self.assertEqual(assets.floor(r, "public/blog-images/a.png", self.cfg(), list(assets.CREDIT_MARKS))[0],
                                 "third-party", m)
        for word in ("trivia", "viaduct", "obviate", "image"):  # via only as a word; image only with its colon
            r = refs.Ref("markdown", "a.png", 1, alt="the %s board" % word)
            self.assertEqual(assets.floor(r, "public/blog-images/a.png", self.cfg(), list(assets.CREDIT_MARKS))[0],
                             "public", word)
        for text in ("(C) 2020", "Ⓒ x", "ⓒ x", "All Rights Reserved.", "写真提供: x", "引用元", "Image: x",
                     "이미지: x", "photo via x", "via: x"):
            self.assertEqual(floor_of("![x](/a.png \"%s\")" % text), ["third-party"], text)
        r = refs.Ref("markdown", "a.png", 1, caption="by SOMEONE")
        self.assertEqual(assets.floor(r, "public/x.png", self.cfg(), ["Someone"])[0], "third-party")

    def test_q1_context_figure_and_window(self):
        # the whole <figure>, however far its caption is from the image
        self.assertEqual(floor_of("<figure>\n<img src=\"/a.png\">\n\n<p>x</p>\n\n\n\n<figcaption>Courtesy X"
                                  "</figcaption>\n</figure>\n"), ["third-party"])
        self.assertEqual(floor_of("![a](/a.png)\n\n출처: X\n"), ["third-party"])  # a caption paragraph below
        self.assertEqual(floor_of("Copyright X\n![a](/a.png)\n"), ["third-party"])  # the line right above
        self.assertEqual(floor_of("Copyright X\n\n![a](/a.png)\n"), ["public"])  # above, across a blank: not its own
        self.assertEqual(floor_of("![a](/a.png)\n\n\n\n© X\n"), ["public"])  # beyond the window
        self.assertEqual(floor_of("![a](/a.png)\n![b](/b.png)\n© X\n"), ["public", "third-party"])  # the nearer image
        self.assertEqual(floor_of("![a](/a.png)\n## © heading\n"), ["public"])  # a heading ends the window
        # end to end: the source copy's context lands in assets.json
        self.replace_article(FIGURE_ARTICLE)
        data = self.resolve()
        html = [i for i in data["images"] if i["kind"] == "html"][0]
        self.assertIn("COURTESY OF the airport", html["context"])
        self.assertEqual(html["floor"], "third-party")

    def replace_article(self, text):
        with open(os.path.join(self.repo, "src", "content", "blog", "airport.md"), "w") as f:
            f.write(text)
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)

    def test_q2_missed_references(self):
        rs = refs.extract("![a [b] c](/x.png \"t\")\n![d [e]][lbl]\n\n[lbl]: /y.png\n")
        self.assertEqual([(r.src, r.alt, r.title) for r in rs], [("/x.png", "a [b] c", "t"), ("/y.png", "d [e]", "")])
        fm = "---\nhero:\n  src: /h.png\n  alt: 출처 X\ngallery:\n  - /g1.png\n  - url: '/g2.png'\n    alt: two\n" \
             "flow: [/f1.png, \"/f2.png\"]\nother:\n  src: /o.png\n---\nbody\n"
        rs, unparsed = refs.extract_all(fm, ("hero", "gallery", "flow"))
        self.assertEqual([(r.src, r.line, r.alt) for r in rs],
                         [("/h.png", 3, "출처 X"), ("/g1.png", 6, ""), ("/g2.png", 7, "two"), ("/f1.png", 9, ""),
                          ("/f2.png", 9, "")])
        self.assertEqual(unparsed, [11])  # other.src is no image key: counted, not parsed
        self.assertEqual(floor_of(fm, ("hero",)), ["third-party"])
        css = "<div style=\"background:url(/c1.png)\"></div>\n<style>\n.a { background: url( \"/c2.png\" ) }\n" \
              ".b { background: url('/c3.png') }\n</style>\n"
        self.assertEqual([(r.kind, r.src, r.line) for r in refs.extract(css)],
                         [("css", "/c1.png", 1), ("css", "/c2.png", 3), ("css", "/c3.png", 4)])
        self.replace_article(FIGURE_ARTICLE)
        data = self.resolve()
        self.assertEqual([(i["kind"], i["ref"]) for i in data["images"]],
                         [("frontmatter", "/blog-images/airport/a.png"), ("frontmatter", "/blog-images/airport/b.jpg"),
                          ("frontmatter", "/blog-images/airport/a.png"), ("html", "/blog-images/airport/a.png"),
                          ("markdown", "/blog-images/airport/b.jpg"), ("css", "/blog-images/airport/a.png")])
        self.assertEqual(data["images"][0]["floor"], "third-party")  # its nested alt
        self.assertEqual(data["unparsed"], {"count": 2, "lines": [10, 25]})  # og: and the lazy <img>
        self.assertIn("2 line(s) look like an image but were not parsed (lines 10, 25)", self.out)

    def test_q5_case_exact_nfc(self):
        import unicodedata
        d = os.path.join(self.repo, "public", "blog-images", "airport")
        nfd = unicodedata.normalize("NFD", "카페.png")
        with open(os.path.join(d, nfd), "wb") as f:
            f.write(png())
        nfc = unicodedata.normalize("NFC", "카페.png")
        self.assertNotEqual(nfd, nfc)
        top = self.repo
        self.assertTrue(assets._case_exact(top, "public/blog-images/airport/" + nfc))
        self.assertTrue(assets._case_exact(top, "public/blog-images/airport/" + nfd))
        self.assertFalse(assets._case_exact(top, "public/blog-images/AIRPORT/" + nfc))  # letter case still exact
        self.assertFalse(assets._case_exact(top, "public/blog-images/airport/A.png"))
        st = assets.resolve(top, "src/content/blog/airport.md", "/blog-images/airport/" + nfc, {"/": "public/"})
        if os.path.lexists(os.path.join(d, nfc)):  # a normalization-insensitive disk finds it under NFC
            self.assertEqual(st[:2], ("ok", None))
        else:
            self.assertEqual(st[1], "not-found")

    def test_q6_comments_masked(self):
        text = "<!-- ![a](/a.png) -->\n<!--\n![b](/b.png)\n```\n-->\n![c](/c.png) <!-- x --> ![d](/d.png)\n" \
               "`<!--` ![e](/e.png)\n<!-- open ![f](/f.png)\n"
        rs, unparsed = refs.extract_all(text)
        self.assertEqual([r.src for r in rs], ["/c.png", "/d.png", "/e.png"])  # ``` inside a comment opens no fence
        self.assertEqual(unparsed, [])


class RecordFingerprint(SourceCase):
    def checked(self):
        self.assertEqual(self.scope(), 0, self.err)
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        return store.read_state(self.vdir)["source"]

    def test_q4_settings_and_overlay_since_the_check(self):
        self.resolve()
        self.assertIsNotNone(self.checked()["assets_sha"])
        sc = assets.read(self.vdir)["scope_check"]
        self.assertEqual(sc["web_roots"], {"/": "public/"})
        self.assertEqual(sc["visibility"]["public"], ["src/content/blog/**", "public/blog-images/**"])
        with open(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"), "rb") as f:
            self.assertEqual(sc["overlay_sha"], __import__("hashlib").sha256(f.read()).hexdigest())
        changes = [
            ("visibility", lambda: self.config(visibility={"default": "unknown", "public": [
                "src/content/blog/**", "public/blog-images/**", "public/other/**"]})),
            ("web_roots", lambda: self.config(web_roots={"/": "public/", "/assets/": "static/"})),
            ("overlay_sha", lambda: make_harness.write_overlay(self.repo, {"internal": {"terms": ["zzz-other"]}})),
        ]
        for name, change in changes:
            change()
            self.assertEqual(self.state("record-source", "v1"), 0, self.err)
            self.assertIn("%s changed since check_scope.py" % name, self.out)
            src = store.read_state(self.vdir)["source"]
            self.assertEqual((src["assets_sha"], src["images"]), (None, []), name)
            self.assertIsNotNone(self.checked()["assets_sha"], name)  # checked again: recorded again


class GuardM1d(JudgeCase):
    def test_assets_and_source_copy_are_protected(self):
        for rel in ("studio/videos/v/work/assets.json", "studio/videos/v/work/source/a.md"):
            d = self.decide("Write", {"file_path": os.path.join(self.repo, rel), "content": "x"})
            self.assertEqual(d.rule, "G-PROT", rel)
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(self.repo, "studio/videos/v/work/source.md"),
                                                "content": "x"}))
        self.assertPass("python3 .claude/studio/scripts/resolve_assets.py v")
        self.assertPass("python3 .claude/studio/scripts/check_scope.py v")


class P6(StudioTestCase):
    def test_s2v_path_prefix_keys_refused(self):
        from stdo.setup import cli as setup_cli
        repo = make_harness.make(os.path.join(self.tmp, "h"))
        for key in ("s2v.path.x", "s2v.pathway"):
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = setup_cli.main(["config", "set", key, '"/x"'], cwd=repo)
            self.assertEqual(code, 2, key)
            self.assertIn("exactly s2v.path", err.getvalue())
        with open(os.path.join(repo, ".claude", "studio", "config.json")) as f:
            self.assertEqual(json.load(f)["s2v"], {"min_version": "0.12.1"})

