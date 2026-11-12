"""Scene images limner generates (design/herald/09-scenes.md, 0.18.0): `kinds.scene`, the
manifest's `g` items and their key, `HRD image generate` against a fake `lmn` (run/status/cancel
with limner's real records and exit codes — never the real engine unless HRD_TEST_LIMNER_GENERATE),
record checks, the generation ledger and rule U, confirm/reject/review, the AI label (per topic and
per slug, outside `run_gate`), translation repos, publishing, holds, the guard and cancel/trial.
A repo without `images.scenes` behaves as 0.17.0 (test_images, test_screenshots, test_auto_capture
run unchanged)."""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from helpers import HERE, SCRIPTS, sh
from test_images import IMG, SLUG, TID, W, ImageCase

from hrdlib import images, limner, shots, store
from hrdlib.config import Config

STYLE = "Flat vector illustration, soft pastel colors."
P1 = "A traveler at an airport immigration counter handing a passport to an officer behind a glass booth"
P2 = "Two friends reading a train timetable on a station platform, seen from the side"
LABEL = "AI-generated image"
BODY = """---
title: Renewal guide
description: How to renew
slug: new-post
date: 2026-11-01
category: guide
---
At the counter you say a few words.

{g1}

On the platform you read the board.

{g2}

That is all.
"""


def ref(gid, name):
    return "/blog-images/%s/%s-%s.png" % (SLUG, gid, name)


class SceneCase(ImageCase):
    def setUp(self):
        super().setUp()
        for k in ("HRD_TEST_ALLOW_FAKE_GENERATOR", "LIMNER_FAKE_GENERATOR"):
            os.environ.pop(k, None)
        # the scene settings go to base first, so a squash finds config.json outside no PR's scope
        br = store.branch_name(TID, SLUG)
        sh(self.root, "git", "switch", "-q", "main")
        self.config(lambda c: c["images"].update(
            scenes={"max": 2, "style": STYLE, "wait_minutes": 30},
            og={"path": "{images}/{slug}/og.png"}))
        self.commit("scenes", ".claude/herald/config.json")
        sh(self.root, "git", "push", "-q", "origin", "main")
        sh(self.root, "git", "switch", "-q", br)
        sh(self.root, "git", "merge", "-q", "--ff-only", "main")
        self.cfg = Config.load(self.root)
        self.manifest([self.g1(), self.g2()])
        self.scene_body()

    def tearDown(self):
        for k in ("HRD_TEST_ALLOW_FAKE_GENERATOR", "LIMNER_FAKE_GENERATOR"):
            os.environ.pop(k, None)
        super().tearDown()

    def g1(self, **kw):
        g = {"id": "g1", "kind": "scene", "file": "%s/g1-counter.png" % IMG, "ref": ref("g1", "counter"),
             "alt": "A traveler handing a passport at a counter", "purpose": "the counter paragraph",
             "size": "landscape", "seed": 41, "prompt": P1}
        g.update(kw)
        return g

    def g2(self, **kw):
        g = {"id": "g2", "kind": "scene", "file": "%s/g2-platform.png" % IMG, "ref": ref("g2", "platform"),
             "alt": "Two friends reading a timetable", "purpose": "the platform paragraph",
             "size": "square", "seed": 7, "prompt": P2}
        g.update(kw)
        return g

    def snip(self, it):
        return "![%s](%s)\n*%s*" % (it["alt"], it["ref"], LABEL)

    def scene_body(self, g1=None, g2=None):
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(
            g1=g1 if g1 is not None else self.snip(self.g1()), g2=g2 if g2 is not None else self.snip(self.g2())))

    def gen(self, wait=0, env=None):
        with mock.patch.dict(os.environ, env or {}):
            limner.reset_cache()
            return images.generate(self.root, self.cfg, TID, wait=wait)

    def gcalls(self, sub=None):
        return [c for c in self.calls() if c and c[0] in ("run", "status", "cancel") and (sub is None or c[0] == sub)]

    def gen_lines(self):
        return shots.ledger_read(os.path.join(self.root, shots.GENERATIONS))[0]

    def generated(self):
        """g1 and g2 generated: plan, one generate that finishes."""
        self.assertEqual(self.plan()["errors"], [])
        out = self.gen()
        self.assertEqual(out["state"], "done", out)
        return out

    def ready(self):
        self.generated()
        images.confirm(self.root, self.cfg, TID, "g1,g2")
        self.assertEqual(self.plan()["errors"], [])

    def made_og(self):
        self.assertEqual(images.og(self.root, self.cfg, TID)["status"], "made")


class KindsTests(SceneCase):
    def test_codes(self):
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual({x: v for x, v in k["scene"].items() if x not in ("stand_in", "decorative")},  # 0.21 parts
                         {"ok": True, "max": 2, "sizes": ["landscape", "square", "portrait"], "why": None})
        self.assertTrue(k["diagram"]["ok"] and k["external"]["ok"])  # 0.17 kinds as they were
        gen = [c for c in self.calls() if c[0] == "run"]
        self.assertEqual(len(gen), 1)
        self.assertIn("--check", gen[0])
        self.assertEqual([os.path.join(dp, f) for dp, _, fns in os.walk(os.path.join(self.root, ".limner"))
                          for f in fns], [])  # the probe leaves nothing
        for env, want in (({"FAKE_LMN_GEN_ENV": "models are not ready (run `lmn setup`)"}, "generate:env"),
                          ({"LIMNER_FAKE_GENERATOR": "1"}, "generate:fake")):
            with mock.patch.dict(os.environ, env):
                limner.reset_cache()
                self.assertEqual(images.kinds(self.root, self.cfg, TID)["scene"]["why"], want)
        with mock.patch.dict(os.environ, {"LIMNER_FAKE_GENERATOR": "1", "HRD_TEST_ALLOW_FAKE_GENERATOR": "1"}):
            limner.reset_cache()
            self.assertTrue(images.kinds(self.root, self.cfg, TID)["scene"]["ok"])
        with mock.patch.dict(os.environ, {"FAKE_LMN_FONTS": "missing"}):  # scenes need no fonts (Q5)
            limner.reset_cache()
            k = images.kinds(self.root, self.cfg, TID)
            self.assertEqual((k["scene"]["ok"], k["diagram"]["why"]), (True, "limner:fonts"))

    def test_config_reasons(self):
        def why(fn):
            self.config(fn)
            return images.kinds(self.root, self.cfg, TID)["scene"]["why"]
        self.assertEqual(why(lambda c: c["images"]["scenes"].update(per_category={"guide": 0})), "category")
        self.assertEqual(why(lambda c: c["images"]["scenes"].update(per_category={}, max=9)), "config")
        self.assertEqual(why(lambda c: c["images"]["scenes"].update(max=2, style="日本語")), "config")
        self.assertEqual(why(lambda c: c["images"]["scenes"].update(style=STYLE, wait_minutes=1)), "config")
        self.assertEqual(why(lambda c: c["images"]["scenes"].update(wait_minutes=30) or
                             c["images"]["figure"].update(scene="![{alt}]({ref})")), "config")
        self.assertIn("{label}", " ".join(images.scene_errors(self.cfg)))
        self.assertEqual(why(lambda c: c["images"]["figure"].pop("scene") and None or
                             c["images"]["figure"]["words"].update(scene="")), "config")
        self.assertEqual(why(lambda c: c["images"]["figure"]["words"].pop("scene") and None or
                             c["images"].pop("og")), "og-fallback")
        self.assertIsNone(why(lambda c: c["images"].update(og={"path": "{images}/{slug}/og.png",
                                                                "fallback_first_image": False})))
        self.assertEqual(why(lambda c: c.update(language="de")), "label:de")
        self.assertIsNone(why(lambda c: c["images"]["figure"]["words"].update(scene="KI-generiertes Bild")))
        self.config(lambda c: c.update(language="en"))
        self.assertEqual(why(lambda c: c.update(roles={"conditional": []})), "no-illustrator")
        self.assertEqual(why(lambda c: c.update(roles={"conditional": ["illustrator", "translator"]}, translations={
            "source": "en", "targets": [{"lang": "ko", "body_pattern": "{content}/ko/{slug}.md",
                                         "url_pattern": "/ko/{slug}/"}]})), "translations")
        self.assertEqual(why(lambda c: c.pop("translations") and c["images"].pop("scenes")), "no-config")
        self.assertEqual(images.config_errors(self.root, self.cfg)["scene_errors"], [])

    def test_labels_by_language(self):
        for lang, want in (("ko", "AI 생성 이미지"), ("ja", "AI生成画像"), ("en", LABEL)):
            self.config(lambda c: c.update(language=lang))
            self.assertEqual(images.snippet_text(self.cfg, self.g1()), "![%s](%s)\n*%s*" % (
                self.g1()["alt"], self.g1()["ref"], want))
        self.config(lambda c: c["images"]["figure"].update(words=dict(c["images"]["figure"]["words"], scene="Made by AI")))
        self.assertTrue(images.snippet_text(self.cfg, self.g1()).endswith("*Made by AI*"))


