"""sed: an allowlist of shapes (fix-0025-plan §1, pilot-2 P11). `classify(words)` -> ("read" | "edit" | "other",
details) for the Words after the program. A shape is accepted only when GNU and BSD sed read it the same way;
everything else is "other" (the judge refuses it in a Studio repository).

- read: `sed [-nEru…] SCRIPT [FILE…]` with no in-place word — it prints, the files are only read;
- edit: `sed -i '' SCRIPT FILE…` or `sed -i.bak SCRIPT FILE…`, no -n — the files (and the backups) are written;
- the script: one line of `p = d q n` and `s/re/rep/[gpI0-9]` with line, `$` and `/re/[I]` addresses, ranges,
  one `!` and `{…;}` blocks; no `w r e` or any other command, no `[`, and at most 3 `&`/`\\1`–`\\9` in replacements
  (no hold space, so a line cannot keep growing)."""

import re

NAMES = ("sed", "gsed")  # cmd.prog_key (NFC + casefold of the basename): SED, /usr/bin/Sed, … on APFS
SCRIPT_MAX = 200
GROWTH_MAX = 3

# an escape is `\` and any character; `[` (bracket expressions differ between GNU and BSD) is never accepted
_BODY = r"(?:[^\\/\[\n]|\\[^\[\n])*"
_NUM = r"0*[1-9][0-9]*"  # 01 is line 1; 0 and 00 are not lines (GNU's 0,/re/ is out)
_RE = r"/" + _BODY + r"/I?"
_ONE = r"(?:" + _NUM + r"|\$|" + _RE + r")"
# N,M  N,$  N,/re/  /re/,/re/  /re/,$  /re/,N — and a single address
_TWO = r"(?:(?:" + _NUM + r"|" + _RE + r")(?:," + _ONE + r")?|\$)"
_S = r"s/" + _BODY + r"/" + _BODY + r"/[gpI0-9]*"
# `=` and `q` take one address (BSD refuses a range); q takes no exit code
_CMD = r"(?:(?:" + _TWO + r"!?)?(?:[pdn]|" + _S + r")|(?:" + _ONE + r"!?)?[=q])"


def _block(inner):
    # every item inside ends with `;` before `}` (BSD refuses `{p}` and `{p;q}`)
    return r"(?:(?:" + _TWO + r"!?)?\{(?:" + inner + r";)+\})"


_ITEM1 = r"(?:" + _CMD + r"|" + _block(_CMD) + r")"
_ITEM = r"(?:" + _CMD + r"|" + _block(_ITEM1) + r")"  # blocks nest two deep
SCRIPT_RE = re.compile(_ITEM + r"(?:;" + _ITEM + r")*;?")
# left to right over a script that matched: s commands and regex addresses as units, anything else one by one
_TOKENS = re.compile(r"s/(" + _BODY + r")/(" + _BODY + r")/[gpI0-9]*|/" + _BODY + r"/|.")
_REP = re.compile(r"\\.|&")
_OPTS = re.compile(r"-[nEru]+")
# an empty word only with a quoted part and nothing unquoted ('', "", "$X", $'', ''''): the shell drops an unquoted
# expansion that is empty (`X=; sed -i $X p '1w F' f` makes BSD read `p` as the suffix and `1w F` as the script)
EMPTY_RAW = re.compile(r"""(?:'[^']*'|"(?:[^"\\]|\\.)*"|\$'(?:[^'\\]|\\.)*')+""")


def script_problem(text):
    """None when the script is in the grammar above, else a short reason."""
    if len(text) > SCRIPT_MAX:
        return "a script longer than %d characters" % SCRIPT_MAX
    if "\n" in text or "\r" in text:
        return "a script of more than one line"
    if not SCRIPT_RE.fullmatch(text):
        return "a command or a form outside the plain p = d q n and s/// subset"
    growth = 0
    for m in _TOKENS.finditer(text):
        rep = m.group(2)
        if rep is None:
            continue
        for t in _REP.findall(rep):
            if t == "\\0":
                return "\\0 in a replacement (GNU reads the whole match, BSD a literal 0)"
            if t == "&" or re.fullmatch(r"\\[1-9]", t):
                growth += 1
    if growth > GROWTH_MAX:
        return "more than %d & or \\1-\\9 in the replacements" % GROWTH_MAX
    return None


