"""M0d-1a walking: cwd sets, environment, wrappers, lock.py, s2v forms, opaque forms, expansions
(m0d1a-plan §10.1, §10.5-§10.10)."""

import os

from guard_base import GuardCase


class Cwd(GuardCase):
    def setUp(self):
        super().setUp()
        for d in ("x", "sub", "a", "b", "studio/work", "link-target/inner"):
            self.mk(d)
        os.symlink(os.path.join(self.root, "link-target", "inner"), os.path.join(self.root, "link"))
        self.R = lambda *p: os.path.join(self.root, *p)

    def cw(self, r, prog, i=0):
        return self.by_prog(r, prog)[i].cwds

    def test_hook_cwd_from_previous_call(self):
        # "앞선 호출에서 cd한 뒤 상대 경로 쓰기": the hook cwd already reflects the earlier cd
        r = self.ok("echo x > studio/work/state.json", cwd=self.R("sub"))
        self.assertEqual(r.commands[0].cwds, [self.R("sub")])
        r = self.ok("cd studio && echo x > work/state.json")
        self.assertEqual(self.one(r, "echo").cwds, [self.R("studio")])

    def test_subshell_and_group(self):
        r = self.ok("( cd x; rm y ); rm z")
        self.assertEqual([c.cwds for c in self.by_prog(r, "rm")], [[self.R("x")], [self.root]])
        r = self.ok("{ cd x; rm y; }; rm z")
        self.assertEqual([c.cwds for c in self.by_prog(r, "rm")], [[self.R("x")], [self.R("x")]])

    def test_cd_success_and_failure(self):
        self.assertEqual(self.cw(self.ok("cd x && touch y"), "touch"), [self.R("x")])
        self.assertEqual(self.cw(self.ok("cd nope && touch y"), "touch"), [self.R("nope")])
        self.assertEqual(self.cw(self.ok("cd nope; touch y"), "touch"), [self.R("nope"), self.root])
        self.assertEqual(self.cw(self.ok("cd x; touch y"), "touch"), [self.R("x")])
        self.assertEqual(self.cw(self.ok("cd nope || exit; touch y"), "touch"), [self.R("nope")])
        self.assertEqual(sorted(self.cw(self.ok("cd nope || true; touch y"), "touch")), sorted([self.R("nope"), self.root]))

    def test_home_and_tilde(self):
        home = self.env["HOME"]
        os.makedirs(os.path.join(home, "a"), exist_ok=True)
        self.assertEqual(self.cw(self.ok("cd; touch y"), "touch"), [home])
        self.assertEqual(self.cw(self.ok("cd ~/a; touch y"), "touch"), [os.path.join(home, "a")])
        r = self.ok("HOME=/tmp/h cd ~; touch y")
        self.assertEqual(self.cw(r, "touch"), [home])  # a prefix assignment is not used for expansion
        os.makedirs(os.path.join(self.tmp, "h2"))
        r = self.ok("export HOME=%s; cd ~; touch y" % os.path.join(self.tmp, "h2"))
        self.assertEqual(self.cw(r, "touch"), [os.path.join(self.tmp, "h2")])

    def test_cd_dash(self):
        self.assertEqual(self.cw(self.ok("cd x; cd -; touch y"), "touch"), [self.root])
        self.assertEqual(self.cw(self.ok("cd -; touch y"), "touch"), [])
        self.env["OLDPWD"] = self.R("a")
        self.assertEqual(self.cw(self.ok("cd -; touch y"), "touch"), [self.R("a")])

    def test_cd_idioms(self):
        os.makedirs(self.R(".git"))
        self.mk("sub", "deeper")
        r = self.ok('cd "$(git rev-parse --show-toplevel)"; touch y', cwd=self.R("sub", "deeper"))
        self.assertEqual(self.cw(r, "touch"), [os.path.realpath(self.root)])
        r = self.ok('cd "$(git -C .. rev-parse --show-toplevel)"; touch y', cwd=self.R("sub", "deeper"))
        self.assertEqual(self.cw(r, "touch"), [os.path.realpath(self.root)])
        self.assertEqual(self.cw(self.ok('cd "$PWD/a"; touch y'), "touch"), [self.R("a")])
        self.assertEqual(self.cw(self.ok('cd "$(dirname "$0")"; touch y'), "touch"), [])

    def test_logical_and_physical(self):
        self.assertEqual(self.cw(self.ok("cd ..; touch y", cwd=self.R("x")), "touch"), [self.root])
        self.assertEqual(self.cw(self.ok("cd link/..; touch y"), "touch"), [self.root])
        self.assertEqual(self.cw(self.ok("cd -P link; touch y"), "touch"),
                         [os.path.realpath(self.R("link-target", "inner"))])

    def test_pushd_popd_autopushd(self):
        self.mk("a", "b")
        self.assertEqual(self.cw(self.ok("pushd a; pushd b; popd; touch c"), "touch"), [self.R("a")])
        self.assertEqual(self.cw(self.ok("pushd a; pushd; touch c"), "touch"), [self.root])
        self.assertEqual(self.cw(self.ok("popd; touch c"), "touch"), [])
        self.assertEqual(self.cw(self.ok("pushd +1; touch c"), "touch"), [])
        # autopushd (default on): cd pushes too
        self.assertEqual(self.cw(self.ok("cd a; cd b; popd; touch c"), "touch"), [self.R("a")])

    def test_autopushd_off(self):
        self.use_snapshots(self.snapshot_text(unsetopts=("autopushd",)))
        self.assertEqual(self.cw(self.ok("cd a; cd b; popd; touch c"), "touch"), [])

    def snapshot_text(self, **kw):
        from guard_base import snapshot_text
        kw.setdefault("path", self.bin)
        return snapshot_text(**kw)

    def test_cdpath(self):
        self.env["CDPATH"] = "/somewhere"
        self.assertEqual(self.cw(self.ok("cd foo; touch y"), "touch"), [])
        self.assertEqual(self.cw(self.ok("cd ./x; touch y"), "touch"), [self.R("x")])
        del self.env["CDPATH"]
        for cmd in ("cdpath=(/x); cd foo; touch y", "cdpath+=(/x); cd foo; touch y", "CDPATH=/x; cd foo; touch y"):
            self.assertEqual(self.cw(self.ok(cmd), "touch"), [], cmd)

    def test_pipelines(self):
        self.assertEqual(self.cw(self.ok("true | cd x; touch y"), "touch"), [self.R("x")])
        # zsh runs the last element in the current shell: its variables persist, earlier ones do not
        self.assertEqual(self.one(self.ok("true | X=studio; rm -rf $X/local"), "rm").argv[-1], "studio/local")
        self.assertIsNone(self.one(self.ok("Y=studio | true; rm -rf $Y/local"), "rm").argv[-1])
        self.assertEqual(self.cw(self.ok("cd x | true; touch y"), "touch"), [self.root])

    def test_background(self):
        self.assertEqual(self.cw(self.ok("cd x & touch y"), "touch"), [self.root])

    def test_loops(self):
        r = self.ok("for d in a b; do cd $d; rm f; done; rm g")
        self.assertEqual([c.cwds for c in self.by_prog(r, "rm")], [[], []])
        r = self.ok("for d in a b; do rm $d; done; rm g")
        self.assertEqual([c.cwds for c in self.by_prog(r, "rm")], [[self.root], [self.root]])

    def test_if_branches(self):
        r = self.ok("if test -d x; then cd x; fi; rm y")
        self.assertEqual(sorted(self.cw(r, "rm")), sorted([self.R("x"), self.root]))

    def test_shadowed_cd(self):
        r = self.ok("cd(){ :; }; cd x; rm y")
        self.assertEqual(self.cw(r, "rm"), [])

    def test_source(self):
        r = self.ok("source ./env.sh; rm y")
        self.assertEqual(self.cw(r, "rm"), [])
        self.assertIn("env-unknown", self.one(r, "rm").flags)
        self.assertIn("source", self.kinds(r))

    def test_cwd_options(self):
        for cmd, prog in (("yarn --cwd sub x", "yarn"), ("yarn --cwd=sub x", "yarn"), ("npm --prefix sub run x", "npm"),
                          ("pnpm -C sub x", "pnpm"), ("make -C sub", "make"), ("tar -C sub -xf a.tar", "tar")):
            r = self.ok(cmd)
            c = r.commands[0]
            self.assertEqual(c.run_cwds, [self.R("sub")], cmd)
            self.assertEqual(c.cwds, [self.root], cmd)
        r = self.ok("env -C sub rm f")
        self.assertEqual(self.one(r, "rm").run_cwds, [self.R("sub")])

    def test_git_targets(self):
        r = self.ok("git -C a -C b status")
        g = self.one(r, "git")
        self.assertEqual(g.git.c_dirs, ["a", "b"])
        self.assertEqual(g.run_cwds, [self.R("a", "b")])
        r = self.ok("git --git-dir=../r/.git --work-tree=../r add x")
        g = self.one(r, "git").git
        self.assertEqual((g.git_dir, g.work_tree, g.sub), ("../r/.git", "../r", "add"))
        r = self.ok("GIT_DIR=../r/.git git status")
        self.assertIn("GIT_DIR", self.one(r, "git").git.env)
        r = self.ok("git -c alias.x='!rm -rf studio' x")
        self.assertEqual(self.one(r, "git").git.configs, [("alias.x", "!rm -rf studio")])
        r = self.ok("git -C sub clean -fdX src/")
        g = self.one(r, "git")
        self.assertEqual((g.git.sub, [w.value for w in g.git.args]), ("clean", ["-fdX", "src/"]))

    def test_symlinked_hook_cwd(self):
        r = self.ok("touch y", cwd=self.R("link"))
        self.assertEqual(r.commands[0].cwds, [self.R("link")])


