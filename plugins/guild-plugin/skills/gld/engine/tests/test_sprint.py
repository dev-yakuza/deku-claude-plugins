"""VA4 · VA5 — the supervisor with doubles for every seam (TR, TQ, TW, TL, TB; §5.2): a member engine is an exit code
plus the state.json it leaves, the clock and the sleep are injected, git is a double, records are real."""

import io
import json
import os
import signal
import sys
import tempfile
import time
import unittest

from gxengine import (basecheck, codes, defaults, github, gitops, lifecycle, paths as pathsmod, sprint, sprintdag,
                      sprinttracker, store)
from tests import c_world as W
from tests.helpers import fakes

REPO, T = "acme/app", 700
MAIN, DEP = "a" * 40, "b" * 40
CONFIG = b'{"format": 1}\n'
NOON = time.mktime((2026, 11, 25, 12, 0, 0, 0, 0, -1))
BAR = "\n|---|---|---|---|---|---|\n"


def table(rows, token="squash-sync", extra=""):
    """A tracker body with a correct plan hash. rows: (issue, base_dep or None, kind)."""
    lines = "".join(f"| {i} | #{n} | {'#%d' % d if d else '—'} | — | | {k} |\n" for i, (n, d, k) in enumerate(rows, 1))
    body = ("# Sprint\n\n<!-- guild:sprint:plan -->\nplan-hash: 000000000000\n- 상한 근거: " + token + "\n" + extra
            + "\n## 멤버\n| # | 이슈 | base 의존 | 원래 의존 | 비고 | 구분 |" + BAR + lines + "<!-- /guild:sprint:plan -->\n")
    return body.replace("plan-hash: 000000000000", "plan-hash: " + sprintdag.plan_hash(body))


def rows(*spec):
    """rows(101, (102, 101), 103) → goal members."""
    return [(s, None, "goal") if isinstance(s, int) else (s[0], s[1], "goal") for s in spec]


class Tracker:
    """sprinttracker's functions over a dict world."""

    def __init__(self, body):
        self.body, self.state, self.run = body, "OPEN", None
        self.issues, self.prs, self.remote, self.fail = {}, {}, {}, {}
        self.markers, self.red, self.settings, self.reads = [], [], {"merge": False, "squash": True, "rebase": False}, []

    def _fail(self, what):
        n = self.fail.get(what)
        if n is True or (isinstance(n, int) and n > 0):
            if n is not True:
                self.fail[what] = n - 1
            raise github.GhError(f"fake {what} failed")

    def read(self, gh, tracker):
        self._fail("read")
        return sprinttracker.Tracker(tracker, self.body, self.state, self.run)

    def write_marker(self, gh, tracker, comment_id, obj):
        self._fail("marker")
        self.markers.append((comment_id, json.loads(json.dumps(obj))))
        return 7001

    def merge_settings(self, gh):
        return self.settings

    def default_branch(self, gh):
        self._fail("default_branch")
        return "main"

    def issue_facts(self, gh, n):
        self._fail(("issue", n))
        self.reads.append(n)
        return dict({"number": n, "state": "OPEN", "state_reason": None, "labels": []}, **self.issues.get(n, {}))

    def dep_facts(self, gh, dep, local, outcome=None):
        i = self.issue_facts(gh, dep)
        self._fail(("dep", dep))
        return sprintdag.DepFacts(issue=dep, issue_state=i["state"], state_reason=i["state_reason"],
                                  prs=self.prs.get(dep, []), local=local, outcome=outcome)

    def remote_state(self, gh, n):
        self._fail(("remote", n))
        return self.remote.get(n, {"branch": False, "open_pr": None})

    def base_red_comment(self, gh, tracker, sha, red, problem):
        self._fail("red")
        self.red.append((red, problem))


class Git:
    """gitops' VA3 functions over {branch: sha}."""

    def __init__(self):
        self.heads, self.fetched, self.control, self.config, self.fail = {"main": MAIN}, [], {}, ("100644", "x", CONFIG), False

    def main_context(self, checkout, base_env=None):
        return "ctx"

    def fetch_branches(self, ctx, branches):
        self.fetched.append(list(branches))
        if self.fail or any(b not in self.heads for b in branches):
            raise gitops.GitError("fetch failed")
        return {b: self.heads[b] for b in branches}

    def control_changes(self, ctx, base, head, issue):
        return self.control.get(head, [])

    def blob(self, ctx, sha, path):
        return self.config

    is_regular_mode = staticmethod(gitops.is_regular_mode)


def state(issue, done=True, stop=None, pr=None, closed=None, mode="unattended", running=False, **over):
    st = {"format": 1, "issue": issue, "revision": 1, "last_head": MAIN, "repo": REPO, "mode": mode, "base_sha": MAIN,
          "steps": [{"id": "analyze", "status": "done", "latest_attempt": 1},
                    {"id": "pr", "status": "done" if done else ("running" if running else "pending"),
                     "latest_attempt": 1 if done or running else None}],
          "github": {"summary_comment_id": None, "engine_comment_ids": [], "last_seen_comment_id": None,
                     "pr_number": pr, "pr_url": None},
          "totals": {"attempts": 1, "cost_usd": 1.5, "leader_calls": 0, "warnings": 0}, "stop": None}
    if stop is not None:
        st["stop"] = dict({"status": "needs_human", "reason": "blocked", "step": "pr", "attempt": 1,
                           "at": "2026-11-25T01:02:03Z", "note": "n"}, **stop)
    if closed:
        st["closed"] = {"reason": "completed", "comment_id": 1, "at": "2026-11-25T01:02:03Z"}
    st.update(over)
    return st


