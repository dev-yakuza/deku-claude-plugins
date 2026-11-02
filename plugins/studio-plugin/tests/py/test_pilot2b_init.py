"""Pilot 2 init fixes (0.0.26, fix-0026-plan §3–§6): N3 — `init analyze` offers each language's narrator candidates
(native first, then two others marked as a ② risk) and init always asks; N5 — `project_names` from the site's title,
the web manifest, package.json and the origin remote's repository name (never its URL), else the folder name; N4 —
`image_folders` from the images the writing shows, with its own budget; init refuses a brand logo that the video
cannot show or that is not committed; init.md asks in the §6 call sequence."""

import json
import os
import re

import helpers
from helpers import StudioTestCase
from test_pilot1b import AnalyzeCase, png

COMMANDS = os.path.join(helpers.SKILL, "commands")
TOKEN = "ghp_SECRETTOKEN0123456789"


# ---------------------------------------------------------------- N3: narrator candidates

class NarratorCandidates(StudioTestCase):
    def test_native_first_then_two_others(self):
        from stdo import narrator
        from stdo.setup import analyze
        c = analyze.narrator_candidates()
        self.assertEqual(sorted(c), sorted(narrator.LANGS))
        self.assertEqual(c["ko"], [{"engine": "qwen:Sohee", "language": "ko", "native": True, "suggested": True},
                                   {"engine": "qwen:Aiden", "language": "en", "native": False, "suggested": False},
                                   {"engine": "qwen:Ryan", "language": "en", "native": False, "suggested": False}])
        self.assertEqual([d["engine"] for d in c["ja"]], ["qwen:Ono_Anna", "qwen:Aiden", "qwen:Ryan"])
        self.assertEqual([(d["engine"], d["native"], d["suggested"]) for d in c["en"]],
                         [("qwen:Ryan", True, True), ("qwen:Aiden", True, False), ("qwen:Ono_Anna", False, False),
                          ("qwen:Sohee", False, False)])
        for lang, items in c.items():
            self.assertLessEqual(len(items), 4, lang)  # one AskUserQuestion question
            self.assertEqual(sum(d["suggested"] for d in items), 1, lang)
            self.assertEqual(items[0]["engine"], narrator.SUGGESTED[lang])
            self.assertEqual(len([d for d in items if not d["native"]]), 2, lang)
            for d in items:
                self.assertTrue(narrator.engine_ok(d["engine"]), d)
                self.assertEqual(d["native"], d["language"] == lang)


# ---------------------------------------------------------------- N5: project names

