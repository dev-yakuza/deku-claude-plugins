"""M1 end to end (m1-plan §12.2): the person's answers in the transcript → the real guard.py process → the scripts the
harness copied into the repository, run as processes (state.py, resolve_assets.py, check_scope.py, check_claims.py,
check_assets.py, lock.py, check_tts.py, audition.py, run_s2v.py, validate_copy.py, check_commit.py) with the fake s2v →
`git commit` with the installed pre-commit hook. No Claude Code and no model: the test plays the person and the agent
(e2e_runner.Session). The scenarios an earlier milestone already pins at a lower level are listed in §23.10 (J157)."""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest

import helpers
from e2e_runner import Session
from helpers import StudioTestCase
from stdo import machine
from test_e2e_m0 import values_of
from test_m1e import ARTICLE, E1, E2, FAKE_ROOT, S1, S2, SCRIPT, cid, png
from test_m1h import COPY, FACT, NOTICE

sys.path.insert(0, os.path.join(helpers.HERE, "drivers"))
import make_harness  # noqa: E402

SID = "sess-e2e-m1"
PY = "python3 .claude/studio/scripts/"
IMG = "../../../docs/img/gate.png"


def need_tools():
    for tool in ("node", "ffmpeg"):
        if not shutil.which(tool):
            if helpers.full_mode():
                raise AssertionError("--full needs %s" % tool)
            raise unittest.SkipTest("needs %s" % tool)


class E2ECase(StudioTestCase):
    def setUp(self):
        need_tools()
        super().setUp()
        pybin = os.path.join(self.tmp, "pybin")
        os.makedirs(pybin)
        os.symlink(sys.executable, os.path.join(pybin, "python3"))
        self.env = dict(os.environ)
        self.env["PATH"] = pybin + os.pathsep + self.env.get("PATH", "")
        self.repo = make_harness.make(os.path.join(self.tmp, "site"), env=self.env, s2v=FAKE_ROOT)
        machine.write(self.repo, FAKE_ROOT)
        self.scen = os.path.join(self.tmp, "scenario.json")
        self.scenario({})
        bash_env = dict(self.env, STUDIO_TEST_FAKE_S2V_SCENARIO=self.scen)
        self.s = Session(self.repo, self.env, bash_env, SID)
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        self.w = os.path.join(self.vdir, "work", "ko")

    # ---- the world ----
    def scenario(self, data):
        with open(self.scen, "w") as f:
            json.dump(data, f)

    def git(self, *args):
        out = subprocess.run(["git", "-C", self.repo] + list(args), capture_output=True, text=True, env=self.env)
        if out.returncode != 0:
            raise AssertionError("git %s: %s%s" % (" ".join(args), out.stdout, out.stderr))
        return out.stdout

    # ---- the agent ----
    def do(self, cmd, code=0):
        r = self.s.bash(cmd)
        self.assertNotEqual(r.decision, "deny", "%s: %s" % (cmd, r.reason))
        if code is not None:
            self.assertEqual(r.code, code, "%s: %s%s" % (cmd, r.out[-1500:], r.err[-1500:]))
        return r

    def write(self, rel, text):
        p = os.path.join(self.repo, rel)
        d = self.s.tool("Write", {"file_path": p, "content": text})
        self.assertNotEqual(d[0], "deny", "%s: %s" % (rel, d[1]))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    # ---- the person ----
    def gate(self, gate, question, extra_scope=(), lines_from=None):
        """shown → the question with the hash and every `in the question:` line → approve, alone, later. In the
        proxy mode (`self.proxy`) the agent approves with `--proxy` and no question."""
        r = self.do(PY + "state.py shown v1 %s%s" % (gate, "".join(" " + x for x in extra_scope)))
        h = re.search(r"^hash12 ([0-9a-f]{12})$", r.out, re.M).group(1)
        if getattr(self, "proxy", False):
            self.do(PY + "state.py approve v1 %s --expect %s%s --proxy" % (gate, h, "".join(" " + x for x in extra_scope)))
            return h
        lines = re.findall(r"^in the question: (.+)$", r.out, re.M) + list(lines_from or [])
        label = "승인 v1 %s" % h
        self.s.ask("[v1] %s · hash %s\n%s" % (question, h, "\n".join(lines)), [label, "고칠 곳이 있다"], label)
        self.do(PY + "state.py approve v1 %s --expect %s%s" % (gate, h, "".join(" " + x for x in extra_scope)))
        return h

    def harness_commit(self, msg):
        r = self.do(PY + "check_commit.py --stage harness")
        line = re.search(r"put this line in the question as it is:\n(.+)\n", r.out).group(1)
        label = line.split(" | ")[0]
        self.s.ask("하네스를 커밋할까요?\n%s%s" % (line, "".join("\n" + v for v in values_of(r.out))),
                   [label, "아직"], label)
        return self.do('git commit -m "%s"' % msg)

    # ---- preparation (the person's) ----
    def prepare(self):
        cfg_p = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(cfg_p) as f:
            cfg = json.load(f)
        cfg["visibility"] = {"default": "unknown", "public": ["docs/**"]}
        with open(cfg_p, "w") as f:
            json.dump(cfg, f, indent=2)
        fmt = os.path.join(self.repo, ".claude", "studio", "formats", "youtube.md")
        with open(fmt) as f:
            text = f.read()
        with open(fmt, "w") as f:
            f.write(text.replace('"length_seconds": {"min": 180, "max": 480}', '"length_seconds": {"min": 1, "max": 600}'))
        plat = os.path.join(self.repo, ".claude", "studio", "platforms", "youtube.md")
        with open(plat) as f:
            text = f.read()
        with open(plat, "w") as f:
            f.write(text.replace('checked: ""', 'checked: "2026-10-30"'))  # U-M1h, done by the person
        self.harness_commit("studio: the person's settings")
        os.makedirs(os.path.join(self.repo, "docs", "img"))
        with open(os.path.join(self.repo, "docs", "airport.md"), "w") as f:
            f.write(ARTICLE)
        with open(os.path.join(self.repo, "docs", "img", "gate.png"), "wb") as f:
            f.write(png())
        self.git("add", "docs")
        self.git("commit", "-q", "-m", "an article")  # through the hook: no Studio file in it