class Env(GuardCase):
    def ops(self, c):
        return [(o.via, o.kind, o.name) for o in c.env.ops]

    def test_assignment_forms(self):
        r = self.ok("A=1 B=2 s2v x")
        self.assertEqual(self.ops(self.one(r, "s2v")), [("prefix", "set", "A"), ("prefix", "set", "B")])
        r = self.ok("A=1; s2v x")
        self.assertEqual(self.ops(self.one(r, "s2v")), [("assign", "set", "A")])
        r = self.ok("export A=1; declare -x B=2; typeset -x C=3; readonly D=4; export -n E; unset F; s2v x")
        self.assertEqual(self.ops(self.one(r, "s2v")),
                         [("export", "set", "A"), ("declare-x", "set", "B"), ("typeset-x", "set", "C"),
                          ("readonly", "set", "D"), ("export-n", "unset", "E"), ("unset", "unset", "F")])

    def test_env_wrapper(self):
        r = self.ok("env -u A s2v x; env -i s2v y; env -i A=1 s2v z; env - s2v w; env -- A=1 s2v v")
        cs = self.by_prog(r, "s2v")
        self.assertEqual(self.ops(cs[0]), [("env-u", "unset", "A")])
        self.assertTrue(cs[1].env.cleared)
        self.assertEqual(self.ops(cs[2]), [("env-i", "clear", None), ("env", "set", "A")])
        self.assertTrue(cs[3].env.cleared)
        self.assertEqual(self.ops(cs[4]), [("env", "set", "A")])
        r = self.ok("env -S 'rm studio/x' y")
        self.assertEqual(self.kinds(r), ["env-S"])

    def test_state_dir_and_home(self):
        r = self.ok("S2V_STATE_DIR=/x s2v tts a.md; HOME=/tmp/x s2v y")
        cs = self.by_prog(r, "s2v")
        self.assertEqual(cs[0].env.set["S2V_STATE_DIR"].value, "/x")
        self.assertEqual(cs[1].env.set["HOME"].value, "/tmp/x")
        r = self.ok("export S2V_STATE_DIR=/y; s2v z")
        self.assertEqual(self.one(r, "s2v").env.set["S2V_STATE_DIR"].value, "/y")
        r = self.ok("STUDIO_HOME=/z s2v q; unset CLAUDECODE; env -u CLAUDE_CODE_SESSION_ID git commit -m x")
        self.assertIn("STUDIO_HOME", self.one(r, "s2v").env.set)
        self.assertIn("CLAUDE_CODE_SESSION_ID", self.one(r, "git").env.unset)

    def test_known_variables(self):
        r = self.ok("X=studio; rm -rf $X/local")
        self.assertEqual(self.one(r, "rm").argv, ["rm", "-rf", "studio/local"])
        r = self.ok("X=a rm $X")
        self.assertIsNone(self.one(r, "rm").argv[1])  # X unset before: dynamic
        r = self.ok('rm "${X:-studio}/local"')
        w = self.one(r, "rm").words[1]
        self.assertTrue(w.dynamic)
        self.assertEqual(w.skeleton, "\0/local")

    def test_path_changes(self):
        r = self.ok("PATH=/tmp/bin:$PATH s2v x")
        self.assertIn("path-modified", self.one(r, "s2v").flags)
        for cmd in ("path=(/tmp/bin $path); s2v x", "path+=(/tmp/bin); s2v x", "path[1,0]=/tmp/bin; s2v x",
                    "export PATH=/opt/bin:/usr/bin; s2v x"):
            self.assertIn("path-modified", self.one(self.ok(cmd), "s2v").flags, cmd)
        r = self.ok("fpath+=(/tmp/f); foo")
        self.assertIn("fpath-changed", r.notes)

    def test_ifs(self):
        self.assertIn("ifs-changed", self.ok("IFS=/; echo x").notes)


