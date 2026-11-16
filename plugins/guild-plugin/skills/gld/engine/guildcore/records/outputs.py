"""guildcore.records.outputs — stage-output markers and the few machine lines inside them.

Presence follows status.md step 2 EXACTLY: `[.comments[]?.body // ""] | join("\\n") |
test("guild:<x>")` — a regex test of the bare marker name over all bodies joined, so a body that
merely mentions `guild:qa:output` counts. That is today's behavior and the status comparison
keeps it (§6.1). Machine lines: `loopback-reason:` / `loopback-signature:` (test/qa attended,
CR-M10), `ran-at:` (qa:output, C5).
"""

import re

from guildcore.records import markers
from guildcore.records.redact import redact

STAGE_OUTPUTS = ("analyze:output", "design:output", "test-evidence:step-1", "test:output",
                 "qa:output")
STATUS_KEYS = {"analyze": "analyze:output", "design": "design:output",
               "evidence": "test-evidence:step-1", "test": "test:output", "qa": "qa:output"}
OTHER = ("children:output", "integration:output", "closed-as-decided", "loopback", "followups",
         "decisions", "needs-human", "auditor:execute", "auditor-violation", "note")


def presence(comments):
    joined = "\n".join(markers.body_of(c) for c in comments)
    out = {k: ("guild:" + v) in joined for k, v in STATUS_KEYS.items()}
    for name in OTHER:
        out[name] = markers.open_tag(name) in joined
    return out


class StageOutput(object):
    def __init__(self, name, comment):
        self.name = name
        self.comment = comment
        self.body = markers.body_of(comment)
        self.comment_id = comment.get("id")
        self.updated_at = comment.get("updated_at")
        lines = [markers.clean(l) for l in self.body.split("\n")]
        self.loopback_reason = _key(lines, "loopback-reason")
        self.loopback_signature = _key(lines, "loopback-signature")
        self.ran_at = _key(lines, "ran-at")

    def render(self):
        return self.body


def _key(lines, key):
    pre = key + ": "
    for ln in lines:
        if ln.startswith(pre):
            return ln[len(pre):]
    return None


def find(comments, name):
    """Replace-in-place outputs: the lowest id is canonical (C11)."""
    c = markers.find(comments, name, pick="lowest")
    return StageOutput(name, c) if c else None


def qa_last_ran(comments):
    """review.md Step 5 (b) via C5: `ran-at:` wins, else the qa:output comment's `updated_at` (latest)."""
    hits = markers.containing(comments, "qa:output")
    if not hits:
        return None
    latest = sorted(hits, key=lambda c: (c.get("updated_at") or "", c.get("id") or 0))[-1]
    so = StageOutput("qa:output", latest)
    return so.ran_at or so.updated_at


def render_loopback_lines(reason, signature):
    sig = signature if isinstance(signature, str) else ",".join(sorted(signature))
    return "loopback-reason: %s\nloopback-signature: %s" % (" ".join(reason.split()), sig)


def render_recheck_note(ts, green, summary):
    """C12: `/gld test N` on done records only this note (no test:output, label or loopback)."""
    return "%s\nrecheck test %s: %s — %s" % (markers.open_tag("note"), ts,
                                             "green" if green else "red", redact(" ".join(summary.split())))
