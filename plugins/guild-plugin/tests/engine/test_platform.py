"""guildcore.decisions (live / answers), config, emit, journal, and K0 inertness."""

import io
import json
import os
import re
import tempfile
import unittest

import _util
from guildcore import config, decisions, emit, journal, state
from guildcore.adapters.gh import FakeGh, GhCli, GhError, assert_read_only
from guildcore.records import decisions as fmt

AT = "2026-11-15T05:00:00Z"


def log_with(*blocks):
    body = fmt.render_comment([fmt.render_block(i + 1, b) for i, b in enumerate(blocks)])
    return decisions.DecisionLog.load([_util.comment(body, 10)])


PENDING = {"point": "SJ-QA", "kind": "loopback", "stage": "qa", "by": "judge:sonnet", "at": AT,
           "status": "pending-human", "question": "q", "options": ["loop-back", "stop"]}


def ev(kind, label, at, actor="owner"):
    return {"event": kind, "label": {"name": label}, "created_at": at, "actor": {"login": actor}}


class Pending(unittest.TestCase):
    def test_pending_and_resolution(self):
        log = log_with(PENDING)
        self.assertEqual([b.id for b in log.pending_human()], ["D1"])
        log = log_with(PENDING, {"resolves": "D1", "by": "human", "status": "answered"})
        self.assertEqual(log.pending_human(), [])
        self.assertEqual(log.next_n(), 3)

    def test_rollover_comments_merge(self):
        a = fmt.render_comment([fmt.render_block(1, PENDING)])
        b = fmt.render_comment([fmt.render_block(2, {"resolves": "D1", "by": "code", "status": "superseded"})],
                               continued_from=10)
        log = decisions.DecisionLog.load([_util.comment(b, 11), _util.comment("x <!-- guild:decisions --> quoted", 9),
                                          _util.comment(a, 10)])
        self.assertEqual([c.comment_id for c in log.comments], [10, 11])   # line-1 marker only
        self.assertEqual(log.pending_human(), [])

    def test_engine_start_and_directives(self):
        log = log_with({"point": "engine-start", "by": "code", "started_at_stage": "design", "plugin": "0.102.0"},
                       {"point": "directive", "by": "human", "text": "skip CI wait"})
        self.assertEqual(log.engine_start().get("started_at_stage"), "design")
        self.assertEqual([d.get("text") for d in log.directives()], ["skip CI wait"])


class Live(unittest.TestCase):
    """§2.5 rule 1b — the three scenarios: rollback while pending, downgrade-era legacy relabel,
    and the engine's own journaled writes."""

    def setUp(self):
        self.block = log_with(dict(PENDING, at_server="2026-11-15T05:00:02Z")).pending_human()[0]

    def test_alive(self):
        ok, why = decisions.live(self.block, state.derive(["guild:qa"]), [ev("labeled", "guild:needs-human", "2026-11-15T06:00:00Z")])
        self.assertTrue(ok, why)

    def test_rollback_kills(self):
        ok, why = decisions.live(self.block, state.derive(["guild:execute"]), [])
        self.assertFalse(ok)
        self.assertIn("stage changed outside engine", why)

    def test_relabel_round_trip_kills(self):
        tl = [ev("unlabeled", "guild:qa", "2026-11-15T07:00:00Z"), ev("labeled", "guild:qa", "2026-11-15T07:01:00Z")]
        self.assertFalse(decisions.live(self.block, state.derive(["guild:qa"]), tl)[0])

    def test_events_before_at_server_and_own_writes_ignored(self):
        own_ev = dict(ev("labeled", "guild:qa", "2026-11-15T08:00:00Z"), id=777)
        tl = [ev("labeled", "guild:qa", "2026-11-15T05:00:01Z"), own_ev]
        self.assertTrue(decisions.live(self.block, state.derive(["guild:qa"]), tl, [777])[0])
        # K0-m10: matching is by server event id — the same label/time without our id kills it
        self.assertFalse(decisions.live(self.block, state.derive(["guild:qa"]), tl, [778])[0])


