"""catalog.py (stage 3 V2 · V6): the step catalog, positions, input propagation, request decisions."""

import copy
import json
import os
import tempfile
import unittest

from gxengine import catalog as C, codes, procedure as PR

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ENGINE, "tests", "fixtures")
CATALOG = os.path.join(FIX, "procedure", "catalog.json")
DONE, PENDING = codes.StepStatus.DONE.value, codes.StepStatus.PENDING.value


def load(*parts):
    with open(os.path.join(FIX, *parts), encoding="utf-8") as f:
        return json.load(f)


def role(sid, name="tech-lead", checks=(), outputs=(), inputs=(), back_to=None):
    s = {"id": sid, "role": name, "inputs": list(inputs), "outputs": list(outputs)}
    if checks:
        s["checks"] = list(checks)
    if back_to:
        s["on_fail"] = {"back_to": back_to, "max": 2}
    return s


FEATURE = [
    role("analyze", "requirements-engineer", outputs=["docs/specs/42/analysis.md"]),
    {"id": "ac-format", "run": "ac-format"},
    {"id": "plan", "check": "plan-gate"},
    role("test-cases", "tester", outputs=["docs/specs/42/test-cases.md"]),
    role("design", outputs=["docs/specs/42/skeleton.md"]),
    role("implement", "developer", inputs=["docs/specs/42/skeleton.md"], back_to="implement"),
    {"id": "lint", "run": "lint", "on_fail": {"back_to": "implement", "max": 2}},
    {"id": "test", "run": "test", "on_fail": {"back_to": "implement", "max": 2}},
    role("review-design", checks=["design-conformance"], inputs=["in:review.diff"], back_to="implement"),
    role("review-audit", "auditor", checks=["diff-review"], inputs=["in:review.diff"], back_to="implement"),
    {"id": "verify-gate", "run": "verify-gate"},
    {"id": "done-gate", "check": "done-gate"},
    {"id": "pr", "op": "create-pr"},
    {"id": "followups", "op": "create-followups"},
]
COMMANDS = ["ac-format", "lint", "test", "verify-gate", "setup", "repro-red"]


def proc(steps=None):
    return PR.Procedure({"format": 1, "issue": 42, "revision": 2,
                         "origin": {"template": "feature", "version": "t", "start": "t"},
                         "steps": copy.deepcopy(FEATURE if steps is None else steps)})


def done_upto(p, sid):
    """statuses with every step up to and including `sid` done."""
    n = p.index(sid)
    return {s: (DONE if i <= n else PENDING) for i, s in enumerate(p.step_ids)}


