"""guildcore.journal — the local journal's FORMAT and read side (§2.5 rule 3, §2.7).

Location: `<git-common-dir>/guild/engine/<N>/journal.jsonl` (+ `ctx.json`), and the lock
`<git-common-dir>/guild/engine/<N>.lock` — under the common dir so a worktree's deletion does not
lose it and the main checkout and a sprint worktree see the same state.

One JSON object per line, compact, keys sorted (a stable byte form for tests):
    {"t":"<iso>","kind":"entry|intent|done|checkpoint|mj|cache|write","issue":N,…}
`entry` opens a stage entry (`entry_id`, `stage`, `worktree`, `loopback_blocks`, `audit_blocks`);
`intent`/`done` bracket a write keyed by (issue, entry_id, stage, step_id, attempt, op, target).
K0 only parses and renders lines; appending with fsync is K1's `Journal.intent/done`.
A torn last line (crash mid-write) is skipped and reported, never fatal.
"""

import json
import os

KINDS = ("entry", "intent", "done", "checkpoint", "mj", "cache", "write", "pid")
KEY_FIELDS = ("issue", "entry_id", "stage", "step_id", "attempt", "op", "target")


def engine_dir(git_common_dir):
    return os.path.join(git_common_dir, "guild", "engine")


def issue_dir(git_common_dir, issue):
    return os.path.join(engine_dir(git_common_dir), str(int(issue)))


def lock_path(git_common_dir, issue):
    return os.path.join(engine_dir(git_common_dir), "%d.lock" % int(issue))


def render(kind, t, **fields):
    if kind not in KINDS:
        raise ValueError("journal kind must be one of %s" % (KINDS,))
    obj = dict(fields)
    obj["kind"] = kind
    obj["t"] = t
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def key_of(obj):
    return tuple(obj.get(k) for k in KEY_FIELDS)


def parse_lines(text):
    """(entries, torn) — torn = count of unparseable lines (only a last line is expected)."""
    out, torn = [], 0
    for ln in (text or "").split("\n"):
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except ValueError:
            torn += 1
            continue
        if isinstance(obj, dict) and obj.get("kind") in KINDS:
            out.append(obj)
        else:
            torn += 1
    return out, torn


class JournalView(object):
    """Read-only view over one Issue's journal."""

    def __init__(self, entries, torn=0):
        self.entries = entries
        self.torn = torn

    @classmethod
    def read(cls, git_common_dir, issue):
        p = os.path.join(issue_dir(git_common_dir, issue), "journal.jsonl")
        try:
            with open(p, encoding="utf-8") as fh:
                return cls(*parse_lines(fh.read()))
        except IOError:
            return cls([], 0)

    def open_entry(self):
        """The latest `entry` (stage entries are never closed explicitly; a newer one supersedes)."""
        ents = [e for e in self.entries if e["kind"] == "entry"]
        return ents[-1] if ents else None

    def intent_only(self):
        """Writes with an `intent` and no matching `done` — verify on restart (§2.7)."""
        done = set(key_of(e) for e in self.entries if e["kind"] == "done")
        return [e for e in self.entries if e["kind"] == "intent" and key_of(e) not in done]

    def own_label_writes(self):
        """Timeline event ids of the engine's own label writes — excluded from `decisions.live`.
        Format decision (K0-m10): after a label write is verified, K1 journals
        `{"kind":"write","op":"label","event_id":<timeline event id>,…}`; the server id, never the
        engine's clock, is the match key."""
        return [e.get("event_id") for e in self.entries
                if e["kind"] == "write" and e.get("op") == "label" and e.get("event_id") is not None]

    def last_checkpoint(self):
        cps = [e for e in self.entries if e["kind"] == "checkpoint"]
        return cps[-1] if cps else None
