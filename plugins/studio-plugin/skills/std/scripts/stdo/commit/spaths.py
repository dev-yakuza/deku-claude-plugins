"""Studio paths of a commit (m0e-plan §2).

`<sr>` candidates are the CONFIGURED names only: studio_root of .claude/studio/config.json in the work
tree, the index and HEAD, and the marker's name. The default `studio` is used only when there is
neither a config nor a marker (an unrelated `studio/` folder of a repository whose studio_root is
`media` is not Studio's)."""

import hashlib
import json
import os

from .. import ignore, paths

CONFIG = ".claude/studio/config.json"
GITIGNORE = ".gitignore"
STUDIO_PREFIXES = (".claude/studio/", ".claude/agents/std-")
LOCAL_FIXED = ".claude/studio/local/"


def _root_of(data):
    if data is None:
        return None
    try:
        cfg = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None
    if isinstance(cfg, dict):
        sr = cfg.get("studio_root") or "studio"
        if isinstance(sr, str) and sr.strip("/"):
            return sr.strip("/")
    return None


def read_config(top):
    """(config dict | None, error | None) of the work tree."""
    p = os.path.join(top, CONFIG)
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:
        return None, "%s cannot be read: %s" % (CONFIG, e)
    if not isinstance(cfg, dict):
        return None, "%s is not a JSON object" % CONFIG
    return cfg, None


def marker_root(common_dir, env):
    """The marker's studio_root (paths.marker_path without another git call)."""
    try:
        key = hashlib.sha256(os.path.realpath(common_dir).encode("utf-8")).hexdigest()[:16]
        m = os.path.join(paths.backup_root(env), key, "marker")
    except ValueError:
        return None
    try:
        with open(m, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("studio_root"), str) and data["studio_root"].strip("/"):
        return data["studio_root"].strip("/")
    return "studio" if isinstance(data, dict) else None


def studio_roots(top, git, env, head=None):
    """Configured studio_root names (work tree first), or ["studio"] when nothing is configured."""
    out = []
    try:
        with open(os.path.join(top, CONFIG), "rb") as f:
            out.append(_root_of(f.read()))
    except OSError:
        pass
    specs = [":" + CONFIG] + (["%s:%s" % (head, CONFIG)] if head else [])
    git.prefetch(specs + ([":" + GITIGNORE] + (["%s:%s" % (head, GITIGNORE)] if head else [])))
    for sp in specs:
        out.append(_root_of(git.show(sp)))
    out.append(marker_root(git.common_dir(), env))
    roots = []
    for r in out:
        if r and r not in roots:
            roots.append(r)
    return roots or ["studio"]


class Classifier(object):
    def __init__(self, roots, fold):
        self.roots = list(roots)
        self.fold = fold

    def _k(self, s):
        return s.casefold() if self.fold else s

    def is_local(self, path):
        p = self._k(path)
        if p.startswith(self._k(LOCAL_FIXED)):
            return True
        return any(p.startswith(self._k(r + "/local/")) for r in self.roots)

    def is_studio(self, path):
        """Studio path by name (`.gitignore` is decided by its block, see gitignore_kind)."""
        p = self._k(path)
        if any(p.startswith(self._k(x)) for x in STUDIO_PREFIXES):
            return True
        return any(p.startswith(self._k(r + "/")) for r in self.roots)

    def video_of(self, path):
        """(root, video id) for `<sr>/videos/<id>/…`."""
        parts = path.split("/")
        for r in self.roots:
            rp = r.split("/")
            n = len(rp)
            if [self._k(x) for x in parts[:n]] == [self._k(x) for x in rp] and len(parts) > n + 2 and \
                    self._k(parts[n]) == "videos":
                return r, parts[n + 1]
        return None


def gitignore_kind(old, new):
    """How a .gitignore change splits: "none" | "studio" (block only) | "other" | "mixed" | "broken"."""
    old = (old or b"").decode("utf-8", "surrogateescape")
    new = (new or b"").decode("utf-8", "surrogateescape")
    if old == new:
        return "none"
    try:
        o_rest, o_blk = ignore.split(old)
        n_rest, n_blk = ignore.split(new)
    except ignore.BlockError:
        return "broken"
    rest_same = o_rest == n_rest
    blk_same = o_blk == n_blk
    if rest_same and not blk_same:
        return "studio"
    if blk_same and not rest_same:
        return "other"
    return "mixed"


def gitignore_block(data):
    try:
        return ignore.split((data or b"").decode("utf-8", "surrogateescape"))[1]
    except ignore.BlockError:
        return "<broken>"