class ManifestTests(SceneCase):
    def errors(self, items):
        self.manifest(items)
        return " | ".join(self.plan(check=True)["errors"])

    def test_each_rule(self):
        cases = [
            ([self.g1(size="wide")], "size must be one of"),
            ([self.g1(seed=-1)], "seed must be"),
            ([self.g1(seed=2 ** 32)], "seed must be"),
            ([self.g1(seed=True)], "seed must be"),
            ([self.g1(prompt="x" * 1001)], "prompt is English"),
            ([self.g1(prompt="")], "prompt is English"),
            ([self.g1(prompt="공항의 여행자")], "prompt is English"),
            ([self.g1(prompt='a "quoted" sign')], "prompt is English"),
            ([self.g1(prompt="a\\b")], "prompt is English"),
            ([self.g1(prompt="a\ntraveler")], "prompt is English"),
            ([self.g1(refs=[])], "takes no refs"),
            ([self.g1(id="e1")], "a scene id"),
            ([self.g1(file="%s/g1-counter.jpg" % IMG, ref=ref("g1", "counter").replace(".png", ".jpg"))],
             "published as .png"),
            ([self.g1(), self.g2(), self.g2(id="g3", file="%s/g3-x.png" % IMG, ref=ref("g3", "x"))],
             "3 scene images — this category allows 2"),
        ]
        for items, want in cases:
            with self.subTest(want=want):
                self.assertIn(want, self.errors(items))
        self.config(lambda c: c["images"]["scenes"].update(per_category={"guide": 1}))
        self.assertIn("2 scene images — this category allows 1", self.errors([self.g1(), self.g2()]))
        self.assertEqual(self.errors([self.g1(), self.g2(prompt="x" * 1000)]).count("prompt"), 0)

    def test_off_by_config_without_limner(self):
        self.config(lambda c: c["images"].pop("scenes"))
        self.assertIn("scene images are off here (no-config)", self.errors([self.g1(), self.g2()]))
        self.assertEqual(self.calls(), [])  # plan never asks this machine's limner (08 R2-1)

    def test_label_snippet_exactly_once(self):
        self.scene_body(g1="![%s](%s)" % (self.g1()["alt"], self.g1()["ref"]))
        self.assertIn("g1: the picture with its AI label", self.errors([self.g1(), self.g2()]))
        self.scene_body()
        self.assertEqual(self.errors([self.g1(), self.g2()]), "")
        self.assertEqual(images.snippet(self.root, self.cfg, TID, "g2")["snippet"], self.snip(self.g2()))

    def test_key_and_full_prompt(self):
        g = self.g1()
        self.assertEqual(images.full_prompt(self.cfg, g), "%s %s %s" % (P1, STYLE, images.NO_TEXT))
        k = images.scene_key(self.cfg, g)
        self.assertEqual(images.scene_key(self.cfg, self.g1(alt="Other words", purpose="x")), k)
        self.assertEqual(images.scene_key(self.cfg, self.g1(file="%s/g1-other.png" % IMG)), k)  # R3-3
        self.assertNotEqual(images.scene_key(self.cfg, self.g1(seed=42)), k)
        self.assertNotEqual(images.scene_key(self.cfg, self.g1(size="square")), k)
        self.config(lambda c: c["images"]["scenes"].update(style="Watercolor."))
        self.assertNotEqual(images.scene_key(self.cfg, g), k)
        self.config(lambda c: c["images"]["scenes"].pop("style"))
        self.assertEqual(images.full_prompt(self.cfg, g), "%s %s" % (P1, images.NO_TEXT))


