"""Consumer-contract tests (§6.3): the jq / grep / bash readers of today's prose, run with the real
binaries over records the engine parses or renders, must agree with the engine.

Every consumer expression is EXTRACTED from the live plugin file it lives in (not re-typed), so a
change to a reader breaks this test instead of silently diverging from the engine."""

import json
import os
import re
import subprocess
import tempfile
import unittest

import _util
from guildcore import emit, state
from guildcore.adapters.gh import FakeGh
from guildcore.records import audit, loopback, markers, needs_human, outputs

CMD = os.path.join(_util.SKILL, "commands")
SUP = os.path.join(_util.SKILL, "templates", "sprint-supervisor.sh")
RENDERED = os.path.join(_util.FX, "rendered")


def text(rel):
    return _util.read(os.path.join(CMD, rel))


def jq_after(source, prefix):
    """The single-quoted --jq program of the first line of `source` containing `prefix`."""
    for ln in source.split("\n"):
        if prefix in ln:
            m = re.search(r"--jq '(.*)'", ln[ln.index(prefix):])
            if m:
                return m.group(1)
    raise AssertionError("consumer expression not found: %s" % prefix)


def all_comments():
    fx = _util.fixture()
    for n, it in sorted(fx["issues"].items(), key=lambda kv: int(kv[0])):
        yield int(n), it


class SectionA(unittest.TestCase):
    def setUp(self):
        _util.need_jq(self)
        self.expr = jq_after(text("atoms/_handoff.md"), "gh issue view <n> --json labels --jq")

    def test_derivation_matches_jq(self):
        cases = [["guild:child", "guild:test"], ["guild:children"], ["guild:qa", "guild:needs-human"],
                 ["guild:harness"], ["guild:sprint"], ["guild:needs-human", "guild:harness", "guild:execute"],
                 ["bug"], [], ["guild:qa", "guild:test"], ["guild:child", "guild:done", "guild:needs-human"]]
        for labels in cases:
            want = json.loads(_util.jq(self.expr, {"labels": [{"name": n} for n in labels]}, raw=False))
            with self.subTest(labels=labels):
                self.assertEqual(state.derive(labels).as_jq(), want)

    def test_list_form_in_status_and_monitoring(self):
        list_expr = jq_after(text("monitoring.md"), "gh issue list --state open --limit 200")
        rows = [dict(it, number=n) for n, it in all_comments()]
        got = json.loads(_util.jq(list_expr, rows, raw=False))
        for row in got:
            st = state.derive([lb["name"] for lb in next(r for r in rows if r["number"] == row["number"])["labels"]])
            self.assertEqual((row["stage"], row["paused"]), (st.label, st.paused))


class StatusPresence(unittest.TestCase):
    def test_marker_presence_jq(self):
        _util.need_jq(self)
        expr = jq_after(text("status.md"), "gh issue view $1 --json labels,title,comments")
        for n, it in all_comments():
            comments = it.get("comments", []) + [{"id": 9, "body": None}]   # `// ""` guard
            want = json.loads(_util.jq(expr, {"title": it["title"], "labels": it["labels"],
                                              "comments": comments}, raw=False))["markers"]
            got = outputs.presence(comments)
            with self.subTest(issue=n):
                self.assertEqual({k: got[k] for k in want}, want)


class NeedsHumanReaders(unittest.TestCase):
    def setUp(self):
        _util.need_jq(self)
        self.daily = jq_after(text("sprint/daily.md"), "gh api repos/<owner>/<repo>/issues/<n>/comments --paginate --jq")
        m = re.search(r"grep -nE -m1 '([^']+)' <file>", text("atoms/_handoff.md"))
        self.grep_re = m.group(1)

    def bodies(self):
        out = [_util.read(p) for _v, _n, p in _util.records_of("needs-human")]
        out.append(_util.read(os.path.join(RENDERED, "needs-human-answer.md")))
        return out

    def test_daily_cause_jq(self):
        for i, body in enumerate(self.bodies()):
            page = [{"id": 1, "body": "<!-- guild:note -->\nx"}, {"id": 2, "body": body}]
            got = _util.jq(self.daily, page).rstrip("\n").split("\n")[-1]
            with self.subTest(i=i):
                self.assertEqual(got, needs_human.Pause(body).daily_cause())

    def test_selfcheck_grep(self):
        for i, body in enumerate(self.bodies()):
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
                fh.write(body)
            try:
                p = subprocess.run(["grep", "-nE", "-m1", self.grep_re, fh.name], stdout=subprocess.PIPE)
                out = p.stdout.decode("utf-8")
            finally:
                os.unlink(fh.name)
            with self.subTest(i=i):
                self.assertEqual(out.startswith("2:"), needs_human.Pause(body).cause_check_ok())


