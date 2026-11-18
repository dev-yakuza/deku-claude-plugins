"""K4 review r4 regressions (design/guild/23-engine/review-k4-r4.md): M1 a create counts as refused ONLY on a definite
non-landing signal (HTTP 4xx, rate limit, gh not logged in) — an unknown error text, empty stderr, stream error,
5xx, timeout or signal goes down the ambiguous path (token → else a person), for every non-idempotent write ·
m1 the restart check records a found create WITH its number · m2 an abandoned create that landed after all is
surfaced to a person · m3 the ambiguous stop names its settle time, fix_child's unknown create is env: service,
1-based slice counter · m4 a deleted / transferred child is a clear stop then withdrawn on resume; the duplicate
check uses the journal key · m5 closed-as-duplicate is withdrawn only when verified · m6 an unclosed fence does
not hide a later plan-decision block."""

import unittest

import _util  # noqa: F401
from _k4 import K4
from test_k4_r3 import kids_of, posts, reload_journal, split_h, stale, Crash

from guildcore.adapters import gh as G
from guildcore.adapters.gh import FakeGh, FakeGhWrite, GhError, GhWriteError
from guildcore.records.write import GhWriter
from workflows.dev import analysis as AN
from workflows.dev.stages import base as B
from workflows.dev.stages import children as CH
from workflows.dev.stages import design as D
from workflows.dev.stages.base import StageResult

UNKNOWN_TEXTS = ("stream error: stream ID 3; INTERNAL_ERROR; received from peer", "", "gh failed",
                 "HTTP 501: Not Implemented", "HTTP 520", "signal: killed", "context deadline exceeded")


def lands_then(h, n_fail, text):
    orig = h.w.create_issue

    def f(title, body, labels=()):
        r = orig(title, body, labels)
        if r["number"] == n_fail:
            raise GhError(text)
        return r
    h.w.create_issue = f
    return orig


def resume(h):
    h.p.writer.labels_apply(7, remove=["guild:needs-human"])


def age_creates(h):
    for e in h.journal.entries:
        if e.get("op") == "issue:create":
            e["t"] = "2026-11-15T00:00:00Z"


# ---- M1 -------------------------------------------------------------------------------------------------------

