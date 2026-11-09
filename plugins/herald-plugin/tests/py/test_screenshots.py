"""Screenshots a human takes (design/herald/06-screenshots.md, 0.15.0): manifest checks, the
allowlist sanitizer, plan/import/stage pass, retakes, holds, the gate's pending screenshots,
publish's one-commit squash and scope, scan/strip."""

import json
import os
import struct
import time
import unittest
import zlib

from helpers import RepoCase, sh

from hrdlib import shots, store

TID, SLUG = "t0001", "new-post"
IMG = "public/blog-images/%s" % SLUG
W = ".claude/herald/work/%s" % TID
BODY = """---
title: New
description: d
slug: new-post
date: 2026-11-01
category: guide
---
Open the settings page. ![Settings](/blog-images/new-post/s1-settings.png)

Then the token page. ![Token](/blog-images/new-post/s2-token.png)
"""


def png_chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


def png(extra=(), tail=b"", pixel=b"\x00\x00\x00\x00"):
    """A 1x1 PNG with `extra` chunks inserted after IHDR and bytes after IEND."""
    ihdr = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    idat = png_chunk(b"IDAT", zlib.compress(b"\x00" + pixel))
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"".join(png_chunk(t, d) for t, d in extra) + idat + png_chunk(b"IEND", b"") + tail


def seg(m, data):
    return bytes([0xFF, m]) + struct.pack(">H", len(data) + 2) + data


def jpeg_dirty():
    base = shots._PLACEHOLDER["jpg"]
    jfif_thumb = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x01\x01" + b"\x10\x20\x30"  # a 1x1 thumbnail
    head = seg(0xE0, jfif_thumb) + seg(0xE0, b"JFXX\x00\x10thumb") + seg(0xE1, b"Exif\x00\x00GPS-HERE") \
        + seg(0xE2, b"ICC_PROFILE\x00\x01\x01profile") + seg(0xE2, b"MPF\x00secondary") \
        + seg(0xEB, b"JP\x00c2pa") + seg(0xFE, b"comment: alice@example.com")
    rest = base[2:]
    rest = rest[rest.index(b"\xff\xdb"):]  # drop the placeholder's own APP0
    return b"\xff\xd8" + head + rest + b"TRAILING-SECRET"


