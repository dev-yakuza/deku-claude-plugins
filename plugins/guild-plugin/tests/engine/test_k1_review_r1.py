"""K1 review r1 regressions (review-k1-r1.md): B1–B6, M1–M6 and the accepted minors."""

import json
import os
import subprocess
import sys
import time
import unittest

import _k1
from _k1 import Clock, FakeSpawn, RecJournal, git, repo, stream_lines, tmpdir

from guildcore import ask as A
from guildcore import cost as COST
from guildcore import decisions as D
from guildcore import journal as J
from guildcore import ratelimit as RL
from guildcore import worker as W
from guildcore.adapters import claude as C
from guildcore.adapters import gh as G
from guildcore.adapters.claude import ProcResult
from guildcore.judges import runner as JR
from guildcore.roles import permissions as P
from guildcore.roles import runner as RR
from guildcore.records.write import GhWriter
from guildcore.state import label_names

DONE = ">>> RESULT <<<\nDONE: ok"


class Base(unittest.TestCase):
    def setUp(self):
        self.wt = repo(self, {"lib/a.dart": "a\n"})
        git(self.wt, "switch", "-q", "-c", "feat")
        self.root = os.path.join(tmpdir(self), "runs")
        self.cd = tmpdir(self)
        self.user = os.path.join(tmpdir(self), "settings.json")
        with open(self.user, "w") as fh:
            json.dump({}, fh)

    def runner(self, sessions, now=None, **kw):
        self.spawn = FakeSpawn(sessions)
        return RR.Runner(journal=RecJournal(), common_dir=self.cd, parent_env={"PATH": os.environ["PATH"]},
                         spawn=self.spawn, user_settings=self.user, run_root_dir=self.root,
                         claude="claude", clock=Clock(), **({"now": now} if now else {}), **kw)

    def spec(self, role="reviewer", task=None, **kw):
        kw.setdefault("remote_check", False)
        return RR.RoleSpec(role, task, "t", issue=7, stage="test", step="T", worktree=self.wt,
                           model="sonnet", base="HEAD", branch="feat", **kw)


def touch(rel):
    def f(argv, env, cwd, stdin):
        with open(os.path.join(cwd, rel), "a") as fh:
            fh.write("x")
    return f


class B4ChecksOnEveryExit(Base):
    def test_timeout_still_checked(self):
        r = self.runner([{"stream": stream_lines(texts=["…"]), "timed_out": True, "rc": -15,
                          "killed_by": "timeout", "check": touch("lib/a.dart")}])
        res = r.run_role(self.spec())
        self.assertEqual(res.status, "SCOPE")
        self.assertIn("was TIMEOUT", res.notes)

    def test_invalid_still_checked(self):
        r = self.runner([{"stream": stream_lines(texts=["no sentinel"]), "check": touch("lib/a.dart")},
                         {"stream": stream_lines(texts=["still none"])}])
        res = r.run_role(self.spec())
        self.assertEqual(res.status, "SCOPE")
        self.assertIn("was INVALID", res.notes)

    def test_unresolvable_remote_fails_closed(self):
        r = self.runner([{"stream": stream_lines(texts=[DONE])}])
        res = r.run_role(self.spec(remote_check=True))        # the temp repo has no origin
        self.assertEqual(res.status, "SCOPE")
        self.assertTrue(any("remote unverifiable" in v for v in res.violations))


