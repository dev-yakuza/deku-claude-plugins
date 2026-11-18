#!/usr/bin/env python3
"""replay.k3r3_net_run — K3r3-M3 measurement on a word_app SCRATCH clone: a refactor-shaped branch (a
net commit adding a characterization test that pins existing behavior, then a transform commit), and
the ENGINE's net run (`ports.net_in_tree`: base warmed in place → moved to the proof point / HEAD →
copy_ignored → offline in the tree sandbox) at the proof and at HEAD. One flutter at a time.

    k3r3_net_run.py --repo ~/projects/word_app --work <dir> --copy-ignored a,b --out FILE.json
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
from workflows.dev import effective as EFF                # noqa: E402
from workflows.dev import ports as PO                     # noqa: E402


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--copy-ignored", default="")
    ap.add_argument("--source-test", default="test/main_boot_retry_test.dart")
    ap.add_argument("--transform", default="lib/main.dart")
    ap.add_argument("--flutter-bin", default=os.path.expanduser("~/fvm/default/bin"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    work = os.path.realpath(a.work)
    clone = os.path.join(work, "clone")
    sh(work, "git", "clone", "-q", "--no-hardlinks", a.repo, clone)
    sh(clone, "git", "config", "user.email", "k3@example.invalid")
    sh(clone, "git", "config", "user.name", "k3")
    copy_list = [x for x in a.copy_ignored.split(",") if x]
    for g in copy_list:
        if os.path.isfile(os.path.join(a.repo, g)):
            os.makedirs(os.path.dirname(os.path.join(clone, g)), exist_ok=True)
            shutil.copy2(os.path.join(a.repo, g), os.path.join(clone, g))
    base = sh(clone, "git", "rev-parse", "HEAD").strip()
    sh(clone, "git", "switch", "-q", "-c", "refactor/#0-k3r3")
    net = a.source_test.replace("_test.dart", "_k3net_test.dart")
    shutil.copyfile(os.path.join(clone, a.source_test), os.path.join(clone, net))
    sh(clone, "git", "add", net)
    sh(clone, "git", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "test: safety net")
    proof = sh(clone, "git", "rev-parse", "HEAD").strip()
    with open(os.path.join(clone, a.transform), "a", encoding="utf-8") as fh:
        fh.write("\n// k3r3 transform: behavior-preserving\n")
    sh(clone, "git", "-c", "core.hooksPath=/dev/null", "commit", "-qam", "refactor: transform")
    run = os.path.join(work, "run")
    for d in ("in", "out", "tmp"):
        os.makedirs(os.path.join(run, d), exist_ok=True)
    env0 = dict(os.environ)
    env0["PATH"] = a.flutter_bin + os.pathsep + env0.get("PATH", "")
    env = C.child_env(env0, {}, role_dir=run)
    env.update(S.render_gitconfig(clone, os.path.join(run, "in", "gitconfig")))
    EFF.TEMP_PARENT = os.path.join(work, "trees")
    os.makedirs(EFF.TEMP_PARENT, exist_ok=True)
    with open(os.path.join(a.repo, ".claude/guild/config.json")) as fh:
        raw = json.load(fh)
    out = {"base": base, "proof": proof, "net": [net], "transform": a.transform}
    for label, rev in (("proof", proof), ("HEAD", "HEAD")):
        rd = os.path.join(run, label)
        os.makedirs(os.path.join(rd, "tmp"), exist_ok=True)
        t0 = time.time()
        r = PO.net_in_tree(clone, base, rev, [net], raw, copy_list, rd, env, 0)
        out[label] = {"passed": r.passed if r else None, "env": getattr(r, "env", None), "warm": getattr(r, "warm", None),
                      "secs": round(time.time() - t0, 1),
                      "tail": CH.redact_lines("\n".join(x[:160] for x in (r.raw or "").rstrip().split("\n")[-3:])) if r else None}
        print(label, out[label], flush=True)
    with open(a.out, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
