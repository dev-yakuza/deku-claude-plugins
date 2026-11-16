"""workflows.status.running — `status running` and `status directives` (§2.10; downgrade runbook
①/①b, §10.5). Both read only.

running: each `<git-common-dir>/guild/engine/<N>.lock` is probed with a non-blocking flock on a
READ-ONLY descriptor (nothing is created or written); a lock someone holds is a live engine. The
lock file's JSON (`mode`, `pid`, `pgid`, `started`) is K1's format — read tolerantly here.
`--all-repos` walks the config-dir registry `${CLAUDE_CONFIG_DIR:-~/.claude}/guild-engine/repos.json`
(keys = absolute git common dirs); a missing entry is skipped and reported.
"""

import fcntl
import glob
import json
import os
import re
import subprocess

from guildcore import journal
from guildcore.decisions import DecisionLog
from guildcore.state import list_snapshots


def git_common_dir(cwd="."):
    p = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace").strip()


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


def probe(lock):
    """(held, info) — held=True when another process holds the flock."""
    try:
        fd = os.open(lock, os.O_RDONLY)
    except OSError:
        return False, {}
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = False
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            held = True
        try:
            info = json.loads(os.read(fd, 65536).decode("utf-8", "replace") or "{}")
        except ValueError:
            info = {}
        return held, info if isinstance(info, dict) else {}
    finally:
        os.close(fd)


def running(common_dirs):
    rows, missing = [], []
    for cd in common_dirs:
        if not os.path.isdir(cd):
            missing.append(cd)
            continue
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


def render_running(rows, missing):
    out = []
    for r in rows:
        out.append("#%d  %s  mode=%s pid=%s pgid=%s started=%s" % (
            r["issue"], r["repo"], r["mode"] or "?", r["pid"] or "?", r["pgid"] or "?",
            r["started"] or "?"))
    if not rows:
        out.append("no engine running")
    for m in missing:
        out.append("skipped (registry entry no longer exists): %s" % m)
    return "\n".join(out) + "\n"


def directives(gh, open_only=True):
    """`by: human` `point: directive` blocks of open Issues (redacted text as stored)."""
    out = []
    for r in list_snapshots(gh, state="open" if open_only else "all"):
        if not any(l.startswith("guild:") for l in r["labels"]):
            continue
        log = DecisionLog.load(gh.comments(r["number"]))
        for b in log.directives():
            out.append({"issue": r["number"], "id": b.id, "at": b.get("at"),
                        "text": b.get("text") or b.get("reason") or b.get("choice") or ""})
    return out


def render_directives(rows):
    if not rows:
        return "no open directive blocks\n"
    return "\n".join("#%d %s %s — %s" % (r["issue"], r["id"], r["at"] or "?", r["text"])
                     for r in rows) + "\n"
