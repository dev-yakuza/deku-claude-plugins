"""M1f (m1-plan §8): cast (check_assets.py --actors), tts under the machine lock and check_tts.py, audition.py, gate ②
with pronounce-approved.json, plus the M1e final re-review items U1 (particle-stripped words stay nouns), U2 (a merge's
diffstat against its first parent) and the native ordinals with 째."""

import contextlib
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import wave

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo.claims import linkrule
from stdo.state import cli, evidence, harnessgate, router, schema, shown as shown_mod, stagechecks, store
from stdo.state.argv import argv_sha
from stdo.state.hashes import file_sha
from stdo.voice import audition as aud, cli as vcli, frontmatter, pronounce, tts
from test_guard_judge import JudgeCase
from test_m1e import FAKE_ROOT, S1, S2, FlowCase, cid, E1, E2

SESSION = "sess-m1f"
MAIN_JS = os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js")
S1_ID, S2_ID = "airport:0:0", "exit:0:0"


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class VoiceCase(FlowCase):
    """A video at ① approved, with the fake s2v."""

    def setUp(self):
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.tool = 0
        self.to_script()
        self.assertEqual(self.check("--narration"), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "script"), 0, self.err)
        self.draft()
        self.assertEqual(self.check(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "verify"), 0, self.err)
        self.approve("1")
        self.roster = {os.path.basename(os.path.dirname(p)): json.load(open(p))
                       for p in glob.glob(os.path.join(self.repo, "studio", "cast", "*", "status.json"))}
        nid = sorted(self.roster)[0]
        v = self.roster[nid]["voice"]["ko"]
        self.voice, self.style = v["engine"], v["style"]

    # ---- helpers ----
    def draft(self):
        d = {"sentences": [
            {"text": S1, "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]},
            {"text": "空港(くうこう)", "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]},
            {"text": S2, "kind": "fact", "verdict": "supported", "claims": [cid(E2)], "excerpts": [E2]}]}
        with open(os.path.join(self.w, "verify.draft.json"), "w") as f:
            json.dump(d, f, ensure_ascii=False)

    def pend(self, argv, answer):
        self.tool += 1
        ev = {"schema": 1, "argv_sha": argv_sha(list(argv)), "session_id": SESSION, "tool_use_id": "toolu_%d" % self.tool,
              "question_index": 0, "question": "Approve?", "answer": answer, "mode": "human", "written_at": stamp()}
        os.makedirs(evidence.local_dir(self.repo), exist_ok=True)
        with open(evidence.pending_path(self.repo), "w") as f:
            json.dump(ev, f)

    def show(self, gate):
        self.assertEqual(self.state("shown", "v1", gate), 0, self.err)
        return [l.split()[1] for l in self.out.splitlines() if l.startswith("hash12 ")][0]

    def approve(self, gate, h=None, code=0):
        h = h or self.show(gate)
        argv = ["approve", "v1", gate, "--expect", h]
        self.pend(argv, "승인 v1 %s" % h)
        self.assertEqual(self.state(*argv), code, self.err)
        return h

    def cast_script(self, voice=None, style=None, pron=(("空港", "쿠우코오"),), extra=""):
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        head = "cast:\n  narrator: { voice: \"%s\", style: \"%s\" }\n" % (voice or self.voice, style or self.style)
        if pron:
            head += "pronounce:\n" + "".join("  %s: %s\n" % kv for kv in pron)
        text = text.replace("lang: ko\n", "lang: ko\n" + head + extra, 1)
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text)

    def changes(self, obj):
        with open(pronounce.path_changes(self.vdir, "ko"), "w") as f:
            json.dump(obj, f, ensure_ascii=False)

    def run_v(self, fn, *argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fn(list(argv), cwd=self.repo, **kw)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def actors(self, *extra):
        return self.run_v(vcli.assets_main, "v1", "--actors", *extra, providers=self.providers)

    def to_cast(self):
        self.cast_script()
        self.changes({"空港": "쿠우코오"})
        self.assertEqual(self.actors(), 0, self.out + self.err)
        self.assertEqual(self.state("stage-done", "v1", "cast"), 0, self.err)

    def synth(self, *extra, scenario=None):
        if scenario is not None:
            self.scenario(scenario)
        r = subprocess.run(["node", MAIN_JS, "tts", os.path.join(self.vdir, "script.ko.md")] + list(extra),
                           capture_output=True, text=True, env=dict(os.environ))
        return r.returncode

    def check_tts(self):
        return self.run_v(vcli.tts_main, "v1", providers=self.providers)

    def to_tts(self):
        self.to_cast()
        self.assertEqual(self.synth(), 0)
        self.assertEqual(self.check_tts(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "tts"), 0, self.err)

    def concat(self, argv):
        out = argv[-1]
        listfile = argv[argv.index("-i") + 1]
        with open(listfile) as f:
            files = [l.split("'", 1)[1].rsplit("'", 1)[0] for l in f if l.startswith("file ")]
        with open(out, "wb") as f:
            for p in files:
                with open(p, "rb") as g:
                    f.write(g.read())
        self.joined = files
        return 0

    def audition(self, runner=None):
        return self.run_v(vcli.audition_main, "v1", providers=self.providers, runner=runner or self.concat)

    def to_audition(self):
        self.to_tts()
        self.assertEqual(self.audition(), 0, self.out + self.err)
        self.assertEqual(self.state("stage-done", "v1", "audition"), 0, self.err)


# ---------------------------------------------------------------- carried: U1 · U2 · ordinals

class Carried(StudioTestCase):
    def test_u1_particle_stripped_words_stay_nouns(self):
        ex = ["세관신고서도 미리 써 두면 출입국신고서를 받을 때 편합니다.", "냉장고에 계산서와 교과서를 넣고 캐나다를 지나 샌디에이고로 갑니다."]
        ts = linkrule.terms(ex)
        for n in ("세관신고서", "출입국신고서", "냉장고", "계산서", "교과서", "캐나다", "샌디에이고"):
            self.assertIn(n, ts)
        for verb in ("편합니다", "갑니다"):
            self.assertNotIn(verb, ts)
        self.assertIsNone(linkrule.term_in("그럼 이제 다음으로 넘어가 볼까요?", ts))  # a transition stays a link
        self.assertEqual(linkrule.term_in("세관신고서는 미리 써 둡니다.", ts), "세관신고서")
        self.assertIsNone(linkrule._noun("계산서"))  # a bare word ending like a verb form is still no term

    def test_native_ordinals(self):
        for t in ("둘째 날", "셋째", "다섯째 줄", "열째"):
            self.assertTrue(linkrule.has_number(t), t)
        self.assertFalse(linkrule.has_number("째려보다"))


class MergeDiffstat(FlowCase):
    def test_u2_merge_against_the_first_parent(self):
        helpers.git(self.repo, "checkout", "-q", "-b", "edit")
        with open(os.path.join(self.repo, "docs", "airport.md"), "a") as f:
            f.write("\n가지에서 고친 문장.\n")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "edit on a branch")
        helpers.git(self.repo, "checkout", "-q", "-")
        with open(os.path.join(self.repo, "README.md"), "a") as f:
            f.write("x\n")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "elsewhere")
        helpers.git(self.repo, "merge", "-q", "--no-ff", "--no-verify", "-m", "merge the edit", "edit")
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        cs = store.read_state(self.vdir)["source"]["commits_since_begin"]
        merge = [c for c in cs if c.get("merge")]
        self.assertEqual(len(merge), 1)
        self.assertEqual(merge[0]["stat"], "+2 -0 docs/airport.md")
        from stdo.state import labels
        lines = labels.source_commit_lines(store.read_state(self.vdir))
        self.assertTrue([l for l in lines if l.endswith("merge the edit (+2 -0 docs/airport.md) (merge)")], lines)
        self.assertTrue([l for l in lines if "edit on a branch (+2 -0 docs/airport.md)" in l and "(merge)" not in l])


