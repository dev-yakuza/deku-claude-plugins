"""workflows.dev.cases — the case / AC ids of `docs/specs/<N>/test-cases.md` (K2 review B2, r2-B2).

Line by line, no nested quantifiers (linear time). An id is accepted only where the document
MARKS it as a case:
* tables — the header's id column (`# | ID | No | 번호 | 케이스 | TC | AC`, a bare number becomes
  `#<n>`); a table without one contributes its first cells only when they are case-shaped
  (`T1`, `TC-N1`, `C3`) and at least two rows share the prefix (a file/codec table `H264 | ES6`
  is not a case table), else its rows' `AC<n>` mentions;
* lines — `AC #3` anywhere at a line start; `TC-01` / `C12` / `**C3**` bullets only when a
  separator follows the id (`:`, `—`, `.`, `)`, `**`) — `- V2 API 를 …` is prose;
* headings — a heading carrying a case marker (`TC-S1`, `케이스 2`, `항목1`, `Case 3`, `S-01 …`, any
  `AC<n>`); a NUMBERED sub-heading (level ≥ 3): a compound number (`### 1-1.`) always, a single number
  (`### 3.`) only below a "케이스 / test case" or an `AC<n>` section; a top-level
  `## n.` section number is never a case (r2-B2: `## 1. 범위` became `#1`).
"""

import re

ID_CELL = re.compile(r"^(AC ?#?\d+[a-z]?|TC-?[A-Z]{0,3}\d+(?:[-.]\d+)*[a-z]?|[A-Z]{1,3}-?\d+(?:[-.]\d+)*[a-z]?|"
                     r"#?\d+(?:[-.]\d+)*[a-z]?)$")
CASE_CELL = re.compile(r"^(TC-?[A-Z]{0,3}\d+(?:[-.]\d+)*[a-z]?|([A-Z]{1,2})-?\d+(?:[-.]\d+)*[a-z]?)$")
AC_ANY = re.compile(r"\bAC ?#?\d+\b")
AC_LINE = re.compile(r"^[\s>*-]{0,8}\**\s{0,4}(AC ?#?\d+)\b")
BULLET_ID = re.compile(r"^[\s>*-]{1,8}\**\s{0,4}(TC-?[A-Z]{0,3}\d+(?:[-.]\d+)*|[A-Z]{1,2}\d+(?:[-.]\d+)*[a-z]?)"
                       r"(?:\*\*|\s{0,2}[:.)—|]|\s{0,2}\()")
HEADING = re.compile(r"^(#{2,6})\s+(.*)$")
H_MARKED = re.compile(r"^(?:\*\*)?(?:((?:케이스|항목|Case|case)\s?\d+(?:[-.]\d+)*[a-z]?)|(TC-?[A-Z]{0,3}\d+(?:[-.]\d+)*[a-z]?)|"
                      r"([A-Z]{1,3}-\d+(?:[-.]\d+)*[a-z]?|[A-Z]{1,2}\d+(?:[-.]\d+)*[a-z]?))(?=[\s.:)—*]|$)")
H_NUMBERED = re.compile(r"^(\d+(?:[-.]\d+)+[a-z]?|\d+[a-z]?)(?=[\s.:)—]|$)")
CASE_SECTION = re.compile(r"케이스|[Tt]est ?[Cc]ase|테스트 ?목록|시나리오")
ID_HEAD = {"#", "id", "no", "no.", "번호", "케이스", "case", "tc", "케이스 id", "case id", "tc id", "ac"}
SEP = re.compile(r"^\|?\s{0,4}:?-{2,}")
NUM = re.compile(r"^#?\d")


def cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    out = []
    for c in s.split("|"):
        c = c.strip().strip("*`").strip()
        lead = c.split(" ", 1)[0] if " (" in c else c          # `C-8 (경계)` → `C-8`
        out.append(lead)
    return out


