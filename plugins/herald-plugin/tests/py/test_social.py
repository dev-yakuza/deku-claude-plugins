"""SNS drafts (design/herald/03-social.md, phase 1): channel guides and the persona, prepare's
promotion rules, the post checks, close, lint's floor and the commit trailers."""

import datetime
import json
import os
import subprocess
import sys
import unittest

from helpers import SCRIPTS, RepoCase, sh

from hrdlib import social, store
from hrdlib.hashing import bundle_hash

TODAY = datetime.date.today().isoformat()
PERSONA = {"service_terms": ["Safie", "セーフィー", {"term": "세이프", "exclude": ["세이프티"]}],
           "mix": {"promo": 1, "daily": 3}, "forbidden": []}
PROMOTION = "# Promotion\n\nSafie keeps your camera footage safe in the cloud.\n"


def guide_head(name="x", **over):
    h = {"name": name, "aliases": [], "lang": "en", "max_chars": 280, "count": "weighted", "url_len": 23,
         "hashtags": [0, 3], "link": "end",
         "disclosure": [{"kind": "ad", "required": True, "text": "#PR", "where": "post"}],
         "disclosure_waiver": None, "forbidden": [], "house": {}, "researched_at": TODAY}
    h.update(over)
    return h


def guide_text(head, researched="- 280 weighted characters.\n", house="- (none yet)\n"):
    return ("# Guide\n\n<!-- herald:channel\n%s\n-->\n\n%s\n## Researched\n%s%s\n\n## House rules\n%s"
            % (json.dumps(head, ensure_ascii=False), social.RESEARCHED_START, researched, social.RESEARCHED_END, house))


def persona_text(p=None):
    return "# Persona\n\n<!-- herald:social-persona\n%s\n-->\n\n## Voice\n- calm\n" % json.dumps(p or PERSONA, ensure_ascii=False)


class SocialCase(RepoCase):
    def setUp(self):
        super().setUp()
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["roles"] = {"conditional": ["distributor"]}
        self.write(".claude/herald/config.json", json.dumps(cfg))
        self.write(".claude/agents/distributor.md", "# Distributor\n")
        self.write("docs/editorial/persona.md", persona_text())
        self.write("docs/editorial/promotion.md", PROMOTION)
        self.write("docs/editorial/channels/x.md", guide_text(guide_head()))
        store.save_topics(self.root, {"version": 1, "topics": [
            {"id": "t0001", "title": "Old", "state": "published", "slug": "old-post", "history": [], "reverted_by": []}]})
        store.save_published(self.root, {"version": 1, "releases": [], "articles": [
            {"slug": "old-post", "origin": "herald", "current_topic_id": "t0001", "human_reviewed": True,
             "path": "src/content/blog/old-post.md", "url": "https://example.test/blog/old-post/"}]})
        self.commit("social setup")
        self.cfg = self.cfg.load(self.root)
        self.write(store.work_rel("t0001", "state.json"),
                   json.dumps({"verified_hash": bundle_hash(self.root, self.cfg, "old-post", rev="HEAD")}))
        self.write(store.work_rel("t0001", "brief.md"), "# brief\n")
        self.commit("verified record")
        sh(self.root, "git", "push", "-q", "origin", "main")

    def reload(self):
        from hrdlib.config import Config
        self.cfg = Config.load(self.root)

    def draft(self, rel, body, kind="promo", slug="old-post", run=None, sources=None, sns="x"):
        rec = social.drafted_record(self.root, rel)
        run = run or rec["run"]
        src = json.dumps(sources if sources is not None else [], ensure_ascii=False)
        self.write(rel, "---\nsns: %s\nkind: %s\nslug: %s\nrun: %s\nsources: %s\n---\n%s\n"
                   % (sns, kind, slug or "", run, src, body))

    def check(self, rel):
        return social.check_draft(self.root, self.cfg, rel)

    def failed(self, rel):
        return sorted({f["id"] for f in self.check(rel)["failed"]})

    def daily(self, body, sources=None):
        out = self.hrd("social", "prepare", "--sns", "x", "--n", "1")[0]
        rel = out["drafts"][0]
        self.draft(rel, body, kind="daily", slug=None, sources=sources)
        return rel

    def promo(self, body, sources=None):
        out = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "1")[0]
        rel = out["drafts"][0]
        self.draft(rel, body, sources=sources if sources is not None else
                   [{"text": "Body text for old-post.", "from": "body"}])
        return rel


QUOTE = [{"text": "Body text for old-post.", "from": "body"}]


