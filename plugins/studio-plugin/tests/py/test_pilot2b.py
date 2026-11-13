"""Pilot 2, 0.0.26 (fix-0026-plan): P16 — the brand's look reaches the script (stdo/look.py: `check_assets.py --look`,
the board check's look rules, the brand logo as a picture with its credit, brand.json in the board's inputs, the
harness commit's warning); P16/P17 at the script stage — every usable image shown or given a reason
(`unused_images`, printed by `shown 1`), scene 1 the title scene, no presenter layout without character art; the fake
s2v's layout default and string logo. Stub Providers: no s2v process (the real-s2v case runs only with
STUDIO_TEST_S2V, under --full). The init parts (narrator candidates, image folders, project names) are tested in
test_pilot2b_init.py."""

import contextlib
import io
import json
import os
import subprocess
import unittest

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo import credits, look
from stdo.claims import check as ccheck
from stdo.commit import harness
from stdo.state import cli as scli, gates, stagechecks, store
from stdo.state.collect import Providers
from stdo.voice import cli as vcli
from test_fake_s2v import FakeCase

SKILL = helpers.SKILL
ACCENT = "#EC174F"


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def flat(text):
    return " ".join(text.split())


def script(fm="", body=None):
    return "---\ntitle: 공항 단어\nlang: ko\n%s---\n\n%s" % (fm, body if body is not None else (
        "# 공항 단어 {#intro}\n\n안녕하세요.\n\n::title[공항 단어]\n\n# 체크인 {#checkin}\n\n먼저 체크인합니다.\n\n"
        ":::bullets\n- 搭乗手続き\n:::\n"))


def ins_of(layout=None, aspect="16:9", logo=None, voices=("narrator",), characters=(), reasons=None, files=()):
    out = {"name": "youtube", "aspect": aspect}
    if layout is not None:
        out["layout"] = layout
    fl = list(files)
    if logo:
        fl.append({"path": logo[0], "sha256": logo[1], "kind": "logo"})
    return {"outputs": [out], "voices": [{"cast": c} for c in voices],
            "characters": [{"cast": c, "dir": "x", "source": "y"} for c in characters],
            "reasons": reasons or {}, "files": fl}


class BrandRepo(StudioTestCase):
    """A git repository with brand.json and a committed PNG logo; a video folder."""

    def setUp(self):
        super().setUp()
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp)
        os.makedirs(os.path.join(self.repo, "public", "img"))
        self.logo_bytes = helpers_png()
        with open(os.path.join(self.repo, "public", "img", "logo.png"), "wb") as f:
            f.write(self.logo_bytes)
        self.brand(logo="public/img/logo.png")
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "brand")
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        os.makedirs(self.vdir, exist_ok=True)
        self.src = "../../../public/img/logo.png"

    def brand(self, logo="", accent=ACCENT, raw=None):
        p = os.path.join(self.repo, ".claude", "studio", "brand.json")
        with open(p, "w") as f:
            f.write(raw if raw is not None else json.dumps({"name": "Site", "accent_color": accent, "logo": logo}))

    def commit(self):
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "c")


def helpers_png(w=4, h=3):
    from test_m1e import png as p
    return p(w, h)


# ---------------------------------------------------------------- brand_logo

