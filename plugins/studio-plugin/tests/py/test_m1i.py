"""M1i (m1-plan §11): the commit kind `video` (`check_commit.py --stage video`, the hook's pronounce rule), `status`,
plus the M1h leftovers (copy-verify in ④b's shown artifacts; a scene title that states something is judged at ①)."""

import contextlib
import io
import json
import os
import subprocess

import helpers
from helpers import StudioTestCase
from stdo.commit import cli as commit_cli, video as video_kind
from stdo.state import cli, store
from test_m1h import FACT, CopyCase

E_NO_CLAUDE = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID")


class CommitCase(CopyCase):
    """A video approved through ④b."""

    def setUp(self):
        super().setUp()
        self.to_four_a()
        self.ready()
        self.assertEqual(self.validate(), 0, self.out + self.err)
        self.assertEqual(self.state("stage-done", "v1", "copy", "--platform", "youtube"), 0, self.err)
        self.assertEqual(self.state("shown", "v1", "4b", "--platform", "youtube"), 0, self.err)
        self.h4b = [l.split()[1] for l in self.out.splitlines() if l.startswith("hash12 ")][0]
        self.approve_scoped("4b", self.h4b, "--platform", "youtube")

    def env(self):
        e = dict(os.environ)
        for k in E_NO_CLAUDE:
            e.pop(k, None)
        return e

    def cc(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        kinds = {"video": video_kind.VideoKind(providers=self.providers)}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = commit_cli.main(list(argv), cwd=self.repo, env=self.env(), extra_kinds=kinds)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def staged(self):
        return subprocess.run(["git", "-C", self.repo, "diff", "--cached", "--name-only"], capture_output=True,
                              text=True).stdout.split()

    def pronounce(self, text):
        with open(os.path.join(self.repo, ".claude", "studio", "pronounce.json"), "w") as f:
            f.write(text)
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "a shared reading")


class VideoCommit(CommitCase):
    def test_stage_hook_commit_done(self):
        self.assertEqual(self.cc("--stage", "video", "v1"), 0, self.err + self.out)
        staged = self.staged()
        self.assertIn("studio/videos/v1/script.ko.md", staged)
        self.assertIn("studio/videos/v1/CREDITS.yaml", staged)
        self.assertIn(".claude/studio/pronounce.json", staged)
        self.assertTrue([p for p in staged if p.startswith("studio/voices/_qwen/")], staged)
        self.assertFalse([p for p in staged if "/work/" in p or "CREDITS.draft" in p], staged)
        with open(os.path.join(self.repo, ".claude", "studio", "pronounce.json")) as f:
            self.assertEqual(json.load(f), {"空港": "쿠우코오"})
        self.assertNotIn("발음 사전", self.out)
        from stdo.commit import okfile
        ok, _why = okfile.read(self.repo)  # what the guard records from the person's answer in a session
        ok["approval"] = {"mode": "human", "answer": ok["label"]}
        okfile.write(self.repo, ok)
        self.assertEqual(self.cc("--staged"), 0, self.err)  # the hook (no Claude Code session here)
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "video v1")
        self.assertEqual(self.state("done", "v1"), 0, self.err)

    def test_skipped_reading_is_in_the_summary(self):
        self.pronounce('{\n  "空港": "구우코우"\n}\n')
        self.assertEqual(self.cc("--stage", "video", "v1"), 0, self.err + self.out)
        self.assertIn("발음 사전: 충돌 1개 건너뜀 (空港)", self.out)
        self.assertNotIn(".claude/studio/pronounce.json", self.staged())

    def test_hook_checks_the_staged_dictionary(self):
        self.assertEqual(self.cc("--stage", "video", "v1"), 0, self.err + self.out)
        p = os.path.join(self.repo, ".claude", "studio", "pronounce.json")
        with open(p, "w") as f:
            f.write('{\n  "空港": "쿠우코오",\n  "x": "y"\n}\n')
        helpers.git(self.repo, "add", ".claude/studio/pronounce.json")
        self.assertNotEqual(self.cc("--staged"), 0)
        self.assertIn("not HEAD's with video v1's approved readings merged", self.err)

    def test_credits_change_after_four_b(self):
        with open(os.path.join(self.vdir, "CREDITS.yaml"), "a") as f:
            f.write(" ")
        self.assertEqual(self.cc("--stage", "video", "v1"), 1)
        self.assertIn("redo copy", self.err)
        self.assertEqual(self.staged(), [])

    def test_proxy_credit_refused(self):
        st = store.read_state(self.vdir)
        st["credits"][list(st["credits"])[0]]["approved_by"] = "proxy"
        with open(os.path.join(self.vdir, "work", "state.json"), "w") as f:
            json.dump(st, f)
        self.assertEqual(self.cc("--stage", "video", "v1"), 4)
        self.assertIn("approved in the proxy mode", self.err)

    def test_two_reworked_means_no_old_render(self):
        """J116: a voice change after ④a (the ② section again) leaves the render stale — no commit."""
        with open(os.path.join(self.vdir, "script.ko.md")) as f:
            text = f.read()
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(text.replace("  空港: 쿠우코오\n", "  空港: 쿠우코우\n"))
        self.assertEqual(self.cc("--stage", "video", "v1"), 1)
        self.assertIn("not ready to commit — redo tts", self.err)

    def test_orphan_base_voice(self):
        d = os.path.join(self.repo, "studio", "voices", "_qwen", "Nobody")
        os.makedirs(d)
        with open(os.path.join(d, "ko-00000000.json"), "w") as f:
            f.write("{}")
        self.assertEqual(self.cc("--stage", "video", "v1"), 1)
        self.assertIn("base voices no video in progress uses", self.err)

    def test_copy_must_still_pass(self):
        self.platform(text=open(os.path.join(self.repo, ".claude", "studio", "platforms", "youtube.md")).read()
                      .replace('checked: "2026-10-29"', 'checked: ""'))
        self.assertEqual(self.cc("--stage", "video", "v1"), 1)
        self.assertIn("validate_copy", self.err)


