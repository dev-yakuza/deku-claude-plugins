"""The fixed answer labels of approval questions (m0b2-plan §1, m0d2-plan §3.3), shared by state.py
(which checks the label against the current state) and the guard (which checks that the person chose
exactly this label). Read-only: nothing here writes."""

import json
import os
import re

from .argv import canonical

HASH12 = re.compile(r"^[0-9a-f]{12}$")

# The label template (m1-plan §3.2, D-M1-1): a video's labels name the video, so an answer about one video never
# approves another (two videos with the same content still have different hash12s, since hash12 hashes the video,
# the language and the gate too). Labels without a video (`사내설정` · `설정` · `갱신` · `커밋`) rely on the
# repository-wide one-use record (paths.consumed_log).


def approve(video, h12):
    return "승인 %s %s" % (video, h12)


def reject(video, h12):
    return "거부 %s %s" % (video, h12)


def repin(video, h12):
    return "재고정 %s %s" % (video, h12)


def exclude(video, h12):
    return "제외 %s %s" % (video, h12)


def unlock(video, lang, held):
    return "해제 %s %s %s" % (video, lang, held)


def credit(video, h12):
    return "출처 %s %s" % (video, h12)


def abandon(video, lang):
    return "중단 %s %s" % (video, lang)


def overlay(sha12):
    return "사내설정 %s" % sha12


def setting(h12):
    return "설정 %s" % h12


def update(h12):
    return "갱신 %s" % h12


def commit(tree12):
    return "커밋 %s" % tree12


# word -> (kind, field names); a field named h12/sha12/tree12 is 12 lowercase hex characters
TEMPLATE = {"승인": ("approve", ("video", "h12")), "거부": ("reject", ("video", "h12")),
            "재고정": ("repin", ("video", "h12")), "제외": ("exclude", ("video", "h12")),
            "해제": ("unlock", ("video", "lang", "held")), "출처": ("credit", ("video", "h12")),
            "중단": ("abandon", ("video", "lang")), "사내설정": ("overlay", ("sha12",)),
            "설정": ("setting", ("h12",)), "갱신": ("update", ("h12",)), "커밋": ("commit", ("tree12",))}
_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def parse(label):
    """(kind, {field: value}) of a fixed label, or NoLabel. Exactly one space between parts, nothing around."""
    if not isinstance(label, str):
        raise NoLabel("a label is text")
    parts = label.split(" ")
    spec = TEMPLATE.get(parts[0])
    if spec is None:
        raise NoLabel("%r is not a Studio label" % parts[0])
    kind, names = spec
    if len(parts) != len(names) + 1:
        raise NoLabel("%s takes %d part(s): %s" % (parts[0], len(names), " ".join("<%s>" % n for n in names)))
    out = {}
    for n, v in zip(names, parts[1:]):
        ok = HASH12.match(v) if n in ("h12", "sha12", "tree12") else _WORD.match(v)
        if not ok:
            raise NoLabel("%s: %r is not a valid <%s>" % (parts[0], v, n))
        out[n] = v
    return kind, out


# subcommands whose label is "<word> <video> <--expect>" (a 12-hex hash the question shows)
HASHED = {"approve": approve, "reject-source-diff": reject, "repin": repin, "exclude-output": exclude}
# subcommands that need evidence but have no label yet: the milestone that brings them
PLANNED = {"approve-actor": "M3b", "credit": "M1g", "move": "later", "rollback": "M4"}


class NoLabel(Exception):
    """The command line has no label the guard can check (with the reason)."""


def video_dir(repo, studio_root, video):
    """state.py's video folder (store.video_dir) without importing the writer: exactly one of public and local."""
    if not video or "/" in video or video in (".", ".."):
        return None
    pub = os.path.join(repo, studio_root, "videos", video)
    loc = os.path.join(repo, studio_root, "local", "videos", video)
    found = [d for d in (pub, loc) if os.path.isdir(d)]
    return found[0] if len(found) == 1 else None


def read_state(vdir):
    try:
        with open(os.path.join(vdir, "work", "state.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _video(repo, studio_root, vid):
    """The video id as its state records it (NoLabel when there is no such video)."""
    vdir = video_dir(repo, studio_root, vid)
    st = read_state(vdir) if vdir else None
    if st is None or not isinstance(st.get("video"), str) or not st["video"]:
        raise NoLabel("cannot read the state of video %s" % vid)
    if st["video"] != os.path.basename(os.path.normpath(vdir)):
        raise NoLabel("folder/state mismatch: the folder %s holds the state of video %s" % (vid, st["video"]))
    return vdir, st


def expected(argv, repo, studio_root):
    """(label, hash12 or None, video or None) for a state.py command line (argv after the script path). A video's
    question must show `[<video>]` literally (the guard checks it)."""
    try:
        c = canonical(argv)
    except ValueError as e:
        raise NoLabel(str(e))
    cmd, pos, opt = c["cmd"], c["pos"], c["opt"]
    expect = opt.get("--expect")
    if cmd in HASHED:
        if not isinstance(expect, str) or not HASH12.match(expect):
            raise NoLabel("--expect must be the 12 lowercase hex characters shown in the question")
        if not pos:
            raise NoLabel("%s needs a video id" % cmd)
        _vdir, st = _video(repo, studio_root, pos[0])
        return HASHED[cmd](st["video"], expect), expect, st["video"]
    if cmd == "unlock":
        if not isinstance(expect, str) or not expect or not pos:
            raise NoLabel("unlock needs a video id and --expect <held state>")
        _vdir, st = _video(repo, studio_root, pos[0])
        lang = opt.get("--lang") if isinstance(opt.get("--lang"), str) else st.get("source_lang")
        if not isinstance(lang, str) or not lang:
            raise NoLabel("cannot tell the language of video %s" % pos[0])
        return unlock(st["video"], lang, expect), None, st["video"]
    if cmd == "abandon":
        # `중단 <video> <lang>` (M1b): the language comes from --lang or the video's source language
        if not pos:
            raise NoLabel("abandon needs a video id")
        _vdir, st = _video(repo, studio_root, pos[0])
        lang = opt.get("--lang") if isinstance(opt.get("--lang"), str) else st.get("source_lang")
        if not isinstance(lang, str) or not _WORD.match(lang):
            raise NoLabel("cannot tell the language of video %s" % pos[0])
        return abandon(st["video"], lang), None, st["video"]
    if cmd == "overlay":
        # `사내설정 <sha12>` (M1b): --expect is the first 12 hex characters of the sha256 of the --from file, which
        # state.py checks; the question shows it
        if not isinstance(expect, str) or not HASH12.match(expect):
            raise NoLabel("--expect must be the 12 lowercase hex characters shown in the question")
        if pos:
            raise NoLabel("overlay takes no video id")
        return overlay(expect), expect, None
    if cmd in PLANNED:
        when = PLANNED[cmd]
        raise NoLabel("state.py %s %s — there is no approval label for it yet" % (
            cmd, "is not part of M1" if when == "later" else "arrives in %s" % when))
    raise NoLabel("state.py %s is not an approval command the guard knows" % cmd)
