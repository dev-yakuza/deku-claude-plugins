"""The protected-path table (m0d1b-plan §5) and path matching. Data, not decisions: judge.py decides.

Patterns are relative to a repository root; `<sr>` is the repository's studio_root; `**` matches zero
or more directories. Matching uses comparison keys (NFC, case-folded on case-insensitive volumes).
"""

import fnmatch
import os
import re
import unicodedata

# id, patterns, class, who may write (for messages)
TABLE = [
    ("P-STATE", ("<sr>/**/videos/*/work/state.json", "<sr>/**/videos/*/work/approvals.jsonl",
                 "<sr>/**/videos/*/work/.state.lock", "<sr>/**/videos/*/work/**/shown.json",
                 "<sr>/**/videos/*/work/**/verify.json", "<sr>/**/videos/*/work/**/verify.md",
                 "<sr>/**/videos/*/work/**/checks/**",
                 "<sr>/**/videos/*/work/assets.json", "<sr>/**/videos/*/work/commit-ok.json",
                 "<sr>/**/videos/*/work/source/**",
                 "<sr>/**/videos/*/work/**/pronounce-approved.json", "<sr>/**/videos/*/work/**/exemptions.json",
                 "<sr>/**/videos/*/work/**/gate2-lines.txt", "<sr>/**/videos/*/work/**/gate4b-lines.*.txt",
                 "<sr>/**/cast/*/status.json", "<sr>/**/cast/*/approvals.json",
                 "<sr>/**/cast/*/shown.json", ".claude/studio/local/commit-ok.json",
                 ".claude/studio/local/pending-approval.json", ".claude/studio/local/guard-ran.json",
                 ".claude/studio/local/guard-ran.lock", ".claude/studio/local/consumed-answers.jsonl",
                 ".claude/studio/local/consumed-answers.lock", ".claude/studio/local/last-checked.json",
                 ".claude/studio/local/commit-summary-*.txt"),
     "state", "state.py, the Studio check scripts (run_s2v.py, …), check_commit.py and the guard"),
    ("P-CRIT", (".claude/studio/charter.md", ".claude/studio/formats/**", ".claude/studio/platforms/**"),
     "criteria", "the person"),
    ("P-PERS", (".claude/agents/std-fact-checker.md", ".claude/agents/std-source-analyst.md"), "persona", "the person"),
    ("P-WIRE", (".claude/studio/scripts/**", ".claude/studio/installed.json"), "wiring",
     "the person (/std update; installed.json: setup.py)"),
    ("P-CONF", (".claude/studio/config.json",), "config", "the person (protected keys)"),
    ("P-CONF-L", (".claude/studio/local/config.internal.json", ".claude/studio/local/machine.json"), "config",
     "the person (/std config; machine.json: /std config s2v.path)"),
    ("P-CHAR", ("<sr>/**/cast/*/character/**",), "character", "s2v and lock.py actor-op (write character.yaml.draft)"),
    ("P-CRED", ("<sr>/**/CREDITS.yaml",), "credits", "state.py credit (write CREDITS.draft.yaml)"),
    ("P-VOICE", ("<sr>/**/voices/**",), "voices", "s2v"),
    ("P-AUDIO", ("<sr>/**/videos/*/audio/**",), "audio", "s2v"),
    ("P-LOCAL", ("<sr>/local/**", ".claude/studio/local/consent/**"), "local", "the person (deletion)"),
]
BY_ID = {t[0]: t for t in TABLE}
# entries s2v owns (its arguments under these are not agent writes)
S2V_OWNED = {"P-VOICE", "P-AUDIO", "P-CHAR"}
DRAFT_OK = {"P-CHAR": "character.yaml.draft"}
# names that make a protected path when they end a dynamic word's literal tail
TAIL_NAMES = {"local", "character", "voices", "audio", "consent", "state.json", "approvals.jsonl", "shown.json",
              "verify.json", "verify.md", "CREDITS.yaml", "status.json", "approvals.json", "charter.md", "config.json",
              "commit-ok.json", "pending-approval.json", "guard-ran.json", "last-checked.json", "assets.json",
              "pronounce-approved.json", "installed.json", "exemptions.json", "gate2-lines.txt"}

