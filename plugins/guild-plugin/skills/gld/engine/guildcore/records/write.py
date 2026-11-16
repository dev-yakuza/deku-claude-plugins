"""guildcore.records.write — every GitHub write the engine makes: intent → perform → re-read → done.

`_handoff.md` Section F as code, plus the §2.7 write protocol:
* **verify, never assume** — after each write the target is RE-READ (comments / labels / PR body /
  the created Issue) and the write counts only when the re-read shows it; a call that returned
  0 but did not land is a failure (`GhWriteError(kind="terminal")` after the one retry);
* **transient** (429, 5xx, network) → ONE retry after 2 s, then verify again; **terminal**
  (404/422) and **auth** (401/403) → no retry, `GhWriteError` (auth → the caller exits 3);
* **journaled** — `intent` (fsync) before the call, `done` after the verified re-read, and a
  `write` line with the server id (comment id, timeline label event ids) so the engine's own
  writes are never read back as a human's (§2.5 신원 한계, K0-m10);
* **idempotent** — a comment upsert with an identical body is skipped; label edits are set
  differences (needs-human removed only when present); Issue creation searches for its hidden
  key first (A-F23);
* cumulative records (loopback · auditor:execute · decisions) are re-read right before the
  PATCH; if the block count moved, the insert is recomputed and retried once; the check after
  is "MY block is present" (CR-m13), not a whole-body hash.
Every body passed in was produced by a `records.*` renderer (redaction is their last step); this
module asserts line 1 is a Guild marker for every comment it creates (CR-m2).
"""

import time

from guildcore.adapters.gh import GhError, GhWriteError, classify_error
from guildcore.records import markers
from guildcore.state import label_names

RETRY_DELAY_S = 2


