"""U17 prbody: the PR body from facts only (scope §6.2 U17: facts fixture → body snapshot).

The snapshot `tests/fixtures/prbody/feature-42.body.md` is the body for the scenario built in
`scenario()` (stage-1 start procedure + plugin feature template, every step done, one flaky
test attempt, a major finding, a refused write, verification and irreversible paths
changed, discoveries). GLD_UPDATE_SNAPSHOT=1 rewrites it (review the diff by hand).
"""

import copy
import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from gxengine import codes, defaults, driver, instructions, outbound, paths as pathsmod, prbody, procedure
from tests.helpers.defects import fixes_defect

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ENGINE, "tests", "fixtures", "prbody", "feature-42.body.md")
SNAP2 = os.path.join(ENGINE, "tests", "fixtures", "prbody", "feature-42-stage2.body.md")
SNAP3 = os.path.join(ENGINE, "tests", "fixtures", "prbody", "bug-42-stage3.body.md")
SNAP4 = os.path.join(ENGINE, "tests", "fixtures", "prbody", "bug-42-stage4.body.md")
ISSUE = 42


def read(*parts):
    with open(os.path.join(ENGINE, *parts), encoding="utf-8") as f:
        return f.read()


SHA = {k: (k * 40)[:40] for k in "abcdef"}


def facts(step, attempt, kind, run=None, changed=(), denials=None, warnings=()):
    return {
        "format": 1, "issue": ISSUE, "step": step, "attempt": attempt, "kind": kind,
        "base_sha": SHA["a"], "merge_base": SHA["a"], "start_head": SHA["b"], "end_head": SHA["c"],
        "start_tree": {"clean": True, "dirty_files": []}, "end_tree": {"clean": True, "dirty_files": []},
        "exit_code": run["exit_code"] if run else 0,
        "changed_files": [dict(c) for c in changed], "outputs": [],
        "session": None if denials is None else {
            "init": {"ok": True, "mismatches": []}, "end": "completed", "structured_output": True,
            "stream_file": "stream.jsonl", "permission_denials": denials},
        "run": run, "warnings": [dict(w) for w in warnings],
    }


def green(name):
    return {"name": name, "exit_code": 0, "timed_out": False, "log_file": "run.log", "rerun": None, "base_run": None}


CHANGED = [
    {"path": "src/settings.ts", "change": "modified", "from": None, "where": "committed"},
    {"path": "test/settings_test.dart", "change": "added", "from": None, "where": "committed"},
    {"path": "db/migrations/007_quiz.sql", "change": "added", "from": None, "where": "committed"},
    {"path": "src/new_name.ts", "change": "renamed", "from": "src/old_name.ts", "where": "committed"},
    {"path": "docs/specs/42/analysis.md", "change": "added", "from": None, "where": "committed"},
]

CONFIG = {
    "format": 1,
    "commands": {n: {"cmd": "true"} for n in ("setup", "lint", "typecheck", "test", "build", "e2e")}
    | {"ac-format": {"plugin": "ac-format"}, "ac-coverage": {"plugin": "ac-coverage"},
       "verify-gate": {"plugin": "verify-gate"}},
    "path_rules": [
        {"kind": "verification", "globs": ["test/**", "**/*_test.dart"]},
        {"kind": "irreversible", "category": "hard-to-revert", "globs": ["db/migrations/**"]},
    ],
    "not_checked_locally": [{"name": "e2e_test/e2e_test", "note": "needs an Android emulator"},
                            {"name": "build: flutter build windows", "note": "other platform"}],
}


def scenario():
    # the stage-1 view of the plugin template (no done-gate: procedure.build parses text at stage 1)
    proc = procedure.build(instructions.load_start_procedure(stage=1), instructions.load_default_template("feature", stage=1), ISSUE,
                           list(CONFIG["commands"]))
    steps = []
    for st in proc.steps:
        status = "running" if st.kind == "op" else "done"
        row = {"id": st.id, "status": status, "latest_attempt": 1 if status == "done" else None}
        if st.id == "build":
            row.update(status="skipped", latest_attempt=None, reason="not checked locally (Xcode in srt)")
        steps.append(row)
    for row in steps:
        if row["id"] == "test":
            row["latest_attempt"] = 2
    state = {"format": 1, "issue": ISSUE, "revision": 1, "steps": steps, "last_head": SHA["c"],
             "totals": {"attempts": 19, "cost_usd": 12.5, "warnings": 1}}
    fb = {}
    for st in proc.steps:
        if st.kind == "run" and st.id != "build":
            fb[st.id] = facts(st.id, 1, "run", run=green(st.name))
        elif st.kind == "role":
            fb[st.id] = facts(st.id, 1, "role", denials=[])
    flaky = dict(green("test"), exit_code=1, rerun={"exit_code": 0, "timed_out": False, "log_file": "run-rerun.log"},
                 base_run={"exit_code": 0, "timed_out": False, "log_file": "run-base.log"})
    fb["test"] = [facts("test", 1, "run", run=flaky), facts("test", 2, "run", run=green("test"))]
    fb["implement"] = facts("implement", 1, "role", changed=CHANGED[:2],
                            denials=[{"tool_name": "Write", "tool_input": {"file_path": "/wt/.claude/agents/x.md"}},
                                     {"tool_name": "Bash", "tool_input": {"command": "curl x"}}],
                            warnings=[{"fact": "cost_usd", "note": "no result event"}])
    fb["verify-gate"] = facts("verify-gate", 1, "run", run=green("verify-gate"), changed=CHANGED)
    results = {
        "review-design": {"status": "done", "findings": [
            {"severity": "major", "file": "src/settings.ts", "line": 12, "text": "the summary label is computed twice"},
            {"severity": "minor", "file": "src/settings.ts", "line": None, "text": "naming"}],
            "discoveries": []},
        "review-audit": {"status": "done", "findings": [], "discoveries": [
            {"kind": "bug", "where": "lib/review_screen.dart", "note": "select-all ignores #12 @alice", "blocks_current_ac": False},
            {"kind": "test-gap", "where": "test/sheet_test.dart", "note": "the sheet had no test", "blocks_current_ac": True}]},
        "implement": [{"status": "done", "discoveries": [
            {"kind": "debt", "where": "lib/settings.dart", "note": "old layout helper", "blocks_current_ac": False}]},
                      {"status": "done", "discoveries": [
            {"kind": "debt", "where": "lib/settings.dart", "note": "old layout helper", "blocks_current_ac": False}]}],
    }
    qa = "- [ ] Open settings → quiz type row is shown\n- [ ] Restart the app → the choice is kept\n"
    analysis = read("tests", "fixtures", "ac", "analysis-ok.md")
    return proc, state, fb, results, CONFIG, qa, analysis


