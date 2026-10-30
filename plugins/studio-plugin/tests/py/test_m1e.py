"""M1e (m1-plan §7): the one excerpt normalization, the brief's computed length, check_claims.py (the script check and
verify → verify.json · verify.md), gate ①'s artifacts, the external auditor's guard rule, J32 (`unread-word` only from
cast on, pinned in STAGE_CHECKS), and the M1d re-review items R1 (record-source freezes only committed writing), R2
(a credit line a blank line above an image) and R3 (lines hidden by an unclosed HTML comment)."""

import contextlib
import hashlib
import io
import json
import os
import struct
import subprocess
import sys

import helpers
import state_fixtures as F
from approve_base import ApproveCase
from helpers import StudioTestCase
from stdo import machine, s2vlint
from stdo.claims import check as ccheck, cli as ccli, sourcemd
from stdo.source import assets, cli as src_cli, imgformat, refs
from stdo.state import cli, gates, router, schema, stagechecks, store
from stdo.state.collect import Providers
from stdo.state.hashes import file_sha
from stdo.text import normalize as N
from test_guard_judge import JudgeCase
from test_m1b import need_node
from test_state_store import StoreCase

sys.path.insert(0, os.path.join(helpers.HERE, "drivers"))
import make_harness  # noqa: E402

FAKE_ROOT = os.path.join(helpers.HERE, "drivers", "fake_s2v_cli")
RUBY = "<ruby>空港<rp>(</rp><rt>くうこう</rt><rp>)</rp></ruby>"
E1 = "공항(%s)에 가면 먼저 체크인 카운터를 찾습니다." % RUBY
E2 = "탑승권을 받으면 출국 심사를 받습니다."
ARTICLE = """---
title: 공항 단어
---

# 공항 단어

%s

%s

![gate](img/gate.png)
""" % (E1, E2)
S1 = "공항에 가면 먼저 체크인 카운터를 찾습니다."
S2 = "탑승권을 받으면 출국 심사를 받습니다."
SCRIPT = """---
title: 공항 단어
lang: ko
outputs:
  youtube: { maxDuration: %(max)s }
targetDuration: %(target)s
---

# 공항 {#airport}

%(s1)s

:::quote
空港(くうこう)
:::

::image{src="../../../docs/img/gate.png"}

# 출국 {#exit}

%(s2)s
"""


def png(w=4, h=3):
    return imgformat.PNG_SIG + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00" + \
        b"\x00\x00\x00\x00"


def cid(e):
    return sourcemd.claim_id(e)


# ---------------------------------------------------------------- §7.1 normalization

class Normalize(StudioTestCase):
    def test_forms(self):
        src = "# 제목\n\n공항(%s)에 **먼저** [체크인](x.html) `카운터`를 *찾습니다*. <!-- 숨김 -->\n> 인용 &amp; 끝\n" \
              "- 목록\n![img](a.png)\n```\ncode\n```\n" % RUBY
        self.assertEqual(N.plain(src), "제목 공항(空港)에 먼저 체크인 카운터를 찾습니다. 인용 & 끝 목록 code")
        self.assertEqual(N.plain(src, "reading"), "제목 공항(空港(くうこう))에 먼저 체크인 카운터를 찾습니다. 인용 & 끝 목록 code")
        self.assertEqual(N.plain("<ruby>漢<rt>かん</rt>字<rt>じ</rt></ruby>", "reading"), "漢(かん)字(じ)")
        self.assertEqual(N.plain("snake_case a_b_c  \r\n x"), "snake_case a_b_c x")
        self.assertEqual(N.plain("café"), "café")
        with self.assertRaises(ValueError):
            N.plain("x", "other")

    def test_s2_deleted_text_is_not_there(self):
        self.assertEqual(N.plain("a ~~old claim~~ b <del>x</del> c <s>y</s> d <STRIKE>z</STRIKE> e <span>k</span> "
                                 "<sub>2</sub> <strong>s</strong>"), "a b c d e k 2 s")
        t = N.Text("The fee is <del>10 dollars</del> 12 dollars. ~~Open on Sundays.~~")
        self.assertFalse(t.contains("10 dollars"))
        self.assertFalse(t.contains("Open on Sundays."))
        self.assertTrue(t.contains("12 dollars"))
        # check_claims: a struck-out excerpt is no support
        cm = {"claims": {cid("Open on Sundays."): {"excerpt": "Open on Sundays.", "sentences": ["x"]}},
              "excerpts": ["Open on Sundays."]}
        draft = {"sentences": [{"text": "x", "kind": "fact", "verdict": "supported",
                                "claims": [cid("Open on Sundays.")], "excerpts": ["Open on Sundays."]}]}
        self.assertIn("sentence 1: an excerpt is not in the source copy: Open on Sundays.",
                      ccheck.draft_problems(draft, cm, t, [], []))

    def test_contains(self):
        t = N.Text(ARTICLE)
        self.assertTrue(t.contains("공항(空港)에 가면"))  # plain: the written form
        self.assertTrue(t.contains("空港(くうこう)"))  # plain: the "글자(읽기)" form
        self.assertTrue(t.contains(E1))  # with ruby: its reading form
        self.assertFalse(t.contains(E1.replace("くうこう", "くーこう")))  # another reading is another excerpt
        self.assertFalse(t.contains(""))
        self.assertFalse(t.contains(None))
        self.assertEqual(N.chars(E1), len("공항(空港)에 가면 먼저 체크인 카운터를 찾습니다."))

    def test_one_function_everywhere(self):
        """check_claims, the router, the source-diff gate and the brief use the same Text (§7.1)."""
        self.assertIs(router.normalize, N.normalize)
        self.assertIs(router.Text, N.Text)
        self.assertIs(ccheck.Text, N.Text)
        from stdo.claims import brief
        self.assertIs(brief.Text, N.Text)
        import inspect
        self.assertIn("from ..text.normalize import Text", inspect.getsource(gates._source_diff))
        self.assertNotIn(" in text", inspect.getsource(gates._source_diff))

    def test_router_source_diff_with_ruby(self):
        before = "# 공항\n\n%s\n\n다른 문장입니다.\n" % E1
        s, c = F.state(), F.current(source_text=before)
        F.approve_all(s, c, upto="2")
        s["langs"]["ko"]["approved"]["1"]["excerpts"] = [E1, "다른 문장"]
        s["source"]["frozen_hash"] = "src2"

        def at(text):
            d = router.decide(s, "ko", F.changed(c, source_hash="src2", source_live_hash="src2", source_text=text))
            return "held" if d.held else d.redo["stage"]
        self.assertEqual(at(before.replace("# 공항", "# 공항 이야기")), "held")  # elsewhere in the source
        self.assertEqual(at(before.replace("먼저 체크인", "먼저 **체크인**")), "held")  # Markdown only
        self.assertEqual(at(before.replace("くうこう", "くーこう")), "script")  # the excerpt's reading changed
        self.assertEqual(at(before.replace(RUBY, "空港")), "script")  # its reading is gone
        self.assertEqual(at(before.replace("다른 문장", "다른 글")), "script")
        self.assertEqual(at(before.replace("다른 문장입니다.", "~~다른 문장입니다.~~")), "script")  # S2: struck out
        self.assertEqual(at(before.replace("다른 문장입니다.", "<del>다른 문장입니다.</del>")), "script")