def webp(chunks, flags=0):
    vp8x = b"VP8X" + struct.pack("<I", 10) + bytes([flags, 0, 0, 0]) + (0).to_bytes(3, "little") * 2
    body = b"WEBP" + vp8x + b"".join(t + struct.pack("<I", len(d)) + d + (b"\x00" if len(d) & 1 else b"")
                                     for t, d in chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


class SanitizeTests(unittest.TestCase):
    def test_png_keeps_only_the_picture(self):
        dirty = png(extra=[(b"tEXt", b"Author\x00alice"), (b"eXIf", b"GPS"), (b"iCCP", b"P3\x00\x00x"),
                           (b"caBX", b"c2pa"), (b"pHYs", b"\x00" * 9)], tail=b"SECRET")
        clean, warn = shots.sanitize(dirty, "png")
        for bad in (b"tEXt", b"alice", b"eXIf", b"iCCP", b"caBX", b"SECRET"):
            self.assertNotIn(bad, clean)
        self.assertIn(b"pHYs", clean)
        self.assertIn(zlib.compress(b"\x00\x00\x00\x00\x00"), clean)  # the image data, byte for byte
        self.assertTrue(warn)  # the colour profile went
        self.assertIsNone(shots.dirty(clean, "png"))
        self.assertTrue(shots.dirty(dirty, "png"))

    def test_jpeg_allowlist_and_thumbnails(self):
        clean, _ = shots.sanitize(jpeg_dirty(), "jpg")
        for bad in (b"Exif", b"GPS-HERE", b"ICC_PROFILE", b"MPF", b"c2pa", b"alice", b"JFXX", b"TRAILING", b"\x10\x20\x30"):
            self.assertNotIn(bad, clean)
        app0 = clean.index(b"JFIF")
        self.assertEqual(clean[app0 + 12:app0 + 14], b"\x00\x00")  # thumbnail cut to 0x0
        self.assertTrue(clean.endswith(b"\xff\xd9"))
        self.assertIsNone(shots.dirty(clean, "jpeg"))

    def test_webp_chunks_and_flags(self):
        dirty = webp([(b"ICCP", b"profile"), (b"VP8L", b"\x2f" + b"\x00" * 12), (b"EXIF", b"GPS"), (b"XMP ", b"<x/>")],
                     flags=0x20 | 0x08 | 0x04)
        clean, _ = shots.sanitize(dirty, "webp")
        for bad in (b"ICCP", b"EXIF", b"XMP ", b"GPS"):
            self.assertNotIn(bad, clean)
        self.assertEqual(clean[20] & (0x20 | 0x08 | 0x04), 0)
        self.assertEqual(struct.unpack("<I", clean[4:8])[0], len(clean) - 8)
        with self.assertRaises(Exception):
            shots.sanitize(webp([(b"ANIM", b"\x00" * 6)]), "webp")

    def test_kind_and_extension_must_agree(self):
        with self.assertRaises(Exception):
            shots.sanitize(png(), "jpg")
        with self.assertRaises(Exception):
            shots.sanitize(b"GIF89a....", "png")
        with self.assertRaises(Exception):
            shots.sanitize(png()[:-12], "png")  # no IEND


class ShotCase(RepoCase):
    def setUp(self):
        super().setUp()
        store.save_topics(self.root, {"version": 1, "topics": [
            {"id": TID, "title": "New", "state": "queued", "history": [], "reverted_by": []}]})
        with open(os.path.join(self.root, ".gitignore"), "a") as f:
            f.write(".claude/herald/inbox/\n")  # templates/gitignore.tmpl
        self.commit("topics")
        sh(self.root, "git", "push", "-q", "origin", "main")
        sh(self.root, "git", "switch", "-q", "-c", store.branch_name(TID, SLUG))
        self.write(W + "/brief.md", "brief\n")
        self.write(W + "/research.md", "**C1.** a claim\n")
        st = store.new_state(TID, SLUG)
        st["stage"] = "draft"
        st["stages"] = {"brief": {"outputs": {"brief.md": store.artifact_hash(self.root, self.cfg, st, "brief.md")}},
                        "research": {"outputs": {"research.md": store.artifact_hash(self.root, self.cfg, st, "research.md")}}}
        store.save_state(self.root, TID, st)
        self.write("src/content/blog/%s.md" % SLUG, BODY)
        self.write(W + "/claims-map.json", json.dumps({"sentences": []}))
        self.manifest()

    def shot(self, sid, name, **kw):
        s = {"id": sid, "file": "%s/%s" % (IMG, name), "ref": "/blog-images/%s/%s" % (SLUG, name), "alt": "x",
             "purpose": "p", "how": [{"step": "open it", "source": "https://docs.example.test/"}],
             "spec": {"viewport": "1280x800"}}
        s.update(kw)
        return s

    def manifest(self, shots_=None):
        if shots_ is None:
            shots_ = [self.shot("s1", "s1-settings.png"), self.shot("s2", "s2-token.png", url="https://app.test/t")]
        self.write(W + "/screenshots.json", json.dumps({"shots": shots_}))

    def state(self):
        return store.load_state(self.root, TID)

    def drop(self, sid, data=None, ext="png", age=0):
        p = os.path.join(self.root, ".claude/herald/inbox", TID, "%s.%s" % (sid, ext))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if data is not None else png(extra=[(b"tEXt", b"k\x00v")]))
        if age:
            t = time.time() - age
            os.utime(p, (t, t))
        return p

    def removed(self):
        out = []
        for dp, _, fns in os.walk(os.path.join(self.root, ".claude/herald/memory/shots/removed")):
            out += fns
        return out