class M1(unittest.TestCase):
    def test_probe_A_unclassified_error_after_landing_is_two_children(self):
        h = stale(split_h(self))
        orig = lands_then(h, 9, UNKNOWN_TEXTS[0])
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.SPLIT)                  # found by its token in the same run
        h.w.create_issue = orig
        self.assertEqual((kids_of(h), len(posts(h))), ([8, 9], 2))
        self.assertEqual(sorted((e["key"], e["number"]) for e in h.journal.own_issues()), [("7-data", 8), ("7-ui", 9)])

    def test_every_non_refusal_text_takes_the_ambiguous_path(self):
        for text in UNKNOWN_TEXTS + ("HTTP 502: Bad Gateway", "net/http: timeout awaiting response headers"):
            h = stale(split_h(self))
            lands_then(h, 9, text)
            self.assertEqual(D.run(h.p).kind, StageResult.SPLIT, text)
            self.assertEqual((kids_of(h), len(posts(h))), ([8, 9], 2), text)

    def test_landed_unknown_not_listed_pauses_posts_once_and_resume_finds_it(self):
        h = stale(split_h(self))
        orig = lands_then(h, 9, "stream error: stream ID 3; INTERNAL_ERROR")
        rows = h.gh.issue_rows
        h.gh.issue_rows = lambda **k: [r for r in rows(**k) if r["number"] != 9]   # the list lags
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("failed ambiguously", r.line)
        self.assertIn("resume after", r.line)                         # m3: the settle time
        self.assertEqual(len(posts(h)), 2)
        self.assertEqual(len([i for i in h.journal.intent_only() if i.get("op") == "issue:create"]), 1)
        h.w.create_issue, h.gh.issue_rows = orig, rows
        resume(h)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        self.assertEqual((kids_of(h), len(posts(h))), ([8, 9], 2))

    def test_classifier_default_is_unknown_and_refusal_is_narrow(self):
        self.assertEqual(G.classify_error("stream error: stream ID 3"), "unknown")
        self.assertEqual(G.classify_error(""), "unknown")
        self.assertEqual(G.classify_error("HTTP 404: Not Found"), "terminal")
        for t in ("HTTP 422: Validation Failed", "gh: Not Found (HTTP 404)", "HTTP 401: Bad credentials",
                  "HTTP 403: Resource not accessible by integration", "API rate limit exceeded",
                  "HTTP 403: You have exceeded a secondary rate limit", "To get started with GitHub CLI, run: gh auth login"):
            self.assertTrue(G.refused_before_accept(t), t)
        for t in UNKNOWN_TEXTS + ("HTTP 502: Bad Gateway", "HTTP 500", "i/o timeout", "connection reset by peer"):
            self.assertFalse(G.refused_before_accept(t), t)

    def test_definite_refusal_still_closes_the_intent(self):
        gh = FakeGh({"repo": "o/r", "issues": {}})
        fw = FakeGhWrite(gh)
        w = GhWriter(gh, fw, sleep=lambda s: None)
        fw.fail_next("ratelimit")
        with self.assertRaises(GhWriteError) as cm:
            w.issue_create("t", "b", labels=["guild:child"], key="7-a")
        self.assertEqual(cm.exception.kind, "ratelimit")
        self.assertEqual(w._ij().intent_only(), [])

    def test_unknown_unlanded_create_is_never_closed_as_refused(self):
        gh = FakeGh({"repo": "o/r", "issues": {}})
        fw = FakeGhWrite(gh)
        w = GhWriter(gh, fw, sleep=lambda s: None)
        fw._fail.append("")                                           # empty stderr, nothing landed
        with self.assertRaises(GhWriteError) as cm:
            w.issue_create("t", "b", labels=["guild:child"], key="7-a")
        self.assertEqual(cm.exception.kind, "ambiguous")
        self.assertEqual(len(w._ij().intent_only()), 1)               # stays open: resolved by token later

    def test_comment_create_unknown_after_landing_is_found_not_resent(self):
        gh = FakeGh({"repo": "o/r", "issues": {"7": {"labels": [], "comments": []}}})
        fw = FakeGhWrite(gh)
        w = GhWriter(gh, fw, sleep=lambda s: None)
        orig = fw.create_comment

        def lands(n, body):
            orig(n, body)
            raise GhError("stream error: stream ID 5; INTERNAL_ERROR")
        fw.create_comment = lands
        c = w.create_comment(7, "<!-- guild:note -->\nhello")
        self.assertTrue(c.get("id"))
        self.assertEqual(len(gh.fx["issues"]["7"]["comments"]), 1)

    def test_comment_create_unknown_unlanded_is_not_resent(self):
        gh = FakeGh({"repo": "o/r", "issues": {"7": {"labels": [], "comments": []}}})
        fw = FakeGhWrite(gh)
        w = GhWriter(gh, fw, sleep=lambda s: None)
        fw.fail_next("transient", message="signal: killed")
        with self.assertRaises(GhWriteError) as cm:
            w.create_comment(7, "<!-- guild:note -->\nhello")
        self.assertEqual(cm.exception.kind, "unknown")
        self.assertEqual(gh.fx["issues"]["7"]["comments"], [])
        self.assertEqual(len([c for c in fw.calls if c[0] == "create_comment"]), 1)

    def test_unkeyed_issue_create_is_never_resent(self):
        gh = FakeGh({"repo": "o/r", "issues": {}})
        fw = FakeGhWrite(gh)
        w = GhWriter(gh, fw, sleep=lambda s: None)
        fw.fail_next("transient")
        with self.assertRaises(GhWriteError):
            w.issue_create("t", "b")
        self.assertEqual(len([c for c in fw.calls if c[0] == "create_issue"]), 1)

    def test_pr_draft_fallback_only_on_a_definite_refusal(self):
        gh = FakeGh({"repo": "o/r", "issues": {}})
        fw = FakeGhWrite(gh)
        w = GhWriter(gh, fw, sleep=lambda s: None)
        gh.pr_for_head = lambda head: []
        fw.create_pr = lambda *a: (_ for _ in ()).throw(GhError("stream error mentioning draft"))
        with self.assertRaises(GhWriteError):
            w.pr_create("feat/x", "main", "t", "b", draft=True)


