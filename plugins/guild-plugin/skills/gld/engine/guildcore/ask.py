"""guildcore.ask — human decisions surfaced as events (attended) or pauses (unattended) (§2.5–2.6).

`Question{kind, text, options[{token,label}], recommended, recommended_by, context_lines,
predict_first}`; `kind` ∈ the closed §2.6 set (records.decisions.ASK_KINDS).

* attended: the question is first written as a `pending-human` block (so `/gld resume` re-asks
  the SAME question), then an `ask` event goes to the driver. With `predict_first` the
  recommendation is withheld from the event and only `recommended_sha = sha256(token + nonce)` is
  written; the token and nonce are revealed in the answer's block (§2.6 R5J-M4).
* unattended: `guildcore.pause.pause` with the question (pending block + needs-human comment
  with the `guild-answer:` hint + label).
* `answer(qid, choice)` (attended `dev answer`): idempotent — a `resolves: D<k>` already present
  is refused; `stop` keeps `guild:needs-human`, any other token removes it (when present); every
  human decision bumps the journal epoch (L0-ESCALATE cap reset, CR-m11).
* `settle(block, comments, timeline, unattended)` (unattended resume): the answer channel of
  §2.5 via `decisions.accepted_answer`; `answered` → resolution block with `answered_by` and
  `answer_comment`; `conflict` stays pending and is surfaced again — never treated as "no
  answer" (K0-m15); rejected answers get a `rejected-answer` note block.
"""

import hashlib
import os

from guildcore import decisions as D
from guildcore.records import answer as answer_rec
from guildcore.records.decisions import ASK_KINDS

parse_guild_answer = answer_rec.parse


class Question(object):
    def __init__(self, kind, text, options, recommended=None, recommended_by=None,
                 context_lines=(), predict_first=False, point=None, refs=None, stakes=None, waits_at=None,
                 group=None):
        if kind not in ASK_KINDS:
            raise ValueError("ask kind must be one of the §2.6 set: %s" % kind)
        toks = [o["token"] for o in options]
        if not toks or len(set(toks)) != len(toks):
            raise ValueError("a question needs distinct option tokens")
        if recommended is not None and recommended not in toks:
            raise ValueError("recommended must be one of the options")
        self.kind, self.text, self.options = kind, text, list(options)
        self.recommended, self.recommended_by = recommended, recommended_by
        self.context_lines = list(context_lines)
        self.predict_first = predict_first
        self.point, self.refs, self.stakes = point or "ask:%s" % kind, refs, stakes
        # K5r2-M1: the stage the question waits at when the asking stage moves the label in the same write
        # (decisions.scope_of / live) — absent = the asking stage
        self.waits_at = waits_at
        self.group = group                # the §9.5 group the recommendation comes from (workflows.dev.predict)
        self.pf_why = None                # why predict_first is on (workflows.dev.predict.apply) — recorded
        self.nonce = None

    def commitment(self):
        if self.recommended is None:
            return None
        if self.nonce is None:
            self.nonce = os.urandom(8).hex()
        return hashlib.sha256((self.recommended + self.nonce).encode("utf-8")).hexdigest()

    def pending_fields(self, stage=None, by="code"):
        f = {"point": self.point, "kind": self.kind, "refs": self.refs, "stage": stage, "by": by,
             "status": "pending-human", "question": self.text,
             "options": [o["token"] for o in self.options], "stakes": self.stakes,
             "recommended_by": self.recommended_by}
        if self.waits_at and self.waits_at != stage:
            f["waits_at"] = self.waits_at
        if self.predict_first:
            f["recommended_sha"] = self.commitment()
            f["predict_first"] = self.pf_why or "true"     # §9.5: only these answers count as a human judgment
        else:
            f["recommended"] = self.recommended
        return f

    def event(self, qid):
        ev = {"qid": qid, "kind": self.kind, "question": self.text, "options": self.options,
              "context_lines": self.context_lines, "predict_first": self.predict_first}
        if not self.predict_first:
            ev["recommended"] = self.recommended
            ev["recommended_by"] = self.recommended_by
        return ev


