"""review-k6-r12 — as table tests over the cases the findings name. Fewer rules, not more.

M1  group names are matched case-insensitively (`directive`, `Directive`, `split`, `EX-ARB:Dismiss` are the canonical
    groups), and one rule: a non-synthetic row naming an UNKNOWN group (a typo, no group) closes the synthetic path
    for every group of that input — reported under `_unknown_groups` and in each `why`. The reports are on stdout.
m3  `export_tree_readonly` drops its temp tree when the extraction itself raises (tar / git not runnable).
"""

import io
import json
import os
import contextlib
import unittest

import _util  # noqa: F401
from _k1 import git, tmpdir

from guildcore.roles import settings as S
from workflows.dev.replay import gate_report as GR

TUNE = [{"id": "#999999/D1", "group": "HANDOFF", "set": "tuning", "source": "replay", "agree": True,
         "advance_agree": True},
        {"id": "syn-tuning-only", "group": "DE-ARB", "set": "tuning", "source": "synthetic", "wrong": False}]


def rep(i, ok, g, st="held-out", **kw):
    return dict({"id": "#%d/D1" % i, "group": g, "set": st, "source": "replay", "agree": ok, "advance_agree": ok}, **kw)


def syn(i, g, **kw):
    return dict({"id": "syn-%s-%d" % (g, i), "group": g, "set": "held-out", "source": "synthetic", "wrong": False},
                **kw)


def failed(g):
    return [rep(100 + i, i >= 10, g) for i in range(20)]       # n 20, agreement 10/20 — measured and failed


class M1CaseAndUnknownGroups(unittest.TestCase):
    # (canonical group, spelling of the failed replay rows, planned synthetic n) — the reviewer's cases + typos
    CASES = [("DIRECTIVE", "DIRECTIVE", 2), ("DIRECTIVE", "directive", 2), ("DIRECTIVE", "Directive", 2),
             ("SPLIT", "split", 4), ("EX-ARB-dismiss", "EX-ARB:Dismiss", 2), ("EX-ARB-dismiss", "ex-arb-DISMISS", 2),
             ("DIRECTIVE", "DIRECTVE", 2), ("SPLIT", "SPLT", 4), ("DE-ARB", "", 3), ("DE-ARB", None, 3)]

    def test_table_a_failed_replay_is_never_covered_by_synthetic(self):
        for canon, spelt, n in self.CASES:
            with self.subTest(group=canon, spelt=spelt):
                d = GR.decide(failed(spelt) + [syn(i, canon) for i in range(n)] + TUNE)
                self.assertFalse(d[canon]["verified"], d[canon]["why"])

    def test_case_variants_are_the_canonical_group(self):
        for spelt, canon in (("directive", "DIRECTIVE"), ("Split", "SPLIT"), ("EX-ARB:Dismiss", "EX-ARB-dismiss"),
                             ("ex-arb", "EX-ARB"), ("handoff", "HANDOFF"), ("NOPE", "NOPE")):
            with self.subTest(spelt=spelt):
                self.assertEqual(GR.canonical(spelt), canon)
        per = GR.decide(failed("directive") + TUNE)
        self.assertEqual(per["DIRECTIVE"]["replay_n"], 20)               # counted under its canonical group
        self.assertTrue(per["DIRECTIVE"]["replayed"])
        self.assertNotIn("_unknown_groups", per)
        good = [rep(300 + i, True, "handoff") for i in range(20)]
        self.assertTrue(GR.decide(good + TUNE)["HANDOFF"]["verified"])   # a passing replay in lower case verifies

    def test_an_unknown_replay_group_closes_every_synthetic_path(self):
        rows = [syn(i, "SPLIT") for i in range(4)] + TUNE
        self.assertTrue(GR.decide(rows)["SPLIT"]["verified"])                     # control
        for extra in (rep(1, True, "NOPE"), rep(1, True, "NOPE", st="tuning"), dict(rep(1, True, "NOPE"), id=None),
                      rep(1, True, ""), {"id": "#1/D1", "set": "held-out", "source": "replay"}):
            with self.subTest(row=extra):
                per = GR.decide(rows + [extra])
                self.assertFalse(per["SPLIT"]["verified"])
                self.assertIn("unknown group", per["SPLIT"]["why"])
                self.assertIn("_unknown_groups", per)
        per = GR.decide(rows + [syn(9, "NOPE")])                                  # an unknown SYNTHETIC row: no
        self.assertTrue(per["SPLIT"]["verified"])
        self.assertEqual(per["_unknown_groups"], {"NOPE": 1})

    def test_replay_verification_is_unaffected(self):
        good = [rep(300 + i, True, "HANDOFF") for i in range(20)]
        per = GR.decide(good + [rep(1, True, "NOPE")] + TUNE)
        self.assertTrue(per["HANDOFF"]["verified"])

    def test_reports_on_stdout(self):
        d = tmpdir(self)
        src, out = os.path.join(d, "rows.json"), os.path.join(d, "v.json")
        rows = (failed("directive") + [syn(i, "DIRECTIVE") for i in range(2)] + [rep(1, True, "NOPE")]
                + [dict(rep(2, True, "SPLIT"), id="#2-D1")] + [rep(3, True, "SPLIT"), rep(3, True, "DE-ARB")] + TUNE)
        with open(src, "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(GR.main(["--rows", src, "--out", out]), 0)
        shown = json.loads(buf.getvalue())
        self.assertEqual(shown["verified"], [])
        self.assertEqual(shown["_unknown_groups"], {"NOPE": 1})
        self.assertIn("replay id is not issue/D-id", shown["_rows_rejected"])
        self.assertIn("replay #3/D1", shown["_conflicting_groups"])
        self.assertIn("DIRECTIVE", shown["replayed"])
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["groups"]["_unknown_groups"], {"NOPE": 1})


class m3ExtractExceptionLeavesNoTemp(unittest.TestCase):
    def test_tar_not_runnable(self):
        d = tmpdir(self)
        os.makedirs(os.path.join(d, "sub"))
        with open(os.path.join(d, "sub", "f.txt"), "w") as fh:
            fh.write("x\n")
        git(d, "init", "-q")
        git(d, "add", "-A")
        git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
        sha = git(d, "rev-parse", "HEAD")
        out = os.path.join(tmpdir(self), "out")
        dest = os.path.join(out, "sub")
        real = S.subprocess.run

        def boom(argv, *a, **kw):
            if argv and argv[0] == "tar":
                raise OSError("tar not runnable")
            return real(argv, *a, **kw)
        S.subprocess.run = boom
        try:
            with self.assertRaises(OSError):
                S.export_tree_readonly(d, sha, "sub", dest)
        finally:
            S.subprocess.run = real
        self.assertEqual(os.listdir(out), [])
        got, digest = S.export_tree_readonly(d, sha, "sub", dest)              # the next call works
        self.assertEqual(got, dest)
        self.assertEqual(sorted(os.listdir(out)), ["sub", "sub.sha256"])


if __name__ == "__main__":
    unittest.main()
