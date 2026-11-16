"""workflows.dev.cases — the case / AC ids of `docs/specs/<N>/test-cases.md` (K2 review B2).

Line by line, no nested quantifiers (linear time — the first version's `^(?:\\s*[|#*\\-]+\\s*)*`
backtracked exponentially on a markdown table separator). Shapes measured on word_app's 233 real
files:
* tables — the id column is the header cell `# | ID | No | 번호 | 케이스 | TC | AC`; a bare number
  there becomes `#<n>`; a table without such a column contributes a non-numeric first cell
  (`T1`, `TC-N1`, `C3`) or, failing that, the `AC<n>` mentions of its rows;
* lines — `AC #3`, `TC-01`, `C12`, `**AC1**` at the start (after `#`/`-`/`*`/`>`);
* headings — `### TC-S1 (AC1)`, `### 케이스 1 —`, `## 1-1.` and any `AC<n>` in a heading.
231/233 files yield ids; the other two (prose / bullet-only checklists, #961, #1791) yield none
— the stage then uses the tester's `covers[].ac` set (`ac_source: tester`) instead of pausing.
"""

import re

ID_CELL = re.compile(r"^(AC ?#?\d+[a-z]?|TC-?[A-Z]{0,3}\d+(?:[-.]\d+)*[a-z]?|[A-Z]{1,3}-?\d+(?:[-.]\d+)*[a-z]?|"
                     r"#?\d+(?:[-.]\d+)*[a-z]?)$")
HEAD_ID = re.compile(r"^#{2,6}\s+(?:케이스|Case|case|TC)?\s?((?:TC-?)?[A-Z]{0,3}-?\d+(?:[-.]\d+)*[a-z]?)(?=[\s.:)—-]|$)")
AC_ANY = re.compile(r"\bAC ?#?\d+\b")
LINE_ID = re.compile(r"^[\s#>*-]{0,12}\**\s{0,4}(AC ?#?\d+|TC-?[A-Z]{0,3}\d+(?:[-.]\d+)*|[A-Z]{1,2}\d+(?:[-.]\d+)*)\b")
ID_HEAD = {"#", "id", "no", "no.", "번호", "케이스", "case", "tc", "케이스 id", "case id", "tc id", "ac"}
SEP = re.compile(r"^\|?\s{0,4}:?-{2,}")
NUM = re.compile(r"^#?\d")


def cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip().strip("*`").strip() for c in s.split("|")]


def case_ids(text):
    """Distinct ids in document order."""
    out = []
    seen = set()

    def add(k):
        k = " ".join(k.split())
        if k not in seen:
            seen.add(k)
            out.append(k)
    lines = (text or "").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("|"):
            head, col, j = cells(ln), None, i
            if i + 1 < len(lines) and SEP.match(lines[i + 1].strip()):
                for k, h in enumerate(head):
                    if h.lower() in ID_HEAD:
                        col = k
                        break
                j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                row = lines[j]
                if not SEP.match(row.strip()):
                    cs = cells(row)
                    if col is not None and col < len(cs) and ID_CELL.match(cs[col]):
                        add("#" + cs[col] if cs[col][:1].isdigit() else cs[col])
                    elif cs and ID_CELL.match(cs[0]) and not NUM.match(cs[0]):
                        add(cs[0])
                    if col is None and not (cs and ID_CELL.match(cs[0])):
                        for m in AC_ANY.finditer(row):
                            add(m.group(0))
                j += 1
            i = max(j, i + 1)
            continue
        m = LINE_ID.match(ln)
        if m:
            add(m.group(1))
        else:
            h = HEAD_ID.match(ln)
            if h:
                add("#" + h.group(1) if h.group(1)[:1].isdigit() else h.group(1))
        if ln.lstrip().startswith("#"):
            for a in AC_ANY.finditer(ln):
                add(a.group(0))
        i += 1
    return out