class PrepareTests(SocialCase):
    def test_promo_basis(self):
        out = self.hrd("social", "prepare", "--sns", "X", "--slug", "old-post")[0]
        self.assertEqual((out["sns"], out["kind"], len(out["drafts"])), ("x", "promo", 3))
        self.assertEqual(out["read"]["url"], "https://example.test/blog/old-post/")
        self.assertEqual(out["read"]["brief"], ".claude/herald/work/t0001/brief.md")
        rec = social.drafted_record(self.root, out["drafts"][0])
        self.assertEqual((rec["body"], rec["signal_topic"][:9]), ("src/content/blog/old-post.md", "social:x:"))

    def test_alias_and_unknown_names(self):
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(aliases=["twitter"])))
        self.commit("alias")
        self.assertEqual(self.hrd("social", "prepare", "--sns", "Twitter", "--n", "1")[0]["sns"], "x")
        _, p = self.hrd("social", "prepare", "--sns", "threads", check=False)
        self.assertIn("--add threads", p.stderr)
        _, p = self.hrd("social", "prepare", "--sns", "pending", check=False)
        self.assertIn("invalid channel name", p.stderr)

    def test_refusals(self):
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "nope", check=False)
        self.assertIn("not a published article", p.stderr)
        pub = store.load_published(self.root)
        pub["articles"].append({"slug": "ext", "origin": "external", "path": "x", "url": "u"})
        store.save_published(self.root, pub)
        self.commit("ext")
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "ext", check=False)
        self.assertIn("external article", p.stderr)
        _, p = self.hrd("social", "prepare", "--sns", "x", "--n", "6", check=False)
        self.assertIn("--n must be", p.stderr)

    def test_changed_article_refused(self):
        self.write("src/content/blog/old-post.md", "---\ntitle: x\n---\nedited\n")
        self.commit("edit outside ship")
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", check=False)
        self.assertIn("differs from what was verified", p.stderr)

    def test_no_verified_record_refused(self):
        sh(self.root, "git", "rm", "-q", store.work_rel("t0001", "state.json"))
        self.commit("drop state")
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", check=False)
        self.assertIn("no verified record", p.stderr)

    def test_merged_unrecorded_refused(self):
        self.set_prs([{"number": 7, "state": "MERGED", "headRefName": "herald/r-old-post-20260101--old-post",
                       "mergedAt": "2026-10-01T00:00:00Z", "labels": ["herald"], "baseRefName": "main", "title": "t"}])
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", check=False)
        self.assertIn("/hrd ship", p.stderr)

    def test_empty_base_url_and_daily_only_and_setup(self):
        self.write("docs/editorial/channels/fr.md", guide_text(guide_head("fr", lang="fr")))
        self.commit("fr")
        _, p = self.hrd("social", "prepare", "--sns", "fr", "--slug", "old-post", check=False)
        self.assertIn("daily posts only", p.stderr)
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["site"]["base_url"] = ""
        cfg["roles"] = {"conditional": []}
        self.write(".claude/herald/config.json", json.dumps(cfg))
        self.commit("cfg")
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", check=False)
        self.assertIn("--setup", p.stderr)
        cfg["roles"] = {"conditional": ["distributor"]}
        self.write(".claude/herald/config.json", json.dumps(cfg))
        self.commit("cfg2")
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", check=False)
        self.assertIn("site.base_url is empty", p.stderr)

    def test_not_on_base_and_unattended(self):
        sh(self.root, "git", "switch", "-q", "-c", "other")
        _, p = self.hrd("social", "prepare", "--sns", "x", check=False)
        self.assertIn("switch to main", p.stderr)
        sh(self.root, "git", "switch", "-q", "main")
        _, p = self.hrd("social", "prepare", "--sns", "x", check=False, env={"HRD_UNATTENDED": "1"})
        self.assertIn("interactive only", p.stderr)

    def test_brief_follows_tr_chain(self):
        self.write(store.work_rel("tr-old-post-20260301", "state.json"),
                   json.dumps({"inherited_from": "t0001",
                               "verified_hash": bundle_hash(self.root, self.cfg, "old-post", rev="HEAD")}))
        pub = store.load_published(self.root)
        pub["articles"][0]["current_topic_id"] = "tr-old-post-20260301"
        store.save_published(self.root, pub)
        self.commit("tr")
        out = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "1")[0]
        self.assertEqual(out["read"]["brief"], ".claude/herald/work/t0001/brief.md")

    def test_unread_article_warns(self):
        pub = store.load_published(self.root)
        pub["articles"][0]["human_reviewed"] = False
        store.save_published(self.root, pub)
        self.commit("auto")
        out = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "1")[0]
        self.assertTrue(any("without a human reading it" in w for w in out["warnings"]))


class TranslationPromoTests(SocialCase):
    def setUp(self):
        super().setUp()
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["roles"] = {"conditional": ["distributor", "translator"]}
        cfg["translations"] = {"source": "en", "targets": [
            {"lang": "ja", "body_pattern": "{content}/ja/{slug}.md", "url_pattern": "/ja/blog/{slug}/"}]}
        self.write(".claude/herald/config.json", json.dumps(cfg))
        self.write("src/content/blog/ja/old-post.md", "---\ntitle: x\n---\n日本語の本文です。\nこれは テストの文です。\n")
        self.write("docs/editorial/channels/xj.md", guide_text(guide_head("xj", lang="ja")))
        self.commit("ja")
        self.reload()
        files = {p: {"blob": b, "role": self.cfg.path_role("old-post", p)}
                 for p, b in __import__("hrdlib.hashing", fromlist=["bundle_entries"]).bundle_entries(
                     self.root, self.cfg, "old-post", rev="HEAD")}
        self.write(store.work_rel("t0001", "state.json"),
                   json.dumps({"verified_hash": bundle_hash(self.root, self.cfg, "old-post", rev="HEAD"),
                               "verified_files": files}))
        pub = store.load_published(self.root)
        pub["articles"][0]["translations"] = {"ja": {"path": "src/content/blog/ja/old-post.md",
                                                     "url": "https://example.test/ja/blog/old-post/", "human_reviewed": True}}
        store.save_published(self.root, pub)
        self.commit("verified ja")

    def test_promotes_the_verified_translation(self):
        out = self.hrd("social", "prepare", "--sns", "xj", "--slug", "old-post", "--n", "1")[0]
        self.assertEqual((out["read"]["body"], out["read"]["url"]),
                         ("src/content/blog/ja/old-post.md", "https://example.test/ja/blog/old-post/"))
        self.assertFalse(out["daily_service_allowed"])  # promotion.md is in config.language (en)
        rel = out["drafts"][0]
        # a hard-wrapped Japanese body still matches a quote written without the break
        self.draft(rel, "これはテストの文です。 #PR https://example.test/ja/blog/old-post/", sns="xj",
                   sources=[{"text": "これはテストの文です。", "from": "body"}])
        self.assertEqual(self.failed(rel), [])
        self.draft(rel, "Safie。 #PR https://example.test/ja/blog/old-post/", sns="xj",
                   sources=[{"text": "Safie keeps your camera footage safe in the cloud.", "from": "promotion"}])
        self.assertIn("promotion-lang", self.failed(rel))

    def test_unpublished_or_unverified_translation_refused(self):
        pub = store.load_published(self.root)
        pub["articles"][0]["translations"] = {}
        store.save_published(self.root, pub)
        self.commit("no ja entry")
        _, p = self.hrd("social", "prepare", "--sns", "xj", "--slug", "old-post", check=False)
        self.assertIn("/hrd translate", p.stderr)


