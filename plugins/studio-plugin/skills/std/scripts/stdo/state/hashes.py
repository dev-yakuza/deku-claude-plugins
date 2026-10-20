"""Hashes Studio computes itself (m0b1-plan §4)."""

import hashlib
import json
import os


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hash_of(value):
    return sha(canonical(value))


def file_sha(path):
    try:
        with open(path, "rb") as f:
            return sha(f.read())
    except OSError:
        return None


ROLE_FIELDS = ("name", "kind")  # the role structure; actors (`actor`, recommendations) stay out


def brief_core(claims, roles):
    """Claim selection and role structure only (no actor ids, no outputs or platforms)."""
    shaped = sorted(({k: r.get(k) for k in ROLE_FIELDS} for r in roles), key=lambda r: canonical(r))
    return hash_of({"claims": sorted(claims), "roles": shaped})


def source_hash_repo_md(repo, path, images):
    """A repository Markdown source: its bytes and the bytes of the images it refers to."""
    text = file_sha(os.path.join(repo, path))
    return hash_of({"text": text, "images": sorted([[p, file_sha(os.path.join(repo, p))] for p in images])})


RENDER_EXTS = ("mp4", "srt", "vtt", "description.md", "chapters.txt", "thumbnail.png")


def render_sha(out_dir, output, lang, proxy=False):
    """The render of one output (S13: `.proxy.*` names while proxy approvals remain)."""
    files = {}
    for ext in RENDER_EXTS:
        name = "%s.%s.%s%s" % (output, lang, "proxy." if proxy else "", ext)
        p = os.path.join(out_dir, name)
        if os.path.exists(p):
            files[ext] = file_sha(p)
    return hash_of(files) if files else None
