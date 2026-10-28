"""M1b (m1-plan §4): state.py's flow commands (begin · record-source · hold · release-lock · record-render · done ·
abandon · overlay), the check results stage-done requires (STAGE_CHECKS), the committed-harness check with its
pronounce.json exception (R1 · R7 · S2 · T1 · T3 · T4), run_s2v.py (watermark from the state only, E10b · E10c) and the
guard's side (labels, P-STATE, messages). The fake s2v CLI has its own module (test_fake_s2v.py)."""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import unittest
from unittest import mock

import checkfix
import helpers
import state_fixtures as F
from approve_base import ApproveCase
from helpers import StudioTestCase
from stdo import SCRIPTS_VERSION, machine, paths, s2vrun, sandbox
from stdo.commit import okfile
from stdo.state import cli, commands, flow, harnessgate, labels, schema, stagechecks, store
from stdo.state.hashes import file_sha, hash_of
from test_guard_approve import GuardApproval
from test_guard_judge import JudgeCase

H = "3f2a9c0d1e4b"
FAKE_ROOT = os.path.join(helpers.HERE, "drivers", "fake_s2v_cli")
SCRIPT = """---
title: 공항 단어
lang: ko
cast:
  narrator: { voice: "qwen:Sohee", style: "차분하게" }
outputs:
  youtube: { aspect: "16:9" }
---

# 시작 {#intro}

narrator: 안녕하세요. 오늘은 공항 단어를 배워요.

# 끝 {#end}

narrator: 고마워요!
"""


def need_node():
    if shutil.which("node"):
        return
    if helpers.full_mode():
        raise AssertionError("--full needs node for the fake s2v CLI")
    raise unittest.SkipTest("needs node (the fake s2v CLI)")


# ---------------------------------------------------------------- classification and labels

class Commands(StudioTestCase):
    def test_evidence_classes(self):
        for c in ("begin", "record-source", "hold", "release-lock", "record-render", "done"):
            self.assertFalse(commands.needs_evidence(c), c)
            self.assertIn(c, commands.IMPLEMENTED)
        for c in ("abandon", "overlay"):
            self.assertTrue(commands.needs_evidence(c), c)
            self.assertIn(c, commands.EVIDENCE)
            self.assertIn(c, commands.IMPLEMENTED)
        self.assertTrue(commands.needs_evidence("an-unknown-one"))  # closed side

    def test_labels(self):
        repo = helpers.make_repo(self.tmp)
        d = os.path.join(repo, "studio", "videos", "v1", "work")
        os.makedirs(d)
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump({"video": "v1", "source_lang": "ko"}, f)
        self.assertEqual(labels.expected(["abandon", "v1"], repo, "studio"), ("중단 v1 ko", None, "v1"))
        self.assertEqual(labels.expected(["abandon", "v1", "--lang", "en"], repo, "studio"), ("중단 v1 en", None, "v1"))
        self.assertEqual(labels.expected(["overlay", "--from", "/x/o.json", "--expect", H], repo, "studio"),
                         ("사내설정 %s" % H, H, None))
        for bad in (["overlay", "--from", "/x", "--expect", "XYZ"], ["overlay", "v1", "--expect", H],
                    ["abandon"], ["abandon", "nope"]):
            with self.assertRaises(labels.NoLabel, msg=bad):
                labels.expected(bad, repo, "studio")
        self.assertNotIn("abandon", labels.PLANNED)
        self.assertNotIn("overlay", labels.PLANNED)

    def test_stage_checks_cover_every_stage(self):
        """The table covers every stage recorded with stage-done except visual-check (v5 S4), with the names of §4.1."""
        self.assertEqual(set(schema.STAGE_CHECKS) | set(schema.NO_CHECK_FILE), set(schema.DONE_STAGES))
        self.assertEqual({s: (v["file"], v["scope"]) for s, v in schema.STAGE_CHECKS.items()},
                         {"script": ("script", None), "verify": ("verify-claims", None), "cast": ("cast", None),
                          "tts": ("tts", None), "audition": ("audition", None), "board": ("board", "output"),
                          "render": ("render", "output"), "copy": ("copy", "platform")})
        for s, v in schema.STAGE_CHECKS.items():
            for k in v["inputs"]:
                self.assertIn(k, stagechecks.RESOLVERS, "%s: %s" % (s, k))
        # the stages that run s2v put its id in the input sha
        self.assertEqual({s for s, v in schema.STAGE_CHECKS.items() if v["s2v"]},
                         {"script", "cast", "tts", "board", "render"})
        self.assertEqual(stagechecks.name("board", "youtube"), "board--youtube.json")
        self.assertEqual(stagechecks.name("verify"), "verify-claims.json")


# ---------------------------------------------------------------- a video in a committed harness

class FlowCase(ApproveCase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.repo, "docs"))
        with open(os.path.join(self.repo, "docs", "a.md"), "w") as f:
            f.write(self.text)
        helpers.git(self.repo, "add", "docs/a.md")
        helpers.git(self.repo, "commit", "-q", "-m", "a source")

    def begin(self, vid="v2", *extra, source="docs/a.md"):
        args = ["begin", vid, "--kind", "youtube"] + (["--source", source] if source else []) + list(extra)
        return self.cli(*args)


