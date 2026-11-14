"""`--ship` all the way (design/herald/11-ship-consent.md, 0.20.0): the lock's ship mark and pass,
the agent review standing in for a human's look (`image confirm|reject --agent`, `image review` of
external images, `shot review`, `shot confirm --agent`, the review problem ledger), the strong
consent and `images-unconfirmed`, `lock ship-pass`, the guard's `--agent` way and its merge/deploy
`allow`, the settings template and `published.json`. Every run without `--ship` stays 0.19.0
(the other suites run unchanged). No network: the fake gh, a fake HTTPS server and a fake tool."""

import datetime
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from helpers import HERE, SCRIPTS, RepoCase, sh
from test_auto_capture import AutoCase
from test_core import Flow
from test_images import IMG, TID, W, ImageCase
from test_scenes import SceneCase

from hrdlib import images, lock, shots, store

E1 = "%s/e1-lobby.jpg" % IMG


def guard_decision(root, tool, tool_input, env=None):
    e = dict(os.environ)
    e.update(env or {})
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": root})
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                       capture_output=True, text=True, env=e, cwd=root, timeout=60)
    if not p.stdout.strip():
        return "none"  # the guard decided nothing (Claude Code's own rules apply)
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]


def ship_lock(root, topic=TID, attended=False):
    return lock.acquire(root, "write", ship=True, topic=topic, attended=attended)


# --- the lock (§2.1, §9 R2-4, §10 R3-1) ------------------------------------------------------------

class LockMarkTests(RepoCase):
    def test_ship_mark_is_written_only_by_the_creating_acquire(self):
        with self.assertRaises(Exception):
            lock.acquire(self.root, "write", ship=True)  # --ship needs --topic
        tok = lock.acquire(self.root, "write", ship=True, topic="t0001", attended=True)
        cur = lock.status(self.root)
        self.assertEqual((cur["ship"], cur["topic"], cur["attended"]), (True, "t0001", True))
        self.assertTrue(lock.ship_active(self.root, "t0001"))
        self.assertFalse(lock.ship_active(self.root, "t0002"))  # bound to its topic
        self.assertFalse(lock.agent_ok(self.root, "t0001"))  # attended: a human looks
        # a nested acquire (same token) never changes the mark
        self.assertEqual(lock.acquire(self.root, "ship", token=tok), tok)
        self.assertEqual(lock.acquire(self.root, "write", token=tok, ship=True, topic="t0009"), tok)
        self.assertEqual(lock.status(self.root)["topic"], "t0001")
        self.assertEqual(lock.acquire(self.root, "write", token=tok, ship=True, topic="t0001", attended=False), tok)
        self.assertTrue(lock.status(self.root)["attended"])  # nested: attended unchanged too
        lock.release(self.root, tok)
        self.assertFalse(lock.ship_active(self.root, "t0001"))
        # an outer command without --ship: the nested --ship adds nothing
        tok = lock.acquire(self.root, "refresh")
        lock.acquire(self.root, "write", token=tok, ship=True, topic="t0001", attended=True)
        self.assertNotIn("ship", lock.status(self.root))
        self.assertNotIn("attended", lock.status(self.root))
        lock.release(self.root, tok)

    def test_unattended_refuses_and_a_given_token_decides_by_its_own_flags(self):
        with mock.patch.dict(os.environ, {"HRD_UNATTENDED": "1"}):
            with self.assertRaises(Exception):
                lock.acquire(self.root, "write", ship=True, topic="t0001")
        tok = lock.acquire(self.root, "write", token="abc123", ship=True, topic="t0001")
        self.assertEqual(tok, "abc123")
        self.assertTrue(lock.ship_active(self.root, "t0001"))
        lock.force_unlock(self.root)
        self.assertFalse(lock.ship_active(self.root, "t0001"))
        out, _ = self.hrd("lock", "acquire", "--cmd", "write", "--ship", "--topic", "t0003")
        self.assertEqual((out["ship"], out["topic"]), (True, "t0003"))
        out2, _ = self.hrd("lock", "acquire", "--cmd", "ship", "--token", out["token"])
        self.assertTrue(out2["ship"])  # nested: the outer mark
        _, p = self.hrd("lock", "acquire", "--cmd", "write", "--ship", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.hrd("lock", "unlock")
        _, p = self.hrd("lock", "acquire", "--cmd", "write", "--ship", "--topic", "t0003",
                        env={"HRD_UNATTENDED": "1"}, check=False)
        self.assertIn("unattended", p.stderr)

    def test_pass_belongs_to_the_lock_that_wrote_it(self):
        tok = lock.acquire(self.root, "write", ship=True, topic="t0001")
        lock.write_pass(self.root, tok, "t0001", 5, "a" * 40)
        self.assertEqual(lock.valid_pass(self.root)["pr"], 5)
        self.assertIs(lock.valid_pass(self.root)["merged"], False)  # a merge first, a deploy after
        lock.mark_merged(self.root, lock.valid_pass(self.root), "b" * 40)
        self.assertIs(lock.valid_pass(self.root)["merged"], True)
        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2, minutes=1)
        self.assertIsNone(lock.valid_pass(self.root, now=later))  # two hours at most
        lock.write_pass(self.root, "other", "t0001", 5, "a" * 40)
        self.assertIsNone(lock.valid_pass(self.root))  # another lock's pass
        lock.write_pass(self.root, tok, "t0002", 5, "a" * 40)
        self.assertIsNone(lock.valid_pass(self.root))  # another topic
        lock.write_pass(self.root, tok, "t0001", 5, "a" * 40)
        with open(lock.lock_path(self.root), "w") as f:
            f.write("{broken")
        self.assertIsNone(lock.valid_pass(self.root))  # unreadable: no pass, no error
        self.assertFalse(lock.ship_active(self.root, "t0001"))
        os.remove(lock.lock_path(self.root))
        tok = lock.acquire(self.root, "write", ship=True, topic="t0001")
        lock.write_pass(self.root, tok, "t0001", 5, "a" * 40)
        lock.release(self.root, tok)
        self.assertFalse(os.path.exists(lock.pass_path(self.root)))  # release ends the pass
        tok = lock.acquire(self.root, "write", ship=True, topic="t0001")
        lock.write_pass(self.root, tok, "t0001", 5, "a" * 40)
        lock.force_unlock(self.root)
        self.assertFalse(os.path.exists(lock.pass_path(self.root)))
        tok = lock.acquire(self.root, "write")  # no mark: no pass
        lock.write_pass(self.root, tok, None, 5, "a" * 40)
        self.assertIsNone(lock.valid_pass(self.root))
        lock.release(self.root, tok)


# --- images: the agent review and --agent (§2.2, §2.3, P25) ----------------------------------------

