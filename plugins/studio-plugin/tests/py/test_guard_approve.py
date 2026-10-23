"""M0d-2 §3–§4, §7: approval commands with the transcript evidence, the pending file, when allow is given
(v2 MAJOR: the call is just that command, with no environment change, alias, wrapper or other interpreter),
the proxy mode, non-interactive sessions, and a guard → state.py end-to-end run."""

import json
import os

import transcripts as TR
from approve_base import ApproveCase, SESSION
from commit_base import commit_scripts
from guard_base import snapshot_text
from stdo import paths
from stdo.guard import judge, transcript
from stdo.state.argv import argv_sha
from test_guard_judge import ALIASES, JudgeCase

H = "3f2a9c0d1e4b"
APPROVE = "python3 .claude/studio/scripts/state.py approve v 1 --expect %s" % H


class GuardApproval(JudgeCase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        self.tpath = TR.transcript_path(self.env)
        self.t = None
        self.video_state("v")

    def video_state(self, vid, lang="ko"):
        d = os.path.join(self.repo, "studio", "videos", vid, "work")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump({"video": vid, "source_lang": lang}, f)

    # --- helpers ---
    def turn(self, label="승인 v %s" % H, **kw):
        self.t = TR.approval_turn(TR.T(), label, **kw)
        self.t.write(self.tpath)
        return self.t

    def run_hook(self, cmd, cwd=None, extra=None):
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd or self.repo, "session_id": "sess-1",
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": self.t.prompt if self.t else "p-none"}
        hook.update(extra or {})
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def pending_path(self):
        return os.path.join(self.repo, ".claude", "studio", "local", "pending-approval.json")

    def pending(self):
        try:
            with open(self.pending_path()) as f:
                return json.load(f)
        except OSError:
            return None

    def assertAllow(self, cmd, **kw):
        deny, ctx = self.run_hook(cmd, **kw)
        self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
        self.assertTrue(ctx.allow, "should allow: %s" % cmd)
        return ctx

    def assertNoDecision(self, cmd, pending=True, **kw):
        if os.path.exists(self.pending_path()):
            os.remove(self.pending_path())
        deny, ctx = self.run_hook(cmd, **kw)
        self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
        self.assertIsNone(ctx.allow, "should not allow: %s" % cmd)
        if pending:
            self.assertIsNotNone(self.pending(), "evidence still written: %s" % cmd)
        return ctx

    def assertRule(self, cmd, rule, **kw):
        deny, ctx = self.run_hook(cmd, **kw)
        self.assertIsNotNone(deny, "should deny: %s" % cmd)
        self.assertEqual(deny.rule, rule, deny.message())
        self.assertIsNone(ctx.allow)
        return deny

    # --- evidence ---
    def test_allow_and_pending(self):
        self.turn()
        ctx = self.assertAllow(APPROVE)
        p = self.pending()
        self.assertEqual(p["argv_sha"], argv_sha(["approve", "v", "1", "--expect", H]))
        self.assertEqual((p["session_id"], p["tool_use_id"], p["question_index"], p["answer"], p["mode"]),
                         ("sess-1", "toolu_ask1", 0, "승인 v %s" % H, "human"))
        self.assertIn(H, p["question"])
        self.assertIn("toolu_ask1#0", ctx.allow)
        # --x=v spelling: same canonical argv
        os.remove(self.pending_path())
        self.assertAllow(APPROVE.replace("--expect ", "--expect="))
        self.assertEqual(self.pending()["argv_sha"], p["argv_sha"])

    def test_current_call_written_after_pretooluse(self):
        """M0f U1: interactive sessions write the current call's line after the tool ran — still allowed."""
        self.turn()
        self.t.lines.pop()
        self.t.write(self.tpath)
        ctx = self.assertAllow(APPROVE)
        self.assertEqual(self.pending()["tool_use_id"], "toolu_ask1")

    def test_no_or_wrong_evidence(self):
        d = self.assertRule(APPROVE, "G-EVIDENCE")
        self.assertIn("승인 v %s" % H, d.message())
        self.turn(chosen="수정해 줘")
        self.assertRule(APPROVE, "G-EVIDENCE")
        self.turn(label="승인 v 000000000000", qtext="[v] q 000000000000")
        self.assertRule(APPROVE, "G-EVIDENCE")
        self.assertIsNone(self.pending())

    def test_consumed_answer_is_not_reused(self):
        self.turn()
        log = paths.consumed_log(self.repo)
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w") as f:
            f.write(json.dumps({"session_id": "sess-1", "tool_use_id": "toolu_ask1", "question_index": 0}) + "\n")
        d = self.assertRule(APPROVE, "G-EVIDENCE")
        self.assertIn("used already", d.message())
        self.assertIsNone(self.pending())

    def test_subcommands_and_labels(self):
        cases = [("reject-source-diff v --expect %s" % H, "거부 v %s" % H), ("repin v --expect %s" % H, "재고정 v %s" % H),
                 ("exclude-output v short --expect %s" % H, "제외 v %s" % H)]
        for args, label in cases:
            self.turn(label=label)
            self.assertAllow("python3 .claude/studio/scripts/state.py " + args)
            self.assertEqual(self.pending()["answer"], label)
        # unlock: video and language from the state (read only)
        with open(os.path.join(self.repo, "studio", "videos", "v", "work", "state.json"), "w") as f:
            json.dump({"video": "v", "source_lang": "ko"}, f)
        self.turn(label="해제 v ko stagnation", qtext="[v] ko 를 해제할까요?")
        self.assertAllow("python3 .claude/studio/scripts/state.py unlock v --expect stagnation")
        self.turn(label="해제 v en stagnation", qtext="[v] en 을 해제할까요?")
        self.assertRule("python3 .claude/studio/scripts/state.py unlock v --expect stagnation", "G-EVIDENCE")
        self.assertAllow("python3 .claude/studio/scripts/state.py unlock v --lang en --expect stagnation")
        # --expect must be the 12 hex shown
        self.turn()
        self.assertRule("python3 .claude/studio/scripts/state.py approve v 1 --expect 3F2A", "G-APPROVAL")

    def test_credit_and_unknown_need_evidence_and_are_denied(self):
        self.turn(label="승인 v %s" % H)
        for sub in ("credit studio/x.png --expect %s" % H, "approve-actor a definition --expect %s" % H,
                    "frobnicate v", "rollback v"):
            d = self.assertRule("python3 .claude/studio/scripts/state.py " + sub, "G-APPROVAL")
            self.assertIn("approval", d.message())
        self.assertIsNone(self.pending())

    def test_one_approval_per_call(self):
        self.turn()
        self.assertRule(APPROVE + " && " + APPROVE, "G-APPROVAL")
        self.assertIsNone(self.pending())

    def test_deny_elsewhere_writes_no_pending(self):
        self.turn()
        self.assertRule(APPROVE + " && rm -rf studio/local", "G-DEL")
        self.assertIsNone(self.pending())

    def test_subagent(self):
        self.turn()
        self.assertRule(APPROVE, "G-MAIN", extra={"agent_id": "a1", "agent_type": "general-purpose"})

    def test_non_interactive(self):
        self.t = TR.approval_turn(TR.T(entrypoint="sdk-cli"), "승인 v %s" % H)
        self.t.write(self.tpath)
        d = self.assertRule(APPROVE, "G-EVIDENCE")
        self.assertIn("claude -p", d.message())

    def test_permission_modes_do_not_matter(self):
        for mode in ("default", "acceptEdits", "plan", "auto", "dontAsk", "bypassPermissions"):
            self.turn()
            self.assertAllow(APPROVE, extra={"permission_mode": mode})
            self.t = None
            os.remove(self.tpath)
            self.assertRule(APPROVE, "G-EVIDENCE", extra={"permission_mode": mode})

    # --- v2 MAJOR: allow only for the plain command alone ---
    def test_allow_shapes(self):
        self.turn()
        self.assertAllow("cd %s && %s" % (self.repo, APPROVE), cwd=os.path.join(self.repo, "src"))
        self.assertAllow(APPROVE + " 2>&1")
        self.assertAllow(APPROVE.replace("python3 ", "python3 -B "))
        for cmd in (APPROVE + " | cat", APPROVE + "; echo done", APPROVE + " && echo ok", "true && " + APPROVE,
                    APPROVE + " > out.txt", "( %s )" % APPROVE, APPROVE + " &",
                    APPROVE.replace("python3 ", "python3 -X importtime ")):
            self.assertNoDecision(cmd)
        self.assertNoDecision("cd %s || %s" % (self.repo, APPROVE), pending=False)  # the script path is not certain
        self.assertNoDecision("cd %s; %s" % (self.repo, APPROVE))  # only `cd <dir> &&` may come before
        self.assertNoDecision("cd %s\n%s" % (self.repo, APPROVE))

    def test_env_changes_mean_no_allow(self):
        self.turn()
        for pre in ("PYTHONPATH=/tmp/x ", "PYTHONHOME=/tmp/x ", "PYTHONSTARTUP=/tmp/x.py ",
                    "DYLD_INSERT_LIBRARIES=/tmp/x.dylib ", "PYTHONDONTWRITEBYTECODE=1 ", "PATH=/tmp/x:$PATH ",
                    "env ", "env PYTHONPATH=/tmp/x "):
            self.assertNoDecision(pre + APPROVE)
        self.assertNoDecision('export PATH="/tmp/x:$PATH" && ' + APPROVE)
        self.assertNoDecision("unset PYTHONPATH && " + APPROVE)

    def test_alias_and_other_interpreters_mean_no_allow(self):
        self.turn()
        self.exe("python3.12")
        self.assertAllow(APPROVE.replace("python3 ", "python3.12 "))
        self.assertNoDecision(APPROVE.replace("python3 ", "%s/python3 " % self.bin))  # not /usr/bin/python3
        self.assertNoDecision(APPROVE.replace("python3 ", "python "))
        self.snap_with = self._snap(ALIASES + [("python3", "'python3 -B'")])
        self.assertNoDecision(APPROVE)

    def test_interpreter_resolves_elsewhere_in_the_shell(self):
        self.turn()
        other = os.path.join(self.tmp, "other-bin")
        os.makedirs(other)
        p = os.path.join(other, "python3")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(p, 0o755)
        self.snap_with = self._snap(ALIASES, path=other + ":" + self.env["PATH"])
        self.assertNoDecision(APPROVE)

    def _snap(self, aliases, path=None):
        from stdo.guard import snapshot as snapmod
        import shutil
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-2-b.sh"), "w") as f:
            f.write(snapshot_text(aliases=aliases, path=path or self.env["PATH"]))
        snap = snapmod.load(self.env)
        shutil.rmtree(d)
        return snap

    # --- proxy mode ---
    def sandbox(self, root=None, on=True):
        with open(os.path.join(self.env["STUDIO_HOME"], "studio-sandbox.json"), "w") as f:
            json.dump({"sandbox_root": root or self.tmp}, f)
        if on:
            self.env["STUDIO_SANDBOX"] = "1"

    def test_proxy_mode(self):
        self.sandbox()
        ctx = self.assertAllow(APPROVE + " --proxy")
        p = self.pending()
        self.assertEqual((p["mode"], p["tool_use_id"], p["question_index"], p["question"], p["answer"]),
                         ("proxy", "toolu_cmd1", 0, "proxy", "승인 v %s" % H))
        self.assertIn("proxy", ctx.allow)
        # s2v approvals are allowed in the proxy mode (none in the person's mode until M3b)
        self.assertAllow("s2v character approve a")
        self.assertNoDecision("S2V_X=1 s2v character approve a", pending=False)

    def test_proxy_conditions(self):
        self.assertRule(APPROVE + " --proxy", "G-PROXY")  # no STUDIO_SANDBOX
        self.sandbox(on=False)
        self.assertRule(APPROVE + " --proxy", "G-PROXY")
        self.sandbox(root=os.path.join(self.tmp, "elsewhere"))
        self.assertRule(APPROVE + " --proxy", "G-PROXY")
        self.sandbox(root="relative/path")
        self.assertRule(APPROVE + " --proxy", "G-PROXY")
        with open(os.path.join(self.env["STUDIO_HOME"], "studio-sandbox.json"), "w") as f:
            f.write("{broken")
        self.assertRule(APPROVE + " --proxy", "G-PROXY")
        self.sandbox()
        self.assertRule("STUDIO_SANDBOX=1 " + APPROVE + " --proxy", "G-ENV")
        # without --proxy the person's answer is still needed in the sandbox
        self.assertRule(APPROVE, "G-EVIDENCE")

    def test_s2v_approvals_in_the_persons_mode(self):
        self.turn(label="승인 v %s" % H)
        d = self.assertRule("s2v character approve a", "G-APPROVAL")
        self.assertIn("M3b", d.message())
        self.assertRule("python3 .claude/studio/scripts/lock.py actor-op a -- s2v character approve a", "G-APPROVAL")


class EndToEnd(ApproveCase):
    """The guard writes the evidence from a transcript; the real state.py consumes it once."""

    def setUp(self):
        super().setUp()
        commit_scripts(self.repo)
        self.tpath = TR.transcript_path(os.environ, SESSION)
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)

    def guard(self, cmd, t):
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": SESSION,
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": t.prompt}
        return judge.decide(hook, dict(os.environ), snapshot_loader=lambda env: (None, ["snapshot-none"]))

    def test_guard_then_state_py(self):
        for st in ("script", "verify"):
            self.assertEqual(self.cli("stage-done", "v1", st), 0, self.last_err)
        h = self.show("1")
        label = "승인 v1 %s" % h
        t = TR.approval_turn(TR.T(session_id=SESSION), label, qtext="[v1] ① 대본을 승인할까요? %s" % h)
        t.write(self.tpath)
        cmd = "python3 .claude/studio/scripts/state.py approve v1 1 --expect %s" % h
        deny, ctx = self.guard(cmd, t)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)
        self.assertEqual(self.cli("approve", "v1", "1", "--expect", h), 0, self.last_err)
        rec = self.state()["langs"]["ko"]["approved"]["1"]
        self.assertEqual(rec["answer"]["tool_use_id"], "toolu_ask1")
        self.assertEqual(rec["answer"]["answer"], label)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "studio", "local", "pending-approval.json")))
        # replay: the same answer again -> the guard refuses (consumed) and writes nothing
        deny, ctx = self.guard(cmd, t)
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("used already", deny.message())
        # and a pending written by hand for the replay is refused by state.py too (exit 6)
        self.pend(["approve", "v1", "1", "--expect", h], label, tool="toolu_ask1", index=0)
        self.assertEqual(self.cli("approve", "v1", "1", "--expect", h), 6)
