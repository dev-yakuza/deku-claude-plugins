"""Shared by setup.py's commands: the repository, errors, the person's evidence, file writes."""

import json
import os
import subprocess

from .. import paths
from ..state import evidence

OK, FAIL, USAGE, REFUSED, WAIT, NO_EVIDENCE = 0, 1, 2, 3, 4, 6


class SetupError(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code


def git(top, *args, check=True):
    out = subprocess.run(["git", "-C", top] + list(args), capture_output=True, text=True, env=paths.git_env())
    if check and out.returncode != 0:
        raise SetupError(USAGE, "git %s failed: %s" % (" ".join(args), out.stderr.strip()))
    return out


def toplevel(cwd):
    out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         env=paths.git_env())
    if out.returncode != 0:
        raise SetupError(USAGE, "not inside a git repository: %s" % cwd)
    return out.stdout.strip()


def read_config(top):
    p = os.path.join(top, ".claude", "studio", "config.json")
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except OSError:
        raise SetupError(USAGE, "no Studio harness here (.claude/studio/config.json is missing) — /std init first")
    except ValueError as e:
        raise SetupError(USAGE, ".claude/studio/config.json is not JSON (%s)" % e)
    if not isinstance(cfg, dict):
        raise SetupError(USAGE, ".claude/studio/config.json is not an object")
    return cfg


def write_text(top, rel, text):
    """Write a repository file atomically (folders created). Refuses a symbolic link on the way."""
    p = os.path.join(top, rel)
    cur = top
    for part in rel.split("/")[:-1]:
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            raise SetupError(FAIL, "%s is a symbolic link — Studio does not write through it" % os.path.relpath(cur, top))
    if os.path.islink(p):
        raise SetupError(FAIL, "%s is a symbolic link — Studio does not write through it" % rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    return p


def with_evidence(top, argv, label, proxy, action, cmd):
    """The person's answer for `argv` (the guard wrote it), checked and used once, then `action()`."""
    if proxy:
        raise SetupError(USAGE, "this records the person's own decision: the proxy mode cannot (--proxy refused)")
    why = paths.local_problem(top)
    if why:
        raise SetupError(USAGE, why)
    with evidence.ConsumptionLock(top):
        try:
            ev = evidence.check(top, argv, label, False)
        except evidence.Missing as e:
            raise SetupError(NO_EVIDENCE, str(e))
        evidence.consume(top, ev, None, cmd)
        result = action()
        evidence.remove_pending(top)
    return result
