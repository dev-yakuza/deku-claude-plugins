"""Images Herald makes or fetches (design/herald/08-images.md, 0.17.0): `HRD image kinds`, the
limner probe and runner (a fake `lmn`, never the real engine), config checks, SVG rules, plan,
render records, fetch (a fake HTTPS server: no network), confirm/reject, the OG card, stage
pass, exclusions, the guard, scan, holds and the translation block. A repo without an `images`
block behaves as 0.16.0 (test_screenshots and test_auto_capture run unchanged)."""

import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import time
import unittest
import zlib
from unittest import mock

from helpers import HERE, SCRIPTS, RepoCase, sh

from hrdlib import images, limner, shots, store
from hrdlib.config import Config

TID, SLUG = "t0001", "new-post"
IMG = "public/blog-images/%s" % SLUG
W = ".claude/herald/work/%s" % TID
SRC = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Lobby.jpg/1280px-Lobby.jpg"
PAGE = "https://commons.wikimedia.org/wiki/File:Lobby.jpg"
GLOBAL = ["93.184.216.34"]
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400">'
       '<rect width="800" height="400" fill="#ffffff"/>'
       '<text x="10" y="40" font-family="sans-serif" font-size="22">1. Apply <tspan>online</tspan></text>'
       '<text x="10" y="90" font-family="sans-serif" font-size="16">Fee   3,000 yen</text></svg>')
TEXTS = [{"text": "1. Apply online", "claims": []}, {"text": "Fee 3,000 yen", "claims": ["C1"]}]
FIGURE = {"diagram": "![{alt}]({ref})",
          "licensed": "![{alt}]({ref})\n*{label}: {credit}, [{license}]({license_url}) — [{source}]({page_url})*",
          "quotation": "![{alt}]({ref})\n*{label}: {credit} — [{source}]({page_url})*",
          "words": {"licensed": "Photo", "quotation": "Quotation", "source": "Source"}}
BODY = """---
title: Renewal guide
description: How to renew
slug: new-post
date: 2026-11-01
category: guide
---
The renewal has two steps.

{d1}

The lobby of the office looks like this.

{e1}

That is all.
"""
RESEARCH = """# Research

**C1.** The fee is 3,000 yen. (https://example.gov/fees)
**C2.** withdrawn: the fee was 2,000 yen.

## Image candidates

### IC1 — the lobby
- image: %s
- page: %s
- credit: Someone
- license: CC BY-SA 3.0

## Other
""" % (SRC, PAGE)


def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


def big_png(w=600, h=400, extra=(), seed=b"x", actl=False):
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    pre = chunk(b"acTL", b"\x00\x00\x00\x02\x00\x00\x00\x00") if actl else b""
    return (b"\x89PNG\r\n\x1a\n" + ihdr + pre + b"".join(chunk(t, d) for t, d in extra)
            + chunk(b"IDAT", zlib.compress(seed * 10)) + chunk(b"IEND", b""))


def seg(m, data):
    return bytes([0xFF, m]) + struct.pack(">H", len(data) + 2) + data


def big_jpeg(w=600, h=400):
    base = shots._PLACEHOLDER["jpg"]
    i = base.index(b"\xff\xc0")
    sof = bytearray(base[i:i + 13])
    sof[5:7] = struct.pack(">H", h)
    sof[7:9] = struct.pack(">H", w)
    body = base[:i] + bytes(sof) + base[i + 13:]
    rest = body[2:]
    rest = rest[rest.index(b"\xff\xdb"):]
    head = seg(0xE1, b"Exif\x00\x00GPS-HERE") + seg(0xE2, b"ICC_PROFILE\x00\x01\x01DisplayP3-profile") + \
        seg(0xE2, b"MPF\x00second") + seg(0xEB, b"JP\x00c2pa")
    return b"\xff\xd8" + head + rest + b"TRAILER"


class FakeResp:
    def __init__(self, status, headers, body, drip=0):
        self.status, self._h, self._body, self._drip = status, {k.lower(): v for k, v in headers.items()}, body, drip

    def getheader(self, name, default=None):
        return self._h.get(name.lower(), default)

    def read1(self, n):
        if self._drip:
            time.sleep(self._drip)
            n = 1
        c, self._body = self._body[:n], self._body[n:]
        return c


class FakeConn:
    """A fake HTTPS server keyed by (host, path); records (host, the checked addresses) per connection."""
    routes, log = {}, []

    def __init__(self, host, ips, timeout):
        self.host, self.ips = host, list(ips)
        FakeConn.log.append((host, self.ips))

    def request(self, method, path, headers=None):
        self.path, self.headers = path, headers

    def getresponse(self):
        r = FakeConn.routes.get((self.host, self.path))
        if r is None:
            return FakeResp(404, {}, b"")
        if isinstance(r, Exception):
            raise r
        return FakeResp(*r)

    def close(self):
        pass


def jpeg_route(data=None, **headers):
    h = {"Content-Type": "image/jpeg"}
    h.update(headers)
    return (200, h, data if data is not None else big_jpeg())


class ImageCase(RepoCase):
    def setUp(self):
        super().setUp()
        limner.reset_cache()
        images._BASE_EXTERNAL.clear()
        self.lmndir = os.path.join(self.tmp, "lmn")
        os.makedirs(self.lmndir)
        self.lmn = os.path.join(self.lmndir, "lmn")
        shutil.copy(os.path.join(HERE, "fake_lmn.py"), self.lmn)
        os.chmod(self.lmn, os.stat(self.lmn).st_mode | stat.S_IEXEC)
        self.env_keys = [k for k in os.environ if k.startswith("FAKE_LMN_")]
        for k in self.env_keys:
            os.environ.pop(k)
        os.environ["FAKE_LMN_DIR"] = self.lmndir
        FakeConn.routes, FakeConn.log = {}, []
        self.config(lambda c: c.update({
            "roles": {"conditional": ["illustrator"]},
            "limner": {"command": [self.lmn], "state_dir": ".limner"},
            "images": {"diagrams": {"width": 800, "background": "#ffffff"}, "external": True, "figure": FIGURE}}))
        with open(os.path.join(self.root, ".gitignore"), "a") as f:
            f.write(".limner/\n.claude/herald/inbox/\n")
        store.save_topics(self.root, {"version": 1, "topics": [
            {"id": TID, "title": "Renewal", "category": "guide", "state": "queued", "history": [], "reverted_by": []}]})
        self.commit("topics")
        sh(self.root, "git", "push", "-q", "origin", "main")
        sh(self.root, "git", "switch", "-q", "-c", store.branch_name(TID, SLUG))
        self.write(W + "/brief.md", "brief\n")
        self.write(W + "/research.md", RESEARCH)
        st = store.new_state(TID, SLUG)
        st["stage"] = "draft"
        st["stages"] = {"brief": {"outputs": {"brief.md": store.artifact_hash(self.root, self.cfg, st, "brief.md")}},
                        "research": {"outputs": {"research.md": store.artifact_hash(self.root, self.cfg, st, "research.md")}}}
        store.save_state(self.root, TID, st)
        self.write(W + "/claims-map.json", json.dumps({"sentences": []}))
        self.write(W + "/diagrams/d1.svg", SVG)
        self.body()
        self.manifest()

    def tearDown(self):
        os.environ.pop("FAKE_LMN_DIR", None)
        for k in [k for k in os.environ if k.startswith("FAKE_LMN_")]:
            os.environ.pop(k)
        os.environ.pop("HRD_UNATTENDED", None)
        super().tearDown()

    # helpers
    def config(self, fn):
        p = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(p))
        fn(cfg)
        with open(p, "w") as f:
            json.dump(cfg, f)
        self.cfg = Config.load(self.root)
        limner.reset_cache()

    def rules(self, data):
        self.write("docs/editorial/gate-rules.json", json.dumps(data))

    def d1(self, **kw):
        d = {"id": "d1", "kind": "diagram", "file": "%s/d1-steps.png" % IMG, "ref": "/blog-images/%s/d1-steps.png" % SLUG,
             "alt": "The two renewal steps", "purpose": "the steps paragraph", "texts": TEXTS}
        d.update(kw)
        return d

    def e1(self, **kw):
        e = {"id": "e1", "kind": "external", "use": "licensed", "file": "%s/e1-lobby.jpg" % IMG,
             "ref": "/blog-images/%s/e1-lobby.jpg" % SLUG, "alt": "The office lobby", "purpose": "the lobby paragraph",
             "source_url": SRC, "page_url": PAGE, "credit": "Someone", "license": "CC BY-SA 3.0"}
        e.update(kw)
        return e

    def manifest(self, items=None):
        self.write(W + "/images.json", json.dumps({"images": items if items is not None else [self.d1(), self.e1()]}))

    def body(self, d1=None, e1=None):
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(
            d1=d1 if d1 is not None else "![The two renewal steps](/blog-images/%s/d1-steps.png)" % SLUG,
            e1=e1 if e1 is not None else "![The office lobby](/blog-images/%s/e1-lobby.jpg)" % SLUG))

    def state(self):
        return store.load_state(self.root, TID)

    def calls(self):
        p = os.path.join(self.lmndir, "calls.jsonl")
        return [json.loads(x) for x in open(p)] if os.path.exists(p) else []

    def plan(self, check=False):
        return images.plan(self.root, self.cfg, TID, check_only=check)

    def render(self, ids=None):
        return images.render(self.root, self.cfg, TID, ids)

    def fetch(self, ids=None, resolve=GLOBAL):
        kw = {"side_effect": OSError("nope")} if resolve is None else {"return_value": resolve}
        with mock.patch.object(images, "CONNECTION", FakeConn), mock.patch.object(images, "_resolve", **kw):
            return images.fetch(self.root, self.cfg, TID, ids)

    def route(self, url, resp):
        from urllib.parse import urlsplit
        p = urlsplit(url)
        FakeConn.routes[(p.hostname, p.path + ("?" + p.query if p.query else ""))] = resp

    def put_snippet(self, iid="e1"):
        sn = images.snippet(self.root, self.cfg, TID, iid)["snippet"]
        self.body(e1=sn)
        return sn

    def fetched(self):
        """d1 rendered, e1 fetched, the snippet in the body, plan recorded."""
        self.route(SRC, jpeg_route())
        self.assertEqual(self.render()["rendered"][0]["problems"], [])
        out = self.fetch()
        self.assertEqual([x["id"] for x in out["fetched"]], ["e1"], out)
        self.put_snippet()
        res = self.plan()
        self.assertEqual(res["errors"], [])
        return res

    def ready(self):
        self.fetched()
        images.confirm(self.root, self.cfg, TID, "e1")
        self.assertEqual(self.plan()["errors"], [])

    def removed(self):
        out = []
        for dp, _, fns in os.walk(os.path.join(self.root, ".claude/herald/memory/images/removed")):
            out += fns
        return out


