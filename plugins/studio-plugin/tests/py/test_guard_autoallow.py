"""0.0.28 §1 (fix-0028-plan, pilot-3 Q1): the guard allows Studio's own read-and-record script calls (kind `script`,
§1.1) and a role's Write/Edit of its own output files (kind `work`, §1.2) in the `default` permission mode. Every
condition is a "no allow" condition: off by one, the call gets the normal prompt (no decision), never a deny.

Everything here is built in temporary folders: a repository copy of the scripts, fake programs on PATH (never run), a
fake pyenv root with its shim, a fake session folder. The real ~/.claude, ~/.pyenv and ~/.s2v are never read."""

import os
import re
import shutil
import stat
from unittest import mock

import helpers
from stdo import manifest
from guard_base import snapshot_text
from stdo.guard import backstop, judge, roleout, scriptrun
from stdo.guard import snapshot as snapmod
from test_guard_judge import ALIASES, JudgeCase

S = ".claude/studio/scripts/"
FAKE_BINARY = b"\xcf\xfa\xed\xfe fake program (never run)\n"
MODES = ("acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto", "", None)


def write(path, data, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    if mode is not None:
        os.chmod(path, mode)
    return path


def install_copy(repo):
    """The repository copy exactly as /std init and /std update make it: the manifest's files and the manifest."""
    scripts = os.path.join(repo, ".claude", "studio", "scripts")
    if os.path.lexists(scripts):
        shutil.rmtree(scripts)
    with open(os.path.join(helpers.SCRIPTS, manifest.NAME), encoding="utf-8") as f:
        files, _v = manifest.parse(f.read())
    for rel in sorted(files) + [manifest.NAME]:
        dst = os.path.join(scripts, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(helpers.SCRIPTS, rel), dst)
    return scripts


class AllowCase(JudgeCase):
    """A Studio repository whose copy is intact, programs that pass the program rule, the hook env of a session
    started in the repository."""

    def setUp(self):
        super().setUp()
        install_copy(self.repo)
        for v, langs, src in (("v", ("ko", "en"), "ko"), ("w", ("ko",), "ko")):
            folder = "studio/videos/v" if v == "v" else "studio/local/videos/w"
            write(os.path.join(self.repo, folder, "work", "state.json"),
                  '{"video": "%s", "source_lang": "%s", "kind": "youtube", "langs": {%s}, '
                  '"brief": {"outputs": ["youtube"], "platforms": {"youtube": ["youtube"]}}}'
                  % (v, src, ", ".join('"%s": {}' % x for x in langs)))
        helpers.git(self.repo, "add", "-A")
        helpers.git(self.repo, "commit", "-q", "-m", "copy")
        for n in ("python3", "node", "ffmpeg"):
            p = os.path.join(self.bin, n)
            if os.path.lexists(p):
                os.remove(p)
            write(p, FAKE_BINARY, 0o755)
        for k in list(self.env):
            if k in scriptrun.ENV_OFF or k in scriptrun.PYENV_ENV or k.startswith(("GIT_CONFIG", "BASH_FUNC_",
                                                                                      "_PYENV_SHIM_PATHS_")) or \
                    k == "CLAUDE_ENV_FILE":
                del self.env[k]  # git reads the test's own HOME/.gitconfig (HOME is a temporary folder)
        self.env["CLAUDE_PROJECT_DIR"] = self.repo
        self.refresh()

    def refresh(self):
        self.snap_with = self.make_snapshot()

    def run_hook(self, cmd, cwd=None, **extra):
        hook = self.hook("Bash", {"command": cmd}, cwd)
        hook.update(extra)
        for k, v in list(hook.items()):
            if v is None:
                del hook[k]
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def assertAllow(self, cmd, cwd=None, **extra):
        deny, ctx = self.run_hook(cmd, cwd, **extra)
        self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
        self.assertTrue(ctx.allow, "%s: no allow (candidates %s)" % (cmd, [k for _, k, _ in ctx.candidates]))
        return ctx

    def assertPrompt(self, cmd, cwd=None, **extra):
        """No decision: neither a deny nor an allow (the normal permission prompt)."""
        deny, ctx = self.run_hook(cmd, cwd, **extra)
        self.assertIsNone(deny, "%s: %s" % (cmd, deny and deny.message()))
        self.assertIsNone(ctx.allow, "%s: allowed" % cmd)
        return ctx

    def assertNoAllow(self, cmd, cwd=None, **extra):
        """No allow; a deny may or may not come from the existing rules."""
        deny, ctx = self.run_hook(cmd, cwd, **extra)
        self.assertIsNone(ctx.allow, "%s: allowed" % cmd)
        return deny


# ---------------------------------------------------------------- §1.1 kind `script`

ALLOWED = (
    S + "state.py next v",
    S + "state.py status",
    S + "state.py status v --json",
    S + "state.py status --since-last v",
    S + "state.py shown v 1",
    S + "state.py next v --enter script",
    S + "state.py stage-done v script",
    S + "state.py record-source v",
    S + "state.py begin newvid --source src/a.ts --kind youtube",
    S + "check_claims.py v --narration",
    S + "check_claims.py v --source --fill",
    S + "check_claims.py v --lang=en",
    S + "check_assets.py v --output youtube",
    S + "check_assets.py v --actors",
    S + "check_scope.py v",
    S + "resolve_assets.py v",
    S + "check_tts.py v --lang ko",
    S + "audition.py v",
    S + "validate_copy.py v --platform youtube",
    S + "check_tts.py w",
)


class ScriptAllow(AllowCase):
    def test_allowed(self):
        for tail in ALLOWED:
            for cmd in ("python3 " + tail, "python3 -B " + tail, "cd %s && python3 %s" % (self.repo, tail),
                        "python3 %s/%s" % (self.repo, tail), "python3 %s 2>&1" % tail):
                ctx = self.assertAllow(cmd)
                self.assertEqual([k for _, k, _ in ctx.candidates], ["script"], cmd)
                self.assertIn("Studio guard: runs Studio's", ctx.allow)
        # from a subfolder of the repository (the hook cwd inside the run repository)
        self.assertAllow("cd %s && python3 %sstate.py next v" % (self.repo, S), cwd=os.path.join(self.repo, "src"))

    def test_permission_mode(self):
        for mode in MODES:
            self.assertPrompt("python3 %sstate.py next v" % S, permission_mode=mode)
        self.assertAllow("python3 %sstate.py next v" % S, permission_mode="default")

    def test_names_not_covered(self):
        for tail in ("run_s2v.py render v --output youtube", "lock.py status", "check_commit.py --video v",
                     "hooks.py install", "state.py ask-before v tts", "state.py ask-before v none"):
            self.assertNoAllow("python3 " + S + tail)
        self.assertPrompt("python3 %sstate.py ask-before v tts" % S)  # neither deny nor allow (§13)
        d = self.assertNoAllow("python3 %sstate.py approve v 1 --expect 3f2a9c0d1e4b" % S)
        self.assertIsNotNone(d)
        self.assertEqual(d.rule, "G-EVIDENCE")

    def test_shape_off_by_one(self):
        for tail in ("state.py next ../v", "state.py next V", "state.py next v/x", "state.py next", "state.py",
                     "state.py next -v", "check_tts.py v --x", "check_tts.py v w", "check_tts.py", "check_tts.py v --lang",
                     "validate_copy.py v --platform", "check_claims.py ../v --narration", "check_scope.py v --lang ko",
                     "state.py next nosuch", "check_tts.py nosuch"):
            self.assertNoAllow("python3 " + S + tail)

    def test_call_shape(self):
        for cmd in ("python3 %sstate.py next $V" % S, "python3 %sstate.py next v | head" % S,
                    "cd %s; python3 %sstate.py next v" % (self.repo, S), "python3 %sstate.py next v; echo $?" % S,
                    "python3 %sstate.py next v && echo done" % S, "X=1 python3 %sstate.py next v" % S,
                    "python3 %sstate.py next v > out.txt" % S, "python %sstate.py next v" % S,
                    "python3 -c 1 %sstate.py next v" % S, "(python3 %sstate.py next v)" % S,
                    "python3 %sstate.py next v &" % S, "python3 ./%sstate.py next v" % S,
                    "python3 src/../%sstate.py next v" % S, "python3 %sstate.py next $(echo v)" % S,
                    "python3 %s/state.py next v" % helpers.SCRIPTS):
            self.assertNoAllow(cmd)

    def test_copy_integrity(self):
        cmd = "python3 %sstate.py next v" % S
        scripts = os.path.join(self.repo, ".claude", "studio", "scripts")
        cases = {
            "extra stdo file": lambda: write(os.path.join(scripts, "stdo", "json.py"), "x = 1\n"),
            "changed stdo file": lambda: write(os.path.join(scripts, "stdo", "paths.py"),
                                               open(os.path.join(scripts, "stdo", "paths.py")).read() + "#\n"),
            "a .pyc": lambda: write(os.path.join(scripts, "stdo", "__pycache__", "paths.cpython-39.pyc"), b"x"),
            "a .pth": lambda: write(os.path.join(scripts, "stdo", "x.pth"), "import os\n"),
            "a .DS_Store": lambda: write(os.path.join(scripts, ".DS_Store"), b"x"),
            "a FIFO": lambda: os.mkfifo(os.path.join(scripts, "stdo", "fifo")),
            "a linked stdo/": lambda: (shutil.copytree(os.path.join(scripts, "stdo"), os.path.join(self.tmp, "stdo2")),
                                       shutil.rmtree(os.path.join(scripts, "stdo")),
                                       os.symlink(os.path.join(self.tmp, "stdo2"), os.path.join(scripts, "stdo"))),
            "a linked listed file": lambda: (shutil.copy(os.path.join(scripts, "stdo", "paths.py"),
                                                         os.path.join(self.tmp, "paths.py")),
                                             os.remove(os.path.join(scripts, "stdo", "paths.py")),
                                             os.symlink(os.path.join(self.tmp, "paths.py"),
                                                        os.path.join(scripts, "stdo", "paths.py"))),
            "a missing file": lambda: os.remove(os.path.join(scripts, "stdo", "paths.py")),
            "a linked script": lambda: (shutil.copy(os.path.join(scripts, "state.py"),
                                                    os.path.join(self.tmp, "state.py")),
                                        os.remove(os.path.join(scripts, "state.py")),
                                        os.symlink(os.path.join(self.tmp, "state.py"), os.path.join(scripts, "state.py"))),
        }
        for what, change in cases.items():
            install_copy(self.repo)
            self.assertAllow(cmd)
            change()
            self.assertNoAllow(cmd)
        install_copy(self.repo)
        self.assertAllow(cmd)
        # a manifest other than the plugin's (another build of the same version)
        with mock.patch.object(scriptrun, "PLUGIN_MANIFEST", write(os.path.join(self.tmp, "M"), "# other\n")):
            self.assertNoAllow(cmd)

    def test_links_below_the_root(self):
        cmd = "python3 %sstate.py next v" % S
        # a linked repository root is fine (/tmp, a linked home)
        os.symlink(self.repo, os.path.join(self.tmp, "linked-repo"))
        self.assertAllow("python3 %s/linked-repo/%sstate.py next v" % (self.tmp, S))
        # a linked .claude below the root is not
        claude = os.path.join(self.repo, ".claude")
        os.rename(claude, os.path.join(self.repo, "real-claude"))
        os.symlink(os.path.join(self.repo, "real-claude"), claude)
        self.assertNoAllow(cmd)
        os.remove(claude)
        os.rename(os.path.join(self.repo, "real-claude"), claude)
        self.assertAllow(cmd)
        # a linked video folder
        vdir = os.path.join(self.repo, "studio", "videos", "v")
        os.rename(vdir, os.path.join(self.tmp, "v-real"))
        os.symlink(os.path.join(self.tmp, "v-real"), vdir)
        self.assertNoAllow(cmd)

    def test_video_in_both_places(self):
        os.makedirs(os.path.join(self.repo, "studio", "local", "videos", "v", "work"))
        self.assertNoAllow("python3 %sstate.py next v" % S)

    def test_repository_holds_the_plugin(self):
        with mock.patch.object(judge, "PLUGIN_SCRIPTS_SPELLED", os.path.join(self.repo, "plugin", "scripts")):
            self.assertNoAllow("python3 %sstate.py next v" % S)

    def test_environment(self):
        cmd = "python3 %sstate.py next v" % S
        for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONUSERBASE", "NODE_OPTIONS",
                  "NODE_PATH", "GIT_DIR", "GIT_WORK_TREE", "GIT_EXEC_PATH", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_COUNT",
                  "GIT_ATTR_SOURCE"):
            self.env[k] = os.path.join(self.tmp, "x")
            self.assertNoAllow(cmd)
            del self.env[k]
        self.assertAllow(cmd)
        del self.env["CLAUDE_PROJECT_DIR"]
        self.assertPrompt(cmd)
        # a session started above the repository: PATH tools and the s2v checkout are inside the area
        self.env["CLAUDE_PROJECT_DIR"] = self.tmp
        self.assertPrompt(cmd)
        self.env["CLAUDE_PROJECT_DIR"] = self.repo
        self.assertAllow(cmd)
        # the session's env folder, CLAUDE_ENV_FILE
        sess = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "session-env", "sess-1")
        write(os.path.join(sess, "hook-1.sh"), "")
        self.assertAllow(cmd)
        write(os.path.join(sess, "hook-1.sh"), "export PATH=/x:$PATH\n")
        self.assertPrompt(cmd)
        shutil.rmtree(sess)
        self.env["CLAUDE_ENV_FILE"] = write(os.path.join(self.tmp, "envfile"), "")
        self.assertAllow(cmd)
        write(self.env["CLAUDE_ENV_FILE"], "python3() { :; }\n")
        self.assertPrompt(cmd)

    def test_environment_0_1_1(self):  # fix-0029 §4.1: seventeen more names, in the hook env and in a snapshot
        cmd = "python3 %sstate.py next v" % S
        added = ("PYTHONPLATLIBDIR", "PYTHONPYCACHEPREFIX", "GIT_EXTERNAL_DIFF", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE",
                 "GIT_GRAFT_FILE", "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS",
                 "GIT_ICASE_PATHSPECS", "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_NAMESPACE")
        self.assertEqual(len(added), 17)
        self.assertTrue(set(added) <= set(scriptrun.ENV_OFF))
        self.assertAllow(cmd)
        for k in added:
            self.env[k] = os.path.join(self.tmp, "x")
            self.assertNoAllow(cmd)
            del self.env[k]
        self.assertAllow(cmd)
        d = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "shell-snapshots")
        for k in added + ("",):
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "snapshot-zsh-1-a.sh"), "w") as f:
                f.write(snapshot_text(aliases=ALIASES, path=self.env["PATH"]) +
                        ("export %s=%s\n" % (k, os.path.join(self.tmp, "x")) if k else ""))
            self.snap_with = snapmod.load(self.env)
            shutil.rmtree(d)
            (self.assertNoAllow if k else self.assertAllow)(cmd)

    def test_path(self):
        cmd = "python3 %sstate.py next v" % S
        base = self.env["PATH"]
        local = os.path.join(self.repo, "node_modules", ".bin")
        os.makedirs(local, exist_ok=True)
        for pv in (local + ":" + base, base + ":" + local, base + ":", "." + ":" + base, "bin:" + base,
                   base + "::/usr/bin"):
            self.env["PATH"] = pv
            self.refresh()
            self.assertNoAllow(cmd)
        # only the snapshot's PATH has the repository entry
        self.env["PATH"] = local + ":" + base
        self.refresh()
        self.env["PATH"] = base
        self.assertNoAllow(cmd)
        self.refresh()
        self.assertAllow(cmd)

    def test_interpreter_in_a_venv_in_the_repository(self):
        venv = os.path.join(self.repo, ".venv")
        write(os.path.join(venv, "pyvenv.cfg"), "home = /usr/bin\n")
        write(os.path.join(venv, "bin", "python3"), FAKE_BINARY, 0o755)
        self.env["PATH"] = os.path.join(venv, "bin") + ":" + self.env["PATH"]
        self.refresh()
        self.assertNoAllow("python3 %sstate.py next v" % S)

    def test_programs(self):
        cmd = "python3 %sstate.py next v" % S
        node = os.path.join(self.bin, "node")
        cases = (
            ("a #! script", lambda: write(node, "#!/bin/sh\nexec real-node \"$@\"\n", 0o755)),
            ("a volta shim", lambda: (os.remove(node), write(os.path.join(self.tmp, "volta", "volta-shim"),
                                                            FAKE_BINARY, 0o755),
                                      os.symlink(os.path.join(self.tmp, "volta", "volta-shim"), node))),
            ("missing", lambda: os.remove(node)),
            ("in the repository", lambda: (os.remove(node), write(os.path.join(self.repo, "tools", "node"),
                                                                  FAKE_BINARY, 0o755),
                                           os.symlink(os.path.join(self.repo, "tools", "node"), node))),
        )
        for what, change in cases:
            if os.path.lexists(node):
                os.remove(node)
            write(node, FAKE_BINARY, 0o755)
            self.assertAllow(cmd)
            change()
            self.assertNoAllow(cmd)
        if os.path.lexists(node):
            os.remove(node)
        write(node, FAKE_BINARY, 0o755)
        write(os.path.join(self.bin, "python3"), "#!/bin/sh\n", 0o755)  # the interpreter itself
        self.assertNoAllow(cmd)
        write(os.path.join(self.bin, "python3"), FAKE_BINARY, 0o755)
        os.remove(os.path.join(self.bin, "ffmpeg"))
        self.assertNoAllow(cmd)

    def test_s2v_checkout_inside_the_area(self):
        from stdo import machine
        machine.write(self.repo, os.path.join(self.repo, "s2v"))
        self.assertNoAllow("python3 %sstate.py next v" % S)
        machine.write(self.repo, "/abs/script2video")
        self.assertAllow("python3 %sstate.py next v" % S)

    def test_git_config(self):
        cmd = "python3 %sstate.py next v" % S
        for key, value in (("filter.x.clean", "cat"), ("filter.x.smudge", "cat"), ("filter.x.process", "x"),
                           ("diff.x.textconv", "cat"), ("diff.x.command", "x"), ("diff.external", "x"),
                           ("core.attributesFile", "/tmp/a"), ("core.fsmonitor", "/tmp/fsm"), ("core.hooksPath", "h"),
                           ("log.showSignature", "true"), ("gpg.program", "x"), ("gpg.ssh.program", "x"),
                           ("include.path", "/nonexistent/x"), ("includeIf.gitdir:/x/.path", "/nonexistent/x"),
                           ("extensions.partialClone", "origin"), ("remote.origin.promisor", "true"),
                           ("core.pager", "less -R; id"), ("core.sshCommand", "ssh"), ("alias.st", "status"),
                           ("remote.x.url", "ext::sh -c id")):
            helpers.git(self.repo, "config", key, value)
            self.assertNoAllow(cmd)
            helpers.git(self.repo, "config", "--unset-all", key)
        self.assertAllow(cmd)
        helpers.git(self.repo, "config", "core.fsmonitor", "false")
        self.assertAllow(cmd)
        # the person's global config is not judged (a global filter.lfs is normal)
        with open(os.path.join(self.env["HOME"], ".gitconfig"), "a") as f:
            f.write('[filter "lfs"]\n\tclean = git-lfs clean -- %f\n\tprocess = git-lfs filter-process\n')
        self.assertAllow(cmd)
        write(os.path.join(self.repo, ".gitmodules"), "")
        self.assertNoAllow(cmd)

    def test_git_config_unreadable(self):
        with mock.patch("stdo.guard.gitprobe.Probe.config_list", lambda self, cwd: None):
            self.assertNoAllow("python3 %sstate.py next v" % S)

    def test_warning(self):
        hook = self.hook("Bash", {"command": "python3 %sstate.py next v" % S})
        for warn in (False, True):
            deny, ctx, complete = judge.decide_g1(hook, self.env, snapshot_loader=self.loader, run_finish=False)
            self.assertIsNone(deny)
            if warn:
                ctx.warnings.append("a warning from either guard")
            judge.finish(ctx)
            self.assertEqual(bool(ctx.allow), not warn)

    def test_backstop(self):
        cmd = "python3 %sstate.py next v" % S
        # the 0.0.26 guard refuses: refused, no allow
        lj, real_decide = backstop._legacy()

        def legacy_refuses(lctx, hook):
            lctx.denies.append(lj.Deny("G-PROT", "refused by the 0.0.26 rules (test)"))
            return lctx.denies[0], lctx
        with mock.patch.object(backstop, "_legacy", lambda: [lj, legacy_refuses]):
            deny, ctx = self.run_hook(cmd)
            self.assertIsNotNone(deny)
            self.assertIsNone(ctx.allow)
        # the 0.0.26 guard's finish is chosen (after a source): no allow
        write(os.path.join(self.repo, "empty.sh"), "")
        self.assertNoAllow(". ./empty.sh && python3 %sstate.py next v" % S)
        self.assertAllow(cmd)

    def test_pyenv_system(self):
        cmd = "python3 %sstate.py next v" % S
        root = os.path.join(self.tmp, "pyenv-root")
        prefix = os.path.join(self.tmp, "pyenv-prefix")
        write(os.path.join(prefix, "libexec", "pyenv"), "#!/usr/bin/env bash\n", 0o755)
        os.makedirs(os.path.join(prefix, "bin"))
        os.symlink(os.path.join("..", "libexec", "pyenv"), os.path.join(prefix, "bin", "pyenv"))
        shim_text = ('#!/usr/bin/env bash\nset -e\n[ -n "$PYENV_DEBUG" ] && set -x\n\nprogram="${0##*/}"\n\n'
                     'export PYENV_ROOT="%s"\nSHIM_PATH=${0%%/*}\nif [[ $SHIM_PATH != "%s/shims" ]]; then\n'
                     '  export _PYENV_SHIM_PATH="$SHIM_PATH"\nfi\nexec "%s/bin/pyenv" exec "$program" "$@"\n')
        shim = write(os.path.join(root, "shims", "python3"), shim_text % (root, root, prefix), 0o755)
        sysbin = os.path.join(self.tmp, "sysbin")
        write(os.path.join(sysbin, "python3"), FAKE_BINARY, 0o755)
        os.remove(os.path.join(self.bin, "python3"))
        self.env["PATH"] = "%s:%s:%s" % (os.path.join(root, "shims"), self.bin, sysbin)
        self.refresh()
        self.assertAllow(cmd)
        version = os.path.join(root, "version")
        for text, ok in (("", True), ("system\n", True), ("# comment\n\nsystem\r\n", True), ("3.12.1\n", False),
                         ("system\n3.12.1\n", False), ("3.12.1 system\n", False), ("x" * 1030 + "\n", False)):
            write(version, text)
            (self.assertAllow if ok else self.assertNoAllow)(cmd)
        os.remove(version)
        self.assertAllow(cmd)
        # the version chosen another way
        for k in ("PYENV_VERSION", "PYENV_DIR", "PYENV_HOOK_PATH", "_PYENV_SHIM_PATH", "_PYENV_SHIM_PATHS_python3",
                  "BASH_ENV", "ENV", "BASHOPTS", "SHELLOPTS", "BASH_FUNC_python3%%"):
            self.env[k] = "3.12.1"
            self.assertNoAllow(cmd)
            del self.env[k]
        # the guard itself started through the same shim (hooks.json runs `python3 …/guard.py`): pyenv's own values
        own = {"PYENV_VERSION": "system", "PYENV_DIR": self.repo,
               "PYENV_HOOK_PATH": "%s/pyenv.d:%s/pyenv.d:/usr/etc/pyenv.d:/opt/homebrew/etc/pyenv.d:/etc/pyenv.d:"
                                  "/usr/lib/pyenv/hooks" % (root, prefix)}
        self.env.update(own)
        self.assertAllow(cmd)
        for k, v in (("PYENV_VERSION", "3.12.1"), ("PYENV_DIR", self.tmp),
                     ("PYENV_HOOK_PATH", "%s/hooks:%s/pyenv.d" % (self.tmp, root)),
                     ("PYENV_HOOK_PATH", "%s/pyenv.d:%s/hooks" % (root, self.tmp))):
            self.env[k] = v
            self.assertNoAllow(cmd)
            self.env[k] = own[k]
        self.assertAllow(cmd)
        for k in own:
            del self.env[k]
        for folder in (self.repo, os.path.join(self.repo, "src"), self.tmp):
            p = write(os.path.join(folder, ".python-version"), "3.12.1\n")
            self.assertNoAllow(cmd, cwd=os.path.join(self.repo, "src"))
            os.remove(p)
        self.assertAllow(cmd)
        # a plugin's bin folder put in front by libexec/pyenv: its python3 must pass the program rule
        write(os.path.join(root, "plugins", "p", "bin", "python3"), "#!/bin/sh\n", 0o755)
        self.assertNoAllow(cmd)
        shutil.rmtree(os.path.join(root, "plugins"))
        # fix-0029 §4.2: the script inherits that PATH, so node, git and ffmpeg are looked up on it too
        for prog in ("git", "node", "ffmpeg"):
            write(os.path.join(root, "plugins", "x", "bin", prog), "#!/bin/sh\n", 0o755)
            self.assertNoAllow(cmd)
            write(os.path.join(root, "plugins", "x", "bin", prog), FAKE_BINARY, 0o755)  # a real-named binary
            self.assertAllow(cmd)
            shutil.rmtree(os.path.join(root, "plugins"))
        write(os.path.join(prefix, "plugins", "y", "bin", "git"), "#!/bin/sh\n", 0o755)
        self.assertNoAllow(cmd)
        shutil.rmtree(os.path.join(prefix, "plugins"))
        # a front folder inside the area (the repository): no allow
        os.makedirs(os.path.join(self.repo, "pyenv-plugin", "bin"))
        os.makedirs(os.path.join(root, "plugins"))
        os.symlink(os.path.join(self.repo, "pyenv-plugin"), os.path.join(root, "plugins", "in-repo"))
        self.assertNoAllow(cmd)
        shutil.rmtree(os.path.join(root, "plugins"))
        shutil.rmtree(os.path.join(self.repo, "pyenv-plugin"))
        self.assertAllow(cmd)
        # the system python3 itself
        write(os.path.join(sysbin, "python3"), "#!/bin/sh\n", 0o755)
        self.assertNoAllow(cmd)
        write(os.path.join(sysbin, "python3"), FAKE_BINARY, 0o755)
        self.assertAllow(cmd)
        # another root in the shim, an exec line that is not pyenv's, pyenv in the repository
        for text in (shim_text % (self.tmp, root, prefix), shim_text.replace('exec "%s/bin/pyenv"', 'exec "$X"') % (
                root, root), shim_text % (root, root, os.path.join(self.repo, "pyenv"))):
            write(shim, text, 0o755)
            self.assertNoAllow(cmd)

    def test_other_shims(self):
        cmd = "python3 %sstate.py next v" % S
        asdf = write(os.path.join(self.tmp, "asdf", "shims", "python3"),
                     '#!/usr/bin/env bash\nexec /opt/asdf/bin/asdf exec "python3" "$@"\n', 0o755)
        os.remove(os.path.join(self.bin, "python3"))
        self.env["PATH"] = os.path.dirname(asdf) + ":" + self.env["PATH"]
        self.refresh()
        self.assertNoAllow(cmd)

    def test_no_snapshot(self):
        self.mode = "none"
        self.assertAllow("python3 %sstate.py next v" % S)

    def test_video_id_matches_flow(self):
        from stdo.state import flow
        self.assertEqual(scriptrun.VIDEO_ID.pattern, flow.VIDEO_ID.pattern)


