"""Stand-ins and decorative pictures (design/herald/12-generated-fallback-and-decorative.md, 0.21.0):
settings and their own error buckets, `kinds`, brief places (`place_key`) and the hash gate, the
research candidates (`- none: … — searched:`, the fixed section), plan's rules (role from the brief
line, one item per place, the computed `why`, a human's drop, refusals, spent places, the name
checks, decorative limits and positions), review (`--generic-checked`, `--subject-ok`, `--problem
subject`), `generate`'s `blocked`, confirm, reject `--stand-in`, the human-loopback records, fetch
failures, `image skip`, the stage-order rule and its regressions (ship §5 `verify --amend`, single
stage reruns, a tr- translation re-pass), the guard, PR rows, `published.json`, SNS materials and the
record-shrink check of a `--ship` run. A topic with a 0.20.0 brief behaves as 0.20.0 (test_images,
test_scenes and test_ship_consent run on one)."""

import json
import os
import unittest

import test_core
import test_multilingual as tm
from test_images import IMG, PAGE, RESEARCH, SLUG, SRC, TID, W, jpeg_route
from test_scenes import SceneCase
from test_ship_consent import guard_decision, ship_lock

from hrdlib import images, lock, social_media, stand_in, store
from hrdlib.util import HeraldError

PLACE_LABEL = "AI-generated image (not the actual place)"
LABEL = "AI-generated image"
TEMPLE = "- Kiyomizu-dera's wooden stage in autumn — kind: external (place) — the temple paragraph — Second"
LOBBY = "- the office lobby — kind: external (place) — the lobby paragraph — First"
COUNTER = "- a traveler at a counter — kind: scene — the counter paragraph — First"
POSTER = "- the festival poster — kind: external (work) — the poster paragraph — Second"
STREET = "- a quiet street — kind: decorative — — — after \"Second\""
BRIEF = "# Brief\n\n## Images\n%s\n" % "\n".join((TEMPLE, LOBBY, COUNTER, POSTER, STREET))
SEARCHED = "https://commons.wikimedia.org/w/index.php?search=Kiyomizu"
TEMPLE_PROMPT = "A wooden Buddhist temple hall on a wooded hillside among red autumn maples, seen from below"
BODY = """---
title: Renewal guide
description: How to renew
slug: new-post
date: 2026-11-01
category: guide
---
An introduction.

## First

At the counter you say a few words.

{g1}

## Second

The temple sits on a hill above the city.

{g3}

The hill is quiet in the evening.

{dec}## Third

That is all.
"""


def key(line):
    return next(p["place"] for p in stand_in.parse_brief(BRIEF) if p["line"] == line)


def research(temple=None, lobby=None):
    temple = temple if temple is not None else "- none: no free photo of the stage — searched: %s" % SEARCHED
    lobby = lobby if lobby is not None else "- image: %s\n- page: %s\n- credit: Someone\n- license: CC BY-SA 3.0" % (
        SRC, PAGE)
    return ("# Research\n\n**C1.** The fee is 3,000 yen. (https://example.gov/fees)\n\n## Image candidates\n\n"
            "### IC1 — Kiyomizu-dera's stage — place: %s\n%s\n\n### IC2 — the lobby — place: %s\n%s\n\n## Other\n"
            % (key(TEMPLE), temple, key(LOBBY), lobby))


class StandInCase(SceneCase):
    def setUp(self):
        super().setUp()
        self.config(lambda c: c["images"]["scenes"].update(max=4))
        self.inputs(BRIEF, research())
        self.manifest([self.g1(place=key(COUNTER)), self.g3()])
        self.body3()

    def inputs(self, brief=None, res=None):
        """brief.md / research.md written and recorded as passed (their stage hashes)."""
        st = self.state()
        if brief is not None:
            self.write(W + "/brief.md", brief)
            st["stages"]["brief"]["outputs"]["brief.md"] = store.artifact_hash(self.root, self.cfg, st, "brief.md")
        if res is not None:
            self.write(W + "/research.md", res)
            st["stages"]["research"]["outputs"]["research.md"] = store.artifact_hash(self.root, self.cfg, st,
                                                                                    "research.md")
        store.save_state(self.root, TID, st)

    def g3(self, **kw):
        g = {"id": "g3", "kind": "scene", "file": "%s/g3-temple.png" % IMG, "ref": "/blog-images/%s/g3-temple.png" % SLUG,
             "alt": "A wooden temple hall among autumn maples", "purpose": "the temple paragraph — no photo",
             "size": "landscape", "seed": 412, "prompt": TEMPLE_PROMPT, "place": key(TEMPLE),
             "stand_in": {"subject": "place", "names": ["清水寺", "Kiyomizu-dera"], "why": "no-candidates"}}
        g.update(kw)
        return g

    def dec(self, **kw):
        g = {"id": "g4", "kind": "scene", "file": "%s/g4-street.png" % IMG, "ref": "/blog-images/%s/g4-street.png" % SLUG,
             "alt": "A quiet street at dusk", "purpose": "a pause between sections", "size": "landscape", "seed": 5,
             "prompt": "A quiet residential street at dusk with low wooden houses", "place": key(STREET),
             "decorative": True}
        g.update(kw)
        return g

    def snip(self, it, label=None):
        lab = label or (PLACE_LABEL if it.get("stand_in") else LABEL)
        return "![%s](%s)\n*%s*" % (it["alt"], it["ref"], lab)

    def body3(self, g1=None, g3=None, dec=None):
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(
            g1=g1 if g1 is not None else self.snip(self.g1(place=key(COUNTER))),
            g3=g3 if g3 is not None else self.snip(self.g3()), dec=dec or ""))

    def errors(self, items=None):
        if items is not None:
            self.manifest(items)
        return " | ".join(self.plan(check=True)["errors"])

    def push_state(self, **kw):
        st = self.state()
        for k, v in kw.items():
            st[k] = v
        store.save_state(self.root, TID, st)


# --- settings and kinds (§2.2, §2.3, §R1-M4, §R1-M6) -----------------------------------------------

class SettingsTests(StandInCase):
    def test_on_by_default_and_its_switches(self):
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual(k["scene"]["stand_in"], {"ok": True, "why": None, "labels": {
            "place": PLACE_LABEL, "thing": "AI-generated image (not the actual object)"}})
        self.assertEqual(k["scene"]["decorative"], {"max": 0, "why": "no-config"})
        self.assertFalse(k["external"]["decorative"])

        def why(fn):
            self.config(fn)
            return images.kinds(self.root, self.cfg, TID)["scene"]["stand_in"]["why"]
        self.assertEqual(why(lambda c: c["images"]["scenes"].update(stand_in=False)), "off")
        self.assertIsNone(why(lambda c: c["images"]["scenes"].update(stand_in=True)))
        self.assertEqual(why(lambda c: c["images"].update(external=False)), "external:no-config")
        self.assertEqual(why(lambda c: c["images"].update(external=True) or c["images"]["scenes"].update(max=0)),
                         "scene:category")
        self.assertEqual(why(lambda c: c["images"]["scenes"].update(max=4, stand_in_per_category={"guide": False})),
                         "category")
        self.config(lambda c: c["images"]["scenes"].pop("stand_in_per_category"))
        self.rules({"images": {"external": {"max": 3, "licenses": ["CC BY-SA 3.0"], "quotation_categories": ["guide"]}}})
        self.assertEqual(images.kinds(self.root, self.cfg, TID)["scene"]["stand_in"]["why"], "category:works")
        self.assertIsNone(why(lambda c: c["images"]["scenes"].update(stand_in_per_category={"guide": True})))
        os.remove(os.path.join(self.root, "docs/editorial/gate-rules.json"))
        self.config(lambda c: c["images"]["scenes"].update(decorative=1, decorative_per_category={"guide": 2}))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["scene"]["decorative"]["max"], k["external"]["decorative"]), (2, True))
        self.assertEqual(why(lambda c: c["images"].pop("scenes")), "scene:no-config")

    def test_each_mistake_turns_only_its_own_feature_off(self):
        self.config(lambda c: c["images"]["scenes"].update(stand_in="yes"))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["scene"]["ok"], k["scene"]["stand_in"]["ok"], k["scene"]["stand_in"]["why"]),
                         (True, False, "config"))
        self.config(lambda c: c["images"]["scenes"].pop("stand_in") and None or
                    c["images"]["figure"]["words"].update(scene_place="a<b"))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["scene"]["ok"], k["external"]["ok"], k["scene"]["stand_in"]["why"]), (True, True, "config"))
        self.config(lambda c: c["images"]["figure"]["words"].update(scene_place=LABEL))  # says no more than words.scene
        self.assertIn("must say more", " ".join(images.config_errors(self.root, self.cfg)["stand_in_errors"]))
        self.config(lambda c: c["images"]["figure"]["words"].pop("scene_place") and None or
                    c["images"]["scenes"].update(decorative=9))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["scene"]["ok"], k["scene"]["stand_in"]["ok"], k["scene"]["decorative"]),
                         (True, True, {"max": 0, "why": "config"}))
        errs = images.config_errors(self.root, self.cfg)
        self.assertEqual((errs["scene_errors"], errs["figure_errors"]), ([], []))
        self.assertTrue(errs["decorative_errors"])
        # a language without defaults: stand-ins only go off
        self.config(lambda c: c["images"]["scenes"].update(decorative=0) or c.update(language="de") or
                    c["images"]["figure"]["words"].update(scene="KI-generiertes Bild") or
                    c["images"]["og"].update(fallback_first_image=False))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["scene"]["ok"], k["scene"]["stand_in"]["why"]), (True, "label:de"))

    def test_hidden_labels(self):
        self.config(lambda c: c["images"]["figure"].update(stand_in='<img src="{ref}" alt="{alt}"><span class="sr-only">{label}</span>'))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["scene"]["ok"], k["scene"]["stand_in"]["why"]), (True, "config"))
        self.config(lambda c: c["images"]["figure"].pop("stand_in") and None or c["images"]["figure"].update(
            scene='<img src="{ref}" alt="{alt}"><span style="display: none">{label}</span>'))
        self.assertIn("hides its label", " ".join(images.scene_errors(self.cfg)))
        self.assertEqual(images.kinds(self.root, self.cfg, TID)["scene"]["why"], "config")

    def test_labels_by_language_and_template(self):
        for lang, want in (("ko", "AI 생성 이미지(실제 장소 아님)"), ("ja", "AI生成画像（実在の場所ではありません）"), ("en", PLACE_LABEL)):
            self.config(lambda c: c.update(language=lang))
            self.assertTrue(images.snippet_text(self.cfg, self.g3()).endswith("*%s*" % want))
        thing = self.g3(stand_in={"subject": "thing", "names": ["Ekiben"], "why": "no-candidates"})
        self.assertTrue(images.snippet_text(self.cfg, thing).endswith("*AI-generated image (not the actual object)*"))
        self.config(lambda c: c["images"]["figure"].update(stand_in="![{alt}]({ref})\n<em class=stand>{label}</em>"))
        self.assertTrue(images.snippet_text(self.cfg, self.g3()).endswith("<em class=stand>%s</em>" % PLACE_LABEL))
        self.assertEqual(images.snippet_text(self.cfg, self.g1()), "![%s](%s)\n*%s*" % (
            self.g1()["alt"], self.g1()["ref"], LABEL))  # a normal scene keeps its label