class KindsTests(ImageCase):
    def test_no_images_block_is_016(self):
        self.config(lambda c: c.pop("images"))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual([k[x]["why"] for x in ("diagram", "external", "og")], ["no-config"] * 3)
        self.assertTrue(k["screenshot"]["ok"])
        self.assertEqual(k["scene"], {"ok": False, "why": "0.18"})
        self.assertEqual(self.calls(), [])  # no limner call at all
        self.assertEqual(images.config_errors(self.root, self.cfg),
                         {"limner_errors": [], "og_errors": [], "figure_errors": []})

    def test_each_kind_alone(self):
        k = images.kinds(self.root, self.cfg, TID)
        self.assertTrue(k["diagram"]["ok"])
        self.assertTrue(k["external"]["ok"])
        self.assertEqual(k["external"]["max"], 3)
        self.assertFalse(k["external"]["quotation"])  # no og block: fallback_first_image is assumed
        self.assertEqual(k["external"]["exts"], ["png", "jpg", "jpeg"])  # the fixture ignores *.webp
        self.assertEqual(k["og"]["why"], "no-config")
        self.config(lambda c: c["images"].pop("diagrams"))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual(k["diagram"]["why"], "no-config")
        self.assertTrue(k["external"]["ok"])

    def test_illustrator_language_translations(self):
        self.config(lambda c: c.update(roles={"conditional": []}))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["diagram"]["why"], k["external"]["why"]), ("no-illustrator", "no-illustrator"))
        self.config(lambda c: c.update(roles={"conditional": ["illustrator"]}, language="de"))
        self.assertEqual(images.kinds(self.root, self.cfg, TID)["diagram"]["why"], "lang:de")
        for v, want in (("ko-KR", "ko"), ("ja_JP", "ja"), ("EN", "en")):
            self.config(lambda c: c.update(language=v))
            self.assertEqual(images.lang_tag(self.cfg), want)
        self.config(lambda c: c.update(language="en", translations={"source": "en", "targets": [
            {"lang": "ko", "body_pattern": "{content}/ko/{slug}.md", "url_pattern": "/ko/{slug}/"}]},
            roles={"conditional": ["illustrator", "translator"]}))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual(k["external"]["why"], "translations")
        self.assertTrue(k["diagram"]["ok"])

    def test_limner_codes(self):
        os.remove(self.lmn)
        self.assertEqual(images.kinds(self.root, self.cfg, TID)["diagram"]["why"], "limner:missing")
        shutil.copy(os.path.join(HERE, "fake_lmn.py"), self.lmn)
        os.chmod(self.lmn, 0o755)
        for env, want in (({"FAKE_LMN_FONTS": "missing"}, "limner:fonts"), ({"FAKE_LMN_CONTRACT": "2"}, "limner:contract-2"),
                          ({"FAKE_LMN_VERSION": "0.0.9"}, "limner:version-0.0.9")):
            limner.reset_cache()
            with mock.patch.dict(os.environ, env):
                self.assertEqual(images.kinds(self.root, self.cfg, TID)["diagram"]["why"], want)
        self.config(lambda c: c["limner"].update(command=["bash", "-lc", "lmn"]))
        self.assertEqual(images.kinds(self.root, self.cfg, TID)["diagram"]["why"], "config")

    def test_categories_quotation_and_exts(self):
        self.rules({"images": {"external": {"max": 0, "per_category": {"guide": 2}, "quotation_categories": ["guide"]}}})
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["external"]["max"], k["external"]["quotation"]), (2, False))
        self.config(lambda c: c["images"].update(og={"path": "{images}/{slug}/og.png", "fallback_first_image": False}))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertTrue(k["external"]["quotation"])
        self.assertEqual(k["external"]["quotation_max"], 2)
        self.rules({"images": {"external": {"max": 0, "per_category": {"other": 2}}}})
        self.assertEqual(images.kinds(self.root, self.cfg, TID)["external"]["why"], "category")


class LimnerTests(ImageCase):
    def test_probe_calls_version_and_rasterize_only_and_leaves_nothing(self):
        for _ in range(2):
            limner.reset_cache()
            self.assertTrue(limner.probe(self.root, self.cfg)["ok"])
        cmds = [c[0] for c in self.calls()]
        self.assertEqual(cmds, ["--version", "rasterize"] * 2)
        self.assertFalse(os.path.exists(os.path.join(self.lmndir, "doctor-called")))
        sd = os.path.join(self.root, ".limner")
        left = [os.path.join(dp, f) for dp, _, fns in os.walk(sd) for f in fns]
        self.assertEqual(left, [])
        # a cut-off probe's leftovers go with the next probe
        os.makedirs(os.path.join(sd, "herald-probe"))
        open(os.path.join(sd, "herald-probe", "old.png"), "w").write("x")
        limner.reset_cache()
        limner.probe(self.root, self.cfg)
        self.assertFalse(os.path.exists(os.path.join(sd, "herald-probe")))

    def test_doctor_command_string_keeps_quoted_paths(self):
        """m12: a path with a space stays one argv element."""
        spaced = os.path.join(self.tmp, "Application Support")
        os.makedirs(spaced)
        shutil.copy(self.lmn, os.path.join(spaced, "lmn"))
        out = limner.doctor(self.root, self.cfg, command='"%s"' % os.path.join(spaced, "lmn"))
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["command"], [os.path.join(spaced, "lmn")])

    def test_doctor_is_display_only(self):
        out = limner.doctor(self.root, self.cfg)
        self.assertTrue(out["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.lmndir, "doctor-called")))
        self.assertEqual(out["fonts"], {"pretendard": True})

    def test_runner_exit_table(self):
        def go(env):
            with mock.patch.dict(os.environ, env):
                res = limner.run(self.root, self.cfg, ["compose"], [
                    ("--template", "og-title"), ("--data", os.path.join(self.root, W, "brief.md")),
                    ("--root", self.root), ("--state-dir", os.path.join(self.root, ".limner")),
                    ("--out", os.path.join(self.root, ".limner", "x", "o.png"))])
            return res, limner.classify(res)
        res, (probs, fail) = go({})
        self.assertEqual((res["exit"], probs, fail), (0, [], None))
        self.assertNotIn("SECRET", json.dumps(res))  # stderr never reaches a result
        _, (probs, fail) = go({"FAKE_LMN_EXIT": "4", "FAKE_LMN_PROBLEMS": '[{"code": "overflow"}]'})
        self.assertEqual((probs[0]["code"], fail), ("overflow", None))
        for code, want, klass in (("2", "input", "content"), ("70", "internal", "env"), ("73", "unexpected-73", "env"),
                                  ("5", "unexpected-5", "env"), ("10", "unexpected-10", "env"),
                                  ("11", "unexpected-11", "env"), ("12", "unexpected-12", "env"),
                                  ("1", "crashed", "env")):
            _, (probs, fail) = go({"FAKE_LMN_EXIT": code})
            self.assertEqual((fail["code"], fail["class"]), (want, klass), code)
        _, (_, fail) = go({"FAKE_LMN_FONTS": "missing"})
        self.assertEqual((fail["code"], fail["class"]), ("limner:fonts", "env"))
        for raw in ("not json\n", '{"a": 1}\n{"b": 2}\n', '{"contract": 2}\n'):
            res, (_, fail) = go({"FAKE_LMN_RAW": raw})
            self.assertEqual((res["fail"], fail["code"]), ("contract", "contract"), raw)
        with mock.patch.object(limner, "KILL_GRACE", 1):
            with mock.patch.dict(os.environ, {"FAKE_LMN_SLEEP": "30"}):
                t0 = time.monotonic()
                res = limner.run(self.root, self.cfg, ["compose"], [
                    ("--data", os.path.join(self.root, W, "brief.md")), ("--root", self.root),
                    ("--state-dir", os.path.join(self.root, ".limner")),
                    ("--out", os.path.join(self.root, ".limner", "x", "o.png"))], timeout=1)
            self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(limner.classify(res)[1]["code"], "timeout")
        with self.assertRaises(Exception):
            limner.run(self.root, self.cfg, ["compose"], [("--out", "-rf")])

    def test_limner_errors(self):
        def errs(**kw):
            self.config(lambda c: c["limner"].update(kw))
            return limner.limner_errors(self.cfg)
        self.assertEqual(errs(), [])
        self.assertIn("shell or an interpreter", errs(command=["bash", "-lc", "lmn"])[0])
        self.assertTrue(errs(command=["env", "lmn"]))
        self.assertTrue(errs(command=["lmn", "-e"]))
        self.assertTrue(errs(command=["lmn", "{out}"]))
        self.assertEqual(errs(command=["uv", "run", "--project", "/abs/limner", "lmn"]), [])
        self.assertIn(".claude", errs(command=[self.lmn], state_dir=".claude/limner")[0])
        self.assertIn("published", errs(state_dir="public/limner")[0])
        self.assertIn("gitignored", errs(state_dir="limner-state")[0])
        self.assertTrue(errs(state_dir="/abs"))
        self.assertTrue(errs(state_dir="../x"))
        # never part of Config.validate, never stops another command
        self.assertEqual(self.cfg.validate(), ([], []))
        out, _ = self.hrd("config-check")
        self.assertTrue(out["ok"])
        self.assertTrue(out["limner_errors"])
        self.hrd("image", "status", "--topic", TID)


class ConfigCheckTests(ImageCase):
    def test_figure_errors(self):
        self.assertEqual(images.figure_errors(self.cfg), [])
        bad = dict(FIGURE, licensed="![{alt}]({ref}) {credit} {license}")
        self.config(lambda c: c["images"].update(figure=bad))
        e = images.figure_errors(self.cfg)
        self.assertTrue(any("{license_url}" in x and "{page_url}" in x for x in e), e)
        self.assertEqual(images.kinds(self.root, self.cfg, TID)["external"]["why"], "config")
        self.config(lambda c: c["images"].update(figure=dict(FIGURE, quotation="![{alt}]({ref}) {label} {credit}")))
        self.assertTrue(any("{page_url}" in x for x in images.figure_errors(self.cfg)))
        self.config(lambda c: c["images"].update(figure=FIGURE, diagrams={"width": 100, "background": "white"}))
        self.assertEqual(len(images.figure_errors(self.cfg)), 2)

    def test_og_errors(self):
        self.write("scripts/og.mjs", "// og\n")
        self.commit("og script")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")

        def errs(cmd):
            self.config(lambda c: c["images"].update(og={"path": "public/blog-og/{slug}.png", "command": cmd}))
            return images.og_errors(self.root, self.cfg)
        ok = ["node", "scripts/og.mjs", "--title", "{title}", "--out", "{out}"]
        self.assertEqual(errs(ok), [])
        self.assertTrue(errs(["node", "scripts/untracked.mjs", "{out}"]))
        self.assertTrue(errs(["node", "-e", "x", "{out}"]))
        self.assertTrue(errs(["bash", "-lc", "x {out}"]))
        self.assertTrue(errs(["gen", "--title={title}"]))  # a placeholder only as a whole element
        self.assertTrue(errs(["gen", "{url}"]))
        self.write("scripts/og.mjs", "// changed\n")
        self.assertIn("differs", errs(ok)[0])
        self.config(lambda c: c["images"].update(og={"path": "{images}/og.png"}))
        self.assertTrue(images.og_errors(self.root, self.cfg))


class SvgTests(unittest.TestCase):
    def wrap(self, inner, attrs='viewBox="0 0 10 10"'):
        return ('<svg xmlns="http://www.w3.org/2000/svg" %s>%s</svg>' % (attrs, inner)).encode()

    def test_extract(self):
        self.assertEqual(images.svg_texts(SVG.encode()), ["1. Apply online", "Fee 3,000 yen"])
        self.assertEqual(images.svg_texts(self.wrap('<text> </text><g fill="url(#g)"><text>a\n b</text></g>')), ["a b"])

    def test_refusals(self):
        for bad in (b'<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>',
                    self.wrap("<script>x</script>"), self.wrap("<foreignObject/>"), self.wrap("<image/>"),
                    self.wrap("<use/>"), self.wrap("<a/>"), self.wrap("<style>x</style>"), self.wrap("<title>t</title>"),
                    self.wrap("<desc>d</desc>"), self.wrap("<metadata/>"), self.wrap('<rect onclick="x"/>'),
                    self.wrap('<rect href="#a"/>'), self.wrap('<rect fill="url(http://x/a)"/>'),
                    self.wrap('<text font-family="Arial">a</text>'), self.wrap("", attrs=""),
                    b"<html/>", b"\xff\xfe"):
            with self.assertRaises(Exception, msg=bad):
                images.svg_texts(bad)


class PlanTests(ImageCase):
    def test_clean_plan_records_pending(self):
        out = self.plan()
        self.assertEqual(out["errors"], [], out)
        self.assertEqual(out["pending"], {"render": ["d1"], "fetch": ["e1"], "confirm": []})
        rec = self.state()["images"]
        self.assertTrue(rec["awaiting"])
        self.assertEqual(rec["files"]["%s/e1-lobby.jpg" % IMG], {"kind": "external", "use": "licensed"})
        self.assertEqual(rec["items"]["d1"]["status"], "pending")

    def test_check_writes_nothing(self):
        self.manifest([self.d1(id="x1")])
        out = self.plan(check=True)
        self.assertTrue(out["errors"])
        self.assertNotIn("images", self.state())
        _, p = self.hrd("image", "plan", "--topic", TID, "--check", check=False)
        self.assertEqual(p.returncode, 1)

    def errors(self, items, body=None):
        self.manifest(items)
        if body:
            self.body(**body)
        return " | ".join(self.plan(check=True)["errors"])

    def test_each_error(self):
        cases = [
            ([self.d1(id="g1", kind="diagram")], "0.18"),
            ([self.d1(kind="scene")], "0.18"),
            ([self.d1(id="e9")], "a diagram id"),
            ([self.d1(file="%s/x.png" % IMG)], "file must be"),
            ([self.d1(file="%s/d1-steps.jpg" % IMG, ref="/blog-images/%s/d1-steps.jpg" % SLUG)], "published as .png"),
            ([self.d1(ref="/blog-images/other/d1-steps.png")], "does not resolve"),
            ([self.d1(alt="a <b>")], "alt must be set"),
            ([self.d1(texts=[{"text": "1. Apply online", "claims": []}])], "texts differ"),
            ([self.d1(texts=[TEXTS[0], {"text": "Fee 3,000 yen", "claims": ["C9"]}])], "does not have"),
            ([self.d1(texts=[TEXTS[0], {"text": "Fee 3,000 yen", "claims": ["C2"]}])], "withdrawn"),
            ([self.d1(), self.e1(source_url="https://elsewhere.example.com/a.jpg")], "Image candidates"),
            ([self.d1(), self.e1(license="CC BY-NC 4.0")], "not one this repo allows"),
            ([self.d1(), self.e1(use="quotation", license=None)], "quotations are not allowed"),
            ([self.d1(), self.e1(use="other")], "use must be"),
            ([self.d1(), self.e1(credit="")], "credit must be set"),
            ([self.d1(), self.e1(file="%s/e1-lobby.webp" % IMG, ref="/blog-images/%s/e1-lobby.webp" % SLUG)],
             "not an extension"),
            ([self.d1(), self.e1(source_url="http://upload.wikimedia.org/x.jpg")], "public https URL"),
        ]
        for items, want in cases:
            with self.subTest(want=want):
                self.assertIn(want, self.errors(items))
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(d1="", e1=""))
        self.assertIn("exactly once", self.errors([self.d1()]))

    def test_candidate_urls_match_whole_values(self):
        """m4: a prefix of a candidate URL, or the page URL used as the image, is not a candidate."""
        for bad in (dict(source_url="https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Lobby.jpg"),
                    dict(source_url=PAGE), dict(page_url=SRC)):
            self.manifest([self.d1(), self.e1(**bad)])
            self.assertIn("Image candidates", " ".join(self.plan(check=True)["errors"]), bad)

    def test_figure_errors_turn_off_their_own_kind(self):
        """m11: a missing quotation template turns only quotations off, a diagram setting only diagrams."""
        self.config(lambda c: c["images"].update(figure={k: v for k, v in FIGURE.items() if k != "quotation"}))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertTrue(k["diagram"]["ok"] and k["external"]["ok"])
        self.rules({"images": {"external": {"quotation_categories": ["guide"]}}})
        self.assertTrue(images.figure_errors(self.cfg))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertTrue(k["diagram"]["ok"] and k["external"]["ok"])
        self.assertFalse(k["external"]["quotation"])
        self.config(lambda c: c["images"].update(figure=FIGURE, diagrams={"width": 10}))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["diagram"]["why"], k["external"]["ok"]), ("config", True))

    def test_rejected_url_and_limits(self):
        st = self.state()
        st["image_rejects"] = [{"id": "e1", "source_url": SRC, "reason": "watermark", "drop": False, "at": "x"}]
        store.save_state(self.root, TID, st)
        self.assertIn("rejected by a human", " ".join(self.plan(check=True)["errors"]))
        st["image_rejects"] = []
        store.save_state(self.root, TID, st)
        self.rules({"images": {"external": {"max": 0, "per_category": {"guide": 1}}, "max_total": 1}})
        e = " ".join(self.plan(check=True)["errors"])
        self.assertIn("max_total", e)
        self.manifest([self.d1(), self.e1(), self.e1(id="e2", file="%s/e2-x.jpg" % IMG, ref="/blog-images/%s/e2-x.jpg" % SLUG)])
        self.body(e1="![a](/blog-images/new-post/e1-lobby.jpg) ![b](/blog-images/new-post/e2-x.jpg)")
        self.assertIn("this category allows 1", " ".join(self.plan(check=True)["errors"]))

    def test_quotation_rules(self):
        self.rules({"images": {"external": {"quotation_categories": ["guide"], "quotation_min_chars": 1000}}})
        self.config(lambda c: c["images"].update(og={"path": "{images}/{slug}/og.png", "fallback_first_image": False}))
        self.manifest([self.d1(), self.e1(use="quotation", license=None)])
        e = " ".join(self.plan(check=True)["errors"])
        self.assertIn("quotations need 1000", e)
        self.rules({"images": {"external": {"quotation_categories": ["guide"], "quotation_min_chars": 10}}})
        self.assertEqual(self.plan(check=True)["errors"], [])
        self.manifest([self.d1(), self.e1(use="quotation")])
        self.assertIn("a quotation has no license", " ".join(self.plan(check=True)["errors"]))

    def test_unmanaged_warning_and_sweep(self):
        self.write("%s/hand.png" % IMG, big_png(), binary=True)
        out = self.plan()
        self.assertTrue(any("unmanaged images" in w and "hand.png" in w for w in out["warnings"]))
        # a hand-made PNG at a diagram's place, and a file that left the manifest: moved, never deleted
        self.write("%s/d1-steps.png" % IMG, big_png(seed=b"hand"), binary=True)
        self.plan()
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "d1-steps.png")))
        self.assertIn("d1-steps.png", self.removed())
        self.render()
        self.manifest([self.e1()])
        self.body(d1="")
        self.plan()
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "d1-steps.png")))
        self.assertEqual(self.removed().count("d1-steps.png"), 2)


