"""M0b-2: shown, approve, the source diff, re-pin, exclude-output, unlock (m0b2-plan).

Approval-type commands (commands.APPROVAL) consume the guard's evidence. Lock order:
consumption lock -> video lock -> state checks + evidence checks -> consumption record (fsync)
-> approvals.jsonl + state.json -> pending file removed -> backup (local videos) -> unlock both."""

import json
import os
import sys

from . import backup, commands, evidence, labels, schema, store
from .collect import CollectError
from .hashes import hash_of
from .router import decide, precheck
from .shown import GATES, ONE, frames_index, frames_stamp, hash12, scopes, shown_hash, tuple_of
from .tuples import tuple_for

C = commands


def _refuse(msg, code):
    raise store.Refused(msg, code)


def _out(line):
    sys.stdout.write(line + "\n")


def _mirror_shown(vdir, state, lang):
    """work/<lang>/shown.json: a readable copy of what was shown (state.json holds the truth)."""
    d = os.path.join(vdir, "work", lang)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "shown.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state["langs"][lang]["shown"], f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, os.path.join(d, "shown.json"))


# ---------- shown ----------

def shown(vdir, state, lang, ctx, o, providers, hooks):
    if len(o["_"]) < 2 or o["_"][1] not in GATES:
        raise store.Refused("shown needs a gate: %s" % "|".join(GATES), C.USAGE)
    gate = o["_"][1]
    scope = o.get("--output") if gate in ("3", "4a") else o.get("--platform") if gate == "4b" else ONE
    if scope is None:
        raise store.Refused("%s needs --%s" % (gate, "platform" if gate == "4b" else "output"), C.USAGE)
    if scope != ONE and scope not in scopes(state, lang, gate):
        raise store.Refused("%s is not in the brief" % scope, C.USAGE)
    begin, end = bool(o.get("--begin")), bool(o.get("--end"))
    if (begin or end) and gate != "3":
        raise store.Refused("--begin/--end are for ③ only", C.USAGE)
    if gate == "3" and not (begin or end):
        raise store.Refused("③ is shown with --begin before the snapshot and --end after it", C.USAGE)
    cur = providers.collect(ctx, state, lang)
    box = {}
    if gate == "2":  # the lines its question must show, computed now (conflicts too) and kept with the shown record
        from ..voice import gate2
        box["lines"] = gate2.lines(vdir, lang, _conflicts(ctx, state, lang, providers), _write_text)
    if gate == "4b":  # the copy's facts and their excerpts (M1h review Y2)
        from ..distribute import gate4b
        box["lines"] = gate4b.lines(vdir, lang, scope, _write_text)

    def check(s):
        first = precheck(s, lang)
        if first:
            _refuse("%s is %s" % (lang, "finished" if first.done else "held"), C.WAIT if first.held else C.USAGE)
        if gate == "3" and end:
            pend = s["langs"][lang]["shown_pending"].get(scope)
            if not pend:
                _refuse("--end without --begin for %s" % scope, C.USAGE)
            stamp = frames_stamp(frames_index(ctx, s, lang, scope))
            if stamp is None or stamp == pend["frames"]:
                _refuse("the stills of %s were not written again after --begin" % scope, C.FAIL)
            if pend["tuple"] != hash_of(tuple_of(s, lang, cur, "3", scope)):
                box["changed"] = True

    def change(s):
        L = s["langs"][lang]
        if gate == "3" and begin:
            L["shown_pending"][scope] = {"tuple": hash_of(tuple_of(s, lang, cur, "3", scope)),
                                         "frames": frames_stamp(frames_index(ctx, s, lang, scope)),
                                         "fails": L["shown_pending"].get(scope, {}).get("fails", 0)}
            return
        if gate == "3" and box.get("changed"):
            L["shown_pending"][scope]["fails"] += 1
            box["fails"] = L["shown_pending"][scope]["fails"]
            return
        L["shown"].setdefault(gate, {})[scope] = {"hash": shown_hash(ctx, s, lang, cur, gate, scope),
                                                  "at": schema.now()}
        if gate in ("2", "4b"):
            L["shown"][gate][scope]["lines"] = list(box["lines"])
        if gate == "3":
            L["shown_pending"].pop(scope, None)
        box["hash12"] = hash12(s, lang, gate)

    def after(s):
        _mirror_shown(vdir, s, lang)

    store.write(vdir, {"event": "shown", "lang": lang, "gate": gate, "scope": scope,
                       "phase": "begin" if begin else "end" if end else None},
                change, hooks=hooks, check=check, after_write=after)
    if box.get("changed"):
        sys.stderr.write("std state: %s changed during the snapshot (%d time(s)); take it again\n"
                         % (scope, box["fails"]))
        return C.FAIL
    if begin:
        _out("begin %s" % scope)
    else:
        _out("hash12 %s" % box["hash12"] if box.get("hash12") else "shown %s (other scopes not shown yet)" % scope)
    if gate in ("2", "4b") and not begin:  # the question shows each of these lines (the guard checks them — V1, Y2)
        for line in box["lines"]:
            _out("in the question: %s" % line)
    return C.OK


