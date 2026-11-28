"""Stage 3 flow — irreversible changes and their levels (V9, session B2): TI1–TI4, TI6."""

import unittest

from gxengine import codes, driver, lifecycle
from tests import s3_world as S


def rule(category, *globs, level=None):
    r = {"kind": "irreversible", "category": category, "globs": list(globs), "note": "n"}
    if level:
        r["level"] = level
    return r


def code(c):
    return {"code": c, "where": "deploy.sh", "note": "ships it"}


def asked(state):
    return [(d["category"], d["code"] or d["path"]) for d in state["irreversible"]["approved"]]


class Notify(S.Stage3):
    cfg = S.config(path_rules=[S.TEST_CODE, S.SAFETY_NET, rule("hard-to-revert", "src/app.py"),
                               rule("human-executed", "db/*.sql", level="proceed"),
                               rule("human-executed", "db/b.sql")])

    def test_ti1_ti4_notify_goes_on_with_the_label_and_the_lowered_level(self):
        s = self.sess(implement=[{"write": {"src/app.py": "x = 2\n", "db/a.sql": "a\n", "db/b.sql": "b\n"},
                                  "commit": "feat: x"}])
        self.ok(self.run3(self.leader(), session=s))
        got = {d["path"]: (d["level"], d["default_level"], d["lowered"], d["source"], d["step"], d["attempt"])
               for d in self.state()["irreversible"]["detected"]}
        self.assertEqual(got, {
            "src/app.py": ("notify", "notify", False, "path-rule", "implement", 1),
            "db/a.sql": ("proceed", "notify", True, "path-rule", "implement", 1),
            "db/b.sql": ("notify", "notify", False, "path-rule", "implement", 1)})      # the strictest rule
        self.assertEqual(self.gh.names().count("add_label"), 1)
        self.assertEqual([c for c in self.gh.calls if c["fn"] == "add_label"][0]["name"], "guild:irreversible")
        self.assertEqual(len(self.log("irreversible-detected")), 3)
        # no comment beyond the summary, the assumptions and the completion
        posts = [c for c in self.w.gh_calls() if c["argv"][:3] == ["api", "-X", "POST"]
                 and c["argv"][3].endswith("/comments")]
        self.assertEqual(len(posts), 3)
        self.assertTrue(any("- irreversible: 3" in (c["stdin"] or "") for c in self.w.gh_calls()))

    def test_a_path_that_is_no_longer_changed_is_no_longer_detected(self):
        s = self.sess(implement=[{"write": {"db/a.sql": "a\n"}, "commit": "feat: x"},
                                 {"write": {"src/other.py": "y\n"}, "commit": "fix: y"}])
        res = S.FakeResults({"review": [lambda: S.W.check_failed(), S.W.done]})
        real = s.run_session

        def run_session(inp, *a, **kw):
            if inp.step == "implement" and inp.attempt == 2:
                self.w.wt_git("rm", "-q", "db/a.sql")
            return real(inp, *a, **kw)

        s.run_session = run_session
        self.ok(self.run3(self.leader(), session=s, results=res))
        self.assertEqual(self.state()["irreversible"]["detected"], [])


