"""guildcore.records.loopback — `<!-- guild:loopback -->`, the cumulative loop-back record.

Grammar (H§B "Loop-back record — active blocks", C §4.2): headings at column 0 are exactly
`### loopback <n>` (`^### loopback [0-9]+$`) or `### loopback-reset` (`^### loopback-reset$`);
keys `from: at: branch: reason: signature: decided: override: consumed: by:` at line start.
Never count by the prefix `### loopback` — it matches a reset too. Active blocks = the numbered
blocks after the last reset. `<n>` of a new block = all numbered headings + 1 (an id only).
"""

import re

from guildcore.records import markers

NAME = "loopback"
CAP = 2  # H§H verify row: "this row defines the cap; every other file says <cap>"
HEADING_RE = re.compile(r"^### loopback( [0-9]+|-reset)$")
NUMBERED_RE = re.compile(r"^### loopback ([0-9]+)$")
TAIL_RE = re.compile(r"^" + re.escape(markers.close_tag(NAME)))
FROM_VALUES = ("test", "qa", "leader")


def signature_set(sig):
    """Compared on the UNESCAPED form: a stored signature had its marker text neutralized at
    render, the caller's raw one did not (K0-m17)."""
    return frozenset(s.strip() for s in markers.unescape(sig).split(",") if s.strip())


class LoopbackRecord(object):
    def __init__(self, doc, comment_id=None):
        self.doc = doc
        self.comment_id = comment_id

    @classmethod
    def parse(cls, body, comment_id=None):
        return cls(markers.BlockDoc.parse(body, HEADING_RE, TAIL_RE), comment_id)

    def render(self):
        return self.doc.render()

    @property
    def blocks(self):
        return self.doc.blocks

    def numbered(self):
        return [b for b in self.blocks if NUMBERED_RE.match(markers.clean(b.heading))]

    def active(self):
        last_reset = -1
        for i, b in enumerate(self.blocks):
            if markers.clean(b.heading) == "### loopback-reset":
                last_reset = i
        return [b for b in self.blocks[last_reset + 1:] if NUMBERED_RE.match(markers.clean(b.heading))]

    def latest_active(self):
        act = self.active()
        return act[-1] if act else None

    def next_n(self):
        return len(self.numbered()) + 1

    def not_yet_handled(self):
        lat = self.latest_active()
        return lat is not None and not lat.has("consumed")

    def cap_reached(self, cap=CAP):
        return len(self.active()) >= cap

    def stagnant_with(self, signature, from_):
        """H§B step 3 reading: a non-empty signature wholly contained in the signature of the
        latest active block with the same `from`. Returns that block's n, or None. An empty
        signature is the [J:STAG-REASON] judgment — not decided here (returns None)."""
        sig = signature_set(signature)
        if not sig:
            return None
        for b in reversed(self.active()):
            if b.get("from") == from_:
                if sig <= signature_set(b.get("signature")):
                    return int(NUMBERED_RE.match(markers.clean(b.heading)).group(1))
                return None
        return None

    def summary(self):
        lat = self.latest_active()
        return {"active": len(self.active()), "total": len(self.numbered()),
                "latest_from": lat.get("from") if lat else None,
                "latest_reason": lat.get("reason") if lat else None,
                "not_yet_handled": self.not_yet_handled()}


def from_comments(comments):
    c = markers.find(comments, NAME, pick="lowest")
    if c is None:
        return None
    return LoopbackRecord.parse(markers.body_of(c), c.get("id"))


def render_block(n, from_, at, branch, reason, signature, decided=None, override=None):
    """One new block (H§B step 5). `reason` is redacted (INV5); keys stay ASCII."""
    if from_ not in FROM_VALUES:
        raise ValueError("from must be one of %s" % (FROM_VALUES,))
    sig = signature if isinstance(signature, str) else ",".join(sorted(signature))
    if markers.has_marker_text(branch):          # a machine field read back by execute (K0-m17)
        raise ValueError("branch carries Guild marker text")
    lines = ["### loopback %d" % n, "from: %s" % from_, "at: %s" % at,
             "branch: %s" % " ".join((branch or "").split()),
             "reason: %s" % " ".join((reason or "").split()), "signature: %s" % " ".join(sig.split())]
    if decided:
        lines.append("decided: %s" % decided)
    if override:
        lines.append("override: %s" % override)
    return markers.assert_own_markers(markers.finish("\n".join(lines)))


def render_reset(at, by="human"):
    return markers.assert_own_markers(markers.finish("\n".join(["### loopback-reset", "at: %s" % at, "by: %s" % by])))


def render_new_record(block_text):
    return markers.assert_own_markers("\n".join([markers.open_tag(NAME), block_text, markers.close_tag(NAME)]), NAME)


def append(body, block_text):
    """Body with `block_text` inserted immediately before the closing marker."""
    rec = LoopbackRecord.parse(body)
    if not rec.doc.tail:
        raise ValueError("loop-back record has no closing marker")
    rec.doc.insert(block_text)
    return rec.render()