class GenerateTests(SceneCase):
    def test_start_then_take_over(self):
        self.assertEqual(self.plan()["pending"]["generate"], ["g1", "g2"])
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10,0"}):
            out = self.gen()
            self.assertEqual((out["state"], out["running"]), ("running", ["g1", "g2"]), out)
            rid = out["run_id"]
            gen = self.state()["images"]["gen"]
            self.assertEqual((gen["run_id"], gen["waited_s"]), (rid, 0))
            self.assertTrue(gen["attempt"] and gen["started_at"] and gen["job_sha256"])
            job = json.load(open(os.path.join(self.root, ".limner/herald-jobs/%s.json" % TID)))
            self.assertEqual(job["model"], "qwen-image-edit-2511")
            self.assertEqual([j["out"] for j in job["jobs"]], [".limner/herald-out/%s/g1.png" % TID,
                                                               ".limner/herald-out/%s/g2.png" % TID])
            self.assertEqual((job["jobs"][0]["width"], job["jobs"][0]["height"], job["jobs"][1]["width"]),
                             (1024, 576, 896))
            self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "g1-counter.png")))
            out = self.gen()
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(out["run_id"], rid)
        self.assertEqual(sorted(x["id"] for x in out["generated"]), ["g1", "g2"])
        self.assertEqual(self.gcalls("cancel"), [])
        self.assertEqual(len(self.gen_lines()), 2)
        line = self.gen_lines()[0]
        self.assertEqual((line["model"]["name"], line["lora"]["file"][:8], line["model_license"], line["generator"]),
                         ("qwen-image-edit-2511-q4", "Qwen-Ima", "Apache-2.0", "mflux"))
        self.assertEqual(line["prompt"], images.full_prompt(self.cfg, self.g1()))
        for gid, f in (("g1", "g1-counter.png"), ("g2", "g2-platform.png")):
            self.assertTrue(os.path.isfile(os.path.join(self.root, IMG, f)))
            self.assertEqual(self.state()["images"]["items"][gid]["status"], "generated")
        for c in self.calls():
            self.assertNotIn("--force", c)
            self.assertNotIn("--accept", c)
        st = images.status(self.root, self.cfg, TID)
        self.assertEqual((st["pending"]["confirm"], st["pending"]["review"]), (["g1", "g2"], ["g1", "g2"]))
        self.assertEqual(st["note"], "screenshots: g1(confirm) g2(confirm)")
        self.assertGreater(st["gen_out_bytes"], 0)

    def test_one_of_two_finished_keeps_the_run(self):
        """R1-2: a finished item stays in the job — same job, same run_id, no cancel."""
        self.plan()
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10,10,0", "FAKE_LMN_PER_POLL": "1"}):
            out = self.gen()
            self.assertEqual(([x["id"] for x in out["generated"]], out["running"], out["state"]),
                             (["g1"], ["g2"], "running"))
            rid = out["run_id"]
            out = self.gen()
            self.assertEqual((out["run_id"], [x["id"] for x in out["generated"]], out["skipped"]), (rid, ["g2"], ["g1"]))
            self.assertEqual(self.gcalls("cancel"), [])
            out = self.gen()  # nothing left to make: the run, only finishing, is stopped (round 2 m5)
            self.assertEqual((out["state"], out["run_id"]), ("done", rid))
            self.assertEqual(len(self.gcalls("cancel")), 1)
            self.assertNotIn("gen", self.state()["images"])
            n = len(self.calls())
            out = self.gen()  # nothing left to make, no run going: no limner call at all
        self.assertEqual((out["state"], self.calls()[n:]), ("done", []))
        self.assertEqual(sorted(x["id"] for x in self.gen_lines()), ["g1", "g2"])  # R2-1: one line each
        self.assertEqual(images.status(self.root, self.cfg, TID)["items"][0]["attempts"], 1)

    def test_attempt_null_takes_in_skipped(self):
        """A generate cut off before the ledger: the output stays in the state dir; the next `run`
        reports it `skipped` (attempt null) and it is taken in then."""
        self.plan()
        with mock.patch.object(images, "ledger_append", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.gen()
        self.assertEqual(self.gen_lines(), [])
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".limner/herald-out/%s/g1.png" % TID)))
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "g1-counter.png")))
        n = len(self.gcalls())
        out = self.gen()
        self.assertEqual(out["state"], "done", out)
        # the probe's --check, the job's --check, then `run` answers attempt null
        self.assertEqual([c[0] for c in self.gcalls()[n:]], ["run", "run", "run"])
        self.assertEqual(len(self.gen_lines()), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.root, IMG, "g1-counter.png")))
        # after the ledger, before the copy: the line is not written again, the file is copied
        os.remove(os.path.join(self.root, IMG, "g1-counter.png"))
        out = self.gen()
        self.assertEqual(([x["id"] for x in out["generated"]], len(self.gen_lines())), (["g1"], 2))

    def test_unreported_record_never_reaches_the_ledger(self):
        """R1-9: a record an agent wrote into the state dir, with no limner report, is nothing."""
        self.plan()
        out_rel = ".limner/herald-out/%s/g1.png" % TID
        self.write(out_rel, b"\x89PNG forged", binary=True)
        self.write(".limner/records/%s.json" % out_rel, json.dumps({"kind": "generate", "generator": "mflux"}))
        out = self.gen(env={"FAKE_LMN_RUN_EXIT": "73"})
        self.assertEqual({x["code"] for x in out["failed"]}, {"busy"})
        self.assertEqual(self.gen_lines(), [])
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "g1-counter.png")))

    def test_jobs_changed_cancels_the_old_run(self):
        self.plan()
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10"}):
            old = self.gen()["run_id"]
            self.manifest([self.g1(), self.g2(seed=8)])
            self.plan()
            out = self.gen()
        self.assertNotEqual(out["run_id"], old)
        cancels = self.gcalls("cancel")
        self.assertEqual(len(cancels), 1)
        self.assertEqual(cancels[0][cancels[0].index("--run-id") + 1], old)
        self.assertEqual(self.state()["images"]["gen"]["run_id"], out["run_id"])
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10", "FAKE_LMN_CANCEL_EXIT": "10"}):
            self.manifest([self.g1(), self.g2(seed=9)])
            self.plan()
            out = self.gen()
        self.assertEqual({x["code"] for x in out["failed"]}, {"busy"})  # the old run did not stop yet

    def test_exit_table(self):
        self.plan()
        out = self.gen(env={"FAKE_LMN_STATUS": "12,0"})  # the state dir lost the run: `run` once more
        self.assertEqual(out["state"], "done", out)
        self.assertEqual([c[0] for c in self.gcalls()], ["run", "run", "run", "status", "run", "status"])
        for env, code in (({"FAKE_LMN_RUN_EXIT": "73"}, "busy"), ({"FAKE_LMN_RUN_EXIT": "70"}, "internal"),
                          ({"FAKE_LMN_RUN_EXIT": "2"}, "env"), ({"FAKE_LMN_RUN_EXIT": "1"}, "crashed"),
                          ({"FAKE_LMN_STATE": "cancelled"}, "cancelled"),
                          ({"FAKE_LMN_FAIL": '[{"id": "g1", "reason": "error"}]'}, "error"),
                          ({"FAKE_LMN_FAIL": '[{"id": null, "reason": "environment", "message": "mflux api"}]'}, "env"),
                          ({"FAKE_LMN_FAIL": '[{"id": "g1", "reason": "lock_lost"}]'}, "lock_lost")):
            with self.subTest(code=code):
                shutil.rmtree(os.path.join(self.root, ".limner"), ignore_errors=True)
                os.remove(os.path.join(self.lmndir, "runs.json")) if os.path.exists(
                    os.path.join(self.lmndir, "runs.json")) else None
                self.manifest([self.g1(seed=100 + len(code)), self.g2(seed=200 + len(code))])
                self.plan()
                out = self.gen(env=env)
                self.assertEqual(out["state"], "failed", out)
                self.assertIn(code, {x["code"] for x in out["failed"]})
                self.assertEqual({x["class"] for x in out["failed"]}, {"env"})  # never content (§2.4.3)
        out = images.status(self.root, self.cfg, TID)
        self.assertEqual([i["id"] for i in out["items"]], ["g1", "g2"])  # nothing was dropped

    def test_busy_message(self):
        self.plan()
        out = self.gen(env={"FAKE_LMN_RUN_EXIT": "73"})
        self.assertIn("s2v", out["failed"][0]["message"])

    def test_machine_failure_retried_once(self):
        self.plan()
        out = self.gen(env={"FAKE_LMN_FAIL": '[{"id": "g1", "reason": "memory"}]'})
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(len([c for c in self.gcalls("run") if "--check" not in c]), 2)
        for f in ("runs.json",):
            os.remove(os.path.join(self.lmndir, f))
        shutil.rmtree(os.path.join(self.root, ".limner"))
        self.manifest([self.g1(seed=1), self.g2(seed=2)])
        self.plan()
        out = self.gen(env={"FAKE_LMN_FAIL": '[{"id": "g1", "reason": "metal"}]', "FAKE_LMN_FAIL_ALWAYS": "1"})
        self.assertEqual([(x["id"], x["code"]) for x in out["failed"]], [("g1", "metal")])
        out = self.gen(env={"FAKE_LMN_STATE": "orphan_child"})
        self.assertTrue(self.gcalls("cancel"))

    def test_budget_and_popen_limit(self):
        self.plan()
        seen = []
        real = limner.run

        def spy(root, cfg, sub, opts=(), timeout=60, command=None):
            seen.append((sub, dict((k, v) for k, v in opts if v is not None), timeout))
            return real(root, cfg, sub, opts, timeout=timeout, command=command)
        with mock.patch.object(limner, "run", side_effect=spy), mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10"}):
            images.generate(self.root, self.cfg, TID, wait=240)
            images.generate(self.root, self.cfg, TID, wait=25)
        st = [x for x in seen if x[0] == ["status"]]
        ws = int(st[0][1]["--wait-seconds"])
        self.assertTrue(215 <= ws <= 220, ws)
        self.assertEqual(st[0][2], ws + 20)
        self.assertEqual((st[1][1]["--wait-seconds"], st[1][2]), (0, 20))
        runs = [x for x in seen if x[0] == ["run"] and "--wait" in x[1]]
        self.assertEqual((runs[0][1]["--wait"], runs[0][2]), (30, 60))
        with self.assertRaises(Exception):
            images.generate(self.root, self.cfg, TID, wait=541)

    def test_human_file_moves_away_and_branch(self):
        self.plan()
        self.write("%s/g1-counter.png" % IMG, b"\x89PNG a human's", binary=True)
        self.plan()  # plan moves a file no generation line vouches for (P9)
        self.assertIn("g1-counter.png", self.removed())
        self.write("%s/g1-counter.png" % IMG, b"\x89PNG again", binary=True)
        self.plan()
        self.write("%s/g1-counter.png" % IMG, b"\x89PNG after plan", binary=True)
        out = self.gen()
        self.assertEqual(out["state"], "done")
        self.assertEqual(self.removed().count("g1-counter.png"), 3)
        sh(self.root, "git", "switch", "-q", "main")
        with self.assertRaises(Exception) as cm:
            images.generate(self.root, self.cfg, TID)
        self.assertIn("herald branch", str(cm.exception))

    def test_needs_plan_first(self):
        self.plan()
        self.manifest([self.g1(seed=5), self.g2()])
        with self.assertRaises(Exception) as cm:
            self.gen()
        self.assertIn("HRD image plan", str(cm.exception))

    def test_off(self):
        self.plan()
        out = self.gen(env={"FAKE_LMN_GEN_ENV": "models are not ready (run `lmn setup`)"})
        self.assertEqual((out["state"], out["why"]), ("off", "generate:env"))
        self.assertIn("lmn setup", out["message"])
        self.assertEqual(self.state()["images"]["items"]["g1"]["status"], "pending")  # never dropped (P18)

    def test_reset_wait_and_waited(self):
        self.plan()
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10"}):
            self.gen()
            st = self.state()
            st["images"]["gen"]["waited_s"] = 1700
            store.save_state(self.root, TID, st)
            self.assertIn(self.gen()["waited_s"], (1700, 1701, 1702))  # kept for the same run (+ this call's wait)
            self.assertEqual(images.reset_wait(self.root, self.cfg, TID), {"ok": True})
            self.assertEqual(self.state()["images"]["gen"]["waited_s"], 0)


class RecordTests(SceneCase):
    def test_fake_generator(self):
        self.plan()
        out = self.gen(env={"FAKE_LMN_GENERATOR": "fake"})
        self.assertEqual({x["code"] for x in out["failed"]}, {"fake-generator"})
        self.assertEqual(self.gen_lines(), [])
        out = self.gen(env={"FAKE_LMN_GENERATOR": "fake", "HRD_TEST_ALLOW_FAKE_GENERATOR": "1"})
        self.assertEqual(out["state"], "done", out)

    def test_each_mismatch(self):
        for over in ({"prompt": "x"}, {"seed": 1}, {"width": 512}, {"height": 512}, {"out": "elsewhere.png"},
                     {"out_sha256": "0" * 64}, {"refs": [{"path": "a.png", "sha256": "x"}]}, {"job_sha": ""},
                     {"kind": "compose"}, {"contract": 2}):
            with self.subTest(over=over):
                shutil.rmtree(os.path.join(self.root, ".limner"), ignore_errors=True)
                p = os.path.join(self.lmndir, "runs.json")
                if os.path.exists(p):
                    os.remove(p)
                self.plan()
                out = self.gen(env={"FAKE_LMN_RECORD": json.dumps(over)})
                self.assertEqual({x["code"] for x in out["failed"]}, {"record-mismatch"}, out)
                self.assertEqual(self.gen_lines(), [])
                self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "g1-counter.png")))


