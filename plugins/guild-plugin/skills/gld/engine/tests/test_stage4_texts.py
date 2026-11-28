"""Stage-4 role texts (VB9): the mutation declaration (developer) and the mutation facts (done-gate leader).

Additions only, read from engine stage 4 (H23); the example in the developer's text is a valid declaration
and the leader's text names every status and refusal code the engine can write.
"""

import json
import re
import unittest

from gxengine import codes, defaults, instructions, schema


def work(stage):
    return instructions.frame("work", "developer", "work", stage)


class Texts(unittest.TestCase):
    def test_below_stage_4_nothing_is_added(self):
        for stage in (1, 2, 3):
            self.assertNotIn(defaults.MUTATIONS_NAME, work(stage))
            self.assertNotIn("killed", instructions.leader_task_text("done-gate", stage) if stage >= 2 else "")
        self.assertTrue(work(4).startswith(work(3).rstrip("\n")))
        self.assertTrue(instructions.leader_task_text("done-gate", 4).startswith(
            instructions.leader_task_text("done-gate", 3).rstrip("\n")))

    def test_only_the_developer_gets_it(self):
        self.assertNotIn(defaults.MUTATIONS_NAME, instructions.frame("review", "auditor", "judge", 4))

    def test_the_example_is_a_valid_declaration(self):
        line = [x for x in work(4).splitlines() if x.strip().startswith('`{"format"')][0]
        obj = json.loads(line.strip().strip("`"))
        schema.validate(obj, "mutations")

    def test_the_numbers_are_the_engines(self):
        self.assertIn(f"At most {defaults.MUTATIONS_MAX} entries", work(4))

    def test_the_leader_knows_every_code(self):
        text = instructions.leader_task_text("done-gate", 4).split("Mutation facts and commit messages")[1]
        for code in codes.MutationStatus.values() + codes.MutationRefusal.values():
            self.assertIn(code, text)
        self.assertIn("done_gate.commits", text)
        self.assertIn("evidence", text)

    def test_no_control_file_or_secret_path_is_named_as_a_place_to_write(self):
        text = work(4)[len(work(3).rstrip("\n")):]
        self.assertFalse(re.search(r"\.claude|CLAUDE\.md|procedure\.yaml", text))


if __name__ == "__main__":
    unittest.main()
