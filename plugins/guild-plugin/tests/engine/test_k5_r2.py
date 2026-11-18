"""K5 review r2 — regressions for M1 and the minors (review-k5-r2.md).

M1  an engine-level question (the per-Issue budget) has the ENGINE scope: `decisions.live` never supersedes it by a
    stage mismatch, so the §2.5 resume reaches the answer channel. Every case runs the REAL resume path
    (`dev run` → restart check → `Driver.run` → `Driver.resume` → boundary), never the boundary alone:
    unattended member answer → one raise, the stage runs · attended session end → resume asks the SAME D-id →
    `dev answer` → the stage runs · an outsider's answer is rejected · a stale stage question's answer is named
    in its superseded block · the pending-regeneration question waits at execute
m1  a parent driving a child mirrors its role / judge pid records into the child's own journal
m2  the create-settle wait is named on stdout (`rate_limit_info.reason`), never a bare rate limit
m3  the engine's halted reasons are listed in daily.md and run.md
m7  the settle resume takes back only the engine's OWN needs-human
m4  a child driven by its parent's attended run is read-only to a second driver (no hold / note on the child)
m6  the test isolation guard: ~/.claude/<sub>, a cloud-provider switch, a `claude-*` binary name
m8  a GitHub outage with no writable pause is exit 75 `gh-service` (unattended), never exit 1
"""

import json
import os
import unittest

import _util  # noqa: F401
from _k2 import CFG, comment
from test_k5_cli import Env

from guildcore import cost as COST
from guildcore import decisions as D
from guildcore.decisions import DecisionLog
from workflows.dev import cli as CLI
from workflows.dev import fsm as F
from workflows.dev.stages.base import StageResult

BUDGET_CFG = dict(CFG, engine={"budget_usd_per_issue": 35.0})


def blocks(e):
    return DecisionLog.load(e.h.gh.comments(7)).blocks


