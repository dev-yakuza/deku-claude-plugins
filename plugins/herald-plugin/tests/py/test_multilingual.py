"""Multilingual support (design/herald/01-multilingual.md): config, bundle hashes, ledger
files and integrity causes."""

import json
import os
import subprocess
import sys
import unittest

from helpers import CONFIG, SCRIPTS, sh
from test_core import CRIT_PASS, VER_PASS, Flow

from hrdlib import integrity, store
from hrdlib.config import Config
from hrdlib.hashing import bundle_hash, lang_hash, worktree_hash

TRANSLATIONS = {
    "source": "en",
    "targets": [
        {"lang": "ko", "body_pattern": "{content}/ko/{slug}.md", "url_pattern": "/ko/blog/{slug}/"},
        {"lang": "ja", "body_pattern": "src/content/ja/{slug}.md", "url_pattern": "/ja/blog/{slug}/"},
    ],
}


def translated_config(**over):
    cfg = json.loads(json.dumps(CONFIG))
    cfg["translations"] = json.loads(json.dumps(TRANSLATIONS))
    cfg["roles"] = {"conditional": ["translator"]}
    cfg.update(over)
    return cfg


class MultiCase(Flow):
    def use_config(self, data, commit=True):
        self.write(".claude/herald/config.json", json.dumps(data))
        if commit:
            self.commit("config")
            sh(self.root, "git", "push", "-q", "origin", "main")
        self.cfg = Config.load(self.root)

    def translation(self, slug, lang, text=None):
        self.write(self.cfg.body_path(slug, lang), text or "---\ntitle: %s %s\nslug: %s\n---\nTranslated.\n" % (lang, slug, slug))


