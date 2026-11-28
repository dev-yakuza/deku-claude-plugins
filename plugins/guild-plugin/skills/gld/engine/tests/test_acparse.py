"""acparse (U15, I6): one AC parser for ac-format and ac-coverage, fail-closed.

Scenario S13 — the 0.102.8 / 10 / 11 parser miss cases are fixed tests below
(`MissCases`). Everything runs on text or a temp directory; nothing is paid."""

import os
import re
import tempfile
import unittest

from gxengine import acparse
from gxengine.acparse import AcError

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "ac")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def analysis(ac_block, fields=None, extra=""):
    """A minimal valid analysis.md around `ac_block` (the AC section body)."""
    f = {"type": "feature", "size": "small", "risk": "low", "split": "none", "prerequisite": "none"}
    f.update(fields or {})
    head = "# Analysis — #5\n\n" + "".join(f"{k}: {v}\n" for k, v in f.items())
    return (head + "\n## Acceptance criteria\n\n" + ac_block + "\n\n## Requirement map\n\n"
            "| Requirement | AC |\n|---|---|\n| the thing | AC #1 |\n" + extra)


class SafetyNet(unittest.TestCase):
    """E3: the stage-3 machine field `safety_net`."""

    def parse(self, value, stage=3, **fields):
        return acparse.parse_analysis(analysis("- AC #1: a", dict(fields, **({} if value is None else {"safety_net": value}))),
                                      stage=stage)

    def test_values(self):
        for value in ("none", "with-refactor", "only"):
            for written in (value, f"**{value}**", f"`{value}`", f"{value} — because", f"{value.upper()} (note)"):
                self.assertEqual(self.parse(written, type="refactor")["safety_net"], value, written)
        for bad in ("", "yes", "with", "with_refactor", "with-refactors", "only-x"):
            with self.subTest(bad=bad), self.assertRaises(AcError):
                self.parse(bad, type="refactor")

    def test_missing_fails_from_stage_3_only(self):
        with self.assertRaises(AcError) as cm:
            self.parse(None)
        self.assertIn("safety_net", cm.exception.message)
        for stage in (1, 2):                                              # E36: not looked at, read as none
            self.assertEqual(self.parse(None, stage)["safety_net"], "none")
            self.assertEqual(self.parse("with-refactor", stage, type="refactor")["safety_net"], "none")
            self.assertEqual(self.parse("nonsense", stage)["safety_net"], "none")
        for bad in (0, True, "3"):
            with self.assertRaises(ValueError):
                self.parse(None, bad)

    def test_needs_type_refactor(self):
        """TY5."""
        for ty in ("feature", "bug", "docs", "chore"):
            for net in ("with-refactor", "only"):
                a = self.parse(net, type=ty)
                self.assertEqual(len(acparse.check_analysis(a, stage=3)), 1, (ty, net))
                self.assertEqual(acparse.check_analysis(a, stage=2), [])
            self.assertEqual(acparse.check_analysis(self.parse("none", type=ty), stage=3), [])
        self.assertEqual(acparse.check_analysis(self.parse("only", type="refactor"), stage=3), [])

    def test_fields_by_stage(self):
        self.assertEqual(acparse.machine_fields(2), acparse.MACHINE_FIELDS)
        self.assertEqual(acparse.machine_fields(3)[-1], "safety_net")