def _glob_problem(w):
    v = w.value
    if "(" in v:
        return "a glob with a qualifier"
    cut = min([i for i, ch in enumerate(v) if ch in "*?["] or [len(v)])
    prefix = (w.glob_base or "") or v[:cut]
    if not prefix or prefix.startswith("-"):
        return "a glob that may expand to an option (%s)" % v
    return None


def classify(words, exec_by=None):
    """(shape, details). exec_by: None, "find" (a find -exec template: a bare `{}` operand is the found path) or
    "xargs" (input the guard cannot see: always other). details: {"files", "suffix", "script"} for read and edit, the
    reason for other."""
    if exec_by == "xargs":
        return "other", "sed fed by xargs or parallel"
    if any(w.value == "" and not EMPTY_RAW.fullmatch(w.raw or "") for w in words):
        return "other", "an empty word from an expansion (the shell may drop it)"
    if len(words) == 1 and words[0].value in ("--version", "--help"):
        return "read", {"files": [], "suffix": None, "script": None}
    i, suffix, n = 0, None, False
    while i < len(words):
        v = words[i].value
        if v is None:
            return "other", "an option the guard cannot read"
        if not v.startswith("-"):
            break
        if v == "-i" and suffix is None and i + 1 < len(words) and words[i + 1].value == "":
            suffix, i = "", i + 2
            continue
        if v == "-i.bak" and suffix is None:
            suffix, i = ".bak", i + 1
            continue
        if _OPTS.fullmatch(v):
            n = n or "n" in v
            i += 1
            continue
        return "other", "the option %s" % v
    if i >= len(words):
        return "other", "no script"
    script, files = words[i], words[i + 1:]
    if script.value is None:
        return "other", "a script the guard cannot read"
    if script.glob:
        return "other", "an unquoted script"
    if exec_by == "find" and "{}" in script.value:
        return "other", "{} in the script"
    for w in files:
        if w.value is None:
            if exec_by == "find" and list(w.dyn) == ["find-path"]:
                continue  # the bare {} operand of find -exec
            return "other", "a file name the guard cannot read"
        if w.value.startswith("-"):
            return "other", "an option after the script (%s)" % w.value
        if exec_by == "find" and "{}" in w.value:
            return "other", "{} inside a word"
        if w.glob:
            if suffix is not None:
                return "other", "a glob in an edit's file (%s)" % w.value  # judge_glob checks one folder only
            why = _glob_problem(w)
            if why:
                return "other", why
    why = script_problem(script.value)
    if why:
        return "other", why
    details = {"files": files, "suffix": suffix, "script": script}
    if suffix is None:
        return "read", details
    if n:
        return "other", "-n with an in-place edit"
    if exec_by == "find":
        return "other", "an in-place edit of the files find gives"
    return "edit", details


def targets(details):
    """(Word, value) pairs an edit writes: every file, its backup, and the script word (GNU reads `-i ''` as an empty
    script and then edits the script word as a file)."""
    out = []
    suffix = details["suffix"] or ""
    for w in details["files"]:
        out.append((w, w.value))
        if suffix:
            out.append((w, w.value + suffix))
    s = details["script"]
    if s is not None:
        out.append((s, s.value))
    return out


def pieces(words):
    """Path candidates in a sed argv that is not checked (outside a Studio repository): every literal word split on
    whitespace and `;`; a piece holding `/`, the piece after a leading address and one w/W/r/R letter, and every
    `[wWrR] name` inside a piece (`s/a/b/w/abs`, `/a/w/abs`, `1{w/abs`). No `~` expansion: sed does not do it."""
    out = []
    for w in words:
        if w.value is None:
            continue
        for piece in re.split(r"[\s;]+", w.value):
            if not piece:
                continue
            if "/" in piece:
                out.append(piece)
            m = re.match(r"[0-9$,!]*[wWrR]", piece)
            if m and piece[m.end():]:
                out.append(piece[m.end():])
            for g in re.finditer(r"(?=[wWrR][ \t]*(\S+))", piece):
                out.append(g.group(1))
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq
