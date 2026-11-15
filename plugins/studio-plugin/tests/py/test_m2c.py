"""Vertical and square outputs (m2-plan §4): outputs shared by name between the brief's platforms, one shape per
output (conflicting aspects refused), a platform's length limit below the format's lower bound refused for the kind
(every output plays the whole script), an output a platform does not accept refused; the script lines for 9:16
(`subtitles: word`, the platform's layout and shot, maxDuration the smallest limit, the targetDuration range under it);
the script check's aspect and maxDuration; the look rules for 9:16 and 1:1 (`shorts`, no presenter without art); and,
with real s2v (--full, mock voice), the measurement behind `shorts`: without a character a vertical `shorts` output
draws exactly as `fullscreen` with word subtitles."""

import hashlib
import json
import os
import shutil

import helpers
import state_fixtures as F
from helpers import StudioTestCase
from stdo import look
from stdo.claims import check as ccheck
from stdo.setup import platform as setup_platform
from stdo.state import scriptlines, store
from test_m1e import E1, E2, FlowCase, cid

SNS = {"min": 20, "max": 90}
YOUTUBE = {"min": 180, "max": 480}


def platform_file(name, outputs, audience="public"):
    lines = ["---", "platform: %s" % name, "audience: %s" % audience, 'checked: ""', "outputs:"]
    for o in outputs:
        lines.append("  - name: %s" % o["name"])
        lines.append('    aspect: "%s"' % o["aspect"])
        lines.append("    max_duration: %s" % ("null" if o.get("max") is None else o["max"]))
        for k in ("layout", "shot"):
            if o.get(k):
                lines.append("    %s: %s" % (k, o[k]))
    lines += ["---", "# %s" % name, ""]
    return "\n".join(lines)


def write_platform(repo, name, outputs, audience="public"):
    d = os.path.join(repo, ".claude", "studio", "platforms")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "%s.md" % name), "w", encoding="utf-8") as f:
        f.write(platform_file(name, outputs, audience))


def shipped_shorts(repo):
    with open(os.path.join(helpers.PLUGIN, "skills", "std", "templates", "platforms", "youtube-shorts.md")) as f:
        text = f.read().replace("{{CHECKED_DATE}}", "")
    with open(os.path.join(repo, ".claude", "studio", "platforms", "youtube-shorts.md"), "w") as f:
        f.write(text)


WIDE = {"name": "youtube", "aspect": "16:9"}
SHORTS = {"name": "shorts", "aspect": "9:16", "max": 180, "shot": "full"}
REELS = {"name": "reels", "aspect": "9:16", "max": 90}


# ---------------------------------------------------------------- the output plan (record-brief, next, the check)

class OutputPlan(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp, "repo")
        write_platform(self.repo, "youtube", [WIDE])
        write_platform(self.repo, "youtube-shorts", [SHORTS])
        write_platform(self.repo, "reels", [REELS])

    def plan(self, platforms, outputs, length=SNS):
        return scriptlines.output_plan(self.repo, platforms, outputs, length)

    def refused(self, platforms, outputs, length=SNS):
        with self.assertRaises(scriptlines.PlanProblem) as cm:
            self.plan(platforms, outputs, length)
        return str(cm.exception)

    def test_shared_output_one_render(self):
        """Shorts and an added vertical platform share one 9:16 output; its maxDuration is the smallest limit."""
        p = self.plan({"youtube-shorts": ["shorts"], "reels": ["shorts"]}, ["shorts"])
        self.assertEqual(list(p), ["shorts"])
        self.assertEqual((p["shorts"]["aspect"], p["shorts"]["shot"], p["shorts"]["max"]), ("9:16", "full", 90))
        self.assertEqual(sorted(p["shorts"]["limits"]), [(90, "reels"), (180, "youtube-shorts")])
        p = self.plan({"youtube-shorts": ["shorts"]}, ["shorts"], {"min": 20, "max": 60})
        self.assertEqual(p["shorts"]["max"], 60)  # the format's bound when it is the smaller
        p = self.plan({"youtube": ["youtube"]}, ["youtube"], YOUTUBE)  # no platform limit: the format's
        self.assertEqual((p["youtube"]["aspect"], p["youtube"]["layout"], p["youtube"]["max"]), ("16:9", None, 480))

    def test_conflicting_aspects_under_one_name(self):
        write_platform(self.repo, "square", [{"name": "shorts", "aspect": "1:1", "max": 60}])
        why = self.refused({"youtube-shorts": ["shorts"], "square": ["shorts"]}, ["shorts"])
        self.assertIn("output shorts has two aspects", why)
        self.assertIn("1:1 in platforms/square.md", why)
        self.assertIn("9:16 in platforms/youtube-shorts.md", why)
        write_platform(self.repo, "clips", [{"name": "shorts", "aspect": "9:16", "max": 60, "layout": "fullscreen"}])
        write_platform(self.repo, "tall", [{"name": "shorts", "aspect": "9:16", "max": 60, "layout": "shorts"}])
        self.assertIn("two layouts", self.refused({"clips": ["shorts"], "tall": ["shorts"]}, ["shorts"]))
        # a name declared differently by a platform outside the brief does not matter
        self.assertEqual(self.plan({"youtube-shorts": ["shorts"]}, ["shorts"])["shorts"]["aspect"], "9:16")

    def test_min_duration(self):
        """Decided Q2: no cut-downs — a platform whose limit is below the kind's minimum is refused for that kind."""
        write_platform(self.repo, "stories", [{"name": "shorts", "aspect": "9:16", "max": 15}])
        why = self.refused({"youtube-shorts": ["shorts"], "stories": ["shorts"]}, ["shorts"])
        self.assertIn("platform stories allows at most 15 s for output shorts, below the format's lower bound 20 s",
                      why)
        self.assertIn("plays the whole video", why)
        # Shorts (180 s) cannot carry a youtube video (180–480 s): no targetDuration s2v can hold fits under it
        why = self.refused({"youtube": ["youtube"], "youtube-shorts": ["shorts"]}, ["youtube", "shorts"], YOUTUBE)
        self.assertIn("platform youtube-shorts allows at most 180 s", why)
        # an sns video (20–90 s) takes it
        self.assertEqual(self.plan({"youtube-shorts": ["shorts"]}, ["shorts"])["shorts"]["max"], 90)

    def test_aspect_not_accepted(self):
        why = self.refused({"youtube": ["shorts"], "youtube-shorts": ["shorts"]}, ["shorts"])
        self.assertIn("platform youtube does not accept output shorts (9:16): platforms/youtube.md declares "
                      "youtube (16:9)", why)
        # another name for the same shape is accepted: reels uses Shorts' output and keeps its own limit
        p = self.plan({"reels": ["shorts"], "youtube-shorts": ["shorts"]}, ["shorts"])
        self.assertIn((90, "reels"), p["shorts"]["limits"])

    def test_declared_by_none_and_unreadable_files(self):
        self.assertIn("output vertical is declared by none of the platforms the brief maps to it",
                      self.refused({"youtube-shorts": ["vertical"]}, ["vertical"]))
        with open(os.path.join(self.repo, ".claude", "studio", "platforms", "bare.md"), "w") as f:
            f.write('---\nplatform: bare\naudience: public\nchecked: ""\n---\n')
        why = self.refused({"bare": ["shorts"]}, ["shorts"])
        self.assertIn("platforms/bare.md declares no outputs", why)
        self.assertIn("/std platform refresh bare", why)
        write_platform(self.repo, "odd", [{"name": "shorts", "aspect": "4:3"}])
        self.assertIn("aspect must be one of", self.refused({"odd": ["shorts"]}, ["shorts"]))
        write_platform(self.repo, "odd", [{"name": "shorts", "aspect": "9:16", "shot": "head"}])
        self.assertIn("shot must be full", self.refused({"odd": ["shorts"]}, ["shorts"]))
        self.assertIn("cannot read", self.refused({"missing": ["shorts"]}, ["shorts"]))

    def test_only_the_mapped_declarations_count(self):
        """A platform's declaration of a name counts only when the brief maps that platform to the output."""
        write_platform(self.repo, "weird", [{"name": "youtube", "aspect": "1:1"}, {"name": "sq", "aspect": "1:1"}])
        p = self.plan({"youtube": ["youtube"], "weird": ["sq"]}, ["youtube", "sq"], YOUTUBE)
        self.assertEqual((p["youtube"]["aspect"], p["sq"]["aspect"]), ("16:9", "1:1"))

    def test_the_most_permissive_declaration_of_the_aspect(self):
        """A platform using an output it does not name takes its most permissive declaration of that aspect (and
        that declaration's layout and shot)."""
        write_platform(self.repo, "insta", [{"name": "reels", "aspect": "9:16", "max": 90},
                                            {"name": "stories", "aspect": "9:16", "max": 60, "layout": "fullscreen"}])
        p = self.plan({"youtube-shorts": ["shorts"], "insta": ["shorts"]}, ["shorts"])
        self.assertIn((90, "insta"), p["shorts"]["limits"])
        self.assertEqual((p["shorts"]["max"], p["shorts"]["layout"]), (90, None))
        write_platform(self.repo, "insta", [{"name": "reels", "aspect": "9:16", "max": 90, "layout": "fullscreen"}])
        self.assertEqual(self.plan({"youtube-shorts": ["shorts"], "insta": ["shorts"]}, ["shorts"])["shorts"]["layout"],
                         "fullscreen")

    def test_a_narrow_format_is_named_not_the_platform(self):
        write_platform(self.repo, "clip", [{"name": "shorts", "aspect": "9:16", "max": 110}])
        why = self.refused({"clip": ["shorts"]}, ["shorts"], {"min": 100, "max": 120})
        self.assertIn("the format's length range 100–120 s is itself too narrow", why)
        why = self.refused({"clip": ["shorts"]}, ["shorts"], {"min": 100, "max": 300})
        self.assertIn("platform clip allows at most 110 s for output shorts, too close", why)

    def test_an_output_name_twice_in_one_file(self):
        write_platform(self.repo, "twice", [{"name": "shorts", "aspect": "9:16"}, {"name": "shorts", "aspect": "1:1"}])
        self.assertIn("unique usable name", self.refused({"twice": ["shorts"]}, ["shorts"]))

    def test_the_shapes_are_s2vs(self):
        """scriptlines (the repository copy) keeps its own lists; setup/platform.py checks drafts with the same."""
        self.assertEqual(scriptlines.ASPECTS, setup_platform.ASPECTS)
        self.assertEqual(scriptlines.LAYOUTS, setup_platform.LAYOUTS)

    def test_the_shipped_files_plan(self):
        for n in ("youtube", "youtube-shorts", "internal"):
            with open(os.path.join(helpers.PLUGIN, "skills", "std", "templates", "platforms", "%s.md" % n)) as f:
                text = f.read().replace("{{CHECKED_DATE}}", "")
            with open(os.path.join(self.repo, ".claude", "studio", "platforms", "%s.md" % n), "w") as f:
                f.write(text)
        self.assertEqual(self.plan({"youtube-shorts": ["shorts"]}, ["shorts"])["shorts"]["shot"], "full")
        self.assertEqual(self.plan({"internal": ["internal"]}, ["internal"], {"min": 60, "max": 480})["internal"],
                         {"aspect": "16:9", "layout": None, "shot": None, "max": 480, "limits": []})


# ---------------------------------------------------------------- record-brief and the script lines

class VerticalBrief(FlowCase):
    def setUp(self):
        super().setUp()
        self.to_brief()  # a youtube video (format 1–600 s) with the shipped youtube.md
        shipped_shorts(self.repo)
        write_platform(self.repo, "reels", [REELS])
        helpers.git(self.repo, "add", "-A", ".claude/studio/platforms")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "platforms")

    def record(self, outputs, platforms):
        with open(os.path.join(self.vdir, "work", "brief.json"), "w") as f:
            json.dump({"claims": [cid(E1), cid(E2)], "roles": [{"name": "narrator"}], "outputs": outputs,
                       "platforms": platforms}, f)
        return self.state("record-brief", "v1", "--from", "work/brief.json")

    def test_shared_output_and_the_script_lines(self):
        self.assertEqual(self.record(["youtube", "shorts"], {"youtube": ["youtube"], "youtube-shorts": ["shorts"],
                                                             "reels": ["shorts"]}), 0, self.err)
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 0, self.err)
        for line in ("  outputs:", '    youtube: { aspect: "16:9", maxDuration: 600 }',
                     '    shorts: { aspect: "9:16", subtitles: word, shot: full, maxDuration: 90 }',
                     "  targetDuration: <2–78, from the brief's estimate>"):
            self.assertIn(line + "\n", self.out)
        self.assertEqual(self.state("next", "v1", "--enter", "script", "--json"), 0, self.err)
        fm = json.loads(self.out)["frontmatter"]
        self.assertIn('  shorts: { aspect: "9:16", subtitles: word, shot: full, maxDuration: 90 }', fm)

    def test_refusals_record_nothing(self):
        before = store.read_state(self.vdir)["brief"]
        self.assertEqual(self.record(["shorts"], {"youtube": ["shorts"], "youtube-shorts": ["shorts"]}), 1)
        self.assertIn("platform youtube does not accept output shorts (9:16)", self.err)
        write_platform(self.repo, "square", [{"name": "shorts", "aspect": "1:1", "max": 60}])
        self.assertEqual(self.record(["shorts"], {"square": ["shorts"], "youtube-shorts": ["shorts"]}), 1)
        self.assertIn("output shorts has two aspects", self.err)
        F.write_format(self.repo, length=(120, 600), commit=False)
        self.assertEqual(self.record(["shorts"], {"youtube-shorts": ["shorts"], "reels": ["shorts"]}), 1)
        self.assertIn("platform reels allows at most 90 s for output shorts, below the format's lower bound 120 s",
                      self.err)
        self.assertEqual(store.read_state(self.vdir)["brief"], before)

    def test_a_platform_layout_needing_art_is_not_printed(self):
        """presenter/dialogue need character art: the script lines leave them to board's --look."""
        write_platform(self.repo, "tall", [{"name": "shorts", "aspect": "9:16", "max": 60, "layout": "presenter"}])
        write_platform(self.repo, "flat", [{"name": "shorts", "aspect": "9:16", "max": 60, "layout": "fullscreen"}])
        self.assertEqual(self.record(["shorts"], {"tall": ["shorts"]}), 0, self.err)
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 0, self.err)
        self.assertIn('shorts: { aspect: "9:16", subtitles: word, maxDuration: 60 }', self.out)
        self.assertEqual(self.record(["shorts"], {"flat": ["shorts"]}), 0, self.err)
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 0, self.err)
        self.assertIn('shorts: { aspect: "9:16", layout: fullscreen, subtitles: word, maxDuration: 60 }', self.out)

    def test_platform_changed_after_the_brief(self):
        self.assertEqual(self.record(["shorts"], {"youtube-shorts": ["shorts"]}), 0, self.err)
        write_platform(self.repo, "youtube-shorts", [{"name": "shorts", "aspect": "1:1", "max": 60},
                                                     {"name": "other", "aspect": "9:16"}])
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 0, self.err)
        self.assertIn('shorts: { aspect: "1:1", maxDuration: 60 }', self.out)  # the file as it is now
        os.remove(os.path.join(self.repo, ".claude", "studio", "platforms", "youtube-shorts.md"))
        self.assertEqual(self.state("next", "v1", "--enter", "script"), 1)
        self.assertIn("cannot read .claude/studio/platforms/youtube-shorts.md", self.err)


