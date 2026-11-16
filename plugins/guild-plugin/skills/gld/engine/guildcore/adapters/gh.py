"""guildcore.adapters.gh — the gh reads the read-only platform needs, real and fake.

K0 owns READS only. `GhCli` refuses any argv that is not one of the read forms below, so the
engine cannot write to GitHub before K1's verified write path exists (§2.7). `FakeGh` serves a
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
        return list(self._issue(n).get("comments", []))

    def timeline(self, n):
        self.calls.append(("timeline", n))
        return list(self._issue(n).get("timeline", []))

    def pr_search(self, n):
        self.calls.append(("pr_search", n))
        needle = "#%d" % int(n)
        return [p for p in self.fx.get("prs", []) if needle in (p.get("body") or "")]

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