class PlanTests(ShotCase):
    def test_checks(self):
        bad = [self.shot("x1", "s1-settings.png"), self.shot("s2", "s2-token.png", how=[]),
               self.shot("s3", "../s3.png"), self.shot("s4", "s4.gif"),
               self.shot("s5", "s5.png", spec={"viewport": "big"})]
        self.manifest(bad)
        _, p = self.hrd("shot", "plan", "--topic", TID, "--check", check=False)
        for msg in ("s1..s999", "how must list", "directly under", "extension", "viewport", "exactly once"):
            self.assertIn(msg, p.stderr)
        self.assertNotIn("screenshots", self.state())  # --check writes nothing

    def test_ref_must_resolve_and_base_file_refused(self):
        self.manifest([self.shot("s1", "s1-settings.png", ref="/blog-images/other/s1-settings.png"),
                       self.shot("s2", "s2-token.png")])
        _, p = self.hrd("shot", "plan", "--topic", TID, check=False)
        self.assertIn("does not resolve", p.stderr)
        # a file already on base is never overwritten (P6)
        sh(self.root, "git", "switch", "-q", "main")
        self.write(IMG + "/s2-token.png", png(), binary=True)
        self.commit("base image", IMG + "/s2-token.png")
        sh(self.root, "git", "push", "-q", "origin", "main")
        sh(self.root, "git", "switch", "-q", store.branch_name(TID, SLUG))
        self.manifest()
        _, p = self.hrd("shot", "plan", "--topic", TID, check=False)
        self.assertIn("already exists on main", p.stderr)

    def test_inherit_and_move(self):
        out = self.hrd("shot", "plan", "--topic", TID)[0]
        self.assertEqual(out["pending"], ["s1", "s2"])
        self.drop("s1")
        self.drop("s2")
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertEqual(out["imported"], ["s1", "s2"])
        # wording only: still ready; a viewport change: pending again
        self.manifest([self.shot("s1", "s1-settings.png", alt="new words", how=[{"step": "other words"}]),
                       self.shot("s2", "s2-token.png", url="https://app.test/t", spec={"viewport": "1440x900"})])
        out = self.hrd("shot", "plan", "--topic", TID)[0]
        self.assertEqual(out["pending"], ["s2"])
        self.assertTrue(self.state()["screenshots"]["awaiting"])
        # s2 leaves the manifest (and the body): its file is moved, never deleted
        self.write("src/content/blog/%s.md" % SLUG, BODY.split("\n\nThen")[0] + "\n")
        self.manifest([self.shot("s1", "s1-settings.png")])
        self.hrd("shot", "plan", "--topic", TID)
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "s2-token.png")))
        self.assertIn("s2-token.png", self.removed())

    def test_manifest_gone_moves_everything_and_keeps_record(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        self.hrd("shot", "import", "--topic", TID)
        os.remove(os.path.join(self.root, W, "screenshots.json"))
        self.hrd("shot", "plan", "--topic", TID)
        st = self.state()
        self.assertNotIn("screenshots", st)
        self.assertIn("%s/s1-settings.png" % IMG, st["shot_files"])
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "s1-settings.png")))


