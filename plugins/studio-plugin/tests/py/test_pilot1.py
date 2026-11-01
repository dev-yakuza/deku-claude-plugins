"""Pilot 1 fixes (0.0.23): P4 — a G-EVIDENCE refusal names the first missing line and `shown` · `credit-preview` print
the question block to paste unchanged; P5 — spaced Korean numbers (`열 다섯 개`, `십 오 분`); P8 — the ignore block
covers what the video commit leaves (CREDITS.draft.yaml, the audio folder) and `/std update` refreshes it; J175 — the
description's byte count (line breaks as CRLF, trailing ones not counted, NFC only)."""

import contextlib
import io
import json
import os
import re
import subprocess
import time

import helpers
import state_fixtures as F
import transcripts as TR
from helpers import StudioTestCase
from stdo import SCRIPTS_VERSION, ignore
from stdo.setup import render, update
from stdo.commit.summary import first_missing, missing_text
from stdo.distribute import check as copy_check
from stdo.guard import judge
from stdo.state import labels, store
from stdo.voice import numbers, tts
from test_e2e_m1 import question_block
from test_guard_judge import JudgeCase
from test_m1c import SID as M1C_SID, InitCase
from test_m1f import S1_ID, VoiceCase
from test_m1g import IMG, BoardCase
from test_m1h import CopyCase, FACT

H = "3f2a9c0d1e4b"
EXPECTED = '근거: "출국 수속은 2시간 안팎으로 끝납니다." ← "출국 수속은 보통 2시간 안팎이다."'
RETYPED = EXPECTED.replace("안팎으로", "안팔으로")


# ---------------------------------------------------------------- P5: spaced numbers

class Numbers(StudioTestCase):
    NEW = [("열 다섯 개", [15]), ("열 다섯.", [15]), ("열다섯", [15]), ("스물 다섯 살", [25]), ("서른 셋", [33]),
           ("마흔 네 명", [44]), ("열 두 시", [12]), ("열 다섯 번째", [15]), ("십 오 분", [15]), ("이십 오 분", [25]),
           ("백 이십", [120]), ("이천 이십 육 년", [2026]), ("십 일 일", [11]), ("이십 오 점 삼", [25.3]),
           # Rev 3: what may follow the chain
           ("이천 이십 육 년에", [2026]), ("이천 이십 육 년부터", [2026]), ("십 오 분에", [15]),
           ("십 오 분이 걸립니다", [15]), ("백 이십 개가", [120]), ("이십 오 년간", [25]), ("오십 오 퍼센트입니다", [55]),
           ("십 이월에", [12]), ("십 일 일에", [11]),
           # standalone native compounds with a particle (Rev 2 NIT 6, Rev 3, Rev 4)
           ("서른 셋이에요", [33]), ("서른셋이에요", [33]), ("열다섯을", [15]), ("열둘이서", [12]), ("열 셋이", [13])]
    SAME = [("십 일", [10]), ("십 일 동안", [10]), ("열 개 다섯 개", [5, 10]), ("열, 다섯", []), ("열. 다섯", []),
            ("열 한", []), ("열 네", []), ("오 십", [10]), ("일 이 삼", []), ("십 백", [10, 100]),
            ("천 만 원", [1000, 10000]), ("이십 일 세기", [20]), ("이십 이 사람", [20]), ("사십 이 점", [40]),
            ("백 일 잔치", [100])]
    # known false joins (accepted: the script and what ASR heard go through the same parser)
    KNOWN = [("문을 열 다섯 사람", [15]), ("그 열 세 개", [13]), ("이십 오 사람", [25])]

    def test_table(self):
        for text, want in self.NEW + self.SAME + self.KNOWN:
            self.assertEqual(numbers.values(text), want, text)

    def test_counted_once(self):
        self.assertEqual(numbers.values("열 다섯 개"), [15])  # rule 2 leaves a counter's number to NATIVE
        self.assertEqual(numbers.values("열다섯 개와 서른 셋"), [15, 33])

    def test_mismatch(self):
        self.assertIsNone(tts.mismatch("단어 15개", "단어 열 다섯 개", "ko"))
        self.assertIsNone(tts.mismatch("15분", "십 오 분", "ko"))
        self.assertEqual(tts.mismatch("15개", "열 여섯 개", "ko"), "numbers 15 heard as 16")

    def test_gate_two_line_not_exempted(self):
        """The pilot's line: `15` heard as `열 다섯` is no mismatch, so no retry and no exemption at ②."""
        line = [{"id": "w", "text": "공항 단어 15개를 봅니다.", "lockKey": "k",
                 "lock": {"asr": True, "cer": 0.05, "heard": "공항 단어 열 다섯 개를 봅니다.", "attempt": 3}}]
        problems, retry, exempt, _new = tts.judge(line, 0.15, "ko", {"w": {"key": "k", "tried": 3, "done": 2}})
        self.assertEqual((problems, retry, exempt), ([], [], []))


