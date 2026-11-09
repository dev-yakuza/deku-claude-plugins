"""Screenshots a human takes for an article (design/herald/06-screenshots.md, 0.15.0).

The writer lists the screens in `<w>screenshots.json`; `plan` checks and records that manifest,
the human drops files into a local inbox, `import` cleans them (an allowlist of image chunks —
the only defence against metadata, which nobody sees at ship) into the article's image
directory, and `stage pass --stage draft` refuses until every listed screenshot is in place.
The rest keeps screenshots from leaving the machine unseen: retakes, orphan checks, the
`screenshots` auto-publish exclusion, publish's one-commit squash, and `scan`/`strip` for
images a human replaced later.

0.16.0 (design/herald/07-auto-capture.md) adds automatic capture of public web pages: a manifest
entry may ask for `capture: auto`; `plan` decides per entry whether Herald may take it, `capture`
runs the configured argv template (never a shell) and a human confirms every captured screen
before it can pass draft or leave the machine. Whether a file is an unconfirmed capture is told
by evidence in two protected ledgers (rule U), never by a state field.
"""

import datetime
import hashlib
import ipaddress
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import threading
import time
import urllib.parse

from .util import HeraldError, git, git_ok, now_iso, read_json, run

MANIFEST = "screenshots.json"
ID_RE = re.compile(r"^s[0-9]{1,3}$")
VIEWPORT_RE = re.compile(r"^[0-9]{3,4}x[0-9]{3,4}$")
EXTS = ("png", "jpg", "jpeg", "webp")
KINDS = ("privacy", "mismatch")
MAX_BYTES = 10 * 1024 * 1024
# what a hold note on base may say: ids and kind codes only, never the agent's reason text
NOTE_RE = re.compile(r"^screenshots:( s[0-9]{1,3}(\((retake:(privacy|mismatch)|confirm)\))?)+$")

# --- automatic capture (design 07) ---
CAPTURES = ".claude/herald/ledger/captures.jsonl"  # under the guard's LEDGER glob: ask attended, deny unattended
CONFIRMATIONS = ".claude/herald/ledger/confirmations.jsonl"
LEDGER_FIELDS = ("topic", "id", "key", "blob", "sha256")
URL_RE = re.compile(r"^https://[A-Za-z0-9\-._~:/?#\[\]@!&()*+,;=%]+$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$")
# reasons that depend on config alone: a confirmed auto screenshot survives them (§2.3 row 5b)
CONFIG_REASONS = ("no-tool", "no-scheme", "no-lang")
FAIL_CODES = ("dns-private", "dns-fail", "bad-value", "timeout", "exit-nonzero", "no-file", "bad-format")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "cmd", "cmd.exe", "powershell", "pwsh",
          "env", "python", "python3", "node", "perl", "ruby", "xargs", "eval", "exec"}
INLINE_FLAGS = ("-c", "/c", "-e", "--eval", "--call", "eval")
SHORT_BUNDLE_RE = re.compile(r"^-[A-Za-z]*[ce][A-Za-z]*$")  # -lc, -ec: a shell's or interpreter's inline code
PLACEHOLDERS = ("{w}", "{h}", "{scheme}", "{lang}", "{url}", "{out}")
DNS_TIMEOUT = 5
ITEM_TIMEOUT = 45
KILL_GRACE = 5
BUDGET = 90
START_MIN = DNS_TIMEOUT + ITEM_TIMEOUT + KILL_GRACE  # 55 s left or the item waits for the next call


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
        if s.get("capture") not in (None, "auto", "human"):
            errors.append("%s: capture must be auto or human" % where)
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


# --- ledgers: where a file came from (design 07 §2.2) ----------------------------------------

def _rec_ok(rec):
    return isinstance(rec, dict) and all(isinstance(rec.get(k), str) and rec.get(k) for k in LEDGER_FIELDS)


def _parse_line(raw):
    try:
        rec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return rec if _rec_ok(rec) else None


