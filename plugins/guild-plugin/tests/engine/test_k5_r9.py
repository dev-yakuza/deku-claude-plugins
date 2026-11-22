"""K5 review r9 — M1 (a person's TEST `gap` takes effect: no advance, the log says what the person chose), M2 (a
person's INTEGRATE `gap` with no judge gap is a decision gap, never an IndexError; `applied` is written only after the
answer's effect), the table "answering X through the conservative gate == the judge choosing X" over every gated group
and option (the conservative default too), m1 (the r7 evaluative labels are cut again while r8's descriptive labels
stay), m3 (qa's real second decision point — DIRECTIVE at the CI habit stop — under the r8 M2 scenario).
"""

import copy
import re
import unittest

import _util  # noqa: F401
from _k2 import FLUTTER_GREEN, FLUTTER_RED, Harness, comment, decision, fixture, role, suite
from _k4 import K4, evidence, kickoff, out_role, techlead_ok, tester_ok
from test_k2_qa_stage import qa_harness
from test_k2_test_stage import EVIDENCE, TC, covers, green_harness
from test_k4_design import SPLIT, design_h
from test_k4_fsm import Children, driver, relabel

from guildcore import ask as ASK
from guildcore.decisions import DecisionLog
from guildcore.judges.runner import Decision
from workflows.dev import conservative as CONS
from workflows.dev import judging as JG
from workflows.dev import predict as PF
from workflows.dev.stages import analyze as A
from workflows.dev.stages import base as B
from workflows.dev.stages import design as D
from workflows.dev.stages import qa as Q
from workflows.dev.stages import test as T
from workflows.dev.stages.base import StageResult


def _blocks(h):
    return DecisionLog.load(h.gh.comments(h.n)).blocks


def _open_questions(h, group):
    """Conservative questions of `group` nobody answered yet."""
    bl = _blocks(h)
    answered = set(b.get("resolves") for b in bl if b.get("by") == "human" and b.get("choice"))
    return [b for b in bl if b.get("kind") == CONS.KIND and b.get("status") == "pending-human"
            and str(b.get("refs") or "").startswith("conservative:%s:" % group) and b.id not in answered]


def _answer(h, blk, choice):
    ASK.answer(h.decisions, h.writer, h.n, blk.id, choice)
    iss = h.issue()
    iss["labels"] = [lb for lb in iss["labels"] if (lb.get("name") if isinstance(lb, dict) else lb)
                     != "guild:needs-human"]


def runner_judge(group, fields_of, choice, seen=None):
    """A judge that chose `choice` on the scenario's evidence, as the JudgeRunner leaves it (the group's coercions)."""
    def judge(spec):
        if seen is not None:
            seen.append(spec.point)
        f = copy.deepcopy(fields_of(choice))
        f[JG.CHOICE.get(group, "verdict")] = choice
        if group in CONS.SECURITY_FIELD_GROUPS:
            f.setdefault(CONS.SECURITY_FIELD, False)        # 0.102.7: a schema-valid output carries the field
        for co in JG.COERCIONS.get(group, ()):
            f, _by = co(f)
        return Decision(f.get(JG.CHOICE.get(group, "verdict")), f, "judge:sonnet", "dg-%s" % spec.point)
    return judge


def _guarded(stage, fn):
    return lambda h: CONS.guarded(h.p, stage, lambda: fn(h))


def _fsm(h):
    out = driver(h).run(h.n)
    return out.result


# -- the scenarios: one per gated group, each reaching that group's real decision point in its real stage ------------

def _test_h(case, judge):
    h = green_harness(case, judges={"TEST": judge}, roles=[role("DONE", covers=covers(), e2e="E2E 불요: x")] * 8)
    h.suites.extend([suite(FLUTTER_GREEN)] * 6)
    h.p.git_dir = None
    return h


def _test_fields(_c):
    return {"ac": [{"id": a, "covered_by": ["test/a_test.dart::t"], "verdict": "effective", "why": "w"}
                   for a in ("C1", "C2")], "visual_rows": []}


