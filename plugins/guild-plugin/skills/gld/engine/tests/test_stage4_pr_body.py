"""Stage-4 PR body layout (R2 6단계): a reviewer reads 「무엇을 바꿨나」, 「사람이 확인할 것」 and the assumptions /
out-of-scope sections first; every other section is folded in `<details>`. Nothing of the flat body is dropped and
every marker another reader looks for stays.

  * Layout       — order, folds, markers (stack block for stack_sync.py, `<!-- guild:manual-qa -->` for /gld qa)
  * NoLineLost   — the stage-4 body holds exactly the flat body's lines, but for the folded sections' bold heading
                   lines (their <summary> names them), the checklist heading and the added summary / fold lines.
                   The flat arrangement of the same parts is what the stage-3 layout joins (prbody._stage4_layout
                   replaced by a join).
  * Summary      — the done-gate leader's `summary` (labelled as the leader's), else three engine-fact lines;
                   the leader check: at most three lines, none blank, approve at least one
  * Vw4          — the real VW4 #1938 inputs (tests/fixtures/prbody/vw4-1938/inputs.json: what prbody read for
                   PR #1987, rebuilt from the archived records) → body.md
"""

import collections
import json
import os
import unittest
from unittest import mock

from gxengine import codes, defaults, outbound, prbody, procedure, repoconfig
from tests import test_leader_stage3 as L3
from tests import test_prbody as TP

VW4 = os.path.join(TP.ENGINE, "tests", "fixtures", "prbody", "vw4-1938")
VW4_SNAP = os.path.join(VW4, "body.md")
F = codes.LeaderFormatReason
QA = ("<!-- guild:manual-qa -->\n## Manual Test Checklist\nOnly what automated tests cannot verify:\n"
      "- [ ] Open settings on a phone → the quiz type row is shown (AC #3)\n<!-- /guild:manual-qa -->\n")


def bug_body(stage4, summary=None, qa=QA, mutate=None):
    proc, state, fb, results, cfg, _, analysis, lead = TP.scenario_bug()
    if summary is not None:
        results["done-gate"]["summary"] = summary
    state["deferred_rows"] = [{"row": "R9", "text": "export the list"}]
    state["dismissed"] = [{"step": "review", "attempt": 2, "head": "c" * 40, "at": "2026-11-25T01:00:00Z",
                           "reason": "not this Issue", "findings": ["x is slow"]}]
    if mutate:
        mutate(proc, state, fb, results)
    return prbody.build(proc, state, fb, results, cfg, qa, analysis, leader=lead,
                        stage3={"is_private": True, "dry_run": False, "followups": None}, stage4=stage4)


FULL = {"stack": TP.Stage4Sections.STACK, "allowed_test_changes": ["test/settings_test.dart"],
        "mutations": TP.Stage4Sections.RECORD}


def vw4_inputs():
    with open(os.path.join(VW4, "inputs.json"), encoding="utf-8") as f:
        return json.load(f)


def vw4_body(x=None, flat=False):
    x = x or vw4_inputs()
    cfg = repoconfig.RepoConfig(x["config"])
    proc = procedure.parse_procedure(x["procedure_yaml"], commands=cfg.command_names(), stage=4)
    build = lambda: prbody.build(proc, x["state"], x["facts_by_step"], x["results_by_step"], cfg, None, x["analysis"],
                                 leader=x["leader"], public_repo=x["public_repo"], stage3=x["stage3"], stage4=x["stage4"])
    if not flat:
        return build()
    with mock.patch.object(prbody, "_stage4_layout", lambda parts, summary, labels: [l for _, ls in parts for l in ls]):
        return build()


def top(body):
    return body[:body.index(prbody.STAGE4_FOLD_HEADING)]