# ---------------------------------------------------------------- the script check's lengths and aspects

SCRIPT_FM = '---\ntitle: T\nlang: ko\noutputs:\n  youtube: { aspect: "16:9", maxDuration: %s }\n' \
            '  shorts: { aspect: "%s", subtitles: word, maxDuration: %s }\ntargetDuration: %s\n---\n# A {#a}\n'


class ScriptLengths(StudioTestCase):
    crit = {"length_seconds": {"min": 20, "max": 600}, "chars_per_sec": {"ko": 5.5}}
    sentences = [{"text": "가" * 220}]  # 40 s

    def problems(self, ymax, smax, target, maxes):
        text = SCRIPT_FM % (ymax, "9:16", smax, target)
        return ccheck.length_problems(text, ["youtube", "shorts"], self.crit, self.sentences, "ko", "f.md",
                                      maxes=maxes)

    def test_platform_limit(self):
        maxes = {"youtube": 600, "shorts": 90}
        self.assertEqual(self.problems(600, 90, 40, maxes), [])
        p = self.problems(600, 600, 40, maxes)
        self.assertEqual(p, ["outputs.shorts.maxDuration must be the smallest platform limit 90 (it is 600.0)"])
        p = self.problems(600, 90, 300, maxes)  # in the format's range, over the Shorts output's
        self.assertEqual(len(p), 1)
        self.assertIn("targetDuration must be a number within 24–78 s", p[0])
        # no limits: the format's bound, as before
        self.assertEqual(self.problems(600, 600, 300, None), [])
        # the shapes are unknown (a platform file problem is reported instead): no maxDuration verdict
        text = SCRIPT_FM % (1, "9:16", 2, 40)
        self.assertEqual(ccheck.length_problems(text, ["youtube", "shorts"], self.crit, self.sentences, "ko", "f.md",
                                                maxes={}, check_max=False), [])