# --- places and candidates (§R1-0, §R2-m6, §R4-m3) -------------------------------------------------

class PlaceTests(StandInCase):
    def test_keys_and_the_hash_gate(self):
        pl = stand_in.parse_brief(BRIEF + LOBBY + "\n")
        lobbies = [p for p in pl if p["line"] == LOBBY]
        self.assertEqual(len({p["place"] for p in lobbies}), 2)  # the same line twice: two places
        out = stand_in.places_cmd(self.root, self.cfg, TID)
        self.assertTrue(out["marked"])
        self.assertEqual({p["kind"] for p in out["places"]}, {"external", "scene", "decorative"})
        self.assertEqual(next(p for p in out["places"] if p["line"] == POSTER)["subject"], "work")
        self.inputs(res=research() + "\nmore notes\n")  # research rewritten: the keys stay
        self.assertEqual([p["place"] for p in stand_in.places_cmd(self.root, self.cfg, TID)["places"]],
                         [p["place"] for p in out["places"]])
        self.write(W + "/brief.md", BRIEF + "\nedited\n")  # not the brief that passed: fail-closed
        with self.assertRaises(HeraldError):
            stand_in.places_cmd(self.root, self.cfg, TID)
        self.assertIn("brief changed since it passed", self.errors())
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(TEMPLE))
        self.assertEqual((out["ok"], out["why"]), (False, "brief-changed"))

    def test_candidates(self):
        b = stand_in.parse_candidates(stand_in.candidates_section(research()))
        self.assertEqual(b["IC1"]["place"], key(TEMPLE))
        self.assertEqual((b["IC1"]["images"], b["IC1"]["searched"]), ([], [SEARCHED]))
        self.assertEqual((b["IC2"]["images"], b["IC2"]["licenses"]), ([SRC], {SRC: "CC BY-SA 3.0"}))
        none = stand_in.parse_candidates(stand_in.candidates_section(research(temple="- none: nothing found")))
        self.assertEqual(none["IC1"]["searched"], [])  # no searched URL: never `no-candidates`
        h = stand_in.candidates_hash(research())
        self.assertEqual(stand_in.candidates_hash(research().replace("\n- page:", "  \n\n   - page:")), h)
        self.assertNotEqual(stand_in.candidates_hash(research(lobby="- image: https://x.test/a.jpg")), h)

    def test_old_brief_is_020(self):
        self.inputs("brief\n", RESEARCH)
        self.manifest([self.g1(), self.g2()])
        self.scene_body()
        self.assertEqual(self.errors(), "")  # no place needed, no stand-in
        self.assertIn("needs its place", self.errors([self.g1(), self.g2(stand_in={"subject": "place"})]))


# --- plan (§2.6, §R1, §R2, §R3) ---------------------------------------------------------------------

class PlanTests(StandInCase):
    def test_stand_in_plans_and_records_its_role(self):
        self.assertEqual(self.plan()["errors"], [])
        st = self.state()
        self.assertEqual(st["images"]["items"]["g3"]["role"], "stand-in:place")
        self.assertEqual(st["images"]["files"]["%s/g3-temple.png" % IMG]["role"], "stand-in:place")
        self.assertNotIn("role", st["images"]["items"]["g1"])
        self.assertEqual(st["stand_in_names"][key(TEMPLE)], ["清水寺", "Kiyomizu-dera"])
        self.assertEqual(st["places_seen"][key(TEMPLE)]["role"], "stand-in:place")
        self.assertTrue(st["candidates_hash"].startswith("sha256:"))
        self.assertEqual(self.plan()["pending"]["subject_check"], ["g3"])
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(TEMPLE))
        self.assertEqual((out["ok"], out["why"], out["label"]), (True, "no-candidates", PLACE_LABEL))
        # a new seed keeps the role (it comes from the place, not the key)
        self.manifest([self.g1(place=key(COUNTER)), self.g3(seed=413)])
        self.assertEqual(self.plan()["errors"], [])
        self.assertEqual(self.state()["images"]["items"]["g3"]["role"], "stand-in:place")

    def test_role_comes_from_the_brief(self):
        g1 = self.g1(place=key(COUNTER))
        self.assertIn("place is required", self.errors([self.g1(), self.g3()]))
        self.assertIn("no line of brief.md", self.errors([g1, self.g3(place="0123456789ab")]))
        self.assertIn("cannot fill", self.errors([g1, self.g3(place=key(POSTER))]))  # a work: never drawn instead
        self.assertIn("is a stand-in", self.errors([g1, self.g3(stand_in=None)]))  # the label cannot be dropped
        self.assertIn("stand_in is only for", self.errors([self.g1(place=key(COUNTER), stand_in=self.g3()["stand_in"]),
                                                           self.g3()]))
        self.assertIn("one picture per place", self.errors([g1, self.g3(), self.e1(place=key(TEMPLE))]))
        self.assertIn("names lists", self.errors([g1, self.g3(stand_in={"subject": "place", "names": [],
                                                                       "why": "no-candidates"})]))
        self.assertIn("stand_in.why is", self.errors([g1, self.g3(stand_in={"subject": "place", "names": ["清水寺"],
                                                                            "why": "used-up"})]))

    def test_why_is_computed(self):
        g1 = self.g1(place=key(COUNTER))
        lobby = self.g3(id="g3", place=key(LOBBY), stand_in={"subject": "place", "names": ["Lobby Tower"],
                                                             "why": "used-up"})
        self.assertIn("still has a usable candidate", self.errors([g1, lobby]))
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual(out["why"], "not-yet")
        self.push_state(fetch_failures=[{"id": "e1", "place": key(LOBBY), "source_url": SRC, "code": "http-404"}])
        self.assertEqual(self.errors([g1, lobby]), "")
        self.push_state(fetch_failures=[])
        self.inputs(res=research(lobby="- image: %s\n- page: %s\n- license: CC BY-NC 4.0" % (SRC, PAGE)))
        self.assertEqual(self.errors([g1, lobby]), "")  # a license this repo does not allow counts as gone
        self.inputs(res=research(temple="- none: nothing found"))  # `none` without a searched URL
        self.assertIn("still has a usable candidate", self.errors([g1, self.g3()]))

    def test_a_humans_drop_blocks_and_stand_in_lifts(self):
        g1 = self.g1(place=key(COUNTER))
        self.push_state(image_rejects=[{"id": "e1", "place": key(TEMPLE), "drop": True, "reason": "no"}])
        self.assertIn("a human chose to go without it", self.errors([g1, self.g3()]))
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(TEMPLE))
        self.assertEqual(out["why"], "human-drop")
        lobby = self.g3(place=key(LOBBY), stand_in={"subject": "place", "names": ["Marunouchi Building"], "why": "used-up"})
        self.push_state(image_rejects=[{"id": "e1", "source_url": SRC, "drop": True, "place": key(LOBBY)},
                                       {"id": "e9", "source_url": SRC, "drop": True, "place": "x"}])
        self.assertIn("go without", self.errors([g1, lobby]))
        # a human's `--stand-in`: allowed, and the why is the human's
        self.push_state(image_rejects=[{"id": "e1", "place": key(LOBBY), "source_url": SRC, "drop": True,
                                        "stand_in": True}])
        self.assertIn("records say 'human-chose'", self.errors([g1, lobby]))
        lobby["stand_in"]["why"] = "human-chose"
        self.assertEqual(self.errors([g1, lobby]), "")
        # an agent's drop is no human's: its URL is used up
        self.push_state(image_rejects=[{"id": "e1", "place": key(LOBBY), "source_url": SRC, "drop": True,
                                        "by": "agent"}])
        lobby["stand_in"]["why"] = "used-up"
        self.assertEqual(self.errors([g1, lobby]), "")
        # a 0.20.0 drop without a place turns the whole topic off
        self.push_state(image_rejects=[{"id": "e7", "source_url": "https://x.test/y.jpg", "drop": True}])
        self.assertIn("topic-off:unplaced-drop", self.errors([g1, self.g3()]))

    def test_spent_counts_by_place(self):
        g1 = self.g1(place=key(COUNTER))
        recs = [{"id": "g%d" % n, "key": "sha256:%d" % n, "place": key(TEMPLE), "role": "stand-in:place"}
                for n in (3, 5)]
        self.push_state(review_rejects=recs)
        self.assertEqual(self.errors([g1, self.g3()]), "")  # two turned down: the third picture may come
        self.push_state(review_rejects=recs + [{"id": "g7", "key": "sha256:7", "place": key(TEMPLE),
                                                "role": "stand-in:place"}])
        self.assertIn("were turned down", self.errors([g1, self.g3(id="g8", file="%s/g8-temple.png" % IMG,
                                                                     ref="/blog-images/%s/g8-temple.png" % SLUG)]))
        self.push_state(review_rejects=[], image_rejects=[{"id": "g3", "job": "sha256:1", "place": key(TEMPLE),
                                                           "role": "stand-in:place", "drop": True, "by": "agent"}])
        self.assertIn("were turned down", self.errors([g1, self.g3()]))  # a dropped stand-in: never again

    def test_names_in_alt_and_prompt(self):
        g1 = self.g1(place=key(COUNTER))
        self.assertIn("names the real place", self.errors([g1, self.g3(alt="The stage of Kiyomizu-dera in autumn")]))
        self.assertIn("names the real place", self.errors([g1, self.g3(prompt="A temple hall near Kiyomizu")]))
        self.assertIn("names the real place", self.errors([g1, self.g3(alt="清水寺の本堂")]))
        self.assertIn("names the real place", self.errors([g1, self.g3(alt="kiyomizu dera at dusk")]))
        self.assertEqual(self.errors([g1, self.g3(stand_in={"subject": "place", "names": ["寺", "Kiyomizu-dera"],
                                                          "why": "no-candidates"})]), "")  # one character: ignored

    def test_the_pool_of_left_out_places(self):
        # §R3-M2 test: a blocked place whose candidate title is generic leaves a normal scene alone
        self.inputs(res=research(lobby="- image: %s\n- page: %s\n- title: Japanese maple at Kiyomizu-dera, autumn "
                                       "2019\n- license: CC BY-SA 3.0" % (SRC, PAGE)))
        self.push_state(image_rejects=[{"id": "e1", "place": key(LOBBY), "source_url": SRC, "drop": True}])
        street = self.g1(place=key(COUNTER), prompt="a Japanese street in autumn", alt="A street in autumn")
        self.body3(g1=self.snip(street))
        self.assertEqual(self.errors([street, self.g3()]), "")
        self.body3()
        # a recorded stand-in's names reach every scene of the topic
        self.manifest([self.g1(place=key(COUNTER)), self.g3()])
        self.assertEqual(self.plan()["errors"], [])
        self.assertIn("left out or drawn elsewhere", self.errors([self.g1(place=key(COUNTER),
                                                                          prompt="A traveler near Kiyomizu"), self.g3()]))
        # a blocked brief line's capitalised names, its <what> first word included (§R4-m1)
        brief = BRIEF.replace(LOBBY, "- Fushimi Inari's gate tunnel — kind: external (place) — the gate paragraph — First")
        self.inputs(brief, None)
        fushimi = next(p["place"] for p in stand_in.parse_brief(brief) if "Fushimi" in p["line"])
        self.push_state(image_rejects=[{"id": "e1", "place": fushimi, "drop": True}], stand_in_names={})
        self.assertIn("Fushimi".casefold(), self.errors([self.g1(place=key(COUNTER), prompt="Red gates at Fushimi"),
                                                          self.g3()]).casefold())

    def test_file_name_tokens_in_a_korean_brief(self):
        ko_line = "- 기요미즈데라의 무대 — kind: external (place) — 절 문단 — 둘째 절"
        brief = BRIEF.replace(LOBBY, ko_line)
        k = next(p["place"] for p in stand_in.parse_brief(brief) if p["line"] == ko_line)
        res = research().replace("place: %s" % key(LOBBY), "place: %s" % k).replace(
            PAGE, "https://commons.wikimedia.org/wiki/File:Kiyomizu-dera_main_hall.jpg")
        self.inputs(brief, res)
        self.push_state(image_rejects=[{"id": "e1", "place": k, "drop": True}])
        self.assertIn("kiyomizu", self.errors([self.g1(place=key(COUNTER), prompt="A temple like Kiyomizu"),
                                               self.g3(stand_in={"subject": "place", "names": ["清水寺"],
                                                                 "why": "no-candidates"})]).casefold())

    def test_limits_count_stand_ins_as_scenes(self):
        self.config(lambda c: c["images"]["scenes"].update(max=1))
        self.assertIn("2 scene images — this category allows 1", self.errors())
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(TEMPLE))
        self.assertEqual(out["why"], "scene-max")


