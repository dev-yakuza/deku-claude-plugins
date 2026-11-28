"""U10 gitops: pinned git calls (S4), recorded-base ranges (S5), engine commit and push (§7.6).

Real git in temporary repositories with a local bare remote (tests/helpers/gitrepo.py).
"""

import json
import os
import stat
import tempfile
import unittest

from gxengine import gitops, schema
from tests.helpers import fakes
from tests.helpers.gitrepo import GitRepo, run_git

BRANCH = "gld/42-feature"


def _hook(dirpath, name, marker):
    """A hook that records it ran (touches `marker`) and fails."""
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.join(dirpath, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    os.chmod(p, 0o755)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gx-gitops-")
        self.tmp = os.path.realpath(self._tmp.name)
        self.repo = GitRepo.create(self.tmp, files={"README.md": "init\n", "src/a.py": "a = 1\n",
                                                    ".gitignore": "*.log\n"})
        self.base = self.repo.head()
        self.wt_path = os.path.join(self.tmp, ".gld-repo-42")
        self.ctx = gitops.create_issue_worktree(self.repo.path, self.wt_path, BRANCH, self.base,
                                                base_env=self.repo.env)
        self.wt = self.ctx.work_tree

    def tearDown(self):
        self._tmp.cleanup()

    def wcommit(self, files, message="work"):
        for rel, text in files.items():
            self.repo.write(rel, text, cwd=self.wt)
        return self.repo.commit(message, cwd=self.wt)


class CreateAndPin(Base):
    def test_recorded_paths_are_absolute_and_inside_the_common_dir(self):
        c = self.ctx
        self.assertEqual(c.common_dir, os.path.join(self.repo.path, ".git"))
        self.assertEqual(os.path.dirname(c.git_dir), os.path.join(c.common_dir, "worktrees"))
        self.assertTrue(os.path.isfile(os.path.join(c.git_dir, "HEAD")))
        self.assertEqual(c.work_tree, os.path.realpath(self.wt_path))
        self.assertEqual(c.main_checkout, self.repo.path)
        self.assertEqual(c.remote_url, self.repo.remote)
        self.assertEqual(c.branch, BRANCH)
        self.assertEqual(gitops.head(c), self.base)

    def test_state_round_trip_matches_the_state_schema(self):
        with open(fakes.fixture("contracts", "state.example.json"), encoding="utf-8") as f:
            state = json.load(f)
        state.update(self.ctx.state_fields())
        schema.validate(state, "state")
        again = gitops.GitContext.from_state(state, base_env=self.repo.env)
        self.assertEqual(again.state_fields(), self.ctx.state_fields())

    def test_from_state_refuses_relative_paths_and_ref_names(self):
        fields = self.ctx.state_fields()
        bad = json.loads(json.dumps(fields))
        bad["git"]["work_tree"] = "relative/wt"
        with self.assertRaises(gitops.GitError):
            gitops.GitContext.from_state(bad)
        bad = json.loads(json.dumps(fields))
        bad["base_sha"] = "main"
        with self.assertRaises(gitops.GitError):
            gitops.GitContext.from_state(bad)
        with self.assertRaises(gitops.GitError):
            gitops.GitContext.from_state({"base_sha": self.base})

    def test_create_refuses_a_ref_name_base_and_a_missing_remote(self):
        with self.assertRaises(gitops.GitError):
            gitops.create_issue_worktree(self.repo.path, os.path.join(self.tmp, "w2"), "gld/2", "main",
                                         base_env=self.repo.env)
        with self.assertRaises(gitops.GitError):
            gitops.create_issue_worktree(self.repo.path, os.path.join(self.tmp, "w3"), "gld/3", self.base,
                                         remote="nope", base_env=self.repo.env)
        for bad in ("-b", "refs/heads/x", "a b", "a..b", ""):
            with self.assertRaises(gitops.GitError, msg=bad):
                gitops.create_issue_worktree(self.repo.path, os.path.join(self.tmp, "w4"), bad, self.base,
                                             base_env=self.repo.env)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "w3")))

    def _other_worktree(self):
        """A second repository (with a linked worktree) the role would like the engine to use instead."""
        other = GitRepo.create(os.path.join(self.tmp, "o"), name="other", with_remote=False)
        other.add_worktree(os.path.join(self.tmp, "o", "owt"), "evil")
        return other

    def test_e6_tampered_gitfile_is_refused_before_git_runs(self):
        other = self._other_worktree()
        mine = self.wcommit({"src/b.py": "b = 1\n"})
        gitfile = os.path.join(self.wt, ".git")
        with open(gitfile, encoding="utf-8") as f:
            original = f.read()
        with open(gitfile, "w", encoding="utf-8") as f:
            f.write("gitdir: " + os.path.join(other.path, ".git", "worktrees", "owt") + "\n")
        # Plain git in the worktree now follows the tampered gitfile…
        self.assertEqual(run_git(self.wt, "rev-parse", "HEAD", env=self.repo.env), other.head())
        # …the engine refuses instead of following it.
        with self.assertRaises(gitops.Tampered):
            gitops.head(self.ctx)
        with self.assertRaises(gitops.Tampered):
            gitops.push(self.ctx, mine)
        self.assertIsNone(self.repo.remote_head(BRANCH))
        with open(gitfile, "w", encoding="utf-8") as f:
            f.write(original)
        self.assertEqual(gitops.head(self.ctx), mine)

    def test_e6_tampered_commondir_is_refused_before_git_runs(self):
        other = self._other_worktree()
        mine = self.wcommit({"src/b.py": "b = 1\n"})
        cd = os.path.join(self.ctx.git_dir, "commondir")
        with open(cd, encoding="utf-8") as f:
            original = f.read()
        with open(cd, "w", encoding="utf-8") as f:
            f.write(os.path.join(other.path, ".git") + "\n")
        for call in (lambda: gitops.head(self.ctx), lambda: gitops.changed_files(self.ctx, mine),
                     lambda: gitops.blob(self.ctx, self.base, "README.md"),
                     lambda: gitops.commit_paths(self.ctx, ["src/b.py"], "x")):
            with self.assertRaises(gitops.Tampered):
                call()
        os.unlink(cd)
        os.symlink(os.path.join(other.path, ".git", "worktrees", "owt", "commondir"), cd)
        with self.assertRaises(gitops.Tampered):
            gitops.head(self.ctx)
        os.unlink(cd)
        with open(cd, "w", encoding="utf-8") as f:
            f.write(original)
        self.assertEqual(gitops.head(self.ctx), mine)

    def test_e6_appeared_worktree_config_is_refused(self):
        with open(os.path.join(self.ctx.git_dir, "config.worktree"), "w", encoding="utf-8") as f:
            f.write("[core]\n\tsshCommand = false\n")
        with self.assertRaises(gitops.Tampered):
            gitops.head(self.ctx)

    def test_inherited_git_location_variables_are_dropped(self):
        env = dict(self.repo.env, GIT_DIR="/nonexistent", GIT_INDEX_FILE="/nonexistent/index",
                   GIT_CONFIG_PARAMETERS="'core.hookspath'='/tmp'")
        ctx = gitops.GitContext(**{**self.ctx.state_fields()["git"], "base_sha": self.base,
                                   "remote_url": self.ctx.remote_url, "branch": BRANCH, "base_env": env})
        self.assertEqual(gitops.head(ctx), self.base)
        e = ctx.env()
        self.assertNotIn("GIT_INDEX_FILE", e)
        self.assertNotIn("GIT_CONFIG_PARAMETERS", e)
        self.assertEqual(e["GIT_DIR"], self.ctx.git_dir)
        self.assertEqual(e["GIT_LITERAL_PATHSPECS"], "1")

    def test_repo_hooks_and_fsmonitor_never_run(self):
        hooks = os.path.join(self.tmp, "hooks")
        marker = os.path.join(self.tmp, "hook-ran")
        for name in ("pre-commit", "commit-msg", "post-commit", "pre-push", "reference-transaction",
                     "post-checkout"):
            _hook(hooks, name, marker)
        fsm = _hook(os.path.join(self.tmp, "fsm"), "monitor", marker + "-fsmonitor")
        self.repo.git("config", "core.hooksPath", hooks)
        self.repo.git("config", "core.fsmonitor", fsm)
        # sanity: plain git in the worktree does run them
        self.assertNotEqual(self.repo.git("commit", "--allow-empty", "-m", "x", cwd=self.wt, check=False).returncode, 0)
        self.repo.git("status", cwd=self.wt)
        self.assertTrue(os.path.exists(marker) and os.path.exists(marker + "-fsmonitor"))
        os.unlink(marker)
        os.unlink(marker + "-fsmonitor")
        self.repo.write("docs/x.md", "x\n", cwd=self.wt)
        sha = gitops.commit_paths(self.ctx, ["docs/x.md"], "engine: x")
        gitops.tree_state(self.ctx)
        self.assertEqual(gitops.push(self.ctx, sha), "*")
        gate = gitops.temp_tree_for_gate(self.ctx, sha, os.path.join(self.tmp, "gate"))
        gitops.remove_worktree(self.ctx, gate.work_tree)
        self.assertFalse(os.path.exists(marker), "a repository hook ran during an engine git call")
        self.assertFalse(os.path.exists(marker + "-fsmonitor"), "fsmonitor ran")

    def test_git_error_carries_rc_and_stderr(self):
        with self.assertRaises(gitops.GitError) as cm:
            gitops.git(self.ctx, "rev-parse", "--verify", "no-such-ref")
        self.assertEqual(cm.exception.returncode, 128)
        self.assertEqual(cm.exception.args_, ("rev-parse", "--verify", "no-such-ref"))
        p = gitops.git(self.ctx, "rev-parse", "--verify", "no-such-ref", check=False)
        self.assertEqual(p, "")