class StateTests(SceneCase):
    def test_states_from_ledgers(self):
        self.generated()
        g1 = self.g1()
        led = shots.Ledger(self.root)
        self.assertEqual(images.scene_state(self.root, self.cfg, TID, g1, led), "generated")
        images.confirm(self.root, self.cfg, TID, "g1")
        led = shots.Ledger(self.root)
        self.assertEqual(images.scene_state(self.root, self.cfg, TID, g1, led), "ready")
        self.assertEqual(images.scene_state(self.root, self.cfg, TID, self.g1(alt="New words"), led), "ready")
        self.assertEqual(images.scene_state(self.root, self.cfg, TID, self.g1(seed=1), led), "pending")
        st = self.state()  # a forged state never counts
        st["images"]["items"]["g2"]["status"] = "ready"
        store.save_state(self.root, TID, st)
        self.assertEqual(images.scene_state(self.root, self.cfg, TID, self.g2(), led), "generated")
        os.remove(os.path.join(self.root, shots.GENERATIONS))
        self.assertEqual(images.scene_state(self.root, self.cfg, TID, g1, shots.Ledger(self.root)), "pending")

    def test_other_machine_record_missing(self):
        """R2-5: generated elsewhere (no ledger here) → record-missing, never drawn again until a
        human's `--regenerate`; then generate and confirm here."""
        self.generated()
        os.remove(os.path.join(self.root, shots.GENERATIONS))
        n = len(self.gcalls())
        out = self.gen()
        self.assertEqual(sorted((x["id"], x["code"]) for x in out["failed"]), [("g1", "record-missing"),
                                                                                ("g2", "record-missing")])
        self.assertEqual(self.gcalls()[n:], [])  # nothing pending: no probe, no run
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("no generation record of this picture on this machine" in p for p in probs), probs)
        images.reject(self.root, self.cfg, TID, "g1", reason="regenerate on this machine", regenerate=True)
        self.assertEqual(self.state().get("image_rejects"), None)
        self.plan()
        out = self.gen()
        self.assertEqual([x["id"] for x in out["generated"]], ["g1"])
        self.assertEqual([(x["id"], x["code"]) for x in out["failed"]], [("g2", "record-missing")])

    def test_a_b_machines(self):
        """R3-2: A's generate never replaces B's confirmed picture with A's old one; a new key
        drops the old picture's marks."""
        self.generated()
        b_pic = b"\x89PNG generated and confirmed on machine B"
        self.write("%s/g1-counter.png" % IMG, b_pic, binary=True)
        st = self.state()
        st["images"]["items"]["g1"]["generated_blob"] = shots.blob(self.root, "%s/g1-counter.png" % IMG)
        store.save_state(self.root, TID, st)
        out = self.gen()
        self.assertEqual([(x["id"], x["code"]) for x in out["failed"]], [("g1", "record-missing")])
        self.assertEqual(open(os.path.join(self.root, IMG, "g1-counter.png"), "rb").read(), b_pic)
        self.manifest([self.g1(seed=99), self.g2()])
        self.plan()
        self.assertNotIn("generated_blob", self.state()["images"]["items"]["g1"])
        out = self.gen()
        self.assertEqual(out["state"], "done", out)

    def test_nothing_pending_needs_no_limner(self):
        """R3-1/R2-4: generated (or ready) scenes only — done without a probe or a run, even where
        no model is."""
        self.generated()
        n = len(self.calls())
        out = self.gen(env={"FAKE_LMN_GEN_ENV": "models are not ready"})
        self.assertEqual((out["state"], self.calls()[n:]), ("done", []))
        images.confirm(self.root, self.cfg, TID, "g1,g2")
        self.assertEqual((self.gen(env={"FAKE_LMN_GEN_ENV": "x"})["state"], self.calls()[n:]), ("done", []))

    def test_lock_change_regenerates_without_an_attempt(self):
        """R2-5: limner's lock changed — the picture is drawn again, shown as `regenerated`;
        `attempts` does not rise."""
        self.generated()
        for f in ("g1-counter.png", "g2-platform.png"):
            os.remove(os.path.join(self.root, IMG, f))
        out = self.gen(env={"FAKE_LMN_LOCK": "lock2"})
        self.assertEqual((out["state"], sorted(out["regenerated"])), ("done", ["g1", "g2"]), out)
        self.assertEqual(len(self.gen_lines()), 4)
        self.assertEqual(images.status(self.root, self.cfg, TID)["items"][0]["attempts"], 1)


class ReviewConfirmTests(SceneCase):
    def test_review(self):
        self.generated()
        st = images.status(self.root, self.cfg, TID)
        self.assertEqual(st["pending"]["review"], ["g1", "g2"])
        out = images.review(self.root, self.cfg, TID, "g1", ok=True, note="no letters, matches the paragraph")
        self.assertEqual(out["reviewed"], ["g1"])
        self.assertEqual(images.status(self.root, self.cfg, TID)["pending"]["review"], ["g2"])
        led_before = open(os.path.join(self.root, shots.GENERATIONS)).read()
        out = images.review(self.root, self.cfg, TID, "g2", redo=True, note="letters on the board")
        self.assertEqual((out["redo"], out["attempts"]), (["g2"], 2))
        self.assertEqual(open(os.path.join(self.root, shots.GENERATIONS)).read(), led_before)  # state only
        self.assertIn("turned down before", " ".join(self.plan(check=True)["errors"]))
        with self.assertRaises(Exception):
            images.review(self.root, self.cfg, TID, "g1", ok=True, redo=True, note="x")
        with self.assertRaises(Exception):
            images.review(self.root, self.cfg, TID, "g1", ok=True, note="")
        self.manifest([self.g1(), self.g2(seed=8)])
        self.assertEqual(self.plan()["errors"], [])
        self.assertEqual(images.status(self.root, self.cfg, TID)["items"][1]["attempts"], 2)

    def test_confirm_without_review_passes_draft(self):
        """The review is no pass decision: a human's confirmation alone lets draft pass, and
        `review_rejects` stays after it."""
        self.generated()
        images.review(self.root, self.cfg, TID, "g2", redo=True, note="letters")
        self.manifest([self.g1(), self.g2(seed=8)])
        self.plan()
        self.gen()
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("waiting for a human's confirmation" in p for p in probs), probs)
        images.confirm(self.root, self.cfg, TID, "g1,g2")
        self.plan()
        self.made_og()
        self.assertEqual(images.draft_problems(self.root, self.cfg, TID, self.state()), [])
        with mock.patch.object(store, "run_gate", return_value={"ok": True, "errors": [], "warnings": [],
                                                                 "prose": {"warnings": [], "stats": {}}}):
            st = store.stage_pass(self.root, self.cfg, TID, "draft")
        self.assertEqual(len(st["review_rejects"]), 1)

    def test_confirm_reject(self):
        self.plan()
        with self.assertRaises(Exception) as cm:
            images.confirm(self.root, self.cfg, TID, "g1")
        self.assertIn("not a generated scene", str(cm.exception))
        self.gen()
        with mock.patch.dict(os.environ, {"HRD_UNATTENDED": "1"}):
            with self.assertRaises(Exception):
                images.confirm(self.root, self.cfg, TID, "g1")
            with self.assertRaises(Exception):
                images.reject(self.root, self.cfg, TID, "g1", reason="x")
        out = images.reject(self.root, self.cfg, TID, "g1", reason="looks like a real airline logo")
        self.assertEqual(out["rejected"], ["g1"])
        self.assertIn("seed or the prompt", out["next"])
        rj = self.state()["image_rejects"][0]
        self.assertEqual((rj["id"], rj["job"], rj["drop"]), ("g1", images.scene_key(self.cfg, self.g1()), False))
        self.assertEqual(self.state()["last_loopback"], "human")
        self.assertIn("g1-counter.png", self.removed())
        self.assertIn("turned down before", " ".join(self.plan(check=True)["errors"]))
        self.manifest([self.g1(file="%s/g1-renamed.png" % IMG, ref=ref("g1", "renamed")), self.g2()])
        self.scene_body(g1="![%s](%s)\n*%s*" % (self.g1()["alt"], ref("g1", "renamed"), LABEL))
        self.assertIn("turned down before", " ".join(self.plan(check=True)["errors"]))  # R3-3
        out = images.reject(self.root, self.cfg, TID, "g2", reason="not needed", drop=True)
        self.assertIn("AI label", out["next"])
        with self.assertRaises(Exception):
            images.reject(self.root, self.cfg, TID, "g2", reason="x", refetch=True)