# ---------------------------------------------------------------- J175: description bytes

class CopyBytes(StudioTestCase):
    def test_counts(self):
        self.assertEqual(copy_check.description_bytes("가" * 10), 30)
        body = "a" * 4995 + "\nb\nc"  # 4999 bytes, 2 internal LFs: 5001
        self.assertEqual(copy_check.description_bytes(body), 5001)
        self.assertEqual(copy_check.description_bytes("a" * 4998 + "\nb"), 5001)
        self.assertEqual(copy_check.description_bytes("a" * 4997 + "\nb"), 5000)
        self.assertEqual(copy_check.description_bytes("a" * 5000 + "\n\n"), 5000)  # trailing breaks not counted
        self.assertEqual(copy_check.description_bytes("a\r\nb"), copy_check.description_bytes("a\nb"))


class CopyBytesValidate(CopyCase):
    """validate_copy on files: CRLF = LF, 5000 passes and 5001 fails with two line breaks, NFD refused."""

    def setUp(self):
        super().setUp()
        self.to_four_a()
        self.ready()
        self.p = os.path.join(self.repo, "studio", "copy", "v1", "ko", "youtube.md")
        self.text = open(self.p, encoding="utf-8").read()

    def write(self, text, newline=None):
        with open(self.p, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)

    def padded(self, total):
        """The copy with "x" padding before its last line so the description counts `total`."""
        head, body = self.text.split("---\n", 2)[1:]
        n = copy_check.description_bytes(body)
        body = body.rstrip("\n")
        cut = body.rindex("\n")
        body = body[:cut] + "x" * (total - n) + body[cut:] + "\n\n"  # trailing breaks: not counted
        return "---\n%s---\n%s" % (head, body)

    def test_limit_and_line_breaks(self):
        self.write(self.padded(5000))
        self.assertEqual(self.validate(), 0, self.out)
        self.write(self.padded(5001))
        self.assertEqual(self.validate(), 1)
        self.assertIn("the description is 5001 bytes in UTF-8 (line breaks counted as 2, CRLF; at most 5000 bytes)",
                      self.out)
        self.write(self.padded(5000).replace("\n", "\r\n"), newline="")  # CRLF on disk counts the same
        self.assertEqual(self.validate(), 0, self.out)

    def test_nfd_refused(self):
        import unicodedata
        self.write(unicodedata.normalize("NFD", self.text))
        self.assertEqual(self.validate(), 1)
        self.assertIn("the copy is not in NFC (composed) form — save it as NFC", self.out)


# ---------------------------------------------------------------- P4: the refusal names the line

class FirstMissing(StudioTestCase):
    def test_helper(self):
        q = "[v] ④b 배포용 글 — x · hash %s\n%s\n- 발음 空港 → 쿠우코오" % (H, RETYPED)
        self.assertIsNone(first_missing(["발음 空港 → 쿠우코오"], q))  # a bulleted line passes (substring rule)
        self.assertIsNone(first_missing(["원본이 begin 뒤에 커밋됨: abc 긴 제목 (1 file)"],
                                        "원본이 begin 뒤에\n커밋됨: abc 긴 제목 (1 file)"))  # wrapped
        line, k, near, pos = first_missing([EXPECTED, "발음 空港 → 쿠우코오"], q)
        self.assertEqual((line, k, near), (EXPECTED, 1, RETYPED))
        msg = missing_text(first_missing([EXPECTED], q), "`shown`")
        self.assertIn("The question lacks this line (1 of 1 missing), exactly as `shown` printed: %s." % EXPECTED, msg)
        self.assertIn("Closest line in the question: %s" % RETYPED, msg)
        self.assertRegex(msg, r'differs at ".*안팔.*" — expected ".*안팎')
        self.assertIn("Copy the lines from the `shown` output; do not retype them.", msg)
        self.assertIn("No line in the question is close to it.", missing_text(first_missing(["완전히 다른 줄"], q)))

    def test_refusal_path_time(self):
        lines = ["면제 s%d: \"문장 %d\" → 들림 \"문장\" (CER 0.5)" % (n, n) for n in range(60)]
        q = "\n".join(l.replace("문장", "문쟝", 1) for l in lines)
        times = []
        for _ in range(9):
            s = time.monotonic()
            self.assertEqual(first_missing(lines, q)[1], 60)
            times.append(time.monotonic() - s)
        self.assertLess(sorted(times)[4], 0.25)