class Deferred(unittest.TestCase):
    """E30: `## 미룬 요구`, `(deferred R3)`, and the set the engine passes."""

    def parse(self, section="", stage=3, map_row=""):
        extra = map_row + ("\n" + section if section else "")
        return acparse.parse_analysis(analysis("- AC #1: a", {"safety_net": "none"}, extra=extra), stage=stage)

    def problems(self, rows, section="", map_row=""):
        return acparse.check_analysis(self.parse(section, map_row=map_row), stage=3, deferred=rows)

    def test_section(self):
        for title in ("미룬 요구", "미룬 요구사항", "Deferred requirements", "**Deferred requirement**:"):
            a = self.parse(f"## {title}\n\nMoved out of this Issue.\n\n- Export as CSV (deferred R3)\n"
                           "- Print the list,\n  also on A4 （deferred R5）\n")
            self.assertEqual(a["deferred"], [{"row": "R3", "text": "Export as CSV"},
                                             {"row": "R5", "text": "Print the list, also on A4"}], title)
        self.assertEqual(self.parse()["deferred"], [])

    def test_set_must_match(self):
        """TS1 · TS3."""
        sec = "## 미룬 요구\n\n- Export (deferred R3)\n"
        self.assertEqual(self.problems(["R3"], sec), [])
        self.assertEqual(self.problems([]), [])
        self.assertTrue(any("was not deferred" in p for p in self.problems([], sec)))
        self.assertTrue(any("R5 was deferred" in p for p in self.problems(["R3", "R5"], sec)))
        self.assertTrue(any("R3 was deferred" in p for p in self.problems(["R3"])))
        self.assertEqual(len(self.problems(["R4"], sec)), 2)

    def test_a_deferred_row_may_stay_in_the_map_without_an_ac(self):
        sec = "## 미룬 요구\n\n- Export (deferred R2)\n"
        a = self.parse(sec, map_row="| Export (deferred R2) | — |\n")
        self.assertEqual(a["requirement_map"], [("the thing", [1])])
        self.assertEqual(a["deferred_map"], [{"row": "R2", "text": "Export", "acs": []}])
        self.assertEqual(acparse.check_analysis(a, stage=3, deferred=["R2"]), [])
        self.assertTrue(any("still names an AC" in p for p in self.problems(["R2"], sec, "| Export (deferred R2) | AC #1 |\n")))
        self.assertTrue(self.problems(["R2"], sec, "| Print (deferred R7) | — |\n"))
        self.assertTrue(any("without an AC" in p for p in self.problems(["R2"], sec, "| Export | — |\n")))

    def test_malformed_is_an_error(self):
        for bad in ("- Export\n", "- Export (deferred)\n", "- Export (deferred 3)\n", "- Export (deferred R0)\n",
                    "- Export (deferred R3, R5)\n", "- Export (deferred R3) later\n", "- (deferred R3)\n",
                    "- Export (deferred R3) (deferred R4)\n", "- A (deferred R3)\n- B (deferred R3)\n",
                    "Export (deferred R3)\n", "| Export (deferred R3) |\n", "### Later\n\n- Export (deferred R3)\n"):
            with self.subTest(bad=bad), self.assertRaises(AcError):
                self.parse("## 미룬 요구\n\n" + bad)
        with self.assertRaises(AcError):
            self.parse(map_row="| Export (deferred R3) now | — |\n")

    def test_not_every_row(self):
        text = analysis("- AC #1: a", {"safety_net": "none"}).replace("| the thing | AC #1 |", "| the thing (deferred R1) | — |")
        with self.assertRaises(AcError):
            acparse.parse_analysis(text, stage=3)

    def test_earlier_stages_do_not_look(self):
        a = self.parse("## 미룬 요구\n\n- Export\n", stage=2, map_row="| Export (deferred R2) | — |\n")
        self.assertEqual((a["deferred"], a["deferred_map"]), ([], []))
        self.assertEqual(a["requirement_map"][1], ("Export (deferred R2)", []))

    def test_bad_arguments(self):
        a = self.parse()
        for rows, stage in ((["R1"], 2), (["R0"], 3), (["3"], 3), (["R1", "R1"], 3), ([1], 3)):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                acparse.check_analysis(a, stage=stage, deferred=rows)


