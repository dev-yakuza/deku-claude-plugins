"""Pilot 3, 0.0.28 (fix-0028-plan §2–§14): the writer's frontmatter lines from `state.py next --enter script` (the
default narrator's cast block from the start, each output's aspect and maxDuration, the targetDuration range) and the
narration check of the cast block (Q2, Q4, Q5); `record-brief --from` relative to the current folder or the video
folder, never outside it (Q3); every s2v failure message (Q4); targetDuration bounded by s2v's ±15 % (Q6); the S7
message, the skeleton's `from` and the on-screen hint (Q7); excerpts in the copy and whole (Q8); the played sentences
and the `read:` line in the ② block (Q9); `floor_text` (Q10); `record-source --url` and the copy's source line (Q11);
brand lines in the value block (Q12); `--ask-before` and `ask-before` (Q15); the ③ and ④a question blocks (Q17,
Q18). The guard's own allows (§1) are tested with the guard. Fake s2v and stub data only."""

import json
import os
import unittest

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo import s2vlint
from stdo.claims import check as ccheck
from stdo.commit import values
from stdo.source import assets as assets_mod
from stdo.state import store
from stdo.text.normalize import Text
from stdo.voice import cast as vcast, frontmatter
from test_guard_judge import JudgeCase
from test_m1e import E1, E2, S1, S2, FlowCase, cid
from test_m1f import CAST_BLOCK, VoiceCase
from test_m1g import BoardCase
from test_m1h import CopyCase

CAST = 'cast:\n  narrator: { voice: "qwen:Sohee", style: "차분하게" }\n'
# the pilot's 緑の通路 line (an excerpt stopped where its inline HTML began)
MIDORI = ("- <strong><ruby>緑<rp>(</rp><rt>みどり</rt><rp>)</rp></ruby>の通路</strong>: 申告するものがない人が通る出口です。"
          "赤の通路は申告する人の出口です。")
MIDORI_WHOLE = ("<strong><ruby>緑<rp>(</rp><rt>みどり</rt><rp>)</rp></ruby>の通路</strong>: "
                "申告するものがない人が通る出口です。")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- §2 · §4 · §5: the writer's frontmatter lines

class ScriptLines(FlowCase):
    def setUp(self):
        super().setUp()
        self.to_brief()

    def test_next_enter_script_prints_the_lines(self):
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 0, self.err)
        self.assertIn("script: go", self.out)
        for line in ("  cast:", '    narrator: { voice: "qwen:Sohee", style: "차분하게" }', "  outputs:",
                     '    youtube: { aspect: "16:9", maxDuration: 600 }',
                     "  targetDuration: <2–521, from the brief's estimate>"):
            self.assertIn(line + "\n", self.out)
        self.assertEqual(self.state("next", "v1", "--enter", "script", "--json"), 0, self.err)
        fm = json.loads(self.out)["frontmatter"]
        self.assertEqual(fm[:2], ["cast:", '  narrator: { voice: "qwen:Sohee", style: "차분하게" }'])

    def test_the_youtube_range(self):
        F.write_format(self.repo, length=(180, 480))
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 0, self.err)
        self.assertIn("targetDuration: <212–417", self.out)
        self.assertIn('youtube: { aspect: "16:9", maxDuration: 480 }', self.out)

    def status_path(self):
        return os.path.join(self.repo, "studio", "cast", "narrator", "status.json")

    def test_no_ready_narrator_stops(self):
        st = json.loads(read(self.status_path()))
        st["voice"]["ko"]["state"] = "building"
        write(self.status_path(), json.dumps(st))
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 1)
        self.assertIn("has no ready voice.ko", self.err)
        self.assertIn("narrator setup", self.err)
        del st["voice"]["ko"]
        st["voice"]["ja"] = {"engine": "qwen:Ono_Anna", "style": "", "state": "ready"}
        write(self.status_path(), json.dumps(st))
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 1)

    def test_empty_style_is_none(self):
        st = json.loads(read(self.status_path()))
        st["voice"]["ko"]["style"] = ""
        write(self.status_path(), json.dumps(st))
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 0, self.err)
        self.assertIn('narrator: { voice: "qwen:Sohee" }', self.out)
        # the cast check takes no style as the actor's empty style (both sides none)
        probs, chosen = vcast.actor_problems('---\ncast:\n  narrator: { voice: "qwen:Sohee" }\n---\n', "ko", [],
                                             {"narrator": st})
        self.assertEqual((probs, chosen), ([], {"narrator": "narrator"}))

    def test_style_limited_at_setup(self):
        self.assertTrue(frontmatter.style_ok("차분하게, 또박또박"))
        for bad in ('따옴표 "x"', "역슬래시 \\", "두\n줄"):
            self.assertFalse(frontmatter.style_ok(bad), bad)
        from stdo.setup import configcmd, initcmd
        with self.assertRaises(initcmd.SetupError) as cm:
            initcmd.normalize(self.repo, {"language": "ko", "project_name": "p", "narrator": {"style": 'a "b"'},
                                          "s2v_path": "/abs/s2v"})
        self.assertIn("must not hold", str(cm.exception))
        with self.assertRaises(configcmd.SetupError) as cm:
            configcmd.narrator_preview(self.repo, "ko", "qwen:Sohee", "a\\b")
        self.assertIn("without", str(cm.exception))


class CastAtScript(FlowCase):
    def setUp(self):
        super().setUp()
        self.to_script()

    def test_the_narration_check_reads_the_cast_block(self):
        self.assertEqual(self.check("--narration"), 0, self.out)
        p = os.path.join(self.vdir, "script.ko.md")
        text = read(p)
        write(p, CAST_BLOCK.sub("", text, count=1))
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("the script's cast must be the default narrator's block exactly", self.out)
        self.assertIn('`cast: /   narrator: { voice: "qwen:Sohee", style: "차분하게" }`', self.out)
        write(p, text.replace('style: "차분하게"', 'style: "밝게"'))
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("default narrator's block", self.out)
        write(p, text.replace('"qwen:Sohee"', '"qwen:Ryan"'))
        self.assertEqual(self.check("--narration"), 1)
        write(p, text)
        self.assertEqual(self.check("--narration"), 0, self.out)


# ---------------------------------------------------------------- §3: record-brief --from

class RecordBrief(FlowCase):
    def setUp(self):
        super().setUp()
        from stdo.source import cli as src_cli
        self.assertEqual(self.run_fn(src_cli.resolve_main, "v1"), 0, self.err)
        self.claims_md()
        self.assertEqual(self.run_fn(src_cli.scope_main, "v1"), 0, self.err)
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        self.brief = {"claims": [cid(E1), cid(E2)], "roles": [{"name": "narrator"}], "outputs": ["youtube"],
                      "platforms": {"youtube": ["youtube"]}}
        write(os.path.join(self.vdir, "work", "brief.json"), json.dumps(self.brief))

    def test_forms(self):
        for src in ("work/brief.json", "studio/videos/v1/work/brief.json",
                    os.path.join(self.vdir, "work", "brief.json")):
            self.assertEqual(self.state("record-brief", "v1", "--from", src), 0, "%s: %s" % (src, self.err))

    def test_outside_is_refused(self):
        write(os.path.join(self.repo, "brief.json"), json.dumps(self.brief))
        self.assertEqual(self.state("record-brief", "v1", "--from", "brief.json"), 2)
        self.assertIn("inside the video folder", self.err)
        self.assertIn(os.path.join(self.repo, "brief.json"), self.err)  # the tried path is named
        self.assertEqual(self.state("record-brief", "v1", "--from", os.path.join(self.repo, "brief.json")), 2)
        self.assertEqual(self.state("record-brief", "v1", "--from", "work/../../../../brief.json"), 2)
        self.assertEqual(self.state("record-brief", "v1", "--from", "work/none.json"), 2)
        self.assertIn("no brief file at", self.err)
        link = os.path.join(self.vdir, "work", "link.json")
        os.symlink(os.path.join(self.repo, "brief.json"), link)
        self.assertEqual(self.state("record-brief", "v1", "--from", "work/link.json"), 2)  # resolved, then judged


# ---------------------------------------------------------------- §1.1 (defence in depth): store.video_dir

class VideoIdRefused(FlowCase):
    def test_not_a_video_id_is_usage(self):
        for bad in ("../v1", "v1/..", "V1", ".", "a/b", "v_1"):
            self.assertEqual(self.state("next", bad), 2, bad)
            self.assertIn("not a video id", self.err)
        with self.assertRaises(Exception):
            store.video_dir(self.repo, "studio", "../videos/v1")
        self.assertEqual(store.video_dir(self.repo, "studio", "v1"), self.vdir)


# ---------------------------------------------------------------- §4: every s2v message

class LintMessages(unittest.TestCase):
    def result(self, n, message="m"):
        diags = [{"severity": "warning", "code": "target-duration", "message": "%s %d" % (message, i)}
                 for i in range(n)]
        return s2vlint.Result("lint", 0, diags, [], "ko")

    def test_every_message_cut_and_counted(self):
        r = self.result(3)
        self.assertEqual(r.problems("x.json"), ["s2v lint: target-duration", "s2v lint: m 0", "s2v lint: m 1",
                                                "s2v lint: m 2"])
        r = self.result(12)
        p = r.problems("studio/videos/v1/work/ko/checks/script.json")
        self.assertEqual(len(p), 1 + 10 + 1)
        self.assertEqual(p[-1], "… 2 more in studio/videos/v1/work/ko/checks/script.json")
        long = self.result(1, "x" * 400).problems()
        self.assertEqual(len(long[1]), len("s2v lint: ") + s2vlint.MESSAGE_MAX)
        self.assertTrue(long[1].endswith("…"))

    def test_errors_too(self):
        r = s2vlint.Result("lint", 1, [{"severity": "error", "code": "schema", "message": "Invalid option: aspect"}],
                           [], "ko")
        self.assertEqual(r.problems(), ["s2v lint: schema", "s2v lint: Invalid option: aspect"])


class TargetDurationMessage(FlowCase):
    def test_the_target_duration_failure_prints_its_message(self):
        self.to_script()
        self.script(target=60)
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("s2v lint: target-duration", self.out)
        self.assertRegex(self.out, r's2v lint: "youtube" is 0:06 \(estimated\), -\d+% from targetDuration 1:00 '
                                   r'\(tolerance ±15%\)')


# ---------------------------------------------------------------- §5: the targetDuration range

class TargetRange(unittest.TestCase):
    CRIT = {"length_seconds": {"min": 180, "max": 480}, "chars_per_sec": {"ko": 5.5}, "cer_max": {"ko": 0.15}}

    def problems(self, target, crit=None):
        text = "---\noutputs:\n  youtube: { maxDuration: 480 }\ntargetDuration: %s\n---\n" % target
        # 1100 characters: about 200 s by Studio's own estimate (inside 180–480)
        return ccheck.length_problems(text, ["youtube"], crit or self.CRIT, [{"text": "가" * 1100}], "ko",
                                      ".claude/studio/formats/youtube.md")

    def test_bounds(self):
        self.assertEqual(ccheck.target_range(self.CRIT["length_seconds"]), (212, 417))
        for t in (211, 418, 185):
            p = self.problems(t)
            self.assertEqual(len(p), 1, (t, p))
            self.assertIn("targetDuration must be a number within 212–417 s (it is %s)" % t, p[0])
            self.assertIn("within ±15 % of targetDuration", p[0])
            self.assertIn("never move targetDuration out of it", p[0])
        for t in (212, 417, 300):
            self.assertEqual(self.problems(t), [], t)

    def test_exact_bounds_are_not_float_noise(self):
        self.assertEqual(ccheck.target_range({"min": 170, "max": 230}), (200, 200))

    def test_empty_range_names_the_format(self):
        crit = dict(self.CRIT, length_seconds={"min": 180, "max": 200})
        self.assertIsNone(ccheck.target_range(crit["length_seconds"]))
        p = [x for x in self.problems(190, crit) if "too narrow" in x]
        self.assertEqual(len(p), 1)
        self.assertIn("too narrow for s2v's ±15 % targetDuration tolerance", p[0])
        self.assertIn(".claude/studio/formats/youtube.md", p[0])


# ---------------------------------------------------------------- §6: claims map and on-screen text

