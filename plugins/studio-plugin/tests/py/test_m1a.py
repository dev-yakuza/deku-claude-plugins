"""M1a (m1-plan §3): this machine's s2v path in `.claude/studio/local/machine.json` and every reader of it, the
guard's s2v recognition without it (N8b), video labels and the hash12 of a video/language/gate, `[<video>]` in the
question, and the used-answer record shared by the worktrees (`<git common dir>/studio/`)."""

import contextlib
import subprocess
import copy
import io
import json
import os

import helpers
import state_fixtures as F
import transcripts as TR
from approve_base import ApproveCase
from commit_base import SID, CommitCase
from harness_base import HarnessCase
from helpers import StudioTestCase
from stdo import lockcli, machine, paths
from stdo.commit import okfile
from stdo.guard import judge, transcript
from stdo.state import cli, evidence, labels, shown, store
from stdo.state.collect import Providers
from test_guard_judge import JudgeCase

H = "3f2a9c0d1e4b"
HOME_LIKE = "/" + "Users/alice/projects/script2video"  # a home-style path (kept apart: shipped files name none)


def video_state(repo, vid, lang="ko"):
    d = os.path.join(repo, "studio", "videos", vid, "work")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "state.json"), "w") as f:
        json.dump({"video": vid, "source_lang": lang}, f)


# ---------------------------------------------------------------- §3.1 machine.json

class Machine(StudioTestCase):
    def test_read_and_write(self):
        repo = helpers.make_repo(self.tmp, s2v=None)
        self.assertIsNone(machine.s2v_path(repo))
        with self.assertRaises(machine.Missing):
            machine.require_s2v_path(repo)
        machine.write(repo, "/opt/s2v/")
        self.assertEqual(machine.s2v_path(repo), "/opt/s2v")
        with open(machine.path(repo)) as f:
            self.assertEqual(json.load(f), {"schema": 1, "s2v": {"path": "/opt/s2v"}})
        # ignored: never part of a commit
        self.assertEqual(helpers.git(repo, "status", "--porcelain").stdout, "")
        for bad in ({"schema": 2, "s2v": {"path": "/opt/s2v"}}, {"schema": 1, "s2v": {"path": "rel/s2v"}},
                    {"schema": 1, "s2v": {"path": ""}}, {"schema": 1, "s2v": "/opt/s2v"}, {"schema": 1}, []):
            with open(machine.path(repo), "w") as f:
                json.dump(bad, f)
            self.assertIsNone(machine.s2v_path(repo), bad)
        with open(machine.path(repo), "w") as f:
            f.write("{broken")
        self.assertIsNone(machine.s2v_path(repo))
        with self.assertRaises(ValueError):
            machine.write(repo, "relative/s2v")

    def test_config_has_no_path_any_more(self):
        repo = helpers.make_repo(self.tmp)
        with open(os.path.join(repo, ".claude", "studio", "config.json")) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["s2v"], {"min_version": "0.12.1"})
        self.assertIn("s2v", cfg["protected_keys"])

    def _video_repo(self, s2v):
        repo = helpers.make_repo(self.tmp, s2v=s2v)
        vdir = os.path.join(repo, "studio", "videos", "v1")
        os.makedirs(vdir)
        store.enable_writes()
        store.create(vdir, F.state())
        with open(os.path.join(vdir, "script.ko.md"), "w") as f:
            f.write("# script\n")  # with a script, next asks s2v inspect
        return repo, vdir

    def test_state_py_reads_machine_json_only(self):
        repo, vdir = self._video_repo(None)
        # an old-format config.json path is never read
        p = os.path.join(repo, ".claude", "studio", "config.json")
        with open(p) as f:
            cfg = json.load(f)
        cfg["s2v"]["path"] = "/opt/old-config-path"
        with open(p, "w") as f:
            json.dump(cfg, f)
        self.assertIsNone(cli._ctx(repo, cfg, vdir, "ko")["s2v_path"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["next", "v1"], providers=Providers(source=lambda c, s: ("src1", "")), cwd=repo)
        self.assertEqual(code, 2, err.getvalue())
        self.assertIn("/std config s2v.path", err.getvalue())
        machine.write(repo, "/opt/s2v")
        self.assertEqual(cli._ctx(repo, cfg, vdir, "ko")["s2v_path"], "/opt/s2v")
        seen = []
        ins = {"s2v_version": "0.12.1+abc", "stale_build": False, "hash_version": 1, "lang": "ko", "reasons": {},
               "hashes": {"content": "c1", "voice": "v1", "audio": "a1", "presentation_by_output": {"youtube": "p"},
                          "engine": dict(F.ENGINE)}, "outputs": [{"name": "youtube"}]}
        prov = Providers(inspect=lambda ctx: seen.append(ctx["s2v_path"]) or copy.deepcopy(ins),
                         source=lambda c, s: ("src1", ""))
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            cli.main(["next", "v1"], providers=prov, cwd=repo)
        self.assertEqual(seen, ["/opt/s2v"])

    def test_lock_py_reads_machine_json_only(self):
        repo = helpers.make_repo(self.tmp, s2v=None)
        seen = []

        def kind(argv, s2v_path, cwd):
            seen.append(s2v_path)
            return None  # "needs no lock": lock.py stops before taking anything (exit 2)

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = lockcli.main(["run", "--kind", "tts", "--", "s2v", "tts", "a.md"], child_kind=kind, cwd=repo)
        self.assertEqual(code, 2)
        self.assertIn("/std config s2v.path", err.getvalue())
        self.assertEqual(seen, [])  # stopped before reading the child
        machine.write(repo, "/opt/s2v")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(lockcli.main(["run", "--kind", "tts", "--", "s2v", "tts", "a.md"], child_kind=kind,
                                          cwd=repo), 2)
        self.assertEqual(seen, ["/opt/s2v"])


class MachineHarnessCommit(HarnessCase):
    """§3.1 test: a home-style path in machine.json does not stop the harness commit; an old config.json does."""

    def test_home_style_path_passes_the_harness_commit(self):
        machine.write(self.repo, HOME_LIKE)
        self.write(".claude/studio/guides/script.md", "# Script guide\n\n- Short.\n")
        out = self.stage()
        self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
        ok, _ = okfile.read(self.repo)
        self.assertNotIn(".claude/studio/local/machine.json", ok["paths"])
        self.assertEqual(self.commit().returncode, 0)
        self.assertEqual(machine.s2v_path(self.repo), HOME_LIKE)
        self.assertIsNone(self.git("ls-files", "--error-unmatch", machine.REL, check=False).stdout.strip() or None)

    def test_old_config_with_s2v_path_is_refused(self):
        self.config(s2v={"path": "/opt/s2v", "min_version": "0.12.1"})
        out = self.stage()
        self.assertEqual(out.returncode, 1, out.stderr + out.stdout)
        self.assertIn("old format", out.stderr)
        self.assertIn("machine.json", out.stderr)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")
        self.config(s2v={"min_version": "0.12.1"})
        # back to the committed config: nothing to stage, but no old-format refusal either
        self.assertNotIn("old format", self.stage().stderr)
        # an old config already committed (a repository set up before M1a): any harness commit says so
        self.config(s2v={"path": "/opt/s2v", "min_version": "0.12.1"})
        self.git("add", ".claude/studio/config.json")
        self.git("commit", "-q", "--no-verify", "-m", "old format (outside any session)")
        self.write(".claude/studio/guides/script.md", "# g\n")
        out = self.stage()
        self.assertEqual(out.returncode, 1, out.stderr + out.stdout)
        self.assertIn("old format", out.stderr)

    def test_make_harness_writes_machine_json(self):
        self.assertEqual(machine.s2v_path(self.repo), "/nonexistent/script2video")
        with open(os.path.join(self.repo, ".claude", "studio", "config.json")) as f:
            self.assertNotIn("path", json.load(f)["s2v"])


# ---------------------------------------------------------------- §3.1 N8b: s2v by form, with or without machine.json

class S2vRecognition(JudgeCase):
    def run_bash(self, cmd):
        return self.bash(cmd), None

    def test_without_machine_json(self):
        os.remove(machine.path(self.repo))
        deny, _ = self.run_bash("S2V_TTS_PORT=1 node /x/packages/cli/dist/main.js tts a.md")
        self.assertIsNotNone(deny, "a lock-bypassing variable on an s2v-shaped call")
        self.assertEqual(deny.rule, self.run_bash("S2V_TTS_PORT=1 s2v tts a.md")[0].rule)
        deny, _ = self.run_bash("node /x/packages/cli/dist/main.js character approve a")
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, "G-APPROVAL")  # an approval command (actors: M3b)
        deny, _ = self.run_bash("tsx /x/packages/cli/src/main.ts character approve a")
        self.assertEqual(deny and deny.rule, "G-APPROVAL")
        # another main.js is not s2v
        deny, _ = self.run_bash("S2V_TTS_PORT=1 node /x/app/main.js tts a.md")
        self.assertIsNone(deny, deny and deny.message())
        deny, _ = self.run_bash("node /x/app/main.js character approve a")
        self.assertIsNone(deny, deny and deny.message())

    def test_machine_json_is_protected(self):
        # choosing which program runs as s2v is the person's (/std config s2v.path with a `설정` answer, M1c)
        p = os.path.join(self.repo, machine.REL)
        for tool, ti in (("Write", {"file_path": p, "content": "{}"}),
                         ("Edit", {"file_path": p, "old_string": "a", "new_string": "b"})):
            deny = self.decide(tool, ti)
            self.assertEqual(deny and deny.rule, "G-PROT", tool)
        for cmd in ("echo '{}' > .claude/studio/local/machine.json", "rm .claude/studio/local/machine.json",
                    "cp /tmp/x.json .claude/studio/local/machine.json"):
            deny, _ = self.run_bash(cmd)
            self.assertIsNotNone(deny, cmd)
        self.assertIsNone(self.run_bash("cat .claude/studio/local/machine.json")[0])

    def test_with_machine_json_the_path_is_recognized(self):
        p = os.path.join(self.tmp, "s2v-here")
        os.makedirs(os.path.join(p, "packages", "cli", "dist"))
        with open(os.path.join(p, "packages", "cli", "dist", "main.js"), "w") as f:
            f.write("// fake\n")
        machine.write(self.repo, p)
        deny, _ = self.run_bash("S2V_TTS_PORT=1 node %s/packages/cli/dist/main.js tts a.md" % p)
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, self.run_bash("S2V_TTS_PORT=1 s2v tts a.md")[0].rule)
        deny, _ = self.run_bash("node %s/packages/cli/dist/main.js character approve a" % p)
        self.assertEqual(deny and deny.rule, "G-APPROVAL")


