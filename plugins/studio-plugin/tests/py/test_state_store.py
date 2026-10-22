"""M0b-1 storage and command tests (m0b1-plan §7.3)."""

import contextlib
import errno
import fcntl
import io
import json
import os
import signal
import subprocess
import sys
import time

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo.state import cli, commands, hashes, schema, store
from stdo.state.collect import Providers

DRIVER = os.path.join(helpers.HERE, "drivers", "state_driver.py")
STATE_PY = os.path.join(helpers.SCRIPTS, "state.py")


def inspect_json(outputs=("youtube", "shorts"), **over):
    c = F.current(outputs=outputs)
    d = {"s2v_version": c["s2v_version"], "stale_build": False, "hash_version": 1, "lang": "ko",
         "hashes": {"content": c["content"], "voice": c["voice"], "audio": c["audio"],
                    "presentation_by_output": c["presentation"], "engine": c["engine"]},
         "reasons": {}, "outputs": [{"name": o} for o in outputs]}
    d.update(over)
    return d


class StoreCase(StudioTestCase):
    def setUp(self):
        super().setUp()
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp)
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        os.makedirs(self.vdir)
        st = F.state(outputs=("youtube",), platforms={"youtube": ["youtube"]})
        store.create(self.vdir, st)
        self.paths = store.paths(self.vdir)
        self.providers = Providers(inspect=lambda ctx: inspect_json(), source=lambda ctx, st: ("src1", ""))

    def cli(self, *argv, providers=None, **kw):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), providers=providers or self.providers, cwd=self.repo, **kw)
        return code, out.getvalue(), err.getvalue()

    def brief(self, **b):
        body = {"claims": ["C-1"], "roles": [{"name": "narrator"}], "outputs": ["youtube"],
                "platforms": {"youtube": ["youtube"]}}
        body.update(b)
        p = os.path.join(self.vdir, "work", "brief.json")
        with open(p, "w") as f:
            json.dump(body, f)
        return p

    def state(self):
        return store.read_state(self.vdir)

    def script(self):
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write("# a script exists\n")