class Wrappers(GuardCase):
    def test_builtins_precommands(self):
        r = self.ok("command rm x; command -v s2v; builtin cd /; exec rm y")
        rms = self.by_prog(r, "rm")
        self.assertEqual([[w.name for w in c.wrappers] for c in rms], [["command"], ["exec"]])
        q = [c for c in r.commands if "query" in c.flags]
        self.assertEqual(len(q), 1)
        r = self.ok("exec >log; exec 3>studio/x")
        self.assertEqual([c.redirs[0].target.value for c in r.commands], ["log", "studio/x"])

    def test_external_wrappers(self):
        for cmd in ("nohup rm x &", "time -p rm x", "/usr/bin/time -l rm x", "nice -n 5 rm x", "timeout 30 rm x",
                    "timeout -s KILL 5 rm x", "stdbuf -oL rm x", "caffeinate -i rm x", "noglob rm x"):
            r = self.ok(cmd)
            self.assertEqual(len(self.by_prog(r, "rm")), 1, cmd)
            self.assertEqual(self.by_prog(r, "rm")[0].argv, ["rm", "x"], cmd)

    def test_sudo(self):
        c = self.one(self.ok("sudo rm x"), "rm")
        self.assertTrue(c.env.cleared)
        c = self.one(self.ok("sudo -E rm x"), "rm")
        self.assertFalse(c.env.cleared)
        c = self.one(self.ok("sudo -u bob rm x"), "rm")
        self.assertEqual(c.wrappers[0].name, "sudo")
        self.assertEqual(self.kinds(self.ok("sudo -i rm x")), ["sudo-shell"])
        self.assertEqual(self.kinds(self.ok("sudo sh -c 'rm studio/x'")), ["shell-c"])

    def test_wrapper_chain(self):
        r = self.ok("sudo env -i nohup timeout 5 s2v tts a.md")
        c = self.one(r, "s2v")
        self.assertEqual([w.name for w in c.wrappers], ["sudo", "env", "nohup", "timeout"])
        self.assertTrue(c.env.cleared)

    def test_xargs_and_find(self):
        r = self.ok("xargs rm < list")
        t = [c for c in r.commands if "exec-template" in c.ctx]
        self.assertEqual(t[0].argv[:1], ["rm"])
        self.assertEqual(self.kinds(r), ["xargs"])
        r = self.ok("xargs -I{} cp {} studio/")
        self.assertEqual([h.term for h in r.opaque[0].hits], ["studio"])
        r = self.ok("find . -name x -exec rm {} \\; ; find . -exec rm {} + ; find . -execdir mv {} y \\; ; find . -ok rm {} \\;")
        self.assertEqual(self.kinds(r), ["find-exec"] * 4)
        r = self.ok("find studio -delete")
        self.assertEqual(r.opaque, [])
        self.assertEqual(self.one(r, "find").argv, ["find", "studio", "-delete"])

    def test_shadows(self):
        r = self.ok("alias rm='rm -rf studio'; rm x")
        self.assertIn("alias", self.kinds(r))
        self.assertIn("shadowed", [c for c in self.by_prog(r, "rm") if c.argv == ["rm", "x"]][0].flags)
        r = self.ok("hash -p /tmp/x rm; rm y")
        self.assertIn("shadowed", [c for c in self.by_prog(r, "rm") if c.argv == ["rm", "y"]][0].flags)
        r = self.ok("trap 'rm -rf studio/local' EXIT")
        self.assertEqual([h.term for h in r.opaque[0].hits], ["studio"])


