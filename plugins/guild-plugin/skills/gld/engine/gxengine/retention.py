"""Engine records cleanup (readiness R1 — design/guild/24-redesign/readiness/incidents.md §7).

  - `prune_members` (retro): a sprint member whose pull requests are all merged or closed (at least one, none
    open) loses records/<owner>/<repo>/<N>/ and tmp/<owner>/<repo>/<N>/. A records folder an incident names is
    kept (its tmp goes). An Issue an engine runs on, or whose pull requests could not be read, is not touched.
  - `stale` / `remove_stale` (`/gld status`): Issue records whose last activity (state.json, log.jsonl, engine.rc)
    is older than `days` are listed; only the ones a human picked are removed, each checked again right before.
Sprint records (sprints/, base-green/), canary/ and init/ are never removed here. Nothing is removed without
`apply`.
"""

import os
import re
import stat
import time

from . import fsafe, incidents, lifecycle, paths as pathsmod, store

STALE_DAYS = 90
ACTIVITY_FILES = ("state.json", "log.jsonl", "engine.rc")
_PICK = re.compile(r"\A([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)\Z")

PR_MERGED, PR_CLOSED = "MERGED", "CLOSED"      # GitHub's words (sprinttracker.PR_STATES)


class Refused(Exception):
    """The command cannot run (no sprint record here)."""


def _size(path):
    total = 0
    for d, dirs, names in os.walk(path):
        dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
        for n in names:
            try:
                st = os.lstat(os.path.join(d, n))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
    return total


def _exists_dir(path):
    st = fsafe._lstat(path)
    return st is not None and stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def _running(paths):
    holder = lifecycle.lock_holder(paths)
    return holder is not None and holder.get("issue") == paths.issue


def _remove(paths, which):
    """Remove the Issue's records and / or tmp folder ("records", "tmp"). Returns {name: bytes removed}."""
    done = {}
    for name in which:
        path = paths.issue_dir if name == "records" else paths.tmp_root
        if _exists_dir(path):
            size = _size(path)
            incidents.remove_tree(path, paths.engine_home)
            done[name] = size
    return done


def prune_members(engine_home, repo, tracker, pr_facts, apply=False, only=None):
    """Retro: one row per sprint member {issue, action (removed / would-remove / kept), why, prs, records_bytes,
    tmp_bytes, removed}. `pr_facts(issue, state)` → [{"number", "state" MERGED/CLOSED/OPEN}] of its pull requests
    (raises on a read failure → kept, `pr-unknown`). `only` = the member numbers a human approved (None = all).
    Refused when this sprint was not run on this machine, or `only` names a non-member."""
    sp = pathsmod.SprintPaths(engine_home, repo, tracker)
    sprint = store.load_sprint(sp)
    if sprint is None:
        raise Refused("this sprint was not run on this machine")
    members = [m["issue"] for m in sprint["members"]]
    if only is not None and set(only) - set(members):
        raise Refused(f"not a member of sprint {tracker}: {sorted(set(only) - set(members))}")
    keep_refs = incidents.referenced_records(engine_home)
    rows = []
    for issue in members:
        if only is not None and issue not in only:
            continue
        paths = pathsmod.EnginePaths(engine_home, repo, issue)
        row = {"issue": issue, "action": "kept", "why": None, "prs": [],
               "records_bytes": _size(paths.issue_dir) if _exists_dir(paths.issue_dir) else 0,
               "tmp_bytes": _size(paths.tmp_root) if _exists_dir(paths.tmp_root) else 0, "removed": {}}
        rows.append(row)
        if not _exists_dir(paths.issue_dir) and not _exists_dir(paths.tmp_root):
            row["why"] = "nothing-here"
            continue
        if _running(paths):
            row["why"] = "running"
            continue
        try:
            state = store.load_state(paths)
        except (store.CorruptFile, store.FormatMismatch, fsafe.UnsafePath):
            state = None
        try:
            prs = [{"number": p["number"], "state": p["state"]} for p in pr_facts(issue, state)]
        except Exception as e:  # noqa: BLE001 — a fact that cannot be read keeps the records (fail-closed)
            row["why"] = "pr-unknown"
            row["note"] = f"{type(e).__name__}: {e}"[:300]
            continue
        row["prs"] = prs
        if not prs:
            row["why"] = "no-pr"
            continue
        if any(p["state"] not in (PR_MERGED, PR_CLOSED) for p in prs):
            row["why"] = "open-pr"
            continue
        referenced = os.path.realpath(paths.issue_dir) in keep_refs
        which = ("tmp",) if referenced else ("records", "tmp")
        row["why"] = "incident" if referenced else "pr-done"
        if referenced and not row["tmp_bytes"]:
            continue
        row["action"] = "would-remove"
        if apply:
            row["removed"] = _remove(paths, which)
            row["action"] = "removed"
    return rows


