"""P3-Z end to end: one feature Issue from the start procedure through the whole plugin
feature template to the PR, with the REAL engine units (driver.Units() defaults), the
fake claude, the fake gh executable, a local bare remote, a temp git repository and the
REAL srt (scope §5.2, §6.2). Plus the stop/continue paths: needs_human → resume, engine
killed → resume, soft / absolute budget, the absolute attempt cap. No paid call.
"""

import json
import os
import signal
import subprocess
import time
import unittest

from gxengine import codes, defaults, driver, lifecycle, store
from tests import z_world as Z

SPECS = Z.SPECS
FULL = ["analyze", "ac-format", "plan", "test-cases", "ac-coverage", "design", "setup", "implement", "lint",
        "typecheck", "test", "build", "e2e", "review-design", "review-tests", "review-audit", "qa",
        "verify-gate", "pr"]


def steps_of(state):
    return {s["id"]: s["status"] for s in state["steps"]}


def events(log, name):
    return [l for l in log if l["event"] == name]


class Base(unittest.TestCase):
    cfg_extra = None

    def setUp(self):
        self.tmp = Z.new_tmp()
        self.addCleanup(Z.rmtree, self.tmp)
        self.w = Z.ZWorld(self.tmp, cfg=Z.config(self.cfg_extra))

    def out(self):
        return self.w.out.getvalue()

    def facts(self, step, attempt=1):
        return store.read_facts(self.w.paths(), step, attempt)


class FeatureIssueToPr(Base):
    cfg_extra = {"sandbox_exceptions": {"allow_local_binding": True}}

    def test_start_procedure_feature_template_and_pr(self):
        self.w.script(Z.ROLE_STEPS)
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assertEqual([s["id"] for s in st["steps"]], FULL)
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        self.assertIsNone(st["stop"])
        # every role session was the fake CLI, one per role step, in the worktree
        calls = self.w.claude_calls()
        self.assertEqual(len(calls), len(Z.ROLE_STEPS))
        for c in calls:
            self.assertEqual(c["cwd"], self.w.worktree)
            self.assertEqual(c["env"]["HOME"], os.path.realpath(self.w.home))   # paths.home (decision 3)
            self.assertNotIn("GH_TOKEN", c["env"])
        # the runs really ran under srt (run.log + srt.json per run step)
        for sid in ("ac-format", "ac-coverage", "setup", "lint", "test", "verify-gate"):
            d = self.w.paths().attempt_dir(sid, 1)
            self.assertTrue(os.path.isfile(os.path.join(d, "srt.json")), sid)
            self.assertEqual(self.facts(sid)["run"]["exit_code"], 0, sid)
        # P5 F2 (reverses decision 5): the exception reaches the runs AND the developer, never a judge
        with open(os.path.join(self.w.paths().attempt_dir("test", 1), "srt.json")) as f:
            self.assertTrue(json.load(f)["network"].get("allowLocalBinding"))
        with open(os.path.join(self.w.paths().attempt_dir("implement", 1), "settings.json")) as f:
            dev = json.load(f)
        self.assertIs(dev["sandbox"]["network"].get("allowLocalBinding"), True)
        with open(os.path.join(self.w.paths().attempt_dir("review-design", 1), "settings.json")) as f:
            self.assertNotIn("allowLocalBinding", json.dumps(json.load(f)))
        self.assertEqual(calls[3]["argv"][0], "-p")
        self.assertIn("Sandbox and toolchain", calls[3]["argv"][1])    # the work-frame line
        self.assertIn("### Repository commands", calls[3]["argv"][1])
        self.assertIn("python3 -I -B tests/test_app.py", calls[3]["argv"][1])
        self.assertNotIn("### Repository commands", calls[4]["argv"][1])
        # setup unpacked node_modules/x/AGENTS.md (gitignored) — allowed, not a control-file stop
        self.assertTrue(os.path.isfile(os.path.join(self.w.worktree, "node_modules", "x", "AGENTS.md")))
        self.assertTrue(self.facts("setup")["control_files"]["ok"])
        # boundary facts filled once per attempt by the driver (results), judge outputs committed
        fx = self.facts("analyze")
        self.assertTrue(fx["control_files"]["ok"] and fx["ownership"]["ok"])
        self.assertEqual(fx["judge_writes_outside"], [])
        self.assertTrue(fx["outputs"][0]["blob"])
        self.assertNotIn("init", self.facts("implement")["session"])          # FC decision D: no init check
        # V1: the test change added test-change-review to the tester review
        rt = next(s for s in st["steps"] if s["id"] == "review-tests")
        self.assertIn("test-change-review", rt.get("added_checks") or [])
        # pushed to the bare remote, one PR with the engine's closing line
        self.assertEqual(self.w.repo.remote_head("gld/42"), st["last_head"])
        self.assertEqual(st["github"]["pr_number"], 77)
        prs = [c for c in self.w.gh_calls() if c["argv"][:4] == ["api", "-X", "POST", "repos/acme/app/pulls"]]
        self.assertEqual(len(prs), 1)
        body = json.loads(prs[0]["stdin"])
        self.assertTrue(body["body"].rstrip().endswith("Closes #42"))
        self.assertIn("AC \uff031", body["body"])          # `#` neutralised to full width (S10)
        self.assertIn("`test`", body["body"])
        self.assertEqual(len(events(self.w.log(), "pr-created")), 1)
        # judge outputs and the procedure are on the branch
        tracked = self.w.wt_git("ls-files").split()
        for f in ("analysis.md", "test-cases.md", "skeleton.md", "manual-test-checklist.md", "procedure.yaml"):
            self.assertIn(f"{SPECS}/{f}", tracked)
        self.assertNotIn("node_modules/x/AGENTS.md", tracked)