class LockPy(GuardCase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.root, ".git"))
        self.lock = self.mk(".claude", "studio", "scripts", "lock.py", file=True, text="#!/usr/bin/env python3\n")
        self.mk("studio", "work", "v", "state.json", file=True)

    def test_run_child(self):
        r = self.ok("python3 .claude/studio/scripts/lock.py run --kind tts -- s2v tts v.md")
        lk = [c for c in r.commands if c.lock][0]
        self.assertEqual((lk.lock.sub, lk.lock.kind, lk.lock.verified, lk.lock.usage_error), ("run", "tts", True, None))
        child = self.one(r, "s2v")
        self.assertIn("lock-child", child.ctx)
        self.assertEqual(child.parent, lk.id)
        self.assertEqual(child.s2v.args[0].value, "tts")

    def test_actor_op_and_approve(self):
        r = self.ok("python3 .claude/studio/scripts/lock.py actor-op hero b -- s2v character approve hero")
        lk = [c for c in r.commands if c.lock][0]
        self.assertEqual(lk.lock.ids, ["hero", "b"])
        self.assertEqual([w.value for w in self.one(r, "s2v").s2v.args[:2]], ["character", "approve"])

    def test_cp_inside_wrapper(self):
        r = self.ok("python3 .claude/studio/scripts/lock.py run --kind tts -- cp a studio/work/v/state.json")
        cp = self.one(r, "cp")
        self.assertIn("lock-child", cp.ctx)
        self.assertEqual(cp.argv[-1], "studio/work/v/state.json")

    def test_usage_errors_still_expand(self):
        r = self.ok('python3 .claude/studio/scripts/lock.py run --kind=tts --holder "two words" -- s2v x')
        lk = [c for c in r.commands if c.lock][0]
        self.assertTrue(lk.lock.usage_error)
        self.assertTrue(self.by_prog(r, "s2v"))
        r = self.ok("python3 .claude/studio/scripts/lock.py run --kind tts s2v x")
        self.assertTrue([c for c in r.commands if c.lock][0].lock.usage_error)
        self.assertEqual(self.by_prog(r, "s2v"), [])
        r = self.ok("python3 .claude/studio/scripts/lock.py status --json")
        self.assertEqual([c for c in r.commands if c.lock][0].lock.sub, "status")

    def test_env_inherited(self):
        r = self.ok("S2V_STATE_DIR=/x python3 .claude/studio/scripts/lock.py run --kind tts -- s2v x")
        self.assertEqual(self.one(r, "s2v").env.set["S2V_STATE_DIR"].value, "/x")

    def test_invocation_forms(self):
        os.chmod(self.lock, 0o755)
        for cmd in ("./.claude/studio/scripts/lock.py run --kind tts -- s2v x",
                    "%s run --kind tts -- s2v x" % self.lock,
                    "python3 -u .claude/studio/scripts/lock.py run --kind tts -- s2v x",
                    "env python3 .claude/studio/scripts/lock.py run --kind tts -- s2v x"):
            r = self.ok(cmd)
            lk = [c for c in r.commands if c.lock]
            self.assertTrue(lk and lk[0].lock.verified, cmd)
            self.assertTrue(self.by_prog(r, "s2v"), cmd)

    def test_unverified_lock(self):
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        with open(os.path.join(other, "lock.py"), "w") as f:
            f.write("")
        r = self.ok("python3 %s/lock.py run --kind tts -- s2v x" % other)
        self.assertFalse([c for c in r.commands if c.lock][0].lock.verified)
        self.assertTrue(self.by_prog(r, "s2v"))

    def test_nesting(self):
        L = "python3 .claude/studio/scripts/lock.py run --kind tts --"
        r = self.ok("%s %s %s s2v x" % (L, L, L))
        self.assertEqual(len(self.by_prog(r, "s2v")), 1)
        r = self.ok("%s %s %s %s s2v x" % (L, L, L, L))
        self.assertEqual(self.by_prog(r, "s2v"), [])
        self.assertIn("lock-depth", r.notes)

    def test_lockargs_matches_lockcli(self):
        from stdo import lockargs, lockcli, locks
        self.assertIs(lockcli._parse, lockargs.parse)
        for argv in (["run", "--kind", "tts", "--", "s2v"], ["actor-op", "a", "--", "s2v"], ["status", "--json"],
                     ["run", "--kind=tts", "--", "s2v"], ["run", "--kind", "tts"], []):
            try:
                lockargs.parse(argv)
            except locks.UsageError:
                pass


