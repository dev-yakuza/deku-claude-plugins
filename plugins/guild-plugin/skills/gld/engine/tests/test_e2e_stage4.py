"""Stage 4 end to end (VZ, TX5): the REAL engine as child processes — `engine.py sprint run` (foreground, then
detached) starts every member as its own `engine.py dev --mode unattended` process, and a human answers a stop
with `engine.py resume`. Every unit is real: the supervisor, the tracker, git (a bare remote), the base check
(the repository's named commands under the real srt, the free srt canary as a child), the driver with the
stage-3 templates, prbody's stack block, the mutation step (nothing declared). Fakes: `claude` (every role and
leader session) and `gh` (tests/fakes/bin). No paid call, no GitHub call, no real repository.

  acme/app, tracking Issue 700: #41 (a refactor) and #42 (a bug fix) stacked on #41, a squash-only repository
  whose plan says `squash-sync` (U1: draft stack).

  run 1   base check green → #41 blocked at `transform`, the leader escalates → stopped (needs_human, the
          guild:needs-human label) → #42 is not started (dep-stopped by #41) → finished
  human   `resume --issue 41 --answer rerun --step transform` → #41 reaches PR 77 (label taken off)
  run 2   detached; #41 is done (not started again), #42 starts on gld/41 at PR 77's head → draft PR 78 with base
          gld/41 and the stack block → finished; the base check is not run again (its green record)
"""

import json
import os
import subprocess
import sys
import unittest

from gxengine import defaults, paths as pathsmod, sprintdag, store
from tests import c_world as W
from tests import z_world as Z
from tests.helpers import fakes

REPO, T, DEP, MEMBER = Z.REPO, 700, 41, 42
ENGINE_PY = os.path.join(Z.ENGINE, "engine.py")
BAR = "\n|---|---|---|---|---|---|\n"
FLAG = "--dangerously-skip" + "-permissions"


def tracker_body():
    rows = f"| 1 | #{DEP} | — | — | | goal |\n| 2 | #{MEMBER} | #{DEP} | #{DEP} | | goal |\n"
    body = ("# Sprint: e2e\n\n<!-- guild:sprint:plan -->\nplan-hash: 000000000000\n- 목표: e2e\n- 스택 깊이 상한: 3\n"
            "- 상한 근거: squash-sync\n\n## 멤버 (실행 순서 · 의존성 정본)\n| # | 이슈 | base 의존 | 원래 의존 | 비고 | 구분 |"
            + BAR + rows + "<!-- /guild:sprint:plan -->\n")
    return body.replace("plan-hash: 000000000000", "plan-hash: " + sprintdag.plan_hash(body))


def issue_rules(n, first_comment_id, labels=()):
    """What one member's engine reads and writes on GitHub (c_world.gh_rules for Issue n)."""
    q = f"repos/{REPO}/"
    rows = [{"name": x} for x in labels]
    rules = [
        {"args": ["issue", "view", str(n), "--repo", REPO, "--json", "number,title,body,labels,state,stateReason,createdAt"],
         "json": {"number": n, "title": f"Issue {n}", "body": "Please make x right.", "state": "OPEN",
                  "stateReason": None, "labels": rows}},
        {"args": ["api", q + f"issues/{n}"], "json": {"number": n, "state": "open", "state_reason": None, "labels": rows}},
        {"args": ["api", q + f"issues/{n}/comments", "--paginate"], "json": []},
        {"args": ["api", q + f"issues/{n}/labels"], "json": []},
        {"args": ["api", "-X", "POST", q + f"issues/{n}/labels", "--input", "-"], "json": []},
        {"args": ["api", "-X", "DELETE", q + f"issues/{n}/labels/*"], "json": []},
    ]
    rules += [{"args": ["api", "-X", "POST", q + f"issues/{n}/comments", "--input", "-"],
               "json": {"id": first_comment_id + k}, "times": 1} for k in range(60)]
    rules += [{"args": ["api", "-X", "PATCH", q + f"issues/comments/{first_comment_id + k}", "--input", "-"],
               "json": {"id": first_comment_id + k}} for k in range(60)]
    return rules