class M1EngineScope(unittest.TestCase):
    """The real CLI → Driver path with stub stage functions (the stages are not under test)."""

    def _env(self, unattended=True, labels=("guild:execute",)):
        e = Env(self, labels=labels, unattended=unattended, config=BUDGET_CFG)
        self.ran = []
        stages = {"execute": lambda p, v=None: (self.ran.append(p.issue),
                                                StageResult(StageResult.PAUSE, cause="execute stub"))[1]}

        def driver(ports_for, unattended=True, plugin=None, events=None, boundary=None):
            return F.Driver(ports_for, unattended=unattended, plugin=plugin, stages=stages, events=events,
                            boundary=boundary)
        e.d.driver_cls = driver
        COST.record(e.common, {"issue": 7, "total_cost_usd": 36.0, "kind": "score", "who": "developer"})
        return e

    def _answer_line(self, e, qid, token, login="owner", assoc="OWNER", cid=990, remover="owner"):
        it = e.h.issue()
        c = comment("guild-answer: %s %s" % (qid, token), cid, at="2099-01-01T00:00:00Z")
        c.update(user={"login": login}, author_association=assoc)
        it["comments"].append(c)
        it["labels"] = [lb for lb in it["labels"] if lb["name"] != "guild:needs-human"]
        it["timeline"].append({"id": cid + 1, "event": "unlabeled", "label": {"name": "guild:needs-human"},
                               "created_at": "2099-01-01T00:00:01Z", "actor": {"login": remover}})

    def _budget_q(self, e):
        return [b for b in blocks(e) if b.get("kind") == "budget" and b.get("status") == "pending-human"]

    def test_budget_question_has_the_engine_scope_and_live_keeps_it(self):
        e = self._env()
        self.assertEqual(e.run("--unattended"), 0)
        q = self._budget_q(e)[0]
        self.assertEqual(q.get("stage"), D.ENGINE_SCOPE)
        from guildcore import state as ST
        for label in ("guild:execute", "guild:design", "guild:test"):
            alive, why = D.live(q, ST.derive([label]), [{"id": 1, "event": "labeled", "label": {"name": label},
                                                         "created_at": "2099-01-01T00:00:00Z"}])
            self.assertTrue(alive, why)                              # no stage move ever makes it stale

    def test_unattended_member_answer_is_settled_raised_once_and_the_stage_runs(self):
        e = self._env()
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(self.ran, [])                               # stopped at the boundary
        qid = self._budget_q(e)[0].id
        self.assertIn("guild:needs-human", e.h.labels())
        self._answer_line(e, qid, "continue")
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(self.ran, [7])                              # the rerun went on
        bl = blocks(e)
        self.assertFalse([b for b in bl if b.get("status") == "superseded"])
        ans = [b for b in bl if b.get("resolves") == qid]
        self.assertEqual([(b.get("by"), b.get("choice"), b.get("answered_by")) for b in ans],
                         [("human", "continue", "owner")])
        raises = [(b.get("budget_from"), b.get("budget_to")) for b in bl if b.get("point") == "budget"]
        self.assertEqual(raises, [("35.00", "70.00")])
        self.assertEqual(e.run("--unattended"), 0)                   # a third run: never raised twice
        self.assertEqual(len([b for b in blocks(e) if b.get("point") == "budget"]), 1)

    def test_unattended_label_still_on_waits_without_a_new_question(self):
        e = self._env()
        e.run("--unattended")
        n0 = len(blocks(e))
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(len(blocks(e)), n0)                         # nothing written, nothing superseded
        self.assertEqual(self.ran, [])
        res = json.loads(e.lines()[-1])
        self.assertIn("waiting for a human answer", res["result"])

    def test_unattended_outsider_answer_is_rejected_and_asked_again(self):
        e = self._env()
        e.run("--unattended")
        qid = self._budget_q(e)[0].id
        self._answer_line(e, qid, "continue", login="stranger", assoc="NONE", remover="stranger")
        self.assertEqual(e.run("--unattended"), 0)
        self.assertEqual(self.ran, [])
        bl = blocks(e)
        self.assertTrue([b for b in bl if b.get("point") == "rejected-answer" and b.get("refs") == qid])
        self.assertFalse([b for b in bl if b.get("point") == "budget"])           # no raise
        open_q = [b for b in self._budget_q(e) if b.id not in DecisionLog.load(e.h.gh.comments(7)).resolved_ids()]
        self.assertEqual(len(open_q), 1)                             # rule 3 re-judged → asked anew, still paused
        self.assertNotEqual(open_q[0].id, qid)
        self.assertIn("guild:needs-human", e.h.labels())

    def test_attended_session_end_resume_asks_same_qid_then_answer_proceeds(self):
        e = self._env(unattended=False)
        self.assertEqual(e.run("--attended", "--worker"), 0)
        qid = self._budget_q(e)[0].id
        e.h.events[:] = []
        self.assertEqual(e.run("--attended", "--worker"), 0)         # the session ended; /gld resume 7
        asks = [kw for what, kw in e.h.events if what == "ask"]
        evs = [ev for ev in __import__("guildcore.worker", fromlist=["Events"]).Events(e.common, 7).read()
               if ev.get("type") == "ask"]
        self.assertEqual([a["qid"] for a in asks + evs][-1], qid)     # the SAME question, not a hold
        self.assertEqual(self.ran, [])
        self.assertFalse([b for b in blocks(e) if b.get("status") == "superseded"])
        rc = CLI.main(["answer", "--issue", "7", "--qid", qid, "--choice", "continue"], e.d)
        self.assertEqual(rc, 0, e.out.getvalue())
        self.assertEqual(e.run("--attended", "--worker"), 0)
        self.assertEqual(self.ran, [7])
        self.assertEqual([(b.get("budget_from"), b.get("budget_to")) for b in blocks(e) if b.get("point") == "budget"],
                         [("35.00", "70.00")])

    def test_stale_stage_question_names_the_read_answer_in_its_superseded_block(self):
        e = Env(self, labels=("guild:execute",))
        from guildcore import ask as ASK
        q = ASK.Question("design-block", "q", [{"token": "stop", "label": "stop"}])
        did = e.h.decisions.record(q.pending_fields(stage="design"))
        e.h.decisions.stamp_server_time(did)
        self._answer_line(e, did, "stop")
        drv = F.Driver(lambda n, s, v=None: e.h.p, unattended=True,
                       stages={"execute": lambda p, v=None: StageResult(StageResult.PAUSE, cause="x")})
        drv.run(7)
        sup = [b for b in blocks(e) if b.get("resolves") == did]
        self.assertEqual(len(sup), 1)
        self.assertEqual(sup[0].get("status"), "superseded")
        self.assertEqual(sup[0].get("by"), "code")                   # never applied as a human answer
        self.assertIn("answer `stop` by owner read, not applied", sup[0].get("reason"))
        self.assertEqual(str(sup[0].get("answer_comment")), "990")

    def test_pending_regeneration_waits_at_execute(self):
        from guildcore import ask as ASK
        from guildcore import state as ST
        q = ASK.Question("pending-regeneration", "t", [{"token": "ok", "label": "ok"}], waits_at="execute")
        f = q.pending_fields(stage="test")
        self.assertEqual(f["waits_at"], "execute")
        from guildcore.records import decisions as fmt
        blk = fmt.DecisionComment(fmt.render_comment([fmt.render_block(3, dict(f, id="D3"))])).blocks[0]
        self.assertTrue(D.live(blk, ST.derive(["guild:execute"]), [])[0])
        self.assertFalse(D.live(blk, ST.derive(["guild:test"]), [])[0])