class Case(unittest.TestCase):
    ROWS = rows(101, (102, 101), 103)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = os.path.realpath(self._tmp.name)
        self.home = os.path.join(self.tmp, "eng")
        self.plugin = os.path.join(self.tmp, "plugin")
        os.makedirs(os.path.join(self.plugin, "skills", "gld", "engine"))
        os.makedirs(os.path.join(self.plugin, ".claude-plugin"))
        self.write_plugin("x = 1\n")
        with open(os.path.join(self.plugin, ".claude-plugin", "plugin.json"), "w") as f:
            f.write('{"version": "9.9.9"}')
        self.env = fakes.fake_env(base={"PATH": os.environ.get("PATH", ""), "HOME": self.tmp})
        self.tracker, self.git = Tracker(table(self.ROWS)), Git()
        self.sp = pathsmod.SprintPaths(self.home, REPO, T)
        self.script, self.spawned, self.slept, self.t = {}, [], [], NOON
        self.base, self.base_requests, self.check_ok, self.checks = basecheck.BaseCheckResult(True, record="/x/r.json"), [], (True, ""), 0
        self.out = io.StringIO()

    def write_plugin(self, text):
        with open(os.path.join(self.plugin, "skills", "gld", "engine", "engine.py"), "w") as f:
            f.write(text)

    # a member engine: script[issue] = list of (rc, state or None or callable) per start, the last repeats
    def spawn(self, argv, *, log_file, rc_file, env, cwd, on_tick):
        tail = argv[argv.index("-I") + 2:]
        issue = int(tail[tail.index("--issue") + 1])
        n = sum(1 for i, _ in self.spawned if i == issue)
        self.spawned.append((issue, tail))
        seq = self.script.get(issue) or [(0, state(issue, pr=900 + issue))]
        act = seq[min(n, len(seq) - 1)]
        if callable(act):
            act = act(on_tick)
        rc, st = act
        if st is not None:
            if "--base-sha" in tail:                      # what the engine records at a start (VA3)
                st = dict(st, base_sha=tail[tail.index("--base-sha") + 1], base_branch=tail[tail.index("--base-branch") + 1],
                          draft="--draft" in tail, sprint=T)
            self.save(st)
        return rc

    def save(self, st):
        store.save_state(pathsmod.EnginePaths(self.home, REPO, st["issue"]), st)
        if st["github"]["pr_number"]:
            self.tracker.prs[st["issue"]] = [{"number": st["github"]["pr_number"], "state": "OPEN", "head_sha": DEP, "base": "main"}]
            self.git.heads[f"gld/{st['issue']}"] = DEP

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds

    def units(self, **over):
        def base_check(req):
            self.base_requests.append(req)
            return self.base

        def self_check():
            self.checks += 1
            return self.check_ok
        kw = dict(spawn_member=self.spawn, base_check=base_check, tracker=self.tracker, git=self.git, self_check=self_check,
                  now=lambda: self.t, sleep=self.sleep)
        kw.update(over)
        return sprint.SprintUnits(**kw)

    def run_sprint(self, units=None, **over):
        kw = dict(repo=REPO, tracker=T, checkout=self.tmp, plugin_root=self.plugin, engine_home=self.home, environ=self.env,
                  out=self.out, window=None, allow_red_base=False, take_over=False, srt="/usr/bin/true", user_tmp=None, stage=4)
        kw.update(over)
        self.rc = sprint.run(sprint.SprintOptions(**kw), units or self.units())
        self.assertIsNone(lifecycle.sprint_lock_holder(self.sp), "the sprint locks are released")
        return self.rc

    @property
    def s(self):
        return store.load_sprint(self.sp)

    def outcomes(self):
        return {m["issue"]: m["block"] or m["outcome"] for m in self.s["members"]}

    def row(self, issue):
        return next(m for m in self.s["members"] if m["issue"] == issue)

    def started(self):
        return [i for i, _ in self.spawned]

    def log(self, event=None):
        return [l for l in store.read_sprint_log(self.sp) if event is None or l["event"] == event]

    def finished_ok(self):
        self.assertEqual((self.rc, self.s["state"]), (0, "finished"), self.out.getvalue())

    def halted(self, why):
        self.assertEqual((self.rc, self.s["state"], self.s["halt"]), (4, "halted", why), self.out.getvalue())
        self.assertEqual(self.log("halt")[-1]["halt"], why)

    def hold(self, path, issue):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"format": 1, "pid": os.getpid(), "started": lifecycle.process_start(os.getpid()), "issue": issue}, f)


