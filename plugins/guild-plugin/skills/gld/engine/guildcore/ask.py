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


AFTER_REVEAL = "after-reveal"     # K6 r1 M2: `predict_first_counted: false — after-reveal …` — excluded from §9.5 wholly
INHERENT = "inherent"             # K6 r2 M1: `predict_first_counted: false — inherent: …` — the question's existence is
                                  # the recommendation; never an `ok` / candidate (a grading-sheet row instead)
OPEN = "open"                     # K6 r4 (user decision 2026-11-20): `predict_first_counted: false — open: …` — a KICKOFF /
                                  # STAKES question asked openly (never blind); a grading-sheet row instead

class Question(object):
    def __init__(self, kind, text, options, recommended=None, recommended_by=None,
                 context_lines=(), predict_first=False, point=None, refs=None, stakes=None, waits_at=None,
                 group=None, neutral=None, aliases=None, raised_by=None):
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
        # K5r3-M1: the wording used when the question is predict-first — it must not state the recommendation
        # (workflows.dev.predict.apply swaps it in); `blind_refused` = why a forced predict-first was refused
        # (the rendered text would show the recommendation) — the answer is then NOT a blind human judgment
        self.neutral = neutral
        # K5r4-M1: other names an option goes by in the judge's text (its own id, the untruncated summary) —
        # {token: [alias, …]}; the leak check treats each as that option. Never rendered.
        self.aliases = dict(aliases or {})
        self.neutralized = False
        self.blind_refused = None
        self.withheld = None              # K5r5-M1: the judge's text a blind question does not show (predict.apply)
        # K5r5-M2 (user decision 2026-11-19): who raised the question — `judge-unclear` (the judge rated it
        # undecidable), `judge-surface` (the judge asked a person), `confirm` (the engine asks although the judge was
        # sure: first-sprint confirmation, a conservative group). Only a `confirm` answer is a §9.5 candidate.
        self.raised_by = raised_by
        # K6 (items 33/40): engine-only fields the pending block carries for the engine itself (the conservative
        # gate's `cons_used` / `cons_run` — the stage run's identity on GitHub, read when the local tape is gone)
        self.extra = {}
        self.after_reveal = None          # K6 r1 M2: set by the conservative gate on a re-asked decision point
        self.inherent = None              # K6 r2 M1: set by the conservative gate for a one-option group (INHERENT)
        self.open_group = None            # K6 r4: set by predict.apply for an OPEN_GROUPS question (asked openly)

    def commitment(self):
        if self.recommended is None:
            return None
        if self.nonce is None:
            self.nonce = os.urandom(8).hex()
        return hashlib.sha256((self.recommended + self.nonce).encode("utf-8")).hexdigest()

    def pending_fields(self, stage=None, by="code"):
        f = {"point": self.point, "kind": self.kind, "refs": self.refs, "stage": stage, "by": by,
             "status": "pending-human", "question": self.text,
             "options": [o["token"] for o in self.options], "stakes": self.stakes}
        if not self.predict_first:
            f["recommended_by"] = self.recommended_by       # K5r6-m8: blind → not even the judge's tier before the answer
        if self.waits_at and self.waits_at != stage:
            f["waits_at"] = self.waits_at
        if self.group:
            f["group"] = self.group                         # §9.5 group of the recommendation (K5r5-M3 conservative path)
        if getattr(self, "irreversible", False):
            f["irreversible"] = "true"                      # §9.5 rule 2: the irreversible class (STAKES)
        if self.raised_by:
            f["raised_by"] = self.raised_by                 # K5r5-M2: who raised it — §9.5 counts only `confirm`
        for k, v in sorted((getattr(self, "extra", None) or {}).items()):
            if k not in f and v not in (None, ""):
                f[k] = v
        if self.predict_first:
            f["recommended_sha"] = self.commitment()
            f["predict_first"] = self.pf_why or "true"     # §9.5: only these answers count as a human judgment
            if getattr(self, "after_reveal", None):
                # K6 r1 M2: an earlier answer of the same decision point revealed the recommendation of that time —
                # this answer is no blind judgment (neither an `ok` nor a wrong candidate)
                f["predict_first_counted"] = "false — %s: %s" % (AFTER_REVEAL, self.after_reveal)
            elif getattr(self, "inherent", None):
                f["predict_first_counted"] = "false — %s: %s" % (INHERENT, self.inherent)
            elif getattr(self, "uncounted", None):
                f["predict_first_counted"] = "false — %s" % self.uncounted   # K5r6-M2(a)
        else:
            f["recommended"] = self.recommended
            if self.blind_refused:
                f["predict_first_refused"] = self.blind_refused   # §9.5: NOT a blind answer — never counted as one
            if getattr(self, "open_group", None):
                f["predict_first_counted"] = "false — %s: %s" % (OPEN, self.open_group)
        return f

    def event(self, qid, issue=None):
        """K5r3-M2: the event names the Issue the question belongs to — an attended parent drives its children on
        ITS event stream, so `qid` is issue-qualified (`#8/D2`) and `issue` / `id` carry the parts."""
        ev = {"qid": qualify(issue, qid), "id": qid, "issue": issue, "kind": self.kind, "question": self.text,
              "options": self.options, "context_lines": self.context_lines, "predict_first": self.predict_first}
        if not self.predict_first:
            ev["recommended"] = self.recommended
            ev["recommended_by"] = self.recommended_by
        return ev