def journal_nonce(journal, question):
    """K1-m4 / K6 predict-first: the nonce (and the hidden recommendation) is journaled BEFORE the commitment is
    written — returns the local token that ties it to the block (`journal_qid`), or None when nothing is hidden."""
    if journal is None or not question.predict_first or question.recommended is None:
        return None
    question.commitment()
    token = os.urandom(6).hex()
    journal.append("event", what="predict-first-nonce", token=token, nonce=question.nonce,
                   recommended=question.recommended)
    return token


def journal_qid(journal, token, qid):
    if journal is not None and token and qid:
        journal.append("event", what="predict-first-qid", token=token, qid=qid)


def surface(question, attended, decisions, events=None, clock=None, writer=None, issue=None,
            stage=None, pause_line=None, journal=None, cause=None):
    """Attended → pending block + `ask` event; unattended → pause. Returns the qid. `cause` (a rendered
    needs-human cause line) rides in the attended block too (K4r1-m1): an unattended resume that
    finds the question unanswered completes the pause with ITS cause, not a generic `defect:`."""
    # K1-m4: the nonce is journaled BEFORE the commitment is written (crash-safe reveal); the block is found
    # again by this local token
    token = journal_nonce(journal, question)
    fields = question.pending_fields(stage=stage)
    if cause:
        fields["cause"] = cause
    if attended:
        qid = decisions.record(fields)
        decisions.stamp_server_time(qid)
        journal_qid(journal, token, qid)
        if events is not None:
            events.emit("ask", clock.now(), **question.event(qid))
        return qid
    from guildcore import pause as P
    res = P.pause(writer, decisions, issue, pause_line, question=question, stage=stage)
    journal_qid(journal, token, res["did"])
    return res["did"]


def _reveal(journal, qid):
    if journal is None:
        return {}
    tokens = [e.get("token") for e in journal.entries
              if e.get("kind") == "event" and e.get("what") == "predict-first-qid" and e.get("qid") == qid]
    for e in reversed(journal.entries):
        if e.get("kind") == "event" and e.get("what") == "predict-first-nonce" and e.get("token") in tokens:
            return {"recommended": e.get("recommended"), "nonce": e.get("nonce")}
    return {}


def answer(decisions, writer, issue, qid, choice, journal=None, login=None, text=None):
    """Attended `dev answer`. Returns the resolution block id."""
    log = decisions._log()
    blk = log.by_id(qid)
    if blk is None or blk.get("status") != "pending-human":
        raise ValueError("%s is not a pending human question" % qid)
    if qid in log.resolved_ids():
        raise ValueError("%s is already answered" % qid)
    if choice not in blk.options():
        raise ValueError("%s is not one of %s" % (choice, "|".join(blk.options())))
    fields = {"point": blk.get("point"), "kind": blk.get("kind"), "stage": blk.get("stage"),
              "by": "human", "choice": choice, "answered_by": login, "reason": text}
    fields.update(_reveal(journal, qid))
    did = decisions.resolve(qid, fields)
    if choice != "stop":
        writer.labels_apply(issue, remove=["guild:needs-human"])
    if journal is not None:
        journal.bump_epoch("answer %s" % qid)
    return did


def settle(decisions, writer, issue, block, comments, timeline, unattended=True,
           associations=D.DEFAULT_ASSOCIATIONS, journal=None):
    """§2.5 channel 1 for one live pending block → ('answered', did) | ('none', None) |
    ('conflict', [answers])."""
    status, ans, rejected = D.accepted_answer(block, comments, timeline, unattended, associations)
    noted = set(str(b.get("answer_comment")) for b in decisions._log().blocks
                if b.get("point") == "rejected-answer")
    for a, why in rejected:
        if why in ("conflicting answers", "superseded by a later answer") or str(a.comment_id) in noted:
            continue
        decisions.record({"point": "rejected-answer", "by": "code", "stage": block.get("stage"),
                          "refs": block.id, "answer_comment": a.comment_id, "reason": why})
        noted.add(str(a.comment_id))
    if status == "answered":
        fields = {"point": block.get("point"), "kind": block.get("kind"),
                  "stage": block.get("stage"), "by": "human", "choice": ans.token,
                  "answered_by": ans.author, "answer_comment": ans.comment_id}
        fields.update(_reveal(journal, block.id))
        did = decisions.resolve(block.id, fields)
        if journal is not None:
            journal.bump_epoch("answer %s" % block.id)
        return "answered", did
    if status == "conflict":
        return "conflict", [a for a, why in rejected if why == "conflicting answers"]
    return "none", None