class NeedsHumanThenResume(Base):
    def test_review_block_back_to_developer_then_blocked_stop_and_resume(self):
        # review-design blocks once (back to implement), the developer fixes, then review-audit
        # reports `blocked` → needs_human; `resume --answer rerun` continues to the PR.
        block = Z.role_scenario("review-design")
        block["structured_output"] = Z.review_result(
            ["design-conformance"], verdict="block",
            findings=[{"severity": "blocker", "file": "src/app.py", "line": None, "text": "x must stay an int"}])
        fix = Z.role_scenario("implement")
        fix["actions"] = [{"op": "write", "path": "src/app.py", "content": "x = 2  # int\n"},
                          {"op": "git", "args": ["commit", "-qam", "fix: keep x an int"]}]
        blocked = Z.role_scenario("review-audit")
        blocked["structured_output"] = dict(Z.work_result(), status="blocked",
                                            blocked_by={"kind": "ambiguous", "note": "needs a decision"})
        blocked["structured_output"].update(verdict="pass", reviewed=["src/app.py", "tests/test_app.py"],
                                            checks=[{"id": "diff-review", "result": "pass", "note": ""}],
                                            findings=[])
        for st in ["analyze", "test-cases", "design", "implement"]:
            self.w.add(Z.role_scenario(st))
        self.w.add(block)
        self.w.add(fix)
        for st in ["review-design", "review-tests"]:
            self.w.add(Z.role_scenario(st))
        self.w.add(blocked)
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("blocked", "review-audit"), st["stop"])
        imp = next(s for s in st["steps"] if s["id"] == "implement")
        self.assertEqual(imp["latest_attempt"], 2)
        self.assertTrue(events(self.w.log(), "back-to"))
        # the developer came back with its session (resume) and the failure summary
        calls = self.w.claude_calls()
        self.assertIn("--resume", calls[5]["argv"])
        with open(os.path.join(self.w.paths().in_dir("implement", 2), "failure-summary.md")) as f:
            summary = f.read()
        self.assertIn("verdict-block", summary)
        body = summary.split("````json\n", 1)[1].split("\n````", 1)[0]      # Q8: the role's own findings
        self.assertEqual(json.loads(body)["findings"], block["structured_output"]["findings"])
        posted = [c for c in self.w.gh_calls() if c["argv"][:3] == ["api", "-X", "POST"]
                  and "needs-human" in (c.get("stdin") or "")]
        self.assertTrue(posted)
        # resume with an answer: review-audit runs again (new attempt) and the Issue reaches its PR
        for s in ["review-audit", "qa"]:
            self.w.add(Z.role_scenario(s))
        rc = self.w.run(answer={"answer": "rerun", "step": None, "reason": None, "note": "go on"})
        self.assertEqual(rc, driver.EXIT_OK, self.out())
        st = self.w.state()
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        self.assertEqual(st["github"]["pr_number"], 77)
        self.assertEqual(len(events(self.w.log(), "answer")), 1)


