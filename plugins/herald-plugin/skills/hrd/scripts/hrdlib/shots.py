"""Screenshots a human takes for an article (design/herald/06-screenshots.md, 0.15.0).

The writer lists the screens in `<w>screenshots.json`; `plan` checks and records that manifest,
the human drops files into a local inbox, `import` cleans them (an allowlist of image chunks —
the only defence against metadata, which nobody sees at ship) into the article's image
directory, and `stage pass --stage draft` refuses until every listed screenshot is in place.
The rest keeps screenshots from leaving the machine unseen: retakes, orphan checks, the
`screenshots` auto-publish exclusion, publish's one-commit squash, and `scan`/`strip` for
images a human replaced later.
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import struct

from .util import HeraldError, git, git_ok, now_iso, read_json, run

MANIFEST = "screenshots.json"
ID_RE = re.compile(r"^s[0-9]{1,3}$")
VIEWPORT_RE = re.compile(r"^[0-9]{3,4}x[0-9]{3,4}$")
EXTS = ("png", "jpg", "jpeg", "webp")
KINDS = ("privacy", "mismatch")
MAX_BYTES = 10 * 1024 * 1024
# what a hold note on base may say: ids and kind codes only, never the agent's reason text
NOTE_RE = re.compile(r"^screenshots:( s[0-9]{1,3}(\(retake:(privacy|mismatch)\))?)+$")


# --- paths ----------------------------------------------------------------------------------

def inbox_rel(tid):
    return ".claude/herald/inbox/%s" % tid


def manifest_rel(tid):
    from .store import work_rel
    return work_rel(tid, MANIFEST)


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def move_to_removed(root, tid, rels, label=""):
    """Move files (paths relative to root) under memory/shots/removed/<tid>/<UTC time>/ —
    never a delete: a screenshot a human took can always be put back (INV3). A fresh time
    folder per call, so moving the same name twice never overwrites."""
    rels = [r for r in rels if r and os.path.isfile(os.path.join(root, r))]
    if not rels:
        return []
    dest = os.path.join(root, ".claude/herald/memory/shots/removed", tid, _stamp() + (("-" + label) if label else ""))
    out = []
    for r in rels:
        tgt = os.path.join(dest, r)
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        shutil.move(os.path.join(root, r), tgt)
        out.append(r)
    return out


def removed_bytes(root, tid=None):
    """Bytes kept under memory/shots/removed/ (one topic, or all)."""
    d = os.path.join(root, ".claude/herald/memory/shots/removed", *([tid] if tid else []))
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fns in os.walk(d) for f in fns)


def archive_inbox(root, tid, label="inbox"):
    """Move the topic's inbox under removed/ (requeue, drop, cleaned holds, draft pass)."""
    d = os.path.join(root, inbox_rel(tid))
    if not os.path.isdir(d):
        return []
    rels = []
    for dp, _, fns in os.walk(d):
        rels += [os.path.relpath(os.path.join(dp, f), root) for f in fns]
    moved = move_to_removed(root, tid, rels, label)
    shutil.rmtree(d, ignore_errors=True)
    return moved


def blob(root, rel):
    """git blob id of a working-tree file (clean filters / LFS as a commit would store it)."""
    if not os.path.isfile(os.path.join(root, rel)):
        return None
    return run(["git", "hash-object", "--", rel], cwd=root).stdout.strip()


def _file_sha256(root, rel):
    from .hashing import file_hash
    return file_hash(root, rel)


def on_base(root, cfg, rel):
    """True when `rel` is tracked at origin/<base> (P6: never overwritten or moved)."""
    return git_ok(root, "cat-file", "-e", "origin/%s:%s" % (cfg.base, rel))


# --- manifest -------------------------------------------------------------------------------

def load_manifest(root, tid, rev=None):
    """The manifest as a dict, None when the file is absent. Malformed JSON raises."""
    rel = manifest_rel(tid)
    if rev:
        if not git_ok(root, "cat-file", "-e", "%s:%s" % (rev, rel)):
            return None
        try:
            data = json.loads(git(root, "show", "%s:%s" % (rev, rel)))
        except ValueError as e:
            raise HeraldError("%s at %s is not valid JSON: %s" % (rel, rev, e))
    else:
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            return None
        try:
            with open(full, encoding="utf-8") as f:
                data = json.load(f)
        except ValueError as e:
            raise HeraldError("%s is not valid JSON: %s" % (rel, e))
    if data is None:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list):
        raise HeraldError('%s must be {"shots": [...]}' % rel)
    return data


def _spec(shot):
    s = shot.get("spec") if isinstance(shot.get("spec"), dict) else {}
    return {"viewport": s.get("viewport"), "theme": s.get("theme") or "light", "ui_lang": s.get("ui_lang")}


def shot_key(shot):
    """What the screenshot shows — free text (how, crop, alt, mask) left out, so polishing the
    wording never asks for a new screenshot."""
    sp = _spec(shot)
    raw = json.dumps([shot.get("file"), shot.get("url"), sp["viewport"], sp["theme"], sp["ui_lang"]])
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def target(shot):
    sp = _spec(shot)
    return {"id": shot.get("id"), "file": shot.get("file"), "url": shot.get("url"),
            "theme": sp["theme"], "ui_lang": sp["ui_lang"]}