class LabelTests(SceneCase):
    def gate_ok(self):
        return mock.patch.object(store, "run_gate", return_value={"ok": True, "errors": [], "warnings": [],
                                                                   "prose": {"warnings": [], "stats": {}}})

    def test_draft_verify_and_trim(self):
        self.ready()
        self.made_og()
        self.assertEqual(images.draft_problems(self.root, self.cfg, TID, self.state()), [])
        self.scene_body(g1="![%s](%s)" % (self.g1()["alt"], self.g1()["ref"]))  # the label line deleted
        probs = images.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("AI label" in p for p in probs), probs)
        self.assertTrue(images.label_problems(self.root, self.cfg, TID, self.state()))
        self.assertTrue(any("AI label" in p for p in images.verify_problems(self.root, self.cfg, TID, self.state(), {})))
        self.scene_body()
        text = open(os.path.join(self.root, "src/content/blog/%s.md" % SLUG)).read()
        spans = images.snippet_spans(self.root, self.cfg, TID, self.state(), text)
        self.assertEqual([text[a:b] for a, b in spans], [self.snip(self.g1()), self.snip(self.g2())])

    def test_stage_pass_checks_labels_outside_run_gate(self):
        self.ready()
        self.made_og()
        self.config(lambda c: c["commands"].update(validate="true"))  # a repo validator: run_gate runs only it
        self.scene_body(g2="![%s](%s)" % (self.g2()["alt"], self.g2()["ref"]))
        self.plan()
        with self.gate_ok():
            with self.assertRaises(Exception) as cm:
                store.stage_pass(self.root, self.cfg, TID, "draft")
        self.assertIn("AI label", str(cm.exception))

    def test_slug_wide_regex(self):
        """R1-4: the label check follows the slug — a refresh topic (no scene in its manifest) that
        drops base's label is refused; alt rewritten is fine; Markdown and HTML templates."""
        self.ready()
        st = self.state()
        other = dict(st, topic_id="r-0002")
        self.assertEqual(images.label_problems(self.root, self.cfg, "r-0002", other), [])
        self.scene_body(g1="![Rewritten alt text](%s)\n*%s*" % (self.g1()["ref"], LABEL))
        self.assertEqual(images.label_problems(self.root, self.cfg, "r-0002", other), [])
        self.scene_body(g1="![Rewritten alt text](%s)\n" % self.g1()["ref"])
        self.assertTrue(images.label_problems(self.root, self.cfg, "r-0002", other))
        self.scene_body(g1="![a](%s)\n*%s*\n\n![b](%s)" % (self.g1()["ref"], LABEL, self.g1()["ref"]))
        self.assertIn("1 of 2", images.label_problems(self.root, self.cfg, "r-0002", other)[0])
        html = '<figure><img src="{ref}" alt="{alt}"><figcaption>{label}</figcaption></figure>'
        self.config(lambda c: c["images"]["figure"].update(scene=html))
        g1 = self.g1()
        self.scene_body(g1='<figure><img src="%s" alt="Anything here"><figcaption>%s</figcaption></figure>'
                        % (g1["ref"], LABEL), g2=images.snippet_text(self.cfg, self.g2()))
        self.assertEqual(images.label_problems(self.root, self.cfg, "r-0002", other), [])
        self.scene_body(g1='<figure><img src="%s" alt="x"></figure>' % g1["ref"], g2=images.snippet_text(self.cfg, self.g2()))
        self.assertTrue(images.label_problems(self.root, self.cfg, "r-0002", other))

    def test_base_states_count(self):
        """A scene recorded only on origin/<base> (another topic, published) is checked too."""
        self.ready()
        self.made_og()
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "publish")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.root, "git", "fetch", "-q", "origin")
        images._BASE_MANAGED.clear()
        self.assertEqual(images.managed_on_base(self.root, self.cfg, SLUG, kinds=True),
                         [("%s/g1-counter.png" % IMG, "scene"), ("%s/g2-platform.png" % IMG, "scene")])
        shutil.rmtree(os.path.join(self.root, W))  # this topic's work dir gone from the working tree
        self.scene_body(g2="![%s](%s)" % (self.g2()["alt"], self.g2()["ref"]))
        probs = images.label_problems(self.root, self.cfg, "r-0002", {"slug": SLUG, "topic_id": "r-0002"})
        self.assertEqual(len(probs), 1, probs)


class TranslationTests(SceneCase):
    def test_off_and_begin_refused(self):
        self.ready()
        self.made_og()
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "publish")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.root, "git", "fetch", "-q", "origin")
        sh(self.root, "git", "switch", "-q", "main")
        sh(self.root, "git", "merge", "-q", "--ff-only", "origin/main")
        self.config(lambda c: c.update(translations={"source": "en", "targets": [
            {"lang": "ko", "body_pattern": "{content}/ko/{slug}.md", "url_pattern": "/ko/{slug}/"}]},
            roles={"conditional": ["illustrator", "translator"]}))
        self.assertEqual(images.kinds(self.root, self.cfg, TID)["scene"]["why"], "translations")
        topics = store.load_topics(self.root)
        topics["topics"].append({"id": "tr-new-post-20261111", "title": "x", "translate_of": SLUG, "state": "queued",
                                 "history": [], "reverted_by": []})
        store.save_topics(self.root, topics)
        _, p = self.hrd("begin", "--topic", "tr-new-post-20261111", check=False)
        self.assertIn("scene images block translation", p.stderr)
        out, _ = self.hrd("select")
        self.assertNotIn("tr-new-post-20261111", out)
        topics["topics"] = [dict(topics["topics"][0], state="published")]
        store.save_topics(self.root, topics)
        sh(self.root, "git", "branch", "-q", "-D", store.branch_name(TID, SLUG))
        store.save_published(self.root, {"articles": [{"slug": SLUG, "origin": "herald", "path": "x",
                                                       "published_at": "2026-11-01"}]})
        out, _ = self.hrd("translate", "missing")
        self.assertEqual((out["blocked"][0]["reason"], out["articles"]), ("scene-images", []))
        from hrdlib import refresh
        pc = refresh.precheck(self.root, Config.load(self.root), SLUG, clear=False)
        self.assertTrue(any("scene-images" in b for b in pc["blocked"]))


class LedgerRuleUTests(SceneCase):
    def test_generations_alone_wake_the_ledger(self):
        """R1-3: no captures, no fetches — the generation ledger alone runs rule U, the history
        check and squash."""
        self.generated()
        led = shots.Ledger(self.root)
        self.assertFalse(led.idle)
        self.assertEqual((led.captures, led.fetches), ([], []))
        shutil.copy(os.path.join(self.root, IMG, "g1-counter.png"), os.path.join(self.root, IMG, "copy.png"))
        probs = shots.draft_problems(self.root, self.cfg, TID, self.state())
        self.assertTrue(any("copy.png" in p for p in probs), probs)
        os.remove(os.path.join(self.root, IMG, "copy.png"))
        self.commit("wip", ".")  # unconfirmed scenes in a WIP commit (batch preserve_wip)
        self.manifest([self.g1(), self.g2(seed=8)])  # g2 turned down, drawn again: the old one never confirmed
        self.plan()
        self.gen()
        images.confirm(self.root, self.cfg, TID, "g1,g2")
        self.commit("next", ".")
        probs, squashable = shots.history_problems(self.root, self.cfg, TID, SLUG)
        self.assertTrue(squashable, probs)
        self.assertTrue(any("past commit" in p for p in probs), probs)
        out = shots.squash(self.root, self.cfg, TID)
        self.assertTrue(out["squashed"])
        self.assertEqual(shots.history_problems(self.root, self.cfg, TID, SLUG), ([], False))

    def test_damaged_line(self):
        self.generated()
        with open(os.path.join(self.root, shots.GENERATIONS), "a") as f:
            f.write("not json\n")
        led = shots.Ledger(self.root)
        self.assertIn("generations.jsonl line 3", led.damage_text())
        self.assertIn("tooling: images ledger damaged", led.damage_text())
        with self.assertRaises(Exception):
            self.gen()


class PublishTests(SceneCase):
    def test_exclusion_scope_rows(self):
        self.ready()
        self.made_og()
        self.write(W + "/critique.json", json.dumps({"final_round": {"verdict": "PASS"}, "audit_log": [],
                                                      "decision_log": []}))
        self.commit("wip", ".")
        reasons = store.exclusion_reasons(self.root, self.cfg, TID)
        self.assertIn("images", reasons)
        self.assertNotIn("external-images", reasons)
        self.assertEqual(store.blocking_exclusions([r for r in reasons if r == "images"], consent=True), [])
        self.assertEqual(images.scope_problems(self.root, self.cfg, TID, publish=True), [])
        st = images.status(self.root, self.cfg, TID)
        rows = "\n".join(st["pr_rows"])
        self.assertIn("| g1 | scene (AI-generated) | %s/g1-counter.png | qwen-image-edit-2511-q4 seed 41 · "
                      "landscape · confirmed " % IMG, rows)
        self.assertIn("<details><summary>Scene prompts</summary>", rows)
        self.assertIn("- g1: `%s`" % P1, rows)
        self.assertNotIn(images.NO_TEXT, rows)
        self.assertIn("Apache-2.0", rows)
        # an unconfirmed committed picture is refused at publish
        self.write("%s/g1-counter.png" % IMG, b"\x89PNG a human's", binary=True)
        self.commit("swap", ".")
        probs = images.scope_problems(self.root, self.cfg, TID, publish=True)
        self.assertTrue(any("g1: the committed file" in p for p in probs), probs)
        st = images.status(self.root, self.cfg, TID, rev="HEAD")
        self.assertTrue(st["items"][0]["replaced"])

    def test_rev_warns_when_the_prompt_changed(self):
        self.ready()
        self.commit("wip", ".")
        self.manifest([self.g1(prompt="A different scene of a traveler"), self.g2()])
        self.commit("human edit", ".")
        st = images.status(self.root, self.cfg, TID, rev="HEAD")
        self.assertTrue(any("g1: the manifest and the picture differ" in w for w in st["warnings"]), st["warnings"])

    def test_og_fallback_note(self):
        self.config(lambda c: c["images"]["og"].update(fallback_first_image=True))
        self.ready()
        os.remove(self.lmn)  # no limner here: OG records off
        limner.reset_cache()
        self.assertEqual(images.og(self.root, self.cfg, TID)["status"], "off")
        rows = "\n".join(images.status(self.root, self.cfg, TID)["pr_rows"])
        self.assertIn("AI-generated g1", rows)


