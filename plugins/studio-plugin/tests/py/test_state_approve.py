"""M0b-2: evidence, shown and approve (m0b2-plan §7.2, §7.3)."""

import json
import os
import signal
import subprocess
import sys
import time

import helpers
from approve_base import SESSION, ApproveCase, stamp
from stdo import paths
from stdo.state import evidence
from stdo.state.argv import argv_sha, canonical

DRIVER = os.path.join(helpers.HERE, "drivers", "state_driver.py")


class Evidence(ApproveCase):
    def ready_1(self):
        for st in ("script", "verify"):
            self.assertEqual(self.cli("stage-done", "v1", st), 0, self.last_err)
        return self.show("1")

    def test_e1_missing_broken_old_future(self):
        h = self.ready_1()
        self.assertEqual(self.cli("approve", "v1", "1", "--expect", h), 6)
        with open(evidence.pending_path(self.repo), "w") as f:
            f.write("{")
        self.assertEqual(self.cli("approve", "v1", "1", "--expect", h), 6)
        self.assertEqual(self.approve("1", h, written_at=stamp(time.time() - 700)), 6)
        self.assertEqual(self.approve("1", h, written_at=stamp(time.time() + 300)), 6)
        self.assertEqual(self.approve("1", h), 0, self.last_err)

    def test_e2_argv_binding(self):
        h = self.ready_1()
        self.pend(["approve", "v1", "1", "--expect", "000000000000"], "승인 v1 %s" % h)
        self.assertEqual(self.cli("approve", "v1", "1", "--expect", h), 6)
        self.assertEqual(canonical(["approve", "v1", "1", "--expect=%s" % h, "--lang", "ko"]),
                         canonical(["approve", "--lang=ko", "v1", "1", "--expect", h]))
        self.pend(["approve", "v1", "1", "--expect", h, "--lang", "ko"], "승인 v1 %s" % h)
        self.assertEqual(self.cli("approve", "--lang=ko", "v1", "1", "--expect=%s" % h), 0, self.last_err)

    def test_e3_other_session(self):
        h = self.ready_1()
        self.assertEqual(self.approve("1", h, session="another"), 6)

    def test_e4_one_use(self):
        h = self.ready_1()
        self.assertEqual(self.approve("1", h, tool="toolu_x", index=0), 0, self.last_err)
        self.assertEqual(self.approve("1", h, tool="toolu_x", index=0), 6)
        self.assertIn("used already", self.last_err)
        self.assertEqual(self.approve("1", h, tool="toolu_x", index=1), 0, self.last_err)

    def test_e5_only_the_fixed_label(self):
        h = self.ready_1()
        for ans in ("Other: looks fine", "승인 v1 000000000000", "승인 v1 %s " % h, "승인 v1  %s" % h):
            self.assertEqual(self.approve("1", h, answer=ans), 6, ans)
        self.assertFalse(self.state()["langs"]["ko"]["approved"].get("1"))

    def test_e6_proxy_mode(self):
        h = self.ready_1()
        self.assertEqual(self.approve("1", h, mode="proxy", question="proxy"), 6)
        self.assertEqual(self.approve("1", h, "--proxy"), 6)
        self.assertEqual(self.approve("1", h, "--proxy", mode="proxy", question="proxy", tool="toolu_bash9"), 0,
                         self.last_err)
        self.assertEqual(self.state()["langs"]["ko"]["approved"]["1"]["approved_by"], "proxy")

    def test_e7_effects_of_a_success(self):
        h = self.ready_1()
        self.cli("loop", "v1", "verify")
        self.assertEqual(self.approve("1", h, reason="ok by me"), 0)
        self.assertFalse(os.path.exists(evidence.pending_path(self.repo)))
        with open(evidence.consumed_path(self.repo)) as f:
            lines = [json.loads(l) for l in f]
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["session_id"], lines[0]["video"]), (SESSION, "v1"))
        ev = [e for e in self.events() if e.get("event") == "approve"][-1]
        self.assertEqual(ev["record"]["answer"]["answer"], "승인 v1 %s" % h)
        self.assertEqual(ev["record"]["answer"]["reason"], "ok by me")
        L = self.state()["langs"]["ko"]
        self.assertEqual((L["loops"]["verify"], L["done_stages"]), (0, []))
        self.assertEqual(self.state()["source"]["approved_hash"], "src1")

    def test_e8_crash_after_consumption_loses_the_approval(self):
        h = self.ready_1()
        argv = ["approve", "v1", "1", "--expect", h]
        self.pend(argv, "승인 v1 %s" % h, tool="toolu_crash")
        ins = os.path.join(self.tmp, "ins.json")
        with open(ins, "w") as f:
            json.dump(self.ins, f)
        out = subprocess.run([sys.executable, "-B", DRIVER, "--kill", "after_log", "--inspect", ins, "--"] + argv,
                             cwd=self.repo, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, -signal.SIGKILL)
        self.assertFalse(self.state()["langs"]["ko"]["approved"].get("1"))  # not approved
        self.assertIn((SESSION, "toolu_crash", 0), evidence.consumed_keys(self.repo))  # but consumed
        self.assertEqual(self.cli(*argv), 6)  # the same answer cannot be used: ask again

    def test_e9_consumption_lock_busy(self):
        h = self.ready_1()
        self.pend(["approve", "v1", "1", "--expect", h], "승인 v1 %s" % h)
        lock = paths.consumed_lock(self.repo)
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        holder = subprocess.Popen([sys.executable, "-B", "-c",
                                   "import fcntl,os,sys,time; fd=os.open(sys.argv[1], os.O_RDWR|os.O_CREAT); "
                                   "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(30)", lock],
                                  stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            self.assertEqual(self.cli("approve", "v1", "1", "--expect", h), 5)
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()

    def test_argv_sha_is_shared(self):
        self.assertEqual(argv_sha(["approve", "v1", "1", "--expect", "x"]),
                         argv_sha(["approve", "v1", "--expect=x", "1"]))


class ClaimsMap(ApproveCase):
    def test_minor1_1_and_4b_fail_closed_without_a_claims_map(self):
        for st in ("script", "verify"):
            self.cli("stage-done", "v1", st)
        h = self.show("1")
        for body in (None, "{", {"excerpts": "x"}, ["x"]):
            p = os.path.join(self.vdir, "work", "ko", "claims-map.json")
            if body is None:
                os.remove(p)
            else:
                self.claims(body)
            self.assertEqual(self.approve("1", h), 1, body)
            self.assertIn("claims map", self.last_err)
        self.claims({"excerpts": []})
        self.assertEqual(self.approve("1", h), 0, self.last_err)

    def test_minor1_4b_needs_copy_excerpts(self):
        self.pass_all(upto="4a")
        self.cli("stage-done", "v1", "copy", "--platform", "youtube")
        h = self.show("4b", "youtube")
        self.claims({"excerpts": [], "copy_excerpts": {}})
        self.assertEqual(self.approve("4b", h), 1)
        self.claims({"excerpts": [], "copy_excerpts": {"youtube": []}})
        self.assertEqual(self.approve("4b", h), 0, self.last_err)

    def test_bad_pending_types_are_6(self):
        for st in ("script", "verify"):
            self.cli("stage-done", "v1", st)
        h = self.show("1")
        argv = ["approve", "v1", "1", "--expect", h]
        for bad in ({"question_index": "0"}, {"question_index": True}, {"tool_use_id": None}, {"tool_use_id": ""}):
            ev = self.pend(argv, "승인 v1 %s" % h)
            ev.update(bad)
            with open(evidence.pending_path(self.repo), "w") as f:
                json.dump(ev, f)
            self.assertEqual(self.cli(*argv), 6, bad)
            self.assertNotIn("Traceback", self.last_err)


class Shown(ApproveCase):
    outputs = ("youtube", "shorts")
    platforms = {"youtube": ["youtube"], "sns": ["shorts"]}

    def test_s1_hash12_needs_every_scope(self):
        self.pass_all(upto="3")
        for o in self.outputs:
            for st in ("render",):
                self.cli("stage-done", "v1", st, "--output", o)
        self.assertIsNone(self.show("4a", "youtube"))
        h = self.show("4a", "shorts")
        self.assertTrue(h)
        self.assertEqual(h, self.show("4a", "youtube"))  # order does not matter

    def test_s2_two_changed_only_one_shown_again(self):
        self.pass_all(upto="4a")
        self.render_files("youtube", b"v2")
        self.render_files("shorts", b"v2")
        for o in self.outputs:
            self.cli("stage-done", "v1", "render", "--output", o)
        self.show("4a", "youtube")
        st = self.state()["langs"]["ko"]["shown"]["4a"]
        h = self.hash12_of() or "000000000000"
        self.assertEqual(self.approve("4a", h), 1)  # shorts was not shown again
        self.assertTrue(st)

    def test_s3_snapshot_begin_end(self):
        self.pass_all(upto="2")
        for o in self.outputs:
            for st in ("board", "visual-check"):
                self.cli("stage-done", "v1", st, "--output", o)
        self.assertEqual(self.cli("shown", "v1", "3", "--output", "youtube", "--end"), 2)
        self.frames("youtube")  # stills from an earlier snapshot exist
        self.assertEqual(self.cli("shown", "v1", "3", "--output", "youtube", "--begin"), 0)
        self.assertEqual(self.cli("shown", "v1", "3", "--output", "youtube", "--end"), 1)  # not written again
        self.frames("youtube")
        self.ins["hashes"]["presentation_by_output"]["youtube"] = "p-moved"
        self.assertEqual(self.cli("shown", "v1", "3", "--output", "youtube", "--end"), 1)
        self.assertEqual(self.state()["langs"]["ko"]["shown_pending"]["youtube"]["fails"], 1)
        self.ins["hashes"]["presentation_by_output"]["youtube"] = "p-youtube"
        self.assertIsNone(self.show("3", "youtube"))  # shorts not shown yet
        h1 = self.show("3", "shorts")
        self.assertTrue(h1)
        h2 = self.show("3", "shorts")  # same input shot again: same content, recorded, same hash12
        self.assertEqual(h1, h2)

    def test_s4_expect_earlier_work_held(self):
        for st in ("script", "verify"):
            self.cli("stage-done", "v1", st)
        h = self.show("1")
        self.assertEqual(self.approve("1", "abcdefabcdef"), 1)
        self.assertEqual(self.approve("2", h), 3)
        st = self.state()
        st["langs"]["ko"]["held"] = {"state": "render"}
        with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
            json.dump(st, f)
        self.assertEqual(self.approve("1", h), 4)

    def test_s6_upstream_change_after_shown_needs_showing_again(self):
        self.pass_all(upto="2")
        for o in self.outputs:
            for st in ("board", "visual-check"):
                self.cli("stage-done", "v1", st, "--output", o)
        for o in self.outputs:
            h3 = self.show("3", o)
        # ② redone with new audio and approved again
        self.ins["hashes"]["audio"] = "a2"
        self.cli("stage-done", "v1", "audition")
        h2 = self.show("2")
        self.assertEqual(self.approve("2", h2), 0, self.last_err)
        for o in self.outputs:
            for st in ("board", "visual-check"):
                self.cli("stage-done", "v1", st, "--output", o)
        self.assertEqual(self.approve("3", h3), 1)  # no new snapshot: refused
        self.assertIn("changed after it was shown", self.last_err)

    def test_s7_4b_after_a_render_change(self):
        self.pass_all()
        h4b = self.show("4b", "youtube")
        self.show("4b", "sns")
        self.render_files("youtube", b"v3")
        self.cli("stage-done", "v1", "render", "--output", "youtube")
        h = self.show("4a", "youtube")
        self.show("4a", "shorts")
        self.assertEqual(self.approve("4a", self.hash12_of() or h), 0, self.last_err)
        self.cli("stage-done", "v1", "copy", "--platform", "youtube")
        self.assertEqual(self.approve("4b", h4b), 1)


class Effects(ApproveCase):
    def test_s5_approval_spends_loops_and_records(self):
        self.pass_gate("1")
        self.cli("stage-done", "v1", "cast")
        self.cli("loop", "v1", "3")
        self.pass_gate("2")
        L = self.state()["langs"]["ko"]
        self.assertEqual([r for r in L["done_stages"] if r["stage"] in ("cast", "tts", "audition")], [])

    def test_proxy_replaced_by_a_person(self):
        for st in ("script", "verify"):
            self.cli("stage-done", "v1", st)
        h = self.show("1")
        self.approve("1", h, "--proxy", mode="proxy", question="proxy")
        self.assertEqual(self.state()["langs"]["ko"]["approved"]["1"]["approved_by"], "proxy")
        self.assertEqual(self.cli("status"), 0)
        self.assertIn("approved by proxy", self.last_out)
        self.assertEqual(self.approve("1", h), 0)
        self.assertEqual(self.state()["langs"]["ko"]["approved"]["1"]["approved_by"], "human")