class RenderTests(ImageCase):
    def test_render_writes_the_png_and_a_content_addressed_record(self):
        out = self.render()
        self.assertEqual(out["rendered"], [{"id": "d1", "file": "%s/d1-steps.png" % IMG, "problems": []}])
        lines, dropped = images.read_renders(self.root, TID)
        self.assertEqual((len(lines), dropped), (1, 0))
        rec = lines[0]
        self.assertEqual(rec["texts"], ["1. Apply online", "Fee 3,000 yen"])
        h = shots.file_hashes(self.root, "%s/d1-steps.png" % IMG)
        self.assertEqual((rec["png_blob"], rec["png_sha256"]), h)
        self.assertNotIn("file", rec)
        self.assertNotIn(SLUG, json.dumps(rec))
        args = [c for c in self.calls() if c[0] == "rasterize" and "herald-probe" not in json.dumps(c)][0]
        self.assertEqual(args[args.index("--width") + 1], "800")
        self.assertTrue(os.path.isabs(args[args.index("--svg") + 1]))
        self.assertEqual(self.render()["skipped"], ["d1"])  # already the render of this SVG

    def test_problems_never_record(self):
        with mock.patch.dict(os.environ, {"FAKE_LMN_EXIT": "4", "FAKE_LMN_PROBLEMS": '[{"code": "missing_glyph"}]'}):
            out = self.render()
        self.assertEqual(out["rendered"][0]["problems"][0]["code"], "missing_glyph")
        self.assertEqual(images.read_renders(self.root, TID)[0], [])
        self.plan()
        self.assertEqual(self.state()["images"]["items"]["d1"]["status"], "pending")

    def test_failure_classes(self):
        with mock.patch.dict(os.environ, {"FAKE_LMN_EXIT": "2"}):
            self.assertEqual(self.render()["failed"][0]["class"], "content")
        with mock.patch.dict(os.environ, {"FAKE_LMN_EXIT": "70"}):
            self.assertEqual(self.render()["failed"][0]["class"], "env")
        with mock.patch.dict(os.environ, {"FAKE_LMN_BADSHA": "1"}):
            self.assertEqual(self.render()["failed"][0]["code"], "record-mismatch")
        self.write(W + "/diagrams/d1.svg", SVG.replace("<rect", "<script/><rect"))
        f = self.render()["failed"][0]
        self.assertEqual((f["code"], f["class"]), ("svg", "content"))
        self.write(W + "/diagrams/d1.svg", SVG)
        os.remove(self.lmn)
        limner.reset_cache()
        f = self.render()["failed"][0]
        self.assertEqual((f["code"], f["class"]), ("limner:missing", "env"))

    def test_budget_and_branch(self):
        with mock.patch.object(images, "RENDER_START_MIN", 1000):
            self.assertEqual(self.render()["remaining"], ["d1"])
        sh(self.root, "git", "stash", "-u", "-q")
        sh(self.root, "git", "switch", "-q", "main")
        sh(self.root, "git", "switch", "-q", "-c", "other")
        sh(self.root, "git", "stash", "pop", "-q")
        with self.assertRaises(Exception):
            self.render()

    def test_texts_svg_and_drawn(self):
        out = images.texts(self.root, self.cfg, TID, "d1", source="svg")
        self.assertEqual([t["text"] for t in out["texts"]], ["1. Apply online", "Fee 3,000 yen"])
        self.assertTrue(images.texts(self.root, self.cfg, TID)["errors"])  # no render yet
        self.render()
        self.write(W + "/diagrams/d1.svg", SVG.replace("3,000", "4,000"))
        drawn = images.texts(self.root, self.cfg, TID)
        self.assertEqual([t["text"] for t in drawn["texts"]], ["1. Apply online", "Fee 3,000 yen"])  # what is drawn


