"""review-k6-r10 — as table tests over the cases the findings name. The direction of this round: remove the rules
that the last rounds added and that opened new gaps, rather than add more.

M1  r9 m2's "latest pass" is gone. A held-out id counts ONCE, its worst verdict across every copy; `pass` is reported
    (`passes`), never counted. A replay-failed group (n ≥ 20, below the bar) stays failed whatever later rows say —
    synthetic never covers it (K6 r8 user decision 1). Re-grading needs a FRESH held-out set: the old held-out rows go
    in as tuning rows. Review cases (a) one `pass: 2` row, (b) a fifth pass, (c) a partial final pass.
M2  r8 m1's compound-noun exception and r9 M3's contrast check are gone (the r7 rule): a rating word / stem refuses
    the label whatever head noun follows — the reviewer's 7 head-variant pairs are refused, so are descriptive
    compounds ("safe area insets"); lower-case "high / low contrast" is no rating (r7), shown again (m4).
m1  the split check reads the tuning Issues from EVERY tuning row (unknown group, kind conflict, no source).
m2  `fsafe.tmp_name` is short and leaf-free — a ~240-byte leaf is written; the P1 refusals stay.
m3  every K0–K6 runner counts `Ran N` − skipped (failures + errors from the summary), floor = the measured count.
m4  accepted refusals (the safe side): "HIGH contrast", "unsafe-inline".
m5  `journal.atomic_write` takes the same per-call temp name — threads writing one path never collide.
m6  two engines exporting the same base's gates at once: the later one uses the identical export already there.
"""

import inspect
import os
import subprocess
import sys
import tempfile
import threading
import unittest

import _util  # noqa: F401
from _k1 import git, tmpdir

from guildcore import fsafe
from guildcore import journal as J
from guildcore.roles import settings as S
from workflows.dev import predict as PF
from workflows.dev.replay import gate_report as GR

TUNE = [{"id": "#999999/D1", "group": "HANDOFF", "set": "tuning", "source": "replay", "agree": True,
         "advance_agree": True},
        {"id": "syn-tuning-only", "group": "SPLIT", "set": "tuning", "source": "synthetic", "wrong": False}]


def rep(i, ok, p=None, g="DIRECTIVE", set_="held-out"):
    r = {"id": "#%d/D1" % i, "group": g, "set": set_, "source": "replay", "agree": ok, "advance_agree": ok}
    if p is not None:
        r["pass"] = p
    return r


def syn(i, g="DIRECTIVE"):
    return {"id": "syn-%s-%d" % (g, i), "group": g, "set": "held-out", "source": "synthetic", "wrong": False}


def decide(rows):
    return GR.decide(list(rows) + TUNE)


FAILED20 = [rep(100 + i, i >= 10, 1) for i in range(20)]           # n 20, 10 wrong
# (name, group, rows, verified?)
M1_TABLE = [
    ("a: one pass-2 row does not lift a failed replay", "DIRECTIVE",
     FAILED20 + [rep(100, True, 2), syn(0), syn(1)], False),
    ("a: every failed id re-graded in pass 2", "DIRECTIVE",
     FAILED20 + [rep(100 + i, True, 2) for i in range(20)] + [syn(0), syn(1)], False),
    ("a: without any pass field", "DIRECTIVE",
     [rep(100 + i, i >= 10) for i in range(20)] + [syn(0), syn(1)], False),
    ("b: a fifth held-out pass", "DIRECTIVE",
     [rep(100 + i, k == 5 or i >= 10, k) for k in range(1, 6) for i in range(20)], False),
    ("b: pass 3 alone of a failed group", "DIRECTIVE",
     FAILED20 + [rep(100 + i, True, 3) for i in range(20)], False),
    ("c: a final pass of the other 20", "DIRECTIVE",
     [rep(100 + i, i >= 5, 1) for i in range(25)] + [rep(100 + i, True, 2) for i in range(5, 25)], False),
    ("c: a final pass of the failures only", "DIRECTIVE",
     [rep(100 + i, i >= 5, 1) for i in range(25)] + [rep(100 + i, True, 2) for i in range(5)], False),
    # still verifies — nothing about `pass` makes a good set fail
    ("one pass, 20/20", "DIRECTIVE", [rep(100 + i, True, 1) for i in range(20)], True),
    ("two passes both 20/20", "DIRECTIVE", [rep(100 + i, True, k) for k in (1, 2) for i in range(20)], True),
    ("short replay + planned synthetic", "DIRECTIVE", [rep(100 + i, True, 1) for i in range(5)] + [syn(0), syn(1)],
     True),
    # a fresh held-out set: the old held-out rows go in as tuning, new Issues are held out
    ("fresh held-out set, old rows as tuning", "DIRECTIVE",
     [rep(100 + i, i >= 10, set_="tuning") for i in range(20)] + [rep(200 + i, True) for i in range(20)], True),
    ("fresh set reusing an old Issue", "DIRECTIVE",
     [rep(100 + i, i >= 10, set_="tuning") for i in range(20)] + [rep(200 + i, True) for i in range(19)]
     + [{"id": "#100/D2", "group": "DIRECTIVE", "set": "held-out", "source": "replay", "agree": True,
         "advance_agree": True}], False),
]