# ---------------------------------------------------------------- §3.2 labels and hash12

class Labels(StudioTestCase):
    def test_generate_and_parse(self):
        cases = [(labels.approve("v1", H), "approve", {"video": "v1", "h12": H}),
                 (labels.reject("v1", H), "reject", {"video": "v1", "h12": H}),
                 (labels.repin("v1", H), "repin", {"video": "v1", "h12": H}),
                 (labels.exclude("v1", H), "exclude", {"video": "v1", "h12": H}),
                 (labels.unlock("v1", "ko", "lock"), "unlock", {"video": "v1", "lang": "ko", "held": "lock"}),
                 (labels.credit("v1", H), "credit", {"video": "v1", "h12": H}),
                 (labels.abandon("v1", "ko"), "abandon", {"video": "v1", "lang": "ko"}),
                 (labels.overlay(H), "overlay", {"sha12": H}), (labels.setting(H), "setting", {"h12": H}),
                 (labels.update(H), "update", {"h12": H}), (labels.commit(H), "commit", {"tree12": H})]
        words = [l.split(" ")[0] for l, _k, _f in cases]
        self.assertEqual(words, ["승인", "거부", "재고정", "제외", "해제", "출처", "중단", "사내설정", "설정", "갱신", "커밋"])
        for label, kind, fields in cases:
            self.assertEqual(labels.parse(label), (kind, fields), label)
        self.assertEqual(labels.commit(H), okfile.LABEL % H)
        for bad in ("승인 %s" % H, "승인 v1 %s x" % H, "승인 v1  %s" % H, "승인 v1 3F2A9C0D1E4B", " 승인 v1 %s" % H,
                    "승인 v/1 %s" % H, "OK v1 %s" % H, "설정 v1 %s" % H, None):
            with self.assertRaises(labels.NoLabel, msg=bad):
                labels.parse(bad)

    def test_expected_needs_the_video(self):
        repo = helpers.make_repo(self.tmp)
        with self.assertRaises(labels.NoLabel) as e:
            labels.expected(["approve", "v1", "1", "--expect", H], repo, "studio")
        self.assertIn("v1", str(e.exception))
        video_state(repo, "v1")
        self.assertEqual(labels.expected(["approve", "v1", "1", "--expect", H], repo, "studio"),
                         ("승인 v1 %s" % H, H, "v1"))
        self.assertEqual(labels.expected(["reject-source-diff", "v1", "--expect", H], repo, "studio"),
                         ("거부 v1 %s" % H, H, "v1"))
        self.assertEqual(labels.expected(["unlock", "v1", "--expect", "lock"], repo, "studio"),
                         ("해제 v1 ko lock", None, "v1"))
        # M1b: abandon and overlay have labels now (test_m1b.Labels)
        self.assertEqual(labels.expected(["abandon", "v1"], repo, "studio"), ("중단 v1 ko", None, "v1"))
        for cmd, when in (("credit", "M1g"), ("move", "not part of M1")):
            with self.assertRaises(labels.NoLabel) as e:
                labels.expected([cmd, "v1", "--expect", H], repo, "studio")
            self.assertIn(when, str(e.exception))

    def test_hash12_of_two_videos_with_the_same_content_differ(self):
        a, b = F.state(), F.state()
        b["video"] = "v2"
        rec = {"-": {"hash": "same-shown-hash"}}
        h1 = shown.hash12(a, "ko", "1", recorded=rec)
        h2 = shown.hash12(b, "ko", "1", recorded=rec)
        self.assertNotEqual(h1, h2)
        self.assertNotEqual(h1, shown.hash12(a, "ko", "2", recorded=rec))  # the gate is in it
        c = F.state(langs=("ko", "en"))
        self.assertNotEqual(shown.hash12(c, "ko", "1", recorded=rec), shown.hash12(c, "en", "1", recorded=rec))
        from stdo.state.hashes import hash_of
        self.assertEqual(h1, hash_of({"video": "v1", "lang": "ko", "gate": "1",
                                      "shown": [["-", "same-shown-hash"]]})[:12])