class ConfigTests(MultiCase):
    def test_no_translations_is_080(self):
        self.assertIsNone(self.cfg.translations())
        self.assertEqual(self.cfg.validate(), ([], []))
        self.assertEqual(self.cfg.bundle_paths("p"), [self.cfg.body_path("p"), self.cfg.image_dir("p")])
        self.assertEqual(self.cfg.source_lang(), "en")

    def test_paths_urls_roles(self):
        self.use_config(translated_config(), commit=False)
        self.assertEqual(self.cfg.validate()[0], [])
        self.assertEqual(self.cfg.body_path("p", "ko"), "src/content/blog/ko/p.md")
        self.assertEqual(self.cfg.body_path("p", "en"), "src/content/blog/p.md")
        self.assertEqual(self.cfg.article_url("p", "ja"), "https://example.test/ja/blog/p/")
        self.assertEqual(self.cfg.path_role("p", "src/content/ja/p.md"), "ja")
        self.assertEqual(self.cfg.path_role("p", "public/blog-images/p/01.png"), "img")
        self.assertEqual(self.cfg.explains("src/content/blog/ko/other-post.md"), "ko")
        self.assertIsNone(self.cfg.explains("src/content/fr/p.md"))
        with self.assertRaises(Exception):
            self.cfg.body_path("p", "fr")

    def errors(self, mutate):
        data = translated_config()
        mutate(data)
        self.use_config(data, commit=False)
        return self.cfg.validate()[0]

    def test_validation_errors(self):
        def overlap(d):
            d["translations"]["targets"][0]["body_pattern"] = "{content}/{slug}-ko.md"
        self.assertTrue(any("same path" in e for e in self.errors(overlap)))

        def url_overlap(d):
            d["translations"]["targets"][1]["url_pattern"] = "/blog/{slug}/"
        self.assertTrue(any("url_pattern" in e for e in self.errors(url_overlap)))

        def no_role(d):
            d["roles"] = {"conditional": []}
        self.assertTrue(any("translator" in e for e in self.errors(no_role)))

        def two_slugs(d):
            d["translations"]["targets"][0]["body_pattern"] = "{content}/{slug}/ko/{slug}.md"
        self.assertTrue(any("exactly once" in e for e in self.errors(two_slugs)))

        def in_images(d):
            d["translations"]["targets"][0]["body_pattern"] = "public/blog-images/{slug}/index.ko.md"
        self.assertTrue(any("image directory" in e for e in self.errors(in_images)))

        def dup(d):
            d["translations"]["targets"][1]["lang"] = "ko"
        self.assertTrue(any("repeated" in e for e in self.errors(dup)))

    def test_build_inputs_warning_not_error(self):
        data = translated_config()
        data["paths"]["build_inputs"] = ["src/content/blog", "public"]
        self.use_config(data, commit=False)
        errors, warnings = self.cfg.validate()
        self.assertEqual(errors, [])
        self.assertTrue(any("ja" in w for w in warnings))

    def test_invalid_config_refuses_commands_but_not_status(self):
        data = translated_config()
        data["roles"] = {"conditional": []}
        self.use_config(data, commit=False)
        _, p = self.hrd("hash", "--slug", "old-post", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("translations is invalid", p.stderr)
        self.hrd("status")


class HashTests(MultiCase):
    def test_bundle_covers_translations_only_when_present(self):
        self.use_config(translated_config())
        self.article("p1")
        src = worktree_hash(self.root, self.cfg, "p1")
        self.assertEqual(bundle_hash(self.root, self.cfg, "p1"), src)
        self.translation("p1", "ko")
        self.assertEqual(worktree_hash(self.root, self.cfg, "p1"), src)
        self.assertNotEqual(bundle_hash(self.root, self.cfg, "p1"), src)
        self.assertEqual(lang_hash(self.root, self.cfg, "p1", "en"), src)
        self.assertIsNotNone(lang_hash(self.root, self.cfg, "p1", "ko"))
        self.assertIsNone(lang_hash(self.root, self.cfg, "p1", "ja"))
        sha = self.commit("p1")
        self.assertEqual(bundle_hash(self.root, self.cfg, "p1", rev=sha), bundle_hash(self.root, self.cfg, "p1"))

    def test_hash_cli_scopes(self):
        self.use_config(translated_config())
        self.article("p1")
        self.translation("p1", "ja")
        b = self.hrd("hash", "--slug", "p1")[0]["hash"]
        s = self.hrd("hash", "--slug", "p1", "--source")[0]["hash"]
        j = self.hrd("hash", "--slug", "p1", "--lang", "ja")[0]["hash"]
        self.assertEqual(b, bundle_hash(self.root, self.cfg, "p1"))
        self.assertEqual(s, worktree_hash(self.root, self.cfg, "p1"))
        self.assertNotIn(j, (b, s))


TR_DOC = """---
title: {lang} title
description: d
slug: {slug}
date: 2026-10-10
---
{sentence}
"""


class TranslationFlow(MultiCase):
    """brief → … → critique → translation → verify with translations configured."""

    def to_critique(self, tid="t0001", slug="new-post", languages=None):
        self.use_config(translated_config())
        topic = {"id": tid, "title": "T", "state": "queued", "history": [], "reverted_by": []}
        if languages is not None:
            topic["languages"] = languages
        store.save_topics(self.root, {"version": 1, "topics": [topic]})
        self.commit("topics")
        sh(self.root, "git", "push", "-q", "origin", "main")
        self.w = ".claude/herald/work/%s/" % tid
        self.hrd("begin", "--topic", tid)
        self.write(self.w + "brief.md", "brief")
        self.hrd("branch", "--topic", tid, "--slug", slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "brief")
        self.write(self.w + "research.md", "C1. source\nC2. other")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "research")
        self.article(slug)
        self.write(self.w + "claims-map.json", json.dumps(
            {"sentences": [{"text": "Body text for %s." % slug, "claims": ["C1"]}]}))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        self.critique(tid, slug)
        return tid, slug

    def critique(self, tid, slug):
        self.write(self.w + "critique.md", "ok %s" % worktree_hash(self.root, self.cfg, slug))
        crit = json.loads(json.dumps(CRIT_PASS))
        crit["final_round"]["body_hash"] = worktree_hash(self.root, self.cfg, slug)
        crit["final_round"]["audit_round"] = self.hrd("audit-round", "--topic", tid)[0]["round"]
        self.write(self.w + "critique.json", json.dumps(crit))
        return self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")[0]

    def translate(self, slug, lang, sentence=None, claims=("C1",)):
        sentence = sentence or "%s sentence for %s." % (lang.upper(), slug)
        self.write(self.cfg.body_path(slug, lang), TR_DOC.format(lang=lang, slug=slug, sentence=sentence))
        self.write(self.w + "claims-map.%s.json" % lang,
                   json.dumps({"sentences": [{"text": sentence, "claims": list(claims)}]}))

    def tpass(self, tid, check=True):
        return self.hrd("stage", "pass", "--topic", tid, "--stage", "translation", check=check)

    def verify(self, tid, slug, langs=("ko", "ja")):
        by = {"en": {"hash": self.hrd("hash", "--slug", slug, "--source")[0]["hash"],
                     "counts": {"supported": 1, "unsupported": 0, "contradicted": 0}}}
        for l in langs:
            by[l] = {"hash": self.hrd("hash", "--slug", slug, "--lang", l)[0]["hash"],
                     "counts": {"supported": 1, "unsupported": 0, "contradicted": 0}}
        ver = {"counts": {"supported": 1 + len(langs), "unsupported": 0, "contradicted": 0, "unmapped": 0},
               "body_hash": bundle_hash(self.root, self.cfg, slug), "by_lang": by}
        self.write(self.w + "verify.md", "ok")
        self.write(self.w + "verify.json", json.dumps(ver))
        return ver