class ProjectNames(AnalyzeCase):
    def names(self):
        return self.analyze()["project_names"]

    def fresh(self, files):
        import shutil
        shutil.rmtree(self.top)
        os.makedirs(self.top)
        helpers.git(self.top, "init", "-q")
        self.put(files)

    def test_each_source(self):
        cases = (
            ({"hugo.toml": "baseURL = 'https://a.sample.dev/'\ntitle = '단어 노트'\n"}, "단어 노트", "hugo.toml title"),
            ({"hugo.yaml": "title: \"Word Notes\"  # the site\n"}, "Word Notes", "hugo.yaml title"),
            ({"_config.yml": "title: Jekyll Words\nurl: https://j.sample.dev\n"}, "Jekyll Words", "_config.yml title"),
            ({"docusaurus.config.js": "module.exports = { title: 'Docu Words', url: 'https://d.sample.dev' }\n"},
             "Docu Words", "docusaurus.config.js title"),
            ({"gatsby-config.js": "module.exports = { siteMetadata: { siteUrl: `x`, title: `Gatsby Words` } }\n"},
             "Gatsby Words", "gatsby-config.js siteMetadata.title"),
            ({"mkdocs.yml": "site_name: MkWords\n"}, "MkWords", "mkdocs.yml site_name"),
            ({"src/consts.ts": "export const SITE_TITLE = 'Astro Words';\n"}, "Astro Words", "src/consts.ts SITE_TITLE"),
            ({"src/config.js": "export default { SITE_NAME: \"Config Words\" }\n"}, "Config Words",
             "src/config.js SITE_TITLE"),
            ({"astro.config.mjs": "integrations: [starlight({ title: 'Star Words' })]\n"}, "Star Words",
             "astro.config.mjs starlight title"),
            ({"astro.config.mjs": "export default {}\n", "public/index.html": "<title>\n  Web &amp; Words\n</title>"},
             "Web & Words", "public/index.html <title>"),
            ({"astro.config.mjs": "export default {}\n", "src/pages/index.astro": "---\n---\n<title>Home Words</title>"},
             "Home Words", "src/pages/index.astro <title>"),
            ({"public/site.webmanifest": json.dumps({"short_name": "MW"})}, "MW", "public/site.webmanifest short_name"),
            ({"package.json": json.dumps({"name": "@me/word-site"})}, "word-site", "package.json name"),
        )
        for files, name, src in cases:
            self.fresh(files)
            self.assertEqual(self.names()[0], {"name": name, "from": src}, files)

    def test_order_dedupe_and_cap(self):
        self.put({"astro.config.mjs": "export default {}\n", "src/consts.ts": "export const SITE_TITLE = 'Words';\n",
                  "public/manifest.json": json.dumps({"name": "WORDS", "short_name": "W app"}),
                  "package.json": json.dumps({"name": "words-site"})})
        helpers.git(self.top, "remote", "add", "origin", "git@code.sample.dev:me/words-repo.git")
        self.assertEqual(self.names(), [{"name": "Words", "from": "src/consts.ts SITE_TITLE"},
                                        {"name": "W app", "from": "public/manifest.json short_name"},
                                        {"name": "words-site", "from": "package.json name"}])  # WORDS: a duplicate

    def test_remote_name_only(self):
        self.put({"a.txt": "x"})
        for url, name in (("https://someone:%s@code.sample.dev/me/word-notes.git" % TOKEN, "word-notes"),
                          ("ssh://git@code.sample.dev:22/me/notes2.git/", "notes2"),
                          ("git@code.sample.dev:me/ssh-notes.git", "ssh-notes"),
                          ("https://code.sample.dev/me/q-notes?token=%s" % TOKEN, "q-notes")):
            helpers.git(self.top, "remote", "remove", "origin", check=False)
            helpers.git(self.top, "remote", "add", "origin", url)
            a = self.analyze()
            self.assertEqual(a["project_names"], [{"name": name, "from": "git remote origin"}], url)
            dump = json.dumps(a, ensure_ascii=False)
            self.assertNotIn(TOKEN, dump)
            self.assertNotIn("code.sample.dev", dump)
            self.assertNotIn("someone", dump)

    def test_placeholders_length_and_folder_fallback(self):
        self.put({"package.json": json.dumps({"name": "my-app"}), "_config.yml": "title: Blog\n",
                  "public/site.webmanifest": json.dumps({"name": "x" * 61, "short_name": "{title}"}),
                  "astro.config.mjs": "export default {}\n", "public/index.html": "<title>Website</title>"})
        helpers.git(self.top, "remote", "add", "origin", "https://code.sample.dev/me/site.git")
        self.assertEqual(self.names(), [{"name": "site", "from": "folder name"}])  # the folder name is not filtered
        self.put({"public/site.webmanifest": json.dumps({"name": "y" * 60})})
        self.assertEqual(self.names(), [{"name": "y" * 60, "from": "public/site.webmanifest name"}])

    def test_untracked_never_read(self):
        self.put({"a.txt": "x"})
        self.put({"package.json": json.dumps({"name": "untracked-name"})}, commit=False)
        self.assertEqual(self.names(), [{"name": "site", "from": "folder name"}])


# ---------------------------------------------------------------- N4: image folders

POST = """---
title: 공항
heroImage: /blog-images/hero.png
---
![로비](/blog-images/a.png)

![로컬](./b.png)

![원격](https://cdn.sample.dev/c.png) ![없음](/blog-images/missing.png) ![밖](../../../../outside.png)
<img src="/blog-images/sub/d.png" alt="d">
"""


