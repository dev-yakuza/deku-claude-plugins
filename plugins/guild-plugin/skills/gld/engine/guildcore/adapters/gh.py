"""guildcore.adapters.gh — the gh reads the read-only platform needs, real and fake.

`GhCli` owns READS only and refuses any argv that is not one of the read forms below. Writes go
through the separate `GhWriteCli` (K1), whose argv must be one of the WRITE forms, and only ever
through `guildcore.records.write.GhWriter`, which re-reads every write (§2.7, Section F). `FakeGh` serves a
JSON fixture (`tests/fixtures/engine/gh/*.json`) and counts calls so tests can assert the
"≤ 3 gh reads per Issue" budget of `guildcore.state.snapshot`.

Fixture shape (all keys optional):
    {"repo": "o/r",
     "issues": {"<n>": {"number", "title", "body", "url", "state", "stateReason",
                        "labels": [{"name"}], "comments": [{"id", "body", "created_at",
                        "updated_at", "author_association", "user": {"login"}}],
                        "timeline": [{"event", "label": {"name"}, "created_at", "actor"}]}},
     "prs": [{"number", "url", "state", "title", "body"}]}
"""

import json
import re
import subprocess


class GhError(Exception):
    pass


_READ_FORMS = (
    re.compile(r"^gh issue view \d+ "),
    re.compile(r"^gh issue list "),
    re.compile(r"^gh pr list "),
    re.compile(r"^gh repo view "),
    re.compile(r"^gh api (--paginate )?repos/[^/ ]+/[^/ ]+/issues/\d+/(comments|timeline)( |$)"),
    re.compile(r"^gh pr view \d+ "),
    # K2 (qa Step 2 `### PR CI`): the head commit's check-runs and a failed run's annotations
    re.compile(r"^gh api (--paginate )?repos/[^/ ]+/[^/ ]+/commits/[0-9a-f]{7,40}/check-runs( |$)"),
    re.compile(r"^gh api (--paginate )?repos/[^/ ]+/[^/ ]+/check-runs/\d+/annotations( |$)"),
    # K4 (analyze A1.0 trust gate, P2): the Issue's own REST row — `author_association` is not in
    # `gh issue view --json`; a plan-decision / safety-net block is honoured only from a member's body
    re.compile(r"^gh api repos/[^/ ]+/[^/ ]+/issues/\d+ --jq "),
)
_WRITE_FLAGS = re.compile(r"(^| )(-X|--method|-f|-F|--field|--raw-field|--input|"
                          r"--add-label|--remove-label|--body|--body-file)( |=|$)")


def assert_read_only(argv):
    line = " ".join(argv)
    if _WRITE_FLAGS.search(line) or not any(rx.search(line) for rx in _READ_FORMS):
        raise GhError("refused non-read gh call in K0: %s" % line)


