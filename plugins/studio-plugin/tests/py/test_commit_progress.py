"""M0e: merge · cherry-pick · revert · rebase in progress (m0e-plan v2 §5.1, §7.2, S9) and --range (§8)."""

import json
import os

from commit_base import CommitCase
from stdo.commit import okfile

SCRIPT = "studio/videos/v1/script.ko.md"


class Base(CommitCase):
    def setUp(self):
        super().setUp()
        self.env["GIT_EDITOR"] = "true"
        self.ready()
        self.studio_commit("# base\n", "base")

    def studio_commit(self, text, msg, rel=SCRIPT):
        self.write(rel, text)
        out = self.cc("--stage", "test", "v1")
        self.assertEqual(out.returncode, 0, out.stderr)
        out = self.commit(msg)
        self.assertEqual(out.returncode, 0, out.stderr)

    def plain_commit(self, rel, text, msg):
        self.write(rel, text)
        self.git("add", rel)
        out = self.commit(msg)
        self.assertEqual(out.returncode, 0, out.stderr)


class InProgress(Base):
    def test_finishing_after_resolving_a_studio_conflict_works(self):
        self.git("checkout", "-q", "-b", "a")
        self.studio_commit("# A\n", "a")
        self.git("checkout", "-q", "main")
        self.studio_commit("# B\n", "b")
        out = self.git("merge", "a", check=False)
        self.assertNotEqual(out.returncode, 0)  # conflict
        self.write(SCRIPT, "# A and B\n")
        # without --stage the hook refuses the new Studio content
        self.git("add", SCRIPT)
        out = self.commit("merge", "--no-edit")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("Studio pre-commit: refused", out.stderr)
        out = self.cc("--stage", "test", "v1")
        self.assertEqual(out.returncode, 0, out.stderr)
        ok, _ = okfile.read(self.repo)
        self.assertEqual(ok["in_progress"], "merge")
        self.assertEqual(ok["paths"], [SCRIPT])
        self.assertEqual(ok["head"], self.git("rev-parse", "HEAD").stdout.strip())
        out = self.git("commit", "--no-edit", check=False)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_clean_studio_auto_merge_with_a_conflict_elsewhere(self):
        """Review MJ-1: both sides edit different lines of a Studio file (git merges them cleanly); the
        conflict is only in src/a.ts — the person resolves it and the merge commit passes."""
        lines = ["# title\n"] + ["line %d\n" % i for i in range(1, 9)]
        self.studio_commit("".join(lines), "lines")
        self.plain_commit("src/a.ts", "base\n", "a base")
        self.git("checkout", "-q", "-b", "x")
        self.studio_commit("".join(["# title X\n"] + lines[1:]), "x studio")
        self.plain_commit("src/a.ts", "x\n", "x a")
        self.git("checkout", "-q", "main")
        self.studio_commit("".join(lines[:-1] + ["line 8 main\n"]), "main studio")
        self.plain_commit("src/a.ts", "main\n", "main a")
        out = self.git("merge", "x", check=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("src/a.ts", out.stdout + out.stderr)
        merged = self.read(SCRIPT)
        self.assertIn("# title X", merged)
        self.assertIn("line 8 main", merged)
        self.write("src/a.ts", "both\n")
        self.git("add", "src/a.ts")
        os.remove(okfile.path(self.repo))
        out = self.git("commit", "--no-edit", check=False)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_clean_studio_auto_merge_in_cherry_pick(self):
        lines = ["# title\n"] + ["line %d\n" % i for i in range(1, 9)]
        self.studio_commit("".join(lines), "lines")
        self.plain_commit("src/a.ts", "base\n", "a base")
        self.git("checkout", "-q", "-b", "y")
        self.write(SCRIPT, "".join(["# title Y\n"] + lines[1:]))
        self.write("src/a.ts", "y\n")
        self.assertEqual(self.cc("--stage", "test", "v1").returncode, 0)
        self.git("add", "src/a.ts")  # a mixed commit, made with --no-verify on purpose (someone else's)
        self.assertEqual(self.commit("y both", "--no-verify").returncode, 0)
        pick = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "main")
        self.studio_commit("".join(lines[:-1] + ["line 8 main\n"]), "main studio")
        self.plain_commit("src/a.ts", "main\n", "main a")
        self.assertNotEqual(self.git("cherry-pick", pick, check=False).returncode, 0)
        self.write("src/a.ts", "both\n")
        self.git("add", "src/a.ts")
        os.remove(okfile.path(self.repo))
        out = self.git("commit", "--no-edit", check=False)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_studio_conflict_resolved_with_theirs_is_not_new(self):
        """A conflicted Studio file resolved by taking the other side as it is: that version was already
        committed (checked) there — not this commit's own change."""
        self.git("checkout", "-q", "-b", "t")
        self.studio_commit("# T\n", "t")
        self.git("checkout", "-q", "main")
        self.studio_commit("# M\n", "m")
        self.assertNotEqual(self.git("merge", "t", check=False).returncode, 0)
        self.git("checkout", "--theirs", "--", SCRIPT)
        self.git("add", SCRIPT)
        os.remove(okfile.path(self.repo))
        out = self.git("commit", "--no-edit", check=False)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_merge_file_fallback_matches_merge_tree(self):
        from stdo.commit import inprogress
        from stdo.commit.gitx import Git
        lines = ["# title\n"] + ["line %d\n" % i for i in range(1, 9)]
        self.studio_commit("".join(lines), "lines")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "-b", "z")
        self.studio_commit("".join(["# title Z\n"] + lines[1:]), "z")
        z = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "main")
        self.studio_commit("".join(lines[:-1] + ["line 8 main\n"]), "m")
        head = self.git("rev-parse", "HEAD").stdout.strip()
        g = Git(self.repo, self.env)
        a = inprogress.auto_merge_blobs(g, head, (None, z), [SCRIPT])
        b = inprogress._merge_file(g, base, head, z, [SCRIPT])
        self.assertEqual(a, b)
        self.assertIsNotNone(a[SCRIPT])

    def test_other_parent_taken_as_is_is_not_checked(self):
        self.git("checkout", "-q", "-b", "b")
        self.studio_commit("# from b\n", "b studio")
        self.plain_commit("README.md", "b\n", "b readme")
        self.git("checkout", "-q", "main")
        self.plain_commit("README.md", "main\n", "main readme")
        out = self.git("merge", "b", check=False)
        self.assertNotEqual(out.returncode, 0)
        self.write("README.md", "both\n")
        self.git("add", "README.md")
        os.remove(okfile.path(self.repo))
        out = self.git("commit", "--no-edit", check=False)
        self.assertEqual(out.returncode, 0, out.stderr)  # no mixing check, no Studio change of its own

    def test_cherry_pick_and_revert_conflicts(self):
        self.git("checkout", "-q", "-b", "c")
        self.studio_commit("# C\n", "c")
        pick = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "main")
        self.studio_commit("# M\n", "m")
        out = self.git("cherry-pick", pick, check=False)
        self.assertNotEqual(out.returncode, 0)
        self.write(SCRIPT, "# C+M\n")
        self.assertEqual(self.cc("--stage", "test", "v1").returncode, 0)
        self.assertEqual(okfile.read(self.repo)[0]["in_progress"], "cherry-pick")
        out = self.git("cherry-pick", "--continue", check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        # revert the base commit's change with a conflict
        self.studio_commit("# later\n", "later")
        out = self.git("revert", "--no-edit", pick, check=False)
        if out.returncode != 0:
            self.write(SCRIPT, "# reverted by hand\n")
            self.assertEqual(self.cc("--stage", "test", "v1").returncode, 0)
            self.assertEqual(okfile.read(self.repo)[0]["in_progress"], "revert")
            out = self.git("revert", "--continue", check=False)
            self.assertEqual(out.returncode, 0, out.stderr)

    def test_nothing_studio_to_finish(self):
        self.git("checkout", "-q", "-b", "d")
        self.plain_commit("README.md", "d\n", "d")
        self.git("checkout", "-q", "main")
        self.plain_commit("README.md", "m\n", "m")
        self.assertNotEqual(self.git("merge", "d", check=False).returncode, 0)
        self.write("README.md", "dm\n")
        self.git("add", "README.md")
        out = self.cc("--stage", "test", "v1")
        self.assertIn(out.returncode, (1, 3), out.stderr)

    def test_which_operations_run_pre_commit(self):
        """Pinned (m0e-plan §5.1): integrations that do not stop for a conflict commit without pre-commit;
        `--range` covers them. A git version that changes this fails here."""
        log = os.path.join(self.tmp, "hook.log")
        hooks = os.path.join(self.repo, ".git", "hooks")
        self.exe(os.path.join(hooks, "pre-commit.studio-chained"), "#!/bin/sh\necho ran >> '%s'\n" % log)
        self.git("checkout", "-q", "-b", "e")
        self.plain_commit("e.txt", "e\n", "e")
        self.git("checkout", "-q", "-b", "f", "main")
        self.plain_commit("f.txt", "f\n", "f")
        f = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "-b", "g", "main")
        self.plain_commit("g.txt", "g\n", "g")
        self.git("checkout", "-q", "main")
        self.plain_commit("m.txt", "m\n", "m")
        os.remove(log)
        seen = {}
        for name, args in (("merge", ["merge", "--no-ff", "--no-edit", "e"]), ("cherry-pick", ["cherry-pick", f]),
                           ("revert", ["revert", "--no-edit", "HEAD"]), ("rebase", ["rebase", "-q", "g"])):
            if os.path.exists(log):
                os.remove(log)
            out = self.git(*args, check=False)
            self.assertEqual(out.returncode, 0, "%s: %s" % (name, out.stderr))
            seen[name] = os.path.exists(log)
        self.assertEqual(seen, {"merge": False, "cherry-pick": False, "revert": False, "rebase": False})