class B5ProcessGroups(unittest.TestCase):
    def test_background_child_reaped_before_return(self):
        d = tmpdir(self)
        late = os.path.join(d, "late.txt")
        script = ("import subprocess; subprocess.Popen(['/bin/sh','-c','sleep 2; echo late > %s'])" % late)
        p = C.run_process([sys.executable, "-c", script], dict(os.environ), d, "", os.path.join(d, "o"),
                          os.path.join(d, "e"), 30, poll_s=0.1)
        self.assertEqual(p.reaped, "killed")
        time.sleep(3)
        self.assertFalse(os.path.exists(late))

    def test_leaderless_group_is_killed(self):
        p = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & exit 0"], start_new_session=True)
        pgid = p.pid
        p.wait()
        time.sleep(0.3)
        self.assertEqual(C.safe_kill_group({"pid": p.pid, "pgid": pgid, "start_time": "x"}, grace_s=2), "killed")
        with self.assertRaises(OSError):
            os.killpg(pgid, 0)

    def test_orphans_with_cwd_in_worktree_are_reaped(self):
        # what the real CLI's Bash tool does: `( sleep; write ) &` ends up an orphan outside our group
        d = tmpdir(self)
        subprocess.run(["/bin/sh", "-c", "(sleep 3; echo late > late.txt) > /dev/null 2>&1 &"], cwd=d)
        time.sleep(0.5)
        pids = C.reap_strays([d], 30)
        self.assertTrue(pids)
        time.sleep(3.5)
        self.assertFalse(os.path.exists(os.path.join(d, "late.txt")))

    def test_live_children_of_a_peer_are_not_reaped(self):
        d = tmpdir(self)
        p = subprocess.Popen(["/bin/sh", "-c", "sleep 5"], cwd=d)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        time.sleep(0.3)
        self.assertEqual(C.reap_strays([d], 30), [])
        self.assertIsNone(p.poll())

    def test_restart_reaps_journaled_groups(self):
        j = J.Journal(tmpdir(self), 3, clock=Clock())
        p = subprocess.Popen(["sleep", "30"], start_new_session=True)
        self.addCleanup(lambda: (p.poll() is None and p.kill(), p.wait()))
        j.record_pid("developer", p.pid, os.getpgid(p.pid), C.process_start(p.pid))
        # K5r1-M1: the journaled owner (this live process) is alive → a restart never touches its group
        self.assertEqual(W.reap_journaled(j), [(p.pid, "owner-alive")])
        self.assertIsNone(p.poll())
        dead = subprocess.Popen(["true"])
        dead.wait()
        j.append("pid", who="developer", pid=p.pid, pgid=os.getpgid(p.pid), start_time=C.process_start(p.pid),
                 session_id=None, owner=dead.pid, owner_start="Thu Jan  1 00:00:00 1970")
        self.assertEqual(W.reap_journaled(j), [(p.pid, "killed")])     # the crashed owner's group is reaped


class B6RateLimits(Base):
    def test_429_in_repair_session(self):
        r = self.runner([{"stream": stream_lines(texts=["no sentinel"])},
                         {"stream": stream_lines(texts=[""], result={"is_error": True, "api_error_status": 429})}])
        self.assertEqual(r.run_role(self.spec()).status, "RATE_LIMITED")

    def test_judge_rate_limit_raises_without_tier_up(self):
        spawn = FakeSpawn([{"stream": json.dumps({"type": "result", "is_error": True, "api_error_status": 429})}])
        jr = JR.JudgeRunner(parent_env={"PATH": "/usr/bin"}, spawn=spawn, run_root_dir=tmpdir(self),
                            claude="claude", user_settings=self.user)
        spec = JR.JudgeSpec("QA", "sonnet", {"type": "object"}, ["s"], [("b", "x")])
        with self.assertRaises(JR.RateLimited) as cm:
            jr.judge(spec)
        self.assertEqual(len(spawn.calls), 1)
        self.assertEqual(RL.exit_code_for(cm.exception), 75)

    def test_secondary_limit_403_exits_75(self):
        read = G.FakeGh({"repo": "o/r", "issues": {"5": {"labels": [], "comments": []}}})
        write = G.FakeGhWrite(read)
        write.fail_next("ratelimit")
        w = GhWriter(read, write, sleep=lambda s: None)
        with self.assertRaises(G.GhWriteError) as cm:
            w.create_comment(5, "<!-- guild:note -->\nx")
        self.assertEqual(cm.exception.kind, "ratelimit")
        self.assertEqual(RL.exit_code_for(cm.exception), 75)
        self.assertEqual(RL.exit_code_for(G.GhWriteError("x", "HTTP 401", "auth")), 3)

    def test_judge_halt(self):
        spawn = FakeSpawn([{"stream": "", "killed_by": "halt", "rc": -15}])
        jr = JR.JudgeRunner(parent_env={"PATH": "/usr/bin"}, spawn=spawn, run_root_dir=tmpdir(self),
                            claude="claude", user_settings=self.user, halt_check=lambda: True)
        with self.assertRaises(JR.Halted):
            jr.judge(JR.JudgeSpec("QA", "sonnet", {"type": "object"}, ["s"], [("b", "x")]))


