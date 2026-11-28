"""Readiness E4 (#1910): a bug Issue keeps its red reproduction — no paid call, no real gh.

The fixtures are #1910 cut down (validation-archive/app_a-1910/runs/s4-final): an Issue labelled `type:bug`,
written at T0; a later commit (the #1905 shape) fixed the sign-out snackbar in the two files the Issue names;
the leader steered analyze from `bug` to `refactor` / `safety_net: only` and planned `safety-net` (VW2).

  rule 1  the engine does not take that plan (leader narrowing + engine-side refusal) → a human, both modes;
  rule 2  repro-red not red after every reproduce retry → not-reproduced for a human, with the facts
          (reproduction test, its runs, commits since T0 on the related files), no leader call;
  rule 3  analyze gets read-only git facts (in:git-history.md); its tools stay Read / Write (no Bash, no Edit,
          no network).
"""

import json
import os
import subprocess
import tempfile
import unittest

from gxengine import codes, defaults, driver, gitops, history, instructions, leader as leadermod, lifecycle
from gxengine import procedure as procmod, render, store
from tests import c_world as W
from tests import s3_world as S
from tests.helpers.gitrepo import GitRepo, run_git

SR = codes.StopReason
LA = W.leader_answer

SECTION = "lib/features/setting_screen/widgets/setting_sync_data_section.dart"
CONTROLLER = "lib/controller/sync_data_controller.dart"
HELPER = "test/helpers/fake_controller.dart"
REPRO = "test/features/setting_screen/sign_out_failure_test.dart"
T0 = "2030-01-02T00:00:00Z"            # the Issue was written (the World's own first commit is older)

ISSUE_BODY = (f"## 무엇이 남았나\n설정 화면 `_signOut`(`{SECTION}`)의 실패 경로는 `e.toString().tr` 를 그대로 보여 줍니다.\n"
              f"`{CONTROLLER}` 의 `manualSignOutFailureBodyKey` 를 써야 합니다.\n")
FILES = {
    "pubspec.yaml": "name: app_a\n",
    SECTION: "void _signOut() {\n  show(e.toString().tr);\n}\n",
    CONTROLLER: "String manualSignOutFailureBodyKey(String raw) => raw;\n",
    HELPER: "class FakeController {}\n",
    "README.md": "app\n",
}
REPRO_TEXT = ("import 'package:app_a/features/setting_screen/widgets/setting_sync_data_section.dart';\n"
              "import 'package:flutter_test/flutter_test.dart';\n"
              "import '../../helpers/fake_controller.dart';\n\n"
              "void main() {\n  group('sign out', () {\n    testWidgets('no raw exception text', (t) async {});\n"
              "    test('generic body', () {});\n  });\n}\n")