class Range(Base):
    def test_local_added_then_removed_is_in_history(self):
        start = self.git("rev-parse", "HEAD").stdout.strip()
        self.write("studio/local/x")
        self.git("add", "-f", "studio/local/x")
        self.assertEqual(self.commit("leak", "--no-verify").returncode, 0)
        self.git("rm", "-q", "--cached", "studio/local/x")
        self.assertEqual(self.commit("unleak", "--no-verify").returncode, 0)
        out = self.cc("--range", start + "..HEAD", "--json")
        self.assertEqual(out.returncode, 1, out.stderr)
        data = json.loads(out.stdout)
        self.assertEqual(len([c for c in data["commits"] if c["local_paths"]]), 1)

    def test_clean_range_records_and_since_last(self):
        start = self.git("rev-parse", "HEAD").stdout.strip()
        self.plain_commit("a.txt", "a\n", "a")
        out = self.cc("--range", start + "..HEAD", "--record")
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = json.load(open(os.path.join(self.repo, ".claude/studio/local/last-checked.json")))
        self.assertEqual(rec["head"], self.git("rev-parse", "HEAD").stdout.strip())
        self.plain_commit("b.txt", "b\n", "b")
        out = self.cc("--since-last", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(json.loads(out.stdout)["commits"]), 1)
        # a failed check does not move the record
        self.write("studio/local/y")
        self.git("add", "-f", "studio/local/y")
        self.commit("leak", "--no-verify")
        before = open(os.path.join(self.repo, ".claude/studio/local/last-checked.json")).read()
        self.assertEqual(self.cc("--since-last", "--record").returncode, 1)
        self.assertEqual(open(os.path.join(self.repo, ".claude/studio/local/last-checked.json")).read(), before)

    def test_someone_elses_video_after_merge_and_rebase(self):
        """Another person's video has no state here: the range check does not ask for approvals."""
        start = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "-b", "other")
        self.write("studio/videos/w9/script.ko.md", "# other person's video\n")
        self.git("add", "studio/videos/w9/script.ko.md")
        self.assertEqual(self.commit("their video", "--no-verify").returncode, 0)
        self.git("checkout", "-q", "main")
        self.plain_commit("mine.txt", "m\n", "mine")
        self.assertEqual(self.git("merge", "--no-edit", "other", check=False).returncode, 0)
        out = self.cc("--range", start + "..HEAD", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        merge = [c for c in json.loads(out.stdout)["commits"] if c["commit"] == self.git("rev-parse", "HEAD").stdout.strip()]
        self.assertEqual(merge[0]["studio_paths"], [])  # the merge itself made no change of its own
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.assertEqual(self.git("rebase", "-q", "other", check=False).returncode, 0)
        self.assertEqual(self.cc("--range", start + "..HEAD").returncode, 0)

    def test_mixed_commit_warns(self):
        start = self.git("rev-parse", "HEAD").stdout.strip()
        self.write("studio/videos/w1/script.ko.md")
        self.write("src/z.ts")
        self.git("add", "studio/videos/w1/script.ko.md", "src/z.ts")
        self.commit("mixed", "--no-verify")
        out = self.cc("--range", start + "..HEAD")
        self.assertEqual(out.returncode, 0)
        self.assertIn("warning: commit", out.stderr)

    def test_bad_range(self):
        self.assertEqual(self.cc("--range", "nope..HEAD").returncode, 2)
        self.assertEqual(self.cc("--range", "HEAD").returncode, 2)
        self.assertEqual(self.cc("--since-last").returncode, 2)