class M1OneHeldOutSet(unittest.TestCase):
    def test_table(self):
        for name, g, rows, want in M1_TABLE:
            with self.subTest(case=name):
                d = decide(rows)[g]
                self.assertEqual(d["verified"], want, d["why"])

    def test_failed_replay_says_why(self):
        d = decide(FAILED20 + [rep(100, True, 2), syn(0), syn(1)])["DIRECTIVE"]
        self.assertEqual((d["replay_n"], d["replay_agree"], d["by"]), (20, 10, None))
        self.assertIn("not covered by synthetic", d["why"])
        self.assertEqual(d["passes"], {"replay": [1, 2]})                   # reported only

    def test_no_latest_pass_keys(self):
        d = decide([rep(100 + i, True, 1) for i in range(20)])["DIRECTIVE"]
        for k in ("pass", "replay_earlier_pass_rows", "replay_pass_mixed"):
            self.assertNotIn(k, d)
        c = GR.report(TUNE)["criteria"]
        self.assertNotIn("latest_pass_only", c)
        self.assertEqual((c["pass_counted"], c["copies_of_an_id"]), (False, "worst verdict"))


class m1TuningIssuesFromEveryRow(unittest.TestCase):
    def test_table(self):
        tuning = [("EX-ARB", {}), ("KICK-EXPLORE", {}), ("split", {}), ("EX-ARB:dismiss", {"kind": "accept"}),
                  ("SPLIT", {"source": "unknown"}), ("SPLIT", {"source": None}), ("SPLIT", {"kind": "accept"})]
        for g, extra in tuning:
            rows = [rep(200 + i, True, g="SPLIT") for i in range(20)]
            t = dict({"id": "#200/D7", "group": g, "set": "tuning", "source": "replay", "agree": True,
                      "advance_agree": True}, **extra)
            rows.append(t)
            with self.subTest(tuning=(g, extra)):
                d = decide(rows)
                self.assertFalse(d["SPLIT"]["verified"], d["SPLIT"]["why"])
                self.assertIn(200, d["_split_overlap"])

    def test_a_known_group_row_still_contaminates(self):
        rows = [rep(200 + i, True, g="SPLIT") for i in range(20)] + [rep(200, True, g="DE-ARB", set_="tuning")]
        self.assertEqual(decide(rows)["SPLIT"]["contaminated"], ["#200/D1"])

    def test_an_unknown_group_synthetic_tuning_id(self):
        rows = [syn(i, "DIRECTIVE") for i in range(2)] + [
            {"id": "syn-DIRECTIVE-0", "group": "WHATEVER", "set": "tuning", "source": "synthetic", "wrong": False}]
        d = decide(rows)["DIRECTIVE"]
        self.assertFalse(d["verified"])
        self.assertEqual(d["contaminated"], ["syn-DIRECTIVE-0"])

    def test_disjoint_issues_still_verify(self):
        rows = [rep(200 + i, True, g="SPLIT") for i in range(20)] + [
            {"id": "#300/D1", "group": "KICK-EXPLORE", "set": "tuning", "source": "replay"}]
        self.assertTrue(decide(rows)["SPLIT"]["verified"])