class AgentImageTests(ImageCase):
    def tearDown(self):
        lock.force_unlock(self.root)
        super().tearDown()

    def review_ok(self, iid="e1", note="the lobby the text names; no faces or marks"):
        return images.review(self.root, self.cfg, TID, iid, ok=True, note=note)

    def test_review_opens_for_fetched_external_only(self):
        with self.assertRaises(Exception):  # not fetched yet
            self.review_ok()
        self.fetched()
        out = images.status(self.root, self.cfg, TID)
        self.assertEqual(out["pending"]["review"], ["e1"])  # external images listed too (§9 m5)
        self.review_ok()
        st = self.state()
        self.assertEqual(st["images"]["items"]["e1"]["reviewed"], shots.blob(self.root, E1))
        self.assertEqual(images.status(self.root, self.cfg, TID)["pending"]["review"], [])
        self.plan()  # a plan keeps the review of the same picture
        self.assertEqual(self.state()["images"]["items"]["e1"]["reviewed"], shots.blob(self.root, E1))
        self.assertEqual(images.status(self.root, self.cfg, TID)["pending"]["review_external"], [])
        out = images.review(self.root, self.cfg, TID, "e1", redo=True, note="a watermark in the corner")
        self.assertEqual(out["redo"], ["e1"])
        self.assertNotIn("review_rejects", self.state())  # an external redo turns no key down
        self.assertNotIn("reviewed", self.state()["images"]["items"]["e1"])
        st = images.status(self.root, self.cfg, TID)["pending"]
        self.assertEqual((st["review_external"], st["review_scene"]), (["e1"], []))
        # review 24 MINOR-1: the redone bytes never pass an agent again — a later reviewer either
        self.assertEqual(self.state()["review_redos"][0]["blob"], shots.blob(self.root, E1))
        with self.assertRaises(Exception) as c:
            self.review_ok()
        self.assertIn("sent these very bytes back", str(c.exception))
        self.plan()  # survives a plan (top-level state)
        st = self.state()
        st["images"]["items"]["e1"]["reviewed"] = shots.blob(self.root, E1)  # even a forged review mark
        store.save_state(self.root, TID, st)
        ship_lock(self.root)
        with self.assertRaises(Exception):
            images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        self.assertEqual(images.confirm(self.root, self.cfg, TID, "e1")["by"], "human")  # a human may

    def test_redone_bytes_never_pass_under_another_id(self):
        """R2-MINOR-3: the review's redo follows the bytes, not the id."""
        self.fetched()
        images.review(self.root, self.cfg, TID, "e1", redo=True, note="a watermark")
        self.manifest([self.d1(), self.e1(id="e2", file="%s/e2-lobby.jpg" % IMG,
                                          ref="/blog-images/new-post/e2-lobby.jpg")])
        self.body(e1="![The office lobby](/blog-images/new-post/e2-lobby.jpg)")
        self.assertEqual(self.plan()["errors"], [])
        self.assertEqual([x["id"] for x in self.fetch()["fetched"]], ["e2"])
        with self.assertRaises(Exception) as c:
            images.review(self.root, self.cfg, TID, "e2", ok=True, note="fine")
        self.assertIn("sent these very bytes back", str(c.exception))

    def test_agent_confirm_needs_the_mark_the_review_and_no_unattended(self):
        self.fetched()
        self.review_ok()
        with self.assertRaises(Exception) as c:  # no lock
            images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        self.assertIn("--ship", str(c.exception))
        tok = lock.acquire(self.root, "write")  # a lock without the mark
        with self.assertRaises(Exception):
            images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        lock.release(self.root, tok)
        tok = ship_lock(self.root, topic="t0099")  # the mark of another topic
        with self.assertRaises(Exception):
            images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        lock.release(self.root, tok)
        tok = ship_lock(self.root, attended=True)  # attended: a human looks
        with self.assertRaises(Exception):
            images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        lock.release(self.root, tok)
        ship_lock(self.root)
        with mock.patch.dict(os.environ, {"HRD_UNATTENDED": "1"}):
            with self.assertRaises(Exception):
                images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        st = self.state()  # a review of other bytes
        st["images"]["items"]["e1"]["reviewed"] = "0" * 40
        store.save_state(self.root, TID, st)
        with self.assertRaises(Exception) as c:
            images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        self.assertIn("review", str(c.exception))
        self.review_ok()
        out = images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        self.assertEqual((out["confirmed"], out["by"]), (["e1"], "agent"))
        recs, _ = shots.ledger_read(os.path.join(self.root, shots.CONFIRMATIONS))
        self.assertEqual((recs[-1]["by"], recs[-1]["id"]), ("agent", "e1"))
        self.assertIn("lobby", recs[-1]["note"])
        self.assertEqual(self.state()["images"]["items"]["e1"]["confirmed_by"], "agent")
        self.assertEqual(self.plan()["errors"], [])
        self.assertEqual(self.state()["images"]["items"]["e1"]["confirmed_by"], "agent")  # plan keeps who
        self.assertEqual(images.draft_problems(self.root, self.cfg, TID, self.state()), [])

    def test_agent_line_vouches_for_its_own_item_only(self):
        self.fetched()
        self.review_ok()
        ship_lock(self.root)
        images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        led = shots.Ledger(self.root)
        h = shots.file_hashes(self.root, E1)
        key = images.item_key(self.e1())
        self.assertTrue(led.confirmed(h))  # rule U counts it
        self.assertTrue(led.confirmed_for(h, TID, "e1", key))
        self.assertFalse(led.confirmed_for(h, "t0002", "e1", key))  # the same content elsewhere
        self.assertFalse(led.confirmed_for(h, TID, "e2", key))
        self.assertFalse(led.confirmed_for(h, TID, "e1", "another-key"))
        self.assertFalse(led.human_confirmed(h))
        self.assertEqual(led.confirmed_by(h, TID, "e1", key), "agent")
        # a human's line stays content-based, as in 0.19.0
        shots.ledger_append(os.path.join(self.root, shots.CONFIRMATIONS),
                            {"topic": "t0050", "id": "e9", "key": "k", "blob": h[0], "sha256": h[1], "at": "x"})
        led = shots.Ledger(self.root)
        self.assertTrue(led.confirmed_for(h, "t0002", "e1", key))
        self.assertEqual(led.confirmed_by(h, TID, "e1", key), "human")
        self.assertEqual(led.confirm_line(h, TID, "e1", key).get("by"), "agent")  # own line first

    def test_rule_u_and_import_see_the_agent_line_differently(self):
        self.fetched()
        self.review_ok()
        ship_lock(self.root)
        images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        h = shots.file_hashes(self.root, E1)
        led = shots.Ledger(self.root)
        self.assertFalse(led.unconfirmed(h))  # may go to the remote
        self.assertTrue(led.unconfirmed_by_human(h))  # never taken as a human's own file (§9 m4)

    def test_agent_reject_external_limits_and_marks(self):
        self.fetched()
        self.plan()
        with self.assertRaises(Exception):  # no mark
            images.reject(self.root, self.cfg, TID, "e1", reason="watermark", agent=True)
        ship_lock(self.root)
        with self.assertRaises(Exception):
            images.reject(self.root, self.cfg, TID, "e1", refetch=True, reason="x", agent=True)
        out = images.reject(self.root, self.cfg, TID, "e1", reason="watermark", agent=True)
        self.assertEqual(out["rejected"], ["e1"])
        st = self.state()
        self.assertEqual((st["last_loopback"], st["image_rejects"][-1]["by"]), ("agent", "agent"))
        images.reject(self.root, self.cfg, TID, "e1", reason="a logo", agent=True)
        with self.assertRaises(Exception) as c:  # the third agent reject of a place must drop it
            images.reject(self.root, self.cfg, TID, "e1", reason="subtitle", agent=True)
        self.assertIn("--drop", str(c.exception))
        images.reject(self.root, self.cfg, TID, "e1", reason="none fits", drop=True, agent=True)
        self.assertEqual(images.agent_rejects(self.state(), "e1"), 3)
        out = images.status(self.root, self.cfg, TID)
        self.assertEqual([x["id"] for x in out["agent"]["rejected"]], ["e1", "e1", "e1"])
        self.assertTrue(any("left out after the agent review (no human look): none fits" in r for r in out["pr_rows"]))

    def test_agent_reject_scene_only_drops_and_decision_log_kind_agent_is_no_reason(self):
        self.fetched()
        self.manifest([self.d1(), self.e1(), {"id": "g1", "kind": "scene", "file": "%s/g1-x.png" % IMG}])
        ship_lock(self.root)
        with self.assertRaises(Exception) as c:
            images.reject(self.root, self.cfg, TID, "g1", reason="hands", agent=True)
        self.assertIn("--drop", str(c.exception))
        crit = {"final_round": {"verdict": "PASS"}, "decision_log": [{"kind": "agent", "id": "image:e1", "note": "x"}]}
        self.assertEqual(store.auto_exclusion(crit, {}), [])

    def test_agent_reject_gate_failure_stays_a_signal(self):
        st = store.load_state(self.root, TID)
        st["last_loopback"] = "agent"
        store.record_gate_failure(self.root, st, TID, "draft", {"errors": ["x"]})
        sig = [r for r in store.read_jsonl(store.paths(self.root)["signals"]) if r.get("kind") == "gate-failure"]
        self.assertEqual(len(sig), 1)

    def test_pr_rows_status_and_published_record(self):
        self.fetched()
        self.review_ok(note="the office lobby; credit visible")
        ship_lock(self.root)
        images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        out = images.status(self.root, self.cfg, TID)
        rows = "\n".join(out["pr_rows"])
        self.assertIn("agent-reviewed (no human look): the office lobby; credit visible", rows)
        self.assertNotIn(", confirmed 20", rows)
        self.assertEqual(out["agent"]["confirmed"], [{"id": "e1", "kind": "external",
                                                       "note": "the office lobby; credit visible"}])
        art = store.record_published(self.root, self.cfg, TID, "new-post")
        self.assertEqual(art["agent_confirmed"], ["e1"])
        self.assertTrue(art["human_reviewed"])  # 0.19.0's field is left as it is

    def test_human_confirm_is_unchanged(self):
        self.ready()  # the 0.19.0 path: a human's confirm, no review needed
        self.assertNotIn("confirmed_by", self.state()["images"]["items"]["e1"])
        recs, _ = shots.ledger_read(os.path.join(self.root, shots.CONFIRMATIONS))
        self.assertNotIn("by", recs[-1])
        rows = "\n".join(images.status(self.root, self.cfg, TID)["pr_rows"])
        self.assertIn(", confirmed 20", rows)

    def test_cli_agent_flags(self):
        self.fetched()
        out, _ = self.hrd("image", "review", "--topic", TID, "--id", "e1", "--ok", "--note", "fine")
        self.assertEqual(out["reviewed"], ["e1"])
        _, p = self.hrd("image", "confirm", "--topic", TID, "--id", "e1", "--agent", check=False)
        self.assertIn("--ship", p.stderr)
        _, p = self.hrd("image", "status", "--topic", TID, "--agent", check=False)
        self.assertIn("--agent applies only", p.stderr)
        self.hrd("lock", "acquire", "--cmd", "write", "--ship", "--topic", TID)
        out, _ = self.hrd("image", "confirm", "--topic", TID, "--id", "e1", "--ag")  # argparse prefix
        self.assertEqual(out["by"], "agent")


