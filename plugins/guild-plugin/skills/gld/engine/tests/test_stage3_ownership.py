"""Stage 3 facts and ownership: attempt_files, step_files, the output union, owned files, I3
(review-q0 D1, D2, D5; K2; scope §5.2 TB3, TB4, TR5). Real git, fake claude only."""

import copy
import json
import os
import tempfile
from unittest import mock

from gxengine import codes, facts, gitops, procedure, schema, store
from gxengine import results as R
from tests import a_layout, test_facts, test_results
from tests.helpers import fakes

CF = codes.CheckFailedReason
OF = codes.OutputFormatReason

TEST_GLOBS = ["test/**/*_test.dart", "integration_test/**/*_test.dart"]
NET_GLOBS = ["test/**/*_safety_net_test.dart"]


def bug_procedure():
    specs = "docs/specs/42"
    return {
        "format": 1, "issue": 42, "revision": 2, "origin": {"template": "bug", "version": "t", "start": "t"},
        "steps": [
            {"id": "analyze", "role": "requirements-engineer", "inputs": ["in:issue.md"], "outputs": [specs + "/analysis.md"]},
            {"id": "reproduce", "role": "developer", "inputs": [specs + "/analysis.md"], "outputs": TEST_GLOBS,
             "on_fail": {"back_to": "reproduce", "max": 2}},
            {"id": "repro-red", "run": "repro-red", "on_fail": {"back_to": "reproduce", "max": 2}},
            {"id": "fix", "role": "developer", "inputs": [], "outputs": [], "on_fail": {"back_to": "fix", "max": 2}},
            {"id": "review", "role": "tester", "inputs": ["in:review.diff"], "outputs": [],
             "checks": ["test-quality"], "on_fail": {"back_to": "fix", "max": 2}},
            {"id": "pr", "op": "create-pr"},
        ]}


BASE_FILES = dict(a_layout.BASE_FILES, **{"test/old_test.dart": "old\n", "test/goldens/a.png": "img\n"})