class Commands(StoreCase):
    def test_r9_record_brief(self):
        self.script()
        self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief(outputs=[]))[0], 1)
        self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief(platforms={}))[0], 1)
        self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief(outputs=["tiktok"]))[0], 1)
        self.assertEqual(self.cli("record-brief", "v1", "--from",
                                  self.brief(platforms={"youtube": ["shorts"]}))[0], 1)
        self.assertEqual(self.cli("record-brief", "v1", "--from",
                                  self.brief(outputs=["youtube", "shorts"],
                                             platforms={"youtube": ["youtube"], "sns": ["shorts"]}))[0], 0)
        # shorts not approved: may be removed
        self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief())[0], 0)
        self.cli("record-brief", "v1", "--from", self.brief(outputs=["youtube", "shorts"],
                                                            platforms={"youtube": ["youtube"], "sns": ["shorts"]}))
        c = F.current(outputs=("youtube", "shorts"), platforms=("youtube", "sns"))
        st = self.state()
        store.record_approval(self.vdir, "ko", "1", {"tuple": F.literal_tuple("1", c)})
        store.record_approval(self.vdir, "ko", "3", {"tuple": F.literal_tuple("3", c, o="shorts")}, key="shorts")
        code, _, err = self.cli("record-brief", "v1", "--from", self.brief())
        self.assertEqual(code, 3)
        self.assertIn("exclude-output", err)
        self.assertEqual(self.state()["brief"]["outputs"], ["youtube", "shorts"])
        self.assertEqual(st["video"], "v1")

    def test_record_brief_before_the_script_exists(self):
        # the brief comes before the script: no inspect, names checked for form only
        p = Providers(inspect=lambda ctx: (_ for _ in ()).throw(AssertionError("inspect called")),
                      source=lambda ctx, st: ("src1", ""))
        self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief(outputs=["tiktok"],
                                  platforms={"tiktok": ["tiktok"]}), providers=p)[0], 0)
        self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief(outputs=["bad name"],
                                  platforms={"x": ["bad name"]}), providers=p)[0], 1)

    def test_record_brief_removing_an_approved_platform(self):
        self.script()
        self.cli("record-brief", "v1", "--from", self.brief(platforms={"youtube": ["youtube"], "x": ["youtube"]}))
        c = F.current(platforms=("youtube", "x"))
        store.record_approval(self.vdir, "ko", "1", {"tuple": F.literal_tuple("1", c)})
        store.record_approval(self.vdir, "ko", "4b", {"tuple": {}}, key="x")
        seq = self.state()["last_seq"]
        self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief())[0], 3)
        self.assertEqual(self.state()["last_seq"], seq)  # nothing written
        self.assertEqual(store.incomplete(self.vdir), [])

    def test_record_brief_malformed(self):
        for body in ({"platforms": {"youtube": "youtube"}}, {"roles": "narrator"}, {"claims": [1]}):
            self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief(**body))[0], 1, body)
        p = os.path.join(self.vdir, "work", "brief.json")
        with open(p, "w") as f:
            f.write("[1]")
        code, _, err = self.cli("record-brief", "v1", "--from", p)
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_r9_brief_core_is_recorded(self):
        self.assertEqual(self.cli("record-brief", "v1", "--from", self.brief(claims=["C-2", "C-1"]))[0], 0)
        self.assertEqual(self.state()["brief"]["core"],
                         hashes.brief_core(["C-1", "C-2"], [{"name": "narrator"}]))

    def test_r10_loop_stagnation_and_reset_on_approval(self):
        self.assertEqual(self.cli("loop", "v1", "verify")[0], 0)
        self.assertEqual(self.cli("loop", "v1", "3")[0], 0)
        self.assertEqual(self.cli("loop", "v1", "verify")[0], 0)
        self.assertEqual(self.state()["langs"]["ko"]["loops"]["3"], 1)
        code, _, _ = self.cli("loop", "v1", "verify")
        self.assertEqual(code, 4)
        L = self.state()["langs"]["ko"]
        self.assertEqual((L["held"]["state"], L["held"]["detail"]["stage"]), ("stagnation", "verify"))
        store.record_approval(self.vdir, "ko", "1", {"tuple": {}})
        L = self.state()["langs"]["ko"]
        self.assertEqual((L["loops"]["verify"], L["loops"]["1"], L["loops"]["3"]), (0, 0, 1))
        store.record_approval(self.vdir, "ko", "3", {"tuple": {}}, key="youtube")
        self.assertEqual(self.state()["langs"]["ko"]["loops"]["3"], 0)

    def test_loop_does_not_overwrite_held_or_touch_finished(self):
        st = self.state()
        st["langs"]["ko"]["held"] = {"state": "render"}
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        seq = self.state()["last_seq"]
        self.assertEqual(self.cli("loop", "v1", "verify")[0], 4)
        self.assertEqual(self.state()["langs"]["ko"]["held"], {"state": "render"})
        st["langs"]["ko"]["held"] = None
        st["langs"]["ko"]["status"] = "done"
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        self.assertEqual(self.cli("loop", "v1", "verify")[0], 2)
        self.assertEqual((self.state()["last_seq"], store.incomplete(self.vdir)), (seq, []))

    def test_next_on_a_held_video_does_not_inspect(self):
        self.script()
        st = self.state()
        st["langs"]["ko"]["held"] = {"state": "lock"}
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        boom = Providers(inspect=lambda ctx: (_ for _ in ()).throw(AssertionError("inspect called")))
        self.assertEqual(self.cli("next", "v1", providers=boom)[0], 4)

    def test_inspect_lang_mismatch(self):
        self.script()
        p = Providers(inspect=lambda ctx: inspect_json(lang="en"), source=lambda ctx, st: ("src1", ""))
        self.assertEqual(self.cli("next", "v1", providers=p)[0], 1)

    def test_brief_output_missing_from_the_script(self):
        self.script()
        c = F.current(outputs=("youtube",))
        store.record_approval(self.vdir, "ko", "1", {"tuple": F.literal_tuple("1", c), "excerpts": [],
                                                     "hash_version": 1})
        p = Providers(inspect=lambda ctx: inspect_json(outputs=("shorts",)), source=lambda ctx, st: ("src1", ""))
        code, out, _ = self.cli("next", "v1", "--json", providers=p)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["redo"], {"stage": "script", "output": "youtube",
                                                   "why": ["output youtube is not in the script"]})

    def test_missing_frozen_copy_is_1(self):
        self.script()
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)
        with open(os.path.join(self.repo, "docs", "a.md"), "w") as f:
            f.write("# A")
        p = Providers(inspect=lambda ctx: inspect_json())
        code, _, err = self.cli("next", "v1", providers=p)
        self.assertEqual(code, 1)
        self.assertIn("frozen source copy is missing", err)
        os.makedirs(os.path.join(self.vdir, "work", "source"))
        with open(os.path.join(self.vdir, "work", "source", "a.md"), "w") as f:
            f.write("# A")
        self.assertEqual(self.cli("next", "v1", providers=p)[0], 0)

    def test_no_script_yet(self):
        boom = Providers(inspect=lambda ctx: (_ for _ in ()).throw(AssertionError("inspect called")))
        code, out, _ = self.cli("next", "v1", "--json", providers=boom)
        self.assertEqual((code, json.loads(out)["redo"]["stage"]), (0, "script"))
        self.assertEqual(self.cli("next", "v1", "--enter", "script", providers=boom)[0], 0)
        self.assertEqual(self.cli("next", "v1", "--enter", "source", providers=boom)[0], 0)
        self.assertEqual(self.cli("next", "v1", "--enter", "verify", providers=boom)[0], 3)
        st = self.state()
        st["brief"]["core"] = None
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        self.assertEqual(self.cli("next", "v1", "--enter", "script", providers=boom)[0], 3)
        self.assertEqual(self.cli("stage-done", "v1", "script", providers=boom)[0], 1)

    def test_stage_done_command(self):
        self.script()
        c = F.current(outputs=("youtube",))
        store.record_approval(self.vdir, "ko", "1", {"tuple": F.literal_tuple("1", c), "excerpts": [],
                                                     "hash_version": 1})
        self.assertEqual(self.cli("stage-done", "v1", "tts")[0], 3)  # cast comes first
        self.assertEqual(self.cli("stage-done", "v1", "2")[0], 2)  # gates are approved
        self.assertEqual(self.cli("stage-done", "v1", "board")[0], 2)  # needs --output
        self.assertEqual(self.cli("stage-done", "v1", "cast", "--output", "youtube")[0], 2)
        self.assertEqual(self.cli("stage-done", "v1", "cast")[0], 0)
        code, out, _ = self.cli("next", "v1", "--json")
        self.assertEqual(json.loads(out)["redo"]["stage"], "tts")
        rec = self.state()["langs"]["ko"]["done_stages"][0]
        want = {k: v for k, v in F.literal_tuple("2", c).items() if k not in F.LATER["cast"]}
        self.assertEqual((rec["stage"], rec["tuple"]), ("cast", want))
        self.assertEqual(store.read_log(self.vdir)[-1]["event"], "stage-done")
        self.cli("stage-done", "v1", "tts")
        store.record_approval(self.vdir, "ko", "2", {"tuple": F.literal_tuple("2", c), "hash_version": 1})
        self.assertEqual(self.state()["langs"]["ko"]["done_stages"], [])  # spent by the approval

    def test_stage_done_first_pass_through_the_cli(self):
        """Hashes change in production order: cast sets voice, tts makes audio (B-1')."""
        self.script()
        c = F.current(outputs=("youtube",))
        store.record_approval(self.vdir, "ko", "1", {"tuple": F.literal_tuple("1", c), "excerpts": [],
                                                     "hash_version": 1})
        now = inspect_json(outputs=("youtube",))
        now["hashes"]["audio"] = None
        p = Providers(inspect=lambda ctx: now, source=lambda ctx, st: ("src1", ""))
        now["hashes"]["voice"] = "v-cast"  # cast's work
        self.assertEqual(self.cli("stage-done", "v1", "cast", providers=p)[0], 0)
        now["hashes"]["audio"] = "a-tts"  # tts's work
        self.assertEqual(self.cli("stage-done", "v1", "tts", providers=p)[0], 0)
        self.assertEqual(self.cli("stage-done", "v1", "audition", providers=p)[0], 0)
        code, out, _ = self.cli("next", "v1", "--json", providers=p)
        self.assertEqual(json.loads(out)["redo"]["stage"], "2")
        # re-recording a stage replaces its record (S7)
        self.assertEqual(self.cli("stage-done", "v1", "audition", providers=p)[0], 0)
        recs = [r for r in self.state()["langs"]["ko"]["done_stages"] if r["stage"] == "audition"]
        self.assertEqual(len(recs), 1)

    def test_stage_done_refusal_codes(self):
        self.script()
        c = F.current(outputs=("youtube",))
        store.record_approval(self.vdir, "ko", "1", {"tuple": F.literal_tuple("1", c), "excerpts": [],
                                                     "hash_version": 1})
        code, _, err = self.cli("stage-done", "v1", "tts")
        self.assertEqual(code, 3)
        self.assertIn("the work is at cast", err)
        bad = inspect_json()
        bad["hashes"]["voice"] = None
        bad["reasons"] = {"voice": ["persona wav missing"]}
        p = Providers(inspect=lambda ctx: bad, source=lambda ctx, st: ("src1", ""))
        self.cli("stage-done", "v1", "cast", providers=p)
        code, _, err = self.cli("stage-done", "v1", "tts", providers=p)
        self.assertEqual(code, 1)
        self.assertIn("persona wav missing", err)
        # the source changed but every approved excerpt is still there: a person decides (4)
        st = self.state()
        st["source"]["frozen_hash"] = "src2"
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        p2 = Providers(inspect=lambda ctx: inspect_json(), source=lambda ctx, st: ("src2", "text"))
        code, _, err = self.cli("stage-done", "v1", "cast", providers=p2)
        self.assertEqual(code, 4)
        self.assertIn("source-diff", err)
        st = self.state()
        st["langs"]["ko"]["held"] = {"state": "lock"}
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        self.assertEqual(self.cli("stage-done", "v1", "cast")[0], 4)  # S12

    def test_next_exit_codes(self):
        self.script()
        code, out, _ = self.cli("next", "v1", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["redo"]["stage"], "script")
        self.assertEqual(self.cli("next", "v1", "--enter", "tts")[0], 3)
        self.assertEqual(self.cli("next", "v1", "--enter", "board")[0], 2)  # needs --output
        self.assertEqual(self.cli("next", "v1", "--enter", "script")[0], 0)
        p = Providers(inspect=lambda ctx: inspect_json(s2v_version="0.13.0+x"), source=lambda ctx, st: ("src1", ""))
        self.assertEqual(self.cli("next", "v1", providers=p)[0], 4)
        c = F.current(outputs=("youtube",))
        store.record_approval(self.vdir, "ko", "1", {"tuple": F.literal_tuple("1", c), "excerpts": [],
                                                     "hash_version": 1})
        bad = inspect_json()
        bad["hashes"]["voice"] = None
        bad["reasons"] = {"voice": ["persona wav missing"]}
        p = Providers(inspect=lambda ctx: bad, source=lambda ctx, st: ("src1", ""))
        self.assertEqual(self.cli("stage-done", "v1", "cast", providers=p)[0], 0)
        code, _, err = self.cli("next", "v1", "--enter", "tts", providers=p)
        self.assertEqual(code, 1)
        self.assertIn("persona wav missing", err)

    def test_sync_and_unknown(self):
        self.assertEqual(self.cli("sync")[0], 2)
        self.assertEqual(self.cli("approve", "v1", "1")[0], 2)

    def test_r16_video_location(self):
        os.makedirs(os.path.join(self.repo, "studio", "local", "videos", "v1"))
        self.assertEqual(self.cli("next", "v1")[0], 2)
        self.assertEqual(self.cli("next", "nope")[0], 2)

    def test_r19_classification(self):
        for n in ("next", "record-brief", "loop", "status", "sync", "shown"):
            self.assertFalse(commands.needs_evidence(n))
        for n in ("approve", "credit", "rollback", "made-up"):
            self.assertTrue(commands.needs_evidence(n))

    def test_r20_schema(self):
        st = self.state()
        st["schema"] = 2
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        self.assertEqual(self.cli("next", "v1")[0], 2)
        st["schema"] = 1
        del st["brief"]
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        self.assertEqual(self.cli("next", "v1")[0], 1)

    def test_r20_unknown_keys_survive_a_write(self):
        st = self.state()
        st["future"] = {"x": 1}
        with open(self.paths["state"], "w") as f:
            json.dump(st, f)
        self.cli("loop", "v1", "copy")
        self.assertEqual(self.state()["future"], {"x": 1})

    def test_status_unknown_video(self):
        self.assertEqual(self.cli("status", "nope")[0], 2)

    def test_status(self):
        code, out, _ = self.cli("status", "--json")
        self.assertEqual(code, 0)
        v = json.loads(out)["videos"][0]
        self.assertEqual((v["video"], v["incomplete_events"]), ("v1", []))
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-1"
        self.assertIn("guard has not run", self.cli("status")[1])
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        with open(os.path.join(self.repo, ".claude", "studio", "local", "guard-ran.json"), "w") as f:
            json.dump({"sess-1": "2026-10-20T00:00:00Z"}, f)
        self.assertNotIn("guard has not run", self.cli("status")[1])