READ_ALLOW = {"cat", "head", "tail", "less", "more", "ls", "stat", "file", "du", "wc", "shasum", "sha256sum",
              "sha1sum", "md5", "md5sum", "cmp", "diff", "grep", "egrep", "fgrep", "rg", "ag", "jq", "ffprobe",
              "afplay", "open", "realpath", "readlink", "basename", "dirname", "test", "[", "tree", "find", "bfs",
              "echo", "printf", "true", ":", "pwd", "cd", "pushd", "popd", "xxd", "hexdump", "od", "strings",
              "sort", "uniq", "cut", "column", "nl", "bat", "exiftool", "mdls"}
# READ_ALLOW programs that can write a file or run a program (G1 §1.11): judged by their options
READ_WRITERS = {"sort", "uniq", "xxd", "tree", "exiftool", "file", "ffprobe", "rg", "open"}
GIT_READ = {"diff", "status", "log", "show", "ls-files", "rev-parse", "blame", "grep", "branch", "describe",
            "ls-tree", "cat-file", "shortlog", "reflog", "remote", "config", "fetch", "tag", "stash"}
GIT_PATHSPEC_WRITE = {"add", "rm", "mv", "restore", "checkout"}
FIND_WRITE = ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls")
DELETE_PROGS = {"rm", "rmdir", "unlink", "trash", "shred", "srm", "rimraf", "del", "trash-put", "trash-rm",
                "del-cli", "rimraf-cli"}


# programs that can put a link, a moved folder or a copied tree at a path (dest of ln/mv/cp/…)
CREATORS = {"ln", "mv", "cp", "gcp", "install", "rsync", "ditto"}
LOCAL_ANCHORS = ((".claude", "studio", "local"), ("<sr>", "local"))


def local_anchor(parts, sr, fold):
    """`parts` is a machine-local folder (`.claude/studio/local`, `<sr>/local`) or a folder above one."""
    if not parts:
        return False
    for anc in LOCAL_ANCHORS:
        full = []
        for x in anc:
            full += [y for y in sr.strip("/").split("/") if y] if x == "<sr>" else [x]
        if len(parts) <= len(full) and all((a.casefold() == b.casefold()) if fold else a == b
                                           for a, b in zip(parts, full)):
            return True
    return False


def may_hold_protected(parts, sr, fold):
    """A folder at `parts` could hold a protected path (any table entry, local/ included)."""
    return bool(parts) and any(_may_contain(parts, _expand(p, sr), fold) for _t, pats, _c, _w in TABLE for p in pats)


def norm(p):
    return unicodedata.normalize("NFC", p)


def _expand(pattern, sr):
    return pattern.replace("<sr>", sr.strip("/") or "studio").split("/")


def _match(parts, pat, fold):
    """Full match of path parts against pattern parts (`**` = zero or more parts)."""
    def eq(a, b):
        if fold:
            a, b = a.casefold(), b.casefold()
        return fnmatch.fnmatchcase(a, b)

    memo = {}

    def rec(i, j):
        k = (i, j)
        if k in memo:
            return memo[k]
        if j == len(pat):
            r = i == len(parts)
        elif pat[j] == "**":
            r = rec(i, j + 1) or (i < len(parts) and rec(i + 1, j))
        else:
            r = i < len(parts) and eq(parts[i], pat[j]) and rec(i + 1, j + 1)
        memo[k] = r
        return r
    return rec(0, 0)


def _may_contain(parts, pat, fold):
    """Whether some path under directory `parts` (or parts itself) can match the pattern."""
    def eq(a, b):
        if fold:
            a, b = a.casefold(), b.casefold()
        return fnmatch.fnmatchcase(a, b)

    memo = {}

    def rec(i, j):
        k = (i, j)
        if k in memo:
            return memo[k]
        if i == len(parts):
            r = True  # the rest of the pattern can match below the directory
        elif j == len(pat):
            r = False
        elif pat[j] == "**":
            r = rec(i, j + 1) or rec(i + 1, j)
        else:
            r = eq(parts[i], pat[j]) and rec(i + 1, j + 1)
        memo[k] = r
        return r
    return rec(0, 0)


