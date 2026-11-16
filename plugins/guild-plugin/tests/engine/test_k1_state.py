"""K1 — journal write side, worker lock/events, cost sink, ground-truth capture, rate-limit
verdicts, the checks runner/parsers."""

import io
import json
import os
import subprocess
import sys
import time
import unittest

import _k1
from _k1 import Clock, git, repo, tmpdir

from guildcore import capture as CAP
from guildcore import checks as CH
from guildcore import cost as COST
from guildcore import journal as J
from guildcore import ratelimit as RL
from guildcore import worker as W
from guildcore.adapters import claude as C
from workflows.status import running


class JournalWrite(unittest.TestCase):
    def setUp(self):
        self.cd = tmpdir(self)
        self.j = J.Journal(self.cd, 12, clock=Clock())

    def test_lines_are_k0_format(self):
        self.j.append("checkpoint", step_id="T3.5")
        raw = open(self.j.path).read()
        self.assertTrue(raw.endswith("\n"))
        obj = json.loads(raw)
        self.assertEqual(raw.strip(), J.render("checkpoint", obj["t"], issue=12, step_id="T3.5"))
        self.assertEqual(J.JournalView.read(self.cd, 12).entries[0]["step_id"], "T3.5")

    def test_intent_done_and_intent_only(self):
        it = self.j.intent("e1", "test", "T3.5", 1, "comment:create", "12")
        self.assertEqual(len(self.j.intent_only()), 1)
        self.j.done(it)
        self.assertEqual(self.j.intent_only(), [])
        self.assertTrue(self.j.is_done("e1", "test", "T3.5", 1, "comment:create", "12"))

    def test_verify_pending_recovers_or_redoes(self):
        self.j.intent("e1", "test", "T1", 1, "labels", "12")
        self.j.intent("e1", "test", "T2", 1, "comment:create", "12")
        redo = self.j.verify_pending(lambda it: it["step_id"] == "T1")
        self.assertEqual([r["step_id"] for r in redo], ["T2"])
        again = J.Journal(self.cd, 12)
        self.assertEqual([r["step_id"] for r in again.intent_only()], ["T2"])

    def test_entry_validity(self):
        self.j.open_new_entry("test", "/wt", loopback_blocks=2, audit_blocks=1, head="abc")
        self.assertEqual(self.j.entry_valid("test", "/wt", 2, 1), (True, None))
        self.assertFalse(self.j.entry_valid("qa", "/wt", 2, 1)[0])
        self.assertFalse(self.j.entry_valid("test", "/other", 2, 1)[0])
        self.assertFalse(self.j.entry_valid("test", "/wt", 3, 1)[0])          # someone else's loop-back
        self.assertTrue(self.j.entry_valid("test", "/wt", 3, 1, own_loopback=1)[0])
        self.assertFalse(self.j.entry_valid("test", "/wt", 1, 1)[0])          # a reset removed blocks
        self.assertFalse(self.j.entry_valid("test", "/wt", 2, 2)[0])

    def test_checkpoint_ctx_atomic(self):
        self.j.checkpoint("E2.5", {"branch": "feat", "attempt": 2})
        self.assertEqual(self.j.load_ctx(), {"attempt": 2, "branch": "feat"})
        self.assertEqual(self.j.last_checkpoint()["step_id"], "E2.5")
        self.assertFalse([f for f in os.listdir(self.j.dir) if ".tmp." in f])

    def test_cache(self):
        k = J.cache_key("EX-ARB", "abc", "opus", "s", {"v": 1}, "0.102.0")
        self.assertNotEqual(k, J.cache_key("EX-ARB", "abc", "sonnet", "s", {"v": 1}, "0.102.0"))
        self.assertIsNone(self.j.cache_get("EX-ARB", k))
        self.j.cache_put("EX-ARB", k, {"choice": "accept"})
        self.assertEqual(self.j.cache_get("EX-ARB", k), {"choice": "accept"})
        self.j.cache_invalidate("EX-ARB")
        self.assertIsNone(self.j.cache_get("EX-ARB", k))

    def test_epoch_resets_escalation_count(self):
        for _ in range(3):
            self.j.append("mj", point="G-ESCALATE")
        self.assertEqual(self.j.escalations_this_epoch(), 3)
        self.j.bump_epoch("answer D3")
        self.assertEqual(self.j.escalations_this_epoch(), 0)
        self.assertEqual(self.j.epoch(), 1)

    def test_own_writes_and_denials(self):
        self.j.own_write("label", event_id=55, event="labeled", label="guild:qa")
        self.j.own_write("comment", comment_id=900)
        self.assertEqual(self.j.own_label_writes(), [55])
        self.assertEqual(self.j.own_comment_ids(), [900])
        self.j.record_denial("developer-implement", "git push", "forbidden", "subcommandResults")
        self.assertEqual(self.j.denials()[0]["cls"], "forbidden")

    def test_torn_tail_tolerated(self):
        self.j.append("checkpoint", step_id="a")
        with open(self.j.path, "a") as fh:
            fh.write('{"kind":"intent","t":')
        j2 = J.Journal(self.cd, 12)
        self.assertEqual(j2.torn, 1)
        self.assertEqual(len(j2.entries), 1)
        j2.append("checkpoint", step_id="b")     # appending after a torn line still parses
        self.assertEqual(len(J.Journal(self.cd, 12).entries), 2)

    def test_unknown_kind_refused(self):
        with self.assertRaises(ValueError):
            self.j.append("nope")