class ImageFolders(AnalyzeCase):
    def site(self, **extra):
        files = {"astro.config.mjs": "export default {}\n", "src/content/blog/post.md": POST,
                 "src/content/blog/b.png": png(4, 3), "public/blog-images/a.png": png(4, 3),
                 "public/blog-images/hero.png": png(4, 3), "public/blog-images/sub/d.png": png(4, 3)}
        files.update(extra)
        self.put(files)

    def test_both_folders_with_counts(self):
        self.site()
        with open(os.path.join(self.tmp, "outside.png"), "wb") as f:
            f.write(png(1, 1))
        a = self.analyze()
        self.assertEqual(a["image_folders"], [
            {"glob": "public/blog-images/**", "images": 3, "posts": 1, "writing": ["src/content/blog/"],
             "example": "public/blog-images/a.png", "via_web_root": True},
            {"glob": "src/content/blog/**", "images": 1, "posts": 1, "writing": ["src/content/blog/"],
             "example": "src/content/blog/b.png", "via_web_root": False}])
        self.assertEqual((a["partial"], a["partial_reason"]), (False, []))
        dump = json.dumps(a["image_folders"])
        for absent in ("cdn.sample.dev", "missing.png", "outside.png"):
            self.assertNotIn(absent, dump)

    def test_untracked_image_not_listed(self):
        self.site()
        self.put({"public/other/x.png": png(1, 1), "src/content/blog/p2.md": "![x](/other/x.png)\n"}, commit=False)
        helpers.git(self.top, "add", "src/content/blog/p2.md")
        helpers.git(self.top, "commit", "-q", "--no-verify", "-m", "p2")
        self.assertNotIn("public/other/**", [d["glob"] for d in self.analyze()["image_folders"]])

    def test_no_web_root_wide_glob(self):
        self.site(**{"public/top.png": png(2, 2), "src/content/blog/p2.md": "![t](/top.png)\n"})
        globs = [d["glob"] for d in self.analyze()["image_folders"]]
        self.assertNotIn("public/**", globs)  # a file right in the web root: never the whole root
        self.assertEqual(globs, ["public/blog-images/**", "src/content/blog/**"])

    def test_site_path_and_relative_mixed(self):
        self.site(**{"src/content/blog/p2.md": "![a](../../../public/blog-images/a.png)\n"})
        f = {d["glob"]: d for d in self.analyze()["image_folders"]}
        self.assertFalse(f["public/blog-images/**"]["via_web_root"])  # reached also without a site path
        self.assertEqual(f["public/blog-images/**"]["posts"], 2)

    def test_no_web_root_no_site_paths(self):
        self.put({"src/content/blog/post.md": POST, "src/content/blog/b.png": png(4, 3),
                  "public/blog-images/a.png": png(4, 3)})  # no static-site settings: no web root
        a = self.analyze()
        self.assertEqual(a["web_roots"], {})
        self.assertEqual([d["glob"] for d in a["image_folders"]], ["src/content/blog/**"])

    def test_sub_budget(self):
        from stdo.setup import drafts
        self.site(**{"src/content/blog/p%d.md" % i: "![x](/blog-images/a.png)\n" for i in range(3)})
        saved = drafts.IMG_BUDGET_FILES
        drafts.IMG_BUDGET_FILES = 2
        try:
            a = self.analyze()
        finally:
            drafts.IMG_BUDGET_FILES = saved
        self.assertTrue(a["partial"])
        self.assertTrue(a["partial_reason"] and a["partial_reason"][-1].startswith("image_folders:"), a)
        self.assertIn("400", drafts.image_folders.__doc__)

    def test_global_budget_used_up(self):
        from stdo.setup import analyze
        self.site()
        saved = analyze.BUDGET_FILES
        analyze.BUDGET_FILES = 0
        try:
            a = self.analyze()
        finally:
            analyze.BUDGET_FILES = saved
        self.assertTrue(a["partial"])
        self.assertEqual(a["image_folders"], [])
        self.assertTrue([r for r in a["partial_reason"] if r.startswith("image_folders:") and "global" in r], a)

    def test_big_post_skipped(self):
        self.site(**{"src/content/blog/big.md": "![x](/blog-images/a.png)\n" + "가" * (200 * 1024)})
        a = self.analyze()
        self.assertTrue(a["partial"])
        self.assertIn("image_folders: src/content/blog/big.md is over 512 KB (not read)", a["partial_reason"])
        self.assertEqual(a["image_folders"][0]["posts"], 1)  # post.md still counted

    def test_read_through_walk_after_project_names(self):
        from stdo.setup import analyze
        self.site(**{"package.json": json.dumps({"name": "words"})})
        read = []
        orig = analyze.Walk.read

        def spy(walk, rel, *a, **kw):
            read.append(rel)
            return orig(walk, rel, *a, **kw)
        analyze.Walk.read = spy
        try:
            self.analyze()
        finally:
            analyze.Walk.read = orig
        self.assertIn("src/content/blog/post.md", read)
        self.assertLess(read.index("package.json"), read.index("src/content/blog/post.md"))


# ---------------------------------------------------------------- initcmd: the brand logo