class ScriptAspect(FlowCase):
    def test_aspect_must_be_the_briefs(self):
        self.to_script()
        self.assertEqual(self.check("--narration"), 0, self.out)
        p = os.path.join(self.vdir, "script.ko.md")
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(text.replace("youtube: { maxDuration", 'youtube: { aspect: "9:16", maxDuration', 1))
        self.assertEqual(self.check("--narration"), 1)
        self.assertIn('outputs.youtube.aspect must be "16:9" (the brief\'s platform files; it is 9:16)', self.out)


# ---------------------------------------------------------------- the look rules for 9:16 and 1:1

class VerticalLook(StudioTestCase):
    def test_layout_rule(self):
        no, art = (set(["narrator"]), set()), (set(["narrator"]), set(["narrator"]))
        for aspect in ("9:16", "1:1"):
            for lay in ("shorts", "fullscreen"):
                self.assertIsNone(look.layout_problem(lay, *no, "board", aspect, "shorts"))
            for lay in ("presenter", "dialogue", None):
                why = look.layout_problem(lay, *no, "board", aspect, "shorts")
                self.assertIn("which shows no one without character art — use shorts", why)
                self.assertIsNone(look.layout_problem(lay, *art, "board", aspect, "shorts"))
            self.assertIsNone(look.layout_problem(None, *no, "script", aspect, "shorts"))  # board sets it
        # 16:9 unchanged: fullscreen
        self.assertIn("use fullscreen", look.layout_problem("presenter", *no, "board", "16:9", "youtube"))
        self.assertIsNone(look.layout_problem("shorts", *no, "board", "16:9", "youtube"))

    def ins(self, aspect, layout, art=False):
        return {"outputs": [{"name": "o", "aspect": aspect, "layout": layout}],
                "voices": [{"cast": "narrator"}],
                "characters": [{"cast": "narrator", "source": "classic"}] if art else []}

    def layout_line(self, ins):
        brand = {"accent_color": "#112233"}
        return dict(look.required(None, brand, ins, "o")).get("outputs.o.layout")

    def test_required(self):
        self.assertEqual(self.layout_line(self.ins("9:16", "presenter")), "shorts")
        self.assertEqual(self.layout_line(self.ins("1:1", "dialogue")), "shorts")
        self.assertIsNone(self.layout_line(self.ins("9:16", "fullscreen")))  # a platform's choice: no line
        self.assertIsNone(self.layout_line(self.ins("9:16", "shorts")))
        self.assertIsNone(self.layout_line(self.ins("9:16", "presenter", art=True)))
        self.assertEqual(self.layout_line(self.ins("16:9", "presenter")), "fullscreen")  # unchanged
        self.assertEqual(self.layout_line(self.ins("16:9", "presenter", art=True)), "presenter")
        self.assertIsNone(self.layout_line(self.ins("16:9", "shorts")))