class Round(Case):
    """TR."""

    def test_all_done(self):
        """TR1."""
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes(), {101: "done", 102: "done", 103: "done"})
        self.assertEqual(self.started(), [101, 102, 103])
        last = self.tracker.markers[-1][1]
        self.assertEqual(last, self.s, "the marker is written from the last sprint.json")
        self.assertEqual([c for c, _ in self.tracker.markers][:2], [None, 7001], "one comment")
        s = self.s
        self.assertEqual((s["run"], s["plugin_version"], s["pid"], s["stack_reason"]), (1, "9.9.9", os.getpid(), "squash-sync"))
        self.assertIsNotNone(s["ended"])
        self.assertEqual(self.row(101)["base"], {"branch": "main", "sha": MAIN, "stacked_on": None})
        self.assertEqual((self.row(101)["pr"], self.row(101)["rc"], self.row(101)["cost_usd"]), (1001, 0, 1.5))
        self.assertEqual([l["event"] for l in self.log()], ["sprint-start", "base-check"] + ["member-start", "member-end"] * 3 + ["sprint-end"])
        self.assertEqual(self.log("sprint-end")[0]["data"]["counts"], {"done": 3})

    def test_the_child_command(self):
        """H1, H6: the same engine command a human starts, in the foreground, unattended, on the fetched base."""
        self.run_sprint()
        self.assertEqual(self.spawned[0][1], [
            "dev", "--repo", REPO, "--issue", "101", "--mode", "unattended", "--checkout", self.tmp, "--foreground",
            "--base-sha", MAIN, "--base-branch", "main", "--sprint", "700"])
        self.assertEqual(self.spawned[1][1][-7:], ["--base-sha", DEP, "--base-branch", "gld/101", "--draft", "--sprint", "700"])
        self.assertFalse([a for _, tail in self.spawned for a in tail if "dangerous" in a or "skip-perm" in a])
        self.assertEqual((self.row(102)["draft"], self.row(102)["base"]), (True, {"branch": "gld/101", "sha": DEP, "stacked_on": 101}))

    def test_a_stop_blocks_its_dependants_only(self):
        """TR2, TD4."""
        self.tracker.body = table(rows(101, (102, 101), (104, 102), 103))
        self.script[101] = [(10, state(101, done=False, stop={}))]
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes(), {101: "stopped", 102: "dep-stopped", 104: "upstream", 103: "done"})
        self.assertEqual(self.started(), [101, 103])
        self.assertEqual((self.row(102)["cause"], self.row(104)["cause"]), (101, 101), "the root cause")
        self.assertEqual((self.row(101)["stop_reason"], self.row(101)["rc"]), ("blocked", 10))
        self.assertEqual(self.log("member-blocked")[0]["cause"], 101)

    def test_every_line_of_the_outcome_table(self):
        """TR3."""
        quota = {"reason": "infra-stop", "detail": "quota", "reset_at": NOON + 99999}
        for rc, st, want in (
                (0, state(101, pr=5), ("done", None)),
                (0, state(101, done=False, closed=True), ("closed", None)),
                (0, state(101), ("failed", None)),                                            # no pull request
                (0, state(101, done=False, pr=5), ("failed", None)),                          # steps left
                (0, state(101, done=False, pr=5, stop={}), ("failed", None)),
                (0, None, ("failed", None)),
                (10, state(101, done=False, stop={}), ("stopped", None)),
                (11, state(101, done=False, stop={"status": "needs_leader", "reason": "plan-gate"}), ("stopped", None)),
                (10, state(101, done=False, stop=quota), ("blocked", "quota")),
                (11, state(101, done=False, stop=dict(quota, status="needs_leader", reason="plan-gate")), ("blocked", "quota")),
                (10, state(101, done=False, stop={"reason": "infra-stop", "detail": "api", "reset_at": None, "note": "quota"}), ("stopped", None)),
                (10, None, ("failed", None)), (10, state(101, done=False), ("failed", None)),
                (4, None, ("refused", None)), (4, state(101, pr=5), ("refused", None)),
                (1, state(101, pr=5), ("failed", None)), (-9, state(101, done=False, running=True), ("failed", None)),
                (127, None, ("failed", None)), (2, None, ("failed", None)), (3, None, ("failed", None))):
            with self.subTest(rc=rc, want=want):
                self.assertEqual(sprint.judge(rc, st), want)

    def test_a_run_again_starts_only_what_is_not_done(self):
        """TR4: stopped → a human resumes it (its state is finished) → the blocked member starts; nothing twice."""
        self.script[101] = [(10, state(101, done=False, stop={}))]
        self.run_sprint()
        self.save(state(101, pr=1001))
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.started(), [101, 103, 102])
        self.assertEqual(self.outcomes(), {101: "done", 102: "done", 103: "done"})
        self.assertEqual(self.s["run"], 2)
        self.assertEqual({l["run"] for l in self.log("member-end") if l["issue"] == 102}, {2})

    def test_a_stopped_member_is_not_started_again(self):
        self.save(state(101, done=False, stop={"reason": "irreversible-change"}))
        self.run_sprint()
        self.assertEqual((self.outcomes()[101], self.row(101)["stop_reason"]), ("stopped", "irreversible-change"))
        self.assertEqual(self.started(), [103])

    def test_a_dead_member_is_failed_and_continued_without_an_answer(self):
        """TR5 (S9)."""
        self.script[101] = [(-9, state(101, done=False, running=True)), (0, state(101, pr=1001))]
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "failed", 102: "dep-failed", 103: "done"})
        self.run_sprint()
        self.assertEqual(self.spawned[-2][1], ["dev", "--repo", REPO, "--issue", "101", "--mode", "unattended", "--checkout",
                                               self.tmp, "--foreground"], "no answer, no start input")
        self.assertEqual(self.outcomes(), {101: "done", 102: "done", 103: "done"})

    def test_member_end_costs_are_this_runs_own(self):
        """VZ (B's note): member-end data.cost_usd is what this run's child engines spent, so the sprint table of
        collect.py never counts an earlier run again; the row keeps the Issue's total."""
        def cost(st, usd):
            st["totals"] = dict(st["totals"], cost_usd=usd)
            return st
        self.script[101] = [(-9, cost(state(101, done=False, running=True), 1.5)), (0, cost(state(101, pr=1001), 4.0))]
        self.run_sprint()
        self.run_sprint()
        ends = {(l["run"], l["issue"]): l["data"]["cost_usd"] for l in self.log() if l["event"] in ("member-end", "member-blocked")}
        self.assertEqual(ends, {(1, 101): 1.5, (1, 102): None, (1, 103): 1.5, (2, 101): 2.5, (2, 102): 1.5, (2, 103): None})
        self.assertEqual((self.row(101)["cost_usd"], self.row(103)["cost_usd"]), (4.0, 1.5), "sprint.json: the Issue's total")

    def test_a_boundary_stop_halts(self):
        """TR6 (H11)."""
        for reason in codes.BOUNDARY_STOPS:
            with self.subTest(reason=reason):
                self.setUp()
                self.script[101] = [(10, state(101, done=False, stop={"reason": reason}))]
                self.run_sprint()
                self.halted("boundary")
                self.assertEqual(self.started(), [101])
                self.assertEqual(self.outcomes(), {101: "stopped", 102: None, 103: None})

    def test_a_refused_self_check_halts_by_its_log_code(self):
        """D3: exit 4 says nothing; the code of the last refused line of THIS start does."""
        def refuse(code, **data):
            def act(on_tick):
                paths = pathsmod.EnginePaths(self.home, REPO, 101)
                store.append_log(paths, "stop", to="needs_human", code=code, note="srt", data=dict({"refused": True}, **data))
                return 4, None
            return act
        self.script[101] = [refuse("self-check-failed")]
        self.run_sprint()
        self.halted("boundary")
        self.assertEqual((self.outcomes()[101], self.row(101)["stop_reason"]), ("refused", "self-check-failed"))
        self.setUp()
        self.script[101] = [refuse("stable-label")]
        self.run_sprint()
        self.finished_ok()
        self.assertEqual((self.row(101)["stop_reason"], self.outcomes()[102], self.outcomes()[103]), ("stable-label", "dep-failed", "done"))
        self.setUp()
        store.append_log(pathsmod.EnginePaths(self.home, REPO, 101), "stop", code="self-check-failed", data={"refused": True})
        self.script[101] = [(4, None)]
        self.run_sprint()
        self.finished_ok()
        self.assertIsNone(self.row(101)["stop_reason"], "an earlier start's refusal is not this one's")

    def test_the_self_check_runs_once_before_anything(self):
        self.check_ok = (False, "srt is not installed")
        self.run_sprint()
        self.halted("boundary")
        self.assertEqual((self.started(), self.base_requests, self.checks), ([], [], 1))

    def test_a_killed_supervisor(self):
        """TR7: dead locks, sprint.json still `running`, one member finished, one whose engine still runs."""
        self.run_sprint()
        dead = dict(self.s, state="running", ended=None)
        store.save_sprint(self.sp, dead)
        for path in (self.sp.lock, self.sp.repo_lock):
            with open(path, "w") as f:
                json.dump({"format": 1, "pid": 999999, "started": "x", "issue": T}, f)
        os.unlink(pathsmod.EnginePaths(self.home, REPO, 103).state)
        self.hold(pathsmod.EnginePaths(self.home, REPO, 103).lock, 103)
        self.tracker.run = {"id": 7001, "data": {"host": sprint.host_name(), "state": "running"}}
        self.spawned.clear()
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes(), {101: "done", 102: "done", 103: "skipped-locked"})
        self.assertEqual(self.started(), [], "nothing is started twice")

    def test_term_ends_after_the_running_member(self):
        """TR8."""
        def act(on_tick):
            os.kill(os.getpid(), signal.SIGTERM)
            on_tick()
            return 0, state(101, pr=1001)
        self.script[101] = [act]
        before = signal.getsignal(signal.SIGTERM)
        self.run_sprint()
        self.halted("signal")
        self.assertEqual(self.outcomes(), {101: "done", 102: None, 103: None})
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_three_failed_markers_halt_but_the_member_ends(self):
        """TR9."""
        def act(on_tick):
            self.tracker.fail["marker"] = True
            for _ in range(4):
                self.t += defaults.SPRINT_MARKER_EVERY_S
                on_tick()
            return 0, state(101, pr=1001)
        self.script[101] = [act]
        self.run_sprint()
        self.halted("marker-unwritable")
        self.assertEqual(self.outcomes(), {101: "done", 102: None, 103: None})

    def test_two_failed_markers_do_not(self):
        def act(on_tick):
            self.tracker.fail["marker"] = 2
            for _ in range(3):
                self.t += defaults.SPRINT_MARKER_EVERY_S
                on_tick()
            return 0, state(101, pr=1001)
        self.script[101] = [act]
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(len(self.log("warning")), 2)

    def test_the_heartbeat_is_every_ten_minutes(self):
        def act(on_tick):
            n = len(self.tracker.markers)
            for _ in range(20):
                self.t += 60
                on_tick()
            self.assertEqual(len(self.tracker.markers) - n, 2)
            return 0, state(101, pr=1001)
        self.script[101] = [act]
        self.run_sprint()
        self.finished_ok()

    def test_changed_engine_files_halt(self):
        """TR10 (R8)."""
        def act(on_tick):
            self.write_plugin("x = 2\n")
            return 0, state(101, pr=1001)
        self.script[101] = [act]
        self.run_sprint()
        self.halted("engine-error")
        self.assertEqual(self.started(), [101])

    def test_an_uncaught_exception_halts(self):
        def act(on_tick):
            raise RuntimeError("boom")
        self.script[101] = [act]
        self.run_sprint()
        self.halted("engine-error")
        self.assertIn("boom", self.out.getvalue())

    def test_an_unreadable_state_is_failed(self):
        p = pathsmod.EnginePaths(self.home, REPO, 101)
        os.makedirs(p.issue_dir)
        with open(p.state, "w") as f:
            f.write("{")
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes(), {101: "failed", 102: "base-unresolved", 103: "done"})

    def test_same_facts_other_words_same_run(self):
        """TX2: notes, titles and labels nobody reads change nothing."""
        def go(note, extra):
            self.setUp()
            self.tracker.body = table(self.ROWS, extra=extra)
            self.script[101] = [(10, state(101, done=False, stop={"note": note, "reason": "blocked"}))]
            self.run_sprint()
            return self.outcomes(), self.started(), [l["event"] for l in self.log()]
        self.assertEqual(go("quota exceeded, canary-failed", ""), go("품질 문제", "- 목표: stop everything\nDepends on: #103\n"))