class DecorativeTests(StandInCase):
    def setUp(self):
        super().setUp()
        self.config(lambda c: c["images"]["scenes"].update(decorative=1))
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), self.dec()])
        self.body3(dec=self.snip(self.dec()) + "\n\n")

    def test_between_sections(self):
        self.assertEqual(self.errors(), "")
        self.config(lambda c: c["images"]["scenes"].update(decorative=0))
        self.assertIn("1 decorative pictures — this category allows 0", self.errors())
        self.config(lambda c: c["images"]["scenes"].update(decorative=1))
        self.assertIn("decorative must be true", self.errors([self.g1(place=key(COUNTER)), self.g3(),
                                                              self.dec(decorative=False)]))
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), self.dec()])
        snip = self.snip(self.dec())
        cases = [
            (BODY.replace("An introduction.", "An introduction.\n\n" + snip), "before the first section heading"),
            (BODY.replace("That is all.", "That is all.\n\n" + snip), "between sections"),
            (BODY.replace("{dec}", "{dec}"), None),
        ]
        for body, want in cases[:2]:
            self.write("src/content/blog/%s.md" % SLUG, body.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                    g3=self.snip(self.g3()), dec=""))
            self.assertIn(want, self.errors())
        # stacked right on the stand-in
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                g3=self.snip(self.g3()) + "\n\n" + snip, dec=""))
        self.assertIn("not stacked", self.errors())
        # a heading inside a code fence is no section heading
        fenced = BODY.replace("## Third", "```\n## Third\n```\n\n## Third")
        self.write("src/content/blog/%s.md" % SLUG, fenced.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                  g3=self.snip(self.g3()), dec=snip + "\n\n"))
        self.assertIn("right before a section heading", self.errors())

    def test_external_decorative_with_multiline_caption(self):
        """A decorative photo's whole figure (picture line plus caption lines) is what must sit right before
        the heading — not just its reference line (a figcaption template is no misplacement)."""
        self.config(lambda c: c["images"]["scenes"].update(decorative=1))
        e = self.e1(id="e2", place=key(STREET), decorative=True, file="%s/e2-street.jpg" % IMG,
                    ref="/blog-images/%s/e2-street.jpg" % SLUG, alt="A quiet street")
        sn = images.snippet_text(self.cfg, e, "landscape")
        self.assertIn("\n", sn)  # the licensed template carries a caption line after the picture
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), e])
        self.body3(dec=sn + "\n\n")
        self.assertNotIn("right before a section heading", self.errors())
        self.body3(dec=sn + "\n\nA stray paragraph.\n\n")
        self.assertIn("e2: a decorative picture goes right before a section heading", self.errors())

    def test_one_per_boundary_and_external_decorative(self):
        self.config(lambda c: c["images"]["scenes"].update(decorative=2))
        brief = BRIEF + "- a river bank — kind: decorative (scene) — — — after \"Second\"\n"
        self.inputs(brief, None)
        k2 = next(p["place"] for p in stand_in.parse_brief(brief) if "river" in p["line"])
        d2 = self.dec(id="g5", file="%s/g5-river.png" % IMG, ref="/blog-images/%s/g5-river.png" % SLUG, place=k2,
                      alt="A river bank", prompt="A grassy river bank under a pale sky")
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), self.dec(), d2])
        self.body3(dec=self.snip(self.dec()) + "\n\n" + self.snip(d2) + "\n\n")  # two at one boundary
        errs = self.errors()
        self.assertIn("g4: a decorative picture goes right before a section heading", errs)
        self.assertIn("g5: a decorative picture is not stacked", errs)
        # a decorative photo is licensed, never a quotation; `decorative (scene)` takes no photo
        e = self.e1(place=key(STREET), decorative=True, use="quotation")
        self.assertIn("licensed — never a quotation", self.errors([self.g1(place=key(COUNTER)), self.g3(), e]))
        self.assertIn("cannot fill", self.errors([self.g1(place=key(COUNTER)), self.g3(), self.e1(place=k2,
                                                                                                  decorative=True)]))

    def test_a_stand_in_is_never_the_first_image(self):
        self.manifest([self.g3()])
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1="", g3=self.snip(self.g3()), dec=""))
        self.assertIn("never the article's first image", self.errors())
        self.write("src/content/blog/%s.md" % SLUG, BODY.replace("An introduction.", "An introduction.\n\n{g3}").replace(
            "The temple sits on a hill above the city.\n\n{g3}", "x").format(g1="", g3=self.snip(self.g3()), dec=""))
        self.assertIn("before the first section heading", self.errors())


# --- review, generate, confirm (§2.10, §2.10a, §R1-B1, §R1-m2, §R2-m1) -----------------------------