# --- screenshots: shot review, --problem, shot confirm --agent (§2.2, §2.3 3, §9 R2-6, §10–§11 m1) --

class AgentShotTests(AutoCase):
    def tearDown(self):
        lock.force_unlock(self.root)
        super().tearDown()

    def review(self, **kw):
        kw.setdefault("note", "a public settings page; no personal data")
        return shots.review(self.root, self.cfg, TID, "s1", **kw)

    def test_review_refuses_what_is_no_capture_waiting(self):
        self.plan()  # s1 pending: nothing captured yet
        with self.assertRaises(Exception) as c:
            self.review(ok=True)
        self.assertIn("not an automatic capture waiting", str(c.exception))
        self.cap()
        os.remove(os.path.join(self.root, shots.CAPTURES))  # no capture line on this machine
        with self.assertRaises(Exception) as c:
            self.review(ok=True)
        self.assertIn("is not the file", str(c.exception))
        with self.assertRaises(Exception):
            self.review(problem="privacy")

    def test_review_ok_then_confirm_agent(self):
        self.captured()
        self.assertEqual(shots.status(self.root, self.cfg, TID)["review"], ["s1"])
        with self.assertRaises(Exception):
            shots.review(self.root, self.cfg, TID, "s1", ok=True, problem="privacy", note="x")
        self.review(ok=True)
        with self.assertRaises(Exception):  # no mark
            shots.confirm(self.root, self.cfg, TID, "s1", agent=True)
        self.plan()  # the same capture keeps its review through a plan
        self.assertEqual(self.rec()["reviewed"], self.rec()["sha"])
        ship_lock(self.root)
        out = shots.confirm(self.root, self.cfg, TID, "s1", agent=True)
        self.assertEqual(out["by"], "agent")
        recs, _ = self.ledger(shots.CONFIRMATIONS)
        self.assertEqual(recs[-1]["by"], "agent")
        r = self.rec()
        self.assertEqual((r["status"], r["confirmed_by"], r["confirmed_sha"]), ("ready", "agent", r["sha"]))
        st = shots.status(self.root, self.cfg, TID)
        self.assertEqual(st["agent_confirmed"][0]["id"], "s1")
        self.assertIn("agent-reviewed (no human look): a public settings page", st["shots"][0]["shot_col"])
        self.plan()
        self.assertEqual(self.rec()["status"], "ready")
        self.assertEqual(self.rec()["confirmed_by"], "agent")
        self.assertEqual(store.agent_confirmed(self.root, TID), ["s1"])

    def test_problem_holds_and_only_a_human_passes_it(self):
        self.captured()
        out = self.review(problem="privacy", note="an e-mail address in the header")
        self.assertEqual(out["problem"], {"id": "s1", "kind": "privacy"})
        recs, bad = shots.read_problems(self.root)
        self.assertEqual((len(recs), bad), (1, []))
        self.assertEqual(recs[0]["blob"], self.rec()["sha"])
        note = shots.hold_note(self.state())
        self.assertIn("s1(review:privacy)", note)
        shots.check_note(note)  # NOTE_RE takes it
        with self.assertRaises(Exception):
            self.review(ok=True)  # the same bytes: never passed by an agent
        ship_lock(self.root)
        st = self.state()  # even a forged review mark does not help
        st["screenshots"]["shots"]["s1"]["reviewed"] = st["screenshots"]["shots"]["s1"]["sha"]
        store.save_state(self.root, TID, st)
        with self.assertRaises(Exception):
            shots.confirm(self.root, self.cfg, TID, "s1", agent=True)
        self.plan()  # resume: the state is rebuilt, the ledger still says so
        with self.assertRaises(Exception):
            shots.confirm(self.root, self.cfg, TID, "s1", agent=True)
        self.assertEqual(shots.confirm(self.root, self.cfg, TID, "s1")["by"], "human")  # a human's look

    def test_damaged_problem_ledger_fails_closed_for_the_agent_only(self):
        self.captured()
        p = os.path.join(self.root, shots.PROBLEMS)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write('{"topic": "t0001"}\n')
        with self.assertRaises(Exception) as c:
            self.review(ok=True)
        self.assertIn("damaged", str(c.exception))
        st = self.state()
        st["screenshots"]["shots"]["s1"]["reviewed"] = st["screenshots"]["shots"]["s1"]["sha"]
        store.save_state(self.root, TID, st)
        ship_lock(self.root)
        with self.assertRaises(Exception):
            shots.confirm(self.root, self.cfg, TID, "s1", agent=True)
        self.assertEqual(shots.confirm(self.root, self.cfg, TID, "s1")["confirmed"], ["s1"])
        self.assertEqual(shots.Ledger(self.root).damaged, [])  # not a Ledger file

    def test_state_after_a_truncated_problem_ledger(self):
        """A `--problem` cut mid-write (its state never written): the agent is refused until a later
        `--problem` cuts the broken tail; a human's confirm is never affected (§10 m1)."""
        self.captured()
        p = os.path.join(self.root, shots.PROBLEMS)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b'{"topic": "t0001", "id": "s1", "kind": "priv')
        self.assertEqual(shots.read_problems(self.root)[1], [1])
        self.assertNotIn("review_problem", self.rec())  # the cut write never reached the state
        with self.assertRaises(Exception) as c:
            self.review(ok=True)
        self.assertIn("damaged", str(c.exception))
        out = self.review(problem="mismatch", note="the wrong page")  # the next problem cuts the tail
        self.assertEqual(out["problem"]["kind"], "mismatch")
        recs, bad = shots.read_problems(self.root)
        self.assertEqual(([r["kind"] for r in recs], bad), (["mismatch"], []))
        self.assertEqual(self.rec()["review_problem"], "mismatch")
        self.assertIn("s1(review:mismatch)", shots.hold_note(self.state()))
        ship_lock(self.root)
        with self.assertRaises(Exception):
            shots.confirm(self.root, self.cfg, TID, "s1", agent=True)
        self.assertEqual(shots.confirm(self.root, self.cfg, TID, "s1")["by"], "human")

    def test_problem_ledger_reader_and_appender(self):
        p = os.path.join(self.root, shots.PROBLEMS)
        rec = {"topic": "t1", "id": "s1", "key": "k", "blob": "b", "sha256": "s", "kind": "privacy", "note": "n",
               "at": "now"}
        shots.append_problem(self.root, rec)
        with open(p, "ab") as f:
            f.write(b'{"topic": "t1", "id": "s1", "bl')  # a cut write
        self.assertEqual(shots.read_problems(self.root)[1], [2])  # damage until a human or the next append
        shots.append_problem(self.root, dict(rec, id="s2"))  # cuts the broken tail
        recs, bad = shots.read_problems(self.root)
        self.assertEqual(([r["id"] for r in recs], bad), (["s1", "s2"], []))
        with open(p, "ab") as f:
            f.write(json.dumps(dict(rec, id="s3")).encode())  # a whole record without its newline
        shots.append_problem(self.root, dict(rec, id="s4"))
        self.assertEqual([r["id"] for r in shots.read_problems(self.root)[0]], ["s1", "s2", "s3", "s4"])
        with open(p, "ab") as f:
            f.write(json.dumps(dict(rec, kind="other")).encode() + b"\n")
        self.assertEqual(shots.read_problems(self.root)[1], [5])

    def test_cli_review_and_confirm(self):
        self.captured()
        out, _ = self.hrd("shot", "review", "--topic", TID, "--id", "s1", "--ok", "--note", "ok")
        self.assertEqual(out["reviewed"], ["s1"])
        _, p = self.hrd("shot", "demote", "--topic", TID, "--id", "s1", "--own", "--agent", check=False)
        self.assertIn("--agent applies only", p.stderr)
        _, p = self.hrd("shot", "confirm", "--topic", TID, "--id", "s1", "--agent", check=False)
        self.assertIn("--ship", p.stderr)
        self.hrd("lock", "acquire", "--cmd", "write", "--ship", "--topic", TID)
        out, _ = self.hrd("shot", "confirm", "--topic", TID, "--id", "s1", "--agent")
        self.assertEqual(out["by"], "agent")