class ParseAnalysis(unittest.TestCase):
    def test_fixture(self):
        a = acparse.parse_analysis(fixture("analysis-ok.md"))
        self.assertEqual(a["acs"], [1, 2, 3, 4])
        self.assertEqual((a["type"], a["size"], a["risk"]), ("feature", "small", "low"))
        self.assertFalse(a["split"])
        self.assertFalse(a["prerequisite_open"])
        self.assertEqual(a["requirement_map"], [
            ("Show the quiz type in settings", [1]),
            ("Reuse the selector sheet", [2, 3]),
            ("Keep the choice after restart", [4]),
        ])
        self.assertEqual(len(a["assumptions"]), 2)
        self.assertIn("selector sheet", a["ac_text"][2])
        self.assertIn("same as when opened", a["ac_text"][2])      # continuation line joined
        self.assertEqual(acparse.check_analysis(a), [])

    def test_real_0102_shapes(self):
        """Lines as the 0.102 analyze output wrote them (`- AC #n: … [must]`)."""
        body = ("- AC #1: 데스크탑 알림 행에 OS 권한 상태 배지가 표시된다. [must]\n"
                "- AC #2: 권한이 허용됨이 아닌 상태에서 'OS 알림 설정 열기' 버튼을 제공한다. [must]\n"
                "- AC #3: 조회는 화면 렌더를 막지 않는다(비동기). [should]")
        a = acparse.parse_analysis(analysis(body))
        self.assertEqual(a["acs"], [1, 2, 3])
        self.assertTrue(a["ac_text"][3].endswith("[should]"))

    def test_gap_is_a_problem(self):
        a = acparse.parse_analysis(analysis("- AC #1: a\n- AC #2: b\n- AC #4: d"))
        self.assertEqual(a["acs"], [1, 2, 4])
        self.assertTrue(any("without gaps" in p for p in acparse.check_analysis(a)))

    def test_numbered_list_items_and_bold_ids(self):
        a = acparse.parse_analysis(analysis("1. AC #1: a\n2. **AC #2**: b\n- **AC #3:** c"))
        self.assertEqual(a["acs"], [1, 2, 3])

    def test_id_spellings(self):
        a = acparse.parse_analysis(analysis("- AC#1: a\n- AC 2: b\n- AC-3. c"))
        self.assertEqual(a["acs"], [1, 2, 3])

    def test_korean_particle_after_the_id_is_fine(self):
        a = acparse.parse_analysis(analysis("- AC #1: a\n- AC #2: b\n\n설명: AC #1은 먼저 한다.") )
        self.assertEqual(a["acs"], [1, 2])

    def test_machine_fields(self):
        a = acparse.parse_analysis(analysis("- AC #1: a", {"type": "bug", "risk": "high", "size": "large",
                                                         "split": "proposed",
                                                         "prerequisite": "open — #540 is not done"}))
        self.assertEqual((a["type"], a["risk"], a["size"]), ("bug", "high", "large"))
        self.assertTrue(a["split"])
        self.assertTrue(a["prerequisite_open"])
        b = acparse.parse_analysis(analysis("- AC #1: a", {"prerequisite": "met"}))
        self.assertFalse(b["prerequisite_open"])

    def test_machine_fields_in_bullets_and_bold(self):
        text = analysis("- AC #1: a").replace("type: feature", "- **type**: Feature")
        self.assertEqual(acparse.parse_analysis(text)["type"], "feature")

    def test_missing_or_invalid_machine_field(self):
        text = analysis("- AC #1: a").replace("risk: low\n", "")
        with self.assertRaisesRegex(AcError, "missing machine field.*risk"):
            acparse.parse_analysis(text)
        for bad in ({"type": "epic"}, {"size": "huge"}, {"risk": "medium"}, {"split": "maybe"},
                    {"prerequisite": "unknown"}, {"type": ""}):
            with self.subTest(bad=bad), self.assertRaises(AcError):
                acparse.parse_analysis(analysis("- AC #1: a", bad))

    def test_conflicting_duplicate_field(self):
        text = analysis("- AC #1: a").replace("risk: low\n", "risk: low\nrisk: high\n")
        with self.assertRaisesRegex(AcError, "given twice"):
            acparse.parse_analysis(text)

    def test_fields_after_the_first_section_do_not_count(self):
        text = analysis("- AC #1: a\n\nrisk: high").replace("risk: low\n", "")
        with self.assertRaisesRegex(AcError, "missing machine field"):
            acparse.parse_analysis(text)

    def test_no_ac_section(self):
        text = "# A\n\ntype: feature\nsize: small\nrisk: low\nsplit: none\nprerequisite: none\n\n## Notes\n- x\n"
        with self.assertRaisesRegex(AcError, "no acceptance-criteria section"):
            acparse.parse_analysis(text)

    def test_empty_ac_section(self):
        with self.assertRaisesRegex(AcError, "defines no AC"):
            acparse.parse_analysis(analysis("Nothing here yet."))

    def test_empty_text(self):
        with self.assertRaises(AcError):
            acparse.parse_analysis("  \n")

    def test_duplicate_and_textless_ac(self):
        with self.assertRaisesRegex(AcError, "defined twice"):
            acparse.parse_analysis(analysis("- AC #1: a\n- AC #1: b"))
        with self.assertRaisesRegex(AcError, "has no text"):
            acparse.parse_analysis(analysis("- AC #1:\n- AC #2: b"))

    def test_malformed_ac_lines_fail_closed(self):
        for bad in ("- AC #1 is the first one", "- first requirement", "AC #1 a thing",
                    "| AC #1 | text |", "### AC #1", "- AC #1, #2: merged"):
            with self.subTest(bad=bad), self.assertRaises(AcError):
                acparse.parse_analysis(analysis("- AC #1: ok\n" + bad))

    def test_an_indented_ac_definition_is_not_silently_swallowed(self):
        """An AC indented 4+ spaces would read as a continuation of the previous one — and be lost."""
        for item in ("    - AC #4: indented under #3", "\t- AC #4: tab indented"):
            with self.subTest(item=item), self.assertRaisesRegex(AcError, "top-level list item"):
                acparse.parse_analysis(analysis("- AC #1: a\n- AC #2: b\n- AC #3: c\n" + item))

    def test_an_indented_definition_outside_the_section(self):
        with self.assertRaisesRegex(AcError, "outside the acceptance-criteria section"):
            acparse.parse_analysis(analysis("- AC #1: a", extra="\n## Notes\n\n    - AC #2: sneaked in\n"))

    def test_ac_definition_outside_the_section(self):
        with self.assertRaisesRegex(AcError, "outside the acceptance-criteria section"):
            acparse.parse_analysis(analysis("- AC #1: a", extra="\n## Notes\n\n- AC #2: sneaked in\n"))

    def test_unparseable_token_anywhere(self):
        for bad in ("AC #1a", "AC #x", "AC 3.1", "AC #1-3", "AC #0", "AC #1~#3", "AC #", "AC #99999"):
            with self.subTest(bad=bad), self.assertRaises(AcError):
                acparse.parse_analysis(analysis("- AC #1: a", extra=f"\n## Assumptions\n\n- see {bad}\n"))

    def test_code_fence_comment_and_quote_are_ignored(self):
        extra = ("\n## Assumptions\n\n- one\n\n```\n- AC #9: in a fence\nAC #x\n```\n\n"
                 "<!-- - AC #8: commented out -->\n\n> - AC #7: quoted from the issue\n")
        a = acparse.parse_analysis(analysis("- AC #1: a", extra=extra))
        self.assertEqual(a["acs"], [1])

    def test_unclosed_fence_or_comment_is_an_error(self):
        with self.assertRaisesRegex(AcError, "never closed"):
            acparse.parse_analysis(analysis("- AC #1: a", extra="\n```\n- AC #2: hidden\n"))
        with self.assertRaisesRegex(AcError, "never closed"):
            acparse.parse_analysis(analysis("- AC #1: a", extra="\n<!-- oops\n"))

    def test_requirement_map(self):
        text = analysis("- AC #1: a\n- AC #2: b")
        text = text.replace("| the thing | AC #1 |", "| first | AC #1 |\n| second | AC #1, #2 |\n| third | AC #3 |\n| fourth | — |")
        a = acparse.parse_analysis(text)
        problems = acparse.check_analysis(a)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("AC #3" in p for p in problems))
        self.assertTrue(any("fourth" in p for p in problems))

    def test_missing_or_empty_requirement_map(self):
        text = analysis("- AC #1: a").split("## Requirement map")[0]
        with self.assertRaisesRegex(AcError, "no requirement map"):
            acparse.parse_analysis(text)
        with self.assertRaisesRegex(AcError, "no rows"):
            acparse.parse_analysis(text + "## Requirement map\n\n| Requirement | AC |\n|---|---|\n")

    def test_korean_titles(self):
        text = (analysis("- AC #1: a").replace("## Acceptance criteria", "## 인수 기준")
                .replace("## Requirement map", "## 이슈 요구 ↔ AC 대응표"))
        self.assertEqual(acparse.parse_analysis(text)["acs"], [1])


