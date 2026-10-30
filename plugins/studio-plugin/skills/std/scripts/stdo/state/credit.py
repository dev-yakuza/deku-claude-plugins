"""`state.py credit-preview <video> <path>` and `state.py credit <video> <path> --expect <h12>` (m1-plan §9).

credit-preview (no evidence): the draft entry of <path> normalized — its eight `key=value` lines and the label
`출처 <video> <h12>` (and "이전 승인 <v>" when another video approved the same entry: it is asked again anyway).
credit: the person's answer to that question (the guard's evidence) — and the question text must show all eight lines
exactly (else `fields-not-shown`, exit 6) — then the entry goes into CREDITS.yaml and its hash into the state
(`credits.<path>`). The draft must still give the same h12 (else 1: preview and ask again)."""

import os
import sys

from .. import credits, writes
from ..commit.summary import norm
from ..source import assets as assets_mod
from . import commands as C, evidence, schema, store

FIELDS_NOT_SHOWN = "fields-not-shown"


def _entry(vdir, path):
    draft, why = credits.read(os.path.join(vdir, credits.DRAFT))
    if why:
        raise store.Refused(why, C.FAIL)
    item = draft.get(path)
    if item is None:
        raise store.Refused("%s has no entry for %s" % (credits.DRAFT, path), C.FAIL)
    asset = credits.assets_by_src(assets_mod.read(vdir)).get(path)
    try:
        return credits.normalize(item, os.path.normpath(os.path.join(vdir, path)), asset)
    except credits.CreditError as e:
        raise store.Refused(str(e), C.FAIL)


def _others(repo, root, video, hashv):
    out = []
    for base in (os.path.join(repo, root, "videos"), os.path.join(repo, root, "local", "videos")):
        if not os.path.isdir(base):
            continue
        for v in sorted(os.listdir(base)):
            if v == video:
                continue
            try:
                st = store.read_state(os.path.join(base, v))
            except schema.SchemaError:
                continue
            if any(isinstance(r, dict) and r.get("hash") == hashv for r in (st.get("credits") or {}).values()):
                out.append(v)
    return out


def preview(repo, root, vdir, state, o):
    if len(o["_"]) != 2:
        raise store.Refused("credit-preview <video> <path> (the image's script_src)", C.USAGE)
    e = _entry(vdir, o["_"][1])
    h = credits.h12(e)
    for line in credits.lines(e):
        sys.stdout.write("%s\n" % line)
    for v in _others(repo, root, state["video"], credits.entry_hash(e)):
        sys.stdout.write("이전 승인 %s (ask again: every video records its own)\n" % v)
    if credits.unsupported(e):
        sys.stdout.write("warning: %s — check_assets will refuse it\n" % credits.unsupported(e))
    sys.stdout.write("label 출처 %s %s\n" % (state["video"], h))
    return C.OK


def credit(repo, vdir, state, o, hooks, argv, with_evidence):
    if len(o["_"]) != 2 or not o.get("--expect"):
        raise store.Refused("credit <video> <path> --expect <h12>", C.USAGE)
    path, expect = o["_"][1], o["--expect"]
    e = _entry(vdir, path)
    hv = credits.entry_hash(e)
    if hv[:12] != expect:
        raise store.Refused("the entry of %s is not the one shown (its h12 is now %s): run credit-preview and ask "
                            "again" % (path, hv[:12]), C.FAIL)

    box = {}

    def check_state(s):  # before the evidence is consumed: a broken CREDITS.yaml refuses here, not after
        cur, why = credits.read(os.path.join(vdir, credits.FILE))
        if why:
            raise store.Refused(why, C.FAIL)
        box["cur"] = cur

    def ev_check(ev):
        if ev.get("mode") == "proxy":
            return  # the proxy mode asks no one (as at the gates); the video commit waits for a person's credit (J131)
        q = norm(ev.get("question") or "")
        missing = [l for l in credits.lines(e) if norm(l) not in q]
        if missing:
            raise store.Refused("%s: the question did not show %s — show all eight lines exactly and ask again"
                                % (FIELDS_NOT_SHOWN, ", ".join(l.split("=", 1)[0] for l in missing)), C.NO_EVIDENCE)

    def events(s, ev):
        return [{"event": "credit", "path": path, "hash": hv, "answer": evidence.answer_of(ev)}]

    def change(s, ev):
        s.setdefault("credits", {})[path] = {"hash": hv, "answer": evidence.answer_of(ev),
                                             "approved_by": ev.get("mode"), "at": schema.now()}
        cur = dict(box["cur"])
        cur[path] = e
        writes.check(credits.FILE)
        p = os.path.join(vdir, credits.FILE)
        tmp = "%s.tmp.%d" % (p, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(credits.dumps(cur))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    with_evidence(repo, vdir, state["video"], argv, "credit", lambda s: "출처 %s %s" % (s["video"], expect),
                  check_state, change, events, bool(o.get("--proxy")), hooks, ev_check=ev_check)
    sys.stdout.write("credited %s (%s)\n" % (path, expect))
    return C.OK