class AgentSceneTests(SceneCase):
    """Review 24 MAJOR-2: a scene a review sent back never passes an agent, nor draft, until its key
    changes; a human may still confirm it (0.18.0)."""

    def tearDown(self):
        lock.force_unlock(self.root)
        super().tearDown()

    def test_redone_key_is_refused_to_the_agent_and_to_draft(self):
        self.generated()
        images.review(self.root, self.cfg, TID, "g1", ok=True, note="fits the paragraph")
        images.review(self.root, self.cfg, TID, "g2", redo=True, note="malformed hands")
        self.assertEqual(images.status(self.root, self.cfg, TID)["pending"]["review_scene"], ["g2"])
        with self.assertRaises(Exception) as c:
            images.review(self.root, self.cfg, TID, "g2", ok=True, note="looks fine now")
        self.assertIn("turned this picture's key down", str(c.exception))
        ship_lock(self.root)
        st = self.state()  # even with a forged review mark
        st["images"]["items"]["g2"]["reviewed"] = shots.blob(self.root, self.g2()["file"])
        store.save_state(self.root, TID, st)
        with self.assertRaises(Exception):
            images.confirm(self.root, self.cfg, TID, "g2", agent=True)
        self.assertEqual(images.confirm(self.root, self.cfg, TID, "g1", agent=True)["by"], "agent")
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("g2: this picture's key was turned down" in x for x in probs), probs)
        self.assertFalse(any(x.startswith("g1:") for x in probs), probs)
        h = shots.file_hashes(self.root, self.g2()["file"])  # an agent's line (forged) never lets it pass
        shots.ledger_append(os.path.join(self.root, shots.CONFIRMATIONS),
                            {"topic": TID, "id": "g2", "key": images.scene_key(self.cfg, self.g2()), "blob": h[0],
                             "sha256": h[1], "at": "x", "by": "agent", "note": "forged"})
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("g2: this picture's key was turned down" in x for x in probs), probs)
        cp = os.path.join(self.root, shots.CONFIRMATIONS)  # take the forged line out again
        with open(cp) as f:
            kept = [x for x in f if '"forged"' not in x]
        with open(cp, "w") as f:
            f.writelines(kept)
        # a human's look at this very picture: draft takes it (R2-MINOR-2), as the refusal text says
        self.assertEqual(images.confirm(self.root, self.cfg, TID, "g2")["by"], "human")
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertFalse(any("turned down" in x for x in probs), probs)


