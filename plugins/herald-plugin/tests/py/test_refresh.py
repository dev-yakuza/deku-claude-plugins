"""Refresh decision (design/herald/02-refresh-decision.md): precheck, recommendation, decide,
override signal, slug rules and the superseded link."""

import json
import os
import unittest

from helpers import RepoCase, sh

from hrdlib import refresh, store

REC = ".claude/herald/memory/refresh/old-post.json"
TOPIC = {"title": "Old post, updated", "category": "guide", "keywords": ["k"], "angle": "refresh: stale facts"}


class RefreshCase(RepoCase):
    def setUp(self):
        super().setUp()
        store.save_topics(self.root, {"version": 1, "topics": [
            {"id": "t0001", "title": "Old", "state": "published", "slug": "old-post", "history": [
                {"at": "2026-01-01T00:00:00+00:00", "state": "published", "reason": None, "note": "PR #1"}],
             "reverted_by": []}]})
        store.save_published(self.root, {"version": 1, "releases": [], "articles": [
            {"slug": "old-post", "origin": "herald", "current_topic_id": "t0001", "published_at": "2026-01-01T00:00:00+00:00",
             "path": "src/content/blog/old-post.md", "url": "https://example.test/blog/old-post/"}]})
        self.commit("published")
        sh(self.root, "git", "push", "-q", "origin", "main")

    def recommend(self, rec):
        self.write(REC, json.dumps(rec))

    def topic_file(self, data=TOPIC):
        p = os.path.join(self.tmp, "topic.json")
        with open(p, "w") as f:
            json.dump(data, f)
        return p

    def topics(self):
        return {t["id"]: t for t in store.load_topics(self.root)["topics"]}

    def article(self, slug="old-post"):
        return store.find_article(store.load_published(self.root), slug)