# ---------------------------------------------------------------- cast

class CastCheck(VoiceCase):
    def test_pass_then_stage_done(self):
        self.to_cast()
        r = stagechecks.read(self.vdir, "ko", "cast")
        self.assertEqual((r["result"], r["details"]["fail_unread"], r["details"]["actors"]),
                         ("pass", True, {"narrator": sorted(self.roster)[0]}))
        self.assertEqual(r["details"]["pronounce_changes"], {"空港": "쿠우코오"})

    def test_unread_word_fails_from_cast_on(self):
        """J32: the same warning that is information at script fails the cast check."""
        self.cast_script()
        self.changes({"空港": "쿠우코오"})
        self.scenario({"lint": {"warnings": [{"code": "unread-word", "message": "\"OK\" may be read as English"}]}})
        self.assertEqual(self.actors(), 1)
        self.assertIn("s2v lint: unread-word", self.out)

    def test_refusals(self):
        self.cast_script(style="밝게")
        self.changes({"空港": "쿠우코오"})
        self.assertEqual(self.actors(), 1)
        self.assertIn("is no actor of the roster", self.out)
        self.cast_script(voice="qwen:Ryan")
        self.assertEqual(self.actors(), 1)
        self.cast_script()
        self.changes({})
        self.assertEqual(self.actors(), 1)
        self.assertIn("is not what the script's pronounce adds", self.out)
        os.remove(pronounce.path_changes(self.vdir, "ko"))
        self.assertEqual(self.actors(), 1)
        self.assertIn("pronounce-changes.json is missing (write {} when", self.out)
        with open(pronounce.path_changes(self.vdir, "ko"), "w") as f:
            f.write('{"空港": ["쿠우코오"]}')
        self.assertEqual(self.actors(), 1)
        self.assertIn("not a flat object", self.out)
        self.changes({"空港": "쿠우코오"})
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace(S2, "탑승권을 받으면 출국 심사를 곧 받습니다."))
        self.assertEqual(self.actors(), 1)
        self.assertIn("content changed since ①", self.out)
        self.assertEqual(self.actors(), 1)
        self.assertEqual(self.run_v(vcli.assets_main, "v1", providers=self.providers), 2)  # the board check: M1g

    def test_no_cast(self):
        self.changes({})
        self.assertEqual(self.actors(), 1)
        self.assertIn("the script has no cast", self.out)

    def test_conflicts_are_information(self):
        with open(os.path.join(self.repo, ".claude", "studio", "pronounce.json"), "w") as f:
            json.dump({"空港": "구우코우"}, f, ensure_ascii=False)
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "a shared reading")
        self.cast_script()
        self.changes({"空港": "쿠우코오"})
        self.assertEqual(self.actors(), 0, self.out)
        self.assertIn("reading elsewhere: 空港: 이 영상 쿠우코오 / HEAD 구우코우 — 공유 사전에는 먼저 커밋된 쪽이 남는다",
                      self.out)
        r = stagechecks.read(self.vdir, "ko", "cast")
        self.assertEqual(r["details"]["conflicts"], [{"key": "空港", "value": "쿠우코오",
                                                       "others": [{"video": "HEAD", "value": "구우코우"}]}])

    def test_frontmatter_and_flat_objects(self):
        t = "---\ncast:\n  narrator:\n    voice: qwen:Sohee\n    style: \"a, b\"\npronounce: { 空港: 쿠우코오, API: 에이피아이 }\n---\n"
        self.assertEqual(frontmatter.block(t, "cast"), {"narrator": {"voice": "qwen:Sohee", "style": "a, b"}})
        self.assertEqual(pronounce.of_script(t), {"空港": "쿠우코오", "API": "에이피아이"})
        self.assertIsNone(frontmatter.block(t, "outputs"))
        self.assertIsNone(pronounce.parse('{"a": 1}'))
        self.assertIsNone(pronounce.parse('[]'))
        self.assertEqual(pronounce.changes({"a": "1", "b": "2"}, {"a": "1", "b": "3"}), {"b": "2"})