class Body(unittest.TestCase):
    def setUp(self):
        self.args = scenario()

    def body(self, **changes):
        names = ("procedure", "state", "facts_by_step", "results_by_step", "config", "qa_checklist", "analysis")
        args = dict(zip(names, copy.deepcopy(self.args)))
        args.update(changes)
        return prbody.build(**args)

    def test_snapshot(self):
        got = self.body()
        if os.environ.get("GLD_UPDATE_SNAPSHOT") == "1":
            os.makedirs(os.path.dirname(SNAP), exist_ok=True)
            with open(SNAP, "w", encoding="utf-8") as f:
                f.write(got)
        with open(SNAP, encoding="utf-8") as f:
            self.assertEqual(got, f.read())

    def test_order_of_the_sections(self):
        b = self.body()
        order = ["**인수 기준 (AC)**", "**이슈 요구 ↔ AC 대응표**", "**가정과 검토할 결정**", "**검증 범위**",
                 "**로컬에서 확인하지 않은 항목**", "**Manual Test Checklist**", "**범위 밖 발견**",
                 "**범위 밖이지만 포함한 수정**", "**측정용 사실 경고**"]
        pos = [b.index(h) for h in order]
        self.assertEqual(pos, sorted(pos))
        self.assertTrue(b.startswith("**인수 기준 (AC)**"), "the AC list comes first (I1, §7.2-6)")

    def test_engine_text_has_no_hash_headings_and_no_closing_line(self):
        b = self.body()
        self.assertFalse([ln for ln in b.splitlines() if ln.lstrip().startswith("#")])
        self.assertEqual(outbound.find_close_keywords(b), [])
        self.assertNotIn("Closes", b)

    def test_facts_drive_the_review_list(self):
        b = self.body()
        self.assertIn("major 지적 (review-design): `src/settings.ts:12`", b)
        self.assertNotIn("naming", b, "minor findings are not listed")
        self.assertIn("바뀐 검증 경로: `test/settings_test.dart`", b)
        self.assertIn("불안정(flaky) 표시: `test` 시도 1", b)
        self.assertIn("거절된 쓰기 (implement 시도 1): Write `/wt/.claude/agents/x.md`", b)
        self.assertNotIn("curl", b)
        self.assertIn("머지 뒤 되돌리기 어려운 변경 (hard-to-revert, notify): `db/migrations/007_quiz.sql`", b)
        self.assertIn("| `build` | `build` | 건너뜀 (not checked locally (Xcode in srt)) | — | — |", b)
        self.assertIn("| `test` | `test` | 통과 (종료 코드 0) | 2 |", b)
        self.assertEqual(b.count("old layout helper"), 1, "discoveries are de-duplicated across attempts")
        self.assertIn("**측정용 사실 경고**: 1건", b)

    def test_vw4_o1_a_flaky_net_proof_is_shown_as_passed_on_its_second_run(self):
        proc, state, fb, results, cfg, qa, analysis = copy.deepcopy(self.args)
        run = dict(green("lint"), head={"exit_code": 1, "timed_out": False, "log_file": "run-head.log"},
                   head_rerun={"exit_code": 0, "timed_out": False, "log_file": "run-head-rerun.log"}, head_flaky=True)
        fb["lint"] = facts("lint", 1, "run", run=run)
        b = prbody.build(proc, state, fb, results, cfg, qa, analysis)
        self.assertIn("불안정(flaky) 표시: `lint` 시도 1 — 판정 트리 `test`가 종료 코드 1로 통과하지 못한 뒤 같은 "
                      "트리 재실행에서 통과해 통과로 판정했습니다(K8-2와 같은 규칙). 첫 실행 로그 `run-head.log`", b)
        fb["lint"] = facts("lint", 1, "run", run=dict(run, head={"exit_code": None, "timed_out": True,
                                                                  "log_file": "run-head.log"}))
        self.assertIn("`test`가 시간 초과로 통과하지 못한 뒤", prbody.build(proc, state, fb, results, cfg, qa, analysis))
        for old in (dict(run, head_flaky=False), {k: v for k, v in run.items() if k != "head_flaky"}):
            fb["lint"] = facts("lint", 1, "run", run=old)
            self.assertNotIn("`lint` 시도 1 — 판정 트리", prbody.build(proc, state, fb, results, cfg, qa, analysis))

    def test_role_text_is_neutralised_by_the_outbound_layer(self):
        b = outbound.neutralise(self.body(), "acme/app")
        self.assertNotIn("@alice", b)
        self.assertNotIn("#12", b)

    def test_fail_closed(self):
        proc, state, fb, results, cfg, qa, analysis = copy.deepcopy(self.args)
        st = copy.deepcopy(state)
        next(s for s in st["steps"] if s["id"] == "qa")["status"] = "needs_human"
        with self.assertRaises(prbody.PrBodyError):
            self.body(state=st)
        bad = copy.deepcopy(fb)
        bad["lint"]["run"]["exit_code"] = 1
        with self.assertRaises(prbody.PrBodyError):
            self.body(facts_by_step=bad)
        bad = copy.deepcopy(fb)
        bad["lint"]["end_tree"] = {"clean": False, "dirty_files": ["x"]}
        with self.assertRaises(prbody.PrBodyError):
            self.body(facts_by_step=bad)
        bad = copy.deepcopy(fb)
        del bad["lint"]
        with self.assertRaises(prbody.PrBodyError):
            self.body(facts_by_step=bad)
        for q in (None, "", "  \n"):
            with self.assertRaises(prbody.PrBodyError):
                self.body(qa_checklist=q)
        with self.assertRaises(prbody.PrBodyError):
            self.body(analysis="no acceptance criteria here")

    def test_warning_count_falls_back_to_the_facts(self):
        st = copy.deepcopy(self.args[1])
        del st["totals"]
        self.assertIn("**측정용 사실 경고**: 1건", self.body(state=st))


# --- stage 2 (V11) ---------------------------------------------------------------------------------

def scenario2(answer="approve"):
    """The stage-1 scenario plus a `check: done-gate` step before the PR, the leader's done-gate answer
    and the state.leader_calls the engine would have recorded."""
    proc, state, fb, results, cfg, qa, analysis = scenario()
    raw = proc.to_json()
    raw["steps"].insert(len(raw["steps"]) - 1, {"id": "done-gate", "check": "done-gate"})
    proc = procedure.Procedure(raw)
    state = copy.deepcopy(state)
    rows = {s["id"]: s for s in state["steps"]}
    rows["done-gate"] = {"id": "done-gate", "status": "done", "latest_attempt": 1}
    state["steps"] = [rows[i] for i in proc.step_ids]
    state["leader_calls"] = [
        {"kind": "check", "k": 1, "sessions": [1], "situation": "plan-gate", "step": None, "answer": "plan",
         "reason": "fits-template", "cost_usd": 0.41, "counted": False, "failed": None},
        {"kind": "leader", "k": 1, "sessions": [1], "situation": "blocked", "step": "implement", "answer": "rerun",
         "reason": "real-defect", "cost_usd": 0.22, "counted": True, "failed": None},
        {"kind": "check", "k": 1, "sessions": [1], "situation": "done-gate", "step": None, "answer": answer,
         "reason": "acceptance-met", "cost_usd": 1.1, "counted": False, "failed": None}]
    results = copy.deepcopy(results)
    results["done-gate"] = {
        "answer": answer, "reason": "acceptance-met", "step": None, "recommendation": None,
        "note": "All four criteria hold.\nSecond line @bob #99 must not show.",
        "ac_verdicts": [
            {"ac": 1, "status": "met", "evidence": "settings.ts adds the row; test/settings_test.dart covers it"},
            {"ac": 2, "status": "met", "evidence": "same sheet | reused @alice"},
            {"ac": 3, "status": "manual", "evidence": "visual check, see the checklist"},
            {"ac": 4, "status": "met", "evidence": "restart test"}],
        "discoveries": [{"id": "D1", "disposition": "followup"}, {"id": "D2", "disposition": "ignore"},
                        {"id": "D3", "disposition": "followup"}, {"id": "D4", "disposition": "followup"}]}
    leader = {
        "discoveries": [
            {"id": "D1", "kind": "bug", "where": "lib/review_screen.dart", "blocks_current_ac": False,
             "role": "auditor", "note": "select-all ignores #12 @alice"},
            {"id": "D2", "kind": "debt", "where": "lib/settings.dart", "blocks_current_ac": False,
             "role": "developer", "note": "old layout helper"},
            {"id": "D3", "kind": "security", "where": "lib/auth.dart", "blocks_current_ac": False,
             "role": "auditor", "note": "token logged in debug builds"},
            {"id": "D4", "kind": "test-gap", "where": "test/sheet_test.dart", "blocks_current_ac": False,
             "role": "auditor", "note": "the sheet had no test"}],
        "notes": {"leader:blocked:1": "Rerun implement: the sheet is copied, not reused.\nmore"}}
    return proc, state, fb, results, cfg, qa, analysis, leader


