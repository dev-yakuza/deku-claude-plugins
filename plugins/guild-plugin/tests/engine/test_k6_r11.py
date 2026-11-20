"""review-k6-r11 — as table tests over the cases the findings name. Same direction as r10: fewer rules, not more.

M1  the "n ≥ 20 failed" boundary is gone. One rule: synthetic rows verify a group ONLY when the input has no replay
    row for it at all (any set — held-out, tuning, retired — and rows a check or the dedupe drops: a misspelt id, an
    id under two groups, no id). A replayed group is verified by replay only, so a failed group stays failed whatever
    rows are added. Old held-out rows go in as `set: "retired"`: replayed, not counted, their Issues blocked.
    Review cases (a) checklist F (old held-out as tuning / retired + a small fresh set) and (b) a typo / conflict row
    under a failed replay of exactly 20, over DIRECTIVE · SPLIT · DE-ARB · EX-ARB-dismiss.
m1  `export_gates_readonly` / `_publish_readonly` drop the temp tree on ANY failure (a failing tar, a failing digest).
m2  the runners read ` failures=` / ` errors=` / ` skipped=` as their own keys — "expected failures=" is not one.
m3  stale docs: the gate_report docstring, the renamed `test_k6_r9` test.
"""

import os
import subprocess
import unittest

import _util  # noqa: F401
from _k1 import git, tmpdir

from guildcore.roles import settings as S
from workflows.dev.replay import gate_report as GR

TUNE = [{"id": "#999999/D1", "group": "HANDOFF", "set": "tuning", "source": "replay", "agree": True,
         "advance_agree": True},
        {"id": "syn-tuning-only", "group": "SPLIT", "set": "tuning", "source": "synthetic", "wrong": False}]

# group → (row group fields, planned held-out synthetic count)
GROUPS = {"DIRECTIVE": ({"group": "DIRECTIVE"}, 2),
          "SPLIT": ({"group": "SPLIT"}, 4),
          "DE-ARB": ({"group": "DE-ARB"}, 3),
          "EX-ARB-dismiss": ({"group": "EX-ARB", "kind": "dismiss"}, 2)}


def rep(g, i, ok, set_="held-out", rid=None, **kw):
    return dict(GROUPS[g][0], id=rid or "#%d/D1" % i, set=set_, source="replay", agree=ok, advance_agree=ok, **kw)


def syns(g):
    return [dict(GROUPS[g][0], id="syn-%s-%d" % (g, i), set="held-out", source="synthetic", wrong=False)
            for i in range(GROUPS[g][1])]


def failed(g):
    return [rep(g, 100 + i, i >= 10) for i in range(20)]       # n 20, 10 wrong — measured and failed


def fresh(g, n):
    return [rep(g, 500 + i, True) for i in range(n)]           # new Issues, all agree


def as_set(rows, st):
    return [dict(r, set=st) for r in rows]


def typo(g):
    rows = failed(g)
    rows[10] = dict(rows[10], id="#110-D1")                     # one misspelt id (an agreeing row) → rejected
    return rows


def conflict(g):
    other = "SPLIT" if g != "SPLIT" else "DIRECTIVE"
    return failed(g) + [rep(other, 110, True)]                   # #110/D1 also held out under another group


# (name, rows(g), verified?, by)
CASES = [
    ("control: never replayed, planned synthetic", lambda g: syns(g), True, "synthetic"),
    ("control: failed replay + synthetic", lambda g: failed(g) + syns(g), False, None),
    ("a: checklist F as r10 wrote it (old held-out as tuning) + 6 fresh",
     lambda g: as_set(failed(g), "tuning") + fresh(g, 6) + syns(g), False, None),
    ("a: old held-out retired + 6 fresh", lambda g: as_set(failed(g), "retired") + fresh(g, 6) + syns(g), False, None),
    ("a: old held-out retired, no fresh rows", lambda g: as_set(failed(g), "retired") + syns(g), False, None),
    ("a: old held-out retired + 20 fresh agreeing", lambda g: as_set(failed(g), "retired") + fresh(g, 20) + syns(g),
     True, "replay"),
    ("b: failed 20, one misspelt id", lambda g: typo(g) + syns(g), False, None),
    ("b: failed 20, one id under two groups", lambda g: conflict(g) + syns(g), False, None),
    ("one tuning replay row of the group", lambda g: [rep(g, 900, True, "tuning")] + syns(g), False, None),
    ("one replay row without an id", lambda g: [dict(rep(g, 0, True), id=None)] + syns(g), False, None),
    ("one replay row with a misspelt id only", lambda g: [rep(g, 0, True, rid="x/D1")] + syns(g), False, None),
    ("one row without a source (read as replay)",
     lambda g: [dict(rep(g, 0, True), source=None)] + syns(g), False, None),
    ("one replay row in an unknown set", lambda g: [rep(g, 0, True, "holdout")] + syns(g), False, None),
]


