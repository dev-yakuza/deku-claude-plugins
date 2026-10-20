"""Backups of git-ignored (local) videos (INV3; m0b2-plan §6).

<user_dir>/studio-backup/<repo-key>/videos/<id>/
    copy.1/ copy.2/ copy.3/   the last three copies (copy.1 newest), each with manifest.json
    complete/                 the last copy that fit under the size cap (outside the rotation)
    status.json               the last result (warnings shown by `state.py status`)
The whole video folder is copied except audio wav files; files unchanged since the previous copy
are hard-linked. No .git anywhere.
"""

import json
import os
import shutil
import secrets

from .. import paths
from . import schema
from .hashes import file_sha

CAP = 200 * 1024 * 1024
ROTATE = 3
TEXT_FIRST = (".md", ".json", ".jsonl", ".yaml", ".yml", ".txt", ".srt", ".vtt")


class Inside(Exception):
    """The backup folder would be inside the repository (a backup must survive `git clean`)."""


def root(repo, video):
    base = paths.backup_root()
    real_repo = os.path.realpath(repo)
    real_base = os.path.realpath(base)
    if real_base == real_repo or real_base.startswith(real_repo + os.sep):
        raise Inside("the backup folder %s is inside the repository" % base)
    return os.path.join(base, paths.repo_key(repo), "videos", video)


def _files(vdir):
    keep, skip = [], []
    for d, dirs, files in os.walk(vdir):
        dirs.sort()
        for n in sorted(files):
            p = os.path.join(d, n)
            rel = os.path.relpath(p, vdir)
            parts = rel.split(os.sep)
            if parts[0] == "audio" and n.endswith(".wav"):
                skip.append({"path": rel, "why": "audio wav (made again from the lock)"})
            elif n == ".state.lock" or ".tmp." in n:
                skip.append({"path": rel, "why": "lock or temporary file"})
            else:
                keep.append(rel)
    keep.sort(key=lambda r: (not r.endswith(TEXT_FIRST), r))
    return keep, skip


def _previous(base):
    try:
        with open(os.path.join(base, "copy.1", "manifest.json"), encoding="utf-8") as f:
            return {e["path"]: e["sha256"] for e in json.load(f)["files"]}
    except (OSError, ValueError, KeyError):
        return {}


def run(repo, vdir, video, cap=CAP):
    """Copy now. Returns the status written (never raises for an ordinary failure)."""
    try:
        base = root(repo, video)
    except Inside as e:
        return {"at": schema.now(), "complete": False, "bytes": 0, "warning": "backup skipped: %s" % e}
    try:
        os.makedirs(base, exist_ok=True)
        keep, skip = _files(vdir)
        prev = _previous(base)
        tmp = os.path.join(base, ".tmp.%s" % secrets.token_hex(4))
        os.makedirs(tmp)
        files, total, complete = [], 0, True
        for rel in keep:
            src = os.path.join(vdir, rel)
            size = os.path.getsize(src)
            if total + size > cap:
                complete = False
                skip.append({"path": rel, "why": "over the size cap"})
                continue
            sha = file_sha(src)
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            linked = False
            if prev.get(rel) == sha:
                try:
                    os.link(os.path.join(base, "copy.1", rel), dst)
                    linked = True
                except OSError:
                    pass
            if not linked:
                shutil.copy2(src, dst)
            files.append({"path": rel, "size": size, "sha256": sha, "linked": linked})
            total += size
        manifest = {"video": video, "at": schema.now(), "complete": complete, "bytes": total,
                    "files": files, "excluded": skip}
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        # rotate: copy.3 goes, copy.2 -> copy.3, copy.1 -> copy.2, new -> copy.1
        last = os.path.join(base, "copy.%d" % ROTATE)
        if os.path.exists(last):
            shutil.rmtree(last)
        for n in range(ROTATE - 1, 0, -1):
            a = os.path.join(base, "copy.%d" % n)
            if os.path.exists(a):
                os.rename(a, os.path.join(base, "copy.%d" % (n + 1)))
        os.rename(tmp, os.path.join(base, "copy.1"))
        if complete:
            done = os.path.join(base, ".complete.tmp")
            if os.path.exists(done):
                shutil.rmtree(done)
            shutil.copytree(os.path.join(base, "copy.1"), done, copy_function=_link_or_copy)
            old = os.path.join(base, "complete")
            if os.path.exists(old):
                shutil.rmtree(old)
            os.rename(done, old)
        status = {"at": manifest["at"], "complete": complete, "bytes": total,
                  "warning": None if complete else "the backup exceeded %d bytes: some files were left out" % cap}
    except OSError as e:
        status = {"at": schema.now(), "complete": False, "bytes": 0, "warning": "backup failed: %s" % e}
    try:
        with open(os.path.join(base, "status.json"), "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, sort_keys=True)
    except OSError:
        pass
    return status


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def read_status(repo, video):
    try:
        root(repo, video)
    except Inside as e:
        return {"warning": "backup skipped: %s" % e}
    try:
        with open(os.path.join(root(repo, video), "status.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
