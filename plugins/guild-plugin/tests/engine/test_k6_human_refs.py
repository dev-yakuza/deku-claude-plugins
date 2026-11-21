"""0.102.3 — a person's ordinary activity on other refs of the shared repo (a commit on main, a deleted merged
branch) is not drift; a ref moved to this worktree's own history still is."""

import os
import unittest

import _util  # noqa: F401
from _k1 import git, repo, tmpdir

from guildcore.roles import scope as SC


class HumanRefs(unittest.TestCase):
    def setUp(self):
        self.main = repo(self)
        git(self.main, "branch", "merged-old")
        self.wt = os.path.join(tmpdir(self), "wt")
        git(self.main, "worktree", "add", "-q", "-b", "fix/1", self.wt)
        self.base = SC.snapshot(self.wt)

    def _commit(self, cwd, name):
        with open(os.path.join(cwd, name), "w") as fh:
            fh.write(name)
        git(cwd, "add", name)
        git(cwd, "commit", "-qm", name)

    def test_main_moved_by_a_person_is_not_drift(self):
        self._commit(self.main, "update.txt")
        git(self.main, "branch", "-D", "merged-old")
        now = SC.snapshot(self.wt)
        self.assertEqual(SC.drift(self.base, now, self.wt), [])
        self.assertEqual([v for v in SC.check(self.wt, self.base, now, ["developer"], branch="fix/1") if "ref" in v], [])

    def test_a_ref_moved_onto_this_worktrees_history_is_drift(self):
        self._commit(self.wt, "late.txt")
        git(self.wt, "branch", "-f", "merged-old", "HEAD")
        now = SC.snapshot(self.wt)
        self.assertIn("ref refs/heads/merged-old", SC.drift(self.base, now, self.wt))
        self.assertIn("ref refs/heads/fix/1", SC.drift(self.base, now, self.wt))

    def test_without_a_worktree_drift_stays_strict(self):
        self._commit(self.main, "update.txt")
        self.assertIn("ref refs/heads/main", SC.drift(self.base, SC.snapshot(self.wt)))


if __name__ == "__main__":
    unittest.main()
