"""E9-2 (stage-4 scope §2.10 H21, VB5): base verification files a human allows an Issue to modify — TT1–TT4.

Git facts on a temporary repository; no process of the repository, no LLM, no network.
"""

import copy
import os
import unittest

from gxengine import cli, codes, gitops, procedure, repoconfig, runner, schema, testchange
from tests import test_runner_stage3 as S3

NOW = "2026-11-25T01:02:03Z"
NOTE = "the signature of fetch() changed (human: JK)"
TEST = "test/a_test.sh"
R = testchange.Refused


class Args(unittest.TestCase):
    def test_a_plain_request(self):
        self.assertIsNone(testchange.args_problem("rerun", "transform", [TEST, "goldens/b.png"], NOTE))

    def test_tt3_anything_else_is_refused_before_detaching(self):
        for answer, step, paths, note in (
                ("escalate", "transform", [TEST], NOTE), ("continue", "transform", [TEST], NOTE), (None, "transform", [TEST], NOTE),
                ("rerun", None, [TEST], NOTE), ("rerun", "", [TEST], NOTE), ("rerun", "transform", [TEST], ""),
                ("rerun", "transform", [TEST], "  \n"), ("rerun", "transform", [], NOTE),
                ("rerun", "transform", ["test/*.sh"], NOTE), ("rerun", "transform", ["test/a?_test.sh"], NOTE),
                ("rerun", "transform", ["test/"], NOTE), ("rerun", "transform", ["/etc/hosts"], NOTE),
                ("rerun", "transform", ["../a"], NOTE), ("rerun", "transform", ["test//a"], NOTE),
                ("rerun", "transform", ["./test/a"], NOTE), ("rerun", "transform", [""], NOTE),
                ("rerun", "transform", ["a\\b"], NOTE), ("rerun", "transform", ["a\nb"], NOTE),
                ("rerun", "transform", [TEST, TEST], NOTE)):
            with self.subTest(answer=answer, step=step, paths=paths, note=note):
                self.assertTrue(testchange.args_problem(answer, step, paths, note))

    def test_tt4_a_leader_has_no_field_for_it(self):
        for name in codes.leader_answer_schemas(4).values():
            def keys(x):
                if isinstance(x, dict):
                    for k, v in x.items():
                        yield k
                        yield from keys(v)
                elif isinstance(x, list):
                    for v in x:
                        yield from keys(v)
            self.assertFalse([k for k in keys(schema.load_schema(name)) if "allow" in k or "test_change" in k], name)


class Apply(S3.Base):
    BASE_FILES = {TEST: "true\n", "goldens/b.txt": "b\n", "src/a.txt": "bug\n", "test/old_net_test.sh": "true\n"}

    def setUp(self):
        super().setUp()
        self.cfg = self.config()
        self.state = {"format": 1, "stop": {"status": "needs_human", "reason": "blocked", "step": "fix", "attempt": 1,
                                             "at": NOW, "note": ""}}

    def apply(self, paths, note=NOTE, step="fix", state=None, owned=None, proc=None, config=None):
        return testchange.apply(self.state if state is None else state, paths, note, step=step,
                                procedure=proc or self.procedure, config=config or self.cfg, ctx=self.ctx,
                                owned=owned or {"reproduce": {}, "safety-net": {}}, now=NOW)

    def refused(self, paths, **kw):
        before = copy.deepcopy(self.state)
        with self.assertRaises(R):
            self.apply(paths, **kw)
        self.assertEqual(self.state, before, "TT3: the state is unchanged")

    def test_tt1_the_state_and_the_log(self):
        events = self.apply([TEST, "goldens/b.txt"])
        self.assertEqual([e for e, _ in events], ["test-change-allowed"])
        self.assertEqual((events[0][1]["who"], events[0][1]["data"]["paths"]), ("human", ["goldens/b.txt", TEST]))
        rows = self.state["allowed_test_changes"]
        self.assertEqual([r["path"] for r in rows], [TEST, "goldens/b.txt"])
        self.assertEqual({r["at"] for r in rows}, {NOW})
        self.assertNotIn(NOTE, str(rows), "the text is in leader-decision.md, the state has its hash")
        self.assertEqual(testchange.allowed(self.state), ["goldens/b.txt", TEST])
        sch = schema.load_schema("state")
        self.assertEqual(schema.errors(rows, dict(sch["properties"]["allowed_test_changes"], **{"$defs": sch["$defs"]})), [])

    def test_a_second_allowance_adds_and_keeps_the_first(self):
        self.apply([TEST])
        first = copy.deepcopy(self.state["allowed_test_changes"][0])
        self.apply([TEST, "goldens/b.txt"], note="again")
        self.assertEqual(self.state["allowed_test_changes"][0], first)
        self.assertEqual(testchange.allowed(self.state), ["goldens/b.txt", TEST])

    def test_both_stops_and_nothing_else(self):
        self.state["stop"]["reason"] = "on-fail-exceeded"
        self.apply([TEST])
        for over in ({"reason": "base-red"}, {"reason": "infra-stop"}, {"status": "needs_leader"}):
            with self.subTest(over=over):
                st = {"stop": dict(self.state["stop"], **over)}
                with self.assertRaises(R):
                    self.apply([TEST], state=st)
                self.assertNotIn("allowed_test_changes", st)
        with self.assertRaises(R):
            self.apply([TEST], state={})

    def test_tt3_files_that_cannot_be_allowed(self):
        os.symlink("a_test.sh", os.path.join(self.wt, "test", "link_test.sh"))
        self.put_files({"test/new_test.sh": "true\n"})
        for path, why in (("test/none_test.sh", "absent"), ("test/new_test.sh", "only on the branch"),
                          ("src/a.txt", "no verification rule"), ("test", "a folder"), ("test/*_test.sh", "a glob"),
                          ("test/link_test.sh", "not on the base")):
            with self.subTest(why=why):
                self.refused([path])
        self.refused([TEST, "src/a.txt"])        # one bad path refuses them all

    def test_a_link_of_the_base_is_no_regular_file(self):
        os.symlink("a_test.sh", os.path.join(self.repo.path, "test", "link_test.sh"))
        self.ctx.base_sha = self.repo.commit("link on the base")
        self.refused(["test/link_test.sh"])

    def test_tt3_a_safety_net_file_is_never_allowed(self):
        self.refused(["test/old_net_test.sh"], owned={"reproduce": {}, "safety-net": {"test/old_net_test.sh": "a" * 40}})
        # an ordinary test under the same glob that the safety-net step does not own is no safety net
        self.apply(["test/old_net_test.sh"])

    def test_only_a_work_step(self):
        for step in ("verification-frozen", "no-such-step", "repro-red"):
            with self.subTest(step=step):
                self.refused([TEST], step=step)

    def test_a_procedure_without_the_frozen_run(self):
        raw = self.procedure.to_json()
        raw["steps"] = [s for s in raw["steps"] if s["id"] != "verification-frozen"]
        self.refused([TEST], proc=procedure.Procedure(raw))

    def test_a_reason_is_needed_here_too(self):
        self.refused([TEST], note=" ")


