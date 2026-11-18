"""K4 review r3 regressions (design/guild/23-engine/review-k4-r3.md): B1 child dedup and discovery never read a
search-backed listing (`gh issue list --label` is IssueSearch) — journal first, the create token through the
REST issues list, every child read by number; an unknown create pauses and is never re-sent · m1 2b leaves
withdrawn and foreign children out · m2 execute's safety-net marker only from a member body (three-valued) ·
m3 the REST list is paginated · m4 a role that never started is not blamed · m5 the engine's own children are
known by the journal, not author association · m6 plan blocks inside code fences / quotes are not read."""

import os
import unittest

import _util  # noqa: F401
from _k1 import git
from _k2 import FLUTTER_GREEN, suite
from _k3 import XHarness, dev, role, wt_repo
from _k4 import ANALYZE_OUT, K4, comment, out_role, techlead_ok, tester_ok
from test_k4_design import SPLIT, design_h, split_dec
from test_k4_fsm import decision

from guildcore.adapters.gh import FakeGh, FakeGhWrite, GhCli, GhError, assert_read_only
from guildcore.journal import Journal
from guildcore.records.write import GhWriter
from guildcore.roles.runner import RoleResult
from guildcore.state import discover_children
from workflows.dev import analysis as AN
from workflows.dev.stages import base as B
from workflows.dev.stages import children as CH
from workflows.dev.stages import design as D
from workflows.dev.stages import execute as X
from workflows.dev.stages.base import StageResult

SEARCH_BACKED = ("issue_search",)


def search_reads(gh):
    """Every search-backed read: issue_search, and issue_list WITH a label (real gh: IssueSearch)."""
    return [c for c in gh.calls if c[0] in SEARCH_BACKED or (c[0] == "issue_list" and c[2])]


def stale(h, lag=10 ** 6):
    """The search index never (or only after `lag` search reads) sees an Issue created in the test."""
    h.gh.index_lag = lag
    return h


def kids_of(h, parent=7):
    return sorted(int(k) for k, it in h.gh.fx["issues"].items()
                  if int(k) != parent and "Parent Issue: #%d" % parent in (it.get("body") or ""))


def split_h(case, **kw):
    return design_h(case, cast="", ui="false", roles=[tester_ok(case, (1, 2)), techlead_ok(case, SPLIT)],
                    judges={"SPLIT": split_dec()}, **kw)


class Crash(Exception):
    """The engine process dies (not a gh error — nothing in the writer catches it)."""


def posts(h):
    return [c for c in h.w.calls if c[0] == "create_issue"]


def reload_journal(h):
    h.journal = Journal(h.common, 7, h.clock)
    h.writer.journal = h.journal


# ---- B1 — no search-backed read decides anything ------------------------------------------------------------