class LeaderBody(unittest.TestCase):
    def body(self, answer="approve", leader=True, public_repo=False, mutate=None):
        proc, state, fb, results, cfg, qa, analysis, lead = scenario2(answer)
        if mutate:
            mutate(proc, state, fb, results, lead)
        return prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead if leader else None,
                            public_repo=public_repo)

    def test_snapshot(self):
        got = self.body()
        if os.environ.get("GLD_UPDATE_SNAPSHOT") == "1":
            os.makedirs(os.path.dirname(SNAP2), exist_ok=True)
            with open(SNAP2, "w", encoding="utf-8") as f:
                f.write(got)
        with open(SNAP2, encoding="utf-8") as f:
            self.assertEqual(got, f.read())

    def test_stage1_body_is_unchanged_without_stage2_input(self):
        proc, state, fb, results, cfg, qa, analysis = scenario()
        old = prbody.build(proc, state, fb, results, cfg, qa, analysis)
        new = prbody.build(proc, state, fb, results, cfg, qa, analysis, leader={}, public_repo=None)
        self.assertEqual(old, new)
        for h in ("인수 기준 판정", "리더 결정"):
            self.assertNotIn(h, old)

    def test_sections_come_after_the_stage1_ones(self):
        b = self.body()
        order = ["**범위 밖이지만 포함한 수정**", "**인수 기준 판정 (리더)**", "**리더 결정**", "**측정용 사실 경고**"]
        pos = [b.index(h) for h in order]
        self.assertEqual(pos, sorted(pos))
        self.assertTrue(b.startswith("**인수 기준 (AC)**"))
        self.assertFalse([ln for ln in b.splitlines() if ln.lstrip().startswith("#")])
        self.assertEqual(outbound.find_close_keywords(b), [])

    def test_ac_verdict_table(self):
        b = self.body()
        self.assertIn("리더(LLM)가 쓴 판정입니다 — 엔진이 확인한 사실이 아닙니다", b)
        self.assertIn("| AC #1 | met | settings.ts adds the row; test/settings_test.dart covers it |", b)
        self.assertIn("| AC #2 | met | same sheet \\| reused @alice |", b)
        self.assertIn("| AC #3 | manual (수동 확인) | visual check, see the checklist |", b)
        self.assertNotIn("`approve`가 아닙니다", b)

    def test_decision_list(self):
        b = self.body()
        self.assertIn("- check#1 `plan-gate`: `plan` · 이유 `fits-template`\n", b)
        self.assertIn("- leader#1 `blocked`: `rerun` → `implement` · 이유 `real-defect` — "
                      "Rerun implement: the sheet is copied, not reused.\n", b)
        # the last done-gate call takes its note from the done-gate result; only the FIRST line
        self.assertIn("`done-gate`: `approve` · 이유 `acceptance-met` — All four criteria hold.\n", b)
        self.assertNotIn("Second line", b)

    def test_discovery_dispositions(self):
        b = self.body()
        self.assertIn("- [후속 이슈 후보 — 2단계는 만들지 않음] D1 · bug · `lib/review_screen.dart`", b)
        self.assertIn("- [무시한 발견] D2 · debt · `lib/settings.dart` — old layout helper", b)
        inc = b[b.index("**범위 밖이지만 포함한 수정**"):b.index("**인수 기준 판정 (리더)**")]
        self.assertIn("(없음)", inc)

    def test_include_and_unjudged_discoveries(self):
        def mutate(proc, state, fb, results, lead):
            results["done-gate"]["discoveries"][3]["disposition"] = "include"     # a human-approved escalate
            del results["done-gate"]["discoveries"][0]                            # D1 has no disposition
            lead["discoveries"][1]["blocks_current_ac"] = True                    # D2 ignored although it blocks
        b = self.body(mutate=mutate)
        inc = b[b.index("**범위 밖이지만 포함한 수정**"):b.index("**인수 기준 판정 (리더)**")]
        self.assertIn("D4 · test-gap", inc)
        self.assertNotIn("D2", inc, "the leader's explicit `ignore` wins over the role's blocks_current_ac")
        self.assertIn("- [리더 판정 없음] D1 · bug", b)
        self.assertIn("- [무시한 발견] D2 · debt", b)

    def test_security_discovery_is_withheld_unless_the_repository_is_private(self):
        for public in (None, True):
            b = self.body(public_repo=public)
            self.assertNotIn("token logged", b)
            self.assertNotIn("lib/auth.dart", b)
        self.assertIn("D3 · security · `lib/auth.dart`", self.body(public_repo=False))

        def add_security(proc, state, fb, results, lead):
            results["review-audit"]["discoveries"].append(
                {"kind": "security", "where": "lib/x.dart", "note": "leaky", "blocks_current_ac": False})
            lead.pop("discoveries")
        # without the engine-numbered list the role results are listed — the rule still holds
        self.assertNotIn("leaky", self.body(public_repo=None, mutate=add_security))
        self.assertIn("leaky", self.body(public_repo=False, mutate=add_security))

    def test_the_leader_answer_is_not_listed_as_a_role_discovery(self):
        b = self.body(mutate=lambda proc, state, fb, results, lead: lead.pop("discoveries"))
        sec = b[b.index("**범위 밖 발견**"):b.index("**범위 밖이지만 포함한 수정**")]
        self.assertNotIn("None", sec)
        self.assertNotIn("followup", sec)
        self.assertIn("lib/review_screen.dart", sec)

    def test_human_approval_after_an_escalate_is_stated(self):
        def esc(proc, state, fb, results, lead):
            results["done-gate"].update(answer="escalate", reason="needs-human-decision")
            state["leader_calls"][-1].update(answer="escalate", reason="needs-human-decision")
        b = self.body(mutate=esc)
        self.assertIn("`escalate`(이유 `needs-human-decision`)로 답한 것이며 `approve`가 아닙니다. "
                      "이 PR은 사람이 승인해 진행했습니다.", b)
        self.assertIn("| AC #1 | met |", b)

    def test_missing_or_malformed_leader_answer_never_blocks_or_invents(self):
        for bad in (None, {"note": "no answer field"}, {"answer": "approve", "ac_verdicts": "x"}):
            def put(proc, state, fb, results, lead, bad=bad):
                if bad is None:
                    del results["done-gate"]
                else:
                    results["done-gate"] = bad
            b = self.body(mutate=put)
            self.assertIn("리더의 AC 판정이 기록되지 않았습니다", b)
            self.assertNotIn("| AC #1 |", b.split("**인수 기준 판정 (리더)**")[1])

    def test_ac_without_a_verdict_is_shown(self):
        def drop(proc, state, fb, results, lead):
            results["done-gate"]["ac_verdicts"] = results["done-gate"]["ac_verdicts"][:2]
        b = self.body(mutate=drop)
        self.assertIn("| AC #3 | (판정 없음) | — |", b)
        self.assertIn("| AC #4 | (판정 없음) | — |", b)

    def test_failed_call_is_listed(self):
        def fail(proc, state, fb, results, lead):
            state["leader_calls"][1].update(answer=None, reason=None, step=None, failed="output-format")
        self.assertIn("`blocked`: 답 없음 (리더 실패: `output-format`)", self.body(mutate=fail))

    def test_long_leader_text_is_cut(self):
        def long(proc, state, fb, results, lead):
            results["done-gate"]["ac_verdicts"][0]["evidence"] = "e " * 1000
            lead["notes"]["leader:blocked:1"] = "n" * 1000
        b = self.body(mutate=long)
        row = next(ln for ln in b.splitlines() if ln.startswith("| AC #1 | met"))
        self.assertLessEqual(len(row), prbody.EVIDENCE_MAX + 30)
        self.assertTrue(row.endswith("… |"))
        line = next(ln for ln in b.splitlines() if ln.startswith("- leader#1"))
        self.assertLessEqual(len(line), prbody.NOTE_MAX + 80)

    def test_leader_text_is_neutralised_by_the_outbound_layer(self):
        b = outbound.neutralise(self.body(), "acme/app")
        for raw in ("@alice", "@bob", "#12", "#99"):
            self.assertNotIn(raw, b)

    def test_an_unfinished_done_gate_still_refuses_the_body(self):
        def red(proc, state, fb, results, lead):
            next(s for s in state["steps"] if s["id"] == "done-gate")["status"] = "needs_human"
        with self.assertRaises(prbody.PrBodyError):
            self.body(mutate=red)

    def test_no_leader_calls_means_no_decision_list(self):
        b = self.body(mutate=lambda proc, state, fb, results, lead: state.pop("leader_calls"))
        self.assertNotIn("**리더 결정**", b)
        self.assertIn("**인수 기준 판정 (리더)**", b)   # the procedure has a done-gate step


