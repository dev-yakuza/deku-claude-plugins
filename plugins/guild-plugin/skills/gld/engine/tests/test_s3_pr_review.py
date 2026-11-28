"""Stage 3 flow — after the PR: `resume --pr-review` and `resume --dismiss` (V13 [P2], session B2): TP1–TP5."""

import io
import json
import os
import subprocess
import tempfile
import unittest

from gxengine import cli, driver, lifecycle, paths as pathsmod, store
from tests import c_world as W
from tests import s3_world as S

REVIEW = {"id": "review:5001", "author_association": "OWNER", "created_at": "2026-11-24T01:02:03Z",
          "state": "CHANGES_REQUESTED", "path": None, "kind": "review", "body": "please rename x"}
NOTE = {"id": "comment:900", "author_association": "MEMBER", "created_at": "2026-11-24T01:02:04Z", "state": None,
        "path": None, "kind": "comment", "body": "why not y?"}


def answer(a, effect, step=None, ids=("review:5001",)):
    return S.LA(a, step=step, reason="real-defect" if a == "rerun" else "comment-no-effect", note="per review",
                reviews=[{"id": i, "effect": effect} for i in ids])


class AfterPr(S.Stage3):
    def finished(self, **script):
        self.ld = self.leader(script)
        self.ok(self.run3(self.ld))

    def pr_review(self, **kw):
        return self.run3(self.ld, answer={"pr_review": True}, **kw)

    def calls(self, situation):
        return [c["request"] for c in self.ld.calls if c["situation"] == situation]

    def new_prs(self):
        return len([c for c in self.w.gh_calls() if c["argv"][:4] == ["api", "-X", "POST", f"repos/{W.REPO}/pulls"]])

    def human_commit(self, force=False):
        """A person pushes a commit to the PR branch from another clone."""
        d = os.path.join(self.w.tmp, "human")
        env = self.w.repo.env
        W.run_git(self.w.tmp, "clone", "-q", os.path.join(self.w.tmp, "app.git"), d, env=env)
        W.run_git(d, "checkout", "-q", "gld/42", env=env)
        if force:
            W.run_git(d, "reset", "-q", "--hard", "HEAD~1", env=env)
        with open(os.path.join(d, "src", "human.py"), "w", encoding="utf-8") as f:
            f.write("h = 1\n")
        W.run_git(d, "add", "-A", env=env)
        subprocess.run(["git", "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-qm", "fix: by hand"], cwd=d,
                       env=env, check=True)
        W.run_git(d, "push", "-q", *(["-f"] if force else []), "origin", "gld/42", env=env)

    def test_tp1_a_change_request_reruns_and_updates_the_same_pr(self):
        self.finished(**{"pr-review": [answer("rerun", "change-request", "implement", ("review:5001", "comment:900"))]})
        self.gh.reviews = [REVIEW, NOTE]
        self.session.actions["implement"].append({"write": {"src/app.py": "y = 2\n"}, "commit": "fix: rename",
                                                  "structured": S.result()})
        self.ok(self.pr_review())
        req = self.calls("pr-review")[0]
        self.assertEqual((req.kind, req.step), ("leader", "pr"))
        self.assertEqual(req.pr_review, {"pr_number": 77, "fast_forward": None, "new": [
            {k: i[k] for k in ("id", "author_association", "created_at", "state", "path")} for i in (REVIEW, NOTE)]})
        self.assertIn("please rename x", req.pr_review_md)
        st = self.state()
        self.assertEqual(st["pr_review"], {"last_seen_ids": {"review": 5001, "review-comment": None, "comment": 900},
                                           "rounds": 1})
        self.assertEqual(st["totals"]["leader_calls"], 0)                       # TX4: not counted
        self.assertEqual(self.new_prs(), 0)            # gh calls of this run: no new PR …
        self.assertEqual([c["number"] for c in self.gh.calls if c["fn"] == "update_pr"], [77])
        upd = self.log("pr-updated")
        self.assertEqual((upd[0]["data"]["number"], upd[0]["data"]["head"]), (77, self.w.repo.remote_head("gld/42")))
        self.assertEqual(len(self.log("pr-created")), 1)
        self.assertEqual(len([l for l in self.log("comment") if (l["data"] or {}).get("kind") == "done"]), 1)
        self.assertEqual(self.brief("implement", 2)["returned"]["from_step"], "pr")
        ans = [l for l in self.log("answer") if l["code"] == "pr-review"][0]
        self.assertEqual(ans["data"]["reviews"][0], {"id": "review:5001", "effect": "change-request"})
        # the same reviews are not seen twice: nothing to do, no leader
        self.ok(self.pr_review())
        self.assertEqual(len(self.calls("pr-review")), 1)
        self.assertEqual(self.state()["pr_review"]["rounds"], 1)

    def test_continue_ends_and_a_change_request_is_never_continued(self):
        self.finished(**{"pr-review": [answer("continue", "question"), answer("continue", "change-request")]})
        self.gh.reviews = [REVIEW]
        n = self.state()["totals"]["attempts"]
        self.ok(self.pr_review())
        self.assertEqual(self.state()["totals"]["attempts"], n)                # nothing ran
        self.assertTrue(all(v == "done" for v in S.steps_of(self.state()).values()))
        self.gh.reviews = [dict(REVIEW, id="review:5002")]
        self.assertEqual(self.pr_review(), driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["leader_failed"]["code"]), ("pr-review", "output-format"))
        self.ok(self.run3(self.ld, answer={"answer": "continue"}))             # the human may (D17)

    def test_tp2_human_commits_are_fast_forwarded_and_verified_again(self):
        self.finished(**{"pr-review": [answer("continue", "none", ids=())]})
        self.human_commit()
        self.ok(self.pr_review())
        self.assertEqual(self.calls("pr-review")[0].pr_review["fast_forward"]["commits"], 1)
        self.assertEqual(self.sstep("test")["latest_attempt"], 2)
        self.assertEqual(self.sstep("review")["latest_attempt"], 2)
        self.assertEqual(self.sstep("implement")["latest_attempt"], 1)
        self.assertEqual(len(self.calls("done-gate")), 2)
        self.assertEqual(len(self.log("pr-updated")), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.w.worktree, "src", "human.py")))

    def test_tp3_a_diverged_branch_stops(self):
        self.finished()
        self.human_commit(force=True)
        self.assertEqual(self.pr_review(), driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("remote-diverged", "pr"))
        self.assertEqual(self.calls("pr-review"), [])

    def test_it_starts_only_from_a_finished_issue_and_fails_before_changing_anything(self):
        self.ld = self.leader({"plan-gate": [{"called": False}]})
        self.assertEqual(self.run3(self.ld), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.pr_review(), driver.EXIT_REFUSED)
        self.ok(self.run3(self.ld, answer={"answer": "plan"}))
        self.gh.reviews = [REVIEW]
        self.gh.fail = {"pr_review_items": 1}
        self.assertEqual(self.pr_review(), driver.EXIT_REFUSED)
        self.assertNotIn("pr_review", self.state())
        self.assertIsNone(self.state()["stop"])


