"""M0b-2: tuple rewrites (source diff, re-pin), exclude-output, unlock, backups (m0b2-plan §7.1, §7.4)."""

import copy
import json
import os

from approve_base import ApproveCase
from stdo.state import backup
from stdo.state.hashes import hash_of


def redo(case):
    case.assertEqual(case.cli("next", "v1", "--json"), 0, case.last_err)
    r = json.loads(case.last_out)["redo"]
    return None if r is None else (r["stage"], r.get("output") or r.get("platform"))


class SourceDiff(ApproveCase):
    def change_source(self, new="src2"):
        self.src = new
        st = self.state()
        st["source"]["frozen_hash"] = new  # the source stage refreshed its copy (M1)
        self.write_state(st)

    def test_t3_approved_source_diff_returns_to_the_stage(self):
        self.pass_all(upto="2")
        self.change_source()
        self.assertEqual(self.cli("next", "v1"), 4)
        h = self.show("source-diff")
        self.assertEqual(self.approve("source-diff", h), 0, self.last_err)
        st = self.state()
        self.assertEqual(st["langs"]["ko"]["approved"]["1"]["tuple"]["source_hash"], "src2")
        self.assertEqual(st["source"]["approved_hash"], "src2")
        rw = [e for e in self.events() if e.get("event") == "rewrite"]
        self.assertEqual([(e["gate"], e["old"], e["new"]) for e in rw], [("1", "src1", "src2")])
        self.assertEqual(redo(self), ("board", "youtube"))

    def reject(self):
        h = self.show("source-diff")
        argv = ["reject-source-diff", "v1", "--expect", h]
        self.pend(argv, "거부 %s" % h)
        return self.cli(*argv)

    def test_t4_rejected_then_1_again_keeps_2(self):
        self.pass_all(upto="2")
        self.change_source()
        self.assertEqual(self.reject(), 0, self.last_err)
        self.assertEqual(redo(self), ("verify", None))
        self.cli("stage-done", "v1", "verify")
        h = self.show("1")
        self.assertEqual(self.approve("1", h), 0, self.last_err)
        self.assertEqual(redo(self), ("board", "youtube"))

    def test_t5_from_4b_through_rejection_without_loops(self):
        self.pass_all()
        self.change_source()
        seen = []
        self.assertEqual(self.reject(), 0)
        seen.append(redo(self))
        self.cli("stage-done", "v1", "verify")
        self.approve("1", self.show("1"))
        seen.append(redo(self))
        self.cli("stage-done", "v1", "copy", "--platform", "youtube")
        self.assertEqual(self.approve("4b", self.show("4b", "youtube")), 0, self.last_err)
        seen.append(redo(self))
        self.assertEqual(seen, [("verify", None), ("copy", "youtube"), None])

    def test_x4_reject_needs_evidence(self):
        self.pass_all(upto="1")
        self.change_source()
        h = self.show("source-diff")
        self.assertEqual(self.cli("reject-source-diff", "v1", "--expect", h), 6)
        self.assertEqual(self.approve("source-diff", h, answer="거부 %s" % h), 6)  # not an approval

    def test_x3_baseline_from_the_last_approved_hash(self):
        self.pass_gate("1")
        st = self.state()
        st["source"]["approved_hash"] = "src0"  # ① (src1) is not what was last approved: stale
        self.write_state(st)
        self.change_source()
        self.assertEqual(self.approve("source-diff", self.show("source-diff")), 0, self.last_err)
        self.assertEqual(self.state()["langs"]["ko"]["approved"]["1"]["tuple"]["source_hash"], "src1")

    def test_x3_baseline_derived_from_the_one_language(self):
        self.pass_gate("1")
        st = self.state()
        st["source"]["approved_hash"] = None
        self.write_state(st)
        self.change_source()
        self.assertEqual(self.approve("source-diff", self.show("source-diff")), 0, self.last_err)
        self.assertEqual(self.state()["langs"]["ko"]["approved"]["1"]["tuple"]["source_hash"], "src2")

    def test_minor2_several_languages_need_m3a(self):
        self.pass_gate("1")
        st = self.state()
        st["langs"]["en"] = copy.deepcopy(st["langs"]["ko"])
        self.write_state(st)
        self.change_source()
        h = self.show("source-diff")
        before = self.state()
        self.assertEqual(self.approve("source-diff", h), 4)
        self.assertIn("needs M3a", self.last_err)
        self.assertEqual(self.state()["langs"], before["langs"])

    def test_approve_source_diff_needs_a_waiting_diff(self):
        self.pass_gate("1")
        h = self.show("source-diff")
        self.assertEqual(self.approve("source-diff", h), 3)

    def test_4b_copy_excerpts_decide_whether_4b_moves(self):
        for text, want in (("The cat sat on the mat.\nIt was cold.", ("copy", "youtube")),
                           ("The cat sat on the mat.\nIt was warm. And more.", None)):
            self.setUp()
            self.pass_all()
            self.change_source()
            self.text = text
            self.assertEqual(self.approve("source-diff", self.show("source-diff")), 0, self.last_err)
            self.assertEqual(redo(self), want, text)

