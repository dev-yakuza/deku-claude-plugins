"""guildcore.decisions — decision-log semantics shared by writers (K1+) and readers (K0).

Read half (K0): `DecisionLog.load`, `pending_human`, `live` (§2.5 rule 1b — the ONE predicate
both the writer and the read-only consumers use, R5C-m3), `accepted_answer` (§2.5 answer channel
1), `engine_start`, `directives`.

Write half (K1): `DecisionWriter.record/resolve/amend`. Numbering = re-read right before the
write → `max(n)+1` → write → re-read: my `id:` is there exactly once (a racing writer that took
the same number → renumber and retry once). A body past 60,000 chars opens a rollover comment
(line 1 marker, line 2 `continued-from: <id>`). Blocks are inserted into the LAST decision
comment (highest id). After a `pending-human` block lands, its comment's server `updated_at` is
added to it as `at_server:` (§2.5 시계, R3C-n6) — answers are compared against that.
"""

from guildcore.records import answer as answer_rec
from guildcore.records import decisions as fmt
from guildcore.records import markers

from guildcore.records.decisions import ASK_KINDS

DEFAULT_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
# §2.5: kinds whose answer must come from the human who removed the label
GATE_KINDS = ("gate-inv2", "disputed-blocker", "loopback", "close-decided", "readiness",
              "premise", "auditor-violation")
STAGE_LABELS = tuple("guild:" + s for s in
                     ("analyze", "design", "execute", "test", "qa", "done", "children"))


def _ev_label(ev):
    lb = ev.get("label")
    return lb.get("name") if isinstance(lb, dict) else (lb or "")


def _ev_actor(ev):
    a = ev.get("actor")
    return a.get("login") if isinstance(a, dict) else (a or "")


class DecisionLog(object):
    def __init__(self, comments):
        self.comments = comments          # [DecisionComment] in id order
        self.blocks = sorted([b for c in comments for b in c.blocks], key=lambda b: b.n)

    @classmethod
    def load(cls, comments):
        mine = [c for c in sorted(comments, key=lambda c: c.get("id") or 0)
                if markers.first_line_marker(markers.body_of(c)) == fmt.NAME]
        return cls([fmt.DecisionComment(markers.body_of(c), c.get("id")) for c in mine])

    def __bool__(self):
        return bool(self.comments)

    __nonzero__ = __bool__

    def next_n(self):
        return max([b.n for b in self.blocks] or [0]) + 1

    def by_id(self, did):
        for b in self.blocks:
            if b.id == did:
                return b
        return None

    def resolved_ids(self):
        return set(b.get("resolves") for b in self.blocks if b.get("resolves"))

    def pending_human(self):
        done = self.resolved_ids()
        return [b for b in self.blocks if b.get("status") == "pending-human" and b.id not in done]

    def engine_start(self):
        for b in self.blocks:
            if b.get("point") == "engine-start":
                return b
        return None

    def directives(self):
        return [b for b in self.blocks if b.get("by") == "human" and b.get("point") == "directive"]


def is_gate(block, kind=None):
    """§2.5 gate kinds need "answer author = label remover". Fail CLOSED (K0-M3): a missing or
    unknown `kind:` is a gate, and so is `stakes: high` (a judgment property, not a kind)."""
    kind = kind or block.get("kind")
    return kind not in ASK_KINDS or kind in GATE_KINDS or block.get("stakes") == "high"


def live(block, state, timeline, own_writes=()):
    """§2.5 rule 1b: a pending block is alive iff its `stage:` equals the derived stage AND the
    timeline has no stage-label event (labeled/unlabeled `guild:<stage>`) after its `at_server:`
    (else `at:`) other than the engine's own journaled writes. `own_writes` = timeline event ids
    the engine journaled after its own label writes (K0-m10 — server ids, never the engine's
    clock). Returns (alive, reason)."""
    if block.get("stage") != state.stage:
        return False, "stage changed outside engine (%s → %s)" % (block.get("stage"), state.stage)
    since = block.get("at_server") or block.get("at") or ""
    own = set(own_writes)
    for ev in timeline or []:
        kind = ev.get("event")
        if kind not in ("labeled", "unlabeled"):
            continue
        lb = _ev_label(ev)
        if lb not in STAGE_LABELS or (ev.get("created_at") or "") <= since:
            continue
        if ev.get("id") is not None and ev.get("id") in own:
            continue
        return False, "stage changed outside engine (%s %s)" % (kind, lb)
    return True, None