class ParseTestCaseRefs(unittest.TestCase):
    def test_fixture(self):
        self.assertEqual(acparse.parse_test_case_refs(fixture("test-cases-ok.md")), {1, 2, 3, 4})

    def test_prose_mention_does_not_cover(self):
        self.assertEqual(acparse.parse_test_case_refs("AC #7 is split off to #1950.\n"), set())
        self.assertEqual(acparse.parse_test_case_refs("Note: AC #7 stays out of scope.\n- case [AC #2]\n"), {2})

    def test_unparseable_token_fails_closed(self):
        for bad in ("- case [AC #1a]", "- case [AC #1-3]", "- case (AC #x)", "Row: AC 2.5 here"):
            with self.subTest(bad=bad), self.assertRaises(AcError):
                acparse.parse_test_case_refs(bad)

    def test_backtick_legend_is_tolerated(self):
        self.assertEqual(acparse.parse_test_case_refs("Every case ends with `[AC #n]`.\n- c [AC #3]\n"), {3})

    def test_fence_comment_quote_are_ignored(self):
        text = "```\n- c [AC #9]\n```\n<!-- - c [AC #8] -->\n> - c [AC #7]\n- c [AC #1]\n"
        self.assertEqual(acparse.parse_test_case_refs(text), {1})

    def test_unclosed_fence(self):
        with self.assertRaises(AcError):
            acparse.parse_test_case_refs("```\n- c [AC #1]\n")

    def test_lists_need_their_own_hash(self):
        self.assertEqual(acparse.parse_test_case_refs("- c [AC #3, 2 cases]"), {3})
        self.assertEqual(acparse.parse_test_case_refs("- c (AC #3, 2 cases)"), {3})
        self.assertEqual(acparse.parse_test_case_refs("- c [AC #3, #4 and #5]"), {3, 4, 5})
        self.assertEqual(acparse.parse_test_case_refs("- c [AC #1·#5]"), {1, 5})
        self.assertEqual(acparse.parse_test_case_refs("- c [AC #2 / #3]"), {2, 3})
        self.assertEqual(acparse.parse_test_case_refs("- c [AC #2 및 #3]"), {2, 3})