def gh_rules(pr77=None, dep_labels=()):
    """The whole fake GitHub of the test. `pr77` = PR 77's head sha once #41 has opened it; `dep_labels` = what
    GitHub shows on #41 (the engine's label after its stop)."""
    q = f"repos/{REPO}/"
    rules = [
        {"args": ["repo", "view", REPO, "--json", "defaultBranchRef"], "json": {"defaultBranchRef": {"name": "main"}}},
        {"args": ["repo", "view", REPO, "--json", "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"],
         "json": {"mergeCommitAllowed": False, "squashMergeAllowed": True, "rebaseMergeAllowed": False}},
        {"args": ["repo", "view", REPO, "--json", "isPrivate"], "json": {"isPrivate": True}},
        # the tracking Issue and its run marker
        {"args": ["issue", "view", str(T), "--repo", REPO, "--json", "number,title,body,labels,state,stateReason,createdAt"],
         "json": {"number": T, "title": "Sprint", "body": tracker_body(), "labels": [{"name": "guild:sprint"}],
                  "state": "OPEN", "stateReason": None}},
        {"args": ["api", q + f"issues/{T}"], "json": {"number": T, "state": "open", "labels": [{"name": "guild:sprint"}]}},
        {"args": ["api", q + f"issues/{T}/comments", "--paginate"], "json": []},
        {"args": ["api", "-X", "POST", q + f"issues/{T}/comments", "--input", "-"], "json": {"id": 7001}},
        {"args": ["api", "-X", "PATCH", q + "issues/comments/7001", "--input", "-"], "json": {"id": 7001}},
        # the members' Issues, labels, branches and pull requests
        *issue_rules(DEP, 4101, dep_labels), *issue_rules(MEMBER, 4201),
        {"args": ["api", q + "labels/*"], "json": {"name": "guild:x"}},
        {"args": ["api", q + "labels?per_page=100", "--paginate"],
         "json": [{"name": "type:bug"}, {"name": "type:refactor"}, {"name": "guild:followup"}, {"name": "guild:needs-human"}]},
        {"args": ["api", "-X", "POST", q + "labels", "--input", "-"], "json": {"name": "created"}},
        {"args": ["api", q + "git/matching-refs/heads/*"], "json": []},
        {"args": ["api", q + "pulls?head=*"], "json": []},
        # readiness T1 P2: a member's start reads the open pull requests that close it (none here)
        {"args": ["pr", "list", "--repo", REPO, "--state", "open", "--limit", "*", "--json",
                  "number,headRefName,body,closingIssuesReferences"], "json": []},
        {"args": ["api", "-X", "POST", q + "pulls", "--input", "-"],
         "json": {"number": 77, "html_url": f"https://github.com/{REPO}/pull/77"}, "times": 1},
        {"args": ["api", "-X", "POST", q + "pulls", "--input", "-"],
         "json": {"number": 78, "html_url": f"https://github.com/{REPO}/pull/78"}, "times": 1},
        {"args": ["api", "-X", "PATCH", q + "pulls/*", "--input", "-"], "json": {"number": 77}},
        # create-followups: nothing to create, the searches answer nothing
        {"args": ["api", q + "issues?labels=*"], "json": []},
        {"args": ["api", q + "issues?labels=*", "--paginate"], "json": []},
    ]
    if pr77 is not None:                       # set_gh starts the use counts again: 77 is taken
        rules = [r for r in rules if not (r["args"][:4] == ["api", "-X", "POST", q + "pulls"] and r["json"]["number"] == 77)]
        rules.insert(0, {"args": ["api", q + "pulls/77"], "json": {
            "number": 77, "state": "open", "merged_at": None, "head": {"ref": f"gld/{DEP}", "sha": pr77},
            "base": {"ref": "main"}}})
    return {"rules": rules}


def for_issue(scn, n):
    """A Z3 scenario (written for #42) for Issue n: its spec paths and its number."""
    return json.loads(json.dumps(scn).replace(f"docs/specs/{Z.ISSUE}", f"docs/specs/{n}").replace(f"#{Z.ISSUE}", f"#{n}"))


REFACTOR_REVIEWED = ("src/app.py", "tests/test_value.py")


def refactor_until_blocked():
    """#41: analyze → plan-gate → test-cases → design → transform BLOCKED → the leader escalates."""
    out = [Z.role_scenario3("analyze", analysis=Z.analysis3("refactor", ac="x keeps its value under a clearer name.")),
           Z.leader_scenario("plan-gate", Z.plan3("refactor", note="A refactor without a safety net.")),
           Z.role_scenario3("test-cases"), Z.role_scenario3("design")]
    tr = Z.role_scenario3("transform")
    tr["structured_output"] = dict(Z.work_result3(), status="blocked",
                                   blocked_by={"kind": "other", "note": "the name is not agreed yet"})
    tr["actions"] = []
    out += [tr, Z.leader_scenario("blocked", Z.envelope(
        "escalate", "needs-human-decision", note="A human has to agree on the name.",
        recommendation={"answer": "rerun", "step": "transform", "note": ""}, session=None))]
    return [for_issue(s, DEP) for s in out]