class Repin(ApproveCase):
    def repin(self, frm, to, expect=None):
        h = expect or hash_of({"video": "v1", "from_id": frm, "to_id": to})[:12]
        argv = ["repin", "v1", "--expect", h]
        self.pend(argv, "재고정 %s" % h)
        return self.cli(*argv)

    def test_t8_repin_migrates_only_what_was_current(self):
        self.pass_all(upto="3")
        old = copy.deepcopy(self.ins)
        old["hashes"]["presentation_by_output"]["youtube"] = "p-stale"  # ③ already stale before
        self.old_ins[1] = old
        new = copy.deepcopy(self.ins)
        new.update(s2v_version="0.13.0+new", hash_version=2)
        h = new["hashes"]
        h.update(content="c1@2", voice="v1@2", audio="a1@2")
        h["presentation_by_output"] = {"youtube": "p@2"}
        self.ins = new
        self.ver.update(id="0.13.0+new", version="0.13.0")
        self.assertEqual(self.cli("next", "v1", "--json"), 4)
        self.assertEqual(json.loads(self.last_out)["stop"]["stop"], "s2v-version")
        self.assertEqual(self.repin("0.12.1+abc", "0.13.0+new"), 0, self.last_err)
        st = self.state()
        A = st["langs"]["ko"]["approved"]
        self.assertEqual((A["1"]["hash_version"], A["1"]["tuple"]["content"]), (2, "c1@2"))
        self.assertEqual((A["2"]["tuple"]["voice"], A["2"]["tuple"]["audio"]), ("v1@2", "a1@2"))
        self.assertEqual(A["3"]["youtube"]["tuple"]["content"], "c1@2")
        self.assertEqual(A["3"]["youtube"]["tuple"]["presentation"], "p-youtube")  # stale stays stale
        self.assertEqual(st["s2v"]["id"], "0.13.0+new")
        self.assertEqual(redo(self), ("board", "youtube"))

    def test_r1_refusals(self):
        self.pass_gate("1")
        self.assertEqual(self.repin("0.12.1+abc", "0.12.1+abc"), 3)  # nothing changed
        self.ins["s2v_version"] = "0.13.0+new"
        self.ver.update(id="0.13.0+new")
        self.assertEqual(self.repin("0.12.1+abc", "0.13.0+new", expect="000000000000"), 1)
        self.ver["stale_build"] = True
        self.assertEqual(self.repin("0.12.1+abc", "0.13.0+new"), 2)
        self.ver["stale_build"] = False
        self.assertEqual(self.repin("0.12.1+abc", "0.13.0+new"), 0, self.last_err)

    def test_approval_without_hash_version(self):
        self.pass_gate("1")
        st = self.state()
        del st["langs"]["ko"]["approved"]["1"]["hash_version"]
        self.write_state(st)
        self.ins.update(s2v_version="0.13.0+new", hash_version=2)
        self.ver.update(id="0.13.0+new")
        self.assertEqual(self.repin("0.12.1+abc", "0.13.0+new"), 4)
        self.assertIn("no hash_version", self.last_err)

    def test_repin_several_languages_need_m3a(self):
        self.pass_gate("1")
        st = self.state()
        st["langs"]["en"] = copy.deepcopy(st["langs"]["ko"])
        self.write_state(st)
        self.ins.update(s2v_version="0.13.0+new")
        self.ver.update(id="0.13.0+new")
        self.assertEqual(self.repin("0.12.1+abc", "0.13.0+new"), 4)

    def test_old_method_unavailable(self):
        self.pass_gate("1")
        self.ins.update(s2v_version="0.13.0+new", hash_version=2)
        self.ver.update(id="0.13.0+new")
        from stdo.state.collect import CollectError

        def gone(ctx, hv):
            raise CollectError("s2v inspect refused (usage): --hash-version 1: supported: 2")
        self.providers.inspect_at = gone
        before = self.state()
        self.assertEqual(self.repin("0.12.1+abc", "0.13.0+new"), 4)
        self.assertEqual(self.state(), before)


