"""Readiness T4 P1 — R4-12 from the promoted edition's side: an Issue that Guild 0.98.7 labelled.

Guild 0.98.7's stage labels (OLD below) are the same text in both trees (promote: literal). Since the first promotion
(R4-1 S1) they are the stable channel's OWN prefix: in the promoted tree such an Issue starts from analyze and its old
stage labels come off, the done label on an open Issue without a pull request stops for a human (done-unconfirmed), an
open 0.98.7 pull request that closes it refuses the start (open-closing-pr) — and the other-channel refusal
(`stable-label`, whose prefix the promotion swapped to the development channel's) never catches it first. In the
development channel the same Issue belongs to the other channel and is refused as `stable-label` before anything.
The same file runs in both trees (tests/channel_names_test.sh, the promoted tree's engine_test.sh)."""

import unittest

from gxengine import channel, defaults, github
from tests.test_t1_guards import T1, issue_rules, pr, pr_list

# promote: literal-begin — Guild 0.98.7's names and the two channels' prefixes are the same text in both trees
OLD = ("guild:execute", "guild:qa", "guild:design")
OLD_DONE = "guild:done"
OLD_GONE = ("guild%3Aexecute", "guild%3Aqa", "guild%3Adesign")
PROMOTED = channel.SELF == "gld"
PREFIXES = {"gld": ("guild:", "gx:"), "gldx": ("gx:", "guild:")}      # channel → (own label prefix, refused prefix)
# promote: literal-end


class Prefixes(unittest.TestCase):
    def test_the_swap_put_the_other_channels_prefix_into_the_refusal(self):
        own, refused = PREFIXES[channel.SELF]
        self.assertEqual(defaults.LABEL_PREFIX, own)
        self.assertEqual(defaults.MARKER_PREFIX, "<!-- " + own)
        self.assertEqual(github.STABLE_PREFIX, refused)
        self.assertFalse(github.has_stable_label({"labels": [defaults.LABEL_PREFIX + "analyze"]}),
                         "the engine never refuses its own stage label")
        self.assertTrue(github.has_stable_label({"labels": [refused + "analyze"]}))
        self.assertEqual(github.has_stable_label({"labels": list(OLD)}), not PROMOTED)


class Guild0987Issue(T1):
    def deletes(self):
        return [c["argv"][3].rsplit("/", 1)[1] for c in self.w.gh.calls
                if c["argv"][:3] == ["api", "-X", "DELETE"] and "/labels/" in c["argv"][3]]

    def test_stage_labels_without_records(self):
        self.w.set_gh(issue_rules(labels=OLD + ("type:feature",)))
        rc = self.run4(self.leader(), mode="unattended")
        if not PROMOTED:
            self.assertRefusedBeforeAnything(rc, "stable-label")
            return
        self.ok(rc)
        self.assertEqual(self.state()["steps"][0]["id"], "analyze")
        self.assertEqual(self.session.calls[0]["step"], "analyze", "the work starts from analyze")
        gone = self.deletes()
        for name in OLD_GONE:
            self.assertEqual(gone.count(name), 1, (name, gone))
        self.assertNotIn("type%3Afeature", gone)
        self.assertIn("starting from analyze", self.w.out.getvalue())
        self.assertFalse([l for l in self.log() if (l.get("data") or {}).get("refused")], "no refusal on the way")

    def test_done_without_a_pull_request(self):
        for mode in ("attended", "unattended"):
            with self.subTest(mode=mode):
                self.w.set_gh(issue_rules(labels=(OLD_DONE,)))
                self.assertRefusedBeforeAnything(self.run4(self.leader(), mode=mode),
                                                 "done-unconfirmed" if PROMOTED else "stable-label")

    def test_done_with_its_0987_pull_request_open(self):
        rows = [pr(1924, "feature/#42-quiz", body="Adds the row.\n\nCloses #42")]
        self.w.set_gh(issue_rules(labels=(OLD_DONE, "guild:qa"), extra=[pr_list(rows)]))  # promote: literal
        self.assertRefusedBeforeAnything(self.run4(self.leader(), mode="unattended"),
                                         "open-closing-pr" if PROMOTED else "stable-label")


if __name__ == "__main__":
    unittest.main()