# the pilot's calls (pilot-3 keep/transcripts; the video renamed v, the sandbox repository <R>): allowed, prompted, refused
PILOT_ALLOW = (
    "python3 .claude/studio/scripts/state.py begin v2 --source src/a.ts --kind youtube",
    "python3 .claude/studio/scripts/state.py next v",
    "python3 .claude/studio/scripts/state.py stage-done v source",
    "python3 .claude/studio/scripts/state.py record-brief v --from work/brief.json",
    "python3 .claude/studio/scripts/state.py shown v 1",
    "python3 .claude/studio/scripts/state.py credit-preview v",
    "python3 .claude/studio/scripts/state.py loop v",
    "python3 .claude/studio/scripts/state.py record-render v --output youtube",
    "python3 .claude/studio/scripts/state.py done v",
    "python3 .claude/studio/scripts/check_claims.py v --source --fill",
    "python3 .claude/studio/scripts/check_assets.py v --look --output youtube",
    "cd <R> && python3 .claude/studio/scripts/check_assets.py v --look --output youtube",
    "python3 .claude/studio/scripts/resolve_assets.py v",
    "python3 .claude/studio/scripts/check_scope.py v",
    "python3 .claude/studio/scripts/audition.py v",
    "python3 .claude/studio/scripts/validate_copy.py v --platform youtube",
)
PILOT_PROMPT = (
    "cd <R>; python3 .claude/studio/scripts/check_claims.py v --narration 2>&1 | head -40",
    "cd <R>; python3 .claude/studio/scripts/check_claims.py v --narration 2>&1 | head",
    "python3 .claude/studio/scripts/check_assets.py v --look --output youtube; echo exit $?",
    "cd <R> && python3 .claude/studio/scripts/check_assets.py v --look --output youtube; echo exit $?",
    "python3 .claude/studio/scripts/run_s2v.py snapshot v --output youtube",
    "python3 .claude/studio/scripts/run_s2v.py render v --output youtube",
    "python3 .claude/studio/scripts/check_commit.py --stage harness",
    "python3 .claude/studio/scripts/lock.py status",
    "open public/a.png", "shasum studio/videos/v/script.md", "git rev-parse --show-toplevel",
)
PILOT_REFUSED = (
    ('code "<R>/.claude/studio/platforms/youtube.md"', "G-PROT"),
    ("head -c 1500 studio/videos/v/work/state.json; echo; python3 -c \"\nimport json\n"
     "d=json.load(open('studio/videos/v/work/state.json'))\nprint(d)\n\"", "G-OPAQUE"),
    ("python3 .claude/studio/scripts/state.py approve v 1 --expect 64d237ad1660", "G-EVIDENCE"),
)