def rel_parts(abs_path, root, fold):
    """Parts of abs_path relative to root, or None when outside."""
    a, r = norm(abs_path), norm(root.rstrip("/"))
    if fold:
        a2, r2 = a.casefold(), r.casefold()
    else:
        a2, r2 = a, r
    if a2 == r2:
        return []
    if not a2.startswith(r2 + "/"):
        return None
    return [x for x in a[len(r) + 1:].split("/") if x]


def classify(parts, sr, fold, include_local=False):
    """The first table entry a repository-relative path matches, or None."""
    for tid, pats, _cls, _who in TABLE:
        if tid == "P-LOCAL" and not include_local:
            continue
        for p in pats:
            if _match(parts, _expand(p, sr), fold):
                if tid in DRAFT_OK and parts and parts[-1] == DRAFT_OK[tid]:
                    break
                return tid
    return None


def delete_hits(parts, sr, fold, is_dir=True):
    """Entry id when deleting/moving `parts` would remove protected data (a directory: anything that
    may be below it; a file or a missing path: the path itself)."""
    roots = [_expand(sr, sr), [".claude", "studio"]]
    for root in roots:
        if len(parts) <= len(root) and _may_contain(parts, root, fold) and \
                all((a.casefold() == b.casefold()) if fold else a == b for a, b in zip(parts, root)):
            return "P-ANC"
    order = [t for t in TABLE if t[0] == "P-LOCAL"] + [t for t in TABLE if t[0] != "P-LOCAL"]
    for tid, pats, _cls, _who in order:
        for p in pats:
            pat = _expand(p, sr)
            if _match(parts, pat, fold) or (is_dir and _may_contain(parts, pat, fold)):
                return tid
    return None


def tail_hits(skeleton):
    """A dynamic word whose literal tail names a protected thing (`\\0/local`, `\\0/character/x`)."""
    tail = skeleton.split("\0")[-1]
    segs = [s for s in tail.split("/") if s]
    return any(s in TAIL_NAMES for s in segs)


def protected_names():
    out = set()
    for _tid, pats, _c, _w in TABLE:
        for p in pats:
            last = p.split("/")[-1]
            if "*" not in last and last not in ("**",):
                out.add(last)
    return sorted(out)


def out_of_repo(user_dir, state_dirs):
    """(path, kind) for files outside repositories: kind "file", "dir" or "prefix"."""
    items = [(os.path.join(user_dir, "studio-sandbox.json"), "file"), (os.path.join(user_dir, "studio-backup"), "dir")]
    for s in state_dirs:
        items.append((os.path.join(s, "heavy.lock.d"), "prefix"))
        items.append((os.path.join(s, "resident.json"), "file"))
    return items


class Seg(str):
    """A path segment that knows which of its characters zsh may read as a pattern (unquoted; review 4 conf M-2). A
    plain str: every glob character may be one."""

    def __new__(cls, text, wild):
        o = str.__new__(cls, text)
        o.wild = frozenset(wild)
        return o


NUMGLOB_RE = re.compile(r"<([0-9]*)-([0-9]*)>")  # zsh's numeric glob (lex.NUMGLOB_RE)


def _w(wild, i):
    return wild is None or i in wild


def bracket_end(g, i, wild=None):
    """Index of the `]` that closes the bracket expression opened by the unquoted `[` at `i`, or None when it is not
    closed (zsh: a bad pattern — an error, or with NO_BAD_PATTERN the word is literal). zsh 5.9 (pattern.c): an
    unquoted `!` or `^` after `[` negates; an unquoted `]` next is a member when another unquoted `]` follows anywhere
    in the word; `[:name:]` is a class; inside, `~ ^ # ( | /` are members, not operators (review 7 B1, M1, M2). The
    word is not split at `/` first: a bracket may hold one (`[s/]tudio` matches `studio`)."""
    n = len(g)
    j = i + 1
    if j < n and g[j] in "!^" and _w(wild, j):
        j += 1
    if j < n and g[j] == "]" and _w(wild, j) and any(g[k] == "]" and _w(wild, k) for k in range(j + 1, n)):
        j += 1
    while j < n:
        ch = g[j]
        if ch == "]" and _w(wild, j):
            return j
        m = NUMGLOB_RE.match(g, j) if ch == "<" and _w(wild, j) else None
        if m is not None and not any(g[k] == "]" and _w(wild, k) for k in range(j, m.end())):
            j = m.end() - 1  # zsh reads `<N-M>` in a bracket as letters, its `-` no range; the `>` may start one
            continue
        if ch == "[" and _w(wild, j) and j + 1 < n and g[j + 1] == ":":
            c = g.find(":", j + 2)
            if c >= 0 and c + 1 < n and g[c + 1] == "]" and _w(wild, c + 1):
                j = c + 2
                continue
        if j + 2 < n and g[j + 1] == "-" and _w(wild, j + 1) and not (g[j + 2] == "]" and _w(wild, j + 2)):
            j += 3
            continue
        j += 1
    return None


