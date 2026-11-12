"""M1k (m1k-plan item 4): removing Studio from a repository with the commands of docs/removing.md, run as written —
the blocks are read from the English document (the Korean and Japanese ones must hold the same blocks). Two worktrees
of one clone: the clone's plain-git hook is a hand-written one Studio chained, the second worktree uses lefthook.
Steps 0 and 2–4 run (step 1 is Claude Code's `/plugin uninstall`); afterwards both worktrees commit, the hand-written
hook is back, nothing of Studio is left in either worktree or in the per-user folders, and a new init is not refused,
while the step-0 copies hold every video, render and backup."""

import os
import re
import shutil
import stat
import subprocess
import sys

import helpers
from stdo import machine, paths
from stdo.guard.repos import Repos
from stdo.guard.where import FS, Where
from stdo.hooks import templates as T
from stdo.setup import analyze, initcmd
from test_m1c import FAKE_ROOT, InitCase

DOCS = os.path.join(helpers.PLUGIN, "docs")
HAND_HOOK = '#!/bin/sh\necho ran >> "$(git rev-parse --git-common-dir)/hand-hook.log"\n'
OWN_HUSKY = '#!/bin/sh\necho own >> "$(git rev-parse --git-common-dir)/own-hook.log"\n'
LEFTHOOK = "pre-push:\n  commands:\n    lint:\n      run: echo lint\n"


def blocks(name):
    """{run label: the shell block that follows `<!-- run: <label> -->`} of one document."""
    with open(os.path.join(DOCS, name), encoding="utf-8") as f:
        text = f.read()
    return dict(re.findall(r"<!-- run: ([a-z-]+) -->\n```sh\n(.*?)```\n", text, re.S))


def tree(root):
    """{relative path: bytes} of every file under `root`."""
    out = {}
    for d, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = f.read()
    return out


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


class RemoveCase(InitCase):
    def run_block(self, cwd, *labels, check=True, shell="bash"):
        """The folders block, then the named blocks, in one shell process (one terminal), from `cwd`."""
        script = "".join(blocks("removing.md")[l] for l in ("folders",) + labels)
        r = subprocess.run([shell, "-c", script], cwd=cwd, capture_output=True, text=True, env=dict(os.environ),
                           timeout=120)
        if check:
            self.assertEqual(r.returncode, 0, "%s: %s%s" % (labels, r.stdout, r.stderr))
        return r.stdout if check else r


class Documents(RemoveCase):
    def test_the_three_languages_hold_the_same_commands(self):
        en = blocks("removing.md")
        self.assertEqual(sorted(en), ["backups-clone", "backups-worktree", "clone", "folders", "hook-status", "keep",
                                      "worktree"])
        for n in ("removing.ko.md", "removing.ja.md"):
            self.assertEqual(blocks(n), en, n)

    def test_the_folders_block_uses_studios_keys(self):
        """The key formula inlined in the document is the scripts' (paths.repo_key / common_key / marker)."""
        self.init()
        out = self.run_block(self.repo, "folders")
        self.assertIn("studio_root:   studio\n", out)
        self.assertIn("this worktree: %s\n" % os.path.join(paths.backup_root(), paths.repo_key(self.repo)), out)
        self.assertIn("this clone:    %s\n" % os.path.dirname(paths.marker_path(self.repo)), out)