def matches(tgt, shot):
    """Same subject as a recorded retake: same id, or same file, or — both with a url — the
    same url, theme and UI language (viewport is left out: 1px would escape it)."""
    t = target(shot)
    if tgt.get("id") and tgt.get("id") == t["id"]:
        return True
    if tgt.get("file") and tgt.get("file") == t["file"]:
        return True
    return bool(tgt.get("url") and t["url"]) and \
        (tgt.get("url"), tgt.get("theme"), tgt.get("ui_lang")) == (t["url"], t["theme"], t["ui_lang"])


def retakes_for(st, shot):
    return [r for r in st.get("retakes") or [] if isinstance(r, dict) and matches(r.get("target") or {}, shot)]


def _body_refs(root, cfg, slug):
    """Repo paths of the images the source body references (the gate's own reading)."""
    from .validate import IMG_RE, image_refs
    body = cfg.body_path(slug)
    full = os.path.join(root, body)
    if not os.path.isfile(full):
        return []
    with open(full, encoding="utf-8") as f:
        text = f.read()
    return image_refs(root, body, text)


def check_manifest(root, cfg, tid, st, man):
    """Errors (refuse) and warnings for one manifest against the body (design §2.2)."""
    from .validate import ignored, resolve_image_ref
    slug = st["slug"]
    img = cfg.image_dir(slug).rstrip("/") + "/"
    body = cfg.body_path(slug)
    refs = _body_refs(root, cfg, slug)
    errors, warnings, seen = [], [], set()
    files_seen, refs_seen = set(), set()
    for i, s in enumerate(man["shots"]):
        if not isinstance(s, dict):
            errors.append("shots[%d] is not an object" % i)
            continue
        sid = s.get("id")
        where = sid if isinstance(sid, str) else "shots[%d]" % i
        if not isinstance(sid, str) or not ID_RE.match(sid):
            errors.append("%s: id must match s1..s999" % where)
        elif sid in seen:
            errors.append("%s: duplicate id" % sid)
        seen.add(sid)
        f = s.get("file")
        if not isinstance(f, str) or not f.startswith(img) or "/" in f[len(img):] or ".." in f.split("/"):
            errors.append("%s: file must sit directly under %s" % (where, img))
            continue
        if f in files_seen or s.get("ref") in refs_seen:
            errors.append("%s: another screenshot already uses this file or ref" % where)
        files_seen.add(f)
        refs_seen.add(s.get("ref"))
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext not in EXTS:
            errors.append("%s: file extension must be one of %s" % (where, ", ".join(EXTS)))
        if ignored(root, f):
            errors.append("%s: %s is gitignored — it would deploy from this machine only" % (where, f))
        if on_base(root, cfg, f):
            errors.append("%s: %s already exists on %s — use a new file name (an existing image is never "
                          "overwritten)" % (where, f, cfg.base))
        how = s.get("how")
        if not isinstance(how, list) or not how or not all(isinstance(h, dict) and h.get("step") for h in how):
            errors.append("%s: how must list the steps to reach the screen (from research.md ## Screen paths)" % where)
        sp = s.get("spec") if isinstance(s.get("spec"), dict) else {}
        if sp.get("viewport") is not None and not VIEWPORT_RE.match(str(sp.get("viewport"))):
            errors.append("%s: spec.viewport must look like 1280x800" % where)
        if sp.get("theme") not in (None, "light", "dark"):
            errors.append("%s: spec.theme must be light or dark" % where)
        mask = s.get("mask")
        if mask is not None and not (isinstance(mask, list) and all(isinstance(m, str) for m in mask)):
            errors.append("%s: mask must be a list of categories" % where)
        ref = s.get("ref")
        if not isinstance(ref, str) or resolve_image_ref(root, body, ref) != f:
            errors.append("%s: ref %r does not resolve to %s the way the gate reads images" % (where, ref, f))
        elif refs.count(f) != 1:
            errors.append("%s: the article must reference %s exactly once (found %d)" % (where, ref, refs.count(f)))
        if any(r.get("kind") == "privacy" for r in retakes_for(st, s)) and not mask:
            errors.append("%s: retaken for privacy — mask must name what to hide" % where)
    # refresh: a base image the body no longer references (left as in 0.14.0; the PR says so)
    tracked = [p for p in git(root, "ls-tree", "-r", "--name-only", "origin/%s" % cfg.base, "--",
                              cfg.image_dir(slug), check=False).splitlines() if p]
    unref = sorted(p for p in tracked if p not in refs)
    if unref:
        warnings.append("existing images not referenced in the body's image syntax (check frontmatter or "
                        "components before removing any): %s" % ", ".join(unref))
    # files this topic added that nothing seems to reference (a frontmatter or MDX reference the
    # gate cannot read may be fine — a warning only)
    added = [p for p in git(root, "ls-files", "--others", "--exclude-standard", "--", cfg.image_dir(slug),
                            check=False).splitlines() if p]
    loose = sorted(p for p in added if p not in refs and p not in files_seen)
    if loose:
        warnings.append("new images the article does not reference: %s" % ", ".join(loose))
    return errors, warnings, unref


# --- plan -----------------------------------------------------------------------------------

