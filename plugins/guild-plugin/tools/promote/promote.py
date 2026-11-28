#!/usr/bin/env python3
"""Channel promotion (readiness T4, R4-2): the development channel's plugin tree → the stable channel's, by names only.

The development channel is the only source. The stable channel is a mechanical copy of it with the channel names
swapped — never edited by hand. This one file does the copy and the checks, and it is channel-neutral: CHANNEL below
says which channel THIS copy of the tool belongs to (it is renamed with everything else), and the copy inside a
promoted tree runs the other way (that is how the round trip V1 is checked). The names are in the table between the
literal-begin / literal-end tags, the same text in both copies.

Usage (standard library only; `python3 -I`):
  promote.py build [--src PLUGIN_DIR] [--out DIR] [--version V] [--marketplace FILE] [--replace]
      PLUGIN_DIR (default: the plugin this file lives in) → DIR/<other channel's plugin folder>/. DIR defaults to
      ~/projects/.gx-promoted/<version>/ and must not be inside the source repository or inside a marketplace
      repository (a folder with .claude-plugin/marketplace.json above it). Writes DIR/marketplace.json too when the
      source repository's (or the given) marketplace file has an entry for the target plugin.
  promote.py check-names [PLUGIN_DIR] [--channel CHANNEL]           V2: no other-channel name outside a tag
  promote.py roundtrip [--src PLUGIN_DIR] [--keep DIR]              V1 (+ V2 on both trees)
  promote.py check-version [PLUGIN_DIR] [--marketplace FILE]        R4-5 version rule of the plugin's channel
Exit: 0 ok · 1 a check failed · 2 usage / refused.

Line tags — a comment on the line (`# promote: <kind>` in code and shell, `<!-- promote: <kind> -->` at the end of a
Markdown line); `rename-exception: <why>` may follow in the same comment (the U0 tag, kept as the reason text):
  self     the default (no tag needed): this channel's names are renamed to the other channel's.
  other    the other channel named on purpose (a refusal, the channel switch): every channel name on the line is
           SWAPPED, so the promoted tree names the development channel there.
  literal  the line is copied as it is (a 0.98.7 path, a table keyed by channel names).
  literal-begin / literal-end   the same for a block of lines (this tool's own name table).
Shared paths that are the same in both channels (GLOBAL_LITERALS — the K2 knowledge folder, the channel file) are
never renamed on any line. Files that cannot carry a comment (JSON fixtures) are listed in FILE_KINDS.
"""
import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

CHANNEL = "gld"                                    # this copy's channel (the promoted copy says the other one)

# promote: literal-begin — the name table is the same text in both channels' copies of this tool
CHANNELS = ("gldx", "gld")
PLUGIN = {"gldx": "guild-exp", "gld": "guild-plugin"}
PLUGIN_DIR = {"gldx": "guild-exp-plugin", "gld": "guild-plugin"}
SKILL = {"gldx": "skills/gldx", "gld": "skills/gld"}
DESCRIPTION_PREFIX = {"gldx": "Guild experimental (redesign: procedure-driven engine). ", "gld": ""}
VERSION_RULE = {"gldx": r"^\d+\.\d+\.\d+-exp\.\d+$", "gld": r"^\d+\.\d+\.\d+$"}
ENV_NAMES = ("ENGINE_HOME", "SRT_BIN", "HOME", "FLUTTER_ROOT", "SDK", "TEST_SRT", "REQUIRE_SRT", "UPDATE_SNAPSHOT",
             "WRITE_SNAPSHOTS", "FAKE_CLAUDE_VERSION", "FAKE_CLAUDE_INIT", "FAKE_CLAUDE_CANARY", "FAKE_CLAUDE_SCENARIOS",
             "FAKE_CLAUDE_SCENARIO", "FAKE_CLAUDE_LOG", "FAKE_GH_FIXTURES", "FAKE_GH_LOG", "EVIL_MARKER", "SAME", "X",
             "RUN_FLAG")