class ScreenText(unittest.TestCase):
    CM = {"claims": {cid(E1): {"excerpt": E1, "sentences": [S1]}, cid(E2): {"excerpt": E2, "sentences": [S2]}},
          "excerpts": [E1, E2]}

    def test_s7_names_the_text_and_where_it_is(self):
        screen = [{"text": "체크인 카운터 3번"}]
        draft = {"sentences": [
            {"text": S1, "kind": "fact", "verdict": "supported", "claims": [cid(E2)], "excerpts": [E2]},
            {"text": "체크인 카운터 3번", "kind": "fact", "verdict": "supported", "claims": [cid(E1)],
             "excerpts": [E1]},
            {"text": S2, "kind": "fact", "verdict": "supported", "claims": [cid(E2)], "excerpts": [E2]},
            {"text": "출국 2번", "from": "title", "kind": "fact", "verdict": "supported", "claims": [cid(E2)],
             "excerpts": [E2]}]}
        out = ccheck.draft_problems(draft, self.CM, Text(E1 + "\n" + E2), [{"text": S1}, {"text": S2}], screen,
                                    ["출국 2번"])
        self.assertIn('sentence 1 (narration): "%s" — %s does not list it in the claims map; add it to that '
                      "claim's sentences" % (S1, cid(E2)), out)
        self.assertIn('sentence 2 (screen): "체크인 카운터 3번" — %s does not list it in the claims map; add it to that '
                      "claim's sentences" % cid(E1), out)
        self.assertIn('sentence 4 (title): "출국 2번" — %s does not list it' % cid(E2), " ".join(out))

    def test_text_cut_at_60(self):
        t = "가" * 80
        out = ccheck.draft_problems({"sentences": [{"text": t, "kind": "fact", "verdict": "supported",
                                                    "claims": [cid(E1)], "excerpts": [E1]}]},
                                    self.CM, Text(E1), [{"text": t}], [])
        self.assertIn('sentence 1 (narration): "%s…" —' % ("가" * 59), " ".join(out))

    def test_warning_for_unlisted_screen_text(self):
        cm = {"claims": {cid(E1): {"excerpt": E1, "sentences": [S1, "空港(くうこう)"]}}}
        w = ccheck.screen_warnings([{"text": "空港(くうこう)"}, {"text": "手荷物"}, {"text": "게이트 12"},
                                    {"text": "탑승"}, {"text": "手荷物"}], cm)
        self.assertEqual(len(w), 2)
        self.assertIn('on-screen text "手荷物" has digits or kanji and no claim lists it', w[0])
        self.assertIn('"게이트 12"', w[1])


class ScreenTextFlow(FlowCase):
    def setUp(self):
        super().setUp()
        self.to_script()

    def test_warning_is_not_a_failure(self):
        self.cmap(claims={cid(E1): {"excerpt": E1, "sentences": [S1]}, cid(E2): {"excerpt": E2, "sentences": [S2]}})
        self.assertEqual(self.check("--narration"), 0, self.out)
        self.assertIn('warning: on-screen text "空港(くうこう)" has digits or kanji', self.out)
        self.assertTrue(self.result()["details"]["warnings"])

    def test_skeleton_from_round_trip(self):
        self.assertEqual(self.check("--narration"), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "script"), 0, self.err)
        self.assertEqual(self.check("--skeleton"), 0, self.out)
        p = os.path.join(self.w, "verify.draft.json")
        entries = json.loads(read(p))["sentences"]
        froms = {e["text"]: e["from"] for e in entries}
        self.assertEqual(froms[S1], "narration")
        self.assertEqual(froms["空港(くうこう)"], "screen")
        self.assertEqual(froms["출국"], "screen")  # a title label is on-screen text first
        entries[0].update(verdict="supported", note="kept", **{"from": "title"})  # a changed `from` is put back
        write(p, json.dumps({"sentences": entries}, ensure_ascii=False))
        self.assertEqual(self.check("--skeleton"), 0, self.out)
        again = json.loads(read(p))["sentences"]
        self.assertEqual((again[0]["verdict"], again[0]["note"], again[0]["from"]), ("supported", "kept", "narration"))