def _recorded_files(st):
    rec = st.get("screenshots") or {}
    return list(dict.fromkeys(list(rec.get("files") or []) + list(st.get("shot_files") or [])))


def plan(root, cfg, tid, check_only=False):
    from .store import load_state, save_state
    st = load_state(root, tid)
    slug = st.get("slug")
    if not slug:
        raise HeraldError("no slug yet for %s" % tid)
    man = load_manifest(root, tid)
    if not man or not man["shots"]:
        if check_only or not st.get("screenshots"):
            return {"shots": 0, "pending": [], "warnings": []}
        rec = st.pop("screenshots")
        files = list(rec.get("files") or [])
        st["shot_files"] = list(dict.fromkeys(list(st.get("shot_files") or []) + files))
        save_state(root, tid, st)
        moved = move_to_removed(root, tid, [f for f in files if not on_base(root, cfg, f)], "unlisted")
        return {"shots": 0, "pending": [], "moved": moved, "warnings": []}
    errors, warnings, unref = check_manifest(root, cfg, tid, st, man)
    if errors:
        raise HeraldError("screenshots.json: " + "; ".join(errors))
    if check_only:
        return {"shots": len(man["shots"]), "ok": True, "warnings": warnings}
    prev = st.get("screenshots") or {}
    prev_shots = prev.get("shots") or {}
    current = [s["file"] for s in man["shots"]]
    files = list(dict.fromkeys(list(prev.get("files") or []) + current))
    to_move = [f for f in prev.get("files") or [] if f not in current]
    shots = {}
    for s in man["shots"]:
        r = prev_shots.get(s["id"]) or {}
        key = shot_key(s)
        same = r.get("key") == key
        if same and r.get("sha") and blob(root, s["file"]) == r["sha"]:
            shots[s["id"]] = {"status": "ready", "key": key, "sha": r["sha"]}
            continue
        if not r.get("sha") and retakes_for(st, s):  # a retake cut off before its file moved
            to_move.append(s["file"])
        since = r.get("waiting_since") if same and r.get("status") == "pending" and r.get("waiting_since") else now_iso()
        shots[s["id"]] = {"status": "pending", "key": key, "sha": None, "waiting_since": since}
    st["screenshots"] = {"manifest": _file_sha256(root, manifest_rel(tid)),
                         "body": _file_sha256(root, cfg.body_path(slug)),
                         "awaiting": True, "files": files, "shots": shots,
                         "unreferenced_base_images": unref}
    save_state(root, tid, st)
    moved = move_to_removed(root, tid, [f for f in dict.fromkeys(to_move) if not on_base(root, cfg, f)], "unlisted")
    return {"shots": len(shots), "pending": sorted(k for k, v in shots.items() if v["status"] == "pending"),
            "moved": moved, "warnings": warnings}


# --- status / note --------------------------------------------------------------------------

def hold_note(st):
    """The only hold note base may carry: ids and retake kind codes (design §2.8)."""
    rec = st.get("screenshots") or {}
    parts = []
    for sid, r in sorted((rec.get("shots") or {}).items(), key=lambda kv: int(kv[0][1:])):
        if r.get("status") != "pending":
            continue
        kinds = [x.get("kind") for x in st.get("retakes") or []
                 if isinstance(x, dict) and (x.get("target") or {}).get("id") == sid and x.get("kind") in KINDS]
        parts.append("%s(retake:%s)" % (sid, kinds[-1]) if kinds else sid)
    return "screenshots: " + " ".join(parts) if parts else None


def check_note(note):
    if not NOTE_RE.match(note or ""):
        raise HeraldError("a screenshots hold note lists ids and kind codes only — use the `note` "
                          "`HRD shot status` prints (e.g. `screenshots: s1 s2(retake:privacy)`)")


def resume_at_import(root, cfg, st):
    rec = st.get("screenshots") or {}
    if st.get("stage") != "draft" or not rec.get("awaiting"):
        return False
    tid, slug = st["topic_id"], st["slug"]
    return rec.get("manifest") == _file_sha256(root, manifest_rel(tid)) and \
        rec.get("body") == _file_sha256(root, cfg.body_path(slug))


def status(root, cfg, tid):
    from .store import load_state
    st = load_state(root, tid)
    rec = st.get("screenshots") or {}
    man = None
    try:
        man = load_manifest(root, tid)
    except HeraldError:
        pass
    by_id = {s.get("id"): s for s in (man or {}).get("shots") or [] if isinstance(s, dict)}
    items = []
    for sid, r in sorted((rec.get("shots") or {}).items(), key=lambda kv: int(kv[0][1:])):
        s = by_id.get(sid) or {}
        ext = (s.get("file") or "").rsplit(".", 1)[-1]
        rts = retakes_for(st, s) if s else []
        items.append({"id": sid, "status": r.get("status"), "file": s.get("file"), "inbox_name": "%s.%s" % (sid, ext),
                      "purpose": s.get("purpose"), "how": s.get("how"), "url": s.get("url"), "spec": s.get("spec"),
                      "mask": s.get("mask"), "alt": s.get("alt"),
                      "retake": ({"kind": rts[-1].get("kind"), "reason": rts[-1].get("reason")} if rts else None)})
    return {"inbox": inbox_rel(tid), "shots": items, "removed_bytes": removed_bytes(root, tid),
            "pending": [i["id"] for i in items if i["status"] == "pending"],
            "all_ready": bool(items) and all(i["status"] == "ready" for i in items),
            "awaiting": bool(rec.get("awaiting")), "resume_at_import": resume_at_import(root, cfg, st),
            "note": hold_note(st), "files": _recorded_files(st),
            "unreferenced_base_images": rec.get("unreferenced_base_images") or [],
            "decisions": st.get("shot_decisions") or []}