def _write_text(p, text):
    from .. import writes
    writes.check(os.path.basename(p))
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)


def _conflicts(ctx, state, lang, providers):
    from ..voice import pronounce
    chg, _why = pronounce.read(pronounce.path_changes(ctx["vdir"], lang))
    if not chg:
        return []
    from . import cli as scli
    cfg = scli._cfg_of(ctx["repo"])
    items = pronounce.conflicts(ctx["repo"], ctx["studio_root"], state["video"], chg,
                                pronounce.head_shared(ctx["repo"]) or {}, providers,
                                lambda vd, lg: scli._ctx(ctx["repo"], cfg, vd, lg))
    return pronounce.conflict_lines(items)


# ---------- evidence-consuming commands ----------

def _with_evidence(repo, vdir, video, argv, cmd, label_of, check_state, change, events, proxy, hooks, after=None,
                   ev_check=None):
    """The one lock order of m0b2-plan §1. `ev_check(ev)` judges the evidence itself (credit: its question text)."""
    box = {}

    def check(s):
        check_state(s)
        label = label_of(s)
        try:
            box["ev"] = evidence.check(repo, argv, label, proxy)
        except evidence.Missing as e:
            _refuse(str(e), C.NO_EVIDENCE)
        if ev_check:
            ev_check(box["ev"])

    def consume(s):
        evidence.consume(repo, box["ev"], video, cmd)

    def apply(s):
        change(s, box["ev"])

    def post(s):
        evidence.remove_pending(repo)
        if after:
            after(s)
        if s["location"] == "local":
            st = backup.run(repo, vdir, video)
            if st.get("warning"):
                sys.stderr.write("warning: %s\n" % st["warning"])

    with evidence.ConsumptionLock(repo):
        return store.write(vdir, lambda s: events(s, box["ev"]), apply, hooks=hooks, check=check,
                           after_check=consume, after_write=post)


def _gate_checks(s, lang, cur, gate):
    first = precheck(s, lang)
    if first:
        _refuse("%s is %s" % (lang, "finished" if first.done else "held"), C.WAIT if first.held else C.USAGE)
    for sc in scopes(s, lang, gate):
        d = decide(s, lang, cur, enter=gate, output=sc if gate in ("3", "4a") else None,
                   platform=sc if gate == "4b" else None)
        if d.stop:
            _refuse("waiting for a person (%s)" % d.stop["stop"], C.WAIT)
        if d.held:
            _refuse("waiting for a person (%s)" % d.held.get("state"), C.WAIT)
        if d.enter == "null-hash":
            _refuse("a hash cannot be computed: %s" % d.null_reasons, C.FAIL)
        if d.enter != "allowed":
            _refuse("%s cannot be approved yet: the work is at %s" % (gate, (d.redo or {}).get("stage")), C.REFUSED)


def _shown_checks(ctx, s, lang, cur, gate, expect):
    rec = s["langs"][lang]["shown"].get(gate, {})
    for sc in scopes(s, lang, gate):
        if sc not in rec:
            _refuse("%s was not shown for %s" % (gate, sc), C.FAIL)
        if rec[sc]["hash"] != shown_hash(ctx, s, lang, cur, gate, sc):
            _refuse("%s changed after it was shown for %s: show it again" % (gate, sc), C.FAIL)
    h = hash12(s, lang, gate)
    if h != expect:
        _refuse("--expect %s is not the shown hash12 %s" % (expect, h), C.FAIL)
    return h


def _strings(x):
    return isinstance(x, list) and all(isinstance(e, str) for e in x)