def undefined_reference_shapes(text):
    """A stdlib stand-in for remark-lint-no-undefined-references on these fixtures: every
    `[...]` outside code that is not a link (`](`), a task checkbox or escaped."""
    out = []
    for line in acparse._clean_lines(text):
        s = re.sub(r"`[^`\n]*`", "", line[1])
        for m in re.finditer(r"(?<!\\)\[([^\[\]\n]*)\](?!\()", s):
            if m.group(1) not in (" ", "x", "X"):
                out.append((line[0], m.group(0)))
    return out


class ParenTags(unittest.TestCase):
    """P5 (app_a #1964): the written form is `(AC #2)` / `(must)` — square brackets broke
    the repository's markdown lint. The old `[AC #2]` / `[must]` is still read."""

    def test_written_form_fixtures(self):
        a = acparse.parse_analysis(fixture("analysis-paren.md"))
        self.assertEqual(a["acs"], [1, 2, 3, 4])
        self.assertTrue(a["ac_text"][4].endswith("(should)"))
        self.assertTrue(a["ac_text"][3].endswith("(no extra tap). (must)"))
        self.assertEqual(acparse.check_analysis(a), [])
        self.assertEqual(acparse.parse_test_case_refs(fixture("test-cases-paren.md")), {1, 2, 3, 4})

    def test_written_form_has_no_undefined_reference_shapes(self):
        for name in ("analysis-paren.md", "test-cases-paren.md"):
            with self.subTest(name=name):
                self.assertEqual(undefined_reference_shapes(fixture(name)), [])
        # the stand-in does see what the lint saw in the old form
        self.assertEqual(len(undefined_reference_shapes(fixture("test-cases-ok.md"))), 5)
        self.assertEqual(len(undefined_reference_shapes(fixture("analysis-ok.md"))), 4)

    def test_tag_at_the_end(self):
        refs = acparse.parse_test_case_refs
        self.assertEqual(refs("- C3: tapping the row opens the sheet. (AC #2)"), {2})
        self.assertEqual(refs("- C3: tapping the row opens the sheet (AC #2)."), {2})
        self.assertEqual(refs("- C3: opens the sheet. (AC #2, #5)"), {2, 5})
        self.assertEqual(refs("- C3: opens the sheet. **(AC #2)**  "), {2})
        self.assertEqual(refs("- C3: opens the sheet. (AC #2) (AC #5)"), {2, 5})
        self.assertEqual(refs("- C3: opens the sheet. （AC #2）"), {2})
        self.assertEqual(refs("1. C3: opens the sheet. (AC #2)"), {2})
        self.assertEqual(refs("- C3: opens the sheet. \\[AC #2]"), {2})       # lint-escaped old form

    def test_tag_at_the_start_after_a_case_id(self):
        refs = acparse.parse_test_case_refs
        self.assertEqual(refs("- C1 (AC #1): the row is found."), {1})
        self.assertEqual(refs("- (AC #1) the row is found."), {1})
        self.assertEqual(refs("- TC-12: (AC #1) the row is found."), {1})
        self.assertEqual(refs("- [ ] C1 (AC #1) the row is found."), {1})

    def test_tag_with_a_label(self):
        """0.102.10 (#1945) testers wrote a case kind into the tag: `- E3 [AC #1, 엣지] …`."""
        refs = acparse.parse_test_case_refs
        self.assertEqual(refs("- E3 [AC #1, 엣지] 세 언어의 키 집합이 동일하다."), {1})
        self.assertEqual(refs("- E5 (AC #5, 실패 경로) 표의 리터럴과 다르면 실패한다."), {5})
        self.assertEqual(refs("- E5: 실패한다. (AC #3, #4; failure path)"), {3, 4})
        self.assertEqual(refs("| D5 | 영어 문구가 없다 | AC #3, 실패 경로 |"), {3})
        # an AC inside the label is a mention, not a tag
        self.assertEqual(refs("- E6 (AC #1, like AC #4) x"), {1})

    def test_item_led_by_a_bare_ac_list(self):
        """Like a heading: a list item whose head is the AC list (0.98.7 test-cases did this)."""
        refs = acparse.parse_test_case_refs
        self.assertEqual(refs("1. **AC1**: 저장된 경로 설정이 없는 최초 실행 시 탐지한다."), {1})
        self.assertEqual(refs("- AC #2 — the sheet opens"), {2})
        self.assertEqual(refs("- **AC #1, #3:** both"), {1, 3})
        self.assertEqual(refs("- AC #3 은 이 문서에서 다루지 않는다: 분리됨"), set())     # a sentence

    def test_table_cell_led_by_an_ac_list_with_a_description(self):
        refs = acparse.parse_test_case_refs
        self.assertEqual(refs("| AC1 (종료 시 타입·exit code 저장) | 1–8 |"), {1})
        self.assertEqual(refs("| N-08 | AC4 / A1 | 운영 기본 소스 | idle |"), {4})
        self.assertEqual(refs("| 파생 — 동시 실행 정확 귀속(AC1·AC4 교차) | 27–30 |"), set())   # prose in a cell

    def test_tag_on_a_continuation_line(self):
        text = "- C4: the sheet content equals the review screen's sheet,\n  including the select-all row. (AC #2)\n"
        self.assertEqual(acparse.parse_test_case_refs(text), {2})

    def test_table_cells(self):
        refs = acparse.parse_test_case_refs
        self.assertEqual(refs("| C5 | one selection shows its name | (AC #3) |"), {3})
        self.assertEqual(refs("| C5 | one selection shows its name | AC #3, #4 |"), {3, 4})
        self.assertEqual(refs("| C5 | one selection shows its name (AC #3) |"), {3})
        self.assertEqual(refs("| C29 | banner | 1 | not shown | [AC #10, #11] |"), {10, 11})   # old form
        # a cell that only mentions an AC inside its text covers nothing
        self.assertEqual(refs("| C5 | the name, like AC #3 says, is shown | ok |"), set())

    def test_prose_mentions_in_parentheses_do_not_count(self):
        refs = acparse.parse_test_case_refs
        self.assertEqual(refs("이 절은 (AC #3) 의 경계를 다룬다.\n"), set())
        self.assertEqual(refs("- C21: 학습일이 0 이면 영향 없다(AC #13 과 같은 규칙). (AC #7)"), {7})
        self.assertEqual(refs("- C21: see (AC #13) for the rule; the count is unchanged."), set())
        self.assertEqual(refs("- case: tapping the row (AC #1 의 '마침' 정의) closes it."), set())
        self.assertEqual(refs("- Tapping (AC #2) opens the sheet."), set())          # a word is not a case id
        self.assertEqual(refs("- C3: opens the sheet. `(AC #2)`"), set())            # an example in code
        self.assertEqual(refs("- C3: opens the sheet; see AC #2."), set())

    def test_old_and_new_forms_in_one_file(self):
        text = "## Row [AC #1]\n- C1 [AC #1]: shown.\n- C2: opens. [AC #2]\n- C3: summary. (AC #3)\n| C4 | restart | (AC #4) |\n"
        self.assertEqual(acparse.parse_test_case_refs(text), {1, 2, 3, 4})

    def test_old_priority_brackets_still_parse(self):
        a = acparse.parse_analysis(analysis("- AC #1: a [must]\n- AC #2: b (should)"))
        self.assertEqual(a["acs"], [1, 2])

    def test_fail_closed_wherever_the_token_stands(self):
        """A token the parser cannot read fails even where it would not count (prose)."""
        for bad in ("- C1: opens. (AC #1-3)", "- C1: opens. (AC #x)", "prose (AC #1a) here",
                    "| C5 | text AC #2.5 | (AC #3) |", "- C1 (AC #0): zero"):
            with self.subTest(bad=bad), self.assertRaises(AcError):
                acparse.parse_test_case_refs(bad)


