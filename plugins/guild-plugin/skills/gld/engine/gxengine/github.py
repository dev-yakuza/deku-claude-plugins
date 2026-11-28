"""The engine's GitHub layer through `gh` (design §4.3 summary, §6.2 issue input, §7.4, §7.6) — U10.

Only the engine writes to GitHub (comments, labels, PR). Every write goes through
outbound.prepare_text first (secret scan + full-width @/# + same-repo URL → ＃N, §7.6,
§7.12 S10). Labels use the `guild:` prefix; comment markers `<!-- guild:… -->` (§9.1).

Summary (§4.3): one summary comment per Issue, PATCHed in place; the stage label shows
the current step. New comments only in three cases: the assumption disclosure after the
plan slot (§7.4), needs_human, completion. Every engine comment id is recorded in
state.json `github.engine_comment_ids` and excluded from issue.md.

Tests use tests/fakes/bin/gh (argument log + fixture replies); no real GitHub call.

Shape of the calls (all REST through `gh api`, except the one `gh issue view` read):
  read   issue view <N> --repo <R> --json number,title,body,labels,state,stateReason,createdAt
         api repos/<R>/issues/<N>/comments --paginate
         api repos/<R>/issues/<M>                    (each `#M` in the body, issue.md)
         api repos/<R>/issues/<N>/labels             (before a label change)
         api repos/<R>/labels/<name>                 (does the stage label exist)
         api repos/<R>/pulls?head=<owner>:<branch>&state=all   (PR once)
  write  api -X POST|PATCH|DELETE <path> [--input -]   JSON body on stdin
Every path is under `repos/<R>/` — a call for another repository is refused before gh runs.
The whole outgoing body is neutralised and then scanned exactly as sent; the only engine
markup added after neutralising is the `<!-- guild:… -->` marker line and the one closing
line of the PR (`Closes #N`). Engine-composed bodies therefore use bold / setext
headings, never `#` headings.

Stage 3 (scope V8, E19–E21, A4; V13 E31): follow-up Issues (candidates, marker search, create,
duplicate comment, labels, the dry-run record), the PR body PATCH, the visibility fact, and the PR
review items of `resume --pr-review`. Section "stage 3" below lists their call shapes.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse

from . import codes
from . import defaults
from . import fsafe
from . import issuerefs
from . import outbound

COLLABORATOR_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
STABLE_PREFIX = "gx:"                    # promote: other — the other channel's label prefix: its Issues are refused
SUMMARY_MARKER = defaults.MARKER_PREFIX + "summary -->"
MAX_REFERENCED = 50          # `#N` lookups for one issue.md; the rest are listed as not looked up
TIMEOUT_S = 120
LABEL_COLOR = "5319e7"

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class GhError(Exception):
    """A gh call failed (rc != 0). → infra (§5.1 `op` failure). `.args_`, `.returncode`, `.stderr`."""

    def __init__(self, message, args_=(), returncode=None, stderr=""):
        super().__init__(message)
        self.args_ = tuple(args_)
        self.returncode = returncode
        self.stderr = stderr

    @property
    def not_found(self):
        return "HTTP 404" in (self.stderr or "") or "Not Found" in (self.stderr or "")


def _number(n):
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError(f"issue/PR number must be a positive int, got {n!r}")
    return n


def _gh_env(env):
    e = dict(os.environ if env is None else env)
    for k in ("GH_REPO", "GH_PAGER", "PAGER", "GH_DEBUG"):
        e.pop(k, None)
    e.update({"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1",
              "GH_SPINNER_DISABLED": "1", "GH_PAGER": "cat"})
    return e


def _loads_concat(text):
    """Parse gh output: one JSON value, or several (`--paginate` prints one array per page)."""
    dec = json.JSONDecoder()
    vals, i, n = [], 0, len(text)
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        val, i = dec.raw_decode(text, i)
        vals.append(val)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    if all(isinstance(v, list) for v in vals):
        return [x for v in vals for x in v]
    raise GhError("gh printed several JSON values that are not pages of one list")


class Gh:
    """Runs `gh` with a scrubbed-but-authenticated env (the engine's own, outside any sandbox).

    `bin` defaults to the first `gh` on PATH (tests put the fake first). `plugin_root` is
    the plugin install path whose secret scanner every write goes through — a Gh without
    one can read but every write fails (outbound.ScanError, fail-closed).
    """

    def __init__(self, repo, bin="gh", env=None, plugin_root=None):
        if not isinstance(repo, str) or not _REPO_RE.match(repo):
            raise ValueError(f"repo must be owner/name, got {repo!r}")
        self.repo = repo
        self.owner = repo.split("/", 1)[0]
        self.env = _gh_env(env)
        resolved = bin if os.path.isabs(bin) else shutil.which(bin, path=self.env.get("PATH", ""))
        if not resolved:
            raise GhError(f"{bin!r} not found on PATH")
        self.bin = resolved
        self.plugin_root = plugin_root

    def call(self, *args, input=None):
        """Run `gh <args>`; return stdout (str). Raises GhError."""
        argv = [self.bin, *args]
        try:
            p = subprocess.run(argv, env=self.env, cwd="/", text=True,
                               input=input, stdin=None if input is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise GhError(f"gh {' '.join(args[:3])}: timed out", args, None, "timeout") from None
        except OSError as e:
            raise GhError(f"gh could not start: {e}", args, None, str(e)) from None
        if p.returncode != 0:
            raise GhError(f"gh {' '.join(args[:4])}: rc={p.returncode}: {p.stderr.strip()[:300]}",
                          args, p.returncode, p.stderr)
        return p.stdout

    def path(self, *parts):
        return "repos/" + self.repo + "/" + "/".join(str(p) for p in parts)

    def api(self, method, path, fields=None, paginate=False):
        """`gh api -X <method> <path>` with JSON fields; returns the parsed JSON.

        GET carries no `-X`. `fields` (a dict) goes as the JSON body on stdin (`--input -`).
        The path must be under `repos/<this repo>/`.
        """
        method = method.upper()
        if method not in ("GET", "POST", "PATCH", "PUT", "DELETE"):
            raise ValueError(f"unsupported method {method!r}")
        if (not isinstance(path, str) or not path.startswith("repos/" + self.repo + "/")
                or any(c.isspace() for c in path) or ".." in path):
            raise GhError(f"refused gh api path outside {self.repo}: {path!r}")
        args = ["api"]
        if method != "GET":
            args += ["-X", method]
        args.append(path)
        if paginate:
            args.append("--paginate")
        body = None
        if fields is not None:
            args += ["--input", "-"]
            body = json.dumps(fields, ensure_ascii=False)
        out = self.call(*args, input=body)
        try:
            return _loads_concat(out)
        except ValueError as e:
            raise GhError(f"gh api {path}: unparsable output ({e})") from None


def _label_names(labels):
    out = []
    for lab in labels or ():
        name = lab.get("name") if isinstance(lab, dict) else lab
        if isinstance(name, str):
            out.append(name)
    return out


def read_issue(gh, number):
    """{number, title, body, labels, state, comments: [{id, author, authorAssociation, body, createdAt}]}.

    Also `stateReason` and `createdAt` (the Issue's, ISO-8601 UTC; None when GitHub did not say). Labels are names.
    """
    _number(number)
    raw = gh.call("issue", "view", str(number), "--repo", gh.repo, "--json",
                  "number,title,body,labels,state,stateReason,createdAt")
    try:
        it = json.loads(raw)
    except ValueError as e:
        raise GhError(f"issue view {number}: unparsable output ({e})") from None
    if it.get("number") != number:
        raise GhError(f"issue view {number}: answered for {it.get('number')!r}")
    rows = gh.api("GET", gh.path("issues", number, "comments"), paginate=True) or []
    if not isinstance(rows, list):
        raise GhError("comments: not a list")
    comments = []
    for c in rows:
        cid = c.get("id")
        if isinstance(cid, bool) or not isinstance(cid, int):
            raise GhError(f"comment without an integer id: {cid!r}")
        comments.append({
            "id": cid,
            "author": (c.get("user") or {}).get("login"),
            "authorAssociation": c.get("author_association"),
            "body": c.get("body") or "",
            "createdAt": c.get("created_at"),
        })
    comments.sort(key=lambda c: c["id"])
    return {
        "number": number,
        "title": it.get("title") or "",
        "body": it.get("body") or "",
        "labels": _label_names(it.get("labels")),
        "state": it.get("state"),
        "stateReason": it.get("stateReason"),
        "createdAt": it.get("createdAt"),        # readiness E4: when the Issue was written (history.py)
        "comments": comments,
    }


def has_stable_label(issue):
    """True when the Issue carries a stable-Guild stage label → refuse (U0, scenario E9)."""
    stable = {STABLE_PREFIX + s for s in defaults.STABLE_STAGE_LABELS}
    return any(n.strip().lower() in stable for n in _label_names(issue.get("labels")))


EPIC_LABEL = defaults.LABEL_PREFIX + defaults.EPIC_LABEL_NAME          # readiness T1 P3
CHILD_LABEL = defaults.LABEL_PREFIX + defaults.CHILD_LABEL_NAME
DONE_LABEL = defaults.LABEL_PREFIX + defaults.DONE_LABEL_NAME          # readiness T1 R4-12
_PARENT_RE = re.compile(r"^\s*Parent Issue:\s*#([1-9][0-9]*)\b", re.MULTILINE)


def has_label(issue, name):
    """True when the Issue carries label `name` (GitHub label names compare case-insensitively)."""
    want = name.strip().lower()
    return any(n.strip().lower() == want for n in _label_names(issue.get("labels")))


def parent_issue(body):
    """The number in the `Parent Issue: #P` line `plan` / `design` write into a child's body, or None."""
    m = _PARENT_RE.search(body or "")
    return int(m.group(1)) if m else None


def issue_state(gh, number):
    """"OPEN" / "CLOSED" of Issue `number`, None when it does not exist or is a pull request."""
    info = _ref_info(gh, _number(number))
    return info["state"] if info["found"] and info["kind"] == "issue" else None


def _is_collaborator(comment):
    return comment.get("authorAssociation") in COLLABORATOR_ASSOCIATIONS


def collaborator_comments(issue, engine_comment_ids):
    """Comments that may reach a role: collaborator-written and not an engine comment (by id)."""
    engine = set(engine_comment_ids or ())
    return [c for c in issue.get("comments", ()) if c["id"] not in engine and _is_collaborator(c)]


def referenced_numbers(body, own=None, stage=1):
    """Every `#N` in the body, ascending, without `own` (issuerefs; stage >= 4: ranges too, H20)."""
    return issuerefs.referenced_numbers(body, own=own, stage=stage)


def _ref_info(gh, n):
    try:
        row = gh.api("GET", gh.path("issues", n))
    except GhError as e:
        if e.not_found:
            return {"number": n, "found": False}
        raise
    if not isinstance(row, dict) or row.get("number") != n:
        raise GhError(f"issues/{n}: unexpected answer")
    return {
        "number": n, "found": True,
        "kind": "pull request" if row.get("pull_request") else "issue",
        "state": (row.get("state") or "").upper() or None,
        "stateReason": (row.get("state_reason") or "").upper() or None,
        "labels": _label_names(row.get("labels")),
    }


def build_issue_md(gh, issue, engine_comment_ids, stage=1):
    """issue.md text (§6.2): body + collaborator comments (engine comments excluded by id,
    non-collaborators excluded) + every `#N` referenced in the body with state, stateReason, labels."""
    n = issue["number"]
    out = [f"Issue {n}: {issue.get('title') or ''}".rstrip(), "=" * 8, ""]
    out.append(f"- state: {issue.get('state') or 'unknown'}")
    out.append(f"- labels: {', '.join(issue.get('labels') or ()) or '(none)'}")
    out += ["", "Body", "----", "", (issue.get("body") or "").rstrip() or "(empty)", ""]
    comments = collaborator_comments(issue, engine_comment_ids)
    out += ["Collaborator comments", "---------------------", ""]
    if not comments:
        out += ["(none)", ""]
    for c in comments:
        out.append(f"**Comment {c['id']}** — {c.get('author') or '?'} ({c.get('authorAssociation')}), "
                   f"{c.get('createdAt') or '?'}")
        out += ["", c["body"].rstrip() or "(empty)", ""]
    refs = referenced_numbers(issue.get("body"), own=n, stage=stage)
    out += ["Referenced issues", "-----------------", ""]
    if not refs:
        out.append("(none)")
    for r in refs[:MAX_REFERENCED]:
        info = _ref_info(gh, r)
        if not info["found"]:
            out.append(f"- #{r}: not found")
            continue
        out.append(f"- #{r} ({info['kind']}): state {info['state'] or 'unknown'}, "
                   f"stateReason {info['stateReason'] or 'none'}, "
                   f"labels {', '.join(info['labels']) or '(none)'}")
    if len(refs) > MAX_REFERENCED:
        rest = refs[MAX_REFERENCED:]
        out.append(f"- not looked up ({len(rest)} more): " + ", ".join(f"#{r}" for r in rest))
    return "\n".join(out).rstrip() + "\n"


def has_decision_marker(issue, engine_comment_ids):
    """D18: a `<!-- guild:plan-decision -->` block exists in the Issue body or a comment that
    may reach a role (collaborator-written, not the engine's — the issue.md filter). The
    engine looks only at whether the marker is there; the leader reads the block."""
    marker = defaults.PLAN_DECISION_MARKER
    if marker in (issue.get("body") or ""):
        return True
    return any(marker in (c.get("body") or "") for c in collaborator_comments(issue, engine_comment_ids))


def referenced_issue_states(gh, issue, stage=1):
    """[{number, state, state_reason}] of every `#N` the body references (the issue.md facts,
    plan-gate input §2.1). Not found → state / state_reason null. At most MAX_REFERENCED."""
    out = []
    for r in referenced_numbers(issue.get("body"), own=issue["number"], stage=stage)[:MAX_REFERENCED]:
        info = _ref_info(gh, r)
        out.append({"number": r, "state": info.get("state") if info["found"] else None,
                    "state_reason": info.get("stateReason") if info["found"] else None})
    return out


def new_collaborator_comments(issue, engine_comment_ids, last_seen_id):
    """Collaborator comments newer than the watermark, not written by the engine (§7.4, E8).

    "Newer" = comment id greater than `last_seen_id` (GitHub ids increase); None = all.
    """
    return [c for c in collaborator_comments(issue, engine_comment_ids)
            if last_seen_id is None or c["id"] > last_seen_id]


def comment_watermark(issue, last_seen_id=None):
    """The new `last_seen_comment_id` after reading `issue`: the largest comment id seen."""
    ids = [c["id"] for c in issue.get("comments", ())]
    if last_seen_id is not None:
        ids.append(last_seen_id)
    return max(ids) if ids else None


def _marker(name):
    if not _NAME_RE.match(name or ""):
        raise ValueError(f"marker name must match {_NAME_RE.pattern}, got {name!r}")
    return f"{defaults.MARKER_PREFIX}{name} -->"


def _outgoing(gh, text, head="", tail=""):
    """The text exactly as it will be sent: engine head + neutralised text + engine tail, scanned once."""
    final = head + outbound.neutralise(text, gh.repo) + tail
    return outbound.check_text(final, gh.plugin_root)


def _comment_id(row, expect=None):
    cid = row.get("id") if isinstance(row, dict) else None
    if isinstance(cid, bool) or not isinstance(cid, int) or (expect is not None and cid != expect):
        raise GhError(f"comment write answered with id {cid!r}")
    return cid


def upsert_summary(gh, number, comment_id, body):
    """PATCH the summary comment (or create it when comment_id is None). Returns the id."""
    _number(number)
    text = _outgoing(gh, body, head=SUMMARY_MARKER + "\n")
    if comment_id is None:
        return _comment_id(gh.api("POST", gh.path("issues", number, "comments"), {"body": text}))
    _number(comment_id)
    return _comment_id(gh.api("PATCH", gh.path("issues", "comments", comment_id), {"body": text}), comment_id)


def post_comment(gh, number, body, marker="comment"):
    """A new comment (assumptions / needs_human / completion only). Returns the id."""
    _number(number)
    text = _outgoing(gh, body, head=_marker(marker) + "\n")
    return _comment_id(gh.api("POST", gh.path("issues", number, "comments"), {"body": text}))


def stage_label(step_id):
    if not _NAME_RE.match(step_id or ""):
        raise ValueError(f"step id must match {_NAME_RE.pattern}, got {step_id!r}")
    return defaults.LABEL_PREFIX + step_id


def _q(name):
    return urllib.parse.quote(name, safe="")


def set_stage_label(gh, number, step_id, stage_ids=()):
    """Replace the `guild:<stage>` label (create it if missing).

    Only `guild:<id>` for `id` in `stage_ids` (the procedure's step ids) are taken off — any
    other `guild:` label (`guild:escaped-ac`, `guild:followup`, …) is a human's and stays.
    Returns the label name.
    """
    _number(number)
    name = stage_label(step_id)
    old = {stage_label(s) for s in stage_ids} - {name}
    outbound.check_text(name, gh.plugin_root, "label")
    try:
        gh.api("GET", gh.path("labels", _q(name)))
    except GhError as e:
        if not e.not_found:
            raise
        gh.api("POST", gh.path("labels"), {"name": name, "color": LABEL_COLOR,
                                           "description": "Guild (gld) current step"})
    current = _label_names(gh.api("GET", gh.path("issues", number, "labels")) or [])
    for lab in current:
        if lab in old:
            gh.api("DELETE", gh.path("issues", number, "labels", _q(lab)))
    if name not in current:
        gh.api("POST", gh.path("issues", number, "labels"), {"labels": [name]})
    return name


def close_issue(gh, number, reason):
    """Stage 2 close-as-decided (D18): `gh issue close <N> --reason completed|"not planned"`.

    `reason` is a codes.CloseReason value, mapped by name (codes.GH_CLOSE_REASON). The
    rationale comment is posted before this (post_comment, marker closed-as-decided)."""
    _number(number)
    if reason not in codes.GH_CLOSE_REASON:
        raise ValueError(f"close reason must be one of {sorted(codes.GH_CLOSE_REASON)}, got {reason!r}")
    gh.call("issue", "close", str(number), "--repo", gh.repo, "--reason", codes.GH_CLOSE_REASON[reason])


def open_prs(gh, branch):
    """Stage 4 (H10): the numbers of the open pull requests whose head is `branch`, ascending."""
    rows = gh.api("GET", gh.path("pulls?head=" + _q(gh.owner + ":" + branch) + "&state=all")) or []
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise GhError("pulls list: not a list")
    return sorted(_number(r.get("number")) for r in rows
                  if r.get("state") == "open" and (r.get("head") or {}).get("ref") in (None, branch))


OPEN_PR_LIST_MAX = 500
"""Readiness T1 P2: open pull requests read at a new Issue's start. As many → the list may be cut → refused."""
PR_LIST_FIELDS = "number,headRefName,body,closingIssuesReferences"
_CLOSING_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#|#|https?://github\.com/(?P<url>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/)"
    r"(?P<n>[1-9][0-9]*)\b", re.IGNORECASE)


def body_closes(body, repo, number):
    """True when a pull request body closes Issue `number` of `repo` with one of GitHub's closing keywords
    (close/closes/closed, fix/fixes/fixed, resolve/resolves/resolved; `#N`, `owner/repo#N` or the Issue URL)."""
    for m in _CLOSING_RE.finditer(body or ""):
        other = m.group("repo") or m.group("url")
        if int(m.group("n")) == number and (other is None or other.lower() == repo.lower()):
            return True
    return False


def _reference_closes(ref, repo, number):
    """One closingIssuesReferences entry of `gh pr list` names Issue `number` of `repo`."""
    if not isinstance(ref, dict) or ref.get("number") != number:
        return False
    r = ref.get("repository")
    if isinstance(r, dict) and isinstance(r.get("name"), str) and isinstance((r.get("owner") or {}).get("login"), str):
        return f"{r['owner']['login']}/{r['name']}".lower() == repo.lower()
    return str(ref.get("url") or "").lower().endswith(f"/{repo.lower()}/issues/{number}")


def _closed_by_body(body, repo):
    """The Issue numbers of `repo` a pull request body closes with a closing keyword."""
    out = set()
    for m in _CLOSING_RE.finditer(body or ""):
        other = m.group("repo") or m.group("url")
        if other is None or other.lower() == repo.lower():
            out.add(int(m.group("n")))
    return out


def open_closing_map(gh):
    """Readiness T1 P2 / P7: {Issue number: [{number, head, via}]} — the open pull requests, on ANY branch, and the
    Issues of this repository each closes (GitHub's closingIssuesReferences, else a closing keyword in the body).
    One read:  gh pr list --repo <R> --state open --limit OPEN_PR_LIST_MAX --json PR_LIST_FIELDS
    GhError when GitHub does not answer, answers something else, or the list may be cut."""
    raw = gh.call("pr", "list", "--repo", gh.repo, "--state", "open", "--limit", str(OPEN_PR_LIST_MAX),
                  "--json", PR_LIST_FIELDS)
    try:
        rows = json.loads(raw)
    except ValueError as e:
        raise GhError(f"pr list: unparsable output ({e})") from None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise GhError("pr list: not a list")
    if len(rows) >= OPEN_PR_LIST_MAX:
        raise GhError(f"pr list: {len(rows)} open pull requests — the list may be cut, so it says nothing")
    out = {}
    for r in rows:
        number, head = _number(r.get("number")), str(r.get("headRefName") or "?")
        refs = {x["number"] for x in r.get("closingIssuesReferences") or ()
                if isinstance(x, dict) and isinstance(x.get("number"), int)
                and _reference_closes(x, gh.repo, x["number"])}
        for n in refs | _closed_by_body(r.get("body"), gh.repo):
            out.setdefault(n, []).append({"number": number, "head": head, "via": "reference" if n in refs else "body"})
    return {n: sorted(v, key=lambda p: p["number"]) for n, v in out.items()}


def open_closing_prs(gh, number):
    """Readiness T1 P2: the open pull requests, on ANY branch, that close Issue `number` ([{number, head, via}]
    ascending; open_closing_map). GhError as there."""
    return open_closing_map(gh).get(_number(number), [])


def create_pr(gh, branch, base, title, body, closes=None, not_before=None, draft=False):
    """Create the PR once (not draft, §7.6; stage 4: `draft` for a stacked member, U1). Returns {number, url}.

    "Once": an open PR whose head is `branch` is returned as is (a resume after a crash
    between creation and recording); a closed / merged one is a GhError (a human closed it).
    `not_before` (this run's state created_at, ISO-8601 UTC): a closed, unmerged PR created
    before it belongs to an earlier run of the same branch name (a validation reset closes it)
    and is skipped. A merged one is always a GhError.
    Title and body are neutralised; `closes` (the Issue number) adds the one closing line
    written by the engine, after neutralising (S10).
    """
    for what, v in (("branch", branch), ("base", base)):
        if not isinstance(v, str) or not v or v.startswith("-") or any(c.isspace() for c in v):
            raise ValueError(f"{what} must be a branch name, got {v!r}")
    tail = ""
    if closes is not None:
        tail = f"\n\nCloses #{_number(closes)}\n"
    query = "pulls?head=" + _q(gh.owner + ":" + branch) + "&state=all"
    existing = gh.api("GET", gh.path(query)) or []
    if not isinstance(existing, list):
        raise GhError("pulls list: not a list")
    for pr in existing:
        if (pr.get("head") or {}).get("ref") not in (None, branch):
            continue
        if pr.get("state") == "open":
            return {"number": _number(pr.get("number")), "url": pr.get("html_url")}
        created = pr.get("created_at")
        if (not_before and pr.get("state") == "closed" and not pr.get("merged_at")
                and isinstance(created, str) and created < not_before):
            continue
        raise GhError(f"PR #{pr.get('number')} for {branch} exists and is {pr.get('state')}")
    safe_title = _outgoing(gh, title)
    safe_body = _outgoing(gh, body, tail=tail)
    row = gh.api("POST", gh.path("pulls"), {"title": safe_title, "head": branch, "base": base,
                                            "body": safe_body, "draft": bool(draft)})
    if not isinstance(row, dict):
        raise GhError("PR create: unexpected answer")
    return {"number": _number(row.get("number")), "url": row.get("html_url")}


def repo_is_private(gh):
    """True / False from `gh repo view --json isPrivate` (D27: the PR body writes a `security`
    discovery only for a repository known to be private). GhError when GitHub does not say."""
    raw = gh.call("repo", "view", gh.repo, "--json", "isPrivate")
    try:
        v = json.loads(raw).get("isPrivate")
    except (ValueError, AttributeError):
        v = None
    if not isinstance(v, bool):
        raise GhError("repo view: no isPrivate in the answer", ("repo", "view"), 0, "")
    return v


def visibility_fact(gh):
    """Stage 3 (E21): `state.github.is_private` — read once at Issue start. True / False, or None
    when GitHub does not say (unknown = treated as public by every reader, fail-closed)."""
    try:
        return repo_is_private(gh)
    except GhError:
        return None


# --- stage 3: follow-up Issues (E19–E21, user decision A4) ---------------------------------------
#
# Call shapes (all under repos/<R>/, the fake-gh rules in tests/fixtures/gh/issue-42-stage3.json):
#   read   labels?per_page=100 --paginate                                    (once per op)
#          issues?labels=<guild:followup | gx:followup>&state=open&sort=updated&direction=desc&per_page=<n>  # promote: other
#          issues?labels=guild%3Afollowup&state=all&per_page=100 --paginate     (marker search, stage-3
#                                                                             interpretation 9)
#          issues/<M>/comments --paginate                                    (duplicate: marker search)
#   write  POST labels · POST issues · POST issues/<M>/comments · POST issues/<N>/labels · PATCH pulls/<P>
# The marker is the FIRST line of every engine-written follow-up body / comment; only a first line
# equal to the marker counts, so a role's text quoting a marker further down cannot fake one.

FOLLOWUP_LABEL = defaults.LABEL_PREFIX + defaults.FOLLOWUP_LABEL_NAME
STABLE_FOLLOWUP_LABEL = STABLE_PREFIX + defaults.FOLLOWUP_LABEL_NAME
SECURITY_LABEL = defaults.LABEL_PREFIX + defaults.SECURITY_LABEL_NAME
IRREVERSIBLE_LABEL = defaults.LABEL_PREFIX + defaults.IRREVERSIBLE_LABEL_NAME
NEEDS_HUMAN_LABEL = defaults.LABEL_PREFIX + defaults.NEEDS_HUMAN_LABEL_NAME          # stage 4 (H9)
FOLLOWUP_TITLE_MAX = 200
FOLLOWUP_DISPOSITIONS = (codes.DiscoveryDisposition.FOLLOWUP.value, codes.DiscoveryDisposition.DUPLICATE.value)
LABEL_DESCRIPTIONS = {
    FOLLOWUP_LABEL: "Guild (gld) follow-up of an out-of-scope discovery",
    SECURITY_LABEL: "Guild (gld) security follow-up",
    IRREVERSIBLE_LABEL: "Guild (gld) hard-to-revert change — review before merging",
    NEEDS_HUMAN_LABEL: "Guild (gld) waits for a human answer",
}
_KEY_RE = re.compile(r"^(D[1-9][0-9]*|deferred):[0-9a-f]{8}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._ -]{0,49}$")


def followup_key(source, payload):
    """`<D id | deferred>:<8 hex>` — the idempotency key of one follow-up (E20). The hash is over the
    canonical JSON of `payload` (the engine-numbered discovery, or the deferred rows), so a D id that
    a later done-gate gives to another discovery makes another key."""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    key = f"{source}:{digest[:8]}"
    if not _KEY_RE.match(key):
        raise ValueError(f"follow-up source must be D<n> or deferred, got {source!r}")
    return key


def followup_marker(issue, key):
    """`<!-- guild:followup origin=<N> key=<key> -->` (defaults.FOLLOWUP_MARKER)."""
    _number(issue)
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise ValueError(f"bad follow-up key {key!r}")
    return defaults.FOLLOWUP_MARKER.format(issue=issue, key=key)


def _first_line_is(body, marker):
    return (body or "").split("\n", 1)[0].strip() == marker


def _need_label(name):
    if not isinstance(name, str) or not _LABEL_RE.match(name):
        raise ValueError(f"not a label name the engine writes: {name!r}")
    return name


def label_names(gh):
    """The repository's label names (read once at the start of create-followups)."""
    rows = gh.api("GET", gh.path("labels?per_page=100"), paginate=True) or []
    if not isinstance(rows, list):
        raise GhError("labels: not a list")
    return set(_label_names(rows))


def _issue_rows(rows, what):
    if not isinstance(rows, list):
        raise GhError(f"{what}: not a list")
    out = []
    for r in rows:
        if not isinstance(r, dict) or "pull_request" in r:
            continue                      # the issues endpoint lists pull requests too
        n = r.get("number")
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise GhError(f"{what}: an issue without a number")
        out.append(r)
    return out


def followup_candidates(gh, limit=defaults.FOLLOWUP_CANDIDATES_MAX):
    """E19 `{candidate_issues}`: open Issues labelled FOLLOWUP_LABEL or STABLE_FOLLOWUP_LABEL (either channel's), newest update
    first, at most `limit` — [{number, title, labels}]. No free-text search (TX1)."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError(f"limit must be 1..100, got {limit!r}")
    seen = {}
    for label in (FOLLOWUP_LABEL, STABLE_FOLLOWUP_LABEL):
        rows = gh.api("GET", gh.path(f"issues?labels={_q(label)}&state=open&sort=updated&direction=desc"
                                     f"&per_page={limit}")) or []
        for r in _issue_rows(rows, "follow-up candidates"):
            if (r.get("state") or "open").lower() != "open":
                continue
            seen.setdefault(r["number"], r)
    rows = sorted(seen.values(), key=lambda r: (str(r.get("updated_at") or ""), r["number"]), reverse=True)
    return [{"number": r["number"], "title": str(r.get("title") or ""), "labels": _label_names(r.get("labels"))}
            for r in rows[:limit]]


def find_followup(gh, marker):
    """The Issue created with `marker` (any state, `guild:followup` label), or None. Lowest number wins."""
    rows = gh.api("GET", gh.path(f"issues?labels={_q(FOLLOWUP_LABEL)}&state=all&per_page=100"), paginate=True) or []
    hits = [r["number"] for r in _issue_rows(rows, "follow-up search") if _first_line_is(r.get("body"), marker)]
    return min(hits) if hits else None


def ensure_label(gh, name, known):
    """Create the label unless `known` (the set from label_names) has it; adds it to `known`."""
    _need_label(name)
    if name in known:
        return
    outbound.check_text(name, gh.plugin_root, "label")
    try:
        gh.api("POST", gh.path("labels"), {"name": name, "color": LABEL_COLOR,
                                           "description": LABEL_DESCRIPTIONS.get(name, "Guild (gld)")})
    except GhError as e:
        if "422" not in (e.stderr or "") and "already_exists" not in (e.stderr or ""):
            raise
    known.add(name)


def _title(gh, title):
    t = " ".join(str(title or "").split())
    if not t:
        raise ValueError("a follow-up Issue needs a title")
    return _outgoing(gh, t[:FOLLOWUP_TITLE_MAX])


def create_followup(gh, title, body, labels, marker):
    """Create the follow-up Issue once (E20). Returns {number, url, created}.

    The marker search runs first: an Issue that already carries `marker` is returned as is (a resume
    after a crash, scenario TF5). Title and body are neutralised and scanned exactly as sent; the
    marker is the engine's first body line, added after neutralising. `labels` must already exist
    (ensure_label) — a missing one would be created by GitHub without the engine's description.
    """
    found = find_followup(gh, marker)
    if found is not None:
        return {"number": found, "url": None, "created": False}
    safe_title = _title(gh, title)
    text = _outgoing(gh, body, head=marker + "\n")
    names = [_need_label(n) for n in labels]
    row = gh.api("POST", gh.path("issues"), {"title": safe_title, "body": text, "labels": names})
    if not isinstance(row, dict):
        raise GhError("issue create: unexpected answer")
    return {"number": _number(row.get("number")), "url": row.get("html_url"), "created": True}


def comment_followup(gh, number, body, marker):
    """E20 `duplicate`: one marker comment on the candidate Issue; an existing one is kept. Returns the id."""
    _number(number)
    rows = gh.api("GET", gh.path("issues", number, "comments"), paginate=True) or []
    if not isinstance(rows, list):
        raise GhError("comments: not a list")
    for c in rows:
        if isinstance(c, dict) and _first_line_is(c.get("body"), marker):
            return _comment_id(c)
    text = _outgoing(gh, body, head=marker + "\n")
    return _comment_id(gh.api("POST", gh.path("issues", number, "comments"), {"body": text}))


def add_label(gh, number, name, known=None):
    """Put `name` on Issue / PR `number` (created first when missing — `known`, or a lookup)."""
    _number(number)
    _need_label(name)
    if known is None:
        try:
            gh.api("GET", gh.path("labels", _q(name)))
            known = {name}
        except GhError as e:
            if not e.not_found:
                raise
            known = set()
    ensure_label(gh, name, known)
    gh.api("POST", gh.path("issues", number, "labels"), {"labels": [name]})
    return name


def remove_label(gh, number, name):
    """Stage 4 (H9): take `name` off Issue `number`; a label that is not there is fine."""
    _number(number)
    _need_label(name)
    try:
        gh.api("DELETE", gh.path("issues", number, "labels", _q(name)))
    except GhError as e:
        if not e.not_found:
            raise


def update_pr(gh, number, body, closes=None):
    """PATCH the PR body (E20 "분리한 후속 이슈", E31 same-PR update). Neutralised and scanned like
    create_pr; `closes` adds the engine's one closing line after neutralising. Returns {number, url}."""
    _number(number)
    tail = f"\n\nCloses #{_number(closes)}\n" if closes is not None else ""
    row = gh.api("PATCH", gh.path("pulls", number), {"body": _outgoing(gh, body, tail=tail)})
    if not isinstance(row, dict) or row.get("number") != number:
        raise GhError(f"PR update: answered for {row.get('number') if isinstance(row, dict) else row!r}")
    return {"number": number, "url": row.get("html_url")}


def _check_item(item):
    if not isinstance(item, dict) or not _KEY_RE.match(str(item.get("key"))):
        raise ValueError(f"follow-up item without a valid key: {item!r}")
    if item.get("disposition") not in FOLLOWUP_DISPOSITIONS:
        raise ValueError(f"follow-up item {item['key']}: disposition {item.get('disposition')!r}")
    if not item.get("private_path"):
        if item["disposition"] == codes.DiscoveryDisposition.DUPLICATE.value:
            _number(item.get("target"))
        elif not item.get("title"):
            raise ValueError(f"follow-up item {item['key']}: no title")
    return item


def _read_jsonl(path, root):
    try:
        raw = fsafe.read_bytes(path, root=root)
    except FileNotFoundError:
        return []
    return [json.loads(ln) for ln in raw.decode("utf-8").splitlines() if ln.strip()]


def _record_dry_run(path, root, record):
    """Upsert one would-be write into the engine-local dry-run file (JSON lines, one per key)."""
    rows = [r for r in _read_jsonl(path, root) if r.get("key") != record["key"]]
    rows.append(record)
    fsafe.write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), root=root)


