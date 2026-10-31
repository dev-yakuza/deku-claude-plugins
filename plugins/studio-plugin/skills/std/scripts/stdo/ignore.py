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
/{{STUDIO_ROOT}}/videos/*/audio/
/{{STUDIO_ROOT}}/videos/*/CREDITS.draft.yaml
/{{STUDIO_ROOT}}/cast/*/work/
/{{STUDIO_ROOT}}/voices/**/candidates/
# <<< studio <<<
"""
# Every line a released block had (0.0.1–0.0.22 and this version), rendered like render(): `/std update` drops the
# ones this version's template no longer has and keeps any other line a person added to the block (pilot-1 P8).
# The video commit commits no picks.json and s2v rewrites it on every tts run, so the audio/ folders are ignored
# whole; M3c restores the picks.json re-include together with the video commit's allow-list.
SHIPPED = """/{{STUDIO_ROOT}}/local/
/.claude/studio/local/
/{{STUDIO_ROOT}}/out/
/{{STUDIO_ROOT}}/copy/
/{{STUDIO_ROOT}}/videos/*/work/
/{{STUDIO_ROOT}}/videos/*/audio/**
!/{{STUDIO_ROOT}}/videos/*/audio/*/
!/{{STUDIO_ROOT}}/videos/*/audio/*/picks.json
/{{STUDIO_ROOT}}/videos/*/audio/
/{{STUDIO_ROOT}}/videos/*/CREDITS.draft.yaml
/{{STUDIO_ROOT}}/cast/*/work/
/{{STUDIO_ROOT}}/voices/**/candidates/
"""
# "# >>> studio (" — not "# >>> studio:hook" (the hook managers' block)
_BEGIN_RE = re.compile(r"^# >>> studio(\s|$)")
_END_RE = re.compile(r"^# <<< studio(\s|$)")


class BlockError(Exception):
    """Unpaired or repeated block markers."""


def _lines(text):
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def shipped(studio_root):
    """SHIPPED's lines for this studio_root, stripped."""
    return _lines(SHIPPED.replace("{{STUDIO_ROOT}}", studio_root.strip("/")))


def template_lines(studio_root):
    """This version's block lines (no markers), stripped."""
    return [l for l in _lines(render(studio_root)) if not l.startswith("#")]


def outdated(block, studio_root):
    """Whether a Studio block is older than this version's (the H13 logic): a template line is missing, or a line a
    released block had and this template dropped is still there. A person's own lines never count."""
    have = set(_lines(block))
    want = set(template_lines(studio_root))
    return bool(want - have) or bool(have & (set(shipped(studio_root)) - want))


def carry(block, studio_root):
    """(kept, removed) lines of an existing block for the new one: kept — a person's lines (not this template's, not
    any release's, not `!`), in order; removed — the old lines the new block leaves out (a person's line equal to a
    released one included)."""
    want = set(template_lines(studio_root))
    ever = set(shipped(studio_root))
    kept, removed = [], []
    for l in _lines(block):
        if _BEGIN_RE.match(l) or _END_RE.match(l) or l in want:
            continue
        (removed if l in ever or l.startswith("!") else kept).append(l)
    return kept, removed


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