class CheckTests(SocialCase):
    def test_promo_passes(self):
        rel = self.promo("A short note on cameras. #PR https://example.test/blog/old-post/")
        res = self.check(rel)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["profile"], "promo")

    def test_promo_url_rules(self):
        rel = self.promo("Read it #PR https://example.test/blog/other/")
        self.assertIn("promo-url", self.failed(rel))
        rel = self.promo("Read it #PR https://evil.test/x")
        self.assertIn("promo-url", self.failed(rel))
        rel = self.promo("Read it #PR https://example.test/blog/old-post/?utm_source=x.")
        self.assertEqual(self.failed(rel), [])  # query stripped, trailing period not part of the URL
        rel = self.promo("Read it #PR")
        self.assertIn("promo-link-missing", self.failed(rel))
        rel = self.promo("https://example.test/blog/old-post/ then more words #PR")
        self.assertIn("link-position", self.failed(rel))

    def test_link_none(self):
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(link="none")))
        self.commit("none")
        rel = self.promo("Read it #PR https://example.test/blog/old-post/")
        self.assertIn("promo-url", self.failed(rel))
        rel = self.promo("Read it via the link in bio #PR")
        self.assertEqual(self.failed(rel), [])

    def test_disclosure_token(self):
        rel = self.promo("New post #PRODUCT https://example.test/blog/old-post/")
        self.assertIn("disclosure", self.failed(rel))

    def test_sources(self):
        rel = self.promo("x #PR https://example.test/blog/old-post/", sources=[])
        self.assertIn("sources", self.failed(rel))
        rel = self.promo("x #PR https://example.test/blog/old-post/", sources=[{"text": "Not in the article at all", "from": "body"}])
        self.assertIn("sources", self.failed(rel))
        rel = self.promo("x #PR https://example.test/blog/old-post/", sources=[{"text": "Body", "from": "body"}])
        self.assertIn("sources", self.failed(rel))  # too short
        rel = self.promo("x #PR https://example.test/blog/old-post/",
                         sources=[{"text": "Safie keeps your camera footage safe in the cloud.", "from": "body"}])
        self.assertIn("sources", self.failed(rel))  # checked only against the source it names
        rel = self.promo("x #PR https://example.test/blog/old-post/",
                         sources=[{"text": "Safie keeps your camera footage safe in the cloud.", "from": "promotion"}])
        self.assertEqual(self.failed(rel), [])

    def test_sources_read_from_head(self):
        self.write("src/content/blog/old-post.md", open(os.path.join(self.root, "src/content/blog/old-post.md")).read()
                   + "\nA sentence added just now.\n")
        rel = self.promo("x #PR https://example.test/blog/old-post/",
                         sources=[{"text": "A sentence added just now.", "from": "body"}])
        self.assertIn("sources", self.failed(rel))

    def test_daily_numbers(self):
        for ok in ("Woke at 3 again.", "In my 40s and still learning.", "Gym 3 times a week.",
                   "배 3개를 샀다.", "배가 고파서 2시에 먹었다.", "Node.js/Deno all day."):
            self.assertEqual(self.failed(self.daily(ok)), [], ok)
        for bad in ("30% of people agree.", "３０％ again", "2배로 늘었다.", "2배가 됐다.", "2倍になった。",
                    "3배에 달한다."):
            self.assertIn("s9b-statistic", self.failed(self.daily(bad)), bad)

    def test_daily_statistics_wording_per_language(self):
        self.write("docs/editorial/channels/xj.md", guide_text(guide_head("xj", lang="ja-JP")))
        self.write("docs/editorial/channels/xk.md", guide_text(guide_head("xk", lang="ko")))
        self.commit("ja ko")
        out = self.hrd("social", "prepare", "--sns", "xj", "--n", "1")[0]
        self.draft(out["drafts"][0], "統計では3人に1人だ。", kind="daily", slug=None, sns="xj")
        self.assertIn("s9b-statistic", self.failed(out["drafts"][0]))
        out = self.hrd("social", "prepare", "--sns", "xk", "--n", "1")[0]
        self.draft(out["drafts"][0], "언덕에 올라 2시간 걸었다.", kind="daily", slug=None, sns="xk")
        self.assertEqual(self.failed(out["drafts"][0]), [])

    def test_service_mentions(self):
        for body in ("Safie made my day.", "follow @safie_jp", "#safie_official is nice", "Ｓａｆｉｅ rocks",
                     "セーフィーの話", "see example.test"):
            rel = self.daily(body)
            res = self.check(rel)
            self.assertEqual(res["profile"], "daily+service", body)
            self.assertIn("disclosure", self.failed(rel), body)
        rel = self.daily("세이프티 수칙을 지켰다.")
        self.assertEqual(self.check(rel)["profile"], "daily")

    def test_daily_plus_service_rules(self):
        rel = self.daily("Safie keeps footage. #PR", sources=[{"text": "Safie keeps your camera footage safe in the cloud.",
                                                                "from": "promotion"}])
        self.assertEqual(self.failed(rel), [])
        rel = self.daily("Safie keeps footage. #PR", sources=QUOTE)
        self.assertIn("sources", self.failed(rel))
        rel = self.daily("Safie #PR https://example.test/blog/old-post/",
                         sources=[{"text": "Safie keeps your camera footage safe in the cloud.", "from": "promotion"}])
        self.assertIn("daily-url", self.failed(rel))

    def test_daily_rules(self):
        self.assertIn("daily-url", self.failed(self.daily("look shop.example.com/x")))
        self.assertIn("daily-sources", self.failed(self.daily("Rainy day.", sources=QUOTE)))

    def test_service_experience(self):
        rel = self.daily("I tried Safie and my mornings got easier. #PR",
                         sources=[{"text": "Safie keeps your camera footage safe in the cloud.", "from": "promotion"}])
        f = {x["id"]: x for x in self.check(rel)["failed"]}
        self.assertFalse(f["s9a-service-experience"]["overridable"])
        rel = self.promo("I tried Safie and loved it. #PR https://example.test/blog/old-post/")
        f = {x["id"]: x for x in self.check(rel)["failed"]}
        self.assertTrue(f["s9a-service-experience"]["overridable"])
        # the host stays one term: `example.test` is not cut at its dot
        rel = self.promo("I used example.test daily. #PR https://example.test/blog/old-post/")
        self.assertIn("s9a-service-experience", self.failed(rel))

    def test_length_hashtags_and_weighted(self):
        self.assertEqual(social.post_length("日本語", "weighted", 23), 6)
        self.assertEqual(social.post_length("ab https://example.test/x", "weighted", 23), 26)
        rel = self.daily("a " * 200)
        self.assertIn("length", self.failed(rel))
        rel = self.daily("tags #a #b #c #d")
        self.assertIn("hashtags", self.failed(rel))
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(house={"hashtags": [0, 1], "researched_at": "2000-01-01"})))
        self.commit("house")
        rel = self.daily("tags #a #b")
        self.assertIn("hashtags", self.failed(rel))

    def test_forbidden_and_scope(self):
        self.write("docs/editorial/gate-rules.json", json.dumps({"forbidden": [
            {"pattern": "Iam", "status": "confirmed", "scope": "article"},
            {"pattern": "awesome", "status": "confirmed"},
            {"pattern": "(bad", "regex": True, "status": "confirmed"}]}))
        self.commit("rules")
        rel = self.daily("Iam here, an awesome day.")
        self.assertEqual(self.failed(rel), ["forbidden-confirmed", "forbidden-invalid"])

    def test_header_mismatch(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--n", "1")[0]
        rel = out["drafts"][0]
        self.draft(rel, "hi", kind="promo", slug="old-post")
        self.assertIn("header-mismatch", self.failed(rel))
        self.write(rel, "no header\n")
        self.assertIn("header-mismatch", self.failed(rel))

    def test_daily_service_not_allowed_in_other_language(self):
        self.write("docs/editorial/channels/xj.md", guide_text(guide_head("xj", lang="ja")))
        self.commit("ja")
        out = self.hrd("social", "prepare", "--sns", "xj", "--n", "1")[0]
        self.assertFalse(out["daily_service_allowed"])
        self.draft(out["drafts"][0], "セーフィーの日。 #PR", kind="daily", slug=None, sns="xj",
                   sources=[{"text": "Safie keeps your camera footage safe in the cloud.", "from": "promotion"}])
        self.assertIn("service-mention-not-allowed", self.failed(out["drafts"][0]))

    def test_urls(self):
        self.assertEqual([u for _, _, u in social.find_urls("see (https://a.test/x).")], ["https://a.test/x"])
        self.assertEqual([u for _, _, u in social.find_urls("https://example.com/a日本語")], ["https://example.com/a"])
        self.assertEqual([u for _, _, u in social.find_urls("visit example.com today")], ["example.com"])
        self.assertEqual(social.find_urls("Node.js/Deno e.g. 3.5"), [])


class ReviewRound1Tests(SocialCase):
    def test_disclosure_inside_a_url_does_not_count(self):
        rel = self.promo("Read our post https://example.test/blog/old-post/#PR")
        self.assertIn("disclosure", self.failed(rel))
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(disclosure=[
            {"kind": "ad", "required": True, "text": "promo", "where": "post"}])))
        self.commit("word disclosure")
        rel = self.promo("Read it https://example.test/blog/old-post/?promo=1")
        self.assertIn("disclosure", self.failed(rel))

    def test_body_changed_after_prepare(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "1")[0]
        rel = out["drafts"][0]
        self.write("src/content/blog/old-post.md", open(os.path.join(self.root, "src/content/blog/old-post.md")).read()
                   + "\nAn unverified sentence here.\n")
        self.commit("edit on base")
        self.draft(rel, "x #PR https://example.test/blog/old-post/",
                   sources=[{"text": "An unverified sentence here.", "from": "body"}])
        self.assertIn("basis-changed", self.failed(rel))

    def test_guide_language_changed_after_prepare(self):
        rel = self.daily("Rainy day.")
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(lang="ko")))
        self.commit("lang")
        self.assertIn("basis-changed", self.failed(rel))

    def test_bom_draft(self):
        rel = self.daily("Rainy day.")
        self.write(rel, "\ufeff" + open(os.path.join(self.root, rel)).read())
        self.assertEqual(self.failed(rel), [])

    def test_invalid_gate_rules_fail_closed(self):
        self.write("docs/editorial/gate-rules.json", "{bad json")
        self.commit("broken rules")
        self.assertIn("forbidden-invalid", self.failed(self.daily("Rainy day.")))

    def test_www_host_and_idn_and_more_tlds(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["site"]["base_url"] = "https://www.example.test"
        self.write(".claude/herald/config.json", json.dumps(cfg))
        self.commit("www")
        self.reload()
        self.assertEqual(social.site_host(self.cfg), "example.test")
        self.assertIn("daily-url", self.failed(self.daily("see https://例え.jp/abc")))
        self.assertIn("daily-url", self.failed(self.daily("see example.ch/abc")))

    def test_weighted_counts(self):
        self.assertEqual(social.post_length("…→", "weighted", 23), 4)
        self.assertEqual(social.post_length("\U0001F469\u200D\U0001F4BB", "weighted", 23), 2)
        self.assertEqual(social.post_length("\U0001F44D\U0001F3FD", "weighted", 23), 2)


class ReviewRound2Tests(SocialCase):
    def test_cjk_adjacent_domains_and_handles(self):
        self.assertEqual([u for _, _, u in social.find_urls("詳しくはevil.comで")], ["evil.com"])
        self.assertEqual([u for _, _, u in social.find_urls("방문은evil.co.kr에서")], ["evil.co.kr"])
        self.assertEqual([u for _, _, u in social.find_urls("https://safie.jpで見た")], ["https://safie.jp"])
        self.assertEqual([u for _, _, u in social.find_urls("see https://例え.jp/abc")], ["https://例え.jp/abc"])
        rel = self.promo("#PR Body text. 詳しくはevil.comで https://example.test/blog/old-post/")
        self.assertIn("promo-url", self.failed(rel))
        self.assertEqual([m.group(0) for m in social.HANDLE_RE.finditer("Xの@tanaka_123さん a@b.c")], ["@tanaka_123"])

    def test_plain_disclosure_is_a_word(self):
        self.assertFalse(social.disclosure_present(social.fold("spring sale, read today"), "Ad"))
        self.assertFalse(social.disclosure_present(social.fold("our product"), "PR"))
        self.assertTrue(social.disclosure_present(social.fold("PR: new post"), "PR"))
        self.assertTrue(social.disclosure_present(social.fold("【PR】新しい記事"), "【PR】"))
        self.assertTrue(social.disclosure_present(social.fold("広告です"), "広告"))

    def test_guide_removed_after_prepare(self):
        rel = self.daily("Rainy day.")
        sh(self.root, "git", "rm", "-q", "docs/editorial/channels/x.md")
        self.commit("remove x")
        self.assertIn("guide-invalid", self.failed(rel))
        out, p = self.hrd("social", "check", "--file", rel, "nope.md", check=False)
        self.assertEqual(len(out), 2)

    def test_ledger_basis(self):
        led = os.path.join(self.root, ".claude/herald/ledger/verified.jsonl")
        os.makedirs(os.path.dirname(led), exist_ok=True)
        with open(led, "w") as f:
            f.write(json.dumps({"topic_id": "t0001", "verified_hash": bundle_hash(self.root, self.cfg, "old-post", rev="HEAD")}) + "\n")
        self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "1")
        with open(led, "a") as f:
            f.write(json.dumps({"topic_id": "t0001", "verified_hash": "sha256:other"}) + "\n")
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", check=False)
        self.assertIn("ledger mismatch", p.stderr)

    def test_withdrawn_refused(self):
        pub = store.load_published(self.root)
        pub["articles"][0]["withdrawn"] = True
        store.save_published(self.root, pub)
        self.commit("withdrawn")
        _, p = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", check=False)
        self.assertIn("withdrawn", p.stderr)

    def test_weights_and_regions(self):
        self.assertEqual(social.post_length("\U0001F1EF\U0001F1F5", "weighted", 23), 2)
        self.assertEqual(social.post_length("1\ufe0f\u20e3", "weighted", 23), 2)
        cfg = self.cfg
        self.assertEqual(social.promo_lang(cfg, "en-US"), "en")
        self.assertIsNone(social.promo_lang(cfg, "zh-TW"))