class GuardEntryTests(RepoCase):
    """Review 24 MAJOR-1: an entry whose `hrdlib` cannot be imported still asks for a merge and the
    deploy (unattended: denies everything), with the stdlib alone."""

    def run_entry(self, cmd, env=None, tool="Bash"):
        import shutil
        copy = os.path.join(self.tmp, "scripts")
        if not os.path.isdir(copy):
            shutil.copytree(SCRIPTS, copy, ignore=shutil.ignore_patterns("__pycache__"))
            with open(os.path.join(copy, "hrdlib", "guard.py"), "a") as f:
                f.write("\ndef broken(:\n")  # a SyntaxError, as a half-copied update could leave
        e = dict(os.environ)
        e.update(env or {})
        payload = json.dumps({"tool_name": tool, "tool_input": {"command": cmd, "file_path": "x"}, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(copy, "guard.py")], input=payload, capture_output=True,
                           text=True, env=e, cwd=self.root, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("could not start", p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] if p.stdout.strip() else "none"

    def test_fallback_asks_for_merge_and_deploy(self):
        self.assertEqual(self.run_entry("gh pr merge 1 --squash"), "ask")
        self.assertEqual(self.run_entry("gh api -X PUT repos/o/r/pulls/1/merge"), "ask")
        self.assertEqual(self.run_entry("cd site && npm run deploy"), "ask")  # the configured deploy
        self.assertEqual(self.run_entry("ls"), "none")
        self.assertEqual(self.run_entry("x", tool="Write"), "none")
        un = {"HRD_UNATTENDED": "1"}
        self.assertEqual(self.run_entry("gh pr merge 1", un), "deny")
        self.assertEqual(self.run_entry("ls", un), "deny")  # as main's crash path: never disabled unattended

    def test_the_real_entry_still_decides(self):
        self.assertEqual(guard_decision(self.root, "Bash", {"command": "gh pr merge 1 --squash"}), "ask")
        self.assertEqual(guard_decision(self.root, "Bash", {"command": "ls"}), "none")


# --- strong consent, images-unconfirmed (§2.4, §9 R2-5, §10 R3-2/m3) ----------------------------------

class StrongConsentTests(ImageCase):
    def tearDown(self):
        lock.force_unlock(self.root)
        super().tearDown()

    def test_blocking_exclusions(self):
        reasons = ["external-images", "images", "screenshots", "decision:dismissal"]
        self.assertEqual(store.blocking_exclusions(reasons, consent=True), ["external-images", "screenshots"])  # 0.19.0
        self.assertEqual(store.blocking_exclusions(reasons, consent=True, strong=True), [])
        self.assertEqual(store.blocking_exclusions(reasons, strong=True), reasons)  # no consent, nothing accepted
        for blocking in ("audit-dismissed:blocker", "audit-log:deferred-blocker", "audit-skipped", "critique-changed",
                         "verify-changed", "missing-critique-or-state", "missing-verify", "audit-log:open"):
            self.assertEqual(store.blocking_exclusions(reasons + [blocking], consent=True, strong=True), [blocking])
        out = store.blocking_exclusions(reasons + ["images-unconfirmed"], consent=True, strong=True)
        self.assertEqual(sorted(out), ["external-images", "images-unconfirmed", "screenshots"])

    def test_unvouched_files_at_the_head(self):
        self.ready()
        self.write(W + "/critique.json", json.dumps({"final_round": {"verdict": "PASS"}, "audit_log": [],
                                                      "decision_log": []}))
        self.commit("wip", ".")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, None, "new-post"), [])
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), [])
        self.write("%s/stray.png" % IMG, b"\x89PNG a human's picture", binary=True)
        self.commit("stray", ".")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), ["%s/stray.png" % IMG])
        reasons = store.exclusion_reasons(self.root, self.cfg, TID, "HEAD", vouch=True)
        self.assertIn("images-unconfirmed", reasons)
        self.assertNotIn("images-unconfirmed", store.exclusion_reasons(self.root, self.cfg, TID, "HEAD"))  # 0.19.0
        # a renamed picture is judged at its new path; a deleted one is not judged
        sh(self.root, "git", "mv", "%s/stray.png" % IMG, "%s/stray2.png" % IMG)
        self.commit("rename")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), ["%s/stray2.png" % IMG])
        sh(self.root, "git", "rm", "-q", "%s/stray2.png" % IMG)
        self.commit("delete")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), [])
        # a fetched picture whose bytes a human changed in the PR
        with open(os.path.join(self.root, E1), "ab") as f:
            f.write(b"edit")
        self.commit("edit", ".")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), [E1])

    def test_agent_confirmed_external_is_vouched_for_its_topic(self):
        self.fetched()
        images.review(self.root, self.cfg, TID, "e1", ok=True, note="ok")
        ship_lock(self.root)
        images.confirm(self.root, self.cfg, TID, "e1", agent=True)
        self.commit("wip", ".")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), [])

    def test_og_file_needs_its_record(self):
        self.config(lambda c: c["images"].update({"og": {"path": "{images}/{slug}/og.png"}}))
        self.ready()
        og = "%s/og.png" % IMG
        self.write(og, b"\x89PNG card", binary=True)
        self.commit("og", ".")
        if not images.og_conf(self.cfg):
            self.skipTest("OG config not accepted in this fixture")
        self.assertIn(og, images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"))
        st = self.state()
        st["images"]["og"] = {"status": "made", "sha": shots.blob(self.root, og), "by": "limner"}
        store.save_state(self.root, TID, st)
        self.commit("og record", ".")
        self.assertNotIn(og, images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"))

    def test_og_outside_the_image_dir_needs_its_record(self):
        self.config(lambda c: c["images"].update({"og": {"path": "public/og/{slug}.png"}}))
        og = self.cfg.og_outside("new-post")
        self.assertEqual(og, "public/og/new-post.png")
        self.ready()
        self.write(og, b"\x89PNG outside card", binary=True)
        self.commit("og", ".")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), [og])
        st = self.state()
        st["images"]["og"] = {"status": "made", "sha": shots.blob(self.root, og), "by": "repo"}
        store.save_state(self.root, TID, st)
        self.commit("og record", ".")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), [])
        st["images"]["og"]["sha"] = "0" * 40  # a record of other bytes
        store.save_state(self.root, TID, st)
        self.commit("other record", ".")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", "new-post"), [og])

    def test_auto_exclusion_strong_comes_from_the_lock(self):
        self.ready()
        self.write(W + "/critique.json", json.dumps({"final_round": {"verdict": "PASS"}, "audit_log": [],
                                                      "decision_log": []}))
        self.commit("wip", ".")
        out, _ = self.hrd("auto-exclusion", "--topic", TID, "--consent")
        self.assertFalse(out["strong"])
        self.assertIn("external-images", out["blocking"])
        ship_lock(self.root, topic="t0077")  # another topic's mark
        self.assertFalse(self.hrd("auto-exclusion", "--topic", TID, "--consent")[0]["strong"])
        lock.force_unlock(self.root)
        ship_lock(self.root)
        out, _ = self.hrd("auto-exclusion", "--topic", TID, "--consent")
        self.assertTrue(out["strong"])
        self.assertNotIn("external-images", out["blocking"])
        self.assertNotIn("images-unconfirmed", out["reasons"])
        self.assertFalse(self.hrd("auto-exclusion", "--topic", TID)[0]["strong"])  # no consent, no strong