def ledger_append(path, rec):
    """One line, fsynced, before the image (capture log) or the state (confirmations) it vouches
    for. An unterminated last piece is kept when it is a whole record (an editor dropped the final
    newline) and cut off otherwise (a write that stopped — nothing after it was written yet)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    with os.fdopen(fd, "r+b") as f:
        data = f.read()
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            if _parse_line(data[cut:]) is not None:
                f.seek(0, 2)
                f.write(b"\n")
            else:
                f.truncate(cut)
        f.seek(0, 2)
        f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        f.flush()
        os.fsync(f.fileno())


def ledger_read(path):
    """(records, damaged line numbers). A finished line that is not a whole record is damage —
    never skipped; an unterminated last line counts only when it is a whole record."""
    if not os.path.isfile(path):
        return [], []
    with open(path, "rb") as f:
        lines = f.read().split(b"\n")
    last = lines.pop()
    out, bad = [], []
    for n, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        rec = _parse_line(raw)
        if rec is None:
            bad.append(n)
        else:
            out.append(rec)
    if last.strip():
        rec = _parse_line(last)
        if rec is not None:
            out.append(rec)
    return out, bad


class Ledger:
    """Both ledgers, read once. Content is (git blob id, sha256 of the bytes); either one
    matching counts as the same content, so a changed .gitattributes cannot hide a capture."""

    def __init__(self, root):
        self.captures, cb = ledger_read(os.path.join(root, CAPTURES))
        self.confirms, fb = ledger_read(os.path.join(root, CONFIRMATIONS))
        self.damaged = [(CAPTURES, n) for n in cb] + [(CONFIRMATIONS, n) for n in fb]

    @property
    def idle(self):
        """Nothing to judge with: rule U is empty (a new clone, or auto capture never used)."""
        return not self.captures and not self.damaged

    @staticmethod
    def _same(rec, h):
        return bool(h) and (rec.get("blob") == h[0] or rec.get("sha256") == h[1])

    def logged(self, h):
        return [r for r in self.captures if self._same(r, h)]

    def confirmed(self, h):
        return any(self._same(r, h) for r in self.confirms)

    def unconfirmed(self, h):
        """Rule U: an automatic capture (any topic, any name) no human confirmed."""
        return bool(self.logged(h)) and not self.confirmed(h)

    def own_line(self, h, tid, sid, key):
        return next((r for r in self.logged(h) if (r.get("topic"), r.get("id"), r.get("key")) == (tid, sid, key)), None)

    def item_lines(self, tid, sid, key=None):
        return [r for r in self.captures if r.get("topic") == tid and r.get("id") == sid
                and (key is None or r.get("key") == key)]

    def damage_text(self):
        where = ", ".join("%s line %d" % w for w in self.damaged)
        first = self.damaged[0][1]
        return ("the screenshot ledgers have a damaged line (%s) — a human removes that line (a protected path: the "
                "guard asks). If you cannot tell which screenshot it recorded, demote the auto screenshots it may "
                "affect or retake them with a loopback. Unattended: hold needs-human with the note "
                "`tooling: shots ledger damaged line %d`" % (where, first))

    def check(self, n, warnings=None):
        """Damage makes every judgement that reads the ledgers undecidable: refuse when there is
        something to judge, a warning otherwise (design §2.2)."""
        if not self.damaged:
            return
        if n:
            raise HeraldError(self.damage_text())
        if warnings is not None:
            warnings.append(self.damage_text())


def _bytes_hashes(root, rel, data):
    """(blob id as a commit at `rel` would store it — clean filters, LFS — and sha256 of the bytes)."""
    p = subprocess.run(["git", "hash-object", "--path=%s" % rel, "--stdin"], cwd=root, input=data,
                       capture_output=True)
    if p.returncode != 0:
        raise HeraldError("git hash-object failed for %s" % rel)
    return p.stdout.decode().strip(), hashlib.sha256(data).hexdigest()


def file_hashes(root, rel):
    full = os.path.join(root, rel)
    if not rel or not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        data = f.read()
    return blob(root, rel), hashlib.sha256(data).hexdigest()


def _clean_hashes(root, rel, data):
    """Hashes of what would land at `rel` (the cleaned bytes; the raw bytes when unreadable)."""
    try:
        data, _ = sanitize(data, rel.rsplit(".", 1)[-1].lower())
    except HeraldError:
        pass
    return _bytes_hashes(root, rel, data)


def _own_capture_text(sid, tid, own, status):
    if own and status == "captured":
        return ("%s: that file is the automatic capture itself — to keep it, `HRD shot confirm --topic %s --id %s` "
                "after looking at it" % (sid, tid, sid))
    return ("%s: that file is an automatic capture no human confirmed — take the screen yourself and save that "
            "file instead" % sid)


# --- automatic capture: who takes a screenshot (design 07 §2.1) ------------------------------

def capture_template(cfg):
    t = cfg.get("screenshots", "capture")
    return t if t is not None else None


def capture_errors(cfg):
    """What is wrong with `screenshots.capture` ([] when it is absent or fine). Never part of
    Config.validate or the guard: a typo here turns capture off (`no-tool`), never the harness."""
    t = capture_template(cfg)
    if t is None:
        return []
    if not isinstance(t, list) or not all(isinstance(x, str) for x in t):
        return ["screenshots.capture must be an array of strings (an argv — no shell)"]
    if not t:
        return ["screenshots.capture is empty"]
    errors = []

    def runner(x):
        prog = os.path.basename(x.replace("\\", "/")).lower()
        return prog in SHELLS or (prog.endswith(".exe") and prog[:-4] in SHELLS) or \
            bool(re.match(r"^(python|pypy|node|perl|ruby|bash|zsh)[0-9.]+(\.exe)?$", prog))
    # any element: a wrapper (`npx sh …`, `timeout 30 bash …`) runs what follows it
    shells = [x for x in t if runner(x)]
    if shells:
        errors.append("screenshots.capture must not run a shell or an interpreter (%s)" % ", ".join(shells))
    if "{" in t[0]:
        errors.append("screenshots.capture's first element is the program — no placeholder there")
    flags = sorted({x for x in t if x in INLINE_FLAGS or SHORT_BUNDLE_RE.match(x)})
    if flags:
        errors.append("screenshots.capture must not pass inline code (%s)" % ", ".join(flags))
    for ph in ("{url}", "{out}"):
        if t.count(ph) != 1 or any(ph in x and x != ph for x in t):
            errors.append("screenshots.capture needs %s exactly once, as a whole element" % ph)
    unknown = sorted({m for x in t for m in re.findall(r"\{[^{}]*\}", x)} - set(PLACEHOLDERS))
    if unknown:
        errors.append("screenshots.capture has unknown placeholders: %s" % ", ".join(unknown))
    return errors


def public_url(url):
    """§2.1 3: a restricted-character https URL on a public-looking host (no userinfo, no IP
    literal, no localhost/.local/.internal). DNS is checked at capture time."""
    if not isinstance(url, str) or not URL_RE.match(url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 — raises on a malformed port
    except ValueError:
        return False
    if "@" in parts.netloc or not host or "[" in parts.netloc:
        return False
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    # a single label (an intranet name) or a numeric last label (127.1, 127.0.0.0x1) is no public
    # name — a resolver may read it as an address
    last = host.rsplit(".", 1)[-1]
    return "." in host and not re.match(r"^(0x[0-9a-f]*|[0-9]+)$", last, re.I) and not host.startswith("0x")


def norm_lang(v):
    """BCP 47 casing (pt-br → pt-BR, zh-hant → zh-Hant), None when it is no language tag."""
    if not isinstance(v, str) or not v:
        return None
    parts = v.split("-")
    out = [parts[0].lower()]
    for p in parts[1:]:
        if len(p) == 4 and p.isalpha():
            out.append(p.title())
        elif len(p) == 2 and p.isalpha():
            out.append(p.upper())
        else:
            out.append(p)
    tag = "-".join(out)
    return tag if LANG_RE.match(tag) else None


def _lang_value(cfg, shot):
    return norm_lang(_spec(shot)["ui_lang"] or cfg.source_lang())


def _crop(shot):
    sp = shot.get("spec") if isinstance(shot.get("spec"), dict) else {}
    return shot.get("crop") or sp.get("crop")


def _url_tuple(tgt, shot):
    t = target(shot)
    return bool(tgt.get("url") and t["url"]) and \
        (tgt.get("url"), tgt.get("theme"), tgt.get("ui_lang")) == (t["url"], t["theme"], t["ui_lang"])


def _retaken(root, tid, st, shot):
    """§2.1 7: this topic's privacy retakes by id, file or url-tuple, its mismatch retakes by
    url-tuple only (a new URL is a new chance); other topics of the slug by url-tuple only."""
    for r in st.get("retakes") or []:
        if not isinstance(r, dict):
            continue
        tgt = r.get("target") or {}
        if (r.get("kind") == "privacy" and matches(tgt, shot)) or (r.get("kind") == "mismatch" and _url_tuple(tgt, shot)):
            return True
    work = os.path.join(root, ".claude/herald/work")
    for other in sorted(os.listdir(work)) if os.path.isdir(work) else []:
        if other == tid:
            continue
        ost = read_json(os.path.join(work, other, "state.json")) or {}
        if not isinstance(ost, dict) or ost.get("slug") != st.get("slug"):
            continue
        if any(isinstance(r, dict) and _url_tuple(r.get("target") or {}, shot) for r in ost.get("retakes") or []):
            return True
    return False


def auto_reasons(root, cfg, tid, st, shot):
    """Every §2.1 reason from 2 on, in order: the first decides; row 5b needs all of them."""
    out = []
    t = capture_template(cfg)
    tool = t is not None and not capture_errors(cfg)
    if not tool:
        out.append("no-tool")
    if not public_url(shot.get("url")):
        out.append("url-not-public")
    sp = _spec(shot)
    if not sp["viewport"]:
        out.append("no-viewport")
    if not str(shot.get("file") or "").lower().endswith(".png"):
        out.append("not-png")
    if shot.get("mask") or _crop(shot):
        out.append("needs-mask")
    if tool:
        joined = "\n".join(t)
        if sp["theme"] == "dark" and "{scheme}" not in joined:
            out.append("no-scheme")
        if (sp["ui_lang"] and "{lang}" not in joined) or ("{lang}" in joined and not _lang_value(cfg, shot)) or \
                (sp["ui_lang"] and not norm_lang(sp["ui_lang"])):
            out.append("no-lang")
    if _retaken(root, tid, st, shot):
        out.append("retaken")
    return out


def verdict(root, cfg, tid, st, shot):
    """(capture, reason code, every reason) for one manifest entry at plan time."""
    if shot.get("capture") != "auto":
        return "human", None, []
    reasons = auto_reasons(root, cfg, tid, st, shot)
    return ("human", reasons[0], reasons) if reasons else ("auto", None, [])


# --- plan -----------------------------------------------------------------------------------

def _recorded_files(st):
    rec = st.get("screenshots") or {}
    return list(dict.fromkeys(list(rec.get("files") or []) + list(st.get("shot_files") or [])))


def _read_prev(r):
    """A record as 07 §2.3 reads it: one 0.15.0 wrote has no `capture` (human) and an imported
    `ready` file counts as the human's own (lock `own`) — an upgrade never turns it into auto."""
    r = dict(r or {})
    if r and "capture" not in r:
        r["capture"] = "human"
        if r.get("status") == "ready" and r.get("sha"):
            r["capture_lock"] = "own"
    return r