class HoldTests(SceneCase):
    def test_note_and_resume(self):
        self.generated()
        st = self.state()
        st["screenshots"] = {"shots": {"s1": {"status": "pending"}}}
        st["images"]["items"]["e1"] = {"kind": "external", "status": "fetched"}
        self.assertEqual(shots.hold_note(st), "screenshots: s1 e1(confirm) g1(confirm) g2(confirm)")
        shots.check_note("screenshots: g1(confirm)")
        with self.assertRaises(Exception):
            shots.check_note("screenshots: g1(redo)")
        self.assertTrue(images.resume_at_collect(self.root, self.cfg, self.state()))
        _, p = self.hrd("result", "--topic", TID, "--status", "held:screenshots", "--note",
                        "screenshots: g1(confirm) g2(confirm)", check=False)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_resume_takes_over_the_run(self):
        self.plan()
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10,0"}):
            rid = self.gen()["run_id"]
            self.assertTrue(images.resume_at_collect(self.root, self.cfg, self.state()))
            out, _ = self.hrd("image", "generate", "--topic", TID, "--wait", "0")
        self.assertEqual((out["state"], out["run_id"]), ("done", rid))
        self.assertEqual(self.gcalls("cancel"), [])


class GuardTests(SceneCase):
    def guard(self, tool, tool_input, env=None):
        e = dict(os.environ)
        e.update(env or {})
        payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": self.root})
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard.py")], input=payload,
                           capture_output=True, text=True, env=e, cwd=self.root, timeout=60)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]

    def test_state_dir_and_commands(self):
        un = {"HRD_UNATTENDED": "1"}
        for rel in (".limner/records/.limner/herald-out/%s/g1.png.json" % TID, ".limner/tmp/x.record.json",
                    ".limner/herald-out/%s/g1.png" % TID, ".limner/herald-jobs/%s.json" % TID):
            self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, rel), "content": "x"}), "ask", rel)
            self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, rel), "content": "x"}, un),
                             "deny", rel)
        self.assertEqual(self.guard("Bash", {"command": "echo '{}' > .limner/tmp/x.record.json"}, un), "deny")
        self.assertEqual(self.guard("Bash", {"command": "rm -rf .limner"}), "ask")
        self.config(lambda c: c["limner"].update(state_dir="var/lmn"))
        self.assertEqual(self.guard("Write", {"file_path": os.path.join(self.root, "var/lmn/records/x.json"),
                                              "content": "x"}, un), "deny")
        hrd = "python3 .claude/herald/scripts/hrd.py image "
        for cmd in ("generate --topic t0001", "cancel --topic t0001", "review --topic t0001 --id g1 --ok --note x"):
            self.assertEqual(self.guard("Bash", {"command": hrd + cmd}, un), "allow", cmd)
        self.assertEqual(self.guard("Bash", {"command": hrd + "confirm --topic t0001 --id g1"}), "ask")
        self.assertEqual(self.guard("Bash", {"command": hrd + "reject --topic t0001 --id g1 --regenerate --reason x"},
                                    un), "deny")


class CancelTrialTests(SceneCase):
    def test_cancel(self):
        self.assertEqual(images.cancel(self.root, self.cfg, TID), {"cancelled": False, "state": None})
        self.plan()
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10"}):
            rid = self.gen()["run_id"]
            out, _ = self.hrd("image", "cancel", "--topic", TID)
        self.assertEqual(out, {"cancelled": True, "state": "cancelled"})
        c = self.gcalls("cancel")[0]
        self.assertEqual((c[c.index("--run-id") + 1], c[c.index("--wait-seconds") + 1]), (rid, "30"))
        self.assertIn("--root", c)
        out = images.cancel(self.root, self.cfg, TID)  # a finished run: exit 0 but not cancelled by this call
        self.assertEqual(out["state"], "cancelled")

    def test_trial(self):
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10,0"}):
            out = images.generate_trial(self.root, self.cfg, wait=0)
            self.assertEqual(out["state"], "running")
            again = images.generate_trial(self.root, self.cfg, wait=0)
        self.assertEqual((again["state"], again["run_id"]), ("done", out["run_id"]))
        self.assertEqual(again["file"], ".limner/herald-trial/scene.png")
        self.assertTrue(os.path.isfile(os.path.join(self.root, again["file"])))
        job = json.load(open(os.path.join(self.root, ".limner/herald-trial/scene.json")))["jobs"][0]
        self.assertEqual((job["width"], job["seed"]), (896, 1))
        self.assertTrue(job["prompt"].startswith(images.TRIAL_PROMPT + " " + STYLE))
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG)))
        self.assertFalse(os.path.exists(os.path.join(self.root, shots.GENERATIONS)))


class ReapTests(SceneCase):
    def test_live_callers_child_is_left_alone(self):
        """R1-11: another live Herald call's limner group is never reaped; a dead caller's is."""
        owner = subprocess.Popen(["sleep", "60"])
        child = subprocess.Popen(["sleep", "60"], start_new_session=True)
        try:
            d = limner._pgid_dir(self.root)
            os.makedirs(d, exist_ok=True)
            rec = {"pgid": child.pid, "started": shots._ps(child.pid, "lstart"), "argv0": "sleep",
                   "owner": owner.pid, "owner_started": shots._ps(owner.pid, "lstart")}
            path = os.path.join(d, "limner.%d.pgid" % owner.pid)
            json.dump(rec, open(path, "w"))
            limner.reset_cache()
            limner.run(self.root, self.cfg, ["--version"])
            self.assertIsNone(child.poll())
            self.assertTrue(os.path.exists(path))
            owner.kill()
            owner.wait()
            limner.run(self.root, self.cfg, ["--version"])
            self.assertEqual(child.wait(timeout=10), -signal.SIGKILL)
            self.assertFalse(os.path.exists(path))
        finally:
            for p in (owner, child):
                if p.poll() is None:
                    p.kill()


