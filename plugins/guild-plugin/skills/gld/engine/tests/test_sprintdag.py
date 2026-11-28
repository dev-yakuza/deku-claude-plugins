"""VA1 — the member table, plan hash, order, dependency verdicts, base choice, run window (TD, TW1, TW2)."""

import itertools
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

from gxengine import codes, sprintdag as D

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STABLE_DAG = os.path.join(os.path.dirname(ENGINE), "commands", "atoms", "sprint_dag.py")

HEAD6 = "| # | 이슈 | base 의존 | 원래 의존 | 비고 | 구분 |\n|---|---|---|---|---|---|"
HEAD5 = "| # | 이슈 | base 의존 | 원래 의존 | 비고 |\n|---|---|---|---|---|"


def body(rows, head=HEAD6, meta="plan-hash: 0123456789ab\n- 목표: x\n- 상한 근거: squash-sync\n"):
    return ("# Sprint: x\n\n<!-- guild:sprint:plan -->\n" + meta + "\n## 멤버 (실행 순서 · 의존성 정본)\n" + head + "\n"
            + "\n".join(rows) + "\n<!-- /guild:sprint:plan -->\n\n보드: https://example.invalid\n")


ROWS = ["| 1 | #101 | — | — | 🏗 기초 | goal |", "| 2 | #102 | #101 | — | a \\| b | goal |",
        "| 3 | #104 | #102 | #101, #102 | fan-in | other |"]


class Table(unittest.TestCase):
    """TD1, TD5."""

    def test_six_columns(self):
        self.assertEqual(D.parse_table(body(ROWS)), [D.Member(101, None, "goal"), D.Member(102, 101, "goal"),
                                                     D.Member(104, 102, "other")])
        self.assertEqual(len(D.parse_table(body(ROWS).replace("\n", "\r\n"))), 3)

    def test_the_old_five_columns_are_read_in_number_order(self):
        rows = ["| 1 | #9 | — | — | |", "| 2 | #3 | — | — | |"]
        got = D.parse_table(body(rows, HEAD5))
        self.assertEqual([m.kind for m in got], [None, None])
        self.assertEqual(D.order(got), ([3, 9], []))

    def test_refused(self):
        bad = {
            "no block": "# Sprint\n" + HEAD6,
            "two blocks": body(ROWS) + body(ROWS),
            "markers reversed": "<!-- /guild:sprint:plan --> <!-- guild:sprint:plan -->",
            "no table": body([], head=""),
            "no rows": body([]),
            "no separator": body(ROWS, head=HEAD6.split("\n")[0]),
            "two tables": body(ROWS + [""] + [HEAD6] + ROWS),
            "another column order": body(ROWS, head=HEAD6.replace("이슈 | base 의존", "base 의존 | 이슈")),
            "kind not last": body(ROWS, head=HEAD6.replace("비고 | 구분", "구분 | 비고")),
            "a column missing": body(ROWS, head=HEAD6.replace(" 원래 의존 |", "").replace("|---|---|---|---|---|---|", "|---|---|---|---|---|")),
            "two dependencies": body(["| 1 | #1 | #2, #3 | — | | goal |"]),
            "a dependency as text": body(["| 1 | #1 | 101 | — | | goal |"]),
            "empty dependency": body(["| 1 | #1 |  | — | | goal |"]),
            "unknown kind": body(["| 1 | #1 | — | — | | 목표 |"]),
            "empty kind": body(["| 1 | #1 | — | — | | |"]),
            "not an issue": body(["| 1 | 101 | — | — | | goal |"]),
            "leading zero": body(["| 1 | #01 | — | — | | goal |"]),
            "another repository": body(["| 1 | acme/x#1 | — | — | | goal |"]),
            "duplicate member": body(ROWS[:1] * 2),
            "itself": body(["| 1 | #1 | #1 | — | | goal |"]),
            "too few cells": body(["| 1 | #1 | — | goal |"]),
            "open row": body(["| 1 | #1 | — | — | | goal"]),
            "interrupted": body([ROWS[0], "", ROWS[1]]),
        }
        for name, text in bad.items():
            with self.subTest(name=name), self.assertRaises(D.SprintTableError):
                D.parse_table(text)
        for text in (None, "", 3):
            with self.assertRaises(D.SprintTableError):
                D.parse_table(text)

    def test_depends_on_lines_mean_nothing(self):
        text = body(ROWS, meta="plan-hash: 0123456789ab\nDepends on: #999\n- Depends on: #101\n")
        self.assertEqual(D.parse_table(text), D.parse_table(body(ROWS)))

    def test_stored_hash(self):
        self.assertEqual(D.stored_plan_hash(body(ROWS)), "0123456789ab")
        self.assertIsNone(D.stored_plan_hash(body(ROWS, meta="- 목표: x\n")))
        for meta in ("plan-hash: 0123\n", "plan-hash:\n", "plan-hash: 0123456789AB\n", "plan-hash: 0123456789ab\n" * 2):
            with self.assertRaises(D.SprintTableError):
                D.stored_plan_hash(body(ROWS, meta=meta))

    def test_stack_reason_token(self):
        for line, want in (("- 상한 근거: squash-sync", "squash-sync"), ('- 상한 근거: "config"', "config"),
                           ("상한 근거: `human-override`", "human-override"), ("- 상한 근거: merge-commit-forbidden", "merge-commit-forbidden"),
                           ("- 상한 근거: squash", None), ("- 상한 근거: squash-sync (사람)", None), ("- 목표: x", None),
                           ("- 상한 근거: config\n- 상한 근거: squash-sync", None)):
            self.assertEqual(D.stack_reason_token(body(ROWS, meta=line + "\n")), want, line)


