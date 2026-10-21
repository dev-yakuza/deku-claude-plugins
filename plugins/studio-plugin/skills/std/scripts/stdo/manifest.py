"""The copy's file list (m0f-plan §2.3 H10): `scripts/MANIFEST.sha256` names every file of Studio's scripts
that a repository copy carries (the guard is plugin-only and not listed), with its sha256. The plugin ships it;
structure_test.sh keeps it equal to the files; check_commit.py compares a harness commit's copy with it."""

import hashlib
import os

NAME = "MANIFEST.sha256"
HEADER = "# Studio scripts manifest v1 — SCRIPTS_VERSION %s\n"


def skip(rel):
    rel = rel.replace(os.sep, "/")
    parts = rel.split("/")
    return rel in (NAME, "guard.py") or "__pycache__" in parts or rel.startswith("stdo/guard/") or \
        parts[-1].endswith((".pyc", ".pyo")) or parts[-1].startswith(".")


def files(scripts_dir):
    out = []
    for d, dirs, names in os.walk(scripts_dir):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for n in sorted(names):
            p = os.path.join(d, n)
            rel = os.path.relpath(p, scripts_dir).replace(os.sep, "/")
            if not skip(rel):
                out.append(rel)
    return sorted(out)


def render(scripts_dir, version):
    lines = [HEADER % version]
    for rel in files(scripts_dir):
        with open(os.path.join(scripts_dir, rel), "rb") as f:
            lines.append("%s  %s\n" % (hashlib.sha256(f.read()).hexdigest(), rel))
    return "".join(lines)


def parse(text):
    """({rel: sha}, version) or ValueError."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    if not lines or not lines[0].startswith("# Studio scripts manifest v1 — SCRIPTS_VERSION "):
        raise ValueError("not a Studio scripts manifest")
    version = lines[0].rsplit(" ", 1)[1]
    out = {}
    for l in lines[1:]:
        if not l:
            continue
        sha, sep, rel = l.partition("  ")
        if not sep or len(sha) != 64:
            raise ValueError("bad manifest line: %r" % l)
        out[rel] = sha
    return out, version
