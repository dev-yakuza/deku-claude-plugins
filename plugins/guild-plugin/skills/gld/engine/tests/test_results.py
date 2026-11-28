"""U8 result handling and boundary judgments — scope §5.2 C · O · S (U6–U8 part), plus R units.

Every attempt runs end to end: facts.start_facts → session.run_session (fake claude) →
facts.finish_facts → results.add_boundary_facts → results.judge_role → statemachine.apply.
Real git in a temp repository; no paid call, nothing outside the temp dir.
"""

import copy
import os
import tempfile
import unittest

from gxengine import codes, facts, gitops, globs, procedure, schema, session, statemachine, store
from gxengine import results as R
from tests import a_layout
from tests.helpers import fakes

ST = codes.StopReason
CF = codes.CheckFailedReason
OF = codes.OutputFormatReason


def new_state(lay):
    return store.new_state(lay.issue, lay.procedure.revision, lay.procedure.step_ids, lay.base_sha)


class Flow(unittest.TestCase):
    """One Issue in a temp repo: the engine has committed procedure.yaml, analyze is done."""

    STAGE = 2
    CATALOG = ()          # stage 3: the `{catalog_steps}` fill of the result schemas
    PROCEDURE = None      # None = a_layout.PROCEDURE
    BASE_FILES = None     # None = a_layout.BASE_FILES

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lay = a_layout.Layout(self._tmp.name, base_files=self.BASE_FILES)
        if self.PROCEDURE is not None:
            self.lay.procedure = procedure.Procedure(copy.deepcopy(self.PROCEDURE))
        self.ctx = self.lay.ctx
        self.state = new_state(self.lay)
        self.owner = {}
        self.attempts = {}
        # the engine writes and commits procedure.yaml (§6.1)
        self.lay.write("docs/specs/42/procedure.yaml", "{}\n")
        self.proc_commit = gitops.commit_paths(self.ctx, ["docs/specs/42/procedure.yaml"], "chore: procedure")

    def tearDown(self):
        self._tmp.cleanup()

    def finish_kwargs(self):
        """Stage-3 arguments of facts.finish_facts (the driver's)."""
        return {}

    def owned_kwargs(self):
        """Stage-3 ownership argument of add_boundary_facts / judge_role (the driver's)."""
        return {}

    def attempt(self, step_id, scenario, mark=True):
        p = self.lay.procedure.step(step_id)
        n = self.attempts.get(step_id, 0) + 1
        self.attempts[step_id] = n
        if mark:
            # walk the state machine up to this step (earlier steps count as done)
            for s in self.state["steps"]:
                if s["id"] == step_id:
                    break
                if s["status"] != "done":
                    s["status"] = "done"
            statemachine.mark_running(self.state, step_id, n, gitops.head(self.ctx))
        if p.kind == codes.StepKind.RUN.value:
            raise AssertionError("use run_attempt")
        st = facts.start_facts(self.ctx, step_id, n, 42, p.kind)
        inp = self.lay.role_input(step_id, p.name, attempt=n, outputs=p.outputs, checks=bool(p.checks))
        if self.STAGE >= 3:
            inp.json_schema = R.result_schema("review" if p.checks else "work", self.STAGE, self.CATALOG)
            inp._check_role()
        st["requested"] = {"model": inp.model, "effort": inp.effort}
        res = session.run_session(inp, self.lay.attempt_dir(step_id, n), self.lay.env(scenarios=[scenario]),
                                  claude_bin=fakes.FAKE_CLAUDE)
        if res.structured is not None:
            store.write_result(self.lay.ep, step_id, n, res.structured)
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, step_id, session=res, **self.finish_kwargs())
        R.add_boundary_facts(self.ctx, self.lay.procedure, self.state, step_id, fx, self.proc_commit, self.owner,
                             **self.owned_kwargs())
        brief = {"result_kind": "review" if p.checks else "work", "checks": list(p.checks), "rule_checks": []}
        out = R.judge_role(self.lay.procedure, step_id, brief, res.structured, fx, res.quota_reset_at,
                           stage=self.STAGE, catalog_steps=self.CATALOG, **self.owned_kwargs())
        dec = statemachine.apply(self.state, self.lay.procedure, step_id, out)
        status = next(s for s in self.state["steps"] if s["id"] == step_id)["status"]
        fx["outcome"] = R.outcome_fact(out, status)
        if out.status == "done" and p.is_judge:
            R.commit_judge_outputs(self.ctx, self.lay.procedure, step_id, 42, fx)
        self.assertEqual(schema.errors(fx, schema.load_schema("facts")), [])
        store.write_facts(self.lay.ep, step_id, n, fx)
        if out.status == "done":
            self.owner[step_id] = fx
        return out, fx, dec

    def analyze_done(self):
        out, fx, _ = self.attempt("analyze", fakes.scn("a-analyze-ok.json"))
        self.assertEqual(out.status, "done", out)
        self.assertIsNotNone(fx["outputs"][0]["blob"])      # read back from the engine commit
        return fx

    def assertStop(self, out, dec, reason):
        self.assertEqual((out.status, out.stop), ("stop", reason), out)
        self.assertEqual(dec.action, "stop")
        self.assertEqual(dec.stop, ("needs_human", reason))
        self.assertIsNone(dec.target)                       # never on_fail

    def assertCheckFailed(self, out, dec, detail):
        self.assertEqual((out.status, out.code, out.detail), ("failed", "check-failed", detail), out)
        self.assertEqual(dec.action, "back-to")