def _vis_h(case, judge):
    raw = FLUTTER_RED + 'Golden "test/goldens/other.png": Pixel test failed\n'
    h = Harness(case, fixture(comments=[comment(EVIDENCE, 2)]),
                roles=[role("DONE", covers=covers(), e2e="E2E 불요: x")] * 8, judges={"VIS-ENV": judge},
                suites=[suite(raw, passed=False, rc=1)] * 6)
    h.write_file("docs/specs/7/test-cases.md", TC)
    h.p.git_dir = None
    return h


def _qa_role():
    return role("DONE", plan="qa-report.md", human_items=[], followups=[])


def _qa_h(case, judge):
    h = qa_harness(case, roles=[_qa_role()] * 8, judges={"QA": judge})
    h.write_file("docs/standards/quality-bar.md", "# bar\n- no crash\n")
    h.p.git_dir = None
    return h


def _qa_fields(_c):
    return {"defects": [], "checklist": ["로그인 확인"], "quality_bar_met": "yes"}


def _directive_h(case, judge, qa_judge=None):
    """qa at the CI habit stop (`stop_on_ci_red`, CI red) with a person's comment: DIRECTIVE at Q2.3."""
    import _k2
    runs = [{"id": 5, "name": "build", "conclusion": "failure", "annotations": 0}]
    h = qa_harness(case, runs=runs, roles=[_qa_role()] * 8, comments=[comment("사람 지시: CI 실패는 무시", 5)],
                   judges={"QA": qa_judge or runner_judge("QA", _qa_fields, "pass"), "DIRECTIVE": judge})
    h.p.config = dict(_k2.CFG, engine={"qa": {"stop_on_ci_red": True}})
    h.write_file("docs/standards/quality-bar.md", "# bar\n- no crash\n")
    h.p.git_dir = None
    return h


def _directive_fields(_c):
    hit = [{"comment": "#7", "line": "CI 실패는 무시"}]
    return {"applies": hit, "out_of_scope": hit}


def _integrate_h(case, judge):
    kid = Children.kid(None, 8, labels=("guild:child", "guild:execute"), state="CLOSED",
                       closed_by_prs=[{"number": 31, "repo": "o/r"}])
    return K4(case, labels=("guild:children",), issues={"8": kid},
              prs=[{"number": 31, "state": "MERGED", "body": "", "url": "u"}],
              roles=[out_role(case, "FAIL", "x")] * 6, judges={"INTEGRATE": judge})


def _stakes_h(case, judge):
    h = K4(case, roles=[evidence(case)] + [out_role(case, "DONE", ac_patch=[])] * 4,
           judges={"KICKOFF": kickoff(success="partial", anchors={"success": {"cite": "lib/app/home.dart:3",
                                                                               "quote": "int count() => 3;"}}),
                   "STAKES": judge})
    h.p.journal = h.journal
    return h


def _stakes_fields(_c):
    return {"local_reversible_reason": "local to one widget, a revert undoes it", "cites": []}


def _anpo_h(case, judge):
    po = out_role(case, "DONE_WITH_CONCERNS", "AC 2 vague", ac_patch=[])
    h = K4(case, roles=[evidence(case), po, po], judges={"KICKOFF": kickoff(po=True), "AN-PO": judge,
                                                          "STAKES": decision("high", {"level": "high"})})
    h.p.journal = h.journal
    return h


def _anpo_fields(_c):
    return {"rating": "unclear", "reason": "vague"}


def _dearb_h(case, judge):
    h = design_h(case, cast="", ui="false",
                 roles=[tester_ok(case, (1, 2)), out_role(case, "BLOCKED", "which module?", evidence="none"),
                        techlead_ok(case), techlead_ok(case)],
                 judges={"DE-ARB": judge, "STAKES": decision("high", {"level": "high"})})
    h.p.journal = h.journal
    return h


def _dearb_fields(_c):
    return {"role": "tech-lead", "addendum": "use lib/app only", "assumption": "keep one module",
            "reason": "executor_conflict", "question": "which module?", "options": []}