class Removing(RemoveCase):
    def setUp(self):
        super().setUp()
        self.hooks = os.path.join(self.repo, ".git", "hooks")
        write(os.path.join(self.hooks, "pre-commit"), HAND_HOOK)
        os.chmod(os.path.join(self.hooks, "pre-commit"), 0o755)
        self.init()
        self.commit_all()
        sr = os.path.join(self.repo, "studio")
        # a tracked video with a local change, a local video, a render, texts, ignored leftovers
        write(os.path.join(sr, "videos", "v1", "script.md"), "# v1\n")
        self.commit_all("video v1")
        write(os.path.join(sr, "videos", "v1", "script.md"), "# v1, changed here\n")
        write(os.path.join(sr, "videos", "v1", "work", "state.json"), "{}\n")
        write(os.path.join(sr, "local", "videos", "v2", "script.md"), "# v2 (local)\n")
        write(os.path.join(sr, "out", "v1", "youtube.mp4"), "mp4")
        write(os.path.join(sr, "copy", "v1", "youtube.md"), "title\n")
        # a video that exists only as a backup
        self.backup = os.path.join(paths.backup_root(), paths.repo_key(self.repo))
        write(os.path.join(self.backup, "videos", "v3", "copy.1", "script.md"), "# v3 (backup only)\n")
        # the second worktree: lefthook, its own machine file and backup (a new worktree: m1k-plan item 4)
        self.wt = os.path.join(self.tmp, "wt2")
        helpers.git(self.repo, "worktree", "add", "-q", "-b", "two", self.wt)
        write(os.path.join(self.wt, "lefthook.yml"), LEFTHOOK)
        helpers.git(self.wt, "add", "lefthook.yml")
        helpers.git(self.wt, "commit", "-q", "--no-verify", "-m", "lefthook")
        machine.write(self.wt, FAKE_ROOT)
        r = subprocess.run([sys.executable, "-B", os.path.join(self.wt, ".claude", "studio", "scripts", "hooks.py"),
                            "install"], cwd=self.wt, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lefthook", r.stdout)
        write(os.path.join(self.wt, "studio", "local", "videos", "w1", "script.md"), "# w1 (local)\n")
        self.wt_backup = os.path.join(paths.backup_root(), paths.repo_key(self.wt))
        write(os.path.join(self.wt_backup, "videos", "w2", "copy.1", "script.md"), "# w2 (backup only)\n")
        self.common_backup = os.path.dirname(paths.marker_path(self.repo))

    def test_fixture(self):
        self.assertTrue(os.path.isfile(os.path.join(self.wt, "lefthook-local.yml")))
        self.assertIn(T.MARK, read(os.path.join(self.hooks, "pre-commit")))
        self.assertEqual(read(os.path.join(self.hooks, T.CHAINED)), HAND_HOOK)
        for top in (self.repo, self.wt):
            self.assertTrue(self.info(top).studio, top)
            self.assertIsNotNone(initcmd.existing(top))

    def info(self, top):
        w = Where(FS(), dict(os.environ))
        return Repos(w, dict(os.environ)).info(w.git_repo(top))

    def test_removal_as_written(self):
        before = {top: tree(os.path.join(top, "studio")) for top in (self.repo, self.wt)}
        backups = {self.repo: tree(self.backup), self.wt: tree(self.wt_backup)}
        common = tree(self.common_backup)
        # macOS's default shell runs the second worktree's blocks (bash, often 3.2 there, the first's)
        sh = {self.repo: "bash", self.wt: "zsh" if shutil.which("zsh") else "bash"}
        internal = read(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"))
        # step 0, in every worktree
        for top in (self.repo, self.wt):
            self.run_block(top, "keep", shell=sh[top])
            self.assertIn("Studio hook (", self.run_block(top, "hook-status", check=False, shell=sh[top]).stdout)
        # step 2, once; step 3 and the worktree's backups (step 4), in each worktree; the clone's backups last
        self.run_block(self.wt, "clone", shell=sh[self.wt])
        for top in (self.repo, self.wt):
            self.run_block(top, "worktree", shell=sh[top])
            self.run_block(top, "backups-worktree", shell=sh[top])
        self.run_block(self.repo, "backups-clone")

        # the commits went through the hand-written hook, which is back and executable
        hook = os.path.join(self.hooks, "pre-commit")
        self.assertEqual(read(hook), HAND_HOOK)
        self.assertTrue(os.stat(hook).st_mode & stat.S_IXUSR)
        self.assertFalse(os.path.exists(os.path.join(self.hooks, T.CHAINED)))
        with open(os.path.join(self.repo, ".git", "hand-hook.log")) as f:
            self.assertEqual(f.read(), "ran\nran\n")
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "studio")))
        with open(os.path.join(self.repo, ".git", "info", "exclude")) as f:
            self.assertNotIn("studio", f.read())
        for top in (self.repo, self.wt):
            self.assertEqual(helpers.git(top, "log", "-1", "--format=%s").stdout.strip(), "Remove Studio")
            self.assertFalse(os.path.exists(os.path.join(top, "lefthook-local.yml")))
            st = helpers.git(top, "status", "--porcelain", "--ignored").stdout
            self.assertEqual(st, "", top)
            files = helpers.git(top, "ls-files").stdout.split()
            self.assertEqual([f for f in files if "studio" in f or "std-" in f], [], top)
            self.assertFalse(self.info(top).studio, top)
            self.assertIsNone(analyze.studio_root_free(top, "studio"))
            self.assertIsNone(initcmd.existing(top))
        self.assertFalse(os.path.exists(self.backup) or os.path.exists(self.wt_backup)
                         or os.path.exists(self.common_backup))
        self.assertTrue(os.path.isfile(os.path.join(self.wt, "lefthook.yml")))
        # a new init is not refused
        self.init()
        # the copies of step 0
        for top in (self.repo, self.wt):
            keep = os.path.join(os.environ["HOME"], "studio-kept", paths.repo_key(top))
            self.assertEqual(tree(os.path.join(keep, "studio-root")), before[top], top)
            self.assertEqual(tree(os.path.join(keep, "studio-backup-worktree")), backups[top], top)
            self.assertEqual(tree(os.path.join(keep, "studio-backup-clone")), common, top)
        kept = os.path.join(os.environ["HOME"], "studio-kept", paths.repo_key(self.repo))
        self.assertEqual(before[self.repo]["videos/v1/script.md"], b"# v1, changed here\n")
        for rel in ("local/videos/v2/script.md", "out/v1/youtube.mp4", "copy/v1/youtube.md"):
            self.assertIn(rel, before[self.repo])
        self.assertIn("videos/v3/copy.1/script.md", backups[self.repo])
        self.assertIn("marker", common)
        with open(os.path.join(kept, "config.internal.json")) as f:
            self.assertEqual(f.read(), internal)

    def test_keep_refuses_an_existing_folder(self):
        self.run_block(self.repo, "keep")
        self.assertNotEqual(self.run_block(self.repo, "keep", check=False).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(os.environ["HOME"], "studio-kept", paths.repo_key(self.repo),
                                                     "studio-root", "studio")))

    def test_pre_commit_framework_installed_again(self):
        """pre-commit moved Studio's shim to pre-commit.legacy: the shim goes and the hand-written hook Studio had
        chained becomes the legacy hook."""
        os.replace(os.path.join(self.hooks, "pre-commit"), os.path.join(self.hooks, "pre-commit.legacy"))
        write(os.path.join(self.hooks, "pre-commit"), "#!/bin/sh\n# File generated by pre-commit\nexit 0\n")
        self.run_block(self.repo, "clone")
        self.assertEqual(read(os.path.join(self.hooks, "pre-commit.legacy")), HAND_HOOK)
        self.assertIn("File generated by pre-commit", read(os.path.join(self.hooks, "pre-commit")))
        self.assertFalse(os.path.exists(os.path.join(self.hooks, T.CHAINED)))