def split_pattern(value, wild=None):
    """`value` split at `/` as zsh's filename generation splits a pattern: not inside a bracket expression. Returns
    [(start, end)] spans (empty and `.` parts kept; the caller drops them)."""
    out, s, i, n = [], 0, 0, len(value)
    while i < n:
        ch = value[i]
        if ch == "[" and _w(wild, i):
            e = bracket_end(value, i, wild)
            if e is not None:
                i = e + 1
                continue
        if ch == "/":
            out.append((s, i))
            s = i + 1
        i += 1
    out.append((s, n))
    return out


def pattern_segments(value, wild=None):
    """Segments of a pattern (`split_pattern`), each a Seg when the quoting is known; no empty or `.` segments."""
    out = []
    for s, e in split_pattern(value, wild):
        part = value[s:e]
        if part in ("", "."):
            continue
        out.append(part if wild is None else Seg(part, {i - s for i in wild if s <= i < e}))
    return out


def _excl_at(g, wild):
    """Index of an exclusion `~` in a segment under EXTENDED_GLOB (`a~b`), or None: a `~` that ends the segment (before
    `/` or the end of the word) is a letter (checked in zsh 5.9: `a.txt~`, `*~`, `d~/b`); a `~` inside a bracket
    expression is a member (`[s~]tudio` matches `studio`; review 7 B1)."""
    i, n = 0, len(g)
    while i < n:
        ch = g[i]
        if ch == "[" and _w(wild, i):
            e = bracket_end(g, i, wild)
            if e is not None:
                i = e + 1
                continue
        if ch == "~" and _w(wild, i) and i + 1 < n:
            return i
        i += 1
    return None


def _double_tilde(g, k):
    wild = getattr(g, "wild", None)
    return k + 1 < len(g) and g[k + 1] == "~" and _w(wild, k + 1)


def ext_cut(segs, extglob):
    """review 6 conf m-1: segments of a pattern up to an exclusion `~` (`x~*/y` excludes paths; what it matches is a
    subset of what `x` matches)."""
    if not extglob:
        return list(segs)
    out = []
    for s in segs:
        k = _excl_at(s, getattr(s, "wild", None))
        if k is None:
            out.append(s)
            continue
        if _double_tilde(s, k):
            out.append(s)  # `x~~y`: zsh does not read it as `x` minus `~y` (checked in zsh 5.9): the matcher fails closed
            continue
        cut = s[:k]
        if cut:
            out.append(Seg(cut, {i for i in s.wild if i < k}) if isinstance(s, Seg) else cut)
        break
    return out


# zsh 5.9 `[:name:]` classes; None: the guard cannot tell (they depend on $IFS / $WORDCHARS)
_CLASSES = {
    "alpha": str.isalpha, "alnum": str.isalnum, "ascii": lambda c: ord(c) < 128,
    "blank": lambda c: c in " \t", "cntrl": lambda c: ord(c) < 32 or ord(c) == 127,
    "digit": lambda c: c in "0123456789", "graph": lambda c: c.isprintable() and not c.isspace(),
    "lower": str.islower, "print": str.isprintable,
    "punct": lambda c: c.isprintable() and not c.isspace() and not c.isalnum(),
    "space": str.isspace, "upper": str.isupper, "xdigit": lambda c: c in "0123456789abcdefABCDEF",
    "IDENT": lambda c: c.isalnum() or c == "_", "IFS": None, "IFSSPACE": None, "WORD": None,
    "INCOMPLETE": lambda c: False, "INVALID": lambda c: False,
}