class StateTests(ImageCase):
    def test_diagram_state_from_records(self):
        self.render()
        self.plan()
        st = self.state()
        it = self.d1()
        lines = images.slug_renders(self.root, self.cfg, SLUG)[0]
        self.assertEqual(images.diagram_state(self.root, self.cfg, TID, st, it, lines)[0], "ready")
        # state.json says ready, but the record decides (R3-2)
        st["images"]["items"]["d1"]["status"] = "pending"
        store.save_state(self.root, TID, st)
        self.assertEqual(images.diagram_state(self.root, self.cfg, TID, st, it, lines)[0], "ready")
        self.config(lambda c: c["images"]["diagrams"].update(width=1600))
        self.assertEqual(images.diagram_state(self.root, self.cfg, TID, st, it, lines)[0], "pending")
        self.assertEqual(images.diagram_state(self.root, self.cfg, TID, st, it, lines, strict=False)[0], "ready")
        self.config(lambda c: c["images"]["diagrams"].update(width=800))
        self.write(W + "/diagrams/d1.svg", SVG.replace("Apply", "Send"))
        self.assertEqual(images.diagram_state(self.root, self.cfg, TID, st, it, lines)[0], "pending")
        self.write(W + "/diagrams/d1.svg", SVG)
        # a broken line is no line: stricter, never looser
        with open(os.path.join(self.root, images.renders_rel(TID)), "a") as f:
            f.write("{broken\n")
        lines, dropped = images.slug_renders(self.root, self.cfg, SLUG)
        self.assertEqual(dropped, 1)
        self.assertEqual(images.diagram_state(self.root, self.cfg, TID, st, it, lines)[0], "ready")

    def test_handmade_png_and_forged_state(self):
        self.write("%s/d1-steps.png" % IMG, big_png(seed=b"hand"), binary=True)
        st = self.state()
        st["images"] = {"items": {"d1": {"kind": "diagram", "status": "ready"}}}
        store.save_state(self.root, TID, st)
        lines = images.slug_renders(self.root, self.cfg, SLUG)[0]
        self.assertEqual(images.diagram_state(self.root, self.cfg, TID, st, self.d1(), lines)[0], "pending")

    def test_external_states(self):
        self.fetched()
        led = shots.Ledger(self.root)
        self.assertEqual(images.external_state(self.root, TID, self.e1(), led), "fetched")
        images.confirm(self.root, self.cfg, TID, "e1")
        led = shots.Ledger(self.root)
        self.assertEqual(images.external_state(self.root, TID, self.e1(), led), "ready")
        # wording only: the key stays (file, source), still ready
        self.assertEqual(images.external_state(self.root, TID, self.e1(credit="Someone Else", alt="x"), led), "ready")
        # a state field saying ready, with no ledger: pending
        os.remove(os.path.join(self.root, shots.FETCHES))
        self.assertEqual(images.external_state(self.root, TID, self.e1(), shots.Ledger(self.root)), "pending")


class FetchTests(ImageCase):
    def test_fetch_logs_then_writes_keeps_icc(self):
        self.plan()
        self.route(SRC, jpeg_route())
        out = self.fetch()
        self.assertEqual(out["fetched"][0]["orientation"], "landscape")
        data = open(os.path.join(self.root, IMG, "e1-lobby.jpg"), "rb").read()
        self.assertIn(b"ICC_PROFILE", data)
        for bad in (b"GPS-HERE", b"MPF", b"c2pa", b"TRAILER"):
            self.assertNotIn(bad, data)
        recs, bad = shots.ledger_read(os.path.join(self.root, shots.FETCHES))
        self.assertEqual(bad, [])
        self.assertEqual((recs[0]["source_url"], recs[0]["final_url"], recs[0]["license"], recs[0]["width"]),
                         (SRC, SRC, "CC BY-SA 3.0", 600))
        self.assertEqual(recs[0]["blob"], shots.blob(self.root, "%s/e1-lobby.jpg" % IMG))
        origs = os.listdir(os.path.join(self.root, ".claude/herald/memory/images/originals", TID))
        self.assertEqual(len(origs), 1)
        self.assertEqual(FakeConn.log, [("upload.wikimedia.org", GLOBAL)])
        st = self.state()["images"]["items"]["e1"]
        self.assertEqual((st["status"], st["orientation"]), ("fetched", "landscape"))
        self.assertEqual(self.state()["images"]["files"]["%s/e1-lobby.jpg" % IMG]["kind"], "external")

    def test_portrait(self):
        self.route(SRC, jpeg_route(big_jpeg(400, 600)))
        self.assertEqual(self.fetch()["fetched"][0]["orientation"], "portrait")

    def code(self, resp=None, resolve=GLOBAL, **kw):
        FakeConn.log = []
        if resp is not None:
            self.route(SRC, resp)
        out = self.fetch(resolve=resolve, **kw)
        return (out["failed"][0]["code"], out["failed"][0]["class"]) if out["failed"] else None

    def test_failure_codes(self):
        cases = [
            ((404, {}, b""), ("http-404", "content")),
            ((503, {}, b""), ("http-503", "env")),
            ((429, {}, b""), ("http-429", "env")),
            ((408, {}, b""), ("http-408", "env")),
            ((403, {"Retry-After": "60"}, b""), ("retry-later", "env")),
            (jpeg_route(**{"Content-Encoding": "gzip"}), ("encoded", "content")),
            ((200, {"Content-Type": "image/svg+xml"}, b"<svg/>"), ("not-image", "content")),
            ((200, {"Content-Type": "text/html"}, b"<html>"), ("not-image", "content")),
            (jpeg_route(**{"Content-Length": "99999999"}), ("too-large", "content")),
            (jpeg_route(big_jpeg(100, 100)), ("too-small", "content")),
            (jpeg_route(big_jpeg(9000, 100)), ("too-big", "content")),
            ((200, {"Content-Type": "image/png"}, big_jpeg()), ("bad-format", "content")),
            (ConnectionRefusedError(), ("net", "env")),
            (__import__("ssl").SSLCertVerificationError("bad cert"), ("tls", "env")),
        ]
        for resp, want in cases:
            with self.subTest(want=want):
                self.assertEqual(self.code(resp), want)
        self.assertEqual(self.code(jpeg_route(), resolve=["10.0.0.7"]), ("dns-private", "content"))
        self.assertEqual(self.code(jpeg_route(), resolve=["93.184.216.34", "127.0.0.1"]), ("dns-private", "content"))
        self.assertEqual(self.code(jpeg_route(), resolve=None), ("dns-fail", "env"))
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "e1-lobby.jpg")))  # nothing written

    def test_stream_limit_drip_animation_png_ext(self):
        self.rules({"images": {"external": {"max_bytes": 2000}}})
        self.assertEqual(self.code(jpeg_route(big_jpeg() + b"\x00" * 3000)), ("too-large", "content"))
        self.rules({})
        self.route(SRC, None)
        FakeConn.routes[("upload.wikimedia.org", "/wikipedia/commons/thumb/a/ab/Lobby.jpg/1280px-Lobby.jpg")] = \
            (200, {"Content-Type": "image/jpeg"}, big_jpeg())

        class Drip(FakeConn):
            def getresponse(self):
                return FakeResp(200, {"Content-Type": "image/jpeg"}, big_jpeg(), drip=0.05)
        with mock.patch.object(images, "FETCH_ITEM", 0.3), mock.patch.object(images, "CONNECTION", Drip), \
                mock.patch.object(images, "_resolve", return_value=GLOBAL):
            out = images.fetch(self.root, self.cfg, TID)
        self.assertEqual(out["failed"][0]["code"], "timeout")
        png_src = SRC.replace(".jpg", ".png")
        self.write(W + "/research.md", RESEARCH.replace(SRC, png_src))
        self.manifest([self.d1(), self.e1(source_url=png_src, file="%s/e1-lobby.png" % IMG,
                                          ref="/blog-images/%s/e1-lobby.png" % SLUG)])
        self.body(e1="![The office lobby](/blog-images/%s/e1-lobby.png)" % SLUG)
        self.route(png_src, (200, {"Content-Type": "image/png"}, big_png(actl=True)))
        self.assertEqual(self.fetch()["failed"][0]["code"], "animated")
        self.route(png_src, (200, {"Content-Type": "image/png"}, big_png(extra=[(b"iCCP", b"P3\x00\x00x"),
                                                                                  (b"tEXt", b"Author\x00me")])))
        self.assertTrue(self.fetch()["fetched"])
        data = open(os.path.join(self.root, IMG, "e1-lobby.png"), "rb").read()
        self.assertIn(b"iCCP", data)
        self.assertNotIn(b"tEXt", data)

    def test_redirects(self):
        other = "https://cdn.example.org/lobby.jpg"
        self.route(SRC, (302, {"Location": other}, b""))
        self.route(other, jpeg_route())
        out = self.fetch()
        self.assertTrue(out["fetched"], out)
        recs, _ = shots.ledger_read(os.path.join(self.root, shots.FETCHES))
        self.assertEqual(recs[-1]["final_url"], other)
        self.route(SRC, (302, {"Location": "http://cdn.example.org/lobby.jpg"}, b""))
        self.assertEqual(self.code(ids="e1"), ("redirect-refused", "content"))
        self.route(SRC, (302, {"Location": "https://127.0.0.1/x.jpg"}, b""))
        self.assertEqual(self.code(ids="e1"), ("redirect-refused", "content"))
        self.route(SRC, (302, {"Location": other}, b""))
        self.route(other, (301, {"Location": SRC}, b""))  # a loop: more than 3 hops
        self.assertEqual(self.code(ids="e1"), ("redirect-refused", "content"))
        # a host that resolves to a private address on the redirect hop
        self.route(SRC, (302, {"Location": other}, b""))
        self.route(other, jpeg_route())
        with mock.patch.object(images, "CONNECTION", FakeConn), \
                mock.patch.object(images, "_resolve", side_effect=[GLOBAL, ["10.1.1.1"]]):
            out = images.fetch(self.root, self.cfg, TID, "e1")
        self.assertEqual(out["failed"][0]["code"], "redirect-refused")

    def test_pinned_connection(self):
        conn = images.PinnedHTTPS("upload.wikimedia.org", "93.184.216.34", 5)
        with mock.patch("socket.create_connection", side_effect=OSError("stop")) as cc, \
                mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 443))]):
            with self.assertRaises(OSError):
                conn.connect()
        cc.assert_called_once_with(("93.184.216.34", 443), 5)
        # every checked address, in the resolver's order: an unreachable first one (IPv6 without a
        # route) falls through to the next (review m2)
        conn = images.PinnedHTTPS("upload.wikimedia.org", ["2406:da00::1", "93.184.216.34"], 5)
        with mock.patch("socket.create_connection", side_effect=[OSError("no route"), OSError("stop")]) as cc:
            with self.assertRaises(OSError):
                conn.connect()
        self.assertEqual([c.args[0] for c in cc.call_args_list], [("2406:da00::1", 443), ("93.184.216.34", 443)])
        with mock.patch("socket.getaddrinfo", return_value=[(30, 1, 6, "", ("2406:da00::1", 443, 0, 0)),
                                                             (2, 1, 6, "", ("93.184.216.34", 443)),
                                                             (2, 1, 6, "", ("3.1.1.1", 443))]):
            self.assertEqual(images._resolve("x.example.org"), ["2406:da00::1", "93.184.216.34", "3.1.1.1"])

    def test_header_drip_hits_the_item_deadline(self):
        class SlowHead(FakeConn):
            def getresponse(self):
                time.sleep(5)  # a server dripping its headers below the socket timeout
                return FakeResp(*jpeg_route())
        t0 = time.monotonic()
        with mock.patch.object(images, "FETCH_ITEM", 0.5), mock.patch.object(images, "CONNECTION", SlowHead), \
                mock.patch.object(images, "_resolve", return_value=GLOBAL):
            out = images.fetch(self.root, self.cfg, TID)
        self.assertLess(time.monotonic() - t0, 3)
        self.assertEqual(out["failed"][0]["code"], "timeout")

    def test_whole_manifest_errors_refuse_a_fetch(self):
        self.rules({"images": {"external": {"max": 0, "per_category": {"guide": 1}}}})
        self.manifest([self.d1(), self.e1(), self.e1(id="e2", file="%s/e2-x.jpg" % IMG, ref="/blog-images/%s/e2-x.jpg" % SLUG)])
        self.body(e1="![a](/blog-images/new-post/e1-lobby.jpg) ![b](/blog-images/new-post/e2-x.jpg)")
        self.route(SRC, jpeg_route())
        with self.assertRaises(Exception) as cm:
            self.fetch()
        self.assertIn("this category allows 1", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.root, shots.FETCHES)))  # nothing downloaded or logged

    def test_rejected_before_and_order(self):
        st = self.state()
        st["image_rejects"] = [{"id": "e1", "source_url": SRC, "reason": "x", "drop": False, "at": "x"}]
        store.save_state(self.root, TID, st)
        self.route(SRC, jpeg_route())
        self.assertEqual(self.code(), ("rejected-before", "content"))
        st["image_rejects"] = []
        store.save_state(self.root, TID, st)
        # a cut between the ledger line and the file: the line is there, the file is not → pending, refetch
        with mock.patch.object(images, "move_to_removed", side_effect=SystemExit("cut")):
            self.write("%s/e1-lobby.jpg" % IMG, b"junk", binary=True)
            with self.assertRaises(SystemExit):
                self.fetch()
        self.assertEqual(len(shots.ledger_read(os.path.join(self.root, shots.FETCHES))[0]), 1)
        self.assertEqual(open(os.path.join(self.root, IMG, "e1-lobby.jpg"), "rb").read(), b"junk")
        led = shots.Ledger(self.root)
        self.assertEqual(images.external_state(self.root, TID, self.e1(), led), "pending")  # the file is not the fetch