def _table(lines, i, add):
    head, col, j = cells(lines[i]), None, i
    if i + 1 < len(lines) and SEP.match(lines[i + 1].strip()):
        for k, h in enumerate(head):
            if h.lower() in ID_HEAD:
                col = k
                break
        j = i + 2
    rows = []
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        if not SEP.match(lines[j].strip()):
            rows.append((lines[j], cells(lines[j])))
        j += 1
    if col is not None:
        for _r, cs in rows:
            if col < len(cs) and ID_CELL.match(cs[col]):
                add("#" + cs[col] if cs[col][:1].isdigit() else cs[col])
    else:
        firsts = [cs[0] for _r, cs in rows if cs and CASE_CELL.match(cs[0])]
        prefixes = {}
        for f in firsts:
            m = CASE_CELL.match(f)
            p = "TC" if f.startswith("TC") else m.group(2)
            prefixes[p] = prefixes.get(p, 0) + 1
        real_table = j > i + 1 and SEP.match(lines[i + 1].strip()) is not None
        # K2r3-m1: a header-row table's first cells count only when its header names cases
        case_head = any(re.search(r"AC|TC|케이스|[Cc]ase|시나리오|테스트", h) for h in head) if real_table else True
        if firsts and case_head and (max(prefixes.values()) >= 2 or not real_table):
            for f in firsts:
                add(f)
        else:
            for r, _cs in rows:
                for m in AC_ANY.finditer(r):
                    add(m.group(0))
    return max(j, i + 1)


def case_ids(text, dropped=None):
    """Distinct ids in document order. `dropped` (a list) receives the numbered headings that
    were NOT taken as cases (for the decision log's `ids_dropped`)."""
    out, seen = [], set()

    def add(k):
        k = " ".join(k.split()).lstrip("-")
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    lines = (text or "").split("\n")
    section = []                                   # [(level, text)] of open headings
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("|"):
            i = _table(lines, i, add)
            continue
        h = HEADING.match(ln)
        if h:
            level, title = len(h.group(1)), h.group(2).strip()
            while section and section[-1][0] >= level:
                section.pop()
            m = H_MARKED.match(title)
            if m:
                add(m.group(1) or m.group(2) or m.group(3))      # `케이스 2` / `항목1` kept literal
            else:
                n = H_NUMBERED.match(title)
                if n:
                    in_cases = any(CASE_SECTION.search(t) or AC_ANY.search(t) for _l, t in section)
                    compound = bool(re.match(r"^\d+[-.]\d", n.group(1)))
                    if level >= 3 and (in_cases or compound):
                        add("#" + n.group(1))
                    elif dropped is not None:
                        dropped.append(n.group(1))
            for a in AC_ANY.finditer(title):
                add(a.group(0))
            section.append((level, title))
            i += 1
            continue
        m = AC_LINE.match(ln)
        if m:
            add(m.group(1))
        else:
            b = BULLET_ID.match(ln)
            # K2r3-m1: a bullet id only below a case / AC section (`- V2: API 버전` under
            # "공통 전제" is prose); a document with no headings at all is one case list
            if b and (not section or any(CASE_SECTION.search(t) or AC_ANY.search(t) for _l, t in section)):
                add(b.group(1))
        i += 1
    return out


# ---- 0.102.9 (word_app #1797 loop-back cap): ONE id set for the TEST judge and the checks -------------------------
# #1797's test-cases.md lists cases `C1`…`C32` under `### … (AC #n)` headings, each line tagged `— AC #n`. `case_ids`
# returned BOTH sets (the heading's `AC #n` and the bullets' `C<k>`), the tester mapped its covers by case id, the judge
# answered some ids of one set and none of the other — every run "uncovered" the other half (D25: C-ids effective, every
# AC uncovered; D32/D33: the reverse), the effectiveness check found no cover for the AC ids (`unsure` with no detail),
# and the loop-back cap was spent on the engine's own id mismatch. Now the AC tags are the source of truth: a case that
# names an AC (on its own line / row, else the nearest heading above it) is FOLDED into that AC — the judge, the covers,
# the checks and the gap all speak AC ids; a case naming no AC stays its own unit.
AC_TAG = re.compile(r"\bAC ?#? ?-?(\d+)\b")