class ReviewTests(StandInCase):
    def subject_ok(self):
        return images.review(self.root, self.cfg, TID, "g3", subject_ok=True, note="a temple, a real place")

    def test_subject_check_before_generating(self):
        self.assertEqual(self.plan()["errors"], [])
        out = self.gen()
        self.assertEqual((out["state"], out["blocked"]), ("blocked", [{"id": "g3", "why": "subject-check"}]))
        self.assertEqual(self.gcalls("run"), [])  # no run started
        with self.assertRaises(HeraldError):  # a normal scene takes no subject check
            images.review(self.root, self.cfg, TID, "g1", subject_ok=True, note="x")
        self.subject_ok()
        self.assertEqual(images.status(self.root, self.cfg, TID)["pending"]["subject_check"], [])
        self.assertEqual(self.gen()["state"], "done")
        # the stricter look: `--ok` needs `--generic-checked` for the stand-in, not for g1
        with self.assertRaises(HeraldError) as cm:
            images.review(self.root, self.cfg, TID, "g3", ok=True, note="fine")
        self.assertIn("--generic-checked", str(cm.exception))
        images.review(self.root, self.cfg, TID, "g1", ok=True, note="fine")
        images.review(self.root, self.cfg, TID, "g3", ok=True, generic_checked=True, note="generic, no landmark")
        self.assertTrue(next(i for i in images.status(self.root, self.cfg, TID)["items"] if i["id"] == "g3")[
            "generic_checked"])
        rows = "\n".join(images.status(self.root, self.cfg, TID)["pr_rows"])
        self.assertIn("scene (AI-generated, stand-in for %s: 清水寺 / Kiyomizu-dera — not the real place; no-candidates "
                      "(searched: %s)" % (key(TEMPLE), SEARCHED), rows)
        self.assertIn("generic checks passed", rows)
        # a redo counts by place
        out = images.review(self.root, self.cfg, TID, "g3", redo=True, note="looks like the real stage")
        self.assertEqual(out["attempts"], 2)
        self.assertEqual(self.state()["review_rejects"][-1]["place"], key(TEMPLE))

    def test_problem_subject_refuses_and_removes(self):
        self.assertEqual(self.plan()["errors"], [])
        self.subject_ok()
        self.assertEqual(self.gen()["state"], "done")
        out = images.review(self.root, self.cfg, TID, "g3", problem="subject", note="the stage is a work's set")
        self.assertEqual((out["refused"], out["removed"]), ([key(TEMPLE)], ["g3"]))
        self.assertEqual(self.gen()["state"], "blocked")
        st = self.state()
        self.assertEqual((st["images"]["awaiting"], st["images"]["items"]["g3"]["status"], st["last_loopback"]),
                         (False, "pending", "review"))
        self.assertFalse(os.path.exists(os.path.join(self.root, IMG, "g3-temple.png")))
        self.assertFalse(images.resume_at_collect(self.root, self.cfg, st))
        # every point refuses it until the illustrator removes it
        self.assertIn("not a place or thing", self.errors())
        with self.assertRaises(HeraldError):
            images.confirm(self.root, self.cfg, TID, "g3")
        self.assertIn("this stand-in may not go on (refused)", " ".join(images.draft_problems(self.root, self.cfg, TID,
                                                                                              self.state())))
        self.assertIn("refused", " ".join(images.verify_problems(self.root, self.cfg, TID, self.state(), {})))
        self.assertIn("not a place or thing", self.errors([self.g1(place=key(COUNTER)), self.e1(place=key(TEMPLE))]))
        # a new seed changes nothing
        self.assertIn("not a place or thing", self.errors([self.g1(place=key(COUNTER)), self.g3(seed=99)]))
        # `--allow` cannot lift a human's own refusal; it lifts a review's
        _, p = self.hrd("image", "stand-in", "--topic", TID, "--place", key(TEMPLE), "--allow", "--reason", "x",
                        check=False, env={"HRD_UNATTENDED": "1"})
        self.assertIn("not allowed in unattended", p.stderr)
        self.hrd("image", "stand-in", "--topic", TID, "--place", key(TEMPLE), "--allow", "--reason", "it is a temple")
        self.assertNotIn("not a place or thing", self.errors([self.g1(place=key(COUNTER)), self.g3(seed=99)]))
        _, p = self.hrd("image", "review", "--topic", TID, "--id", "g3", "--problem", "subject", "--human", "--note",
                        "a set", check=False, env={"HRD_UNATTENDED": "1"})
        self.assertIn("not allowed in unattended", p.stderr)
        self.manifest([self.g1(place=key(COUNTER)), self.g3(seed=99)])
        self.hrd("image", "review", "--topic", TID, "--id", "g3", "--problem", "subject", "--human", "--note", "a set")
        _, p = self.hrd("image", "stand-in", "--topic", TID, "--place", key(TEMPLE), "--allow", "--reason", "x",
                        check=False)
        self.assertIn("a human judged", p.stderr)
        self.assertIn("not a place or thing (human)", "\n".join(images.status(self.root, self.cfg, TID)["pr_rows"]))

    def test_subject_problem_on_an_external_image_and_a_borrowed_scene(self):
        e1 = self.e1(place=key(LOBBY))
        self.manifest([self.g1(place=key(COUNTER)), e1])
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                g3="![The office lobby](%s)" % e1["ref"], dec=""))
        self.assertEqual(self.plan()["errors"], [])
        images.review(self.root, self.cfg, TID, "e1", problem="subject", note="a mascot statue is the subject")
        self.assertEqual(self.plan(check=True)["errors"], [])  # the photo stays
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual(out["why"], "refused")
        with self.assertRaises(HeraldError):  # a borrowed scene names the place it redraws
            images.review(self.root, self.cfg, TID, "g1", problem="subject", note="redraws the lobby")
        images.review(self.root, self.cfg, TID, "g1", problem="subject", note="redraws the lobby", place=key(LOBBY))
        self.assertIn("redraws a blocked place", self.errors())
        st = self.state()
        st["stage"] = "critique"
        store.save_state(self.root, TID, st)
        with self.assertRaises(HeraldError):  # draft only
            images.review(self.root, self.cfg, TID, "e1", problem="subject", note="x")


    def test_a_blocked_stand_in_is_refused_everywhere_until_removed(self):
        # R1-B1's points with a picture in place: review --ok, confirm (human and --agent), the draft pass
        self.assertEqual(self.plan()["errors"], [])
        self.subject_ok()
        self.assertEqual(self.gen()["state"], "done")
        self.push_state(image_rejects=[{"id": "e1", "place": key(TEMPLE), "drop": True, "via": "human-push"}])
        with self.assertRaises(HeraldError) as cm:
            images.review(self.root, self.cfg, TID, "g3", ok=True, generic_checked=True, note="fine")
        self.assertIn("human-drop", str(cm.exception))
        with self.assertRaises(HeraldError):
            images.confirm(self.root, self.cfg, TID, "g3")
        ship_lock(self.root)
        with self.assertRaises(HeraldError):
            images.confirm(self.root, self.cfg, TID, "g3", agent=True)
        lock.force_unlock(self.root)
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "draft", check=False)
        self.assertIn("this stand-in may not go on (human-drop)", p.stderr)
        # the illustrator removes it: nothing about it is left
        self.manifest([self.g1(place=key(COUNTER))])
        self.body3(g3="")
        self.assertEqual(self.plan()["errors"], [])
        self.assertNotIn("g3", " ".join(images.draft_problems(self.root, self.cfg, TID, self.state())))

    def test_an_agent_never_passes_a_stand_in_without_the_generic_look(self):
        self.assertEqual(self.plan()["errors"], [])
        self.subject_ok()
        self.assertEqual(self.gen()["state"], "done")
        images.review(self.root, self.cfg, TID, "g3", ok=True, generic_checked=True, note="generic")
        st = self.state()
        st["images"]["items"]["g3"].pop("reviewed_generic")
        store.save_state(self.root, TID, st)
        ship_lock(self.root)
        with self.assertRaises(HeraldError) as cm:
            images.confirm(self.root, self.cfg, TID, "g3", agent=True)
        self.assertIn("--generic-checked", str(cm.exception))


# --- reject (§2.7, §R1-M7) ---------------------------------------------------------------------------

