#!/usr/bin/env python3
"""replay.suite_subset — the MAIN suite path on real code (K2r5-B1): a scratch clone of the repository
at a commit (the "developer checkout": K1-style `pub get`, then the developer's git-ignored files
copied from the source checkout), the engine's preflight (`preflight.ignored_needed`), then
`ports.suite_in_tree` — pristine <base> warmed in place under the deps proxy → HEAD → ignored entries
→ `copy_ignored` → the suite offline in `tree_sandbox` (every checkout of the clone AND the source
repository denied). One target per invocation (the caller serialises and checks memory).

    suite_subset.py --repo <src> --work <dir> --sha <head> --base <base> --cmd "flutter test" [--cmd …]
                    [--copy-ignored a,b] [--no-preflight] --out FILE.json
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
from guildcore.roles import settings as S                 # noqa: E402
from workflows.dev import effective as EFF                # noqa: E402
from workflows.dev import ports as PT                     # noqa: E402
from workflows.dev import preflight as PF                 # noqa: E402
from workflows.dev.replay.revert_subset import GENERATED  # noqa: E402


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--cmd", action="append", help="the repo's commands.test (repeatable, in order)")
    ap.add_argument("--copy-ignored", default="")
    ap.add_argument("--no-preflight", action="store_true")
    ap.add_argument("--flutter-bin", default=os.path.expanduser("~/fvm/default/bin"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    work = os.path.abspath(a.work)
    clone = os.path.join(work, "clone")
    EFF.TEMP_PARENT = os.path.join(work, "trees")
    os.makedirs(EFF.TEMP_PARENT, exist_ok=True)
    copy_list = [x for x in a.copy_ignored.split(",") if x]
    env = dict(os.environ)
    env["PATH"] = a.flutter_bin + os.pathsep + env.get("PATH", "")
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    row = {"sha": a.sha, "base": a.base, "copy_ignored": copy_list}
    sh(clone, "git", "checkout", "-q", "--detach", a.sha)
    sh(clone, "git", "clean", "-qfdx", "-e", ".dart_tool")
    run_dir = os.path.join(work, "runs", "suite-" + a.sha[:10])
    shutil.rmtree(run_dir, True)
    for d in ("in", "out", "tmp"):
        os.makedirs(os.path.join(run_dir, d))
    env.update(S.render_gitconfig(clone, os.path.join(run_dir, "in", "gitconfig")))
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    t0 = time.time()
    dev_sb = S.role_sandbox("developer", clone, run_dir, toolchain=True, tool_writes=S.toolchain_writes(clone))
    dr, px = CH.deps_step(["flutter pub get"], clone, dev_sb, os.path.join(run_dir, "tmp"), env=env)   # K1 deps step
    row["deps"] = {"rc": dr.rc, "secs": round(time.time() - t0, 1), "proxy": px}
    for g in GENERATED:                                      # the developer checkout's ignored files
        src = os.path.join(a.repo, g)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(os.path.join(clone, g)), exist_ok=True)
            shutil.copy2(src, os.path.join(clone, g))
    need = PF.ignored_needed(clone, copy_list)
    row["preflight"] = need
    if need and not a.no_preflight:
        row["result"] = "halted: env ignored-missing — %s" % ", ".join(need)
    else:
        t1 = time.time()
        r = PT.suite_in_tree(clone, a.base, a.cmd or ["flutter test"], "tester", 3600, run_dir, env, copy_list,
                             extra_roots=[os.path.abspath(a.repo)])
        summ = CH.parse_summary(r.raw, "flutter")
        row.update(secs=round(time.time() - t1, 1), rc=r.rc, passed=r.passed, warm=r.warm,
                   tree_kb=getattr(r, "tree_kb", None), ignored_copied=r.ignored_copied,
                   build_inputs=getattr(r, "build_inputs", None), build_inputs_changed=getattr(r, "build_inputs_changed", None),
                   summary=summ.as_dict() if summ else None, missing_ignored=r.missing_ignored,
                   tail=CH.redact_lines(r.raw[-1200:]))
        if not r.passed and r.missing_ignored:
            row["result"] = "halted: env ignored-missing — %s" % ", ".join(r.missing_ignored)
        elif not r.passed and getattr(r, "build_inputs_changed", None):
            row["result"] = "halted: env build-inputs-changed — %s" % ", ".join(r.build_inputs_changed)
        else:
            row["result"] = "green" if r.passed else "red"
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(row, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: row.get(k) for k in ("sha", "result", "secs", "warm", "summary")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
