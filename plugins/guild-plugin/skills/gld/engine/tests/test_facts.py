"""U7 facts.json collection — real git in a temp repo, fake claude only."""

import os
import tempfile
import unittest
from unittest import mock

from gxengine import codes, facts, gitops, schema, session, store
from tests import a_layout
from tests.helpers import fakes


def fake_session(lay, end="completed", cost=0.5, model="claude-sonnet-5-5", exit_code=0,
                 structured=None, denials=None, warnings=()):
    return session.SessionResult(
        exit_code=exit_code, end=end,
        structured=structured, result_event={"type": "result"}, stream_file=os.path.join(lay.tmp, "s.jsonl"),
        stderr_file=os.path.join(lay.tmp, "e.log"), session_id="sid-1",
        cost={"cost_usd": cost, "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5, "num_turns": 3},
        denials=denials if denials is not None else [{"tool_name": "Bash", "tool_input": {"command": "x"},
                                                      "tool_use_id": "t1"}],
        duration_s=1.0, cli_version="2.1.323", model=model, warnings=list(warnings))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lay = a_layout.Layout(self._tmp.name)
        self.ctx = self.lay.ctx

    def tearDown(self):
        self._tmp.cleanup()

    def valid(self, fx):
        fx = dict(fx)
        errs = schema.errors(fx, schema.load_schema("facts"))
        self.assertEqual(errs, [])
        store.write_facts(self.lay.ep, fx["step"], fx["attempt"], fx)       # the store accepts it too


class StartFinish(Base):
    def test_role_facts_complete_and_valid(self):
        st = facts.start_facts(self.ctx, "implement", 1, 42, "role")
        st["requested"] = {"model": "sonnet", "effort": "high"}
        self.assertEqual(st["start_head"], self.lay.base_sha)
        self.assertEqual(st["merge_base"], self.lay.base_sha)
        self.assertTrue(st["start_tree"]["clean"])
        self.lay.write("src/a.py", "x = 2\n")
        self.lay.git("mv", "README.md", "README2.md")
        self.lay.commit("rename and edit")
        self.lay.write("src/new.py", "n\n")          # untracked
        self.lay.write("ignored/x.txt", "i\n")       # gitignored: not a changed file
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, "implement", session=fake_session(self.lay))
        self.assertEqual(fx["exit_code"], 0)
        self.assertEqual(fx["start_head"], self.lay.base_sha)
        self.assertNotEqual(fx["end_head"], self.lay.base_sha)
        self.assertFalse(fx["end_tree"]["clean"])
        self.assertEqual(facts.changed_paths(fx), ["README.md", "README2.md", "src/a.py", "src/new.py"])
        where = {c["path"]: c["where"] for c in fx["changed_files"]}
        self.assertEqual(where["src/new.py"], "untracked")
        self.assertEqual(len(fx["commits"]), 1)
        s = fx["session"]
        self.assertNotIn("init", s, "no system/init comparison (FC decision D)")
        self.assertEqual(s["effort"], "high")                 # tied to the init model (open question 8)
        self.assertEqual(s["cost_usd"], 0.5)
        self.assertEqual(s["permission_denials"], [{"tool_name": "Bash", "tool_input": {"command": "x"}}])
        self.assertEqual(fx["warnings"], [])
        self.assertIsNone(fx["control_files"])           # results.py fills the boundary facts
        self.valid(fx)

    def test_an_earlier_engines_session_init_still_reads(self):
        """FC decision D removed `session.init`; an attempt an earlier engine wrote keeps it — still valid."""
        st = facts.start_facts(self.ctx, "implement", 1, 42, "role")
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, "implement", session=fake_session(self.lay))
        fx["session"]["init"] = {"ok": True, "mismatches": []}
        self.valid(fx)
        self.assertEqual(store.read_facts(self.lay.ep, "implement", 1)["session"]["init"]["ok"], True)

    def test_run_facts(self):
        st = facts.start_facts(self.ctx, "test", 1, 42, "run")
        run = {"name": "test", "exit_code": 0, "timed_out": False, "log_file": "run.log"}
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, "test", run=run)
        self.assertEqual(fx["exit_code"], 0)
        self.assertIsNone(fx["session"])
        self.valid(fx)

    def test_missing_session_or_run_is_fact_missing(self):
        st = facts.start_facts(self.ctx, "design", 1, 42, "role")
        with self.assertRaises(facts.FactMissing):
            facts.finish_facts(self.ctx, st, self.lay.procedure, "design")
        st = facts.start_facts(self.ctx, "test", 1, 42, "run")
        with self.assertRaises(facts.FactMissing):
            facts.finish_facts(self.ctx, st, self.lay.procedure, "test", run={})


