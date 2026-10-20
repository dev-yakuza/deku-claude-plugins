"""M0d-1a parser: structure, nesting, compound commands, failures (m0d1a-plan §10.4, §10.12)."""

import os

from guard_base import GuardCase
from stdo.guard import limits


class Structure(GuardCase):
    def setUp(self):
        super().setUp()
        for d in ("a/b", "x", "sub"):
            self.mk(d)

    def test_nested_subshells(self):
        r = self.ok("( ( cd a; ( cd b; rm c ) ); rm d )")
        self.assertEqual(self.one(r, "rm").cwds if False else [c.cwds for c in self.by_prog(r, "rm")],
                         [[os.path.join(self.root, "a", "b")], [self.root]])

    def test_depth_limit(self):
        ok = "( " * 30 + "true" + " )" * 30
        self.ok(ok)
        deep = "( " * 70 + "true" + " )" * 70
        r = self.scan(deep)
        self.assertEqual((r.status, r.reason), ("unparsable", "limit:depth"))

    def test_substitution_cd_does_not_leak(self):
        r = self.ok("echo $(cd x && pwd); rm y")
        self.assertEqual(self.one(r, "rm").cwds, [self.root])

    def test_subshell_vs_arith(self):
        r = self.ok("echo $( (cd x) ) $((1+2))")
        self.assertEqual(self.one(r, "cd").ctx, ["cmdsubst", "subshell"])
        r = self.ok("(( 1 + 2 )); ( (cd x) )")
        self.assertTrue(self.by_prog(r, "cd"))

    def test_nested_backticks(self):
        r = self.ok("echo `echo \\`pwd\\``")
        self.assertEqual(sorted(c.prog for c in r.commands), ["echo", "echo", "pwd"])

    def test_paren_inside_substitution(self):
        r = self.ok('echo $(echo ")") $(case x in a) echo;; esac)')
        self.assertEqual(len(self.by_prog(r, "echo")), 3)

    def test_unbalanced(self):
        for cmd, code in (("echo (", "syntax"), ("echo )", "syntax"), ("echo $(ls", "syntax"), ("echo `ls", "unterminated-backtick"),
                          ("echo ${x", "unterminated-brace"), ("echo 'x", "unterminated-quote"),
                          ('echo "x', "unterminated-quote"), ("( ls", "syntax")):
            r = self.scan(cmd)
            self.assertEqual(r.status, "unparsable", cmd)
            self.assertTrue(r.reason.startswith(code), (cmd, r.reason))
            self.assertEqual([o.kind for o in r.opaque], ["unparsable"])
            self.assertEqual(r.commands, [])

    def test_unparsable_keeps_raw_hits(self):
        r = self.scan("rm -rf studio/local 'unterminated")
        self.assertEqual(r.status, "unparsable")
        self.assertEqual([h.term for h in r.opaque[0].hits], ["studio"])

    def test_zsh_group_without_semicolon(self):
        r = self.ok("{ rm x }; { rm y; }")
        self.assertEqual([c.argv for c in self.by_prog(r, "rm")], [["rm", "x"], ["rm", "y"]])

    def test_control_structures(self):
        r = self.ok("if test -d a; then rm a1; elif false; then rm a2; else rm a3; fi")
        self.assertEqual(len(self.by_prog(r, "rm")), 3)
        r = self.ok("for f in a b; do rm $f; done; while read f; do rm \"$f\"; done < list; until true; do :; done")
        self.assertEqual(len(self.by_prog(r, "rm")), 2)
        r = self.ok("select x in a b; do echo $x; done")
        self.assertTrue(self.by_prog(r, "echo"))
        r = self.ok("case $x in (a|b) rm one;; c) rm two;& *) rm three;;& esac")
        self.assertEqual(len(self.by_prog(r, "rm")), 3)

    def test_dbracket_and_arith_are_not_redirections(self):
        r = self.ok("[[ a < b && -f studio/x ]] && (( x > 3 )) && [ a \\> b ]")
        for c in r.commands:
            self.assertEqual(c.redirs, [], c.argv)

    def test_negation_time_background(self):
        r = self.ok("! rm x; time -p rm y; rm z &")
        z = [c for c in self.by_prog(r, "rm") if c.argv[1] == "z"][0]
        self.assertIn("background", z.ctx)

    def test_process_substitution(self):
        r = self.ok("diff <(cat a) <(cat studio/b)")
        cats = self.by_prog(r, "cat")
        self.assertEqual([c.ctx for c in cats], [["procsubst"], ["procsubst"]])
        self.assertTrue(self.one(r, "diff").words[1].dynamic)
        r = self.ok("tee >(cat > studio/x)")
        w = [c for c in r.commands if c.prog == "cat"][0]
        self.assertEqual(w.redirs[0].target.value, "studio/x")

    def test_function_definitions(self):
        r = self.ok("f(){ rm -rf studio/local; }; f")
        body = [c for c in r.commands if c.prog == "rm"][0]
        self.assertIn("function-body", body.ctx)
        self.assertIn("inline-function", self.one(r, "f").flags)
        r = self.ok("function g { rm a; }; function h () { rm b; }")
        self.assertEqual(len(self.by_prog(r, "rm")), 2)
        r = self.ok("git(){ rm x; }; git status")
        self.assertIn("shadowed", [c for c in r.commands if c.prog == "git"][0].flags)

    def test_multiline_with_comments(self):
        r = self.ok("# top\nrm a  # one\n\n\n# two\nrm b\n")
        self.assertEqual(len(self.by_prog(r, "rm")), 2)

    def test_zsh_only_syntax_is_unsupported(self):
        for cmd in ("rm *(.)", "ls @(a|b)", "for x (a b) echo $x", "repeat 3 echo", "diff =(ls) x"):
            r = self.scan(cmd)
            self.assertEqual(r.status, "unparsable", cmd)
            self.assertTrue(r.reason.startswith("unsupported:"), (cmd, r.reason))

    def test_coproc(self):
        r = self.ok("coproc rm x")
        self.assertIn("coproc", self.kinds(r))
        self.assertTrue(self.by_prog(r, "rm"))