def accepted_answer(block, comments, timeline, unattended=True, associations=DEFAULT_ASSOCIATIONS,
                    kind=None):
    """§2.5 channel 1. Returns (status, answer|None, rejected[(answer, why)]) with status
    `answered` | `none` | `conflict` (K0-m15). A `conflict` is NOT "no valid answer": rule 2(d)
    must not re-judge it — the block stays pending for a human to settle.

    Several answers can pass every check (K0-M4 — §2.5 sets no order). Then: all from ONE author
    → that author's latest answer wins (a correction), the earlier ones are rejected as
    superseded; from different authors with different tokens → no answer, every one rejected as
    `conflicting answers` (the question stays pending — a human must settle it). Different
    authors agreeing on one token → the latest is taken."""
    k = int(block.id[1:]) if block.id[1:].isdigit() else block.n
    since = block.get("at_server") or block.get("at") or ""
    opts = block.options()
    gate = is_gate(block, kind)
    rejected, passed = [], []
    unlabels = [ev for ev in timeline or [] if ev.get("event") == "unlabeled"
                and _ev_label(ev) == "guild:needs-human" and (ev.get("created_at") or "") > since]
    for a in answer_rec.from_comments(comments):
        if a.k != k:
            continue
        why = None
        if a.association not in associations:
            why = "author_association %s" % (a.association or "none")
        elif a.created_at <= since:
            why = "answer older than the question"
        elif a.token not in opts:
            why = "token not in options"
        elif unattended:
            # "그 이후" = after the question was asked (the block's at_server/at)
            if not unlabels:
                why = "guild:needs-human not removed"
            elif gate and not any(_ev_actor(ev) == a.author for ev in unlabels):
                why = "gate answer: author is not the label remover"
        if why:
            rejected.append((a, why))
            continue
        passed.append(a)
    if not passed:
        return "none", None, rejected
    passed.sort(key=lambda a: (a.created_at, a.comment_id or 0))
    authors = set(a.author for a in passed)
    tokens = set(a.token for a in passed)
    if len(authors) > 1 and len(tokens) > 1:
        return "conflict", None, rejected + [(a, "conflicting answers") for a in passed]
    return "answered", passed[-1], rejected + [(a, "superseded by a later answer") for a in passed[:-1]]


