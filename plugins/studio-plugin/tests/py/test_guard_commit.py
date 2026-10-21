"""M0d-2 §5–§6: Studio commits through the guard (commit-ok.json + the person's answer "커밋 <tree12>"),
the forms and settings that skip Studio's checks, plumbing and GitHub API writes, and `git push`.
Real git in temporary repositories only; the test commit kind stands in for the real kinds (M0f · M1 · M3b)."""

import json
import os
import subprocess

import transcripts as TR
from commit_base import SID, CommitCase
from stdo.commit import okfile
from stdo.guard import judge


class GuardCommit(CommitCase):
    def setUp(self):
        super().setUp()
        self.tpath = TR.transcript_path(self.env, SID)
        self.t = None

    def gate(self, cmd, cwd=None, extra=None, env=None):
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd or self.repo, "session_id": SID,
                "transcript_path": self.tpath, "permission_mode": "default", "tool_use_id": "toolu_cmd1",
                "prompt_id": self.t.prompt if self.t else "p-none"}
        hook.update(extra or {})
        return judge.decide(hook, env or self.env, snapshot_loader=lambda e: (None, ["snapshot-none"]))

    def staged(self):
        """An approved video staged by check_commit --stage in this session; returns commit-ok.json."""
        if not getattr(self, "_ready", False):
            self.ready()
            self._ready = True
        self.guard_ran()
        out = self.cc("--stage", "test", "v1", env=self.claude_env())
        self.assertEqual(out.returncode, 0, out.stderr)
        return okfile.read(self.repo)[0]

    def answer(self, label, qtext=None, **kw):
        """The person's answer; the question shows the summary line --stage printed (M0f) unless `qtext` is given."""
        ok, _ = okfile.read(self.repo)
        line = ok.get("summary") if ok and ok.get("label") == label else "%s | 변경 1" % label
        self.t = TR.approval_turn(TR.T(session_id=SID), label, qtext=qtext or "이 파일들을 커밋할까요?\n%s" % line,
                                  **kw)
        self.t.write(self.tpath)

    def assertGate(self, cmd, rule=None, allow=None, **kw):
        deny, ctx = self.gate(cmd, **kw)
        if rule:
            self.assertIsNotNone(deny, "should deny: %s" % cmd)
            self.assertEqual(deny.rule, rule, deny.message())
        else:
            self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
        if allow is not None:
            self.assertEqual(bool(ctx.allow), allow, cmd)
        return deny, ctx

    # --- the Studio commit ---
    def test_studio_commit_with_the_answer(self):
        ok = self.staged()
        self.answer(ok["label"])
        _d, ctx = self.assertGate('git commit -m "studio: v1"', allow=True)
        ap = okfile.read(self.repo)[0]["approval"]
        self.assertEqual((ap["mode"], ap["session_id"], ap["answer"], ap["tree"], ap["tool_use_id"]),
                         ("human", SID, ok["label"], ok["tree"], "toolu_ask1"))
        # the hook then sees the guard's record and the commit goes through
        out = self.commit("studio: v1", env=self.claude_env())
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_commit_with_the_current_call_written_late(self):
        """M0f U1/U5: the commit evidence uses the same transcript reading (end of file = now)."""
        ok = self.staged()
        self.answer(ok["label"])
        self.t.lines.pop()
        self.t.write(self.tpath)
        self.assertGate('git commit -m "studio: v1"', allow=True)

    def test_heredoc_message_is_still_one_command(self):
        ok = self.staged()
        self.answer(ok["label"])
        self.assertGate("git commit -m \"$(cat <<'EOF'\nstudio: v1\n\nbody\nEOF\n)\"", allow=True)
        self.assertGate("git commit -m \"$(cat ~/.ssh/x)\"", allow=False)
        self.assertGate("git commit -m \"$(date)\"", allow=False)

    def test_no_allow_for_changed_environment_or_other_git(self):
        ok = self.staged()
        self.answer(ok["label"])
        for cmd in ("PATH=/tmp/x:$PATH git commit -m x", "GIT_TRACE=1 git commit -m x", 'export X=1 && git commit -m x',
                    "git commit -m x && git push", "git commit -m x; echo ok", "env git commit -m x"):
            self.assertGate(cmd, allow=False)
        # review MJ-1: git options that run programs or change the repository — never allow
        for cmd in ("git -c gpg.program=/tmp/evil commit -S -m x", "git -c core.editor=/tmp/e commit -m x",
                    "git commit -e -m x", "git -c trailer.x.command=/tmp/t commit --trailer x=1 -m x",
                    "git -c commit.gpgsign=true commit -m x", "git -C %s commit -m x" % self.repo,
                    "git --git-dir=.git commit -m x", "git commit -S -m x", "git commit --template=/tmp/t -m x",
                    "git commit -m x -v", "git commit -qm x", "git commit -F - -m x"):
            self.assertGate(cmd, allow=False)
        self.assertGate("git -c include.path=/tmp/x.cfg commit -m x", "G-HOOKOFF")
        self.assertGate("git -c includeIf.gitdir:/x/.path=/tmp/x.cfg commit -m x", "G-HOOKOFF")
        # the whitelisted options keep the allow
        self.write("msg.txt", "studio: v1\n")
        for cmd in ("git commit -q -s --no-edit --cleanup=strip -m x", "git commit --message=x --allow-empty",
                    "git commit -F msg.txt", "git commit --file=msg.txt"):
            self.assertGate(cmd, allow=True)
        # review 2 MINOR-2: -F only from a regular file inside the repository
        os.symlink("/etc/hosts", os.path.join(self.repo, "outside.txt"))
        os.mkfifo(os.path.join(self.repo, "pipe.txt"))
        for cmd in ("git commit -F /etc/hosts", "git commit -F /dev/stdin", "git commit -F outside.txt",
                    "git commit -F pipe.txt", "git commit --file=/etc/hosts", "git commit -F missing.txt",
                    "git commit -F ~/.ssh/id_x"):
            self.assertGate(cmd, allow=False)
        # review 2 MINOR-1: a substituted message is a message, not a pathspec (no decision, no deny)
        for cmd in ("git commit -m\"$(cat <<'EOF'\nstudio: v1\nEOF\n)\"", "git commit --message=\"$(date)\""):
            self.assertGate(cmd, allow=False)
        fake = os.path.join(self.tmp, "fakegit")
        os.makedirs(fake)
        self.exe(os.path.join(fake, "git"), "#!/bin/sh\nexit 0\n")
        self.assertGate("%s/git commit -m x" % fake, allow=False)

    def test_no_answer_or_wrong_answer(self):
        ok = self.staged()
        self.assertGate("git commit -m x", "G-EVIDENCE")
        self.answer("커밋 000000000000")
        self.assertGate("git commit -m x", "G-EVIDENCE")
        self.answer(ok["label"], chosen="수정해 줘")
        self.assertGate("git commit -m x", "G-EVIDENCE")
        self.answer(ok["label"], qtext="이 파일들을 커밋할까요?")  # the summary line (with tree12) was not shown
        self.assertGate("git commit -m x", "G-EVIDENCE")
        self.answer(ok["label"], qtext="커밋할까요? %s" % ok["summary"].replace("변경 ", "변경 1"))  # one digit off
        self.assertGate("git commit -m x", "G-EVIDENCE")
        self.assertIsNone(okfile.read(self.repo)[0]["approval"])

    def test_commit_ok_must_match(self):
        self.assertGate("git commit -m x")  # nothing staged: not a Studio commit
        ok = self.staged()
        self.answer(ok["label"])
        os.remove(okfile.path(self.repo))
        d, _ = self.assertGate("git commit -m x", "G-COMMIT")
        self.assertIn("did not prepare", d.message())
        ok = self.staged()
        self.answer(ok["label"])
        self.write("studio/videos/v1/script.ko.md", "# changed after staging\n")
        self.git("add", "studio/videos/v1/script.ko.md")
        d, _ = self.assertGate("git commit -m x", "G-COMMIT")
        self.assertIn("staged tree", d.message())
        # HEAD moved (an empty commit made outside the index): the tree is the same, the head is not
        ok = self.staged()
        self.answer(ok["label"])
        new = self.git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "elsewhere").stdout.strip()
        self.git("update-ref", "HEAD", new)
        d, _ = self.assertGate("git commit -m x", "G-COMMIT")
        self.assertIn("HEAD moved", d.message())
        # another session's commit-ok
        ok = self.staged()
        self.answer(ok["label"])
        data = json.load(open(okfile.path(self.repo)))
        data["session_id"] = "sess-other"
        json.dump(data, open(okfile.path(self.repo), "w"))
        self.assertGate("git commit -m x", "G-COMMIT")

    def test_old_runner_is_refused(self):
        """M0f review MINOR-3: a clone whose runner predates M0f (v1) or has none cannot make a Studio commit."""
        ok = self.staged()
        self.answer(ok["label"])
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        rp = os.path.join(common, "studio", "pre-commit")
        with open(rp) as f:
            text = f.read()
        with open(rp, "w") as f:
            f.write(text.replace("studio:hook v2 ", "studio:hook v1 "))
        d, _ = self.assertGate("git commit -m x", "G-COMMIT")
        self.assertIn("hooks.py install", d.message())
        os.remove(rp)
        self.assertGate("git commit -m x", "G-COMMIT")
        with open(rp, "w") as f:
            f.write(text)
        self.assertGate("git commit -m x", allow=True)

    def test_subagent_cannot_commit_studio(self):
        ok = self.staged()
        self.answer(ok["label"])
        self.assertGate("git commit -m x", "G-MAIN", extra={"agent_id": "a", "agent_type": "general-purpose"})

    def test_forms_that_skip_the_checks(self):
        self.staged()
        for cmd in ("git commit -a -m x", "git commit -am x", "git commit -m x studio/videos/v1/script.ko.md",
                    "git commit -i -m x src/a.ts", "git commit --only -m x studio", "git commit --amend -m x",
                    "git commit --no-verify -m x", "git commit -n -m x", "git commit --fixup=amend:HEAD",
                    "git commit --pathspec-from-file=list.txt -m x"):
            self.assertGate(cmd, "G-COMMITFORM")

    def test_forms_pass_without_studio_changes(self):
        self.write("src/a.ts", "a\n")
        self.git("add", "src/a.ts")
        self.git("commit", "-q", "-m", "src")
        self.write("src/a.ts", "b\n")
        self.write("studio/videos/v9/notes.md", "untracked studio file\n")
        for cmd in ("git commit -a -m x", "git commit -m x src/a.ts", "git commit --amend -m x",
                    "git commit --no-verify -m x", "git commit -m 'fix: x'"):
            self.assertGate(cmd, allow=False)
        # a tracked Studio change makes -a a Studio commit; a pathspec elsewhere still passes
        self.write("studio/voices/.keep", "")
        self.git("add", "studio/voices/.keep")
        self.git("commit", "-q", "--no-verify", "-m", "studio keep")
        self.write("studio/voices/.keep", "changed\n")
        self.assertGate("git commit -a -m x", "G-COMMITFORM")
        self.assertGate("git commit -m x src/a.ts", allow=False)
        self.assertGate("git commit --amend -m x", "G-COMMITFORM")  # HEAD is a Studio commit

    def test_hook_disabling_environment_and_settings(self):
        for cmd in ("HUSKY=0 git commit -m x", "export LEFTHOOK=0 && git commit -m x", "env SKIP=x git commit -m x",
                    "SKIP_SIMPLE_GIT_HOOKS=1 git commit -m x", "GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='/x'\" git commit -m x",
                    "GIT_INDEX_FILE=/tmp/i git commit -m x", "git -c core.hooksPath=/dev/null commit -m x",
                    "git -c alias.ci=commit ci -m x", "git --config-env=core.hooksPath=X commit -m x",
                    "git config core.hooksPath /dev/null", "git config --unset core.hooksPath",
                    "git config --local core.hooksPath x", "git config alias.c 'commit --no-verify'",
                    "git config set core.hooksPath x", "git config --edit", "echo '[core]' >> .git/config",
                    "git config include.path /tmp/x.cfg", "git config --add Include.Path /tmp/x.cfg",
                    "git config --unset core.hooksPath", "git config unset alias.c",
                    "git config includeIf.gitdir:~/x/.path /tmp/x.cfg", "git -c include.path=/tmp/x status",
                    "git --exec-path=/tmp/x commit -m x"):
            self.assertGate(cmd, "G-HOOKOFF")
        for cmd in ("git config user.email a@b.c", "git config --get core.hooksPath", "git config --list",
                    "git commit -m 'docs: mention --exec-path and -c core.hooksPath'", "git --exec-path",
                    "git config --get include.path", "git config --unset include.path",
                    "git config --unset-all includeIf.gitdir:/x/.path", "git config unset include.path",
                    "git config get core.hooksPath", "cat .git/config"):
            self.assertGate(cmd, allow=False)

    def test_global_include_message_sends_the_person_to_a_terminal(self):
        d, _ = self.assertGate("git config --global include.path /tmp/x.cfg", "G-HOOKOFF")
        self.assertIn("themselves in a terminal", d.message())

    def test_marker_matters_in_the_target_repository(self):
        other = os.path.join(self.tmp, "plain")
        os.makedirs(other)
        subprocess.run(["git", "init", "-q", other], check=True, env=self.env)
        # cwd is a plain repository, the commit targets the Studio repository (git -C)
        self.assertGate("git -C %s -c core.hooksPath=/dev/null commit -m x" % self.repo, "G-HOOKOFF", cwd=other)
        self.assertGate("HUSKY=0 git -C %s commit -m x" % other, cwd=other)
        ok = self.staged()
        self.answer(ok["label"])
        self.assertGate("git -C %s commit -m x" % self.repo, cwd=other)

    def test_plumbing_and_github_api(self):
        for cmd in ("git commit-tree HEAD^{tree} -m x", "git update-ref refs/heads/main HEAD",
                    "git symbolic-ref HEAD refs/heads/x", "git read-tree HEAD", "git update-index --add studio/a",
                    "git apply --cached p.diff", "gh api -X PUT repos/o/r/contents/studio/a.md -f content=x",
                    "gh api repos/o/r/contents/studio/a.md -f message=x", "gh api --method=PATCH /repos/o/r/contents/.claude/studio/config.json",
                    "gh api -X PUT 'repos/{owner}/{repo}/contents/studio%2Fa.md'", "gh api repos/o/r/git/trees -f base_tree=x",
                    "gh api graphql -f query='mutation { createCommitOnBranch(input: {}) { commit { url } } }'",
                    "gh api graphql -F query=@q.graphql"):
            self.assertGate(cmd, "G-PLUMB")
        for cmd in ("git update-index --refresh", "git symbolic-ref HEAD", "gh api repos/o/r/contents/studio/a.md",
                    "gh api -X PUT repos/o/r/contents/docs/a.md -f content=x", "gh api repos/o/r/pulls",
                    "gh api graphql -f query='{ viewer { login } }'"):
            self.assertGate(cmd, allow=False)

    def test_marker_only_repo_gets_hook_rules_but_no_evidence(self):
        other = os.path.join(self.tmp, "plain2")
        os.makedirs(other)
        subprocess.run(["git", "init", "-q", other], check=True, env=self.env)
        self.assertGate("HUSKY=0 git commit -m x", cwd=other)
        self.assertGate("git commit-tree x", cwd=other)


    def test_studio_commit_judgement_time(self):
        import sys
        import time
        ok = self.staged()
        self.answer(ok["label"])
        times = []
        for _ in range(7):
            s = time.monotonic()
            deny, ctx = self.gate('git commit -m "studio: v1"')
            times.append(time.monotonic() - s)
            self.assertTrue(ctx.allow, deny and deny.message())
        times.sort()  # p50 is asserted; the max only loosely (machines under load)
        print("\n[perf] %s: Studio commit judgement (git calls in-process) p50 %.0f ms max %.0f ms"
              % (sys.version.split()[0], times[3] * 1000, times[-1] * 1000))
        self.assertLess(times[3], 0.4)
        self.assertLess(times[-1], 1.5)