class TwoVideos(ApproveCase):
    """state.py: v1's answer never approves v2, even when both have the same content (and so the same shown hash)."""

    def setUp(self):
        super().setUp()
        self.v2 = os.path.join(self.repo, "studio", "videos", "v2")
        os.makedirs(self.v2)
        st = self.state()
        st2 = F.state(outputs=self.outputs, platforms=self.platforms)
        st2["video"] = "v2"
        st2["brief"]["core"] = st["brief"]["core"]
        store.create(self.v2, st2)
        with open(os.path.join(self.v2, "script.ko.md"), "w") as f:
            f.write("# script\n")
        d = os.path.join(self.v2, "work", "ko")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "claims-map.json"), "w") as f:
            json.dump({"excerpts": ["The cat sat on the mat."]}, f)

    def test_v1_answer_for_v2(self):
        for vid in ("v1", "v2"):
            for stg in ("script", "verify"):
                self.assertEqual(self.cli("stage-done", vid, stg), 0, self.last_err)
        self.assertEqual(self.cli("shown", "v1", "1"), 0, self.last_err)
        h1 = self.hash12_of()
        self.assertEqual(self.cli("shown", "v2", "1"), 0, self.last_err)
        h2 = self.hash12_of()
        self.assertNotEqual(h1, h2)
        s1 = self.state()["langs"]["ko"]["shown"]["1"]["-"]["hash"]
        s2 = store.read_state(self.v2)["langs"]["ko"]["shown"]["1"]["-"]["hash"]
        self.assertEqual(s1, s2)  # same content: same shown hash, different labels
        argv = ["approve", "v2", "1", "--expect", h2]
        self.pend(argv, labels.approve("v1", h2))  # v1's label with v2's hash
        self.assertEqual(self.cli(*argv), 6)
        self.assertIn("v2", self.last_err)
        self.pend(argv, labels.approve("v2", h2))
        self.assertEqual(self.cli(*argv), 0, self.last_err)


class GuardVideoInQuestion(JudgeCase):
    def setUp(self):
        super().setUp()
        self.tpath = TR.transcript_path(self.env)
        for v in ("v1", "v2", "v10"):
            video_state(self.repo, v)

    def run_cmd(self, cmd, t):
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": t.prompt}
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def approve(self, vid):
        return "python3 .claude/studio/scripts/state.py approve %s 1 --expect %s" % (vid, H)

    def test_video_label_and_brackets(self):
        t = TR.approval_turn(TR.T(), labels.approve("v1", H), qtext="[v1] ① 대본 · hash %s" % H)
        t.write(self.tpath)
        deny, ctx = self.run_cmd(self.approve("v1"), t)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)
        # v1's answer for v2: the label differs
        deny, _ = self.run_cmd(self.approve("v2"), t)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("승인 v2 %s" % H, deny.message())
        # a question that shows [v1] answered with v10's label: refused (brackets are literal)
        t = TR.approval_turn(TR.T(), labels.approve("v10", H), qtext="[v1] ① 대본 · hash %s" % H)
        t.write(self.tpath)
        deny, _ = self.run_cmd(self.approve("v10"), t)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("[<video>]", deny.message())
        # the video without brackets is not enough either
        t = TR.approval_turn(TR.T(), labels.approve("v1", H), qtext="v1 ① 대본 · hash %s" % H)
        t.write(self.tpath)
        self.assertEqual(self.run_cmd(self.approve("v1"), t)[0].rule, "G-EVIDENCE")
        # unlock names the video too
        t = TR.approval_turn(TR.T(), labels.unlock("v1", "ko", "lock"), qtext="v1 ko 잠금을 풀까요?")
        t.write(self.tpath)
        deny, _ = self.run_cmd("python3 .claude/studio/scripts/state.py unlock v1 --expect lock", t)
        self.assertEqual(deny.rule, "G-EVIDENCE")

    def test_choose_unit(self):
        t = TR.approval_turn(TR.T(), labels.approve("v10", H), qtext="[v10] q %s" % H)
        t.write(self.tpath)
        ans = transcript.find({"session_id": "sess-1", "transcript_path": self.tpath, "tool_use_id": "toolu_cmd1",
                               "prompt_id": t.prompt}, self.env)
        self.assertEqual(transcript.choose(ans, labels.approve("v10", H), H, video="v10")[0], 0)
        with self.assertRaises(transcript.NoEvidence) as e:
            transcript.choose(ans, labels.approve("v10", H), H, video="v1")
        self.assertEqual(e.exception.code, "video-not-shown")


# ---------------------------------------------------------------- §3.2 the used-answer record in the common dir

class SharedRecord(JudgeCase):
    def setUp(self):
        super().setUp()
        self.tpath = TR.transcript_path(self.env)
        video_state(self.repo, "v1")
        self.wt = os.path.join(self.tmp, "worktree-b")
        helpers.git(self.repo, "worktree", "add", "-q", "--detach", self.wt)
        machine.write(self.wt, "/abs/script2video")
        video_state(self.wt, "v1")  # video states are per worktree (ignored work/)

    def test_paths_are_shared(self):
        self.assertEqual(paths.consumed_log(self.repo), paths.consumed_log(self.wt))
        self.assertEqual(paths.consumed_lock(self.repo), paths.consumed_lock(self.wt))
        common = os.path.realpath(paths.common_dir(self.repo))
        self.assertEqual(os.path.realpath(os.path.dirname(paths.consumed_log(self.wt))), os.path.join(common, "studio"))
        self.assertEqual(evidence.consumed_path(self.wt), paths.consumed_log(self.repo))

    def test_answer_used_in_one_worktree_is_refused_in_another(self):
        t = TR.approval_turn(TR.T(), labels.approve("v1", H), qtext="[v1] ① 대본 · hash %s" % H)
        t.write(self.tpath)
        cmd = "python3 .claude/studio/scripts/state.py approve v1 1 --expect %s" % H
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.wt, "session_id": "sess-1",
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": t.prompt}
        deny, ctx = judge.decide(hook, self.env, snapshot_loader=self.loader)
        self.assertIsNone(deny, deny and deny.message())
        # the answer is used in worktree A (state.py records it in the common dir)
        evidence.consume(self.repo, {"session_id": "sess-1", "tool_use_id": "toolu_ask1", "question_index": 0},
                         "v1", "approve")
        deny, _ = judge.decide(hook, self.env, snapshot_loader=self.loader)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("used already", deny.message())
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "studio", "local",
                                                     "consumed-answers.jsonl")))