def _inherit(r, key, cap, code, reasons, asked_auto, h, led, tid, sid, now):
    """The inheritance table (07 §2.3), first matching row. Returns (record, move the file now)."""
    fb = h[0] if h else None
    base = {"key": key, "capture": cap, "capture_lock": None, "note": code, "sha": None,
            "captured_at": None, "confirmed_sha": None}

    def pending(since):
        return dict(base, status="pending", waiting_since=since)

    was_pending = r.get("status") == "pending" and r.get("waiting_since")
    if r.get("key") != key:  # 1: another screen (an unconfirmed capture of the old one moves away)
        return pending(now), bool(h and led.unconfirmed(h))
    lock = r.get("capture_lock")
    if lock:  # 2: a human's screenshot for as long as the key stays
        base.update(capture="human", capture_lock=lock, note=r.get("note") or lock)
        since = r["waiting_since"] if was_pending else now
        if h and led.unconfirmed(h):  # a demote cut before its file moved
            return pending(since), True
        if r.get("sha") and fb and fb == r["sha"]:
            return dict(base, status="ready", sha=fb), False
        return pending(since), False
    if h and led.unconfirmed(h):  # 3: an unconfirmed capture sits there
        line = led.own_line(h, tid, sid, key)
        if cap == "auto" and line:
            return dict(base, status="captured", sha=fb, captured_at=line.get("at")), False
        return pending(now), True
    if cap == "auto" and r.get("capture") == "auto" and r.get("sha") and fb and fb == r["sha"] == r.get("confirmed_sha"):
        return dict(base, status="ready", sha=fb, captured_at=r.get("captured_at"), confirmed_sha=fb), False  # 4
    if cap == "human" and r.get("capture") == "human":  # 5: as 0.15.0
        if r.get("sha") and fb and fb == r["sha"]:
            return dict(base, status="ready", sha=fb), False
        return pending(r["waiting_since"] if was_pending else now), False
    if (r.get("capture") == "auto" and cap == "human" and asked_auto and reasons
            and set(reasons) <= set(CONFIG_REASONS) and r.get("sha") and fb
            and fb == r["sha"] == r.get("confirmed_sha") and led.confirmed(h)):
        # 5b: a config change never throws away a screen a human confirmed
        return dict(base, capture="auto", note=None, status="ready", sha=fb, captured_at=r.get("captured_at"),
                    confirmed_sha=fb), False
    if (r.get("status") == "captured" and cap == "auto" and h and r.get("sha") and fb == r["sha"]
            and led.own_line(h, tid, sid, key) and led.confirmed(h)):
        # a confirm cut after its ledger line: still `captured` — confirm again completes it
        return dict(base, status="captured", sha=fb, captured_at=r.get("captured_at")
                    or led.own_line(h, tid, sid, key).get("at")), False
    since = r["waiting_since"] if was_pending and r.get("capture") == cap else now  # 6
    return pending(since), bool(h)


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
    led = Ledger(root)
    led.check(sum(1 for s in man["shots"] if os.path.isfile(os.path.join(root, s["file"]))), warnings)
    prev = st.get("screenshots") or {}
    prev_shots = prev.get("shots") or {}
    current = [s["file"] for s in man["shots"]]
    files = list(dict.fromkeys(list(prev.get("files") or []) + current))
    to_move = [f for f in prev.get("files") or [] if f not in current]
    shots, now = {}, now_iso()
    for s in man["shots"]:
        r = _read_prev(prev_shots.get(s["id"]))
        key = shot_key(s)
        cap, code, reasons = verdict(root, cfg, tid, st, s)
        h = file_hashes(root, s["file"])
        new, move = _inherit(r, key, cap, code, reasons, s.get("capture") == "auto", h, led, tid, s["id"], now)
        if new["status"] == "pending" and not r.get("sha") and retakes_for(st, s):
            move = True  # a retake cut off before its file moved (0.15.0)
        if move and h:
            to_move.append(s["file"])
        shots[s["id"]] = new
        if s.get("capture") == "auto" and new["capture"] == "human":
            warnings.append("%s: a human takes it (%s)" % (s["id"], new.get("note")))
    st["screenshots"] = {"manifest": _file_sha256(root, manifest_rel(tid)),
                         "body": _file_sha256(root, cfg.body_path(slug)),
                         "awaiting": True, "files": files, "shots": shots,
                         "unreferenced_base_images": unref}
    save_state(root, tid, st)
    moved = move_to_removed(root, tid, [f for f in dict.fromkeys(to_move) if not on_base(root, cfg, f)], "unlisted")
    return {"shots": len(shots), "pending": sorted(k for k, v in shots.items() if v["status"] == "pending"),
            "auto": sorted(k for k, v in shots.items() if v["status"] == "pending" and v["capture"] == "auto"),
            "captured": sorted(k for k, v in shots.items() if v["status"] == "captured"),
            "moved": moved, "warnings": warnings}


# --- status / note --------------------------------------------------------------------------

def hold_note(st):
    """The only hold note base may carry: ids, retake kind codes and `confirm` for an automatic
    capture waiting for a human's look (design 06 §2.8, 07 §2.5)."""
    rec = st.get("screenshots") or {}
    parts = []
    for sid, r in sorted((rec.get("shots") or {}).items(), key=lambda kv: int(kv[0][1:])):
        if r.get("status") == "captured":
            parts.append("%s(confirm)" % sid)
            continue
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
                      "retake": ({"kind": rts[-1].get("kind"), "reason": rts[-1].get("reason")} if rts else None),
                      "capture": r.get("capture") or "human", "capture_note": r.get("note"),
                      "captured_at": r.get("captured_at"), "shot_col": shot_col(root, s, r)})
    return {"inbox": inbox_rel(tid), "shots": items, "removed_bytes": removed_bytes(root, tid),
            "pending": [i["id"] for i in items if i["status"] == "pending"],
            "auto": [i["id"] for i in items if i["status"] == "pending" and i["capture"] == "auto"],
            "captured": [i["id"] for i in items if i["status"] == "captured"],
            "all_ready": bool(items) and all(i["status"] == "ready" for i in items),
            "awaiting": bool(rec.get("awaiting")), "resume_at_import": resume_at_import(root, cfg, st),
            "note": hold_note(st), "files": _recorded_files(st),
            "unreferenced_base_images": rec.get("unreferenced_base_images") or [],
            "decisions": st.get("shot_decisions") or []}


