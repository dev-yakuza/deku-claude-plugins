"""guildcore.state — the canonical stage derivation and the per-Issue snapshot.

`derive()` is `_handoff.md` Section A — canonical stage derivation, as code:

    stage: ([.labels[].name] | map(select(startswith("guild:") and . != "guild:child"
            and . != "guild:needs-human" and . != "guild:harness" and . != "guild:sprint"))
            | .[0] // "none")

`.[0]` is "the first such label in the order GitHub returned them", so `derive()` keeps the input
order and never sorts. Every consumer (status, resume routing, the board) goes through here.

`snapshot()` gathers one Issue in at most three gh reads (issue, comments, PR search) — §2.0.
"""

import re

STAGE_ORDER = ("analyze", "design", "execute", "test", "qa", "done")
# The four non-stage kinds, excluded from `stage` (Section A — "four kinds of row").
NON_STAGE = ("guild:child", "guild:needs-human", "guild:harness", "guild:sprint")
PARENT_RE = re.compile(r"Parent Issue: #(\d+)(?:[^0-9]|$)")
CLOSING_RE_T = r"(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s*:?\s*#{n}\b"


def label_names(labels):
    """Accept `[{"name": …}]` (gh --json labels) or plain strings; keep order."""
    out = []
    for lb in labels or []:
        if isinstance(lb, dict):
            out.append(lb.get("name") or "")
        else:
            out.append(str(lb))
    return out


class IssueState(object):
    """`derive()`'s result. `label` is the raw stage label (`guild:test`) or `"none"`;
    `stage` is its short name (`test`, `children`, `none`); `ordinal` indexes STAGE_ORDER and is
    None for `children` / `none` (an orchestration state has no ordinal — Section A)."""

    __slots__ = ("label", "stage", "ordinal", "paused", "child", "harness", "sprint", "children")

    def __init__(self, label, paused, child, harness, sprint):
        self.label = label
        self.stage = label[len("guild:"):] if label.startswith("guild:") else "none"
        self.ordinal = STAGE_ORDER.index(self.stage) if self.stage in STAGE_ORDER else None
        self.paused = paused
        self.child = child
        self.harness = harness
        self.sprint = sprint
        self.children = self.stage == "children"

    def as_jq(self):
        """The exact object the Section A jq prints (keys in its order)."""
        return {"stage": self.label, "paused": self.paused, "harness": self.harness,
                "child": self.child, "sprint": self.sprint}

    def at_least(self, stage):
        """label ≥ `stage` in the ordinal chain (False for children/none)."""
        return self.ordinal is not None and self.ordinal >= STAGE_ORDER.index(stage)

    def __repr__(self):
        return "IssueState(%r)" % (self.as_jq(),)


def derive(labels):
    names = label_names(labels)
    stage = "none"
    for n in names:
        if n.startswith("guild:") and n not in NON_STAGE:
            stage = n
            break
    return IssueState(stage, "guild:needs-human" in names, "guild:child" in names,
                      "guild:harness" in names, "guild:sprint" in names)


def labels_csv(labels):
    """batch/supervisor's flattened form: `map(select(startswith("guild:"))) | join(",")`."""
    return ",".join(n for n in label_names(labels) if n.startswith("guild:"))


def parent_of(body):
    m = PARENT_RE.search(body or "")
    return int(m.group(1)) if m else None


def closing_re(number):
    return re.compile(CLOSING_RE_T.format(n=int(number)))


class PrMatch(object):
    """status.md step 5: `strict` (a closing reference) is authoritative; `candidates` are what
    the old prose left to a judgment — the engine lists them without judging (Q-PR-MATCH)."""

    def __init__(self, strict, candidates):
        self.strict = strict
        self.candidates = candidates


def match_prs(number, prs):
    rx = closing_re(number)
    strict = [{"number": p.get("number"), "url": p.get("url"), "state": p.get("state")}
              for p in prs if rx.search(p.get("body") or "")]
    cands = [{"number": p.get("number"), "url": p.get("url"), "state": p.get("state"),
              "title": p.get("title")} for p in prs]
    return PrMatch(strict, cands)


class IssueSnapshot(object):
    """Everything the read-only consumers need about one Issue."""

    def __init__(self, number, issue, comments, prs):
        from guildcore.records import outputs, loopback, audit, needs_human
        from guildcore import decisions
        self.number = number
        self.title = issue.get("title") or ""
        self.body = issue.get("body") or ""
        self.url = issue.get("url") or ""
        self.issue_state = issue.get("state") or ""
        self.state_reason = issue.get("stateReason") or ""
        self.labels = label_names(issue.get("labels"))
        self.state = derive(self.labels)
        self.comments = sorted(comments or [], key=lambda c: c.get("id") or 0)
        self.markers = outputs.presence(self.comments)
        self.loopback = loopback.from_comments(self.comments)
        self.audit = audit.from_comments(self.comments)
        self.pauses = needs_human.from_comments(self.comments)
        self.decisions = decisions.DecisionLog.load(self.comments)
        self.parent = parent_of(self.body)
        self.pr = match_prs(number, prs or [])

    @property
    def is_pr(self):
        return "/pull/" in self.url

    def unmarked_comments_since(self, ts):
        """Comments a human wrote (Section M: no `<!-- guild:` anywhere) after `ts` (ISO)."""
        out = []
        for c in self.comments:
            body = c.get("body") or ""
            if "<!-- guild:" in body:
                continue
            if ts and (c.get("created_at") or "") <= ts:
                continue
            out.append(c)
        return out


def snapshot(gh, number):
    """≤ 3 gh reads: the Issue, its comments (paginated), the PR search."""
    issue = gh.issue(number)
    comments = gh.comments(number)
    prs = gh.pr_search(number)
    return IssueSnapshot(number, issue, comments, prs)


def list_snapshots(gh, state="open", label=None, limit=200):
    """The list form of Section A: `{number, title, stage, paused, …}` per Issue, one gh read."""
    rows = []
    for it in gh.issue_list(state=state, label=label, limit=limit):
        st = derive(it.get("labels"))
        rows.append({"number": it.get("number"), "title": it.get("title") or "",
                     "state": it.get("state") or "", "stateReason": it.get("stateReason") or "",
                     "body": it.get("body") or "", "labels": label_names(it.get("labels")),
                     "derived": st})
    return rows


def discover_children(gh, parent):
    """status.md split-parent discovery (DISPLAY only — the engine knows its own children by its journal,
    `stages.base.own_children`): every `guild:child` Issue through the REST issues list (database-backed,
    all pages — K4r3-B1/m3: `gh issue list --label` is the search index and stopped at 200), body
    `Parent Issue: #<parent>([^0-9]|$)`, sorted by number."""
    rx = re.compile(r"Parent Issue: #%d(?:[^0-9]|$)" % int(parent))
    rows = []
    for it in gh.issue_rows(label="guild:child", state="all"):
        if not rx.search(it.get("body") or ""):
            continue
        rows.append({"number": it.get("number"), "title": it.get("title") or "", "state": it.get("state") or "",
                     "stateReason": it.get("stateReason") or "", "body": it.get("body") or "",
                     "labels": label_names(it.get("labels")), "derived": derive(it.get("labels"))})
    return sorted(rows, key=lambda r: r["number"])
