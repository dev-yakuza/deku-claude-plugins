"""A URL source's records (m2-plan §6.2–§6.3): record-source's URL branch, a recheck's record (`record-recheck`), the
promotion of a recheck (`record-source --from-recheck <n>`) with `work/source-diff.txt`, the folders kept, and the
recheck rule of the video commit.

- The copy is `work/source/` as capture.py source wrote it (stdo/capture/files.py); record-source re-hashes it against
  its `capture-files.json` and records `frozen_hash` = s2v's contentHash, `copy_sha` = page.md's sha256 and `capture`
  (when, the final address, blocked hosts, opaque frames, the record's sha). Stage entries never fetch the page
  (collect.default_source returns the frozen hash).
- After gate ① the copy changes only by a promotion: the recorded recheck's files are assembled in
  `work/source/.promote-<pid>/` and checked against its record, the current copy moves to `work/source/prev-<k>/`
  (through `.prev-<pid>/`), the assembled files take its place (capture-files.json last) and the state event comes
  last. A promotion cut short is finished by the same command again: a `.prev-*` folder goes back, a `.promote-*`
  folder goes, and a copy whose page.md is not the recorded `copy_sha` is dropped when a kept `prev-<k>/` holds the
  recorded one.
- `work/source-diff.txt` (P-STATE): the unified diff of page.md of the copy gate ①'s approval was made on (a kept
  `prev-<k>/` found by the approved source hash) against the promoted one; `state.py shown <video> source-diff` binds
  its sha.
- Kept: the last KEEP_RECHECKS `recheck-<n>/` folders and the one the current copy came from; the `prev-<k>/` of
  gate ①'s copy and the newest one. Older ones are deleted by record-recheck and by a promotion.
- The video commit (`check_commit.py --stage video`, never the hook) needs the latest recheck to have read the page, to
  be at most RECHECK_HOURS old and to have the approved source hash."""

import datetime
import difflib
import json
import os
import re
import shutil
import sys

from ..capture import files
from . import commands, flow, labels, schema, store

C = commands
KEEP_RECHECKS = 3
RECHECK_HOURS = 24
SKEW = datetime.timedelta(minutes=5)  # a recheck's `at` may be this far ahead of this machine's clock, no more
NUMBER = re.compile(r"^[1-9][0-9]{0,5}$")
DIFF = "source-diff.txt"


def _out(line):
    sys.stdout.write(line + "\n")


def _refuse(msg, code):
    raise store.Refused(msg, code)


