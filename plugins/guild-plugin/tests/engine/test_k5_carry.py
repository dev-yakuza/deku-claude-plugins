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


if __name__ == "__main__":
    unittest.main()