def shot_col(root, shot, r):
    """The PR body's and ship's capture column (07 §2.6): `auto <url> <captured_at>` only for the
    capture itself — a file a human replaced shows `human`, without URL or time."""
    if r.get("capture") == "auto" and r.get("captured_at") and shot.get("file") and \
            blob(root, shot["file"]) == r.get("sha"):
        return "auto %s %s" % (shot.get("url"), r["captured_at"])
    return "human"


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


def _plan_current(root, cfg, tid, st):
    rec = st.get("screenshots")
    if not rec:
        raise HeraldError("no screenshots planned for %s — `HRD shot plan --topic %s` first" % (tid, tid))
    if rec.get("manifest") != _file_sha256(root, manifest_rel(tid)) or \
            rec.get("body") != _file_sha256(root, cfg.body_path(st["slug"])):
        raise HeraldError("the article or screenshots.json changed since `HRD shot plan` — run it again")
    return rec


def _inbox_names(root, tid):
    inbox = os.path.join(root, inbox_rel(tid))
    return inbox, (os.listdir(inbox) if os.path.isdir(inbox) else [])


def _inbox_hashes(root, inbox, name, rel):
    with open(os.path.join(inbox, name), "rb") as f:
        return _clean_hashes(root, rel, f.read())


def _human_first(root, tid, r, s, led, inbox, names):
    """07 §2.4 0: a file the human put in the inbox for a pending auto screenshot after it started
    waiting, and not an unconfirmed capture — the screenshot becomes the human's (lock `own`)."""
    since = _parse_iso(r.get("waiting_since"))
    for n in [n for n in names if n.rsplit(".", 1)[0] == s["id"] and not n.startswith(".")]:
        p = os.path.join(inbox, n)
        if since is not None and os.path.getmtime(p) < since:
            continue
        if led.unconfirmed(_inbox_hashes(root, inbox, n, s["file"])):
            continue
        r.update(capture="human", capture_lock="own", note="own")
        return True
    return False


def import_(root, cfg, tid):
    from .store import load_state, save_state
    st = load_state(root, tid)
    rec = _plan_current(root, cfg, tid, st)
    man = load_manifest(root, tid) or {"shots": []}
    by_id = {s["id"]: s for s in man["shots"]}
    inbox, names = _inbox_names(root, tid)
    led = Ledger(root)
    led.check(sum(1 for n in names if not n.startswith(".")))
    imported, problems, warnings, done, stale = [], [], [], [], []
    for sid, r in sorted(rec["shots"].items(), key=lambda kv: int(kv[0][1:])):
        if sid not in by_id:
            continue
        s = by_id[sid]
        if r.get("status") == "captured":  # waits for a human's look: never a silent move or a replacement
            for n in [n for n in names if n.rsplit(".", 1)[0] == sid and not n.startswith(".")]:
                own = led.own_line(_inbox_hashes(root, inbox, n, s["file"]), tid, sid, r.get("key"))
                if own or led.unconfirmed(_inbox_hashes(root, inbox, n, s["file"])):
                    problems.append(_own_capture_text(sid, tid, own, "captured"))
                else:
                    warnings.append("%s is an automatic capture waiting for confirmation — %s is not used; to use your "
                                    "file instead: `HRD shot demote --topic %s --id %s --own`" % (sid, n, tid, sid))
            continue
        if r.get("status") != "pending":
            for n in [n for n in names if n.rsplit(".", 1)[0] == sid]:
                if _same_as_recorded(os.path.join(inbox, n), s["file"], r.get("sha")):
                    stale.append(os.path.relpath(os.path.join(inbox, n), root))  # an import cut off before the move
                else:  # never a silent replacement
                    warnings.append("%s is already imported — %s is not used; to replace it, retake it (`HRD loopback "
                                    "--human --retake %s …`), then save the new file into the inbox again"
                                    % (sid, n, sid))
            continue
        if r.get("capture") == "auto" and not _human_first(root, tid, r, s, led, inbox, names):
            # Herald takes it (`HRD shot capture`); an inbox file here is older than the wait or a capture
            since = _parse_iso(r.get("waiting_since"))
            for n in [n for n in names if n.rsplit(".", 1)[0] == sid and not n.startswith(".")]:
                if since is not None and os.path.getmtime(os.path.join(inbox, n)) < since:
                    problems.append("%s: %s was made before %s started waiting (%s) — if it is a new screenshot, "
                                    "save it again and put it back" % (sid, n, sid, r.get("waiting_since")))
                else:
                    problems.append(_own_capture_text(sid, tid, False, "pending"))
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
        if led.unconfirmed(_bytes_hashes(root, s["file"], clean)):  # 07 §2.2: never as a human's file
            problems.append(_own_capture_text(sid, tid, False, "pending"))
            continue
        warnings += ["%s: %s" % (sid, w) for w in warn]
        vp = _spec(s)["viewport"]
        width = image_width(clean)
        if vp and width and width > 2 * int(vp.split("x")[0]):
            warnings.append("%s: %dpx wide — more than twice the %s viewport (a Retina capture?)" % (sid, width, vp))
        dest = os.path.join(root, s["file"])
        if os.path.isfile(dest) and not (r.get("sha") and blob(root, s["file"]) == r["sha"]) and \
                not on_base(root, cfg, s["file"]):
            move_to_removed(root, tid, [s["file"]], "replaced")  # never overwrite what sits there (P9)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(clean)
        # a human's own file: it stays theirs for as long as the screen stays the same (07 §2.3)
        r.update(status="ready", sha=blob(root, s["file"]), capture="human", capture_lock="own",
                 note="own", captured_at=None, confirmed_sha=None)
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
    order = sorted(rec["shots"], key=lambda k: int(k[1:]))
    remaining = [k for k in order if rec["shots"][k].get("status") == "pending"]
    captured = [k for k in order if rec["shots"][k].get("status") == "captured"]
    for k in captured:  # 07 §2.5 wording
        warnings.append("%s: an automatic capture waiting for confirmation — look at %s, then `HRD shot confirm "
                        "--topic %s --id %s`, or `HRD shot demote` to take it again or use your own file"
                        % (k, (by_id.get(k) or {}).get("file"), tid, k))
    return {"imported": imported, "remaining": remaining, "captured": captured, "problems": problems,
            "warnings": warnings, "note": hold_note(st)}


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
        # a retaken screen is a human's until plan judges it again (a mismatch with a new URL may
        # be auto again); `capture` never takes it before that
        rec["shots"][sid].update(status="pending", sha=None, waiting_since=now_iso(), captured_at=None,
                                 confirmed_sha=None, capture="human", note="retaken")
        files.append(s["file"])
    return files


