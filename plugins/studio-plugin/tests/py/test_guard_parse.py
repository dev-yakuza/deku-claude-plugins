"""M0d-1a parser: structure, nesting, compound commands, failures (m0d1a-plan §10.4, §10.12)."""

import os

from guard_base import GuardCase, snapshot_text
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

    def test_function_with_several_names(self):  # G1 review 5 M4: `function a b { … }` defines both
        r = self.ok("function x y { rm a; }; y")
        self.assertIn("inline-function", self.one(r, "y").flags)
        r = self.ok("function x y\nrm a\ny")
        self.assertIn("inline-function", self.one(r, "y").flags)

    def test_reserved_word_after_assignments(self):  # G1 review 5 R1: zsh reads `}`/`fi`/`done` after `X=v`
        for cmd in ("{ X=v }; rm a", "f(){ X=v }; f; rm a", "if true; then X=v fi; rm a",
                    "for i in 1; do X=v done; rm a", "{ X=v > /dev/null }; rm a", "if true; then > /dev/null fi; rm a"):
            r = self.ok(cmd)
            self.assertEqual(len(self.by_prog(r, "rm")), 1, cmd)
        r = self.ok("{ rm a } always { rm b }; rm c")  # `always`: both lists run
        self.assertEqual(len(self.by_prog(r, "rm")), 3)

    def test_review6_forms(self):
        # conf M-1: the operand after `=~` is a regular expression; balanced `( … )` and `|` are part of it
        for cmd in ("[[ $b =~ ^feature/(.*)$ ]] && rm a", "[[ $x =~ ^v([0-9]+)$ ]] && rm a",
                    "[[ ( $x =~ ^a(b|c)$ ) && -n $y ]] && rm a"):
            self.assertEqual(len(self.by_prog(self.ok(cmd), "rm")), 1, cmd)
        # M10: zsh's short loop and brace forms are unsupported (refused in a Studio repository)
        for cmd in ("for i in x; rm a", "for ((i=0;i<1;i++)) rm a", "while (( 1 )) { rm a; break }", "if true { rm a }",
                    "case x { (x) rm a ;; }", "until false { rm a }", "if true; then :; elif true { rm a }; fi"):
            r = self.scan(cmd)
            self.assertEqual((r.status, r.reason.split("@")[0][:18]), ("unparsable", "unsupported:zsh-sh"), cmd)
        # M3: `0=…` and `1=…` are assignments; M4: an `s` modifier's text keeps its quotes
        r = self.ok("0=x; 1=y; rm a")
        self.assertEqual(len(self.by_prog(r, "rm")), 1)
        r = self.ok("rm $X:s/a/'b c'/ $X:gs/a/b/")
        self.assertEqual(len(self.by_prog(r, "rm")[0].words), 3)
        # an alias in `$(…)` is spliced into the text: the words after it are read from the new text
        self.use_snapshots(snapshot_text(aliases=[("ls", "'ls -G'")]))
        r = self.ok("for f in $(ls src); do rm $f; done; echo $(ls x) b; rm \"$(ls y)\"c")
        self.assertEqual(len(self.by_prog(r, "rm")), 2)
        self.assertEqual([len(c.words) for c in self.by_prog(r, "echo")], [3])

    def test_review7_forms(self):
        # conf M-1: the pattern after `==` / `=` / `!=` is one word (a glob group with `|` and blanks in it)
        for cmd in ("[[ a == (a|b) ]]; rm a", "[[ $x != (a | b)* ]] && rm a", "if [[ $x = (#b)(*)-(*) ]]; then rm a; fi",
                    "[[ a == a && (b == (b|c)) ]] && rm a"):
            self.assertEqual(len(self.by_prog(self.ok(cmd), "rm")), 1, cmd)
        for cmd in ("[[ a == (a|b)|c ]]; rm a", "[[ a == (a|b ]]; rm a"):  # zsh's parse errors
            self.assertEqual(self.scan(cmd).status, "unparsable", cmd)
        # a lone `;` where a command is expected is an empty command (zsh 5.9); `;;` outside `case` is not
        for cmd in ("rm a &;", "true; ; rm a", "; rm a", "for i in x; do; rm a; done", "true &&; rm a", "{ ; rm a; }"):
            self.assertEqual(len(self.by_prog(self.ok(cmd), "rm")), 1, cmd)
        self.assertEqual(self.scan("true;; rm a").status, "unparsable")
        # R3: several loop names
        r = self.ok("for i j in x y; do rm $i $j; done")
        self.assertEqual(len(self.by_prog(r, "rm")), 1)

    def test_review9_forms(self):
        # B2: `$'…'` (with `\'`), `${(s:(:)X}` and `$(…)` with quotes are whole units in a case pattern and in parens
        for cmd in ("case x in ($'\\'') ;; esac; rm a", "case x in (${(s:(:)X}) ;; esac; rm a",
                    "case x in $'\\'') ;; esac; rm a", "case x in ($(print $'a\\'b'; true\n)) ;; esac; rm a",
                    "a=($'\\'' b); rm a", "echo \"$(echo \")\")\"; rm a"):
            self.assertEqual(len(self.by_prog(self.ok(cmd), "rm")), 1, cmd)
        # s7#11: `$~1`, `$=1`, `$~@` are pattern expansions of positional parameters, not the text `$~1`
        r = self.ok("ls $~1 $=2 $~@")
        self.assertEqual([w.value for w in self.by_prog(r, "ls")[0].words[1:]], [None, None, None])

    def test_review8_forms(self):
        # M1: `time`, `!` and `coproc` with no command; the `;|` branch end; zsh's clobber / stderr redirections
        for cmd in ("time; rm a", "time | cat; rm a", "time && rm a", "! ; rm a", "coproc ; rm a", "time\nrm a",
                    "time ! ; rm a", "case x in (x) print;| (y) rm a;; esac", "print a &>|/dev/null; rm a"):
            self.assertEqual(len(self.by_prog(self.ok(cmd), "rm")), 1, cmd)
        r = self.ok("print x >>&| f; print x >&| f; print x &>>! f; print x >>& f; print x &>! f; print x >&2")
        self.assertEqual([(x.op, x.mode) for c in r.commands for x in c.redirs],
                         [(">>&|", "append"), (">&|", "write"), ("&>>!", "append"), (">>&", "append"), ("&>!", "write"),
                          (">&", "dup")])
        # conf m-1, m-2: case patterns as zsh 5.9 reads them (glob groups, an optional opener); the bodies are commands
        for cmd in ("case $x in (#i)abc) rm a;; esac", "case $f in *.(ts|tsx)) rm a;; esac",
                    "case $f in (*.(ts|tsx)) rm a;; esac", "case a in (a|b)) rm a;; esac", "case a in ((a|b)) rm a;; esac",
                    "case 'a b' in (a b) rm a;; esac", "case ab in (a)b) rm a;; esac", "case x in (x|y)|z) rm a;; esac",
                    "case x in ( x ) rm a;; esac", "case 5 in <1-9>) rm a;; esac", "case a in a | b ) rm a;; esac",
                    "case $(echo x) in $(echo y)) rm a;; esac", "case a in a) rm a\nesac"):
            self.assertEqual(len(self.by_prog(self.ok(cmd), "rm")), 1, cmd)
        self.assertEqual(len(self.by_prog(self.ok("case $(rm a) in $(rm b)) :;; esac"), "rm")), 2)
        self.assertEqual(self.scan("case x in [x)]) rm a;; esac").status, "unparsable")  # zsh's parse error too
        # B1: a numeric glob is part of a word; other `<` are redirections
        r = self.ok("rm -rf studi[o<->] 2<-> {a}<-> <5-> x<-9>y < in")
        self.assertEqual(r.commands[0].argv, ["rm", "-rf", "studi[o<->]", "2<->", "{a}<->", "<5->", "x<-9>y"])
        self.assertEqual([(x.op, x.mode) for x in r.commands[0].redirs], [("<", "read")])
        self.assertTrue(all(w.glob for w in r.commands[0].words[2:]))
        r = self.ok("cat <in <1-2>")
        self.assertEqual(r.commands[0].argv, ["cat", "<1-2>"])

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