# ---------------------------------------------------------------- §7: excerpts

class Excerpts(unittest.TestCase):
    def test_the_pilots_midori_line(self):
        copy_raw = "# 공항\n\n" + MIDORI + "\n"
        copy = Text(copy_raw)
        stopped = "<strong><ruby>緑"
        self.assertTrue(ccheck.open_tag_at_end(stopped))
        self.assertIn("stops inside a tag", ccheck.excerpt_problems("C-1", stopped, copy, copy_raw)[0])
        self.assertTrue(ccheck.open_tag_at_end("<strong><ruby"))
        half = MIDORI_WHOLE[:MIDORI_WHOLE.index("人が")]
        self.assertEqual(ccheck.excerpt_problems("C-2", half, copy, copy_raw),
                         ["excerpt of C-2 stops mid-sentence — copy the whole sentence"])
        self.assertEqual(ccheck.excerpt_problems("C-3", MIDORI_WHOLE, copy, copy_raw), [])
        self.assertEqual(ccheck.excerpt_problems("C-4", "赤の通路は申告する人の出口です。", copy, copy_raw), [])
        self.assertIn("is not in the source copy", ccheck.excerpt_problems("C-5", "青の通路", copy, copy_raw)[0])

    def test_closed_tags_and_void_tags(self):
        self.assertFalse(ccheck.open_tag_at_end("<strong>a</strong>b<br>c"))
        self.assertFalse(ccheck.open_tag_at_end("a<img src=x>b"))
        self.assertTrue(ccheck.open_tag_at_end("a <span>b"))
        self.assertTrue(ccheck.open_tag_at_end("a </stro"))
        self.assertFalse(ccheck.open_tag_at_end("料金は 3 < 5 ドルです。"))

    def test_dots_that_end_no_sentence(self):
        for line in ("緑の通路 (https://example.com/a.html)", "緑の通路 1.5 km", "緑の通路 e.g.x"):
            self.assertFalse(ccheck.stops_mid_sentence("緑の通路", line + "\n"), line)
        self.assertTrue(ccheck.stops_mid_sentence("緑の通路", "緑の通路です. 次\n"))
        self.assertTrue(ccheck.stops_mid_sentence("緑の通路", "緑の通路です。\n"))


class SourceExcerpts(FlowCase):
    def test_source_check_reads_the_copy(self):
        stopped = E1[:E1.index("<rp>")]  # "공항(<ruby>空港"
        half = E2[:E2.index(" 출국")]  # "탑승권을 받으면"
        with open(os.path.join(self.vdir, "work", "source.md"), "w") as f:
            f.write("## Claims\n- %s: a\n  > %s\n- %s: b\n  > %s\n- %s: c\n  > %s\n" % (
                cid(stopped), stopped, cid(half), half, cid(E2), E2))
        self.assertEqual(self.run_fn(__import__("stdo.claims.cli", fromlist=["main"]).main, "v1", "--source"), 1)
        self.assertIn("excerpt of %s stops inside a tag" % cid(stopped), self.out)
        self.assertIn("excerpt of %s stops mid-sentence" % cid(half), self.out)
        self.assertIn("line 6  %s  ok\n" % cid(E2), self.out)


# ---------------------------------------------------------------- §8: the ② block

