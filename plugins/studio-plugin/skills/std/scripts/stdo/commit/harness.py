"""The harness commit kind (m0f-plan v4 §2): `.claude/studio/**` (not local/), `.claude/agents/std-*.md`, the
Studio blocks of `.gitignore` and the tracked `.husky/pre-commit`. Checks run on the index (what is committed):
H2 home paths · H3 internal terms · H4 internal guide items · H6 studio_root · H10 the scripts copy equals its
manifest (complete) · H11 no links/submodules · H12 husky block == template · H13 .gitignore block · H14 deletions
that are not a harness change."""

import json
import os
import re

from .. import SCRIPTS_VERSION, ignore, manifest, paths
from ..hooks import templates as T
from . import spaths
from .approvals import Problem
from .kinds import Collected

SCRIPTS = ".claude/studio/scripts/"
MANIFEST = SCRIPTS + manifest.NAME
NO_DELETE = (spaths.CONFIG, MANIFEST, ".claude/studio/charter.md", ".claude/agents/std-fact-checker.md",
             ".claude/agents/std-source-analyst.md")
CONTENT = (".claude/studio/charter.md", ".claude/studio/brand.json", ".claude/studio/config.json",
           ".claude/studio/pronounce.json", ".claude/studio/evolution-log.md")
CONTENT_DIRS = (".claude/studio/formats/", ".claude/studio/platforms/", ".claude/studio/guides/")
INTERNAL_DIRS = (".claude/studio/guides/", ".claude/studio/formats/", ".claude/studio/platforms/")
_HOMES = ("Users", "home")  # macOS and Linux user folders (kept apart so this file names no home path itself)
HOME_RE = re.compile(r"(/(?:%s)/[A-Za-z0-9._-]+|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+|~/)" % "|".join(_HOMES))
HOME_OK = set("/%s/%s" % (h, n) for h in _HOMES for n in ("user", "me", "name", "you"))  # example names
SCOPE_RE = re.compile(r"^\s*(<!--\s*)?scope:\s*internal\b", re.I | re.M)
MIN_TERM = 4


def old_s2v_path(cfg):
    """config.json in the format before M1a: a machine's s2v folder in a committed file (m1-plan §3.1)."""
    s2v = cfg.get("s2v") if isinstance(cfg, dict) else None
    return isinstance(s2v, dict) and "path" in s2v


OLD_FORMAT = Problem(1, "config.json has s2v.path — the old format: this machine's s2v path now lives in "
                        ".claude/studio/local/machine.json (not committed). Remove \"path\" from config.json's s2v "
                        "and set the path with /std config s2v.path", spaths.CONFIG)


def _content(p):
    """Guides, criteria, platform rules and other content files (H3 with a missing overlay, m0f-plan Q2)."""
    return (p in CONTENT or p.startswith(CONTENT_DIRS)) and p != spaths.CONFIG


