"""Issue references in an Issue body (design §6.2 issue.md; stage-4 scope §2.11 H20, VB4).

Every stage: a `#N` is a reference (not `owner/repo#N`, not `&#N;`). Stage >= 4 only: a written range
(`#a~#b`, `#a-#b`, `#a–#b`, `#a~b`) also stands for the numbers between its ends (word_app / service #123:
"#102~#104" hid #103), and a number may be followed by a letter of another script — a Korean particle
(`#104이`, `#102~104가`; VZ) — where stages 1-3 need a word boundary. What a reference means (a prerequisite
or not) is never the engine's to say — the leader reads it.
"""

import re

from . import codes, defaults

REF_RE = re.compile(r"(?<![\w&/])#([0-9]+)\b")
"""Stages 1-3: a `#N` ends at a word boundary, so `#104이` (a Korean particle) is no reference there."""

_END = r"(?![0-9A-Za-z_])"
"""Stage >= 4: what may follow a number — anything but an ASCII letter, digit or `_` (`#104이`, not `#104a`)."""

REF4_RE = re.compile(r"(?<![\w&/])#([0-9]+)" + _END)

RANGE_RE = re.compile(r"(?<![\w&/])#([0-9]{1,9})(?:[~\-–]#([0-9]{1,9})|~([0-9]{1,9}))" + _END)
"""H20, no spaces. Either end may be followed by a letter of another script (`#104가`, `~104가`), never by an
ASCII letter (`#102~104a` is no range)."""


def referenced_numbers(body, own=None, stage=1):
    """Every `#N` in the body, ascending, without `own`. Stage >= 4: also every number of a range with
    a < b and b - a <= defaults.REF_RANGE_MAX; any other range gives what it gave before (its `#` ends)."""
    text = body or ""
    nums = {int(m.group(1)) for m in (REF4_RE if stage >= codes.STAGE4 else REF_RE).finditer(text)}
    if stage >= codes.STAGE4:
        for m in RANGE_RE.finditer(text):
            a, b = int(m.group(1)), int(m.group(2) or m.group(3))
            if a < b and b - a <= defaults.REF_RANGE_MAX:
                nums.update(range(a, b + 1))
    return [n for n in sorted(nums) if n != own and n > 0]