class S5(Base):
    """S5: a judgment fact that cannot be collected → FactMissing (infra stop); a measurement
    fact that cannot → a warning only."""

    def test_git_failure_is_fact_missing(self):
        st = facts.start_facts(self.ctx, "implement", 1, 42, "role")
        with mock.patch.object(gitops, "changed_files", side_effect=gitops.GitError("boom")):
            with self.assertRaises(facts.FactMissing) as cm:
                facts.finish_facts(self.ctx, st, self.lay.procedure, "implement", session=fake_session(self.lay))
        self.assertEqual(cm.exception.fact, "changed_files")

    def test_head_failure_at_start(self):
        with mock.patch.object(gitops, "head", side_effect=gitops.GitError("no HEAD")):
            with self.assertRaises(facts.FactMissing) as cm:
                facts.start_facts(self.ctx, "implement", 1, 42, "role")
        self.assertEqual(cm.exception.fact, "start_head")

    def test_tampered_worktree_is_not_infra(self):
        with open(os.path.join(self.lay.wt, ".git"), "w", encoding="utf-8") as f:
            f.write(f"gitdir: {self.lay.repo.path}/.git\n")
        with self.assertRaises(gitops.UnsafePath):
            facts.start_facts(self.ctx, "implement", 1, 42, "role")

    def test_bad_end_is_fact_missing(self):
        st = facts.start_facts(self.ctx, "implement", 1, 42, "role")
        s = fake_session(self.lay)
        s.end = None
        with self.assertRaises(facts.FactMissing) as cm:
            facts.finish_facts(self.ctx, st, self.lay.procedure, "implement", session=s)
        self.assertEqual(cm.exception.fact, "session.end")

    def test_measurement_failures_are_warnings(self):
        st = facts.start_facts(self.ctx, "implement", 1, 42, "role")
        st["requested"] = {"model": "opus", "effort": "high"}       # init says sonnet → effort unknown
        s = fake_session(self.lay, cost=None, warnings=["garbage line"])
        s.cost["num_turns"] = None
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, "implement", session=s)
        names = sorted(w["fact"] for w in fx["warnings"])
        self.assertEqual(names, ["session.cost_usd", "session.effort", "session.num_turns", "session.stream"])
        self.assertIsNone(fx["session"]["cost_usd"])
        self.assertIsNone(fx["session"]["effort"])
        self.assertEqual(facts.warning_count(fx), 4)
        self.valid(fx)

    def test_unspawned_session_has_no_measurement_warnings(self):
        st = facts.start_facts(self.ctx, "implement", 1, 42, "role")
        s = session.SessionResult(exit_code=None, end="error", stream_file="/x/stream.jsonl")
        fx = facts.finish_facts(self.ctx, st, self.lay.procedure, "implement", session=s)
        self.assertEqual(fx["session"]["end"], "error")
        self.assertEqual([w["fact"] for w in fx["warnings"]], ["session.effort"])
        self.valid(fx)