class GateTwoGuard(JudgeCase):
    H = "3f2a9c0d1e4b"

    def setUp(self):
        super().setUp()
        import transcripts as TR
        self.TR = TR
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        self.tpath = TR.transcript_path(self.env)
        st = F.state()
        st["video"] = "v"
        self.lines = ['- "공항에 가면 먼저 체크인 카운터를 찾습니다." — the longest sentence',
                      "발음 空港 → 쿠우코오", "read: studio/out/v/ko/audition/audition.md"]
        st["langs"]["ko"]["shown"] = {"2": {"-": {"hash": "x", "at": "t", "lines": self.lines}}}
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump(st, f, ensure_ascii=False)

    def run_hook(self, qtext):
        t = self.TR.approval_turn(self.TR.T(), "승인 v %s" % self.H, qtext=qtext)
        t.write(self.tpath)
        hook = {"tool_name": "Bash", "tool_input": {"command": "python3 .claude/studio/scripts/state.py approve v 2 "
                                                               "--expect %s" % self.H},
                "cwd": self.repo, "session_id": "sess-1", "transcript_path": self.tpath, "permission_mode": "default",
                "tool_use_id": "toolu_cmd1", "prompt_id": t.prompt}
        from stdo.guard import judge
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def test_the_recorded_lines_are_compared(self):
        base = "[v] ② 오디션 — studio/out/v/ko/audition/narrator.wav · hash %s" % self.H
        deny, _ctx = self.run_hook("\n".join([base] + self.lines))
        self.assertIsNone(deny, deny and deny.message())
        edited = [self.lines[0].replace("카운터", "카운타")] + self.lines[1:]
        deny, _ctx = self.run_hook("\n".join([base] + edited))
        self.assertEqual(deny.rule, "G-EVIDENCE")
        deny, _ctx = self.run_hook("\n".join([base] + self.lines[:-1]))  # the read: line is checked too
        self.assertEqual(deny.rule, "G-EVIDENCE")


# ---------------------------------------------------------------- §9: floor_text

class FloorText(FlowCase):
    def test_floor_text_is_the_credits_floor(self):
        from stdo import credits
        from stdo.source import cli as src_cli
        self.assertEqual(self.run_fn(src_cli.resolve_main, "v1"), 0, self.err)
        img = assets_mod.read(self.vdir)["images"][0]
        self.assertEqual((img["floor"], img["floor_text"]), ("public", "public/-"))
        self.assertEqual(img["floor_text"], credits.floor_of(img))
        self.assertEqual(credits.floor_of({"floor": "unknown", "floor_reason": "outside visibility.public"}),
                         "unknown/outside visibility.public")


# ---------------------------------------------------------------- §10: the source URL

class SourceUrl(FlowCase):
    def setUp(self):
        super().setUp()
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        cfg = json.loads(read(p))
        cfg["public_domains"] = ["example.com"]
        write(p, json.dumps(cfg))

    def url(self):
        return store.read_state(self.vdir)["source"].get("url")

    def test_accepted_and_refused(self):
        self.assertEqual(self.state("record-source", "v1", "--url", "https://example.com/posts/airport?lang=ko"), 0,
                         self.err)
        self.assertEqual(self.url(), "https://example.com/posts/airport?lang=ko")
        self.assertIn("source url: https://example.com/posts/airport?lang=ko", self.out)
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)  # no --url: the stored one stays
        self.assertEqual(self.url(), "https://example.com/posts/airport?lang=ko")
        for bad in ("http://example.com/a", "https://other.com/a", "https://example.com.evil.net/a",
                    "https://user@example.com/a", "https://example.com:8443/a", "https://example.com/a#top",
                    "https://example.com/a?token=x", "https://example.com/a?SessionId=1", "https://example.com",
                    "https://example.com/a b", "https://example.com/<a>", "javascript:alert(1)", ""):
            self.assertEqual(self.state("record-source", "v1", "--url", bad), 2, bad)
        self.assertEqual(self.url(), "https://example.com/posts/airport?lang=ko")
        self.assertEqual(self.state("record-source", "v1", "--url", "https://Example.com/A"), 0, self.err)
        self.assertEqual(self.state("record-source", "v1", "--url", "none"), 0, self.err)
        self.assertIsNone(self.url())

    def test_no_public_domains(self):
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        cfg = json.loads(read(p))
        cfg["public_domains"] = []
        write(p, json.dumps(cfg))
        self.assertEqual(self.state("record-source", "v1", "--url", "https://example.com/a"), 2)
        self.assertIn("none set", self.err)


