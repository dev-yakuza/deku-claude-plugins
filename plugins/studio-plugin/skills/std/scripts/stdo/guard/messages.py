"""Deny messages (m0d1b-plan §7). English: the model reads them and tells the person."""

INV9 = ("Stop: do not reach the same effect another way (INV9). Tell the user what was refused and why, "
        "and ask how to proceed.")
LIMIT = 1000

SNAPSHOT_NOTES = {"snapshot-unavailable": "unavailable", "snapshot-truncated": "not all read",
                  "snapshot-format-unrecognized": "format not recognized"}


class Deny(object):
    def __init__(self, rule, text, sources=()):
        self.rule, self.text, self.sources = rule, text, list(sources)

    def message(self, more=0):
        body = "Studio guard [%s]: %s" % (self.rule, self.text)
        if more:
            body += " (and %d more)" % more
        for s in self.sources:
            body += " " + s
        if len(body) > LIMIT - len(INV9) - 2:
            body = body[:LIMIT - len(INV9) - 6] + " ..."
        return body + "\n" + INV9

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