_ENV = "|".join(sorted(ENV_NAMES, key=len, reverse=True))
# (name, development-channel regex, its text, stable-channel regex, its text) — the order is the match priority at
# one position (longest / most specific first). Each pair is a bijection: the swap of a swap is the identity.
RULES = (
    ("plugin folder",   r"plugins/guild-exp-plugin(?![\w-])", "plugins/guild-exp-plugin",
                        r"plugins/guild-plugin(?![\w-])", "plugins/guild-plugin"),
    ("settings folder", r"\.claude/guild-exp(?![\w-])", ".claude/guild-exp",
                        r"\.claude/guild(?![\w-])", ".claude/guild"),
    ("settings part",   r"(?:(?<=\.claude\", \")|(?<=\.claude', '))guild-exp(?=[\"'])", "guild-exp",
                        r"(?:(?<=\.claude\", \")|(?<=\.claude', '))guild(?=[\"'])", "guild"),
    ("env",             r"(?<![\w])GX_(?=(?:" + _ENV + r")(?![\w]))", "GX_",
                        r"(?<![\w])GLD_(?=(?:" + _ENV + r")(?![\w]))", "GLD_"),
    ("plugin name",     r"(?<![\w])guild-exp(?![\w]|-plugin)", "guild-exp",
                        r"(?<![\w])guild-plugin(?![\w])", "guild-plugin"),
    ("branch",          r"(?<![\w.-])(?<!skills/)gx/", "gx/",
                        r"(?<![\w.-])(?<!skills/)gld/", "gld/"),
    ("branch, encoded", r"(?<=%3A)gx(?=%2F)", "gx",
                        r"(?<=%3A)gld(?=%2F)", "gld"),
    ("command",         r"(?<![\w])gldx(?![\w])", "gldx",
                        r"(?<![\w])gld(?![\w])", "gld"),
    ("label",           r"(?<![\w-])gx(?=:|%3A)", "gx",
                        r"(?<![\w-])guild(?=:|%3A)", "guild"),
)
GLOBAL_LITERALS = (".claude/guild/knowledge", ".claude/guild-channel")
# exact strings kept in one file where no line comment can be written (a code fence, JSON) — see FILE_LITERALS below
STABLE_INSTALL = ("deku-claude-plugins@guild-plugin",)                       # the public marketplace's install line
VW1_0987 = (".claude/guild/gates/", '".claude/guild/config.json": "{')     # 0.98.7 files in a recorded tree (VW1)
VW4_0987 = (".claude/guild/config.json v0.102.3",)                           # the 0.98.7 settings a record came from
# loose spellings of the development channel's names: every one must be part of a RULES match (or sit on a tagged line)
DEV_RESIDUE = r"gldx|guild-exp|(?<![\w])GX_[A-Z]"
# promote: literal-end

DEV, STABLE = CHANNELS
OTHER = STABLE if CHANNEL == DEV else DEV

# Not copied into the other channel (paths relative to the plugin folder, this channel's spelling) and not compared
# by the round trip: other repositories' validation records (readiness R4-6 D).
EXCLUDE_DIRS = ("skills/gld/engine/tools/out/", "skills/gld/engine/tools/decisions/")
JUNK = ("__pycache__/", ".DS_Store", ".pytest_cache/")
GENERATED = ("PROMOTED.md",)                         # written by build, never copied, not part of the round trip
PLUGIN_JSON = ".claude-plugin/plugin.json"           # name / version / description come from the table above
# Files that cannot carry a line comment, by kind (this channel's spelling): literal = copied as it is, other = every
# channel name swapped.
FILE_KINDS = {
    "skills/gld/engine/tests/fixtures/claude/f2/r5ctl.jsonl": "literal",     # a recorded session: installed plugins
    "skills/gld/engine/tests/fixtures/gh/issue-42-stage3.json": "other",     # fake GitHub: both followup labels
}
FILE_LITERALS = {
    "README.md": STABLE_INSTALL, "README.ko.md": STABLE_INSTALL, "README.ja.md": STABLE_INSTALL,
    "skills/gld/engine/tests/fixtures/init/app_a_vw1.json": VW1_0987,
    "skills/gld/engine/tests/fixtures/prbody/vw4-1938/inputs.json": VW4_0987,
}

TAG = re.compile(r"(?:#|<!--)[^\n]*?\bpromote:\s*(self|other|literal-begin|literal-end|literal)(?![\w-])")


class Refused(Exception):
    pass


# --- the swap ---------------------------------------------------------------------------------------------------------

def _side(channel):
    return 0 if channel == DEV else 1


