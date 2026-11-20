"""guildcore.journal — the local journal's FORMAT and read side (§2.5 rule 3, §2.7).

Location: `<git-common-dir>/guild/engine/<N>/journal.jsonl` (+ `ctx.json`), and the lock
`<git-common-dir>/guild/engine/<N>.lock` — under the common dir so a worktree's deletion does not
lose it and the main checkout and a sprint worktree see the same state.

One JSON object per line, compact, keys sorted (a stable byte form for tests):
    {"t":"<iso>","kind":"entry|intent|done|checkpoint|mj|cache|write","issue":N,…}
`entry` opens a stage entry (`entry_id`, `stage`, `worktree`, `loopback_blocks`, `audit_blocks`);
`intent`/`done` bracket a write keyed by (issue, entry_id, stage, step_id, attempt, op, target).
A torn last line (crash mid-write) is skipped and reported, never fatal.

K1 adds the WRITE side, `Journal`: every line is appended with O_APPEND + fsync (the write
protocol `intent → fsync → perform → verify → done`, §2.7), `checkpoint(ctx)` also rewrites
`ctx.json` atomically (tmp + fsync + rename), `cache_get/put` hold judge decisions keyed by the
§2.5 rule-4 key, `pid` lines journal each child process group {pid, pgid, start_time,
session_id} for the safe kill of §2.7, and `epoch()` counts human decisions (the L0-ESCALATE cap
resets at each, CR-m11). `denial` lines hold §5.1 permission denials for `dev denials`.
"""

import hashlib
import json
import os
import uuid

KINDS = ("entry", "intent", "done", "checkpoint", "mj", "cache", "write", "pid", "denial", "epoch",
         "event")
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

    def own_issues(self):
        """K4r3-B1/m5: the Issues this engine created — `{"kind":"write","op":"issue","key","number",
        "token"}` journaled the moment the create answered (or the token was found after a lost reply).
        The engine knows its own children by these numbers, never by a listing or an author association."""
        return [e for e in self.entries
                if e["kind"] == "write" and e.get("op") == "issue" and e.get("number") is not None]

    def last_checkpoint(self):
        cps = [e for e in self.entries if e["kind"] == "checkpoint"]
        return cps[-1] if cps else None


def fsync_append(path, line):
    """Append one line durably: O_APPEND write of the whole line, then fsync."""
    os.makedirs(os.path.dirname(path), exist_ok=True)  # fs-ok: engine journal under <git-common-dir>/guild/engine (no role can write there)
    data = (line.rstrip("\n") + "\n").encode("utf-8")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o644)  # fs-ok: engine journal under <git-common-dir>/guild/engine (no role can write there)
    try:
        size = os.fstat(fd).st_size
        if size and os.pread(fd, 1, size - 1) != b"\n":
            data = b"\n" + data         # a torn last line (crash mid-write) stays its own line
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)  # fs-ok: engine journal under <git-common-dir>/guild/engine (no role can write there)
    from guildcore.fsafe import tmp_name
    tmp = tmp_name(path)        # review-k6-r10 m5: unique per call (two threads never share it), short
    try:
        with open(tmp, "x", encoding="utf-8") as fh:  # fs-ok: engine-owned journal
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # fs-ok: engine-owned journal
    except BaseException:
        try:
            os.unlink(tmp)  # fs-ok: engine-owned journal (our own temp file)
        except OSError:
            pass
        raise


