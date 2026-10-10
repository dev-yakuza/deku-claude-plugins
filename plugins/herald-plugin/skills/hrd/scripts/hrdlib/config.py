"""`.claude/herald/config.json` — the single source for paths, commands and dials.

Only keys that deterministic scripts read are modelled here; commands read the rest.
"""

import fnmatch
import os

from .util import HeraldError, herald_dir, read_json

DEFAULTS = {
    "version": 1,
    "language": "en",
    "base_branch": "main",
    "paths": {
        "content": "content",
        "body_pattern": "{content}/{slug}.md",
        "images": "public/images",
        "build_inputs": ["content", "public"],
    },
    "site": {"base_url": "", "url_pattern": "/{slug}/"},
    "commands": {"deploy": "", "deploy_artifacts": [], "validate": ""},
    "autonomy": {"publish": "approve", "throttle": {"max_per_day": 2}},
    "budget": {"per_article_usd": 0},
    "models": {
        "batch_main": "sonnet",
        # USD per 1M input tokens, by model family. Cache read 0.1x, cache write 5m 1.25x,
        # 1h 2x, output 5x (same derivation as Guild's measurement tool). Override per repo.
        "prices": {"opus": 5.0, "sonnet": 3.0, "haiku": 1.0},
    },
    "roles": {"conditional": []},
    "gh": {"label": "herald", "revert_label": "herald-revert"},
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, root, data):
        self.root = root
        self.data = data

    @classmethod
    def load(cls, root, required=True):
        path = os.path.join(herald_dir(root), "config.json")
        raw = read_json(path)
        if raw is None:
            if required:
                raise HeraldError("Herald is not initialized here (.claude/herald/config.json missing). Run /hrd init.")
            raw = {}
        return cls(root, _merge(DEFAULTS, raw))

    def __getitem__(self, key):
        return self.data[key]

    def get(self, *keys, default=None):
        cur = self.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    @property
    def base(self):
        return self.data.get("base_branch") or "main"

    # --- article paths ---------------------------------------------------------------

    def body_path(self, slug):
        p = self.data["paths"]
        return p["body_pattern"].format(content=p["content"], slug=slug)

    def image_dir(self, slug):
        return "%s/%s" % (self.data["paths"]["images"].rstrip("/"), slug)

    def slug_of_path(self, path):
        """Map a repo path back to the slug it belongs to (body file or image dir), else None."""
        p = self.data["paths"]
        images = p["images"].rstrip("/") + "/"
        if path.startswith(images):
            rest = path[len(images):]
            return rest.split("/", 1)[0] if "/" in rest else None
        pattern = p["body_pattern"].format(content=p["content"], slug="\0")
        prefix, _, suffix = pattern.partition("\0")
        if path.startswith(prefix) and path.endswith(suffix) and len(path) > len(prefix) + len(suffix):
            slug = path[len(prefix): len(path) - len(suffix)]
            if "/" not in slug:
                return slug
        return None

    def is_build_input(self, path):
        for b in self.data["paths"].get("build_inputs", []):
            b = b.rstrip("/")
            if path == b or path.startswith(b + "/") or fnmatch.fnmatch(path, b):
                return True
        return False

    def article_url(self, slug):
        base = (self.data["site"].get("base_url") or "").rstrip("/")
        return base + self.data["site"]["url_pattern"].format(slug=slug)

    def deploy_artifacts(self):
        return list(self.data["commands"].get("deploy_artifacts") or [])