class GateLinesMessage(JudgeCase):
    """The guard's G-EVIDENCE for ① ② ④b names the first missing line, how many are missing and the closest line."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        self.tpath = TR.transcript_path(self.env)
        self.t = None

    def video(self, st):
        st["video"] = "v"
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump(st, f, ensure_ascii=False)

    def decide(self, cmd, question, label="승인 v %s" % H, extra=None):
        self.t = TR.approval_turn(TR.T(), label, qtext=question)
        self.t.write(self.tpath)
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": self.t.prompt}
        hook.update(extra or {})
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def refused(self, cmd, question, *parts):
        deny, _ = self.decide(cmd, question)
        self.assertIsNotNone(deny, question)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        for p in parts:
            self.assertIn(p, deny.message())
        self.assertNotIn(" / ", deny.message())  # the full list is gone
        return deny.message()

    def test_two(self):
        st = F.state()
        lines = [EXPECTED, "발음 空港 → 쿠우코오"]
        st["langs"]["ko"]["shown"]["2"] = {"-": {"hash": "x", "at": "t", "lines": lines}}
        self.video(st)
        cmd = "python3 .claude/studio/scripts/state.py approve v 2 --expect %s" % H
        head = "[v] ② 오디션 — studio/out/v/ko/audition/narrator.wav · hash %s\n" % H
        msg = self.refused(cmd, head + RETYPED + "\n" + lines[1],
                           "lacks this line (1 of 1 missing), exactly as `shown` printed: %s." % EXPECTED,
                           "Closest line in the question: %s" % RETYPED, "copy the block `shown` printed")
        self.assertRegex(msg, r'differs at ".*안팔.*" — expected ".*안팎')
        self.refused(cmd, head, "(1 of 2 missing), exactly as `shown` printed: %s." % EXPECTED,
                     "No line in the question is close to it.")
        deny, ctx = self.decide(cmd, head + "\n".join(lines))
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)

    def test_four_b_union_without_platform(self):
        st = F.state(platforms={"youtube": ["youtube"], "shorts": ["youtube"]})
        st["langs"]["ko"]["shown"]["4b"] = {"youtube": {"hash": "x", "at": "t", "lines": [EXPECTED]},
                                            "shorts": {"hash": "y", "at": "t", "lines": ["근거: \"b\" ← \"c\""]}}
        self.video(st)
        cmd = "python3 .claude/studio/scripts/state.py approve v 4b --expect %s" % H
        head = "[v] ④b 배포용 글 — studio/copy/v/ko/youtube.md · hash %s\n" % H
        self.refused(cmd, head + RETYPED + "\n근거: \"b\" ← \"c\"", "(1 of 1 missing)", "Closest line")
        self.refused(cmd + " --platform youtube", head + EXPECTED, "(1 of 1 missing)", '근거: "b" ← "c"')
        deny, ctx = self.decide(cmd + " --platform youtube", head + EXPECTED + "\n근거: \"b\" ← \"c\"")
        self.assertIsNone(deny, deny and deny.message())
        st["langs"]["ko"]["excluded"]["platforms"] = ["shorts"]  # an excluded platform's lines are not needed
        self.video(st)
        deny, ctx = self.decide(cmd, head + EXPECTED)
        self.assertIsNone(deny, deny and deny.message())

    def test_fail_closed(self):
        st = F.state()
        st["brief"]["platforms"] = ["youtube"]  # malformed: not an object
        self.video(st)
        cmd = "python3 .claude/studio/scripts/state.py approve v 4b --expect %s --platform youtube" % H
        self.refused(cmd, "[v] ④b 배포용 글 · hash %s" % H, "cannot be read from the video's state.json")
        del st["brief"]
        self.video(st)
        self.refused(cmd, "[v] ④b 배포용 글 · hash %s" % H, "cannot be read from the video's state.json")

    def test_one(self):
        st = F.state()
        st["source"]["commits_since_begin"] = [{"sha": "a" * 40, "subject": "글 고침", "stat": "1 file"},
                                               {"sha": "b" * 40, "subject": "그림", "stat": "2 files"}]
        self.video(st)
        want = labels.source_commit_lines(st)
        cmd = "python3 .claude/studio/scripts/state.py approve v 1 --expect %s" % H
        head = "[v] ① 대본 — studio/videos/v/script.ko.md · hash %s\n" % H
        self.refused(cmd, head + want[0] + "\n" + want[1].replace("그림", "그림들"),
                     "(1 of 1 missing), exactly as `shown` (and record-source) printed: %s." % want[1])
        deny, _ = self.decide(cmd, head + "\n".join(want))
        self.assertIsNone(deny, deny and deny.message())

    def test_malformed_records_deny(self):
        """A record that is there but malformed denies (gate-lines-unknown) — never read as no lines."""
        cmd2 = "python3 .claude/studio/scripts/state.py approve v 2 --expect %s" % H
        q = "[v] ② 오디션 · hash %s" % H
        for bad in ({"-": {"hash": "x", "at": "t", "lines": EXPECTED}}, {"-": {"hash": "x", "lines": [EXPECTED, 3]}},
                    {"-": ["x"]}, ["x"]):
            st = F.state()
            st["langs"]["ko"]["shown"]["2"] = bad
            self.video(st)
            self.refused(cmd2, q, "cannot be read from the video's state.json")
        st = F.state()
        st["langs"]["ko"]["shown"] = []
        self.video(st)
        self.refused(cmd2, q, "cannot be read from the video's state.json")
        cmd1 = "python3 .claude/studio/scripts/state.py approve v 1 --expect %s" % H
        for bad in ("a1b2", [{"sha": 3, "subject": "x"}], ["x"]):
            st = F.state()
            st["source"]["commits_since_begin"] = bad
            self.video(st)
            self.refused(cmd1, "[v] ① 대본 · hash %s" % H, "cannot be read from the video's state.json")
        # nothing shown yet is no lines (state.py refuses the approval itself)
        st = F.state()
        self.assertEqual((labels.gate2_lines(st), labels.source_commit_lines(st)), ([], []))
        self.assertEqual(labels.gate2_lines({"video": "v"}), [])

    def test_proxy_unchanged(self):
        st = F.state()
        st["langs"]["ko"]["shown"]["2"] = {"-": {"hash": "x", "at": "t", "lines": [EXPECTED]}}
        self.video(st)
        with open(os.path.join(self.env["STUDIO_HOME"], "studio-sandbox.json"), "w") as f:
            json.dump({"sandbox_root": self.tmp}, f)
        self.env["STUDIO_SANDBOX"] = "1"
        deny, ctx = self.decide("python3 .claude/studio/scripts/state.py approve v 2 --expect %s --proxy" % H, "x")
        self.assertIsNone(deny, deny and deny.message())
        self.assertIn("proxy", ctx.allow)


class SetupLineMessage(JudgeCase):
    def test_config_line(self):
        from stdo.setup import labels as sl
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        cfg = json.load(open(os.path.join(self.repo, ".claude", "studio", "config.json")))
        old, new = cfg["public_domains"], ["example.com"]
        h = sl.setting_hash("public_domains", old, new)
        line = sl.config_line("public_domains", old, new)
        tpath = TR.transcript_path(self.env)
        t = TR.approval_turn(TR.T(), "설정 %s" % h, qtext="설정을 바꿀까요? %s\n%s" % (h, line.replace("example", "exanple")))
        t.write(tpath)
        cmd = "python3 %s config set public_domains '[\"example.com\"]' --expect %s" % (
            os.path.join(helpers.SCRIPTS, "setup.py"), h)
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                "transcript_path": tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": t.prompt}
        deny, _ = judge.decide(hook, self.env, snapshot_loader=self.loader)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("lacks this line (1 of 1 missing), exactly as the preview printed: %s." % line, deny.message())
        self.assertIn("Closest line in the question:", deny.message())


class CreditMessage(BoardCase):
    def test_names_the_credit_line(self):
        self.credit_draft()
        code, lines, h = self.preview()
        self.assertEqual(code, 0)
        cl = [l for l in lines if l.startswith("credit_line=")][0]
        q = "[v1] 출처 — %s · hash %s\n%s" % (IMG, h, "\n".join(lines).replace(cl, cl.replace("author", "autor")))
        self.assertEqual(self.credit(lines, h, question=q), 6)
        self.assertIn("fields-not-shown: The question lacks this line (1 of 1 missing), exactly as credit-preview "
                      "printed: %s." % cl, self.err)
        self.assertIn("Closest line in the question: %s" % cl.replace("author", "autor"), self.err)

    def test_preview_block(self):
        self.credit_draft()
        code, lines, h = self.preview()
        block = question_block(self.out)
        self.assertEqual(block, "[v1] 출처 — %s · hash %s\n%s" % (IMG, h, "\n".join(lines)))
        self.assertIn("question (paste unchanged as the AskUserQuestion question):\n", self.out)
        self.assertEqual(self.credit(lines, h, question=block), 0, self.err)


class CommitValuesMessage(InitCase):
    """As test_m1c.GuardValues (not imported: its tests would run twice)."""

    def setUp(self):
        super().setUp()
        from e2e_runner import Session
        self.init()
        self.commit_all()
        self.s = Session(self.repo, dict(os.environ), dict(os.environ), M1C_SID)

    def staged(self, cfg_change):
        from test_e2e_m0 import values_of
        cfg = self.cfg()
        cfg_change(cfg)
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        r = self.s.bash("python3 .claude/studio/scripts/check_commit.py --stage harness")
        self.assertEqual(r.code, 0, r)
        line = re.search(r"put this line in the question as it is:\n(.+)\n", r.out).group(1)
        return line, line.split(" | ")[0], values_of(r.out)

    def commit_with(self, text, label):
        self.s.ask(text, [label, "고칠 곳이 있다"], label)
        return self.s.bash('git commit -m "studio: settings"')

    def test_names_the_value_line(self):
        line, label, vals = self.staged(lambda c: c.__setitem__("public_domains", ["a.example.com"]))
        r = self.commit_with(line + "\n" + vals[0].replace("a.example", "b.example"), label)
        self.assertEqual(r.decision, "deny")
        self.assertIn("lacks this line (1 of 1 missing), exactly as check_commit.py --stage printed: %s." % vals[0],
                      r.reason)
        self.assertIn("Closest line in the question: %s" % vals[0].replace("a.example", "b.example"), r.reason)


# ---------------------------------------------------------------- P4: the question block

class ShownBlock(VoiceCase):
    def test_two(self):
        self.to_audition()
        with open(tts.exemptions_path(self.vdir, "ko"), "w") as f:
            json.dump({"schema": 1, "lines": [{"id": S1_ID, "text": "x", "heard": "y", "cer": 0.4}]}, f)
        h = self.show("2")
        block = question_block(self.out)
        want = labels.gate2_lines(store.read_state(self.vdir))
        self.assertEqual(block, "[v1] ② 오디션 — studio/out/v1/ko/audition/narrator.wav · hash %s\n%s"
                         % (h, "\n".join(want)))
        self.assertIn("question (paste unchanged as the AskUserQuestion question; add the length warning when there "
                      "is one after it):", self.out)
        # too many lines: the file line is inside the block
        many = [{"id": "s%d" % n, "text": "문장 %d" % n, "heard": "문장", "cer": 0.5} for n in range(50)]
        with open(tts.exemptions_path(self.vdir, "ko"), "w") as f:
            json.dump({"schema": 1, "lines": many}, f, ensure_ascii=False)
        self.show("2")
        self.assertRegex(question_block(self.out).splitlines()[1], r"^② 목록 파일: work/ko/gate2-lines.txt ")

    def test_one(self):
        st = store.read_state(self.vdir)
        self.assertEqual(self.state("shown", "v1", "1"), 0, self.err)
        h = re.search(r"^hash12 ([0-9a-f]{12})$", self.out, re.M).group(1)
        self.assertEqual(question_block(self.out).splitlines(),
                         ["[v1] ① 대본 — studio/videos/v1/script.ko.md · hash %s" % h] + labels.source_commit_lines(st))
        self.assertIn("add the auditor's findings after it", self.out)


class ShownBlockFourB(CopyCase):
    def test_four_b_and_platform(self):
        self.to_four_a()
        self.ready()
        self.assertEqual(self.validate(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "copy", "--platform", "youtube"), 0, self.err)
        self.assertEqual(self.state("shown", "v1", "4b", "--platform", "youtube"), 0, self.err)
        h = re.search(r"^hash12 ([0-9a-f]{12})$", self.out, re.M).group(1)
        from test_m1e import E2
        self.assertEqual(question_block(self.out), "[v1] ④b 배포용 글 — studio/copy/v1/ko/youtube.md · hash %s\n"
                         "근거: \"%s\" ← \"%s\"" % (h, FACT, E2))
        argv = ["approve", "v1", "4b", "--expect", h, "--platform", "nowhere"]
        self.pend(argv, "승인 v1 %s" % h)
        self.assertEqual(self.state(*argv), 2)
        self.assertIn("nowhere is not in the brief", self.err)


# ---------------------------------------------------------------- P8: the ignore block and /std update

OLD_BLOCK = """# >>> studio (managed by /std init; edit with /std config) >>>
/studio/local/
/.claude/studio/local/
/studio/out/
/studio/copy/
/studio/videos/*/work/
/studio/videos/*/audio/**
!/studio/videos/*/audio/*/
!/studio/videos/*/audio/*/picks.json
/studio/cast/*/work/
/studio/voices/**/candidates/
%s# <<< studio <<<
"""


class IgnoreUpdate(InitCase):
    def setUp(self):
        super().setUp()
        self.init()
        with open(os.path.join(self.repo, "lefthook.yml"), "w") as f:
            f.write("pre-commit: {}\n")
        self.commit_all()
        os.environ["CLAUDE_CODE_SESSION_ID"] = M1C_SID  # the session InitCase.pend writes

    def plan(self):
        self.assertEqual(self.setup("update", "plan"), 0, self.last_err)
        return self.out_json()

    def exclude_path(self):
        out = subprocess.run(["git", "-C", self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, check=True)
        return os.path.join(out.stdout.strip(), "info", "exclude")

    def status_text(self):
        from stdo.state import cli as scli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            scli.main(["status"], cwd=self.repo)
        return out.getvalue() + err.getvalue()

    def test_old_block_refreshed(self):
        fresh = self.plan()
        gi = os.path.join(self.repo, ".gitignore")
        text = open(gi).read()
        rest, _blk = ignore.split(text)
        mine = "/studio/notes/\n"
        with open(gi, "w") as f:
            f.write(ignore.ensure(rest, OLD_BLOCK % (mine + "/studio/videos/*/audio/**\n")))
        ex = self.exclude_path()
        with open(ex) as f:
            ex_rest, _b = ignore.split(f.read())
        with open(ex, "w") as f:
            f.write(ignore.ensure(ex_rest, OLD_BLOCK % "/lefthook-local.yml\n/by-hand/\n"))
        r = self.script("check_commit.py", "--stage", "harness")  # H13: the old block fails with new scripts
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("re-includes paths", r.stdout + r.stderr)
        helpers.git(self.repo, "reset", "-q")
        self.as_0022()
        self.commit_all("a 0.0.22 repository")
        st = self.status_text()
        self.assertIn("the Studio block in .gitignore is older than this version — /std update", st)
        self.assertIn("the Studio block in info/exclude is older than this version — /std update", st)

        p = self.plan()
        ig = p["ignore"]
        self.assertEqual((ig["gitignore"], ig["exclude"], ig["kept"]), (True, True, ["/studio/notes/"]))
        self.assertEqual(sorted(ig["removed"]), sorted(["/studio/videos/*/audio/**", "/studio/videos/*/audio/**",
                                                        "!/studio/videos/*/audio/*/",
                                                        "!/studio/videos/*/audio/*/picks.json"]))
        self.assertIn(".gitignore Studio 블록: 0.0.22 → %s" % render.plugin_version(), ig["lines"])
        self.assertIn("stdo/__init__.py", p["scripts"]["replace"])  # the scripts are copied in the same apply
        self.assertTrue([l for l in ig["lines"] if l.startswith("info/exclude Studio 블록: ")], ig)
        self.assertNotEqual(p["h12"], fresh["h12"])
        argv = ["update", "apply", "--expect", p["h12"]]
        self.pend(argv, p["label"])
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        self.assertIn(".gitignore", self.out_json()["wrote"])
        self.assertEqual(update.repo_scripts_version(self.repo), int(SCRIPTS_VERSION))
        self.assertEqual(json.load(open(os.path.join(self.repo, render.INSTALLED)))["plugin_version"],
                         render.plugin_version())
        self.assertEqual(ignore.split(open(gi).read()), (rest, ignore.render("studio", ["/studio/notes/"])))
        self.assertEqual(ignore.split(open(ex).read())[1], ignore.render("studio", ["/lefthook-local.yml"]))
        self.assertEqual(self.plan()["ignore"]["gitignore"], False)

        r = self.script("check_commit.py", "--stage", "harness")  # H13 passes; the change is block-only
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        helpers.git(self.repo, "reset", "-q")
        self.commit_all("studio: update")
        vdir = os.path.join(self.repo, "studio", "videos", "v1")
        os.makedirs(os.path.join(vdir, "audio", "ko"))
        for rel, body in (("CREDITS.draft.yaml", "{}\n"), ("audio/ko/picks.json", "{}\n"),
                          ("audio/ko/manifest.json", "{}\n")):
            with open(os.path.join(vdir, rel), "w") as f:
                f.write(body)
        self.assertEqual(helpers.git(self.repo, "status", "--porcelain", "--untracked-files=all").stdout, "")
        self.assertNotIn("older than this version", self.status_text())

    def as_0022(self):
        """installed.json and the scripts' copy as 0.0.22 left them (SCRIPTS_VERSION 21)."""
        p = os.path.join(self.repo, render.INSTALLED)
        inst = json.load(open(p))
        inst.update(plugin_version="0.0.22", scripts_version="21")
        with open(p, "w") as f:
            f.write(render.dump_json(inst))
        f = os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "__init__.py")
        body = open(f).read()
        with open(f, "w") as fh:
            fh.write(re.sub(r'SCRIPTS_VERSION = "\d+"', 'SCRIPTS_VERSION = "21"', body))

    def test_broken_markers_refused(self):
        gi = os.path.join(self.repo, ".gitignore")
        text = open(gi).read()
        with open(gi, "w") as f:
            f.write(text + ignore.BEGIN + "\n")  # a second begin marker
        self.commit_all("broken markers")
        p = self.plan()
        self.assertTrue(p["ignore"]["problems"] and p["ignore"]["problems"][0].startswith(".gitignore: "), p["ignore"])
        argv = ["update", "apply", "--expect", p["h12"]]
        self.pend(argv, p["label"])
        self.assertEqual(self.setup(*argv), 3)
        self.assertIn("the Studio ignore blocks cannot be updated: .gitignore: the Studio block markers are unpaired "
                      "or repeated — fix the markers by hand, then plan again", self.last_err)
        self.assertEqual(open(gi).read(), text + ignore.BEGIN + "\n")

    def test_outdated_and_carry(self):
        new = ignore.render("studio")
        self.assertFalse(ignore.outdated(new, "studio"))
        self.assertTrue(ignore.outdated(OLD_BLOCK % "", "studio"))
        self.assertFalse(ignore.outdated(ignore.render("studio", ["/mine/"]), "studio"))  # a person's line
        self.assertTrue(ignore.outdated(new.replace("/studio/videos/*/CREDITS.draft.yaml\n", ""), "studio"))
        self.assertEqual(ignore.carry(OLD_BLOCK % "/mine/\n!/re-included/\n", "studio"),
                         (["/mine/"], ["/studio/videos/*/audio/**", "!/studio/videos/*/audio/*/",
                                       "!/studio/videos/*/audio/*/picks.json", "!/re-included/"]))
