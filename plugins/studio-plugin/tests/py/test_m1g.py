"""M1g (m1-plan §9): the board check (`check_assets.py --output`), `state.py credit-preview` · `credit` and
CREDITS.yaml, visual-check and gate ③ — plus the M1f re-review items W1 (a retry counts when s2v's `tried` grows) and
W2 (number values: digits with units, dates, English ordinals)."""

import contextlib
import io
import json
import os

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo import board, credits, s2vrun
from stdo.source import assets as assets_mod
from stdo.state import router, stagechecks, store
from stdo.state.hashes import file_sha
from stdo.voice import cli as vcli, numbers, tts
from test_guard_judge import JudgeCase
from test_m1f import S1_ID, VoiceCase, stamp

IMG = "../../../docs/img/gate.png"


class BoardCase(VoiceCase):
    """A video at ② approved."""

    def setUp(self):
        super().setUp()
        self.to_audition()
        self.approve("2")

    def credit_draft(self, **over):
        item = {"path": IMG, "license": "own work", "credit_line": "the author", "floor": "public/-",
                "license_checked": True, "public_ok": True, "redistribute": True, "commercial": True}
        item.update(over)
        for k in [k for k, v in over.items() if v is None]:
            del item[k]
        with open(os.path.join(self.vdir, credits.DRAFT), "w") as f:
            json.dump({"schema": 1, "items": [item]}, f, ensure_ascii=False)
        return item

    def preview(self):
        code = self.state("credit-preview", "v1", IMG)
        lines = [l for l in self.out.splitlines() if "=" in l and not l.startswith(("label", "이전"))]
        h = [l.split()[-1] for l in self.out.splitlines() if l.startswith("label 출처 ")]
        return code, lines, (h[0] if h else None)

    def credit(self, lines=None, h=None, question=None):
        if h is None:
            _c, lines, h = self.preview()
        argv = ["credit", "v1", IMG, "--expect", h]
        self.tool += 1
        q = question if question is not None else "[v1] 출처 — %s · hash %s\n%s" % (IMG, h, "\n".join(lines))
        from stdo.state import evidence
        from stdo.state.argv import argv_sha
        ev = {"schema": 1, "argv_sha": argv_sha(argv), "session_id": "sess-m1f", "tool_use_id": "toolu_c%d" % self.tool,
              "question_index": 0, "question": q, "answer": "출처 v1 %s" % h, "mode": "human",
              "written_at": stamp()}
        os.makedirs(evidence.local_dir(self.repo), exist_ok=True)
        with open(evidence.pending_path(self.repo), "w") as f:
            json.dump(ev, f, ensure_ascii=False)
        return self.state(*argv)

    def check_board(self):
        return self.run_v(vcli.assets_main, "v1", "--output", "youtube", providers=self.providers)

    def themed(self):
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace("lang: ko\n", "lang: ko\ntheme: dark\n", 1))  # presentation only

    def to_board(self):
        self.themed()
        self.credit_draft()
        self.assertEqual(self.credit(), 0, self.err)
        self.assertEqual(self.check_board(), 0, self.out + self.err)
        self.assertEqual(self.state("stage-done", "v1", "board", "--output", "youtube"), 0, self.err)


