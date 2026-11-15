"""Platform rules v2 and `/std platform` (m2-plan §3): the rules block v1 and v2 (`title_max: null`, characters or
bytes, `chapters`, `link`), the frontmatter (`audience`, `outputs`, `sources`), validate_copy following the keys,
`setup.py platform list|preview|apply|remove-preview|remove` with the person's `플랫폼 <h12>` answer (every preview line
in the question — checked by the script and by the guard), init choosing kinds and platforms, update adding missing
files and never replacing a person's platform file, record-brief's unchecked-platform warning."""

import json
import os
from unittest import mock

import helpers
import state_fixtures as F
import transcripts as TR
from helpers import StudioTestCase
from stdo.distribute import check as copy_check, rules
from stdo.setup import labels as sl, platform as pf, render, update
from stdo.state import labels as state_labels, store
from test_guard_judge import JudgeCase
from test_m1c import SETUP, SID, InitCase
from test_m2a import run_cli

V1 = """---
platform: youtube
audience: public
checked: "2026-11-01"
---
<!-- studio:rules -->
```json
%s
```
<!-- /studio:rules -->
"""
BASE = {"title_max": 100, "description_max_bytes": 5000, "hashtags_max": 15, "required": ["AI voice."]}

DRAFT = """---
platform: clips
audience: public
checked: ""
outputs:
  - name: shorts
    aspect: "9:16"
    max_duration: 60
    layout: shorts
sources:
  - https://help.example.com/clips/upload
---
# Clips

<!-- studio:rules -->
```json
{"title_max": null, "description_max_chars": 2200, "hashtags_max": 30, "required": ["AI voice."],
 "chapters": "none", "link": "none"}
```
<!-- /studio:rules -->

## Upload checklist
- Upload the vertical video.
"""


def rules_text(**over):
    data = dict(BASE, **over)
    for k in [k for k, v in over.items() if v is ...]:
        del data[k]
    return V1 % json.dumps(data)


