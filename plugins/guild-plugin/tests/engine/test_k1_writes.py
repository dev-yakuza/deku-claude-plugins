"""K1 — verified GitHub writes (Section F + §2.7), the decision-log writer, pause order, ask/answer."""

import unittest

import _k1
from _k1 import Clock, tmpdir

from guildcore import ask as A
from guildcore import decisions as D
from guildcore import journal as J
from guildcore import pause as PZ
from guildcore.adapters import gh as G
from guildcore.records import decisions as fmt
from guildcore.records import loopback, markers, needs_human
from guildcore.records.write import GhWriter
from guildcore.state import derive, label_names


def world(issue_labels=("guild:test",), comments=(), prs=()):
    fx = {"repo": "o/r", "issues": {"5": {"title": "t", "body": "b", "state": "OPEN",
                                          "labels": [{"name": l} for l in issue_labels],
                                          "comments": list(comments), "timeline": []}},
          "prs": list(prs)}
    read = G.FakeGh(fx)
    write = G.FakeGhWrite(read, clock=Clock())
    return read, write


class Writer(unittest.TestCase):
    def setUp(self):
        self.read, self.write = world()
        self.j = J.Journal(tmpdir(self), 5, clock=Clock())
        self.w = GhWriter(self.read, self.write, journal=self.j, sleep=lambda s: None,
                          key_ctx={"entry_id": "e", "stage": "test", "step_id": "T1", "attempt": 1})

    def test_create_comment_verified_and_journaled(self):
        c = self.w.create_comment(5, "<!-- guild:note -->\nhello")
        self.assertEqual(self.read.comments(5)[0]["id"], c["id"])
        self.assertEqual(self.j.intent_only(), [])
        self.assertEqual(self.j.own_comment_ids(), [c["id"]])

    def test_first_line_marker_required(self):
        with self.assertRaises(ValueError):
            self.w.create_comment(5, "hello <!-- guild:note -->")

    def test_lost_write_retried_once(self):
        self.write.lose_next(1)
        self.w.create_comment(5, "<!-- guild:note -->\nx")
        self.assertEqual(len(self.read.comments(5)), 1)

    def test_lost_twice_is_a_terminal_failure(self):
        self.write.lose_next(2)
        with self.assertRaises(G.GhWriteError) as cm:
            self.w.create_comment(5, "<!-- guild:note -->\nx")
        self.assertEqual(cm.exception.kind, "terminal")
        self.assertEqual(len(self.j.intent_only()), 1)          # never journaled as done

    def test_transient_retry_then_success(self):
        self.write.fail_next("transient")
        self.w.create_comment(5, "<!-- guild:note -->\nx")
        self.assertEqual(len(self.read.comments(5)), 1)

    def test_transient_twice_fails(self):
        self.write.fail_next("transient", 2)
        with self.assertRaises(G.GhWriteError) as cm:
            self.w.create_comment(5, "<!-- guild:note -->\nx")
        self.assertEqual(cm.exception.kind, "transient")

    def test_auth_not_retried(self):
        self.write.fail_next("auth")
        with self.assertRaises(G.GhWriteError) as cm:
            self.w.create_comment(5, "<!-- guild:note -->\nx")
        self.assertEqual(cm.exception.kind, "auth")
        self.assertEqual(len(self.write.calls), 1)

    def test_upsert_skips_identical_and_patches_lowest(self):
        a = self.w.create_comment(5, "<!-- guild:test:output -->\nv1")["id"]
        self.w.create_comment(5, "<!-- guild:test:output -->\nstray")
        n = len(self.write.calls)
        self.assertEqual(self.w.upsert_comment(5, "test:output", "<!-- guild:test:output -->\nv1"), (a, False))
        self.assertEqual(len(self.write.calls), n)
        self.assertEqual(self.w.upsert_comment(5, "test:output", "<!-- guild:test:output -->\nv2"), (a, True))
        self.assertEqual(self.read.comments(5)[0]["body"], "<!-- guild:test:output -->\nv2")

    def test_labels_set_difference_and_own_events(self):
        self.assertEqual(self.w.labels_apply(5, add=["guild:qa", "guild:test"], remove=["guild:test", "guild:needs-human"]),
                         (["guild:qa"], ["guild:test"]))
        self.assertEqual(label_names(self.read.issue(5)["labels"]), ["guild:qa"])
        own = self.j.own_label_writes()
        self.assertEqual(len(own), 2)
        tl_ids = [e["id"] for e in self.read.timeline(5)]
        self.assertEqual(sorted(own), sorted(tl_ids))
        self.assertEqual(self.w.labels_apply(5, add=["guild:qa"]), ([], []))

    def test_own_label_writes_do_not_kill_pending(self):
        blk = fmt.DecisionComment(fmt.render_comment([fmt.render_block(1, {
            "point": "x", "kind": "loopback", "stage": "qa", "status": "pending-human", "at": "2026-11-16T00:00:00Z",
            "options": ["stop"]})])).blocks[0]
        self.w.labels_apply(5, add=["guild:qa"], remove=["guild:test"])
        st = derive(label_names(self.read.issue(5)["labels"]))
        self.assertFalse(D.live(blk, st, self.read.timeline(5))[0])
        self.assertTrue(D.live(blk, st, self.read.timeline(5), own_writes=self.j.own_label_writes())[0])

    def test_append_block_present_check_and_recompute(self):
        cid = self.w.create_comment(5, loopback.render_new_record(
            loopback.render_block(1, "test", "2026-11-16T00:00:01Z", "b", "r", "s")))["id"]
        blk2 = loopback.render_block(2, "qa", "2026-11-16T00:00:02Z", "b", "r2", "s2")
        present = lambda body: "at: 2026-11-16T00:00:02Z" in body
        count = lambda body: body.count("### loopback ")
        got = self.w.append_block(5, "loopback", lambda body: loopback.append(body, blk2), present, count=count)
        self.assertEqual(got, cid)
        body = self.read.comments(5)[0]["body"]
        self.assertEqual(body.count("### loopback "), 2)
        # already present → no second PATCH
        n = len(self.write.calls)
        self.w.append_block(5, "loopback", lambda body: loopback.append(body, blk2), present, count=count)
        self.assertEqual(len(self.write.calls), n)

    def test_pr_body_splice_preserves_human_text(self):
        read, write = world(prs=[{"number": 9, "body": "Human intro\n\nmore", "state": "OPEN"}])
        w = GhWriter(read, write, sleep=lambda s: None)
        blk = "<!-- guild:manual-qa -->\n- [ ] check\n<!-- /guild:manual-qa -->"
        self.assertTrue(w.pr_body_splice(9, "manual-qa", blk))
        self.assertTrue(read.pr(9)["body"].startswith("Human intro\n\nmore"))
        self.assertFalse(w.pr_body_splice(9, "manual-qa", blk))
        read.fx["prs"][0]["body"] += "\n" + blk                # two blocks → refuse, never write back
        with self.assertRaises(ValueError):
            w.pr_body_splice(9, "manual-qa", None)

    def test_issue_create_dedup_by_key(self):
        n, created = self.w.issue_create("slice", "body", labels=["guild:analyze"], key="k1")
        self.assertTrue(created)
        self.assertIn("<!-- guild:slice-key k1 -->", self.read.issue(n)["body"])
        self.assertEqual(self.w.issue_create("slice", "body", key="k1"), (n, False))

    def test_write_forms_enforced(self):
        with self.assertRaises(G.GhError):
            G.assert_write_form(["gh", "pr", "merge", "1"])
        G.assert_write_form(["gh", "issue", "edit", "5", "--add-label", "guild:qa", "--repo", "o/r"])
        cli = G.GhWriteCli("o/r", runner=lambda argv, stdin: '{"id": 1}')
        self.assertEqual(cli.create_comment(5, "x"), {"id": 1})
        with self.assertRaises(G.GhError):
            G.GhCli(runner=lambda a: "").issue_list.__self__._gh(["gh", "api", "repos/o/r/issues/1", "-X", "PATCH"])

    def test_classify(self):
        self.assertEqual(G.classify_error("HTTP 503"), "transient")
        self.assertEqual(G.classify_error("API rate limit exceeded"), "transient")
        self.assertEqual(G.classify_error("HTTP 403: forbidden"), "auth")
        self.assertEqual(G.classify_error("HTTP 404: Not Found"), "terminal")