def _split_h(case, judge):
    h = design_h(case, cast="", ui="false", roles=[tester_ok(case, (1, 2)), techlead_ok(case, SPLIT)],
                 judges={"SPLIT": judge})
    h.p.journal = h.journal
    return h


def _split_fields(_c):
    return {"slices": copy.deepcopy(SPLIT["slices"]), "reason": "two PRs"}


def _handoff_h(case, judge):
    h = K4(case, labels=("guild:execute",), judges={"HANDOFF": judge})
    h.p.journal = h.journal
    ran = []

    def test_stage(p, **k):
        ran.append(1)
        return StageResult(StageResult.PAUSE, cause="test ran")
    h.stages = {"execute": relabel(h, "test"), "test": test_stage}
    return h


def _handoff_fields(_c):
    return {"line": "evidence is in the PR", "fixable_by_execute": False}


def _handoff_run(h):
    return driver(h, h.stages).run(h.n).result


def _exdwc_h(case, judge):
    """execute runs live again after an answer (no replay): each stage run is dev → tech-lead (a concern the FIRST
    time in that run) → auditor, and again after a loop-back."""
    from _k3 import XHarness, auditor, dev
    seen = {"tl": 0}

    def dispatch(call):
        if call.role == "tech-lead":
            seen["tl"] += 1
            return role("DONE_WITH_CONCERNS", "M4 mutant not pinned") if seen["tl"] == 1 else role("DONE")
        return auditor() if call.role == "auditor" else dev()
    h = XHarness(case, roles=[dispatch] * 24, suites=[suite(FLUTTER_GREEN)] * 12, judges={"EX-DWC": judge})
    h.exdwc_seen = seen
    return h


def _exdwc_run(h):
    from workflows.dev.stages import execute as X
    h.exdwc_seen["tl"] = 0                                                # a new stage run
    return CONS.guarded(h.p, "execute", lambda: X.run(h.p, "implement"))


def _reason(_c):
    return {"reason": "r"}


# group → (harness, run, fields-of-the-evidence, the judge's own non-default pick, {option: the outcome kind})
SCENARIOS = {
    "TEST": (_test_h, _guarded("test", lambda h: T.run(h.p)), _test_fields, "all_effective",
             {"all_effective": StageResult.ADVANCE, "gap": StageResult.LOOPBACK}),
    "VIS-ENV": (_vis_h, _guarded("test", lambda h: T.run(h.p)), lambda c: {}, "regression",
                {"regression": StageResult.LOOPBACK, "env_suspect": StageResult.PAUSE}),
    "QA": (_qa_h, _guarded("qa", lambda h: Q.run(h.p, diff_paths=[])), _qa_fields, "pass",
           {"pass": StageResult.DONE, "block": StageResult.PAUSE}),
    "DIRECTIVE": (_directive_h, _guarded("qa", lambda h: Q.run(h.p, diff_paths=[])), _directive_fields, "applies",
                  {"applies": StageResult.PAUSE, "none": StageResult.PAUSE, "out_of_scope": StageResult.PAUSE}),
    "INTEGRATE": (_integrate_h, _fsm, lambda c: {"coverage": [], "gaps": []}, "clean",
                  {"clean": StageResult.DONE, "gap": StageResult.PAUSE}),
    "STAKES": (_stakes_h, _guarded("analyze", lambda h: A.run(h.p)), _stakes_fields, "low",
               {"low": StageResult.ADVANCE, "medium": StageResult.ADVANCE, "high": StageResult.PAUSE}),
    "AN-PO": (_anpo_h, _guarded("analyze", lambda h: A.run(h.p)), _anpo_fields, "record",
              {"record": StageResult.ADVANCE, "rerate_success": StageResult.PAUSE}),
    "DE-ARB": (_dearb_h, _guarded("design", lambda h: D.run(h.p)), _dearb_fields, "reinvoke",
               {"reinvoke": StageResult.ADVANCE, "decide": StageResult.PAUSE, "escalate": StageResult.PAUSE,
                "pause": StageResult.PAUSE}),
    "SPLIT": (_split_h, _guarded("design", lambda h: D.run(h.p)), _split_fields, "single",
              {"single": StageResult.ADVANCE, "split": StageResult.SPLIT}),
    "HANDOFF": (_handoff_h, _handoff_run, _handoff_fields, "ok",
                {"ok": StageResult.PAUSE, "ok_with_assumption": StageResult.PAUSE, "upstream_gap": StageResult.PAUSE}),
    "EX-DWC": (_exdwc_h, _exdwc_run, _reason, "loop_back",
               {"loop_back": StageResult.ADVANCE, "proceed": StageResult.ADVANCE}),
}


