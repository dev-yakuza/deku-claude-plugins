"""SNS phase 2 (design/herald/03-social.md, 0.12.0): growth signals, the final text, the
re-research merge, lint's refresh/evolve modes and the commit-time floor check."""

import json
import os
import subprocess
import sys
import unittest

from helpers import SCRIPTS, sh
from test_social import QUOTE, TODAY, SocialCase, guide_head, guide_text, persona_text, PERSONA

from hrdlib import social, store


def signals(case, kind=None):
    p = os.path.join(case.root, ".claude/herald/signals.jsonl")
    if not os.path.exists(p):
        return []
    rows = [json.loads(l) for l in open(p) if l.strip()]
    return [r for r in rows if kind is None or r["kind"] == kind]


class SignalTests(SocialCase):
    def test_check_record_signals_once_per_theme(self):
        rel = self.daily("30% of us agree. see https://x.test/")
        self.hrd("social", "check", "--file", rel, check=False)
        self.assertEqual(signals(self, "social-gate-failure"), [])  # not the last check
        self.hrd("social", "check", "--record", "--file", rel, check=False)
        self.hrd("social", "check", "--record", "--file", rel, check=False)
        rows = signals(self, "social-gate-failure")
        self.assertEqual(sorted(r["data"]["theme"] for r in rows), ["format", "persona"])
        rec = social.drafted_record(self.root, rel)
        self.assertTrue(all(r["topic_id"] == rec["signal_topic"] for r in rows))

    def test_basis_and_guide_failures_are_not_signals(self):
        rel = self.daily("Rainy day.")
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(lang="ko")))
        self.commit("lang")
        self.hrd("social", "check", "--record", "--file", rel, check=False)
        self.assertEqual(signals(self, "social-gate-failure"), [])

    def test_reject_all_signal(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--n", "2")[0]
        self.hrd("social", "close", "--run", out["run"], "--reject-all")
        rows = signals(self, "social-reject")
        self.assertEqual((len(rows), rows[0]["data"]["n"], rows[0]["topic_id"]), (1, 2, out["signal_topic"]))

    def test_edit_request_validation(self):
        good = {"theme": "tone", "request": "softer", "run": "r", "draft": "d"}
        _, p = self.hrd("signal", "--kind", "social-edit-request", "--topic", "t0001", "--data", json.dumps(good), check=False)
        self.assertIn("social:<sns>", p.stderr)
        _, p = self.hrd("signal", "--kind", "social-edit-request", "--topic", "social:x:20261017",
                        "--data", json.dumps(dict(good, theme="voice")), check=False)
        self.assertIn("data.theme", p.stderr)
        _, p = self.hrd("signal", "--kind", "social-edit-request", "--topic", "social:x:20261017",
                        "--data", json.dumps({"theme": "tone"}), check=False)
        self.assertIn("request, run, draft", p.stderr)
        self.hrd("signal", "--kind", "social-edit-request", "--topic", "social:x:20261017", "--data", json.dumps(good))
        _, p = self.hrd("signal", "--kind", "social-reject", "--topic", "social:x:20261017", check=False)
        self.assertIn("recorded by HRD itself", p.stderr)

    def test_axes_and_readiness(self):
        for day, draft in (("20261015", "a"), ("20261016", "b"), ("20261017", "c")):
            store.signal(self.root, "social-edit-request", "social:x:%s" % day,
                         {"theme": "persona", "request": "less formal", "run": day, "draft": draft})
        store.signal(self.root, "social-edit-request", "social:x:20261017",
                     {"theme": "tone", "request": "x", "run": "r", "draft": "d"})
        store.signal(self.root, "hold", "t0001", {"reason": "research"})
        out = store.evolve_readiness(self.root)
        self.assertEqual(out["themes"]["social-edit-request:persona"]["count"], 3)
        self.assertIn("social-edit-request:persona", out["ready_themes"])
        self.assertEqual((out["topics"], out["social_topics"]), (1, 3))
        # the same day, same theme, two different requests stay two
        store.signal(self.root, "social-edit-request", "social:x:20261018",
                     {"theme": "length", "request": "shorter", "run": "r1", "draft": "d1"})
        store.signal(self.root, "social-edit-request", "social:x:20261018",
                     {"theme": "length", "request": "shorter", "run": "r1", "draft": "d2"})
        self.assertEqual(store.evolve_readiness(self.root)["themes"]["social-edit-request:length"]["count"], 2)

    def test_final_baseline(self):
        base = {"kind": "social-final", "topic_id": "social:x:20261017", "at": "x", "nonce": "n"}
        self.assertTrue(store.baseline_signal(dict(base, data={"chars_changed": 3, "draft_chars": 120})))
        self.assertFalse(store.baseline_signal(dict(base, data={"chars_changed": 40, "draft_chars": 40})))
        self.assertFalse(store.baseline_signal(dict(base, data={"chars_changed": "x", "draft_chars": 40})))


class FinalTests(SocialCase):
    def approve(self, body="Nice read. #PR https://example.test/blog/old-post/"):
        out = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "1")[0]
        rel = out["drafts"][0]
        self.draft(rel, body, sources=QUOTE)
        self.hrd("social", "close", "--run", out["run"], "--approved", rel)
        return rel

    def final_file(self, rel, text):
        path = social.memory_rel("final", "x", os.path.basename(rel))
        self.write(path, text)
        return path

    def test_unchanged_final_records_no_signal(self):
        rel = self.approve()
        out = self.hrd("social", "final", "--draft", rel, "--final-file",
                       self.final_file(rel, "Nice read. #PR https://example.test/blog/old-post/\n"))[0]
        self.assertEqual((out["chars_changed"], out["signal"]), (0, False))
        self.assertEqual(social.latest_status(self.root)[rel]["status"], "uploaded")
        self.assertEqual(social.recent_mix(self.root), {"n": 1, "promo": 1, "daily": 0})
        _, p = self.hrd("social", "final", "--draft", rel, "--final-file", self.final_file(rel, "again"), check=False)
        self.assertIn("not an approved draft", p.stderr)

    def test_changed_final_and_live_post_fix(self):
        rel = self.approve()
        out = self.hrd("social", "final", "--draft", rel, "--final-file",
                       self.final_file(rel, "Totally rewritten https://example.test/blog/old-post/"))[0]
        self.assertTrue(out["signal"])
        self.assertIn("disclosure", out["fix_live_post"])
        row = signals(self, "social-final")[0]
        self.assertEqual(row["data"]["draft_chars"], len("Nice read. #PR https://example.test/blog/old-post/"))
        self.assertFalse(store.baseline_signal(row))

    def test_refusals_and_guide_removed(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--n", "1")[0]
        rel = out["drafts"][0]
        _, p = self.hrd("social", "final", "--draft", rel, "--final-file", self.final_file(rel, "x"), check=False)
        self.assertIn("not an approved draft", p.stderr)
        rel = self.approve()
        self.write("elsewhere.md", "x")
        _, p = self.hrd("social", "final", "--draft", rel, "--final-file", "elsewhere.md", check=False)
        self.assertIn("memory/social/final/x", p.stderr)
        sh(self.root, "git", "rm", "-q", "docs/editorial/channels/x.md")
        self.commit("remove x")
        out = self.hrd("social", "final", "--draft", rel, "--final-file", self.final_file(rel, "Nice read."))[0]
        self.assertEqual(out["check"], {"skipped": "guide-missing"})

    def test_off_base_skips_quotes(self):
        rel = self.approve()
        sh(self.root, "git", "switch", "-q", "-c", "elsewhere")
        out = self.hrd("social", "final", "--draft", rel, "--final-file",
                       self.final_file(rel, "Nice read. #PR https://example.test/blog/old-post/"))[0]
        self.assertEqual(out["fix_live_post"], [])  # quotes are about the draft, never checked on the post
        self.assertIn("profile", out["check"])


class MergeTests(SocialCase):
    def setUp(self):
        super().setUp()
        self.base = guide_head(forbidden=[{"pattern": "spam", "status": "confirmed"}], house={"hashtags": [0, 1]},
                               aliases=["twitter"],
                               disclosure=[{"kind": "ad", "required": True, "text": "#PR", "where": "post"},
                                           {"kind": "operator", "required": True, "text": "Run by ACME", "where": "profile"}])
        self.write("docs/editorial/channels/x.md", guide_text(self.base, house="- our own rule\n"))
        self.commit("guide")

    def research(self, **over):
        h = dict(self.base, researched_at="2099-01-01", max_chars=500, house={}, aliases=[], lang="ko",
                 forbidden=[{"pattern": "spam", "status": "draft"}, {"pattern": "new-bad", "status": "confirmed"}])
        h.update(over)
        p = social.memory_rel("pending", "channels", "x.md")
        self.write(p, guide_text(h, researched="- 500 now.\n", house="- research rewrote this\n"))
        return p

    def merged(self, out):
        text = open(os.path.join(self.root, out["out"])).read()
        return social.parse_channel(text)[0], text

    def test_merge_keeps_what_research_does_not_own(self):
        out = self.hrd("social", "merge", "--sns", "x", "--researched", self.research())[0]
        h, text = self.merged(out)
        self.assertEqual((h["max_chars"], h["researched_at"]), (500, "2099-01-01"))
        self.assertEqual((h["aliases"], h["lang"], h["house"]), (["twitter"], "en", {"hashtags": [0, 1]}))
        rules = {r["pattern"]: r["status"] for r in h["forbidden"]}
        self.assertEqual(rules, {"spam": "confirmed", "new-bad": "draft"})
        self.assertIn("- 500 now.", text)
        self.assertIn("- our own rule", text)
        self.assertNotIn("research rewrote this", text)
        lint, _ = self.hrd("social", "lint", "--mode", "refresh", "--file", out["out"], "--target",
                           "docs/editorial/channels/x.md", check=False)
        self.assertTrue(lint["ok"], lint)

    def test_disclosure_loss_needs_the_human(self):
        weaker = [{"kind": "ad", "required": True, "text": "#ad", "where": "post"}]
        out = self.hrd("social", "merge", "--sns", "x", "--researched", self.research(disclosure=weaker))[0]
        h, _ = self.merged(out)
        self.assertEqual({d["text"] for d in h["disclosure"]}, {"#PR", "Run by ACME"})
        self.assertTrue(all(not c["applied"] for c in out["floor_changes"]))
        out = self.hrd("social", "merge", "--sns", "x", "--researched", self.research(disclosure=weaker),
                       "--accept-floor", "disclosure:ad/post")[0]
        h, _ = self.merged(out)
        self.assertEqual({d["text"] for d in h["disclosure"]}, {"#ad", "Run by ACME"})
        lint, _ = self.hrd("social", "lint", "--mode", "refresh", "--file", out["out"], "--target",
                           "docs/editorial/channels/x.md", check=False)
        self.assertFalse(lint["ok"])  # the operator item is gone too, and nobody accepted that
        self.assertIn("--allow-floor disclosure:ad/post", out["next"])

    def test_accept_subset(self):
        out = self.hrd("social", "merge", "--sns", "x", "--researched", self.research(), "--accept", "researched_at")[0]
        h, text = self.merged(out)
        self.assertEqual((h["max_chars"], h["researched_at"]), (280, "2099-01-01"))
        self.assertNotIn("- 500 now.", text)
        _, p = self.hrd("social", "merge", "--sns", "x", "--researched", self.research(), "--accept", "lang", check=False)
        self.assertIn("names nothing the research changed", p.stderr)


class LintModeTests(SocialCase):
    def lint(self, mode, text, target="docs/editorial/channels/x.md", *extra):
        p = os.path.join(self.tmp, "pending.md")
        with open(p, "w") as f:
            f.write(text)
        return self.hrd("social", "lint", "--mode", mode, "--file", p, "--target", target, *extra, check=False)[0]

    def setUp(self):
        super().setUp()
        self.base = guide_head(forbidden=[{"pattern": "spam", "status": "confirmed"}])
        self.write("docs/editorial/channels/x.md", guide_text(self.base))
        self.commit("guide")

    def test_refresh_mode(self):
        for over, house, what in ((dict(house={"hashtags": [0, 1]}), "- (none yet)\n", "house"),
                                  (dict(aliases=["tw"]), "- (none yet)\n", "identity"),
                                  ({}, "- changed\n", "house rules"),
                                  (dict(disclosure_waiver={"kind": "ad", "reason": "r", "approved_at": TODAY}),
                                   "- (none yet)\n", "waiver"),
                                  (dict(forbidden=self.base["forbidden"] + [{"pattern": "z", "status": "confirmed"}]),
                                   "- (none yet)\n", "draft")):
            out = self.lint("refresh", guide_text(dict(self.base, **over), house=house))
            self.assertFalse(out["ok"], what)
        self.assertTrue(self.lint("refresh", guide_text(dict(self.base, max_chars=300)))["ok"])

    def test_evolve_mode(self):
        self.assertTrue(self.lint("evolve", guide_text(dict(self.base, house={"hashtags": [0, 1]}), house="- shorter\n"))["ok"])
        self.assertTrue(self.lint("evolve", guide_text(dict(self.base, forbidden=self.base["forbidden"] + [
            {"pattern": "z", "status": "draft"}])))["ok"])
        self.assertFalse(self.lint("evolve", guide_text(dict(self.base, max_chars=300)))["ok"])
        out = self.lint("evolve", guide_text(dict(self.base, forbidden=[])), "docs/editorial/channels/x.md",
                        "--allow-floor", "forbidden:%s" % social._rule_hash({"pattern": "spam"}))
        self.assertTrue(any("evolve never loosens" in e for e in out["errors"]), out)
        self.assertFalse(self.lint("evolve", guide_text(dict(self.base, forbidden=self.base["forbidden"] + [
            {"pattern": "z", "status": "confirmed"}])))["ok"])
        out = self.lint("evolve", persona_text(dict(PERSONA, service_terms=["Safie", "セーフィー"])), "docs/editorial/persona.md")
        self.assertFalse(out["ok"])
        self.assertTrue(self.lint("evolve", persona_text(dict(PERSONA, mix={"promo": 1, "daily": 4})),
                                  "docs/editorial/persona.md")["ok"])


class CommitLintTests(SocialCase):
    def test_commit_checks_the_floor(self):
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(forbidden=[{"pattern": "spam", "status": "confirmed"}])))
        self.commit("rule")
        self.write("docs/editorial/channels/x.md", guide_text(guide_head()))
        _, p = self.hrd("commit", "--cmd", "harness", "--kind", "evolve", "-m", "chore(herald): evolve #1 — x",
                        "docs/editorial/channels/x.md", check=False)
        self.assertIn("social guides' floor", p.stderr)
        self.assertEqual(sh(self.root, "git", "diff", "--cached", "--name-only").strip(), "")  # unstaged again
        tok = "forbidden:%s" % social._rule_hash({"pattern": "spam"})
        self.hrd("commit", "--cmd", "harness", "--kind", "social", "-m", "chore(herald): social edit x",
                 "--trailer", "Herald-Floor: %s — no longer needed" % tok, "docs/editorial/channels/x.md")

    def test_deletions(self):
        os.remove(os.path.join(self.root, "docs/editorial/channels/x.md"))
        self.hrd("commit", "--cmd", "harness", "--kind", "social", "-m", "chore(herald): social remove x",
                 "docs/editorial/channels/x.md")
        os.remove(os.path.join(self.root, "docs/editorial/persona.md"))
        _, p = self.hrd("commit", "--cmd", "harness", "--kind", "social", "-m", "m", "docs/editorial/persona.md", check=False)
        self.assertIn("Herald-Floor: persona", p.stderr)
        self.hrd("commit", "--cmd", "harness", "--kind", "social", "-m", "m", "--trailer", "Herald-Floor: persona — off",
                 "docs/editorial/persona.md")

    def test_other_editorial_files_untouched(self):
        self.write("docs/editorial/style-guide.md", "# style\n")
        self.hrd("commit", "--cmd", "harness", "--kind", "config", "-m", "m", "docs/editorial/style-guide.md")

    def test_guard_asks_for_a_raw_commit(self):
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(house={"hashtags": [0, 1]})))
        sh(self.root, "git", "add", "docs/editorial/channels/x.md")
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                           capture_output=True, text=True, env=dict(os.environ), cwd=self.root, timeout=60)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "ask")
        self.assertIn("HRD commit", out["permissionDecisionReason"])


