"""K4 review r2 regressions (design/guild/23-engine/review-k4-r2.md): M1 child-creation dedup never by the
(eventually consistent) search index · M2 three-valued author trust — unknown pauses, never a side · M3 close
only from the structured close form of a member Goal plan line · decision 1 clarified (partial OR unclear ∧
stakes ≥ medium) · lefthook-local overlay closed (PROTECTED, denyWrite, integrity, pre-role refusal) and
LEFTHOOK=0 without a base · one lefthook name list · minors m3 m4 m6 m8."""

import json
import os
import types
import unittest
from unittest import mock

import _util  # noqa: F401
from _k1 import git, repo, tmpdir
from _k4 import (ANALYZE_OUT, CFG, K4, comment, evidence, kickoff, out_role, stakes, techlead_ok,
                 tester_ok)
from test_k4_design import SPLIT, design_h, split_dec
from test_k4_fsm import decision, driver
from test_k4_r1 import _Judges, _Runner, _main_with_origin

from guildcore.adapters.gh import FakeGh, FakeGhWrite, GhError
from guildcore.records.write import GhWriter
from guildcore.roles import runner as RR
from guildcore.roles import scope as SC
from guildcore.roles import settings as S
from workflows.dev import analysis as AN
from workflows.dev import local_checks as LC
from workflows.dev import ports as PO
from workflows.dev import roleout as RO
from workflows.dev.stages import analyze as A
from workflows.dev.stages import children as CH
from workflows.dev.stages import design as D
from workflows.dev.stages.base import StageResult


def _raise(exc):
    def fn(*a, **k):
        raise exc
    return fn


def stale_search(gh):
    """An eventually consistent search index: it only ever knows the Issues that existed when it was
    built (GitHub's search lags seconds to minutes behind a create)."""
    known = set(gh.fx.get("issues", {}))
    orig = gh.issue_search

    def search(text, limit=50):
        return [r for r in orig(text, limit) if str(r["number"]) in known]
    gh.issue_search = search
    return gh


def kids_of(h, parent=7):
    return sorted(int(k) for k, it in h.gh.fx["issues"].items()
                  if int(k) != parent and "Parent Issue: #%d" % parent in (it.get("body") or ""))


# ---- M1 — dedup of a lost-reply create never relies on the search index ------------------------------------

