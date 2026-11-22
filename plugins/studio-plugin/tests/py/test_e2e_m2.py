"""M2 end to end (m2-plan §12 case 1), what pilot 4 does: an `sns` video from a public page on the site's own domain,
with YouTube Shorts (the shipped rules, checked by the person through `/std platform refresh`) and one platform added
with `/std platform add` sharing one 9:16 output (one render), and a board capture shown in place of a page picture.
The person's answers in the transcript → the real guard.py process → the scripts the harness copied into the
repository (state.py, capture.py, resolve_assets.py, check_claims.py, check_scope.py, check_assets.py, lock.py,
check_tts.py, audition.py, run_s2v.py, validate_copy.py, check_commit.py) and the plugin's setup.py, run as
processes with the fake s2v (its `capture` too: no network, no browser) → `git commit` with the installed pre-commit
hook. No Claude Code and no model: the test plays the person and the agent (e2e_runner.Session). Every call goes
through the guard, which must not refuse it; the test does not check which calls it allows without a prompt (a call
that would prompt runs as if allowed) — the auto-allow rules are test_guard_autoallow's."""

import hashlib
import json
import os
import re

import helpers
from test_e2e_m0 import values_of
from test_e2e_m1 import PY, FlowCase, question_block
from test_m1e import FAKE_ROOT, cid
from test_m1h import NOTICE

SETUP = "python3 %s " % os.path.join(helpers.SCRIPTS, "setup.py")
HOST = "example.com"
URL = "https://%s/posts/airport" % HOST
PNG = ("89504e470d0a1a0a0000000d4948445200000001000000010800000000"
       "3a7e9b550000000a4944415478da6368000000820081da45083b0000000049454e44ae426082")
PIC = "assets/src-%s.png" % hashlib.sha256(bytes.fromhex(PNG)).hexdigest()[:12]
CAP = "assets/capture-counter.png"
P1 = "공항에 도착하면 먼저 항공사 체크인 카운터를 찾아서 여권과 예약 번호를 직원에게 보여 줍니다."
P2 = "탑승권을 받으면 보안 검색대를 지나서 출국 심사를 받고 면세 구역으로 들어갑니다."
P3 = "출발 삼십 분 전까지 탑승구 앞에 도착해서 안내 방송과 전광판의 탑승구 번호를 다시 확인합니다."
PAGE = {"title": "공항에서 출국하기", "lang": "ko",
        "text": [{"kind": "heading", "text": "공항에서 출국하기"}, {"kind": "paragraph", "text": P1},
                 {"kind": "paragraph", "text": P2}, {"kind": "list-item", "text": P3}],
        "images": [{"src": "https://%s/img/counter.png" % HOST, "hex": PNG, "alt": "체크인 카운터"}]}
TITLES = ("공항", "출국", "탑승구")  # the scene titles: s2v's screen text, judged as facts
REELS = """---
platform: reels
audience: public
checked: ""
outputs:
  - name: shorts
    aspect: "9:16"
    max_duration: 60
sources:
  - https://help.example.net/reels/upload
---
# Reels

<!-- studio:rules -->
```json
{"title_max": null, "description_max_chars": 2200, "hashtags_max": 30, "required": ["%s"],
 "chapters": "none", "link": "none"}
```
<!-- /studio:rules -->

## Copy
- No title: the caption is the description.

## Upload checklist (the person)
- Upload the vertical video as a reel and paste the caption.
""" % NOTICE
SHORTS_COPY = """---
title: "공항에서 출국하기"
hashtags: ["#공항", "#출국"]
---
공항에서 출국하는 순서를 알아봅니다.
%(fact)s

%(credit)s

%(notice)s

%(link)s
"""
REELS_COPY = """---
hashtags: ["#공항", "#출국"]
---
공항에서 출국하는 순서를 알아봅니다.
%(fact)s

%(credit)s

%(notice)s
"""