class ConfirmRejectTests(ImageCase):
    def test_confirm(self):
        self.fetched()
        with mock.patch.dict(os.environ, {"HRD_UNATTENDED": "1"}):
            with self.assertRaises(Exception):
                images.confirm(self.root, self.cfg, TID, "e1")
        with self.assertRaises(Exception):
            images.confirm(self.root, self.cfg, TID, "d1")
        out = images.confirm(self.root, self.cfg, TID, "e1")
        self.assertEqual(out["items"][0]["license"], "CC BY-SA 3.0")
        recs, _ = shots.ledger_read(os.path.join(self.root, shots.CONFIRMATIONS))
        self.assertEqual(recs[0]["id"], "e1")
        self.assertEqual(self.state()["images"]["items"]["e1"]["sha"], shots.blob(self.root, "%s/e1-lobby.jpg" % IMG))
        with self.assertRaises(Exception):  # no longer waiting
            images.confirm(self.root, self.cfg, TID, "e1")

    def test_reject_and_drop_and_refetch(self):
        self.fetched()
        self.plan()
        out = images.reject(self.root, self.cfg, TID, "e1", reason="a watermark")
        self.assertEqual(out["rejected"], ["e1"])
        st = self.state()
        self.assertEqual((st["stage"], st["last_loopback"], st["images"]["awaiting"]), ("draft", "human", False))
        self.assertEqual(st["image_rejects"][0]["source_url"], SRC)
        self.assertEqual(st.get("loopbacks", 0), 0)  # uncounted
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "e1-lobby.jpg")))
        self.assertEqual(self.fetch()["failed"][0]["code"], "rejected-before")
        images.reject(self.root, self.cfg, TID, "e1", reason="no", drop=True)
        self.assertTrue(self.state()["image_rejects"][-1]["drop"])
        # --refetch: no reject record, the same URL may come again
        st = self.state()
        st["image_rejects"] = []
        store.save_state(self.root, TID, st)
        self.fetch()
        n = len(self.state().get("image_rejects") or [])
        images.reject(self.root, self.cfg, TID, "e1", refetch=True, reason="refetch on this machine")
        self.assertEqual(len(self.state().get("image_rejects") or []), n)
        self.assertNotIn("fetched_at", self.state()["images"]["items"]["e1"])
        with mock.patch.dict(os.environ, {"HRD_UNATTENDED": "1"}):
            with self.assertRaises(Exception):
                images.reject(self.root, self.cfg, TID, "e1", reason="x")

    def test_fail_closed_without_the_fetch_line(self):
        self.ready()
        os.remove(os.path.join(self.root, shots.FETCHES))
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("no fetch record on this machine" in p for p in probs), probs)


class StagePassTests(ImageCase):
    def gate_ok(self):
        return mock.patch.object(store, "run_gate", return_value={"ok": True, "errors": [], "warnings": [],
                                                                   "prose": {"warnings": [], "stats": {}}})

    def test_draft_waits_then_passes(self):
        self.fetched()
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("waiting for a human's confirmation" in p for p in probs), probs)
        images.confirm(self.root, self.cfg, TID, "e1")
        self.plan()
        self.assertEqual(images.draft_problems(self.root, self.cfg, TID, self.state()), [])
        # the attribution removed (a writer's edit): refused even after plan
        self.body(e1="![The office lobby](/blog-images/%s/e1-lobby.jpg)" % SLUG)
        self.plan()
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("attribution" in p for p in probs), probs)
        self.put_snippet()
        self.plan()
        n = len(self.calls())
        with self.gate_ok():
            st = store.stage_pass(self.root, self.cfg, TID, "draft")
        self.assertFalse(st["images"]["awaiting"])
        self.assertEqual(len(self.calls()), n)  # stage pass never calls limner (P14)

    def test_rule_u_covers_an_outside_og_path(self):
        """m6: an unconfirmed fetched image put at a repo generator's OG path is caught too."""
        self.config(lambda c: c["images"].update(og={"path": "public/blog-og/{slug}.png", "command": ["gen", "{out}"]}))
        self.fetched()
        os.makedirs(os.path.join(self.root, "public/blog-og"))
        shutil.copy(os.path.join(self.root, IMG, "e1-lobby.jpg"), os.path.join(self.root, "public/blog-og/%s.png" % SLUG))
        self.assertIn("public/blog-og/%s.png" % SLUG, shots._changed_images(self.root, self.cfg, SLUG))
        probs = shots.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("blog-og" in p for p in probs), probs)
        self.commit("wip", ".")
        hits = [p for _, p, _ in shots._range_blobs(self.root, self.cfg, SLUG)]
        self.assertIn("public/blog-og/%s.png" % SLUG, hits)

    def test_rule_u_copy_under_another_name(self):
        self.fetched()
        shutil.copy(os.path.join(self.root, IMG, "e1-lobby.jpg"), os.path.join(self.root, IMG, "copy.jpg"))
        probs = shots.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("copy.jpg" in p for p in probs), probs)

    def test_verify_reads_the_drawn_text(self):
        self.ready()
        st = self.state()
        ver = {"images": {"texts": 1, "unsupported": []}}
        probs = images.verify_problems(self.root, self.cfg, TID, st, ver)
        self.assertTrue(any("draw 2 texts" in p for p in probs), probs)
        ver = {"images": {"texts": 2, "unsupported": [{"id": "d1", "text": "Fee 3,000 yen", "why": "x"}]}}
        self.assertTrue(any("unsupported" in p for p in images.verify_problems(self.root, self.cfg, TID, st, ver)))
        ver = {"images": {"texts": 2, "unsupported": []}}
        self.assertEqual(images.verify_problems(self.root, self.cfg, TID, st, ver), [])
        # another machine without limner: unchanged diagrams pass, --amend ignores settings
        os.remove(self.lmn)
        limner.reset_cache()
        self.assertEqual(images.verify_problems(self.root, self.cfg, TID, st, ver), [])
        self.config(lambda c: c["images"]["diagrams"].update(width=1600))
        self.assertTrue(images.verify_problems(self.root, self.cfg, TID, st, ver))
        self.assertEqual(images.verify_problems(self.root, self.cfg, TID, st, ver, amend=True), [])
        # base: the SVG edited, the PNG as published → a warning only
        self.write(W + "/diagrams/d1.svg", SVG.replace("Apply", "Send"))
        self.assertEqual(images.verify_problems(self.root, self.cfg, TID, st, ver, amend=True), [])
        self.assertTrue(images.svg_drift(self.root, self.cfg, TID, st))
        # the PNG itself replaced: the drawn text is unknown
        self.write("%s/d1-steps.png" % IMG, big_png(seed=b"edited"), binary=True)
        self.assertTrue(images.verify_problems(self.root, self.cfg, TID, st, ver, amend=True))
        self.assertEqual(self.calls() and [c for c in self.calls() if c[0] == "rasterize" and "--width" in c and
                                           "1600" in c], [])  # no render was asked for

    def move_slug(self, new="c-post"):
        """`status --move new-post -> c-post` as a human does it: body, images and image paths
        moved, published.json and the topic's state point at the new slug."""
        pub = store.load_published(self.root)
        pub.setdefault("articles", []).append({"slug": new, "path": "src/content/blog/%s.md" % new, "origin": "herald",
                                               "moved_from": [{"slug": SLUG}], "current_topic_id": TID})
        store.save_published(self.root, pub)
        shutil.move(os.path.join(self.root, IMG), os.path.join(self.root, "public/blog-images", new))
        old = os.path.join(self.root, "src/content/blog/%s.md" % SLUG)
        body = open(old).read().replace("/blog-images/%s/" % SLUG, "/blog-images/%s/" % new)
        os.remove(old)
        self.write("src/content/blog/%s.md" % new, body)
        st = self.state()
        st["slug"] = new
        store.save_state(self.root, TID, st)
        return new

    def test_refresh_and_moved_slug_find_the_record(self):
        self.ready()
        lines = images.slug_renders(self.root, self.cfg, SLUG)[0]
        # a refresh topic of the same slug reads the earlier topic's records
        store.save_state(self.root, "r-0002", store.new_state("r-0002", SLUG))
        self.assertEqual(len(images.slug_renders(self.root, self.cfg, SLUG)[0]), len(lines))
        # after `status --move` the diagram is found by the move chain and passes base re-verify
        new = self.move_slug()
        st = self.state()
        self.assertEqual(images.cur_path(self.root, self.cfg, new, self.d1()["file"]),
                         "public/blog-images/%s/d1-steps.png" % new)
        self.assertEqual(images.texts(self.root, self.cfg, TID)["texts"][1]["text"], "Fee 3,000 yen")
        ver = {"images": {"texts": 2, "unsupported": []}}
        # M3 (implementation review): the external attribution follows the move too
        self.assertEqual(images.verify_problems(self.root, self.cfg, TID, st, ver, amend=True), [])
        out = images.status(self.root, self.cfg, TID)
        self.assertEqual(out["snippets"][0]["in_body"], 1)
        self.assertEqual([i["status"] for i in out["items"]], ["ready", "ready"])

    def test_trim_refuses_attribution_and_image_text(self):
        from hrdlib.hashing import worktree_hash
        self.ready()
        st = self.state()
        cur = worktree_hash(self.root, self.cfg, SLUG)
        st["stage"] = "verify"
        st["stages"]["critique"] = {"body_hash": cur}
        store.save_state(self.root, TID, st)
        text = open(os.path.join(self.root, "src/content/blog/%s.md" % SLUG)).read()
        spans = images.snippet_spans(self.root, self.cfg, TID, st, text)
        self.assertEqual(text[spans[0][0]:spans[0][1]], images.snippet_text(self.cfg, self.e1(), "landscape"))

        def verify(sentence, **extra):
            self.write(W + "/verify.json", json.dumps(dict({"body_hash": cur, "counts": {
                "supported": 1, "unsupported": 1, "contradicted": 0, "unmapped": 0},
                "unsupported_sentences": [sentence]}, **extra)))
        verify("Someone")  # a value inside the attribution (the credit)
        with self.assertRaises(Exception) as cm:
            store.trim_begin(self.root, self.cfg, TID)
        self.assertIn("overlaps an image attribution", str(cm.exception))
        verify("That is all.", images={"texts": 2, "unsupported": [{"id": "d1", "text": "Fee 3,000 yen", "why": "x"}]})
        with self.assertRaises(Exception) as cm:
            store.trim_begin(self.root, self.cfg, TID)
        self.assertIn("unsupported text in a diagram is never trimmed", str(cm.exception))
        verify("That is all.")  # the same sentence, nothing about images: the trim opens
        store.trim_begin(self.root, self.cfg, TID)
        self.assertEqual(self.state()["trim"]["status"], "open")

    def test_ship5_settings_change_needs_no_render(self):
        """M2 (implementation review): after publish the repo changes diagrams.width and a human
        fixes a typo in the PR; ship §5 on a machine without limner must pass."""
        self.ready()
        st = self.state()
        st["stage"] = "publish"
        store.save_state(self.root, TID, st)
        self.config(lambda c: c["images"]["diagrams"].update(width=1600))
        os.remove(self.lmn)
        limner.reset_cache()
        s = images.status(self.root, self.cfg, TID)
        self.assertEqual(s["pending"]["render_after_push"], [])
        self.assertEqual(s["pending"]["render"], ["d1"])  # draft's strict view still sees the settings
        out = images.render(self.root, self.cfg, TID, after_push=True)
        self.assertEqual((out["skipped"], out["failed"]), (["d1"], []))
        ver = {"images": {"texts": 2, "unsupported": []}}
        self.assertEqual(images.verify_problems(self.root, self.cfg, TID, self.state(), ver, amend=True), [])
        # the human edited the SVG: listed, and the render needs limner
        self.write(W + "/diagrams/d1.svg", SVG.replace("Apply", "Send"))
        self.assertEqual(images.status(self.root, self.cfg, TID)["pending"]["render_after_push"], ["d1"])
        self.assertEqual(images.render(self.root, self.cfg, TID, after_push=True)["failed"][0]["code"], "limner:missing")
        # the human replaced the PNG: listed too
        self.write(W + "/diagrams/d1.svg", SVG)
        self.write("%s/d1-steps.png" % IMG, big_png(seed=b"human"), binary=True)
        self.assertEqual(images.status(self.root, self.cfg, TID)["pending"]["render_after_push"], ["d1"])


