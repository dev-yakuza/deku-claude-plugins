"""The files of one page capture (a URL source's copy in `work/source/`, a recheck's `work/source/recheck-<n>/`) and
their record `capture-files.json`: what capture.py wrote, with the sha256 of each file, and what the capture said (the
asked and final address, when, the content hash, blocked hosts and opaque frames in the picture). The state commands
re-hash the files against it before they record anything (a copy changed after the capture is refused). Pure file
work: no state, no guard."""

import hashlib
import json
import os
import re

NAME = "capture-files.json"
RESULT = "result.json"
# a capture's copy: the picture, s2v's JSON, the page's text and readings, the page's pictures (assets/)
COPY = ("capture.png", "capture.json", "page.md", "page-ruby.json", "assets")
REQUIRED = ("capture.png", "capture.json", "page.md", "page-ruby.json")
SCHEMA = 1
RECHECK = re.compile(r"^recheck-([1-9][0-9]{0,5})$")
PREV = re.compile(r"^prev-([1-9][0-9]{0,5})$")


def numbered(folder, pattern):
    """{n: path} of the `recheck-<n>` or `prev-<n>` folders (real folders, not links) in `folder`."""
    out = {}
    for x in os.listdir(folder) if os.path.isdir(folder) else []:
        m = pattern.match(x)
        p = os.path.join(folder, x)
        if m and os.path.isdir(p) and not os.path.islink(p):
            out[int(m.group(1))] = p
    return out


def sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def listing(folder):
    """{relative path: sha256} of the regular files of a capture folder (its copy entries and result.json; never
    capture-files.json itself). A link anywhere is an error (ValueError)."""
    out = {}
    for name in COPY + (RESULT,):
        p = os.path.join(folder, name)
        if os.path.islink(p):
            raise ValueError("%s is a symbolic link" % p)
        if os.path.isfile(p):
            out[name] = sha(p)
        elif os.path.isdir(p):
            for d, dirs, files in os.walk(p):
                for x in dirs + files:
                    if os.path.islink(os.path.join(d, x)):
                        raise ValueError("%s is a symbolic link" % os.path.join(d, x))
                for f in files:
                    full = os.path.join(d, f)
                    out[os.path.relpath(full, folder).replace(os.sep, "/")] = sha(full)
    return out


def write(folder, meta):
    """Write capture-files.json (`meta` plus `files`) atomically, after every other file of the folder."""
    rec = dict(meta, schema=SCHEMA, files=listing(folder))
    p = os.path.join(folder, NAME)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return rec


def read(folder):
    try:
        with open(os.path.join(folder, NAME), encoding="utf-8") as f:
            rec = json.load(f)
    except OSError:
        return None, "%s has no %s (the capture did not finish)" % (os.path.basename(folder), NAME)
    except ValueError:
        return None, "%s/%s is not JSON" % (os.path.basename(folder), NAME)
    if not isinstance(rec, dict) or rec.get("schema") != SCHEMA or not isinstance(rec.get("files"), dict):
        return None, "%s/%s is not a capture record" % (os.path.basename(folder), NAME)
    return rec, None


def verify(folder, required=REQUIRED):
    """(the record, None) when every file capture-files.json lists has its sha and the required ones are listed, else
    (None, what is wrong)."""
    rec, why = read(folder)
    if why:
        return None, why
    try:
        now = listing(folder)
    except ValueError as e:
        return None, str(e)
    missing = [n for n in required if n not in rec["files"]]
    if missing:
        return None, "%s lists no %s" % (NAME, ", ".join(missing))
    changed = sorted(n for n, h in rec["files"].items() if now.get(n) != h)
    extra = sorted(n for n in now if n not in rec["files"])
    if changed or extra:
        return None, "the capture's files changed after capture.py wrote them (%s)" % ", ".join((changed + extra)[:5])
    return rec, None