class StatusTests(SocialCase):
    def test_status_social_field(self):
        self.write("docs/editorial/channels/old.md", guide_text(guide_head("old", researched_at="2020-01-01")))
        self.commit("old")
        out = self.hrd("status")[0]
        self.assertEqual(out["social"], {"stale": ["old"], "invalid": []})
        sh(self.root, "git", "rm", "-q", "docs/editorial/persona.md")
        self.commit("no persona")
        self.assertNotIn("social", self.hrd("status")[0])

    def test_unattended(self):
        for args in (("merge", "--sns", "x", "--researched", "a"), ("final", "--draft", "a", "--final-file", "b")):
            _, p = self.hrd("social", *args, check=False, env={"HRD_UNATTENDED": "1"})
            self.assertIn("interactive only", p.stderr)


if __name__ == "__main__":
    unittest.main()


class Round1Tests(SocialCase):
    def hrd_commit(self, msg, *paths, trailers=(), check=True):
        args = ["commit", "--cmd", "harness", "--kind", "social", "-m", msg]
        for t in trailers:
            args += ["--trailer", t]
        return self.hrd(*args, *paths, check=check)

    def revert(self, sha):
        sh(self.root, "git", "revert", "--no-commit", sha)

    def test_rollback_lint_cases(self):
        t = "docs/editorial/channels/x.md"
        # a refresh commit: research fields reverted — fine for rollback
        self.write(t, guide_text(guide_head(max_chars=300)))
        sha = self.hrd_commit("chore(herald): social refresh x", t)[0]["commit"]
        self.revert(sha)
        self.assertTrue(self.hrd("social", "lint", "--mode", "rollback", "--target", t)[0]["ok"])
        sh(self.root, "git", "revert", "--abort")
        # an add commit: the revert deletes the guide — fine
        y = "docs/editorial/channels/y.md"
        self.write(y, guide_text(guide_head("y")))
        sha = self.hrd_commit("chore(herald): social add y", y)[0]["commit"]
        self.revert(sha)
        out = self.hrd("social", "lint", "--mode", "rollback", "--target", y)[0]
        self.assertTrue(out["ok"] and out["deleted"])
        sh(self.root, "git", "revert", "--abort")
        # reverting a loosening confirms the rule again: needs --strengthen, and the commit takes it
        self.write(t, guide_text(guide_head(forbidden=[{"pattern": "spam", "status": "confirmed"}])))
        self.commit("rule")
        h = social._rule_hash({"pattern": "spam"})
        self.write(t, guide_text(guide_head()))
        sha = self.hrd_commit("chore(herald): social edit x", t, trailers=["Herald-Floor: forbidden:%s — gone" % h])[0]["commit"]
        self.revert(sha)
        out = self.hrd("social", "lint", "--mode", "rollback", "--target", t, check=False)[0]
        self.assertFalse(out["ok"])
        out = self.hrd("social", "lint", "--mode", "rollback", "--target", t, "--strengthen", "forbidden:%s" % h)[0]
        self.assertEqual(out["trailers"], ["Herald-Strengthen: forbidden:%s" % h])
        sh(self.root, "git", "reset", "-q")
        self.hrd_commit("chore(herald): rollback x", t, trailers=["Herald-Strengthen: forbidden:%s — restore" % h])
        # a persona deletion by revert needs `persona`
        out = self.hrd("social", "lint", "--mode", "rollback", "--target", "docs/editorial/persona.md")[0]
        self.assertTrue(out["ok"])  # still there
        os.remove(os.path.join(self.root, "docs/editorial/persona.md"))
        out = self.hrd("social", "lint", "--mode", "rollback", "--target", "docs/editorial/persona.md", check=False)[0]
        self.assertFalse(out["ok"])

    def test_remove_then_add_keeps_the_floor(self):
        t = "docs/editorial/channels/x.md"
        self.write(t, guide_text(guide_head(forbidden=[{"pattern": "spam", "status": "confirmed"}])))
        self.commit("rule")
        os.remove(os.path.join(self.root, t))
        self.hrd_commit("chore(herald): social remove x", t)
        p = os.path.join(self.tmp, "p.md")
        with open(p, "w") as f:
            f.write(guide_text(guide_head()))
        out = self.hrd("social", "lint", "--mode", "add", "--file", p, "--target", t, check=False)[0]
        self.assertTrue(any("forbidden:" in e for e in out["errors"]), out)
        self.write(t, guide_text(guide_head()))
        _, proc = self.hrd_commit("chore(herald): social add x", t, check=False)
        self.assertIn("social guides' floor", proc.stderr)

    def test_malformed_heads_fail_closed_and_unstage(self):
        self.write("docs/editorial/persona.md", persona_text(dict(PERSONA, service_terms=[{"term": "Safie", "exclude": 5}])))
        _, proc = self.hrd_commit("m", "docs/editorial/persona.md", check=False)
        self.assertIn("social guides' floor", proc.stderr)
        self.assertEqual(sh(self.root, "git", "diff", "--cached", "--name-only").strip(), "")
        self.write("docs/editorial/persona.md", persona_text())
        self.write("docs/editorial/channels/x.md", guide_text(guide_head(disclosure=[
            {"kind": ["ad"], "required": True, "text": "#PR", "where": "post"}])))
        _, proc = self.hrd_commit("m", "docs/editorial/channels/x.md", check=False)
        self.assertIn("social guides' floor", proc.stderr)
        self.assertEqual(sh(self.root, "git", "diff", "--cached", "--name-only").strip(), "")

    def test_rename_does_not_hide_a_persona_removal(self):
        sh(self.root, "git", "mv", "docs/editorial/persona.md", "docs/editorial/persona-old.md")
        sh(self.root, "git", "reset", "-q")
        _, proc = self.hrd_commit("m", "docs/editorial/persona.md", "docs/editorial/persona-old.md", check=False)
        self.assertIn("Herald-Floor: persona", proc.stderr)

    def test_evolve_never_widens_house(self):
        t = "docs/editorial/channels/x.md"
        self.write(t, guide_text(guide_head(house={"max_chars": 100, "hashtags": [0, 1], "link": "end"})))
        self.commit("house")
        p = os.path.join(self.tmp, "p.md")
        for house in ({"max_chars": 200, "hashtags": [0, 1], "link": "end"}, {"max_chars": 100, "hashtags": [0, 2], "link": "end"},
                      {"max_chars": 100, "hashtags": [0, 1], "link": "any"}, {}):
            with open(p, "w") as f:
                f.write(guide_text(guide_head(house=house)))
            out = self.hrd("social", "lint", "--mode", "evolve", "--file", p, "--target", t, check=False)[0]
            self.assertFalse(out["ok"], house)
        with open(p, "w") as f:
            f.write(guide_text(guide_head(house={"max_chars": 90, "hashtags": [0, 0], "link": "none"})))
        self.assertTrue(self.hrd("social", "lint", "--mode", "evolve", "--file", p, "--target", t)[0]["ok"])

    def test_final_after_the_article_changed(self):
        out = self.hrd("social", "prepare", "--sns", "x", "--slug", "old-post", "--n", "1")[0]
        rel = out["drafts"][0]
        body = "Nice read. #PR https://example.test/blog/old-post/"
        self.draft(rel, body, sources=QUOTE)
        self.hrd("social", "close", "--run", out["run"], "--approved", rel)
        self.write("src/content/blog/old-post.md", "---\ntitle: x\n---\nnew body\n")
        self.commit("article updated")
        path = social.memory_rel("final", "x", os.path.basename(rel))
        self.write(path, body)
        res = self.hrd("social", "final", "--draft", rel, "--final-file", path)[0]
        self.assertEqual(res["fix_live_post"], [])

    def test_merge_move_loss_and_additions(self):
        t = "docs/editorial/channels/x.md"
        self.write(t, guide_text(guide_head(disclosure=[
            {"kind": "ad", "required": True, "text": "#PR", "where": "post"},
            {"kind": "operator", "required": True, "text": "Run by ACME", "where": "post"}])))
        self.commit("two items")
        new = guide_head(researched_at="2099-01-01", disclosure=[
            {"kind": "ad", "required": True, "text": "#PR", "where": "post"},
            {"kind": "operator", "required": True, "text": "Run by ACME", "where": "profile"},
            {"kind": "ad", "required": True, "text": "Paid", "where": "setting"}])
        p = social.memory_rel("pending", "channels", "x.md")
        self.write(p, guide_text(new))
        out = self.hrd("social", "merge", "--sns", "x", "--researched", p)[0]
        h = social.parse_channel(open(os.path.join(self.root, out["out"])).read())[0]
        keys = {(d["kind"], d["where"]) for d in h["disclosure"]}
        self.assertEqual(keys, {("ad", "post"), ("operator", "post"), ("ad", "setting")})
        self.assertEqual([c["token"] for c in out["floor_changes"]], ["disclosure:operator/post"])
