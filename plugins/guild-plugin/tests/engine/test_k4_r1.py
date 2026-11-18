"""K4 review r1 regressions (design/guild/23-engine/review-k4-r1.md) and the user decisions of 2026-11-18:
B1 the FSM's test/qa ports (late-bound branch, engine push, no main-checkout fallback) · M1 fail-closed author
trust · M2/M3 resumable, idempotent split + failures through B.fail · M4 every FSM end on the §2.4 contract ·
M5 close only from an exact, engine-verified member plan line · minors m1–m8, m10, m11 · decisions: PO
forcing (partial ∧ stakes ≥ medium), outsider text never pauses the harness guard, the role commit's
lefthook config from <base>."""

import json
import os
import unittest
from unittest import mock

import _util  # noqa: F401
from _k1 import git, repo, tmpdir
from _k4 import (ANALYZE_OUT, CFG, K4, comment, evidence, kickoff, stakes, techlead_ok,
                 tester_ok)
from test_k4_design import SPLIT, design_h, split_dec
from test_k4_fsm import driver

from guildcore.adapters.gh import FakeGh, FakeGhWrite, GhError, GhWriteError
from guildcore.decisions import DecisionWriter
from guildcore.records import markers
from guildcore.records.write import GhWriter
from guildcore.roles import permissions as P
from guildcore.roles import settings as S
from workflows.dev import fsm as F
from workflows.dev import ports as PO
from workflows.dev import roleout as RO
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages import children as CH
from workflows.dev.stages import design as D
from workflows.dev.stages.base import StageResult


def _raise(exc):
    def fn(*a, **k):
        raise exc
    return fn


# ---- B1 — test/qa ports of the FSM ------------------------------------------------------------------

class _Runner(object):
    parent_env = {}

    def run_role(self, spec):
        raise AssertionError("no role in this test")

    def rebaseline(self, *a):
        pass

    def drift_check(self, *a):
        return []


class _Judges(object):
    def judge(self, spec):
        raise AssertionError("no judge in this test")