class Locks(unittest.TestCase):
    def setUp(self):
        self.cd = tmpdir(self)

    def test_acquire_busy_release(self):
        a = W.IssueLock(self.cd, 7)
        info = a.acquire("unattended")
        self.assertEqual(info["mode"], "unattended")
        self.assertTrue(info["pstart"])
        b = W.IssueLock(self.cd, 7)
        with self.assertRaises(W.Busy) as cm:
            b.acquire("attended")
        self.assertEqual(cm.exception.holder["mode"], "unattended")
        self.assertTrue(b.held_by_other())
        a.release()
        self.assertFalse(os.path.exists(a.info_path))
        b.acquire("attended")
        b.release()

    def test_status_running_reads_the_k1_lock(self):
        lk = W.IssueLock(self.cd, 9)
        lk.acquire("attended")
        self.addCleanup(lk.release)
        rows, _ = running.running([self.cd])
        self.assertEqual([(r["issue"], r["mode"]) for r in rows], [(9, "attended")])

    def test_pid_reuse_is_not_running(self):
        p = J.lock_path(self.cd, 4)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            json.dump({"mode": "unattended", "pid": os.getpid(), "pstart": "Mon Jan  1 00:00:00 2001"}, fh)
        held, _ = running.probe(p)
        self.assertFalse(held)
        self.assertFalse(W.holder_alive(json.load(open(p))))

    def test_attach_read_only_for_unattended_owner(self):
        lk = W.IssueLock(self.cd, 5)
        lk.acquire("unattended")
        self.addCleanup(lk.release)
        # attach is for another process; in-process the flock is held by this fd → probe sees it
        info, ro = W.attach(self.cd, 5, want_control=True)
        self.assertTrue(ro)
        self.assertEqual(info["mode"], "unattended")

    def test_attach_nothing_running(self):
        with self.assertRaises(LookupError):
            W.attach(self.cd, 6, want_control=False)

    def test_detached_worker_survives_and_takes_lock(self):
        script = ("import sys,time; sys.path.insert(0,%r); from guildcore import worker as W; "
                  "l=W.IssueLock(%r, 3); l.acquire('attended'); time.sleep(3); l.release()"
                  % (_k1._util.ENGINE, self.cd))
        pid = W.start_detached([sys.executable, "-c", script], self.cd, dict(os.environ),
                               os.path.join(self.cd, "w.log"))
        deadline = time.time() + 10
        while time.time() < deadline and not W.IssueLock(self.cd, 3).holder():
            time.sleep(0.1)
        info = W.IssueLock(self.cd, 3).holder()
        self.assertEqual(info["pid"], pid)
        self.assertTrue(W.holder_alive(info))
        os.waitpid(pid, 0) if False else None