class Begin(FlowCase):
    def test_begin_creates_the_state(self):
        shutil.rmtree(os.path.join(self.repo, "studio", "voices"))
        self.assertEqual(self.begin(), 0, self.last_err)
        st = store.read_state(os.path.join(self.repo, "studio", "videos", "v2"))
        self.assertEqual((st["video"], st["kind"], st["scope"], st["location"], st["source_lang"]),
                         ("v2", "youtube", "public", "public", "ko"))
        self.assertEqual(st["s2v"], {k: self.ver[k] for k in ("id", "version", "commit", "dirty")})
        self.assertEqual(st["source"]["path"], "docs/a.md")
        self.assertIsNone(st["source"]["frozen_hash"])
        self.assertTrue(os.path.isdir(os.path.join(self.repo, "studio", "voices")))  # S7
        self.assertEqual(store.read_log(os.path.join(self.repo, "studio", "videos", "v2"))[0]["event"], "create")
        self.assertEqual(self.begin("v3", "--lang", "en"), 0, self.last_err)
        self.assertEqual(store.read_state(os.path.join(self.repo, "studio", "videos", "v3"))["source_lang"], "en")

    def test_ids_kinds_and_sources(self):
        for vid in ("V2", "-v2", "v_2", "a" * 65, "v2/x"):
            self.assertEqual(self.begin(vid), 2, vid)
        self.assertEqual(self.begin("a" * 64), 0, self.last_err)
        self.assertEqual(self.begin("v1"), 3)  # exists (public)
        os.makedirs(os.path.join(self.repo, "studio", "local", "videos", "v9"))
        self.assertEqual(self.begin("v9"), 3)  # exists (local)
        self.assertEqual(self.cli("begin", "v4", "--source", "docs/a.md", "--kind", "shorts"), 2)
        self.assertEqual(self.cli("begin", "v4", "--source", "docs/a.md"), 2)
        self.assertEqual(self.begin("v4", source=None), 2)
        self.assertEqual(self.begin("v4", source="docs/none.md"), 2)
        self.assertEqual(self.begin("v4", source="README.txt"), 2)
        outside = os.path.join(self.tmp, "outside.md")
        with open(outside, "w") as f:
            f.write("# outside\n")
        self.assertEqual(self.begin("v4", source=outside), 2)
        self.assertIn("a file in this repository", self.last_err)
        self.assertEqual(self.begin("v4", source=".claude/studio/charter.md"), 2)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "studio", "videos", "v4")))

    def test_d29(self):
        self.ver["stale_build"] = True
        self.assertEqual(self.begin(), 2)
        self.assertIn("yarn build", self.last_err)
        self.ver["stale_build"] = False
        self.ver["version"] = "0.12.0"
        self.assertEqual(self.begin(), 2)
        self.assertIn("min_version", self.last_err)
        self.ver["version"] = "0.12.1"
        self.ver["dirty"] = True
        self.assertEqual(self.begin(), 0, self.last_err)
        self.assertIn("uncommitted changes", self.last_err)
        self.ver.update(commit=None, dirty=None)
        self.assertEqual(self.begin("v3"), 0, self.last_err)
        self.assertIn("no git commit", self.last_err)
        machine.write(self.repo, "/abs/elsewhere")
        os.remove(machine.path(self.repo))
        self.assertEqual(self.begin("v5"), 2)
        self.assertIn("/std config s2v.path", self.last_err)

    def test_uncommitted_harness_refuses_with_the_paths(self):
        """v3 N13 · v4 R1 · R7: 3 and the blocking paths (10, then how many more)."""
        with open(os.path.join(self.repo, ".claude", "studio", "charter.md"), "a") as f:
            f.write("\nmore\n")
        self.assertEqual(self.begin(), 3)
        self.assertIn(".claude/studio/charter.md", self.last_err)
        self.assertIn("check_commit.py --stage harness", self.last_err)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "studio", "videos", "v2")))
        g = os.path.join(self.repo, ".claude", "studio", "guides")
        os.makedirs(g)
        for i in range(12):
            with open(os.path.join(g, "g%02d.md" % i), "w") as f:
                f.write("x\n")
        self.assertEqual(self.begin(), 3)
        self.assertIn("and 3 more", self.last_err)
        self.assertEqual(self.last_err.count(".claude/studio/"), 10 + self.last_err.count("check_commit.py"))
        # the same list in status
        code, out = self.cli("status"), self.last_out
        self.assertEqual(code, 0)
        self.assertIn("harness changes not committed", out)
        self.assertIn("and 3 more", out)
        # committed: begin goes
        helpers.git(self.repo, "add", "-A", "--", ".claude")
        helpers.git(self.repo, "commit", "-q", "-m", "harness")
        self.assertEqual(self.begin(), 0, self.last_err)
        self.cli("status")
        self.assertNotIn("harness changes not committed", self.last_out)

    def test_what_counts(self):
        """R1: only what a harness commit would stage — not untracked files outside its list, not local/, not videos."""
        for rel in (".claude/agents/notes.md", ".claude/studio/local/x.json", "studio/videos/v1/work/x.json",
                    "studio/out/x.mp4", "notes.txt"):
            p = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write("x\n")
        self.assertFalse(harnessgate.check(self.repo).blocking)
        for rel in (".claude/agents/std-new.md", ".claude/studio/formats/youtube.md"):
            p = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write("x\n")
            res = harnessgate.check(self.repo)
            self.assertIn(rel, res.paths)
            os.remove(p)
        # the Studio block of .gitignore counts, other lines do not
        gi = os.path.join(self.repo, ".gitignore")
        with open(gi, "a") as f:
            f.write("node_modules/\n")
        self.assertFalse(harnessgate.check(self.repo).blocking)
        with open(gi) as f:
            body = f.read()
        with open(gi, "w") as f:
            f.write(body.replace("/studio/out/\n", ""))
        self.assertEqual(harnessgate.check(self.repo).paths, [".gitignore"])

    def test_y4_junk_files_do_not_count(self):
        for rel in (".claude/studio/.DS_Store", ".claude/studio/guides/.script.md.swp", ".claude/studio/charter.md~",
                    ".claude/studio/guides/__pycache__/x.pyc", ".claude/agents/.std-writer.md.swo",
                    ".claude/studio/.#charter.md"):
            p = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write("junk")
        res = harnessgate.check(self.repo)
        self.assertFalse(res.blocking, res.message())
        self.assertEqual(self.begin(), 0, self.last_err)
        with open(os.path.join(self.repo, ".claude", "studio", "notes.md"), "w") as f:
            f.write("a real file")
        self.assertEqual(harnessgate.check(self.repo).paths, [".claude/studio/notes.md"])
        # Z4: in the scripts copy every file counts, leftovers included
        os.remove(os.path.join(self.repo, ".claude", "studio", "notes.md"))
        for rel in (".claude/studio/scripts/stdo/__pycache__/x.pyc", ".claude/studio/scripts/x.py~"):
            p = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write("junk")
            self.assertEqual(harnessgate.check(self.repo).paths, [rel])
            os.remove(p)

    def test_stage_done_needs_the_committed_harness_too(self):
        with open(os.path.join(self.repo, ".claude", "studio", "config.json"), "a") as f:
            f.write("\n")
        self.assertEqual(self.cli("stage-done", "v1", "script"), 3)
        self.assertIn(".claude/studio/config.json", self.last_err)


class HuskyBlock(StudioTestCase):
    """E19 (v4 R1 · R7): edits outside Studio's block of .husky/pre-commit do not count; inside it they do."""

    def setUp(self):
        super().setUp()
        import sys
        sys.path.insert(0, os.path.join(helpers.HERE, "drivers"))
        import make_harness
        self.repo = make_harness.make(os.path.join(self.tmp, "h"), husky=True)

    def test_husky_outside_and_inside(self):
        p = os.path.join(self.repo, ".husky", "pre-commit")
        self.assertFalse(harnessgate.check(self.repo).blocking, harnessgate.check(self.repo).message())
        with open(p) as f:
            body = f.read()
        with open(p, "w") as f:
            f.write("echo person\n" + body)
        self.assertFalse(harnessgate.check(self.repo).blocking)
        helpers.git(self.repo, "checkout", "--", ".husky/pre-commit")
        lines = body.splitlines(True)
        inside = [i for i, l in enumerate(lines) if "studio" in l.lower()][1]
        lines.insert(inside, "echo inside\n")
        with open(p, "w") as f:
            f.write("".join(lines))
        res = harnessgate.check(self.repo)
        self.assertTrue(res.blocking)
        self.assertIn(".husky/pre-commit", res.message())


# ---------------------------------------------------------------- pronounce.json (S2 · T1 · T3 · T4)