# ---------------------------------------------------------------- §7.2 the brief's length

class Brief(StoreCase):
    def brief_of(self, claims, **extra):
        return self.brief(claims=claims, **extra)

    def test_estimate_is_computed_by_studio(self):
        code, out, err = self.cli("record-brief", "v1", "--from", self.brief_of([F.C1, F.C2], estimate_seconds=9999))
        self.assertEqual(code, 0, err)
        n = sum(N.chars(e) for e in F.EXCERPTS)
        self.assertIn("estimated length %s s (%d characters ÷ 5.5 per second" % (round(n / 5.5, 1), n), out)
        ev = [e for e in store.read_log(self.vdir) if e.get("event") == "record-brief"][-1]
        self.assertEqual(ev["estimate"]["chars"], n)
        self.assertNotIn("9999", json.dumps(ev))

    def test_counts_normalized_characters(self):
        e = "A **bold**   claim, [here](x.html)."
        F.brief_ready(self.repo, self.vdir, excerpts=(e,))
        code, out, err = self.cli("record-brief", "v1", "--from", self.brief_of([cid(e)]))
        self.assertEqual(code, 0, err)
        self.assertIn("(%d characters" % len("A bold claim, here."), out)

    def test_outside_the_format(self):
        F.write_format(self.repo, length=(5, 600))
        code, _, err = self.cli("record-brief", "v1", "--from", self.brief_of([F.C2]))  # 12 chars: about 2 s
        self.assertEqual(code, 1)
        self.assertIn("choose more claims", err)
        F.write_format(self.repo, length=(1, 3))
        code, _, err = self.cli("record-brief", "v1", "--from", self.brief_of([F.C1, F.C2]))
        self.assertEqual(code, 1)
        self.assertIn("choose fewer claims", err)
        self.assertEqual(self.state()["brief"]["core"], "brief1")  # nothing recorded
        os.remove(os.path.join(self.repo, ".claude", "studio", "formats", "youtube.md"))
        code, _, err = self.cli("record-brief", "v1", "--from", self.brief_of([F.C1]))
        self.assertEqual(code, 1)
        self.assertIn("criteria cannot be read", err)

    def test_claims_must_be_the_analysts_and_in_the_copy(self):
        code, _, err = self.cli("record-brief", "v1", "--from", self.brief_of(["C-00000000"]))
        self.assertEqual((code, "not in work/source.md" in err), (1, True))
        F.brief_ready(self.repo, self.vdir, source_md="- %s: x\n  > %s\n" % (cid("Not in the copy."),
                                                                             "Not in the copy."))
        code, _, err = self.cli("record-brief", "v1", "--from", self.brief_of([cid("Not in the copy.")]))
        self.assertEqual((code, "not in the source copy" in err), (1, True))
        F.brief_ready(self.repo, self.vdir, source_md="- C-12345678: x\n  > %s\n" % F.EXCERPTS[0])
        code, _, err = self.cli("record-brief", "v1", "--from", self.brief_of(["C-12345678"]))
        self.assertEqual((code, "not the id of its excerpt" in err), (1, True))

    def test_checked_assets_must_be_the_recorded_ones(self):
        """J61 · J74: the sha too, not only its presence."""
        with open(os.path.join(self.vdir, "work", "assets.json"), "a") as f:
            f.write(" ")
        code, _, err = self.cli("record-brief", "v1", "--from", self.brief_of([F.C1]))
        self.assertEqual(code, 3)
        self.assertIn("not the one record-source recorded", err)

    def test_sourcemd_parse(self):
        e = "Line one\nline two"
        text = "## Claims\n- %s: two lines\n  > Line one\n  > line two\n- %s: none\n- %s: twice\n  > %s\n" \
               "- %s: twice\n  > %s\n- 空港 → くうこう\n" % (cid(e), cid("x"), cid("y"), "y", cid("y"), "y")
        claims, problems = sourcemd.parse(text)
        self.assertEqual(claims[cid(e)]["excerpt"], e)
        self.assertEqual(sorted(claims), sorted([cid(e), cid("y")]))
        self.assertEqual(len(problems), 2)  # no excerpt; listed twice
        self.assertEqual(sourcemd.read(os.path.join(self.tmp, "nowhere"))[1][0][:22], "work/source.md is miss")


# ---------------------------------------------------------------- a video through source with the fake s2v