class SharedRecordCommit(CommitCase):
    """`커밋 <tree12>`: the guard and the pre-commit hook read the same record; the hook records the answer used."""

    def setUp(self):
        super().setUp()
        self.tpath = TR.transcript_path(self.env, SID)

    def stage(self):
        self.ready()
        self.guard_ran()
        out = self.cc("--stage", "test", "v1", env=self.claude_env())
        self.assertEqual(out.returncode, 0, out.stderr)
        return okfile.read(self.repo)[0]

    def gate(self, t):
        hook = {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "studio: v1"'}, "cwd": self.repo,
                "session_id": SID, "transcript_path": self.tpath, "permission_mode": "default",
                "tool_use_id": "toolu_cmd1", "prompt_id": t.prompt}
        return judge.decide(hook, self.env, snapshot_loader=lambda e: (None, ["snapshot-none"]))

    def test_used_in_another_worktree(self):
        ok = self.stage()
        t = TR.approval_turn(TR.T(session_id=SID), ok["label"], qtext="커밋할까요?\n%s" % ok["summary"])
        t.write(self.tpath)
        wt = os.path.join(self.tmp, "worktree-b")
        helpers.git(self.repo, "worktree", "add", "-q", "--detach", wt)
        evidence.consume(wt, {"session_id": SID, "tool_use_id": "toolu_ask1", "question_index": 0}, None,
                         "setting")  # e.g. the same answer was used for another command in worktree B
        deny, _ = self.gate(t)
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("used already", deny.message())

    def test_hook_records_and_refuses_reuse(self):
        ok = self.stage()
        t = TR.approval_turn(TR.T(session_id=SID), ok["label"], qtext="커밋할까요?\n%s" % ok["summary"])
        t.write(self.tpath)
        deny, ctx = self.gate(t)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)
        ap = okfile.read(self.repo)[0]["approval"]
        key = (ap["session_id"], ap["tool_use_id"], ap["question_index"])
        # the record already holds the key (another commit used it): the hook refuses
        log = paths.consumed_log(self.repo)
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w") as f:
            f.write(json.dumps({"session_id": key[0], "tool_use_id": key[1], "question_index": key[2]}) + "\n")
        out = self.commit("studio: v1", env=self.claude_env())
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("used already", out.stderr)
        os.remove(log)
        out = self.commit("studio: v1", env=self.claude_env())
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(key, evidence.consumed_keys(self.repo, log=log))
        with open(log) as f:
            self.assertEqual(len(f.readlines()), 1)

    def test_no_record_outside_a_session(self):
        self.stage()
        self.guard_approved()
        # a person at a terminal: the hook checks no answer, so it records none
        out = self.commit("studio: v1", env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(os.path.exists(paths.consumed_log(self.repo)))


class MeasuredRelabeled(StudioTestCase):
    """§3.3: the measured 2.1.304 excerpts, re-made with the new labels, still give the same answers — and the
    video check holds on them."""

    def setUp(self):
        super().setUp()
        self.env = dict(os.environ)

    def load(self, lines, call, prompt):
        out = []
        for d in lines:
            out.append(d)
            c = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
            if d.get("type") == "assistant" and isinstance(c, list) and any(b.get("id") == call for b in c):
                break
        sid = [d for d in out if d.get("sessionId")][0]["sessionId"]
        path = TR.transcript_path(self.env, sid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            for d in out:
                f.write(json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n")
        res = [d for d in out if isinstance(d.get("toolUseResult"), dict)]
        now = transcript._epoch(res[-1]["timestamp"]) + 5 if res else None
        return transcript.find({"session_id": sid, "prompt_id": prompt, "tool_use_id": call, "transcript_path": path},
                               self.env, now=now)

    def test_ask_one(self):
        call, prompt = "toolu_01PdQhQk2PG2hXdSwsGiBmeS", "017d1537-36d1-4f34-a650-a531d920c9bc"
        a = self.load(TR.relabeled("ask-one", "v1"), call, prompt)
        i, text, _n = transcript.choose(a, "승인 v1 abc123def456", None, video="v1")
        self.assertEqual((i, text, a.tool_use_id), (0, "[v1] 이 결과를 승인할까?", "toolu_016zN3dWZhn45yHQP8z8YHKV"))
        with self.assertRaises(transcript.NoEvidence) as e:
            transcript.choose(a, "승인 v1 abc123def456", None, video="v10")
        self.assertEqual(e.exception.code, "video-not-shown")
        # the recorded excerpt (old label, no [v1]) is no approval in the new form
        a = self.load(TR.fixture_lines("ask-one"), call, prompt)
        with self.assertRaises(transcript.NoEvidence) as e:
            transcript.choose(a, "승인 v1 abc123def456", None, video="v1")
        self.assertEqual(e.exception.code, "label-not-chosen")

    def test_ask_then_bash_late(self):
        lines = TR.relabeled("ask-then-bash-late", "v2")
        call, prompt = "toolu_01S6TLSnog4DSeRjvL515tQ3", "664441d5-ce43-4267-a383-b0f2c69eb2d7"
        for upto in (11, len(lines)):
            a = self.load(lines[:upto], call, prompt)
            i, text, _n = transcript.choose(a, "승인 v2 c26611707a0e", "c26611707a0e", video="v2")
            self.assertEqual((i, a.tool_use_id), (0, "toolu_01Y6w5y1X1jC7bmUgaNo2vX5"))
            self.assertTrue(text.startswith("[v2] "))

    def test_other_fixtures_unchanged_in_meaning(self):
        call, prompt = "toolu_01FjYp2cMyxcvYC3FoWN87rB", "c5efd994-a5ff-4466-a713-eac0dc317a29"
        a = self.load(TR.relabeled("ask-four-other", "v1"), call, prompt)
        self.assertEqual(transcript.choose(a, "B")[0], 1)
        with self.assertRaises(transcript.NoEvidence) as e:
            transcript.choose(a, "A")
        self.assertEqual(e.exception.code, "ambiguous")
        with self.assertRaises(transcript.NoEvidence) as e:
            self.load(TR.relabeled("ask-esc", "v1"), "toolu_01QZaz73LgCFxApp8jNmmuQo",
                      "8b7178dc-09fb-4a3d-bd32-f0d63d306350")
        self.assertEqual(e.exception.code, "no-question")


# ---------------------------------------------------------------- review U1: a link in place of local/

def link_local(repo, target):
    """A fresh worktree has no local/: put a link there (what the review's probe did)."""
    import shutil
    local = os.path.join(repo, ".claude", "studio", "local")
    if os.path.lexists(local):
        shutil.rmtree(local) if not os.path.islink(local) else os.remove(local)
    os.makedirs(target, exist_ok=True)
    os.symlink(target, local)
    with open(os.path.join(target, "machine.json"), "w") as f:
        json.dump({"schema": 1, "s2v": {"path": "/opt/forged-s2v"}}, f)
    return local


class LocalLinkConsumers(StudioTestCase):
    def setUp(self):
        super().setUp()
        store.enable_writes()
        self.repo = helpers.make_repo(self.tmp)
        self.vdir = os.path.join(self.repo, "studio", "videos", "v1")
        os.makedirs(self.vdir)
        store.create(self.vdir, F.state())
        self.evil = os.path.join(self.tmp, "evil")
        link_local(self.repo, self.evil)

    def test_every_reader_and_writer_refuses(self):
        self.assertIn("symbolic link", paths.local_problem(self.repo))
        with self.assertRaises(paths.UnsafeLocal):
            machine.s2v_path(self.repo)
        with self.assertRaises(paths.UnsafeLocal):
            machine.write(self.repo, "/opt/s2v")
        # pending approval
        with open(os.path.join(self.evil, "pending-approval.json"), "w") as f:
            json.dump({"schema": 1}, f)
        with self.assertRaises(evidence.Missing) as e:
            evidence.check(self.repo, ["approve", "v1", "1", "--expect", H], "승인 v1 %s" % H, False)
        self.assertIn("symbolic link", str(e.exception))
        self.assertFalse(evidence.remove_pending(self.repo))
        self.assertTrue(os.path.exists(os.path.join(self.evil, "pending-approval.json")))
        # commit-ok
        ok, why = okfile.read(self.repo)
        self.assertIsNone(ok)
        self.assertIn("symbolic link", why)
        with self.assertRaises(OSError):
            okfile.write(self.repo, {"tree": "0" * 40, "paths": []})
        # the guard's pending file and its ran-record
        from stdo.guard import approve, ranlog

        class RI(object):
            worktree = self.repo
            common_dir = None
        with self.assertRaises(OSError):
            approve.write_pending(RI(), {"schema": 1, "forged": "yes"})
        with open(os.path.join(self.evil, "pending-approval.json")) as f:
            self.assertNotIn("forged", f.read())  # refused before writing, not only noticed after
        self.assertFalse(ranlog.record(self.repo, "s1", True))
        self.assertFalse(os.path.exists(os.path.join(self.evil, "guard-ran.json")))

    def test_state_and_lock_exit_2_and_status_reports(self):
        err = io.StringIO()
        for argv in (["next", "v1"], ["approve", "v1", "1", "--expect", H]):
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(argv, cwd=self.repo), 2, argv)
        self.assertIn("symbolic link", err.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["status", "--json"], cwd=self.repo), 0)
        self.assertTrue(any("symbolic link" in w for w in json.loads(out.getvalue())["warnings"]))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(lockcli.main(["run", "--kind", "tts", "--", "s2v", "tts", "a.md"],
                                          child_kind=lambda a, p, c: "tts", cwd=self.repo), 2)
        self.assertIn("symbolic link", err.getvalue())

    def test_studio_root_local_link(self):
        os.remove(os.path.join(self.repo, ".claude", "studio", "local"))
        os.symlink(self.evil, os.path.join(self.repo, "studio", "local"))
        self.assertIn("studio/local", paths.local_problem(self.repo, "studio"))
        self.assertIsNone(paths.local_problem(self.repo))  # .claude/studio/local itself is absent: fine
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["next", "v1"], cwd=self.repo), 2)


