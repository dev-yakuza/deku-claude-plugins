"""M0e: the pre-commit hook's checks and --stage (m0e-plan v2 §5–§7, §12.2–12.3). Real git in temporary
repositories; the hook runs through real `git commit`."""

import json
import os
import subprocess

import helpers
import state_fixtures as F
from commit_base import SID, CommitCase
from stdo.commit import approvals, checks, kinds, okfile, spaths
from stdo.commit.gitx import Git
from stdo.state import store


class NonStudio(CommitCase):
    def test_other_paths_pass_without_python(self):
        # a python3 that leaves a trace: the runner must not call it for non-Studio commits
        trace = os.path.join(self.tmp, "py-called")
        os.remove(os.path.join(self.pybin, "python3"))
        self.exe(os.path.join(self.pybin, "python3"), "#!/bin/sh\ntouch '%s'\nexit 1\n" % trace)
        for rel in ("src/a.ts", "plugins/other/x.md", ".claude/agents/other.md", ".claude/settings.json",
                    "src/한 글.ts"):
            self.write(rel)
            self.git("add", rel)
            out = self.commit("other " + rel)
            self.assertEqual(out.returncode, 0, rel + out.stderr)
        self.assertFalse(os.path.exists(trace))

    def test_gitignore_outside_block_passes(self):
        with open(os.path.join(self.repo, ".gitignore"), "a") as f:
            f.write("node_modules/\n")
        self.git("add", ".gitignore")
        self.assertEqual(self.commit().returncode, 0)


class Local(CommitCase):
    def test_local_paths_refused(self):
        for rel in ("studio/local/x", ".claude/studio/local/notes.md"):
            self.write(rel)
            self.git("add", "-f", rel)
            out = self.commit()
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("machine-only", out.stderr)
            self.git("restore", "--staged", rel)
        # mixed with an ordinary file
        self.write("src/a.ts")
        self.git("add", "src/a.ts")
        self.git("add", "-f", "studio/local/x")
        self.assertNotEqual(self.commit().returncode, 0)

    def test_unstaging_or_deleting_a_leak_passes(self):
        """Review MINOR 1: `git rm --cached` / `git rm` of a leaked local file is not a leak."""
        for rel, rm in (("studio/local/leak.txt", ["rm", "-q", "--cached"]),
                        (".claude/studio/local/leak2.txt", ["rm", "-q"])):
            self.write(rel)
            self.git("add", "-f", rel)
            self.assertEqual(self.commit("leak", "--no-verify").returncode, 0)
            self.git(*(rm + [rel]))
            out = self.commit("unleak " + rel)
            self.assertEqual(out.returncode, 0, out.stderr)
        # a real leak says what it is
        self.write("studio/local/new.txt")
        self.git("add", "-f", "studio/local/new.txt")
        out = self.commit()
        self.assertIn("staged to be added or changed", out.stderr)
        self.assertIn("  - studio/local/new.txt", out.stderr)

    def test_fixed_local_path_without_the_runner(self):
        """Review MINOR 2: check_commit --staged itself refuses .claude/studio/local/ (whatever studio_root)."""
        self.write(".claude/studio/local/x.json")
        self.git("add", "-f", ".claude/studio/local/x.json")
        out = self.cc("--staged", "--json")
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn(".claude/studio/local/x.json", [p.get("path") for p in json.loads(out.stdout)["problems"]])

    def test_case_variant_on_ignorecase(self):
        self.git("config", "core.ignorecase", "true")
        self.write("Studio/Local/x")
        self.git("add", "-f", "Studio/Local/x")
        out = self.commit()
        self.assertNotEqual(out.returncode, 0, out.stderr)

    def test_without_harness_branch_still_refuses_local(self):
        self.git("checkout", "-q", "--orphan", "bare")
        self.git("rm", "-rq", "--cached", ".")
        for p in (".claude", ".gitignore"):
            subprocess.run(["rm", "-rf", os.path.join(self.repo, p)])
        self.write("README.md", "bare\n")
        self.git("add", "README.md")
        self.assertEqual(self.commit("bare").returncode, 0)
        self.write("studio/local/x")
        self.git("add", "-f", "studio/local/x")
        out = self.commit("leak")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("machine-only", out.stderr)
        # a Studio path that is not local passes on a branch without the harness
        self.git("restore", "--staged", "studio/local/x")
        self.write("studio/videos/v/script.ko.md")
        self.git("add", "studio/videos/v/script.ko.md")
        self.assertEqual(self.commit("no harness").returncode, 0)