class Exclude(ApproveCase):
    outputs = ("youtube", "shorts")
    platforms = {"youtube": ["youtube"], "sns": ["shorts"]}

    def exclude(self, out, platforms):
        h = hash_of({"video": "v1", "lang": "ko", "output": out, "platforms": platforms})[:12]
        argv = ["exclude-output", "v1", out, "--expect", h]
        self.pend(argv, "제외 %s" % h)
        return self.cli(*argv)

    def test_x1_exclude_and_bring_back(self):
        self.pass_all()
        self.render_files("shorts")
        self.assertEqual(self.cli("stage-done", "v1", "render", "--output", "shorts"), 0, self.last_err)
        self.assertTrue([r for r in self.state()["langs"]["ko"]["done_stages"] if r.get("output") == "shorts"])
        self.assertEqual(self.exclude("shorts", ["sns"]), 0, self.last_err)
        self.assertFalse([r for r in self.state()["langs"]["ko"]["done_stages"] if r.get("output") == "shorts"])
        st = self.state()
        self.assertEqual((st["brief"]["outputs"], list(st["brief"]["platforms"])), (["youtube"], ["youtube"]))
        A = st["langs"]["ko"]["approved"]
        self.assertNotIn("shorts", A["3"])
        self.assertNotIn("sns", A["4b"])
        removed = [e for e in self.events() if e.get("event") == "removed"]
        self.assertTrue(any(e["gate"] == "4a" and e["key"] == "shorts" for e in removed))
        out = os.path.join(self.repo, "studio", "out", "v1", "ko")
        self.assertTrue(os.path.exists(os.path.join(out, "shorts.ko.mp4.EXCLUDED")))
        shown = st["langs"]["ko"]["shown"]
        self.assertNotIn("shorts", shown.get("3", {}))
        self.assertNotIn("sns", shown.get("4b", {}))
        with open(os.path.join(self.vdir, "work", "ko", "shown.json")) as f:
            self.assertNotIn("shorts", json.load(f).get("3", {}))
        self.assertIsNone(redo(self))
        self.assertEqual(self.cli("record-brief", "v1", "--from",
                                  self.brief(self.outputs, dict(self.platforms))), 0, self.last_err)
        self.assertEqual(redo(self), ("board", "shorts"))

    def test_x1_last_output_and_label(self):
        self.pass_all(upto="1")
        self.assertEqual(self.exclude("shorts", []), 1)  # the label names sns: another hash12
        self.assertEqual(self.exclude("shorts", ["sns"]), 0, self.last_err)
        self.assertEqual(self.exclude("youtube", ["youtube"]), 2)