def _main_with_origin(case):
    from guildcore import config as CF
    main = repo(case, {"README.md": "hi\n", ".claude/guild/config.json": json.dumps(dict(CFG, visual={}))})
    git(main, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(main, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return main, CF.load(main)


class B1(unittest.TestCase):
    def _factory(self, main, cfg, gh, push_url=None):
        clock = __import__("_k1").Clock()
        return PO.fsm_factory(main, cfg, clock, gh, FakeGhWrite(gh, clock), _Runner(), _Judges(), push_url=push_url,
                              env={})

    def _gh(self, labels=("guild:qa",), comments=()):
        from _k2 import fixture
        return FakeGh(fixture(labels=labels, comments=comments))

    def test_push_reads_the_branch_filled_after_live(self):
        main = repo(self)
        bare = tmpdir(self)
        git(bare, "init", "-q", "--bare")
        git(main, "switch", "-q", "-c", "feat/7-x")
        gh = self._gh()
        clock = __import__("_k1").Clock()
        w = GhWriter(gh, FakeGhWrite(gh, clock), sleep=lambda s: None)
        p = PO.live(7, main, None, None, CFG, clock, gh, w, DecisionWriter(w, 7, clock), _Runner(), _Judges(),
                    push_url=bare)
        with self.assertRaises(RuntimeError):                  # no branch → never a silent "nothing pushed"
            p.push()
        p.branch = "feat/7-x"                                   # what handoff.fill_from_execute does
        with open(os.path.join(main, "t.txt"), "w") as fh:
            fh.write("qa case\n")
        git(main, "add", "t.txt")
        git(main, "commit", "-qm", "qa")
        sha = p.push()
        self.assertEqual(sha, git(main, "rev-parse", "HEAD").strip())
        self.assertEqual(git(bare, "rev-parse", "refs/heads/feat/7-x").strip(), sha)

    def test_qa_without_an_engine_worktree_is_an_env_pause_not_the_main_checkout(self):
        main, cfg = _main_with_origin(self)
        gh = self._gh()
        wt = os.path.join(tmpdir(self), "absent")
        with mock.patch("workflows.dev.branching.worktree_path", lambda m, n: wt):
            pf = self._factory(main, cfg, gh)
            out = F.Driver(pf, stages={"qa": _raise(AssertionError("qa ran in the main checkout"))}).run(7)
        self.assertEqual(out.exit_code, 0)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        labels = [l["name"] for l in gh.fx["issues"]["7"]["labels"]]
        self.assertIn("guild:needs-human", labels)
        nh = [c["body"] for c in gh.fx["issues"]["7"]["comments"] if c["body"].startswith("<!-- guild:needs-human")]
        self.assertIn("env: other — no engine worktree for #7", nh[-1])

    def test_qa_ports_take_base_and_branch_from_the_handoff_block(self):
        main, cfg = _main_with_origin(self)
        wt = os.path.join(tmpdir(self), "wt")
        git(main, "worktree", "add", "-q", "-b", "feat/7-x", wt)
        gh = self._gh()
        clock = __import__("_k1").Clock()
        w = GhWriter(gh, FakeGhWrite(gh, clock), sleep=lambda s: None)
        DecisionWriter(w, 7, clock).record({"point": "execute-handoff", "stage": "execute", "by": "code",
                                            "impl_files": "lib/a.dart", "base": "origin/main",
                                            "branch": "feat/7-x", "head": "abc", "push": "github.com"})
        with mock.patch("workflows.dev.branching.worktree_path", lambda m, n: wt):
            p = self._factory(main, cfg, gh, push_url="/nowhere")(7, "qa")
        self.assertEqual(os.path.realpath(p.root), os.path.realpath(wt))
        self.assertEqual((p.base, p.branch, p.impl_files), ("origin/main", "feat/7-x", ["lib/a.dart"]))
        self.assertIsNone(getattr(p, "unavailable", None))

    def test_qa_ports_fall_back_to_the_worktree_branch(self):
        main, cfg = _main_with_origin(self)
        wt = os.path.join(tmpdir(self), "wt")
        git(main, "worktree", "add", "-q", "-b", "feat/7-legacy", wt)
        gh = self._gh()
        gh.fx.setdefault("prs", []).append({"number": 90, "state": "OPEN", "headRefName": "feat/7-legacy",
                                            "body": "Closes #7", "title": "x"})   # K4r2-m3: its open PR head
        with mock.patch("workflows.dev.branching.worktree_path", lambda m, n: wt):
            p = self._factory(main, cfg, gh)(7, "test")
        self.assertEqual(p.branch, "feat/7-legacy")
        self.assertEqual(p.base, "origin/main")                  # K4r2-m2: the resolved base, never None
        self.assertIsNone(getattr(p, "unavailable", None))


# ---- M1 — author trust fails closed ------------------------------------------------------------------

CLOSE_BODY = ("x\n<!-- guild:plan-decision -->\n- Goal: 할까요? → close: not_planned — 현행 유지 (2026-10-28, sprint plan)\n"
              "<!-- /guild:plan-decision -->\n")
CLOSE_LINE = "- Goal: 할까요? → close: not_planned — 현행 유지 (2026-10-28, sprint plan)"


class M1(unittest.TestCase):
    def _close_h(self, author="OWNER"):
        return K4(self, body=CLOSE_BODY, author=author, roles=[evidence(self)], judges={"KICKOFF": kickoff(
            close={"decide": "not_planned", "source": "plan_line", "line": CLOSE_LINE})})

    def test_association_read_error_is_unknown_never_a_side(self):
        # K4r2-M2 changed this: unknown is neither member nor outsider — the stage pauses (env: service)
        h = self._close_h()
        h.gh.issue_author_association = _raise(GhError("HTTP 502: Bad Gateway"))
        with self.assertRaises(A.TrustUnknown) as cm:
            A.trusted_body(h.p, h.gh.issue(7))
        self.assertEqual(cm.exception.cls, "transient")
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)              # no close, no guess
        self.assertEqual(h.issue()["state"], "OPEN")
        self.assertIn("env: service", h.body_with("needs-human"))

    def test_blank_or_missing_association_is_unknown(self):
        for v in ("", "  ", None):
            h = self._close_h()
            h.gh.issue_author_association = lambda n, v=v: v
            with self.assertRaises(A.TrustUnknown) as cm:
                A.trusted_body(h.p, dict(h.gh.issue(7), author_association="OWNER"))
            self.assertEqual(cm.exception.cls, "defect")

    def test_association_auth_error_ends_the_run_with_3(self):
        h = self._close_h()
        h.gh.issue_author_association = _raise(GhError("HTTP 401: Bad credentials"))
        self.assertEqual(driver(h).run(7).exit_code, 3)

    def test_comment_without_association_is_not_a_record_nor_a_member_comment(self):
        c = {"id": 5, "body": "<!-- guild:analyze:output -->\nx\n<!-- /guild:analyze:output -->"}
        self.assertEqual(markers.trusted([c]), [])
        self.assertEqual(markers.trusted([dict(c, author_association="")]), [])
        self.assertEqual(len(markers.trusted([dict(c, author_association="MEMBER")])), 1)
        h = K4(self)
        self.assertEqual(A.human_comments(h.p, [{"id": 6, "body": "please do X"}]), [])


# ---- M2 / M3 — the split resumes from the recorded plan; failures need a person ---------------------

class M2M3(unittest.TestCase):
    CHILD8 = {"8": {"number": 8, "title": "[Guild子] data layer", "state": "OPEN",
                    "body": "x\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-data -->\n",
                    "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}], "comments": []}}

    def _creates(self, h):
        return [c for c in h.w.calls if c[0] == "create_issue"]

    def test_children_without_a_recorded_split_go_to_a_person(self):
        # review probe 1: child #8 + a NEW judgment with other keys used to create 2 more (AC #1 twice)
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec([dict(SPLIT["slices"][0], key="model"),
                                                 dict(SPLIT["slices"][1], key="ui")])}, issues=self.CHILD8)
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("children exist (#8)", r.line)
        self.assertEqual(self._creates(h), [])
        self.assertEqual(h.calls["roles"], [])                  # no tester / tech-lead / SPLIT re-run
        self.assertIn("guild:needs-human", h.labels())

    def _first_run_stops_after_one(self, h):
        orig = h.w.create_issue
        n = {"n": 0}

        def flaky(title, body, labels=()):
            n["n"] += 1
            if n["n"] == 2:
                raise GhError("HTTP 422: Validation Failed")
            return orig(title, body, labels)
        h.w.create_issue = flaky
        self.assertEqual(D.run(h.p).kind, StageResult.PAUSE)
        h.w.create_issue = orig
        h.p.writer.labels_apply(7, remove=["guild:needs-human"])

    def test_resume_never_reads_a_new_split_json_false(self):
        # review probe 2: the re-run tech-lead's split.json `split: false` used to advance to a single PR
        h = design_h(self, cast="", ui="false",
                     roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT), tester_ok(self, (1, 2)), techlead_ok(self)],
                     judges={"SPLIT": split_dec()})
        self._first_run_stops_after_one(h)
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.SPLIT)
        self.assertIn("guild:children", h.labels())
        self.assertEqual(len(self._creates(h)), 2)

    def test_tampered_plan_goes_to_a_person(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        self._first_run_stops_after_one(h)
        RO.put(h.p, "split-plan.json", RO.get(h.p, "split-plan.json").replace('"ui"', '"view"'))
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("does not match the recorded SPLIT block", r.line)
        self.assertEqual(len(self._creates(h)), 1)

    def test_child_outside_the_plan_goes_to_a_person(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        self._first_run_stops_after_one(h)
        stray = dict(self.CHILD8["8"], number=20, body="y\n\nParent Issue: #7\n\n<!-- guild:slice-key 7-other -->\n")
        h.gh.fx["issues"]["20"] = stray
        h.seed_child(20, stray)                     # K4r3-B1: the engine's own (journaled) child, outside the plan
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("outside the recorded split plan", r.line)
        self.assertIn("#20", r.line)

    def test_create_landed_but_the_call_failed_is_not_duplicated(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        orig = h.w.create_issue
        n = {"n": 0}

        def lands_then_fails(title, body, labels=()):
            n["n"] += 1
            r = orig(title, body, labels)
            if n["n"] == 2:
                raise GhError("HTTP 502: Bad Gateway")       # the server created it; the answer was lost
            return r
        h.w.create_issue = lands_then_fails
        r = D.run(h.p)
        kids = [k for k in h.gh.fx["issues"] if int(k) > 7]
        self.assertEqual(len(kids), 2)
        self.assertEqual(r.kind, StageResult.SPLIT)

    def test_transient_creation_failure_is_an_env_service_pause(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self, SPLIT)],
                     judges={"SPLIT": split_dec()})
        h.p.writer.issue_create = _raise(GhWriteError("issue:create", "HTTP 503", "transient"))
        r = D.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("env: service", h.body_with("needs-human"))


# ---- M4 — every FSM end maps to the §2.4 contract ------------------------------------------------------

class M4(unittest.TestCase):
    def _run(self, exc, where="stage"):
        h = K4(self)
        if where == "stage":
            return h, driver(h, {"analyze": _raise(exc)}).run(7)
        h.gh.issue = _raise(exc)
        return h, driver(h).run(7)

    def test_read_auth_is_3(self):
        self.assertEqual(self._run(GhError("HTTP 401: Bad credentials"))[1].exit_code, 3)
        self.assertEqual(self._run(GhError("HTTP 401: Bad credentials"), "first-read")[1].exit_code, 3)

    def test_read_rate_limit_is_75(self):
        out = self._run(GhError("API rate limit exceeded for user"))[1]
        self.assertEqual(out.exit_code, 75)
        buf = __import__("io").StringIO()
        F.final_events(out, out=buf)
        self.assertIn('"status":"rejected"', buf.getvalue().replace(" ", ""))

    def test_read_5xx_is_an_env_service_pause(self):
        h, out = self._run(GhError("HTTP 502: Bad Gateway"))
        self.assertEqual((out.exit_code, out.result.kind), (0, StageResult.PAUSE))
        self.assertIn("env: service", h.body_with("needs-human"))
        self.assertIn("guild:needs-human", h.labels())

    def test_any_exception_is_a_defect_pause(self):
        h, out = self._run(KeyError("slices"))
        self.assertEqual((out.exit_code, out.result.kind), (0, StageResult.PAUSE))
        self.assertIn("defect: engine FAIL — KeyError", h.body_with("needs-human"))

    def test_exception_with_unwritable_pause_is_1(self):
        h = K4(self)
        d = driver(h, {"analyze": _raise(OSError("disk"))})
        h.w.create_comment = _raise(GhError("HTTP 500"))
        self.assertEqual(d.run(7).exit_code, 1)

    def test_child_exception_pauses_the_child_and_a_child_exit_ends_the_parent(self):
        kid = {"8": {"number": 8, "title": "c", "state": "OPEN", "body": "x\n\nParent Issue: #7\n",
                     "labels": [{"name": "guild:child"}, {"name": "guild:analyze"}], "comments": []}}
        h = K4(self, labels=("guild:children",), issues=kid)
        out = driver(h, {"analyze": _raise(ValueError("boom"))}).run(7)
        self.assertEqual(out.exit_code, 0)
        nh = h.body_with("needs-human", 8)
        self.assertIn("defect: engine FAIL — ValueError", nh)
        h2 = K4(self, labels=("guild:children",), issues=kid)
        out2 = driver(h2, {"analyze": _raise(GhError("HTTP 401: Bad credentials"))}).run(7)
        self.assertEqual(out2.exit_code, 3)


# ---- M5 — close only from an exact, engine-verified member plan line ------------------------------------

class M5(unittest.TestCase):
    BODY = ("x\n<!-- guild:plan-decision -->\n- Goal: 화면 범위? → 기존 위젯 재사용 (2026-10-28, sprint plan)\n"
            "- Goal: 이미 되나? → 닫음: 하지 않기로 — 부채로 기록 (2026-10-28, sprint plan)\n<!-- /guild:plan-decision -->\n")

    def _h(self, line, decide="completed"):
        return K4(self, body=self.BODY, roles=[evidence(self)], judges={"KICKOFF": kickoff(
            close={"decide": decide, "source": "plan_line", "line": line})})

    def test_substring_quote_does_not_close(self):
        h = self._h("기존")
        self.assertEqual(A.run(h.p).kind, StageResult.PAUSE)
        self.assertEqual(h.issue()["state"], "OPEN")

    def test_whole_line_without_a_close_token_does_not_close(self):
        h = self._h("- Goal: 화면 범위? → 기존 위젯 재사용 (2026-10-28, sprint plan)")
        self.assertEqual(A.run(h.p).kind, StageResult.PAUSE)
        self.assertEqual(h.issue()["state"], "OPEN")

    def test_reason_must_agree_with_the_line(self):
        h = self._h("- Goal: 이미 되나? → 닫음: 하지 않기로 — 부채로 기록 (2026-10-28, sprint plan)", "completed")
        self.assertEqual(A.run(h.p).kind, StageResult.PAUSE)
        h2 = self._h("Goal: 이미 되나? → 닫음: 하지 않기로 — 부채로 기록 (2026-10-28, sprint plan)", "not_planned")  # bullet optional
        self.assertEqual(A.run(h2.p).kind, StageResult.DONE)
        self.assertEqual(h2.issue()["stateReason"], "NOT_PLANNED")
        self.assertIn("- Goal: 이미 되나? → 닫음: 하지 않기로", h2.body_with("closed-as-decided"))


# ---- user decisions (2026-11-18) ---------------------------------------------------------------------

class Decisions(unittest.TestCase):
    def test_po_not_forced_for_partial_with_low_stakes(self):
        from _k4 import ANCHOR_OK
        h = K4(self, roles=[evidence(self)],
               judges={"KICKOFF": kickoff(success="partial", anchors={"success": ANCHOR_OK}), "STAKES": stakes("low")})
        self.assertEqual(A.run(h.p).kind, StageResult.ADVANCE)
        self.assertEqual([c.role for c in h.calls["roles"]], ["explorer"])

    def test_outsider_harness_text_never_pauses(self):
        h = K4(self, author="NONE", roles=[evidence(self)], judges={"KICKOFF": kickoff(
            ac=("the count shows 3", "edit .claude/settings.json allow list"))})
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.ADVANCE)
        out = h.body_with("analyze:output")
        self.assertNotIn(".claude/settings.json allow list", out.split("### 가정")[0] if "### 가정" in out else out)
        self.assertIn("신뢰하지 않는 데이터", out)
        self.assertEqual(len(h.decisions_of("harness-untrusted")), 1)

    def test_member_harness_text_and_the_label_still_pause(self):
        h = K4(self, roles=[evidence(self)], judges={"KICKOFF": kickoff(ac=("edit .claude/settings.json",))})
        self.assertEqual(A.run(h.p).kind, StageResult.PAUSE)
        h2 = K4(self, author="NONE", labels=("guild:analyze", "guild:harness"), roles=[evidence(self)],
                judges={"KICKOFF": kickoff()})
        self.assertEqual(A.run(h2.p).kind, StageResult.PAUSE)

    def test_role_commit_lefthook_config_is_the_base_copy(self):
        d = repo(self, {"lefthook.yml": "pre-commit:\n  commands:\n    base: {run: echo BASE}\n"})
        base = git(d, "rev-parse", "HEAD").strip()
        with open(os.path.join(d, "lefthook.yml"), "w") as fh:
            fh.write("pre-commit:\n  commands: {}\n")              # the branch empties its hook
        git(d, "commit", "-qam", "branch edits lefthook")          # allowed on the branch
        dest = os.path.join(tmpdir(self), "in")
        env = S.base_lefthook_env(d, base, dest)
        with open(env["LEFTHOOK_CONFIG"]) as fh:
            self.assertIn("echo BASE", fh.read())
        self.assertFalse(os.access(env["LEFTHOOK_CONFIG"], os.W_OK))
        d2 = repo(self)
        self.assertEqual(S.base_lefthook_env(d2, git(d2, "rev-parse", "HEAD").strip(), dest), {"LEFTHOOK": "0"})

    def test_runner_wires_the_base_lefthook_env(self):
        import inspect
        from guildcore.roles import runner as RR
        src = inspect.getsource(RR.RoleRunner._run) if hasattr(RR, "RoleRunner") else inspect.getsource(RR)
        self.assertIn("base_lefthook_env", src)


