#!/usr/bin/env python3
"""
harness_size.py — which evolve-grown files have outgrown their size bar.

Read-only. Prints one line per file over its bar, furthest over first, and nothing about the
rest, so the caller (evolve Phase 3, audit dimensions B/C) spends tokens only on what needs
densifying:

    habits <role>: count=6 chars=3331 longest=959 (bars 5 / 2000 / 800)
    index: chars=5302 (bar 4000)
    fact facts/accessibility.md: chars=18965 (bar 12000)

or the single line `harness: within bars`. Characters, not bytes: a Hangul character is three
UTF-8 bytes, and the context cost tracks characters far more closely.

The bars (design/guild/10-ledger-hygiene.md D11):
  • habits — the section below `<!-- guild:persona:habits -->` of `.claude/agents/<role>.md`,
    read on every spawn of that role: more than HABITS_MAX bullets, more than HABITS_CHARS
    characters, or one bullet longer than HABIT_LONG (twice the 400-character bar evolve applies
    to a new or rewritten habit).
  • index — `.claude/guild/knowledge/index.md`, loaded by every stage: more than INDEX_CHARS.
  • fact — any `.claude/guild/knowledge/facts/**/*.md`: more than FACT_CHARS.

Exit: 0 (also when nothing exists yet) · 64 usage.
"""
import argparse
import glob
import os
import re
import sys

HABITS_MARKER = "<!-- guild:persona:habits -->"
HABITS_MAX = 5
HABITS_CHARS = 2000
HABIT_LONG = 800
INDEX_CHARS = 4000
FACT_CHARS = 12000

_BULLET = re.compile(r"^([-*+]|\d{1,3}[.)])[ \t]+")
# the section ends at the next level-1/2 heading or a persona marker; `###` groups and other
# comments (an `<!-- init: … -->` note) stay inside it
_STOP = re.compile(r"^(#{1,2}[ \t]|<!-- guild:persona:)")
_COMMENT = re.compile(r"^[ \t]*<!--.*-->[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def repo_root():
    d = os.getcwd()
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


SKIPPED = []


def text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as e:
        SKIPPED.append("skipped %s: %s" % (path, e.__class__.__name__))
        return None


def habits(body):
    """Bullets of the topmost habits section, each with its continuation lines."""
    i = body.find(HABITS_MARKER)
    if i < 0:
        return None
    lines = body[i + len(HABITS_MARKER):].splitlines()
    out, fenced = [], False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if _STOP.match(line):
            break
        if _COMMENT.match(line) or re.match(r"^#{3,6}[ \t]", line):
            continue
        if _BULLET.match(line):
            out.append(line.strip())
        elif out and line.strip():
            out[-1] += "\n" + line.strip()
    return out


def check(root):
    del SKIPPED[:]
    lines = []
    for path in sorted(glob.glob(os.path.join(root, ".claude", "agents", "*.md"))):
        body = text(path)
        bullets = habits(body) if body is not None else None
        if not bullets:
            continue
        n, chars = len(bullets), sum(len(b) for b in bullets)
        longest = max(len(b) for b in bullets)
        over = max(n / HABITS_MAX, chars / HABITS_CHARS, longest / HABIT_LONG)
        if over > 1:
            lines.append((over, "habits %s: count=%d chars=%d longest=%d (bars %d / %d / %d)" % (
                os.path.splitext(os.path.basename(path))[0], n, chars, longest,
                HABITS_MAX, HABITS_CHARS, HABIT_LONG)))
    kdir = os.path.join(root, ".claude", "guild", "knowledge")
    index = text(os.path.join(kdir, "index.md")) if os.path.exists(os.path.join(kdir, "index.md")) else None
    if index is not None and len(index) > INDEX_CHARS:
        lines.append((len(index) / INDEX_CHARS, "index: chars=%d (bar %d)" % (len(index), INDEX_CHARS)))
    for path in sorted(glob.glob(os.path.join(kdir, "facts", "**", "*.md"), recursive=True)):
        body = text(path)
        if body is not None and len(body) > FACT_CHARS:
            lines.append((len(body) / FACT_CHARS, "fact %s: chars=%d (bar %d)" % (
                os.path.relpath(path, kdir).replace(os.sep, "/"), len(body), FACT_CHARS)))
    # Furthest over its bar first: evolve takes the head of this list, not all of it.
    return [line for _, line in sorted(lines, key=lambda x: -x[0])]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="harness_size.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", help="repo root (default: nearest directory holding .git)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 64 if e.code else 0
    lines = check(os.path.abspath(args.root) if args.root else repo_root())
    print("\n".join(lines) if lines else "harness: within bars")
    for s in SKIPPED:  # stderr, so an unreadable file never takes one of evolve's first lines
        sys.stderr.write(s + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
