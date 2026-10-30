"""Commit kind `video` (m1-plan §11): `check_commit.py --stage video <video>`.

The allow-list: the video's `script.<l>.md`, its `CREDITS.yaml`, the files under its `assets/` the scripts show,
`.claude/studio/pronounce.json` (HEAD's with the video's approved readings merged in — v5 S1 · S6 · T4) and the base
voices of its cast (`<sr>/voices/_qwen/<speaker>/<lang>-*.{json,wav}`, made by the first tts). Only changed or new
files are staged.

Before staging (s2v runs here, never in the hook): the light check (approvals, held, proxy approvals and proxy credits
— J131), the router's full check per active language (nothing to redo: a ② rework stales the render, J116), the source
stage's check again (assets.json and the scope check still the recorded ones), check_assets and validate_copy again
(J142), the files the script refers to present, no machine-only path, no orphan base voice, no committed picture whose
CREDITS entry forbids redistribution (every remote counts as public: Studio cannot ask it — J150), no home path or
in-house term in the committed text.

The pronounce merge: HEAD's object in its own order and format, the video's approved readings (the valid
pronounce-approved.json of a person's ② of each active language) that HEAD lacks appended at the end; a key HEAD has
with another value is skipped and named in the summary line (`발음 사전: 충돌 N개 건너뜀 (…)`). The hook checks the
staged file is exactly that."""

import glob
import json
import os
import re

from .. import credits as credits_mod
from .approvals import Problem
from . import approvals
from .kinds import Collected

PRONOUNCE = ".claude/studio/pronounce.json"
HOME_RE = re.compile(r"(/(?:%s)/[A-Za-z0-9._-]+|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+|~/)" % "|".join(("Users", "home")))


def _text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def approved_readings(vdir, state):
    """{written: reading} of the video's valid approved readings (a person's ② and its file's sha)."""
    from ..state import schema
    from ..state.hashes import file_sha
    from ..voice import pronounce
    out = {}
    for lang, L in sorted(state.get("langs", {}).items()):
        if L.get("status") == "aborted":
            continue
        rec = (L.get("approved") or {}).get("2")
        p = pronounce.path_approved(vdir, lang)
        sha = file_sha(p)
        if not isinstance(rec, dict) or rec.get("approved_by") != "human" or sha is None or \
                rec.get(schema.PRONOUNCE_SHA) != sha:
            continue
        obj, _why = pronounce.read(p)
        for k, v in (obj or {}).items():
            out.setdefault(k, v)
    return out


def merge(head_text, readings):
    """(merged text or None when nothing is added, skipped keys). Raises ValueError when HEAD's file is not a flat
    object."""
    from ..voice import pronounce
    head = pronounce.parse(head_text) if head_text and head_text.strip() else {}
    if head is None:
        raise ValueError("HEAD's %s is not a flat object of written form → reading" % PRONOUNCE)
    readings = pronounce.nfc_keys(readings) or {}  # parse already gives NFC keys; a caller's own dict too (A4)
    add, skipped = [], []
    for key, v in readings.items():
        if key not in head:
            add.append((key, v))
        elif head[key] != v:
            skipped.append(key)
    skipped.sort()
    if not add:
        return None, skipped
    body = (head_text or "{}").rstrip()
    if not body.endswith("}"):
        raise ValueError("%s does not end with }" % PRONOUNCE)
    inner = body[:-1].rstrip()
    lines = ",\n".join("  %s: %s" % (json.dumps(k, ensure_ascii=False), json.dumps(v, ensure_ascii=False))
                       for k, v in add)
    if inner.endswith("{"):
        text = inner + "\n" + lines + "\n}\n"
    else:
        text = inner + ",\n" + lines + "\n}\n"
    return text, skipped


def state_of(ctx, rel):
    """"same" · "changed" · "new" · "deleted" · "absent" of one file against HEAD, by content — never by the index's
    stat cache (M1i re-review: a same-size rewrite within the same second escapes `ls-files --modified`)."""
    full = os.path.join(ctx.top, rel)
    head = ctx.git.text("rev-parse", "-q", "--verify", "%s:%s" % (ctx.head, rel)).strip() \
        if ctx.head and ctx.git.ok("rev-parse", "-q", "--verify", "%s:%s" % (ctx.head, rel)) else ""
    if not os.path.lexists(full):
        return "deleted" if head else "absent"
    work = ctx.git.text("hash-object", "--path=" + rel, "--", rel).strip()
    if not head:
        return "new"
    return "same" if work == head else "changed"


