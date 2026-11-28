"""VA3 · VA5 — what one Issue's engine does for a sprint: the start input and the stacked PR (TS), the remote check
(TS6), the needs-human label (TL4), the automatic quota rerun (TQ3, TQ5). Real git, gh in process."""

import json
import os
import tempfile
import time
import unittest

from gxengine import cli, defaults, driver, github, gitops, lifecycle, paths as pathsmod, results, statemachine, store
from tests import c_world as W
from tests import s3_world as S
from tests.helpers.gitrepo import GitRepo
from tests.test_stage4_wiring import Stage4World

LABEL = "guild:needs-human"


class Member(Stage4World):
    def start(self, sha=None, branch="main", draft=False):
        return driver.StartOptions(sha or self.origin("main"), branch, draft, 700)

    def origin(self, branch):
        return self.w.repo.git("rev-parse", branch, cwd=self.w.repo.remote)

    def member(self, leader=None, start=None, **kw):
        kw.setdefault("mode", "unattended")
        return self.run4(leader or self.leader(), start=start, **kw)

    def pr_fields(self):
        calls = [c for c in self.w.gh.calls if c["argv"][:4] == ["api", "-X", "POST", f"repos/{W.REPO}/pulls"]]
        return [json.loads(c["stdin"]) for c in calls]

    def push_branch(self, branch, files, base="main"):
        """A branch on the remote only (a dependency's work), → its sha."""
        tmp = os.path.join(self.w.tmp, "other")
        if not os.path.isdir(tmp):
            self.w.repo.git("clone", "-q", self.w.repo.remote, tmp, cwd=self.w.tmp)
        self.w.repo.git("checkout", "-q", "-B", branch, "origin/" + base, cwd=tmp)
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
            with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
                f.write(text)
        self.w.repo.git("add", "-A", cwd=tmp)
        self.w.repo.git("commit", "-q", "-m", "work of " + branch, cwd=tmp)
        self.w.repo.git("push", "-q", "origin", branch, cwd=tmp)
        self.w.repo.git("fetch", "-q", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
        return self.origin(branch)


class StartInput(Member):
    def test_a_stacked_member(self):
        """TS1: base sha = the dependency's head, PR base = gld/41, the stack value for the PR body, no file of 41."""
        sha = self.push_branch("gld/41", {"src/dep.py": "d = 1\n", "docs/specs/41/analysis.md": "a\n"})
        self.ok(self.member(start=self.start(sha, "gld/41", draft=True)))
        st = self.state()
        self.assertEqual((st["base_sha"], st["base_branch"], st["draft"], st["sprint"], st["mode"]),
                         (sha, "gld/41", True, 700, "unattended"))
        pr = self.pr_fields()[0]
        self.assertEqual((pr["base"], pr["draft"], pr["head"]), ("gld/41", True, "gld/42"))
        self.assertIn("Closes #42", pr["body"])
        self.assertEqual(self.prbody.stage4[0]["stack"], {"issue": 41, "tracker": 700, "draft": True})
        ctx = gitops.GitContext.from_state(st, base_env=self.w.environ)
        changed = {c["path"] for c in gitops.changed_files(ctx, gitops.head(ctx))}
        self.assertIn("src/app.py", changed)
        self.assertFalse({p for p in changed if "41" in p or "dep" in p}, changed)
        line = self.log("sprint-member")[0]["data"]
        self.assertEqual(line, {"tracker": 700, "base_sha": sha, "base_branch": "gld/41", "draft": True})
        self.assertEqual(self.log("issue-start")[0]["data"]["base_branch"], "gld/41")

    def test_the_default_branch_is_the_remotes_and_no_local_ref_moves(self):
        """TS2, TS4: a sprint member starts on the fetched commit, a human's dev on the local branch."""
        local = self.w.repo.git("rev-parse", "refs/heads/main")
        new = self.push_branch("main", {"src/merged.py": "m = 1\n"})
        self.assertNotEqual(local, new)
        self.ok(self.member(start=self.start(new)))
        st = self.state()
        self.assertEqual((st["base_sha"], st["base_branch"], st["draft"]), (new, "main", False))
        self.assertEqual((self.pr_fields()[0]["base"], self.pr_fields()[0]["draft"]), ("main", False))
        self.assertIsNone(self.prbody.stage4[0]["stack"])
        self.assertEqual(self.w.repo.git("rev-parse", "refs/heads/main"), local)

    def test_a_humans_dev_is_unchanged(self):
        local = self.w.repo.git("rev-parse", "refs/heads/main")
        self.push_branch("main", {"src/merged.py": "m = 1\n"})
        self.ok(self.run4(self.leader()))
        st = self.state()
        self.assertEqual(st["base_sha"], local)
        for key in ("base_branch", "draft", "sprint"):
            self.assertNotIn(key, st)
        self.assertEqual(self.log("sprint-member"), [])
        self.assertEqual((self.pr_fields()[0]["base"], self.pr_fields()[0]["draft"]), ("main", False))

    def test_control_files_and_specs_of_the_stack_base_are_not_this_issues(self):
        """TS7: they are in the base, so neither the control-file nor the ownership judgment sees a change."""
        sha = self.push_branch("gld/41", {"CLAUDE.md": "other rules\n", "docs/specs/41/procedure.yaml": "{}\n",
                                         "docs/specs/41/analysis.md": "a\n"})
        self.ok(self.member(start=self.start(sha, "gld/41")))
        st = self.state()
        ctx = gitops.GitContext.from_state(st, base_env=self.w.environ)
        got = results.check_control_files(ctx, st["procedure"]["commit"], W.ISSUE, gitops.head(ctx))
        self.assertEqual((got["ok"], got["changed"]), (True, []))
        self.w.wt_git("rm", "-q", "CLAUDE.md")
        self.w.wt_git("commit", "-q", "-m", "x")
        self.assertFalse(results.check_control_files(ctx, st["procedure"]["commit"], W.ISSUE, gitops.head(ctx))["ok"])

    def test_resume_opens_the_pr_on_the_recorded_branch(self):
        """TS8: nothing but state.json says where the PR goes — also when GitHub's default branch changes meanwhile."""
        sha = self.push_branch("gld/41", {"src/dep.py": "d = 1\n"})
        res = S.FakeResults({"design": [W.blocked, W.done]})
        ld = self.leader({"blocked": [W.leader_answer("escalate", recommendation={"answer": "rerun", "step": "design", "note": ""})]})
        self.assertEqual(self.member(ld, start=self.start(sha, "gld/41", draft=True), results=res), driver.EXIT_NEEDS_HUMAN)
        rules = W.gh_rules()
        rules["rules"][0]["json"]["defaultBranchRef"]["name"] = "develop"
        self.w.set_gh(rules)
        self.ok(self.run4(ld, answer={"answer": "rerun", "step": "design"}, results=res))
        self.assertEqual((self.pr_fields()[0]["base"], self.pr_fields()[0]["draft"]), ("gld/41", True))

    def test_a_start_input_is_refused(self):
        sha = self.origin("main")
        for start, mode, stage in ((self.start(), "attended", 4),                              # TS9
                                   (self.start(), "unattended", 3),
                                   (self.start(sha, "develop"), "unattended", 4),              # neither default nor a member's
                                   (self.start(sha, "gld/42"), "unattended", 4),                # itself
                                   (self.start(sha, "gld/x"), "unattended", 4),
                                   (self.start("b" * 40), "unattended", 4)):                   # not fetched
            with self.subTest(branch=start.base_branch, mode=mode, stage=stage):
                self.assertEqual(self.run4(self.leader(), mode=mode, stage=stage, start=start), driver.EXIT_REFUSED)
                self.assertIsNone(self.state())
                self.assertFalse(os.path.exists(self.w.worktree))
                self.assertTrue(self.log("warning")[-1]["data"]["refused"])

    def test_a_started_issue_takes_no_start_input(self):
        self.ok(self.member(start=self.start()))
        self.assertEqual(self.member(start=self.start()), driver.EXIT_REFUSED)
        self.assertIn("has engine state", self.w.out.getvalue())


class RemoteBranch(Member):
    """TS6 (H10)."""

    def test_a_leftover_branch_refuses_before_anything_is_paid(self):
        self.push_branch("gld/42", {"src/old.py": "o\n"})
        self.assertEqual(self.run4(self.leader()), driver.EXIT_REFUSED)
        self.assertIn("already on the remote", self.w.out.getvalue())
        self.assertIsNone(self.state())
        self.assertEqual(self.session.calls, [])
        self.assertFalse(os.path.exists(self.w.worktree))

    def test_an_open_pull_request_refuses(self):
        rules = W.gh_rules()
        rules["rules"].insert(0, {"args": ["api", f"repos/{W.REPO}/pulls?head=*"], "json": [
            {"number": 8, "state": "open", "head": {"ref": "gld/42"}}]})
        self.w.set_gh(rules)
        self.assertEqual(self.member(start=self.start()), driver.EXIT_REFUSED)
        self.assertIn("pull request 8", self.w.out.getvalue())

    def test_closed_pull_requests_and_other_branches_do_not_refuse(self):
        self.push_branch("gld/421", {"src/old.py": "o\n"})
        rules = W.gh_rules()
        rules["rules"].insert(0, {"args": ["api", f"repos/{W.REPO}/pulls?head=*"], "times": 1, "json": [
            {"number": 8, "state": "closed", "head": {"ref": "gld/42"}}]})
        self.w.set_gh(rules)
        self.ok(self.run4(self.leader()))

    def test_unknown_is_not_free(self):
        rules = W.gh_rules()
        rules["rules"].insert(0, {"args": ["api", f"repos/{W.REPO}/pulls?head=*"], "exit_code": 1, "stderr": "HTTP 502"})
        self.w.set_gh(rules)
        self.assertEqual(self.run4(self.leader()), driver.EXIT_REFUSED)
        self.assertIsNone(self.state())

    def test_stage_3_does_not_look(self):
        rules = W.gh_rules()
        self.w.set_gh(rules)
        self.ok(self.run4(self.leader(), stage=3))
        reads = [c["argv"] for c in self.w.gh.calls if len(c["argv"]) == 2 and "pulls?head" in c["argv"][1]]
        self.assertEqual(len(reads), 1, "create_pr's own look only")


class Label(Member):
    """TL4 (H9)."""

    def stopped(self, mode, stage=4):
        self.res = S.FakeResults({"design": [W.blocked, W.done]})
        self.ld = self.leader({"blocked": [W.leader_answer("escalate", recommendation={"answer": "rerun", "step": "design", "note": ""})]})
        return self.run4(self.ld, mode=mode, stage=stage, results=self.res)

    def adds(self):
        return [c for c in self.gh.calls if c["fn"] == "add_label" and c["name"] == LABEL]

    def deletes(self):
        return [c["argv"][3] for c in self.w.gh.calls if c["argv"][:3] == ["api", "-X", "DELETE"] and "needs-human" in c["argv"][3]]

    def test_on_while_a_human_is_needed_off_when_it_goes_on(self):
        for mode in ("attended", "unattended"):
            with self.subTest(mode=mode):
                self.assertEqual(self.stopped(mode), driver.EXIT_NEEDS_HUMAN)
                self.assertEqual(len(self.adds()), 1)
                self.assertEqual(self.log("label")[-1]["data"], {"name": LABEL, "on": True})
                self.w.set_gh(W.gh_rules(labels=[LABEL]))
                self.ok(self.run4(self.ld, answer={"answer": "rerun", "step": "design"}, results=self.res))
                self.assertEqual(self.deletes(), [f"repos/{W.REPO}/issues/42/labels/guild%3Aneeds-human"])
                self.assertEqual(self.log("label")[-1]["data"], {"name": LABEL, "on": False})
            self.tearDown()
            self.setUp()

    def test_an_escalate_answer_keeps_it(self):
        self.stopped("attended")
        self.w.set_gh(W.gh_rules(labels=[LABEL]))
        self.assertEqual(self.run4(self.ld, answer={"answer": "escalate"}, results=self.res), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.deletes(), [])

    def test_a_failed_write_is_a_warning(self):
        self.gh.fail["add_label"] = 1
        self.assertEqual(self.stopped("unattended"), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.state()["stop"]["status"], "needs_human")
        self.assertTrue([l for l in self.log("warning") if "label" in (l.get("note") or "")])
        rules = W.gh_rules(labels=[LABEL])
        rules["rules"].insert(0, {"args": ["api", "-X", "DELETE", f"repos/{W.REPO}/issues/{W.ISSUE}/labels/guild%3Aneeds-human"],
                                  "exit_code": 1, "stderr": "HTTP 502"})
        self.w.set_gh(rules)
        self.ok(self.run4(self.ld, answer={"answer": "rerun", "step": "design"}, results=self.res))

    def test_an_engine_error_gets_it_too(self):
        class Boom(S.FakeRunner):
            def run_step(self, *a, **kw):
                raise RuntimeError("boom")
        self.assertEqual(self.run4(self.leader(), runner=Boom()), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.state()["stop"]["reason"], "engine-error")
        self.assertEqual(len(self.adds()), 1)

    def test_a_leader_turn_is_no_human_turn(self):
        ld = self.leader({"plan-gate": [{"quota_reset_at": 1000.0 + defaults.INFRA_WAIT_MAX_S + 60}]})
        self.assertEqual(self.run4(ld, now=lambda: 1000.0), driver.EXIT_NEEDS_LEADER)
        self.assertEqual(self.adds(), [])

    def test_stage_3_has_none(self):
        self.assertEqual(self.stopped("attended", stage=3), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.adds(), [])
        self.w.set_gh(W.gh_rules(labels=[LABEL]))
        self.ok(self.run4(self.ld, answer={"answer": "rerun", "step": "design"}, results=self.res, stage=3))
        self.assertEqual(self.deletes(), [])


class RemoveLabel(unittest.TestCase):
    def gh(self, rules):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = os.path.join(self._tmp.name, "gh.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rules": rules}, f)
        return W.InProcGh("acme/app", path, W.PLUGIN_ROOT)

    def test_missing_is_fine_anything_else_is_not(self):
        args = ["api", "-X", "DELETE", "repos/acme/app/issues/42/labels/guild%3Aneeds-human"]
        github.remove_label(self.gh([{"args": args, "json": []}]), 42, LABEL)
        github.remove_label(self.gh([{"args": args, "exit_code": 1, "stderr": "gh: Label does not exist (HTTP 404)"}]), 42, LABEL)
        with self.assertRaises(github.GhError):
            github.remove_label(self.gh([{"args": args, "exit_code": 1, "stderr": "HTTP 502"}]), 42, LABEL)
        with self.assertRaises(ValueError):
            github.remove_label(self.gh([]), 42, "a/b")