class OgTests(ImageCase):
    def setUp(self):
        super().setUp()
        self.config(lambda c: c["images"].update(og={"path": "{images}/{slug}/og.png"}))
        self.og_path = "%s/og.png" % IMG

    def og(self, **kw):
        return images.og(self.root, self.cfg, TID, **kw)

    def test_limner_made_then_key_skips(self):
        out = self.og()
        self.assertEqual((out["status"], out["by"]), ("made", "limner"))
        self.assertTrue(os.path.exists(os.path.join(self.root, self.og_path)))
        data = json.load(open(os.path.join(self.root, W, "og.json")))
        self.assertEqual(data, {"title": "Renewal guide", "lang": "en"})
        n = len(self.calls())
        self.assertEqual(self.og()["status"], "made")
        self.assertEqual(len(self.calls()), n)  # same inputs, same file: limner not called, no probe
        st = self.state()
        st["stage"] = "publish"  # ship §5 after a human's typo fix: nothing to do, no limner (R5-1)
        store.save_state(self.root, TID, st)
        self.assertEqual(self.og()["status"], "made")
        self.assertEqual(len(self.calls()), n)
        st["stage"] = "draft"
        store.save_state(self.root, TID, st)
        self.assertEqual(images.og_draft_problems(self.root, self.cfg, TID, self.state()), [])
        self.body(d1="changed")  # body only: same key
        self.assertEqual(len(self.calls()), n)
        self.write("src/content/blog/%s.md" % SLUG, BODY.replace("Renewal guide", "Renewal guide 2026").format(
            d1="", e1=""))
        self.assertTrue(images.og_draft_problems(self.root, self.cfg, TID, self.state()))
        self.assertEqual(self.og()["status"], "made")
        self.assertIn("og.png", self.removed())  # the old card moved

    def test_off_never_holds(self):
        with mock.patch.dict(os.environ, {"FAKE_LMN_EXIT": "4", "FAKE_LMN_PROBLEMS": '[{"code": "too_small"}]'}):
            out = self.og()
        self.assertEqual((out["status"], out["why"]), ("off", "title-too-long"))
        self.assertFalse(os.path.exists(os.path.join(self.root, self.og_path)))
        n = len(self.calls())
        self.assertEqual(self.og()["why"], "title-too-long")  # a content reason is not retried
        self.assertEqual(len(self.calls()), n)
        self.assertEqual(images.og_draft_problems(self.root, self.cfg, TID, self.state()), [])
        st = self.state()
        st["images"]["og"] = {}
        store.save_state(self.root, TID, st)
        os.remove(self.lmn)
        limner.reset_cache()
        self.assertEqual(self.og()["why"], "no-limner")
        shutil.copy(os.path.join(HERE, "fake_lmn.py"), self.lmn)
        os.chmod(self.lmn, 0o755)
        limner.reset_cache()
        with mock.patch.dict(os.environ, {"FAKE_LMN_FONTS": "missing"}):
            self.assertEqual(self.og()["why"], "limner:fonts")
        limner.reset_cache()
        self.assertEqual(self.og()["status"], "made")  # an environment reason is tried again
        with mock.patch.dict(os.environ, {"FAKE_LMN_EXIT": "4", "FAKE_LMN_PROBLEMS": '[{"code": "low_contrast"}]'}):
            self.body(d1="")
            self.write("src/content/blog/%s.md" % SLUG, BODY.replace("Renewal guide", "Other").format(d1="", e1=""))
            self.assertEqual(self.og()["why"], "low_contrast")

    def test_unknown_file_draft_moves_pr_stage_needs_human(self):
        self.write(self.og_path, big_png(seed=b"agent"), binary=True)
        self.assertEqual(self.og()["status"], "made")
        self.assertIn("og.png", self.removed())
        self.write(self.og_path, big_png(seed=b"human"), binary=True)
        st = self.state()
        st["stage"] = "publish"
        store.save_state(self.root, TID, st)
        out = self.og()
        self.assertEqual((out["status"], out["unknown_file"]), ("needs-human", self.og_path))
        self.assertTrue(os.path.exists(os.path.join(self.root, self.og_path)))
        with mock.patch.dict(os.environ, {"HRD_UNATTENDED": "1"}):
            with self.assertRaises(Exception):
                self.og(human_push=True, pr=1)
        with self.assertRaises(Exception) as cm:  # no push record on this machine
            self.og(human_push=True, pr=1)
        self.assertIn("no Herald push", str(cm.exception))

    def test_human_push_accepted(self):
        self.og()
        self.commit("work", ".")
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        os.makedirs(os.path.join(self.root, ".claude/herald"), exist_ok=True)
        from hrdlib.util import append_jsonl
        append_jsonl(store.paths(self.root)["ledger"], {"topic_id": TID, "kind": "push", "sha": head, "slug": SLUG})
        st = self.state()
        st["stage"] = "publish"
        store.save_state(self.root, TID, st)
        self.commit("stage", ".")
        self.write(self.og_path, big_png(seed=b"human"), binary=True)
        sha = self.commit("a human's OG", ".")
        sh(self.root, "git", "update-ref", "refs/remotes/origin/pr-7", sha)
        self.assertEqual(self.og()["status"], "needs-human")
        out = self.og(human_push=True, pr=7)
        self.assertEqual((out["status"], out["why"]), ("off", "human-file"))
        rec = self.state()["images"]["og"]
        self.assertEqual(rec["sha"], shots.blob(self.root, self.og_path))
        n = len(self.calls())
        self.assertEqual(self.og()["why"], "human-file")  # known now: nothing to do, no needs-human
        self.assertEqual(len(self.calls()), n)
        # a local commit is no human's push
        self.write(self.og_path, big_png(seed=b"local"), binary=True)
        self.commit("local", ".")
        with self.assertRaises(Exception):
            self.og(human_push=True, pr=7)

    def test_quotation_never_the_og(self):
        self.rules({"images": {"external": {"quotation_categories": ["guide"], "quotation_min_chars": 1}}})
        self.config(lambda c: c["images"]["og"].update(fallback_first_image=False))
        self.manifest([self.d1(), self.e1(use="quotation", license=None)])
        self.fetched()
        shutil.copy(os.path.join(self.root, IMG, "e1-lobby.jpg"), os.path.join(self.root, self.og_path))
        with self.assertRaises(Exception):
            self.og()
        self.assertTrue(any("quotation" in p for p in images.og_draft_problems(self.root, self.cfg, TID, self.state())))
        st = self.state()
        self.assertTrue(any("quotation" in p for p in images.verify_problems(self.root, self.cfg, TID, st, {}, amend=True)))

    def test_repo_generator(self):
        gen = os.path.join(self.tmp, "gen")
        with open(gen, "w") as f:
            f.write("#!/usr/bin/env python3\nimport sys, os, zlib, struct\nout = sys.argv[-1]\n"
                    "mode = open(%r).read().strip() if os.path.exists(%r) else 'ok'\n"
                    "if mode == 'fail': sys.exit(3)\n"
                    "if mode == 'side': open('stray.txt', 'w').write('x')\n"
                    "if mode == 'body': open('src/content/blog/new-post.md', 'a').write('x')\n"
                    "os.makedirs(os.path.dirname(out), exist_ok=True)\n"
                    "open(out, 'wb').write(%r)\n" % (gen + ".mode", gen + ".mode", big_png(seed=b"repo")))
        os.chmod(gen, 0o755)
        self.config(lambda c: c["images"].update(og={"path": "public/blog-og/{slug}.png",
                                                    "command": [gen, "--title", "{title}", "{out}"]}))
        path = "public/blog-og/%s.png" % SLUG
        out = self.og()
        self.assertEqual((out["status"], out["by"]), ("made", "repo"))
        # outside path: PR scope, jurisdiction and the `images` exclusion — never the hash
        from hrdlib import commits
        self.assertIn(path, commits.pr_scope_globs(self.cfg, TID, SLUG))
        self.assertIn(path, commits.pr_scope_paths(self.cfg, TID, SLUG))
        from hrdlib.hashing import worktree_hash
        h1 = worktree_hash(self.root, self.cfg, SLUG)
        self.write(path, big_png(seed=b"other"), binary=True)
        self.assertEqual(worktree_hash(self.root, self.cfg, SLUG), h1)
        self.assertTrue(images.og_excluded(self.root, self.cfg, TID, None, [path], SLUG))
        os.remove(os.path.join(self.root, path))
        open(gen + ".mode", "w").write("fail")
        self.write("src/content/blog/%s.md" % SLUG, BODY.replace("Renewal guide", "T2").format(d1="", e1=""))
        self.assertEqual(self.og()["why"], "repo:exit-nonzero")
        for mode in ("side", "body"):
            open(gen + ".mode", "w").write(mode)
            self.write("src/content/blog/%s.md" % SLUG, BODY.replace("Renewal guide", "T-" + mode).format(d1="", e1=""))
            with self.assertRaises(Exception) as cm:
                self.og()
            self.assertIn("og:side-effects", str(cm.exception))
            if os.path.exists(os.path.join(self.root, "stray.txt")):
                os.remove(os.path.join(self.root, "stray.txt"))
        # trial: the published path and the folder it made go again
        open(gen + ".mode", "w").write("ok")
        shutil.rmtree(os.path.join(self.root, "public/blog-og"), ignore_errors=True)
        out = images.og_trial(self.root, self.cfg)
        self.assertTrue(out["ok"], out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "public/blog-og")))

    def test_limner_trial_leaves_nothing(self):
        out = images.og_trial(self.root, self.cfg)
        self.assertTrue(out["ok"], out)
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG)))
        left = [f for dp, _, fns in os.walk(os.path.join(self.root, ".limner")) for f in fns]
        self.assertEqual(left, [])

    def published_refresh(self):
        """The article is published with a card on base; this topic now refreshes it."""
        self.og()
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "publish")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.root, "git", "fetch", "-q", "origin")
        topics = store.load_topics(self.root)
        topics["topics"][0]["refresh_of"] = SLUG
        store.save_topics(self.root, topics)
        st = self.state()
        st["images"]["og"] = {}
        store.save_state(self.root, TID, st)
        return shots.blob(self.root, self.og_path)

    def base_card_in_place(self, base_blob):
        self.assertEqual(shots.blob(self.root, self.og_path), base_blob)
        self.assertEqual(sh(self.root, "git", "status", "--porcelain", "--", self.og_path), "")
        self.assertEqual(images.og_draft_problems(self.root, self.cfg, TID, self.state()), [])

    def test_kept_never_loses_the_base_card(self):
        """M1 (implementation review): a refresh made its own card, a loopback brought the base
        title back — `kept` must leave base's card in place, on every path."""
        base_blob = self.published_refresh()
        self.write("src/content/blog/%s.md" % SLUG, BODY.replace("Renewal guide", "New title").format(d1="", e1=""))
        self.assertEqual(self.og()["status"], "made")
        self.assertNotEqual(shots.blob(self.root, self.og_path), base_blob)
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(d1="", e1=""))
        self.assertEqual(self.og()["status"], "kept")
        self.base_card_in_place(base_blob)
        self.assertEqual(self.og()["status"], "kept")  # the early return keeps it so
        self.base_card_in_place(base_blob)
        # the card deleted after `kept`: stage pass refuses, and `og` (early return) puts it back
        os.remove(os.path.join(self.root, self.og_path))
        self.assertTrue(images.og_draft_problems(self.root, self.cfg, TID, self.state()))
        self.assertEqual(self.og()["status"], "kept")
        self.base_card_in_place(base_blob)
        # a content `off` (title too long) on a refresh: base's card stays as well
        self.write("src/content/blog/%s.md" % SLUG, BODY.replace("Renewal guide", "T3").format(d1="", e1=""))
        with mock.patch.dict(os.environ, {"FAKE_LMN_EXIT": "4", "FAKE_LMN_PROBLEMS": '[{"code": "overflow"}]'}):
            self.assertEqual(self.og()["why"], "title-too-long")
        self.base_card_in_place(base_blob)
        os.remove(os.path.join(self.root, self.og_path))
        self.assertEqual(self.og()["why"], "title-too-long")
        self.base_card_in_place(base_blob)

    def test_pr_stage_deletion_of_the_base_card_is_asked(self):
        """n1 (review round 2): at the PR stage a human's deletion of base's card is a human's
        change — `needs-human`, never silently restored."""
        base_blob = self.published_refresh()
        self.assertEqual(self.og()["status"], "kept")
        st = self.state()
        st["stage"] = "publish"
        store.save_state(self.root, TID, st)
        os.remove(os.path.join(self.root, self.og_path))
        out = self.og()
        self.assertEqual((out["status"], out["unknown_file"]), ("needs-human", "%s (deleted)" % self.og_path))
        self.assertFalse(os.path.exists(os.path.join(self.root, self.og_path)))
        with self.assertRaises(Exception) as cm:  # taking it needs this machine's push record
            self.og(human_push=True, pr=1)
        self.assertIn("no Herald push", str(cm.exception))
        # in draft the card is Herald's to keep: put back
        st["stage"] = "draft"
        store.save_state(self.root, TID, st)
        self.assertEqual(self.og()["status"], "kept")
        self.assertEqual(shots.blob(self.root, self.og_path), base_blob)

    def test_kept_and_stale_base(self):
        # published with a card, then refreshed
        self.og()
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "publish")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.root, "git", "fetch", "-q", "origin")
        topics = store.load_topics(self.root)
        topics["topics"][0]["refresh_of"] = SLUG
        store.save_topics(self.root, topics)
        st = self.state()
        st["images"]["og"] = {}
        store.save_state(self.root, TID, st)
        self.assertEqual(self.og()["status"], "kept")
        self.write("src/content/blog/%s.md" % SLUG, BODY.replace("Renewal guide", "New title").format(d1="", e1=""))
        os.remove(self.lmn)
        limner.reset_cache()
        out = self.og()
        self.assertEqual(out["status"], "off")
        self.assertTrue(self.state()["images"]["og"]["stale_base"])
        self.assertTrue(images.og_excluded(self.root, self.cfg, TID, None, [], SLUG))
        self.assertTrue(os.path.exists(os.path.join(self.root, self.og_path)))  # base's card untouched