class PrecheckTests(RefreshCase):
    def test_all_choices_and_stale_file_removed(self):
        self.recommend({"recommendation": "none", "reasons": ["old"]})
        out = self.hrd("refresh-decision", "--slug", "old-post", "--precheck")[0]
        self.assertEqual(out["choices"], ["update", "new", "none"])
        self.assertFalse(os.path.exists(os.path.join(self.root, REC)))  # last session's file is not this one's

    def test_unpublished_refused(self):
        _, p = self.hrd("refresh-decision", "--slug", "nope", "--precheck", check=False)
        self.assertIn("not a published article", p.stderr)

    def test_in_progress_refresh_blocks_update_and_follows_blocks_new(self):
        data = store.load_topics(self.root)
        data["topics"] += [{"id": "r-old-post-20260101", "title": "x", "state": "queued", "refresh_of": "old-post",
                            "slug": "old-post", "history": [], "reverted_by": []},
                           {"id": "t0002", "title": "y", "state": "queued", "follows": "old-post", "history": [],
                            "reverted_by": []}]
        store.save_topics(self.root, data)
        out = self.hrd("refresh-decision", "--slug", "old-post", "--precheck")[0]
        self.assertEqual(out["choices"], ["none"])

    def test_required_update_for_translation_and_source_defect(self):
        out = self.hrd("refresh-decision", "--slug", "old-post", "--precheck", "--for-translation")[0]
        self.assertEqual((out["choices"], out["required"]), (["update"], "for-translation"))
        data = store.load_topics(self.root)
        data["topics"].append({"id": "tr-old-post-20260301", "title": "x", "state": "held", "reason": "source-defect",
                               "translate_of": "old-post", "slug": "old-post", "reverted_by": [], "history": [
                                   {"at": "2026-03-01T00:00:00+00:00", "state": "held", "reason": "source-defect",
                                    "note": "C3 no longer true"}]})
        store.save_topics(self.root, data)
        out = self.hrd("refresh-decision", "--slug", "old-post", "--precheck")[0]
        self.assertEqual((out["choices"], out["required"], out["source_defects"]), (["update"], "source-defect", ["C3 no longer true"]))

    def test_nothing_possible_stops(self):
        data = store.load_topics(self.root)
        data["topics"].append({"id": "r-old-post-20260101", "title": "x", "state": "queued", "refresh_of": "old-post",
                               "slug": "old-post", "history": [], "reverted_by": []})
        store.save_topics(self.root, data)
        out, p = self.hrd("refresh-decision", "--slug", "old-post", "--precheck", "--for-translation", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(out["choices"], [])


class DecideTests(RefreshCase):
    def test_check_rules(self):
        self.recommend({"recommendation": "update", "stale": []})
        out, _ = self.hrd("refresh-decision", "--slug", "old-post", "--check", check=False)
        self.assertTrue(any("stale" in x for x in out["problems"]))
        self.recommend({"recommendation": "new", "new_topic": {"title": "x"}})
        out, _ = self.hrd("refresh-decision", "--slug", "old-post", "--check", check=False)
        self.assertTrue(any("angle" in x for x in out["problems"]))
        self.recommend({"recommendation": "update", "stale": ["the 2025 fee"]})
        self.assertTrue(self.hrd("refresh-decision", "--slug", "old-post", "--check")[0]["ok"])

    def test_update_creates_refresh_topic_and_records_decision(self):
        self.recommend({"recommendation": "update", "stale": ["the 2025 fee"], "reasons": ["fees changed"],
                        "policy_rule": "1"})
        _, p = self.hrd("refresh-decision", "--slug", "old-post", "--decide", "update", check=False)
        self.assertIn("--topic-file", p.stderr)
        out = self.hrd("refresh-decision", "--slug", "old-post", "--decide", "update", "--topic-file", self.topic_file())[0]
        t = self.topics()[out["topic_id"]]
        self.assertTrue(out["topic_id"].startswith("r-old-post-"))
        self.assertEqual((t["refresh_of"], t["slug"], t["refresh_decision"]["stale"]), ("old-post", "old-post", ["the 2025 fee"]))
        d = self.article()["last_refresh_decision"]
        self.assertEqual((d["recommendation"], d["decision"], d["source"], d["choices"]),
                         ("update", "update", "recommended", ["update", "new", "none"]))

    def test_new_creates_following_topic(self):
        self.recommend({"recommendation": "new", "reasons": ["yearly"], "new_topic": {"title": "2027", "angle": "the 2027 edition"}})
        out = self.hrd("refresh-decision", "--slug", "old-post", "--decide", "new", "--topic-file",
                       self.topic_file({"title": "Exam dates 2027", "category": "guide", "angle": "2027 edition"}))[0]
        t = self.topics()[out["topic_id"]]
        self.assertEqual((t["follows"], t.get("slug"), t.get("refresh_of")), ("old-post", None, None))

    def test_none_records_only_and_signal_rule(self):
        self.recommend({"recommendation": "update", "stale": ["x"]})
        self.hrd("refresh-decision", "--slug", "old-post", "--decide", "none", "--override-reason", "still right")
        self.assertEqual(set(self.topics()), {"t0001"})
        self.assertEqual(self.article()["last_refresh_decision"]["override_reason"], "still right")
        # the override is recorded only once the decision is committed, and only once
        self.assertFalse(self.hrd("refresh-decision", "--slug", "old-post", "--signal")[0]["recorded"])
        self.commit("decision")
        self.assertTrue(self.hrd("refresh-decision", "--slug", "old-post", "--signal")[0]["recorded"])
        self.assertFalse(self.hrd("refresh-decision", "--slug", "old-post", "--signal")[0]["recorded"])

    def test_forced_is_not_an_override_and_needs_no_recommendation(self):
        out = self.hrd("refresh-decision", "--slug", "old-post", "--decide", "update", "--source", "forced",
                       "--topic-file", self.topic_file())[0]
        self.assertEqual(self.topics()[out["topic_id"]]["refresh_decision"]["source"], "forced")
        self.commit("decision")
        self.assertFalse(self.hrd("refresh-decision", "--slug", "old-post", "--signal")[0]["recorded"])

    def test_direction_needs_its_file(self):
        _, p = self.hrd("refresh-decision", "--slug", "old-post", "--decide", "update", "--source", "direction",
                        "--direction", "t0001", "--topic-file", self.topic_file(), check=False)
        self.assertIn("no saved direction", p.stderr)
        self.write(".claude/herald/memory/directions/t0001.diff", "diff")
        out = self.hrd("refresh-decision", "--slug", "old-post", "--decide", "update", "--source", "direction",
                       "--direction", "t0001", "--topic-file", self.topic_file())[0]
        self.assertTrue(self.topics()[out["topic_id"]]["direction"].endswith("t0001.diff"))

    def test_decision_outside_choices_and_unattended_refused(self):
        _, p = self.hrd("refresh-decision", "--slug", "old-post", "--decide", "none", "--for-translation", check=False)
        self.assertIn("not possible", p.stderr)
        _, p = self.hrd("refresh-decision", "--slug", "old-post", "--decide", "none", check=False,
                        env={"HRD_UNATTENDED": "1"})
        self.assertIn("unattended", p.stderr)

    def test_same_day_refresh_ids(self):
        data = store.load_topics(self.root)
        tid = refresh._next_refresh_id(data["topics"], "old-post")
        data["topics"].append({"id": tid, "title": "x", "state": "published", "history": [], "reverted_by": []})
        self.assertEqual(refresh._next_refresh_id(data["topics"], "old-post"), tid + "-2")


class BranchSlugTests(RefreshCase):
    def begin(self, item):
        data = store.load_topics(self.root)
        data["topics"].append(dict({"state": "queued", "history": [], "reverted_by": []}, **item))
        store.save_topics(self.root, data)
        self.commit("topic")
        sh(self.root, "git", "push", "-q", "origin", "main")
        self.hrd("begin", "--topic", item["id"])

    def test_refresh_keeps_its_slug(self):
        self.begin({"id": "r-old-post-20261016", "title": "x", "refresh_of": "old-post", "slug": "old-post"})
        _, p = self.hrd("branch", "--topic", "r-old-post-20261016", "--slug", "other", check=False)
        self.assertIn("slug mismatch", p.stderr)
        self.hrd("branch", "--topic", "r-old-post-20261016", "--slug", "old-post")

    def test_new_article_never_takes_a_used_slug(self):
        self.begin({"id": "t0002", "title": "x", "follows": "old-post"})
        _, p = self.hrd("branch", "--topic", "t0002", "--slug", "old-post", check=False)
        self.assertIn("slug used", p.stderr)
        self.hrd("branch", "--topic", "t0002", "--slug", "old-post-2027")

    def test_withdrawn_slug_is_reusable(self):
        pub = store.load_published(self.root)
        pub["articles"].append({"slug": "gone", "origin": "herald", "withdrawn": True})
        store.save_published(self.root, pub)
        self.begin({"id": "t0003", "title": "x"})
        self.hrd("branch", "--topic", "t0003", "--slug", "gone")


class SupersededTests(RefreshCase):
    def test_link_pending_and_cleanup(self):
        data = store.load_topics(self.root)
        data["topics"].append({"id": "t0002", "title": "2027", "state": "queued", "follows": "old-post",
                               "history": [], "reverted_by": []})
        store.save_topics(self.root, data)
        self.article_file("exam-2027")
        store.record_published(self.root, self.cfg, "t0002", "exam-2027", pr=2)
        self.assertEqual(self.article()["superseded"]["by"], "exam-2027")
        pending = self.hrd("status")[0]["supersede_pending"]
        self.assertEqual(pending, [{"old": "old-post", "new": "exam-2027", "refreshable": True}])
        # the human chose not to link: the reminder stops
        pub = store.load_published(self.root)
        store.find_article(pub, "old-post")["last_refresh_decision"] = {"at": "2999-01-01T00:00:00+00:00", "decision": "none"}
        store.save_published(self.root, pub)
        self.assertEqual(self.hrd("status")[0]["supersede_pending"], [])
        # withdrawing the new article drops the link
        os.remove(os.path.join(self.root, "src/content/blog/exam-2027.md"))
        sh(self.root, "git", "rm", "-q", "-r", "--cached", "public/blog-images/exam-2027", check=False)
        import shutil
        shutil.rmtree(os.path.join(self.root, "public/blog-images/exam-2027"), ignore_errors=True)
        self.hrd("withdraw", "exam-2027")
        self.assertNotIn("superseded", self.article())

    def test_link_added_in_body_clears_pending(self):
        data = store.load_topics(self.root)
        data["topics"].append({"id": "t0002", "title": "2027", "state": "queued", "follows": "old-post",
                               "history": [], "reverted_by": []})
        store.save_topics(self.root, data)
        self.article_file("exam-2027")
        store.record_published(self.root, self.cfg, "t0002", "exam-2027", pr=2)
        with open(os.path.join(self.root, "src/content/blog/old-post.md"), "a") as f:
            f.write("\nSee [2027](/blog/exam-2027/).\n")
        self.assertEqual(self.hrd("status")[0]["supersede_pending"], [])

    def article_file(self, slug):
        RepoCase.article(self, slug)


if __name__ == "__main__":
    unittest.main()