class MediaRoot(CommitCase):
    studio_root = "media"

    def test_configured_root_only(self):
        # an unrelated app folder named studio/ is not Studio's when studio_root is media
        self.write("studio/app.ts")
        self.write("studio/local/x")
        self.git("add", "studio/app.ts", "studio/local/x")
        out = self.commit("app")
        self.assertEqual(out.returncode, 0, out.stderr)
        g = Git(self.repo, self.env)
        ctx = checks.Ctx(g, self.env, kinds.registry(self.env))
        self.assertEqual(ctx.roots, ["media"])
        self.write("media/local/x")
        self.git("add", "-f", "media/local/x")
        out = self.commit("leak")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("media/local/x", out.stderr)

    def test_default_root_without_config_or_marker(self):
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        self.git("init", "-q", cwd=bare)
        self.assertEqual(spaths.studio_roots(bare, Git(bare, self.env), self.env), ["studio"])
        self.write("studio/local/x", repo=bare)
        self.git("add", "-f", "studio/local/x", cwd=bare)
        out = subprocess.run(["python3", "-B", os.path.join(helpers.SCRIPTS, "check_commit.py"), "--staged"],
                             cwd=bare, capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 1, out.stderr)


class Mixed(CommitCase):
    def test_mixed_refused_with_both_ways(self):
        self.write("studio/videos/v1/script.ko.md")
        self.write("src/a.ts")
        self.git("add", "studio/videos/v1/script.ko.md", "src/a.ts")
        out = self.commit()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("mixes Studio paths (1) with other paths (1)", out.stderr)
        self.assertIn("git restore --staged -- 'studio/videos/v1/script.ko.md'", out.stderr)

    def test_gitignore_kinds(self):
        blk = self.read(".gitignore")
        k = spaths.gitignore_kind
        self.assertEqual(k(blk.encode(), (blk + "x/\n").encode()), "other")
        self.assertEqual(k(blk.encode(), blk.replace("/studio/out/\n", "").encode()), "studio")
        self.assertEqual(k(blk.encode(), (blk.replace("/studio/out/\n", "") + "x/\n").encode()), "mixed")
        self.assertEqual(k(blk.encode(), (blk + "# <<< studio <<<\n").encode()), "broken")
        # a block-only change is a Studio change: refused without commit-ok
        with open(os.path.join(self.repo, ".gitignore"), "w") as f:
            f.write(blk.replace("/studio/out/\n", "/studio/out/\n/studio/tmp/\n"))
        self.git("add", ".gitignore")
        out = self.commit()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("did not prepare this commit", out.stderr)