class Answers(unittest.TestCase):
    def setUp(self):
        self.block = log_with(PENDING).pending_human()[0]
        self.unlabel = [ev("unlabeled", "guild:needs-human", "2026-11-15T06:00:00Z", "owner")]

    def ans(self, body="guild-answer: D1 loop-back", at="2026-11-15T06:05:00Z", assoc="OWNER", login="owner", cid=20):
        return _util.comment(body, cid, at, assoc, login)

    def test_accepted(self):
        _st, a, rej = decisions.accepted_answer(self.block, [self.ans()], self.unlabel)
        self.assertEqual((a.token, rej), ("loop-back", []))

    def test_each_rejection(self):
        cases = [(self.ans(assoc="CONTRIBUTOR"), self.unlabel, "author_association"),
                 (self.ans(at="2026-11-15T04:00:00Z"), self.unlabel, "older"),
                 (self.ans(body="guild-answer: D1 maybe"), self.unlabel, "token"),
                 (self.ans(), [], "not removed"),
                 (self.ans(login="someone-else"), self.unlabel, "label remover")]
        for c, tl, why in cases:
            _st, a, rej = decisions.accepted_answer(self.block, [c], tl)
            with self.subTest(why=why):
                self.assertIsNone(a)
                self.assertIn(why, rej[0][1])

    def test_attended_skips_timeline_checks(self):
        _st, a, _ = decisions.accepted_answer(self.block, [self.ans(login="x")], [], unattended=False)
        self.assertEqual(a.token, "loop-back")

    def test_marked_comment_is_not_an_answer(self):
        _st, a, rej = decisions.accepted_answer(self.block, [self.ans(body="<!-- guild:note -->\nguild-answer: D1 stop")], self.unlabel)
        self.assertEqual((a, rej), (None, []))


class Config(unittest.TestCase):
    def write(self, obj, agents=None):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".claude", "guild"))
        os.makedirs(os.path.join(root, ".claude", "agents"))
        with open(os.path.join(root, ".claude", "guild", "config.json"), "w") as fh:
            fh.write(obj if isinstance(obj, str) else json.dumps(obj))
        for name, text in (agents or {}).items():
            with open(os.path.join(root, ".claude", "agents", name + ".md"), "w") as fh:
                fh.write(text)
        return root

    def test_defaults_and_forward_compat(self):
        c = config.load(self.write({"language": "ko", "engine": {
            "answer_associations": ["OWNER"], "max_parallel_roles": "three", "first_sprint_mode": "maybe",
            "budget_usd_per_issue": 20, "zz_later_key": {"a": 1}, "attended_confirm_interpretation": 1}}))
        e = c.engine
        self.assertEqual(e["answer_associations"], ["OWNER"])
        self.assertEqual(e["max_parallel_roles"], 3)               # wrong type → default + warning
        self.assertEqual(e["first_sprint_mode"], "auto")
        self.assertEqual(e["budget_usd_per_issue"], 20.0)
        self.assertIs(e["attended_confirm_interpretation"], False)  # 1 is not a bool
        self.assertEqual(c.engine_unknown, ["zz_later_key"])
        self.assertEqual(e["zz_later_key"], {"a": 1})              # kept, never fatal
        self.assertEqual(len(c.warnings), 3)

    def test_real_word_app_shape_without_engine(self):
        c = config.load(self.write({"version": "0.99.2", "language": "ko", "roles": ["leader"],
                                    "gates": {"enabled": True}, "sprint": {"capacity": 14}}))
        self.assertEqual(c.engine, config.ENGINE_DEFAULTS)
        self.assertEqual(c.get("sprint.capacity"), 14)
        self.assertEqual(c.warnings, [])

    def test_errors(self):
        with self.assertRaises(config.ConfigError):
            config.load(tempfile.mkdtemp())
        with self.assertRaises(config.ConfigError):
            config.load(self.write("{not json"))

    def test_persona_habits_and_tags(self):
        leader = ("---\nname: leader\nmodel: opus\n---\n# Leader\n## 프로젝트 특화\nx\n"
                  "## 역할 습관 (로컬)\n<!-- guild:persona:habits -->\n"
                  "- [J:EX-ARB] dismiss rule\n- untagged habit\n- [J:KICKOFF] [J:STAKES] both\n\n## 다음 절\n- not a habit\n")
        root = self.write({"roles": ["leader", "qa"]}, {"leader": leader,
                                                         "qa": "---\nname: qa\n---\nbody\n<!-- guild:persona:habits -->\n- (아직 없음 — x)\n"})
        p = config.load(root).persona("leader")
        self.assertEqual(p.model, "opus")
        self.assertEqual(len(p.habits()), 3)
        self.assertEqual(p.habits("EX-ARB"), ["- [J:EX-ARB] dismiss rule"])
        self.assertEqual(p.habits("KICKOFF"), ["- untagged habit", "- [J:KICKOFF] [J:STAKES] both"])
        self.assertEqual(p.habits("STAKES"), ["- [J:KICKOFF] [J:STAKES] both"])
        q = config.persona(root, "qa")
        self.assertEqual((q.model, q.habits()), ("sonnet", []))


