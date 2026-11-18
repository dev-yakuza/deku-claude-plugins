"""K5 carry-overs from the K4 review (review-k4-r5.md, final list items 16–18, r5-m4/m5):
16 (r5-m1) a deleted / transferred child on the DESIGN resume path is withdrawn (one judgement shared by
`own_children` and `issue_create`), never an endless stop · r5-m5 the transfer check compares with the parent
Issue's own REST row · 17 (r5-m2) `orphan_creates` only the lowest-numbered token holder, written by the engine's
login, with settled orphans out of the scan · 18 (r5-m3) an unclosed fence opened right before a block hides it ·
r5-m4 the restart check records a found comment's id; an unkeyed create / pr:create is never a blind redo."""

import unittest

import _util  # noqa: F401
from test_k4_r3 import kids_of, posts, split_h, stale

from guildcore.adapters.gh import GhError
from workflows.dev.stages import design as D
from workflows.dev.stages.base import StageResult


def age_creates(h):
    for e in h.journal.entries:
        if e.get("op") == "issue:create":
            e["t"] = "2026-11-15T00:00:00Z"


def resume(h):
    h.p.writer.labels_apply(7, remove=["guild:needs-human"])


def half_split(case):
    """#8 created, the second create fails before landing (502) → a partial-creation stop."""
    h = stale(split_h(case))
    orig = h.w.create_issue
    cnt = [0]

    def f(title, body, labels=()):
        cnt[0] += 1
        if cnt[0] == 2:
            raise GhError("HTTP 502: Bad Gateway")
        return orig(title, body, labels)
    h.w.create_issue = f
    case.assertEqual(D.run(h.p).kind, StageResult.PAUSE)
    h.w.create_issue = orig
    age_creates(h)
    return h


class Item16DesignResume(unittest.TestCase):
    def _resumes(self, h):
        out = []
        for _ in range(2):
            resume(h)
            out.append(D.run(h.p))
        return out

    def test_deleted_child_during_design_pause_is_recreated_not_looped(self):
        h = half_split(self)
        del h.gh.fx["issues"]["8"]
        r1, r2 = self._resumes(h)
        self.assertEqual(r1.kind, StageResult.PAUSE)
        self.assertIn("gone from this repository: #8 (7-data)", r1.line)
        self.assertEqual(r2.kind, StageResult.SPLIT)                 # the resume after it: withdrawn → re-created
        self.assertEqual(kids_of(h), [9, 10])
        self.assertEqual(len(posts(h)), 3)

    def test_transferred_child_during_design_pause_is_recreated_not_looped(self):
        h = half_split(self)
        h.gh.fx["issues"]["8"]["repo"] = "other/repo"
        r1, r2 = self._resumes(h)
        self.assertIn("now in other/repo (transferred)", r1.line)
        self.assertEqual(r2.kind, StageResult.SPLIT)
        self.assertEqual(len(posts(h)), 3)

    def test_issue_create_itself_judges_a_gone_holder(self):
        """No `own_children` before it (the journal's number deleted): recorded gone, created anew — no 404 FAIL."""
        h = split_h(self)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        del h.gh.fx["issues"]["8"]
        n, created = h.p.writer.issue_create("t", "Parent Issue: #7\n", labels=["guild:child"], key="7-data")
        self.assertTrue(created)
        self.assertNotEqual(n, 8)
        self.assertIn(8, h.p.writer.gone_numbers())

    def test_live_holder_is_still_returned(self):
        h = split_h(self)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        n, created = h.p.writer.issue_create("t", "x", labels=["guild:child"], key="7-data")
        self.assertEqual((n, created), (8, False))

    def test_transfer_reference_is_the_parent_row_repo(self):
        """r5-m5: a renamed repository (configured name stale, rows carry the new one) is not a transfer."""
        h = split_h(self)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        for k in ("7", "8", "9"):
            h.gh.fx["issues"][k]["repo"] = "owner/renamed"
        h.gh.repo = "owner/old-name"
        self.assertEqual(h.p.writer.home_repo(7), "owner/renamed")
        n, created = h.p.writer.issue_create("t", "x", labels=["guild:child"], key="7-data")
        self.assertEqual((n, created), (8, False))


