"""Reading and writing a video's state (m0b1-plan §2).

state.json is the source of truth. A write: lock (flock) -> read again -> append `{seq, event, …}`
to approvals.jsonl + fsync -> replace state.json atomically with `last_seq = seq`. A jsonl line with
seq > last_seq is an incomplete event (never an approval); the next write voids it first.
Writes work only from state.py's CLI entry (`enable_writes`).
"""

import errno
import fcntl
import json
import os
import secrets
import time

from .. import writes
from . import schema

LOCK_WAIT = 2.0
TMP_AGE = 60.0
UNSUPPORTED = (errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOLCK, errno.EINVAL)


class Busy(Exception):
    """Another state.py holds this video's state lock (exit 5)."""


class Unsupported(Exception):
    """The file system does not support flock (exit 2)."""


class Refused(Exception):
    """A write's precondition failed under the lock; nothing was written."""

    def __init__(self, msg, code):
        Exception.__init__(self, msg)
        self.code = code


def enable_writes():
    writes.enable()  # one flag for every protected writer of the library (M1b review Y2)


def _check_writes():
    writes.check("a video's state")


def video_dir(repo, studio_root, video):
    """The video's folder: exactly one of public and local."""
    pub = os.path.join(repo, studio_root, "videos", video)
    loc = os.path.join(repo, studio_root, "local", "videos", video)
    found = [d for d in (pub, loc) if os.path.isdir(d)]
    if not found:
        raise schema.SchemaError("no video %s (%s or %s)" % (video, pub, loc), 2)
    if len(found) == 2:
        raise schema.SchemaError("video %s exists both public and local" % video, 2)
    return found[0]


def paths(vdir):
    w = os.path.join(vdir, "work")
    return {"work": w, "state": os.path.join(w, "state.json"), "log": os.path.join(w, "approvals.jsonl"),
            "lock": os.path.join(w, ".state.lock")}


def read_state(vdir):
    p = paths(vdir)["state"]
    try:
        with open(p, encoding="utf-8") as f:
            state = json.load(f)
    except OSError:
        raise schema.SchemaError("no state at %s" % p, 2)
    except ValueError as e:
        raise schema.SchemaError("state.json is not JSON: %s" % e)
    state = schema.validate(state)
    folder = os.path.basename(os.path.normpath(vdir))
    if state.get("video") != folder:
        # a copied video folder still names the original: its approvals and labels would be the original's
        raise schema.SchemaError("folder/state mismatch: the folder %s holds the state of video %r — a copied or "
                                 "renamed video folder is not a video (ask the user)" % (folder, state.get("video")), 2)
    return state


def read_log(vdir):
    out = []
    try:
        with open(paths(vdir)["log"], encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        out.append({"seq": None, "event": "unreadable"})
    except OSError:
        pass
    return out


def incomplete(vdir, state=None):
    """Seqs written to approvals.jsonl but never committed to state.json (and not voided)."""
    state = state or read_state(vdir)
    log = read_log(vdir)
    voided = {e.get("of") for e in log if e.get("event") == "void"}
    return [e["seq"] for e in log if isinstance(e.get("seq"), int) and e["seq"] > state["last_seq"]
            and e.get("event") != "void" and e["seq"] not in voided]


class Lock(object):
    def __init__(self, path, flock=fcntl.flock, wait=LOCK_WAIT):
        self.path, self.flock, self.wait, self.fd = path, flock, wait, None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0), 0o600)
        end = time.time() + self.wait
        while True:
            try:
                self.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                pass
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EACCES):
                    pass
                elif e.errno in UNSUPPORTED:
                    os.close(self.fd)
                    raise Unsupported("this file system does not support flock (%s): %s"
                                      % (errno.errorcode.get(e.errno, e.errno), self.path))
                else:
                    os.close(self.fd)
                    raise
            if time.time() >= end:
                os.close(self.fd)
                raise Busy("another state.py is writing this video's state (%s)" % self.path)
            time.sleep(0.05)

    def __exit__(self, *exc):
        os.close(self.fd)  # releases the flock


def _fsync_dir(d):
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _clean_tmp(work):
    for n in os.listdir(work):
        if n.startswith("state.json.tmp."):
            p = os.path.join(work, n)
            try:
                if time.time() - os.stat(p).st_mtime > TMP_AGE:
                    os.remove(p)
            except OSError:
                pass


