"""workflows.dev.escalation — the L0-ESCALATE cap and the repeat rule of design §4.2 / §4.3 (K6 item 14).

The engine has no G-ESCALATE judge wired (decision: every unknown state and engine FAIL pauses for a person — the
conservative end of the §4.1 ladder; `conservative.NOT_GATED["ESCALATE"]`). The cap still holds on the record:
* every escalation (an `engine unknown state` / `engine FAIL` defect) is journaled as an `mj` entry
  `point: G-ESCALATE` with the hash of its step id and its one-line state (`sig`) — never stderr or journal text
  (CR-M5);
* the count resets on every human decision (`journal.bump_epoch`, CR-m11);
* the 4th escalation in one epoch is `defect: escalation cap reached — …` (3 / Issue);
* the same (step, state) again in the epoch is marked `repeated` (an immediate pause — it always is here).
A future G-ESCALATE judge reads `allowed(journal)` before it may act instead of pausing.
"""

import hashlib
import re

CAP = 3


def _sig(step, line):
    norm = re.sub(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{7,40}\b|\b\d+\b", "#", " ".join(str(line or "").split()).lower())
    return hashlib.sha256(("%s\0%s" % (step, norm)).encode("utf-8")).hexdigest()[:12]


def this_epoch(journal):
    out = []
    for e in (journal.entries if journal is not None else []):
        if e.get("kind") == "epoch":
            out = []
        elif e.get("kind") == "mj" and e.get("point") == "G-ESCALATE":
            out.append(e)
    return out


def allowed(journal):
    """True while an escalation may still be handled by a judge in this epoch (fewer than CAP so far)."""
    return len(this_epoch(journal)) < CAP


TRACE_CAP = 12000


def redacted_trace(tb):
    """0.102.12 (word_app #1797 `engine FAIL — TypeError — sequence item 8 …` with no traceback anywhere): the engine's own
    traceback, every line redacted on its own (a key-shaped line becomes the redaction mark, the rest stays), the
    newest frames kept when it is long."""
    if not tb:
        return None
    from guildcore.records import redact as RD
    lines = [RD.redact(ln) for ln in str(tb).rstrip("\n").split("\n")]
    text = "\n".join(lines)
    return text if len(text) <= TRACE_CAP else "…\n" + text[-TRACE_CAP:]


def note(journal, step, line, traceback=None):
    """Journal one escalation and return the pause line (`line`, or the cap / repeat form). 0.102.12: an engine FAIL
    carries its redacted traceback on the same entry (`traceback`) — the next one is diagnosable without guessing."""
    if journal is None:
        return line
    prior = this_epoch(journal)
    sig = _sig(step, line)
    repeat = any(e.get("sig") == sig for e in prior)
    extra = {"traceback": redacted_trace(traceback)} if traceback else {}
    journal.append("mj", point="G-ESCALATE", step=str(step), sig=sig, choice="pause", **extra)
    if len(prior) + 1 > CAP:
        return "escalation cap reached (%d this epoch) — %s" % (len(prior) + 1, line)
    if repeat:
        return "%s (repeated: same step and state this epoch)" % line
    return line
