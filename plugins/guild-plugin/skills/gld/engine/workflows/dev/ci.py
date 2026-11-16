"""workflows.dev.ci — qa Step 2 `### PR CI`: one line, a record not a gate (qa.md, C §2.Q Q2.2).

    no PR                          → `PR CI: 없음`
    0 check-runs                   → `PR CI: 없음(check-run 없음 — commit status 는 보지 않음)`
    failure|timed_out|cancelled|action_required → red; a run whose annotation says
                                     `was not started` → `시작되지 않음 <names> (env: ci-blocked)`
                                     (both forms on one line when both occur)
    else any conclusion null       → `진행 중`
    else                           → `green` (`neutral`, `skipped` are not red)
At most 3 failed runs with annotations > 0 have their annotations read. `base-red` needs a run
URL showing the same check red without this change (Q-CI-BASE, a judgment) — the engine records
plain `red` (conservative: a base-red stop is only a cause-line refinement of a habit stop).
"""

RED = ("failure", "timed_out", "cancelled", "action_required")
NOT_STARTED = "was not started"


class CiRecord(object):
    def __init__(self, cls, line, red=(), never_started=(), head=None, runs=()):
        self.cls = cls                    # none | no-runs | red | not-started | red+not-started | pending | green
        self.line = line
        self.red = list(red)
        self.never_started = list(never_started)
        self.head = head
        self.runs = list(runs)

    @property
    def is_red(self):
        return bool(self.red or self.never_started)


def record(gh, pr, head=None):
    """`pr` = the PR dict from Step 2.5's lookup (or None). `head` = the sha the ENGINE just pushed
    (qa committed tests) — GitHub's `headRefOid` can lag a fresh push (replay #1799), so the
    pushed sha wins over a re-read."""
    if not pr:
        return CiRecord("none", "PR CI: 없음")
    head = head or pr.get("headRefOid")
    if not head:
        head = (gh.pr(pr["number"]) or {}).get("headRefOid")
    runs = gh.check_runs(head) if head else []
    return classify(runs, lambda rid: gh.annotations(rid), head)


def classify(runs, annotations, head=None):
    if not runs:
        return CiRecord("no-runs", "PR CI: 없음(check-run 없음 — commit status 는 보지 않음)", head=head)
    red, never = [], []
    looked = 0
    for r in runs:
        if (r.get("conclusion") or None) not in RED:
            continue
        name = r.get("name") or str(r.get("id"))
        started = True
        if r.get("conclusion") == "failure" and (r.get("annotations") or 0) > 0 and looked < 3:
            looked += 1
            if any(NOT_STARTED in (m or "") for m in annotations(r.get("id"))):
                started = False
        (red if started else never).append(name)
    parts = []
    if red:
        parts.append("red %s" % " ".join(red))
    if never:
        parts.append("시작되지 않음 %s (env: ci-blocked)" % " ".join(never))
    if parts:
        cls = "red+not-started" if red and never else ("red" if red else "not-started")
        return CiRecord(cls, "PR CI: " + " · ".join(parts), red, never, head, runs)
    if any(r.get("conclusion") is None for r in runs):
        return CiRecord("pending", "PR CI: 진행 중", head=head, runs=runs)
    return CiRecord("green", "PR CI: green", head=head, runs=runs)