class ReviewRound3Tests(SocialCase):
    def test_handle_is_not_a_disclosure_label(self):
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(disclosure=[
            {"kind": "ad", "required": True, "text": "PR", "where": "post"}])))
        self.commit("PR label")
        for body in ("New post from @safie_pr", "see #safie_pr", "ad_free PR_team"):
            rel = self.promo(body + " https://example.test/blog/old-post/")
            self.assertIn("disclosure", self.failed(rel), body)
        rel = self.promo("PR New post https://example.test/blog/old-post/")
        self.assertNotIn("disclosure", self.failed(rel))

    def test_fullwidth_domain_is_a_url(self):
        rel = self.daily("Ｓａｆｉｅ．ｃｏｍ I tried it and my mornings changed.")
        self.assertIn("daily-url", self.failed(rel))

    def test_url_forms(self):
        for text, want in (("see...evil.com/x", ["evil.com/x"]), ("https://203.0.113.5/x", ["https://203.0.113.5/x"]),
                           ("http://intranet/x", ["http://intranet/x"]),
                           ("https://safie.jpで詳しくはNode.jsへ", ["https://safie.jp"])):
            self.assertEqual([u for _, _, u in social.find_urls(text)], want, text)

    def test_weights(self):
        flag = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
        self.assertEqual(social.post_length(flag, "weighted", 23), 2)
        self.assertEqual(social.post_length("\u00a9\ufe0f", "weighted", 23), 2)
        self.assertEqual(social.post_length("\u0915\u094d\u200d\u0937", "weighted", 23), 2)

    def test_language_tags(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["roles"] = {"conditional": ["distributor", "translator"]}
        cfg["translations"] = {"source": "en", "targets": [
            {"lang": "ja-JP", "body_pattern": "{content}/ja/{slug}.md", "url_pattern": "/ja/blog/{slug}/"}]}
        self.write(".claude/herald/config.json", json.dumps(cfg))
        self.commit("ja-JP")
        self.reload()
        self.assertEqual(social.promo_lang(self.cfg, "ja"), "ja-JP")
        self.assertEqual(social.promo_lang(self.cfg, "JA-jp"), "ja-JP")
        self.assertTrue(social.daily_service_allowed(self.cfg, "EN"))
        self.assertFalse(social.same_lang("zh-TW", "zh-CN"))

    def test_check_errors_are_not_writing_failures(self):
        out, _ = self.hrd("social", "check", "--file", "nope.md", check=False)
        self.assertEqual(out[0]["failed"][0]["id"], "check-error")
        sh(self.root, "git", "switch", "-q", "-c", "other")
        _, p = self.hrd("social", "check", "--file", "nope.md", check=False)
        self.assertIn("switch to main", p.stderr)

    def test_close_needs_clean_config(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--n", "1")[0]
        self.draft(out["drafts"][0], "Rainy day.", kind="daily", slug=None)
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cfg = json.load(open(cfgp))
        cfg["language"] = "ko"
        self.write(".claude/herald/config.json", json.dumps(cfg))
        _, p = self.hrd("social", "close", "--run", out["run"], "--approved", out["drafts"][0], check=False)
        self.assertIn("local edits", p.stderr)


class ReviewRound4Tests(SocialCase):
    def test_missing_space_after_a_period_is_not_a_url(self):
        for body in ("Long day.So tired.", "Went to the gym.It was hard.", "Finally home.me time", "done.Today was fine"):
            self.assertEqual(self.failed(self.daily(body)), [], body)
        for text, want in (("evil.cafe/x", ["evil.cafe/x"]), ("x.it/abc", ["x.it/abc"]), ("evil.ng", ["evil.ng"])):
            self.assertEqual([u for _, _, u in social.find_urls(text)], want, text)

    def test_fullwidth_disclosure_after_the_link(self):
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(disclosure=[
            {"kind": "ad", "required": True, "text": "（PR）", "where": "post"}])))
        self.commit("fullwidth PR")
        rel = self.promo("Body text. https://example.test/blog/old-post/ （PR）")
        self.assertEqual(self.failed(rel), [])

    def test_fullwidth_article_url_is_not_a_link(self):
        rel = self.promo("Body text. #PR ｈｔｔｐｓ://ｅｘａｍｐｌｅ.ｔｅｓｔ/ｂｌｏｇ/ｏｌｄ-ｐｏｓｔ/")
        self.assertIn("promo-url", self.failed(rel))


