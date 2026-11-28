"""VA6 — the `sprint` commands, and the supervisor over the REAL tracker, git and engine: the member is
driver.run_issue (in process, role sessions faked), gh is the fake executable, the repository and its remote are git."""

import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from gxengine import basecheck, cli, driver, gitops, lifecycle, paths as pathsmod, sprint, sprinttracker, store
from tests import c_world as W
from tests import s3_world as S
from tests.helpers import fakes
from tests.test_sprint import REPO, T, Case, rows, state, table
from tests.test_sprint_member import Member

ENGINE_PY = os.path.join(W.ENGINE, "engine.py")
BASE = ("--repo", REPO, "--tracker", str(T))


class Commands(Case):
    def cli(self, *argv, units=None, stage=4, env=None):
        out = io.StringIO()
        rc = cli.main(["sprint", *argv], environ=dict(env or self.env, GLD_ENGINE_HOME=self.home), out=out, units=units, stage=stage)
        return rc, out.getvalue()

    def detach(self, *extra, env=None):
        """(rc, output, the argv handed to spawn_detached or None)."""
        seen = []

        def spawn(argv, log_file, rc_file, env=None, cwd=None):
            seen.append((argv, log_file, rc_file, cwd))
            return 4711
        with mock.patch.object(lifecycle, "spawn_detached", spawn):
            rc, out = self.cli("run", *BASE, "--checkout", self.tmp, *extra, env=env)
        return rc, out, seen[0] if seen else None

    def test_run_detaches(self):
        rc, out, got = self.detach("--allow-red-base", "--take-over")
        self.assertEqual(rc, 0, out)
        argv, log_file, rc_file, cwd = got
        self.assertEqual(argv[:2], [sys.executable, "-I"])
        self.assertEqual(argv[3:], ["sprint", "run", *BASE, "--checkout", self.tmp, "--allow-red-base", "--take-over", "--foreground"])
        self.assertEqual((log_file, rc_file, cwd), (self.sp.supervisor_log, self.sp.supervisor_rc, self.tmp))
        self.assertTrue(os.path.isdir(self.sp.dir))
        self.assertIn("pid 4711", out)

    def test_a_window_keeps_the_machine_awake(self):
        """§2.6: both conditions — a window in effect (given or inherited) and caffeinate on PATH."""
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        awake = os.path.join(bin_dir, "caffeinate")
        with open(awake, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(awake, os.stat(awake).st_mode | stat.S_IXUSR)
        env = dict(self.env, PATH=bin_dir + os.pathsep + self.env["PATH"])
        none = dict(self.env, PATH=fakes.FAKE_BIN)
        self.assertEqual(self.detach("--window", "22:00~10:00", env=env)[2][0][:2], [awake, "-i"])
        self.assertEqual(self.detach("--window", "22:00-10:00", env=none)[2][0][0], sys.executable)
        self.assertEqual(self.detach(env=env)[2][0][0], sys.executable)
        self.run_sprint(window="00:00-23:59")
        self.assertEqual(self.detach(env=env)[2][0][:2], [awake, "-i"], "inherited")
        self.assertEqual(self.detach("--window", "none", env=env)[2][0][0], sys.executable)

    def test_refused_before_detaching(self):
        rc, out, got = self.detach("--window", "9:00-10:00")
        self.assertEqual((rc, got), (4, None))
        self.assertIn("HH:MM-HH:MM", out)
        os.makedirs(self.sp.dir)
        self.hold(self.sp.repo_lock, 701)
        rc, out, got = self.detach()
        self.assertEqual((rc, got), (3, None))
        self.assertIn("sprint 701", out)

    def test_run_in_the_foreground(self):
        rc, out = self.cli("run", *BASE, "--checkout", self.tmp, "--foreground", "--window", "none", units=self.units())
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.outcomes(), {101: "done", 102: "done", 103: "done"})
        rc, out = self.cli("status", *BASE, "--wait", "0")
        self.assertEqual((rc, "run 1: finished" in out), (0, True))
        self.assertEqual(json.loads(self.cli("report", *BASE, "--json")[1])["counts"], {"done": 3})
        self.assertEqual(self.cli("stop", *BASE)[0], 4)

    def test_status_waits_for_the_supervisor(self):
        os.makedirs(self.sp.dir)
        naps = []

        def nap(seconds):
            naps.append(seconds)
            with open(self.sp.supervisor_rc, "w") as f:
                f.write("4\n")
        with mock.patch.object(time, "sleep", nap):
            self.assertEqual(self.cli("status", *BASE, "--wait", "30")[0], 4)
        self.assertEqual(len(naps), 1)

    def test_check_reads_github_only(self):
        with open(fakes.gh_fixture("sprint-700.json"), encoding="utf-8") as f:
            rules = json.load(f)
        rules["rules"][0]["json"]["body"] = table(rows(101, (102, 101)))
        rules["rules"][:0] = [                    # readiness T1 P7: the members' open closing pull requests, gld/ branches
            {"args": ["pr", "list", "--repo", REPO, "--state", "open", "--limit", "*", "--json",
                      "number,headRefName,body,closingIssuesReferences"], "json": []},
            {"args": ["api", f"repos/{REPO}/git/matching-refs/heads/gld/", "--paginate"], "json": []}]
        path, log = os.path.join(self.tmp, "gh.json"), os.path.join(self.tmp, "ghlog")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rules, f)
        env = fakes.fake_env(base=self.env, gh_fixtures=path, gh_log=log)
        rc, out = self.cli("check", *BASE, env=env)
        self.assertEqual(rc, 0, out)
        self.assertIn("2 members", out)
        self.assertFalse([c for c in fakes.gh_calls(log) if "-X" in c["argv"]])
        self.assertFalse(os.path.exists(self.home), "nothing was written")

    def test_the_self_check_is_the_engines_own(self):
        with mock.patch.object(driver, "default_self_check", lambda env: (False, "srt says no")):
            self.assertEqual(cli._sprint_self_check(REPO, T, self.home, self.env, self.out, 4), (False, "srt says no"))
        with mock.patch.object(driver, "default_self_check", lambda env: (True, "")):
            self.assertTrue(cli._sprint_self_check(REPO, T, self.home, self.env, self.out, 4)[0], "the plugin's gate hook")

    def test_a_detached_supervisor_is_refused_below_stage_4(self):
        """The real entry point, at this engine's own stage."""
        env = dict(self.env, GLD_ENGINE_HOME=self.home)
        p = subprocess.run([sys.executable, "-I", "-B", ENGINE_PY, "sprint", "status", *BASE], capture_output=True, text=True, env=env)
        self.assertIn(p.returncode, (0, 4), p.stderr)
        self.assertIn("stage 4" if p.returncode == 4 else "not run on this machine", p.stdout)


