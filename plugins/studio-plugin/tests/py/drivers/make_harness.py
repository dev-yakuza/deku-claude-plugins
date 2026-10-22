#!/usr/bin/env python3
"""A synthetic Studio harness for tests and the sandbox real-session check (m0f-plan §3). Test tree only —
`/std init` (M1) is the real way to set up a repository.

    make_harness.py <dir> [--studio-root studio] [--husky] [--overlay terms.json] [--s2v PATH]

Writes a git repository with the rendered templates, Studio's agents, a copy of the plugin's scripts (without the
guard), the ignore blocks, the pre-commit hook and this machine's `.claude/studio/local/machine.json` (`--s2v`; the
path is never committed), and makes the first commit outside any session
(`--no-verify`: what a person would do once). Everything is synthetic: no home paths, nothing internal."""

import hashlib
import json
import os
import shutil
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


def _render(rel, values):
    with open(os.path.join(TEMPLATES, rel), encoding="utf-8") as f:
        text = f.read()
    for k, v in values.items():
        text = text.replace("{{%s}}" % k, v)
    return text


def _git(repo, env, *args):
    out = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, env=env)
    if out.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), out.stderr))
    return out.stdout


def copy_scripts(repo):
    dst = os.path.join(repo, ".claude", "studio", "scripts")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__", "guard.py", "guard", "*.pyc"))
    return dst


def make(repo, env=None, studio_root="studio", husky=False, overlay=(), s2v="/nonexistent/script2video",
         python=None):
    env = dict(os.environ if env is None else env)
    python = python or sys.executable
    os.makedirs(repo)
    _git(repo, env, "init", "-q")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# Sandbox\n")
    values = {"LANGUAGE": "ko", "S2V_PATH": s2v, "PROJECT_NAME": "Sandbox", "PRIORITIES_BY_KIND": "sandbox",
              "PURPOSE": "sandbox", "STUDIO_ROOT": studio_root}
    st = os.path.join(repo, ".claude", "studio")
    os.makedirs(st)
    with open(os.path.join(st, "config.json"), "w") as f:
        json.dump(json.loads(_render("studio/config.json.tmpl", values)), f, indent=2)
        f.write("\n")
    with open(os.path.join(st, "charter.md"), "w") as f:
        f.write(_render("studio/charter.md.tmpl", values))
    os.makedirs(os.path.join(st, "guides"))
    with open(os.path.join(st, "guides", "script.md"), "w") as f:
        f.write("# Script guide\n\n- Say what the source says.\n")
    with open(os.path.join(repo, ".gitignore"), "w") as f:
        f.write("node_modules/\n" + _render("studio/gitignore.tmpl", values))
    agents = os.path.join(repo, ".claude", "agents")
    os.makedirs(agents)
    for n in sorted(os.listdir(os.path.join(TEMPLATES, "agents"))):
        if n.startswith("std-") and n.endswith(".md"):
            shutil.copy(os.path.join(TEMPLATES, "agents", n), os.path.join(agents, n))
    os.makedirs(os.path.join(repo, studio_root, "voices"))
    with open(os.path.join(repo, studio_root, "voices", ".keep"), "w"):
        pass
    copy_scripts(repo)
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
    args = [python, "-B", os.path.join(repo, ".claude", "studio", "scripts", "hooks.py"), "install"]
    if husky:
        args.append("--husky-apply")
    out = subprocess.run(args, cwd=repo, capture_output=True, text=True, env=env)
    if out.returncode != 0:
        raise RuntimeError("hooks.py install: %s%s" % (out.stdout, out.stderr))
    from stdo import machine
    machine.write(repo, s2v)  # this machine's s2v path (m1-plan §3.1): ignored, never committed
    if overlay == ():
        overlay = {"internal": {}}  # set up (with its machine sha) like /std init would; nothing internal yet
    if overlay is not None:
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
