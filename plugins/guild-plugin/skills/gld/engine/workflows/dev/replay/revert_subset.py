#!/usr/bin/env python3
"""replay.revert_subset — the TEST `effective` check ② on REAL code (K2 review M7): a scratch clone of
the repository, the Issue's squash commit `(#N)` as HEAD, its parent as `<base>`, the tests the
commit ADDED as `kind: new` covers, the impl revert in a temp worktree, the single test re-run
with the exact filter — every command under the tester-verify sandbox (checks.run_command +
settings.role_sandbox, K1r3-B1), dependencies fetched once per commit by the engine's deps step
(host-allowlist proxy). Gitignored generated sources the repo needs are copied (read-only) from
the source checkout. Nothing is written to the source repository.

    revert_subset.py --repo <src> --work <scratch dir> --issues 1873,1890,… [--flutter-bin DIR] --out FILE.json
"""

import argparse
import json
import os
import re
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

# gitignored files the repo's code needs; copied into the CLONE (like a developer's checkout) —
# the engine's temp tree never copies ignored files (K2r2-M1), so a test that needs them is
# `unverified(secret-required)` there
GENERATED = ("lib/env/env.dart", "lib/firebase_options.dart", "lib/controller/tts_controller/wrong_words.dart",
             "assets/data.db")
TEST_NAME_RE = re.compile(r"\b(?:test|testWidgets)\s*\(\s*'([^'$]+)'")


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()