# --- import ---------------------------------------------------------------------------------

def _same_as_recorded(path, file_rel, sha):
    """The inbox file is the original of what is already recorded (cleaned, its git blob id
    matches) — an import that stopped before moving it. Without git filters the blob id is
    sha1("blob <n>\\0" + bytes); with filters it simply never matches (a warning, never a loss)."""
    if not sha:
        return False
    try:
        with open(path, "rb") as f:
            clean, _ = sanitize(f.read(), file_rel.rsplit(".", 1)[-1].lower())
    except (OSError, HeraldError):
        return False
    return hashlib.sha1(b"blob %d\x00" % len(clean) + clean).hexdigest() == sha


def _parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def import_(root, cfg, tid):
    from .store import load_state, save_state
    st = load_state(root, tid)
    rec = st.get("screenshots")
    if not rec:
        raise HeraldError("no screenshots planned for %s — `HRD shot plan --topic %s` first" % (tid, tid))
    if rec.get("manifest") != _file_sha256(root, manifest_rel(tid)) or \
            rec.get("body") != _file_sha256(root, cfg.body_path(st["slug"])):
        raise HeraldError("the article or screenshots.json changed since `HRD shot plan` — run it again")
    man = load_manifest(root, tid) or {"shots": []}
    by_id = {s["id"]: s for s in man["shots"]}
    inbox = os.path.join(root, inbox_rel(tid))
    names = os.listdir(inbox) if os.path.isdir(inbox) else []
    imported, problems, warnings, done, stale = [], [], [], [], []
    for sid, r in sorted(rec["shots"].items(), key=lambda kv: int(kv[0][1:])):
        if sid not in by_id:
            continue
        s = by_id[sid]
        if r.get("status") != "pending":
            for n in [n for n in names if n.rsplit(".", 1)[0] == sid]:
                if _same_as_recorded(os.path.join(inbox, n), s["file"], r.get("sha")):
                    stale.append(os.path.relpath(os.path.join(inbox, n), root))  # an import cut off before the move
                else:  # never a silent replacement
                    warnings.append("%s is already imported — %s is not used; to replace it, retake it (`HRD loopback "
                                    "--human --retake %s …`), then save the new file into the inbox again"
                                    % (sid, n, sid))
            continue
        want = s["file"].rsplit(".", 1)[-1].lower()
        cands = [n for n in names if n.rsplit(".", 1)[0] == sid and not n.startswith(".")]
        if not cands:
            continue
        name = cands[0]
        if len(cands) > 1:
            problems.append("%s: more than one file (%s) — keep one named %s.%s" % (sid, ", ".join(cands), sid, want))
            continue
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext != want and not ({ext, want} <= {"jpg", "jpeg"}):
            problems.append("%s: %s has the wrong extension — save it as %s.%s" % (sid, name, sid, want))
            continue
        path = os.path.join(inbox, name)
        since = _parse_iso(r.get("waiting_since"))
        if since is not None and os.path.getmtime(path) < since:
            problems.append("%s: %s was made before %s started waiting (%s) — if it is a new screenshot, save it "
                            "again and put it back" % (sid, name, sid, r.get("waiting_since")))
            continue
        if os.path.getsize(path) > MAX_BYTES:
            problems.append("%s: %s is larger than 10 MB" % (sid, name))
            continue
        with open(path, "rb") as f:
            data = f.read()
        try:
            clean, warn = sanitize(data, want)
        except HeraldError as e:
            problems.append("%s: %s — %s" % (sid, name, e))
            continue
        warnings += ["%s: %s" % (sid, w) for w in warn]
        vp = _spec(s)["viewport"]
        width = image_width(clean)
        if vp and width and width > 2 * int(vp.split("x")[0]):
            warnings.append("%s: %dpx wide — more than twice the %s viewport (a Retina capture?)" % (sid, width, vp))
        dest = os.path.join(root, s["file"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(clean)
        r.update(status="ready", sha=blob(root, s["file"]))
        r.pop("waiting_since", None)
        imported.append(sid)
        done.append(os.path.relpath(path, root))
    save_state(root, tid, st)
    # the original leaves the inbox once its cleaned copy is recorded — moved, never deleted (INV3) —
    # so an inbox file for an imported screenshot is always a new version a human put there
    move_to_removed(root, tid, done + stale, "imported")
    planned = {sid for sid in rec["shots"]}
    without = {str(d.get("id", ""))[5:] for d in st.get("shot_decisions") or [] if d.get("choice") == "without"}
    for n in names:
        stem = n.rsplit(".", 1)[0]
        if n.startswith(".") or stem in planned:
            continue
        if stem in without:
            warnings.append("%s: %s was left out by a human's choice — the file is not used" % (n, stem))
            continue
        hint = next((sid for sid in planned if stem.lower() == sid), None)
        warnings.append("%s in the inbox matches no screenshot%s — name files s1.png, s2.png, … as the guide says"
                        % (n, " (did you mean %s?)" % hint if hint else ""))
    remaining = sorted((k for k, v in rec["shots"].items() if v.get("status") == "pending"), key=lambda k: int(k[1:]))
    return {"imported": imported, "remaining": remaining, "problems": problems, "warnings": warnings,
            "note": hold_note(st)}


# --- decide / retake ------------------------------------------------------------------------

def decide_without(root, tid, sid):
    from .store import load_state, save_state
    if os.environ.get("HRD_UNATTENDED") == "1":
        raise HeraldError("`shot decide` records a human's decision — not allowed in unattended sessions")
    st = load_state(root, tid)
    man = load_manifest(root, tid) or {"shots": []}
    shot = next((s for s in man["shots"] if isinstance(s, dict) and s.get("id") == sid), None)
    if not shot:
        raise HeraldError("%s is not in screenshots.json" % sid)
    st.setdefault("shot_decisions", []).append({"id": "shot:%s" % sid, "file": shot.get("file"),
                                                "choice": "without", "at": now_iso()})
    save_state(root, tid, st)
    return {"decided": sid, "next": "HRD loopback --topic %s --human, then the writer removes it" % tid}


def mark_retake(st, man, ids, kind, reason):
    """Record retakes in `st` (the caller saves state first, then moves the returned files —
    a cut between the two leaves files plan moves later, never a `ready` problem screen)."""
    if kind not in KINDS:
        raise HeraldError("--retake-kind must be privacy or mismatch")
    rec = st.get("screenshots") or {}
    by_id = {s.get("id"): s for s in (man or {}).get("shots") or [] if isinstance(s, dict)}
    files = []
    for sid in ids:
        if sid not in by_id or sid not in (rec.get("shots") or {}):
            raise HeraldError("%s is not a planned screenshot" % sid)
        s = by_id[sid]
        st.setdefault("retakes", []).append({"target": target(s), "kind": kind, "reason": (reason or "")[:300],
                                             "at": now_iso()})
        rec["shots"][sid].update(status="pending", sha=None, waiting_since=now_iso())
        files.append(s["file"])
    return files


# --- stage pass / orphans -------------------------------------------------------------------

def orphans(root, cfg, st, man):
    """Recorded screenshot files still in the working tree but no longer listed (plan did not
    move them). Only Herald's own records count — illustrator images, frontmatter references
    and manifest-less topics are never judged here."""
    current = {s.get("file") for s in (man or {}).get("shots") or [] if isinstance(s, dict)}
    return [f for f in _recorded_files(st) if f not in current and os.path.isfile(os.path.join(root, f))
            and not on_base(root, cfg, f)]


def draft_problems(root, cfg, tid, st):
    man = load_manifest(root, tid)
    rec = st.get("screenshots")
    out = []
    if man and man["shots"]:
        if not rec:
            return ["screenshots.json is not planned — run `HRD shot plan --topic %s`" % tid]
        if rec.get("manifest") != _file_sha256(root, manifest_rel(tid)):
            out.append("screenshots.json changed since `HRD shot plan` — run it again")
        if rec.get("body") != _file_sha256(root, cfg.body_path(st["slug"])):
            out.append("the article changed since `HRD shot plan` — run it again")
        by_id = {s.get("id"): s for s in man["shots"] if isinstance(s, dict)}
        if set(by_id) != set(rec.get("shots") or {}):
            out.append("screenshots.json lists other shots than were planned — run `HRD shot plan` again")
        for sid, r in sorted((rec.get("shots") or {}).items()):
            s = by_id.get(sid) or {}
            if r.get("status") != "ready":
                out.append("%s is still pending — `HRD shot import --topic %s`" % (sid, tid))
            elif blob(root, s.get("file") or "") != r.get("sha"):
                out.append("%s: %s is not the file `HRD shot import` wrote — `HRD shot plan` first (it becomes "
                           "pending), then the edited version into the inbox and `HRD shot import`"
                           % (sid, s.get("file")))
    elif rec:
        out.append("screenshots.json is gone but screenshots are recorded — run `HRD shot plan --topic %s`" % tid)
    left = orphans(root, cfg, st, man)
    if left:
        out.append("screenshots no longer listed are still in place: %s — run `HRD shot plan --topic %s`"
                   % (", ".join(left), tid))
    return out


# --- gate (writer's pre-check) --------------------------------------------------------------

def _png_1x1():
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")) + chunk(b"IEND", b""))


_PLACEHOLDER = {
    "png": _png_1x1(),
    "jpg": bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c"
                         "1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b08"
                         "0001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002"
                         "010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433"
                         "627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a73"
                         "7475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7"
                         "c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9"),
    "webp": __import__("base64").b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA=="),
}
_PLACEHOLDER["jpeg"] = _PLACEHOLDER["jpg"]


def gate_relaxed(root, cfg, tid, st):
    """The writer's `HRD gate --topic` on its own herald branch in the draft stage — nothing else
    (ship, translation gates, base) ever relaxes a missing image (INV2)."""
    from .store import branch_name
    if st.get("stage") != "draft" or not st.get("slug"):
        return False
    head = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    return head == branch_name(tid, st["slug"])


def pending_files(root, tid, st):
    """Manifest files not yet `ready` (every manifest file before the first plan)."""
    try:
        man = load_manifest(root, tid)
    except HeraldError:
        return []
    rec = (st.get("screenshots") or {}).get("shots") or {}
    out = []
    for s in (man or {}).get("shots") or []:
        if isinstance(s, dict) and isinstance(s.get("file"), str) and (rec.get(s.get("id")) or {}).get("status") != "ready":
            out.append(s["file"])
    return out


def with_placeholders(root, files, fn):
    """Run fn() with 1x1 stand-ins where pending screenshots will go; always removed after."""
    made = []
    try:
        for f in files:
            full = os.path.join(root, f)
            if os.path.exists(full):
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(_PLACEHOLDER.get(f.rsplit(".", 1)[-1].lower(), _PLACEHOLDER["png"]))
            made.append(full)
        return fn()
    finally:
        for full in made:
            try:
                os.remove(full)
            except OSError:
                pass


# --- sanitizing (allowlist) -----------------------------------------------------------------

PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"pHYs"}
JPEG_SOF = set(range(0xC0, 0xD0)) - {0xC4, 0xC8}  # SOFn and DAC (0xCC); DHT and JPG are not frames
JPEG_KEEP = JPEG_SOF | {0xC4, 0xDB, 0xDD, 0xDA, 0xDC}  # DHT, DQT, DRI, SOS, DNL
WEBP_KEEP = {b"VP8 ", b"VP8L", b"VP8X", b"ALPH"}