class ImportAndPassTests(ShotCase):
    def test_import_rules(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1", age=3600)  # made before s1 started waiting
        self.drop("s2", data=png(), ext="jpg")
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertEqual(out["imported"], [])
        self.assertTrue(any("before s1 started waiting" in p for p in out["problems"]))
        self.assertTrue(any("wrong extension" in p for p in out["problems"]))
        self.assertEqual(out["note"], "screenshots: s1 s2")
        # body changed since plan: refused
        self.write("src/content/blog/%s.md" % SLUG, BODY + "\nMore.\n")
        _, p = self.hrd("shot", "import", "--topic", TID, check=False)
        self.assertIn("changed since", p.stderr)

    def test_stage_pass_waits_for_every_screenshot(self):
        self.hrd("shot", "plan", "--topic", TID)
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "draft", check=False)
        self.assertIn("still pending", p.stderr)
        self.drop("s1")
        self.drop("s2")
        self.hrd("shot", "import", "--topic", TID)
        with open(os.path.join(self.root, IMG, "s1-settings.png"), "rb") as f:
            self.assertNotIn(b"tEXt", f.read())
        # a swapped-in file is not what import wrote
        good = open(os.path.join(self.root, IMG, "s2-token.png"), "rb").read()
        self.write(IMG + "/s2-token.png", png(extra=[(b"tEXt", b"x\x00y")]), binary=True)
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "draft", check=False)
        self.assertIn("not the file", p.stderr)
        self.write(IMG + "/s2-token.png", good, binary=True)
        self.hrd("stage", "pass", "--topic", TID, "--stage", "draft")
        st = self.state()
        self.assertEqual(st["stage"], "critique")
        self.assertFalse(st["screenshots"]["awaiting"])
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".claude/herald/inbox", TID)))
        self.assertIn("s1.png", self.removed())  # the inbox original is kept, not deleted

    def test_orphan_only_for_recorded_files(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        self.drop("s2")
        self.hrd("shot", "import", "--topic", TID)
        st = self.state()
        st["screenshots"]["files"].append("%s/s9-old.png" % IMG)
        store.save_state(self.root, TID, st)
        self.write(IMG + "/s9-old.png", png(), binary=True)
        self.write(IMG + "/diagram.png", png(), binary=True)  # an illustrator image: never judged
        probs = shots.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertEqual(len(probs), 1)
        self.assertIn("s9-old.png", probs[0])

    def test_no_manifest_is_0_14_0(self):
        os.remove(os.path.join(self.root, W, "screenshots.json"))
        self.assertEqual(shots.draft_problems(self.root, self.cfg, TID, self.state()), [])


class GateTests(ShotCase):
    def test_pending_screenshots_are_not_the_writers_errors(self):
        rep, p = self.hrd("gate", "--topic", TID, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(sorted(rep["pending_shots"]), ["%s/s1-settings.png" % IMG, "%s/s2-token.png" % IMG])
        _, p = self.hrd("gate", "--topic", TID, "--slug", SLUG, check=False)  # never relaxed
        self.assertNotEqual(p.returncode, 0)
        sh(self.root, "git", "switch", "-q", "main")  # not the topic's branch
        _, p = self.hrd("gate", "--topic", TID, check=False)
        self.assertNotEqual(p.returncode, 0)

    def test_custom_validator_gets_stand_ins_then_they_go(self):
        cfg = json.load(open(os.path.join(self.root, ".claude/herald/config.json")))
        cfg["commands"]["validate"] = 'sh -c "test -f %s/s1-settings.png"' % IMG
        self.write(".claude/herald/config.json", json.dumps(cfg))
        rep, p = self.hrd("gate", "--topic", TID, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "s1-settings.png")))