# ---------------------------------------------------------------- tts

class TtsCheck(VoiceCase):
    def setUp(self):
        super().setUp()
        self.to_cast()

    def test_pass(self):
        self.assertEqual(self.synth(), 0)
        self.assertEqual(self.check_tts(), 0, self.out)
        with open(tts.exemptions_path(self.vdir, "ko")) as f:
            self.assertEqual(json.load(f), {"schema": 1, "lines": []})
        self.assertEqual(self.state("stage-done", "v1", "tts"), 0, self.err)

    def test_no_asr_is_the_closed_side(self):
        self.assertEqual(self.synth("--no-asr"), 0)
        self.assertEqual(self.check_tts(), 1)
        self.assertIn("has no ASR check", self.out)

    def test_retry_twice_then_exempt(self):
        sc = {"sentences": {S1_ID: {"cer": [0.4, 0.3, 0.25]}}}
        self.assertEqual(self.synth(scenario=sc), 0)
        self.assertEqual(self.check_tts(), 1)
        self.assertIn("%s: CER 0.400 over 0.150 — retry it (0 of 2 retries done)" % S1_ID, self.out)
        self.assertEqual(self.check_tts(), 1)  # checking again without a retry counts nothing
        self.assertIn("(0 of 2 retries done)", self.out)
        self.assertIn("--retry %s" % S1_ID, self.out)
        self.assertEqual(self.state("stage-done", "v1", "tts"), 1)
        for n in (2, 3):
            self.assertEqual(self.synth("--retry", S1_ID), 0)
            code = self.check_tts()
        self.assertEqual(code, 0, self.out)
        with open(tts.exemptions_path(self.vdir, "ko")) as f:
            ex = json.load(f)["lines"]
        self.assertEqual([(e["id"], e["retries"], e["why"]) for e in ex], [(S1_ID, 2, "CER 0.250 over 0.150")])
        self.assertEqual(store.read_state(self.vdir)["langs"]["ko"]["tts_retries"][S1_ID]["done"], 2)
        self.assertIn("exempted (shown at ②): %s" % S1_ID, self.out)

    def test_v2_a_kept_take_number_is_no_retry(self):
        """s2v's attempt is the take it kept: one run may keep take 5 — that is no Studio retry."""
        self.assertEqual(self.synth(scenario={"sentences": {S1_ID: {"cer": [0.4]}}}), 0)
        mp = os.path.join(self.vdir, "audio", "ko", "manifest.json")
        with open(mp) as f:
            m = json.load(f)
        for e in m["entries"].values():
            e["attempt"] = 5
        with open(mp, "w") as f:
            json.dump(m, f)
        self.assertEqual(self.check_tts(), 1)
        self.assertIn("retry it (0 of 2 retries done)", self.out)
        with open(tts.exemptions_path(self.vdir, "ko")) as f:
            self.assertEqual(json.load(f)["lines"], [])

    def test_heard_negation(self):
        self.assertEqual(self.synth(scenario={"sentences": {S2_ID: {"heard": ["탑승권을 받으면 출국 심사를 받지 않습니다."]}}}),
                         0)
        self.assertEqual(self.check_tts(), 1)
        self.assertIn("a negation is heard but not written", self.out)

    def test_config_checks_key_is_never_read(self):
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(p) as f:
            cfg = json.load(f)
        cfg["checks"] = {"cer_max": 1.0}
        with open(p, "w") as f:
            json.dump(cfg, f)
        self.assertEqual(self.synth(scenario={"sentences": {S1_ID: {"cer": [0.4]}}}), 0)
        self.assertEqual(self.check_tts(), 1)

    def test_audio_hash_must_be_computable(self):
        self.assertEqual(self.synth(), 0)
        real = self.providers.inspect

        def no_audio(ctx):
            ins = real(ctx)
            ins["hashes"]["audio"] = None
            ins["reasons"] = {"audio": ["1 sentence(s) not synthesized: x"]}
            return ins
        self.providers.inspect = no_audio
        self.assertEqual(self.check_tts(), 1)
        self.assertIn("the audio hash cannot be computed: 1 sentence(s) not synthesized: x", self.out)

    def test_judge_units(self):
        s = [{"id": "a", "text": "3번 게이트", "recorded": True, "lock": None},
             {"id": "b", "text": "게이트 3번", "lock": {"asr": True, "cer": 0.0, "heard": "게이트 5번", "attempt": 1}},
             {"id": "c", "text": "x", "lock": None},
             {"id": "d", "text": "y", "lock": {"asr": True, "cer": None, "heard": "y", "attempt": 1}}]
        problems, retry, exempt, _new = tts.judge(s, 0.15, "ko")
        self.assertEqual(retry, ["b", "d"])
        self.assertTrue(any("numbers 3 heard as 5" in p for p in problems))
        self.assertTrue(any("c is not synthesized" in p for p in problems))
        self.assertFalse(any(p.startswith("a ") for p in problems))  # a person's recording is skipped
        self.assertIsNone(tts.mismatch("문을 열지 않습니다", "문을 열지 않습니다", "ko"))
        # V3: numbers compared as values, however they are written
        self.assertEqual(tts.mismatch("이십 분 걸립니다", "30분 걸립니다", "ko"), "numbers 20 heard as 30")
        self.assertEqual(tts.mismatch("20분 걸립니다", "삼십 분 걸립니다", "ko"), "numbers 20 heard as 30")
        self.assertIsNone(tts.mismatch("이십 분 걸립니다", "20분 걸립니다", "ko"))
        self.assertIsNone(tts.mismatch("스물두 명이 탑니다", "22명이 탑니다", "ko"))
        self.assertEqual(tts.mismatch("세 가지를 봅니다", "가지를 봅니다", "ko"), "a number is missing in what was heard")
        self.assertIsNone(tts.mismatch("이번에는 구분해 봅시다", "이번에는 구분해 봅시다", "ko"))
        self.assertEqual(tts.mismatch("삼 년 전입니다", "5 년 전입니다", "ko"), "numbers 3 heard as 5")
        # V2: a new lock key (another text or voice) starts the count again
        line = [{"id": "x", "text": "y", "lockKey": "k2", "lock": {"asr": True, "cer": 0.9, "heard": "y",
                                                                   "attempt": 2}}]
        p_, retry, ex, new = tts.judge(line, 0.15, "ko", {"x": {"key": "k1", "tried": 1, "done": 2}})
        self.assertEqual((retry, ex, new), (["x"], [], {"x": {"key": "k2", "tried": 2, "done": 0}}))
        p_, retry, ex, new = tts.judge(line, 0.15, "ko", {"x": {"key": "k2", "tried": 1, "done": 1}})
        self.assertEqual((retry, [e["id"] for e in ex]), ([], ["x"]))
        self.assertEqual(tts.mismatch("we do not stop", "we do stop", "en"), "a negation is missing in what was heard")
        self.assertEqual(tts.mismatch("3 gates", "gates", "en"), "a number is missing in what was heard")
        self.assertIsNone(tts.length_warning(300, {"min": 180, "max": 480}))
        self.assertIn("more than 30 %", tts.length_warning(100, {"min": 180, "max": 480}))
        self.assertIsNone(tts.length_warning(130, {"min": 180, "max": 480}))

    def test_length_warning_reaches_the_details(self):
        F.write_format(self.repo, length=(30, 600))  # a few seconds of narration: far under 30 s × 0.7
        self.assertEqual(self.synth(), 0)
        self.assertEqual(self.check_tts(), 0, self.out)
        self.assertIn("warning: the narration is", self.out)
        self.assertIsNotNone(stagechecks.read(self.vdir, "ko", "tts")["details"]["length_warning"])