class LeaderNoteKeys(unittest.TestCase):
    """VW4 E3: a check call's k is counted per check step, so plan-gate check#1 and done-gate check#1 shared
    the note key and the done-gate note was printed on the plan-gate line (PR #1987, and #1984 of VW2).
    The fixture is the leader_calls of the VW4 #1938 state and the three leader results, cut."""
    FIXTURE = os.path.join(ENGINE, "tests", "fixtures", "prbody", "vw4-1938")
    STEPS = [("plan", "check", "plan-gate"), ("safety-net", "role", "developer"), ("done-gate", "check", "done-gate")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ep = pathsmod.EnginePaths(os.path.realpath(self._tmp.name), "owner/app_a", 1938)
        shutil.copytree(os.path.join(self.FIXTURE, "runs"), ep.runs)
        with open(os.path.join(self.FIXTURE, "state.json"), encoding="utf-8") as f:
            self.state = json.load(f)
        self.proc = SimpleNamespace(steps=[SimpleNamespace(id=i, kind=k, name=n) for i, k, n in self.STEPS])
        self.env = SimpleNamespace(state=self.state, proc=self.proc, paths=ep)
        self.result = {}
        for step, n in (("plan", 1), ("done-gate", 1), ("done-gate", 2)):
            with open(ep.attempt_file(step, n, "result.json"), encoding="utf-8") as f:
                self.result[(step, n)] = json.load(f)

    def first(self, step, n):
        return prbody._first_line(self.result[(step, n)]["note"])

    def lines(self, notes, results_by_step=None):
        return prbody._decision_lines(self.state, results_by_step or {}, self.proc, notes)

    def test_the_keys_name_the_situation(self):
        notes = driver._leader_notes(self.env)
        self.assertEqual(notes, {"check:plan-gate:1": self.result[("plan", 1)]["note"],
                                 "check:done-gate:1": self.result[("done-gate", 1)]["note"],
                                 "check:done-gate:2": self.result[("done-gate", 2)]["note"]})
        self.assertEqual([prbody.leader_note_key(c) for c in self.state["leader_calls"]], list(notes))

    @fixes_defect("E3", "silent @ driver._leader_notes")
    def test_e3_each_line_gets_its_own_note(self):
        plan, dg1, dg2 = self.lines(driver._leader_notes(self.env))
        self.assertEqual(plan, f"- check#1 `plan-gate`: `plan` · 이유 `fits-template` — {self.first('plan', 1)}")
        self.assertNotIn(self.first("done-gate", 1), plan)
        self.assertEqual(dg1, "- check#1 `done-gate`: `rerun` → `safety-net` · 이유 `real-defect` — "
                         + self.first("done-gate", 1))
        self.assertEqual(dg2, f"- check#2 `done-gate`: `approve` · 이유 `acceptance-met` — {self.first('done-gate', 2)}")

    def test_old_keys_leave_the_note_out_rather_than_guess(self):
        """A notes dict in the old "<kind>:<k>" form cannot say which call it was: it is not read. Only the
        LAST call of a situation still gets the latest result of its check step (the old fallback)."""
        old = {"check:1": self.result[("done-gate", 1)]["note"], "check:2": self.result[("done-gate", 2)]["note"]}
        latest = {"plan": self.result[("plan", 1)],
                  "done-gate": [self.result[("done-gate", 1)], self.result[("done-gate", 2)]]}
        plan, dg1, dg2 = self.lines(old, latest)
        self.assertTrue(plan.endswith(f"— {self.first('plan', 1)}"), plan)
        self.assertEqual(dg1, "- check#1 `done-gate`: `rerun` → `safety-net` · 이유 `real-defect`")
        self.assertTrue(dg2.endswith(f"— {self.first('done-gate', 2)}"), dg2)
        plan, dg1, dg2 = self.lines(old)
        self.assertEqual(plan, "- check#1 `plan-gate`: `plan` · 이유 `fits-template`")
        self.assertNotIn("—", dg1 + dg2)

    def test_a_result_that_cannot_be_read_leaves_that_note_out(self):
        os.unlink(self.env.paths.attempt_file("plan", 1, "result.json"))
        with open(self.env.paths.attempt_file("done-gate", 1, "result.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        notes = driver._leader_notes(self.env)
        self.assertEqual(list(notes), ["check:done-gate:2"])
        plan, dg1, _ = self.lines(notes)
        self.assertEqual(plan, "- check#1 `plan-gate`: `plan` · 이유 `fits-template`")
        self.assertEqual(dg1, "- check#1 `done-gate`: `rerun` → `safety-net` · 이유 `real-defect`")


class SummaryLines(unittest.TestCase):
    def test_empty_when_there_is_nothing(self):
        self.assertEqual(prbody.summary_leader_lines({"steps": []}), [])
        self.assertEqual(prbody.summary_leader_lines({}), [])

    def test_decisions_waiting_recommendation_failure(self):
        calls = scenario2()[1]["leader_calls"]
        self.assertEqual(prbody.summary_leader_lines({"leader_calls": calls}), [
            "- leader `plan-gate`: `plan` (reason `fits-template`)",
            "- leader `blocked`: `rerun` → `implement` (reason `real-defect`)",
            "- leader `done-gate`: `approve` (reason `acceptance-met`)"])
        waiting = {"stop": {"status": "needs_leader", "reason": "blocked", "step": "design"}}
        self.assertEqual(prbody.summary_leader_lines(waiting), ["- waiting for the leader: `blocked` at `design`"])
        rec = {"stop": {"status": "needs_human", "reason": "blocked", "step": "design",
                        "recommendation": {"answer": "rerun", "step": "design", "note": "free text",
                                           "reason": "needs-human-decision"},
                        "leader_failed": {"code": "output-format", "detail": "plan-with-gap"}}}
        lines = prbody.summary_leader_lines(rec)
        self.assertEqual(lines, ["- leader recommends `rerun` → `design` (reason `needs-human-decision`)",
                                 "- leader failed: `output-format` (plan-with-gap)"])
        self.assertNotIn("free text", "\n".join(lines))     # the recommendation note stays out of the summary

    def test_security_count_follows_the_visibility_rule(self):
        idx = [{"kind": "security"}, {"kind": "bug"}, {"kind": "security"}]
        self.assertEqual(prbody.security_discovery_count(idx), 2)
        self.assertEqual(prbody.summary_leader_lines({}, 2, None),
                         ["- withheld security discoveries: 2 (public repository — tell the owner)"])
        self.assertEqual(prbody.summary_leader_lines({}, 2, True), prbody.summary_leader_lines({}, 2, None))
        self.assertEqual(prbody.summary_leader_lines({}, 2, False), [])
        self.assertEqual(prbody.summary_leader_lines({}, 0, None), [])

    def test_no_hash_and_no_at(self):
        lines = prbody.summary_leader_lines(scenario2()[1], 1, None)
        self.assertFalse([ln for ln in lines if "#" in ln or "@" in ln])


# --- stage 3 (V8, V16) ------------------------------------------------------------------------------

def answer3(**over):
    """A stage-3 done-gate answer for scenario2's four discoveries."""
    disc = [{"id": "D1", "disposition": "followup", "title": "Select-all ignores #12", "duplicate_of": None},
            {"id": "D2", "disposition": "ignore", "title": None, "duplicate_of": None},
            {"id": "D3", "disposition": "followup", "title": "Token in debug logs", "duplicate_of": None},
            {"id": "D4", "disposition": "duplicate", "title": None, "duplicate_of": 77}]
    return dict({"answer": "approve", "reason": "acceptance-met", "step": None, "recommendation": None,
                 "note": "Ship it.", "discoveries": disc, "included_fixes": []}, **over)


def scenario3(answer=None):
    proc, state, fb, results, cfg, qa, analysis, lead = scenario2()
    results["done-gate"] = dict(results["done-gate"], **(answer or answer3()))
    return proc, state, fb, results, cfg, qa, analysis, lead


SECRET_TEXT = "token logged in debug builds"


class FollowupItems(unittest.TestCase):
    """V8: prbody.followup_items / bodies / security record (E19–E21) — pure."""

    def items(self, is_private=True, answer=None):
        lead = scenario2()[-1]
        return prbody.followup_items(ISSUE, 7, lead["discoveries"], answer or answer3(), is_private=is_private)

    def test_items_of_a_private_repository(self):
        got = self.items()
        self.assertEqual([(i["source"], i["disposition"], i["private_path"]) for i in got],
                         [("D1", "followup", False), ("D3", "followup", False), ("D4", "duplicate", False)])
        d1, d3, d4 = got
        self.assertEqual((d1["title"], d1["labels"], d1["type_label"]),
                         ("Select-all ignores #12", ["guild:followup"], "type:bug"))
        self.assertEqual(d3["labels"], ["guild:followup", "guild:security"])
        self.assertEqual((d4["target"], d4["title"], d4["labels"]), (77, None, []))
        self.assertRegex(d1["key"], r"^D1:[0-9a-f]{8}$")
        self.assertEqual([i["key"] for i in got], [i["key"] for i in self.items()], "stable keys")
        self.assertIn("- 원래 이슈: #42", d1["body"])
        self.assertIn("- PR: #7", d1["body"])
        self.assertIn("select-all ignores #12 @alice", d1["body"])
        self.assertIn("Ship it.", d1["body"])
        self.assertIn("the sheet had no test", d4["body"])
        for i in got:
            self.assertFalse([ln for ln in i["body"].splitlines() if ln.lstrip().startswith("#")])

    def test_security_goes_the_private_path_unless_known_private(self):
        for vis in (None, False):
            got = {i["source"]: i for i in self.items(is_private=vis)}
            self.assertTrue(got["D3"]["private_path"])
            self.assertFalse(got["D1"]["private_path"])

    def test_tx1_free_text_changes_bodies_not_calls(self):
        a = self.items()
        other = answer3()
        other["discoveries"][0]["title"] = "completely different words"
        other["note"] = "another note"
        b = self.items(answer=other)
        shape = lambda xs: [(i["source"], i["disposition"], i["labels"], i["type_label"], i["target"],
                             i["private_path"], i["key"]) for i in xs]
        self.assertEqual(shape(a), shape(b))

    def test_fail_closed(self):
        for change in ({"title": None}, {"title": "  "}):
            ans = answer3()
            ans["discoveries"][0].update(change)
            with self.assertRaises(prbody.PrBodyError):
                self.items(answer=ans)
        ans = answer3()
        ans["discoveries"][3]["duplicate_of"] = None
        with self.assertRaises(prbody.PrBodyError):
            self.items(answer=ans)
        ans = answer3()
        ans["discoveries"].append({"id": "D9", "disposition": "followup", "title": "x", "duplicate_of": None})
        with self.assertRaises(prbody.PrBodyError):
            self.items(answer=ans)
        lead = scenario2()[-1]
        many = [dict(lead["discoveries"][0], id=f"D{n}") for n in range(1, 8)]
        ans = answer3(discoveries=[{"id": f"D{n}", "disposition": "followup", "title": "t", "duplicate_of": None}
                                   for n in range(1, 7)])
        with self.assertRaises(prbody.PrBodyError):
            prbody.followup_items(ISSUE, 7, many, ans, is_private=True)
        self.assertEqual(prbody.followup_items(ISSUE, 7, many, None, is_private=True), [])

    def test_security_findings_record(self):
        lead = scenario2()[-1]
        md = prbody.security_findings_md(ISSUE, lead["discoveries"], answer3(), is_private=None)
        self.assertIn("## D3 · auditor · lib/auth.dart", md)
        self.assertIn(SECRET_TEXT, md)
        self.assertIn("- disposition: followup", md)
        self.assertIn("nothing was written to GitHub", md)
        self.assertIsNone(prbody.security_findings_md(ISSUE, lead["discoveries"][:2]))


class Stage3Body(unittest.TestCase):
    def body(self, stage3, answer=None, leader=True):
        proc, state, fb, results, cfg, qa, analysis, lead = scenario3(answer)
        return prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead if leader else None,
                            public_repo=False, stage3=stage3)

    def test_e21_no_security_content_in_any_repository(self):
        for vis in (True, False, None):
            b = self.body({"is_private": vis, "dry_run": False, "followups": None})
            self.assertNotIn(SECRET_TEXT, b)
            self.assertNotIn("lib/auth.dart", b)
            self.assertIn("- 보안 발견 1건 — 내용은 PR 본문에 쓰지 않습니다", b)
        # stage 2 with a private repository still writes it (D27, unchanged)
        proc, state, fb, results, cfg, qa, analysis, lead = scenario3()
        self.assertIn(SECRET_TEXT, prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                                                public_repo=False))

    def test_e21_role_result_listing_withholds_security_too(self):
        def mut(proc, state, fb, results, lead):
            results["review-audit"]["discoveries"].append(
                {"kind": "security", "where": "lib/auth.dart", "note": SECRET_TEXT, "blocks_current_ac": True})
        proc, state, fb, results, cfg, qa, analysis = scenario()
        mut(proc, state, fb, results, None)
        b = prbody.build(proc, state, fb, results, cfg, qa, analysis, stage3={"is_private": True})
        self.assertNotIn(SECRET_TEXT, b)
        self.assertIn("- 보안 발견 1건", b)

    def test_stage3_template_without_qa_has_no_checklist(self):
        # Q7 #698: the safety-net template has no qa step, so there is no checklist to insert
        proc, state, fb, results, cfg, qa, analysis = scenario()
        raw = proc.to_json() if isinstance(proc, procedure.Procedure) else copy.deepcopy(proc)
        n = len(raw["steps"])
        raw["steps"] = [st for st in raw["steps"] if st.get("role") != "qa"]
        self.assertEqual(n - 1, len(raw["steps"]))
        no_qa = procedure.Procedure(raw)
        b = prbody.build(no_qa, state, fb, results, cfg, None, analysis, stage3={"is_private": True})
        self.assertIn("- 이 절차에는 qa 단계가 없습니다", b)
        # a procedure with a qa step still refuses an empty checklist, in stage 3 too
        with self.assertRaises(prbody.PrBodyError):
            prbody.build(proc, state, fb, results, cfg, "", analysis, stage3={"is_private": True})
        # stage 2 keeps refusing even without a qa step
        with self.assertRaises(prbody.PrBodyError):
            prbody.build(no_qa, state, fb, results, cfg, None, analysis)

    def test_followup_section_before_the_op_ran(self):
        b = self.body({"is_private": True, "dry_run": False, "followups": None})
        sec = b.split("**분리한 후속 이슈**")[1].split("**측정용")[0]
        self.assertIn("`create-followups` 단계가 처리합니다: 후속 이슈 2건 · 중복 댓글 1건", sec)
        self.assertIn("- [후속 이슈] D1 · bug", b)
        self.assertIn("- [중복] D4 · test-gap", b)
        self.assertIn("(dry-run — 만들지 않음)", self.body({"is_private": True, "dry_run": True, "followups": None}))
        self.assertIn("후속 이슈 1건 · 중복 댓글 1건 · 보안 발견 1건은 엔진 로컬 기록만",
                      self.body({"is_private": None, "dry_run": False, "followups": None}))

    def test_followup_section_after_the_op(self):
        lead = scenario2()[-1]
        items = prbody.followup_items(ISSUE, 7, lead["discoveries"], answer3(), is_private=True)
        rows = [{"key": items[0]["key"], "kind": "bug", "disposition": "followup", "number": 90, "comment_id": None,
                 "dry_run": False, "private_path": False, "at": "x"},
                {"key": items[1]["key"], "kind": "security", "disposition": "followup", "number": 91,
                 "comment_id": None, "dry_run": False, "private_path": False, "at": "x"},
                {"key": items[2]["key"], "kind": "test-gap", "disposition": "duplicate", "number": 77,
                 "comment_id": 9101, "dry_run": False, "private_path": False, "at": "x"}]
        b = self.body({"is_private": True, "dry_run": False, "followups": rows})
        sec = b.split("**분리한 후속 이슈**")[1].split("**측정용")[0]
        self.assertEqual([ln for ln in sec.splitlines() if ln.startswith("- ")], [
            "- D1 · bug → 후속 이슈 #90", "- 보안 후속 이슈 #91 — 내용은 이슈에서", "- D4 · test-gap → 기존 이슈 #77에 댓글"])
        self.assertIn("- 보안 후속 이슈 #91 — 내용은 이슈에서", b.split("**검증 범위**")[0], "in 가정과 검토할 결정")
        self.assertIn("- [후속 이슈 #90] D1 · bug", b)
        self.assertIn("- [중복 — 기존 이슈 #77에 댓글] D4", b)
        self.assertNotIn(SECRET_TEXT, b)

    def test_followup_section_dry_run_and_private_path(self):
        rows = [{"key": "D1:00000000", "kind": "bug", "disposition": "followup", "number": None, "comment_id": None,
                 "dry_run": True, "private_path": False, "at": "x"},
                {"key": "D4:00000000", "kind": "test-gap", "disposition": "duplicate", "number": None,
                 "comment_id": None, "dry_run": True, "private_path": False, "at": "x"},
                {"key": "D3:00000000", "kind": "security", "disposition": "followup", "number": None,
                 "comment_id": None, "dry_run": True, "private_path": True, "at": "x"}]
        b = self.body({"is_private": None, "dry_run": True, "followups": rows})
        sec = b.split("**분리한 후속 이슈**")[1].split("**측정용")[0]
        self.assertIn("- dry-run — 만들지 않음: 후속 이슈 1건 · 중복 댓글 1건", sec)
        self.assertIn("- 보안 발견 1건 — 비공개로 확인되지 않은 저장소라 GitHub에 쓰지 않았습니다", sec)
        self.assertNotIn("#", sec.replace("**", ""))

    def test_stage3_without_anything_to_show_adds_no_followup_section(self):
        ans = answer3(discoveries=[{"id": d, "disposition": "ignore", "title": None, "duplicate_of": None}
                                   for d in ("D1", "D2", "D3", "D4")])
        self.assertNotIn("분리한 후속 이슈", self.body({"is_private": True, "followups": None}, answer=ans))
        self.assertNotIn("분리한 후속 이슈", self.body({"is_private": True, "followups": []}, answer=ans))


def fold(body, title):
    """The content of the stage-4 `<details>` whose summary starts with `title` (AssertionError when there is none)."""
    start = body.index(f"<summary>{title}")
    return body[start:body.index("</details>", start)]


def rr(code, timed_out=False, log="x.log"):
    return {"exit_code": code, "timed_out": timed_out, "log_file": log}


def scenario_bug():
    """scenario3 with the bug template's evidence steps (reproduce · repro-red before implement), the
    engine's irreversible detection, an included fix F1 and the template-candidate mark."""
    proc, state, fb, results, cfg, qa, analysis, lead = scenario3()
    raw = proc.to_json()
    at = next(i for i, st in enumerate(raw["steps"]) if st["id"] == "implement")
    raw["steps"][at:at] = [{"id": "reproduce", "role": "developer", "inputs": [], "outputs": ["test/**"]},
                           {"id": "repro-red", "run": "repro-red"}]
    raw["new_template_candidate"] = True
    proc = procedure.Procedure(raw)
    rows = {r["id"]: r for r in state["steps"]}
    rows["reproduce"] = {"id": "reproduce", "status": "done", "latest_attempt": 1}
    rows["repro-red"] = {"id": "repro-red", "status": "done", "latest_attempt": 2}
    state["steps"] = [rows[i] for i in proc.step_ids]
    red = dict(green("repro-red"), head=rr(1, log="run-head.log"), head_rerun=rr(1, log="run-head-rerun.log"),
               base_run=rr(0, log="run-base.log"), evidence={
                   "kind": "repro-red", "globs": ["test/**"],
                   "scope": {"ok": True, "step": "reproduce", "attempts": [1], "outside": []},
                   "overlay": {"base_sha": SHA["a"], "head_sha": SHA["b"], "existed": [],
                               "files": [{"path": "test/settings_test.dart", "blob": SHA["d"], "base_blob": None}]},
                   "end_tree": {"clean": True, "dirty_files": []}})
    fb["repro-red"] = [facts("repro-red", 1, "run", run=dict(red, exit_code=1, head=rr(0))),
                       facts("repro-red", 2, "run", run=red)]
    fb["reproduce"] = facts("reproduce", 1, "role", denials=[])
    state["irreversible"] = {"approved": [
        {"category": "external-side-effect", "code": None, "path": "deploy/app.yaml", "at": "2026-11-25T01:00:00Z",
         "who": "human"}], "detected": [
        {"category": "hard-to-revert", "level": "notify", "default_level": "notify", "lowered": False,
         "source": "path-rule", "code": None, "path": "db/migrations/007_quiz.sql", "step": "implement", "attempt": 1},
        {"category": "hard-to-revert", "level": "notify", "default_level": "notify", "lowered": False,
         "source": "path-rule", "code": None, "path": "db/migrations/007_quiz.sql", "step": "verify-gate", "attempt": 1},
        {"category": "external-side-effect", "level": "human-decision", "default_level": "human-decision",
         "lowered": False, "source": "path-rule", "code": None, "path": "deploy/app.yaml", "step": "implement",
         "attempt": 1},
        {"category": "human-executed", "level": "proceed", "default_level": "notify", "lowered": True,
         "source": "role-code", "code": "migration-file", "path": None, "step": "implement", "attempt": 1}]}
    state["included_fixes"] = [
        {"id": "F1", "from_step": "design", "from_attempt": 1, "role": "tech-lead", "kind": "bug",
         "where": "lib/sheet.dart", "note": "blocks AC 2 @bob", "handled_by": "implement", "verdict": None},
        {"id": "F2", "from_step": "review-audit", "from_attempt": 1, "role": "auditor", "kind": "security",
         "where": "lib/auth.dart", "note": SECRET_TEXT, "handled_by": "fix-discovery", "verdict": None}]
    results["done-gate"]["included_fixes"] = [{"id": "F1", "verdict": "keep"}, {"id": "F2", "verdict": "keep"}]
    state["github"] = {"pr_number": 7, "is_private": True}
    return proc, state, fb, results, cfg, qa, analysis, lead


class Stage3Sections(unittest.TestCase):
    """V16: repro evidence, irreversible levels, included fixes, template candidate, summary lines."""

    def body(self, mutate=None, followups=None):
        proc, state, fb, results, cfg, qa, analysis, lead = scenario_bug()
        if mutate:
            mutate(proc, state, fb, results, lead)
        return prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                            stage3={"is_private": True, "dry_run": False, "followups": followups})

    def test_snapshot(self):
        got = self.body()
        if os.environ.get("GLD_UPDATE_SNAPSHOT") == "1":
            with open(SNAP3, "w", encoding="utf-8") as f:
                f.write(got)
        with open(SNAP3, encoding="utf-8") as f:
            self.assertEqual(got, f.read())

    def test_order_and_shape(self):
        b = self.body()
        order = ["**인수 기준 (AC)**", "**가정과 검토할 결정**", "**범위 밖이지만 포함한 수정**", "**리더 결정**",
                 "**분리한 후속 이슈**", "**재현 증거 (버그)**", "**새 템플릿 후보**", "**측정용 사실 경고**"]
        pos = [b.index(h) for h in order]
        self.assertEqual(pos, sorted(pos))
        self.assertFalse([ln for ln in b.splitlines() if ln.lstrip().startswith("#")])
        self.assertEqual(outbound.find_close_keywords(b), [])
        self.assertNotIn(SECRET_TEXT, b)

    def test_repro_evidence_is_the_latest_facts(self):
        sec = self.body().split("**재현 증거 (버그)**")[1].split("**새 템플릿")[0]
        for row in ("| 판정 트리 `test` 1회 (빨강이어야 함) | 종료 코드 1 |", "| 판정 트리 `test` 2회 (빨강이어야 함) | 종료 코드 1 |",
                    "| 기록 base `test` (녹색이어야 함) | 종료 코드 0 |", "| 판정 트리에 올린 파일 | `test/settings_test.dart` |",
                    "| 최종 `test` (수정 뒤 HEAD `cccccccccccc`) | 종료 코드 0 |"):
            self.assertIn(row, sec)
        self.assertIn("의 변경이 test-code glob 안) | 통과 |", sec)

    def test_no_repro_section_without_a_repro_red_step(self):
        self.assertNotIn("재현 증거", Stage3Body().body({"is_private": True, "followups": None}))

    def test_irreversible_levels_and_lowered(self):
        review = self.body().split("**가정과 검토할 결정**")[1].split("**검증 범위**")[0]
        lines = [ln for ln in review.splitlines() if "되돌리기" in ln or "낮춘" in ln]
        self.assertEqual(lines, [
            "- 되돌리기 어려운 변경 (hard-to-revert, notify): `db/migrations/007_quiz.sql` (implement)",
            "- 되돌리기 어려운 변경 (external-side-effect, human-decision): `deploy/app.yaml` (implement) — 사람 승인 "
            "2026-11-25T01:00:00Z",
            "- 저장소 설정이 기본보다 낮춘 수준: human-executed 기본 notify → proceed"])
        self.assertNotIn("머지 뒤 되돌리기 어려운 변경", review, "the stage-1 path-rule lines are replaced")

    def test_without_recorded_detection_the_path_rule_lines_stay(self):
        def mut(proc, state, fb, results, lead):
            del state["irreversible"]
        self.assertIn("- 머지 뒤 되돌리기 어려운 변경 (hard-to-revert, notify): `db/migrations/007_quiz.sql`",
                      self.body(mut))

    def test_included_fixes(self):
        sec = self.body().split("**범위 밖이지만 포함한 수정**")[1].split("**인수 기준 판정")[0]
        self.assertIn("- F1 · bug · `lib/sheet.dart` — blocks AC 2 @bob (발견 tech-lead/design, 처리 implement, "
                      "리더 판정 keep)", sec)
        self.assertIn("- F2 · security — 내용은 쓰지 않습니다(E21) (발견 auditor/review-audit, 처리 fix-discovery, "
                      "리더 판정 keep)", sec)

    def test_template_candidate_line_only_when_marked(self):
        def mut(proc, state, fb, results, lead):
            proc.new_template_candidate = None
        self.assertNotIn("새 템플릿 후보", self.body(mut))