class LocalLinkCommit(HarnessCase):
    def test_stage_and_hook_refuse(self):
        self.write(".claude/studio/guides/script.md", "# g\n")
        link_local(self.repo, os.path.join(self.tmp, "evil"))
        out = self.stage()
        self.assertEqual(out.returncode, 1, out.stderr + out.stdout)
        self.assertIn("symbolic link", out.stderr)
        self.assertNotIn("Traceback", out.stderr)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")  # refused before staging
        self.git("add", ".claude/studio/guides/script.md")
        out = self.commit()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("symbolic link", out.stderr)


class LocalLinkVideoCommit(CommitCase):
    LINK = "does not read or write this machine's files through a link"

    def test_stage_and_hook_say_why(self):
        self.ready()
        link_local(self.repo, os.path.join(self.tmp, "evil"))
        out = self.cc("--stage", "test", "v1")
        self.assertEqual(out.returncode, 1, out.stderr + out.stdout)
        self.assertIn(self.LINK, out.stderr)
        self.git("add", "studio/videos/v1/script.ko.md", check=False)
        out = self.commit("studio: v1")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn(self.LINK, out.stderr)


class LocalLinkGuard(JudgeCase):
    def setUp(self):
        super().setUp()
        import shutil
        shutil.rmtree(os.path.join(self.repo, ".claude", "studio", "local"))  # a fresh worktree
        self.evil = os.path.join(self.tmp, "evil")
        os.makedirs(self.evil)

    def test_creating_local_other_than_mkdir_is_denied(self):
        for cmd in ("ln -s %s .claude/studio/local" % self.evil, "ln -sfn %s .claude/studio/local" % self.evil,
                    "mv %s .claude/studio/local" % self.evil, "cp -R %s .claude/studio/local" % self.evil,
                    "cp -r %s/ .claude/studio/local" % self.evil, "rsync -a %s/ .claude/studio/local" % self.evil,
                    "ln -s %s studio/local" % self.evil, "mv %s studio/local" % self.evil,
                    "ln -s %s studio/videos/v9" % self.evil):
            d = self.bash(cmd)
            self.assertIsNotNone(d, cmd)
            self.assertEqual(d.rule, "G-PROT", "%s: %s" % (cmd, d.message()))
        for cmd in ("mkdir -p .claude/studio/local", "mkdir .claude/studio/local", "ln -s %s src/lib" % self.evil,
                    "cp -R %s src/copied" % self.evil):
            d = self.bash(cmd)
            self.assertIsNone(d, "%s: %s" % (cmd, d and d.message()))

    def test_copy_into_an_existing_local_folder_is_not_creation(self):
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"))
        self.assertIsNone(self.bash("cp src/a.ts .claude/studio/local/"))


# ---------------------------------------------------------------- review U2: redirected git folders

class GitRedirect(JudgeCase):
    def test_guard_denies_git_variables_on_studio_scripts(self):
        video_state(self.repo, "v1")
        for pre in ("GIT_COMMON_DIR=/tmp/x ", "GIT_DIR=/tmp/x/.git ", "env GIT_COMMON_DIR=/tmp/x ",
                    "GIT_WORK_TREE=/tmp/x ", "GIT_INDEX_FILE=/tmp/i "):
            for cmd in ("python3 .claude/studio/scripts/state.py approve v1 1 --expect %s" % H,
                        "python3 .claude/studio/scripts/state.py next v1",
                        "python3 .claude/studio/scripts/check_commit.py --stage harness"):
                d = self.bash(pre + cmd)
                self.assertIsNotNone(d, pre + cmd)
                self.assertEqual(d.rule, "G-ENV", d.message())
        d = self.bash("export GIT_COMMON_DIR=/tmp/x && python3 .claude/studio/scripts/state.py next v1")
        self.assertEqual(d and d.rule, "G-ENV")
        self.assertIsNone(self.bash("python3 .claude/studio/scripts/state.py next v1"))

    def test_paths_ignore_inherited_git_variables(self):
        import shutil
        real = paths.consumed_log(self.repo)
        copy_git = os.path.join(self.tmp, "copied-git")
        shutil.copytree(os.path.join(self.repo, ".git"), copy_git)
        old = dict(os.environ)
        try:
            os.environ["GIT_COMMON_DIR"] = copy_git
            os.environ["GIT_DIR"] = copy_git
            self.assertEqual(paths.consumed_log(self.repo), real)
            self.assertEqual(paths.common_dir(self.repo), paths.common_dir(self.repo))
            self.assertNotIn("copied-git", paths.consumed_log(self.repo))
        finally:
            os.environ.clear()
            os.environ.update(old)


# ---------------------------------------------------------------- review U3: a copied video folder

