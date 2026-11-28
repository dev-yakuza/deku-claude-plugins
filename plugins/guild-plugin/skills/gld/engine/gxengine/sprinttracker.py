"""The sprint tracking Issue and the dependency facts (stage-4 scope §2.2, §2.3, VA2) — owner: branch A.

`gh` is github.Gh. Reads raise github.GhError when GitHub does not answer (or answers something else than
asked): the supervisor turns that into base-unresolved / failed, never into a guess (§2.0).

Calls (all under repos/<R>/ but the two views):
  read   issue view <T> · issues/<n> · issues/<T>/comments --paginate · pulls/<n> · pulls?head=<owner>:gld/<n>&state=all
         git/matching-refs/heads/gld/<n> · repo view --json defaultBranchRef | merge settings
  write  the run marker comment (POST once, then PATCH) · one comment when the base check is red
"""

import json
import re

from . import codes, defaults, github, sprintdag, store

_SHA = re.compile(r"\A[0-9a-f]{40}([0-9a-f]{24})?\Z")
BRANCH_PREFIX = "gld/"
PR_STATES = ("OPEN", "CLOSED", "MERGED")
MARKER_MEMBER_KEYS = ("issue", "outcome", "block", "cause", "stop_reason", "pr", "draft")


class Tracker:
    """What `read` gives: number, body, state ("OPEN" | "CLOSED"), run ({"id", "data"} of the oldest
    `guild:sprint:run` comment, data = its JSON object or None) or None."""

    def __init__(self, number, body, state, run=None):
        self.number, self.body, self.state, self.run = number, body, state, run


def _issue_row(gh, number):
    """github._ref_info of a plain Issue; GhError when it is missing or a pull request."""
    row = github._ref_info(gh, number)
    if not row["found"]:
        raise github.GhError(f"issue {number} does not exist")
    if row["kind"] != "issue":
        raise github.GhError(f"{number} is a {row['kind']}, not an Issue")
    if row["state"] not in ("OPEN", "CLOSED"):
        raise github.GhError(f"issue {number}: unknown state {row['state']!r}")
    return row


def _marker_data(body):
    """The JSON object between the run markers, or None when there is none to read."""
    rest = body.split(defaults.SPRINT_RUN_MARKER, 1)[1].split(defaults.SPRINT_RUN_MARKER_END, 1)[0].strip()
    if rest.startswith("```"):
        rest = rest.split("\n", 1)[1] if "\n" in rest else ""
        rest = rest.rsplit("```", 1)[0]
    try:
        data = json.loads(rest)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def read(gh, tracker):
    """The Tracker of Issue `tracker`. GhError when it cannot be read or is a pull request.

    The run marker is the OLDEST marker comment a collaborator wrote (several: every earlier run kept the
    oldest one up to date, 0.98.7); an outsider's comment is never one."""
    _issue_row(gh, tracker)
    data = github.read_issue(gh, tracker)
    run = None
    for c in github.collaborator_comments(data, ()):                        # ascending ids
        if defaults.SPRINT_RUN_MARKER in c["body"]:
            run = {"id": c["id"], "data": _marker_data(c["body"])}
            break
    return Tracker(tracker, data["body"], data["state"], run)


def marker_object(sprint, heartbeat):
    """The run marker's JSON object: the 0.98.7 keys + members, codes and numbers only (R11)."""
    state = sprint["state"] if sprint["halt"] is None else f"{sprint['state']}:{sprint['halt']}"
    completion = None
    if sprint["state"] in codes.SPRINT_ENDED:
        completion = {o: [m["issue"] for m in sprint["members"] if m["outcome"] == o] for o in codes.MemberOutcome.values()}
        completion["not-started"] = [m["issue"] for m in sprint["members"] if m["outcome"] is None]
    return {"host": sprint["host"], "pid": sprint["pid"], "state": state, "started": sprint["started"],
            "heartbeat": heartbeat, "window": sprint["window"], "completion": completion, "run": sprint["run"],
            "allow_red_base": sprint["allow_red_base"],
            "members": [{k: m[k] for k in MARKER_MEMBER_KEYS} for m in sprint["members"]]}


def write_marker(gh, tracker, comment_id, sprint):
    """Write the run marker (defaults.SPRINT_RUN_MARKER … ```json … ```) for the sprint.json object `sprint`: PATCH
    `comment_id` (the oldest one), or create it when None. Keys: the 0.98.7 ones (host pid state started heartbeat
    window completion) + `members`; codes and numbers only, no path and no free text (R11). Returns the comment id."""
    obj = marker_object(sprint, store.now_ts())
    text = github._outgoing(gh, "```json\n" + json.dumps(obj, sort_keys=True) + "\n```\n",
                            head=defaults.SPRINT_RUN_MARKER + "\n", tail=defaults.SPRINT_RUN_MARKER_END + "\n")
    if comment_id is None:
        return github._comment_id(gh.api("POST", gh.path("issues", tracker, "comments"), {"body": text}))
    return github._comment_id(gh.api("PATCH", gh.path("issues", "comments", comment_id), {"body": text}), comment_id)


def base_red_comment(gh, tracker, sha, red, problem):
    """§2.7: a red base check stops the sprint; the failing command NAMES (codes) go to the tracking Issue."""
    body = ("**Guild (gld) — the sprint did not start: the base is red**\n\n"
            f"- base: `{sha}`\n- red commands: {', '.join(f'`{n}`' for n in red) or '—'}\n"
            + (f"- not checked: `{problem}`\n" if problem else ""))
    return github.post_comment(gh, tracker, body, marker="sprint-base-red")