class RulesV2(StudioTestCase):
    def test_v1_reads_as_before(self):
        r, checked = rules.parse(rules_text())
        self.assertEqual((r["chapters"], r["link"], checked), ("required", "body", "2026-11-01"))

    def test_v2_keys(self):
        r, _ = rules.parse(rules_text(title_max=None, description_max_bytes=..., description_max_chars=500,
                                      hashtags_max=0, chapters="none", link="none"))
        self.assertEqual((r["title_max"], r["description_max_chars"], r["hashtags_max"], r["chapters"], r["link"]),
                         (None, 500, 0, "none", "none"))

    def test_refusals(self):
        for over, msg in (({"description_max_chars": 10}, "exactly one of"),
                          ({"description_max_bytes": ...}, "exactly one of"),
                          ({"title_max": 0}, "title_max"), ({"title_max": ...}, "title_max"),
                          ({"hashtags_max": -1}, "hashtags_max"), ({"chapters": "maybe"}, "chapters"),
                          ({"link": "footer"}, "link"), ({"extra": 1}, "unknown rules keys")):
            with self.assertRaises(rules.RulesProblem, msg=over) as cm:
                rules.parse(rules_text(**over))
            self.assertIn(msg, str(cm.exception))

    def test_unknown_key_names_refresh(self):
        repo = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo, ".claude", "studio", "platforms"))
        with open(os.path.join(repo, ".claude", "studio", "platforms", "clips.md"), "w") as f:
            f.write(rules_text(chapter="none"))
        with self.assertRaises(rules.RulesProblem) as cm:
            rules.read(repo, "clips")
        self.assertIn("unknown rules keys: chapter — /std platform refresh clips", str(cm.exception))

    def test_frontmatter_of_the_shipped_files(self):
        for name in render.SHIPPED_PLATFORMS:
            with open(os.path.join(render.TEMPLATES, "platforms", name + ".md"), encoding="utf-8") as f:
                text = f.read()
            fm = rules.frontmatter(text)
            self.assertEqual(fm["platform"], name)
            rules.parse(text)
            self.assertTrue(fm["outputs"])
        with open(os.path.join(render.TEMPLATES, "platforms", "internal.md"), encoding="utf-8") as f:
            fm = rules.frontmatter(f.read())
        self.assertEqual((fm["audience"], fm["outputs"][0]["name"]), ("internal", "internal"))
        with open(os.path.join(render.TEMPLATES, "platforms", "youtube-shorts.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(rules.parse(text)[0]["chapters"], "none")
        self.assertNotIn("format only", text)
        with self.assertRaises(rules.RulesProblem):
            rules.frontmatter("---\nplatform: x\n  stray line\n---\n")


class CopyV2(StudioTestCase):
    def problems(self, rule_over, copy):
        repo = helpers.make_repo(self.tmp) if not hasattr(self, "repo") else self.repo
        self.repo = repo
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir, exist_ok=True)
        path = os.path.join(self.tmp, "copy.md")
        with open(path, "w") as f:
            f.write(copy)
        r, _ = rules.parse(rules_text(**rule_over))
        st = F.state()
        st["source"]["url"] = "https://example.com/a"
        with mock.patch.object(copy_check.rules_mod, "read", return_value=(r, "2026-11-01")), \
                mock.patch.object(copy_check, "overlay_terms", return_value=("ok", [])), \
                mock.patch.object(copy_check, "excerpt_problems", return_value=[]), \
                mock.patch.object(copy_check, "chapter_files", return_value=[os.path.join(self.tmp, "ch.txt")]), \
                mock.patch.object(copy_check, "source_line", return_value="원문: https://example.com/a"):
            with open(os.path.join(self.tmp, "ch.txt"), "w") as f:
                f.write("0:00 시작\n")
            return copy_check.problems(repo, vdir, st, "ko", {"repo": repo, "studio_root": "studio"}, "p", {}, {},
                                       path)

    def test_no_title(self):
        body = "About it.\nAI voice.\n"
        self.assertEqual(self.problems({"title_max": None, "chapters": "none", "link": "none"},
                                       "---\nhashtags: []\n---\n" + body), [])
        got = self.problems({"title_max": None, "chapters": "none", "link": "none"},
                            "---\ntitle: \"t\"\nhashtags: []\n---\n" + body)
        self.assertTrue(any("has no title" in p for p in got), got)
        got = self.problems({}, "---\nhashtags: []\n---\n" + body)  # a v1 platform still needs one
        self.assertTrue(any("no title" in p for p in got), got)

    def test_chapters_and_link(self):
        body = "About it.\nAI voice.\n"
        got = self.problems({}, "---\ntitle: \"t\"\nhashtags: []\n---\n" + body)
        self.assertTrue(any("chapters" in p for p in got) and any("source link line" in p for p in got), got)
        self.assertEqual(self.problems({"chapters": "none", "link": "none"},
                                       "---\ntitle: \"t\"\nhashtags: []\n---\n" + body), [])

    def test_characters_or_bytes(self):
        body = "가" * 30 + "\nAI voice.\n"
        over = {"chapters": "none", "link": "none"}
        copy = "---\ntitle: \"t\"\nhashtags: []\n---\n" + body
        self.assertTrue(any("bytes" in p for p in self.problems(dict(over, description_max_bytes=60), copy)))
        self.assertEqual(self.problems(dict(over, description_max_bytes=..., description_max_chars=60), copy), [])
        got = self.problems(dict(over, description_max_bytes=..., description_max_chars=20), copy)
        self.assertTrue(any("characters (at most 20)" in p for p in got), got)


# ---------------------------------------------------------------- preview lines

class PreviewLines(StudioTestCase):
    def test_lines(self):
        lines = pf.preview_lines("clips", DRAFT)
        self.assertEqual(lines, [
            "플랫폼 clips — audience public",
            "플랫폼 clips — output shorts: 9:16, max 60 s, layout shorts",
            "플랫폼 clips — title_max: null",
            "플랫폼 clips — description_max_chars: 2200",
            "플랫폼 clips — hashtags_max: 30",
            "플랫폼 clips — chapters: none",
            "플랫폼 clips — link: none",
            "플랫폼 clips — required: AI voice.",
            "플랫폼 clips — source: https://help.example.com/clips/upload",
            "플랫폼 clips — 본문 sha %s (%d줄)" % (pf._sha(pf.body_of(DRAFT))[:12], len(pf.body_of(DRAFT).splitlines()))])
        # the body is approved too: a changed copy note changes the last line
        other = pf.preview_lines("clips", DRAFT.replace("Upload the vertical video.", "Mention the brand."))
        self.assertEqual(other[:-1], lines[:-1])
        self.assertNotEqual(other[-1], lines[-1])

    def test_the_documents_example_parses(self):
        with open(os.path.join(helpers.SKILL, "commands", "platform.md"), encoding="utf-8") as f:
            ex = f.read().split("   ~~~\n", 2)[1]
        ex = "\n".join(l[3:] for l in ex.splitlines()) + "\n"
        ex = ex.replace("<name>", "clips").replace("<the platform's help page>", "help.example.com/x")
        self.assertIn("플랫폼 clips — audience public", pf.preview_lines("clips", ex))

    def test_refusals(self):
        for old, new, msg in (("https://help", "http://help", "not an https address"),
                              ('aspect: "9:16"', 'aspect: "4:3"', "aspect must be"),
                              ("platform: clips", "platform: other", "platform: must be clips"),
                              ("audience: public", "audience: everyone", "audience"),
                              ("layout: shorts", "layout: wide", "layout must be"),
                              ("max_duration: 60", "max_duration: -5", "max_duration"),
                              ("sources:\n  - https://help.example.com/clips/upload\n", "", "help pages")):
            with self.assertRaises(pf.PlatformProblem, msg=new) as cm:
                pf.preview_lines("clips", DRAFT.replace(old, new))
            self.assertIn(msg, str(cm.exception))


# ---------------------------------------------------------------- setup.py platform

class PlatformCase(InitCase):
    def setUp(self):
        super().setUp()
        self.init(kinds=["youtube", "sns"], platforms=["youtube", "youtube-shorts"])
        self.commit_all()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SID

    def draft(self, name, text):
        p = os.path.join(self.repo, pf.draft_rel(name))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, rel):
        with open(os.path.join(self.repo, rel), encoding="utf-8") as f:
            return f.read()