class Layout(unittest.TestCase):
    def test_top_then_folds(self):
        b = bug_body(FULL, summary=["one", "two"])
        self.assertTrue(b.startswith(defaults.SPRINT_STACK_MARKER + "\n"))
        heads = [defaults.SPRINT_STACK_MARKER_END, prbody.STAGE4_SUMMARY_HEADING, prbody.STAGE4_CHECKLIST_HEADING,
                 "**가정과 검토할 결정**", "**미룬 요구**", "**범위 밖 발견**", "**분리한 후속 이슈**",
                 "**범위 밖이지만 포함한 수정**", prbody.STAGE4_FOLD_HEADING]
        self.assertEqual([b.index(h) for h in heads], sorted(b.index(h) for h in heads))
        folds = [ln[len("<summary>"):].split(" — ")[0].split("</summary>")[0] for ln in b.splitlines()
                 if ln.startswith("<summary>")]
        self.assertEqual(folds, ["인수 기준 (AC)", "인수 기준 판정 (리더)", "이슈 요구 ↔ AC 대응표", "검증 범위", "재현 증거 (버그)",
                                 "뮤테이션 실행", "로컬에서 확인하지 않은 항목", "리더 결정", "사람이 기각한 지적",
                                 "새 템플릿 후보", "엔진 기록"])
        self.assertNotIn("<details>", top(b))
        for t in ("인수 기준 (AC)", "검증 범위", "리더 결정", "인수 기준 판정 (리더)"):
            self.assertNotIn(f"**{t}**", b, "a folded section's heading is its <summary>")

    def test_the_follow_ups_the_engine_filed_are_open(self):
        """Q11 (user decision 2026-11-28): the engine files every recommended follow-up without asking — the Issue
        numbers it made and the existing Issues it commented on stand open, right below the out-of-scope findings."""
        made = [{"key": "D1:x", "disposition": "followup", "kind": "test-gap", "number": 77},
                {"key": "D2:y", "disposition": "duplicate", "kind": "bug", "number": 12},
                {"key": "deferred:z", "disposition": "followup", "kind": None, "number": 78}]
        proc, state, fb, results, cfg, _, analysis, lead = TP.scenario_bug()
        state["deferred_rows"] = [{"row": "R9", "text": "export the list"}]
        lead["discoveries"] = [dict(d, id=f"D{i}") for i, d in enumerate(
            [{"kind": "test-gap", "where": "a.py", "note": "n1"}, {"kind": "bug", "where": "b.py", "note": "n2"}], 1)]
        results["done-gate"]["discoveries"] = [{"id": "D1", "disposition": "followup", "title": "t1"},
                                               {"id": "D2", "disposition": "duplicate", "issue": 12}]
        b = prbody.build(proc, state, fb, results, cfg, QA, analysis, leader=lead,
                         stage3={"is_private": True, "dry_run": False, "followups": made}, stage4=FULL)
        t = top(b)
        for ln in ("**분리한 후속 이슈**", "- D1 · test-gap → 후속 이슈 #77", "- D2 · bug → 기존 이슈 #12에 댓글",
                   "- 미룬 요구 → 후속 이슈 #78"):
            self.assertIn(ln, t)
        self.assertLess(t.index("**범위 밖 발견**"), t.index("**분리한 후속 이슈**"))
        self.assertNotIn("<summary>분리한 후속 이슈", b, "not folded")

    def test_every_fold_is_closed_and_renders_markdown(self):
        lines = bug_body(FULL).splitlines()
        opens = [i for i, ln in enumerate(lines) if ln == "<details>"]
        closes = [i for i, ln in enumerate(lines) if ln == "</details>"]
        self.assertEqual(len(opens), len(closes))
        for o, c in zip(opens, closes):
            self.assertLess(o, c)
            self.assertTrue(lines[o + 1].startswith("<summary>") and lines[o + 1].endswith("</summary>"))
            self.assertEqual((lines[o + 2], lines[c - 1]), ("", ""), "blank lines so GitHub renders the tables")
            self.assertFalse(any(ln in ("<details>", "</details>") for ln in lines[o + 1:c]), "no nesting")

    def test_counts_in_the_summaries(self):
        b = bug_body(FULL)
        self.assertIn("<summary>인수 기준 (AC) — 4개</summary>", b)
        self.assertIn("<summary>인수 기준 판정 (리더) — met 3 · manual 1</summary>", b)
        self.assertIn("<summary>리더 결정 — 3건</summary>", b)
        self.assertIn("<summary>엔진 기록 — 측정용 사실 경고 ", b)

    def test_markers_stay_where_their_readers_find_them(self):
        """stack_sync.py looks for the stack marker anywhere; /gld qa replaces the text between the manual-qa
        markers in place — one pair, open (not folded), under 「사람이 확인할 것」."""
        b = outbound.neutralise(bug_body(FULL), "acme/app")
        self.assertIn(defaults.SPRINT_STACK_MARKER, b)
        self.assertIn(defaults.SPRINT_STACK_MARKER_END, b)
        t = top(b)
        self.assertEqual((b.count("<!-- guild:manual-qa -->"), b.count("<!-- /guild:manual-qa -->")), (1, 1))
        self.assertLess(t.index(prbody.STAGE4_CHECKLIST_HEADING), t.index("<!-- guild:manual-qa -->"))
        self.assertLess(t.index("<!-- guild:manual-qa -->"), t.index("<!-- /guild:manual-qa -->"))
        self.assertEqual((b.count("<!-- guild:"), b.count("<!-- /guild:")), (2, 2))        # the stack and manual-qa pairs

    def test_without_a_qa_step_the_checklist_says_so(self):
        b = vw4_body()
        self.assertIn(prbody.STAGE4_CHECKLIST_HEADING + "\n\n- 이 절차에는 qa 단계가 없습니다(수동 확인 항목 없음).", b)

    def test_no_hash_headings_and_no_closing_line(self):
        b = bug_body(FULL)
        self.assertEqual([ln for ln in b.splitlines() if ln.startswith("#")], ["## Manual Test Checklist"])  # the qa text
        self.assertFalse([ln for ln in outbound.neutralise(b, "acme/app").splitlines() if ln.startswith("#")])
        self.assertNotIn("Closes", b)