# ---------------------------------------------------------------- audition and ②

class Audition(VoiceCase):
    def test_pass_and_files(self):
        self.to_audition()
        d = vcli.out_dir(self.repo, "studio", store.read_state(self.vdir), "ko")
        self.assertTrue(os.path.isfile(os.path.join(d, "narrator.wav")))
        with open(os.path.join(d, "audition.md")) as f:
            md = f.read()
        self.assertIn("1. %s — the longest sentence" % S1_ID, md)
        self.assertIn("## Reading changes (pronounce-changes.json)\n\n- 발음 空港 → 쿠우코오 (no sentence says it)", md)
        r = stagechecks.read(self.vdir, "ko", "audition")
        self.assertEqual(r["result"], "pass")
        # touching the outputs never passes it (v5 S4): their sha is an input
        with open(os.path.join(d, "narrator.wav"), "ab") as f:
            f.write(b"\0")
        self.assertEqual(self.state("stage-done", "v1", "audition"), 1)

    def test_pick(self):
        s = [{"id": "a", "text": "짧다", "lockKey": "k1", "lock": {}},
             {"id": "b", "text": "조금 더 긴 문장입니다", "lockKey": "k2", "lock": {}},
             {"id": "c", "text": "3번 게이트", "lockKey": "k3", "lock": {}},
             {"id": "r", "text": "사람이 녹음한 아주 아주 긴 문장입니다", "recorded": True, "lock": {}}]
        got = aud.pick(s, {"a": "k1", "b": "old", "c": "k3"}, [{"id": "a", "why": "CER"}])
        self.assertEqual([(x["id"], w) for x, w in got], [
            ("a", ["exempted: CER"]), ("b", ["the longest sentence", "changed since the last ② approval"]),
            ("c", ["a number or a proper noun"])])
        self.assertEqual([x["id"] for x, _w in aud.pick(s, None, [])], ["b", "c"])  # no ② yet: nothing "changed"
        # V4: a clip for every reading change
        got = aud.pick(s, None, [], ["짧", "긴"])
        self.assertEqual([(x["id"], w) for x, w in got], [
            ("a", ["a number or a proper noun", "pronounce 짧"]), ("b", ["the longest sentence", "pronounce 긴"])])

    def test_ffmpeg_failure_and_absence(self):
        self.to_tts()
        self.assertEqual(self.audition(runner=lambda argv: 1), 1)
        self.assertIn("ffmpeg could not join the clips (exit 1)", self.out)
        from unittest import mock
        with mock.patch.object(vcli.shutil, "which", lambda name: None):
            self.assertEqual(self.run_v(vcli.audition_main, "v1", providers=self.providers), 2)
        self.assertIn("ffmpeg is not on PATH", self.err)

    def test_real_ffmpeg(self):
        """--full: the clips joined by the real ffmpeg (a mono 16-bit WAV of all of them)."""
        if shutil.which("ffmpeg") is None:
            if helpers.full_mode():
                raise AssertionError("--full needs ffmpeg")
            raise unittest.SkipTest("needs ffmpeg")
        if not helpers.full_mode():
            raise unittest.SkipTest("run with run_tests.sh --full")
        clips = []
        for n in range(2):
            p = os.path.join(self.tmp, "c%d.wav" % n)
            with wave.open(p, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"\x01\x00" * 800)
            clips.append(p)
        out = os.path.join(self.tmp, "o", "narrator.wav")
        self.assertEqual(aud.assemble(clips, out, vcli._ffmpeg), 0)
        with wave.open(out, "rb") as w:
            self.assertEqual((w.getnchannels(), w.getnframes()), (1, 1600))


