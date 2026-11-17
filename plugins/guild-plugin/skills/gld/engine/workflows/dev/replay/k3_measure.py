#!/usr/bin/env python3
"""replay.k3_measure — K3's real-code measurements on a word_app SCRATCH clone (never the real checkout):

  m1  the K1 deps step in the worktree (`ports.deps_main`): `pub get` only, registry hosts only, reads
      limited to the allowlist, the `copy_ignored` originals denied — plus read probes in the same
      sandbox (an original, a home dotfile, a tree file).
  m3  K2r8-m2: the REAL offline failure when a native-assets hook needs a download (pub get done, no
      warm-up): the raw output and flutter's machine report → is it read as a loading-phase dependency
      failure (text heuristic and report)?
  m2  K2r8-m1: after a warm-up, a test body that PRINTS a fake `loading … [E]` + `Failed host lookup`
      and fails, and a test file that does not compile → what the report says for each.
One flutter process at a time; the caller checks memory between runs.

    k3_measure.py --repo ~/projects/word_app --work <dir> --copy-ignored a,b,c --out FILE.json
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
from workflows.dev import ports as PO                     # noqa: E402
from workflows.dev import preflight as PF                 # noqa: E402

FAKE = """import 'package:flutter_test/flutter_test.dart';

void main() {
  test('prints a fake loader failure', () {
    // ignore: avoid_print
    print("00:01 +0 -1: loading /x/test/other_test.dart [E]");
    // ignore: avoid_print
    print("  Failed host lookup: 'pub.dev'");
    expect(1, 2);
  });
}
"""
BROKEN = """import 'package:flutter_test/flutter_test.dart';

