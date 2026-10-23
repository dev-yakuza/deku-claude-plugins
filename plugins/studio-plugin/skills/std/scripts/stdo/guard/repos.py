"""Which repositories a call touches and whether they are Studio repositories (m0d1b-plan §4)."""

import hashlib
import json
import os

from .. import paths
from . import protect
from .terms import Terms

LOCK_VARS = ("S2V_STATE_DIR", "S2V_HEAVY_LOCK_TOKEN", "S2V_ACTOR_LOCK_TOKEN", "S2V_TTS_PORT", "S2V_ALIGNER_PORT",
             "S2V_TTS", "S2V_TAKES_ALL")
STUDIO_WORDS = ("s2v", "state.py", "lock.py", "check_commit.py", "run_s2v.py", "STUDIO_SANDBOX", "STUDIO_HOME") + LOCK_VARS


class RepoInfo(object):
    def __init__(self, repo):
        self.worktree = repo.worktree
        self.common_dir = repo.common_dir
        self.git_dir = repo.git_dir
        self.harness = False
        self.marker = None
        self.config = {}
        self.config_error = None
        self.studio_root = "studio"
        self.local_exists = False

    @property
    def studio(self):
        return self.harness or self.marker is not None or self.local_exists

    @property
    def protected_keys(self):
        fixed = {"visibility", "internal_overlay", "public_domains", "web_roots", "allow_internal_commits", "s2v",
                 "models", "gates", "roles", "studio_root", "protected_keys"}
        more = self.config.get("protected_keys") if isinstance(self.config, dict) else None
        return fixed | set(k for k in (more or []) if isinstance(k, str))


def marker_key(common_dir):
    """paths.common_key() without running git: the hash of the real common dir (parity-tested)."""
    return hashlib.sha256(os.path.realpath(common_dir).encode("utf-8")).hexdigest()[:16]


class Repos(object):
    """RepoInfo per worktree, cached for one hook call."""

    def __init__(self, where, env):
        self.where = where
        self.env = env
        self.cache = {}

    def info(self, repo):
        if repo is None:
            return None
        if repo.worktree in self.cache:
            return self.cache[repo.worktree]
        ri = RepoInfo(repo)
        fs = self.where.fs
        cfg = os.path.join(repo.worktree, ".claude", "studio", "config.json")
        if fs.exists(cfg):
            ri.harness = True
            try:
                with open(cfg, encoding="utf-8") as f:
                    ri.config = json.load(f)
                if not isinstance(ri.config, dict):
                    raise ValueError("not an object")
                sr = ri.config.get("studio_root") or "studio"
                ri.studio_root = sr.strip("/") if isinstance(sr, str) and sr.strip("/") else "studio"
            except (OSError, ValueError) as e:
                ri.config, ri.config_error = {}, str(e)
        try:
            mpath = os.path.join(paths.backup_root(self.env), marker_key(repo.common_dir), "marker")
        except ValueError:
            mpath = None
        if mpath and fs.isfile(mpath):
            try:
                with open(mpath, encoding="utf-8") as f:
                    ri.marker = json.load(f) or {}
            except (OSError, ValueError):
                ri.marker = {}
            if not ri.harness and isinstance(ri.marker, dict) and isinstance(ri.marker.get("studio_root"), str):
                ri.studio_root = ri.marker["studio_root"].strip("/") or "studio"
        ri.local_exists = fs.isdir(os.path.join(repo.worktree, ri.studio_root, "local")) or \
            fs.isdir(os.path.join(repo.worktree, ".claude", "studio", "local"))
        self.cache[repo.worktree] = ri
        return ri

    def of_path(self, abs_path):
        if abs_path is None:
            return None
        r = self.where.resolve(abs_path, None)
        return self.info(r.repo) if r is not None and r.repo is not None else None


def terms_for(infos, fold):
    roots = sorted({ri.studio_root for ri in infos} | {"studio"})
    return Terms(words=STUDIO_WORDS, paths=roots + [".claude/studio"], names=protected_names_cached(), fold=fold)


_NAMES = None


def protected_names_cached():
    global _NAMES
    if _NAMES is None:
        _NAMES = protect.protected_names()
    return _NAMES


def has_exclude_block(ri):
    p = os.path.join(ri.common_dir, "info", "exclude")
    try:
        with open(p, encoding="utf-8") as f:
            return "# >>> studio" in f.read()
    except OSError:
        return False