class Stage4Sections(unittest.TestCase):
    """VB8: the stack block, the files a human allowed, the mutation facts (stage-4 scope §2.4, §2.10, VB9)."""

    RECORD = {"format": 1, "issue": ISSUE, "head": "c" * 40, "blob": "d" * 40, "problem": None,
              "control": {"exit_code": 0, "timed_out": False, "log_file": "try-1/control.log"},
              "rows": [
                  {"id": "M1", "acs": [1, 2], "path": "lib/sheet.dart", "find": "hint: `on` | x\n", "replace": "",
                   "note": "SECRET NOTE", "status": "killed", "detail": None,
                   "run": {"exit_code": 1, "timed_out": False, "log_file": "try-1/m1.log"}, "log_tail": "OUTPUT @bob"},
                  {"id": "M2", "acs": [2], "path": "test/a_test.dart", "find": "a" * 200, "replace": "b", "note": "",
                   "status": "refused", "detail": "verification-path", "run": None, "log_tail": ""},
                  {"id": "M3", "acs": [2], "path": "lib/b.dart", "find": "b", "replace": "c", "note": "",
                   "status": "survived", "detail": None,
                   "run": {"exit_code": 0, "timed_out": False, "log_file": "try-1/m3.log"}, "log_tail": ""}],
              "at": "2026-11-25T01:02:03Z"}
    STACK = {"issue": 101, "tracker": 700, "draft": True}

    SUMMARY = ["lib/settings.dart adds the quiz-type row and keeps the choice across restarts.",
               "test/settings_test.dart covers the row and the restart; #12 @bob stays plain text."]

    def body(self, stage4=None, stage3=True, mutate=None, summary=None):
        proc, state, fb, results, cfg, qa, analysis, lead = scenario_bug()
        if mutate:
            mutate(state, fb)
        if summary is not None:
            results["done-gate"]["summary"] = summary
        return prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                            stage3={"is_private": True, "dry_run": False, "followups": None} if stage3 else None, stage4=stage4)

    def test_snapshot(self):
        got = self.body({"stack": self.STACK, "allowed_test_changes": ["test/settings_test.dart", "test/x.dart"],
                         "mutations": self.RECORD}, summary=self.SUMMARY)
        if os.environ.get("GLD_UPDATE_SNAPSHOT") == "1":
            with open(SNAP4, "w", encoding="utf-8") as f:
                f.write(got)
        with open(SNAP4, encoding="utf-8") as f:
            self.assertEqual(got, f.read())

    def test_without_stage4_it_is_the_stage_3_body(self):
        """None keeps the stage-3 body; any stage-4 dict, even one with nothing of its own, is the stage-4 layout."""
        plain = self.body(stage3=True)
        self.assertEqual(self.body(None), plain)
        empty = self.body({})
        self.assertEqual(self.body({"stack": None, "allowed_test_changes": [], "mutations": None}), empty)
        self.assertNotEqual(empty, plain)
        self.assertTrue(empty.startswith(prbody.STAGE4_SUMMARY_HEADING))

    def test_the_stack_block_comes_first_and_has_the_markers(self):
        b = self.body({"stack": self.STACK})
        self.assertTrue(b.startswith(defaults.SPRINT_STACK_MARKER + "\n"))
        block = b[:b.index(defaults.SPRINT_STACK_MARKER_END)]
        self.assertIn("스택: 이 PR은 #101 위에 있다 — 먼저 머지할 것", block)
        self.assertIn("(스프린트 #700)", block)
        self.assertIn("draft", block)
        ready = self.body({"stack": dict(self.STACK, draft=False, tracker=None)})
        self.assertNotIn("draft", ready[:ready.index(defaults.SPRINT_STACK_MARKER_END)])
        self.assertNotIn("스프린트 #", ready)

    def test_the_markers_survive_the_neutraliser(self):
        """stack_sync.py finds the block in the PR body GitHub has; the Issue number is full width there."""
        b = outbound.neutralise(self.body({"stack": self.STACK}), "acme/app")
        self.assertIn(defaults.SPRINT_STACK_MARKER, b)
        self.assertIn(defaults.SPRINT_STACK_MARKER_END, b)
        self.assertIn("＃101", b)

    def test_allowed_files_are_decisions_to_review(self):
        review = self.body({"allowed_test_changes": ["test/none_test.dart"]}).split("**가정과 검토할 결정**")[1].split("**범위 밖 발견**")[0]
        self.assertIn("- 사람이 허용한 기존 테스트 수정(내용만): `test/none_test.dart` — 이 PR에서 바뀌지 않았습니다", review)
        self.assertIn("`test/settings_test.dart` — 이 PR에서 바뀌었습니다",
                      self.body({"allowed_test_changes": ["test/settings_test.dart"]}))

    def test_the_mutation_table(self):
        sec = fold(self.body({"mutations": self.RECORD}), "뮤테이션 실행")
        self.assertIn("대조 실행(변경 없음): 종료 코드 0", sec)
        self.assertIn("| M1 | 1, 2 | `lib/sheet.dart` | `hint: 'on' \\| x` | (없음) | killed — 테스트가 빨강, 종료 코드 1 |", sec)
        self.assertIn("refused — 실행 안 함 (`verification-path`) |", sec)
        self.assertIn("survived — 테스트가 녹색 그대로(증거 아님), 종료 코드 0 |", sec)
        self.assertNotIn("a" * 100, sec)
        self.assertNotIn("OUTPUT", sec, "the run output never reaches the PR")
        self.assertNotIn("SECRET NOTE", sec)
        self.assertEqual(len({ln.replace("\\|", "").count("|") for ln in sec.splitlines() if ln.startswith("| M")}), 1)

    def test_a_flaky_control_and_a_second_run(self):
        """VW2 E1: the control red, then green on the same tree; a kill after it was red twice."""
        run = {"exit_code": 1, "timed_out": False, "log_file": "x"}
        rec = dict(self.RECORD, control=dict(run, again=dict(run, exit_code=0), flaky=True),
                   rows=[dict(self.RECORD["rows"][0], again=run)])
        sec = fold(self.body({"mutations": rec}), "뮤테이션 실행")
        self.assertIn("대조 실행(변경 없음): 종료 코드 1, 같은 트리에서 다시: 종료 코드 0 — 흔들림(빨강 뒤 녹색)", sec)
        self.assertIn("killed — 테스트가 빨강, 종료 코드 1, 다시 종료 코드 1 |", sec)
        red_twice = dict(rec, control=dict(run, again=run, flaky=False))
        sec = self.body({"mutations": red_twice})
        self.assertIn("같은 트리에서 다시: 종료 코드 1\n", sec)
        self.assertNotIn("흔들림", sec)

    def test_a_bad_declaration(self):
        sec = self.body({"mutations": dict(self.RECORD, problem="bad-file", control=None, rows=[])})
        self.assertIn("- `mutations.json`을 쓸 수 없어 실행하지 않았습니다 (`bad-file`)", sec)

    def test_every_status_has_its_words(self):
        self.assertEqual(set(prbody._MUTATION_STATUS), set(codes.MutationStatus.values()))


