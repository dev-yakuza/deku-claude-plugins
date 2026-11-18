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
  differences (needs-human removed only when present); Issue creation lists its label for its
  hidden key first — never the search index (A-F23, K4r2-M1);
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


def _final_redact(text):
    from guildcore.records.redact import redact
    return "\n".join(redact(ln) for ln in (text or "").split("\n"))


def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def withdrawn(row):
    """An Issue a person closed as not planned — no longer the holder of its hidden key (K4r2-m4)."""
    return ((row.get("state") or "").upper() == "CLOSED"
            and (row.get("stateReason") or "").upper().replace(" ", "_") == "NOT_PLANNED")


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
            if not tag:
                return False
            return self.keyed_issue(tag, it.get("find_label")) is not None     # K4r2-M1: the listing, never search
        return False

    def _records(self, issue):
        """Record candidates only (K2-M5): never PATCH a stranger's comment that carries a marker."""
        own = self.journal.own_comment_ids() if self.journal is not None else ()
        return markers.trusted(self.read.comments(issue), own)

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
        cur = markers.find(self._records(issue), name, pick=pick)
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
            comments = self._records(issue)
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
        return self.pr_body_edit(pr, lambda body: markers.splice(body, name, block))

    def pr_body_edit(self, pr, fn):
        """`fn(current body) -> new body`, re-applied to the CURRENT body on every try (a human
        edit between tries survives — INV4, K1-M1). No change → no write. Returns changed. The new
        body gets a last per-line INV5 pass (K3r1-B1 — renderers already redact per value)."""
        body = self.read.pr(pr).get("body") or ""
        raw_fn = fn
        fn = lambda b: _final_redact(raw_fn(b))                     # noqa: E731
        new = fn(body)
        if new == body:
            return False
        want = {"body": new}

        def do():
            want["body"] = fn(self.read.pr(pr).get("body") or "")
            return self.write.patch_pr_body(pr, want["body"])
        self._perform("pr:body", pr, do,
                      lambda r: (self.read.pr(pr).get("body") or "") == want["body"],
                      body_sha256=_sha(new))
        return True

    # -- PR create (K3 execute Step 5) -------------------------------------------------------------
    def pr_create(self, head, base, title, body, draft=False):
        """Open the Issue's PR once: an open PR whose head is `head` is returned instead (a resumed
        write). Draft unsupported (422 naming draft) → once more without draft (D-5.3). Returns
        {number, url, created, draft}."""
        body, title = _final_redact(body), _final_redact(title)
        def find():
            hits = [h for h in self.read.pr_for_head(head) if not h.get("isCrossRepository")]
            return {"number": hits[0]["number"], "url": hits[0].get("url"), "found": True} if hits else None
        hit = self._call("pr:find", find)
        if hit:
            return dict(hit, created=False, draft=None)
        from guildcore.adapters.gh import GhError
        for d in ([True, False] if draft else [False]):
            try:
                res = self._perform("pr:create", head, lambda: self.write.create_pr(head, base, title, body, d),
                                    lambda r: bool(r and r.get("number")) and
                                    (self.read.pr(r["number"]).get("body") or "") == body,
                                    find=find, body_sha256=_sha(body), base=base, draft=d)
                return {"number": int(res["number"]), "url": res.get("url"), "created": not res.get("found"),
                        "draft": d}
            except (GhError, GhWriteError) as e:
                if d and "draft" in str(e).lower():
                    continue
                raise
        raise GhWriteError("pr:create", "unreachable", "terminal")

    # -- Issues --------------------------------------------------------------------------------
    def issue_close(self, issue, reason):
        """analyze 0b ④: close with `completed` | `not_planned`; verified by re-reading the state.
        Already closed → no write. Returns True when this call closed it."""
        if (self.read.issue(issue).get("state") or "").upper() == "CLOSED":
            return False
        self._perform("issue:close", issue, lambda: self.write.close_issue(issue, reason),
                      lambda r: (self.read.issue(issue).get("state") or "").upper() == "CLOSED",
                      reason=reason)
        return True

    MEMBERS = ("OWNER", "MEMBER", "COLLABORATOR")

    def keyed_issue(self, tag, label, members=None):
        """K4r2-M1/m6: the Issue that already carries the hidden key `tag` — found by the LABEL
        LISTING (`gh issue list --label`, the repository's issue connection: strongly consistent,
        newest first), never by the search API (an eventually consistent index that misses an
        Issue created seconds ago → a duplicate child). Only an Issue that carries `label` AND whose
        author is a member counts: an outsider who opens an Issue with the public key first plants
        nothing. An Issue closed as NOT_PLANNED is withdrawn (a person re-splitting closes the old
        children that way) and never counts. An unreadable author association raises (unknown is never member, never outsider).
        The lowest number wins when two carry the key (the caller fails on duplicates)."""
        from guildcore.state import label_names as _ln
        members = tuple(members or self.MEMBERS)
        rows = self._call("issue:list", lambda: self.read.issue_list(state="all", label=label, limit=200))
        hits = sorted((r for r in rows or [] if tag in (r.get("body") or "")
                       and (label is None or label in _ln(r.get("labels"))) and not withdrawn(r)),
                      key=lambda r: int(r["number"]))
        for r in hits:
            assoc = self._call("issue:author", lambda: self.read.issue_author_association(int(r["number"])))
            assoc = (assoc or "").strip()
            if not assoc:
                raise GhWriteError("issue:author", "author association of #%s unreadable" % r["number"], "transient")
            if assoc in members:
                return {"number": int(r["number"]), "found": True}
        return None

    def issue_create(self, title, body, labels=(), key=None, key_kind="slice-key", members=None):
        """Create once: the body carries `<!-- guild:<key_kind> <key> -->`; an existing member Issue
        with that key and the first label is returned instead (A-F23). The intent is journaled
        BEFORE the POST (with the key tag and the listing label), and every "did it land?" read —
        before the create, after an ambiguous failure, on restart — is the label listing
        (`keyed_issue`), never the search index (K4r2-M1). Returns (number, created)."""
        tag = None
        label = None
        if key is not None:
            # the listing label: guild:child for a child; an unlabelled keyed create lists every Issue
            # (still the consistent listing, newest first — never the search index)
            label = ("guild:child" if "guild:child" in labels else list(labels)[0]) if labels else None
            tag = "<!-- guild:%s %s -->" % (key_kind, key)
            if tag not in body:
                body = body.rstrip("\n") + "\n\n" + tag + "\n"
            hit = self.keyed_issue(tag, label, members)
            if hit is not None:
                return hit["number"], False

        def find():
            return self.keyed_issue(tag, label, members) if tag else None
        res = self._perform("issue:create", key or title,
                            lambda: self.write.create_issue(title, body, labels),
                            lambda r: bool(r and r.get("number")) and
                            (self.read.issue(r["number"]).get("body") or "") == body,
                            find=find if tag else None, key_tag=tag, find_label=label, body_sha256=_sha(body))
        return int(res["number"]), not res.get("found")
