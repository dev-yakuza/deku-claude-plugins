"""guildcore.records.prbody — PR-body sections other than manual-qa.

C14: the `## 무인 결정 로그 (GLD_UNATTENDED)` section is wrapped in
`<!-- guild:unattended-log -->` … `<!-- /guild:unattended-log -->`. A body that still has the
bare heading (0.101.x execute) is migrated ONCE on the engine's first write: the span from the
heading to the next `## ` heading, another `<!-- guild:` marker, or the end of the body is
wrapped; every byte outside that span is preserved (INV4, R3C-n5). The heading string itself is
byte-identical (§6.1 — review reads it).
"""

import re

from guildcore.records import markers

UNATTENDED = "unattended-log"
UNATTENDED_HEADING = "## 무인 결정 로그 (GLD_UNATTENDED)"
PR_SECTIONS = ("manual-qa", "auditor:pr", "visual-changes", "sprint:stack", "central-owned",
               "arch-drift", UNATTENDED)


def sections(body):
    """Which marker sections the PR body carries."""
    return {n: markers.open_tag(n) in (body or "") for n in PR_SECTIONS}


def migrate_unattended(body):
    """Wrap a bare unattended-log section in its markers. Idempotent: a body that already has
    the marker, or has no heading, is returned unchanged."""
    body = body or ""
    if markers.marker_span(body, UNATTENDED) is not None:
        return body
    lines = body.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if markers.clean(ln) == UNATTENDED_HEADING:
            start = i
            break
    if start is None:
        return body
    end = len(lines)
    fence = None
    for j in range(start + 1, len(lines)):
        c = markers.clean(lines[j])
        f = re.match(r"^\s*(```+|~~~+)", c)
        if f:                                   # a `## ` inside fenced code is no heading (K0-m7)
            mark = f.group(1)[0] * 3
            fence = None if fence and mark == fence else (fence or mark)
            continue
        if fence:
            continue
        if c.startswith("## ") or c.startswith("<!-- guild:") or c.startswith("<!-- /guild:"):
            end = j
            break
    # keep trailing blank lines of the span outside the markers
    k = end
    while k > start + 1 and not markers.clean(lines[k - 1]).strip():
        k -= 1
    out = lines[:start] + [markers.open_tag(UNATTENDED)] + lines[start:k] + \
        [markers.close_tag(UNATTENDED)] + lines[k:]
    return "\n".join(out)


def render_unattended(entries):
    """`entries` = [str] one line each (interpretation · rationale · "사람 확인 요")."""
    lines = [UNATTENDED_HEADING] + ["- " + " ".join(e.split()) for e in entries]
    return markers.assert_own_markers("\n".join([markers.open_tag(UNATTENDED), markers.finish("\n".join(lines)),
                                                  markers.close_tag(UNATTENDED)]), UNATTENDED)


def unattended_entries(body):
    inner = markers.inner(body or "", UNATTENDED)
    if inner is None:
        return None
    return [markers.clean(l)[2:] for l in inner.split("\n") if markers.clean(l).startswith("- ")]


def splice(body, name, block):
    return markers.splice(body, name, block)


HEADING_RE = re.compile(r"^## ")