def _append(log_path, entries):
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                torn = f.read(1) != b"\n"  # a line cut by a crash: start on a new line
            else:
                torn = False
    except OSError:
        torn = False
    with open(log_path, "a", encoding="utf-8") as f:
        if torn:
            f.write("\n")
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _replace_state(state_path, state, hooks):
    d = os.path.dirname(state_path)
    tmp = "%s.tmp.%s" % (state_path, secrets.token_hex(4))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    hooks.get("before_replace", lambda: None)()
    os.replace(tmp, state_path)
    _fsync_dir(d)


def write(vdir, event, change, hooks=None, flock=fcntl.flock, check=None, after_check=None,
          after_write=None):
    """Record `event` (a dict, or a list of dicts, or a function of the checked state returning
    them) and apply `change(state)` under the lock. `check(state)` runs first, under the lock, and
    may raise Refused (then nothing is written); `after_check(state)` runs once the checks passed,
    before anything of the video is written (M0b-2: the evidence's consumption record);
    `after_write(state)` runs after state.json is replaced, still under the lock. Returns the state."""
    _check_writes()
    hooks = hooks or {}
    p = paths(vdir)
    with Lock(p["lock"], flock=flock):
        state = read_state(vdir)
        if check:
            check(state)
        if after_check:
            after_check(state)
        if callable(event):
            event = event(state)
        _clean_tmp(p["work"])
        seq = state["last_seq"]
        entries = []
        log = read_log(vdir)
        top = max([state["last_seq"]] + [e["seq"] for e in log if isinstance(e.get("seq"), int)])
        seq = top
        for s in incomplete(vdir, state):
            seq += 1
            entries.append({"seq": seq, "event": "void", "of": s, "at": schema.now()})
        for ev in (event if isinstance(event, list) else [event]):
            seq += 1
            entry = dict(ev)
            entry.update(seq=seq, at=schema.now())
            entries.append(entry)
        _append(p["log"], entries)
        hooks.get("after_log", lambda: None)()
        change(state)
        state["last_seq"] = seq
        _replace_state(p["state"], state, hooks)
        if after_write:
            after_write(state)
        return state


def create(vdir, state):
    """Write a new state (M1's `begin`; tests). Refuses to overwrite."""
    _check_writes()
    p = paths(vdir)
    os.makedirs(p["work"], exist_ok=True)
    with Lock(p["lock"]):
        if os.path.exists(p["state"]):
            raise schema.SchemaError("state exists already: %s" % p["state"], 2)
        seq = max([0] + [e["seq"] for e in read_log(vdir) if isinstance(e.get("seq"), int)]) + 1
        _append(p["log"], [{"seq": seq, "event": "create", "video": state["video"], "at": schema.now()}])
        state["last_seq"] = seq
        _replace_state(p["state"], state, {})


def apply_approval(state, lang, gate, record, key=None):
    """Store an approval in `state`: the record, the loop counters of the gate's stages back to 0,
    the section's completion records spent; ① also sets the video's approved source hash."""
    L = state["langs"][lang]
    if gate in ("3", "4a", "4b"):
        L["approved"].setdefault(gate, {})[key] = record
    else:
        L["approved"][gate] = record
    for k in schema.LOOP_RESET.get(gate, ()):
        L["loops"][k] = 0
    o = key if gate in ("3", "4a") else None
    p = key if gate == "4b" else None
    L["done_stages"] = [r for r in L.get("done_stages", [])
                        if not (schema.section_gate(r["stage"]) == gate and r.get("output") == o
                                and r.get("platform") == p)]
    if gate == "1" and isinstance(record.get("tuple"), dict) and "source_hash" in record["tuple"]:
        state["source"]["approved_hash"] = record["tuple"]["source_hash"]


def record_approval(vdir, lang, gate, record, key=None, hooks=None):
    """Store one approval (tests; `approve` uses apply_approval inside its own write)."""
    def change(state):
        apply_approval(state, lang, gate, record, key)
    return write(vdir, {"event": "approve", "lang": lang, "gate": gate, "key": key, "record": record},
                 change, hooks=hooks)
