#!/usr/bin/env python3
"""replay.k3r2_local_checks — K3r2-M2/m6 measurement on a word_app SCRATCH clone (never the real repo):
the K1 deps step (pub get + npm + the `npx` tools the hook names, under the registry proxy), then ONE
1L-shaped staged change (a lib .dart, its test, a docs .md, a release note) and every check derived
from the clone's `lefthook.yml` run OFFLINE in the 1L sandbox (`ports.local_sandbox`), then the gate
`--git-hook`, then — after the engine's warm-up — one `flutter test` inside the 1L sandbox.

    k3r2_local_checks.py --repo ~/projects/word_app --work <dir> --copy-ignored a,b --out FILE.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from guildcore import checks as CH                        # noqa: E402
from guildcore.adapters import claude as C                # noqa: E402
from guildcore.roles import settings as S                 # noqa: E402
from workflows.dev import local_checks as LC              # noqa: E402
from workflows.dev import ports as PO                     # noqa: E402


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()


def tail(t, n=4):
    return CH.redact_lines("\n".join(x[:160] for x in (t or "").rstrip().split("\n")[-n:]))


def append(path, text):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--copy-ignored", default="")
    ap.add_argument("--flutter-bin", default=os.path.expanduser("~/fvm/default/bin"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    work = os.path.realpath(a.work)
    clone = os.path.join(work, "clone")
    if not os.path.exists(clone):
        sh(work, "git", "clone", "-q", "--no-hardlinks", a.repo, clone)
    copy_list = [x for x in a.copy_ignored.split(",") if x]
    for g in copy_list:
        if os.path.isfile(os.path.join(a.repo, g)):
            os.makedirs(os.path.dirname(os.path.join(clone, g)), exist_ok=True)
            shutil.copy2(os.path.join(a.repo, g), os.path.join(clone, g))
    run = os.path.join(work, "run")
    for d in ("in", "out", "tmp"):
        os.makedirs(os.path.join(run, d), exist_ok=True)
    base_env = dict(os.environ)
    base_env["PATH"] = a.flutter_bin + os.pathsep + base_env.get("PATH", "")
    env = C.child_env(base_env, {}, role_dir=run)
    env.update(S.render_gitconfig(clone, os.path.join(run, "in", "gitconfig")))
    with open(os.path.join(clone, "lefthook.yml"), encoding="utf-8") as fh:
        dropped = []
        checks = LC.derive(fh.read(), {}, dropped)
    out = {"head": sh(clone, "git", "rev-parse", "HEAD").strip(), "checks": [c.name for c in checks],
           "dropped": dropped, "npx_tools": LC.npx_tools(checks)}
    t0 = time.time()
    d = PO.deps_main(clone, run, env, copy_list, 0, tools=LC.npx_tools(checks))
    out["deps"] = {"passed": d.passed, "secs": round(time.time() - t0, 1), "proxy": getattr(d, "proxy", None),
                   "notes": getattr(d, "notes", None)}
    # one 1L-shaped staged change
    lib = sh(clone, "git", "ls-files", "lib/*.dart").split("\n")[0]
    test = sh(clone, "git", "ls-files", "test/*_test.dart").split("\n")[0]
    md = "docs/standards/conventions.md" if os.path.exists(os.path.join(clone, "docs/standards/conventions.md")) else \
        sh(clone, "git", "ls-files", "docs/*.md").split("\n")[0]
    rn = "release_notes/ko.txt"
    append(os.path.join(clone, lib), "\n// k3r2 measurement\n")
    append(os.path.join(clone, test), "\n// k3r2 measurement\n")
    append(os.path.join(clone, md), "\n")
    staged = [lib, test, md] + ([rn] if os.path.exists(os.path.join(clone, rn)) else [])
    sh(clone, "git", "add", "--", *staged)
    sb = PO.local_sandbox(clone, run, 0)
    env = dict(env, npm_config_offline="true")    # as commit_local
    res = []
    for c in checks:
        cmd = c.command(staged)
        if cmd is None:
            res.append({"check": c.name, "verdict": "not applicable (glob matches nothing)"})
            continue
        t1 = time.time()
        r = CH.run_command([cmd], 1800, cwd=clone, env=env, sandbox=sb, tmp=os.path.join(run, "tmp"))
        res.append({"check": c.name, "cmd": cmd[:160], "verdict": LC.classify(r), "rc": r.rc,
                    "secs": round(time.time() - t1, 1), "tail": tail(r.raw)})
    out["checks_run"] = res
    gate = os.path.join(clone, ".claude/guild/gates/scripts/gate_precommit.py")
    g = CH.run_command(["python3 %s --git-hook </dev/null" % gate], 600, cwd=clone, env=env, sandbox=sb,
                       tmp=os.path.join(run, "tmp"))
    out["gate"] = {"passed": g.passed, "tail": tail(g.raw, 3)}
    # flutter inside the 1L sandbox (m6): the engine's warm-up first (hooks under the proxy), then offline
    wdir = os.path.join(clone, PO.WARMUP_DIR)
    os.makedirs(wdir, exist_ok=True)
    with open(os.path.join(wdir, "warmup_test.dart"), "w") as fh:
        fh.write(PO.WARMUP_DART)
    wr, wpx = CH.deps_step(["flutter test --no-pub %s/warmup_test.dart" % PO.WARMUP_DIR], clone,
                           PO.deps_sandbox(clone, run, clone, [], 0), os.path.join(run, "tmp"), env=env)
    shutil.rmtree(wdir, True)
    out["warmup"] = {"passed": wr.passed, "proxy": wpx}
    t2 = time.time()
    f = CH.run_command(["flutter test --no-pub %s" % test], 1800, cwd=clone, env=env, sandbox=sb,
                       tmp=os.path.join(run, "tmp"))
    out["flutter_in_1l_sandbox"] = {"passed": f.passed, "rc": f.rc, "secs": round(time.time() - t2, 1), "tail": tail(f.raw)}
    with open(a.out, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