class LedgerIntegrityTests(TranslationFlow):
    def verified_with_translation(self, tid="t0001", slug="new-post"):
        """A verified bundle with a ko translation, through the translation stage."""
        self.to_critique(tid, slug, languages=["ko"])
        self.translate(slug, "ko")
        self.tpass(tid)
        w = self.w
        ver = self.verify(tid, slug, langs=("ko",))
        src_only = dict(ver, body_hash=worktree_hash(self.root, self.cfg, slug))
        self.write(w + "verify.json", json.dumps(src_only))
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertNotEqual(p.returncode, 0, "a source-only verify hash must not vouch for the bundle")
        self.write(w + "verify.json", json.dumps(ver))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        st = store.load_state(self.root, tid)
        self.assertEqual(st["verified_hash"], bundle_hash(self.root, self.cfg, slug))
        self.assertIn(self.cfg.body_path(slug, "ko"), st["verified_files"])
        self.assertEqual(self.hrd("finalize", "--topic", tid)[0]["agent_final_hash"], st["verified_hash"])
        rec = self.hrd("ledger", "record", "--topic", tid)[0]
        self.assertEqual(rec["langs"], ["ko"])
        self.assertEqual(rec["files"][self.cfg.body_path(slug, "ko")]["role"], "ko")
        self.commit("article")
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        sh(self.root, "git", "checkout", "-q", "main")
        sh(self.root, "git", "merge", "-q", "--no-ff", "-m", "merge", store.branch_name(tid, slug))
        sh(self.root, "git", "push", "-q", "origin", "main")
        self.set_prs([{"number": 1, "state": "MERGED", "headRefName": store.branch_name(tid, slug),
                       "headRefOid": head, "mergedAt": "2026-10-10T00:00:01Z", "labels": ["herald"]}])
        return tid, slug

    def row(self):
        rep = integrity.check(self.root, self.cfg)
        return [r for r in rep["articles"] if r["slug"] == "new-post"][0]

    def test_clean_bundle_is_ok(self):
        self.verified_with_translation()
        self.assertEqual(self.row()["status"], "ok")

    def test_causes(self):
        _, slug = self.verified_with_translation()
        ko, ja = self.cfg.body_path(slug, "ko"), self.cfg.body_path(slug, "ja")
        self.translation(slug, "ja")
        r = self.row()
        self.assertEqual((r["status"], r["causes"]), ("mismatch", ["translation_added:ja"]))
        os.remove(os.path.join(self.root, ja))
        self.write(ko, "changed")
        self.assertEqual(self.row()["causes"], ["translation_changed:ko"])
        os.remove(os.path.join(self.root, ko))
        self.assertEqual(self.row()["causes"], ["translation_missing:ko"])
        sh(self.root, "git", "checkout", "-q", "--", ko)
        self.write("public/blog-images/%s/02.png" % slug, b"new", binary=True)
        self.assertEqual(self.row()["causes"], ["image_changed"])
        os.remove(os.path.join(self.root, "public/blog-images/%s/02.png" % slug))
        self.write(self.cfg.body_path(slug), "human edit")
        self.assertEqual(self.row()["causes"], ["source_changed"])
        os.remove(os.path.join(self.root, self.cfg.body_path(slug)))
        self.assertEqual(self.row()["causes"], ["source_missing"])

    def test_unknown_path_after_target_pattern_change(self):
        self.verified_with_translation()
        data = translated_config()
        data["translations"]["targets"][0]["body_pattern"] = "src/content/korean/{slug}.md"
        self.use_config(data, commit=False)
        self.assertIn("unknown_path", self.row()["causes"])

    def test_080_ledger_line_digest_rule(self):
        """A line without `files` predates translations: an equal source means translations
        were only added; a changed source is reported too."""
        _, slug = self.verified_with_translation()
        led = os.path.join(self.root, ".claude/herald/ledger/verified.jsonl")
        lines = [json.loads(l) for l in open(led)]
        for rec in lines:
            rec.pop("files", None)
            rec.pop("langs", None)
            rec["verified_hash"] = worktree_hash(self.root, self.cfg, slug)
        with open(led, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in lines))
        self.assertEqual(self.row()["causes"], ["translation_added:ko"])
        self.write(self.cfg.body_path(slug), "human edit")
        self.assertEqual(self.row()["causes"], ["source_changed", "translation_added:ko"])

    def test_no_ledger_uses_committed_verified_files(self):
        _, slug = self.verified_with_translation()
        os.remove(os.path.join(self.root, ".claude/herald/ledger/verified.jsonl"))
        r = self.row()
        self.assertEqual((r["status"], r["causes"]), ("no-ledger", []))
        self.translation(slug, "ja")
        self.assertEqual(self.row()["causes"], ["translation_added:ja"])

    def test_withdraw_lang_proves_file_level_and_records(self):
        tid, slug = self.verified_with_translation()
        store.record_published(self.root, self.cfg, tid, slug, pr=1)
        self.commit("published")
        ko = self.cfg.body_path(slug, "ko")
        _, p = self.hrd("withdraw-lang", slug, "--lang", "ko", check=False)
        self.assertIn("remove", p.stderr)
        os.remove(os.path.join(self.root, ko))
        self.write(self.cfg.body_path(slug), "sneaky edit")
        _, p = self.hrd("withdraw-lang", slug, "--lang", "ko", check=False)
        self.assertIn("beyond removing", p.stderr)
        sh(self.root, "git", "checkout", "-q", "--", self.cfg.body_path(slug))
        out = self.hrd("withdraw-lang", slug, "--lang", "ko")[0]
        self.assertFalse(out["already_applied"])
        art = store.find_article(store.load_published(self.root), slug)
        self.assertNotIn("ko", art.get("translations") or {})
        self.assertEqual(art["withdrawn_langs"], ["ko"])
        self.commit("withdraw ko")
        self.hrd("ledger", "record", "--topic", tid, "--kind", "withdraw-lang")
        self.assertEqual(self.row()["status"], "ok")

    def test_no_translations_rows_unchanged(self):
        self.run_flow("t0001", "new-post")
        self.hrd("ledger", "record", "--topic", "t0001")
        rec = store.ledger_latest(self.root, "t0001")
        self.assertNotIn("files", rec)
        self.assertNotIn("verified_files", store.load_state(self.root, "t0001"))