def dated_commit(repo, message, files, when):
    """Commit `files` in the main checkout at committer / author time `when` and push main."""
    for rel, text in files.items():
        repo.write(rel, text)
    env = dict(repo.env, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    run_git(repo.path, "add", "-A", env=env)
    run_git(repo.path, "commit", "-q", "-m", message, env=env)
    sha = repo.head()
    if repo.remote:
        repo.git("push", "-q", "origin", "main")
    return sha


def history_commits(repo):
    """Before T0 (on SECTION), after T0 the #1905 fix (SECTION + CONTROLLER), after T0 an unrelated one."""
    before = dated_commit(repo, "refactor: sign-out wording (before the Issue)",
                          {SECTION: "void _signOut() {\n  show(e.toString().tr); // old\n}\n"}, "2030-01-01T00:00:00Z")
    fix = dated_commit(repo, "fix: 로그인·로그아웃 실패 스낵바에 예외 원문 대신 안내 문구 (#1905)",
                       {SECTION: "void _signOut() {\n  show(manualSignOutFailureBodyKey(e.toString()).tr);\n}\n",
                        CONTROLLER: "String manualSignOutFailureBodyKey(String raw) => 'FailToGoogleSignOut';\n"},
                       "2030-01-03T00:00:00Z")
    other = dated_commit(repo, "docs: readme", {"README.md": "app 2\n"}, "2030-01-04T00:00:00Z")
    return before, fix, other


# --- unit: history ------------------------------------------------------------------------------------

class HistoryFacts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = GitRepo.create(self._tmp.name, name="app", files=dict(FILES))
        self.before, self.fix, self.other = history_commits(self.repo)
        self.repo.write(REPRO, REPRO_TEXT)
        self.head = self.repo.commit("test: reproduce")
        self.ctx = gitops.main_context(self.repo.path, base_env=self.repo.env)

    def tearDown(self):
        self._tmp.cleanup()

    def test_bug_labels_and_evidence(self):
        self.assertTrue(history.is_bug_label(" Type:Bug "))
        self.assertTrue(history.is_bug_label("bug"))
        self.assertFalse(history.is_bug_label("type:refactor"))
        self.assertEqual(history.bug_evidence(["guild:analyze"], [("a" * 40, "refactor")]), [])
        ev = history.bug_evidence(["type:bug"], [("a" * 40, "bug"), ("b" * 40, "refactor")])
        self.assertEqual(ev, ["Issue label `type:bug`", f"analysis.md at {'a' * 12} recorded `type: bug`"])

    def test_analysis_types_reads_every_recorded_analysis(self):
        rel = "docs/specs/42/analysis.md"
        base = self.repo.head()
        self.repo.write(rel, S.analysis(type="bug"))
        a1 = self.repo.commit("docs: analyze 1")
        self.repo.write(rel, S.analysis(type="refactor", safety_net="only"))
        a2 = self.repo.commit("docs: analyze 2")
        self.assertEqual(history.analysis_types(self.ctx, base, a2, rel), [(a1, "bug"), (a2, "refactor")])

    def test_related_files_follow_imports_and_named_paths(self):
        rel = history.related_files(self.ctx, self.before, self.head, [REPRO],
                                    [("diagnosis.md", f"the cause is in `{CONTROLLER}:1`")], ISSUE_BODY)
        got = {r["path"]: r["why"] for r in rel}
        self.assertEqual(got[SECTION], f"imported by {REPRO}")          # package:app_a/… → lib/…
        self.assertEqual(got[HELPER], f"imported by {REPRO}")           # relative import
        self.assertEqual(got[CONTROLLER], "named in diagnosis.md")
        self.assertNotIn(REPRO, got)                                   # not in the base tree
        self.assertFalse([p for p in got if "flutter_test" in p])        # an outside package resolves to nothing

    def test_commits_since_the_issue_on_related_files(self):
        cs, more = history.commits_since(self.ctx, self.other, T0, [SECTION, CONTROLLER])
        self.assertEqual([c["sha"] for c in cs], [self.fix])            # not the one before T0, not the unrelated one
        self.assertEqual(sorted(cs[0]["files"]), sorted([SECTION, CONTROLLER]))
        self.assertEqual(more, 0)
        with self.assertRaises(history.HistoryError):
            history.commits_since(self.ctx, self.other, "yesterday", [SECTION])

    def test_analyze_history_md(self):
        ctx = gitops.main_context(self.repo.path, base_env=self.repo.env)
        text = history.analyze_history_md(ctx, self.other, {"createdAt": T0, "body": ISSUE_BODY})
        self.assertIn(f"Issue written at: {T0}", text)
        self.assertIn(self.fix[:12], text)                              # commits since T0 on the named paths
        self.assertNotIn(self.before[:12], text)
        self.assertIn("### `manualSignOutFailureBodyKey`", text)
        self.assertIn(f"{CONTROLLER}:1:", text)                         # git grep hit at the base
        none = history.analyze_history_md(ctx, self.other, {"createdAt": None, "body": "no tokens"})
        self.assertIn("unknown", none)
        self.assertIn("not listed (no Issue time)", none)


# --- unit: rule 1 narrowing, the human's rows --------------------------------------------------------

class Narrowing(unittest.TestCase):
    def setUp(self):
        start = instructions.load_start_procedure(stage=3)
        self.proc = procmod.build_start(start, 42, ["ac-format"], stage=3)
        self.state = store.new_state(42, self.proc.revision, self.proc.step_ids, "a" * 40)
        self.state["developer_started"] = False
        self.templates = [{"name": n, "version": "1", "steps": ["x"]} for n in ("bug", "safety-net", "refactor")]
        self.bug = {"evidence": ["Issue label `type:bug`"], "repro_templates": ["bug"]}

    def allowed(self, analysis, bug, mode="unattended"):
        return leadermod.allowed_answers("plan-gate", self.state, self.proc, "plan", mode=mode, analysis=analysis,
                                         decision_marker=False, stage=3, templates=self.templates, bug_issue=bug)

    def test_safety_net_row_of_a_bug_issue_loses_plan_in_both_modes(self):
        an = {"type": "refactor", "safety_net": "only", "split": False, "prerequisite_open": False, "risk": "low"}
        for mode in ("unattended", "attended"):
            with self.subTest(mode=mode):
                a = self.allowed(an, self.bug, mode)
                self.assertNotIn("plan", a.answers)
                self.assertIn(("bug-without-repro-red", ("plan",)), a.narrowed)
                self.assertIn("escalate", a.answers)
                self.assertIn("plan", a.human_answers)                   # D17: the human keeps every answer
        a = self.allowed(an, None)                                         # not a bug Issue: unchanged
        self.assertIn("plan", a.answers)

    def test_bug_row_keeps_plan(self):
        an = {"type": "bug", "safety_net": "none", "split": False, "prerequisite_open": False, "risk": "low"}
        a = self.allowed(an, self.bug)
        self.assertIn("plan", a.answers)
        self.assertNotIn("bug-without-repro-red", [r for r, _ in a.narrowed])

    def test_not_reproduced_is_a_human_row(self):
        self.assertEqual(lifecycle.allowed_answers(SR.NOT_REPRODUCED.value, {}, stage=4),
                         ["rerun", "close-as-decided", "escalate"])
        self.assertEqual(codes.stop_cause(SR.NOT_REPRODUCED.value), codes.StopCause.LABEL.value)
        self.assertNotIn(SR.NOT_REPRODUCED.value, codes.STAGE3_LEADER_SITUATIONS)
        from gxengine import statemachine
        self.assertEqual(statemachine.stop_status(SR.NOT_REPRODUCED.value, 4), "needs_human")


# --- unit: rule 3 tools -------------------------------------------------------------------------------

class AnalyzeTools(unittest.TestCase):
    def test_analyze_is_a_read_only_judge_with_git_facts(self):
        start = instructions.load_start_procedure(stage=4)
        analyze = next(s for s in start["steps"] if s["id"] == "analyze")
        self.assertIn("in:git-history.md", analyze["inputs"])
        self.assertEqual(codes.role_class(analyze["role"]), codes.RoleClass.JUDGE.value)
        t = render.template(codes.RoleClass.JUDGE.value)
        self.assertEqual(t["tools"], ["Read", "Write"])
        for bad in ("Bash", "Edit", "WebFetch", "WebSearch", "Grep", "Glob"):
            self.assertNotIn(bad, t["tools"])
        allow = t["settings"]["permissions"]["allow"]
        self.assertFalse([a for a in allow if a.startswith("Bash")])
        self.assertEqual([a for a in allow if a.startswith("Edit")], ["Edit(/{worktree}/{outputs})"])
        self.assertIn("WebFetch", t["settings"]["permissions"]["deny"])
        self.assertEqual(t["settings"]["sandbox"]["network"]["allowedDomains"], [])
        for stage in (1, 2):                                               # earlier engines: unchanged
            a = next(s for s in instructions.load_start_procedure(stage=stage)["steps"] if s["id"] == "analyze")
            self.assertNotIn("in:git-history.md", a["inputs"])
        self.assertIn("git-history.md", instructions.task_text("analyze", stage=4))
        self.assertNotIn("git-history.md", instructions.task_text("analyze", stage=3))
        self.assertIn("bug-without-repro-red", instructions.leader_task_text("plan-gate", stage=4))


# --- scenarios ----------------------------------------------------------------------------------------

def gh(labels=("type:bug",), created=T0, body=ISSUE_BODY):
    rules = W.gh_rules(labels=labels)
    issue = rules["rules"][1]["json"]
    issue.update({"createdAt": created, "body": body})
    rules["rules"].append({"args": ["issue", "close", str(W.ISSUE), "--repo", W.REPO, "--reason", "*"], "stdout": ""})
    return rules


class Rule1PlanGate(S.Stage3):
    """VW2 (#1910): analyze 1 says bug, the leader reruns analyze toward refactor / safety_net only, then plans
    safety-net. The engine does not take that plan; a human decides."""

    def setUp(self):
        super().setUp()
        self.w.set_gh(gh())

    def vw2_session(self, first="bug"):
        return self.sess(analyze=[
            {"write": {f"{S.SPECS}/analysis.md": S.analysis(type=first)}, "structured": S.result()},
            {"write": {f"{S.SPECS}/analysis.md": S.analysis(type="refactor", safety_net="only")},
             "structured": S.result()}])

    def vw2_leader(self):
        return self.leader({"plan-gate": [LA("rerun", step="analyze", reason="analysis-gap",
                                             note="already fixed? then refactor + safety_net: only"),
                                          S.plan_ok("safety-net")]})

    def assert_refused(self, ld, rc):
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.w.out.getvalue())
        st = self.state()
        stop = st["stop"]
        self.assertEqual((stop["status"], stop["reason"], stop["step"]), ("needs_human", "plan-gate", "plan"))
        self.assertTrue(stop["note"].startswith("bug-without-repro-red: a bug Issue"), stop["note"])
        self.assertIn("plan --template bug", stop["note"])
        self.assertEqual(stop["recommendation"]["answer"], "plan")
        self.assertIn("template safety-net", stop["recommendation"]["note"])
        self.assertEqual(st["revision"], 1)                                # no safety-net procedure was written
        self.assertEqual([l["data"]["revision"] for l in self.log("procedure-written")], [1])
        self.assertEqual([c["situation"] for c in ld.calls], ["plan-gate", "plan-gate"])
        req = ld.calls[-1]["request"]
        self.assertEqual(req.bug_issue["repro_templates"], ["bug"])
        return req

    def test_unattended_safety_net_plan_of_a_bug_issue_goes_to_a_human(self):
        ld = self.vw2_leader()
        rc = self.run3(ld, mode="unattended", session=self.vw2_session())
        req = self.assert_refused(ld, rc)
        self.assertIn("Issue label `type:bug`", req.bug_issue["evidence"])
        self.assertTrue([e for e in req.bug_issue["evidence"] if "recorded `type: bug`" in e])

    def test_attended_too(self):
        ld = self.vw2_leader()
        self.assert_refused(ld, self.run3(ld, mode="attended", session=self.vw2_session()))

    def test_the_analysis_record_alone_makes_it_a_bug_issue(self):
        self.w.set_gh(gh(labels=()))
        ld = self.vw2_leader()
        req = self.assert_refused(ld, self.run3(ld, mode="unattended", session=self.vw2_session()))
        self.assertEqual(len(req.bug_issue["evidence"]), 1)

    def test_no_bug_evidence_keeps_the_plan(self):
        self.w.set_gh(gh(labels=("type:refactor",)))
        ld = self.vw2_leader()
        self.run3(ld, mode="unattended", session=self.vw2_session(first="refactor"))
        st = self.state()
        self.assertNotEqual((st.get("stop") or {}).get("reason"), "plan-gate", st.get("stop"))
        self.assertEqual(self.procedure()["origin"]["template"], "safety-net")
        self.assertIsNone(ld.calls[0]["request"].bug_issue)

    def test_the_human_may_take_the_switch(self):
        ld = self.vw2_leader()
        self.run3(ld, mode="unattended", session=self.vw2_session())
        self.run3(ld, mode="unattended", answer={"answer": "plan", "template": "safety-net"})
        self.assertEqual(self.procedure()["origin"]["template"], "safety-net")
        self.assertEqual([c["situation"] for c in ld.calls].count("plan-gate"), 2)