class GuardPush(CommitCase):
    install_hook = False

    def setUp(self):
        super().setUp()
        self.remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", self.remote], check=True, env=self.env)
        self.git("remote", "add", "origin", self.remote)
        self.git("push", "-q", "-u", "origin", "main")

    def gate(self, cmd):
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.repo, "session_id": SID,
                "transcript_path": None, "permission_mode": "default", "tool_use_id": "t", "prompt_id": "p"}
        return judge.decide(hook, self.env, snapshot_loader=lambda e: (None, ["snapshot-none"]))

    def add_commit(self, rel, msg, force=False):
        self.write(rel, msg + "\n")
        self.git("add", *(["-f"] if force else []), rel)
        self.git("commit", "-q", "--no-verify", "-m", msg)

    def test_local_file_in_the_pushed_history_is_refused(self):
        self.add_commit("studio/local/videos/w/script.md", "leak", force=True)
        self.git("rm", "-q", "--cached", "studio/local/videos/w/script.md")
        self.git("commit", "-q", "--no-verify", "-m", "remove again")
        deny, _ = self.gate("git push")
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, "G-PUSH")
        self.assertIsNone(self.gate("git push --dry-run")[0])

    def test_merged_videos_of_others_push_freely(self):
        """00-plan M0 test: develop has another video; after merge/rebase the push is not blocked."""
        self.git("checkout", "-q", "-b", "develop")
        self.add_commit("studio/videos/other/script.ko.md", "another person's video")
        self.git("push", "-q", "-u", "origin", "develop")
        self.git("checkout", "-q", "main")
        self.add_commit("src/a.ts", "my work")
        self.git("merge", "-q", "--no-edit", "develop")
        deny, ctx = self.gate("git push")
        self.assertIsNone(deny, deny and deny.message())
        self.assertEqual(ctx.warnings, [])
        self.git("checkout", "-q", "-b", "feature")
        self.git("rebase", "-q", "develop")
        deny, ctx = self.gate("git push -u origin feature")
        self.assertIsNone(deny, deny and deny.message())

    def test_mixed_commit_warns(self):
        self.write("src/b.ts", "b\n")
        self.write("studio/videos/v2/script.ko.md", "s\n")
        self.git("add", "src/b.ts", "studio/videos/v2/script.ko.md")
        self.git("commit", "-q", "--no-verify", "-m", "mixed")
        deny, ctx = self.gate("git push")
        self.assertIsNone(deny)
        self.assertTrue(any("mixes" in w for w in ctx.warnings), ctx.warnings)
        deny, ctx = self.gate("git push --all")
        self.assertIsNone(deny)
        self.assertTrue(any("mixes" in w for w in ctx.warnings), ctx.warnings)  # every pushed branch is checked

    def leak(self, branch=None):
        if branch:
            self.git("checkout", "-q", "-b", branch)
        self.add_commit("studio/local/videos/w/script.md", "leak", force=True)

    def test_h5_explicit_refspec_without_upstream(self):
        """Sandbox H5: `git push origin HEAD:main` from a branch with no upstream (and no origin/HEAD)."""
        self.leak("work")
        self.assertIsNone(self.git("rev-parse", "-q", "--verify", "refs/remotes/origin/HEAD", check=False).stdout.strip()
                          or None)
        for cmd in ("git push origin HEAD:main", "git push origin work:refs/heads/main", "git push origin +HEAD:main"):
            deny, _ = self.gate(cmd)
            self.assertIsNotNone(deny, cmd)
            self.assertEqual(deny.rule, "G-PUSH", deny.message())
            self.assertIn("machine-only", deny.message())

    def test_leak_already_on_another_remote_branch_reaching_main(self):
        """The base is the destination's remote branch: a leak already on origin/side still counts when it goes to
        main (a fallback over every remote ref would miss it)."""
        self.leak("side")
        self.git("push", "-q", "origin", "side")
        self.git("checkout", "-q", "-b", "work")
        self.add_commit("src/w.ts", "work")
        deny, _ = self.gate("git push origin HEAD:main")
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, "G-PUSH")
        # a plain branch with its own remote branch (no upstream): based on origin/work, the leak counts too
        self.git("checkout", "-q", "main")
        self.git("checkout", "-q", "-b", "w2")
        self.add_commit("src/w2.ts", "w2")
        self.git("push", "-q", "origin", "w2")  # no -u
        self.git("merge", "-q", "--no-edit", "side")
        deny, _ = self.gate("git push origin w2")
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, "G-PUSH")

    def test_plain_branch_with_a_remote_branch_but_no_upstream(self):
        self.git("checkout", "-q", "-b", "work")
        self.add_commit("src/w.ts", "work")
        self.git("push", "-q", "origin", "work")  # no -u
        self.add_commit("studio/local/videos/w/script.md", "leak", force=True)
        deny, _ = self.gate("git push origin work")
        self.assertEqual(deny.rule, "G-PUSH")

    def test_new_remote_branch(self):
        self.git("checkout", "-q", "-b", "fresh")
        self.write("src/f.ts", "f\n")
        self.write("studio/videos/v3/script.ko.md", "s\n")
        self.git("add", "src/f.ts", "studio/videos/v3/script.ko.md")
        self.git("commit", "-q", "--no-verify", "-m", "mixed on a new branch")
        deny, ctx = self.gate("git push -u origin fresh")
        self.assertIsNone(deny, deny and deny.message())
        self.assertEqual(sum("mixes" in w for w in ctx.warnings), 1, ctx.warnings)  # only the new commit
        self.add_commit("studio/local/videos/w/script.md", "leak", force=True)
        self.assertEqual(self.gate("git push -u origin fresh")[0].rule, "G-PUSH")

    def test_all_and_tags_are_checked_per_ref(self):
        self.leak("side")
        self.git("checkout", "-q", "main")
        self.add_commit("src/m.ts", "main work")
        self.assertIsNone(self.gate("git push")[0])  # main itself is clean
        self.assertEqual(self.gate("git push --all")[0].rule, "G-PUSH")
        self.assertEqual(self.gate("git push --mirror")[0].rule, "G-PUSH")
        self.git("tag", "t1", "side")
        self.assertEqual(self.gate("git push --tags")[0].rule, "G-PUSH")
        self.assertEqual(self.gate("git push origin main side")[0].rule, "G-PUSH")
        self.assertIsNone(self.gate("git push origin :old-branch")[0])  # deleting a remote branch sends nothing

    def test_delete_and_configured_refspecs(self):
        """Review: --delete sends nothing; a bare push follows push.default=matching or remote.<r>.push."""
        self.assertIsNone(self.gate("git push --delete origin old")[0])
        self.assertIsNone(self.gate("git push origin -d old")[0])
        self.git("checkout", "-q", "-b", "side")
        self.add_commit("src/s.ts", "side")
        self.git("push", "-q", "origin", "side")
        self.add_commit("studio/local/videos/w/script.md", "leak", force=True)
        self.git("checkout", "-q", "main")
        self.assertIsNone(self.gate("git push")[0])  # simple: only main
        self.git("config", "push.default", "matching")
        self.assertEqual(self.gate("git push")[0].rule, "G-PUSH")
        self.git("config", "--unset", "push.default")
        self.git("config", "remote.origin.push", "refs/heads/side:refs/heads/side")
        self.assertEqual(self.gate("git push")[0].rule, "G-PUSH")
        self.git("config", "remote.origin.push", "refs/heads/*:refs/heads/*")
        d = self.gate("git push")[0]
        self.assertEqual(d.rule, "G-PUSH")
        self.assertIn("pattern", d.message())

    def test_first_publish_checks_local_paths_only(self):
        from stdo.guard import push
        fresh = os.path.join(self.tmp, "fresh.git")
        subprocess.run(["git", "init", "-q", "--bare", fresh], check=True, env=self.env)
        self.git("remote", "add", "fresh", fresh)
        self.git("checkout", "-q", "-b", "pub")
        for i in range(4):
            self.add_commit("src/p%d.ts" % i, "p%d" % i)
        old = push.MAX_COMMITS
        push.MAX_COMMITS = 2
        try:
            deny, ctx = self.gate("git push fresh pub")
            self.assertIsNone(deny, deny and deny.message())
            self.assertTrue(any("only machine-only and internal files were checked" in w for w in ctx.warnings),
                            ctx.warnings)
            self.add_commit("studio/local/videos/w/script.md", "leak", force=True)
            deny, _ = self.gate("git push fresh pub")
            self.assertEqual(deny.rule, "G-PUSH")
            self.assertIn("from a terminal", deny.message())
        finally:
            push.MAX_COMMITS = old

    def leak_on_origin(self):
        """A machine-only file already on origin/main (someone pushed it earlier): origin's base hides it."""
        self.add_commit("studio/local/videos/w/script.md", "old leak", force=True)
        self.git("push", "-q", "origin", "main")
        public = os.path.join(self.tmp, "public.git")
        subprocess.run(["git", "init", "-q", "--bare", public], check=True, env=self.env)
        return public

    def test_target_remote_is_the_base(self):
        """Review MAJOR-1: the base comes from the remote actually pushed to, never origin's upstream."""
        public = self.leak_on_origin()
        self.assertIsNone(self.gate("git push")[0])  # origin already has it: nothing new for origin
        for cmd in ("git push %s main" % public, "git push --repo=%s HEAD" % public, "git push --repo %s" % public):
            deny, _ = self.gate(cmd)
            self.assertIsNotNone(deny, cmd)
            self.assertEqual(deny.rule, "G-PUSH", cmd)
        self.git("remote", "add", "public", public)
        self.git("config", "remote.pushDefault", "public")
        self.assertEqual(self.gate("git push")[0].rule, "G-PUSH")
        self.git("config", "--unset", "remote.pushDefault")
        self.git("config", "branch.main.pushRemote", "public")
        self.assertEqual(self.gate("git push")[0].rule, "G-PUSH")
        self.git("config", "--unset", "branch.main.pushRemote")
        self.assertIsNone(self.gate("git push")[0])

    def test_pushurl_elsewhere_is_a_url_target(self):
        """origin fetches one place and pushes to another: its tracking refs say nothing about the push target."""
        public = self.leak_on_origin()
        self.assertIsNone(self.gate("git push")[0])
        self.git("config", "remote.origin.pushurl", public)
        deny, _ = self.gate("git push")
        self.assertIsNotNone(deny)
        self.assertEqual(deny.rule, "G-PUSH")

    def evil_merge(self):
        self.git("checkout", "-q", "-b", "b1")
        self.add_commit("src/b1.ts", "b1")
        self.git("checkout", "-q", "main")
        self.add_commit("src/m1.ts", "m1")
        self.git("merge", "-q", "--no-ff", "--no-commit", "b1")
        self.write("studio/local/videos/w/evil.md", "only in the merge\n")
        self.git("add", "-f", "studio/local/videos/w/evil.md")
        self.git("commit", "-q", "--no-verify", "-m", "evil merge")

    def test_evil_merge_is_seen(self):
        """A machine-only file added only by a merge commit: both the commit-by-commit path and the over-the-cap
        `git log -m` path see it."""
        from stdo.guard import push
        self.evil_merge()
        self.assertEqual(self.gate("git push")[0].rule, "G-PUSH")  # rangecheck: differs from every parent
        old = push.MAX_COMMITS
        push.MAX_COMMITS = 1
        try:
            deny, _ = self.gate("git push")
            self.assertIsNotNone(deny)
            self.assertIn("evil.md", deny.message())
        finally:
            push.MAX_COMMITS = old

    def test_ignorecase_paths_over_the_cap(self):
        from stdo.guard import push
        self.git("config", "core.ignorecase", "true")
        self.git("checkout", "-q", "-b", "case")
        self.add_commit("src/c0.ts", "c0")
        self.add_commit("src/c1.ts", "c1")
        self.add_commit("studio/LOCAL/videos/w/x.md", "case leak", force=True)
        old = push.MAX_COMMITS
        push.MAX_COMMITS = 1
        try:
            deny, _ = self.gate("git push origin case")
            self.assertIsNotNone(deny)
            self.assertEqual(deny.rule, "G-PUSH")
        finally:
            push.MAX_COMMITS = old

    def test_follow_tags_keeps_the_branch(self):
        """Review MAJOR-2: --follow-tags pushes the branch too."""
        self.add_commit("studio/local/videos/w/script.md", "leak", force=True)
        self.assertEqual(self.gate("git push --follow-tags")[0].rule, "G-PUSH")
        self.assertEqual(self.gate("git push origin main --follow-tags")[0].rule, "G-PUSH")

    def test_over_the_cap_checks_internal_ids_too(self):
        """Review MAJOR-3: the single git log of the over-the-cap path covers internal video/actor folders."""
        from stdo.guard import push
        self.overlay()
        p = os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json")
        with open(p, "w") as f:
            json.dump({"internal": {"videos": ["onboard-x"], "actors": ["staff-a"]}}, f)
        self.overlay_sha(p)
        self.git("checkout", "-q", "-b", "big")
        for i in range(3):
            self.add_commit("src/b%d.ts" % i, "b%d" % i)
        self.add_commit("studio/cast/staff-a/profile.md", "internal actor")
        old = push.MAX_COMMITS
        push.MAX_COMMITS = 2
        try:
            deny, _ = self.gate("git push origin big")
            self.assertIsNotNone(deny)
            self.assertIn("staff-a", deny.message())
        finally:
            push.MAX_COMMITS = old

    def test_unclear_or_too_many_is_refused(self):
        from stdo.guard import push
        self.git("checkout", "-q", "-b", "many")
        for i in range(5):
            self.add_commit("src/n%d.ts" % i, "n%d" % i)
        old = push.MAX_COMMITS
        push.MAX_COMMITS = 3
        try:
            deny, ctx = self.gate("git push origin many")  # over the cap: the local-path check only, a warning
            self.assertIsNone(deny, deny and deny.message())
            self.assertTrue(any("only machine-only and internal files" in w for w in ctx.warnings), ctx.warnings)
        finally:
            push.MAX_COMMITS = old
        self.assertIsNone(self.gate("git push origin many")[0])
        self.assertEqual(self.gate('git push origin "$BRANCH"')[0].rule, "G-PUSH")
        self.assertEqual(self.gate("git push origin nosuch:main")[0].rule, "G-PUSH")

    def test_internal_video_id(self):
        self.overlay()
        p = os.path.join(self.repo, ".claude", "studio", "local", "config.internal.json")
        with open(p, "w") as f:
            json.dump({"internal": {"videos": ["onboard-x"]}}, f)
        self.overlay_sha(p)
        self.add_commit("studio/videos/onboard-x/script.ko.md", "internal video in the public folder")
        deny, _ = self.gate("git push")
        self.assertIsNotNone(deny)
        self.assertIn("internal video onboard-x", deny.message())

    def overlay_sha(self, p):
        import hashlib
        from stdo import paths
        with open(p, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        d = os.path.join(paths.backup_root(), paths.repo_key(self.repo))
        with open(os.path.join(d, "overlay.sha"), "w") as f:
            f.write(sha + "\n")