class MissCases(unittest.TestCase):
    """S13 — the 0.102.8 / 10 / 11 cases the 0.102 parser lost, fixed forever."""

    def test_0102_8_inin_gijun_heading_is_read(self):
        """0.102.8 M1: `## 인수 기준` was not recognised as an AC section → every AC lost."""
        text = analysis("- AC #1: a\n- AC #2: b").replace("## Acceptance criteria", "## 인수 기준")
        self.assertEqual(acparse.parse_analysis(text)["acs"], [1, 2])
        text = analysis("- AC #1: a").replace("## Acceptance criteria", "### 수용 기준 (AC)")
        self.assertEqual(acparse.parse_analysis(text)["acs"], [1])

    def test_0102_8_a_section_that_is_not_read_is_an_error_not_an_empty_set(self):
        text = analysis("- AC #1: a").replace("## Acceptance criteria", "## Search criteria")
        with self.assertRaisesRegex(AcError, "no acceptance-criteria section"):
            acparse.parse_analysis(text)

    def test_0102_10_bracket_tag_after_the_case_id(self):
        """0.102.10 B1 (#1945): `- E4 [AC #5] …` marks a case that covers AC #5."""
        self.assertEqual(acparse.parse_test_case_refs("- E4 [AC #5] error text is translated"), {5})
        self.assertEqual(acparse.parse_test_case_refs("- E4 (AC #5) error text is translated"), {5})
        self.assertEqual(acparse.parse_test_case_refs("**E4** 【AC #5】 error text"), {5})

    def test_0102_11_heading_list_names_every_ac(self):
        """0.102.11: `### … (AC #1, #5)` named only AC #1 — [must] AC #4·#5 passed unjudged."""
        text = "### Error state (AC #1, #5)\n\n### Persistence (AC #4)\n"
        self.assertEqual(acparse.parse_test_case_refs(text), {1, 4, 5})
        self.assertEqual(acparse.parse_test_case_refs("## Cases — AC #2, #3, #4\n"), {2, 3, 4})

    def test_0102_11_an_ac_the_document_never_names_stays_uncovered(self):
        refs = acparse.parse_test_case_refs("### Error state (AC #1)\n- c [AC #2]\n")
        self.assertEqual(set([1, 2, 3, 4, 5]) - refs, {3, 4, 5})