class Pronounce(FlowCase):
    def setUp(self):
        super().setUp()
        self.pj = os.path.join(self.repo, ".claude", "studio", "pronounce.json")
        with open(self.pj, "w") as f:
            f.write('{\n  "空港": "쿠우코오"\n}\n')
        helpers.git(self.repo, "add", self.pj)
        helpers.git(self.repo, "commit", "-q", "-m", "pronounce")
        self.pass_gate("1")
        self.pass_gate("2")

    def approved(self, entries, mode="human", sha_ok=True):
        p = os.path.join(self.vdir, "work", "ko", "pronounce-approved.json")
        with open(p, "w") as f:
            json.dump(entries, f, ensure_ascii=False)
        st = self.state()
        st["langs"]["ko"]["approved"]["2"][schema.PRONOUNCE_SHA] = file_sha(p) if sha_ok else "0" * 64
        st["langs"]["ko"]["approved"]["2"]["approved_by"] = mode
        self.write_state(st)

    def dictionary(self, text):
        with open(self.pj, "w") as f:
            f.write(text)

    def gate(self):
        return harnessgate.check(self.repo, providers=self.providers, ctx_of=cli._ctx_of(self.repo, cli._cfg_of(self.repo)))

    def test_s2_leftover_of_a_refused_video_commit_is_exempt(self):
        self.approved({"出口": "데구치"})
        self.dictionary('{\n  "空港": "쿠우코오",\n  "出口": "데구치"\n}\n')
        res = self.gate()
        self.assertFalse(res.blocking, res.message())
        self.assertTrue(res.exempted)
        self.assertEqual(self.cli("stage-done", "v1", "board", "--output", "youtube"), 0, self.last_err)  # E18/E21

    def test_not_exempt(self):
        self.approved({"出口": "데구치"})
        cases = {
            "another value": '{"空港": "쿠우코오", "出口": "데구찌"}',
            "not approved": '{"空港": "쿠우코오", "出口": "데구치", "入口": "이리구치"}',
            "existing changed": '{"空港": "구우코우", "出口": "데구치"}',
            "existing removed": '{"出口": "데구치"}',
            "not JSON": '{"空港": ',
        }
        for why, text in cases.items():
            self.dictionary(text)
            res = self.gate()
            self.assertTrue(res.blocking, why)
            self.assertIn(harnessgate.PRONOUNCE, res.paths, why)
        self.dictionary('{"空港": "쿠우코오", "出口": "데구찌"}')
        self.assertTrue(self.gate().leftover)  # additions only: the leftover hint (T3)
        self.dictionary('{"空港": "구우코우"}')
        self.assertFalse(self.gate().leftover)  # a change: no such hint
        self.dictionary('{"空港": "쿠우코오", "出口": "데구찌"}')
        self.assertEqual(self.cli("stage-done", "v1", "board", "--output", "youtube"), 3)
        self.assertIn("git checkout -- .claude/studio/pronounce.json", self.last_err)
        self.cli("status")
        self.assertIn("git checkout -- .claude/studio/pronounce.json", self.last_out)

    def test_t1_only_a_current_persons_record(self):
        added = '{"空港": "쿠우코오", "出口": "데구치"}'
        self.dictionary(added)
        self.approved({"出口": "데구치"}, mode="proxy")  # E24
        self.assertTrue(self.gate().blocking)
        self.approved({"出口": "데구치"}, sha_ok=False)  # the file is not the one ② recorded
        self.assertTrue(self.gate().blocking)
        self.approved({"出口": "데구치"})
        self.assertFalse(self.gate().blocking)
        self.ins["hashes"]["voice"] = "v-changed"  # E25: ② is stale now
        self.assertTrue(self.gate().blocking)
        self.ins["hashes"]["voice"] = F.current()["voice"]
        self.assertFalse(self.gate().blocking)
        st = self.state()
        st["langs"]["ko"]["status"] = "aborted"  # T3: an abandoned video exempts nothing
        self.write_state(st)
        res = self.gate()
        self.assertTrue(res.blocking)
        self.assertTrue(res.leftover)

    def test_y5_the_index_is_judged_too(self):
        self.approved({"出口": "데구치"})
        self.dictionary('{"空港": "쿠우코오", "入口": "이리구치"}')
        helpers.git(self.repo, "add", self.pj)  # an unapproved addition staged …
        self.dictionary('{"空港": "쿠우코오", "出口": "데구치"}')  # … and the work tree restored to an approved one
        res = self.gate()
        self.assertTrue(res.blocking)
        self.assertIn(harnessgate.PRONOUNCE, res.paths)
        helpers.git(self.repo, "add", self.pj)  # both approved now
        self.assertFalse(self.gate().blocking)
        helpers.git(self.repo, "rm", "-q", "--cached", self.pj)  # a staged deletion blocks
        self.assertTrue(self.gate().blocking)
        # also when the committed dictionary is empty (a deletion is never "no difference")
        helpers.git(self.repo, "add", self.pj)
        self.dictionary("{}")
        helpers.git(self.repo, "commit", "-q", "-am", "empty dictionary")
        self.assertFalse(self.gate().blocking)
        helpers.git(self.repo, "rm", "-q", "--cached", self.pj)
        self.assertTrue(self.gate().blocking)

    def test_t4_parsed_objects(self):
        self.dictionary('{"空港":"쿠우코오"}')  # E27: formatting only
        res = self.gate()
        self.assertFalse(res.blocking)
        self.assertFalse(res.exempted)  # no difference at all, not an exempted addition
        self.approved({"出口": "데구치"})
        self.dictionary('{"出口": "데구치",\r\n "空港": "쿠우코오"}')
        self.assertFalse(self.gate().blocking)


# ---------------------------------------------------------------- record-source

class RecordSource(FlowCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.begin(), 0, self.last_err)
        self.v2 = os.path.join(self.repo, "studio", "videos", "v2")

    def test_copy_and_hashes(self):
        with open(os.path.join(self.v2, "work", "assets.json"), "w") as f:
            f.write("{}")
        self.assertEqual(self.cli("record-source", "v2"), 0, self.last_err)
        st = store.read_state(self.v2)
        from stdo.state.hashes import source_hash_repo_md
        self.assertEqual(st["source"]["frozen_hash"], source_hash_repo_md(self.repo, "docs/a.md", []))
        self.assertEqual(st["source"]["copy_sha"], file_sha(os.path.join(self.repo, "docs", "a.md")))
        # M1d: an assets.json that check_scope did not pass for this copy is not recorded (test_m1d.Record)
        self.assertIsNone(st["source"]["assets_sha"])
        self.assertIn("not checked for this copy", self.last_out)
        with open(os.path.join(self.v2, "work", "source", "a.md")) as f:
            self.assertEqual(f.read(), self.text)

    def test_source_changed_while_copying(self):
        real = shutil.copyfile

        def copy_then_edit(a, b):
            real(a, b)
            with open(a, "a") as f:
                f.write("edited\n")
        with mock.patch.object(flow.shutil, "copyfile", copy_then_edit):
            self.assertEqual(self.cli("record-source", "v2"), 1)
        self.assertIn("changed while it was copied", self.last_err)
        self.assertIsNone(store.read_state(self.v2)["source"]["frozen_hash"])
        self.assertFalse(os.path.exists(os.path.join(self.v2, "work", "source", "a.md")))


# ---------------------------------------------------------------- hold / release-lock

class HoldRelease(FlowCase):
    def services(self, busy=None, state_dir=None):
        sd = state_dir or os.environ["S2V_STATE_DIR"]
        self.providers.services = lambda ctx: {"version": 1, "state_dir": sd, "busy": {"tts": busy, "gen": busy},
                                               "fake_unknown": 1}

    def held(self):
        return self.state()["langs"]["ko"]["held"]

    def test_hold_and_release(self):
        self.assertEqual(self.cli("hold", "v1", "render", "--reason", "x"), 2)
        self.assertEqual(self.cli("hold", "v1", "lock"), 2)
        self.assertEqual(self.cli("hold", "v1", "lock", "--reason", "busy (lock): another s2v"), 0, self.last_err)
        self.assertEqual(self.held()["state"], "lock")
        self.assertEqual(self.cli("hold", "v1", "lock", "--reason", "again"), 0)
        self.assertEqual(self.held()["detail"]["reason"], "again")
        self.services(busy={"reason": "lock"})
        self.assertEqual(self.cli("release-lock", "v1"), 4)
        self.assertEqual(self.held()["state"], "lock")
        self.services(state_dir=os.path.join(self.tmp, "another-state"))
        self.assertEqual(self.cli("release-lock", "v1"), 4)
        self.assertIn("state folder", self.last_err)
        self.services()
        self.assertEqual(self.cli("release-lock", "v1"), 0, self.last_err)
        self.assertIsNone(self.held())
        self.assertEqual(self.cli("release-lock", "v1"), 3)  # nothing held

    def test_release_lock_leaves_other_held_states(self):
        self.services()
        for h in schema.HELD:
            if h == "lock":
                continue
            st = self.state()
            st["langs"]["ko"]["held"] = {"state": h, "detail": {}, "since": schema.now()}
            self.write_state(st)
            self.assertEqual(self.cli("release-lock", "v1"), 3, h)
            self.assertEqual(self.held()["state"], h)
            self.assertEqual(self.cli("hold", "v1", "lock", "--reason", "x"), 4, h)  # never over another held

    def test_release_lock_with_the_fake_s2v(self):
        """E5: s2v services status through the fake CLI (busy, then free)."""
        need_node()
        machine.write(self.repo, FAKE_ROOT)
        from stdo.state.collect import Providers
        self.providers.services = Providers().services
        scen = os.path.join(self.tmp, "scenario.json")
        with open(scen, "w") as f:
            json.dump({"services": {"busy_tts": "lock"}}, f)
        os.environ["STUDIO_TEST_FAKE_S2V_SCENARIO"] = scen
        self.assertEqual(self.cli("hold", "v1", "lock", "--reason", "busy (lock): x"), 0)
        self.assertEqual(self.cli("release-lock", "v1"), 4, self.last_err)
        with open(scen, "w") as f:
            json.dump({}, f)
        self.assertEqual(self.cli("release-lock", "v1"), 0, self.last_err)
        with open(os.path.join(self.tmp, "calls.log")) as f:
            calls = [json.loads(l)["argv"] for l in f]
        self.assertEqual(calls, [["services", "status", "--json"]] * 2)


# ---------------------------------------------------------------- check results and stage-done

