"""guildcore.records.audit — `<!-- guild:auditor:execute -->` (cumulative) and
`<!-- guild:auditor-violation -->` (one comment per violation, never PATCHed).

Block grammar (catalog B §1.4, H§B auditor row):
    ### audit-record <n>
    invocation: <stage-start ISO>
    head: <40 hex>                  ← C1: the engine's key; legacy blocks carry a bare SHA line
                                      or `HEAD: <sha>` (measured 0.98.7–0.99.1)
    [local-pass: <job_id>]
    [scan: none] | [findings: none]
    - <looped-back|fixed|recorded|dismissed> · <BLOCKER|MAJOR|MINOR> · <spec|standards> · <file:line> — <finding>[ — <reason>][ [id:F<k>]]
    role-axis: <role> <verdict> — <reason>
C2: ` [id:F<k>]` ends a finding line in engine output; the parser recognizes it anywhere in the
line (a legacy re-statement may move it). Token recognition mirrors sprint/retro.md's jq (`$p`,
`$s`, `$d`): up to two backticks/asterisks may wrap the token, and the legacy
`disposition: <token>` form on a non-role-axis line.
"""

import re

from guildcore.records import markers

NAME = "auditor:execute"
VIOLATION = "auditor-violation"
RESOLVED_LINE = "<!-- guild:auditor-violation:resolved -->"
TOKENS = ("looped-back", "fixed", "recorded", "dismissed")
HEADING_RE = re.compile(r"^### audit-record ([0-9]+)")
TAIL_RE = re.compile(r"^" + re.escape(markers.close_tag(NAME)))
SHA_RE = re.compile(r"^(?:(head|HEAD): )?([0-9a-f]{40})$")  # legacy: bare or `HEAD:` (0.98–0.99)
ID_RE = re.compile(r"\[id:(F[0-9]+)\]\s*$")   # K3r1-m1: the engine's line-end id …
ID_MID_RE = re.compile(r"\[id:(F[0-9]+)\](?= — )")   # … or a legacy re-statement's `[id:Fk] — <reason>` (CR-m12)
_W = "[`*]{0,2}"
TOKEN_RE = re.compile(r"^- " + _W + r"(looped-back|fixed|recorded|dismissed)" + _W + r"([^-A-Za-z0-9_]|$)")
DISP_RE = re.compile(r"disposition: " + _W + r"(looped-back|fixed|recorded|dismissed)" + _W + r"([^-A-Za-z0-9_]|$)")
ROLE_AXIS_RE = re.compile(r"^(- )?role-axis")
FINDING_RE = re.compile(r"^- (looped-back|fixed|recorded|dismissed) · (BLOCKER|MAJOR|MINOR) · "
                        r"([^ ·]+) · ([^ ]+) — (.*)$")


class Finding(object):
    def __init__(self, line):
        self.line = line
        c = markers.clean(line)
        m_id = ID_RE.search(c) or ID_MID_RE.search(c)
        self.fid = m_id.group(1) if m_id else None
        m = TOKEN_RE.match(c)
        d = None if ROLE_AXIS_RE.match(c) else DISP_RE.search(c)
        self.token = m.group(1) if m else (d.group(1) if d else None)
        self.legacy = bool(d and not m)
        f = FINDING_RE.match(ID_MID_RE.sub("", ID_RE.sub("", c)).rstrip())
        self.severity = f.group(2) if f else None
        self.axis = f.group(3) if f else None
        self.location = f.group(4) if f else None
        rest = f.group(5) if f else None
        self.text, _, self.reason = (rest or "").partition(" — ")
        self.reason = self.reason or None


class AuditBlock(object):
    def __init__(self, block):
        self.block = block
        self.n = int(HEADING_RE.match(markers.clean(block.heading)).group(1))
        self.invocation = block.get("invocation")
        self.head = None
        self.head_key = None
        for ln in block.lines:
            m = SHA_RE.match(markers.clean(ln))
            if m:
                self.head = m.group(2)
                self.head_key = m.group(1)          # "head" (C1) | "HEAD" | None (bare)
                break
        self.local_pass = block.get("local-pass")
        self.loopback = block.get("loopback")      # K3 (K2r1-m7): the loop-back number this invocation consumed
        cl = [markers.clean(x) for x in block.lines]
        self.scan_none = "scan: none" in cl
        self.findings_none = "findings: none" in cl
        self.findings = [f for f in (Finding(x) for x in block.lines) if f.token]
        self.role_axis = [x for x in cl if ROLE_AXIS_RE.match(x)]
        # K4 carry-over 6 (decision: STRICT read, detected not guessed): lines that say `looped-back`
        # but parse as no finding — a legacy free-form pending item the carry-forward cannot see
        self.unreadable_pending = [x for x in cl if re.search(r"looped[- ]back", x, re.I) and not TOKEN_RE.match(x)
                                   and not DISP_RE.search(x) and not ROLE_AXIS_RE.match(x)]