ICC_WARN = "a non-sRGB colour profile was removed — colours may shift slightly"


def _srgb(profile, png=False):
    """An sRGB profile (its removal changes nothing a browser shows). A PNG iCCP is `name\\0`,
    a method byte and the deflated profile; anything unreadable counts as non-sRGB (a warning,
    never a refusal)."""
    import zlib
    if png:
        name, _, rest = profile.partition(b"\x00")
        if b"sRGB" in name:
            return True
        try:
            profile = zlib.decompress(rest[1:])
        except zlib.error:
            return False
    return b"sRGB" in profile[:4096]


def kind_of(data):
    if data.startswith(PNG_SIG):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def sanitize(data, ext):
    """Keep only what draws the picture; returns (bytes, warnings). Anything it cannot read is
    refused — an unknown structure is never passed on (design §2.5)."""
    kind = kind_of(data)
    want = "jpg" if ext in ("jpg", "jpeg") else ext
    if kind is None:
        raise HeraldError("not a PNG, JPEG or WebP image")
    if kind != want:
        raise HeraldError("the file is a %s but is named .%s" % (kind.upper(), ext))
    return {"png": _png, "jpg": _jpeg, "webp": _webp}[kind](data)


def _png(data):
    out, pos, warn, seen_end, kept = [PNG_SIG], 8, [], False, set()
    first = True
    while pos < len(data):
        if pos + 8 > len(data):
            raise HeraldError("truncated PNG chunk")
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        end = pos + 12 + n
        if end > len(data):
            raise HeraldError("truncated PNG chunk %r" % typ)
        if first and typ != b"IHDR":
            raise HeraldError("PNG does not start with IHDR")
        first = False
        if typ in PNG_KEEP:
            out.append(data[pos:end])
            kept.add(typ)
        elif typ == b"iCCP" and not _srgb(data[pos + 8:pos + 8 + n], png=True):
            warn.append(ICC_WARN)
        pos = end
        if typ == b"IEND":
            seen_end = True
            break
    if not seen_end:
        raise HeraldError("PNG has no IEND")
    if b"IDAT" not in kept:
        raise HeraldError("PNG has no image data")
    return b"".join(out), warn