class Normal(Flow):
    def test_judge_then_developer_then_judge(self):
        a = self.analyze_done()
        out, fx, dec = self.attempt("design", fakes.scn("ok-judge.json"))
        self.assertEqual(out.status, "done", out)
        self.assertEqual(fx["judge_writes_outside"], [])
        self.assertTrue(fx["control_files"]["ok"])
        # the engine committed the judge output: the tree is clean, the blob is recorded
        self.assertTrue(gitops.tree_state(self.ctx)["clean"])
        self.assertIsNotNone(fx["outputs"][0]["blob"])
        msg = gitops.git(self.ctx, "log", "-1", "--format=%B")
        self.assertNotIn("#", msg)
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-ok.json"))
        self.assertEqual(out.status, "done", out)
        self.assertTrue(fx["ownership"]["ok"])
        self.assertIsNone(fx["judge_writes_outside"])
        self.assertEqual(a["outputs"][0]["path"], "docs/specs/42/analysis.md")


class C(Flow):
    """C — control files: security-boundary stop, result discarded, never on_fail, never reverted."""

    def test_c1_commit(self):
        out, fx, dec = self.attempt("implement", fakes.scn("developer-commits-control-file.json"))
        self.assertStop(out, dec, ST.CONTROL_FILE.value)
        self.assertIn(".claude/agents/x.md", fx["control_files"]["changed"])
        self.assertTrue(os.path.exists(os.path.join(self.lay.wt, ".claude/agents/x.md")))    # not reverted

    def test_c2_worktree_only(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-control-worktree.json"))
        self.assertStop(out, dec, ST.CONTROL_FILE.value)
        self.assertEqual(fx["control_files"]["changed"], [".claude/agents/developer.md"])

    def test_c3_gitignored(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-control-ignored.json"))
        self.assertStop(out, dec, ST.CONTROL_FILE.value)
        self.assertEqual(fx["control_files"]["changed"], [".claude/local/x.md"])
        self.assertNotIn(".claude/local/x.md", facts.changed_paths(fx))      # git does not see it

    def test_c4_nested(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-control-nested.json"))
        self.assertStop(out, dec, ST.CONTROL_FILE.value)
        self.assertEqual(fx["control_files"]["changed"],
                         ["pkg/AGENTS.md", "pkg/CLAUDE.md", "pkg/sub/CLAUDE.local.md"])

    def test_c5_procedure(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-procedure-edit.json"))
        self.assertStop(out, dec, ST.CONTROL_FILE.value)
        self.assertEqual(fx["control_files"]["changed"], ["docs/specs/42/procedure.yaml"])

    def test_c5_procedure_reference_is_the_engine_commit(self):
        # unchanged procedure.yaml: compared with the engine's commit, not the base (where it is absent)
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertTrue(cf["ok"], cf)
        cf = R.check_control_files(self.ctx, None, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], ["docs/specs/42/procedure.yaml"])    # no engine commit → base

    def test_c6_revert_passes(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-control-revert.json"))
        self.assertEqual(out.status, "done", out)
        self.assertTrue(fx["control_files"]["ok"])
        self.assertEqual(len(fx["commits"]), 3)

    def test_c6_partial_revert_fails(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-control-revert-partial.json"))
        self.assertStop(out, dec, ST.CONTROL_FILE.value)
        self.assertEqual(fx["control_files"]["changed"], ["CLAUDE.md"])

    def test_c7_run_writes_control_file(self):
        statemachine.mark_running(self.state, "test", 1, gitops.head(self.ctx))
        st = facts.start_facts(self.ctx, "test", 1, 42, "run")
        self.lay.write("sub/CLAUDE.md", "from a run\n")            # what the run command did
        run = {"name": "test", "exit_code": 0, "timed_out": False, "log_file": "run.log"}
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, "test", run=run)
        R.add_boundary_facts(self.ctx, self.lay.procedure, self.state, "test", fx, self.proc_commit)
        out = R.judge_run(self.lay.procedure.step("test"), fx)
        self.assertEqual((out.status, out.stop), ("stop", ST.CONTROL_FILE.value))

    def test_c9_gitignored_name_only_control_files_are_not_compared(self):
        # P3-Z decision 6b: `run: setup` may unpack CLAUDE.md / AGENTS.md into a gitignored folder
        self.lay.write("node_modules/x/AGENTS.md", "package rules\n")
        self.lay.write("ignored/deep/CLAUDE.md", "x\n")
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertTrue(cf["ok"], cf)
        # ... but a `.claude` folder under a gitignored path still counts, and so does a
        # control-named file in a folder git does not ignore
        self.lay.write("node_modules/x/.claude/settings.json", "{}\n")
        self.lay.write("newdir/AGENTS.md", "x\n")
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], ["newdir/AGENTS.md", "node_modules/x/.claude/settings.json"])

    def test_c8_reference_is_the_base_blob(self):
        # HEAD and worktree changed IDENTICALLY: a worktree-copy reference would see no change
        self.lay.write(".claude/guild/config.json", '{"format": 1, "gates": "off"}\n')
        self.lay.commit("tamper")
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], [".claude/guild/config.json"])
        # and a worktree copy restored to base while HEAD still differs → still a violation
        self.lay.write(".claude/guild/config.json", a_layout.BASE_FILES[".claude/guild/config.json"])
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], [".claude/guild/config.json"])

    def test_case_folded(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-control-case.json"))
        self.assertStop(out, dec, ST.CONTROL_FILE.value)
        self.assertEqual(len(fx["control_files"]["changed"]), 1)
        self.assertTrue(fx["control_files"]["changed"][0].lower().endswith(".claude/agents/evil.md"))

    def test_deleted_control_file_and_mode_change(self):
        os.unlink(os.path.join(self.lay.wt, "CLAUDE.md"))
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], ["CLAUDE.md"])
        self.lay.git("checkout", "--", "CLAUDE.md")
        os.chmod(os.path.join(self.lay.wt, "CLAUDE.md"), 0o755)
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], ["CLAUDE.md"])

    def test_symlinked_control_file(self):
        os.makedirs(os.path.join(self.lay.wt, "pkg"))
        os.symlink("../CLAUDE.md", os.path.join(self.lay.wt, "pkg", "AGENTS.md"))
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], ["pkg/AGENTS.md"])

    def test_symlink_named_like_the_control_folder(self):
        target = os.path.join(self.lay.tmp, "agents-elsewhere")
        os.makedirs(target)
        os.makedirs(os.path.join(self.lay.wt, "pkg"))
        os.symlink(target, os.path.join(self.lay.wt, "pkg", ".claude"))
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], ["pkg/.claude"])
        self.lay.git("add", "pkg/.claude")
        self.lay.commit("link")
        os.unlink(os.path.join(self.lay.wt, "pkg", ".claude"))
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], ["pkg/.claude"])                   # still in HEAD

    def test_staged_only(self):
        self.lay.write("CLAUDE.md", "# staged\n")
        self.lay.git("add", "CLAUDE.md")
        self.lay.write("CLAUDE.md", a_layout.BASE_FILES["CLAUDE.md"])
        cf = R.check_control_files(self.ctx, self.proc_commit, 42, gitops.head(self.ctx))
        self.assertEqual(cf["changed"], ["CLAUDE.md"])

    def test_control_beats_everything(self):
        # a control-file change also in a session that hit its budget → still the security stop
        scn = self.lay.scenario("c-budget.json", {
            "format": 1, "stream": fakes.scn("../f2/r4.jsonl"), "init_from_argv": True,
            "result": {"subtype": "error_max_budget_usd", "is_error": True}, "exit_code": 1,
            "actions": [{"op": "write", "path": "CLAUDE.md", "content": "x\n"}]})
        out, fx, dec = self.attempt("implement", scn)
        self.assertStop(out, dec, ST.CONTROL_FILE.value)