def cache_key(point, inputs, tier, system_schema_sha, valves, plugin):
    """§2.5 rule 4: (point, inputs, tier, sha(system parts + schema), valve snapshot, plugin)."""
    raw = json.dumps([point, inputs, tier, system_schema_sha, valves, plugin], sort_keys=True,
                     ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


_OWN_START = []


def _own_start():
    """This process's start time (`ps -o lstart`), read once per process."""
    if not _OWN_START:
        try:
            from guildcore.adapters.claude import process_start
            _OWN_START.append(process_start(os.getpid()))
        except Exception:                                    # noqa: BLE001 — a missing ps leaves it unknown
            _OWN_START.append(None)
    return _OWN_START[0]


class Journal(JournalView):
    """Append side of one Issue's journal (`<git-common-dir>/guild/engine/<N>/journal.jsonl`)."""

    def __init__(self, git_common_dir, issue, clock=None):
        self.common_dir = git_common_dir
        self.dir = issue_dir(git_common_dir, issue)
        self.path = os.path.join(self.dir, "journal.jsonl")
        self.ctx_path = os.path.join(self.dir, "ctx.json")
        self.issue = int(issue)
        self.clock = clock
        entries, torn = [], 0
        try:
            with open(self.path, encoding="utf-8") as fh:
                entries, torn = parse_lines(fh.read())
        except IOError:
            pass
        JournalView.__init__(self, entries, torn)
        # K5r2-m1: while a parent drives a child (2b), the runners' pid records are ALSO written to the child's
        # own journal — a person's `/gld dev <child>` after a parent crash reaps the orphan from J<child>
        self.pid_mirror = None

    def _now(self):
        if self.clock is not None:
            return self.clock.now()
        from guildcore.adapters.clock import Clock
        return Clock().now()

    def append(self, kind, **fields):
        fields.setdefault("issue", self.issue)
        line = render(kind, self._now(), **fields)
        fsync_append(self.path, line)
        self.entries.append(json.loads(line))
        return self.entries[-1]

    # -- stage entry (§2.7) ----------------------------------------------------------------
    def open_new_entry(self, stage, worktree, loopback_blocks, audit_blocks, head=None):
        return self.append("entry", entry_id=str(uuid.uuid4()), stage=stage, worktree=worktree,
                           loopback_blocks=int(loopback_blocks), audit_blocks=int(audit_blocks),
                           head=head)

    def entry_valid(self, stage, worktree, loopback_blocks, audit_blocks, own_loopback=0,
                    own_audit=0):
        """(valid, reason) for the open entry against the current GitHub/worktree facts:
        label stage == entry stage, worktree path equal, loop-back and audit block counts ≥ the
        entry's and every increase written by this entry (R3C-n3)."""
        e = self.open_entry()
        if e is None or not e.get("entry_id"):
            return False, "no entry"
        if e.get("stage") != stage:
            return False, "stage %s != %s" % (e.get("stage"), stage)
        if os.path.abspath(e.get("worktree") or "") != os.path.abspath(worktree or ""):
            return False, "worktree changed"
        lb0, au0 = int(e.get("loopback_blocks") or 0), int(e.get("audit_blocks") or 0)
        if loopback_blocks < lb0 or loopback_blocks - lb0 != own_loopback:
            return False, "loop-back blocks %d (entry %d, own %d)" % (loopback_blocks, lb0, own_loopback)
        if audit_blocks < au0 or audit_blocks - au0 != own_audit:
            return False, "audit blocks %d (entry %d, own %d)" % (audit_blocks, au0, own_audit)
        return True, None

    # -- write protocol --------------------------------------------------------------------
    def intent(self, entry_id, stage, step_id, attempt, op, target, **extra):
        return self.append("intent", entry_id=entry_id, stage=stage, step_id=step_id,
                           attempt=attempt, op=op, target=target, **extra)

    def done(self, intent_entry, **extra):
        f = dict((k, intent_entry.get(k)) for k in KEY_FIELDS if k != "issue")
        f.update(extra)
        return self.append("done", **f)

    def is_done(self, entry_id, stage, step_id, attempt, op, target):
        key = (self.issue, entry_id, stage, step_id, attempt, op, target)
        return any(e["kind"] == "done" and key_of(e) == key for e in self.entries)

    def verify_pending(self, verify):
        """For each intent-only write: `verify(intent) -> bool` (re-read GitHub). Landed → `done`
        is journaled; returns the intents that did NOT land (to be performed again)."""
        redo = []
        for it in self.intent_only():
            if verify(it):
                # K4r4-m1: a verifier may close the intent itself (an Issue create records its number, or
                # `abandoned`) — never a second, contradicting done
                if not any(e["kind"] == "done" and key_of(e) == key_of(it) for e in self.entries):
                    self.done(it, recovered=True)
            else:
                redo.append(it)
        return redo

    def own_write(self, op, **fields):
        """A verified write the timeline/answer readers must not mistake for a human's (K0-m10:
        label writes carry the server's timeline `event_id`; comments their `comment_id`)."""
        return self.append("write", op=op, **fields)

    def own_comment_ids(self):
        return [e.get("comment_id") for e in self.entries
                if e["kind"] == "write" and e.get("comment_id") is not None]

    # -- ctx / checkpoints -------------------------------------------------------------------
    def checkpoint(self, step_id, ctx):
        atomic_write(self.ctx_path, json.dumps(ctx, ensure_ascii=False, sort_keys=True, indent=1))
        return self.append("checkpoint", step_id=step_id)

    def load_ctx(self):
        try:
            with open(self.ctx_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (IOError, ValueError):
            return None

    # -- judge cache (§2.5 rule 4) -----------------------------------------------------------
    def cache_put(self, point, key, decision):
        return self.append("cache", point=point, key=key, decision=decision)

    def cache_get(self, point, key):
        hit = None
        for e in self.entries:
            if e["kind"] == "cache" and e.get("point") == point and e.get("key") == key:
                hit = e.get("decision")
            elif e["kind"] == "cache" and e.get("point") == point and e.get("invalidate"):
                hit = None
        return hit

    def cache_invalidate(self, point):
        return self.append("cache", point=point, invalidate=True)

    # -- processes ---------------------------------------------------------------------------
    def record_pid(self, who, pid, pgid, start_time, session_id=None):
        # K5r1-M1: the engine process that started the group (pid + its own start time) rides along — a
        # restart reaps a group only when that owner is provably dead (a crashed run), never a live run's
        rec = self.append("pid", who=who, pid=pid, pgid=pgid, start_time=start_time,
                          session_id=session_id, owner=os.getpid(), owner_start=_own_start())
        m = self.pid_mirror
        if m is not None and m is not self:
            m.append("pid", who=who, pid=pid, pgid=pgid, start_time=start_time, session_id=session_id,
                     owner=os.getpid(), owner_start=_own_start(), via=self.issue)
        return rec

    def pids(self):
        return [e for e in self.entries if e["kind"] == "pid"]

    # -- human decisions epoch (L0-ESCALATE cap, CR-m11) -------------------------------------
    def bump_epoch(self, why):
        return self.append("epoch", why=why)

    def epoch(self):
        return sum(1 for e in self.entries if e["kind"] == "epoch")

    def escalations_this_epoch(self):
        n = 0
        for e in self.entries:
            if e["kind"] == "epoch":
                n = 0
            elif e["kind"] == "mj" and e.get("point") == "G-ESCALATE":
                n += 1
        return n

    # -- permission denials (§5.1 거부되었을 때 1) ----------------------------------------------
    def record_denial(self, role, command, cls, reason_type=None):
        return self.append("denial", role=role, command=command, cls=cls, reason_type=reason_type)

    def denials(self):
        return [e for e in self.entries if e["kind"] == "denial"]
