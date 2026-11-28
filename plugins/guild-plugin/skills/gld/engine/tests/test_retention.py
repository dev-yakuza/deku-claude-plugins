"""Readiness R1: engine records cleanup (design incidents.md §7) — retro's merged / closed members, status's 90 days.

A temp engine home with a sprint record and member folders; pull request facts come from a double (the CLI test
passes a double `make_gh` and `sprinttracker.member_prs`). Nothing outside the temp folder is read or written.
"""

import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from gxengine import cli, driver, incidents, lifecycle, paths as pathsmod, retention, sprinttracker, store

REPO = "acme/app"
T = 700
DAY = 86400
NOW = 1_800_000_000.0
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "incidents")


def sprint_obj(issues):
    """The sprint-state contract example with this repository, tracker and members (outcome done)."""
    with open(os.path.join(os.path.dirname(FIX), "contracts", "sprint-state.example.json"), encoding="utf-8") as f:
        ex = json.load(f)
    row = next(m for m in ex["members"] if m["outcome"] == "done")
    ex.update(repo=REPO, tracker=T, order=list(issues), state="finished", halt=None,
              members=[dict(row, issue=n) for n in issues])
    return ex


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(os.path.realpath(self._tmp.name), "gld")
        os.makedirs(self.home)

    def tearDown(self):
        self._tmp.cleanup()

    def member(self, issue, repo=REPO, size=1000, tmp=True, age_days=None):
        p = pathsmod.EnginePaths(self.home, repo, issue)
        os.makedirs(os.path.join(p.issue_dir, "runs", "test", "1"))
        with open(p.log, "w") as f:
            f.write("x" * size)
        with open(os.path.join(p.issue_dir, "runs", "test", "1", "run.log"), "w") as f:
            f.write("y" * size)
        if tmp:
            os.makedirs(os.path.join(p.tmp_root, "test-1"))
            with open(os.path.join(p.tmp_root, "test-1", "f"), "w") as f:
                f.write("z" * 10)
        if age_days is not None:
            t = NOW - age_days * DAY
            os.utime(p.log, (t, t))
        return p

    def sprint(self, issues):
        sp = pathsmod.SprintPaths(self.home, REPO, T)
        store.save_sprint(sp, sprint_obj(issues))
        return sp

    def refer(self, paths):
        """An incident whose occurrence names `paths`' records folder."""
        ip = pathsmod.IncidentPaths(self.home)
        sig = "canary-failed @ analyze"
        sl = incidents.slug(sig)
        os.makedirs(ip.incident_dir(sl))
        occ = {"n": 1, "at": "2026-11-26T00:00:00Z", "recorded": "2026-11-26T00:00:00Z", "repo": paths.repo,
               "issue": paths.issue, "tracker": None, "step": "analyze", "reason": "canary-failed", "detail": None,
               "escalate_reason": None, "leader_failed": None,
               "engine": {"version": "x", "commit": None, "dirty": None, "fixes": []}, "records": paths.issue_dir,
               "note": None, "log": []}
        store.write_record(ip, ip.incident_json(sl), {
            "format": 1, "signature": sig, "slug": sl, "kind": "defect", "first_seen": occ["at"],
            "last_seen": occ["at"], "count": 1, "evidence": None, "occurrences": [occ]}, "incident")


PRS = {
    1: [{"number": 11, "state": "MERGED"}],
    2: [{"number": 12, "state": "CLOSED"}],
    3: [{"number": 13, "state": "OPEN"}],
    4: [],
    5: [{"number": 15, "state": "CLOSED"}, {"number": 16, "state": "MERGED"}],
    6: [{"number": 17, "state": "MERGED"}, {"number": 18, "state": "OPEN"}],
}


def facts(issue, state):
    if issue == 9:
        raise RuntimeError("GitHub did not answer")
    return PRS[issue]