class Credit(BoardCase):
    def test_board_visual_check_and_three(self):
        self.to_board()
        with open(os.path.join(self.vdir, credits.FILE)) as f:
            data = json.load(f)
        e = data["items"][0]
        self.assertEqual((e["path"], e["sha256"]), (IMG, file_sha(os.path.join(self.repo, "docs", "img", "gate.png"))))
        self.assertEqual(store.read_state(self.vdir)["credits"][IMG]["hash"], credits.entry_hash(e))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = s2vrun.main(["snapshot", "v1", "--output", "youtube"], providers=self.providers, cwd=self.repo)
        self.assertEqual(code, 0, err.getvalue())
        h = [l.split()[1] for l in out.getvalue().splitlines() if l.startswith("hash12 ")][0]
        self.assertEqual(self.state("stage-done", "v1", "visual-check", "--output", "youtube"), 0, self.err)
        argv = ["approve", "v1", "3", "--expect", h, "--output", "youtube"]
        self.pend(argv, "승인 v1 %s" % h)
        self.assertEqual(self.state(*argv), 0, self.err)

    def test_fields_not_shown(self):
        self.credit_draft()
        code, lines, h = self.preview()
        self.assertEqual((code, len(lines)), (0, 8))
        self.assertEqual(lines[0], 'path="%s"' % IMG)
        self.assertIn("public_ok=true", lines)
        for n in range(8):  # each line missing
            q = "[v1] 출처 — %s · hash %s\n%s" % (IMG, h, "\n".join(lines[:n] + lines[n + 1:]))
            self.assertEqual(self.credit(lines, h, question=q), 6, lines[n])
            self.assertIn("fields-not-shown", self.err)
            self.assertIn(lines[n].split("=")[0], self.err)
        wrong = [l.replace('"the author"', '"someone else"') for l in lines]  # a value that differs
        self.assertEqual(self.credit(lines, h, question="[v1] 출처 · hash %s\n%s" % (h, "\n".join(wrong))), 6)
        self.assertNotIn(IMG, store.read_state(self.vdir).get("credits") or {})
        self.credit_draft(floor="public/the author's own")  # not the image's real floor
        code, _l, _h = self.preview()
        self.assertEqual(code, 1)
        self.assertIn("floor must be the image's floor public/-", self.err)
        self.credit_draft(credit_line="x" * 220)
        self.assertEqual(self.preview()[0], 1)
        self.assertIn("longer than 200 characters", self.err)
        self.credit_draft(public_ok=None)
        self.assertEqual(self.preview()[0], 1)
        self.assertIn("needs public_ok (true or false)", self.err)

    def test_changed_entry_needs_the_person_again(self):
        self.to_board()
        _c, _l, h_old = self.preview()
        self.credit_draft(credit_line="photo by the author")
        _c, lines, h_new = self.preview()
        self.assertNotEqual(h_old, h_new)
        self.assertEqual(self.credit(lines, h_old), 1)  # --expect of the old entry
        self.assertIn("is not the one shown", self.err)
        with open(os.path.join(self.vdir, credits.FILE)) as f:  # stands in for a direct edit of CREDITS.yaml
            data = json.load(f)
        data["items"][0]["credit_line"] = "photo by the author"
        with open(os.path.join(self.vdir, credits.FILE), "w") as f:
            json.dump(data, f)
        self.assertEqual(self.check_board(), 1)
        self.assertIn("not the one the person approved", self.out)
        self.assertEqual(self.credit(lines, h_new), 0, self.err)
        self.assertEqual(self.check_board(), 0, self.out)

    def test_replaced_file_refused(self):
        self.to_board()
        with open(os.path.join(self.repo, "docs", "img", "gate.png"), "ab") as f:
            f.write(b"\0")
        self.assertEqual(self.check_board(), 1)
        self.assertIn("changed since resolve_assets", self.out)
        self.assertIn("not the one its CREDITS entry was approved for", self.out)

    def test_own_image_needs_an_entry(self):
        self.themed()
        self.assertEqual(self.check_board(), 1)
        self.assertIn("has no CREDITS entry (every picture of a public video needs one, your own too)", self.out)

    def test_consent_not_supported(self):
        self.themed()
        item = self.credit_draft()
        item["consent"] = "yes"
        with open(os.path.join(self.vdir, credits.DRAFT), "w") as f:
            json.dump({"schema": 1, "items": [item]}, f)
        _c, lines, h = self.preview()
        self.assertIn("warning: consent is not supported in M1", self.out)
        self.assertEqual(self.credit(lines, h), 0, self.err)
        self.assertEqual(self.check_board(), 1)
        self.assertIn("consent is not supported in M1", self.out)

    def test_block_yaml_refused(self):
        with open(os.path.join(self.vdir, credits.DRAFT), "w") as f:
            f.write("items:\n  - path: %s\n    license: own\n" % IMG)
        self.assertEqual(self.preview()[0], 1)
        self.assertIn("not the JSON form Studio reads", self.err)
        self.to_board()
        with open(os.path.join(self.vdir, credits.FILE), "w") as f:
            f.write("items:\n  - path: x\n")
        self.assertEqual(self.check_board(), 1)
        self.assertIn("CREDITS.yaml is not the JSON form", self.out)

    def test_j73_only_usable_images(self):
        self.to_board()
        with open(os.path.join(self.repo, "docs", "img", "other.png"), "wb") as f:
            with open(os.path.join(self.repo, "docs", "img", "gate.png"), "rb") as g:
                f.write(g.read())
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace("![gate](%s)" % IMG, "![gate](%s)\n\n![other](../../../docs/img/other.png)" % IMG))
        self.assertEqual(self.check_board(), 1)
        self.assertIn("../../../docs/img/other.png is not a usable image of work/assets.json", self.out)

    def test_scope_needs_public_ok_and_license(self):
        self.to_board()
        st = store.read_state(self.vdir)
        data = assets_mod.read(self.vdir)
        for i in data["images"]:
            i["scope"] = "third-party"
        with open(assets_mod.path(self.vdir), "w") as f:
            json.dump(data, f)
        e = json.load(open(os.path.join(self.vdir, credits.FILE)))["items"][0]
        ins = {"files": [{"path": IMG, "kind": "image"}]}

        def problems(**over):
            item = dict(e, **over)
            with open(os.path.join(self.vdir, credits.FILE), "w") as f:
                f.write(credits.dumps({IMG: item}))
            st["credits"][IMG]["hash"] = credits.entry_hash(item)
            return board.picture_problems(self.repo, self.vdir, st, ins)
        self.assertEqual(problems(), [])
        self.assertIn("a public video needs public_ok: true", " ".join(problems(public_ok=False)))
        self.assertIn("needs license_checked: true", " ".join(problems(license="TODO", license_checked=False)))
        self.assertEqual(problems(license="see README", license_checked=True), [])

    def test_x1_frontmatter_logo_is_a_picture(self):
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        text = text.replace("![gate](%s)\n" % IMG, "")  # the image only as the logo
        text = text.replace("lang: ko\n", "lang: ko\ntheme: dark\nlogo: { src: \"%s\" }\n" % IMG, 1)
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text)
        self.assertEqual(self.check_board(), 1)
        self.assertIn("%s has no CREDITS entry" % IMG, self.out)
        self.credit_draft()
        self.assertEqual(self.credit(), 0, self.err)
        self.assertEqual(self.check_board(), 0, self.out)

    def test_x1_unknown_kinds_fail_closed_and_fonts_are_listed(self):
        self.assertTrue(board.is_picture("sticker"))
        self.assertTrue(board.is_picture(""))
        self.assertTrue(board.is_picture("font,logo"))
        self.assertFalse(board.is_picture("font"))
        st = store.read_state(self.vdir)
        got = board.picture_problems(self.repo, self.vdir, st, {"files": [{"path": "x/sticker.png", "kind": "sticker"},
                                                                          {"path": "f.ttf", "kind": "font"}]})
        self.assertEqual(got, ["x/sticker.png is not a usable image of work/assets.json (use its script_src)"])
        self.to_board()
        with open(os.path.join(self.vdir, "f.ttf"), "wb") as f:
            f.write(b"font")
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace("theme: dark\n", "theme: dark\nsubtitleStyle: { font: \"f.ttf\" }\n", 1))
        self.assertEqual(self.check_board(), 0, self.out)  # a font needs no CREDITS entry
        r = stagechecks.read(self.vdir, "ko", "board", "youtube")
        self.assertEqual(r["details"]["not_pictures"], [{"path": "f.ttf", "kind": "font"}])

    def test_x2_proxy_credit_needs_the_person(self):
        self.to_board()
        st = store.read_state(self.vdir)
        st["credits"][IMG]["approved_by"] = "proxy"
        with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
            json.dump(st, f)
        self.assertEqual(self.check_board(), 1)
        self.assertIn("approved in the proxy mode — the person runs `state.py credit` for it again", self.out)
        ins = {"files": [{"path": IMG, "kind": "image"}]}
        self.assertEqual(board.picture_problems(self.repo, self.vdir, st, ins, proxy=True), [])

    def test_s2v_check_overflow_fails(self):
        self.to_board()
        self.scenario({"check": {"overflow": True}})
        self.assertEqual(self.check_board(), 1)
        self.assertIn("s2v check: subtitle-overflow", self.out)

    def test_content_must_stay(self):
        self.to_board()
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace("체크인 카운터", "체크인 창구"))
        self.assertEqual(self.check_board(), 1)
        self.assertIn("content changed since ②", self.out)