class CopiedVideo(ApproveCase):
    def test_copy_is_not_the_original(self):
        import shutil
        for stg in ("script", "verify"):
            self.assertEqual(self.cli("stage-done", "v1", stg), 0, self.last_err)
        self.assertEqual(self.cli("shown", "v1", "1"), 0, self.last_err)
        h = self.hash12_of()
        shutil.copytree(self.vdir, os.path.join(self.repo, "studio", "videos", "v1b"))
        with self.assertRaises(labels.NoLabel) as e:
            labels.expected(["approve", "v1b", "1", "--expect", h], self.repo, "studio")
        self.assertIn("folder/state mismatch", str(e.exception))
        with self.assertRaises(Exception) as e:
            store.read_state(os.path.join(self.repo, "studio", "videos", "v1b"))
        self.assertEqual(getattr(e.exception, "code", None), 2)
        argv = ["approve", "v1b", "1", "--expect", h]
        self.pend(argv, labels.approve("v1", h))
        self.assertEqual(self.cli(*argv), 2)
        self.assertIn("folder/state mismatch", self.last_err)


# ---------------------------------------------------------------- review U4: the staged config blob

class OldConfigStaged(HarnessCase):
    def test_staged_old_config_with_reverted_work_tree(self):
        p = os.path.join(self.repo, ".claude", "studio", "config.json")
        with open(p) as f:
            good = f.read()
        self.config(s2v={"path": "/opt/s2v", "min_version": "0.12.1"})
        self.git("add", ".claude/studio/config.json")
        with open(p, "w") as f:
            f.write(good)  # the work tree says the new format, the index the old one
        out = self.stage()
        self.assertEqual(out.returncode, 1, out.stderr + out.stdout)  # --stage refuses the mixed state anyway
        # the hook's own check reads the staged blob (whatever the work tree says)
        from stdo.commit import checks, gitx, kinds
        ctx = checks.Ctx(gitx.Git(self.repo, self.env), self.env, kinds.registry(self.env))
        msgs = [x.message for x in ctx.kinds["harness"].staged_problems(ctx, [".claude/studio/config.json"])]
        self.assertTrue(any("old format" in m for m in msgs), msgs)


# ---------------------------------------------------------------- review U7: an unreadable record

class UnreadableRecord(JudgeCase):
    def test_closed_with_a_message(self):
        from stdo.guard import approve
        video_state(self.repo, "v1")
        tpath = TR.transcript_path(self.env)
        t = TR.approval_turn(TR.T(), labels.approve("v1", H), qtext="[v1] ① · hash %s" % H)
        t.write(tpath)
        log = paths.consumed_log(self.repo)
        os.makedirs(log)  # a folder where the record should be: unreadable
        hook = {"tool_name": "Bash", "tool_input": {"command": "python3 .claude/studio/scripts/state.py approve v1 1 "
                                                              "--expect %s" % H}, "cwd": self.repo,
                "session_id": "sess-1", "transcript_path": tpath, "permission_mode": "default",
                "tool_use_id": "toolu_cmd1", "prompt_id": t.prompt}
        deny, _ = judge.decide(hook, self.env, snapshot_loader=self.loader)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("record of used answers cannot be read", deny.message())

        class RI(object):
            worktree = self.repo
            common_dir = None
        with self.assertRaises(transcript.NoEvidence) as e:
            approve.consumed(RI(), ("a", "b", 0))
        self.assertEqual(e.exception.code, "record-unreadable")


# ---------------------------------------------------------------- re-review V1: other writers of protected files