class FlowCase(StudioTestCase):
    def setUp(self):
        need_node()
        super().setUp()
        store.enable_writes()
        self.repo = make_harness.make(os.path.join(self.tmp, "site"), s2v=FAKE_ROOT)
        machine.write(self.repo, FAKE_ROOT)
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(p) as f:
            cfg = json.load(f)
        cfg.update(visibility={"default": "unknown", "public": ["docs/**"]})
        with open(p, "w") as f:
            json.dump(cfg, f, indent=2)
        F.write_format(self.repo, length=(1, 600), commit=False)
        os.makedirs(os.path.join(self.repo, "docs", "img"))
        with open(os.path.join(self.repo, "docs", "airport.md"), "w") as f:
            f.write(ARTICLE)
        with open(os.path.join(self.repo, "docs", "img", "gate.png"), "wb") as f:
            f.write(png())
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "site")
        self.scenario({})
        self.providers = Providers()
        self.assertEqual(self.state("begin", "v1", "--source", "docs/airport.md", "--kind", "youtube"), 0, self.err)
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        self.w = os.path.join(self.vdir, "work", "ko")
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)

    def scenario(self, data):
        p = os.path.join(self.tmp, "scenario.json")
        with open(p, "w") as f:
            json.dump(data, f)
        os.environ["STUDIO_TEST_FAKE_S2V_SCENARIO"] = p

    def state(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), providers=self.providers, cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def run_fn(self, fn, *argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fn(list(argv), cwd=self.repo, **kw)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def claims_md(self, extra=""):
        with open(os.path.join(self.vdir, "work", "source.md"), "w") as f:
            f.write("# Source\n\n## Claims\n- %s: the counter first\n  > %s\n- %s: then passport control\n  > %s\n\n"
                    "## Ruby pairs\n- 空港 → くうこう\n\n<!-- studio:images -->\n```json\n%s\n```\n"
                    "<!-- /studio:images -->\n%s" % (cid(E1), E1, cid(E2), E2,
                                                    json.dumps({"img-01": {"class": "diagram", "reason": "own"}}),
                                                    extra))

    def to_brief(self):
        self.assertEqual(self.run_fn(src_cli.resolve_main, "v1"), 0, self.err)
        self.claims_md()
        self.assertEqual(self.run_fn(src_cli.scope_main, "v1"), 0, self.err)
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        self.assertIsNotNone(store.read_state(self.vdir)["source"]["assets_sha"])
        with open(os.path.join(self.vdir, "work", "brief.json"), "w") as f:
            json.dump({"claims": [cid(E1), cid(E2)], "roles": [{"name": "narrator"}], "outputs": ["youtube"],
                       "platforms": {"youtube": ["youtube"]}}, f)
        self.assertEqual(self.state("record-brief", "v1", "--from", "work/brief.json"), 0, self.err)

    def script(self, s1=S1, s2=S2, max=600, target=6):
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(SCRIPT % {"s1": s1, "s2": s2, "max": max, "target": target})

    def cmap(self, **over):
        m = {"claims": {cid(E1): {"excerpt": E1, "sentences": [S1, "空港(くうこう)"]},
                        cid(E2): {"excerpt": E2, "sentences": [S2]}},
             "excerpts": [E1, E2], "copy_excerpts": {}}
        m.update(over)
        os.makedirs(self.w, exist_ok=True)
        with open(os.path.join(self.w, "claims-map.json"), "w") as f:
            json.dump(m, f, ensure_ascii=False)
        return m

    def to_script(self):
        self.to_brief()
        self.script()
        self.cmap()

    def check(self, *extra):
        return self.run_fn(ccli.main, "v1", *extra, providers=self.providers)

    def result(self, stage="script"):
        return stagechecks.read(self.vdir, "ko", stage)


class ScriptCheck(FlowCase):
    def test_pass_then_stage_done(self):
        self.to_script()
        self.assertEqual(self.check("--narration"), 0, self.out + self.err)
        r = self.result()
        self.assertEqual((r["result"], r["details"]["fail_unread"]), ("pass", False))
        self.assertEqual(self.state("stage-done", "v1", "script"), 0, self.err)
        # the checked assets are compared again at stage-done (J61)
        with open(os.path.join(self.vdir, "work", "assets.json"), "a") as f:
            f.write(" ")
        self.assertEqual(self.state("stage-done", "v1", "script"), 1)  # assets.json is one of the check's inputs

    def test_stage_done_compares_the_recorded_assets(self):
        self.to_script()
        self.assertEqual(self.check("--narration"), 0, self.out)
        st = store.read_state(self.vdir)
        st["source"]["assets_sha"] = "0" * 64
        with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
            json.dump(st, f)
        self.assertEqual(self.state("stage-done", "v1", "script"), 3)
        self.assertIn("not the one record-source recorded", self.err)

    def test_length_warnings_fail_although_lint_exits_0(self):
        self.to_script()
        self.script(max=3)
        r = subprocess.run(["node", os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js"), "lint",
                            os.path.join(self.vdir, "script.ko.md")], capture_output=True, text=True,
                           env=dict(os.environ))
        self.assertEqual(r.returncode, 0)
        self.assertIn("[max-duration]", r.stderr)
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("s2v lint: max-duration", self.out)
        self.script(target=60)
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("target-duration", self.out)

    def test_s6_length_follows_the_format(self):
        self.to_script()
        self.script(max=300)  # under the format's 600: lint stays quiet, Studio does not
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("outputs.youtube.maxDuration must be the format's upper bound 600 (it is 300.0)", self.out)
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace("  youtube: { maxDuration: 300 }", "  youtube:\n    aspect: \"16:9\"")
                    .replace("targetDuration: 6\n", ""))
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("maxDuration must be the format's upper bound 600 (it is missing)", self.out)
        self.assertIn("targetDuration must be a number within the format's 1–600 s (it is missing)", self.out)
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace("  youtube: { maxDuration: 300 }", "  youtube:\n    maxDuration: 600"))
        self.assertEqual(self.check("--narration"), 0, self.out)  # a nested block counts too
        self.script(target=900)
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("targetDuration must be a number within", self.out)
        F.write_format(self.repo, length=(30, 600))  # the narration itself: about 8 s
        self.script(target=30)
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("the narration comes to about 8 s", self.out)
        self.assertNotIn("targetDuration", self.out)

    def test_unread_word_is_information_at_script(self):
        """J32: pinned in STAGE_CHECKS (script False, cast and board True), and the script check uses it."""
        self.assertIs(schema.STAGE_CHECKS["script"]["fail_unread"], False)
        self.assertIs(schema.STAGE_CHECKS["cast"]["fail_unread"], True)
        self.assertIs(schema.STAGE_CHECKS["board"]["fail_unread"], True)
        self.to_script()
        self.scenario({"lint": {"warnings": [{"code": "unread-word", "message": "\"OK\" may be read as English"}]}})
        self.assertEqual(self.check("--narration"), 0, self.out)
        self.assertEqual(self.result()["details"]["lint"]["failures"], [])
        lint = s2vlint.run(FAKE_ROOT, os.path.join(self.vdir, "script.ko.md"), "lint", env=dict(os.environ),
                           fail_unread=schema.STAGE_CHECKS["cast"]["fail_unread"])
        self.assertEqual([d["code"] for d in lint.failures], ["unread-word"])

    def test_narration_has_no_kana_or_kanji(self):
        self.to_script()
        self.script(s1="공항(空港)에 가면 먼저 체크인 카운터를 찾습니다.")
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("kana or kanji", self.out)
        self.script(s1="くうこう에 가면 먼저 체크인 카운터를 찾습니다.")
        self.assertEqual(self.check("--narration"), 1)
        self.assertEqual(ccheck.narration_problems([{"id": "a", "text": "空港です"}], "ja"), [])
        self.assertEqual(len(ccheck.narration_problems([{"id": "a", "text": "ｸｳｺｳ"}], "en")), 1)

    def test_images_only_usable_script_src(self):
        self.to_script()
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        with open(os.path.join(self.repo, "docs", "img", "other.png"), "wb") as f:
            f.write(png())
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace("docs/img/gate.png", "docs/img/other.png"))
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("not a usable image of work/assets.json", self.out)

    def test_claims_map_refusals(self):
        self.to_script()
        cases = [
            (dict(excerpts=[E1]), "not in the claims map's excerpts"),
            (dict(excerpts=[E1, E2, "Not in the source."]), "not in the source copy"),
            (dict(claims={cid("x"): {"excerpt": "x", "sentences": [S1]}}, excerpts=["x"]), "not a claim of the brief"),
            (dict(claims={cid(E1): {"excerpt": E1 + " ", "sentences": [S1]}}, excerpts=[E1 + " "]),
             "not the one in work/source.md"),
            (dict(claims={cid(E1): {"excerpt": E1}}), "needs an excerpt and the sentences"),
            (dict(claims={}), "has no claims"),
            (dict(copy_excerpts=[]), "copy_excerpts must be an object"),
        ]
        for over, why in cases:
            self.cmap(**over)
            self.assertEqual(self.check("--narration"), 1, over)
            self.assertIn(why, self.out, over)
        self.cmap()
        with open(os.path.join(self.vdir, "work", "brief.json"), "w") as f:
            json.dump({"claims": [cid(E1)], "roles": [{"name": "narrator"}]}, f)
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("not the brief record-brief recorded", self.out)
        os.remove(os.path.join(self.w, "claims-map.json"))
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn("claims-map.json is missing", self.out)

    def test_usage(self):
        self.assertEqual(self.check("--narration"), 2)  # no script yet
        self.assertIn("no script yet", self.err)
        self.to_script()
        self.assertEqual(self.check("--narration", "--bogus"), 2)
        self.assertEqual(self.run_fn(ccli.main, providers=self.providers), 2)
        self.assertEqual(self.check("--lang", "ja"), 2)