class Ranges(Base):
    def test_ref_names_are_refused_everywhere(self):
        for call in (lambda: gitops.merge_base(self.ctx, "HEAD"),
                     lambda: gitops.changed_files(self.ctx, "main"),
                     lambda: gitops.changed_between(self.ctx, "main", self.base),
                     lambda: gitops.commits_between(self.ctx, self.base, "HEAD~0"),
                     lambda: gitops.is_forward(self.ctx, "origin/main", self.base),
                     lambda: gitops.blob(self.ctx, "HEAD", "README.md"),
                     lambda: gitops.diff_text(self.ctx, "main"),
                     lambda: gitops.push(self.ctx, "HEAD")):
            with self.assertRaises(gitops.GitError):
                call()

    def test_changed_files_committed_worktree_untracked(self):
        self.repo.git("mv", "src/a.py", "src/renamed.py", cwd=self.wt)
        self.repo.write("src/new.py", "n = 1\n", cwd=self.wt)
        self.repo.git("rm", "-q", "README.md", cwd=self.wt)
        head = self.repo.commit("rename, add, delete", cwd=self.wt)
        self.repo.write(".gitignore", "*.log\n# more\n", cwd=self.wt)       # tracked, uncommitted
        self.repo.write("notes.txt", "n\n", cwd=self.wt)                    # untracked
        self.repo.write("debug.log", "ignored\n", cwd=self.wt)              # ignored → not listed
        got = gitops.changed_files(self.ctx, head)
        self.assertIn({"path": "src/renamed.py", "change": "renamed", "from": "src/a.py", "where": "committed"}, got)
        self.assertIn({"path": "src/new.py", "change": "added", "from": None, "where": "committed"}, got)
        self.assertIn({"path": "README.md", "change": "deleted", "from": None, "where": "committed"}, got)
        self.assertIn({"path": ".gitignore", "change": "modified", "from": None, "where": "worktree"}, got)
        self.assertIn({"path": "notes.txt", "change": "added", "from": None, "where": "untracked"}, got)
        self.assertNotIn("debug.log", [c["path"] for c in got])
        self.assertEqual(len(got), 5)
        for c in got:
            schema.validate({"path": c["path"], "change": c["change"], "from": c["from"], "where": c["where"]},
                            schema.load_schema("facts")["properties"]["changed_files"]["items"])
        self.assertEqual(gitops.changed_between(self.ctx, self.base, head),
                         ["README.md", "src/a.py", "src/new.py", "src/renamed.py"])

    def test_s5_range_is_from_the_recorded_sha_not_the_moving_main(self):
        head = self.wcommit({"src/b.py": "b\n"})
        # main moves on after the Issue started (someone merged elsewhere).
        self.repo.write("later.txt", "later\n")
        self.repo.commit("main moves")
        self.assertEqual(gitops.merge_base(self.ctx, head), self.base)
        self.assertEqual([c["path"] for c in gitops.changed_files(self.ctx, head)], ["src/b.py"])
        self.assertNotIn("later.txt", gitops.diff_text(self.ctx, head))

    def test_tree_state(self):
        self.assertEqual(gitops.tree_state(self.ctx), {"clean": True, "dirty_files": []})
        self.repo.write("src/a.py", "a = 2\n", cwd=self.wt)
        self.repo.write("z.txt", "z\n", cwd=self.wt)
        self.repo.write("x.log", "ignored\n", cwd=self.wt)
        self.assertEqual(gitops.tree_state(self.ctx), {"clean": False, "dirty_files": ["src/a.py", "z.txt"]})

    def test_commits_between_and_is_forward(self):
        a = self.wcommit({"a.txt": "a\n"}, "first\n\nbody line")
        b = self.wcommit({"b.txt": "b\n"}, "second")
        self.assertEqual(gitops.commits_between(self.ctx, self.base, b),
                         [{"sha": a, "subject": "first"}, {"sha": b, "subject": "second"}])
        self.assertEqual(gitops.commit_messages(self.ctx, b), [(a, "first\n\nbody line\n"), (b, "second\n")])
        self.assertTrue(gitops.is_forward(self.ctx, a, b))
        self.assertFalse(gitops.is_forward(self.ctx, b, a))
        self.repo.git("reset", "-q", "--hard", self.base, cwd=self.wt)
        c = self.wcommit({"c.txt": "c\n"}, "rewritten")
        self.assertFalse(gitops.is_forward(self.ctx, b, c))

    def test_diff_and_log_text(self):
        self.repo.git("mv", "src/a.py", "src/moved.py", cwd=self.wt)
        with open(os.path.join(self.wt, "bin.dat"), "wb") as f:
            f.write(b"\x00\x01binary-marker\x00\xff\n")
        head = self.repo.commit("move and binary\n\nwhy: because", cwd=self.wt)
        d = gitops.diff_text(self.ctx, head)
        self.assertIn("binary-marker", d)          # -a: binary shown as text
        self.assertIn("+a = 1", d)                 # --no-renames: the moved file's whole content
        self.assertNotIn("Binary files", d)
        log = gitops.log_text(self.ctx, head)
        self.assertEqual(log.splitlines()[:4], ["Engine Test", "engine-test@example.invalid",
                                                "move and binary", ""])
        self.assertIn("why: because", log)
        r = gitops.review_diff_text(self.ctx, head)   # review input: no binary bytes
        self.assertNotIn("binary-marker", r)
        self.assertIn("Binary files", r)
        self.assertIn("+a = 1", r)


