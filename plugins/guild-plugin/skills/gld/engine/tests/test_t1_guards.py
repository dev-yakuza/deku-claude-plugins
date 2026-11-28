"""Readiness T1 — the entry guards of the first promotion (design/guild/24-redesign/readiness/promote/t1-guards.md).

P3 epic guard (dev / resume refuse an epic, an attended child gets a notice) · P2 an open pull request that closes the
Issue (any branch) refuses a new start · R4-12 own stage labels without engine records (restart from analyze, `guild:done`
on an open Issue without a pull request stops). Real git, gh in process (c_world rules), the stage-4 doubles of
test_stage4_wiring."""

import os
import unittest

from gxengine import cli, defaults, driver, github
from tests import c_world as W
from tests import s3_world as S
from tests.test_stage4_wiring import Stage4World


def issue_rules(labels=(), body=None, state="OPEN", extra=()):
    """c_world's gh rules with the Issue's labels / body / state, and `extra` rules first."""
    rules = W.gh_rules(issue_state=state, labels=labels)
    if body is not None:
        rules["rules"][1]["json"]["body"] = body
    rules["rules"][:0] = list(extra)
    return rules


PARENT = {"args": ["api", f"repos/{W.REPO}/issues/7"], "json": {"number": 7, "state": "open", "labels": []}}


class T1(Stage4World):
    def refused_code(self):
        lines = [l for l in self.log() if (l.get("data") or {}).get("refused")]
        return lines[-1].get("code") if lines else None

    def assertRefusedBeforeAnything(self, rc, code):
        self.assertEqual(rc, driver.EXIT_REFUSED, self.w.out.getvalue())
        self.assertEqual(self.refused_code(), code)
        self.assertIsNone(self.state())
        self.assertEqual(self.session.calls if self.session else [], [])
        self.assertFalse(os.path.exists(self.w.worktree))
        self.assertFalse([c for c in self.w.gh.calls if "-X" in c["argv"]], "nothing written to GitHub")

    def status_text(self):
        return cli._format_status(cli.status_report(self.w.paths()))


class EpicGuard(T1):
    """P3: `guild:children` → unsupported-epic at dev and resume, in both modes; `guild:child` runs, attended with a notice."""

    def test_dev_refuses_an_epic_in_both_modes(self):
        for mode in ("attended", "unattended"):
            with self.subTest(mode=mode):
                self.w.set_gh(issue_rules(labels=("guild:children", "type:feature")))
                self.assertRefusedBeforeAnything(self.run4(self.leader(), mode=mode), "unsupported-epic")
                self.assertIn("epics are not supported yet", self.w.out.getvalue())
                self.assertIn("/gld dev <child>", self.w.out.getvalue())

    def test_the_label_compares_like_github(self):
        self.w.set_gh(issue_rules(labels=(defaults.LABEL_PREFIX.upper() + "Children",)))
        self.assertRefusedBeforeAnything(self.run4(self.leader()), "unsupported-epic")

    def test_resume_refuses_an_issue_that_became_an_epic(self):
        res = S.FakeResults({"design": [W.blocked, W.done]})
        ld = self.leader({"blocked": [W.leader_answer("escalate", recommendation={"answer": "rerun", "step": "design",
                                                                                   "note": ""})]})
        self.assertEqual(self.run4(ld, results=res), driver.EXIT_NEEDS_HUMAN)
        before = self.state()
        self.w.set_gh(issue_rules(labels=("guild:children",)))
        self.assertEqual(self.run4(ld, answer={"answer": "rerun", "step": "design"}, results=res), driver.EXIT_REFUSED)
        self.assertEqual(self.refused_code(), "unsupported-epic")
        self.assertEqual(self.state()["stop"], before["stop"], "the stop waits as it was")
        self.w.set_gh(issue_rules())
        self.ok(self.run4(ld, answer={"answer": "rerun", "step": "design"}, results=res))

    def test_stage_3_does_not_look(self):
        self.w.set_gh(issue_rules(labels=("guild:children",)))
        self.ok(self.run4(self.leader(), stage=3))

    def test_an_attended_child_runs_with_a_notice(self):
        self.w.set_gh(issue_rules(labels=("guild:child",), body="Do a slice.\n\nParent Issue: #7\n", extra=[PARENT]))
        self.ok(self.run4(self.leader()))
        notes = [l for l in self.log("warning") if (l.get("data") or {}).get("kind") == "epic-child"]
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0]["data"]["parent"], notes[0]["data"]["parent_state"]), (7, "OPEN"))
        self.assertIn("- notice: #42 is a child of epic #7 (open) — epics are not supported yet", self.status_text())
        self.assertEqual(cli.status_report(self.w.paths())["notices"][0]["kind"], "epic-child")

    def test_a_child_whose_parent_cannot_be_read_still_runs(self):
        broken = {"args": ["api", f"repos/{W.REPO}/issues/7"], "exit_code": 1, "stderr": "HTTP 502", "times": 1}
        self.w.set_gh(issue_rules(labels=("guild:child",), body="Parent Issue: #7", extra=[broken, PARENT]))
        self.ok(self.run4(self.leader()))
        self.assertIn("epic #7 (state unknown)", self.status_text())

    def test_a_child_without_a_parent_line_still_runs(self):
        self.w.set_gh(issue_rules(labels=("guild:child",), body="no parent line"))
        self.ok(self.run4(self.leader()))
        self.assertIn("child of an epic (no `Parent Issue:` line)", self.status_text())

    def test_an_unattended_child_runs_without_a_word(self):
        self.w.set_gh(issue_rules(labels=("guild:child",), body="Parent Issue: #7", extra=[PARENT]))
        self.ok(self.run4(self.leader(), mode="unattended"))
        self.assertNotIn("notice", self.status_text())
        self.assertFalse([l for l in self.log("warning") if (l.get("data") or {}).get("kind") == "epic-child"])

    def test_no_label_no_notice(self):
        self.ok(self.run4(self.leader()))
        self.assertEqual(cli.status_report(self.w.paths())["notices"], [])


