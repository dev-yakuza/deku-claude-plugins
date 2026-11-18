"""guildcore.pause — the unattended pause, in the order that makes a crash recoverable (§2.5, CR-M9).

    1. decision log  `pending-human` block (question, options, kind preserved) — when there is a
       question; then `at_server:` from the server's clock;
    2. `<!-- guild:needs-human -->` comment: cause line on line 2, optional directive line,
       the `guild-answer:` hint, prose; its id is added to the block as `pause_comment:`;
    3. the `guild:needs-human` label — the COMMIT POINT.
A crash between steps leaves a live pending block without the label; §2.5 rule 2(d) then
`complete()`s the pause (comment if `pause_comment` is missing, then the label) instead of
re-judging a gate no human has seen (R2C-N-M3).
Cause keys follow §4.2's pause table: `defect:` / `ambiguity:` / `env: <key> — …`.
"""

from guildcore.records import needs_human

NEEDS_HUMAN = "guild:needs-human"


class Pause(object):
    def __init__(self, cause_kind, line, prose="", env_key=None, directive_line=None):
        self.cause_kind = cause_kind
        self.line = line
        self.prose = prose
        self.env_key = env_key
        self.directive_line = directive_line


def pause(writer, decisions, issue, p, question=None, stage=None, by="code"):
    """Write a pause. `question` = ask.Question or None. Returns {did, comment_id}."""
    did = None
    cause = needs_human.cause_line(p.cause_kind, p.line, p.env_key)
    if question is not None:
        f = question.pending_fields(stage=stage, by=by)
        # K4: the cause line rides in the pending block so a resume can finish a pause that died
        # before its comment landed (§2.5 rule 2(d)) with the SAME cause, not a generic one
        f["cause"] = cause
        did = decisions.record(f)
        decisions.stamp_server_time(did)
    answer = (int(did[1:]), [o["token"] for o in question.options]) if question is not None else None
    body = needs_human.render(cause, p.prose, p.directive_line, answer)
    c = writer.create_comment(issue, body)
    if did is not None:
        decisions.amend(did, "pause_comment", c["id"])
    writer.labels_apply(issue, add=[NEEDS_HUMAN])
    return {"did": did, "comment_id": c["id"]}


def complete(writer, decisions, issue, block, p):
    """Finish a pause interrupted after step 1 or 2 (rule 2(d), no unlabel event seen)."""
    cid = block.get("pause_comment")
    comments = writer.read.comments(issue)
    if not cid or not any(str(c.get("id")) == str(cid) for c in comments):
        cause = needs_human.cause_line(p.cause_kind, p.line, p.env_key)
        body = needs_human.render(cause, p.prose, p.directive_line,
                                  (block.n, block.options()))
        cid = writer.create_comment(issue, body)["id"]
        decisions.amend(block.id, "pause_comment", cid)
    writer.labels_apply(issue, add=[NEEDS_HUMAN])
    return cid
