"""Stage 2 — close-as-decided, the engine's built-in action (scope §2.6, D18, §7.12 S10, V5: L5).

Order: rationale comment (marker, full-width neutralising, secret scan; id recorded) →
`gh issue close --reason completed|"not planned"` → every later step skipped → log
`issue-closed` → the summary comment updated → exit 0. No push, no PR. The unattended
narrowing (no decision marker → no close in the enum) is session A's; the engine passes the
mode and the marker fact (test_plan_gate).
"""

import json
import unittest

from gxengine import driver, lifecycle
from tests import c_world as W
from tests.test_leader_flow import LA, Stage2, events, steps_of

GH_PAT = "ghp_" + "a1" * 18
CLOSE = ["issue", "close", str(W.ISSUE), "--repo", W.REPO, "--reason"]


def close_answer(reason="not-planned", note="Decided in the owners' meeting: not doing this. cc @alice see #12"):
    return LA("close-as-decided", reason="already-decided", note=note,
              requirements=[{"row": "R1", "covered": True}], missing_requirements=[], plan=None,
              close={"reason": reason})


class Close(Stage2):
    def gh(self, fail_close=False):
        rules = W.gh_rules()
        for reason in ("completed", "not planned"):
            rule = {"args": CLOSE + [reason], "stdout": ""}
            if fail_close:
                rule.update({"exit_code": 1, "stderr": "HTTP 502"})
            rules["rules"].insert(0, rule)
        self.w.set_gh(rules)

    def pushes_and_prs(self):
        return [c for c in self.w.gh_calls() if "pulls" in " ".join(c["argv"])]

    def test_l5_close_comment_close_skip_no_pr(self):
        self.gh()
        ld = self.leader({"plan-gate": [close_answer()]})
        rc = self.run2(ld)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        st = self.w.state()
        calls = self.w.gh_calls()
        closes = [c for c in calls if c["argv"][:2] == ["issue", "close"]]
        self.assertEqual([c["argv"][-1] for c in closes], ["not planned"])
        # the rationale comment came first, neutralised, with the marker; its id is recorded
        posts = [(i, json.loads(c["stdin"])["body"]) for i, c in enumerate(calls)
                 if c["stdin"] and "guild:closed-as-decided" in c["stdin"]]
        self.assertEqual(len(posts), 1)
        i, body = posts[0]
        self.assertLess(i, calls.index(closes[0]))
        self.assertTrue(body.startswith("<!-- guild:closed-as-decided -->"))
        self.assertIn("＠alice", body)
        self.assertIn("＃12", body)
        self.assertEqual(st["closed"]["reason"], "not-planned")
        self.assertIn(st["closed"]["comment_id"], st["github"]["engine_comment_ids"])
        self.assertEqual(steps_of(st)["plan"], "done")
        self.assertEqual(st["revision"], 1)                                # no template attached
        self.assertEqual(self.pushes_and_prs(), [])
        self.assertIsNone(self.w.repo.remote_head("gld/42"))
        closed = events(self.w.log(), "issue-closed")
        self.assertEqual(closed[0]["data"], {"reason": "not-planned", "comment_id": st["closed"]["comment_id"]})
        summary = [json.loads(c["stdin"])["body"] for c in calls
                   if c["argv"][:3] == ["api", "-X", "PATCH"] and c["stdin"]]
        self.assertIn("closed as decided", summary[-1])
        self.assertEqual([c["situation"] for c in ld.calls], ["plan-gate"])

    def test_l5_human_close_needs_a_close_reason(self):
        self.gh()
        ld = self.leader({"plan-gate": [LA("escalate", reason="needs-human-decision",
                                           recommendation={"answer": "close-as-decided", "step": None,
                                                           "note": "already shipped in #12"})]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        self.assertEqual(self.run2(ld, answer={"answer": "close-as-decided", "note": "done"}), driver.EXIT_REFUSED)
        self.assertEqual(self.w.state()["stop"]["reason"], "plan-gate")
        rc = self.run2(ld, answer={"answer": "close-as-decided", "close_reason": "completed", "note": "Shipped."})
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        st = self.w.state()
        self.assertEqual(st["closed"]["reason"], "completed")
        closes = [c["argv"][-1] for c in self.w.gh_calls() if c["argv"][:2] == ["issue", "close"]]
        self.assertEqual(closes, ["completed"])
        ans = [l for l in events(self.w.log(), "answer") if l["data"]["answer"] == "close-as-decided"]
        self.assertEqual(ans[0]["who"], "human")

    def test_a_secret_in_the_note_stops_before_github(self):
        self.gh()
        ld = self.leader({"plan-gate": [close_answer(note=f"token {GH_PAT}")]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual(st["stop"]["reason"], "secret-detected")
        self.assertIsNone(st.get("closed"))
        self.assertFalse([c for c in self.w.gh_calls() if c["argv"][:2] == ["issue", "close"]])
        self.assertNotIn(GH_PAT, json.dumps(self.w.gh_calls()))

    def test_a_failed_close_stops_for_a_human(self):
        self.gh(fail_close=True)
        ld = self.leader({"plan-gate": [close_answer()]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_human", "infra-stop"))
        self.assertIsNone(st.get("closed"))
        self.assertEqual(lifecycle.pending_question(st, stage=2)["allowed_answers"], ["rerun", "escalate"])

    def test_a_leader_close_without_the_close_field_is_a_leader_failure(self):
        self.gh()
        bad = close_answer()
        bad["extra"]["close"] = None
        ld = self.leader({"plan-gate": [bad]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_HUMAN)
        st = self.w.state()
        self.assertEqual(st["stop"]["leader_failed"], {"code": "output-format", "detail": "close-mismatch"})
        self.assertFalse([c for c in self.w.gh_calls() if c["argv"][:2] == ["issue", "close"]])


if __name__ == "__main__":
    unittest.main()