class DecisionWriter(object):
    """Writes decision blocks through a `records.write.GhWriter`."""

    def __init__(self, writer, issue, clock):
        self.w = writer
        self.issue = issue
        self.clock = clock

    def _comments(self):
        return markers.trusted(self.w.read.comments(self.issue))

    def _log(self):
        return DecisionLog.load(self._comments())

    def _last(self, log):
        return log.comments[-1] if log.comments else None

    def record(self, fields, _retry=True):
        """Write one block; returns its id `D<n>`. `fields` without `at` get the clock's now."""
        log = self._log()
        n = log.next_n()
        f = dict(fields)
        f.setdefault("at", self.clock.now())
        f["id"] = "D%d" % n
        block = fmt.render_block(n, f)
        last = self._last(log)
        did = "D%d" % n

        def mine(body):
            # MY block, not just my number: a racer may have taken D<n> with other content
            return block.rstrip("\n") in body
        if last is None:
            self.w.create_comment(self.issue, fmt.render_comment([block]))
        else:
            try:
                fmt.insert(last.body, block)
            except ValueError as e:
                if str(e) != "rollover":
                    raise
                self.w.create_comment(self.issue, fmt.render_comment([block], continued_from=last.comment_id))
            else:
                try:
                    self._append(last.comment_id, block, mine, len(last.blocks))
                except ValueError:
                    if not _retry:
                        raise
                    return self.record(fields, _retry=False)      # renumber once (§2.5)
        # verify: exactly one block with my number across the log
        after = self._log()
        dup = [b for b in after.blocks if b.n == n]
        if len(dup) != 1 or after.by_id(did) is None:
            if not _retry:
                raise ValueError("decision %s did not land uniquely" % did)
            new_id = self.record(fields, _retry=False)
            # K1-m9: my block that collided keeps its number but is marked superseded
            mine_dups = [b for b in dup if b.get("point") == f.get("point") and b.get("at") == f.get("at")]
            if mine_dups and len(dup) > 1:
                self.record({"point": "renumbered", "by": "code", "resolves": did,
                             "status": "superseded", "reason": "number race — re-recorded as %s" % new_id})
            return new_id
        return did

    def _append(self, cid, block, mine, n_blocks):
        from guildcore.adapters.gh import GhWriteError

        def body_now():
            for c in self._comments():
                if c.get("id") == cid:
                    return markers.body_of(c)
            raise GhWriteError("decisions:append", "decision comment %s vanished" % cid, "terminal")
        cur = body_now()
        if mine(cur):
            return
        if len(fmt.DecisionComment(cur).blocks) != n_blocks:
            raise ValueError("decision log moved during the write")   # caller renumbers
        n = len(fmt.DecisionComment(cur).blocks)

        def do():
            fresh = body_now()
            if mine(fresh):
                return {"id": cid}
            if len(fmt.DecisionComment(fresh).blocks) != n:
                raise ValueError("decision log moved during the write")
            return self.w.write.patch_comment(cid, fmt.insert(fresh, block))
        self.w._perform("decisions:append", cid, do, lambda r: mine(body_now()),
                        issue_n=self.issue, present=block.rstrip("\n"))

    def amend(self, did, key, value):
        """Add `key: value` to block `did` (at_server, pause_comment …) — a PATCH verified by
        re-read. The key must not exist yet (blocks are append-only otherwise)."""
        log = self._log()
        b = log.by_id(did)
        if b is None:
            raise ValueError("no decision %s" % did)
        if b.get(key) is not None:
            return False
        cid = b.comment_id
        body = [c for c in self._comments() if c.get("id") == cid][0]["body"]
        dc = fmt.DecisionComment(body)
        target = [x for x in dc.blocks if x.id == did][0]
        lines = target.block.lines
        # insert before the trailing blank line(s) of the block
        i = len(lines)
        while i > 0 and not markers.clean(lines[i - 1]).strip():
            i -= 1
        lines.insert(i, "%s: %s" % (key, fmt._value(key, value)))
        new = dc.render()

        def landed(_r):
            again = DecisionLog.load(self._comments()).by_id(did)
            return again is not None and again.get(key) == fmt._value(key, value)
        def do():
            cur = [c for c in self._comments() if c.get("id") == cid][0]["body"]
            dc2 = fmt.DecisionComment(cur)
            t2 = [x for x in dc2.blocks if x.id == did][0]
            if t2.get(key) is not None:
                return {"id": cid}
            ls = t2.block.lines
            j = len(ls)
            while j > 0 and not markers.clean(ls[j - 1]).strip():
                j -= 1
            ls.insert(j, "%s: %s" % (key, fmt._value(key, value)))
            return self.w.write.patch_comment(cid, dc2.render())
        self.w._perform("decisions:amend", "%s:%s" % (did, key), do, landed, issue_n=self.issue,
                        did=did)
        return True

    def stamp_server_time(self, did):
        b = self._log().by_id(did)
        for c in self._comments():
            if c.get("id") == b.comment_id:
                return self.amend(did, "at_server", c.get("updated_at") or c.get("created_at"))
        return False

    def resolve(self, did, fields):
        """A block that `resolves: <did>` (answer, superseded, re-judgment …)."""
        log = self._log()
        if did in log.resolved_ids():
            raise ValueError("%s is already resolved" % did)
        f = dict(fields)
        f["resolves"] = did
        return self.record(f)