class VerifyCheck(FlowCase):
    def draft(self, **over):
        sentences = [
            {"text": S1, "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]},
            {"text": "空港(くうこう)", "kind": "fact", "verdict": "supported", "claims": [cid(E1)],
             "excerpts": [E1]},
            {"text": S2, "kind": "fact", "verdict": "supported", "claims": [cid(E2)], "excerpts": [E2]},
        ]
        d = {"sentences": sentences}
        d.update(over)
        with open(os.path.join(self.w, "verify.draft.json"), "w") as f:
            json.dump(d, f, ensure_ascii=False)
        return d

    def setUp(self):
        super().setUp()
        self.to_script()
        self.assertEqual(self.check("--narration"), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "script"), 0, self.err)

    def test_pass_writes_verify_json_and_md(self):
        self.draft()
        self.assertEqual(self.check(), 0, self.out)
        with open(os.path.join(self.w, "verify.json")) as f:
            v = json.load(f)
        self.assertEqual([s["text"] for s in v["sentences"]], [S1, "空港(くうこう)", S2])
        self.assertEqual(v["from"]["draft"], file_sha(os.path.join(self.w, "verify.draft.json")))
        with open(os.path.join(self.w, "verify.md")) as f:
            md = f.read()
        self.assertEqual(md, ccheck.verify_md(v))  # the person reads what was judged
        self.assertIn(S1, md)
        self.assertEqual(self.result("verify")["result"], "pass")
        self.assertEqual(self.state("stage-done", "v1", "verify"), 0, self.err)
        # a failed check never leaves the last verify.json behind
        self.draft(sentences=[{"text": S1, "kind": "fact", "verdict": "unsupported"}])
        self.assertEqual(self.check(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.w, "verify.json")))
        self.assertFalse(os.path.exists(os.path.join(self.w, "verify.md")))
        self.assertIn("state.py loop v1 verify", self.out)
        self.assertEqual(self.state("stage-done", "v1", "verify"), 1)

    def test_refusals(self):
        good = self.draft()["sentences"]

        def with_(i, **kw):
            s = [dict(x) for x in good]
            s[i].update(kw)
            return s
        cases = [
            (with_(0, verdict="unsupported"), "is unsupported"),
            (with_(2, verdict="contradicted"), "is contradicted"),
            (with_(0, claims=[]), "mapped to no claim"),
            (with_(0, claims=["C-00000000"]), "not a claim of the claims map"),
            (with_(0, excerpts=[]), "quotes no excerpt"),
            (with_(0, excerpts=["어디에도 없는 문장"]), "not in the source copy"),
            (with_(0, verdict=None), "has no verdict"),
            (with_(0, kind="opinion"), "needs text and a kind"),
            (with_(1, excerpts=["空港(くうこう)"]), "not the excerpt of a claim it cites"),  # S7
            (with_(0, claims=[cid(E2)], excerpts=[E2]), "not among the sentences of %s" % cid(E2)),  # S7
            (good[:2], "not judged: " + S2),
            (good[1:], "not judged: " + S1),
            ([good[0], good[2]], "not judged: 空港(くうこう)"),
        ]
        for sentences, why in cases:
            self.draft(sentences=sentences)
            self.assertEqual(self.check(), 1, why)
            self.assertIn(why, self.out)
        link = good + [{"text": "이번에는 출국을 봅시다.", "kind": "link", "note": "a transition"}]
        self.draft(sentences=link)
        self.assertEqual(self.check(), 0, self.out)  # a link sentence needs no verdict (but a note)
        with open(os.path.join(self.w, "verify.md")) as f:
            md = f.read()
        self.assertIn("## Link sentences", md)
        self.assertIn("1. 이번에는 출국을 봅시다.\n   - why a link: a transition", md)
        self.assertLess(md.index("## Facts"), md.index(S1))
        self.assertLess(md.index(S1), md.index("## Link sentences"))
        self.draft(sentences="x")
        self.assertEqual(self.check(), 1)
        os.remove(os.path.join(self.w, "verify.draft.json"))
        self.assertEqual(self.check(), 1)
        self.assertIn("verify.draft.json is missing", self.out)

    def test_s1_links_have_a_floor(self):
        good = self.draft()["sentences"]
        note = {"note": "a transition"}
        everything_link = [dict(x, kind="link", verdict=None, **note) for x in good]
        self.draft(sentences=everything_link)
        self.assertEqual(self.check(), 1)
        self.assertIn("is a sentence of claim", self.out)  # the claims map lists them
        cases = [
            ("공항에서는 3번 게이트로 갑니다.", "holds a number"),
            ("두 번 확인해 봅시다.", "holds a number"),
            ("다음은 三つ 이야기입니다.", "holds a number"),
            ("이제 카운터를 봅시다.", "uses 카운터 from the excerpts"),
            ("다음은 空港 이야기입니다.", "uses 空港 from the excerpts"),
        ]
        for text, why in cases:
            self.draft(sentences=good + [dict(text=text, kind="link", **note)])
            self.assertEqual(self.check(), 1, text)
            self.assertIn(why, self.out)
        self.draft(sentences=good + [{"text": "이번에는 출국을 봅시다.", "kind": "link"}])
        self.assertEqual(self.check(), 1)
        self.assertIn("needs a note", self.out)
        many = good + [dict(text="이제 넘어가 볼게요 %s." % w, kind="link", **note) for w in ("가", "나", "다")]
        self.draft(sentences=many)  # 6 judged: at most max(2, 25 %) = 2 links
        self.assertEqual(self.check(), 1)
        self.assertIn("3 link sentences — at most 2", self.out)
        self.draft(sentences=many[:-1])
        self.assertEqual(self.check(), 0, self.out)

    def test_s1_number_words(self):
        from stdo.claims import linkrule
        for t in ("3번 게이트", "３번", "三つ", "two gates", "두 번", "세 가지", "삼십 명", "오백 명", "삼 년 전", "하나 더",
                  # T2
                  "열두 개", "서른 살", "마흔 개", "스물두 명", "수백 명", "몇십 년", "첫 번째", "첫째", "세 번째",
                  "절반이 넘습니다", "반 년 동안", "dozens of gates", "the first gate", "みっつ", "ひとつ"):
            self.assertTrue(linkrule.has_number(t), t)
        for t in ("이번에는 출국을 봅시다.", "사이좋게", "하나씩 봅시다", "someone", "이제 넘어가 볼게요", "반갑습니다",
                  "그래서 다음으로 넘어가 보겠습니다."):
            self.assertFalse(linkrule.has_number(t), t)

    def test_t1_terms_are_noun_like(self):
        from stdo.claims import linkrule
        ex = ["공항에서는 탑승권을 받아야 합니다. 그래서 일본어로 「搭乗券」이라고 말합니다.",
              "하지만 출국 심사는 간단하게 끝납니다."]
        self.assertEqual(linkrule.terms(ex), {"탑승권", "일본어", "搭乗券"})
        # stacked particles, function words (also once their particles are gone)
        self.assertEqual(linkrule.terms(["여러분, 탑승권까지는 챙기세요. 마지막으로 출국장입니다."]), {"탑승권"})
        cm = {"claims": {cid(ex[0]): {"excerpt": ex[0], "sentences": ["공항에서는 탑승권을 꼭 받아야 합니다."]},
                         cid(ex[1]): {"excerpt": ex[1], "sentences": ["출국 심사는 간단하게 끝납니다."]}},
              "excerpts": ex}
        transcript = [  # (narration, the label it must be allowed to have)
            ("안녕하세요, 오늘은 공항에서 쓰는 말을 알아봅니다.", "link"),
            ("공항에서는 탑승권을 꼭 받아야 합니다.", "fact"),
            ("그래서 다음으로 넘어가 보겠습니다.", "link"),
            ("일본어로는 이걸 뭐라고 할까요?", "fact"),  # 일본어: a term of the excerpts
            ("출국 심사는 간단하게 끝납니다.", "fact"),
            ("그럼 이제 정리해 볼까요?", "link"),
        ]
        copy = N.Text(" ".join(ex))
        sentences = []
        for text, kind in transcript:
            if kind == "link":
                sentences.append({"text": text, "kind": "link", "note": "a transition"})
            else:
                c = [k for k, v in cm["claims"].items() if text in v["sentences"]]
                sentences.append({"text": text, "kind": "fact", "verdict": "supported", "claims": c or [cid(ex[0])],
                                  "excerpts": [cm["claims"][(c or [cid(ex[0])])[0]]["excerpt"]]})
        sentences[3]["kind"] = "link"  # the question about 일본어 as a link: refused
        sentences[3]["note"] = "a question"
        problems = ccheck.draft_problems({"sentences": sentences}, cm, copy, [], [])
        self.assertEqual([p for p in problems if "must be a fact" in p], ["sentence 4 uses 일본어 from the excerpts — it "
                                                                          "must be a fact"])
        sentences[3] = {"text": transcript[3][0], "kind": "link", "note": "x"}
        transcript_only_links = [dict(s) for s in sentences if s["kind"] == "link"]
        self.assertEqual([p for p in ccheck.draft_problems({"sentences": [transcript_only_links[0],
                                                                          transcript_only_links[1]]}, cm, copy, [], [])
                          if "must be a fact" in p], [])  # the transitions stay links

    def test_loop_three_times_holds(self):
        self.draft(sentences=[])
        for n in (1, 2):
            self.assertEqual(self.check(), 1)
            self.assertEqual(self.state("loop", "v1", "verify"), 0, self.err)
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.state("loop", "v1", "verify"), 4)
        self.assertEqual(store.read_state(self.vdir)["langs"]["ko"]["held"]["state"], "stagnation")

    def test_entry_writes_only_from_the_script(self):
        r = subprocess.run([sys.executable, "-B", "-c", "import sys; sys.path.insert(0, %r); from stdo.claims import "
                            "cli; cli._atomic(%r, 'x')" % (helpers.SCRIPTS, os.path.join(self.w, "verify.json"))],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("entry scripts", r.stderr)


class RealLint(StudioTestCase):
    def test_max_duration_with_real_s2v(self):
        """--full: real s2v lint exits 0 with the length warning; Studio's judgement fails it (§7.5)."""
        path = helpers.s2v_path(self)
        repo = helpers.make_repo(self.tmp)
        script = os.path.join(repo, "studio", "videos", "v1", "script.ko.md")
        os.makedirs(os.path.dirname(script))
        with open(script, "w") as f:
            f.write("---\ntitle: 공항 단어\nlang: ko\ncast:\n  narrator: { voice: \"qwen:Sohee\", style: \"차분하게\" }\n"
                    "outputs:\n  youtube: { aspect: \"16:9\", maxDuration: 1 }\n---\n\n# 시작 {#intro}\n\n"
                    "narrator: 안녕하세요. 오늘은 공항에서 쓰는 단어를 천천히 배워 볼게요. 체크인 카운터부터 시작합니다.\n")
        r = s2vlint.run(path, script, "lint", env=helpers.s2v_env(os.path.join(self.tmp, "s2v")),
                        fail_unread=schema.STAGE_CHECKS["script"]["fail_unread"])
        self.assertEqual(r.code, 0, r.stderr_tail)
        self.assertIn("max-duration", [d["code"] for d in r.failures])
        self.assertFalse(r.passed)


# ---------------------------------------------------------------- gate ①

class GateOne(ApproveCase):
    def test_verify_json_changed_after_shown_needs_showing_again(self):
        for st in ("script", "verify"):
            self.assertEqual(self.cli("stage-done", "v1", st), 0, self.last_err)
        w = os.path.join(self.vdir, "work", "ko")
        with open(os.path.join(w, "verify.json"), "w") as f:
            f.write('{"sentences": []}\n')
        with open(os.path.join(w, "verify.md"), "w") as f:
            f.write("# Verify\n")
        h = self.show("1")
        with open(os.path.join(w, "verify.json"), "w") as f:
            f.write('{"sentences": [1]}\n')  # only verify.json: verify.md is the same
        self.assertNotEqual(self.approve("1", h), 0)
        self.assertIn("shown", self.last_err)
        h2 = self.show("1")
        self.assertNotEqual(h, h2)
        self.assertEqual(self.approve("1", h2), 0, self.last_err)

    def test_artifacts(self):
        from stdo.state import shown
        ctx = {"vdir": self.vdir, "repo": self.repo}
        a = shown.artifacts(ctx, self.state(), "ko", "1", shown.ONE)
        self.assertEqual(sorted(a), ["verify_json", "verify_md"])


# ---------------------------------------------------------------- the external auditor (J46)

class Auditor(JudgeCase):
    def hook(self, tool, ti, cwd=None):
        h = super().hook(tool, ti, cwd)
        h.update({"agent_id": "a1", "agent_type": getattr(self, "agent", "std-auditor")})
        return h

    def test_writes_denied(self):
        for tool, ti in (("Write", {"file_path": os.path.join(self.repo, "a.txt"), "content": "x"}),
                         ("Edit", {"file_path": os.path.join(self.repo, "a.txt"), "old_string": "a",
                                   "new_string": "b"}),
                         ("MultiEdit", {"file_path": os.path.join(self.repo, "a.txt"), "edits": []}),
                         ("NotebookEdit", {"notebook_path": os.path.join(self.repo, "n.ipynb"), "new_source": "x"}),
                         ("mcp__fs__write_file", {"path": os.path.join(self.repo, "a.txt"), "content": "x"}),
                         ("mcp__notes__search", {"query": "x"})):
            d = self.decide(tool, ti)
            self.assertIsNotNone(d, tool)
            self.assertEqual(d.rule, "G-AUDIT", tool)
        self.agent = "studio-plugin:std-auditor"
        self.assertEqual(self.decide("Write", {"file_path": os.path.join(self.repo, "a.txt"), "content": "x"}).rule,
                         "G-AUDIT")
        self.agent = "std-writer"  # other roles: the usual rules (a plain file outside Studio's paths)
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(self.repo, "a.txt"), "content": "x"}))

    def test_bash_reads_only(self):
        for cmd in ("cat a.txt", "grep -n x src/a.ts", "git log --oneline -3", "git diff HEAD", "ls -la studio",
                    "wc -l a.txt 2>/dev/null", "find . -name '*.md'", "shasum a.txt", "cd src && cat a.ts",
                    "sort a.txt", "sort -n -r a.txt", "uniq -c a.txt", "rg -n x src", "GIT_PAGER=cat git log -1"):
            self.assertPass(cmd)
        for cmd in ("touch b.txt", "echo x > b.txt", "cat a.txt >> b.txt", "rm a.txt", "git commit -m x",
                    "git checkout -- a.txt", "find . -delete", "python3 -c 'print(1)'", "open a.txt",
                    "sed -i '' s/a/b/ a.txt", "xargs rm < a.txt", "git diff --output=x.patch",
                    "python3 .claude/studio/scripts/state.py next v", "cat a.txt | tee b.txt", "eval ls",
                    "git -c diff.external=x diff", "git diff --ext-diff", "git log -p --textconv",
                    # S3
                    "sort -o out.txt a.txt", "sort --output=out.txt a.txt", "sort -no out.txt a.txt",
                    "uniq a.txt out.txt", "uniq -c a.txt out.txt", "rg --pre /bin/sh x", "rg --pre=/bin/sh x",
                    "rg --pre-glob '*' --pre x x", "rg -z x", "GIT_EXTERNAL_DIFF=/bin/sh git diff",
                    "env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=diff.external GIT_CONFIG_VALUE_0=/bin/sh git diff",
                    "LESSOPEN='|sh -c id' less a.txt", "LESSCLOSE=x less a.txt"):
            self.assertDeny(cmd, "G-AUDIT")