class Durability(StoreCase):
    def driver(self, *args, inspect=None):
        cmd = [sys.executable, "-B", DRIVER] + list(args)
        return subprocess.run(cmd, cwd=self.repo, capture_output=True, text=True, timeout=60)

    def test_r13_kill_between_log_and_state(self):
        for at in ("after_log", "before_replace"):
            before = self.state()
            out = self.driver("--kill", at, "--", "loop", "v1", "verify")
            self.assertEqual(out.returncode, -signal.SIGKILL)
            after = self.state()
            self.assertEqual(after, before)
            pending = store.incomplete(self.vdir)
            self.assertEqual(len(pending), 1)
            code, out_, _ = self.cli("status", "--json")
            self.assertEqual(json.loads(out_)["videos"][0]["incomplete_events"], pending)
            # the next write voids it first and continues
            self.assertEqual(self.cli("loop", "v1", "copy")[0], 0)
            self.assertEqual(store.incomplete(self.vdir), [])
            log = store.read_log(self.vdir)
            self.assertIn({"event": "void", "of": pending[0]}, [{k: e[k] for k in ("event", "of") if k in e}
                                                                for e in log if e.get("event") == "void"])
            seqs = [e["seq"] for e in log]
            self.assertEqual(seqs, sorted(set(seqs)))
            self.assertEqual(self.state()["last_seq"], seqs[-1])

    def test_double_crash_both_voided(self):
        self.driver("--kill", "after_log", "--", "loop", "v1", "verify")
        self.driver("--kill", "before_replace", "--", "loop", "v1", "verify")
        last = self.state()["last_seq"]
        crashed = {e["seq"] for e in store.read_log(self.vdir) if e.get("event") == "loop" and e["seq"] > last}
        self.assertEqual(len(crashed), 2)
        # the second attempt already voided the first: only the second is still incomplete
        self.assertEqual(store.incomplete(self.vdir), [max(crashed)])
        self.assertEqual(self.cli("loop", "v1", "copy")[0], 0)
        voids = [e["of"] for e in store.read_log(self.vdir) if e.get("event") == "void"]
        self.assertEqual(sorted(voids), sorted(crashed))  # each voided exactly once
        self.assertEqual(store.incomplete(self.vdir), [])

    def test_torn_log_line(self):
        with open(self.paths["log"], "a") as f:
            f.write('{"seq": 99, "ev')  # cut by a crash
        self.assertEqual(self.cli("loop", "v1", "copy")[0], 0)
        code, out, _ = self.cli("status", "--json")
        self.assertEqual(json.loads(out)["videos"][0]["unreadable_log_lines"], 1)
        log = store.read_log(self.vdir)
        self.assertEqual(log[-1]["event"], "loop")

    def test_create_continues_the_log(self):
        v = os.path.join(self.repo, "studio", "videos", "v2")
        os.makedirs(os.path.join(v, "work"))
        with open(os.path.join(v, "work", "approvals.jsonl"), "w") as f:
            f.write('{"seq": 7, "event": "old"}\n')
        st = F.state()
        st["video"] = "v2"  # the folder's own id (a state in another video's folder is refused, M1a review U3)
        store.create(v, st)
        self.assertEqual(store.read_state(v)["last_seq"], 8)

    def test_r13_old_tmp_files_are_cleaned(self):
        old = os.path.join(self.paths["work"], "state.json.tmp.deadbeef")
        with open(old, "w") as f:
            f.write("x")
        t = time.time() - 120
        os.utime(old, (t, t))
        young = os.path.join(self.paths["work"], "state.json.tmp.cafebabe")
        with open(young, "w") as f:
            f.write("x")
        self.cli("loop", "v1", "copy")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(young))

    def test_r14_lock_busy_then_free(self):
        holder = subprocess.Popen([sys.executable, "-B", "-c",
                                   "import fcntl,os,sys,time; fd=os.open(sys.argv[1], os.O_RDWR|os.O_CREAT); "
                                   "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(30)",
                                   self.paths["lock"]], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            t = time.time()
            self.assertEqual(self.cli("loop", "v1", "copy")[0], 5)
            self.assertGreaterEqual(time.time() - t, 1.5)
            holder.kill()
            holder.wait()
            self.assertEqual(self.cli("loop", "v1", "copy")[0], 0)
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()

    def test_r14_flock_unsupported_is_exit_2(self):
        def nolock(fd, op):
            raise OSError(errno.ENOLCK, "No locks available")

        code, _, err = self.cli("loop", "v1", "copy", flock=nolock)
        self.assertEqual(code, 2)
        self.assertIn("does not support flock", err)

    def test_r14_lock_not_inherited_by_children(self):
        with store.Lock(self.paths["lock"]):
            child = subprocess.Popen(["sleep", "10"], close_fds=False)
        try:
            # the child would keep the flock if it had inherited the descriptor
            code = ("import sys; sys.path.insert(0, %r); from stdo.state import store\n"
                    "with store.Lock(%r, wait=0.5):\n    print('got it')\n") % (helpers.SCRIPTS, self.paths["lock"])
            out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=30)
            self.assertIn("got it", out.stdout, out.stderr)
        finally:
            child.kill()
            child.wait()

    def test_r15_writes_only_from_the_cli(self):
        code = ("import sys; sys.path.insert(0, %r); from stdo.state import store\n"
                "try:\n    store.write(%r, {'event': 'x'}, lambda s: None)\n"
                "except RuntimeError as e:\n    print('refused', e)\n") % (helpers.SCRIPTS, self.vdir)
        out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=30)
        self.assertIn("refused", out.stdout)

    def test_state_py_entry_runs(self):
        out = subprocess.run([sys.executable, "-B", STATE_PY, "status", "--json"], cwd=self.repo,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)