class M1ReplayedGroupsAreReplayOnly(unittest.TestCase):
    def test_table(self):
        for g in GROUPS:
            for name, make, want, by in CASES:
                with self.subTest(group=g, case=name):
                    d = GR.decide(make(g) + TUNE)[g]
                    self.assertEqual((d["verified"], d["by"]), (want, by), d["why"])

    def test_reviewer_repro_shapes(self):
        # the review's own rows: TUNE carries a tuning replay row OF the group (so even its control is replay only)
        for g in GROUPS:
            with self.subTest(group=g):
                rows = [rep(g, 900000, True, "tuning")] + syns(g) + TUNE
                self.assertFalse(GR.decide(rows)[g]["verified"])

    def test_a_failed_group_stays_failed_whatever_one_row_adds(self):
        # the docstring's sentence: no single added row (of any set / spelling) opens the synthetic path
        extra = [rep("DIRECTIVE", 700, True, st) for st in ("held-out", "tuning", "retired", "x")]
        extra += [dict(rep("DIRECTIVE", 701, True), id=i) for i in (None, "#701-D1", "701")]
        extra += [dict(GROUPS["DIRECTIVE"][0], id="syn-extra", set="held-out", source="synthetic", wrong=False)]
        extra += [rep("SPLIT", 100, True)]                                       # conflicting id
        for e in extra:
            with self.subTest(row=e):
                d = GR.decide(failed("DIRECTIVE") + syns("DIRECTIVE") + [e] + TUNE)["DIRECTIVE"]
                self.assertFalse(d["verified"], d["why"])
                self.assertTrue(d["replayed"])

    def test_bare_exarb_replay_row_closes_both_exarb_groups(self):
        rows = [{"id": "#5/D1", "group": "EX-ARB", "set": "held-out", "source": "replay", "agree": True,
                 "advance_agree": True}] + syns("EX-ARB-dismiss") + TUNE
        per = GR.decide(rows)
        self.assertEqual(per["_unknown_groups"], {"EX-ARB?": 1})
        self.assertFalse(per["EX-ARB-dismiss"]["verified"])
        self.assertTrue(per["EX-ARB-dismiss"]["replayed"] and per["EX-ARB-accept"]["replayed"])

    def test_retired_rows_block_their_issues_and_ids(self):
        old = as_set(failed("SPLIT"), "retired")
        per = GR.decide(old + fresh("SPLIT", 19) + [rep("SPLIT", 105, True, rid="#105/D2")] + TUNE)
        self.assertEqual(per["SPLIT"]["contaminated"], ["#105/D2"])            # a fresh decision of a retired Issue
        self.assertEqual(per["_split_overlap"], [105])
        self.assertFalse(per["SPLIT"]["verified"])
        per = GR.decide(old + [rep("SPLIT", 100, True)] + fresh("SPLIT", 19) + TUNE)
        self.assertEqual(per["SPLIT"]["contaminated"], ["#100/D1"])            # the same id held out again

    def test_retired_rows_are_not_tuning_rows(self):
        # the train = test check needs real tuning rows; retired ones do not stand in for them (K6 r9 m3)
        rows = as_set(failed("SPLIT"), "retired") + fresh("SPLIT", 20)
        per = GR.decide(rows)
        self.assertEqual(per["_no_tuning_rows"], ["replay", "synthetic"])
        self.assertFalse(per["SPLIT"]["verified"])
        self.assertEqual(per["SPLIT"]["ignored"], 20)                           # retired rows never gate

    def test_why_and_criteria(self):
        d = GR.decide(failed("DE-ARB") + syns("DE-ARB") + TUNE)["DE-ARB"]
        self.assertIn("verified by replay only", d["why"])
        self.assertIn("r11 M1", d["why"])
        h = GR.decide(TUNE + [dict(syns("DIRECTIVE")[0], group="HANDOFF")])["HANDOFF"]
        self.assertIn("no synthetic set planned", h["why"])                      # HANDOFF keeps its own reason
        c = GR.report(TUNE)["criteria"]
        self.assertTrue(c["synthetic_only_when_never_replayed"])
        self.assertNotIn("synthetic_only_when_replay_short", c)
        self.assertIn("retired_set", c)


