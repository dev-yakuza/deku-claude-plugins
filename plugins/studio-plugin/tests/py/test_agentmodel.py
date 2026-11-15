"""0.1.2 (fix-0102 §2, pilot-2 P20): a role's model — `setup.py agent-model preview|set` (the person's `설정 <h12>`
answer, its line checked by the guard and by the script before the answer is used up), the harness commit's
`모델 <role>: <old> → <new>` value line, `/std update` keeping it (`model` listed on a differing item), std-auditor.md a
protected persona, the guard (G1 and the 0.0.26 guard on the same calls). The documents' spawn rule is checked by
structure_test.sh."""

import json
import os
import re
import subprocess

import helpers
import transcripts as TR
from stdo.commit import okfile, values
from stdo.setup import labels as sl, render
from stdo.state import evidence
from test_guard_judge import JudgeCase
from test_m1c import SETUP, SID, InitCase, need_node

FC = ".claude/agents/std-fact-checker.md"
AU = ".claude/agents/std-auditor.md"
WR = ".claude/agents/std-writer.md"


class AgentModelCase(InitCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.commit_all()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SID

    def read(self, rel):
        with open(os.path.join(self.repo, rel), encoding="utf-8") as f:
            return f.read()

    def write(self, rel, text):
        with open(os.path.join(self.repo, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def preview(self, role, model):
        self.assertEqual(self.setup("agent-model", "preview", role, model), 0, self.last_err)
        return self.out_json()

    def set_model(self, role, model):
        p = self.preview(role, model)
        argv = ["agent-model", "set", role, model, "--expect", p["h12"]]
        self.pend(argv, p["label"], question="역할 모델을 바꿀까요?\n%s" % p["line"])
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        return p


class AgentModel(AgentModelCase):
    def test_preview_and_set(self):
        before = self.read(FC)
        p = self.preview("std-fact-checker", "haiku")
        self.assertEqual(p["line"], "설정 std-fact-checker model: sonnet → haiku")
        self.assertEqual(p["h12"], sl.agent_model_hash("std-fact-checker", "sonnet", "haiku"))
        self.assertEqual(p["label"], "설정 %s" % p["h12"])
        argv = ["agent-model", "set", "std-fact-checker", "haiku"]
        self.assertEqual(self.setup(*argv), 2)  # no --expect: what to ask
        self.assertIn(p["label"], self.last_err)
        argv += ["--expect", p["h12"]]
        self.assertEqual(self.setup(*argv), 6)  # no answer
        self.assertEqual(self.setup(*argv[:-1], "0" * 12), 1)  # another --expect
        # an answer whose question lacks the line (as after a `source`, where the 0.0.26 guard checks the label only),
        # or has no question: refused, and the answer is not used up
        for q in ("역할 모델을 바꿀까요?", None):
            self.pend(argv, p["label"], question=q)
            if q is None:
                with open(evidence.pending_path(self.repo)) as f:
                    ev = json.load(f)
                ev.pop("question")
                with open(evidence.pending_path(self.repo), "w") as f:
                    json.dump(ev, f)
            self.assertEqual(self.setup(*argv), 6)
            self.assertIn("values-not-shown", self.last_err)
            self.assertIn("설정 std-fact-checker model: sonnet → haiku", self.last_err)
            self.assertTrue(os.path.exists(evidence.pending_path(self.repo)))
            self.assertEqual(evidence.consumed_keys(self.repo), set())
        self.pend(argv, p["label"], question="역할 모델을 바꿀까요?\n%s" % p["line"])
        self.assertEqual(self.setup(*argv), 0, self.last_err)
        after = self.read(FC)
        self.assertEqual(after, before.replace("model: sonnet", "model: haiku", 1))
        self.assertEqual(render.persona_block(after), render.persona_block(before))
        self.assertEqual(self.setup(*argv), 3)  # already haiku
        p = self.preview("std-fact-checker", "opus")
        self.pend(["agent-model", "set", "std-fact-checker", "opus", "--expect", p["h12"], "--proxy"], p["label"],
                  question=p["line"])
        self.assertEqual(self.setup("agent-model", "set", "std-fact-checker", "opus", "--expect", p["h12"], "--proxy"), 2)

    def test_the_auditors_tools_stay(self):
        before = self.read(AU)
        self.set_model("std-auditor", "opus")
        after = self.read(AU)
        self.assertEqual(after, before.replace("model: sonnet", "model: opus", 1))
        self.assertIn("tools: Read, Grep, Glob", after)

    def test_a_missing_line_is_added(self):
        self.write(WR, self.read(WR).replace("model: sonnet\n", ""))
        p = self.preview("std-writer", "haiku")
        self.assertEqual(p["line"], "설정 std-writer model: (없음) → haiku")
        self.set_model("std-writer", "haiku")
        head = self.read(WR).split("---")[1]
        self.assertEqual(re.findall(r"(?m)^(\w+):", head), ["name", "description", "model"])
        self.assertEqual(values.read_model(self.read(WR)), "haiku")

    def test_crlf_and_a_comment(self):
        self.write(WR, self.read(WR).replace("model: sonnet", "model: sonnet  # the default").replace("\n", "\r\n"))
        p = self.preview("std-writer", "haiku")
        self.assertEqual(p["line"], "설정 std-writer model: sonnet → haiku")
        self.set_model("std-writer", "haiku")
        with open(os.path.join(self.repo, WR), "rb") as f:
            raw = f.read()
        self.assertIn(b"\r\nmodel: haiku\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_refusals(self):
        for role, model, code in (("std-translator", "haiku", 2), ("../x", "haiku", 2), ("std-writer", "fable", 2),
                                  ("std-writer", "sonnet[1m]", 2)):
            self.assertEqual(self.setup("agent-model", "preview", role, model), code, (role, model))
        self.write(WR, self.read(WR).replace("model: sonnet\n", "model: sonnet\nmodel: opus\n"))
        self.assertEqual(self.setup("agent-model", "preview", "std-writer", "haiku"), 1)
        self.assertIn("2 model: lines", self.last_err)
        self.write(WR, "# no frontmatter\n")
        self.assertEqual(self.setup("agent-model", "preview", "std-writer", "haiku"), 1)
        os.remove(os.path.join(self.repo, WR))
        self.assertEqual(self.setup("agent-model", "preview", "std-writer", "haiku"), 1)
        self.assertIn("is missing", self.last_err)
        self.assertEqual(self.setup("agent-model", "set", "std-writer"), 2)

    def test_harness_commit_shows_the_model(self):
        self.set_model("std-fact-checker", "haiku")
        r = self.script("check_commit.py", "--stage", "harness")
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)
        self.assertEqual(ok["values_shown"], ["모델 std-fact-checker: sonnet → haiku"])
        self.assertIn("모델 std-fact-checker: sonnet → haiku", r.stdout)
        # the hook recomputes the block from HEAD and the index: the same lines, so the commit goes through
        c = subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "x"], capture_output=True, text=True,
                           env=dict(os.environ))
        self.assertEqual(c.returncode, 0, c.stderr)
        # an Edit of a role that is not protected changes the model too: the harness commit shows it
        self.write(WR, self.read(WR).replace("model: sonnet", "model: opus"))
        r = self.script("check_commit.py", "--stage", "harness")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(okfile.read(self.repo)[0]["values_shown"], ["모델 std-writer: sonnet → opus"])

    def test_the_auditor_cannot_be_deleted(self):
        os.remove(os.path.join(self.repo, AU))
        r = self.script("check_commit.py", "--stage", "harness")
        self.assertEqual(r.returncode, 1)
        self.assertIn("%s is deleted" % AU, r.stderr)


class FirstInstallNoModel(InitCase):
    def test_no_model_line_on_first_install(self):
        need_node()
        self.init()
        r = self.script("check_commit.py", "--stage", "harness")
        self.assertEqual(r.returncode, 0, r.stderr)
        ok, _ = okfile.read(self.repo)
        self.assertFalse([l for l in ok["values_shown"] + ok["values_settings"] if l.startswith("모델 ")])


class UpdateKeepsTheModel(AgentModelCase):
    def plan(self, take=None):
        args = ["update", "plan"] + (["--take", take] if take else [])
        self.assertEqual(self.setup(*args), 0, self.last_err)
        return self.out_json()

    def item(self, p, path):
        return [i for i in p["templates"] if i["path"] == path][0]

    def apply(self, p, take=None):
        argv = ["update", "apply", "--expect", p["h12"]] + (["--take", take] if take else [])
        self.pend(argv, p["label"])
        return self.setup(*argv)

    def newer(self, changes):
        real = render.templated

        def f(vals):
            out = real(vals)
            for rel, g in changes.items():
                out[rel] = g(out[rel])
            return out
        render.templated = f
        self.addCleanup(setattr, render, "templated", real)

    def test_new_keeps_new_file_resets(self):
        self.set_model("std-writer", "haiku")
        self.commit_all()
        p = self.plan()
        self.assertEqual(self.item(p, WR)["state"], "same")
        self.assertEqual(self.item(p, WR)["model"], {"local": "haiku", "new": "sonnet"})
        self.assertNotIn("model", self.item(p, FC))
        self.newer({WR: lambda t: t.replace("## Rules", "## Rules\n- upstream rule")})
        p = self.plan()
        self.assertEqual(self.item(p, WR)["state"], "update")
        self.assertEqual(self.apply(p), 0, self.last_err)
        self.assertIn("upstream rule", self.read(WR))
        self.assertEqual(values.read_model(self.read(WR)), "haiku")
        self.write(WR, self.read(WR).replace("upstream rule", "local rule"))
        p = self.plan(take="%s=new-file" % WR)
        self.assertEqual(self.apply(p, take="%s=new-file" % WR), 0, self.last_err)
        self.assertEqual(values.read_model(self.read(WR)), "sonnet")

    def test_the_auditor_is_a_protected_persona(self):
        """A 0.1.1 repository whose auditor persona is unedited: update asks (protected-needs-choice), and `new` writes
        the block and keeps the model and the tools."""
        self.set_model("std-auditor", "opus")
        self.commit_all()
        self.newer({AU: lambda t: t.replace("- Read only.", "- Read only. Read each teaching note too.")})
        p = self.plan()
        self.assertEqual(self.item(p, AU)["state"], "protected-needs-choice")
        self.assertIn(AU, p["conflicts"])
        p = self.plan(take="%s=new" % AU)
        self.assertEqual(self.apply(p, take="%s=new" % AU), 0, self.last_err)
        text = self.read(AU)
        self.assertIn("Read each teaching note too.", text)
        self.assertEqual(values.read_model(text), "opus")
        self.assertIn("tools: Read, Grep, Glob", text)


class GuardAgentModel(JudgeCase):
    def setUp(self):
        super().setUp()
        self.tpath = TR.transcript_path(self.env)
        os.makedirs(os.path.join(self.repo, ".claude", "agents"), exist_ok=True)
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "local"), exist_ok=True)
        for role in ("std-fact-checker", "std-auditor"):
            with open(os.path.join(helpers.SKILL, "templates", "agents", role + ".md"), encoding="utf-8") as f:
                text = f.read()
            with open(os.path.join(self.repo, ".claude", "agents", role + ".md"), "w", encoding="utf-8") as f:
                f.write(text)

    def hook_for(self, cmd, **extra):
        h = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": "sess-1",
             "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
             "prompt_id": getattr(self, "t", None) and self.t.prompt or "p-none"}
        h.update(extra)
        return h

    def run_hook(self, cmd, **extra):
        from stdo.guard import judge
        return judge.decide(self.hook_for(cmd, **extra), self.env, snapshot_loader=self.loader)

    def turn(self, label, qtext):
        self.t = TR.approval_turn(TR.T(), label, qtext=qtext)
        self.t.write(self.tpath)

    def test_set_needs_the_line(self):
        h = sl.agent_model_hash("std-fact-checker", "sonnet", "haiku")
        line = sl.agent_model_line("std-fact-checker", "sonnet", "haiku")
        cmd = "python3 %s agent-model set std-fact-checker haiku --expect %s" % (SETUP, h)
        deny, _ = self.run_hook(cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.turn("설정 %s" % h, "역할 모델을 바꿀까요? %s" % h)  # the line missing
        deny, _ = self.run_hook(cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn(line, deny.message())
        self.turn("설정 %s" % h, "역할 모델을 바꿀까요? %s\n%s" % (h, line))
        deny, ctx = self.run_hook(cmd)
        self.assertIsNone(deny, deny and deny.message())
        self.assertTrue(ctx.allow)
        deny, _ = self.run_hook(cmd, agent_id="a1", agent_type="std-writer")  # from a subagent
        self.assertEqual(deny.rule, "G-MAIN")
        deny, _ = self.run_hook(cmd + " --proxy")
        self.assertEqual(deny.rule, "G-PROXY")
        # stale: the file changed after the question (the line the guard computes is another one)
        p = os.path.join(self.repo, FC)
        with open(p) as f:
            text = f.read()
        with open(p, "w") as f:
            f.write(text.replace("model: sonnet", "model: opus"))
        deny, _ = self.run_hook(cmd)
        self.assertEqual(deny.rule, "G-EVIDENCE")
        self.assertIn("설정 std-fact-checker model: opus → haiku", deny.message())

    def test_a_role_outside_the_list_reads_no_file(self):
        opened = []
        import builtins
        real = builtins.open

        def spy(f, *a, **k):
            opened.append(str(f))
            return real(f, *a, **k)
        for role in ("../x", "std-translator", "std-x/../../etc"):
            cmd = "python3 %s agent-model set %s haiku --expect %s" % (SETUP, role, "a" * 12)
            builtins.open = spy
            try:
                deny, _ = self.run_hook(cmd)
            finally:
                builtins.open = real
            self.assertEqual(deny.rule, "G-APPROVAL", role)
            self.assertIn("is not a Studio role", deny.message())
            self.assertFalse([p for p in opened if ".claude/agents" in p], role)
        self.assertIn("std-auditor", render.AGENTS)

    def test_the_026_guard_on_the_same_calls(self):
        """The 0.0.26 guard reaches its own setup check through the shared setup/labels: it refuses a call without an
        answer and passes one with it (it checks the label only; the script checks the line)."""
        from stdo.guard.legacy import judge as lj
        h = sl.agent_model_hash("std-fact-checker", "sonnet", "haiku")
        cmd = "python3 %s agent-model set std-fact-checker haiku --expect %s" % (SETUP, h)
        d, _ = lj.decide(self.hook_for(cmd), dict(self.env))
        self.assertIsNotNone(d)
        self.turn("설정 %s" % h, "역할 모델을 바꿀까요? %s\n%s" % (h, sl.agent_model_line("std-fact-checker", "sonnet",
                                                                                        "haiku")))
        d, _ = lj.decide(self.hook_for(cmd), dict(self.env))
        self.assertIsNone(d, d and d.message())

    def test_the_auditor_file_is_protected(self):
        d = self.decide("Edit", {"file_path": os.path.join(self.repo, AU), "old_string": "model: sonnet",
                                 "new_string": "model: opus"})
        self.assertEqual(d.rule, "G-PROT")
        self.assertIn("persona", d.message())
        d = self.decide("Edit", {"file_path": os.path.join(self.repo, ".claude", "agents", "std-writer.md"),
                                 "old_string": "a", "new_string": "b"})
        self.assertIsNone(d, d and d.message())  # the other roles stay editable (the harness commit shows a model)

    def test_the_auditor_file_after_a_source(self):
        """0.1.4 (std-auditor.md after a source, fix-0102 §2.4): this guard walks on after a `source` — a file it can
        read (class 3) and one it cannot (class 4) both keep the literal persona path refused."""
        with open(os.path.join(self.repo, "e.sh"), "w") as f:
            f.write("export A=1\n")
        for cmd in ("source e.sh; echo x > %s" % AU, "source missing.sh; cp x %s" % AU):
            deny, _ = self.run_hook(cmd)
            self.assertIsNotNone(deny, cmd)
            self.assertEqual(deny.rule, "G-PROT", cmd)