class RejectTests(StandInCase):
    def setUp(self):
        super().setUp()
        self.e = self.e1(place=key(LOBBY))
        self.manifest([self.g1(place=key(COUNTER)), self.e])
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                g3="![The office lobby](%s)" % self.e["ref"], dec=""))
        self.route(SRC, jpeg_route())
        self.assertEqual(self.fetch()["failed"], [])
        self.put_lobby()
        self.assertEqual(self.plan()["errors"], [])

    def put_lobby(self):
        sn = images.snippet(self.root, self.cfg, TID, "e1")["snippet"]
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))), g3=sn, dec=""))

    def test_a_human_chooses_a_stand_in(self):
        with self.assertRaises(HeraldError):
            images.reject(self.root, self.cfg, TID, "e1", reason="x", as_stand_in=True)  # needs --drop
        with self.assertRaises(HeraldError):
            images.reject(self.root, self.cfg, TID, "e1", reason="x", drop=True, refetch=True, as_stand_in=True)
        with self.assertRaises(HeraldError):
            images.reject(self.root, self.cfg, TID, "g1", reason="x", drop=True, as_stand_in=True)  # a scene
        out = images.reject(self.root, self.cfg, TID, "e1", reason="no good photo", drop=True, as_stand_in=True)
        self.assertIn("stand-in", out["next"])
        rj = self.state()["image_rejects"][-1]
        self.assertEqual((rj["place"], rj["stand_in"], rj["drop"]), (key(LOBBY), True, True))
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual((out["ok"], out["why"]), (True, "human-chose"))
        self.assertIn("→ AI stand-in: no usable photo (a human chose)",
                      "\n".join(images.status(self.root, self.cfg, TID)["pr_rows"]))
        _, p = self.hrd("image", "reject", "--topic", TID, "--id", "e1", "--drop", "--stand-in", "--reason", "x",
                        check=False, env={"HRD_UNATTENDED": "1"})
        self.assertIn("unattended", p.stderr)

    def test_a_human_drop_or_an_agent(self):
        images.reject(self.root, self.cfg, TID, "e1", reason="go without", drop=True)
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual(out["why"], "human-drop")

    def test_an_agent_drops_only_after_two_rejects(self):
        src2 = "https://upload.wikimedia.org/wikipedia/commons/b/bb/Lobby2.jpg"
        self.inputs(None, research(lobby="- image: %s\n- page: %s\n- license: CC BY-SA 3.0\n- image: %s\n- page: %s\n"
                                         "- license: CC BY-SA 3.0" % (SRC, PAGE, src2, PAGE)))
        self.assertEqual(self.plan()["errors"], [])
        ship_lock(self.root)
        with self.assertRaises(HeraldError) as cm:
            images.reject(self.root, self.cfg, TID, "e1", reason="x", drop=True, agent=True)
        self.assertIn("reject without --drop first", str(cm.exception))
        with self.assertRaises(HeraldError):
            images.reject(self.root, self.cfg, TID, "e1", reason="x", drop=True, agent=True, as_stand_in=True)
        # the real path: a fresh review's redo, then the agent's reject — twice, one id after another
        images.review(self.root, self.cfg, TID, "e1", redo=True, note="watermark")
        images.reject(self.root, self.cfg, TID, "e1", reason="watermark", agent=True)
        e2 = dict(self.e, id="e2", file="%s/e2-lobby.jpg" % IMG, ref="/blog-images/%s/e2-lobby.jpg" % SLUG,
                  source_url=src2)
        self.manifest([self.g1(place=key(COUNTER)), e2])
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                g3="![The office lobby](%s)" % e2["ref"], dec=""))
        self.route(src2, jpeg_route())
        self.assertEqual(self.fetch()["failed"], [])
        self.assertEqual(images.agent_rejects(self.state(), "e2", key(LOBBY)), 1)  # another id: the same place
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual(out["why"], "not-yet")  # src2 is still usable
        images.review(self.root, self.cfg, TID, "e2", redo=True, note="another country's lobby")
        images.reject(self.root, self.cfg, TID, "e2", reason="another country's lobby", agent=True)
        self.assertEqual(images.agent_rejects(self.state(), "e2", key(LOBBY)), 2)
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual((out["ok"], out["why"]), (True, "used-up"))  # the agent's rejects used it up

    def test_an_agent_drops_a_work_at_once(self):
        brief = BRIEF.replace(LOBBY, LOBBY.replace("external (place)", "external (work)"))
        res = research().replace(key(LOBBY), next(p["place"] for p in stand_in.parse_brief(brief)
                                                   if "lobby" in p["line"]))
        self.inputs(brief, res)
        k = next(p["place"] for p in stand_in.parse_brief(brief) if "lobby" in p["line"])
        self.manifest([self.g1(place=key(COUNTER)), dict(self.e, place=k)])
        self.put_lobby()
        self.assertEqual(self.plan()["errors"], [])
        ship_lock(self.root)
        images.reject(self.root, self.cfg, TID, "e1", reason="a mascot's rights", drop=True, agent=True)  # as 0.20.0


# --- section images: `external (sign)` (design/herald/14-section-images.md D2, 0.23.0) ---------------

class SignTests(StandInCase):
    """A section whose point is written words gets a photo of the sign or nothing — never a picture
    drawn instead (P28: text is never generated)."""

    def setUp(self):
        super().setUp()
        self.sign = LOBBY.replace("the office lobby", "the 免税 sign at the counter").replace(
            "external (place)", "external (sign)")
        self.brief = BRIEF.replace(LOBBY, self.sign)
        self.k = next(p["place"] for p in stand_in.parse_brief(self.brief) if p["line"] == self.sign)
        self.inputs(self.brief, research().replace(key(LOBBY), self.k))
        self.e = self.e1(place=self.k)
        self.manifest([self.g1(place=key(COUNTER)), self.e])
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                g3="![The tax-free sign](%s)" % self.e["ref"], dec=""))
        self.route(SRC, jpeg_route())
        self.assertEqual(self.fetch()["failed"], [])
        sn = images.snippet(self.root, self.cfg, TID, "e1")["snippet"]
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))), g3=sn, dec=""))
        self.assertEqual(self.plan()["errors"], [])

    def test_a_sign_line_parses_and_a_guide_line_is_no_place(self):
        guide = '- guide: "illustrator on: one route diagram - the usual" → names diagram ≤1'
        pl = stand_in.parse_brief(self.brief.replace("## Images\n", "## Images\n%s\n" % guide))
        self.assertEqual(next(p for p in pl if p["place"] == self.k)["subject"], "sign")
        self.assertFalse(any(p["line"].startswith("- guide:") for p in pl))
        self.assertTrue(stand_in.marked(pl))
        self.assertIn("sign", stand_in.SUBJECTS)
        self.assertNotIn("sign", stand_in.STAND_IN_SUBJECTS)

    def test_no_stand_in_for_a_sign(self):
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", self.k)
        self.assertEqual((out["ok"], out["why"]), (False, "subject:sign"))
        with self.assertRaises(HeraldError) as cm:
            images.reject(self.root, self.cfg, TID, "e1", reason="no good photo", drop=True, as_stand_in=True)
        self.assertIn("--stand-in is for", str(cm.exception))
        images.reject(self.root, self.cfg, TID, "e1", reason="go without", drop=True)  # going without works
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", self.k)
        self.assertFalse(out["ok"])

    def test_a_scene_cannot_fill_a_sign_line(self):
        line = next(p for p in stand_in.parse_brief(self.brief) if p["place"] == self.k)
        self.assertEqual(line["subject"], "sign")  # the subject path, not an unmarked external line
        g = self.g3(id="g3", place=self.k, stand_in={"subject": "sign", "names": ["免税"], "why": "no-candidates"})
        self.assertIsNone(stand_in.role_of(g, line))
        place = dict(line, subject="place")  # the same line as `external (place)` is a stand-in's
        self.assertEqual(stand_in.role_of(self.g3(), place), "stand-in:place")
        self.assertIn("cannot fill", self.errors([self.g1(place=key(COUNTER)), g]))
        self.assertIn("cannot fill", self.errors([self.g1(place=key(COUNTER)), self.g3(place=self.k, stand_in=None)]))

    def test_image_places_shows_the_sign_subject(self):
        out, _ = self.hrd("image", "places", "--topic", TID)
        self.assertEqual(next(p for p in out["places"] if p["place"] == self.k)["subject"], "sign")

    def test_no_quotation_on_a_sign_line(self):
        q = dict(self.e, use="quotation")
        q.pop("license", None)
        self.assertIn("a quotation fills an `external (quotation)` line only",
                      self.errors([self.g1(place=key(COUNTER)), q]))


# --- records: human loopback, fetch failures, skip (§R1-M3, §R2-M3, §R2-M4, §R3-m4) -----------------