class Blobs(Base):
    def test_blob_modes(self):
        os.symlink("README.md", os.path.join(self.wt, "link"))
        self.repo.write("tool.sh", "#!/bin/sh\n", cwd=self.wt)
        os.chmod(os.path.join(self.wt, "tool.sh"), 0o755)
        head = self.repo.commit("modes", cwd=self.wt)
        mode, sha, data = gitops.blob(self.ctx, self.base, "README.md")
        self.assertEqual((mode, data), ("100644", b"init\n"))
        self.assertEqual(len(sha), 40)
        self.assertTrue(gitops.is_regular_mode(mode))
        self.assertEqual(gitops.blob(self.ctx, head, "tool.sh")[0], "100755")
        mode, _, data = gitops.blob(self.ctx, head, "link")
        self.assertEqual((mode, data), ("120000", b"README.md"))
        self.assertFalse(gitops.is_regular_mode(mode))
        mode, _, data = gitops.blob(self.ctx, head, "src")
        self.assertEqual((mode, data), ("040000", None))
        self.assertIsNone(gitops.blob(self.ctx, self.base, "tool.sh"))     # absent at base
        self.assertIsNone(gitops.blob(self.ctx, head, "src/nope.py"))

    def test_blob_reads_the_commit_not_the_worktree(self):
        self.repo.write("README.md", "edited by a role\n", cwd=self.wt)
        self.assertEqual(gitops.blob(self.ctx, self.base, "README.md")[2], b"init\n")

    def test_blob_refuses_odd_paths(self):
        for p in ("../x", "/etc/passwd", "a/../b", "src/", "", ".git/config", "a//b", "./README.md"):
            with self.assertRaises(gitops.UnsafePath, msg=p):
                gitops.blob(self.ctx, self.base, p)

    def test_literal_pathspec(self):
        self.assertIsNone(gitops.blob(self.ctx, self.base, "*.md"))


