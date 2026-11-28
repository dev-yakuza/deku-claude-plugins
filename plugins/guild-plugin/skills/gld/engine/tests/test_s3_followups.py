"""Stage 3 flow — the create-followups op, security discoveries, the dry run (V8 wiring, session B2).

TF4–TF6 and TF8–TF11 from the driver's side: what is written, in which order, what survives
a failure. GitHub is tests/s3_world.FakeGithub; the texts go through the real outbound checks
in the dry run.
"""

import json
import os
import unittest
from unittest import mock

from gxengine import defaults, driver
from tests import s3_world as S

D1 = {"id": "D1", "kind": "debt", "where": "src/a.py", "blocks_current_ac": False, "role": "tester",
      "note": "dup parsing, see @bob"}
D2 = {"id": "D2", "kind": "bug", "where": "src/b.py", "blocks_current_ac": False, "role": "tester", "note": "old bug"}
D3 = {"id": "D3", "kind": "security", "where": "src/auth.py", "blocks_current_ac": False, "role": "auditor",
      "note": "raw exception text is shown"}
D4 = {"id": "D4", "kind": "doc", "where": "README.md", "blocks_current_ac": False, "role": "qa", "note": "typo"}


def inp(*discoveries):
    return {"done_gate": {"discoveries": list(discoveries)}}


def disp(d, disposition, title=None, duplicate_of=None):
    return {"id": d["id"], "disposition": disposition, "title": title, "duplicate_of": duplicate_of}