class Platform(PlatformCase):
    def test_init_installs_the_chosen_files(self):
        for rel in (".claude/studio/formats/youtube.md", ".claude/studio/formats/sns.md",
                    ".claude/studio/platforms/youtube.md", ".claude/studio/platforms/youtube-shorts.md"):
            self.assertTrue(os.path.isfile(os.path.join(self.repo, rel)), rel)
        for rel in (".claude/studio/formats/onboarding.md", ".claude/studio/platforms/internal.md"):
            self.assertFalse(os.path.exists(os.path.join(self.repo, rel)), rel)
        inst = json.loads(self.read(render.INSTALLED))
        self.assertTrue(inst["templates"][".claude/studio/platforms/internal.md"].get("declined"))
        self.assertNotIn("declined", inst["templates"][".claude/studio/formats/sns.md"])
        states = {i["path"]: i["state"] for i in update.plan(self.repo)["templates"]}
        self.assertEqual(states[".claude/studio/platforms/internal.md"], "declined")  # init's answer is kept

    def test_list(self):
        self.assertEqual(self.setup("platform", "list"), 0, self.last_err)
        got = {p["name"]: p for p in self.out_json()["platforms"]}
        self.assertEqual(sorted(got), ["youtube", "youtube-shorts"])
        self.assertEqual(got["youtube-shorts"]["outputs"], ["shorts 9:16"])
        self.assertEqual((got["youtube"]["rules"], got["youtube-shorts"]["rules"]), ("v1", "v2"))
        self.assertIn("not checked yet", got["youtube"]["warning"])

    def test_add_apply_with_evidence(self):
        self.draft("clips", DRAFT)
        self.assertEqual(self.setup("platform", "preview", "clips"), 0, self.last_err)
        p = self.out_json()
        self.assertEqual((p["action"], p["lines"]), ("add", pf.preview_lines("clips", DRAFT)))
        self.assertEqual(p["label"], "플랫폼 %s" % p["h12"])
        argv = ["platform", "apply", "clips"]
        self.assertEqual(self.setup(*argv), 2)  # no --expect: what to ask
        argv += ["--expect", p["h12"]]
        self.assertEqual(self.setup(*argv), 6)  # no answer
        self.pend(argv, p["label"], question="규칙을 적용할까요?\n" + "\n".join(p["lines"][:-1]))
        self.assertEqual(self.setup(*argv), 6)
        self.assertIn("values-not-shown", self.last_err)
        self.pend(argv, p["label"], question="규칙을 적용할까요?\n" + "\n".join(p["lines"]))
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        text = self.read(pf.file_rel("clips"))
        self.assertRegex(text, r'\nchecked: "\d{4}-\d{2}-\d{2}"\n')
        self.assertEqual(text.replace(rules.frontmatter(text)["checked"], ""), DRAFT)  # only checked changed
        self.assertFalse(os.path.exists(os.path.join(self.repo, pf.draft_rel("clips"))))
        self.assertEqual(self.setup(*argv), 1)  # the draft is gone

    def test_refresh_unchanged_sets_only_checked(self):
        before = self.read(pf.file_rel("youtube-shorts"))
        self.draft("youtube-shorts", before)
        self.assertEqual(self.setup("platform", "preview", "youtube-shorts"), 0, self.last_err)
        p = self.out_json()
        self.assertEqual(p["action"], "refresh")
        argv = ["platform", "apply", "youtube-shorts", "--expect", p["h12"]]
        self.pend(argv, p["label"], question="\n".join(p["lines"]))
        self.assertEqual(self.setup(*argv, "--proxy"), 2)  # the person's rules
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        after = self.read(pf.file_rel("youtube-shorts"))
        self.assertEqual(after.replace(rules.frontmatter(after)["checked"], ""), before)

    def test_preview_refuses(self):
        home = "/".join(("", "Users", "x"))  # not spelled out (structure_test.sh: no home paths in the plugin)
        self.draft("clips", DRAFT.replace("Upload the vertical video.", "Upload from %s." % home))
        self.assertEqual(self.setup("platform", "preview", "clips"), 1)
        self.assertIn("home path", self.last_err)
        self.assertEqual(self.setup("platform", "preview", "../x"), 2)
        self.draft("bad", DRAFT.replace("platform: clips", "platform: bad").replace('"9:16"', '"5:4"'))
        self.assertEqual(self.setup("platform", "preview", "bad"), 1)
        self.assertIn("aspect", self.last_err)

    def test_preview_refuses_an_in_house_term(self):
        self.draft("clips", DRAFT.replace("Upload the vertical video.", "Upload to Zorblax."))
        with mock.patch("stdo.commit.harness.overlay_terms", return_value=("ok", ["Zorblax"])):
            self.assertEqual(self.setup("platform", "preview", "clips"), 1)
        self.assertIn("in-house term", self.last_err)
        with mock.patch("stdo.commit.harness.overlay_terms", return_value=("missing", [])):
            self.assertEqual(self.setup("platform", "preview", "clips"), 1)
        self.assertIn("overlay is missing", self.last_err)

    def video(self, vid, platforms):
        store.enable_writes()
        st = F.state()
        st["video"] = vid
        st["brief"]["platforms"] = platforms
        st["brief"]["outputs"] = sorted({o for outs in platforms.values() for o in outs})
        vdir = os.path.join(self.repo, "studio", "videos", vid)
        os.makedirs(vdir)
        store.create(vdir, st)

    def test_remove(self):
        self.video("v1", {"youtube-shorts": ["shorts"], "youtube": ["youtube"]})
        self.assertEqual(self.setup("platform", "remove-preview", "youtube-shorts"), 0, self.last_err)
        p = self.out_json()
        self.assertIn("state.py exclude-output v1 v1".replace("v1 v1", "v1 shorts"), p["refused"])
        argv = ["platform", "remove", "youtube-shorts", "--expect", p["h12"]]
        self.assertEqual(self.setup(*argv), 3)
        self.video("v2", {"youtube-shorts": ["shorts"], "clips": ["shorts"]})
        self.setup("platform", "remove-preview", "youtube-shorts")
        refused = self.out_json()["refused"]
        self.assertIn("v2 (abandon it: the platform shares its output with clips", refused)
        self.assertNotIn("exclude-output v2", refused)
        for v in ("v1", "v2"):
            st = store.read_state(os.path.join(self.repo, "studio", "videos", v))
            st["langs"]["ko"]["status"] = "aborted"
            with open(os.path.join(self.repo, "studio", "videos", v, "work", "state.json"), "w") as f:
                json.dump(st, f)
        self.setup("platform", "remove-preview", "youtube-shorts")
        p = self.out_json()
        self.assertNotIn("refused", p)
        argv = ["platform", "remove", "youtube-shorts", "--expect", p["h12"]]
        self.pend(argv, p["label"], question="\n".join(p["lines"]))
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        self.assertFalse(os.path.exists(os.path.join(self.repo, pf.file_rel("youtube-shorts"))))