class Commit(Base):
    def test_commits_exactly_the_paths(self):
        self.repo.write("docs/specs/42/design.md", "design\n", cwd=self.wt)
        self.repo.write("src/a.py", "a = 99\n", cwd=self.wt)
        self.repo.git("add", "src/a.py", cwd=self.wt)                   # staged by a role
        sha = gitops.commit_paths(self.ctx, ["docs/specs/42/design.md"], "engine: design output")
        self.assertEqual(gitops.head(self.ctx), sha)
        self.assertEqual(gitops.changed_between(self.ctx, self.base, sha), ["docs/specs/42/design.md"])
        self.assertIn("src/a.py", gitops.tree_state(self.ctx)["dirty_files"])   # still staged, not committed
        # unchanged → no new commit
        self.assertEqual(gitops.commit_paths(self.ctx, ["docs/specs/42/design.md"], "again"), sha)

    def test_refuses_symlinks_and_symlinked_parents(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "f.md"), "w") as f:
            f.write("x\n")
        os.symlink(os.path.join(outside, "f.md"), os.path.join(self.wt, "out.md"))
        os.symlink(outside, os.path.join(self.wt, "linkdir"))
        for p in ("out.md", "linkdir/f.md", "missing.md", "../outside/f.md"):
            with self.assertRaises(gitops.UnsafePath, msg=p):
                gitops.commit_paths(self.ctx, [p], "engine")
        self.assertEqual(gitops.head(self.ctx), self.base)

    def test_refuses_an_empty_list_or_message(self):
        self.repo.write("x.md", "x\n", cwd=self.wt)
        with self.assertRaises(gitops.GitError):
            gitops.commit_paths(self.ctx, [], "m")
        with self.assertRaises(gitops.GitError):
            gitops.commit_paths(self.ctx, ["x.md"], "  ")