class StageChecks(FlowCase):
    auto_checks = False

    def setUp(self):
        super().setUp()
        F.write_assets(self.vdir)  # the checked assets the fixture state recorded (stage-done script compares them)

    def done(self, stage, **kw):
        args = ["stage-done", "v1", stage]
        for k, v in kw.items():
            args += ["--%s" % k, v]
        return self.cli(*args)

    def test_three_conditions(self):
        """v3 N2: result pass · this scripts version · the input sha of now — each one alone refuses (1)."""
        self.assertEqual(self.done("script"), 1)
        self.assertIn("no check result", self.last_err)
        checkfix.pass_check(self.repo, "v1", "script", self.providers, result="fail")
        self.assertEqual(self.done("script"), 1)
        self.assertIn("the check failed", self.last_err)
        p = checkfix.pass_check(self.repo, "v1", "script", self.providers)
        with open(p) as f:
            data = json.load(f)
        data["scripts_version"] = str(int(SCRIPTS_VERSION) - 1)
        with open(p, "w") as f:
            json.dump(data, f)
        self.assertEqual(self.done("script"), 1)
        self.assertIn("scripts version", self.last_err)
        checkfix.pass_check(self.repo, "v1", "script", self.providers)
        self.claims({"excerpts": ["The cat sat on the mat.", "It was warm."], "copy_excerpts": {}})  # an input changed
        self.assertEqual(self.done("script"), 1)
        self.assertIn("other inputs", self.last_err)
        checkfix.pass_check(self.repo, "v1", "script", self.providers)
        self.ins["s2v_version"] = "0.12.2+other"  # another s2v: the router stops first (4)
        self.assertEqual(self.done("script"), 4)
        self.ins["s2v_version"] = self.ver["id"]
        self.assertEqual(self.done("script"), 0, self.last_err)

    def test_y9_current_values_read_under_the_video_lock(self):
        import fcntl
        seen = []
        real = self.providers.inspect

        def inspect(ctx):
            fd = os.open(store.paths(self.vdir)["lock"], os.O_RDWR | os.O_CREAT)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen.append("free")
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                seen.append("locked")
            finally:
                os.close(fd)
            return real(ctx)
        self.providers.inspect = inspect
        checkfix.pass_check(self.repo, "v1", "script", self.providers)
        seen[:] = []
        self.assertEqual(self.done("script"), 0, self.last_err)
        self.assertEqual(seen, ["locked"])

    def test_another_stage_or_scope_file_does_not_count(self):
        p = checkfix.pass_check(self.repo, "v1", "verify", self.providers)
        shutil.copy(p, stagechecks.path(self.vdir, "ko", "script"))
        self.assertEqual(self.done("script"), 1)
        self.assertIn("not the check result of script", self.last_err)

    def test_inputs_follow_the_table(self):
        """Every input of a stage changes its sha (here: script and tts; files s2v lists with their sha)."""
        ctx = cli._ctx(self.repo, cli._cfg_of(self.repo), self.vdir, "ko")
        cur = self.providers.collect(ctx, self.state(), "ko")

        def sha(stage, scope=None, cur_=None, s2v="id1"):
            return stagechecks.input_sha(stage, stagechecks.Inputs(ctx, self.state(), "ko", scope, cur_ or cur,
                                                                    self.providers), s2v)
        base = sha("script")
        self.assertNotEqual(base, sha("script", s2v="id2"))
        self.assertEqual(sha("verify"), stagechecks.input_sha("verify", stagechecks.Inputs(
            ctx, self.state(), "ko", None, cur, self.providers), "anything"))  # no s2v id in verify
        withimg = dict(cur, files=[{"path": "a.png", "sha256": "1" * 64, "kind": "image"}])
        self.assertNotEqual(base, sha("script", cur_=withimg))
        other = dict(cur, files=[{"path": "a.png", "sha256": "2" * 64, "kind": "image"}])
        self.assertNotEqual(sha("script", cur_=withimg), sha("script", cur_=other))
        # Y6: every file the script shows or plays counts for script and board, not the audio-side ones
        for kind in ("logo", "thumbnail", "bgm", "video", "font", "character", "image,logo"):
            a = dict(cur, files=[{"path": "x", "sha256": "1" * 64, "kind": kind}])
            b = dict(cur, files=[{"path": "x", "sha256": "2" * 64, "kind": kind}])
            for st, sc in (("script", None), ("board", "youtube")):
                self.assertNotEqual(sha(st, sc, cur_=a), sha(st, sc, cur_=b), (kind, st))
        for kind in ("recording", "voice", "recording,voice"):
            a = dict(cur, files=[{"path": "x", "sha256": "1" * 64, "kind": kind}])
            b = dict(cur, files=[{"path": "x", "sha256": "2" * 64, "kind": kind}])
            self.assertEqual(sha("board", "youtube", cur_=a), sha("board", "youtube", cur_=b), kind)
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "formats"))
        with open(os.path.join(self.repo, ".claude", "studio", "formats", "youtube.md"), "w") as f:
            f.write("cer_max: 0.1\n")
        self.assertNotEqual(base, sha("script"))
        t1 = sha("tts")
        self.providers.sentences = lambda c: [{"id": "s:0:0", "lock": {"cer": 0.2}}]
        self.assertNotEqual(t1, sha("tts"))
        b1 = sha("board", "youtube")
        cfg = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(cfg) as f:
            c = json.load(f)
        c["visibility"]["public"] = ["**"]
        with open(cfg, "w") as f:
            json.dump(c, f)
        self.assertNotEqual(b1, sha("board", "youtube"))

    def test_render_needs_a_successful_record_render(self):
        """N2: a failing check file and no record-render — stage-done render cannot pass (1)."""
        self.auto_checks = True
        self.pass_all(upto="3")
        self.auto_checks = False
        self.assertEqual(self.done("render", output="youtube"), 1)
        # a passing check file without record-render: still refused
        checkfix.render(self.repo, "v1", "youtube", self.providers)
        st = self.state()
        st["langs"]["ko"]["renders"] = {}
        self.write_state(st)
        self.assertEqual(self.done("render", output="youtube"), 1)
        self.assertIn("record-render", self.last_err)
        self.assertEqual(checkfix.render(self.repo, "v1", "youtube", self.providers), 0)
        self.assertEqual(self.done("render", output="youtube"), 0, self.last_err)
        # the result replaced after record-render
        self.render_files("youtube", body=b"replaced")
        self.assertEqual(self.done("render", output="youtube"), 1)


class RecordRender(FlowCase):
    def setUp(self):
        super().setUp()
        self.pass_all(upto="3")

    def test_no_check_file(self):
        self.assertEqual(self.cli("record-render", "v1", "--output", "youtube"), 1)
        self.assertIn("run_s2v.py render first", self.last_err)
        self.assertEqual(self.cli("record-render", "v1", "--output", "nope"), 2)
        self.assertEqual(self.cli("record-render", "v1"), 2)

    def test_result_replaced(self):
        checkfix.render(self.repo, "v1", "youtube", self.providers)
        self.render_files("youtube", body=b"another file")
        self.assertEqual(self.cli("record-render", "v1", "--output", "youtube"), 1)
        self.assertIn("sha changed", self.last_err)

    def test_check_failed_and_exit(self):
        self.assertEqual(checkfix.render(self.repo, "v1", "youtube", self.providers, check_failed=True), 4)
        h = self.state()["langs"]["ko"]["held"]
        self.assertEqual((h["state"], h["detail"]["check_failed"]), ("render", True))
        st = self.state()
        st["langs"]["ko"]["held"] = None
        self.write_state(st)
        self.assertEqual(checkfix.render(self.repo, "v1", "youtube", self.providers, exit_code=1), 4)
        self.assertEqual(self.state()["langs"]["ko"]["held"]["detail"]["exit"], 1)
        self.assertEqual(self.cli("record-render", "v1", "--output", "youtube"), 4)  # held: nothing more

    def test_check_failed_line_wins(self):
        checkfix.render(self.repo, "v1", "youtube", self.providers)
        p = stagechecks.path(self.vdir, "ko", "render", "youtube")
        with open(p) as f:
            data = json.load(f)
        data["details"]["check_failed_line"] = "CHECK FAILED: 87/90 frames"
        with open(p, "w") as f:
            json.dump(data, f)
        st = self.state()
        st["langs"]["ko"]["renders"] = {}
        self.write_state(st)
        self.assertEqual(self.cli("record-render", "v1", "--output", "youtube"), 4)
        self.assertEqual(self.state()["langs"]["ko"]["held"]["state"], "render")

    def test_good_render(self):
        self.assertEqual(checkfix.render(self.repo, "v1", "youtube", self.providers, watermark=True), 0)
        r = self.state()["langs"]["ko"]["renders"]["youtube"]
        self.assertEqual((r["result"], r["proxy"], r["file"]), ("pass", True, "studio/out/v1/ko/youtube.ko.proxy.mp4"))