class RealMember(Member):
    """Members 41 (finished here, its PR open) and 42 (stacked on it) of acme/app; 42 is the real driver."""

    ROWS = [(41, None, "goal"), (42, 41, "goal")]

    def setUp(self):
        super().setUp()
        self.dep = self.push_branch("gld/41", {"src/dep.py": "d = 1\n", "docs/specs/41/analysis.md": "a\n"})
        self.home = os.path.realpath(self.w.engine_home)
        st = state(41, pr=77, base_sha=self.origin("main"), base_branch="main", draft=False)
        store.save_state(pathsmod.EnginePaths(self.home, W.REPO, 41), st)
        self.ld, self.res, self.sprint_out = self.leader(), None, io.StringIO()
        self.argv, self.w_rules = [], None
        self.gh_rules()

    def gh_rules(self, labels=()):
        q = f"repos/{W.REPO}/"
        pr = {"number": 77, "state": "open", "merged_at": None, "head": {"ref": "gld/41", "sha": self.dep}, "base": {"ref": "main"}}
        rules = [
            {"args": ["issue", "view", str(T), "--repo", W.REPO, "--json", "number,title,body,labels,state,stateReason,createdAt"],
             "json": {"number": T, "title": "S", "body": table(self.ROWS), "labels": [], "state": "OPEN", "stateReason": None}},
            {"args": ["api", q + f"issues/{T}"], "json": {"number": T, "state": "open", "labels": []}},
            {"args": ["api", q + f"issues/{T}/comments", "--paginate"], "json": []},
            {"args": ["api", "-X", "POST", q + f"issues/{T}/comments", "--input", "-"], "json": {"id": 7001}},
            {"args": ["api", "-X", "PATCH", q + "issues/comments/7001", "--input", "-"], "json": {"id": 7001}},
            {"args": ["repo", "view", W.REPO, "--json", "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"],
             "json": {"mergeCommitAllowed": False, "squashMergeAllowed": True, "rebaseMergeAllowed": False}},
            {"args": ["api", q + "issues/41"], "json": {"number": 41, "state": "open", "state_reason": None, "labels": []}},
            {"args": ["api", q + "issues/42"], "json": {"number": 42, "state": "open", "state_reason": None, "labels": []}},
            {"args": ["api", q + "pulls/77"], "json": pr},
            {"args": ["api", q + "git/matching-refs/heads/gld/42"], "json": []}]
        base = W.gh_rules(labels=labels)
        self.w.set_gh({"rules": rules + base["rules"]})

    def spawn(self, argv, *, log_file, rc_file, env, cwd, on_tick):
        """The engine's own command line, at stage 4, with the faked role machinery."""
        tail = argv[argv.index("-I") + 2:]
        self.argv.append(tail)
        u = self.units(self.ld, **({"results": self.res} if self.res is not None else {}))
        return cli.main(tail, environ=env, out=self.w.out, units=u, stage=4)

    def sprint(self, **over):
        units = sprint.SprintUnits(spawn_member=self.spawn, base_check=lambda r: basecheck.BaseCheckResult(True, record="/r.json"),
                                   tracker=sprinttracker, git=gitops, self_check=lambda: (True, ""), now=time.time, sleep=lambda s: None)
        kw = dict(repo=W.REPO, tracker=T, checkout=self.w.repo.path, plugin_root=W.PLUGIN_ROOT, engine_home=self.home,
                  environ=self.w.environ, out=self.sprint_out, window=None, allow_red_base=False, take_over=False,
                  srt="/usr/bin/true", user_tmp=None, stage=4)
        kw.update(over)
        rc = sprint.run(sprint.SprintOptions(**kw), units)
        sp = pathsmod.SprintPaths(self.home, W.REPO, T)
        s = store.load_sprint(sp)
        return rc, s, {m["issue"]: m for m in s["members"]}

    def test_a_stacked_member_end_to_end(self):
        """TS1 with everything but the role sessions real; TX1: no bypass flag in what is started."""
        local = self.w.repo.git("rev-parse", "refs/heads/main")
        self.push_branch("main", {"src/merged.py": "m\n"})
        rc, s, m = self.sprint()
        self.assertEqual((rc, s["state"]), (0, "finished"), self.sprint_out.getvalue() + self.w.out.getvalue())
        self.assertEqual((m[41]["outcome"], m[42]["outcome"]), ("done", "done"))
        self.assertEqual(m[42]["base"], {"branch": "gld/41", "sha": self.dep, "stacked_on": 41})
        self.assertTrue(m[42]["draft"])
        st = self.state()
        self.assertEqual((st["base_sha"], st["base_branch"], st["draft"], st["sprint"], st["mode"]),
                         (self.dep, "gld/41", True, T, "unattended"))
        pr = self.pr_fields()[0]
        self.assertEqual((pr["base"], pr["draft"]), ("gld/41", True))
        self.assertEqual(self.w.repo.git("rev-parse", "refs/heads/main"), local, "no local ref moved")
        self.assertEqual(len(self.argv), 1)
        self.assertFalse([a for a in self.argv[0] if "dangerously" in a])

    def test_a_stop_then_a_human_then_the_next_run(self):
        """TR4 over the real engine: the sprint never answers a human's stop; after the resume the member is done."""
        self.res = S.FakeResults({"design": [W.blocked, W.done]})
        self.ld = self.leader({"blocked": [W.leader_answer("escalate", recommendation={"answer": "rerun", "step": "design", "note": ""})]})
        rc, s, m = self.sprint()
        self.assertEqual((rc, m[42]["outcome"], m[42]["stop_reason"], m[42]["rc"]), (0, "stopped", "blocked", 10))
        self.gh_rules(labels=["guild:needs-human"])
        self.sprint()
        self.assertEqual(len(self.argv), 1, "a stopped member is not started again")
        self.ok(self.run4(self.ld, answer={"answer": "rerun", "step": "design"}, results=self.res))
        self.assertEqual(self.pr_fields()[-1]["base"], "gld/41")                                           # TS8
        rc, s, m = self.sprint()
        self.assertEqual((rc, m[42]["outcome"], s["run"], len(self.argv)), (0, "done", 3, 1))

    def test_a_control_file_in_the_dependencys_branch(self):
        """D1 with real git."""
        self.dep = self.push_branch("gld/41", {"CLAUDE.md": "another rule\n"}, base="gld/41")
        self.gh_rules()
        rc, s, m = self.sprint()
        self.assertEqual((rc, m[42]["block"], self.argv), (0, "base-unresolved", []))
        self.assertIn("CLAUDE.md", self.sprint_out.getvalue())

    def test_a_pushed_commit_the_pull_request_does_not_have_yet(self):
        """TS3 with real git: GitHub's head and the fetched head differ."""
        self.push_branch("gld/41", {"src/late.py": "l\n"}, base="gld/41")
        rc, s, m = self.sprint()
        self.assertEqual((rc, m[42]["block"], m[42]["cause"]), (0, "base-unresolved", 41))


