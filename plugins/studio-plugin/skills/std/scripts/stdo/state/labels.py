"""The fixed answer labels of approval questions (m0b2-plan §1, m0d2-plan §3.3), shared by state.py
(which checks the label against the current state) and the guard (which checks that the person chose
exactly this label). Read-only: nothing here writes."""

import json
import os
import re

from .argv import canonical

HASH12 = re.compile(r"^[0-9a-f]{12}$")


def approve(expect):
    return "승인 %s" % expect


def reject(expect):
    return "거부 %s" % expect


def repin(h12):
    return "재고정 %s" % h12


def exclude(h12):
    return "제외 %s" % h12


def unlock(video, lang, held):
    return "해제 %s %s %s" % (video, lang, held)


# subcommands whose label is "<word> <--expect>" (a 12-hex hash the question shows)
HASHED = {"approve": approve, "reject-source-diff": reject, "repin": repin, "exclude-output": exclude}
# subcommands that need evidence but have no label yet: the milestone that brings them
PLANNED = {"approve-actor": "M3b", "credit": "M1", "abandon": "M1", "move": "M1", "overlay": "M1",
           "rollback": "M4"}


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


def expected(argv, repo, studio_root):
    """(label, hash12 or None) for a state.py command line (argv after the script path)."""
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
        return HASHED[cmd](expect), expect
    if cmd == "unlock":
        if not isinstance(expect, str) or not expect or not pos:
            raise NoLabel("unlock needs a video id and --expect <held state>")
        vdir = video_dir(repo, studio_root, pos[0])
        st = read_state(vdir) if vdir else None
        if st is None or not isinstance(st.get("video"), str):
            raise NoLabel("cannot read the state of video %s" % pos[0])
        lang = opt.get("--lang") if isinstance(opt.get("--lang"), str) else st.get("source_lang")
        if not isinstance(lang, str) or not lang:
            raise NoLabel("cannot tell the language of video %s" % pos[0])
        return unlock(st["video"], lang, expect), None
    if cmd in PLANNED:
        raise NoLabel("state.py %s arrives in %s — there is no approval label for it yet" % (cmd, PLANNED[cmd]))
    raise NoLabel("state.py %s is not an approval command the guard knows" % cmd)