def _bracket_set(g, i, e, wild):
    """(negated, members) of the bracket expression g[i..e] (`e` from bracket_end). Members: ("c", ch),
    ("r", lo, hi), ("k", class name or None for an unknown name, which zsh ignores)."""
    n = e
    j = i + 1
    neg = False
    if j < n and g[j] in "!^" and _w(wild, j):
        neg, j = True, j + 1
    mem = []
    if j < n and g[j] == "]" and _w(wild, j) and any(g[k] == "]" and _w(wild, k) for k in range(j + 1, len(g))):
        mem.append(("c", "]"))
        j += 1
    while j < n:
        m = NUMGLOB_RE.match(g, j, n) if g[j] == "<" and _w(wild, j) else None
        if m is not None:
            # review 9: `<1-9>` in a bracket is letters (its `-` makes no range); its `>` may start a range (`<-3>-2`)
            mem.extend(("c", c) for c in m.group(0)[:-1])
            j = m.end() - 1
            if not (j + 2 < n and g[j + 1] == "-" and _w(wild, j + 1)):
                mem.append(("c", ">"))
                j += 1
            continue
        if g[j] == "[" and _w(wild, j) and j + 1 < n and g[j + 1] == ":":
            c = g.find(":", j + 2)
            if 0 <= c and c + 1 < n and g[c + 1] == "]" and _w(wild, c + 1):
                name = g[j + 2:c]
                mem.append(("k", name if name in _CLASSES else None))
                j = c + 2
                continue
        if j + 2 < n and g[j + 1] == "-" and _w(wild, j + 1):
            mem.append(("r", g[j], g[j + 2]))
            j += 3
            continue
        mem.append(("c", g[j]))
        j += 1
    return neg, mem


def _in_set(neg, mem, c, fold):
    """True / False / None (the guard cannot tell) for one character against a bracket set."""
    cs = {c, c.lower(), c.upper()} if fold else {c}
    res = False
    for m in mem:
        if m[0] == "c":
            if m[1] in cs or (fold and m[1].casefold() == c.casefold()):
                res = True
        elif m[0] == "r":
            if any(m[1] <= x <= m[2] for x in cs):
                res = True
        elif m[1] is not None:
            f = _CLASSES[m[1]]
            if f is None:
                res = None if res is False else res
            elif any(f(x) for x in cs):
                res = True
        if res is True:
            break
    if res is None:
        return None
    return (not res) if neg else res


def _seg_atoms(g, wild, extglob):
    """(atoms, negated) for one pattern segment read as zsh reads it, or None when the guard is unsure (groups, `|`,
    `<…>`, `^` or `#` where it cannot tell): the caller fails closed. Atoms: [kind, data, repeat] with kind "c" (a
    letter), "?", "*" or "s" (a bracket set); repeat "" / "*" (`#`) / "+" (`##`). An exclusion `~` keeps only its
    first part (a superset)."""
    if extglob:
        k = _excl_at(g, wild)
        if k is not None and _double_tilde(g, k):
            return None
        if k is not None:
            g = g[:k]
            if wild is not None:
                wild = {i for i in wild if i < k}
    neg = False
    start = 0
    if extglob and g.startswith("^") and _w(wild, 0) and len(g) > 1:
        neg, start = True, 1
    out = []
    i = start
    n = len(g)
    while i < n:
        ch = g[i]
        if not _w(wild, i):
            out.append(["c", ch, ""])
            i += 1
            continue
        if ch == "<":
            m = NUMGLOB_RE.match(g, i)
            if m is None or not all(_w(wild, k) for k in range(i, m.end())):
                return None
            lo, hi = m.group(1), m.group(2)
            out.append(["n", (int(lo) if lo else None, int(hi) if hi else None), ""])  # review 9 conf m-1
            i = m.end()
            continue
        if ch in "(|" or (extglob and ch == "^"):
            return None
        if ch == "*":
            out.append(["*", None, ""])
        elif ch == "?":
            out.append(["?", None, ""])
        elif ch == "[":
            e = bracket_end(g, i, wild)
            if e is None:
                out.append(["c", ch, ""])  # not closed: a bad pattern (an error), or literal under NO_BAD_PATTERN
                i += 1
                continue
            out.append(["s", _bracket_set(g, i, e, wild), ""])
            i = e + 1
            continue
        elif ch == "#" and extglob:
            if not out or out[-1][2] or out[-1][0] == "n":
                return None  # `#` first, a repeat of a repeat (`a###`) or of a numeric glob (`<->#`): unsure
            two = i + 1 < n and g[i + 1] == "#" and _w(wild, i + 1)
            out[-1][2] = "+" if two else "*"
            i += 2 if two else 1
            continue
        else:
            out.append(["c", ch, ""])
        i += 1
    return out, neg