class OtherWriters(JudgeCase):
    def setUp(self):
        super().setUp()
        for t in ("tar", "gtar", "bsdtar", "unzip", "7z", "ditto", "cpio", "pax", "rsync"):
            if not os.path.exists(os.path.join(self.bin, t)):
                self.exe(t)
        self.out = os.path.join(self.tmp, "outside")
        os.makedirs(self.out)
        os.makedirs(os.path.join(self.repo, ".git", "studio"), exist_ok=True)

    def assertProt(self, cmd):
        d = self.bash(cmd)
        self.assertIsNotNone(d, cmd)
        self.assertEqual(d.rule, "G-PROT", "%s: %s" % (cmd, d.message()))
        return d

    def assertPass(self, cmd):
        d = self.bash(cmd)
        self.assertIsNone(d, "%s: %s" % (cmd, d and d.message()))

    def test_extraction_destination_rule(self):
        os.makedirs(os.path.join(self.repo, "dist"), exist_ok=True)
        for cmd in ("tar -xf a.tar", "tar xf a.tar", "tar -xf a.tar -C .claude/studio",
                    "tar -xf a.tar -C .claude/studio/local", "tar -xf a.tar -C .claude", "tar -xf a.tar -C .claude/agents",
                    "tar -xf a.tar -C studio/videos", "tar -xf a.tar -C .git", "tar -xf a.tar -C .git/studio",
                    "tar --extract -f a.tar", "tar -xf a.tar -C ..", "bsdtar -xf a.tar", "gtar -xf a.tar",
                    "unzip a.zip", "unzip -o a.zip -d studio/x", "ditto -x -k a.zip .", "ditto -xk a.zip studio",
                    "cpio -i --no-absolute-filenames < a.cpio", "cd studio && tar -xf ../a.tar",
                    "tar -xf %s/a.tar -C %s" % (self.out, self.repo)):
            d = self.assertProt(cmd)
            self.assertIn("cannot list beforehand", d.message())
        for cmd in ("tar -xf a.tar -C dist", "tar -xf a.tar -C src", "cd dist && tar -xf ../a.tar", "unzip a.zip -d dist",
                    "unzip -o a.zip -d src", "ditto -x -k a.zip dist", "cd dist && cpio -i --no-absolute-filenames < "
                    "../a.cpio", "tar -xf a.tar -C %s" % self.out, "unzip a.zip -d %s" % self.out,
                    "cd %s && tar -xf a.tar" % self.out, "tar -tf a.tar", "unzip -l a.zip", "7z l a.7z",
                    "tar -cf %s/x.tar src" % self.out):
            self.assertPass(cmd)

    def test_w1_flags_that_leave_the_folder(self):
        for cmd in ("tar -xPf a.tar -C dist", "tar -x -P -f a.tar -C dist", "tar xPf a.tar -C dist",
                    "tar --absolute-names -xf a.tar -C dist", "tar -xf a.tar -C dist --transform=s/a/b/",
                    "gtar -xf a.tar -C dist --xform s/a/b/", "bsdtar -xf a.tar -C dist -s /a/b/", "unzip -: a.zip -d dist",
                    "unzip -o: a.zip -d dist", "cd dist && cpio -i < ../a.cpio", "cd dist && pax -r < ../a.pax",
                    "pax -rw src dist"):
            d = self.assertProt(cmd)
            self.assertIn("leave the folder", d.message())

    def test_weak_extractors(self):
        for t in ("busybox", "jar", "cmake", "bsdcpio", "7za", "7zz"):
            if not os.path.exists(os.path.join(self.bin, t)):
                self.exe(t)
        for cmd in ("7z x a.7z -odist", "7za x a.7z", "7zz e a.7z", "7z x a.7z -o%s" % self.out, "busybox tar -xf a.tar",
                    "busybox unzip a.zip -d dist", "jar xf a.jar", "cd dist && jar -xf ../a.jar",
                    "cmake -E tar xf a.tar", "python3 -m tarfile -e a.tar dist", "python3 -m zipfile -e a.zip dist",
                    "bsdcpio -i < a.cpio"):
            d = self.assertProt(cmd)
            self.assertIn("not an extractor Studio has checked", d.message())
        for cmd in ("7z l a.7z", "python3 -m tarfile -l a.tar", "jar tf a.jar", "cmake -E tar tf a.tar",
                    "busybox ls"):
            self.assertPass(cmd)

    def test_x1_scripts_and_text_built_at_run_time(self):
        os.makedirs(os.path.join(self.repo, "dist"), exist_ok=True)
        for t in ("script", "xargs", "env"):
            if not os.path.exists(os.path.join(self.bin, t)):
                self.exe(t)
        files = {"s.sh": "tar -xf a.tar\n", "ok.sh": "tar -xf a.tar -C dist\nls dist\n", "nest.sh": ". ./s.sh\n",
                 "w4.sh": "tar -xf a.tar -C dist\nmv dist/x src/\n", "cp.sh": "cp -R %s/plain .claude\n" % self.out,
                 "d1.sh": ". ./d2.sh\n", "d2.sh": ". ./d3.sh\n", "d3.sh": ". ./d4.sh\n", "d4.sh": "ls\n"}
        for n, body in files.items():
            with open(os.path.join(self.repo, n), "w") as f:
                f.write(body)
        for cmd in ("bash s.sh", "sh ./s.sh", ". s.sh", "source s.sh", "bash < s.sh", "cat s.sh | bash",
                    "bash nest.sh", "bash w4.sh", "bash cp.sh", "bash missing.sh",
                    "xargs -I{} sh -c {} < s.sh", 'sh -c "$(cat s.sh)"', 'eval "$(cat s.sh)"', "eval \"$X\"",
                    "X='tar -xf a.tar'; $X", "$(echo tar) -xf a.tar", "`echo tar` -xf a.tar",
                    "env -S 'tar -xf a.tar'", "env --split-string='tar -xf a.tar'", "script -q /dev/null tar -xf a.tar",
                    "script -c 'tar -xf a.tar' /dev/null", "script -q /dev/null bash s.sh",
                    "bash d1.sh"):  # deeper than three levels: not followed, refused
            d = self.bash(cmd)
            self.assertIsNotNone(d, cmd)
            self.assertIn(d.rule, ("G-PROT", "G-OPAQUE", "G-UNKNOWN"), "%s: %s" % (cmd, d.message()))
        for cmd in ("bash ok.sh", ". ./ok.sh", "eval 'ls dist'", "env -S 'tar -xf a.tar -C dist'",
                    "script -q /dev/null tar -xf a.tar -C dist", "script -q /dev/null", "sh -c 'ls'"):
            self.assertPass(cmd)

    def test_w2_shell_strings(self):
        os.makedirs(os.path.join(self.repo, "dist"), exist_ok=True)
        for cmd in ("sh -c 'tar -xf a.tar'", "bash -c 'tar -xf a.tar -C .claude/studio'",
                    "zsh -c 'cd studio && unzip ../a.zip'", "sh -c \"bash -c 'tar -xf a.tar'\"",
                    "bash -c 'cp -R %s/evil/. .claude/studio'" % self.out,
                    "sh -c 'tar -xf a.tar -C dist && mv dist/x studio/'"):
            d = self.assertProt(cmd)
        self.assertPass("sh -c 'tar -xf a.tar -C dist'")

    def test_w3_recursive_copies(self):
        src = os.path.join(self.out, "tree")
        os.makedirs(os.path.join(src, "studio", "videos", "v", "work"))
        with open(os.path.join(src, "studio", "videos", "v", "work", "state.json"), "w") as f:
            f.write("{}")
        harmless = os.path.join(self.out, "plain")
        os.makedirs(os.path.join(harmless, "docs"))
        with open(os.path.join(harmless, "docs", "x.md"), "w") as f:
            f.write("x")
        local = os.path.join(self.out, "loc")
        os.makedirs(os.path.join(local, ".claude", "studio", "local"))
        with open(os.path.join(local, ".claude", "studio", "local", "machine.json"), "w") as f:
            f.write("{}")
        linked = os.path.join(self.out, "linked")
        os.makedirs(os.path.join(linked, "studio"))
        os.symlink("/tmp", os.path.join(linked, "studio", "v9"))
        for cmd in ("cp -r %s/. ." % src, "cp -R %s/ ." % src, "cp -a %s/. ." % src, "rsync -a %s/ ." % src,
                    "rsync -r %s/ ." % src, "cp -R %s/. ." % local, "rsync -a %s/ ." % local,
                    "cp -a %s/. ." % linked, "ditto %s ." % src, "cp -R %s/studio ." % src):
            self.assertProt(cmd)
        # X2: the destination rule always — even a harmless tree is not copied into the root or Studio's folders
        for cmd in ("cp -r %s/. ." % harmless, "cp -R %s/ ." % harmless, "rsync -a %s/ ." % harmless,
                    "cp -rT %s/.claude .claude" % local, "cp -R -T %s .claude/studio" % harmless,
                    "gcp --no-target-directory -r %s studio/x" % harmless, "cp -R %s .claude/agents" % harmless):
            self.assertProt(cmd)
        d = self.assertProt("cp -R %s .claude/agents" % harmless)
        self.assertIn("copy the files one by one", d.message())
        for cmd in ("cp -r %s/. dist" % harmless, "cp -R %s dist" % src, "rsync -a %s/ dist/" % src,
                    "cp -rT %s dist/plain" % harmless):
            self.assertPass(cmd)
        self.assertPass("cp -a %s/. dist" % linked)  # a link below dist is not in Studio's folders
        # the walk judges the other destinations entry by entry: Studio's block in a team-shared hook file
        os.makedirs(os.path.join(self.repo, ".husky"), exist_ok=True)
        with open(os.path.join(self.repo, ".husky", "pre-commit"), "w") as f:
            f.write("npm test\n# >>> studio:hook >>>\npython3 x\n# <<< studio:hook <<<\n")
        hk = os.path.join(self.out, "hk")
        os.makedirs(hk)
        with open(os.path.join(hk, "pre-commit"), "w") as f:
            f.write("exit 0\n")
        self.assertProt("cp -R %s/. .husky" % hk)
        self.assertProt("rsync -a %s/ .husky/" % hk)
        self.assertPass("cp -R %s/. dist" % hk)
        # a source the guard cannot walk: the destination rule
        self.assertProt("cp -R %s/missing ." % self.out)
        self.assertProt("rsync -aR %s/ ." % harmless)
        self.assertPass("cp -R %s/missing dist" % self.out)

    def test_w4_a_later_writer_in_the_same_call(self):
        os.makedirs(os.path.join(self.repo, "dist"), exist_ok=True)
        for cmd in ("tar -xf a.tar -C dist && mv dist/x studio/x", "tar -xf a.tar -C dist; cp dist/x src/",
                    "unzip a.zip -d dist && python3 tool.py", "cp -R %s/plain dist && mv dist/plain src/" % self.out,
                    "tar -xf a.tar -C dist && echo x > notes.md"):
            d = self.assertProt(cmd)
            self.assertIn("in the same call", d.message())
            self.assertIn("separate call", d.message())
        for cmd in ("tar -xf a.tar -C dist && ls dist", "tar -xf a.tar -C dist && cat dist/a",
                    "mv a b && tar -xf a.tar -C dist", "tar -xf a.tar -C dist && git status"):
            self.assertPass(cmd)

    def test_hard_link_copies(self):
        self.assertProt("cp -l .claude/studio/local/machine.json %s/h" % self.out)
        self.assertProt("cp --link .claude/studio/local/machine.json %s/h" % self.out)
        self.assertProt("cp -al .git/studio %s/s" % self.out)
        self.assertProt("cp -Rl studio %s/s" % self.out)
        self.assertProt("cp -la studio/videos/v %s/v" % self.out)
        self.assertProt("ln studio/videos/v/work/state.json %s/st" % self.out)
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        self.assertProt("cp -T src/a.ts .claude/studio/local")  # -T: the folder itself is replaced, not copied into
        self.assertPass("cp src/a.ts .claude/studio/local/")
        self.assertPass("cp -l src/a.ts %s/h" % self.out)
        self.assertPass("cp .claude/studio/local/machine.json %s/c" % self.out)  # a copy, not the same file
        self.assertPass("cp -R studio/videos/v %s/v" % self.out)

    def test_new_checkouts_inside_studio_folders(self):
        for cmd in ("git worktree add .claude/studio/local main", "git worktree add -b x studio/local/wt",
                    "git clone %s studio/videos/v9" % self.repo, "git init studio/x", "git init .claude/studio/local",
                    "cd studio && git init", "git -C studio init newrepo"):
            d = self.assertProt(cmd)
            self.assertIn("checkout inside Studio's folders", d.message())
        for cmd in ("git worktree add %s/wt main" % self.out, "git init %s/r" % self.out,
                    "git clone %s %s/c" % (self.repo, self.out)):
            self.assertPass(cmd)

    def test_ln_message(self):
        d = self.assertProt("ln -s %s studio/videos/v9" % self.out)
        self.assertIn("Studio does not follow links under studio/", d.message())
        self.assertIn("script_src", d.message())