class M1Idempotence(unittest.TestCase):
    def world(self):
        read = G.FakeGh({"repo": "o/r", "issues": {"5": {"labels": [], "comments": []}},
                         "prs": [{"number": 9, "body": "Human intro", "state": "OPEN"}]})
        return read, G.FakeGhWrite(read, clock=Clock())

    def test_lost_ack_does_not_duplicate(self):
        read, write = self.world()
        GhWriter(read, write, sleep=lambda s: None).create_comment(5, "<!-- guild:note -->\nx")
        self.assertEqual(len(read.comments(5)), 1)

    def test_eventual_consistency_does_not_duplicate(self):
        read, write = self.world()
        write.lag_next(1)
        GhWriter(read, write, sleep=lambda s: None).create_comment(5, "<!-- guild:note -->\ny")
        self.assertEqual(len(read.comments(5)), 1)

    def test_lost_ack_issue_create(self):
        read, write = self.world()
        write._acklost = 1
        orig = write.create_issue

        def lossy(title, body, labels=()):
            r = orig(title, body, labels)
            if getattr(write, "_acklost", 0):
                write._acklost -= 1
                raise G.GhError("HTTP 502: Bad Gateway")
            return r
        write.create_issue = lossy
        # K4r3-B1: the lost reply is found by its create token through the REST list filtered by `since`
        # — the writer's clock must be the fake server's (the fake stamps 2026-11-16)
        from guildcore.adapters.clock import FixedClock
        n, created = GhWriter(read, write, sleep=lambda s: None,
                              clock=FixedClock("2026-11-16T00:00:00Z")).issue_create("t", "b", key="k9")
        self.assertEqual(len([k for k in read.fx["issues"] if "k9" in (read.fx["issues"][k].get("body") or "")]), 1)
        self.assertFalse(created)

    def test_pr_patch_retry_keeps_human_edit(self):
        read, write = self.world()
        w = GhWriter(read, write, sleep=lambda s: None)
        orig = write.patch_pr_body
        state = {"n": 0}

        def flaky(n, body):
            state["n"] += 1
            if state["n"] == 1:
                read.fx["prs"][0]["body"] = "Human intro EDITED"       # a human edits meanwhile
                raise G.GhError("HTTP 502: Bad Gateway")
            return orig(n, body)
        write.patch_pr_body = flaky
        w.pr_body_splice(9, "manual-qa", "<!-- guild:manual-qa -->\n- [ ] c\n<!-- /guild:manual-qa -->")
        self.assertTrue(read.pr(9)["body"].startswith("Human intro EDITED"))


class M2VerifyIntent(unittest.TestCase):
    def test_restart_finds_landed_comment(self):
        read = G.FakeGh({"repo": "o/r", "issues": {"5": {"labels": [], "comments": []}}})
        write = G.FakeGhWrite(read, clock=Clock())
        j = J.Journal(tmpdir(self), 5, clock=Clock())
        w = GhWriter(read, write, journal=j, sleep=lambda s: None)
        w.create_comment(5, "<!-- guild:note -->\nhello")
        it = [e for e in j.entries if e["kind"] == "intent"][0]
        self.assertTrue(it["body_sha256"] and it["marker"] == "note")
        self.assertTrue(w.verify_intent(it))
        it2 = dict(it, body_sha256="0" * 64)
        self.assertFalse(w.verify_intent(it2))

    def test_restart_labels(self):
        read = G.FakeGh({"repo": "o/r", "issues": {"5": {"labels": [{"name": "guild:qa"}], "comments": []}}})
        w = GhWriter(read, G.FakeGhWrite(read), sleep=lambda s: None)
        self.assertTrue(w.verify_intent({"op": "labels", "target": "5", "add": ["guild:qa"], "remove": []}))


class M3Cost(Base):
    def test_dead_session_estimated(self):
        lines = [json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 1000000,
                                                                                    "output_tokens": 100000},
                                                               "content": [{"type": "text", "text": "…"}]}})]
        r = self.runner([{"stream": "\n".join(lines), "timed_out": True, "killed_by": "timeout", "rc": -15}])
        r.run_role(self.spec())
        row = COST.rows(self.cd)[0]
        self.assertTrue(row["estimated"])
        self.assertAlmostEqual(row["total_cost_usd"], 3.0 + 1.5)
        self.assertTrue(row["t"])
        self.assertEqual(row["session_kind"], "main")

    def test_session_kinds_and_brief(self):
        r = self.runner([{"stream": stream_lines(texts=["x"])}, {"stream": stream_lines(texts=[DONE])}])
        r.run_role(self.spec())
        rows = COST.rows(self.cd)
        self.assertEqual([x["session_kind"] for x in rows], ["main", "repair"])
        self.assertLess(rows[1]["brief_chars"], rows[0]["brief_chars"])


