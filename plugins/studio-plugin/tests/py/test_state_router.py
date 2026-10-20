"""M0b-1 router tests (m0b1-plan §7.1, §7.2): 00-plan §3.2's M0 tests, rules (a)/(b), the table.
Expected stages are literals; tuples come from state_fixtures.literal_tuple, not stdo/state/tuples.py."""

import unittest

import state_fixtures as F
from stdo.state.router import decide


def redo(d):
    r = d.redo
    return None if r is None else (r["stage"], r.get("output") or r.get("platform"), r.get("mode"))


class PlanTests(unittest.TestCase):
    def test_t1_cast_after_gate1_does_not_go_back_to_1(self):
        s, c = F.state(), F.current()
        F.approve(s, "1", c, excerpts=[])
        c2 = F.changed(c, voice="v2")
        d = decide(s, "ko", c2)
        self.assertEqual(redo(d), ("cast", None, None))  # ② not approved yet: rule (b)
        self.assertEqual(decide(s, "ko", c2, enter="tts").enter, "refused")  # cast not done yet
        F.done(s, "cast", c2)
        self.assertEqual(decide(s, "ko", c2, enter="tts").enter, "allowed")

    def test_t2_excluding_an_output_keeps_the_other_outputs_approvals(self):
        s, c = F.state(outputs=("youtube", "shorts"), platforms={"youtube": ["youtube"]}), \
            F.current(outputs=("youtube", "shorts"))
        F.approve_all(s, c, upto="4a")
        s["langs"]["ko"]["excluded"]["outputs"].append("shorts")
        self.assertEqual(redo(decide(s, "ko", c)), ("copy", "youtube", None))

    def test_t3_after_the_source_diff_is_approved_next_returns_to_the_stage(self):
        # router half (M0b-2 completes it with a real approve)
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="2")
        c2 = F.changed(c, source_hash="src2", source_live_hash="src2",
                       source_text="The cat sat on the mat.\nIt was cold.")
        s["source"]["frozen_hash"] = "src2"
        d = decide(s, "ko", c2)
        self.assertEqual(d.held, {"state": "source-diff"})
        s["langs"]["ko"]["approved"]["1"]["tuple"]["source_hash"] = "src2"  # what M0b-2 rewrites
        self.assertEqual(redo(decide(s, "ko", c2)), ("board", "youtube", None))

    def test_t4_rejected_source_diff_goes_to_verify_then_past_2_without_looping(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="2")
        c2 = F.changed(c, source_hash="src2", source_live_hash="src2")
        s["source"]["frozen_hash"] = "src2"
        s["langs"]["ko"]["approved"]["source-diff"] = {"tuple": {"source_hash": "src2"}, "rejected": True}
        self.assertEqual(redo(decide(s, "ko", c2)), ("verify", None, None))
        F.approve(s, "1", c2, excerpts=["The cat sat on the mat."])  # ① again, same content
        d = decide(s, "ko", c2)
        self.assertIsNone(d.held)
        self.assertEqual(redo(d), ("board", "youtube", None))  # ② still holds

    def test_t5_4b_then_rejected_source_diff_copy_then_4b_no_loop(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        c2 = F.changed(c, source_hash="src2", source_live_hash="src2")
        s["source"]["frozen_hash"] = "src2"
        s["langs"]["ko"]["approved"]["source-diff"] = {"tuple": {"source_hash": "src2"}, "rejected": True}
        seen = [redo(decide(s, "ko", c2))]
        F.approve(s, "1", c2, excerpts=["The cat sat on the mat."])
        seen.append(redo(decide(s, "ko", c2)))
        F.approve(s, "4b", c2, p="youtube")
        seen.append(redo(decide(s, "ko", c2)))
        self.assertEqual(seen, [("verify", None, None), ("copy", "youtube", None), None])

    def test_t6_platform_losing_one_of_its_outputs_goes_to_copy(self):
        s = F.state(outputs=("youtube", "shorts"), platforms={"youtube": ["youtube", "shorts"]})
        c = F.current(outputs=("youtube", "shorts"))
        F.approve_all(s, c)
        s["langs"]["ko"]["excluded"]["outputs"].append("shorts")
        self.assertEqual(redo(decide(s, "ko", c)), ("copy", "youtube", None))

    def test_t7_old_video_cannot_commit_after_2_is_redone(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        c2 = F.changed(c, voice="v2", audio="a2")
        F.approve(s, "2", c2)
        d = decide(s, "ko", c2, enter="commit")
        self.assertEqual(d.enter, "refused")
        # ③'s upstream field (voice) changed, ② already redone: board's exit condition (decision 6)
        self.assertEqual(redo(d), ("board", "youtube", "exit-condition"))

    def test_t8_s2v_version_stops_before_hash_version(self):
        # router half: the migration itself is M0b-2's re-pin
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="2")
        c2 = F.changed(c, s2v_version="0.13.0+def", hash_version=2)
        self.assertEqual(decide(s, "ko", c2).stop["stop"], "s2v-version")
        s["s2v"]["id"] = "0.13.0+def"  # re-pinned (M0b-2)
        self.assertEqual(decide(s, "ko", c2).stop, {"stop": "hash-version", "from": 1, "to": 2})


class RulesAB(unittest.TestCase):
    def test_n1_unapproved_gates_before_the_stage(self):
        s, c = F.state(), F.current()
        F.approve(s, "1", c, excerpts=[])
        d = decide(s, "ko", c, enter="render", output="youtube")
        self.assertEqual((d.enter, redo(d)), ("refused", ("cast", None, None)))
        F.approve(s, "2", c)
        d = decide(s, "ko", c, enter="render", output="youtube")
        self.assertEqual((d.enter, redo(d)), ("refused", ("board", "youtube", None)))

    def test_n2_added_output_goes_to_board_alone(self):
        s, c = F.state(outputs=("youtube",)), F.current(outputs=("youtube", "shorts"))
        F.approve_all(s, c)
        s["brief"]["outputs"].append("shorts")
        d = decide(s, "ko", c)
        self.assertEqual(redo(d), ("board", "shorts", None))
        self.assertEqual(decide(s, "ko", c, enter="4a", output="youtube").enter, "allowed")

    def test_n3_platform_stage_needs_every_outputs_4a(self):
        s = F.state(outputs=("youtube", "shorts"), platforms={"youtube": ["youtube"]})
        c = F.current(outputs=("youtube", "shorts"))
        F.approve_all(s, c, upto="2")
        for o in ("youtube", "shorts"):
            F.approve(s, "3", c, o=o)
        F.approve(s, "4a", c, o="youtube")
        d = decide(s, "ko", c, enter="copy", platform="youtube")
        self.assertEqual((d.enter, redo(d)), ("refused", ("render", "shorts", None)))

    def test_n4_commit_needs_every_platform(self):
        s = F.state(platforms={"youtube": ["youtube"], "internal": ["youtube"]})
        c = F.current(platforms=("youtube", "internal"))
        F.approve_all(s, c, upto="4a")
        F.approve(s, "4b", c, p="youtube")
        d = decide(s, "ko", c, enter="commit")
        self.assertEqual((d.enter, redo(d)), ("refused", ("copy", "internal", None)))
        F.approve(s, "4b", c, p="internal")
        self.assertEqual(decide(s, "ko", c, enter="commit").enter, "allowed")

    def test_r1_the_table(self):
        rows = [({"brief_core": "b2"}, ("script", None, None)),
                ({"content": "c2"}, ("verify", None, None)),
                ({"voice": "v2"}, ("tts", None, None)),
                ({"engine_tts": "x"}, ("tts", None, None)),
                ({"engine_templates": "x"}, ("tts", None, None)),
                ({"audio": "a2"}, ("2", None, None)),
                ({"presentation": {"youtube": "p2"}}, ("board", "youtube", "exit-condition")),
                ({"engine_composer": "x"}, ("visual-check", "youtube", None)),
                ({"engine_renderer": "x"}, ("visual-check", "youtube", None)),
                ({"engine_defaults_presentation": "x"}, ("visual-check", "youtube", None)),
                ({"engine_ffmpeg": "x"}, ("visual-check", "youtube", None)),
                ({"render": {"youtube": "r2"}}, ("4a", "youtube", None)),
                ({"copy": {"youtube": "cp2"}}, ("4b", "youtube", None)),
                ({"engine_defaults_voice": "x"}, None)]
        for over, want in rows:
            s, c = F.state(), F.current()
            F.approve_all(s, c)
            self.assertEqual(redo(decide(s, "ko", F.changed(c, **over))), want, over)

    def test_r2_many_changes_earliest_wins(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        d = decide(s, "ko", F.changed(c, audio="a2", content="c2", copy={"youtube": "x"}))
        self.assertEqual(redo(d), ("verify", None, None))

    def test_r3_one_outputs_presentation(self):
        s = F.state(outputs=("youtube", "shorts"), platforms={"youtube": ["youtube"], "sns": ["shorts"]})
        c = F.current(outputs=("youtube", "shorts"), platforms=("youtube", "sns"))
        F.approve_all(s, c)
        d = decide(s, "ko", F.changed(c, presentation={"youtube": "p-youtube", "shorts": "p2"}))
        self.assertEqual(redo(d), ("board", "shorts", "exit-condition"))
        # a platform stage looks at every output's ③ and ④a (plan review 2, MINOR 1)
        self.assertEqual(decide(s, "ko", F.changed(c, presentation={"youtube": "p-youtube", "shorts": "p2"}),
                                enter="4b", platform="youtube").enter, "refused")
        self.assertEqual(decide(s, "ko", F.changed(c, presentation={"youtube": "p-youtube", "shorts": "p2"}),
                                enter="4a", output="youtube").enter, "allowed")

    def test_r4_ffmpeg_message(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        d = decide(s, "ko", F.changed(c, engine_ffmpeg="x"))
        self.assertIn("ffmpeg", d.redo["why"][0])

    def test_r5_null_hash_entry(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="1")
        c2 = F.changed(c, voice=None, reasons={"voice": ["persona wav missing"]})
        F.done(s, "cast", c2)
        d = decide(s, "ko", c2, enter="tts")
        self.assertEqual(d.enter, "null-hash")
        self.assertEqual(d.null_reasons[0]["reasons"], ["persona wav missing"])
        self.assertEqual(decide(s, "ko", c2, enter="cast").enter, "allowed")

    def test_r6_d29(self):
        s, c = F.state(), F.current()
        d = decide(s, "ko", F.changed(c, s2v_version="0.12.2+x"))
        self.assertEqual((d.stop["stop"], d.stop["exact_revert_possible"]), ("s2v-version", True))
        s["s2v"]["commit"] = None
        self.assertFalse(decide(s, "ko", F.changed(c, s2v_version="0.12.2+x")).stop["exact_revert_possible"])
        self.assertEqual(decide(s, "ko", F.changed(c, stale_build=True)).stop["stop"], "s2v-version")

    def test_r7_source_diff_branches_and_normalization(self):
        def at(frozen, text, rejected=False, content="c1"):
            s, c = F.state(), F.current()
            F.approve_all(s, c, upto="2")
            s["source"]["frozen_hash"] = frozen
            if rejected:
                s["langs"]["ko"]["approved"]["source-diff"] = {"tuple": {"source_hash": "src2"}, "rejected": True}
            d = decide(s, "ko", F.changed(c, source_hash="src2", source_live_hash="src2", source_text=text,
                                          content=content))
            return "held" if d.held else redo(d)[0]

        self.assertEqual(at("src1", "x"), "source")
        self.assertEqual(at("src2", "x", rejected=True), "verify")
        self.assertEqual(at("src2", "The  cat sat\r\non the mat.  More."), "held")
        self.assertEqual(at("src2", "The cat́ sat"), "script")  # not NFC-equal to the excerpt
        self.assertEqual(at("src2", "A dog."), "script")

    def test_r10_done_and_other_languages(self):
        s, c = F.state(langs=("ko", "en")), F.current()
        s["langs"]["ko"]["status"] = "done"
        self.assertTrue(decide(s, "ko", c).done)
        self.assertEqual(redo(decide(s, "en", c)), ("script", None, None))

    def test_r11_held_actor_states_wait(self):
        for h in ("actor", "actor-building", "render", "lock", "stagnation"):
            s, c = F.state(), F.current()
            s["langs"]["ko"]["held"] = {"state": h}
            self.assertEqual(decide(s, "ko", c).held["state"], h)


class Review1(unittest.TestCase):
    """Implementation review 1 of M0b-1 (MAJOR-1, MINOR 9–10, NITs)."""

    def test_major1_entered_stages_own_gate_is_compared(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        cp = F.changed(c, presentation={"youtube": "p2"})
        for stage in ("visual-check", "3"):
            d = decide(s, "ko", cp, enter=stage, output="youtube")
            self.assertEqual((d.enter, redo(d)), ("refused", ("board", "youtube", "exit-condition")), stage)
        self.assertEqual(decide(s, "ko", cp, enter="board", output="youtube").enter, "allowed")
        cv = F.changed(c, voice="v2")
        for stage in ("audition", "2"):
            d = decide(s, "ko", cv, enter=stage)
            self.assertEqual((d.enter, redo(d)), ("refused", ("tts", None, None)), stage)
        self.assertEqual(decide(s, "ko", cv, enter="tts").enter, "allowed")

    def test_source_diff_held_loses_to_a_brief_change(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="2")
        s["source"]["frozen_hash"] = "src2"
        d = decide(s, "ko", F.changed(c, source_hash="src2", source_live_hash="src2", brief_core="b2"))
        self.assertIsNone(d.held)
        self.assertEqual(redo(d), ("script", None, None))

    def test_null_audio_and_presentation_entry(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="2")
        d = decide(s, "ko", F.changed(c, audio=None, reasons={"audio": ["not synthesized"]}), enter="audition")
        self.assertEqual((d.enter, d.null_reasons[0]["hash"]), ("null-hash", "audio"))
        c3 = F.changed(c, presentation={"youtube": None},
                       reasons={"presentation.youtube": ["missing file(s): a.png"]})
        F.done(s, "board", c3, o="youtube")
        d = decide(s, "ko", c3, enter="visual-check", output="youtube")
        self.assertEqual((d.enter, d.null_reasons[0]["hash"]), ("null-hash", "presentation.youtube"))

    def test_nfd_source_nfc_excerpt_is_held(self):
        s, c = F.state(), F.current()
        F.approve(s, "1", c, excerpts=["caf\u00e9 opens"])
        s["source"]["frozen_hash"] = "src2"
        d = decide(s, "ko", F.changed(c, source_hash="src2", source_live_hash="src2",
                                      source_text="The cafe\u0301 opens at nine."))
        self.assertEqual(d.held, {"state": "source-diff"})

    def test_rejection_only_for_the_current_hash(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="2")
        s["source"]["frozen_hash"] = "src3"
        s["langs"]["ko"]["approved"]["source-diff"] = {"tuple": {"source_hash": "src2"}, "rejected": True}
        d = decide(s, "ko", F.changed(c, source_hash="src3", source_live_hash="src3"))
        self.assertEqual(d.held, {"state": "source-diff"})

    def test_content_change_with_source_change_is_not_held(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c, upto="2")
        s["source"]["frozen_hash"] = "src2"
        d = decide(s, "ko", F.changed(c, source_hash="src2", source_live_hash="src2", content="c2"))
        self.assertIsNone(d.held)
        self.assertEqual(redo(d), ("script", None, None))

    def test_aborted_language(self):
        s, c = F.state(), F.current()
        s["langs"]["ko"]["status"] = "aborted"
        self.assertTrue(decide(s, "ko", c).done)

    def test_minor10_brief_and_source_before_script(self):
        s, c = F.state(), F.current()
        s["brief"]["core"] = None
        d = decide(s, "ko", c, enter="script")
        self.assertEqual((d.enter, redo(d)), ("refused", ("brief", None, None)))
        s["source"]["frozen_hash"] = None
        self.assertEqual(redo(decide(s, "ko", F.changed(c, source_text=None))), ("source", None, None))

    def test_missing_hash_version_is_stale(self):
        s, c = F.state(), F.current()
        F.approve(s, "1", c, excerpts=[])
        del s["langs"]["ko"]["approved"]["1"]["hash_version"]
        self.assertEqual(decide(s, "ko", c).stop["stop"], "hash-version")

    def test_tuple_for_matches_the_literal_table(self):
        from stdo.state.tuples import tuple_for
        c = F.current(outputs=("youtube",), platforms=("youtube",))
        self.assertEqual(tuple_for("1", c), {"brief_core": "brief1", "content": "c1", "source_hash": "src1"})
        two = {"brief_core": "brief1", "content": "c1", "voice": "v1", "audio": "a1", "engine.tts": "e-tts",
               "engine.templates": "e-tpl", "engine.defaults_voice": "e-dv"}
        self.assertEqual(tuple_for("2", c), two)
        three = dict(two, **{"presentation": "p-youtube", "engine.composer": "e-comp", "engine.renderer": "e-rend",
                             "engine.ffmpeg": "e-ff", "engine.defaults_presentation": "e-dp"})
        self.assertEqual(tuple_for("3", c, output="youtube"), three)
        self.assertEqual(tuple_for("4a", c, output="youtube"), dict(three, render="r-youtube"))
        self.assertEqual(tuple_for("4b", c, platform="youtube", platform_outputs=["youtube"]),
                         {"content": "c1", "source_hash": "src1", "renders": {"youtube": "r-youtube"},
                          "copy": "cp-youtube"})


class StageDone(unittest.TestCase):
    """Implementation review 2 (B-1): completion records let a section be redone up to its gate."""

    def test_voice_tts_audition_2(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        c2 = F.changed(c, voice="v2")
        self.assertEqual(redo(decide(s, "ko", c2, enter="audition")), ("tts", None, None))
        F.done(s, "tts", c2)
        self.assertEqual(decide(s, "ko", c2, enter="audition").enter, "allowed")
        d = decide(s, "ko", c2, enter="2")
        self.assertEqual((d.enter, redo(d)), ("refused", ("audition", None, None)))
        F.done(s, "audition", c2)
        self.assertEqual(decide(s, "ko", c2, enter="2").enter, "allowed")
        self.assertEqual(redo(decide(s, "ko", c2)), ("2", None, None))
        self.assertEqual(decide(s, "ko", c2, enter="board", output="youtube").enter, "refused")

    def test_presentation_board_visual_check_3(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        c2 = F.changed(c, presentation={"youtube": "p2"})
        F.done(s, "board", c2, o="youtube")
        self.assertEqual(decide(s, "ko", c2, enter="visual-check", output="youtube").enter, "allowed")
        self.assertEqual(decide(s, "ko", c2, enter="3", output="youtube").enter, "refused")
        F.done(s, "visual-check", c2, o="youtube")
        self.assertEqual(decide(s, "ko", c2, enter="3", output="youtube").enter, "allowed")

    def test_content_verify_1(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        c2 = F.changed(c, content="c2")
        self.assertEqual(decide(s, "ko", c2, enter="1").enter, "refused")
        F.done(s, "verify", c2)
        self.assertEqual(decide(s, "ko", c2, enter="1").enter, "allowed")

    def test_an_older_tuple_does_not_unlock(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        F.done(s, "tts", F.changed(c, voice="v2"))
        d = decide(s, "ko", F.changed(c, voice="v3"), enter="audition")
        self.assertEqual((d.enter, redo(d)), ("refused", ("tts", None, None)))

    def test_records_of_another_scope_do_not_count(self):
        s = F.state(outputs=("youtube", "shorts"), platforms={"youtube": ["youtube"]})
        c = F.current(outputs=("youtube", "shorts"))
        F.approve_all(s, c)
        c2 = F.changed(c, presentation={"youtube": "p2", "shorts": "p2"})  # same tuple, other scope
        F.done(s, "board", c2, o="shorts")
        self.assertEqual(decide(s, "ko", c2, enter="visual-check", output="youtube").enter, "refused")

    def test_n10_4b_section_entry(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        c2 = F.changed(c, copy={"youtube": "cp2"})
        self.assertEqual(decide(s, "ko", c2, enter="4b", platform="youtube").enter, "allowed")
        c3 = F.changed(c, render={"youtube": "r2"})
        F.approve(s, "4a", c3, o="youtube")  # the new render approved
        d = decide(s, "ko", c3, enter="4b", platform="youtube")
        self.assertEqual((d.enter, redo(d)), ("refused", ("copy", "youtube", None)))
        F.done(s, "copy", c3, p="youtube")
        self.assertEqual(decide(s, "ko", c3, enter="4b", platform="youtube").enter, "allowed")

    def test_first_time_flow_through_a_section(self):
        s, c = F.state(), F.current()
        F.approve(s, "1", c, excerpts=[])
        for st in ("cast", "tts", "audition"):
            self.assertEqual(redo(decide(s, "ko", c)), (st, None, None))
            F.done(s, st, c)
        self.assertEqual(redo(decide(s, "ko", c)), ("2", None, None))

    def test_first_pass_in_production_order(self):
        """Each stage changes the hashes it produces (B-1'): cast→voice, tts→audio, board→presentation,
        render→render sha, copy→copy sha. Nothing bounces back to an earlier stage."""
        s = F.state()
        c = F.current(voice="v0", audio=None, presentation={"youtube": None}, render={"youtube": None},
                      copy={"youtube": None})
        F.approve(s, "1", c, excerpts=[])
        steps = [("cast", {"voice": "v1"}, None), ("tts", {"audio": "a1"}, None), ("audition", {}, None),
                 ("2", {}, None),
                 ("board", {"presentation": {"youtube": "p1"}}, "youtube"), ("visual-check", {}, "youtube"),
                 ("3", {}, "youtube"),
                 ("render", {"render": {"youtube": "r1"}}, "youtube"), ("4a", {}, "youtube"),
                 ("copy", {"copy": {"youtube": "cp1"}}, "youtube"), ("4b", {}, "youtube")]
        for stage, produced, scope in steps:
            self.assertEqual(redo(decide(s, "ko", c))[0], stage)
            c = F.changed(c, **produced)
            if stage in ("2", "3", "4a", "4b"):
                F.approve(s, stage, c, o=scope if stage in ("3", "4a") else None,
                          p=scope if stage == "4b" else None)
            else:
                F.done(s, stage, c, o=scope if stage not in ("copy",) else None,
                       p=scope if stage == "copy" else None)
        self.assertIsNone(decide(s, "ko", c).redo)

    def test_redo_in_production_order(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        c = F.changed(c, voice="v2")  # cast changed the voice
        self.assertEqual(redo(decide(s, "ko", c))[0], "tts")
        c = F.changed(c, audio="a2")  # tts made new audio
        F.done(s, "tts", c)
        self.assertEqual(redo(decide(s, "ko", c))[0], "audition")
        F.done(s, "audition", c)
        self.assertEqual(redo(decide(s, "ko", c))[0], "2")
        F.approve(s, "2", c)
        d = decide(s, "ko", c)
        self.assertEqual(redo(d), ("board", "youtube", "exit-condition"))
        F.done(s, "board", c, o="youtube")
        d = decide(s, "ko", c)
        self.assertEqual(redo(d), ("visual-check", "youtube", None))  # S14: mode cleared
        self.assertNotIn("mode", d.redo)

    def test_missing_output_goes_to_script_despite_records(self):
        s, c = F.state(), F.current()
        F.done(s, "script", c)
        F.done(s, "verify", c)
        self.assertEqual(redo(decide(s, "ko", c)), ("1", None, None))
        c2 = F.changed(c, outputs_missing=["youtube"])
        self.assertEqual(redo(decide(s, "ko", c2)), ("script", "youtube", None))
        self.assertEqual(decide(s, "ko", c2, enter="1").enter, "refused")

    def test_content_change_after_the_script_record_goes_back_to_script(self):
        s, c = F.state(), F.current()
        F.done(s, "script", c)
        self.assertEqual(redo(decide(s, "ko", c)), ("verify", None, None))
        self.assertEqual(redo(decide(s, "ko", F.changed(c, content="c2"))), ("script", None, None))

    def test_output_missing_from_the_script_goes_to_script(self):
        s, c = F.state(), F.current()
        F.approve_all(s, c)
        d = decide(s, "ko", F.changed(c, outputs_missing=["youtube"]))
        self.assertEqual(redo(d), ("script", "youtube", None))


if __name__ == "__main__":
    unittest.main()
