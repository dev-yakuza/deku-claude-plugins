"""Issue references of an Issue body (stage-4 scope §2.11 H20, VB4): TF1, TF2."""

import unittest

from gxengine import defaults, github, issuerefs

MAX = defaults.REF_RANGE_MAX


def refs(body, stage=4, own=None):
    return issuerefs.referenced_numbers(body, own=own, stage=stage)


class Ranges(unittest.TestCase):
    def test_tf1_every_written_form(self):
        for body in ("#102~#104", "#102-#104", "#102–#104", "#102~104"):
            with self.subTest(body=body):
                self.assertEqual(refs(body), [102, 103, 104])

    def test_the_sentence_of_service_123(self):
        body = "착수 순서는 언어별 페이지(EPIC #100, #102~#104) 이후로 한다."
        self.assertEqual(refs(body), [100, 102, 103, 104])
        self.assertEqual(refs(body, stage=3), [100, 102, 104])

    def test_a_particle_after_the_end_and_several_ranges(self):
        self.assertEqual(refs("#102~#104가 끝난 뒤, #7-#9"), [7, 8, 9, 102, 103, 104])

    def test_a_particle_after_a_single_reference(self):
        """VZ (B's finding): `#104이` is #104 from stage 4; an ASCII letter still ends no reference."""
        for body, want in (("#104이 먼저 끝나야 한다", [104]), ("선행: #101와 #104이다", [101, 104]),
                           ("#102~104가 끝난 뒤", [102, 103, 104]), ("#104는, #105도", [104, 105]),
                           ("#104a", []), ("#104_x", []), ("#102~104a", [102]), ("이슈#104이", [])):
            with self.subTest(body=body):
                self.assertEqual(refs(body), want)
        self.assertEqual(refs("#104이 먼저", stage=3), [], "stages 1-3 keep their word boundary (H23)")
        self.assertEqual(refs("#102~104가", stage=3), [102])
        self.assertEqual(github.referenced_numbers("#7이 먼저", own=1, stage=4), [7])

    def test_the_own_number_is_left_out(self):
        self.assertEqual(refs("#1~#4", own=3), [1, 2, 4])

    def test_the_widest_range(self):
        self.assertEqual(refs(f"#10~#{10 + MAX}"), list(range(10, 11 + MAX)))

    def test_tf2_anything_else_is_as_before(self):
        for body in (f"#10~#{11 + MAX}", "#104~#102", "#104~#104", "service#102~#104", "acme/x#102~#104",
                     "&#102;~&#104;", "`color: #112233`", "#112233-#445566", "#102 ~ #104", "#102..#104", "#102-104",
                     "#102~104a", "#0~#0", "", "no reference"):
            with self.subTest(body=body):
                self.assertEqual(refs(body), refs(body, stage=3))

    def test_below_stage_4_nothing_is_expanded(self):
        for stage in (1, 2, 3):
            self.assertEqual(refs("#102~#104", stage=stage), [102, 104])

    def test_issue_md_and_the_plan_gate_facts_use_it(self):
        self.assertEqual(github.referenced_numbers("#1~#3", stage=4), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