# ---------------------------------------------------------------- R1: only committed writing is frozen

class CommittedSource(FlowCase):
    def test_uncommitted_source_refused(self):
        p = os.path.join(self.repo, "docs", "airport.md")
        with open(p, "a") as f:
            f.write("\n추가 문장.\n")
        self.assertEqual(self.state("record-source", "v1"), 3)
        self.assertIn("docs/airport.md: changed since the last commit", self.err)
        self.assertIn("Ask the person to commit", self.err)
        helpers.git(self.repo, "add", "docs/airport.md")  # staged is not committed either
        self.assertEqual(self.state("record-source", "v1"), 3)
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "more")
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)

    def test_uncommitted_image_refused(self):
        self.assertEqual(self.run_fn(src_cli.resolve_main, "v1"), 0, self.err)
        self.claims_md()
        self.assertEqual(self.run_fn(src_cli.scope_main, "v1"), 0, self.err)
        with open(os.path.join(self.repo, "docs", "img", "gate.png"), "ab") as f:
            f.write(b"\x00")
        self.assertEqual(self.state("record-source", "v1"), 3)
        self.assertIn("docs/img/gate.png: changed since the last commit", self.err)
        self.assertFalse([n for n in os.listdir(os.path.join(self.vdir, "work", "source")) if ".tmp." in n])

    def test_s4_hidden_changes(self):
        from stdo.state import flow
        p = os.path.join(self.repo, "docs", "airport.md")
        for flag in ("--skip-worktree", "--assume-unchanged"):
            helpers.git(self.repo, "update-index", flag, "docs/airport.md")
            with open(p, "a") as f:
                f.write("\n고친 문장.\n")
            self.assertEqual(self.state("record-source", "v1"), 3, flag)
            self.assertIn("skip-worktree or assume-unchanged", self.err)
            helpers.git(self.repo, "update-index", flag.replace("--", "--no-"), "docs/airport.md")
            helpers.git(self.repo, "checkout", "--", "docs/airport.md")
        # the blob comparison stands on its own: a diff that saw nothing still finds other bytes
        with open(p, "a") as f:
            f.write("x")
        real = flow._git

        def blind(repo, *args):
            return "" if args[:1] == ("diff",) else real(repo, *args)
        from unittest import mock
        with mock.patch.object(flow, "_git", blind):
            self.assertEqual(flow.uncommitted(self.repo, ["docs/airport.md"]),
                             [("docs/airport.md", "changed since the last commit")])
        helpers.git(self.repo, "checkout", "--", "docs/airport.md")
        self.assertEqual(flow.uncommitted(self.repo, ["docs/airport.md"]), [])

    def test_s5_commits_after_begin(self):
        st = store.read_state(self.vdir)
        self.assertEqual(st["source"]["begin_commit"], self._head())
        self.assertEqual(st["source"]["commits_since_begin"], [])
        with open(os.path.join(self.repo, "docs", "airport.md"), "a") as f:
            f.write("\n새 문장.\n")
        with open(os.path.join(self.repo, "docs", "other.md"), "w") as f:
            f.write("not the source\n")  # in the same commit: not in its diffstat
        helpers.git(self.repo, "add", "docs/other.md")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "edit the article")
        sha = self._head()
        with open(os.path.join(self.repo, "README.md"), "a") as f:
            f.write("x\n")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "unrelated")
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        st = store.read_state(self.vdir)
        self.assertEqual(st["source"]["commits_since_begin"],
                         [{"sha": sha, "subject": "edit the article", "stat": "+2 -0 docs/airport.md"}])
        from stdo.state import flow
        line = "원본이 begin 뒤에 커밋됨: %s edit the article (+2 -0 docs/airport.md)" % sha[:12]
        self.assertEqual(flow.source_commit_lines(st), [line])
        self.assertIn(line + " — put this line in the ① question", self.out)

    def _head(self):
        r = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True)
        return r.stdout.strip()

    def test_untracked_and_unborn(self):
        from stdo.state import flow
        with open(os.path.join(self.repo, "docs", "new.md"), "w") as f:
            f.write("x\n")
        self.assertEqual(flow.uncommitted(self.repo, ["docs/new.md", "docs/airport.md"]),
                         [("docs/new.md", "not committed (untracked)")])
        self.assertEqual(flow.uncommitted(self.repo, []), [])
        fresh = os.path.join(self.tmp, "fresh")
        os.makedirs(fresh)
        helpers.git(fresh, "init", "-q")
        self.assertEqual(flow.uncommitted(fresh, ["a.md"]), [("a.md", "no commit yet")])