# ---------------------------------------------------------------- --full: the measurement behind `shorts`

MEASURE = """---
title: 세로 측정
lang: ko
cast:
  narrator: { voice: "supertonic:F1" }
outputs:
  s: { aspect: "9:16", layout: shorts }
  fw: { aspect: "9:16", layout: fullscreen, subtitles: word }
  f: { aspect: "9:16", layout: fullscreen }
---

# 시작 {#intro}

::title[세로 영상 측정]

안녕하세요. 세로 영상에서 레이아웃을 비교합니다.

# 두 번째 {#next}

::title[둘째 장면]

오른쪽 위의 설정 버튼을 누르면 새 프로젝트를 만들 수 있습니다.
"""


class VerticalSnapshot(StudioTestCase):
    """Real s2v, mock voice (S2V_TTS=mock, fake uv): the 9:16 layout without a character. No network: s2v's fonts come
    from the person's cache (verified against s2v's fonts.lock.json) — a run that would download them fails here."""

    def fonts(self, s2v):
        with open(os.path.join(s2v, "fonts.lock.json")) as f:
            lock = json.load(f)["fonts"]
        real = os.environ.get("STUDIO_TEST_REAL_HOME") or os.path.expanduser("~")
        src = os.path.join(real, ".cache", "script2video", "fonts")
        dst = os.path.join(self.tmp, "fonts")
        os.makedirs(dst)
        for name, spec in sorted(lock.items()):
            p = os.path.join(src, name)
            try:
                with open(p, "rb") as f:
                    ok = hashlib.sha256(f.read()).hexdigest() == spec["sha256"]
            except OSError:
                ok = False
            if not ok:
                self.fail("s2v's font %s is not in %s: render once with s2v outside the tests (it downloads the "
                          "fonts); this test makes no network call" % (name, src))
            shutil.copyfile(p, os.path.join(dst, name))
        return dst

    def test_shorts_is_fullscreen_with_word_subtitles(self):
        s2v = helpers.s2v_path(self)
        self.s2v_environ["S2V_FONTS_DIR"] = self.fonts(s2v)
        v = os.path.join(self.tmp, "v")
        os.makedirs(v)
        with open(os.path.join(v, "script.ko.md"), "w", encoding="utf-8") as f:
            f.write(MEASURE)
        out = os.path.join(self.tmp, "out")
        shas = {}
        for o in ("s", "fw", "f"):
            r = helpers.run_s2v(self, ["snapshot", "script.ko.md", "--output", o, "--out-dir", out], cwd=v,
                                timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            self.assertNotIn("downloading", r.stderr)
            with open(os.path.join(out, "%s.ko.snapshot.png" % o), "rb") as f:
                shas[o] = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(shas["s"], shas["fw"])  # shorts = fullscreen + word subtitles
        self.assertNotEqual(shas["s"], shas["f"])  # the subtitles are the difference