class S2vForms(GuardCase):
    def setUp(self):
        super().setUp()
        self.p = os.path.join(self.tmp, "s2v")
        os.makedirs(os.path.join(self.p, "packages", "cli", "dist"))
        os.makedirs(os.path.join(self.p, "packages", "cli", "src"))
        self.main = os.path.join(self.p, "packages", "cli", "dist", "main.js")
        with open(self.main, "w") as f:
            f.write("#!/usr/bin/env node\n")
        os.chmod(self.main, 0o755)
        open(os.path.join(self.p, "packages", "cli", "src", "main.ts"), "w").close()

    def form(self, cmd, cwd=None):
        r = self.ok(cmd, cwd=cwd, s2v_path=self.p)
        c = [c for c in r.commands if c.s2v]
        self.assertTrue(c, cmd)
        return c[0].s2v

    def test_name_verified_by_path(self):
        self.exe("s2v", target=self.main)
        f = self.form("s2v tts a.md")
        self.assertEqual((f.form, f.accepted, f.verified), ("name", True, True))
        os.remove(os.path.join(self.bin, "s2v"))
        self.exe("s2v")
        f = self.form("s2v tts a.md")
        self.assertEqual((f.form, f.verified), ("name", False))
        os.remove(os.path.join(self.bin, "s2v"))
        self.assertFalse(self.form("s2v x").verified)

    def test_node_tsx(self):
        self.assertTrue(self.form("node %s tts" % self.main).accepted)
        self.assertTrue(self.form("node packages/cli/dist/main.js tts", cwd=self.p).accepted)
        rel = os.path.relpath(self.main, self.root)
        self.assertTrue(self.form("node %s tts" % rel).accepted)
        self.assertTrue(self.form("cd %s && node packages/cli/dist/main.js x" % self.p).accepted)
        self.assertTrue(self.form("tsx %s/packages/cli/src/main.ts x" % self.p).accepted)

    def test_runners(self):
        f = self.form("yarn --cwd %s s2v tts a.md" % self.p)
        self.assertEqual((f.form, f.accepted), ("yarn", True))
        self.assertEqual(self.form("yarn s2v x", cwd=self.p).accepted, True)
        f = self.form("yarn s2v x")
        self.assertEqual((f.form, f.accepted), ("yarn", False))
        for cmd in ("yarn run s2v x", "yarn --cwd=%s s2v x" % self.p, "npx -y s2v x", "pnpm s2v x", "bunx s2v x",
                    "npm exec s2v x"):
            f = self.form(cmd)
            self.assertEqual(f.form, "runner-other", cmd)
            self.assertFalse(f.accepted, cmd)
        self.assertTrue(self.form("npx s2v x", cwd=self.p).accepted)

    def test_paths_and_case(self):
        self.exe("s2v-real", target=self.main)
        f = self.form("%s/s2v-real x" % self.bin) if False else None
        link = os.path.join(self.tmp, "s2v")
        f = self.form("%s x" % os.path.join(self.p, "packages", "cli", "dist", "main.js"))
        self.assertEqual((f.form, f.verified), ("direct-main", True))
        lb = os.path.join(self.tmp, "lb")
        os.makedirs(lb)
        os.symlink(self.main, os.path.join(lb, "s2v"))
        f = self.form("%s/s2v x" % lb)
        self.assertEqual((f.form, f.verified), ("path-bin", True))
        other = os.path.join(self.tmp, "ob")
        os.makedirs(other)
        open(os.path.join(other, "s2v"), "w").close()
        self.assertFalse(self.form("%s/s2v x" % other).verified)
        f = self.form("S2V tts")
        self.assertEqual((f.form, f.accepted), ("name", False))
        del link

    def test_dynamic_and_prefixes(self):
        r = self.ok('"$S2V" tts', s2v_path=self.p)
        self.assertEqual(self.kinds(r), ["dynamic-command"])
        r = self.ok("$(which s2v) tts", s2v_path=self.p)
        self.assertIn("dynamic-command", self.kinds(r))
        self.assertIn("s2v", [h.term for o in r.opaque for h in o.hits])
        for cmd in ("command s2v x", "exec s2v x", "env s2v x"):
            self.assertEqual(self.form(cmd).form, "name", cmd)


