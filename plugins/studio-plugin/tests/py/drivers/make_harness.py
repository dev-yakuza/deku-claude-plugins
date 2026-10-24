#!/usr/bin/env python3
"""A synthetic Studio harness for tests and the sandbox real-session check (m0f-plan §3). Test tree only — a thin
wrapper over setup.py's `init plan|apply` (M1c), which is the real way to set up a repository.

    make_harness.py <dir> [--studio-root studio] [--husky] [--overlay terms.json] [--s2v PATH]

Writes a git repository with the rendered templates, Studio's agents, a copy of the plugin's scripts (without the
guard), the ignore blocks, the pre-commit hook and this machine's `.claude/studio/local/machine.json` (`--s2v`; the
path is never committed), and makes the first commit outside any session
(`--no-verify`: what a person would do once). Everything is synthetic: no home paths, nothing internal."""

import hashlib
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SKILL = os.path.join(PLUGIN, "skills", "std")
SCRIPTS = os.path.join(SKILL, "scripts")
TEMPLATES = os.path.join(SKILL, "templates")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def _git(repo, env, *args):
    out = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, env=env)
    if out.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), out.stderr))
    return out.stdout


def copy_scripts(repo):
    """The plugin's scripts as /std init copies them (exactly the manifest's files)."""
    from stdo.setup import initcmd
    return initcmd.copy_scripts(repo)


ANSWERS = {"language": "ko", "project_name": "Sandbox", "purpose": "sandbox", "priorities": "sandbox",
           "narrator": {"style": "차분하게"}}


def make(repo, env=None, studio_root="studio", husky=False, overlay=(), s2v="/nonexistent/script2video",
         python=None):
    """A harness made by setup.py's own init (m1-plan §5.1: make_harness is a thin wrapper), committed once outside
    any session. `python` is kept for older callers (the hook runs python3 from PATH)."""
    env = dict(os.environ if env is None else env)
    from stdo import writes
    from stdo.setup import initcmd
    writes.enable()  # a test-tree driver: it stands in for /std init (setup.py)
    os.makedirs(repo)
    _git(repo, env, "init", "-q")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# Sandbox\n")
    with open(os.path.join(repo, ".gitignore"), "w") as f:
        f.write("node_modules/\n")
    if husky:
        os.makedirs(os.path.join(repo, ".husky", "_"))
        with open(os.path.join(repo, ".husky", "pre-commit"), "w") as f:
            f.write("npm test\n")
        with open(os.path.join(repo, ".husky", "_", "pre-commit"), "w") as f:
            f.write("#!/bin/sh\n. \"$(dirname \"$0\")/../pre-commit\"\n")
        os.chmod(os.path.join(repo, ".husky", "_", "pre-commit"), 0o755)
        with open(os.path.join(repo, "package.json"), "w") as f:
            f.write('{"name": "sandbox", "devDependencies": {"husky": "9.1.7"}}\n')
        _git(repo, env, "config", "core.hooksPath", ".husky/_")
    answers = dict(ANSWERS, studio_root=studio_root, s2v_path=s2v, husky=husky)
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)  # STUDIO_HOME and friends: the marker and the overlay sha go to the test's folders
    try:
        plan = initcmd.plan(repo, answers, check_s2v=False)
        res = initcmd.apply(repo, plan, env=env, check_s2v=False)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    if res["hooks"]["code"] not in (0,):
        raise RuntimeError("hooks install: %s" % res["hooks"])
    with open(os.path.join(repo, studio_root, "voices", ".keep"), "w"):
        pass
    if overlay != ():
        if overlay is None:
            os.remove(os.path.join(repo, ".claude", "studio", "local", "config.internal.json"))
        else:
            write_overlay(repo, overlay, env)
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-q", "--no-verify", "-m", "sandbox harness (set up outside any session)")
    return repo


def write_overlay(repo, data, env=None):
    env = dict(os.environ if env is None else env)
    from stdo import paths
    p = os.path.join(repo, ".claude", "studio", "local", "config.internal.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    with open(p, "wb") as f:
        f.write(raw)
    d = os.path.join(paths.backup_root(env), paths.repo_key(repo))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "overlay.sha"), "w") as f:
        f.write(hashlib.sha256(raw).hexdigest() + "\n")


def main(argv):
    if not argv:
        sys.stderr.write(__doc__)
        return 2
    repo = os.path.abspath(argv[0])

    def opt(n, d=None):
        return argv[argv.index(n) + 1] if n in argv else d
    overlay = None
    if "--overlay" in argv:
        with open(opt("--overlay")) as f:
            overlay = json.load(f)
    make(repo, studio_root=opt("--studio-root", "studio"), husky="--husky" in argv, overlay=overlay,
         s2v=opt("--s2v", "/nonexistent/script2video"))
    print(repo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