class Labels(StudioTestCase):
    def test_evidence_and_label(self):
        for argv, need in ((["platform", "list"], False), (["platform", "preview", "x"], False),
                           (["platform", "remove-preview", "x"], False), (["platform", "apply", "x"], True),
                           (["platform", "remove", "x"], True)):
            self.assertEqual(sl.needs_evidence(argv, []), need, argv)
        self.assertEqual(sl.expected(["platform", "apply", "x", "--expect", "a" * 12]),
                         ("플랫폼 " + "a" * 12, "a" * 12))
        self.assertEqual(state_labels.parse("플랫폼 " + "b" * 12), ("platform", {"h12": "b" * 12}))


# ---------------------------------------------------------------- init and update

class InitChoices(InitCase):
    def plan(self, **over):
        p = os.path.join(self.tmp, "answers.json")
        with open(p, "w") as f:
            json.dump(self.answers(**over), f, ensure_ascii=False)
        return self.setup("init", "plan", "--answers", p)

    def test_kinds_need_their_platforms(self):
        self.assertEqual(self.plan(kinds=["onboarding"], platforms=["youtube"]), 2)
        self.assertIn("no platform for onboarding", self.last_err)
        self.assertEqual(self.plan(kinds=["youtube"], platforms=["youtube", "internal"]), 2)
        self.assertIn("no kind for platform internal", self.last_err)
        self.assertEqual(self.plan(kinds=["shorts"]), 2)
        self.assertEqual(self.plan(platforms=["tiktok"]), 2)
        self.assertEqual(self.plan(kinds=["youtube", "explainer"], platforms=["internal", "youtube"]), 0,
                         self.last_err)
        files = self.out_json()["files"]
        self.assertIn(".claude/studio/formats/explainer.md", files)
        self.assertIn(".claude/studio/platforms/internal.md", files)
        self.assertEqual(self.out_json()["answers"]["platforms"], ["youtube", "internal"])

    def test_defaults(self):
        self.assertEqual(self.plan(), 0, self.last_err)
        files = self.out_json()["files"]
        self.assertEqual(sorted(f for f in files if f.startswith((".claude/studio/formats/",
                                                                  ".claude/studio/platforms/"))),
                         [".claude/studio/formats/youtube.md", ".claude/studio/platforms/youtube.md"])