class DecisionWriting(unittest.TestCase):
    def setUp(self):
        self.read, self.write = world()
        self.w = GhWriter(self.read, self.write, sleep=lambda s: None)
        self.dw = D.DecisionWriter(self.w, 5, Clock())

    def test_first_block_creates_the_log(self):
        did = self.dw.record({"point": "engine-start", "by": "code", "started_at_stage": "test", "plugin": "0.102.0"})
        self.assertEqual(did, "D1")
        body = self.read.comments(5)[0]["body"]
        self.assertTrue(body.startswith("<!-- guild:decisions -->\n"))

    def test_numbering_and_amend(self):
        self.dw.record({"point": "a", "by": "code"})
        did = self.dw.record({"point": "b", "by": "code", "kind": "loopback", "status": "pending-human",
                              "options": ["loop-back", "stop"], "question": "q?", "stage": "test"})
        self.assertEqual(did, "D2")
        self.assertTrue(self.dw.stamp_server_time(did))
        log = D.DecisionLog.load(self.read.comments(5))
        self.assertTrue(log.by_id("D2").get("at_server"))
        self.assertFalse(self.dw.amend("D2", "at_server", "x"))        # append-only per key

    def test_rollover(self):
        self.dw.record({"point": "a", "by": "code", "reason": "r" * 1900})
        body = self.read.comments(5)[0]["body"]
        self.read.fx["issues"]["5"]["comments"][0]["body"] = body.replace(
            "</details>", "\n".join(["### decision %d\nid: D%d\npoint: x\n" % (i, i) for i in range(2, 1800)]) + "\n</details>")
        did = self.dw.record({"point": "next", "by": "code", "reason": "y" * 1500})
        cs = self.read.comments(5)
        self.assertEqual(len(cs), 2)
        self.assertTrue(cs[1]["body"].startswith("<!-- guild:decisions -->\ncontinued-from: %d" % cs[0]["id"]))
        self.assertEqual(D.DecisionLog.load(cs).by_id(did).n, 1800)

    def test_race_renumbers(self):
        self.dw.record({"point": "a", "by": "code"})
        orig = self.w._perform
        state = {"raced": False}

        def racing(op, target, do, verify, **kw):
            if op == "decisions:append" and not state["raced"]:
                state["raced"] = True
                c = self.read.fx["issues"]["5"]["comments"][0]
                c["body"] = fmt.insert(c["body"], fmt.render_block(2, {"point": "other", "by": "human"}))
            return orig(op, target, do, verify, **kw)
        self.w._perform = racing
        did = self.dw.record({"point": "mine", "by": "code"})
        log = D.DecisionLog.load(self.read.comments(5))
        self.assertEqual(sorted(b.n for b in log.blocks), sorted(set(b.n for b in log.blocks)))
        self.assertEqual(log.by_id(did).get("point"), "mine")

    def test_resolve_refuses_twice(self):
        self.dw.record({"point": "p", "by": "code", "kind": "budget", "status": "pending-human",
                        "options": ["ok"], "stage": "qa"})
        self.dw.resolve("D1", {"by": "human", "choice": "ok"})
        with self.assertRaises(ValueError):
            self.dw.resolve("D1", {"by": "human", "choice": "ok"})


