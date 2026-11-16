"""Board captures as pictures (m2-plan §7): a shot's floor (own host, another host, a third-party picture inside it, a
frame inside it, internal hosts, pages and terms), capture.py's refusals of an internal source page and a final
address that names one, the script and board checks, the credit's source and captured_at, a shot taken again (its
sha and time change, the credit is asked again), `idle: false` in gate ③'s question, ③ binding each used shot's bytes
(shown, approve and the video commit), and the commit staging only the pictures the script shows. Fake s2v only."""

import contextlib
import hashlib
import io
import json
import os
import subprocess
import time

import helpers
import state_fixtures as F  # noqa: F401 — the fixtures' import order (test_m2d)
from helpers import StudioTestCase
from stdo import board, credits, s2vrun
from stdo.capture import cli as ccli, rules, shots
from stdo.claims import check as claims_check
from stdo.state import schema, store
from test_m1e import png
from test_m1g import IMG, BoardCase
from test_m1i import CommitCase
from test_m2d import CFG as M2D_CFG, OVERLAY, Shot, items

import make_harness  # noqa: E402 — on the path test_m1e adds (drivers/)

CAP = "assets/capture-hero.png"
CFG = {"public_domains": ["example.com"], "internal_overlay": "required",
       "capture": {"hosts": ["docs.thirdparty.net"], "allow_hosts": []}}


def page(url="https://example.com/a", images=(), opaque=(), text="a page", title=""):
    return {"url": url, "title": title, "text": [{"kind": "paragraph", "text": text, "ruby": []}],
            "images": list(images), "opaque": list(opaque)}


def img(src, inside=True, alt=""):
    return {"src": src, "kind": "img", "alt": alt, "inCapture": inside, "sha256": None}


class Floors(StudioTestCase):
    def judge(self, data, cfg=CFG, it=None, urls=()):
        return shots.judge(data, cfg, it or ("ok", set(), []), list(urls))

    def test_page_and_pictures(self):
        self.assertEqual(self.judge(page()), ("public", None, None))
        self.assertEqual(self.judge(page("https://docs.thirdparty.net/x")),
                         ("third-party", "a page of another host (docs.thirdparty.net)", None))
        # a third-party picture inside the captured area; one outside it does not count
        self.assertEqual(self.judge(page(images=[img("https://cdn.other.net/p.png")]))[:2],
                         ("third-party", "a picture in it from another host (cdn.other.net)"))
        self.assertEqual(self.judge(page(images=[img("https://cdn.other.net/p.png", inside=False)]))[0], "public")
        self.assertEqual(self.judge(page(images=[img("https://example.com/own.png")]))[0], "public")
        self.assertEqual(self.judge(page(images=[img("data:image/png;base64,AA")]))[:2],
                         ("unknown", "a picture in it has no host address"))
        # a frame inside it: unknown, and third-party still wins over unknown
        frame = {"kind": "iframe", "src": None, "bbox": [0, 0, 1, 1], "inCapture": True}
        self.assertEqual(self.judge(page(opaque=[frame]))[:2], ("unknown", "a iframe in it Studio cannot read"))
        self.assertEqual(self.judge(page(opaque=[dict(frame, inCapture=False)]))[0], "public")
        self.assertEqual(self.judge(page(images=[img("https://cdn.other.net/p.png")], opaque=[frame]))[0],
                         "third-party")
        self.assertEqual(self.judge(page(opaque=[dict(frame, kind="<b>")]))[1], "a frame in it Studio cannot read")

    def test_internal(self):
        it = items(OVERLAY)
        urls = ["https://example.com/internal/memo"]
        self.assertIsNone(self.judge(page(), it=it)[2])
        self.assertEqual(self.judge(page(images=[img("https://wiki.corp.example/x.png")]), it=it)[2],
                         "a picture in it comes from an internal host")
        self.assertEqual(self.judge(page("https://example.com/internal/memo/2"), it=it, urls=urls)[2],
                         "the page is an internal source")
        self.assertEqual(self.judge(page("https://example.com/bluebird"), it=it)[2],
                         "the page's address names an in-house term")
        for data in (page(text="the Bluebird plan"), page(title="사내전용 안내"),
                     page(images=[img("https://example.com/a.png", alt="secret-plan")])):
            self.assertEqual(self.judge(data, it=it)[2], "the page names an in-house term", data)
        # a picture's alt text outside the area is not read; an overlay host that is exactly a public domain is not
        self.assertIsNone(self.judge(page(images=[img("https://example.com/a.png", False, "Bluebird")]), it=it)[2])
        self.assertIsNone(self.judge(page(), it=("ok", {"example.com"}, []))[2])

    def test_invisible_characters(self):
        # review 1 MINOR: a soft hyphen or a zero-width space inside a term still names it
        it = items(OVERLAY)
        for t in ("Blue\u00adbird", "Blue\u200bbird", "사내\u200d전용"):
            for data in (page(text=t), page(title=t), page(images=[img("https://example.com/a.png", alt=t)])):
                self.assertEqual(self.judge(data, it=it)[2], "the page names an in-house term", (t, data))

    def test_line_drops_controls(self):
        # review 1 NIT 4: bidirectional controls dropped, C0/C1 controls and line breaks as spaces
        e = {"capture": "hero", "url": "https://example.com/\u202eevil\u2066x\u0085y\u2028z\x9b",
             "sha256": "a" * 64, "floor_text": "public/-", "status": "ok"}
        self.assertEqual(shots.line(e), "화면 캡처 hero: https://example.com/evilx y z  · png aaaaaaaaaaaa · public/-")

    def test_names(self):
        self.assertEqual(shots.script_src("hero"), CAP)
        self.assertEqual(shots.name_of(CAP), "hero")
        for p in ("assets/capture-.png", "assets/capture-Hero.png", "assets/src-abc.png", "x/capture-hero.png", None):
            self.assertIsNone(shots.name_of(p), p)
        self.assertEqual(shots.NAME.pattern, ccli.SHOT_NAME.pattern)