class GhCli(object):
    """Real reads through the `gh` binary (never used by tests)."""

    def __init__(self, repo=None, runner=None):
        self.repo = repo
        self.runner = runner or self._run
        self.calls = 0

    @staticmethod
    def _run(argv):
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise GhError((p.stderr.decode("utf-8", "replace").strip().splitlines() or ["gh failed"])[-1])
        return p.stdout.decode("utf-8", "replace")

    def _gh(self, argv):
        assert_read_only(argv)
        self.calls += 1
        return self.runner(argv)

    def _repo_args(self):
        return ["--repo", self.repo] if self.repo else []

    def owner_repo(self):
        if not self.repo:
            self.repo = self._gh(["gh", "repo", "view", "--json", "nameWithOwner", "--jq",
                                  ".nameWithOwner"]).strip()
        return self.repo

    def issue(self, n):
        out = self._gh(["gh", "issue", "view", str(n)] + ["--json",
                        "number,title,body,url,state,stateReason,labels"] + self._repo_args())
        it = json.loads(out)
        if not self.repo:
            # owner/repo from the URL we already have — no extra `gh repo view` (K0-m2)
            m = re.match(r"^https://[^/]+/([^/]+/[^/]+)/(?:issues|pull)/\d+", it.get("url") or "")
            if m:
                self.repo = m.group(1)
        return it

    def _paged(self, path):
        out = self._gh(["gh", "api", "--paginate", path, "--jq", ".[]"])
        rows = []
        # "\n" only: jq prints U+2028/U+0085 raw inside strings, and splitlines() cuts there (K0-m1)
        for ln in out.split("\n"):
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
        return rows

    def comments(self, n):
        return self._paged("repos/%s/issues/%d/comments" % (self.owner_repo(), int(n)))

    def timeline(self, n):
        return self._paged("repos/%s/issues/%d/timeline" % (self.owner_repo(), int(n)))

    def pr_search(self, n):
        out = self._gh(["gh", "pr", "list", "--state", "all", "--search", "#%d in:body" % int(n),
                        "--json", "number,url,state,title,body"] + self._repo_args())
        return json.loads(out or "[]")

    def pr_for_head(self, branch):
        """execute Step 5 (P5.11): the open PR whose head is the Issue branch."""
        out = self._gh(["gh", "pr", "list", "--head", branch, "--state", "open", "--json",
                        "number,url,state,title,body,headRefName,baseRefName,isCrossRepository,headRefOid"] + self._repo_args())
        return json.loads(out or "[]")

    def pr(self, n):
        return json.loads(self._gh(["gh", "pr", "view", str(n), "--json",
                                    "number,url,state,title,body,headRefName,headRefOid"] + self._repo_args()))

    def check_runs(self, sha):
        """qa Step 2 step 2: `{id, name, conclusion, annotations}` per check-run of `sha`."""
        out = self._gh(["gh", "api", "--paginate", "repos/%s/commits/%s/check-runs" % (self.owner_repo(), sha),
                        "--jq", ".check_runs[] | {id, name, conclusion, annotations: .output.annotations_count}"])
        return [json.loads(ln) for ln in out.split("\n") if ln.strip()]

    def annotations(self, run_id):
        out = self._gh(["gh", "api", "repos/%s/check-runs/%d/annotations" % (self.owner_repo(), int(run_id)),
                        "--jq", ".[] | .message"])
        return [ln for ln in out.split("\n") if ln.strip()]

    def issue_search(self, text, limit=50):
        out = self._gh(["gh", "issue", "list", "--state", "all", "--limit", str(limit),
                        "--search", text, "--json", "number,title,body,state,labels"]
                       + self._repo_args())
        return json.loads(out or "[]")

    def issue_author_association(self, n):
        """K4: OWNER | MEMBER | COLLABORATOR | CONTRIBUTOR | NONE … of the Issue's author."""
        out = self._gh(["gh", "api", "repos/%s/issues/%d" % (self.owner_repo(), int(n)), "--jq",
                        ".author_association"])
        return out.strip() or None

    def closed_by_prs(self, n):
        """dev 2b step 1b: `closedByPullRequestsReferences` — [{number, repo: "owner/name"}]."""
        out = self._gh(["gh", "issue", "view", str(int(n)), "--json", "closedByPullRequestsReferences"]
                       + self._repo_args())
        refs = (json.loads(out or "{}").get("closedByPullRequestsReferences") or [])
        rows = []
        for r in refs:
            repo = r.get("repository") or {}
            owner = (repo.get("owner") or {}).get("login") or ""
            rows.append({"number": r.get("number"), "repo": "%s/%s" % (owner, repo.get("name") or "")})
        return rows

    def pr_state(self, n):
        """{state, mergedAt} of a PR (dev 2b step 1b, 2c)."""
        return json.loads(self._gh(["gh", "pr", "view", str(int(n)), "--json", "number,state,mergedAt,url"]
                                   + self._repo_args()))

    def issue_list(self, state="open", label=None, limit=200):
        argv = ["gh", "issue", "list", "--state", state, "--limit", str(limit),
                "--json", "number,title,body,labels,state,stateReason"]
        if label:
            argv += ["--label", label]
        return json.loads(self._gh(argv + self._repo_args()) or "[]")