# ---- m1 -------------------------------------------------------------------------------------------------------

class M1Restart(unittest.TestCase):
    def test_probe_B_restart_check_records_the_number(self):
        h = stale(split_h(self))
        orig = h.w.create_issue

        def dies(title, body, labels=()):
            r = orig(title, body, labels)
            if r["number"] == 9:
                raise Crash()
            return r
        h.w.create_issue = dies
        with self.assertRaises(Crash):
            D.run(h.p)
        h.w.create_issue = orig
        reload_journal(h)
        self.assertEqual(h.journal.verify_pending(h.writer.verify_intent), [])
        reload_journal(h)
        self.assertIn(("7-ui", 9), [(e["key"], e["number"]) for e in h.journal.own_issues()])
        dones = [e for e in h.journal.entries if e["kind"] == "done" and e.get("op") == "issue:create"
                 and str(e.get("target", "")).startswith("7-ui")]
        self.assertEqual(len(dones), 1)                               # no second, contradicting done
        resume(h)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        self.assertEqual((kids_of(h), len(posts(h))), ([8, 9], 2))

    def test_young_absent_create_is_never_redo(self):
        h = stale(split_h(self))
        orig = h.w.create_issue

        def dies(title, body, labels=()):
            if len(posts(h)) == 1:
                h.w.calls.append(("create_issue",))
                raise Crash()                                         # died before the POST was sent
            return orig(title, body, labels)
        h.w.create_issue = dies
        with self.assertRaises(Crash):
            D.run(h.p)
        reload_journal(h)
        with self.assertRaises(GhWriteError) as cm:
            h.journal.verify_pending(h.writer.verify_intent)
        self.assertEqual(cm.exception.kind, "ambiguous")


# ---- m2 -------------------------------------------------------------------------------------------------------

class M2(unittest.TestCase):
    def test_probe_C_orphan_is_surfaced_not_ignored(self):
        h = stale(split_h(self))
        orig = h.w.create_issue

        def drops_label(title, body, labels=()):
            r = orig(title, body, labels)
            if r["number"] == 9:
                h.gh.fx["issues"]["9"]["labels"] = [{"name": "guild:analyze"}]
                raise GhError("HTTP 502: Bad Gateway")
            return r
        h.w.create_issue = drops_label
        self.assertEqual(D.run(h.p).kind, StageResult.PAUSE)
        h.w.create_issue = orig
        age_creates(h)
        resume(h)
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("outside the engine's journal: 7-ui → #9", r.line)
        self.assertEqual(len(posts(h)), 2)                            # nothing re-created over the orphan
        h.gh.fx["issues"]["9"].update(state="CLOSED", stateReason="NOT_PLANNED")     # the person's call
        resume(h)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        self.assertEqual(len(posts(h)), 3)

    def test_orphan_that_appears_after_the_recreate_stops_2b(self):
        h = stale(split_h(self))
        orig = lands_then(h, 9, "HTTP 502: Bad Gateway")
        rows = h.gh.issue_rows
        h.gh.issue_rows = lambda **k: [r for r in rows(**k) if r["number"] != 9]   # #9 invisible for a while
        self.assertEqual(D.run(h.p).kind, StageResult.PAUSE)
        h.w.create_issue = orig
        age_creates(h)
        resume(h)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)          # abandoned → #10
        h.gh.issue_rows = rows                                        # the late #9 shows up
        driven = []
        r = CH.run(h.p, lambda c: driven.append(c) or StageResult(StageResult.DONE))
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("7-ui → #9", r.line)
        self.assertEqual(driven, [])


# ---- m3 -------------------------------------------------------------------------------------------------------

class M3(unittest.TestCase):
    def test_fix_child_unknown_create_is_env_service(self):
        h = K4(self, labels=("guild:children",))
        h.w.create_issue = lambda *a, **k: (_ for _ in ()).throw(GhError("stream error: stream ID 1; CANCEL"))
        h.writer.sleep = lambda s: None
        r = CH.fix_child(h.p, {"refs": "seam differs"})
        self.assertIsNotNone(r)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("service unavailable", r.cause)                 # env: service, not "engine FAIL"
        self.assertNotIn("engine FAIL", r.cause)