# ---------------------------------------------------------------- done

class Done(FlowCase):
    SCRIPT_PATH = "studio/videos/v1/script.ko.md"

    def setUp(self):
        super().setUp()
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "-m", "the video")

    def ok(self, keep=False, **over):
        tree = helpers.git(self.repo, "rev-parse", "HEAD^{tree}").stdout.strip()
        data = {"tree": tree, "head": "x", "kind": "video", "target": "v1", "studio_root": "studio",
                "paths": [self.SCRIPT_PATH], "states": {"v1": {"last_seq": self.state()["last_seq"]}},
                "session_id": "s", "summary": "s", "protected_changes": [], "in_progress": None,
                "scripts_version": SCRIPTS_VERSION, "approval": {"mode": "human", "answer": "커밋 x"}}
        data.update(over)
        written = okfile.write(self.repo, data)
        if keep:
            return okfile.keep_for_video(self.repo, "studio", written)
        return written

    def test_each_condition(self):
        """M2: kind · target · a person's answer · the state's seq · a commit with that tree — each broken alone."""
        self.assertEqual(self.cli("done", "v1"), 1)  # no record
        for over, word in (({"kind": "harness"}, "harness commit"), ({"target": "v2"}, "v2"),
                           ({"approval": None}, "person's answer"),
                           ({"approval": {"mode": "proxy"}}, "person's answer"),
                           ({"states": {"v1": {"last_seq": 0}}}, "state changed"),
                           ({"tree": "0" * 40}, "history has no commit")):
            self.ok(**over)
            self.assertEqual(self.cli("done", "v1"), 1, over)
            self.assertIn(word, self.last_err, over)
            self.assertEqual(self.state()["langs"]["ko"]["status"], "active")
        self.ok()
        self.assertEqual(self.cli("done", "v1"), 0, self.last_err)
        self.assertEqual(self.state()["langs"]["ko"]["status"], "done")
        self.assertEqual(self.cli("done", "v1"), 1)  # E15-like: the seq moved with done itself

    def test_y3_later_commits(self):
        """Y3: the hook kept the record in the video's folder; a later commit (and a later --stage of another kind)
        does not block done, a later change of the video's committed files does."""
        self.assertIsNone(okfile.keep_for_video(self.repo, "studio", dict(self.ok(), kind="harness")))
        self.assertIsNone(okfile.keep_for_video(self.repo, "studio", dict(self.ok(), approval={"mode": "proxy"})))
        p = self.ok(keep=True)
        self.assertEqual(p, okfile.video_record_path(self.repo, "studio", "v1"))
        with open(os.path.join(self.repo, "README.md"), "a") as f:
            f.write("x\n")
        helpers.git(self.repo, "commit", "-q", "-am", "a later commit")
        self.ok(kind="harness", target=None)  # commit-ok.json now belongs to another commit
        with open(os.path.join(self.repo, self.SCRIPT_PATH), "a") as f:
            f.write("changed\n")
        helpers.git(self.repo, "commit", "-q", "-am", "the script changed after the video commit")
        self.assertEqual(self.cli("done", "v1"), 1)
        self.assertIn("committed files changed", self.last_err)
        helpers.git(self.repo, "revert", "--no-edit", "HEAD")
        self.assertEqual(self.cli("done", "v1"), 0, self.last_err)
        self.assertEqual(self.state()["langs"]["ko"]["status"], "done")

    def test_z2_shared_files_of_other_videos(self):
        shared = ".claude/studio/pronounce.json"
        with open(os.path.join(self.repo, shared), "w") as f:
            f.write('{"空港": "쿠우코오"}')
        helpers.git(self.repo, "add", shared)
        helpers.git(self.repo, "commit", "-q", "-m", "the video with its dictionary merge")
        self.ok(keep=True, paths=[self.SCRIPT_PATH, shared])
        with open(os.path.join(self.repo, shared), "w") as f:
            f.write('{"空港": "쿠우코오", "出口": "데구치"}')
        helpers.git(self.repo, "commit", "-q", "-am", "another video's commit merges its readings")
        self.assertEqual(self.cli("done", "v1"), 0, self.last_err)

    def test_record_protected(self):
        from stdo.guard import protect
        self.assertEqual(protect.classify(["studio", "videos", "v1", "work", "commit-ok.json"], "studio", False),
                         "P-STATE")


# ---------------------------------------------------------------- abandon and overlay (evidence)

class Abandon(FlowCase):
    def test_abandon(self):
        self.assertEqual(self.cli("abandon", "v1"), 6)
        self.pend(["abandon", "v1"], "중단 v1 en")
        self.assertEqual(self.cli("abandon", "v1"), 6)
        self.pend(["abandon", "v1"], "중단 v1 ko")
        self.assertEqual(self.cli("abandon", "v1"), 0, self.last_err)
        self.assertEqual(self.state()["langs"]["ko"]["status"], "aborted")
        self.assertTrue(os.path.exists(os.path.join(self.vdir, "script.ko.md")))
        self.pend(["abandon", "v1"], "중단 v1 ko")
        self.assertEqual(self.cli("abandon", "v1"), 2)