class UpdateAdditive(PlatformCase):
    def item(self, p, rel):
        return [i for i in p["templates"] if i["path"] == rel][0]

    def test_missing_is_added_and_a_persons_platform_kept(self):
        guide = ".claude/studio/guides/board.md"
        os.remove(os.path.join(self.repo, guide))
        yt = pf.file_rel("youtube")
        with open(os.path.join(self.repo, yt), "a", encoding="utf-8") as f:
            f.write("\nA person's note.\n")
        inst_p = os.path.join(self.repo, render.INSTALLED)
        inst = json.loads(self.read(render.INSTALLED))
        inst["templates"][yt]["sha"] = "0" * 64  # an older template: both sides changed
        with open(inst_p, "w") as f:
            json.dump(inst, f)
        p = update.plan(self.repo)
        g, y = self.item(p, guide), self.item(p, yt)
        self.assertEqual((g["state"], g["action"], g["resolved"]), ("missing", "write-new", True))
        self.assertEqual((y["state"], y["action"], y["resolved"]), ("person-platform", "keep", True))
        self.assertNotIn(yt, p["conflicts"])
        for take in ("new", "new-file"):
            with self.assertRaises(Exception):
                update.plan(self.repo, "%s=%s" % (yt, take))
        with mock.patch.object(update, "with_evidence", lambda top, argv, label, proxy, fn, cmd: fn()):
            update.apply(self.repo, p["h12"], None, ["update", "apply"])
        self.assertTrue(os.path.isfile(os.path.join(self.repo, guide)))
        self.assertIn("A person's note.", self.read(yt))


