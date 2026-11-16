"""guildcore.records.decisions — the `<!-- guild:decisions -->` decision-log grammar (§2.5, C4).

    <!-- guild:decisions -->
    [continued-from: <comment id>]            ← line 2 of a rollover comment only
    <details><summary>Guild 결정 기록</summary>

    ### decision 7
    id: D7
    point: EX-ARB
    …one `key: value` per line…

    </details>
    <!-- /guild:decisions -->

Line 1 is always the marker (CR-m2). A block is inserted before `</details>`; a body that would
pass ROLLOVER_CHARS opens a new comment. Values are one line each; `reason` and `question` are
redacted (INV5). This module is grammar only — semantics (pending, live, numbering) are in
`guildcore.decisions`.
"""

import re

from guildcore.records import markers

NAME = "decisions"
SUMMARY = "<details><summary>Guild 결정 기록</summary>"
HEADING_RE = re.compile(r"^### decision ([0-9]+)[ \t]*$")   # a human's trailing blank must not hide a block (K0-m3)
TAIL_RE = re.compile(r"^</details>[ \t]*$")   # K0-m19
CONTINUED_RE = re.compile(r"^continued-from: ([0-9]+)$")
ROLLOVER_CHARS = 60000
# render order; unknown keys a later engine adds are kept on parse and rendered after these
KEY_ORDER = ("id", "point", "kind", "refs", "stage", "by", "at", "at_server", "inputs", "choice",
             "unsure", "coerced", "coerced_by", "raw_choice", "reason", "recommended",
             "recommended_by", "recommended_sha", "nonce", "stakes", "status", "question", "options",
             "resolves", "answered_by", "answer_comment", "pause_comment", "started_at_stage",
             "plugin", "arm", "experiment_id")
VALUE_CAP = 2000                 # per value — a block must fit far under GitHub's 65,536 (K0-m3)
TRUNCATED = "…(truncated)"
TOKEN_RE = re.compile(r"^[a-z0-9:_-]+$")   # the guild-answer token grammar
# §2.6 — the closed set of ask kinds; a pending-human block must name one (K0-M3)
ASK_KINDS = ("readiness", "premise", "close-decided", "interpretation-surface", "design-block",
             "leaf-split", "branch-ambiguous", "branch-blocked", "base-unusable", "loopback",
             "stagnation", "visual-env", "pending-regeneration", "pr-body-unreadable",
             "record-unreadable", "needs-context-producer-ran", "directive-out-of-scope",
             "restore-failed", "local-dev-files", "gate-inv2", "disputed-blocker",
             "dismiss-blocker", "auditor-violation", "auditor-scan-failed", "role-result-invalid",
             "diverged", "integration-gap", "integration-fix-child", "followups", "arch-drift",
             "escalation", "permission", "budget")
BY_RE = re.compile(r"^(code|human|judge:[a-z0-9.-]+|leader:[a-z0-9.-]+)$")


class DecisionBlock(object):
    def __init__(self, n, fields, block=None, comment_id=None):
        self.n = n
        self.fields = fields          # ordered [(key, value)]
        self.block = block
        self.comment_id = comment_id

    def get(self, key, default=None):
        for k, v in self.fields:
            if k == key:
                return v
        return default

    @property
    def id(self):
        return self.get("id") or "D%d" % self.n

    def options(self):
        return [o.strip() for o in (self.get("options") or "").split("|") if o.strip()]


class DecisionComment(object):
    def __init__(self, body, comment_id=None):
        self.body = body
        self.comment_id = comment_id
        self.doc = markers.BlockDoc.parse(body, HEADING_RE, TAIL_RE)
        second = markers.clean(self.doc.head[1]) if len(self.doc.head) > 1 else ""
        m = CONTINUED_RE.match(second)
        self.continued_from = int(m.group(1)) if m else None
        self.blocks = []
        for b in self.doc.blocks:
            n = int(HEADING_RE.match(markers.clean(b.heading)).group(1))
            self.blocks.append(DecisionBlock(n, b.fields(), b, comment_id))

    def render(self):
        return self.doc.render()


def _value(key, value):
    if isinstance(value, bool):
        value = "true" if value else "false"
    elif isinstance(value, (list, tuple)):
        value = ("|" if key == "options" else ",").join(str(x) for x in value)
    value = markers.finish(" ".join(str(value).split()))   # redact BEFORE capping (K0-m16)
    if len(value) > VALUE_CAP:
        value = value[:VALUE_CAP - len(TRUNCATED)] + TRUNCATED
    return value


def render_block(n, fields):
    """`fields` = dict or [(k, v)]; `None` values are dropped. Keys outside KEY_ORDER come after
    the known ones in the given order (forward-compatible)."""
    items = list(fields.items()) if isinstance(fields, dict) else list(fields)
    items = [(k, v) for k, v in items if v is not None]
    if not any(k == "id" for k, _ in items):
        items.insert(0, ("id", "D%d" % n))
    d = dict(items)
    by = d.get("by")
    if by is not None and not BY_RE.match(str(by)):
        raise ValueError("by: must be code | human | judge:<tier> | leader:<tier>")
    opts = d.get("options")
    if opts is not None:
        toks = list(opts) if isinstance(opts, (list, tuple)) else str(opts).split("|")
        if not toks or not all(TOKEN_RE.match(str(t).strip()) and not markers.has_marker_text(str(t))
                               for t in toks):
            raise ValueError("options must be guild-answer tokens [a-z0-9:_-]+ without marker text")
    if d.get("status") == "pending-human" and d.get("kind") not in ASK_KINDS:
        raise ValueError("a pending-human block needs kind: from the closed ask set (§2.6)")
    rank = {k: i for i, k in enumerate(KEY_ORDER)}
    known = sorted([kv for kv in items if kv[0] in rank], key=lambda kv: rank[kv[0]])
    extra = [kv for kv in items if kv[0] not in rank]
    keys = [k for k, _ in known + extra]
    # every value redacted+neutralized on its own, then capped (K0-M1, B1, B2, m16); the whole
    # block is checked once more and must keep every key line (K0-B2)
    body = markers.finish("\n".join("%s: %s" % (k, _value(k, v)) for k, v in known + extra))
    out = "### decision %d\n%s\n" % (n, body)
    got = [k for k, _ in markers.BlockDoc.parse(out, HEADING_RE, TAIL_RE).blocks[0].fields()]
    if got != keys:
        raise ValueError("decision block lost key lines: %s" % sorted(set(keys) - set(got)))
    return markers.assert_own_markers(out)


def render_comment(block_texts=(), continued_from=None):
    head = [markers.open_tag(NAME)]
    if continued_from is not None:
        head.append("continued-from: %d" % int(continued_from))
    head += [SUMMARY, ""]
    return markers.assert_own_markers(
        "\n".join(head + list(block_texts) + ["</details>", markers.close_tag(NAME)]), NAME)


def insert(body, block_text):
    """Body with `block_text` inserted before `</details>`; ValueError if the result would pass
    the rollover size (caller opens a `continued-from` comment instead)."""
    dc = DecisionComment(body)
    if not dc.doc.tail:
        raise ValueError("decision log has no </details> line")
    dc.doc.insert(block_text)
    out = dc.doc.render()
    if len(out) > ROLLOVER_CHARS:
        raise ValueError("rollover")
    return out