class EngineKilledThenResume(Base):
    def test_sigkill_mid_session_then_cli_resume(self):
        # design hangs inside the fake CLI; the engine (the real CLI, foreground) is killed
        for st in ["analyze", "test-cases"]:
            self.w.add(Z.role_scenario(st))
        self.w.add(dict(Z.role_scenario("design"), hang_after=1, hang_s=8))
        cmd = self.w.engine_cli("dev", "--repo", Z.REPO, "--issue", str(Z.ISSUE), "--checkout",
                                self.w.repo.path, "--foreground", stage=1)   # a stage-1 world
        log = open(os.path.join(self.tmp, "engine-1.log"), "w")
        child = subprocess.Popen(cmd, cwd=self.w.repo.path, env=self.w.environ, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.time() + 240
            while time.time() < deadline:
                st = self.w.state() if os.path.exists(self.w.paths().state) else None
                if st and steps_of(st).get("design") == "running" and len(self.w.claude_calls()) >= 3:
                    break
                if child.poll() is not None:
                    break
                time.sleep(0.3)
            else:
                self.fail("the engine never reached the design session")
            if child.poll() is not None:
                with open(log.name) as f:
                    self.fail("the engine ended early: " + f.read())
            os.kill(child.pid, signal.SIGKILL)
            child.wait()
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            log.close()
        time.sleep(9)                  # the orphaned fake session ends on its own
        self.assertIsNone(lifecycle.lock_holder(self.w.paths()))
        self.assertTrue(lifecycle.pending_question(self.w.state())["crashed"])
        for st in Z.ROLE_STEPS[2:]:
            self.w.add(Z.role_scenario(st))
        p = subprocess.run(self.w.engine_cli("resume", "--repo", Z.REPO, "--issue", str(Z.ISSUE), "--foreground", stage=1),
                           cwd=self.w.repo.path, env=self.w.environ, capture_output=True, text=True, timeout=600)
        self.assertEqual(p.returncode, driver.EXIT_OK, p.stdout + p.stderr)
        st = self.w.state()
        self.assertTrue(all(v == "done" for v in steps_of(st).values()), steps_of(st))
        design = next(s for s in st["steps"] if s["id"] == "design")
        self.assertEqual(design["latest_attempt"], 2)
        self.assertTrue(os.path.isdir(self.w.paths().attempt_dir("design", 1)))     # evidence kept
        self.assertEqual(st["github"]["pr_number"], 77)


class Budget(Base):
    def test_soft_budget_stops_once_then_absolute_stops_for_good(self):
        costs = {"analyze": 7.9, "test-cases": 7.9, "design": 7.9, "implement": 14.9, "review-design": 7.9}
        self.w.script(Z.ROLE_STEPS[:5], costs)
        rc = self.w.run()
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("soft-budget", "review-tests"))
        self.assertGreaterEqual(st["totals"]["cost_usd"], defaults.SOFT_BUDGET_USD["attended"])
        self.assertEqual(steps_of(st)["review-tests"], "pending")
        # the human lets it go on once; review-tests pushes the total past the absolute budget
        self.w.add(Z.role_scenario("review-tests", cost=45.0))
        rc = self.w.run(answer={"answer": "rerun", "step": None, "reason": None, "note": ""})
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("absolute-limit", "review-audit"))
        self.assertGreaterEqual(st["totals"]["cost_usd"], defaults.ABSOLUTE_BUDGET_USD["attended"])
        # the absolute limit takes no rerun (escalate only)
        rc = self.w.run(answer={"answer": "rerun", "step": None, "reason": None, "note": ""})
        self.assertEqual(rc, driver.EXIT_REFUSED)
        self.assertEqual(len(self.w.claude_calls()), 6)          # nothing more was spent

    def test_absolute_attempt_cap_is_steps_times_four(self):
        self.w.script(Z.ROLE_STEPS[:1])
        self.w.add(dict(Z.role_scenario("test-cases"), structured_output=None))   # output-format → stop
        self.assertEqual(self.w.run(), driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        cap = defaults.total_attempts_max(len(st["steps"]))
        self.assertEqual(cap, len(FULL) * 4)
        st["totals"]["attempts"] = cap
        store.save_state(self.w.paths(), st)
        before = len(self.w.claude_calls())
        rc = self.w.run(answer={"answer": "rerun", "step": None, "reason": None, "note": ""})
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.out())
        st = self.w.state()
        self.assertEqual(st["stop"]["reason"], "absolute-limit")
        self.assertEqual(len(self.w.claude_calls()), before)     # no session after the cap


if __name__ == "__main__":
    unittest.main()