class LoopbackReaders(unittest.TestCase):
    def test_lookup_lowest_id(self):
        _util.need_jq(self)
        expr = jq_after(text("atoms/_handoff.md"), "gh api --paginate repos/<owner>/<repo>/issues/<N>/comments --jq")
        rec = _util.record("loopback/0.98.7/omc-161.md")
        page = [{"id": 30, "body": rec}, {"id": 12, "body": rec.replace("loopback 2", "loopback 9")},
                {"id": 5, "body": None}]
        ids = [json.loads(l)["id"] for l in _util.jq(expr, page, raw=False).split("\n") if l.strip()]
        self.assertEqual(min(ids), markers.find(page, "loopback")["id"])

    def test_supervisor_loopback_mark(self):
        sup = _util.read(SUP)
        self.assertIn("grep -c '^### loopback'", sup)
        self.assertIn("grep -c '^consumed:'", sup)
        body = _util.read(os.path.join(RENDERED, "loopback-append-0987.md"))
        body += "\n" + _util.record("loopback/0.101.0/prose-reset-human.md")
        rc, out, _ = _util.bash("b=$(cat); printf '%s/%s\\n' \"$(printf '%s\\n' \"$b\" | grep -c '^### loopback')\" "
                                "\"$(printf '%s\\n' \"$b\" | grep -c '^consumed:')\"", body)
        r1 = loopback.LoopbackRecord.parse(_util.read(os.path.join(RENDERED, "loopback-append-0987.md")))
        r2 = loopback.LoopbackRecord.parse(_util.record("loopback/0.101.0/prose-reset-human.md"))
        blocks = len(r1.blocks) + len(r2.blocks)                      # the reset counts here, on purpose
        consumed = sum(1 for r in (r1, r2) for b in r.blocks if b.has("consumed"))
        self.assertEqual(out.strip(), "%d/%d" % (blocks, consumed))


class SupervisorAndBatch(unittest.TestCase):
    def test_stage_of(self):
        sup = _util.read(SUP)
        fn = re.search(r"^stage_of\(\) \{.*?^\}", sup, re.M | re.S).group(0)
        for labels in (["guild:child", "guild:test"], ["guild:needs-human", "guild:qa"],
                       ["guild:done"], ["guild:children"], [], ["guild:harness", "guild:analyze"]):
            csv = state.labels_csv(labels)
            rc, out, _ = _util.bash(fn + '\nstage_of "$(cat)"', csv)
            st = state.derive(labels)
            want = st.stage if st.stage in ("analyze", "design", "execute", "test", "qa") else ""
            with self.subTest(labels=labels):
                self.assertEqual(out.strip(), want)

    def test_batch_case_arms(self):
        src = text("batch.md")
        self.assertLess(src.index("*guild:needs-human*)"), src.index("*guild:done*)"))
        self.assertLess(src.index("*guild:done*)"), src.index("*guild:children*)"))
        script = ('case "$(cat)" in *guild:needs-human*) echo paused ;; *guild:done*) echo done ;; '
                  '*guild:children*) echo children ;; *) echo mid ;; esac')
        for labels, want in ((["guild:children", "guild:needs-human"], "paused"),
                             (["guild:child", "guild:done"], "done"), (["guild:children"], "children"),
                             (["guild:test"], "mid")):
            st = state.derive(labels)
            mine = "paused" if st.paused else ("done" if st.stage == "done" else
                                              ("children" if st.children else "mid"))
            self.assertEqual(mine, want)
            self.assertEqual(_util.bash(script, state.labels_csv(labels))[1].strip(), want)

    def test_split_head_needs_human(self):
        _util.need_jq(self)
        sup = _util.read(SUP)
        m = re.search(r'split_head_needs_human\(\) \{.*?--jq "(.*?)" \\\n', sup, re.S)
        expr = m.group(1).replace('\\"', '"').replace("${1}", "105").replace("\\$", "$")
        gh = FakeGh(_util.GH_STATUS)
        rows = gh.issue_list(state="all", label="guild:child")
        got = _util.jq(expr, rows).strip()
        kids = [k for k in state.discover_children(FakeGh(_util.GH_STATUS), 105) if k["derived"].stage != "done"]
        head = kids[0] if kids else None
        want = str(head["number"]) if head and head["state"] == "OPEN" and head["derived"].paused else ""
        self.assertEqual(got, want)
        self.assertEqual(got, "106")

    def test_rate_limit_fence_reads_emit(self):
        _util.need_jq(self)
        sup = _util.read(SUP)
        expr = re.search(r"RL_LAST=\$\(jq -r -R '(.*?)' \"\$LOG\"", sup).group(1)
        log = (emit.rate_limit_event("rejected", 1794877200, out=_Sink()) +
               emit.stream_result(1.25, False, "OK PAUSE: needs-human — x", out=_Sink()))
        self.assertEqual(_util.jq(expr, log, extra=["-R"]).strip().split("\n")[-1], "rejected 1794877200")
        allowed = emit.rate_limit_event("allowed", out=_Sink())
        self.assertTrue(_util.jq(expr, allowed, extra=["-R"]).startswith("allowed"))
        self.assertIn('{"type":"rate_limit_event"', log)       # RL_LOST literal match