# ---- m4 -------------------------------------------------------------------------------------------------------

class M4(unittest.TestCase):
    def _split(self):
        h = split_h(self)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        return h

    def test_deleted_child_is_a_clear_stop_then_withdrawn_on_resume(self):
        h = self._split()
        del h.gh.fx["issues"]["9"]
        driven = []
        drive = lambda c: driven.append(c) or StageResult(StageResult.PAUSE, cause="x")   # noqa: E731
        r = CH.run(h.p, drive)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("gone from this repository: #9 (7-ui)", r.line)
        self.assertEqual(driven, [])
        r2 = CH.run(h.p, drive)                                       # the resume: no crash loop
        self.assertEqual(driven, [8])

    def test_transferred_child_is_not_driven_as_this_repos_number(self):
        h = self._split()
        h.gh.fx["issues"]["9"]["repo"] = "other/repo"
        r = CH.run(h.p, lambda c: StageResult(StageResult.DONE))
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("now in other/repo", r.line)

    def test_number_mismatch_is_gone(self):
        h = self._split()
        h.gh.fx["issues"]["9"]["number"] = 42
        r = CH.run(h.p, lambda c: StageResult(StageResult.DONE))
        self.assertIn("answered as #42", r.line)

    def test_duplicate_check_uses_the_journal_key(self):
        h = self._split()
        b = h.gh.fx["issues"]["9"]["body"]
        h.gh.fx["issues"]["9"]["body"] = b.replace("<!-- guild:slice-key 7-ui -->", "")   # a person edited it away
        h.journal.own_write("issue", key="7-ui", number=10, token="x")
        h.gh.fx["issues"]["10"] = dict(h.gh.fx["issues"]["9"], number=10)
        driven = []
        r = CH.run(h.p, lambda c: driven.append(c) or StageResult(StageResult.DONE))
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("7-ui → #9, #10", r.line)
        self.assertEqual(driven, [])

    def test_read_failure_that_is_not_gone_stops_without_crashing(self):
        h = self._split()
        real = h.gh.issue_row
        h.gh.issue_row = lambda n: (_ for _ in ()).throw(GhError("HTTP 502: Bad Gateway")) if n == 9 else real(n)
        r = CH.run(h.p, lambda c: StageResult(StageResult.DONE))
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("service unavailable", r.cause)


# ---- m5 -------------------------------------------------------------------------------------------------------

class M5(unittest.TestCase):
    def test_duplicate_close_with_a_live_sibling_is_withdrawn(self):
        h = split_h(self)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        h.journal.own_write("issue", key="7-ui", number=10, token="x")
        h.gh.fx["issues"]["10"] = dict(h.gh.fx["issues"]["9"], number=10)
        h.gh.fx["issues"]["10"].update(state="CLOSED", stateReason="DUPLICATE")
        self.assertEqual([r["number"] for r in B.own_children(h.p)], [8, 9])

    def test_unverified_duplicate_close_is_noted(self):
        h = split_h(self)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        h.gh.fx["issues"]["8"].update(state="CLOSED", stateReason="DUPLICATE")
        r = CH.run(h.p, lambda c: StageResult(StageResult.DONE))
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("closed as duplicate (no live child holds 7-data)", r.line or r.cause)


# ---- m6 -------------------------------------------------------------------------------------------------------

class M6(unittest.TestCase):
    BLK = "<!-- guild:plan-decision -->\n- Goal: 범위? → close: not_planned — 결정\n<!-- /guild:plan-decision -->"

    def test_unclosed_fence_does_not_hide_an_appended_block(self):
        body = "log:\n```\npanic: x\n  at y\n\n" + self.BLK + "\n"
        self.assertEqual(len(AN.plan_decisions(body)), 1)

    def test_block_opened_inside_a_fence_is_still_ignored(self):
        self.assertEqual(AN.plan_decisions("x\n```md\n" + self.BLK + "\n```\n"), [])
        self.assertEqual(len(AN.plan_decisions("```\nlog\n```\n" + self.BLK)), 1)


if __name__ == "__main__":
    unittest.main()