class PilotCalls(AllowCase):
    def test_pilot_calls(self):
        os.makedirs(os.path.join(self.repo, ".claude", "studio", "platforms"), exist_ok=True)
        write(os.path.join(self.repo, ".claude", "studio", "platforms", "youtube.md"), "# youtube\n")
        for cmd in PILOT_ALLOW:
            self.assertAllow(cmd.replace("<R>", self.repo))
        for cmd in PILOT_PROMPT:
            self.assertNoAllow(cmd.replace("<R>", self.repo))
        for cmd, rule in PILOT_REFUSED:
            d = self.assertNoAllow(cmd.replace("<R>", self.repo))
            self.assertIsNotNone(d, cmd)
            self.assertEqual(d.rule, rule, "%s: %s" % (cmd, d.message()))


# ---------------------------------------------------------------- §1.2 kind `work`

class WorkAllow(AllowCase):
    def write_hook(self, path, agent="std-writer", tool="Write", **extra):
        ti = {"file_path": path, "content": "x\n"} if tool == "Write" else (
            {"file_path": path, "old_string": "a", "new_string": "b"} if tool == "Edit" else
            {"file_path": path, "edits": [{"old_string": "a", "new_string": "b"}]})
        if tool == "NotebookEdit":
            ti = {"notebook_path": path, "new_source": "x"}
        hook = self.hook(tool, ti)
        if agent is not None:
            hook.update({"agent_id": "a123", "agent_type": agent})
        hook.update(extra)
        for k, v in list(hook.items()):
            if v is None:
                del hook[k]
        return judge.decide(hook, self.env, snapshot_loader=self.loader)

    def p(self, *rel):
        return os.path.join(self.repo, "studio", *rel)

    def assertWork(self, path, ok, **kw):
        deny, ctx = self.write_hook(path, **kw)
        self.assertIsNone(deny, "%s: %s" % (path, deny and deny.message()))
        if ok:
            self.assertTrue(ctx.allow, "%s %s: no allow" % (kw, path))
            self.assertEqual([k for _, k, _ in ctx.candidates], ["work"])
        else:
            self.assertIsNone(ctx.allow, "%s %s: allowed" % (kw, path))

    def test_each_role_its_own_files(self):
        own = {
            "std-source-analyst": [self.p("videos/v/work/source.md")],
            "std-strategist": [self.p("videos/v/work/brief.json"), self.p("videos/v/work/brief.md")],
            "std-writer": [self.p("videos/v/script.ko.md"), self.p("videos/v/script.en.md"),
                           self.p("videos/v/work/ko/claims-map.json"), self.p("local/videos/w/script.ko.md")],
            "std-translator": [self.p("videos/v/script.en.md")],
            "std-visual-director": [self.p("videos/v/script.ko.md"), self.p("videos/v/script.en.md"),
                                    self.p("local/videos/w/script.ko.md"), self.p("videos/v/CREDITS.draft.yaml"),
                                    self.p("videos/v/work/ko/board.md")],
            "std-distributor": [self.p("copy/v/ko/youtube.md")],
        }
        everything = sorted({p for ps in own.values() for p in ps})
        for agent, paths in own.items():
            for p in everything:
                self.assertWork(p, p in paths, agent=agent)
        for tool in ("Edit", "MultiEdit"):
            self.assertWork(self.p("videos/v/script.ko.md"), True, tool=tool)

    def test_not_allowed(self):
        mine = self.p("videos/v/script.ko.md")
        self.assertWork(mine, False, agent=None)  # the main session
        self.assertWork(mine, False, agent=None, agent_type="std-writer")  # `claude --agent`: agent_type alone
        deny, ctx = self.write_hook(mine, agent="std-auditor")  # the external auditor only reads (G-AUDIT)
        self.assertIsNotNone(deny)
        self.assertIsNone(ctx.allow)
        for agent in ("std-fact-checker", "std-casting-director", "std-actor-designer",
                      "studio-plugin:std-writer", "std-writer ", "Std-Writer"):
            self.assertWork(mine, False, agent=agent)
        for mode in MODES:
            self.assertWork(mine, False, permission_mode=mode)
        self.assertWork(mine, False, tool="NotebookEdit")
        for p in (self.p("videos/v/./script.ko.md"), self.p("videos/x/../v/script.ko.md"),
                  self.p("videos/v/script.fr.md"), self.p("videos/v/script.ko.txt"), self.p("videos/v/work/brief.json"),
                  self.p("videos/nosuch/script.ko.md"), self.p("videos/w/script.ko.md"),
                  self.p("local/videos/v/script.ko.md"), self.p("videos/V/script.ko.md"),
                  self.p("videos/v/work/ko/verify.draft.json"), self.p("videos/v/.script.ko.md"),
                  os.path.join(self.repo, "src", "a.ts"), "studio/videos/v/script.ko.md"):
            self.assertWork(p, False)
        self.assertWork(self.p("videos/v/script.ko.md"), False, agent="std-translator")  # the source language
        self.assertWork(self.p("copy/v/ko/tiktok.md"), False, agent="std-distributor")
        self.assertWork(self.p("copy/v/fr/youtube.md"), False, agent="std-distributor")
        # a protected file stays refused
        deny, ctx = self.write_hook(self.p("videos/v/work/state.json"))
        self.assertIsNotNone(deny)
        self.assertIsNone(ctx.allow)

    def test_links(self):
        os.symlink(self.p("videos/v"), self.p("videos/x"))
        self.assertWork(self.p("videos/x/script.ko.md"), False)
        os.symlink(os.path.join(self.repo, "studio"), os.path.join(self.repo, "st"))
        self.assertWork(os.path.join(self.repo, "st", "videos", "v", "script.ko.md"), False)
        target = write(os.path.join(self.tmp, "elsewhere.md"), "x\n")
        os.symlink(target, self.p("videos/v/script.en.md"))
        self.assertWork(self.p("videos/v/script.en.md"), False)
        # a linked repository root is fine
        os.symlink(self.repo, os.path.join(self.tmp, "linked-repo"))
        self.assertWork(os.path.join(self.tmp, "linked-repo", "studio", "videos", "v", "script.ko.md"), True)

    def test_hard_link(self):
        outside = write(os.path.join(self.tmp, "hook.sh"), "x\n")
        os.link(outside, self.p("videos/v/script.ko.md"))
        self.assertWork(self.p("videos/v/script.ko.md"), False)

    def test_video_in_both_places(self):
        os.makedirs(self.p("local/videos/v/work"))
        self.assertWork(self.p("videos/v/script.ko.md"), False)

    def test_warning(self):
        hook = self.hook("Write", {"file_path": self.p("videos/v/script.ko.md"), "content": "x"})
        hook.update({"agent_id": "a1", "agent_type": "std-writer"})
        for warn in (False, True):
            deny, ctx, complete = judge.decide_g1(hook, self.env, snapshot_loader=self.loader, run_finish=False)
            if warn:
                ctx.warnings.append("w")
            judge.finish(ctx)
            self.assertEqual(bool(ctx.allow), not warn)