def _counter(text):
    return collections.Counter(ln for ln in text.splitlines() if ln.strip())


class NoLineLost(unittest.TestCase):
    """The stage-4 body = the flat body's lines, rearranged; only headings and the summary / fold lines differ."""

    def check(self, flat, new):
        lost = _counter(flat) - _counter(new)
        added = _counter(new) - _counter(flat)
        folded_titles = {f"**{t}**" for t in prbody.FOLD_TITLES.values()}
        self.assertTrue(set(lost) <= folded_titles | {prbody.CHECKLIST_HEADING}, sorted(lost))
        self.assertTrue(all(n == 1 for n in lost.values()), lost)
        summary = new[new.index(prbody.STAGE4_SUMMARY_HEADING):new.index(prbody.STAGE4_CHECKLIST_HEADING)]
        allowed = _counter(summary) + collections.Counter(
            [prbody.STAGE4_CHECKLIST_HEADING, prbody.STAGE4_FOLD_HEADING])
        wrappers = {"<details>", "</details>"}
        extra = collections.Counter({k: v for k, v in added.items() if k not in wrappers and not k.startswith("<summary>")})
        self.assertEqual(extra - allowed, collections.Counter())
        self.assertEqual(added["<details>"], added["</details>"])
        self.assertEqual(added["<details>"], sum(1 for ln in new.splitlines() if ln.startswith("<summary>")))
        # every table row and list item of the flat body is in the new one, as often
        for ln, n in _counter(flat).items():
            if ln.startswith(("|", "- ")):
                self.assertEqual(_counter(new)[ln], n, ln)

    def test_bug_scenario_with_every_section(self):
        for summary in (None, ["what changed"]):
            with self.subTest(summary=summary):
                new = bug_body(FULL, summary=summary)
                with mock.patch.object(prbody, "_stage4_layout", lambda parts, s, labels: [l for _, ls in parts for l in ls]):
                    flat = bug_body(FULL, summary=summary)
                self.check(flat, new)
                self.assertIn("**뮤테이션 실행**", flat)
                self.assertIn("**사람이 기각한 지적**", flat)

    def test_vw4_1938(self):
        self.check(vw4_body(flat=True), vw4_body())

    def test_the_follow_up_section_moves_whole(self):
        """Q11: 「분리한 후속 이슈」 moved from the folds to the open top — every line of it, its heading included, is in
        the top part, exactly as often as in the flat body; nothing of it is left in a fold."""
        for new, flat in ((bug_body(FULL), self.flat_bug()), (vw4_body(), vw4_body(flat=True))):
            sec = flat[flat.index("**분리한 후속 이슈**"):]
            sec = sec[:sec.index("\n\n**")] if "\n\n**" in sec else sec
            lines = [ln for ln in sec.splitlines() if ln.strip()]
            self.assertGreater(len(lines), 1, sec)
            for ln in lines:
                self.assertEqual(top(new).count(ln), flat.count(ln), ln)

    @staticmethod
    def flat_bug():
        with mock.patch.object(prbody, "_stage4_layout", lambda parts, s, labels: [l for _, ls in parts for l in ls]):
            return bug_body(FULL)

    def test_the_flat_join_is_the_stage_3_body(self):
        """The mock above joins the parts as stages 1–3 do: with no stage-4 content it is the stage-3 body."""
        with mock.patch.object(prbody, "_stage4_layout", lambda parts, s, labels: [l for _, ls in parts for l in ls]):
            flat = bug_body({})
        self.assertEqual(flat, bug_body(None))

    def test_every_part_has_a_place(self):
        keys = {v for k, v in vars(prbody).items() if k.startswith("P_")}
        self.assertEqual(keys, set(prbody.STAGE4_TOP) | set(prbody.STAGE4_FOLDS) | {prbody.P_CHECKLIST})
        self.assertEqual(set(prbody.FOLD_TITLES), set(prbody.STAGE4_FOLDS))