class Outputs(Base):
    def test_literal_and_glob(self):
        self.lay.write("docs/specs/42/design.md", "d\n")
        head = gitops.head(self.ctx)
        out = facts.output_facts(self.ctx, self.lay.procedure, "design", head)
        self.assertEqual(out, [{"path": "docs/specs/42/design.md", "exists": True, "regular": True, "blob": None}])
        out = facts.output_facts(self.ctx, self.lay.procedure, "qa", head)
        self.assertEqual(out, [{"path": "docs/specs/42/qa-*.md", "exists": False, "regular": False, "blob": None}])
        self.lay.write("docs/specs/42/qa-a.md", "a\n")
        self.lay.write("docs/specs/42/qa-b.md", "b\n")
        sha = self.lay.commit("qa", paths=["docs/specs/42/qa-a.md"])
        out = facts.output_facts(self.ctx, self.lay.procedure, "qa", sha)
        self.assertEqual([o["path"] for o in out], ["docs/specs/42/qa-a.md", "docs/specs/42/qa-b.md"])
        self.assertIsNotNone(out[0]["blob"])
        self.assertIsNone(out[1]["blob"])

    def test_symlink_and_linked_parent_are_not_regular(self):
        os.symlink("../../../README.md", os.path.join(self.lay.wt, "docs/specs/42/design.md"))
        out = facts.output_facts(self.ctx, self.lay.procedure, "design", gitops.head(self.ctx))
        self.assertEqual((out[0]["exists"], out[0]["regular"]), (True, False))
        os.unlink(os.path.join(self.lay.wt, "docs/specs/42/design.md"))
        os.rmdir(os.path.join(self.lay.wt, "docs/specs/42"))
        real = os.path.join(self.lay.tmp, "elsewhere")
        os.makedirs(real)
        with open(os.path.join(real, "design.md"), "w", encoding="utf-8") as f:
            f.write("x\n")
        os.symlink(real, os.path.join(self.lay.wt, "docs/specs/42"))
        out = facts.output_facts(self.ctx, self.lay.procedure, "design", gitops.head(self.ctx))
        self.assertEqual((out[0]["exists"], out[0]["regular"]), (True, False))

    def test_attempt_changes_vs_cumulative(self):
        self.lay.write("src/a.py", "x = 5\n")
        start = self.lay.commit("developer work")            # an earlier step's change
        self.lay.write("docs/specs/42/design.md", "d\n")
        tree = gitops.tree_state(self.ctx)
        self.assertEqual(facts.attempt_changes(self.ctx, start, start, tree), ["docs/specs/42/design.md"])
        self.lay.write("src/c.py", "c\n")
        end = self.lay.commit("more")
        got = facts.attempt_changes(self.ctx, start, end, gitops.tree_state(self.ctx))
        self.assertEqual(got, ["docs/specs/42/design.md", "src/c.py"])


class Reentry(Base):
    def test_forward_and_dirty(self):
        h0 = gitops.head(self.ctx)
        self.lay.write("src/a.py", "x = 2\n")
        self.lay.commit("forward")
        self.lay.write("src/d.py", "d\n")
        r = facts.reentry_facts(self.ctx, h0)
        self.assertEqual(r, {"forward_only": True, "dirty_files": ["src/d.py"]})

    def test_rewritten_history(self):
        self.lay.write("src/a.py", "x = 2\n")
        h1 = self.lay.commit("one")
        self.lay.git("reset", "-q", "--hard", self.lay.base_sha)
        self.lay.write("src/a.py", "x = 3\n")
        self.lay.commit("other")
        self.assertFalse(facts.reentry_facts(self.ctx, h1)["forward_only"])


class SessionFacts(unittest.TestCase):
    def test_from_a_real_fake_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = a_layout.Layout(tmp)
            inp = lay.role_input("design", "tech-lead", outputs=["docs/specs/42/design.md"])
            r = session.run_session(inp, lay.attempt_dir("design", 1), lay.env(scenarios=["ok-judge.json"]),
                                    claude_bin=fakes.FAKE_CLAUDE)
            s = facts.session_facts(r)
            self.assertNotIn("init", s)
            self.assertEqual(s["end"], codes.SessionEnd.COMPLETED.value)
            self.assertTrue(s["structured_output"])
            self.assertEqual(s["model"], "sonnet")           # the fake sets the init model from --model
            self.assertIsInstance(s["cache_read_input_tokens"], int)
            self.assertEqual(s["permission_denials"][0]["tool_name"], "Bash")
            self.assertNotIn("tool_use_id", s["permission_denials"][0])


if __name__ == "__main__":
    unittest.main()
