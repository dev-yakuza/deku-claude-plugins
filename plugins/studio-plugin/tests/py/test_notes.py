"""0.1.2 (fix-0102 §1, pilot-2 N8): teaching notes — general knowledge a learner needs and the source does not say,
marked `<!-- studio:note -->` above a narration paragraph or a text card. The marker (claims/notes.py: placement,
matching against s2v's sentences and screen_text, the same-text rule, the caps), the script check, the verify skeleton
and check (kind `note`, a basis, terms), verify.json / verify.md (0.1.1's bytes without notes), gate ① (the note
lines in shown, the question, the guard and `state.py approve` itself), the ① tuple (`notes`), the copy check, and the
fake s2v's comment rule and screen_text shape against real s2v (when STUDIO_TEST_S2V is set)."""

import contextlib
import io
import json
import os
import subprocess
import unittest

import helpers
import state_fixtures as F
import verifyref
from helpers import StudioTestCase
from stdo.claims import check as ccheck, cli as ccli, linkrule, notes
from stdo.distribute import factcheck
from stdo.state import cli, evidence, router, store
from stdo.state.argv import argv_sha
from stdo.text.normalize import Text, normalize
from approve_base import stamp
from test_guard_judge import JudgeCase
from test_m1b import need_node
from test_m1e import E1, E2, FAKE_ROOT, S1, S2, SCRIPT, TITLE1, FlowCase, cid, rendered

FAKE_MAIN = os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js")
HEAD = """---
title: 노트
lang: %s
cast:
  narrator: { voice: "qwen:Sohee", style: "차분하게" }
outputs:
  youtube: { aspect: "16:9", maxDuration: 600 }
---
"""
LONG = " ".join("이 영상은 여행 단어를 차례로 살펴봅니다." for _ in range(20))
INTRO = "\n# 시작 {#intro}\n\n%s\n\n::title[노트]\n" % LONG
NOTE = "조사로 쓰일 때 이 글자는 와로 읽습니다."
M = "<!-- studio:note -->"


# review of 0.1.2 (MAJOR): an underlined heading and a `# ` hidden in a multi-line comment cancel out in a count of
# scenes; the scenes are matched by their titles, so the unmarked card never becomes the note
HIDDEN = HEAD % "ko" + INTRO + ("\n하나\n====\n\n본문입니다.\n\n:::bullets\n- 원문이 말한 사실 하나\n:::\n\n# 둘 {#two}\n\n"
                               "%s\n:::bullets\n- 조사로 쓰일 때 와로 읽음\n:::\n\n<!--\n# 숨은 제목\n-->\n" % M)
LEAD_HIDDEN = HEAD % "ko" + "\n머리말입니다.\n\n::thumbnail{src=\"t.png\"}\n" + INTRO + \
    "\n# 둘 {#two}\n\n둘째입니다.\n\n%s\n:::bullets\n- 조사로 쓰일 때 와로 읽음\n:::\n\n<!--\n# 숨은 제목\n-->\n" % M
LEAD_NOTE = HEAD % "ko" + "\n머리말입니다.\n\n::thumbnail{src=\"t.png\"}\n" + \
    INTRO.replace("\n::title[노트]\n", "\n%s\n%s\n\n::title[노트]\n" % (M, NOTE))


# re-review of 0.1.2: cards s2v reads and a simpler walk would not (each with an empty card that evens the counts);
# the fact card must never become the note
FACT = "원문이 말한 사실"
MARKED_CARD = "%s\n:::bullets\n- 조사로 쓰일 때 와로 읽음\n:::\n\n:::bullets\n:::\n" % M
WALK = {
    "indented": " :::bullets\n - %s\n :::\n\n" % FACT + MARKED_CARD,
    "four colons": "::::bullets\n- %s\n::::\n\n" % FACT + MARKED_CARD,
    "inline html": "<span>가</span> 원문 문장입니다.\n:::bullets\n- %s\n:::\n\n" % FACT + MARKED_CARD,
    "backtick info": "```a`b 원문입니다.\n\n:::bullets\n- %s\n:::\n\n<!--\n```\n-->\n\n" % FACT + MARKED_CARD,
}
AFTER_HTML = "<span>가</span> 원문 문장입니다.\n%s\n:::bullets\n- 조사로 쓰일 때 와로 읽음\n:::\n" % M
HEADINGS = ("본문입니다.\n\n# 제목 ## {#x}\n\n가 문장입니다.\n\n#\t탭 제목 {#y} ##\n\n나 문장입니다.\n\n  # 들여쓴 \\# 제목\n\n"
            "다 문장입니다.\n\n# *강조* <b>굵게</b> 제목\n\n라 문장은 **굵게** <span>스팬</span> 입니다.\n")


def script(body, intro=INTRO, lang="ko"):
    return HEAD % lang + intro + "\n# 본문 {#body}\n\n본문 문장입니다.\n\n" + body + "\n"


