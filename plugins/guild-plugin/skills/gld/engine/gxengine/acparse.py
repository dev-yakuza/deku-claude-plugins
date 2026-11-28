"""The AC parser shared by `ac-format` and `ac-coverage` (design §3.1, §7.1, I6) — U15.

One parser reads the AC set from `docs/specs/<N>/analysis.md` and the AC references of
`test-cases.md` (one reference form, fixed in the tester work instruction). A token that
looks like an AC but cannot be parsed is a failure (fail-closed): the parser raises
`AcError`, it never skips. The 0.102.8 / 10 / 11 miss cases are fixed tests (scenario S13):

  * 0.102.8  — an AC section titled `## 인수 기준` was not read at all      → `AC_HEADING`
  * 0.102.10 — a case tagged `- E4 [AC #5] …` (bracketed tag) was not read   → case tags
  * 0.102.11 — a heading `(AC #1, #5)` named only AC #1                      → AC lists

`analysis.md` shape (the requirements-engineer role file prescribes it; `data/roles/`):

    # Analysis — #<N>
    type: feature            <- machine fields, before the first `##` heading
    size: small              <- small | medium | large
    risk: low                <- low | high
    split: none              <- none | proposed
    prerequisite: none       <- none | met | open
    safety_net: none         <- none | with-refactor | only — stage 3 only (E3)
    ## Acceptance criteria   <- `AC_HEADING` (English or Korean titles)
    - AC #1: …               <- consecutive ids 1..n, one top-level list item each
    ## Requirement map       <- table: | issue requirement | AC #… |
    ## Assumptions           <- optional, posted publicly by the engine
    ## 미룬 요구             <- stage 3 (E30), only when a replan deferred requirement rows:
    - <the requirement> (deferred R3)   <- one top-level item per deferred row, tag at its end

A deferred row has no AC. It may also stay in the requirement map with the same tag at the end
of its requirement cell and no AC; such a row is not part of `requirement_map`.

Ids are integers (`AC #3` → 3). Fenced code, HTML comments and `>` quote lines are
ignored; an unclosed fence or comment is an error (it would hide ACs).

test-cases.md references (what covers an AC; `parse_test_case_refs`):

  * a heading names ACs anywhere in it: `### Persistence (AC #3, #4)`, `## Cases — AC #2, #3`;
  * any other line (list item, continuation line, paragraph) names ACs only through a case
    tag — a bracket group that holds one AC list, alone or followed by a separator and a
    label: `(AC #2)`, `(AC #2, #5)`, `[AC #1, 엣지]` — standing at the END of the line
    (`- C3: opens the sheet. (AC #2)`) or at its START, after the list marker and an
    optional case id (`- E4 (AC #5) …`, 0.102.10); a list item may also be led by a bare
    AC list and a separator, like a heading (`- **AC #2**: …`, `1. AC #3 — …`);
  * a table row names ACs through a cell that starts with an AC list (`| C5 | AC #3 |`,
    `| AC #1 (saved on exit) | 1–8 |`, a label allowed as above) or a case tag at the start
    / end of a cell;
  * everything else is a prose mention and covers nothing (0.102.12, "AC #7 은 #1950 으로
    분리"; `(AC #1 의 정의)` is not a tag, nor is `(AC #2)` in the middle of a sentence).

Parentheses are the written form (P5: square brackets `[AC #2]` / `[must]` are undefined
references to markdown lint — remark-lint-no-undefined-references — and broke a
repository's lint). The old square-bracket tag `[AC #2]` and `【AC #5】` are still read
under the same position rule. Every AC-like token on every line is still parsed — an
unparseable one fails, wherever it stands (fail-closed).
"""

import os
import re
import stat

from . import codes

MAX_SPEC_BYTES = 2 * 1024 * 1024
MAX_AC_ID = 9999

MACHINE_FIELDS = ("type", "size", "risk", "split", "prerequisite")
STAGE3_MACHINE_FIELDS = MACHINE_FIELDS + ("safety_net",)
"""Stage 3 (E3). Earlier stages do not look at `safety_net` (E36) and read it as none."""
SPLIT_VALUES = ("none", "proposed")
PREREQUISITE_VALUES = ("none", "met", "open")

PLAN_REASON_TYPE = "type-not-feature"
PLAN_REASON_SPLIT = "split-proposed"
PLAN_REASON_PREREQUISITE = "prerequisite-open"
PLAN_REASON_RISK = "risk-high"


class AcError(Exception):
    """Unparseable AC-like token / malformed section. `.line` (1-based or None), `.text`."""

    def __init__(self, message, line=None, text=None):
        self.line = line
        self.text = text
        self.message = message
        super().__init__(f"line {line}: {message}" if line else message)