def _atoms_match(atoms, name, fold, unsure):
    """Whether `name` matches the atoms; a character the guard cannot tell against a class counts as `unsure`."""
    n = len(name)
    memo = {}

    def one(a, c):
        k = a[0]
        if k == "?":
            return True
        if k == "c":
            return a[1] == c or (fold and a[1].casefold() == c.casefold())
        r = _in_set(a[1][0], a[1][1], c, fold)
        return unsure if r is None else r

    def rec(i, p):
        key = (i, p)
        if key in memo:
            return memo[key]
        if i == len(atoms):
            r = p == n
        else:
            a = atoms[i]
            if a[0] == "n":
                # `<lo-hi>`: one or more digits whose number is in the range (any split of a digit run: a superset)
                r = False
                q = p
                while not r and q < n and name[q] in "0123456789":
                    q += 1
                    v = int(name[p:q])
                    if (a[1][0] is None or v >= a[1][0]) and (a[1][1] is None or v <= a[1][1]):
                        r = rec(i + 1, q)
            elif a[0] == "*":
                r = any(rec(i + 1, q) for q in range(p, n + 1))
            elif a[2] == "":
                r = p < n and one(a, name[p]) and rec(i + 1, p + 1)
            else:
                r = a[2] == "*" and rec(i + 1, p)
                q = p
                while not r and q < n and one(a, name[q]):
                    q += 1
                    r = rec(i + 1, q)
        memo[key] = r
        return r
    return rec(0, 0)


def _seg_ok(g, p, fold, extglob):
    """One segment of a command's pattern (`g`, read as zsh reads it) against one table segment (`p`, fnmatch). A
    quoted character (Seg) is a letter. `[…]` and, under extendedglob, `^ ~ #` are matched as zsh 5.9 does (review 6
    conf m-1, review 7 B1/M2: `~ ^ #` inside a bracket are members); fail closed: groups, `|`, `<…>` and forms the
    guard is unsure of match every name."""
    wild = getattr(g, "wild", None)
    p_wild = any(ch in p for ch in "*?[")
    if any(ch in "(|" and _w(wild, i) for i, ch in enumerate(g)):
        return True
    special = "*?[<^~#" if extglob else "*?[<"
    if not any(ch in special and _w(wild, i) for i, ch in enumerate(g)):
        if p_wild:
            return fnmatch.fnmatchcase(g.casefold() if fold else g, p.casefold() if fold else p)
        return g.casefold() == p.casefold() if fold else g == p
    if p_wild:
        return True
    r = _seg_atoms(g, wild, extglob)
    if r is None:
        return True
    atoms, neg = r
    if neg:  # `^x`: any other name (GLOB_DOTS may be on: dot names too); a subset of `x` decides
        return not _atoms_match(atoms, p, fold, False)
    return _atoms_match(atoms, p, fold, True)