def options(group):
    prop = JG.schema(group)["properties"][JG.CHOICE.get(group, "verdict")]
    return [x for x in prop["enum"] if x not in CONS.NOT_OPTIONS]


# the one intended difference: who named an unnamed gap (the person's decision id vs the judge's rule)
_ATTRIBUTION = re.compile(r"사람이 (?:통합|커버리지) 간극으로 판정 \(D\d+\)|integration judged a gap without naming it|"
                          r"the judgment named a gap without an AC")


def outcome(h, r, group):
    """What the stage did: its result kind and line, the Issue's labels, the group's own judgment blocks (point ·
    choice)."""
    log = [(b.get("point"), b.get("choice")) for b in _blocks(h)
           if b.get("point") == group or str(b.get("point") or "").startswith(group + ":")]
    line = _ATTRIBUTION.sub("<gap>", re.sub(r"#\d+:? group\.\S+", "", str(getattr(r, "cause", None) or "")))
    return (getattr(r, "kind", r), line, h.labels(), log)


class AnswerEqualsJudge(unittest.TestCase):
    """K5r9 table: for every gated group and every option X (the conservative default included), a person answering X
    to the group's conservative question has the stage outcome / labels / judgment log of the judge choosing X."""

    def native(self, group, x):
        build, run, fields, _y, _e = SCENARIOS[group]
        h = build(self, runner_judge(group, fields, x))
        return outcome(h, run(h), group)

    def gated(self, group, x):
        build, run, fields, y, _e = SCENARIOS[group]
        h = build(self, runner_judge(group, fields, y))
        h.p.valves = {"group.%s.conservative" % group: True}
        asked = 0
        for _i in range(5):
            r = run(h)
            q = _open_questions(h, group)
            if not q:
                break
            asked += 1
            _answer(h, q[-1], x)
        else:
            self.fail("%s/%s: the questions never ended" % (group, x))
        self.assertGreaterEqual(asked, 1, "%s: the judge's %s raised no conservative question" % (group, y))
        by = [b.get("by") for b in _blocks(h) if b.get("point") == group]
        self.assertTrue(by and by[-1] == "human", (group, x, by))
        return outcome(h, r, group)

    def test_every_gated_group_has_a_scenario(self):
        self.assertEqual(sorted(SCENARIOS), sorted(CONS.GATED))

    def test_answer_x_is_the_judge_choosing_x(self):
        """K5r10-M1/m4: these fixtures pre-fill every option's fields — so only an X whose own fields (JG.OPTION_FIELDS)
        the judge's Y shares is compared here; an X that needs grounds only a judge choosing X writes (DE-ARB decide /
        escalate, SPLIT split, HANDOFF ok_with_assumption) never runs on Y's fields any more — `test_k5_r10.Table`
        covers every (X, Y ≠ X) on Y's own output shape."""
        for group in CONS.GATED:
            y = SCENARIOS[group][3]
            table = JG.OPTION_FIELDS.get(group) or {}
            for x in options(group):
                if x != y and not set(table.get(x, ())) <= set(table.get(y, ())) and \
                        set(table.get(x, ())) - set(JG._fill(group, x, {}, "D0")):
                    continue
                with self.subTest(group=group, option=x):
                    want = self.native(group, x)
                    got = self.gated(group, x)
                    self.assertEqual(got, want)
                    exp = SCENARIOS[group][4].get(x)
                    self.assertEqual(got[0], exp)

    def test_the_conservative_default_is_an_option_of_every_defaulted_group(self):
        for group in CONS.GATED:
            safe = JG.UNSURE.get(group)
            if safe is not None:
                self.assertIn(safe, options(group), group)