def orphan_h(case):
    """Probe C of r4: #9 lands, its reply is a 502 and a person removed its label → abandoned → orphan stop."""
    h = stale(split_h(case))
    orig = h.w.create_issue

    def drops_label(title, body, labels=()):
        r = orig(title, body, labels)
        if r["number"] == 9:
            h.gh.fx["issues"]["9"]["labels"] = [{"name": "guild:analyze"}]
            raise GhError("HTTP 502: Bad Gateway")
        return r
    h.w.create_issue = drops_label
    D.run(h.p)
    h.w.create_issue = orig
    age_creates(h)
    resume(h)
    r = D.run(h.p)
    case.assertIn("outside the engine's journal: 7-ui → #9", r.line)
    return h


def outsider_copy(h, n, src=9):
    h.gh.fx["issues"][str(n)] = {"number": n, "title": "spam", "body": "copy:\n" + h.gh.fx["issues"][str(src)]["body"],
                                 "state": "OPEN", "labels": [], "comments": [], "timeline": [],
                                 "author_association": "NONE", "user": {"login": "mallory"},
                                 "created_at": "2026-11-16T00:00:00Z", "updated_at": "2026-11-16T00:00:00Z"}


class Item17Orphans(unittest.TestCase):
    def test_outsider_copy_of_a_closed_orphan_does_not_stop_the_parent(self):
        h = orphan_h(self)
        h.gh.fx["issues"]["9"].update(state="CLOSED", stateReason="NOT_PLANNED")
        outsider_copy(h, 20)
        resume(h)
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.SPLIT)
        self.assertNotIn("#20", r.line or "")

    def test_outsider_copy_is_never_the_candidate_even_while_the_orphan_is_open(self):
        h = orphan_h(self)
        outsider_copy(h, 20)
        resume(h)
        r = D.run(h.p)
        self.assertIn("7-ui → #9", r.line)
        self.assertNotIn("#20", r.line)

    def test_a_settled_orphan_leaves_the_scan(self):
        h = orphan_h(self)
        h.gh.fx["issues"]["9"].update(state="CLOSED", stateReason="NOT_PLANNED")
        resume(h)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        h.gh.calls[:] = []
        self.assertEqual(h.p.writer.orphan_creates("7-"), [])
        self.assertFalse([c for c in h.gh.calls if c[0] == "issue_rows"])    # no unfiltered list read any more

    def test_the_scan_window_closes(self):
        h = orphan_h(self)
        for e in h.journal.entries:
            if e.get("kind") == "done" and e.get("abandoned"):
                e["t"] = "2026-11-01T00:00:00Z"
        h.gh.calls[:] = []
        self.assertEqual(h.p.writer.orphan_creates("7-"), [])
        self.assertFalse([c for c in h.gh.calls if c[0] == "issue_rows"])

    def test_lost_reply_never_adopts_a_copy_by_another_login(self):
        from guildcore.adapters.gh import FakeGh, FakeGhWrite
        from guildcore.records.write import GhWriter
        gh = FakeGh({"repo": "o/r", "issues": {"7": {"number": 7, "title": "p", "body": "", "state": "OPEN"}}})
        w = GhWriter(gh, FakeGhWrite(gh), sleep=lambda s: None)
        gh.fx["issues"]["5"] = {"number": 5, "title": "x", "body": "<!-- guild:create-token abc -->", "state": "OPEN",
                                "labels": [{"name": "guild:child"}], "user": {"login": "mallory"},
                                "created_at": "2026-11-16T00:00:00Z", "updated_at": "2026-11-16T00:00:00Z"}
        self.assertIsNone(w.find_by_token("abc", "guild:child", None, reads=1))
        gh.fx["issues"]["5"]["user"] = {"login": "guild-bot"}
        self.assertEqual(w.find_by_token("abc", "guild:child", None, reads=1), 5)