void main() {
  test('does not compile', () { final int x = 'nope'; expect(x, 1); });
}
"""


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()


def tail(t, n=12):
    return CH.redact_lines("\n".join((t or "").rstrip().split("\n")[-n:]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--copy-ignored", default="")
    ap.add_argument("--small-test", default="test/main_boot_retry_test.dart")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="m1,m3,m2")
    a = ap.parse_args(argv)
    only = a.only.split(",")
    work = os.path.realpath(a.work)
    clone = os.path.join(work, "clone")
    if not os.path.exists(clone):
        sh(work, "git", "clone", "-q", "--no-hardlinks", a.repo, clone)
    copy_list = [x for x in a.copy_ignored.split(",") if x]
    for g in copy_list:
        src = os.path.join(a.repo, g)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(os.path.join(clone, g)), exist_ok=True)
            shutil.copy2(src, os.path.join(clone, g))
    out = {"head": sh(clone, "git", "rev-parse", "HEAD").strip(), "copy_ignored": copy_list}
    run_dir = os.path.join(work, "run")
    os.makedirs(os.path.join(run_dir, "in"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "tmp"), exist_ok=True)
    env = C.child_env(dict(os.environ), {}, role_dir=run_dir)
    env.update(S.render_gitconfig(clone, os.path.join(run_dir, "in", "gitconfig")))

    prev = {}
    if os.path.exists(a.out):
        with open(a.out) as fh:
            prev = json.load(fh)
    out = dict(prev, **out)
    # m1 — deps step in the worktree
    if "m1" not in only:
        return _m2(a, clone, run_dir, env, copy_list, out) if "m2" in only else 0
    shutil.rmtree(os.path.join(clone, ".dart_tool"), True)
    t0 = time.time()
    r = PO.deps_main(clone, run_dir, env, copy_list, 0)
    out["m1_deps_main"] = {"passed": r.passed, "rc": r.rc, "secs": round(time.time() - t0, 1),
                           "proxy": getattr(r, "proxy", None), "tail": tail(r.raw, 6)}
    sb = PO.deps_sandbox(clone, run_dir, clone, copy_list, 0)
    probes = {}
    for label, cmd in (("tree file", "head -c 20 pubspec.yaml"),
                       ("copy_ignored original", "head -c 20 %s" % (copy_list[0] if copy_list else "lib/env/env.dart")),
                       ("home dotfile", "head -c 20 %s" % os.path.expanduser("~/.zshrc")),
                       ("other checkout", "head -c 20 %s" % os.path.join(a.repo, "pubspec.yaml"))):
        pr = CH.run_command([cmd], 60, cwd=clone, env=env, sandbox=sb, tmp=os.path.join(run_dir, "tmp"))
        probes[label] = {"readable": pr.passed, "err": tail(pr.raw, 1) if not pr.passed else None}
    out["m1_read_probes"] = probes

    # m3 — offline run with no hook warm-up: the REAL native-assets failure
    tsb = PO.deps_sandbox(clone, run_dir, clone, copy_list, 0)
    rep3 = os.path.join(run_dir, "tmp", "m3.jsonl")
    t0 = time.time()
    r3 = CH.run_command(["flutter test --no-pub --file-reporter json:%s %s" % (rep3, a.small_test)], 900, cwd=clone,
                        env=env, sandbox=tsb, tmp=os.path.join(run_dir, "tmp"))
    rep_text = open(rep3).read() if os.path.exists(rep3) else None
    out["m3_offline_no_warmup"] = {
        "passed": r3.passed, "rc": r3.rc, "secs": round(time.time() - t0, 1), "tail": tail(r3.raw, 14),
        "text_load_only": PF.dependency_failure(r3.raw, r3.rc, load_only=True),
        "report_present": rep_text is not None,
        "report_load_errors": tail(PF.json_load_errors(rep_text) or "", 6) if rep_text else None,
        "report_load_only": PF.dependency_failure(r3.raw, r3.rc, load_only=True, report=rep_text) if rep_text else None}

    return _m2(a, clone, run_dir, env, copy_list, out)


def _m2(a, clone, run_dir, env, copy_list, out):
    # warm-up as the engine does it (an ENGINE-written empty test outside test/, under the deps proxy
    # with the GitHub release hosts), then m2 OFFLINE in a sandbox that may read the copied files
    # (the suite's temp tree has them — `copy_ignored`)
    wdir = os.path.join(clone, PO.WARMUP_DIR)
    os.makedirs(wdir, exist_ok=True)
    with open(os.path.join(wdir, "warmup_test.dart"), "w") as fh:
        fh.write(PO.WARMUP_DART)
    wsb = PO.deps_sandbox(clone, run_dir, clone, [], 0)
    wr, wpx = CH.deps_step(["flutter test --no-pub %s/warmup_test.dart" % PO.WARMUP_DIR], clone, wsb,
                           os.path.join(run_dir, "tmp"), env=env)
    shutil.rmtree(wdir, True)
    out["warmup"] = {"passed": wr.passed, "proxy": wpx, "tail": tail(wr.raw, 4)}
    tsb = PO.deps_sandbox(clone, run_dir, clone, [], 0)
    m2 = {}
    for name, body in (("fake_loading", FAKE), ("broken_compile", BROKEN)):
        rel = "test/zz_k3_%s_test.dart" % name
        with open(os.path.join(clone, rel), "w") as fh:
            fh.write(body)
        rep = os.path.join(run_dir, "tmp", "m2-%s.jsonl" % name)
        rr = CH.run_command(["flutter test --no-pub --file-reporter json:%s %s" % (rep, rel)], 900, cwd=clone,
                            env=env, sandbox=tsb, tmp=os.path.join(run_dir, "tmp"))
        txt = open(rep).read() if os.path.exists(rep) else None
        m2[name] = {"passed": rr.passed, "tail": tail(rr.raw, 8),
                    "text_load_only_dependency": PF.dependency_failure(rr.raw, rr.rc, load_only=True),
                    "report_load_errors": tail(PF.json_load_errors(txt) or "", 4) if txt is not None else None,
                    "report_load_only_dependency": PF.dependency_failure(rr.raw, rr.rc, load_only=True, report=txt)
                    if txt is not None else None}
        os.remove(os.path.join(clone, rel))
    out["m2"] = m2
    with open(a.out, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