class Parity(unittest.TestCase):
    """TD2: the 0.98.7 script, run for real, gives the same order and hash."""

    def dag(self, mode, obj):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "in.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
            p = subprocess.run([sys.executable, "-I", STABLE_DAG, "--input", path, "--mode", mode], capture_output=True, text=True)
        return p.returncode, p.stdout.split()

    def test_order(self):
        rnd = random.Random(7)
        cases = [[(101, None, "goal"), (102, 101, "goal"), (103, None, "other"), (104, 103, "slot")],
                 [(9, None, None), (3, None, None), (5, 9, None)],
                 [(1, 2, "goal"), (2, 1, "goal")],                                   # a cycle
                 [(5, 77, "goal"), (4, 5, "other"), (3, None, "other")]]             # a dependency outside
        for _ in range(16):
            nums = rnd.sample(range(1, 60), rnd.randint(2, 7))
            cases.append([(n, rnd.choice([None, None, rnd.choice(nums), 999]), rnd.choice(["goal", "other", "slot"])) for n in nums])
        for case in cases:
            members = [D.Member(*c) for c in case]
            rc, out = self.dag("order", {"members": [
                dict({"number": n, "base_deps": [] if d is None else [d]}, **({"kind": k} if k else {})) for n, d, k in case]})
            with self.subTest(case=case):
                try:
                    got = D.order(members)[0]
                except D.SprintTableError:
                    self.assertEqual(rc, 2)
                    continue
                self.assertEqual((rc, out), (0, [str(n) for n in got]))

    def test_hash(self):
        texts = [body(ROWS), body(ROWS, meta="- 목표: x\n"), body(ROWS).replace("\n", "\r\n"),
                 body(ROWS).replace("<!-- guild:sprint:plan -->\n", "<!-- guild:sprint:plan -->\n\n  \n"),
                 body(ROWS, meta="  plan-hash: zz\n- 목표: x   \n\n\n"), "<!-- guild:sprint:plan --><!-- /guild:sprint:plan -->"]
        for t in texts:
            rc, out = self.dag("hash", {"text": t})
            self.assertEqual((rc, out), (0, [D.plan_hash(t)]), t)
        self.assertEqual(len({D.plan_hash(texts[0]), D.plan_hash(texts[2])}), 1, "CR is formatting")
        with self.assertRaises(D.SprintTableError):
            D.plan_hash("no markers")

    def test_the_stored_hash_is_not_part_of_the_hash(self):
        a = body(ROWS)
        h = D.plan_hash(a)
        b = a.replace("plan-hash: 0123456789ab", "plan-hash: " + h)
        self.assertEqual((D.plan_hash(b), D.stored_plan_hash(b)), (h, h))