class FakeGh(object):
    def __init__(self, fixture):
        if isinstance(fixture, str):
            with open(fixture, encoding="utf-8") as fh:
                fixture = json.load(fh)
        self.fx = fixture
        self.repo = fixture.get("repo", "o/r")
        self.calls = []

    def _issue(self, n):
        it = self.fx.get("issues", {}).get(str(int(n)))
        if it is None:
            raise GhError("Could not resolve to an issue or pull request with the number of %s" % n)
        return it

    def owner_repo(self):
        return self.repo

    def issue(self, n):
        self.calls.append(("issue", n))
        it = dict(self._issue(n))
        it.pop("comments", None)
        it.pop("timeline", None)
        it.setdefault("number", int(n))
        it.setdefault("url", "https://github.com/%s/issues/%s" % (self.repo, n))
        return it

    def comments(self, n):
        self.calls.append(("comments", n))
        lag = getattr(self, "lagging", {})
        out = []
        for c in self._issue(n).get("comments", []):
            if lag.get(c.get("id")):
                lag[c["id"]] -= 1
                continue
            out.append(c)
        return out

    def timeline(self, n):
        self.calls.append(("timeline", n))
        return list(self._issue(n).get("timeline", []))

    def pr_search(self, n):
        self.calls.append(("pr_search", n))
        needle = "#%d" % int(n)
        return [p for p in self.fx.get("prs", []) if needle in (p.get("body") or "")]

    def pr_for_head(self, branch):
        self.calls.append(("pr_for_head", branch))
        return [dict(p) for p in self.fx.get("prs", []) if p.get("headRefName") == branch
                and (p.get("state") or "OPEN").upper() == "OPEN"]

    def pr(self, n):
        self.calls.append(("pr", n))
        for p in self.fx.get("prs", []):
            if int(p.get("number")) == int(n):
                return dict(p)
        raise GhError("no pull request %s" % n)

    def check_runs(self, sha):
        self.calls.append(("check_runs", sha))
        return list(self.fx.get("check_runs", {}).get(sha, []))

    def annotations(self, run_id):
        self.calls.append(("annotations", run_id))
        return list(self.fx.get("annotations", {}).get(str(run_id), []))

    def issue_search(self, text, limit=50):
        self.calls.append(("issue_search", text))
        out = []
        for k in sorted(self.fx.get("issues", {}), key=int):
            it = self.fx["issues"][k]
            if text in (it.get("body") or "") or text in (it.get("title") or ""):
                out.append({"number": int(k), "title": it.get("title"), "body": it.get("body"),
                            "state": it.get("state", "OPEN"), "labels": it.get("labels", [])})
        return out[:limit]

    def issue_author_association(self, n):
        self.calls.append(("issue_author_association", n))
        return self._issue(n).get("author_association")

    def closed_by_prs(self, n):
        self.calls.append(("closed_by_prs", n))
        return [dict(r) for r in self._issue(n).get("closed_by_prs", [])]

    def pr_state(self, n):
        self.calls.append(("pr_state", n))
        for p in self.fx.get("prs", []):
            if int(p.get("number")) == int(n):
                return {"number": p["number"], "state": p.get("state", "OPEN"), "mergedAt": p.get("mergedAt"),
                        "url": p.get("url")}
        raise GhError("no pull request %s" % n)

    def issue_list(self, state="open", label=None, limit=200):
        self.calls.append(("issue_list", state, label))
        rows = []
        for k in sorted(self.fx.get("issues", {}), key=int):
            it = self.fx["issues"][k]
            if "/pull/" in (it.get("url") or ""):
                continue
            st = (it.get("state") or "OPEN").upper()
            if state == "open" and st != "OPEN":
                continue
            if state == "closed" and st != "CLOSED":
                continue
            names = [lb["name"] if isinstance(lb, dict) else lb for lb in it.get("labels", [])]
            if label and label not in names:
                continue
            row = {k2: v for k2, v in it.items() if k2 not in ("comments", "timeline")}
            row.setdefault("number", int(k))
            rows.append(row)
        return rows[:limit]