# the reviewer's 7 head-variant pairs (r7 refused, r8 / r9 showed) + compounds r8 m1 showed
M2_REFUSED = [
    ("Split in two (safe zone only)", "Single PR (unsafe zones only)"),
    ("Split in two (safe area only)", "Single PR (unsafe areas only)"),
    ("Split in two (safe zone only)", "Single PR (dangerous area only)"),
    ("Split in two. Safe zone.", "Single PR. Unsafe zones."),
    ("분할 (안전 구역만)", "단일 PR (위험 지역만)"),
    ("分割（安全区域のみ）", "単一PR（危険地帯のみ）"),
    ("分割（安全地帯のみ）", "単一PR（危険区域のみ）"),
    ("Use the safe area insets", "Use fixed padding"),
    ("Add a risk register doc", "Skip the doc"),
    ("Dangerous goods label", "Plain label"),
    ("위험 물품 목록 추가", "그대로"),
    ("安全装置を追加", "そのまま"),
    ("Show HIGH contrast toggle", "No toggle"),                  # m4: upper-case weak word — accepted refusal
    ("Allow unsafe-inline styles", "Hash the styles"),          # m4: CSP keyword — accepted refusal
]
M2_SHOWN = [
    ("Use high contrast theme", "Use low contrast theme"),      # m4: lower-case high / low rate nothing (r7)
    ("Fail-safe default", "Fail-open default"),
    ("Add the 안전망 test", "Skip it"),                           # 안전망 = a safety net (domain noun)
]


class M2CompoundExceptionGone(unittest.TestCase):
    def test_refused(self):
        for a, b in M2_REFUSED:
            with self.subTest(pair=(a, b)):
                self.assertIn(None, PF.blind_labels([a, b]))

    def test_shown(self):
        for a, b in M2_SHOWN:
            with self.subTest(pair=(a, b)):
                self.assertEqual(PF.blind_labels([a, b]), [a, b])

    def test_the_exception_code_is_gone(self):
        for name in ("_COMPOUND_HEADS", "_COMPOUND_TAIL", "_compound_noun", "_compound_contrast", "_CJK_COMPOUND",
                     "_CJK_STEMS"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(PF, name))
        self.assertEqual(PF._CJK_RATING.pattern, r"안전(?!망)|위험|安全(?!網)|危険")


class m2ShortTempNames(unittest.TestCase):
    def test_a_long_leaf_is_written(self):
        root = tmpdir(self)
        for n in (225, 240, 250):
            leaf = "a" * (n - 4) + ".png"
            with self.subTest(bytes=n):
                fsafe.write_bytes(root, leaf, b"x")
                fsafe.symlink(root, "l" * n, "/nonexistent")
        self.assertFalse([x for x in os.listdir(root) if x.startswith(".engine")])

    def test_names_are_short_and_unique(self):
        t = os.path.join(tmpdir(self), "b" * 250)
        names = [fsafe.tmp_name(t, "-link") for _ in range(200)]
        self.assertEqual(len(set(names)), 200)
        self.assertTrue(all(len(os.path.basename(n)) <= 64 for n in names))
        self.assertTrue(all(os.path.dirname(n) == os.path.dirname(t) for n in names))

    def test_p1_refusals_unchanged(self):
        root = tmpdir(self)
        os.symlink(tmpdir(self), os.path.join(root, "lnk"))
        for rel in ("lnk/x", "lnk"):
            with self.subTest(rel=rel), self.assertRaises(fsafe.UnsafePath):
                fsafe.write_bytes(root, rel, b"x")
        with self.assertRaises(fsafe.UnsafePath):
            fsafe.write_bytes(root, "../x", b"x")


