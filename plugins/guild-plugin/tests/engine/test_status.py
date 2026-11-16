"""status show / status route / status board — output comparison.

1. status.md's own three output examples are rebuilt as fake-GitHub Issues and the engine output
   must reproduce each example's lines verbatim (extracted from the live status.md).
2. Every Issue of tests/fixtures/engine/gh/status.json renders exactly its pinned text
   (tests/fixtures/engine/status/<n>.txt) — C-F-18 rows, loop-back line, PR candidates,
   Decisions/Mode lines, sprint/harness rows, not-an-Issue.
3. Routing follows resume.md's order; the board is actionable-first; gh read budgets hold."""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

import _util
from guildcore.adapters.clock import FixedClock
from guildcore.adapters.gh import FakeGh
from workflows.status import board, cli, route, show

STATUS_TXT = os.path.join(_util.FX, "status")
ENTRY = os.path.join(_util.ENGINE, "gld_engine.py")


def example_blocks():
    src = _util.read(os.path.join(_util.SKILL, "commands", "status.md"))
    return [b for b in re.findall(r"```\n(Issue #.*?)```", src, re.S)]


def L(*names):
    return [{"name": n} for n in names]


AN = "<!-- guild:analyze:output -->\nx\n<!-- /guild:analyze:output -->"
DE = "<!-- guild:design:output -->\nx\n<!-- /guild:design:output -->"
EXAMPLES = {
    "repo": "owner/repo",
    "issues": {
        "123": {"title": "Add login form", "labels": L("guild:execute"), "body": "",
                "comments": [{"id": 1, "body": AN}, {"id": 2, "body": DE}]},
        "124": {"title": "Add login form", "labels": L("guild:execute", "guild:needs-human"), "body": "",
                "comments": [{"id": 1, "body": AN}, {"id": 2, "body": DE}]},
        "838": {"title": "Word detail screen", "labels": L("guild:children"), "body": "", "comments": []},
        "841": {"title": "DB schema slice", "labels": L("guild:child", "guild:done"), "state": "CLOSED",
                "body": "Parent Issue: #838"},
        "842": {"title": "detail view slice", "labels": L("guild:child", "guild:execute"),
                "body": "Parent Issue: #838"},
        "843": {"title": "entry-point slice", "labels": L("guild:child"), "body": "Parent Issue: #838"},
    },
    "prs": [{"number": 456, "url": "https://github.com/<owner>/<repo>/pull/456", "state": "OPEN",
             "title": "x", "body": "Closes #123"}],
}


class StatusMdExamples(unittest.TestCase):
    def test_three_examples_verbatim(self):
        blocks = example_blocks()
        self.assertEqual(len(blocks), 3)
        gh = FakeGh(EXAMPLES)
        # 1 — plain
        want = [re.sub(r"\s+\(or \"none\"\)$", "", l) for l in blocks[0].rstrip("\n").split("\n")]
        got = show.show(gh, 123).split("\n")
        self.assertEqual(got[:len(want)], want)
        # 2 — paused (the example ends in "..." after the execute row; 124 has no PR)
        want = blocks[1].rstrip("\n").split("\n")
        want = [l.replace("#123", "#124") for l in want if l != "..."]
        got = show.show(gh, 124).split("\n")
        self.assertEqual(got[:len(want)], want)
        # 3 — split parent
        want = blocks[2].rstrip("\n").split("\n")
        got = show.show(gh, 838).split("\n")
        self.assertEqual(got[:len(want)], want)


class PinnedOutputs(unittest.TestCase):
    def test_every_fixture_issue(self):
        fx = _util.fixture()
        seen = 0
        for n in sorted(fx["issues"], key=int):
            path = os.path.join(STATUS_TXT, "%s.txt" % n)
            if not os.path.exists(path):
                continue
            with self.subTest(issue=n):
                self.assertEqual(show.show(FakeGh(fx), int(n)), _util.read(path))
            seen += 1
        self.assertGreaterEqual(seen, 14)

    def test_read_budget(self):
        for n, cap in ((101, 3), (117, 3), (113, 4), (105, 4)):
            gh = FakeGh(_util.GH_STATUS)
            show.show(gh, n)
            with self.subTest(issue=n):
                self.assertLessEqual(len(gh.calls), cap)


