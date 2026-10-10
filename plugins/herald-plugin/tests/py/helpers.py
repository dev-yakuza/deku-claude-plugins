"""Test fixture: a throwaway git repo with a bare origin, a Herald config, and a fake gh."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "..", "skills", "hrd", "scripts"))
sys.path.insert(0, SCRIPTS)

from hrdlib.config import Config  # noqa: E402

CONFIG = {
    "version": 1,
    "language": "en",
    "base_branch": "main",
    "paths": {"content": "src/content/blog", "body_pattern": "{content}/{slug}.md",
              "images": "public/blog-images", "build_inputs": ["src", "public"]},
    "site": {"base_url": "https://example.test", "url_pattern": "/blog/{slug}/"},
    "commands": {"deploy": "npm run deploy", "deploy_artifacts": ["scripts/share-status.json"]},
    "autonomy": {"publish": "approve", "throttle": {"max_per_day": 2}},
}

ARTICLE = """---
title: Hello
description: d
slug: {slug}
date: 2026-10-10
category: guide
---
Body text for {slug}. ![x](/blog-images/{slug}/01.png)
"""


def sh(cwd, *args, check=True, env=None):
    p = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise AssertionError("%s failed: %s" % (" ".join(args), p.stderr))
    return p.stdout


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hrd-test-")
        self.origin = os.path.join(self.tmp, "origin.git")
        self.root = os.path.join(self.tmp, "repo")
        sh(self.tmp, "git", "init", "-q", "--bare", "-b", "main", self.origin)
        sh(self.tmp, "git", "init", "-q", "-b", "main", self.root)
        for k, v in (("user.email", "t@example.test"), ("user.name", "t"), ("commit.gpgsign", "false")):
            sh(self.root, "git", "config", k, v)
        sh(self.root, "git", "remote", "add", "origin", self.origin)
        self.write(".gitignore", "public/blog-images/**/*.webp\n.claude/herald/memory/\n.claude/herald/ledger/\n.claude/herald/signals.jsonl\n")
        self.write(".claude/herald/config.json", json.dumps(CONFIG))
        self.write("scripts/share-status.json", "{}\n")
        self.write("src/content/blog/old-post.md", ARTICLE.format(slug="old-post"))
        self.commit("init")
        sh(self.root, "git", "push", "-q", "-u", "origin", "main")
        self.gh_state = os.path.join(self.tmp, "gh.json")
        with open(self.gh_state, "w") as f:
            json.dump({"prs": []}, f)
        os.environ["HRD_GH"] = os.path.join(HERE, "fake_gh.py")
        os.environ["HRD_FAKE_GH_STATE"] = self.gh_state
        os.environ["CLAUDE_PROJECT_DIR"] = self.root
        os.environ.pop("HRD_UNATTENDED", None)
        os.environ.pop("HRD_LOCK_TOKEN", None)
        os.environ.pop("HRD_AUTO_PRS", None)
        self.cfg = Config.load(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def write(self, rel, text, binary=False):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb" if binary else "w") as f:
            f.write(text)

    def commit(self, msg, *paths):
        sh(self.root, "git", "add", "-A", *(["--"] + list(paths) if paths else []))
        sh(self.root, "git", "commit", "-q", "-m", msg)
        return sh(self.root, "git", "rev-parse", "HEAD").strip()

    def article(self, slug, extra=""):
        self.write("src/content/blog/%s.md" % slug, ARTICLE.format(slug=slug) + extra)
        self.write("public/blog-images/%s/01.png" % slug, b"\x89PNG fake", binary=True)

    def set_prs(self, prs):
        with open(self.gh_state, "w") as f:
            json.dump({"prs": prs}, f)

    def gh_prs(self):
        with open(self.gh_state) as f:
            return json.load(f)["prs"]

    def hrd(self, *args, check=True, env=None):
        e = dict(os.environ)
        e.update(env or {})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "hrd.py"), *args], cwd=self.root,
                           capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL, timeout=60)
        if check and p.returncode != 0:
            raise AssertionError("hrd %s failed: %s" % (" ".join(args), p.stderr))
        return json.loads(p.stdout) if p.stdout.strip() else None, p