class M1TestGapTakesEffect(unittest.TestCase):
    """review-k5-r9 test_gap_ignored.py — the judge says all_effective, the person answers `gap`."""

    def go(self, unattended):
        h = green_harness(self, unattended=unattended,
                          roles=[role("DONE", covers=covers(), e2e="E2E 불요: x")] * 6,
                          judges={"TEST": runner_judge("TEST", _test_fields, "all_effective")})
        h.suites.extend([suite(FLUTTER_GREEN)] * 4)
        h.p.valves = {"group.TEST.conservative": True}
        h.p.git_dir = None
        run = _guarded("test", lambda hh: T.run(hh.p))
        run(h)
        q = _open_questions(h, "TEST")
        self.assertEqual(q[-1].get("refs"), "conservative:TEST:#7:test:T3.4:L0")
        _answer(h, q[-1], "gap")
        r = run(h)
        self.assertNotEqual(getattr(r, "kind", None), StageResult.ADVANCE)
        self.assertNotIn("guild:qa", h.labels())
        blk = [b for b in _blocks(h) if b.get("point") == "TEST"][-1]
        self.assertEqual((blk.get("choice"), blk.get("by"), blk.get("coerced_by")),
                         ("effective:none;uncovered:C1,C2", "human", "conservative"))
        self.assertEqual(blk.get("unsure_acs"), "C1,C2")
        # the repair re-judgment (TEST:repair) is a decision point of its own: its answer takes effect the same way
        q2 = _open_questions(h, "TEST")
        self.assertEqual(q2[-1].get("refs"), "conservative:TEST:#7:test:T3.4:L0:TEST:repair")
        _answer(h, q2[-1], "gap")
        r = run(h)
        self.assertIn(getattr(r, "kind", None), (StageResult.PAUSE, StageResult.ASK, StageResult.LOOPBACK))
        rep = [b for b in _blocks(h) if b.get("point") == "TEST:repair"][-1]
        self.assertEqual((rep.get("choice"), rep.get("by")), ("effective:none;uncovered:C1,C2", "human"))
        self.assertNotIn("guild:qa", h.labels())

    def test_unattended(self):
        self.go(True)

    def test_attended(self):
        self.go(False)

    def test_apply_choice_rewrites_the_per_ac_verdicts(self):
        sp = JG.spec(None, "TEST", [("x", "y")], "test", "T3.4")
        f, final, _by = JG.apply_choice(sp, dict(_test_fields(None), overall="all_effective"), "gap", who="D9")
        self.assertEqual(final, "gap")
        self.assertEqual([a["verdict"] for a in f["ac"]], ["unsure", "unsure"])
        self.assertIn("D9", f["ac"][0]["why"])
        f, final, _by = JG.apply_choice(sp, dict(_test_fields(None), overall="all_effective"), "all_effective")
        self.assertEqual([a["verdict"] for a in f["ac"]], ["effective", "effective"])

    def test_the_judges_own_inconsistent_gap_is_a_gap_too(self):
        f, by = JG.coerce_test(dict(_test_fields(None), overall="gap"))
        self.assertEqual((by, [a["verdict"] for a in f["ac"]]), ("rule", ["unsure", "unsure"]))
        f, by = JG.coerce_test({"ac": [{"id": "C1", "verdict": "vacuous"}], "overall": "all_effective"})
        self.assertEqual((by, f["overall"]), ("rule", "gap"))