class Deferred(unittest.TestCase):
    """[P2] V12 (E30): PR "미룬 요구" below the AC list and one follow-up Issue for the deferred rows."""
    ROWS = [{"row": "R3", "text": "Also on Android 14 @x", "at": "t"}, {"row": "R5", "text": "dark mode", "at": "t"}]

    def test_pr_section_right_below_the_ac_list(self):
        proc, state, fb, results, cfg, qa, analysis, lead = scenario3()
        state["deferred_rows"] = self.ROWS
        b = prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                         stage3={"is_private": True, "followups": None})
        self.assertLess(b.index("**인수 기준 (AC)**"), b.index("**미룬 요구**"))
        self.assertLess(b.index("**미룬 요구**"), b.index("**이슈 요구 ↔ AC 대응표**"))
        self.assertIn("- R3: Also on Android 14 @x", b)
        self.assertIn("· 미룬 요구 묶음 1건", b)
        self.assertNotIn("미룬 요구", prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead),
                         "stage 2 never shows it")

    def test_one_item_for_all_rows(self):
        lead = scenario2()[-1]
        items = prbody.followup_items(ISSUE, 7, lead["discoveries"], None, is_private=True, deferred_rows=self.ROWS)
        [it] = items
        self.assertEqual((it["source"], it["kind"], it["type_label"], it["labels"]),
                         ("deferred", "deferred-requirement", "type:feature", ["guild:followup"]))
        self.assertRegex(it["key"], r"^deferred:[0-9a-f]{8}$")
        self.assertEqual(it["title"], "미룬 요구 — Issue 42 (R3, R5)")
        self.assertIn("- R5: dark mode", it["body"])
        ans = answer3(discoveries=[{"id": f"D{n}", "disposition": "followup", "title": "t", "duplicate_of": None}
                                   for n in range(1, 5)])
        self.assertEqual(len(prbody.followup_items(ISSUE, 7, lead["discoveries"], ans, is_private=True,
                                                   deferred_rows=self.ROWS)), 5)

    def test_section_after_the_op(self):
        proc, state, fb, results, cfg, qa, analysis, lead = scenario3()
        state["deferred_rows"] = self.ROWS
        rows = [{"key": "deferred:00000000", "kind": "deferred-requirement", "disposition": "followup", "number": 95,
                 "comment_id": None, "dry_run": False, "private_path": False, "at": "x"}]
        b = prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                         stage3={"is_private": True, "followups": rows})
        self.assertIn("- 미룬 요구 → 후속 이슈 #95", b)