class m1FailedExportLeavesNoTemp(unittest.TestCase):
    def _repo(self):
        d = tmpdir(self)
        os.makedirs(os.path.join(d, ".claude/guild/gates/scripts"))
        with open(os.path.join(d, ".claude/guild/gates/scripts/gate.py"), "w") as fh:
            fh.write("print('gate')\n")
        git(d, "init", "-q")
        git(d, "add", "-A")
        git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        return d, git(d, "rev-parse", "HEAD")

    def _left(self, d, base):
        parent = os.path.dirname(S.gates_home(S.git_dirs(d)[1], base))
        return sorted(os.listdir(parent)) if os.path.isdir(parent) else []

    def test_a_failing_tar(self):
        d, base = self._repo()
        real = S.subprocess.run

        def failing_tar(cmd, *a, **k):
            r = real(cmd, *a, **k)
            if cmd and cmd[0] == "tar":
                r.returncode = 2                                                 # e.g. disk full mid-extract
            return r
        S.subprocess.run = failing_tar
        try:
            with self.assertRaises(Exception):
                S.export_gates_readonly(d, base)
        finally:
            S.subprocess.run = real
        self.assertEqual(self._left(d, base), [])
        dest, digest = S.export_gates_readonly(d, base)                          # the next call works
        self.assertTrue(S.verify_gates(dest, digest))
        self.assertEqual(self._left(d, base), sorted([base, base + ".sha256"]))

    def test_a_failure_while_publishing(self):
        d, base = self._repo()
        real = S.tree_digest

        def boom(path):
            raise RuntimeError("digest failed")
        S.tree_digest = boom
        try:
            with self.assertRaises(RuntimeError):
                S.export_gates_readonly(d, base)
        finally:
            S.tree_digest = real
        self.assertEqual(self._left(d, base), [])


class m2RunnerKeys(unittest.TestCase):
    RUNNERS = [os.path.join(_util.TESTS, "engine_k%d_test.sh" % k) for k in range(7)]
    CASES = [("OK (expected failures=1)", "0 0 0"),
             ("FAILED (failures=2, expected failures=1)", "2 0 0"),
             ("FAILED (errors=1, expected failures=3)", "0 1 0"),
             ("OK (skipped=1, expected failures=2)", "0 0 1"),
             ("FAILED (failures=1, errors=2, skipped=3, unexpected successes=1)", "1 2 3"),
             ("OK", "0 0 0")]

    def test_every_runner(self):
        for path in self.RUNNERS:
            src = _util.read(path)
            a = src.index("SKIPPED=$(printf")
            b = src.index("COUNTED=$((")
            for summary, want in self.CASES:
                with self.subTest(runner=os.path.basename(path), summary=summary):
                    r = subprocess.run(["bash", "-c", 'SUMMARY="$1"\n' + src[a:b] + 'echo "$FAILURES $ERRORS $SKIPPED"',
                                        "x", summary], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertEqual(r.stdout.decode().strip(), want)


class m3StaleDocs(unittest.TestCase):
    def test_gate_report_docstring(self):
        doc = GR.__doc__
        self.assertNotIn("held-out final pass", doc)
        self.assertNotIn("go in as tuning rows", doc)
        self.assertIn('`set: "retired"`', doc)
        self.assertIn("stays failed whatever rows are added later", doc)

    def test_r9_test_renamed(self):
        src = _util.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_k6_r9.py"))
        self.assertNotIn("test_latest_pass_reported", src)
        self.assertIn("test_passes_reported_never_counted", src)


if __name__ == "__main__":
    unittest.main()