class GateTwo(VoiceCase):
    def test_approve_writes_the_readings_and_the_sentences(self):
        self.to_audition()
        h = self.approve("2")
        st = store.read_state(self.vdir)
        rec = st["langs"]["ko"]["approved"]["2"]
        p = pronounce.path_approved(self.vdir, "ko")
        with open(p) as f:
            self.assertEqual(json.load(f), {"空港": "쿠우코오"})
        self.assertEqual(rec[schema.PRONOUNCE_SHA], file_sha(p))
        self.assertEqual(sorted(rec["sentences"]), [S1_ID, S2_ID])
        # the commit side reads it as this video's valid addition (T1)
        cfg = cli._cfg_of(self.repo)
        per = {}
        harnessgate.approved_additions(self.repo, "studio", self.providers,
                                       lambda vd, lg: cli._ctx(self.repo, cfg, vd, lg), per_video=per)
        self.assertEqual(per, {"v1": {"空港": "쿠우코오"}})
        self.assertTrue(h)

    def test_no_additions_writes_an_empty_object(self):
        self.cast_script(pron=())
        self.changes({})
        self.assertEqual(self.actors(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "cast"), 0, self.err)
        self.assertEqual(self.synth(), 0)
        self.assertEqual(self.check_tts(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "tts"), 0, self.err)
        self.assertEqual(self.audition(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "audition"), 0, self.err)
        self.approve("2")
        with open(pronounce.path_approved(self.vdir, "ko")) as f:
            self.assertEqual(json.load(f), {})

    def test_shown_covers_the_audition_and_the_lists(self):
        self.to_audition()
        a = shown_mod.artifacts({"vdir": self.vdir, "repo": self.repo, "studio_root": "studio"},
                                store.read_state(self.vdir), "ko", "2", shown_mod.ONE)
        self.assertEqual(sorted(a), ["audition_md", "audition_wav", "exemptions", "pronounce_changes"])
        for change in ("exemptions", "audition"):
            h = self.show("2")
            if change == "exemptions":
                with open(tts.exemptions_path(self.vdir, "ko"), "w") as f:
                    f.write('{"lines": [{"id": "x"}], "schema": 1}\n')
            else:
                d = vcli.out_dir(self.repo, "studio", store.read_state(self.vdir), "ko")
                with open(os.path.join(d, "audition.md"), "a") as f:
                    f.write("x\n")
            argv = ["approve", "v1", "2", "--expect", h]
            self.pend(argv, "승인 v1 %s" % h)
            self.assertNotEqual(self.state(*argv), 0, change)

    def test_v1_question_lines_recorded_at_shown(self):
        self.to_audition()
        with open(tts.exemptions_path(self.vdir, "ko"), "w") as f:
            json.dump({"schema": 1, "lines": [{"id": S1_ID, "text": S1, "heard": "공항에 가면", "cer": 0.4}]}, f,
                      ensure_ascii=False)
        self.show("2")
        want = ["면제 %s: \"%s\" → 들림 \"공항에 가면\" (CER 0.4)" % (S1_ID, S1), "발음 空港 → 쿠우코오"]
        for l in want:
            self.assertIn("in the question: %s" % l, self.out)
        from stdo.state import labels
        self.assertEqual(labels.gate2_lines(store.read_state(self.vdir)), want)
        # too many: one line with the file, its sha12 and the counts
        many = [{"id": "s%d" % n, "text": "문장 %d" % n, "heard": "문장", "cer": 0.5} for n in range(50)]
        with open(tts.exemptions_path(self.vdir, "ko"), "w") as f:
            json.dump({"schema": 1, "lines": many}, f, ensure_ascii=False)
        self.show("2")
        lines = labels.gate2_lines(store.read_state(self.vdir))
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^② 목록 파일: work/ko/gate2-lines.txt \(sha [0-9a-f]{12}\) · 면제 50 · 발음 1 · 다른 읽기 0$")
        with open(os.path.join(self.w, "gate2-lines.txt")) as f:
            self.assertEqual(f.read().count("\n"), 51)

    def test_conflicts_recomputed_at_shown(self):
        self.to_audition()
        with open(os.path.join(self.repo, ".claude", "studio", "pronounce.json"), "w") as f:
            json.dump({"空港": "구우코우"}, f, ensure_ascii=False)
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "someone committed a reading meanwhile")
        self.show("2")
        self.assertIn("in the question: 空港: 이 영상 쿠우코오 / HEAD 구우코우", self.out)