class S2vCase(StudioTestCase):
    """notes.marked on what an s2v CLI gives for a script (the fake by default)."""
    main = FAKE_MAIN

    def setUp(self):
        need_node()
        super().setUp()

    def s2v(self, text):
        p = os.path.join(self.tmp, "script.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        run = (lambda args: helpers.run_s2v(self, args)) if self.main is None else \
            (lambda args: subprocess.run(["node", self.main] + args, capture_output=True, text=True, cwd=self.tmp))
        ins, sen = run(["inspect", p, "--json"]), run(["sentences", p, "--json"])
        self.assertEqual(ins.returncode, 0, ins.stderr)
        return json.loads(sen.stdout), json.loads(ins.stdout)

    def marked(self, body, **kw):
        text = script(body, **kw)
        sen, ins = self.s2v(text)
        return notes.marked(text, sen, ins)

    def problem(self, body, want, **kw):
        texts, problems = self.marked(body, **kw)
        self.assertTrue(any(want in p for p in problems), "%r not in %r" % (want, problems))
        return texts


class Marker(S2vCase):
    def test_paragraph_and_card(self):
        body = "%s\n%s\n\n%s\n:::table\n| 글자 | 읽기 |\n|---|---|\n| は | 와 |\n| | 빈칸 |\n:::" % (M, NOTE, M)
        texts, problems = self.marked(body)
        self.assertEqual(problems, [])
        # one note per table cell; an empty cell (text "") is no note and no occurrence
        self.assertEqual(texts, [NOTE, "글자", "읽기", "は", "와", "빈칸"])

    def test_a_narration_note_is_not_refused_by_its_paragraph_entries(self):
        text = script("%s\n%s" % (M, NOTE))
        sen, ins = self.s2v(text)
        self.assertIn(NOTE, [e["text"] for e in ins["screen_text"] if e.get("directive") == "paragraph"])
        self.assertEqual(notes.marked(text, sen, ins), ([NOTE], []))

    def test_under_a_heading(self):
        text = HEAD % "ko" + INTRO + "\n# 본문 {#body}\n%s\n%s\n" % (M, NOTE)
        sen, ins = self.s2v(text)
        self.assertEqual(notes.marked(text, sen, ins), ([NOTE], []))

    def test_placement(self):
        cases = [
            ("앞 문장입니다.\n%s\n%s" % (M, NOTE), notes.ABOVE),
            ("%s\n\n%s" % (M, NOTE), notes.BELOW),
            ("%s\n::title[본문]" % M, notes.BELOW),
            ("%s\n:::quote\n가나다\n:::" % M, notes.QUOTE),
            ("%s\n:::compare\n## 왼쪽\n- 가\n:::" % M, notes.BELOW),
            ("%s\n::image{src=\"a.png\"}" % M, notes.BELOW),
            ("%s" % M, notes.BELOW),  # EOF
            ("```\n%s\n```" % M, notes.INSIDE),
            (":::bullets\n- 가\n%s\n- 나\n:::" % M, notes.INSIDE),
            ("    %s\n%s" % (M, NOTE), notes.INDENT),  # 4 spaces: an indented code block, never a marker
        ]
        for body, want in cases:
            self.problem(body, want)
        self.problem("%s\n%s" % (M, NOTE), notes.FIRST, intro="\n# 시작 {#intro}\n\n%s\n\n%s\n%s\n\n::title[노트]\n"
                     % (LONG, M, NOTE))
        self.problem("%s\n# 다음 {#next}\n\n다음 문장입니다." % M, notes.BELOW)

    def test_plain_text_only(self):
        for line, want in (("narrator: " + NOTE, "no speaker prefix"), ("조사 :pause{s=1} 설명입니다.", "text directive"),
                           ("**조사** 설명입니다.", "keep a teaching note plain"),
                           ("`조사` 설명입니다.", "keep a teaching note plain"),
                           ("[조사](x) 설명입니다.", "keep a teaching note plain"),
                           ("<b>조사</b> 설명입니다.", "keep a teaching note plain")):
            self.problem("%s\n%s" % (M, line), want)

    def test_the_same_text_rule(self):
        # narration against a card, a card against a scene title
        self.problem("%s\n읽는 법을 봅시다.\n\n:::bullets\n- 읽는 법을 봅시다.\n:::" % M,
                     "is a teaching note in one place and not in another")
        self.problem("%s\n:::bullets\n- 본문\n:::" % M, "is a teaching note in one place and not in another")

    def test_the_kth_card(self):
        texts, problems = self.marked(":::bullets\n- 가나\n:::\n\n%s\n:::bullets\n- 다라\n:::" % M)
        self.assertEqual((texts, problems), (["다라"], []))
        both = ":::bullets\n- 가나\n:::\n\n%s\n:::bullets\n- 가나\n:::" % M  # identical: one marked, one not
        self.problem(both, "is a teaching note in one place and not in another")
        texts, problems = self.marked("%s\n:::bullets\n- 가나\n:::\n\n%s\n:::bullets\n- 가나\n:::" % (M, M))
        self.assertEqual((texts, problems), (["가나", "가나"], []))

    def test_empty_cards(self):
        # an empty card has no screen_text entry: positions would shift, so the counts must agree
        texts = self.problem(":::bullets\n:::\n\n%s\n:::bullets\n- 마\n:::\n\n:::bullets\n- 바\n:::" % M,
                             "scene 2 has 3 :::bullets card(s) but s2v shows 2")
        self.assertEqual(texts, [])  # no unmarked card's text became a note
        self.problem("%s\n:::bullets\n:::" % M, "but s2v shows 0")
        self.problem("%s\n:::table\n| | |\n|---|---|\n| | |\n:::" % M, "shows nothing on screen")

    def test_scenes_by_position(self):
        body = ":::bullets\n- 가\n:::\n\n# 셋째 {#third}\n\n셋째 문장입니다.\n\n%s\n:::bullets\n- 나\n:::" % M
        text = script(body)
        sen, ins = self.s2v(text)
        self.assertEqual([s["id"] for s in ins["scenes"]], ["intro", "body", "third"])
        self.assertEqual(notes.marked(text, sen, ins), (["나"], []))
        # an implicit scene (text before the first heading) or a setext heading: s2v counts another scene
        lead = HEAD % "ko" + "\n머리말입니다.\n\n::thumbnail{src=\"t.png\"}\n" + INTRO + \
            "\n# 본문 {#body}\n\n%s\n:::bullets\n- 나\n:::\n" % M
        sen, ins = self.s2v(lead)
        self.assertTrue(any("s2v sees 3 scene(s), the script has 2" in p for p in notes.marked(lead, sen, ins)[1]))

    def test_scenes_by_identity(self):
        for text in (HIDDEN, LEAD_HIDDEN):
            sen, ins = self.s2v(text)
            texts, problems = notes.marked(text, sen, ins)
            self.assertEqual(texts, [])
            self.assertTrue(any("the scenes do not match s2v's" in p for p in problems), problems)
        texts, problems = notes.marked(*((HIDDEN,) + self.s2v(HIDDEN)))
        self.assertIn("underlined heading", " ".join(problems))
        heads, setext = notes.scan(HIDDEN)[1], notes.scan(HIDDEN)[4]
        self.assertEqual((heads, setext), (["시작", "둘"], 1))  # the commented `# ` is no heading

    def check_walk(self, body):
        texts, problems = self.marked(body)
        self.assertNotIn(FACT, texts)
        self.assertTrue(problems)
        return problems

    def test_cards_the_walk_reads_as_s2v_does(self):
        for what, body in WALK.items():
            with self.subTest(what):
                self.assertIn("an empty card?", " ".join(self.check_walk(body)))
                # without the evening card: the card is found where s2v shows it
                texts, problems = self.marked(body.replace("\n\n:::bullets\n:::\n", "\n"))
                self.assertEqual((texts, problems), (["조사로 쓰일 때 와로 읽음"], []), what)
        self.problem(AFTER_HTML, notes.ABOVE)  # never dropped silently

    def test_the_root_guard(self):
        """Whatever the walk reads, the mapped block must show the marked card's own text; an empty card of the same
        name in that scene is refused (it would even out the counts)."""
        text = script("%s\n:::bullets\n- 가나\n:::" % M)
        sen, ins = self.s2v(text)
        for e in ins["screen_text"]:
            if e.get("directive") == "bullets":
                e["text"] = FACT
        texts, problems = notes.marked(text, sen, ins)
        self.assertEqual(texts, [])
        self.assertIn("is not the card s2v shows in its place", " ".join(problems))
        text = script("%s\n:::bullets\n- 가나\n:::\n\n:::bullets\n:::" % M)
        sen, ins = self.s2v(text)
        e = [x for x in ins["screen_text"] if x.get("directive") == "bullets"][0]
        ins["screen_text"].append(dict(e, block=e["block"] + 1, text="다라"))  # counts even, as a misread would
        texts, problems = notes.marked(text, sen, ins)
        self.assertEqual(texts, [])
        self.assertIn("an empty :::bullets card besides a marked one", " ".join(problems))
        # a table: pipes and the separator row are no text
        self.assertEqual(notes.card_text("table", ["| 가 | 나 |", "|---|---|", "| | 다 |"]), "가나다")

    def test_heading_titles_as_commonmark(self):
        for line, want in (("# 제목 ## {#two}", "제목 ##"), ("# 제목 {#two} ##", "제목"), ("#\t탭", "탭"),
                           ("  # 들여쓴 \\# 제목", "들여쓴 # 제목"), ("# *강조* <b>굵게</b>", "강조 굵게"), ("# 끝 #", "끝")):
            self.assertEqual(notes.heading_text(line), want, line)
        text = script(HEADINGS)
        sen, ins = self.s2v(text)
        self.assertEqual([normalize(x["title"]) for x in ins["scenes"]], ["시작", "본문"] + notes.scan(text)[1][2:])

    def test_scene_one_is_s2vs(self):
        """With a lead-in (an implicit scene), s2v's scene 1 is the lead-in: the first `# ` scene may hold a note."""
        sen, ins = self.s2v(LEAD_NOTE)
        self.assertEqual(notes.marked(LEAD_NOTE, sen, ins), ([NOTE], []))

    def test_a_fence_inside_a_card(self):
        """The walk follows check.top_directives: a fence inside a card hides its `:::`."""
        text = script(":::markdown\n```\n:::\n```\n:::\n\n%s\n:::bullets\n- 가\n:::" % M)
        blks, _h, cards, problems = notes.scan(text)[:4]
        self.assertEqual(problems, [])
        self.assertEqual((cards[(1, "markdown")], cards[(1, "bullets")]), (1, 1))
        self.assertEqual([(b["kind"], b["name"], b["k"]) for b in blks], [("card", "bullets", 0)])

    def test_no_marked_card_no_scene_rule(self):
        """review 4 m1: the scene-count rule runs only for a marked card — a script with ::thumbnail and a lead-in line
        (an implicit scene) and no marker gives no note problem (its script check is 0.1.1's: NoMarkerScript)."""
        lead = HEAD % "ko" + "\n머리말입니다.\n\n::thumbnail{src=\"t.png\"}\n" + INTRO + "\n# 본문 {#body}\n\n본문입니다.\n"
        sen, ins = self.s2v(lead)
        self.assertEqual(len(ins["scenes"]), 3)
        self.assertEqual(notes.marked(lead, sen, ins), ([], []))
        para = lead + "\n%s\n%s\n" % (M, NOTE)  # a marked paragraph needs no scene mapping
        sen, ins = self.s2v(para)
        self.assertEqual(notes.marked(para, sen, ins), ([NOTE], []))

    def test_whitespace_free_matching(self):
        """ja/zh sentences that s2v joins without a space still match their paragraph."""
        text = HEAD % "ja" + "\n# 始め {#a}\n\n始めです。\n\n::title[ノート]\n\n# 本文 {#b}\n\n%s\nこれは例です。次も例です。\n" % M
        sen = [{"id": "a:0:0", "text": "始めです。"}, {"id": "b:0:0", "text": "これは例です。"},
               {"id": "b:0:1", "text": "次も例です。"}]
        ins = {"scenes": [{"id": "a", "title": "始め"}, {"id": "b", "title": "本文"}], "screen_text": []}
        texts, problems = notes.marked(text, sen + [{"id": "b:1:0", "text": "x" * 200}], ins)
        self.assertEqual(texts, ["これは例です。", "次も例です。"])
        self.assertEqual(problems, [])
        _t, problems = notes.marked(text.replace("次も", "次は"), sen, ins)
        self.assertTrue(any("does not match s2v's sentences" in p for p in problems))

    def test_caps(self):
        blocks = "\n\n".join("%s\n설명 %s 입니다." % (M, w) for w in ("가", "나", "다", "라"))
        self.assertEqual(self.marked(blocks)[1], [])
        self.problem(blocks + "\n\n%s\n설명 마 입니다." % M, "5 marked teaching-note blocks — at most 4")
        items = "".join("- 항목 %s\n" % w for w in "가나다라마바사아")
        self.assertEqual(self.marked("%s\n:::bullets\n%s:::" % (M, items))[1], [])
        self.problem("%s\n:::bullets\n%s- 항목 자\n:::" % (M, items), "9 teaching-note texts — at most 8")
        self.assertEqual(self.marked("%s\n:::bullets\n- %s\n:::" % (M, "가" * 120))[1], [])
        self.problem("%s\n:::bullets\n- %s\n:::" % (M, "가" * 121), "longer than 120 characters")
        # the share: narration notes against all narration
        many = " ".join("설명 %s 입니다 %s." % (w, "나" * 90) for w in "가다라마")
        self.problem("%s\n%s" % (M, many), "% of the narration — at most 15 %")

    def test_blocks_bind_markers_only(self):
        a = script("%s\n%s" % (M, NOTE))
        self.assertEqual(notes.blocks(a), [NOTE])
        self.assertEqual(notes.blocks(a.replace(M + "\n", "")), [])
        self.assertNotEqual(notes.blocks(a), notes.blocks(a.replace("와로", "와")))


class TextRules(unittest.TestCase):
    CM = {"claims": {cid(E1): {"excerpt": E1, "sentences": [S1]}}, "excerpts": [E1, E2]}

    def test_numbers_dates_and_claim_sentences(self):
        self.assertEqual(notes.text_problems([NOTE], self.CM), [])
        for t in ("3번 출구로 갑니다.", "5일에 읽습니다.", "두 번 읽습니다."):
            self.assertIn("never holds a number or a date", " ".join(notes.text_problems([t], self.CM)), t)
        self.assertIn("either a claim's sentence or a teaching note", notes.text_problems([S1], self.CM)[0])

    def test_terms(self):
        ts = linkrule.terms([E1, E2])
        self.assertEqual(linkrule.terms_in("空港과 탑승권과 카운터", ts), ["空港", "카운터", "탑승권"])
        self.assertEqual(linkrule.term_in("空港과 탑승권", ts) in ("空港", "탑승권"), True)
        self.assertEqual(notes.terms_of(NOTE, self.CM), [])
        self.assertEqual(notes.terms_of("空港은 くうこう로 읽습니다", self.CM), ["空港"])

    def test_screen_warnings_skip_notes(self):
        screen = [{"text": "漢字를 읽습니다"}]
        self.assertEqual(len(ccheck.screen_warnings(screen, self.CM)), 1)
        self.assertEqual(ccheck.screen_warnings(screen, self.CM, ["漢字를 읽습니다"]), [])


class Draft(unittest.TestCase):
    CM = {"claims": {cid(E1): {"excerpt": E1, "sentences": [S1]}}, "excerpts": [E1]}
    N = "조사로 쓰일 때 は는 와로 읽습니다."
    BASIS = "일본어 문법서: 조사 は는 wa로 발음한다"

    def run_(self, entries, notes_=(N,), sentences=None):
        sentences = sentences if sentences is not None else [{"text": S1}, {"text": self.N}]
        return ccheck.draft_problems({"sentences": entries}, self.CM, Text(E1), sentences, [], (), notes_)

    def fact(self):
        return {"text": S1, "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]}

    def note(self, **kw):
        e = {"text": self.N, "kind": "note", "verdict": "supported", "basis": self.BASIS, "claims": [], "excerpts": []}
        e.update(kw)
        return e

    def test_a_good_note(self):
        self.assertEqual(self.run_([self.fact(), self.note()]), [])

    def test_kinds_follow_the_script(self):
        self.assertIn("is a teaching note in the script — its kind is note",
                      " ".join(self.run_([self.fact(), dict(self.note(), kind="fact")])))
        self.assertIn("(note) is not marked as a teaching note", " ".join(self.run_([self.fact(), self.note()], ())))
        self.assertIn("needs text and a kind (fact | link | note)",
                      " ".join(self.run_([self.fact(), dict(self.note(), kind="tip")])))

    def test_the_basis(self):
        for basis, want in (("", "needs a basis"), (None, "needs a basis"), ("a\nb", "one line"),
                            ("가" * 201, "longer than 200"), ("ok End of question", "must not say")):
            self.assertIn(want, " ".join(self.run_([self.fact(), self.note(basis=basis)])), basis)
        self.assertEqual(self.run_([self.fact(), self.note(basis="가" * 200)]), [])

    def test_no_claims_no_excerpts_a_verdict(self):
        self.assertIn("cites claims or excerpts", " ".join(self.run_([self.fact(), self.note(claims=[cid(E1)])])))
        self.assertIn("cites claims or excerpts", " ".join(self.run_([self.fact(), self.note(excerpts=[E1])])))
        self.assertIn("(note) has no verdict", " ".join(self.run_([self.fact(), self.note(verdict="")])))
        self.assertIn("is unsupported", " ".join(self.run_([self.fact(), self.note(verdict="unsupported")])))

    def test_terms_named_in_the_basis(self):
        n = "空港은 くうこう로 읽습니다"
        sentences = [{"text": S1}, {"text": n}]
        e = {"text": n, "kind": "note", "verdict": "supported", "basis": "일본어 사전: 공항이라는 낱말의 읽기",
             "claims": [], "excerpts": []}
        out = " ".join(self.run_([self.fact(), e], (n,), sentences))
        self.assertIn('terms must be ["空港"]', out)
        e["terms"] = ["空港"]
        self.assertIn("the basis names 空港", " ".join(self.run_([self.fact(), e], (n,), sentences)))
        e["basis"] = "일본어 사전: 空港의 읽기는 くうこう"
        self.assertEqual(self.run_([self.fact(), e], (n,), sentences), [])

    def test_the_link_cap_counts_no_notes(self):
        links = [{"text": "넘어가 볼게요 %s." % w, "kind": "link", "note": "a transition"} for w in "가나다"]
        ns = ["설명 %s 입니다." % w for w in "가나다라마바사아"]
        entries = [self.fact()] + links + [self.note(text=t) for t in ns]
        sentences = [{"text": S1}] + [{"text": l["text"]} for l in links] + [{"text": t} for t in ns]
        out = self.run_(entries, ns, sentences)
        self.assertIn("3 link sentences — at most 2", " ".join(out))  # 4 judged without the 8 notes (12 with: 3)
        self.assertEqual([p for p in out if "link sentences" in p],
                         [p for p in self.run_([self.fact()] + links, (), sentences[:4]) if "link sentences" in p])


class VerifyFiles(unittest.TestCase):
    STATE = {"video": "v1"}
    SHAS = {"script": "a", "source_copy": "b", "claims_map": "c", "draft": "d"}

    def test_without_notes_the_bytes_of_0_1_1(self):
        draft = {"sentences": [
            {"text": S1, "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1], "note": "n"},
            {"text": "다음을 봅시다.", "kind": "link", "note": "a transition", "basis": "ignored", "terms": ["x"]},
            {"text": S2, "kind": "fact", "verdict": "supported", "claims": [cid(E2)], "excerpts": [E2], "note": ""}]}
        for d in (draft, {"sentences": draft["sentences"][:1]}):
            new = ccheck.verify_json(self.STATE, "ko", d, self.SHAS)
            self.assertEqual(json.dumps(new, ensure_ascii=False, sort_keys=True),
                             json.dumps(verifyref.verify_json(self.STATE, "ko", d, self.SHAS), ensure_ascii=False,
                                        sort_keys=True))
            self.assertEqual(ccheck.verify_md(new), verifyref.verify_md(new))
            self.assertNotIn("Teaching notes", ccheck.verify_md(new))

    def test_notes_section(self):
        draft = {"sentences": [
            {"text": S1, "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]},
            {"text": "空港은 くうこう로 읽습니다", "kind": "note", "verdict": "supported", "basis": "사전: 空港은 くうこう",
             "terms": ["空港"], "claims": [], "excerpts": [], "from": "screen"}]}
        v = ccheck.verify_json(self.STATE, "ko", draft, self.SHAS)
        self.assertEqual(v["sentences"][1], {"text": "空港은 くうこう로 읽습니다", "kind": "note", "verdict": "supported",
                                             "basis": "사전: 空港은 くうこう", "terms": ["空港"], "claims": [],
                                             "excerpts": []})
        self.assertNotIn("basis", v["sentences"][0])
        md = ccheck.verify_md(v)
        self.assertIn("## Teaching notes (general knowledge, not from the source — approved at ①)\n\n"
                      "1. 空港은 くうこう로 읽습니다\n   - basis: 사전: 空港은 くうこう\n   - words of the source: 空港\n", md)
        self.assertLess(md.index("## Link sentences"), md.index("## Teaching notes"))


class CopyCheck(StudioTestCase):
    def test_a_note_is_not_copy_material(self):
        vdir = os.path.join(self.tmp, "v1")
        os.makedirs(os.path.join(vdir, "work", "ko"))
        cm = {"claims": {}, "excerpts": [E1], "copy_excerpts": {"youtube": []}}
        with open(os.path.join(vdir, "work", "ko", "copy-verify.youtube.json"), "w") as f:
            json.dump({"sentences": []}, f)
        own = ["여행 단어를 배워요.", "조사로 쓰일 때 이 글자는 와로 읽습니다."]
        before = factcheck.problems(vdir, "ko", "youtube", cm, Text(E1), own)
        self.assertEqual(before, [])  # no verify.json, or one without notes: as before
        with open(os.path.join(vdir, "work", "ko", "verify.json"), "w") as f:
            json.dump({"sentences": [{"text": S1, "kind": "fact"}, {"text": NOTE, "kind": "note"}]}, f,
                      ensure_ascii=False)
        out = factcheck.problems(vdir, "ko", "youtube", cm, Text(E1), own)
        self.assertEqual(out, ["a teaching note is not copy material: the copy says only what the source says "
                               "(조사로 쓰일 때 이 글자는 와로 읽습니다.)"])
        self.assertEqual(factcheck.problems(vdir, "ko", "youtube", cm, Text(E1), own[:1]), [])
        # a short note (a table cell such as 읽기) is refused only as a whole sentence, never inside ordinary copy
        with open(os.path.join(vdir, "work", "ko", "verify.json"), "w") as f:
            json.dump({"sentences": [{"text": "읽기", "kind": "note"}, {"text": NOTE, "kind": "note"}]}, f,
                      ensure_ascii=False)
        self.assertEqual(factcheck.problems(vdir, "ko", "youtube", cm, Text(E1), ["읽기 연습을 해 봅니다."]), [])
        self.assertEqual(len(factcheck.problems(vdir, "ko", "youtube", cm, Text(E1), ["읽기"])), 1)
        self.assertEqual(len(factcheck.problems(vdir, "ko", "youtube", cm, Text(E1),
                                                ["여기서 " + NOTE.replace(" ", "  ")])), 1)


# ---------------------------------------------------------------- a video with a note, through ① (fake s2v)

CARD = "%s\n:::bullets\n- 空港은 くうこう로 읽습니다\n:::\n" % M
NOTE_TEXT = "空港은 くうこう로 읽습니다"
BASIS = "일본어 사전: 空港의 읽기는 くうこう"
NOTE_LINE = '원문 밖 설명: "%s" — 근거: %s — 원문 용어: 空港' % (NOTE_TEXT, BASIS)
SESSION = "sess-notes"


class NotesFlow(FlowCase):
    def setUp(self):
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.tool = 0
        self.to_brief()
        self.script()
        self.cmap()

    def script(self, s1=S1, s2=S2, max=600, target=6, extra=CARD):
        FlowCase.script(self, s1, s2, max, target)
        p = os.path.join(self.vdir, "script.ko.md")
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(text.replace(":::quote\n空港(くうこう)\n:::\n", ":::quote\n空港(くうこう)\n:::\n\n" + extra, 1))

    def check(self, *extra):
        return self.run_fn(ccli.main, "v1", *extra, providers=self.providers)

    def draft(self, basis=BASIS, **note):
        e = {"text": NOTE_TEXT, "kind": "note", "verdict": "supported", "basis": basis, "claims": [],
             "excerpts": [], "terms": ["空港"]}
        e.update(note)
        d = {"sentences": [
            {"text": S1, "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]},
            {"text": "空港(くうこう)", "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]},
            {"text": S2, "kind": "fact", "verdict": "supported", "claims": [cid(E2)], "excerpts": [E2]},
            {"text": "출국", "kind": "fact", "verdict": "supported", "claims": [cid(E2)], "excerpts": [E2]},
            e] + rendered()}
        with open(os.path.join(self.w, "verify.draft.json"), "w") as f:
            json.dump(d, f, ensure_ascii=False)

    def pend(self, argv, answer, question):
        self.tool += 1
        ev = {"schema": 1, "argv_sha": argv_sha(list(argv)), "session_id": SESSION, "tool_use_id": "toolu_%d" % self.tool,
              "question_index": 0, "answer": answer, "mode": "human", "written_at": stamp()}
        if question is not None:
            ev["question"] = question
        os.makedirs(evidence.local_dir(self.repo), exist_ok=True)
        with open(evidence.pending_path(self.repo), "w") as f:
            json.dump(ev, f, ensure_ascii=False)

    def to_one(self):
        self.assertEqual(self.check("--narration"), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "script"), 0, self.err)
        self.draft()
        self.assertEqual(self.check(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "verify"), 0, self.err)

    def shown(self):
        self.assertEqual(self.state("shown", "v1", "1"), 0, self.err)
        return [l.split()[1] for l in self.out.splitlines() if l.startswith("hash12 ")][0]

    def test_script_check_and_skeleton(self):
        self.assertEqual(self.check("--narration"), 0, self.out)
        self.assertEqual(self.result()["details"]["notes"], 1)
        self.assertEqual(self.check("--skeleton"), 0, self.out)
        with open(os.path.join(self.w, "verify.draft.json")) as f:
            d = json.load(f)
        e = [x for x in d["sentences"] if x["text"] == NOTE_TEXT][0]
        self.assertEqual(e, {"text": NOTE_TEXT, "from": "screen", "kind": "note", "verdict": "", "basis": "",
                             "claims": [], "excerpts": [], "terms": ["空港"]})
        # the fact-checker fills it; the skeleton keeps it — until the script unmarks it (then it starts again)
        e.update(verdict="supported", basis=BASIS)
        with open(os.path.join(self.w, "verify.draft.json"), "w") as f:
            json.dump(d, f, ensure_ascii=False)
        self.assertEqual(self.check("--skeleton"), 0, self.out)
        with open(os.path.join(self.w, "verify.draft.json")) as f:
            self.assertEqual([x for x in json.load(f)["sentences"] if x["text"] == NOTE_TEXT][0]["basis"], BASIS)
        self.script(extra=CARD.replace(M + "\n", ""))
        self.assertEqual(self.check("--skeleton"), 0, self.out)
        self.assertIn("kept 6 · added 1", self.out)
        with open(os.path.join(self.w, "verify.draft.json")) as f:
            e = [x for x in json.load(f)["sentences"] if x["text"] == NOTE_TEXT][0]
        self.assertEqual((e["kind"], e["verdict"], "basis" in e), ("fact", "", False))
        self.script()  # marked again: a note entry anew
        self.assertEqual(self.check("--skeleton"), 0, self.out)
        self.assertIn("kept 6 · added 1", self.out)

    def test_script_check_refuses(self):
        self.script(extra=CARD.replace("空港은 くうこう로 읽습니다", "3번 출구로 갑니다"))
        self.assertEqual(self.check("--narration"), 1, self.out)
        self.assertIn("never holds a number or a date", self.out)
        self.script(extra=CARD.replace("空港은 くうこう로 읽습니다", S2))
        self.assertEqual(self.check("--narration"), 1, self.out)
        self.assertIn("either a claim's sentence or a teaching note", self.out)

    def test_through_one(self):
        self.to_one()
        with open(os.path.join(self.w, "verify.json")) as f:
            v = json.load(f)
        self.assertEqual([s for s in v["sentences"] if s["kind"] == "note"][0]["basis"], BASIS)
        with open(os.path.join(self.w, "verify.md")) as f:
            self.assertIn("## Teaching notes", f.read())
        h = self.shown()
        self.assertIn("in the question: %s" % NOTE_LINE, self.out)
        block = self.out[self.out.index("question (paste"):]
        self.assertIn("\n%s\nend of question" % NOTE_LINE, block)
        with open(os.path.join(self.w, "shown.json")) as f:
            self.assertEqual(json.load(f)["1"]["-"]["lines"], [NOTE_LINE])
        argv = ["approve", "v1", "1", "--expect", h]
        q = "[v1] ① 대본 · hash %s" % h
        for question in (q, None):  # the note line missing, or no question at all: refused, the answer stays unused
            self.pend(argv, "승인 v1 %s" % h, question)
            self.assertEqual(self.state(*argv), 6, self.err)
            self.assertIn("gate-lines-not-shown", self.err)
            self.assertTrue(os.path.exists(evidence.pending_path(self.repo)))
        self.pend(argv, "승인 v1 %s" % h, q + "\n" + NOTE_LINE)
        self.assertEqual(self.state(*argv), 0, self.err)
        rec = store.read_state(self.vdir)["langs"]["ko"]["approved"]["1"]
        self.assertIn("notes", rec["tuple"])
        # unmarking (or adding) a marker after ① sends the video to verify: s2v's content is the same
        self.script(extra=CARD.replace(M + "\n", ""))
        self.assertEqual(self.state("next", "v1", "--json"), 0, self.err)
        d = json.loads(self.out)
        self.assertEqual(d["redo"]["stage"], "verify", d)
        self.assertIn("notes changed (1)", d["redo"]["why"])

    def test_a_source_commit_line_is_required_too(self):
        self.to_one()
        st = store.read_state(self.vdir)
        st["source"]["commits_since_begin"] = [{"sha": "ab" * 20, "subject": "edit the article", "stat": "+1 -1"}]
        with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
            json.dump(st, f, ensure_ascii=False)
        h = self.shown()
        commit = "원본이 begin 뒤에 커밋됨: %s edit the article (+1 -1)" % ("ab" * 6)
        self.assertIn("in the question: %s" % commit, self.out)
        argv = ["approve", "v1", "1", "--expect", h]
        q = "[v1] ① 대본 · hash %s" % h
        self.pend(argv, "승인 v1 %s" % h, q + "\n" + NOTE_LINE)  # the note line, not the commit line
        self.assertEqual(self.state(*argv), 6, self.err)
        self.assertIn("gate-lines-not-shown", self.err)
        self.assertIn(commit, self.err)
        self.pend(argv, "승인 v1 %s" % h, ["not", "text"])  # a question that is not text shows nothing (no traceback)
        self.assertEqual(self.state(*argv), 6, self.err)
        self.assertIn("gate-lines-not-shown", self.err)
        self.pend(argv, "승인 v1 %s" % h, "\n".join([q, commit, NOTE_LINE]))
        self.assertEqual(self.state(*argv), 0, self.err)

    def test_a_proxy_approval_is_not_checked(self):
        self.to_one()
        h = self.shown()
        argv = ["approve", "v1", "1", "--expect", h, "--proxy"]
        ev = {"schema": 1, "argv_sha": argv_sha(argv), "session_id": SESSION, "tool_use_id": "toolu_p",
              "question_index": 0, "question": "proxy", "answer": "승인 v1 %s" % h, "mode": "proxy",
              "written_at": stamp()}  # what the guard writes in the sandbox proxy mode
        os.makedirs(evidence.local_dir(self.repo), exist_ok=True)
        with open(evidence.pending_path(self.repo), "w") as f:
            json.dump(ev, f)
        code = self.state(*argv)
        self.assertNotIn("gate-lines-not-shown", self.err)
        self.assertEqual(code, 0, self.err)

    def test_malformed_lines_are_never_skipped(self):
        self.to_one()
        h = self.shown()
        st = store.read_state(self.vdir)
        st["langs"]["ko"]["shown"]["1"]["-"]["lines"] = "not a list"
        with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
            json.dump(st, f)
        argv = ["approve", "v1", "1", "--expect", h]
        self.pend(argv, "승인 v1 %s" % h, "[v1] ① · hash %s\n%s" % (h, NOTE_LINE))
        self.assertEqual(self.state(*argv), 6, self.err)
        self.assertIn("gate-lines-unknown", self.err)

    def test_a_changed_basis_needs_shown_again(self):
        self.to_one()
        h = self.shown()
        self.draft(basis="일본어 사전: 空港은 くうこう로 읽는다")
        self.assertEqual(self.check(), 0, self.out)
        argv = ["approve", "v1", "1", "--expect", h]
        self.pend(argv, "승인 v1 %s" % h, "[v1] ① · hash %s\n%s" % (h, NOTE_LINE))
        self.assertEqual(self.state(*argv), 1, self.err)
        self.assertIn("changed after it was shown", self.err)

    def test_verify_runs_the_caps_again(self):
        """A marker added after ① sends the video to verify (not script): verify checks the caps itself."""
        self.to_one()
        more = CARD + "".join("\n%s\n:::bullets\n- 설명 %s 입니다\n:::\n" % (M, w) for w in "가나다라")
        self.script(extra=more)
        self.assertEqual(self.check(), 1, self.out)
        self.assertIn("5 marked teaching-note blocks — at most 4", self.out)


class NoMarkerScript(FlowCase):
    """A script without markers gives 0.1.1's result: no `notes` in the check result or the ① tuple, no lines in
    shown.json; and review 4 m1 — `::thumbnail` with a lead-in line (s2v's implicit scene) adds no note problem."""

    def test_the_script_check_is_as_before(self):
        self.to_brief()
        self.script()
        text = open(os.path.join(self.vdir, "script.ko.md")).read()
        text = text.replace("---\n\n# 공항", "---\n\n머리말입니다.\n\n::thumbnail{src=\"../../../docs/img/gate.png\"}\n\n"
                                           "# 공항", 1)
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text)
        self.cmap()
        outs = []
        for patch in (False, True):
            orig = notes.marked
            if patch:  # 0.1.1: no teaching-note code at all
                ccli.notes.marked = lambda *a: ([], [])
            try:
                code = self.run_fn(ccli.main, "v1", "--narration", providers=self.providers)
            finally:
                ccli.notes.marked = orig
            r = self.result()
            outs.append((code, self.out, r["result"], r["details"]))
        self.assertEqual(outs[0], outs[1])
        self.assertNotIn("notes", outs[0][3])
        self.assertFalse(any("teaching" in p or "s2v sees" in p for p in outs[0][3]["problems"]))

    def test_no_notes_field(self):
        self.to_brief()
        self.script()
        ctx = cli._ctx(self.repo, cli._cfg_of(self.repo), self.vdir, "ko")
        cur = self.providers.collect(ctx, store.read_state(self.vdir), "ko")
        self.assertNotIn("notes", cur)
        t = router.tuple_for("1", cur)
        self.assertEqual(set(t), {"brief_core", "content", "source_hash"})


class TupleUnit(unittest.TestCase):
    def test_an_approved_video_without_markers_keeps_its_decision(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        before = router.decide(s, "ko", c).as_dict()
        self.assertEqual(router.decide(s, "ko", dict(c)).as_dict(), before)
        d = router.decide(s, "ko", dict(c, notes="n1"))  # a marker added after ①
        self.assertEqual(d.redo["stage"], "verify")
        self.assertEqual(d.redo["why"], ["notes changed (1)"])


class GuardNoteLines(JudgeCase):
    """G1 compares the ① question with the source-commit lines and the note lines `shown 1` recorded."""
    H = "3f2a9c0d1e4b"

    def setUp(self):
        super().setUp()
        import transcripts as TR
        self.TR = TR
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        self.tpath = TR.transcript_path(self.env)
        st = F.state()
        st["video"] = "v"
        st["langs"]["ko"].setdefault("shown", {})["1"] = {"-": {"hash": "x", "at": "t", "lines": [NOTE_LINE]}}
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump(st, f, ensure_ascii=False)

    def run_hook(self, qtext, cmd):
        t = self.TR.approval_turn(self.TR.T(), "승인 v %s" % self.H, qtext=qtext)
        t.write(self.tpath)
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": t.prompt}
        from stdo.guard import judge
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def pending(self):
        try:
            with open(os.path.join(self.repo, ".claude", "studio", "local", "pending-approval.json")) as f:
                return json.load(f)
        except OSError:
            return None

    def test_the_note_lines(self):
        cmd = "python3 .claude/studio/scripts/state.py approve v 1 --expect %s" % self.H
        base = "[v] ① 대본 — studio/videos/v/script.ko.md · hash %s" % self.H
        deny, _ = self.run_hook(base, cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn(NOTE_LINE, deny.message())
        deny, ctx = self.run_hook(base + "\n" + NOTE_LINE, cmd)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)

    def test_after_a_source_the_script_checks(self):
        """After a `source` only the 0.0.26 guard judges: it does not know the note lines, so the pending answer can
        lack them — `state.py approve 1` refuses that itself (NotesFlow.test_through_one, the same hand evidence)."""
        cmd = "source /dev/null; python3 .claude/studio/scripts/state.py approve v 1 --expect %s" % self.H
        base = "[v] ① 대본 — studio/videos/v/script.ko.md · hash %s" % self.H
        deny, _ = self.run_hook(base, cmd)
        if deny is None:
            p = self.pending()
            self.assertIsNotNone(p)
            self.assertNotIn(NOTE_LINE, p.get("question") or "")
            from stdo.commit.summary import first_missing
            self.assertIsNotNone(first_missing([NOTE_LINE], p.get("question") or ""))  # what the script refuses
        else:
            self.assertEqual(deny.rule[:2], "G-")


class RealS2v(S2vCase):
    """The comment rule and the probes on real s2v (STUDIO_TEST_S2V; skipped without it, a failure in --full)."""
    main = None

    def setUp(self):
        super().setUp()
        helpers.s2v_path(self)

    def ids_and_hash(self, text):
        sen, ins = self.s2v(text)
        return [s["id"] for s in sen], ins["hashes"]["content"], ins["hashes"]["voice"]

    def test_a_placed_marker_changes_nothing(self):
        plain = script("%s\n\n:::bullets\n- 가\n:::" % NOTE)
        marked = script("%s\n%s\n\n%s\n:::bullets\n- 가\n:::" % (M, NOTE, M))
        self.assertEqual(self.ids_and_hash(plain), self.ids_and_hash(marked))
        under = HEAD % "ko" + INTRO + "\n# 본문 {#body}\n%s\n%s\n" % (M, NOTE)
        self.assertEqual(self.ids_and_hash(under), self.ids_and_hash(under.replace(M + "\n", "")))
        sen, ins = self.s2v(marked)
        self.assertEqual(notes.marked(marked, sen, ins), ([NOTE, "가"], []))

    def test_no_blank_line_above_splits_the_paragraph(self):
        text = script("가 문장. 나 문장.\n%s\n다 문장." % M)
        ids = self.ids_and_hash(text)[0]
        self.assertEqual(ids[-3:], ["body:1:0", "body:1:1", "body:2:0"])
        sen, ins = self.s2v(text)
        self.assertIn(notes.ABOVE, notes.marked(text, sen, ins)[1])

    def test_scenes_by_identity(self):
        for text in (HIDDEN, LEAD_HIDDEN):
            sen, ins = self.s2v(text)
            texts, problems = notes.marked(text, sen, ins)
            self.assertEqual(texts, [], text)
            self.assertTrue(any("the scenes do not match s2v's" in p for p in problems), problems)
        sen, ins = self.s2v(LEAD_NOTE)
        self.assertEqual(notes.marked(LEAD_NOTE, sen, ins), ([NOTE], []))

    def test_cards_the_walk_reads_as_s2v_does(self):
        for what, body in WALK.items():
            text = script(body)
            sen, ins = self.s2v(text)
            texts, problems = notes.marked(text, sen, ins)
            self.assertNotIn(FACT, texts, what)
            self.assertTrue(problems, what)
        text = script(AFTER_HTML)
        sen, ins = self.s2v(text)
        self.assertIn(notes.ABOVE, notes.marked(text, sen, ins)[1])

    def test_empty_card(self):
        text = script(":::bullets\n:::\n\n%s\n:::bullets\n- 마\n:::" % M)
        sen, ins = self.s2v(text)
        self.assertTrue(any("but s2v shows 1" in p for p in notes.marked(text, sen, ins)[1]))


class FakeMatchesReal(S2vCase):
    """The fake's screen_text and sentence ids equal real s2v's for the shapes Studio reads (one entry per item, cell
    and markdown block; paragraph entries; headings, the frontmatter title and the speaker's name; comments dropped)."""

    def setUp(self):
        super().setUp()
        helpers.s2v_path(self)

    def test_same_walk_cases(self):
        for body in list(WALK.values()) + [AFTER_HTML, HEADINGS]:
            text = script(body)
            self.main = FAKE_MAIN
            fake = self.s2v(text)
            self.main = None
            real = self.s2v(text)
            keys = ("scene", "block", "directive", "attr", "text")
            self.assertEqual([[e.get(k) for k in keys] for e in fake[1]["screen_text"]],
                             [[e.get(k) for k in keys] for e in real[1]["screen_text"]], body)
            self.assertEqual([(s["id"], s["text"]) for s in fake[0]], [(s["id"], s["text"]) for s in real[0]], body)

    def test_same_screen_text(self):
        body = ("%s\n%s\n\n%s\n:::table\n| 글자 | 읽기 |\n|---|---|\n| は | 와 |\n| | 빈칸 |\n:::\n\n:::bullets\n:::\n\n"
                ":::quote{by=\"누군가\"}\n空港(くうこう)\n둘째 줄\n:::\n\n:::compare\n## 왼쪽\n- 가\n## 오른쪽\n- 다\n:::\n\n"
                ":::markdown\n첫 문단 **굵게**\n이어지는 줄.\n\n## 소제목\n\n- 항목 `코드`\n:::\n\n가 문장. 나 문장.\n%s\n다 문장."
                % (M, NOTE, M, M))
        text = script(body)
        fake = self.s2v(text)
        self.main = None
        real = self.s2v(text)
        keys = ("scene", "block", "directive", "attr", "text")
        self.assertEqual([[e.get(k) for k in keys] for e in fake[1]["screen_text"]],
                         [[e.get(k) for k in keys] for e in real[1]["screen_text"]])
        self.assertEqual([(s["id"], s["text"]) for s in fake[0]], [(s["id"], s["text"]) for s in real[0]])


if __name__ == "__main__":
    unittest.main()