def glob_may_match(gparts, pat, fold, prefix=False, anchors=None, extglob=False):
    """Whether some path matches both `gparts` (a command's pattern, `**` = zero or more folders) and the table pattern
    `pat` (G1 §2, §1.7a). prefix=True: also when `gparts` runs out first (a folder that may hold a match).
    `anchors`: indexes of `gparts` of which at least one must meet a literal table segment (a table `**` may not stand
    for all of them)."""
    need = bool(anchors)
    n, m = len(gparts), len(pat)
    # review 10: computed bottom-up (a long path no longer runs out of recursion depth); dp[i][j][a] as before
    dp = [[[False, False] for _j in range(m + 1)] for _i in range(n + 1)]
    for j in range(m + 1):
        tail = prefix or all(x == "**" for x in pat[j:])
        for a in (0, 1):
            dp[n][j][a] = tail and (bool(a) or not need)
    for i in range(n - 1, -1, -1):
        g = gparts[i]
        for j in range(m, -1, -1):
            for a in (0, 1):
                if g == "**":
                    r = dp[i + 1][j][a] or (j < m and dp[i][j + 1][a])
                elif j == m:
                    r = False
                elif pat[j] == "**":
                    r = dp[i][j + 1][a] or dp[i + 1][j][a]
                else:
                    lit = not any(ch in pat[j] for ch in "*?[")
                    a2 = 1 if (a or (need and lit and i in anchors)) else 0
                    r = dp[i + 1][j + 1][a2] and _seg_ok(g, pat[j], fold, extglob)
                dp[i][j][a] = bool(r)
    return dp[0][0][0]


# names one of which a relative path under an unknown folder must hold (G1 §1.7a); the values need that parent
UNKNOWN_FOLDER_NAMES = {".claude", "studio", "local", "voices", "audio", "character", "work", "videos", "cast",
                        "source", "checks", "consent"} | TAIL_NAMES
NEEDS_PARENT = {"config.json": ("studio",), "status.json": ("cast", "*"), "source": ("work",)}


def unknown_folder_anchors(rel, sr, fold, extglob=False):
    """Indexes of `rel` that name a protected thing literally (with the parent some names need). `extglob`: `^ ~ #`
    are wildcards too (review 5)."""
    def eq(a, b):
        return a.casefold() == b.casefold() if fold else a == b
    names = set(UNKNOWN_FOLDER_NAMES) | {x for x in sr.strip("/").split("/") if x}
    out = set()
    for k, s in enumerate(rel):
        wild = getattr(s, "wild", None)
        if any(ch in ("*?[(|<^~#" if extglob else "*?[(|<") and (wild is None or i in wild) for i, ch in enumerate(s)):
            out.add(k)  # a wildcard may be any name (review 2, B-1): glob_may_match still needs a literal table name
            continue
        hit = next((n for n in names if eq(s, n)), None)
        if hit is None:
            continue
        par = NEEDS_PARENT.get(hit.casefold() if fold else hit)
        if par is not None:
            before = rel[max(0, k - len(par)):k]
            if len(before) < len(par) or not all(q == "*" or eq(b, q) for b, q in zip(before, par)):
                continue
        out.add(k)
    return out


def unknown_folder_hit(rel, sr, fold, op, include_local=False, skip=(), extglob=False):
    """G1 §1.7a: the table entry `**/<rel>` may hit when the folder is unknown (`rel` relative, `..` already handled),
    or None. op: write | delete-file | delete | write-dir."""
    anchors = unknown_folder_anchors(rel, sr, fold, extglob)
    if not anchors:
        return None
    g = ["**"] + list(rel)
    shifted = {k + 1 for k in anchors}
    prefix = op in ("delete", "write-dir")
    if op in ("delete", "write-dir"):
        # the path may be the studio root, .claude/studio, or a folder above either (a wildcard may be any name)
        for root in (_expand(sr, sr), [".claude", "studio"]):
            for s in range(len(root)):
                for e in range(s + 1, len(root) + 1):
                    if len(rel) == e - s and all(_seg_ok(a, b, fold, extglob) for a, b in zip(rel, root[s:e])):
                        return "P-ANC"
    order = [t for t in TABLE if t[0] == "P-LOCAL"] + [t for t in TABLE if t[0] != "P-LOCAL"]
    for tid, pats, _c, _w in order:
        if tid in skip or (tid == "P-LOCAL" and not (include_local or op.startswith("delete"))):
            continue
        for p in pats:
            if glob_may_match(g, _expand(p, sr), fold, prefix=prefix, anchors=shifted, extglob=extglob):
                return tid
    return None
