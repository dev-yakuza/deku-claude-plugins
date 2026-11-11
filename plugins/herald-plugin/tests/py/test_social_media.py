"""SNS formats (design/herald/10-social-media.md, 0.19.0): `--format image|cards|comic`, the media
spec, the materials (the article's limner OG, diagrams in a render record, confirmed scenes — never
a quotation's or an external image's bytes), `HRD social media` against a fake `lmn` (generation
with limner's real records, `compose --layout` with limner's real compose record), the words in
the pictures checked with the post (P23), the AI disclosure (P25), the compose-record proof check
and close read (§2.5), `--final`, the guide and persona fields, lint, merge and the guard. A run
of `--format text` is 0.18 (test_social, test_social_growth run unchanged). The real limner runs
only with HRD_TEST_LIMNER_COMPOSE (fonts installed)."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helpers import HERE, SCRIPTS, sh
from test_social import PERSONA, SocialCase, guide_head, guide_text, persona_text

from hrdlib import guard, images, limner, shots, social, social_media as sm, store
from hrdlib.hashing import bundle_hash

IMG = "public/blog-images/old-post"
APPEARANCE = "a woman in her thirties with short black hair, a green cardigan and round glasses"
HANDLE = "@safie_official"
AI = {"where": "post", "text": "#AIgenerated"}
URL = "https://example.test/blog/old-post/"
QUOTE = [{"text": "Body text for old-post.", "from": "body"}]
PROMO_Q = [{"text": "Safie keeps your camera footage safe in the cloud.", "from": "promotion"}]
P = "A woman reading a train timetable on a station platform, seen from the side"


def png(tag):
    return b"\x89PNG\r\n\x1a\n" + tag.encode() + b"\x00" * 16


def real_png(w, h, rgb):
    """A PNG limner can decode (the fake never decodes)."""
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def media_head(**over):
    h = guide_head(formats=["text", "image", "cards", "comic"], image_aspect="4x5", max_images=10, ai_disclosure=AI)
    h.update(over)
    return h


class MediaCase(SocialCase):
    def setUp(self):
        super().setUp()
        limner.reset_cache()
        images._BASE_MANAGED.clear()
        self.lmndir = os.path.join(self.tmp, "lmn")
        os.makedirs(self.lmndir)
        self.lmn = os.path.join(self.lmndir, "lmn")
        shutil.copy(os.path.join(HERE, "fake_lmn.py"), self.lmn)
        os.chmod(self.lmn, os.stat(self.lmn).st_mode | stat.S_IEXEC)
        for k in [k for k in os.environ if k.startswith("FAKE_LMN_")] + ["HRD_TEST_ALLOW_FAKE_GENERATOR",
                                                                          "LIMNER_FAKE_GENERATOR"]:
            os.environ.pop(k, None)
        os.environ["FAKE_LMN_DIR"] = self.lmndir
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["limner"] = {"command": [self.lmn], "state_dir": ".limner"}
        cfg["images"] = {"og": {"path": "{images}/{slug}/og.png"}}
        self.write(".claude/herald/config.json", json.dumps(cfg))
        with open(os.path.join(self.root, ".gitignore"), "a") as f:
            f.write(".limner/\n")
        p = dict(PERSONA, appearance=APPEARANCE, service_terms=PERSONA["service_terms"] + [HANDLE])
        self.write("docs/editorial/persona.md", persona_text(p))
        self.write("docs/editorial/channels/x.md", guide_text(media_head()))
        self.write(IMG + "/og.png", png("og"), binary=True)
        self.write(IMG + "/d1-steps.png", png("d1"), binary=True)
        self.write(IMG + "/g1-platform.png", png("g1"), binary=True)
        self.write(IMG + "/e1-lobby.jpg", png("e1"), binary=True)
        self.commit("pictures")
        self.reload()
        b = {n: shots.blob(self.root, "%s/%s" % (IMG, n)) for n in ("og.png", "d1-steps.png", "g1-platform.png",
                                                                    "e1-lobby.jpg")}
        self.blobs = b
        self.state({"files": {IMG + "/d1-steps.png": {"kind": "diagram", "use": None},
                              IMG + "/g1-platform.png": {"kind": "scene", "use": None},
                              IMG + "/e1-lobby.jpg": {"kind": "external", "use": "licensed"}},
                    "items": {"d1": {"kind": "diagram", "file": IMG + "/d1-steps.png", "status": "ready"},
                              "g1": {"kind": "scene", "file": IMG + "/g1-platform.png", "status": "ready",
                                     "sha": b["g1-platform.png"], "generated_blob": b["g1-platform.png"]},
                              "e1": {"kind": "external", "file": IMG + "/e1-lobby.jpg", "status": "ready"}},
                    "og": {"status": "made", "by": "limner", "sha": b["og.png"]}})
        self.write(store.work_rel("t0001", "diagram-renders.jsonl"), json.dumps(
            {"svg_sha256": "a" * 64, "background": "#ffffff", "png_blob": b["d1-steps.png"], "png_sha256": "b" * 64,
             "width": 800, "texts": ["Step 1"]}) + "\n")
        self.commit("records")
        sh(self.root, "git", "push", "-q", "origin", "main")

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith("FAKE_LMN_")]:
            os.environ.pop(k)
        super().tearDown()

    # helpers
    def state(self, imgs, extra=None):
        st = {"slug": "old-post", "verified_hash": bundle_hash(self.root, self.cfg, "old-post", rev="HEAD"),
              "images": imgs}
        st.update(extra or {})
        self.write(store.work_rel("t0001", "state.json"), json.dumps(st))

    def guide(self, **over):
        self.write("docs/editorial/channels/x.md", guide_text(media_head(**over)))
        self.commit("guide")
        limner.reset_cache()

    def prep(self, fmt, slug="old-post", n=1, check=True, env=None):
        args = ["social", "prepare", "--sns", "x", "--n", str(n), "--format", fmt] + (["--slug", slug] if slug else [])
        out, p = self.hrd(*args, check=check, env=env)
        return out if check else p

    def mdraft(self, rel, body, spec, fmt=None, kind=None, sources=None):
        rec = social.drafted_record(self.root, rel)
        kind = kind or rec["kind"]
        src = json.dumps(sources if sources is not None else (QUOTE if kind == "promo" else []), ensure_ascii=False)
        self.write(rel, "---\nsns: x\nkind: %s\nslug: %s\nrun: %s\nformat: %s\nsources: %s\n---\n%s\n"
                   % (kind, rec.get("slug") or "", rec["run"], fmt or rec["format"], src, body))
        if spec is not None:
            self.write(sm.spec_rel(rel), json.dumps(spec, ensure_ascii=False))

    def media(self, rel, wait=0, stage=None, env=None):
        with mock.patch.dict(os.environ, env or {}):
            limner.reset_cache()
            return sm.media(self.root, self.cfg, rel, wait=wait, stage=stage)

    def check(self, rel):
        limner.reset_cache()
        return social.check_draft(self.root, self.cfg, rel)

    def failed(self, rel):
        return sorted({f["id"] for f in self.check(rel)["failed"]})

    def calls(self):
        p = os.path.join(self.lmndir, "calls.jsonl")
        return [json.loads(x) for x in open(p)] if os.path.exists(p) else []

    def events(self, kind="media"):
        return [e for e in social.events(self.root) if e.get("event") == kind]

    def promo_image(self, spec_from=IMG + "/d1-steps.png", body=None):
        rel = self.prep("image")["drafts"][0]
        self.mdraft(rel, body or "A short note. #PR " + URL, {"version": 1, "format": "image",
                                                               "image": {"from": spec_from}})
        return rel

    def cards_spec(self, cover_image=None, **body):
        cover = {"template": "card-cover", "title": "Renewing in two steps"}
        if cover_image is not None:
            cover["image"] = cover_image
        b = {"template": "card-body", "heading": "Step one", "body": "Book a slot online.", "sources": []}
        b.update(body)
        return {"version": 1, "format": "cards", "cards": [
            cover, b, {"template": "card-end", "message": "Read the full guide"}]}

    def comic_spec(self, layout="strip-2x2", boxes=True, **p1):
        panels = []
        for i in range(1, (4 if layout == "strip-2x2" else 6) + 1):
            p = {"prompt": P, "seed": i, "bubbles": [{"kind": "speech", "text": "Good morning"}]}
            if boxes:
                p["bubbles"][0].update(box=[40, 300, 300, 460], tail=[200, 200])
            panels.append(p)
        panels[0].update(p1)
        return {"version": 1, "format": "comic", "layout": layout, "panels": panels}

    def daily_comic(self, body="Monday again. #AIgenerated", **kw):
        rel = self.prep("comic", slug=None)["drafts"][0]
        self.mdraft(rel, body, self.comic_spec(**kw))
        return rel


class PrepareTests(MediaCase):
    def test_text_is_018(self):
        out = self.prep("text")
        self.assertEqual(out["format"], "text")
        self.assertNotIn("materials", out)
        self.assertEqual(social.drafted_record(self.root, out["drafts"][0])["format"], "text")
        out = self.hrd("social", "prepare", "--sns", "x", "--n", "1")[0]  # no --format: text
        self.assertEqual(out["format"], "text")
        self.assertEqual([c for c in self.calls() if c and c[0] in ("run", "compose")], [])  # no limner asked

    def test_format_must_be_in_the_guide(self):
        self.guide(formats=["text", "image"])
        self.assertIn("takes text, image posts only", self.prep("cards", check=False).stderr)
        self.guide(house={"formats": ["text"]})
        self.assertIn("takes text posts only", self.prep("image", check=False).stderr)
        h = guide_head()  # a 0.18 guide: text only
        self.write("docs/editorial/channels/x.md", guide_text(h))
        self.commit("old guide")
        self.assertIn("--refresh x", self.prep("image", check=False).stderr)

    def test_language_and_limner(self):
        self.guide(lang="fr")
        self.assertIn("ko, ja and en only", self.prep("image", slug=None, check=False).stderr)
        self.guide()
        p = self.prep("image", check=False, env={"FAKE_LMN_FONTS": "missing"})
        self.assertIn("limner:fonts", p.stderr)
        self.prep("text", env={"FAKE_LMN_FONTS": "missing"})  # text never asks limner

    def test_materials(self):
        out = self.prep("image")
        got = {m["path"]: m["kind"] for m in out["materials"]}
        self.assertEqual(got, {IMG + "/og.png": "og", IMG + "/d1-steps.png": "diagram",
                               IMG + "/g1-platform.png": "scene", "gen": "gen"})
        self.assertEqual(out["media_paths"], [out["drafts"][0][:-3] + ".media.json"])
        self.assertEqual(out["gen_size"], [720, 896])
        self.assertEqual(social.drafted_record(self.root, out["drafts"][0])["format"], "image")
        m = next(x for x in out["materials"] if x["kind"] == "og")
        self.assertEqual(m["blob"], self.blobs["og.png"])

    def test_materials_refused(self):
        st = json.loads(open(os.path.join(self.root, store.work_rel("t0001", "state.json"))).read())
        st["images"]["og"]["by"] = "repo"  # a repo generator's card: Herald does not know its content
        st["images"]["items"]["g1"]["generated_blob"] = "0" * 40  # a human's picture at the scene's place
        st["verified_hash"] = bundle_hash(self.root, self.cfg, "old-post", rev="HEAD")
        self.write(store.work_rel("t0001", "state.json"), json.dumps(st))
        self.commit("refused")
        got = {m["path"] for m in self.prep("image")["materials"]}
        self.assertEqual(got, {IMG + "/d1-steps.png", "gen"})

    def test_quotation_and_external_bytes_refused(self):
        # the diagram's bytes are also an external image's: never on a post (P16)
        self.write(IMG + "/e1-lobby.jpg", png("d1"), binary=True)
        self.commit("same bytes")
        self.state(json.loads(open(os.path.join(self.root, store.work_rel("t0001", "state.json"))).read())["images"])
        self.commit("rehash")
        got = {m["path"] for m in self.prep("image")["materials"]}
        self.assertNotIn(IMG + "/d1-steps.png", got)

    def test_head_blob_must_match(self):
        self.write(IMG + "/g1-platform.png", png("g1-edited"), binary=True)
        self.write(IMG + "/d1-steps.png", png("d1-edited"), binary=True)
        self.commit("edited by hand")
        self.state(json.loads(open(os.path.join(self.root, store.work_rel("t0001", "state.json"))).read())["images"])
        self.commit("rehash")
        got = {m["path"] for m in self.prep("image")["materials"]}
        self.assertEqual(got, {IMG + "/og.png", "gen"})

    def test_moved_slug_chain(self):
        # the state still names the old slug and its paths; the article moved to old-post
        st = json.loads(open(os.path.join(self.root, store.work_rel("t0001", "state.json"))).read())
        old = "public/blog-images/older"
        st["slug"] = "older"
        st["images"]["items"]["g1"]["file"] = old + "/g1-platform.png"
        st["images"]["files"] = {k.replace(IMG, old): v for k, v in st["images"]["files"].items()}
        self.write(store.work_rel("t0001", "state.json"), json.dumps(st))
        pub = store.load_published(self.root)
        pub["articles"][0]["moved_from"] = [{"slug": "older"}]
        store.save_published(self.root, pub)
        self.commit("moved")
        got = {m["path"] for m in self.prep("image")["materials"]}
        self.assertIn(IMG + "/g1-platform.png", got)
        self.assertIn(IMG + "/d1-steps.png", got)

    def test_ai_disclosure_conditions(self):
        self.guide(ai_disclosure=None)
        out = self.prep("image")
        self.assertEqual({m["kind"] for m in out["materials"]}, {"og", "diagram"})  # no gen, no scene (R1-7)
        self.assertIn("ai_disclosure", self.prep("comic", check=False).stderr)
        self.guide(ai_disclosure={"waiver": {"reason": "the platform labels it", "approved_at": "2026-11-11"}})
        out = self.prep("comic", n=3)
        self.assertEqual(len(out["drafts"]), 1)  # a comic run has one draft (Q2)
        self.assertEqual(out["panel_size"], {"strip-2x2": [508, 508], "strip-3x2": [508, 423]})
        self.guide()
        p = self.prep("comic", check=False, env={"FAKE_LMN_GEN_ENV": "models are not ready"})
        self.assertIn("cannot generate", p.stderr)
        out = self.prep("cards", env={"FAKE_LMN_GEN_ENV": "models are not ready"})
        self.assertNotIn("gen", {m["path"] for m in out["materials"]})
        self.assertIn(IMG + "/g1-platform.png", {m["path"] for m in out["materials"]})  # a scene needs no generator

    def test_daily_has_gen_only(self):
        out = self.prep("image", slug=None)
        self.assertEqual(out["materials"], [{"path": "gen", "kind": "gen", "blob": None, "sha256": None}])
        self.assertEqual(out["handles"], [])
        self.assertEqual(self.prep("cards")["handles"], [HANDLE])


class SpecTests(MediaCase):
    def setUp(self):
        super().setUp()
        self.mats = {m["path"]: m for m in sm.materials(self.root, self.cfg, "old-post", True)}
        self.persona = dict(PERSONA, appearance=APPEARANCE, service_terms=PERSONA["service_terms"] + [HANDLE])

    def errs(self, spec, fmt, kind="promo", stage="compose", mats=None):
        return sm.spec_problems(spec, fmt, kind, mats if mats is not None else self.mats, self.persona, stage)

    def test_image(self):
        self.assertEqual(self.errs({"version": 1, "format": "image", "image": {"from": IMG + "/d1-steps.png"}},
                                   "image"), [])
        self.assertEqual(self.errs({"version": 1, "format": "image", "image": {"from": "gen", "prompt": P, "seed": 2}},
                                   "image"), [])
        e = self.errs({"version": 1, "format": "image", "image": {"from": IMG + "/e1-lobby.jpg"}}, "image")
        self.assertTrue(any("not one of this draft's materials" in x for x in e), e)
        e = self.errs({"version": 1, "format": "image", "image": {"from": "gen", "prompt": "日本の駅", "seed": 2}},
                      "image")
        self.assertTrue(any("printable ASCII" in x for x in e), e)
        e = self.errs({"version": 1, "format": "image", "image": {"from": "gen", "prompt": P, "seed": 2}}, "image",
                      mats={k: v for k, v in self.mats.items() if k != "gen"})
        self.assertTrue(any("no picture can be generated" in x for x in e), e)
        e = self.errs({"version": 1, "format": "cards", "cards": []}, "image")
        self.assertTrue(any("but this run is image" in x for x in e), e)

    def test_cards(self):
        ok = self.cards_spec()
        self.assertEqual(self.errs(ok, "cards"), [])
        bad = self.cards_spec()
        bad["cards"][0]["title"] = "x" * 121
        bad["cards"][0]["page"] = "1/3"
        bad["cards"][1]["body"] = "See https://evil.test/x for more"
        bad["cards"][2]["handle"] = "@someone_else"
        e = "\n".join(self.errs(bad, "cards"))
        for want in ("title must be 1–120", "takes no page", "holds a URL", "account handles"):
            self.assertIn(want, e)
        empty = self.cards_spec()
        empty["cards"][0]["subtitle"] = ""  # an empty optional field is left out (R3-4)
        empty["cards"][2]["handle"] = ""
        self.assertEqual(self.errs(empty, "cards"), [])
        lay = sm.layouts(empty, "cards", "en", lambda ref: "x.png")
        self.assertEqual(len(lay[0]["layers"]), 1)
        self.assertEqual(len(lay[2]["layers"]), 1)
        empty["cards"][1]["heading"] = ""
        self.assertTrue(any("heading must be 1–120" in x for x in self.errs(empty, "cards")))
        e = self.errs(self.cards_spec(cover_image=IMG + "/d1-steps.png"), "cards")
        self.assertTrue(any("a diagram cannot be used here" in x for x in e), e)  # a 4:3 crop cuts labels
        self.assertEqual(self.errs(self.cards_spec(cover_image=IMG + "/g1-platform.png"), "cards"), [])
        self.assertEqual(self.errs(self.cards_spec(cover_image={"from": "gen", "prompt": P, "seed": 1}), "cards"), [])
        two = self.cards_spec()
        two["cards"] = two["cards"][:2]
        self.assertTrue(any("2 cards" in x for x in self.errs(two, "cards")))
        order = self.cards_spec()
        order["cards"] = [order["cards"][1], order["cards"][0], order["cards"][2]]
        self.assertTrue(any("first card" in x for x in self.errs(order, "cards")))
        h = self.cards_spec()
        h["cards"][2]["handle"] = HANDLE
        self.assertEqual(self.errs(h, "cards"), [])
        self.assertTrue(any("promotional cards only" in x for x in self.errs(h, "cards", kind="daily")))

    def test_comic(self):
        self.assertEqual(self.errs(self.comic_spec(), "comic"), [])
        self.assertEqual(self.errs(self.comic_spec(boxes=False), "comic", stage="panels"), [])
        self.assertTrue(any("box must be" in x for x in self.errs(self.comic_spec(boxes=False), "comic")))
        three = self.comic_spec()
        three["panels"] = three["panels"][:3]
        self.assertTrue(any("exactly 4 panels" in x for x in self.errs(three, "comic")))
        s = self.comic_spec()
        s["panels"][0]["bubbles"] = [{"kind": "speech", "text": "Hi", "box": [300, 100, 505, 200]},
                                     {"kind": "shout", "text": "Wow", "box": [320, 150, 480, 300]}]
        e = "\n".join(self.errs(s, "comic"))
        self.assertIn("leaves the panel box", e)
        self.assertIn("overlaps bubble 1", e)
        s = self.comic_spec(layout="strip-3x2")
        s["panels"][0]["bubbles"][0]["box"] = [40, 300, 300, 420]  # 423 high, 8 px margin
        self.assertTrue(any("leaves the panel box" in x for x in self.errs(s, "comic")))
        s = self.comic_spec()
        s["panels"][0]["bubbles"][0]["tail"] = [600, 10]
        self.assertTrue(any("tail must be" in x for x in self.errs(s, "comic")))
        s = self.comic_spec()
        s["panels"][0]["bubbles"] *= 4
        self.assertTrue(any("at most 3 bubbles" in x for x in self.errs(s, "comic")))
        s = self.comic_spec(persona=True)
        self.assertTrue(any("appearance word for word" in x for x in self.errs(s, "comic")))
        s = self.comic_spec(persona=True, prompt=APPEARANCE + " reads a timetable")
        self.assertEqual(self.errs(s, "comic"), [])
        s = self.comic_spec(caption={"text": "Monday", "pos": "middle"})
        self.assertTrue(any("caption.pos" in x for x in self.errs(s, "comic")))
        self.assertEqual(self.errs(s, "comic", stage="panels"), [])

    def test_image_text_and_sources(self):
        s = self.cards_spec()
        s["cards"][2]["handle"] = HANDLE
        s["cards"][1]["sources"] = QUOTE
        self.assertEqual(sm.image_text(s, "cards"), "Renewing in two steps\nStep one\nBook a slot online.\n"
                                                    "Read the full guide")  # never the handle (v3 R2-3)
        self.assertEqual(sm.spec_sources(s, "cards"), QUOTE)
        c = self.comic_spec(caption={"text": "Monday", "pos": "top"})
        self.assertTrue(sm.image_text(c, "comic").startswith("Monday\nGood morning\n"))


class MediaTests(MediaCase):
    def test_image_material(self):
        rel = self.promo_image()
        # the working tree's file is not what goes out: HEAD's content (v3 R2-5)
        self.write(IMG + "/d1-steps.png", png("uncommitted"), binary=True)
        out = self.media(rel)
        self.assertEqual(out["state"], "done", out)
        self.assertFalse(out["generated"])
        name = os.path.basename(rel)[:-3]
        self.assertEqual(out["files"], [social.memory_rel("x", "media", name, "1.png")])
        run = social.drafted_record(self.root, rel)["run"]
        copy = ".limner/herald-out/social/%s/1/in-%s.png" % (run, hashlib.sha256(png("d1")).hexdigest()[:12])
        self.assertEqual(open(os.path.join(self.root, copy), "rb").read(), png("d1"))
        lay = json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1-layout-1.json" % run)))
        self.assertEqual(lay["canvas"]["preset"], "instagram-4x5")
        self.assertEqual(lay["layers"], [{"type": "image", "src": copy, "box": [0, 0, 1080, 1350], "fit": "contain"}])
        compose = [c for c in self.calls() if c[0] == "compose"]
        self.assertEqual(len(compose), 1)
        self.assertIn("--layout", compose[0])
        self.assertNotIn("--template", compose[0])
        ev = self.events()[-1]
        self.assertEqual(ev["materials"], [{"path": IMG + "/d1-steps.png", "blob": self.blobs["d1-steps.png"],
                                            "sha256": hashlib.sha256(png("d1")).hexdigest()}])
        self.assertEqual(ev["generated"], False)
        self.assertEqual(sh(self.root, "git", "status", "--porcelain", "--", "public", "src").strip(),
                         "M %s/d1-steps.png" % IMG)  # nothing new in the working tree
        self.assertEqual(self.check(rel)["ok"], True, self.check(rel))

    def test_image_gen_writes_no_ledger(self):
        self.guide(image_aspect="16x9")
        rel = self.promo_image(spec_from=None, body="A short note. #PR #AIgenerated " + URL)
        self.mdraft(rel, "A short note. #PR #AIgenerated " + URL,
                    {"version": 1, "format": "image", "image": {"from": "gen", "prompt": P, "seed": 9}})
        out = self.media(rel)
        self.assertEqual(out["state"], "done", out)
        self.assertTrue(out["generated"])
        run = social.drafted_record(self.root, rel)["run"]
        job = json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1.json" % run)))["jobs"][0]
        self.assertEqual((job["width"], job["height"], job["refs"], job["seed"]), (1024, 576, [], 9))
        self.assertTrue(job["prompt"].startswith(P) and job["prompt"].endswith(images.NO_TEXT))
        self.assertEqual(job["out"], ".limner/herald-out/social/%s/1/gen-1.png" % run)
        self.assertFalse(os.path.exists(os.path.join(self.root, shots.GENERATIONS)))  # P26: no generation ledger
        lay = json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1-layout-1.json" % run)))
        self.assertEqual(lay["canvas"]["preset"], "x-16x9")
        res = self.check(rel)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["media"]["generated"], True)

    def test_gen_record_must_vouch(self):
        rel = self.promo_image(body="x #PR #AIgenerated " + URL)
        self.mdraft(rel, "x #PR #AIgenerated " + URL,
                    {"version": 1, "format": "image", "image": {"from": "gen", "prompt": P, "seed": 9}})
        out = self.media(rel, env={"FAKE_LMN_RECORD": json.dumps({"refs": [{"path": "x.png", "sha256": "0" * 64}]})})
        self.assertEqual(out["state"], "failed")
        self.assertEqual(out["errors"][0]["code"], "record-mismatch")
        shutil.rmtree(os.path.join(self.root, ".limner/herald-out"))
        shutil.rmtree(os.path.join(self.root, ".limner/records"))
        out = self.media(rel, env={"FAKE_LMN_GENERATOR": "fake"})  # limner's fake engine: tests only
        self.assertEqual(out["errors"][0]["code"], "fake-generator")
        out = self.media(rel, env={"FAKE_LMN_GENERATOR": "fake", "HRD_TEST_ALLOW_FAKE_GENERATOR": "1"})
        self.assertEqual(out["state"], "done", out)

    def test_running_then_done(self):
        rel = self.promo_image(body="x #PR #AIgenerated " + URL)
        self.mdraft(rel, "x #PR #AIgenerated " + URL,
                    {"version": 1, "format": "image", "image": {"from": "gen", "prompt": P, "seed": 9}})
        out = self.media(rel, env={"FAKE_LMN_STATUS": "10,0"})
        self.assertEqual((out["state"], out["remaining"]), ("running", ["img"]))
        run = social.drafted_record(self.root, rel)["run"]
        g = json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1.gen.json" % run)))
        self.assertTrue(g["gen"]["run_id"])
        out = self.media(rel, env={"FAKE_LMN_STATUS": "10,0"})
        self.assertEqual(out["state"], "done", out)
        g = json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1.gen.json" % run)))
        self.assertIsNone(g["gen"])
        self.assertEqual(len(g["drawn"]), 1)

    def test_cards_layouts(self):
        rel = self.prep("cards")["drafts"][0]
        spec = self.cards_spec(cover_image={"from": "gen", "prompt": P, "seed": 4})
        spec["cards"][2]["handle"] = HANDLE
        self.mdraft(rel, "Two steps. #PR #AIgenerated " + URL, spec)
        out = self.media(rel)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(len(out["files"]), 3)
        run = social.drafted_record(self.root, rel)["run"]
        job = json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1.json" % run)))["jobs"][0]
        self.assertEqual((job["width"], job["height"]), (1024, 768))  # a generated cover is 4:3 (v3 R2-6)
        lays = [json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1-layout-%d.json" % (run, i))))
                for i in (1, 2, 3)]
        cover, body, end = lays
        self.assertEqual(cover["layers"][0], {"type": "image", "src": ".limner/herald-out/social/%s/1/gen-1.png" % run,
                                              "box": [0, 0, 1080, 810], "fit": "cover"})
        self.assertEqual(len(cover["layers"]), 2)  # no subtitle: its layer goes (R3-4)
        self.assertEqual(cover["layers"][1]["runs"], [{"text": "Renewing in two steps"}])
        self.assertEqual(cover["layers"][1]["lang"], "en")
        self.assertEqual(body["layers"][-1]["runs"], [{"text": "2/3"}])  # page: card-body only
        self.assertEqual(end["layers"][1]["runs"], [{"text": HANDLE}])
        self.assertEqual(end["canvas"], {"preset": "instagram-4x5", "background": "#111827"})
        self.assertFalse(any("when" in l or "{{" in json.dumps(l) for lay in lays for l in lay["layers"]))
        self.assertTrue(self.check(rel)["ok"], self.check(rel))

    def test_comic_two_stages(self):
        rel = self.prep("comic", slug=None)["drafts"][0]
        spec = self.comic_spec(boxes=False)
        self.mdraft(rel, "Monday again. #AIgenerated", spec)
        out = self.media(rel)  # the compose stage wants coordinates
        self.assertEqual(out["state"], "failed")
        self.assertIn("box must be", out["errors"][0]["message"])
        self.assertEqual([c for c in self.calls() if c[0] == "run" and "--check" not in c], [])
        out = self.media(rel, stage="panels")
        self.assertEqual(out["state"], "done", out)
        name = os.path.basename(rel)[:-3]
        self.assertEqual(out["preview"], social.memory_rel("x", "media", name, "preview", "preview.png"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, out["preview"])))
        self.assertEqual(out["panel_size"], [508, 508])
        self.assertEqual([p["n"] for p in out["panels"]], [1, 2, 3, 4])
        run = social.drafted_record(self.root, rel)["run"]
        prev = json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1-preview.json" % run)))
        self.assertEqual({l["type"] for l in prev["layers"]}, {"image"})  # panels alone (v3 R2-6)
        res = self.check(rel)
        self.assertIn("media-spec", {f["id"] for f in res["failed"]})  # no coordinates yet
        self.assertEqual(res["media"]["preview"], out["preview"])
        spec = self.comic_spec(caption={"text": "Monday", "pos": "top"})
        self.mdraft(rel, "Monday again. #AIgenerated", spec)
        n = len([c for c in self.calls() if c[0] == "run"])
        out = self.media(rel)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(len([c for c in self.calls() if c[0] == "run"]), n)  # the panels were made already
        self.assertFalse(os.path.exists(os.path.join(self.root, social.memory_rel("x", "media", name, "preview"))))
        lay = json.load(open(os.path.join(self.root, ".limner/herald-jobs/social-%s-1-layout-1.json" % run)))
        imgs = [l for l in lay["layers"] if l["type"] == "image"]
        self.assertEqual([l["box"] for l in imgs], sm.STRIPS["strip-2x2"]["boxes"])
        self.assertEqual(imgs[0]["border"], {"width": 4, "color": "#000000"})
        cap = next(l for l in lay["layers"] if l["type"] == "caption")
        self.assertEqual((cap["box"], cap["min_size"]), ([24, 24, 532, 24 + 91], 20))
        bub = [l for l in lay["layers"] if l["type"] == "bubble"]
        self.assertEqual((bub[1]["box"], bub[1]["tail"], bub[1]["min_size"]),
                         ([548 + 40, 24 + 300, 548 + 300, 24 + 460], [548 + 200, 24 + 200], 22))
        self.assertTrue(self.check(rel)["ok"], self.check(rel))

    def test_compose_exits(self):
        rel = self.promo_image()
        out = self.media(rel, env={"FAKE_LMN_COMPOSE_EXIT": "2"})
        self.assertEqual(out["errors"][0]["class"], "internal")  # Herald's layout broke limner's checks
        out = self.media(rel, env={"FAKE_LMN_FONTS": "missing"})
        self.assertEqual((out["errors"][0]["code"], out["errors"][0]["class"]), ("limner:fonts", "env"))
        out = self.media(rel, env={"FAKE_LMN_COMPOSE_EXIT": "70"})
        self.assertEqual(out["errors"][0]["class"], "env")
        out = self.media(rel, env={"FAKE_LMN_EXIT": "4", "FAKE_LMN_PROBLEMS": '[{"code": "overflow", "layer": 0}]'})
        self.assertEqual(out["state"], "done")  # kept with its problems: the human decides (R3-3)
        self.assertEqual(out["problems"], [{"code": "overflow", "layer": 0, "i": 1}])
        res = self.check(rel)
        mp = [f for f in res["failed"] if f["id"] == "media-problems"]
        self.assertEqual([f["overridable"] for f in mp], [True])
        self.media(rel, env={"FAKE_LMN_EXIT": "4", "FAKE_LMN_PROBLEMS": '[{"code": "missing_glyph", "layer": 0}]'})
        mp = [f for f in self.check(rel)["failed"] if f["id"] == "media-problems"]
        self.assertEqual([f["overridable"] for f in mp], [False])

    def test_compose_budget(self):
        rel = self.promo_image()
        with mock.patch.object(sm, "COMPOSE_START_MIN", 10 ** 6):
            out = self.media(rel)
        self.assertEqual((out["state"], out["remaining"]), ("running", ["compose-1"]))
        self.assertEqual(self.events(), [])

    def test_words_checked_before_generating(self):
        rel = self.daily_comic()
        spec = self.comic_spec()
        spec["panels"][1]["bubbles"][0]["text"] = "30% more trains today"
        self.mdraft(rel, "Monday again. #AIgenerated", spec)
        out = self.media(rel)
        self.assertEqual(out["state"], "failed")
        self.assertEqual([e["code"] for e in out["errors"]], ["s9b-statistic"])
        self.assertEqual([c for c in self.calls() if c[0] == "run" and "herald-jobs" in json.dumps(c)], [])
        # nothing drawn for words that fail

    def test_media_profile_is_checks(self):
        # R3-2: the post names the service and quotes promotion.md, the bubbles do not
        rel = self.daily_comic(body="Safie has a new app, they say. #PR #AIgenerated")
        self.mdraft(rel, "Safie has a new app, they say. #PR #AIgenerated", self.comic_spec(), sources=PROMO_Q)
        self.assertEqual(self.media(rel)["state"], "done")
        # and the other way round: a bubble names it, the quote is in the post's header
        spec = self.comic_spec()
        spec["panels"][0]["bubbles"][0]["text"] = "Safie keeps it safe"
        self.mdraft(rel, "Monday again. #PR #AIgenerated", spec, sources=PROMO_Q)
        self.assertEqual(self.media(rel)["state"], "done")
        self.assertEqual(self.check(rel)["profile"], "daily+service")

    def test_redraw_limit(self):
        rel = self.daily_comic()
        self.assertEqual(self.media(rel)["state"], "done")
        spec = self.comic_spec()
        for p in spec["panels"]:
            p["seed"] += 10
        self.mdraft(rel, "Monday again. #AIgenerated", spec)
        self.assertEqual(self.media(rel)["state"], "done")  # four drawn again: the limit
        spec["panels"][0]["seed"] = 99
        self.mdraft(rel, "Monday again. #AIgenerated", spec)
        out = self.media(rel)
        self.assertEqual((out["state"], out["errors"][0]["code"], out["errors"][0]["class"]),
                         ("failed", "redraw-limit", "human"))


class CheckTests(MediaCase):
    def test_bubble_service_name_is_daily_plus_service(self):
        spec = self.comic_spec()
        spec["panels"][2]["bubbles"][0]["text"] = "I saw it on Safie"
        rel = self.daily_comic()
        self.mdraft(rel, "Monday again. #AIgenerated", spec)
        res = self.check(rel)
        self.assertEqual(res["profile"], "daily+service")
        ids = {f["id"] for f in res["failed"]}
        self.assertIn("disclosure", ids)  # the ad disclosure is the post text's
        self.assertIn("sources", ids)

    def test_card_statistic_and_quotes(self):
        rel = self.prep("cards", slug=None)["drafts"][0]
        self.mdraft(rel, "Little things. #AIgenerated", self.cards_spec(body="Twice as fast: 2倍"))
        self.assertIn("s9b-statistic", self.failed(rel))
        rel = self.prep("cards")["drafts"][0]
        self.mdraft(rel, "Two steps. #PR " + URL,
                    self.cards_spec(sources=[{"text": "A sentence the article never says.", "from": "body"}]))
        self.assertIn("sources", self.failed(rel))
        self.mdraft(rel, "Two steps. #PR " + URL, self.cards_spec(sources=QUOTE))
        self.assertNotIn("sources", self.failed(rel))

    def test_media_missing_and_stale(self):
        rel = self.promo_image()
        self.assertIn("media-missing", self.failed(rel))
        self.assertEqual(self.media(rel)["state"], "done")
        self.assertEqual(self.failed(rel), [])
        name = os.path.basename(rel)[:-3]
        mfile = os.path.join(self.root, social.memory_rel("x", "media", name, "1.png"))
        # the spec
        self.mdraft(rel, "A short note. #PR " + URL, {"version": 1, "format": "image", "image": {"from": IMG + "/og.png"}})
        self.assertIn("media-stale", self.failed(rel))
        self.mdraft(rel, "A short note. #PR " + URL,
                    {"version": 1, "format": "image", "image": {"from": IMG + "/d1-steps.png"}})
        self.assertEqual(self.failed(rel), [])
        # the file
        keep = open(mfile, "rb").read()
        with open(mfile, "wb") as f:
            f.write(png("a screenshot"))
        self.assertIn("media-stale", self.failed(rel))
        with open(mfile, "wb") as f:
            f.write(keep)
        open(os.path.join(os.path.dirname(mfile), "2.png"), "wb").write(png("extra"))
        self.assertIn("media-stale", self.failed(rel))
        os.remove(os.path.join(os.path.dirname(mfile), "2.png"))
        self.assertEqual(self.failed(rel), [])
        # the material on base
        self.write(IMG + "/d1-steps.png", png("d1-v2"), binary=True)
        self.commit("d1 again")
        self.assertIn("media-spec", self.failed(rel))  # no render record: no material any more

    def test_direct_compose_is_stale(self):
        rel = self.promo_image()
        self.assertEqual(self.media(rel)["state"], "done")
        run = social.drafted_record(self.root, rel)["run"]
        lp = os.path.join(self.root, ".limner/herald-jobs/social-%s-1-layout-1.json" % run)
        lay = json.load(open(lp))
        lay["layers"].append({"type": "text", "box": [0, 0, 500, 100], "lang": "en",
                              "runs": [{"text": "Users up 95%!"}]})
        own = os.path.join(self.tmp, "mine.json")
        json.dump(lay, open(own, "w"))
        out_rel = ".limner/herald-out/social/%s/1/composed-1.png" % run
        subprocess.run([self.lmn, "compose", "--layout", own, "--root", self.root, "--state-dir",
                        os.path.join(self.root, ".limner"), "--out", os.path.join(self.root, out_rel)],
                       capture_output=True, env=dict(os.environ))
        name = os.path.basename(rel)[:-3]
        shutil.copyfile(os.path.join(self.root, out_rel),
                        os.path.join(self.root, social.memory_rel("x", "media", name, "1.png")))
        ev = self.events()[-1]
        ev["files"][0]["sha256"] = hashlib.sha256(open(os.path.join(self.root, out_rel), "rb").read()).hexdigest()
        social.log_event(self.root, ev)  # even the log says so
        res = self.check(rel)
        stale = [f for f in res["failed"] if f["id"] == "media-stale"]
        self.assertTrue(stale and "another layout" in stale[0]["detail"], res)

    def test_foreign_input_is_stale(self):
        rel = self.promo_image()
        self.assertEqual(self.media(rel, env={"FAKE_LMN_COMPOSE_INPUT": IMG + "/e1-lobby.jpg"})["state"], "failed")
        self.assertEqual(self.media(rel)["state"], "done")
        self.assertEqual(self.failed(rel), [])

    def test_ai_disclosure_kinds(self):
        rel = self.daily_comic(body="Monday again.")
        self.assertEqual(self.media(rel)["state"], "done")  # the post text's rules wait for check
        self.assertEqual(self.failed(rel), ["disclosure-ai"])  # a daily comic needs it too (P25)
        self.mdraft(rel, "Monday again. #AIgenerated", self.comic_spec())
        res = self.check(rel)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["profile"], "daily")
        self.guide(ai_disclosure={"where": "setting", "text": "AI info label"})
        self.mdraft(rel, "Monday again.", self.comic_spec())
        res = self.check(rel)
        self.assertEqual(res["settings_to_confirm"], ["ai"])
        self.guide(ai_disclosure={"waiver": {"reason": "the platform labels it", "approved_at": "2026-11-11"}})
        res = self.check(rel)
        self.assertEqual(res["settings_to_confirm"], [])
        self.assertNotIn("disclosure-ai", {f["id"] for f in res["failed"]})

    def test_ai_tag_is_no_hashtag_and_no_tail(self):
        self.guide(hashtags=[0, 1])
        rel = self.promo_image(spec_from=None)
        self.mdraft(rel, "A short note. #PR #travel " + URL + " #AIgenerated",
                    {"version": 1, "format": "image", "image": {"from": "gen", "prompt": P, "seed": 9}})
        self.media(rel)
        self.assertEqual(self.failed(rel), [])

    def test_header_format(self):
        rel = self.promo_image()
        self.media(rel)
        self.mdraft(rel, "A short note. #PR " + URL, None, fmt="text")
        self.assertIn("header-mismatch", self.failed(rel))

    def test_scene_material_is_generated(self):
        rel = self.promo_image(spec_from=IMG + "/g1-platform.png")
        self.media(rel)
        self.assertEqual(self.failed(rel), ["disclosure-ai"])


class CloseTests(MediaCase):
    def test_close_copies_and_records(self):
        rel = self.prep("comic", slug=None)["drafts"][0]
        self.mdraft(rel, "Monday again. #AIgenerated", self.comic_spec())
        self.media(rel, stage="panels")
        self.media(rel)
        run = social.drafted_record(self.root, rel)["run"]
        out = social.close(self.root, self.cfg, run, approved=rel)
        name = os.path.basename(rel)[:-3]
        self.assertEqual(out["media"], [social.memory_rel("approved", "x", name, "1.png")])
        self.assertTrue(out["generated"])
        st = social.latest_status(self.root)[rel]
        sha = hashlib.sha256(open(os.path.join(self.root, out["media"][0]), "rb").read()).hexdigest()
        self.assertEqual(st["media"][0]["sha256"], sha)
        self.assertEqual((st["format"], st["generated"]), ("comic", True))
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, social.memory_rel("approved", "x", name)))),
                         ["1.png"])  # never the preview

    def test_close_refuses_stale_and_wants_the_ai_setting(self):
        rel = self.promo_image()
        run = social.drafted_record(self.root, rel)["run"]
        with self.assertRaises(Exception) as e:
            social.close(self.root, self.cfg, run, approved=rel)
        self.assertIn("media-missing", str(e.exception))
        self.guide(ai_disclosure={"where": "setting", "text": "AI info label"})
        rel = self.promo_image(spec_from=IMG + "/g1-platform.png")
        self.media(rel)
        run = social.drafted_record(self.root, rel)["run"]
        with self.assertRaises(Exception) as e:
            social.close(self.root, self.cfg, run, approved=rel)
        self.assertIn("--setting-confirmed ai", str(e.exception))
        out = social.close(self.root, self.cfg, run, approved=rel, settings_confirmed=["ai"])
        self.assertTrue(out["generated"])

    def test_close_override_for_problems(self):
        rel = self.promo_image()
        self.media(rel, env={"FAKE_LMN_EXIT": "4", "FAKE_LMN_PROBLEMS": '[{"code": "too_small", "layer": 0}]'})
        run = social.drafted_record(self.root, rel)["run"]
        with self.assertRaises(Exception) as e:
            social.close(self.root, self.cfg, run, approved=rel)
        self.assertIn("--override", str(e.exception))
        out = social.close(self.root, self.cfg, run, approved=rel, override="the human reads it fine")
        self.assertEqual(out["override"]["rules"], ["media-problems"])


class FinalTests(MediaCase):
    def approve_daily_comic(self, bubble="Good morning", body="Monday again. #AIgenerated", sources=None):
        rel = self.prep("comic", slug=None)["drafts"][0]
        spec = self.comic_spec()
        spec["panels"][0]["bubbles"][0]["text"] = bubble
        self.mdraft(rel, body, spec, sources=sources)
        self.assertEqual(self.media(rel)["state"], "done")
        run = social.drafted_record(self.root, rel)["run"]
        social.close(self.root, self.cfg, run, approved=rel)
        return rel

    def final(self, rel, text):
        p = social.memory_rel("final", "x", os.path.basename(rel))
        self.write(p, text)
        return social.final(self.root, self.cfg, rel, p)

    def test_profile_carries_over(self):
        rel = self.approve_daily_comic(bubble="Safie keeps it safe", body="Monday again. #PR #AIgenerated",
                                       sources=PROMO_Q)
        self.assertEqual(social.latest_status(self.root)[rel]["profile"], "daily+service")
        out = self.final(rel, "Monday again.")
        self.assertEqual(out["check"]["profile"], "daily+service")  # never down to daily (v3 R2-1)
        self.assertIn("disclosure", out["fix_live_post"])
        self.assertIn("disclosure-ai", out["fix_live_post"])
        self.assertEqual(social.latest_status(self.root)[rel]["profile"], "daily+service")
        self.assertEqual(social.recent_mix(self.root)["promo"], 1)

    def test_ai_setting_on_final(self):
        a, b = self.approve_daily_comic(), self.approve_daily_comic()
        self.assertEqual(self.final(a, "Monday again. #AIgenerated")["fix_live_post"], [])
        self.guide(ai_disclosure={"where": "setting", "text": "AI info label"})
        self.assertEqual(self.final(b, "Monday again.")["fix_live_post"], ["setting:ai"])


class GuideLintTests(MediaCase):
    def lint(self, head, mode="edit", allow=(), target="docs/editorial/channels/x.md", text=None):
        p = social.memory_rel("pending", "channels", "x.md")
        self.write(p, text or guide_text(head))
        return social.lint(self.root, self.cfg, mode, p, target, allow_floor=allow)

    def test_fields(self):
        bad = media_head(formats=["text", "video"], image_aspect="3x2", max_images=30,
                         house={"formats": ["comic", "text"]})
        bad["formats"] = ["text", "video"]
        e = "\n".join(self.lint(bad)["errors"])
        for want in ("formats must be", "image_aspect must be", "max_images must be"):
            self.assertIn(want, e)
        e = "\n".join(self.lint(media_head(formats=["text", "image"], house={"formats": ["comic"]}))["errors"])
        self.assertIn("house.formats only narrows", e)
        out = self.lint(media_head(house={"formats": ["text", "image"]}))
        self.assertTrue(out["ok"], out)
        self.assertEqual(social.effective(media_head(house={"formats": ["comic", "text"]}))["formats"], ["text", "comic"])

    def test_research_fields_by_refresh_only(self):
        e = "\n".join(self.lint(media_head(formats=["text", "image"]))["errors"])
        self.assertIn("research fields change only through --refresh: formats", e)
        out = self.lint(media_head(house={"formats": ["text", "image"]}), mode="evolve")
        self.assertTrue(out["ok"], out)
        self.guide(house={"formats": ["text"]})
        e = "\n".join(self.lint(media_head(house={"formats": ["text", "image"]}), mode="evolve")["errors"])
        self.assertIn("loosened: formats", e)

    def test_ai_disclosure_lint_and_floor(self):
        e = "\n".join(self.lint(media_head(ai_disclosure={"where": "post", "text": "AI https://x.test/ai"}))["errors"])
        self.assertIn("contains a URL", e)
        e = "\n".join(self.lint(media_head(ai_disclosure={"where": "post", "text": "@ai_label"}))["errors"])
        self.assertIn("@handle", e)
        e = "\n".join(self.lint(media_head(ai_disclosure={"where": "post", "text": " "}))["errors"])
        self.assertIn("needs a text", e)
        for new, tok in (({"where": "post", "text": "#AIart"}, "ai_disclosure:text"),
                         ({"where": "setting", "text": "AI info"}, "ai_disclosure:moved"),
                         ({"waiver": {"reason": "r", "approved_at": "2026-11-11"}}, "ai_disclosure:waiver"),
                         (None, "ai_disclosure:removed")):
            h = media_head(ai_disclosure=new)
            if new is None:
                h.pop("ai_disclosure")
            out = self.lint(h)
            self.assertIn(tok, "\n".join(out["errors"]), new)
            out = self.lint(h, allow=[tok])
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["trailers"], ["Herald-Floor: x::%s" % tok])
        self.guide(ai_disclosure={"where": "setting", "text": "AI info"})
        self.assertTrue(self.lint(media_head())["ok"])  # setting → post: stronger
        e = "\n".join(self.lint(media_head(ai_disclosure={"waiver": {"reason": "r", "approved_at": "2026-11-11"}}),
                                mode="evolve")["errors"])
        self.assertIn("AI disclosure waiver changes only through --edit", e)

    def test_persona_appearance(self):
        p = social.memory_rel("pending", "persona.md")
        terms = PERSONA["service_terms"] + [HANDLE]
        for bad in ("日本人の女性", "x" * 301, 'a "quoted" man', 7):
            self.write(p, persona_text(dict(PERSONA, appearance=bad, service_terms=terms)))
            out = social.lint(self.root, self.cfg, "persona", p, "docs/editorial/persona.md")
            self.assertIn("appearance must be", "\n".join(out["errors"]), bad)
        self.write(p, persona_text(dict(PERSONA, appearance="an older man in a grey coat", service_terms=terms)))
        out = social.lint(self.root, self.cfg, "persona", p, "docs/editorial/persona.md")
        self.assertTrue(out["ok"], out)  # a new field, not a floor change


class MergeTests(MediaCase):
    def research(self, **over):
        p = social.memory_rel("pending", "channels", "x.md")
        self.write(p, guide_text(media_head(**over)))
        return p

    def test_refresh_takes_formats_and_a_new_ai_disclosure(self):
        h = guide_head()  # a 0.18 guide
        self.write("docs/editorial/channels/x.md", guide_text(h))
        self.commit("0.18 guide")
        out = social.merge(self.root, self.cfg, "x", self.research())
        self.assertEqual(sorted(set(out["changed"]) & {"formats", "image_aspect", "max_images"}),
                         ["formats", "image_aspect", "max_images"])
        self.assertEqual(out["ai_disclosure_added"], AI)
        merged = social.parse_channel(open(os.path.join(self.root, out["out"])).read())[0]
        self.assertEqual((merged["formats"], merged["ai_disclosure"]), (["text", "image", "cards", "comic"], AI))
        lint = social.lint(self.root, self.cfg, "refresh", out["out"], "docs/editorial/channels/x.md")
        self.assertTrue(lint["ok"], lint)

    def test_refresh_keeps_a_stronger_one_and_the_waiver(self):
        out = social.merge(self.root, self.cfg, "x", self.research(ai_disclosure={"where": "setting", "text": "AI"}))
        merged = social.parse_channel(open(os.path.join(self.root, out["out"])).read())[0]
        self.assertEqual(merged["ai_disclosure"], AI)
        self.assertEqual([c["token"] for c in out["floor_changes"]], ["ai_disclosure:moved"])
        out = social.merge(self.root, self.cfg, "x", self.research(ai_disclosure={"where": "setting", "text": "AI"}),
                           accept_floor=["ai_disclosure:moved"])
        merged = social.parse_channel(open(os.path.join(self.root, out["out"])).read())[0]
        self.assertEqual(merged["ai_disclosure"]["where"], "setting")
        w = {"waiver": {"reason": "r", "approved_at": "2026-11-11"}}
        self.guide(ai_disclosure=w)
        out = social.merge(self.root, self.cfg, "x", self.research())
        merged = social.parse_channel(open(os.path.join(self.root, out["out"])).read())[0]
        self.assertEqual(merged["ai_disclosure"], w)  # a waiver is the humans'


class GuardTests(MediaCase):
    def guard(self, cmd, env=None):
        e = dict(os.environ)
        e.update(env or {})
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                           capture_output=True, text=True, env=e, cwd=self.root, timeout=60)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_direct_limner(self):
        un = {"HRD_UNATTENDED": "1"}
        for cmd in ("lmn compose --layout mine.json --out x.png", "%s compose --layout a --out b.png" % self.lmn,
                    "env A=1 lmn compose --layout a --out b.png", "uv run --project ../limner lmn compose --layout a"):
            self.assertEqual(self.guard(cmd), "ask", cmd)
            self.assertEqual(self.guard(cmd, un), "deny", cmd)
        for cmd in ("python3 .claude/herald/scripts/hrd.py social media --draft x", "grep lmn README.md",
                    "which lmn"):
            self.assertEqual(self.guard(cmd), "allow", cmd)

    def test_runs_limner(self):
        self.assertTrue(guard.runs_limner(["lmn", "doctor"], self.cfg))
        self.assertFalse(guard.runs_limner(["git", "status"], self.cfg))


class LfsMaterialTests(MediaCase):
    def test_material_copy_goes_through_filters(self):
        sh(self.root, "git", "config", "filter.up.clean", "cat")
        sh(self.root, "git", "config", "filter.up.smudge", "sed s/STORED/SMUDGE/")
        self.write(".gitattributes", "%s/og.png filter=up\n" % IMG)
        self.write(IMG + "/og.png", b"STORED-og-card", binary=True)
        self.commit("filtered og")
        st = json.loads(open(os.path.join(self.root, store.work_rel("t0001", "state.json"))).read())
        st["images"]["og"]["sha"] = sh(self.root, "git", "rev-parse", "HEAD:%s/og.png" % IMG).strip()
        self.state(st["images"])
        self.commit("og sha")
        rel = self.promo_image(spec_from=IMG + "/og.png")
        out = self.media(rel)
        self.assertEqual(out["state"], "done", out)
        run = social.drafted_record(self.root, rel)["run"]
        d = os.path.join(self.root, ".limner/herald-out/social/%s/1" % run)
        copy = [f for f in os.listdir(d) if f.startswith("in-")][0]
        self.assertEqual(open(os.path.join(d, copy), "rb").read(), b"SMUDGE-og-card")
        self.assertEqual(self.failed(rel), [])


class CliTests(MediaCase):
    def test_hrd_social_media(self):
        rel = self.promo_image()
        out, p = self.hrd("social", "media", "--draft", rel, "--wait", "0")
        self.assertEqual(out["state"], "done", p.stderr)
        res, p = self.hrd("social", "check", "--file", rel)
        self.assertTrue(res[0]["ok"], res)
        self.assertEqual(res[0]["media"]["files"], out["files"])
        _, p = self.hrd("social", "media", "--draft", rel, check=False, env={"HRD_UNATTENDED": "1"})
        self.assertIn("interactive only", p.stderr)
        t = self.prep("text")["drafts"][0]
        _, p = self.hrd("social", "media", "--draft", t, check=False)
        self.assertIn("text draft", p.stderr)


class StructureTests(unittest.TestCase):
    def test_versions_and_prompts(self):
        plugin = os.path.abspath(os.path.join(HERE, "..", ".."))
        pj = json.load(open(os.path.join(plugin, ".claude-plugin", "plugin.json")))
        mk = json.load(open(os.path.join(plugin, "..", "..", ".claude-plugin", "marketplace.json")))
        import hrd
        herald = next(p for p in mk["plugins"] if p["name"] == pj["name"])
        self.assertEqual({pj["version"], herald["version"], hrd.SCRIPTS_VERSION}, {"0.19.0"})
        skill = os.path.join(plugin, "skills", "hrd")
        text = open(os.path.join(skill, "commands", "social.md")).read()
        for want in ("HRD social media --draft", "--stage panels", "--format", "media-stale", "setting-confirmed"):
            self.assertIn(want, text)
        self.assertIn("media_paths", open(os.path.join(skill, "templates", "agents", "distributor.md")).read())
        self.assertIn("ai_disclosure", open(os.path.join(skill, "templates", "editorial", "channel.md.tmpl")).read())
        self.assertIn("appearance", open(os.path.join(skill, "templates", "editorial", "persona.md.tmpl")).read())


@unittest.skipUnless(os.environ.get("HRD_TEST_LIMNER_COMPOSE"), "the real limner: set HRD_TEST_LIMNER_COMPOSE=1 "
                     "(fonts installed; generation with LIMNER_FAKE_GENERATOR=1, a temp S2V_STATE_DIR)")
class RealLimnerTests(MediaCase):
    """limner itself (`uv run --project ~/projects/limner lmn` or HRD_TEST_LIMNER_CMD): the compose
    record Herald checks, a card set and a daily comic with limner's fake generator."""

    def setUp(self):
        super().setUp()
        cmd = os.environ.get("HRD_TEST_LIMNER_CMD") or "uv run --project %s lmn" % os.path.expanduser("~/projects/limner")
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["limner"]["command"] = cmd.split()
        self.write(".claude/herald/config.json", json.dumps(cfg))
        self.commit("real limner")
        self.reload()
        # real PNGs for limner to decode
        for k, n in enumerate(("og.png", "d1-steps.png", "g1-platform.png")):
            self.write("%s/%s" % (IMG, n), real_png(64, 48, (40 * k, 120, 200)), binary=True)
        self.write(IMG + "/e1-lobby.jpg", png("e1"), binary=True)
        self.commit("real pictures")
        b = {n: shots.blob(self.root, "%s/%s" % (IMG, n)) for n in ("og.png", "d1-steps.png", "g1-platform.png")}
        st = json.loads(open(os.path.join(self.root, store.work_rel("t0001", "state.json"))).read())
        st["images"]["og"]["sha"] = b["og.png"]
        st["images"]["items"]["g1"].update(sha=b["g1-platform.png"], generated_blob=b["g1-platform.png"])
        self.state(st["images"])
        self.write(store.work_rel("t0001", "diagram-renders.jsonl"), json.dumps(
            {"svg_sha256": "a" * 64, "background": "#ffffff", "png_blob": b["d1-steps.png"], "png_sha256": "b" * 64,
             "width": 800, "texts": ["Step 1"]}) + "\n")
        self.commit("records")
        self.s2v = tempfile.mkdtemp(prefix="hrd-s2v-")
        self.genv = {"LIMNER_FAKE_GENERATOR": "1", "HRD_TEST_ALLOW_FAKE_GENERATOR": "1", "S2V_STATE_DIR": self.s2v,
                     "S2V_TTS_PORT": "9", "S2V_ALIGNER_PORT": "9"}
        self.p = mock.patch.dict(os.environ, self.genv)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.s2v, ignore_errors=True)
        super().tearDown()

    def test_image_and_cards(self):
        rel = self.promo_image()
        out = self.media(rel, wait=120)
        self.assertEqual(out["state"], "done", out)
        rec = limner.read_record(self.root, self.cfg, ".limner/herald-out/social/%s/1/composed-1.png"
                                 % social.drafted_record(self.root, rel)["run"])
        self.assertEqual(rec["kind"], "compose")
        self.assertIn("layout_sha256", rec)
        self.assertTrue(self.check(rel)["ok"], self.check(rel))
        rel = self.prep("cards")["drafts"][0]
        spec = self.cards_spec(cover_image=IMG + "/g1-platform.png")
        spec["cards"][2]["handle"] = HANDLE
        self.mdraft(rel, "Two steps. #PR #AIgenerated " + URL, spec)
        out = self.media(rel, wait=120)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(len(out["files"]), 3)
        res = self.check(rel)
        self.assertEqual([f["id"] for f in res["failed"] if f["id"] != "media-problems"], [], res)

    def test_daily_comic(self):
        rel = self.prep("comic", slug=None)["drafts"][0]
        self.mdraft(rel, "Monday again. #AIgenerated", self.comic_spec(boxes=False))
        out = None
        for _ in range(20):
            out = self.media(rel, wait=240, stage="panels")
            if out["state"] != "running":
                break
        self.assertEqual(out["state"], "done", out)
        self.mdraft(rel, "Monday again. #AIgenerated", self.comic_spec(caption={"text": "Monday", "pos": "top"}))
        out = self.media(rel, wait=120)
        self.assertEqual(out["state"], "done", out)
        res = self.check(rel)
        self.assertEqual([f["id"] for f in res["failed"] if f["id"] != "media-problems"], [], res)


if __name__ == "__main__":
    unittest.main()