class DismissedSection(unittest.TestCase):
    """[P2] V13 (E32): the PR lists a human's dismissal of a review's blockers."""

    def test_section(self):
        proc, state, fb, results, cfg, qa, analysis, lead = scenario_bug()
        state["dismissed"] = [{"step": "review-audit", "attempt": 2, "head": SHA["c"], "findings": ["blocker: x @a"],
                               "reason": "Intended: the old API stays.", "who": "human", "at": "2026-11-25T02:00:00Z"}]
        b = prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                         stage3={"is_private": True, "followups": None})
        sec = b.split("**사람이 기각한 지적**")[1].split("**재현 증거")[0]
        self.assertIn("- `review-audit` 시도 2 (HEAD `cccccccccccc`, 2026-11-25T02:00:00Z) — 이유: Intended: the old "
                      "API stays.", sec)
        self.assertIn("  - blocker: x @a", sec)
        self.assertNotIn("사람이 기각한 지적", Stage3Sections().body())


class GoldenLedger(unittest.TestCase):
    """[P2] V14 (E33): the "시각 변경" table from facts and the C row as a decision to review."""

    def test_table_and_config_row(self):
        proc, state, fb, results, cfg, qa, analysis, lead = scenario_bug()
        fb["verify-gate"]["golden"] = [
            {"row": "M", "path": "test/goldens/a.png", "from": None, "old_blob": SHA["a"], "new_blob": SHA["b"],
             "reason": "bug-fix"},
            {"row": "R", "path": "test/goldens/b2.png", "from": "test/goldens/b.png", "old_blob": SHA["c"],
             "new_blob": SHA["c"], "reason": None},
            {"row": "C", "path": "test/flutter_test_config.dart", "from": None, "old_blob": SHA["d"],
             "new_blob": SHA["e"], "reason": "intended-change"}]
        b = prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                         stage3={"is_private": True, "followups": None})
        sec = b.split("**시각 변경**")[1].split("**재현 증거")[0]
        self.assertIn("| M | `test/goldens/a.png` | — | bug-fix |", sec)
        self.assertIn("| R | `test/goldens/b2.png` | `test/goldens/b.png` | (없음) |", sec)
        review = b.split("**가정과 검토할 결정**")[1].split("**검증 범위**")[0]
        self.assertIn("- 비교 설정 변경 (C): `test/flutter_test_config.dart`", review)
        self.assertNotIn("시각 변경", Stage3Sections().body())