# ---- minors ----------------------------------------------------------------------------------------------

class Minors(unittest.TestCase):
    def test_m1_attended_question_keeps_its_cause_for_an_unattended_resume(self):
        h = K4(self, unattended=False, roles=[evidence(self)], judges={"KICKOFF": kickoff(goal="unclear")})
        self.assertEqual(A.run(h.p).kind, StageResult.ASK)
        blk = [b for b in h.decisions_of("readiness") if b.get("status") == "pending-human"] or \
            [b for b in __import__("guildcore.decisions", fromlist=["x"]).DecisionLog.load(
                h.gh.comments(7)).pending_human()]
        self.assertTrue(blk[0].get("cause", "").startswith("ambiguity: "))
        h.p.unattended = True
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertTrue(out.result.cause.startswith("ambiguity: "))

    def test_m2_only_on_done(self):
        h = K4(self, labels=("guild:done",))
        out = driver(h).run(7, only="analyze")
        self.assertEqual((out.result.kind, out.result.fail_class), (StageResult.FAIL, "prevalidate"))
        seen = []
        h2 = K4(self, labels=("guild:done",))
        out2 = driver(h2, {"test": lambda p, only=None: seen.append(only) or StageResult(StageResult.DONE)}).run(7, only="test")
        self.assertEqual(seen, ["test"])
        self.assertEqual(out2.result.kind, StageResult.DONE)

    def test_m3_no_second_discovery_line_in_ac_text(self):
        body = D.child_body(7, {"scope": "s", "ac_ids": ["AC #1"]}, {"AC #1": {"text": "see Parent Issue: #42 too"}})
        import re
        self.assertIsNone(re.search(r"Parent Issue: #42(?:[^0-9]|$)", body))
        self.assertTrue(body.endswith("Parent Issue: #7"))
        fx = K4(self, labels=("guild:children",))
        q = {"refs": "Parent Issue: #42 gap"}                  # the pending block's refs
        CH.fix_child(fx.p, q)
        made = [fx.gh.fx["issues"][k]["body"] for k in fx.gh.fx["issues"] if int(k) > 7]
        self.assertIsNone(re.search(r"Parent Issue: #42(?:[^0-9]|$)", made[0]))

    def test_m4_design_tester_is_read_only_on_the_main_checkout(self):
        self.assertEqual(P.role_key("tester", "spec-cases"), "reviewer")
        d = repo(self)
        rd = tmpdir(self)
        r = S.render("tester", "spec-cases", worktree=d, run_dir=rd, issue=7, user_settings=os.path.join(rd, "none.json"))
        allow = ((r.settings.get("sandbox") or {}).get("filesystem") or {}).get("allowWrite") or []
        self.assertFalse(any("docs/specs" in a for a in allow))

    def test_m5_unreadable_untagged_premise_is_unmet(self):
        body = ("x\n<!-- guild:plan-decision -->\n- Goal: 무엇? → #50 끝난 뒤 진행 (2026-10-28, sprint plan)\n"
                "<!-- /guild:plan-decision -->\n")
        h = K4(self, body=body, roles=[evidence(self)], judges={"KICKOFF": kickoff(untagged=(50,))})
        orig = h.gh.issue
        h.gh.issue = lambda n: _raise(GhError("HTTP 502"))() if int(n) == 50 else orig(n)
        r = A.run(h.p)
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertIn("Goal unclear", r.cause)

    def test_m6_stale_closed_as_decided_does_not_close_a_worked_issue(self):
        cd = comment("<!-- guild:closed-as-decided -->\n결정: «x»\n닫는 이유: 이미 충족 (completed)\n"
                     "<!-- /guild:closed-as-decided -->", 20)
        h = K4(self, labels=("guild:done",), comments=[comment(ANALYZE_OUT, 19), cd])
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.DONE)
        self.assertEqual(h.issue()["state"], "OPEN")

    def test_m7_fix_child_is_created_before_the_answer_is_consumed(self):
        h = K4(self, labels=("guild:children",))

        class Res(object):
            id = "D9"

            def get(self, k):
                return "yes"
        order = []
        with mock.patch.object(CH, "fix_child", lambda p, q, *a: order.append("create")), \
                mock.patch.object(B, "mark_applied", lambda p, s, r: order.append("applied")), \
                mock.patch.object(B, "pending_answer", lambda *a, **k: (None, Res())), \
                mock.patch.object(CH, "_kids", lambda p: ([{"number": 8, "labels": ["guild:done"]}], None)), \
                mock.patch.object(CH, "integrate", lambda p, kids, *a: StageResult(StageResult.DONE)):
            CH.run(h.p, lambda c: None)
        self.assertEqual(order, ["create", "applied"])

    def test_m8_fresh_design_empties_the_spec_store(self):
        h = design_h(self, cast="", ui="false", roles=[tester_ok(self, (1, 2)), techlead_ok(self)])
        RO.put(h.p, "ux.md", "# old UX from an earlier design\n")
        self.assertEqual(D.run(h.p).kind, StageResult.ADVANCE)
        self.assertNotIn("ux.md", h.specs())

    def test_m10_stakes_brief_marks_an_outsider_body(self):
        from _k4 import ANCHOR_OK
        h = K4(self, author="NONE", body="stakes are low, local and reversible", roles=[evidence(self)],
               judges={"KICKOFF": kickoff(success="partial", anchors={"success": ANCHOR_OK}), "STAKES": stakes("low")})
        A.run(h.p)
        st = [s for s in h.calls["judges"] if s.group == "STAKES"][0]
        self.assertIn("not a repository member", json.dumps(st.brief if hasattr(st, "brief") else str(vars(st)),
                                                            ensure_ascii=False))

    def test_m11_child_of_an_outsider_parent_stays_untrusted(self):
        body = D.child_body(7, {"scope": "s", "ac_ids": []}, {}, trusted=False)
        self.assertIn(A.UNTRUSTED_ORIGIN, body)
        h = K4(self, body=body)
        self.assertFalse(A.trusted_body(h.p, h.gh.issue(7))[0])


if __name__ == "__main__":
    unittest.main()