class CopySourceLine(CopyCase):
    def test_copy_check_with_and_without_the_url(self):
        self.to_four_a()
        self.ready()
        self.assertEqual(self.validate(), 0, self.out)
        self.assertEqual(self.state("next", "v1", "--enter", "copy", "--platform", "youtube"), 0, self.err)
        self.assertNotIn("in the description:", self.out)
        st = store.read_state(self.vdir)
        st["source"]["url"] = "https://example.com/posts/airport"
        write(os.path.join(self.vdir, "work", "state.json"), json.dumps(st, ensure_ascii=False))
        self.assertEqual(self.state("next", "v1", "--enter", "copy", "--platform", "youtube"), 0, self.err)
        self.assertIn("in the description: 원문: https://example.com/posts/airport", self.out)
        self.assertEqual(self.validate(), 1)
        self.assertIn("the source link line is missing: 원문: https://example.com/posts/airport", self.out)
        self.write_copy(notice="원문: https://example.com/posts/airport\n\n" + "이 영상의 내레이션은 AI 합성 음성입니다.")
        self.assertEqual(self.validate(), 0, self.out)  # and the line is no fact the fact-checker must judge


class SourceLabel(StudioTestCase):
    def test_labels(self):
        from stdo import criteria
        self.assertEqual(criteria.source_label(None, "ko"), "원문")
        self.assertEqual(criteria.source_label(None, "ja"), "原文")
        self.assertEqual(criteria.source_label(None, "fr"), "Source")
        self.assertEqual(criteria.source_label({"source_label": {"ko": "출처 글"}}, "ko"), "출처 글")
        tmpl = read(os.path.join(helpers.SKILL, "templates", "formats", "youtube.md"))
        self.assertEqual(criteria.parse(tmpl, ("ko",))["source_label"]["ko"], "원문")
        with self.assertRaises(criteria.Missing):
            criteria.parse(tmpl.replace('"ko": "원문"', '"ko": 1'), ("ko",))


# ---------------------------------------------------------------- §11: brand lines

class BrandLines(StudioTestCase):
    BRAND = {"name": "Site", "accent_color": "#EC174F", "logo": "public/img/logo.png"}

    def test_first_install(self):
        lines, _l = values.settings({}, {}, [], brand=(None, json.dumps(self.BRAND).encode()))
        self.assertEqual(lines, ['brand.accent_color: (없음) → "#EC174F"', "brand.logo: (없음) → \"public/img/logo.png\"",
                                 'brand.name: (없음) → "Site"'])

    def test_changed_colour(self):
        new = dict(self.BRAND, accent_color="#112233")
        lines, _l = values.settings({}, {}, [], brand=(json.dumps(self.BRAND).encode(), json.dumps(new).encode()))
        self.assertEqual(lines, ['brand.accent_color: "#EC174F" → "#112233"'])
        self.assertEqual(values.settings({}, {}, [], brand=None)[0], [])
        blk = values.block({}, {}, [], [], [], "t" * 40, False, brand=(json.dumps(self.BRAND).encode(),
                                                                       json.dumps(new).encode()))
        self.assertEqual(blk["shown"], ['brand.accent_color: "#EC174F" → "#112233"'])


# ---------------------------------------------------------------- §13: ask-before

class AskBefore(FlowCase):
    def ask(self, video="v1"):
        return store.read_state(os.path.join(self.repo, "studio", "videos", video)).get("ask_before")

    def test_begin_stores_and_ask_before_changes(self):
        self.assertEqual(self.state("begin", "v2", "--source", "docs/airport.md", "--kind", "youtube",
                                    "--ask-before", "render,tts"), 0, self.err)
        self.assertIn("ask before: tts, render", self.out)
        self.assertEqual(self.ask("v2"), ["tts", "render"])
        self.assertEqual(self.ask("v1"), [])
        self.assertEqual(self.state("ask-before", "v2", "copy,commit"), 0, self.err)
        self.assertEqual(self.ask("v2"), ["copy", "commit"])
        self.assertEqual(self.state("ask-before", "v2", "none"), 0, self.err)
        self.assertEqual(self.ask("v2"), [])
        for bad in ("tts,cast", "audition", "", "tts,"):
            self.assertEqual(self.state("ask-before", "v2", bad), 2, bad)
        self.assertEqual(self.state("ask-before", "v2"), 2)
        self.assertEqual(self.state("begin", "v3", "--source", "docs/airport.md", "--kind", "youtube",
                                    "--ask-before", "voice"), 2)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "studio", "videos", "v3")))