class M2IntegrateGap(unittest.TestCase):
    """review-k5-r9 integrate_gap_crash.py — judge `clean` with no gaps, the person answers `gap`."""

    def go(self, unattended):
        h = _integrate_h(self, runner_judge("INTEGRATE", lambda c: {"coverage": [], "gaps": []}, "clean"))
        h.p.valves = {"group.INTEGRATE.conservative": True}
        out = driver(h, unattended=unattended).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        q = _open_questions(h, "INTEGRATE")
        self.assertEqual(q[-1].get("refs"), "conservative:INTEGRATE:#7:children:2c.2:L0")
        _answer(h, q[-1], "gap")
        out = driver(h, unattended=unattended).run(7)
        self.assertNotIn("IndexError", out.line or "")
        self.assertNotIn("engine FAIL", out.line or "")
        res = [b for b in _blocks(h) if b.get("resolves") == q[-1].id and b.get("by") == "human"][-1]
        self.assertIn("사람이 통합 간극으로 판정 (%s)" % res.id, out.line or "")   # the person's decision, by id
        self.assertNotIn("guild:done", h.labels())
        blk = [b for b in _blocks(h) if b.get("point") == "INTEGRATE"][-1]
        self.assertEqual((blk.get("choice"), blk.get("by")), ("gap", "human"))
        self.assertIn("verdict: gap", h.body_with("integration:output"))
        self.assertIn("### 간극", h.body_with("integration:output"))
        self.assertTrue([b for b in _blocks(h) if b.get("point") == "applied"])

    def test_unattended(self):
        self.go(True)

    def test_attended(self):
        self.go(False)

    def test_a_judges_gap_without_gaps_is_no_crash_either(self):
        h = _integrate_h(self, lambda spec: decision("gap", {"verdict": "gap", "coverage": [], "gaps": []}))
        h.judges["INTEGRATE"] = lambda spec: Decision("gap", {"verdict": "gap", "coverage": [], "gaps": []},
                                                      "judge:opus", "dg")
        h._judge = lambda spec: h.judges["INTEGRATE"](spec)                 # no coercion: the stage's own guard
        h.p.judge = h._judge
        out = driver(h).run(7)
        self.assertEqual(out.result.kind, StageResult.PAUSE)
        self.assertIn("integration judged a gap without naming it", out.line)


class M2AppliedAfterTheEffect(unittest.TestCase):
    def _answered(self):
        h = _qa_h(self, runner_judge("QA", _qa_fields, "pass"))
        h.p.valves = {"group.QA.conservative": True}
        _guarded("qa", lambda hh: Q.run(hh.p, diff_paths=[]))(h)
        _answer(h, _open_questions(h, "QA")[-1], "block")
        return h

    def _applied(self, h):
        return [b for b in _blocks(h) if b.get("point") == "applied"]

    def _gate(self, h):
        return CONS.gate(h.p, JG.spec(h.p, "QA", [("x", "y")], "qa", "Q2.5"), runner_judge("QA", _qa_fields, "pass"))

    def test_a_crash_after_the_gate_leaves_the_answer_unapplied(self):
        h = self._answered()

        def crash():
            self._gate(h)
            raise RuntimeError("write failed")
        with self.assertRaises(RuntimeError):
            CONS.guarded(h.p, "qa", crash)
        self.assertEqual(self._applied(h), [])
        CONS.begin(h.p)
        self.assertEqual(self._gate(h).choice, "block")                     # the same point: applied again

    def test_a_fail_leaves_it_unapplied(self):
        h = self._answered()
        r = CONS.guarded(h.p, "qa", lambda: (self._gate(h), StageResult(StageResult.FAIL, line="x",
                                                                         fail_class="defect"))[1])
        self.assertEqual(r.kind, StageResult.FAIL)
        self.assertEqual(self._applied(h), [])

    def test_the_effect_written_marks_it(self):
        h = self._answered()
        r = CONS.guarded(h.p, "qa", lambda: (self._gate(h), StageResult(StageResult.PAUSE, cause="x"))[1])
        self.assertEqual(r.kind, StageResult.PAUSE)
        self.assertEqual(len(self._applied(h)), 1)