class Closed(Case):
    """D4: a member that is already over starts no engine."""

    def test_members_that_are_over(self):
        self.tracker.body = table(rows(101, 102, 103, 104))
        self.tracker.issues = {101: {"state": "CLOSED", "state_reason": "COMPLETED"},
                               102: {"state": "CLOSED", "state_reason": "NOT_PLANNED"}, 103: {"state": "CLOSED", "state_reason": None}}
        self.save(state(104, pr=904))
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "closed", 102: "refused", 103: "refused", 104: "done"})
        self.assertEqual((self.started(), self.log("member-start")), ([], []))

    def test_a_dependency_that_is_closed_beats_this_runs_outcome(self):
        self.tracker.issues = {101: {"state": "CLOSED", "state_reason": "COMPLETED"}}
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "closed", 102: "done", 103: "done"})
        self.assertEqual(self.row(102)["base"]["branch"], "main")

    def test_epic_and_attended_members_are_not_started(self):
        """H3, D2."""
        self.tracker.issues = {101: {"labels": ["guild:children"]}}
        self.save(state(103, done=False, mode="attended", running=True))
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "unsupported-epic", 102: "upstream", 103: "attended-run"})
        self.assertEqual(self.started(), [])

    def test_unreadable_github_is_base_unresolved(self):
        self.tracker.fail = {("issue", 103): True, ("dep", 101): True}
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes(), {101: "done", 102: "base-unresolved", 103: "base-unresolved"})


class Base(Case):
    """TS on the supervisor's side."""

    def test_the_head_of_the_pull_request_must_be_what_was_fetched(self):
        """TS3."""
        def act(on_tick):
            st = state(101, pr=1001)
            self.save(st)
            self.git.heads["gld/101"] = "c" * 40
            return 0, None
        self.script[101] = [act]
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "done", 102: "base-unresolved", 103: "done"})

    def test_a_control_file_in_the_stack_base(self):
        """D1."""
        self.git.control[DEP] = [".claude/agents/qa.md"]
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "done", 102: "base-unresolved", 103: "done"})
        self.assertIn(".claude/agents/qa.md", self.out.getvalue())

    def test_a_merged_dependency(self):
        """TS2: the new default branch commit."""
        def act(on_tick):
            self.save(state(101, pr=1001))
            self.tracker.prs[101] = [{"number": 1001, "state": "MERGED", "head_sha": DEP, "base": "main"}]
            self.git.heads["main"] = "d" * 40
            return 0, None
        self.script[101] = [act]
        self.run_sprint()
        self.assertEqual(self.row(102)["base"], {"branch": "main", "sha": "d" * 40, "stacked_on": None})

    def test_no_stacking_here(self):
        """TS5: the settings are unknown, the human declined stacks, the plan is older than the settings."""
        for token, settings, want in (("squash-sync", None, "dep-unmerged"), ("merge-commit-forbidden", {"merge": True, "squash": True, "rebase": True}, "dep-unmerged"),
                                      ("config", {"merge": False, "squash": True, "rebase": False}, "dep-unmerged"),
                                      ("config", {"merge": True, "squash": True, "rebase": False}, "done")):
            with self.subTest(token=token, settings=settings):
                self.setUp()
                self.tracker.body, self.tracker.settings = table(self.ROWS, token), settings
                self.run_sprint()
                self.assertEqual(self.outcomes()[102], want)
        self.assertNotIn("--draft", self.spawned[1][1], "merge commits allowed: a plain stacked PR")

    def test_a_remote_branch(self):
        """TS6."""
        self.tracker.remote = {101: {"branch": True, "open_pr": None}, 103: {"branch": False, "open_pr": 8}}
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "remote-branch-exists", 102: "upstream", 103: "remote-branch-exists"})
        self.assertEqual(self.started(), [])

    def test_a_failed_fetch(self):
        def act(on_tick):
            self.git.fail = True
            return 0, state(101, pr=1001)
        self.script[101] = [act]
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "done", 102: "base-unresolved", 103: "base-unresolved"})