class RouterBoard(StudioTestCase):
    def test_image_replaced_goes_to_board_and_keeps_two(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="3")
        rec2 = json.dumps(s["langs"]["ko"]["approved"]["2"], sort_keys=True)
        d = router.decide(s, "ko", F.changed(c, presentation={"youtube": "p-other"}))
        self.assertEqual(d.redo["stage"], "board")
        self.assertEqual(json.dumps(s["langs"]["ko"]["approved"]["2"], sort_keys=True), rec2)


class GuardCredit(JudgeCase):
    def test_credit_needs_evidence_and_credits_are_protected(self):
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump({"video": "v", "source_lang": "ko"}, f)
        self.assertDeny("python3 .claude/studio/scripts/state.py credit v ../a.png --expect 3f2a9c0d1e4b", "G-EVIDENCE")
        self.assertPass("python3 .claude/studio/scripts/state.py credit-preview v ../a.png")
        d = self.decide("Write", {"file_path": os.path.join(self.repo, "studio/videos/v/CREDITS.yaml"), "content": "{}"})
        self.assertEqual(d.rule, "G-PROT")
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(self.repo, "studio/videos/v/CREDITS.draft.yaml"),
                                                "content": "{}"}))
        self.assertPass("python3 .claude/studio/scripts/check_assets.py v --output youtube")