def default_branch(gh):
    """The repository's default branch name. GhError when GitHub does not say."""
    raw = gh.call("repo", "view", gh.repo, "--json", "defaultBranchRef")
    try:
        name = (json.loads(raw).get("defaultBranchRef") or {}).get("name")
    except (ValueError, AttributeError):
        name = None
    if not isinstance(name, str) or not name or name.startswith("-") or any(c.isspace() for c in name):
        raise github.GhError("repo view: no default branch in the answer")
    return name


def merge_settings(gh):
    """{"merge", "squash", "rebase"} bools of `gh repo view --json mergeCommitAllowed,…`, or None when GitHub does
    not say (§2.4: then no stacking)."""
    keys = {"merge": "mergeCommitAllowed", "squash": "squashMergeAllowed", "rebase": "rebaseMergeAllowed"}
    try:
        got = json.loads(gh.call("repo", "view", gh.repo, "--json", ",".join(keys.values())))
    except (github.GhError, ValueError):
        return None
    out = {k: got.get(v) if isinstance(got, dict) else None for k, v in keys.items()}
    return out if all(isinstance(v, bool) for v in out.values()) else None


def issue_facts(gh, number):
    """{"number", "state", "state_reason", "labels"} of a member Issue, read fresh before it is started."""
    row = _issue_row(gh, number)
    return {"number": number, "state": row["state"], "state_reason": row["stateReason"], "labels": row["labels"]}


def _pr(row, branch):
    """One pull request as DepFacts holds it; GhError on anything unexpected."""
    if not isinstance(row, dict):
        raise github.GhError("pull request: not an object")
    n, head, base = row.get("number"), row.get("head") or {}, row.get("base") or {}
    state = "MERGED" if row.get("merged_at") else str(row.get("state") or "").upper()
    if (isinstance(n, bool) or not isinstance(n, int) or state not in PR_STATES or head.get("ref") != branch
            or not _SHA.match(str(head.get("sha"))) or not isinstance(base.get("ref"), str) or not base["ref"]):
        raise github.GhError(f"pull request of {branch}: unexpected answer (number {n!r}, state {state!r}, "
                             f"head {head.get('ref')!r})")
    return {"number": n, "state": state, "head_sha": head["sha"], "base": base["ref"]}


def _prs_of(gh, branch):
    rows = gh.api("GET", gh.path("pulls?head=" + github._q(gh.owner + ":" + branch) + "&state=all"))
    if not isinstance(rows, list):
        raise github.GhError("pulls list: not a list")
    return [_pr(r, branch) for r in rows]


def dep_facts(gh, dep, local, outcome=None):
    """sprintdag.DepFacts of dependency `dep`. `local` = its state.json facts on this machine (the supervisor
    reads them), `outcome` = its outcome in this run. The PR: local pr_number first, else the PRs of head
    `gld/<dep>` — never a name guess (§2.3)."""
    issue = issue_facts(gh, dep)
    branch = BRANCH_PREFIX + str(dep)
    number = (local or {}).get("pr_number")
    prs = _prs_of(gh, branch) if number is None else [_pr(gh.api("GET", gh.path("pulls", number)), branch)]
    if number is not None and prs[0]["number"] != number:
        raise github.GhError(f"pulls/{number}: answered for {prs[0]['number']}")
    return sprintdag.DepFacts(issue=dep, issue_state=issue["state"], state_reason=issue["state_reason"], prs=prs,
                              local=local, outcome=outcome)


def member_prs(gh, number):
    """Readiness R1 (records cleanup): every pull request headed by `gld/<number>` [{number, state, head_sha, base}].
    GhError on anything unexpected."""
    return _prs_of(gh, BRANCH_PREFIX + str(github._number(number)))


def engine_branches(gh):
    """Readiness T1 P7: the Issue numbers N whose engine branch `gld/<N>` is on GitHub (one prefix read of
    git/matching-refs/heads/gld/, every page). GhError on anything unexpected."""
    refs = gh.api("GET", gh.path("git", "matching-refs", "heads", BRANCH_PREFIX), paginate=True)
    if not isinstance(refs, list) or not all(isinstance(r, dict) and isinstance(r.get("ref"), str) for r in refs):
        raise github.GhError("matching-refs: unexpected answer")
    head = "refs/heads/" + BRANCH_PREFIX
    return sorted({int(r["ref"][len(head):]) for r in refs
                   if r["ref"].startswith(head) and r["ref"][len(head):].isdigit() and r["ref"][len(head)] != "0"})


def remote_state(gh, number):
    """H10: {"branch": bool, "open_pr": int or None} of `gld/<number>` on GitHub (before a start without state.json)."""
    branch = BRANCH_PREFIX + str(github._number(number))
    refs = gh.api("GET", gh.path("git", "matching-refs", "heads", branch))        # a prefix search: exact name below
    if not isinstance(refs, list) or not all(isinstance(r, dict) and isinstance(r.get("ref"), str) for r in refs):
        raise github.GhError("matching-refs: unexpected answer")
    open_prs = [p["number"] for p in _prs_of(gh, branch) if p["state"] == "OPEN"]
    return {"branch": any(r["ref"] == "refs/heads/" + branch for r in refs), "open_pr": min(open_prs, default=None)}