class Members(Base):
    def test_only_members_whose_prs_are_all_merged_or_closed_lose_their_records(self):
        ps = {n: self.member(n) for n in (1, 2, 3, 4, 5, 6, 9)}
        self.sprint([1, 2, 3, 4, 5, 6, 9, 8])
        rows = {r["issue"]: r for r in retention.prune_members(self.home, REPO, T, facts, apply=True)}
        self.assertEqual({n: (rows[n]["action"], rows[n]["why"]) for n in rows}, {
            1: ("removed", "pr-done"), 2: ("removed", "pr-done"), 3: ("kept", "open-pr"), 4: ("kept", "no-pr"),
            5: ("removed", "pr-done"), 6: ("kept", "open-pr"), 9: ("kept", "pr-unknown"), 8: ("kept", "nothing-here")})
        for n in (1, 2, 5):
            self.assertFalse(os.path.exists(ps[n].issue_dir))
            self.assertFalse(os.path.exists(ps[n].tmp_root))
            self.assertEqual(set(rows[n]["removed"]), {"records", "tmp"})
        for n in (3, 4, 6, 9):
            self.assertTrue(os.path.isdir(ps[n].issue_dir))
            self.assertTrue(os.path.isdir(ps[n].tmp_root))
        self.assertIn("GitHub did not answer", rows[9]["note"])
        self.assertTrue(os.path.isdir(pathsmod.SprintPaths(self.home, REPO, T).dir))       # the sprint record stays

    def test_without_apply_nothing_goes(self):
        p = self.member(1)
        self.sprint([1])
        rows = retention.prune_members(self.home, REPO, T, facts, apply=False)
        self.assertEqual((rows[0]["action"], rows[0]["removed"]), ("would-remove", {}))
        self.assertTrue(os.path.isdir(p.issue_dir) and os.path.isdir(p.tmp_root))

    def test_records_an_incident_names_are_kept_their_tmp_goes(self):
        p = self.member(1)
        self.refer(p)
        self.sprint([1])
        row = retention.prune_members(self.home, REPO, T, facts, apply=True)[0]
        self.assertEqual((row["action"], row["why"], set(row["removed"])), ("removed", "incident", {"tmp"}))
        self.assertTrue(os.path.isdir(p.issue_dir))
        self.assertFalse(os.path.exists(p.tmp_root))

    def test_a_running_engine_keeps_its_records(self):
        p = self.member(1)
        self.sprint([1])
        with mock.patch.object(lifecycle, "lock_holder", return_value={"issue": 1, "pid": 1}):
            row = retention.prune_members(self.home, REPO, T, facts, apply=True)[0]
        self.assertEqual((row["action"], row["why"]), ("kept", "running"))
        self.assertTrue(os.path.isdir(p.issue_dir))

    def test_no_sprint_record_is_refused(self):
        with self.assertRaises(retention.Refused):
            retention.prune_members(self.home, REPO, T, facts)

    def test_only_the_approved_members(self):
        a, b = self.member(1), self.member(2)
        self.sprint([1, 2])
        rows = retention.prune_members(self.home, REPO, T, facts, apply=True, only=[2])
        self.assertEqual([(r["issue"], r["action"]) for r in rows], [(2, "removed")])
        self.assertTrue(os.path.isdir(a.issue_dir))
        self.assertFalse(os.path.exists(b.issue_dir))
        with self.assertRaises(retention.Refused):
            retention.prune_members(self.home, REPO, T, facts, only=[3])


