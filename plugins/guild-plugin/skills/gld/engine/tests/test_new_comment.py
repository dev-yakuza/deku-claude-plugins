"""Stage 2 — a new collaborator comment is a leader judgment (scope §2.5, §7.4 2, D16, V7: L11).

Engine side: the between-step stop becomes a needs_leader call (not counted against the
cap), the request names the new comments (bundled) and carries a re-made issue.md, the
answer's `effects` go to the `answer` log line (metric "가정이 틀려 다시 한 작업"), and a
resume after a crash finds the same comments again. The D16 checks on the answer itself
(cover, continue-with-effect, adds-requirement → analyze) are session A's.
"""

import unittest

from gxengine import driver, lifecycle
from tests import c_world as W
from tests.test_leader_flow import LA, Stage2, events, steps_of


def comment_answer(answer, effects, step=None, reason=None):
    return LA(answer, step=step, reason=reason or ("comment-no-effect" if answer == "continue"
                                                   else "assumption-corrected"),
              comments=[{"id": i, "effect": e} for i, e in effects])


class NewComment(Stage2):
    def seq(self, *later):
        """Comments as GitHub returns them: none for the first reads, then `later` (repeats)."""
        return W.gh_rules(comments_seq=[[]] * 6 + [list(later)])

    def test_l11_continue_is_not_counted_and_the_request_names_the_comments(self):
        self.w.set_gh(self.seq(W.collab(9001, body="Progress looks fine."),
                               W.collab(9002, body="Also fine.", assoc="OWNER")))
        ld = self.leader({"new-collaborator-comment": [comment_answer("continue", [(9001, "none"),
                                                                                  (9002, "none")])]})
        rc = self.run2(ld)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        calls = [c for c in ld.calls if c["situation"] == "new-collaborator-comment"]
        self.assertEqual(len(calls), 1)                                  # both comments in one call
        req = calls[0]["request"]
        self.assertEqual(req.kind, "leader")
        self.assertEqual([c["id"] for c in req.new_comments], [9001, 9002])
        self.assertEqual(req.new_comments[1]["author_association"], "OWNER")
        self.assertEqual(req.new_comments[0]["created_at"], "2026-11-23T02:00:00Z")
        self.assertIn("Progress looks fine.", req.issue_md)                # issue.md re-made
        st = self.w.state()
        self.assertEqual(st["totals"]["leader_calls"], 0)                 # not counted (D14, §5.1)
        entry = [c for c in st["leader_calls"] if c["situation"] == "new-collaborator-comment"][0]
        self.assertFalse(entry["counted"])
        ans = [l for l in events(self.w.log(), "answer") if l["code"] == "new-collaborator-comment"][0]
        self.assertEqual(ans["data"]["effects"], [{"id": 9001, "effect": "none"}, {"id": 9002, "effect": "none"}])
        self.assertEqual(st["github"]["last_seen_comment_id"], 9002)

    def test_l11_corrected_assumption_reruns_analyze_and_is_countable(self):
        self.w.set_gh(self.seq(W.collab(9001, body="Correction: iOS only.")))
        ld = self.leader({"new-collaborator-comment": [comment_answer("rerun", [(9001, "corrects-assumption")],
                                                                      step="analyze")]})
        rc = self.run2(ld)
        self.assertEqual(rc, driver.EXIT_OK, self.w.out.getvalue())
        back = [l for l in events(self.w.log(), "back-to") if l["data"].get("answer") == "rerun"]
        self.assertEqual(back[0]["data"]["target"], "analyze")
        # metric (§9.5): a new-comment situation answered rerun / replan with a non-none effect
        reworked = [l for l in events(self.w.log(), "answer")
                    if l["who"] == "leader" and l["code"] == "new-collaborator-comment"
                    and l["data"]["answer"] in ("rerun", "replan")
                    and any(e["effect"] != "none" for e in l["data"]["effects"])]
        self.assertEqual(len(reworked), 1)
        self.assertEqual(self.w.state().get("counters", {}).get("plan_rerun", 0), 0)   # not a plan-gate rerun

    def test_l11_a_resume_finds_the_same_comments(self):
        self.w.set_gh(self.seq(W.collab(9001)))
        ld = self.leader({"new-collaborator-comment": [{"stop": "infra-stop"},
                                                       comment_answer("continue", [(9001, "none")])]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_LEADER)
        st = self.w.state()
        self.assertEqual((st["stop"]["status"], st["stop"]["reason"]), ("needs_leader", "new-collaborator-comment"))
        self.assertEqual(steps_of(st)[st["stop"]["step"]], "pending")      # between steps: untouched
        # GitHub keeps showing the comment to the new engine (the fake's read sequence restarts)
        self.w.set_gh(W.gh_rules(comments_seq=[[W.collab(9001)]]))
        self.assertEqual(self.run2(ld), driver.EXIT_OK, self.w.out.getvalue())
        calls = [c for c in ld.calls if c["situation"] == "new-collaborator-comment"]
        self.assertEqual([[x["id"] for x in c["request"].new_comments] for c in calls], [[9001], [9001]])

    def test_a_comment_gone_from_the_issue_is_not_guessed(self):
        self.w.set_gh(self.seq(W.collab(9001)))
        ld = self.leader({"new-collaborator-comment": [{"stop": "infra-stop"}]})
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_LEADER)
        self.w.set_gh(W.gh_rules())                                        # deleted on GitHub meanwhile
        n = len(ld.calls)
        self.assertEqual(self.run2(ld), driver.EXIT_NEEDS_LEADER)          # fact missing → no call (§9.3)
        self.assertEqual(len(ld.calls), n)
        self.assertIn("fact-collection", self.w.state()["stop"]["note"])

    def test_a_new_comment_still_calls_the_leader_after_the_cap(self):
        self.w.set_gh(self.seq(W.collab(9001)))
        ld = self.leader({"new-collaborator-comment": [comment_answer("continue", [(9001, "none")])]})
        # five counted calls already used (set at the first call): the comment is not counted,
        # so the leader is still called (D14)
        orig = ld.call

        def call(req):
            req.state.setdefault("totals", {})["leader_calls"] = 5
            return orig(req)
        ld.call = call
        self.assertEqual(self.run2(ld), driver.EXIT_OK, self.w.out.getvalue())
        self.assertIn("new-collaborator-comment", [c["situation"] for c in ld.calls])
        self.assertEqual(lifecycle.pending_question(self.w.state(), stage=2), None)


if __name__ == "__main__":
    unittest.main()