class Item18Fence(unittest.TestCase):
    def test_block_right_after_an_unclosed_fence_is_the_example(self):
        from workflows.dev import analysis as AN
        body = ("Implement the close form. Example of what sprint plan writes:\n```\n"
                "<!-- guild:plan-decision -->\n- Goal: 범위? → close: not_planned — 예시\n<!-- /guild:plan-decision -->\n")
        self.assertEqual(AN.plan_decisions(body), [])

    def test_block_after_pasted_content_in_an_unclosed_fence_is_read(self):
        from workflows.dev import analysis as AN
        body = ("log:\n```\nerror at foo.dart:12\n\n"
                "<!-- guild:plan-decision -->\n- Goal: 범위? → close: not_planned — 예시\n<!-- /guild:plan-decision -->\n")
        self.assertEqual(len(AN.plan_decisions(body)), 1)


class R5M4RestartCheck(unittest.TestCase):
    def _w(self):
        import tempfile
        from _k1 import Clock
        from guildcore.adapters.gh import FakeGh, FakeGhWrite
        from guildcore.journal import Journal
        from guildcore.records.write import GhWriter
        d = tempfile.mkdtemp()
        clock = Clock("2026-11-16T00:00:00Z")
        gh = FakeGh({"repo": "o/r", "issues": {"7": {"number": 7, "title": "p", "body": "", "state": "OPEN",
                                                     "comments": [], "labels": []}}})
        fw = FakeGhWrite(gh)
        j = Journal(d, 7, clock)
        return gh, fw, GhWriter(gh, fw, journal=j, sleep=lambda s: None, clock=clock), j

    def test_found_comment_is_recorded_as_own(self):
        gh, fw, w, j = self._w()
        orig = fw.create_comment

        def lands_then_dies(issue, body):
            orig(issue, body)
            raise KeyboardInterrupt()
        fw.create_comment = lands_then_dies
        with self.assertRaises(KeyboardInterrupt):
            w.create_comment(7, "<!-- guild:needs-human -->\nx")
        self.assertEqual(j.own_comment_ids(), [])
        self.assertEqual(j.verify_pending(w.verify_intent), [])
        cid = gh.fx["issues"]["7"]["comments"][0]["id"]
        self.assertIn(cid, j.own_comment_ids())

    def test_unkeyed_create_is_never_a_redo(self):
        gh, fw, w, j = self._w()
        orig = fw.create_issue

        def lands_then_dies(title, body, labels=()):
            orig(title, body, labels)
            raise KeyboardInterrupt()
        fw.create_issue = lands_then_dies
        with self.assertRaises(KeyboardInterrupt):
            w.issue_create("t", "body")
        self.assertEqual(j.verify_pending(w.verify_intent), [])        # found by its body hash — recorded
        self.assertIn(8, [e["number"] for e in j.own_issues()])

    def test_unkeyed_create_absent_and_young_is_ambiguous(self):
        from guildcore.adapters.gh import GhWriteError
        gh, fw, w, j = self._w()
        fw.create_issue = lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            w.issue_create("t", "body")
        with self.assertRaises(GhWriteError) as cm:
            j.verify_pending(w.verify_intent)
        self.assertEqual(cm.exception.kind, "ambiguous")

    def test_pr_create_found_is_recorded_not_redone(self):
        gh, fw, w, j = self._w()
        j.intent(op="pr:create", target="feat/7", body_sha256="x", entry_id=None, stage=None, step_id=None, attempt=0)
        self.assertEqual(len(j.verify_pending(w.verify_intent)), 1)    # absent: left to the stage's pr_create (find first)
        gh.fx.setdefault("prs", []).append({"number": 30, "headRefName": "feat/7", "state": "OPEN"})
        self.assertEqual(j.verify_pending(w.verify_intent), [])
        self.assertIn(30, [e.get("number") for e in j.entries if e.get("op") == "pr"])


if __name__ == "__main__":
    unittest.main()
