"""K2 — the procedure replay harness (§10.2-2) on a synthetic stream-json log: episodes, the legacy view,
the engine run on a fake GitHub with canned/injected inputs, the structural/prose comparison."""

import json
import os
import unittest

from _k2 import CFG, tmpdir
from workflows.dev.replay import procedure as P

LEDGER = "<!-- guild:visual-baselines -->\nrun: no\nnone\n<!-- /guild:visual-baselines -->"
EVID = "<!-- guild:test-evidence:step-1 -->\nok\n%s\n<!-- /guild:test-evidence:step-1 -->\n" % LEDGER
TEST_OUT = ("<!-- guild:test:output -->\n## Test\n- `flutter test`: `03:00 +9: All tests passed!`\n### 검증 범위\n"
            "- (a) x\n- (b) y\n- (c)\n%s\n- (d) E2E 불요: 위젯 한정\n<!-- /guild:test:output -->\n" % LEDGER)
QA_OUT = "<!-- guild:qa:output -->\n## QA\n### PR CI\nPR CI: green\n<!-- /guild:qa:output -->\n"
RESULT = ">>> RESULT <<<\nDONE"


class Log(object):
    def __init__(self):
        self.lines = [{"type": "system", "subtype": "init", "plugins": [{"name": "guild-plugin", "version": "0.101.0"}]}]
        self.n = 0

    def tool(self, name, inp, result="ok"):
        self.n += 1
        tid = "tu%d" % self.n
        self.lines.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name,
                                                                           "input": inp}]}})
        self.lines.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                                                    "content": result}]}})

    def save(self, path):
        with open(path, "w") as fh:
            for l in self.lines:
                fh.write(json.dumps(l, ensure_ascii=False) + "\n")


def sample(loopback=False):
    g = Log()
    g.tool("Write", {"file_path": "/tmp/ev.md", "content": EVID})
    g.tool("Bash", {"command": "gh issue comment 7 --body-file /tmp/ev.md"})
    g.tool("Bash", {"command": "cat /p/skills/gld/commands/test.md"}, "# TEST\nvisual-baselines safety-net-evidence")
    g.tool("Bash", {"command": "gh issue view 7 --json labels --jq '[.labels[].name]'"}, '["guild:test"]')
    g.tool("Agent", {"description": "tester verify #7"}, RESULT)
    g.tool("Write", {"file_path": "/tmp/t.md", "content": TEST_OUT})
    g.tool("Bash", {"command": "gh issue comment 7 --body-file /tmp/t.md"})
    g.tool("Bash", {"command": 'gh issue edit 7 --remove-label "guild:test" --add-label "guild:qa"'})
    g.tool("Bash", {"command": "cat /p/skills/gld/commands/qa.md"}, "# QA\nPR CI guild:followups")
    g.tool("Agent", {"description": "qa #7"}, RESULT)
    g.tool("Bash", {"command": "gh pr view 40 --json headRefOid --jq .headRefOid"}, "f" * 40)
    g.tool("Bash", {"command": "gh api repos/o/r/commits/%s/check-runs --paginate --jq x" % ("f" * 40)},
           '{"id":1,"name":"ci","conclusion":"success","annotations":0}')
    g.tool("Write", {"file_path": "/tmp/q.md", "content": QA_OUT})
    g.tool("Bash", {"command": "gh issue comment 7 --body-file /tmp/q.md"})
    g.tool("Bash", {"command": 'gh issue edit 7 --remove-label "guild:qa" --add-label "guild:done"'})
    return g