# --- automatic capture (design 07 §2.4) -------------------------------------------------------

def _tmp_dir(root, name):
    return os.path.join(root, ".claude/herald/memory/shots/tmp", name)


def _resolve(host, timeout=DNS_TIMEOUT):
    """Every address `host` resolves to, looked up in a separate thread with a time limit."""
    import socket
    box = {}

    def work():
        try:
            box["addrs"] = sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
        except Exception as e:  # noqa: BLE001 — any failure is `dns-fail`
            box["err"] = e
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive() or "err" in box or not box.get("addrs"):
        raise OSError("%s did not resolve" % host)
    return box["addrs"]


def _dns(host):
    """None, `dns-private` (any address that is not global) or `dns-fail`. Best effort: a redirect
    or DNS rebinding still reaches what this cannot see — a human looks at every capture (P8)."""
    try:
        addrs = _resolve(host)
    except Exception:  # noqa: BLE001
        return "dns-fail"
    for a in addrs:
        try:
            if not ipaddress.ip_address(str(a).split("%")[0]).is_global:
                return "dns-private"
        except ValueError:
            return "dns-private"
    return None


def _values(cfg, shot, out, template=None):
    """The checked placeholder values, or None (`bad-value`): nothing starts with `-`. A language
    is needed only when the template has `{lang}` (plan's `no-lang` reads it the same way)."""
    sp = _spec(shot)
    vp = str(sp["viewport"] or "")
    needs_lang = "{lang}" in "\n".join(template if template is not None else capture_template(cfg) or [])
    lang = _lang_value(cfg, shot) if needs_lang else "und"
    if not VIEWPORT_RE.match(vp) or sp["theme"] not in ("light", "dark") or not lang or not public_url(shot.get("url")):
        return None
    w, h = vp.split("x")
    vals = {"w": w, "h": h, "scheme": sp["theme"], "lang": lang, "url": shot["url"], "out": out}
    return None if any(str(v).startswith("-") for v in vals.values()) else vals


def _argv(template, vals):
    """`{url}`/`{out}` only as whole elements; the rest in one pass inside an element (a value
    that looks like a placeholder is never substituted again)."""
    out = []
    for x in template:
        if x in ("{url}", "{out}"):
            out.append(vals[x[1:-1]])
        else:
            out.append(re.sub(r"\{(w|h|scheme|lang)\}", lambda m: vals[m.group(1)], x))
    return out


def _ps(pid, field):
    try:
        p = subprocess.run(["ps", "-o", "%s=" % field, "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def _killpg(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _reap_stale(root, name, warnings):
    """A group an earlier, cut-off run left behind: killed only when its leader's start time and
    command still match the record (a reused PID is left alone, with a warning)."""
    path = os.path.join(_tmp_dir(root, name), ".pgid")
    rec = read_json(path) or {}
    pgid = rec.get("pgid") if isinstance(rec, dict) else None
    if isinstance(pgid, int) and pgid > 1:
        started = _ps(pgid, "lstart")
        if started:
            argv0 = os.path.basename(str(rec.get("argv0") or ""))
            if rec.get("started") == started and argv0 and argv0 in _ps(pgid, "command"):
                _killpg(pgid, signal.SIGKILL)
            else:
                warnings.append("an earlier capture's process group %d does not match its record (a reused PID?) — "
                                "left alone" % pgid)
    try:
        os.remove(path)
    except OSError:
        pass


def _run_tool(root, argv, pgid_file):
    """Run the capture tool: no shell, its own process group, output captured and thrown away,
    SIGTERM to the group at ITEM_TIMEOUT and SIGKILL KILL_GRACE later. None or a failure code."""
    import tempfile
    with tempfile.TemporaryFile() as sink:
        try:
            proc = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=sink, stderr=sink,
                                    start_new_session=True)
        except OSError:
            return "exit-nonzero"
        try:
            os.makedirs(os.path.dirname(pgid_file), exist_ok=True)
            with open(pgid_file, "w", encoding="utf-8") as f:
                json.dump({"pgid": proc.pid, "started": _ps(proc.pid, "lstart"), "argv0": argv[0]}, f)
        except OSError:
            pass
        code = None
        try:
            proc.wait(timeout=ITEM_TIMEOUT)
            if proc.returncode != 0:
                code = "exit-nonzero"
        except subprocess.TimeoutExpired:
            code = "timeout"
            _killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=KILL_GRACE)
            except subprocess.TimeoutExpired:
                _killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        _killpg(proc.pid, signal.SIGKILL)  # whatever the tool left running in its group
        try:
            os.remove(pgid_file)
        except OSError:
            pass
        return code