class O(Flow):
    """O — output ownership and judge writes."""

    def test_o1_foreign_output(self):
        self.analyze_done()
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-foreign-output.json"))
        self.assertCheckFailed(out, dec, CF.FOREIGN_OUTPUT.value)
        self.assertEqual(fx["ownership"]["foreign"], [{"path": "docs/specs/42/analysis.md", "owner_step": "analyze"}])
        self.assertEqual(dec.target, "implement")                  # the step's on_fail

    def test_o1_later_owner(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-foreign-later.json"))
        self.assertCheckFailed(out, dec, CF.FOREIGN_OUTPUT.value)
        self.assertEqual(fx["ownership"]["foreign"], [{"path": "docs/specs/42/qa-notes.md", "owner_step": "qa"}])

    def test_o1_case_folded(self):
        self.analyze_done()
        # a new tracked path that differs from an owned one only in case is still owned
        self.lay.git("rm", "-q", "--cached", "docs/specs/42/analysis.md")
        os.rename(os.path.join(self.lay.wt, "docs/specs/42/analysis.md"),
                  os.path.join(self.lay.wt, "docs/specs/42/x.tmp"))
        os.rename(os.path.join(self.lay.wt, "docs/specs/42/x.tmp"),
                  os.path.join(self.lay.wt, "docs/specs/42/ANALYSIS.md"))
        self.lay.git("add", "docs/specs/42/ANALYSIS.md")
        self.lay.commit("case rename")
        own = R.check_ownership(self.ctx, self.lay.procedure, self.state, "implement", self.owner)
        self.assertFalse(own["ok"])
        self.assertIn({"path": "docs/specs/42/ANALYSIS.md", "owner_step": "analyze"}, own["foreign"])

    def test_o2_restored_passes(self):
        self.analyze_done()
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-foreign-revert.json"))
        self.assertEqual(out.status, "done", out)
        self.assertTrue(fx["ownership"]["ok"])

    def test_o3_judge_writes_outside(self):
        out, fx, dec = self.attempt("qa", fakes.scn("a-qa-writes-outside.json"))
        self.assertStop(out, dec, ST.JUDGE_WROTE_OUTSIDE.value)
        self.assertEqual(fx["judge_writes_outside"], ["src/a.py"])
        self.assertFalse(gitops.tree_state(self.ctx)["clean"])           # not reverted, not committed

    def test_o3_earlier_developer_work_is_not_counted(self):
        self.attempt("implement", fakes.scn("a-developer-ok.json"))
        out, fx, dec = self.attempt("qa", fakes.scn("a-qa-ok.json"))
        self.assertEqual(out.status, "done", out)
        self.assertIn("src/a.py", facts.changed_paths(fx))               # cumulative facts …
        self.assertEqual(fx["judge_writes_outside"], [])                  # … but not this attempt's writes

    def test_o3_case_differs_is_outside(self):
        got = R.judge_writes_outside(self.lay.procedure, "design", ["docs/specs/42/Design.md"])
        self.assertEqual(got, ["docs/specs/42/Design.md"])

    def test_o4_symlink_output(self):
        out, fx, dec = self.attempt("design", fakes.scn("a-design-output-symlink.json"))
        self.assertEqual((out.status, out.code, out.detail), ("failed", "output-format", OF.NON_REGULAR_OUTPUT.value))
        self.assertEqual(dec.action, "retry-same")
        with self.assertRaises(gitops.UnsafePath):
            R.commit_judge_outputs(self.ctx, self.lay.procedure, "design", 42, fx)

    def test_o5_dirty_tree(self):
        out, fx, dec = self.attempt("implement", fakes.scn("a-developer-dirty.json"))
        self.assertCheckFailed(out, dec, CF.DIRTY_TREE.value)
        self.assertEqual(fx["end_tree"]["dirty_files"], ["src/b.py"])

    def test_o6_run_dirty_tree(self):
        statemachine.mark_running(self.state, "test", 1, gitops.head(self.ctx))
        st = facts.start_facts(self.ctx, "test", 1, 42, "run")
        self.lay.write("coverage/out.txt", "x\n")
        run = {"name": "test", "exit_code": 0, "timed_out": False, "log_file": "run.log"}
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, "test", run=run)
        R.add_boundary_facts(self.ctx, self.lay.procedure, self.state, "test", fx, self.proc_commit)
        out = R.judge_run(self.lay.procedure.step("test"), fx)
        self.assertEqual((out.code, out.detail), ("check-failed", CF.RUN_DIRTY_TREE.value))

    def test_missing_output(self):
        out, fx, dec = self.attempt("design", fakes.scn("a-design-no-output.json"))
        self.assertEqual((out.code, out.detail), ("output-format", OF.MISSING_OUTPUT.value))

    def test_blocked(self):
        out, fx, dec = self.attempt("design", fakes.scn("a-design-blocked.json"))
        self.assertEqual(out.status, "blocked")
        self.assertEqual(dec.stop, ("needs_human", ST.BLOCKED.value))