# --- lock ship-pass (§2.5, §9 R2-4, §10 R3-1/m2) ---------------------------------------------------

class ShipPassTests(Flow):
    def setUp(self):
        super().setUp()
        self.tid, self.slug = self.run_flow()
        os.remove(os.path.join(self.root, "public/blog-images/%s/01.png" % self.slug))  # no image in the PR
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "pr head")
        self.branch = sh(self.root, "git", "branch", "--show-current").strip()
        self.sha = sh(self.root, "git", "rev-parse", self.branch).strip()
        sh(self.root, "git", "switch", "-q", "main")
        self.set_prs([{"number": 12, "headRefName": self.branch, "state": "OPEN", "labels": ["herald"]},
                      {"number": 13, "headRefName": "herald/t0999--other", "state": "OPEN", "labels": ["herald"]},
                      {"number": 14, "headRefName": self.branch, "state": "OPEN", "labels": ["herald"]},
                      {"number": 15, "headRefName": self.branch, "state": "OPEN", "isCrossRepository": True},
                      {"number": 16, "headRefName": self.branch, "state": "OPEN", "baseRefName": "dev"}])

    def tearDown(self):
        lock.force_unlock(self.root)
        super().tearDown()

    def ship_pass(self, pr="12", sha=None, topic=None, check=False, env=None):
        return self.hrd("lock", "ship-pass", "--topic", topic or self.tid, "--pr", pr, "--rev", self.branch,
                        "--sha", sha or self.sha, check=check, env=env)

    def stamp(self, pr="12"):
        return self.hrd("auto-merged", "--topic", self.tid, "--pr", pr, "--rev", self.branch, "--sha", self.sha,
                        "--consent")

    def test_refusals(self):
        _, p = self.ship_pass()
        self.assertIn("no ship mark", p.stderr)  # no lock
        tok = lock.acquire(self.root, "write")
        _, p = self.ship_pass()
        self.assertIn("no ship mark", p.stderr)  # a lock without the mark
        lock.release(self.root, tok)
        ship_lock(self.root, topic=self.tid)
        _, p = self.ship_pass(topic="t0999")
        self.assertIn("no ship mark", p.stderr)  # another topic than the mark's
        _, p = self.ship_pass()
        self.assertIn("auto-merge stamp", p.stderr)  # not stamped yet
        self.stamp()
        _, p = self.ship_pass(sha="0" * 40)
        self.assertIn("not the verified head", p.stderr)
        _, p = self.ship_pass(pr="13")
        self.assertIn("herald branch", p.stderr)
        _, p = self.ship_pass(pr="14")
        self.assertIn("auto-merge stamp", p.stderr)  # the stamp names PR 12
        _, p = self.ship_pass(pr="99")
        self.assertIn("cannot read", p.stderr)  # GitHub gives no answer: no pass
        _, p = self.ship_pass(pr="15")
        self.assertIn("another repository", p.stderr)  # a fork naming its branch like ours (MINOR-3)
        _, p = self.ship_pass(pr="16")
        self.assertIn("targets dev", p.stderr)
        _, p = self.ship_pass(env={"HRD_UNATTENDED": "1"})
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(os.path.exists(lock.pass_path(self.root)))
        out, _ = self.ship_pass(check=True)
        self.assertEqual((out["pass"]["pr"], out["pass"]["sha"]), (12, self.sha))
        self.assertEqual(lock.valid_pass(self.root)["pr"], 12)
        self.hrd("lock", "ship-pass", "--clear")
        self.assertIsNone(lock.valid_pass(self.root))

    def test_blocking_at_the_head_refuses(self):
        sh(self.root, "git", "switch", "-q", self.branch)
        self.article(self.slug)  # a picture nobody vouched for
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "a human's picture")
        self.sha = sh(self.root, "git", "rev-parse", "HEAD").strip()
        sh(self.root, "git", "switch", "-q", "main")
        ship_lock(self.root, topic=self.tid, attended=True)  # attended: no stamp needed, blocking still counts
        _, p = self.ship_pass()
        self.assertIn("images-unconfirmed", p.stderr)

    def test_attended_skips_only_the_stamp(self):
        ship_lock(self.root, topic=self.tid, attended=True)
        out, _ = self.ship_pass(check=True)
        self.assertEqual(out["pass"]["pr"], 12)
        # `--attended --ship`: the guard lets the merge, then (after --merged) the deploy through too
        merge = "gh pr merge 12 --squash --match-head-commit %s --delete-branch" % self.sha
        self.assertEqual(guard_decision(self.root, "Bash", {"command": merge}), "allow")
        self.merged()
        self.assertEqual(guard_decision(self.root, "Bash", {"command": "npm run deploy"}), "allow")

    def set_cap(self, n):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        cur = json.load(open(cfgp))
        cur["autonomy"]["throttle"]["max_per_day"] = n
        with open(cfgp, "w") as f:
            json.dump(cur, f)

    def test_throttle_is_checked_again(self):
        ship_lock(self.root, topic=self.tid)
        self.stamp()
        self.set_cap(0)
        _, p = self.ship_pass()
        self.assertIn("auto-publish limit", p.stderr)
        self.set_cap(1)  # this topic's own stamp is the one publish of the day
        self.assertEqual(self.ship_pass(check=True)[0]["pass"]["pr"], 12)
        data = store.load_topics(self.root)  # another auto merge today takes the room
        data["topics"].append({"id": "t0005", "title": "x", "state": "pr-open", "history": [], "reverted_by": [],
                               "auto_merged_pr": 3, "auto_merged_at": store.now_iso()})
        store.save_topics(self.root, data)
        _, p = self.ship_pass()
        self.assertIn("auto-publish limit", p.stderr)
        lock.force_unlock(self.root)
        ship_lock(self.root, topic=self.tid, attended=True)  # attended counts no stamp of its own
        _, p = self.ship_pass()
        self.assertIn("auto-publish limit", p.stderr)
        # R2-MINOR-4: a stamp from before midnight UTC lends no slot — only the other topics count
        lock.force_unlock(self.root)
        ship_lock(self.root, topic=self.tid)
        data = store.load_topics(self.root)
        store.get_topic(data, self.tid)["auto_merged_at"] = "2000-01-01T23:59:58+00:00"
        store.save_topics(self.root, data)
        _, p = self.ship_pass()
        self.assertIn("limit is reached (1 of 1)", p.stderr)

    def merged(self, merge_commit=None):
        main = sh(self.root, "git", "rev-parse", "main").strip()
        prs = self.gh_prs()
        prs[0].update(state="MERGED", headRefOid=self.sha, mergeCommit={"oid": merge_commit or main})
        self.set_prs(prs)
        return self.hrd("lock", "ship-pass", "--merged", "--topic", self.tid, "--pr", "12", check=True)

    def test_merged_turns_the_pass_from_merge_to_deploy(self):
        ship_lock(self.root, topic=self.tid)
        self.stamp()
        _, p = self.hrd("lock", "ship-pass", "--merged", "--topic", self.tid, "--pr", "12", check=False)
        self.assertIn("no valid pass", p.stderr)
        self.ship_pass(check=True)
        _, p = self.hrd("lock", "ship-pass", "--merged", "--topic", self.tid, "--pr", "12", check=False)
        self.assertIn("not merged", p.stderr)  # GitHub still says OPEN
        prs = self.gh_prs()
        prs[0].update(state="MERGED", headRefOid=self.sha, mergeCommit={"oid": self.sha})  # not in this base
        self.set_prs(prs)
        _, p = self.hrd("lock", "ship-pass", "--merged", "--topic", self.tid, "--pr", "12", check=False)
        self.assertIn("HRD sync", p.stderr)
        prs[0].update(headRefOid="0" * 40)
        self.set_prs(prs)
        _, p = self.hrd("lock", "ship-pass", "--merged", "--topic", self.tid, "--pr", "12", check=False)
        self.assertIn("not merged at the verified head", p.stderr)
        self.assertFalse(lock.valid_pass(self.root)["merged"])
        out, _ = self.merged()
        self.assertTrue(out["pass"]["merged"])
        self.assertTrue(lock.valid_pass(self.root)["merged"])

    def test_guard_lets_the_verified_merge_and_the_deploy_through(self):
        ship_lock(self.root, topic=self.tid)
        self.stamp()
        merge = "gh pr merge 12 --squash --match-head-commit %s --delete-branch" % self.sha
        g = lambda c, env=None: guard_decision(self.root, "Bash", {"command": c}, env)  # noqa: E731
        self.assertEqual(g(merge), "ask")  # no pass yet
        self.ship_pass(check=True)
        self.assertEqual(g(merge), "allow")
        self.assertEqual(g("gh pr merge 12 --match-head-commit=%s" % self.sha), "allow")
        for bad in ("gh pr merge 12 --squash --match-head-commit %s" % ("0" * 40),
                    "gh pr merge 13 --squash --match-head-commit %s" % self.sha,
                    "gh pr merge 12 --squash --admin --match-head-commit %s" % self.sha,
                    "gh pr merge 12 --squash --merge --match-head-commit %s" % self.sha,
                    "gh pr merge 12 --squash",
                    "GH_REPO=o/r gh pr merge 12 --squash --match-head-commit %s" % self.sha,
                    "cd . && gh pr merge 12 --squash --match-head-commit %s" % self.sha,
                    "gh pr merge 12 --squash --match-head-commit %s 2>&1" % self.sha,
                    "gh pr merge 12 --squash --match-head-commit %s; echo done" % self.sha,
                    "gh pr merge 12 --squash --match-head-commit $(git rev-parse HEAD)",
                    "gh pr merge 12 -R o/r --match-head-commit %s" % self.sha):
            self.assertEqual(g(bad), "ask", bad)
        self.assertEqual(g(merge, {"HRD_UNATTENDED": "1"}), "deny")  # unattended unchanged
        self.assertEqual(g("npm run deploy"), "ask")  # the deploy only after the merge (review 24 MINOR-4)
        self.merged()
        self.assertEqual(g(merge), "ask")  # the merge only before it
        # the deploy: the configured string, byte for byte, on base
        self.assertEqual(g("npm run deploy"), "allow")
        self.assertEqual(g("  npm run deploy  "), "allow")
        for bad in ("npm run deploy -- --force", "npm  run deploy", "npx npm run deploy", "npm run deploy && echo x",
                    "env A=1 npm run deploy"):
            self.assertEqual(g(bad), "ask", bad)
        sh(self.root, "git", "switch", "-q", self.branch)
        self.assertEqual(g("npm run deploy"), "ask")  # not on base
        sh(self.root, "git", "switch", "-q", "main")
        # another rule still decides first (§11 m2): nothing is allowed past a protected write
        p = lock.valid_pass(self.root)
        self.assertTrue(p)
        rec = json.load(open(lock.pass_path(self.root)))
        rec["at"] = "2000-01-01T00:00:00+00:00"  # expired
        with open(lock.pass_path(self.root), "w") as f:
            json.dump(rec, f)
        self.assertEqual(g("npm run deploy"), "ask")

    def test_deploy_only_on_the_base_merged_saw(self):
        """R2-MINOR-1: a pass `--merged` marked covers the deploy of that base commit only."""
        ship_lock(self.root, topic=self.tid)
        self.stamp()
        self.ship_pass(check=True)
        out, _ = self.merged()
        self.assertEqual(out["pass"]["base_head"], sh(self.root, "git", "rev-parse", "HEAD").strip())
        self.assertEqual(guard_decision(self.root, "Bash", {"command": "npm run deploy"}), "allow")
        sh(self.root, "git", "commit", "-q", "--allow-empty", "-m", "someone's later change synced in")
        self.assertEqual(guard_decision(self.root, "Bash", {"command": "npm run deploy"}), "ask")
        self.assertEqual(self.merged()[0]["pass"]["base_head"], out["pass"]["base_head"])  # never moved forward
        self.assertEqual(guard_decision(self.root, "Bash", {"command": "npm run deploy"}), "ask")

    def test_other_rules_decide_before_the_pass(self):
        """§11 m2: a valid pass never overrides another rule — a broken `translations` block
        (closed_rule) asks for the very merge; a deploy string writing a protected path asks."""
        ship_lock(self.root, topic=self.tid)
        self.stamp()
        self.ship_pass(check=True)
        merge = "gh pr merge 12 --squash --match-head-commit %s --delete-branch" % self.sha
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        good = open(cfgp).read()
        cur = json.loads(good)
        cur["translations"] = "broken"
        with open(cfgp, "w") as f:
            json.dump(cur, f)
        self.assertEqual(guard_decision(self.root, "Bash", {"command": merge}), "ask")
        with open(cfgp, "w") as f:
            f.write(good)
        self.assertEqual(guard_decision(self.root, "Bash", {"command": merge}), "allow")
        self.merged()
        cur = json.loads(good)
        cur["commands"]["deploy"] = "npm run deploy > .claude/herald/ledger/deploy.log"
        with open(cfgp, "w") as f:
            json.dump(cur, f)
        self.assertEqual(guard_decision(self.root, "Bash", {"command": cur["commands"]["deploy"]}), "ask")


