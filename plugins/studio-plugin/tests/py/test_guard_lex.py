"""M0d-1a lexer: quoting, escapes, comments, operators, heredocs (m0d1a-plan §10.2, §10.3)."""

from guard_base import GuardCase


class Quoting(GuardCase):
    def argv(self, command):
        r = self.ok(command)
        return [c.argv for c in r.commands]

    def test_single_quotes_are_literal(self):
        self.assertEqual(self.argv("echo 'a;b && c | d $(x) `y` # z \\ q'"),
                         [["echo", "a;b && c | d $(x) `y` # z \\ q"]])
        self.assertEqual(self.argv("echo 'line1\nline2'"), [["echo", "line1\nline2"]])

    def test_double_quote_escapes(self):
        self.assertEqual(self.argv('echo "a\\"b \\$x \\` \\\\ \\a"'), [["echo", 'a"b $x ` \\ \\a']])
        self.assertEqual(self.argv('echo "ab\\\ncd"'), [["echo", "abcd"]])

    def test_double_quote_expansions_are_commands(self):
        r = self.ok('echo "x $(rm studio/a) `touch b`"')
        self.assertEqual(sorted(c.prog for c in r.commands), ["echo", "rm", "touch"])
        self.assertIsNone(self.one(r, "echo").argv[1])

    def test_ansi_c(self):
        self.assertEqual(self.argv("echo $'a\\tb\\n\\x41\\101\\'\\\\\\e'"), [["echo", "a\tb\nAA'\\\x1b"]])
        self.assertEqual(self.argv("rm $'studio\\x2flocal'"), [["rm", "studio/local"]])
        r = self.ok("$'\\x72m' x")
        self.assertEqual(r.commands[0].prog, "rm")
        self.assertEqual(self.argv('echo $"loc $HOME"'), [["echo", "loc " + self.env["HOME"]]])
        # zsh: unknown escapes (and \c) drop the backslash; locale-dependent ones are dynamic
        self.assertEqual(self.argv("echo $'\\c@x|\\cA|\\q'"), [["echo", "c@x|cA|q"]])
        self.assertEqual(self.argv("echo $'\\u00e9' $'\\x' $'\\u0041'"), [["echo", None, None, "A"]])

    def test_concatenation_and_empty_args(self):
        self.assertEqual(self.argv("echo a'b'\"c\"$'d' '' \"\""), [["echo", "abcd", "", ""]])

    def test_line_continuation(self):
        self.assertEqual(self.argv("echo a \\\n b"), [["echo", "a", "b"]])
        self.assertEqual(self.argv("ec\\\nho x"), [["echo", "x"]])
        self.assertEqual(self.argv("echo 'a\\\nb'"), [["echo", "a\\\nb"]])

    def test_comments(self):
        self.assertEqual(self.argv("echo a # c\nrm b"), [["echo", "a"], ["rm", "b"]])
        self.assertEqual(self.argv("echo a#b ${#x}"), [["echo", "a#b", None]])
        # a quote inside a comment is not a quote
        self.assertEqual(self.argv("echo a # don't\nrm studio/x"), [["echo", "a"], ["rm", "studio/x"]])
        self.assertEqual(self.argv("echo '#x' \"#y\""), [["echo", "#x", "#y"]])

    def test_operators_without_spaces(self):
        self.assertEqual(self.argv("echo a&&rm b"), [["echo", "a"], ["rm", "b"]])
        self.assertEqual(self.argv("echo a|grep b;ls"), [["echo", "a"], ["grep", "b"], ["ls"]])
        self.assertEqual(self.argv("echo a |& cat"), [["echo", "a"], ["cat"]])

    def test_quoted_and_escaped_operators(self):
        self.assertEqual(self.argv('echo "a && b"'), [["echo", "a && b"]])
        self.assertEqual(self.argv("echo a\\;b a\\|b 'x;y'"), [["echo", "a;b", "a|b", "x;y"]])

    def test_redirections(self):
        r = self.ok("cmd 2>&1 &>out1 &>>out2 >|out3 <>rw 1>/dev/null >&2 {fd}>f4 3<&0 >&- >out5 <in")
        modes = [(x.op, x.mode) for x in r.commands[0].redirs]
        self.assertEqual(modes, [(">&", "dup"), ("&>", "write"), ("&>>", "append"), (">|", "write"), ("<>", "rw"),
                                 (">", "write"), (">&", "dup"), (">", "write"), ("<&", "dup"), (">&", "close"),
                                 (">", "write"), ("<", "read")])
        r = self.ok(">out cmd arg")
        self.assertEqual(r.commands[0].argv, ["cmd", "arg"])

    def test_unicode_and_odd_blanks(self):
        nbsp, ideo = " ", "　"
        self.assertEqual(self.argv("rm 스튜디오/파일 🎬"), [["rm", "스튜디오/파일", "🎬"]])
        self.assertEqual(self.argv("echo a%sb c%sd e\rf" % (nbsp, ideo)), [["echo", "a%sb" % nbsp, "c%sd" % ideo, "e\rf"]])
        self.assertEqual(self.argv("echo a；b"), [["echo", "a；b"]])
        nfd = "한"  # 한 in NFD
        self.assertEqual(self.argv("rm %s" % nfd), [["rm", nfd]])

    def test_nul_and_trailing_backslash(self):
        r = self.scan("echo a\x00b")
        self.assertEqual(r.status, "unparsable")
        self.assertEqual(self.argv("echo a\\"), [["echo", "a"]])  # zsh drops it