BLOCK = S.result(verdict="block", reviewed=["src/app.py"], checks=[{"id": "test-quality", "result": "pass", "note": ""}],
                 findings=[{"severity": "blocker", "file": "src/app.py", "line": 1, "text": "not\ntested"},
                           {"severity": "minor", "file": "src/app.py", "line": 2, "text": "nit"}])


class Dismiss(S.Stage3):
    def stopped(self, structured=BLOCK, outcome=W.check_failed, escalate=True):
        self.results = S.FakeResults({"review": [outcome, outcome, outcome, W.done]})
        self.session = self.sess(review=[{"structured": structured}])
        rec = {"answer": "rerun", "step": "review", "note": ""}
        self.ld = self.leader({"on-fail-exceeded": [S.LA("escalate", reason="needs-human-decision", recommendation=rec)
                                                    if escalate else {"stop": "infra-stop"}]})
        return self.run3(self.ld)

    def resume(self, *argv, foreground=True):
        out = io.StringIO()
        rc = cli.main(["resume", "--repo", W.REPO, "--issue", str(W.ISSUE), *argv, *(["--foreground"] if foreground else [])],
                      environ=self.w.environ, out=out, stage=3, units=self.units(self.ld))
        return rc, out.getvalue()

    def reason(self, text="We accept this risk."):
        p = os.path.join(self.w.tmp, "reason.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_tp4_the_block_is_dismissed_and_changed_code_is_judged_again(self):
        self.assertEqual(self.stopped(), driver.EXIT_NEEDS_HUMAN)
        head = self.w.wt_git("rev-parse", "HEAD").strip()
        self.assertEqual(self.resume("--dismiss", "review")[0], cli.EXIT_REFUSED)            # no reason
        self.assertEqual(self.resume("--dismiss", "review", "--reason-file", self.reason("  "))[0], cli.EXIT_REFUSED)
        self.assertEqual(self.resume("--dismiss", "review", "--reason-file", self.reason(), "--answer", "rerun")[0],
                         cli.EXIT_REFUSED)
        # the done-gate sends the developer back once: the dismissal was for the old HEAD only
        self.ld.script["done-gate"] = [S.LA("rerun", step="implement", reason="real-defect", discoveries=[],
                                            included_fixes=[]), S.approve()]
        rc, out = self.resume("--dismiss", "review", "--reason-file", self.reason())
        self.assertEqual(rc, cli.EXIT_OK, out + self.w.out.getvalue())
        st = self.state()
        d = st["dismissed"]
        self.assertEqual([(x["step"], x["attempt"], x["head"], x["reason"], x["who"], x["findings"]) for x in d],
                         [("review", 3, head, "We accept this risk.", "human", ["blocker: src/app.py: not tested"])])
        ans = [l for l in self.log("answer") if (l.get("data") or {}).get("dismiss")]
        self.assertEqual([(a["who"], a["data"]["dismiss"]) for a in ans], [("human", "review")])
        self.assertEqual(self.sstep("review")["latest_attempt"], 4)                          # judged again
        self.assertIn("We accept this risk.", self.in_file("implement", 4, "leader-decision.md"))

    def test_tp5_nothing_else_can_be_dismissed(self):
        self.assertEqual(self.stopped(outcome=lambda: W.check_failed("required-check-fail")), driver.EXIT_NEEDS_HUMAN)
        rc, out = self.resume("--dismiss", "review", "--reason-file", self.reason(), foreground=False)
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("did not stop on a review's block", out)
        for step in ("test", "design"):
            rc, out = self.resume("--dismiss", step, "--reason-file", self.reason(), foreground=False)
            self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertEqual(self.state()["stop"]["reason"], "on-fail-exceeded")
        with self.assertRaises(lifecycle.AnswerRefused):
            lifecycle.validate_answer(self.state(), "dismiss", stage=3)                      # no answer of any seat

    def test_tp5_the_leaders_turn_and_a_moved_head_refuse(self):
        self.assertEqual(self.stopped(escalate=False), driver.EXIT_NEEDS_LEADER)
        self.assertIn("leader answers", lifecycle.dismiss_problem(self.w.paths(), self.state(), "review"))
        self.ld.script["on-fail-exceeded"] = [S.LA("escalate", reason="needs-human-decision", recommendation={
            "answer": "rerun", "step": "review", "note": ""})]
        self.assertEqual(self.run3(self.ld), driver.EXIT_NEEDS_HUMAN)
        self.w.wt_git("commit", "-q", "--allow-empty", "-m", "chore: moved")
        rc, out = self.resume("--dismiss", "review", "--reason-file", self.reason())
        self.assertEqual(rc, cli.EXIT_REFUSED)
        self.assertIn("branch moved", out)
        self.assertNotIn("dismissed", self.state())


class DismissRules(unittest.TestCase):
    """dismiss_problem on hand-made records: a mandatory check, a step with outputs."""

    def test_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathsmod.EnginePaths(os.path.join(os.path.realpath(tmp), "gx"), "acme/app", 42)
            os.makedirs(p.engine_home)
            store._root(p)
            st = store.new_state(42, 1, ["review"], "a" * 40)
            st["stop"] = {"status": "needs_human", "reason": "on-fail-exceeded", "step": "review", "attempt": 1, "at": "x"}
            with open(os.path.join(W.ENGINE, "tests", "fixtures", "contracts", "facts.example.json"),
                      encoding="utf-8") as f:
                facts = json.load(f)
            facts.update(step="review", attempt=1, outcome={"status": "needs_human", "code": "check-failed",
                                                            "detail": "verdict-block", "stop": None})
            store.write_facts(p, "review", 1, facts)

            def put(brief, result):
                for name, obj in (("brief.json", brief), ("result.json", result)):
                    with open(p.attempt_file("review", 1, name), "w", encoding="utf-8") as f:
                        json.dump(obj, f)
                return lifecycle.dismiss_problem(p, st, "review")

            ok = {"result_kind": "review", "rule_checks": ["test-change-review"], "outputs": []}
            res = {"checks": [{"id": "test-change-review", "result": "pass"}]}
            self.assertIsNone(put(ok, res))
            self.assertIn("mandatory check", put(ok, {"checks": [{"id": "test-change-review", "result": "fail"}]}))
            self.assertIn("outputs", put(dict(ok, outputs=["docs/x.md"]), res))
            self.assertIn("block verdict", put(dict(ok, result_kind="work"), res))


class SkillDocs(unittest.TestCase):
    def test_the_two_resumes_are_documented_with_real_arguments(self):
        p = cli.build_parser()
        sub = next(a for a in p._actions if a.dest == "command").choices["resume"]
        flags = {o for a in sub._actions for o in a.option_strings}
        for rel in ("commands/engine/dev.md", "commands/engine/resume.md"):
            with open(os.path.join(os.path.realpath(os.path.join(W.ENGINE, "..")), rel), encoding="utf-8") as f:
                text = f.read()
            for flag in ("--pr-review", "--dismiss", "--reason-file"):
                self.assertIn(flag, flags)
                self.assertIn(flag, text)


if __name__ == "__main__":
    unittest.main()