class StrongStampTests(Flow):
    """`auto-merged --consent` takes strong consent from the lock's mark, as `auto-exclusion` does."""

    def tearDown(self):
        lock.force_unlock(self.root)
        super().tearDown()

    def test_mark_other_topic_and_none(self):
        tid, slug = self.run_flow()  # the PR adds 01.png — a picture no record vouches for
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "pr head")
        branch = sh(self.root, "git", "branch", "--show-current").strip()
        sha = sh(self.root, "git", "rev-parse", branch).strip()
        sh(self.root, "git", "switch", "-q", "main")
        args = ("auto-merged", "--topic", tid, "--pr", "7", "--rev", branch, "--sha", sha, "--consent")
        out, _ = self.hrd(*args)  # no mark: 0.19.0
        self.assertEqual(out["accepted"], ["images"])
        self.hrd("auto-merged", "--topic", tid, "--clear")
        ship_lock(self.root, topic="t0999")  # another topic's mark: 0.19.0 too
        self.assertEqual(self.hrd(*args)[0]["accepted"], ["images"])
        self.hrd("auto-merged", "--topic", tid, "--clear")
        lock.force_unlock(self.root)
        ship_lock(self.root, topic=tid)  # its own mark: strong, and the unvouched picture blocks
        _, p = self.hrd(*args, check=False)
        self.assertIn("images-unconfirmed", p.stderr)


