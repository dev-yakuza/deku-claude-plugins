import unittest

import _util  # noqa: F401  (sys.path)
from guildcore import state
from guildcore.adapters.gh import FakeGh


class Derive(unittest.TestCase):
    # _handoff.md Section A — "Verified against the real jq binary" examples
    def test_section_a_examples(self):
        self.assertEqual(state.derive(["guild:child", "guild:test"]).label, "guild:test")
        self.assertEqual(state.derive(["guild:children"]).label, "guild:children")
        st = state.derive(["guild:qa", "guild:needs-human"])
        self.assertEqual((st.label, st.paused), ("guild:qa", True))
        st = state.derive(["guild:harness"])
        self.assertEqual((st.label, st.harness), ("none", True))

    def test_sprint_projected_not_staged(self):
        st = state.derive([{"name": "guild:sprint"}])
        self.assertEqual((st.stage, st.sprint), ("none", True))

    def test_first_label_in_github_order_wins(self):
        # `.[0]` — the derivation never sorts
        self.assertEqual(state.derive(["guild:qa", "guild:test"]).stage, "qa")
        self.assertEqual(state.derive(["guild:test", "guild:qa"]).stage, "test")

    def test_ordinal(self):
        st = state.derive(["guild:test"])
        self.assertTrue(st.at_least("execute"))
        self.assertFalse(st.at_least("qa"))
        self.assertIsNone(state.derive(["guild:children"]).ordinal)
        self.assertFalse(state.derive(["guild:children"]).at_least("analyze"))

    def test_non_guild_labels_ignored(self):
        self.assertEqual(state.derive(["bug", "type:feature"]).label, "none")

    def test_labels_csv(self):
        self.assertEqual(state.labels_csv(["bug", "guild:child", "guild:execute"]),
                         "guild:child,guild:execute")


class Prs(unittest.TestCase):
    def test_closing_keywords(self):
        prs = [{"number": 1, "body": "Closes #12"}, {"number": 2, "body": "fixed: #12"},
               {"number": 3, "body": "RESOLVES #12."}, {"number": 4, "body": "see #12"},
               {"number": 5, "body": "Closes #123"}, {"number": 6, "body": None}]
        m = state.match_prs(12, prs)
        self.assertEqual([p["number"] for p in m.strict], [1, 2, 3])
        self.assertEqual(len(m.candidates), 6)


class Snapshot(unittest.TestCase):
    def test_three_reads_per_issue(self):
        gh = FakeGh(_util.GH_STATUS)
        snap = state.snapshot(gh, 117)
        self.assertEqual(len(gh.calls), 3)
        self.assertEqual(snap.state.stage, "done")
        self.assertTrue(snap.markers["qa"])
        self.assertEqual(snap.loopback.summary()["active"], 2)
        self.assertEqual(snap.pr.strict[0]["number"], 205)

    def test_children_discovery_boundary(self):
        gh = FakeGh(_util.GH_STATUS)
        kids = state.discover_children(gh, 105)
        # #108 says `Parent Issue: #1050` — the `([^0-9]|$)` boundary excludes it
        self.assertEqual([k["number"] for k in kids], [104, 106, 107, 113])

    def test_unmarked_since(self):
        gh = FakeGh(_util.GH_STATUS)
        snap = state.snapshot(gh, 113)
        got = snap.unmarked_comments_since("2026-11-15T05:30:00Z")
        self.assertEqual(len(got), 2)
        self.assertTrue(all("<!-- guild:" not in c["body"] for c in got))


if __name__ == "__main__":
    unittest.main()
