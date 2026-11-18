"""workflows.status.running — `status running` and `status directives` (§2.10; downgrade runbook
①/①b, §10.5). Both read only.

running: each `<git-common-dir>/guild/engine/<N>.lock` is judged WITHOUT touching the lock
(K0-m5 — taking the flock even briefly made a real start see "busy"): the lock file's JSON
(`mode`, `pid`, `pgid`, `started`) names the holder, and the holder is live when that pid
exists. Format decision for K1: the lock holder writes that JSON (pid + its start time) right
after taking the flock and keeps the flock for its lifetime; a pid-less lock file reads as
"unknown holder", never as "not running".
A git common dir that cannot be resolved is an ERROR, never "no engine running" (K0-M6 — this is
the downgrade runbook's safety check).
`--all-repos` walks the config-dir registry `${CLAUDE_CONFIG_DIR:-~/.claude}/guild-engine/repos.json`
(keys = absolute git common dirs); a missing entry is skipped and reported.
"""

import errno
import glob
import time
import json
import os
import re
import subprocess

from guildcore import journal
from guildcore.decisions import DecisionLog
from guildcore.state import list_snapshots


STALE_S = 600


class RunningError(Exception):
    pass


def git_common_dir(cwd="."):
    """Absolute git common dir. `--path-format=absolute` needs git ≥ 2.31; older git falls back
    to the plain form resolved against `cwd`. Unresolvable → RunningError."""
    def rp(args):
        try:
            p = subprocess.run(["git", "rev-parse"] + args, cwd=cwd,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            return None
        out = p.stdout.decode("utf-8", "replace").strip()
        return out if p.returncode == 0 and out and not out.startswith("--") else None
    cd = rp(["--path-format=absolute", "--git-common-dir"])
    if cd is None:
        cd = rp(["--git-common-dir"])
        if cd is not None:
            cd = os.path.abspath(os.path.join(cwd, cd))
    if cd is None or not os.path.isdir(cd):
        raise RunningError("cannot resolve git common dir — not a git repo, or git failed")
    return cd


def registry_path(env=None):
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "guild-engine", "repos.json")


def registry(env=None):
    try:
        with open(registry_path(env), encoding="utf-8") as fh:
            data = json.load(fh)
    except (IOError, ValueError):
        return []
    return sorted(data.keys()) if isinstance(data, dict) else []


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (ValueError, TypeError):
        return False
    except OSError as e:
        return e.errno == errno.EPERM          # exists, owned by someone else
    return True


def probe(lock):
    """(held, info) without taking the lock: held = the recorded pid is alive; a lock file with
    no readable pid is reported as held by an unknown holder (fail toward "running")."""
    try:
        with open(lock, encoding="utf-8") as fh:
            raw = fh.read()
    except (IOError, OSError, UnicodeDecodeError):
        return True, {"mode": "unreadable-lock"}        # fail toward "running" (K0-m18)
    try:
        info = json.loads(raw or "{}")
    except ValueError:
        info = {}
    if not isinstance(info, dict):
        info = {}
    if info.get("pid") is None:
        # A holder that died before writing its JSON leaves this forever; tell the two apart by
        # age so a human can clear a stale one (K1 writes the JSON atomically — k0-notes).
        try:
            age = time.time() - os.path.getmtime(lock)
        except OSError:
            age = 0
        mode = "stale-unknown" if age > STALE_S else "unknown-holder"
        return True, dict(info, mode=info.get("mode") or mode)
    alive = pid_alive(info["pid"])
    if alive and info.get("pstart"):
        # K1 lock holders record their process start time: a reused pid is not a live engine
        from guildcore.adapters.claude import process_start
        alive = process_start(info["pid"]) == info["pstart"]
    return alive, info


def running(common_dirs, halts=None):
    """(rows, missing); `halts` (a list, K5r1-m3) collects every common dir whose kill switch `HALT` is on —
    the runbook's "no repository still has HALT" check reads it from this same command."""
    rows, missing = [], []
    for cd in common_dirs:
        if not os.path.isdir(cd):
            missing.append(cd)
            continue
        if halts is not None and os.path.exists(os.path.join(journal.engine_dir(cd), "HALT")):
            halts.append(cd)
        for lock in sorted(glob.glob(os.path.join(journal.engine_dir(cd), "*.lock"))):
            m = re.match(r"^(\d+)\.lock$", os.path.basename(lock))
            if not m:
                continue
            held, info = probe(lock)
            if held:
                rows.append({"repo": cd, "issue": int(m.group(1)), "mode": info.get("mode"),
                             "pid": info.get("pid"), "pgid": info.get("pgid"),
                             "started": info.get("started")})
    return rows, missing


def render_running(rows, missing, halts=()):
    out = []
    for h in halts:
        out.append("HALT  %s  (kill switch on — `dev valve resume` there, or `--all`)" % h)
    if not halts:
        out.append("HALT: none")
    for r in rows:
        out.append("#%d  %s  mode=%s pid=%s pgid=%s started=%s" % (
            r["issue"], r["repo"], r["mode"] or "?", r["pid"] or "?", r["pgid"] or "?",
            r["started"] or "?"))
    if not rows:
        out.append("no engine running")
    for m in missing:
        out.append("skipped (registry entry no longer exists): %s" % m)
    return "\n".join(out) + "\n"


def own_comment_ids(n, common=None):
    """The engine's own comment ids of #n from this clone's journal ([] when there is none here)."""
    try:
        from guildcore.journal import Journal
        return Journal(common or git_common_dir("."), n).own_comment_ids()
    except Exception:                                            # noqa: BLE001 — no journal here: association only
        return []


def repo_of(common_dir):
    """owner/repo of a registered clone (its origin remote), or None."""
    try:
        p = subprocess.run(["git", "--git-dir", common_dir, "remote", "get-url", "origin"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?\s*$", p.stdout.decode("utf-8", "replace"))
    return m.group(1) if p.returncode == 0 and m else None


def directives(gh, open_only=True, common=None):
    """`by: human` `point: directive` blocks of open Issues (redacted text as stored)."""
    out = []
    for r in list_snapshots(gh, state="open" if open_only else "all"):
        if not any(l.startswith("guild:") for l in r["labels"]):
            continue
        # K5: only engine/member-written decision comments (a stranger's comment carrying the marker is not a
        # directive — the runbook asks a person to RE-POST these as their own words)
        from guildcore.records import markers
        log = DecisionLog.load(markers.trusted(gh.comments(r["number"]), own_comment_ids(r["number"], common)))
        for b in log.directives():
            out.append({"issue": r["number"], "id": b.id, "at": b.get("at"), "repo": getattr(gh, "repo", None),
                        "text": b.get("text") or b.get("reason") or b.get("choice") or ""})
    return out


def render_directives(rows):
    if not rows:
        return "no open directive blocks\n"
    return "\n".join("%s#%d %s %s — %s" % ((r["repo"] + " ") if r.get("repo") else "", r["issue"], r["id"],
                                            r["at"] or "?", r["text"]) for r in rows) + "\n"