class AuditRecord(object):
    def __init__(self, doc, comment_ids=()):
        self.doc = doc
        self.comment_ids = list(comment_ids)
        self.blocks = [AuditBlock(b) for b in doc.blocks]

    @classmethod
    def parse(cls, body, comment_ids=()):
        return cls(markers.BlockDoc.parse(body, HEADING_RE, TAIL_RE), comment_ids)

    def render(self):
        return self.doc.render()

    def next_n(self):
        return len(self.blocks) + 1

    def invocations(self):
        return [b.invocation for b in self.blocks if b.invocation]

    def counts(self):
        """The retro view: records + per-token counts (strict line-start or legacy form)."""
        out = {"records": len(self.blocks)}
        for t in TOKENS:
            out[t.replace("-", "_")] = sum(1 for b in self.blocks for f in b.findings if f.token == t)
        out["clean"] = sum(1 for b in self.blocks if b.findings_none)
        out["no_scan"] = sum(1 for b in self.blocks if b.scan_none)
        return out


def all_from_comments(comments):
    """Every auditor:execute comment's record in id order — what sprint/retro.md's jq joins and
    counts (K0-m6: a duplicate comment left by a write race still counts there)."""
    return [AuditRecord.parse(markers.body_of(c), [c.get("id")])
            for c in sorted(markers.containing(comments, NAME), key=lambda c: c.get("id") or 0)]


def counts_all(comments):
    """retro's view: counts summed over every auditor:execute comment."""
    tot = {}
    for r in all_from_comments(comments):
        for k, v in r.counts().items():
            tot[k] = tot.get(k, 0) + v
    return tot


def from_comments(comments):
    """The canonical record: the lowest-id comment (§2.7). Returns None when absent. Note
    `counts()` on it is the canonical comment's view; `counts_all()` is retro's."""
    c = markers.find(comments, NAME, pick="lowest")
    if c is None:
        return None
    return AuditRecord.parse(markers.body_of(c), [c.get("id")])


def render_finding(token, severity, axis, location, text, reason=None, fid=None):
    if token not in TOKENS:
        raise ValueError("token must be one of %s" % (TOKENS,))
    def v(t):                                  # K3r1-m1: a quoted `[id:` cannot hijack identity
        return markers.value(t).replace("[id:", "[id\u200b:")
    s = "- %s · %s · %s · %s — %s" % (token, severity, axis, v(location), v(text))
    if reason:
        s += " — " + v(reason)
    if fid:
        s += " [id:%s]" % fid
    return s


def render_block(n, invocation, head, findings=(), role_axis=(), local_pass=None,
                 scan_none=False, loopback=None):
    """A new block. `findings` are rendered lines (`render_finding`); none and not scan_none →
    `findings: none`. Redacted last (INV5)."""
    if not re.match(r"^[0-9a-f]{40}$", head or ""):
        raise ValueError("head must be a full 40-hex SHA")
    lines = ["### audit-record %d" % n, "invocation: %s" % invocation, "head: %s" % head]
    if loopback is not None:
        lines.append("loopback: %d" % int(loopback))
    if local_pass:
        lines.append("local-pass: %s" % local_pass)
    if scan_none:
        lines.append("scan: none")
    elif not findings:
        lines.append("findings: none")
    lines.extend(findings)
    for ra in role_axis:                          # keep the line head, redact the value
        head, sep, rest = ra.partition(": ")
        lines.append(head + sep + markers.value(rest) if sep else markers.value(ra))
    return markers.assert_own_markers(markers.finish("\n".join(lines)))


def lint_block(block_text):
    """execute Step 4's pre-append format lint (catalog B §1.4): lines a legacy shape would
    produce. Empty list = clean."""
    rx = re.compile(r"^- (BLOCKER|MAJOR|MINOR)( |·)|disposition:|→ (looped-back|fixed|recorded|dismissed)")
    return [l for l in block_text.split("\n") if rx.search(l)]


class Violation(object):
    def __init__(self, body, comment_id=None):
        self.body = body
        self.comment_id = comment_id
        nonblank = [markers.clean(l) for l in body.split("\n") if markers.clean(l).strip()]
        # resolved by POSITION, not presence — the note's own text quotes the string
        self.resolved = bool(nonblank) and nonblank[-1] == RESOLVED_LINE


def violations(comments):
    return [Violation(markers.body_of(c), c.get("id"))
            for c in sorted(markers.containing(comments, VIOLATION), key=lambda c: c.get("id") or 0)]
