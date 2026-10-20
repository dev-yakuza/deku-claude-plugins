"""Shell snapshots (m0d1a-plan §5.4): Claude Code's Bash tool runs
`/bin/zsh -c 'source <config>/shell-snapshots/snapshot-zsh-<ms>-<rand>.sh … && setopt … && eval <cmd>'`.
Snapshots are created at a session's first Bash call and deleted when the session ends, and the
hook cannot tell which one belongs to the session — so every recent snapshot is read and merged:
an alias is an alias only when every variant agrees; otherwise its alternatives are expanded.
Nothing here executes the snapshot.
"""

import hashlib
import json
import os
import re
import time

from .model import NOT_ALIAS

MAX_AGE = 14 * 24 * 3600
MAX_FILES = 30
MAX_DISTINCT = 8
MAX_SIZE = 1024 * 1024
NAME_RE = re.compile(r"^snapshot-zsh-.+\.sh$")
# Claude Code's own sections after the aliases (column 0, prefix match: the pkill marker has a tail)
CLAUDE_MARKERS = ("# Check for rg availability", "# Shadow find/grep with embedded bfs/ugrep", "# Shadow pkill")
DELEGATED_NAMES = ("find", "grep", "rg", "pkill")
# applied by the Bash tool after `source <snapshot>` (measured, Claude Code 2.1.304; re-check on updates)
BASH_TOOL_POSTLUDE = {"options": {"extendedglob": False, "bareglobqual": False},
                      "unalias": ("unsetenv",), "unfunction": ("unsetenv",)}
DEFAULT_OPTIONS = {"autocd": True, "autopushd": True, "nomatch": True, "interactivecomments": True,
                   "rcquotes": False, "shwordsplit": False, "cdablevars": False, "pushdminus": False,
                   "pushdignoredups": False, "equals": True, "rcexpandparam": False}
ARGV_OPTIONS = ("rcquotes", "shwordsplit", "rcexpandparam")
USER_FUNC_RE = re.compile(r"^(?:function\s+)?([^\s(){};|&<>'\"$`]+)\s*(?:\(\))?\s*\{")
FUNC_ANY_RE = re.compile(r"^\s*(?:function\s+([^\s(){};|&<>'\"$`]+)\s*(?:\(\))?\s*\{|([^\s(){};|&<>'\"$`]+)\s*\(\)\s*\{)")


class Variant(object):
    def __init__(self):
        self.aliases = {}
        self.global_aliases = set()
        self.suffix_aliases = set()
        self.user_functions = set()
        self.delegated = set()
        self.options = {}
        self.path = None
        self.notes = []
        self.func_offsets = {}
        self.text = ""
        self.weight = 1
        self.extra_paths = []

    def key(self):
        d = {"a": sorted(self.aliases.items()), "g": sorted(self.global_aliases), "s": sorted(self.suffix_aliases),
             "f": sorted(self.user_functions), "d": sorted(self.delegated), "o": sorted(self.options.items())}
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()


def _option_name(o):
    o = o.lower().replace("_", "")
    if o.startswith("no") and o[2:] in DEFAULT_OPTIONS and o not in DEFAULT_OPTIONS:
        return o[2:], False
    return o, True


def split_line(line):
    """Literal words of one simple shell line (quote removal only)."""
    from .parse import Parser
    from .scanctx import LexCtx
    p = Parser(line, LexCtx())
    out = []
    while True:
        p.skip_blanks()
        if p.pos >= len(p.buf) or p.at() in ";\n&|":
            break
        w = p.read_word()
        if w is None:
            break
        vals = []
        for part in w.parts:
            if part[0] == "lit":
                vals.append(part[1])
            else:
                vals = None
                break
        out.append("".join(vals) if vals is not None else None)
    return out


