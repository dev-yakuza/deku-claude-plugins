"""Shared setup for the M0e tests (m0e-plan §12): a harness repository in a temporary folder with the
repository copy of Studio's scripts, the hook installed, and helpers for the internal overlay, an approved
video state, the guard-ran record and real `git commit` runs. Real git only in temporary repositories."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo import paths
from stdo.commit import kinds
from stdo.state import store

SID = "sess-commit-1"


def copy_scripts(repo):
    dst = os.path.join(repo, ".claude", "studio", "scripts")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(helpers.SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__", "guard.py", "guard"))
    return dst


class CommitCase(StudioTestCase):
    studio_root = "studio"
    install_hook = True

    def setUp(self):
        super().setUp()
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp, harness=True, studio_root=self.studio_root)
        copy_scripts(self.repo)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "scripts")
        # python3 for the hook = the interpreter running the tests (PY=/usr/bin/python3 checks 3.9)
        self.pybin = os.path.join(self.tmp, "pybin")
        os.makedirs(self.pybin)
        os.symlink(sys.executable, os.path.join(self.pybin, "python3"))
        self.env = dict(os.environ)
        self.env["PATH"] = self.pybin + os.pathsep + self.env.get("PATH", "")
        self.env[kinds.TEST_ENV] = "1"
        if self.install_hook:
            out = self.hooks("install")
            self.assertEqual(out.returncode, 0, out.stderr + out.stdout)

    # --- running things ---
    def git(self, *args, check=True, env=None, cwd=None):
        out = subprocess.run(["git", "-C", cwd or self.repo] + list(args), capture_output=True, text=True,
                             env=env or getattr(self, "env", None) or os.environ)
        if check and out.returncode != 0:
            raise AssertionError("git %s: %s%s" % (" ".join(args), out.stdout, out.stderr))
        return out

    def script(self, name, *args, env=None, cwd=None):
        return subprocess.run([sys.executable, "-B", os.path.join(self.repo, ".claude", "studio", "scripts", name)]
                              + list(args), cwd=cwd or self.repo, capture_output=True, text=True,
                              env=env or self.env)

    def cc(self, *args, env=None, cwd=None):
        return self.script("check_commit.py", *args, env=env, cwd=cwd)

    def hooks(self, *args, env=None, cwd=None):
        return self.script("hooks.py", *args, env=env, cwd=cwd)

    def commit(self, msg="m", *extra, env=None, cwd=None):
        return self.git("commit", "-q", "-m", msg, *extra, check=False, env=env, cwd=cwd)

    def claude_env(self, sid=SID):
        e = dict(self.env)
        e["CLAUDECODE"] = "1"
        e["CLAUDE_CODE_SESSION_ID"] = sid
        return e

    # --- files ---
    def write(self, rel, text="x\n", repo=None):
        p = os.path.join(repo or self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        return p

    def read(self, rel, repo=None):
        with open(os.path.join(repo or self.repo, rel)) as f:
            return f.read()

    def overlay(self, repo=None, wrong=False):
        repo = repo or self.repo
        p = self.write(".claude/studio/local/config.internal.json", '{"internal": []}\n', repo)
        with open(p, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        d = os.path.join(paths.backup_root(), paths.repo_key(repo))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "overlay.sha"), "w") as f:
            f.write(("0" * 64 if wrong else sha) + "\n")

    def guard_ran(self, sid=SID, repo=None):
        p = self.write(".claude/studio/local/guard-ran.json",
                       json.dumps({"schema": 1, "sessions": {sid: "2026-10-21T00:00:00Z"}}), repo)
        return p

    def video(self, vid="v1", proxy=False, skip_gate=None, repo=None):
        """An approved public video: state + approvals through store (events included) + a script."""
        repo = repo or self.repo
        vdir = os.path.join(repo, self.studio_root, "videos", vid)
        os.makedirs(vdir, exist_ok=True)
        st = F.state()
        st["video"] = vid
        store.create(vdir, st)
        c = F.current()
        for gate, key in (("1", None), ("2", None), ("3", "youtube"), ("4a", "youtube"), ("4b", "youtube")):
            if gate == skip_gate:
                continue
            rec = {"tuple": F.literal_tuple(gate, c, key if gate in ("3", "4a") else None,
                                            key if gate == "4b" else None, ["youtube"]),
                   "hash_version": 1, "s2v_id": st["s2v"]["id"], "approved_by": "proxy" if proxy else "human",
                   "answer": {"answer": "승인 x"}, "at": "2026-10-21T00:00:00Z"}
            if gate in ("1", "4b"):
                rec["excerpts"] = []
            store.record_approval(vdir, "ko", gate, rec, key)
        self.write(os.path.join(self.studio_root, "videos", vid, "script.ko.md"), "# script\n", repo)
        return vdir

    @staticmethod
    def exe(path, text):
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def ready(self, repo=None):
        """Overlay + approved video v1: what `--stage test v1` needs."""
        self.overlay(repo)
        return self.video(repo=repo)