class RecordTests(StandInCase):
    def lobby_planned(self):
        self.e = self.e1(place=key(LOBBY))
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), self.e])
        self.write("src/content/blog/%s.md" % SLUG, BODY.replace("That is all.", "{e1}\n\nThat is all.").format(
            g1=self.snip(self.g1(place=key(COUNTER))), g3=self.snip(self.g3()), dec="",
            e1="![The office lobby](%s)" % self.e["ref"]))
        self.assertEqual(self.plan()["errors"], [])

    def test_a_human_loopback_that_leaves_a_place_out(self):
        self.lobby_planned()
        self.hrd("loopback", "--topic", TID, "--human")
        self.assertTrue(self.state()["human_loopback"])
        self.manifest([self.g1(place=key(COUNTER)), self.g3()])
        self.body3()
        self.assertEqual(self.plan()["errors"], [])
        rj = [r for r in self.state()["image_rejects"] if r.get("via") == "human-loopback"]
        self.assertEqual([(r["place"], r["id"], r["drop"]) for r in rj], [(key(LOBBY), "e1", True)])
        lobby = self.g3(id="g5", file="%s/g5-lobby.png" % IMG, ref="/blog-images/%s/g5-lobby.png" % SLUG,
                        place=key(LOBBY), alt="An office lobby", prompt="A bright office lobby with a reception desk",
                        stand_in={"subject": "place", "names": ["Marunouchi Building"], "why": "used-up"})
        self.assertIn("go without", self.errors([self.g1(place=key(COUNTER)), self.g3(), lobby]))

    def test_used_up_or_no_loopback_records_nothing(self):
        self.lobby_planned()
        images.reject(self.root, self.cfg, TID, "e1", reason="another photo")  # a reject is no human loopback
        self.assertNotIn("human_loopback", self.state())
        self.manifest([self.g1(place=key(COUNTER)), self.g3()])
        self.body3()
        self.assertEqual(self.plan()["errors"], [])
        self.assertFalse([r for r in self.state()["image_rejects"] if r.get("via")])

    def test_a_human_loopback_swapping_a_used_up_photo_records_nothing(self):
        self.lobby_planned()
        self.hrd("loopback", "--topic", TID, "--human")
        self.push_state(fetch_failures=[{"id": "e1", "place": key(LOBBY), "source_url": SRC, "code": "http-404"}])
        lobby = self.g3(id="g5", file="%s/g5-lobby.png" % IMG, ref="/blog-images/%s/g5-lobby.png" % SLUG,
                        place=key(LOBBY), alt="An office lobby", prompt="A bright office lobby with a reception desk",
                        stand_in={"subject": "place", "names": ["Marunouchi Building"], "why": "used-up"})
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), lobby])
        self.body3(dec=self.snip(lobby) + "\n\nMore.\n\n")
        self.assertEqual(self.plan()["errors"], [])
        self.assertFalse([r for r in (self.state().get("image_rejects") or []) if r.get("via")])

    def test_fetch_failures_and_skip(self):
        self.lobby_planned()
        self.route(SRC, (404, {}, b""))
        out = self.fetch()
        self.assertEqual(out["failed"][0]["class"], "content")
        self.assertEqual([(r["id"], r["place"], r["code"]) for r in self.state()["fetch_failures"]],
                         [("e1", key(LOBBY), out["failed"][0]["code"])])
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual(out["why"], "used-up")
        # an env failure is no evidence
        self.push_state(fetch_failures=[])
        self.route(SRC, (503, {}, b""))
        self.assertEqual(self.fetch()["failed"][0]["class"], "env")
        self.assertEqual(self.state()["fetch_failures"], [])
        # skip: only a URL this machine fetched, never in a --ship run
        with self.assertRaises(HeraldError):
            stand_in.skip(self.root, self.cfg, TID, key(LOBBY), SRC, "wrong building")
        self.route(SRC, jpeg_route())
        self.assertEqual(self.fetch()["failed"], [])
        ship_lock(self.root)
        with self.assertRaises(HeraldError):
            stand_in.skip(self.root, self.cfg, TID, key(LOBBY), SRC, "wrong building")
        lock.force_unlock(self.root)
        stand_in.skip(self.root, self.cfg, TID, key(LOBBY), SRC, "wrong building")
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual(out["why"], "used-up")
        # a skip made during a human loopback does not make it used up for the auto record (§R3-m4)
        st = self.state()
        st["candidate_skips"][-1]["human_loopback"] = True
        b = stand_in.block_of(stand_in.candidate_blocks(self.root, TID, st), key(LOBBY))
        self.assertFalse(stand_in.used_up(st, b, ["CC BY-SA 3.0"], during_loopback=False))

    def test_removed_by_a_human_push(self):
        self.lobby_planned()
        self.commit("work")
        self.manifest([self.g1(place=key(COUNTER)), self.g3()])
        self.body3()
        head = self.commit("a human removed the lobby")
        out = stand_in.removed(self.root, self.cfg, TID, head)
        self.assertEqual(out["recorded"], [key(LOBBY)])
        self.assertEqual(self.state()["image_rejects"][-1]["via"], "human-push")
        self.assertEqual(stand_in.removed(self.root, self.cfg, TID, head)["recorded"], [])  # once


# --- stage order (§R3-M1, §R3-m2, §R4-m2) and its regressions ------------------------------------------

class StageOrderTests(StandInCase):
    def test_brief_and_research_do_not_pass_again(self):
        for stage in ("brief", "research"):
            _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", stage, check=False)
            self.assertIn("passed already", p.stderr)
            _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", stage, "--rerun", check=False,
                            env={"HRD_UNATTENDED": "1"})
            self.assertIn("unattended", p.stderr)
        ship_lock(self.root)
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "brief", "--re", check=False)
        self.assertIn("--ship", p.stderr)  # argparse takes the prefix; the code refuses it

    def test_a_humans_rerun_and_orphans(self):
        self.push_state(image_rejects=[{"id": "e1", "place": key(LOBBY), "drop": True}])
        self.write(W + "/brief.md", BRIEF.replace(LOBBY + "\n", ""))
        out, _ = self.hrd("stage", "pass", "--topic", TID, "--stage", "brief", "--rerun")
        self.assertEqual(out["stage"], "research")
        self.assertTrue(self.state()["stand_in_orphaned"])
        self.assertIn("topic-off:orphaned", self.errors())

    def test_research_fix_and_the_fixed_candidates(self):
        self.assertEqual(self.plan()["errors"], [])  # records candidates_hash (a pre-0.21 research pass)
        st = self.state()
        st["research_fixes"] = [{"status": "open", "claims": ["C1"], "ids_before": ["C1"], "research_before": "x"}]
        store.save_state(self.root, TID, st)
        self.write(W + "/research.md", research().replace("3,000 yen", "3,500 yen").replace("- page:", "  - page:"))
        self.hrd("stage", "pass", "--topic", TID, "--stage", "research")  # a fix passes, whitespace is no change
        st = self.state()
        st["research_fixes"].append({"status": "open", "claims": ["C1"], "ids_before": ["C1"], "research_before": "x"})
        st["stage"] = "draft"
        store.save_state(self.root, TID, st)
        self.write(W + "/research.md", research(lobby="- image: https://upload.wikimedia.org/x.jpg"))
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "research", check=False)
        self.assertIn("image candidates are fixed", p.stderr)

    def test_other_stages_rerun_as_before(self):
        for stage in ("draft", "critique", "translation", "verify", "publish"):
            st = dict(self.state(), stage="publish")
            self.assertIsNone(store._repass_refusal(self.root, TID, st, stage, False), stage)

    def test_inherited_gate_needs_tr(self):
        st = {"topic_id": "t0001", "stages": {"brief": {"inherited": True}}}
        self.assertFalse(stand_in.inherited(st, "brief"))
        self.assertTrue(stand_in.inherited(dict(st, topic_id="tr-x"), "brief"))


class ReverifyRegressionTests(test_core.Flow):
    def test_ship_5_amend_from_publish_and_single_stage_reruns(self):
        tid, slug = self.run_flow()
        self.assertEqual(store.load_state(self.root, tid)["stage"], "publish")
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify", "--amend")  # ship §5
        self.hrd("stage", "pass", "--topic", tid, "--stage", "verify")  # /hrd verify again
        test_core.write_machine(self, tid, "critique.json", test_core.CRIT_PASS, slug)
        self.hrd("stage", "pass", "--topic", tid, "--stage", "critique")  # /hrd critique again
        self.hrd("stage", "pass", "--topic", tid, "--stage", "draft")  # /hrd draft again (stage was verify)
        _, p = self.hrd("stage", "pass", "--topic", tid, "--stage", "brief", check=False)
        self.assertIn("passed already", p.stderr)


class TranslationRepassTests(tm.TranslationFlow):
    published_untranslated = tm.LaterTranslationTests.published_untranslated
    add_tr = tm.LaterTranslationTests.add_tr

    def test_tr_translation_passes_again_after_its_loopback(self):
        slug = self.published_untranslated()
        tid = self.add_tr(slug, ["ja"])
        self.hrd("begin", "--topic", tid)
        self.hrd("branch", "--topic", tid, "--slug", slug)
        self.hrd("remap", "--topic", tid)
        self.translate(slug, "ja", claims=("C2",))
        _, p = self.tpass(tid, check=False)
        self.assertIn("C2", p.stderr)
        self.hrd("loopback", "--topic", tid, "--cause", "translation")
        self.translate(slug, "ja")
        self.assertEqual(self.tpass(tid)[0]["stage"], "verify")
        st = store.load_state(self.root, tid)
        self.assertTrue(stand_in.inherited(st, "brief"))
        self.assertEqual(stand_in.places(self.root, tid, st), [])  # no gate for an inherited brief


# --- guard, records and outputs (§R3-m1, §R4-m2, §R4-m5, §2.13) ----------------------------------------

class GuardTests(StandInCase):
    def test_rerun_allow_and_a_humans_subject(self):
        hrd = "python3 .claude/herald/scripts/hrd.py "
        g = lambda c, env=None: guard_decision(self.root, "Bash", {"command": hrd + c}, env)  # noqa: E731
        self.assertEqual(g("stage pass --topic t0001 --stage brief"), "none")
        for c in ("stage pass --topic t0001 --stage brief --rerun", "stage pass --topic t0001 --stage brief --re",
                  "stage pass --topic t0001 --rer --stage research",
                  "image review --topic t0001 --id g3 --problem subject --human --note x",
                  "image stand-in --topic t0001 --place abc --allow --reason x"):
            self.assertEqual(g(c), "ask", c)
        self.assertEqual(g("stage pass --topic t0001 --stage brief", {"HRD_UNATTENDED": "1"}), "none")
        self.assertEqual(g("stage pass --topic t0001 --stage brief --rerun", {"HRD_UNATTENDED": "1"}), "deny")
        self.assertEqual(g("stage pass --topic t0001 --stage verify --amend"), "none")
        self.assertEqual(g("image review --topic t0001 --id g3 --subject-ok --note --rerun"), "none")
        self.assertEqual(g("image stand-in --topic t0001 --place abc"), "none")