class Documents(unittest.TestCase):
    """The commands the documents tell people to run exist with exactly those arguments (VA6)."""

    SKILL = os.path.dirname(W.ENGINE)
    FILES = ("commands/engine/dev.md", "commands/engine/resume.md", "commands/engine/status.md", "commands/engine/sprint.md",
             "commands/sprint/run.md", "commands/sprint/plan.md", "commands/sprint/retro.md", "commands/sprint.md", "SKILL.md")
    FILL = {"OWNER/REPO": "o/n", "N": "7", "T": "700", "REPO_ROOT": "/x", "ANSWER": "rerun", "STEP": "design", "W": "22:00-10:00",
            "NOTE_FILE": "/n", "REASON_FILE": "/r", "PATH": "test/a.py"}

    def commands(self):
        for rel in self.FILES:
            with open(os.path.join(self.SKILL, rel), encoding="utf-8") as f:
                for line in f.read().split("\n"):
                    m = re.match(r"\s*python3 -I <<SKILL_DIR>>/engine/engine\.py (.+)$", line)
                    if m:
                        yield rel, m.group(1).split()

    def test_every_documented_call_parses(self):
        seen = set()
        for rel, argv in self.commands():
            argv = [self.FILL.get(a, a) for a in argv]
            with self.subTest(rel=rel, argv=argv):
                args = cli.build_parser().parse_args(argv)
                seen.add((args.command, getattr(args, "action", None)))
        for want in (("sprint", a) for a in ("run", "status", "report", "check", "stop")):
            self.assertIn(want, seen)
        self.assertTrue({("dev", None), ("resume", None), ("status", None), ("canary", None)} <= seen)

    def test_every_sprint_argument_is_documented(self):
        with open(os.path.join(self.SKILL, "commands/engine/sprint.md"), encoding="utf-8") as f:
            text = f.read()
        sub = cli.build_parser()._subparsers._group_actions[0].choices["sprint"]._subparsers._group_actions[0].choices
        for name, parser in sub.items():
            self.assertIn(f"sprint {name}", text)
            for a in parser._actions:
                for o in a.option_strings:
                    if o.startswith("--") and o not in ("--help", "--foreground"):
                        self.assertIn(o, text, (name, o))