def _jpeg(data):
    out, pos, warn, frame, scanned = [b"\xff\xd8"], 2, [], False, False
    while True:
        if pos >= len(data) or data[pos] != 0xFF:
            raise HeraldError("JPEG marker expected at byte %d" % pos)
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            raise HeraldError("truncated JPEG")
        m = data[pos]
        pos += 1
        if m == 0xD9:  # EOI — anything after it is dropped
            if not (frame and scanned):
                raise HeraldError("JPEG has no image data")
            out.append(b"\xff\xd9")
            return b"".join(out), warn
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            out.append(bytes([0xFF, m]))
            continue
        if pos + 2 > len(data):
            raise HeraldError("truncated JPEG segment")
        n = struct.unpack(">H", data[pos:pos + 2])[0]
        seg = data[pos + 2:pos + n]
        if n < 2 or len(seg) != n - 2:
            raise HeraldError("truncated JPEG segment 0x%02X" % m)
        nxt = pos + n
        if m == 0xE0:
            if seg[:5] == b"JFIF\x00" and len(seg) >= 14:
                body = seg[:12] + b"\x00\x00"  # thumbnail cut to 0x0
                out.append(b"\xff\xe0" + struct.pack(">H", len(body) + 2) + body)
        elif m == 0xEE:
            if seg[:5] == b"Adobe":
                out.append(b"\xff\xee" + data[pos:nxt])
        elif m in JPEG_KEEP:
            out.append(bytes([0xFF, m]) + data[pos:nxt])
            frame = frame or m in JPEG_SOF
            scanned = scanned or m == 0xDA
        elif m == 0xE2 and seg[:12] == b"ICC_PROFILE\x00":
            if ICC_WARN not in warn and not _srgb(seg[14:]):
                warn.append(ICC_WARN)
        pos = nxt
        if m == 0xDA:  # entropy-coded data up to the next marker that is not RSTn or a stuffed 0xFF00
            start = pos
            while True:
                j = data.find(b"\xff", pos)
                if j < 0 or j + 1 >= len(data):
                    raise HeraldError("JPEG scan never ends")
                b = data[j + 1]
                if b == 0x00 or 0xD0 <= b <= 0xD7 or b == 0xFF:
                    pos = j + 1 if b == 0xFF else j + 2
                    continue
                out.append(data[start:j])
                pos = j
                break