class Order(unittest.TestCase):
    def test_goal_first_then_number(self):
        ms = [D.Member(3, None, "other"), D.Member(7, None, "slot"), D.Member(9, None, "goal"), D.Member(1, 9, "goal")]
        self.assertEqual(D.order(ms), ([7, 9, 1, 3], []))

    def test_a_dependency_outside_the_table_is_dropped_with_a_warning(self):
        got, warnings = D.order([D.Member(5, 77, "goal")])
        self.assertEqual(got, [5])
        self.assertIn("#77", warnings[0])
        self.assertEqual(D.effective_deps([D.Member(5, 77, "goal")])[0], {5: None})

    def test_a_cycle_is_refused(self):                                                      # TD6
        with self.assertRaises(D.SprintTableError):
            D.order([D.Member(1, 3), D.Member(2, 1), D.Member(3, 2), D.Member(4)])
        with self.assertRaises(D.SprintTableError):
            D.order([])
        with self.assertRaises(D.SprintTableError):
            D.order([D.Member(1), D.Member(1)])


def pr(state, number=900):
    return {"number": number, "state": state, "head_sha": "a" * 40, "base": "main"}


def facts(**over):
    kw = {"issue": 1, "issue_state": "OPEN", "state_reason": None, "prs": [], "local": None, "outcome": None}
    kw.update(over)
    return D.DepFacts(**kw)


FINISHED = {"finished": True, "stopped": False, "pr_number": 900}
STOPPED = {"finished": False, "stopped": True, "pr_number": 900}
RUNNING = {"finished": False, "stopped": False, "pr_number": None}
DONE = dict(issue_state="CLOSED", state_reason="COMPLETED")


class DepState(unittest.TestCase):
    """TD3 (§2.3, every line), TD4, review-q0 D4 (the order)."""

    def verdict(self, **over):
        v = D.member_state(facts(**over))
        return v.block or v.base

    def test_the_fact_table(self):
        for want, over in (
                ("default", dict(prs=[pr("MERGED")])),
                ("default", dict(prs=[pr("MERGED")], **DONE)),
                ("default", DONE),
                ("dep-not-planned", dict(issue_state="CLOSED", state_reason="NOT_PLANNED")),
                ("stack", dict(prs=[pr("OPEN")], local=FINISHED)),
                ("dep-stopped", dict(prs=[pr("OPEN")], local=STOPPED)),
                ("dep-pr-closed", dict(prs=[pr("CLOSED")], local=FINISHED)),
                ("dep-pr-ambiguous", dict(prs=[pr("OPEN"), pr("OPEN", 901)], local=FINISHED)),
                ("dep-not-done", {}),
                ("dep-not-done", dict(prs=[pr("OPEN")])),                     # no state.json on this machine
                ("dep-not-done", dict(prs=[pr("OPEN")], local=RUNNING)),
                ("dep-not-done", dict(issue_state="CLOSED"))):                # closed, GitHub gives no reason
            with self.subTest(over=over):
                self.assertEqual(self.verdict(**over), want)

    def test_the_order_of_the_rules(self):
        for want, over in (
                ("upstream", dict(outcome="blocked", prs=[pr("MERGED")], **DONE)),                # 1 before 2
                ("default", dict(outcome="refused", **DONE)),                                     # 2 before 3
                ("default", dict(outcome="failed", prs=[pr("MERGED")], **DONE)),
                ("default", dict(local=STOPPED, prs=[pr("MERGED")], **DONE)),                     # 2 before 4
                ("dep-failed", dict(outcome="failed", prs=[pr("MERGED")])),                       # merged alone: 3 first
                ("dep-stopped", dict(local=STOPPED, prs=[pr("MERGED")])),                         # reopened and stopped (X15)
                ("dep-failed", dict(outcome="failed", prs=[pr("OPEN")], local=FINISHED)),
                ("dep-stopped", dict(outcome="stopped")), ("dep-stopped", dict(outcome="skipped-locked")),
                ("dep-failed", dict(outcome="refused")),
                ("stack", dict(outcome="done", prs=[pr("OPEN")], local=FINISHED)),
                ("default", dict(outcome="closed", **DONE)),
                ("stack", dict(prs=[pr("CLOSED", 1), pr("OPEN", 2)], local=FINISHED)),
                ("dep-pr-ambiguous", dict(prs=[pr("MERGED", 1), pr("OPEN", 2), pr("OPEN", 3)]))):
            with self.subTest(over=over):
                self.assertEqual(self.verdict(**over), want)
        self.assertEqual(D.member_state(facts(prs=[pr("CLOSED", 1), pr("OPEN", 2)], local=FINISHED)).pr["number"], 2)

    def test_every_input_has_exactly_one_answer_and_blocked_is_never_startable(self):
        prs = ([], [pr("OPEN")], [pr("MERGED")], [pr("CLOSED")], [pr("OPEN"), pr("OPEN", 2)], [pr("CLOSED"), pr("OPEN", 2)])
        for st, rs, p, local, out in itertools.product(("OPEN", "CLOSED"), (None, "COMPLETED", "NOT_PLANNED"), prs,
                                                       (None, FINISHED, STOPPED, RUNNING), [None] + codes.MemberOutcome.values()):
            v = D.member_state(facts(issue_state=st, state_reason=rs, prs=p, local=local, outcome=out))
            if out == "blocked":
                self.assertEqual(v.block, "upstream")
            if v.base == "stack":
                self.assertTrue(local and local["finished"] and out in (None, "done", "closed"))


