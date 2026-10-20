"""M0e: cost of the hook (m0e-plan §12.7). Targets: the runner on a non-Studio commit p50 ≤ 50 ms (shell only,
no Python); `--staged` on a Studio commit p50 ≤ 300 ms. The test fails only above 3× the target (shared,
loaded machines) and prints the measurements."""

import os
import statistics
import subprocess
import sys
import time

from commit_base import CommitCase

N = 15


class Perf(CommitCase):
    def timed(self, argv):
        ts = []
        for _ in range(N):
            t = time.perf_counter()
            out = subprocess.run(argv, cwd=self.repo, capture_output=True, text=True, env=self.env)
            ts.append((time.perf_counter() - t) * 1000)
        return out, statistics.median(ts), max(ts)

    def test_runner_and_staged(self):
        runner = os.path.join(self.repo, ".git", "studio", "pre-commit")
        self.write("src/a.ts")
        self.git("add", "src/a.ts")
        out, p50, worst = self.timed(["sh", runner])
        self.assertEqual(out.returncode, 0, out.stderr)
        sys.stderr.write("\n  runner, non-Studio commit: p50 %.1f ms, max %.1f ms\n" % (p50, worst))
        self.assertLess(p50, 150)
        self.git("restore", "--staged", "src/a.ts")
        self.ready()
        self.assertEqual(self.cc("--stage", "test", "v1").returncode, 0)
        out, p50, worst = self.timed([sys.executable, "-B", os.path.join(self.repo, ".claude/studio/scripts/check_commit.py"),
                                      "--staged"])
        self.assertEqual(out.returncode, 0, out.stderr)
        sys.stderr.write("  check_commit --staged, Studio commit: p50 %.1f ms, max %.1f ms (%s)\n"
                         % (p50, worst, sys.version.split()[0]))
        self.assertLess(p50, 900)
