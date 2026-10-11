#!/usr/bin/env python3
"""
ledger.py — read and compact the evolve ledger without an LLM reading all of it.

`.claude/guild/evolution-log.md` grows by one run entry per `/gld evolve` and nothing shrank it:
one repo reached 383KB / 33 runs, past what a single Read returns, so Phase 0 could miss the
newest runs or miscount the next run number. This tool owns every mechanical part:

    ledger.py status            one line: runs, next run number, last run date, window, archived
                                run count, line count of the active file (to Read only its tail)
    ledger.py context           status + what older runs must still say (below) + the window
                                runs — what evolve Phase 0 reads; bounded by OUTPUT_CHARS
    ledger.py compact           move every run outside the window from the active ledger to
                                .claude/guild/evolution-log.archive.md (append, never delete)
    ledger.py where <n>         path:start-end lines of run #<n>, active file or archive
    ledger.py tagged <tag>      the `<tag>:` lines of the newest run that has any (`overseer`)

What `context` carries from runs OUTSIDE the window, one cut line per item, newest kept when a
section is over its cap (the rest are counted, and `where <n>` opens any run):
  • `[rejected]` items (declined-stays-declined),
  • runs carrying a `[reverted …]` note: the note and that run's `[applied]` items,
  • `model-tier-item:` lines from every run (a raise is followed up after 3 qualifying windows),
  • `model-tier:` rows of the SERIES_RUNS runs just before the window (the streak skips
    small/unmeasured rows, so it can reach past 3 runs); a ledger written before rows were
    tagged gives the first line under a heading that names `model-tier` instead.

Contract (design/guild/10-ledger-hygiene.md):
  • A run is a level-2 heading with nothing before its `evolve #<n>` but an optional "Run", an
    optional date and punctuation — `## Run — evolve #7 (…)` (what evolve.md Phase 7 writes),
    `## 2026-07-24 — evolve #7`, `## 2026-07-24 · evolve #7`, `## [2026-07-24] (evolve run #7)` —
    in any order in the file, up to the next
    run heading: a level-2 section that is not a run heading (`## 감독자 회고`, `## Follow-up of
    evolve #1`) and follows a run belongs to it. Fenced code follows CommonMark — a fence
    closes only on the same character, at least as long, with nothing after it, and a backtick
    line whose info string holds a backtick opens nothing — except that a run heading always
    ends an open fence: an unclosed fence must not hide every later run.
  • next = the highest run number written in ANY level-2 heading + 1, fences or not, so a
    number the parser could not attribute is still never reused (a `warning:` line names it,
    and `where` still points at that heading).
  • Window = the newest runs by NUMBER: at most WINDOW_RUNS, at most WINDOW_CHARS characters in
    total, but never fewer than WINDOW_MIN (Phase 0 reads the last 3 runs' applied targets).
    When those minimum runs alone pass WINDOW_CHARS, `context` prints the oldest of them as an
    outline (headings and the first line of each item) until the window fits.
    On a ledger numbered 1..N without gaps this is the old "count of entries + 1", so no
    existing run is renumbered.
  • compact keeps the preamble, sections before the first run and window runs in place, moves
    the rest, and refuses to write unless every chunk it read is present exactly once in what
    it writes. A failed write puts the archive back, so a non-zero exit means nothing changed.

Exit: 0 ok · 1 `where` found nothing · 2 `where` found the number only under a heading that is
not a run heading (the range is printed; evolve treats it as a heading to fix) · 64 usage · 65 unreadable ledger / conservation failure /
failed write.
"""
import argparse
import os
import re
import stat
import sys
import tempfile
from collections import Counter

ACTIVE_REL = os.path.join(".claude", "guild", "evolution-log.md")
ARCHIVE_REL = os.path.join(".claude", "guild", "evolution-log.archive.md")
WINDOW_RUNS = 10
WINDOW_CHARS = 18000
WINDOW_MIN = 3
ITEM_CHARS = 240
SERIES_RUNS = 12
# Per carried section, in characters. With the window this keeps `context` under OUTPUT_CHARS,
# below the ~30000 characters a Bash tool result shows before it truncates.
CAPS = {"skip": 4000, "reverted": 1500, "items": 1500, "rows": 3200}
OUTPUT_CHARS = 28500