class Overlay(FlowCase):
    DATA = {"internal": {"hosts": ["wiki.example.invalid"], "terms": ["Kestrel"], "sources": [{"url": "https://x"}],
                         "videos": [], "actors": []}}

    def source_file(self, data=None, where=None, raw=None):
        self.n_src = getattr(self, "n_src", 0) + 1
        p = where or os.path.join(self.tmp, "overlay-%d.json" % self.n_src)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        body = raw if raw is not None else json.dumps(data or self.DATA).encode()
        with open(p, "wb") as f:
            f.write(body)
        return p, hash_of_bytes(body)[:12]

    def run_overlay(self, p, h, answer=True, *extra):
        argv = ["overlay", "--from", p, "--expect", h] + list(extra)
        if answer:
            try:
                from stdo.state.flow import overlay_lines
                with open(p, "rb") as f:
                    shown = "\n".join(overlay_lines(f.read()))  # J29: every key and its count (M1c)
            except Exception:  # noqa: BLE001 — a source the command refuses anyway
                shown = ""
            self.pend(argv, "사내설정 %s" % h, question="사내설정 %s\n%s" % (h, shown))
        return self.cli(*argv)

    def test_good(self):
        p, h = self.source_file()
        self.assertEqual(self.run_overlay(p, h, False), 6)
        self.assertEqual(self.run_overlay(p, h), 0, self.last_err)
        with open(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json"), "rb") as f:
            raw = f.read()
        with open(os.path.join(paths.backup_root(), paths.repo_key(self.repo), "overlay.sha")) as f:
            self.assertEqual(f.read().strip(), hash_of_bytes(raw))
        p2, h2 = self.source_file(where=os.path.join(self.repo, ".claude", "studio", "local", "new.json"))
        self.assertEqual(self.run_overlay(p2, h2), 0, self.last_err)

    def test_refused_sources(self):
        p, h = self.source_file(where=os.path.join(self.repo, "docs", "o.json"))
        self.assertEqual(self.run_overlay(p, h), 1)  # inside the repository (tracked or not)
        self.assertIn("inside the repository", self.last_err)
        p, h = self.source_file()
        link = os.path.join(self.tmp, "link.json")
        os.symlink(p, link)
        self.assertEqual(self.run_overlay(link, h), 1)
        self.assertIn("symbolic link", self.last_err)
        big, hb = self.source_file(raw=b'{"internal": {"terms": ["' + b"x" * (65 * 1024) + b'"]}}')
        self.assertEqual(self.run_overlay(big, hb), 1)
        self.assertIn("64 KB", self.last_err)
        self.assertEqual(self.run_overlay(p, "0" * 12), 1)
        self.assertIn("is not the sha", self.last_err)
        bad, hbad = self.source_file(data={"internal": {"terms": ["abc"]}})
        self.assertEqual(self.run_overlay(bad, hbad), 1)
        self.assertIn("4 characters", self.last_err)
        bad, hbad = self.source_file(data={"internal": {"other": []}})
        self.assertEqual(self.run_overlay(bad, hbad), 1)
        bad, hbad = self.source_file(data={"internal": {}, "more": 1})
        self.assertEqual(self.run_overlay(bad, hbad), 1)
        self.assertEqual(self.run_overlay(p, h, True, "--proxy"), 2)
        self.assertEqual(self.run_overlay("relative.json", h), 2)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json")))


def hash_of_bytes(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- run_s2v.py with the fake s2v CLI

class RunS2V(FlowCase):
    def setUp(self):
        need_node()
        super().setUp()
        machine.write(self.repo, FAKE_ROOT)
        with open(os.path.join(self.vdir, "script.ko.md"), "w") as f:
            f.write(SCRIPT)
        self.scenario({})
        r = subprocess.run(["node", os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js"), "tts",
                            os.path.join(self.vdir, "script.ko.md")], capture_output=True, text=True,
                           env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)

    def scenario(self, data):
        self.scen = os.path.join(self.tmp, "scenario.json")
        with open(self.scen, "w") as f:
            json.dump(data, f)
        os.environ["STUDIO_TEST_FAKE_S2V_SCENARIO"] = self.scen

    def run_s2v(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = s2vrun.main(list(argv), providers=self.providers, env=env or dict(os.environ), cwd=self.repo)
        self.last_out, self.last_err = out.getvalue(), err.getvalue()
        return code

    def outs(self):
        d = os.path.join(self.repo, "studio", "out", "v1", "ko")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def calls(self):
        try:
            with open(os.path.join(self.tmp, "calls.log")) as f:
                return [json.loads(l)["argv"] for l in f]
        except OSError:
            return []

    def proxy_gate(self, gate):
        for st in self.STAGES[gate]:
            args = ["stage-done", "v1", st] + (["--output", "youtube"] if gate in ("3", "4a") else [])
            self.assertEqual(self.cli(*args), 0, self.last_err)
        h = self.snapshot() if gate == "3" else self.show(gate, "youtube")
        self.assertEqual(self.approve(gate, h, "--proxy", mode="proxy", question="proxy"), 0, self.last_err)

    def snapshot(self):
        self.assertEqual(self.run_s2v("snapshot", "v1", "--output", "youtube"), 0, self.last_err)
        line = [l for l in self.last_out.splitlines() if l.startswith("hash12 ")]
        self.assertTrue(line, self.last_out)
        return line[0].split()[1]

    def test_argv_and_check_file(self):
        self.pass_all(upto="3")
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube"), 0, self.last_err)
        main_js = os.path.join(FAKE_ROOT, "packages", "cli", "dist", "main.js")
        out_dir = os.path.join(self.repo, "studio", "out", "v1", "ko")
        self.assertEqual(self.calls()[-1], ["render", os.path.join(self.vdir, "script.ko.md"), "--output", "youtube",
                                            "--frozen-audio", "--out-dir", out_dir])
        self.assertEqual(s2vrun.argv_for("/s", "render", "a.md", "y", "/o", True)[:2],
                         ["node", "/s/packages/cli/dist/main.js"])
        self.assertTrue(os.path.exists(main_js))
        data = stagechecks.read(self.vdir, "ko", "render", "youtube")
        det = data["details"]
        self.assertEqual((data["result"], det["exit"], det["watermark"]), ("pass", 0, False))
        self.assertTrue(det["ok_line"].startswith("ok: "))
        self.assertTrue(det["arrow_line"].startswith("→ ") and det["arrow_line"].endswith("s)"))
        self.assertEqual(det["mp4_sha"], file_sha(os.path.join(out_dir, "youtube.ko.mp4")))
        self.assertIn("youtube.ko.chapters.txt", self.outs())
        self.assertEqual(self.cli("record-render", "v1", "--output", "youtube"), 0, self.last_err)
        self.assertEqual(self.cli("stage-done", "v1", "render", "--output", "youtube"), 0, self.last_err)

    def test_check_failed_and_exit_after_write(self):
        self.pass_all(upto="3")
        for scen in ({"render": {"check_failed": True}}, {"render": {"exit_after_write": 1}},
                     {"render": {"no_ok_line": True}}):
            self.scenario(scen)
            self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube"), 1, scen)
            data = stagechecks.read(self.vdir, "ko", "render", "youtube")
            self.assertEqual(data["result"], "fail", scen)
        self.assertEqual(self.cli("record-render", "v1", "--output", "youtube"), 4)
        self.assertEqual(self.state()["langs"]["ko"]["held"]["state"], "render")

    def test_usage_and_busy(self):
        before = self.calls()
        self.assertEqual(self.run_s2v("render", "v1"), 2)
        self.assertEqual(self.run_s2v("render", "v1", "--output", "nope"), 2)
        self.assertEqual(self.run_s2v("encode", "v1", "--output", "youtube"), 2)
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube", "--watermark", "proxy"), 2)
        lock = os.path.join(self.vdir, "work", "ko", ".run_s2v.youtube.lock")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        with store.Lock(lock):
            self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube"), 5)
        self.assertEqual(self.calls(), before)  # s2v never ran

    def test_watermark_from_the_state_only(self):
        st = F.state()
        c = F.current()
        F.approve_all(st, c, upto="4a")
        env = {}
        self.assertEqual(s2vrun.watermark(st, "ko", "youtube", env, self.repo)[0], False)
        for g in ("1", "2", "3"):
            s2 = json.loads(json.dumps(st))
            rec = s2["langs"]["ko"]["approved"][g]
            (rec["youtube"] if g == "3" else rec)["approved_by"] = "proxy"
            self.assertEqual(s2vrun.watermark(s2, "ko", "youtube", env, self.repo)[0], True, g)
            s3 = json.loads(json.dumps(st))
            if g == "3":
                del s3["langs"]["ko"]["approved"]["3"]["youtube"]
            else:
                del s3["langs"]["ko"]["approved"][g]
            self.assertEqual(s2vrun.watermark(s3, "ko", "youtube", env, self.repo)[0], True, g)
        s4 = json.loads(json.dumps(st))
        s4["langs"]["ko"]["approved"]["4a"]["youtube"]["approved_by"] = "proxy"
        self.assertEqual(s2vrun.watermark(s4, "ko", "youtube", env, self.repo)[0], False)  # ④a's own is not read

    def sandbox_env(self):
        with open(paths.sandbox_file(), "w") as f:
            json.dump({"sandbox_root": self.tmp}, f)
        return dict(os.environ, STUDIO_SANDBOX="1")

    def test_e10c_a_proxy_session_always_marks(self):
        self.pass_all(upto="3")
        env = self.sandbox_env()
        self.assertTrue(sandbox.active(env, self.repo))
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube", env=env), 0, self.last_err)
        self.assertIn("youtube.ko.proxy.mp4", self.outs())
        self.assertNotIn("youtube.ko.mp4", self.outs())
        self.assertEqual(self.calls()[-1][-2:], ["--watermark", "proxy"])
        self.assertTrue(stagechecks.read(self.vdir, "ko", "render", "youtube")["details"]["watermark"])

    def test_y7_the_other_named_render_goes(self):
        self.pass_all(upto="3")
        env = self.sandbox_env()
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube", env=env), 0, self.last_err)
        self.assertTrue([n for n in self.outs() if ".proxy." in n])
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube"), 0, self.last_err)
        self.assertFalse([n for n in self.outs() if ".proxy." in n], self.outs())
        self.assertIn("youtube.ko.proxy.mp4",
                      stagechecks.read(self.vdir, "ko", "render", "youtube")["details"]["removed_other_name"])
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube", env=env), 0, self.last_err)
        self.assertNotIn("youtube.ko.mp4", self.outs())

    def test_e10b_hand_over(self):
        """§4.2 v3 N3 · v4 R4: proxy ①–③ → marked render; a person approves ① ② again (allowed by the code as it is),
        ③ on a new snapshot's hash12; the render is unmarked only once ①–③ are all the person's; ④a by the person."""
        for g in ("1", "2", "3"):
            self.proxy_gate(g)
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube"), 0, self.last_err)
        self.assertIn("youtube.ko.proxy.mp4", self.outs())
        self.assertEqual(self.cli("record-render", "v1", "--output", "youtube"), 0, self.last_err)
        self.assertEqual(self.cli("stage-done", "v1", "render", "--output", "youtube"), 0, self.last_err)
        # hand over: ① and ② shown again and approved by the person (re-approval of a proxy record)
        for g in ("1", "2"):
            h = self.show(g)
            self.assertEqual(self.approve(g, h), 0, self.last_err)
            self.assertEqual(self.state()["langs"]["ko"]["approved"][g]["approved_by"], "human")
        # ③ still the proxy's: the render stays marked
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube"), 0, self.last_err)
        self.assertTrue(stagechecks.read(self.vdir, "ko", "render", "youtube")["details"]["watermark"])
        # ③: a new snapshot, its printed hash12 is the one to approve
        h3 = self.snapshot()
        self.assertEqual(self.approve("3", h3), 0, self.last_err)
        self.assertEqual(self.state()["langs"]["ko"]["approved"]["3"]["youtube"]["approved_by"], "human")
        self.assertEqual(self.run_s2v("render", "v1", "--output", "youtube"), 0, self.last_err)
        det = stagechecks.read(self.vdir, "ko", "render", "youtube")["details"]
        self.assertFalse(det["watermark"])
        self.assertIn("youtube.ko.mp4", self.outs())
        self.assertEqual(self.cli("record-render", "v1", "--output", "youtube"), 0, self.last_err)
        self.assertEqual(self.cli("stage-done", "v1", "render", "--output", "youtube"), 0, self.last_err)
        h4 = self.show("4a", "youtube")
        self.assertEqual(self.approve("4a", h4), 0, self.last_err)
        rec = self.state()["langs"]["ko"]["approved"]["4a"]["youtube"]
        self.assertEqual(rec["approved_by"], "human")
        self.assertFalse(self.state()["langs"]["ko"]["renders"]["youtube"]["proxy"])

    def test_z5_end_retried_while_the_state_is_busy(self):
        self.pass_all(upto="2")
        for st in ("board", "visual-check"):
            self.assertEqual(self.cli("stage-done", "v1", st, "--output", "youtube"), 0, self.last_err)
        real = s2vrun._state_cli
        calls = []

        def busy_twice(argv, providers, cwd):
            if "--end" in argv:
                calls.append(1)
                if len(calls) <= 2:
                    return 5, "", "busy\n"
            return real(argv, providers, cwd)
        with mock.patch.object(s2vrun, "_state_cli", busy_twice), mock.patch.object(s2vrun, "END_WAIT", 0):
            self.assertEqual(self.run_s2v("snapshot", "v1", "--output", "youtube"), 0, self.last_err)
        self.assertEqual(len(calls), 3)
        self.assertTrue(self.last_out.startswith("hash12 "))
        self.assertEqual(s2vrun.END_TRIES * s2vrun.END_WAIT, 10.0)

        def always_busy(argv, providers, cwd):
            return (5, "", "busy\n") if "--end" in argv else real(argv, providers, cwd)
        with mock.patch.object(s2vrun, "_state_cli", always_busy), mock.patch.object(s2vrun, "END_WAIT", 0):
            self.assertEqual(self.run_s2v("snapshot", "v1", "--output", "youtube"), 5)

    def test_snapshot_needs_new_stills(self):
        self.pass_all(upto="2")
        for st in ("board", "visual-check"):
            self.assertEqual(self.cli("stage-done", "v1", st, "--output", "youtube"), 0, self.last_err)
        h = self.snapshot()
        self.assertEqual(self.calls()[-1][:2], ["snapshot", os.path.join(self.vdir, "script.ko.md")])
        self.assertIn("--frames", self.calls()[-1])
        # a snapshot s2v cannot take: shown stays at --begin, nothing approved
        self.scenario({"snapshot": {"interrupt": True}})
        self.assertEqual(self.run_s2v("snapshot", "v1", "--output", "youtube"), 1)
        self.assertTrue(self.state()["langs"]["ko"]["shown_pending"].get("youtube"))
        self.assertTrue(h)


# ---------------------------------------------------------------- s2v lint run by a check script

class Lint(StudioTestCase):
    def setUp(self):
        need_node()
        super().setUp()
        self.repo = helpers.make_repo(self.tmp)
        self.script = os.path.join(self.repo, "studio", "videos", "v1", "script.ko.md")
        os.makedirs(os.path.dirname(self.script))

    def lint(self, text, scenario=None, mode="lint"):
        from stdo import s2vlint
        with open(self.script, "w") as f:
            f.write(text)
        env = dict(os.environ)
        if scenario is not None:
            p = os.path.join(self.tmp, "scenario.json")
            with open(p, "w") as f:
                json.dump(scenario, f)
            env["STUDIO_TEST_FAKE_S2V_SCENARIO"] = p
        return s2vlint.run(FAKE_ROOT, self.script, mode, env=env)

    def test_length_warnings_fail(self):
        """v3 N6 · v4 R3: s2v exits 0 with a length warning; the Studio check fails."""
        r = self.lint(SCRIPT.replace('aspect: "16:9" }', 'aspect: "16:9", maxDuration: 1 }'))
        self.assertEqual(r.code, 0)
        self.assertEqual(r.failures[0]["code"], "max-duration")
        self.assertFalse(r.passed)
        r = self.lint(SCRIPT.replace("---\n\n#", "targetDuration: 60\n---\n\n#", 1))
        self.assertEqual((r.code, [d["code"] for d in r.failures]), (0, ["target-duration"]))
        r = self.lint(SCRIPT)
        self.assertTrue(r.passed, r.details())
        r = self.lint(SCRIPT, {"lint": {"warnings": [{"code": "subtitle-font", "message": "x"}]}})
        self.assertTrue(r.passed)  # other warnings are shown, not failures
        # Y8: a Latin word left in Korean (or Japanese) narration fails; in English narration it is just a warning
        r = self.lint(SCRIPT, {"lint": {"warnings": [{"code": "unread-word", "message": "API"}]}})
        self.assertEqual((r.lang, [d["code"] for d in r.failures]), ("ko", ["unread-word"]))
        from stdo import s2vlint
        r2 = s2vlint.Result(r.mode, r.code, r.diagnostics, r.stderr_tail, "ko", fail_unread=False)
        self.assertTrue(r2.passed)  # Z3: information only at the script stage (the caller chooses)
        r = self.lint(SCRIPT.replace("lang: ko", "lang: ja"), {"lint": {"warnings": [{"code": "unread-word",
                                                                                     "message": "API"}]}})
        self.assertFalse(r.passed)
        r = self.lint(SCRIPT.replace("lang: ko", "lang: en"), {"lint": {"warnings": [{"code": "unread-word",
                                                                                     "message": "API"}]}})
        self.assertTrue(r.passed, r.details())
        r = self.lint(SCRIPT, {"lint": {"errors": [{"code": "cast", "message": "x"}]}})
        self.assertEqual(r.code, 1)
        self.assertEqual([d["code"] for d in r.failures], ["cast"])
        self.assertFalse(r.passed)
        r = self.lint(SCRIPT, {"check": {"overflow": True}}, mode="check")
        self.assertEqual((r.code, r.failures[0]["code"]), (1, "subtitle-overflow"))


# ---------------------------------------------------------------- the guard

class GuardFlow(GuardApproval):
    def test_evidence_free_flow_commands(self):
        for cmd in ("begin v2 --source docs/a.md --kind youtube", "record-source v", "hold v lock --reason x",
                    "release-lock v", "record-render v --output youtube", "done v"):
            deny, ctx = self.run_hook("python3 .claude/studio/scripts/state.py %s" % cmd)
            self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
            self.assertIsNone(ctx.allow, cmd)
            self.assertIsNone(self.pending(), cmd)
        deny, ctx = self.run_hook("python3 .claude/studio/scripts/run_s2v.py render v --output youtube")
        self.assertIsNone(deny, deny and deny.message())

    def test_abandon_needs_the_persons_answer(self):
        cmd = "python3 .claude/studio/scripts/state.py abandon v"
        self.assertRule(cmd, "G-EVIDENCE")
        self.turn(label="중단 v en")
        self.assertRule(cmd, "G-EVIDENCE")
        self.turn(label="중단 v ko", qtext="v를 중단할까요?")  # no [v] in the question
        self.assertRule(cmd, "G-EVIDENCE")
        self.turn(label="중단 v ko")
        self.assertAllow(cmd)
        self.assertEqual(self.pending()["answer"], "중단 v ko")

    def test_overlay_needs_the_persons_answer(self):
        cmd = "python3 .claude/studio/scripts/state.py overlay --from /tmp/o.json --expect %s" % H
        self.assertRule(cmd, "G-EVIDENCE")
        self.turn(label="사내설정 %s" % H)
        self.assertAllow(cmd)
        self.assertRule("python3 .claude/studio/scripts/state.py overlay v --from /tmp/o.json --expect %s" % H,
                        "G-APPROVAL")


class GuardM1b(JudgeCase):
    def test_check_files_are_protected(self):
        for rel in ("studio/videos/v/work/ko/checks/render--youtube.json", "studio/videos/v/work/checks/x.json",
                    "studio/videos/v/work/assets.json", "studio/videos/v/work/ko/pronounce-approved.json",
                    "studio/local/videos/w/work/ko/checks/tts.json"):
            d = self.decide("Write", {"file_path": os.path.join(self.repo, rel), "content": "{}"})
            self.assertIsNotNone(d, rel)
            self.assertEqual(d.rule, "G-PROT", rel)
            self.assertDeny("echo '{}' > %s" % rel, "G-PROT")
        self.assertIsNone(self.decide("Write", {"file_path": os.path.join(self.repo, "studio/videos/v/work/ko/"
                                                                                     "verify.draft.json"),
                                                "content": "{}"}))

    def test_nit_a_command_word_from_a_variable(self):
        d = self.assertDeny('S2V=/x; "$S2V" tts studio/videos/v/script.md', "G-OPAQUE")
        self.assertIn("write the command's path literally (or use npx", d.message())
        d = self.assertDeny("`which node` x.js studio/videos/v/script.md", "G-OPAQUE")
        self.assertIn("write the command's path literally", d.message())

    def test_nit_b_recursive_copy_into_the_studio_folder(self):
        os.makedirs(os.path.join(self.tmp, "imgs"))
        with open(os.path.join(self.tmp, "imgs", "a.png"), "w") as f:
            f.write("png")
        d = self.assertDeny("cp -R %s studio/videos/v/assets" % os.path.join(self.tmp, "imgs"), "G-PROT")
        self.assertIn("copy them one at a time", d.message())
        self.assertIn("Studio script", d.message())
        self.assertPass("cp %s studio/videos/v/a.png" % os.path.join(self.tmp, "imgs", "a.png"))

    def test_y1_render_and_snapshot_only_through_run_s2v(self):
        main_js = "/abs/script2video/packages/cli/dist/main.js"
        sc = "studio/videos/v/script.md"
        for cmd in ("node %s render %s --output youtube --frozen-audio --out-dir /tmp/x" % (main_js, sc),
                    "node %s render %s --output youtube --frozen-audio --out-dir studio/out/v/ko" % (main_js, sc),
                    "node %s snapshot %s --output youtube --frozen-audio --frames --out-dir /tmp/x" % (main_js, sc),
                    "node /elsewhere/packages/cli/dist/main.js render %s --frozen-audio" % sc,
                    "s2v render %s --output youtube --frozen-audio" % sc,
                    "s2v snapshot %s --frozen-audio" % sc,
                    "cd studio && s2v render videos/v/script.md --frozen-audio",
                    "python3 .claude/studio/scripts/lock.py run --kind tts -- s2v render %s" % sc):
            d = self.assertDeny(cmd, "G-WRAP")
            self.assertIn("run_s2v.py render|snapshot", d.message())
        for cmd in ("s2v lint %s" % sc, "node %s inspect %s --json" % (main_js, sc),
                    "python3 .claude/studio/scripts/run_s2v.py render v --output youtube",
                    "python3 .claude/studio/scripts/run_s2v.py snapshot v --output youtube"):
            self.assertPass(cmd)
        # Z1: dev (it runs snapshot / render --draft and keeps the servers up), takes/direct with --out-dir
        for cmd in ("s2v dev %s" % sc, "node %s dev %s --output youtube" % (main_js, sc),
                    "s2v takes %s --out-dir /tmp/x" % sc, "s2v direct %s --out-dir=studio/out" % sc):
            self.assertDeny(cmd, "G-WRAP")
        for cmd in ("s2v takes %s --list" % sc, "s2v direct %s --json" % sc,
                    "s2v check %s" % sc, "s2v sentences %s --json" % sc, "s2v services status --json",
                    "python3 .claude/studio/scripts/lock.py run --kind tts -- s2v tts %s" % sc):
            self.assertPass(cmd)
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        self.assertPass("s2v render %s/script.md --frozen-audio" % other, cwd=other)  # not a Studio repository

    def test_run_s2v_is_version_checked(self):
        p = os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "__init__.py")
        with open(p, "w") as f:
            f.write('SCRIPTS_VERSION = "%d"\n' % (int(SCRIPTS_VERSION) - 1))
        self.assertDeny("python3 .claude/studio/scripts/run_s2v.py render v --output youtube", "G-VERSION")


class Y2Writers(StudioTestCase):
    """The library's protected writers refuse in a process that is not one of Studio's entry scripts."""

    def test_import_and_write_is_refused(self):
        repo = helpers.make_repo(self.tmp)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(os.path.join(vdir, "work"))
        code = """
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, %(scripts)r)
from stdo import machine
from stdo.commit import okfile
from stdo.state import evidence, stagechecks, store
calls = {
  "stagechecks.write": lambda: stagechecks.write(%(vdir)r, "ko", "script", None, "pass", {}, "x"),
  "evidence.consume": lambda: evidence.consume(%(repo)r, {"session_id": "s", "tool_use_id": "t", "question_index": 0},
                                               "v1", "x", log=%(log)r),
  "okfile.write": lambda: okfile.write(%(repo)r, {"tree": "0" * 40, "paths": []}),
  "okfile.keep_for_video": lambda: okfile.keep_for_video(%(repo)r, "studio", {"kind": "video", "target": "v1",
                                                                              "approval": {"mode": "human"}}),
  "machine.write": lambda: machine.write(%(repo)r, "/x"),
  "store.create": lambda: store.create(%(vdir)r, {"video": "v1"}),
}
for name, f in calls.items():
    try:
        f()
        print("WROTE", name)
    except RuntimeError as e:
        print("REFUSED", name)
"""
        script = os.path.join(self.tmp, "agent.py")
        with open(script, "w") as f:
            f.write(code % {"scripts": helpers.SCRIPTS, "vdir": vdir, "repo": repo,
                            "log": os.path.join(self.tmp, "log.jsonl")})
        out = subprocess.run(["python3", "-B", script], capture_output=True, text=True, cwd=self.tmp)
        lines = sorted(out.stdout.split("\n")[:-1])
        self.assertEqual(lines, sorted("REFUSED " + n for n in ("stagechecks.write", "evidence.consume", "okfile.write",
                                                               "okfile.keep_for_video", "machine.write",
                                                               "store.create")), out.stderr)
        self.assertFalse(os.path.exists(stagechecks.path(vdir, "ko", "script")))
        # the entry scripts do enable it
        for entry in ("state.py", "run_s2v.py", "check_commit.py"):
            with open(os.path.join(helpers.SCRIPTS, entry)) as f:
                body = f.read()
            self.assertTrue(re.search(r"enable(_writes)?\(\)|entry\(\)", body), entry)


class SandboxShared(StudioTestCase):
    def test_guard_and_scripts_share_one_rule(self):
        from stdo.guard import proxy
        self.assertIs(proxy.active, sandbox.active)