class AskBeforeAtTts(VoiceCase):
    def test_next_prints_the_line_at_tts(self):
        self.assertEqual(self.state("ask-before", "v1", "tts,render"), 0, self.err)
        self.to_cast()
        self.assertEqual(self.state("next", "v1", "--enter", "tts"), 0, self.err)
        self.assertIn("ask the person before tts (they asked)", self.out)
        self.assertEqual(self.state("next", "v1"), 0, self.err)
        self.assertIn("next tts", self.out)
        self.assertIn("ask the person before tts (they asked)", self.out)
        self.assertEqual(self.state("next", "v1", "--enter", "tts", "--json"), 0, self.err)
        self.assertEqual(json.loads(self.out)["ask_before"], "tts")
        self.assertEqual(self.state("ask-before", "v1", "render"), 0, self.err)
        self.assertEqual(self.state("next", "v1", "--enter", "tts"), 0, self.err)
        self.assertNotIn("ask the person", self.out)


class AskBeforeGuard(JudgeCase):
    def test_no_deny_and_no_allow(self):
        import transcripts as TR
        from stdo.guard import judge
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        tpath = TR.transcript_path(self.env)
        t = TR.T()
        t.write(tpath)
        for cmd in ("python3 .claude/studio/scripts/state.py ask-before v tts,render",
                    "python3 .claude/studio/scripts/state.py ask-before v none"):
            hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                    "transcript_path": tpath, "permission_mode": "default", "tool_use_id": "toolu_x"}
            deny, ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
            self.assertIsNone(deny, deny and deny.message())
            self.assertFalse(getattr(ctx, "allow", None), cmd)


# ---------------------------------------------------------------- §14: the ③ and ④a blocks

class GateThreeBlock(BoardCase):
    def test_snapshot_prints_the_block(self):
        import contextlib
        import io
        from stdo import s2vrun
        self.to_board()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(s2vrun.main(["snapshot", "v1", "--output", "youtube"], providers=self.providers,
                                         cwd=self.repo), 0, err.getvalue())
        text = out.getvalue()
        h = [l.split()[1] for l in text.splitlines() if l.startswith("hash12 ")][0]
        block = text.split("question (paste unchanged as the AskUserQuestion question; add the auditor's findings "
                           "after it):\n", 1)[1].split("end of question", 1)[0]
        self.assertEqual(block, "[v1] ③ 정지 화면 — studio/out/v1/ko/youtube.ko.frames · hash %s\n" % h)


class GateBlockOneOutput(unittest.TestCase):
    def test_named_output_only(self):
        from unittest import mock
        from stdo.state import gates
        with mock.patch.object(gates, "scopes", return_value=["youtube", "shorts"]):
            self.assertEqual(gates._outs34({}, "ko", "3", "shorts"), ["shorts"])
            self.assertEqual(gates._outs34({}, "ko", "3", None), ["youtube", "shorts"])


class GateFourABlock(CopyCase):
    def test_shown_4a_prints_the_block(self):
        self.assertEqual(self.run_render(), 0, self.err)
        self.assertEqual(self.state("record-render", "v1", "--output", "youtube"), 0, self.err)
        self.assertEqual(self.state("stage-done", "v1", "render", "--output", "youtube"), 0, self.err)
        self.assertEqual(self.state("shown", "v1", "4a", "--output", "youtube"), 0, self.err)
        h = [l.split()[1] for l in self.out.splitlines() if l.startswith("hash12 ")][0]
        mp4 = store.read_state(self.vdir)["langs"]["ko"]["renders"]["youtube"]["file"]
        lines = self.out.split("end of question")[0].splitlines()
        i = lines.index("[v1] ④a 최종 — %s · hash %s" % (mp4, h))
        self.assertTrue(lines[i - 1].startswith("question (paste unchanged"))
        self.assertIn("소리·자막·그림이 함께 맞는지", lines[i + 1])
        self.assertEqual(len(lines), i + 2)

    def test_ask_before_render(self):
        self.assertEqual(self.state("ask-before", "v1", "render"), 0, self.err)
        self.assertEqual(self.state("next", "v1", "--enter", "render", "--output", "youtube"), 0, self.err)
        self.assertIn("ask the person before render (they asked)", self.out)


if __name__ == "__main__":
    unittest.main()
