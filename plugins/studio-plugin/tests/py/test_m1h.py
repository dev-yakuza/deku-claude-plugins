"""M1h (m1-plan §10): render · ④a · copy · ④b — `validate_copy.py` and the platform rules, the flow from ③ to ④b with
the fake s2v, plus the M1g re-review NIT on number values (weeks, native day counts, a spaced Sino day)."""

import contextlib
import io
import json
import os
import sys

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo import s2vrun
from stdo.distribute import check as copy_check, cli as copy_cli, rules
from stdo.state import router, store
from stdo.voice import numbers, tts
from test_m1g import IMG, BoardCase

sys.path.insert(0, os.path.join(helpers.HERE, "drivers"))
import make_harness  # noqa: E402

NOTICE = "This video's narration is AI-synthesized speech."
FACT = "탑승권을 받으면 출국 심사를 받습니다."
COPY = """---
title: "공항에서 쓰는 단어"
hashtags: ["#일본어", "#공항"]
---
공항에서 쓰는 일본어 단어를 알아봅니다.
%(fact)s

%(chapters)s

%(credit)s

%(notice)s
"""


class CopyCase(BoardCase):
    """A video at ③ approved, then rendered and approved at ④a."""

    def setUp(self):
        super().setUp()
        self.to_board()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(s2vrun.main(["snapshot", "v1", "--output", "youtube"], providers=self.providers,
                                         cwd=self.repo), 0, err.getvalue())
        h = [l.split()[1] for l in out.getvalue().splitlines() if l.startswith("hash12 ")][0]
        self.assertEqual(self.state("stage-done", "v1", "visual-check", "--output", "youtube"), 0, self.err)
        self.approve_scoped("3", h, "--output", "youtube")

    def approve_scoped(self, gate, h, *scope, code=0):
        argv = ["approve", "v1", gate, "--expect", h] + list(scope)
        self.pend(argv, "승인 v1 %s" % h)
        self.assertEqual(self.state(*argv), code, self.err)

    def run_render(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = s2vrun.main(["render", "v1", "--output", "youtube"], providers=self.providers, cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def to_four_a(self):
        self.assertEqual(self.run_render(), 0, self.err)
        self.assertEqual(self.state("record-render", "v1", "--output", "youtube"), 0, self.err)
        self.assertEqual(self.state("stage-done", "v1", "render", "--output", "youtube"), 0, self.err)
        self.assertEqual(self.state("shown", "v1", "4a", "--output", "youtube"), 0, self.err)
        h = [l.split()[1] for l in self.out.splitlines() if l.startswith("hash12 ")][0]
        self.approve_scoped("4a", h, "--output", "youtube")

    def platform(self, checked="2026-10-29", text=None):
        p = rules.path(self.repo, "youtube")
        with open(p) as f:
            body = f.read()
        body = text if text is not None else body.replace('checked: ""', 'checked: "%s"' % checked)
        with open(p, "w") as f:
            f.write(body)
        helpers.git(self.repo, "commit", "-q", "--no-verify", "--allow-empty", "-am", "platform rules checked")

    def chapters(self):
        with open(os.path.join(self.repo, "studio", "out", "v1", "ko", "youtube.ko.chapters.txt")) as f:
            return f.read().strip()

    def write_copy(self, **over):
        v = {"chapters": self.chapters(), "credit": "the author", "notice": NOTICE, "fact": FACT}
        v.update(over)
        text = COPY % v
        d = os.path.join(self.repo, "studio", "copy", "v1", "ko")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "youtube.md"), "w") as f:
            f.write(text)
        return text

    def copy_excerpts(self, ex):
        p = os.path.join(self.w, "claims-map.json")
        with open(p) as f:
            cm = json.load(f)
        cm["copy_excerpts"] = {"youtube": ex}
        with open(p, "w") as f:
            json.dump(cm, f, ensure_ascii=False)

    def validate(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = copy_cli.main(["v1", "--platform", "youtube"], cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def copy_verify(self, entries=None):
        from test_m1e import E2
        entries = entries if entries is not None else [{"text": FACT, "kind": "fact", "verdict": "supported",
                                                        "excerpts": [E2]}]
        with open(os.path.join(self.w, "copy-verify.youtube.json"), "w") as f:
            json.dump({"sentences": entries}, f, ensure_ascii=False)

    def ready(self):
        from test_m1e import E2
        self.platform()
        self.write_copy()
        self.copy_verify()
        self.copy_excerpts([E2])


class Flow(CopyCase):
    def test_three_to_four_b_then_commit(self):
        self.to_four_a()
        self.ready()
        self.assertEqual(self.validate(), 0, self.out + self.err)
        self.assertEqual(self.state("stage-done", "v1", "copy", "--platform", "youtube"), 0, self.err)
        self.assertEqual(self.state("shown", "v1", "4b", "--platform", "youtube"), 0, self.err)
        from test_m1e import E2
        self.assertIn('in the question: 근거: "%s" ← "%s"' % (FACT, E2), self.out)
        from stdo.state import labels
        self.assertEqual(labels.gate2_lines(store.read_state(self.vdir), None, "4b", "youtube"),
                         ['근거: "%s" ← "%s"' % (FACT, E2)])
        h = [l.split()[1] for l in self.out.splitlines() if l.startswith("hash12 ")][0]
        self.approve_scoped("4b", h, "--platform", "youtube")
        self.assertEqual(self.state("next", "v1", "--json"), 0, self.err)
        self.assertEqual(json.loads(self.out)["redo"], None)  # everything approved: the commit is next (M1i)
        # Y3: a credit change after ④b sends the copy back to the copy stage
        from stdo import credits
        with open(os.path.join(self.vdir, credits.FILE), "a") as f:
            f.write(" ")
        self.assertEqual(self.state("next", "v1", "--json"), 0, self.err)
        self.assertEqual(json.loads(self.out)["redo"]["stage"], "copy")

    def test_check_failed_holds_the_render(self):
        self.scenario({"render": {"check_failed": True}})
        self.assertEqual(self.run_render(), 1)
        self.assertEqual(self.state("record-render", "v1", "--output", "youtube"), 4)
        self.assertEqual(store.read_state(self.vdir)["langs"]["ko"]["held"]["state"], "render")


class ValidateCopy(CopyCase):
    def setUp(self):
        super().setUp()
        self.to_four_a()
        self.ready()
        self.assertEqual(self.validate(), 0, self.out)

    def refused(self, why):
        self.assertEqual(self.validate(), 1, why)
        self.assertIn(why, self.out)

    def test_platform_not_checked(self):
        self.platform(text=open(rules.path(self.repo, "youtube")).read().replace('checked: "2026-10-29"', 'checked: ""'))
        self.refused("is not checked yet (its `checked` date is empty)")

    def test_rules_block_required(self):
        text = open(rules.path(self.repo, "youtube")).read()
        self.platform(text=text.replace("<!-- studio:rules -->", "<!-- rules -->"))
        self.refused("no studio:rules JSON block")

    def test_limits_and_format(self):
        self.write_copy().replace("공항에서 쓰는 단어", "x" * 101)
        text = open(os.path.join(self.repo, "studio", "copy", "v1", "ko", "youtube.md")).read()
        with open(os.path.join(self.repo, "studio", "copy", "v1", "ko", "youtube.md"), "w") as f:
            f.write(text.replace("공항에서 쓰는 단어", "x" * 101))
        self.refused("the title has 101 characters (1–100)")
        with open(os.path.join(self.repo, "studio", "copy", "v1", "ko", "youtube.md"), "w") as f:
            f.write(text.replace('["#일본어", "#공항"]', json.dumps(["#t%d" % n for n in range(16)])))
        self.refused("16 hashtags (at most 15)")
        with open(os.path.join(self.repo, "studio", "copy", "v1", "ko", "youtube.md"), "w") as f:
            f.write(text.replace('"#공항"', '"#공항 여행"'))
        self.refused("is not one hashtag")
        with open(os.path.join(self.repo, "studio", "copy", "v1", "ko", "youtube.md"), "w") as f:
            f.write(text.split("---\n", 2)[2])
        self.refused("the copy has no frontmatter")
        with open(os.path.join(self.repo, "studio", "copy", "v1", "ko", "youtube.md"), "w") as f:
            f.write(text + "x" * 5000)
        self.refused("the description has")

    def test_notice_credit_and_chapters(self):
        self.write_copy(notice="")
        self.refused("the required notice is missing: %s" % NOTICE)
        self.write_copy(credit="")
        self.refused("the credit line of %s is missing: the author" % IMG)
        lines = self.chapters().splitlines()
        self.write_copy(chapters="\n".join(reversed(lines)))
        self.refused("the chapters are not the render's")
        self.write_copy(chapters=lines[0])
        self.refused("the chapters are not the render's")

    def test_home_path_and_in_house_terms(self):
        self.write_copy(credit="the author (/" + "Users/someone/pics)")
        self.refused("the copy shows a home path")
        self.write_copy(credit="the author ~/pics")
        self.refused("the copy shows a home path")
        make_harness.write_overlay(self.repo, {"internal": {"terms": ["Kestrelwing"]}})
        self.write_copy(credit="the author, Kestrelwing team")
        self.refused("the copy uses an in-house term (Kestrelwing)")

    def test_copy_excerpts(self):
        self.copy_excerpts([])
        self.refused("copy_excerpts.youtube is empty")
        self.copy_excerpts(["어디에도 없는 문장입니다."])
        self.refused("a copy excerpt is not in the source copy")

    def test_y2_a_new_number_needs_the_fact_checker(self):
        from test_m1e import E1, E2
        self.write_copy(fact=FACT + " 공항에는 체크인 창구가 30개 있습니다.")
        self.refused("is not judged (copy-verify): 공항에는 체크인 창구가 30개 있습니다.")
        self.write_copy(fact=FACT + " 체크인은 출발 직전에 끝납니다.")  # a term of the excerpts, no number
        self.refused("is not judged (copy-verify): 체크인은 출발 직전에 끝납니다.")
        self.write_copy(fact=FACT + " 모두 세 가지 표현을 배웁니다.")  # a number, no term
        self.refused("is not judged (copy-verify): 모두 세 가지 표현을 배웁니다.")
        self.write_copy()
        self.copy_verify([{"text": FACT, "kind": "fact", "verdict": "unsupported"}])
        self.refused("the copy says something unsupported")
        self.copy_verify([{"text": FACT, "kind": "fact", "verdict": "supported", "excerpts": ["없는 문장"]}])
        self.refused("copy-verify: an excerpt is not in the source copy")
        self.copy_verify()
        self.copy_excerpts([E2, E1])  # more than the facts rest on
        self.refused("copy_excerpts.youtube must be exactly the excerpts of copy-verify's facts")
        self.copy_excerpts([E2])
        os.remove(os.path.join(self.w, "copy-verify.youtube.json"))
        self.refused("copy-verify.youtube.json is missing")
        self.copy_verify()
        self.assertEqual(self.validate(), 0, self.out)  # chapters, credits and notices are not the copy's own facts

    def test_nit_angle_brackets(self):
        self.write_copy(credit="the author <b>")
        self.refused("the copy has < or >")

    def test_usage(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(copy_cli.main(["v1"], cwd=self.repo), 2)
            for bad in ("tiktok", "../../../../tmp/p", "/tmp/p"):
                self.assertEqual(copy_cli.main(["v1", "--platform", bad], cwd=self.repo), 2, bad)
            # a state that names a bad platform (written before Y1, or by hand) still gives no path
            st = store.read_state(self.vdir)
            st["brief"]["platforms"]["../../../../tmp/p"] = ["youtube"]
            with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
                json.dump(st, f)
            self.assertEqual(copy_cli.main(["v1", "--platform", "../../../../tmp/p"], cwd=self.repo), 2)

    def test_units(self):
        self.assertIsNone(copy_check.in_order(["a", "b"], "x a y b"))
        self.assertEqual(copy_check.in_order(["a", "b"], "b a"), "b")
        with self.assertRaises(rules.RulesProblem):
            rules.parse('---\nchecked: ""\n---\n<!-- studio:rules -->\n```json\n{"title_max": 0}\n```\n'
                        '<!-- /studio:rules -->\n')
        r, checked = rules.parse(open(rules.path(self.repo, "youtube")).read())
        self.assertEqual((r["title_max"], checked), (100, "2026-10-29"))


class RouterFour(StudioTestCase):
    def test_new_render_goes_to_four_a_and_copy_only_to_four_b(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        self.assertEqual(router.decide(s, "ko", F.changed(c, credits="cr2")).redo["stage"], "copy")  # Y3
        self.assertEqual(router.decide(s, "ko", F.changed(c, render={"youtube": "r-other"})).redo["stage"], "4a")
        self.assertEqual(router.decide(s, "ko", F.changed(c, copy={"youtube": "cp-other"})).redo["stage"], "4b")


class Template(StudioTestCase):
    def test_platform_draft_is_unchecked(self):
        text = open(os.path.join(helpers.SKILL, "templates", "platforms", "youtube.md")).read()
        r, checked = rules.parse(text.replace("{{CHECKED_DATE}}", ""))
        self.assertEqual(checked, "")
        self.assertEqual(r["required"], [NOTICE])


class PlatformNames(StudioTestCase):
    """Y1: a platform name becomes a path — only safe names of the video's kind."""

    def test_names(self):
        from stdo.state import schema
        for bad in ("../../../../tmp/p", "/tmp/p", "a/b", "", ".hidden", "youtube.md", None):
            self.assertFalse(schema.platform_ok(bad), bad)
            with self.assertRaises(rules.RulesProblem):
                rules.path("/repo", bad)
        self.assertTrue(schema.platform_ok("youtube", "youtube"))
        self.assertFalse(schema.platform_ok("tiktok", "youtube"))
        from stdo.distribute import factcheck
        with self.assertRaises(ValueError):
            factcheck.path("/v", "ko", "../x")

    def test_rules_outside_the_folder(self):
        repo = os.path.join(self.tmp, "r")
        d = os.path.join(repo, ".claude", "studio", "platforms")
        os.makedirs(d)
        os.symlink(os.path.join(self.tmp, "elsewhere.md"), os.path.join(d, "youtube.md"))
        with self.assertRaises(rules.RulesProblem):
            rules.path(repo, "youtube")


class BriefPlatforms(StudioTestCase):
    def test_record_brief_refuses_other_platforms(self):
        from test_state_store import StoreCase  # noqa: F401 (its setup below)
        import io as _io
        from stdo.state import cli
        store.enable_writes()
        repo = helpers.make_repo(self.tmp)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir)
        store.create(vdir, F.state())
        F.brief_ready(repo, vdir)
        for bad in ("../../../../tmp/p", "/tmp/p", "tiktok"):
            p = os.path.join(vdir, "work", "brief.json")
            with open(p, "w") as f:
                json.dump({"claims": [F.C1], "roles": [{"name": "narrator"}], "outputs": ["youtube"],
                           "platforms": {bad: ["youtube"]}}, f)
            out, err = _io.StringIO(), _io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["record-brief", "v1", "--from", p], cwd=repo)
            self.assertEqual(code, 1, bad)
            self.assertIn("platforms the youtube kind does not have", err.getvalue())


class NumbersNit(StudioTestCase):
    def test_weeks_days_and_a_spaced_sino_day(self):
        for a, b in (("일주일", "1주일"), ("이주일 동안", "2주일 동안"), ("이틀 동안", "2일 동안"), ("사흘", "3일"),
                     ("나흘", "4일"), ("닷새", "5일"), ("열흘", "10일"), ("삼 일 동안", "3일 동안")):
            self.assertEqual(numbers.values(a), numbers.values(b), (a, b))
            self.assertIsNone(tts.mismatch(a, b, "ko"), (a, b))
        self.assertEqual(numbers.values("보름 동안"), [15])
        self.assertEqual(numbers.values("보름"), numbers.values("15일"))
        self.assertEqual(numbers.values("하루하루"), [1])  # a known limit (J145): read once, both sides alike
        for word in ("오일에", "오일을 넣고", "이 일은 중요합니다"):
            self.assertEqual(numbers.values(word), [], word)


from test_guard_judge import JudgeCase  # noqa: E402


class GateFourBLines(JudgeCase):
    """Y2: the ④b question must show each fact line shown 4b recorded (the V1 pattern)."""
    H = "3f2a9c0d1e4b"

    def test_lines_in_the_question(self):
        import transcripts as TR
        from stdo.guard import judge
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        tpath = TR.transcript_path(self.env)
        st = F.state()
        st["video"] = "v"
        line = '근거: "%s" ← "x"' % FACT
        st["langs"]["ko"]["shown"]["4b"] = {"youtube": {"hash": "x", "at": "t", "lines": [line]}}
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump(st, f)
        cmd = "python3 .claude/studio/scripts/state.py approve v 4b --expect %s --platform youtube" % self.H

        def run(q):
            t = TR.approval_turn(TR.T(), "승인 v %s" % self.H, qtext=q)
            t.write(tpath)
            hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                    "transcript_path": tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                    "prompt_id": t.prompt}
            return judge.decide(hook, self.env, snapshot_loader=self.loader)
        base = "[v] ④b 배포용 글 — studio/copy/v/ko/youtube.md · hash %s" % self.H
        deny, _ = run(base)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn(line, deny.message())
        deny, ctx = run(base + "\n" + line)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)
