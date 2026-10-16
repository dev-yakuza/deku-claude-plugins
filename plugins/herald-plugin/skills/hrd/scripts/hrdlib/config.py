"""`.claude/herald/config.json` — the single source for paths, commands and dials.

Only keys that deterministic scripts read are modelled here; commands read the rest.
"""

import os
import re

from .util import HeraldError, herald_dir, read_json

# Same character set as store.SLUG_RE (no "/" or "."), widened to any hyphen run: wide enough
# that a pattern overlap check never misses a real collision.
_SLUG_CHARS = r"[a-z0-9][a-z0-9-]*"
_PATTERN_SAMPLES = ("a", "a-a", "ab", "0")
LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

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

    @classmethod
    def load_checked(cls, root):
        """`load` + `validate`: deploy paths and stand-alone scripts fail closed on a malformed
        `translations` block (01-multilingual.md §2)."""
        cfg = cls.load(root)
        errors, _ = cfg.validate()
        if errors:
            raise HeraldError("config.json translations is invalid: %s — fix it with /hrd config" % "; ".join(errors))
        return cfg

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

    # --- translations (design/herald/01-multilingual.md §2) ------------------------------

    def translations(self):
        """The `translations` block, or None when the repo does not translate (0.8.0 behaviour)."""
        t = self.data.get("translations")
        return t if isinstance(t, dict) and t.get("targets") else None

    def source_lang(self):
        return (self.translations() or {}).get("source") or self.data.get("language") or "en"

    def targets(self, langs=None):
        out = [t for t in (self.translations() or {}).get("targets") or [] if isinstance(t, dict)]
        if langs is not None:
            want = set(langs)
            out = [t for t in out if t.get("lang") in want]
        return out

    def target_langs(self):
        return [t.get("lang") for t in self.targets()]

    def _target(self, lang):
        for t in self.targets():
            if t.get("lang") == lang:
                return t
        raise HeraldError("%r is not a translation target in config.json" % lang)

    # --- article paths ---------------------------------------------------------------

    def body_path(self, slug, lang=None):
        p = self.data["paths"]
        if lang is None or lang == self.source_lang():
            return p["body_pattern"].format(content=p["content"], slug=slug)
        return self._target(lang)["body_pattern"].format(content=p["content"], slug=slug)

    def image_dir(self, slug):
        return "%s/%s" % (self.data["paths"]["images"].rstrip("/"), slug)

    def translation_paths(self, slug):
        """{lang: path} for every configured target, whether the file exists or not."""
        return {lang: self.body_path(slug, lang) for lang in self.target_langs()}

    def bundle_paths(self, slug):
        """Body + image dir + every target path: what the bundle hash, the guard's jurisdiction
        and cleanups cover (§3). Without translations this is the 0.8.0 article."""
        return [self.body_path(slug), self.image_dir(slug)] + list(self.translation_paths(slug).values())

    def path_role(self, slug, path):
        """'src', 'img', a target language, or None — the role a bundle path plays for slug."""
        if path == self.body_path(slug):
            return "src"
        img = self.image_dir(slug).rstrip("/") + "/"
        if path.startswith(img):
            return "img"
        for lang, tp in self.translation_paths(slug).items():
            if path == tp:
                return lang
        return None

    def _pattern_regex(self, pattern):
        content = self.data["paths"]["content"]
        head, sep, tail = pattern.partition("{slug}")
        if not sep:
            return None
        esc = lambda x: re.escape(x.replace("{content}", content))  # noqa: E731
        return re.compile("^%s(%s)%s$" % (esc(head), _SLUG_CHARS, esc(tail)))

    def explains(self, path):
        """Whether the current config describes `path` as some slug's body, image or translation
        (§3 `unknown_path`). Returns the role or None."""
        img = self.data["paths"]["images"].rstrip("/") + "/"
        if path.startswith(img) and re.match(_SLUG_CHARS + "/", path[len(img):]):
            return "img"
        rx = self._pattern_regex(self.data["paths"]["body_pattern"])
        if rx and rx.match(path):
            return "src"
        for t in self.targets():
            rx = self._pattern_regex(t.get("body_pattern") or "")
            if rx and rx.match(path):
                return t.get("lang")
        return None

    def article_url(self, slug, lang=None):
        base = (self.data["site"].get("base_url") or "").rstrip("/")
        if lang is None or lang == self.source_lang():
            return base + self.data["site"]["url_pattern"].format(slug=slug)
        return base + self._target(lang)["url_pattern"].format(slug=slug)

    def translation_urls(self, slug):
        return {lang: self.article_url(slug, lang) for lang in self.target_langs()}

    # --- validation (§2) — HRD commands and deploy paths only; `load` stays lenient --------

    def validate(self):
        """(errors, warnings). Errors make HRD commands refuse and deploy paths fail closed; the
        guard falls back to a closed rule. No `translations` block → nothing to check."""
        t = self.data.get("translations")
        if t is None:
            return [], []
        errors, warnings = [], []
        if not isinstance(t, dict) or not isinstance(t.get("targets"), list) or not t["targets"]:
            return ["translations needs a non-empty `targets` list"], []
        src = self.source_lang()
        if not LANG_RE.match(src or ""):
            errors.append("translations.source %r is not a language code" % src)
        if "translator" not in (self.get("roles", "conditional") or []):
            errors.append("translations is set but the translator role is not in roles.conditional")
        seen = set()
        body_patterns = [("source", self.data["paths"]["body_pattern"])]
        url_patterns = [("source", self.data["site"]["url_pattern"])]
        for i, tg in enumerate(t["targets"]):
            if not isinstance(tg, dict):
                errors.append("translations.targets[%d] is not an object" % i)
                continue
            lang = tg.get("lang")
            if not isinstance(lang, str) or not LANG_RE.match(lang):
                errors.append("translations.targets[%d].lang %r is not a language code" % (i, lang))
                continue
            if lang in seen or lang == src:
                errors.append("translations target %r is repeated or equals the source language" % lang)
            seen.add(lang)
            bp, up = tg.get("body_pattern"), tg.get("url_pattern")
            for name, pat, allowed in (("body_pattern", bp, ("{content}", "{slug}")), ("url_pattern", up, ("{slug}",))):
                if not isinstance(pat, str) or not pat:
                    errors.append("translations target %r needs %s" % (lang, name))
                    continue
                holes = re.findall(r"\{[^{}]*\}", pat)
                bad = [h for h in holes if h not in allowed]
                if bad or pat.count("{slug}") != 1:
                    errors.append("translations target %r %s may use %s, with {slug} exactly once"
                                  % (lang, name, " ".join(allowed)))
            if isinstance(bp, str) and bp.count("{slug}") == 1:
                body_patterns.append((lang, bp))
                images = self.data["paths"]["images"].rstrip("/") + "/"
                if any(self._fill(bp, s).startswith(images) for s in _PATTERN_SAMPLES):
                    errors.append("translations target %r body_pattern lies inside the image directory — "
                                  "not supported (the source hash covers the whole image directory)" % lang)
            if isinstance(up, str) and up.count("{slug}") == 1:
                url_patterns.append((lang, up))
        for what, pats in (("body_pattern", body_patterns), ("url_pattern", url_patterns)):
            for i in range(len(pats)):
                for j in range(i + 1, len(pats)):
                    if self._patterns_overlap(pats[i][1], pats[j][1]):
                        errors.append("%s of %s and %s can produce the same path for some slugs"
                                      % (what, pats[i][0], pats[j][0]))
        if not errors:
            inputs = [b.rstrip("/") for b in self.get("paths", "build_inputs") or []]
            for lang in seen:
                sample = self.body_path("a", lang)
                if inputs and not any(sample == b or sample.startswith(b + "/") for b in inputs):
                    warnings.append("paths.build_inputs does not cover the %s translations (%s)" % (lang, sample))
        return errors, warnings

    def _fill(self, pattern, slug):
        return pattern.replace("{content}", self.data["paths"]["content"]).replace("{slug}", slug)

    def _patterns_overlap(self, a, b):
        """Whether pattern a and b can name the same path for two slugs: sample each one's paths
        against the other's matcher (slug characters cannot contain "/" or ".")."""
        if "{slug}" not in a or "{slug}" not in b:
            return False
        content = self.data["paths"]["content"]
        (pa, sa), (pb, sb) = (x.replace("{content}", content).split("{slug}", 1) for x in (a, b))
        # a path p·s·q of one equals p'·t·q' of the other only if the fixed prefixes nest and the
        # fixed suffixes nest, and what one has extra there can be part of a slug (no "/", ".")
        if pa.startswith(pb):
            px = pa[len(pb):]
        elif pb.startswith(pa):
            px = pb[len(pa):]
        else:
            return False
        if sa.endswith(sb):
            sx = sa[:len(sa) - len(sb)]
        elif sb.endswith(sa):
            sx = sb[:len(sb) - len(sa)]
        else:
            return False
        ok = re.compile(r"^[a-z0-9-]*$")
        return bool(ok.match(px) and ok.match(sx))

    def deploy_artifacts(self):
        return list(self.data["commands"].get("deploy_artifacts") or [])
