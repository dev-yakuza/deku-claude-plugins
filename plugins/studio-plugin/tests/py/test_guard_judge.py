"""M0d-1b judgement (m0d1b-plan v2 §6, §10): must-deny and must-pass lists, git previews, env rules,
approvals, Write/Edit/MCP, out-of-repo files. Real git only in temporary repositories."""

import json
import os
import shutil

import helpers
from guard_base import DEFAULT_ALIASES, GuardCase, snapshot_text
from stdo import SCRIPTS_VERSION, paths
from stdo.guard import judge
from stdo.guard import snapshot as snapmod

FAKE_TOOLS = ("npm", "yarn", "pnpm", "make", "npx", "node", "gh", "python3", "rg", "s2v", "ffprobe", "open",
              "tsc", "curl", "jq", "tree", "trash")
ALIASES = DEFAULT_ALIASES + [("gst", "'git status'")]


class JudgeCase(GuardCase):
    def setUp(self):
        super().setUp()
        for t in FAKE_TOOLS:
            if not os.path.exists(os.path.join(self.bin, t)):
                self.exe(t)
        self.env["PATH"] = self.bin + ":/usr/bin:/bin"
        os.remove(os.path.join(self.bin, "git"))
        git = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
        os.symlink(git, os.path.join(self.bin, "git"))
        self.repo = helpers.make_repo(self.tmp, name="studio-repo", harness=True)
        for d in ("studio/videos/v/work", "studio/local/videos/w/work", "studio/cast/a/character", "studio/voices/a",
                  "studio/videos/v/audio/ko", "src", ".claude/studio/scripts/stdo", "scripts", "node_modules", "dist"):
            os.makedirs(os.path.join(self.repo, d), exist_ok=True)
        for f, text in (("studio/videos/v/work/state.json", "{}"), ("studio/videos/v/script.md", "# s\n"),
                        ("src/a.ts", "x\n"), ("src/x.ts", "x\n"), ("a.txt", "a\n"), ("studio/CREDITS.yaml", "[]\n"),

                        ("scripts/x.py", "print(1)\n"), ("scripts/release.sh", "echo release\n"),
                        ("studio/cast/a/character/character.yaml", "a: 1\n")):
            p = os.path.join(self.repo, f)
            with open(p, "w") as fh:
                fh.write(text)
        # the repository copy of Studio's scripts: the plugin's own files (the guard checks the copy's version and
        # manifest on every Studio command — D-M0-3, M0f)
        from commit_base import copy_scripts
        copy_scripts(self.repo)
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "-m", "fixture files")
        self.snap_with = self.make_snapshot()
        self.mode = "with"

    def make_snapshot(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
            f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"]))
        snap = snapmod.load(self.env)
        shutil.rmtree(d)
        return snap

    def loader(self, env):
        return self.snap_with if self.mode == "with" else (None, ["snapshot-none"])

    def hook(self, tool, ti, cwd=None):
        return {"tool_name": tool, "tool_input": ti, "cwd": cwd or self.repo, "session_id": "sess-1",
                "transcript_path": None, "permission_mode": "default", "tool_use_id": "t1"}

    def decide(self, tool, ti, cwd=None, probe=None):
        deny, ctx = judge.decide(self.hook(tool, ti, cwd), self.env, probe=probe, snapshot_loader=self.loader)
        return deny

    def bash(self, cmd, cwd=None, **kw):
        return self.decide("Bash", {"command": cmd}, cwd, **kw)

    def assertDeny(self, cmd, rule=None, cwd=None):
        d = self.bash(cmd, cwd)
        self.assertIsNotNone(d, "should deny: %s (%s)" % (cmd, self.mode))
        if rule:
            self.assertEqual(d.rule, rule, "%s: %s" % (cmd, d.message()))
        return d

    def assertPass(self, cmd, cwd=None):
        d = self.bash(cmd, cwd)
        self.assertIsNone(d, "should pass: %s (%s): %s" % (cmd, self.mode, d and d.message()))


MUST_DENY = [
    ("echo x > studio/videos/v/work/state.json", "G-PROT"),
    ("sed -i '' s/a/b/ .claude/studio/config.json", "G-PROT"),
    ("cp a.txt studio/voices/x.wav", "G-PROT"),
    ("rm -rf studio/local", "G-DEL"),
    ("rm -rf studio", "G-DEL"),
    ("rm -rf *", "G-DEL"),
    ("mv studio/local /tmp/x", "G-DEL"),
    ("find studio -delete", "G-DEL"),
    ("find studio -name x -exec rm {} +", "G-DEL"),
    ("find studio/voices -execdir mv {} /tmp \\;", "G-DEL"),
    ("rsync -a --delete src/ ./", "G-DEL"),
    ("git stash -a", "G-STASH"),
    ("git add -f studio/local/x", "G-PROT"),
    ("git checkout -- studio/videos/v/work/state.json", "G-PROT"),
    ("python3 -c \"import shutil; shutil.rmtree('studio/local')\"", "G-OPAQUE"),
    ("bash -c 'rm -rf studio/local'", "G-DEL"),  # M1a W2: the string's commands are judged too
    ("cat > /tmp/gx.sh <<'EOF'\nrm -rf studio/local\nEOF\nbash /tmp/gx.sh", "G-DEL"),  # M1a X1: script files too
    ('eval "rm studio/x"', "G-OPAQUE"),
    ("X=$(echo s); rm -rf $X/local", "G-DEL"),
    ("S2V_TTS_PORT=1 s2v tts v.md", "G-ENV"),
    ("env -i s2v x", "G-ENV"),
    ("HOME=/tmp/x s2v x", "G-ENV"),
    ("S2V_STATE_DIR=/elsewhere s2v x", "G-ENV"),
    ("export S2V_HEAVY_LOCK_TOKEN=a; s2v tts v.md", "G-ENV"),
    ("unset S2V_TTS; s2v x", "G-ENV"),
    ("env -u S2V_ACTOR_LOCK_TOKEN s2v x", "G-ENV"),
    ("python3 .claude/studio/scripts/state.py approve v 1 --expect abc", "G-APPROVAL"),
    ("python3 .claude/studio/scripts/state.py credit x --expect a", "G-APPROVAL"),
    ("python3 .claude/studio/scripts/state.py frobnicate", "G-APPROVAL"),
    ("python3 .claude/studio/scripts/state.py next $V", "G-DYNARG"),
    ("python3 .claude/studio/scripts/lock.py actor-op a -- s2v character approve a", "G-APPROVAL"),
    ("python3 .claude/studio/scripts/lock.py run --kind tts -- cp a.txt studio/videos/v/work/state.json", "G-PROT"),
    ("s2v character build a --reset-derived", "G-APPROVAL"),
    ("s2v voice create a --candidates 1", "G-APPROVAL"),
    ("unset CLAUDE_CODE_SESSION_ID; git commit -m x", "G-MARKER"),
    ("env -u CLAUDECODE python3 .claude/studio/scripts/check_commit.py --staged", "G-MARKER"),
    ("STUDIO_SANDBOX=1 s2v x", "G-ENV"),
    ("STUDIO_HOME=/tmp/h s2v x", "G-ENV"),
    ("python3 - <<EOF\nopen('studio/videos/v/work/state.json','w')\nEOF", "G-OPAQUE"),
    ("bash -c 'cd studio && ls'", "G-OPAQUE"),
    ("python3 scripts/x.py studio/videos/v/work/state.json", "G-PROT"),
    ("dd if=/dev/zero of=studio/videos/v/work/state.json", "G-PROT"),
    ("cp --target-directory=studio/voices a.txt", "G-PROT"),
    ("rsync --backup-dir=studio/voices/b -a src/ dist/", "G-PROT"),
    ("tar --directory=studio/cast -xf a.tar", "G-PROT"),
    ("tar -xf a.tar -C studio/voices", "G-PROT"),
    ("cp a.txt studio/cast/a/character/", "G-PROT"),
    ("cp -t studio/voices a.txt", "G-PROT"),
    ("cp dist/state.json studio/videos/v/work/", "G-PROT"),
    ("echo x > studio/CREDITS.yaml", "G-PROT"),
    ("touch .claude/studio/charter.md", "G-PROT"),
]
NO_SNAPSHOT_DENY = ["g st", "gst", "ll", "take newdir", "g clean -fdx"]

MUST_PASS = [
    "git status", "git diff", "git log --oneline -5", "git add src/x.ts", "git add -A", "git commit -m 'fix: x'",
    "git push", "git pull --rebase", "git checkout -b feat/x", "git switch main", "git stash", "git stash pop",
    "git clean -n", "git clean -fd src/", "git reset --hard", "git fetch", "gh pr create --fill", "gh pr view 12",
    "npm test", "yarn build", "pnpm lint", "make", "npx tsc --noEmit", "python3 -m pytest", "node scripts/build.js",
    "ls -la studio", "cat studio/videos/v/work/state.json", "grep -r foo studio", "rg foo", "find . -name '*.md'",
    "find studio -name '*.md'", "cp src/a.ts src/b.ts", "mkdir -p src/x", "rm -rf node_modules dist", "rm src/a.ts",
    "mv a.txt b.txt", "sed -i '' s/a/b/ src/x.ts", "cat > src/y.ts <<'EOF'\nx\nEOF", "echo x > notes.md",
    "tee README.md < /dev/null", "touch studio/videos/v/script.md", "echo x >> studio/local/videos/w/notes.md",
    "python3 -c 'print(1)'", "python3 - <<'EOF'\nimport json\nEOF", "node -e 'console.log(1)'", "bash scripts/release.sh",
    "python3 .claude/studio/scripts/state.py next v", "python3 .claude/studio/scripts/state.py status",
    "python3 .claude/studio/scripts/lock.py status --json",
    "python3 .claude/studio/scripts/lock.py run --kind tts -- s2v tts studio/videos/v/script.md",
    "s2v --version --json", "s2v inspect --json studio/videos/v/script.md", "S2V_TTS=mock node test.js",
    "find . -name '*.json' -exec grep -l x {} +", "curl -o /tmp/x.json https://example.invalid/a",
    "cp a.txt studio/videos/v/", "tar -xf a.tar -C dist", "dd if=a.txt of=dist/b.txt",
]
WITH_SNAPSHOT_PASS = ["g st", "gst", "ll", "grep foo src", "find . -name x", "take newdir"]


class MustDeny(JudgeCase):
    def test_must_deny_with_and_without_snapshot(self):
        for mode in ("with", "none"):
            self.mode = mode
            for cmd, rule in MUST_DENY:
                self.assertDeny(cmd, rule)

    def test_no_snapshot_aliases_are_unknown(self):
        self.mode = "none"
        for cmd in NO_SNAPSHOT_DENY:
            d = self.assertDeny(cmd, "G-UNKNOWN")
            self.assertIn("shell snapshot", d.message())

    def test_owner_json(self):
        st = self.env["S2V_STATE_DIR"]
        os.makedirs(os.path.join(st, "heavy.lock.d"), exist_ok=True)
        self.assertDeny("cat %s/heavy.lock.d/owner.json" % st, "G-OUT")
        self.assertDeny("cat studio/cast/a/character/.work/op.lock.d/owner.json", "G-OUT")
        del self.env["S2V_STATE_DIR"]
        os.makedirs(os.path.join(self.env["HOME"], ".s2v", "heavy.lock.d"), exist_ok=True)
        self.assertDeny("cat ~/.s2v/heavy.lock.d/owner.json", "G-OUT")

    def test_out_of_repo_files_everywhere(self):
        other = helpers.make_repo(self.tmp, name="plain", harness=False)
        ud = paths.user_dir(self.env)
        for cwd in (self.repo, other):
            self.assertDeny("rm -rf %s/studio-backup" % ud, "G-OUT", cwd=cwd)
            self.assertDeny("echo x > %s/studio-sandbox.json" % ud, "G-OUT", cwd=cwd)
            self.assertDeny("rm -rf %s/heavy.lock.d" % self.env["S2V_STATE_DIR"], "G-OUT", cwd=cwd)
            self.assertDeny("rm -rf %s" % self.env["S2V_STATE_DIR"], "G-OUT", cwd=cwd)
        st = self.env.pop("S2V_STATE_DIR")
        self.assertDeny("rm -rf ~/.s2v", "G-OUT", cwd=other)
        self.env["S2V_STATE_DIR"] = st

    def test_alias_alternative_message(self):
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        os.makedirs(d, exist_ok=True)
        for i, al in enumerate(([("g", "git")], [])):
            with open(os.path.join(d, "snapshot-zsh-%d-a.sh" % i), "w") as f:
                f.write(snapshot_text(aliases=al, path=self.env["PATH"]))
        self.snap_with = snapmod.load(self.env)
        dn = self.assertDeny("g add -f studio/local/x", "G-PROT")
        self.assertIn('alias "g" is "git" in 1 of 2 recent shell snapshots', dn.message())
        dn = self.assertDeny("g stash -a", "G-STASH")
        self.assertIn("recent shell snapshots", dn.message())


class MustPass(JudgeCase):
    def test_must_pass_with_snapshot(self):
        self.mode = "with"
        for cmd in MUST_PASS + WITH_SNAPSHOT_PASS:
            self.assertPass(cmd)

    def test_must_pass_without_snapshot(self):
        self.mode = "none"
        for cmd in MUST_PASS:
            self.assertPass(cmd)

    def test_repo_without_harness(self):
        plain = helpers.make_repo(self.tmp, name="plain", harness=False)
        os.makedirs(os.path.join(plain, "studio", "local"))
        os.rename(os.path.join(plain, "studio", "local"), os.path.join(plain, "studio", "notlocal"))
        for mode in ("with", "none"):
            self.mode = mode
            for cmd in MUST_PASS + ["rm -rf studio", "echo x > studio/videos/v/work/state.json"]:
                if mode == "none" and cmd in NO_SNAPSHOT_DENY:
                    continue
                self.assertPass(cmd, cwd=plain)
            # s2v in a repository without a harness or marker
            self.assertPass("s2v tts x.md", cwd=plain)
            self.assertPass("S2V_TTS_PORT=1 s2v tts x.md", cwd=plain)

    def test_same_state_dir_passes(self):
        self.assertPass("S2V_STATE_DIR=%s s2v x" % self.env["S2V_STATE_DIR"])
        self.assertPass("S2V_STATE_DIR=%s S2V_TTS=mock python3 x.py" % "/elsewhere")


class Plan00(JudgeCase):
    """00-plan §3.4 M0 tests (the 1b part)."""

    def untracked(self, rel):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")

    def test_git_clean_cases(self):
        self.untracked("studio/cast/b/character/face.png")
        self.untracked("src/tmp.o")
        self.assertDeny("git clean -fd", "G-CLEAN")
        self.assertDeny("git clean -fdx", "G-CLEAN")
        self.assertDeny("git clean -f -d -x", "G-CLEAN")
        self.assertPass("git clean -fd src/")
        self.assertPass("git clean -fdX src/")
        self.assertPass("git clean -n")

    def test_git_clean_whole_studio_untracked(self):
        repo2 = helpers.make_repo(self.tmp, name="r2", harness=True)
        self.untracked_in(repo2, "studio/videos/x/script.md")
        self.assertDeny("git clean -fd", "G-CLEAN", cwd=repo2)

    def untracked_in(self, repo, rel):
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")

    def test_git_clean_hardening(self):
        self.untracked("src/tmp.o")
        self.assertDeny("git -c core.fsmonitor=/bin/true clean -fd src/", "G-CLEAN")
        self.assertDeny("git -c alias.x=clean clean -fd src/", "G-CLEAN")
        self.assertDeny("git --exec-path=/tmp clean -fd src/", "G-CLEAN")
        self.assertDeny("git -c core.hooksPath=/tmp clean -fd src/", "G-CLEAN")
        self.assertPass("git -c core.excludesFile=/dev/null clean -fd src/")

        class Slow(object):
            def __init__(s, *a, **k):
                pass

            def clean_preview(s, *a, **k):
                return None

            def studio_changes(s, *a, **k):
                return None

            def is_rev(s, *a, **k):
                return None
        d = self.bash("git clean -fd src/", probe=Slow())
        self.assertEqual(d.rule, "G-CLEAN")
        d = self.bash("git reset --hard", probe=Slow())
        self.assertEqual(d.rule, "G-RESET")

    def test_git_clean_requireforce_false(self):
        self.untracked("studio/videos/z/a.md")
        self.assertDeny("git -c clean.requireForce=false clean -d", "G-CLEAN")

    def test_reset_with_studio_changes(self):
        self.assertPass("git reset --hard")
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("more\n")
        self.assertDeny("git reset --hard", "G-RESET")
        self.assertDeny("git checkout -f", "G-RESET")
        self.assertDeny("git switch --discard-changes main", "G-RESET")
        self.assertDeny("git checkout -- .", "G-RESET")
        self.assertDeny("git restore -- studio", "G-RESET")

    def test_cd_then_relative(self):
        cwd = os.path.join(self.repo, "studio", "videos", "v")
        self.assertDeny("echo x > work/state.json", "G-PROT", cwd=cwd)
        self.assertDeny("cd studio/videos/v && echo x > work/state.json", "G-PROT")
        self.assertPass("( cd studio/videos/v; echo x > notes.md ); echo y > work/state.json")
        self.assertDeny("{ cd studio/videos/v; echo x > work/state.json; }", "G-PROT")

    def test_yarn_cwd(self):
        self.assertPass("yarn --cwd studio/videos/v build")

    def test_other_repo_session(self):
        other = helpers.make_repo(self.tmp, name="other", harness=False)
        self.assertDeny("cp a %s/studio/videos/v/work/state.json" % self.repo, "G-PROT", cwd=other)
        self.assertDeny("touch %s/studio/voices/new/deep/x.wav" % self.repo, "G-PROT", cwd=other)
        d = self.decide("Write", {"file_path": "%s/studio/cast/a/character/new/x.yaml" % self.repo,
                                  "content": "x"}, cwd=other)
        self.assertEqual(d.rule, "G-PROT")

    def test_outside_studio_interpreters_pass(self):
        self.assertPass("python3 -c 'print(1)'")
        self.assertPass("python3 - <<'EOF'\nimport json\nprint(json.dumps({}))\nEOF")

    def test_marker_only_branch(self):
        repo3 = helpers.make_repo(self.tmp, name="r3", harness=False, marker=True)
        os.makedirs(os.path.join(repo3, "studio", "local"))
        self.assertDeny("rm -rf studio/local", "G-DEL", cwd=repo3)
        self.assertDeny("git stash -a", "G-STASH", cwd=repo3)
        self.assertDeny("git add -f studio/local/x", "G-PROT", cwd=repo3)
        self.assertPass("rm -rf src", cwd=repo3)

    def test_guard_exception_denies(self):
        from stdo.guard.where import FS

        class Boom(FS):
            def realpath(s, p):
                raise KeyError("x")
        deny, ctx = judge.decide(self.hook("Bash", {"command": "rm -rf studio"}), self.env, fs=Boom(),
                                 snapshot_loader=self.loader)
        self.assertEqual(deny.rule, "G-ERR")


class FileTools(JudgeCase):
    def test_write_edit(self):
        D = lambda tool, ti: self.decide(tool, ti)
        self.assertEqual(D("Write", {"file_path": "studio/videos/v/work/state.json", "content": "{}"}).rule, "G-PROT")
        self.assertEqual(D("Write", {"file_path": ".claude/studio/charter.md", "content": "x"}).rule, "G-PROT")
        self.assertEqual(D("Write", {"file_path": "studio/cast/a/character/character.yaml", "content": "x"}).rule,
                         "G-PROT")
        self.assertIsNone(D("Write", {"file_path": "studio/cast/a/character/character.yaml.draft", "content": "x"}))
        self.assertEqual(D("Write", {"file_path": "studio/CREDITS.yaml", "content": "x"}).rule, "G-PROT")
        self.assertIsNone(D("Write", {"file_path": "studio/CREDITS.draft.yaml", "content": "x"}))
        self.assertIsNone(D("Write", {"file_path": "src/a.ts", "content": "x"}))
        self.assertIsNone(D("Write", {"file_path": "studio/videos/v/script.md", "content": "x"}))
        self.assertIsNone(D("Write", {"file_path": "studio/local/videos/w/notes.md", "content": "x"}))
        self.assertEqual(D("NotebookEdit", {"notebook_path": "studio/voices/a/x.ipynb"}).rule, "G-PROT")
        self.assertEqual(D("Edit", {"file_path": "studio/voices/a/x", "old_string": "a", "new_string": "b"}).rule,
                         "G-PROT")

    def test_config_keys(self):
        cfgp = os.path.join(self.repo, ".claude", "studio", "config.json")
        cfg = json.load(open(cfgp))
        new = dict(cfg, language="en")
        self.assertIsNone(self.decide("Write", {"file_path": cfgp, "content": json.dumps(new)}))
        new = dict(cfg, visibility={"default": "public"})
        self.assertEqual(self.decide("Write", {"file_path": cfgp, "content": json.dumps(new)}).rule, "G-PROT")
        text = open(cfgp).read()
        old_lang = '"language": "%s"' % cfg["language"]
        self.assertIsNone(self.decide("Edit", {"file_path": cfgp, "old_string": old_lang,
                                               "new_string": '"language": "en"'}))
        self.assertEqual(self.decide("Edit", {"file_path": cfgp, "old_string": '"allow_internal_commits": false',
                                              "new_string": '"allow_internal_commits": true'}).rule, "G-PROT")
        self.assertEqual(self.decide("Write", {"file_path": cfgp, "content": "not json"}).rule, "G-PROT")
        self.assertIsNone(self.decide("Edit", {"file_path": cfgp, "old_string": "nope-not-there", "new_string": "x"}))
        self.assertEqual(self.decide("MultiEdit", {"file_path": cfgp, "edits": [
            {"old_string": old_lang, "new_string": '"language": "en"'},
            {"old_string": '"gates": [', "new_string": '"gates": ["0", '}]}).rule, "G-PROT")
        del text

    def test_out_of_repo_write(self):
        ud = paths.user_dir(self.env)
        self.assertEqual(self.decide("Write", {"file_path": os.path.join(ud, "studio-sandbox.json"),
                                               "content": "{}"}).rule, "G-OUT")

    def test_mcp_tools(self):
        D = lambda ti: self.decide("mcp__fs__write_file", ti)
        self.assertEqual(D({"path": "studio/videos/v/work/state.json", "content": "x"}).rule, "G-PROT")
        self.assertEqual(D({"paths": ["src/a.ts", "studio/voices/a/b.wav"]}).rule, "G-PROT")
        self.assertEqual(D({"destination": "studio/cast/a/character/x"}).rule, "G-PROT")
        self.assertIsNone(D({"path": "src/a.ts"}))
        self.assertIsNone(D({"query": "studio/videos/v/work/state.json"}))
        self.assertIsNone(D({"path": "studio/local/videos/w/x.md"}))
        self.assertIsNone(self.decide("TodoWrite", {"todos": []}))


class Messages(JudgeCase):
    def test_ancestor_message(self):
        for cmd in ("rm -rf studio", "rm -rf .claude", "rm -rf ."):
            self.assertIn("ancestor of Studio's folders", self.bash(cmd).message(), cmd)

    def test_message_shape(self):
        d = self.bash("rm -rf studio/local")
        m = d.message()
        self.assertTrue(m.startswith("Studio guard [G-DEL]: "))
        self.assertIn("(INV9)", m)
        self.assertLessEqual(len(m), 1000)
        self.mode = "none"
        d = self.bash("g st")
        self.assertIn("(shell snapshot:", d.message())


class Review1b(JudgeCase):
    """Implementation review round 1 (M0d-1b): every repro, in temporary harness repositories with real git."""

    def test_xargs_parallel_inputs(self):  # MJ-1
        for cmd in ("echo studio/local | xargs rm -rf", "ls -d studio/local | xargs rm -rf",
                    "find studio -maxdepth 1 -name local | xargs rm -rf",
                    "printf '%s\\n' studio/local | xargs -I{} rm -rf {}",
                    "find . -path ./studio/local -prune -o -print0 | xargs -0 rm -f",
                    "echo studio/x | parallel rm {}"):
            self.assertDeny(cmd, "G-OPAQUE")
        for cmd in ("echo studio/local | xargs grep foo", "ls studio | xargs wc -l", "ls src | xargs rm -f",
                    "find src -name '*.o' | xargs rm -f"):
            self.assertPass(cmd)
        self.assertDeny("ls | xargs rm -f", "G-OPAQUE", cwd=os.path.join(self.repo, "studio"))

    def test_checkout_restore_pathspecs(self):  # MJ-2
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("changed\n")
        for cmd, rule in (("git checkout .", "G-RESET"), ("git restore .", "G-RESET"), ("git checkout studio", "G-RESET"),
                          ("git checkout -- studio/videos/v/script.md", "G-RESET"),
                          ("git checkout HEAD .claude/studio/config.json", "G-PROT"),
                          ("git checkout HEAD~0 .claude/studio/charter.md", "G-PROT"),
                          ("git checkout HEAD -- studio", "G-PROT"), ("git restore -s HEAD~0 studio", "G-PROT"),
                          ("git restore --source=HEAD .claude/studio/config.json", "G-PROT"),
                          ("git checkout :/", "G-RESET"), ("git restore -- '*'", "G-RESET"),
                          ("git rm -r --cached studio", "G-DEL"), ("git mv studio studio2", "G-DEL"),
                          ("git rm .claude/studio/config.json", "G-DEL"), ("git mv a.txt .claude/studio/charter.md", "G-PROT")):
            self.assertDeny(cmd, rule)
        for cmd in ("git checkout main", "git checkout -b feat/y", "git checkout src/a.ts", "git restore src/a.ts",
                    "git restore --staged studio/videos/v/script.md", "git rm src/x.ts", "git mv src/x.ts src/z.ts",
                    "git checkout -b feat/z main"):
            self.assertPass(cmd)

    def test_checkout_clean_studio_passes(self):  # MJ-2: nothing uncommitted under Studio
        self.assertPass("git checkout .")
        self.assertPass("git restore studio")

    def test_git_dir_and_work_tree(self):  # MJ-3
        other = helpers.make_repo(self.tmp, name="plain2", harness=False)
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("changed\n")
        gd = os.path.join(self.repo, ".git")
        self.assertDeny("git --git-dir=%s --work-tree=%s reset --hard" % (gd, self.repo), "G-RESET", cwd=other)
        self.assertDeny("GIT_DIR=%s GIT_WORK_TREE=%s git reset --hard" % (gd, self.repo), "G-RESET", cwd=other)
        self.assertDeny("git --git-dir=$X reset --hard", "G-RESET")
        self.assertDeny("GIT_DIR=$X git reset --hard", "G-RESET")
        self.assertDeny("git -C $X reset --hard", "G-RESET")
        self.assertDeny("GIT_CONFIG_COUNT=1 git clean -fd src/", "G-CLEAN")
        # the user's own GIT_DIR (inherited) points the command at the Studio repository
        self.env["GIT_DIR"] = gd
        self.env["GIT_WORK_TREE"] = self.repo
        self.assertDeny("git reset --hard", "G-RESET", cwd=other)
        del self.env["GIT_DIR"], self.env["GIT_WORK_TREE"]
        # a plain repository targeted explicitly is not judged
        self.assertPass("git --git-dir=%s/.git --work-tree=%s reset --hard" % (other, other))
        self.untracked = None
        p = os.path.join(self.repo, "studio", "cast", "z", "character", "f.png")
        os.makedirs(os.path.dirname(p))
        open(p, "w").close()
        self.assertDeny("git -C %s clean -fd" % self.repo, "G-CLEAN", cwd=other)
        self.assertDeny("git --git-dir=%s --work-tree=%s clean -fd" % (gd, self.repo), "G-CLEAN", cwd=other)

    def test_probe_env_cleared(self):  # MJ-3
        from stdo.guard.gitprobe import Probe
        pr = Probe(dict(self.env, GIT_DIR="/x", GIT_WORK_TREE="/y", GIT_INDEX_FILE="/z", GIT_CONFIG_COUNT="1",
                        GIT_CONFIG_KEY_0="core.fsmonitor", GIT_CONFIG_VALUE_0="/bin/sh"))
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
            self.assertNotIn(k, pr.env)

    def test_find_conditions(self):  # MINOR 1
        for cmd in ("find . -name '*.pyc' -delete", "find . -name __pycache__ -type d -exec rm -rf {} +",
                    "find src -name '*.o' -delete"):
            self.assertPass(cmd)
        for cmd in ("find . -name local -delete", "find . -name '*' -delete", "find . -delete",
                    "find . ! -name x -delete", "find . -path './studio/*' -delete", "find . -iname 'STATE.json' -delete",
                    "find . -regex '.*' -delete", "find studio -name x -delete", "find studio/voices -name '*.wav' -delete"):
            self.assertDeny(cmd, "G-DEL")

    def test_more_deleters(self):  # MINOR 2
        for cmd in ("rimraf studio/local", "npx rimraf studio/local", "pnpm dlx rimraf studio", "yarn dlx rimraf studio",
                    "bunx rimraf studio/voices", "del studio/local", "trash-put studio/local", "gio trash studio/local",
                    "zip -m out.zip studio/videos/v/work/state.json", "tar --remove-files -cf a.tar studio/local"):
            self.assertDeny(cmd, "G-DEL")
        for cmd in ("npx rimraf dist", "zip -m out.zip src/a.ts", "npx prettier --write src/a.ts"):
            self.assertPass(cmd)
        wt = os.path.join(self.tmp, "wt2")
        helpers.git(self.repo, "worktree", "add", "-q", wt)
        os.makedirs(os.path.join(wt, ".claude", "studio"), exist_ok=True)
        self.assertDeny("git worktree remove %s" % wt, "G-DEL")

    def test_ln_protected_source(self):  # MINOR 3
        self.assertDeny("ln -s studio/videos/v/work/state.json /tmp/s.json", "G-PROT")
        self.assertDeny("ln .claude/studio/charter.md x.md", "G-PROT")
        self.assertPass("ln -s studio/local/videos/w/notes.md n.md")
        self.assertPass("ln -s src/a.ts b.ts")

    def test_stash_clusters(self):  # MINOR 4
        for cmd in ("git stash -au", "git stash push -ua", "git stash save -a x", "git stash --all"):
            self.assertDeny(cmd, "G-STASH")
        self.assertPass("git stash -u")
        self.assertPass("git stash push -m 'a b'")

    def test_plugin_data_pycache(self):  # MINOR 5b
        pd = os.path.join(self.tmp, "pdata")
        self.env["CLAUDE_PLUGIN_DATA"] = pd
        self.assertDeny("rm -rf %s/pycache" % pd, "G-OUT")
        self.assertDeny("rm -rf %s" % pd, "G-OUT")
        self.assertPass("ls %s" % pd)

    def test_marker_only_detection(self):  # MINOR 6 (J5)
        from stdo.guard.repos import Repos, marker_key
        from stdo.guard.where import FS, Where
        r = helpers.make_repo(self.tmp, name="mk", harness=False, marker=False)
        m = os.path.join(paths.backup_root(self.env), marker_key(os.path.join(r, ".git")), "marker")
        os.makedirs(os.path.dirname(m))
        with open(m, "w") as f:
            json.dump({"studio_root": "media"}, f)
        w = Where(FS(), self.env)
        ri = Repos(w, self.env).info(w.git_repo(r))
        self.assertTrue(ri.studio and not ri.harness)
        self.assertEqual(ri.studio_root, "media")
        os.makedirs(os.path.join(r, "media", "local"))
        self.assertDeny("rm -rf media/local", "G-DEL", cwd=r)
        self.assertEqual(marker_key(os.path.join(r, ".git")), paths.common_key(r))

    def test_opaque_literal_hits_protected_path(self):  # MINOR 6 (J21)
        cwd = os.path.join(self.repo, "studio")
        d = self.assertDeny("python3 -c \"open('voices/a/x.wav','w')\"", "G-OPAQUE", cwd=cwd)
        self.assertIn("voices/a/x.wav", d.message())

    def test_unknown_payload_in_studio_cwd(self):  # MINOR 6 (J22)
        self.assertDeny('eval "$X"', "G-OPAQUE", cwd=os.path.join(self.repo, "studio", "videos"))
        self.assertDeny('eval "$X"', "G-OPAQUE")  # M1a X1: a non-literal eval anywhere in a Studio repository

    def test_studio_script_needs_harness(self):  # NIT
        fake = helpers.make_repo(self.tmp, name="noh", harness=False)
        os.makedirs(os.path.join(fake, ".claude", "studio", "scripts"))
        with open(os.path.join(fake, ".claude", "studio", "scripts", "state.py"), "w") as f:
            f.write("#\n")
        self.assertPass("python3 .claude/studio/scripts/state.py approve v 1", cwd=fake)
        self.assertDeny("python3 .claude/studio/scripts/state.py approve v 1", "G-APPROVAL")
        self.assertDeny("python3 %s/.claude/studio/scripts/state.py next v > studio/videos/v/work/state.json" % fake,
                        "G-PROT")

    def test_mcp_nested(self):  # NIT
        D = lambda ti: self.decide("mcp__x__op", ti)
        self.assertEqual(D({"args": {"options": {"path": "studio/videos/v/work/state.json"}}}).rule, "G-PROT")
        self.assertEqual(D({"ops": [{"destination": "studio/voices/a/x"}]}).rule, "G-PROT")
        self.assertIsNone(D({"a": {"b": {"c": {"d": {"e": {"f": {"path": "studio/voices/a/x"}}}}}}}))

    def test_clean_flag_stripping(self):  # NIT
        from stdo.guard.gitprobe import Probe
        calls = []

        class R(object):
            returncode, stdout = 0, ""

        def runner(argv, **k):
            calls.append(argv)
            return R()
        pr = Probe(self.env, runner=runner)
        pr.clean_preview(self.repo, [], ["-fdx", "-efoo", "-e", "fbar", "-fe", "x"])
        tail = calls[-1][calls[-1].index("-n") + 1:]
        self.assertEqual(tail, ["-dx", "-efoo", "-e", "fbar", "-e", "x"])

    def test_dynamic_git_targets_clean_repo(self):  # MJ-3: unknown targets deny even with nothing to lose here
        for cmd in ("GIT_DIR=$X git reset --hard", "GIT_WORK_TREE=$Y git checkout .", "git --work-tree=$Y clean -fd",
                    "git -C $X reset --hard"):
            self.assertIsNotNone(self.bash(cmd), cmd)
        other = helpers.make_repo(self.tmp, name="plain3", harness=False)
        self.assertPass("GIT_DIR=$X git reset --hard", cwd=other)  # no Studio repository involved

    def test_untrusted_script_copy_is_an_ordinary_command(self):  # NIT
        fake = helpers.make_repo(self.tmp, name="noh2", harness=False)
        os.makedirs(os.path.join(fake, ".claude", "studio", "scripts"))
        with open(os.path.join(fake, ".claude", "studio", "scripts", "state.py"), "w") as f:
            f.write("#\n")
        self.assertDeny("python3 %s/.claude/studio/scripts/state.py studio/videos/v/work/state.json" % fake, "G-PROT")
        self.assertPass("python3 .claude/studio/scripts/state.py next studio/videos/v/work/state.json")


class Review2b(JudgeCase):
    """Implementation review round 2 (M0d-1b)."""

    def dirty(self):
        with open(os.path.join(self.repo, "studio", "videos", "v", "script.md"), "a") as f:
            f.write("changed\n")

    def test_subdirectory_discards(self):  # MJ-1
        self.dirty()
        R = self.repo
        for cmd in ("cd studio && git checkout .", "cd studio && git checkout -- .", "cd studio/videos && git restore .",
                    "cd studio && git restore videos", "cd studio/videos/v && git checkout script.md",
                    "cd studio && git reset --hard", "cd src && git reset --hard", "git -C src reset --hard",
                    "git -C studio checkout .", "git -C studio/videos restore .", "cd src && git checkout -- ../studio",
                    "cd %s/src && git --git-dir=../.git --work-tree=.. reset --hard" % R):
            self.assertDeny(cmd, "G-RESET")
        for cmd in ("cd src && git checkout .", "git -C src restore .", "cd studio && git restore --staged ."):
            self.assertPass(cmd)

    def test_subdirectory_clean_tree_passes(self):  # MJ-1: no uncommitted Studio changes
        self.assertPass("cd studio && git checkout .")
        self.assertPass("cd src && git reset --hard")

    def test_patch_without_pathspec(self):  # NIT
        self.dirty()
        self.assertDeny("git checkout -p", "G-RESET")
        self.assertDeny("git restore --patch", "G-RESET")
        self.assertPass("git checkout -p src/a.ts")

    def write(self, name, text):
        p = os.path.join(self.repo, name)
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_arguments_from_files(self):  # MINOR 1
        self.write("bad.txt", "studio/local\n")
        self.write("rel.txt", "voices/a\n")
        self.write("ok.txt", "dist\nnode_modules\n")
        for cmd in ("xargs -a bad.txt rm -rf", "xargs --arg-file=bad.txt rm -rf", "xargs rm -rf < bad.txt",
                    "cat bad.txt | xargs rm -rf", "while read f; do rm -rf \"$f\"; done < bad.txt",
                    "for f in $(cat bad.txt); do rm -rf $f; done", "rm -rf $(cat bad.txt)",
                    ):
            self.assertDeny(cmd, None)
        d = self.bash("cd studio && xargs -a ../rel.txt rm -rf")
        self.assertIsNotNone(d)
        # a line with no Studio term that resolves to a protected folder from the command's cwd
        self.write("studio/videos/list.txt", "v/audio\n")
        cwd = os.path.join(self.repo, "studio", "videos")
        d = self.bash("while read f; do rm -rf \"$f\"; done < list.txt", cwd=cwd)
        self.assertIsNotNone(d)
        self.assertIn("protected Studio path", d.message())
        for cmd in ("xargs -a ok.txt rm -rf", "cat ok.txt | xargs rm -rf", "while read f; do rm -rf \"$f\"; done < ok.txt",
                    "rm -rf $(cat ok.txt)", "xargs -a bad.txt grep foo", "while read f; do echo \"$f\"; done < bad.txt",
                    # a missing file is not a reason: the command fails by itself (review round 3)
                    "xargs -a missing.txt rm -rf", "while read f; do mv \"$f\" /tmp; done < missing.txt"):
            self.assertPass(cmd)

    def test_parallel_arguments(self):  # MINOR 2
        self.write("bad.txt", "studio/local\n")
        self.write("ok.txt", "dist\n")
        self.assertDeny("parallel rm -rf ::: studio/local", "G-DEL")
        self.assertDeny("parallel cp a.txt ::: studio/videos/v/work/state.json", "G-PROT")
        self.assertDeny("parallel rm -rf :::: bad.txt", "G-OPAQUE")
        self.assertPass("parallel rm -rf ::: dist node_modules")
        self.assertPass("parallel rm -rf :::: ok.txt")
        self.assertPass("parallel grep foo ::: studio/videos/v/script.md")


class Review3b(JudgeCase):
    """Implementation review round 3 (M0d-1b): file-fed judgement only for real inputs of path writers."""

    def write(self, name, text, mode="w"):
        p = os.path.join(self.repo, name)
        with open(p, mode) as f:
            f.write(text)
        return p

    def test_must_pass(self):
        self.write("msg.txt", "fix: studio/local handling in studio/videos\n")
        self.write("body.md", "touches .claude/studio/config.json and studio/voices\n")
        self.write("README.md", "studio/local is ignored\n")
        self.write("build.json", '{"files": ["dist/a.js", "dist/b.js"]}\n')
        for cmd in ('git commit -m "$(cat msg.txt)"', 'gh pr create --title x --body "$(cat body.md)"',
                    'node scripts/x.js "$V" < README.md', 'python3 scripts/x.py --out "$OUT" < README.md',
                    "git branch --merged | grep -v main | xargs git branch -d",
                    "jq -r .files[] build.json | xargs rm -f", "grep -l studio src/*.ts | xargs rm -f",
                    "sed -n 's/studio/x/p' README.md | xargs rm -f"):
            self.assertPass(cmd)
        self.write("bad.txt", "studio/local\n")
        # non-writing programs are not judged by their input, even when it lists protected paths
        self.write("plist.txt", "studio/videos/v/work/state.json\nstudio/local\n")
        for cmd in ('node scripts/x.js "$V" < plist.txt', 'git commit -F plist.txt -m "$(cat plist.txt)"',
                    'python3 scripts/x.py --out "$OUT" < plist.txt'):
            self.assertPass(cmd)
        # input that feeds another command does not feed this one
        for cmd in ('echo $(cat bad.txt); rm -rf "$X"', 'wc -l < bad.txt; rm -rf "$X"',
                    'cat bad.txt | wc -l; ls | xargs rm -f'):
            self.assertPass(cmd)

    def test_round2_cases_still_deny(self):
        self.write("bad.txt", "studio/local\n")
        self.write("bad2.txt", "studio/videos/v/work/state.json\n")
        for cmd in ("xargs -a bad.txt rm -rf", "xargs --arg-file=bad.txt rm -rf", "xargs rm -rf < bad.txt",
                    "cat bad.txt | xargs rm -rf", "while read f; do rm -rf \"$f\"; done < bad.txt",
                    "for f in $(cat bad.txt); do rm -rf $f; done", "rm -rf $(cat bad.txt)",
                    "parallel rm -rf :::: bad.txt", "grep -h . bad.txt | xargs rm -rf",
                    "jq -r . bad.txt | xargs rm -rf", "cp a.txt $(cat bad2.txt)"):
            self.assertIsNotNone(self.bash(cmd), cmd)

    def test_binary_and_unreadable(self):
        self.write("bin.dat", b"studio/local\x00\x01\n\x00\n".decode("latin-1"))
        d = self.bash("xargs -a bin.dat rm -rf")
        self.assertTrue(d is None or d.rule != "G-ERR")
        p = self.write("locked.txt", "studio/local\n")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o644)
        if os.geteuid() != 0:
            self.assertEqual(self.bash("xargs -a locked.txt rm -rf").rule, "G-OPAQUE")