class TrackedHook(RemoveCase):
    """husky (core.hooksPath=.husky): the tracked .husky/pre-commit carries the Studio block (its studio:hook marker
    too) — step 2 leaves it as it is (it is not Studio's shim, and it is tracked), and step 3's commit still runs it."""

    def test_husky_file_is_left_and_runs(self):
        husky = os.path.join(self.repo, ".husky", "pre-commit")
        write(husky, OWN_HUSKY)
        os.chmod(husky, 0o755)
        write(os.path.join(self.repo, "package.json"), '{"devDependencies": {"husky": "9.1.7"}}\n')
        helpers.git(self.repo, "config", "core.hooksPath", ".husky")
        self.commit_all("husky")
        self.init(husky=True)
        self.commit_all()
        text = read(husky)
        self.assertIn(T.husky_block(), text)
        self.assertTrue(text.startswith(OWN_HUSKY))
        self.assertIn("Studio hook (husky)", self.run_block(self.repo, "hook-status", check=False).stdout)
        self.run_block(self.repo, "clone")
        self.assertEqual(read(husky), text)
        self.assertTrue(os.stat(husky).st_mode & stat.S_IXUSR)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "studio")))
        self.run_block(self.repo, "worktree")
        with open(os.path.join(self.repo, ".git", "own-hook.log")) as f:
            self.assertEqual(f.read(), "own\n")
        self.assertEqual(helpers.git(self.repo, "log", "-1", "--format=%s").stdout.strip(), "Remove Studio")
        self.assertEqual(read(husky), text)
        self.assertEqual(helpers.git(self.repo, "status", "--porcelain").stdout, "")


class Refusals(RemoveCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.commit_all()

    def test_staged_changes_are_refused(self):
        write(os.path.join(self.repo, "notes.md"), "mine\n")
        helpers.git(self.repo, "add", "notes.md")
        r = self.run_block(self.repo, "worktree", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already staged", r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.repo, ".claude", "studio")))

    def test_unpaired_gitignore_markers_are_refused(self):
        gi = os.path.join(self.repo, ".gitignore")
        text = read(gi).replace("# <<< studio <<<\n", "") + "/build/\n"
        write(gi, text)
        r = self.run_block(self.repo, "worktree", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unpaired", r.stderr)
        self.assertEqual(read(gi), text)
        self.assertTrue(os.path.isdir(os.path.join(self.repo, ".claude", "studio")))

    def test_settings_change_is_committed(self):
        s = os.path.join(self.repo, ".claude", "settings.json")
        write(s, '{"enabledPlugins": {"studio-plugin@deku-claude-plugins": true}}\n')
        helpers.git(self.repo, "add", ".claude/settings.json")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "enable")
        write(s, '{"enabledPlugins": {}}\n')
        self.run_block(self.repo, "clone")
        self.run_block(self.repo, "worktree")
        self.assertEqual(helpers.git(self.repo, "show", "HEAD:.claude/settings.json").stdout, '{"enabledPlugins": {}}\n')
        self.assertEqual(helpers.git(self.repo, "status", "--porcelain").stdout, "")