def parse_snapshot(text):
    v = Variant()
    v.text = text
    lines = text.split("\n")
    opt_i = alias_i = None
    for i, line in enumerate(lines):
        if line == "# Shell Options":
            opt_i = i
        elif line == "# Aliases":
            alias_i = i
    claude_i = None
    path_i = None
    if alias_i is not None:
        for i in range(alias_i + 1, len(lines)):
            if claude_i is None and lines[i].startswith(CLAUDE_MARKERS):
                claude_i = i
            if lines[i].startswith("export PATH="):
                path_i = i
    if opt_i is None or alias_i is None:
        v.notes.append("snapshot-markers-missing")
    if opt_i is None and alias_i is None and claude_i is None:
        # M0d-1b: deny messages say "snapshot format not recognized" when this note is present
        v.notes.append("snapshot-format-unrecognized")
    # (1) user functions: column-0 names only (typeset -f output); bodies are never lexed
    head_end = opt_i if opt_i is not None else (alias_i if alias_i is not None else len(lines))
    offset = 0
    for i, line in enumerate(lines[:head_end]):
        m = USER_FUNC_RE.match(line)  # anchored at column 0: nested (indented) definitions are not names
        if m:
            name = m.group(1)
            if name not in ("if", "while", "for", "case", "{"):
                v.user_functions.add(name)
                v.func_offsets[name] = offset
        offset += len(line) + 1
    # (2) options
    if opt_i is not None:
        end = alias_i if alias_i is not None and alias_i > opt_i else len(lines)
        for line in lines[opt_i + 1:end]:
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("setopt", "unsetopt"):
                for o in parts[1:]:
                    name, on = _option_name(o)
                    v.options[name] = on if parts[0] == "setopt" else not on
    # (3) aliases (a function defined in this region is a user function)
    if alias_i is not None:
        end = claude_i if claude_i is not None else (path_i if path_i is not None else len(lines))
        for line in lines[alias_i + 1:end]:
            fm = FUNC_ANY_RE.match(line)
            if fm:
                v.user_functions.add(fm.group(1) or fm.group(2))
            if not line.startswith("alias "):
                continue
            words = split_line(line)
            kind = None
            i = 1
            while i < len(words) and words[i] is not None and words[i].startswith("-") and words[i] != "--":
                if words[i] == "-g":
                    kind = "g"
                elif words[i] == "-s":
                    kind = "s"
                i += 1
            if i < len(words) and words[i] == "--":
                i += 1
            for w in words[i:]:
                if w is None or "=" not in w:
                    continue
                name, value = w.split("=", 1)
                v.aliases[name] = value
                if kind == "g":
                    v.global_aliases.add(name)
                elif kind == "s":
                    v.suffix_aliases.add(name)
    # (4) Claude Code's sections: unalias lines and the delegating shadow functions (by position)
    if claude_i is not None:
        end = path_i if path_i is not None and path_i > claude_i else len(lines)
        for line in lines[claude_i:end]:
            s = line.strip()
            if s.startswith("unalias "):
                for w in split_line(s)[1:]:
                    if w and not w.startswith("-"):
                        v.aliases.pop(w, None)
            m = FUNC_ANY_RE.match(line)
            if m:
                name = m.group(1) or m.group(2)
                if name in DELEGATED_NAMES:
                    v.delegated.add(name)
                else:
                    v.user_functions.add(name)
    else:
        # no Claude section: every function defined after the aliases is the user's (closed side);
        # without any marker, every definition in the file is (indented ones included)
        v.notes.append("claude-shadow-section-missing")
        start = alias_i + 1 if alias_i is not None else 0
        for line in lines[start:]:
            fm = FUNC_ANY_RE.match(line)
            if fm:
                name = fm.group(1) or fm.group(2)
                if name not in ("if", "while", "for", "case", "{"):
                    v.user_functions.add(name)
    # (5) PATH
    if path_i is not None:
        w = split_line(lines[path_i][len("export "):])
        if w and w[0] and w[0].startswith("PATH="):
            v.path = w[0][5:]
    # Bash tool postlude
    for k, val in BASH_TOOL_POSTLUDE["options"].items():
        v.options[k] = val
    for n in BASH_TOOL_POSTLUDE["unalias"]:
        v.aliases.pop(n, None)
    for n in BASH_TOOL_POSTLUDE["unfunction"]:
        v.user_functions.discard(n)
        v.delegated.discard(n)
    return v