# ---------------------------------------------------------------- R2 · R3

class SourceFollowUps(StudioTestCase):
    def floors(self, text):
        marks = list(assets.CREDIT_MARKS)
        cfg = {"visibility": {"public": ["**"]}}
        found = refs.extract(text, (), credit=lambda t: assets.has_mark(t, marks) is not None)
        return [assets.floor(r, "public/x.png", cfg, marks)[0] for r in found]

    def test_r2_short_credit_a_blank_line_above(self):
        self.assertEqual(self.floors("© X\n\n![a](/a.png)\n"), ["third-party"])
        self.assertEqual(self.floors("출처: 공항공사\n\n![a](/a.png)\n"), ["third-party"])
        self.assertEqual(self.floors("Some text\n\n![a](/a.png)\n"), ["public"])  # not credit-like
        self.assertEqual(self.floors("%s ©\n\n![a](/a.png)\n" % ("x" * 90)), ["public"])  # not short
        self.assertEqual(self.floors("© X\n\n\n![a](/a.png)\n"), ["public"])  # two blank lines
        self.assertEqual(self.floors("![b](/b.png)\n\n![a](/a.png)\n"), ["public", "public"])
        # right under an earlier image, the credit is that image's caption, not the next one's
        self.assertEqual(self.floors("![b](/b.png)\n© X\n\n![a](/a.png)\n"), ["third-party", "public"])
        self.assertEqual(self.floors("![b](/b.png)\n\n© X\n\n![a](/a.png)\n"), ["third-party", "third-party"])
        self.assertEqual(refs.extract("© X\n\n![a](/a.png)\n")[0].context, "")  # without a credit test: as before

    def test_r3_unclosed_comment(self):
        text = "![a](/a.png)\n<!-- draft\n![b](/b.png)\nplain\n<img src=\"/c.png\">\n"
        rs, unparsed, hidden = refs.extract_all(text)
        self.assertEqual([r.src for r in rs], ["/a.png"])
        self.assertEqual(unparsed, [])
        self.assertEqual(hidden, {"from": 2, "lines": [3, 5]})
        self.assertIsNone(refs.extract_all("<!-- closed\n![b](/b.png)\n-->\n")[2])
        self.assertEqual(refs.extract_all("x <!-- open\nnothing\n")[2], {"from": 1, "lines": []})