class Facts(test_facts.Base):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lay = a_layout.Layout(self._tmp.name, base_files=BASE_FILES)
        self.ctx = self.lay.ctx
        self.lay.procedure = procedure.Procedure(bug_procedure())
        self.n = 0

    def finish(self, step, work, stage=3, record=True, n=None, paths=True):
        """One attempt: `work()` changes the tree between start and finish."""
        self.n += 1
        n = n or self.n
        st = facts.start_facts(self.ctx, step, n, 42, "role")
        work()
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, step, session=test_facts.fake_session(self.lay),
                                stage=stage, paths=self.lay.ep if paths else None)
        if record:
            self.valid(fx)
        return fx

    def put(self, **files):
        def work():
            for rel, text in files.items():
                self.write(rel, text)
            self.lay.commit("work")
        return work

    def write(self, rel, text):
        rel = rel.replace("__", "/")
        if text is None:
            os.unlink(os.path.join(self.lay.wt, rel))
        else:
            self.lay.write(rel, text)

    def rows(self, fx):
        return {r["path"]: (r["old_blob"] is not None, r["new_blob"] is not None) for r in fx["attempt_files"]}

    def test_stage_2_facts_have_no_stage3_key(self):
        fx = self.finish("fix", self.put(**{"src/a.py": "x = 2\n"}), stage=2)
        for k in ("attempt_files", "golden"):
            self.assertNotIn(k, fx)
        self.assertNotIn("escalation", fx["session"])

    def test_attempt_files_are_this_attempt_only_both_rename_sides_and_dirty_files(self):
        self.finish("reproduce", self.put(**{"test/a_test.dart": "t\n"}))

        def work():
            self.lay.git("mv", "README.md", "READ2.md")
            self.lay.write("docs/specs/42/note.md", "n\n")
            self.lay.commit("rename")
            self.lay.write("src/a.py", "x = 9\n")            # dirty
            self.lay.write("src/new.py", "n\n")              # untracked
            os.unlink(os.path.join(self.lay.wt, "test/a_test.dart"))
        fx = self.finish("fix", work, n=1)
        self.assertEqual(self.rows(fx), {
            "README.md": (True, False), "READ2.md": (False, True), "docs/specs/42/note.md": (False, True),
            "src/a.py": (True, True), "src/new.py": (False, True), "test/a_test.dart": (True, False)})
        new = next(r for r in fx["attempt_files"] if r["path"] == "src/a.py")["new_blob"]
        self.assertEqual(new, self.lay.git("hash-object", "src/a.py"))

    def test_step_files_net_over_the_attempts(self):
        self.finish("reproduce", self.put(**{"test/a_test.dart": "1\n", "src/a.py": "oops\n", "docs/specs/42/x.md": "x\n"}))
        sf = facts.step_files(self.lay.ep, "reproduce", TEST_GLOBS)
        self.assertEqual((sf["step"], sf["attempts"], sf["owned"], sf["outside"]),
                         ("reproduce", [1], ["test/a_test.dart"], ["src/a.py"]))
        # a later step's work never counts
        self.finish("fix", self.put(**{"src/b.py": "b\n"}), n=1)
        # the second attempt takes the production change back and rewrites its own test
        self.finish("reproduce", self.put(**{"test/a_test.dart": "2\n", "src/a.py": a_layout.BASE_FILES["src/a.py"],
                                             "test/old_test.dart": "changed\n"}), n=2)
        sf = facts.step_files(self.lay.ep, "reproduce", TEST_GLOBS)
        self.assertEqual((sf["attempts"], sf["owned"], sf["outside"]),
                         ([1, 2], ["test/a_test.dart", "test/old_test.dart"], []))
        self.assertEqual(sf["net"]["test/a_test.dart"], [None, self.lay.git("hash-object", "test/a_test.dart")])
        self.assertIsNotNone(sf["net"]["test/old_test.dart"][0])

    def test_a_file_made_and_removed_is_not_owned(self):
        self.finish("reproduce", self.put(**{"test/a_test.dart": "1\n"}))
        self.finish("reproduce", self.put(**{"test/a_test.dart": None}))
        self.assertEqual(facts.step_files(self.lay.ep, "reproduce", TEST_GLOBS)["net"], {})

    def test_no_attempt_yet(self):
        sf = facts.step_files(self.lay.ep, "reproduce", TEST_GLOBS)
        self.assertEqual(sf, {"step": "reproduce", "attempts": [], "net": {}, "owned": [], "outside": []})

    def test_facts_without_attempt_files_are_fact_missing(self):
        self.finish("reproduce", self.put(**{"test/a_test.dart": "1\n"}), stage=2)
        with self.assertRaises(facts.FactMissing):
            facts.step_files(self.lay.ep, "reproduce", TEST_GLOBS)

    def test_an_attempt_the_engine_lost_is_counted_by_the_next_one(self):
        """Killed between the session and facts.json: its committed work belongs to the next attempt."""
        with open(os.path.join(a_layout.__file__.rsplit("/", 1)[0], "fixtures", "contracts", "brief.example.json"),
                  encoding="utf-8") as f:
            brief = json.load(f)
        brief.update({"step": "reproduce", "attempt": 1, "issue": 42, "start_head": gitops.head(self.ctx)})
        store.write_brief(self.lay.ep, "reproduce", 1, brief)
        self.finish("reproduce", self.put(**{"test/a_test.dart": "1\n", "src/a.py": "oops\n"}), record=False)   # no facts.json
        fx = self.finish("reproduce", lambda: None, n=2)
        self.assertEqual(sorted(self.rows(fx)), ["src/a.py", "test/a_test.dart"])
        sf = facts.step_files(self.lay.ep, "reproduce", TEST_GLOBS)
        self.assertEqual((sf["attempts"], sf["owned"], sf["outside"]), ([2], ["test/a_test.dart"], ["src/a.py"]))
        # an attempt that HAS facts ends the search
        self.assertEqual(self.finish("reproduce", lambda: None, n=3)["attempt_files"], [])

    def test_tm1_the_escalation_is_carried_into_the_session_facts(self):
        from gxengine import ladder
        esc = ladder.raised({"model": "sonnet", "effort": "high", "layer": "plugin-default"}, 3,
                            ["sonnet", "opus"], ["high", "xhigh"])["escalation"]
        for want in (esc, None):
            self.n += 1
            st = facts.start_facts(self.ctx, "fix", self.n, 42, "role")
            if want is not None:
                st["escalation"] = want
            fx = facts.finish_facts(self.ctx, st, self.lay.procedure, "fix",
                                    session=test_facts.fake_session(self.lay), stage=3)
            self.assertEqual(fx["session"]["escalation"], want)
            self.valid(fx)

    def test_attempt_files_failure_is_fact_missing(self):
        with mock.patch.object(facts, "attempt_file_facts", side_effect=gitops.GitError("boom")):
            with self.assertRaises(facts.FactMissing) as cm:
                self.finish("fix", lambda: None)
        self.assertEqual(cm.exception.fact, "attempt_files")

    # D5 ------------------------------------------------------------------------------------
    def outputs(self, stage=3, step="reproduce"):
        return facts.output_facts(self.ctx, self.lay.procedure, step, gitops.head(self.ctx), stage=stage)

    def test_d5_the_union_of_the_globs_has_one_file(self):
        self.assertEqual([o["path"] for o in self.outputs() if not o["exists"]], [])      # test/old_test.dart is there
        self.assertEqual([o["path"] for o in self.outputs(stage=2) if not o["exists"]],
                         ["integration_test/**/*_test.dart"])
        self.lay.git("rm", "-q", "test/old_test.dart")
        self.lay.commit("no test left")
        self.assertEqual([(o["path"], o["exists"]) for o in self.outputs()], [(g, False) for g in TEST_GLOBS])

    def test_d5_judge_outputs_keep_the_old_rule(self):
        self.assertEqual(self.outputs(step="analyze"),
                         [{"path": "docs/specs/42/analysis.md", "exists": False, "regular": False, "blob": None}])

    def test_d5_an_old_link_is_not_this_steps_output(self):
        os.symlink("old_test.dart", os.path.join(self.lay.wt, "test", "link_test.dart"))
        self.assertIn(("test/link_test.dart", False), [(o["path"], o["regular"]) for o in self.outputs()])   # new → refused
        self.ctx.base_sha = self.lay.commit("link on the base")
        self.assertNotIn("test/link_test.dart", [o["path"] for o in self.outputs()])