class M1LabelRule(unittest.TestCase):
    # r7 cut these (5b3d93f), r8 m3 let them through (review-k5-r9 label_regress_r9.py)
    EVALUATIVE = ("앱 전체 (제목 그대로 해석)", "앱 전체 — 요청 그대로의 범위", "앱 전체 (요청 그대로 구현)",
                  "ログイン画面のみ（タイトル通りに解釈）", "アプリ全体（本文通りに読む）", "Whole app (taking the title literally)",
                  "Whole app (matches the title text)", "Login only (the title's literal sense)", "Login only (literal scope)",
                  "Whole app (typical scope)", "Whole app (the typical case)", "로그인만 (근거가 약해 보임)", "로그인만 (근거: 제목)",
                  "Whole app (follows the title text)", "ログインのみ（根拠：タイトル）", "Whole app (read the title literally)")
    # r8 m3: descriptive — kept as they are
    DESCRIPTIVE = ("근거 자료 링크 추가", "本文 그대로 표시", "본문 그대로 표시", "根拠リンクを追加", "タイトル通りに表示",
                   "Typical flow only", "Literal string search", "Match title case in headers",
                   "Header follows the title style")

    def test_evaluative_labels_are_cut(self):
        for lb in self.EVALUATIVE:
            self.assertTrue(PF.evaluative(lb), lb)
            head = lb.split(" (")[0].split("（")[0].split(" — ")[0]
            self.assertEqual(PF.neutral_label(lb), head, lb)

    def test_descriptive_labels_are_kept(self):
        for lb in self.DESCRIPTIVE:
            self.assertFalse(PF.evaluative(lb), lb)
            self.assertEqual(PF.neutral_label(lb), lb, lb)


class M3DirectiveSecondPoint(unittest.TestCase):
    """r8 M2 through qa's real second conservative point: QA (Q2.5) then DIRECTIVE at the CI habit stop (Q2.3)."""

    def _h(self):
        qa_seen, dr_seen = [], []
        h = _directive_h(self, runner_judge("DIRECTIVE", _directive_fields, "applies", dr_seen),
                         qa_judge=runner_judge("QA", _qa_fields, "pass", qa_seen))
        h.p.valves = {"group.QA.conservative": True, "group.DIRECTIVE.conservative": True}
        return h, qa_seen, dr_seen

    def _two_questions(self, h):
        run = _guarded("qa", lambda hh: Q.run(hh.p, diff_paths=[]))
        run(h)
        q = _open_questions(h, "QA")
        self.assertEqual(q[-1].get("refs"), "conservative:QA:#7:qa:Q2.5:L0")
        _answer(h, q[-1], "pass")
        run(h)
        q = _open_questions(h, "DIRECTIVE")
        self.assertEqual(q[-1].get("refs"), "conservative:DIRECTIVE:#7:qa:Q2.3:L0")
        return run, q[-1]

    def test_same_run_replayed_reuses_the_qa_answer(self):
        h, qa_seen, dr_seen = self._h()
        run, dq = self._two_questions(h)
        _answer(h, dq, "out_of_scope")
        r = run(h)
        self.assertEqual(r.kind, StageResult.PAUSE)                        # the CI habit stop, with the directive line
        self.assertEqual(qa_seen, ["QA"])                                  # QA judged once — its answer reused
        self.assertFalse(_open_questions(h, "QA"))
        self.assertEqual([(b.get("choice"), b.get("by")) for b in _blocks(h) if b.get("point") == "DIRECTIVE"],
                         [("out_of_scope", "human")])

    def test_inputs_changed_between_the_questions_judge_qa_again(self):
        h, qa_seen, dr_seen = self._h()
        run, dq = self._two_questions(h)
        h.issue()["body"] = (h.issue().get("body") or "") + "\n\n(edited: also iPad)"
        _answer(h, dq, "out_of_scope")
        run(h)
        self.assertEqual(qa_seen, ["QA", "QA"])                            # live → judged again, no old answer
        q = _open_questions(h, "QA")
        self.assertEqual(q[-1].get("refs"), "conservative:QA:#7:qa:Q2.5:L0:a1")


if __name__ == "__main__":
    unittest.main()