class QuotaRerun(Member):
    """TQ3–TQ5: the sprint seat through the command line (`resume --foreground --answer rerun --sprint T`)."""

    def resume(self):
        args = ["resume", "--repo", W.REPO, "--issue", str(W.ISSUE), "--foreground", "--answer", "rerun", "--sprint", "700"]
        self.results = S.FakeResults()
        return cli.main(args, environ=self.w.environ, out=self.w.out, units=self.units(self.leader()), stage=4)

    def quota_stop(self, **stop):
        late = time.time() + defaults.INFRA_WAIT_MAX_S + 60
        res = S.FakeResults({"design": [lambda *a, **k: statemachine.Outcome("failed", code="infra", detail="quota", reset_at=late)]})
        self.assertEqual(self.member(start=self.start(), results=res), driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        st["stop"].update(stop)
        store.save_state(self.w.paths(), st)

    def test_after_the_reset_it_reruns_as_the_sprint(self):
        self.quota_stop(reset_at=time.time() - 1)
        self.ok(self.resume())
        self.assertEqual([l["who"] for l in self.log("answer") if l["who"] != "leader"], ["sprint"])
        self.assertEqual(self.state()["mode"], "unattended")

    def test_before_the_reset_nothing_changes(self):
        self.quota_stop()
        before = self.state()["stop"]
        self.assertEqual(self.resume(), driver.EXIT_REFUSED)
        self.assertEqual(self.state()["stop"], before)

    def test_a_note_that_says_quota_is_no_quota_stop(self):
        self.quota_stop(detail="api", reset_at=None, note="quota resets soon")
        self.assertEqual(self.resume(), driver.EXIT_REFUSED)
        self.assertEqual(self.state()["stop"]["detail"], "api")
        self.assertEqual([l for l in self.log("answer") if l["who"] == "sprint"], [])


class InfraDetail(Member):
    def test_a_github_failure_of_a_close_is_coded(self):
        rules = W.gh_rules()
        rules["rules"].insert(0, {"args": ["api", "-X", "POST", f"repos/{W.REPO}/issues/{W.ISSUE}/comments", "--input", "-"],
                                  "json": {"id": 5001}, "times": 1})
        self.w.set_gh(rules)
        ld = self.leader({"plan-gate": [W.leader_answer("close-as-decided", reason="already-decided", note="done before",
                                                        requirements=[], missing_requirements=[], plan=None,
                                                        close={"reason": "completed"})]})
        self.assertEqual(self.run4(ld), driver.EXIT_NEEDS_HUMAN)         # `issue close` has no rule: gh fails
        st = self.state()["stop"]
        self.assertEqual((st["reason"], st["detail"], st["reset_at"]), ("infra-stop", "op-failed", None))


class Git(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.r = GitRepo.create(self._tmp.name, files={"README.md": "a\n", "CLAUDE.md": "r\n", "src/a.py": "x\n"})
        self.ctx = gitops.main_context(self.r.path, base_env=self.r.env)

    def branch(self, name, files, base="main"):
        self.r.git("checkout", "-q", "-B", name, base)
        for rel, text in files.items():
            self.r.write(rel, text)
        sha = self.r.commit("c " + name)
        self.r.git("push", "-q", "origin", name)
        self.r.git("checkout", "-q", "main")
        return sha

    def test_main_context(self):
        self.assertEqual(self.ctx.git_dir, self.ctx.common_dir)
        self.assertEqual(gitops.blob(self.ctx, self.ctx.base_sha, "README.md")[2], b"a\n")
        for bad in (os.path.join(self.r.path, "src"), os.path.join(self._tmp.name, "none")):
            with self.assertRaises((gitops.GitError, OSError)):
                gitops.main_context(bad, base_env=self.r.env)
        self.r.git("remote", "set-url", "--push", "origin", "ext::sh -c x")
        with self.assertRaises(gitops.GitError):
            gitops.main_context(self.r.path, base_env=self.r.env)

    def test_fetch_branches_moves_remote_tracking_refs_only(self):
        sha = self.branch("gld/41", {"src/b.py": "y\n"})
        self.r.git("update-ref", "-d", "refs/remotes/origin/gld/41")
        self.r.git("branch", "-q", "-D", "gld/41")
        heads = self.r.git("for-each-ref", "refs/heads")
        got = gitops.fetch_branches(self.ctx, ["main", "gld/41"])
        self.assertEqual(got, {"main": self.r.git("rev-parse", "main"), "gld/41": sha})
        self.assertEqual(self.r.git("for-each-ref", "refs/heads"), heads)
        self.assertFalse(os.path.exists(os.path.join(self.r.path, ".git", "FETCH_HEAD")))
        for bad in (["gld/99"], ["-x"], ["a b"], ["main", "refs/heads/main"]):
            with self.subTest(bad=bad), self.assertRaises(gitops.GitError):
                gitops.fetch_branches(self.ctx, bad)

    def test_remote_branch_sha(self):
        sha = self.branch("gld/41", {"src/b.py": "y\n"})
        self.branch("x/refs/heads/gld/4", {"src/c.py": "y\n"})
        self.assertEqual(gitops.remote_branch_sha(self.ctx, "gld/41"), sha)
        self.assertIsNone(gitops.remote_branch_sha(self.ctx, "gld/4"))
        self.ctx.remote_url = os.path.join(self._tmp.name, "gone.git")
        with self.assertRaises(gitops.GitError):
            gitops.remote_branch_sha(self.ctx, "gld/41")

    def test_control_changes(self):
        """D1."""
        main = self.r.git("rev-parse", "main")
        plain = self.branch("gld/41", {"src/b.py": "y\n", "docs/specs/41/procedure.yaml": "{}\n"})
        self.assertEqual(gitops.control_changes(self.ctx, main, plain, 42), [])
        for n, rel in enumerate(("CLAUDE.md", "sub/AGENTS.md", ".claude/agents/qa.md", ".claude/guild/config.json",
                                 "docs/specs/42/procedure.yaml")):
            sha = self.branch(f"gld/{60 + n}", {rel: "changed\n"})
            self.assertEqual(gitops.control_changes(self.ctx, main, sha, 42), [rel])
        self.r.git("checkout", "-q", "-B", "gld/51", "main")
        self.r.git("mv", "CLAUDE.md", "notes.md")
        self.r.git("commit", "-q", "-m", "x")
        self.assertEqual(gitops.control_changes(self.ctx, main, self.r.git("rev-parse", "HEAD"), 42), ["CLAUDE.md"])
        self.r.git("checkout", "-q", "main")
        self.r.write("CLAUDE.md", "newer on main\n")
        newer = self.r.commit("main moves")
        self.assertEqual(gitops.control_changes(self.ctx, newer, plain, 42), [], "from the merge base: main's own change is not D's")


class SprintLock(unittest.TestCase):
    """H4."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.realpath(self._tmp.name)
        self.sp = pathsmod.SprintPaths(self.home, "acme/app", 700)

    def test_one_supervisor_per_repository(self):
        self.assertIsNone(lifecycle.sprint_lock_holder(self.sp))
        lifecycle.acquire_sprint_lock(self.sp)
        holder = lifecycle.sprint_lock_holder(self.sp)
        self.assertEqual((holder["pid"], holder["issue"]), (os.getpid(), 700))
        other = pathsmod.SprintPaths(self.home, "acme/app", 701)
        with self.assertRaises(lifecycle.LockHeld):
            lifecycle.acquire_sprint_lock(other)
        self.assertEqual(lifecycle.sprint_lock_holder(other)["issue"], 700)
        lifecycle.acquire_sprint_lock(pathsmod.SprintPaths(self.home, "acme/else", 700))
        issue = pathsmod.EnginePaths(self.home, "acme/app", 42)
        self.assertIsNone(lifecycle.lock_holder(issue), "the engines' repository lock is free (a human may dev / resume)")
        lifecycle.release_sprint_lock(self.sp)
        self.assertIsNone(lifecycle.sprint_lock_holder(self.sp))
        lifecycle.acquire_sprint_lock(other)

    def test_a_dead_holder_is_released(self):
        os.makedirs(self.sp.dir)
        for path in (self.sp.lock, self.sp.repo_lock):
            with open(path, "w") as f:
                json.dump({"format": 1, "pid": 999999, "started": "x", "issue": 700}, f)
        self.assertEqual(len(lifecycle.acquire_sprint_lock(self.sp)["released"]), 2)


if __name__ == "__main__":
    unittest.main()