# ---------------------------------------------------------------- the router around ②

class RouterVoice(StudioTestCase):
    def test_reading_change_goes_to_tts_and_rework_stales_the_render(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="4a")
        d = router.decide(s, "ko", F.changed(c, voice="v2"))
        self.assertEqual(d.redo["stage"], "tts")  # a pronounce change changes the voice hash
        c2 = F.changed(c, voice="v2", audio="a2")
        F.approve(s, "2", c2)  # ② again with new audio
        d = router.decide(s, "ko", c2)
        self.assertNotEqual(d.redo, None)
        self.assertIn(d.redo["stage"], ("board",))  # ③ · ④a rest on the old audio: from board again, never commit


# ---------------------------------------------------------------- the guard

class GateTwoLines(JudgeCase):
    """V1: the ② question must show each line shown 2 recorded."""
    H = "3f2a9c0d1e4b"

    def test_lines_in_the_question(self):
        import transcripts as TR
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        tpath = TR.transcript_path(self.env)
        st = F.state()
        st["video"] = "v"
        lines = ["면제 a:0:0: \"셋\" → 들림 \"넷\" (CER 0.3)", "발음 空港 → 쿠우코오"]
        st["langs"]["ko"]["shown"]["2"] = {"-": {"hash": "x", "at": "t", "lines": lines}}
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump(st, f)
        cmd = "python3 .claude/studio/scripts/state.py approve v 2 --expect %s" % self.H
        base = "[v] ② 오디션 — studio/out/v/ko/audition/narrator.wav · hash %s" % self.H
        from stdo.guard import judge

        def run(q):
            t = TR.approval_turn(TR.T(), "승인 v %s" % self.H, qtext=q)
            t.write(tpath)
            hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                    "transcript_path": tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                    "prompt_id": t.prompt}
            return judge.decide(hook, self.env, snapshot_loader=self.loader)
        deny, _ = run(base + "\n" + lines[1])
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn(lines[0], deny.message())
        deny, ctx = run(base + "\n" + "\n".join(lines))
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)