def question(**kw):
    return A.Question("loopback", "Loop back to execute?", [{"token": "loop-back", "label": "loop"},
                                                            {"token": "stop", "label": "stop"}],
                      recommended="loop-back", recommended_by="judge:sonnet", **kw)


class PauseAndAsk(unittest.TestCase):
    def setUp(self):
        self.read, self.write = world()
        self.j = J.Journal(tmpdir(self), 5, clock=Clock())
        self.w = GhWriter(self.read, self.write, journal=self.j, sleep=lambda s: None)
        self.dw = D.DecisionWriter(self.w, 5, Clock())

    def test_pause_order_block_comment_label(self):
        order = []
        orig_create, orig_labels = self.w.create_comment, self.w.labels_apply
        self.w.create_comment = lambda *a, **k: (order.append("comment"), orig_create(*a, **k))[1]
        self.w.labels_apply = lambda *a, **k: (order.append("label"), orig_labels(*a, **k))[1]
        res = PZ.pause(self.w, self.dw, 5, PZ.Pause("defect", "loop-back cap reached"), question=question(), stage="test")
        self.assertEqual(order, ["comment", "comment", "label"])     # decision log, needs-human, label
        log = D.DecisionLog.load(self.read.comments(5))
        b = log.by_id(res["did"])
        self.assertEqual(b.get("status"), "pending-human")
        self.assertEqual(int(b.get("pause_comment")), res["comment_id"])
        self.assertTrue(b.get("at_server"))
        nh = needs_human.from_comments(self.read.comments(5))[-1]
        self.assertTrue(nh.cause_check_ok())
        self.assertIn("guild-answer: D1 <token>", nh.body)
        self.assertIn("guild:needs-human", label_names(self.read.issue(5)["labels"]))

    def test_pause_without_question(self):
        res = PZ.pause(self.w, self.dw, 5, PZ.Pause("env", "역할 권한 거부: git push", env_key="other"))
        self.assertIsNone(res["did"])
        self.assertEqual(len(self.read.comments(5)), 1)

    def test_complete_after_crash(self):
        did = self.dw.record(question().pending_fields(stage="test"))
        blk = D.DecisionLog.load(self.read.comments(5)).by_id(did)
        PZ.complete(self.w, self.dw, 5, blk, PZ.Pause("defect", "loop-back cap reached"))
        self.assertIn("guild:needs-human", label_names(self.read.issue(5)["labels"]))
        self.assertEqual(len(needs_human.from_comments(self.read.comments(5))), 1)
        blk = D.DecisionLog.load(self.read.comments(5)).by_id(did)
        PZ.complete(self.w, self.dw, 5, blk, PZ.Pause("defect", "loop-back cap reached"))
        self.assertEqual(len(needs_human.from_comments(self.read.comments(5))), 1)   # not twice

    def test_attended_ask_event_and_answer(self):
        ev = _k1.W_Events = __import__("guildcore.worker", fromlist=["Events"]).Events(tmpdir(self), 5)
        self.w.labels_apply(5, add=["guild:needs-human"])
        qid = A.surface(question(), True, self.dw, events=ev, clock=Clock(), stage="test", journal=self.j)
        e = ev.read()[-1]
        self.assertEqual((e["type"], e["qid"], e["recommended"]), ("ask", qid, "loop-back"))
        did = A.answer(self.dw, self.w, 5, qid, "loop-back", journal=self.j, login="owner")
        self.assertNotIn("guild:needs-human", label_names(self.read.issue(5)["labels"]))
        self.assertEqual(self.j.epoch(), 1)
        with self.assertRaises(ValueError):
            A.answer(self.dw, self.w, 5, qid, "stop")
        self.assertEqual(D.DecisionLog.load(self.read.comments(5)).by_id(did).get("resolves"), qid)

    def test_stop_keeps_needs_human(self):
        self.w.labels_apply(5, add=["guild:needs-human"])
        qid = self.dw.record(question().pending_fields(stage="test"))
        A.answer(self.dw, self.w, 5, qid, "stop")
        self.assertIn("guild:needs-human", label_names(self.read.issue(5)["labels"]))

    def test_predict_first_hides_then_reveals(self):
        ev = __import__("guildcore.worker", fromlist=["Events"]).Events(tmpdir(self), 5)
        q = question(predict_first=True)
        qid = A.surface(q, True, self.dw, events=ev, clock=Clock(), stage="test", journal=self.j)
        e = ev.read()[-1]
        self.assertNotIn("recommended", e)
        b = D.DecisionLog.load(self.read.comments(5)).by_id(qid)
        self.assertIsNone(b.get("recommended"))
        self.assertEqual(len(b.get("recommended_sha")), 64)
        did = A.answer(self.dw, self.w, 5, qid, "stop", journal=self.j)
        r = D.DecisionLog.load(self.read.comments(5)).by_id(did)
        import hashlib
        self.assertEqual(hashlib.sha256((r.get("recommended") + r.get("nonce")).encode()).hexdigest(),
                         b.get("recommended_sha"))

    def test_bad_question(self):
        with self.assertRaises(ValueError):
            A.Question("not-a-kind", "q", [{"token": "a"}])
        with self.assertRaises(ValueError):
            A.Question("budget", "q", [{"token": "a"}], recommended="b")

    def _pending_unattended(self):
        res = PZ.pause(self.w, self.dw, 5, PZ.Pause("defect", "cap"), question=question(), stage="test")
        return D.DecisionLog.load(self.read.comments(5)).by_id(res["did"])

    def _human(self, cid, body, login="owner", at="2026-11-16T09:00:00Z", unlabel_by="owner"):
        self.read.fx["issues"]["5"]["comments"].append(_k1._util.comment(body, cid=cid, at=at, login=login))
        if unlabel_by:
            self.read.fx["issues"]["5"]["timeline"].append({"id": 70000 + cid, "event": "unlabeled",
                                                           "label": {"name": "guild:needs-human"},
                                                           "created_at": at, "actor": {"login": unlabel_by}})

    def test_settle_answered(self):
        blk = self._pending_unattended()
        self._human(501, "guild-answer: D1 loop-back")
        st, did = A.settle(self.dw, self.w, 5, blk, self.read.comments(5), self.read.timeline(5), journal=self.j)
        self.assertEqual(st, "answered")
        r = D.DecisionLog.load(self.read.comments(5)).by_id(did)
        self.assertEqual((r.get("answered_by"), r.get("answer_comment"), r.get("choice")), ("owner", "501", "loop-back"))

    def test_settle_conflict_stays_pending(self):
        blk = self._pending_unattended()
        self._human(501, "guild-answer: D1 loop-back", login="a", unlabel_by="a")
        self._human(502, "guild-answer: D1 stop", login="b", at="2026-11-16T09:01:00Z", unlabel_by="b")
        st, ans = A.settle(self.dw, self.w, 5, blk, self.read.comments(5), self.read.timeline(5))
        self.assertEqual(st, "conflict")
        self.assertEqual(len(ans), 2)
        self.assertEqual(D.DecisionLog.load(self.read.comments(5)).pending_human()[0].id, "D1")

    def test_settle_rejected_answer_noted_once(self):
        blk = self._pending_unattended()
        self._human(501, "guild-answer: D1 maybe")
        for _ in range(2):
            st, _x = A.settle(self.dw, self.w, 5, blk, self.read.comments(5), self.read.timeline(5))
            self.assertEqual(st, "none")
        notes = [b for b in D.DecisionLog.load(self.read.comments(5)).blocks if b.get("point") == "rejected-answer"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].get("reason"), "token not in options")


if __name__ == "__main__":
    unittest.main()