class CloseTests(SocialCase):
    def test_approve_records_and_copies(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "2")[0]
        a, b = out["drafts"]
        self.draft(a, "Nice read. #PR https://example.test/blog/old-post/", sources=QUOTE)
        self.draft(b, "Other. #PR https://example.test/blog/old-post/", sources=QUOTE)
        res = self.hrd("social", "close", "--run", out["run"], "--approved", a)[0]
        self.assertTrue(os.path.exists(os.path.join(self.root, res["copy"])))
        latest = social.latest_status(self.root)
        self.assertEqual((latest[a]["status"], latest[b]["status"], latest[a]["profile"]), ("approved", "unused", "promo"))
        self.assertEqual(social.recent_mix(self.root), {"n": 1, "promo": 1, "daily": 0})
        _, p = self.hrd("social", "close", "--run", out["run"], "--approved", b, check=False)
        self.assertIn("already closed", p.stderr)

    def test_hard_and_soft_failures(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--n", "1")[0]
        rel = out["drafts"][0]
        self.draft(rel, "30% sure. link https://x.test/", kind="daily", slug=None)
        _, p = self.hrd("social", "close", "--run", out["run"], "--approved", rel, check=False)
        self.assertIn("daily-url", p.stderr)
        self.draft(rel, "100% agree.", kind="daily", slug=None)
        _, p = self.hrd("social", "close", "--run", out["run"], "--approved", rel, check=False)
        self.assertIn("--override", p.stderr)
        res = self.hrd("social", "close", "--run", out["run"], "--approved", rel, "--override", "a figure of speech")[0]
        self.assertEqual(res["override"]["rules"], ["s9b-statistic"])

    def test_setting_disclosure_needs_confirmation(self):
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(disclosure=[
            {"kind": "ad", "required": True, "text": "Paid partnership label", "where": "setting"}])))
        self.commit("setting")
        out = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "1")[0]
        rel = out["drafts"][0]
        self.draft(rel, "Nice read. https://example.test/blog/old-post/", sources=QUOTE)
        _, p = self.hrd("social", "close", "--run", out["run"], "--approved", rel, check=False)
        self.assertIn("disclosure-setting-unconfirmed", p.stderr)
        self.hrd("social", "close", "--run", out["run"], "--approved", rel, "--setting-confirmed", "ad")

    def test_dirty_sources_and_reject_all(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--n", "2")[0]
        self.draft(out["drafts"][0], "Rainy day.", kind="daily", slug=None)
        self.write("docs/editorial/persona.md", persona_text() + "\nedit\n")
        _, p = self.hrd("social", "close", "--run", out["run"], "--approved", out["drafts"][0], check=False)
        self.assertIn("local edits", p.stderr)
        res = self.hrd("social", "close", "--run", out["run"], "--reject-all")[0]
        self.assertEqual(len(res["rejected"]), 2)


class LintTests(SocialCase):
    def lint(self, mode, text, target, *extra):
        p = os.path.join(self.tmp, "pending.md")
        with open(p, "w") as f:
            f.write(text)
        out, proc = self.hrd("social", "lint", "--mode", mode, "--file", p, "--target", target, *extra, check=False)
        return out

    def test_new_guide_needs_ad_disclosure_or_waiver(self):
        t = "docs/editorial/channels/y.md"
        out = self.lint("add", guide_text(guide_head("y", disclosure=[])), t)
        self.assertTrue(any("no required ad disclosure" in e for e in out["errors"]))
        waived = guide_head("y", disclosure=[], disclosure_waiver={"kind": "ad", "reason": "own brand account, legal ok",
                                                                    "approved_at": TODAY})
        out = self.lint("add", guide_text(waived), t)
        self.assertTrue(any("--allow-floor disclosure_waiver" in e for e in out["errors"]))
        out = self.lint("add", guide_text(waived), t, "--allow-floor", "disclosure_waiver")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["trailers"], ["Herald-Floor: disclosure_waiver"])

    def test_format_errors(self):
        t = "docs/editorial/channels/y.md"
        bad = guide_head("y", disclosure=[{"kind": "ad", "required": True, "text": " ", "where": "post"},
                                          {"kind": "ad", "required": True, "text": "#ad", "where": "post"}])
        out = self.lint("add", guide_text(bad), t)
        self.assertTrue(any("needs a text" in e for e in out["errors"]))
        self.assertTrue(any("two ad/post" in e for e in out["errors"]))
        out = self.lint("add", guide_text(guide_head("z")), t)
        self.assertTrue(any("must equal the file name" in e for e in out["errors"]))
        out = self.lint("add", guide_text(guide_head("y", aliases=["x"])), t)
        self.assertTrue(any("already the name" in e for e in out["errors"]))
        out = self.lint("add", guide_text(guide_head("y", lang="fr")), t)
        self.assertTrue(any("s9:fr" in e for e in out["errors"]))
        self.assertTrue(self.lint("add", guide_text(guide_head("y", lang="fr")), t, "--allow-floor", "s9:fr")["ok"])
        out = self.lint("add", guide_text(guide_head("y", forbidden=[{"pattern": "x", "status": "confirmed"}])), t)
        self.assertFalse(out["ok"])  # research never confirms a rule
        out = self.lint("edit", guide_text(guide_head("y")), t)
        self.assertIsNone(out)  # refused: not on base

    def test_edit_floor(self):
        t = "docs/editorial/channels/x.md"
        base = guide_head(forbidden=[{"pattern": "spam", "status": "confirmed"}])
        self.write(t, guide_text(base))
        self.commit("confirmed rule")
        out = self.lint("edit", guide_text(guide_head(forbidden=[{"pattern": "spam", "status": "draft"}])), t)
        tok = [e for e in out["errors"] if "forbidden:" in e]
        self.assertTrue(tok, out)
        out = self.lint("edit", guide_text(guide_head(max_chars=500, forbidden=base["forbidden"])), t)
        self.assertTrue(any("research fields" in e for e in out["errors"]))
        moved = guide_head(forbidden=base["forbidden"], disclosure=[
            {"kind": "ad", "required": True, "text": "#PR", "where": "profile"},
            {"kind": "ad", "required": True, "text": "Paid", "where": "setting"}])
        out = self.lint("edit", guide_text(moved), t)
        self.assertTrue(any("moved from post to" in e for e in out["errors"]), out)
        stronger = guide_head(forbidden=base["forbidden"] + [{"pattern": "scam", "status": "confirmed"}])
        out = self.lint("edit", guide_text(stronger), t)
        self.assertFalse(out["ok"])
        h = social._rule_hash({"pattern": "scam"})
        out = self.lint("edit", guide_text(stronger), t, "--strengthen", "forbidden:%s" % h)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["trailers"], ["Herald-Strengthen: forbidden:%s" % h])
        out = self.lint("edit", guide_text(guide_head(forbidden=base["forbidden"]), house="- shorter posts\n"), t)
        self.assertTrue(out["ok"], out)  # house rules are free

    def test_persona_floor_and_notes(self):
        p = dict(PERSONA, service_terms=["Safie"])
        out = self.lint("persona", persona_text(p), "docs/editorial/persona.md")
        self.assertTrue(any("service_terms" in e for e in out["errors"]))
        p = dict(PERSONA, service_terms=["Safie", "セーフィー", {"term": "세이프", "exclude": ["세이프티", "세이프존"]}])
        out = self.lint("persona", persona_text(p), "docs/editorial/persona.md")
        self.assertTrue(any("exclude:" in e for e in out["errors"]))
        p = dict(PERSONA, service_terms=[{"term": "세이프", "exclude": ["세이"]}])
        out = self.lint("persona", persona_text(p), "docs/editorial/persona.md")
        self.assertTrue(any("must contain the term" in e for e in out["errors"]))
        out = self.lint("setup", "# notes\n- crowded trains (source kind: forum, https://forum.test/thread/9)\n- @someone said\n",
                        "docs/editorial/persona-notes.md")
        self.assertEqual(len(out["errors"]), 2)
        self.assertTrue(self.lint("setup", "# notes\n- crowded trains (source kind: forum.test)\n",
                                  "docs/editorial/persona-notes.md")["ok"])