def _compile(src, swap):
    """One regex over the names of `src` (and of the other channel too when `swap`); group i → replacement i."""
    s = _side(src)
    parts, repl = [], []
    for _name, dev_rx, dev_txt, st_rx, st_txt in RULES:
        rxs, txts = (dev_rx, st_rx), (dev_txt, st_txt)
        parts.append(rxs[s])
        repl.append(txts[1 - s])
        if swap:
            parts.append(rxs[1 - s])
            repl.append(txts[s])
    alt = "|".join(f"(?P<g{i}>{p})" for i, p in enumerate(parts))
    return re.compile(alt), repl


_CACHE = {}


def _rx(src, swap):
    key = (src, swap)
    if key not in _CACHE:
        _CACHE[key] = _compile(src, swap)
    return _CACHE[key]


def _mask(text, extra=()):
    keep = []

    def put(m):
        keep.append(m.group(0))
        return f"\x00{len(keep) - 1}\x00"
    toks = sorted(set(GLOBAL_LITERALS) | set(extra), key=len, reverse=True)
    return re.sub("|".join(re.escape(x) for x in toks), put, text), keep


def _unmask(text, keep):
    return re.sub("\x00(\\d+)\x00", lambda m: keep[int(m.group(1))], text)


def rename(text, src, swap=False, literals=()):
    """`src` channel names in text → the other channel's (both ways when swap). Global literals stay."""
    rx, repl = _rx(src, swap)
    masked, keep = _mask(text, literals)
    out = rx.sub(lambda m: repl[int(m.lastgroup[1:])], masked)
    return _unmask(out, keep)


def find_names(text, channel, literals=()):
    """[(name, token)] of `channel`'s names in text (global literals masked)."""
    rx, _ = _rx(channel, False)
    masked, _keep = _mask(text, literals)
    return [(RULES[int(m.lastgroup[1:])][0], m.group(0)) for m in rx.finditer(masked)]


def line_kinds(lines):
    """Kind of every line: self / other / literal (blocks resolved)."""
    kinds, block = [], False
    for ln in lines:
        m = TAG.search(ln)
        k = m.group(1) if m else None
        if k == "literal-begin":
            block = True
            kinds.append("literal")
        elif k == "literal-end":
            block = False
            kinds.append("literal")
        elif block:
            kinds.append("literal")
        else:
            kinds.append(k or "self")
    return kinds


def transform_text(text, src, file_kind=None, literals=()):
    if file_kind == "literal":
        return text
    lines = text.splitlines(keepends=True)
    kinds = ["other"] * len(lines) if file_kind == "other" else line_kinds(lines)
    out = []
    for ln, k in zip(lines, kinds):
        if k == "literal":
            out.append(ln)
        else:
            out.append(rename(ln, src, swap=(k == "other"), literals=literals))
    return "".join(out)


def rename_path(rel, src):
    return rename(rel, src)


# --- the trees --------------------------------------------------------------------------------------------------------

def _excluded(rel, channel):
    dirs = EXCLUDE_DIRS if channel == CHANNEL else tuple(rename(d, CHANNEL) for d in EXCLUDE_DIRS)
    if any(rel.startswith(d) for d in dirs):
        return True
    parts = rel.split("/")
    if any(p + "/" in JUNK or p in JUNK for p in parts):
        return True
    return rel in GENERATED


def _file_kind(rel, channel):
    for path, kind in FILE_KINDS.items():
        p = path if channel == CHANNEL else rename(path, CHANNEL)
        if rel == p or (p.endswith("/") and rel.startswith(p)):
            return kind
    return None


def _file_literals(rel, channel):
    for path, toks in FILE_LITERALS.items():
        if rel == (path if channel == CHANNEL else rename(path, CHANNEL)):
            return toks
    return ()


def tree_files(root):
    """Relative paths of the plugin tree: git's tracked files when it is a git checkout, else every file."""
    root = os.path.realpath(root)
    try:
        top = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        top = None
    if top:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                              "."], capture_output=True, check=True).stdout
        files = [p for p in out.decode("utf-8").split("\0") if p]
        return sorted(p for p in files if os.path.isfile(os.path.join(root, p)))
    found = []
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        for n in names:
            found.append(os.path.relpath(os.path.join(d, n), root).replace(os.sep, "/"))
    return sorted(found)