class Port(object):
    def __init__(self, root, env, run_dir):
        self.root, self.env, self.run_dir = root, env, run_dir
        self.calls = []

    def read_file(self, rel):
        try:
            with open(os.path.join(self.root, rel), encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except (IOError, OSError):
            return None

    def warm(self, tree):
        """ports.live's warm-up: an engine-written empty test under the deps proxy."""
        rel = os.path.join("test", "guild_engine_warmup_test.dart")
        with open(os.path.join(tree, rel), "w", encoding="utf-8") as fh:
            fh.write("import 'package:flutter_test/flutter_test.dart';\n\nvoid main() {\n  test('guild engine warm-up', () {});\n}\n")
        try:
            from workflows.dev.ports import warm_sandbox
            sb = warm_sandbox(tree, self.run_dir, self.root)
            t0 = time.time()
            r, px = CH.deps_step(["flutter test --no-pub %s" % rel], tree, sb, os.path.join(self.run_dir, "tmp"), env=self.env)
            self.calls.append({"cmd": "warm-up", "rc": r.rc, "secs": round(time.time() - t0, 1), "proxy": px,
                               "tail": CH.redact_lines(r.raw[-600:])})
        finally:
            os.remove(os.path.join(tree, rel))

    def check(self, cmd, cwd, owner, timeout_s, write_dirs):
        sb = S.role_sandbox("tester-verify", self.root, self.run_dir, toolchain=True,
                            tool_writes=S.toolchain_writes(self.root))
        fs = dict(sb["filesystem"])
        fs["allowWrite"] = list(fs.get("allowWrite") or []) + [d.rstrip("/") + "/**" for d in write_dirs]
        fs["denyWrite"] = list(fs.get("denyWrite") or []) + [self.root + "/**"]
        t0 = time.time()
        r = CH.run_command([cmd], timeout_s, cwd=cwd, env=self.env, sandbox=dict(sb, filesystem=fs),
                           tmp=os.path.join(self.run_dir, "tmp"))             # OFFLINE (K2r2-M1)
        # re-run output is redacted before it is stored anywhere (K2 r3)
        self.calls.append({"cmd": cmd, "rc": r.rc, "secs": round(time.time() - t0, 1),
                           "tail": CH.redact_lines(r.raw[-1500:])})
        return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--issues", required=True)
    ap.add_argument("--flutter-bin", default=os.path.expanduser("~/fvm/default/bin"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--copy-ignored", default="", help="comma list → engine.effective.copy_ignored")
    a = ap.parse_args(argv)
    os.makedirs(a.work, exist_ok=True)
    clone = os.path.join(a.work, "clone")
    if not os.path.isdir(clone):
        sh(a.work, "git", "clone", "-q", "--no-hardlinks", os.path.abspath(a.repo), clone)
    env = dict(os.environ)
    env["PATH"] = a.flutter_bin + os.pathsep + env.get("PATH", "")
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    results = []
    for n in [int(x) for x in a.issues.split(",") if x]:
        row = {"issue": n}
        sha = sh(a.repo, "git", "log", "--format=%H", "-1", "--grep", "(#%d)" % n, "HEAD").strip()
        if not sha:
            results.append(dict(row, skipped="no squash commit"))
            continue
        sh(clone, "git", "checkout", "-q", "--detach", sha)
        sh(clone, "git", "clean", "-qfdx", "-e", ".dart_tool")       # no ignored originals yet
        base = sh(clone, "git", "rev-parse", sha + "^").strip()
        touched = [f for f in sh(clone, "git", "diff", "--name-only", "--diff-filter=AM", base, sha).split("\n")
                   if f.endswith("_test.dart")]
        covers = []
        for f in touched:
            head = TEST_NAME_RE.findall(open(os.path.join(clone, f), encoding="utf-8").read())
            try:
                old = set(TEST_NAME_RE.findall(sh(clone, "git", "show", "%s:%s" % (base, f))))
            except subprocess.CalledProcessError:
                old = set()
            new = [x for x in head if x not in old and head.count(x) == 1]       # tests this commit ADDED
            if new and len(covers) < 2:
                covers.append({"test": "%s::%s" % (f, new[0]), "ac": "C%d" % (len(covers) + 1), "kind": "new"})
        if not covers:
            results.append(dict(row, sha=sha, skipped="the commit adds no new named dart test"))
            continue
        run_dir = os.path.join(a.work, "runs", str(n))
        for d in ("in", "out", "tmp"):
            os.makedirs(os.path.join(run_dir, d), exist_ok=True)
        env.update(S.render_gitconfig(clone, os.path.join(run_dir, "in", "gitconfig")))   # ~/.gitconfig is denyRead
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        dev_sb = S.role_sandbox("developer", clone, run_dir, toolchain=True, tool_writes=S.toolchain_writes(clone))
        t0 = time.time()
        # K2r3-M1: the networked deps step runs BEFORE any git-ignored original exists in the clone,
        # and warms with an ENGINE-written empty test, never a role's test
        wrel = os.path.join("test", "guild_engine_warmup_test.dart")
        with open(os.path.join(clone, wrel), "w", encoding="utf-8") as fh:
            fh.write("import 'package:flutter_test/flutter_test.dart';\n\nvoid main() {\n  test('guild engine warm-up', () {});\n}\n")
        try:
            dr, px = CH.deps_step(["flutter pub get", "flutter test --no-pub %s" % wrel], clone, dev_sb,
                                  os.path.join(run_dir, "tmp"), env=env)
        finally:
            os.remove(os.path.join(clone, wrel))
        row["deps"] = {"rc": dr.rc, "secs": round(time.time() - t0, 1), "proxy": px}
        for g in GENERATED:                                  # the developer checkout's ignored files — offline from here on
            src = os.path.join(a.repo, g)
            if os.path.exists(src):
                os.makedirs(os.path.dirname(os.path.join(clone, g)), exist_ok=True)
                shutil.copy2(src, os.path.join(clone, g))
        p = Port(clone, env, run_dir)
        cfg = {"commands": {"test": "flutter test"},
               "engine": {"effective": {"copy_ignored": [x for x in a.copy_ignored.split(",") if x]}}}
        out, meta = EFF.run(p, cfg, [c["ac"] for c in covers], {c["ac"]: [c] for c in covers}, base, None, timeout_s=900)
        row.update(sha=sha, base=base, covers=covers,
                   meta={k: v for k, v in meta.items() if k not in ("rejected", "skipped_ignored")},
                   rejected=meta.get("rejected"), outcomes=[o.detail() for o in out.values()], calls=p.calls)
        results.append(row)
        print(json.dumps({"issue": n, "results": [(o.ac, o.result, o.why) for o in out.values()]}, ensure_ascii=False),
              flush=True)
        with open(a.out, "w", encoding="utf-8") as fh:              # incremental: a long run keeps its rows
            json.dump(results, fh, ensure_ascii=False, indent=1)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