class TranslationStageTests(TranslationFlow):
    def test_begin_sets_languages_and_critique_leads_to_translation(self):
        tid, slug = self.to_critique()
        st = store.load_state(self.root, tid)
        self.assertEqual(st["stage"], "translation")
        self.assertEqual(st["translation"]["langs"], ["ko", "ja"])
        self.assertEqual(st["translation"]["pending"], ["ko", "ja"])
        _, p = self.hrd("stage", "check", "--topic", tid, "--stage", "verify", check=False)
        self.assertNotEqual(p.returncode, 0)

    def test_full_pass_then_verify_and_publish_entry(self):
        tid, slug = self.to_critique()
        self.translate(slug, "ko")
        self.translate(slug, "ja")
        self.assertEqual(self.tpass(tid)[0]["stage"], "verify")
        ver = self.verify(tid, slug)
        bad = json.loads(json.dumps(ver))
        bad["counts"]["supported"] = 99
        self.write(self.w + "verify.json", json.dumps(bad))
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertIn("sum of by_lang", p.stderr)
        self.write(self.w + "verify.json", json.dumps(ver))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        self.assertEqual(self.hrd("stage", "check", "--topic", tid, "--stage", "publish")[0]["ok"], True)

    def test_partial_refusal_then_loopback_redoes_only_refused(self):
        tid, slug = self.to_critique()
        self.translate(slug, "ko")
        self.translate(slug, "ja", claims=("C2",))
        _, p = self.tpass(tid, check=False)
        self.assertIn("claims in ja the source does not state: C2", p.stderr)
        tr = store.load_state(self.root, tid)["translation"]
        self.assertEqual(tr["last_refusal"]["langs"], ["ja"])
        self.assertIn("ko", tr["passed"])
        out = self.hrd("loopback", "--topic", tid, "--cause", "translation")[0]
        self.assertEqual((out["stage"], out["langs"], out["stagnation"]), ("translation", ["ja"], False))
        self.translate(slug, "ja")
        self.assertEqual(self.tpass(tid)[0]["stage"], "verify")

    def test_untouched_language_must_not_change(self):
        tid, slug = self.to_critique()
        self.translate(slug, "ko")
        self.translate(slug, "ja", claims=("C2",))
        self.tpass(tid, check=False)
        self.hrd("loopback", "--topic", tid, "--cause", "translation")
        self.translate(slug, "ja")
        self.translate(slug, "ko", sentence="KO rewritten sentence.")
        _, p = self.tpass(tid, check=False)
        self.assertIn("ko changed although it was not being translated", p.stderr)

    def test_same_language_twice_is_stagnation(self):
        tid, slug = self.to_critique()
        self.translate(slug, "ko")
        self.translate(slug, "ja", claims=("C2",))
        self.tpass(tid, check=False)
        self.hrd("loopback", "--topic", tid, "--cause", "translation")
        self.tpass(tid, check=False)
        out = self.hrd("loopback", "--topic", tid, "--cause", "translation")[0]
        self.assertTrue(out["stagnation"])
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "translation", check=False)
        self.assertNotEqual(p.returncode, 0, "a consumed refusal is no basis for another loopback")

    def test_source_edit_during_translation_is_refused(self):
        tid, slug = self.to_critique()
        self.translate(slug, "ko")
        self.translate(slug, "ja")
        self.write(self.cfg.body_path(slug), ARTICLE_EDIT % slug)
        _, p = self.tpass(tid, check=False)
        self.assertIn("translator modified the source", p.stderr)

    def test_recritique_resets_translation_and_blocks_stale_verify(self):
        tid, slug = self.to_critique()
        self.translate(slug, "ko")
        self.translate(slug, "ja")
        self.tpass(tid)
        self.verify(tid, slug)
        self.hrd("loopback", "--topic", tid, "--cause", "verify", "--note", "x")
        self.write(self.cfg.body_path(slug), self.read(self.cfg.body_path(slug)) + "\nMore.\n")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")
        self.assertEqual(self.critique(tid, slug)["stage"], "translation")
        tr = store.load_state(self.root, tid)["translation"]
        self.assertEqual((tr["pending"], tr["hashes"], tr["last_refusal"]), (["ko", "ja"], {}, None))
        self.verify(tid, slug)  # skipping translation: the old translations are not from this source
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertNotEqual(p.returncode, 0)

    def test_no_languages_skips_translation(self):
        tid, slug = self.to_critique(languages=[])
        st = store.load_state(self.root, tid)
        self.assertEqual(st["stage"], "verify")
        self.write(self.w + "verify.md", "ok")
        self.write(self.w + "verify.json", json.dumps(dict(VER_PASS, body_hash=bundle_hash(self.root, self.cfg, slug))))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")

    def test_draft_requires_map_text_in_body(self):
        self.use_config(translated_config())
        store.save_topics(self.root, {"version": 1, "topics": [
            {"id": "t0001", "title": "T", "state": "queued", "history": [], "reverted_by": []}]})
        self.commit("topics")
        w = ".claude/herald/work/t0001/"
        self.hrd("begin", "--topic", "t0001")
        self.write(w + "brief.md", "b")
        self.hrd("branch", "--topic", "t0001", "--slug", "p")
        self.hrd("stage", "pass", "--topic", "t0001", "--stage", "brief")
        self.write(w + "research.md", "C1. s")
        self.hrd("stage", "pass", "--topic", "t0001", "--stage", "research")
        self.article("p")
        self.write(w + "claims-map.json", json.dumps({"sentences": [{"text": "Not in the body.", "claims": ["C1"]}]}))
        _, p = self.hrd("stage", "pass", "--topic", "t0001", "--stage", "draft", check=False)
        self.assertIn("text not found", p.stderr)
        self.write(w + "claims-map.json", json.dumps({"sentences": [{"text": "Body **text** for p.", "claims": ["C1"]}]}))
        self.hrd("stage", "pass", "--topic", "t0001", "--stage", "draft")

    def test_human_lang_loopback_not_counted(self):
        tid, slug = self.to_critique()
        self.translate(slug, "ko")
        self.translate(slug, "ja")
        self.tpass(tid)
        out = self.hrd("loopback", "--topic", tid, "--human", "--lang", "ja")[0]
        self.assertEqual((out["loopbacks"], out["langs"], out["stage"]), (0, ["ja"], "translation"))

    def read(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return f.read()


ARTICLE_EDIT = """---
title: Hello
description: d
slug: %s
date: 2026-10-10
---
Edited by the translator.
"""


class LanguageGateTests(MultiCase):
    def test_translation_rules_by_path(self):
        from hrdlib.validate import validate
        data = translated_config()
        self.use_config(data, commit=False)
        self.write("docs/editorial/gate-rules.json", json.dumps({
            "length": {"min_chars": 500}, "forbidden": [{"pattern": "BAD", "status": "confirmed"}],
            "languages": {"ja": {"forbidden": [{"pattern": "ダメ", "status": "confirmed"}]}}}))
        self.write(self.cfg.body_path("p", "ja"), TR_DOC.format(lang="ja", slug="p", sentence="短い。ダメ"))
        rep = validate(self.root, self.cfg, self.cfg.body_path("p", "ja"))
        self.assertEqual(rep["lang"], "ja")
        self.assertFalse(any("minimum" in e for e in rep["errors"]), rep)  # no source length range
        self.assertTrue(any("ダメ" in e for e in rep["errors"]))
        self.write(self.cfg.body_path("p"), TR_DOC.format(lang="en", slug="p", sentence="short"))
        rep = validate(self.root, self.cfg, self.cfg.body_path("p"))
        self.assertTrue(any("minimum" in e for e in rep["errors"]))
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "validate_content.py"), self.cfg.body_path("p", "ja")],
                           cwd=self.root, capture_output=True, text=True)
        self.assertEqual(json.loads(p.stdout)["lang"], "ja")

    def test_links_inside_a_translation(self):
        from hrdlib.validate import validate
        self.use_config(translated_config(), commit=False)
        self.article("other")
        self.write(self.cfg.body_path("p", "ko"), TR_DOC.format(lang="ko", slug="p", sentence="[x](/ko/blog/other/)"))
        rep = validate(self.root, self.cfg, self.cfg.body_path("p", "ko"))
        self.assertTrue(any("no ko translation" in w for w in rep["warnings"]), rep)
        self.assertEqual(rep["errors"], [])