class Rule2NotReproduced(S.Stage3):
    """The bug template on an Issue already fixed by a later commit: repro-red stays green → not-reproduced."""

    cfg = S.config(path_rules=[{"kind": "test-code", "globs": ["test/**/*_test.dart"]}, S.SAFETY_NET])
    extra = dict(FILES)

    def setUp(self):
        super().setUp()
        self.w.set_gh(gh())
        self.before, self.fix, self.other = history_commits(self.w.repo)

    def make_session(self):
        return self.sess(
            analyze=[{"write": {f"{S.SPECS}/analysis.md": S.analysis(type="bug") + f"\nThe cause: `{CONTROLLER}:1`.\n"},
                      "structured": S.result()}],
            reproduce=[{"write": {REPRO: REPRO_TEXT}, "commit": "test: reproduce the raw snackbar text",
                        "structured": S.result()}])

    def make_runner(self):
        ev = {"kind": "repro-red", "globs": ["test/**/*_test.dart"],
              "scope": {"ok": True, "step": "reproduce", "attempts": [1], "outside": []},
              "overlay": {"base_sha": "0" * 40, "head_sha": "0" * 40,
                          "files": [{"path": REPRO, "blob": "1" * 40, "base_blob": None}], "existed": []},
              "end_tree": None}
        green = {"exit_code": 0, "timed_out": False, "log_file": "run-head.log"}
        return S.FakeRunner(runs={"repro-red": [{"evidence": ev, "head": green, "head_rerun": None}]})

    def make_results(self):
        return S.FakeResults(judge={"repro-red": [lambda: W.check_failed("repro-not-red")]})

    def leader_(self):
        return self.leader({"plan-gate": [S.plan_ok("bug")],
                            "on-fail-exceeded": [LA("replan", reason="real-defect", note="should never be asked")]})

    def go(self, mode):
        ld = self.leader_()
        rc = self.run3(ld, mode=mode, session=self.make_session(), runner=self.make_runner(), results=self.make_results())
        return ld, rc

    def check_stop(self, ld, rc):
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN, self.w.out.getvalue())
        stop = self.state()["stop"]
        self.assertEqual((stop["status"], stop["reason"], stop["step"]), ("needs_human", "not-reproduced", "repro-red"))
        self.assertEqual(stop["allowed_answers"], ["rerun", "close-as-decided", "escalate"])
        self.assertNotIn("on-fail-exceeded", [c["situation"] for c in ld.calls])     # no leader decision
        self.assertEqual(self.sstep("repro-red")["on_fail_count"], 3)
        note = stop["note"]
        self.assertIn('does not conclude "already fixed"', note)
        self.assertIn(REPRO, note)
        self.assertIn(self.fix[:10], note)
        self.assertNotIn(self.before[:10], note)
        self.assertNotIn(self.other[:10], note)
        with open(os.path.join(self.w.paths().issue_dir, defaults.NOT_REPRODUCED_FILE), encoding="utf-8") as f:
            md = f.read()
        self.assertIn(f"Issue written at: {T0}", md)
        self.assertIn(f"- {self.fix[:12]} ", md)
        self.assertIn("(#1905)", md)
        self.assertNotIn(self.before[:12], md)
        self.assertNotIn(f"- {self.other[:12]} ", md)                    # the recorded base itself, no listed commit
        self.assertIn(f"recorded base {self.other[:12]}", md)
        self.assertIn(f"`{SECTION}` (imported by {REPRO})", md)
        self.assertIn(f"`{CONTROLLER}` (named in analysis.md)", md)
        self.assertIn("testWidgets('no raw exception text'", md)
        self.assertIn("--answer close-as-decided --close-reason completed", md)
        self.assertIn("exit 0", md)
        return md

    def test_unattended_repro_not_red_after_its_retries_goes_to_a_human_with_the_facts(self):
        ld, rc = self.go("unattended")
        self.check_stop(ld, rc)

    def test_attended_too(self):
        ld, rc = self.go("attended")
        self.check_stop(ld, rc)

    def test_analyze_got_the_git_history(self):
        self.go("unattended")
        text = self.in_file("analyze", 1, "git-history.md")
        self.assertIn(self.fix[:12], text)
        self.assertIn("### `manualSignOutFailureBodyKey`", text)
        b = self.brief("analyze", 1)
        self.assertIn("git-history.md", b["in_files"])
        self.assertEqual(b["session"]["tools"], ["Read", "Write"])

    def test_human_rerun_reproduces_again_then_stops_again(self):
        ld, _ = self.go("unattended")
        n = len([c for c in self.session.calls if c["step"] == "reproduce"])
        rc = self.run3(ld, mode="unattended", answer={"answer": "rerun", "step": "reproduce", "note": "use a real exception"},
                       runner=self.make_runner(), results=self.make_results())
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.state()["stop"]["reason"], "not-reproduced")
        self.assertEqual(len([c for c in self.session.calls if c["step"] == "reproduce"]), n + 1)
        self.assertNotIn("on-fail-exceeded", [c["situation"] for c in ld.calls])

    def test_human_close_as_decided(self):
        ld, _ = self.go("unattended")
        rc = self.run3(ld, mode="unattended", answer={"answer": "close-as-decided", "close_reason": "completed",
                                                       "note": "Fixed by #1905 (3ed02bf33)."})
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        st = self.state()
        self.assertEqual(st["closed"]["reason"], "completed")
        self.assertEqual(self.sstep("repro-red")["status"], "skipped")
        self.assertEqual(self.sstep("fix")["status"], "skipped")
        argv = [c["argv"] for c in self.w.gh_calls()]
        self.assertIn(["issue", "close", str(W.ISSUE), "--repo", W.REPO, "--reason", "completed"], argv)


if __name__ == "__main__":
    unittest.main()