class M4Deadline(Base):
    def test_one_budget_across_sessions(self):
        clock = [0.0]

        def now():
            return clock[0]

        def slow(argv, env, cwd, stdin):
            clock[0] += 70
        r = self.runner([{"stream": stream_lines(texts=["no"]), "check": slow},
                         {"stream": stream_lines(texts=[DONE]), "check": slow}], now=now)
        res = r.run_role(self.spec(timeout_s=100))
        self.assertEqual(res.status, "TIMEOUT")
        self.assertLessEqual(self.spawn.calls[1]["timeout_s"], 30)


class M5Ask(Base):
    def test_project_ask_is_denied(self):
        wt = repo(self, {".claude/settings.json": {"permissions": {"ask": ["Bash(git push origin -d:*)"]}}})
        from guildcore.roles import settings as S
        rd = S.render("developer", "implement", worktree=wt, base="HEAD", user_settings=self.user)
        self.assertIn("Bash(git push origin -d:*)", rd.settings["permissions"]["deny"])


class Minors(Base):
    def test_m2_fresh_spawn_does_not_read_s1_result(self):
        rd = os.path.join(self.root, "001-test-explorer")
        files = {os.path.join(rd, "out", "result.json"): json.dumps({"evidence_path": "x"})}
        r = self.runner([{"stream": stream_lines(texts=["no"]), "files": files},
                         {"stream": "", "rc": 1},
                         {"stream": stream_lines(texts=[DONE])}])
        from guildcore.roles import result as R
        res = r.run_role(self.spec("explorer", result_schema=R.RESULT_SCHEMAS["explorer"]))
        self.assertEqual(res.status, "INVALID")
        self.assertTrue(os.path.exists(os.path.join(rd, "out", "result.json.s1")))

    def test_m3_denial_class_uses_session_rules(self):
        _, deny = P.role_rules("reviewer")
        self.assertEqual(RR.denial_class("git commit -m x", deny), "forbidden")
        self.assertEqual(RR.denial_class("gh pr review 1 --approve"), "forbidden")
        self.assertEqual(RR.denial_class("bash -c 'x'"), "forbidden")

    def test_m4_nonce_journaled_before_block(self):
        read = G.FakeGh({"repo": "o/r", "issues": {"5": {"labels": [], "comments": []}}})
        w = GhWriter(read, G.FakeGhWrite(read, clock=Clock()), sleep=lambda s: None)
        j = J.Journal(tmpdir(self), 5, clock=Clock())
        dw = D.DecisionWriter(w, 5, Clock())
        orig = dw.record
        seen = {}

        def rec(fields, _retry=True):
            seen["nonce_first"] = any(e.get("what") == "predict-first-nonce" for e in j.entries)
            return orig(fields, _retry)
        dw.record = rec
        q = A.Question("loopback", "q", [{"token": "a"}, {"token": "b"}], recommended="a", predict_first=True)
        qid = A.surface(q, True, dw, events=None, clock=Clock(), journal=j)
        self.assertTrue(seen["nonce_first"])
        self.assertEqual(A._reveal(j, qid)["recommended"], "a")

    def test_m5_own_label_ids_before_done(self):
        read = G.FakeGh({"repo": "o/r", "issues": {"5": {"labels": [], "comments": [], "timeline": []}}})
        j = J.Journal(tmpdir(self), 5, clock=Clock())
        w = GhWriter(read, G.FakeGhWrite(read, clock=Clock()), journal=j, sleep=lambda s: None)
        w.labels_apply(5, add=["guild:qa"])
        kinds = [(e["kind"], e.get("op")) for e in j.entries]
        self.assertLess(kinds.index(("write", "label")), kinds.index(("done", "labels")))

    def test_m9_renumber_marks_superseded(self):
        read = G.FakeGh({"repo": "o/r", "issues": {"5": {"labels": [], "comments": []}}})
        w = GhWriter(read, G.FakeGhWrite(read, clock=Clock()), sleep=lambda s: None)
        dw = D.DecisionWriter(w, 5, Clock())
        dw.record({"point": "a", "by": "code"})
        from guildcore.records import decisions as fmt
        orig = dw._log
        state = {"n": 0}

        def racing_log():
            log = orig()
            state["n"] += 1
            if state["n"] == 2:      # after my append: a racer wrote the same number elsewhere
                c = read.fx["issues"]["5"]["comments"][0]
                c["body"] = fmt.insert(c["body"], fmt.render_block(2, {"point": "other", "by": "human"}))
                log = orig()
            return log
        dw._log = racing_log
        did = dw.record({"point": "mine", "by": "code"})
        blocks = D.DecisionLog.load(read.comments(5)).blocks
        self.assertTrue(any(b.get("status") == "superseded" and b.get("resolves") == "D2" for b in blocks), did)


if __name__ == "__main__":
    unittest.main()