def pr_list(rows=None, **rule):
    """The `gh pr list` rule of a stage-4 start (readiness T1 P2)."""
    r = {"args": ["pr", "list", "--repo", W.REPO, "--state", "open", "--limit", "*", "--json",
                  "number,headRefName,body,closingIssuesReferences"]}
    r.update(rule)
    if "exit_code" not in rule:
        r["json"] = rows or []
    return r


def pr(number, head, body="", refs=()):
    def ref(repo, n):
        owner, name = repo.split("/")
        return {"number": n, "repository": {"name": name, "owner": {"login": owner}},
                "url": f"https://github.com/{repo}/issues/{n}"}
    return {"number": number, "headRefName": head, "body": body, "closingIssuesReferences": [ref(*x) for x in refs]}


def blocked_once(t):
    """A stage-4 run that stops needs_human at design (so the Issue has engine records), and its leader / results."""
    res = S.FakeResults({"design": [W.blocked, W.done]})
    ld = t.leader({"blocked": [W.leader_answer("escalate", recommendation={"answer": "rerun", "step": "design",
                                                                           "note": ""})]})
    t.assertEqual(t.run4(ld, results=res), driver.EXIT_NEEDS_HUMAN)
    return ld, res


class ClosingPr(T1):
    """P2 (user decision 2 B): no engine record + an open pull request on any branch that closes the Issue → no start."""

    def test_refused_in_both_modes_with_the_numbers(self):
        rows = [pr(1924, "feature/#42-quiz", body="Adds the row.\n\nCloses #42")]
        for mode in ("attended", "unattended"):
            with self.subTest(mode=mode):
                self.w.set_gh(issue_rules(extra=[pr_list(rows)]))
                self.assertRefusedBeforeAnything(self.run4(self.leader(), mode=mode), "open-closing-pr")
                self.assertIn("open pull request #1924 (feature/#42-quiz) already closes this Issue",
                              self.w.out.getvalue())
                stop = [l for l in self.log("stop") if (l.get("data") or {}).get("refused")][-1]
                self.assertEqual(stop["to"], "needs_human")

    def test_a_linked_pull_request_without_a_keyword_counts(self):
        self.w.set_gh(issue_rules(extra=[pr_list([pr(7, "fix/x", refs=[(W.REPO, 42)]),
                                                  pr(5, "other", body="Fixes acme/app#42")])]))
        self.assertRefusedBeforeAnything(self.run4(self.leader()), "open-closing-pr")
        self.assertIn("#5 (other), #7 (fix/x)", self.w.out.getvalue())

    def test_pull_requests_of_other_issues_and_repositories_do_not_count(self):
        rows = [pr(1, "a", body="Closes #420 and refs #42"), pr(2, "b", body="Fixes other/app#42"),
                pr(3, "c", refs=[("other/app", 42), (W.REPO, 41)]), pr(4, "d", body="See #42, fixes nothing")]
        self.w.set_gh(issue_rules(extra=[pr_list(rows)]))
        self.ok(self.run4(self.leader()))

    def test_github_not_answering_is_a_refusal(self):
        for rule in (pr_list(exit_code=1, stderr="HTTP 502"), pr_list([pr(n, f"b{n}") for n in range(1, 501)])):
            with self.subTest(rule=str(rule)[:60]):
                self.w.set_gh(issue_rules(extra=[rule]))
                self.assertEqual(self.run4(self.leader()), driver.EXIT_REFUSED)
                self.assertIn("cannot tell whether an open pull request closes the Issue", self.w.out.getvalue())
                self.assertIsNone(self.state())

    def test_an_issue_with_engine_records_does_not_look(self):
        ld, res = blocked_once(self)
        self.w.set_gh(issue_rules(extra=[pr_list([pr(9, "feature/#42", body="Closes #42")])]))
        self.ok(self.run4(ld, answer={"answer": "rerun", "step": "design"}, results=res))
        self.assertFalse([c for c in self.w.gh.calls if c["argv"][:2] == ["pr", "list"]])

    def test_stage_3_does_not_look(self):
        self.w.set_gh(issue_rules(extra=[pr_list([pr(9, "feature/#42", body="Closes #42")])]))
        self.ok(self.run4(self.leader(), stage=3))