class RetakeAndDecideTests(ShotCase):
    def ready(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        self.drop("s2")
        self.hrd("shot", "import", "--topic", TID)
        st = self.state()
        st["stage"] = "critique"
        store.save_state(self.root, TID, st)

    def test_retake_moves_records_and_needs_mask(self):
        self.ready()
        out = self.hrd("loopback", "--topic", TID, "--cause", "revise", "--theme", "images", "--retake", "s2",
                       "--retake-kind", "privacy", "--reason", "an account e-mail is visible")[0]
        self.assertEqual(out["retake"], ["s2"])
        st = self.state()
        self.assertEqual(st["screenshots"]["shots"]["s2"]["status"], "pending")
        self.assertFalse(st["screenshots"]["awaiting"])
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "s2-token.png")))
        self.assertEqual(st["retakes"][0]["kind"], "privacy")
        # renaming the id alone does not escape: same url → same subject, mask required
        self.manifest([self.shot("s1", "s1-settings.png"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])
        _, p = self.hrd("shot", "plan", "--topic", TID, check=False)
        self.assertIn("mask must name", p.stderr)
        self.manifest([self.shot("s1", "s1-settings.png"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t", mask=["account e-mail"])])
        self.hrd("shot", "plan", "--topic", TID)
        status = self.hrd("shot", "status", "--topic", TID)[0]
        self.assertEqual(status["note"], "screenshots: s2(retake:privacy)")
        self.assertEqual(status["shots"][1]["retake"]["reason"], "an account e-mail is visible")
        self.assertTrue(status["resume_at_import"])

    def test_url_less_shots_do_not_share_a_subject(self):
        self.ready()
        self.hrd("loopback", "--topic", TID, "--cause", "revise", "--theme", "images", "--retake", "s1",
                 "--retake-kind", "privacy", "--reason", "r")
        st = self.state()
        man = shots.load_manifest(self.root, TID)
        self.assertTrue(shots.retakes_for(st, man["shots"][0]))
        self.assertFalse(shots.retakes_for(st, man["shots"][1]))

    def test_past_the_cap_skips_and_unattended_human_refused(self):
        self.ready()
        st = self.state()
        st["loopbacks"] = 3
        store.save_state(self.root, TID, st)
        out = self.hrd("loopback", "--topic", TID, "--cause", "revise", "--theme", "images", "--retake", "s1",
                       "--retake-kind", "mismatch")[0]
        self.assertEqual(out["retake"], "skipped")
        self.assertTrue(os.path.exists(os.path.join(self.root, IMG, "s1-settings.png")))
        _, p = self.hrd("loopback", "--topic", TID, "--human", "--retake", "s1", "--retake-kind", "mismatch",
                        check=False, env={"HRD_UNATTENDED": "1"})
        self.assertIn("unattended", p.stderr)
        out = self.hrd("loopback", "--topic", TID, "--human", "--retake", "s1", "--retake-kind", "mismatch")[0]
        self.assertEqual(out["retake"], ["s1"])  # a human may still retake past the cap

    def test_decide_without(self):
        self.ready()
        _, p = self.hrd("shot", "decide", "--topic", TID, "--id", "s1", "--without", check=False,
                        env={"HRD_UNATTENDED": "1"})
        self.assertIn("unattended", p.stderr)
        self.hrd("shot", "decide", "--topic", TID, "--id", "s1", "--without")
        self.assertEqual(self.state()["shot_decisions"][0]["id"], "shot:s1")


class HoldTests(ShotCase):
    def test_note_and_signal(self):
        _, p = self.hrd("result", "--topic", TID, "--status", "held:screenshots", "--note", "waiting for the token page",
                        check=False)
        self.assertIn("ids and kind codes only", p.stderr)
        self.hrd("result", "--topic", TID, "--status", "held:screenshots", "--note", "screenshots: s1 s2(retake:privacy)")
        self.assertFalse(store.hold_is_signal("screenshots", "screenshots: s1"))
        self.assertTrue(store.hold_is_signal("needs-human", "defect: x"))
        self.assertIn("screenshots", store.PRESERVE_REASONS)

    def test_archive_inbox_moves(self):
        self.drop("s1")
        shots.archive_inbox(self.root, TID, "requeue")
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".claude/herald/inbox", TID)))
        self.assertIn("s1.png", self.removed())


class PublishTests(ShotCase):
    def published_branch(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        self.drop("s2", data=png(extra=[(b"tEXt", b"first\x00take")], pixel=b"\xff\x00\x00\xff"))
        self.hrd("shot", "import", "--topic", TID)
        self.commit("wip(herald): t0001")  # a WIP commit holds the screens before critique
        # retake s2: the first take must not reach the remote
        st = self.state()
        st["stage"] = "critique"
        store.save_state(self.root, TID, st)
        self.hrd("loopback", "--topic", TID, "--human", "--retake", "s2", "--retake-kind", "privacy", "--reason", "r")
        self.manifest([self.shot("s1", "s1-settings.png"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t", mask=["token"])])
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s2", data=png())
        self.hrd("shot", "import", "--topic", TID)
        sh(self.root, "git", "add", "-A", "--", W, IMG, "src/content/blog/%s.md" % SLUG)

    def test_squash_one_commit_and_scope(self):
        self.published_branch()
        self.commit("feat(herald): publish")
        _, p = self.hrd("scope", "--topic", TID, check=False)
        self.assertIn("not one commit", p.stdout)
        out = self.hrd("shot", "squash", "--topic", TID)[0]
        self.assertTrue(out["squashed"])
        self.hrd("scope", "--topic", TID)
        base = sh(self.root, "git", "merge-base", "HEAD", "origin/main").strip()
        self.assertEqual(sh(self.root, "git", "rev-parse", "HEAD^").strip(), base)
        first_take = png(extra=[(b"tEXt", b"first\x00take")], pixel=b"\xff\x00\x00\xff")
        objs = sh(self.root, "git", "rev-list", "--objects", "origin/main..HEAD")
        cleaned_first, _ = shots.sanitize(first_take, "png")
        p = os.path.join(self.tmp, "first.png")
        open(p, "wb").write(cleaned_first)
        first_blob = sh(self.root, "git", "hash-object", p).strip()
        self.assertNotIn(first_blob, objs)
        # pushed, then a retry with nothing new: no empty commit
        sh(self.root, "git", "push", "-q", "-u", "origin", store.branch_name(TID, SLUG))
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        out = self.hrd("shot", "squash", "--topic", TID)[0]
        self.assertIsNone(out["commit"])
        self.assertEqual(sh(self.root, "git", "rev-parse", "HEAD").strip(), head)
        self.hrd("scope", "--topic", TID)

    def test_squash_refuses_off_branch_and_out_of_scope(self):
        self.published_branch()
        self.write("README.md", "stray\n")
        sh(self.root, "git", "add", "README.md")
        _, p = self.hrd("shot", "squash", "--topic", TID, check=False)
        self.assertIn("outside this topic's PR scope", p.stderr)
        sh(self.root, "git", "reset", "-q", "--", "README.md")
        sh(self.root, "git", "switch", "-q", "--detach")
        _, p = self.hrd("shot", "squash", "--topic", TID, check=False)
        self.assertIn("squash runs on", p.stderr)

    def test_exclusion_is_not_consentable(self):
        self.published_branch()
        self.assertTrue(shots.excluded(self.root, self.cfg, TID, None, []))
        self.assertNotIn("screenshots", store.CONSENT_ACCEPTS)
        self.assertEqual(store.blocking_exclusions(["screenshots"], consent=True), ["screenshots"])


class ScanTests(ShotCase):
    def test_scan_and_strip_recorded_files_only(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        self.drop("s2")
        self.hrd("shot", "import", "--topic", TID)
        out, p = self.hrd("shot", "scan", "--slug", SLUG)
        self.assertEqual(out["found"], [])
        self.write(IMG + "/s1-settings.png", png(extra=[(b"tEXt", b"GPS\x00here")]), binary=True)  # a human swapped it
        self.write(IMG + "/diagram.png", png(extra=[(b"tEXt", b"Software\x00tool")]), binary=True)  # not a screenshot
        out, p = self.hrd("shot", "scan", "--slug", SLUG, check=False)
        self.assertEqual([f["file"] for f in out["found"]], ["%s/s1-settings.png" % IMG])
        self.hrd("shot", "strip", "--path", "%s/s1-settings.png" % IMG)
        self.assertEqual(self.hrd("shot", "scan", "--slug", SLUG)[0]["found"], [])

    def test_moved_slug_paths(self):
        from hrdlib.integrity import moved_image_path
        self.assertEqual(moved_image_path(self.cfg, "c", "public/blog-images/a/s1.png", ["a", "b"]),
                         "public/blog-images/c/s1.png")
        self.assertEqual(moved_image_path(self.cfg, "c", "public/blog-images/x/s1.png", ["a", "b"]),
                         "public/blog-images/x/s1.png")


class ReviewRound1Tests(ShotCase):
    """Implementation review round 1 (06-screenshots.md §4 gaps)."""
    published_branch = PublishTests.published_branch

    def test_duplicates_and_empty_images_refused(self):
        self.manifest([self.shot("s1", "s1-settings.png"), self.shot("s2", "s1-settings.png")])
        _, p = self.hrd("shot", "plan", "--topic", TID, "--check", check=False)
        self.assertIn("already uses this file or ref", p.stderr)
        no_idat = png().replace(png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")), b"")
        with self.assertRaises(Exception):
            shots.sanitize(no_idat, "png")

    def test_malformed_manifest_at_a_rev_raises(self):
        self.write(W + "/screenshots.json", "{not json")
        self.commit("bad manifest")
        with self.assertRaises(Exception):
            shots.load_manifest(self.root, TID, rev="HEAD")
        self.assertIsNone(shots.load_manifest(self.root, TID, rev="origin/main"))

    def test_waiting_since_kept_and_size_cap(self):
        self.hrd("shot", "plan", "--topic", TID)
        since = self.state()["screenshots"]["shots"]["s2"]["waiting_since"]
        self.manifest([self.shot("s1", "s1-settings.png", alt="reworded"),
                       self.shot("s2", "s2-token.png", url="https://app.test/t")])
        self.hrd("shot", "plan", "--topic", TID)
        self.assertEqual(self.state()["screenshots"]["shots"]["s2"]["waiting_since"], since)
        self.drop("s1", data=png(tail=b"\x00" * (shots.MAX_BYTES + 1)))
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertTrue(any("10 MB" in x for x in out["problems"]))

    def test_resume_at_import_only_between_plan_and_pass(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.assertTrue(self.hrd("shot", "status", "--topic", TID)[0]["resume_at_import"])
        st = self.state()
        st["stage"] = "critique"
        store.save_state(self.root, TID, st)
        self.hrd("loopback", "--topic", TID, "--cause", "revise", "--theme", "clarity", "--note", "x")
        self.assertFalse(self.hrd("shot", "status", "--topic", TID)[0]["resume_at_import"])

    def test_squash_refusals(self):
        self.published_branch()
        url = sh(self.root, "git", "remote", "get-url", "origin").strip()
        sh(self.root, "git", "remote", "set-url", "origin", os.path.join(self.tmp, "nowhere.git"))
        _, p = self.hrd("shot", "squash", "--topic", TID, check=False)
        self.assertIn("ls-remote", p.stderr)
        sh(self.root, "git", "remote", "set-url", "origin", url)
        self.commit("feat(herald): publish")
        self.hrd("shot", "squash", "--topic", TID)
        branch = store.branch_name(TID, SLUG)
        sh(self.root, "git", "push", "-q", "-u", "origin", branch)
        # base moved and was merged in after the push: one commit on the pushed head would carry it
        sh(self.root, "git", "switch", "-q", "main")
        self.write("src/content/blog/other.md", "x\n")
        self.commit("other", "src/content/blog/other.md")
        sh(self.root, "git", "push", "-q", "origin", "main")
        sh(self.root, "git", "switch", "-q", branch)
        sh(self.root, "git", "merge", "-q", "--no-edit", "origin/main")
        _, p = self.hrd("shot", "squash", "--topic", TID, check=False)
        self.assertIn("merged with main after it was pushed", p.stderr)
        # the pushed head is not this branch's ancestor (history rewritten locally)
        sh(self.root, "git", "reset", "-q", "--hard", "HEAD~1")
        sh(self.root, "git", "commit", "-q", "--amend", "-m", "rewritten")
        _, p = self.hrd("shot", "squash", "--topic", TID, check=False)
        self.assertIn("not part of this branch's history", p.stderr)

    def test_squash_stacks_one_commit_on_a_pushed_head(self):
        self.published_branch()
        self.commit("feat(herald): publish")
        self.hrd("shot", "squash", "--topic", TID)
        branch = store.branch_name(TID, SLUG)
        sh(self.root, "git", "push", "-q", "-u", "origin", branch)
        pushed = sh(self.root, "git", "rev-parse", "HEAD").strip()
        # gh pr create failed; a resume changed the article and left WIP commits
        self.write("src/content/blog/%s.md" % SLUG, BODY + "\nOne more line.\n")
        self.commit("wip(herald): a")
        self.write(W + "/brief.md", "brief v2\n")
        self.commit("wip(herald): b")
        out = self.hrd("shot", "squash", "--topic", TID)[0]
        self.assertEqual(out["onto"], pushed)
        self.assertEqual(sh(self.root, "git", "rev-parse", "HEAD^").strip(), pushed)
        self.hrd("scope", "--topic", TID)
        self.assertGreater(self.hrd("status")[0]["shots_removed_bytes"], 0)

    def test_replacing_an_imported_screenshot(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        self.drop("s2")
        self.hrd("shot", "import", "--topic", TID)
        # a new version in the inbox alone is never silently dropped or taken
        self.drop("s1", data=png(pixel=b"\x10\x20\x30\xff"))
        self.hrd("shot", "plan", "--topic", TID)
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertTrue(any("already imported" in w for w in out["warnings"]))
        # edited in place: plan first (pending), then the inbox, then import
        self.write(IMG + "/s2-token.png", png(pixel=b"\x00\x00\x00\x01"), binary=True)
        self.assertEqual(self.hrd("shot", "plan", "--topic", TID)[0]["pending"], ["s2"])
        time.sleep(0.01)
        self.drop("s2", data=png(pixel=b"\x00\x00\x00\x01"))
        self.assertEqual(self.hrd("shot", "import", "--topic", TID)[0]["imported"], ["s2"])

    def test_split_import_and_inbox_names(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude/herald/inbox", TID, "s1.png")))
        self.assertIn("s1.png", self.removed())  # moved at once, never deleted
        self.drop("s2")
        self.drop("S1", ext="png")
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertEqual(out["imported"], ["s2"])
        self.assertFalse(any("already imported" in w for w in out["warnings"]))  # the second batch is normal
        self.assertTrue(any("S1.png" in w and "did you mean s1" in w for w in out["warnings"]))

    def test_interrupted_import_and_retake_order(self):
        from unittest import mock
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        with mock.patch.object(shots, "move_to_removed", side_effect=RuntimeError("cut")):
            with self.assertRaises(RuntimeError):
                shots.import_(self.root, self.cfg, TID)
        self.assertEqual(self.state()["screenshots"]["shots"]["s1"]["status"], "ready")
        out = self.hrd("shot", "import", "--topic", TID)[0]  # the left-over original: moved, no warning
        self.assertFalse(any("already imported" in w for w in out["warnings"]))
        self.assertIn("s1.png", self.removed())
        # a new version, then the retake the warning asks for, then saved again
        self.drop("s1", data=png(pixel=b"\x01\x02\x03\xff"))
        self.assertTrue(any("already imported" in w for w in self.hrd("shot", "import", "--topic", TID)[0]["warnings"]))
        st = self.state()
        st["stage"] = "critique"
        store.save_state(self.root, TID, st)
        time.sleep(1.1)  # waiting_since has second precision
        self.hrd("loopback", "--topic", TID, "--human", "--retake", "s1", "--retake-kind", "mismatch", "--reason", "r")
        self.hrd("shot", "plan", "--topic", TID)
        out = self.hrd("shot", "import", "--topic", TID)[0]
        self.assertTrue(any("before s1 started waiting" in p for p in out["problems"]))  # older than the retake
        time.sleep(0.01)
        self.drop("s1", data=png(pixel=b"\x01\x02\x03\xff"))
        self.assertEqual(self.hrd("shot", "import", "--topic", TID)[0]["imported"], ["s1"])

    def test_draft_pass_moves_leftover_inbox_files(self):
        self.hrd("shot", "plan", "--topic", TID)
        self.drop("s1")
        self.drop("s2")
        self.hrd("shot", "import", "--topic", TID)
        self.drop("misnamed")
        self.hrd("stage", "pass", "--topic", TID, "--stage", "draft")
        self.assertIn("misnamed.png", self.removed())

    def test_state_hold_note_signal_and_requeue_inbox(self):
        sh(self.root, "git", "switch", "-q", "main")
        _, p = self.hrd("state", "--topic", TID, "--state", "held", "--reason", "screenshots", "--note", "free text",
                        check=False)
        self.assertIn("ids and kind codes only", p.stderr)
        self.hrd("state", "--topic", TID, "--state", "held", "--reason", "screenshots", "--note", "screenshots: s1")
        sig = os.path.join(self.root, ".claude/herald/signals.jsonl")
        self.assertFalse(os.path.exists(sig) and '"hold"' in open(sig).read())
        from hrdlib import batch
        batch.record_hold(self.root, self.cfg, TID, "screenshots", "screenshots: s1 s2")
        self.assertFalse(os.path.exists(sig) and '"hold"' in open(sig).read())
        self.drop("s1")
        self.hrd("requeue", "--topic", TID)
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".claude/herald/inbox", TID)))
        self.assertIn("s1.png", self.removed())

    def test_exclusion_at_a_pr_head(self):
        self.published_branch()
        self.write(W + "/critique.json", "{}")  # a real PR head carries the verdict files
        self.commit("feat(herald): publish")
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        sh(self.root, "git", "switch", "-q", "main")
        self.assertIn("screenshots", store.exclusion_reasons(self.root, self.cfg, TID, rev=head))

    def test_scope_rev_lets_a_human_push_through(self):
        self.published_branch()
        self.commit("feat(herald): publish")
        self.hrd("shot", "squash", "--topic", TID)
        branch = store.branch_name(TID, SLUG)
        sh(self.root, "git", "push", "-q", "-u", "origin", branch)
        self.write("src/content/blog/%s.md" % SLUG, BODY + "\nA human line.\n")
        self.commit("human edit", "src/content/blog/%s.md" % SLUG)
        head = sh(self.root, "git", "rev-parse", "HEAD").strip()
        out, p = self.hrd("scope", "--topic", TID, "--rev", head, check=False)
        self.assertNotIn("screenshots", out or {}, p.stdout)


if __name__ == "__main__":
    unittest.main()