class ShotRules(Shot):
    """capture.py shot's M2f additions: internal source pages, the final address, a left temporary folder, the floor
    and credit lines."""

    def setUp(self):
        super().setUp()
        ov = dict(OVERLAY, internal=dict(OVERLAY["internal"],
                                         sources=[{"url": "https://example.com/internal/memo"}]))
        self.overlay(ov)

    def test_internal_source_page_refused_before_running(self):
        for u in ("https://example.com/internal/memo", "https://example.com/internal/memo/x",
                  "https://example.com/Internal/Memo/index.html"):
            self.assertEqual(self.cap("shot", "v1", "h", "--url", u), 3, (u, self.err))
            self.assertIn("internal source", self.err)
        self.assertEqual(self.calls(), [])

    def test_final_address_judged(self):
        self.write_scenario({"capture": {"https://example.com/a": {"url": "https://example.com/internal/memo"},
                                         "https://example.com/b": {"url": "https://example.com/bluebird"}}})
        self.assertEqual(self.cap("shot", "v1", "ok", "--url", "https://example.com/c"), 0, self.err)
        for n in "ab":
            self.assertEqual(self.cap("shot", "v1", n, "--url", "https://example.com/" + n), 1, n)
            self.assertEqual(self.shots()[n]["status"], "unusable")
            self.assertFalse(os.path.exists(os.path.join(self.vdir, "assets", "capture-%s.png" % n)))
        self.assertIn("in-house term", self.shots()["b"]["reason"])
        self.assertIn("internal source", self.shots()["a"]["reason"])
        self.assertEqual(self.shots()["ok"]["final"], "https://example.com/c")
        self.assertEqual(rules.shot_final_problem("https://example.com/a", M2D_CFG, items(), []), None)

    def test_left_temporary_folder_removed(self):
        left = os.path.join(self.vdir, "work", "captures", ".tmp-old-99999")
        os.makedirs(left)
        self.assertEqual(self.cap("shot", "v1", "hero", "--url", "https://example.com/a"), 0, self.err)
        self.assertFalse(os.path.exists(left))
        self.assertIn("floor: public/-", self.out)
        self.assertIn("credit: the CREDITS.draft.yaml item's path is assets/capture-hero.png and its floor public/-",
                      self.out)
        self.assertEqual(self.cap("shot", "v1", "doc", "--url", "https://docs.thirdparty.net/x"), 0, self.err)
        self.assertIn("floor: third-party/a page of another host (docs.thirdparty.net)", self.out)

    def test_internal_floor_printed(self):
        self.write_scenario({"capture": {"*": {"text": [{"kind": "paragraph", "text": "Bluebird"}]}}})
        self.assertEqual(self.cap("shot", "v1", "hero", "--url", "https://example.com/a"), 0, self.err)
        self.assertIn("internal (the page names an in-house term): a public video cannot show it", self.out)
        self.assertEqual(self.cap("shot", "l1", "hero", "--url", "https://example.com/a"), 0, self.err)
        self.assertNotIn("a public video cannot show it", self.out)