class Opaques(GuardCase):
    def test_eval(self):
        r = self.ok('eval "rm studio/x"')
        self.assertEqual([h.term for h in r.opaque[0].hits], ["studio"])
        r = self.ok('eval "$x"')
        self.assertTrue(r.opaque[0].hits_unknown)
        self.assertEqual(self.ok("eval echo hi").opaque[0].hits, [])

    def test_shell_c(self):
        for cmd in ("bash -c 'rm studio/x'", "zsh -lc 'rm studio/x'", "bash -ec 'rm studio/x'", "bash -xc 'rm studio/x'"):
            r = self.ok(cmd)
            self.assertEqual(self.kinds(r), ["shell-c"], cmd)
            self.assertEqual([h.term for h in r.opaque[0].hits], ["studio"], cmd)
        self.assertEqual(self.ok("sh -c 'ls'").opaque[0].hits, [])

    def test_inline_interpreters(self):
        r = self.ok("python3 -c \"open('studio/work/v/state.json','w')\"")
        o = r.opaque[0]
        self.assertEqual(o.kind, "interp-inline")
        self.assertIn("studio/work/v/state.json", o.literals)
        for cmd in ("python -c 'x'", "python3.12 -c 'x'", "node -e 'x'", "node --eval='x'", "node -p 'x'",
                    "perl -e 'x'", "ruby -e 'x'", "php -r 'x'", "osascript -e 'x'", "deno eval 'x'", "bun -e 'x'"):
            self.assertEqual(self.kinds(self.ok(cmd)), ["interp-inline"], cmd)

    def test_outside_studio_passes(self):
        # "Studio 밖의 python -c · heredoc은 통과": opaque but no Studio terms
        for cmd in ("python3 -c 'print(1)'", "python3 - <<'EOF'\nimport json\nEOF\n"):
            r = self.ok(cmd)
            self.assertTrue(r.opaque, cmd)
            self.assertEqual(r.opaque[0].hits, [], cmd)

    def test_pipes_into_shells(self):
        r = self.ok("echo 'rm studio/x' | sh")
        self.assertEqual((r.opaque[0].kind, r.opaque[0].origin), ("stdin-interp", "pipe-literal"))
        self.assertEqual([h.term for h in r.opaque[0].hits], ["studio"])
        r = self.ok("curl https://example.invalid/x | bash")
        self.assertTrue([o for o in r.opaque if o.kind == "stdin-interp"][0].hits_unknown)

    def test_stdin_targets(self):
        for cmd, origin in (("source /dev/stdin <<'EOF'\nrm -rf studio/local\nEOF\n", "heredoc"),
                            (". /dev/fd/0 <<< 'rm studio/x'", "herestring"),
                            ("python3 /dev/stdin <<EOF\nopen('studio/x')\nEOF\n", "heredoc"),
                            ("python3 - <<< 'open(\"studio/x\")'", "herestring"),
                            ("bash -s <<'EOF'\nrm studio/x\nEOF\n", "heredoc"),
                            ("bash -s -- a b <<EOF\nrm studio/x\nEOF\n", "heredoc"),
                            ("zsh -s <<< 'rm studio/x'", "herestring"),
                            ("node - <<EOF\nrequire('fs').rmSync('studio/x')\nEOF\n", "heredoc")):
            r = self.ok(cmd)
            o = [x for x in r.opaque][0]
            self.assertEqual(o.origin, origin, cmd)
            self.assertEqual([h.term for h in o.hits], ["studio"], cmd)
        self.mk("f.sh", file=True, text="rm studio/x\n")
        r = self.ok("source /dev/stdin < f.sh")
        self.assertEqual(r.opaque[0].origin, "file")
        r = self.ok("echo 'rm studio/x' | source /dev/stdin")
        self.assertEqual(r.opaque[0].origin, "pipe-literal")

    def test_devnull_stdin(self):
        # the Bash tool runs `eval '<cmd>' < /dev/null`: a bare interpreter reads nothing
        r = self.ok("python3")
        self.assertEqual((r.opaque[0].origin, r.opaque[0].payload), ("devnull", ""))

    def test_scripts(self):
        self.mk("work", "run.sh", file=True, text="#!/bin/sh\nrm -rf studio/local\n")
        self.mk("scripts", "x.sh", file=True, text="#!/bin/sh\necho hi\n")
        r = self.ok("bash ./work/run.sh")
        o = r.opaque[0]
        self.assertEqual((o.kind, o.origin), ("script", "file"))
        self.assertEqual([h.term for h in o.hits], ["studio"])
        self.assertEqual(self.ok("./scripts/x.sh").opaque[0].hits, [])
        r = self.ok("bash /tmp/does-not-exist-%d.sh" % os.getpid())
        self.assertTrue(r.opaque[0].hits_unknown)
        self.assertEqual(r.opaque[0].path_class, ["tmp"])

    def test_awk_sed(self):
        self.assertEqual(self.ok("awk '{print $1}' f").opaque, [])
        self.assertEqual(self.kinds(self.ok("awk 'BEGIN{system(\"rm x\")}'")), ["awk-program"])
        self.assertEqual(self.ok("sed -i 's/a/b/' f").opaque, [])
        self.assertEqual(self.kinds(self.ok("sed 'e rm x' f")), ["sed-exec"])

    def test_misc(self):
        self.assertEqual(self.kinds(self.ok("parallel rm ::: a b")), ["parallel"])
        self.assertEqual(self.kinds(self.ok("watch -n1 ls")), ["watch"])

    def test_case_and_unicode_terms(self):
        from stdo.guard.terms import Terms
        t = Terms(paths=["studio/local"], words=["local"], fold=True)
        self.assertTrue(t.find("rm -rf STUDIO/LOCAL"))
        self.assertEqual(t.find("curl localhost"), [])
        nfd = Terms(paths=["스튜디오"]).find("rm 스튜디오/x")
        self.assertTrue(nfd)