class GuardM1f(JudgeCase):
    def test_criteria_and_exemptions_protected(self):
        f = os.path.join(self.repo, ".claude", "studio", "formats", "youtube.md")
        d = self.decide("Edit", {"file_path": f, "old_string": "0.15", "new_string": "0.9"})
        self.assertEqual(d.rule, "G-PROT")
        self.assertDeny("sed -i '' s/0.15/0.9/ .claude/studio/formats/youtube.md", "G-PROT")
        d = self.decide("Write", {"file_path": os.path.join(self.repo, "studio/videos/v/work/ko/exemptions.json"),
                                  "content": "{}"})
        self.assertEqual(d.rule, "G-PROT")
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(
            self.repo, "studio/videos/v/work/ko/pronounce-changes.json"), "content": "{}"}))

    def test_tts_only_under_the_lock_wrapper(self):
        self.assertDeny("s2v tts studio/videos/v/script.md", "G-WRAP")
        self.assertDeny("s2v audio prune studio/videos/v/script.md", "G-WRAP")  # V5
        self.assertPass("python3 .claude/studio/scripts/lock.py run --kind tts -- s2v audio prune "
                        "studio/videos/v/script.md")
        self.assertPass("s2v say hello --voice qwen:Sohee")  # say takes the machine lock itself
        self.assertPass("python3 .claude/studio/scripts/lock.py run --kind tts -- s2v tts studio/videos/v/script.md")
        for cmd in ("python3 .claude/studio/scripts/check_assets.py v --actors",
                    "python3 .claude/studio/scripts/check_tts.py v", "python3 .claude/studio/scripts/audition.py v"):
            self.assertPass(cmd)