def qualify(issue, qid):
    """`#<issue>/<D-id>` (K5r3-M2); the bare id when the Issue is unknown."""
    return "#%d/%s" % (int(issue), qid) if issue is not None and qid else qid


def parse_qid(s):
    """(issue or None, bare D-id) of `#8/D2` | `8/D2` | `D2`; ValueError on anything else."""
    import re
    m = re.match(r"^\s*(?:#?([0-9]+)/)?(D[0-9]+)\s*$", str(s or ""))
    if not m:
        raise ValueError("%r is not a question id (D<n> or #<issue>/D<n>)" % (s,))
    return (int(m.group(1)) if m.group(1) else None), m.group(2)


def journal_nonce(journal, question):
    """K1-m4 / K6 predict-first: the nonce (and the hidden recommendation) is journaled BEFORE the commitment is
    written — returns the local token that ties it to the block (`journal_qid`), or None when nothing is hidden."""
    if journal is None or not question.predict_first or question.recommended is None:
        return None
    question.commitment()
    token = os.urandom(6).hex()
    extra = {}
    w = withheld_text(question)            # K5r5-M1: the judge's text a blind question withheld, revealed after the answer
    if w:
        extra["withheld"] = w
    journal.append("event", what="predict-first-nonce", token=token, nonce=question.nonce,
                   recommended=question.recommended, **extra)
    return token


def withheld_text(q):
    """The judge's free text withheld from a blind question (`Question.withheld`, set by the predict-first
    enforcement point) as one line — journaled with the nonce, revealed in the answer's resolution block."""
    w = getattr(q, "withheld", None) or {}
    shown = dict((o["token"], o.get("label")) for o in (getattr(q, "options", None) or []))
    labels = ["%s = %s" % (o["token"], o.get("label")) for o in (w.get("labels") or [])
              if o["token"] != "stop" and o.get("label") != shown.get(o["token"])]   # K5r6-M2: the cut clauses
    parts = [w.get("question")] + list(w.get("context") or []) + list(w.get("texts") or []) + labels
    seen, out = set(), []
    for x in parts:
        x = " ".join(str(x or "").split())
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return " / ".join(out)[:600] or None


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
            events.emit("ask", clock.now(), **question.event(qid, issue))
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
            out = {"recommended": e.get("recommended"), "nonce": e.get("nonce")}
            if e.get("withheld"):
                out["revealed_question"] = e.get("withheld")        # K5r5-M1: shown only now, after the answer
            return out
    return {}


def _reveal_fields(journal, blk):
    """The reveal for a predict-first block; K5r3-m4: when the journal cannot reveal it (another clone, a crash
    between the block and `journal_qid`) the resolution says `reveal: unavailable` — §9.5 must not count it."""
    out = _reveal(journal, blk.id)
    if not out and blk.get("recommended_sha"):
        out = {"reveal": "unavailable"}
    return out


def answer(decisions, writer, issue, qid, choice, journal=None, login=None, text=None):
    """Attended `dev answer`. Returns the resolution block id. `qid` may be issue-qualified (`#8/D2`); a qualified
    id of another Issue is refused — it never lands on this Issue's question with the same number (K5r3-M2)."""
    qi, qid = parse_qid(qid)
    if qi is not None and int(qi) != int(issue):
        raise ValueError("#%d/%s belongs to #%d, not #%d" % (qi, qid, qi, int(issue)))
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
    fields.update(_reveal_fields(journal, blk))
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
    status, ans, rejected = D.accepted_answer(block, comments, timeline, unattended, associations, issue=issue)
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
        fields.update(_reveal_fields(journal, block))
        did = decisions.resolve(block.id, fields)
        if journal is not None:
            journal.bump_epoch("answer %s" % block.id)
        return "answered", did
    if status == "conflict":
        return "conflict", [a for a, why in rejected if why == "conflicting answers"]
    return "none", None