class Flow(test_results.Flow):
    STAGE = 3
    CATALOG = test_results.CATALOG_IDS
    PROCEDURE = bug_procedure()
    BASE_FILES = BASE_FILES

    def finish_kwargs(self):
        return {"stage": 3, "paths": self.lay.ep}

    def owned_kwargs(self):
        return {"owned": R.owned_files(self.lay.ep, self.lay.procedure)}

    def scenario_of(self, files, name="s.json"):
        return self.lay.scenario(name, {
            "format": 1, "stream": fakes.scn("../f2/r4.jsonl"), "init_from_argv": True,
            "structured_output": test_results.s3_work(),
            "actions": [{"op": "write", "path": p, "content": t} for p, t in files.items()] + [
                {"op": "git", "args": ["add", "-A"]}, {"op": "git", "args": ["commit", "-q", "-m", "work"]}]})

    def reproduce(self):
        out, fx, _ = self.attempt("reproduce", fakes.scn("t-reproduce-ok.json"))
        self.assertEqual(out.status, "done", (out, out.errors))
        return fx


class OwnedFiles(Flow):
    def test_owned_files_are_the_net_files_of_the_attempts(self):
        self.assertEqual(R.owned_files(self.lay.ep, self.lay.procedure), {"reproduce": {}})
        self.reproduce()
        self.assertEqual(R.owned_files(self.lay.ep, self.lay.procedure),
                         {"reproduce": {"test/a_test.dart": self.lay.git("hash-object", "test/a_test.dart")}})

    def test_tb4_the_fix_may_not_touch_the_regression_test(self):
        self.reproduce()
        out, fx, dec = self.attempt("fix", fakes.scn("t-fix-regression-test.json"))
        self.assertCheckFailed(out, dec, CF.FOREIGN_OUTPUT.value)
        self.assertEqual(fx["ownership"]["foreign"], [{"path": "test/a_test.dart", "owner_step": "reproduce"}])
        self.assertEqual(dec.target, "fix")

    def test_d2_other_tests_are_free(self):
        """A signature change of the fix may update another test or add one (test-change-review looks at it)."""
        self.reproduce()
        out, fx, _ = self.attempt("fix", self.scenario_of({"src/a.py": "x = 3\n", "test/old_test.dart": "new\n",
                                                           "test/more_test.dart": "m\n"}))
        self.assertEqual(out.status, "done", (out, out.errors))
        self.assertTrue(fx["ownership"]["ok"])

    def test_without_owned_the_glob_rule_stays(self):
        self.reproduce()
        self.lay.write("test/more_test.dart", "m\n")
        self.lay.commit("more")
        old = R.check_ownership(self.ctx, self.lay.procedure, self.state, "fix", self.owner)
        self.assertEqual(old["foreign"], [{"path": "test/more_test.dart", "owner_step": "reproduce"}])
        self.assertTrue(R.check_ownership(self.ctx, self.lay.procedure, self.state, "fix", self.owner,
                                          **self.owned_kwargs())["ok"])

    def test_deleting_the_regression_test_is_foreign(self):
        self.reproduce()
        self.lay.git("rm", "-q", "test/a_test.dart")
        self.lay.commit("drop")
        own = R.check_ownership(self.ctx, self.lay.procedure, self.state, "fix", self.owner, **self.owned_kwargs())
        self.assertEqual(own["foreign"], [{"path": "test/a_test.dart", "owner_step": "reproduce"}])

    def test_the_owner_may_change_its_file_and_becomes_the_reference(self):
        self.reproduce()
        next(s for s in self.state["steps"] if s["id"] == "reproduce")["status"] = "pending"
        out, fx, _ = self.attempt("reproduce", self.scenario_of({"test/a_test.dart": "better\n"}))
        self.assertEqual(out.status, "done", (out, out.errors))
        out, fx, _ = self.attempt("fix", fakes.scn("t-fix-ok.json"))
        self.assertEqual(out.status, "done", (out, out.errors))

    def test_a_judge_output_is_still_owned_by_glob(self):
        self.lay.write("docs/specs/42/analysis.md", "by the fix\n")
        self.lay.commit("x")
        own = R.check_ownership(self.ctx, self.lay.procedure, self.state, "fix", self.owner, **self.owned_kwargs())
        self.assertEqual(own["foreign"], [{"path": "docs/specs/42/analysis.md", "owner_step": "analyze"}])

    def test_tb3_scope_facts(self):
        out, fx, _ = self.attempt("reproduce", fakes.scn("t-reproduce-production.json"))
        self.assertEqual(out.status, "done")                 # the judge of the scope is run: repro-red
        sf = facts.step_files(self.lay.ep, "reproduce", TEST_GLOBS)
        self.assertEqual((sf["owned"], sf["outside"]), (["test/a_test.dart"], ["src/a.py"]))