class Push(Base):
    def test_push_new_then_up_to_date_then_fast_forward(self):
        a = self.wcommit({"a.txt": "a\n"})
        self.assertEqual(gitops.push(self.ctx, a), "*")
        self.assertEqual(self.repo.remote_head(BRANCH), a)
        self.assertEqual(gitops.push(self.ctx, a), "=")
        b = self.wcommit({"b.txt": "b\n"})
        self.assertEqual(gitops.push(self.ctx, b), " ")
        self.assertEqual(self.repo.remote_head(BRANCH), b)

    def test_e5_non_fast_forward_is_remote_diverged_and_never_forced(self):
        a = self.wcommit({"a.txt": "a\n"})
        gitops.push(self.ctx, a)
        theirs = self.repo.diverge_remote(BRANCH, "other.txt", "x")
        b = self.wcommit({"b.txt": "b\n"})
        with self.assertRaises(gitops.RemoteDiverged):          # "fetch first" form
            gitops.push(self.ctx, b)
        self.assertEqual(self.repo.remote_head(BRANCH), theirs)
        gitops.fetch(self.ctx)
        self.assertEqual(gitops.git(self.ctx, "rev-parse", "refs/remotes/origin/" + BRANCH).strip(), theirs)
        with self.assertRaises(gitops.RemoteDiverged):          # "non-fast-forward" form (objects known)
            gitops.push(self.ctx, b)
        self.assertEqual(self.repo.remote_head(BRANCH), theirs)

    def test_push_uses_the_recorded_url_not_the_configured_remote(self):
        decoy = os.path.join(self.tmp, "decoy.git")
        run_git(self.tmp, "init", "-q", "--bare", decoy, env=self.repo.env)
        self.repo.git("remote", "set-url", "origin", decoy)       # a role re-points origin
        a = self.wcommit({"a.txt": "a\n"})
        gitops.push(self.ctx, a)
        self.assertEqual(self.repo.remote_head(BRANCH), a)
        p = run_git(decoy, "rev-parse", "--verify", "-q", "refs/heads/" + BRANCH, env=self.repo.env, check=False)
        self.assertEqual(p.stdout.strip(), "")

    def test_push_refuses_a_remote_name_or_odd_urls(self):
        a = self.wcommit({"a.txt": "a\n"})
        for url in ("origin", "-oProxyCommand=x", "ext::sh -c id", "", None):
            self.ctx.remote_url = url
            with self.assertRaises(gitops.GitError, msg=repr(url)):
                gitops.push(self.ctx, a)
        self.assertIsNone(self.repo.remote_head(BRANCH))
        self.assertTrue(gitops.is_fixed_url("git@github.com:acme/app.git"))
        self.assertTrue(gitops.is_fixed_url("https://github.com/acme/app.git"))

    def test_remote_hook_refusal_is_a_git_error_not_divergence(self):
        hooks = os.path.join(self.tmp, "remote-hooks")
        _hook(hooks, "pre-receive", os.path.join(self.tmp, "remote-hook-ran"))
        run_git(self.repo.remote, "config", "core.hooksPath", hooks, env=self.repo.env)
        a = self.wcommit({"a.txt": "a\n"})
        try:
            gitops.push(self.ctx, a)
        except gitops.RemoteDiverged:
            self.fail("a declined push is not a divergence")
        except gitops.GitError:
            pass
        else:
            self.skipTest("this git does not run the bare remote's hooks over the local transport")
        self.assertIsNone(self.repo.remote_head(BRANCH))