_H2 = re.compile(r"^ {0,3}##(?!#)[ \t]")
# Before the run number a run heading holds nothing but an optional "Run", an optional date and
# punctuation: `## Run — evolve #7 (…)`, `## 2026-07-24 · evolve #7`, `## [2026-07-24] (evolve #7)`,
# `## **evolve run #7**`. Anything with other words first (`## Follow-up of evolve #1`) is not.
_P = r"[ \t\[\]()*_—–:\-·|,]*"
_RUN_HEAD = re.compile(
    r"^ {0,3}##[ \t]+" + _P + r"(?:run" + _P + r")?(?:\d{4}-\d{2}-\d{2}" + _P + r")?"
    r"evolve(?:[ \t]+run)?[ \t]*#(\d+)(?!\d)(?![ \t]*[^\W\d_])", re.I)  # no word after #N
# A run-shaped heading at another level, or a bold-led run line (`### evolve #1 — …`,
# `**evolve #3** (…)`): ledgers written before the heading was fixed. Not read as runs, but their
# numbers count toward next= and are warned about, so a number is never reused.
_SHAPED = re.compile(
    r"^ {0,3}(?:#(?:#{2,5})?[ \t]+|(?:[-*+][ \t]+)?\*\*)" + _P + r"(?:run" + _P + r")?(?:\d{4}-\d{2}-\d{2}"
    + _P + r")?evolve(?:[ \t]+run)?[ \t]*#(\d+)(?!\d)(?![ \t]*[^\W\d_])", re.I)
_ANY_RUN = re.compile(r"^ {0,3}##[ \t].*?\bevolve(?:[ \t]+run)?[ \t]*#(\d+)(?!\d)", re.I)
_REVERTED = re.compile(r"^[ \t]*(?:>[ \t]*)?(?:[-*+][ \t]+)?(?:\*\*)?\[reverted", re.I)
# Heading text after `[rejected]`/`[applied]` that names no item: a count, "none", a label.
_BOILER = re.compile(r"^(?:skip-?list|없음|항목|none|이번|사람 거절|\d)", re.I)
TAGGED_CHARS = 4000
LEFT_OUT_CHARS = 1200  # facts kept for a window run left out of `context`
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]")
_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ITEM = re.compile(r"^([ \t]*)([-*+]|\d{1,3}[.)])[ \t]+")
_TABLE = re.compile(r"^[ \t]*\|")
_TABLE_RULE = re.compile(r"^[ \t]*\|?[ \t:]*-{3,}")
ARCHIVE_HEADER = (
    "# Evolution Log — archive\n\n"
    "> Runs moved out of `evolution-log.md` by `ledger.py compact` (oldest first). Nothing here is\n"
    "> read whole at runtime: `ledger.py context` re-reads the `[rejected]` skip-list from it and\n"
    "> `ledger.py where <n>` finds a run for `/gld rollback`.\n\n"
)


class LedgerError(Exception):
    pass


def repo_root():
    d = os.getcwd()
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