class BlockTarget(Flow):
    """K2: I3 goes back to the step that really owns the file, not to whoever's glob matches."""

    def target(self, path, **kw):
        return R.block_target(self.lay.procedure, "review", [{"severity": "blocker", "file": path}], **kw)

    def test_k2(self):
        self.reproduce()
        owned = self.owned_kwargs()
        self.assertEqual(self.target("test/a_test.dart", **owned), "reproduce")
        self.assertEqual(self.target("./test/a_test.dart", **owned), "reproduce")
        self.assertEqual(self.target("test/old_test.dart", **owned), "fix")          # glob only → the on_fail target
        self.assertEqual(self.target("docs/specs/42/analysis.md", **owned), "analyze")
        self.assertEqual(self.target("test/old_test.dart"), "reproduce")             # stages 1–2: the glob

    def test_the_judge_passes_it_on(self):
        self.reproduce()
        res = test_results.s3_work(verdict="block", reviewed=["src/a.py"],
                                   checks=[{"id": "test-quality", "result": "pass", "note": ""}],
                                   findings=[{"severity": "blocker", "file": "test/old_test.dart", "line": None, "text": "t"}])
        del res["golden_reasons"]
        brief = {"result_kind": "review", "checks": ["test-quality"], "rule_checks": []}
        for owned, want in ((None, "reproduce"), (self.owned_kwargs()["owned"], "fix")):
            out = R.judge_role(self.lay.procedure, "review", brief, copy.deepcopy(res), test_results._facts(),
                               stage=3, catalog_steps=self.CATALOG, owned=owned)
            self.assertEqual((out.detail, out.back_to), (CF.VERDICT_BLOCK.value, want), out.errors)


class FactsExamples(test_facts.unittest.TestCase):
    def test_the_contract_examples_still_fit(self):
        d = os.path.join(os.path.dirname(a_layout.__file__), "fixtures", "contracts")
        for name in ("facts.stage3-role", "facts.stage3-repro-red", "facts.stage3-frozen"):
            with open(os.path.join(d, name + ".example.json"), encoding="utf-8") as f:
                schema.validate(json.load(f), "facts")