class Replay(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir(self)
        self.log = os.path.join(self.d, "issue-7-20261101_000000-attempt1.log")
        sample().save(self.log)

    def test_episodes_and_state(self):
        eps = P.episodes([self.log])
        self.assertEqual([e.stage for e in eps], ["test", "qa"])
        self.assertEqual(eps[0].start_labels, ["guild:test"])
        self.assertIn("test-evidence:step-1", eps[0].state["issue"])
        self.assertIn("test:output", eps[1].state["issue"])
        self.assertEqual([P.Legacy(e).outcome() for e in eps], ["ADVANCE", "DONE"])

    def test_engine_reproduces_test_structure_byte_for_byte(self):
        ep = P.episodes([self.log])[0]
        leg = P.Legacy(ep)
        eng = P.run_engine(ep, leg, CFG, self.d)
        self.assertEqual(eng["token"], "OK ADVANCE: qa")
        c = P.compare(ep, leg, eng)
        self.assertTrue(c["exact"], c["diffs"])
        self.assertTrue(all(f[0] for f in c["fields"].values()), c["fields"])

    def test_qa_only_intentional_ran_at(self):
        ep = P.episodes([self.log])[1]
        leg = P.Legacy(ep)
        self.assertEqual(leg.check_runs[0]["conclusion"], "success")
        eng = P.run_engine(ep, leg, CFG, self.d)
        self.assertEqual(eng["token"], "OK DONE")
        c = P.compare(ep, leg, eng)
        self.assertEqual([(d["element"], d["class"]) for d in c["diffs"]], [("qa:output/ran-at", "intentional:C5")])
        self.assertTrue(c["fields"]["qa.pr_ci"][0])

    def test_report_gates(self):
        rows = []
        for ep in P.episodes([self.log]):
            leg = P.Legacy(ep)
            rows.append(dict(P.compare(ep, leg, P.run_engine(ep, leg, CFG, self.d)), stage=ep.stage, error=None, legacy_outcome=leg.outcome(), engine_kind=leg.outcome() if ep.stage == "test" else "DONE", episode=ep.key))
        rep = P.report(rows, {})
        self.assertEqual(rep["episodes"]["test"]["structural_byte_match_after_intentional"], 100.0)
        self.assertEqual(rep["episodes"]["qa"]["structural_defect_bytes"], 0)

    def test_file_tracking_follows_edit_sed_and_relative_paths(self):
        f = P.Files()
        f.step({"name": "Write", "input": {"file_path": "/w/.claude/x.md", "content": "<!-- guild:note -->\nverified: no\n"}})
        f.step({"name": "Bash", "input": {"command": "sed -i '' 's/^verified: no$/verified: yes/' /w/.claude/x.md"}})
        f.step({"name": "Edit", "input": {"file_path": "/w/.claude/x.md", "old_string": "yes", "new_string": "YES"}})
        po = P.post_of({"name": "Bash", "input": {"command": "gh issue comment 7 --body-file .claude/x.md"}}, f, 7)
        self.assertEqual(po, ("issue", 7, "<!-- guild:note -->\nverified: YES\n"))

    def test_derived_mode_uses_real_cases_and_leader_prose(self):
        ep = P.episodes([self.log])[0]
        leg = P.Legacy(ep)
        real = "| ID | AC |\n|---|---|\n| T1 | AC1 |\n| T2 | AC1 |\n"
        p, gh, w, calls, inj = P.build(ep, leg, CFG, self.d, real_tc=real)
        self.assertTrue(inj["derived"])
        self.assertEqual(inj["verdicts"], {"effective": 0, "not_covering": 0, "unsure": 2})   # prose never names T1/T2
        self.assertEqual(P.prose_verdicts(["C1", "C2", "C3"], "### AC 커버리지\n- C1–C2 PASS\n- C3 미커버\n### 검증 범위\n"),
                         {"C1": "effective", "C2": "effective", "C3": "not_covering"})

    def test_agreement_split(self):
        rows = [{"legacy_outcome": "ADVANCE", "engine_kind": "ADVANCE", "episode": "a",
                 "derived_run": {"kind": "LOOPBACK", "token": "OK LOOPBACK: execute", "verdicts": {"unsure": 2}}}]
        a = P._agreement(rows)
        self.assertEqual((a["by_construction"]["pct"], a["derived"]["pct"], a["derived"]["miss_extraction"]), (100.0, 0.0, 1))

    def test_manual_qa_absent_is_a_replay_gap(self):
        self.assertEqual(P.classify("manual-qa", "(absent)", "manual-qa x", P.episodes([self.log])[1])[0], "replay-gap")

    def test_e2e_normalisation(self):
        self.assertEqual(P.e2e_of("**E2E 불요** — 위젯 한정"), "E2E 불요: 위젯 한정")
        self.assertEqual(P.e2e_of("x\nE2E 회귀 실행 필요: `app_test`**"), "E2E 회귀 실행 필요: `app_test`")


if __name__ == "__main__":
    unittest.main()