class LintRound1Tests(LintTests):
    def test_unparsable_head_is_compared_as_new(self):
        t = "docs/editorial/channels/x.md"
        self.write(t, "<!-- herald:channel {\"name\": \"x\",} -->\n")
        self.commit("broken guide")
        waived = guide_head(disclosure=[{"kind": "ad", "required": False, "text": "#PR", "where": "post"}],
                            disclosure_waiver={"kind": "ad", "reason": "r", "approved_at": TODAY})
        out = self.lint("edit", guide_text(waived), t)
        self.assertFalse(out["ok"])
        self.assertTrue(any("--allow-floor head" in e for e in out["errors"]))
        self.assertTrue(any("--allow-floor disclosure_waiver" in e for e in out["errors"]))
        self.write("docs/editorial/persona.md", "<!-- herald:social-persona {bad} -->\n")
        self.commit("broken persona")
        out = self.lint("persona", persona_text(), "docs/editorial/persona.md")
        self.assertTrue(any("--allow-floor head" in e for e in out["errors"]))

    def test_mode_must_fit_target(self):
        for mode, target in (("setup", "docs/editorial/channels/x.md"), ("persona", "docs/editorial/channels/x.md"),
                             ("edit", "docs/editorial/persona.md"), ("setup", "docs/editorial/persona.md")):
            self.assertIsNone(self.lint(mode, guide_text(guide_head()), target), (mode, target))

    def test_non_string_text_and_upward_move(self):
        t = "docs/editorial/channels/x.md"
        out = self.lint("edit", guide_text(guide_head(disclosure=[
            {"kind": "ad", "required": True, "text": 123, "where": "post"}])), t)
        self.assertTrue(any("must be a string" in e for e in out["errors"]))
        self.write(t, guide_text(guide_head(disclosure=[
            {"kind": "ad", "required": True, "text": "#PR", "where": "post"},
            {"kind": "operator", "required": True, "text": "Run by ACME", "where": "profile"}])))
        self.commit("operator profile")
        out = self.lint("edit", guide_text(guide_head(disclosure=[
            {"kind": "ad", "required": True, "text": "#PR", "where": "post"},
            {"kind": "operator", "required": True, "text": "#ACME", "where": "post"}])), t)
        self.assertTrue(out["ok"], out)

    def test_notes_without_scheme(self):
        out = self.lint("setup", "# notes\n- x.com/someone/status/123\n- www.instagram.com/p/abc\n"
                        "- example.com?user=tanaka\n- Xの＠tanaka_note\n", "docs/editorial/persona-notes.md")
        self.assertEqual(len(out["errors"]), 4, out)