class ExcludeShared(ApproveCase):
    outputs = ("youtube", "shorts")
    platforms = {"youtube": ["youtube", "shorts"]}

    def test_a_platform_using_several_outputs_survives(self):
        self.pass_all(upto="1")
        h = hash_of({"video": "v1", "lang": "ko", "output": "shorts", "platforms": []})[:12]
        argv = ["exclude-output", "v1", "shorts", "--expect", h]
        self.pend(argv, "제외 %s" % h)
        self.assertEqual(self.cli(*argv), 0, self.last_err)
        self.assertEqual(self.state()["brief"]["platforms"], {"youtube": ["youtube"]})


class Unlock(ApproveCase):
    def test_unlock_label_is_the_actual_held(self):
        for _ in range(3):
            self.cli("loop", "v1", "verify")
        argv = ["unlock", "v1", "--expect", "lock"]
        self.pend(argv, "해제 v1 ko lock")
        self.assertEqual(self.cli(*argv), 1)  # held as stagnation, not lock
        self.assertEqual(self.state()["langs"]["ko"]["held"]["state"], "stagnation")

    def test_x2_unlock_stagnation(self):
        for _ in range(3):
            self.cli("loop", "v1", "verify")
        self.assertEqual(self.state()["langs"]["ko"]["held"]["state"], "stagnation")
        argv = ["unlock", "v1", "--expect", "stagnation"]
        self.pend(argv, "해제 v1 ko lock")
        self.assertEqual(self.cli(*argv), 6)
        self.pend(argv, "해제 v1 ko stagnation", reason="rewrote the claim")
        self.assertEqual(self.cli(*argv), 0, self.last_err)
        L = self.state()["langs"]["ko"]
        self.assertEqual((L["held"], L["loops"]["verify"]), (None, 0))
        ev = [e for e in self.events() if e.get("event") == "unlock"][-1]
        self.assertEqual(ev["answer"]["reason"], "rewrote the claim")


class Backup(ApproveCase):
    location = "local"

    def test_b1_backups(self):
        os.makedirs(os.path.join(self.vdir, "audio", "ko"))
        with open(os.path.join(self.vdir, "audio", "ko", "a.wav"), "wb") as f:
            f.write(b"RIFF")
        self.pass_gate("1")
        base = backup.root(self.repo, "v1")
        self.assertTrue(base.startswith(os.environ["STUDIO_HOME"]))
        with open(os.path.join(base, "copy.1", "manifest.json")) as f:
            m = json.load(f)
        paths = [e["path"] for e in m["files"]]
        self.assertIn("script.ko.md", paths)
        self.assertIn(os.path.join("work", "state.json"), paths)
        self.assertIn(os.path.join("audio", "ko", "a.wav"), [e["path"] for e in m["excluded"]])
        self.assertTrue(os.path.isdir(os.path.join(base, "complete")))
        self.pass_gate("2")
        with open(os.path.join(base, "copy.1", "manifest.json")) as f:
            m2 = json.load(f)
        self.assertTrue(any(e["linked"] for e in m2["files"] if e["path"] == "script.ko.md"))
        self.assertTrue(os.path.isdir(os.path.join(base, "copy.2")))
        st = backup.run(self.repo, self.vdir, "v1", cap=10)
        self.assertIn("exceeded", st["warning"])
        self.assertEqual(self.cli("status"), 0)
        self.assertIn("backup:", self.last_out)
        with open(os.path.join(base, "complete", "manifest.json")) as f:
            complete_before = json.load(f)["at"]
        backup.run(self.repo, self.vdir, "v1", cap=10)  # partial: complete/ stays
        with open(os.path.join(base, "complete", "manifest.json")) as f:
            m = json.load(f)
        self.assertEqual((m["at"], m["complete"]), (complete_before, True))
        for _ in range(5):
            backup.run(self.repo, self.vdir, "v1")
        self.assertEqual(sorted(n for n in os.listdir(base) if n.startswith("copy.")),
                         ["copy.1", "copy.2", "copy.3"])
        self.assertFalse([n for n in os.listdir(base) if n.startswith(".tmp")])