class InitLogo(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.top = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.top, "public"))
        helpers.git(self.top, "init", "-q")

    def write(self, rel, data):
        with open(os.path.join(self.top, rel), "wb") as f:
            f.write(data)

    def commit(self):
        helpers.git(self.top, "add", "-A")
        helpers.git(self.top, "commit", "-q", "--no-verify", "-m", "x")

    def normalize(self, logo):
        from stdo.setup import initcmd
        return initcmd.normalize(self.top, {"language": "ko", "project_name": "단어", "brand": {"logo": logo},
                                            "s2v_path": os.path.join(self.tmp, "s2v")})

    def refused(self, logo, text):
        from stdo.setup import initcmd
        with self.assertRaises(initcmd.SetupError) as e:
            self.normalize(logo)
        self.assertEqual(e.exception.code, 2)
        self.assertIn(text, str(e.exception))
        return str(e.exception)

    def test_committed_png_and_jpeg_pass(self):
        from test_pilot1b import JPEG
        self.write("public/logo.png", png(8, 8))
        self.write("public/logo.jpg", JPEG)
        self.commit()
        self.assertEqual(self.normalize("public/logo.png")["brand"]["logo"], "public/logo.png")
        self.assertEqual(self.normalize("public/logo.jpg")["brand"]["logo"], "public/logo.jpg")

    def test_no_commit_untracked_or_changed(self):
        msg = "commit the logo first, or choose 로고 없음 now"
        self.write("public/logo.png", png(8, 8))
        self.assertIn("no commit yet", self.refused("public/logo.png", msg))
        self.write("a.txt", b"x")
        helpers.git(self.top, "add", "a.txt")
        helpers.git(self.top, "commit", "-q", "--no-verify", "-m", "x")
        self.assertIn("untracked", self.refused("public/logo.png", msg))
        self.commit()
        self.normalize("public/logo.png")
        self.write("public/logo.png", png(9, 9))
        self.refused("public/logo.png", msg)
        helpers.git(self.top, "add", "-A")  # staged, not committed
        self.refused("public/logo.png", msg)

    def test_not_png_or_jpeg(self):
        self.write("public/logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        self.write("public/fake.png", b"<svg/>")
        self.write("public/logo.webp", b"RIFF\0\0\0\0WEBP")
        self.commit()
        for rel in ("public/logo.svg", "public/fake.png", "public/logo.webp"):
            self.refused(rel, "is not a PNG or JPEG image the video can show")

    def test_link_refused(self):
        self.write("public/real.png", png(8, 8))
        os.symlink("real.png", os.path.join(self.top, "public", "logo.png"))
        self.commit()
        self.refused("public/logo.png", "symbolic link")


# ---------------------------------------------------------------- init.md: the §6 call sequence

class InitSequence(StudioTestCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(COMMANDS, "init.md"), encoding="utf-8") as f:
            self.raw = f.read()
        self.text = " ".join(self.raw.split())

    def section(self, start, end):
        a = self.text.index(start)
        return self.text[a:self.text.index(end, a)]

    def test_calls_in_order(self):
        marks = ["**Call 1**", "**Purpose message**", "**Call 2**", "**Call 3**", "**Each question**"]
        pos = [self.text.index(m) for m in marks]
        self.assertEqual(pos, sorted(pos))
        c1 = self.section("**Call 1**", "**Purpose message**")
        c2 = self.section("**Call 2**", "**Call 3**")
        c3 = self.section("**Call 3**", "**Each question**")
        for s in ("language", "project name (`project_names`)", "which writing is public", "`web_roots`"):
            self.assertIn(s, c1)
        for s in ("`narrator_candidates`", "speaking style", "`image_folders`", "accent colour"):
            self.assertIn(s, c2)
        for s in ("logo", "`public_domains`", "`ask_husky`", "notices"):
            self.assertIn(s, c3)
        self.assertNotIn("accent", c1)
        self.assertNotIn("logo", c2)
        self.assertIn("plain message", self.section("**Purpose message**", "**Call 2**"))

    def test_rules(self):
        for s in ("at most 4 questions per call and 2–4 options per question",
                  "The free-input line is on the language question only",
                  "may carry an accent and fail the ② pronunciation check (CER ≤ 0.15)",
                  "Always asked, even when the language has one native speaker",
                  "at most 3 folders, the most Markdown files first", "`공개 글 없음`",
                  "`via_web_root: true`", "At most 3", "plus `없음`",
                  "Never suggest removing a glob the analysis lists",
                  "only `logos` entries with `video: true`", "when at least one `logos` entry has `video: true`",
                  "asked even with a single candidate (that candidate and `로고 없음`)",
                  "commit the logo first, or choose 로고 없음 now", "ask the logo question again",
                  "the logo candidates plus `로고 없음`"):
            self.assertIn(s, self.text)
        for s in ("it is fixed", "do not ask for the speaker", "one built-in speaker",
                  "when more than one `logos` entry has `video: true`"):
            self.assertNotIn(s, self.text)
        self.assertEqual(len(re.findall("목록에 없으면 직접 입력해 주세요", self.text)), 1)

    def test_logo_message_matches_initcmd(self):
        from stdo.setup import initcmd
        self.assertIn(initcmd.LOGO_UNCOMMITTED, self.text)