class ExclusionTests(ImageCase):
    def test_external_images_not_lifted_by_consent(self):
        self.ready()
        self.commit("wip", ".")
        changed = [p for p in sh(self.root, "git", "diff", "--name-only", "origin/main...HEAD").split() if p]
        self.assertTrue(images.excluded_external(self.root, self.cfg, TID, None, changed))
        self.assertIn("external-images", store.blocking_exclusions(["external-images", "images"], consent=True))
        self.assertNotIn("images", store.blocking_exclusions(["external-images", "images"], consent=True))
        # diagrams only: `images` and no `external-images`
        self.manifest([self.d1()])
        st = self.state()
        st["images"]["files"] = {k: v for k, v in st["images"]["files"].items() if v["kind"] == "diagram"}
        store.save_state(self.root, TID, st)
        self.assertFalse(images.excluded_external(self.root, self.cfg, TID, None, changed))
        # unreadable manifest with records: fail closed
        self.write(W + "/images.json", "{bad")
        self.assertTrue(images.excluded_external(self.root, self.cfg, TID, None, changed))

    def test_exclusion_reasons(self):
        self.ready()
        self.write(W + "/critique.json", json.dumps({"final_round": {"verdict": "PASS"}, "audit_log": [],
                                                      "decision_log": []}))
        self.commit("wip", ".")  # the exclusion reads the committed diff
        reasons = store.exclusion_reasons(self.root, self.cfg, TID)
        self.assertIn("external-images", reasons)
        self.assertIn("images", reasons)
        self.assertIn("external-images", store.blocking_exclusions(reasons, consent=True))
        out, _ = self.hrd("auto-exclusion", "--topic", TID, "--consent")
        self.assertIn("external-images", out["blocking"])

    def test_cli(self):
        out, _ = self.hrd("image", "kinds", "--topic", TID)
        self.assertTrue(out["diagram"]["ok"])
        out, _ = self.hrd("image", "plan", "--topic", TID)
        self.assertEqual(out["pending"]["render"], ["d1"])
        out, _ = self.hrd("image", "render", "--topic", TID)
        self.assertEqual(out["rendered"][0]["id"], "d1")
        out, _ = self.hrd("image", "texts", "--topic", TID)
        self.assertEqual(len(out["texts"]), 2)
        out, _ = self.hrd("image", "status", "--topic", TID)
        self.assertEqual(out["pending"]["fetch"], ["e1"])
        _, p = self.hrd("image", "confirm", "--topic", TID, "--id", "e1", env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("unattended", p.stderr)
        out, _ = self.hrd("config-check")
        self.assertEqual((out["limner_errors"], out["og_errors"], out["figure_errors"]), ([], [], []))

    def test_publish_scope(self):
        self.ready()
        self.commit("wip", ".")
        self.assertEqual(images.scope_problems(self.root, self.cfg, TID, publish=True), [])
        self.assertEqual(images.scope_problems(self.root, self.cfg, TID, publish=False), [])
        self.body(e1="![The office lobby](/blog-images/%s/e1-lobby.jpg)" % SLUG)
        self.commit("drop attribution", ".")
        self.assertTrue(images.scope_problems(self.root, self.cfg, TID, publish=True))

    def test_pr_rows_and_status(self):
        self.ready()
        out = images.status(self.root, self.cfg, TID)
        self.assertTrue(out["all_ready"])
        rows = "\n".join(out["pr_rows"])
        self.assertIn("licensed CC BY-SA 3.0", rows)
        self.assertIn("2 texts, claims C1", rows)
        self.assertEqual(out["snippets"][0]["alt"], "The office lobby")
        self.assertEqual(out["snippets"][0]["in_body"], 1)

    def test_tampered_render_record(self):
        from hrdlib import commits
        self.render()
        sha = self.commit("herald push", ".")
        with open(os.path.join(self.root, images.renders_rel(TID)), "a") as f:
            f.write('{"forged": 1}\n')
        self.commit("human push", ".")
        res = commits.scope_check(self.root, self.cfg, TID, SLUG, rev="HEAD", herald_sha=sha)
        self.assertIn(images.renders_rel(TID), res["tampered"])


class GuardTests(ImageCase):
    def guard(self, tool, tool_input, env=None):
        e = dict(os.environ)
        e.update(env or {})
        payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                           capture_output=True, text=True, env=e, cwd=self.root, timeout=60)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_guard(self):
        un = {"HRD_UNATTENDED": "1"}
        for cmd in ("python3 .claude/herald/scripts/hrd.py image confirm --topic t0001 --id e1",
                    "python3 .claude/herald/scripts/hrd.py image reject --topic t0001 --id e1 --reason x"):
            self.assertEqual(self.guard("Bash", {"command": cmd}), "ask")
            self.assertEqual(self.guard("Bash", {"command": cmd}, un), "deny")
        self.assertEqual(self.guard("Bash", {"command": "python3 .claude/herald/scripts/hrd.py image fetch --topic t0001"}),
                         "allow")
        rr = images.renders_rel(TID)
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, rr), "content": "x"}), "ask")
        self.assertEqual(self.guard("Edit", {"file_path": os.path.join(self.root, rr)}, un), "deny")
        self.assertEqual(self.guard("Bash", {"command": "echo '{}' >> %s" % rr}, un), "deny")
        for cmd in ("git clean -fd -- %s" % W, "git checkout HEAD -- %s" % W, "git add -A -- %s" % W):
            self.assertEqual(self.guard("Bash", {"command": cmd}), "allow", cmd)
        for key, val in (("limner", {"command": ["x"]}), ("images", {})):
            cfg = json.load(open(os.path.join(self.root, ".claude/herald/config.json")))
            cfg[key] = val
            self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, ".claude/herald/config.json"),
                                                  "content": json.dumps(cfg)}), "ask", key)
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, shots.FETCHES), "content": "x"}), "ask")