class Units(StudioTestCase):
    def test_merge(self):
        text, skipped = video_kind.merge('{\n  "b": "2",\n  "a": "1"\n}\n', {"c": "3", "a": "1", "b": "9"})
        self.assertEqual(text, '{\n  "b": "2",\n  "a": "1",\n  "c": "3"\n}\n')  # order and format kept, c appended
        self.assertEqual(skipped, ["b"])
        self.assertEqual(video_kind.merge('{"a": "1"}', {"a": "1"}), (None, []))  # nothing to add: idempotent
        self.assertEqual(video_kind.merge("{}\n", {"x": "y"})[0], '{\n  "x": "y"\n}\n')
        self.assertEqual(video_kind.merge(None, {"x": "y"})[0], '{\n  "x": "y"\n}\n')
        with self.assertRaises(ValueError):
            video_kind.merge('{"a": ["1"]}', {"x": "y"})

    def test_allow_list(self):
        k = video_kind.VideoKind()

        class C(object):
            roots = ["studio"]
        for ok in ("studio/videos/v1/script.ko.md", "studio/videos/v1/CREDITS.yaml", "studio/videos/v1/assets/a.png",
                   ".claude/studio/pronounce.json", "studio/voices/_qwen/Sohee/ko-1234abcd.wav"):
            self.assertTrue(k.allowed(C(), ok), ok)
        for bad in ("studio/videos/v1/work/state.json", "studio/videos/v1/CREDITS.draft.yaml", "studio/copy/v1/ko/x.md",
                    "studio/videos/v1/notes.md", ".claude/studio/config.json", "studio/voices/other/x.wav"):
            self.assertFalse(k.allowed(C(), bad), bad)

    def test_redistribution(self):
        repo = helpers.make_repo(self.tmp)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(os.path.join(vdir, "assets"))
        with open(os.path.join(vdir, "CREDITS.yaml"), "w") as f:
            json.dump({"schema": 1, "items": [{"path": "assets/a.png", "redistribute": False}]}, f)

        class C(object):
            top, cfg, env = repo, {}, {}
        got = video_kind.VideoKind()._content_problems(C(), vdir, ["studio/videos/v1/assets/a.png"], "studio", "v1")
        self.assertIn("does not allow redistribution", got[0].message)


class Status(CommitCase):
    def test_warnings_and_since_last(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["status", "--json", "--since-last"], cwd=self.repo), 0)
        data = json.loads(out.getvalue())
        self.assertTrue([w for w in data["warnings"] if "no range check yet" in w], data["warnings"])
        self.assertEqual(data["videos"][0]["langs"]["ko"]["status"], "active")
        os.remove(os.path.join(self.repo, ".claude", "studio", "local", "machine.json"))
        p = os.path.join(self.repo, ".claude", "studio", "platforms", "youtube.md")
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(text.replace('checked: "2026-10-29"', 'checked: "2020-01-01"'))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["status"], cwd=self.repo)
        self.assertIn("this machine has no s2v path", out.getvalue())
        self.assertIn("platforms/youtube.md was checked", out.getvalue())


# ---------------------------------------------------------------- the M1h leftovers

class CopyVerifyShown(CommitCase):
    def test_copy_verify_change_after_shown_needs_showing_again(self):
        with open(os.path.join(self.w, "copy-verify.youtube.json")) as f:
            data = json.load(f)
        self.assertEqual(self.state("shown", "v1", "4b", "--platform", "youtube"), 0, self.err)
        h = [l.split()[1] for l in self.out.splitlines() if l.startswith("hash12 ")][0]
        data["sentences"][0]["note"] = "changed after showing"
        with open(os.path.join(self.w, "copy-verify.youtube.json"), "w") as f:
            json.dump(data, f, ensure_ascii=False)
        argv = ["approve", "v1", "4b", "--expect", h, "--platform", "youtube"]
        self.pend(argv, "승인 v1 %s" % h)
        self.assertNotEqual(self.state(*argv), 0)
        self.assertIn(FACT, open(os.path.join(self.w, "copy-verify.youtube.json")).read())


class SceneTitles(StudioTestCase):
    def test_a_scene_title_that_states_something_is_judged_at_one(self):
        from stdo.claims import check
        cm = {"claims": {}, "excerpts": ["탑승권을 받으면 출국 심사를 받습니다."]}
        draft = {"sentences": [{"text": "x", "kind": "link", "note": "n"}]}
        got = check.draft_problems(draft, cm, None, [], [], ["3개의 탑승권", "출국"])
        self.assertEqual([p for p in got if "scene title" in p],
                         ["not judged: the scene title 3개의 탑승권 (it states something, and it becomes a chapter of "
                          "the copy)"])