# ---- write side (K1) ------------------------------------------------------------------------------

class GhWriteError(Exception):
    """A failed state mutation (Section F). `kind` = auth | terminal | transient."""

    def __init__(self, op, message, kind):
        Exception.__init__(self, "gh %s failed — %s" % (op, message))
        self.op = op
        self.message = message
        self.kind = kind

    @property
    def terminal(self):
        return self.kind != "transient"


_AUTH = re.compile(r"\b(401|403)\b|gh auth login|authentication|Bad credentials|not logged", re.I)
_TERMINAL = re.compile(r"\b(404|422)\b|Not Found|Validation Failed|could not add label|"
                       r"does not exist|Could not resolve to", re.I)
_TRANSIENT = re.compile(r"\b(500|502|503|504)\b|timed? ?out|timeout|connection|"
                        r"network|EOF|TLS|temporar|reset by peer|no such host|server error", re.I)


_RATELIMIT = re.compile(r"rate limit|secondary rate|abuse detection|\b429\b|Retry-After", re.I)


def classify_error(text):
    """auth | ratelimit | terminal | transient. Rate limits are checked FIRST: GitHub answers a
    secondary limit with 403, which must not read as an auth failure (K1-B6)."""
    t = text or ""
    if _RATELIMIT.search(t):
        return "ratelimit"
    if re.search(r"could not resolve host|resolve host", t, re.I):
        return "transient"                    # K1-m6: DNS is a network hiccup, not a 404
    if _AUTH.search(t):
        return "auth"
    if _TERMINAL.search(t):
        return "terminal"
    if _TRANSIENT.search(t):
        return "transient"
    return "terminal"


_WRITE_FORMS = (
    re.compile(r"^gh api repos/[^/ ]+/[^/ ]+/issues/\d+/comments -X POST --input -$"),
    re.compile(r"^gh api repos/[^/ ]+/[^/ ]+/issues/comments/\d+ -X PATCH --input -$"),
    re.compile(r"^gh api repos/[^/ ]+/[^/ ]+/issues -X POST --input -$"),
    re.compile(r"^gh api repos/[^/ ]+/[^/ ]+/pulls/\d+ -X PATCH --input -$"),
    re.compile(r"^gh issue edit \d+( --(add|remove)-label [^ ]+)+( --repo [^ ]+)?$"),
    # K3 execute Step 5: the engine opens the PR (roles never touch GitHub, Q23)
    re.compile(r"^gh api repos/[^/ ]+/[^/ ]+/pulls -X POST --input -$"),
    # K4 analyze 0b ④ (close as decided): `{"state": "closed", "state_reason": …}` only
    re.compile(r"^gh api repos/[^/ ]+/[^/ ]+/issues/\d+ -X PATCH --input -$"),
)


def assert_write_form(argv):
    line = " ".join(argv)
    if not any(rx.match(line) for rx in _WRITE_FORMS):
        raise GhError("refused gh write outside the engine's write forms: %s" % line)