class ReviewReadsTheBody(unittest.TestCase):
    """Q11: `/gld review` (commands/review.md) reads the engine's follow-up and out-of-scope-fix lines from the PR body.
    Every fragment it quotes is one prbody really writes — a renamed line here would leave review blind."""

    REVIEW = os.path.join(os.path.dirname(TP.ENGINE), "commands", "review.md")

    def setUp(self):
        with open(self.REVIEW, encoding="utf-8") as f:
            self.doc = f.read()

    def test_the_follow_up_lines(self):
        made = [{"key": "D1:x", "disposition": "followup", "kind": "test-gap", "number": 77},
                {"key": "D2:y", "disposition": "duplicate", "kind": "bug", "number": 12},
                {"key": "deferred:z", "disposition": "followup", "kind": None, "number": 78},
                {"key": "D3:s", "disposition": "followup", "kind": "security", "number": 79}]
        lines = prbody._followup_lines([], {}, made, False)
        self.assertEqual(lines, ["- D1 · test-gap → 후속 이슈 #77", "- D2 · bug → 기존 이슈 #12에 댓글",
                                 "- 미룬 요구 → 후속 이슈 #78", "- 보안 후속 이슈 #79 — 내용은 이슈에서"])
        for quoted in ("`→ 후속 이슈 #<n>`", "`미룬 요구 → 후속 이슈 #<n>`", "`보안 후속 이슈 #<n>`", "`→ 기존 이슈 #<c>에 댓글`"):
            self.assertIn(quoted, self.doc)
        before = prbody._followup_lines([{"id": "D1"}], {"D1": "followup"}, None, False)
        self.assertTrue(before[0].startswith("- 이 PR 뒤 `create-followups` 단계가 처리합니다"), before)
        self.assertIn("(`이 PR 뒤 \\`create-followups\\` 단계가 처리합니다…`)", self.doc)
        dry = prbody._followup_lines([], {}, [dict(made[0], dry_run=True, number=None)], True)
        self.assertTrue(dry[0].startswith("- dry-run — 만들지 않음"), dry)
        self.assertIn("(dry-run — 만들지 않음)", self.doc)

    def test_the_section_titles(self):
        b = bug_body(FULL)
        for title in ("분리한 후속 이슈", "범위 밖이지만 포함한 수정", "범위 밖 발견"):
            self.assertIn(f"**{title}**", top(b))
            self.assertIn(f"`{title}`", self.doc)
        self.assertIn("- F1 · bug · `lib/sheet.dart` — ", b, "the F/D line shape review.md quotes")
        self.assertIn("`- F<n> · <kind> · \\`<where>\\` — …`", self.doc)