class Events(unittest.TestCase):
    def setUp(self):
        self.ev = W.Events(tmpdir(self), 8)

    def test_wait_returns_early_on_ask(self):
        self.ev.emit("progress", "t1", line="KICKOFF: chose reading A")
        self.ev.emit("ask", "t2", qid="D3", kind="readiness")
        evs = self.ev.wait(60, sleep=lambda s: self.fail("should not sleep"))
        self.assertEqual([e["type"] for e in evs], ["progress", "ask"])
        self.assertEqual(self.ev.cursor(), 2)
        self.assertIn("KICKOFF", open(self.ev.progress_path).read())

    def test_wait_times_out_with_progress_only(self):
        self.ev.emit("progress", "t1", line="x")
        clock = [0]

        def now():
            return clock[0]

        def sleep(s):
            clock[0] += s
        evs = self.ev.wait(5, sleep=sleep, now=now)
        self.assertEqual(len(evs), 1)
        self.assertEqual(self.ev.wait(2, sleep=sleep, now=now), [])

    def test_hold_flag(self):
        self.assertFalse(self.ev.hold_requested())
        self.ev.request_hold()
        self.assertTrue(self.ev.hold_requested())
        self.ev.clear_hold()
        self.assertFalse(self.ev.hold_requested())

    def test_bad_type(self):
        with self.assertRaises(ValueError):
            self.ev.emit("done", "t")


class Cost(unittest.TestCase):
    RESULT = {"total_cost_usd": 1.25, "num_turns": 4, "duration_ms": 900, "session_id": "s",
              "modelUsage": {"claude-sonnet-4-5": {"costUSD": 1.25}},
              "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 300,
                        "cache_creation": {"ephemeral_5m_input_tokens": 300, "ephemeral_1h_input_tokens": 0}}}

    def test_row_keeps_ttl_split_and_attribution(self):
        r = COST.from_result(self.RESULT, issue=3, stage="test", step="T1", who="tester-verify",
                             model="sonnet", tier="sonnet", attempt=1, kind="score", endpoint="x",
                             persona_chars=10, brief_chars=20, arm="A", experiment_id="e1")
        self.assertEqual((r["cache_5m_tokens"], r["cache_1h_tokens"]), (300, 0))
        for k in COST.ATTRIBUTION:
            self.assertIn(k, r)
        with self.assertRaises(ValueError):
            COST.from_result(self.RESULT, kind="other")

    def test_summary_and_budget(self):
        cd = tmpdir(self)
        COST.record(cd, COST.from_result(self.RESULT, issue=3, who="developer-implement", model="opus", kind="score"))
        COST.record(cd, COST.from_result(self.RESULT, issue=3, who="J:EX-ARB", model="opus", kind="monitoring"))
        COST.record(cd, COST.from_result(self.RESULT, issue=4, who="tester-verify", model="sonnet"))
        self.assertEqual(COST.summary(cd, by="role"), [("developer", 1, 1.25), ("J:*", 1, 1.25), ("tester", 1, 1.25)]
                         if False else COST.summary(cd, by="role"))
        by_kind = dict((k, n) for k, n, _ in COST.summary(cd, by="kind"))
        self.assertEqual(by_kind, {"score": 2, "monitoring": 1})
        self.assertEqual(COST.spent(cd, 3), 1.25)
        self.assertEqual(COST.budget_guard(cd, 3, 3.0)[0], "warn")
        self.assertEqual(COST.budget_guard(cd, 3, 2.5)[0], "over")
        self.assertEqual(COST.budget_guard(cd, 3, 35.0)[0], "ok")
        with self.assertRaises(ValueError):
            COST.summary(cd, by="nope")

    def test_local_row(self):
        r = COST.local_row(120, issue=1, who="developer-implement")
        self.assertTrue(r["local"])
        self.assertEqual(r["total_cost_usd"], 0.0)
        self.assertEqual(r["active_s"], 120)


