"""Studio's ignore block (m0e-plan §3.4): the same lines in the tracked `.gitignore` and in
`$(git rev-parse --git-common-dir)/info/exclude`. The text below must stay equal to
templates/studio/gitignore.tmpl (structure_test.sh checks it)."""

import re

BEGIN = "# >>> studio (managed by /std init; edit with /std config) >>>"
END = "# <<< studio <<<"
TEMPLATE = """# >>> studio (managed by /std init; edit with /std config) >>>
/{{STUDIO_ROOT}}/local/
/.claude/studio/local/
/{{STUDIO_ROOT}}/out/
/{{STUDIO_ROOT}}/copy/
/{{STUDIO_ROOT}}/videos/*/work/
/{{STUDIO_ROOT}}/videos/*/audio/**
!/{{STUDIO_ROOT}}/videos/*/audio/*/
!/{{STUDIO_ROOT}}/videos/*/audio/*/picks.json
/{{STUDIO_ROOT}}/cast/*/work/
/{{STUDIO_ROOT}}/voices/**/candidates/
# <<< studio <<<
"""
# "# >>> studio (" — not "# >>> studio:hook" (the hook managers' block)
_BEGIN_RE = re.compile(r"^# >>> studio(\s|$)")
_END_RE = re.compile(r"^# <<< studio(\s|$)")


class BlockError(Exception):
    """Unpaired or repeated block markers."""


def render(studio_root, extra=()):
    text = TEMPLATE.replace("{{STUDIO_ROOT}}", studio_root.strip("/"))
    if extra:
        lines = text.splitlines(True)
        text = "".join(lines[:-1]) + "".join(e.rstrip("\n") + "\n" for e in extra) + lines[-1]
    return text


def span(text):
    """(start, end) line indexes of the block (end inclusive), None when absent; BlockError when broken."""
    lines = (text or "").splitlines()
    starts = [i for i, l in enumerate(lines) if _BEGIN_RE.match(l)]
    ends = [i for i, l in enumerate(lines) if _END_RE.match(l)]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise BlockError("the Studio block markers are unpaired or repeated")
    return starts[0], ends[0]


def split(text):
    """(text without the block, the block's lines) — the block is None when absent."""
    sp = span(text)
    lines = (text or "").splitlines(True)
    if sp is None:
        return "".join(lines), None
    a, b = sp
    return "".join(lines[:a] + lines[b + 1:]), "".join(lines[a:b + 1])


def ensure(text, block):
    """`text` with its Studio block replaced by (or appended as) `block`."""
    text = text or ""
    sp = span(text)
    lines = text.splitlines(True)
    if sp is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        return "".join(lines) + block
    a, b = sp
    return "".join(lines[:a]) + block + "".join(lines[b + 1:])


def ok(text, studio_root):
    """The block is present and keeps the machine-only lines."""
    try:
        _rest, block = split(text)
    except BlockError:
        return False
    if block is None:
        return False
    have = {l.strip() for l in block.splitlines()}
    return "/%s/local/" % studio_root.strip("/") in have and "/.claude/studio/local/" in have
