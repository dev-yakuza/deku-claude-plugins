"""Stage 3 V14 (P2): the baseline-image ledger and its reasons (E33; scope §5.2 TG1–TG3). TG4 = test_runner_stage3.Frozen."""

import os

from gxengine import codes, facts, repoconfig, schema
from gxengine import results as R
from tests import test_results, test_stage3_ownership
from tests.helpers import fakes

OF = codes.OutputFormatReason
CONFIG = {"format": 1, "commands": {"test": {"cmd": "true"}}, "path_rules": [
    {"kind": "verification", "category": "test", "globs": ["test/**/*_test.dart"]},
    {"kind": "verification", "category": "golden", "globs": ["test/goldens/**"]},
    {"kind": "verification", "category": "comparison-config", "globs": ["compare.json"]}]}


class Golden(test_stage3_ownership.Flow):
    BASE_FILES = dict(test_stage3_ownership.BASE_FILES, **{"compare.json": "{}\n"})

    def setUp(self):
        super().setUp()
        self.cfg = repoconfig.RepoConfig(CONFIG)

    def finish_kwargs(self):
        return {"stage": 3, "paths": self.lay.ep, "config": self.cfg}

    def pending(self, step="fix"):
        """Make the step runnable again (what an answer / a resume does after a stop)."""
        self.state["stop"] = None
        next(s for s in self.state["steps"] if s["id"] == step)["status"] = "pending"

    def fix(self, reasons=(), files=None, dirty=None, delete=()):
        self.pending()
        acts = [{"op": "write", "path": p, "content": t} for p, t in (files or {}).items()]
        acts += [{"op": "delete", "path": p} for p in delete]
        acts += [{"op": "git", "args": ["add", "-A"]}, {"op": "git", "args": ["commit", "-q", "--allow-empty", "-m", "w"]}]
        scn = self.lay.scenario(f"g{self.attempts.get('fix', 0)}.json", {
            "format": 1, "stream": fakes.scn("../f2/r4.jsonl"), "init_from_argv": True, "actions": acts,
            "structured_output": test_results.s3_work(
                golden_reasons=[{"path": p, "reason": r} for p, r in reasons])})
        return self.attempt("fix", scn)

    def rows(self, fx):
        return [(g["row"], g["path"], g["reason"]) for g in fx["golden"]]

    def test_tg1_a_change_with_its_reason(self):
        out, fx, _ = self.attempt("fix", fakes.scn("t-fix-golden-reason.json"))
        self.assertEqual(out.status, "done", (out, out.errors))
        self.assertEqual(self.rows(fx), [("M", "test/goldens/a.png", "bug-fix")])
        self.assertEqual(fx["golden"][0]["new_blob"], self.lay.git("hash-object", "test/goldens/a.png"))

    def test_tg2_a_change_without_a_reason(self):
        out, fx, dec = self.attempt("fix", fakes.scn("t-fix-golden-no-reason.json"))
        self.assertEqual((out.code, out.detail), ("output-format", OF.MISSING_GOLDEN_REASON.value))
        self.assertEqual(dec.action, "retry-same")
        # the retry changes nothing, but the row is still there: the reason is still due
        out, fx, _ = self.fix()
        self.assertEqual(out.detail, OF.MISSING_GOLDEN_REASON.value)
        out, fx, _ = self.fix([("./test/goldens/a.png", "intended-change")])
        self.assertEqual(out.status, "done", (out, out.errors))

    def test_the_reason_is_carried_over_while_the_blobs_stay(self):
        self.fix([("test/goldens/a.png", "bug-fix")], {"test/goldens/a.png": "v1\n"})
        out, fx, _ = self.fix(files={"src/a.py": "x = 7\n"})
        self.assertEqual((out.status, self.rows(fx)), ("done", [("M", "test/goldens/a.png", "bug-fix")]))
        out, fx, _ = self.fix(files={"test/goldens/a.png": "v2\n"})          # another content: a new reason
        self.assertEqual(out.detail, OF.MISSING_GOLDEN_REASON.value)
        out, fx, _ = self.fix(files={"test/goldens/a.png": "img\n"})         # back to the base: no row
        self.assertEqual((out.status, fx["golden"]), ("done", []))

    def test_rows(self):
        out, fx, _ = self.fix([("test/goldens/new.png", "new-case")], {"test/goldens/new.png": "n\n"})
        self.assertEqual((out.status, self.rows(fx)), ("done", [("A", "test/goldens/new.png", "new-case")]))
        out, fx, _ = self.fix([("test/goldens/a.png", "intended-change")], delete=["test/goldens/a.png"])
        self.assertEqual(self.rows(fx), [("D", "test/goldens/a.png", "intended-change"),
                                         ("A", "test/goldens/new.png", "new-case")])
        out, fx, _ = self.fix(files={"test/goldens/moved/a.png": "img\n"})
        self.assertEqual([r for r in fx["golden"] if r["row"] == "R"],
                         [{"row": "R", "path": "test/goldens/moved/a.png", "from": "test/goldens/a.png",
                           "old_blob": self.lay.git("rev-parse", self.lay.base_sha + ":test/goldens/a.png"),
                           "new_blob": self.lay.git("rev-parse", self.lay.base_sha + ":test/goldens/a.png"), "reason": None}])
        self.assertEqual(out.status, "done", (out, out.errors))             # R needs no reason

    def test_tg3_a_comparison_config_row_needs_a_reason_too(self):
        out, fx, _ = self.fix(files={"compare.json": "loose\n"})
        self.assertEqual((out.detail, self.rows(fx)), (OF.MISSING_GOLDEN_REASON.value, [("C", "compare.json", None)]))
        out, fx, _ = self.fix([("compare.json", "intended-change")])
        self.assertEqual(out.status, "done", (out, out.errors))

    def test_needs_regeneration(self):
        out, fx, _ = self.fix([("test/goldens/a.png", "needs-regeneration"), ("src/a.py", "needs-regeneration")])
        self.assertEqual((out.status, self.rows(fx)), ("done", [("P", "test/goldens/a.png", "needs-regeneration")]))
        out, fx, _ = self.fix()
        self.assertEqual(self.rows(fx), [("P", "test/goldens/a.png", "needs-regeneration")])
        out, fx, _ = self.fix([("test/goldens/a.png", "bug-fix")], {"test/goldens/a.png": "done\n"})
        self.assertEqual((out.status, self.rows(fx)), ("done", [("M", "test/goldens/a.png", "bug-fix")]))

    def test_a_dirty_image_counts(self):
        self.lay.write("test/goldens/a.png", "dirty\n")
        tree = {"clean": False, "dirty_files": ["test/goldens/a.png"]}
        rows = facts.golden_facts(self.ctx, self.cfg, self.lay.git("rev-parse", "HEAD"), tree, {}, {})
        self.assertEqual([(r["row"], r["new_blob"]) for r in rows], [("M", self.lay.git("hash-object", "test/goldens/a.png"))])
        os.unlink(os.path.join(self.lay.wt, "test/goldens/a.png"))
        rows = facts.golden_facts(self.ctx, self.cfg, self.lay.git("rev-parse", "HEAD"), tree, {}, {})
        self.assertEqual([r["row"] for r in rows], ["D"])

    def test_no_config_means_no_ledger(self):
        self.finish_kwargs = lambda: {"stage": 3, "paths": self.lay.ep}
        out, fx, _ = self.attempt("fix", fakes.scn("t-fix-golden-no-reason.json"))
        self.assertEqual((out.status, fx["golden"]), ("done", None))

    def test_no_golden_rule(self):
        self.cfg = repoconfig.RepoConfig({"format": 1, "commands": {"test": {"cmd": "true"}}})
        out, fx, _ = self.attempt("fix", fakes.scn("t-fix-golden-no-reason.json"))
        self.assertEqual((out.status, fx["golden"]), ("done", []))

    def test_a_judge_is_not_asked_for_reasons(self):
        self.lay.write("test/goldens/a.png", "by a human\n")
        self.lay.commit("human")
        fx = test_results._facts()
        fx["golden"] = [{"row": "M", "path": "test/goldens/a.png", "from": None, "old_blob": None, "new_blob": None, "reason": None}]
        res = test_results.s3_work()
        judge = lambda step: R.judge_role(self.lay.procedure, step, {"result_kind": "work"}, res, fx, stage=3,
                                          catalog_steps=self.CATALOG)             # noqa: E731
        self.assertEqual(judge("analyze").status, "done")
        self.assertEqual(judge("fix").detail, OF.MISSING_GOLDEN_REASON.value)

    def test_malformed_reasons_are_left_to_the_schema(self):
        self.assertEqual(facts.golden_reasons(None), {})
        self.assertEqual(facts.golden_reasons({"golden_reasons": ["x", {"path": 1, "reason": "bug-fix"}, {"path": "a", "reason": "?"}]}), {})
        self.assertTrue(schema.schema_tokens(schema.load_schema("result-work-s3")))