def channel_of(root):
    with open(os.path.join(root, PLUGIN_JSON), encoding="utf-8") as f:
        name = json.load(f)["name"]
    for ch in CHANNELS:
        if PLUGIN[ch] == name:
            return ch
    raise Refused(f"{root}: plugin.json names `{name}`, not a Guild channel ({', '.join(PLUGIN.values())})")


def _read(path):
    with open(path, "rb") as f:
        data = f.read()
    if b"\0" in data:
        return data, None
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError:
        return data, None


def target_version(src_version, src, dst):
    if not re.match(VERSION_RULE[src], src_version):
        raise Refused(f"version {src_version} does not follow the {src} channel's rule {VERSION_RULE[src]}")
    if dst == STABLE:
        return src_version.split("-exp.")[0]                       # R4-5: the stable version drops -exp.N
    major, minor, _patch = (int(x) for x in src_version.split("."))
    return f"{major}.{minor + 1}.0-exp.1"                           # R4-5: the next development line


def _plugin_json(text, dst, version):
    data = json.loads(text)
    data["name"] = PLUGIN[dst]
    data["version"] = version
    desc = data.get("description", "")
    for ch in CHANNELS:
        if DESCRIPTION_PREFIX[ch] and desc.startswith(DESCRIPTION_PREFIX[ch]):
            desc = desc[len(DESCRIPTION_PREFIX[ch]):]
    data["description"] = DESCRIPTION_PREFIX[dst] + desc
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _inside(path, top):
    path, top = os.path.realpath(path), os.path.realpath(top)
    return path == top or path.startswith(top + os.sep)


def _marketplace_repo(path):
    d = os.path.realpath(path)
    while True:
        if os.path.isfile(os.path.join(d, ".claude-plugin", "marketplace.json")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def _git_top(path):
    try:
        return subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (subprocess.CalledProcessError, OSError):
        return None


def _source_rev(src):
    top = _git_top(src)
    if not top:
        return None, None
    rev = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", src, "status", "--porcelain", "--", "."], capture_output=True,
                           text=True).stdout.strip()
    return rev or None, bool(dirty)


