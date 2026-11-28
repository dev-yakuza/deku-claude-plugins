"""Readiness R1 — the fixed-defects list cannot drift from the reproduction tests (design incidents.md §9).

Every test that reproduces a fixed engine defect declares it with @fixes_defect(id, signature)
(tests/helpers/defects.py). This file fails when
  1. a declared (id, signature) is not in engine/data/fixed-defects.json with exactly that signature;
  2. an entry of the list has no declaring test;
  3. ids repeat, a signature breaks the grammar (incidents.signature_kind) or its kind does not match the entry's;
so a fix that adds a reproduction test cannot forget the list, and the list cannot hold an entry nobody tests.
It cannot see a fix whose test declares nothing (the design says so).
"""

import importlib
import inspect
import os
import unittest

from gxengine import incidents
from tests.helpers import defects

TESTS = os.path.dirname(os.path.abspath(__file__))


def declarations():
    """{(id, signature): ["module.Class.test", …]} of every @fixes_defect in tests/test_*.py (each method once, by
    the module that defines it)."""
    out = {}
    for name in sorted(os.listdir(TESTS)):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        mod = importlib.import_module(f"tests.{name[:-3]}")
        for cname, cls in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(cls, unittest.TestCase):
                continue
            for mname, fn in vars(cls).items():
                if not callable(fn) or cls.__module__ != mod.__name__:
                    continue
                for decl in getattr(fn, defects.ATTR, ()):
                    out.setdefault(tuple(decl), []).append(f"{mod.__name__}.{cname}.{mname}")
    return out


class FixedDefects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = incidents.load_fixed()
        cls.decl = declarations()

    def test_the_list_is_not_empty_and_ids_are_unique(self):
        ids = [e["id"] for e in self.entries]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_every_declaration_is_in_the_list(self):
        listed = {(e["id"], e["signature"]) for e in self.entries}
        for decl, where in self.decl.items():
            with self.subTest(decl=decl):
                self.assertIn(decl, listed, f"{where} declares {decl}, which engine/data/fixed-defects.json lacks "
                                            "(add the entry, or correct the signature)")

    def test_every_entry_has_a_reproduction_test(self):
        declared = {d[0] for d in self.decl}
        for e in self.entries:
            with self.subTest(id=e["id"]):
                self.assertIn(e["id"], declared, f"{e['id']} has no test with @fixes_defect({e['id']!r}, …)")

    def test_signatures_follow_the_grammar_and_the_kind(self):
        for e in self.entries:
            with self.subTest(id=e["id"]):
                self.assertEqual(incidents.signature_kind(e["signature"]), e["kind"], e["signature"])

    def test_the_first_entries(self):
        """E1 · E2 · O1 · E3 — the defects stage 4 fixed (VW2–VW4)."""
        by = {e["id"]: e for e in self.entries}
        self.assertEqual({i: (by[i]["signature"], by[i]["kind"]) for i in ("E1", "E2", "O1", "E3")}, {
            "E1": ("escalate:env-problem @ done-gate", "suspect"),
            "E2": ("escalate:env-problem @ done-gate", "suspect"),
            "O1": ("silent @ runner._overlay_runs", "silent"),
            "E3": ("silent @ driver._leader_notes", "silent")})

    def test_the_guard_catches_both_ways(self):
        """The two checks above on made-up data: a declaration the list lacks, an entry nobody declares."""
        listed = {("E1", "escalate:env-problem @ done-gate")}
        declared = {("E1", "escalate:env-problem @ done-gate"): ["t"], ("E7", "canary-failed @ analyze"): ["u"]}
        self.assertEqual(set(declared) - listed, {("E7", "canary-failed @ analyze")})
        self.assertEqual({"E1", "E8"} - {d[0] for d in declared}, {"E8"})

    def test_the_named_functions_exist(self):
        """A `silent` / engine-error location names a real function of the engine (module.function)."""
        for e in self.entries:
            where = e["signature"].split(" @ ", 1)[1]
            if e["kind"] == "suspect" or "." not in where:
                continue
            mod, _, func = where.partition(".")
            with self.subTest(id=e["id"]):
                m = importlib.import_module(f"gxengine.{mod}")
                self.assertTrue(callable(getattr(m, func, None)), where)


if __name__ == "__main__":
    unittest.main()