class BrandLogo(BrandRepo):
    def test_ok_for_a_committed_png(self):
        bl = look.brand_logo(self.repo, self.vdir)
        self.assertEqual((bl["status"], bl["script_src"], bl["path"]), ("ok", self.src, "public/img/logo.png"))
        a = look.brand_asset(bl)
        self.assertEqual((a["floor"], a["floor_reason"]), ("public", "brand.json logo (committed in the harness)"))
        self.assertEqual(credits.floor_of(a), "public/brand.json logo (committed in the harness)")

    def test_no_logo_is_none(self):
        self.brand(logo="")
        self.assertIsNone(look.brand_logo(self.repo, self.vdir))

    def test_svg_is_format(self):
        with open(os.path.join(self.repo, "public", "img", "logo.svg"), "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        self.brand(logo="public/img/logo.svg")
        self.commit()
        bl = look.brand_logo(self.repo, self.vdir)
        self.assertEqual(bl["status"], "format")
        self.assertIn("is not PNG or JPEG", bl["reason"])

    def test_uncommitted_brand_or_logo(self):
        self.brand(logo="public/img/logo.png", accent="#112233")  # brand.json changed, not committed
        bl = look.brand_logo(self.repo, self.vdir)
        self.assertEqual(bl["status"], "uncommitted")
        self.assertIn("make a harness commit", bl["reason"])
        self.commit()
        self.assertEqual(look.brand_logo(self.repo, self.vdir)["status"], "ok")
        with open(os.path.join(self.repo, "public", "img", "new.png"), "wb") as f:
            f.write(helpers_png(5, 5))  # an untracked logo
        self.brand(logo="public/img/new.png", accent="#112233")
        helpers.git(self.repo, "add", ".claude/studio/brand.json")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "brand only")
        self.assertEqual(look.brand_logo(self.repo, self.vdir)["status"], "uncommitted")

    def test_outside_missing_invalid(self):
        self.brand(logo="../elsewhere.png")
        self.assertEqual(look.brand_logo(self.repo, self.vdir)["status"], "outside")
        self.brand(logo="public/img/none.png")
        self.assertEqual(look.brand_logo(self.repo, self.vdir)["status"], "missing")
        self.brand(raw="{not json")
        self.assertEqual(look.brand_logo(self.repo, self.vdir)["status"], "invalid")
        self.brand(accent="red")
        self.assertEqual(look.brand_logo(self.repo, self.vdir)["status"], "invalid")


# ---------------------------------------------------------------- the frontmatter readers

class Readers(unittest.TestCase):
    def theme(self, fm):
        return look.theme_of(script(fm))

    def test_theme_forms(self):
        self.assertEqual(self.theme("theme: dark\n"), ("dark", None))
        self.assertEqual(self.theme('theme: { base: light, accent: "#EC174F" }\n')[0],
                         {"base": "light", "accent": "#EC174F"})
        self.assertEqual(self.theme('theme: { "base": light, \'accent\': "#EC174F" }\n')[0],
                         {"base": "light", "accent": "#EC174F"})  # quoted keys
        self.assertEqual(self.theme('theme:\n  base: dark   # the channel\n  # a note\n  accent: "#ec174f"\n')[0],
                         {"base": "dark", "accent": "#ec174f"})  # comments on child lines, comment-only line
        self.assertEqual(self.theme("title2: x\n"), (None, None))

    def test_trailing_comment_is_stripped(self):
        self.assertEqual(self.theme('theme: { base: light, accent: "#EC174F" } # brand\n'),
                         ({"base": "light", "accent": "#EC174F"}, None))

    def test_unquoted_hash_is_reported_before_the_scalar_read(self):
        for fm in ("theme: { base: light, accent: #EC174F }\n", "theme:\n  accent: #EC174F\n", "theme: #EC174F\n"):
            theme, problem = self.theme(fm)
            self.assertIsNone(theme, fm)
            self.assertIn("quote", problem, fm)

    def test_outputs_and_title(self):
        t = script('outputs:\n  youtube: { aspect: "16:9", layout: presenter, maxDuration: 480 }  # presenter | x\n')
        self.assertEqual(look.outputs_of(t)["youtube"]["layout"], "presenter")
        t = script("outputs:\n  youtube:\n    layout: fullscreen\n")
        self.assertEqual(look.outputs_of(t)["youtube"]["layout"], "fullscreen")
        self.assertEqual(look.title_of(script()), "공항 단어")


# ---------------------------------------------------------------- the layout rule

class Layout(unittest.TestCase):
    def test_modes(self):
        no_art = ({"narrator"}, set())
        self.assertIsNone(look.layout_problem(None, *no_art, mode="script"))  # absent before board: fine
        self.assertIn("use fullscreen", look.layout_problem(None, *no_art, mode="board"))  # s2v's presenter
        for lay in ("presenter", "dialogue"):
            for mode in ("script", "board"):
                self.assertIn("shows no one", look.layout_problem(lay, *no_art, mode=mode))
        self.assertIsNone(look.layout_problem("fullscreen", *no_art, mode="board"))
        self.assertIsNone(look.layout_problem("presenter", {"a"}, {"a"}, mode="board"))  # every speaker has art
        self.assertIsNotNone(look.layout_problem("presenter", {"a", "b"}, {"a"}, mode="board"))
        self.assertIsNone(look.layout_problem("presenter", *no_art, mode="board", aspect="9:16"))
        self.assertIsNone(look.layout_problem("shorts", *no_art, mode="board"))

    def test_invalid_art_does_not_count(self):
        ins = ins_of(layout="presenter")
        ins["characters"] = [{"cast": "narrator", "dir": "x"}, {"cast": "guest", "dir": "y", "source": ""}]
        self.assertEqual(look.cast_art(ins, "youtube"), ({"narrator"}, set()))  # no source: unreadable art
        # an unrelated presentation reason (a missing bgm) does not wipe readable art
        ins = ins_of(characters=("narrator",), reasons={"presentation.youtube": ["missing file(s): bgm.mp3"]})
        self.assertEqual(look.cast_art(ins, "youtube"), ({"narrator"}, {"narrator"}))


