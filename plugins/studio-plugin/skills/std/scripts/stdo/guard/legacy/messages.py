# FROZEN copy of guard/messages.py at d2028cc (0.0.26) — the backstop (fix20). Do not edit; see guard/backstop.py.
"""Deny messages (m0d1b-plan §7). English: the model reads them and tells the person."""

INV9_FIRST = "Stop: do not reach the same effect another way (INV9)."
INV9 = INV9_FIRST + " Tell the user what was refused and why, and ask how to proceed."
# closing lines other than INV9 (fix-0025-plan §2): a refusal that is not a stop, and two G-EVIDENCE classes
NONSTOP = ("This is not a stop: read a file with the Read tool (offset/limit for a line range) and write or change it "
           "with Write or Edit — the guard checks those.")
REASK = INV9_FIRST + (" If the person has already answered, show the question again as the stage says and run the "
                      "command alone as your next tool call.")
LABEL = INV9_FIRST + (" The answer does not match this option exactly: if the person chose another option, follow it; "
                      "if the option you showed was spelled differently, ask again with the label the stage gives.")
# 1 000 until 0.0.24 (m0d1b-plan §7); the 0.0.25 timing sentence and the re-ask/label lines would cut the first
# missing line off a G-EVIDENCE refusal (pilot-1 P4) at 1 000
LIMIT = 1500

SNAPSHOT_NOTES = {"snapshot-unavailable": "unavailable", "snapshot-truncated": "not all read",
                  "snapshot-format-unrecognized": "format not recognized"}


class Deny(object):
    def __init__(self, rule, text, sources=(), suffix=None):
        self.rule, self.text, self.sources, self.suffix = rule, text, list(sources), suffix

    def message(self, denies=None):
        """`denies`: every deny of the call (None: this one alone). The closing line is this deny's suffix only when
        every deny shares it; otherwise INV9."""
        denies = [self] if denies is None else list(denies)
        tail = INV9
        if self.suffix and all(d.suffix == self.suffix for d in denies):
            tail = self.suffix
        body = "Studio guard [%s]: %s" % (self.rule, self.text)
        if len(denies) > 1:
            body += " (and %d more)" % (len(denies) - 1)
        for s in self.sources:
            body += " " + s
        if len(body) > LIMIT - len(tail) - 2:
            body = body[:LIMIT - len(tail) - 6] + " ..."
        return body + "\n" + tail

    def __repr__(self):
        return "Deny(%s, %r)" % (self.rule, self.text)


def alias_sources(cmd):
    out = []
    alt = getattr(cmd, "alt", None)
    for s in (alt or {}).get("source", []) or []:
        if s.get("value") is None:
            out.append('alias "%s" is not an alias in %d of %d recent shell snapshots.' % (s["name"], s["in"], s["of"]))
        else:
            rest = s["of"] - s["in"]
            out.append('alias "%s" is "%s" in %d of %d recent shell snapshots%s — write "%s" directly.'
                       % (s["name"], s["value"], s["in"], s["of"],
                          (" and differs or is absent in %d" % rest) if rest else "", s["value"]))
    return out


def snapshot_sources(notes):
    seen = []
    for n in notes or ():
        key = "snapshot-truncated" if n.startswith(("snapshot-truncated", "snapshot-unreadable")) else n
        if key in SNAPSHOT_NOTES and SNAPSHOT_NOTES[key] not in seen:
            seen.append(SNAPSHOT_NOTES[key])
    return ["(shell snapshot: %s)" % ", ".join(seen)] if seen else []