class Failures(GuardCase):
    def test_size_limit(self):
        r = self.scan("echo " + "a" * limits.MAX_INPUT)
        self.assertEqual((r.status, r.reason), ("unparsable", "limit:size"))

    def test_command_limit(self):
        r = self.scan(";".join(["true"] * (limits.MAX_COMMANDS + 1)))
        self.assertEqual((r.status, r.reason), ("unparsable", "limit:commands"))

    def test_budget_cpu_and_wall(self):
        clock = {"t": 0.0}

        def cpu():
            clock["t"] += 0.5
            return clock["t"]
        b = limits.Budget(cpu_clock=cpu, wall_clock=lambda: 0.0)
        r = self.scan(";".join(["echo x"] * 2000), budget=b)
        self.assertEqual((r.status, r.reason), ("unparsable", "limit:budget"))
        wall = {"t": 0.0}

        def slow():
            wall["t"] += 1.0
            return wall["t"]
        b = limits.Budget(cpu_clock=lambda: 0.0, wall_clock=slow)
        r = self.scan(";".join(["echo x"] * 2000), budget=b)
        self.assertEqual((r.status, r.reason), ("unparsable", "limit:budget"))
        b = limits.Budget(cpu_clock=lambda: 0.0, wall_clock=lambda: 3.0)
        self.assertEqual(self.scan("echo x", budget=b).status, "ok")

    def test_fs_call_limit(self):
        from stdo.guard.where import FS
        r = self.scan("cd a; cd b; ls", fs=FS(max_calls=3))
        self.assertEqual((r.status, r.reason), ("unparsable", "limit:fs-calls"))

    def test_internal_error_never_escapes(self):
        from stdo.guard.where import FS

        class Boom(FS):
            def stat(self, path):
                raise KeyError("boom")
        r = self.scan("rm -rf studio/local; cd x", fs=Boom())
        self.assertEqual(r.status, "error")
        self.assertTrue(r.reason.startswith("internal:"))
        self.assertEqual([o.kind for o in r.opaque], ["unparsable"])
        self.assertEqual([h.term for h in r.raw_hits], ["studio"])

    def test_pathological_inputs_end_quickly(self):
        import time
        for text in ("(" * 10000, "$(" * 100, "'a'" * 10000, "\\" * 100000, "{" * 5000 + "a,b" + "}" * 5000):
            t = time.monotonic()
            r = self.scan(text)
            self.assertLess(time.monotonic() - t, 3.0)
            self.assertIn(r.status, ("ok", "unparsable"))

    def test_linear_time(self):
        import time

        def run(n):
            t = time.process_time()
            self.scan(";".join(["echo 'x' \"y\" $z"] * n))
            return time.process_time() - t
        a, b = run(300), run(600)
        self.assertLess(b, a * 3 + 0.05)

    def test_big_heredoc_file_write(self):
        import time
        body = ("x" * 99 + "\n") * 10000
        t = time.process_time()
        r = self.ok("cat > out.txt <<'EOF'\n%sEOF\n" % body)
        self.assertLess(time.process_time() - t, 1.0)
        self.assertEqual(len(r.commands[0].redirs[1].body), len(body))