class Snapshot(object):
    """The merged view of every recent snapshot variant."""

    def __init__(self, variants, files, notes):
        self.variants = variants
        self.files = files
        self.notes = list(notes)
        self.partial = any(n.startswith(("snapshot-truncated", "snapshot-unreadable")) for n in self.notes)
        n = len(variants)
        names = set()
        for v in variants:
            names |= set(v.aliases)
        self.alternatives = {}
        self.plain = {}
        for name in names:
            vals = [v.aliases.get(name) for v in variants]
            distinct = []
            for x in vals:
                if x is not None and x not in distinct:
                    distinct.append(x)
            missing = any(x is None for x in vals) or self.partial
            if len(distinct) == 1 and not missing:
                self.plain[name] = distinct[0]
            else:
                self.alternatives[name] = distinct + ([NOT_ALIAS] if missing else [])
        self.counts = {name: {} for name in names}
        for v in variants:
            for name in names:
                key = v.aliases.get(name)
                self.counts[name][key] = self.counts[name].get(key, 0) + v.weight
        self.total = sum(v.weight for v in variants)
        self.global_aliases = set().union(*[v.global_aliases for v in variants]) if variants else set()
        self.suffix_aliases = set().union(*[v.suffix_aliases for v in variants]) if variants else set()
        self.user_functions = set().union(*[v.user_functions for v in variants]) if variants else set()
        self.delegated = set.intersection(*[set(v.delegated) for v in variants]) if variants else set()
        self.options = dict(DEFAULT_OPTIONS)
        self.option_conflicts = set()
        for k in set().union(*[set(v.options) for v in variants]) if variants else ():
            vals = {v.options.get(k, DEFAULT_OPTIONS.get(k, False)) for v in variants}
            self.options[k] = True in vals
            if len(vals) > 1:
                self.option_conflicts.add(k)
        for k in ARGV_OPTIONS:
            if k in self.option_conflicts:
                self.options[k] = "both"
        self.paths = [v.path for v in variants if v.path]
        for v in variants:
            for nt in v.notes:
                if nt not in self.notes:
                    self.notes.append(nt)

    def source(self, name, value):
        c = self.counts.get(name, {})
        return {"name": name, "value": value, "in": c.get(value, 0), "of": self.total}

    def function_text(self, name, limit=65536):
        for v in self.variants:
            off = v.func_offsets.get(name)
            if off is not None:
                return v.text[off:off + limit]
        return None


def snapshot_dir(env):
    cfg = env.get("CLAUDE_CONFIG_DIR") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude")
    return os.path.join(cfg, "shell-snapshots")


def load(env, now=None):
    """(Snapshot or None, notes)."""
    now = time.time() if now is None else now
    d = snapshot_dir(env)
    notes = []
    try:
        names = [n for n in os.listdir(d) if NAME_RE.match(n)]
    except OSError:
        return None, ["snapshot-dir-missing"]
    entries = []
    for n in names:
        p = os.path.join(d, n)
        try:
            st = os.stat(p)
        except OSError:
            notes.append("snapshot-unreadable:%s" % n)
            continue
        if now - st.st_mtime > MAX_AGE:
            continue
        entries.append((st.st_mtime, n, st.st_size, p))
    entries.sort(reverse=True)
    if len(entries) > MAX_FILES:
        notes.append("snapshot-truncated")
        entries = entries[:MAX_FILES]
    by_key = {}
    seen_files = {}
    for mtime, n, size, p in entries:
        fkey = (n, size, mtime)
        if fkey in seen_files:
            continue
        if size > MAX_SIZE:
            notes.append("snapshot-unreadable:%s" % n)
            continue
        try:
            with open(p, "rb") as f:
                text = f.read(MAX_SIZE + 1).decode("utf-8", "replace")
            v = parse_snapshot(text)
        except Exception:  # noqa: BLE001 — a broken file is one unreadable variant
            notes.append("snapshot-unreadable:%s" % n)
            continue
        seen_files[fkey] = True
        k = v.key()
        if k in by_key:
            by_key[k].weight += 1
            if v.path and v.path not in by_key[k].extra_paths:
                by_key[k].extra_paths.append(v.path)
        else:
            by_key[k] = v
    if not by_key:
        return None, notes + ["snapshot-none"]
    if len(by_key) > MAX_DISTINCT:
        return None, notes + ["snapshot-too-many-variants"]
    variants = list(by_key.values())
    snap = Snapshot(variants, [e[3] for e in entries], notes)
    for v in variants:
        snap.paths.extend(p for p in v.extra_paths if p not in snap.paths)
    return snap, snap.notes