# ---------------------------------------------------------------- the board's look and --look

class Problems(BrandRepo):
    def ok_text(self, extra=""):
        return script('theme: { base: dark, accent: "%s" }\nlogo: { src: "%s" }\n%s' % (ACCENT, self.src, extra))

    def ok_ins(self, **kw):
        bl = look.brand_logo(self.repo, self.vdir)
        kw.setdefault("logo", (self.src, bl["sha256"]))
        kw.setdefault("layout", "fullscreen")
        return ins_of(**kw)

    def probs(self, text=None, ins=None):
        return look.problems(self.repo, self.vdir, ins or self.ok_ins(), text or self.ok_text(), "youtube")

    def test_pass(self):
        self.assertEqual(self.probs(), [])
        self.assertEqual(self.probs(self.ok_text().replace(ACCENT, ACCENT.lower())), [])  # case-insensitive

    def test_each_problem(self):
        cases = [
            (self.ok_text().replace(', accent: "%s"' % ACCENT, ""), None, "has no accent"),
            (self.ok_text().replace(ACCENT, "#000000"), None, "not the brand's"),
            (self.ok_text().replace('theme: { base: dark, accent: "%s" }' % ACCENT, "theme: dark"), None,
             "theme is dark"),
            (self.ok_text().replace('"%s" }' % ACCENT, "%s }" % ACCENT), None, "quote"),
            (None, self.ok_ins(logo=None), "not the brand logo"),
            (None, self.ok_ins(logo=(self.src, "0" * 64)), "not the brand logo's bytes"),
            (None, self.ok_ins(layout=None), "use fullscreen"),
            (None, self.ok_ins(layout="presenter"), "use fullscreen"),
            (None, self.ok_ins(layout="dialogue"), "use fullscreen"),
        ]
        for text, ins, want in cases:
            p = self.probs(text, ins)
            self.assertTrue(any(want in x for x in p), (want, p))
            self.assertTrue(all("--look" in x for x in p if want in x and "bytes" not in x and "quote" not in x), p)

    def test_kinds_split_on_commas(self):
        bl = look.brand_logo(self.repo, self.vdir)
        ins = self.ok_ins(logo=None, files=[{"path": self.src, "sha256": bl["sha256"], "kind": "image,logo"}])
        self.assertEqual(self.probs(None, ins), [])

    def test_logo_while_brand_has_none(self):
        ins = self.ok_ins()
        self.brand(logo="")
        self.commit()
        p = self.probs(None, ins)
        self.assertTrue(any("brand.json names none" in x for x in p), p)

    def test_uncommitted_brand(self):
        self.brand(logo="public/img/logo.png", accent="#112233")
        p = self.probs(self.ok_text().replace(ACCENT, "#112233"))
        self.assertTrue(any("is not committed — commit it in a harness commit" in x for x in p), p)

    def test_svg_brand_logo(self):
        with open(os.path.join(self.repo, "public", "img", "logo.svg"), "w") as f:
            f.write("<svg/>")
        self.brand(logo="public/img/logo.svg")
        self.commit()
        p = self.probs()
        self.assertTrue(any("is not PNG or JPEG" in x and "brand.json" in x for x in p), p)