def read(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as e:
        raise LedgerError("cannot read %s: %s" % (path, e))


def run_number(line):
    m = _RUN_HEAD.match(line.lstrip("\ufeff"))
    return int(m.group(1)) if m else None


def lines_of(text, keepends=False):
    """Split on "\\n" only — str.splitlines also breaks on U+2028, \\x0c and others, which would
    put `where` and `lines=` off from what Read and `wc -l` count."""
    parts = text.split("\n")
    if keepends:
        out = [p + "\n" for p in parts[:-1]]
        return out + ([parts[-1]] if parts[-1] else [])
    return parts[:-1] if parts and parts[-1] == "" else parts


def code_flags(lines):
    """For each line, True when it is a fence line or inside fenced code (CommonMark)."""
    flags, fence = [], None
    for line in lines:
        bare = line.rstrip("\r\n")
        if fence is None:
            m = _OPEN.match(bare)
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = m.group(1)
                flags.append(True)
                continue
            flags.append(False)
        elif run_number(bare) is not None:  # an unclosed fence ends at the next run
            fence = None
            flags.append(False)
        else:
            flags.append(True)
            m = _OPEN.match(bare)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                    and not m.group(2).strip():
                fence = None
    return flags


def split(text):
    """Return (preamble, chunks); a chunk is [run-number-or-None, text, first-line-offset]."""
    lines = lines_of(text, keepends=True)
    preamble, chunks, cur = [], [], None
    for i, (line, code) in enumerate(zip(lines, code_flags(lines))):
        if not code and _H2.match(line.lstrip("\ufeff")):
            n = run_number(line)
            if n is not None or cur is None or cur[0] is None:
                cur = [n, [], i]
                chunks.append(cur)
            # else: an un-numbered level-2 section inside a run stays with that run
        (cur[1] if cur else preamble).append(line)
    return "".join(preamble), [[n, "".join(body), ln] for n, body, ln in chunks]


def norm(s):
    return s.rstrip("\r\n")


def cut(s, limit):
    s = s.strip()
    return s if len(s) <= limit else s[:limit - 1] + "…"


def join(pieces):
    """Concatenate, making sure every piece starts on its own line after a blank line."""
    out = ""
    for p in pieces:
        if not p:
            continue
        if out and not out.endswith("\n"):
            out += "\n"
        if out and not out.endswith("\n\n"):
            out += "\n"
        out += p
    if out and not out.endswith("\n"):
        out += "\n"
    return out


class Ledger:
    def __init__(self, root):
        self.root = root
        self.active_path = os.path.join(root, ACTIVE_REL)
        self.archive_path = os.path.join(root, ARCHIVE_REL)
        a, b = read(self.active_path), read(self.archive_path)
        self.active_lines = len(lines_of(a or ""))
        self.active_exists, self.archive_exists = a is not None, b is not None
        self.pre_a, self.chunks_a = split(a or "")
        self.pre_b, self.chunks_b = split(b or "")
        self.loose = {int(m.group(1)) for t in (a or "", b or "") for l in lines_of(t)
                      for m in [_ANY_RUN.match(l.lstrip("\ufeff"))] if m}
        self.shaped = {int(m.group(1)) for t in (a or "", b or "") for l in lines_of(t)
                       for m in [_SHAPED.match(l.lstrip("\ufeff"))] if m}

    def runs(self):
        """[(number, text, path, first-line)] for every run in both files."""
        out = []
        for path, chunks in ((self.active_path, self.chunks_a), (self.archive_path, self.chunks_b)):
            out += [(n, t, path, ln + 1) for n, t, ln in chunks if n is not None]
        return out

    def window(self):
        size = {}
        for n, t, _, _ in self.runs():
            size[n] = size.get(n, 0) + len(t)
        keep, total = [], 0
        for n in sorted(size, reverse=True):
            if len(keep) >= WINDOW_RUNS:
                break
            if len(keep) >= WINDOW_MIN and total + size[n] > WINDOW_CHARS:
                break
            keep.append(n)
            total += size[n]
        return set(keep)

    def status_lines(self):
        runs = self.runs()
        nums = sorted({n for n, _, _, _ in runs})
        win = sorted(self.window())
        last = "-"
        if nums:
            head = next(t for n, t, _, _ in runs if n == nums[-1]).split("\n", 1)[0]
            m = _DATE.search(head)
            last = m.group(0) if m else "-"
        n_arch = len({n for n, _, _ in self.chunks_b if n is not None})
        every = nums + sorted(self.loose | self.shaped)
        top = max(every) if every else 0
        lines = ["ledger: runs=%d next=%d last=%s window=%s archived=%d lines=%d" % (
            len(nums), top + 1, last,
            ("#%d-#%d" % (win[0], win[-1])) if win else "-", n_arch, self.active_lines)]
        seen = Counter(n for n, _, _, _ in runs)
        lines += ["warning: run #%d has %d entries" % (n, c) for n, c in sorted(seen.items()) if c > 1]
        # one line per kind, however many numbers — a legacy ledger must not flood `context`
        nums_s = lambda ns: ",".join("#%d" % n for n in ns[:20]) + (" …" if len(ns) > 20 else "")
        stray = sorted(self.loose - set(nums))
        shaped = sorted(self.shaped - set(nums))
        if stray:
            lines.append("warning: a level-2 heading names evolve %s but is not read as a run"
                         % nums_s(stray))
        if shaped:
            lines.append("warning: evolve %s written as a run but not as a level-2 heading — make "
                         "each `## Run — evolve #<n> (<date>)`" % nums_s(shaped))
        return lines


def section_items(text, marker):
    """One line per item of every heading that STARTS with `marker` (`[rejected]`, `[applied]`):
    each list item at the section's outermost indent (bullets or numbers), each sub-heading, each
    table row below the header — or the first non-blank line when there are none — plus every
    list item elsewhere that itself starts with `marker`. First line only, cut to ITEM_CHARS:
    this is an index; the reasoning stays in the run, which `where <n>` opens."""
    lines = lines_of(text)
    code = code_flags(lines)
    head = re.compile(r"^ {0,3}(#{1,6})[ \t]+(\*\*)?" + re.escape(marker), re.I)
    tagged = re.compile(r"^[ \t]*([-*+]|\d{1,3}[.)])[ \t]+(\*\*)?" + re.escape(marker), re.I)
    out, i = [], 1  # line 0 is the run heading
    while i < len(lines):
        h = None if code[i] else head.match(lines[i])
        if h:
            rest = re.sub(r"^[\s*_—–:\-·|,()]+", "", lines[i][h.end():]).rstrip(" *")
            level, j, body = len(h.group(1)), i + 1, []
            while j < len(lines):
                h2 = None if code[j] else _HEADING.match(lines[j])
                if h2 and len(h2.group(1)) <= level:
                    break
                body.append((lines[j], code[j]))
                j += 1
            listed = [(_ITEM.match(l), l) for l, c in body if not c and _ITEM.match(l)]
            indent = min((len(m.group(1).expandtabs(4)) for m, _ in listed), default=0)
            items, table_seen, first, para = [], False, None, None
            for l, c in body:
                if c:
                    continue
                m = _ITEM.match(l)
                if m and len(m.group(1).expandtabs(4)) == indent:
                    items.append(l[m.end():])
                elif _HEADING.match(l):
                    items.append(l)
                elif _TABLE.match(l) and not _TABLE_RULE.match(l):
                    if table_seen:
                        items.append(l)
                    table_seen = True
                elif not _TABLE.match(l):
                    table_seen = False if not l.strip() else table_seen
                if first is None and l.strip():
                    first = l
                if para is None and l.strip() and not (m or _HEADING.match(l) or _TABLE.match(l)):
                    para = l
            # `### [rejected] <theme>`: the theme is in the heading. With one line under it the two
            # make one item; over several lines the heading is its own line and every line stays
            # — whether they are `reason:`/`evidence:` fields or separate items, none is dropped.
            if rest and not _BOILER.match(rest):
                if len(items) <= 1:
                    lead = (items[0] if items else first or "").strip()
                    out.append(rest + (" — " + lead if lead else ""))
                else:  # the heading, a reason written as a paragraph, then every item
                    out += [rest] + ([para] if para and items else []) + items
            else:
                out += items or ([first] if first else [])
            i = j
            continue
        if not code[i] and tagged.match(lines[i]):
            out.append(lines[i][_ITEM.match(lines[i]).end():])
        i += 1
    return [cut(o, ITEM_CHARS) for o in out if o.strip()]


def tagged_lines(text, tag):
    """Lines that start with `<tag>:` (after an optional list marker and bold), outside code."""
    rx = re.compile(r"^[ \t]*(?:(?:[-*+]|\d{1,3}[.)])[ \t]+)?(?:\*\*)?" + re.escape(tag)
                    + r"(?:\*\*)?:", re.I)
    lines = lines_of(text)
    return [l.strip() for l, c in zip(lines[1:], code_flags(lines)[1:]) if not c and rx.match(l)]


def legacy_row(text, word):
    """Before rows were tagged: a heading that names `word`, with its first body line when the
    heading itself carries no row (`### model-tier scorecard` vs `### model-tier scorecard — …`)."""
    lines = lines_of(text)
    code = code_flags(lines)
    heads = [i for i in range(1, len(lines))
             if not code[i] and _HEADING.match(lines[i]) and word in lines[i].lower()]
    # an `[applied]` HR item may also name the word; the scorecard heading is the row
    heads.sort(key=lambda i: not re.search(r"scorecard|성적표|회고", lines[i].lower()))
    for i in heads:
        line = lines[i]
        if re.search(r"[—:]", line.lower().split(word, 1)[1]):
            return [line.strip()]
        for k in range(i + 1, len(lines)):
            if not code[k] and _HEADING.match(lines[k]):
                break
            if lines[k].strip():
                return [line.strip() + " " + lines[k].strip()]
        return [line.strip()]
    return []


def must_keep(text):
    """Lines no outline may drop: later runs act on them."""
    lines = lines_of(text)
    keep = [l for l, c in zip(lines, code_flags(lines)) if not c and _REVERTED.match(l)]
    for tag in ("model-tier", "model-tier-item", "overseer"):
        keep += tagged_lines(text, tag)
    return [cut(l, ITEM_CHARS) for l in keep]


def outline(text, width=160):
    """A run reduced to its headings, the first line of each outermost list item, its
    [rejected]/[applied] items and the lines `must_keep` names."""
    lines = lines_of(text)
    keep = []
    for l, c in zip(lines, code_flags(lines)):
        if c:
            continue
        m = _ITEM.match(l)
        if _HEADING.match(l) or (m and not m.group(1)):
            keep.append(cut(l, width))
    # What later runs act on goes right after the heading — a hard cut takes the tail — and
    # leaves the rest of the outline, so a line already in it moves up instead of staying behind.
    first = []
    for x in must_keep(text) + ["- " + y for y in section_items(text, "[rejected]")
                                + section_items(text, "[applied]")]:
        if cut(x, width) not in first:
            first.append(cut(x, width))
    moved = set(first)
    return "\n".join(keep[:1] + first + [k for k in keep[1:] if k not in moved])


def take(xs, cap):
    """The leading items of `xs` that fit in `cap` characters, and the characters they use."""
    got, used = [], 0
    for x in xs:
        if used + len(x) + 1 > cap:
            break
        got.append(x)
        used += len(x) + 1
    return got, used


def capped(items, cap):
    """Keep the newest items (the list is oldest first) within `cap` characters."""
    kept, used = [], 0
    for x in reversed(items):
        if used + len(x) + 1 > cap:
            break
        kept.append(x)
        used += len(x) + 1
    kept.reverse()
    return kept, len(items) - len(kept)


def cmd_context(led):
    out = list(led.status_lines())
    runs = sorted(led.runs(), key=lambda r: r[0])
    win = led.window()
    older = [r for r in runs if r[0] not in win]

    def section(title, items, cap):
        kept, dropped = capped(items, cap)
        more = (" — %d older not shown" % dropped) if dropped else ""
        out.append("--- %s (%d%s) ---" % (title, len(items), more))
        out.extend(kept)

    skip, rev, items, rows, reverted = [], [], [], [], set()
    for n, t, _, _ in older:
        skip += ["[evolve #%d] %s" % (n, x) for x in section_items(t, "[rejected]")]
        tl = lines_of(t)
        notes = [cut(l, ITEM_CHARS) for l, c in zip(tl, code_flags(tl)) if not c and _REVERTED.match(l)]
        if notes:
            reverted.add(n)
            rev += ["[evolve #%d] %s" % (n, x) for x in notes + section_items(t, "[applied]")]
        items += ["[evolve #%d] %s" % (n, cut(x, ITEM_CHARS)) for x in tagged_lines(t, "model-tier-item")]
    # A raise still waiting for its follow-up goes first. A later
    # `model-tier-item: <role> raise of evolve #N — follow-up done: …` line closes the raise of
    # that role in run N — only that one: a run can raise two roles.
    done_items = [x for x in items if "follow-up done" in x.lower()]
    closed = set()
    # a follow-up written in a window run closes an older raise too
    window_done = ["[evolve #%d] %s" % (n, x) for n, t, _, _ in runs if n in win
                   for x in tagged_lines(t, "model-tier-item") if "follow-up done" in x.lower()]
    for x in done_items + window_done:
        m = re.search(r"model-tier-item\W*[ \t]*(\S+)[ \t]+raise[ \t]+of[ \t]+evolve #(\d+)", x, re.I)
        if m:
            closed.add((int(m.group(2)), m.group(1).strip("`*_").lower()))

    def raise_key(x):
        run = int(re.match(r"\[evolve #(\d+)\]", x).group(1))
        m = re.search(r"model-tier-item\W*[ \t]*(\S+)[ \t]+raise\b", x, re.I)
        return run, (m.group(1).strip("`*_").lower() if m else None)

    # pending = a raise (its role parsed) that no follow-up closed and no human reverted
    open_items = [x for x in items if x not in done_items and raise_key(x)[1] is not None
                  and raise_key(x) not in closed and raise_key(x)[0] not in reverted]
    done_items = [x for x in items if x not in open_items]
    series = sorted(older, key=lambda r: r[0])[-SERIES_RUNS:]
    for n, t, _, _ in series:
        got = tagged_lines(t, "model-tier") or legacy_row(t, "model-tier")
        rows += ["[evolve #%d] %s" % (n, cut(x, ITEM_CHARS)) for x in got]
    section("skip-list from runs outside the window, first line of each item — "
            "`ledger.py where <n>` opens a run", skip, CAPS["skip"])
    section("runs a human reverted: the note and what they applied", rev, CAPS["reverted"])
    # Open raises first (newest kept within the cap), finished ones in what is left.
    order = {x: i for i, x in enumerate(items)}
    pending = {x + " (follow-up pending)": x for x in open_items}  # marked before capping
    kept_open, gone_open = capped(list(pending), CAPS["items"])
    kept_done, gone = capped(done_items, max(0, CAPS["items"] - sum(len(x) + 1 for x in kept_open)))
    out.append("--- model-tier items from every run before the window (%d%s) ---" % (
        len(items), (" — %d older not shown" % (gone + gone_open)) if gone + gone_open else ""))
    out.extend((x + " (reverted by human)") if x not in pending and raise_key(x)[0] in reverted
               and raise_key(x)[1] is not None else x
               for x in sorted(kept_open + kept_done, key=lambda x: order[pending.get(x, x)]))
    section("model-tier rows of the %d runs before the window, oldest first" % len(series),
            rows, CAPS["rows"])
    body = [(n, norm(t)) for n, t, _, _ in runs if n in win]
    budget = OUTPUT_CHARS - len("\n".join(out)) - 200
    shown = [t for _, t in body]
    k = 0
    note = "\n(outline — `ledger.py where %d` opens the full run)"
    over = lambda: sum(len(t) + 2 for t in shown) > budget
    while over() and k < len(shown):  # oldest first; the newest goes last
        shown[k] = outline(body[k][1]) + note % body[k][0]
        k += 1
    for j in range(len(shown)):  # still over: narrower outlines, oldest first
        if not over():
            break
        shown[j] = outline(body[j][1], 80) + note % body[j][0]
    dropped = 0
    while over() and dropped < len(shown) - 1:  # still over: leave out whole runs, oldest first
        # a left-out run still says what later runs act on: tagged/[reverted] lines and its items
        t = body[dropped][1]
        # tagged/[reverted] lines first; then applied targets and declined items share what is
        # left half and half (either list can run long, and Phase 0 needs both), unused half
        # going to the other
        unmark = lambda x, m: re.sub(r"^(\*\*)?" + re.escape(m) + r"(\*\*)?[ \t]*", "", x, flags=re.I)
        app = [cut("- [applied] " + unmark(x, "[applied]"), 160) for x in section_items(t, "[applied]")]
        rej = [cut("- [rejected] " + unmark(x, "[rejected]"), 160) for x in section_items(t, "[rejected]")]
        mk = [cut(x, 160) for x in must_keep(t)]
        keep, _ = take(mk, LEFT_OUT_CHARS)  # capped too
        room = max(0, LEFT_OUT_CHARS - sum(len(x) + 1 for x in keep))


        a1, ua = take(app, room // 2)
        r1, ur = take(rej, room - ua)
        a1, _ = take(app, room - ur)
        kept = keep + a1 + r1
        left = len(mk) - len(keep) + len(app) - len(a1) + len(rej) - len(r1)
        if left:
            kept.append("… %d more" % left)
        shown[dropped] = "\n".join(["(run #%d left out — `ledger.py where %d` opens it; what later runs need:)"
                                    % (body[dropped][0], body[dropped][0])] + kept)
        dropped += 1
    out.append("--- runs in the window, oldest first%s ---" % (
        (" (the oldest %d as outlines)" % k) if k else ""))
    for t in shown:
        out.append(t)
        out.append("")
    text = "\n".join(out)
    if len(text) > OUTPUT_CHARS:  # only the newest run's outline is left and it alone is too long
        text = text[:OUTPUT_CHARS] + "\n… (cut at %d characters — `ledger.py where <n>` opens a run)" % OUTPUT_CHARS
    print(text)
    return 0


LEGACY = {"overseer": ("overseer", "감독자")}


def legacy_lines(text, words):
    """Before lines were tagged: a heading or a bold label that names one of `words`."""
    for w in words:
        got = legacy_row(text, w)
        if got:
            return [cut(x, 600) for x in got]
    lines = lines_of(text)
    rx = re.compile(r"^[ \t]*(?:[-*+][ \t]+)?\*\*[^*]*(?:%s)" % "|".join(map(re.escape, words)), re.I)
    return [cut(l, 600) for l, c in zip(lines, code_flags(lines)) if not c and rx.match(l)]


def cmd_tagged(led, tag):
    """The `<tag>:` lines of the newest WINDOW run that has any — e.g. `overseer`. A lesson an
    older run recorded and later runs dropped is not brought back. Ledgers written before the
    tag fall back to a heading or bold label naming it (LEGACY)."""
    win = led.window()
    inside = sorted((r for r in led.runs() if r[0] in win), key=lambda r: -r[0])
    # the fallback is for ledgers written before the tag; once any window run uses it, only tags count
    legacy = not any(tagged_lines(t, tag) for _, t, _, _ in inside)
    for n, t, _, _ in inside:
        got = tagged_lines(t, tag) or (legacy_lines(t, LEGACY.get(tag, ())) if legacy else [])
        if got:
            kept, used = [], 0
            for x in got:
                if used + len(x) + 1 > TAGGED_CHARS:
                    kept.append("… %d more — `ledger.py where %d` opens the run" % (len(got) - len(kept), n))
                    break
                kept.append(x)
                used += len(x) + 1
            print("[evolve #%d]" % n)
            print("\n".join(kept))
            return 0
    print("none")
    return 0


def atomic_write(path, text):
    d = os.path.dirname(path)
    mode = stat.S_IMODE(os.stat(path).st_mode) if os.path.exists(path) else None
    fd, tmp = tempfile.mkstemp(prefix=".ledger-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if mode is None:  # mkstemp makes 0600; give a new file the umask default instead
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def cmd_compact(led):
    rel_a, rel_b = ACTIVE_REL, ARCHIVE_REL
    if not led.active_exists:
        print("compact: no ledger — nothing to move")
        return 0
    win = led.window()
    stay = [c for c in led.chunks_a if c[0] is None or c[0] in win]
    move = [c for c in led.chunks_a if c[0] is not None and c[0] not in win]
    if not move:
        print("compact: moved=0")
        print("stage: " + rel_a)
        return 0
    have = {norm(t) for n, t, _ in led.chunks_b if n is not None}
    fresh = [c for c in move if norm(c[1]) not in have]  # already archived by an interrupted run
    archived = [c for c in led.chunks_b if c[0] is not None] + fresh
    order = {id(c): k for k, c in enumerate(archived)}
    archived.sort(key=lambda c: (c[0], order[id(c)]))
    other_b = [c for c in led.chunks_b if c[0] is None]
    new_b = join([led.pre_b if led.archive_exists else ARCHIVE_HEADER]
                 + [t for _, t, _ in other_b] + [t for _, t, _ in archived])
    new_a = join([led.pre_a] + [t for _, t, _ in stay])
    # Conservation: every chunk read is written exactly once — except a moved run whose identical
    # copy is already in the archive (an interrupted compact), which is written once, not twice.
    before = Counter(norm(t) for _, t, _ in led.chunks_a + led.chunks_b)
    fresh_ids = {id(c) for c in fresh}
    before.subtract(norm(c[1]) for c in move if id(c) not in fresh_ids)
    pa, ca = split(new_a)
    pb, cb = split(new_b)
    after = Counter(norm(t) for _, t, _ in ca + cb)
    if +before != +after or norm(pa) != norm(led.pre_a):
        raise LedgerError("conservation check failed — nothing was written")
    old_b = read(led.archive_path)
    try:
        atomic_write(led.archive_path, new_b)
        atomic_write(led.active_path, new_a)
    except OSError as e:
        # Put the archive back, so a failed compact leaves both files as they were — evolve then
        # commits without it, and the next run's clean-tree gate finds nothing left behind.
        try:
            if old_b is None:
                os.unlink(led.archive_path)
            else:
                atomic_write(led.archive_path, old_b)
        except OSError as e2:
            raise LedgerError("cannot write the ledger: %s, and the archive could not be put back "
                              "(%s) — %s is changed: restore it with `git checkout HEAD -- %s`, or "
                              "delete it if it is untracked" % (e, e2, rel_b, rel_b))
        raise LedgerError("cannot write the ledger: %s — nothing was moved" % e)
    print("compact: moved=%d (%s) archive=%s" % (
        len(move), ",".join("#%d" % c[0] for c in sorted(move, key=lambda c: c[0])), rel_b))
    print("stage: %s %s" % (rel_a, rel_b))
    return 0


def cmd_where(led, n):
    hits = []
    for path, chunks in ((led.active_path, led.chunks_a), (led.archive_path, led.chunks_b)):
        for m, t, ln in chunks:
            if m == n:
                body = lines_of(norm(t))
                hits.append("%s:%d-%d" % (os.path.relpath(path, led.root), ln + 1, ln + len(body)))
    loose = not hits
    if loose:  # a heading not in the run shape still names the number: point at it (exit 2)
        for path in (led.active_path, led.archive_path):
            text = read(path) or ""
            ls = lines_of(text)
            for i, l in enumerate(ls):
                m = _ANY_RUN.match(l.lstrip("\ufeff"))
                if m and int(m.group(1)) == n:
                    end = next((k for k in range(i + 1, len(ls)) if _H2.match(ls[k])), len(ls))
                    while end - 1 > i and not ls[end - 1].strip():
                        end -= 1
                    hits.append("%s:%d-%d" % (os.path.relpath(path, led.root), i + 1, end))
    for h in hits:
        print(h)
    return 1 if not hits else (2 if loose else 0)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ledger.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=("status", "context", "compact", "where", "tagged"))
    ap.add_argument("arg", nargs="?", help="run number (where) · tag (tagged)")
    ap.add_argument("--root", help="repo root (default: nearest directory holding .git)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 64 if e.code else 0
    takes = args.mode in ("where", "tagged")
    if takes != (args.arg is not None) or (args.mode == "where" and not args.arg.isdigit()) or (
            args.mode == "tagged" and not re.match(r"^[a-z][a-z-]*$", args.arg)):
        sys.stderr.write("ledger.py: `where <run-number>` and `tagged <tag>` take one argument; "
                         "other modes take none\n")
        return 64
    root = os.path.abspath(args.root) if args.root else repo_root()
    try:
        led = Ledger(root)
        if args.mode == "status":
            print("\n".join(led.status_lines()))
            return 0
        if args.mode == "context":
            return cmd_context(led)
        if args.mode == "compact":
            return cmd_compact(led)
        if args.mode == "tagged":
            return cmd_tagged(led, args.arg)
        return cmd_where(led, int(args.arg))
    except LedgerError as e:
        sys.stderr.write("ledger.py: %s\n" % e)
        return 65


if __name__ == "__main__":
    sys.exit(main())