class Locks(Case):
    """TL1–TL3."""

    def test_a_member_a_human_runs(self):
        self.hold(pathsmod.EnginePaths(self.home, REPO, 101).lock, 101)
        self.save(state(101, done=False, mode="attended", running=True))
        self.run_sprint()
        self.assertEqual(self.outcomes(), {101: "skipped-locked", 102: "dep-stopped", 103: "done"})
        self.assertEqual(self.started(), [103])

    def test_exit_3_with_this_issues_lock(self):
        def act(on_tick):
            self.hold(pathsmod.EnginePaths(self.home, REPO, 101).lock, 101)
            return 3, None
        self.script[101] = [act]
        self.run_sprint()
        self.assertEqual((self.outcomes()[101], self.row(101)["rc"], self.row(101)["started"]), ("skipped-locked", None, None))

    def repo_lock(self):
        return lifecycle.repo_lock_path(pathsmod.EnginePaths(self.home, REPO, 101))

    def test_another_issue_holds_the_repository(self):
        """TL2 (H5)."""
        self.hold(self.repo_lock(), 55)

        def sleep(seconds):
            self.sleep(seconds)
            if len(self.slept) == 3:
                os.unlink(self.repo_lock())
        self.run_sprint(self.units(sleep=sleep))
        self.finished_ok()
        self.assertEqual(self.slept, [defaults.SPRINT_POLL_S] * 3)
        self.assertEqual(self.outcomes(), {101: "done", 102: "done", 103: "done"})
        self.assertEqual(self.log("wait")[0]["data"]["for"], "repo-lock")
        self.assertEqual(len(self.log("wait")), 1)

    def test_four_hours_is_repo_busy(self):
        self.hold(self.repo_lock(), 55)
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes(), {101: "repo-busy", 102: "upstream", 103: "repo-busy"})
        self.assertEqual(sum(self.slept), 2 * defaults.SPRINT_REPO_BUSY_MAX_S)

    def test_a_lock_that_is_already_gone_is_tried_at_once(self):
        self.script[101] = [(3, None), (0, state(101, pr=1001))]
        self.run_sprint()
        self.assertEqual((self.outcomes()[101], self.slept, self.started()), ("done", [], [101, 101, 102, 103]))
        self.setUp()
        self.script[101] = [(3, None), (3, None), (0, state(101, pr=1001))]
        self.run_sprint()
        self.assertEqual(self.slept, [defaults.SPRINT_POLL_S], "twice: no busy loop")

    def test_a_second_supervisor(self):
        """TL3."""
        os.makedirs(self.sp.dir)
        self.hold(self.sp.repo_lock, 701)
        kw = dict(repo=REPO, tracker=T, checkout=self.tmp, plugin_root=self.plugin, engine_home=self.home, environ=self.env,
                  out=self.out, window=None, allow_red_base=False, take_over=False, srt="/x", user_tmp=None, stage=4)
        self.assertEqual(sprint.run(sprint.SprintOptions(**kw), self.units()), 3)
        self.assertEqual((self.tracker.markers, self.started(), self.s), ([], [], None))

    def test_another_host(self):
        for data in ({"host": "other-mac", "state": "running"}, {"host": "other-mac", "state": "waiting-for-window"}, None, {}):
            with self.subTest(data=data):
                self.setUp()
                self.tracker.run = {"id": 5, "data": data}
                self.run_sprint()
                self.halted("other-host")
                self.assertEqual((self.tracker.markers, self.started()), ([], []), "the other run's marker is not touched")
                self.run_sprint(take_over=True)
                self.finished_ok()
                self.assertEqual(self.tracker.markers[0][0], 5)
        for state_text in ("finished", "halted:signal"):
            self.setUp()
            self.tracker.run = {"id": 5, "data": {"host": "other-mac", "state": state_text}}
            self.run_sprint()
            self.finished_ok()


class Start(Case):
    def test_refused_before_anything_is_written(self):
        cyc = table(rows((101, 102), (102, 101)))
        for what in ("cycle", "table", "read", "closed", "window", "stage"):
            with self.subTest(what=what):
                self.setUp()
                kw = {}
                if what == "cycle":
                    self.tracker.body = cyc
                elif what == "table":
                    self.tracker.body = "no table"
                elif what == "read":
                    self.tracker.fail["read"] = True
                elif what == "closed":
                    self.tracker.state = "CLOSED"
                elif what == "window":
                    kw["window"] = "9:00-10:00"
                else:
                    kw["stage"] = 3
                self.assertEqual(self.run_sprint(**kw), 4)
                self.assertIn("refused", self.out.getvalue())
                self.assertEqual((self.s, self.tracker.markers, self.started(), self.log()), (None, [], [], []))

    def test_plan_hash(self):
        for body in (table(self.ROWS).replace("상한 근거: squash-sync", "상한 근거: config"),
                     "\n".join(l for l in table(self.ROWS).split("\n") if not l.startswith("plan-hash"))):
            self.setUp()
            self.tracker.body = body
            self.run_sprint()
            self.halted("plan-hash-mismatch")
            self.assertEqual((self.started(), self.base_requests), ([], []))
            self.assertEqual(self.tracker.markers[-1][1]["halt"], "plan-hash-mismatch")

    def test_a_dependency_outside_the_table_is_warned_and_dropped(self):
        self.tracker.body = table(rows((101, 99)))
        self.run_sprint()
        self.finished_ok()
        self.assertIn("#99", self.log("warning")[0]["note"])
        self.assertEqual((self.row(101)["base"]["branch"], self.row(101)["base_dep"]), ("main", 99))

    def test_the_order_is_the_tables(self):
        self.tracker.body = table([(103, None, "other"), (105, None, "slot"), (104, 103, "goal")])
        self.run_sprint()
        self.assertEqual(self.started(), [105, 103, 104])


class Quota(Case):
    """TQ."""
    RESET = NOON + 5 * 3600

    def stop(self, **over):
        return dict({"reason": "infra-stop", "detail": "quota", "reset_at": self.RESET}, **over)

    def test_a_member_that_waits_inside_is_done(self):
        """TQ1: the wait is the member engine's; the supervisor shows it."""
        def act(on_tick):
            paths = pathsmod.EnginePaths(self.home, REPO, 101)
            store.append_log(paths, "wait", data={"seconds": 3600})
            self.t += defaults.SPRINT_MARKER_EVERY_S
            on_tick()
            self.assertEqual(self.tracker.markers[-1][1]["state"], "waiting-for-quota")
            store.append_log(paths, "engine-exit", data={"rc": 0})
            return 0, state(101, pr=1001)
        self.script[101] = [act]
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes()[101], "done")

    def test_past_four_hours_the_whole_run_waits(self):
        """TQ2."""
        self.script[101] = [(10, state(101, done=False, stop=self.stop()))]
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes(), {101: "quota", 102: "upstream", 103: "quota"})
        self.assertEqual((self.started(), self.s["quota_reset_at"]), ([101], self.RESET))
        self.assertEqual((self.row(101)["stop_reason"], self.row(101)["stop_detail"], self.row(103)["stop_reason"]), ("infra-stop", "quota", None))
        self.assertEqual(self.log("sprint-end")[0]["data"]["counts"], {"blocked": 3})

    def test_a_done_member_stays_done(self):
        self.save(state(103, pr=903))
        self.script[101] = [(10, state(101, done=False, stop=self.stop()))]
        self.run_sprint()
        self.assertEqual(self.outcomes()[103], "done")

    def test_without_a_reset_time_nothing_else_starts(self):
        self.script[101] = [(10, state(101, done=False, stop=self.stop(reset_at=None)))]
        self.run_sprint()
        self.assertEqual((self.outcomes()[103], self.started()), ("quota", [101]))
        self.run_sprint()
        self.assertEqual(self.outcomes()[101], "stopped", "no reset time: a human's")

    def test_the_next_run_after_the_reset_reruns_it(self):
        """TQ3 (H8)."""
        self.script[101] = [(10, state(101, done=False, stop=self.stop())), (0, state(101, pr=1001))]
        self.run_sprint()
        self.t = self.RESET + 1
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.spawned[1][1], ["resume", "--repo", REPO, "--issue", "101", "--foreground", "--answer", "rerun",
                                              "--sprint", "700"])
        self.assertEqual(self.log("member-start")[1]["data"]["rerun"], True)
        self.assertEqual(self.outcomes(), {101: "done", 102: "done", 103: "done"})

    def test_the_next_run_before_the_reset_starts_nothing(self):
        """TQ4."""
        self.save(state(101, done=False, stop=self.stop()))
        self.run_sprint()
        self.assertEqual((self.outcomes(), self.started()), ({101: "quota", 102: "upstream", 103: "quota"}, []))

    def test_a_leader_quota_stop_is_called_again_without_an_answer(self):
        self.save(state(101, done=False, stop=self.stop(status="needs_leader", reason="plan-gate")))
        self.run_sprint()
        self.assertEqual(self.outcomes()[101], "quota")
        self.t = self.RESET + 1
        self.run_sprint()
        self.assertEqual(self.spawned[0][1][0], "dev")
        self.assertNotIn("--answer", self.spawned[0][1])
        self.assertEqual(self.outcomes()[101], "done")

    def test_another_stop_is_never_rerun(self):
        """TQ5."""
        for stop in ({"reason": "infra-stop", "detail": "api", "reset_at": None, "note": "quota"},
                     {"reason": "infra-stop", "note": "quota"}, {"reason": "blocked", "note": "quota"}):
            self.setUp()
            self.save(state(101, done=False, stop=stop))
            self.run_sprint()
            self.assertEqual((self.outcomes()[101], 101 in self.started()), ("stopped", False))

    def test_a_boundary_stop_of_an_earlier_run_is_only_a_stop(self):
        self.save(state(101, done=False, stop={"reason": "canary-failed"}))
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.outcomes(), {101: "stopped", 102: "dep-stopped", 103: "done"})


