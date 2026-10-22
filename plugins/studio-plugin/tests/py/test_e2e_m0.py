"""M0 end to end (m0f-plan v4 §4): the person's answers in the transcript → the real guard.py process → state.py →
check_commit --stage → git commit with the pre-commit hook → git push. Each Bash call runs only when the guard
did not deny it (e2e_runner). s2v is injected (ApproveCase) and git runs in temporary repositories."""

import json
import os
import re
import subprocess

import transcripts as TR
from approve_base import SESSION, ApproveCase
from commit_base import copy_scripts
from e2e_runner import Session, state_py_executor
from harness_base import SID, HarnessCase
from stdo import machine, paths
from stdo.commit import okfile
from stdo.state import backup
from stdo.state.hashes import hash_of

STAGE = "python3 .claude/studio/scripts/check_commit.py --stage harness"


class HarnessE2E(HarnessCase):
    def session(self, guard_env=None, sid=SID, mode="default"):
        return Session(self.repo, guard_env or self.env, self.env, sid, mode=mode)

    def staged_line(self, r):
        self.assertTrue(r.ran and r.code == 0, r)
        m = re.search(r"put this line in the question as it is:\n(.+)\n", r.out)
        self.assertTrue(m, r.out)
        return m.group(1), m.group(1).split(" | ")[0]

    def commit_round(self, s, msg="studio: harness", show_line=True):
        line, label = self.staged_line(s.bash(STAGE))
        q = "이 파일들을 커밋할까요?\n" + (line if show_line else label)
        s.ask(q, [label, "수정해 줘"], label)
        return s.bash('git commit -m "%s"' % msg), line

    def log(self):
        return self.git("log", "--format=%s").stdout.splitlines()

    def test_e1_harness_commit_through_guard_and_hook(self):
        s = self.session()
        self.write(".claude/studio/guides/script.md", "# Script guide\n\n- Keep it short.\n")
        r, line = self.commit_round(s)
        self.assertEqual((r.decision, r.code), ("allow", 0), r)
        self.assertEqual(self.log()[0], "studio: harness")
        ap = okfile.read(self.repo)[0]["approval"]
        self.assertEqual((ap["mode"], ap["summary"], ap["session_id"]), ("human", line, SID))
        with open(os.path.join(self.repo, ".claude", "studio", "local", "guard-ran.json")) as f:
            self.assertIn(SID, json.load(f)["sessions"])

    def test_e1b_scripts_copy_integrity(self):
        s = self.session()
        p = os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "paths.py")
        with open(p, "a") as f:
            f.write("# edited by hand\n")
        r = s.bash(STAGE)
        self.assertEqual(r.decision, "deny", r)  # the guard sees the edited work-tree copy first (review MAJOR-1b)
        self.assertIn("was edited", r.reason)
        out = self.stage()  # a person outside a session: the harness check (H10) refuses it
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("differ from their manifest", out.stderr)
        # the manifest edited too: the copy is no longer the plugin's -> the guard stops Studio commands
        import sys
        sys.path.insert(0, os.path.join(self.repo, ".claude", "studio", "scripts"))
        mp = os.path.join(self.repo, ".claude", "studio", "scripts", "MANIFEST.sha256")
        import hashlib
        with open(mp) as f:
            text = f.read()
        old = [l for l in text.splitlines() if l.endswith("  stdo/paths.py")][0]
        with open(p, "rb") as f:
            new = hashlib.sha256(f.read()).hexdigest() + "  stdo/paths.py"
        with open(mp, "w") as f:
            f.write(text.replace(old, new))
        r = s.bash(STAGE)
        self.assertEqual(r.decision, "deny")
        self.assertIn("G-VERSION", r.reason)
        sys.path.pop(0)

    def test_e5_e6_mixed_and_other_session(self):
        s = self.session()
        self.write("src/a.ts", "a\n")
        self.git("add", "src/a.ts")
        self.write(".claude/studio/guides/script.md", "# g\n")
        r = s.bash(STAGE)
        self.assertEqual(r.code, 1)
        self.assertIn("other changes are already staged", r.err)
        self.git("add", ".claude/studio/guides/script.md")
        out = self.commit(env=self.claude_env())
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("mixes Studio paths", out.stderr)
        self.git("reset", "-q")
        # a Claude session whose guard never ran (another session id): the hook refuses (7)
        r = s.bash(STAGE)
        self.assertEqual(r.code, 0, r)
        out = self.commit(env=self.claude_env("sess-without-guard"))
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("guard has not run", out.stderr)

    def test_e7_protected_keys(self):
        s = self.session()
        self.config(public_domains=["example.com"])
        r, line = self.commit_round(s, show_line=False)  # the question without the summary line
        self.assertEqual(r.decision, "deny")
        self.assertIn("summary", r.reason)
        self.assertIn("보호 키: public_domains", line)
        # a question with a near-miss line (the key list differs) is not enough either
        s.ask("커밋할까요?\n" + line.replace("보호 키: public_domains", "보호 키: 없음"), [line.split(" | ")[0]],
              line.split(" | ")[0])
        r = s.bash('git commit -m "x"')
        self.assertEqual(r.decision, "deny")
        s.ask("커밋할까요?\n" + line, [line.split(" | ")[0]], line.split(" | ")[0])
        r = s.bash('git commit -m "settings"')
        self.assertEqual((r.decision, r.code), ("allow", 0), r)

    def sandbox_env(self):
        e = dict(self.env)
        e["STUDIO_SANDBOX"] = "1"
        with open(os.path.join(e["STUDIO_HOME"], "studio-sandbox.json"), "w") as f:
            json.dump({"sandbox_root": self.tmp}, f)
        return e

    def test_e7c_e11_proxy(self):
        s = self.session(guard_env=self.sandbox_env())
        self.write(".claude/studio/guides/script.md", "# g\n")
        self.staged_line(s.bash(STAGE))
        r = s.bash('git commit -m "proxy harness"')
        self.assertEqual((r.decision, r.code), ("allow", 0), r)
        self.assertEqual(okfile.read(self.repo)[0]["approval"]["mode"], "proxy")
        self.config(visibility={"default": "public"})
        self.staged_line(s.bash(STAGE))
        r = s.bash('git commit -m "proxy settings"')
        self.assertEqual(r.decision, "deny")
        self.assertIn("protected settings", r.reason)

    def test_e8_content_checks(self):
        s = self.session()
        self.write(".claude/studio/guides/script.md", "- internal only\n  scope: internal\n")
        r = s.bash(STAGE)
        self.assertEqual(r.code, 1)
        self.write(".claude/studio/guides/script.md", "run it from /" + "Users/alice/x\n")
        self.assertEqual(s.bash(STAGE).code, 1)

    def remote(self):
        rem = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", rem], check=True, env=self.env)
        self.git("remote", "add", "origin", rem)
        self.git("push", "-q", "-u", "origin", "HEAD")

    def test_e9_e10_push(self):
        self.remote()
        s = self.session()
        self.write(".claude/studio/guides/script.md", "# g\n")
        r, _ = self.commit_round(s)
        self.assertEqual(r.code, 0, r)
        r = s.bash("git push")
        self.assertEqual((r.decision, r.code), (None, 0), r)
        # someone else's video on develop, merged, then pushed: not blocked (00-plan M0 test)
        self.git("checkout", "-q", "-b", "develop")
        self.write("studio/videos/other/script.ko.md", "# other\n")
        self.git("add", "studio/videos/other/script.ko.md")
        self.git("commit", "-q", "--no-verify", "-m", "another person's video")
        self.git("checkout", "-q", "-")
        self.git("merge", "-q", "--no-edit", "develop")
        r = s.bash("git push")
        self.assertEqual((r.decision, r.code), (None, 0), r)
        # a machine-only file in the history: refused
        self.write("studio/local/videos/w/script.md", "# internal\n")
        self.git("add", "-f", "studio/local/videos/w/script.md")
        self.git("commit", "-q", "--no-verify", "-m", "leak")
        r = s.bash("git push")
        self.assertEqual(r.decision, "deny")
        self.assertIn("G-PUSH", r.reason)

    def test_e12_person_outside_a_session(self):
        self.write(".claude/studio/guides/script.md", "# g\n")
        out = self.stage()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.commit().returncode, 0)

    def test_e14_version(self):
        s = self.session()
        p = os.path.join(self.repo, ".claude", "studio", "scripts", "stdo", "__init__.py")
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(re.sub(r'SCRIPTS_VERSION = "\d+"', 'SCRIPTS_VERSION = "7"', text))
        r = s.bash(STAGE)
        self.assertEqual(r.decision, "deny")
        self.assertIn("/std update", r.reason)
        self.assertEqual(s.bash("git status").code, 0)

    def test_e16_writes_through_the_process(self):
        s = self.session()
        os.makedirs(os.path.join(self.repo, "studio", "videos", "v", "work"))
        cases = [("Write", {"file_path": os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"),
                            "content": "{}"}, "G-PROT"),
                 ("Edit", {"file_path": os.path.join(self.repo, ".claude", "studio", "config.json"),
                           "old_string": '"public_domains": []', "new_string": '"public_domains": ["x.com"]'},
                  "G-PROT"),
                 ("Edit", {"file_path": os.path.join(self.repo, ".git", "config"), "old_string": "[core]",
                           "new_string": "[core]\n\thooksPath = /dev/null"}, "G-HOOKOFF"),
                 ("Write", {"file_path": s.tpath, "content": "{}"}, "G-OUT")]
        for tool, ti, rule in cases:
            decision, reason = s.tool(tool, ti)
            self.assertEqual(decision, "deny", (tool, ti))
            self.assertIn(rule, reason)

    def test_e17_repo_wide_cleanups(self):
        s = self.session()
        self.write("studio/cast/a/character/views/front.png", "png")
        for cmd in ("git clean -fd", "git clean -fdx", "git stash -a"):
            r = s.bash(cmd)
            self.assertEqual(r.decision, "deny", cmd)
        self.assertTrue(os.path.exists(os.path.join(self.repo, "studio", "cast", "a", "character", "views",
                                                    "front.png")))
        self.write(".claude/studio/guides/script.md", "# changed\n")
        self.assertEqual(s.bash("git reset --hard").decision, "deny")

    def test_e18_lock_bypass(self):
        s = self.session()
        self.exe_on_path("s2v")
        r = s.bash("S2V_STATE_DIR=/tmp/other python3 .claude/studio/scripts/lock.py run tts -- s2v tts v.md")
        self.assertEqual(r.decision, "deny")
        self.assertIn("G-ENV", r.reason)

    def exe_on_path(self, name):
        p = os.path.join(self.pybin, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)

    def test_e19_snapshot_alias(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1792000000000-a.sh"), "w") as f:
            f.write("# Snapshot file\nunalias -a 2>/dev/null || true\n# Functions\n# Shell Options\n# Aliases\n"
                    "alias -- g=git\nexport PATH='%s'\n" % self.env["PATH"])
        s = self.session()
        self.write("studio/cast/a/character/views/front.png", "png")
        r = s.bash("g clean -fdx")
        self.assertEqual(r.decision, "deny", r)

    def test_e20_subagent(self):
        s = self.session()
        self.write(".claude/studio/guides/script.md", "# g\n")
        line, label = self.staged_line(s.bash(STAGE))
        s.ask("커밋할까요?\n" + line, [label], label)
        r = s.bash('git commit -m "x"', extra={"agent_id": "a1", "agent_type": "general-purpose"})
        self.assertEqual(r.decision, "deny")
        self.assertIn("G-MAIN", r.reason)


class ApprovalE2E(ApproveCase):
    outputs = ("youtube", "shorts")
    platforms = {"youtube": ["youtube"], "sns": ["shorts"]}

    def setUp(self):
        super().setUp()
        copy_scripts(self.repo)
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        self.s = Session(self.repo, dict(os.environ), dict(os.environ), SESSION)
        self.s.executor = state_py_executor(self, self.s)

    def sp(self, args):
        return self.s.bash("python3 .claude/studio/scripts/state.py " + args)

    def show1(self):
        for st in ("script", "verify"):
            self.assertEqual(self.cli("stage-done", "v1", st), 0, self.last_err)
        r = self.sp("shown v1 1")
        self.assertEqual(r.code, 0, r)
        return re.search(r"hash12 (\w+)", r.out).group(1)

    def test_e2_e3_approve_with_the_persons_answer(self):
        h = self.show1()
        label = "승인 v1 %s" % h
        q = "[v1] ① 대본을 승인할까요? %s" % h
        # no answer yet
        r = self.sp("approve v1 1 --expect %s" % h)
        self.assertEqual((r.decision, r.code), ("deny", None))
        # Esc, then "수정해 줘", then an Other text: none is an approval
        self.s.ask(q, [label, "수정해 줘"], None)
        self.assertEqual(self.sp("approve v1 1 --expect %s" % h).decision, "deny")
        self.s.ask(q, [label, "수정해 줘"], "수정해 줘")
        self.assertEqual(self.sp("approve v1 1 --expect %s" % h).decision, "deny")
        self.s.ask(q, [label, "수정해 줘"], "좋아요 진행")
        self.assertEqual(self.sp("approve v1 1 --expect %s" % h).decision, "deny")
        # the fixed label
        aid = self.s.ask(q, [label, "수정해 줘"], label)
        r = self.sp("approve v1 1 --expect %s" % h)
        self.assertEqual((r.decision, r.code), ("allow", 0), r)
        rec = self.state()["langs"]["ko"]["approved"]["1"]
        self.assertEqual((rec["answer"]["tool_use_id"], rec["answer"]["question_index"]), (aid, 0))
        # the same answer again
        r = self.sp("approve v1 1 --expect %s" % h)
        self.assertEqual(r.decision, "deny")
        self.assertIn("used already", r.reason)
        # the person says something before the command: an earlier turn
        self.s.ask(q, [label], label)
        self.s.say("잠깐")
        self.assertEqual(self.sp("approve v1 1 --expect %s" % h).decision, "deny")

    def test_e23_question_and_approval_in_one_message(self):
        """Review MINOR-3: the agent sends AskUserQuestion and the approval in one message — refused."""
        from e2e_runner import guard
        import transcripts as TRm
        h = self.show1()
        label = "승인 v1 %s" % h
        qs = [TRm.question("[v1] ① %s" % h, [label])]
        cmd = "python3 .claude/studio/scripts/state.py approve v1 1 --expect %s" % h
        t = self.s.t
        d = t._base("assistant", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_q", "name": "AskUserQuestion", "input": {"questions": qs}},
            {"type": "tool_use", "id": "toolu_same", "name": "Bash", "input": {"command": cmd}}]})
        t.add(d)
        t.answer("toolu_q", qs, {qs[0]["question"]: label})
        t.write(self.s.tpath)
        hook = {"session_id": SESSION, "transcript_path": self.s.tpath, "cwd": self.repo, "permission_mode": "default",
                "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
                "tool_use_id": "toolu_same", "prompt_id": t.prompt}
        decision, reason, _ = guard(hook, self.s.guard_env)
        self.assertEqual(decision, "deny")
        self.assertIn("G-EVIDENCE", reason)

    def test_e4_changed_after_showing(self):
        h = self.show1()
        self.ins["hashes"]["content"] = "c-changed"  # the script changed after it was shown
        self.s.ask("[v1] ① %s" % h, ["승인 v1 %s" % h], "승인 v1 %s" % h)
        r = self.sp("approve v1 1 --expect %s" % h)
        self.assertEqual(r.decision, "allow")  # the label is right…
        self.assertIn(r.code, (1, 3), r)  # …but state.py sees the shown work is not current (back to script: 3)
        self.assertNotIn("1", self.state()["langs"]["ko"]["approved"])

    def test_e15_rewriting_events(self):
        h = self.show1()
        self.s.ask("[v1] ① %s" % h, ["승인 v1 %s" % h], "승인 v1 %s" % h)
        self.assertEqual(self.sp("approve v1 1 --expect %s" % h).code, 0)
        # exclude-output (shorts takes sns with it)
        x = hash_of({"video": "v1", "lang": "ko", "output": "shorts", "platforms": ["sns"]})[:12]
        self.s.ask("[v1] shorts 출력을 뺄까요? %s" % x, ["제외 v1 %s" % x], "제외 v1 %s" % x)
        r = self.sp("exclude-output v1 shorts --expect %s" % x)
        self.assertEqual((r.decision, r.code), ("allow", 0), r)
        # reject the source diff
        self.src = "src2"
        st = self.state()
        st["source"]["frozen_hash"] = "src2"
        self.write_state(st)
        r = self.sp("shown v1 source-diff")
        self.assertEqual(r.code, 0, r)
        d = re.search(r"hash12 (\w+)", r.out).group(1)
        self.s.ask("[v1] 원본 변경을 받아들일까요? %s" % d, ["승인 v1 %s" % d, "거부 v1 %s" % d], "거부 v1 %s" % d)
        r = self.sp("reject-source-diff v1 --expect %s" % d)
        self.assertEqual((r.decision, r.code), ("allow", 0), r)
        # unlock a stagnation
        for _ in range(3):
            self.cli("loop", "v1", "verify")
        self.s.ask("[v1] ko 를 해제할까요?", ["해제 v1 ko stagnation"], "해제 v1 ko stagnation")
        r = self.sp("unlock v1 --expect stagnation")
        self.assertEqual((r.decision, r.code), ("allow", 0), r)
        # re-pin
        self.ins["s2v_version"] = "0.13.0+new"
        self.ver["id"] = "0.13.0+new"
        self.old_ins[1] = dict(self.ins)
        rp = hash_of({"video": "v1", "from_id": "0.12.1+abc", "to_id": "0.13.0+new"})[:12]
        self.s.ask("[v1] s2v 판을 다시 고정할까요? %s" % rp, ["재고정 v1 %s" % rp], "재고정 v1 %s" % rp)
        r = self.sp("repin v1 --expect %s" % rp)
        self.assertEqual(r.decision, "allow", r)
        self.assertNotEqual(r.code, 6, r)  # the evidence was accepted (state rules decide the rest)
        with open(paths.consumed_log(self.repo)) as f:
            cmds = [json.loads(l)["cmd"] for l in f]
        self.assertEqual(cmds[:4], ["approve", "exclude-output", "reject-source-diff", "unlock"])