class Followups(S.Stage3):
    def run_with(self, *dispositions, discoveries=(D1, D2, D3, D4), **kw):
        gate = S.approve([*dispositions], inp=inp(*discoveries), note="leader says so")
        self.ld = self.leader({"done-gate": [gate]})
        return self.run3(self.ld, **kw)

    def local(self, name):
        p = os.path.join(self.w.paths().issue_dir, name)
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return f.read()

    def comments(self):
        return [json.loads(c["stdin"])["body"] for c in self.w.gh_calls()
                if c["stdin"] and c["argv"][:3] == ["api", "-X", "POST"] and c["argv"][3].endswith("/comments")]

    def test_tf4_tf6_tf8_created_commented_and_the_private_security_issue(self):
        self.gh.candidates = [{"number": 77, "title": "Old", "labels": ["guild:followup"]}]
        self.ok(self.run_with(disp(D1, "followup", "Merge the parsing code"), disp(D2, "duplicate", None, 77),
                              disp(D3, "followup", "Hide the exception text"), disp(D4, "ignore")))
        req = [c["request"] for c in self.ld.calls if c["situation"] == "done-gate"][0]
        self.assertEqual(req.followup_candidates, self.gh.candidates)
        self.assertEqual((req.requests, req.included_fixes, req.deferred_rows), ([], [], []))
        self.assertEqual(self.gh.names(), ["repo_is_private", "followup_candidates", "label_names", "find_followup",
                                           "create_followup", "comment_followup", "find_followup", "create_followup",
                                           "update_pr"])
        a, b = self.gh.issues[900], self.gh.issues[901]
        self.assertEqual((a["title"], a["labels"]), ("Merge the parsing code", ["guild:followup", "type:refactor"]))
        self.assertEqual(b["labels"], ["guild:followup", "guild:security", "type:bug"])
        self.assertRegex(a["marker"], r"^<!-- guild:followup origin=42 key=D1:[0-9a-f]{8} -->$")
        self.assertIn("- PR: #77", a["body"])                                  # prbody.followup_body (E)
        self.assertIn("leader says so", a["body"])
        st = self.state()
        self.assertEqual([(f["key"][:3], f["disposition"], f["number"], f["dry_run"], f["private_path"])
                          for f in st["followups"]],
                         [("D1:", "followup", 900, False, False), ("D2:", "duplicate", 77, False, False),
                          ("D3:", "followup", 901, False, False)])
        self.assertIs(st["github"]["is_private"], True)
        self.assertEqual([l["event"] for l in self.log() if l["event"].startswith("followup")],
                         ["followup-created", "followup-commented", "followup-created"])
        upd = self.gh.calls[-1]
        self.assertEqual((upd["number"], upd["closes"]), (77, 42))
        # E21 (session E, adopted at Q4): the engine-local record holds every security discovery, any visibility
        self.assertIn("raw exception text is shown", self.local(defaults.SECURITY_FINDINGS_FILE))
        self.assertEqual(self.log("security-private-path"), [])
        # the completion comment comes once, after the follow-ups
        done = [c for c in self.comments() if "guild:done" in c]
        self.assertEqual(len(done), 1)
        kinds = [l["event"] + ":" + str((l.get("data") or {}).get("kind")) for l in self.log()]
        self.assertGreater(kinds.index("comment:done"), kinds.index("followup-created:security"))
        # prbody.build's stage-3 dict: the PR first (no follow-ups yet), then the body after the op
        self.assertEqual([(x["is_private"], x["dry_run"]) for x in self.prbody.stage3], [(True, False)] * 2)
        self.assertIsNone(self.prbody.stage3[0]["followups"])
        self.assertEqual([f["number"] for f in self.prbody.stage3[1]["followups"]], [900, 77, 901])

    def test_tf9_public_repository_nothing_of_a_security_discovery_leaves(self):
        for private in (False, None):
            with self.subTest(private=private):
                self.tearDown()
                self.setUp()
                self.gh.private = private
                self.ok(self.run_with(disp(D3, "followup", "Hide the exception text"), discoveries=(D3,)))
                self.assertFalse({"create_followup", "comment_followup", "find_followup"} & set(self.gh.names()))
                text = self.local(defaults.SECURITY_FINDINGS_FILE)
                self.assertIn("raw exception text is shown", text)
                self.assertEqual(driver.read_security_findings(self.w.paths()), text)
                f = self.state()["followups"][0]
                self.assertEqual((f["private_path"], f["number"], f["kind"]), (True, None, "security"))
                self.assertEqual([l["data"]["count"] for l in self.log("security-private-path")], [1])
                sent = json.dumps([c["stdin"] for c in self.w.gh_calls()])
                self.assertNotIn("raw exception text", sent)

    def test_tf5_tf10_a_failure_stops_infra_and_resume_repeats_nothing(self):
        self.gh.fail = {"create_followup": 2}
        rc = self.run_with(disp(D1, "followup", "A"), disp(D2, "followup", "B"), discoveries=(D1, D2))
        self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("infra-stop", "followups"))
        self.assertEqual(st["github"]["pr_number"], 77)                          # the PR stays
        self.assertEqual([f["number"] for f in st["followups"]], [900])
        self.assertEqual([c for c in self.comments() if "guild:done" in c], [])
        # the second Issue exists on GitHub although the engine never recorded it (killed in between)
        marker = [c["marker"] for c in self.gh.calls if c["fn"] == "create_followup"][1]
        self.gh.issues[950] = {"marker": marker}
        self.gh.fail = {}
        before = self.gh.names().count("create_followup")
        self.ok(self.run3(self.ld, answer={"answer": "rerun"}))
        self.assertEqual(self.gh.names().count("create_followup"), before)
        self.assertEqual([f["number"] for f in self.state()["followups"]], [900, 950])
        self.assertEqual(len([c for c in self.comments() if "guild:done" in c]), 1)

    def test_q11_a_security_duplicate_on_a_public_repository_comments_nothing(self):
        """Q11 (real creation is the default): a security discovery the leader calls a duplicate of an open Issue
        is no more written to a public repository than a security follow-up — the other items go on."""
        self.gh.private = False
        self.gh.candidates = [{"number": 77, "title": "Old", "labels": ["guild:followup"]}]
        self.ok(self.run_with(disp(D1, "followup", "Merge the parsing code"), disp(D3, "duplicate", None, 77),
                              discoveries=(D1, D3)))
        self.assertNotIn("comment_followup", self.gh.names())
        self.assertEqual(self.gh.names().count("create_followup"), 1)
        rows = {f["key"][:2]: f for f in self.state()["followups"]}
        self.assertEqual((rows["D3"]["private_path"], rows["D3"]["number"], rows["D3"]["comment_id"]), (True, None, None))
        self.assertEqual(rows["D1"]["number"], 900)
        self.assertNotIn("raw exception text", json.dumps([c["stdin"] for c in self.w.gh_calls()]))
        self.assertNotIn("raw exception text", json.dumps(self.gh.calls, ensure_ascii=False))
        self.assertIn("raw exception text is shown", self.local(defaults.SECURITY_FINDINGS_FILE))

    def test_q11_every_github_failure_of_the_op_is_infra_and_resume_repeats_nothing(self):
        """Q11: a failed label read or duplicate comment stops like a failed create (infra, the PR stays), and the
        resume writes each follow-up once."""
        for fn in ("label_names", "comment_followup"):
            with self.subTest(fails=fn):
                self.tearDown()
                self.setUp()
                self.gh.candidates = [{"number": 77, "title": "Old", "labels": ["guild:followup"]}]
                self.gh.fail = {fn: 1}
                rc = self.run_with(disp(D1, "followup", "A"), disp(D2, "duplicate", None, 77), discoveries=(D1, D2))
                self.assertEqual(rc, driver.EXIT_NEEDS_HUMAN)
                st = self.state()
                self.assertEqual((st["stop"]["reason"], st["stop"]["step"]), ("infra-stop", "followups"))
                self.assertEqual(st["github"]["pr_number"], 77)
                self.assertEqual([c for c in self.comments() if "guild:done" in c], [])
                self.gh.fail = {}
                self.ok(self.run3(self.ld, answer={"answer": "rerun"}))
                self.assertEqual(self.gh.names().count("create_followup"), 1)
                self.assertEqual(self.gh.names().count("comment_followup"), 2 if fn == "comment_followup" else 1,
                                 "the failed comment is tried again, once")
                self.assertEqual([(f["disposition"], f["number"]) for f in self.state()["followups"]],
                                 [("followup", 900), ("duplicate", 77)])
                self.assertEqual(len([c for c in self.comments() if "guild:done" in c]), 1)

    def test_nothing_to_do_is_done_with_the_completion_comment(self):
        self.ok(self.run_with(disp(D4, "ignore"), discoveries=(D4,)))
        self.assertFalse({"label_names", "update_pr", "create_followup"} & set(self.gh.names()))
        self.assertEqual(len([c for c in self.comments() if "guild:done" in c]), 1)

    def test_a_human_approval_uses_no_leader_disposition(self):
        ld = self.leader({"done-gate": [S.LA("escalate", reason="needs-human-decision", recommendation={
            "answer": "approve", "step": None, "note": ""}, discoveries=[disp(D1, "followup", "A")],
            _input=inp(D1))]})
        self.assertEqual(self.run3(ld), driver.EXIT_NEEDS_HUMAN)
        self.ok(self.run3(ld, answer={"answer": "approve"}))
        self.assertNotIn("create_followup", self.gh.names())

    def test_an_answer_over_the_cap_creates_nothing(self):
        # the leader check refuses it (followup-over-cap); one that reaches the op anyway is a fact the
        # engine cannot use (prbody.followup_items -> FactMissing): an infra stop, no Issue (fail-closed, Q4)
        many = [dict(D1, id=f"D{i}", note=f"n{i}") for i in range(1, 8)]
        self.assertEqual(self.run_with(*[disp(d, "followup", d["id"]) for d in many], discoveries=many),
                         driver.EXIT_NEEDS_HUMAN)
        self.assertNotIn("create_followup", self.gh.names())
        self.assertEqual((self.state()["stop"]["reason"], self.state()["stop"]["step"]), ("infra-stop", "followups"))

    def test_the_issue_cap_holds_over_pr_reentry(self):
        # follow-ups an earlier round made count against FOLLOWUPS_MAX of this Issue
        made = [{"key": "D%d:%08x" % (i, i), "kind": "debt", "disposition": "followup", "number": 800 + i,
                 "comment_id": None, "dry_run": False, "private_path": False, "at": "2026-11-24T00:00:00Z"}
                for i in range(11, 10 + defaults.FOLLOWUPS_MAX)]
        orig = driver._followup_work

        def with_made(env, step, attempt):
            env.state["followups"] = list(made)
            return orig(env, step, attempt)
        with mock.patch.object(driver, "_followup_work", with_made):
            self.ok(self.run_with(disp(D1, "followup", "A"), disp(D2, "followup", "B"), discoveries=(D1, D2)))
        self.assertEqual(self.gh.names().count("create_followup"), 1)
        self.assertTrue(any("cap" in (l.get("note") or "") for l in self.log("warning")))


