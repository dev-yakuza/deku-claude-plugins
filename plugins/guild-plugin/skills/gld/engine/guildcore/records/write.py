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
  differences (needs-human removed only when present); a keyed Issue create is journal-first: the
  intent (key + a unique token in the body) before the POST, the number right after, a lost reply
  resolved by the token through the REST issues list (database-backed) and confirmed by number —
  never a search-backed read (`gh issue list --label` is IssueSearch), never a second POST while
  unknown (A-F23, K4r3-B1);
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
TOKEN_TAG = "<!-- guild:create-token %s -->"


def _parse_iso(t):
    import calendar
    try:
        return calendar.timegm(time.strptime((t or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _age_s(t, now):
    a, b = _parse_iso(t), _parse_iso(now)
    return None if a is None or b is None else b - a


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
    def __init__(self, read, write, journal=None, sleep=time.sleep, key_ctx=None, clock=None):
        self.read = read
        self.clock = clock
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
            # K4r3-B1: the journaled number, else the create token through the REST list (never search)
            if not it.get("token"):
                return False
            if any(e.get("token") == it["token"] for e in self._ij().own_issues()):
                return True
            return self.find_by_token(it["token"], it.get("find_label"), it.get("since")) is not None
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

    # -- keyed Issue creation (K4r3-B1: journal first, never an index) ------------------------------
    TOKEN_READS = 4            # REST list reads for a lost reply: now, +2 s, +4 s, +8 s
    SETTLE_S = 600             # an unresolved intent this old, absent from the REST list, never landed
    SINCE_MARGIN_S = 600       # clock skew between this host and GitHub on the list's `since`

    def _ij(self):
        """The journal that holds Issue-create intents and numbers (an in-memory one without a journal)."""
        if self.journal is not None:
            return self.journal
        if getattr(self, "_memj", None) is None:
            self._memj = _MemJournal(self.clock)
        return self._memj

    def own_issues(self, prefix=None):
        """{key: number} of the Issues this engine created (journal, latest record per key), keys starting
        with `prefix`. Identity is the journal's number — never a listing, never author association (m5)."""
        out = {}
        for e in self._ij().own_issues():
            k = str(e.get("key") or "")
            if prefix is None or k.startswith(prefix):
                out[k] = int(e["number"])
        return out

    def _record_issue(self, it, number, recovered=False):
        j = self._ij()
        j.own_write("issue", key=it.get("key"), number=int(number), token=it.get("token"),
                    recovered=bool(recovered))
        j.done(it, number=int(number))

    def _since(self, t):
        ts = _parse_iso(t)
        if ts is None:
            return None
        return _iso(ts - self.SINCE_MARGIN_S)

    def find_by_token(self, token, label, since, reads=None):
        """The Issue whose body carries the create token — the REST issues LIST (database-backed:
        `GET /repos/{o}/{r}/issues?labels=…&since=…`, all pages), each candidate confirmed by number;
        bounded re-reads with backoff. The lowest confirmed number wins (a copy of a public token can
        only be made after the original exists). None after the last read."""
        reads = self.TOKEN_READS if reads is None else reads
        for i in range(reads):
            rows = self._call("issue:find", lambda: self.read.issue_rows(label=label, state="all", since=since))
            for r in sorted((r for r in rows or [] if token in (r.get("body") or "")), key=lambda r: int(r["number"])):
                row = self._call("issue:row", lambda: self.read.issue_row(int(r["number"])))
                if token in (row.get("body") or ""):
                    return int(row["number"])
            if i + 1 < reads:
                self.sleep(RETRY_DELAY_S * (2 ** i))
        return None

    def resolve_creates(self, prefix=None, key=None, reads=None):
        """Every journaled Issue create that has an intent but no number (the POST's reply was lost, or
        the process died between the POST and the record): found by its token → its number is journaled;
        absent and the intent older than SETTLE_S → it never landed (abandoned); absent and younger →
        `GhWriteError(kind="ambiguous")` — the caller pauses for a person and NOTHING is created."""
        j = self._ij()
        known = set(e.get("token") for e in j.own_issues())
        for it in j.intent_only():
            if it.get("op") != "issue:create" or not it.get("token") or it.get("token") in known:
                continue
            k = str(it.get("key") or "")
            if (prefix is not None and not k.startswith(prefix)) or (key is not None and k != key):
                continue
            n = self.find_by_token(it["token"], it.get("find_label"), it.get("since"), reads)
            if n is not None:
                self._record_issue(it, n, recovered=True)
                known.add(it["token"])
                continue
            age = _age_s(it.get("t"), j._now())
            if age is not None and age >= self.SETTLE_S:
                j.done(it, abandoned=True)
                continue
            raise GhWriteError("issue:create", "the create of %s may have landed (its reply was lost) and is not "
                               "in the issue list yet — nothing is re-created while that is unknown" % k,
                               "ambiguous")

    def issue_create(self, title, body, labels=(), key=None, key_kind="slice-key", members=None):
        """Create once (A-F23, K4r3-B1 — journal first):
        1. an unresolved earlier create of this key is resolved by its token (`resolve_creates`);
        2. a number the journal holds for the key that is still live (read by number: carries the key,
           not closed as not planned) is returned;
        3. else intent (key, a fresh unique token embedded in the body, the list's `since`) is journaled
           and fsynced, the POST is sent once, and the answered number is journaled IMMEDIATELY; a
           transient failure is resolved by the token through the REST list (bounded backoff) — found →
           that number; not found → `GhWriteError("ambiguous")`, never a second POST. Refused writes
           (auth, rate limit, 4xx) never landed: the intent is closed and the error raised.
        No search-backed read anywhere. `members` is accepted for old callers and ignored (m5: the
        engine's own Issues are known by the journal, not by author association). Returns (number, created)."""
        if key is None:
            res = self._perform("issue:create", title, lambda: self.write.create_issue(title, body, labels),
                                lambda r: bool(r and r.get("number")) and
                                (self.read.issue(r["number"]).get("body") or "") == body, body_sha256=_sha(body))
            return int(res["number"]), True
        label = ("guild:child" if "guild:child" in labels else list(labels)[0]) if labels else None
        tag = "<!-- guild:%s %s -->" % (key_kind, key)
        if tag not in body:
            body = body.rstrip("\n") + "\n\n" + tag + "\n"
        self.resolve_creates(key=key)
        have = self.own_issues().get(key)
        if have is not None:
            row = self._call("issue:row", lambda: self.read.issue_row(have))
            if tag in (row.get("body") or "") and not withdrawn(row):
                return have, False
        import uuid
        token = uuid.uuid4().hex
        body = body.rstrip("\n") + "\n" + (TOKEN_TAG % token) + "\n"
        j = self._ij()
        # target carries the token: every create attempt is its own journal key (an abandoned or
        # recorded earlier attempt of the same slice key never marks this one done)
        it = j.intent(op="issue:create", target="%s %s" % (key, token), key=key, key_tag=tag, token=token, find_label=label,
                      since=self._since(j._now()), body_sha256=_sha(body),
                      **dict((k, v) for k, v in self.key_ctx.items() if k not in ("op", "target")))
        try:
            res = self._call("issue:create", lambda: self.write.create_issue(title, body, labels), retry=False)
            n = int(res["number"])
            self._record_issue(it, n)                       # the number, before anything else can fail
        except GhWriteError as e:
            if e.kind != "transient":
                j.done(it, refused=e.kind)                  # the server refused it: nothing landed
                raise
            n = self.find_by_token(token, label, it.get("since"))
            if n is None:
                raise GhWriteError("issue:create", "the create of %s failed ambiguously (%s) and the issue list "
                                   "does not show it — nothing is re-created while that is unknown"
                                   % (key, e.message), "ambiguous")
            self._record_issue(it, n, recovered=True)
            return n, False
        if not self._verify_with_backoff("issue:create", lambda _r: token in
                                         (self._call("issue:row", lambda: self.read.issue_row(n)).get("body") or ""), n):
            raise GhWriteError("issue:create", "#%d did not carry its create token on re-read" % n, "terminal")
        return n, True


class _MemJournal(object):
    """The intent/number records of keyed creates when the writer has no journal (tests, one process)."""

    def __init__(self, clock=None):
        from guildcore.journal import JournalView
        self.view = JournalView([], 0)
        self.entries = self.view.entries
        self.clock = clock

    def _now(self):
        return self.clock.now() if self.clock is not None else _iso(time.time())

    def append(self, kind, **f):
        f.setdefault("issue", None)
        f["kind"], f["t"] = kind, self._now()
        self.entries.append(f)
        return f

    def intent(self, op, target, **extra):
        return self.append("intent", op=op, target=target, **extra)

    def done(self, it, **extra):
        from guildcore.journal import KEY_FIELDS
        f = dict((k, it.get(k)) for k in KEY_FIELDS if k != "issue")
        f.update(extra)
        return self.append("done", **f)

    def own_write(self, op, **fields):
        return self.append("write", op=op, **fields)

    def intent_only(self):
        return self.view.intent_only()

    def own_issues(self):
        return self.view.own_issues()