def _webp(data):
    size = struct.unpack("<I", data[4:8])[0]
    if size + 8 > len(data) or size < 4:
        raise HeraldError("truncated WebP")
    pos, end, chunks, warn = 12, 8 + size, [], []
    vp8x, image = None, False
    while pos < end:
        if pos + 8 > end:
            raise HeraldError("truncated WebP chunk")
        typ = data[pos:pos + 4]
        n = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        nxt = pos + 8 + n + (n & 1)
        if pos + 8 + n > end:
            raise HeraldError("truncated WebP chunk %r" % typ)
        if typ in (b"ANIM", b"ANMF"):
            raise HeraldError("animated WebP is not a screenshot")
        if typ == b"VP8X":
            vp8x = len(chunks)
        if typ in WEBP_KEEP:
            chunks.append(bytearray(data[pos:min(nxt, end)]))
            image = image or typ in (b"VP8 ", b"VP8L")
        elif typ == b"ICCP" and not _srgb(data[pos + 8:pos + 8 + n]):
            warn.append(ICC_WARN)
        pos = nxt
    if not image:
        raise HeraldError("WebP has no image data")
    if vp8x is not None:
        chunks[vp8x][8] &= ~(0x20 | 0x08 | 0x04 | 0x02) & 0xFF  # ICC, EXIF, XMP, animation flags off
    body = b"WEBP" + b"".join(bytes(c) for c in chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body, warn


def image_width(data):
    k = kind_of(data)
    try:
        if k == "png":
            return struct.unpack(">I", data[16:20])[0]
        if k == "jpg":
            pos = 2
            while pos + 4 <= len(data):
                if data[pos] != 0xFF:
                    return None
                m = data[pos + 1]
                n = struct.unpack(">H", data[pos + 2:pos + 4])[0]
                if m in JPEG_SOF and m != 0xCC:
                    return struct.unpack(">H", data[pos + 7:pos + 9])[0]
                pos += 2 + n
        if k == "webp" and data[12:16] == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little")
    except (struct.error, IndexError):
        return None
    return None


def dirty(data, ext):
    """Why a file would not pass as-is (None when clean): what scan reports."""
    try:
        clean, _ = sanitize(data, ext)
    except HeraldError as e:
        return str(e)
    return None if clean == data else "metadata or bytes outside the image"


# --- scan / strip ---------------------------------------------------------------------------

def slug_files(root, cfg, slug):
    """Every screenshot recorded for this slug, by any topic (refresh topics included), with
    paths recorded under an old slug (`status --move`) mapped onto the current image dir."""
    from .integrity import moved_image_path
    from .store import load_published
    pub = load_published(root)
    art = next((a for a in pub.get("articles") or [] if a.get("slug") == slug), None) or {}
    # `status --move` appends every old slug to the same article (A→B→C lists A and B)
    old = [m["slug"] for m in art.get("moved_from") or [] if isinstance(m, dict) and m.get("slug")]
    work = os.path.join(root, ".claude/herald/work")
    files = []
    for tid in sorted(os.listdir(work)) if os.path.isdir(work) else []:
        st = read_json(os.path.join(work, tid, "state.json")) or {}
        if st.get("slug") != slug:
            continue
        for f in _recorded_files(st):
            files.append(moved_image_path(cfg, slug, f, old))
    return [f for f in dict.fromkeys(files) if f.rsplit(".", 1)[-1].lower() in EXTS]


def scan(root, cfg, slug):
    found = []
    for f in slug_files(root, cfg, slug):
        full = os.path.join(root, f)
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as fh:
            why = dirty(fh.read(), f.rsplit(".", 1)[-1].lower())
        if why:
            found.append({"file": f, "problem": why})
    return found


def strip(root, rel):
    full = os.path.join(root, rel)
    with open(full, "rb") as f:
        data = f.read()
    clean, warn = sanitize(data, rel.rsplit(".", 1)[-1].lower())
    if clean != data:
        with open(full, "wb") as f:
            f.write(clean)
    return {"file": rel, "changed": clean != data, "warnings": warn}


# --- publish: one commit, scope ------------------------------------------------------------

def has_records(st):
    return bool(_recorded_files(st or {}))


def _remote_branch(root, branch):
    proc = run(["git", "ls-remote", "--heads", "origin", branch], cwd=root, check=False)
    if proc.returncode != 0:
        raise HeraldError("`git ls-remote origin` failed — cannot tell whether %s was pushed; retry when the "
                          "remote is reachable" % branch)
    return proc.stdout.split()[0] if proc.stdout.strip() else None


def squash(root, cfg, tid):
    """Publish step 4 for a topic with screenshots (P7): rebuild the branch as one commit on
    the merge-base (or on what was already pushed), so WIP commits holding screens no one
    reviewed never reach the remote."""
    from .commits import _match, pr_scope_globs, topic_langs
    from .store import branch_name, load_state
    st = load_state(root, tid)
    slug = st.get("slug")
    if not has_records(st):
        return {"squashed": False, "reason": "no screenshots recorded"}
    branch = branch_name(tid, slug)
    head = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    if head != branch:
        raise HeraldError("squash runs on %s (now on %s)" % (branch, head or "a detached HEAD"))
    remote = _remote_branch(root, branch)
    base = git(root, "merge-base", "HEAD", "origin/%s" % cfg.base).strip()
    globs = pr_scope_globs(cfg, tid, slug, topic_langs(root, tid))
    changed = [p for p in git(root, "diff", "--name-only", "-z", base, "HEAD").split("\0") if p]
    changed += [p for p in git(root, "diff", "--cached", "--name-only", "-z").split("\0") if p]
    bad = sorted({p for p in changed if not _match(p, globs)})
    if bad:
        raise HeraldError("changes outside this topic's PR scope: %s — remove them before publishing" % ", ".join(bad))
    msg = "feat(herald): %s %s" % (tid, slug)
    if remote:
        git(root, "fetch", "-q", "origin", "%s:refs/remotes/origin/%s" % (branch, branch))
        if not git_ok(root, "merge-base", "--is-ancestor", remote, "HEAD"):
            raise HeraldError("origin/%s is not part of this branch's history — a human sorts it out" % branch)
        if git(root, "merge-base", remote, "origin/%s" % cfg.base).strip() != base:
            # base was merged in after the push: one commit on the pushed head would carry base's
            # changes into this PR's diff
            raise HeraldError("%s was merged with %s after it was pushed — a human sorts out the pushed branch "
                              "first" % (branch, cfg.base))
        onto = remote
    else:
        onto = base
    git(root, "reset", "-q", "--soft", onto)
    if git(root, "write-tree").strip() == git(root, "rev-parse", "%s^{tree}" % onto).strip():
        return {"squashed": True, "onto": onto, "commit": None, "remote": bool(remote)}
    git(root, "commit", "-q", "-m", msg)
    return {"squashed": True, "onto": onto, "commit": git(root, "rev-parse", "HEAD").strip(), "remote": bool(remote)}


def scope_problems(root, cfg, tid, rev="HEAD", publish=False):
    """Extra `HRD scope` checks (design §2.10). Every call: no screenshot that left the manifest
    is still in the tree. Publish (no --rev) only: a topic with screenshots is in squash shape."""
    from .store import branch_name, load_state, read_json_at, work_rel
    if rev and rev != "HEAD":
        st = read_json_at(root, rev, work_rel(tid, "state.json")) or {}
        try:
            man = load_manifest(root, tid, rev=rev)
        except HeraldError:
            man = None
        tree = set(git(root, "ls-tree", "-r", "--name-only", rev, check=False).splitlines())
    else:
        st = load_state(root, tid)
        try:
            man = load_manifest(root, tid)
        except HeraldError:
            man = None
        tree = set(git(root, "ls-tree", "-r", "--name-only", "HEAD", check=False).splitlines())
    if not has_records(st):
        return []
    current = {s.get("file") for s in (man or {}).get("shots") or [] if isinstance(s, dict)}
    out = ["%s left screenshots.json but is still committed" % f for f in _recorded_files(st)
           if f not in current and f in tree and not on_base(root, cfg, f)]
    if publish:
        branch = branch_name(tid, st.get("slug"))
        base = git(root, "merge-base", "HEAD", "origin/%s" % cfg.base).strip()
        parent = git(root, "rev-parse", "HEAD^", check=False).strip()
        head = git(root, "rev-parse", "HEAD").strip()
        remote = git(root, "rev-parse", "--verify", "-q", "refs/remotes/origin/%s" % branch, check=False).strip()
        if not (parent == base or (remote and (parent == remote or head == remote))):
            out.append("the branch is not one commit on its base — run `HRD shot squash --topic %s` first" % tid)
    return out


def excluded(root, cfg, tid, rev, changed):
    """The `screenshots` auto-publish exclusion, fail-closed (design §2.10)."""
    from .store import read_json_at, work_rel
    st = (read_json_at(root, rev, work_rel(tid, "state.json")) if rev else
          read_json(os.path.join(root, work_rel(tid, "state.json")))) or {}
    try:
        man = load_manifest(root, tid, rev=rev) if rev else load_manifest(root, tid)
    except HeraldError:
        return has_records(st)  # records but an unreadable manifest
    if man and man.get("shots"):
        return True
    return bool(set(_recorded_files(st)) & set(changed))