class PublishTests(TranslationFlow):
    def on_branch_verified(self, langs=("ko",)):
        tid, slug = self.to_critique(languages=list(langs))
        for l in langs:
            self.translate(slug, l)
        self.tpass(tid)
        self.verify(tid, slug, langs=langs)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        self.hrd("finalize", "--topic", tid)
        self.commit("article")
        return tid, slug

    def test_scope_includes_own_languages_only(self):
        tid, slug = self.on_branch_verified()
        self.assertTrue(self.hrd("scope", "--topic", tid)[0]["ok"])
        self.translate(slug, "ja")
        self.commit("ja")
        _, p = self.hrd("scope", "--topic", tid, check=False)
        self.assertIn(self.cfg.body_path(slug, "ja"), p.stdout)

    def test_translated_exclusion_and_consent(self):
        tid, slug = self.on_branch_verified()
        self.assertIn("translated", store.exclusion_reasons(self.root, self.cfg, tid, rev="HEAD"))
        self.assertIn("translated", store.CONSENT_ACCEPTS)
        data = translated_config()
        data["translations"]["auto_publish"] = True
        self.use_config(data, commit=False)
        self.assertNotIn("translated", store.exclusion_reasons(self.root, self.cfg, tid, rev="HEAD"))

    def test_record_published_translations_and_throttle(self):
        from hrdlib import batch
        tid, slug = self.on_branch_verified()
        art = store.record_published(self.root, self.cfg, tid, slug, pr=1, auto=True)
        self.assertEqual(art["translations"]["ko"]["url"], "https://example.test/ko/blog/%s/" % slug)
        self.assertIs(art["translations"]["ko"]["human_reviewed"], False)
        self.assertEqual(len(art["publishes"]), 1)
        self.assertEqual(batch.auto_published_today(store.load_published(self.root)), 1)
        self.assertEqual(store.bundle_urls(self.root, self.cfg, slug),
                         {"en": "https://example.test/blog/%s/" % slug, "ko": "https://example.test/ko/blog/%s/" % slug})

    def test_move_refused_with_translations(self):
        tid, slug = self.on_branch_verified()
        store.record_published(self.root, self.cfg, tid, slug, pr=1)
        _, p = self.hrd("move", "--topic", tid, "--new-slug", "other", check=False)
        self.assertIn("not supported", p.stderr)

    def test_slug_in_progress_blocks_second_topic(self):
        tid, slug = self.to_critique()
        data = store.load_topics(self.root)
        data["topics"].append({"id": "t0002", "title": "U", "state": "queued", "history": [], "reverted_by": []})
        store.save_topics(self.root, data)
        sh(self.root, "git", "stash", "-u", "-q")
        sh(self.root, "git", "checkout", "-q", "main")
        sh(self.root, "git", "stash", "pop", "-q")
        self.hrd("begin", "--topic", "t0002")
        _, p = self.hrd("branch", "--topic", "t0002", "--slug", slug, check=False)
        self.assertIn("slug in progress: %s" % tid, p.stderr)

    def test_preserve_wip_discards_out_of_scope_bundle_files(self):
        from hrdlib import batch
        tid, slug = self.to_critique(languages=["ko"])
        self.translate(slug, "ko")
        self.translate(slug, "ja")  # not this topic's language
        batch.preserve_wip(self.root, self.cfg, tid)
        self.assertFalse(os.path.exists(os.path.join(self.root, self.cfg.body_path(slug, "ja"))))
        kept = os.path.join(self.root, ".claude/herald/memory/wip-discard", tid, "untracked", self.cfg.body_path(slug, "ja"))
        self.assertTrue(os.path.exists(kept))
        branch = store.branch_name(tid, slug)
        files = sh(self.root, "git", "show", "--name-only", "--format=", branch)
        self.assertIn(self.cfg.body_path(slug, "ko"), files)
        self.assertNotIn(self.cfg.body_path(slug, "ja"), files)