class OutputTests(StandInCase):
    def test_published_sns_and_slug_labels(self):
        self.config(lambda c: c["images"]["scenes"].update(decorative=1))
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), self.dec()])
        self.body3(dec=self.snip(self.dec()) + "\n\n")
        self.assertEqual(self.plan()["errors"], [])
        self.assertEqual(store.stand_in_record(self.root, TID), {
            "stand_ins": [{"id": "g3", "of": key(TEMPLE), "names": ["清水寺", "Kiyomizu-dera"], "why": "no-candidates"}],
            "decorative": ["g4"]})
        rows = "\n".join(images.status(self.root, self.cfg, TID)["pr_rows"])
        self.assertIn("| g4 | scene (AI-generated, decorative) |", rows)
        # the slug-wide label check: the plain AI label on a stand-in's file is wrong
        self.assertEqual(images.label_problems(self.root, self.cfg, TID, self.state()), [])
        self.body3(g3=self.snip(self.g3(), label=LABEL), dec=self.snip(self.dec()) + "\n\n")
        self.assertTrue(images.label_problems(self.root, self.cfg, TID, self.state()))
        # SNS materials: a confirmed stand-in never goes, a confirmed decorative scene does
        self.body3(dec=self.snip(self.dec()) + "\n\n")
        self.assertEqual(self.plan()["errors"], [])
        images.review(self.root, self.cfg, TID, "g3", subject_ok=True, note="a temple")
        self.assertEqual(self.gen()["state"], "done")
        images.confirm(self.root, self.cfg, TID, "g1,g3,g4")
        self.assertEqual(self.plan()["errors"], [])
        self.commit("pictures")
        mats = social_media.materials(self.root, self.cfg, SLUG, False)
        paths = {m["path"] for m in mats}
        self.assertIn("%s/g4-street.png" % IMG, paths)
        self.assertIn("%s/g1-counter.png" % IMG, paths)
        self.assertNotIn("%s/g3-temple.png" % IMG, paths)

    def test_records_shrank(self):
        self.push_state(image_rejects=[{"id": "e1", "place": key(LOBBY), "drop": True}])
        self.commit("work")
        self.assertEqual(stand_in.records_shrank(self.root, self.cfg, TID, "HEAD"), [])
        self.push_state(image_rejects=[])
        bad = self.commit("drop the record")
        self.assertEqual(stand_in.records_shrank(self.root, self.cfg, TID, "HEAD"), [bad])
        self.write(W + "/critique.json", "{}")
        self.commit("critique")
        self.assertIn("stand-in-records-shrank", store.exclusion_reasons(self.root, self.cfg, TID, rev="HEAD",
                                                                          vouch=True))
        self.assertNotIn("stand-in-records-shrank", store.exclusion_reasons(self.root, self.cfg, TID, rev="HEAD"))

    def test_unvouched_blocked_stand_in(self):
        self.assertEqual(self.plan()["errors"], [])
        images.review(self.root, self.cfg, TID, "g3", subject_ok=True, note="a temple")
        self.assertEqual(self.gen()["state"], "done")
        images.confirm(self.root, self.cfg, TID, "g1,g3")
        self.commit("pictures")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", SLUG), [])
        self.push_state(stand_in_refused=[{"place": key(TEMPLE), "id": "g3", "by": "human"}])
        self.commit("refused")
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", SLUG), ["%s/g3-temple.png" % IMG])


if __name__ == "__main__":
    unittest.main()


# --- implementation review round 1 (design/herald/REVIEW-26, B1, M1–M4, m2–m9) ------------------------

class ReviewRoundOneTests(StandInCase):
    def confirmed(self):
        self.assertEqual(self.plan()["errors"], [])
        images.review(self.root, self.cfg, TID, "g3", subject_ok=True, note="a temple")
        self.assertEqual(self.gen()["state"], "done")
        images.review(self.root, self.cfg, TID, "g3", ok=True, generic_checked=True, note="generic")
        images.review(self.root, self.cfg, TID, "g1", ok=True, note="fine")
        images.confirm(self.root, self.cfg, TID, "g1,g3")

    def test_b1_a_stand_in_moved_to_a_scene_line_keeps_its_role(self):
        hill_line = "- a hillside view — kind: scene — the temple paragraph — Second"
        brief = BRIEF.replace(STREET, hill_line + "\n" + STREET)
        self.inputs(brief, research())
        hill = next(p["place"] for p in stand_in.parse_brief(brief) if p["line"] == hill_line)
        self.confirmed()
        g3 = self.g3(place=hill)
        g3.pop("stand_in")
        self.manifest([self.g1(place=key(COUNTER)), g3])
        self.body3(g3=self.snip(g3, label=LABEL))
        self.assertIn("was a stand-in", " | ".join(self.plan()["errors"]))
        self.assertTrue(images.label_problems(self.root, self.cfg, TID, self.state()))  # its label stays
        self.assertNotEqual(images.scene_key(self.cfg, g3), images.scene_key(self.cfg, self.g3()))
        # a new picture under a new file name is a new scene
        g5 = dict(g3, id="g5", file="%s/g5-hill.png" % IMG, ref="/blog-images/%s/g5-hill.png" % SLUG, seed=7,
                  prompt="A green hillside with a few pine trees under a pale sky")
        self.manifest([self.g1(place=key(COUNTER)), g5])
        self.body3(g3=self.snip(g5, label=LABEL))
        self.assertEqual(self.plan()["errors"], [])

    def test_b1_a_scene_moved_to_a_stand_in_line_is_a_new_picture(self):
        self.manifest([self.g1(place=key(COUNTER))])
        self.body3(g3="")
        self.assertEqual(self.plan()["errors"], [])
        self.assertEqual(self.gen()["state"], "done")
        images.review(self.root, self.cfg, TID, "g1", ok=True, note="fine")
        moved = self.g1(place=key(TEMPLE), stand_in={"subject": "place", "names": ["清水寺"], "why": "no-candidates"})
        g2 = self.g2(place=key(COUNTER))
        self.manifest([g2, moved])
        self.body3(g1=self.snip(g2), g3=self.snip(moved))
        self.assertEqual(self.plan()["errors"], [])
        st = self.state()
        self.assertEqual(st["images"]["items"]["g1"]["status"], "pending")  # a new key: no picture, no review
        self.assertNotIn("reviewed", st["images"]["items"]["g1"])

    def test_m1_a_wrong_extension_is_no_evidence(self):
        e = self.e1(place=key(LOBBY), file="%s/e1-lobby.png" % IMG, ref="/blog-images/%s/e1-lobby.png" % SLUG)
        self.manifest([self.g1(place=key(COUNTER)), e])
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                g3="![The office lobby](%s)" % e["ref"], dec=""))
        self.plan()
        self.route(SRC, jpeg_route())
        self.assertEqual(self.fetch()["failed"][0]["code"], "ext-mismatch")
        self.assertEqual(self.state().get("fetch_failures") or [], [])
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual(out["why"], "not-yet")
        # an earlier failure does not outlive a successful fetch of the same URL
        self.push_state(fetch_failures=[{"id": "e1", "place": key(LOBBY), "source_url": SRC, "code": "http-404"}])
        e = self.e1(place=key(LOBBY))
        self.manifest([self.g1(place=key(COUNTER)), e])
        self.write("src/content/blog/%s.md" % SLUG, BODY.format(g1=self.snip(self.g1(place=key(COUNTER))),
                                                                g3="![The office lobby](%s)" % e["ref"], dec=""))
        self.assertEqual(self.fetch()["failed"], [])
        out, _ = self.hrd("image", "stand-in", "--topic", TID, "--place", key(LOBBY))
        self.assertEqual(out["why"], "not-yet")

    def test_m2_a_borrowed_refusal_holds_everywhere(self):
        self.assertEqual(self.plan()["errors"], [])
        images.review(self.root, self.cfg, TID, "g3", subject_ok=True, note="ok")
        self.assertEqual(self.gen()["state"], "done")
        with self.assertRaises(HeraldError):  # the blocked place must be another place of the brief (m7)
            images.review(self.root, self.cfg, TID, "g1", problem="subject", note="x", place="nope")
        images.review(self.root, self.cfg, TID, "g1", problem="subject", note="redraws", place=key(LOBBY))
        out = self.gen()
        self.assertEqual(out["state"], "blocked")
        self.assertIn({"id": "g1", "why": "refused"}, out["blocked"])
        self.assertIn("g1: this stand-in may not go on (refused)",
                      " ".join(images.draft_problems(self.root, self.cfg, TID, self.state())))
        self.assertEqual(images._head_block(self.root, TID, self.state(), self.g1(place=key(COUNTER))), "refused")
        self.assertIn(images.scene_key(self.cfg, self.g1(place=key(COUNTER))),
                      images.rejected_scene_keys(self.state(), "g1"))  # the same picture never comes back

    def test_m3_rerun_in_a_research_fix_is_refused_unattended_or_shipping(self):
        self.assertEqual(self.plan()["errors"], [])
        st = self.state()
        st["research_fixes"] = [{"status": "open", "claims": ["C1"], "ids_before": ["C1"], "research_before": "x"}]
        st["stage"] = "research"
        store.save_state(self.root, TID, st)
        self.write(W + "/research.md", research(lobby="- none: nothing — searched: https://commons.wikimedia.org/x")
                   .replace("3,000", "3,500"))
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "research", "--rerun", check=False,
                        env={"HRD_UNATTENDED": "1"})
        self.assertIn("unattended", p.stderr)
        ship_lock(self.root)
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "research", "--rerun", check=False)
        self.assertIn("--ship", p.stderr)
        lock.force_unlock(self.root)
        _, p = self.hrd("stage", "pass", "--topic", TID, "--stage", "research", "--rerun", check=False)
        self.assertIn("image candidates are fixed", p.stderr)  # a fix is no re-pass: the flag lifts nothing

    def test_m4_research_after_a_brief_rerun(self):
        self.assertEqual(self.plan()["errors"], [])
        nb = BRIEF.replace(LOBBY, "- the station lobby — kind: external (place) — the lobby paragraph — First")
        self.write(W + "/brief.md", nb)
        self.hrd("stage", "pass", "--topic", TID, "--stage", "brief", "--rerun")
        k = next(x["place"] for x in stand_in.parse_brief(nb) if "station" in x["line"])
        self.write(W + "/research.md", research().replace(key(LOBBY), k))
        out, _ = self.hrd("stage", "pass", "--topic", TID, "--stage", "research")
        self.assertEqual(out["stage"], "draft")
        h = self.state()["candidates_hash"]
        self.assertEqual(h, stand_in.candidates_hash(research().replace(key(LOBBY), k)))

    def test_m2_m3_hidden_labels(self):
        for t, hidden in (('<figure style="overflow:hidden"><img src="{ref}" alt="{alt}"><i aria-hidden="true">*</i>'
                           '<figcaption>{label}</figcaption></figure>', False),
                          ('<img src="{ref}" alt="{alt}" class="hidden-xs"><p>{label}</p>', False),
                          ('<img src="{ref}" alt="{alt}"><p class="caption sr-only">{label}</p>', True),
                          ('<img src="{ref}" alt="{alt}"><p hidden>{label}</p>', True),
                          ('<img src="{ref}" alt="{alt}"><span aria-hidden="true">{label}</span>', True),
                          ("<img src='{ref}' alt='{alt}'><span aria-hidden='true'>{label}</span>", True),
                          ('<img src="{ref}" alt="{alt}"><div style="visibility: hidden"><b>{label}</b></div>', True),
                          ('<img src="{ref}" alt="{alt} {label}">', True),
                          ('![{alt}]({ref})\n<!-- {label} -->', True),
                          ('<p class="hidden">x</p><img src="{ref}" alt="{alt}"><p>{label}</p>', False),
                          ('<img src="{ref}" alt="{alt}"><img src="/i.svg" aria-hidden="true"><p>{label}</p>', False),
                          ('<img src="{ref}" alt="{alt}"><br hidden>{label}', False)):
            self.assertEqual(stand_in.hidden_label(t), hidden, t)

    def test_m6_only_the_images_section(self):
        text = "# Brief\n\n## Notes\n%s\n\n## Images\n%s\n\n## Other\n%s\n" % (TEMPLE, LOBBY, COUNTER)
        self.assertEqual([p["line"] for p in stand_in.parse_brief(text)], [LOBBY])

    def test_m9_no_notice_where_stand_ins_cannot_run(self):
        self.config(lambda c: c["images"].update(external=False))
        self.assertIsNone(stand_in.first_notice(self.root, self.cfg))
        self.config(lambda c: c["images"].update(external=True))
        self.assertIn("stand-ins on", stand_in.first_notice(self.root, self.cfg))
        self.assertIsNone(stand_in.first_notice(self.root, self.cfg))  # once

    def test_m4_records_edited_or_switched_back(self):
        self.push_state(image_rejects=[{"id": "e1", "place": key(LOBBY), "drop": True}], stand_in_orphaned=True)
        self.commit("work")
        self.push_state(image_rejects=[{"id": "e1", "place": key(LOBBY), "drop": False},
                                       {"id": "e2", "place": key(LOBBY), "drop": True}])
        edited = self.commit("edit a record and add one")
        self.assertIn(edited, stand_in.records_shrank(self.root, self.cfg, TID, "HEAD"))
        self.push_state(stand_in_orphaned=False)
        off = self.commit("switch back")
        self.assertIn(off, stand_in.records_shrank(self.root, self.cfg, TID, "HEAD"))

    def test_m8_a_swap_with_a_usable_photo_is_recorded(self):
        e = self.e1(place=key(LOBBY))
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), e])
        self.write("src/content/blog/%s.md" % SLUG, BODY.replace("That is all.", "{e1}\n\nThat is all.").format(
            g1=self.snip(self.g1(place=key(COUNTER))), g3=self.snip(self.g3()), dec="",
            e1="![The office lobby](%s)" % e["ref"]))
        self.assertEqual(self.plan()["errors"], [])
        self.hrd("loopback", "--topic", TID, "--human")
        lobby = self.g3(id="g5", file="%s/g5-lobby.png" % IMG, ref="/blog-images/%s/g5-lobby.png" % SLUG,
                        place=key(LOBBY), alt="An office lobby", prompt="A bright office lobby with a reception desk",
                        stand_in={"subject": "place", "names": ["Marunouchi Building"], "why": "used-up"})
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), lobby])
        self.body3(dec=self.snip(lobby) + "\n\nMore.\n\n")
        self.plan()  # its own check refuses the swap (a usable photo) — the record is made anyway
        rj = [r for r in self.state()["image_rejects"] if r.get("via") == "human-loopback"]
        self.assertEqual([r["place"] for r in rj], [key(LOBBY)])

    def test_m8_fetch_failure_row_translations_and_a_later_setting(self):
        self.push_state(fetch_failures=[{"id": "e9", "place": key(LOBBY), "source_url": SRC, "code": "http-404"}])
        self.assertIn("e9: fetch failed (http-404)", "\n".join(images.status(self.root, self.cfg, TID)["pr_rows"]))
        self.push_state(fetch_failures=[])
        # a stand-in confirmed before the setting turned off is no unvouched file in its PR
        self.confirmed()
        self.commit("pictures")
        self.config(lambda c: c["images"]["scenes"].update(stand_in=False))
        self.assertEqual(images.unvouched(self.root, self.cfg, TID, "HEAD", SLUG), [])
        self.assertIn("stand-ins are now off", " ".join(images.status(self.root, self.cfg, TID)["warnings"]))
        # a translation repo: no stand-in, no decorative picture
        self.config(lambda c: c["images"]["scenes"].update(stand_in=True, decorative=2) or c.update(
            roles={"conditional": ["illustrator", "translator"]}, translations={
                "source": "en", "targets": [{"lang": "ko", "body_pattern": "{content}/ko/{slug}.md",
                                             "url_pattern": "/ko/{slug}/"}]}))
        k = images.kinds(self.root, self.cfg, TID)
        self.assertEqual((k["scene"]["stand_in"]["ok"], k["scene"]["decorative"]["max"], k["external"]["decorative"]),
                         (False, 0, False))