class Expansion(GuardCase):
    def test_globs(self):
        w = self.one(self.ok("rm studio/*"), "rm").words[1]
        self.assertEqual((w.glob, w.glob_base), (True, "studio/"))
        w = self.one(self.ok("rm stud*"), "rm").words[1]
        self.assertEqual((w.glob, w.glob_base), (True, ""))
        self.assertTrue(self.one(self.ok("rm studio/**/x"), "rm").words[1].glob)
        self.assertTrue(self.one(self.ok("rm [s]tudio"), "rm").words[1].glob)
        self.assertFalse(self.one(self.ok("rm 'studio/*'"), "rm").words[1].glob)

    def test_braces(self):
        self.assertEqual(self.one(self.ok("rm studio/{a,b}.json"), "rm").argv,
                         ["rm", "studio/a.json", "studio/b.json"])
        self.assertEqual(self.one(self.ok("echo {1..3}"), "echo").argv, ["echo", "1", "2", "3"])
        self.assertEqual(self.one(self.ok("echo {a,{b,c}}"), "echo").argv, ["echo", "a", "b", "c"])
        w = self.one(self.ok("echo {1..100000}"), "echo").words[1]
        self.assertEqual(w.dyn, ["brace-overflow"])
        self.assertEqual(self.one(self.ok("echo '{a,b}'"), "echo").argv, ["echo", "{a,b}"])

    def test_tildes(self):
        home = self.env["HOME"]
        self.assertEqual(self.one(self.ok("ls ~ ~/x"), "ls").argv, ["ls", home, home + "/x"])
        self.assertTrue(self.one(self.ok("ls ~root"), "ls").words[1].dynamic)
        w = self.one(self.ok("cp a --out=~/x"), "cp").words[2]
        self.assertEqual((w.value, w.alt), ("--out=~/x", "--out=%s/x" % home))
        c = self.one(self.ok("X=~/x s2v"), "s2v")
        self.assertEqual(c.env.set["X"].value, home + "/x")
        r = self.ok("export X=a:~/b; s2v")
        self.assertEqual(self.one(r, "s2v").env.set["X"].value, "a:%s/b" % home)

    def test_equals_forms(self):
        w = self.one(self.ok("echo =~"), "echo").words[1]
        self.assertEqual((w.value, w.alt), ("=~", "\0"))
        self.assertEqual(self.one(self.ok("echo =git"), "echo").argv[1], os.path.join(self.bin, "git"))
        self.assertTrue(self.one(self.ok("echo =nope"), "echo").words[1].dynamic)

    def test_arith_eval(self):
        for cmd in ("i='$(rm -rf studio)'; echo $(( i ))", "i='$(rm -rf studio)'; a[$i]=1",
                    "i='$(rm -rf studio)'; (( i > 0 ))", "i='$(rm -rf studio)'; let i+1",
                    "i='$(rm -rf studio)'; [[ $i -eq 1 ]]"):
            r = self.ok(cmd)
            self.assertIn("arith-eval", self.kinds(r), cmd)
            self.assertEqual([h.term for o in r.opaque if o.kind == "arith-eval" for h in o.hits][:1], ["studio"], cmd)
        self.assertEqual(self.ok("i=3; echo $((i+1))").opaque, [])

    def test_dynamic_skeleton(self):
        r = self.ok('rm "$(echo studio)"/local')
        w = self.one(r, "rm").words[1]
        self.assertTrue(w.dynamic)
        self.assertEqual(w.skeleton, "\0/local")
        self.assertTrue([c for c in r.commands if c.prog == "echo"])

    def test_backslash_command_names(self):
        for cmd in ("\\rm x", "r\\m x", "'r'm x", "$'\\x72m' x", "command rm x", "/bin/rm x", "env rm x", "exec rm x"):
            self.assertEqual(self.ok(cmd).commands[-1].prog, "rm", cmd)