class m3RunnerCounts(unittest.TestCase):
    RUNNERS = [os.path.join(_util.TESTS, "engine_k%d_test.sh" % k) for k in range(7)]

    def _count(self, src, out_text):
        """Run the runner's own counting lines on a fabricated unittest log."""
        a = src.index("RAN=$(sed")
        b = src.index('echo "engine K')
        d = tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        p = os.path.join(d, "out")
        with open(p, "w") as fh:
            fh.write(out_text)
        r = subprocess.run(["bash", "-c", 'OUT="$1"\n' + src[a:b] + 'echo "$COUNTED $PASS $FAIL"', "x", p],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.stdout.decode().split()[-3:]

    def test_every_runner_counts_ran_minus_skipped(self):
        for path in self.RUNNERS:
            src = _util.read(path)
            with self.subTest(runner=os.path.basename(path)):
                self.assertNotIn("PASS + FAIL", src)
                self.assertNotIn("grep -cE '\\.\\.\\. ok$'", src)
                self.assertRegex(src, r'if \[ "\$COUNTED" -lt "\$ENGINE_K\d_MIN_TESTS" \]')
                split_line = "test_a (m.T.test_a) ... <stderr noise>\nok\ntest_b (m.T.test_b) ... skipped 'x'\n"
                self.assertEqual(self._count(src, split_line + "Ran 5 tests in 0.1s\n\nOK (skipped=1)\n"),
                                 ["4", "4", "0"])
                self.assertEqual(self._count(src, "Ran 7 tests in 0.1s\n\nFAILED (failures=1, errors=2, skipped=2)\n"),
                                 ["5", "2", "3"])

    def test_floors_are_whole_numbers_set(self):
        for path in self.RUNNERS:
            src = _util.read(path)
            with self.subTest(runner=os.path.basename(path)):
                self.assertRegex(src, r"\nENGINE_K\d_MIN_TESTS=\d+\n")


class m5JournalAtomicWrite(unittest.TestCase):
    def test_threads_writing_one_path(self):
        d = tmpdir(self)
        p = os.path.join(d, "state.json")
        errors = []

        def run(k):
            try:
                for i in range(40):
                    J.atomic_write(p, "%d-%d" % (k, i))
            except BaseException as e:
                errors.append(repr(e))
        ths = [threading.Thread(target=run, args=(k,)) for k in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(os.listdir(d), ["state.json"])
        with open(p) as fh:
            self.assertRegex(fh.read(), r"^\d+-39$")

    def test_settings_and_journal_use_the_fsafe_helper(self):
        self.assertNotIn("getpid", inspect.getsource(J.atomic_write))
        self.assertIn("tmp_name", inspect.getsource(J.atomic_write))
        src = inspect.getsource(S)
        self.assertFalse([ln for ln in src.splitlines() if "tmp" in ln and "getpid" in ln])
        self.assertEqual(src.count("tmp = tmp_name(dest)"), 2)


CHILD = ("import sys; sys.path.insert(0, %r); from guildcore.roles import settings as S; "
         "print(S.export_gates_readonly(sys.argv[1], sys.argv[2])[1])")


class m6TwoEnginesExportOneBase(unittest.TestCase):
    def _repo(self):
        d = tmpdir(self)
        os.makedirs(os.path.join(d, ".claude/guild/gates/scripts"))
        with open(os.path.join(d, ".claude/guild/gates/scripts/gate.py"), "w") as fh:
            fh.write("print('gate')\n")
        git(d, "init", "-q")
        git(d, "add", "-A")
        git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        return d, git(d, "rev-parse", "HEAD")

    def _race(self, d, base):
        real = S.export_gates

        def racing(worktree, base_sha, dest):
            ok = real(worktree, base_sha, dest)
            # another Issue's engine (another process) exports the same base between our extract and rename
            subprocess.run([sys.executable, "-c", CHILD % _util.ENGINE, worktree, base_sha], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return ok
        S.export_gates = racing
        try:
            return S.export_gates_readonly(d, base)
        finally:
            S.export_gates = real

    def test_the_later_engine_uses_the_identical_export(self):
        d, base = self._repo()
        dest, digest = self._race(d, base)
        self.assertTrue(dest and os.path.isdir(dest))
        self.assertTrue(S.verify_gates(dest, digest))
        parent = os.path.dirname(dest)
        self.assertEqual(sorted(os.listdir(parent)), sorted([base, base + ".sha256"]))   # no temp tree left
        with open(dest + ".sha256") as fh:
            self.assertEqual(fh.read().strip(), digest)
        self.assertEqual(S.export_gates_readonly(d, base), (dest, digest))                # re-verified, reused

    def test_a_different_tree_at_dest_still_raises(self):
        d, base = self._repo()
        real = S.export_gates

        def planted(worktree, base_sha, dest):
            ok = real(worktree, base_sha, dest)
            final = S.gates_home(S.git_dirs(worktree)[1], base_sha)
            os.makedirs(os.path.join(final, "other"))
            with open(os.path.join(final, "other", "x"), "w") as fh:
                fh.write("not the base\n")
            return ok
        S.export_gates = planted
        try:
            with self.assertRaises(OSError):
                S.export_gates_readonly(d, base)
        finally:
            S.export_gates = real
        final = S.gates_home(S.git_dirs(d)[1], base)
        self.assertEqual(os.listdir(os.path.dirname(final)), [base])                      # our temp tree removed


if __name__ == "__main__":
    unittest.main()