class Window(Case):
    """TW3, TW4."""

    def at(self, text):
        h, m = map(int, text.split(":"))
        return time.mktime((2026, 11, 25, h, m, 0, 0, 0, -1))

    def test_waits_only_before_a_new_member(self):
        self.t = self.at("21:58")

        def act(on_tick):
            self.t = self.at("23:30")                         # the window closes while it runs
            return 0, state(101, pr=1001)
        self.script[101] = [act]
        starts = []

        def spawn(argv, **kw):
            starts.append(time.strftime("%H:%M", time.localtime(self.t)))
            return self.spawn(argv, **kw)
        self.tracker.body = table(rows(101, 103))
        self.run_sprint(self.units(spawn_member=spawn), window="22:00~23:00")
        self.finished_ok()
        self.assertEqual(starts, ["22:00", "22:00"], "two evenings")
        self.assertEqual([l["data"] for l in self.log("wait")], [{"for": "window", "until": "22:00"}] * 2)
        self.assertEqual(self.s["window"], "22:00-23:00")
        self.assertIn("waiting-for-window", [m["state"] for _, m in self.tracker.markers])

    def test_a_quota_stop_does_not_wait_for_the_next_window(self):
        self.t = self.at("22:30")

        def act(on_tick):
            self.t = self.at("23:30")
            return 10, state(101, done=False, stop={"reason": "infra-stop", "detail": "quota", "reset_at": self.t + 9 * 3600})
        self.script[101] = [act]
        self.run_sprint(window="22:00-23:00")
        self.finished_ok()
        self.assertEqual((self.slept, self.outcomes()), ([], {101: "quota", 102: "upstream", 103: "quota"}))

    def test_the_base_check_comes_before_the_wait(self):
        self.t = self.at("12:00")
        self.base = basecheck.BaseCheckResult(False, red=["test"])
        self.run_sprint(window="22:00-23:00")
        self.halted("base-red")
        self.assertEqual(self.slept, [])

    def test_a_run_again_inherits_the_window(self):
        self.t = self.at("22:30")
        self.run_sprint(window="22:00-10:00")
        self.run_sprint()
        self.assertEqual(self.s["window"], "22:00-10:00")
        self.run_sprint(window="none")
        self.assertIsNone(self.s["window"])

    def test_a_signal_while_waiting(self):
        self.t = self.at("12:00")

        def sleep(seconds):
            self.sleep(seconds)
            if len(self.slept) == 2:
                os.kill(os.getpid(), signal.SIGHUP)
        self.run_sprint(self.units(sleep=sleep), window="22:00-23:00")
        self.halted("signal")
        self.assertEqual((self.started(), len(self.slept)), ([], 2))

    def test_eighteen_failed_markers_while_waiting(self):
        self.t = self.at("12:00")
        real = self.sleep

        def sleep(seconds):
            self.tracker.fail["marker"] = True
            real(seconds)
        self.run_sprint(self.units(sleep=sleep), window="22:00-23:00")
        self.halted("marker-unwritable")
        self.assertEqual(len(self.log("warning")), defaults.SPRINT_MARKER_FAILS_MAX_WINDOW + 1, "+ the last try at the end")


class BaseCheck(Case):
    """TB on the supervisor's side (H12)."""

    def test_the_request_and_the_record(self):
        self.run_sprint()
        r = self.base_requests[0]
        self.assertEqual((r.repo, r.sha, r.config_text, r.checkout, r.force), (REPO, MAIN, CONFIG.decode(), self.tmp, False))
        self.assertEqual(len(self.base_requests), 1, "once per run, not per member")
        self.assertEqual((self.s["base_check"]["ok"], self.s["base_check"]["record"], self.s["base_check"]["sha"]), (True, "r.json", MAIN))
        self.assertEqual(self.git.fetched[0], ["main"])
        self.assertEqual(self.log("base-check")[0]["data"], {"sha": MAIN, "ok": True, "red": [], "flaky": []})

    def test_red_starts_nothing(self):
        """TB2."""
        self.base = basecheck.BaseCheckResult(False, red=["test", "lint"], record="/x/r.json")
        self.run_sprint()
        self.halted("base-red")
        self.assertEqual((self.started(), self.tracker.red), ([], [(["test", "lint"], None)]))
        self.assertEqual(self.outcomes(), {101: None, 102: None, 103: None})

    def test_flaky_goes_on(self):
        self.base = basecheck.BaseCheckResult(True, flaky=["test"], record="/x/r.json")
        self.run_sprint()
        self.finished_ok()
        self.assertEqual(self.log("base-check")[0]["data"]["flaky"], ["test"])

    def test_a_human_may_allow_a_red_base(self):
        """TB5: members are judged as ever."""
        self.base = basecheck.BaseCheckResult(False, red=["test"], record="/x/r.json")
        self.script[101] = [(10, state(101, done=False, stop={"reason": "base-red"}))]
        self.run_sprint(allow_red_base=True)
        self.finished_ok()
        self.assertEqual((self.outcomes()[101], self.row(101)["stop_reason"], self.s["allow_red_base"], self.s["base_check"]["ok"]),
                         ("stopped", "base-red", True, False))

    def test_a_fact_that_could_not_be_collected_is_never_allowed(self):
        """TB4."""
        for problem, halt in (("worktree", "base-red"), ("prepare", "base-red"), ("engine-error", "base-red"), ("srt-canary", "boundary")):
            for allow in (False, True):
                self.setUp()
                self.base = basecheck.BaseCheckResult(False, problem=problem)
                self.run_sprint(allow_red_base=allow)
                self.halted(halt)
                self.assertEqual(self.started(), [])
        for prepare in ("config", "fetch", "branch"):
            self.setUp()
            if prepare == "config":
                self.git.config = None
            elif prepare == "fetch":
                self.git.fail = True
            else:
                self.tracker.fail["default_branch"] = True
            self.run_sprint(allow_red_base=True)
            self.halted("base-red")
            self.assertEqual(self.base_requests, [])

    def test_an_exception_of_the_check_halts(self):
        def boom(req):
            raise RuntimeError("boom")
        self.run_sprint(self.units(base_check=boom))
        self.halted("engine-error")