# --- the guard: the lock files, --agent, failure (§2.5, §9 R2-3, §10 m4, §11 m2–m3) ------------------

class GuardShipTests(RepoCase):
    def g(self, cmd, env=None):
        return guard_decision(self.root, "Bash", {"command": cmd}, env)

    def tearDown(self):
        lock.force_unlock(self.root)
        super().tearDown()

    def test_lock_files_are_protected(self):
        un = {"HRD_UNATTENDED": "1"}
        for name in (".claude/herald/memory/lock", ".claude/herald/memory/lock.pass"):
            self.assertEqual(guard_decision(self.root, "Write", {"file_path": os.path.join(self.root, name)}), "ask")
            self.assertEqual(guard_decision(self.root, "Edit", {"file_path": os.path.join(self.root, name)}, un), "deny")
            self.assertEqual(self.g("echo '{}' > %s" % name), "ask")
            self.assertEqual(self.g("rm -f %s" % name, un), "deny")
            self.assertEqual(self.g("cp /tmp/x %s" % name), "ask")
        self.assertEqual(self.g("rm -rf .claude/herald/memory"), "ask")  # a directory holding them
        self.assertEqual(self.g("cat .claude/herald/memory/lock"), "none")
        self.assertEqual(self.g("python3 .claude/herald/scripts/hrd.py lock status"), "none")

    def test_agent_flag_passes_only_its_segment_in_a_ship_run(self):
        hrd = "python3 .claude/herald/scripts/hrd.py "
        confirm = hrd + "image confirm --topic t0001 --id e1 --agent"
        self.assertEqual(self.g(confirm), "ask")  # no mark
        tok = lock.acquire(self.root, "write", ship=True, topic="t0001")
        self.assertEqual(self.g(confirm), "none")
        self.assertEqual(self.g(hrd + "image reject --topic t0001 --id e1 --agent --reason x"), "none")
        self.assertEqual(self.g(hrd + "shot confirm --topic t0001 --id s1 --agent"), "none")
        self.assertEqual(self.g(hrd + "image confirm --topic=t0001 --id e1 --ag"), "none")  # argparse prefixes
        self.assertEqual(self.g(hrd + "image confirm --to t0001 --id e1 --agen"), "none")
        self.assertEqual(self.g(hrd + "shot demote --topic t0001 --id s1 --own --agent"), "ask")  # never demote
        self.assertEqual(self.g(hrd + "image confirm --topic t0002 --id e1 --agent"), "ask")  # another topic
        self.assertEqual(self.g(hrd + "image confirm --topic t0001 --id e1"), "ask")  # a human's confirm
        self.assertEqual(self.g(hrd + "image confirm --topic t0001 --id e1 --note=--agent"), "ask")  # a value
        self.assertEqual(self.g(hrd + "image confirm --topic t0001 --id e1 --note --agent"), "ask")
        self.assertEqual(self.g(hrd + "image reject --topic t0001 --id e1 --reason --agent"), "ask")
        self.assertEqual(self.g(confirm + " && echo x > .claude/herald/ledger/confirmations.jsonl"), "ask")
        self.assertEqual(self.g(confirm + " && " + hrd + "shot confirm --topic t0001 --id s1"), "ask")
        self.assertEqual(self.g(confirm, {"HRD_UNATTENDED": "1"}), "deny")  # unattended unchanged
        lock.release(self.root, tok)
        lock.acquire(self.root, "write", ship=True, topic="t0001", attended=True)
        self.assertEqual(self.g(confirm), "ask")  # attended: a human looks (§11 m3)

    def test_no_config_and_broken_config_still_ask_for_a_merge(self):
        cfgp = os.path.join(self.root, ".claude/herald/config.json")
        with open(cfgp) as f:
            good = f.read()
        with open(cfgp, "w") as f:
            f.write("{broken")
        self.assertEqual(self.g("gh pr merge 3 --squash"), "ask")
        self.assertEqual(self.g("GH_REPO=o/r gh pr  merge 3"), "ask")
        self.assertEqual(self.g("ls"), "none")
        os.remove(cfgp)
        self.assertEqual(self.g("gh pr merge 3"), "ask")
        self.assertEqual(self.g("git status"), "none")
        self.assertEqual(self.g("gh pr merge 3", {"HRD_UNATTENDED": "1"}), "none")  # the 0.19.0 path
        with open(cfgp, "w") as f:
            f.write(good)

    def test_guard_crash_asks_for_merge_and_deploy(self):
        from hrdlib import guard
        payload = {"tool_name": "Bash", "tool_input": {"command": "npm run deploy"}, "cwd": self.root}
        for cmd, want in (("npm run deploy", "ask"), ("gh pr merge 1", "ask"), ("ls", None)):
            payload["tool_input"]["command"] = cmd
            out = []
            with mock.patch.object(guard, "check_bash", side_effect=RuntimeError("boom")), \
                    mock.patch.object(sys, "stdin") as stdin, \
                    mock.patch("builtins.print", side_effect=lambda s: out.append(s)), \
                    mock.patch.object(sys, "stderr"):
                stdin.isatty.return_value = False
                stdin.read.return_value = json.dumps(payload)
                with self.assertRaises(SystemExit):
                    guard.main()
            got = json.loads(out[0])["hookSpecificOutput"]["permissionDecision"] if out else None
            self.assertEqual(got, want, cmd)


# --- settings, config-check (§2.6, §9 m5) ------------------------------------------------------------

class SettingsTests(RepoCase):
    def test_template_has_no_merge_ask(self):
        p = os.path.join(SCRIPTS, "..", "templates", "settings.json.tmpl")
        data = json.load(open(p))
        self.assertNotIn("Bash(gh pr merge:*)", data["permissions"]["ask"])
        self.assertIn("Bash(git push --force:*)", data["permissions"]["ask"])

    def test_config_check_warns_every_time(self):
        out, _ = self.hrd("config-check")
        self.assertEqual(out["settings_warnings"], [])
        self.write(".claude/settings.json", json.dumps({"permissions": {"ask": ["Bash(gh pr merge:*)"]}}))
        self.write(".claude/settings.local.json", json.dumps({"permissions": {"ask": ["Bash(npm run deploy:*)"]}}))
        out, _ = self.hrd("config-check")
        self.assertTrue(out["ok"])
        w = "\n".join(out["settings_warnings"])
        self.assertIn(".claude/settings.json asks before `gh pr merge`", w)
        self.assertIn(".claude/settings.local.json has an ask rule matching the deploy command", w)
        self.assertEqual(len(self.hrd("config-check")[0]["settings_warnings"]), 2)  # never remembered

    def test_version(self):
        self.assertEqual(self.hrd("version")[0]["version"], "0.23.2")


if __name__ == "__main__":
    unittest.main()