class B1(unittest.TestCase):
    def test_normal_split_with_a_stale_index_does_not_pause(self):
        # the review's probe NORMAL: used to PAUSE "created children not listed yet" on every split
        h = stale(split_h(self))
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.SPLIT)
        self.assertEqual(kids_of(h), [8, 9])
        self.assertIn("guild:children", h.labels())
        self.assertNotIn("guild:needs-human", h.labels())
        self.assertEqual(search_reads(h.gh), [])

    def test_lost_reply_with_a_stale_index_is_exactly_two_children(self):
        # the review's probe LOST-REPLY: 2nd POST lands then 502 → used to give #8 #9 #10
        h = stale(split_h(self))
        orig = h.w.create_issue
        n = {"n": 0}

        def lands_then_fails(title, body, labels=()):
            n["n"] += 1
            r = orig(title, body, labels)
            if n["n"] == 2:
                raise GhError("HTTP 502: Bad Gateway")
            return r
        h.w.create_issue = lands_then_fails
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.SPLIT)
        self.assertEqual((kids_of(h), n["n"]), ([8, 9], 2))
        self.assertEqual(search_reads(h.gh), [])
        rec = [e for e in h.journal.own_issues()]
        self.assertEqual(sorted((e["key"], e["number"]) for e in rec), [("7-data", 8), ("7-ui", 9)])
        self.assertTrue([e for e in rec if e["number"] == 9][0]["recovered"])

    def test_partial_index_lost_reply_is_still_two(self):
        # partial lag: #8 indexed by the end, #9 not — the r3 case where the old end check passed
        h = stale(split_h(self), lag=1)
        orig = h.w.create_issue

        def lands_then_fails(title, body, labels=()):
            r = orig(title, body, labels)
            if r["number"] == 9:
                raise GhError("HTTP 502: Bad Gateway")
            return r
        h.w.create_issue = lands_then_fails
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        self.assertEqual(kids_of(h), [8, 9])
        self.assertEqual(len(posts(h)), 2)

    def test_crash_between_post_and_record_is_found_by_token_on_restart(self):
        h = stale(split_h(self))
        orig = h.w.create_issue
        n = {"n": 0}

        def lands_then_dies(title, body, labels=()):
            n["n"] += 1
            r = orig(title, body, labels)
            if n["n"] == 2:
                raise Crash()
            return r
        h.w.create_issue = lands_then_dies
        with self.assertRaises(Crash):
            D.run(h.p)
        h.w.create_issue = orig
        reload_journal(h)                                           # the supervisor restarts the engine
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.SPLIT)
        self.assertEqual((kids_of(h), len(posts(h))), ([8, 9], 2))
        self.assertEqual(search_reads(h.gh), [])

    def test_unknown_create_pauses_with_bounded_backoff_and_never_resends(self):
        h = stale(split_h(self))
        orig = h.w.create_issue
        n = {"n": 0}

        def lands_then_dies(title, body, labels=()):
            n["n"] += 1
            r = orig(title, body, labels)
            if n["n"] == 2:
                raise Crash()
            return r
        h.w.create_issue = lands_then_dies
        with self.assertRaises(Crash):
            D.run(h.p)
        h.w.create_issue = orig
        reload_journal(h)
        rows = h.gh.issue_rows
        h.gh.issue_rows = lambda **k: [r for r in rows(**k) if r["number"] != 9]   # the list lags too
        sleeps = []
        h.writer.sleep = sleeps.append
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("may have landed", r.line)
        self.assertEqual(len(posts(h)), 2)                          # never a third POST
        self.assertEqual(sleeps, [2, 4, 8])                         # 4 list reads, backoff between
        h.gh.issue_rows = rows
        h.p.writer.labels_apply(7, remove=["guild:needs-human"])
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        self.assertEqual((kids_of(h), len(posts(h))), ([8, 9], 2))

    def test_refused_create_closes_its_intent(self):
        gh = FakeGh({"repo": "o/r", "issues": {}})
        fw = FakeGhWrite(gh)
        w = GhWriter(gh, fw, sleep=lambda s: None)
        fw.fail_next("terminal")
        with self.assertRaises(Exception):
            w.issue_create("t", "b", labels=["guild:child"], key="7-a")
        self.assertEqual(w._ij().intent_only(), [])                 # 422: nothing landed, nothing unknown
        self.assertEqual(w.issue_create("t", "b", labels=["guild:child"], key="7-a"), (1, True))

    def test_journal_number_wins_over_any_listing(self):
        gh = FakeGh({"repo": "o/r", "issues": {}})
        w = GhWriter(gh, FakeGhWrite(gh), sleep=lambda s: None)
        self.assertEqual(w.issue_create("t", "b", labels=["guild:child"], key="7-a"), (1, True))
        gh.issue_rows = lambda **k: []                              # even an empty list cannot cause a re-create
        self.assertEqual(w.issue_create("t", "b", labels=["guild:child"], key="7-a"), (1, False))
        gh.fx["issues"]["1"].update(state="CLOSED", stateReason="NOT_PLANNED")      # a re-split withdraws it
        self.assertEqual(w.issue_create("t", "b", labels=["guild:child"], key="7-a"), (2, True))

    def test_2b_duplicate_slice_key_goes_to_a_person(self):
        body = "x\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-data -->\n"
        kid = {"title": "k", "state": "OPEN", "body": body, "comments": [],
               "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}]}
        h = K4(self, labels=("guild:children",), issues={"8": dict(kid, number=8), "9": dict(kid, number=9)})
        driven = []
        r = CH.run(h.p, lambda c: driven.append(c) or StageResult(StageResult.DONE))
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("duplicate child Issues for one slice key: 7-data → #8, #9", r.line)
        self.assertEqual(driven, [])

    def test_the_fake_models_gh_label_listing_as_search(self):
        gh = FakeGh({"repo": "o/r", "issues": {}})
        gh.index_lag = 2
        FakeGhWrite(gh).create_issue("t", "b", ["guild:child"])
        self.assertEqual(gh.issue_list(state="all", label="guild:child"), [])
        self.assertEqual(gh.issue_search("b"), [])
        self.assertEqual([r["number"] for r in gh.issue_list(state="all", label="guild:child")], [1])
        self.assertEqual([r["number"] for r in gh.issue_rows(label="guild:child")], [1])   # REST: always


# ---- m3 — the REST list, all pages --------------------------------------------------------------------------

class M3(unittest.TestCase):
    def test_gh_reads_are_the_rest_list_and_row(self):
        seen = []

        def runner(argv):
            seen.append(argv)
            if "--paginate" in argv:
                return ('{"number":3,"title":"t","body":"b","state":"OPEN","stateReason":"","labels":["guild:child"],'
                        '"pr":false}\n{"number":4,"title":"p","body":"","state":"OPEN","stateReason":"","labels":[],'
                        '"pr":true}\n')
            return '{"number":3,"title":"t","body":"b","state":"OPEN","stateReason":"","labels":[],"pr":false}'
        gh = GhCli("o/r", runner=runner)
        self.assertEqual([r["number"] for r in gh.issue_rows(label="guild:child", since="2026-11-16T00:00:00Z")], [3])
        self.assertEqual(gh.issue_row(3)["number"], 3)
        a, b = seen
        self.assertEqual(a[:4], ["gh", "api", "--paginate", "repos/o/r/issues?state=all&sort=created&direction=desc"
                                 "&per_page=100&labels=guild%3Achild&since=2026-11-16T00%3A00%3A00Z"])
        self.assertEqual(b[:3], ["gh", "api", "repos/o/r/issues/3"])
        for argv in seen:
            assert_read_only(argv)
            self.assertNotIn("--label", argv)
            self.assertNotIn("--search", argv)

    def test_discovery_is_not_capped_at_200(self):
        issues = dict((str(k), {"number": k, "title": "c", "state": "OPEN", "body": "Parent Issue: #%d\n" % (
            7 if k in (3, 255) else 1000), "labels": [{"name": "guild:child"}]}) for k in range(1, 260))
        gh = FakeGh({"repo": "o/r", "issues": issues})
        self.assertEqual([r["number"] for r in discover_children(gh, 7)], [3, 255])   # 259 rows, no 200 cap

    def test_engine_children_of_an_old_parent_behind_many_others(self):
        body = "x\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-data -->\n"
        many = dict((str(k), {"number": k, "title": "o", "state": "OPEN", "body": "Parent Issue: #1\n",
                              "labels": [{"name": "guild:child"}]}) for k in range(20, 260))
        many["8"] = {"number": 8, "title": "k", "state": "OPEN", "body": body, "comments": [],
                     "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}]}
        h = K4(self, labels=("guild:children",), issues=many)
        self.assertEqual([r["number"] for r in B.own_children(h.p)], [8])


# ---- m1 / m5 — 2b drives only this engine's live children ---------------------------------------------------

class M1M5(unittest.TestCase):
    def test_resplit_reaches_2b_without_the_withdrawn_child(self):
        # the review's probe: old #8 closed as not planned → design makes #9 #10 → 2b drives #9 #10 only
        kid = {"number": 8, "title": "[Guild子] data layer", "state": "CLOSED", "stateReason": "NOT_PLANNED",
               "body": "x\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-data -->\n", "author_association": "OWNER",
               "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}], "comments": []}
        h = split_h(self, issues={"8": kid})
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        driven = []
        CH.run(h.p, lambda c: driven.append(c) or StageResult(StageResult.PAUSE, cause="x"))
        self.assertEqual(driven, [9])                               # the first live child; #8 never

    def test_2b_ignores_a_foreign_child_issue(self):
        outsider = {"number": 8, "title": "[Guild子] mine", "state": "OPEN", "author_association": "NONE",
                    "body": "do this\n\nParent Issue: #7\n", "comments": [],
                    "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}]}
        own = dict(outsider, number=9, author_association="OWNER", title="[Guild子] data",
                   body="x\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-data -->\n")
        h = K4(self, labels=("guild:children",), issues={"8": outsider, "9": own}, foreign=(8,))
        driven = []
        CH.run(h.p, lambda c: driven.append(c) or StageResult(StageResult.PAUSE, cause="x"))
        self.assertEqual(driven, [9])

    def test_own_children_never_read_author_association(self):
        h = split_h(self)
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        for k in ("8", "9"):
            h.gh.fx["issues"][k]["author_association"] = "NONE"      # a bot token / private membership
        h.gh.calls[:] = []
        self.assertEqual([r["number"] for r in B.own_children(h.p)], [8, 9])
        self.assertEqual([c for c in h.gh.calls if c[0] == "issue_author_association"], [])


# ---- m2 — execute's net marker is a member's control ------------------------------------------------------

class M2(unittest.TestCase):
    def _h(self, author):
        root = wt_repo(self, branch="refactor/#7-x", change={"test/a_net_test.dart": "test('a', () {});\n"})
        sha = git(root, "rev-parse", "HEAD")
        with open(os.path.join(root, "lib", "a.dart"), "w") as fh:
            fh.write("int a() => 1; // reshaped\n")
        git(root, "commit", "-qam", "transform")
        h = XHarness(self, root=root, body="<!-- guild:safety-net -->", suites=[suite(FLUTTER_GREEN)] * 3,
                     roles=[dev(safety_net=sha, net=["test/a_net_test.dart"], net_run=["test/a_net_test.dart +1"]),
                            role("DONE"), role("DONE", None, findings=[])], author=author)
        h.p.branch = "refactor/#7-x"
        h.runs = []
        h.p.net_run = lambda rev, files: h.runs.append(rev) or suite(FLUTTER_GREEN)
        return h

    def test_outsider_marker_is_ignored(self):
        h = self._h("NONE")
        X.run(h.p, "refactor")
        self.assertEqual(h.runs, [])                                # no net procedure for an outsider's marker
        self.assertNotIn("<!-- guild:safety-net-evidence -->", h.body_with("test-evidence:step-1") or "")

    def test_member_marker_still_runs_the_net(self):
        h = self._h("OWNER")
        self.assertEqual(X.run(h.p, "refactor").kind, "ADVANCE")
        self.assertTrue(h.runs)

    def test_unknown_trust_stops(self):
        h = self._h(None)
        r = X.run(h.p, "refactor")
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("cannot be decided", r.line)
        self.assertEqual(h.runs, [])


# ---- m4 / m6 ------------------------------------------------------------------------------------------------

class Minors(unittest.TestCase):
    def test_m4_a_role_that_never_ran_is_not_blamed(self):
        h = K4(self, labels=("guild:execute",))
        v = ["lefthook overlay lefthook-local.yml present and not <base>'s — the engine leaves it in place"]
        r = B.role_outcome(h.p, "execute", "developer", RoleResult("DRIFT", "x", violations=v, notes=["not run"]))
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("developer not started — the worktree needs a person first", r.line if r.line else r.cause)
        self.assertNotIn("wrote outside its scope", r.cause)
        self.assertTrue(r.cause.startswith("env:"))
        r2 = B.role_outcome(h.p, "execute", "developer", RoleResult("DRIFT", "x", violations=["late change after the "
                            "previous step: lib/a.dart"], notes=["not run"]))
        self.assertNotIn("wrote outside its scope", r2.cause)
        r3 = B.role_outcome(h.p, "execute", "developer", RoleResult("SCOPE", "x", violations=["lib/x"]))
        self.assertIn("developer wrote outside its scope", r3.cause)

    def test_m6_plan_block_in_a_fence_or_quote_is_not_read(self):
        blk = "<!-- guild:plan-decision -->\n- Goal: 범위? → close: not_planned — 예시\n<!-- /guild:plan-decision -->"
        self.assertEqual(len(AN.plan_decisions("x\n" + blk)), 1)
        self.assertEqual(AN.plan_decisions("x\n```md\n" + blk + "\n```\n"), [])
        self.assertEqual(AN.plan_decisions("x\n~~~\n" + blk + "\n~~~\n"), [])
        self.assertEqual(AN.plan_decisions("x\n" + "\n".join("> " + ln for ln in blk.split("\n"))), [])
        self.assertEqual(len(AN.plan_decisions("```\nexample\n```\n" + blk)), 1)   # after a closed fence: read


if __name__ == "__main__":
    unittest.main()