class SnsFromAPage(FlowCase):
    harness_answers = {"kinds": ["youtube", "sns"], "platforms": ["youtube", "youtube-shorts"],
                       "public_domains": [HOST]}

    # ---- the person's preparation: the platforms, checked and added through /std platform ----
    def platform(self, name, action):
        r = self.do(SETUP + "platform preview %s" % name)
        p = json.loads(r.out)
        self.assertEqual(p["action"], action)
        self.s.ask("플랫폼 %s · hash %s — 규칙을 원문과 비교했습니다. 적용할까요?\n%s"
                   % (name, p["h12"], "\n".join(p["lines"])),
                   [p["label"], "그만두기"], p["label"])
        self.do(SETUP + "platform apply %s --expect %s" % (name, p["h12"]))

    def prepare_platforms(self):
        shorts = os.path.join(self.repo, ".claude", "studio", "platforms", "youtube-shorts.md")
        with open(shorts, encoding="utf-8") as f:
            self.write(".claude/studio/local/drafts/platforms/youtube-shorts.md", f.read())  # refresh: from the file
        self.platform("youtube-shorts", "refresh")
        self.write(".claude/studio/local/drafts/platforms/reels.md", REELS)  # add: the agent's draft
        self.platform("reels", "add")
        r = self.do(SETUP + "platform list")
        got = {p["name"]: p for p in json.loads(r.out)["platforms"]}
        self.assertEqual(got["reels"]["outputs"], ["shorts 9:16"])
        self.assertNotIn("warning", got["reels"])
        self.harness_commit("studio: the person's platforms")

    # ---- source → ① ----
    def source_to_one(self):
        self.prepare_platforms()
        self.scenario({"capture": {URL: PAGE}})
        self.do(PY + "state.py begin v1 --url %s --kind sns" % URL)
        self.do(PY + "capture.py source v1")
        r = self.do(PY + "state.py record-source v1")
        self.capture_line = [l for l in r.out.splitlines() if l.startswith("원본 페이지 캡처: ")]
        self.assertEqual(len(self.capture_line), 1, r.out)
        self.do(PY + "resolve_assets.py v1")
        assets = json.load(open(os.path.join(self.vdir, "work", "assets.json")))
        self.assertEqual([i["id"] for i in assets["images"]], ["img-" + PIC[len("assets/src-"):-len(".png")]])
        self.write("studio/videos/v1/work/source.md", (
            "# Source\n\n## Claims\n- C-00000000: the counter first\n  > %s\n- C-00000000: then the exit\n  > %s\n"
            "- C-00000000: then the gate\n  > %s\n\n## Ruby pairs\n\n## Images\n<!-- studio:images -->\n```json\n"
            "{\"%s\": {\"class\": \"photo\", \"reason\": \"the site's own picture\"}}\n```\n<!-- /studio:images -->\n")
            % (P1, P2, P3, assets["images"][0]["id"]))
        self.do(PY + "check_claims.py v1 --source --fill")
        self.do(PY + "check_scope.py v1")
        self.do(PY + "state.py record-source v1")
        self.write("studio/videos/v1/work/brief.json", json.dumps({
            "claims": [cid(P1), cid(P2), cid(P3)], "roles": [{"name": "narrator"}], "outputs": ["shorts"],
            "platforms": {"youtube-shorts": ["shorts"], "reels": ["shorts"]}}))
        self.do(PY + "state.py record-brief v1 --from work/brief.json")
        r = self.do(PY + "state.py next v1 --enter script")
        out = re.search(r"^(    shorts: \{[^\n]*\})$", r.out, re.M).group(1).strip()
        self.assertIn('aspect: "9:16"', out)
        self.assertIn("subtitles: word", out)
        self.assertIn("maxDuration: 60", out)  # the smaller limit of the two platforms sharing the output (Shorts 180)
        self.write("studio/videos/v1/script.ko.md", self.script(out))
        self.write("studio/videos/v1/work/ko/claims-map.json", json.dumps({
            "claims": {cid(P1): {"excerpt": P1, "sentences": [P1, TITLES[0]]},
                       cid(P2): {"excerpt": P2, "sentences": [P2, TITLES[1]]},
                       cid(P3): {"excerpt": P3, "sentences": [P3, TITLES[2]]}},
            "excerpts": [P1, P2, P3], "copy_excerpts": {}}, ensure_ascii=False))
        self.do(PY + "check_claims.py v1 --narration")
        self.do(PY + "state.py stage-done v1 script")
        facts = [(P1, P1), (TITLES[0], P1), (P2, P2), (TITLES[1], P2), (P3, P3), (TITLES[2], P3)]
        self.write("studio/videos/v1/work/ko/verify.draft.json", json.dumps({"sentences": [
            {"text": t, "kind": "fact", "verdict": "supported", "claims": [cid(e)], "excerpts": [e]} for t, e in facts]
            + [{"text": "narrator", "kind": "link", "note": "the speaker's name on screen"}]}, ensure_ascii=False))
        self.do(PY + "check_claims.py v1")
        self.do(PY + "state.py stage-done v1 verify")
        r = self.do(PY + "state.py shown v1 1")  # the ① question carries the page's capture line
        self.assertIn(self.capture_line[0].split(" — put this line")[0], question_block(r.out))
        self.gate("1", "① 대본 — studio/videos/v1/script.ko.md")

    def script(self, out):
        return ("---\ntitle: 출국\nlang: ko\ncast:\n  narrator: { voice: \"qwen:Sohee\", style: \"차분하게\" }\n"
                "outputs:\n  %s\ntargetDuration: 24\n---\n\n# %s {#airport}\n\n%s\n\n::title[출국]\n\n"
                "# %s {#exit}\n\n%s\n\n::image{src=\"%s\"}\n\n# %s {#gate}\n\n%s\n\n::image{src=\"%s\"}\n"
                % (out, TITLES[0], P1, TITLES[1], P2, PIC, TITLES[2], P3, PIC))

    # ---- cast → ② (no reading changes) ----
    def one_to_two(self):
        self.write("studio/videos/v1/work/ko/pronounce-changes.json", "{}")
        self.do(PY + "check_assets.py v1 --actors")
        self.do(PY + "state.py stage-done v1 cast")
        main = os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js")
        self.do(PY + "lock.py run --kind tts -- node %s tts studio/videos/v1/script.ko.md" % main)
        self.do(PY + "check_tts.py v1")
        self.do(PY + "state.py stage-done v1 tts")
        self.do(PY + "audition.py v1")
        self.do(PY + "state.py stage-done v1 audition")
        self.gate("2", "② 오디션 — studio/out/v1/ko/audition/narrator.wav")

    # ---- board with a capture → ③ ----
    def credit_of(self, path):
        r = self.do(PY + "state.py credit-preview v1 %s" % path)
        h = re.search(r"label 출처 v1 ([0-9a-f]{12})", r.out).group(1)
        label = "출처 v1 %s" % h
        block = question_block(r.out)
        self.assertTrue(block.startswith("[v1] 출처 — %s · hash %s\n" % (path, h)), block)
        self.s.ask(block, [label, "고칠 곳이 있다"], label)
        self.do(PY + "state.py credit v1 %s --expect %s" % (path, h))
        return block

    def board(self):
        self.do(PY + "state.py next v1 --enter board --output shorts")
        r = self.do(PY + "check_assets.py v1 --look --output shorts")
        self.assertIn("shorts", r.out)
        # the visual director: one capture of the page in place of the second picture (its src only)
        r = self.do(PY + "capture.py shot v1 counter --url %s --selector main" % URL)
        self.assertIn("floor: public", r.out)
        script = os.path.join(self.vdir, "script.ko.md")
        text = open(script, encoding="utf-8").read()
        text = text.replace("lang: ko\n", "lang: ko\ntheme: { base: dark, accent: \"#2563EB\" }\n", 1)
        text = text.replace("  shorts: { ", "  shorts: { layout: shorts, ", 1)
        head, tail = text.rsplit('::image{src="%s"}' % PIC, 1)
        self.write("studio/videos/v1/script.ko.md", head + '::image{src="%s"}' % CAP + tail)
        self.write("studio/videos/v1/work/ko/board.md", "# Board\n\n## Captures\n- counter: %s · scene gate · the "
                   "page as the viewer sees it\n\n## Applied\n- theme, layout shorts\n" % URL)
        item = {"license": "own work", "credit_line": "the author", "floor": "public/-", "license_checked": True,
                "public_ok": True, "redistribute": True, "commercial": True}
        self.write("studio/videos/v1/CREDITS.draft.yaml", json.dumps({"schema": 1, "items": [
            dict(item, path=PIC), dict(item, path=CAP)]}))
        self.credit_of(PIC)
        block = self.credit_of(CAP)
        self.assertIn('source="%s"' % URL, block)
        self.assertIn("captured_at=", block)
        self.do(PY + "check_assets.py v1 --output shorts")
        self.do(PY + "state.py stage-done v1 board --output shorts")

    def three(self):
        self.do(PY + "state.py next v1 --enter visual-check --output shorts")
        r = self.do(PY + "run_s2v.py snapshot v1 --output shorts")
        h3 = re.search(r"^hash12 ([0-9a-f]{12})$", r.out, re.M).group(1)
        self.do(PY + "state.py stage-done v1 visual-check --output shorts")
        block = question_block(r.out)
        self.assertRegex(block, r"\n화면 캡처 counter: %s · png [0-9a-f]{12} · public/-" % re.escape(URL))
        label = "승인 v1 %s" % h3
        self.s.ask(block, [label, "고칠 곳이 있다"], label)
        self.do(PY + "state.py approve v1 3 --expect %s --output shorts" % h3)

    # ---- render → ④a, copy per platform → ④b ----
    def render_to_four_a(self):
        self.do(PY + "state.py next v1 --enter render --output shorts")
        self.do(PY + "run_s2v.py render v1 --output shorts")
        self.do(PY + "state.py record-render v1 --output shorts")
        self.do(PY + "state.py stage-done v1 render --output shorts")
        self.gate("4a", "④a 최종 — studio/out/v1/ko/shorts.ko.mp4", ("--output", "shorts"))

    def copy(self, platform, text):
        r = self.do(PY + "state.py next v1 --enter copy --platform %s" % platform)
        link = re.findall(r"^in the description: (.+)$", r.out, re.M)
        self.write("studio/copy/v1/ko/%s.md" % platform, text % {
            "fact": P2, "credit": "the author", "notice": NOTICE, "link": link[0] if link else ""})
        self.write("studio/videos/v1/work/ko/copy-verify.%s.json" % platform, json.dumps({"sentences": [
            {"text": P2, "kind": "fact", "verdict": "supported", "excerpts": [P2]}]}, ensure_ascii=False))
        cm_p = os.path.join(self.w, "claims-map.json")
        cm = json.load(open(cm_p))
        cm["copy_excerpts"][platform] = [P2]
        self.write("studio/videos/v1/work/ko/claims-map.json", json.dumps(cm, ensure_ascii=False))
        self.do(PY + "validate_copy.py v1 --platform %s" % platform)
        self.do(PY + "state.py stage-done v1 copy --platform %s" % platform)
        return link

    def copies(self):
        links = self.copy("youtube-shorts", SHORTS_COPY)
        self.assertEqual(links, ["원문: %s" % URL])  # the Shorts rules put the source link in the description
        self.assertEqual(self.copy("reels", REELS_COPY), [])  # reels: "link": "none"
        # ④b: shown per platform; the last one gives the hash and one question for both, one approval
        r = self.do(PY + "state.py shown v1 4b --platform youtube-shorts")
        self.assertIn("shown youtube-shorts (other scopes not shown yet)", r.out)
        r = self.do(PY + "state.py shown v1 4b --platform reels")
        h = re.search(r"^hash12 ([0-9a-f]{12})$", r.out, re.M).group(1)
        block = question_block(r.out)
        self.assertTrue(block.startswith("[v1] ④b 배포용 글 — studio/copy/v1/ko/reels.md · hash %s" % h), block)
        label = "승인 v1 %s" % h
        self.s.ask(block, [label, "고칠 곳이 있다"], label)
        self.do(PY + "state.py approve v1 4b --expect %s --platform reels" % h)

    # ---- the commit: the page read again first ----
    def recheck_and_commit(self):
        r = self.do(PY + "capture.py recheck v1")
        line = re.search(r"^next: (python3 \.claude/studio/scripts/state\.py record-recheck v1 \d+)$", r.out, re.M)
        self.assertTrue(line, r.out)
        r = self.do(line.group(1))  # the line capture.py printed, as make.md says
        self.assertNotIn("--from-recheck", r.out)  # the same page: nothing to promote
        r = self.do(PY + "check_commit.py --stage video v1")
        self.commit_staged(r)
        self.do(PY + "state.py done v1")

    def test_sns_from_a_page_shorts_and_reels(self):
        self.source_to_one()
        L = json.load(open(os.path.join(self.vdir, "work", "state.json")))["langs"]["ko"]
        self.assertIn("1", L["approved"])
        self.one_to_two()
        self.board()
        self.three()
        self.render_to_four_a()
        self.copies()
        self.recheck_and_commit()
        # one render for both platforms: the 9:16 output they share
        outs = sorted(os.listdir(os.path.join(self.repo, "studio", "out", "v1", "ko")))
        self.assertEqual([f for f in outs if f.endswith(".mp4")], ["shorts.ko.mp4"])
        committed = self.git("show", "--name-only", "--format=", "HEAD").split()
        for rel in ("studio/videos/v1/script.ko.md", "studio/videos/v1/CREDITS.yaml", "studio/videos/v1/%s" % PIC,
                    "studio/videos/v1/%s" % CAP):
            self.assertIn(rel, committed)
        self.assertFalse([p for p in committed if "/work/" in p or p.startswith("studio/out/")], committed)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "studio: video v1")
        st = json.load(open(os.path.join(self.vdir, "work", "state.json")))
        L = st["langs"]["ko"]
        recs = [L["approved"]["1"], L["approved"]["2"], L["approved"]["3"]["shorts"], L["approved"]["4a"]["shorts"],
                L["approved"]["4b"]["youtube-shorts"], L["approved"]["4b"]["reels"]] + list(st["credits"].values())
        self.assertEqual({r["approved_by"] for r in recs}, {"human"})
        self.assertEqual(set(L["approved"]["3"]["shorts"]["captures"]), {CAP})
        self.assertEqual(L["status"], "done")
        self.assertEqual(st["source"]["kind"], "url")
        self.assertEqual(len(st["source"]["rechecks"]), 1)
        self.assertTrue(st["source"]["rechecks"][0]["reachable"])
        # no network: every page the fake s2v loaded is the site's own page, through capture.py
        calls = [json.loads(x) for x in open(os.path.join(self.tmp, "calls.log")) if x.strip()]
        caps = [c for c in calls if c["argv"][:1] == ["capture"]]
        self.assertEqual([c["argv"][1] for c in caps], [URL] * 3)  # source, the board's shot, the recheck
        self.assertEqual({c["no_sandbox"] for c in caps}, {None})
        self.assertEqual(self.git("status", "--porcelain"), "")