def apply_followups(gh, items, *, issue, dry_run, done_keys=(), on_row=None, dry_run_path=None,
                    security_md=None, security_path=None, root=None, now=None):
    """Run the `create-followups` op over prepared items (E20, E21, A4). Returns the new
    `state.followups` rows in item order; each row goes to `on_row(row)` as soon as it is final, so
    the caller records it (state + log) before the next GitHub write.

    items         prbody.followup_items(…): {key, kind, disposition, title, body, labels, type_label,
                  target, private_path}
    dry_run       repo-config `followups_dry_run` (A4): no Issue / comment / label write — every
                  would-be write (title, body, labels, marker, target) is upserted into `dry_run_path`
                  after the same neutralising and secret scan. The label list is still read once.
    done_keys     keys already in state.followups (a resume continues after the last one, TF5).
    security_md   prbody.security_findings_md text, written to `security_path` (engine-local,
                  never committed) before any GitHub call when given.
    Private-path items (a security discovery of a repository not known to be private) never reach
    GitHub. outbound.SecretDetected / ScanError and GhError propagate (→ needs_human / infra
    op-failed); the rows already passed to on_row stay recorded.
    """
    items = [_check_item(i) for i in items]
    if len({i["key"] for i in items}) != len(items):
        raise ValueError("follow-up items repeat a key")
    if dry_run and not dry_run_path:
        raise ValueError("a dry run needs the engine-local record path")
    stamp = now or (lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if security_md is not None:
        if not security_path:
            raise ValueError("security findings need the engine-local record path")
        fsafe.write_text(security_path, security_md, root=root)
    todo = [i for i in items if i["key"] not in set(done_keys)]
    known = label_names(gh) if any(not i.get("private_path") for i in todo) else set()
    out = []
    for it in todo:
        marker = followup_marker(issue, it["key"])
        row = {"key": it["key"], "kind": it["kind"], "disposition": it["disposition"], "number": None,
               "comment_id": None, "dry_run": bool(dry_run), "private_path": bool(it.get("private_path")), "at": None}
        if not it.get("private_path"):
            duplicate = it["disposition"] == codes.DiscoveryDisposition.DUPLICATE.value
            labels = [] if duplicate else list(it.get("labels") or [FOLLOWUP_LABEL])
            if not duplicate and it.get("type_label") and it["type_label"] in known:
                labels.append(it["type_label"])
            if dry_run:
                record = {"key": it["key"], "kind": it["kind"], "disposition": it["disposition"],
                          "action": "comment" if duplicate else "create-issue",
                          "target": it.get("target") if duplicate else None,
                          "title": None if duplicate else _title(gh, it["title"]),
                          "body": _outgoing(gh, it["body"], head=marker + "\n"),
                          "labels": labels, "labels_to_create": sorted(set(labels) - known), "marker": marker}
                _record_dry_run(dry_run_path, root, record)
            elif duplicate:
                row["number"] = it["target"]
                row["comment_id"] = comment_followup(gh, it["target"], it["body"], marker)
            else:
                for name in labels:
                    ensure_label(gh, name, known)
                row["number"] = create_followup(gh, it["title"], it["body"], labels, marker)["number"]
        row["at"] = stamp()
        out.append(row)
        if on_row is not None:
            on_row(row)
    return out


# --- stage 3 (V13, E31): PR reviews for `resume --pr-review` -------------------------------------

PR_REVIEW_KINDS = tuple(codes.PrReviewKind.values())


def _assoc_ok(row):
    return row.get("author_association") in COLLABORATOR_ASSOCIATIONS


def pr_review_items(gh, pr, last_seen_ids, engine_comment_ids=()):
    """New collaborator items of PR `pr` since the watermarks (E31) — the §6.2 filter: collaborators
    only, engine comments out (by id, and any body whose first line is an engine marker).

    Three GitHub id spaces (stage-3 interpretation 10): reviews (`pulls/<n>/reviews`, a PENDING draft
    and an empty COMMENTED container of inline comments are skipped), review comments
    (`pulls/<n>/comments`) and conversation comments (`issues/<n>/comments`). Returns
    [{id: "<kind>:<n>", kind, author_association, created_at, state, path, body}], oldest first.
    """
    _number(pr)
    seen = dict(last_seen_ids or {})
    engine = set(engine_comment_ids or ())
    K = codes.PrReviewKind
    sources = ((K.REVIEW.value, gh.path("pulls", pr, "reviews")),
               (K.REVIEW_COMMENT.value, gh.path("pulls", pr, "comments")),
               (K.COMMENT.value, gh.path("issues", pr, "comments")))
    out = []
    for kind, path in sources:
        rows = gh.api("GET", path, paginate=True) or []
        if not isinstance(rows, list):
            raise GhError(f"{kind}: not a list")
        floor = seen.get(kind)
        for r in rows:
            rid = r.get("id") if isinstance(r, dict) else None
            if isinstance(rid, bool) or not isinstance(rid, int) or rid <= 0:
                raise GhError(f"{kind} without an integer id: {rid!r}")
            if floor is not None and rid <= floor:
                continue
            body = r.get("body") or ""
            if not _assoc_ok(r) or (kind == K.COMMENT.value and rid in engine):
                continue
            if body.split("\n", 1)[0].lstrip().startswith(defaults.MARKER_PREFIX):
                continue
            state = r.get("state") if kind == K.REVIEW.value else None
            if kind == K.REVIEW.value and (state == "PENDING" or (state == "COMMENTED" and not body.strip())):
                continue
            out.append({"id": f"{kind}:{rid}", "kind": kind, "author_association": r.get("author_association"),
                        "created_at": r.get("submitted_at") if kind == K.REVIEW.value else r.get("created_at"),
                        "state": state, "path": r.get("path") if kind == K.REVIEW_COMMENT.value else None,
                        "author": (r.get("user") or {}).get("login"), "body": body})
    out.sort(key=lambda i: (str(i.get("created_at") or ""), i["kind"], int(i["id"].split(":")[1])))
    return out


def pr_review_watermarks(items, last_seen_ids=None):
    """state.pr_review.last_seen_ids after reading `items`: the largest id per kind (None = none yet)."""
    marks = {k: (last_seen_ids or {}).get(k) for k in PR_REVIEW_KINDS}
    for i in items:
        n = int(i["id"].split(":", 1)[1])
        if marks[i["kind"]] is None or n > marks[i["kind"]]:
            marks[i["kind"]] = n
    return marks


def build_pr_review_md(items):
    """in/pr-review.md (E31): one block per item — the leader answers `reviews[].effect` per id."""
    out = ["# PR reviews since the last read", ""]
    if not items:
        return "\n".join(out + ["(none)", ""])
    for i in items:
        bits = [i.get("author") or "?", f"({i.get('author_association')})"]
        if i.get("state"):
            bits.append(i["state"])
        if i.get("path"):
            bits.append(f"on `{i['path']}`")
        bits.append(str(i.get("created_at") or "?"))
        out += [f"## {i['id']}", "", " ".join(bits), "", (i.get("body") or "").rstrip() or "(empty)", ""]
    return "\n".join(out)


def summary_text(state):
    """The summary comment body (§4.3, M6 rest) from state.json — engine text only, no `#` headings.

    Shape: a bold title line, the current step, a stop line when stopped, the PR when
    made, one table row per step (id · status · latest attempt), and the running totals.
    """
    steps = state.get("steps") or []
    cur = next((s for s in steps if s.get("status") not in ("done", "pending", "skipped")), None)
    lines = [f"**Guild (gld) — Issue {state.get('issue')}**", ""]
    closed = state.get("closed")
    if closed:
        lines.append(f"- closed as decided (`{closed.get('reason')}`) — no pull request")
    elif cur:
        lines.append(f"- current step: `{cur['id']}` ({cur['status']})")
    elif steps and all(s.get("status") == "done" for s in steps):
        lines.append("- all steps done")
    stop = state.get("stop")
    if stop:
        where = f" at `{stop['step']}`" if stop.get("step") else ""
        lines.append(f"- stopped: {stop['status']} — `{stop['reason']}`{where} ({stop.get('at')})")
    gh_state = state.get("github") or {}
    if gh_state.get("pr_number"):
        lines.append(f"- pull request: {gh_state['pr_number']}")
    calls = state.get("leader_calls") or []
    if calls:
        # stage 2 (scope §2.0-5): one line per leader decision — situation · answer · reason · step
        lines += ["", "leader decisions:"]
        for c in calls:
            what = f"`{c['answer']}`" if c.get("answer") else f"no answer ({c.get('failed') or 'stopped'})"
            lines.append(f"- `{c['situation']}` → {what}"
                         + (f" `{c['step']}`" if c.get("step") else "")
                         + (f" (reason `{c['reason']}`)" if c.get("reason") else ""))
    lines += ["", "| step | status | attempt |", "|---|---|---|"]
    for s in steps:
        att = s.get("latest_attempt")
        lines.append(f"| `{s['id']}` | {s.get('status')} | {att if att is not None else '—'} |")
    totals = state.get("totals") or {}
    if totals:
        cost = totals.get("cost_usd")
        lines += ["", f"attempts {totals.get('attempts', 0)} · cost "
                      f"{'$%.2f' % cost if isinstance(cost, (int, float)) else 'n/a'} · "
                      f"updated {state.get('updated_at')}"]
    return "\n".join(lines) + "\n"