class ReviewRoundTwoTests(StandInCase):
    """r2-M1: a picture turned down in one role never comes back in another (REVIEW-26 round 2)."""

    def setUp(self):
        super().setUp()
        self.config(lambda c: c["images"]["scenes"].update(decorative=1))

    def test_e8_a_decorative_redo_does_not_return_as_a_plain_scene(self):
        hill_line = "- a hillside view — kind: scene — the temple paragraph — Second"
        brief = BRIEF.replace("## Images\n", "## Images\n" + hill_line + "\n")
        self.inputs(brief, None)
        hill = next(p["place"] for p in stand_in.parse_brief(brief) if p["line"] == hill_line)
        dec = self.dec()
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), dec])
        self.body3(dec=self.snip(dec) + "\n\n")
        self.assertEqual(self.plan()["errors"], [])
        images.review(self.root, self.cfg, TID, "g3", subject_ok=True, note="ok")
        self.assertEqual(self.gen()["state"], "done")
        images.review(self.root, self.cfg, TID, "g4", redo=True, note="looks like Kiyomizu's stage")
        g4 = self.dec(place=hill)
        g4.pop("decorative")
        self.manifest([self.g1(place=key(COUNTER)), self.g3(), g4])
        self.body3(dec=self.snip(g4, label=LABEL) + "\n\n")
        self.assertIn("g4: this prompt, seed and size were turned down before", self.errors())

    def test_e8b_a_plain_redo_does_not_return_as_decorative(self):
        self.assertEqual(self.plan()["errors"], [])
        images.review(self.root, self.cfg, TID, "g3", subject_ok=True, note="ok")
        self.assertEqual(self.gen()["state"], "done")
        images.review(self.root, self.cfg, TID, "g1", redo=True, note="a landmark")
        g4 = self.g1(id="g4", place=key(STREET), decorative=True, file="%s/g4-counter.png" % IMG,
                     ref="/blog-images/%s/g4-counter.png" % SLUG)
        g1 = self.g1(place=key(COUNTER), seed=77)
        self.manifest([g1, self.g3(), g4])
        self.body3(g1=self.snip(g1), dec=self.snip(g4) + "\n\n")
        self.assertIn("g4: this prompt, seed and size were turned down before", self.errors())

    def test_a_stand_in_redo_does_not_return_as_another_subject(self):
        thing_line = "- a boxed lunch — kind: external (thing) — the lunch paragraph — Second"
        brief = BRIEF.replace("## Images\n", "## Images\n" + thing_line + "\n")
        thing = next(p["place"] for p in stand_in.parse_brief(brief) if p["line"] == thing_line)
        res = research().replace("\n\n## Other", "\n\n### IC3 — a boxed lunch — place: %s\n- none: none — searched: "
                                                  "%s\n\n## Other" % (thing, SEARCHED))
        self.inputs(brief, res)
        self.assertEqual(self.plan()["errors"], [])
        images.review(self.root, self.cfg, TID, "g3", subject_ok=True, note="ok")
        self.assertEqual(self.gen()["state"], "done")
        images.review(self.root, self.cfg, TID, "g3", redo=True, note="the real stage")
        g3 = self.g3(place=thing, stand_in={"subject": "thing", "names": ["Ekiben"], "why": "no-candidates"})
        self.manifest([self.g1(place=key(COUNTER)), g3])
        self.body3(g3=self.snip(g3, label="AI-generated image (not the actual object)"))
        self.assertIn("turned down before", self.errors())
