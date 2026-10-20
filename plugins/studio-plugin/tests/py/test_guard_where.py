"""M0d-1a path resolution and git discovery (m0d1a-plan §7, §10.1, §10.11)."""

import os
import unicodedata

import helpers
from guard_base import GuardCase
from stdo import guard, paths
from stdo.guard.where import FS, Where


class Paths(GuardCase):
    def where(self):
        return Where(FS(), self.env)

    def test_lexical(self):
        w = self.where()
        r = w.resolve("a/../b//c/", self.root)
        self.assertEqual(r.abs, os.path.join(self.root, "b", "c"))
        self.assertIsNone(w.resolve("x", None).abs)
        self.assertEqual(w.resolve("/abs/x", None).abs, "/abs/x")

    def test_symlinks_and_private_tmp(self):
        self.mk("t", "inner")
        os.symlink(os.path.join(self.root, "t"), os.path.join(self.root, "l"))
        r = self.where().resolve("l/inner/new.txt", self.root)
        self.assertEqual(r.real, os.path.join(os.path.realpath(self.root), "t", "inner", "new.txt"))
        if os.path.realpath("/tmp") != "/tmp":
            self.assertTrue(self.where().resolve("/tmp", "/").real.startswith("/private/"))

    def test_nearest_existing_ancestor(self):
        self.mk("studio")
        r = self.where().resolve("studio/new/deep/f", self.root)
        self.assertEqual((r.anchor, r.tail, r.exists), (os.path.join(self.root, "studio"), "new/deep/f", False))

    def test_git_repos_match_git(self):
        repo = helpers.make_repo(self.tmp, name="r1", harness=False)
        wt = os.path.join(self.tmp, "wt")
        helpers.git(repo, "commit", "--allow-empty", "-m", "x")
        helpers.git(repo, "worktree", "add", "-q", wt)
        sub_src = helpers.make_repo(self.tmp, name="subsrc", harness=False)
        helpers.git(sub_src, "commit", "--allow-empty", "-m", "s")
        helpers.git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub_src, "mod")
        w = self.where()
        for path in (repo, wt, os.path.join(repo, "mod")):
            g = w.git_repo(path)
            self.assertIsNotNone(g, path)
            common = helpers.git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
            self.assertEqual(g.common_dir, os.path.realpath(common), path)
            self.assertEqual(g.worktree, os.path.realpath(path))
            self.assertEqual(paths._key(g.common_dir), paths.common_key(path))
        self.assertIsNone(w.git_repo(self.tmp))

    def test_case_and_unicode_keys(self):
        self.mk("Studio")
        w = self.where()
        ci = w.case_insensitive(os.path.join(self.root, "Studio"))
        k1 = w.cmp_key(os.path.join(self.root, "Studio"))
        k2 = w.cmp_key(os.path.join(self.root, "studio"))
        self.assertEqual(k1 == k2, ci)
        nfc = unicodedata.normalize("NFC", "한")
        nfd = unicodedata.normalize("NFD", "한")
        self.assertEqual(w.cmp_key("/x/" + nfc), w.cmp_key("/x/" + nfd))

    def test_stat_error(self):
        d = self.mk("locked")
        self.mk("locked", "inner")
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o755)
        r = self.where().resolve("locked/inner/f", self.root)
        if os.geteuid() != 0:
            self.assertTrue(r.stat_error)

    def test_path_class(self):
        w = self.where()
        self.assertEqual(w.path_class("/tmp/x", self.env), ["tmp"])
        self.assertEqual(w.path_class("/private/var/folders/ab/T/x", self.env), ["tmp"])
        self.assertEqual(w.path_class("/private/tmp/claude-1/k/s/scratchpad/x.sh", self.env), ["scratch"])
        os.makedirs(os.path.join(self.root, ".git"))
        cls = w.path_class(os.path.join(os.path.realpath(self.root), "x"), self.env)
        self.assertEqual(cls[0], "repo:" + os.path.realpath(self.root))
        if os.path.realpath(self.root).startswith(("/private/var/folders", "/tmp", "/private/tmp", "/var/folders")):
            self.assertIn(cls[1], ("tmp", "scratch"))  # both apply: a sandbox repository under a temp folder

    def test_public_resolve(self):
        r = guard.resolve_path("a", self.root, self.env)
        self.assertEqual(r.abs, os.path.join(self.root, "a"))


class PlanCases(GuardCase):
    """00-plan §3.4 "M0 테스트" — the scanner's part."""

    def setUp(self):
        super().setUp()
        self.studio = helpers.make_repo(self.tmp, name="studio-repo", harness=False)
        os.makedirs(os.path.join(self.studio, "studio", "work"))
        self.other = helpers.make_repo(self.tmp, name="other-repo", harness=False)

    def test_absolute_write_from_another_repo(self):
        r = self.ok("cp a %s/studio/work/state.json" % self.studio, cwd=self.other)
        c = self.one(r, "cp")
        self.assertEqual(c.cwds, [self.other])
        res = guard.resolve_path(c.argv[-1], c.cwds[0], self.env)
        self.assertEqual(res.repo.worktree, os.path.realpath(self.studio))

    def test_git_c_commit_from_another_repo(self):
        r = self.ok("git -C %s commit -m x" % self.studio, cwd=self.other)
        c = self.one(r, "git")
        self.assertEqual((c.git.sub, c.run_cwds), ("commit", [self.studio]))

    def test_new_file_in_studio_repo(self):
        r = self.ok("touch %s/studio/new/deep/f" % self.studio, cwd=self.other)
        res = guard.resolve_path(self.one(r, "touch").argv[1], self.other, self.env)
        self.assertEqual(res.anchor, os.path.join(self.studio, "studio"))
        self.assertEqual(res.repo.worktree, os.path.realpath(self.studio))

    def test_owner_json_with_and_without_state_dir(self):
        st = self.env["S2V_STATE_DIR"]
        r = self.ok("cat $S2V_STATE_DIR/heavy.lock.d/owner.json")
        self.assertEqual(self.one(r, "cat").argv[1], st + "/heavy.lock.d/owner.json")
        del self.env["S2V_STATE_DIR"]
        r = self.ok("cat ~/.s2v/heavy.lock.d/owner.json")
        self.assertEqual(self.one(r, "cat").argv[1], self.env["HOME"] + "/.s2v/heavy.lock.d/owner.json")

    def test_git_clean_flags_and_reset(self):
        for cmd, sub, args in (("git clean -fdx", "clean", ["-fdx"]), ("git clean -fd src/", "clean", ["-fd", "src/"]),
                               ("git reset --hard", "reset", ["--hard"]), ("git checkout -f", "checkout", ["-f"]),
                               ("git switch --discard-changes main", "switch", ["--discard-changes", "main"])):
            g = self.one(self.ok(cmd, cwd=self.studio), "git").git
            self.assertEqual((g.sub, [w.value for w in g.args]), (sub, args), cmd)

    def test_s2v_in_repo_without_harness(self):
        r = self.ok("s2v tts x.md", cwd=self.other)
        c = self.one(r, "s2v")
        self.assertIsNotNone(c.s2v)
        self.assertEqual(guard.resolve_path("x.md", self.other, self.env).repo.worktree, os.path.realpath(self.other))
