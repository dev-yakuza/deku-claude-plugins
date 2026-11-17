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
        if firsts and (max(prefixes.values()) >= 2 or not real_table):
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
            if b:
                add(b.group(1))
        i += 1
    return out