def ac_key(x):
    """`AC #3` / `AC3` / `AC 3` / `AC#3` → `AC #3`; anything else unchanged."""
    m = re.match(r"^\s*AC ?#? ?-?(\d+)\s*$", str(x or ""))
    return "AC #%s" % m.group(1) if m else " ".join(str(x or "").split())


def _line_case(ln, section):
    """The case id a line MARKS (bullet / table first cell / heading), or None."""
    if ln.lstrip().startswith("|"):
        cs = cells(ln)
        if cs and (CASE_CELL.match(cs[0]) or (ID_CELL.match(cs[0]) and not NUM.match(cs[0]))):
            return cs[0]
        return None
    h = HEADING.match(ln)
    if h:
        m = H_MARKED.match(h.group(2).strip())
        return (m.group(1) or m.group(2) or m.group(3)) if m else None
    b = BULLET_ID.match(ln)
    return b.group(1) if b else None


def ac_map(text):
    """{case id: [AC keys]} for every case of `case_ids(text)` that names an AC — on its own line (a table row, a
    bullet, a heading) or, failing that, in the nearest open heading that names one."""
    ids = set(case_ids(text))
    out = {}
    section = []
    for ln in (text or "").split("\n"):
        h = HEADING.match(ln)
        cid = _line_case(ln, section)
        if h:
            level = len(h.group(1))
            while section and section[-1][0] >= level:
                section.pop()
        if cid and cid in ids and not AC_TAG.match(cid) and cid not in out:
            own = ["AC #%s" % n for n in AC_TAG.findall(ln[ln.find(cid) + len(cid):])]
            if not own:
                for _l, t in reversed(section):
                    own = ["AC #%s" % n for n in AC_TAG.findall(t)]
                    if own:
                        break
            if own:
                out[cid] = list(dict.fromkeys(own))
        if h:
            section.append((len(h.group(1)), h.group(2).strip()))
    return out


def judged_units(text, deferred=()):
    """(ids the TEST judge rules on, {AC id: [its cases]}, {case id: [AC ids]}) — AC ids (in document order) with the
    cases that name them folded in, plus every case naming no AC as its own unit. A deferred case leaves its AC's case
    list; a deferred AC leaves the set."""
    ids = case_ids(text)
    amap = ac_map(text)
    if not amap:                                   # no case names an AC — the ids as before
        return [x for x in ids if x not in set(deferred or ())], {}, {}
    deferred = set(deferred or ()) | set(ac_key(x) for x in deferred or ())
    units, members = [], {}
    for x in ids:
        k = ac_key(x)
        if AC_TAG.match(x):
            if k not in deferred and k not in units:
                units.append(k)
                members.setdefault(k, [])
            continue
        if x in deferred:
            continue
        acs = amap.get(x)
        if not acs:
            if x not in units:
                units.append(x)
            continue
        for a in acs:
            if a in deferred:
                continue
            if a not in units:
                units.append(a)
            members.setdefault(a, []).append(x)
    return units, members, amap


def rekey_covers(covers, amap):
    """The tester's covers in the judged id set: a cover of a case that names an AC counts for each such AC (the case
    kept as `case`); `AC3` / `AC #3` forms → `AC #3`. No mapping (no case names an AC) → the covers as they are."""
    if not amap:
        return list(covers or [])
    out = []
    for c in covers or []:
        if not isinstance(c, dict):
            continue
        a = c.get("ac")
        k = ac_key(a)
        if a in (amap or {}):
            for x in amap[a]:
                out.append(dict(c, ac=x, case=a))
        else:
            out.append(dict(c, ac=k) if k != a else c)
    return out