def _files_under(ctx, prefix):
    """Every file under a folder: on disk, and in HEAD (so a deletion is seen)."""
    out = set()
    base = os.path.join(ctx.top, prefix)
    for d, _dirs, files in os.walk(base):
        for f in files:
            out.add(os.path.relpath(os.path.join(d, f), ctx.top).replace(os.sep, "/"))
    if ctx.head:
        raw = ctx.git.text("ls-tree", "-r", "-z", "--name-only", ctx.head, "--", ":(literal)" + prefix.rstrip("/"))
        out |= set(p for p in raw.split("\0") if p)
    return sorted(out)


def cast_voices(text):
    """The qwen speakers a script's cast uses."""
    from ..voice import frontmatter
    out = set()
    for spec in (frontmatter.block(text or "", "cast") or {}).values():
        v = spec.get("voice") if isinstance(spec, dict) else None
        if isinstance(v, str) and v.startswith("qwen:"):
            out.add(v[len("qwen:"):])
    return out


def voice_paths(root, speakers, langs):
    """The base-voice path patterns of these speakers and languages."""
    return ["%s/voices/_qwen/%s/%s-" % (root, s, l) for s in sorted(speakers) for l in sorted(langs)]


class VideoKind(object):
    name = "video"
    needs_overlay = True
    proxy_commit = False  # a video is committed after a person's gates only (approvals.light_check: proxy → 4)

    def __init__(self, providers=None, runner=None):
        self.providers = providers
        self.runner = runner

    # ---- the allow-list ----
    def _target_of(self, ctx):
        t = getattr(self, "_target", None)
        if t:
            return t
        from . import okfile
        ok, _why = okfile.read(ctx.top)
        return (ok or {}).get("target") if (ok or {}).get("kind") == "video" else None

    def allowed(self, ctx, path):
        """The target video's paths only (defence in depth: another video's files never ride along)."""
        if path == PRONOUNCE:
            return True
        target = self._target_of(ctx)
        for r in ctx.roots:
            m = re.match(r"^%s/videos/([^/]+)/(.+)$" % re.escape(r), path)
            if m:
                if target is not None and m.group(1) != target:
                    return False
                rest = m.group(2)
                return bool(re.match(r"^script\.[A-Za-z0-9-]+\.md$", rest)) or rest == credits_mod.FILE or \
                    rest.startswith("assets/")
            if path.startswith("%s/voices/_qwen/" % r) and path.endswith((".json", ".wav")):
                return True
        return False

    # ---- --stage ----
    def collect(self, ctx, target):
        from ..state import schema, store
        root = ctx.roots[0]
        if not target or "/" in target:
            return Collected([], problems=[Problem(2, "the video kind needs a video id")])
        vdir = approvals.video_dir(ctx.top, root, target)
        if not os.path.exists(os.path.join(vdir, "work", "state.json")):
            return Collected([], problems=[Problem(1, "video %s has no state on this machine" % target)])
        problems = approvals.light_check(vdir, target)
        if problems:
            return Collected([], problems=problems)
        state = store.read_state(vdir)
        langs = [l for l, L in sorted(state["langs"].items()) if L.get("status") == "active"]
        problems += self._full(ctx, vdir, state, langs, target)
        if problems:
            return Collected([], problems=problems)
        speakers, scripts, pictures = set(), [], set()
        for lang in sorted(state["langs"]):
            if state["langs"][lang].get("status") == "aborted":
                continue
            rel = "%s/videos/%s/script.%s.md" % (root, target, lang)
            scripts.append(rel)
            speakers |= cast_voices(_text(os.path.join(ctx.top, rel)))
        for f in self._files:
            p = os.path.normpath(os.path.join("%s/videos/%s" % (root, target), f))
            if p.startswith("%s/videos/%s/assets/" % (root, target)):
                pictures.add(p)
        # the pronounce merge (written into the work tree, then staged like the rest)
        skipped = []
        head_text = ctx.git.show("%s:%s" % (ctx.head, PRONOUNCE)) if ctx.head else None
        head_text = head_text.decode("utf-8") if isinstance(head_text, bytes) else head_text
        try:
            merged, skipped = merge(head_text, approved_readings(vdir, state))
        except ValueError as e:
            return Collected([], problems=[Problem(1, str(e))])
        if merged is not None:
            with open(os.path.join(ctx.top, PRONOUNCE), "w", encoding="utf-8") as f:
                f.write(merged)
        vprefix = voice_paths(root, speakers, langs or list(state["langs"]))
        voice_dir = "%s/voices/_qwen" % root
        voices = {p: state_of(ctx, p) for p in _files_under(ctx, voice_dir)}
        gone = sorted(p for p, st in voices.items() if st == "deleted")
        if gone:  # a shared base voice is never removed by a video commit (M1i re-review Z1)
            problems.append(Problem(1, "base voices HEAD has are deleted in the work tree: %s — restore them with "
                                       "\"git checkout -- <path>\" (a video commit never removes a shared voice)"
                                       % ", ".join(gone[:5])))
        moved = [p for p, st in voices.items() if st in ("new", "changed")]
        ours = [p for p in moved if any(p.startswith(x) for x in vprefix)]
        others_used = self._other_speakers(ctx, root, target)
        orphans = [p for p in moved if p not in ours and not any(
            p.startswith(x) for x in voice_paths(root, others_used[0], others_used[1]))]
        if orphans:
            problems.append(Problem(1, "base voices no video in progress uses: %s — remove them (they came from a run "
                                       "whose cast changed)" % ", ".join(orphans[:5])))
        wanted = set(scripts) | pictures | {"%s/videos/%s/%s" % (root, target, credits_mod.FILE), PRONOUNCE}
        changed = set(p for p in wanted if state_of(ctx, p) in ("new", "changed"))
        paths = sorted(changed | set(ours))
        self._target = target
        problems += self._content_problems(ctx, vdir, paths, root, target)
        if problems:
            return Collected([], problems=problems)
        extra = ("발음 사전: 충돌 %d개 건너뜀 (%s)" % (len(skipped), " ".join(skipped))) if skipped else None
        col = Collected(paths, states={target: {"last_seq": approvals.state_seq(vdir)}},
                        warnings=["pronounce.json: %d reading(s) of this video skipped (another value is in the "
                                  "shared dictionary): %s" % (len(skipped), ", ".join(skipped))] if skipped else [])
        col.summary_extra = extra
        return col

    def _full(self, ctx, vdir, state, langs, video):
        """The router, the source check, check_assets and validate_copy again (J142)."""
        from .. import board
        from ..distribute import check as copy_check
        from ..source import scope
        from ..state import cli as scli, flow, schema
        from ..state.collect import CollectError, Providers
        providers = self.providers or Providers()
        cfg = ctx.cfg or {}
        out = []
        self._files = []
        _imgs, _sha, note = flow._checked_assets(vdir, state["source"].get("copy_sha"),
                                                 scope.fingerprint(ctx.top, cfg, ctx.env))
        if note or state["source"].get("assets_sha") is None:
            out.append(Problem(1, "video %s: the source's images are not checked as recorded (%s) — run the source "
                                  "stage again" % (video, note or "no assets_sha")))
        for lang in langs:
            sctx = scli._ctx(ctx.top, cfg, vdir, lang)
            try:
                ins = providers.inspect(sctx)
                cur = providers.collect(sctx, state, lang, ins=ins)
            except CollectError as e:
                out.append(Problem(1, "video %s [%s]: %s" % (video, lang, e)))
                continue
            out += approvals.full_check(state, lang, cur, video)
            missing = [f.get("path") for f in ins.get("files") or [] if isinstance(f, dict) and f.get("sha256") is None
                       and not str(f.get("kind") or "").startswith(("voice", "recording"))]
            if missing:
                out.append(Problem(1, "video %s [%s]: files the script refers to are missing: %s"
                                      % (video, lang, ", ".join(missing[:5]))))
            self._files += [f.get("path") for f in ins.get("files") or [] if isinstance(f, dict)]
            for o in schema.current_outputs(state, lang):
                res, details, _cur = board.check(ctx.top, vdir, state, lang, sctx, o, providers, ctx.env,
                                                 self.runner)
                out += [Problem(1, "video %s [%s] %s: check_assets: %s" % (video, lang, o, p))
                        for p in details["problems"]]
            for p in schema.current_platforms(state, lang):
                L = state["langs"][lang]
                cp = L["copies"].get(p, {}).get("path") or os.path.join(
                    sctx["studio_root"], "copy", state["video"], lang, p + ".md")
                cp = cp if os.path.isabs(cp) else os.path.join(ctx.top, cp)
                out += [Problem(1, "video %s [%s] %s: validate_copy: %s" % (video, lang, p, x))
                        for x in copy_check.problems(ctx.top, vdir, state, lang, sctx, p, cfg, ctx.env, cp)]
        return out

    def _other_speakers(self, ctx, root, target):
        from ..state import schema, store
        speakers, langs = set(), set()
        base = os.path.join(ctx.top, root, "videos")
        for v in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if v == target:
                continue
            vd = os.path.join(base, v)
            try:
                st = store.read_state(vd)
            except schema.SchemaError:
                continue
            for lang, L in st["langs"].items():
                if L.get("status") == "aborted":
                    continue
                langs.add(lang)
                speakers |= cast_voices(_text(os.path.join(vd, "script.%s.md" % lang)))
        return speakers, langs

    def _content_problems(self, ctx, vdir, paths, root, target):
        from ..commit.harness import overlay_terms, term_hit
        out = []
        cred, why = credits_mod.read(os.path.join(vdir, credits_mod.FILE))
        if why:
            out.append(Problem(1, why))
        for p in paths:
            if p.startswith("%s/videos/%s/assets/" % (root, target)):
                rel = os.path.relpath(os.path.join(ctx.top, p), vdir).replace(os.sep, "/")
                e = (cred or {}).get(rel)
                if not isinstance(e, dict) or e.get("redistribute") is not True:
                    out.append(Problem(1, "%s is committed, but its CREDITS entry does not allow redistribution "
                                          "(every remote counts as public)" % p, p))
        _st, terms = overlay_terms(ctx.top, ctx.cfg or {}, ctx.env)
        for p in paths:
            if p.endswith((".md", ".yaml", ".json")):
                t = _text(os.path.join(ctx.top, p)) or ""
                h = HOME_RE.search(t)
                if h:
                    out.append(Problem(1, "%s shows a home path (%s)" % (p, h.group(0)), p))
                hit = term_hit(t, terms) if terms else None
                if hit:
                    out.append(Problem(1, "%s uses an in-house term (%s)" % (p, hit), p))
        return out

    # ---- the hook ----
    def staged_problems(self, ctx, studio_paths):
        """The staged pronounce.json is exactly HEAD's with the video's approved readings merged (v5.1 T4)."""
        if PRONOUNCE not in studio_paths:
            return []
        from ..state import schema, store
        vids = sorted(set(v[1] for v in (ctx.cls.video_of(p) for p in studio_paths) if v))
        if len(vids) != 1:
            return [Problem(1, "pronounce.json is committed with exactly one video's commit", PRONOUNCE)]
        vdir = approvals.video_dir(ctx.top, ctx.roots[0], vids[0])
        try:
            state = store.read_state(vdir)
        except schema.SchemaError as e:
            return [Problem(1, "video %s: %s" % (vids[0], e), PRONOUNCE)]
        head = ctx.git.show("%s:%s" % (ctx.head, PRONOUNCE)) if ctx.head else None
        head = head.decode("utf-8") if isinstance(head, bytes) else head
        staged = ctx.git.show(":" + PRONOUNCE)
        staged = staged.decode("utf-8") if isinstance(staged, bytes) else staged
        try:
            want, _skipped = merge(head, approved_readings(vdir, state))
        except ValueError as e:
            return [Problem(1, str(e), PRONOUNCE)]
        if want is None or staged != want:
            return [Problem(1, "the staged pronounce.json is not HEAD's with video %s's approved readings merged — "
                               "stage again with check_commit.py --stage video" % vids[0], PRONOUNCE)]
        return []