class S(Flow):
    """S — session limits, init, facts (the U6–U8 part of the S set)."""

    def test_s3_session_limit(self):
        out, fx, dec = self.attempt("design", fakes.scn("budget-reached.json"))
        self.assertEqual((out.status, out.code), ("failed", "session-limit"))
        self.assertEqual(dec.stop, ("needs_human", ST.SESSION_LIMIT.value))
        self.assertEqual(fx["session"]["end"], "budget")

    def test_s6_other_init_lists_are_not_a_stop(self):
        """Was S6 init-mismatch. FC decision D: the init lists are not compared — the attempt is judged
        on its result like any other (this scenario wrote no design.md: a missing output)."""
        out, fx, dec = self.attempt("design", fakes.scn("init-lists-differ.json"))
        self.assertEqual((out.code, out.detail), ("output-format", OF.MISSING_OUTPUT.value))
        self.assertNotIn("init", fx["session"])
        self.assertNotIn("init-mismatch", ST.values())

    def test_an_earlier_engines_init_fact_is_not_read(self):
        fx = _facts(outputs=[{"path": "docs/specs/42/design.md", "exists": True, "regular": True, "blob": "x"}])
        fx["session"]["init"] = {"ok": False, "mismatches": ["plugins: …"]}
        out = R.judge_role(self.lay.procedure, "design", {}, a_layout.work_result(), fx)
        self.assertEqual(out.status, "done", out)

    def test_r5_no_structured_output_twice(self):
        out, fx, dec = self.attempt("design", fakes.scn("no-structured-output.json"))
        self.assertEqual((out.code, out.detail), ("output-format", OF.NO_STRUCTURED_OUTPUT.value))
        self.assertEqual(dec.action, "retry-same")
        out, fx, dec = self.attempt("design", fakes.scn("no-structured-output.json"))
        self.assertEqual(dec.stop, ("needs_human", ST.OUTPUT_FORMAT_TWICE.value))

    def test_no_output_is_infra(self):
        old = session.NO_OUTPUT_GRACE_S
        session.NO_OUTPUT_GRACE_S = -59           # floor = 60 s bash timeout − 59 = 1 s
        orig = session.session_limits
        session.session_limits = lambda inp, limits=None: orig(inp, {"no_output_s": 1})
        try:
            out, fx, dec = self.attempt("design", fakes.scn("no-output-hang.json"))
        finally:
            session.NO_OUTPUT_GRACE_S = old
            session.session_limits = orig
        self.assertEqual((out.code, out.detail), ("infra", "no-output"))
        self.assertEqual(dec.stop, ("needs_human", ST.INFRA_STOP.value))

    def test_quota_wait(self):
        out, fx, dec = self.attempt("design", fakes.scn("a-rate-limit-rejected.json"))
        self.assertEqual((out.code, out.detail, out.reset_at), ("infra", "quota", 1795407000))

    def test_s5_missing_boundary_fact_is_infra(self):
        fx = {"session": {"end": "completed"},
              "control_files": None, "ownership": {"ok": True, "foreign": []}, "judge_writes_outside": [],
              "outputs": []}
        out = R.judge_role(self.lay.procedure, "design", {}, a_layout.work_result(), fx)
        self.assertEqual((out.code, out.detail), ("infra", "fact-collection"))
        fx["control_files"] = {"ok": True, "changed": []}
        fx["judge_writes_outside"] = None
        out = R.judge_role(self.lay.procedure, "design", {}, a_layout.work_result(), fx)
        self.assertEqual((out.code, out.detail), ("infra", "fact-collection"))

    def test_s5_git_failure_in_a_boundary_check(self):
        from unittest import mock
        with mock.patch.object(gitops, "git", side_effect=gitops.GitError("boom")):
            with self.assertRaises(facts.FactMissing):
                R.check_control_files(self.ctx, self.proc_commit, 42, self.lay.base_sha)