class CaptureFlow(object):
    """A board capture used in place of the script's picture (presentation only: an image's file is in no content
    hash)."""

    def configure(self):
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(p) as f:
            cfg = json.load(f)
        cfg.update(public_domains=CFG["public_domains"], capture=CFG["capture"])
        with open(p, "w") as f:
            json.dump(cfg, f, indent=2)
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-am", "capture settings")

    def captures(self, data):
        self.scenario({"capture": data})

    def cap(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ccli.main(list(argv), cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        return code

    def use(self, src=CAP, old=IMG):
        p = os.path.join(self.vdir, "script.ko.md")
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(text.replace('::image{src="%s"}' % old, '::image{src="%s"}' % src))

    def shot(self, name="hero", url="https://example.com/a"):
        self.assertEqual(self.cap("shot", "v1", name, "--url", url), 0, self.err)

    def credit_capture(self, **over):
        self.credit_draft(path=CAP, **over)
        return self.credit(path=CAP)

    def capture_board(self):
        self.themed()
        self.configure()
        self.captures({"*": {}})
        self.shot()
        self.use()
        self.assertEqual(self.credit_capture(), 0, self.err)
        self.assertEqual(self.check_board(), 0, self.out + self.err)
        self.assertEqual(self.state("stage-done", "v1", "board", "--output", "youtube"), 0, self.err)

    def snapshot(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = s2vrun.main(["snapshot", "v1", "--output", "youtube"], providers=self.providers, cwd=self.repo)
        self.out, self.err = out.getvalue(), err.getvalue()
        self.assertEqual(code, 0, self.err)
        return [l.split()[1] for l in self.out.splitlines() if l.startswith("hash12 ")][0]

    def pend_q(self, argv, answer, question):
        from stdo.state import evidence
        from stdo.state.argv import argv_sha
        from test_m1f import SESSION, stamp
        self.tool += 1
        ev = {"schema": 1, "argv_sha": argv_sha(list(argv)), "session_id": SESSION,
              "tool_use_id": "toolu_q%d" % self.tool, "question_index": 0, "question": question, "answer": answer,
              "mode": "human", "written_at": stamp()}
        os.makedirs(evidence.local_dir(self.repo), exist_ok=True)
        with open(evidence.pending_path(self.repo), "w") as f:
            json.dump(ev, f, ensure_ascii=False)

    def question(self):
        out = self.out.splitlines()
        i = out.index([l for l in out if l.startswith("question (")][0])
        return "\n".join(out[i + 1:out.index("end of question")])


class BoardCapture(CaptureFlow, BoardCase):
    def setUp(self):
        super().setUp()
        self.themed()
        self.configure()
        self.captures({"*": {}})

    def test_board_credit_three(self):
        self.shot()
        self.use()
        # before the credit: the capture is a picture of the script (script check), without a credit (board)
        self.assertEqual(claims_check.picture_problems({"files": [{"path": CAP, "kind": "image"}]}, {},
                                                       shots.usable(self.vdir)), [])
        self.assertEqual(self.check_board(), 1)
        self.assertIn("%s has no CREDITS entry" % CAP, self.out)
        # credit-preview: the eight lines, then the capture's source and time (from its record, not the draft)
        self.credit_draft(path=CAP)
        _c, lines, h = self.preview(CAP)
        rec = json.load(open(os.path.join(self.vdir, "work", "captures.json")))["shots"]["hero"]
        self.assertEqual(lines[-2:], ['source="https://example.com/a"', 'captured_at="%s"' % rec["at"]])
        self.assertEqual(len(lines), 10)
        q = "[v1] 출처 — %s · hash %s\n%s" % (CAP, h, "\n".join(lines[:-1]))
        self.assertEqual(self.credit(lines, h, question=q, path=CAP), 6)  # captured_at not shown
        self.assertIn("captured_at", self.err)
        self.assertEqual(self.credit(lines, h, path=CAP), 0, self.err)
        e = json.load(open(os.path.join(self.vdir, credits.FILE)))["items"][0]
        self.assertEqual((e["path"], e["source"], e["captured_at"], e["sha256"]),
                         (CAP, "https://example.com/a", rec["at"], rec["png_sha"]))
        self.assertEqual(self.check_board(), 0, self.out + self.err)
        self.assertEqual(self.state("stage-done", "v1", "board", "--output", "youtube"), 0, self.err)
        # ③: the capture's line is in the question; approve refuses a question without it
        h3 = self.snapshot()
        line = [l for l in self.out.splitlines() if l.startswith("화면 캡처 hero: ")]
        self.assertTrue(line, self.out)
        self.assertIn("in the question: %s" % line[0], self.out)
        self.assertIn("png %s · public/-" % rec["png_sha"][:12], line[0])
        q3 = self.question()
        self.assertIn(line[0], q3)
        self.assertEqual(self.state("stage-done", "v1", "visual-check", "--output", "youtube"), 0, self.err)
        argv = ["approve", "v1", "3", "--expect", h3, "--output", "youtube"]
        self.pend_q(argv, "승인 v1 %s" % h3, q3.replace(line[0], ""))
        self.assertEqual(self.state(*argv), 6)
        self.assertIn("gate-lines-not-shown", self.err)
        self.pend_q(argv, "승인 v1 %s" % h3, q3)
        self.assertEqual(self.state(*argv), 0, self.err)
        st = store.read_state(self.vdir)
        self.assertEqual(st["langs"]["ko"]["approved"]["3"]["youtube"]["captures"],
                         {CAP: {"png_sha": rec["png_sha"], "floor": "public/-"}})

    def test_shot_again_asks_the_credit_again(self):
        self.shot()
        self.use()
        self.assertEqual(self.credit_capture(), 0, self.err)
        self.assertEqual(self.check_board(), 0, self.out)
        first = json.load(open(os.path.join(self.vdir, "work", "captures.json")))["shots"]["hero"]["at"]
        while schema.now() == first:  # the record's time has whole seconds: the next shot must be later
            time.sleep(0.2)
        # the same name taken again: other bytes (a new sha) and a new time
        self.captures({"*": {"png_hex": png(5, 5).hex()}})
        self.shot()
        self.assertEqual(self.check_board(), 1)
        self.assertIn("not the one its CREDITS entry was approved for", self.out)
        self.assertIn("its CREDITS entry is not of this capture", self.out)
        self.assertEqual(self.credit_capture(), 0, self.err)
        self.assertEqual(self.check_board(), 0, self.out)
        # same bytes, a later time: still asked again (the record's time is in the entry)
        rec = json.load(open(os.path.join(self.vdir, "work", "captures.json")))["shots"]["hero"]
        while schema.now() == rec["at"]:
            time.sleep(0.2)
        self.shot()
        self.assertEqual(self.check_board(), 1)
        self.assertIn("its CREDITS entry is not of this capture", self.out)
        self.assertNotIn("not the one its CREDITS entry was approved for", self.out)

    def test_draft_cannot_give_other_source(self):
        self.shot()
        self.use()
        self.credit_draft(path=CAP, source="https://example.com/other")
        self.assertEqual(self.preview(CAP)[0], 1)
        self.assertIn("source is the capture's own", self.err)
        self.credit_draft(path=CAP, source="https://example.com/a")  # the same value may be copied
        self.assertEqual(self.preview(CAP)[0], 0, self.err)
        self.credit_draft(path=CAP, floor="third-party/x")
        self.assertEqual(self.preview(CAP)[0], 1)
        self.assertIn("floor must be the image's floor public/-", self.err)

    def test_third_party_page(self):
        self.shot(url="https://docs.thirdparty.net/x")
        self.use()
        self.credit_draft(path=CAP, floor="third-party/a page of another host (docs.thirdparty.net)",
                          public_ok=False)
        self.assertEqual(self.credit(path=CAP), 0, self.err)
        self.assertEqual(self.check_board(), 1)
        self.assertIn("is third-party: a public video needs public_ok: true", self.out)

    def test_idle_false_warning_in_the_question(self):
        self.captures({"*": {"idle": False, "blocked": [{"url": "https://cdn.other.net/a.js", "reason": "x"}]}})
        self.shot()
        self.use()
        self.assertEqual(self.credit_capture(), 0, self.err)
        self.assertEqual(self.check_board(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "board", "--output", "youtube"), 0, self.err)
        self.snapshot()
        q = self.question()
        self.assertIn("경고: 페이지가 다 그려지기 전에 찍혔을 수 있음 · 막힌 요청의 호스트 1개", q)

    def test_shot_again_after_shown(self):
        self.shot()
        self.use()
        self.assertEqual(self.credit_capture(), 0, self.err)
        self.assertEqual(self.check_board(), 0, self.out)
        self.assertEqual(self.state("stage-done", "v1", "board", "--output", "youtube"), 0, self.err)
        h3 = self.snapshot()
        q3 = self.question()
        self.assertEqual(self.state("stage-done", "v1", "visual-check", "--output", "youtube"), 0, self.err)
        self.captures({"*": {"png_hex": png(6, 6).hex()}})
        self.shot()  # capture.py runs without a prompt: the approval must not take the new picture
        argv = ["approve", "v1", "3", "--expect", h3, "--output", "youtube"]
        self.pend_q(argv, "승인 v1 %s" % h3, q3)
        self.assertNotEqual(self.state(*argv), 0)
        self.assertIn("cannot be approved yet: the work is at board", self.err)  # the picture's bytes: presentation
        self.assertNotIn("3", store.read_state(self.vdir)["langs"]["ko"]["approved"])

    def test_not_usable_files(self):
        self.shot()
        self.use()
        self.assertEqual(self.credit_capture(), 0, self.err)
        p = os.path.join(self.vdir, *CAP.split("/"))
        with open(p, "ab") as f:  # stands in for a hand edit or a run cut short after the picture
            f.write(b"\0")
        self.assertEqual(shots.usable(self.vdir), set())
        self.assertEqual(self.check_board(), 1)
        self.assertIn("the board capture hero is not usable (%s is not the picture capture.py recorded) — run "
                      "capture.py shot v1 hero again" % CAP, self.out)
        # a run that is not usable removes the picture: the board says so
        self.captures({"*": {"exit": 1, "stderr": "the page answered 404"}})
        self.assertEqual(self.cap("shot", "v1", "hero", "--url", "https://example.com/a"), 1)
        self.assertEqual(self.check_board(), 1)
        self.assertIn("its last run was not usable (the page answered 404)", self.out)
        self.assertFalse(os.path.exists(p))

    def test_internal_capture_refused_in_a_public_video(self):
        self.captures({"*": {"text": [{"kind": "paragraph", "text": "the Bluebird plan"}]}})
        self.shot()
        self.use()
        self.credit_draft(path=CAP)
        self.assertEqual(self.credit(path=CAP), 0, self.err)
        make_harness.write_overlay(self.repo, {"internal": {"terms": ["Bluebird"]}})
        st = store.read_state(self.vdir)
        got = board.picture_problems(self.repo, self.vdir, st, {"files": [{"path": CAP, "kind": "image"}]})
        self.assertEqual(got, ["%s is an internal picture (the page names an in-house term): a public video cannot "
                               "show it" % CAP])
        # the overlay missing: a public video's captures are not usable (closed side)
        os.remove(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"))
        got = board.picture_problems(self.repo, self.vdir, st, {"files": [{"path": CAP, "kind": "image"}]})
        self.assertIn("internal overlay is missing", " ".join(got))

    def test_floor_stale_after_settings_change(self):
        # review 1 MAJOR 2: the floor is judged now — a host that left public_domains asks the credit again
        self.shot()
        self.use()
        self.assertEqual(self.credit_capture(), 0, self.err)
        st = store.read_state(self.vdir)
        files = {"files": [{"path": CAP, "kind": "image"}]}
        self.assertEqual(board.picture_problems(self.repo, self.vdir, st, files), [])
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        cfg = json.load(open(p))
        cfg["public_domains"] = ["other.org"]
        with open(p, "w") as f:
            json.dump(cfg, f)
        got = " ".join(board.picture_problems(self.repo, self.vdir, st, files))
        self.assertIn("its CREDITS entry's floor public/- is not the capture's floor now (third-party/a page of "
                      "another host (example.com)) — credit-preview, ask, credit", got)

    def test_inputs_follow_captures(self):
        from stdo.state import stagechecks
        from stdo.state import cli as scli
        ctx = scli._ctx(self.repo, scli._cfg_of(self.repo), self.vdir, "ko")
        st = store.read_state(self.vdir)
        inp = stagechecks.Inputs(ctx, st, "ko", "youtube", {}, self.providers)
        before = stagechecks.inputs("board", inp)
        self.assertFalse([n for n, _v in before if "captures" in n or "public_domains" in n])  # none: as before
        self.shot()
        names = [n for n, _v in stagechecks.inputs("board", inp)]
        self.assertIn("config:public_domains", names)
        self.assertTrue([n for n in names if n.endswith("work/captures.json")], names)


class CaptureCommit(CaptureFlow, CommitCase):
    """A video whose board shows a capture, through ④b to the commit."""

    def to_board(self):
        self.capture_board()
        self.shot(name="unused", url="https://example.com/b")  # taken, never shown

    def approve_scoped(self, gate, h, *scope, code=0):
        if gate != "3":
            return CommitCase.approve_scoped(self, gate, h, *scope, code=code)
        from stdo.state import gates
        lines = gates.gate3_lines(store.read_state(self.vdir), "ko")
        self.assertTrue(lines)
        argv = ["approve", "v1", gate, "--expect", h] + list(scope)
        self.pend_q(argv, "승인 v1 %s" % h, "\n".join(lines))
        self.assertEqual(self.state(*argv), code, self.err)

    def test_commit_stages_only_used_pictures(self):
        self.assertEqual(self.cc("--stage", "video", "v1"), 0, self.err + self.out)
        staged = self.staged()
        self.assertIn("studio/videos/v1/%s" % CAP, staged)
        self.assertNotIn("studio/videos/v1/assets/capture-unused.png", staged)
        self.assertFalse([p for p in staged if "/work/" in p], staged)
        rec = store.read_state(self.vdir)["langs"]["ko"]["approved"]["3"]["youtube"]
        self.assertEqual(set(rec["captures"]), {CAP})

    def test_commit_refuses_a_capture_other_than_approved(self):
        # the ③ record's binding: a picture whose bytes ③ did not approve is refused even when nothing else tells
        st = store.read_state(self.vdir)
        sha = st["langs"]["ko"]["approved"]["3"]["youtube"]["captures"][CAP]["png_sha"]
        p = os.path.join(self.vdir, "work", "captures.json")
        data = json.load(open(p))
        self.assertEqual(data["shots"]["hero"]["png_sha"], sha)
        from stdo.commit import video as video_kind
        from stdo.capture import shots as shots_mod
        real = shots_mod.bound
        try:
            shots_mod.bound = lambda pics, files: {CAP: {"png_sha": hashlib.sha256(b"other").hexdigest(),
                                                         "floor": "public/-"}}
            self.assertNotEqual(self.cc("--stage", "video", "v1"), 0)
        finally:
            shots_mod.bound = real
        self.assertIn("a board capture is not the picture ③ approved", self.out + self.err)
        self.assertTrue(video_kind)

    def test_clean_filter(self):
        # review 1 MAJOR 1: with a clean filter (git-lfs) the index holds a pointer, not the picture's bytes
        with open(os.path.join(self.repo, ".gitattributes"), "a") as f:
            f.write("*.png filter=fakelfs\n")
        helpers.git(self.repo, "add", ".gitattributes")
        helpers.git(self.repo, "commit", "-q", "--no-verify", "-m", "attrs")
        helpers.git(self.repo, "config", "filter.fakelfs.clean",
                    "python3 -B -c \"import hashlib, sys; d = sys.stdin.buffer.read(); sys.stdout.write("
                    "'version https://git-lfs.github.com/spec/v1\\noid sha256:%s\\nsize %d\\n' % "
                    "(hashlib.sha256(d).hexdigest(), len(d)))\"")
        helpers.git(self.repo, "config", "filter.fakelfs.smudge", "cat")
        self.assertEqual(self.cc("--stage", "video", "v1"), 0, self.out + self.err)
        self.assertIn("studio/videos/v1/%s" % CAP, self.staged())
        blob = subprocess.run(["git", "-C", self.repo, "cat-file", "-p", ":studio/videos/v1/%s" % CAP],
                              capture_output=True).stdout
        self.assertTrue(blob.startswith(b"version https://git-lfs.github.com/spec/v1"), blob[:40])

    def test_floor_changed_after_three(self):
        # review 1 MAJOR 2: ③ bound the floor too — a settings change that moves it is refused at the commit
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        cfg = json.load(open(p))
        cfg["public_domains"] = ["other.org"]
        with open(p, "w") as f:
            json.dump(cfg, f)
        self.assertNotEqual(self.cc("--stage", "video", "v1"), 0)
        self.assertIn("a board capture is not the picture ③ approved", self.out + self.err)
        self.assertIn("is not the capture's floor now", self.out + self.err)

    def test_picture_changed_while_staging(self):
        # capture.py runs without a prompt: a shot taken between the checks and `git add` is not staged as approved
        from stdo.commit import video as video_kind
        real = video_kind.VideoKind.collect
        p = os.path.join(self.vdir, *CAP.split("/"))

        def racing(kind, ctx, target):
            col = real(kind, ctx, target)
            with open(p, "wb") as f:
                f.write(png(7, 7))
            return col
        try:
            video_kind.VideoKind.collect = racing
            self.assertNotEqual(self.cc("--stage", "video", "v1"), 0)
        finally:
            video_kind.VideoKind.collect = real
        self.assertIn("changed while it was staged", self.out + self.err)
        self.assertEqual(self.staged(), [])