class SpecFileError(Exception):
    """A spec file exists but cannot be read safely (link, non-regular, too large, not UTF-8)."""


# --- reading a spec file safely -----------------------------------------------------

def read_spec(root, issue, name):
    """Text of `<root>/docs/specs/<issue>/<name>`; None when the file does not exist.

    Refuses a link anywhere on the path below `root`, a non-regular file, a file over
    MAX_SPEC_BYTES and non-UTF-8 content (raises SpecFileError). Never writes."""
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        raise SpecFileError(f"invalid issue number {issue!r}")
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", name or ""):
        raise SpecFileError(f"invalid spec file name {name!r}")
    cur = root
    for part in ("docs", "specs", str(issue), name):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return None
        except OSError as e:
            raise SpecFileError(f"{cur}: {e.strerror or e}") from e
        if stat.S_ISLNK(st.st_mode):
            raise SpecFileError(f"{os.path.relpath(cur, root)} is a symbolic link")
    if not stat.S_ISREG(st.st_mode):
        raise SpecFileError(f"{os.path.relpath(cur, root)} is not a regular file")
    if st.st_size > MAX_SPEC_BYTES:
        raise SpecFileError(f"{os.path.relpath(cur, root)} is larger than {MAX_SPEC_BYTES} bytes")
    try:
        fd = os.open(cur, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(MAX_SPEC_BYTES + 1)
    except OSError as e:
        raise SpecFileError(f"{os.path.relpath(cur, root)}: {e.strerror or e}") from e
    if len(data) > MAX_SPEC_BYTES:
        raise SpecFileError(f"{os.path.relpath(cur, root)} is larger than {MAX_SPEC_BYTES} bytes")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise SpecFileError(f"{os.path.relpath(cur, root)} is not valid UTF-8") from e


# --- text preparation ---------------------------------------------------------------

def _clean_lines(text):
    """[(lineno, line)] with fenced code, HTML comments and `>` quote lines blanked.

    Blank lines keep their line numbers. An unclosed fence or comment raises AcError:
    the rest of the document would silently vanish (fail-closed)."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    fence = None          # (marker char, length, opening lineno)
    in_comment = None     # opening lineno
    for no, line in enumerate(raw, 1):
        if fence:
            m = re.match(r"^[ ]{0,3}(`{3,}|~{3,})[ \t]*$", line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                fence = None
            out.append((no, ""))
            continue
        # HTML comments (possibly several per line, possibly spanning lines)
        pos, buf = 0, []
        while pos < len(line):
            if in_comment:
                end = line.find("-->", pos)
                if end < 0:
                    pos = len(line)
                else:
                    in_comment = None
                    pos = end + 3
                    buf.append(" ")
            else:
                start = line.find("<!--", pos)
                if start < 0:
                    buf.append(line[pos:])
                    pos = len(line)
                else:
                    buf.append(line[pos:start])
                    in_comment = no
                    pos = start + 4
        line = "".join(buf)
        m = re.match(r"^[ ]{0,3}(`{3,}|~{3,})", line)
        if m:
            fence = (m.group(1)[0], len(m.group(1)), no)
            out.append((no, ""))
            continue
        if re.match(r"^[ \t]*>", line):
            out.append((no, ""))
            continue
        out.append((no, line))
    if fence:
        raise AcError("code fence opened here is never closed", fence[2])
    if in_comment:
        raise AcError("HTML comment opened here is never closed", in_comment)
    return out


HEADING_RE = re.compile(r"^[ ]{0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
LIST_ITEM_RE = re.compile(r"^([ ]{0,3})(?:[-*+]|\d{1,3}[.)])[ \t]+")
ANY_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-*+]|\d{1,3}[.)])[ \t]+")
TABLE_ROW_RE = re.compile(r"^[ \t]*\|")
TABLE_SEP_RE = re.compile(r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$")

# Section titles. English and the Korean titles seen in 0.102 outputs / 0.98.7 analyses.
AC_HEADING = re.compile(
    r"^(?:\d+[.)][ \t]*)?(?:acceptance[ \t]+criteria|ac|수용[ \t]*기준|인수[ \t]*기준)"
    r"(?:[ \t]*[(（][^)）]*[)）])?[ \t]*:?$", re.I)
MAP_HEADING = re.compile(r"(requirements?[ \t]+map|requirement[ \t]+to[ \t]+ac|대응표)", re.I)
ASSUMPTIONS_HEADING = re.compile(r"^(?:\d+[.)][ \t]*)?(?:assumptions?|가정)(?:[ \t]*[(（][^)）]*[)）])?[ \t]*:?$", re.I)


# Stage 3 (E30): the section of the deferred requirement rows and its tag, `(deferred R3)`.
DEFERRED_HEADING = re.compile(
    r"^(?:\d+[.)][ \t]*)?(?:deferred[ \t]+requirements?|미룬[ \t]*요구(?:[ \t]*사항)?)(?:[ \t]*[(（][^)）]*[)）])?[ \t]*:?$", re.I)
_DEFERRED_LIKE = re.compile(r"[(（][ \t]*deferred(?![a-z])", re.I)
_DEFERRED_TAG = re.compile(r"[(（][ \t]*deferred[ \t]+(R[1-9][0-9]{0,3})[ \t]*[)）][ \t*_`]*[.。]?[ \t*_`]*$", re.I)
ROW_ID = re.compile(r"R[1-9][0-9]{0,3}")


def _deferred_tag(text, no):
    """(row id, text without the tag) of `text` ending in one deferred tag; None without any tag.
    Anything that looks like the tag but is not that is an AcError (fail-closed)."""
    like = _DEFERRED_LIKE.findall(text)
    if not like:
        return None
    m = _DEFERRED_TAG.search(text)
    if len(like) != 1 or not m:
        raise AcError("a deferred tag is written `(deferred R<n>)`, one row, once, at the end", no, text)
    rest = text[:m.start()].strip()
    if not _strip_markup(rest):
        raise AcError("a deferred requirement needs its text before the tag", no, text)
    return m.group(1).upper(), rest


def _strip_markup(s):
    """Heading / cell text without emphasis and code ticks."""
    return re.sub(r"[*_`]", "", s).strip()


# --- AC tokens ----------------------------------------------------------------------

# An AC-like token starts at `AC` (not inside a longer ASCII word) followed by `#`, or by
# optional space/hyphen and a digit. `AC power`, `ACL`, `ACID` are not candidates.
_CAND = re.compile(r"(?<![A-Za-z0-9_])AC(?=[ \t]*#|[ \t]*-?[ \t]*\d)")
_NUM = re.compile(r"[ \t]*(?:#[ \t]*|-?[ \t]*)(\d+)")
# A list continuation names more ids after the first; every id needs its own `#`
# (`AC #3, 2 cases` names AC #3 only — 0.102.11).
_CONT = re.compile(
    r"[ \t]*(?:[,、，/&·・][ \t]*|[ \t]+)(?:(?:and|및|と|&)[ \t]+)?(?:AC[ \t]*)?#[ \t]*(\d+)")


def _check_number_end(s, end, token, line):
    """After the digits of an id: no ASCII letter, `.5`, or an adjacent range."""
    nxt = s[end:end + 1]
    if nxt and nxt.isascii() and nxt.isalpha():
        raise AcError(f"unparseable AC token {token!r}: a letter follows the number", line, token)
    if nxt == "." and s[end + 1:end + 2].isdigit():
        raise AcError(f"unparseable AC token {token!r}: dotted number", line, token)
    if nxt in ("-", "–", "—", "~", "〜") and re.match(r"[-–—~〜][ \t]*(?:AC[ \t]*)?#?[ \t]*\d", s[end:]) \
            and not s[end:end + 2].startswith(("— ", "– ", "- ")):
        raise AcError(f"unparseable AC token {token!r}: ranges are not supported, list every id", line, token)


def _to_id(digits, token, line):
    n = int(digits)
    if n < 1 or n > MAX_AC_ID:
        raise AcError(f"AC id out of range in {token!r}", line, token)
    return n


def _tokens(s, line):
    """[(start, end, [ids])] for every AC token in `s`. Raises AcError on an unparseable one.

    Tokens inside backtick code spans are parsed leniently: an unparseable one there is
    skipped (a legend like `AC #n`), a valid one still counts."""
    spans = [(m.start(), m.end()) for m in re.finditer(r"`[^`\n]*`", s)]

    def in_code(pos):
        return any(a <= pos < b for a, b in spans)

    out = []
    pos = 0
    while True:
        m = _CAND.search(s, pos)
        if not m:
            break
        start = m.start()
        nm = _NUM.match(s, m.end())
        try:
            if not nm:
                raise AcError(f"unparseable AC token {s[start:start + 12].strip()!r}: no number", line,
                              s[start:start + 12])
            token = s[start:nm.end()]
            _check_number_end(s, nm.end(), token, line)
            ids = [_to_id(nm.group(1), token, line)]
            end = nm.end()
            while True:
                cm = _CONT.match(s, end)
                if not cm:
                    break
                tok = s[start:cm.end()]
                _check_number_end(s, cm.end(), tok, line)
                ids.append(_to_id(cm.group(1), tok, line))
                end = cm.end()
            out.append((start, end, ids))
            pos = max(end, start + 2)
        except AcError:
            if in_code(start):
                pos = start + 2
                continue
            raise
    return out


# A case tag candidate: one bracket pair on one line. Parentheses are the written form;
# `[…]` and `【…】` are the old forms, still read (module doc).
_TAG_GROUP = re.compile(r"\(([^()\n]{1,100})\)|（([^（）\n]{1,100})）|\[([^\[\]\n]{1,100})\]|【([^【】\n]{1,100})】")
# What may stand before a tag at the start of a line or cell: list marker, task checkbox,
# emphasis, a case id with a digit (`C3`, `E4`, `TC-12`, `T1.2`) and an optional separator,
# a markdown escape `\`. A word without a digit is prose, not a case id.
_TAG_LEAD = re.compile(
    r"^[ \t]*(?:(?:[-*+]|\d{1,3}[.)])[ \t]+)?(?:\[[ xX]\][ \t]+)?[*_`]{0,3}"
    r"(?:[A-Za-z]{1,8}[-_]?\d{1,4}(?:[.-]\d{1,4})*[*_`]{0,3}[ \t]*[:.)—–-]?[ \t]*)?[*_`]{0,3}[ \t]*\\?$")
# What may follow a tag at the end of a line or cell: emphasis, one full stop, spaces.
_TAG_TRAIL = re.compile(r"^[ \t*_`]*[.。]?[ \t*_`]*$")
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


_TAG_LABEL = re.compile(r"[ \t]*[,;、，；/][ \t]*\S|[ \t]+[(（]")
# A list item led by a bare AC list and a separator, like a heading: `- **AC #2**: …`,
# `1. AC #3 — …` (not `- AC #3 은 …`, which is a sentence).
_ITEM_HEAD = re.compile(
    r"^[ \t]*(?:[-*+]|\d{1,3}[.)])[ \t]+(?:\[[ xX]\][ \t]+)?[*_]{0,2}(?=AC)(?P<list>[^*_:：—–\n]{1,100}?)[*_]{0,2}"
    r"[ \t]*(?:[:：—–]|-[ \t]|$)")


def _ac_list_ids(text, line):
    """The ids when `text` (markup and spaces around it ignored) is one AC list (`AC #2`,
    `AC #2, #5`, `AC #1 및 #3`), alone or followed by a separator and a label (`AC #1, 엣지`,
    `AC #5, 실패 경로` — 0.102.10 #1945 output); None otherwise (`AC #1 의 정의` is prose).

    The caller has already parsed the whole line with `_tokens` (an unparseable token
    outside code raised there), so a parse error here comes from a code-span legend with
    its ticks stripped (`` (`AC #n`) ``) — that is not a tag."""
    core = text.strip().strip("*_`\\").strip()
    try:
        toks = _tokens(core, line)
    except AcError:
        return None
    if toks and toks[0][0] == 0 and (toks[0][1] == len(core) or _TAG_LABEL.match(core, toks[0][1])):
        return toks[0][2]                 # an AC token inside the label is a mention only
    return None


def _segment_tags(seg, line):
    """Ids of the case tags at the start or the end of `seg` (a line or a table cell)."""
    code = [(m.start(), m.end()) for m in _CODE_SPAN.finditer(seg)]
    tags = []
    for m in _TAG_GROUP.finditer(seg):
        if any(a <= m.start() < b for a, b in code):
            continue                      # an example in backticks is not a tag
        inner = next(g for g in m.groups() if g is not None)
        found = _ac_list_ids(inner, line)
        if found is not None:
            tags.append((m.start(), m.end(), found))
    ids = []
    for k, (start, end, found) in enumerate(tags):
        # tags next to each other form one run: `(AC #2) (AC #5)` at the end both count
        before = seg[:start]
        for a, b, _f in reversed(tags[:k]):
            before = before[:a] + before[b:]
        after = seg[end:]
        for a, b, _f in reversed(tags[k + 1:]):
            after = after[:a - end] + after[b - end:]
        if _TAG_LEAD.match(before) or _TAG_TRAIL.match(after):
            ids.extend(found)
    return ids


def _line_refs(line, no):
    """(ids that count as references, ids only mentioned) on one line — the rules are in
    the module doc. Every AC token on the line is still parsed (fail-closed)."""
    toks = _tokens(line, no)
    if not toks:
        return [], []
    every = [n for _s, _e, found in toks for n in found]
    if HEADING_RE.match(line):
        return every, []
    if TABLE_ROW_RE.match(line):
        ids = []
        for cell in _CELL_SPLIT.split(line.strip().strip("|")):
            whole = None if not cell.strip() else _ac_list_ids(cell, no)
            ids.extend(whole if whole is not None else _segment_tags(cell, no))
    else:
        ids = _segment_tags(line, no)
        head = _ITEM_HEAD.match(line)
        if head:
            core = head.group("list").strip()
            found = _tokens(core, no)
            if len(found) == 1 and found[0][0] == 0 and found[0][1] == len(core):
                ids.extend(found[0][2])
    counted = set(ids)
    return ids, [n for n in every if n not in counted]


# --- analysis.md --------------------------------------------------------------------

_DEF_RE = re.compile(
    r"^(?P<indent>[ ]{0,3})(?:(?:[-*+]|\d{1,3}[.)])[ \t]+)?[*_`]{0,2}AC[ \t]*(?:#[ \t]*|-?[ \t]*)(?P<n>\d+)[*_`]{0,2}"
    r"[ \t]*(?:(?P<delim>[:：.)\]—–-])|$)[ \t]*(?P<rest>.*)$")
_STARTS_WITH_AC = re.compile(
    r"^[ ]{0,3}(?:(?:[-*+]|\d{1,3}[.)])[ \t]+)?[*_`]{0,2}AC(?=[ \t]*#|[ \t]*-?[ \t]*\d)")
_FIELD_RE = re.compile(r"^[ ]{0,3}(?:[-*+][ \t]+)?[*_]{0,2}(type|size|risk|split|prerequisite|safety_net)[*_]{0,2}[ \t]*[:：][ \t]*(.*)$",
                       re.I)


def machine_fields(stage):
    """The machine fields analysis.md must carry in an engine stage."""
    codes.check_stage(stage)
    return MACHINE_FIELDS if stage < 3 else STAGE3_MACHINE_FIELDS


def _sections(lines):
    """[(heading lineno, level, title, [(lineno, line)] body)] — a body ends at the next
    heading of the same or a higher level."""
    heads = []
    for i, (no, line) in enumerate(lines):
        m = HEADING_RE.match(line)
        if m:
            heads.append((i, no, len(m.group(1)), m.group(2).strip()))
    out = []
    for k, (i, no, level, title) in enumerate(heads):
        end = len(lines)
        for j, _no2, level2, _t in heads[k + 1:]:
            if level2 <= level:
                end = j
                break
        out.append((no, level, title, lines[i + 1:end]))
    return out


def _field_value(name, raw, no):
    value = _strip_markup(raw).lower()
    # a safety_net value has a hyphen of its own (with-refactor)
    end = r"[\s,;:(（—–]+" if name == "safety_net" else r"[\s,;:(（—–-]+"
    first = re.split(end, value, maxsplit=1)[0] if value else ""
    allowed = {
        "type": codes.AnalysisType.values(),
        "size": codes.Size.values(),
        "risk": codes.Risk.values(),
        "split": SPLIT_VALUES,
        "prerequisite": PREREQUISITE_VALUES,
        "safety_net": codes.SafetyNet.values(),
    }[name]
    if first not in allowed:
        raise AcError(f"`{name}:` must be one of {', '.join(allowed)} (got {raw.strip()!r})", no, raw)
    return first


def machine_field(text, name):
    """Readiness E4: one machine field of an analysis.md text read leniently — the first valid value of
    `name` before the first `##` heading, or None (absent, unreadable). Never raises: the bug guard reads
    every recorded analysis, also one that ac-format refused."""
    if name not in STAGE3_MACHINE_FIELDS or not isinstance(text, str):
        return None
    for no, line in enumerate(text.split("\n"), 1):
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) >= 2:
            return None
        fm = _FIELD_RE.match(line)
        if fm and fm.group(1).lower() == name:
            try:
                return _field_value(name, fm.group(2), no)
            except AcError:
                continue
    return None


def _parse_fields(lines, stage):
    """Machine fields from the preamble (before the first `##` or deeper heading)."""
    wanted = machine_fields(stage)
    fields = {}
    for no, line in lines:
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) >= 2:
            break
        fm = _FIELD_RE.match(line)
        if not fm:
            continue
        name = fm.group(1).lower()
        if name not in wanted:
            continue
        value = _field_value(name, fm.group(2), no)
        if name in fields and fields[name] != value:
            raise AcError(f"`{name}:` is given twice with different values", no, line)
        fields[name] = value
    missing = [f for f in wanted if f not in fields]
    if missing:
        raise AcError("missing machine field(s) before the first `##` heading: " + ", ".join(missing))
    return fields


def _parse_acs(lines, sections):
    """(ids in document order, {id: text}) from every acceptance-criteria section."""
    ac_sections = [s for s in sections if AC_HEADING.match(_strip_markup(s[2]))]
    if not ac_sections:
        raise AcError("no acceptance-criteria section (heading `## Acceptance criteria`)")
    ids, texts = [], {}
    in_section = set()
    for head_no, _level, _title, body in ac_sections:
        current = None
        for no, line in body:
            in_section.add(no)
            if not line.strip():
                current = None
                continue
            _tokens(line, no)               # an unparseable AC-like token anywhere is an error
            if HEADING_RE.match(line):
                if _tokens(line, no):
                    raise AcError("an AC token in a heading inside the acceptance-criteria section; "
                                  "write `- AC #n: …` list items", no, line)
                current = None
                continue
            if TABLE_ROW_RE.match(line):
                raise AcError("table row in the acceptance-criteria section; write `- AC #n: …` list items",
                              no, line)
            nested = bool(re.match(r"^(?:\t|[ ]{4,})", line))
            if nested:
                if _STARTS_WITH_AC.match(line.lstrip()):
                    raise AcError("an AC definition must be a top-level list item, not an indented one "
                                  "(it would be read as part of the previous criterion)", no, line)
                if current is not None:
                    texts[current] += " " + line.strip()
                continue
            dm = _DEF_RE.match(line)
            if dm:
                n = _to_id(dm.group("n"), line.strip()[:12], no)
                if n in texts:
                    raise AcError(f"AC #{n} is defined twice", no, line)
                if not dm.group("rest").strip():
                    raise AcError(f"AC #{n} has no text", no, line)
                ids.append(n)
                texts[n] = dm.group("rest").strip()
                current = n
                continue
            if _STARTS_WITH_AC.match(line):
                raise AcError("line starts with an AC token but is not an AC definition (`- AC #n: text`)",
                              no, line)
            if ANY_LIST_ITEM_RE.match(line):
                raise AcError("list item in the acceptance-criteria section is not an AC definition "
                              "(`- AC #n: text`)", no, line)
            if current is not None:
                texts[current] += " " + line.strip()
    # an AC definition outside every AC section would be silently dropped
    for no, line in lines:
        if no in in_section:
            continue
        if ANY_LIST_ITEM_RE.match(line) and _DEF_RE.match(line.lstrip()):
            raise AcError("AC definition outside the acceptance-criteria section", no, line)
    if not ids:
        raise AcError("the acceptance-criteria section defines no AC")
    return ids, texts


def _parse_requirement_map(sections, stage=2):
    """(rows, deferred rows of the map) — the second list is always empty before stage 3."""
    map_sections = [s for s in sections if MAP_HEADING.search(_strip_markup(s[2]))]
    if not map_sections:
        raise AcError("no requirement map (heading `## Requirement map`, a table of issue requirement ↔ AC)")
    rows, deferred = [], []
    for _head_no, _level, _title, body in map_sections:
        table_rows = [(no, line) for no, line in body if TABLE_ROW_RE.match(line)]
        header_seen = False
        for no, line in table_rows:
            if TABLE_SEP_RE.match(line):
                continue
            if not header_seen:
                header_seen = True      # the first row is the column header
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2 or not cells[0]:
                raise AcError("requirement map row needs `| requirement | AC … |`", no, line)
            refs = []
            for cell in cells[1:]:
                for a in _tokens(cell, no):
                    refs.extend(a[2])
            tag = _deferred_tag(cells[0], no) if stage >= 3 else None
            if tag is not None:
                deferred.append({"row": tag[0], "text": _strip_markup(tag[1]), "acs": list(dict.fromkeys(refs))})
                continue
            rows.append((_strip_markup(cells[0]), list(dict.fromkeys(refs))))
    if not rows:
        raise AcError("the requirement map has no rows" + (" that are not deferred" if deferred else ""))
    return rows, deferred


def _parse_deferred(sections):
    """[{"row", "text"}] of the deferred-requirements section(s) (E30), document order."""
    out = []
    for _no, _level, title, body in sections:
        if not DEFERRED_HEADING.match(_strip_markup(title)):
            continue
        items = []                       # [first line number, text]
        open_item = False
        for no, line in body:
            if HEADING_RE.match(line) or TABLE_ROW_RE.match(line):
                raise AcError("the deferred-requirements section holds list items only "
                              "(`- <requirement> (deferred R<n>)`)", no, line)
            if LIST_ITEM_RE.match(line):
                items.append([no, LIST_ITEM_RE.sub("", line, count=1).strip()])
                open_item = True
            elif not line.strip():
                open_item = False
            elif open_item or (items and re.match(r"^(?:\t|[ ]{2,})", line)):
                items[-1][1] += " " + line.strip()
            elif _DEFERRED_LIKE.search(line):
                raise AcError("a deferred tag outside a list item", no, line)
        for no, text in items:
            tag = _deferred_tag(text, no)
            if tag is None:
                raise AcError("list item without a `(deferred R<n>)` tag in the deferred-requirements section", no, text)
            if any(d["row"] == tag[0] for d in out):
                raise AcError(f"{tag[0]} is deferred twice", no, text)
            out.append({"row": tag[0], "text": tag[1]})
    return out


def _parse_assumptions(sections):
    out = []
    for _no, _level, title, body in sections:
        if ASSUMPTIONS_HEADING.match(_strip_markup(title)):
            for _n, line in body:
                if ANY_LIST_ITEM_RE.match(line):
                    out.append(ANY_LIST_ITEM_RE.sub("", line, 1).strip())
    return out


def parse_analysis(text, stage=2):
    """{"acs": [ids], "ac_text": {id: text}, "type": AnalysisType, "size": Size, "risk": Risk,
    "split": bool, "prerequisite_open": bool, "requirement_map": [(requirement, [ac ids])],
    "assumptions": [text], "safety_net": SafetyNet (stage < 3: always none),
    "deferred": [{"row", "text"}] (the `## 미룬 요구` section, E30), "deferred_map": [{"row", "text",
    "acs"}] (requirement-map rows with a deferred tag, left out of requirement_map) — both empty
    before stage 3}. Raises AcError."""
    if not (text or "").strip():
        raise AcError("analysis.md is empty")
    lines = _clean_lines(text)
    fields = _parse_fields(lines, stage)
    sections = _sections(lines)
    ids, texts = _parse_acs(lines, sections)
    rmap, deferred_map = _parse_requirement_map(sections, stage)
    deferred = _parse_deferred(sections) if stage >= 3 else []
    # every other AC token anywhere must still parse (fail-closed)
    for no, line in lines:
        _tokens(line, no)
    return {
        "acs": ids,
        "ac_text": texts,
        "type": fields["type"],
        "size": fields["size"],
        "risk": fields["risk"],
        "split": fields["split"] == "proposed",
        "prerequisite_open": fields["prerequisite"] == "open",
        "requirement_map": rmap,
        "assumptions": _parse_assumptions(sections),
        "safety_net": fields.get("safety_net", codes.SafetyNet.NONE.value),
        "deferred": deferred,
        "deferred_map": deferred_map,
    }


def _deferred_problems(analysis, deferred):
    """E30: the section names exactly the rows the engine deferred; a deferred row has no AC."""
    want = list(deferred)
    got = [d["row"] for d in analysis["deferred"]]
    out = [f"requirement row {r} was deferred but the `## 미룬 요구` section does not list it" for r in want if r not in got]
    out += [f"the `## 미룬 요구` section lists {r}, which was not deferred" for r in got if r not in want]
    for d in analysis["deferred_map"]:
        if d["row"] not in got:
            out.append(f"the requirement map tags {d['row']} as deferred, which the `## 미룬 요구` section does not list")
        if d["acs"]:
            out.append(f"the deferred row {d['row']} still names an AC in the requirement map: {d['text']!r}")
    return out


def check_analysis(analysis, stage=2, deferred=()):
    """Problems a parsed analysis has beyond the parse (reasons, one per list item; empty = ok).

    ids are exactly 1..n in order (a gap hides a dropped AC); every requirement row names at
    least one AC and only existing ones. Stage ≥ 3 (E3): a safety_net other than none needs
    type refactor; the deferred rows are exactly `deferred` (row ids of state.deferred_rows, E30)."""
    codes.check_stage(stage)
    deferred = list(deferred)
    if (deferred and stage < 3) or len(set(deferred)) != len(deferred) \
            or not all(isinstance(r, str) and ROW_ID.fullmatch(r) for r in deferred):
        raise ValueError(f"bad deferred rows {deferred!r} (stage {stage})")
    problems = []
    if stage >= 3:
        problems += _deferred_problems(analysis, deferred)
    if stage >= 3 and analysis["safety_net"] != codes.SafetyNet.NONE.value \
            and analysis["type"] != codes.AnalysisType.REFACTOR.value:
        problems.append(f"safety_net: {analysis['safety_net']} needs type: refactor (type is {analysis['type']})")
    acs = analysis["acs"]
    if acs != list(range(1, len(acs) + 1)):
        problems.append("AC ids must be 1..n in order without gaps (found "
                        + ", ".join(f"AC #{n}" for n in acs) + ")")
    known = set(acs)
    for requirement, refs in analysis["requirement_map"]:
        if not refs:
            problems.append(f"requirement without an AC in the requirement map: {requirement!r}")
        for n in refs:
            if n not in known:
                problems.append(f"requirement map names AC #{n}, which analysis.md does not define "
                                f"({requirement!r})")
    return problems


# --- test-cases.md ------------------------------------------------------------------

def _scan_test_cases(text):
    """(referenced ids, {id only mentioned in prose: first line number})."""
    refs, mentions = set(), {}
    for no, line in _clean_lines(text):
        if line.strip():
            ids, mentioned = _line_refs(line, no)
            refs.update(ids)
            for n in mentioned:
                mentions.setdefault(n, no)
    return refs, {n: no for n, no in mentions.items() if n not in refs}


def parse_test_case_refs(text):
    """The set of AC ids test-cases.md references (a heading, or a case tag at the start /
    end of a line or table cell — module doc; a prose mention does not count). Raises
    AcError on an unparseable AC-like token."""
    return _scan_test_cases(text)[0]


# --- stage-1 plan rule (I1) ---------------------------------------------------------

def plan_rule_reasons(analysis):
    """Why the stage-1 plan rule stops (I1): codes in a fixed order; empty = proceed."""
    reasons = []
    if analysis["type"] != codes.AnalysisType.FEATURE.value:
        reasons.append(PLAN_REASON_TYPE)
    if analysis["split"]:
        reasons.append(PLAN_REASON_SPLIT)
    if analysis["prerequisite_open"]:
        reasons.append(PLAN_REASON_PREREQUISITE)
    if analysis["risk"] == codes.Risk.HIGH.value:
        reasons.append(PLAN_REASON_RISK)
    return reasons


def plan_rule_stop(analysis):
    """I1: True when type ≠ feature, a split is proposed, a prerequisite is open, or risk = high."""
    return bool(plan_rule_reasons(analysis))


# --- the two check scripts' logic (scripts/ac_format.py, scripts/ac_coverage.py) -----

EXIT_PASS, EXIT_FAIL, EXIT_CANNOT_JUDGE = 0, 1, 2
"""Plugin check-script exit codes (interfaces.md §2.7): pass / fail (reasons on stdout) /
cannot judge (also red)."""


def _load_analysis(root, issue, stage=2):
    """(analysis, None) or (None, (exit code, [reason lines]))."""
    where = f"docs/specs/{issue}/analysis.md"
    try:
        text = read_spec(root, issue, "analysis.md")
    except SpecFileError as e:
        return None, (EXIT_CANNOT_JUDGE, [f"cannot read {where}: {e}"])
    if text is None:
        return None, (EXIT_FAIL, [f"{where} not found"])
    try:
        return parse_analysis(text, stage), None
    except AcError as e:
        loc = f"{where}:{e.line}" if e.line else where
        return None, (EXIT_FAIL, [f"{loc}: {e.message}"])


def check_format(root, issue, stage=2, deferred=()):
    """`ac-format`: analysis.md has a parseable AC set and the analysis structure fields.
    Returns (exit code, [stdout lines])."""
    analysis, failure = _load_analysis(root, issue, stage)
    if failure:
        return failure
    problems = check_analysis(analysis, stage, deferred)
    if problems:
        return EXIT_FAIL, [f"docs/specs/{issue}/analysis.md: {p}" for p in problems]
    return EXIT_PASS, [f"ok: {len(analysis['acs'])} AC(s), type {analysis['type']}, risk {analysis['risk']}"]


def check_coverage(root, issue):
    """`ac-coverage`: every AC of analysis.md is referenced by test-cases.md (document level
    only, §7.1) and test-cases.md references no AC analysis.md lacks. Returns (exit code, [lines])."""
    analysis, failure = _load_analysis(root, issue)
    if failure:
        return failure
    where = f"docs/specs/{issue}/test-cases.md"
    try:
        text = read_spec(root, issue, "test-cases.md")
    except SpecFileError as e:
        return EXIT_CANNOT_JUDGE, [f"cannot read {where}: {e}"]
    if text is None:
        return EXIT_FAIL, [f"{where} not found"]
    try:
        refs, mentions = _scan_test_cases(text)
    except AcError as e:
        loc = f"{where}:{e.line}" if e.line else where
        return EXIT_FAIL, [f"{loc}: {e.message}"]
    known = set(analysis["acs"])
    lines = []
    for n in analysis["acs"]:
        if n in refs:
            continue
        if n in mentions:
            lines.append(f"AC #{n}: not referenced in {where} (line {mentions[n]} mentions it in prose, which "
                         f"does not count — end the case's line with the tag `(AC #{n})`)")
        else:
            lines.append(f"AC #{n}: not referenced in {where}")
    lines += [f"{where} references AC #{n}, which analysis.md does not define" for n in sorted(refs - known)]
    if lines:
        return EXIT_FAIL, lines
    return EXIT_PASS, [f"ok: all {len(known)} AC(s) are referenced"]