class Heredocs(GuardCase):
    def test_expanding_heredoc_runs_substitutions(self):
        r = self.ok("cat <<EOF > out\nhi $(pwd) $(rm studio/a)\nEOF\n")
        self.assertTrue(self.by_prog(r, "rm"))
        cat = self.one(r, "cat")
        h = [x for x in cat.redirs if x.mode == "heredoc"][0]
        self.assertTrue(h.body_dynamic)
        self.assertIn(self.root, h.body)

    def test_quoted_delimiters_do_not_expand(self):
        for d in ("'EOF'", '"EOF"', "\\EOF", 'E"O"F'):
            r = self.ok("cat <<%s\n$(rm x)\nEOF\n" % d)
            self.assertEqual([c.prog for c in r.commands], ["cat"], d)
            self.assertEqual(r.commands[0].redirs[0].body, "$(rm x)\n")

    def test_strip_tabs(self):
        r = self.ok("cat <<-EOF\n\t\tx\n\tEOF\n")
        self.assertEqual(r.commands[0].redirs[0].body, "x\n")

    def test_two_heredocs_one_line(self):
        r = self.ok("cat <<A <<B\n1\nA\n2\nB\nrm z")
        self.assertEqual([x.body for x in r.commands[0].redirs], ["1\n", "2\n"])
        self.assertTrue(self.by_prog(r, "rm"))

    def test_terminator_rules(self):
        r = self.ok("cat <<EOF\nx\nEOF \nEOF\n")
        self.assertEqual(r.commands[0].redirs[0].body, "x\nEOF \n")
        r = self.ok("cat <<EOF\nnever ends\n")
        self.assertIn("heredoc-unterminated", r.notes)
        self.assertEqual(r.commands[0].redirs[0].body, "never ends\n")

    def test_heredoc_then_and_on_same_line(self):
        r = self.ok("cat <<'EOF' > /tmp/s.sh && bash /tmp/s.sh\nrm -rf studio/local\nEOF\n")
        op = [o for o in r.opaque if o.kind == "script"][0]
        self.assertEqual(op.origin, "linked-heredoc")
        self.assertEqual([h.term for h in op.hits], ["studio"])

    def test_heredoc_to_interpreters(self):
        for cmd in ("python3 - <<'EOF'\nimport os\nEOF\n", "python3 <<EOF\nx\nEOF\n", "bash <<EOF\nls\nEOF\n",
                    "node <<EOF\n1\nEOF\n"):
            r = self.ok(cmd)
            self.assertEqual(self.kinds(r), ["heredoc-interp"], cmd)
            self.assertEqual(r.opaque[0].hits, [])

    def test_heredoc_piped_to_interpreter(self):
        r = self.ok("cat <<'EOF' | python3\nopen('studio/work/state.json','w')\nEOF\n")
        op = [o for o in r.opaque if o.kind == "stdin-interp"][0]
        self.assertEqual(op.origin, "pipe-literal")
        self.assertEqual(sorted(h.term for h in op.hits), ["state.json", "studio"])

    def test_herestrings(self):
        r = self.ok('bash <<< "rm studio/x"')
        self.assertEqual(self.kinds(r), ["herestring-interp"])
        self.assertEqual([h.term for h in r.opaque[0].hits], ["studio"])
        r = self.ok('python3 <<< "print(1)"')
        self.assertEqual(self.kinds(r), ["herestring-interp"])
        r = self.ok('grep x <<< "$y"')
        self.assertEqual(r.opaque, [])

    def test_heredoc_inside_substitution(self):
        r = self.ok("x=$(cat <<EOF\nhello\nEOF\n)\necho $x")
        self.assertTrue(self.by_prog(r, "cat"))
        self.assertEqual(self.by_prog(r, "cat")[0].redirs[0].body, "hello\n")