class GhWriteCli(object):
    """Raw writes through `gh` — the engine's ONLY write path, used solely by records.write."""

    def __init__(self, repo, runner=None):
        if not repo:
            raise GhError("GhWriteCli needs owner/repo (Section F)")
        self.repo = repo
        self.runner = runner or self._run
        self.calls = 0

    @staticmethod
    def _run(argv, stdin=None):
        p = subprocess.run(argv, input=(stdin or "").encode("utf-8"), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise GhError(p.stderr.decode("utf-8", "replace").strip() or "gh failed")
        return p.stdout.decode("utf-8", "replace")

    def _gh(self, argv, payload=None):
        assert_write_form(argv)
        self.calls += 1
        return self.runner(argv, json.dumps(payload) if payload is not None else None)

    def create_comment(self, n, body):
        return json.loads(self._gh(["gh", "api", "repos/%s/issues/%d/comments" % (self.repo, int(n)),
                                    "-X", "POST", "--input", "-"], {"body": body}))

    def patch_comment(self, cid, body):
        return json.loads(self._gh(["gh", "api", "repos/%s/issues/comments/%d" % (self.repo, int(cid)),
                                    "-X", "PATCH", "--input", "-"], {"body": body}))

    def create_issue(self, title, body, labels=()):
        return json.loads(self._gh(["gh", "api", "repos/%s/issues" % self.repo, "-X", "POST",
                                    "--input", "-"], {"title": title, "body": body,
                                                      "labels": list(labels)}))

    def close_issue(self, n, reason):
        if reason not in ("completed", "not_planned"):
            raise GhError("close reason must be completed|not_planned: %r" % reason)
        return json.loads(self._gh(["gh", "api", "repos/%s/issues/%d" % (self.repo, int(n)), "-X", "PATCH",
                                    "--input", "-"], {"state": "closed", "state_reason": reason}))

    def patch_pr_body(self, n, body):
        return json.loads(self._gh(["gh", "api", "repos/%s/pulls/%d" % (self.repo, int(n)), "-X",
                                    "PATCH", "--input", "-"], {"body": body}))

    def create_pr(self, head, base, title, body, draft=False):
        r = json.loads(self._gh(["gh", "api", "repos/%s/pulls" % self.repo, "-X", "POST", "--input", "-"],
                                {"head": head, "base": base, "title": title, "body": body, "draft": bool(draft)}))
        return {"number": r.get("number"), "url": r.get("html_url") or r.get("url")}

    def edit_labels(self, n, add=(), remove=()):
        argv = ["gh", "issue", "edit", str(int(n))]
        for a in add:
            argv += ["--add-label", a]
        for r in remove:
            argv += ["--remove-label", r]
        self._gh(argv + ["--repo", self.repo])
        return True


class FakeGhWrite(object):
    """Writes into a FakeGh's fixture (same object), with server ids/timestamps and timeline
    events, and fault injection: `fail_next(kind, n=1)` raises before the write; `lose_next(n)`
    returns success WITHOUT landing (the re-read verification must catch it)."""

    def __init__(self, fake, clock=None, actor="guild-bot"):
        self.fake = fake
        self.clock = clock
        self.actor = actor
        self.calls = []
        self._fail = []
        self._lose = 0
        self._next_id = 9000

    def fail_next(self, kind, n=1, message=None):
        msg = message or {"transient": "HTTP 502: Bad Gateway", "auth": "HTTP 401: Bad credentials",
                          "terminal": "HTTP 422: Validation Failed",
                          "ratelimit": "HTTP 403: You have exceeded a secondary rate limit"}[kind]
        self._fail += [msg] * n

    def lose_next(self, n=1):
        self._lose += n

    def ack_lost_next(self, n=1):
        """The write LANDS but the client gets a 502 (K1-M1)."""
        self._acklost = getattr(self, "_acklost", 0) + n

    def lag_next(self, reads=1):
        """The next created comment stays invisible to `reads` comment reads (eventual
        consistency, K1-M1)."""
        self._lag = reads

    def _now(self):
        return self.clock.now() if self.clock else "2026-11-16T00:00:00Z"

    def _gate(self, op):
        self.calls.append(op)
        if self._fail:
            raise GhError(self._fail.pop(0))
        if self._lose:
            self._lose -= 1
            return False
        return True

    def _id(self):
        self._next_id += 1
        return self._next_id

    def _issue(self, n):
        return self.fake.fx.setdefault("issues", {}).setdefault(str(int(n)), {"labels": [], "comments": []})

    def create_comment(self, n, body):
        cid, now = self._id(), self._now()
        c = {"id": cid, "body": body, "created_at": now, "updated_at": now,
             "author_association": "OWNER", "user": {"login": self.actor}}
        if self._gate(("create_comment", n)):
            self._issue(n).setdefault("comments", []).append(c)
            if getattr(self, "_lag", 0):
                self.fake.lagging = getattr(self.fake, "lagging", {})
                self.fake.lagging[cid] = self._lag
                self._lag = 0
            if getattr(self, "_acklost", 0):
                self._acklost -= 1
                raise GhError("HTTP 502: Bad Gateway")
        return dict(c)

    def patch_comment(self, cid, body):
        now = self._now()
        land = self._gate(("patch_comment", cid))
        for it in self.fake.fx.get("issues", {}).values():
            for c in it.get("comments", []):
                if c.get("id") == cid:
                    if land:
                        c["body"] = body
                        c["updated_at"] = now
                    return dict(c, body=body, updated_at=now)
        raise GhError("HTTP 404: Not Found")

    def create_issue(self, title, body, labels=()):
        nums = [int(k) for k in self.fake.fx.get("issues", {})] or [0]
        n = max(nums) + 1
        if self._gate(("create_issue", title)):
            self.fake.fx.setdefault("issues", {})[str(n)] = {
                "number": n, "title": title, "body": body, "state": "OPEN",
                "labels": [{"name": l} for l in labels], "comments": [], "timeline": [],
                "author_association": "OWNER"}          # the engine writes with the operator's token
        return {"number": n, "html_url": "https://github.com/%s/issues/%d" % (self.fake.repo, n)}

    def close_issue(self, n, reason):
        if reason not in ("completed", "not_planned"):
            raise GhError("HTTP 422: bad state_reason")
        it = self._issue(n)
        if self._gate(("close_issue", n, reason)):
            it["state"] = "CLOSED"
            it["stateReason"] = reason.upper()
        return {"number": int(n), "state": "closed"}

    def patch_pr_body(self, n, body):
        land = self._gate(("patch_pr_body", n))
        for p in self.fake.fx.get("prs", []):
            if int(p.get("number")) == int(n):
                if land:
                    p["body"] = body
                return dict(p, body=body)
        raise GhError("HTTP 404: Not Found")

    def create_pr(self, head, base, title, body, draft=False):
        if getattr(self, "draft_unsupported", False) and draft:
            self._gate(("create_pr", head))
            raise GhError("HTTP 422: Draft pull requests are not supported in this repository")
        nums = [int(k) for k in self.fake.fx.get("issues", {})] + [int(p.get("number")) for p in self.fake.fx.get("prs", [])]
        n = max(nums or [0]) + 1
        pr = {"number": n, "url": "https://github.com/%s/pull/%d" % (self.fake.repo, n), "state": "OPEN",
              "title": title, "body": body, "headRefName": head, "baseRefName": base, "isDraft": bool(draft),
              "headRefOid": None}
        if self._gate(("create_pr", head, base, bool(draft))):
            self.fake.fx.setdefault("prs", []).append(pr)
            self.fake.fx.setdefault("issues", {})[str(n)] = {"number": n, "labels": [], "comments": [],
                                                             "url": pr["url"]}
        return {"number": n, "url": pr["url"]}

    def edit_labels(self, n, add=(), remove=()):
        it = self._issue(n)
        names = [l["name"] if isinstance(l, dict) else l for l in it.get("labels", [])]
        for r in remove:
            if r not in names:
                raise GhError("HTTP 422: label %s not on issue" % r)
        if not self._gate(("edit_labels", n, tuple(add), tuple(remove))):
            return True
        now = self._now()
        tl = it.setdefault("timeline", [])
        for a in add:
            if a not in names:
                names.append(a)
                tl.append({"id": self._id(), "event": "labeled", "label": {"name": a},
                           "created_at": now, "actor": {"login": self.actor}})
        for r in remove:
            names.remove(r)
            tl.append({"id": self._id(), "event": "unlabeled", "label": {"name": r},
                       "created_at": now, "actor": {"login": self.actor}})
        it["labels"] = [{"name": x} for x in names]
        return True