def _png_result(path):
    """(bytes, None) or (None, failure code) for what the tool wrote."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None, "no-file"
    if os.path.getsize(path) > MAX_BYTES:
        return None, "bad-format"
    with open(path, "rb") as f:
        data = f.read()
    if kind_of(data) != "png":
        return None, "bad-format"
    try:
        clean, _ = sanitize(data, "png")
    except HeraldError:
        return None, "bad-format"
    return clean, None


def _capture_one(root, cfg, tid, r, s):
    url = s.get("url")
    if not public_url(url):
        return "bad-value"
    code = _dns(urllib.parse.urlsplit(url).hostname)
    if code:
        return code
    d = _tmp_dir(root, tid)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "%s.png" % s["id"])
    if os.path.exists(out):
        os.remove(out)
    vals = _values(cfg, s, out, capture_template(cfg))
    if vals is None:
        return "bad-value"
    try:
        code = _run_tool(root, _argv(capture_template(cfg), vals), os.path.join(d, ".pgid"))
        if code:
            return code
        clean, code = _png_result(out)
        if code:
            return code
        h = _bytes_hashes(root, s["file"], clean)
        at = now_iso()
        # the log line first: an image no line vouches for is never left behind (rule U)
        ledger_append(os.path.join(root, CAPTURES), {"topic": tid, "id": s["id"], "key": r["key"], "file": s["file"],
                                                     "blob": h[0], "sha256": h[1], "at": at})
        cur = file_hashes(root, s["file"])
        if cur and not (r.get("sha") and cur[0] == r["sha"]):
            move_to_removed(root, tid, [s["file"]], "replaced")  # whatever sat there was not ours untouched (P9)
        dest = os.path.join(root, s["file"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(clean)
        r.update(status="captured", capture="auto", capture_lock=None, note=None, sha=blob(root, s["file"]),
                 captured_at=at, confirmed_sha=None)
        r.pop("waiting_since", None)
        return None
    finally:
        if os.path.exists(out):
            os.remove(out)


def capture(root, cfg, tid):
    """`HRD shot capture`: take the pending auto screenshots one at a time, saving state after
    each, within a BUDGET-second run (what did not start is `remaining`: call again)."""
    from .store import load_state, save_state
    st = load_state(root, tid)
    rec = _plan_current(root, cfg, tid, st)
    man = load_manifest(root, tid) or {"shots": []}
    by_id = {s["id"]: s for s in man["shots"]}
    todo = [k for k in sorted(rec["shots"], key=lambda k: int(k[1:])) if k in by_id
            and rec["shots"][k].get("status") == "pending" and rec["shots"][k].get("capture") == "auto"]
    out = {"captured": [], "failed": [], "own": [], "skipped": [], "remaining": [], "warnings": []}
    if todo:
        errs = capture_errors(cfg) if capture_template(cfg) is not None else ["screenshots.capture is not set"]
        if errs:
            raise HeraldError("cannot capture: %s — fix it with /hrd config (or turn capture off), then `HRD shot plan "
                              "--topic %s` (the screenshots become a human's; unattended: hold needs-human, note `tooling: shots "
                              "capture template invalid`)" % ("; ".join(errs), tid))
        led = Ledger(root)
        led.check(len(todo))
        inbox, names = _inbox_names(root, tid)
        _reap_stale(root, tid, out["warnings"])
        t0 = time.monotonic()
        for sid in todo:
            if BUDGET - (time.monotonic() - t0) < START_MIN:
                out["remaining"].append(sid)
                continue
            r, s = rec["shots"][sid], by_id[sid]
            cap, code, _ = verdict(root, cfg, tid, st, s)
            if cap != "auto":  # judged again here: a retake or a config change since plan
                r.update(capture="human", note=code)
                out["skipped"].append({"id": sid, "code": code})
            elif _human_first(root, tid, r, s, led, inbox, names):
                out["own"].append(sid)
            else:
                code = _capture_one(root, cfg, tid, r, s)
                if code:  # a human takes it, and it stays so while the screen stays the same (P4)
                    r.update(status="pending", capture="human", capture_lock=code, note=code, sha=None,
                             captured_at=None, confirmed_sha=None, waiting_since=now_iso())
                    out["failed"].append({"id": sid, "code": code})
                else:
                    out["captured"].append(sid)
            save_state(root, tid, st)
    out["note"] = hold_note(st)
    out["captures"] = [{"id": k, "file": by_id[k]["file"], "url": by_id[k].get("url"),
                        "captured_at": rec["shots"][k].get("captured_at")}
                       for k in sorted(rec["shots"], key=lambda k: int(k[1:]))
                       if k in by_id and rec["shots"][k].get("status") == "captured"]
    return out


def trial(root, cfg):
    """`HRD shot trial`: the template once with fixed values (about:blank, 800x600, light, en) —
    the tool and its browser are installed. The result is deleted and never logged."""
    t = capture_template(cfg)
    errs = capture_errors(cfg) if t is not None else ["screenshots.capture is not set"]
    if errs:
        raise HeraldError("; ".join(errs))
    d = _tmp_dir(root, "trial")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "trial.png")
    vals = {"w": "800", "h": "600", "scheme": "light", "lang": "en", "url": "about:blank", "out": out}
    argv = _argv(t, vals)
    warnings = []
    _reap_stale(root, "trial", warnings)
    try:
        code = _run_tool(root, argv, os.path.join(d, ".pgid"))
        if not code:
            code = _png_result(out)[1]
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": code is None, "code": code, "argv": argv, "warnings": warnings}


# --- confirm / demote (design 07 §2.5) ---------------------------------------------------------

def _human_only(what):
    if os.environ.get("HRD_UNATTENDED") == "1":
        raise HeraldError("`shot %s` records a human's decision — not allowed in unattended sessions" % what)


def _ids(ids):
    out = [x.strip() for x in (ids if isinstance(ids, list) else str(ids or "").split(",")) if x and x.strip()]
    if not out:
        raise HeraldError("--id needs one or more screenshot ids (s1,s2)")
    return list(dict.fromkeys(out))


def confirm(root, cfg, tid, ids):
    """A human looked at captured screenshots: the confirmation line first, then the state."""
    from .store import load_state, save_state
    _human_only("confirm")
    ids = _ids(ids)
    st = load_state(root, tid)
    rec = st.get("screenshots") or {}
    by_id = {s.get("id"): s for s in (load_manifest(root, tid) or {}).get("shots") or [] if isinstance(s, dict)}
    led = Ledger(root)
    led.check(len(ids))
    todo = []
    for sid in ids:
        r, s = (rec.get("shots") or {}).get(sid), by_id.get(sid)
        if not r or not s:
            raise HeraldError("%s is not a planned screenshot" % sid)
        if r.get("status") != "captured":
            raise HeraldError("%s is not an automatic capture waiting for confirmation (status %s)" % (sid, r.get("status")))
        h = file_hashes(root, s["file"])
        if not h or not r.get("sha") or h[0] != r["sha"]:
            raise HeraldError("%s: %s is not the file `HRD shot capture` wrote — `HRD shot plan --topic %s` first (an "
                              "edited file is moved away and the screen is taken again)" % (sid, s["file"], tid))
        if not led.own_line(h, tid, sid, r.get("key")):
            raise HeraldError("%s: no capture record on this machine — `HRD shot demote --topic %s --id %s` (with --own "
                              "or --retake-kind) so a human takes it" % (sid, tid, sid))
        todo.append((sid, r, h))
    at = now_iso()
    for sid, r, h in todo:
        ledger_append(os.path.join(root, CONFIRMATIONS), {"topic": tid, "id": sid, "key": r["key"], "blob": h[0],
                                                          "sha256": h[1], "at": at})
    for sid, r, h in todo:
        r.update(status="ready", confirmed_sha=r["sha"])
    save_state(root, tid, st)
    return {"confirmed": [t[0] for t in todo], "note": hold_note(st)}


def _just_before(ts):
    return datetime.datetime.fromtimestamp(int(ts) - 1, datetime.timezone.utc).replace(microsecond=0).isoformat()


def demote(root, cfg, tid, ids, kind=None, reason=None, own=False):
    """A captured screenshot becomes a human's: taken again (`kind` — a retake with the `--human`
    loopback's state change in the same write, so the writer runs next) or the human's own file
    from the inbox (`own` — on to import). State first, then the file moves (07 §2.5)."""
    from .store import load_state, open_research_fix, save_state
    _human_only("demote")
    ids = _ids(ids)
    if bool(kind) == bool(own):
        raise HeraldError("give exactly one of --retake-kind privacy|mismatch or --own")
    if kind and kind not in KINDS:
        raise HeraldError("--retake-kind must be privacy or mismatch")
    st = load_state(root, tid)
    if st.get("stage") != "draft":
        raise HeraldError("demote is for a capture waiting in draft — after confirmation a retake goes through "
                          "`HRD loopback --retake`")
    if open_research_fix(st):
        raise HeraldError("a research fix is open — the researcher runs first (`atoms/_stages.md` § research)")
    if (st.get("trim") or {}).get("status") == "open":
        raise HeraldError("a trim is open — `HRD trim --topic %s --abort` first (it restores the article)" % tid)
    rec = st.get("screenshots") or {}
    by_id = {s.get("id"): s for s in (load_manifest(root, tid) or {}).get("shots") or [] if isinstance(s, dict)}
    for sid in ids:
        r = (rec.get("shots") or {}).get(sid)
        if not r or sid not in by_id:
            raise HeraldError("%s is not a planned screenshot" % sid)
        if r.get("status") != "captured":
            raise HeraldError("%s is not an automatic capture waiting for confirmation (status %s)" % (sid, r.get("status")))
    since = {}
    if own:
        inbox, names = _inbox_names(root, tid)
        led = Ledger(root)
        led.check(len(ids))
        for sid in ids:
            cands = [n for n in names if n.rsplit(".", 1)[0] == sid and not n.startswith(".")]
            if len(cands) != 1:
                raise HeraldError("%s: put exactly one file named %s.<ext> into %s first" % (sid, sid, inbox_rel(tid)))
            h = _inbox_hashes(root, inbox, cands[0], by_id[sid]["file"])
            if led.unconfirmed(h):
                raise HeraldError(_own_capture_text(sid, tid, led.own_line(h, tid, sid, rec["shots"][sid].get("key")),
                                                    "captured"))
            since[sid] = _just_before(os.path.getmtime(os.path.join(inbox, cands[0])))
    now = now_iso()
    lock = "own" if own else "demoted"
    files = []
    for sid in ids:
        rec["shots"][sid].update(status="pending", capture="human", capture_lock=lock, note=lock, sha=None,
                                 captured_at=None, confirmed_sha=None, waiting_since=since.get(sid, now))
        if kind:
            st.setdefault("retakes", []).append({"target": target(by_id[sid]), "kind": kind,
                                                 "reason": (reason or "")[:300], "at": now})
        files.append(by_id[sid]["file"])
    if kind:  # `HRD loopback --human` (uncounted) in the same state write: the writer runs next
        st["stage"] = "draft"
        st["last_loopback"] = "human"
        rec["awaiting"] = False
        if st.get("translation"):  # as any loopback that is not a translation one
            st["translation"].pop("last_loopback_langs", None)
            st["translation"].pop("last_loopback_stage", None)
    save_state(root, tid, st)
    moved = move_to_removed(root, tid, [f for f in files if not on_base(root, cfg, f)], "demoted")
    return {"demoted": ids, "moved": moved, "note": hold_note(st),
            "next": ("the writer (draft again: %s)" % ("fill mask" if kind == "privacy" else "fix the URL, how or text"))
            if kind else "HRD shot import --topic %s" % tid}


def audit(root, cfg):
    """`/hrd audit` step 2: auto screenshots recorded as confirmed whose confirmation this
    machine's ledger does not hold (only for those captured here — the rest are counted apart),
    and damaged ledger lines. Local states and the herald branches on origin."""
    from .store import read_json_at
    led = Ledger(root)
    states = []
    work = os.path.join(root, ".claude/herald/work")
    for tid in sorted(os.listdir(work)) if os.path.isdir(work) else []:
        st = read_json(os.path.join(work, tid, "state.json"))
        if isinstance(st, dict):
            states.append(("local", tid, st))
    refs = git(root, "for-each-ref", "--format=%(refname)", "refs/remotes/origin/herald/", check=False).split()
    for ref in refs:
        for p in git(root, "ls-tree", "-r", "--name-only", ref, "--", ".claude/herald/work", check=False).splitlines():
            if p.endswith("/state.json"):
                st = read_json_at(root, ref, p)
                if isinstance(st, dict):
                    states.append((ref[len("refs/remotes/"):], p.split("/")[-2], st))
    anomalies, no_record, seen = [], [], set()
    for where, tid, st in states:
        for sid, r in ((st.get("screenshots") or {}).get("shots") or {}).items():
            if not isinstance(r, dict) or r.get("capture") != "auto" or \
                    not (r.get("status") == "ready" or r.get("confirmed_sha")):
                continue
            k = (tid, sid, r.get("key"), r.get("confirmed_sha"))
            if k in seen:
                continue
            seen.add(k)
            item = {"where": where, "topic": tid, "id": sid}
            if not led.item_lines(tid, sid, r.get("key")):
                no_record.append(item)
            elif not r.get("confirmed_sha") or not any(c.get("blob") == r["confirmed_sha"] for c in led.confirms):
                anomalies.append(dict(item, confirmed_sha=r.get("confirmed_sha")))
    return {"ok": not anomalies and not led.damaged, "anomalies": anomalies, "no_record": len(no_record),
            "no_record_items": no_record, "damaged": [{"file": f, "line": n} for f, n in led.damaged]}


# --- stage pass / orphans -------------------------------------------------------------------

def orphans(root, cfg, st, man):
    """Recorded screenshot files still in the working tree but no longer listed (plan did not
    move them). Only Herald's own records count — illustrator images, frontmatter references
    and manifest-less topics are never judged here."""
    current = {s.get("file") for s in (man or {}).get("shots") or [] if isinstance(s, dict)}
    return [f for f in _recorded_files(st) if f not in current and os.path.isfile(os.path.join(root, f))
            and not on_base(root, cfg, f)]


def _changed_images(root, cfg, slug):
    """Every file under the image directory that differs from origin/<base> (added or changed)."""
    d = cfg.image_dir(slug)
    full = os.path.join(root, d)
    if not os.path.isdir(full):
        return []
    on = {}
    for line in git(root, "ls-tree", "-r", "origin/%s" % cfg.base, "--", d, check=False).splitlines():
        meta, _, path = line.partition("\t")
        if path:
            on[path] = meta.split()[-1]
    out = []
    for dp, _, fns in os.walk(full):
        for fn in sorted(fns):
            rel = os.path.relpath(os.path.join(dp, fn), root).replace(os.sep, "/")
            if blob(root, rel) != on.get(rel):
                out.append(rel)
    return sorted(out)


def _fail_closed(tid, sid, r, led):
    """07 §2.2: a capture time with no capture line on this machine (log gone, another machine)."""
    if not r.get("captured_at") or led.item_lines(tid, sid, r.get("key")):
        return None
    if r.get("status") == "captured":
        return ("%s: no capture record on this machine — `HRD shot demote --topic %s --id %s` (--own or --retake-kind) "
                "so a human takes it" % (sid, tid, sid))
    return ("%s: no capture record on this machine — `HRD loopback --topic %s --human --retake %s --retake-kind "
            "mismatch` so a human takes it again (unattended: hold needs-human, note `tooling: shots capture record "
            "missing %s`)" % (sid, tid, sid, sid))


def _auto_ok(r, b):
    """An auto screenshot passes only confirmed, as the very file confirmed (no value = not equal)."""
    return r.get("status") == "ready" and bool(r.get("sha")) and r.get("confirmed_sha") == r["sha"] and b == r["sha"]


def draft_problems(root, cfg, tid, st):
    man = load_manifest(root, tid)
    rec = st.get("screenshots")
    out = []
    led = Ledger(root)
    shots_rec = (rec or {}).get("shots") or {}
    by_file = {s.get("file"): s.get("id") for s in (man or {}).get("shots") or [] if isinstance(s, dict)}
    if not led.idle and st.get("slug"):
        # rule U first, for every topic, records or not: the whole image directory against every capture
        changed = _changed_images(root, cfg, st["slug"])
        if led.damaged and changed:
            return [led.damage_text()]
        for f in changed:
            h = file_hashes(root, f)
            if not led.unconfirmed(h):
                continue
            sid = by_file.get(f)
            status = (shots_rec.get(sid) or {}).get("status") if sid else None
            if status == "captured":
                continue  # reported below as waiting for confirmation
            if not sid:
                how = "it is no listed screenshot of this topic: move it out of %s" % cfg.image_dir(st["slug"])
            elif status == "pending":
                how = ("`HRD shot plan --topic %s` moves it away; then `HRD shot capture` / `HRD shot import` for %s"
                       % (tid, sid))
            else:
                how = "take %s again: `HRD loopback --topic %s --human --retake %s --retake-kind mismatch`" % (sid, tid, sid)
            out.append("%s is an automatic capture no human confirmed — %s" % (f, how))
    for sid, r in sorted(shots_rec.items()):
        why = _fail_closed(tid, sid, r, led)
        if why:
            out.append(why)
    if man and man["shots"]:
        if not rec:
            return out + ["screenshots.json is not planned — run `HRD shot plan --topic %s`" % tid]
        if rec.get("manifest") != _file_sha256(root, manifest_rel(tid)):
            out.append("screenshots.json changed since `HRD shot plan` — run it again")
        if rec.get("body") != _file_sha256(root, cfg.body_path(st["slug"])):
            out.append("the article changed since `HRD shot plan` — run it again")
        by_id = {s.get("id"): s for s in man["shots"] if isinstance(s, dict)}
        if set(by_id) != set(rec.get("shots") or {}):
            out.append("screenshots.json lists other shots than were planned — run `HRD shot plan` again")
        for sid, r in sorted((rec.get("shots") or {}).items()):
            s = by_id.get(sid) or {}
            b = blob(root, s.get("file") or "")
            if r.get("status") == "captured":
                out.append("%s is an automatic capture waiting for confirmation — look at %s, then `HRD shot confirm "
                           "--topic %s --id %s`, or `HRD shot demote`" % (sid, s.get("file"), tid, sid))
            elif r.get("status") != "ready":
                out.append("%s is still pending — `HRD shot import --topic %s`" % (sid, tid))
            elif b != r.get("sha"):
                out.append("%s: %s is not the file `HRD shot import` wrote — `HRD shot plan` first (it becomes "
                           "pending), then the edited version into the inbox and `HRD shot import`"
                           % (sid, s.get("file")))
            elif r.get("capture") == "auto" and not _auto_ok(r, b):
                out.append("%s: an automatic capture no human confirmed — `HRD shot plan --topic %s`, then confirm it"
                           % (sid, tid))
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


def _range_blobs(root, cfg, slug):
    """(commit, path, blob) for every new blob under the image directory in merge-base..HEAD —
    every commit a push carries, merge commits against each parent, no history simplification."""
    base = git(root, "merge-base", "HEAD", "origin/%s" % cfg.base, check=False).strip()
    if not base:
        return []
    log = git(root, "-c", "core.quotePath=false", "log", "--format=%H", "--raw", "--no-abbrev", "--no-renames", "-m",
              "--full-history", "%s..HEAD" % base, "--", cfg.image_dir(slug), check=False)
    out, commit = [], None
    for line in log.splitlines():
        if re.match(r"^[0-9a-f]{40,64}$", line):
            commit = line
        elif line.startswith(":") and commit and "\t" in line:
            meta, path = line.split("\t", 1)
            new = meta.split()[3]
            if new.strip("0"):
                out.append((commit, path, new))
    return list(dict.fromkeys(out))


def history_problems(root, cfg, tid, slug, led=None):
    """07 §2.2 at publish: rule U over every commit the push would carry. Each hit says where it
    is — HEAD's tree (confirm, demote, loopback), only in what origin already has (a human), or
    only in past local commits (`HRD shot squash`). Returns (problems, squash would clear some)."""
    from .store import branch_name
    led = led or Ledger(root)
    if led.idle:
        return [], False
    hits = _range_blobs(root, cfg, slug)
    if led.damaged and hits:
        return [led.damage_text()], False
    img = cfg.image_dir(slug)
    head = {line.split()[2] for line in git(root, "ls-tree", "-r", "HEAD", "--", img, check=False).splitlines()
            if len(line.split()) >= 3}
    remote = git(root, "rev-parse", "--verify", "-q", "refs/remotes/origin/%s" % branch_name(tid, slug),
                 check=False).strip()
    out, squashable, seen = [], False, set()
    for commit, path, b in hits:
        if b in seen:
            continue
        p = subprocess.run(["git", "cat-file", "--filters", "%s:%s" % (commit, path)], cwd=root, capture_output=True)
        if p.returncode != 0:
            seen.add(b)
            out.append("cannot read %s at %s (an LFS object missing?) — whether it is an unconfirmed automatic capture "
                       "cannot be told" % (path, commit[:12]))
            continue
        if not led.unconfirmed((b, hashlib.sha256(p.stdout).hexdigest())):
            continue
        seen.add(b)
        if b in head:
            out.append("%s is an automatic capture no human confirmed — confirm or demote it, or take it again "
                       "(`HRD loopback --human --retake …`)" % path)
        elif remote and git_ok(root, "merge-base", "--is-ancestor", commit, remote):
            out.append("an automatic capture no human confirmed (%s) is in %s, already pushed — a human sorts it out "
                       "(needs-human)" % (path, commit[:12]))
        else:
            squashable = True
            out.append("a past commit (%s) holds an automatic capture no human confirmed (%s) — `HRD shot squash "
                       "--topic %s` rewrites the history as one commit" % (commit[:12], path, tid))
    return out, squashable


def squash(root, cfg, tid):
    """Publish step 4 for a topic with screenshots (P7): rebuild the branch as one commit on
    the merge-base (or on what was already pushed), so WIP commits holding screens no one
    reviewed never reach the remote."""
    from .commits import _match, pr_scope_globs, topic_langs
    from .store import branch_name, load_state
    st = load_state(root, tid)
    slug = st.get("slug")
    # a topic without records too, when past commits hold an unconfirmed capture (07 §2.2)
    if not has_records(st) and not (slug and history_problems(root, cfg, tid, slug)[1]):
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
    out = []
    if publish and st.get("slug"):
        # 07 §2.2/§2.6, before anything else and whether or not the topic has records; never at
        # a --rev (ship), L3
        led = Ledger(root)
        out += history_problems(root, cfg, tid, st["slug"], led)[0]
        by_id = {s.get("id"): s for s in (man or {}).get("shots") or [] if isinstance(s, dict)}
        for sid, r in sorted(((st.get("screenshots") or {}).get("shots") or {}).items()):
            why = _fail_closed(tid, sid, r, led)
            if why:
                out.append(why)
            elif r.get("capture") == "auto" and sid in by_id:
                b = git(root, "rev-parse", "-q", "--verify", "HEAD:%s" % by_id[sid].get("file"), check=False).strip()
                if not _auto_ok(r, b or None):
                    out.append("%s: an automatic capture no human confirmed in HEAD — confirm it (`HRD shot confirm`) "
                               "before publishing" % sid)
    if not has_records(st):
        return out
    current = {s.get("file") for s in (man or {}).get("shots") or [] if isinstance(s, dict)}
    out += ["%s left screenshots.json but is still committed" % f for f in _recorded_files(st)
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