class Base(unittest.TestCase):
    STACK = D.DepVerdict("stack", pr=pr("OPEN"))

    def test_base_for(self):
        for v in (None, D.DepVerdict("default")):
            b = D.base_for(v, "develop", 101, None)
            self.assertEqual((b.branch, b.stacked_on, b.draft), ("develop", None, False))
        for reason, draft in (("config", False), ("squash-sync", True), ("human-override", True)):
            b = D.base_for(self.STACK, "main", 101, reason)
            self.assertEqual((b.branch, b.stacked_on, b.draft), ("gld/101", 101, draft))
        for reason in ("merge-commit-forbidden", None):                                        # TS5
            self.assertEqual(D.base_for(self.STACK, "main", 101, reason), "dep-unmerged")
        self.assertEqual(D.base_for(D.DepVerdict("blocked", block="upstream"), "main", 101, "config"), "upstream")

    def test_effective_stack_reason(self):
        merge, squash = {"merge": True, "squash": True, "rebase": False}, {"merge": False, "squash": True, "rebase": False}
        for token, settings, want in (
                ("config", merge, "config"), (None, merge, "config"), ("squash-sync", merge, "config"),
                ("squash-sync", squash, "squash-sync"), ("human-override", squash, "human-override"),
                ("config", squash, None), (None, squash, None),
                ("merge-commit-forbidden", merge, "merge-commit-forbidden"),
                ("merge-commit-forbidden", None, "merge-commit-forbidden"),
                ("config", None, None), ("squash-sync", None, None)):
            self.assertEqual(D.effective_stack_reason(token, settings), want, (token, settings))


class Window(unittest.TestCase):
    """TW1, TW2."""

    def test_format(self):
        for text, want in (("22:00-10:00", "22:00-10:00"), ("22:00~10:00", "22:00-10:00"), ("08:09-09:08", "08:09-09:08"),
                           ("00:00-23:59", "00:00-23:59"), ("none", None)):
            self.assertEqual(D.parse_window(text), want)
        for text in ("9:00-10:00", "24:00-10:00", "22:60-10:00", "22:00-22:00", "22:00", "", None, "22:00-10:00 ", "NONE",
                     "22:00-10:00\n", "22:00--10:00", "２２:00-10:00"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                D.parse_window(text)

    def test_inside(self):
        for window, inside, outside in (("22:00-10:00", ("22:00", "23:59", "00:00", "08:08", "09:59"), ("10:00", "21:59", "12:00")),
                                        ("08:00-09:30", ("08:00", "08:59", "09:29"), ("07:59", "09:30", "00:00"))):
            for t in inside:
                self.assertTrue(D.in_window(window, t), (window, t))
            for t in outside:
                self.assertFalse(D.in_window(window, t), (window, t))
        self.assertTrue(D.in_window(None, "03:00"))


if __name__ == "__main__":
    unittest.main()