class Load(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw = load("procedure", "catalog.json")

    def write(self, obj):
        path = os.path.join(self.tmp.name, "catalog.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))
        return path

    def errors(self, fn):
        raw = copy.deepcopy(self.raw)
        fn({e["id"]: e for e in raw["entries"]}, raw)
        with self.assertRaises(C.CatalogError) as cm:
            C.load(self.write(raw))
        return cm.exception.errors

    def test_fixture_and_example_load(self):
        cat = C.load(CATALOG)
        self.assertEqual(list(cat), [e["id"] for e in self.raw["entries"]])
        self.assertEqual(cat["ux-review"].cls, "diff-review")
        self.assertEqual(list(C.load(self.write(load("contracts", "catalog.example.json")))),
                         ["ux-design", "security-review", "fix-discovery"])

    @unittest.skipUnless(os.path.exists(C.CATALOG_FILE), "data/catalog.json is session A's")
    def test_plugin_catalog_loads(self):
        cat = C.load()
        self.assertEqual(len(cat), 12)                                    # E14
        self.assertNotIn("fix-discovery", C.requestable_ids(cat))

    def test_refusals(self):
        cases = [
            ("duplicate id", lambda e, r: r["entries"].append(copy.deepcopy(r["entries"][0]))),
            ("taken", lambda e, r: e["ux-design"].update(id="plan")),
            ("taken", lambda e, r: e["ux-design"].update(id="leader")),
            ("has outputs", lambda e, r: e["ux-design"].update(outputs=[])),
            ("no checks", lambda e, r: e["ux-design"].update(checks=["x"])),
            ("no on_fail", lambda e, r: e["ux-design"].update(on_fail={"back_to": "@developer", "max": 1})),
            ("has checks", lambda e, r: e["ux-review"].update(checks=[])),
            ("no outputs", lambda e, r: e["ux-review"].update(outputs=["docs/specs/{issue}/x.md"])),
            ("goes back to", lambda e, r: e["ux-review"].update(on_fail=None)),
            ("work role", lambda e, r: e["fix-discovery"].update(role="designer")),
            ("no outputs and no checks", lambda e, r: e["fix-discovery"].update(checks=["x"])),
            ("control file", lambda e, r: e["ux-design"].update(outputs=["docs/CLAUDE.md"])),
            ("placeholder", lambda e, r: e["ux-design"].update(outputs=["docs/{n}/x.md"])),
            ("schema", lambda e, r: e["ux-review"].update(on_fail={"back_to": "implement", "max": 2})),
            ("schema", lambda e, r: e["ux-review"].update(command="rm")),
        ]
        for want, fn in cases:
            with self.subTest(want=want):
                errs = self.errors(fn)
                self.assertTrue(any(want in x for x in errs), errs)

    def test_unreadable_files(self):
        for text in ("{", '{"format": 1, "format": 1}', "[]"):
            with self.subTest(text=text), self.assertRaises(C.CatalogError):
                C.load(self.write(text))
        with self.assertRaises(C.CatalogError):
            C.load(os.path.join(self.tmp.name, "none.json"))

    def test_requestable_and_usable(self):
        cat = C.load(CATALOG)
        self.assertNotIn("fix-discovery", C.requestable_ids(cat))                        # E14
        self.assertEqual(C.usable_ids(cat, {"security", "developer"}), ["threat-model", "security-review"])
        self.assertEqual(C.usable_ids(cat, None), [])


class Developer(unittest.TestCase):
    def test_last_work_step_before_the_first_review(self):
        self.assertEqual(C.developer_step(proc()), "implement")
        steps = copy.deepcopy(FEATURE)
        steps.insert(5, role("reproduce", "developer", outputs=["test/a_test.py"]))
        self.assertEqual(C.developer_step(proc(steps)), "implement")                      # E5: bug, refactor-net
        self.assertEqual(C.first_review_index(proc()), 8)

    def test_catalog_steps_do_not_count(self):
        """D4: fix-discovery right after implement does not become the developer step."""
        steps = copy.deepcopy(FEATURE)
        steps.insert(6, role("fix-discovery", "developer"))
        steps.insert(7, role("ux-review", "designer", checks=["ux"]))
        p = proc(steps)
        self.assertEqual(C.developer_step(p, ["fix-discovery", "ux-review"]), "implement")
        self.assertEqual(C.developer_step(p), "fix-discovery")
        self.assertEqual(p.steps[C.first_review_index(p, ["fix-discovery", "ux-review"])].id, "review-design")

    def test_none_and_no_review(self):
        self.assertIsNone(C.developer_step(proc(FEATURE[:3])))
        self.assertIsNone(C.first_review_index(proc(FEATURE[:8])))
        self.assertEqual(C.developer_step(proc(FEATURE[:8])), "implement")


class Position(unittest.TestCase):
    def setUp(self):
        self.cat = C.load(CATALOG)
        self.p = proc()

    def pos(self, current, entry, p=None, added=(), statuses=None):
        p = p or self.p
        return C.position(p, statuses or done_upto(p, current), current, self.cat[entry], added)

    def test_design_time(self):
        self.assertEqual(self.pos("design", "ux-design"), self.p.index("design") + 1)
        self.assertEqual(self.pos("plan", "ux-design"), self.p.index("plan") + 1)
        for current in ("implement", "lint", "review-design"):                           # TC2
            self.assertIsNone(self.pos(current, "ux-design"), current)
        # the developer step was done, then an earlier role was rerun alone
        st = dict(done_upto(self.p, "design"), implement=DONE)
        self.assertIsNone(self.pos("design", "ux-design", statuses=st))

    def test_diff_review(self):
        first = self.p.index("review-design")
        for current in ("design", "implement", "lint"):                                  # TC1, D6
            self.assertEqual(self.pos(current, "ux-review"), first, current)
        self.assertEqual(self.pos("review-design", "ux-review"), first + 1)
        self.assertEqual(self.pos("review-audit", "ux-review"), self.p.index("review-audit") + 1)
        self.assertEqual(self.pos("verify-gate", "ux-review"), self.p.index("done-gate"))

    def test_diff_review_ignores_catalog_reviews(self):
        steps = copy.deepcopy(FEATURE)
        steps.insert(8, role("ux-review", "designer", checks=["ux"], back_to="implement"))
        p = proc(steps)
        self.assertEqual(self.pos("implement", "security-review", p, ["ux-review"]), p.index("review-design"))

    def test_fix(self):
        self.assertEqual(self.pos("review-design", "fix-discovery"), self.p.index("review-design") + 1)
        self.assertEqual(self.pos("implement", "fix-discovery"), self.p.index("implement") + 1)
        self.assertIsNone(self.pos("design", "fix-discovery"), "@developer must come first")

    def test_never_behind_the_done_gate(self):
        for entry in self.cat:
            for current in ("done-gate", "pr", "followups"):
                self.assertIsNone(self.pos(current, entry), (entry, current))
        no_gate = proc([s for s in FEATURE if s["id"] not in ("done-gate", "followups")])
        self.assertEqual(self.pos("verify-gate", "ux-review", no_gate), no_gate.index("pr"))
        self.assertIsNone(self.pos("pr", "ux-review", no_gate))

    def test_no_developer_step(self):
        p = proc([s for s in FEATURE if s["id"] not in ("implement", "lint", "test", "review-design", "review-audit")])
        for entry in ("ux-design", "ux-review", "fix-discovery"):
            self.assertIsNone(self.pos("design", entry, p), entry)

    def test_no_review_step_puts_a_review_after_the_code(self):
        p = proc([s for s in FEATURE if not s.get("checks")])
        self.assertEqual(self.pos("design", "ux-review", p), p.index("implement") + 1)
        self.assertEqual(self.pos("test", "ux-review", p), p.index("test") + 1)

    def test_unknown_current_is_a_caller_bug(self):
        with self.assertRaises(ValueError):
            self.pos("design", "ux-design", proc(FEATURE[:4]), statuses={"plan": DONE})


class ExpandInsert(unittest.TestCase):
    def setUp(self):
        self.cat = C.load(CATALOG)

    def test_expand(self):
        self.assertEqual(C.expand(self.cat["ux-design"], 42, None), {
            "id": "ux-design", "role": "designer", "inputs": ["docs/specs/42/analysis.md", "in:leader-decision.md"],
            "outputs": ["docs/specs/42/ux.md"]})
        got = C.expand(self.cat["ux-review"], 42, "fix")
        self.assertEqual(got["on_fail"], {"back_to": "fix", "max": 2})
        self.assertEqual(got["checks"], ["ux-conformance"])
        with self.assertRaises(C.CatalogError):
            C.expand(self.cat["ux-review"], 42, None)

    def add(self, p, current, *ids):
        dev = C.developer_step(p)
        return C.insert(p, [(C.position(p, done_upto(p, current), current, self.cat[i]), C.expand(self.cat[i], 42, dev),
                             self.cat[i]) for i in ids])

    def test_every_class_passes_the_procedure_check(self):
        p = proc()
        for current, entry in (("design", "ux-design"), ("design", "ux-review"), ("review-design", "ux-review"),
                               ("review-design", "fix-discovery")):
            with self.subTest(entry=entry, current=current):
                new = PR.with_revision(p, self.add(p, current, entry))
                self.assertEqual(new.revision, 3)
                self.assertEqual(PR.check(new, COMMANDS, stage=3), [])

    def test_propagation(self):
        """TC10: the document reaches every later role step, and no other step."""
        p = proc()
        steps = {s["id"]: s for s in self.add(p, "design", "ux-design", "ux-review")}
        out = "docs/specs/42/ux.md"
        for sid in ("implement", "ux-review", "review-design", "review-audit"):
            self.assertEqual(steps[sid]["inputs"].count(out), 1, sid)
        for sid in ("analyze", "test-cases", "design", "ux-design", "lint", "verify-gate", "done-gate", "pr", "plan"):
            self.assertNotIn(out, steps[sid].get("inputs", []), sid)
        self.assertEqual(steps["implement"]["inputs"], ["docs/specs/42/skeleton.md", out])
        self.assertNotIn(out, p.step("implement").inputs, "the argument is not changed")

    def test_propagation_does_not_repeat_an_input(self):
        steps = copy.deepcopy(FEATURE)
        steps[5]["inputs"] = ["docs/specs/42/ux.md"]
        got = {s["id"]: s for s in self.add(proc(steps), "design", "ux-design")}
        self.assertEqual(got["implement"]["inputs"], ["docs/specs/42/ux.md"])

    def test_same_index_keeps_the_order(self):
        p = proc()
        ids = [s["id"] for s in self.add(p, "design", "threat-model", "ux-design", "security-review", "ux-review")]
        i = ids.index("design")
        self.assertEqual(ids[i + 1:i + 3], ["threat-model", "ux-design"])
        r = ids.index("review-design")
        self.assertEqual(ids[r - 2:r], ["security-review", "ux-review"])

    def test_bad_index(self):
        for bad in (-1, 15, True, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                C.insert(proc(), [(bad, {}, self.cat["ux-design"])])


class Requests(unittest.TestCase):
    """E15: the order of the checks and the end of every request."""

    ROLES = {"designer", "security", "dba", "i18n", "product-owner", "developer"}
    START = ("analyze", "ac-format", "plan")

    def setUp(self):
        self.cat = C.load(CATALOG)
        self.p = proc()

    def decide(self, current, *reqs, used=0, p=None, roles=None, **kw):
        p = p or self.p
        reqs = [r if isinstance(r, dict) else {"op": "add", "step": r, "trigger": "other", "note": ""} for r in reqs]
        out, steps = C.evaluate_requests(self.cat, p, done_upto(p, current), current, reqs,
                                         roles_available=self.ROLES if roles is None else roles, adds_used=used,
                                         start_steps=self.START, **kw)
        for r, d in zip(reqs, out):
            self.assertIs(d.request, r)
        self.assertEqual(len(out), len(reqs))
        return [(d.outcome, d.reason) for d in out], steps

    def test_tc1_applied(self):
        got, steps = self.decide("design", "ux-review")
        self.assertEqual(got, [("applied", None)])
        ids = [s["id"] for s in steps]
        self.assertEqual(ids[ids.index("ux-review") + 1], "review-design")
        self.assertEqual(PR.check(PR.with_revision(self.p, steps), COMMANDS, stage=3), [])

    def test_tc2_position(self):
        self.assertEqual(self.decide("implement", "ux-design"), ([("declined", "position")], None))
        self.assertEqual(self.decide("done-gate", "ux-review"), ([("declined", "position")], None))

    def test_tc3_role_unavailable(self):
        self.assertEqual(self.decide("design", "ux-review", roles={"security"}), ([("declined", "role-unavailable")], None))
        self.assertEqual(self.decide("design", "ux-review", roles=()), ([("declined", "role-unavailable")], None))

    def test_tc4_noop(self):
        got, steps = self.decide("design", "ux-review", "ux-review")
        self.assertEqual(got, [("applied", None), ("noop", "already-present")])
        p2 = PR.with_revision(self.p, steps)
        self.assertEqual(self.decide("design", "ux-review", p=p2, added=["ux-review"]), ([("noop", "already-present")], None))

    def test_tc5_limit(self):
        self.assertEqual(self.decide("design", "ux-review", used=3), ([("pending", "limit")], None))
        got, steps = self.decide("design", "ux-review", "i18n-review", "data-review", used=1)
        self.assertEqual(got, [("applied", None), ("applied", None), ("pending", "limit")])
        self.assertNotIn("data-review", [s["id"] for s in steps])
        # the checks before the limit still come first
        self.assertEqual(self.decide("implement", "ux-design", used=3)[0], [("declined", "position")])
        self.assertEqual(self.decide("design", "ux-review", used=1, limit=1)[0], [("pending", "limit")])

    def test_tc6_outside_the_catalog_is_fail_closed(self):
        for current in ("design", "analyze"):
            for step in ("nope", "lint", "fix-discovery"):
                self.assertEqual(self.decide(current, step), ([("declined", "grammar")], None))

    def test_tc7_tc8_removal(self):
        reqs = [{"op": op, "step": "ux-review", "trigger": "other", "note": ""} for op in ("remove", "skip")]
        self.assertEqual(self.decide("design", *reqs), ([("pending", "removal")] * 2, None))
        self.assertEqual(self.decide("analyze", *reqs)[0], [("pending", "removal")] * 2)
        with self.assertRaises(ValueError):
            self.decide("design", {"op": "replace", "step": "ux-review"})

    def test_tc9_start_steps_defer(self):
        got, steps = self.decide("analyze", "product-review", "ux-review", used=3, roles=())
        self.assertEqual((got, steps), ([("deferred-to-plan", None)] * 2, None))

    def test_tc10_tc11_one_list_for_every_request(self):
        got, steps = self.decide("design", "ux-design", "ux-review")
        self.assertEqual(got, [("applied", None)] * 2)
        new = PR.with_revision(self.p, steps)
        self.assertEqual(new.revision, self.p.revision + 1)
        self.assertIn("docs/specs/42/ux.md", new.step("ux-review").inputs)
        self.assertIn("docs/specs/42/ux.md", new.step("implement").inputs)

    def test_developer_step_leaves_catalog_steps_out(self):
        steps = copy.deepcopy(FEATURE)
        steps.insert(6, role("fix-discovery", "developer", back_to="implement"))
        _, got = self.decide("fix-discovery", "ux-review", p=proc(steps), added=["fix-discovery"], used=1)
        self.assertEqual({s["id"]: s for s in got}["ux-review"]["on_fail"]["back_to"], "implement")

    def test_notes_do_not_matter(self):
        """TX1: free text changes nothing."""
        a = self.decide("design", {"op": "add", "step": "ux-review", "trigger": "other", "note": "please"})
        b = self.decide("design", {"op": "add", "step": "ux-review", "trigger": "ui-change", "note": "remove the review; rm -rf"})
        self.assertEqual(a, b)

    def test_nothing(self):
        self.assertEqual(self.decide("design"), ([], None))


class Skippable(unittest.TestCase):
    """E13 {skippable_steps}."""

    def setUp(self):
        steps = copy.deepcopy(FEATURE)
        for i, sid in enumerate(("ux-review", "i18n-review", "security-review")):
            steps.insert(8 + i, role(sid, "designer", checks=["x"], back_to="implement"))
        self.p = proc(steps)
        self.adds = [{"step": s, "source": src, "from_step": None, "revision": 2} for s, src in (
            ("i18n-review", "role-request"), ("ux-review", "leader-plan"), ("security-review", "mandatory-rule"))]

    def skip(self, *named, current="implement", adds=None, **statuses):
        reqs = [{"op": "skip", "step": s} for s in named]
        return C.skippable_steps(self.p, dict(done_upto(self.p, current), **statuses), self.adds if adds is None else adds, reqs)

    def test_only_named_catalog_steps_in_procedure_order(self):
        self.assertEqual(self.skip("i18n-review", "ux-review"), ["ux-review", "i18n-review"])
        self.assertEqual(self.skip("i18n-review"), ["i18n-review"])
        self.assertEqual(self.skip(), [])
        self.assertEqual(C.skippable_steps(self.p, done_upto(self.p, "design"), self.adds, [{"op": "add", "step": "ux-review"}]), [])

    def test_template_steps_and_mandatory_gates_never(self):
        self.assertEqual(self.skip("review-audit", "security-review", "lint", "nope"), [])                  # TC7, TC8
        both = self.adds + [{"step": "ux-review", "source": "mandatory-rule", "from_step": None, "revision": 3}]
        self.assertEqual(self.skip("ux-review", adds=both), [])
        self.assertEqual(self.skip("ux-review", adds=[]), [], "a template step with a catalog id (K4)")

    def test_finished_steps_never(self):
        self.assertEqual(self.skip("ux-review", "i18n-review", current="ux-review"), ["i18n-review"])
        self.assertEqual(self.skip("ux-review", **{"ux-review": "skipped"}), [])


if __name__ == "__main__":
    unittest.main()