class NoNetwork(unittest.TestCase):
    def test_real_gh_is_blocked(self):
        p = subprocess.run(["gh", "issue", "view", "1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 97)


class Routing(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, ".claude", "guild"))
        with open(os.path.join(self.root, ".claude", "guild", "config.json"), "w") as fh:
            json.dump({"version": "0.101.0", "language": "ko", "roles": ["leader"]}, fh)

    def r(self, n, root=None):
        return route.route(FakeGh(_util.GH_STATUS), n, root or self.root)

    def test_order(self):
        cases = {103: ("stop", "done"), 105: ("dev", "children"), 102: ("dev", "spine"),
                 109: ("fail", "sprint"), 110: ("dev", "harness"), 111: ("suggest", "none"),
                 112: ("fail", "not_issue")}
        for n, want in cases.items():
            with self.subTest(issue=n):
                got = self.r(n)
                self.assertEqual((got.action, got.reason), want)
        self.assertEqual(self.r(103).message, "Issue #103 is already done.")
        self.assertEqual(self.r(109).message, "FAIL: #109 is a sprint tracking Issue — use /gld sprint daily")

    def test_uninitialized(self):
        got = self.r(102, root=tempfile.mkdtemp())
        self.assertEqual((got.action, got.message), ("stop", "Guild not initialized (run `/gld init`)."))

    def test_loopbacks_and_interrupted(self):
        r = self.r(116)
        self.assertTrue(r.interrupted_loopback)
        self.assertEqual(r.loopbacks["active"], 1)
        r = self.r(118)                    # an audit invocation ≥ at: execute ran since
        self.assertFalse(r.interrupted_loopback)
        self.assertTrue(r.paused is False and self.r(102).paused)

    def test_pending_human_answer(self):
        r = self.r(113)
        self.assertEqual(len(r.pending), 1)
        p = r.pending[0]
        self.assertEqual((p["id"], p["kind"], p["options"]), ("D2", "loopback", ["loop-back", "stop"]))
        # the OWNER answer after the unlabel wins; the NONE drive-by is ignored
        self.assertEqual(p["answer"]["token"], "loop-back")

    def test_superseded_pending_is_not_routed(self):
        self.assertEqual(self.r(114).pending, [])

    def test_route_text_and_json(self):
        out = io.StringIO()
        os.environ["GLD_ENGINE_GH_FIXTURE"] = _util.GH_STATUS
        try:
            rc = cli.main(["route", "--issue", "113", "--json", "--root", self.root], out=out)
        finally:
            del os.environ["GLD_ENGINE_GH_FIXTURE"]
        self.assertEqual(rc, 0)
        lines = out.getvalue().split("\n")
        self.assertEqual(lines[0], ">>> ENGINE <<<")
        self.assertEqual(json.loads(lines[1])["pending_human"][0]["id"], "D2")


class Board(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        g = os.path.join(self.root, ".claude", "guild")
        os.makedirs(os.path.join(g, "gates"))
        os.makedirs(os.path.join(g, "memory"))
        os.makedirs(os.path.join(g, "knowledge"))
        os.makedirs(os.path.join(self.root, ".claude", "agents"))
        os.makedirs(os.path.join(self.root, "docs", "standards"))
        with open(os.path.join(g, "config.json"), "w") as fh:
            json.dump({"version": "0.101.0", "language": "ko", "roles": ["leader", "qa"],
                       "gates": {"enabled": True}}, fh)
        with open(os.path.join(g, "gates", "findings.json"), "w") as fh:
            json.dump({"open": [{"rule": "x"}]}, fh)
        with open(os.path.join(g, "gates", "dismissed.md"), "w") as fh:
            fh.write("# Dismissed\n\n- `a` — r\n- `b` — r\n")
        with open(os.path.join(g, "memory", "ground-truth.jsonl"), "w") as fh:
            fh.write('{"kind":"correction"}\n{"kind":"stagnation"}\n')
        with open(os.path.join(g, "knowledge", "index.md"), "w") as fh:
            fh.write("# idx\n- `lib/**` → [a](facts/a.md)\n")
        with open(os.path.join(self.root, ".claude", "agents", "qa.md"), "w") as fh:
            fh.write("---\nmodel: sonnet\n---\n## 프로젝트 특화\n(미정 — 추후 확정)\n<!-- guild:persona:habits -->\n- (아직 없음)\n")
        for name, st in (("a.md", "draft"), ("b.md", "confirmed")):
            with open(os.path.join(self.root, "docs", "standards", name), "w") as fh:
                fh.write("---\nstatus: %s\n---\n" % st)

    def run_board(self, *args):
        out = io.StringIO()
        os.environ["GLD_ENGINE_GH_FIXTURE"] = _util.GH_STATUS
        try:
            rc = cli.main(["board"] + list(args) + ["--root", self.root], out=out,
                          clock=FixedClock("2026-11-16T00:00:00Z"), ledger=lambda root: "ledger: runs=2 next=3")
        finally:
            del os.environ["GLD_ENGINE_GH_FIXTURE"]
        return rc, out.getvalue()

    def test_full_snapshot_pinned(self):
        rc, text = self.run_board()
        if os.environ.get("GLD_ENGINE_REPIN") == "1":
            with open(os.path.join(STATUS_TXT, "board-ko.txt"), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.assertEqual(rc, 0)
        self.assertEqual(text, _util.read(os.path.join(STATUS_TXT, "board-ko.txt")))
        lines = text.split("\n")
        self.assertTrue(lines[1].startswith("▲ 2개 이슈 사람 대기 중"))   # actionable first
        self.assertTrue(lines[2].startswith("▲ 게이트"))

    def test_focus_and_invalid(self):
        rc, text = self.run_board("gates")
        self.assertTrue(text.startswith("포커스: gates\n"))
        self.assertNotIn("활성 작업", text)
        rc, text = self.run_board("bogus")
        self.assertTrue(text.startswith("알 수 없는 섹션 'bogus'"))
        self.assertIn("활성 작업", text)

    def test_html_written_under_memory_only(self):
        rc, text = self.run_board("--html")
        p = board.html_path(self.root)
        self.assertTrue(os.path.isfile(p))
        self.assertIn("/.claude/guild/memory/monitoring.html", p.replace(os.sep, "/"))
        self.assertNotIn("<script", _util.read(p))


class EntryPoint(unittest.TestCase):
    def run_entry(self, *args, env=None):
        e = dict(os.environ, **(env or {}))
        p = subprocess.run([sys.executable, ENTRY] + list(args), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=e, cwd=_util.ENGINE)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_show_via_cli(self):
        rc, out, _ = self.run_entry("status", "show", "--issue", "117",
                                    env={"GLD_ENGINE_GH_FIXTURE": _util.GH_STATUS})
        self.assertEqual((rc, out), (0, _util.read(os.path.join(STATUS_TXT, "117.txt"))))

    def test_unknown_workflow_and_usage(self):
        self.assertEqual(self.run_entry("dev", "run", "--issue", "1")[0], 64)
        self.assertEqual(self.run_entry()[0], 64)
        self.assertEqual(self.run_entry("version")[1], "guild engine K0\n")

    def test_old_python_halts_6(self):
        code = ("import sys; sys.path.insert(0, %r); import gld_engine as g; g.MIN_PY = (99, 0); "
                "sys.exit(g.main(['status']))" % _util.ENGINE)
        p = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stdout.decode()), (6, "halted: env python\n"))

    def test_shim_parses_as_python36(self):
        import ast
        src = _util.read(ENTRY)
        tree = ast.parse(src, feature_version=(3, 6))
        self.assertIsNotNone(tree)


if __name__ == "__main__":
    unittest.main()