def _excerpts(vdir, lang, gate, scopes_):
    """The source excerpts an approval rests on (① and ④b). Fails closed: without a readable
    claims-map of the expected shape nothing is approved (a later source diff could not be judged).
    Shape (M1 fills it): {"excerpts": [str], "copy_excerpts": {<platform>: [str]}}."""
    p = os.path.join(vdir, "work", lang, "claims-map.json")
    try:
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
    except OSError:
        _refuse("the claims map is missing: %s" % p, C.FAIL)
    except ValueError as e:
        _refuse("the claims map is not JSON (%s): %s" % (e, p), C.FAIL)
    if not isinstance(m, dict):
        _refuse("the claims map is not an object: %s" % p, C.FAIL)
    if gate == "1":
        if not _strings(m.get("excerpts")):
            _refuse("the claims map has no list of excerpts: %s" % p, C.FAIL)
        return m["excerpts"], {}
    cx = m.get("copy_excerpts")
    if not isinstance(cx, dict) or not all(_strings(cx.get(sc)) for sc in scopes_):
        _refuse("the claims map has no copy excerpts for %s: %s" % (", ".join(scopes_), p), C.FAIL)
    return [], cx


def approve(repo, vdir, state, lang, ctx, o, providers, hooks, argv):
    gate = o["_"][1] if len(o["_"]) > 1 else None
    expect = o.get("--expect")
    if gate not in GATES or not expect:
        raise store.Refused("approve needs a gate (%s) and --expect <hash12>" % "|".join(GATES), C.USAGE)
    if gate == "source-diff":
        return _source_diff(repo, vdir, state, lang, ctx, o, providers, hooks, argv, reject=False)
    proxy = bool(o.get("--proxy"))
    cur = providers.collect(ctx, state, lang)
    box = {"excerpts": [], "copy": {}}
    if gate == "2":  # what ② approves besides the tuple: the sentences heard, the readings added (m1-plan §8, T1)
        box["sentences"] = {x.get("id"): x.get("lockKey") for x in providers.sentences(ctx) or []
                            if isinstance(x, dict) and not x.get("recorded") and x.get("id")}
        box["pronounce"] = _pronounce_approved(vdir, lang)

    def check_state(s):
        _gate_checks(s, lang, cur, gate)
        _shown_checks(ctx, s, lang, cur, gate, expect)
        if gate in ("1", "4b"):
            box["excerpts"], box["copy"] = _excerpts(vdir, lang, gate, scopes(s, lang, gate))

    def records(s, ev):
        out = []
        for sc in scopes(s, lang, gate):
            o_, p_ = (sc if gate in ("3", "4a") else None), (sc if gate == "4b" else None)
            outs = [x for x in s["brief"]["platforms"].get(p_, []) if x in schema.current_outputs(s, lang)]
            rec = {"tuple": tuple_for(gate, cur, output=o_, platform=p_, platform_outputs=outs),
                   "shown": s["langs"][lang]["shown"][gate][sc]["hash"], "answer": evidence.answer_of(ev),
                   "approved_by": ev["mode"], "s2v_id": s["s2v"].get("id"), "s2v_commit": s["s2v"].get("commit"),
                   "s2v_dirty": s["s2v"].get("dirty"), "hash_version": cur["hash_version"],
                   "engine": cur["engine"], "at": schema.now()}
            if gate == "1":
                rec["excerpts"] = list(box["excerpts"])
            if gate == "4b":
                rec["excerpts"] = list(box["copy"].get(sc, []))
            if gate == "2":
                rec["sentences"] = dict(box["sentences"])
                rec[schema.PRONOUNCE_SHA] = hash_sha(box["pronounce"])
            out.append((None if gate in ("1", "2") else sc, rec))
        return out

    def events(s, ev):
        return [{"event": "approve", "lang": lang, "gate": gate, "key": k, "record": r} for k, r in records(s, ev)]

    def change(s, ev):
        for k, r in records(s, ev):
            store.apply_approval(s, lang, gate, r, k)
        if gate == "2":  # always written anew ({} without additions); its sha is in the record (v5.1 T1)
            _write_atomic(os.path.join(vdir, "work", lang, "pronounce-approved.json"), box["pronounce"])

    _with_evidence(repo, vdir, state["video"], argv, "approve", lambda s: labels.approve(s["video"], expect), check_state,
                   change, events, proxy, hooks)
    _out("approved %s %s" % (gate, lang))
    return C.OK