class DryRun(Followups):
    cfg = S.config(followups_dry_run=True)

    test_tf4_tf6_tf8_created_commented_and_the_private_security_issue = None
    test_tf9_public_repository_nothing_of_a_security_discovery_leaves = None
    test_tf5_tf10_a_failure_stops_infra_and_resume_repeats_nothing = None
    test_nothing_to_do_is_done_with_the_completion_comment = None
    test_a_human_approval_uses_no_leader_disposition = None
    test_an_answer_over_the_cap_creates_nothing = None
    test_the_issue_cap_holds_over_pr_reentry = None
    test_q11_a_security_duplicate_on_a_public_repository_comments_nothing = None
    test_q11_every_github_failure_of_the_op_is_infra_and_resume_repeats_nothing = None

    def test_tf11_records_only(self):
        self.ok(self.run_with(disp(D1, "followup", "Tell @bob"), disp(D2, "duplicate", None, 77),
                              discoveries=(D1, D2)))
        self.assertFalse({"create_followup", "comment_followup", "add_label", "find_followup"} & set(self.gh.names()))
        lines = [json.loads(x) for x in self.local(defaults.FOLLOWUPS_DRY_RUN_FILE).splitlines()]
        self.assertEqual([(x["disposition"], x["target"]) for x in lines], [("followup", None), ("duplicate", 77)])
        self.assertNotIn("@", lines[0]["title"] + lines[0]["body"])            # neutralised like a real write
        self.assertEqual(lines[0]["labels"], ["guild:followup", "type:refactor"])
        self.assertEqual([(f["dry_run"], f["number"]) for f in self.state()["followups"]], [(True, None)] * 2)
        self.assertTrue(all(l["data"]["dry_run"] for l in self.log() if l["event"].startswith("followup")))
        self.assertIn("update_pr", self.gh.names())
        self.assertTrue(self.prbody.stage3[-1]["dry_run"])
        self.assertEqual(len([c for c in self.comments() if "guild:done" in c]), 1)

    def test_a_secret_in_a_dry_run_stops_like_a_real_write(self):
        key = "AKIA" + "ABCDEFGHIJ234567"
        self.assertEqual(self.run_with(disp(D1, "followup", f"key {key}"), discoveries=(D1,)),
                         driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.state()["stop"]["reason"], "secret-detected")
        self.assertIsNone(self.local(defaults.FOLLOWUPS_DRY_RUN_FILE))


if __name__ == "__main__":
    unittest.main()