# ---------------------------------------------------------------- the real mock (--full)

class RealMock(StudioTestCase):
    def test_check_tts_is_1_on_real_mock_entries(self):
        """§8: a real mock lock entry has no ASR, so check_tts never passes on it. The entries are written the way
        s2v's mock records them (`model: mock`) — no TTS or aligner is started; real `s2v sentences` derives asr."""
        path = helpers.s2v_path(self)
        repo = helpers.make_repo(self.tmp)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir)
        script = os.path.join(vdir, "script.ko.md")
        with open(script, "w") as f:
            f.write("---\ntitle: 공항\nlang: ko\ncast:\n  narrator: { voice: \"qwen:Sohee\", style: \"차분하게\" }\n"
                    "outputs:\n  youtube: { aspect: \"16:9\" }\n---\n\n# 시작 {#intro}\n\nnarrator: 안녕하세요.\n")
        env = helpers.s2v_env(os.path.join(self.tmp, "s2v"))
        run = lambda: subprocess.run(["node", helpers.s2v_main(path), "sentences", script, "--json"],
                                     capture_output=True, text=True, env=env, cwd=repo)
        r = run()
        self.assertIn(r.returncode, (0, 1), r.stderr)
        sents = json.loads(r.stdout)
        d = os.path.join(vdir, "audio", "ko")
        os.makedirs(d)
        entries = {}
        for n, s in enumerate(sents):
            src = "m%d.wav" % n
            with wave.open(os.path.join(d, src), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"\0\0" * 80)
            entries[s["lockKey"]] = {"src": src, "attempt": 1, "duration": 0.01, "words": [], "model": "mock",
                                     "heard": s["text"]}
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump({"version": 1, "entries": entries}, f)
        sents = json.loads(run().stdout)
        self.assertTrue(all(s["lock"] and s["lock"]["asr"] is False for s in sents), sents)
        problems, _r, _e, _n = tts.judge(sents, 0.15, "ko")
        self.assertTrue(problems and all("has no ASR check" in p for p in problems))