class LocalBackupE2E(ApprovalE2E):
    location = "local"
    outputs = ("youtube",)
    platforms = {"youtube": ["youtube"]}

    def test_e2_e3_approve_with_the_persons_answer(self):
        pass

    def test_e4_changed_after_showing(self):
        pass

    def test_e15_rewriting_events(self):
        pass

    def test_e21_local_video_backup(self):
        h = self.show1()
        self.s.ask("[v1] ① %s" % h, ["승인 v1 %s" % h], "승인 v1 %s" % h)
        r = self.sp("approve v1 1 --expect %s" % h)
        self.assertEqual((r.decision, r.code), ("allow", 0), r)
        base = backup.root(self.repo, "v1")
        self.assertTrue(base.startswith(os.environ["STUDIO_HOME"]))
        self.assertTrue(os.path.exists(os.path.join(base, "copy.1", "manifest.json")))


class RealProcessE2E(ApproveCase):
    """M0f review MINOR-4: state.py as a real process (`python3 .claude/studio/scripts/state.py`) with a fake s2v
    behind this machine's s2v path (machine.json) — the guard's argv sha, CLAUDE_CODE_SESSION_ID and the consumption lock across
    processes."""

    FAKE = ("const fs = require('fs'), path = require('path');\n"
            "const f = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture.json'), 'utf8'));\n"
            "const a = process.argv.slice(2);\n"
            "if (a[0] === '--version') process.stdout.write(JSON.stringify(f.version));\n"
            "else if (a[0] === 'inspect') process.stdout.write(JSON.stringify(f.inspect));\n"
            "else process.exit(2);\n")

    def setUp(self):
        import shutil
        import unittest
        if not shutil.which("node"):
            raise unittest.SkipTest("needs node for the fake s2v")
        super().setUp()
        from stdo.state import hashes, store
        copy_scripts(self.repo)
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        fake = os.path.join(self.tmp, "fake-s2v")
        dist = os.path.join(fake, "packages", "cli", "dist")
        os.makedirs(dist)
        with open(os.path.join(dist, "main.js"), "w") as f:
            f.write(self.FAKE)
        with open(os.path.join(dist, "fixture.json"), "w") as f:
            json.dump({"inspect": self.ins, "version": self.ver}, f)
        machine.write(self.repo, fake)  # this machine's s2v path (m1-plan §3.1)
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)
        with open(os.path.join(self.repo, "docs", "a.md"), "w") as f:
            f.write(self.text)
        live = hashes.source_hash_repo_md(self.repo, "docs/a.md", [])
        st = store.read_state(self.vdir)
        st["source"]["frozen_hash"] = live
        self.write_state(st)
        os.makedirs(os.path.join(self.vdir, "work", "source"), exist_ok=True)
        with open(os.path.join(self.vdir, "work", "source", "a.md"), "w") as f:
            f.write(self.text)
        self.s = Session(self.repo, dict(os.environ), dict(os.environ), SESSION)

    def sp(self, args):
        return self.s.bash("python3 .claude/studio/scripts/state.py " + args)

    def direct(self, args, sid=SESSION):
        e = dict(os.environ)
        e.update({"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": sid})
        return subprocess.run(["python3", ".claude/studio/scripts/state.py"] + args.split(), cwd=self.repo,
                              capture_output=True, text=True, env=e)

    def test_e2_e3_real_state_py(self):
        for st in ("script", "verify"):
            r = self.sp("stage-done v1 %s" % st)
            self.assertEqual(r.code, 0, r)
        r = self.sp("shown v1 1")
        self.assertEqual(r.code, 0, r)
        h = re.search(r"hash12 (\w+)", r.out).group(1)
        label = "승인 v1 %s" % h
        q = "[v1] ① 대본을 승인할까요? %s" % h
        # the guard writes the evidence for this exact command line; nothing runs yet
        self.s.executor = lambda cmd: (0, "", "")
        self.s.ask(q, [label, "수정해 줘"], label)
        r = self.sp("approve v1 1 --expect %s" % h)
        self.assertEqual(r.decision, "allow", r)
        # another command line (an option added) -> the argv sha does not match
        self.assertEqual(self.direct("approve v1 1 --expect %s --lang ko" % h).returncode, 6)
        # another session's environment -> 6
        self.assertEqual(self.direct("approve v1 1 --expect %s" % h, sid="sess-other").returncode, 6)
        # the consumption lock held by another process -> busy (5), nothing recorded
        lock = paths.consumed_lock(self.repo)
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        holder = subprocess.Popen(["python3", "-c", "import fcntl,sys,time; fd=open(sys.argv[1],'a'); "
                                   "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(20)", lock],
                                  stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            self.assertEqual(self.direct("approve v1 1 --expect %s" % h).returncode, 5)
        finally:
            holder.kill()
            holder.wait()
        # the same command line in this session: recorded once
        out = self.direct("approve v1 1 --expect=%s" % h)
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = self.state()["langs"]["ko"]["approved"]["1"]
        self.assertEqual(rec["answer"]["answer"], label)
        self.assertEqual(self.direct("approve v1 1 --expect %s" % h).returncode, 6)  # used once
        # the guard refuses the replay too
        self.s.executor = self.s.shell
        r = self.sp("approve v1 1 --expect %s" % h)
        self.assertEqual(r.decision, "deny")


class RemovalE2E(HarnessCase):
    def test_removal_procedure_then_a_normal_commit(self):
        """NIT: the person takes Studio out in a terminal; afterwards ordinary commits pass."""
        from stdo.hooks import templates as T
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        hooks_dir = os.path.join(common, "hooks")
        os.remove(os.path.join(hooks_dir, "pre-commit"))  # the shim (no previous hook was chained)
        import shutil
        shutil.rmtree(os.path.join(common, "studio"))
        self.git("rm", "-q", "-r", ".claude/studio", ".claude/agents")
        gi = self.read(".gitignore")
        from stdo import ignore
        rest, _blk = ignore.split(gi)
        self.write(".gitignore", rest)
        self.git("add", ".gitignore")
        out = self.git("commit", "-q", "--no-verify", "-m", "remove Studio (the person, in a terminal)", check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.write("src/a.ts", "a\n")
        self.git("add", "src/a.ts")
        out = self.commit("an ordinary commit")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(os.path.exists(os.path.join(common, T.RUNNER_REL)))