class Frozen(S3.Base):
    """The run: only the CONTENT of an allowed file may change."""
    BASE_FILES = {TEST: "true\n", "test/b_test.sh": "true\n", "goldens/b.txt": "b\n"}

    def frozen(self, allowed=(), stage=4):
        self.n = getattr(self, "n", 0) + 1
        return self.run_s3("verification-frozen", attempt=self.n, stage=stage, allowed_test_changes=tuple(allowed))

    def violations(self, r):
        return [(v["change"], v["path"]) for v in r.run["paths_check"]["violations"]]

    def test_tt1_an_allowed_content_change_passes(self):
        self.put_files({TEST: "true # new signature\n"})
        self.assertFailed(self.frozen(), S3.CF.VERIFICATION_CHANGED)
        r = self.frozen([TEST])
        self.assertDone(r)
        self.assertIn("content changes a human allowed (E9-2):", self.log("verification-frozen", attempt=2))
        self.assertNotIn("queue_wait_s", r.run, "git facts never wait")

    def test_tt2_another_file_is_still_a_violation(self):
        self.put_files({TEST: "x\n", "test/b_test.sh": "x\n"})
        r = self.frozen([TEST])
        self.assertFailed(r, S3.CF.VERIFICATION_CHANGED)
        self.assertEqual(self.violations(r), [("modified", "test/b_test.sh")])

    def test_tt2_deleted_renamed_retyped_remade(self):
        self.put_files({TEST: None})
        self.assertEqual(self.violations(self.frozen([TEST])), [("deleted", TEST)])
        self.repo.git("reset", "-q", "--hard", self.base, cwd=self.wt)
        self.repo.git("mv", TEST, "src_a_test.sh", cwd=self.wt)
        self.repo.commit("move", cwd=self.wt)
        self.assertEqual(self.violations(self.frozen([TEST, "src_a_test.sh"])), [("renamed", "src_a_test.sh")])
        self.repo.git("reset", "-q", "--hard", self.base, cwd=self.wt)
        os.unlink(os.path.join(self.wt, TEST))
        os.symlink("b_test.sh", os.path.join(self.wt, TEST))
        self.repo.commit("link", cwd=self.wt)
        self.assertEqual(self.violations(self.frozen([TEST])), [("type-changed", TEST)])
        self.repo.git("reset", "-q", "--hard", self.base, cwd=self.wt)
        os.chmod(os.path.join(self.wt, TEST), 0o755)
        self.repo.commit("mode", cwd=self.wt)
        self.assertEqual(self.violations(self.frozen([TEST])), [("modified", TEST)], "a mode is not the content")

    def test_the_list_changes_nothing_below_it(self):
        self.put_files({"test/new_test.sh": "true\n"})
        self.assertDone(self.frozen([TEST]))
        self.assertEqual(runner.frozen_violations(self.ctx, self.config(), gitops.head(self.ctx), allowed=["test/none"]), [])


class Config(unittest.TestCase):
    def test_a_repository_without_rules_has_nothing_to_allow(self):
        raw = copy.deepcopy(S3.CONFIG)
        raw["path_rules"] = [r for r in raw["path_rules"] if r["kind"] != "verification"]
        self.assertEqual(repoconfig.RepoConfig(raw).matches("verification", TEST), [])

    def test_cli_and_engine_agree(self):
        """The same function decides before detaching (cli._stage4_problem) and under the lock."""
        self.assertIs(cli.testchange, testchange)


if __name__ == "__main__":
    unittest.main()