class Hashes(StudioTestCase):
    def test_r17_actor_ids_are_not_in_brief_core(self):
        a = hashes.brief_core(["C-1"], [{"name": "host", "kind": "narrator", "actor": "sora"}])
        b = hashes.brief_core(["C-1"], [{"name": "host", "kind": "narrator", "actor": "kai", "recommend": ["x"]}])
        self.assertEqual(a, b)

    def test_inspect_not_built_message(self):
        from stdo.state.collect import CollectError, run_inspect
        with self.assertRaises(CollectError) as e:
            run_inspect(self.tmp, os.path.join(self.tmp, "s.md"))
        self.assertIn("not built", str(e.exception))

    def test_r17_brief_core(self):
        a = hashes.brief_core(["C-2", "C-1"], [{"name": "b"}, {"name": "a"}])
        b = hashes.brief_core(["C-1", "C-2"], [{"name": "a"}, {"name": "b"}])
        self.assertEqual(a, b)
        self.assertNotEqual(a, hashes.brief_core(["C-1"], [{"name": "a"}, {"name": "b"}]))

    def test_r18_source_hash(self):
        repo = self.tmp
        os.makedirs(os.path.join(repo, "docs"))
        for n, b in (("docs/a.md", b"# A"), ("docs/x.png", b"\x89PNG1"), ("docs/y.png", b"\x89PNG2")):
            with open(os.path.join(repo, n), "wb") as f:
                f.write(b)
        h1 = hashes.source_hash_repo_md(repo, "docs/a.md", ["docs/x.png", "docs/y.png"])
        self.assertEqual(h1, hashes.source_hash_repo_md(repo, "docs/a.md", ["docs/y.png", "docs/x.png"]))
        with open(os.path.join(repo, "docs/y.png"), "wb") as f:
            f.write(b"\x89PNG3")
        self.assertNotEqual(h1, hashes.source_hash_repo_md(repo, "docs/a.md", ["docs/x.png", "docs/y.png"]))
        self.assertNotEqual(h1, hashes.source_hash_repo_md(repo, "docs/a.md", ["docs/x.png", "docs/gone.png"]))

    def test_r21_render_sha_proxy(self):
        d = self.tmp
        for n in ("youtube.ko.mp4", "youtube.ko.proxy.mp4"):
            with open(os.path.join(d, n), "wb") as f:
                f.write(n.encode())
        plain = hashes.render_sha(d, "youtube", "ko")
        proxy = hashes.render_sha(d, "youtube", "ko", proxy=True)
        self.assertNotEqual(plain, proxy)
        self.assertIsNone(hashes.render_sha(d, "shorts", "ko"))


class Create(StudioTestCase):
    def test_create_refuses_to_overwrite(self):
        store.enable_writes()
        v = os.path.join(self.tmp, "v")
        os.makedirs(v)
        store.create(v, F.state())
        with self.assertRaises(schema.SchemaError):
            store.create(v, F.state())