class Summary(unittest.TestCase):
    def test_the_leaders_lines_on_top(self):
        b = bug_body(FULL, summary=["Adds the row in `lib/settings.dart`.", "  ", "x " * 400])
        s = b[b.index(prbody.STAGE4_SUMMARY_HEADING):b.index(prbody.STAGE4_CHECKLIST_HEADING)]
        self.assertIn("리더(LLM)가 diff를 읽고 쓴 요약입니다 — 엔진이 확인한 사실이 아닙니다.", s)
        self.assertIn("- Adds the row in `lib/settings.dart`.\n", s)
        self.assertEqual(len([ln for ln in s.splitlines() if ln.startswith("- ")]), 2, "a blank line is not shown")
        self.assertTrue(any(ln.endswith("…") and len(ln) <= prbody.SUMMARY_LINE_MAX + 2 for ln in s.splitlines()))
        self.assertIn("＃12 ＠bob", outbound.neutralise(bug_body(FULL, summary=["see #12 @bob"]), "acme/app"))

    def test_without_one_the_engine_facts(self):
        for summary in (None, []):
            b = bug_body(FULL, summary=summary)
            s = b[b.index(prbody.STAGE4_SUMMARY_HEADING):b.index(prbody.STAGE4_CHECKLIST_HEADING)]
            self.assertIn("리더 요약이 없어 엔진이 기록한 사실로 만든 요약입니다.", s)
            self.assertEqual(len([ln for ln in s.splitlines() if ln.startswith("- ")]), 3)
            self.assertIn("- 인수 기준 4개 — 리더 판정 met 3 · manual 1", s)
            self.assertNotIn("리더(LLM)", s)

    def test_a_human_approval_after_an_escalate_has_no_leader_verdict_count(self):
        def no_answer(proc, state, fb, results):
            results["done-gate"] = {"note": "not a leader answer"}
        b = bug_body({}, mutate=no_answer)
        self.assertIn("- 인수 기준 4개 — 리더 판정 없음", b)


class SummaryRule(L3.Stage3Case):
    def setUp(self):
        super().setUp()
        self.req = L3.dg_request(L3.dg_world(self.tmp))

    def test_one_to_three_lines(self):
        for lines, want in ((["a"], []), (["a", "b", "c"], []), ([], [F.SUMMARY_INVALID.value]),
                            (["a", "b", "c", "d"], [F.SUMMARY_INVALID.value]), (["a", " "], [F.SUMMARY_INVALID.value])):
            with self.subTest(lines=lines):
                self.assertEqual(self.check(self.req, L3.dg(summary=lines)), want)

    def test_a_rerun_may_have_none(self):
        self.assertEqual(self.check(self.req, L3.dg(answer="rerun", step="implement", reason="real-defect", summary=[])), [])
        self.assertEqual(self.check(self.req, L3.dg(answer="rerun", step="implement", reason="real-defect",
                                                    summary=list("abcd"))), [F.SUMMARY_INVALID.value])

    def test_required_by_the_schema_and_told_in_the_task(self):
        self.assertIn("summary", self.schema_of(self.req)["required"])
        answer = L3.dg()
        del answer["summary"]
        self.assertEqual(set(self.check(self.req, answer)), {F.ANSWER_SCHEMA.value})
        from gxengine import instructions
        self.assertIn("**Summary** (`summary`)", instructions.leader_task_text("done-gate", 4))
        self.assertNotIn("summary", instructions.leader_task_text("done-gate", 2))


class Vw4(unittest.TestCase):
    def test_snapshot(self):
        got = vw4_body()
        if os.environ.get("GLD_UPDATE_SNAPSHOT") == "1":
            with open(VW4_SNAP, "w", encoding="utf-8") as f:
                f.write(got)
        with open(VW4_SNAP, encoding="utf-8") as f:
            self.assertEqual(got, f.read())

    def test_the_inputs_are_the_real_pr_1987(self):
        """The flat body of the inputs is PR #1987's text as GitHub has it (neutralised), but for the E3 note fix of
        the plan-gate line (552f68c — the PR was made before it) and the closing line github.create_pr appends."""
        flat = outbound.neutralise(vw4_body(flat=True), "owner/app_a").splitlines()
        plan = [ln for ln in flat if ln.startswith("- check＃1 `plan-gate`")]
        self.assertEqual(len(plan), 1)
        self.assertIn("safety-net 템플릿으로 진행", plan[0])
        self.assertIn("**측정용 사실 경고**: 0건", flat)
        self.assertNotIn(".gld", json.dumps(vw4_inputs()))
        self.assertNotIn("/Users/", json.dumps(vw4_inputs()))

    def test_the_body_is_far_below_githubs_limit(self):
        """GitHub refuses a PR body over 65,536 characters; the engine has no cut of its own. The folds add only
        their wrapper lines."""
        new, flat = vw4_body(), vw4_body(flat=True)
        self.assertLess(len(new) - len(flat), 1200)
        self.assertLess(len(new), 65536 // 4)


if __name__ == "__main__":
    unittest.main()