class FlowCase(E2ECase):
    """The flow's steps as the agent and the person take them."""

    def source_to_one(self):
        self.prepare()
        self.do(PY + "state.py begin v1 --source docs/airport.md --kind youtube")
        self.do(PY + "state.py record-source v1")
        self.do(PY + "resolve_assets.py v1")
        self.write("studio/videos/v1/work/source.md", (
            "# Source\n\n## Claims\n- %s: the counter first\n  > %s\n- %s: then passport control\n  > %s\n\n"
            "<!-- studio:images -->\n```json\n{\"img-01\": {\"class\": \"diagram\", \"reason\": \"own\"}}\n```\n"
            "<!-- /studio:images -->\n") % (cid(E1), E1, cid(E2), E2))
        self.do(PY + "check_scope.py v1")
        self.do(PY + "state.py record-source v1")
        self.write("studio/videos/v1/work/brief.json", json.dumps({
            "claims": [cid(E1), cid(E2)], "roles": [{"name": "narrator"}], "outputs": ["youtube"],
            "platforms": {"youtube": ["youtube"]}}))
        self.do(PY + "state.py record-brief v1 --from work/brief.json")
        self.write("studio/videos/v1/script.ko.md", SCRIPT % {"s1": S1, "s2": S2, "max": 600, "target": 6})
        self.write("studio/videos/v1/work/ko/claims-map.json", json.dumps({
            "claims": {cid(E1): {"excerpt": E1, "sentences": [S1, "空港(くうこう)"]},
                       cid(E2): {"excerpt": E2, "sentences": [S2]}},
            "excerpts": [E1, E2], "copy_excerpts": {}}, ensure_ascii=False))
        self.do(PY + "check_claims.py v1 --narration")
        self.do(PY + "state.py stage-done v1 script")
        self.write("studio/videos/v1/work/ko/verify.draft.json", json.dumps({"sentences": [
            {"text": S1, "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]},
            {"text": "空港(くうこう)", "kind": "fact", "verdict": "supported", "claims": [cid(E1)], "excerpts": [E1]},
            {"text": S2, "kind": "fact", "verdict": "supported", "claims": [cid(E2)], "excerpts": [E2]}]},
            ensure_ascii=False))
        self.do(PY + "check_claims.py v1")
        self.do(PY + "state.py stage-done v1 verify")
        self.gate("1", "① 대본 — studio/videos/v1/script.ko.md")

    def one_to_two(self):
        st = json.load(open(os.path.join(self.repo, "studio", "cast", "narrator", "status.json")))
        v = st["voice"]["ko"]
        script = os.path.join(self.vdir, "script.ko.md")
        text = open(script).read().replace("lang: ko\n", "lang: ko\ncast:\n  narrator: { voice: \"%s\", style: \"%s\" }"
                                           "\npronounce:\n  空港: 쿠우코오\n" % (v["engine"], v["style"]), 1)
        self.write("studio/videos/v1/script.ko.md", text)
        self.write("studio/videos/v1/work/ko/pronounce-changes.json", json.dumps({"空港": "쿠우코오"}, ensure_ascii=False))
        self.do(PY + "check_assets.py v1 --actors")
        self.do(PY + "state.py stage-done v1 cast")
        main = os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js")
        self.do(PY + "lock.py run --kind tts -- node %s tts studio/videos/v1/script.ko.md" % main)
        self.do(PY + "check_tts.py v1")
        self.do(PY + "state.py stage-done v1 tts")
        self.do(PY + "audition.py v1")
        self.do(PY + "state.py stage-done v1 audition")
        self.gate("2", "② 오디션 — studio/out/v1/ko/audition/narrator.wav")

    def two_to_four_b(self):
        self.two_to_three()
        self.render_to_four_b()

    def credit(self):
        r = self.do(PY + "state.py credit-preview v1 %s" % IMG)
        lines = [l for l in r.out.splitlines() if "=" in l and not l.startswith(("label", "이전"))]
        h = re.search(r"label 출처 v1 ([0-9a-f]{12})", r.out).group(1)
        if getattr(self, "proxy", False):
            return self.do(PY + "state.py credit v1 %s --expect %s --proxy" % (IMG, h))
        label = "출처 v1 %s" % h
        self.s.ask("[v1] 출처 — %s · hash %s\n%s" % (IMG, h, "\n".join(lines)), [label, "고칠 곳이 있다"], label)
        return self.do(PY + "state.py credit v1 %s --expect %s" % (IMG, h))

    def three(self):
        r = self.do(PY + "run_s2v.py snapshot v1 --output youtube")
        h3 = re.search(r"hash12 ([0-9a-f]{12})", r.out).group(1)
        self.do(PY + "state.py stage-done v1 visual-check --output youtube")
        if getattr(self, "proxy", False):
            self.do(PY + "state.py approve v1 3 --expect %s --output youtube --proxy" % h3)
            return h3
        self.s.ask("[v1] ③ 정지 화면 — youtube · hash %s" % h3, ["승인 v1 %s" % h3, "고칠 곳이 있다"], "승인 v1 %s" % h3)
        self.do(PY + "state.py approve v1 3 --expect %s --output youtube" % h3)
        return h3

    def render(self):
        self.do(PY + "run_s2v.py render v1 --output youtube")
        self.do(PY + "state.py record-render v1 --output youtube")
        self.do(PY + "state.py stage-done v1 render --output youtube")

    def two_to_three(self):
        script = os.path.join(self.vdir, "script.ko.md")
        self.write("studio/videos/v1/script.ko.md", open(script).read().replace("lang: ko\n", "lang: ko\ntheme: dark\n", 1))
        self.write("studio/videos/v1/CREDITS.draft.yaml", json.dumps({"schema": 1, "items": [{
            "path": IMG, "license": "own work", "credit_line": "the author", "floor": "public/-",
            "license_checked": True, "public_ok": True, "redistribute": True, "commercial": True}]}))
        self.credit()
        self.do(PY + "check_assets.py v1 --output youtube")
        self.do(PY + "state.py stage-done v1 board --output youtube")
        self.three()

    def render_to_four_b(self):
        self.render()
        self.gate("4a", "④a 최종 — studio/out/v1/ko/youtube.ko.mp4", ("--output", "youtube"))
        self.copy_to_four_b()

    def copy_to_four_b(self):
        chapters = open(os.path.join(self.repo, "studio", "out", "v1", "ko", "youtube.ko.chapters.txt")).read().strip()
        self.write("studio/copy/v1/ko/youtube.md", COPY % {"chapters": chapters, "credit": "the author",
                                                          "notice": NOTICE, "fact": FACT})
        self.write("studio/videos/v1/work/ko/copy-verify.youtube.json", json.dumps({"sentences": [
            {"text": FACT, "kind": "fact", "verdict": "supported", "excerpts": [E2]}]}, ensure_ascii=False))
        cm_p = os.path.join(self.w, "claims-map.json")
        cm = json.load(open(cm_p))
        cm["copy_excerpts"] = {"youtube": [E2]}
        self.write("studio/videos/v1/work/ko/claims-map.json", json.dumps(cm, ensure_ascii=False))
        self.do(PY + "validate_copy.py v1 --platform youtube")
        self.do(PY + "state.py stage-done v1 copy --platform youtube")
        self.gate("4b", "④b 배포용 글 — studio/copy/v1/ko/youtube.md", ("--platform", "youtube"))

    def video_commit(self):
        r = self.do(PY + "check_commit.py --stage video v1")
        return self.commit_staged(r)

    def commit_staged(self, r):
        line = re.search(r"put this line in the question as it is:\n(.+)\n", r.out).group(1)
        label = line.split(" | ")[0]
        self.s.ask("[v1] 영상을 커밋할까요?\n%s" % line, [label, "아직"], label)
        return self.do('git commit -m "studio: video v1"')


class E1Flow(FlowCase):
    def test_e1_from_the_harness_to_done(self):
        """E1: two Studio commits in the session (the person's settings, the video), every gate by a person."""
        self.source_to_one()
        self.one_to_two()
        self.two_to_four_b()
        self.video_commit()
        self.do(PY + "state.py done v1")
        log = self.git("log", "--format=%s").splitlines()
        self.assertEqual(log[:2], ["studio: video v1", "an article"])
        self.assertIn("studio: the person's settings", log)
        st = json.load(open(os.path.join(self.w, "..", "state.json")))
        L = st["langs"]["ko"]
        recs = [L["approved"]["1"], L["approved"]["2"], L["approved"]["3"]["youtube"], L["approved"]["4a"]["youtube"],
                L["approved"]["4b"]["youtube"]]
        self.assertEqual({r["approved_by"] for r in recs}, {"human"})
        self.assertEqual(L["status"], "done")
        self.assertEqual(json.loads(self.git("show", "HEAD:.claude/studio/pronounce.json")), {"空港": "쿠우코오"})

    def test_e13_kanji_in_the_narration(self):
        """E13: the script check refuses a narration with kanji."""
        self.prepare()
        self.do(PY + "state.py begin v1 --source docs/airport.md --kind youtube")
        self.do(PY + "state.py record-source v1")
        self.do(PY + "resolve_assets.py v1")
        self.write("studio/videos/v1/script.ko.md",
                   SCRIPT % {"s1": "공항(空港)에 가면 먼저 체크인 카운터를 찾습니다.", "s2": S2, "max": 600, "target": 6})
        r = self.do(PY + "check_claims.py v1 --narration", code=1)
        self.assertIn("kana or kanji", r.out)


class E2EGuard(E2ECase):
    def test_e1b_begin_before_the_harness_commit(self):
        """E1b: a harness change not committed yet stops begin (3)."""
        cfg_p = os.path.join(self.repo, ".claude", "studio", "config.json")
        cfg = json.load(open(cfg_p))
        cfg["visibility"] = {"default": "unknown", "public": ["docs/**"]}
        json.dump(cfg, open(cfg_p, "w"), indent=2)
        os.makedirs(os.path.join(self.repo, "docs"))
        open(os.path.join(self.repo, "docs", "a.md"), "w").write("# a\n")
        self.git("add", "docs")
        self.git("commit", "-q", "-m", "a")
        r = self.do(PY + "state.py begin v1 --source docs/a.md --kind youtube", code=3)
        self.assertIn("config.json", r.err)

    def test_e11_protected_writes(self):
        """E11: the agent writes verify.json, assets.json, a check result, CREDITS.yaml, machine.json, a protected key."""
        os.makedirs(os.path.join(self.vdir, "work", "ko", "checks"))
        for rel in ("studio/videos/v1/work/ko/verify.json", "studio/videos/v1/work/assets.json",
                    "studio/videos/v1/work/ko/checks/script.json", "studio/videos/v1/CREDITS.yaml",
                    ".claude/studio/local/machine.json"):
            d = self.s.tool("Write", {"file_path": os.path.join(self.repo, rel), "content": "{}"})
            self.assertEqual(d[0], "deny", rel)
            self.assertIn("G-PROT", d[1] or "", rel)
        r = self.s.bash("sed -i '' 's/unknown/public/' .claude/studio/config.json")
        self.assertEqual(r.decision, "deny")

    def test_e16_auditor_write(self):
        """E16: std-auditor writes nothing."""
        d = self.s.tool("Write", {"file_path": os.path.join(self.repo, "notes.md"), "content": "x"},
                        extra={"agent_id": "a1", "agent_type": "std-auditor"})
        self.assertEqual(d[0], "deny")
        self.assertIn("G-AUDIT", d[1])


class E2EVideo(FlowCase):
    """Scenarios from a video at ② or later (each test runs the flow up to where it needs)."""

    def test_e2_one_videos_answer_for_another(self):
        """E2: an answer for v1 does not approve v2 (same content)."""
        self.source_to_one()
        r = self.do(PY + "state.py shown v1 1")
        h = re.search(r"^hash12 ([0-9a-f]{12})$", r.out, re.M).group(1)
        self.s.ask("[v1] ① 대본 · hash %s" % h, ["승인 v1 %s" % h, "아니"], "승인 v1 %s" % h)
        r = self.s.bash(PY + "state.py approve v2 1 --expect %s" % h)
        self.assertTrue(r.decision == "deny" or r.code != 0, r)

    def test_e3_verify_loops_hold_then_a_person(self):
        """E3: three failed verify rounds hold the video (stagnation); a person's 해제 releases it."""
        self.prepare()
        self.do(PY + "state.py begin v1 --source docs/airport.md --kind youtube")
        for _ in range(2):
            self.do(PY + "state.py loop v1 verify")
        self.do(PY + "state.py loop v1 verify", code=4)
        label = "해제 v1 ko stagnation"
        self.s.ask("[v1] 검증이 세 번 실패했습니다. 해제할까요?", [label, "그만두기"], label)
        self.do(PY + "state.py unlock v1 --expect stagnation")

    def test_e5_tts_busy_then_release(self):
        """E5: tts exits 73 under the lock wrapper → held:lock → release-lock once the machine is free."""
        self.source_to_one()
        st = json.load(open(os.path.join(self.repo, "studio", "cast", "narrator", "status.json")))
        v = st["voice"]["ko"]
        script = os.path.join(self.vdir, "script.ko.md")
        self.write("studio/videos/v1/script.ko.md", open(script).read().replace(
            "lang: ko\n", "lang: ko\ncast:\n  narrator: { voice: \"%s\", style: \"%s\" }\n" % (v["engine"], v["style"]), 1))
        self.write("studio/videos/v1/work/ko/pronounce-changes.json", "{}")
        self.do(PY + "check_assets.py v1 --actors")
        self.do(PY + "state.py stage-done v1 cast")
        self.scenario({"tts": {"busy": "lock"}})
        main = os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js")
        r = self.do(PY + "lock.py run --kind tts -- node %s tts studio/videos/v1/script.ko.md" % main, code=73)
        busy = [l for l in r.err.splitlines() if l.startswith("busy (")][0]
        self.do(PY + "state.py hold v1 lock --reason \"%s\"" % busy)
        self.scenario({})
        self.do(PY + "state.py release-lock v1")

    def test_e17_orphan_base_voice(self):
        """E17: a base voice no video uses stops the video commit."""
        self.source_to_one()
        self.one_to_two()
        self.two_to_four_b()
        d = os.path.join(self.repo, "studio", "voices", "_qwen", "Gone")
        os.makedirs(d)
        open(os.path.join(d, "ko-00000000.json"), "w").write("{}")
        r = self.do(PY + "check_commit.py --stage video v1", code=1)
        self.assertIn("base voices no video in progress uses", r.err)

    def test_e22_staging_twice_is_idempotent(self):
        """E22: --stage video twice merges the readings once."""
        self.source_to_one()
        self.one_to_two()
        self.two_to_four_b()
        self.do(PY + "check_commit.py --stage video v1")
        first = open(os.path.join(self.repo, ".claude", "studio", "pronounce.json")).read()
        self.git("reset", "-q")
        self.do(PY + "check_commit.py --stage video v1")
        self.assertEqual(open(os.path.join(self.repo, ".claude", "studio", "pronounce.json")).read(), first)

    def test_e15_done_after_a_harness_commit(self):
        """E15: done refuses when the last Studio commit was a harness commit (kind and target differ)."""
        self.source_to_one()
        self.write(".claude/studio/guides/script.md", "# Script guide\n\n- Keep it short.\n")
        self.harness_commit("studio: a guide")
        r = self.do(PY + "state.py done v1", code=None)
        self.assertNotEqual(r.code, 0)


class E10bHandOver(FlowCase):
    """E10 → E10b (m1-plan §4.2 hand-over, M1j review A1): ①–③ and the credit in the proxy mode (a sandbox session),
    a marked render; then the person, in their own session: ① ② again, ③ on a new snapshot, an unmarked render, ④a,
    copy, ④b — and the video commit, refused while the credit is the proxy's, passing once the person re-runs it."""

    def proxy_session(self):
        from stdo import paths
        env = dict(self.env, STUDIO_SANDBOX="1")
        with open(paths.sandbox_file(env), "w") as f:
            json.dump({"sandbox_root": self.tmp}, f)
        return Session(self.repo, env, dict(env, STUDIO_TEST_FAKE_S2V_SCENARIO=self.scen), "sess-e2e-m1-proxy")

    def outs(self):
        return sorted(os.listdir(os.path.join(self.repo, "studio", "out", "v1", "ko")))

    def test_e10b_proxy_then_the_person_to_the_commit(self):
        self.prepare()  # the committed harness (E10 starts from it)
        person = self.s
        self.prepare = lambda: None
        self.s, self.proxy = self.proxy_session(), True
        self.source_to_one()
        self.one_to_two()
        self.two_to_three()
        self.render()
        self.assertIn("youtube.ko.proxy.mp4", self.outs())
        L = json.load(open(os.path.join(self.vdir, "work", "state.json")))["langs"]["ko"]
        self.assertEqual({L["approved"]["1"]["approved_by"], L["approved"]["2"]["approved_by"],
                          L["approved"]["3"]["youtube"]["approved_by"]}, {"proxy"})
        # the hand-over: the person's own session (no STUDIO_SANDBOX)
        self.s, self.proxy = person, False
        self.gate("1", "① 대본 — studio/videos/v1/script.ko.md")
        self.gate("2", "② 오디션 — studio/out/v1/ko/audition/narrator.wav")
        self.three()  # a new snapshot: its printed hash12 is the one approved
        self.render()
        self.assertIn("youtube.ko.mp4", self.outs())
        self.assertNotIn("youtube.ko.proxy.mp4", self.outs())
        self.gate("4a", "④a 최종 — studio/out/v1/ko/youtube.ko.mp4", ("--output", "youtube"))
        self.copy_to_four_b()
        # the credit is still the proxy's: the video commit waits for the person (exit 4)
        r = self.do(PY + "check_commit.py --stage video v1", code=4)
        self.assertIn("approved in the proxy mode", r.err)
        self.assertEqual(self.git("diff", "--cached", "--name-only").strip(), "")
        self.credit()
        r = self.do(PY + "check_commit.py --stage video v1")
        self.commit_staged(r)
        self.do(PY + "state.py done v1")
        st = json.load(open(os.path.join(self.vdir, "work", "state.json")))
        L = st["langs"]["ko"]
        recs = [L["approved"]["1"], L["approved"]["2"], L["approved"]["3"]["youtube"], L["approved"]["4a"]["youtube"],
                L["approved"]["4b"]["youtube"]] + list(st["credits"].values())
        self.assertEqual({r["approved_by"] for r in recs}, {"human"})
        self.assertFalse(L["renders"]["youtube"]["proxy"])
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "studio: video v1")