def refactor_after_the_answer():
    """#41 after `resume --answer rerun --step transform`: transform → reviews → qa → done-gate approve."""
    tr = Z.role_scenario3("transform")
    tr["actions"] = [{"op": "write", "path": "src/app.py", "content": "VALUE = 1\nx = VALUE\n"},
                     {"op": "write", "path": "tests/test_value.py",
                      "content": "import sys\nsys.path.insert(0, 'src')\nimport app\nassert app.VALUE == app.x\n"},
                     {"op": "git", "args": ["add", "-A"]}, {"op": "git", "args": ["commit", "-q", "-m", "refactor: name it"]}]
    out = [tr]
    for st, checks in (("review-design", ["structure-improved", "behavior-preserved"]),
                       ("review-tests", ["test-quality", "test-change-review"]), ("review-audit", ["diff-review"])):
        out.append(Z.role_scenario3(st, structured_output=Z.review_result3(checks, reviewed=REFACTOR_REVIEWED)))
    qa = Z.role_scenario3("qa")
    qa["structured_output"]["reviewed"] = list(REFACTOR_REVIEWED)
    out += [qa, Z.leader_scenario("done-gate", Z.approve3(evidence="tests/test_value.py"))]
    return [for_issue(s, DEP) for s in out]


def bug_on_the_stack():
    """#42 on gld/41 (x = VALUE = 1): the bug template; the fix keeps #41's name (VALUE = 2)."""
    out = [Z.role_scenario3("analyze"), Z.leader_scenario("plan-gate", Z.plan3("bug"))]
    for st in Z.BUG_ROLE_STEPS:
        s = Z.role_scenario3(st)
        if st == "fix":
            s["actions"] = [{"op": "write", "path": "src/app.py", "content": "VALUE = 2\nx = VALUE\n"},
                            {"op": "git", "args": ["add", "-A"]}, {"op": "git", "args": ["commit", "-q", "-m", "fix: x is 2"]}]
        out.append(s)
    return out + [Z.leader_scenario("done-gate", Z.approve3())]


class SprintWorld(Z.Z3World):
    """Z3World with two members and the tracker: the engine home is shared by every child process."""

    def __init__(self, tmp):
        super().__init__(tmp, gh=gh_rules())
        self.home_real = os.path.realpath(self.engine_home)

    def cli(self, *args, timeout=1800):
        """The real entry point as a child process (the engine's own stage, defaults.ENGINE_STAGE)."""
        fakes.assert_fakes_first(self.environ)
        return subprocess.run([sys.executable, "-I", "-B", ENGINE_PY, *args], cwd=self.repo.path, env=self.environ,
                              capture_output=True, text=True, timeout=timeout)

    def ipaths(self, n):
        return pathsmod.EnginePaths(self.home_real, REPO, n)

    def istate(self, n):
        return store.load_state(self.ipaths(n))

    def sp(self):
        return pathsmod.SprintPaths(self.home_real, REPO, T)

    def sprint_json(self):
        return store.load_sprint(self.sp())

    def sprint_log(self):
        return list(store.read_sprint_log(self.sp()))

    def remote_sha(self, branch):
        return self.repo.git("rev-parse", branch, cwd=self.repo.remote).strip()

    def pulls(self):
        return [json.loads(c["stdin"]) for c in self.gh_calls()
                if c["argv"][:4] == ["api", "-X", "POST", f"repos/{REPO}/pulls"]]


class SprintEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Z.new_tmp()
        self.addCleanup(Z.rmtree, self.tmp)
        self.w = SprintWorld(self.tmp)

    def why(self, p=None):
        text = "" if p is None else f"rc={p.returncode}\n--- stdout\n{p.stdout}\n--- stderr\n{p.stderr}\n"
        for n in (DEP, MEMBER):
            log = self.w.ipaths(n).engine_log
            if os.path.exists(log):
                with open(log, encoding="utf-8", errors="replace") as f:
                    text += f"--- engine.log #{n}\n" + f.read()[-6000:]
            if os.path.exists(self.w.ipaths(n).log):
                lines = list(store.read_log(self.w.ipaths(n)))[-8:]
                text += f"--- log.jsonl #{n}\n" + "\n".join(json.dumps(l, ensure_ascii=False)[:1500] for l in lines) + "\n"
        sup = self.w.sp().supervisor_log
        if os.path.exists(sup):
            with open(sup, encoding="utf-8", errors="replace") as f:
                text += "--- supervisor.log\n" + f.read()[-6000:]
        return text

    def test_tx5_two_members_stacked_one_stops_a_human_answers_the_next_run_finishes(self):
        w = self.w
        for scn in refactor_until_blocked() + refactor_after_the_answer() + bug_on_the_stack():
            w.add(scn)
        main = w.remote_sha("main")
        local_main = w.repo.git("rev-parse", "refs/heads/main").strip()

        # --- run 1: the supervisor in the foreground (as the detached one runs it)
        p = w.cli("sprint", "run", "--repo", REPO, "--tracker", str(T), "--checkout", w.repo.path, "--foreground")
        self.assertEqual(p.returncode, 0, self.why(p))
        s = w.sprint_json()
        m = {r["issue"]: r for r in s["members"]}
        self.assertEqual((s["run"], s["state"], s["halt"], s["order"]), (1, "finished", None, [DEP, MEMBER]), self.why(p))
        self.assertEqual((s["stack_reason"], s["base_check"]["sha"], s["base_check"]["ok"]), ("squash-sync", main, True))
        self.assertEqual((m[DEP]["outcome"], m[DEP]["stop_reason"], m[DEP]["rc"]), ("stopped", "blocked", 10), self.why(p))
        self.assertEqual(m[DEP]["base"], {"branch": "main", "sha": main, "stacked_on": None})
        self.assertEqual((m[MEMBER]["outcome"], m[MEMBER]["block"], m[MEMBER]["cause"], m[MEMBER]["started"]),
                         ("blocked", "dep-stopped", DEP, None))
        self.assertIsNone(w.istate(MEMBER), "no child engine for the blocked member")
        st = w.istate(DEP)
        self.assertEqual((st["mode"], st["base_sha"], st["base_branch"], st["sprint"], st["draft"]),
                         ("unattended", main, "main", T, False))
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"], st["stop"]["step"]), ("needs_human", "blocked", "transform"))
        labels = [c for c in w.gh_calls() if c["argv"][:4] == ["api", "-X", "POST", f"repos/{REPO}/issues/{DEP}/labels"]]
        self.assertTrue(labels and "guild:needs-human" in labels[-1]["stdin"], "H9: the label of a human's stop")
        green = os.listdir(os.path.dirname(pathsmod.base_green_record(self.w.home_real, REPO, main, "0" * 64)))
        self.assertEqual(len([f for f in green if f.endswith(".json")]), 1, "the base-green record of run 1")
        # the run marker: codes and numbers, one comment created then patched
        markers = [json.loads(c["stdin"])["body"] for c in w.gh_calls()
                   if c["argv"][:4] in (["api", "-X", "POST", f"repos/{REPO}/issues/{T}/comments"],
                                        ["api", "-X", "PATCH", f"repos/{REPO}/issues/comments/7001"])]
        self.assertTrue(markers and all(b.startswith(defaults.SPRINT_RUN_MARKER) for b in markers))
        last = json.loads(markers[-1].split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual((last["state"], last["completion"]["stopped"], last["completion"]["blocked"]),
                         ("finished", [DEP], [MEMBER]))
        self.assertEqual(len([c for c in w.gh_calls()
                              if c["argv"][:4] == ["api", "-X", "POST", f"repos/{REPO}/issues/{T}/comments"]]), 1)

        # --- a human answers #41's stop (the sprint never does); GitHub now shows the engine's label on #41
        w.set_gh(gh_rules(dep_labels=["guild:needs-human"]))
        p = w.cli("resume", "--repo", REPO, "--issue", str(DEP), "--answer", "rerun", "--step", "transform", "--foreground")
        self.assertEqual(p.returncode, 0, self.why(p))
        st = w.istate(DEP)
        self.assertIsNone(st["stop"])
        self.assertEqual((st["github"]["pr_number"], st["base_branch"]), (77, "main"))
        pr41 = w.pulls()[0]
        self.assertEqual((pr41["base"], pr41["head"], pr41["draft"]), ("main", f"gld/{DEP}", False))
        self.assertNotIn(defaults.SPRINT_STACK_MARKER, pr41["body"])
        self.assertTrue([c for c in w.gh_calls() if c["argv"][:4] == ["api", "-X", "DELETE", f"repos/{REPO}/issues/{DEP}/labels/guild%3Aneeds-human"]],
                        "H9: the label comes off when the Issue goes on")
        head41 = w.remote_sha(f"gld/{DEP}")
        w.set_gh(gh_rules(pr77=head41))

        # --- run 2: detached, then `status --wait` for its exit code
        p = w.cli("sprint", "run", "--repo", REPO, "--tracker", str(T), "--checkout", w.repo.path)
        self.assertEqual(p.returncode, 0, self.why(p))
        self.assertIn("sprint supervisor started", p.stdout)
        p = w.cli("sprint", "status", "--repo", REPO, "--tracker", str(T), "--wait", "1500", timeout=1600)
        self.assertEqual(p.returncode, 0, self.why(p))
        self.assertIn("run 2: finished", p.stdout)
        with open(w.sp().supervisor_rc) as f:
            self.assertEqual(f.read().strip(), "0")
        s = w.sprint_json()
        m = {r["issue"]: r for r in s["members"]}
        self.assertEqual((s["run"], s["state"]), (2, "finished"), self.why())
        self.assertEqual((m[DEP]["outcome"], m[DEP]["started"], m[DEP]["pr"]), ("done", None, 77), "#41 is not run again")
        self.assertEqual((m[MEMBER]["outcome"], m[MEMBER]["pr"], m[MEMBER]["draft"], m[MEMBER]["rc"]), ("done", 78, True, 0), self.why())
        self.assertEqual(m[MEMBER]["base"], {"branch": f"gld/{DEP}", "sha": head41, "stacked_on": DEP})
        st = w.istate(MEMBER)
        self.assertEqual((st["mode"], st["base_sha"], st["base_branch"], st["draft"], st["sprint"]),
                         ("unattended", head41, f"gld/{DEP}", True, T))
        # TS1 for real: PR base gld/41, draft, the stack block; the change list has none of #41's files
        pr42 = w.pulls()[-1]
        self.assertEqual((pr42["base"], pr42["head"], pr42["draft"]), (f"gld/{DEP}", f"gld/{MEMBER}", True))
        self.assertIn(defaults.SPRINT_STACK_MARKER, pr42["body"])
        self.assertIn(defaults.SPRINT_STACK_MARKER_END, pr42["body"])
        self.assertIn(f"이 PR은 \uff03{DEP} 위에 있다", pr42["body"])          # the outbound layer's full-width number sign
        changed = w.repo.git("diff", "--name-only", f"gld/{DEP}", f"gld/{MEMBER}", cwd=w.repo.remote).split()
        self.assertIn("src/app.py", changed)
        self.assertIn("tests/test_bug.py", changed)
        self.assertFalse([f for f in changed if f == "tests/test_value.py" or f.startswith(f"docs/specs/{DEP}/")], changed)
        self.assertEqual(w.repo.git("merge-base", f"gld/{DEP}", f"gld/{MEMBER}", cwd=w.repo.remote).strip(), head41)
        # the sprint's own records: one base check (run 2 used the green record), each member started once per run
        log = w.sprint_log()
        starts = [(l["run"], l["issue"]) for l in log if l["event"] == "member-start"]
        self.assertEqual(starts, [(1, DEP), (2, MEMBER)])
        ends = {(l["run"], l["issue"]): (l["outcome"], l.get("block")) for l in log if l["event"] in ("member-end", "member-blocked")}
        self.assertEqual(ends, {(1, DEP): ("stopped", None), (1, MEMBER): ("blocked", "dep-stopped"),
                                (2, DEP): ("done", None), (2, MEMBER): ("done", None)})
        costs = {(l["run"], l["issue"]): l["data"]["cost_usd"] for l in log if l["event"] in ("member-end", "member-blocked")}
        self.assertIsNone(costs[(2, DEP)], "#41's run-1 and human costs are not counted again in run 2")
        self.assertGreater(costs[(2, MEMBER)], 0)
        self.assertEqual([l["data"]["ok"] for l in log if l["event"] == "base-check"], [True, True])
        self.assertEqual(len([f for f in os.listdir(os.path.dirname(pathsmod.base_green_record(self.w.home_real, REPO, main, "0" * 64)))
                              if f.endswith(".json")]), 1)
        # the report the retro reads
        p = w.cli("sprint", "report", "--repo", REPO, "--tracker", str(T), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = json.loads(p.stdout)
        self.assertEqual(rep["counts"], {"done": 2})
        # TX1: no session of the sprint switched the permission prompts off; the human's checkout never moved
        calls = w.claude_calls()
        self.assertEqual(len(calls), len(w.scenarios), "every scripted session ran, nothing more")
        for c in calls:
            self.assertNotIn(FLAG, c["argv"])
            if "--permission-mode" in c["argv"]:
                self.assertEqual(c["argv"][c["argv"].index("--permission-mode") + 1], "default")
        self.assertEqual(w.repo.git("rev-parse", "refs/heads/main").strip(), local_main)
        self.assertEqual(w.remote_sha("main"), main, "nothing merged")


if __name__ == "__main__":
    unittest.main()