def _facts(changed=(), outputs=(), clean=True):
    return {"session": {"end": "completed"},
            "control_files": {"ok": True, "changed": []}, "ownership": {"ok": True, "foreign": []},
            "judge_writes_outside": [], "outputs": list(outputs),
            "changed_files": [{"path": p, "change": "modified", "from": None, "where": "committed"} for p in changed],
            "end_tree": {"clean": clean, "dirty_files": []}}


class ReviewRules(unittest.TestCase):
    """R1–R4, R6–R8 on the judge function (pure)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.proc = a_layout.Layout(cls._tmp.name).procedure

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def judge(self, result, changed=("src/a.py",), rule_checks=()):
        brief = {"result_kind": "review", "checks": ["diff-review", "design-conformance"],
                 "rule_checks": list(rule_checks)}
        return R.judge_role(self.proc, "review", brief, result, _facts(changed))

    def test_pass(self):
        self.assertEqual(self.judge(a_layout.review_result()).status, "done")

    def test_r1_block(self):
        out = self.judge(a_layout.review_result(verdict="block", findings=[
            {"severity": "major", "file": "src/a.py", "line": 1, "text": "bug"}]))
        self.assertEqual((out.code, out.detail, out.back_to), ("check-failed", CF.VERDICT_BLOCK.value, "implement"))

    def test_r2_pass_with_blocker(self):
        out = self.judge(a_layout.review_result(findings=[{"severity": "blocker", "file": "x", "line": None,
                                                           "text": "t"}]))
        self.assertEqual(out.detail, OF.PASS_WITH_BLOCKER.value)

    def test_r3_empty_reviewed(self):
        self.assertEqual(self.judge(a_layout.review_result(reviewed=[])).detail, OF.EMPTY_REVIEWED.value)

    def test_r4_missing_check(self):
        r = a_layout.review_result()
        r["checks"] = r["checks"][:1]
        out = self.judge(r)
        self.assertEqual(out.detail, OF.MISSING_CHECK.value)
        self.assertIn("design-conformance", out.errors[0])

    def test_r6_blocked_ignores_verdict(self):
        r = a_layout.review_result(status="blocked", verdict="block",
                                   blocked_by={"kind": "missing-input", "note": "x"})
        self.assertEqual(self.judge(r).status, "blocked")

    def test_r7_reviewed_not_covering(self):
        out = self.judge(a_layout.review_result(), changed=("src/a.py", "src/b.py", "docs/specs/42/design.md"))
        self.assertEqual(out.detail, OF.REVIEWED_NOT_COVERING.value)
        self.assertEqual(out.errors, ["changed file 'src/b.py' is not in `reviewed`"])

    def test_r7_required_check_fail_and_na(self):
        r = a_layout.review_result()
        r["checks"][1]["result"] = "fail"
        self.assertEqual(self.judge(r).detail, CF.REQUIRED_CHECK_FAIL.value)
        r["checks"][1]["result"] = "n/a"
        self.assertEqual(self.judge(r).status, "done")                         # template check: n/a allowed
        self.assertEqual(self.judge(r, rule_checks=["design-conformance"]).detail, OF.REQUIRED_CHECK_NA.value)

    def test_r8_block_target_owner(self):
        out = self.judge(a_layout.review_result(verdict="block", findings=[
            {"severity": "blocker", "file": "docs/specs/42/design.md", "line": None, "text": "wrong"},
            {"severity": "minor", "file": "docs/specs/42/analysis.md", "line": None, "text": "nit"}]))
        self.assertEqual(out.back_to, "design")
        self.assertEqual(R.block_target(self.proc, "review", [
            {"severity": "blocker", "file": "./docs/specs/42/analysis.md"},
            {"severity": "blocker", "file": "docs/specs/42/design.md"}]), "analyze")          # earliest owner
        self.assertEqual(R.block_target(self.proc, "review", [
            {"severity": "blocker", "file": "docs/specs/42/qa-x.md"}]), "implement")         # later owner ignored
        self.assertEqual(R.block_target(self.proc, "review", [{"severity": "blocker", "file": "/etc/x"}]),
                         "implement")

    def test_result_schema(self):
        out = self.judge({"status": "done"})
        self.assertEqual(out.detail, OF.RESULT_SCHEMA.value)
        self.assertTrue(out.errors)
        self.assertEqual(R.validate_result(a_layout.work_result(status="blocked"), "work"),
                         ["blocked_by: required (not null) when status is blocked"])

    def test_request_with_a_command(self):
        r = a_layout.review_result(requests=[{"op": "add", "step": "rm -rf /", "trigger": "other", "note": ""}])
        self.assertEqual(self.judge(r).detail, OF.UNKNOWN_REQUEST_STEP.value)


class RunJudge(unittest.TestCase):
    def fx(self, **run):
        base = {"name": "test", "exit_code": 0, "timed_out": False, "log_file": "run.log"}
        base.update(run)
        f = _facts()
        f["run"] = base
        return f

    def test_table(self):
        self.assertEqual(R.judge_run("test", self.fx()).status, "done")
        self.assertEqual(R.judge_run("test", self.fx(exit_code=1)).detail, CF.RUN_NONZERO.value)
        self.assertEqual(R.judge_run("test", self.fx(exit_code=None, timed_out=True)).detail, CF.RUN_TIMEOUT.value)
        self.assertEqual(R.judge_run("test", self.fx(exit_code=None)).detail, "op-failed")
        # I8: a flaky pass on rerun stays red; a red base stops
        f = self.fx(exit_code=1, rerun={"exit_code": 0, "timed_out": False, "log_file": "r"})
        self.assertEqual(R.judge_run("test", f).code, "check-failed")
        f = self.fx(exit_code=1, base_run={"exit_code": 1, "timed_out": False, "log_file": "b"})
        self.assertEqual(R.judge_run("test", f).stop, ST.BASE_RED.value)
        f = self.fx()
        f["control_files"] = None
        self.assertEqual(R.judge_run("test", f).detail, "fact-collection")

    def test_runner_outcome_is_the_verdict(self):
        """P3-Z decision 1: the run verdict is runner.StepRun.outcome (base-red first); the
        security boundary still comes first."""
        f = self.fx(exit_code=1)
        oc = {"status": "needs_human", "code": None, "detail": None, "stop": ST.BASE_RED.value}
        self.assertEqual(R.judge_run("test", f, oc).stop, ST.BASE_RED.value)
        oc = {"status": "failed", "code": "check-failed", "detail": CF.RUN_DIRTY_TREE.value, "stop": None}
        f["end_tree"] = {"clean": False, "dirty_files": ["x.txt"]}
        out = R.judge_run("test", f, oc)
        self.assertEqual((out.code, out.detail, list(out.errors)), ("check-failed", CF.RUN_DIRTY_TREE.value,
                                                                    ["left behind: x.txt"]))
        self.assertEqual(R.judge_run("test", self.fx(), {"status": "done", "code": None, "detail": None,
                                                         "stop": None}).status, "done")
        f = self.fx()
        f["control_files"] = {"ok": False, "changed": ["CLAUDE.md"]}
        self.assertEqual(R.judge_run("test", f, {"status": "done", "code": None, "detail": None, "stop": None}).stop,
                         ST.CONTROL_FILE.value)
        self.assertEqual(R.judge_run("test", self.fx(), {"bogus": 1}).detail, "fact-collection")

    def test_fallback_precedence_matches_the_runner(self):
        f = self.fx(exit_code=1, base_run={"exit_code": 1, "timed_out": False, "log_file": "b"})
        f["end_tree"] = {"clean": False, "dirty_files": ["x"]}
        self.assertEqual(R.judge_run("test", f).stop, ST.BASE_RED.value)            # base red before dirty
        f = self.fx(exit_code=None, timed_out=True)
        f["end_tree"] = {"clean": False, "dirty_files": ["x"]}
        self.assertEqual(R.judge_run("test", f).detail, CF.RUN_DIRTY_TREE.value)    # dirty before timeout


CATALOG_IDS = ("product-review", "ux-design", "threat-model", "data-design", "i18n-plan", "ux-review",
               "security-review", "data-review", "i18n-review", "performance-review", "infra-review")


def s3_work(**over):
    r = a_layout.work_result(irreversible=[], golden_reasons=[])
    r.update(over)
    return r


class ResultSchemas(unittest.TestCase):
    """Stage 3 E16 / review-q0 D9: the filled result schemas and the surrogate refusal."""

    def test_stage_picks_the_schema(self):
        for kind in codes.ResultKind.values():
            self.assertEqual(R.result_schema(kind, 1), f"result-{kind}")
            self.assertEqual(R.result_schema(kind, 2, CATALOG_IDS), f"result-{kind}")
            s3 = R.result_schema(kind, 3, CATALOG_IDS)
            self.assertEqual(schema.schema_tokens(s3), set())
            self.assertEqual(s3["properties"]["requests"]["items"]["properties"]["step"]["enum"], list(CATALOG_IDS))
        self.assertNotIn("requests", R.result_schema("work", 3, ())["properties"])
        with self.assertRaises(ValueError):
            R.result_schema("leader", 3, CATALOG_IDS)

    def test_tc6_a_request_outside_the_catalog_is_a_schema_error(self):
        req = {"op": "add", "step": "ux-review", "trigger": "ui-change", "note": ""}
        ok = s3_work(requests=[req])
        self.assertEqual(R.validate_result(ok, "work", 3, CATALOG_IDS), [])
        for step in ("lint", "fix-discovery", "npm run lint"):
            self.assertTrue(R.validate_result(s3_work(requests=[dict(req, step=step)]), "work", 3, CATALOG_IDS), step)
        # stages 1-2 keep the old schema: the new fields are unknown there, the name is a pattern only
        self.assertTrue(R.validate_result(ok, "work"))
        self.assertEqual(R.validate_result(a_layout.work_result(requests=[dict(req, step="lint")]), "work"), [])
        self.assertTrue(R.validate_result(a_layout.work_result(), "work", 3, CATALOG_IDS))

    def test_no_catalog_step_at_all(self):
        r = s3_work()
        del r["requests"]
        self.assertEqual(R.validate_result(r, "work", 3, ()), [])

    def test_blocked_by_rules_hold_at_stage_3(self):
        self.assertTrue(R.validate_result(s3_work(status="blocked"), "work", 3, CATALOG_IDS))

    def test_a_lone_surrogate_is_refused_at_every_stage(self):
        bad = "x\ud83d"
        want = ["$/note: a lone surrogate (not valid Unicode text)"]
        self.assertEqual(R.validate_result(s3_work(note=bad), "work", 3, CATALOG_IDS), want)
        self.assertEqual(R.validate_result(a_layout.work_result(note=bad), "work"), want)
        for e in R.validate_result(s3_work(**{bad: 1}), "work", 3, CATALOG_IDS):
            e.encode("utf-8")          # the messages themselves can be written anywhere


class Stage3Results(Flow):
    STAGE = 3
    CATALOG = CATALOG_IDS

    def test_surrogate_result_is_output_format_not_an_engine_error(self):
        """Q8 (3): recorded with ASCII escapes, judged output-format / result-schema, one retry."""
        out, fx, dec = self.attempt("implement", fakes.scn("t-result-surrogate.json"))
        self.assertEqual((out.status, out.code, out.detail), ("failed", "output-format", OF.RESULT_SCHEMA.value), out)
        self.assertEqual(dec.action, "retry-same")
        with open(self.lay.ep.attempt_file("implement", 1, "result.json"), "rb") as f:
            raw = f.read()
        self.assertIn(b"\\ud800", raw)
        self.assertEqual(store.loads_strict(raw.decode("utf-8"))["note"], "bad \ud800 text")

    def test_a_stage3_result_passes(self):
        out, fx, dec = self.attempt("implement", fakes.scn("t-fix-ok.json"))
        self.assertEqual(out.status, "done", (out, out.errors))


class Globs(unittest.TestCase):
    def test_fold_and_secret(self):
        self.assertFalse(globs.match("docs/*.md", "DOCS/x.md"))
        self.assertTrue(globs.match("docs/*.md", "DOCS/x.md", fold=True))
        self.assertTrue(globs.is_secret_path("app/.ENV.local", ["**/.env*"]))
        self.assertFalse(globs.is_secret_path("app/env", ["**/.env*"]))


if __name__ == "__main__":
    unittest.main()