class ReviewRound1Tests(SceneCase):
    """REVIEW-20 round 1: ended old runs, mixed results, `regenerated`, confirmation mid-run,
    the call budget, the label's reach, prompts in the PR body."""

    def fresh(self, **kw):
        p = os.path.join(self.lmndir, "runs.json")
        if os.path.exists(p):
            os.remove(p)
        self.manifest([self.g1(**kw), self.g2()])
        self.plan()

    def test_old_run_ended_busy_or_env_is_passed(self):
        """M1: the old run's last attempt ended busy (cancel answers 73) or on an environment
        failure (2) — judged by its state, it is over: the new run starts."""
        self.plan()
        out = self.gen(env={"FAKE_LMN_RUN_EXIT": "73"})
        self.assertEqual({x["code"] for x in out["failed"]}, {"busy"})
        old = out["run_id"]
        self.assertNotIn("gen", self.state()["images"])  # the run ended: nothing to take over
        st = self.state()  # as if a live run had been recorded before it ended busy
        st["images"]["gen"] = {"run_id": old, "waited_s": 0}
        store.save_state(self.root, TID, st)
        self.manifest([self.g1(seed=5), self.g2()])
        self.plan()
        out = self.gen()
        self.assertEqual(out["state"], "done", out)
        c = self.gcalls("cancel")[-1]
        self.assertEqual(c[c.index("--run-id") + 1], old)
        # an attempt that ended on an environment failure (cancel answers 2)
        with mock.patch.dict(os.environ, {"FAKE_LMN_FAIL": '[{"id": null, "reason": "environment", "message": "x"}]',
                                          "FAKE_LMN_STATUS": "10,0"}):
            self.fresh(seed=6)
            rid = self.gen()["run_id"]
            out = self.gen()
            self.assertEqual({x["code"] for x in out["failed"]}, {"env"})
        st = self.state()
        st["images"]["gen"] = {"run_id": rid, "waited_s": 0}
        store.save_state(self.root, TID, st)
        self.manifest([self.g1(seed=7), self.g2()])
        self.plan()
        self.assertEqual(self.gen()["state"], "done")
        st = self.state()
        st["images"]["gen"] = {"run_id": rid, "waited_s": 0}
        store.save_state(self.root, TID, st)
        self.assertEqual(images.cancel(self.root, self.cfg, TID), {"cancelled": False, "state": "failed"})

    def test_mixed_result_takes_in_what_is_done(self):
        """m2: an attempt with g1 done and g2 failed `environment` (status exit 2) gives g1; an
        already generated scene is never a failure (run 73 afterwards)."""
        self.plan()
        out = self.gen(env={"FAKE_LMN_FAIL": '[{"id": "g2", "reason": "environment", "message": "mflux api"}]'})
        self.assertEqual(([x["id"] for x in out["generated"]], [(x["id"], x["code"]) for x in out["failed"]]),
                         (["g1"], [("g2", "env")]))
        self.assertEqual(len(self.gen_lines()), 1)
        out = self.gen(env={"FAKE_LMN_RUN_EXIT": "73"})
        self.assertEqual(([(x["id"], x["code"]) for x in out["failed"]], out["skipped"]), ([("g2", "busy")], ["g1"]))

    def test_regenerated_only_for_a_limner_update(self):
        """m3: a redo's new seed is drawn again by limner (job_changed) but is no limner update."""
        self.generated()
        images.review(self.root, self.cfg, TID, "g1", redo=True, note="letters")
        self.manifest([self.g1(seed=42), self.g2()])
        self.plan()
        out = self.gen()
        self.assertEqual((out["state"], out["regenerated"]), ("done", []))
        self.assertFalse(images.status(self.root, self.cfg, TID)["items"][0]["regenerated"])
        os.remove(os.path.join(self.root, IMG, "g2-platform.png"))
        out = self.gen(env={"FAKE_LMN_LOCK": "lock2"})  # limner updated: both drawn again, same jobs
        self.assertEqual(out["regenerated"], ["g1", "g2"])
        self.assertTrue(images.status(self.root, self.cfg, TID)["items"][1]["regenerated"])

    def test_confirm_mid_run_keeps_the_run_and_a_drop_stops_it(self):
        """m4: confirming g1 while g2 is drawn keeps the job (no cancel, the same run_id); when
        nothing is left to make, the run Herald left going is stopped."""
        self.plan()
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10,10,10", "FAKE_LMN_PER_POLL": "1"}):
            rid = self.gen()["run_id"]
            images.confirm(self.root, self.cfg, TID, "g1")
            self.plan()
            out = self.gen()
            self.assertEqual((out["run_id"], self.gcalls("cancel")), (rid, []))
            self.assertEqual(out["state"], "running")
        os.remove(os.path.join(self.lmndir, "runs.json"))
        shutil.rmtree(os.path.join(self.root, ".limner"))
        self.fresh(seed=9)
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10", "FAKE_LMN_PER_POLL": "1"}):
            rid = self.gen()["run_id"]  # g1 done, g2 still drawn
            images.reject(self.root, self.cfg, TID, "g2", reason="not needed", drop=True)
            self.manifest([self.g1(seed=9)])
            self.scene_body(g2="")
            self.plan()
            self.assertEqual(self.gen()["state"], "done")
        c = self.gcalls("cancel")
        self.assertEqual(c[-1][c[-1].index("--run-id") + 1], rid)
        self.assertNotIn("gen", self.state()["images"])

    def test_budget_bounds_retries_and_timeouts(self):
        """m7: no `run` again once the call has no room; every limner call's limit fits the call."""
        self.plan()
        seen = []
        real = limner.run

        def spy(root, cfg, sub, opts=(), timeout=60, command=None):
            seen.append(timeout)
            return real(root, cfg, sub, opts, timeout=timeout, command=command)
        with mock.patch.object(images, "GEN_SLACK", 5), mock.patch.object(limner, "run", side_effect=spy):
            out = self.gen(env={"FAKE_LMN_FAIL": '[{"id": "g1", "reason": "memory"}]'})
        self.assertEqual(out["state"], "running", out)  # the retry is left to the next call
        self.assertEqual(len([c for c in self.gcalls("run") if "--check" not in c]), 1)
        self.assertTrue(all(t <= 10 for t in seen[2:]), seen)  # after the probe: capped to the call's room
        out = self.gen()
        self.assertEqual(out["state"], "done", out)

    def test_label_reach(self):
        """m8: a site-absolute URL of a scene, and another article's scene, need the label too —
        also where a repo validator replaces the gate (the check runs outside run_gate)."""
        self.ready()
        st = self.state()
        self.scene_body(g1="![x](https://example.test%s)" % self.g1()["ref"])
        self.assertTrue(images.label_problems(self.root, self.cfg, TID, st))
        self.scene_body(g1="![x](https://example.test%s)\n*%s*" % (self.g1()["ref"], LABEL))
        self.assertEqual(images.label_problems(self.root, self.cfg, TID, st), [])
        # another article (slug old-post) shows new-post's scene without the label
        self.write("src/content/blog/old-post.md", "---\ntitle: Old\nslug: old-post\n---\n![a](%s)\n" % self.g1()["ref"])
        other = {"slug": "old-post", "topic_id": "t0009"}
        self.assertTrue(images.label_problems(self.root, self.cfg, "t0009", other))
        self.write("src/content/blog/old-post.md", "---\ntitle: Old\nslug: old-post\n---\n%s\n" % self.snip(self.g1()))
        self.assertEqual(images.label_problems(self.root, self.cfg, "t0009", other), [])
        # stage pass with a repo validator and the real run_gate: still refused by the label
        self.scene_body(g2="![x](https://example.test%s)" % self.g2()["ref"])
        self.config(lambda c: c["commands"].update(validate="true"))
        with self.assertRaises(Exception) as cm:
            store.stage_pass(self.root, self.cfg, TID, "draft")
        self.assertIn("must carry its AI label", str(cm.exception))

    def test_stage_pass_paths_call_the_label_check(self):
        """§11-24: draft, verify `--amend` and trim keep the label (each call site pinned)."""
        self.ready()
        self.made_og()
        calls = []
        with mock.patch.object(images, "label_problems", side_effect=lambda *a, **k: calls.append(a[2]) or ["LABEL"]):
            with mock.patch.object(store, "run_gate", return_value={"ok": True, "errors": [], "warnings": [],
                                                                     "prose": {"warnings": [], "stats": {}}}):
                with self.assertRaises(Exception) as cm:
                    store.stage_pass(self.root, self.cfg, TID, "draft")
                self.assertIn("LABEL", str(cm.exception))
                from hrdlib.hashing import bundle_hash
                self.write(W + "/verify.md", "ok\n")
                self.write(W + "/verify.json", json.dumps({"body_hash": bundle_hash(self.root, self.cfg, SLUG),
                                                           "counts": {"supported": 1, "unsupported": 0,
                                                                      "contradicted": 0, "unmapped": 0}}))
                st = self.state()
                st["stage"] = "verify"
                store.save_state(self.root, TID, st)
                with self.assertRaises(Exception) as cm:
                    store.stage_pass(self.root, self.cfg, TID, "verify", amend=True)
                self.assertIn("LABEL", str(cm.exception))
        self.assertEqual(calls, [TID, TID])
        text = open(os.path.join(self.root, "src/content/blog/%s.md" % SLUG)).read()
        self.assertIn((text.index(self.snip(self.g1())), text.index(self.snip(self.g1())) + len(self.snip(self.g1()))),
                      images.snippet_spans(self.root, self.cfg, TID, self.state(), text))

    def test_trim_refuses_the_label(self):
        from hrdlib.hashing import worktree_hash
        self.ready()
        st = self.state()
        cur = worktree_hash(self.root, self.cfg, SLUG)
        st["stage"] = "verify"
        st["stages"]["critique"] = {"body_hash": cur}
        store.save_state(self.root, TID, st)
        self.write(W + "/verify.json", json.dumps({"body_hash": cur, "counts": {
            "supported": 1, "unsupported": 1, "contradicted": 0, "unmapped": 0},
            "unsupported_sentences": [self.g1()["alt"]]}))
        with self.assertRaises(Exception) as cm:
            store.trim_begin(self.root, self.cfg, TID)
        self.assertIn("overlaps an image attribution", str(cm.exception))

    def test_batch_select_drops_scene_articles(self):
        self.ready()
        self.made_og()
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "publish")
        sh(self.root, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.root, "git", "fetch", "-q", "origin")
        images._BASE_MANAGED.clear()
        self.config(lambda c: c.update(translations={"source": "en", "targets": [
            {"lang": "ko", "body_pattern": "{content}/ko/{slug}.md", "url_pattern": "/ko/{slug}/"}]},
            roles={"conditional": ["illustrator", "translator"]}))
        topics = store.load_topics(self.root)
        topics["topics"] = [dict(topics["topics"][0], state="published"),
                            {"id": "tr-new-post-20261112", "title": "x", "translate_of": SLUG, "state": "queued",
                             "history": [], "reverted_by": []},
                            {"id": "tr-old-post-20261112", "title": "y", "translate_of": "old-post", "state": "queued",
                             "history": [], "reverted_by": []}]
        store.save_topics(self.root, topics)
        from hrdlib import batch
        self.assertEqual(batch.select_topics(self.root, Config.load(self.root), 5), ["tr-old-post-20261112"])

    def test_prompt_in_the_pr_body_is_a_code_span(self):
        self.manifest([self.g1(prompt="A traveler `at` a counter"), self.g2()])
        self.assertIn("prompt is English", " ".join(self.plan(check=True)["errors"]))
        self.manifest([self.g1(prompt="A traveler @someone <b>at</b> [x](https://x.test) a counter"), self.g2()])
        self.assertEqual(self.plan()["errors"], [])
        rows = "\n".join(images.status(self.root, self.cfg, TID)["pr_rows"])
        self.assertIn("- g1: `A traveler @someone <b>at</b> [x](https://x.test) a counter`", rows)