class SummaryStage3(unittest.TestCase):
    def test_lines(self):
        state = scenario_bug()[1]
        state["followups"] = [
            {"key": "D1:00000000", "kind": "bug", "disposition": "followup", "number": 90, "dry_run": False,
             "private_path": False},
            {"key": "D4:00000000", "kind": "test-gap", "disposition": "duplicate", "number": 77, "dry_run": False,
             "private_path": False}]
        lines = prbody.summary_stage3_lines(state, security_count=1)
        self.assertEqual(lines, [
            "- hard to revert (hard-to-revert, notify): `db/migrations/007_quiz.sql` (implement)",
            "- hard to revert (external-side-effect, human-decision): `deploy/app.yaml` (implement) — approved by a "
            "human 2026-11-25T01:00:00Z",
            "- level lowered by the repository settings: human-executed default notify → proceed",
            "- security discoveries: 1 (content only in follow-up issues of this private repository)",
            "- follow-ups: 1 created, 1 commented"])
        self.assertFalse([ln for ln in lines if "#" in ln or "@" in ln])

    def test_public_and_dry_run(self):
        state = {"issue": 42, "github": {"is_private": None}, "followups": [
            {"key": "D1:00000000", "disposition": "followup", "dry_run": True, "private_path": False},
            {"key": "D3:00000000", "disposition": "followup", "dry_run": True, "private_path": True}]}
        self.assertEqual(prbody.summary_stage3_lines(state, security_count=2), [
            "- public repository — 2 security discoveries, see `/gld status 42`",
            "- follow-ups (dry run — not created): 1"])
        self.assertEqual(prbody.summary_stage3_lines({}), [])


class Title(unittest.TestCase):
    def test_title(self):
        self.assertEqual(prbody.title("  복습 문제 유형을\n설정 화면에서도 선택 ", 1797), "복습 문제 유형을 설정 화면에서도 선택")
        self.assertEqual(prbody.title("", 7), "Issue 7")
        self.assertEqual(len(prbody.title("x" * 500, 7)), prbody.TITLE_MAX)
        with self.assertRaises(prbody.PrBodyError):
            prbody.title("", 0)


if __name__ == "__main__":
    unittest.main()