class LintRound2Tests(LintTests):
    def test_unpatterned_language_decided_once(self):
        t = "docs/editorial/channels/fr.md"
        self.write(t, guide_text(guide_head("fr", lang="fr")))
        self.commit("fr accepted earlier")
        out = self.lint("edit", guide_text(guide_head("fr", lang="fr"), house="- calmer\n"), t)
        self.assertTrue(out["ok"], out)
        out = self.lint("edit", guide_text(guide_head("fr", lang="de")), t)
        self.assertTrue(any("s9:de" in e for e in out["errors"]))

    def test_disclosure_text_with_a_handle(self):
        out = self.lint("add", guide_text(guide_head("y", disclosure=[
            {"kind": "ad", "required": True, "text": "#PR", "where": "post"},
            {"kind": "operator", "required": True, "text": "Sponsored by @safie_jp", "where": "post"}])),
            "docs/editorial/channels/y.md")
        self.assertTrue(any("@handle" in e for e in out["errors"]))

    def test_disclosure_text_with_a_url(self):
        out = self.lint("add", guide_text(guide_head("y", disclosure=[
            {"kind": "ad", "required": True, "text": "#PR", "where": "post"},
            {"kind": "operator", "required": True, "text": "提供: safie.jp", "where": "post"}])),
            "docs/editorial/channels/y.md")
        self.assertTrue(any("contains a URL" in e for e in out["errors"]))