class TempTrees(Base):
    def test_gate_tree_is_base_head_with_head_index(self):
        self.wcommit({"src/a.py": "a = 2\n", "src/c.py": "c\n"})
        self.repo.git("rm", "-q", "README.md", cwd=self.wt)
        head = self.repo.commit("rm", cwd=self.wt)
        gate = gitops.temp_tree_for_gate(self.ctx, head, os.path.join(self.tmp, "gate"))
        self.assertEqual(gitops.head(gate), self.base)
        cached = gitops.git(gate, "diff", "--cached", "--name-only").split()
        self.assertEqual(sorted(cached), gitops.changed_between(self.ctx, self.base, head))
        with open(os.path.join(gate.work_tree, "src", "a.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "a = 2\n")
        self.assertFalse(os.path.exists(os.path.join(gate.work_tree, "README.md")))
        self.assertIsNone(gate.remote_url)
        with self.assertRaises(gitops.GitError):
            gitops.push(gate, head)
        # the Issue worktree is untouched
        self.assertEqual(gitops.head(self.ctx), head)
        self.assertTrue(gitops.tree_state(self.ctx)["clean"])
        gitops.remove_worktree(self.ctx, gate.work_tree)
        self.assertFalse(os.path.exists(gate.work_tree))
        self.assertFalse(os.path.exists(gate.git_dir))

    def test_detached_base_tree_and_remove_refusals(self):
        t = gitops.detached_worktree(self.ctx, os.path.join(self.tmp, "base-run"), self.base)
        self.assertEqual(gitops.head(t), self.base)
        gitops.remove_worktree(self.ctx, t.work_tree)
        with self.assertRaises(gitops.GitError):
            gitops.remove_worktree(self.ctx, self.wt)
        with self.assertRaises(gitops.GitError):
            gitops.remove_worktree(self.ctx, self.repo.path)
        self.assertTrue(os.path.isdir(self.wt))
        with self.assertRaises(gitops.GitError):
            gitops.detached_worktree(self.ctx, self.wt, self.base)       # exists



class FastForward(Base):
    """Stage 3 V13 (E31): resume --pr-review fetches and fast-forwards a human's commits only."""

    def pushed(self):
        sha = self.wcommit({"src/a.py": "a = 2\n"}, "engine work")
        gitops.push(self.ctx, sha)
        return sha

    def test_remote_ahead_is_fast_forwarded(self):
        local = self.pushed()
        remote = self.repo.diverge_remote(BRANCH, "src/human.py", "h = 1\n")
        got = gitops.fast_forward(self.ctx)
        self.assertEqual(got, {"from": local, "to": remote, "commits": 1})
        self.assertEqual(gitops.head(self.ctx), remote)
        with open(os.path.join(self.wt, "src", "human.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "h = 1\n")
        self.assertIsNone(gitops.fast_forward(self.ctx), "a second call has nothing to do")

    def test_equal_behind_or_missing_is_none(self):
        self.assertIsNone(gitops.fast_forward(self.ctx), "the branch was never pushed")
        self.pushed()
        self.assertIsNone(gitops.fast_forward(self.ctx))
        self.wcommit({"src/b.py": "b\n"}, "local only")
        self.assertIsNone(gitops.fast_forward(self.ctx), "local ahead: the next push carries it")

    def test_diverged_is_refused(self):
        self.pushed()
        self.repo.diverge_remote(BRANCH, "src/human.py", "h\n")
        before = self.wcommit({"src/b.py": "b\n"}, "local only")
        with self.assertRaises(gitops.Diverged) as cm:
            gitops.fast_forward(self.ctx)
        self.assertIsInstance(cm.exception, gitops.GitError)
        self.assertEqual(gitops.head(self.ctx), before)

    def test_dirty_tree_is_refused(self):
        local = self.pushed()
        self.repo.diverge_remote(BRANCH, "src/human.py", "h\n")
        self.repo.write("src/a.py", "uncommitted\n", cwd=self.wt)
        with self.assertRaises(gitops.GitError):
            gitops.fast_forward(self.ctx)
        self.assertEqual(gitops.head(self.ctx), local)


if __name__ == "__main__":
    unittest.main()