class HumanDecision(S.Stage3):
    cfg = S.config(path_rules=[S.TEST_CODE, S.SAFETY_NET, rule("external-side-effect", "deploy/*")])

    def impl(self, *names):
        return [{"write": {f"deploy/{n}": "x\n" for n in names[:i + 1]}, "commit": f"feat: {i}"}
                for i in range(len(names))]

    def test_ti2_ti6_approve_once_per_path_and_no_leader(self):
        res = S.FakeResults({"review": [lambda: S.W.check_failed(), S.W.done]})
        ld = self.leader()
        s = self.sess(implement=self.impl("a.yml", "b.yml"))
        self.assertEqual(self.run3(ld, session=s, results=res), driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"], st["stop"]["step"], st["stop"]["attempt"]),
                         ("needs_human", "irreversible-change", "implement", 1))
        self.assertEqual(st["stop"]["allowed_answers"], ["continue", "rerun"])
        self.assertIn("deploy/a.yml", st["stop"]["note"])
        self.assertEqual(S.steps_of(st)["implement"], "done")
        self.assertEqual(S.steps_of(st)["test"], "pending")                     # nothing ran after it
        self.assertEqual([c["situation"] for c in ld.calls], ["plan-gate"])
        # no other answer fits, and no leader answer can lift it
        for bad in ("approve", "escalate", "replan"):
            with self.assertRaises(lifecycle.AnswerRefused):
                lifecycle.validate_answer(st, bad, stage=3)
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.validate_answer(st, "continue", stage=3, who="leader", procedure=object())
        # approved → goes on; the review sends the developer back, who adds a second path → asked again
        self.assertEqual(self.run3(ld, answer={"answer": "continue"}), driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        self.assertEqual((st["stop"]["reason"], asked(st)),
                         ("irreversible-change", [("external-side-effect", "deploy/a.yml")]))
        self.assertIn("deploy/b.yml", st["stop"]["note"])
        self.assertNotIn("deploy/a.yml", st["stop"]["note"])
        self.ok(self.run3(ld, answer={"answer": "continue"}))
        st = self.state()
        self.assertEqual(asked(st), [("external-side-effect", "deploy/a.yml"), ("external-side-effect", "deploy/b.yml")])
        self.assertTrue(all(a["who"] == "human" for a in st["irreversible"]["approved"]))
        self.assertEqual(self.sstep("implement")["latest_attempt"], 2)          # continue reran nothing
        self.assertEqual({c["situation"] for c in ld.calls}, {"plan-gate", "done-gate"})

    def test_rerun_asks_again_only_while_the_change_is_there(self):
        s = self.sess(implement=[{"write": {"deploy/a.yml": "x\n"}, "commit": "feat: a"},
                                 {"write": {"src/app.py": "x = 2\n"}, "commit": "feat: without"}])
        real = s.run_session

        def run_session(inp, *a, **kw):
            if inp.step == "implement" and inp.attempt == 2:
                self.w.wt_git("rm", "-q", "deploy/a.yml")
            return real(inp, *a, **kw)

        s.run_session = run_session
        ld = self.leader()
        self.assertEqual(self.run3(ld, session=s), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.run3(ld, answer={"answer": "rerun", "step": "review"}), driver.EXIT_REFUSED)
        self.ok(self.run3(ld, answer={"answer": "rerun", "step": "implement", "note": "no deploy files"}))
        self.assertEqual(self.state()["irreversible"], {"detected": [], "approved": []})
        self.assertIn("no deploy files", self.in_file("implement", 2, "leader-decision.md"))


class Codes(S.Stage3):
    cfg = S.config(irreversible_levels={"hard-to-revert": "proceed"})

    def test_ti3_a_code_of_the_analysis_stops_before_the_plan_gate(self):
        ld = self.leader()
        s = self.sess(analyze=[{"write": {f"{S.SPECS}/analysis.md": S.analysis()}, "structured": S.result(
            irreversible=[code("deploy-or-release"), code("breaking-api")])}])
        self.assertEqual(self.run3(ld, session=s), driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("irreversible-change", "analyze"))
        self.assertEqual(ld.calls, [])
        self.assertEqual([(d["code"], d["level"], d["lowered"]) for d in st["irreversible"]["detected"]],
                         [("deploy-or-release", "human-decision", False), ("breaking-api", "proceed", True)])
        self.assertEqual(self.gh.names().count("add_label"), 0)            # `proceed` is a log line only
        self.ok(self.run3(ld, answer={"answer": "continue", "note": "known"}))
        self.assertEqual(asked(self.state()), [("external-side-effect", "deploy-or-release")])


class Pure(unittest.TestCase):
    def test_there_is_no_leader_seat(self):
        self.assertNotIn("irreversible-change", codes.leader_situations(3))
        self.assertNotIn("irreversible-change", codes.leader_answer_schemas(3))


if __name__ == "__main__":
    unittest.main()