class TrailerAndGuardTests(SocialCase):
    def test_commit_trailers(self):
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(house={"hashtags": [0, 1]})))
        out = self.hrd("commit", "--cmd", "harness", "--kind", "social", "-m", "chore(herald): social edit x",
                       "--trailer", "Herald-Floor: disclosure_waiver — legal ok", "docs/editorial/channels/x.md")[0]
        body = sh(self.root, "git", "log", "-1", "--format=%(trailers:key=Herald-Floor,valueonly)", out["commit"]).strip()
        self.assertEqual(body, "disclosure_waiver — legal ok")
        self.write("docs/editorial/channels/x.md", guide_text(guide_head()))
        _, p = self.hrd("commit", "--cmd", "harness", "--kind", "social", "-m", "m", "--trailer", "Herald-Record: ship",
                        "docs/editorial/channels/x.md", check=False)
        self.assertIn("--trailer takes", p.stderr)

    def guard(self, tool, tool_input):
        payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                           capture_output=True, text=True, env=dict(os.environ), cwd=self.root, timeout=60)
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] if p.stdout.strip() else "allow"

    def test_guard(self):
        self.assertEqual(self.guard("Edit", {"file_path": os.path.join(self.root, "docs/editorial/channels/x.md")}), "ask")
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, "docs/editorial/persona.md")}), "ask")
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, ".claude/agents/distributor.md")}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "rm -r docs/editorial/channels"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": "cp .claude/herald/memory/social/pending/channels/y.md docs/editorial/channels/y.md"}), "ask")
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, ".claude/herald/memory/social/pending/x.md")}), "allow")


class ListTests(SocialCase):
    def test_list(self):
        self.write("docs/editorial/channels/old.md", guide_text(guide_head("old", researched_at="2020-01-01")))
        self.commit("old")
        out = self.hrd("social", "list")[0]
        rows = {r["name"]: r for r in out["channels"]}
        self.assertTrue(rows["old"]["stale"])
        self.assertFalse(rows["x"]["stale"])
        self.assertEqual((out["site_host"], out["persona"], out["enabled"]), ("example.test", True, True))


if __name__ == "__main__":
    unittest.main()
