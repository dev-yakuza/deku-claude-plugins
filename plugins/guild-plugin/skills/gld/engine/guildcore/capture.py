"""guildcore.capture — ground-truth capture, schema UNCHANGED (§8.2, A-F34, JR-M2).

Writes exactly the row `commands/atoms/capture_signal.py` writes to
`<repo>/.claude/guild/memory/ground-truth.jsonl` — `{ts, kind, issue, stage, role, area, summary,
evidence, surprise, escalated}` with the same caps (area 80, summary/evidence 200) — so evolve and
`--count` read engine captures like legacy ones. Two engine rules on top:
* `anchored=False` → NOT written (JR-M2: a capture must rest on a human act or hard evidence);
* idempotent: the key `(issue, stage, kind, role, sha1(summary + evidence))` is checked against
  the rows already in the log (no new field — the schema stays the same), so a resumed stage
  never captures twice.
`mark(issue, stage)` is `capture_signal.py --mark` (the stage-start stamp file) — called once per
NEW stage entry (§2.7), so a downgrade to 0.101.x keeps `--count --since auto` meaningful.
"""

import hashlib
import json
import os

from guildcore import journal as J

LOG_REL = os.path.join(".claude", "guild", "memory", "ground-truth.jsonl")
KINDS = ("correction", "verify-gap", "accepted-risk", "stagnation")


def log_path(root):
    return os.path.join(root, LOG_REL)


def mark_path(root, issue, stage):
    return os.path.join(os.path.dirname(log_path(root)), "stage-start", "%s-%s.txt" % (issue, stage))


def _key(issue, stage, kind, role, summary, evidence):
    h = hashlib.sha1(((summary or "") + "\x00" + (evidence or "")).encode("utf-8")).hexdigest()
    return (str(issue), stage, kind, role, h)


def entry(ts, kind, issue, stage, role, area, summary, evidence, surprise, escalated):
    return {
        "ts": ts, "kind": kind, "issue": int(issue) if str(issue).isdigit() else issue,
        "stage": stage, "role": role,
        "area": (area or "").strip()[:80] or None,
        "summary": (summary or "").strip()[:200],
        "evidence": (evidence or "").strip()[:200] or None,
        "surprise": bool(surprise), "escalated": bool(escalated),
    }


def existing_keys(root):
    keys = set()
    try:
        with open(log_path(root), encoding="utf-8") as fh:
            for ln in fh:
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                keys.add(_key(e.get("issue"), e.get("stage"), e.get("kind"), e.get("role"),
                              e.get("summary"), e.get("evidence")))
    except IOError:
        pass
    return keys


def capture(root, kind, issue, stage, role, summary, evidence=None, area=None, surprise=False,
            escalated=False, anchored=True, clock=None):
    """The written row, or None (unanchored, or already captured)."""
    if kind not in KINDS:
        raise ValueError("capture kind must be one of %s" % (KINDS,))
    if not anchored:
        return None
    from guildcore.adapters.clock import Clock
    e = entry((clock or Clock()).now(), kind, issue, stage, role, area, summary, evidence,
              surprise, escalated)
    k = _key(e["issue"], stage, kind, role, e["summary"], e["evidence"])
    if k in existing_keys(root):
        return None
    J.fsync_append(log_path(root), json.dumps(e, ensure_ascii=False))
    return e


def mark(root, issue, stage, clock=None):
    from guildcore.adapters.clock import Clock
    stamp = (clock or Clock()).now()
    J.atomic_write(mark_path(root, issue, stage), stamp + "\n")
    return stamp


def read_mark(root, issue, stage):
    try:
        with open(mark_path(root, issue, stage), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except IOError:
        return None