class Stale(Base):
    def test_older_than_90_days_listed_oldest_first_minus_incident_and_running(self):
        old = self.member(1, age_days=120)
        older = self.member(2, repo="acme/other", age_days=200)
        self.member(3, age_days=10)
        ref = self.member(4, age_days=300)
        self.refer(ref)
        run = self.member(5, age_days=95)
        holder = lambda p: {"issue": 5, "pid": 1} if p.issue == 5 else None                     # noqa: E731
        with mock.patch.object(lifecycle, "lock_holder", side_effect=holder):
            rep = retention.stale(self.home, now=NOW)
        self.assertEqual([i["pick"] for i in rep["items"]], ["acme/other#2", "acme/app#1"])
        self.assertEqual([i["age_days"] for i in rep["items"]], [200, 120])
        self.assertEqual({k["pick"]: k["why"] for k in rep["kept"]}, {"acme/app#4": "incident", "acme/app#5": "running"})
        self.assertTrue(rep["items"][1]["records_bytes"] >= 2000 and rep["items"][1]["tmp_bytes"] == 10)
        self.assertTrue(os.path.isdir(old.issue_dir) and os.path.isdir(older.issue_dir) and os.path.isdir(run.issue_dir))

    def test_only_the_picked_go_each_checked_again(self):
        a = self.member(1, age_days=120)
        b = self.member(2, age_days=120)
        fresh = self.member(3, age_days=5)
        ref = self.member(4, age_days=300)
        self.refer(ref)
        rows = retention.remove_stale(self.home, ["acme/app#1", "acme/app#3", "acme/app#4", "acme/app#99",
                                                  "../x#1", "acme/app#0"], now=NOW)
        self.assertEqual([(r["pick"], r["action"]) for r in rows], [
            ("acme/app#1", "removed"), ("acme/app#3", "refused"), ("acme/app#4", "refused"),
            ("acme/app#99", "refused"), ("../x#1", "refused"), ("acme/app#0", "refused")])
        self.assertEqual(rows[2]["why"], "incident")
        self.assertFalse(os.path.exists(a.issue_dir) or os.path.exists(a.tmp_root))
        self.assertTrue(os.path.isdir(b.issue_dir) and os.path.isdir(fresh.issue_dir) and os.path.isdir(ref.issue_dir))

    def test_sprint_and_base_green_folders_are_never_items(self):
        self.member(1, age_days=120)
        for d in ("sprints/700", "base-green"):
            os.makedirs(os.path.join(self.home, "records", "acme", "app", d))
        rep = retention.stale(self.home, now=NOW)
        self.assertEqual([i["pick"] for i in rep["items"]], ["acme/app#1"])


class Cli(Base):
    def run_cli(self, *argv):
        out = io.StringIO()
        env = {"GLD_ENGINE_HOME": self.home, "HOME": os.path.dirname(self.home), "PATH": os.environ.get("PATH", "")}
        rc = cli.main(list(argv), environ=env, out=out, units=driver.Units(make_gh=lambda *a: "GH"))
        return rc, out.getvalue()

    def test_records_prune(self):
        self.member(1)
        self.member(3)
        self.sprint([1, 3])
        with mock.patch.object(sprinttracker, "member_prs", side_effect=lambda gh, n: PRS[n]) as mp:
            rc, text = self.run_cli("records", "prune", "--repo", REPO, "--tracker", str(T))
            self.assertEqual(rc, 0)
            self.assertIn("#1: would-remove (pr-done)", text)
            self.assertIn("#3: kept (open-pr)", text)
            rc, text = self.run_cli("records", "prune", "--repo", REPO, "--tracker", str(T), "--apply", "--json")
        self.assertEqual({r["issue"]: r["action"] for r in json.loads(text)}, {1: "removed", 3: "kept"})
        self.assertEqual(mp.call_args_list[0].args[0], "GH")
        rc, text = self.run_cli("records", "prune", "--repo", REPO, "--tracker", "701")
        self.assertEqual(rc, 4)

    def test_records_stale(self):
        self.member(1, age_days=120)
        with mock.patch.object(time, "time", return_value=NOW):
            rc, text = self.run_cli("records", "stale")
            self.assertIn("engine records untouched for more than 90 days: 1", text)
            self.assertIn("1. acme/app#1 — last activity", text)
            self.assertEqual(self.run_cli("records", "stale", "--apply")[0], 4)            # --apply needs --pick
            self.assertEqual(self.run_cli("records", "stale", "--pick", "acme/app#1")[0], 4)
            rc, text = self.run_cli("records", "stale", "--apply", "--pick", "acme/app#1")
            self.assertEqual(rc, 0)
            self.assertIn("acme/app#1: removed", text)
            rc, text = self.run_cli("records", "stale", "--json")
        self.assertEqual(json.loads(text)["items"], [])


if __name__ == "__main__":
    unittest.main()
