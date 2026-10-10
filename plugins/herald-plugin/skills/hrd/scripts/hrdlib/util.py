"""Shared helpers: process execution, git/gh wrappers, JSON files.

Everything that talks to git or GitHub goes through `git()` / `gh_json()` so tests can point
`HRD_GH` at a fake `gh` and run against a throwaway repository.
"""

import datetime
import json
import os
import subprocess
import sys
import tempfile


class HeraldError(Exception):
    """A precondition failed. The message is shown to the human as-is."""


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def run(args, cwd=None, check=True, input_text=None, env=None):
    proc = subprocess.run(
        args, cwd=cwd, input=input_text, capture_output=True, text=True, env=env
    )
    if check and proc.returncode != 0:
        raise HeraldError(
            "command failed (%d): %s\n%s" % (proc.returncode, " ".join(args), proc.stderr.strip())
        )
    return proc


def git(root, *args, check=True):
    return run(["git", *args], cwd=root, check=check).stdout


def git_ok(root, *args):
    return run(["git", *args], cwd=root, check=False).returncode == 0


def gh_bin():
    return os.environ.get("HRD_GH", "gh")


def gh(root, *args, check=True):
    return run([gh_bin(), *args], cwd=root, check=check).stdout


def gh_json(root, *args):
    out = gh(root, *args)
    return json.loads(out) if out.strip() else []


def repo_root(start=None):
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and os.path.isdir(env) and start is None:
        start = env
    out = run(["git", "rev-parse", "--show-toplevel"], cwd=start or os.getcwd(), check=False)
    if out.returncode != 0:
        raise HeraldError("not inside a git repository")
    return out.stdout.strip()


def herald_dir(root):
    return os.path.join(root, ".claude", "herald")


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    """Atomic write so an interrupted command never leaves a half-written state file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def append_jsonl(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def fail(msg, code=1):
    sys.stderr.write(msg.rstrip() + "\n")
    sys.exit(code)