# ---------------------------------------------------------------- structure

class Structure(helpers.StudioTestCase):
    def test_kinds_and_single_allow_site(self):
        src = open(judge.__file__, encoding="utf-8").read()
        body = src[src.index("\ndef finish(ctx):"):src.index("\ndef allow_for(ctx, reason):")]
        self.assertEqual(body.count("allow_for("), 1)
        for kind in ('"script"', '"work"', '"doc"'):
            self.assertIn(kind, body)
        self.assertIn('"script" | "work"', src)
        self.assertEqual(src.count("allow_for(ctx"), 2)  # the call in finish and the definition

    def test_table_has_no_dotfile_or_lock(self):
        for agent, pats in roleout.TABLE.items():
            self.assertTrue(re.match(r"^std-[a-z-]+$", agent), agent)
            for pat in pats:
                for part in pat.split("/"):
                    self.assertFalse(part.startswith("."), pat)
                    self.assertNotIn("lock", part, pat)
                self.assertTrue(pat.startswith(("videos/<v>/", "copy/<v>/")), pat)

    def test_table_matches_the_templates(self):
        """Each role's files are named in its template's Outputs (up to "Write nothing else"); every file a template
        names there is in the table, except the intended exclusions."""
        excluded = {
            # verdicts keep the prompt: a forged verify.draft.json is never silent
            "std-fact-checker": {"verify.draft.json"},
            # casting director and actor designer: no row (script cast blocks, profiles, character drafts)
            "std-casting-director": None,
            "std-actor-designer": None,
            "std-auditor": None,
            # named in the brief's claims line (ids from work/source.md), read only
            "std-strategist": {"source.md"},
        }
        # outputs a template names without a file name: the visual director's board edits of the script
        implied = {"std-visual-director": (("script.<lang>.md", "How the script looks, with Edit"),)}
        tdir = os.path.join(helpers.TEMPLATES, "agents")
        seen = set()
        for fn in sorted(os.listdir(tdir)):
            agent = fn[:-3]
            text = open(os.path.join(tdir, fn), encoding="utf-8").read()
            m = re.search(r"## Outputs?\b(.*?)(Write nothing else|write nothing else)", text, re.S)
            if agent in excluded and excluded[agent] is None:
                self.assertNotIn(agent, roleout.TABLE)
                continue
            self.assertIsNotNone(m, "%s: no Output section" % fn)
            named = set()
            for tok in re.findall(r"`([^`\s]+)`", m.group(1)):
                base = tok.split("/")[-1]
                if re.search(r"\.(md|json|yaml)$", base) and not tok.startswith(".claude/"):
                    named.add(base)
            for base, phrase in implied.get(agent, ()):
                self.assertIn(phrase, m.group(1), fn)
                named.add(base)
            mine = {pat.split("/")[-1] for pat in roleout.TABLE.get(agent, ())}
            extra = excluded.get(agent) or set()
            self.assertEqual(named - extra, mine, fn)
            if mine:
                seen.add(agent)
        self.assertEqual(set(roleout.TABLE), seen)