class StageAndCommit(CommitCase):
    def stage(self, *extra, env=None):
        return self.cc("--stage", "test", "v1", *extra, env=env)

    def test_stage_then_commit(self):
        self.ready()
        out = self.stage()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout, r"ask the user with the option \"커밋 [0-9a-f]{12}\"")
        ok, _ = okfile.read(self.repo)
        self.assertEqual(ok["paths"], ["studio/videos/v1/script.ko.md"])
        self.assertEqual(ok["label"], "커밋 " + ok["tree"][:12])
        self.assertIsNone(ok["session_id"])
        out = self.commit("video")
        self.assertEqual(out.returncode, 0, out.stderr)
        # one use only: the next Studio commit with the same commit-ok is refused
        self.write("studio/videos/v1/script.ko.md", "# changed\n")
        self.git("add", "studio/videos/v1/script.ko.md")
        out = self.commit("again")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("is not the one Studio prepared", out.stderr)

    def test_more_staged_after_stage(self):
        self.ready()
        self.assertEqual(self.stage().returncode, 0)
        self.write("studio/videos/v1/assets/a.png", "png")
        self.git("add", "studio/videos/v1/assets/a.png")
        out = self.commit()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("not the ones Studio prepared", out.stderr)

    def test_commit_all_uses_another_index(self):
        self.ready()
        self.assertEqual(self.stage().returncode, 0)
        self.write("README.md", "changed\n")
        out = self.commit("all", "-a")
        self.assertNotEqual(out.returncode, 0)

    def test_head_bound(self):
        self.ready()
        self.assertEqual(self.stage().returncode, 0)
        p = okfile.path(self.repo)
        data = json.load(open(p))
        data["head"] = "0" * 40
        json.dump(data, open(p, "w"))
        out = self.commit()
        self.assertIn("HEAD moved", out.stderr)

    def test_existing_other_staged_refused_untouched(self):
        self.ready()
        self.write("src/a.ts")
        self.git("add", "src/a.ts")
        before = self.git("write-tree").stdout
        out = self.stage()
        self.assertEqual(out.returncode, 1)
        self.assertIn("other changes are already staged", out.stderr)
        self.assertEqual(self.git("write-tree").stdout, before)
        self.assertFalse(os.path.exists(okfile.path(self.repo)))

    def test_planned_kinds_refuse(self):
        self.ready()
        for kind, m in (("video", "M1"), ("actor", "M3b"), ("harness", "M0f")):
            out = self.cc("--stage", kind, "v1")
            self.assertEqual(out.returncode, 3, out.stderr)
            self.assertIn(m, out.stderr)
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")

    def test_overlay(self):
        self.video()
        out = self.stage()
        self.assertEqual(out.returncode, 4, out.stderr)
        self.assertIn("overlay", out.stderr)
        self.overlay(wrong=True)
        self.assertEqual(self.stage().returncode, 4)
        self.overlay()
        self.assertEqual(self.stage().returncode, 0)
        # the hook checks it too
        os.remove(os.path.join(self.repo, ".claude/studio/local/config.internal.json"))
        out = self.commit()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("overlay", out.stderr)

    def test_overlay_not_needed_by_a_kind_without_internal_content(self):
        self.video()

        class NoOverlay(kinds.FolderKind):
            needs_overlay = False
        g = Git(self.repo, self.env)
        ctx = checks.Ctx(g, self.env, kinds.registry(self.env, {"test": NoOverlay()}))
        from stdo.commit import stage
        code, problems, data = stage.run(ctx, "test", "v1")
        self.assertEqual(code, 0, [p.message for p in problems])
        ctx = checks.Ctx(g, self.env, kinds.registry(self.env, {"test": NoOverlay()}))
        code, problems = checks.staged_check(ctx)
        self.assertEqual(code, 0, [p.message for p in problems])

    def test_ignore_blocks(self):
        self.ready()
        self.assertEqual(self.stage().returncode, 0)
        ex = os.path.join(self.repo, ".git", "info", "exclude")
        with open(ex, "w") as f:
            f.write("")
        out = self.commit()
        self.assertIn("info/exclude lacks", out.stderr)
        self.assertEqual(self.hooks("install").returncode, 0)
        self.assertEqual(self.commit().returncode, 0)

    def test_gitignore_block_partial_stage(self):
        self.ready()
        blk = self.read(".gitignore")
        with open(os.path.join(self.repo, ".gitignore"), "w") as f:
            f.write("dist/\n" + blk.replace("/studio/out/\n", "/studio/out/\n/studio/tmp/\n"))
        env = dict(self.env)
        env[kinds.TEST_ENV] = "gitignore"
        out = self.stage(env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        staged = self.git("show", ":.gitignore").stdout
        self.assertIn("/studio/tmp/", staged)
        self.assertNotIn("dist/", staged)
        self.assertIn("dist/", self.read(".gitignore"))
        self.assertEqual(self.commit(env=env).returncode, 0)

    def test_restore_index_when_the_result_differs(self):
        self.ready()

        class Wrong(kinds.FolderKind):
            def collect(self, ctx, target):
                c = kinds.FolderKind.collect(self, ctx, target)
                c.paths = c.paths + ["studio/voices/a/ko.wav"]
                return c
        self.write("studio/voices/a/ko.wav", "wav")
        g = Git(self.repo, self.env)
        before = self.git("write-tree").stdout
        from stdo.commit import stage
        code, problems, _ = stage.run(checks.Ctx(g, self.env, kinds.registry(self.env, {"test": Wrong()})), "test", "v1")
        self.assertEqual(code, 1)
        self.assertTrue(any("outside the allow-list" in p.message for p in problems))
        self.assertEqual(self.git("write-tree").stdout, before)

    def test_inv7_paths_outside_every_kind(self):
        g = Git(self.repo, self.env)
        ctx = checks.Ctx(g, self.env, kinds.registry(self.env))
        probs = checks.kind_problems(ctx, "test", ["studio/voices/a/ko.wav", "studio/cast/a/character/x.png"])
        self.assertEqual(len(probs), 2)

    def test_sha256_repository(self):
        repo = os.path.join(self.tmp, "s256")
        os.makedirs(repo)
        out = self.git("init", "-q", "--object-format=sha256", cwd=repo, check=False)
        if out.returncode != 0:
            self.skipTest("git without sha256 support")
        import shutil
        for rel in (".claude/studio/config.json", ".gitignore"):
            os.makedirs(os.path.dirname(os.path.join(repo, rel)) or repo, exist_ok=True)
            shutil.copy(os.path.join(self.repo, rel), os.path.join(repo, rel))
        from commit_base import copy_scripts
        copy_scripts(repo)
        self.git("add", "-A", cwd=repo)
        self.git("commit", "-q", "-m", "init", cwd=repo)
        self.assertEqual(self.hooks("install", cwd=repo).returncode, 0)
        self.ready(repo=repo)
        out = self.cc("--stage", "test", "v1", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(okfile.read(repo)[0]["tree"]), 64)
        self.assertEqual(self.commit(cwd=repo).returncode, 0)


class Approvals(CommitCase):
    install_hook = False

    def test_light_check(self):
        vdir = self.video()
        self.assertEqual(approvals.light_check(vdir, "v1"), [])
        # an interrupted write
        with open(os.path.join(vdir, "work", "approvals.jsonl"), "a") as f:
            f.write(json.dumps({"seq": 99, "event": "approve"}) + "\n")
        msgs = [p.message for p in approvals.light_check(vdir, "v1")]
        self.assertTrue(any("interrupted" in m for m in msgs), msgs)

    def test_hand_edited_approval(self):
        vdir = self.video()
        p = os.path.join(vdir, "work", "state.json")
        st = json.load(open(p))
        st["langs"]["ko"]["approved"]["2"]["answer"] = {"answer": "forged"}
        json.dump(st, open(p, "w"))
        msgs = [p.message for p in approvals.light_check(vdir, "v1")]
        self.assertTrue(any("no matching approve event" in m for m in msgs), msgs)

    def test_missing_gate_held_proxy(self):
        vdir = self.video(skip_gate="4a")
        self.assertTrue(any("4a(youtube) is not approved" in p.message for p in approvals.light_check(vdir, "v1")))
        vdir = self.video(vid="v2", proxy=True)
        codes = {p.code for p in approvals.light_check(vdir, "v2")}
        self.assertEqual(codes, {4})
        vdir = self.video(vid="v3")
        p = os.path.join(vdir, "work", "state.json")
        st = json.load(open(p))
        st["langs"]["ko"]["held"] = {"state": "stagnation"}
        json.dump(st, open(p, "w"))
        self.assertTrue(any("held" in x.message for x in approvals.light_check(vdir, "v3")))

    def test_rework_of_2_does_not_pass_commit(self):
        """00-plan M0 test "② 재작업 뒤 옛 영상이 commit을 통과하지 못함" on check_commit's side."""
        vdir = self.video()
        st = store.read_state(vdir)
        self.assertEqual(approvals.full_check(st, "ko", F.current(), "v1"), [])
        probs = approvals.full_check(st, "ko", F.current(audio="a2"), "v1")
        self.assertTrue(probs and "redo" in probs[0].message, [p.message for p in probs])
        # the commit prepared before the rework is refused (the state changed)
        out = self.hooks("install")
        self.assertEqual(out.returncode, 0)
        self.overlay()
        self.assertEqual(self.cc("--stage", "test", "v1").returncode, 0)
        rec = dict(st["langs"]["ko"]["approved"]["2"], at="2026-10-22T00:00:00Z")
        store.record_approval(vdir, "ko", "2", rec)
        out = self.commit()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("changed since Studio prepared this commit", out.stderr)


class GuardRan(CommitCase):
    def test_claude_session_needs_the_record(self):
        self.ready()
        env = self.claude_env()
        out = self.cc("--stage", "test", "v1", env=env)
        self.assertEqual(out.returncode, 7, out.stderr)
        stage_msg = [l for l in out.stderr.splitlines() if "guard has not run" in l][0]
        self.guard_ran()
        self.assertEqual(self.cc("--stage", "test", "v1", env=env).returncode, 0)
        self.assertEqual(okfile.read(self.repo)[0]["session_id"], SID)
        # the hook: another session has no record -> 7 with the same sentence
        other = self.claude_env("sess-other")
        out = self.commit(env=other)
        self.assertNotEqual(out.returncode, 0)
        hook_msg = [l for l in out.stderr.splitlines() if "guard has not run" in l][0]
        self.assertEqual(stage_msg.replace("sess-com", "X"), hook_msg.replace("sess-oth", "X"))
        # empty session id
        e = self.claude_env("")
        self.assertEqual(self.cc("--staged", env=e).returncode, 7)
        # the same session (a subagent has the same id) passes once the guard recorded the answer (M0d-2)
        out = self.commit(env=env)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("did not see this commit being approved", out.stderr)
        self.guard_approved()
        self.assertEqual(self.commit(env=env).returncode, 0)

    def test_commit_ok_from_another_session(self):
        self.ready()
        self.guard_ran()
        p = os.path.join(self.repo, ".claude/studio/local/guard-ran.json")
        json.dump({"schema": 1, "sessions": {SID: "t", "sess-2": "t"}}, open(p, "w"))
        self.assertEqual(self.cc("--stage", "test", "v1", env=self.claude_env()).returncode, 0)
        out = self.commit(env=self.claude_env("sess-2"))
        self.assertIn("another Claude Code session", out.stderr)

    def test_person_outside_a_session(self):
        self.ready()
        self.assertEqual(self.cc("--stage", "test", "v1").returncode, 0)
        self.assertEqual(self.commit().returncode, 0)


class PythonMissing(CommitCase):
    def test_studio_path_without_python(self):
        bindir = os.path.join(self.tmp, "nopy")
        os.makedirs(bindir)
        for t in ("git", "tr", "grep", "sed", "head", "dirname", "cat", "sh", "awk", "cut"):
            for d in ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin"):
                if os.path.exists(os.path.join(d, t)):
                    os.symlink(os.path.join(d, t), os.path.join(bindir, t))
                    break
        env = dict(self.env)
        env["PATH"] = bindir
        self.write("studio/videos/v1/script.ko.md")
        self.git("add", "studio/videos/v1/script.ko.md")
        out = self.commit(env=env)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("python3 (3.9 or newer) is needed", out.stderr)
        # a missing text tool closes the hook too (it must not pass everything)
        os.remove(os.path.join(bindir, "awk"))
        out = self.commit(env=env)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("'awk' is not on PATH", out.stderr)