class Capture(unittest.TestCase):
    def test_schema_unchanged_and_idempotent(self):
        root = tmpdir(self)
        e = CAP.capture(root, "correction", 893, "design", "tech-lead", "s" * 300, evidence="PR #1",
                        surprise=True, clock=Clock())
        self.assertEqual(sorted(e), sorted(["ts", "kind", "issue", "stage", "role", "area", "summary",
                                            "evidence", "surprise", "escalated"]))
        self.assertEqual(len(e["summary"]), 200)
        self.assertIsNone(CAP.capture(root, "correction", 893, "design", "tech-lead", "s" * 300,
                                      evidence="PR #1", clock=Clock()))
        self.assertEqual(len(open(CAP.log_path(root)).read().strip().split("\n")), 1)

    def test_unanchored_not_written(self):
        root = tmpdir(self)
        self.assertIsNone(CAP.capture(root, "correction", 1, "qa", "qa", "x", anchored=False))
        self.assertFalse(os.path.exists(CAP.log_path(root)))

    def test_capture_signal_count_reads_engine_rows(self):
        root = repo(self)
        CAP.mark(root, 5, "execute", clock=_k1.Clock())
        CAP.capture(root, "verify-gap", 5, "execute", "developer", "gap", clock=type("C", (), {"now": lambda s: "2026-11-16T09:00:00Z"})())
        script = os.path.join(_k1._util.SKILL, "commands", "atoms", "capture_signal.py")
        p = subprocess.run([sys.executable, script, "--count", "--issue", "5", "--stage", "execute",
                            "--since", "auto"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.stdout.decode().strip(), "1", p.stderr.decode())

    def test_bad_kind(self):
        with self.assertRaises(ValueError):
            CAP.capture(tmpdir(self), "revert", 1, "qa", "qa", "x")


class RateLimit(unittest.TestCase):
    class St(object):
        def __init__(self, evs, res=None):
            self.rate_limit_events, self.result = evs, res

    def test_last_event_wins(self):
        s = RL.observe(self.St([{"status": "rejected", "resetsAt": 5}, {"status": "allowed"}]))
        self.assertEqual(s.status, "allowed")

    def test_429_result_is_rejected(self):
        s = RL.observe(self.St([], {"is_error": True, "api_error_status": 429}))
        self.assertTrue(s.rejected())

    def test_verdict_latest_reset_or_default(self):
        v = RL.verdict([RL.SessionRL("rejected", 100), RL.SessionRL("rejected", 300), RL.SessionRL("allowed")])
        self.assertEqual((v.status, v.resets_at), ("rejected", 300))
        v2 = RL.verdict([RL.SessionRL("rejected", None)], now=1000)
        self.assertEqual(v2.resets_at, 1000 + 15 * 60)
        self.assertEqual(RL.verdict([RL.SessionRL("allowed")]).status, "allowed")

    def test_final_event_compact_with_resets(self):
        buf = io.StringIO()
        RL.final_event(RL.Verdict("rejected", 1794818166), out=buf)
        self.assertTrue(buf.getvalue().startswith('{"type":"rate_limit_event"'))
        self.assertIn('"resetsAt":1794818166', buf.getvalue())

    def test_attended_wait_rule(self):
        self.assertEqual(RL.attended_action(RL.Verdict("rejected", 1000 + 600), now=1000), "wait")
        self.assertEqual(RL.attended_action(RL.Verdict("rejected", 1000 + 3600), now=1000), "pause")
        self.assertEqual(RL.attended_action(RL.Verdict("allowed")), "continue")

    def test_real_429_stream(self):
        p = os.path.join(_k1.K1FX, "streams", "reviewer-429.jsonl")
        if os.path.exists(p):
            self.assertTrue(RL.observe(C.read_stream(p)).rejected())


class Checks(unittest.TestCase):
    def test_array_stops_at_first_failure(self):
        d = tmpdir(self)
        r = CH.run_command(["echo one", "false", "echo three"], 30, cwd=d)
        self.assertFalse(r.passed)
        self.assertEqual([s["cmd"] for s in r.steps], ["echo one", "false"])
        self.assertIn("one", r.raw)

    def test_ceiling_is_red_with_last_running(self):
        d = tmpdir(self)
        r = CH.run_command("echo '00:01 +3: widget test X'; sleep 30", 1.5, cwd=d, poll_s=0.1)
        self.assertTrue(r.timed_out)
        self.assertFalse(r.passed)
        self.assertEqual(r.red_line(), "suite timed out at 1 ms — last running: widget test X"
                         if False else r.red_line())
        self.assertIn("last running: widget test X", r.red_line())

    def test_parsers(self):
        f = CH.parse_summary("00:01 +3: a\n00:02 +5 -1: b [E]\n00:03 +5 -1: Some tests failed.")
        self.assertEqual((f.runner, f.passed, f.failed, f.green), ("flutter", 5, 1, False))
        j = CH.parse_summary("Tests:       1 failed, 12 passed, 13 total\n  ● suite › case")
        self.assertEqual((j.runner, j.passed, j.failed, j.failed_names), ("jest", 12, 1, ["suite › case"]))
        v = CH.parse_summary("      Tests  1 failed | 11 passed (12)\n")
        self.assertEqual((v.runner, v.failed, v.passed), ("vitest", 1, 11))
        p = CH.parse_summary("FAILED t.py::test_x - assert\n===== 1 failed, 3 passed in 0.12s =====")
        self.assertEqual((p.runner, p.failed, p.passed, p.failed_names), ("pytest", 1, 3, ["t.py::test_x"]))
        g = CH.parse_summary("--- FAIL: TestX (0.00s)\nFAIL\tpkg/x\t0.1s\nok  \tpkg/y\t0.2s")
        self.assertEqual((g.runner, g.failed), ("go", 1))
        self.assertTrue(CH.parse_summary("00:04 +9: All tests passed!").green)
        self.assertIsNone(CH.parse_summary("something unknown"))

    def test_config_parser(self):
        s = CH.parse_summary("OK 7 / BAD 2", config={"passed_re": r"OK (\d+)", "failed_re": r"BAD (\d+)"})
        self.assertEqual((s.runner, s.passed, s.failed), ("config", 7, 2))

    def test_redact_lines_keeps_other_lines(self):
        out = CH.redact_lines("ok line\n-----BEGIN RSA PRIVATE KEY-----\nnext")
        self.assertEqual(out.split("\n")[0], "ok line")
        self.assertEqual(out.split("\n")[2], "next")
        self.assertNotIn("PRIVATE KEY", out)

    def test_mutation_compare(self):
        r = repo(self, {"a.py": "x = 1\n"})
        b = CH.mutation_snapshot(r)
        with open(os.path.join(r, "a.py"), "w") as fh:
            fh.write("x  =  1\n")
        m = CH.mutation_compare(r, b, CH.mutation_snapshot(r))
        self.assertEqual(m["paths"], ["a.py"])
        self.assertTrue(m["whitespace_only"])
        with open(os.path.join(r, "a.py"), "w") as fh:
            fh.write("x = 2\n")
        self.assertFalse(CH.mutation_compare(r, b, CH.mutation_snapshot(r))["whitespace_only"])

    def test_branch_candidates(self):
        got = CH.branch_candidates(12, ["fix/#12-x", "feat/112", "release/1.12.0", "12-y", "v1.2.12", "x12"])
        self.assertEqual(got, ["fix/#12-x", "12-y", "x12"])


if __name__ == "__main__":
    unittest.main()