def _pronounce_approved(vdir, lang):
    """The bytes of pronounce-approved.json: the cast stage's flat changes, or {} (none, or not a flat object —
    check_assets refuses that before ②)."""
    from ..voice import pronounce
    obj, _why = pronounce.read(pronounce.path_changes(vdir, lang))
    return (json.dumps(obj or {}, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def hash_sha(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _write_atomic(p, data):
    from .. import writes
    writes.check("pronounce-approved.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _one_language(s):
    """Until M3a (translation), tuple rewrites support one active language only: with more,
    refuse rather than move some languages' fields."""
    active = [k for k, L in s["langs"].items() if L["status"] == "active"]
    if len(active) > 1:
        _refuse("rewriting approvals of several languages (%s) needs M3a" % ", ".join(active), C.WAIT)


def _from_hash(s):
    """The video's last approved source hash (m0b2-plan §4.1), or None when it cannot be told."""
    if s["source"].get("approved_hash"):
        return s["source"]["approved_hash"]
    vals = {L["approved"]["1"]["tuple"].get("source_hash") for L in s["langs"].values()
            if L["status"] == "active" and "1" in L["approved"]}
    active_with_1 = [L for L in s["langs"].values() if L["status"] == "active" and "1" in L["approved"]]
    active = [L for L in s["langs"].values() if L["status"] == "active"]
    if active_with_1 and len(active_with_1) == len(active) and len(vals) == 1:
        return vals.pop()
    return None


def _source_diff(repo, vdir, state, lang, ctx, o, providers, hooks, argv, reject):
    expect = o.get("--expect")
    if not expect:
        raise store.Refused("needs --expect <hash12>", C.USAGE)
    cur = providers.collect(ctx, state, lang)
    from ..text.normalize import Text
    text = Text(cur.get("source_text") or "")

    def check_state(s):
        _one_language(s)
        d = decide(s, lang, cur)
        if not (d.held and d.held.get("state") == "source-diff"):
            _refuse("no source diff is waiting for a decision", C.REFUSED)
        _shown_checks(ctx, s, lang, cur, "source-diff", expect)
        if not reject and _from_hash(s) is None:
            _refuse("the approved source hash cannot be told (languages differ): approve ① again", C.WAIT)

    def plan(s):
        new = cur["source_hash"]
        if reject:
            return [], new
        frm = _from_hash(s)
        moves = []
        for lg, L in s["langs"].items():
            if L["status"] != "active":
                continue
            r1 = L["approved"].get("1")
            if r1 and r1["tuple"].get("source_hash") == frm:
                moves.append((lg, "1", None))
            for p, r in (L["approved"].get("4b") or {}).items():
                if r["tuple"].get("source_hash") == frm and all(text.contains(e) for e in r.get("excerpts") or []):
                    moves.append((lg, "4b", p))
        return moves, new

    def events(s, ev):
        moves, new = plan(s)
        frm = _from_hash(s)
        out = [{"event": "rewrite", "cause": "source-diff", "lang": lg, "gate": g, "key": k,
                "field": "source_hash", "old": frm, "new": new} for lg, g, k in moves]
        out.append({"event": "reject-source-diff" if reject else "approve-source-diff", "source_hash": new,
                    "answer": evidence.answer_of(ev)})
        return out

    def change(s, ev):
        moves, new = plan(s)
        for lg, g, k in moves:
            rec = s["langs"][lg]["approved"][g] if g == "1" else s["langs"][lg]["approved"][g][k]
            rec["tuple"]["source_hash"] = new
        for L in s["langs"].values():
            if L["status"] == "active":
                L["approved"]["source-diff"] = {"tuple": {"source_hash": new}, "rejected": reject,
                                                "answer": evidence.answer_of(ev), "at": schema.now()}
        if not reject:
            s["source"]["approved_hash"] = new

    _with_evidence(repo, vdir, state["video"], argv, "reject-source-diff" if reject else "approve",
                   lambda s: (labels.reject if reject else labels.approve)(s["video"], expect), check_state, change, events, bool(o.get("--proxy")), hooks)
    _out("source diff %s" % ("rejected" if reject else "approved"))
    return C.OK


def reject_source_diff(repo, vdir, state, lang, ctx, o, providers, hooks, argv):
    return _source_diff(repo, vdir, state, lang, ctx, o, providers, hooks, argv, reject=True)


def repin(repo, vdir, state, lang, ctx, o, providers, hooks, argv):
    expect = o.get("--expect")
    if not expect:
        raise store.Refused("repin needs --expect <hash12>", C.USAGE)
    ins = providers.inspect(ctx)
    cur = providers.collect(ctx, state, lang, ins=ins)
    ver = providers.version(ctx)
    if ver.get("stale_build") or cur.get("stale_build"):
        raise store.Refused("s2v's build is stale: run yarn build in the s2v repository first", C.USAGE)
    if ver.get("id") != cur["s2v_version"]:
        raise store.Refused("s2v changed while reading it: try again", C.FAIL)
    old_cur = {}

    def olds_of(s):
        """Computed inside the lock, on the state as it is (NIT)."""
        olds = set()
        for L in s["langs"].values():
            for g, rs in L["approved"].items():
                if g == "source-diff":
                    continue
                for r in (rs.values() if g in ("3", "4a", "4b") else [rs]):
                    if isinstance(r, dict) and r.get("hash_version") != cur["hash_version"]:
                        olds.add(r.get("hash_version"))
        for hv in sorted(olds, key=str):
            if hv is None:
                _refuse("an approval has no hash_version: it cannot be moved — approve again", C.WAIT)
            if hv not in old_cur:
                try:
                    old_cur[hv] = providers.collect(ctx, s, lang, ins=providers.inspect_at(ctx, hv))
                except CollectError as e:
                    _refuse("s2v cannot compute hash_version %s any more (%s): approve again" % (hv, e), C.WAIT)

    def label(s):
        return labels.repin(s["video"], hash_of({"video": s["video"], "from_id": s["s2v"].get("id"),
                                                 "to_id": cur["s2v_version"]})[:12])

    def check_state(s):
        _one_language(s)
        d = decide(s, lang, cur)
        if not (d.stop and d.stop.get("stop") == "s2v-version"):
            _refuse("the s2v version did not change: nothing to re-pin", C.REFUSED)
        if label(s) != labels.repin(s["video"], expect):
            _refuse("--expect %s does not match this re-pin" % expect, C.FAIL)
        olds_of(s)

    def moves(s):
        out = []
        for lg, L in s["langs"].items():
            for g, rs in L["approved"].items():
                if g == "source-diff":
                    continue
                items = rs.items() if g in ("3", "4a", "4b") else [(None, rs)]
                for k, r in items:
                    hv = r.get("hash_version")
                    if hv == cur["hash_version"]:
                        continue
                    oc = old_cur[hv]
                    o_, p_ = (k if g in ("3", "4a") else None), (k if g == "4b" else None)
                    outs = [x for x in s["brief"]["platforms"].get(p_, []) if x in schema.current_outputs(s, lg)]
                    then = tuple_for(g, oc, output=o_, platform=p_, platform_outputs=outs)
                    now = tuple_for(g, cur, output=o_, platform=p_, platform_outputs=outs)
                    for f, v in r["tuple"].items():
                        if v == then.get(f) and now.get(f) != v:
                            out.append((lg, g, k, f, v, now.get(f)))
                    out.append((lg, g, k, None, hv, cur["hash_version"]))
        return out

    def events(s, ev):
        out = [{"event": "rewrite", "cause": "repin", "field": "s2v", "old": s["s2v"],
                "new": {k: ver.get(k) for k in ("id", "version", "commit", "dirty")}, "answer": evidence.answer_of(ev)}]
        for lg, g, k, f, a, b in moves(s):
            out.append({"event": "rewrite", "cause": "hash_version", "lang": lg, "gate": g, "key": k,
                        "field": f or "hash_version", "old": a, "new": b})
        return out

    def change(s, ev):
        for lg, g, k, f, a, b in moves(s):
            rec = s["langs"][lg]["approved"][g] if k is None else s["langs"][lg]["approved"][g][k]
            if f is None:
                rec["hash_version"] = b
            else:
                rec["tuple"][f] = b
        s["s2v"] = {k: ver.get(k) for k in ("id", "version", "commit", "dirty")}

    _with_evidence(repo, vdir, state["video"], argv, "repin", label, check_state, change, events,
                   bool(o.get("--proxy")), hooks)
    _out("re-pinned to %s" % cur["s2v_version"])
    return C.OK


def exclude_output(repo, vdir, state, lang, ctx, o, providers, hooks, argv):
    if len(o["_"]) < 2 or not o.get("--expect"):
        raise store.Refused("exclude-output needs an output and --expect <hash12>", C.USAGE)
    out = o["_"][1]
    expect = o["--expect"]

    def dropped(s):
        return sorted(p for p, outs in s["brief"]["platforms"].items() if outs == [out])

    def label(s):
        return labels.exclude(s["video"], hash_of({"video": s["video"], "lang": lang, "output": out,
                                                   "platforms": dropped(s)})[:12])

    def check_state(s):
        if out not in s["brief"]["outputs"]:
            _refuse("%s is not an output of %s" % (out, s["video"]), C.USAGE)
        if len(s["brief"]["outputs"]) == 1:
            _refuse("%s is the last output: to stop the video, abandon it" % out, C.USAGE)
        if label(s) != labels.exclude(s["video"], expect):
            _refuse("--expect %s does not match this exclusion" % expect, C.FAIL)

    def removed(s):
        drop = dropped(s)
        rm = []
        for lg, L in s["langs"].items():
            for g in ("3", "4a"):
                if out in (L["approved"].get(g) or {}):
                    rm.append((lg, "approved", g, out, L["approved"][g][out]))
            for p in drop:
                if p in (L["approved"].get("4b") or {}):
                    rm.append((lg, "approved", "4b", p, L["approved"]["4b"][p]))
            for r in L.get("done_stages", []):
                if r.get("output") == out or r.get("platform") in drop:
                    rm.append((lg, "done", r["stage"], r.get("output") or r.get("platform"), r))
        return rm

    def events(s, ev):
        evs = [{"event": "exclude-output", "output": out, "platforms": dropped(s), "lang": lang,
                "answer": evidence.answer_of(ev)}]
        evs += [{"event": "removed", "lang": lg, "kind": kind, "gate": g, "key": k, "record": r}
                for lg, kind, g, k, r in removed(s)]
        return evs

    def change(s, ev):
        drop = dropped(s)
        s["brief"]["outputs"] = [x for x in s["brief"]["outputs"] if x != out]
        s["brief"]["platforms"] = {p: [x for x in outs if x != out] for p, outs in s["brief"]["platforms"].items()
                                   if p not in drop}
        for L in s["langs"].values():
            for g in ("3", "4a"):
                (L["approved"].get(g) or {}).pop(out, None)
            for p in drop:
                (L["approved"].get("4b") or {}).pop(p, None)
            L["done_stages"] = [r for r in L.get("done_stages", [])
                                if r.get("output") != out and r.get("platform") not in drop]
            for g in ("3", "4a"):
                (L["shown"].get(g) or {}).pop(out, None)
            for p in drop:
                (L["shown"].get("4b") or {}).pop(p, None)
            L["shown_pending"].pop(out, None)
            if out not in L["excluded"]["outputs"]:
                L["excluded"]["outputs"].append(out)
            for p in drop:
                if p not in L["excluded"]["platforms"]:
                    L["excluded"]["platforms"].append(p)

    def after(s):
        for lg in s["langs"]:
            try:
                _mirror_shown(vdir, s, lg)
                d = os.path.join(ctx["repo"], ctx["studio_root"], "out", s["video"], lg)
                if not os.path.isdir(d):
                    continue
                for n in os.listdir(d):
                    if n.startswith("%s.%s." % (out, lg)) and not n.endswith(".EXCLUDED"):
                        os.rename(os.path.join(d, n), os.path.join(d, n + ".EXCLUDED"))
            except OSError as e:  # the exclusion is recorded; renaming is a convenience
                sys.stderr.write("warning: could not mark the excluded files of %s: %s\n" % (lg, e))

    _with_evidence(repo, vdir, state["video"], argv, "exclude-output", label, check_state, change, events,
                   bool(o.get("--proxy")), hooks, after=after)
    _out("excluded %s" % out)
    return C.OK


def unlock(repo, vdir, state, lang, ctx, o, providers, hooks, argv):
    held = o.get("--expect")
    if not held:
        raise store.Refused("unlock needs --expect <held state>", C.USAGE)

    def check_state(s):
        h = s["langs"][lang].get("held")
        if not h:
            _refuse("%s is not held" % lang, C.USAGE)
        if h.get("state") != held:
            _refuse("%s is held as %s, not %s" % (lang, h.get("state"), held), C.FAIL)

    def events(s, ev):
        return [{"event": "unlock", "lang": lang, "held": s["langs"][lang]["held"], "answer": evidence.answer_of(ev)}]

    def change(s, ev):
        L = s["langs"][lang]
        h = L["held"]
        if h.get("state") == "stagnation":
            st = (h.get("detail") or {}).get("stage")
            if st in L["loops"]:
                L["loops"][st] = 0
        L["held"] = None

    _with_evidence(repo, vdir, state["video"], argv, "unlock",
                   lambda s: labels.unlock(s["video"], lang, s["langs"][lang]["held"]["state"]),
                   check_state, change, events,
                   bool(o.get("--proxy")), hooks)
    _out("%s unlocked" % lang)
    return C.OK