class SourceFollowUpsCli(FlowCase):
    def test_r2_through_resolve(self):
        with open(os.path.join(self.repo, "docs", "airport.md"), "a") as f:
            f.write("\n사진 출처: 공항공사\n\n![terminal](img/gate.png)\n")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "photo")
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        self.assertEqual(self.run_fn(src_cli.resolve_main, "v1"), 0, self.err)
        imgs = assets.read(self.vdir)["images"]
        # the earlier image's window below reaches the credit too (stricter only); the new one now gets it from above
        self.assertEqual([(i["alt"], i["floor"]) for i in imgs], [("gate", "third-party"), ("terminal", "third-party")])

    def test_r3_reported(self):
        with open(os.path.join(self.repo, "docs", "airport.md"), "a") as f:
            f.write("\n<!-- unfinished\n![later](img/gate.png)\n")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "draft")
        self.assertEqual(self.state("record-source", "v1"), 0, self.err)
        self.assertEqual(self.run_fn(src_cli.resolve_main, "v1"), 0, self.err)
        n = ARTICLE.count("\n") + 2
        self.assertIn("1 image-like line(s) hidden by an HTML comment from line %d (it never closes): lines %d"
                      % (n, n + 1), self.out)
        self.assertEqual(assets.read(self.vdir)["unparsed"]["hidden_by_comment"], {"from": n, "lines": [n + 1]})