# ---------------------------------------------------------------- carried: W1 · W2

class RetryTried(VoiceCase):
    def test_w1_a_retry_counts_when_s2v_tried_more(self):
        """s2v may keep the old take after a retry: `tried` still grows, so the retry counts."""
        self.to_cast()
        sc = {"sentences": {S1_ID: {"cer": [0.4], "keep": True}}}
        self.assertEqual(self.synth(scenario=sc), 0)
        self.assertEqual(self.check_tts(), 1)
        self.assertIn("(0 of 2 retries done)", self.out)
        self.assertEqual(self.check_tts(), 1)  # no retry ran: nothing counted
        self.assertIn("(0 of 2 retries done)", self.out)
        self.assertEqual(self.synth("--retry", S1_ID), 0)  # the same take is kept, tried grows
        self.assertEqual(self.check_tts(), 1)
        self.assertIn("(1 of 2 retries done)", self.out)
        self.assertEqual(self.synth("--retry", S1_ID), 0)
        self.assertEqual(self.check_tts(), 0, self.out)
        with open(tts.exemptions_path(self.vdir, "ko")) as f:
            self.assertEqual([e["id"] for e in json.load(f)["lines"]], [S1_ID])

    def test_nit_s2v_writes_tried(self):
        """s2v 0.12.1 writes `tried` for every synthesized line (tts.ts commit(…, { tried })); the fake does too."""
        self.to_cast()
        self.assertEqual(self.synth(), 0)
        with open(os.path.join(self.vdir, "audio", "ko", "manifest.json")) as f:
            entries = json.load(f)["entries"]
        self.assertTrue(entries and all(e.get("tried") == 1 for e in entries.values()))

    def test_made(self):
        self.assertEqual(tts.made({"entries": {"k": {"tried": 7, "attempt": 2}}}, "k", {"attempt": 2}), 7)
        self.assertEqual(tts.made({"entries": {"k": {"attempt": 2}}}, "k", {"attempt": 2}), 2)
        self.assertEqual(tts.made(None, "k", None), 0)


class NumbersW2(StudioTestCase):
    def test_w2_values(self):
        same = [("일만 원", "1만 원"), ("3만 5천 원", "삼만 오천 원"), ("삼월에", "3월에"), ("first", "1st"),
                ("이천이십육 년", "2026년"), ("십이월", "12월"),
                # X3: separators, decimals, ranges said as a word
                ("1,000원", "1000원"), ("3.5배", "삼 점 오 배"), ("한두 개", "1~2개"), ("서너 명", "3~4명"),
                ("두세 번", "2~3번")]
        for a, b in same:
            self.assertEqual(numbers.values(a), numbers.values(b), (a, b))
            self.assertIsNone(tts.mismatch(a, b, "ko"), (a, b))
        self.assertEqual(numbers.values("3만 5천 원"), [35000])
        self.assertEqual(numbers.values("1만5천"), [15000])
        self.assertEqual(numbers.values("2nd and third"), [2, 3])
        for word in ("일본", "이번", "구분", "삼성", "만나다", "천천히", "백화점", "오시는 분", "사이좋게", "일주일",
                     "오일을 넣고", "오일에", "오시에"):  # X3: 오일 · 오시 alone are words
            self.assertEqual(numbers.values(word), [], word)
        self.assertEqual(tts.mismatch("삼월에 갑니다", "4월에 갑니다", "ko"), "numbers 3 heard as 4")
        self.assertEqual(numbers.values("1,000원과 2,500,000원"), [1000, 2500000])
        self.assertEqual(numbers.values("영 점 오 초"), [0.5])
        self.assertEqual(tts.mismatch("3.5배", "3배", "ko"), "numbers 3.5 heard as 3")