class ShotsIntegrationTests(ImageCase):
    def test_note_and_resume(self):
        self.fetched()
        st = self.state()
        st["screenshots"] = {"shots": {"s1": {"status": "pending"}}}
        note = shots.hold_note(st)
        self.assertEqual(note, "screenshots: s1 e1(confirm)")
        shots.check_note(note)
        shots.check_note("screenshots: e1(confirm)")
        with self.assertRaises(Exception):
            shots.check_note("screenshots: e1(watermark)")
        self.assertTrue(images.resume_at_collect(self.root, self.cfg, self.state()))
        self.body(d1="edited")
        self.assertFalse(images.resume_at_collect(self.root, self.cfg, self.state()))
        self.hrd("loopback", "--topic", TID, "--human")
        self.assertFalse(self.state()["images"]["awaiting"])
        _, p = self.hrd("result", "--topic", TID, "--status", "held:screenshots", "--note", "screenshots: e1(confirm)",
                        check=False)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_scan_skips_confirmed_external_and_checks_replaced(self):
        self.ready()
        self.assertEqual(shots.scan(self.root, self.cfg, SLUG), [])  # ICC kept on purpose (P15)
        files = {f: k for f, k, _ in shots.slug_files(self.root, self.cfg, SLUG)}
        self.assertEqual(files["%s/e1-lobby.jpg" % IMG], "external")
        self.write("%s/e1-lobby.jpg" % IMG, big_jpeg(), binary=True)  # a human's replacement with metadata
        found = shots.scan(self.root, self.cfg, SLUG)
        self.assertEqual([x["file"] for x in found], ["%s/e1-lobby.jpg" % IMG])
        out = shots.strip(self.root, "%s/e1-lobby.jpg" % IMG)
        self.assertTrue(out["changed"])
        self.assertNotIn(b"ICC_PROFILE", open(os.path.join(self.root, IMG, "e1-lobby.jpg"), "rb").read())

    def test_shot_manifest_warning_skips_managed_files(self):
        self.render()
        self.write(W + "/screenshots.json", json.dumps({"shots": []}))
        st = self.state()
        st["slug"] = SLUG
        _, warnings, _ = shots.check_manifest(self.root, self.cfg, TID, st, {"shots": []})
        self.assertFalse(any("d1-steps.png" in w for w in warnings), warnings)


class GateTests(ImageCase):
    def test_merge_and_hotlinks(self):
        from hrdlib import validate
        self.rules({"images": {"external": {"max": 2}}})
        ext = validate.load_rules(self.root)["images"]["external"]
        self.assertEqual(ext["max"], 2)
        self.assertIn("CC BY 4.0", ext["licenses"])
        self.assertEqual(ext["min_width"], 280)
        self.body(e1="![x](https://example.com/a.png)")
        rep = validate.validate(self.root, self.cfg, "src/content/blog/%s.md" % SLUG)
        self.assertTrue(any("hotlinked" in e for e in rep["errors"]))
        self.body(e1="![x](data:image/png;base64,iVBORw0KGgo=)")  # m5: an inlined picture
        rep = validate.validate(self.root, self.cfg, "src/content/blog/%s.md" % SLUG)
        self.assertTrue(any("data: URI" in e for e in rep["errors"]))
        self.config(lambda c: c.pop("images"))
        rep = validate.validate(self.root, self.cfg, "src/content/blog/%s.md" % SLUG)
        self.assertFalse(any("hotlinked" in e or "data: URI" in e for e in rep["errors"]))


class CostTests(ImageCase):
    def test_external_on_base_is_bounded(self):
        """M4 (implementation review): `external_on_base` reads base once per command — one `git
        grep` when nothing on base records an external image (any 0.16 repo), never a process per
        topic or per call."""
        for n in range(40):
            st = store.new_state("t%04d" % (100 + n), "post-%d" % n)
            store.save_state(self.root, "t%04d" % (100 + n), st)
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "many topics")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.root, "git", "fetch", "-q", "origin")
        calls = []
        real = images._git_run

        def count(*a, **k):
            calls.append(a[1][0])
            return real(*a, **k)
        self.config(lambda c: c.pop("images"))
        images._BASE_EXTERNAL.clear()
        with mock.patch.object(images, "_git_run", side_effect=count):
            for n in range(40):
                self.assertEqual(images.external_on_base(self.root, self.cfg, "post-%d" % n), [])
        self.assertEqual(calls, ["grep"])
        # with external images on base: still a fixed number of processes per command
        self.config(lambda c: c.update(images={"external": True, "figure": FIGURE}))
        self.manifest([self.e1()])
        self.body(d1="")
        self.route(SRC, jpeg_route())
        self.fetch()
        self.put_snippet()
        self.plan()
        images.confirm(self.root, self.cfg, TID, "e1")
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "publish")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.root, "git", "fetch", "-q", "origin")
        calls.clear()
        with mock.patch.object(images, "_git_run", side_effect=count):
            for n in range(40):
                images.external_on_base(self.root, self.cfg, "post-%d" % n)
            self.assertEqual(images.external_on_base(self.root, self.cfg, SLUG), ["%s/e1-lobby.jpg" % IMG])
        self.assertEqual(calls, ["grep", "cat-file", "cat-file"])

    def test_select_and_missing_without_images_block(self):
        """The CLI paths of a 0.16 translation repo: no `images` block → no per-topic reads."""
        self.config(lambda c: c.pop("images"))
        self.config(lambda c: c.update(translations={"source": "en", "targets": [
            {"lang": "ko", "body_pattern": "{content}/ko/{slug}.md", "url_pattern": "/ko/{slug}/"}]},
            roles={"conditional": ["illustrator", "translator"]}))
        images._BASE_EXTERNAL.clear()
        calls = []
        real = images._git_run
        with mock.patch.object(images, "_git_run", side_effect=lambda *a, **k: calls.append(1) or real(*a, **k)):
            for n in range(25):
                images.external_on_base(self.root, self.cfg, "post-%d" % n)
        self.assertLessEqual(len(calls), 1)


class TranslationBlockTests(ImageCase):
    def test_begin_and_missing_refuse_external_image_articles(self):
        self.ready()
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "publish")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.root, "git", "fetch", "-q", "origin")
        self.assertEqual(images.external_on_base(self.root, self.cfg, SLUG), ["%s/e1-lobby.jpg" % IMG])
        self.assertEqual(images.external_on_base(self.root, self.cfg, "old-post"), [])
        sh(self.root, "git", "switch", "-q", "main")
        sh(self.root, "git", "merge", "-q", "--ff-only", "origin/main")
        self.config(lambda c: c.update(translations={"source": "en", "targets": [
            {"lang": "ko", "body_pattern": "{content}/ko/{slug}.md", "url_pattern": "/ko/{slug}/"}]},
            roles={"conditional": ["illustrator", "translator"]}))
        topics = store.load_topics(self.root)
        topics["topics"].append({"id": "tr-new-post-20261110", "title": "x", "translate_of": SLUG, "state": "queued", "history": [],
                                 "reverted_by": []})
        store.save_topics(self.root, topics)
        _, p = self.hrd("begin", "--topic", "tr-new-post-20261110", check=False)
        self.assertIn("external images block translation", p.stderr)
        out, _ = self.hrd("select")
        self.assertNotIn("tr-new-post-20261110", out)
        topics["topics"] = [dict(topics["topics"][0], state="published")]
        store.save_topics(self.root, topics)
        sh(self.root, "git", "branch", "-q", "-D", store.branch_name(TID, SLUG))
        store.save_published(self.root, {"articles": [{"slug": SLUG, "origin": "herald", "path": "x",
                                                       "published_at": "2026-11-01"}]})
        out, _ = self.hrd("translate", "missing")
        self.assertEqual(out["blocked"][0]["reason"], "external-images")
        self.assertEqual(out["articles"], [])
        # n2 (review round 2): the batch runner's selection drops it too
        from hrdlib import batch
        topics = store.load_topics(self.root)
        topics["topics"].append({"id": "tr-new-post-20261111", "title": "x", "translate_of": SLUG, "state": "queued",
                                 "history": [], "reverted_by": []})
        topics["topics"].append({"id": "tr-old-post-20261111", "title": "y", "translate_of": "old-post",
                                 "state": "queued", "history": [], "reverted_by": []})
        store.save_topics(self.root, topics)
        cfg = Config.load(self.root)
        self.assertEqual(batch.select_topics(self.root, cfg, 5), ["tr-old-post-20261111"])
        topics["topics"] = topics["topics"][:1]
        store.save_topics(self.root, topics)
        # m10: a refresh is refused at the candidate step, with the reason
        from hrdlib import refresh
        pc = refresh.precheck(self.root, Config.load(self.root), SLUG, clear=False)
        self.assertNotIn("update", pc["choices"])
        self.assertTrue(any("external-images" in b for b in pc["blocked"]))


@unittest.skipUnless(os.environ.get("HRD_TEST_LIMNER"), "real limner: set HRD_TEST_LIMNER to the limner argv")
class RealLimnerTests(ImageCase):
    def test_render_and_og(self):
        self.config(lambda c: c["limner"].update(command=os.environ["HRD_TEST_LIMNER"].split()))
        out = self.render()
        self.assertEqual(out["rendered"][0]["problems"], [], out)
        self.config(lambda c: c["images"].update(og={"path": "{images}/{slug}/og.png"}))
        self.assertEqual(images.og(self.root, self.cfg, TID)["status"], "made")


def setUpModule():
    if not os.environ.get("HRD_TEST_LIMNER"):
        sys.stderr.write("test_images: the real-limner test was not run (set HRD_TEST_LIMNER)\n")


if __name__ == "__main__":
    unittest.main()