# ---------------------------------------------------------------- re-review V2: links and local/ in any commit

class LinksInCommits(CommitCase):
    def blob(self, text):
        return subprocess.run(["git", "-C", self.repo, "hash-object", "-w", "--stdin"], input=text,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_hook_refuses_links_and_local_paths_in_any_commit(self):
        self.write("src/a.txt", "x\n")
        self.git("add", "src/a.txt")
        b = self.blob("/tmp/evil")
        for path in (".claude/studio/local", "studio/local", ".claude/studio/guides/g.md", "studio/videos/v9"):
            self.git("update-index", "--add", "--cacheinfo", "120000,%s,%s" % (b, path))
            out = self.commit("non-Studio change")
            self.assertNotEqual(out.returncode, 0, path)
            self.assertTrue("symbolic link" in out.stderr or "machine-only" in out.stderr, out.stderr)
            self.git("rm", "--cached", "-q", path)
        for path in (".claude/studio/local", "studio/local"):  # a plain file standing in for the folder
            self.git("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (self.blob("{}"), path))
            out = self.commit("non-Studio change")
            self.assertIn("machine-only", out.stderr, path)
            self.git("rm", "--cached", "-q", path)
        self.git("add", "-f", ".claude/studio/local/machine.json")
        out = self.commit("non-Studio change")
        self.assertIn("machine-only", out.stderr)
        self.git("rm", "--cached", "-q", ".claude/studio/local/machine.json")
        self.assertEqual(self.commit("non-Studio change").returncode, 0)

    def test_range_check_reports_a_committed_link(self):
        b = self.blob("/tmp/evil")
        self.git("update-index", "--add", "--cacheinfo", "120000,%s,%s" % (b, "studio/videos/v9"))
        self.git("commit", "-q", "--no-verify", "-m", "a link (outside any session)")
        out = self.cc("--range", "HEAD~1..HEAD")
        self.assertEqual(out.returncode, 1, out.stderr + out.stdout)
        self.assertIn("symbolic link studio/videos/v9", out.stderr)


# ---------------------------------------------------------------- re-review V4 · V5

class ReadLocal(StudioTestCase):
    def test_no_follow_and_recheck(self):
        repo = helpers.make_repo(self.tmp)
        target = os.path.join(self.tmp, "fake.json")
        with open(target, "w") as f:
            json.dump({"schema": 1, "s2v": {"path": "/opt/fake"}}, f)
        os.remove(machine.path(repo))
        os.symlink(target, machine.path(repo))  # the file itself is a link inside a real local/
        with self.assertRaises(paths.UnsafeLocal) as e:
            machine.s2v_path(repo)
        self.assertIn("symbolic link", str(e.exception))  # refused at the open (O_NOFOLLOW), not only after it
        os.remove(machine.path(repo))
        machine.write(repo, "/opt/s2v")
        real_id = paths._local_id
        calls = []

        def swapped(r):
            calls.append(r)
            ident = real_id(r)
            return ident if len(calls) == 1 else (ident[0], ident[1] + 1)  # the folder changed after the open
        paths._local_id = swapped
        try:
            with self.assertRaises(paths.UnsafeLocal) as e:
                machine.s2v_path(repo)
            self.assertIn("retry", str(e.exception))
        finally:
            paths._local_id = real_id
        self.assertEqual(machine.s2v_path(repo), "/opt/s2v")
        self.assertIsNone(paths.read_local(repo, "absent.json"))


class ReportDedupe(StudioTestCase):
    def test_one_line_per_reason(self):
        from stdo.commit import cli as ccli
        from stdo.commit.approvals import Problem
        err = io.StringIO()
        p = Problem(1, "same reason")
        ccli._report("Studio stage", [p, Problem(1, "same reason"), Problem(1, "other")], stream=err)
        self.assertEqual(err.getvalue().count("same reason"), 1)
        self.assertIn("refused (2 problems)", err.getvalue())


class LinksAbove(StudioTestCase):
    """W6: a link standing for `.claude`, `.claude/studio` or `<sr>` itself is one of Studio's links too."""

    def test_links_include_the_folders_above(self):
        from stdo.commit import gitx, spaths
        repo = os.path.join(self.tmp, "r")
        os.makedirs(repo)
        helpers.git(repo, "init", "-q")
        for n in (".claude", "studio", "src"):
            os.symlink("/tmp", os.path.join(repo, n))
        helpers.git(repo, "add", "-A")
        helpers.git(repo, "commit", "-q", "-m", "links")
        cls = spaths.Classifier(["studio"], False)
        g = gitx.Git(repo, dict(os.environ))
        self.assertEqual(cls.links(g, "HEAD", [".claude", "studio", "src"]), [".claude", "studio"])
        self.assertEqual(cls.links(g, None, [".claude", "src"]), [".claude"])
        repo2 = os.path.join(self.tmp, "r2")
        os.makedirs(os.path.join(repo2, ".claude"))
        helpers.git(repo2, "init", "-q")
        os.symlink("/tmp", os.path.join(repo2, ".claude", "studio"))
        helpers.git(repo2, "add", "-A")
        self.assertEqual(cls.links(gitx.Git(repo2, dict(os.environ)), None, [".claude/studio"]), [".claude/studio"])
