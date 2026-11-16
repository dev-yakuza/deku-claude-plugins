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

import hashlib
import time

from guildcore.adapters.gh import GhError, GhWriteError, classify_error
from guildcore.records import markers
from guildcore.state import label_names

RETRY_DELAY_S = 2
VERIFY_READS = 3


def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class GhWriter(object):
    def __init__(self, read, write, journal=None, sleep=time.sleep, key_ctx=None):
        self.read = read
        self.write = write
        self.journal = journal
        self.sleep = sleep
        # (entry_id, stage, step_id, attempt) — the journal key prefix of every write
        self.key_ctx = key_ctx or {"entry_id": None, "stage": None, "step_id": None, "attempt": 0}

    # -- plumbing ---------------------------------------------------------------------------
    def _call(self, op, fn, retry=True):
        """fn() with Section F's retry rule; GhWriteError on failure. A rate limit is not retried
        here — the caller stops with exit 75 (K1-B6)."""
        try:
            return fn()
        except GhError as e:
            kind = classify_error(str(e))
            if kind != "transient" or not retry:
                raise GhWriteError(op, str(e), kind)
            self.sleep(RETRY_DELAY_S)
            try:
                return fn()
            except GhError as e2:
                raise GhWriteError(op, str(e2), classify_error(str(e2)))

    def _verify_with_backoff(self, op, verify, res):
        """Re-read up to VERIFY_READS times (eventual consistency) before calling it missing."""
        for i in range(VERIFY_READS):
            if self._call(op + ":verify", lambda: verify(res)):
                return True
            if i + 1 < VERIFY_READS:
                self.sleep(RETRY_DELAY_S * (2 ** i))
        return False

    def _perform(self, op, target, do, verify, find=None, before_done=None, **extra):
        """intent (with content identifiers) → do() → verify (re-read with backoff) → done.
        A non-idempotent create is never simply re-sent: before any retry `find()` looks for
        the write having landed after all (K1-M1); `do` must RECOMPUTE from a fresh read so a
        retried PATCH never writes a stale body. `before_done()` runs between the verified
        re-read and `done` (own-write ids land in the journal first, K1-m5)."""
        it = None
        if self.journal is not None:
            it = self.journal.intent(op=op, target=str(target), **dict(self.key_ctx, **extra))
        try:
            res = self._call(op, do, retry=find is None)
        except GhWriteError as e:
            hit = find() if (find and e.kind == "transient") else None
            if hit is None:
                if find and e.kind == "transient":
                    self.sleep(RETRY_DELAY_S)
                    hit = find()
                if hit is None and find and e.kind == "transient":
                    res = self._call(op, do, retry=False)        # the ONE bounded retry
                elif hit is None:
                    raise
                else:
                    res = hit
            else:
                res = hit
        ok = self._verify_with_backoff(op, verify, res)
        if not ok:
            hit = find() if find else None
            if hit is not None:
                res, ok = hit, True
            else:
                res = self._call(op, do)
                ok = self._verify_with_backoff(op, verify, res)
            if not ok:
                raise GhWriteError(op, "write did not land on re-read (%s)" % target, "terminal")
        if before_done is not None:
            before_done(res)
        if it is not None:
            self.journal.done(it)
        return res

    def verify_intent(self, it):
        """Restart (§2.7): did this journaled write land? Uses the content identifiers the
        intent carries (K1-M2)."""
        op, tgt = it.get("op"), it.get("target")
        if op == "comment:create":
            return self._find_comment(int(tgt), it.get("marker"), it.get("body_sha256")) is not None
        if op in ("comment:patch", "comment:append", "decisions:append", "decisions:amend"):
            issue = it.get("issue_n")
            c = self._comment(issue, int(tgt) if str(tgt).isdigit() else tgt) if issue else None
            if c is None:
                return False
            body = markers.body_of(c)
            if it.get("present"):
                return it["present"] in body
            return _sha(body) == it.get("body_sha256")
        if op == "labels":
            now = set(label_names(self.read.issue(int(tgt)).get("labels")))
            return all(a in now for a in it.get("add") or []) and not any(r in now for r in it.get("remove") or [])
        if op == "pr:body":
            return _sha(self.read.pr(int(tgt)).get("body") or "") == it.get("body_sha256")
        if op == "issue:create":
            tag = it.get("key_tag")
            return bool(tag) and any(tag in (x.get("body") or "") for x in self.read.issue_search(tag))
        return False

    def _find_comment(self, issue, marker, sha):
        for c in self.read.comments(issue):
            b = markers.body_of(c)
            if markers.first_line_marker(b) == marker and _sha(b) == sha:
                return c
        return None

    def _comment(self, issue, cid):
        for c in self.read.comments(issue):
            if c.get("id") == cid:
                return c
        return None

    # -- comments ---------------------------------------------------------------------------
    def create_comment(self, issue, body):
        if markers.first_line_marker(body) is None:
            raise ValueError("an engine comment's first line must be a Guild marker (CR-m2)")
        marker = markers.first_line_marker(body)
        sha = _sha(body)

        def own(r):
            if self.journal is not None:
                self.journal.own_write("comment", comment_id=r["id"], target=issue)
        return self._perform("comment:create", issue,
                             lambda: self.write.create_comment(issue, body),
                             lambda r: bool(r and r.get("id")) and
                             markers.body_of(self._comment(issue, r["id"])) == body,
                             find=lambda: self._find_comment(issue, marker, sha),
                             before_done=own, marker=marker, body_sha256=sha)

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
                      lambda r: markers.body_of(self._comment(issue, cid)) == body,
                      issue_n=issue, body_sha256=_sha(body))
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

            def do():
                # recompute from a FRESH read on every (re)try — never PATCH a stale body (M1)
                fresh = markers.body_of(self._comment(issue, cid))
                return self.write.patch_comment(cid, fresh if present(fresh) else insert(fresh))
            self._perform("comment:append", cid, do,
                          lambda r: present(markers.body_of(self._comment(issue, cid))),
                          issue_n=issue, body_sha256=_sha(new))
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
        def own(_r):
            if self.journal is None:
                return
            for e in self.read.timeline(issue):
                if e.get("id") in before or e.get("event") not in ("labeled", "unlabeled"):
                    continue
                lb = (e.get("label") or {}).get("name")
                if (e["event"] == "labeled" and lb in add) or (e["event"] == "unlabeled" and lb in remove):
                    self.journal.own_write("label", event_id=e.get("id"), event=e["event"],
                                           label=lb, created_at=e.get("created_at"), target=issue)
        self._perform("labels", issue, lambda: self.write.edit_labels(issue, add, remove), verify,
                      before_done=own, add=list(add), remove=list(remove))
        return add, remove

    # -- PR body (INV4) ----------------------------------------------------------------------
    def pr_body_splice(self, pr, name, block):
        """Splice one marker block of a PR body; bytes outside the markers are preserved. An
        unreadable body (two blocks, unclosed marker) raises ValueError — never written back."""
        body = self.read.pr(pr).get("body") or ""
        new = markers.splice(body, name, block)
        if new == body:
            return False
        want = {"body": new}

        def do():
            # re-splice into the CURRENT body: a human edit between tries survives (INV4, M1)
            want["body"] = markers.splice(self.read.pr(pr).get("body") or "", name, block)
            return self.write.patch_pr_body(pr, want["body"])
        self._perform("pr:body", pr, do,
                      lambda r: (self.read.pr(pr).get("body") or "") == want["body"],
                      body_sha256=_sha(new))
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
        tag = "<!-- guild:%s %s -->" % (key_kind, key) if key is not None else None

        def find():
            if not tag:
                return None
            for it in self.read.issue_search(tag):
                if tag in (it.get("body") or ""):
                    return {"number": it["number"], "found": True}
            return None
        res = self._perform("issue:create", key or title,
                            lambda: self.write.create_issue(title, body, labels),
                            lambda r: bool(r and r.get("number")) and
                            (self.read.issue(r["number"]).get("body") or "") == body,
                            find=find if tag else None, key_tag=tag, body_sha256=_sha(body))
        return int(res["number"]), not res.get("found")