class PlanRule(unittest.TestCase):
    def base(self, **kw):
        a = {"type": "feature", "size": "small", "risk": "low", "split": False, "prerequisite_open": False}
        a.update(kw)
        return a

    def test_proceed(self):
        self.assertFalse(acparse.plan_rule_stop(self.base()))
        self.assertEqual(acparse.plan_rule_reasons(self.base()), [])

    def test_each_trigger(self):
        cases = {
            acparse.PLAN_REASON_TYPE: {"type": "bug"},
            acparse.PLAN_REASON_SPLIT: {"split": True},
            acparse.PLAN_REASON_PREREQUISITE: {"prerequisite_open": True},
            acparse.PLAN_REASON_RISK: {"risk": "high"},
        }
        for reason, kw in cases.items():
            with self.subTest(reason=reason):
                self.assertTrue(acparse.plan_rule_stop(self.base(**kw)))
                self.assertEqual(acparse.plan_rule_reasons(self.base(**kw)), [reason])

    def test_order_is_fixed(self):
        got = acparse.plan_rule_reasons(self.base(type="refactor", split=True, prerequisite_open=True, risk="high"))
        self.assertEqual(got, [acparse.PLAN_REASON_TYPE, acparse.PLAN_REASON_SPLIT,
                               acparse.PLAN_REASON_PREREQUISITE, acparse.PLAN_REASON_RISK])