class LookCommand(BrandRepo):
    def setUp(self):
        super().setUp()
        store.create(self.vdir, F.state(outputs=("youtube",), platforms={"youtube": ["youtube"]}))
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(script("theme: dark\n"))
        self.ins = ins_of()

        def no_process(*a, **kw):
            raise AssertionError("an s2v process would start")
        self.providers = Providers(inspect=lambda ctx: self.ins, sentences=no_process, source=no_process,
                                   inspect_at=no_process, version=no_process, services=no_process)

    def run_look(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vcli.assets_main(["v1", "--look", "--output", "youtube"] + list(extra), providers=self.providers,
                                    cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def snapshot(self):
        out = {}
        for d, _dirs, files in os.walk(self.vdir):
            for n in files:
                out[os.path.join(d, n)] = read(d, n) if not n.endswith(".png") else None
        return out

    def test_prints_the_lines_and_writes_nothing(self):
        before = self.snapshot()
        self.assertEqual(self.run_look(), 0, self.out + self.err)
        self.assertIn('theme.accent: "%s"' % ACCENT, self.out)
        self.assertIn('logo.src: "%s"' % self.src, self.out)
        self.assertIn("outputs.youtube.layout: fullscreen", self.out)
        self.assertIn('theme: { base: dark, accent: "%s" }' % ACCENT, self.out)  # the script's base kept, hex quoted
        self.assertIn('logo: { src: "%s" }' % self.src, self.out)
        self.assertEqual(self.snapshot(), before)

    def test_presenter_with_art_and_no_line_for_shorts(self):
        self.ins = ins_of(characters=("narrator",))
        self.assertEqual(self.run_look(), 0)
        self.assertIn("outputs.youtube.layout: presenter", self.out)
        self.assertNotIn("dialogue", self.out)
        self.ins = ins_of(aspect="9:16", layout="shorts")
        self.assertEqual(self.run_look(), 0)
        self.assertNotIn("layout", self.out)

    def test_no_logo(self):
        self.brand(logo="")
        self.commit()
        self.assertEqual(self.run_look(), 0)
        self.assertIn("logo: none", self.out)
        self.assertNotIn("logo.src", self.out)

    def test_exit_1_for_svg_uncommitted_or_bad_brand(self):
        self.brand(logo="public/img/logo.png", accent="#112233")
        self.assertEqual(self.run_look(), 1)
        self.assertIn("not committed", self.out)
        self.brand(raw="[]")
        self.assertEqual(self.run_look(), 1)
        self.assertIn("not an object", self.out)

    def test_usage(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vcli.assets_main(["v1", "--look"], providers=self.providers, cwd=self.repo)
        self.assertEqual(code, 2)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = vcli.assets_main(["v1", "--look", "--actors", "--output", "youtube"], providers=self.providers,
                                    cwd=self.repo)
        self.assertEqual(code, 2)


# ---------------------------------------------------------------- credits and board inputs

class BrandCredit(BrandRepo):
    def setUp(self):
        super().setUp()
        store.create(self.vdir, F.state(outputs=("youtube",), platforms={"youtube": ["youtube"]}))
        F.write_assets(self.vdir)

    def draft(self, floor="public/brand.json logo (committed in the harness)"):
        item = {"path": self.src, "license": "own work", "credit_line": "Site", "floor": floor,
                "license_checked": True, "public_ok": True, "redistribute": True, "commercial": True}
        with open(os.path.join(self.vdir, credits.DRAFT), "w") as f:
            json.dump({"schema": 1, "items": [item]}, f)

    def preview(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = scli.main(["credit-preview", "v1", self.src], cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def test_preview_takes_the_brand_logo(self):
        self.draft()
        self.assertEqual(self.preview(), 0, self.err)
        self.assertIn('floor="public/brand.json logo (committed in the harness)"', self.out)
        self.assertIn("label 출처 v1 ", self.out)

    def test_preview_says_why_the_brand_logo_is_not_usable(self):
        self.draft()
        self.brand(logo="public/img/logo.png", accent="#112233")  # uncommitted
        self.assertEqual(self.preview(), 1)
        self.assertIn("brand logo is not committed", self.err)
        self.assertNotIn("not a usable image of work/assets.json", self.err)

    def test_picture_problems(self):
        from stdo import board
        self.draft()
        bl = look.brand_logo(self.repo, self.vdir)
        ins = {"files": [{"path": self.src, "sha256": bl["sha256"], "kind": "logo"}]}
        st = store.read_state(self.vdir)
        p = board.picture_problems(self.repo, self.vdir, st, ins)
        self.assertTrue(any("has no CREDITS entry" in x or "not the one the person approved" in x for x in p), p)
        self.assertFalse(any("not a usable image" in x for x in p), p)
        self.brand(logo="public/img/logo.png", accent="#112233")
        p = board.picture_problems(self.repo, self.vdir, st, ins)
        self.assertTrue(any("brand logo is not committed" in x for x in p), p)
        self.assertFalse(any("not a usable image" in x for x in p), p)

    def test_credits_sha_pins_the_bytes(self):
        bl = look.brand_logo(self.repo, self.vdir)
        e = credits.normalize({"path": self.src, "license": "own", "credit_line": "Site",
                               "floor": "public/brand.json logo (committed in the harness)", "license_checked": True,
                               "public_ok": True, "redistribute": True, "commercial": True},
                              os.path.normpath(os.path.join(self.vdir, self.src)), look.brand_asset(bl))
        self.assertEqual(e["sha256"], bl["sha256"])

    def test_board_inputs_follow_brand_and_logo(self):
        repo, vdir = self.repo, self.vdir

        class Inp(object):
            def __init__(s):
                s.repo, s.vdir = repo, vdir

            def rel(s, p):
                return os.path.relpath(p, repo)
        before = stagechecks.RESOLVERS["brand_json"](Inp())
        self.brand(logo="public/img/logo.png", accent="#112233")
        self.assertNotEqual(stagechecks.RESOLVERS["brand_json"](Inp()), before)
        self.brand(logo="public/img/logo.png")
        self.assertEqual(stagechecks.RESOLVERS["brand_json"](Inp()), before)
        with open(os.path.join(self.repo, "public", "img", "logo.png"), "ab") as f:
            f.write(b"x")
        self.assertNotEqual(stagechecks.RESOLVERS["brand_json"](Inp()), before)
        from stdo.state import schema
        self.assertIn("brand_json", schema.STAGE_CHECKS["board"]["inputs"])

    def test_board_inputs_never_read_a_fifo_or_an_outside_path(self):
        repo, vdir = self.repo, self.vdir

        class Inp(object):
            def __init__(s):
                s.repo, s.vdir = repo, vdir

            def rel(s, p):
                return os.path.relpath(p, repo)
        fifo = os.path.join(self.repo, "public", "img", "pipe.png")
        os.mkfifo(fifo)
        for logo in ("public/img/pipe.png", "../../../../../dev/zero", "/dev/zero"):
            self.brand(logo=logo)
            got = dict(stagechecks.RESOLVERS["brand_json"](Inp()))  # returns at once: nothing is opened
            k = [x for x in got if x.startswith("brand_logo")][0]
            self.assertTrue(got[k].endswith(":None"), (logo, got))
        with open(os.path.join(self.repo, "public", "img", "big.png"), "wb") as f:
            f.truncate(look.MAX_LOGO + 1)
        self.brand(logo="public/img/big.png")
        self.assertEqual(look.brand_logo(self.repo, self.vdir)["status"], "too-large")


class HarnessWarning(BrandRepo):
    def ctx(self):
        class Git(object):
            def __init__(s, repo):
                s.repo = repo

            def show(s, spec):
                r = subprocess.run(["git", "-C", s.repo, "show", spec], capture_output=True)
                return r.stdout if r.returncode == 0 else None

        class Ctx(object):
            top = self.repo
            head = "HEAD"
            git = Git(self.repo)
        return Ctx()

    def test_warns_for_an_uncommitted_logo(self):
        self.assertEqual(harness.brand_logo_warnings(self.ctx()), [])
        with open(os.path.join(self.repo, "public", "img", "new.png"), "wb") as f:
            f.write(helpers_png())
        self.brand(logo="public/img/new.png")
        w = harness.brand_logo_warnings(self.ctx())
        self.assertEqual(len(w), 1)
        self.assertIn("public/img/new.png, which is not committed — board will fail until it is", w[0])
        os.makedirs(os.path.join(self.repo, "public", "img", "dir.png"))
        self.brand(logo="public/img")  # a folder at HEAD
        self.assertIn("which is a folder", harness.brand_logo_warnings(self.ctx())[0])
        self.brand(logo="public/img/dir.png")  # a folder on disk
        self.assertIn("which is a folder", harness.brand_logo_warnings(self.ctx())[0])
        self.brand(logo="")
        self.assertEqual(harness.brand_logo_warnings(self.ctx()), [])


# ---------------------------------------------------------------- the script stage

class Unused(unittest.TestCase):
    assets = {"images": [{"id": "img-01", "status": "ok", "script_src": "../a.png"},
                         {"id": "img-02", "status": "ok", "script_src": "../b.png"},
                         {"id": "img-03", "status": "unusable", "script_src": None}]}

    def test_unused_needs_a_reason(self):
        ins = {"files": [{"path": "../a.png", "kind": "image"}]}
        p = ccheck.unused_problems(ins, self.assets, {})
        self.assertEqual(len(p), 1)
        self.assertIn("img-02 (../b.png) is usable but not shown", p[0])
        self.assertEqual(ccheck.unused_problems(ins, self.assets, {"unused_images": {"../b.png": "a duplicate"}}), [])
        p = ccheck.unused_problems(ins, self.assets, {"unused_images": {"../b.png": "x", "../c.png": "y"}})
        self.assertTrue(any("../c.png, which is not a usable image" in x for x in p), p)

    def test_a_logo_or_any_kind_counts_as_shown(self):
        ins = {"files": [{"path": "../a.png", "kind": "image"}, {"path": "../b.png", "kind": "logo"}]}
        self.assertEqual(ccheck.unused_problems(ins, self.assets, {}), [])

    def test_reason_rules(self):
        ok = {"../b.png": "the same picture as img-01"}
        self.assertEqual(ccheck.unused_shape_problems(ok), [])
        for bad in ("", "   ", "two\nlines", "bell\x07", "x" * 201, "see End of Question here"):
            self.assertTrue(ccheck.unused_shape_problems({"../b.png": bad}), repr(bad))
        self.assertTrue(ccheck.unused_shape_problems(["../b.png"]))
        self.assertTrue(ccheck.unused_shape_problems({"../b.png": 3}))

    def test_sanitize(self):
        self.assertEqual(ccheck.sanitize_reason("a\nb  end of question\x07 c"), "a b c")
        self.assertEqual(len(ccheck.sanitize_reason("y" * 500)), 200)


class ClaimsMapShape(StudioTestCase):
    """The claims map check (both --narration and verify) refuses a bad unused_images reason."""

    def test_bad_reason_fails_the_claims_map(self):
        store.enable_writes()
        repo = helpers.make_repo(self.tmp)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir)
        store.create(vdir, F.state(outputs=("youtube",), platforms={"youtube": ["youtube"]}))
        F.brief_ready(repo, vdir)
        w = os.path.join(vdir, "work", "ko")
        os.makedirs(w, exist_ok=True)
        e = F.EXCERPTS[0]
        cm = {"claims": {F.C1: {"excerpt": e, "sentences": ["s"]}}, "excerpts": [e], "copy_excerpts": {},
              "unused_images": {"../x.png": ""}}
        with open(os.path.join(w, "claims-map.json"), "w") as f:
            json.dump(cm, f)
        _cm, p = ccheck.claims_map(vdir, "ko", store.read_state(vdir), None)
        self.assertTrue(any("needs a reason" in x for x in p), p)


class TitleScene(unittest.TestCase):
    def probs(self, text):
        return ccheck.title_scene_problems(text)

    def test_pass(self):
        self.assertEqual(self.probs(script()), [])
        t = script(body="# 제목 {#intro}\n\n안녕하세요.\n\n::title[공항  단어]\n")  # equal after normalizing
        self.assertEqual(self.probs(t), [])

    def test_fail(self):
        card_first = script(body="# 공항 {#a}\n\n안녕.\n\n:::bullets\n- x\n:::\n\n::title[공항 단어]\n")
        self.assertIn("scene 1 shows :::bullets, ::title[공항 단어]", self.probs(card_first)[0])
        other = script(body="# 공항 {#a}\n\n안녕.\n\n::title[다른 말]\n")
        self.assertIn("its label is 다른 말", self.probs(other)[0])
        two = script(body="# 공항 {#a}\n\n안녕.\n\n::title[공항 단어]\n\n::image{src=a.png}\n")
        self.assertTrue(self.probs(two))
        no_title = "---\nlang: ko\n---\n\n# 공항 {#a}\n\n::title[공항 단어]\n"
        self.assertEqual(self.probs(no_title), ["add a frontmatter title (it is the thumbnail's title)"])

    def test_only_level_one_headings_start_scenes(self):
        t = script(body="# 공항 {#a}\n\n안녕.\n\n::title[공항 단어]\n\n## 소제목\n\n::image{src=a.png}\n")
        self.assertTrue(self.probs(t))  # the ## line does not start a scene: scene 1 has two visuals
        t = script(body="# 공항 {#a}\n\n안녕.\n\n::title[공항 단어]\n\n# 둘 {#b}\n\n::image{src=a.png}\n")
        self.assertEqual(self.probs(t), [])

    def test_content_before_the_first_heading_fails(self):
        # s2v puts it into an untitled first scene (parse.ts implicit-scene)
        for pre in ("::image{src=a.png}\n\n", "안녕하세요.\n\n", "```\ncode\n```\n\n"):
            t = script(body=pre + "# 공항 {#a}\n\n안녕.\n\n::title[공항 단어]\n")
            p = self.probs(t)
            self.assertEqual(len(p), 1, pre)
            self.assertIn("move it under a `# ` heading", p[0])
        t = script(body="\n<!-- a note -->\n\n# 공항 {#a}\n\n안녕.\n\n::title[공항 단어]\n")
        self.assertEqual(self.probs(t), [])  # blank lines and a one-line comment are not content

    def test_a_title_with_brackets(self):
        t = script(body="# 속보 {#a}\n\n안녕.\n\n::title[[속보] 공항 단어]\n").replace(
            "title: 공항 단어", "title: \"[속보] 공항 단어\"")
        self.assertEqual(self.probs(t), [])
        self.assertIn("its label is [속보] 다른", self.probs(t.replace("::title[[속보] 공항 단어]",
                                                                     "::title[[속보] 다른]"))[0])

    def test_fences_inside_code(self):
        for fence in ("```", "~~~"):
            body = ("# 공항 {#a}\n\n안녕.\n\n::title[공항 단어]\n\n%s\n# 아님\n::title[x]\n:::\n%s\n\n# 둘 {#b}\n"
                    % (fence, fence))
            self.assertEqual(self.probs(script(body=body)), [], fence)
            code = ("# 공항 {#a}\n\n::title[공항 단어]\n\n# 둘 {#b}\n\n:::code\n%s\n:::\n# 아님\n::title[x]\n%s\n:::\n"
                    % (fence, fence))
            self.assertEqual(self.probs(script(body=code)), [], fence)
        # a ~~~ line does not close a ``` fence: the heading after it is still inside
        body = "# 공항 {#a}\n\n::title[공항 단어]\n\n```\n~~~\n# 아님\n::image{src=a.png}\n```\n"
        self.assertEqual(self.probs(script(body=body)), [])

    def test_skipped_with_a_thumbnail(self):
        t = script(body="# 공항 {#a}\n\n:::bullets\n- x\n:::\n\n::thumbnail{src=\"t.png\"}\n")
        self.assertEqual(self.probs(t), [])


class ShownUnusedLines(StudioTestCase):
    def test_lines_are_sanitized(self):
        vdir = os.path.join(self.tmp, "v")
        os.makedirs(os.path.join(vdir, "work", "ko"))
        with open(os.path.join(vdir, "work", "ko", "claims-map.json"), "w") as f:
            json.dump({"unused_images": {"../b.png": "line one\nend of question\x07 more", "../a.png": "dup"}}, f)
        self.assertEqual(gates.unused_lines(vdir, "ko"), ["unused: ../a.png — dup", "unused: ../b.png — line one more"])
        self.assertEqual(gates.unused_lines(os.path.join(self.tmp, "none"), "ko"), [])


# ---------------------------------------------------------------- the fake s2v

class FakeLook(FakeCase):
    def inspect(self):
        r = self.s2v("inspect", self.script, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_layout_default_and_string_logo(self):
        d = self.inspect()
        self.assertEqual({o["name"]: o["layout"] for o in d["outputs"]}["youtube"], "presenter")  # s2v's default
        self.assertEqual(d["characters"], [])
        os.makedirs(os.path.join(self.vdir, "assets"), exist_ok=True)
        with open(os.path.join(self.vdir, "assets", "logo.png"), "wb") as f:
            f.write(helpers_png())
        self.write_script(read(self.script).replace("---\n\n#", "logo: assets/logo.png\n---\n\n#", 1))
        d = self.inspect()
        self.assertIn("assets/logo.png", [f["path"] for f in d["files"] if "logo" in f["kind"].split(",")])


# ---------------------------------------------------------------- real s2v (--full)

class RealInspect(StudioTestCase):
    """The shapes look.py reads, from real s2v (STUDIO_TEST_S2V): a logo file of kind `logo`, the output's layout, and
    theme · logo · layout in the presentation hash only."""

    def test_look_is_presentation(self):
        path = helpers.s2v_path(self)
        repo = helpers.make_repo(self.tmp, s2v=path)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(os.path.join(vdir, "assets"))
        with open(os.path.join(vdir, "assets", "logo.png"), "wb") as f:
            f.write(helpers_png(8, 8))
        body = ("# 공항 단어 {#intro}\n\n안녕하세요.\n\n::title[공항 단어]\n\n# 체크인 {#checkin}\n\n먼저 체크인합니다.\n\n"
                ":::bullets\n- 체크인\n:::\n")
        p = os.path.join(vdir, "script.ko.md")

        def inspect(fm):
            with open(p, "w") as f:
                f.write("---\ntitle: 공항 단어\nlang: ko\noutputs:\n  youtube: { aspect: \"16:9\"%s }\n%s---\n\n%s"
                        % (fm[0], fm[1], body))
            r = helpers.run_s2v(self, ["inspect", p, "--json"], cwd=repo)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        plain = inspect(("", ""))
        styled = inspect((", layout: fullscreen", 'theme: { base: dark, accent: "#EC174F" }\n'
                          'logo: { src: "assets/logo.png" }\n'))
        self.assertEqual(plain["hashes"]["content"], styled["hashes"]["content"])
        self.assertNotEqual(plain["hashes"]["presentation_by_output"], styled["hashes"]["presentation_by_output"])
        self.assertEqual(styled["outputs"][0]["layout"], "fullscreen")
        self.assertEqual(plain["outputs"][0]["layout"], "presenter")
        self.assertIn("assets/logo.png", [f["path"] for f in styled["files"] if "logo" in f["kind"].split(",")])
        r = helpers.run_s2v(self, ["lint", p], cwd=repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("no-visual", r.stdout + r.stderr)


# ---------------------------------------------------------------- documents and versions

class Text(unittest.TestCase):
    def test_board_documents(self):
        g = flat(read(SKILL, "templates", "guides", "board.md"))
        d = flat(read(SKILL, "templates", "agents", "std-visual-director.md"))
        b = flat(read(SKILL, "commands", "board.md"))
        for t in (g, d, b):
            self.assertIn("--look --output", t)
        for key in ("`theme`", "`logo`", "`transition`"):
            self.assertIn(key, g)
            self.assertIn(key, d)
        self.assertIn("## Applied", d)
        self.assertIn("public/brand.json logo (committed in the harness)", d)

    def test_writer_and_script_guide(self):
        w = flat(read(SKILL, "templates", "agents", "std-writer.md"))
        s = flat(read(SKILL, "templates", "guides", "script.md"))
        self.assertIn("Never write `layout` yourself", w)
        self.assertIn("keep what board wrote", w)
        for t in (w, s):
            self.assertIn("Scene 1 is the title scene", t)
            self.assertIn("unused_images", t)
        self.assertIn("10 seconds", s)
        v = flat(read(SKILL, "commands", "verify.md"))
        self.assertIn("unused: <script_src> — <reason>", v)

    def test_no_presenter_layout_in_shipped_docs(self):
        for d, _dirs, files in os.walk(SKILL):
            for n in files:
                if n.endswith(".md"):
                    self.assertNotIn("layout: presenter", read(d, n), os.path.join(d, n))

    def test_versions(self):
        from stdo import SCRIPTS_VERSION
        self.assertEqual(SCRIPTS_VERSION, "26")
        with open(os.path.join(helpers.PLUGIN, ".claude-plugin", "plugin.json")) as f:
            self.assertEqual(json.load(f)["version"], "0.1.1")
        for n, notes in (("README.md", "## Version notes"), ("README.ko.md", "## 버전 노트"),
                         ("README.ja.md", "## バージョンノート")):
            text = read(helpers.PLUGIN, n)
            self.assertIn(notes, text, n)
            self.assertIn("0.1.1", text.split(notes)[1], n)
        self.assertIn("0.1.1", read(helpers.PLUGIN, "tests", "README.md"))


if __name__ == "__main__":
    unittest.main()