class Reports(Case):
    def run_stopped(self):
        self.tracker.body = table(rows(101, (102, 101), 103))
        calls = [{"k": 1, "kind": "check", "situation": "plan-gate", "answer": "plan", "reason": "fits-template", "step": None,
                  "note": "", "cost_usd": 0.2, "sessions": [1], "failed": None, "stop": None, "at": "2026-11-25T01:02:03Z",
                  "counted": False, "attempts": 1}]
        wt = os.path.join(self.tmp, "wt")
        os.makedirs(os.path.join(wt, "docs"))
        self.script[101] = [(10, state(101, done=False, stop={"reason": "infra-stop", "detail": "api", "reset_at": None},
                                       git={"git_dir": "/x", "common_dir": "/x", "work_tree": wt, "main_checkout": "/x"},
                                       procedure={"path": "docs/specs/101/procedure.yaml", "commit": MAIN}))]
        p = pathsmod.EnginePaths(self.home, REPO, 101)
        os.makedirs(os.path.join(p.issue_dir, "runs", "analyze", "1"))
        with open(os.path.join(p.issue_dir, "runs", "analyze", "1", "facts.json"), "w") as f:
            f.write("{}")
        self.run_sprint()
        return calls

    def test_report(self):
        self.run_stopped()
        out = io.StringIO()
        self.assertEqual(sprint.report(self.sp, out), 0)
        rep = json.loads(out.getvalue())
        m = {x["issue"]: x for x in rep["members"]}
        self.assertEqual((m[101]["stop"]["detail"], m[101]["stop"]["cause"], m[101]["stop_cause"]), ("api", "engine", "engine"))
        self.assertEqual(rep["stop_causes"], {"engine": 1, "issue": 0, "label": 0})                      # A13
        self.assertEqual(rep["counts"], {"stopped": 1, "blocked": 1, "done": 1})
        self.assertEqual(rep["cost_usd"], 3.0)
        self.assertTrue(m[101]["worktree"]["path"].endswith("wt"))
        self.assertIsInstance(m[101]["worktree"]["bytes"], int)
        self.assertTrue(m[101]["paths"]["procedure"].endswith("wt/docs/specs/101/procedure.yaml"))
        self.assertEqual(len(m[101]["paths"]["facts"]), 1)
        self.assertIsNone(m[103]["worktree"])
        self.assertEqual(sprint.report(pathsmod.SprintPaths(self.home, REPO, 1), io.StringIO()), 4)

    def test_status(self):
        out = io.StringIO()
        self.assertEqual(sprint.status(self.sp, out), 0)
        self.assertIn("not run on this machine", out.getvalue())
        self.run_stopped()
        out = io.StringIO()
        self.assertEqual(sprint.status(self.sp, out), 0)
        text = out.getvalue()
        for want in ("finished", "#101", "stopped — infra-stop / api", "blocked", "dep-stopped by #101", "PR 1003", "$1.50"):
            self.assertIn(want, text)
        out = io.StringIO()
        sprint.status(self.sp, out, as_json=True)
        rep = json.loads(out.getvalue())
        self.assertEqual((rep["running"], rep["sprint"]["state"], rep["members"][0]["engine"]["stop"]["reason"]), (False, "finished", "infra-stop"))

    def test_the_exit_code_of_status(self):
        self.base = basecheck.BaseCheckResult(False, red=["test"])
        self.run_sprint()
        self.assertEqual(sprint.status(self.sp, io.StringIO()), 4)
        with open(self.sp.supervisor_rc, "w") as f:
            f.write("0\n")
        self.assertEqual(sprint.status(self.sp, io.StringIO()), 4, "halted is never 0, whatever supervisor.rc says")
        store.save_sprint(self.sp, dict(self.s, state="running", halt=None, ended=None))
        out = io.StringIO()
        self.assertEqual(sprint.status(self.sp, out), 4)
        self.assertIn("the supervisor died", out.getvalue())
        self.hold(self.sp.lock, T)
        self.assertEqual(sprint.status(self.sp, io.StringIO()), 0, "running")
        os.unlink(self.sp.lock)
        with open(self.sp.supervisor_rc, "w") as f:
            f.write("3\n")
        self.assertEqual(sprint.status(self.sp, io.StringIO()), 3)

    def test_stop(self):
        self.assertEqual(sprint.stop(self.sp, io.StringIO()), 4)
        got = []
        old = signal.signal(signal.SIGTERM, lambda *a: got.append(a[0]))
        try:
            os.makedirs(self.sp.dir)
            self.hold(self.sp.repo_lock, 701)
            self.assertEqual(sprint.stop(self.sp, io.StringIO()), 4, "another sprint's supervisor")
            self.hold(self.sp.lock, T)
            self.assertEqual(sprint.stop(self.sp, io.StringIO()), 0)
        finally:
            signal.signal(signal.SIGTERM, old)
        self.assertEqual(got, [signal.SIGTERM])