class ReadSpec(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.root, "docs", "specs", "7"))

    def put(self, name, data, mode="w"):
        p = os.path.join(self.root, "docs", "specs", "7", name)
        with open(p, mode) as f:
            f.write(data)
        return p

    def test_reads_and_strips_bom(self):
        self.put("analysis.md", b"\xef\xbb\xbfhello\n", "wb")
        self.assertEqual(acparse.read_spec(self.root, 7, "analysis.md"), "hello\n")

    def test_missing_is_none(self):
        self.assertIsNone(acparse.read_spec(self.root, 7, "analysis.md"))
        self.assertIsNone(acparse.read_spec(self.root, 8, "analysis.md"))

    def test_symlink_file(self):
        target = os.path.join(self.root, "secret.txt")
        with open(target, "w") as f:
            f.write("x")
        os.symlink(target, os.path.join(self.root, "docs", "specs", "7", "analysis.md"))
        with self.assertRaisesRegex(acparse.SpecFileError, "symbolic link"):
            acparse.read_spec(self.root, 7, "analysis.md")

    def test_symlink_directory_on_the_path(self):
        other = os.path.join(self.root, "other")
        os.makedirs(other)
        with open(os.path.join(other, "analysis.md"), "w") as f:
            f.write("x")
        os.symlink(other, os.path.join(self.root, "docs", "specs", "9"))
        with self.assertRaisesRegex(acparse.SpecFileError, "symbolic link"):
            acparse.read_spec(self.root, 9, "analysis.md")

    def test_not_regular(self):
        os.makedirs(os.path.join(self.root, "docs", "specs", "7", "analysis.md"))
        with self.assertRaisesRegex(acparse.SpecFileError, "not a regular file"):
            acparse.read_spec(self.root, 7, "analysis.md")

    def test_not_utf8_and_too_large(self):
        self.put("a.md", b"\xff\xfe\x00bad", "wb")
        with self.assertRaisesRegex(acparse.SpecFileError, "UTF-8"):
            acparse.read_spec(self.root, 7, "a.md")
        self.put("big.md", "x" * (acparse.MAX_SPEC_BYTES + 1))
        with self.assertRaisesRegex(acparse.SpecFileError, "larger"):
            acparse.read_spec(self.root, 7, "big.md")

    def test_bad_arguments(self):
        for issue, name in ((0, "a.md"), ("7", "a.md"), (7, "../a.md"), (7, "A.md"), (True, "a.md")):
            with self.subTest(issue=issue, name=name), self.assertRaises(acparse.SpecFileError):
                acparse.read_spec(self.root, issue, name)


if __name__ == "__main__":
    unittest.main()