class GhWriter(object):
    def __init__(self, read, write, journal=None, sleep=time.sleep, key_ctx=None):
        self.read = read
        self.write = write
        self.journal = journal
        self.sleep = sleep
        # (entry_id, stage, step_id, attempt) — the journal key prefix of every write
        self.key_ctx = key_ctx or {"entry_id": None, "stage": None, "step_id": None, "attempt": 0}

    # -- plumbing ---------------------------------------------------------------------------
    def _call(self, op, fn):
        """fn() with Section F's retry rule; GhWriteError on failure."""
        try:
            return fn()
        except GhError as e:
            kind = classify_error(str(e))
            if kind != "transient":
                raise GhWriteError(op, str(e), kind)
            self.sleep(RETRY_DELAY_S)
            try:
                return fn()
            except GhError as e2:
                raise GhWriteError(op, str(e2), classify_error(str(e2)))

    def _perform(self, op, target, do, verify, **extra):
        """intent → do() → verify() (retry once if it did not land) → done."""
        it = None
        if self.journal is not None:
            it = self.journal.intent(op=op, target=str(target), **dict(self.key_ctx, **extra))
        res = self._call(op, do)
        ok = self._call(op + ":verify", lambda: verify(res))
        if not ok:
            self.sleep(RETRY_DELAY_S)
            res = self._call(op, do)
            ok = self._call(op + ":verify", lambda: verify(res))
            if not ok:
                raise GhWriteError(op, "write did not land on re-read (%s)" % target, "terminal")
        if it is not None:
            self.journal.done(it)
        return res

    def _comment(self, issue, cid):
        for c in self.read.comments(issue):
            if c.get("id") == cid:
                return c
        return None

    # -- comments ---------------------------------------------------------------------------
    def create_comment(self, issue, body):
        if markers.first_line_marker(body) is None:
            raise ValueError("an engine comment's first line must be a Guild marker (CR-m2)")
        res = self._perform("comment:create", issue,
                            lambda: self.write.create_comment(issue, body),
                            lambda r: bool(r and r.get("id")) and
                            markers.body_of(self._comment(issue, r["id"])) == body)
        if self.journal is not None:
            self.journal.own_write("comment", comment_id=res["id"], target=issue)
        return res

    def upsert_comment(self, issue, name, body, pick="lowest"):
        """The `<name>` comment (lowest id, A-F33) PATCHed to `body`, or created. Identical
        body → no write. Returns (comment_id, changed)."""
        if markers.first_line_marker(body) is None:
            raise ValueError("an engine comment's first line must be a Guild marker (CR-m2)")
        cur = markers.find(self.read.comments(issue), name, pick=pick)
        if cur is None:
            return self.create_comment(issue, body)["id"], True
        if markers.body_of(cur) == body:
            return cur["id"], False
        cid = cur["id"]
        self._perform("comment:patch", cid, lambda: self.write.patch_comment(cid, body),
                      lambda r: markers.body_of(self._comment(issue, cid)) == body)
        return cid, True

    def append_block(self, issue, name, insert, present, new_comment=None, count=None):
        """Cumulative record write. `insert(body) -> new body` (may raise ValueError("rollover"));
        `present(body) -> bool` = my block is there; `count(body) -> int` blocks before the
        write (re-checked right before the PATCH; moved → recompute, retry once);
        `new_comment() -> body` when no comment exists yet. Returns comment id."""
        for attempt in (1, 2):
            comments = self.read.comments(issue)
            cur = markers.find(comments, name, pick="lowest")
            if cur is None:
                if new_comment is None:
                    raise ValueError("no %s comment and no new_comment renderer" % name)
                return self.create_comment(issue, new_comment())["id"]
            body = markers.body_of(cur)
            if present(body):
                return cur["id"]                      # already landed (a resumed write)
            n0 = count(body) if count else None
            new = insert(body)
            again = markers.body_of(self._comment(issue, cur["id"]))
            if count and count(again) != n0:
                if attempt == 1:
                    continue                          # someone else appended: recompute once
                raise GhWriteError("comment:append", "%s changed during the write" % name, "terminal")
            cid = cur["id"]
            self._perform("comment:append", cid, lambda: self.write.patch_comment(cid, new),
                          lambda r: present(markers.body_of(self._comment(issue, cid))))
            return cid
        raise GhWriteError("comment:append", "unreachable", "terminal")

    # -- labels -----------------------------------------------------------------------------
    def labels_apply(self, issue, add=(), remove=()):
        """Set difference against the current labels; verified by re-reading the labels; the
        timeline events of this write are journaled as own writes (K0-m10). Returns
        (added, removed)."""
        cur = set(label_names(self.read.issue(issue).get("labels")))
        add = [a for a in add if a not in cur]
        remove = [r for r in remove if r in cur]       # needs-human removed only when present
        if not add and not remove:
            return [], []
        before = set(e.get("id") for e in self.read.timeline(issue))

        def verify(_r):
            now = set(label_names(self.read.issue(issue).get("labels")))
            return all(a in now for a in add) and not any(r in now for r in remove)
        self._perform("labels", issue, lambda: self.write.edit_labels(issue, add, remove), verify,
                      add=list(add), remove=list(remove))
        if self.journal is not None:
            for e in self.read.timeline(issue):
                if e.get("id") in before or e.get("event") not in ("labeled", "unlabeled"):
                    continue
                lb = (e.get("label") or {}).get("name")
                if (e["event"] == "labeled" and lb in add) or (e["event"] == "unlabeled" and lb in remove):
                    self.journal.own_write("label", event_id=e.get("id"), event=e["event"],
                                           label=lb, created_at=e.get("created_at"), target=issue)
        return add, remove

    # -- PR body (INV4) ----------------------------------------------------------------------
    def pr_body_splice(self, pr, name, block):
        """Splice one marker block of a PR body; bytes outside the markers are preserved. An
        unreadable body (two blocks, unclosed marker) raises ValueError — never written back."""
        body = self.read.pr(pr).get("body") or ""
        new = markers.splice(body, name, block)
        if new == body:
            return False
        self._perform("pr:body", pr, lambda: self.write.patch_pr_body(pr, new),
                      lambda r: (self.read.pr(pr).get("body") or "") == new)
        return True

    # -- Issues --------------------------------------------------------------------------------
    def issue_create(self, title, body, labels=(), key=None, key_kind="slice-key"):
        """Create once: the body carries `<!-- guild:<key_kind> <key> -->`; an existing Issue
        with that key is returned instead (A-F23). Returns (number, created)."""
        if key is not None:
            tag = "<!-- guild:%s %s -->" % (key_kind, key)
            if tag not in body:
                body = body.rstrip("\n") + "\n\n" + tag + "\n"
            for it in self._call("issue:search", lambda: self.read.issue_search(tag)):
                if tag in (it.get("body") or ""):
                    return int(it["number"]), False
        res = self._perform("issue:create", key or title,
                            lambda: self.write.create_issue(title, body, labels),
                            lambda r: bool(r and r.get("number")) and
                            (self.read.issue(r["number"]).get("body") or "") == body)
        return int(res["number"]), True