class Check(unittest.TestCase):
    """`sprint check`: the real tracker functions, the fake gh, no write."""

    def gh(self, body=None, issues=None, prs=(), branches=(), extra=()):
        """sprint-700.json + (readiness T1 P7) member Issue rows `issues` {n: labels}, the open pull requests `prs`
        of `gh pr list`, the engine branches on the remote."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = os.path.join(self._tmp.name, "gh.json")
        with open(fakes.gh_fixture("sprint-700.json"), encoding="utf-8") as f:
            rules = json.load(f)
        if body is not None:
            rules["rules"][0]["json"]["body"] = body
        q = f"repos/{REPO}/"
        mine = [{"args": ["api", q + f"issues/{n}"], "json": {"number": n, "state": "open", "state_reason": None,
                                                             "labels": [{"name": x} for x in labels]}}
                for n, labels in (issues or {90: ()}).items()]
        mine += [{"args": ["pr", "list", "--repo", REPO, "--state", "open", "--limit", "*", "--json",
                           "number,headRefName,body,closingIssuesReferences"], "json": list(prs)},
                 {"args": ["api", q + "git/matching-refs/heads/gld/", "--paginate"],
                  "json": [{"ref": f"refs/heads/gld/{n}"} for n in branches]}]
        rules["rules"][:0] = list(extra) + mine
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rules, f)
        return W.InProcGh(REPO, path, W.PLUGIN_ROOT)

    def test_check(self):
        out, gh = io.StringIO(), self.gh(table(rows(101, (102, 101)) + [(90, None, "other")]),
                                         issues={101: (), 102: (), 90: ()})
        self.assertEqual(sprint.check(gh, T, out), 0, out.getvalue())
        self.assertIn("1. #101 [goal]\n  2. #102 on #101 [goal]\n  3. #90 [other]", out.getvalue())
        self.assertFalse([c for c in gh.calls if "-X" in c["argv"]])
        for body in (None, "nothing", table(rows((101, 102), (102, 101)))):                    # 000… hash, no table, a cycle
            out = io.StringIO()
            self.assertEqual(sprint.check(self.gh(body), T, out), 4)
            self.assertIn("refused", out.getvalue())

    def home(self, *with_records):
        """An engine home with a state.json of each Issue in `with_records`."""
        home = os.path.join(self._tmp.name, "gld")
        for n in with_records:
            with open(fakes.fixture("contracts", "state.stage4.example.json"), encoding="utf-8") as f:
                st = json.load(f)
            st["issue"] = n
            store.save_state(pathsmod.EnginePaths(home, REPO, n), st)
        return home

    def test_check_names_what_the_run_would_not_start(self):
        """Readiness T1 P7: an epic; without records here, an open pull request that closes it, gld/N on the remote,
        guild:done on the open Issue — each blocks (exit 4); a child is a note."""
        body = table(rows(101, 102, 103, 104, 105, 106))
        pr = {"number": 1924, "headRefName": "feature/#102-x", "body": "Closes #102", "closingIssuesReferences": []}
        gh = self.gh(body, issues={101: ("guild:children",), 102: (), 103: (), 104: ("guild:done",), 105: ("guild:child",),
                                   106: ()}, prs=[pr], branches=(103, 7))
        out = io.StringIO()
        self.assertEqual(sprint.check(gh, T, out, home=self.home()), 4, out.getvalue())
        text = out.getvalue()
        self.assertIn("blocked: #101: an epic (guild:children) — run blocks it (unsupported-epic)", text)
        self.assertIn("blocked: #102: open pull request #1924 (feature/#102-x) closes it — run refuses it "
                      "(open-closing-pr)", text)
        self.assertIn("blocked: #103: gld/103 is on the remote without engine records here — run blocks it "
                      "(remote-branch-exists)", text)
        self.assertIn("blocked: #104: guild:done on the open Issue — run refuses it (done-unconfirmed)", text)
        self.assertIn("note: #105: a child of an epic (guild:child) — it runs as a single Issue", text)
        self.assertNotIn(": #106:", text, "a plain member is not named")
        self.assertIn("refused: members the run would not start", text)
        self.assertFalse([c for c in gh.calls if "-X" in c["argv"]])

    def test_a_members_own_records_make_its_branch_and_pull_request_its_own(self):
        body = table(rows(102, 103, 105))
        pr = {"number": 900, "headRefName": "gld/102", "body": "Closes #102", "closingIssuesReferences": []}
        gh = self.gh(body, issues={102: (), 103: (), 105: ("guild:child",)}, prs=[pr], branches=(102, 103))
        out = io.StringIO()
        self.assertEqual(sprint.check(gh, T, out, home=self.home(102, 103)), 0, out.getvalue())
        self.assertNotIn("blocked", out.getvalue())
        self.assertIn("note: #105", out.getvalue())

    def test_github_not_answering_refuses(self):
        broken = {"args": ["pr", "list", "--repo", REPO, "--state", "open", "--limit", "*", "--json",
                           "number,headRefName,body,closingIssuesReferences"], "exit_code": 1, "stderr": "HTTP 502"}
        out = io.StringIO()
        self.assertEqual(sprint.check(self.gh(table(rows(101)), issues={101: ()}, extra=[broken]), T, out), 4)
        self.assertIn("refused", out.getvalue())


class Small(unittest.TestCase):
    def test_engine_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = os.path.join(tmp, "skills", "gld", "engine")
            os.makedirs(os.path.join(eng, "gxengine", "__pycache__"))
            os.makedirs(os.path.join(eng, "tests"))
            with self.assertRaises(ValueError):
                sprint.engine_sha256(tmp)

            def put(rel, text):
                with open(os.path.join(eng, rel), "w") as f:
                    f.write(text)
            put("gxengine/a.py", "1")
            one = sprint.engine_sha256(tmp)
            self.assertRegex(one, "^[0-9a-f]{64}$")
            put("tests/test_x.py", "x")
            put("gxengine/__pycache__/a.cpython.pyc", "x")
            self.assertEqual(sprint.engine_sha256(tmp), one)
            put("gxengine/a.py", "2")
            self.assertNotEqual(sprint.engine_sha256(tmp), one)
            put("gxengine/a.py", "1")
            os.symlink("a.py", os.path.join(eng, "gxengine", "b.py"))
            self.assertNotEqual(sprint.engine_sha256(tmp), one)
        self.assertRegex(sprint.engine_sha256(W.PLUGIN_ROOT), "^[0-9a-f]{64}$")

    def test_spawn_member(self):
        """D5: its own session, the log appended, rc removed before and written after."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            log, rc = os.path.join(tmp, "engine.log"), os.path.join(tmp, "engine.rc")
            for path, text in ((log, "before\n"), (rc, "99\n")):
                with open(path, "w") as f:
                    f.write(text)
            code = f"import os, sys; print(os.getsid(0) == os.getpid(), os.path.exists({rc!r}), os.environ['X']); sys.exit(10)"
            got = sprint.spawn_member([sys.executable, "-I", "-c", code], log_file=log, rc_file=rc, env={"X": "y"}, cwd=tmp,
                                      on_tick=lambda: None)
            self.assertEqual(got, 10)
            with open(log) as f:
                self.assertEqual(f.read(), "before\nTrue False y\n")
            with open(rc) as f:
                self.assertEqual(f.read(), "10\n")
            self.assertEqual(sprint.spawn_member([os.path.join(tmp, "none")], log_file=log, rc_file=rc, env={}, cwd=tmp,
                                                 on_tick=lambda: None), 127)

    def test_spawn_member_ticks(self):
        ticks, old = [], defaults.SPRINT_POLL_S
        defaults.SPRINT_POLL_S = 0.05
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp = os.path.realpath(tmp)
                sprint.spawn_member([sys.executable, "-I", "-c", "import time; time.sleep(0.5)"], log_file=os.path.join(tmp, "l"),
                                    rc_file=os.path.join(tmp, "rc"), env={}, cwd=tmp, on_tick=lambda: ticks.append(1))
        finally:
            defaults.SPRINT_POLL_S = old
        self.assertTrue(ticks)

    def test_host_name(self):
        self.assertRegex(sprint.host_name(), r"\A[A-Za-z0-9._-]+\Z")

    def test_units_and_options(self):
        with self.assertRaises(TypeError):
            sprint.SprintUnits(spawn_member=None)
        with self.assertRaises(TypeError):
            sprint.SprintOptions(repo="x")
        u = sprint.default_units(lambda: (True, ""))
        self.assertIs(u.base_check, basecheck.check)


if __name__ == "__main__":
    unittest.main()