class ReviewRound2Tests(SceneCase):
    def test_label_after_a_move(self):
        """m1: a state still on the old slug — its scenes follow the move chain."""
        self.ready()
        shutil.move(os.path.join(self.root, IMG), os.path.join(self.root, "public/blog-images/c-post"))
        old = os.path.join(self.root, "src/content/blog/%s.md" % SLUG)
        body = open(old).read().replace("/blog-images/%s/" % SLUG, "/blog-images/c-post/")
        os.remove(old)
        store.save_published(self.root, {"articles": [{"slug": "c-post", "path": "src/content/blog/c-post.md",
                                                       "origin": "herald", "moved_from": [{"slug": SLUG}]}]})
        st = {"slug": "c-post", "topic_id": "r-0002"}
        self.write("src/content/blog/c-post.md", body)
        self.assertEqual(images.label_problems(self.root, self.cfg, "r-0002", st), [])
        self.write("src/content/blog/c-post.md", body.replace("*%s*" % LABEL, "", 1))
        self.assertTrue(images.label_problems(self.root, self.cfg, "r-0002", st))

    def test_plan_keeps_regenerated(self):
        """m2"""
        self.generated()
        for f in ("g1-counter.png", "g2-platform.png"):
            os.remove(os.path.join(self.root, IMG, f))
        self.assertEqual(sorted(self.gen(env={"FAKE_LMN_LOCK": "lock2"})["regenerated"]), ["g1", "g2"])
        self.plan()
        self.assertEqual([i["regenerated"] for i in images.status(self.root, self.cfg, TID)["items"]], [True, True])

    def test_orphan_stop_within_the_call(self):
        """m3: the orphan_child stop is capped to the call's room too."""
        self.plan()
        seen = []
        real = limner.run

        def spy(root, cfg, sub, opts=(), timeout=60, command=None):
            seen.append((sub[0], timeout))
            return real(root, cfg, sub, opts, timeout=timeout, command=command)
        with mock.patch.object(images, "GEN_SLACK", 5), mock.patch.object(limner, "run", side_effect=spy):
            self.gen(env={"FAKE_LMN_STATE": "orphan_child"})
        cancels = [t for sub, t in seen if sub == "cancel"]
        # after the probe (`--version`, `run --check`, before the call's budget logic): all capped
        self.assertTrue(all(t <= 5 for _, t in seen[2:]), seen)
        self.assertLessEqual(len(cancels), 2)

    def test_last_place_removed_stops_the_run(self):
        """m4: the only scene dropped while drawn — generate (no scene left) stops the run."""
        self.manifest([self.g1()])
        self.scene_body(g2="")
        self.plan()
        with mock.patch.dict(os.environ, {"FAKE_LMN_STATUS": "10"}):
            rid = self.gen()["run_id"]
        images.reject(self.root, self.cfg, TID, "g1", reason="not needed", drop=True)
        self.manifest([])
        self.scene_body(g1="", g2="")
        self.plan()
        self.assertEqual(self.gen()["state"], "done")
        c = self.gcalls("cancel")
        self.assertEqual(c[-1][c[-1].index("--run-id") + 1], rid)
        self.assertNotIn("gen", self.state()["images"])

    def test_new_run_never_redraws_confirmed(self):
        """m5: a confirmed scene stays out of a new run's job."""
        self.generated()
        images.confirm(self.root, self.cfg, TID, "g1")
        self.manifest([self.g1(), self.g2(seed=8)])
        self.plan()
        out = self.gen(env={"FAKE_LMN_LOCK": "lock2"})
        self.assertEqual((out["state"], out["regenerated"]), ("done", []), out)
        job = json.load(open(os.path.join(self.root, ".limner/herald-jobs/%s.json" % TID)))
        self.assertEqual([j["id"] for j in job["jobs"]], ["g2"])

    def test_label_url_variants(self):
        """m6"""
        self.ready()
        st = self.state()
        r = self.g1()["ref"]
        for form in ("![x](https://example.test%s)", "![x](http://example.test%s)", "![x](//example.test%s)",
                     "![x](https://EXAMPLE.test%s)", "![x](https://www.example.test%s)", "![x](%s?v=2)",
                     "![x][a]\n\n[a]: %s", "<img src=%s alt=x>"):
            with self.subTest(form=form):
                self.scene_body(g1=form % r)
                self.assertTrue(images.label_problems(self.root, self.cfg, TID, st), form)
        self.scene_body(g1="![x](https://elsewhere.test%s)" % r)  # another host: the gate's hotlink rule
        self.assertEqual(images.label_problems(self.root, self.cfg, TID, st), [])

    def test_seed_back_and_forth_is_no_update(self):
        """n7: a seed changed by hand and back — drawn again, but no limner update."""
        self.generated()
        self.manifest([self.g1(seed=42), self.g2()])
        self.plan()
        self.gen()
        self.manifest([self.g1(), self.g2()])
        self.plan()
        out = self.gen()
        self.assertEqual((out["state"], out["regenerated"]), ("done", []), out)

    def test_other_machines_run_is_forgotten(self):
        """n8: a recorded run this machine cannot reach (no limner) is forgotten, not retried."""
        self.generated()
        st = self.state()
        st["images"]["gen"] = {"run_id": "f" * 16, "job_sha256": "x", "waited_s": 0}
        store.save_state(self.root, TID, st)
        os.remove(self.lmn)
        self.assertEqual(self.gen()["state"], "done")
        self.assertNotIn("gen", self.state()["images"])


class StructureTests(unittest.TestCase):
    def test_versions_and_prompts(self):
        plugin = os.path.abspath(os.path.join(HERE, "..", ".."))
        pj = json.load(open(os.path.join(plugin, ".claude-plugin", "plugin.json")))
        mk = json.load(open(os.path.join(plugin, "..", "..", ".claude-plugin", "marketplace.json")))
        sys.path.insert(0, SCRIPTS)
        import hrd
        herald = next(p for p in mk["plugins"] if p["name"] == pj["name"])
        self.assertEqual(len({pj["version"], herald["version"], hrd.SCRIPTS_VERSION}), 1)  # 0.19: the pin moved
        text = open(os.path.join(plugin, "skills", "hrd", "commands", "atoms", "_images.md")).read()
        self.assertIn("## 8. Scene prompts", text)
        self.assertIn("HRD_TEST_ALLOW_FAKE_GENERATOR", text)
        fc = open(os.path.join(plugin, "skills", "hrd", "templates", "agents", "fact-checker.md")).read()
        self.assertIn("scene", fc)


@unittest.skipUnless(os.environ.get("HRD_TEST_LIMNER_GENERATE"),
                     "real limner, fake generator: set HRD_TEST_LIMNER_GENERATE to the limner argv")
class RealLimnerGenerateTests(SceneCase):
    """The real `lmn run`/`status` and its detached worker with limner's fake generator
    (`LIMNER_FAKE_GENERATOR=1` + `HRD_TEST_ALLOW_FAKE_GENERATOR=1`, `S2V_STATE_DIR` a temp dir) — no model."""

    def setUp(self):
        super().setUp()
        self.config(lambda c: c["limner"].update(command=os.environ["HRD_TEST_LIMNER_GENERATE"].split()))
        self.s2v = tempfile.mkdtemp(prefix="hrd-s2v-")
        self.env = {"LIMNER_FAKE_GENERATOR": "1", "HRD_TEST_ALLOW_FAKE_GENERATOR": "1", "S2V_STATE_DIR": self.s2v}

    def tearDown(self):
        shutil.rmtree(self.s2v, ignore_errors=True)
        super().tearDown()

    def test_worker_path(self):
        """R2-2: the worker writes under the state dir only — a checkout of base meanwhile leaves
        the working tree clean; Herald copies on the topic's branch."""
        self.plan()
        with mock.patch.dict(os.environ, dict(self.env, LIMNER_FAKE_SECONDS="3")):
            limner.reset_cache()
            out = images.generate(self.root, self.cfg, TID, wait=0)
            self.assertIn(out["state"], ("running", "done"), out)
            if out["state"] == "running":
                sh(self.root, "git", "stash", "-q", "-u")
                sh(self.root, "git", "switch", "-q", "main")
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    o = subprocess.run(os.environ["HRD_TEST_LIMNER_GENERATE"].split() + [
                        "status", "--run-id", out["run_id"], "--root", os.path.realpath(self.root), "--state-dir",
                        os.path.join(os.path.realpath(self.root), ".limner")], capture_output=True, text=True,
                        env=dict(os.environ))
                    if o.returncode != 10:
                        break
                    time.sleep(1)
                status = sh(self.root, "git", "status", "--porcelain", "--untracked-files=all")
                self.assertEqual([x for x in status.splitlines() if "blog-images" in x], [], status)
                sh(self.root, "git", "switch", "-q", store.branch_name(TID, SLUG))
                sh(self.root, "git", "stash", "pop", "-q")
            deadline = time.monotonic() + 180
            while out["state"] == "running" and time.monotonic() < deadline:
                out = images.generate(self.root, self.cfg, TID, wait=30)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(sorted(x["id"] for x in self.gen_lines()), ["g1", "g2"])
        self.assertEqual(self.gen_lines()[0]["generator"], "fake")
        self.assertTrue(os.path.isfile(os.path.join(self.root, IMG, "g1-counter.png")))


def setUpModule():
    if not os.environ.get("HRD_TEST_LIMNER_GENERATE"):
        sys.stderr.write("test_scenes: the real-limner generate test was not run (set HRD_TEST_LIMNER_GENERATE)\n")


if __name__ == "__main__":
    unittest.main()