class _Sink(object):
    def write(self, _):
        pass


class RetroAuditCounts(unittest.TestCase):
    """sprint/retro.md's audit jq (the record of account): engine parse == retro counts on every
    real record, and C2's ` [id:F<k>]` / C1's `head:` change no count (incl. `loose`)."""

    def setUp(self):
        _util.need_jq(self)
        self.expr = jq_after(text("sprint/retro.md"), "gh api repos/<owner>/<repo>/issues/<n>/comments --paginate --jq")

    def retro(self, body):
        return json.loads(_util.jq(self.expr, [{"id": 1, "body": body}, {"id": 2, "body": None}], raw=False))

    def test_counts_agree(self):
        bodies = [_util.read(p) for _v, _n, p in _util.records_of("auditor-execute")]
        blk = _util.read(os.path.join(RENDERED, "audit-block-c1c2.md")).rstrip("\n")
        bodies.append("<!-- guild:auditor:execute -->\n" + blk + "\n<!-- /guild:auditor:execute -->")
        for i, body in enumerate(bodies):
            r = self.retro(body)
            mine = audit.AuditRecord.parse(body).counts()
            with self.subTest(i=i):
                self.assertEqual(r["records"], mine["records"])
                for k in ("looped_back", "fixed", "recorded", "dismissed", "clean", "no_scan"):
                    self.assertEqual(r[k], mine[k], k)

    def test_c2_ids_change_nothing(self):
        blk = _util.read(os.path.join(RENDERED, "audit-block-c1c2.md")).rstrip("\n")
        with_ids = "<!-- guild:auditor:execute -->\n" + blk + "\n<!-- /guild:auditor:execute -->"
        without = re.sub(r" \[id:F\d+\]", "", with_ids).replace("head: ", "")
        self.assertEqual(self.retro(with_ids), self.retro(without))


class SectionMFilter(unittest.TestCase):
    def test_engine_comments_are_never_read_as_the_humans(self):
        _util.need_jq(self)
        src = text("atoms/_handoff.md")
        expr = re.search(r"--jq '(\.\[\] \| select\(\(\.body // \"\"\) \| contains\(\"<!-- guild:\"\) \| not\) \| \{id, html_url, body\})'", src).group(1)
        page = [{"id": i, "html_url": "u", "body": _util.read(os.path.join(RENDERED, fn))}
                for i, fn in enumerate(sorted(os.listdir(RENDERED)))
                if not fn.startswith(("prbody-", "audit-block"))]
        page.append({"id": 99, "html_url": "u", "body": "guild-answer: D7 stop"})
        got = [json.loads(l)["id"] for l in _util.jq(expr, page, raw=False).split("\n") if l.strip()]
        self.assertEqual(got, [99])


if __name__ == "__main__":
    unittest.main()