# ---------------------------------------------------------------- the guard protects verify.md

class GuardM1e(JudgeCase):
    def test_verify_outputs_protected(self):
        for rel in ("studio/videos/v/work/ko/verify.md", "studio/videos/v/work/ko/verify.json"):
            d = self.decide("Write", {"file_path": os.path.join(self.repo, rel), "content": "x"})
            self.assertEqual(d.rule, "G-PROT", rel)
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(self.repo,
                                                                          "studio/videos/v/work/ko/verify.draft.json"),
                                                "content": "{}"}))
        self.assertPass("python3 .claude/studio/scripts/check_claims.py v --narration")


class GateOneLines(JudgeCase):
    """S5: the ① question shows each commit to the source after begin, or the guard finds no answer."""
    H = "3f2a9c0d1e4b"

    def setUp(self):
        super().setUp()
        import transcripts as TR
        self.TR = TR
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        self.tpath = TR.transcript_path(self.env)
        st = F.state()
        st["video"] = "v"
        st["source"]["commits_since_begin"] = [{"sha": "ab" * 20, "subject": "edit the article",
                                                 "stat": "+1 -1 docs/a.md, binary docs/img/a.png"}]
        d = os.path.join(self.repo, "studio", "videos", "v", "work")
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump(st, f)
        self.line = "원본이 begin 뒤에 커밋됨: %s edit the article (+1 -1 docs/a.md, binary docs/img/a.png)" % ("ab" * 6)

    def run_hook(self, qtext, cmd):
        label = "승인 v %s" % self.H
        t = self.TR.approval_turn(self.TR.T(), label, qtext=qtext)
        t.write(self.tpath)
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": t.prompt}
        from stdo.guard import judge
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def test_commit_lines_in_the_question(self):
        cmd = "python3 .claude/studio/scripts/state.py approve v 1 --expect %s" % self.H
        base = "[v] ① 대본 — studio/videos/v/script.ko.md · hash %s" % self.H
        deny, _ctx = self.run_hook(base, cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn(self.line, deny.message())
        deny, _ctx = self.run_hook(base + "\n" + self.line.split(" (")[0], cmd)  # T3: the diffstat is required too
        self.assertEqual(deny.rule, "G-EVIDENCE")
        deny, ctx = self.run_hook(base + "\n" + self.line, cmd)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)


class GuardSparse(JudgeCase):
    def test_s4_sparse_checkout_denied(self):
        for cmd in ("git sparse-checkout set docs", "git sparse-checkout init --cone", "git sparse-checkout add x"):
            self.assertDeny(cmd, "G-PLUMB")
        self.assertPass("git sparse-checkout list")
        self.assertIn("ask the person", self.assertDeny("git sparse-checkout set docs").message())  # T4