class OwnLabels(T1):
    """R4-12, own prefix only (the promoted edition's case is T4's): stage labels without engine records."""

    def deletes(self):
        return [c["argv"][3].rsplit("/", 1)[1] for c in self.w.gh.calls
                if c["argv"][:3] == ["api", "-X", "DELETE"] and "/labels/" in c["argv"][3]]

    def test_stage_labels_without_records_start_from_analyze_and_are_relabelled(self):
        labels = ("guild:execute", "guild:qa", "guild:design", "guild:implement", "guild:followup", "guild:child", "type:feature",
                  "guild:needs-human")
        self.w.set_gh(issue_rules(labels=labels, extra=[PARENT]))
        self.ok(self.run4(self.leader(), mode="unattended"))
        st = self.state()
        self.assertEqual(st["steps"][0]["id"], "analyze")
        self.assertEqual(self.session.calls[0]["step"], "analyze", "the work starts from analyze")
        gone = self.deletes()
        for name in ("guild%3Aexecute", "guild%3Aqa", "guild%3Adesign", "guild%3Aimplement", "guild%3Aneeds-human"):
            self.assertEqual(gone.count(name), 1, (name, gone))
        for kept in ("guild%3Afollowup", "guild%3Achild", "type%3Afeature"):
            self.assertNotIn(kept, gone)
        restart = [l["data"]["name"] for l in self.log("label") if l["data"].get("restart")]
        self.assertEqual(restart, ["guild:execute", "guild:qa", "guild:design", "guild:implement"])
        added = [c for c in self.w.gh.calls if c["argv"][:4] == ["api", "-X", "POST", f"repos/{W.REPO}/issues/42/labels"]]
        self.assertIn('"guild:analyze"', added[0]["stdin"], "the engine's own first label")
        self.assertIn("starting from analyze", self.w.out.getvalue())

    def test_a_failed_removal_is_a_warning(self):
        fail = {"args": ["api", "-X", "DELETE", f"repos/{W.REPO}/issues/42/labels/guild%3Aqa"], "exit_code": 1,
                "stderr": "HTTP 502"}
        self.w.set_gh(issue_rules(labels=("guild:qa",), extra=[fail]))
        self.ok(self.run4(self.leader()))
        self.assertTrue([l for l in self.log("warning") if "guild:qa not removed" in (l.get("note") or "")])

    def test_done_on_an_open_issue_without_a_pull_request_stops_for_a_human(self):
        for mode in ("attended", "unattended"):
            with self.subTest(mode=mode):
                self.w.set_gh(issue_rules(labels=("guild:done",)))
                self.assertRefusedBeforeAnything(self.run4(self.leader(), mode=mode), "done-unconfirmed")
                self.assertIn("whether it is finished is unknown", self.w.out.getvalue())

    def test_done_with_an_open_pull_request_is_the_pull_requests_refusal(self):
        self.w.set_gh(issue_rules(labels=("guild:done",), extra=[pr_list([pr(31, "feature/#42", body="Closes #42")])]))
        self.assertRefusedBeforeAnything(self.run4(self.leader()), "open-closing-pr")

    def test_done_on_a_closed_issue_is_the_closed_refusal(self):
        self.w.set_gh(issue_rules(labels=("guild:done",), state="CLOSED"))
        self.assertEqual(self.run4(self.leader()), driver.EXIT_REFUSED)
        self.assertIn("not open", self.w.out.getvalue())
        self.assertIsNone(self.state())

    def test_labels_of_an_issue_with_records_are_the_engines(self):
        ld, res = blocked_once(self)
        self.w.set_gh(issue_rules(labels=("guild:done", "guild:execute")))
        self.ok(self.run4(ld, answer={"answer": "rerun", "step": "design"}, results=res))
        self.assertFalse([l for l in self.log("label") if l["data"].get("restart")])

    def test_stage_3_does_not_look(self):
        self.w.set_gh(issue_rules(labels=("guild:done", "guild:execute")))
        self.ok(self.run4(self.leader(), stage=3))
        self.assertFalse([l for l in self.log("label") if (l.get("data") or {}).get("restart")])


class BodyCloses(unittest.TestCase):
    """github.body_closes — GitHub's closing keywords, this repository's Issue only."""

    def test_keywords(self):
        yes = ("Closes #42", "closed #42", "FIX #42", "fixes: #42", "Resolved #42", "resolves acme/app#42",
               "fixes https://github.com/acme/app/issues/42", "Fix #42.")
        no = ("Closes #421", "Refs #42", "Closes other/app#42", "closes#42", "prefix-closes #4", "")
        for body in yes:
            self.assertTrue(github.body_closes(body, "acme/app", 42), body)
        for body in no:
            self.assertFalse(github.body_closes(body, "acme/app", 42), body)