class Review1(GuardCase):
    """Implementation review round 1: when unsure, the value is dynamic/unknown."""

    def setUp(self):
        super().setUp()
        for d in ("x", "a/b", "b", "t/inner"):
            self.mk(d)
        os.symlink(os.path.join(self.root, "t", "inner"), os.path.join(self.root, "link"))
        self.R = lambda *p: os.path.join(self.root, *p)

    def test_zsh_modifiers_and_flags(self):  # MJ-1
        for cmd in ("X=/a/b.c; rm $X:h", "X=/a/b.c; rm $X:s/a/z/", 'X=/a/b.c; rm "$X:u"', "X=/a; rm $X:t:r",
                    "X=a; rm $=X", "X=a; rm $~X", "X=a; rm $^X", "X=a; rm $+X", "X=a; rm ${=X}", "X=a; rm $==X"):
            self.assertIsNone(self.one(self.ok(cmd), "rm").argv[1], cmd)
        self.assertEqual(self.one(self.ok("X=/a; rm ${X}:h"), "rm").argv[1], "/a:h")
        self.assertEqual(self.one(self.ok("X=/a; rm $X:/b"), "rm").argv[1], "/a:/b")  # ':' + '/' is no modifier

    def test_tilde_plus_minus(self):  # MJ-1
        self.assertEqual(self.one(self.ok("ls ~+ ~+/q"), "ls").argv[1:], [self.root, self.root + "/q"])
        r = self.ok("cd ~+/x; touch y")
        self.assertEqual(self.one(r, "touch").cwds, [self.R("x")])
        self.assertEqual(self.one(self.ok("cd x; ls ~-"), "ls").argv[1], self.root)
        self.assertIsNone(self.one(self.ok("ls ~-"), "ls").argv[1])
        self.assertIsNone(self.one(self.ok("ls ~+2"), "ls").argv[1])
        r = self.ok("for d in a; do cd $d; done; ls ~+")
        self.assertIsNone(self.one(r, "ls").argv[1])

    def test_eval_makes_cwd_unknown(self):  # MJ-2
        r = self.ok("eval 'cd x'; touch y")
        self.assertEqual(self.one(r, "touch").cwds, [])
        self.assertIn("env-unknown", self.one(r, "touch").flags)
        r = self.ok("emulate sh -c 'rm studio/a'; touch y")
        self.assertEqual(self.kinds(r), ["eval"])
        self.assertEqual([h.term for h in r.opaque[0].hits], ["studio"])
        self.assertEqual(self.one(r, "touch").cwds, [])

    def test_anonymous_functions(self):  # MJ-2
        for cmd in ("function { rm a }", "function () { rm a; }", "() { rm a }", "() rm a"):
            r = self.scan(cmd)
            self.assertEqual((r.status, r.reason.split("@")[0]), ("unparsable", "unsupported:zsh-anon-function"), cmd)

    def test_cd_prefix_cdpath(self):  # MJ-3
        for cmd in ("CDPATH=/x cd b; touch y", "cdpath=/x cd ./b; touch y", "CDPATH=/x pushd b; touch y"):
            self.assertEqual(self.one(self.ok(cmd), "touch").cwds, [], cmd)

    def test_cd_physical(self):  # MJ-3
        real_t = os.path.realpath(self.R("t"))
        self.assertEqual(self.one(self.ok("cd -P link/..; touch y"), "touch").cwds, [real_t])
        self.assertEqual(self.one(self.ok("cd -LP link/..; touch y"), "touch").cwds, [real_t])
        self.assertEqual(self.one(self.ok("setopt chaselinks; cd link/..; touch y"), "touch").cwds, [real_t])
        self.assertEqual(self.one(self.ok("set -o chaselinks; cd link/..; touch y"), "touch").cwds, [real_t])
        self.assertEqual(self.one(self.ok("cd link/..; touch y"), "touch").cwds, [self.root])
        self.assertEqual(self.one(self.ok("emulate zsh; cd link/..; touch y"), "touch").cwds, [])
        from guard_base import snapshot_text
        self.use_snapshots(snapshot_text(options=("chaselinks",), path=self.bin), snapshot_text(path=self.bin))
        self.assertEqual(self.one(self.ok("cd link/..; touch y"), "touch").cwds, [])

    def test_options_changing_words(self):  # MINOR 1
        for cmd in ("setopt shwordsplit; X=a; rm $X", "unsetopt shwordsplit; X=a; rm $X", "setopt SH_WORD_SPLIT; X=a; rm $X",
                    "set -o globsubst; X=a; rm $X", "setopt rcexpandparam; X=a; rm $X", "emulate sh; X=a; rm $X",
                    "setopt $opt; X=a; rm $X"):
            self.assertIsNone(self.one(self.ok(cmd), "rm").argv[1], cmd)
        self.assertEqual(self.one(self.ok('setopt shwordsplit; X=a; rm "$X"'), "rm").argv[1], "a")
        self.assertIsNone(self.one(self.ok("setopt ignorebraces; rm {a,b}"), "rm").argv[1])
        self.assertEqual(self.one(self.ok("setopt autopushd; X=a; rm $X"), "rm").argv[1], "a")

    def test_disable_cd(self):  # NIT
        r = self.ok("disable cd; cd x; touch y")
        self.assertEqual(self.one(r, "touch").cwds, [])

    def test_exec_by_program_marker(self):  # MINOR 4 (G20)
        os.makedirs(self.R(".git"))
        self.mk(".claude", "studio", "scripts", "lock.py", file=True)
        r = self.ok("env rm a; xargs rm; python3 .claude/studio/scripts/lock.py run --kind tts -- rm b; "
                    "find . -exec rm {} +; rm c")
        flags = {tuple(c.argv): "exec-by-program" in c.flags for c in self.by_prog(r, "rm")}
        self.assertEqual(flags[("rm", "a")], True)
        self.assertEqual(flags[("rm", "b")], True)
        self.assertEqual(flags[("rm", "c")], False)
        self.assertTrue(all(v for k, v in flags.items() if None in k))


class Review2(GuardCase):
    def setUp(self):
        super().setUp()
        self.mk("a")
        self.mk("b")

    def test_failing_move_leaves_stack_unknown(self):  # MINOR 1
        self.assertEqual(self.one(self.ok("pushd x; pushd b; popd; touch c"), "touch").cwds, [])
        self.assertEqual(self.one(self.ok("cd nope; cd a; popd; touch c"), "touch").cwds, [])
        self.assertEqual(self.one(self.ok("cd a; cd ../b; popd; touch c"), "touch").cwds,
                         [os.path.join(self.root, "a")])

    def test_function_options_leak(self):  # MINOR 2
        r = self.ok("f() { setopt shwordsplit }; f; X='a b'; rm $X")
        self.assertIsNone([c for c in self.by_prog(r, "rm")][-1].argv[1])
        for body in ("unsetopt shwordsplit", "emulate sh", "set -o globsubst"):
            r = self.ok("f() { %s; }; f; X=a; rm $X" % body)
            self.assertIsNone(self.by_prog(r, "rm")[-1].argv[1], body)
        for body in ("emulate -L zsh; setopt shwordsplit", "setopt localoptions shwordsplit"):
            r = self.ok("f() { %s; }; f; X=a; rm $X" % body)
            self.assertEqual(self.by_prog(r, "rm")[-1].argv[1], "a", body)
        r = self.ok("f() { setopt shwordsplit }; X=a; rm $X")  # defined, never called
        self.assertEqual(self.by_prog(r, "rm")[-1].argv[1], "a")
