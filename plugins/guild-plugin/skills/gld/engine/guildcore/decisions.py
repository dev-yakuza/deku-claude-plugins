"""guildcore.decisions — decision-log semantics shared by writers (K1+) and readers (K0).

K0 implements the read half: `DecisionLog.load`, `pending_human`, `live` (§2.5 rule 1b — the ONE
predicate both the writer and the read-only consumers use, R5C-m3), `accepted_answer` (§2.5
answer channel 1), `engine_start`, `directives`. `record/resolve` (writes) arrive in K1.
"""

from guildcore.records import answer as answer_rec
from guildcore.records import decisions as fmt
from guildcore.records import markers

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


def live(block, state, timeline, own_writes=()):
    """§2.5 rule 1b: a pending block is alive iff its `stage:` equals the derived stage AND the
    timeline has no stage-label event (labeled/unlabeled `guild:<stage>`) after its `at_server:`
    (else `at:`) other than the engine's own journaled writes. `own_writes` = iterable of
    (event, label, created_at). Returns (alive, reason)."""
    if block.get("stage") != state.stage:
        return False, "stage changed outside engine (%s → %s)" % (block.get("stage"), state.stage)
    since = block.get("at_server") or block.get("at") or ""
    own = set(tuple(w) for w in own_writes)
    for ev in timeline or []:
        kind = ev.get("event")
        if kind not in ("labeled", "unlabeled"):
            continue
        lb = _ev_label(ev)
        if lb not in STAGE_LABELS or (ev.get("created_at") or "") <= since:
            continue
        if (kind, lb, ev.get("created_at")) in own:
            continue
        return False, "stage changed outside engine (%s %s)" % (kind, lb)
    return True, None


def accepted_answer(block, comments, timeline, unattended=True, associations=DEFAULT_ASSOCIATIONS,
                    kind=None):
    """§2.5 channel 1: the first `guild-answer:` for this block passing every check, or None.
    Returns (answer|None, rejected[(answer, why)])."""
    k = int(block.id[1:]) if block.id[1:].isdigit() else block.n
    since = block.get("at_server") or block.get("at") or ""
    opts = block.options()
    kind = kind or block.get("kind")
    rejected = []
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
            elif kind in GATE_KINDS and not any(_ev_actor(ev) == a.author for ev in unlabels):
                why = "gate answer: author is not the label remover"
        if why:
            rejected.append((a, why))
            continue
        return a, rejected
    return None, rejected
