"""guildcore.records.manual_qa — the PR body's `<!-- guild:manual-qa -->` checklist (qa.md 2.5).

    <!-- guild:manual-qa -->
    ## 사람 QA 체크리스트 (Manual Test Checklist)
    자동 테스트로 검증 불가능한 항목만 (test 스테이지가 커버하는 것은 제외):
    - [ ] <무엇을 확인하는가> — <어디서 / 어떻게>
    <!-- /guild:manual-qa -->

Spliced into the PR body in place (INV4 — everything outside the marker pair is preserved, see
`markers.splice`). Only the block is redacted, never the human's text around it (R2C-n1).
"""

import re

from guildcore.records import markers
from guildcore.records.redact import redact

NAME = "manual-qa"
HEADING = "## 사람 QA 체크리스트 (Manual Test Checklist)"
INTRO = "자동 테스트로 검증 불가능한 항목만 (test 스테이지가 커버하는 것은 제외):"
ITEM_RE = re.compile(r"^- \[( |x|X)\] (.*)$")


class Checklist(object):
    def __init__(self, block):
        self.block = block
        self.items = []
        for ln in block.split("\n"):
            m = ITEM_RE.match(markers.clean(ln))
            if m:
                self.items.append((m.group(1).lower() == "x", m.group(2)))

    def render(self):
        return self.block


def from_pr_body(body):
    """The full marker block (markers included) of a PR body, or None."""
    body = body or ""
    o, c = markers.open_tag(NAME), markers.close_tag(NAME)
    i = body.find(o)
    if i < 0:
        return None
    j = body.find(c, i)
    if j < 0:
        return None
    return Checklist(body[i:j + len(c)])


def render(items, none_line=None):
    """`items` = [str] (each `<what> — <where/how>`); `none_line` = the explicit "나머지는 자동
    테스트로 검증됨 — 사람 확인 불필요" statement qa.md requires when nothing is left out."""
    lines = [HEADING, INTRO] + ["- [ ] " + " ".join(i.split()) for i in items]
    if none_line:
        lines.append(none_line)
    return "\n".join([markers.open_tag(NAME), redact("\n".join(lines)), markers.close_tag(NAME)])


def splice(pr_body, block):
    return markers.splice(pr_body, NAME, block)