def _issue_dirs(engine_home):
    """(repo, issue) of every records/<owner>/<repo>/<N>/ folder (numbers only — sprints/ and base-green/ are not)."""
    records = os.path.join(engine_home, "records")
    out = []
    for owner in sorted(os.listdir(records)) if _exists_dir(records) else ():
        od = os.path.join(records, owner)
        if not _exists_dir(od):
            continue
        for name in sorted(os.listdir(od)):
            rd = os.path.join(od, name)
            if not _exists_dir(rd):
                continue
            for n in sorted(os.listdir(rd)):
                if n.isdigit() and n == str(int(n)) and int(n) >= 1 and _exists_dir(os.path.join(rd, n)):
                    try:
                        pathsmod.split_repo(f"{owner}/{name}")
                    except ValueError:
                        continue
                    out.append((f"{owner}/{name}", int(n)))
    return out


def last_activity(paths):
    """Epoch seconds of the Issue's last engine write (the newest of state.json, log.jsonl, engine.rc; the folder
    itself when none of them exists)."""
    times = []
    for name in ACTIVITY_FILES:
        st = fsafe._lstat(os.path.join(paths.issue_dir, name))
        if st is not None and stat.S_ISREG(st.st_mode):
            times.append(st.st_mtime)
    if not times:
        times.append(os.lstat(paths.issue_dir).st_mtime)
    return max(times)


def _judge_stale(paths, keep_refs, days, now):
    """(stale?, why-kept or None, last activity)."""
    last = last_activity(paths)
    if now - last <= days * 86400:
        return False, None, last
    if os.path.realpath(paths.issue_dir) in keep_refs:
        return False, "incident", last
    if _running(paths):
        return False, "running", last
    return True, None, last


def stale(engine_home, days=STALE_DAYS, now=None):
    """`/gld status`: {"days", "items": [{pick, repo, issue, last_activity, age_days, records_bytes, tmp_bytes}],
    "kept": [{pick, why}]} — the items oldest first. Nothing is removed."""
    now = time.time() if now is None else now
    keep_refs = incidents.referenced_records(engine_home)
    items, kept = [], []
    for repo, issue in _issue_dirs(engine_home):
        paths = pathsmod.EnginePaths(engine_home, repo, issue)
        ok, why, last = _judge_stale(paths, keep_refs, days, now)
        pick = f"{repo}#{issue}"
        if why:
            kept.append({"pick": pick, "why": why})
        if not ok:
            continue
        items.append({"pick": pick, "repo": repo, "issue": issue, "last_activity": store.now_ts(last),
                      "age_days": int((now - last) // 86400), "records_bytes": _size(paths.issue_dir),
                      "tmp_bytes": _size(paths.tmp_root) if _exists_dir(paths.tmp_root) else 0})
    items.sort(key=lambda r: r["last_activity"])
    return {"days": days, "items": items, "kept": kept}


def remove_stale(engine_home, picks, days=STALE_DAYS, now=None):
    """Remove the records (and tmp) of the picked `owner/repo#N`, each judged again right before. One row per pick
    {pick, action (removed / refused), why, removed}."""
    now = time.time() if now is None else now
    keep_refs = incidents.referenced_records(engine_home)
    rows = []
    for pick in picks:
        m = _PICK.match(pick or "")
        if not m:
            rows.append({"pick": pick, "action": "refused", "why": "not owner/repo#N", "removed": {}})
            continue
        try:
            paths = pathsmod.EnginePaths(engine_home, m.group(1), int(m.group(2)))
        except ValueError as e:
            rows.append({"pick": pick, "action": "refused", "why": str(e)[:200], "removed": {}})
            continue
        if not _exists_dir(paths.issue_dir):
            rows.append({"pick": pick, "action": "refused", "why": "no records", "removed": {}})
            continue
        ok, why, _last = _judge_stale(paths, keep_refs, days, now)
        if not ok:
            rows.append({"pick": pick, "action": "refused", "why": why or f"active within {days} days", "removed": {}})
            continue
        rows.append({"pick": pick, "action": "removed", "why": None, "removed": _remove(paths, ("records", "tmp"))})
    return rows