class HarnessKind(object):
    name = "harness"
    needs_overlay = False  # nothing internal; H3 decides about content files
    proxy_commit = True  # the sandbox proxy mode may commit the harness (not with protected key changes)

    def allowed(self, ctx, path):
        if ctx.cls.is_local(path):
            return False
        if path in (spaths.GITIGNORE, spaths.HUSKY):
            return True
        if path.startswith(".claude/studio/"):
            return True
        return path.startswith(".claude/agents/std-") and path.endswith(".md")

    def collect(self, ctx, target):
        if target:
            return Collected([], problems=[Problem(2, "a harness commit takes no target")])
        specs = ["--", ":(literal).claude/studio", ":(glob).claude/agents/std-*.md"]
        raw = ctx.git.text("ls-files", "-z", "--modified", "--deleted", "--others", "--exclude-standard", *specs)
        cached = ctx.git.text("diff", "--name-only", "-z", "--no-renames", ctx.head or ctx.git.empty_tree(), *specs)
        found = sorted(set(p for p in (raw + "\0" + cached).split("\0") if p and self.allowed(ctx, p)))
        problems = []
        if old_s2v_path(ctx.cfg):
            problems.append(OLD_FORMAT)  # also when config.json itself is not part of this commit
        gi = False
        try:
            with open(os.path.join(ctx.top, spaths.GITIGNORE), "rb") as f:
                work = f.read()
        except OSError:
            work = None
        head_gi = ctx.git.show("%s:%s" % (ctx.head, spaths.GITIGNORE)) if ctx.head else None
        if spaths.gitignore_kind(head_gi, work) in ("studio", "mixed"):
            gi = True
        try:
            with open(os.path.join(ctx.top, spaths.HUSKY), "rb") as f:
                hwork = f.read()
        except OSError:
            hwork = None
        head_h = ctx.git.show("%s:%s" % (ctx.head, spaths.HUSKY)) if ctx.head else None
        hk = spaths.husky_kind(head_h, hwork) if (hwork is not None or head_h is not None) else "none"
        if hk == "studio":
            found.append(spaths.HUSKY)
        elif hk in ("mixed", "broken"):
            problems.append(Problem(1, ".husky/pre-commit has changes outside Studio's block (or broken markers) — "
                                       "commit those separately", spaths.HUSKY))
        return Collected(sorted(set(found)), gitignore=gi, problems=problems)

    # --- checks on the index (stage and hook) ---
    def staged_problems(self, ctx, studio_paths):
        out = []
        git = ctx.git
        status = dict((p, st) for st, p in git.staged(ctx.base))
        present = [p for p in studio_paths if status.get(p) != "D"]
        # H14 deletions that are not a harness change
        listed = self._manifest_index(ctx)
        for p in studio_paths:
            if status.get(p) != "D":
                continue
            rel = p[len(SCRIPTS):] if p.startswith(SCRIPTS) else None
            if p in NO_DELETE or (rel and listed and rel in listed[0]):
                out.append(Problem(1, "%s is deleted — taking Studio (or its criteria) out of the repository is the "
                                      "person's removal procedure, not a harness commit" % p, p))
        # H11 links and submodules
        if present:
            raw = git.text("ls-files", "-s", "-z", "--", *[":(literal)" + p for p in present])
            for rec in raw.split("\0"):
                if rec:
                    meta, path = rec.split("\t", 1)
                    if meta.split()[0] in ("120000", "160000"):
                        out.append(Problem(1, "%s is a symbolic link or a submodule — a harness commit holds files "
                                              "only" % path, path))
        # H10 the scripts copy is complete and equals its manifest
        if any(p.startswith(SCRIPTS) for p in studio_paths) or listed is None:
            out += self._scripts_problems(ctx, listed)
        # H12 husky block
        if spaths.HUSKY in present:
            blk = spaths.husky_block(git.show(":" + spaths.HUSKY))
            if blk != T.husky_block():
                out.append(Problem(1, ".husky/pre-commit's Studio block is not this version's (hooks.py install "
                                      "proposes it); removing or changing it is the person's decision", spaths.HUSKY))
        # H13 .gitignore block
        if spaths.GITIGNORE in studio_paths:
            out += gitignore_block_problems(git.show(":" + spaths.GITIGNORE), ctx.roots[0])
        # H6 config
        if spaths.CONFIG in present:
            cfg = _json(git.show(":" + spaths.CONFIG))
            if cfg is None:
                out.append(Problem(2, ".claude/studio/config.json is not a JSON object", spaths.CONFIG))
            else:
                if old_s2v_path(cfg):
                    out.append(OLD_FORMAT)  # the committed blob (the work tree copy may say otherwise)
                old = _json(git.show("%s:%s" % (ctx.head, spaths.CONFIG))) if ctx.head else None
                if isinstance(old, dict) and (old.get("studio_root") or "studio") != (cfg.get("studio_root") or "studio"):
                    out.append(Problem(3, "studio_root changes — moving Studio's folder is not supported yet (M1)",
                                       spaths.CONFIG))
        # H2 · H3 · H4 on content and config files
        texts = {}
        listed_files = listed[0] if listed else {}
        for p in present:
            # every text file of the commit except the scripts copy (H10 holds it byte-identical to the plugin's;
            # its docstrings name ~/.claude) — review MINOR-1
            if p.startswith(SCRIPTS) and p[len(SCRIPTS):] in listed_files:
                continue
            data = git.show(":" + p)
            if data is not None and b"\0" not in data[:8192]:
                texts[p] = data.decode("utf-8", "replace")
        home = os.path.realpath(ctx.env.get("HOME") or os.path.expanduser("~"))
        for p, t in sorted(texts.items()):
            for n, line in enumerate(t.splitlines(), 1):
                for m in HOME_RE.finditer(line):
                    if m.group(0) == "~/" or m.group(0) not in HOME_OK:
                        out.append(Problem(1, "%s:%d has a home-folder path (%s) — committed files must not name a "
                                              "machine's folders" % (p, n, m.group(0)), p))
                        break
                if home not in ("/", "") and home in line:
                    out.append(Problem(1, "%s:%d has this machine's home folder" % (p, n), p))
            if p.startswith(INTERNAL_DIRS) and SCOPE_RE.search(t):
                out.append(Problem(1, "%s has an internal item (scope: internal) — internal guide items live in "
                                      ".claude/studio/local/" % p, p))
        out += self._terms(ctx, texts)
        return out

    def _manifest_index(self, ctx):
        data = ctx.git.show(":" + MANIFEST)
        if data is None:
            return None
        try:
            return manifest.parse(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _scripts_problems(self, ctx, listed):
        if listed is None:
            return [Problem(1, "%s is missing or unreadable in the commit — copy Studio's scripts again" % MANIFEST,
                            MANIFEST)]
        files, version = listed
        out = []
        if version != SCRIPTS_VERSION:
            out.append(Problem(1, "the committed scripts are version %s, this check is %s — copy them again"
                                  % (version, SCRIPTS_VERSION), MANIFEST))
        raw = ctx.git.text("ls-files", "-s", "-z", "--", ":(literal)" + SCRIPTS.rstrip("/"))
        have = {}
        for rec in raw.split("\0"):
            if rec:
                meta, path = rec.split("\t", 1)
                have[path[len(SCRIPTS):]] = meta.split()[1]
        have.pop(manifest.NAME, None)
        extra = sorted(set(have) - set(files))
        missing = sorted(set(files) - set(have))
        if extra:
            out.append(Problem(1, "files in Studio's scripts that its manifest does not list: %s"
                                  % ", ".join(extra[:5]), SCRIPTS + extra[0]))
        if missing:
            out.append(Problem(1, "files of Studio's scripts missing from the commit: %s" % ", ".join(missing[:5]),
                               SCRIPTS + missing[0]))
        import hashlib
        common = sorted(set(have) & set(files))
        ctx.git.prefetch([":" + SCRIPTS + r for r in common])
        bad = []
        for r in common:
            data = ctx.git.show(":" + SCRIPTS + r)
            if data is None or hashlib.sha256(data).hexdigest() != files[r]:
                bad.append(r)
        if bad:
            out.append(Problem(1, "Studio's scripts differ from their manifest (edited copy): %s" % ", ".join(bad[:5]),
                               SCRIPTS + bad[0]))
        return out

    def _terms(self, ctx, texts):
        if not texts:
            return []
        state, terms = overlay_terms(ctx.top, ctx.cfg, ctx.env)
        if state == "none":
            return []
        if state == "missing":
            content = [p for p in texts if _content(p)]
            if content:
                return [Problem(4, "the internal overlay is missing or changed, so the guide and criteria files "
                                   "(%s) cannot be checked for internal terms — ask the person to recreate it "
                                   "(/std config)" % ", ".join(sorted(content)[:3]))]
            return []
        out = []
        for p, t in sorted(texts.items()):
            hit = term_hit(t, terms)
            if hit:
                out.append(Problem(1, "%s names an internal term (\"%s…\") — internal content stays in "
                                      ".claude/studio/local/" % (p, hit[:3]), p))
        return out


def gitignore_block_problems(data, root):
    text = (data or b"").decode("utf-8", "surrogateescape")
    try:
        _rest, blk = ignore.split(text)
    except ignore.BlockError:
        return [Problem(1, ".gitignore's Studio block markers are unpaired or repeated", spaths.GITIGNORE)]
    if blk is None:
        return [Problem(1, ".gitignore lacks Studio's block", spaths.GITIGNORE)]
    have = [l.strip() for l in blk.splitlines() if l.strip()]
    want = [l.strip() for l in ignore.render(root).splitlines() if l.strip()]
    out = []
    missing = [l for l in want if l not in have and not l.startswith("#")]
    if missing:
        out.append(Problem(1, ".gitignore's Studio block lacks %s" % ", ".join(missing[:3]), spaths.GITIGNORE))
    neg = [l for l in have if l.startswith("!") and l not in want]
    if neg:
        out.append(Problem(1, ".gitignore's Studio block re-includes paths (%s) — only the template's lines may "
                              "start with !" % ", ".join(neg[:3]), spaths.GITIGNORE))
    return out


def _json(data):
    if data is None:
        return None
    try:
        v = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return v if isinstance(v, dict) else None


def overlay_terms(top, cfg, env):
    """("none" | "ok" | "missing", [terms]) — the keys the guard reads (m0d2-plan §9.2), without the guard."""
    import hashlib
    if not isinstance(cfg, dict) or cfg.get("internal_overlay") != "required":
        return "none", []
    p = os.path.join(top, ".claude", "studio", "local", "config.internal.json")
    try:
        with open(p, "rb") as f:
            raw = f.read()
        with open(os.path.join(paths.backup_root(env), paths.repo_key(top), "overlay.sha"), encoding="utf-8") as f:
            want = f.read().strip()
    except (OSError, RuntimeError, ValueError):
        return "missing", []
    if hashlib.sha256(raw).hexdigest() != want:
        return "missing", []
    data = _json(raw)
    inner = data.get("internal") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
        return "ok", []
    terms = [t for t in inner.get("terms") or [] if isinstance(t, str)]
    terms += [h for h in inner.get("hosts") or [] if isinstance(h, str)]
    terms += [x for x in (inner.get("videos") or []) + (inner.get("actors") or []) if isinstance(x, str)]
    return "ok", sorted(set(t.strip() for t in terms if len(t.strip()) >= MIN_TERM))


def term_hit(text, terms):
    low = text.casefold()
    for t in terms:
        tl = t.casefold()
        if re.match(r"^[\x00-\x7f]+$", t):
            if re.search(r"(?<![0-9a-z])%s(?![0-9a-z])" % re.escape(tl), low):
                return t
        elif tl in low:
            return t
    return None