class LaterTranslationTests(TranslationFlow):
    def published_untranslated(self, tid="t0001", slug="new-post"):
        """A published Herald article with no translation (languages []), on main."""
        self.to_critique(tid, slug, languages=[])
        self.write(self.w + "verify.md", "ok")
        self.write(self.w + "verify.json", json.dumps(dict(VER_PASS, body_hash=bundle_hash(self.root, self.cfg, slug))))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        self.hrd("finalize", "--topic", tid)
        self.hrd("ledger", "record", "--topic", tid)
        self.commit("article")
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        sh(self.root, "git", "checkout", "-q", "main")
        sh(self.root, "git", "merge", "-q", "--no-ff", "-m", "merge", store.branch_name(tid, slug))
        self.set_prs([{"number": 1, "state": "MERGED", "headRefName": store.branch_name(tid, slug),
                       "headRefOid": head, "mergedAt": "2026-10-10T00:00:01Z", "labels": ["herald"]}])
        store.record_published(self.root, self.cfg, tid, slug, pr=1)
        self.commit("published")
        sh(self.root, "git", "push", "-q", "origin", "main")
        return slug

    def add_tr(self, slug, langs, tid="tr-new-post-20261016", adopt=False):
        item = {"id": tid, "title": "T", "translate_of": slug, "slug": slug, "languages": langs}
        if adopt:
            item["adopt"] = True
        self.write(".claude/herald/memory/tr.json", json.dumps([item]))
        self.hrd("topics", "add", "--file", ".claude/herald/memory/tr.json")
        self.commit("tr topic", ".claude/herald/topics.json")
        sh(self.root, "git", "push", "-q", "origin", "main")
        self.w = ".claude/herald/work/%s/" % tid
        return tid

    def test_later_translation_end_to_end(self):
        slug = self.published_untranslated()
        self.assertEqual(self.hrd("translate", "missing")[0]["articles"], [{"slug": slug, "langs": ["ko", "ja"]}])
        self.assertEqual(self.hrd("translate", "check", "--slug", slug, "--lang", "ja")[0]["ref"], "t0001")
        tid = self.add_tr(slug, ["ja"])
        st = self.hrd("begin", "--topic", tid) and store.load_state(self.root, tid)
        self.assertEqual((st["stage"], st["translation"]["langs"], st["inherited_from"]), ("translation", ["ja"], "t0001"))
        self.hrd("branch", "--topic", tid, "--slug", slug)
        self.translate(slug, "ja")
        _, p = self.tpass(tid, check=False)
        self.assertIn("remap", p.stderr)
        self.hrd("remap", "--topic", tid)
        self.assertEqual(self.tpass(tid)[0]["stage"], "verify")
        _, p = self.hrd("loopback", "--topic", tid, "--cause", "verify", check=False)
        self.assertIn("tr- topic has no draft", p.stderr)
        self.verify(tid, slug, langs=("ja",))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        self.hrd("finalize", "--topic", tid)
        self.commit("translation")
        self.assertTrue(self.hrd("scope", "--topic", tid)[0]["ok"])
        self.assertEqual(store.exclusion_reasons(self.root, self.cfg, tid, rev="HEAD"), ["translated"])
        self.assertTrue(self.hrd("premerge", "--topic", tid, "--rev", "HEAD")[0]["ok"])
        # a source edit on the tr- branch is out of its scope
        self.write(self.cfg.body_path(slug), self.read(self.cfg.body_path(slug)) + "x")
        self.commit("sneak")
        self.assertFalse(self.hrd("scope", "--topic", tid, check=False)[0]["ok"])

    def test_base_source_change_blocks_merge(self):
        slug = self.published_untranslated()
        tid = self.add_tr(slug, ["ja"])
        self.hrd("begin", "--topic", tid)
        self.hrd("branch", "--topic", tid, "--slug", slug)
        self.hrd("remap", "--topic", tid)
        self.translate(slug, "ja")
        self.tpass(tid)
        self.verify(tid, slug, langs=("ja",))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        self.commit("translation")
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        sh(self.root, "git", "checkout", "-q", "main")
        self.write(self.cfg.body_path(slug), self.read(self.cfg.body_path(slug)) + "human")
        self.commit("human edit on base")
        sh(self.root, "git", "push", "-q", "origin", "main")
        out, _ = self.hrd("premerge", "--topic", tid, "--rev", head, check=False)
        self.assertTrue(any(p.startswith("base-source-changed") for p in out["problems"]), out)

    def test_check_refusals(self):
        slug = self.published_untranslated()
        _, p = self.hrd("translate", "check", "--slug", "old-post", check=False)
        self.assertIn("not a published Herald article", p.stderr)
        self.add_tr(slug, ["ja"])
        _, p = self.hrd("translate", "check", "--slug", slug, "--lang", "ko", check=False)
        self.assertIn("in progress", p.stderr)

    def test_adopt_human_translation(self):
        slug = self.published_untranslated()
        self.translate(slug, "ko", sentence="A human KO translation.")
        row = [r for r in integrity.check(self.root, self.cfg)["articles"] if r["slug"] == slug][0]
        self.assertEqual(row["causes"], ["translation_added:ko"])
        _, p = self.hrd("translate", "check", "--slug", slug, "--lang", "ko", check=False)
        self.assertIn("already exist", p.stderr)
        self.assertEqual(self.hrd("translate", "check", "--slug", slug, "--lang", "ko", "--adopt")[0]["langs"], ["ko"])

    def read(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return f.read()


class ReviewRound1Tests(TranslationFlow):
    def test_topic_begun_without_translations_cannot_verify_a_human_translation(self):
        """R1 MJ-2: begun before translations were on; a human's ko file sits in the bundle."""
        data = translated_config()
        tid, slug = "t0001", "new-post"
        self.to_critique(tid, slug)  # languages = all targets
        st = store.load_state(self.root, tid)
        st.pop("translation")  # what a 0.8.0-begun topic looks like
        st["stage"] = "verify"
        st["stages"].pop("translation", None)
        store.save_state(self.root, tid, st)
        self.translate(slug, "ko")
        self.verify(tid, slug, langs=("ko",))
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", check=False)
        self.assertIn("did not make", p.stderr)

    def test_amend_refuses_a_source_edit_on_a_translated_article(self):
        """R1 MJ-3 (L18)."""
        tid, slug = self.to_critique(languages=["ko"])
        self.translate(slug, "ko")
        self.tpass(tid)
        self.verify(tid, slug, langs=("ko",))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        body = self.cfg.body_path(slug)
        with open(os.path.join(self.root, body)) as f:
            text = f.read()
        self.write(body, text + "\nA human sentence.\n")
        self.verify(tid, slug, langs=("ko",))
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", "--amend", check=False)
        self.assertIn("L18", p.stderr)

    def test_amend_regates_every_language_when_an_image_changes(self):
        """R1 MN-4: a shared image removed — the untouched translation's reference breaks."""
        self.write("public/blog-images/new-post/02.png", b"img", binary=True)  # part of the source from draft on
        tid, slug = self.to_critique(languages=["ko"])
        self.translate(slug, "ko", sentence="KO ![x](/blog-images/%s/02.png)" % slug)
        self.write(self.w + "claims-map.ko.json", json.dumps({"sentences": [{"text": "KO", "claims": ["C1"]}]}))
        self.tpass(tid)
        self.verify(tid, slug, langs=("ko",))
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")
        os.remove(os.path.join(self.root, "public/blog-images/%s/02.png" % slug))
        self.verify(tid, slug, langs=("ko",))
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", "--amend", check=False)
        self.assertIn("ko gate", p.stderr)

    def test_begin_with_an_existing_branch_resumes_there(self):
        """R1 MJ-1: the state lives on the branch (preserved hold / retry)."""
        tid, slug = self.to_critique(languages=["ko"])
        self.commit("wip")
        sh(self.root, "git", "checkout", "-q", "main")
        self.assertFalse(os.path.exists(store.state_path(self.root, tid)))
        out = self.hrd("begin", "--topic", tid)[0]
        self.assertEqual(out["branch"], store.branch_name(tid, slug))
        self.assertFalse(os.path.exists(store.state_path(self.root, tid)))

    def test_translation_loopback_needs_the_translation_stage(self):
        """R1 MN-11."""
        tid, slug = self.to_critique(languages=["ko"])
        st = store.load_state(self.root, tid)
        st["stage"] = "draft"
        store.save_state(self.root, tid, st)
        _, p = self.hrd("loopback", "--topic", tid, "--human", "--lang", "ko", check=False)
        self.assertIn("follows critique", p.stderr)

    def test_premerge_reports_missing_and_deleted_translations(self):
        """R1 MN-3: a topic language absent at the PR head."""
        tid, slug = self.to_critique(languages=["ko", "ja"])
        self.translate(slug, "ko")
        self.translate(slug, "ja")
        self.tpass(tid)
        os.remove(os.path.join(self.root, self.cfg.body_path(slug, "ja")))
        self.commit("head without ja")
        out, _ = self.hrd("premerge", "--topic", tid, "--rev", "HEAD", check=False)
        self.assertTrue(any(p.startswith("translation-missing:ja") for p in out["problems"]), out)

    def test_config_check_reports_warnings(self):
        """R1 MN-5."""
        data = translated_config()
        data["paths"]["build_inputs"] = ["src/content/blog"]
        self.use_config(data, commit=False)
        out = self.hrd("config-check")[0]
        self.assertTrue(out["ok"])
        self.assertTrue(out["warnings"])


class GuardTests(MultiCase):
    def guard(self, tool, tool_input, env=None):
        e = dict(os.environ)
        e.update(env or {})
        payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                           capture_output=True, text=True, env=e, cwd=self.root, timeout=60)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_translation_paths_are_herald_jurisdiction_on_base(self):
        data = translated_config()
        self.use_config(data)
        store.save_published(self.root, {"version": 1, "releases": [], "articles": [
            {"slug": "old-post", "origin": "herald", "current_topic_id": "t0001"}]})
        self.commit("pub")
        self.write("notes.md", "unrelated")
        sh(self.root, "git", "add", "-A")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m x"}), "allow")
        self.translation("old-post", "ko")
        sh(self.root, "git", "add", "-A")
        # same rule as a base commit of the body itself in 0.8.0: refused
        self.assertEqual(self.guard("Bash", {"command": "git commit -m x"}), "deny")

    def test_translations_key_is_protected(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        self.assertEqual(self.guard("Write", {"file_path": cfgp, "content": json.dumps(translated_config())}), "ask")

    def test_invalid_config_closed_rule(self):
        data = translated_config()
        data["roles"] = {"conditional": []}
        self.use_config(data, commit=False)
        self.assertEqual(self.guard("Bash", {"command": "git commit -m x"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "git commit -m x"}, {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, "notes.md")}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "ls"}), "allow")
        self.assertEqual(self.guard("Bash", {"command": "git status"}), "allow")
        # R1 MN-10: any other Bash needs a human — the guard computes no path from a broken config
        self.assertEqual(self.guard("Bash", {"command": "cp a.md src/content/blog/ko/x.md"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "git cherry-pick abc"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "cat a > b"}), "ask")


if __name__ == "__main__":
    unittest.main()