# ---------------------------------------------------------------- record-brief

class BriefWarnings(StudioTestCase):
    def test_unchecked_warning_and_the_internal_lines(self):
        store.enable_writes()
        repo = helpers.make_repo(self.tmp)
        st = F.state()
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir)
        store.create(vdir, st)
        F.brief_ready(repo, vdir)
        p = os.path.join(vdir, "work", "brief.json")
        with open(p, "w") as f:
            json.dump({"claims": [F.C1], "roles": [{"name": "narrator"}], "outputs": ["youtube"],
                       "platforms": {"youtube": ["youtube"]}}, f)
        code, _out, err = run_cli(repo, "record-brief", "v1", "--from", p)
        self.assertEqual(code, 0, err)
        self.assertIn("platforms/youtube.md is not checked yet", err)
        st2 = dict(F.state(), video="v2", kind="explainer", scope="internal", location="local")
        vdir2 = os.path.join(repo, "studio", "local", "videos", "v2")
        os.makedirs(vdir2)
        store.create(vdir2, st2)
        F.brief_ready(repo, vdir2)
        F.write_format(repo, kind="explainer")
        with open(os.path.join(repo, ".claude", "studio", "platforms", "internal.md"), "w") as f:
            f.write("---\nplatform: internal\nchecked: \"\"\noutputs:\n  - name: youtube\n    aspect: \"16:9\"\n"
                    "    max_duration: null\n---\n")
        p2 = os.path.join(vdir2, "work", "brief.json")
        with open(p2, "w") as f:
            json.dump({"claims": [F.C1], "roles": [{"name": "narrator"}], "outputs": ["youtube"],
                       "platforms": {"internal": ["youtube"]}}, f)
        code, _out, err = run_cli(repo, "record-brief", "v2", "--from", p2)
        self.assertEqual(code, 1)
        for want in ("audience: internal", "- name: internal", "/std platform refresh internal"):
            self.assertIn(want, err)


# ---------------------------------------------------------------- the guard

class GuardPlatform(JudgeCase):
    def setUp(self):
        super().setUp()
        self.tpath = TR.transcript_path(self.env)
        d = os.path.join(self.repo, ".claude", "studio", "local", "drafts", "platforms")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "clips.md"), "w", encoding="utf-8") as f:
            f.write(DRAFT)

    def run_hook(self, cmd, **extra):
        from stdo.guard import judge
        h = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
             "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
             "prompt_id": getattr(self, "t", None) and self.t.prompt or "p-none"}
        h.update(extra)
        return judge.decide(h, self.env, snapshot_loader=self.loader)

    def turn(self, label, qtext):
        self.t = TR.approval_turn(TR.T(), label, qtext=qtext)
        self.t.write(self.tpath)

    def test_apply_needs_every_line(self):
        h = pf.apply_hash("clips", DRAFT)
        lines = pf.preview_lines("clips", DRAFT)
        cmd = "python3 %s platform apply clips --expect %s" % (SETUP, h)
        deny, _ = self.run_hook(cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.turn("플랫폼 %s" % h, "규칙? %s\n%s" % (h, "\n".join(lines[:-1])))
        deny, _ = self.run_hook(cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn(lines[-1], deny.message())
        self.turn("플랫폼 %s" % h, "규칙? %s\n%s" % (h, "\n".join(lines)))
        deny, ctx = self.run_hook(cmd)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)
        deny, _ = self.run_hook(cmd + " --proxy")
        self.assertEqual(deny.rule, "G-PROXY")
        for bad in ("platform apply ../x --expect %s" % h, "platform apply nodraft --expect %s" % h):
            deny, _ = self.run_hook("python3 %s %s" % (SETUP, bad))
            self.assertEqual(deny.rule, "G-APPROVAL", bad)

    def test_read_only_lines_need_no_answer(self):
        for sub in ("platform list", "platform preview clips", "platform remove-preview clips"):
            deny, _ = self.run_hook("python3 %s %s" % (SETUP, sub))
            self.assertIsNone(deny, "%s: %s" % (sub, deny and deny.message()))