def source_dir(vdir):
    return os.path.join(vdir, "work", "source")


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_at(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def approved_1(state):
    return any(L.get("status") == "active" and "1" in L.get("approved", {}) for L in state["langs"].values())


def approved_hash(state):
    """The source hash gate ① (or the latest source-diff approval) approved, or None."""
    from .gates import _from_hash
    return _from_hash(state)


def approved_hashes(state):
    """Every source hash an active language's ① (or the source-diff approval) rests on."""
    out = {approved_hash(state), state["source"].get("approved_hash")}
    for L in state["langs"].values():
        r1 = L.get("approved", {}).get("1") if L.get("status") == "active" else None
        if isinstance(r1, dict) and isinstance(r1.get("tuple"), dict):
            out.add(r1["tuple"].get("source_hash"))
    return {h for h in out if h}


def diff_base_hash(state):
    """The copy the source diff is shown against: the approved one, else the source language's ① copy."""
    h = approved_hash(state)
    if h:
        return h
    r1 = state["langs"].get(state.get("source_lang"), {}).get("approved", {}).get("1")
    return r1.get("tuple", {}).get("source_hash") if isinstance(r1, dict) else None


def _number(value, what):
    if not isinstance(value, str) or not NUMBER.match(value):
        raise flow.Usage("%s is the recheck's number (1, 2, …): %r" % (what, value))
    return int(value)


def _finished(s):
    if all(L["status"] in ("done", "aborted") for L in s["langs"].values()):
        raise store.Refused("every language of %s is finished" % s["video"], C.USAGE)


def _capture_lock(vdir):
    return store.Lock(os.path.join(vdir, "work", ".capture.lock"), wait=0.0)


# ---------- record-source (URL) ----------

def record_source(repo, vdir, state, cfg, hooks=None, env=None, url=False, from_recheck=None):
    if url not in (False, None):
        raise flow.Usage("a URL source's address is the one begin recorded: record-source takes no --url for it")
    env = dict(os.environ if env is None else env)
    n = _number(from_recheck, "--from-recheck") if from_recheck is not None else None
    try:
        with _capture_lock(vdir):
            notes = []
            if n is not None:
                done, notes = _promote(repo, vdir, state, cfg, env, n)
                if not done:
                    return C.OK
            return _record(repo, vdir, state, cfg, hooks, env, promoted=n, notes=notes)
    except store.Busy:
        raise store.Refused("capture.py works on this video's source now: wait for it, then run record-source again",
                            C.BUSY)


def _record(repo, vdir, state, cfg, hooks, env, promoted=None, notes=()):
    from ..capture import run as crun
    from ..source.scope import fingerprint
    src = state["source"]
    sdir = source_dir(vdir)
    if promoted is None and src.get("copy_sha") and approved_1(state):
        # after ①, the copy changes only by a promotion: one cut short is undone here (the recorded copy back)
        from .. import writes
        writes.check("a video's source copy")
        if not restore(sdir, src):
            _refuse("work/source/ holds neither the copy recorded for gate ① nor a kept one — ask the person", C.FAIL)
    rec, why = files.verify(sdir)
    if why:
        _refuse("the source's copy cannot be recorded: %s — run capture.py source %s again" % (why, state["video"]),
                C.FAIL)
    page_sha = files.sha(os.path.join(sdir, "page.md"))
    data = crun.read_json(os.path.join(sdir, "capture.json")) or {}
    content = data.get("contentHash")
    if not isinstance(content, str) or not content or content != rec.get("content_hash"):
        _refuse("work/source/capture.json has no content hash, or not the recorded one — run capture.py source %s "
                "again" % state["video"], C.FAIL)
    fp = fingerprint(repo, cfg, env)
    images, assets_sha, note = flow._checked_assets(vdir, page_sha, fp, public=state.get("scope") != "internal")
    cap = {"at": rec.get("at"), "url": rec.get("final"), "status": rec.get("status"),
           "blocked": len(rec.get("blocked") or []), "opaque_in_capture": rec.get("opaque_in_capture"),
           "files_sha": files.sha(os.path.join(sdir, files.NAME)), "s2v": (state.get("s2v") or {}).get("id")}
    upd = {"frozen_hash": content, "copy_sha": page_sha, "assets_sha": assets_sha, "images": images,
           "frozen_at": schema.now(), "capture": cap}
    if promoted is not None:
        upd["promoted_from"] = promoted
    elif page_sha != src.get("copy_sha"):
        upd["promoted_from"] = None  # a new capture: the copy no longer comes from a recheck

    def change(s):
        s["source"].update(upd)

    ev = dict({"event": "record-source"}, **upd)
    if promoted is not None:
        ev["from_recheck"] = promoted
    new = store.write(vdir, ev, change, hooks=hooks, check=_finished)
    if promoted is not None:
        keep(vdir, new)
        _out("promoted recheck %d: work/%s is the page's change since gate ①'s copy — the router holds the video at "
             "the source diff" % (promoted, DIFF))
    _out("source frozen %s (%d image(s))" % (content[:12], len(images)))
    for line in labels.source_commit_lines(new):
        _out("%s — put this line in the ① question" % line)
    for x in list(notes) + ([note] if note else []):
        _out("note: %s" % x)
    return C.OK


# ---------- record-recheck ----------

def record_recheck(vdir, state, o, hooks=None):
    if len(o["_"]) != 2:
        raise flow.Usage("record-recheck needs the video and the recheck's number: record-recheck <video> <n>")
    n = _number(o["_"][1], "<n>")
    if state["source"].get("kind") != "url":
        raise store.Refused("%s has no URL source: nothing is rechecked" % state["video"], C.USAGE)
    rdir = os.path.join(source_dir(vdir), "recheck-%d" % n)
    box = {}

    def check(s):
        _finished(s)
        top = max([r.get("n") for r in s["source"].get("rechecks") or [] if isinstance(r, dict)
                   and isinstance(r.get("n"), int)] + [0])
        if n <= top:
            _refuse("recheck %d is not above the last recorded one (%d): run capture.py recheck %s again"
                    % (n, top, s["video"]), C.REFUSED)
        if not os.path.isdir(rdir) or os.path.islink(rdir):
            _refuse("there is no work/source/recheck-%d/: run capture.py recheck %s" % (n, s["video"]), C.FAIL)
        rec, why = files.verify(rdir, required=(files.RESULT,))
        if why:
            _refuse("recheck %d: %s" % (n, why), C.FAIL)
        try:
            with open(os.path.join(rdir, files.RESULT), encoding="utf-8") as f:
                res = json.load(f)
        except (OSError, ValueError):
            res = None
        reach = res.get("reachable") if isinstance(res, dict) else None
        h = res.get("hash") if isinstance(res, dict) else None
        if not isinstance(res, dict) or res.get("n") != n or not isinstance(reach, bool) or parse_at(res.get("at")) is \
                None or (reach and (not isinstance(h, str) or h != rec.get("content_hash"))):
            _refuse("recheck %d: result.json is not capture.py's result for it" % n, C.FAIL)
        if parse_at(res["at"]) > utcnow() + SKEW:
            _refuse("recheck %d is dated in the future (%s): check this machine's clock and run capture.py recheck "
                    "again" % (n, res["at"]), C.FAIL)
        if reach:
            _rec, why = files.verify(rdir, required=files.REQUIRED + (files.RESULT,))
            if why:
                _refuse("recheck %d: %s" % (n, why), C.FAIL)
        box["entry"] = {"n": n, "at": res["at"], "hash": h if reach else None, "reachable": reach,
                        "files_sha": files.sha(os.path.join(rdir, files.NAME)),
                        "reason": None if reach else str(res.get("reason") or "")[:300]}

    def change(s):
        s["source"].setdefault("rechecks", []).append(dict(box["entry"]))

    try:
        with _capture_lock(vdir):
            new = store.write(vdir, lambda s: dict({"event": "record-recheck"}, **box["entry"]), change, hooks=hooks,
                              check=check)
            keep(vdir, new)
    except store.Busy:
        raise store.Refused("capture.py works on this video's source now: wait for it, then run record-recheck again",
                            C.BUSY)
    e = box["entry"]
    if not e["reachable"]:
        _out("recheck %d recorded: the page could not be read (%s) — the video cannot be committed until a recheck "
             "reads it; try again later" % (n, e["reason"]))
    elif e["hash"] == new["source"].get("frozen_hash"):
        _out("recheck %d recorded: the page is as the recorded copy" % n)
    else:
        _out("recheck %d recorded: the page changed — promote it: python3 .claude/studio/scripts/state.py "
             "record-source %s --from-recheck %d" % (n, state["video"], n))
    return C.OK


# ---------- the promotion ----------

def _promote(repo, vdir, state, cfg, env, n):
    """(promoted, notes): the recheck's files in place of the copy (False when there is nothing to promote)."""
    src = state["source"]
    _finished(state)
    r = [x for x in src.get("rechecks") or [] if isinstance(x, dict) and x.get("n") == n]
    if not r:
        _refuse("recheck %d is not recorded: run state.py record-recheck %s %d first" % (n, state["video"], n),
                C.REFUSED)
    r = r[-1]
    if not r.get("reachable") or not r.get("hash"):
        _refuse("recheck %d could not read the page: there is nothing to promote" % n, C.REFUSED)
    sdir = source_dir(vdir)
    from .. import writes
    writes.check("a video's source copy")
    # first the recorded copy back in place (a promotion cut short), also when there is nothing to promote
    if not restore(sdir, src):
        _refuse("work/source/ holds neither the recorded copy nor a kept one: Studio cannot keep the copy gate ① "
                "was made on — ask the person", C.FAIL)
    if r["hash"] == src.get("frozen_hash"):
        _out("recheck %d is the recorded copy: nothing to promote" % n)
        return False, []
    rdir = os.path.join(sdir, "recheck-%d" % n)
    rrec, why = files.verify(rdir, required=files.REQUIRED + (files.RESULT,))
    if why:
        _refuse("recheck %d: %s" % (n, why), C.FAIL)
    if files.sha(os.path.join(rdir, files.NAME)) != r.get("files_sha") or rrec.get("content_hash") != r["hash"]:
        _refuse("recheck %d changed after record-recheck: run capture.py recheck %s again" % (n, state["video"]),
                C.FAIL)
    tmp = os.path.join(sdir, ".promote-%d" % os.getpid())
    os.mkdir(tmp)
    try:
        for name in files.COPY:
            p = os.path.join(rdir, name)
            if os.path.isdir(p):
                shutil.copytree(p, os.path.join(tmp, name))
            elif os.path.isfile(p):
                shutil.copy2(p, os.path.join(tmp, name))
        meta = {k: v for k, v in rrec.items() if k not in ("files", "schema")}
        meta["promoted_from"] = n
        new = files.write(tmp, meta)
        if new["files"] != {k: v for k, v in rrec["files"].items() if k != files.RESULT}:
            _refuse("recheck %d's files changed while they were copied: try again" % n, C.FAIL)
        # the current (recorded) copy is kept: prev-<k>/, through one rename
        hold = os.path.join(sdir, ".prev-%d" % os.getpid())
        os.mkdir(hold)
        for name in (files.NAME,) + files.COPY:
            if os.path.lexists(os.path.join(sdir, name)):
                os.replace(os.path.join(sdir, name), os.path.join(hold, name))
        k = max(list(files.numbered(sdir, files.PREV)) + [0]) + 1
        os.rename(hold, os.path.join(sdir, "prev-%d" % k))
        for name in files.COPY:
            if os.path.lexists(os.path.join(tmp, name)):
                os.replace(os.path.join(tmp, name), os.path.join(sdir, name))
        os.replace(os.path.join(tmp, files.NAME), os.path.join(sdir, files.NAME))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    write_diff(vdir, state)
    return True, assets_again(repo, vdir, state, cfg, env)


def _remove(p):
    if os.path.islink(p) or os.path.isfile(p):
        os.remove(p)
    elif os.path.isdir(p):
        shutil.rmtree(p)


def recover(sdir):
    """What a promotion cut short left: a `.prev-*` folder goes back into place (its capture-files.json last), a
    `.promote-*` folder goes."""
    for x in sorted(os.listdir(sdir)):
        p = os.path.join(sdir, x)
        if x.startswith(".promote-"):
            _remove(p)
        elif x.startswith(".prev-") and os.path.isdir(p) and not os.path.islink(p):
            for name in sorted(os.listdir(p), key=lambda n: n == files.NAME):
                dst = os.path.join(sdir, name)
                if os.path.isdir(dst) and not os.path.islink(dst):
                    shutil.rmtree(dst)
                os.replace(os.path.join(p, name), dst)
            os.rmdir(p)


def restore(sdir, src):
    """recover(), then, when page.md is not the recorded copy (`copy_sha`) and a kept prev-<k>/ holds it — the same
    page.md, the recorded content hash and, when recorded, the same capture-files.json — that copy back in place (the
    files there now are a promotion's, half installed). True when work/source/ holds the recorded copy afterwards (or
    nothing was recorded yet)."""
    recover(sdir)
    copy_sha = src.get("copy_sha")
    if not copy_sha:
        return True
    cur, _why = files.verify(sdir)
    if cur is not None and files.sha(os.path.join(sdir, "page.md")) == copy_sha:
        return True
    want_rec = (src.get("capture") or {}).get("files_sha") if isinstance(src.get("capture"), dict) else None
    p = None
    for _k, q in sorted(files.numbered(sdir, files.PREV).items(), reverse=True):
        rec, why = files.verify(q)
        if why or files.sha(os.path.join(q, "page.md")) != copy_sha or rec.get("content_hash") != src.get(
                "frozen_hash") or (want_rec and files.sha(os.path.join(q, files.NAME)) != want_rec):
            continue
        p = q
        break
    if p is None:
        return False
    for name in (files.NAME,) + files.COPY:
        _remove(os.path.join(sdir, name))
    # through a `.prev-*` name: a restore cut short is finished by the next recover()
    hold = os.path.join(sdir, ".prev-r%s" % os.path.basename(p).split("-", 1)[1])
    os.rename(p, hold)
    recover(sdir)
    cur, _why = files.verify(sdir)
    return cur is not None and files.sha(os.path.join(sdir, "page.md")) == copy_sha


def _content_of(folder):
    rec, why = files.verify(folder)
    return (rec or {}).get("content_hash") if not why else None


def find_prev(sdir, page_sha=None, content=None):
    """The newest kept `prev-<k>/` whose copy is intact and has this page.md sha (or content hash), or None."""
    for k, p in sorted(files.numbered(sdir, files.PREV).items(), reverse=True):
        rec, why = files.verify(p)
        if why:
            continue
        if page_sha is not None and files.sha(os.path.join(p, "page.md")) == page_sha:
            return p
        if content is not None and rec.get("content_hash") == content:
            return p
    return None


def write_diff(vdir, state):
    """work/source-diff.txt: page.md of gate ①'s copy (else the copy just replaced) against the current one."""
    sdir = source_dir(vdir)
    want = diff_base_hash(state)
    base = find_prev(sdir, content=want) if want else None
    if base is None:
        prevs = files.numbered(sdir, files.PREV)
        base = prevs[max(prevs)] if prevs else None
    a = _text(os.path.join(base, "page.md")) if base else ""
    b = _text(os.path.join(sdir, "page.md"))
    diff = "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), "a/page.md", "b/page.md", n=3))
    p = os.path.join(vdir, "work", DIFF)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(diff)
    os.replace(tmp, p)
    return p


def _text(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def assets_again(repo, vdir, state, cfg, env):
    """resolve_assets and check_scope on the promoted copy, as their scripts would (notes for what is left)."""
    from ..source import assets, scope
    from ..source.cli import _overlay
    try:
        data = assets.build_url(repo, vdir, state, cfg)
        assets.write(vdir, data)
    except assets.AssetError as e:
        return ["resolve_assets.py: %s — run it again, then check_scope.py and record-source" % e]
    notes = []
    classes, _note = scope.analyst_classes(vdir)
    new = [i["id"] for i in data["images"] if i["id"] not in classes]
    if new:
        notes.append("pictures the source analyst has not classed yet (%s): spawn the analyst for them, then "
                     "check_scope.py and record-source again" % ", ".join(new[:10]))
    try:
        st, ov = _overlay(repo, cfg, env)
        out = scope.check(repo, vdir, state, cfg, files.sha(os.path.join(source_dir(vdir), "page.md")), st, ov,
                          scope.fingerprint(repo, cfg, env))
        assets.write(vdir, out)
    except (assets.AssetError, scope.ScopeError) as e:
        notes.append("check_scope.py: %s" % e)
    return notes


# ---------- the folders kept ----------

def keep(vdir, state):
    """Delete the recheck and prev folders no rule keeps (see the module text)."""
    sdir = source_dir(vdir)
    src = state["source"]
    rechecks = files.numbered(sdir, files.RECHECK)
    keep_r = set(sorted(rechecks)[-KEEP_RECHECKS:])
    if isinstance(src.get("promoted_from"), int):
        keep_r.add(src["promoted_from"])
    prevs = files.numbered(sdir, files.PREV)
    keep_p = set(sorted(prevs)[-1:])
    want = approved_hashes(state)
    for k, p in prevs.items():
        if _content_of(p) in want:
            keep_p.add(k)
    for n, p in rechecks.items():
        if n not in keep_r:
            shutil.rmtree(p, ignore_errors=True)
    for k, p in prevs.items():
        if k not in keep_p:
            shutil.rmtree(p, ignore_errors=True)


# ---------- the video commit ----------

def recheck_problem(state, now=None):
    """None, or why a URL source's video cannot be staged now: the latest recheck must have read the page, be at most
    RECHECK_HOURS old (counted here, at staging) and have the approved source hash."""
    src = state.get("source") or {}
    if src.get("kind") != "url":
        return None
    v = state.get("video")
    recs = [r for r in src.get("rechecks") or [] if isinstance(r, dict) and isinstance(r.get("n"), int)]
    if not recs:
        return ("the page was not read again before the commit: run capture.py recheck %s, then state.py "
                "record-recheck %s <n>" % (v, v))
    last = max(recs, key=lambda r: r["n"])
    if not last.get("reachable") or not last.get("hash"):
        return ("the page could not be read (recheck %d: %s); try again later — capture.py recheck %s"
                % (last["n"], last.get("reason") or "unreachable", v))
    at = parse_at(last.get("at"))
    now = now or utcnow()
    if at is not None and at > now + SKEW:
        return ("the latest recheck (%d, %s) is dated in the future: check this machine's clock, then run capture.py "
                "recheck %s again" % (last["n"], last.get("at"), v))
    if at is None or now - at > datetime.timedelta(hours=RECHECK_HOURS):
        return ("the latest recheck (%d, %s) is more than %d hours old: run capture.py recheck %s and state.py "
                "record-recheck again" % (last["n"], last.get("at"), RECHECK_HOURS, v))
    want = approved_hash(state)
    if last["hash"] != want:
        return ("the page changed since its approved copy (recheck %d): state.py record-source %s --from-recheck %d, "
                "then the source diff (/std resume %s)" % (last["n"], v, last["n"], v))
    return None