class M1(unittest.TestCase):
    def test_lost_reply_with_a_stale_search_index_creates_no_duplicate(self):
        # the review's probe: 2nd POST lands, answers 502; the search index lags → used to give #8 #9 #10
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        stale_search(h.gh)
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
        self.assertEqual(kids_of(h), [8, 9])
        self.assertEqual(n["n"], 2)                                  # never re-sent
        self.assertNotIn("issue_search", [c[0] for c in h.gh.calls])

    def test_failure_before_landing_is_retried_once_from_the_listing(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        stale_search(h.gh)
        orig = h.w.create_issue
        n = {"n": 0}

        def fails_then_lands(title, body, labels=()):
            n["n"] += 1
            if n["n"] == 2:
                raise GhError("HTTP 502: Bad Gateway")                # nothing created
            return orig(title, body, labels)
        h.w.create_issue = fails_then_lands
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)
        self.assertEqual(kids_of(h), [8, 9])

    def test_writer_create_dedups_by_label_listing(self):
        gh = stale_search(FakeGh({"repo": "o/r", "issues": {"7": {"number": 7, "body": "", "labels": []}}}))
        clock = __import__("_k1").Clock()
        fw = FakeGhWrite(gh, clock)
        w = GhWriter(gh, fw, sleep=lambda s: None)
        orig = fw.create_issue

        def lands_then_fails(title, body, labels=()):
            orig(title, body, labels)
            raise GhError("HTTP 504: Gateway Timeout")
        fw.create_issue = lands_then_fails
        num, created = w.issue_create("t", "b\n\nParent Issue: #7", labels=["guild:child"], key="7-a")
        self.assertEqual((num, created), (8, False))
        self.assertEqual(sorted(gh.fx["issues"]), ["7", "8"])
        fw.create_issue = orig
        self.assertEqual(w.issue_create("t", "b", labels=["guild:child"], key="7-a"), (8, False))
        n2, _c = w.issue_create("t", "b", labels=(), key="7-b")    # unlabelled: the whole listing, still not search
        self.assertEqual(w.issue_create("t", "b", labels=(), key="7-b"), (n2, False))

    def test_restart_verify_intent_uses_the_listing(self):
        gh = stale_search(FakeGh({"repo": "o/r", "issues": {}}))
        clock = __import__("_k1").Clock()
        w = GhWriter(gh, FakeGhWrite(gh, clock), sleep=lambda s: None)
        w.issue_create("t", "b", labels=["guild:child"], key="7-a")
        tag = "<!-- guild:slice-key 7-a -->"
        self.assertTrue(w.verify_intent({"op": "issue:create", "key_tag": tag, "find_label": "guild:child"}))
        self.assertFalse(w.verify_intent({"op": "issue:create", "key_tag": "<!-- guild:slice-key 7-zz -->",
                                          "find_label": "guild:child"}))
        self.assertNotIn("issue_search", [c[0] for c in gh.calls])

    def test_two_live_children_with_one_key_go_to_a_person(self):
        body = "x\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-data -->\n"
        kid = {"title": "[Guild子] data", "state": "OPEN", "body": body, "author_association": "OWNER",
               "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}], "comments": []}
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        self.assertEqual(D.run(h.p).kind, StageResult.SPLIT)   # records the plan, creates #8 #9
        h.gh.fx["issues"]["10"] = dict(kid, number=10)            # a duplicate of 7-data appears
        r = D.make_children(h.p, None, _rec(h), json.loads(RO.get(h.p, D.PLAN_FILE)), [], {}, True)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("duplicate child Issues for one slice key: 7-data → #8, #10", r.line)


def _rec(h):
    from guildcore.records import outputs as OUT
    so = OUT.find(h.gh.comments(7), "analyze:output")
    return AN.parse_output(so.body)


# ---- M2 — author trust is three-valued; unknown pauses --------------------------------------------------

NET = "Body\n## Safety net\n<!-- guild:safety-net -->\n- lib/app/home.dart · Home.count · returns 3 · #12\n"


class M2(unittest.TestCase):
    def test_safety_net_issue_with_a_5xx_association_read_pauses(self):
        # the review's probe: a member body with a safety net + association 502 used to ADVANCE without it
        h = K4(self, body=NET, roles=[evidence(self)], judges={"KICKOFF": kickoff()})
        h.gh.issue_author_association = _raise(GhError("HTTP 502: Bad Gateway"))
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("env: service", h.body_with("needs-human"))
        self.assertNotIn("guild:design", h.labels())
        self.assertEqual(h.calls["roles"], [])                    # stopped before any model call
        self.assertFalse(h.decisions_of("ignored-body-block"))

    def test_member_harness_issue_with_unknown_trust_does_not_drop_the_ac(self):
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(ac=("edit .claude/settings.json",))})
        h.gh.issue_author_association = lambda n: ""
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("defect: engine FAIL — issue author association unreadable", h.body_with("needs-human"))
        self.assertFalse(h.decisions_of("harness-untrusted"))

    def test_attended_unknown_trust_is_a_fail(self):
        h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff()})
        h.gh.issue_author_association = _raise(GhError("HTTP 503"))
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.FAIL)
        self.assertIn("association unreadable", r.line)

    def test_rate_limit_still_ends_with_75(self):
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff()})
        h.gh.issue_author_association = _raise(GhError("HTTP 429: API rate limit exceeded"))
        self.assertEqual(driver(h).run(7).exit_code, 75)

    def test_design_and_children_pause_on_unknown_trust(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self)])
        h.gh.issue_author_association = _raise(GhError("HTTP 500"))
        self.assertEqual(D.run(h.p).kind, StageResult.PAUSE)
        self.assertEqual(h.calls["roles"], [])
        kid = {"number": 8, "title": "k", "body": "s\n\nParent Issue: #7\n", "state": "OPEN",
               "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}], "comments": []}
        h2 = K4(self, labels=("guild:children",), issues={"8": kid})
        h2.gh.issue_author_association = _raise(GhError("HTTP 500"))
        self.assertEqual(CH.run(h2.p, lambda c: StageResult(StageResult.DONE)).kind, StageResult.PAUSE)

    def test_a_read_outsider_is_still_an_outsider(self):
        h = K4(self, author="NONE")
        self.assertEqual(A.author_trust(h.p, h.gh.issue(7))[0], "outsider")
        self.assertEqual(A.author_trust(K4(self).p, K4(self).gh.issue(7))[0], "member")


# ---- M3 — close only from the structured close form ---------------------------------------------------

FALSE_POSITIVES = (
    "- Constraint: 오프라인 동작? → 오프라인에서는 동기화하지 않음 (2026-10-28, sprint plan)",
    "- Goal: 팝업 범위? → 기존 닫기 버튼 재사용 (2026-10-28, sprint plan)",
    "- Success: 완료 기준? → 학습 completed 상태에서 배지 표시 (2026-10-28, sprint plan)",
    "- Goal: 취소 흐름? → 취소 버튼 추가 (2026-10-28, sprint plan)",
)


def _plan(*lines):
    return "x\n<!-- guild:plan-decision -->\n%s\n<!-- /guild:plan-decision -->\n" % "\n".join(lines)


class M3(unittest.TestCase):
    def test_the_reviews_four_requirement_lines_never_close(self):
        for line in FALSE_POSITIVES:
            for decide in ("completed", "not_planned"):
                pl = AN.plan_decisions(_plan(line))
                self.assertIsNone(AN.close_plan_line(line, pl, decide), (line, decide))
                h = K4(self, body=_plan(line), roles=[evidence(self)], judges={"KICKOFF": kickoff(
                    close={"decide": decide, "source": "plan_line", "line": line})})
                r = A.run(h.p)
                self.assertEqual(r.kind, StageResult.PAUSE, (line, decide))
                self.assertEqual(h.issue()["state"], "OPEN")
                self.assertIn("ambiguity: 작업 불필요 판단", h.body_with("needs-human"))

    def test_structured_close_form(self):
        self.assertEqual(AN.close_form("close: completed — #12 에서 이미 됨 (2026-10-28, sprint plan)"), "completed")
        self.assertEqual(AN.close_form("close: not planned (현행 유지)"), "not_planned")
        self.assertEqual(AN.close_form("close: not_planned"), "not_planned")
        self.assertEqual(AN.close_form("닫음: 이미 충족 — #12"), "completed")
        for a in ("closed: completed", "close: completedly", "the dialog close: completed", "현행 유지, 닫는다",
                  "close the popup", "취소 — not planned"):
            self.assertIsNone(AN.close_form(a), a)

    def test_close_form_on_a_non_goal_line_does_not_close(self):
        line = "- Success: 이미? → close: completed — #12 (2026-10-28, sprint plan)"
        self.assertIsNone(AN.close_plan_line(line, AN.plan_decisions(_plan(line)), "completed"))

    def test_member_goal_close_form_closes(self):
        line = "- Goal: 할까요? → close: completed — #12 에서 이미 됨 (2026-10-28, sprint plan)"
        h = K4(self, body=_plan(line), roles=[evidence(self)], judges={"KICKOFF": kickoff(
            close={"decide": "completed", "source": "plan_line", "line": line})})
        self.assertEqual(A.run(h.p).kind, StageResult.DONE)
        self.assertEqual(h.issue()["stateReason"], "COMPLETED")


# ---- decision 1 (clarified in r2) -----------------------------------------------------------------------

class Decision1(unittest.TestCase):
    def test_unclear_with_medium_stakes_forces_the_product_owner(self):
        po = out_role(self, "DONE", files={"po.json": {"ac_patch": []}}, po_path="out/po.json")
        h = K4(self, roles=[evidence(self), po], extra_files={".claude/agents/product-owner.md": "# PO\n"},
               judges={"KICKOFF": kickoff(goal="unclear"), "STAKES": stakes("medium")})
        A.run(h.p)
        self.assertIn("product-owner", [c.role for c in h.calls["roles"]])

    def test_unclear_with_low_stakes_does_not(self):
        h = K4(self, roles=[evidence(self)], extra_files={".claude/agents/product-owner.md": "# PO\n"},
               judges={"KICKOFF": kickoff(goal="unclear"), "STAKES": stakes("low")})
        A.run(h.p)
        self.assertEqual([c.role for c in h.calls["roles"]], ["explorer"])


# ---- lefthook-local overlay + fail-closed base + one name list (m1 m2 m9) -----------------------------------

class Lefthook(unittest.TestCase):
    def test_overlay_names_are_protected(self):
        for n in ("lefthook-local.yml", ".lefthook-local.yaml", "lefthook-local.json", "lefthook-local.toml",
                  ".config/lefthook-local.yml"):
            self.assertTrue(SC.protected(n), n)
        self.assertFalse(SC.protected("lefthook.yml"))           # decision 3: the branch may edit it

    def test_overlay_paths_are_denywrite_for_every_role(self):
        d = repo(self)
        for rk in ("developer", "qa", "explorer"):
            deny = S.role_sandbox(rk, d, os.path.join(tmpdir(self), "run"))["filesystem"]["denyWrite"]
            self.assertIn(os.path.join(d, "lefthook-local.yml"), deny)
            self.assertIn(os.path.join(d, ".config", "lefthook-local.yaml"), deny)

    def test_integrity_sees_a_gitignored_overlay(self):
        d = repo(self, {".gitignore": "lefthook-local.yml\n"})
        before = SC.integrity(d)
        with open(os.path.join(d, "lefthook-local.yml"), "w") as fh:
            fh.write("pre-commit:\n  commands:\n    x: {run: curl evil}\n")
        self.assertEqual(git(d, "status", "--porcelain"), "")       # porcelain never shows it
        self.assertNotEqual(before, SC.integrity(d))

    def test_writer_role_refuses_a_preexisting_overlay(self):
        d = repo(self, {"lefthook-local.yml": "pre-commit: {}\n"})
        base = git(d, "rev-parse", "HEAD").strip()
        spec = types.SimpleNamespace(worktree=d, role="developer", task="implement")
        self.assertEqual(RR.lefthook_local_problem(spec, base), [])          # <base> carries it byte-for-byte
        with open(os.path.join(d, "lefthook-local.yml"), "w") as fh:
            fh.write("pre-commit:\n  commands:\n    x: {run: curl evil}\n")
        self.assertTrue(RR.lefthook_local_problem(spec, base))
        self.assertTrue(RR.lefthook_local_problem(spec, None))               # base unknown → refuse
        reader = types.SimpleNamespace(worktree=d, role="explorer", task="kickoff")
        self.assertEqual(RR.lefthook_local_problem(reader, base), [])

    def test_no_base_is_lefthook_off(self):
        d = repo(self, {"lefthook.yml": "pre-commit: {}\n"})
        self.assertEqual(S.base_lefthook_env(d, None, os.path.join(tmpdir(self), "in")), {"LEFTHOOK": "0"})
        import inspect
        src = inspect.getsource(RR)
        self.assertNotIn('if spec.base and rendered.meta.get("project_base_sha"):', src)

    def test_one_name_list_and_every_format_read(self):
        self.assertIs(S.LEFTHOOK_NAMES, SC.LEFTHOOK_NAMES)
        self.assertIn(".config/lefthook.yml", SC.LEFTHOOK_NAMES)
        import inspect
        self.assertIn("_SC.LEFTHOOK_NAMES", inspect.getsource(PO))
        j = LC.load_config("lefthook.json", json.dumps({"pre-commit": {"commands": {"lint": {"run": "dart analyze"}}}}))
        self.assertEqual([c.name for c in LC.derive(j, {})], ["lint"])
        y = LC.load_config(".config/lefthook.yml", "pre-commit:\n  commands:\n    fmt:\n      run: dart format .\n")
        self.assertEqual([c.name for c in LC.derive(y, {})], ["fmt"])
        self.assertIsNone(LC.load_config("lefthook.json", "{not json"))


# ---- minors ------------------------------------------------------------------------------------------------

class Minors(unittest.TestCase):
    def _factory(self, main, cfg, gh, push_url=None):
        clock = __import__("_k1").Clock()
        return PO.fsm_factory(main, cfg, clock, gh, FakeGhWrite(gh, clock), _Runner(), _Judges(), push_url=push_url,
                              env={})

    def _gh(self, labels=("guild:qa",), comments=()):
        from _k2 import fixture
        return FakeGh(fixture(labels=labels, comments=comments))

    def test_m3_fallback_branch_on_main_or_without_a_pr_never_pushes(self):
        main, cfg = _main_with_origin(self)
        wt = os.path.join(tmpdir(self), "wt")
        git(main, "worktree", "add", "-q", "-b", "feat/7-legacy", wt)
        with mock.patch("workflows.dev.branching.worktree_path", lambda m, n: wt):
            p = self._factory(main, cfg, self._gh())(7, "qa")
        self.assertIsNone(p.branch)                                     # no open PR of #7 has that head
        self.assertIn("not the head of an open PR of #7", p.unavailable)
        gh = self._gh()
        gh.fx.setdefault("prs", []).append({"number": 90, "state": "OPEN", "headRefName": "feat/7-legacy",
                                            "body": "Closes #7"})
        p.unavailable = None
        PO.fill_handoff(p, wt, "origin/feat/7-legacy", "main")          # the worktree sits on the base branch
        self.assertIsNone(p.branch)
        self.assertIn("on the base branch feat/7-legacy", p.unavailable)
        git(wt, "switch", "-q", "--detach")
        p.unavailable = None
        PO.fill_handoff(p, wt, "origin/main", "main")
        self.assertIsNone(p.branch)
        self.assertIn("detached HEAD", p.unavailable)

    def test_m4_superseded_split_block_is_not_current(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        h.w.create_issue = _raise(GhError("HTTP 422: Validation Failed"))
        self.assertEqual(D.run(h.p).kind, StageResult.PAUSE)          # SPLIT recorded, no child
        blk = D.split_block(h.gh.comments(7))
        self.assertIsNotNone(blk)
        h.decisions.resolve(blk.id, {"point": "rollback", "by": "code", "status": "superseded", "reason": "re-split"})
        self.assertIsNone(D.split_block(h.gh.comments(7)))

    def test_m4_resume_after_the_ac_changed_goes_to_a_person(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        orig = h.w.create_issue
        n = {"n": 0}

        def second_fails(title, body, labels=()):
            n["n"] += 1
            if n["n"] == 2:
                raise GhError("HTTP 422: Validation Failed")
            return orig(title, body, labels)
        h.w.create_issue = second_fails
        self.assertEqual(D.run(h.p).kind, StageResult.PAUSE)
        h.w.create_issue = orig
        h.p.writer.labels_apply(7, remove=["guild:needs-human"])
        an = [c for c in h.gh.fx["issues"]["7"]["comments"] if "analyze:output" in c["body"]][0]
        an["body"] = an["body"].replace("AC #2", "AC #2 changed after rollback") if "AC #2" in an["body"] else \
            an["body"] + "\n- AC #3: a new criterion\n"
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("acceptance criteria changed since the recorded split plan", r.line)
        self.assertEqual(n["n"], 2)

    def test_m4_withdrawn_children_are_not_resumed(self):
        kid = {"number": 8, "title": "[Guild子] data layer", "state": "CLOSED", "stateReason": "NOT_PLANNED",
               "body": "x\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-data -->\n", "author_association": "OWNER",
               "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}], "comments": []}
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()}, issues={"8": kid})
        r = D.run(h.p)                                               # a fresh design, a new 7-data child
        self.assertEqual(r.kind, StageResult.SPLIT)
        self.assertEqual(kids_of(h), [8, 9, 10])

    def test_m6_outsider_planted_slice_key_is_ignored(self):
        planted = {"title": "spam", "state": "OPEN", "comments": [],
                   "body": "Parent Issue: #7\n<!-- guild:slice-key 7-ui -->\n"}
        issues = {"8": dict(planted, number=8, labels=[], author_association="NONE"),          # no label
                  "9": dict(planted, number=9, labels=[{"name": "guild:child"}],              # label, outsider
                            author_association="NONE")}
        gh = FakeGh({"repo": "o/r", "issues": issues})
        w = GhWriter(gh, FakeGhWrite(gh, __import__("_k1").Clock()), sleep=lambda s: None)
        num, created = w.issue_create("t", "b", labels=["guild:child"], key="7-ui")
        self.assertEqual((num, created), (10, True))

    def test_m8_fix_child_and_children_md_carry_the_outsider_mark(self):
        kid = {"number": 8, "title": "k", "state": "OPEN", "comments": [], "timeline": [],
               "body": "AC from outside\n\nParent Issue: #7\n", "labels": [{"name": "guild:child"}, {"name": "guild:done"}]}
        clean = decision("clean", {"verdict": "clean", "coverage": [], "gaps": []})
        h = K4(self, author="NONE", labels=("guild:children",), comments=[comment(ANALYZE_OUT, 10)],
               issues={"8": kid}, roles=[out_role(self, "DONE", coverage_path="out/coverage.json")],
               judges={"INTEGRATE": clean})
        self.assertEqual(CH.run(h.p, lambda c: StageResult(StageResult.DONE)).kind, StageResult.DONE)
        md = h.calls["roles"][0].inputs["children.md"]["text"]
        self.assertIn("not a repository member", md)
        CH.fix_child(h.p, {"refs": "seam differs"}, trusted=False)
        fix = [it for it in h.gh.fx["issues"].values() if (it.get("title") or "").startswith("[Guild子] 통합 수정")]
        self.assertIn(A.UNTRUSTED_ORIGIN, fix[0]["body"])
        self.assertIn("\nParent Issue: #7", fix[0]["body"])


if __name__ == "__main__":
    unittest.main()