class NoBypass(unittest.TestCase):
    """TX1 / VA6: nothing this plugin can run switches the permission prompts off."""

    FLAG = "--dangerously-skip" + "-permissions"
    ALLOWED = ("skills/gld/engine/gxengine/render.py",       # the flag list the engine refuses to render
               "skills/gld/engine/tests/",                   # the boundary tests
               "skills/gld/engine/tools/out/", "skills/gld/engine/tools/decisions/")      # past reports of other repositories

    def test_no_executed_path_has_the_flag(self):
        hits = []
        for d, dirs, files in os.walk(W.PLUGIN_ROOT):
            dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", "node_modules")]
            for f in files:
                path = os.path.join(d, f)
                with open(path, "rb") as fh:
                    if self.FLAG.encode() in fh.read():
                        hits.append(os.path.relpath(path, W.PLUGIN_ROOT))
        self.assertEqual([h for h in hits if not h.startswith(self.ALLOWED)], [])
        self.assertIn("skills/gld/engine/gxengine/render.py", hits)

    def test_the_generated_supervisor_is_gone(self):
        for rel in ("templates/sprint-supervisor.sh", "commands/atoms/render_supervisor.py", "commands/atoms/spawn_supervisor.py"):
            self.assertFalse(os.path.exists(os.path.join(Documents.SKILL, rel)), rel)

    def test_batch_is_refused(self):
        with open(os.path.join(Documents.SKILL, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        valid = next(l for l in text.split("\n") if l.startswith("- Valid commands:"))
        self.assertNotIn("`batch`", valid)
        with open(os.path.join(Documents.SKILL, "commands/batch.md"), encoding="utf-8") as f:
            batch = f.read()
        self.assertIn("/gld sprint run", batch)
        self.assertNotIn("claude -p", batch)


if __name__ == "__main__":
    unittest.main()