class Minors(unittest.TestCase):
    def test_m1_child_pids_are_mirrored_into_the_childs_journal(self):
        from guildcore import journal as J
        from test_k5_r1 import child_ports, kid, real_driver
        e = Env(self, labels=("guild:children",), issues={"8": kid(8)})
        e.d.ports_for = child_ports(e)
        recorded = []

        def an(p, **k):
            e.h.journal.record_pid("developer", 424242, 424242, "t0")   # the parent's runner journal
            recorded.append(p.issue)
            return StageResult(StageResult.PAUSE, cause="stub")
        e.d.driver_cls = real_driver({"analyze": an})
        e.run("--unattended")
        self.assertEqual(recorded, [8])
        j8 = [x for x in J.Journal(e.h.p.git_dir, 8).pids() if x.get("pid") == 424242]
        self.assertEqual(len(j8), 1)
        self.assertEqual(j8[0].get("via"), 7)
        self.assertEqual(j8[0].get("owner"), os.getpid())                 # the owner rule still applies
        self.assertIsNone(e.h.journal.pid_mirror)                          # the parent's own records no longer mirror

    def test_m2_settle_wait_carries_its_reason_on_stdout(self):
        import io
        out = io.StringIO()
        F.final_events(F.retry_outcome(None, 2000000000), 0.0, out=out)
        ev = json.loads(out.getvalue().split("\n")[0])
        self.assertEqual(ev["rate_limit_info"]["reason"], "create-settle")
        self.assertTrue(json.loads(out.getvalue().split("\n")[1])["result"].startswith("create-settle-wait:"))
        out2 = io.StringIO()
        F.final_events(F.Outcome(None, 75, "rate limited"), 0.0, out=out2)
        self.assertNotIn("reason", json.loads(out2.getvalue().split("\n")[0])["rate_limit_info"])

    def test_m3_engine_halt_reasons_in_daily_and_run(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "skills", "gld", "commands", "sprint")
        for name in ("daily.md", "run.md"):
            with open(os.path.join(base, name), encoding="utf-8") as fh:
                txt = fh.read()
            for r in ("engine-kill-switch", "plugin-version-changed", "engine-gh-auth", "engine-env-"):
                self.assertIn(r, txt, "%s lacks %s" % (name, r))

    def _settle_env(self, own):
        from guildcore import journal as J
        import time
        e = Env(self, labels=("guild:design", "guild:needs-human"))
        e.h.issue()["timeline"].append({"id": 501, "event": "labeled", "label": {"name": "guild:needs-human"},
                                        "created_at": "2026-11-18T00:00:00Z", "actor": {"login": "owner"}})
        J.Journal(e.common, 7).own_write("label", event_id=501, event="labeled", label="guild:needs-human", target=7)
        if not own:                                                    # a person took it off and put it back
            e.h.issue()["timeline"].append({"id": 610, "event": "labeled", "label": {"name": "guild:needs-human"},
                                            "created_at": "2026-11-18T00:05:00Z", "actor": {"login": "owner"}})
        J.Journal(e.common, 7).append("event", what="retry-after", at=int(time.time()) - 5)
        return e

    def test_m7_settle_resume_keeps_a_persons_needs_human(self):
        from test_k5_cli import FakeDriver
        e = self._settle_env(own=False)
        self.assertEqual(e.run("--unattended"), 0)
        self.assertIn("guild:needs-human", e.h.labels())
        self.assertEqual(FakeDriver.calls, [])
        self.assertIn("someone other than the engine", json.loads(e.lines()[-1])["result"])

    def test_m7_settle_resume_takes_back_its_own(self):
        from test_k5_cli import FakeDriver
        e = self._settle_env(own=True)
        self.assertEqual(e.run("--unattended"), 0)
        self.assertNotIn("guild:needs-human", e.h.labels())
        self.assertEqual(FakeDriver.calls, [(7, None, True)])

    def test_m4_child_driven_by_parent_is_read_only(self):
        from guildcore import worker as W
        e = Env(self, n=8, labels=("guild:child", "guild:analyze"))
        lk = W.IssueLock(e.common, 8)
        lk.acquire("attended", driven_by=7)
        self.addCleanup(lk.release)
        self.assertEqual(CLI.main(["hold", "--issue", "8"], e.d), 4)
        self.assertIn("driven by #7", e.lines()[-1])
        self.assertEqual(CLI.main(["run", "--issue", "8", "--attended"], e.d), 0)
        msg = json.loads(e.lines()[-1].split("<<<")[-1].strip() if "<<<" in e.lines()[-1] else e.lines()[-1])
        self.assertTrue(msg["read_only"])
        self.assertEqual(msg["driven_by"], 7)
        self.assertEqual(e.spawned, [])                                  # no second worker

    def test_m6_isolation_guard_gaps(self):
        from guildcore.adapters import claude as C
        home = os.path.expanduser("~")
        self.assertFalse(C.isolated_config_dir(os.path.join(home, ".claude", "sub")))
        self.assertFalse(C.isolated_config_dir(os.path.join(home, ".claude-personal")))
        self.assertTrue(C.isolated_config_dir(os.path.join(home, "tmp-cfg")))
        ok_env = {"GLD_ENGINE_TEST": "1", "CLAUDE_CONFIG_DIR": "/tmp/iso", "ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}
        C.test_isolation_guard(["/x/claude"], ok_env)                   # passes
        with self.assertRaises(C.TestIsolation):
            C.test_isolation_guard(["/x/claude"], dict(ok_env, CLAUDE_CODE_USE_BEDROCK="1"))
        with self.assertRaises(C.TestIsolation):
            C.test_isolation_guard(["/x/claude-2.1"], dict(ok_env, ANTHROPIC_BASE_URL=""))

    def _outage(self, unattended):
        from guildcore.adapters.gh import GhError
        e = Env(self, unattended=unattended)

        def down(n, stage, variant=None):
            raise GhError("gh repo view: HTTP 502: Bad Gateway")
        e.d.ports_for = down
        return e

    def test_m8_outage_without_a_pause_is_a_service_wait(self):
        e = self._outage(True)
        self.assertEqual(e.run("--unattended"), 75)
        ev = json.loads(e.lines()[0])
        self.assertEqual(ev["rate_limit_info"]["reason"], "gh-service")
        self.assertTrue(json.loads(e.lines()[1])["result"].startswith("gh-service-wait:"))

    def test_m8_attended_outage_stays_exit_1(self):
        e = self._outage(False)
        self.assertEqual(e.run("--attended", "--worker"), 1)


if __name__ == "__main__":
    unittest.main()