class Emit(unittest.TestCase):
    def test_sentinel(self):
        out = io.StringIO()
        emit.engine({"a": "가"}, out)
        self.assertEqual(out.getvalue(), '>>> ENGINE <<<\n{"a":"가"}\n')

    def test_result_and_rate_limit(self):
        line = emit.stream_result(0.1234567, True, "FAIL: x\n  y", {"input_tokens": 1}, out=io.StringIO())
        obj = json.loads(line)
        self.assertEqual((obj["type"], obj["is_error"], obj["result"], obj["total_cost_usd"]),
                         ("result", True, "FAIL: x y", 0.123457))
        with self.assertRaises(ValueError):
            emit.rate_limit_event("rejected", out=io.StringIO())
        self.assertNotIn("resetsAt", emit.rate_limit_event("allowed", out=io.StringIO()))

    def test_stderr_never_says_rate_limit(self):
        err = io.StringIO()
        emit.warn("gh: API rate limit exceeded; Overloaded; too many requests", err)
        self.assertIsNone(re.search(r"rate[ -]?limit|overloaded|too many requests", err.getvalue(), re.I))


class Journal(unittest.TestCase):
    def test_format_and_views(self):
        cd = tempfile.mkdtemp()
        d = journal.issue_dir(cd, 42)
        os.makedirs(d)
        k = dict(issue=42, entry_id="e1", stage="test", step_id="T3.5", attempt=1, op="comment", target="test:output")
        lines = [journal.render("entry", "t0", issue=42, entry_id="e1", stage="test", loopback_blocks=1),
                 journal.render("intent", "t1", **k), journal.render("done", "t2", **k),
                 journal.render("intent", "t3", **dict(k, op="label", target="guild:qa")),
                 journal.render("write", "t4", op="label", event_id=555, label="guild:test"),
                 '{"kind":"intent","t":"t5","iss']                      # torn tail
        with open(os.path.join(d, "journal.jsonl"), "w") as fh:
            fh.write("\n".join(lines))
        v = journal.JournalView.read(cd, 42)
        self.assertEqual(v.torn, 1)
        self.assertEqual(v.open_entry()["entry_id"], "e1")
        self.assertEqual([e["target"] for e in v.intent_only()], ["guild:qa"])
        self.assertEqual(v.own_label_writes(), [555])
        self.assertEqual(lines[1], json.dumps(json.loads(lines[1]), sort_keys=True, separators=(",", ":")))
        self.assertTrue(journal.lock_path(cd, 42).endswith("/guild/engine/42.lock"))
        with self.assertRaises(ValueError):
            journal.render("bogus", "t")


class Inert(unittest.TestCase):
    """K0 ships inert: nothing in the plugin calls the engine, and the engine cannot write."""

    def test_no_plugin_file_references_the_engine(self):
        hits = []
        for base, dirs, files in os.walk(_util.SKILL):
            if os.path.abspath(base).startswith(_util.ENGINE):
                continue
            for fn in files:
                p = os.path.join(base, fn)
                try:
                    if "gld_engine.py" in _util.read(p) or "/engine/" in _util.read(p):
                        hits.append(p)
                except UnicodeDecodeError:
                    pass
        self.assertEqual(hits, [])

    def test_gh_adapter_refuses_writes(self):
        for argv in (["gh", "issue", "edit", "1", "--add-label", "guild:qa"],
                     ["gh", "api", "repos/o/r/issues/1/comments", "-X", "POST"],
                     ["gh", "api", "--paginate", "repos/o/r/issues/1/comments", "-f", "body=x"],
                     ["gh", "issue", "comment", "1", "--body-file", "x"],
                     ["gh", "pr", "edit", "1", "--body-file", "x"]):
            with self.assertRaises(GhError):
                assert_read_only(argv)
        assert_read_only(["gh", "api", "--paginate", "repos/o/r/issues/1/comments", "--jq", ".[]"])
        calls = []
        g = GhCli("o/r", runner=lambda a: calls.append(a) or "[]")
        g.pr_search(5)
        g.issue_list(state="all", label="guild:child")
        self.assertEqual(len(calls), 2)

    def test_guildcore_never_imports_workflows_or_network(self):
        core = os.path.join(_util.ENGINE, "guildcore")
        for base, _d, files in os.walk(core):
            for fn in files:
                if fn.endswith(".py"):
                    src = _util.read(os.path.join(base, fn))
                    with self.subTest(fn=fn):
                        self.assertNotRegex(src, r"(?m)^\s*(from|import) workflows")
                        self.assertNotRegex(src, r"(?m)^\s*(from|import) (urllib|socket|http|requests)")

    def test_fake_gh_counts(self):
        gh = FakeGh(_util.GH_STATUS)
        with self.assertRaises(GhError):
            gh.issue(9999)


if __name__ == "__main__":
    unittest.main()