def build(src, out, version=None, marketplace=None, replace=False, check_out=True):
    """src plugin tree → out/<target plugin folder>. Returns (target dir, report dict)."""
    src = os.path.realpath(src)
    s_ch = channel_of(src)
    d_ch = OTHER if s_ch == CHANNEL else CHANNEL
    with open(os.path.join(src, PLUGIN_JSON), encoding="utf-8") as f:
        src_json = f.read()
    s_ver = json.loads(src_json)["version"]
    d_ver = version or target_version(s_ver, s_ch, d_ch)
    if not re.match(VERSION_RULE[d_ch], d_ver):
        raise Refused(f"version {d_ver} does not follow the {d_ch} channel's rule {VERSION_RULE[d_ch]}")
    out = os.path.realpath(os.path.expanduser(out))
    if check_out:
        top = _git_top(src)
        if top and _inside(out, top):
            raise Refused(f"{out} is inside the source repository {top} — promote writes outside it")
        mk = _marketplace_repo(out)
        if mk:
            raise Refused(f"{out} is inside a marketplace repository ({mk}) — the public copy is made by a human "
                          "after the checks, never by this tool")
    dst = os.path.join(out, PLUGIN_DIR[d_ch])
    if os.path.lexists(dst):
        if not replace:
            raise Refused(f"{dst} exists — pass --replace to make it again")
        if not os.path.isfile(os.path.join(dst, PLUGIN_JSON)):
            raise Refused(f"{dst} exists and is not a plugin folder — not replaced")
        shutil.rmtree(dst)
    os.makedirs(dst)
    report = {"from": {"channel": s_ch, "plugin": PLUGIN[s_ch], "version": s_ver, "path": src},
              "to": {"channel": d_ch, "plugin": PLUGIN[d_ch], "version": d_ver, "path": dst},
              "files": 0, "renamed_lines": 0, "binary": [], "skipped": []}
    for rel in tree_files(src):
        if _excluded(rel, s_ch):
            report["skipped"].append(rel)
            continue
        out_rel = rename_path(rel, s_ch)
        target = os.path.join(dst, out_rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        data, text = _read(os.path.join(src, rel))
        if rel == PLUGIN_JSON:
            with open(target, "w", encoding="utf-8", newline="") as f:
                f.write(_plugin_json(text, d_ch, d_ver))
        elif text is None:
            report["binary"].append(rel)
            with open(target, "wb") as f:
                f.write(data)
        else:
            new = transform_text(text, s_ch, _file_kind(rel, s_ch), _file_literals(rel, s_ch))
            report["renamed_lines"] += sum(1 for a, b in zip(text.splitlines(), new.splitlines()) if a != b)
            with open(target, "w", encoding="utf-8", newline="") as f:
                f.write(new)
        shutil.copymode(os.path.join(src, rel), target)
        report["files"] += 1
    if d_ch == STABLE:
        rev, dirty = _source_rev(src)
        with open(os.path.join(dst, "PROMOTED.md"), "w", encoding="utf-8") as f:
            f.write(promoted_md(s_ver, d_ver, rev, dirty))
    report["marketplace"] = write_marketplace(src, out, d_ch, d_ver, marketplace)
    return dst, report


def promoted_md(s_ver, d_ver, rev, dirty):
    # promote: literal-begin — names the development channel on purpose (provenance)
    return ("# Promoted build — do not edit this folder by hand\n\n"
            f"- version: {d_ver}\n"
            f"- promoted from: guild-exp {s_ver} (`plugins/guild-exp-plugin/`)"
            + (f" at commit `{rev}`" + (" with uncommitted changes" if dirty else "") if rev else "") + "\n"
            "- made by: `tools/promote/promote.py build` — the stable channel is a mechanical copy of the development\n"
            "  channel with the channel names swapped. Change the development channel and promote again.\n")
    # promote: literal-end


def write_marketplace(src, out, d_ch, d_ver, marketplace):
    """A copy of the marketplace file with the target plugin's version — only when it lists that plugin.
    marketplace None = the source repository's; "" = none."""
    if marketplace is None:
        top = _git_top(src)
        cand = os.path.join(top, ".claude-plugin", "marketplace.json") if top else None
        marketplace = cand if cand and os.path.isfile(cand) else None
    if not marketplace:
        return None
    with open(marketplace, encoding="utf-8") as f:
        text = f.read()
    data = json.loads(text)
    entries = [p for p in data.get("plugins", []) if p.get("name") == PLUGIN[d_ch]]
    if len(entries) != 1:
        return {"path": None, "note": f"{marketplace} has {len(entries)} entries for {PLUGIN[d_ch]} — not written"}
    old = entries[0].get("version")
    pat = re.compile(r'("name"\s*:\s*"' + re.escape(PLUGIN[d_ch]) + r'"[^{}]*?"version"\s*:\s*")([^"]*)(")', re.S)
    new_text, n = pat.subn(lambda m: m.group(1) + d_ver + m.group(3), text, count=1)
    if n != 1:
        raise Refused(f"{marketplace}: cannot find the version of the {PLUGIN[d_ch]} entry in the text")
    check = json.loads(new_text)
    entries[0]["version"] = d_ver
    if check != data:
        raise Refused(f"{marketplace}: the edit changed more than the {PLUGIN[d_ch]} version")
    path = os.path.join(out, "marketplace.json")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    return {"path": path, "plugin": PLUGIN[d_ch], "from": old, "to": d_ver, "source": os.path.realpath(marketplace)}


# --- V2: names ------------------------------------------------------------------------------------------------------

def check_names(root, channel=None):
    """Lines of a `channel` tree that name the other channel outside an `other` / `literal` tag, and loose
    development-channel spellings no rule covers. [(rel, line no, problem, text)]."""
    root = os.path.realpath(root)
    channel = channel or channel_of(root)
    other = STABLE if channel == DEV else DEV
    residue = re.compile(DEV_RESIDUE)
    bad = []
    for rel in tree_files(root):
        if _excluded(rel, channel) or rel == PLUGIN_JSON:
            continue
        kind = _file_kind(rel, channel)
        if kind in ("literal", "other"):
            continue
        for name, tok in find_names(rel, other):
            bad.append((rel, 0, f"path names the {other} channel ({name} `{tok}`)", rel))
        _data, text = _read(os.path.join(root, rel))
        lits = _file_literals(rel, channel)
        if text is None:
            if any(x in _data for x in (b"gld", b"guild-plugin")):
                bad.append((rel, 0, "binary file holds a channel name", ""))
            continue
        lines = text.splitlines()
        for i, (ln, k) in enumerate(zip(lines, line_kinds(lines)), 1):
            if k == "literal" and find_names(ln, channel, lits) and any(g in ln for g in GLOBAL_LITERALS):
                bad.append((rel, i, "a literal tag freezes this channel's names on a line whose shared path is kept "
                                    "anyway — drop the tag (or tag it `promote: other`)", ln.strip()[:160]))
            if k != "self":
                continue
            for name, tok in find_names(ln, other, lits):
                bad.append((rel, i, f"names the {other} channel ({name} `{tok}`) — tag the line "
                                    "`promote: other` or `promote: literal`, or rename it", ln.strip()[:160]))
            # every loose development-channel spelling must be part of a rule's match
            masked, _ = _mask(ln, lits)
            covered = [m.span() for m in _rx(DEV, False)[0].finditer(masked)]
            for m in residue.finditer(masked):
                if not any(a <= m.start() < b for a, b in covered):
                    bad.append((rel, i, f"`{m.group(0)}` here is no channel name any rule renames", ln.strip()[:160]))
    return bad


# --- V1: the round trip ---------------------------------------------------------------------------------------------

def compare_trees(a, b, a_channel):
    """Differences between plugin tree a (a git checkout or a folder) and folder b, both of `a_channel`; the excluded
    and generated files are left out, plugin.json is compared without its version."""
    fa = {r for r in tree_files(a) if not _excluded(r, a_channel)}
    fb = {r for r in tree_files(b) if not _excluded(r, a_channel)}
    diffs = [f"only in the source: {r}" for r in sorted(fa - fb)] + [f"only in the round trip: {r}" for r in sorted(fb - fa)]
    for r in sorted(fa & fb):
        pa, pb = os.path.join(a, r), os.path.join(b, r)
        da, ta = _read(pa)
        db, tb = _read(pb)
        if r == PLUGIN_JSON:
            ja, jb = json.loads(ta), json.loads(tb)
            ja.pop("version", None)
            jb.pop("version", None)
            if ja != jb:
                diffs.append(f"{r}: differs beyond the version")
            continue
        if da != db:
            if ta is not None and tb is not None:
                d = list(difflib.unified_diff(ta.splitlines(), tb.splitlines(), r, r + " (round trip)", n=0,
                                              lineterm=""))
                diffs.append(f"{r}: differs\n" + "\n".join(d[:12]))
            else:
                diffs.append(f"{r}: differs (binary)")
        elif (os.stat(pa).st_mode & 0o111) != (os.stat(pb).st_mode & 0o111):
            diffs.append(f"{r}: the executable bit differs")
    return diffs


def roundtrip(src, keep=None):
    """V1: build src into a temporary folder, build that back with the PROMOTED copy of this tool, compare."""
    src = os.path.realpath(src)
    s_ch = channel_of(src)
    work = keep or tempfile.mkdtemp(prefix="promote-rt-")
    os.makedirs(work, exist_ok=True)
    one, two = os.path.join(work, "one"), os.path.join(work, "two")
    dst, rep = build(src, one, replace=True, check_out=False)
    tool = os.path.join(dst, "tools", "promote", "promote.py")
    p = subprocess.run([sys.executable, "-I", "-B", tool, "build", "--src", dst, "--out", two, "--replace",
                        "--no-marketplace", "--json"], capture_output=True, text=True)
    if p.returncode != 0:
        return {"ok": False, "problems": [f"the promoted tool failed: {p.stderr.strip() or p.stdout.strip()}"],
                "work": work}
    back = json.loads(p.stdout)["to"]["path"]
    problems = compare_trees(src, back, s_ch)
    return {"ok": not problems, "problems": problems, "work": work, "promoted": dst, "back": back,
            "files": rep["files"], "renamed_lines": rep["renamed_lines"]}


# --- R4-5: the version rule -----------------------------------------------------------------------------------------

def check_version(root, marketplace=None):
    root = os.path.realpath(root)
    ch = channel_of(root)
    with open(os.path.join(root, PLUGIN_JSON), encoding="utf-8") as f:
        ver = json.load(f)["version"]
    problems = []
    if not re.match(VERSION_RULE[ch], ver):
        problems.append(f"{PLUGIN_JSON}: version {ver} does not follow the {ch} channel's rule {VERSION_RULE[ch]}")
    if marketplace:
        with open(marketplace, encoding="utf-8") as f:
            entries = [p for p in json.load(f).get("plugins", []) if p.get("name") == PLUGIN[ch]]
        if ch == STABLE and len(entries) != 1:
            problems.append(f"{marketplace}: {len(entries)} entries for {PLUGIN[ch]} (one expected)")
        for e in entries:
            if e.get("version") != ver:
                problems.append(f"{marketplace}: {PLUGIN[ch]} {e.get('version')} ≠ {PLUGIN_JSON} {ver} — update both")
    if ch == STABLE:
        prov = os.path.join(root, "PROMOTED.md")
        text = open(prov, encoding="utf-8").read() if os.path.isfile(prov) else ""
        m = re.search(r"promoted from: \S+ (\d+\.\d+\.\d+-exp\.\d+)", text)
        if not m:
            problems.append("PROMOTED.md: no `promoted from: <plugin> <X.Y.Z-exp.N>` line — the stable channel is "
                            "made by promote.py build only")
        elif m.group(1).split("-exp.")[0] != ver:
            problems.append(f"PROMOTED.md: promoted from {m.group(1)}, so the version is "
                            f"{m.group(1).split('-exp.')[0]}, not {ver}")
    return {"channel": ch, "version": ver, "problems": problems}


# --- command line ---------------------------------------------------------------------------------------------------

HERE = os.path.dirname(os.path.realpath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promote.py", description="Guild channel promotion (names only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--src", default=PLUGIN_ROOT)
    b.add_argument("--out")
    b.add_argument("--version")
    b.add_argument("--marketplace")
    b.add_argument("--no-marketplace", action="store_true")
    b.add_argument("--replace", action="store_true")
    b.add_argument("--json", action="store_true")
    n = sub.add_parser("check-names")
    n.add_argument("root", nargs="?", default=PLUGIN_ROOT)
    n.add_argument("--channel", choices=CHANNELS)
    r = sub.add_parser("roundtrip")
    r.add_argument("--src", default=PLUGIN_ROOT)
    r.add_argument("--keep")
    v = sub.add_parser("check-version")
    v.add_argument("root", nargs="?", default=PLUGIN_ROOT)
    v.add_argument("--marketplace")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            src = os.path.realpath(a.src)
            if a.out:
                out = a.out
            else:
                with open(os.path.join(src, PLUGIN_JSON), encoding="utf-8") as f:
                    s_ver = json.load(f)["version"]
                s_ch = channel_of(src)
                d_ver = a.version or target_version(s_ver, s_ch, OTHER if s_ch == CHANNEL else CHANNEL)
                out = os.path.join("~", "projects", ".gx-promoted", d_ver)
            dst, rep = build(src, out, a.version, "" if a.no_marketplace else a.marketplace, a.replace)
            if a.json:
                print(json.dumps(rep, ensure_ascii=False))
            else:
                print(f"promoted {rep['from']['plugin']} {rep['from']['version']} → {rep['to']['plugin']} "
                      f"{rep['to']['version']}: {dst}")
                print(f"  {rep['files']} files, {rep['renamed_lines']} lines renamed, "
                      f"{len(rep['skipped'])} left out, {len(rep['binary'])} binary copied as they are")
                if rep["marketplace"]:
                    print(f"  marketplace: {rep['marketplace']}")
            return 0
        if a.cmd == "check-names":
            bad = check_names(a.root, a.channel)
            for rel, i, why, text in bad:
                print(f"{rel}:{i}: {why}\n    {text}")
            print(f"check-names: {len(bad)} problem(s)")
            return 1 if bad else 0
        if a.cmd == "roundtrip":
            res = roundtrip(a.src, a.keep)
            for p in res["problems"]:
                print(p)
            print(f"roundtrip: {'OK' if res['ok'] else 'FAIL'} ({res.get('files', 0)} files, "
                  f"{res.get('renamed_lines', 0)} lines renamed; work {res['work']})")
            if not a.keep and res["ok"]:
                shutil.rmtree(res["work"], ignore_errors=True)
            return 0 if res["ok"] else 1
        if a.cmd == "check-version":
            res = check_version(a.root, a.marketplace)
            for p in res["problems"]:
                print(p)
            print(f"check-version: {res['channel']} {res['version']} {'OK' if not res['problems'] else 'FAIL'}")
            return 1 if res["problems"] else 0
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
